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

from unittest.mock import MagicMock, patch

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
    TranscriptSegment,
    transcribe_audio,
)
from app.services.verification_readiness_service import compute_readiness_report

from tests.conftest import seed_skill_evidence

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
    # Session creation fail-closes on unowned skill_evidence_id (G6).
    seed_skill_evidence(mem_store, DEMO_USER_ID, EVIDENCE_ID)
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

        Using patch.dict(sys.modules, {"faster_whisper": None}) forces the
        import inside the service to raise ImportError regardless of whether
        the package is actually installed in the current environment.
        """
        import app.services.transcription_service as svc

        with patch.dict(sys.modules, {"faster_whisper": None}):
            with patch.object(svc, "_PROVIDER", "local_whisper"):
                with pytest.raises(svc.TranscriptionUnavailableError, match="faster-whisper"):
                    svc.transcribe_audio(b"audio-bytes", "talk.mp3")

    def test_local_whisper_missing_dependency_does_not_crash(self):
        """The missing-dep case must raise, not crash with an AttributeError or ImportError."""
        import app.services.transcription_service as svc

        with patch.dict(sys.modules, {"faster_whisper": None}):
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

    def test_local_whisper_forces_configured_language(self):
        """
        For the MVP the configured language (default 'en') is forced — Whisper's
        auto-detection is bypassed so short/quiet clips never misfire to obscure
        low-confidence languages (e.g. 'nn'). The forced language is passed to
        model.transcribe() and reported back on the result.
        """
        import app.services.transcription_service as svc

        mock_fw = _make_mock_faster_whisper(["I built a data pipeline."])
        # Give the info object a bogus auto-detected language to prove it is NOT used.
        mock_fw.WhisperModel.return_value.transcribe.return_value = (
            mock_fw.WhisperModel.return_value.transcribe.return_value[0],
            MagicMock(language="nn"),
        )

        with patch.dict(sys.modules, {"faster_whisper": mock_fw}):
            with patch.object(svc, "_PROVIDER", "local_whisper"), \
                 patch.object(svc, "_LOCAL_WHISPER_LANGUAGE", "en"):
                result = svc.transcribe_audio(b"quiet-audio-bytes", "defense.webm")

        # The forced language is what gets sent to Whisper AND reported back —
        # never the low-confidence auto-detected 'nn'.
        _args, kwargs = mock_fw.WhisperModel.return_value.transcribe.call_args
        assert kwargs.get("language") == "en"
        assert result.language == "en"

    def test_local_whisper_auto_detects_when_language_unset(self):
        """
        Setting LOCAL_WHISPER_LANGUAGE="" restores Whisper auto-detection:
        language=None is passed to transcribe() and the detected language is used.
        """
        import app.services.transcription_service as svc

        mock_fw = _make_mock_faster_whisper(["Segment text."])
        mock_fw.WhisperModel.return_value.transcribe.return_value = (
            mock_fw.WhisperModel.return_value.transcribe.return_value[0],
            MagicMock(language="es"),
        )

        with patch.dict(sys.modules, {"faster_whisper": mock_fw}):
            with patch.object(svc, "_PROVIDER", "local_whisper"), \
                 patch.object(svc, "_LOCAL_WHISPER_LANGUAGE", ""):
                result = svc.transcribe_audio(b"audio-bytes", "clip.webm")

        _args, kwargs = mock_fw.WhisperModel.return_value.transcribe.call_args
        assert kwargs.get("language") is None
        assert result.language == "es"

    def test_local_whisper_passes_anti_hallucination_decoding_config(self):
        """The env-driven anti-hallucination decoding config is forwarded to
        faster-whisper: VAD on, condition_on_previous_text off, temperature 0, and
        the confidence/compression thresholds — this is what stops the "new new
        new …" repeated-token loop at the source."""
        import app.services.transcription_service as svc

        mock_fw = _make_mock_faster_whisper(["I built a data pipeline."])

        with patch.dict(sys.modules, {"faster_whisper": mock_fw}):
            with patch.object(svc, "_PROVIDER", "local_whisper"), \
                 patch.object(svc, "_LOCAL_WHISPER_VAD", True), \
                 patch.object(svc, "_LOCAL_WHISPER_CONDITION_ON_PREVIOUS_TEXT", False), \
                 patch.object(svc, "_LOCAL_WHISPER_TEMPERATURE", 0.0), \
                 patch.object(svc, "_LOCAL_WHISPER_BEAM_SIZE", 5), \
                 patch.object(svc, "_LOCAL_WHISPER_NO_SPEECH_THRESHOLD", 0.6), \
                 patch.object(svc, "_LOCAL_WHISPER_COMPRESSION_RATIO_THRESHOLD", 2.4), \
                 patch.object(svc, "_LOCAL_WHISPER_LOG_PROB_THRESHOLD", -1.0):
                svc.transcribe_audio(b"audio-bytes", "defense.webm")

        _args, kwargs = mock_fw.WhisperModel.return_value.transcribe.call_args
        assert kwargs.get("vad_filter") is True
        assert kwargs.get("condition_on_previous_text") is False
        assert kwargs.get("temperature") == 0.0
        assert kwargs.get("beam_size") == 5
        assert kwargs.get("no_speech_threshold") == 0.6
        assert kwargs.get("compression_ratio_threshold") == 2.4
        assert kwargs.get("log_prob_threshold") == -1.0

    def test_stt_config_reads_provider_and_model_from_settings(self):
        """Provider/model/decoding config comes from Settings (env-driven), not
        hardcoded — so LOCAL_WHISPER_* / TRANSCRIPTION_PROVIDER select them."""
        import app.services.transcription_service as svc
        from app.core.config import settings

        assert svc._LOCAL_WHISPER_MODEL_SIZE == settings.local_whisper_model_size.strip()
        assert svc._LOCAL_WHISPER_DEVICE == settings.local_whisper_device.strip()
        assert svc._LOCAL_WHISPER_VAD == settings.local_whisper_vad
        assert (
            svc._LOCAL_WHISPER_CONDITION_ON_PREVIOUS_TEXT
            == settings.local_whisper_condition_on_previous_text
        )
        # The field default (used when no env override is present) is the
        # recommended MVP model.
        assert (
            type(settings).model_fields["local_whisper_model_size"].default
            == "large-v3-turbo"
        )


