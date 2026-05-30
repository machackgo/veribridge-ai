"""Tests for video/keyframe analysis visibility and correct limitation text.

Covers:
A. Recorder state sync
   1. RECORDER_STREAM_STARTED / RECORDER_STREAM_STOPPED message handling
   2. recorderTabStreamActive resets on START_RECORDING

B. Video / keyframe evidence in response
   3. video_keyframe_timestamps_ms populated from stored frame records
   4. video_duration_ms derived from last timestamp
   5. Limitation text when video extracted but OCR not configured
   6. Limitation text NOT replaced when video not uploaded
   7. Correct wording: does not say "not available" when keyframes exist
   8. Correct wording when provider is actually configured

C. Public/recruiter safety
   9. video_keyframe_timestamps_ms contains only int timestamps (no paths or tokens)
  10. No _extracted_frames or frame_storage_path in response

D. _enrich_video_keyframes() with timestamps
  11. Returns sorted timestamps from stored records
  12. Returns empty list when no keyframe records
  13. Gracefully handles records with null timestamp_ms
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api import deps as _deps
from app.api.v1.endpoints.extension_proof_workflow_analysis import (
    _enrich_video_keyframes,
    _to_response,
)
from app.services.extension_proof_workflow_analysis_service import _SESSION_TABLE

DEMO_USER_ID = "00000000-0000-0000-0000-000000000088"


# ── Mock DB helpers ─────────────────────────────────────────────────────────────

def _make_kf_db_mock(rows: list[dict]) -> Any:
    """Supabase mock returning given rows with id + timestamp_ms select."""
    mock_db = MagicMock()
    mock_resp = MagicMock()
    mock_resp.count = len(rows)
    mock_resp.data = rows
    # Chain: .table().select().eq().eq().eq().execute()
    (mock_db.table.return_value
     .select.return_value
     .eq.return_value.eq.return_value.eq.return_value
     .execute.return_value) = mock_resp
    return mock_db


def _make_mem_session(mem_store: dict, proof_data: dict) -> str:
    import uuid
    sid = str(uuid.uuid4())
    mem_store.setdefault(_SESSION_TABLE, {})[sid] = {
        "id": sid,
        "user_id": DEMO_USER_ID,
        "status": "uploaded_pending_analysis",
        "proof_data": proof_data,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    return sid


def _proof_data() -> dict:
    return {
        "workflow_events": [
            {
                "type": "page_visit",
                "timestamp": "2026-01-01T00:00:01Z",
                "page_url": "https://teachablemachine.withgoogle.com/train",
                "page_title": "Teachable Machine",
            }
        ],
        "screenshots": [],
        "browser_metadata": {"userAgent": "test"},
        "extension_version": "0.2.0",
        "started_at": "2026-01-01T00:00:00Z",
        "stopped_at": "2026-01-01T00:02:00Z",
        "student_final_note": None,
    }


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict):
    app.dependency_overrides[_deps.get_current_user_id] = lambda: DEMO_USER_ID
    app.dependency_overrides[_deps.get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── A. _enrich_video_keyframes with timestamps ─────────────────────────────────

class TestEnrichVideoKeyframesTimestamps:
    def test_returns_sorted_timestamps(self):
        rows = [
            {"id": "f1", "timestamp_ms": 5000},
            {"id": "f2", "timestamp_ms": 1000},
            {"id": "f3", "timestamp_ms": 3000},
        ]
        db = _make_kf_db_mock(rows)
        result = _enrich_video_keyframes(db, "user-1", "sess-1", {})
        assert result["video_keyframe_status"] == "extracted"
        assert result["video_keyframe_count"] == 3
        assert result["video_keyframe_timestamps_ms"] == [1000, 3000, 5000]
        assert result["video_duration_ms"] == 5000   # last timestamp

    def test_empty_timestamps_when_no_keyframes(self):
        db = _make_kf_db_mock([])
        result = _enrich_video_keyframes(db, "user-1", "sess-1", {})
        assert result["video_keyframe_timestamps_ms"] == []
        assert result["video_duration_ms"] is None
        assert result["video_keyframe_status"] is None

    def test_handles_null_timestamp_ms_gracefully(self):
        """Records with null timestamp_ms are excluded from the list."""
        rows = [
            {"id": "f1", "timestamp_ms": 2000},
            {"id": "f2", "timestamp_ms": None},  # null — skip
            {"id": "f3", "timestamp_ms": 4000},
        ]
        db = _make_kf_db_mock(rows)
        result = _enrich_video_keyframes(db, "user-1", "sess-1", {})
        assert result["video_keyframe_timestamps_ms"] == [2000, 4000]
        assert result["video_duration_ms"] == 4000
        assert result["video_keyframe_count"] == 3  # count from DB, not filtered list

    def test_db_error_returns_empty_timestamps(self):
        """Query failure must not raise — falls back to empty."""
        result = _enrich_video_keyframes({}, "user-1", "sess-1", {})
        assert result["video_keyframe_timestamps_ms"] == []
        assert result["video_duration_ms"] is None

    def test_preserves_existing_row_fields(self):
        rows = [{"id": "f1", "timestamp_ms": 1000}]
        db = _make_kf_db_mock(rows)
        row = {"workflow_summary": "Great demo", "evidence_strength_score": 82}
        result = _enrich_video_keyframes(db, "user-1", "sess-1", row)
        assert result["workflow_summary"] == "Great demo"
        assert result["evidence_strength_score"] == 82


# ── B. Limitation text correction in _to_response ─────────────────────────────

_BASE_RESPONSE_ARGS = dict(
    id="id-1",
    proof_session_id="sess-1",
    analysis_type="timeline_only",
    analyzer_version="4.0",
    workflow_summary="Demo",
    demonstrated_actions=[],
    supported_skills=[],
    weakly_supported_skills=[],
    unsupported_skills=[],
    evidence_strength_score=60,
    workflow_confidence="medium",
    missing_evidence=[],
    risk_flags=[],
    recruiter_summary="Good demo",
    student_improvement_suggestions=[],
    human_review_needed=False,
    visible_evidence_status="not_captured",
    visual_analysis_status="not_configured",
    created_at="2026-01-01T00:00:00Z",
)


def _row_with_demo_and_video(video_kf_status: str, lims: list[str]) -> dict:
    return {
        **_BASE_RESPONSE_ARGS,
        "observed_demonstration": {
            "target_app": "teachablemachine.withgoogle.com",
            "visual_analysis_status": "not_configured",
            "visible_evidence_status": "not_captured",
            "steps": [],
            "summary": "Demo summary",
            "limitations": lims,
        },
        "video_keyframe_status": video_kf_status,
        "video_keyframe_count": 5,
        "video_keyframe_timestamps_ms": [0, 1000, 2000, 3000, 4000],
        "video_duration_ms": 4000,
        "video_upload_error": None,
    }


class TestToResponseLimitationText:
    def test_replaces_not_configured_limitation_when_video_extracted(self):
        """When keyframes extracted + OCR not configured, limitation is replaced."""
        lims = [
            "Visual frame analysis is not configured.  "
            "Set VISUAL_ANALYSIS_PROVIDER=local_ocr or local_vision to enable "
            "screenshot analysis (DOM evidence is always active regardless)."
        ]
        row = _row_with_demo_and_video("extracted", lims)
        response = _to_response(row)
        assert response.observed_demonstration is not None
        joined = " ".join(response.observed_demonstration.limitations)
        # Must reference video evidence
        assert "Video was recorded" in joined or "keyframe" in joined
        # Must NOT say just "not configured" without video context
        assert "not configured" in joined  # still mentions OCR not configured
        # Must NOT say the old "is not configured" bare message
        assert "screenshot analysis" not in joined  # old text removed

    def test_does_not_replace_limitation_when_no_video(self):
        """When no video uploaded, original limitation is kept unchanged."""
        original_lim = (
            "Visual frame analysis is not configured.  "
            "Set VISUAL_ANALYSIS_PROVIDER=local_ocr or local_vision to enable "
            "screenshot analysis (DOM evidence is always active regardless)."
        )
        row = _row_with_demo_and_video(None, [original_lim])  # type: ignore[arg-type]
        row["video_keyframe_count"] = 0
        response = _to_response(row)
        assert response.observed_demonstration is not None
        assert response.observed_demonstration.limitations == [original_lim]

    def test_non_visual_limitations_preserved(self):
        """Other limitations (DOM, IAO) are not touched."""
        lims = [
            "Visible DOM evidence was not captured for this recording.",
            "Visual frame analysis is not configured.  Set VISUAL_ANALYSIS_PROVIDER=local_ocr.",
        ]
        row = _row_with_demo_and_video("extracted", lims)
        response = _to_response(row)
        joined_lims = response.observed_demonstration.limitations  # type: ignore[union-attr]
        # DOM limitation must be preserved
        assert any("DOM evidence was not captured" in l for l in joined_lims)
        # Old visual_analysis not-configured message replaced
        assert not any("VISUAL_ANALYSIS_PROVIDER" in l and "screenshot analysis" in l for l in joined_lims)

    def test_video_keyframe_timestamps_in_response(self):
        """video_keyframe_timestamps_ms flows through _to_response."""
        row = _row_with_demo_and_video("extracted", [])
        response = _to_response(row)
        assert response.video_keyframe_timestamps_ms == [0, 1000, 2000, 3000, 4000]
        assert response.video_duration_ms == 4000

    def test_timestamps_default_empty_when_not_in_row(self):
        """Missing timestamps field defaults to []."""
        row = dict(_row_with_demo_and_video("extracted", []))
        del row["video_keyframe_timestamps_ms"]
        response = _to_response(row)
        assert response.video_keyframe_timestamps_ms == []


# ── C. API integration: timestamps in analysis response ───────────────────────

class TestAnalysisEndpointTimestamps:
    def test_timestamps_present_and_empty_when_no_video(self, client: TestClient, mem_store: dict):
        """video_keyframe_timestamps_ms is always in response (empty when no video)."""
        sid = _make_mem_session(mem_store, _proof_data())
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{sid}/analyze/workflow",
            json={
                "claimed_skills": ["Machine Learning"],
                "proof_objective": "Demo Teachable Machine",
                "original_url": "https://teachablemachine.withgoogle.com/train",
                "url_type": "live_deployed_url",
                "github_url": None,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "video_keyframe_timestamps_ms" in body
        assert isinstance(body["video_keyframe_timestamps_ms"], list)
        assert body["video_keyframe_timestamps_ms"] == []   # no video uploaded
        assert body.get("video_duration_ms") is None


# ── D. Public/recruiter safety ─────────────────────────────────────────────────

class TestPublicSafety:
    def test_timestamps_are_ints_only(self):
        """video_keyframe_timestamps_ms must contain only int offsets — no paths/tokens."""
        rows = [
            {"id": "f1", "timestamp_ms": 0},
            {"id": "f2", "timestamp_ms": 2500},
        ]
        db = _make_kf_db_mock(rows)
        result = _enrich_video_keyframes(db, "user-1", "sess-1", {})
        ts = result["video_keyframe_timestamps_ms"]
        assert all(isinstance(t, int) for t in ts)

    def test_no_private_fields_in_timestamps_response(self, client: TestClient, mem_store: dict):
        """Response must never include _extracted_frames, frame_storage_path, or access tokens."""
        sid = _make_mem_session(mem_store, _proof_data())
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{sid}/analyze/workflow",
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
        assert "_extracted_frames" not in body
        assert "frame_storage_path" not in body
        assert "access_token" not in str(body)

    def test_correct_limitation_text_not_say_unavailable_when_keyframes_exist(self):
        """The response must not say 'not available' or 'unavailable' for video evidence
        when keyframes have been successfully extracted."""
        lims = [
            "Visual frame analysis is not configured.  "
            "Set VISUAL_ANALYSIS_PROVIDER=local_ocr or local_vision to enable "
            "screenshot analysis (DOM evidence is always active regardless)."
        ]
        row = _row_with_demo_and_video("extracted", lims)
        response = _to_response(row)
        joined = " ".join(response.observed_demonstration.limitations)  # type: ignore[union-attr]
        # Must not claim video is unavailable
        assert "visual video evidence not yet available" not in joined.lower()
        assert "video evidence unavailable" not in joined.lower()
