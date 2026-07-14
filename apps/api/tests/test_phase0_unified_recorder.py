"""Phase 0 — Unified MediaRecorder Flow tests.

Tests for:
1. _enrich_video_keyframes() — live query for video keyframe evidence.
2. WorkflowAnalysisResponse schema includes video keyframe fields.
3. video_keyframe_status is "extracted" when keyframe records exist.
4. video_keyframe_status is None when no video was uploaded.
5. video_upload_error flows through the response.
6. /workflow/video endpoint returns keyframe count in the response body.
7. Analysis stage "video_recording" is "complete" (Phase 0 implemented).

These tests run against the in-memory mock DB (no Supabase required).
"""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api import deps as _deps
from app.api.v1.endpoints.extension_proof_workflow_analysis import _enrich_video_keyframes
from app.services.extension_proof_workflow_analysis_service import _SESSION_TABLE

DEMO_USER_ID = "00000000-0000-0000-0000-000000000099"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_real_db_mock(keyframe_rows: list[dict]) -> Any:
    """Return a mock db object whose .table() chain simulates a Supabase query result."""
    mock_db = MagicMock()
    mock_resp = MagicMock()
    mock_resp.count = len(keyframe_rows)
    mock_resp.data = keyframe_rows
    # Chain: db.table(...).select(...).eq(...).eq(...).eq(...).execute()
    mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = mock_resp
    return mock_db


