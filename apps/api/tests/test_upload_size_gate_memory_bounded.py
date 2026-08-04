"""Regression tests: memory-bounded upload size gates (G9).

The workflow-video OOM incident (see test_video_upload_memory_bounded.py)
established the rule: an upload endpoint must NEVER materialize the whole
request body in memory before its size check. These tests pin the same
bounded-chunk streaming pattern on the three remaining whole-body readers:

  * POST /student/document-proofs/upload            (20 MB, file_too_large)
  * POST /proofs/video                              (max_video_size_bytes, video_too_large)
  * POST /student/extension-proof/sessions/{id}/defense/upload-media
                                                    (200 MB, media_too_large)

Each endpoint keeps its existing limit + error shape; an oversized body is
rejected as soon as the limit is crossed and nothing is persisted. Limits are
monkeypatched small so the tests stay fast and hermetic (dict-mode storage).
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_optional_user_id, get_pipeline_db
from app.main import app

USER_ID = "00000000-0000-0000-0000-000000000001"
SESSION_ID = "ssssssss-0000-0000-0000-000000000001"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_optional_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: {}
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Document proof upload (20 MB gate) ────────────────────────────────────────


class TestDocumentUploadSizeGate:
    def _post(self, client: TestClient, body: bytes):
        return client.post(
            "/api/v1/student/document-proofs/upload",
            files={"file": ("report.md", io.BytesIO(body), "text/markdown")},
            data={"title": "Report"},
        )

    def test_oversized_upload_rejected_with_canonical_413(
        self, client: TestClient, mem_store: dict, monkeypatch
    ):
        from app.api.v1.endpoints import document_proofs

        monkeypatch.setattr(document_proofs, "_MAX_UPLOAD_BYTES", 16)
        # Chunk smaller than the limit so the abort provably happens mid-stream,
        # after a bounded read — not after buffering the whole body.
        monkeypatch.setattr(document_proofs, "_UPLOAD_CHUNK_BYTES", 4)

        response = self._post(client, b"x" * 64)
        assert response.status_code == 413
        assert response.json()["detail"] == {
            "code": "file_too_large",
            "message": "File exceeds 20 MB limit.",
        }
        # Nothing persisted: no evidence row, no retained artifact.
        assert not mem_store.get("optional_evidence_submissions")
        assert not mem_store.get("proof_artifacts")

    def test_upload_at_limit_still_succeeds(
        self, client: TestClient, mem_store: dict, monkeypatch
    ):
        from app.api.v1.endpoints import document_proofs

        body = b"# Report\nBuilt a small FastAPI service with tests."
        monkeypatch.setattr(document_proofs, "_MAX_UPLOAD_BYTES", len(body))
        monkeypatch.setattr(document_proofs, "_UPLOAD_CHUNK_BYTES", 7)

        response = self._post(client, body)
        assert response.status_code == 201, response.text


# ── Video proof upload (max_video_size_bytes gate) ────────────────────────────


class TestVideoProofUploadSizeGate:
    @pytest.fixture(autouse=True)
    def _offline_pipeline(self, monkeypatch):
        from app.services import video_proof_service
        from app.services.transcription_service import TranscriptionUnavailableError
        from app.services.video_keyframe_extractor_service import VideoKeyframeResult

        def _unavailable(*_args, **_kwargs):
            raise TranscriptionUnavailableError("not configured")

        class _NoBackend:
            def extract_keyframes(self, *_args, **_kwargs):
                return VideoKeyframeResult(
                    video_analysis_status="not_available",
                    keyframe_count=0,
                    selected_frame_timestamps_ms=[],
                    extraction_method="none",
                    duration_ms=None,
                    frame_width=None,
                    frame_height=None,
                    limitations=["No extraction backend installed."],
                )

        monkeypatch.setattr(video_proof_service, "transcribe_audio", _unavailable)
        monkeypatch.setattr(video_proof_service, "VideoKeyframeExtractorService", _NoBackend)

    def _post(self, client: TestClient, body: bytes, filename: str = "demo.mp4"):
        return client.post(
            "/api/v1/proofs/video",
            files={"file": (filename, io.BytesIO(body), "video/mp4")},
            data={"title": "Demo", "source_kind": "hackathon_demo"},
        )

    def test_oversized_upload_rejected_with_canonical_413(
        self, client: TestClient, mem_store: dict, monkeypatch
    ):
        from app.api.v1.endpoints import video_proofs
        from app.core.config import settings

        monkeypatch.setattr(settings, "max_video_size_bytes", 16)
        monkeypatch.setattr(video_proofs, "_UPLOAD_CHUNK_BYTES", 4)

        response = self._post(client, b"x" * 64)
        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "video_too_large"
        # Nothing persisted: no proof row, no retained artifact.
        assert not mem_store.get("video_proofs")
        assert not mem_store.get("proof_artifacts")

    def test_unsupported_extension_still_rejected_before_body_is_read(
        self, client: TestClient, monkeypatch
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "max_video_size_bytes", 16)
        # Bad extension + oversized body → format 422 wins (checked first).
        response = self._post(client, b"x" * 64, filename="notes.pdf")
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "unsupported_video_format"

    def test_upload_at_limit_still_succeeds(
        self, client: TestClient, monkeypatch
    ):
        from app.api.v1.endpoints import video_proofs
        from app.core.config import settings

        body = b"fake-mp4-bytes"
        monkeypatch.setattr(settings, "max_video_size_bytes", len(body))
        monkeypatch.setattr(video_proofs, "_UPLOAD_CHUNK_BYTES", 5)

        response = self._post(client, body)
        assert response.status_code == 201, response.text


# ── Defense media upload (200 MB gate) ────────────────────────────────────────


class TestDefenseMediaUploadSizeGate:
    @pytest.fixture()
    def session_store(self, mem_store: dict) -> dict:
        mem_store["extension_proof_sessions"] = {
            SESSION_ID: {"id": SESSION_ID, "user_id": USER_ID, "status": "recording"}
        }
        return mem_store

    def _post(self, client: TestClient, body: bytes):
        return client.post(
            f"/api/v1/student/extension-proof/sessions/{SESSION_ID}/defense/upload-media",
            files={"file": ("talk.mp3", io.BytesIO(body), "audio/mpeg")},
        )

    def test_oversized_upload_rejected_with_canonical_413(
        self, client: TestClient, session_store: dict, monkeypatch
    ):
        from app.api.v1.endpoints import project_defense_analysis

        monkeypatch.setattr(project_defense_analysis, "MAX_MEDIA_SIZE_BYTES", 16)
        monkeypatch.setattr(project_defense_analysis, "_UPLOAD_CHUNK_BYTES", 4)

        response = self._post(client, b"x" * 64)
        assert response.status_code == 413
        detail = response.json()["detail"]
        assert detail["code"] == "media_too_large"
        assert "exceeds" in detail["message"]
        # No media row registered for the session.
        assert not session_store.get("project_defense_analysis_results")

    def test_upload_at_limit_still_succeeds(
        self, client: TestClient, session_store: dict, monkeypatch
    ):
        from app.api.v1.endpoints import project_defense_analysis

        body = b"fake-audio-bytes"
        monkeypatch.setattr(project_defense_analysis, "MAX_MEDIA_SIZE_BYTES", len(body))
        monkeypatch.setattr(project_defense_analysis, "_UPLOAD_CHUNK_BYTES", 6)

        response = self._post(client, body)
        assert response.status_code in (200, 201), response.text
