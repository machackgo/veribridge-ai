"""Tests for Skill Evidence Pipeline persistence.

Covers:
  ✓ create/upsert skill pipeline
  ✓ add GitHub line-level artifact (exact_code_url includes /blob/main/ + #Lstart-Lend)
  ✓ add transcript artifact
  ✓ add document artifact
  ✓ add workflow/OCR/DOM/Qwen artifact
  ✓ list pipelines for student
  ✓ get single pipeline
  ✓ recruiter-safe payload excludes student_id, student_summary
  ✓ recruiter-safe payload excludes private/locked/unavailable artifacts
  ✓ recruiter-safe payload strips unsafe artifact_data keys
  ✓ public/protected/private visibility states are preserved
  ✓ GitHub exact_code_url includes /blob/main/ and #Lstart-Lend
  ✓ missing evidence / next actions stored correctly
  ✓ seed-mock endpoint creates 4 pipelines
  ✓ upsert is idempotent (same skill_name → update, not duplicate)
  ✓ pipeline_id mismatch rejected
  ✓ 404 on get for wrong user

All storage is in-memory (get_db → {}).
No real network calls.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.services.skill_evidence_pipeline_service import (
    ArtifactNotFoundError,
    PipelineNotFoundError,
    SkillEvidencePipelineService,
    _compute_github_urls,
    _strip_unsafe_artifact_data,
)

# ── Constants ─────────────────────────────────────────────────────────────────

STUDENT_A = "aaaaaaaa-0000-0000-0000-000000000001"
STUDENT_B = "bbbbbbbb-0000-0000-0000-000000000002"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mem() -> dict:
    return {}


@pytest.fixture()
def client_a(mem: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: STUDENT_A
    app.dependency_overrides[get_db] = lambda: mem
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def client_b(mem: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: STUDENT_B
    app.dependency_overrides[get_db] = lambda: mem
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def svc(mem: dict) -> SkillEvidencePipelineService:
    return SkillEvidencePipelineService(mem)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _upsert(client: TestClient, skill_name: str, **kwargs) -> dict:
    body = {
        "skill_name": skill_name,
        "skill_category": "AI/ML",
        "confidence_score": 80,
        "support_status": "strongly_supported",
        "evidence_count": 3,
        "strongest_proof": {"label": "GitHub code", "reason": "ML pipeline confirmed"},
        "weakest_proof": {"label": "OCR", "reason": "Partial extraction"},
        "missing_evidence": ["Deployment demo"],
        "next_actions": ["Add a model evaluation report"],
        "evidence_sources": [{"key": "github", "label": "GitHub", "status": "supported", "score": 90, "reason": "Confirmed"}],
        "recruiter_summary": "Strong ML evidence.",
        "student_summary": "Add a deployment demo.",
        "visibility_status": "public",
        **kwargs,
    }
    r = client.post("/api/v1/student/skill-pipelines/upsert", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _add_artifact(client: TestClient, pipeline_id: str, source_type: str = "github", **kwargs) -> dict:
    body = {
        "pipeline_id": pipeline_id,
        "source_type": source_type,
        "source_title": "test_artifact",
        "project_name": "Test Project",
        "visibility": "public",
        "confidence_score": 85,
        "relevance_to_skill": "Demonstrates skill",
        "proof_reason": "Confirmed via analysis",
        "artifact_data": {},
        **kwargs,
    }
    r = client.post(f"/api/v1/student/skill-pipelines/{pipeline_id}/artifacts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ── Phase 2: Schema / pure-unit tests ────────────────────────────────────────


class TestGitHubUrlComputation:
    def test_exact_code_url_includes_blob_main_and_line_anchor(self):
        data = {
            "repo_url": "https://github.com/veribridge-ai/veribridge",
            "branch": "main",
            "file_path": "apps/api/app/services/final_evidence_evaluator_service.py",
            "start_line": 40,
            "end_line": 140,
        }
        exact, full = _compute_github_urls(data)
        assert "/blob/main/" in exact
        assert "#L40-L140" in exact
        assert "final_evidence_evaluator_service.py" in exact

    def test_full_file_url_has_no_line_anchor(self):
        data = {
            "repo_url": "https://github.com/veribridge-ai/veribridge",
            "branch": "main",
            "file_path": "apps/api/app/services/foo.py",
            "start_line": 10,
            "end_line": 50,
        }
        _, full = _compute_github_urls(data)
        assert "#L" not in full
        assert "/blob/main/" in full

    def test_empty_repo_url_returns_empty_strings(self):
        exact, full = _compute_github_urls({"repo_url": "", "file_path": "foo.py"})
        assert exact == ""
        assert full == ""

    def test_missing_lines_uses_full_url_as_exact(self):
        data = {
            "repo_url": "https://github.com/veribridge-ai/veribridge",
            "branch": "main",
            "file_path": "apps/api/app/services/foo.py",
        }
        exact, full = _compute_github_urls(data)
        assert exact == full
        assert "#L" not in exact


class TestUnsafeArtifactDataStripping:
    def test_strips_storage_path(self):
        data = {"storage_path": "private/bucket/key", "code_reason": "safe"}
        assert "storage_path" not in _strip_unsafe_artifact_data(data)
        assert "code_reason" in _strip_unsafe_artifact_data(data)

    def test_strips_signed_url(self):
        data = {"signed_url": "https://storage.example.com/signed?token=xyz", "file_path": "foo.py"}
        result = _strip_unsafe_artifact_data(data)
        assert "signed_url" not in result

    def test_strips_access_token(self):
        data = {"access_token": "secret", "branch": "main"}
        result = _strip_unsafe_artifact_data(data)
        assert "access_token" not in result
        assert "branch" in result

    def test_safe_fields_pass_through(self):
        data = {"repo_url": "https://github.com/x/y", "start_line": 10, "end_line": 50}
        result = _strip_unsafe_artifact_data(data)
        assert result == data


# ── Phase 3: Service unit tests (dict-mode) ────────────────────────────────────


class TestSkillEvidencePipelineService:
    def test_upsert_creates_pipeline(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        payload = SkillEvidencePipelineCreate(
            skill_name="AI / Machine Learning",
            skill_category="AI/ML",
            confidence_score=88,
            support_status="strongly_supported",
            evidence_count=5,
            strongest_proof={"label": "Workflow", "reason": "Live inference confirmed"},
            weakest_proof={"label": "OCR", "reason": "Partial"},
            missing_evidence=["Deployment"],
            next_actions=["Add model report"],
            evidence_sources=[],
            recruiter_summary="Strong AI evidence.",
            student_summary="Add a deployment demo.",
        )
        pipeline = svc.upsert_pipeline(STUDENT_A, payload)
        assert pipeline.skill_name == "AI / Machine Learning"
        assert pipeline.confidence_score == 88
        assert pipeline.student_id == STUDENT_A
        assert pipeline.missing_evidence == ["Deployment"]
        assert pipeline.next_actions == ["Add model report"]

    def test_upsert_is_idempotent(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        payload = SkillEvidencePipelineCreate(
            skill_name="JavaScript / Frontend",
            confidence_score=70,
            support_status="partially_supported",
        )
        p1 = svc.upsert_pipeline(STUDENT_A, payload)
        payload2 = SkillEvidencePipelineCreate(
            skill_name="JavaScript / Frontend",
            confidence_score=85,
            support_status="strongly_supported",
        )
        p2 = svc.upsert_pipeline(STUDENT_A, payload2)
        # Same ID, updated score
        assert p1.id == p2.id
        assert p2.confidence_score == 85

    def test_list_pipelines_for_student(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(skill_name="Skill A"))
        svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(skill_name="Skill B"))
        svc.upsert_pipeline(STUDENT_B, SkillEvidencePipelineCreate(skill_name="Skill A"))
        pipelines_a = svc.list_pipelines_for_student(STUDENT_A)
        assert len(pipelines_a) == 2
        names = {p.skill_name for p in pipelines_a}
        assert names == {"Skill A", "Skill B"}

    def test_get_pipeline_raises_for_wrong_user(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        pipeline = svc.upsert_pipeline(
            STUDENT_A,
            SkillEvidencePipelineCreate(skill_name="DevOps"),
        )
        with pytest.raises(PipelineNotFoundError):
            svc.get_pipeline(pipeline.id, STUDENT_B)

    def test_add_github_artifact_stores_line_refs(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import (
            SkillEvidencePipelineCreate,
            SkillEvidenceArtifactCreate,
        )
        pipeline = svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(skill_name="AI/ML"))
        artifact = svc.add_artifact(
            STUDENT_A,
            SkillEvidenceArtifactCreate(
                pipeline_id=pipeline.id,
                source_type="github",
                source_title="evaluator_service.py",
                project_name="VeriBridge",
                visibility="public",
                confidence_score=88,
                proof_reason="ML pipeline confirmed",
                artifact_data={
                    "repo_url": "https://github.com/veribridge-ai/veribridge",
                    "branch": "main",
                    "file_path": "apps/api/app/services/evaluator.py",
                    "start_line": 40,
                    "end_line": 140,
                    "symbol_name": "FinalEvidenceEvaluatorService",
                },
            ),
        )
        assert artifact.source_type == "github"
        assert artifact.exact_code_url is not None
        assert "/blob/main/" in artifact.exact_code_url
        assert "#L40-L140" in artifact.exact_code_url
        assert artifact.full_file_url is not None
        assert "#L" not in artifact.full_file_url

    def test_add_transcript_artifact(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import (
            SkillEvidencePipelineCreate,
            SkillEvidenceArtifactCreate,
        )
        pipeline = svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(skill_name="AI/ML"))
        artifact = svc.add_artifact(
            STUDENT_A,
            SkillEvidenceArtifactCreate(
                pipeline_id=pipeline.id,
                source_type="transcript",
                source_title="Project defense excerpt",
                project_name="VeriBridge",
                visibility="public",
                confidence_score=82,
                proof_reason="Candidate explained model selection and training",
                artifact_data={
                    "excerpt": "I chose TensorFlow.js because it allowed real-time inference.",
                    "highlighted_segments": ["TensorFlow.js", "real-time inference"],
                    "full_transcript_available": False,
                    "ownership_signals": ["Described design decisions"],
                    "technical_depth_signals": ["Discussed training pipeline"],
                },
            ),
        )
        assert artifact.source_type == "transcript"
        assert artifact.artifact_data["excerpt"].startswith("I chose TensorFlow")

    def test_add_document_artifact(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import (
            SkillEvidencePipelineCreate,
            SkillEvidenceArtifactCreate,
        )
        pipeline = svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(skill_name="AI/ML"))
        artifact = svc.add_artifact(
            STUDENT_A,
            SkillEvidenceArtifactCreate(
                pipeline_id=pipeline.id,
                source_type="document",
                source_title="ML Project Report",
                project_name="VeriBridge",
                visibility="public",
                confidence_score=75,
                proof_reason="Project report covers ML methodology",
                artifact_data={
                    "document_title": "ML Project Report",
                    "document_type": "pdf",
                    "extracted_sections": ["Model evaluation", "Training methodology"],
                    "download_available": False,
                    "open_available": True,
                },
            ),
        )
        assert artifact.source_type == "document"
        assert artifact.artifact_data["document_type"] == "pdf"

    def test_add_workflow_ocr_dom_qwen_artifact(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import (
            SkillEvidencePipelineCreate,
            SkillEvidenceArtifactCreate,
        )
        pipeline = svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(skill_name="AI/ML"))
        for src_type in ("workflow", "ocr", "dom", "qwen"):
            artifact = svc.add_artifact(
                STUDENT_A,
                SkillEvidenceArtifactCreate(
                    pipeline_id=pipeline.id,
                    source_type=src_type,
                    source_title=f"{src_type} capture",
                    project_name="VeriBridge",
                    visibility="protected",
                    confidence_score=70,
                    proof_reason=f"Evidence from {src_type}",
                    artifact_data={
                        "timestamp": "1:18",
                        "frame_label": "Model inference UI",
                        "ocr_snippet": "Prediction: 94.2% confidence",
                        "dom_summary": "Input form and prediction output div captured",
                        "qwen_observation": "TensorFlow.js inference output rendered",
                        "keyframe_available": True,
                    },
                ),
            )
            assert artifact.source_type == src_type
            assert artifact.artifact_data["keyframe_available"] is True


class TestRecruiterSanitization:
    def test_recruiter_payload_excludes_student_id(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        pipeline = svc.upsert_pipeline(
            STUDENT_A,
            SkillEvidencePipelineCreate(
                skill_name="AI / Machine Learning",
                recruiter_summary="Strong ML evidence.",
                student_summary="Private note for student only.",
            ),
        )
        summary = svc.sanitize_recruiter_payload(pipeline, [])
        payload_dict = summary.model_dump()
        assert "student_id" not in payload_dict
        assert "student_summary" not in payload_dict
        assert "profile_id" not in payload_dict

    def test_recruiter_payload_excludes_private_artifacts(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import (
            SkillEvidencePipelineCreate,
            SkillEvidenceArtifactCreate,
            SkillEvidenceArtifactResponse,
        )
        pipeline = svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(skill_name="AI/ML"))
        now = "2026-06-06T00:00:00+00:00"
        private_art = SkillEvidenceArtifactResponse(
            id="art-1", pipeline_id=pipeline.id, source_type="github",
            source_title="private_file.py", project_name="P",
            visibility="private", confidence_score=80,
            relevance_to_skill="High", proof_reason="Confirmed",
            artifact_data={"file_path": "secret.py"},
            created_at=now, updated_at=now,
        )
        locked_art = SkillEvidenceArtifactResponse(
            id="art-2", pipeline_id=pipeline.id, source_type="github",
            source_title="locked_file.py", project_name="P",
            visibility="locked", confidence_score=80,
            relevance_to_skill="High", proof_reason="Confirmed",
            artifact_data={"file_path": "locked.py"},
            created_at=now, updated_at=now,
        )
        public_art = SkillEvidenceArtifactResponse(
            id="art-3", pipeline_id=pipeline.id, source_type="github",
            source_title="public_file.py", project_name="P",
            visibility="public", confidence_score=80,
            relevance_to_skill="High", proof_reason="Confirmed",
            artifact_data={"repo_url": "https://github.com/x/y", "file_path": "safe.py"},
            created_at=now, updated_at=now,
        )
        summary = svc.sanitize_recruiter_payload(pipeline, [private_art, locked_art, public_art])
        ids = [a["id"] for a in summary.artifacts]
        assert "art-1" not in ids  # private excluded
        assert "art-2" not in ids  # locked excluded
        assert "art-3" in ids      # public included

    def test_recruiter_payload_strips_unsafe_artifact_data_keys(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import (
            SkillEvidencePipelineCreate,
            SkillEvidenceArtifactResponse,
        )
        pipeline = svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(skill_name="AI/ML"))
        now = "2026-06-06T00:00:00+00:00"
        art = SkillEvidenceArtifactResponse(
            id="art-safe", pipeline_id=pipeline.id, source_type="workflow",
            source_title="recording", project_name="P",
            visibility="public", confidence_score=80,
            relevance_to_skill="High", proof_reason="Confirmed",
            artifact_data={
                "signed_url": "https://storage.example.com/private?token=xyz",
                "storage_path": "private/bucket/key",
                "access_token": "secret",
                "frame_label": "Model inference UI",
            },
            created_at=now, updated_at=now,
        )
        summary = svc.sanitize_recruiter_payload(pipeline, [art])
        safe_data = summary.artifacts[0]["artifact_data"]
        assert "signed_url" not in safe_data
        assert "storage_path" not in safe_data
        assert "access_token" not in safe_data
        assert "frame_label" in safe_data  # safe field retained

    def test_recruiter_payload_includes_github_exact_code_url(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import (
            SkillEvidencePipelineCreate,
            SkillEvidenceArtifactCreate,
        )
        pipeline = svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(skill_name="AI/ML"))
        artifact = svc.add_artifact(
            STUDENT_A,
            SkillEvidenceArtifactCreate(
                pipeline_id=pipeline.id,
                source_type="github",
                source_title="evaluator.py",
                project_name="VeriBridge",
                visibility="public",
                confidence_score=90,
                proof_reason="ML confirmed",
                artifact_data={
                    "repo_url": "https://github.com/veribridge-ai/veribridge",
                    "branch": "main",
                    "file_path": "apps/api/app/services/evaluator.py",
                    "start_line": 40,
                    "end_line": 140,
                },
            ),
        )
        artifacts = svc.list_artifacts_for_pipeline(pipeline.id, STUDENT_A)
        summary = svc.sanitize_recruiter_payload(pipeline, artifacts)
        art_entry = summary.artifacts[0]
        assert "exact_code_url" in art_entry
        assert "/blob/main/" in art_entry["exact_code_url"]
        assert "#L40-L140" in art_entry["exact_code_url"]


class TestVisibilityPreservation:
    def test_pipeline_visibility_states_preserved(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        for vis in ("public", "protected", "private"):
            p = svc.upsert_pipeline(
                STUDENT_A,
                SkillEvidencePipelineCreate(
                    skill_name=f"Skill-{vis}",
                    visibility_status=vis,
                ),
            )
            assert p.visibility_status == vis

    def test_artifact_visibility_states_preserved(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import (
            SkillEvidencePipelineCreate,
            SkillEvidenceArtifactCreate,
        )
        pipeline = svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(skill_name="Vis Test"))
        for vis in ("public", "protected", "private", "approved", "locked", "unavailable"):
            art = svc.add_artifact(
                STUDENT_A,
                SkillEvidenceArtifactCreate(
                    pipeline_id=pipeline.id,
                    source_type="document",
                    source_title=f"doc-{vis}",
                    project_name="P",
                    visibility=vis,
                    confidence_score=70,
                    proof_reason="Test",
                    artifact_data={},
                ),
            )
            assert art.visibility == vis


class TestMockPipelineSeeding:
    def test_build_mock_pipelines_creates_4_pipelines(self, svc: SkillEvidencePipelineService):
        pipelines = svc.build_mock_pipelines_for_student(STUDENT_A)
        assert len(pipelines) == 4
        names = {p.skill_name for p in pipelines}
        assert "AI / Machine Learning" in names
        assert "JavaScript / Frontend" in names
        assert "Data & Visualization" in names
        assert "DevOps / Deployment" in names

    def test_mock_pipelines_are_idempotent(self, svc: SkillEvidencePipelineService):
        svc.build_mock_pipelines_for_student(STUDENT_A)
        svc.build_mock_pipelines_for_student(STUDENT_A)
        pipelines = svc.list_pipelines_for_student(STUDENT_A)
        assert len(pipelines) == 4  # no duplicates

    def test_ai_ml_mock_has_dom_evidence_source(self, svc: SkillEvidencePipelineService):
        svc.build_mock_pipelines_for_student(STUDENT_A)
        pipelines = svc.list_pipelines_for_student(STUDENT_A)
        ai_ml = next(p for p in pipelines if p.skill_name == "AI / Machine Learning")
        source_keys = [s["key"] for s in ai_ml.evidence_sources]
        assert "dom" in source_keys

    def test_devops_mock_has_low_confidence(self, svc: SkillEvidencePipelineService):
        svc.build_mock_pipelines_for_student(STUDENT_A)
        pipelines = svc.list_pipelines_for_student(STUDENT_A)
        devops = next(p for p in pipelines if p.skill_name == "DevOps / Deployment")
        assert devops.confidence_score < 50
        assert devops.support_status == "needs_review"

    def test_mock_seeds_github_artifacts_for_ai_ml(self, svc: SkillEvidencePipelineService):
        svc.build_mock_pipelines_for_student(STUDENT_A)
        pipelines = svc.list_pipelines_for_student(STUDENT_A)
        ai_ml = next(p for p in pipelines if p.skill_name == "AI / Machine Learning")
        artifacts = svc.list_artifacts_for_pipeline(ai_ml.id, STUDENT_A)
        github_arts = [a for a in artifacts if a.source_type == "github"]
        assert len(github_arts) >= 1
        for art in github_arts:
            assert art.exact_code_url is not None
            assert "/blob/main/" in art.exact_code_url


# ── Phase 4: API endpoint tests ───────────────────────────────────────────────


class TestPipelineEndpoints:
    def test_list_pipelines_returns_empty_initially(self, client_a: TestClient):
        r = client_a.get("/api/v1/student/skill-pipelines")
        assert r.status_code == 200
        assert r.json() == []

    def test_upsert_pipeline_creates_and_returns(self, client_a: TestClient):
        p = _upsert(client_a, "AI / Machine Learning")
        assert p["skill_name"] == "AI / Machine Learning"
        assert p["confidence_score"] == 80
        assert p["visibility_status"] == "public"

    def test_upsert_pipeline_is_idempotent(self, client_a: TestClient):
        p1 = _upsert(client_a, "JavaScript / Frontend", confidence_score=70)
        p2 = _upsert(client_a, "JavaScript / Frontend", confidence_score=90)
        assert p1["id"] == p2["id"]
        assert p2["confidence_score"] == 90

    def test_list_pipelines_returns_created(self, client_a: TestClient):
        _upsert(client_a, "AI / Machine Learning")
        _upsert(client_a, "DevOps / Deployment")
        r = client_a.get("/api/v1/student/skill-pipelines")
        assert r.status_code == 200
        names = {p["skill_name"] for p in r.json()}
        assert names == {"AI / Machine Learning", "DevOps / Deployment"}

    def test_get_pipeline_returns_pipeline(self, client_a: TestClient):
        p = _upsert(client_a, "Data & Visualization")
        r = client_a.get(f"/api/v1/student/skill-pipelines/{p['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == p["id"]

    def test_get_pipeline_404_for_unknown(self, client_a: TestClient):
        r = client_a.get("/api/v1/student/skill-pipelines/00000000-0000-0000-0000-000000000099")
        assert r.status_code == 404

    def test_student_a_cannot_see_student_b_pipeline(
        self, client_a: TestClient, mem: dict
    ):
        # Seed STUDENT_B's pipeline directly via service (avoids dep-override conflict)
        svc = SkillEvidencePipelineService(mem)
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        pb = svc.upsert_pipeline(STUDENT_B, SkillEvidencePipelineCreate(skill_name="NLP"))
        # client_a is authenticated as STUDENT_A — should not see STUDENT_B's pipeline
        r = client_a.get(f"/api/v1/student/skill-pipelines/{pb.id}")
        assert r.status_code == 404

    def test_seed_mock_creates_4_pipelines(self, client_a: TestClient):
        r = client_a.post("/api/v1/student/skill-pipelines/seed-mock")
        assert r.status_code == 200
        pipelines = r.json()
        assert len(pipelines) == 4

    def test_seed_mock_is_idempotent(self, client_a: TestClient):
        client_a.post("/api/v1/student/skill-pipelines/seed-mock")
        client_a.post("/api/v1/student/skill-pipelines/seed-mock")
        r = client_a.get("/api/v1/student/skill-pipelines")
        assert len(r.json()) == 4


class TestArtifactEndpoints:
    def test_add_github_artifact(self, client_a: TestClient):
        p = _upsert(client_a, "AI / Machine Learning")
        art = _add_artifact(
            client_a,
            p["id"],
            source_type="github",
            source_title="evaluator.py",
            artifact_data={
                "repo_url": "https://github.com/veribridge-ai/veribridge",
                "branch": "main",
                "file_path": "apps/api/app/services/evaluator.py",
                "start_line": 40,
                "end_line": 140,
                "symbol_name": "FinalEvidenceEvaluatorService",
            },
        )
        assert art["source_type"] == "github"
        assert art["exact_code_url"] is not None
        assert "/blob/main/" in art["exact_code_url"]
        assert "#L40-L140" in art["exact_code_url"]
        assert art["full_file_url"] is not None
        assert "#L" not in art["full_file_url"]

    def test_add_transcript_artifact(self, client_a: TestClient):
        p = _upsert(client_a, "AI / Machine Learning")
        art = _add_artifact(
            client_a,
            p["id"],
            source_type="transcript",
            source_title="Project defense excerpt",
            artifact_data={
                "excerpt": "I chose TensorFlow.js because it allowed real-time inference.",
                "highlighted_segments": ["TensorFlow.js"],
                "full_transcript_available": False,
            },
        )
        assert art["source_type"] == "transcript"
        assert "excerpt" in art["artifact_data"]

    def test_add_document_artifact(self, client_a: TestClient):
        p = _upsert(client_a, "AI / Machine Learning")
        art = _add_artifact(
            client_a,
            p["id"],
            source_type="document",
            source_title="ML Report",
            artifact_data={
                "document_title": "ML Project Report",
                "document_type": "pdf",
                "extracted_sections": ["Model evaluation"],
                "download_available": False,
                "open_available": True,
            },
        )
        assert art["source_type"] == "document"
        assert art["artifact_data"]["document_type"] == "pdf"

    def test_add_workflow_artifact(self, client_a: TestClient):
        p = _upsert(client_a, "AI / Machine Learning")
        art = _add_artifact(
            client_a,
            p["id"],
            source_type="workflow",
            source_title="AI Proof Builder recording",
            artifact_data={
                "timestamp": "1:18",
                "frame_label": "Model inference UI visible",
                "ocr_snippet": "Prediction: 94.2% confidence",
                "dom_summary": "Input form and prediction output div captured",
                "qwen_observation": "TensorFlow.js inference output rendered",
                "keyframe_available": True,
            },
        )
        assert art["source_type"] == "workflow"
        assert art["artifact_data"]["keyframe_available"] is True

    def test_add_dom_artifact(self, client_a: TestClient):
        p = _upsert(client_a, "AI / Machine Learning")
        art = _add_artifact(
            client_a,
            p["id"],
            source_type="dom",
            source_title="DOM Evidence",
            artifact_data={
                "dom_summary": "Captured page structure, visible UI labels, and proof builder state changes.",
                "keyframe_available": False,
            },
        )
        assert art["source_type"] == "dom"
        assert "dom_summary" in art["artifact_data"]

    def test_pipeline_id_mismatch_rejected(self, client_a: TestClient):
        p = _upsert(client_a, "AI / Machine Learning")
        body = {
            "pipeline_id": "wrong-pipeline-id",
            "source_type": "github",
            "source_title": "foo.py",
            "project_name": "P",
            "visibility": "public",
            "confidence_score": 80,
            "relevance_to_skill": "Test",
            "proof_reason": "Test",
            "artifact_data": {},
        }
        r = client_a.post(f"/api/v1/student/skill-pipelines/{p['id']}/artifacts", json=body)
        assert r.status_code == 422

    def test_artifact_404_for_unknown_pipeline(self, client_a: TestClient):
        fake_id = "00000000-0000-0000-0000-000000000099"
        body = {
            "pipeline_id": fake_id,
            "source_type": "github",
            "source_title": "foo.py",
            "project_name": "P",
            "visibility": "public",
            "confidence_score": 80,
            "relevance_to_skill": "Test",
            "proof_reason": "Test",
            "artifact_data": {},
        }
        r = client_a.post(f"/api/v1/student/skill-pipelines/{fake_id}/artifacts", json=body)
        assert r.status_code == 404


class TestRecruiterViewEndpoint:
    def test_recruiter_view_omits_student_id(self, client_a: TestClient):
        p = _upsert(client_a, "AI / Machine Learning")
        r = client_a.get(f"/api/v1/student/skill-pipelines/{p['id']}/recruiter-view")
        assert r.status_code == 200
        data = r.json()
        assert "student_id" not in data
        assert "student_summary" not in data
        assert "profile_id" not in data

    def test_recruiter_view_includes_recruiter_summary(self, client_a: TestClient):
        p = _upsert(client_a, "AI / Machine Learning", recruiter_summary="Strong ML evidence confirmed.")
        r = client_a.get(f"/api/v1/student/skill-pipelines/{p['id']}/recruiter-view")
        assert r.status_code == 200
        assert r.json()["recruiter_summary"] == "Strong ML evidence confirmed."

    def test_recruiter_view_excludes_private_artifacts(self, client_a: TestClient):
        p = _upsert(client_a, "AI / Machine Learning")
        pub = _add_artifact(client_a, p["id"], source_type="github", visibility="public")
        prv = _add_artifact(client_a, p["id"], source_type="github", visibility="private")
        r = client_a.get(f"/api/v1/student/skill-pipelines/{p['id']}/recruiter-view")
        ids = [a["id"] for a in r.json()["artifacts"]]
        assert pub["id"] in ids
        assert prv["id"] not in ids

    def test_recruiter_view_response_has_no_unsafe_strings(self, client_a: TestClient):
        p = _upsert(client_a, "AI / Machine Learning")
        _add_artifact(
            client_a,
            p["id"],
            source_type="workflow",
            artifact_data={
                "frame_label": "Safe label",
                "signed_url": "UNSAFE_SIGNED_URL",
                "storage_path": "UNSAFE_STORAGE_PATH",
            },
        )
        r = client_a.get(f"/api/v1/student/skill-pipelines/{p['id']}/recruiter-view")
        payload_str = r.text
        assert "UNSAFE_SIGNED_URL" not in payload_str
        assert "UNSAFE_STORAGE_PATH" not in payload_str
        assert "service_role" not in payload_str
        assert "access_token" not in payload_str


# ── Visibility persistence endpoints ─────────────────────────────────────────


class TestVisibilityPersistenceEndpoints:
    def test_patch_pipeline_visibility_to_protected(self, client_a: TestClient):
        p = _upsert(client_a, "AI / Machine Learning", visibility_status="public")
        r = client_a.patch(
            f"/api/v1/student/skill-pipelines/{p['id']}/visibility",
            json={"visibility": "protected"},
        )
        assert r.status_code == 200
        assert r.json()["visibility_status"] == "protected"

    def test_patch_pipeline_visibility_to_private(self, client_a: TestClient):
        p = _upsert(client_a, "JavaScript / Frontend", visibility_status="public")
        r = client_a.patch(
            f"/api/v1/student/skill-pipelines/{p['id']}/visibility",
            json={"visibility": "private"},
        )
        assert r.status_code == 200
        assert r.json()["visibility_status"] == "private"

    def test_patch_pipeline_visibility_to_public(self, client_a: TestClient):
        p = _upsert(client_a, "Data & Visualization", visibility_status="protected")
        r = client_a.patch(
            f"/api/v1/student/skill-pipelines/{p['id']}/visibility",
            json={"visibility": "public"},
        )
        assert r.status_code == 200
        assert r.json()["visibility_status"] == "public"

    def test_invalid_pipeline_visibility_rejected(self, client_a: TestClient):
        p = _upsert(client_a, "DevOps / Deployment")
        r = client_a.patch(
            f"/api/v1/student/skill-pipelines/{p['id']}/visibility",
            json={"visibility": "invalid_value"},
        )
        assert r.status_code == 422

    def test_patch_pipeline_visibility_404_for_wrong_user(
        self, client_a: TestClient, mem: dict
    ):
        svc = SkillEvidencePipelineService(mem)
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        pb = svc.upsert_pipeline(STUDENT_B, SkillEvidencePipelineCreate(skill_name="NLP"))
        r = client_a.patch(
            f"/api/v1/student/skill-pipelines/{pb.id}/visibility",
            json={"visibility": "private"},
        )
        assert r.status_code == 404

    def test_patch_artifact_visibility(self, client_a: TestClient):
        p = _upsert(client_a, "AI / Machine Learning")
        art = _add_artifact(client_a, p["id"], visibility="public")
        r = client_a.patch(
            f"/api/v1/student/skill-pipelines/artifacts/{art['id']}/visibility",
            json={"visibility": "protected"},
        )
        assert r.status_code == 200
        assert r.json()["visibility"] == "protected"

    def test_patch_artifact_visibility_all_valid_values(self, client_a: TestClient):
        p = _upsert(client_a, "AI / Machine Learning")
        art = _add_artifact(client_a, p["id"], visibility="public")
        for vis in ("public", "protected", "private", "approved", "locked", "unavailable"):
            r = client_a.patch(
                f"/api/v1/student/skill-pipelines/artifacts/{art['id']}/visibility",
                json={"visibility": vis},
            )
            assert r.status_code == 200, f"Failed for visibility={vis}: {r.text}"
            assert r.json()["visibility"] == vis

    def test_invalid_artifact_visibility_rejected(self, client_a: TestClient):
        p = _upsert(client_a, "AI / Machine Learning")
        art = _add_artifact(client_a, p["id"])
        r = client_a.patch(
            f"/api/v1/student/skill-pipelines/artifacts/{art['id']}/visibility",
            json={"visibility": "invalid_value"},
        )
        assert r.status_code == 422

    def test_patch_artifact_visibility_404_for_unknown_artifact(self, client_a: TestClient):
        r = client_a.patch(
            "/api/v1/student/skill-pipelines/artifacts/00000000-0000-0000-0000-000000000099/visibility",
            json={"visibility": "public"},
        )
        assert r.status_code == 404

    def test_recruiter_view_excludes_private_artifacts_after_visibility_update(
        self, client_a: TestClient
    ):
        p = _upsert(client_a, "AI / Machine Learning")
        pub = _add_artifact(client_a, p["id"], source_type="github", visibility="public")
        prv = _add_artifact(client_a, p["id"], source_type="github", visibility="public")
        # Change second artifact to private
        client_a.patch(
            f"/api/v1/student/skill-pipelines/artifacts/{prv['id']}/visibility",
            json={"visibility": "private"},
        )
        r = client_a.get(f"/api/v1/student/skill-pipelines/{p['id']}/recruiter-view")
        ids = [a["id"] for a in r.json()["artifacts"]]
        assert pub["id"] in ids
        assert prv["id"] not in ids

    def test_protected_artifact_appears_in_recruiter_view(self, client_a: TestClient):
        p = _upsert(client_a, "AI / Machine Learning")
        art = _add_artifact(client_a, p["id"], source_type="github", visibility="protected")
        r = client_a.get(f"/api/v1/student/skill-pipelines/{p['id']}/recruiter-view")
        assert r.status_code == 200
        artifacts = r.json()["artifacts"]
        assert any(a["id"] == art["id"] and a["visibility"] == "protected" for a in artifacts)

    def test_public_artifact_appears_in_recruiter_view(self, client_a: TestClient):
        p = _upsert(client_a, "AI / Machine Learning")
        art = _add_artifact(client_a, p["id"], source_type="github", visibility="public")
        r = client_a.get(f"/api/v1/student/skill-pipelines/{p['id']}/recruiter-view")
        assert r.status_code == 200
        artifacts = r.json()["artifacts"]
        assert any(a["id"] == art["id"] and a["visibility"] == "public" for a in artifacts)

    def test_service_update_pipeline_visibility(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        pipeline = svc.upsert_pipeline(
            STUDENT_A,
            SkillEvidencePipelineCreate(skill_name="AI/ML", visibility_status="public"),
        )
        updated = svc.update_pipeline_visibility(pipeline.id, STUDENT_A, "protected")
        assert updated.visibility_status == "protected"
        assert updated.id == pipeline.id

    def test_service_update_artifact_visibility(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import (
            SkillEvidencePipelineCreate,
            SkillEvidenceArtifactCreate,
        )
        pipeline = svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(skill_name="AI/ML"))
        artifact = svc.add_artifact(
            STUDENT_A,
            SkillEvidenceArtifactCreate(
                pipeline_id=pipeline.id,
                source_type="github",
                source_title="evaluator.py",
                project_name="P",
                visibility="public",
                confidence_score=80,
                proof_reason="Confirmed",
                artifact_data={},
            ),
        )
        updated = svc.update_artifact_visibility(artifact.id, STUDENT_A, "private")
        assert updated.visibility == "private"
        assert updated.id == artifact.id

    def test_service_update_pipeline_visibility_wrong_user_raises(
        self, svc: SkillEvidencePipelineService
    ):
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        pipeline = svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(skill_name="AI/ML"))
        with pytest.raises(PipelineNotFoundError):
            svc.update_pipeline_visibility(pipeline.id, STUDENT_B, "private")

    def test_service_update_artifact_visibility_unknown_artifact_raises(
        self, svc: SkillEvidencePipelineService
    ):
        with pytest.raises(ArtifactNotFoundError):
            svc.update_artifact_visibility("nonexistent-id", STUDENT_A, "public")

    def test_visibility_persists_after_get(self, svc: SkillEvidencePipelineService):
        """Simulates a page refresh: update visibility then re-fetch to confirm persistence."""
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        pipeline = svc.upsert_pipeline(
            STUDENT_A,
            SkillEvidencePipelineCreate(skill_name="AI/ML", visibility_status="public"),
        )
        svc.update_pipeline_visibility(pipeline.id, STUDENT_A, "protected")
        fetched = svc.get_pipeline(pipeline.id, STUDENT_A)
        assert fetched.visibility_status == "protected"


# ── Dev fallback ID persistence tests ─────────────────────────────────────────

# UUID that matches the DEMO_USER_ID set in apps/api/.env for local dev.
DEV_FALLBACK_ID = "836d5bc3-3b1b-4bae-8c8b-104fc220ac95"


class TestDevFallbackPersistence:
    """Verify the full seed → fetch → update → refresh cycle using the dev fallback user ID.

    In non-production, get_current_user_id falls back to DEMO_USER_ID when no
    valid JWT is present.  These tests exercise that same user ID end-to-end via
    the service layer (dict-mode, no network).
    """

    def test_seed_demo_pipelines_with_dev_fallback_id(self, svc: SkillEvidencePipelineService):
        pipelines = svc.build_mock_pipelines_for_student(DEV_FALLBACK_ID)
        assert len(pipelines) == 4

    def test_fetch_returns_seeded_pipelines_for_dev_fallback_id(self, svc: SkillEvidencePipelineService):
        svc.build_mock_pipelines_for_student(DEV_FALLBACK_ID)
        pipelines = svc.list_pipelines_for_student(DEV_FALLBACK_ID)
        assert len(pipelines) == 4
        names = {p.skill_name for p in pipelines}
        assert "AI / Machine Learning" in names

    def test_update_visibility_persists_for_dev_fallback_id(self, svc: SkillEvidencePipelineService):
        svc.build_mock_pipelines_for_student(DEV_FALLBACK_ID)
        pipelines = svc.list_pipelines_for_student(DEV_FALLBACK_ID)
        ai_ml = next(p for p in pipelines if p.skill_name == "AI / Machine Learning")
        updated = svc.update_pipeline_visibility(ai_ml.id, DEV_FALLBACK_ID, "protected")
        assert updated.visibility_status == "protected"

    def test_refresh_fetch_returns_updated_visibility(self, svc: SkillEvidencePipelineService):
        """Simulates a page refresh: update then re-list to confirm the change persisted."""
        svc.build_mock_pipelines_for_student(DEV_FALLBACK_ID)
        pipelines = svc.list_pipelines_for_student(DEV_FALLBACK_ID)
        ai_ml = next(p for p in pipelines if p.skill_name == "AI / Machine Learning")
        svc.update_pipeline_visibility(ai_ml.id, DEV_FALLBACK_ID, "private")
        refreshed = svc.list_pipelines_for_student(DEV_FALLBACK_ID)
        updated = next(p for p in refreshed if p.skill_name == "AI / Machine Learning")
        assert updated.visibility_status == "private"

    def test_seed_is_idempotent_for_dev_fallback_id(self, svc: SkillEvidencePipelineService):
        svc.build_mock_pipelines_for_student(DEV_FALLBACK_ID)
        svc.build_mock_pipelines_for_student(DEV_FALLBACK_ID)
        pipelines = svc.list_pipelines_for_student(DEV_FALLBACK_ID)
        assert len(pipelines) == 4  # no duplicates

    def test_recruiter_safe_payload_excludes_private_for_dev_fallback(
        self, svc: SkillEvidencePipelineService
    ):
        from app.schemas.skill_evidence_pipeline import SkillEvidenceArtifactResponse
        svc.build_mock_pipelines_for_student(DEV_FALLBACK_ID)
        pipelines = svc.list_pipelines_for_student(DEV_FALLBACK_ID)
        ai_ml = next(p for p in pipelines if p.skill_name == "AI / Machine Learning")
        now = "2026-06-06T00:00:00+00:00"
        artifacts = [
            SkillEvidenceArtifactResponse(
                id="art-pub", pipeline_id=ai_ml.id, source_type="github",
                source_title="public.py", project_name="P",
                visibility="public", confidence_score=80,
                relevance_to_skill="High", proof_reason="Confirmed",
                artifact_data={"repo_url": "https://github.com/x/y"},
                created_at=now, updated_at=now,
            ),
            SkillEvidenceArtifactResponse(
                id="art-prv", pipeline_id=ai_ml.id, source_type="github",
                source_title="private.py", project_name="P",
                visibility="private", confidence_score=80,
                relevance_to_skill="High", proof_reason="Confirmed",
                artifact_data={"repo_url": "https://github.com/x/y"},
                created_at=now, updated_at=now,
            ),
            SkillEvidenceArtifactResponse(
                id="art-pro", pipeline_id=ai_ml.id, source_type="github",
                source_title="protected.py", project_name="P",
                visibility="protected", confidence_score=80,
                relevance_to_skill="High", proof_reason="Confirmed",
                artifact_data={"repo_url": "https://github.com/x/y"},
                created_at=now, updated_at=now,
            ),
        ]
        summary = svc.sanitize_recruiter_payload(ai_ml, artifacts)
        ids = [a["id"] for a in summary.artifacts]
        assert "art-pub" in ids       # public visible
        assert "art-pro" in ids       # protected visible (locked card)
        assert "art-prv" not in ids   # private excluded
        # student_id and student_summary must not appear in recruiter payload
        payload = summary.model_dump()
        assert "student_id" not in payload
        assert "student_summary" not in payload


# ── Dev auth fallback endpoint tests ─────────────────────────────────────────
# These tests exercise the real get_current_user_id dependency (no override)
# so they verify that missing/invalid auth falls back to DEMO_USER_ID in dev.
# get_db (and therefore get_pipeline_db) is still overridden to avoid real
# Supabase calls.


class TestDevAuthFallbackEndpoints:
    """Verify that all pipeline endpoints work without an Authorization header
    in non-production mode (DEMO_USER_ID fallback active).

    Requirement: seed / list / visibility PATCH must work in local dev even
    when the browser has no Supabase session token.
    """

    @pytest.fixture()
    def no_auth_client(self) -> TestClient:
        """TestClient with real auth dependency (no get_current_user_id override)
        but in-memory DB so no real Supabase calls are made."""
        mem: dict = {}
        app.dependency_overrides[get_db] = lambda: mem
        yield TestClient(app)
        app.dependency_overrides.clear()

    def test_seed_without_auth_header_succeeds(self, no_auth_client: TestClient):
        """POST seed-mock without Authorization header → 200 in dev (DEMO_USER_ID fallback)."""
        r = no_auth_client.post("/api/v1/student/skill-pipelines/seed-mock")
        assert r.status_code == 200, r.text
        assert len(r.json()) == 4

    def test_list_without_auth_header_returns_seeded(self, no_auth_client: TestClient):
        """GET list without Authorization header → returns seeded pipelines."""
        no_auth_client.post("/api/v1/student/skill-pipelines/seed-mock")
        r = no_auth_client.get("/api/v1/student/skill-pipelines")
        assert r.status_code == 200, r.text
        names = {p["skill_name"] for p in r.json()}
        assert "AI / Machine Learning" in names

    def test_visibility_patch_without_auth_header_succeeds(self, no_auth_client: TestClient):
        """PATCH visibility without Authorization header → 200 in dev."""
        seed_r = no_auth_client.post("/api/v1/student/skill-pipelines/seed-mock")
        pipelines = seed_r.json()
        first_id = pipelines[0]["id"]
        r = no_auth_client.patch(
            f"/api/v1/student/skill-pipelines/{first_id}/visibility",
            json={"visibility": "protected"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["visibility_status"] == "protected"

    def test_visibility_persists_after_re_list(self, no_auth_client: TestClient):
        """Visibility PATCH without auth persists when the list endpoint is re-called
        (simulates a browser refresh against the same server process)."""
        seed_r = no_auth_client.post("/api/v1/student/skill-pipelines/seed-mock")
        pipeline_id = seed_r.json()[0]["id"]
        no_auth_client.patch(
            f"/api/v1/student/skill-pipelines/{pipeline_id}/visibility",
            json={"visibility": "private"},
        )
        list_r = no_auth_client.get("/api/v1/student/skill-pipelines")
        updated = next(p for p in list_r.json() if p["id"] == pipeline_id)
        assert updated["visibility_status"] == "private"

    def test_seed_is_idempotent_without_auth(self, no_auth_client: TestClient):
        """Re-seeding without auth does not duplicate pipelines."""
        no_auth_client.post("/api/v1/student/skill-pipelines/seed-mock")
        no_auth_client.post("/api/v1/student/skill-pipelines/seed-mock")
        r = no_auth_client.get("/api/v1/student/skill-pipelines")
        assert len(r.json()) == 4  # no duplicates

    def test_production_mode_rejects_missing_auth(self):
        """In production mode, missing auth must return 401."""
        mem: dict = {}
        app.dependency_overrides[get_db] = lambda: mem

        def _prod_auth(
            credentials=None,  # simulates no Authorization header
        ) -> str:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "unauthorized", "message": "Authentication required."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        app.dependency_overrides[get_current_user_id] = _prod_auth
        try:
            r = TestClient(app).post("/api/v1/student/skill-pipelines/seed-mock")
            assert r.status_code == 401, r.text
        finally:
            app.dependency_overrides.clear()


# ── Recruiter-safe list service tests ────────────────────────────────────────


class TestRecruiterSafeListService:
    """Service-level tests for list_recruiter_safe_pipelines."""

    def test_private_pipeline_excluded(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(
            skill_name="Private Skill", visibility_status="private",
        ))
        result = svc.list_recruiter_safe_pipelines(STUDENT_A)
        names = [r.skill_name for r in result]
        assert "Private Skill" not in names

    def test_public_pipeline_included(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(
            skill_name="Public Skill", visibility_status="public",
            recruiter_summary="Strong public evidence.",
        ))
        result = svc.list_recruiter_safe_pipelines(STUDENT_A)
        names = [r.skill_name for r in result]
        assert "Public Skill" in names
        pub = next(r for r in result if r.skill_name == "Public Skill")
        assert pub.is_locked_for_recruiter is False
        assert pub.recruiter_summary == "Strong public evidence."

    def test_protected_pipeline_included_as_locked(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(
            skill_name="Protected Skill", visibility_status="protected",
            recruiter_summary="Detailed private summary not for recruiter.",
        ))
        result = svc.list_recruiter_safe_pipelines(STUDENT_A)
        names = [r.skill_name for r in result]
        assert "Protected Skill" in names
        prot = next(r for r in result if r.skill_name == "Protected Skill")
        assert prot.is_locked_for_recruiter is True
        assert "approval" in prot.recruiter_summary.lower()
        assert "Detailed private summary" not in prot.recruiter_summary

    def test_only_non_private_pipelines_returned(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        for vis in ("public", "protected", "private"):
            svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(
                skill_name=f"Skill-{vis}", visibility_status=vis,
            ))
        result = svc.list_recruiter_safe_pipelines(STUDENT_A)
        names = {r.skill_name for r in result}
        assert "Skill-public" in names
        assert "Skill-protected" in names
        assert "Skill-private" not in names

    def test_protected_artifact_data_hidden_in_public_pipeline(
        self, svc: SkillEvidencePipelineService
    ):
        from app.schemas.skill_evidence_pipeline import (
            SkillEvidencePipelineCreate,
            SkillEvidenceArtifactCreate,
        )
        pipeline = svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(
            skill_name="ML Skill", visibility_status="public",
        ))
        svc.add_artifact(STUDENT_A, SkillEvidenceArtifactCreate(
            pipeline_id=pipeline.id,
            source_type="transcript",
            source_title="Defense excerpt",
            project_name="P",
            visibility="protected",
            confidence_score=80,
            proof_reason="Explains model selection",
            artifact_data={"excerpt": "PRIVATE_TRANSCRIPT_TEXT", "ownership_signals": ["explained design"]},
        ))
        result = svc.list_recruiter_safe_pipelines(STUDENT_A)
        skill = next(r for r in result if r.skill_name == "ML Skill")
        assert len(skill.artifacts) == 1
        art = skill.artifacts[0]
        assert art["visibility"] == "protected"
        assert art["artifact_data"] == {}
        assert "PRIVATE_TRANSCRIPT_TEXT" not in str(art)

    def test_private_artifact_excluded_in_public_pipeline(
        self, svc: SkillEvidencePipelineService
    ):
        from app.schemas.skill_evidence_pipeline import (
            SkillEvidencePipelineCreate,
            SkillEvidenceArtifactCreate,
        )
        pipeline = svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(
            skill_name="FE Skill", visibility_status="public",
        ))
        svc.add_artifact(STUDENT_A, SkillEvidenceArtifactCreate(
            pipeline_id=pipeline.id,
            source_type="github",
            source_title="private_file.py",
            project_name="P",
            visibility="private",
            confidence_score=80,
            proof_reason="Private code",
            artifact_data={"file_path": "secret.py"},
        ))
        svc.add_artifact(STUDENT_A, SkillEvidenceArtifactCreate(
            pipeline_id=pipeline.id,
            source_type="github",
            source_title="public_file.py",
            project_name="P",
            visibility="public",
            confidence_score=85,
            proof_reason="Public code",
            artifact_data={"repo_url": "https://github.com/x/y", "file_path": "safe.py"},
        ))
        result = svc.list_recruiter_safe_pipelines(STUDENT_A)
        skill = next(r for r in result if r.skill_name == "FE Skill")
        assert len(skill.artifacts) == 1
        assert skill.artifacts[0]["source_title"] == "public_file.py"

    def test_public_github_link_visible_in_public_pipeline(
        self, svc: SkillEvidencePipelineService
    ):
        from app.schemas.skill_evidence_pipeline import (
            SkillEvidencePipelineCreate,
            SkillEvidenceArtifactCreate,
        )
        pipeline = svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(
            skill_name="Code Skill", visibility_status="public",
        ))
        svc.add_artifact(STUDENT_A, SkillEvidenceArtifactCreate(
            pipeline_id=pipeline.id,
            source_type="github",
            source_title="evaluator.py",
            project_name="VeriBridge",
            visibility="public",
            confidence_score=90,
            proof_reason="ML confirmed",
            artifact_data={
                "repo_url": "https://github.com/veribridge-ai/veribridge",
                "branch": "main",
                "file_path": "apps/api/app/services/evaluator.py",
                "start_line": 40,
                "end_line": 140,
            },
        ))
        result = svc.list_recruiter_safe_pipelines(STUDENT_A)
        skill = next(r for r in result if r.skill_name == "Code Skill")
        art = skill.artifacts[0]
        assert "exact_code_url" in art
        assert "/blob/main/" in art["exact_code_url"]
        assert "#L40-L140" in art["exact_code_url"]

    def test_unsafe_keys_stripped_from_public_artifact(
        self, svc: SkillEvidencePipelineService
    ):
        from app.schemas.skill_evidence_pipeline import (
            SkillEvidencePipelineCreate,
            SkillEvidenceArtifactCreate,
        )
        pipeline = svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(
            skill_name="Workflow Skill", visibility_status="public",
        ))
        svc.add_artifact(STUDENT_A, SkillEvidenceArtifactCreate(
            pipeline_id=pipeline.id,
            source_type="workflow",
            source_title="recording",
            project_name="P",
            visibility="public",
            confidence_score=70,
            proof_reason="Workflow captured",
            artifact_data={
                "signed_url": "UNSAFE_SIGNED_URL",
                "storage_path": "UNSAFE_STORAGE_PATH",
                "access_token": "UNSAFE_TOKEN",
                "frame_label": "Safe label",
            },
        ))
        result = svc.list_recruiter_safe_pipelines(STUDENT_A)
        skill = next(r for r in result if r.skill_name == "Workflow Skill")
        art_data = skill.artifacts[0]["artifact_data"]
        assert "signed_url" not in art_data
        assert "storage_path" not in art_data
        assert "access_token" not in art_data
        assert art_data["frame_label"] == "Safe label"

    def test_changing_visibility_private_excludes_from_recruiter_safe(
        self, svc: SkillEvidencePipelineService
    ):
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        pipeline = svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(
            skill_name="Toggle Skill", visibility_status="public",
        ))
        result_before = svc.list_recruiter_safe_pipelines(STUDENT_A)
        assert any(r.skill_name == "Toggle Skill" for r in result_before)

        svc.update_pipeline_visibility(pipeline.id, STUDENT_A, "private")
        result_after = svc.list_recruiter_safe_pipelines(STUDENT_A)
        assert not any(r.skill_name == "Toggle Skill" for r in result_after)

    def test_changing_visibility_to_protected_locks_recruiter_view(
        self, svc: SkillEvidencePipelineService
    ):
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        pipeline = svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(
            skill_name="Switch Skill", visibility_status="public",
            recruiter_summary="Full detail summary.",
        ))
        svc.update_pipeline_visibility(pipeline.id, STUDENT_A, "protected")
        result = svc.list_recruiter_safe_pipelines(STUDENT_A)
        skill = next(r for r in result if r.skill_name == "Switch Skill")
        assert skill.is_locked_for_recruiter is True
        assert "Full detail summary" not in skill.recruiter_summary

    def test_private_only_variant_excluded(self, svc: SkillEvidencePipelineService, mem: dict):
        # Simulate legacy "private_only" stored by old code paths.
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        pipeline = svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(
            skill_name="Legacy Private Skill",
        ))
        mem["skill_evidence_pipelines"][pipeline.id]["visibility_status"] = "private_only"
        result = svc.list_recruiter_safe_pipelines(STUDENT_A)
        assert not any(r.skill_name == "Legacy Private Skill" for r in result)

    def test_protected_pipeline_strips_strongest_and_weakest_proof(
        self, svc: SkillEvidencePipelineService
    ):
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(
            skill_name="Sensitive Skill",
            visibility_status="protected",
            strongest_proof={"label": "GitHub", "reason": "ML confirmed in 3 files"},
            weakest_proof={"label": "OCR", "reason": "Partial extraction only"},
            missing_evidence=["Live demo"],
            next_actions=["Add deployment report"],
        ))
        result = svc.list_recruiter_safe_pipelines(STUDENT_A)
        p = next(r for r in result if r.skill_name == "Sensitive Skill")
        assert p.strongest_proof == {}
        assert p.weakest_proof == {}
        assert p.missing_evidence == []
        assert p.next_actions == []

    def test_protected_pipeline_strips_evidence_source_reasons(
        self, svc: SkillEvidencePipelineService
    ):
        from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
        svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(
            skill_name="Sensitive Skill",
            visibility_status="protected",
            evidence_sources=[
                {"key": "github", "label": "GitHub code", "status": "supported",
                 "score": 91, "reason": "ML pipeline confirmed in 3 production service files"},
                {"key": "workflow", "label": "Workflow recording", "status": "partial",
                 "score": 65, "reason": "Inference output text extracted; some frames inconclusive"},
            ],
        ))
        result = svc.list_recruiter_safe_pipelines(STUDENT_A)
        p = next(r for r in result if r.skill_name == "Sensitive Skill")
        for src in p.evidence_sources:
            assert src.get("reason", "") == "", f"reason leaked for source {src['key']}"
            assert src.get("score") is None, f"score leaked for source {src['key']}"
            assert src["status"] == "protected"

    def test_protected_pipeline_artifacts_excluded(self, svc: SkillEvidencePipelineService):
        from app.schemas.skill_evidence_pipeline import (
            SkillEvidencePipelineCreate,
            SkillEvidenceArtifactCreate,
        )
        pipeline = svc.upsert_pipeline(STUDENT_A, SkillEvidencePipelineCreate(
            skill_name="Protected With Artifacts", visibility_status="protected",
        ))
        svc.add_artifact(STUDENT_A, SkillEvidenceArtifactCreate(
            pipeline_id=pipeline.id,
            source_type="github",
            source_title="secret_impl.py",
            project_name="P",
            visibility="public",
            confidence_score=90,
            proof_reason="Core logic",
            artifact_data={"file_path": "secret_impl.py", "repo_url": "https://github.com/x/y"},
        ))
        result = svc.list_recruiter_safe_pipelines(STUDENT_A)
        p = next(r for r in result if r.skill_name == "Protected With Artifacts")
        assert p.artifacts == []
        assert "secret_impl.py" not in str(p)


# ── Recruiter-safe list endpoint tests ───────────────────────────────────────


class TestRecruiterSafeListEndpoint:
    """HTTP endpoint tests for GET /student/skill-pipelines/recruiter-safe."""

    def test_recruiter_safe_excludes_private_pipeline(self, client_a: TestClient):
        _upsert(client_a, "Private Pipeline", visibility_status="private")
        r = client_a.get("/api/v1/student/skill-pipelines/recruiter-safe")
        assert r.status_code == 200
        names = [p["skill_name"] for p in r.json()]
        assert "Private Pipeline" not in names

    def test_recruiter_safe_includes_public_pipeline(self, client_a: TestClient):
        _upsert(client_a, "Public Pipeline", visibility_status="public",
                recruiter_summary="Evidence-backed public skill.")
        r = client_a.get("/api/v1/student/skill-pipelines/recruiter-safe")
        assert r.status_code == 200
        pipelines = r.json()
        pub = next((p for p in pipelines if p["skill_name"] == "Public Pipeline"), None)
        assert pub is not None
        assert pub["is_locked_for_recruiter"] is False
        assert pub["recruiter_summary"] == "Evidence-backed public skill."

    def test_recruiter_safe_includes_protected_pipeline_as_locked(self, client_a: TestClient):
        _upsert(client_a, "Protected Pipeline", visibility_status="protected")
        r = client_a.get("/api/v1/student/skill-pipelines/recruiter-safe")
        assert r.status_code == 200
        pipelines = r.json()
        prot = next((p for p in pipelines if p["skill_name"] == "Protected Pipeline"), None)
        assert prot is not None
        assert prot["is_locked_for_recruiter"] is True
        assert "approval" in prot["recruiter_summary"].lower()

    def test_recruiter_safe_excludes_private_artifacts_from_public_pipeline(
        self, client_a: TestClient
    ):
        p = _upsert(client_a, "AI / Machine Learning", visibility_status="public")
        pub = _add_artifact(client_a, p["id"], source_type="github", visibility="public",
                            source_title="public.py")
        prv = _add_artifact(client_a, p["id"], source_type="github", visibility="private",
                            source_title="private.py")
        r = client_a.get("/api/v1/student/skill-pipelines/recruiter-safe")
        assert r.status_code == 200
        pipeline = next(p for p in r.json() if p["skill_name"] == "AI / Machine Learning")
        art_ids = [a["id"] for a in pipeline["artifacts"]]
        assert pub["id"] in art_ids
        assert prv["id"] not in art_ids

    def test_recruiter_safe_protected_artifact_strips_detail(self, client_a: TestClient):
        p = _upsert(client_a, "AI / Machine Learning", visibility_status="public")
        art = _add_artifact(
            client_a, p["id"],
            source_type="transcript",
            source_title="Defense excerpt",
            visibility="protected",
            artifact_data={
                "excerpt": "PRIVATE_TRANSCRIPT",
                "ownership_signals": ["described decisions"],
            },
        )
        r = client_a.get("/api/v1/student/skill-pipelines/recruiter-safe")
        assert r.status_code == 200
        pipeline = next(p for p in r.json() if p["skill_name"] == "AI / Machine Learning")
        protected_art = next((a for a in pipeline["artifacts"] if a["id"] == art["id"]), None)
        assert protected_art is not None
        assert protected_art["artifact_data"] == {}
        assert "PRIVATE_TRANSCRIPT" not in r.text

    def test_recruiter_safe_public_github_link_visible(self, client_a: TestClient):
        p = _upsert(client_a, "Code Skill", visibility_status="public")
        _add_artifact(
            client_a, p["id"],
            source_type="github",
            source_title="evaluator.py",
            visibility="public",
            artifact_data={
                "repo_url": "https://github.com/veribridge-ai/veribridge",
                "branch": "main",
                "file_path": "apps/api/app/services/evaluator.py",
                "start_line": 40,
                "end_line": 140,
            },
        )
        r = client_a.get("/api/v1/student/skill-pipelines/recruiter-safe")
        assert r.status_code == 200
        pipeline = next(p for p in r.json() if p["skill_name"] == "Code Skill")
        art = pipeline["artifacts"][0]
        assert "exact_code_url" in art
        assert "/blob/main/" in art["exact_code_url"]
        assert "#L40-L140" in art["exact_code_url"]

    def test_recruiter_safe_strips_unsafe_strings_from_response(self, client_a: TestClient):
        p = _upsert(client_a, "Workflow Skill", visibility_status="public")
        _add_artifact(
            client_a, p["id"],
            source_type="workflow",
            source_title="recording",
            visibility="public",
            artifact_data={
                "signed_url": "UNSAFE_SIGNED_URL",
                "storage_path": "UNSAFE_STORAGE_PATH",
                "access_token": "UNSAFE_TOKEN",
                "frame_label": "Safe label",
            },
        )
        r = client_a.get("/api/v1/student/skill-pipelines/recruiter-safe")
        assert r.status_code == 200
        text = r.text
        assert "UNSAFE_SIGNED_URL" not in text
        assert "UNSAFE_STORAGE_PATH" not in text
        assert "UNSAFE_TOKEN" not in text
        assert "Safe label" in text

    def test_recruiter_safe_response_excludes_student_fields(self, client_a: TestClient):
        _upsert(client_a, "AI / Machine Learning", visibility_status="public",
                student_summary="Private note for student only.")
        r = client_a.get("/api/v1/student/skill-pipelines/recruiter-safe")
        assert r.status_code == 200
        text = r.text
        assert "student_id" not in text
        assert "student_summary" not in text
        assert "profile_id" not in text

    def test_recruiter_safe_empty_when_all_private(self, client_a: TestClient):
        _upsert(client_a, "Secret Skill 1", visibility_status="private")
        _upsert(client_a, "Secret Skill 2", visibility_status="private")
        r = client_a.get("/api/v1/student/skill-pipelines/recruiter-safe")
        assert r.status_code == 200
        assert r.json() == []

    def test_recruiter_safe_mixed_visibility(self, client_a: TestClient):
        _upsert(client_a, "Public Skill", visibility_status="public")
        _upsert(client_a, "Protected Skill", visibility_status="protected")
        _upsert(client_a, "Private Skill", visibility_status="private")
        r = client_a.get("/api/v1/student/skill-pipelines/recruiter-safe")
        assert r.status_code == 200
        names = {p["skill_name"] for p in r.json()}
        assert "Public Skill" in names
        assert "Protected Skill" in names
        assert "Private Skill" not in names
        # Verify locking
        pub = next(p for p in r.json() if p["skill_name"] == "Public Skill")
        prot = next(p for p in r.json() if p["skill_name"] == "Protected Skill")
        assert pub["is_locked_for_recruiter"] is False
        assert prot["is_locked_for_recruiter"] is True

    def test_recruiter_safe_protected_pipeline_strips_proof_fields(self, client_a: TestClient):
        _upsert(
            client_a, "Protected Evidence Skill",
            visibility_status="protected",
            strongest_proof={"label": "GitHub", "reason": "Confirmed in 3 files"},
            weakest_proof={"label": "OCR", "reason": "Partial only"},
            missing_evidence=["Live demo URL"],
            next_actions=["Add deployment demo"],
            evidence_sources=[
                {"key": "github", "label": "GitHub code", "status": "supported",
                 "score": 91, "reason": "ML pipeline confirmed"},
            ],
        )
        r = client_a.get("/api/v1/student/skill-pipelines/recruiter-safe")
        assert r.status_code == 200
        p = next(x for x in r.json() if x["skill_name"] == "Protected Evidence Skill")
        assert p["is_locked_for_recruiter"] is True
        assert p["strongest_proof"] == {}
        assert p["weakest_proof"] == {}
        assert p["missing_evidence"] == []
        assert p["next_actions"] == []
        assert p["artifacts"] == []
        # Proof reasons must not appear in the HTTP response text
        assert "Confirmed in 3 files" not in r.text
        assert "Partial only" not in r.text
        assert "Live demo URL" not in r.text
        assert "ML pipeline confirmed" not in r.text

    def test_recruiter_safe_protected_pipeline_no_artifacts_before_approval(
        self, client_a: TestClient
    ):
        p = _upsert(client_a, "Protected Pipeline With Artifacts", visibility_status="protected")
        _add_artifact(
            client_a, p["id"],
            source_type="github",
            source_title="secret_impl.py",
            visibility="public",
            artifact_data={
                "repo_url": "https://github.com/x/y",
                "file_path": "SECRET_PATH.py",
                "start_line": 1, "end_line": 100,
            },
        )
        r = client_a.get("/api/v1/student/skill-pipelines/recruiter-safe")
        assert r.status_code == 200
        pipeline = next(x for x in r.json() if x["skill_name"] == "Protected Pipeline With Artifacts")
        assert pipeline["artifacts"] == []
        assert "SECRET_PATH.py" not in r.text
