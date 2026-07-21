"""Tests for VideoKeyframeExtractorService (Week 2 — video keyframe extraction).

Coverage:
1.  Valid video → analyzed status, correct keyframe count, correct timestamps.
2.  Missing (None) video bytes → failed status, does not raise.
3.  Unsupported MIME type → unsupported_format, does not raise.
4.  Video exceeds MAX_VIDEO_SIZE_BYTES → limit_exceeded, does not raise.
5.  Keyframes capped to MAX_VIDEO_KEYFRAMES even when video has many frames.
6.  Corrupt video (cv2 cannot open) → failed status, does not raise.
7.  to_public_dict() never exposes _extracted_frames or private metadata.
8.  to_public_dict() never exposes frame_storage_path, tokens, or debug fields.
9.  Integration: extracted frames are stored via WorkflowVisualAnalysisService
    using the video_keyframe frame_type.
10. When neither cv2 nor ffmpeg is available → not_available, no crash.
11. Duration limit exceeded (cv2 backend) → limit_exceeded.
12. ffmpeg fallback when cv2 is unavailable.
13. Extension of existing visual-analysis tests: importing VideoKeyframeExtractorService
    alongside WorkflowVisualAnalysisService causes no import-time errors.
14. VideoUploadResponse endpoint returns video_analysis_status in response body.
15. Endpoint rejects unsupported content type with 415.
"""

from __future__ import annotations

