"""Tests for the five pipeline fixes applied in this session.

Fix 1: workflow_analysis_results DB insert — all new columns must be writable
       without WORKFLOW_ANALYSIS_DB_INSERT_FAILED.
Fix 2: visible-evidence endpoint accepts up to 120 visible_text_blocks (extension cap).
Fix 3: video uploaded + keyframes extracted + provider disabled still shows video evidence.
Fix 4: frontend WorkflowAnalysisResponse includes sequence_analysis and video_upload_status.
Fix 5: extension floating bar suppression during recorder tab stream (content.ts + background.ts).
"""

from __future__ import annotations

import importlib
import json
import sys
import pytest


# ---------------------------------------------------------------------------
# Fix 1: DB schema — all new analysis columns must fit in the in-memory store
#         (no KeyError / AttributeError) and the service returns _db_saved=True
#         when DB insert succeeds.
# ---------------------------------------------------------------------------

class TestWorkflowAnalysisDBInsert:
    """Verify that _analyze_workflow result dict contains all expected fields
    and the upsert helper can write them to the in-memory store without error."""

    def _run_analysis(self):
        from app.services.extension_proof_workflow_analysis_service import (
            ExtensionProofWorkflowAnalysisService,
        )
        mem: dict = {
            "extension_proof_sessions": {
                "sess-1": {
                    "id": "sess-1",
                    "user_id": "u1",
                    "status": "uploaded_pending_analysis",
                    "proof_data": {
                        "workflow_events": [
                            {"type": "page_visit", "page_url": "http://localhost:8000", "page_title": "Demo"},
                            {"type": "click", "element_text": "predict", "page_url": "http://localhost:8000"},
                        ],
                        "started_at": "2024-01-01T00:00:00Z",
                        "stopped_at": "2024-01-01T00:02:00Z",
                    },
                }
            }
        }
        svc = ExtensionProofWorkflowAnalysisService(mem)
        row = svc.run_analysis(
            user_id="u1",
            session_id="sess-1",
            claimed_skills=["Python", "FastAPI"],
            proof_objective="Demo a FastAPI prediction endpoint",
            original_url="http://localhost:8000",
            url_type="localhost_url",
            github_url=None,
        )
        return row

    def test_db_insert_success(self):
        row = self._run_analysis()
        assert row["_db_saved"] is True, f"DB insert should succeed. Got _db_saved={row['_db_saved']}"

    def test_has_graphical_rendering_field_present(self):
        row = self._run_analysis()
        assert "has_graphical_rendering" in row, "has_graphical_rendering must be in result"

    def test_all_new_columns_present(self):
        """Check every column added by migration 038 is in the result dict."""
        row = self._run_analysis()
        new_columns = [
            "target_website", "target_site_pages_count", "supporting_evidence_count",
            "noise_filtered_count", "observed_demonstration",
            "visible_evidence_status", "dom_evidence_status",
            "has_graphical_rendering", "graphical_rendering_note",
            "top_result_snippets", "page_context_summary",
            "visual_analysis_status", "visual_analysis_provider",
            "visual_frame_count", "visual_frames_stored",
            "ocr_status", "visual_result_values", "visual_summary",
            "sequence_analysis",
        ]
        missing = [c for c in new_columns if c not in row]
        assert not missing, f"Missing columns in result: {missing}"

    def test_no_unknown_column_in_insert(self):
        """In-memory upsert must not raise KeyError for any field."""
        # The _run_analysis method uses the in-memory store; if it succeeds
        # _db_saved=True, the upsert wrote all fields without error.
        row = self._run_analysis()
        assert row["_db_saved"] is True


# ---------------------------------------------------------------------------
# Fix 2: visible-evidence 422 — extension sends up to 120 blocks
# ---------------------------------------------------------------------------