class TestMediaClassificationAndNormalization:
    """Content-type-first media classification + video/webm normalization.

    Root cause these cover: VBR Project Defense records a combined screen+mic
    ``video/webm`` (VP8/VP9 + Opus). Before this fix a bare ``.webm`` was mapped
    to audio and handed straight to faster-whisper, which crashed on the video
    container. Now the caller's content_type routes video/webm through ffmpeg
    audio extraction to clean 16 kHz mono WAV, while audio/webm (Extension Proof
    microphone recordings) is still decoded directly.
    """

    def test_is_video_input_classifier(self):
        from app.services.transcription_service import _is_video_input

        # content_type wins and disambiguates .webm
        assert _is_video_input("full.webm", "video/webm") is True
        assert _is_video_input("rec.webm", "audio/webm") is False
        assert _is_video_input("demo.mp4", "video/mp4") is True
        assert _is_video_input("clip.mov", "video/quicktime") is True
        # No content_type → conservative extension fallback
        assert _is_video_input("demo.mp4", None) is True
        assert _is_video_input("clip.mov", None) is True
        # Bare .webm with no content_type stays audio (Extension Proof default)
        assert _is_video_input("recording.webm", None) is False
        assert _is_video_input("voice.mp3", None) is False
        assert _is_video_input("voice.wav", None) is False

    def test_transcribe_audio_forwards_content_type_to_local_whisper(self):
        """transcribe_audio must forward content_type to the local provider."""
        import app.services.transcription_service as svc

        captured: dict = {}

        def _spy(file_bytes, filename, content_type=None):
            captured["content_type"] = content_type
            return TranscriptionResult(transcript_text="ok", provider_used="local_whisper")

        with patch.object(svc, "_PROVIDER", "local_whisper"), \
             patch.object(svc, "_transcribe_local_whisper", _spy):
            svc.transcribe_audio(b"bytes", "full.webm", content_type="video/webm")

        assert captured["content_type"] == "video/webm"

    def test_video_webm_triggers_ffmpeg_extraction_to_wav(self):
        """video/webm → ffmpeg extracts + normalizes to 16 kHz mono WAV, and the
        extracted WAV path (not the original webm) is handed to Whisper."""
        import app.services.transcription_service as svc

        mock_fw = _make_mock_faster_whisper(["Candidate explained the architecture."])
        mock_run = MagicMock(return_value=MagicMock(returncode=0, stderr=b""))

        with patch.dict(sys.modules, {"faster_whisper": mock_fw}), \
             patch.object(svc, "_PROVIDER", "local_whisper"), \
             patch("subprocess.run", mock_run):
            result = svc.transcribe_audio(
                b"fake-video-webm-bytes", "full.webm", content_type="video/webm"
            )

        assert result.provider_used == "local_whisper"
        assert "architecture" in result.transcript_text

        # ffmpeg was invoked with the expected normalization parameters.
        mock_run.assert_called_once()
        argv = mock_run.call_args[0][0]
        assert argv[0] == "ffmpeg"
        assert "-vn" in argv                 # drop the video stream
        assert "16000" in argv               # 16 kHz (Whisper native)
        assert "1" in argv and "-ac" in argv  # mono
        assert "wav" in argv                 # WAV output

        # Whisper received the extracted WAV, not the raw .webm container.
        whisper_input = mock_fw.WhisperModel.return_value.transcribe.call_args[0][0]
        assert whisper_input.endswith("audio_extracted.wav")

    def test_audio_webm_is_decoded_directly_no_ffmpeg(self):
        """audio/webm (Extension Proof mic recording) must NOT invoke ffmpeg."""
        import app.services.transcription_service as svc

        mock_fw = _make_mock_faster_whisper(["I built the API layer."])

        with patch.dict(sys.modules, {"faster_whisper": mock_fw}), \
             patch.object(svc, "_PROVIDER", "local_whisper"), \
             patch("subprocess.run", side_effect=AssertionError("ffmpeg must not run")) as mock_sp:
            result = svc.transcribe_audio(b"mic-webm", "rec.webm", content_type="audio/webm")

        mock_sp.assert_not_called()
        assert "API layer" in result.transcript_text

    def test_bare_webm_without_content_type_is_conservatively_audio(self):
        """.webm with no content_type stays on the audio path (no ffmpeg) —
        preserves prior Extension Proof behaviour and stays safe."""
        import app.services.transcription_service as svc

        mock_fw = _make_mock_faster_whisper(["Segment."])

        with patch.dict(sys.modules, {"faster_whisper": mock_fw}), \
             patch.object(svc, "_PROVIDER", "local_whisper"), \
             patch("subprocess.run", side_effect=AssertionError("ffmpeg must not run")) as mock_sp:
            svc.transcribe_audio(b"webm", "recording.webm")

        mock_sp.assert_not_called()

    def test_video_webm_missing_ffmpeg_raises_unavailable(self):
        """video/webm with ffmpeg absent → TranscriptionUnavailableError (safe
        fallback), never a raw crash."""
        import app.services.transcription_service as svc

        mock_fw = _make_mock_faster_whisper(["Unreachable."])

        with patch.dict(sys.modules, {"faster_whisper": mock_fw}), \
             patch.object(svc, "_PROVIDER", "local_whisper"), \
             patch("subprocess.run", side_effect=FileNotFoundError("ffmpeg not found")):
            with pytest.raises(svc.TranscriptionUnavailableError, match="ffmpeg"):
                svc.transcribe_audio(b"video-webm", "full.webm", content_type="video/webm")