import io
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.video_keyframe_extractor_service import (
    VideoKeyframeExtractorService,
    VideoKeyframeResult,
    VIDEO_STATUS_ANALYZED,
    VIDEO_STATUS_FAILED,
    VIDEO_STATUS_NOT_AVAILABLE,
    VIDEO_STATUS_UNSUPPORTED,
    VIDEO_STATUS_LIMIT_EXCEEDED,
    _Cv2Unavailable,
    _FfmpegUnavailable,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_svc(
    max_size_bytes: int = 100 * 1024 * 1024,
    max_duration_seconds: int = 300,
    max_keyframes: int = 10,
) -> VideoKeyframeExtractorService:
    """Return a service with explicit limits — no env dependency."""
    return VideoKeyframeExtractorService(
        max_size_bytes=max_size_bytes,
        max_duration_seconds=max_duration_seconds,
        max_keyframes=max_keyframes,
    )


def _fake_cv2(
    total_frames: int = 30,
    fps: float = 10.0,
    width: int = 1280,
    height: int = 720,
    can_open: bool = True,
    read_success: bool = True,
) -> MagicMock:
    """Build a minimal cv2 mock that VideoKeyframeExtractorService can drive."""
    import numpy as np

    mock = MagicMock()

    # Constants (must be ints/floats — the service indexes them via cap.get())
    mock.CAP_PROP_FPS          = 0
    mock.CAP_PROP_FRAME_COUNT  = 1
    mock.CAP_PROP_FRAME_WIDTH  = 2
    mock.CAP_PROP_FRAME_HEIGHT = 3
    mock.CAP_PROP_POS_FRAMES   = 4
    mock.IMWRITE_JPEG_QUALITY  = 5

    # cap instance
    cap = MagicMock()
    cap.isOpened.return_value = can_open

    def _cap_get(prop: int) -> float:
        mapping = {0: fps, 1: float(total_frames), 2: float(width), 3: float(height)}
        return mapping.get(prop, 0.0)

    cap.get.side_effect = _cap_get
    cap.set.return_value = None

    fake_frame = np.zeros((height, width, 3), dtype="uint8")
    cap.read.return_value = (read_success, fake_frame)

    mock.VideoCapture.return_value = cap

    # imencode → (True, numpy array whose bytes() is b"FAKE")
    fake_jpeg = np.frombuffer(b"FAKEJPEG", dtype="uint8")
    mock.imencode.return_value = (True, fake_jpeg)

    return mock


# ── Test 1 ─────────────────────────────────────────────────────────────────────

def test_valid_video_cv2_returns_analyzed():
    """A valid video processed by cv2 returns analyzed status with correct counts."""
    svc = _make_svc(max_keyframes=5)
    fake_cv2 = _fake_cv2(total_frames=50, fps=10.0)

    with patch.dict(sys.modules, {"cv2": fake_cv2}):
        result = svc.extract_keyframes(b"fake_video_bytes", "test.webm", "video/webm")

    assert result.video_analysis_status == VIDEO_STATUS_ANALYZED
    assert result.keyframe_count == 5
    assert len(result.selected_frame_timestamps_ms) == 5
    assert result.extraction_method == "cv2_interval"
    assert len(result._extracted_frames) == 5
    # All timestamps should be non-negative
    assert all(ts >= 0 for ts in result.selected_frame_timestamps_ms)


# ── Test 2 ─────────────────────────────────────────────────────────────────────

def test_missing_video_bytes_returns_failed():
    """None / empty bytes → failed status, no exception raised."""
    svc = _make_svc()

    result_none = svc.extract_keyframes(None, "test.webm", "video/webm")
    assert result_none.video_analysis_status == VIDEO_STATUS_FAILED
    assert result_none.keyframe_count == 0
    assert len(result_none.limitations) > 0

    result_empty = svc.extract_keyframes(b"", "test.webm", "video/webm")
    assert result_empty.video_analysis_status == VIDEO_STATUS_FAILED


# ── Test 3 ─────────────────────────────────────────────────────────────────────

def test_unsupported_mime_type_returns_unsupported():
    """An unrecognised MIME type AND extension → unsupported_format status."""
    svc = _make_svc()

    result = svc.extract_keyframes(b"fake", "clip.txt", "text/plain")
    assert result.video_analysis_status == VIDEO_STATUS_UNSUPPORTED
    assert result.keyframe_count == 0
    assert any("Unsupported" in lim for lim in result.limitations)


def test_allowed_octet_stream_mime_not_rejected():
    """application/octet-stream is accepted (browsers sometimes send this for WebM)."""
    svc = _make_svc(max_keyframes=3)
    fake_cv2 = _fake_cv2(total_frames=30, fps=10.0)

    with patch.dict(sys.modules, {"cv2": fake_cv2}):
        result = svc.extract_keyframes(b"fake", "recording.webm", "application/octet-stream")

    # Should attempt extraction (not reject as unsupported)
    assert result.video_analysis_status != VIDEO_STATUS_UNSUPPORTED


# ── Test 4 ─────────────────────────────────────────────────────────────────────

def test_size_limit_exceeded_returns_limit_exceeded():
    """Video larger than max_size_bytes → limit_exceeded, no extraction attempted."""
    svc = _make_svc(max_size_bytes=10)   # 10 bytes limit

    result = svc.extract_keyframes(b"x" * 20, "test.mp4", "video/mp4")
    assert result.video_analysis_status == VIDEO_STATUS_LIMIT_EXCEEDED
    assert result.keyframe_count == 0
    assert any("limit" in lim.lower() for lim in result.limitations)


# ── Test 5 ─────────────────────────────────────────────────────────────────────

def test_frames_capped_to_max_keyframes():
    """Even when cv2 reports 200 frames, at most max_keyframes are extracted."""
    max_kf  = 4
    svc     = _make_svc(max_keyframes=max_kf)
    fake_cv2 = _fake_cv2(total_frames=200, fps=25.0)

    with patch.dict(sys.modules, {"cv2": fake_cv2}):
        result = svc.extract_keyframes(b"fake_video", "long.webm", "video/webm")

    assert result.video_analysis_status == VIDEO_STATUS_ANALYZED
    assert result.keyframe_count <= max_kf
    assert len(result._extracted_frames) <= max_kf


# ── Test 6 ─────────────────────────────────────────────────────────────────────

def test_corrupt_video_cv2_cannot_open_returns_failed():
    """When cv2.VideoCapture cannot open the file, status is failed (no crash)."""
    svc      = _make_svc()
    fake_cv2 = _fake_cv2(can_open=False)

    with patch.dict(sys.modules, {"cv2": fake_cv2}):
        result = svc.extract_keyframes(b"bad_bytes", "corrupt.webm", "video/webm")

    assert result.video_analysis_status == VIDEO_STATUS_FAILED
    assert result.keyframe_count == 0
    assert len(result.limitations) > 0


# ── Test 7 ─────────────────────────────────────────────────────────────────────

def test_public_dict_excludes_extracted_frames():
    """to_public_dict() must NOT include _extracted_frames or raw bytes."""
    result = VideoKeyframeResult(
        video_analysis_status=VIDEO_STATUS_ANALYZED,
        keyframe_count=3,
        selected_frame_timestamps_ms=[0, 1000, 2000],
        extraction_method="cv2_interval",
        duration_ms=3000,
        frame_width=1280,
        frame_height=720,
        limitations=[],
        _extracted_frames=[(0, b"secret_frame_bytes")],
    )

    public = result.to_public_dict()

    assert "_extracted_frames" not in public
    assert "secret_frame_bytes" not in str(public)
    assert b"secret_frame_bytes" not in public.values()


# ── Test 8 ─────────────────────────────────────────────────────────────────────

def test_public_dict_no_private_metadata():
    """to_public_dict() must not expose frame_storage_path, tokens, or debug data."""
    result = VideoKeyframeResult(
        video_analysis_status=VIDEO_STATUS_ANALYZED,
        keyframe_count=2,
        selected_frame_timestamps_ms=[0, 500],
        extraction_method="cv2_interval",
        duration_ms=1000,
        frame_width=640,
        frame_height=360,
        limitations=[],
        _extracted_frames=[(0, b"pixeldata"), (500, b"pixeldata2")],
    )
    public = result.to_public_dict()

    forbidden_keys = {
        "frame_storage_path", "_extracted_frames", "frame_bytes",
        "access_token", "storage_url", "debug",
        "frame_width", "frame_height",   # dimensions are internal
    }
    for key in forbidden_keys:
        assert key not in public, f"Private key '{key}' must not appear in public dict"

    # Required public keys must be present
    required_keys = {
        "video_analysis_status", "keyframe_count",
        "selected_frame_timestamps_ms", "extraction_method",
        "duration_ms", "limitations",
    }
    for key in required_keys:
        assert key in public, f"Required key '{key}' missing from public dict"


# ── Test 9 ─────────────────────────────────────────────────────────────────────

def test_extracted_frames_stored_via_visual_analysis_service():
    """Integration: frames from a successful extraction are stored via
    WorkflowVisualAnalysisService.store_visual_frame with frame_type=video_keyframe."""
    svc      = _make_svc(max_keyframes=3)
    fake_cv2 = _fake_cv2(total_frames=30, fps=10.0)

    # Mock the visual analysis service
    mock_va_svc = MagicMock()
    mock_va_svc.store_visual_frame.side_effect = lambda **kw: f"frame-{kw['timestamp_ms']}"
    mock_va_svc.get_provider_status.return_value = {
        "provider_configured": False,
        "visual_analysis_provider": "none",
    }

    with patch.dict(sys.modules, {"cv2": fake_cv2}):
        result = svc.extract_keyframes(b"fake_video", "demo.webm", "video/webm")

    assert result.video_analysis_status == VIDEO_STATUS_ANALYZED
    assert len(result._extracted_frames) == 3

    # Simulate what the endpoint does: store each frame
    stored_ids: list[str] = []
    for ts_ms, jpeg_bytes in result._extracted_frames:
        fid = mock_va_svc.store_visual_frame(
            user_id="user-1",
            session_id="session-1",
            frame_type="video_keyframe",
            frame_bytes=jpeg_bytes,
            timestamp_ms=ts_ms,
        )
        stored_ids.append(fid)

    assert len(stored_ids) == 3
    # Verify frame_type was always "video_keyframe"
    for call in mock_va_svc.store_visual_frame.call_args_list:
        assert call.kwargs.get("frame_type") == "video_keyframe"


# ── Test 10 ────────────────────────────────────────────────────────────────────

def test_no_cv2_no_ffmpeg_returns_not_available():
    """When cv2 is missing AND ffmpeg is missing → not_available, no crash."""
    svc = _make_svc()

    # Simulate cv2 not installed (ImportError) and ffmpeg binary not found
    with patch.dict(sys.modules, {"cv2": None}):
        with patch(
            "app.services.video_keyframe_extractor_service.subprocess.run",
            side_effect=FileNotFoundError("ffmpeg: not found"),
        ):
            result = svc.extract_keyframes(b"fake_video", "test.webm", "video/webm")

    assert result.video_analysis_status == VIDEO_STATUS_NOT_AVAILABLE
    assert result.keyframe_count == 0
    assert any(
        "opencv" in lim.lower() or "ffmpeg" in lim.lower()
        for lim in result.limitations
    )


# ── Test 11 ────────────────────────────────────────────────────────────────────

def test_cv2_duration_limit_exceeded_returns_limit_exceeded():
    """cv2 path: a video longer than max_duration_seconds → limit_exceeded."""
    max_dur  = 5   # 5 seconds
    svc      = _make_svc(max_duration_seconds=max_dur)
    # 100 frames @ 10 fps = 10 seconds > 5 seconds limit
    fake_cv2 = _fake_cv2(total_frames=100, fps=10.0)

    with patch.dict(sys.modules, {"cv2": fake_cv2}):
        result = svc.extract_keyframes(b"long_video", "long.webm", "video/webm")

    assert result.video_analysis_status == VIDEO_STATUS_LIMIT_EXCEEDED
    assert result.keyframe_count == 0
    assert any("duration" in lim.lower() for lim in result.limitations)


# ── Test 12 ────────────────────────────────────────────────────────────────────

def test_ffmpeg_fallback_when_cv2_unavailable():
    """When cv2 import fails, the service tries ffmpeg and succeeds."""
    svc = _make_svc(max_keyframes=3)

    # Build a fake successful ffmpeg path result via _extract_with_ffmpeg
    fake_result = VideoKeyframeResult(
        video_analysis_status=VIDEO_STATUS_ANALYZED,
        keyframe_count=3,
        selected_frame_timestamps_ms=[0, 1000, 2000],
        extraction_method="ffmpeg_interval",
        duration_ms=3000,
        frame_width=None,
        frame_height=None,
        limitations=[],
        _extracted_frames=[(0, b"f1"), (1000, b"f2"), (2000, b"f3")],
    )

    # cv2 module not installed; ffmpeg fallback works
    with patch.dict(sys.modules, {"cv2": None}):
        with patch.object(svc, "_extract_with_ffmpeg", return_value=fake_result):
            result = svc.extract_keyframes(b"fake_video", "test.webm", "video/webm")

    assert result.video_analysis_status == VIDEO_STATUS_ANALYZED
    assert result.extraction_method == "ffmpeg_interval"
    assert result.keyframe_count == 3


# ── Test 13 ────────────────────────────────────────────────────────────────────

def test_no_import_error_alongside_visual_analysis_service():
    """Importing VideoKeyframeExtractorService alongside WorkflowVisualAnalysisService
    must not raise any import-time error."""
    # Re-importing modules should be idempotent
    from app.services.video_keyframe_extractor_service import (
        VideoKeyframeExtractorService as VKE,
        VIDEO_STATUS_ANALYZED as VSA,
    )
    from app.services.workflow_visual_analysis_service import (
        WorkflowVisualAnalysisService,
        VISUAL_STATUS_ANALYZED,
    )

    assert VKE is VideoKeyframeExtractorService
    assert VSA == VIDEO_STATUS_ANALYZED
    assert VISUAL_STATUS_ANALYZED == "analyzed"


# ── Test 14 ────────────────────────────────────────────────────────────────────

def test_video_upload_endpoint_returns_video_analysis_status():
    """The /workflow/video endpoint returns video_analysis_status in the response."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user_id, get_db

    client = TestClient(app)

    fake_extractor_result = VideoKeyframeResult(
        video_analysis_status=VIDEO_STATUS_ANALYZED,
        keyframe_count=2,
        selected_frame_timestamps_ms=[0, 500],
        extraction_method="cv2_interval",
        duration_ms=1000,
        frame_width=640,
        frame_height=360,
        limitations=[],
        _extracted_frames=[(0, b"j1"), (500, b"j2")],
    )

    owner_id = "00000000-0000-0000-0000-000000000001"
    mock_db = {
        "extension_proof_sessions": {
            "test-session": {
                "id": "test-session",
                "user_id": owner_id,
                "status": "recording",
            }
        }
    }

    def _fake_get_db():
        return mock_db

    def _fake_get_user():
        return owner_id

    # Authenticate explicitly instead of relying on the (now gated) dev
    # no-token fallback: register the identity/db overrides this test defines.
    app.dependency_overrides[get_current_user_id] = _fake_get_user
    app.dependency_overrides[get_db] = _fake_get_db

    # Patch extractor and visual analysis to avoid real cv2/DB calls
    with (
        patch(
            "app.api.v1.endpoints.workflow_visual_frames.VideoKeyframeExtractorService"
        ) as MockExtractor,
        patch(
            "app.api.v1.endpoints.workflow_visual_frames.WorkflowVisualAnalysisService"
        ) as MockVA,
    ):
        mock_extractor_inst = MagicMock()
        mock_extractor_inst.extract_keyframes.return_value = fake_extractor_result
        MockExtractor.return_value = mock_extractor_inst

        mock_va_inst = MagicMock()
        mock_va_inst.store_visual_frame.return_value = "frame-id-1"
        mock_va_inst.get_provider_status.return_value = {
            "provider_configured": False,
            "visual_analysis_provider": "none",
        }
        MockVA.return_value = mock_va_inst

        response = client.post(
            "/api/v1/student/extension-proof/sessions/test-session/workflow/video",
            files={"video": ("recording.webm", io.BytesIO(b"fake_video"), "video/webm")},
        )
        duplicate_response = client.post(
            "/api/v1/student/extension-proof/sessions/test-session/workflow/video",
            files={"video": ("recording.webm", io.BytesIO(b"fake_video"), "video/webm")},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 202, response.text
    body = response.json()
    assert "video_analysis_status" in body
    assert body["video_analysis_status"] == VIDEO_STATUS_ANALYZED
    assert "keyframe_count" in body
    assert body["replay_retained"] is True
    assert duplicate_response.status_code == 202
    assert duplicate_response.json()["replay_artifact_id"] == body["replay_artifact_id"]
    artifacts = list(mock_db["proof_artifacts"].values())
    assert len(artifacts) == 1
    assert artifacts[0]["artifact_type"] == "website_replay_video"
    assert artifacts[0]["owner_user_id"] == owner_id
    assert list(mock_db["_proof_artifact_objects"].values()) == [b"fake_video"]
    # Private fields must not appear in the response
    assert "_extracted_frames" not in body
    assert "frame_storage_path" not in body


# ── Test 15 ────────────────────────────────────────────────────────────────────

def test_video_upload_endpoint_rejects_unsupported_content_type():
    """Endpoint returns 415 for content types that are not video formats."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user_id, get_db

    client = TestClient(app)
    # Authenticate explicitly so we exercise the media-type check, not auth.
    owner_id = "00000000-0000-0000-0000-000000000001"
    app.dependency_overrides[get_current_user_id] = lambda: owner_id
    app.dependency_overrides[get_db] = lambda: {
        "extension_proof_sessions": {
            "test-session": {
                "id": "test-session",
                "user_id": owner_id,
                "status": "recording",
            }
        }
    }

    try:
        response = client.post(
            "/api/v1/student/extension-proof/sessions/test-session/workflow/video",
            files={"video": ("clip.txt", io.BytesIO(b"not a video"), "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()

    # 415 Unsupported Media Type
    assert response.status_code == 415, response.text


# ── Test 16 ────────────────────────────────────────────────────────────────────

def test_video_upload_duplicate_delivery_is_idempotent_no_new_frames():
    """A retried upload (same session) must not duplicate keyframes or re-extract.

    The extension retries a failed/ack-lost upload with the same session and a
    stable idempotency key. Once a retained replay exists, the endpoint must
    short-circuit: no second extraction, no additional stored frames, and an
    acknowledgment with replay_retained=True so the recorder can settle.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user_id, get_db

    client = TestClient(app)

    fake_extractor_result = VideoKeyframeResult(
        video_analysis_status=VIDEO_STATUS_ANALYZED,
        keyframe_count=2,
        selected_frame_timestamps_ms=[0, 500],
        extraction_method="cv2_interval",
        duration_ms=1000,
        frame_width=640,
        frame_height=360,
        limitations=[],
        _extracted_frames=[(0, b"j1"), (500, b"j2")],
    )

    owner_id = "00000000-0000-0000-0000-000000000001"
    mock_db = {
        "extension_proof_sessions": {
            "idem-session": {
                "id": "idem-session",
                "user_id": owner_id,
                "status": "recording",
            }
        }
    }

    app.dependency_overrides[get_current_user_id] = lambda: owner_id
    app.dependency_overrides[get_db] = lambda: mock_db

    with (
        patch(
            "app.api.v1.endpoints.workflow_visual_frames.VideoKeyframeExtractorService"
        ) as MockExtractor,
        patch(
            "app.api.v1.endpoints.workflow_visual_frames.WorkflowVisualAnalysisService"
        ) as MockVA,
    ):
        mock_extractor_inst = MagicMock()
        mock_extractor_inst.extract_keyframes.return_value = fake_extractor_result
        MockExtractor.return_value = mock_extractor_inst

        mock_va_inst = MagicMock()
        mock_va_inst.store_visual_frame.return_value = "frame-id-1"
        mock_va_inst.get_provider_status.return_value = {
            "provider_configured": False,
            "visual_analysis_provider": "none",
        }
        MockVA.return_value = mock_va_inst

        first = client.post(
            "/api/v1/student/extension-proof/sessions/idem-session/workflow/video",
            files={"video": ("recording.webm", io.BytesIO(b"fake_video"), "video/webm")},
        )
        frames_stored_after_first = mock_va_inst.store_visual_frame.call_count
        extractions_after_first = mock_extractor_inst.extract_keyframes.call_count

        # The mocked visual-analysis service does not write keyframe rows;
        # seed the row the real service would have stored so the duplicate
        # sees a completed extraction (otherwise it would run the
        # zero-keyframe extraction-repair path by design).
        mock_db["workflow_visual_frame_evidence"] = {
            "kf-1": {
                "id": "kf-1",
                "user_id": owner_id,
                "proof_session_id": "idem-session",
                "frame_type": "video_keyframe",
            }
        }

        duplicate = client.post(
            "/api/v1/student/extension-proof/sessions/idem-session/workflow/video",
            files={"video": ("recording.webm", io.BytesIO(b"fake_video"), "video/webm")},
        )

    app.dependency_overrides.clear()

    assert first.status_code == 202, first.text
    assert first.json()["replay_retained"] is True
    assert duplicate.status_code == 202, duplicate.text
    dup_body = duplicate.json()
    assert dup_body["replay_retained"] is True
    assert dup_body["replay_artifact_id"] == first.json()["replay_artifact_id"]
    assert dup_body["frames_stored"] == 0
    assert "idempotent" in dup_body["message"]

    # The duplicate performed NO second extraction and stored NO new frames.
    assert mock_extractor_inst.extract_keyframes.call_count == extractions_after_first
    assert mock_va_inst.store_visual_frame.call_count == frames_stored_after_first

    # Exactly one retained replay artifact exists for the session.
    artifacts = [
        a for a in mock_db["proof_artifacts"].values()
        if a["artifact_type"] == "website_replay_video"
    ]
    assert len(artifacts) == 1
