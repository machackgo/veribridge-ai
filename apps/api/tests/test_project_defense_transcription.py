"""
Tests for the Project Defense Audio Transcription Pipeline.

Covers:
- provider=none returns graceful 200 with configured=False (no crash)
- missing OPENAI_API_KEY returns TranscriptionUnavailableError
- successful mock transcription sets transcript_ready status
- transcript_text is saved and retrievable after transcription
- privacy scan runs on generated transcript (sensitive data → flagged)
- manual transcript analysis still works after transcription is added
- project defense analysis still works on a generated transcript
- final verification is NEVER set to 'complete' from this feature
- no project-specific hardcoding (no Boston / React-demo logic)
- transcription endpoint returns 404 when no media is registered
- transcription endpoint returns 404 for unknown session
- re-analyzing with generated transcript works end-to-end
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.project_defense_analysis_service import (
    ProjectDefenseAnalysisService,
)
from app.services.transcription_service import (
    TranscriptionResult,
    TranscriptionUnavailableError,
    transcribe_audio,
)
from app.services.verification_readiness_service import compute_readiness_report

# ── Test identifiers ──────────────────────────────────────────────────────────

DEMO_USER_ID = "00000000-0000-0000-0000-000000000099"
EVIDENCE_ID  = "eeeeeeee-0000-0000-0000-000000000099"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_session(client: TestClient) -> str:
    """Create a proof session in the in-memory store and return its ID."""
    r = client.post(
        "/api/v1/student/extension-proof/sessions",
        json={"skill_evidence_id": EVIDENCE_ID},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _upload_media(client: TestClient, session_id: str, filename: str = "talk.mp3") -> None:
    """Register fake media metadata for a session (no real file bytes needed)."""
    r = client.post(
        f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
        files={"file": (filename, b"fake-audio-bytes", "audio/mpeg")},
    )
    assert r.status_code in (200, 201), r.text


# ── Unit tests: transcription_service ────────────────────────────────────────

class TestTranscriptionServiceUnit:
    """Pure unit tests — no HTTP, no DB.

    We patch the module-level _PROVIDER / _OPENAI_KEY variables directly
    with patch.object rather than reloading the module.  Reloading would
    create new class objects and break exception-class-identity matching in
    the endpoint's 'except TranscriptionUnavailableError' clause.
    """

    def test_provider_none_raises_unavailable(self):
        """Default provider (none) raises TranscriptionUnavailableError — never crashes."""
        import app.services.transcription_service as svc
        with patch.object(svc, "_PROVIDER", "none"):
            with pytest.raises(svc.TranscriptionUnavailableError):
                svc.transcribe_audio(b"audio", "test.mp3")

    def test_empty_provider_raises_unavailable(self):
        """Empty TRANSCRIPTION_PROVIDER also raises TranscriptionUnavailableError."""
        import app.services.transcription_service as svc
        with patch.object(svc, "_PROVIDER", ""):
            with pytest.raises(svc.TranscriptionUnavailableError):
                svc.transcribe_audio(b"audio", "test.webm")

    def test_unknown_provider_raises_unavailable(self):
        """An unrecognised provider name raises TranscriptionUnavailableError."""
        import app.services.transcription_service as svc
        with patch.object(svc, "_PROVIDER", "deepgram"):
            with pytest.raises(svc.TranscriptionUnavailableError):
                svc.transcribe_audio(b"audio", "test.mp4")

    def test_openai_provider_without_key_raises_unavailable(self):
        """OpenAI provider with no API key raises TranscriptionUnavailableError — no crash."""
        import app.services.transcription_service as svc
        with patch.object(svc, "_PROVIDER", "openai"), patch.object(svc, "_OPENAI_KEY", ""):
            with pytest.raises(svc.TranscriptionUnavailableError, match="OPENAI_API_KEY"):
                svc.transcribe_audio(b"audio", "test.mp3")

    def test_transcription_result_dataclass(self):
        """TranscriptionResult holds text and provider."""
        r = TranscriptionResult(transcript_text="I built a REST API.", provider_used="openai")
        assert r.transcript_text == "I built a REST API."
        assert r.provider_used == "openai"

    def test_guess_mime_known_extensions(self):
        """_guess_mime returns correct MIME types for all supported extensions."""
        from app.services.transcription_service import _guess_mime
        assert _guess_mime("talk.mp3") == "audio/mpeg"
        assert _guess_mime("demo.mp4") == "video/mp4"
        assert _guess_mime("clip.mov") == "video/quicktime"
        assert _guess_mime("rec.webm") == "audio/webm"
        assert _guess_mime("voice.wav") == "audio/wav"
        assert _guess_mime("audio.m4a") == "audio/mp4"

    def test_guess_mime_unknown_extension(self):
        """Unknown extensions fall back to application/octet-stream."""
        from app.services.transcription_service import _guess_mime
        assert _guess_mime("file.xyz") == "application/octet-stream"
        assert _guess_mime("noextension") == "application/octet-stream"


# ── Service-layer tests ───────────────────────────────────────────────────────

class TestProjectDefenseTranscriptionService:
    """Tests for ProjectDefenseAnalysisService.save_transcription_result."""

    def test_save_transcription_result_sets_transcript_ready(self):
        """save_transcription_result sets transcription_status = 'transcript_ready'."""
        store: dict = {}
        svc = ProjectDefenseAnalysisService(store)

        # Create a media stub first
        svc.register_media(
            user_id=DEMO_USER_ID,
            proof_session_id="sess-tx-1",
            media_filename="voice.mp3",
            media_type="mp3",
            media_size_bytes=12345,
        )

        row = svc.save_transcription_result(
            user_id=DEMO_USER_ID,
            proof_session_id="sess-tx-1",
            transcript_text="I built a full-stack app using React and FastAPI.",
            privacy_scan_status="clean",
        )

        assert row["transcript_text"] == "I built a full-stack app using React and FastAPI."
        assert row["transcription_status"] == "transcript_ready"
        assert row["transcript_reviewed"] is False
        assert row["privacy_scan_status"] == "clean"

    def test_save_transcription_preserves_media_fields(self):
        """Saving transcript does not overwrite media_filename / media_type."""
        store: dict = {}
        svc = ProjectDefenseAnalysisService(store)
        svc.register_media(
            user_id=DEMO_USER_ID,
            proof_session_id="sess-tx-2",
            media_filename="recording.webm",
            media_type="webm",
            media_size_bytes=50000,
        )
        row = svc.save_transcription_result(
            user_id=DEMO_USER_ID,
            proof_session_id="sess-tx-2",
            transcript_text="I designed the data pipeline.",
        )
        assert row["media_filename"] == "recording.webm"
        assert row["media_type"] == "webm"

    def test_save_transcription_result_new_session(self):
        """save_transcription_result on a new key creates a row."""
        store: dict = {}
        svc = ProjectDefenseAnalysisService(store)
        row = svc.save_transcription_result(
            user_id=DEMO_USER_ID,
            proof_session_id="sess-tx-new",
            transcript_text="Hello world.",
        )
        assert row["transcript_text"] == "Hello world."
        assert row["transcription_status"] == "transcript_ready"


# ── HTTP endpoint tests ───────────────────────────────────────────────────────

class TestTranscribeEndpoint:

    def test_provider_none_returns_200_with_configured_false(self, client: TestClient, mem_store: dict):
        """
        When TRANSCRIPTION_PROVIDER=none, the endpoint returns HTTP 200 with
        configured=False and an instructional message.  It does NOT crash.
        """
        session_id = _make_session(client)
        _upload_media(client, session_id, "talk.mp3")

        with patch(
            "app.services.transcription_service.transcribe_audio",
            side_effect=TranscriptionUnavailableError("not configured"),
        ):
            r = client.post(
                f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
            )

        assert r.status_code == 200, r.text
        data = r.json()
        assert data["configured"] is False
        assert data["transcript_text"] == ""
        assert "not configured" in data["message"].lower() or "paste" in data["message"].lower()

    def test_missing_api_key_returns_200_not_500(self, client: TestClient, mem_store: dict):
        """Missing API key must NOT cause a 5xx — graceful 200 with configured=False."""
        session_id = _make_session(client)
        _upload_media(client, session_id, "voice.webm")

        with patch(
            "app.services.transcription_service.transcribe_audio",
            side_effect=TranscriptionUnavailableError("OPENAI_API_KEY is not set"),
        ):
            r = client.post(
                f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
            )

        assert r.status_code == 200, r.text
        assert r.json()["configured"] is False

    def test_successful_transcription_returns_transcript_text(self, client: TestClient, mem_store: dict):
        """
        Mock a successful OpenAI transcription and verify the endpoint returns
        the transcript text, sets configured=True and status=transcript_ready.
        """
        session_id = _make_session(client)
        _upload_media(client, session_id, "walkthrough.mp3")

        mock_result = TranscriptionResult(
            transcript_text="I built a recommendation engine using collaborative filtering.",
            provider_used="openai",
        )
        with patch(
            "app.services.transcription_service.transcribe_audio",
            return_value=mock_result,
        ):
            r = client.post(
                f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
            )

        assert r.status_code == 200, r.text
        data = r.json()
        assert data["configured"] is True
        assert data["provider_used"] == "openai"
        assert "recommendation engine" in data["transcript_text"]
        assert data["transcription_status"] == "transcript_ready"
        assert data["transcript_reviewed"] is False

    def test_transcript_saved_to_db_after_transcription(self, client: TestClient, mem_store: dict):
        """After transcription succeeds, the transcript is persisted and GET returns it."""
        session_id = _make_session(client)
        _upload_media(client, session_id, "demo.mp3")

        transcript = "I implemented a REST API with JWT authentication and rate limiting."
        mock_result = TranscriptionResult(transcript_text=transcript, provider_used="openai")
        with patch(
            "app.services.transcription_service.transcribe_audio",
            return_value=mock_result,
        ):
            client.post(
                f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
            )

        # Retrieve and check
        svc = ProjectDefenseAnalysisService(mem_store)
        row = svc.get_analysis(DEMO_USER_ID, session_id)
        assert row is not None
        assert row["transcript_text"] == transcript
        assert row["transcription_status"] == "transcript_ready"

    def test_privacy_scan_runs_on_generated_transcript(self, client: TestClient, mem_store: dict):
        """A generated transcript with an API key is flagged by the privacy scan."""
        session_id = _make_session(client)
        _upload_media(client, session_id, "audio.mp3")

        flagged_text = (
            "I built an app. My API key is sk-abc123xyz789supersecretkey and I used it everywhere."
        )
        mock_result = TranscriptionResult(transcript_text=flagged_text, provider_used="openai")
        with patch(
            "app.services.transcription_service.transcribe_audio",
            return_value=mock_result,
        ):
            r = client.post(
                f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
            )

        assert r.status_code == 200, r.text
        # Privacy flag note should appear in message
        assert "privacy" in r.json()["message"].lower()

        # Stored row should have flagged status
        svc = ProjectDefenseAnalysisService(mem_store)
        row = svc.get_analysis(DEMO_USER_ID, session_id)
        assert row is not None
        assert row["privacy_scan_status"] in ("flagged", "redacted")

    def test_transcribe_404_without_registered_media(self, client: TestClient, mem_store: dict):
        """Transcription endpoint returns 404 if no media row exists for the session."""
        session_id = _make_session(client)
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
        )
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "media_not_found"

    def test_transcribe_404_for_unknown_session(self, client: TestClient, mem_store: dict):
        """Transcription endpoint returns 404 for a non-existent session."""
        r = client.post(
            "/api/v1/student/extension-proof/sessions/no-such-session/defense/transcribe"
        )
        assert r.status_code == 404

    def test_manual_transcript_still_works_when_transcription_unavailable(
        self, client: TestClient, mem_store: dict
    ):
        """
        Even if transcription is not configured, the student can still paste a
        transcript and run analysis via POST /analyze/project-defense.
        """
        session_id = _make_session(client)

        manual_transcript = (
            "I built a web scraper using Python and BeautifulSoup. "
            "I designed the data pipeline, implemented retry logic, and added "
            "rate limiting to avoid overloading the target servers. "
            "The scraper writes cleaned data to a SQLite database. "
            "A future improvement would be to add async concurrency."
        )

        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/project-defense",
            json={
                "transcript_text": manual_transcript,
                "claimed_skills": ["Python", "Web Scraping"],
                "proof_objective": "Demonstrate Python web scraping skills",
            },
        )
        assert r.status_code in (200, 201), r.text
        data = r.json()
        assert data["overall_defense_score"] > 0
        assert data["transcription_status"] == "analysis_complete"

    def test_analyze_after_generated_transcript_end_to_end(
        self, client: TestClient, mem_store: dict
    ):
        """
        Full end-to-end: upload media → transcribe (mocked) → analyze.
        Final verification must NOT be set to complete.
        """
        session_id = _make_session(client)
        _upload_media(client, session_id, "defense.mp3")

        generated = (
            "I built a machine learning model to classify customer churn. "
            "I used scikit-learn for training, pandas for feature engineering, "
            "and deployed the model as a FastAPI endpoint. "
            "I handled the full pipeline: data cleaning, training, evaluation, "
            "and serving predictions. A limitation is the model needs retraining "
            "every month. Next I would add automated retraining via Airflow."
        )
        mock_result = TranscriptionResult(transcript_text=generated, provider_used="openai")
        with patch(
            "app.services.transcription_service.transcribe_audio",
            return_value=mock_result,
        ):
            tx_r = client.post(
                f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
            )
        assert tx_r.status_code == 200, tx_r.text

        # Now analyze
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/project-defense",
            json={
                "transcript_text": generated,
                "claimed_skills": ["Python", "Machine Learning", "FastAPI"],
                "proof_objective": "Demonstrate ML deployment skills",
            },
        )
        assert r.status_code in (200, 201), r.text
        data = r.json()
        assert data["overall_defense_score"] >= 30
        assert "Python" in data["skills_mentioned"] or "Machine Learning" in data["skills_mentioned"]

    def test_final_verification_never_complete_from_transcription(
        self, client: TestClient, mem_store: dict
    ):
        """
        Transcription endpoint must never cause final_verification_status to
        become 'complete'.  Only the VeriBridge reviewer step can do that.
        """
        session_id = _make_session(client)
        _upload_media(client, session_id, "talk.mp3")

        mock_result = TranscriptionResult(
            transcript_text="I built and deployed a student portfolio app.",
            provider_used="openai",
        )
        with patch(
            "app.services.transcription_service.transcribe_audio",
            return_value=mock_result,
        ):
            client.post(
                f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
            )

        # Proof session status should not be "completed" just from transcription
        from app.services.extension_proof_service import ExtensionProofSessionService
        svc = ExtensionProofSessionService(mem_store)
        sess = svc._get_row(DEMO_USER_ID, session_id)
        # Status may be "created" or "uploaded_pending_analysis" — never "completed"
        assert sess.get("status") != "completed"
        assert sess.get("final_verification_status") != "complete"

    def test_no_hardcoded_project_names_in_transcription_response(
        self, client: TestClient, mem_store: dict
    ):
        """
        The transcription endpoint must not mention specific project names,
        cities, or domains in its fixed-text response fields.
        """
        session_id = _make_session(client)
        _upload_media(client, session_id, "audio.mp3")

        mock_result = TranscriptionResult(
            transcript_text="This is a generic transcript about a generic project.",
            provider_used="openai",
        )
        with patch(
            "app.services.transcription_service.transcribe_audio",
            return_value=mock_result,
        ):
            r = client.post(
                f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
            )

        assert r.status_code == 200
        body_str = r.text.lower()
        for forbidden in ["boston", "react-demo", "localhost:3000", "todo-app"]:
            assert forbidden not in body_str, f"Found hardcoded string '{forbidden}' in response"

    def test_transcribe_provider_runtime_error_returns_502(
        self, client: TestClient, mem_store: dict
    ):
        """A RuntimeError from the provider (e.g. network failure) returns 502."""
        session_id = _make_session(client)
        _upload_media(client, session_id, "voice.wav")

        with patch(
            "app.services.transcription_service.transcribe_audio",
            side_effect=RuntimeError("OpenAI rate limit reached."),
        ):
            r = client.post(
                f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
            )

        assert r.status_code == 502
        assert r.json()["detail"]["code"] == "transcription_failed"


# ── local_whisper provider tests ──────────────────────────────────────────────

import sys
from unittest.mock import MagicMock


def _make_mock_faster_whisper(segments_text: list[str]) -> MagicMock:
    """
    Build a minimal fake `faster_whisper` module that returns the given
    segment texts when WhisperModel(...).transcribe(...) is called.
    """
    mock_fw = MagicMock()
    mock_segments = []
    for text in segments_text:
        seg = MagicMock()
        seg.text = text
        mock_segments.append(seg)
    mock_model_instance = MagicMock()
    mock_model_instance.transcribe.return_value = (mock_segments, MagicMock())
    mock_fw.WhisperModel.return_value = mock_model_instance
    return mock_fw


class TestLocalWhisperProviderUnit:
    """Unit tests for the local_whisper provider path."""

    def test_local_whisper_missing_dependency_raises_unavailable(self):
        """
        When faster-whisper is not installed, transcribe_audio raises
        TranscriptionUnavailableError with an instructional message.
        """
        import app.services.transcription_service as svc

        # Ensure faster_whisper is absent from sys.modules
        sys.modules.pop("faster_whisper", None)

        with patch.object(svc, "_PROVIDER", "local_whisper"):
            with pytest.raises(svc.TranscriptionUnavailableError, match="faster-whisper"):
                svc.transcribe_audio(b"audio-bytes", "talk.mp3")

    def test_local_whisper_missing_dependency_does_not_crash(self):
        """The missing-dep case must raise, not crash with an AttributeError or ImportError."""
        import app.services.transcription_service as svc
        sys.modules.pop("faster_whisper", None)

        with patch.object(svc, "_PROVIDER", "local_whisper"):
            exc = None
            try:
                svc.transcribe_audio(b"audio-bytes", "talk.wav")
            except svc.TranscriptionUnavailableError as e:
                exc = e
            except Exception as e:
                pytest.fail(f"Expected TranscriptionUnavailableError, got {type(e).__name__}: {e}")
        assert exc is not None

    def test_local_whisper_mocked_success_audio_file(self):
        """
        Mock faster-whisper: successful transcription of an audio file returns
        the concatenated segment text with transcript_ready status.
        """
        import app.services.transcription_service as svc

        mock_fw = _make_mock_faster_whisper([
            "I built a recommendation engine.",
            "It uses collaborative filtering.",
        ])

        with patch.dict(sys.modules, {"faster_whisper": mock_fw}):
            with patch.object(svc, "_PROVIDER", "local_whisper"):
                result = svc.transcribe_audio(b"fake-audio-bytes", "defense.mp3")

        assert result.provider_used == "local_whisper"
        assert "recommendation engine" in result.transcript_text
        assert "collaborative filtering" in result.transcript_text

    def test_local_whisper_mocked_success_webm_file(self):
        """WebM (browser recording format) transcribes correctly — no ffmpeg needed."""
        import app.services.transcription_service as svc

        mock_fw = _make_mock_faster_whisper(["I designed the API layer using FastAPI."])

        with patch.dict(sys.modules, {"faster_whisper": mock_fw}):
            with patch.object(svc, "_PROVIDER", "local_whisper"):
                result = svc.transcribe_audio(b"webm-bytes", "defense-recording-123.webm")

        assert result.provider_used == "local_whisper"
        assert "FastAPI" in result.transcript_text

    def test_local_whisper_video_ffmpeg_missing_raises_unavailable(self):
        """
        When a video file (mp4/mov) is provided and ffmpeg is not installed,
        TranscriptionUnavailableError is raised with an ffmpeg-specific message.
        """
        import app.services.transcription_service as svc
        import subprocess

        mock_fw = _make_mock_faster_whisper(["This text should never be reached."])

        with patch.dict(sys.modules, {"faster_whisper": mock_fw}):
            with patch.object(svc, "_PROVIDER", "local_whisper"):
                with patch("subprocess.run", side_effect=FileNotFoundError("ffmpeg not found")):
                    with pytest.raises(svc.TranscriptionUnavailableError, match="ffmpeg"):
                        svc.transcribe_audio(b"fake-video-bytes", "project-demo.mp4")

    def test_local_whisper_video_mov_ffmpeg_missing_raises_unavailable(self):
        """.mov files also trigger the ffmpeg check."""
        import app.services.transcription_service as svc

        mock_fw = _make_mock_faster_whisper(["Unreachable segment."])

        with patch.dict(sys.modules, {"faster_whisper": mock_fw}):
            with patch.object(svc, "_PROVIDER", "local_whisper"):
                with patch("subprocess.run", side_effect=FileNotFoundError("no ffmpeg")):
                    with pytest.raises(svc.TranscriptionUnavailableError, match="ffmpeg"):
                        svc.transcribe_audio(b"fake-mov-bytes", "walkthrough.mov")

    def test_local_whisper_audio_does_not_need_ffmpeg(self):
        """
        Audio files (mp3/wav/m4a) are passed directly to Whisper.
        subprocess.run should NOT be called — no ffmpeg requirement.
        """
        import app.services.transcription_service as svc

        mock_fw = _make_mock_faster_whisper(["I implemented the machine learning pipeline."])

        with patch.dict(sys.modules, {"faster_whisper": mock_fw}):
            with patch.object(svc, "_PROVIDER", "local_whisper"):
                with patch("subprocess.run", side_effect=AssertionError("subprocess called unexpectedly")) as mock_sp:
                    result = svc.transcribe_audio(b"mp3-audio-bytes", "voice.mp3")

        # subprocess.run must not have been called
        mock_sp.assert_not_called()
        assert result.provider_used == "local_whisper"

    def test_local_whisper_m4a_audio_does_not_need_ffmpeg(self):
        """m4a is an audio container — no ffmpeg needed."""
        import app.services.transcription_service as svc

        mock_fw = _make_mock_faster_whisper(["The data flows from input to output."])

        with patch.dict(sys.modules, {"faster_whisper": mock_fw}):
            with patch.object(svc, "_PROVIDER", "local_whisper"):
                with patch("subprocess.run", side_effect=AssertionError("subprocess called unexpectedly")) as mock_sp:
                    result = svc.transcribe_audio(b"m4a-bytes", "voice.m4a")

        mock_sp.assert_not_called()
        assert "data flows" in result.transcript_text

    def test_local_whisper_empty_result_raises_runtime_error(self):
        """If Whisper returns empty segments, RuntimeError is raised (not a crash)."""
        import app.services.transcription_service as svc

        mock_fw = _make_mock_faster_whisper([])  # no segments → empty transcript

        with patch.dict(sys.modules, {"faster_whisper": mock_fw}):
            with patch.object(svc, "_PROVIDER", "local_whisper"):
                with pytest.raises(RuntimeError, match="empty"):
                    svc.transcribe_audio(b"silent-audio-bytes", "silence.wav")

    def test_local_whisper_model_error_raises_runtime_error(self):
        """If WhisperModel.transcribe raises an exception, RuntimeError is returned."""
        import app.services.transcription_service as svc

        mock_fw = MagicMock()
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = Exception("CUDA out of memory")
        mock_fw.WhisperModel.return_value = mock_model

        with patch.dict(sys.modules, {"faster_whisper": mock_fw}):
            with patch.object(svc, "_PROVIDER", "local_whisper"):
                with pytest.raises(RuntimeError, match="Local Whisper transcription failed"):
                    svc.transcribe_audio(b"audio-bytes", "talk.wav")


class TestCleanTranscript:
    """Unit tests for clean_transcript_for_project_defense()."""

    def test_strips_whitespace(self):
        from app.services.transcription_service import clean_transcript_for_project_defense
        assert clean_transcript_for_project_defense("  hello world  ") == "hello world"

    def test_collapses_spaces(self):
        from app.services.transcription_service import clean_transcript_for_project_defense
        assert clean_transcript_for_project_defense("I   built   an   API") == "I built an API"

    def test_collapses_excess_newlines(self):
        from app.services.transcription_service import clean_transcript_for_project_defense
        result = clean_transcript_for_project_defense("line one\n\n\n\nline two")
        assert result == "line one\n\nline two"

    def test_normalizes_ellipsis(self):
        from app.services.transcription_service import clean_transcript_for_project_defense
        assert clean_transcript_for_project_defense("So....it worked") == "So…it worked"

    def test_adds_space_after_sentence(self):
        from app.services.transcription_service import clean_transcript_for_project_defense
        result = clean_transcript_for_project_defense("I built it.Then I deployed it.")
        assert "it. Then" in result

    def test_empty_string_returns_empty(self):
        from app.services.transcription_service import clean_transcript_for_project_defense
        assert clean_transcript_for_project_defense("") == ""
        assert clean_transcript_for_project_defense("   ") == ""

    def test_does_not_modify_technical_terms(self):
        """Technical terms must be preserved exactly — no hallucination."""
        from app.services.transcription_service import clean_transcript_for_project_defense
        text = "I used FastAPI, PostgreSQL, and scikit-learn."
        result = clean_transcript_for_project_defense(text)
        assert "FastAPI" in result
        assert "PostgreSQL" in result
        assert "scikit-learn" in result

    def test_claimed_skills_param_accepted(self):
        """claimed_skills parameter is accepted (future API) without affecting output."""
        from app.services.transcription_service import clean_transcript_for_project_defense
        text = "I implemented JWT authentication."
        result = clean_transcript_for_project_defense(text, claimed_skills=["JWT", "FastAPI"])
        assert result == "I implemented JWT authentication."


class TestLocalWhisperEndpointIntegration:
    """Integration tests: local_whisper provider via the HTTP endpoint."""

    def test_local_whisper_unavailable_returns_200_configured_false(
        self, client: TestClient, mem_store: dict
    ):
        """
        When local_whisper is not installed, the endpoint returns HTTP 200
        with configured=False — identical graceful fallback to provider=none.
        """
        session_id = _make_session(client)
        _upload_media(client, session_id, "talk.mp3")

        sys.modules.pop("faster_whisper", None)

        with patch(
            "app.services.transcription_service.transcribe_audio",
            side_effect=TranscriptionUnavailableError("Local Whisper transcription is not installed."),
        ):
            r = client.post(
                f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
            )

        assert r.status_code == 200, r.text
        data = r.json()
        assert data["configured"] is False
        assert "transcription" in data["message"].lower() or "paste" in data["message"].lower()

    def test_local_whisper_success_populates_transcript_ready(
        self, client: TestClient, mem_store: dict
    ):
        """
        Successful local_whisper transcription: endpoint returns configured=True,
        transcript_text, and the DB row is set to transcript_ready.
        """
        session_id = _make_session(client)
        _upload_media(client, session_id, "voice.wav")

        mock_result = TranscriptionResult(
            transcript_text="I built a data pipeline with Apache Airflow and dbt.",
            provider_used="local_whisper",
        )
        with patch(
            "app.services.transcription_service.transcribe_audio",
            return_value=mock_result,
        ):
            r = client.post(
                f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
            )

        assert r.status_code == 200, r.text
        data = r.json()
        assert data["configured"] is True
        assert data["provider_used"] == "local_whisper"
        assert "Airflow" in data["transcript_text"]
        assert data["transcription_status"] == "transcript_ready"

    def test_local_whisper_ffmpeg_missing_returns_200_configured_false(
        self, client: TestClient, mem_store: dict
    ):
        """
        Missing ffmpeg for a video file returns graceful 200 with configured=False,
        not a 5xx error.
        """
        session_id = _make_session(client)
        _upload_media(client, session_id, "walkthrough.mp4")

        with patch(
            "app.services.transcription_service.transcribe_audio",
            side_effect=TranscriptionUnavailableError(
                "Video transcription requires ffmpeg."
            ),
        ):
            r = client.post(
                f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
            )

        assert r.status_code == 200, r.text
        assert r.json()["configured"] is False

    def test_local_whisper_then_analyze_end_to_end(
        self, client: TestClient, mem_store: dict
    ):
        """
        End-to-end: upload → local_whisper transcribe (mocked) → analyze.
        Final verification must NOT be set to complete.
        """
        session_id = _make_session(client)
        _upload_media(client, session_id, "talk.mp3")

        generated = (
            "I built a real-time dashboard using React and WebSockets. "
            "I implemented the backend with FastAPI and PostgreSQL. "
            "I handled authentication with JWT and designed the database schema. "
            "A limitation is that the WebSocket server does not yet scale horizontally. "
            "I would add Redis pub/sub for the next iteration."
        )
        mock_result = TranscriptionResult(transcript_text=generated, provider_used="local_whisper")
        with patch(
            "app.services.transcription_service.transcribe_audio",
            return_value=mock_result,
        ):
            tx_r = client.post(
                f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
            )
        assert tx_r.status_code == 200, tx_r.text

        analyze_r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/project-defense",
            json={
                "transcript_text": generated,
                "claimed_skills": ["React", "FastAPI", "PostgreSQL", "WebSockets"],
                "proof_objective": "Demonstrate full-stack real-time app skills",
            },
        )
        assert analyze_r.status_code in (200, 201), analyze_r.text
        data = analyze_r.json()
        assert data["overall_defense_score"] >= 30
        assert data["transcription_status"] == "analysis_complete"

        # Final verification must NOT be 'complete' from this feature
        from app.services.extension_proof_service import ExtensionProofSessionService
        sess = ExtensionProofSessionService(mem_store)._get_row(DEMO_USER_ID, session_id)
        assert sess.get("final_verification_status") != "complete"
        assert sess.get("status") != "completed"

    def test_no_hardcoded_project_names_in_local_whisper_response(
        self, client: TestClient, mem_store: dict
    ):
        """Response fields must not contain hardcoded project names or domains."""
        session_id = _make_session(client)
        _upload_media(client, session_id, "audio.wav")

        mock_result = TranscriptionResult(
            transcript_text="Generic project transcript.",
            provider_used="local_whisper",
        )
        with patch(
            "app.services.transcription_service.transcribe_audio",
            return_value=mock_result,
        ):
            r = client.post(
                f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
            )

        body = r.text.lower()
        for forbidden in ["boston", "react-demo", "localhost:3000", "todo-app"]:
            assert forbidden not in body, f"Hardcoded string '{forbidden}' in response"