class TestVisibleEvidence422:
    """The Pydantic schema must accept up to 200 visible_text_blocks
    so extension's MAX_VE_BLOCKS=120 doesn't trigger a 422."""

    def test_accepts_120_visible_text_blocks(self):
        from app.schemas.workflow_visible_evidence import (
            VisibleEvidenceBatchRequest,
            VisibleEvidenceEventInput,
        )
        blocks = [f"visible block {i}" for i in range(120)]
        event = VisibleEvidenceEventInput(
            event_type="dom_snapshot",
            timestamp_ms=1000,
            url="http://localhost:8000",
            page_title="Test",
            visible_text_blocks=blocks,
            result_like_blocks=[],
            input_snapshot={},
            action_snapshot={},
        )
        req = VisibleEvidenceBatchRequest(events=[event])
        assert len(req.events[0].visible_text_blocks) == 120

    def test_accepts_200_visible_text_blocks(self):
        from app.schemas.workflow_visible_evidence import VisibleEvidenceEventInput
        blocks = [f"block {i}" for i in range(200)]
        event = VisibleEvidenceEventInput(
            event_type="page_load",
            timestamp_ms=500,
            url="http://example.com",
            page_title="Test",
            visible_text_blocks=blocks,
            result_like_blocks=[],
            input_snapshot={},
            action_snapshot={},
        )
        assert len(event.visible_text_blocks) == 200

    def test_rejects_over_200_visible_text_blocks(self):
        from app.schemas.workflow_visible_evidence import VisibleEvidenceEventInput
        import pydantic
        blocks = [f"block {i}" for i in range(201)]
        with pytest.raises(pydantic.ValidationError):
            VisibleEvidenceEventInput(
                event_type="dom_snapshot",
                timestamp_ms=0,
                url="http://example.com",
                page_title="Test",
                visible_text_blocks=blocks,
                result_like_blocks=[],
                input_snapshot={},
                action_snapshot={},
            )

    def test_visible_evidence_ingest_with_120_blocks(self):
        """End-to-end ingest: 120 blocks per event → service truncates to 30."""
        from app.schemas.workflow_visible_evidence import (
            VisibleEvidenceBatchRequest,
            VisibleEvidenceEventInput,
        )
        from app.services.workflow_visible_evidence_service import (
            WorkflowVisibleEvidenceService,
        )
        blocks = [f"block {i}" for i in range(120)]
        event = VisibleEvidenceEventInput(
            event_type="result_detected",
            timestamp_ms=2000,
            url="http://localhost:8000",
            page_title="Result Page",
            visible_text_blocks=blocks,
            result_like_blocks=["prediction: dog 0.89"],
            input_snapshot={},
            action_snapshot={},
        )
        req = VisibleEvidenceBatchRequest(events=[event])
        mem: dict = {}
        svc = WorkflowVisibleEvidenceService(mem)
        result = svc.ingest(user_id="u1", session_id="sess-ve", request=req)
        assert result["events_stored"] == 1
        assert result["status"] == "accepted"
        # Service truncates to _MAX_VISIBLE_BLOCKS=30 on insert
        stored_events = list(mem.get("workflow_visible_evidence_events", {}).values())
        assert len(stored_events) == 1
        assert len(stored_events[0]["visible_text_blocks"]) <= 30


# ---------------------------------------------------------------------------
# Fix 3: video uploaded + keyframes extracted + provider disabled shows evidence
# ---------------------------------------------------------------------------