class TestAudioStreamSummary:
    """Unit tests for the safe ffmpeg audio-stream diagnostic parser.

    This is server-side-only telemetry used to investigate whether a screen+mic
    recording actually carried a microphone/audio track. It must parse only
    booleans/duration and never log the raw stderr (which contains temp paths),
    and it must never raise.
    """

    def test_detects_audio_stream_and_duration(self, caplog):
        import logging

        from app.services.transcription_service import _log_audio_stream_summary

        stderr = (
            b"Input #0, matroska,webm, from '/tmp/whatever/full.webm':\n"
            b"  Duration: 00:00:23.45, start: 0.000000, bitrate: 512 kb/s\n"
            b"  Stream #0:0(eng): Video: vp9, yuv420p, 1280x720\n"
            b"  Stream #0:1(eng): Audio: opus, 48000 Hz, mono, fltp\n"
        )
        with caplog.at_level(logging.INFO):
            _log_audio_stream_summary(stderr)

        assert "audio_stream_detected=True" in caplog.text
        assert "duration_s=23.45" in caplog.text
        # The raw stderr (with the temp path) must never be logged.
        assert "/tmp/whatever/full.webm" not in caplog.text

    def test_reports_missing_audio_stream(self, caplog):
        import logging

        from app.services.transcription_service import _log_audio_stream_summary

        stderr = (
            b"  Duration: 00:00:10.00, start: 0.000000, bitrate: 400 kb/s\n"
            b"  Stream #0:0(eng): Video: vp9, yuv420p, 1280x720\n"
        )
        with caplog.at_level(logging.INFO):
            _log_audio_stream_summary(stderr)

        assert "audio_stream_detected=False" in caplog.text

    def test_never_raises_on_garbage(self):
        from app.services.transcription_service import _log_audio_stream_summary

        # None and non-UTF-8 bytes must not raise.
        _log_audio_stream_summary(None)
        _log_audio_stream_summary(b"\xff\xfe not ffmpeg output")


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

        with patch.dict(sys.modules, {"faster_whisper": None}), patch(
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


# ── Regression tests: register_media media_size_bytes fix ─────────────────────

class TestRegisterMediaFix:
    """
    Regression tests for the 'media_size_bytes causes silent DB failure' bug.

    Root cause: register_media was including media_size_bytes in the Supabase
    upsert dict, but that column does not exist in project_defense_analysis_results.
    The DB exception was caught silently, returning a stub dict, so upload returned
    HTTP 201, but nothing was saved.  The transcription endpoint then queried the
    real DB, found no row, and returned 404 'No media file registered'.

    Fix: media_size_bytes is excluded from the DB upsert dict.  DB failures are
    no longer silently swallowed — they propagate so callers see the failure.
    """

    def test_register_media_db_upsert_excludes_media_size_bytes(self):
        """
        media_size_bytes must NOT appear in the Supabase upsert payload.
        This column does not exist in project_defense_analysis_results and
        would cause the upsert to fail with a column-not-found error.
        """
        mock_client = MagicMock()
        mock_row = {
            "proof_session_id": "sess-rm-fix",
            "media_filename": "talk.mp3",
            "media_type": "mp3",
        }
        (
            mock_client.table.return_value
            .upsert.return_value
            .execute.return_value
        ).data = [mock_row]

        svc = ProjectDefenseAnalysisService(mock_client)
        svc.register_media(
            user_id=DEMO_USER_ID,
            proof_session_id="sess-rm-fix",
            media_filename="talk.mp3",
            media_type="mp3",
            media_size_bytes=99999,
        )

        upsert_call = mock_client.table.return_value.upsert.call_args
        assert upsert_call is not None, "upsert was never called"
        upsert_dict: dict = upsert_call[0][0]
        assert "media_size_bytes" not in upsert_dict, (
            "media_size_bytes must NOT be included in the Supabase upsert — "
            "this column does not exist in project_defense_analysis_results."
        )

    def test_register_media_db_upsert_includes_required_fields(self):
        """
        The DB upsert must include all required media fields (filename, type,
        transcription_status, user_id, proof_session_id) even without media_size_bytes.
        """
        mock_client = MagicMock()
        (
            mock_client.table.return_value
            .upsert.return_value
            .execute.return_value
        ).data = [{"proof_session_id": "sess-rm-fields", "media_filename": "audio.webm"}]

        svc = ProjectDefenseAnalysisService(mock_client)
        svc.register_media(
            user_id=DEMO_USER_ID,
            proof_session_id="sess-rm-fields",
            media_filename="audio.webm",
            media_type="webm",
            media_size_bytes=500,
            media_url="https://example.com/audio.webm",
            media_storage_path="user123/session456/audio.webm",
        )

        upsert_dict: dict = mock_client.table.return_value.upsert.call_args[0][0]
        for required in (
            "user_id", "proof_session_id", "media_filename", "media_type",
            "transcription_status", "media_url", "media_storage_path",
        ):
            assert required in upsert_dict, f"Required field '{required}' missing from upsert"
        assert upsert_dict["transcription_status"] == "uploaded"
        assert upsert_dict["media_filename"] == "audio.webm"

    def test_register_media_db_failure_raises_not_silently_swallows(self):
        """
        A DB exception in register_media must propagate — not be silently caught and
        replaced with stub data.  If we silently swallow, upload returns 201 but no
        row is in DB, and transcription later returns 404.
        """
        mock_client = MagicMock()
        (
            mock_client.table.return_value
            .upsert.return_value
            .execute
        ).side_effect = Exception("column 'media_size_bytes' does not exist")

        svc = ProjectDefenseAnalysisService(mock_client)
        with pytest.raises(Exception, match="does not exist"):
            svc.register_media(
                user_id=DEMO_USER_ID,
                proof_session_id="sess-rm-raise",
                media_filename="audio.mp3",
                media_type="mp3",
                media_size_bytes=100,
            )

    def test_register_media_empty_upsert_response_raises_runtime_error(self):
        """
        If the Supabase upsert succeeds but returns no rows (empty data list),
        RuntimeError is raised with a descriptive message — not a silent return
        of stub data that hides the DB problem.
        """
        mock_client = MagicMock()
        (
            mock_client.table.return_value
            .upsert.return_value
            .execute.return_value
        ).data = []  # upsert succeeded but returned nothing

        svc = ProjectDefenseAnalysisService(mock_client)
        with pytest.raises(RuntimeError, match="upsert returned no rows"):
            svc.register_media(
                user_id=DEMO_USER_ID,
                proof_session_id="sess-rm-empty",
                media_filename="audio.mp3",
                media_type="mp3",
                media_size_bytes=100,
            )

    def test_register_media_returns_response_with_media_size_bytes(self):
        """
        Even though media_size_bytes is excluded from the DB upsert,
        the returned dict from register_media still contains it (for the caller).
        """
        store: dict = {}
        svc = ProjectDefenseAnalysisService(store)
        row = svc.register_media(
            user_id=DEMO_USER_ID,
            proof_session_id="sess-rm-resp",
            media_filename="voice.mp3",
            media_type="mp3",
            media_size_bytes=42000,
        )
        # media_size_bytes is in the returned row (for API response), even though
        # it's not in the DB upsert
        assert row["media_size_bytes"] == 42000
        assert row["media_filename"] == "voice.mp3"

    def test_transcribe_does_not_return_404_after_upload(
        self, client: TestClient, mem_store: dict
    ):
        """
        Core regression: after uploading media, the transcription endpoint must
        NOT return 404 'No media file registered'.
        This test would have FAILED before the media_size_bytes fix.
        """
        session_id = _make_session(client)
        # Simulate what the record tab does: upload a webm blob
        upload_r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
            files={"file": ("recording.webm", b"fake-webm-audio-bytes", "audio/webm")},
        )
        assert upload_r.status_code in (200, 201), f"Upload failed: {upload_r.text}"
        assert "media_filename" in upload_r.json()

        # Now transcribe — must NOT be 404
        with patch(
            "app.services.transcription_service.transcribe_audio",
            side_effect=TranscriptionUnavailableError("not configured"),
        ):
            tx_r = client.post(
                f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
            )

        assert tx_r.status_code != 404, (
            "Transcription returned 404 'No media file registered' even though "
            "media was uploaded. This is the register_media bug — check that "
            "media_size_bytes is excluded from the Supabase upsert."
        )
        assert tx_r.status_code == 200, tx_r.text
        assert tx_r.json()["configured"] is False  # graceful fallback, not error

    def test_transcribe_does_not_return_404_after_mp3_upload(
        self, client: TestClient, mem_store: dict
    ):
        """mp3 file upload (Upload tab) also registers correctly and doesn't 404 on transcribe."""
        session_id = _make_session(client)
        upload_r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
            files={"file": ("presentation.mp3", b"fake-mp3-bytes", "audio/mpeg")},
        )
        assert upload_r.status_code in (200, 201), f"Upload failed: {upload_r.text}"

        with patch(
            "app.services.transcription_service.transcribe_audio",
            return_value=TranscriptionResult(
                transcript_text="I built a full-stack app.", provider_used="openai"
            ),
        ):
            tx_r = client.post(
                f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
            )

        assert tx_r.status_code == 200, tx_r.text
        assert tx_r.json()["configured"] is True
        assert "full-stack" in tx_r.json()["transcript_text"]