def _make_mem_session(mem_store: dict, proof_data: dict) -> str:
    """Insert a fake session into the in-memory store (matches service layer expectations)."""
    import uuid
    session_id = str(uuid.uuid4())
    mem_store.setdefault(_SESSION_TABLE, {})[session_id] = {
        "id": session_id,
        "user_id": DEMO_USER_ID,
        "status": "uploaded_pending_analysis",
        "proof_data": proof_data,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    return session_id


# ── _enrich_video_keyframes() ──────────────────────────────────────────────────

class TestEnrichVideoKeyframes:
    def test_returns_extracted_when_keyframes_exist(self):
        db = _make_real_db_mock([{"id": "f1"}, {"id": "f2"}, {"id": "f3"}])
        row: dict[str, Any] = {"proof_session_id": "sess-1"}
        result = _enrich_video_keyframes(db, "user-1", "sess-1", row)
        assert result["video_keyframe_status"] == "extracted"
        assert result["video_keyframe_count"] == 3
        assert result["video_upload_error"] is None

    def test_returns_null_when_no_keyframes(self):
        db = _make_real_db_mock([])
        row: dict[str, Any] = {"proof_session_id": "sess-1"}
        result = _enrich_video_keyframes(db, "user-1", "sess-1", row)
        assert result["video_keyframe_status"] is None
        assert result["video_keyframe_count"] == 0

    def test_dict_db_fails_gracefully(self):
        """In-memory dict db (used in tests) has no .table() — must not raise."""
        row: dict[str, Any] = {"proof_session_id": "sess-dict"}
        result = _enrich_video_keyframes({}, "user-1", "sess-dict", row)
        # Falls back to null status — never raises
        assert result["video_keyframe_status"] is None
        assert result["video_keyframe_count"] == 0

    def test_preserves_existing_row_fields(self):
        db = _make_real_db_mock([{"id": "f1"}])
        row: dict[str, Any] = {"proof_session_id": "sess-1", "workflow_summary": "Great job", "evidence_strength_score": 75}
        result = _enrich_video_keyframes(db, "user-1", "sess-1", row)
        assert result["workflow_summary"] == "Great job"
        assert result["evidence_strength_score"] == 75
        assert result["video_keyframe_status"] == "extracted"

    def test_count_from_data_length_when_count_attribute_none(self):
        """Fallback: when resp.count is None, use len(resp.data)."""
        db = MagicMock()
        mock_resp = MagicMock()
        mock_resp.count = None  # Supabase sometimes omits count
        mock_resp.data = [{"id": "f1"}, {"id": "f2"}]
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = mock_resp
        row: dict[str, Any] = {}
        result = _enrich_video_keyframes(db, "user-1", "sess-1", row)
        assert result["video_keyframe_status"] == "extracted"
        assert result["video_keyframe_count"] == 2


# ── WorkflowAnalysisResponse schema ───────────────────────────────────────────

class TestWorkflowAnalysisResponseSchema:
    def test_video_keyframe_fields_have_defaults(self):
        from app.schemas.extension_proof_workflow_analysis import WorkflowAnalysisResponse
        # Should not raise with missing video fields (all default to None/0)
        resp = WorkflowAnalysisResponse(
            id="id-1",
            proof_session_id="sess-1",
            analysis_type="timeline_only",
            analyzer_version="1.0",
            workflow_summary="Test",
            demonstrated_actions=[],
            supported_skills=["Python"],
            weakly_supported_skills=[],
            unsupported_skills=[],
            evidence_strength_score=70,
            workflow_confidence="medium",
            missing_evidence=[],
            risk_flags=[],
            recruiter_summary="Good",
            student_improvement_suggestions=[],
            human_review_needed=False,
            created_at="2026-01-01T00:00:00Z",
        )
        assert resp.video_keyframe_status is None
        assert resp.video_keyframe_count == 0
        assert resp.video_upload_error is None

    def test_video_keyframe_status_extracted(self):
        from app.schemas.extension_proof_workflow_analysis import WorkflowAnalysisResponse
        resp = WorkflowAnalysisResponse(
            id="id-1",
            proof_session_id="sess-1",
            analysis_type="timeline_only",
            analyzer_version="1.0",
            workflow_summary="Test",
            demonstrated_actions=[],
            supported_skills=[],
            weakly_supported_skills=[],
            unsupported_skills=[],
            evidence_strength_score=70,
            workflow_confidence="medium",
            missing_evidence=[],
            risk_flags=[],
            recruiter_summary="Good",
            student_improvement_suggestions=[],
            human_review_needed=False,
            video_keyframe_status="extracted",
            video_keyframe_count=5,
            created_at="2026-01-01T00:00:00Z",
        )
        assert resp.video_keyframe_status == "extracted"
        assert resp.video_keyframe_count == 5


# ── Analysis endpoint: video_keyframe fields in response ──────────────────────

def _make_proof_data() -> dict:
    return {
        "workflow_events": [
            {
                "type": "page_visit",
                "timestamp": "2026-01-01T00:00:01Z",
                "page_url": "https://example.com/app",
                "page_title": "Demo App",
            }
        ],
        "screenshots": [],
        "browser_metadata": {"userAgent": "test"},
        "extension_version": "0.1.0",
        "started_at": "2026-01-01T00:00:00Z",
        "stopped_at": "2026-01-01T00:01:00Z",
        "student_final_note": None,
    }


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict):  # type: ignore[override]
    app.dependency_overrides[_deps.get_current_user_id] = lambda: DEMO_USER_ID
    app.dependency_overrides[_deps.get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestAnalysisEndpointVideoKeyframes:
    """Integration tests via TestClient using in-memory store."""

    def test_analysis_response_includes_video_keyframe_fields(self, client: TestClient, mem_store: dict):
        """video_keyframe_status and video_keyframe_count always present in response."""
        session_id = _make_mem_session(mem_store, _make_proof_data())
        # Trigger analysis
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/workflow",
            json={
                "claimed_skills": ["Python"],
                "proof_objective": "demo",
                "original_url": "https://example.com/app",
                "url_type": "live_deployed_url",
                "github_url": None,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "video_keyframe_status" in body
        assert "video_keyframe_count" in body
        # No video uploaded → null status and 0 count
        assert body["video_keyframe_status"] is None
        assert body["video_keyframe_count"] == 0

    def test_analysis_stages_include_video_recording(self, client: TestClient, mem_store: dict):
        """video_recording stage must be 'complete' (Phase 0 implemented)."""
        session_id = _make_mem_session(mem_store, _make_proof_data())
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/workflow",
            json={
                "claimed_skills": ["Python"],
                "proof_objective": "demo",
                "original_url": "https://example.com/app",
                "url_type": "live_deployed_url",
                "github_url": None,
            },
        )
        assert r.status_code == 200, r.text
        stages = r.json()["stages"]
        vr = next((s for s in stages if s["key"] == "video_recording"), None)
        assert vr is not None, f"video_recording stage missing — keys: {[s['key'] for s in stages]}"
        assert vr["status"] == "complete"

    def test_get_analysis_response_includes_video_keyframe_fields(self, client: TestClient, mem_store: dict):
        """GET analysis also returns video_keyframe_status and video_keyframe_count."""
        session_id = _make_mem_session(mem_store, _make_proof_data())
        # Run analysis first (stores it in mem_store)
        client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/workflow",
            json={
                "claimed_skills": ["Python"],
                "proof_objective": "demo",
                "original_url": "https://example.com/app",
                "url_type": "live_deployed_url",
                "github_url": None,
            },
        )
        # Now GET the stored analysis
        r = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analysis/workflow",
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "video_keyframe_status" in body
        assert "video_keyframe_count" in body
        assert body["video_keyframe_count"] == 0  # no video uploaded in test


