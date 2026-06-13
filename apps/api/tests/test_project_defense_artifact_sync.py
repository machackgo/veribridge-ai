"""Tests for Project Defense → Skill Graph artifact sync (Phase 1).

Covers:
  - sync requires a completed deterministic analysis first
  - sync creates protected skill_evidence_artifacts with
    source_type="transcript" and artifact_data.kind="project_defense"
  - sync is idempotent (safe to call multiple times for the same session)
  - sync never leaks the full transcript / raw metadata / storage paths
  - sync never downgrades stronger existing evidence (e.g. GitHub Proof)
  - ownership checks (404 for other users)

All storage is in-memory (dict mode). No real network calls, no LLM calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app

USER_ID = "00000000-0000-0000-0000-000000000042"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000099"


DEFENSE_TRANSCRIPT = (
    "I built this project to solve the problem of tracking student skill evidence. "
    "My approach was to design a REST API backend using Python and FastAPI with a "
    "PostgreSQL database, and a React frontend for the dashboard. I implemented the "
    "authentication middleware myself and designed the database schema for storing "
    "evidence records. I also configured the API endpoints and built the component "
    "architecture for the React frontend. One limitation of the current version is "
    "that it does not yet support real-time updates, and in the future I would "
    "improve the caching layer for better performance."
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def pipeline_db() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict, pipeline_db: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: pipeline_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_project_defense(client: TestClient, **overrides: object):
    payload = {
        "title": "Skill Evidence Tracker",
        "description": "A platform that tracks student skill evidence across proof sources.",
        "claimed_skills": ["Python", "React"],
        "student_role": "I built the backend API and the React dashboard.",
        "repo_url": "https://github.com/octocat/Hello-World",
        **overrides,
    }
    return client.post("/api/v1/student/vbr/project-defense", json=payload)


def _seed_github_proof(mem_store: dict, user_id: str = USER_ID, **overrides) -> str:
    proof_id = str(uuid4())
    now_iso = datetime.now(UTC).isoformat()
    row = {
        "id": proof_id,
        "user_id": user_id,
        "proof_session_id": None,
        "repo_url": "https://github.com/octocat/Hello-World",
        "repo_owner": "octocat",
        "repo_name": "Hello-World",
        "default_branch": "main",
        "visibility": "public",
        "status": "analyzed",
        "submitted_skill_claims": ["Python", "React"],
        "detected_skills": ["Python", "React"],
        "repo_metadata": {"secret_token": "should-never-leak"},
        "analysis_summary": "Repo demonstrates backend and frontend work.",
        "evidence_strength": "partial",
        "confidence_score": 72,
        "risk_flags": [],
        "missing_evidence": [],
        "public_safe_summary": "GitHub proof for octocat/Hello-World is partial evidence with 72/100 confidence.",
        "analysis_snapshot": {"raw_dump": "should-never-leak"},
        "last_analyzed_at": now_iso,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    row.update(overrides)
    mem_store.setdefault("github_proof_submissions", {})[proof_id] = row
    return proof_id


def _seed_document_evidence(mem_store: dict, user_id: str = USER_ID, **overrides) -> str:
    doc_id = str(uuid4())
    now_iso = datetime.now(UTC).isoformat()
    row = {
        "id": doc_id,
        "user_id": user_id,
        "proof_session_id": None,
        "source_type": "document",
        "status": "analyzed",
        "analysis_json": {"title": "Final Year Project Report"},
        "file_path": None,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    row.update(overrides)
    mem_store.setdefault("optional_evidence_submissions", {})[doc_id] = row
    return doc_id


def _generate_questions(client: TestClient, project_id: str):
    return client.post(f"/api/v1/student/vbr/projects/{project_id}/generate-defense-questions")


def _submit_defense(client: TestClient, session_id: str, **body):
    return client.post(f"/api/v1/student/vbr/sessions/{session_id}/submit-defense", json=body)


def _sync(client: TestClient, session_id: str):
    return client.post(f"/api/v1/student/skill-pipelines/from-project-defense/{session_id}")


# ── Skill Graph sync ────────────────────────────────────────────────────────

def test_sync_requires_analysis_first(client: TestClient) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]

    response = _sync(client, session_id)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "project_defense_not_analyzed"


def test_sync_creates_protected_transcript_artifacts(client: TestClient, mem_store: dict, pipeline_db: dict) -> None:
    from app.services.skill_evidence_pipeline_service import SkillEvidencePipelineService

    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]
    _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)

    response = _sync(client, session_id)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["ok"] is True
    assert body["already_synced"] is False
    assert sorted(body["skills_synced"]) == ["Python", "React"]
    assert body["pipelines_upserted"] == 2
    assert body["artifacts_created"] == 2
    assert body["errors"] == []

    pipeline_svc = SkillEvidencePipelineService(pipeline_db)
    pipelines = pipeline_svc.list_pipelines_for_student(USER_ID)
    assert {p.skill_name for p in pipelines} == {"Python", "React"}

    for pipeline in pipelines:
        assert pipeline.visibility_status == "protected"
        assert pipeline.support_status in {"partially_supported", "needs_review"}
        assert pipeline.confidence_score <= 50

        artifacts = pipeline_svc.list_artifacts_for_pipeline(pipeline.id, USER_ID)
        artifact = next(a for a in artifacts if a.source_type == "transcript")
        assert artifact.visibility == "protected"
        assert artifact.artifact_data["kind"] == "project_defense"
        assert artifact.artifact_data["vbr_session_id"] == session_id
        assert artifact.artifact_data["vbr_project_id"] == project_id


def test_sync_is_idempotent(client: TestClient, mem_store: dict, pipeline_db: dict) -> None:
    from app.services.skill_evidence_pipeline_service import SkillEvidencePipelineService

    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]
    _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)

    first = _sync(client, session_id).json()
    assert first["already_synced"] is False
    assert first["artifacts_created"] == 2

    second = _sync(client, session_id).json()
    assert second["already_synced"] is True
    assert second["artifacts_created"] == 0

    pipeline_svc = SkillEvidencePipelineService(pipeline_db)
    pipelines = pipeline_svc.list_pipelines_for_student(USER_ID)
    assert len(pipelines) == 2
    for pipeline in pipelines:
        artifacts = pipeline_svc.list_artifacts_for_pipeline(pipeline.id, USER_ID)
        project_defense_artifacts = [a for a in artifacts if a.artifact_data.get("kind") == "project_defense"]
        assert len(project_defense_artifacts) == 1


def test_sync_does_not_leak_full_transcript_or_raw_metadata(client: TestClient, mem_store: dict, pipeline_db: dict) -> None:
    from app.services.skill_evidence_pipeline_service import SkillEvidencePipelineService

    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]
    _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)
    _sync(client, session_id)

    pipeline_svc = SkillEvidencePipelineService(pipeline_db)
    pipelines = pipeline_svc.list_pipelines_for_student(USER_ID)
    for pipeline in pipelines:
        artifacts = pipeline_svc.list_artifacts_for_pipeline(pipeline.id, USER_ID)
        artifact = next(a for a in artifacts if a.source_type == "transcript")
        data = artifact.artifact_data

        for unsafe_key in (
            "full_transcript", "transcript_text", "refined_transcript",
            "video_path", "storage_path", "signed_url", "access_token",
            "telemetry", "metadata", "analysis_snapshot",
        ):
            assert unsafe_key not in data

        # Excerpt is capped — never the full transcript.
        assert len(data["capped_transcript_excerpt"]) <= 300
        assert data["capped_transcript_excerpt"] != DEFENSE_TRANSCRIPT
        assert DEFENSE_TRANSCRIPT not in str(data)


def test_sync_does_not_downgrade_existing_stronger_evidence(client: TestClient, mem_store: dict, pipeline_db: dict) -> None:
    from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
    from app.services.skill_evidence_pipeline_service import SkillEvidencePipelineService

    pipeline_svc = SkillEvidencePipelineService(pipeline_db)
    pipeline_svc.upsert_pipeline(
        USER_ID,
        SkillEvidencePipelineCreate(
            skill_name="Python",
            skill_category="Backend",
            confidence_score=85,
            support_status="strongly_supported",
            evidence_count=1,
            evidence_sources=[
                {"key": "github", "label": "GitHub", "status": "supported", "score": 85, "reason": "Strong GitHub evidence for Python."},
            ],
            recruiter_summary="Strong GitHub evidence for Python.",
            student_summary="Your Python evidence is strong from GitHub Proof.",
            visibility_status="public",
        ),
    )

    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]
    _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)

    response = _sync(client, session_id)
    assert response.status_code == 200, response.text

    pipelines = pipeline_svc.list_pipelines_for_student(USER_ID)
    python_pipeline = next(p for p in pipelines if p.skill_name == "Python")

    # Stronger existing evidence is never downgraded.
    assert python_pipeline.confidence_score == 85
    assert python_pipeline.support_status == "strongly_supported"
    assert python_pipeline.visibility_status == "public"
    assert python_pipeline.recruiter_summary == "Strong GitHub evidence for Python."

    keys = {s["key"] for s in python_pipeline.evidence_sources}
    assert keys == {"github", "project_defense"}


def test_sync_not_found_for_other_user(client: TestClient, mem_store: dict) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]
    _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = _sync(client, session_id)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "project_defense_session_not_found"