# ── Storage upload tests ───────────────────────────────────────────────────────

# A minimal non-dict client that supports both session lookup (via .table()) and
# storage (.storage).  We use it to exercise the real storage upload code path
# without a live Supabase connection.

class _FakeTableQuery:
    """Very thin fluent query builder backed by an in-memory dict."""
    def __init__(self, store: dict, name: str):
        self._store = store
        self._name = name
        self._filters: dict = {}
        self._upsert_data: dict | None = None
        self._conflict: str | None = None

    def select(self, *_):
        return self

    def eq(self, field: str, value):
        self._filters[field] = value
        return self

    def maybe_single(self):
        return self

    def upsert(self, data: dict, **kwargs):
        self._upsert_data = data
        self._conflict = kwargs.get("on_conflict", "")
        return self

    def execute(self):
        tbl = self._store.setdefault(self._name, {})
        if self._upsert_data is not None:
            key = self._upsert_data.get(self._conflict) if self._conflict else None
            if key:
                row = {**tbl.get(key, {}), **self._upsert_data}
                tbl[key] = row
                return type("R", (), {"data": [row]})()
            return type("R", (), {"data": []})()
        # select
        for row in tbl.values():
            if all(row.get(k) == v for k, v in self._filters.items()):
                return type("R", (), {"data": row})()
        return type("R", (), {"data": None})()