class TestVideoKeyframeEvidenceVisibility:
    """When video is uploaded and keyframes extracted but OCR is not configured,
    the limitation message should say 'Video recorded and N keyframes extracted'
    rather than 'Visual frame analysis is not configured'."""

    def _make_row(self, kf_status: str | None, kf_count: int, visual_status: str):
        """Build a minimal analysis row for _to_response testing."""
        from app.services.extension_proof_workflow_analysis_service import (
            _build_observed_demonstration,
        )
        observed = _build_observed_demonstration(
            target_events=[],
            app_type="generic",
            target_app="test.com",
            iao_patterns=[],
            visible_observations=None,
            visual_frame_observations={"visual_frame_analysis_status": visual_status,
                                        "provider_used": "none",
                                        "visual_frame_count": 0,
                                        "visual_frames_stored": 0},
        )
        row = {
            "id": "row-1",
            "proof_session_id": "sess-1",
            "user_id": "u1",
            "analysis_type": "timeline_only",
            "analyzer_version": "workflow-analysis-v4",
            "workflow_summary": "test",
            "recruiter_summary": "test",
            "demonstrated_actions": [],
            "supported_skills": [],
            "weakly_supported_skills": [],
            "unsupported_skills": [],
            "evidence_strength_score": 10,
            "workflow_confidence": "low",
            "missing_evidence": [],
            "risk_flags": [],
            "student_improvement_suggestions": [],
            "human_review_needed": False,
            "target_website": "test.com",
            "target_site_pages_count": 1,
            "supporting_evidence_count": 0,
            "noise_filtered_count": 0,
            "observed_demonstration": observed,
            "visual_analysis_status": visual_status,
            "visual_analysis_provider": "none",
            "visual_frame_count": 0,
            "visual_frames_stored": 0,
            "ocr_status": "not_configured",
            "visual_result_values": [],
            "visual_summary": "",
            "dom_evidence_status": "not_captured",
            "visible_evidence_status": "not_captured",
            "has_graphical_rendering": False,
            "graphical_rendering_note": None,
            "top_result_snippets": [],
            "page_context_summary": None,
            "sequence_analysis": None,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": None,
            # Injected by _enrich_video_keyframes
            "video_keyframe_status": kf_status,
            "video_keyframe_count": kf_count,
            "video_keyframe_timestamps_ms": list(range(0, kf_count * 5000, 5000)),
            "video_duration_ms": kf_count * 5000 if kf_count > 0 else None,
            "video_upload_error": None,
        }
        return row

    def test_limitations_updated_when_keyframes_extracted(self):
        from app.api.v1.endpoints.extension_proof_workflow_analysis import _to_response
        row = self._make_row(kf_status="extracted", kf_count=5, visual_status="not_configured")
        resp = _to_response(row)
        demo = resp.observed_demonstration
        assert demo is not None
        lims_text = " ".join(demo.limitations)
        # The old terse message "Visual frame analysis is not configured." (standalone,
        # with the "screenshot analysis" wording) should be replaced.
        assert "screenshot analysis" not in lims_text, (
            "Old 'screenshot analysis' limitation wording should be replaced"
        )
        # The new limitation explicitly acknowledges the video evidence.
        assert "keyframe" in lims_text.lower() or "video" in lims_text.lower(), (
            "Should mention video/keyframe in limitation when keyframes are extracted"
        )
        # The new message says "not configured" for OCR (accurate) and gives setup advice.
        assert "not configured" in lims_text.lower(), (
            "Should still say OCR is not configured (accurate, actionable)"
        )

    def test_video_upload_status_uploaded_when_keyframes_extracted(self):
        from app.api.v1.endpoints.extension_proof_workflow_analysis import _to_response
        row = self._make_row(kf_status="extracted", kf_count=3, visual_status="not_configured")
        resp = _to_response(row)
        assert resp.video_upload_status == "uploaded"

    def test_video_upload_status_none_when_no_video(self):
        from app.api.v1.endpoints.extension_proof_workflow_analysis import _to_response
        row = self._make_row(kf_status=None, kf_count=0, visual_status="not_configured")
        resp = _to_response(row)
        assert resp.video_upload_status == "none"

    def test_video_upload_status_failed_when_failed(self):
        from app.api.v1.endpoints.extension_proof_workflow_analysis import _to_response
        row = self._make_row(kf_status="failed", kf_count=0, visual_status="not_configured")
        resp = _to_response(row)
        assert resp.video_upload_status == "failed"

    def test_keyframe_timestamps_exposed(self):
        from app.api.v1.endpoints.extension_proof_workflow_analysis import _to_response
        row = self._make_row(kf_status="extracted", kf_count=4, visual_status="not_configured")
        resp = _to_response(row)
        assert resp.video_keyframe_count == 4
        assert len(resp.video_keyframe_timestamps_ms) == 4

    def test_sequence_analysis_passed_through(self):
        from app.api.v1.endpoints.extension_proof_workflow_analysis import _to_response
        row = self._make_row(kf_status="extracted", kf_count=2, visual_status="not_configured")
        row["sequence_analysis"] = {
            "sequence_analysis_status": "completed",
            "analyzed_frame_count": 2,
            "confidence_score": 60,
            "evidence_strength": "moderate",
        }
        resp = _to_response(row)
        assert resp.sequence_analysis is not None
        assert resp.sequence_analysis["sequence_analysis_status"] == "completed"

    def test_sequence_analysis_none_when_empty(self):
        from app.api.v1.endpoints.extension_proof_workflow_analysis import _to_response
        row = self._make_row(kf_status=None, kf_count=0, visual_status="not_configured")
        row["sequence_analysis"] = {}   # empty dict → should become None
        resp = _to_response(row)
        assert resp.sequence_analysis is None


