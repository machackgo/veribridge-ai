"""Regression tests: memory-bounded workflow-video upload (Render OOM fix).

Production incident 2026-07-21: POST /workflow/video OOM-killed the 512 Mi
Render instance (`oomKilled {memoryLimit: 512Mi}`) because the endpoint did
`await video.read(MAX_VIDEO_SIZE_BYTES + 1)` — CPython preallocates the full
requested buffer (100 MB) regardless of the actual body size. The fix streams
the body to disk in 1 MB chunks, retains the replay artifact durable-first,
and runs extraction file-based behind a process-wide gate.

Covered here:
1. The extractor is invoked with a file path, never with in-memory bytes.
2. An oversized body yields limit_exceeded (202) and stores NO artifact.
3. Extraction crash → honest degraded 202 with the replay already retained
   (durable-first), never a 500.
4. A retry after an extraction crash lands on the idempotent path.
5. Another user's session id → 404 (ownership unchanged by the rework).
6. The streamed temp file is deleted after the request.
"""

from __future__ import annotations

import io
import glob
import os
import tempfile
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.api.deps import get_current_user_id, get_db
from app.services.video_keyframe_extractor_service import (
    VideoKeyframeResult,
    VIDEO_STATUS_ANALYZED,
)

OWNER = "00000000-0000-0000-0000-000000000001"
INTRUDER = "00000000-0000-0000-0000-000000000002"


def _mock_db(session_id: str = "mem-session", owner: str = OWNER) -> dict:
    return {
        "extension_proof_sessions": {
            session_id: {"id": session_id, "user_id": owner, "status": "recording"},
        }
    }


def _analyzed_result() -> VideoKeyframeResult:
    return VideoKeyframeResult(
        video_analysis_status=VIDEO_STATUS_ANALYZED,
        keyframe_count=1,
        selected_frame_timestamps_ms=[0],
        extraction_method="cv2_interval",
        duration_ms=1000,
        frame_width=640,
        frame_height=360,
        limitations=[],
        _extracted_frames=[(0, b"jpeg")],
    )


def _post_video(client: TestClient, session_id: str, body: bytes = b"fake_video"):
    return client.post(
        f"/api/v1/student/extension-proof/sessions/{session_id}/workflow/video",
        files={"video": ("recording.webm", io.BytesIO(body), "video/webm")},
    )


def _override(db: dict, user: str = OWNER) -> None:
    app.dependency_overrides[get_current_user_id] = lambda: user
    app.dependency_overrides[get_db] = lambda: db


def _mock_va():
    inst = MagicMock()
    inst.store_visual_frame.return_value = "frame-id-1"
    inst.get_provider_status.return_value = {
        "provider_configured": False,
        "visual_analysis_provider": "none",
    }
    return inst


def test_extractor_receives_file_path_never_bytes():
    """The endpoint must hand the extractor a file path; video_bytes stays None."""
    client = TestClient(app)
    db = _mock_db()
    _override(db)
    seen: dict = {}

    def _capture(**kwargs):
        seen.update(kwargs)
        # The temp file must exist at extraction time.
        assert kwargs.get("video_path") and os.path.exists(kwargs["video_path"])
        return _analyzed_result()

    try:
        with (
            patch(
                "app.api.v1.endpoints.workflow_visual_frames.VideoKeyframeExtractorService"
            ) as MockExtractor,
            patch(
                "app.api.v1.endpoints.workflow_visual_frames.WorkflowVisualAnalysisService"
            ) as MockVA,
        ):
            inst = MagicMock()
            inst.extract_keyframes.side_effect = _capture
            MockExtractor.return_value = inst
            MockVA.return_value = _mock_va()

            resp = _post_video(client, "mem-session")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 202, resp.text
    assert seen.get("video_bytes") is None
    assert seen.get("video_path")
    # Temp file cleaned up after the request completed.
    assert not os.path.exists(seen["video_path"])
    # Replay artifact was streamed from the same file content.
    assert list(db["_proof_artifact_objects"].values()) == [b"fake_video"]