class _FakeSupabaseWithStorage:
    """
    Non-dict Supabase-like client for storage tests.
    - NOT a dict → the endpoint's storage upload block runs.
    - .table() delegates to the in-memory store.
    - .storage is a configurable MagicMock.
    """
    def __init__(self, store: dict, bucket: MagicMock):
        self._store = store
        self.storage = MagicMock()
        self.storage.from_.return_value = bucket

    def table(self, name: str) -> _FakeTableQuery:
        return _FakeTableQuery(self._store, name)


def _make_bucket(
    upload_side_effect=None,
    public_url: str = "https://supabase.example.co/storage/path",
    download_bytes: bytes = b"fake-audio-bytes",
) -> MagicMock:
    """Build a mock Supabase Storage bucket with sensible defaults."""
    b = MagicMock()
    if upload_side_effect is not None:
        b.upload.side_effect = upload_side_effect
    else:
        b.upload.return_value = None  # success
    b.get_public_url.return_value = public_url
    b.download.return_value = download_bytes
    return b


@pytest.fixture()
def storage_mem_store() -> dict:
    return {}


@pytest.fixture()
def storage_bucket() -> MagicMock:
    return _make_bucket()


@pytest.fixture()
def fake_supabase(storage_mem_store: dict, storage_bucket: MagicMock) -> _FakeSupabaseWithStorage:
    return _FakeSupabaseWithStorage(storage_mem_store, storage_bucket)


@pytest.fixture()
def storage_client(
    storage_mem_store: dict,
    fake_supabase: _FakeSupabaseWithStorage,
) -> TestClient:
    """
    Test client using the fake Supabase client (not a dict) so storage upload
    code runs.  Bucket is pre-configured to succeed.
    """
    from app.api.v1.endpoints import project_defense_analysis as ep

    app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
    app.dependency_overrides[get_db] = lambda: fake_supabase
    with patch.object(ep, "_MEDIA_BUCKET", "project-defense-media"):
        yield TestClient(app)
    app.dependency_overrides.clear()


def _make_storage_session(
    storage_mem_store: dict,
    session_id: str = "storage-sess-1",
) -> str:
    """Pre-populate an extension-proof session row in the in-memory store."""
    from app.services.extension_proof_service import _TABLE as SESSION_TABLE
    storage_mem_store.setdefault(SESSION_TABLE, {})[session_id] = {
        "id": session_id,
        "user_id": DEMO_USER_ID,
        "skill_evidence_id": EVIDENCE_ID,
        "status": "uploaded_pending_analysis",
        "final_verification_status": "pending",
    }
    return session_id


