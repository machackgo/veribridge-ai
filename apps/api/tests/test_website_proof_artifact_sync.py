"""Tests for Website Proof → Skill Evidence Artifact Sync.

Covers:
  ✓ sync creates skill pipelines for detected skills
  ✓ sync creates workflow artifact
  ✓ sync creates OCR artifact when OCR evidence exists
  ✓ sync creates DOM artifact when DOM evidence exists
  ✓ sync creates Qwen artifact when visual reasoning analyzed
  ✓ sync skips Qwen artifact when status != analyzed
  ✓ sync creates keyframe artifact when video keyframes exist
  ✓ sync creates transcript artifact when transcript exists
  ✓ sync creates document artifact when document evidence exists
  ✓ sync creates review artifact when AI review exists
  ✓ sync skips transcript when transcript is empty/short
  ✓ sync skips OCR when has_ocr_evidence is False
  ✓ sync skips DOM when dom_evidence_status is not_captured
  ✓ sync returns already_synced=True on second call (idempotent)
  ✓ artifact visibility defaults to protected
  ✓ existing pipeline visibility is NOT overwritten
  ✓ unsafe fields are stripped from artifact_data
  ✓ recruiter-safe view masks protected artifacts (empty artifact_data)
  ✓ sync returns no_skills error when no analysis data exists
  ✓ HTTP endpoint returns 200 with correct shape
  ✓ skills from weakly_supported_skills are included

All storage is in-memory (dict mode).
No real network calls.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.services.website_proof_artifact_sync_service import (
    WebsiteProofArtifactSyncService,
    _strip_unsafe,
    _infer_category,
)
from app.services.skill_evidence_pipeline_service import SkillEvidencePipelineService

# ── Constants ─────────────────────────────────────────────────────────────────

STUDENT_A = "aaaaaaaa-1111-0000-0000-000000000001"
SESSION_1 = "sessssss-1111-0000-0000-000000000001"
SESSION_2 = "sessssss-2222-0000-0000-000000000002"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def proof_db() -> dict:
    """In-memory store for proof analysis tables."""
    return {}


@pytest.fixture()
def pipeline_db() -> dict:
    """In-memory store for skill_evidence_pipelines / artifacts tables."""
    return {}


@pytest.fixture()
def svc(proof_db: dict, pipeline_db: dict) -> WebsiteProofArtifactSyncService:
    return WebsiteProofArtifactSyncService(db=proof_db, pipeline_db=pipeline_db)


@pytest.fixture()
def client(proof_db: dict, pipeline_db: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: STUDENT_A
    app.dependency_overrides[get_db] = lambda: proof_db
    app.dependency_overrides[get_pipeline_db] = lambda: pipeline_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _seed_workflow(proof_db: dict, user_id: str, session_id: str, **kwargs) -> None:
    row_id = str(uuid4())
    proof_db.setdefault("workflow_analysis_results", {})[row_id] = {
        "id": row_id,
        "user_id": user_id,
        "proof_session_id": session_id,
        "supported_skills": ["Machine Learning", "React"],
        "weakly_supported_skills": ["TypeScript"],
        "evidence_strength_score": 75,
        "workflow_confidence": "strong",
        "workflow_summary": "Student demonstrated ML inference on a live app.",
        "recruiter_summary": "Strong evidence of ML workflow.",
        "target_website": "http://demo.example.com",
        "dom_evidence_status": "available",
        "visible_evidence_status": "available",
        "frame_ocr_evidence_summary": {
            "has_ocr_evidence": True,
            "frames_analyzed": 3,
            "top_ocr_snippets": ["accuracy: 92%", "prediction: dog 0.89"],
            "detected_page_context": "ml_demo",
            "skill_signals": [
                {"skill": "Machine Learning", "ocr_support": True, "reasoning": "accuracy score visible"},
            ],
        },
        "visual_reasoning_summary": {
            "status": "analyzed",
            "frames_analyzed": 2,
            "summary": "ML inference UI observed with prediction output",
            "observations": [],
            "supported_signals": ["Machine Learning"],
            "missing_claims": [],
        },
        "created_at": "2026-01-01T00:00:00+00:00",
        **kwargs,
    }


def _seed_project_defense(proof_db: dict, user_id: str, session_id: str, **kwargs) -> None:
    proof_db.setdefault("project_defense_analysis_results", {})[session_id] = {
        "user_id": user_id,
        "proof_session_id": session_id,
        "transcript_text": "I built this ML model using TensorFlow. I trained it on MNIST and achieved 98% accuracy.",
        "refined_transcript": "I built this ML model using TensorFlow. I trained it on MNIST and achieved 98% accuracy.",
        "skills_mentioned": ["Machine Learning", "React"],
        "skills_explained_well": ["Machine Learning"],
        "ownership_signal_score": 80,
        "technical_depth_score": 75,
        "overall_defense_score": 78,
        "recruiter_summary": "Candidate explained ML model selection clearly.",
        "recommended_improvements": ["Describe deployment pipeline."],
        "created_at": "2026-01-01T00:00:00+00:00",
        **kwargs,
    }


def _seed_optional_doc(proof_db: dict, user_id: str, session_id: str) -> None:
    row_id = str(uuid4())
    proof_db.setdefault("optional_evidence_submissions", {})[row_id] = {
        "id": row_id,
        "user_id": user_id,
        "proof_session_id": session_id,
        "source_type": "document",
        "file_path": "/uploads/project_report.pdf",
        "status": "analyzed",
        "evidence_objects": [
            {
                "skill_name": "Machine Learning",
                "confidence": "high",
                "snippet": "We trained a convolutional neural network on MNIST.",
            }
        ],
        "analysis_json": {},
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def _seed_frames(proof_db: dict, user_id: str, session_id: str, count: int = 2) -> None:
    for i in range(count):
        row_id = str(uuid4())
        proof_db.setdefault("workflow_visual_frame_evidence", {})[row_id] = {
            "id": row_id,
            "user_id": user_id,
            "proof_session_id": session_id,
            "frame_type": "video_keyframe",
            "timestamp_ms": i * 1000,
            "visual_summary": f"Frame {i}: ML inference UI visible",
            "ocr_text": ["accuracy: 92%"],
            "confidence_score": 0.85,
            "visual_reasoning_json": None,
        }


def _seed_review(proof_db: dict, user_id: str, session_id: str) -> None:
    row_id = str(uuid4())
    proof_db.setdefault("ai_domain_review_results", {})[row_id] = {
        "id": row_id,
        "user_id": user_id,
        "proof_session_id": session_id,
        "ai_domain_review_status": "ai_domain_reviewed",
        "domain_review_score": 82,
        "recruiter_summary": "Strong ML evidence confirmed by AI review.",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T01:00:00+00:00",
    }


# ── Unit tests ────────────────────────────────────────────────────────────────

class TestSyncCreatesSkillPipelines:
    def test_creates_pipelines_for_detected_skills(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        result = svc.sync(STUDENT_A, SESSION_1)
        assert result.pipelines_upserted > 0
        assert "Machine Learning" in result.skills_synced
        assert "React" in result.skills_synced
        pipeline_svc = SkillEvidencePipelineService(pipeline_db)
        pipelines = pipeline_svc.list_pipelines_for_student(STUDENT_A)
        skill_names = [p.skill_name for p in pipelines]
        assert "Machine Learning" in skill_names
        assert "React" in skill_names

    def test_includes_weakly_supported_skills(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        result = svc.sync(STUDENT_A, SESSION_1)
        assert "TypeScript" in result.skills_synced

    def test_pipeline_visibility_defaults_to_protected(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        svc.sync(STUDENT_A, SESSION_1)
        pipeline_svc = SkillEvidencePipelineService(pipeline_db)
        for p in pipeline_svc.list_pipelines_for_student(STUDENT_A):
            assert p.visibility_status == "protected"

    def test_existing_pipeline_visibility_not_overwritten(self, svc, proof_db, pipeline_db):
        # Pre-create pipeline with public visibility
        pipeline_svc = SkillEvidencePipelineService(pipeline_db)
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        pipeline_svc.upsert_pipeline(
            STUDENT_A,
            SkillEvidencePipelineCreate(
                skill_name="Machine Learning",
                skill_category="AI/ML",
                confidence_score=80,
                visibility_status="public",
            ),
        )
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        svc.sync(STUDENT_A, SESSION_1)
        # Visibility should remain public
        for p in pipeline_svc.list_pipelines_for_student(STUDENT_A):
            if p.skill_name == "Machine Learning":
                assert p.visibility_status == "public"
                break
        else:
            pytest.fail("Machine Learning pipeline not found")


class TestWorkflowArtifact:
    def test_creates_workflow_artifact(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        result = svc.sync(STUDENT_A, SESSION_1)
        assert "workflow" in result.artifact_types_created
        assert result.artifacts_created > 0

    def test_workflow_artifact_is_protected(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        svc.sync(STUDENT_A, SESSION_1)
        pipeline_svc = SkillEvidencePipelineService(pipeline_db)
        for p in pipeline_svc.list_pipelines_for_student(STUDENT_A):
            for a in pipeline_svc._list_artifacts_for_pipeline_by_id(p.id):
                if a.source_type == "workflow":
                    assert a.visibility == "protected"

    def test_workflow_artifact_data_contains_session_id(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        svc.sync(STUDENT_A, SESSION_1)
        pipeline_svc = SkillEvidencePipelineService(pipeline_db)
        found = False
        for p in pipeline_svc.list_pipelines_for_student(STUDENT_A):
            for a in pipeline_svc._list_artifacts_for_pipeline_by_id(p.id):
                if a.source_type == "workflow":
                    assert a.artifact_data.get("proof_session_id") == SESSION_1
                    found = True
        assert found


class TestOcrArtifact:
    def test_creates_ocr_artifact_when_evidence_exists(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        result = svc.sync(STUDENT_A, SESSION_1)
        assert "ocr" in result.artifact_types_created

    def test_skips_ocr_artifact_when_no_evidence(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1, frame_ocr_evidence_summary={"has_ocr_evidence": False})
        result = svc.sync(STUDENT_A, SESSION_1)
        assert "ocr" not in result.artifact_types_created

    def test_skips_ocr_artifact_when_summary_missing(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1, frame_ocr_evidence_summary=None)
        result = svc.sync(STUDENT_A, SESSION_1)
        assert "ocr" not in result.artifact_types_created


class TestDomArtifact:
    def test_creates_dom_artifact_when_evidence_available(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        result = svc.sync(STUDENT_A, SESSION_1)
        assert "dom" in result.artifact_types_created

    def test_skips_dom_artifact_when_not_captured(self, svc, proof_db, pipeline_db):
        _seed_workflow(
            proof_db, STUDENT_A, SESSION_1,
            dom_evidence_status="not_captured",
            visible_evidence_status="not_captured",
        )
        result = svc.sync(STUDENT_A, SESSION_1)
        assert "dom" not in result.artifact_types_created


class TestQwenArtifact:
    def test_creates_qwen_artifact_when_analyzed(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        result = svc.sync(STUDENT_A, SESSION_1)
        assert "qwen" in result.artifact_types_created

    def test_skips_qwen_artifact_when_status_not_analyzed(self, svc, proof_db, pipeline_db):
        _seed_workflow(
            proof_db, STUDENT_A, SESSION_1,
            visual_reasoning_summary={"status": "disabled", "frames_analyzed": 0},
        )
        result = svc.sync(STUDENT_A, SESSION_1)
        assert "qwen" not in result.artifact_types_created

    def test_skips_qwen_artifact_when_no_frames(self, svc, proof_db, pipeline_db):
        _seed_workflow(
            proof_db, STUDENT_A, SESSION_1,
            visual_reasoning_summary={"status": "analyzed", "frames_analyzed": 0},
        )
        result = svc.sync(STUDENT_A, SESSION_1)
        assert "qwen" not in result.artifact_types_created


class TestKeyframeArtifact:
    def test_creates_keyframe_artifact_when_frames_exist(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        _seed_frames(proof_db, STUDENT_A, SESSION_1, count=3)
        result = svc.sync(STUDENT_A, SESSION_1)
        assert "keyframe" in result.artifact_types_created

    def test_skips_keyframe_artifact_when_no_frames(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        result = svc.sync(STUDENT_A, SESSION_1)
        assert "keyframe" not in result.artifact_types_created


class TestTranscriptArtifact:
    def test_creates_transcript_artifact_when_transcript_exists(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        _seed_project_defense(proof_db, STUDENT_A, SESSION_1)
        result = svc.sync(STUDENT_A, SESSION_1)
        assert "transcript" in result.artifact_types_created

    def test_skips_transcript_when_transcript_empty(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        _seed_project_defense(proof_db, STUDENT_A, SESSION_1, transcript_text="", refined_transcript="")
        result = svc.sync(STUDENT_A, SESSION_1)
        assert "transcript" not in result.artifact_types_created

    def test_skips_transcript_when_too_short(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        _seed_project_defense(proof_db, STUDENT_A, SESSION_1, transcript_text="Hi", refined_transcript="Hi")
        result = svc.sync(STUDENT_A, SESSION_1)
        assert "transcript" not in result.artifact_types_created

    def test_transcript_excerpt_limited_to_300_chars(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        long_transcript = "word " * 200
        _seed_project_defense(proof_db, STUDENT_A, SESSION_1, transcript_text=long_transcript)
        svc.sync(STUDENT_A, SESSION_1)
        pipeline_svc = SkillEvidencePipelineService(pipeline_db)
        for p in pipeline_svc.list_pipelines_for_student(STUDENT_A):
            for a in pipeline_svc._list_artifacts_for_pipeline_by_id(p.id):
                if a.source_type == "transcript":
                    excerpt = a.artifact_data.get("excerpt", "")
                    assert len(excerpt) <= 300


class TestDocumentArtifact:
    def test_creates_document_artifact_when_doc_exists(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        _seed_optional_doc(proof_db, STUDENT_A, SESSION_1)
        result = svc.sync(STUDENT_A, SESSION_1)
        assert "document" in result.artifact_types_created

    def test_skips_document_artifact_when_no_docs(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        result = svc.sync(STUDENT_A, SESSION_1)
        assert "document" not in result.artifact_types_created


class TestReviewArtifact:
    def test_creates_review_artifact_when_review_exists(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        _seed_review(proof_db, STUDENT_A, SESSION_1)
        result = svc.sync(STUDENT_A, SESSION_1)
        assert "review" in result.artifact_types_created

    def test_skips_review_artifact_when_no_review(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        result = svc.sync(STUDENT_A, SESSION_1)
        assert "review" not in result.artifact_types_created

    def test_review_artifact_data_contains_snapshot(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        _seed_review(proof_db, STUDENT_A, SESSION_1)
        svc.sync(STUDENT_A, SESSION_1)
        pipeline_svc = SkillEvidencePipelineService(pipeline_db)
        found = False
        for p in pipeline_svc.list_pipelines_for_student(STUDENT_A):
            for a in pipeline_svc._list_artifacts_for_pipeline_by_id(p.id):
                if a.source_type == "review":
                    assert "approval_status" in a.artifact_data
                    assert "review_snapshot_summary" in a.artifact_data
                    found = True
        assert found


class TestIdempotency:
    def test_second_sync_returns_already_synced(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        first = svc.sync(STUDENT_A, SESSION_1)
        assert not first.already_synced
        second = svc.sync(STUDENT_A, SESSION_1)
        assert second.already_synced

    def test_second_sync_does_not_duplicate_artifacts(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        svc.sync(STUDENT_A, SESSION_1)
        svc.sync(STUDENT_A, SESSION_1)
        pipeline_svc = SkillEvidencePipelineService(pipeline_db)
        workflow_count = 0
        for p in pipeline_svc.list_pipelines_for_student(STUDENT_A):
            for a in pipeline_svc._list_artifacts_for_pipeline_by_id(p.id):
                if a.source_type == "workflow":
                    workflow_count += 1
        # One workflow artifact per skill (3 skills), not doubled
        assert workflow_count == len(first_result_skills(svc, proof_db, pipeline_db))


def first_result_skills(svc, proof_db, pipeline_db):
    _seed_workflow(proof_db, "fake-user-idempotency", "fake-session-id-idem")
    r = svc.sync("fake-user-idempotency", "fake-session-id-idem")
    return r.skills_synced


class TestSecurityStripping:
    def test_unsafe_keys_stripped_from_artifact_data(self):
        data = {
            "workflow_summary": "ML inference",
            "proof_session_id": SESSION_1,
            "signed_url": "https://private.example.com/secret",
            "storage_path": "/bucket/private/frame.jpg",
            "screenshot_url": "https://private.example.com/screenshot.png",
        }
        stripped = _strip_unsafe(data)
        assert "signed_url" not in stripped
        assert "storage_path" not in stripped
        assert "screenshot_url" not in stripped
        assert "workflow_summary" in stripped
        assert "proof_session_id" in stripped

    def test_artifact_data_never_contains_video_url(self, svc, proof_db, pipeline_db):
        row_id = str(uuid4())
        proof_db.setdefault("workflow_analysis_results", {})[row_id] = {
            "id": row_id,
            "user_id": STUDENT_A,
            "proof_session_id": SESSION_1,
            "supported_skills": ["Machine Learning"],
            "weakly_supported_skills": [],
            "evidence_strength_score": 70,
            "workflow_summary": "ML demo",
            "target_website": "http://example.com",
            "dom_evidence_status": "not_captured",
            "frame_ocr_evidence_summary": {"has_ocr_evidence": False},
            "visual_reasoning_summary": {"status": "disabled"},
            "video_url": "https://private.example.com/proof.mp4",
            "media_storage_path": "/bucket/private/proof.mp4",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        svc.sync(STUDENT_A, SESSION_1)
        pipeline_svc = SkillEvidencePipelineService(pipeline_db)
        for p in pipeline_svc.list_pipelines_for_student(STUDENT_A):
            for a in pipeline_svc._list_artifacts_for_pipeline_by_id(p.id):
                assert "video_url" not in a.artifact_data
                assert "media_storage_path" not in a.artifact_data


class TestRecruiterSafety:
    def test_recruiter_safe_view_masks_protected_artifacts(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        svc.sync(STUDENT_A, SESSION_1)
        pipeline_svc = SkillEvidencePipelineService(pipeline_db)
        summaries = pipeline_svc.list_recruiter_safe_pipelines(STUDENT_A, access_approved=False)
        # All pipelines default to protected → locked cards, no artifact detail
        for summary in summaries:
            assert summary.is_locked_for_recruiter is True
            assert summary.artifacts == []

    def test_recruiter_safe_view_when_pipeline_set_public(self, svc, proof_db, pipeline_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        svc.sync(STUDENT_A, SESSION_1)
        pipeline_svc = SkillEvidencePipelineService(pipeline_db)
        pipelines = pipeline_svc.list_pipelines_for_student(STUDENT_A)
        # Set one pipeline to public
        ml_pipeline = next((p for p in pipelines if p.skill_name == "Machine Learning"), None)
        assert ml_pipeline is not None
        pipeline_svc.update_pipeline_visibility(ml_pipeline.id, STUDENT_A, "public")
        summaries = pipeline_svc.list_recruiter_safe_pipelines(STUDENT_A, access_approved=False)
        ml_summary = next((s for s in summaries if s.skill_name == "Machine Learning"), None)
        assert ml_summary is not None
        assert ml_summary.is_locked_for_recruiter is False
        # Protected artifacts in a public pipeline show safe sanitized data.
        # artifact visibility is a student label, not a data gate — the pipeline gate controls access.
        for art in ml_summary.artifacts:
            if art.get("visibility") == "protected":
                # Safe artifact data is surfaced (not empty) for public pipelines
                assert isinstance(art.get("artifact_data"), dict)
                # Unsafe storage/auth keys must never appear
                data = art.get("artifact_data") or {}
                assert "signed_url" not in data
                assert "storage_path" not in data
                assert "access_token" not in data


class TestNoSkillsCase:
    def test_returns_error_when_no_analysis_data(self, svc, proof_db, pipeline_db):
        result = svc.sync(STUDENT_A, "nonexistent-session-id")
        assert result.artifacts_created == 0
        assert result.pipelines_upserted == 0
        assert len(result.errors) > 0

    def test_returns_no_skills_when_empty_lists(self, svc, proof_db, pipeline_db):
        row_id = str(uuid4())
        proof_db.setdefault("workflow_analysis_results", {})[row_id] = {
            "id": row_id,
            "user_id": STUDENT_A,
            "proof_session_id": SESSION_1,
            "supported_skills": [],
            "weakly_supported_skills": [],
            "evidence_strength_score": 0,
            "dom_evidence_status": "not_captured",
            "frame_ocr_evidence_summary": {"has_ocr_evidence": False},
            "visual_reasoning_summary": {"status": "disabled"},
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        result = svc.sync(STUDENT_A, SESSION_1)
        assert result.skills_synced == []
        assert result.artifacts_created == 0
        assert len(result.errors) > 0


class TestHelperFunctions:
    def test_infer_category_ml(self):
        assert _infer_category("Machine Learning") == "AI/ML"

    def test_infer_category_frontend(self):
        assert _infer_category("React") == "Frontend"

    def test_infer_category_backend(self):
        assert _infer_category("FastAPI") == "Backend"

    def test_infer_category_devops(self):
        assert _infer_category("Docker") == "DevOps"

    def test_infer_category_fallback(self):
        assert _infer_category("Obscure Niche Skill XYZ") == "technical"


class TestHttpEndpoint:
    def test_endpoint_returns_200(self, client, proof_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        r = client.post(f"/api/v1/student/skill-pipelines/from-website-proof/{SESSION_1}")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "skills_synced" in data
        assert "artifacts_created" in data
        assert "pipelines_upserted" in data

    def test_endpoint_idempotent_on_second_call(self, client, proof_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_1)
        client.post(f"/api/v1/student/skill-pipelines/from-website-proof/{SESSION_1}")
        r = client.post(f"/api/v1/student/skill-pipelines/from-website-proof/{SESSION_1}")
        assert r.status_code == 200
        assert r.json()["already_synced"] is True

    def test_endpoint_returns_empty_for_unknown_session(self, client, proof_db):
        r = client.post("/api/v1/student/skill-pipelines/from-website-proof/unknown-session-id")
        assert r.status_code == 200
        data = r.json()
        assert data["artifacts_created"] == 0
        assert len(data["errors"]) > 0

    def test_full_flow_all_evidence_types(self, client, proof_db):
        _seed_workflow(proof_db, STUDENT_A, SESSION_2)
        _seed_project_defense(proof_db, STUDENT_A, SESSION_2)
        _seed_optional_doc(proof_db, STUDENT_A, SESSION_2)
        _seed_frames(proof_db, STUDENT_A, SESSION_2, count=3)
        _seed_review(proof_db, STUDENT_A, SESSION_2)
        r = client.post(f"/api/v1/student/skill-pipelines/from-website-proof/{SESSION_2}")
        assert r.status_code == 200
        data = r.json()
        types_created = set(data["artifact_types_created"])
        assert "workflow" in types_created
        assert "ocr" in types_created
        assert "dom" in types_created
        assert "qwen" in types_created
        assert "keyframe" in types_created
        assert "transcript" in types_created
        assert "document" in types_created
        assert "review" in types_created