# ── Video upload endpoint smoke test ──────────────────────────────────────────

class TestVideoUploadEndpoint:
    def test_upload_webm_returns_202_with_keyframe_count(self):
        """Uploading a WebM file returns 202 with video_analysis_status and keyframe_count."""
        from app.services.video_keyframe_extractor_service import (
            VIDEO_STATUS_ANALYZED, VideoKeyframeResult,
        )

        fake_result = VideoKeyframeResult(
            video_analysis_status=VIDEO_STATUS_ANALYZED,
            keyframe_count=3,
            selected_frame_timestamps_ms=[0, 1000, 2000],
            extraction_method="cv2_interval",
            duration_ms=3000,
            frame_width=1280,
            frame_height=720,
            limitations=[],
            _extracted_frames=[(0, b"jpg1"), (1000, b"jpg2"), (2000, b"jpg3")],
        )

        store = {
            _SESSION_TABLE: {
                "test-sess": {
                    "id": "test-sess",
                    "user_id": "user-1",
                    "status": "recording",
                }
            }
        }
        app.dependency_overrides[_deps.get_db] = lambda: store
        app.dependency_overrides[_deps.get_current_user_id] = lambda: "user-1"

        client = TestClient(app)

        with (
            patch("app.api.v1.endpoints.workflow_visual_frames.VideoKeyframeExtractorService") as MockExt,
            patch("app.api.v1.endpoints.workflow_visual_frames.WorkflowVisualAnalysisService") as MockVA,
        ):
            mock_ext = MagicMock()
            mock_ext.extract_keyframes.return_value = fake_result
            MockExt.return_value = mock_ext

            mock_va = MagicMock()
            mock_va.store_visual_frame.return_value = "frame-1"
            mock_va.get_provider_status.return_value = {
                "provider_configured": False,
                "visual_analysis_provider": "none",
            }
            MockVA.return_value = mock_va

            resp = client.post(
                "/api/v1/student/extension-proof/sessions/test-sess/workflow/video",
                files={"video": ("recording.webm", io.BytesIO(b"fake_video_bytes"), "video/webm")},
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["video_analysis_status"] == VIDEO_STATUS_ANALYZED
        assert body["keyframe_count"] == 3
        # Privacy: no raw frame bytes or storage paths
        assert "_extracted_frames" not in body
        assert "frame_storage_path" not in body
        # Exact error message is in the response for debugging
        assert "message" in body

    def test_upload_too_large_returns_message(self):
        """Oversized video body gets a descriptive message in the response."""
        from app.services.video_keyframe_extractor_service import (
            VideoKeyframeResult,
        )

        fake_result = VideoKeyframeResult(
            video_analysis_status="limit_exceeded",
            keyframe_count=0,
            selected_frame_timestamps_ms=[],
            extraction_method="rejected",
            duration_ms=None,
            frame_width=None,
            frame_height=None,
            limitations=["File exceeds 100 MB limit"],
            _extracted_frames=[],
        )

        store = {
            _SESSION_TABLE: {
                "test-sess": {
                    "id": "test-sess",
                    "user_id": "user-1",
                    "status": "recording",
                }
            }
        }
        app.dependency_overrides[_deps.get_db] = lambda: store
        app.dependency_overrides[_deps.get_current_user_id] = lambda: "user-1"
        client = TestClient(app)

        with patch("app.api.v1.endpoints.workflow_visual_frames.VideoKeyframeExtractorService") as MockExt:
            mock_ext = MagicMock()
            mock_ext.extract_keyframes.return_value = fake_result
            MockExt.return_value = mock_ext

            # Send a ~1 byte payload that exceeds the mocked limit
            resp = client.post(
                "/api/v1/student/extension-proof/sessions/test-sess/workflow/video",
                files={"video": ("big.webm", io.BytesIO(b"x"), "video/webm")},
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["video_analysis_status"] == "limit_exceeded"
        assert "message" in body
        assert body["message"]  # non-empty — exact reason surfaced