def test_oversized_upload_returns_limit_exceeded_and_stores_nothing(monkeypatch):
    """A body over MAX_VIDEO_SIZE_BYTES → 202 limit_exceeded, no artifact, no extraction."""
    from app.core.config import settings

    client = TestClient(app)
    db = _mock_db("big-session")
    _override(db)
    monkeypatch.setattr(settings, "max_video_size_bytes", 10)

    try:
        with patch(
            "app.api.v1.endpoints.workflow_visual_frames.VideoKeyframeExtractorService"
        ) as MockExtractor:
            inst = MagicMock()
            MockExtractor.return_value = inst
            resp = _post_video(client, "big-session", body=b"x" * 64)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["video_analysis_status"] == "limit_exceeded"
    assert body["replay_retained"] is False
    assert body["replay_artifact_id"] is None
    assert "proof_artifacts" not in db or not db["proof_artifacts"]
    inst.extract_keyframes.assert_not_called()


def test_extraction_crash_is_degraded_not_500_and_replay_is_durable():
    """Durable-first: extraction blowing up must not lose the media or 500."""
    client = TestClient(app)
    db = _mock_db("crash-session")
    _override(db)

    try:
        with (
            patch(
                "app.api.v1.endpoints.workflow_visual_frames.VideoKeyframeExtractorService"
            ) as MockExtractor,
            patch(
                "app.api.v1.endpoints.workflow_visual_frames.WorkflowVisualAnalysisService"
            ) as MockVA,
        ):
            inst = MagicMock()
            inst.extract_keyframes.side_effect = MemoryError("simulated OOM")
            MockExtractor.return_value = inst
            MockVA.return_value = _mock_va()

            resp = _post_video(client, "crash-session")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["video_analysis_status"] == "failed"
    # The media survived the crash — this is the core durability guarantee.
    assert body["replay_retained"] is True
    assert body["replay_artifact_id"]
    artifacts = list(db["proof_artifacts"].values())
    assert len(artifacts) == 1
    assert artifacts[0]["owner_user_id"] == OWNER


def test_retry_after_extraction_crash_hits_idempotent_path():
    """After a crash-with-retained-replay, a retry must be acknowledged idempotently."""
    client = TestClient(app)
    db = _mock_db("retry-session")
    _override(db)

    try:
        with (
            patch(
                "app.api.v1.endpoints.workflow_visual_frames.VideoKeyframeExtractorService"
            ) as MockExtractor,
            patch(
                "app.api.v1.endpoints.workflow_visual_frames.WorkflowVisualAnalysisService"
            ) as MockVA,
        ):
            inst = MagicMock()
            inst.extract_keyframes.side_effect = MemoryError("simulated OOM")
            MockExtractor.return_value = inst
            MockVA.return_value = _mock_va()

            first = _post_video(client, "retry-session")
            retry = _post_video(client, "retry-session")
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 202
    assert retry.status_code == 202
    retry_body = retry.json()
    assert retry_body["replay_retained"] is True
    assert retry_body["replay_artifact_id"] == first.json()["replay_artifact_id"]
    assert "idempotent" in retry_body["message"]
    # Retry created no duplicate artifact.
    assert len(db["proof_artifacts"]) == 1
    # Extraction ran only for the first delivery.
    assert inst.extract_keyframes.call_count == 1


def test_other_users_session_is_404():
    """Ownership gate unchanged: an intruder posting to another user's session gets 404."""
    client = TestClient(app)
    db = _mock_db("victim-session", owner=OWNER)
    _override(db, user=INTRUDER)

    try:
        resp = _post_video(client, "victim-session")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404, resp.text
    assert "proof_artifacts" not in db or not db["proof_artifacts"]


def test_no_temp_files_leak(tmp_path):
    """Every request must clean up its streamed temp file (success path)."""
    client = TestClient(app)
    db = _mock_db("leak-session")
    _override(db)

    before = set(glob.glob(os.path.join(tempfile.gettempdir(), "*.webm")))
    try:
        with (
            patch(
                "app.api.v1.endpoints.workflow_visual_frames.VideoKeyframeExtractorService"
            ) as MockExtractor,
            patch(
                "app.api.v1.endpoints.workflow_visual_frames.WorkflowVisualAnalysisService"
            ) as MockVA,
        ):
            inst = MagicMock()
            inst.extract_keyframes.return_value = _analyzed_result()
            MockExtractor.return_value = inst
            MockVA.return_value = _mock_va()
            resp = _post_video(client, "leak-session")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 202
    after = set(glob.glob(os.path.join(tempfile.gettempdir(), "*.webm")))
    assert after <= before