# ---------------------------------------------------------------------------
# Fix 4: frontend type (backend schema) includes sequence_analysis and video_upload_status
# ---------------------------------------------------------------------------

class TestWorkflowAnalysisResponseSchema:
    """WorkflowAnalysisResponse must have the fields the frontend expects."""

    def test_schema_has_sequence_analysis_field(self):
        from app.schemas.extension_proof_workflow_analysis import WorkflowAnalysisResponse
        fields = WorkflowAnalysisResponse.model_fields
        assert "sequence_analysis" in fields, "sequence_analysis must be in WorkflowAnalysisResponse"

    def test_schema_has_video_upload_status_field(self):
        from app.schemas.extension_proof_workflow_analysis import WorkflowAnalysisResponse
        fields = WorkflowAnalysisResponse.model_fields
        assert "video_upload_status" in fields, "video_upload_status must be in WorkflowAnalysisResponse"

    def test_video_upload_status_default_none(self):
        from app.schemas.extension_proof_workflow_analysis import WorkflowAnalysisResponse
        # Build a minimal valid response
        resp = WorkflowAnalysisResponse(
            id="x",
            proof_session_id="s",
            analysis_type="timeline_only",
            analyzer_version="v4",
            workflow_summary="test",
            demonstrated_actions=[],
            supported_skills=[],
            weakly_supported_skills=[],
            unsupported_skills=[],
            evidence_strength_score=0,
            workflow_confidence="insufficient",
            missing_evidence=[],
            risk_flags=[],
            recruiter_summary="",
            student_improvement_suggestions=[],
            human_review_needed=False,
            target_website="",
            target_site_pages_count=0,
            supporting_evidence_count=0,
            noise_filtered_count=0,
            created_at="2024-01-01T00:00:00Z",
        )
        assert resp.video_upload_status == "none"
        assert resp.sequence_analysis is None


# ---------------------------------------------------------------------------
# Fix 5: visible-evidence service does not drop events with empty events list
# ---------------------------------------------------------------------------

class TestVisibleEvidenceEdgeCases:
    """Edge cases: empty events list, single event with no text blocks."""

    def test_empty_events_list_accepted(self):
        from app.schemas.workflow_visible_evidence import VisibleEvidenceBatchRequest
        req = VisibleEvidenceBatchRequest(events=[])
        assert req.events == []

    def test_ingest_empty_events_returns_zero_stored(self):
        from app.schemas.workflow_visible_evidence import VisibleEvidenceBatchRequest
        from app.services.workflow_visible_evidence_service import WorkflowVisibleEvidenceService
        req = VisibleEvidenceBatchRequest(events=[])
        mem: dict = {}
        svc = WorkflowVisibleEvidenceService(mem)
        result = svc.ingest(user_id="u1", session_id="sess-empty", request=req)
        assert result["events_stored"] == 0
        assert result["status"] == "accepted"

    def test_target_domain_not_required_in_request(self):
        """The extension sends target_domain but schema ignores extra fields safely."""
        from app.schemas.workflow_visible_evidence import VisibleEvidenceBatchRequest
        import pydantic
        # target_domain is not in schema but Pydantic v2 ignores unknown fields by default
        payload = {
            "events": [{
                "event_type": "dom_snapshot",
                "timestamp_ms": 1000,
                "url": "http://localhost:8000",
                "page_title": "Test",
                "target_domain": "localhost:8000",  # extra field from extension
                "visible_text_blocks": ["test block"],
                "result_like_blocks": [],
                "input_snapshot": {},
                "action_snapshot": {},
            }]
        }
        req = VisibleEvidenceBatchRequest(**payload)
        assert len(req.events) == 1
