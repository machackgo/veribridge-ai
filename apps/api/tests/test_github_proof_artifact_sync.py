"""Tests for GitHub Proof → Skill Evidence Artifact Sync.

Covers:
  ✓ wrong user cannot sync another user's proof (404)
  ✓ submitted/analyzing/failed/archived proofs do not sync (400)
  ✓ analyzed proof creates pipelines/artifacts
  ✓ second sync is idempotent, no duplicates
  ✓ artifact visibility defaults to protected
  ✓ artifact_data excludes unsafe raw analysis_snapshot / repo_metadata
  ✓ existing pipeline visibility is preserved
  ✓ existing Website Proof pipeline is not overwritten/downgraded
  ✓ GitHub-only evidence does not overclaim full verification
  ✓ needs_more_evidence falls back to submitted_skill_claims

All storage is in-memory (dict mode). No real network calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.services.github_proof_artifact_sync_service import (
    GitHubProofArtifactSyncService,
    GitHubProofNotFoundError,
    GitHubProofSyncStatusError,
)
from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
from app.services.skill_evidence_pipeline_service import SkillEvidencePipelineService

# ── Constants ─────────────────────────────────────────────────────────────────

STUDENT_A = "aaaaaaaa-1111-0000-0000-000000000001"
STUDENT_B = "bbbbbbbb-2222-0000-0000-000000000002"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def proof_db() -> dict:
    """In-memory store for github_proof_submissions."""
    return {}


@pytest.fixture()
def pipeline_db() -> dict:
    """In-memory store for skill_evidence_pipelines / artifacts tables."""
    return {}


@pytest.fixture()
def svc(proof_db: dict, pipeline_db: dict) -> GitHubProofArtifactSyncService:
    return GitHubProofArtifactSyncService(db=proof_db, pipeline_db=pipeline_db)


@pytest.fixture()
def client(proof_db: dict, pipeline_db: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: STUDENT_A
    app.dependency_overrides[get_db] = lambda: proof_db
    app.dependency_overrides[get_pipeline_db] = lambda: pipeline_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _seed_github_proof(
    proof_db: dict,
    user_id: str = STUDENT_A,
    *,
    status: str = "analyzed",
    detected_skills: list[str] | None = None,
    submitted_skill_claims: list[str] | None = None,
    confidence_score: int = 72,
    evidence_strength: str = "partial",
    **overrides,
) -> str:
    proof_id = str(uuid4())
    now_iso = datetime.now(UTC).isoformat()
    row = {
        "id": proof_id,
        "user_id": user_id,
        "proof_session_id": None,
        "repo_url": "https://github.com/example/project",
        "repo_owner": "example",
        "repo_name": "project",
        "default_branch": "main",
        "visibility": "public",
        "status": status,
        "submitted_skill_claims": submitted_skill_claims if submitted_skill_claims is not None else ["FastAPI", "React"],
        "detected_skills": detected_skills if detected_skills is not None else ["FastAPI", "React"],
        "repo_metadata": {
            "detected_stack": ["Python", "FastAPI", "React"],
            "detected_features": ["readme", "testing"],
            "evidence_files": ["README.md", "requirements.txt"],
            "warnings": [],
            "submitted_skill_claims": submitted_skill_claims if submitted_skill_claims is not None else ["FastAPI", "React"],
            "detected_skills": detected_skills if detected_skills is not None else ["FastAPI", "React"],
        },
        "analysis_summary": "Standalone GitHub proof supports backend and frontend work.",
        "evidence_strength": evidence_strength,
        "confidence_score": confidence_score,
        "risk_flags": [],
        "missing_evidence": ["deployment evidence"],
        "public_safe_summary": "GitHub proof for example/project is partial evidence with 72/100 confidence.",
        "analysis_snapshot": {
            "raw_dump": "should never be copied",
            "secret_token": "abc123",
        },
        "last_analyzed_at": datetime.now(UTC),
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    row.update(overrides)
    proof_db.setdefault("github_proof_submissions", {})[proof_id] = row
    return proof_id


def _seed_pipeline(pipeline_db: dict, user_id: str, **overrides) -> str:
    """Seed an existing skill_evidence_pipeline directly (e.g. from Website Proof)."""
    payload = SkillEvidencePipelineCreate(
        skill_name="FastAPI",
        skill_category="Backend",
        confidence_score=85,
        support_status="strongly_supported",
        evidence_count=1,
        evidence_sources=[
            {"key": "workflow", "label": "Workflow Recording", "status": "supported", "score": 85, "reason": "Live workflow demonstrated FastAPI"},
        ],
        recruiter_summary="Strong website proof evidence for FastAPI.",
        student_summary="Your FastAPI evidence is strong from Website Proof.",
        visibility_status="public",
    )
    data = payload.model_dump()
    data.update(overrides)
    payload = SkillEvidencePipelineCreate(**data)
    pipeline = SkillEvidencePipelineService(pipeline_db).upsert_pipeline(user_id, payload)
    return pipeline.id


# ── Tests: status gating ────────────────────────────────────────────────────

def test_wrong_user_cannot_sync_another_users_proof(svc: GitHubProofArtifactSyncService, proof_db: dict) -> None:
    proof_id = _seed_github_proof(proof_db, user_id=STUDENT_A)
    with pytest.raises(GitHubProofNotFoundError):
        svc.sync(user_id=STUDENT_B, github_proof_id=proof_id)


def test_nonexistent_proof_raises_not_found(svc: GitHubProofArtifactSyncService) -> None:
    with pytest.raises(GitHubProofNotFoundError):
        svc.sync(user_id=STUDENT_A, github_proof_id=str(uuid4()))


@pytest.mark.parametrize("status", ["submitted", "analyzing", "failed", "archived"])
def test_disallowed_statuses_do_not_sync(svc: GitHubProofArtifactSyncService, proof_db: dict, status: str) -> None:
    proof_id = _seed_github_proof(proof_db, status=status)
    with pytest.raises(GitHubProofSyncStatusError):
        svc.sync(user_id=STUDENT_A, github_proof_id=proof_id)


def test_wrong_user_returns_404_via_endpoint(client: TestClient, proof_db: dict) -> None:
    proof_id = _seed_github_proof(proof_db, user_id=STUDENT_B)
    response = client.post(f"/api/v1/student/skill-pipelines/from-github-proof/{proof_id}")
    assert response.status_code == 404


@pytest.mark.parametrize("status", ["submitted", "analyzing", "failed", "archived"])
def test_disallowed_statuses_return_400_via_endpoint(client: TestClient, proof_db: dict, status: str) -> None:
    proof_id = _seed_github_proof(proof_db, status=status)
    response = client.post(f"/api/v1/student/skill-pipelines/from-github-proof/{proof_id}")
    assert response.status_code == 400


# ── Tests: analyzed proof sync ──────────────────────────────────────────────

def test_analyzed_proof_creates_pipelines_and_artifacts(svc: GitHubProofArtifactSyncService, proof_db: dict, pipeline_db: dict) -> None:
    proof_id = _seed_github_proof(proof_db, detected_skills=["FastAPI", "React"], confidence_score=90)

    result = svc.sync(user_id=STUDENT_A, github_proof_id=proof_id)

    assert result.already_synced is False
    assert sorted(result.skills_synced) == ["FastAPI", "React"]
    assert result.pipelines_upserted == 2
    assert result.artifacts_created == 2
    assert result.errors == []

    pipelines = SkillEvidencePipelineService(pipeline_db).list_pipelines_for_student(STUDENT_A)
    assert {p.skill_name for p in pipelines} == {"FastAPI", "React"}


def test_analyzed_proof_via_endpoint(client: TestClient, proof_db: dict) -> None:
    proof_id = _seed_github_proof(proof_db, detected_skills=["FastAPI"], confidence_score=90)

    response = client.post(f"/api/v1/student/skill-pipelines/from-github-proof/{proof_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["already_synced"] is False
    assert body["skills_synced"] == ["FastAPI"]
    assert body["pipelines_upserted"] == 1
    assert body["artifacts_created"] == 1
    assert body["errors"] == []


# ── Tests: idempotency ──────────────────────────────────────────────────────

def test_second_sync_is_idempotent(svc: GitHubProofArtifactSyncService, proof_db: dict, pipeline_db: dict) -> None:
    proof_id = _seed_github_proof(proof_db, detected_skills=["FastAPI"], confidence_score=90)

    first = svc.sync(user_id=STUDENT_A, github_proof_id=proof_id)
    assert first.already_synced is False
    assert first.artifacts_created == 1

    second = svc.sync(user_id=STUDENT_A, github_proof_id=proof_id)
    assert second.already_synced is True
    assert second.artifacts_created == 0

    # No duplicate artifacts created
    pipelines = SkillEvidencePipelineService(pipeline_db).list_pipelines_for_student(STUDENT_A)
    assert len(pipelines) == 1
    artifacts = SkillEvidencePipelineService(pipeline_db).list_artifacts_for_pipeline(pipelines[0].id, STUDENT_A)
    github_artifacts = [a for a in artifacts if a.source_type == "github"]
    assert len(github_artifacts) == 1


# ── Tests: artifact safety ──────────────────────────────────────────────────

def test_artifact_visibility_defaults_to_protected(svc: GitHubProofArtifactSyncService, proof_db: dict, pipeline_db: dict) -> None:
    proof_id = _seed_github_proof(proof_db, detected_skills=["FastAPI"], confidence_score=90)
    svc.sync(user_id=STUDENT_A, github_proof_id=proof_id)

    pipelines = SkillEvidencePipelineService(pipeline_db).list_pipelines_for_student(STUDENT_A)
    artifacts = SkillEvidencePipelineService(pipeline_db).list_artifacts_for_pipeline(pipelines[0].id, STUDENT_A)
    github_artifact = next(a for a in artifacts if a.source_type == "github")
    assert github_artifact.visibility == "protected"


def test_artifact_data_excludes_unsafe_raw_analysis_snapshot(svc: GitHubProofArtifactSyncService, proof_db: dict, pipeline_db: dict) -> None:
    proof_id = _seed_github_proof(proof_db, detected_skills=["FastAPI"], confidence_score=90)
    svc.sync(user_id=STUDENT_A, github_proof_id=proof_id)

    pipelines = SkillEvidencePipelineService(pipeline_db).list_pipelines_for_student(STUDENT_A)
    artifacts = SkillEvidencePipelineService(pipeline_db).list_artifacts_for_pipeline(pipelines[0].id, STUDENT_A)
    github_artifact = next(a for a in artifacts if a.source_type == "github")

    assert "analysis_snapshot" not in github_artifact.artifact_data
    assert "repo_metadata" not in github_artifact.artifact_data
    serialized = str(github_artifact.artifact_data)
    assert "secret_token" not in serialized
    assert "raw_dump" not in serialized

    # Safe fields are present
    assert github_artifact.artifact_data["github_proof_id"] == proof_id
    assert github_artifact.artifact_data["repo_url"] == "https://github.com/example/project"
    assert github_artifact.artifact_data["repo_owner"] == "example"
    assert github_artifact.artifact_data["repo_name"] == "project"
    assert github_artifact.artifact_data["default_branch"] == "main"
    assert github_artifact.artifact_data["detected_skills"] == ["FastAPI"]
    assert github_artifact.artifact_data["evidence_strength"] == "partial"
    assert github_artifact.artifact_data["confidence_score"] == 90
    assert isinstance(github_artifact.artifact_data["last_analyzed_at"], str)


# ── Tests: existing pipeline preservation ───────────────────────────────────

def test_existing_pipeline_visibility_is_preserved(svc: GitHubProofArtifactSyncService, proof_db: dict, pipeline_db: dict) -> None:
    _seed_pipeline(pipeline_db, STUDENT_A, visibility_status="private")
    proof_id = _seed_github_proof(proof_db, detected_skills=["FastAPI"], confidence_score=95)

    svc.sync(user_id=STUDENT_A, github_proof_id=proof_id)

    pipelines = SkillEvidencePipelineService(pipeline_db).list_pipelines_for_student(STUDENT_A)
    fastapi_pipeline = next(p for p in pipelines if p.skill_name == "FastAPI")
    assert fastapi_pipeline.visibility_status == "private"


def test_existing_website_proof_pipeline_not_overwritten_or_downgraded(svc: GitHubProofArtifactSyncService, proof_db: dict, pipeline_db: dict) -> None:
    _seed_pipeline(
        pipeline_db,
        STUDENT_A,
        skill_name="FastAPI",
        confidence_score=85,
        support_status="strongly_supported",
        recruiter_summary="Strong website proof evidence for FastAPI.",
        student_summary="Your FastAPI evidence is strong from Website Proof.",
        visibility_status="public",
        evidence_sources=[
            {"key": "workflow", "label": "Workflow Recording", "status": "supported", "score": 85, "reason": "Live workflow demonstrated FastAPI"},
        ],
    )
    proof_id = _seed_github_proof(proof_db, detected_skills=["FastAPI"], confidence_score=99)

    svc.sync(user_id=STUDENT_A, github_proof_id=proof_id)

    pipelines = SkillEvidencePipelineService(pipeline_db).list_pipelines_for_student(STUDENT_A)
    assert len(pipelines) == 1  # no duplicate created from case differences
    fastapi_pipeline = pipelines[0]

    # confidence_score and support_status never downgraded
    assert fastapi_pipeline.confidence_score == 85
    assert fastapi_pipeline.support_status == "strongly_supported"
    assert fastapi_pipeline.visibility_status == "public"

    # recruiter/student summaries preserved, not overwritten
    assert fastapi_pipeline.recruiter_summary == "Strong website proof evidence for FastAPI."
    assert fastapi_pipeline.student_summary == "Your FastAPI evidence is strong from Website Proof."

    # GitHub merged into evidence_sources, existing workflow source preserved
    keys = {s["key"] for s in fastapi_pipeline.evidence_sources}
    assert keys == {"workflow", "github"}
    assert fastapi_pipeline.evidence_count == 2


# ── Tests: no overclaiming from GitHub-only evidence ────────────────────────

def test_github_only_evidence_does_not_overclaim_full_verification(svc: GitHubProofArtifactSyncService, proof_db: dict, pipeline_db: dict) -> None:
    proof_id = _seed_github_proof(proof_db, detected_skills=["FastAPI"], confidence_score=100)

    svc.sync(user_id=STUDENT_A, github_proof_id=proof_id)

    pipelines = SkillEvidencePipelineService(pipeline_db).list_pipelines_for_student(STUDENT_A)
    fastapi_pipeline = pipelines[0]

    # Never "strongly_supported" from GitHub evidence alone, and confidence capped
    assert fastapi_pipeline.support_status == "partially_supported"
    assert fastapi_pipeline.confidence_score <= 75
    assert fastapi_pipeline.visibility_status == "protected"


# ── Tests: needs_more_evidence partial sync ─────────────────────────────────

def test_needs_more_evidence_falls_back_to_submitted_skill_claims(svc: GitHubProofArtifactSyncService, proof_db: dict, pipeline_db: dict) -> None:
    proof_id = _seed_github_proof(
        proof_db,
        status="needs_more_evidence",
        detected_skills=[],
        submitted_skill_claims=["Python"],
        confidence_score=40,
        evidence_strength="weak",
    )

    result = svc.sync(user_id=STUDENT_A, github_proof_id=proof_id)

    assert result.errors == []
    assert result.skills_synced == ["Python"]

    pipelines = SkillEvidencePipelineService(pipeline_db).list_pipelines_for_student(STUDENT_A)
    python_pipeline = next(p for p in pipelines if p.skill_name == "Python")
    assert python_pipeline.support_status == "needs_review"
    assert python_pipeline.confidence_score <= 50


def test_needs_more_evidence_with_no_skills_returns_error(svc: GitHubProofArtifactSyncService, proof_db: dict) -> None:
    proof_id = _seed_github_proof(
        proof_db,
        status="needs_more_evidence",
        detected_skills=[],
        submitted_skill_claims=[],
        confidence_score=20,
        evidence_strength="insufficient",
    )

    result = svc.sync(user_id=STUDENT_A, github_proof_id=proof_id)

    assert result.errors
    assert result.artifacts_created == 0
    assert result.pipelines_upserted == 0


def test_analyzed_proof_with_no_detected_skills_returns_error(svc: GitHubProofArtifactSyncService, proof_db: dict) -> None:
    """An analyzed proof with no detected skills has nothing usable to sync.

    Submitted claims are not used as a fallback for fully "analyzed" proofs
    (only for "needs_more_evidence"), so this must produce errors and create
    no artifacts/pipelines.
    """
    proof_id = _seed_github_proof(
        proof_db,
        status="analyzed",
        detected_skills=[],
        submitted_skill_claims=["Python"],
        confidence_score=55,
    )

    result = svc.sync(user_id=STUDENT_A, github_proof_id=proof_id)

    assert result.errors
    assert result.artifacts_created == 0
    assert result.pipelines_upserted == 0
    assert result.skills_synced == []


# ── Tests: evidence_count preservation ──────────────────────────────────────

def test_existing_strong_evidence_count_is_preserved_and_incremented(svc: GitHubProofArtifactSyncService, proof_db: dict, pipeline_db: dict) -> None:
    """A strong existing evidence_count (e.g. from Website Proof, 55) must not
    be overwritten by len(evidence_sources) (e.g. 2) — it should only grow."""
    _seed_pipeline(
        pipeline_db,
        STUDENT_A,
        skill_name="FastAPI",
        evidence_count=55,
        evidence_sources=[
            {"key": "workflow", "label": "Workflow Recording", "status": "supported", "score": 85, "reason": "Live workflow demonstrated FastAPI"},
        ],
    )
    proof_id = _seed_github_proof(proof_db, detected_skills=["FastAPI"], confidence_score=80)

    svc.sync(user_id=STUDENT_A, github_proof_id=proof_id)

    pipelines = SkillEvidencePipelineService(pipeline_db).list_pipelines_for_student(STUDENT_A)
    fastapi_pipeline = next(p for p in pipelines if p.skill_name == "FastAPI")
    assert fastapi_pipeline.evidence_count >= 56