class TestStorageUpload:
    """
    Tests for the Supabase Storage upload path in upload_project_defense_media.

    These tests use _FakeSupabaseWithStorage (not the plain dict mem_store)
    so that 'not isinstance(db, dict)' is True and the real storage code runs.
    """

    def test_upload_calls_storage_with_correct_bytes(
        self,
        storage_client: TestClient,
        storage_mem_store: dict,
        storage_bucket: MagicMock,
    ):
        """
        upload-media must call storage.from_(bucket).upload(path, file_bytes, ...)
        with the exact bytes that were sent.
        """
        session_id = _make_storage_session(storage_mem_store)
        file_bytes = b"fake-audio-content-bytes-1234"

        r = storage_client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
            files={"file": ("talk.mp3", file_bytes, "audio/mpeg")},
        )

        assert r.status_code in (200, 201), r.text
        storage_bucket.upload.assert_called_once()
        call_args = storage_bucket.upload.call_args
        # Second positional arg is the file bytes
        actual_bytes = call_args[0][1] if call_args[0] else call_args[1].get("content")
        assert actual_bytes == file_bytes, "Storage upload must use the received file bytes"

    def test_upload_returns_media_storage_path(
        self,
        storage_client: TestClient,
        storage_mem_store: dict,
    ):
        """
        Response must contain a non-null media_storage_path when storage succeeds.
        Without it the transcription endpoint has nothing to download.
        """
        session_id = _make_storage_session(storage_mem_store)

        r = storage_client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
            files={"file": ("voice.webm", b"webm-audio", "audio/webm")},
        )

        assert r.status_code in (200, 201), r.text
        data = r.json()
        assert data["media_storage_path"] is not None, (
            "media_storage_path must be set in the response when storage succeeds"
        )
        assert "voice.webm" in data["media_storage_path"]

    def test_storage_path_contains_timestamp(
        self,
        storage_client: TestClient,
        storage_mem_store: dict,
        storage_bucket: MagicMock,
    ):
        """
        The storage path must include a server-side timestamp so that re-uploading
        the same filename produces a unique path and doesn't overwrite the previous file.
        """
        import time as t
        before = int(t.time())

        session_id = _make_storage_session(storage_mem_store)
        r = storage_client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
            files={"file": ("defense.mp3", b"audio", "audio/mpeg")},
        )

        after = int(t.time())
        assert r.status_code in (200, 201), r.text

        path: str = r.json()["media_storage_path"]
        # Path format: {user_id}/{session_id}/{timestamp}_{filename}
        # Extract the timestamp part
        parts = path.split("/")
        assert len(parts) >= 3, f"Unexpected path format: {path}"
        ts_and_name = parts[-1]  # e.g. "1748123456_defense.mp3"
        ts_str = ts_and_name.split("_")[0]
        assert ts_str.isdigit(), f"Expected timestamp prefix in path segment '{ts_and_name}'"
        ts_val = int(ts_str)
        assert before <= ts_val <= after + 2, (
            f"Timestamp {ts_val} should be between {before} and {after}"
        )

    def test_storage_path_saved_to_db(
        self,
        storage_client: TestClient,
        storage_mem_store: dict,
    ):
        """
        The media_storage_path returned by upload-media must be persisted in the DB
        so the transcription endpoint can retrieve the file later.
        """
        from app.services.project_defense_analysis_service import (
            ProjectDefenseAnalysisService,
            _TABLE as DEFENSE_TABLE,
        )
        session_id = _make_storage_session(storage_mem_store)

        r = storage_client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
            files={"file": ("recording.webm", b"webm-bytes", "audio/webm")},
        )

        assert r.status_code in (200, 201), r.text
        response_path = r.json()["media_storage_path"]
        assert response_path is not None

        # The same path must be in the DB row (so transcription can find it)
        db_row = storage_mem_store.get(DEFENSE_TABLE, {}).get(session_id)
        assert db_row is not None, "No DB row created after upload"
        assert db_row.get("media_storage_path") == response_path, (
            "media_storage_path in DB must match what was returned in the response"
        )

    def test_failed_storage_upload_returns_502_not_201(
        self,
        storage_mem_store: dict,
        storage_bucket: MagicMock,
    ):
        """
        When Supabase Storage upload raises an exception, the endpoint must return
        HTTP 502 — NOT 201 with a fake-success message.
        This is the root cause of the 'Supabase Storage bucket is EMPTY' bug.
        """
        from app.api.v1.endpoints import project_defense_analysis as ep

        # Make storage upload fail
        storage_bucket.upload.side_effect = Exception("bucket does not exist or access denied")
        fake_db = _FakeSupabaseWithStorage(storage_mem_store, storage_bucket)
        session_id = _make_storage_session(storage_mem_store)

        app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
        app.dependency_overrides[get_db] = lambda: fake_db
        try:
            with patch.object(ep, "_MEDIA_BUCKET", "project-defense-media"):
                tc = TestClient(app)
                r = tc.post(
                    f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
                    files={"file": ("audio.mp3", b"bytes", "audio/mpeg")},
                )
        finally:
            app.dependency_overrides.clear()

        assert r.status_code == 502, (
            f"Expected 502 when storage fails, got {r.status_code}: {r.text}"
        )
        detail = r.json()["detail"]
        assert detail["code"] == "storage_upload_failed"

    def test_failed_storage_upload_does_not_store_metadata(
        self,
        storage_mem_store: dict,
        storage_bucket: MagicMock,
    ):
        """
        After a storage failure (502), no media row should be written to the DB.
        A misleading DB row would make the transcription endpoint attempt to
        download from a path that never existed.
        """
        from app.api.v1.endpoints import project_defense_analysis as ep
        from app.services.project_defense_analysis_service import _TABLE as DEFENSE_TABLE

        storage_bucket.upload.side_effect = Exception("storage error")
        fake_db = _FakeSupabaseWithStorage(storage_mem_store, storage_bucket)
        session_id = _make_storage_session(storage_mem_store)

        app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
        app.dependency_overrides[get_db] = lambda: fake_db
        try:
            with patch.object(ep, "_MEDIA_BUCKET", "project-defense-media"):
                tc = TestClient(app)
                tc.post(
                    f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
                    files={"file": ("audio.mp3", b"bytes", "audio/mpeg")},
                )
        finally:
            app.dependency_overrides.clear()

        db_row = storage_mem_store.get(DEFENSE_TABLE, {}).get(session_id)
        assert db_row is None, (
            "No DB row should be created when storage upload fails — a row with "
            "null storage_path would make transcription endpoint attempt to "
            "download from a non-existent path."
        )

    def test_no_bucket_configured_returns_201_with_honest_message(
        self,
        storage_mem_store: dict,
        storage_bucket: MagicMock,
    ):
        """
        When no storage bucket is configured (env var empty), upload returns
        201 but is honest: message says no storage configured, not 'uploaded and stored'.
        """
        from app.api.v1.endpoints import project_defense_analysis as ep

        fake_db = _FakeSupabaseWithStorage(storage_mem_store, storage_bucket)
        session_id = _make_storage_session(storage_mem_store)

        app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
        app.dependency_overrides[get_db] = lambda: fake_db
        try:
            with patch.object(ep, "_MEDIA_BUCKET", ""):  # no bucket
                tc = TestClient(app)
                r = tc.post(
                    f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
                    files={"file": ("audio.mp3", b"bytes", "audio/mpeg")},
                )
        finally:
            app.dependency_overrides.clear()

        assert r.status_code in (200, 201), r.text
        data = r.json()
        assert data["media_storage_path"] is None
        # Message must NOT claim the file was stored
        assert "uploaded and stored" not in data["message"].lower(), (
            "Message must not say 'uploaded and stored' when no storage is configured"
        )
        assert "storage" in data["message"].lower() or "paste" in data["message"].lower()
        # Storage upload was never called
        storage_bucket.upload.assert_not_called()

    def test_storage_success_message_says_uploaded_and_stored(
        self,
        storage_client: TestClient,
        storage_mem_store: dict,
    ):
        """
        When storage upload succeeds, message must say 'uploaded and stored'
        (or equivalent) so the student knows the file is safely persisted.
        """
        session_id = _make_storage_session(storage_mem_store)
        r = storage_client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
            files={"file": ("demo.mp3", b"audio", "audio/mpeg")},
        )
        assert r.status_code in (200, 201), r.text
        assert "uploaded and stored" in r.json()["message"].lower()

    def test_transcribe_downloads_file_from_storage_path(
        self,
        storage_client: TestClient,
        storage_mem_store: dict,
        storage_bucket: MagicMock,
    ):
        """
        After a successful upload, the transcription endpoint must download the
        file using media_storage_path from the DB row.
        """
        from app.api.v1.endpoints import project_defense_analysis as ep

        session_id = _make_storage_session(storage_mem_store)

        # Upload the file
        r = storage_client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
            files={"file": ("defense.mp3", b"real-audio-bytes", "audio/mpeg")},
        )
        assert r.status_code in (200, 201), r.text
        stored_path = r.json()["media_storage_path"]
        assert stored_path is not None

        # Now transcribe — endpoint must call storage.download(stored_path)
        mock_result = TranscriptionResult(
            transcript_text="I built a data pipeline.", provider_used="openai"
        )
        with patch.object(ep, "_MEDIA_BUCKET", "project-defense-media"), \
             patch("app.services.transcription_service.transcribe_audio", return_value=mock_result):
            tx_r = storage_client.post(
                f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
            )

        assert tx_r.status_code == 200, tx_r.text
        storage_bucket.download.assert_called()
        actual_path = storage_bucket.download.call_args[0][0]
        assert actual_path == stored_path, (
            f"Transcription should download from storage path {stored_path!r}, "
            f"got {actual_path!r}"
        )

    def test_manual_transcript_still_works_without_storage(
        self, client: TestClient, mem_store: dict
    ):
        """
        Manual transcript analysis via POST /analyze/project-defense works even
        with no media registered and no storage bucket configured.
        This is the 'paste transcript' fallback path.
        """
        session_id = _make_session(client)
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/project-defense",
            json={
                "transcript_text": (
                    "I built a TypeScript CLI tool that parses log files and generates reports. "
                    "I used Node.js streams to handle large files without memory issues. "
                    "I wrote unit tests with Jest and documented the API with JSDoc."
                ),
                "claimed_skills": ["TypeScript", "Node.js", "Jest"],
                "proof_objective": "Demonstrate TypeScript CLI development",
            },
        )
        assert r.status_code in (200, 201), r.text
        data = r.json()
        assert data["overall_defense_score"] > 0
        assert data["transcription_status"] == "analysis_complete"


