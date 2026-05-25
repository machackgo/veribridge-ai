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