# ── No-speech / low-quality gates (G3) ────────────────────────────────────────


class TestTranscribeNoSpeechAndLowQualityGates:
    """G3 regression: Whisper's punctuation-only / repeated-token output must
    never be refined, persisted or returned as ``transcript_ready`` — the
    endpoint applies the same meaningfulness/quality gates as VBR
    (``vbr_transcription``) and fails honestly with retry guidance."""

    def _transcribe(self, client: TestClient, session_id: str, mock_result: TranscriptionResult):
        with patch(
            "app.services.transcription_service.transcribe_audio",
            return_value=mock_result,
        ):
            return client.post(
                f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
            )

    def test_punctuation_only_segments_return_no_speech_not_ready(
        self, client: TestClient, mem_store: dict
    ):
        """A silent recording yields "." segments — honest no_speech, nothing saved."""
        session_id = _make_session(client)
        _upload_media(client, session_id, "silent.mp3")

        mock_result = TranscriptionResult(
            transcript_text=". . . .",
            provider_used="openai",
            transcript_segments=[
                TranscriptSegment(0.0, 7.0, "."),
                TranscriptSegment(7.0, 14.0, "."),
                TranscriptSegment(14.0, 21.0, "."),
            ],
        )
        r = self._transcribe(client, session_id, mock_result)

        assert r.status_code == 200, r.text
        data = r.json()
        assert data["transcription_status"] == "no_speech"
        assert data["transcript_text"] == ""
        assert data["configured"] is True
        assert "retry" in data["message"].lower() or "clearer" in data["message"].lower()

        # Nothing was persisted — the session keeps its pre-transcribe state,
        # so a retry re-runs transcription from scratch.
        svc = ProjectDefenseAnalysisService(mem_store)
        row = svc.get_analysis(DEMO_USER_ID, session_id)
        assert row is not None
        assert not row.get("transcript_text")
        assert row["transcription_status"] == "uploaded"

    def test_punctuation_only_output_is_never_refined_into_content(
        self, client: TestClient, mem_store: dict
    ):
        """The gate runs BEFORE refinement — refinement must not be reached."""
        session_id = _make_session(client)
        _upload_media(client, session_id, "silent.webm")

        mock_result = TranscriptionResult(transcript_text="...", provider_used="openai")
        with patch(
            "app.services.transcription_service.transcribe_audio",
            return_value=mock_result,
        ), patch(
            "app.services.transcript_refinement_service.refine_project_defense_transcript"
        ) as refine_mock:
            r = client.post(
                f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
            )
        assert r.status_code == 200, r.text
        assert r.json()["transcription_status"] == "no_speech"
        refine_mock.assert_not_called()

    def test_repeated_token_hallucination_returns_low_quality(
        self, client: TestClient, mem_store: dict
    ):
        """A "new new new …" hallucination fails closed as low_quality."""
        session_id = _make_session(client)
        _upload_media(client, session_id, "degraded.mp3")

        hallucinated = " ".join(["new"] * 40)
        mock_result = TranscriptionResult(
            transcript_text=hallucinated,
            provider_used="openai",
            transcript_segments=[TranscriptSegment(0.0, 30.0, hallucinated)],
        )
        r = self._transcribe(client, session_id, mock_result)

        assert r.status_code == 200, r.text
        data = r.json()
        assert data["transcription_status"] == "low_quality"
        assert data["transcript_text"] == ""
        assert "new new" not in r.text

        svc = ProjectDefenseAnalysisService(mem_store)
        row = svc.get_analysis(DEMO_USER_ID, session_id)
        assert row is not None
        assert not row.get("transcript_text")
        assert row["transcription_status"] == "uploaded"

    def test_degenerate_segments_fail_even_when_full_text_looks_clean(
        self, client: TestClient, mem_store: dict
    ):
        """Gates measure BOTH sources — clean full_text cannot mask "." segments
        hallucinated into a dominant repeated token."""
        session_id = _make_session(client)
        _upload_media(client, session_id, "mixed.mp3")

        mock_result = TranscriptionResult(
            transcript_text="ok ok ok ok ok ok",
            provider_used="openai",
            transcript_segments=[TranscriptSegment(0.0, 10.0, "ok ok ok ok ok ok")],
        )
        r = self._transcribe(client, session_id, mock_result)
        assert r.status_code == 200, r.text
        assert r.json()["transcription_status"] == "low_quality"

    def test_real_speech_still_persists_transcript_ready(
        self, client: TestClient, mem_store: dict
    ):
        """The gates do not block genuine short answers with distinct words."""
        session_id = _make_session(client)
        _upload_media(client, session_id, "talk.mp3")

        mock_result = TranscriptionResult(
            transcript_text="I built the backend scoring route with FastAPI.",
            provider_used="openai",
            transcript_segments=[
                TranscriptSegment(0.0, 6.0, "I built the backend scoring route with FastAPI.")
            ],
        )
        r = self._transcribe(client, session_id, mock_result)
        assert r.status_code == 200, r.text
        assert r.json()["transcription_status"] == "transcript_ready"

        svc = ProjectDefenseAnalysisService(mem_store)
        row = svc.get_analysis(DEMO_USER_ID, session_id)
        assert row is not None
        assert row["transcription_status"] == "transcript_ready"
