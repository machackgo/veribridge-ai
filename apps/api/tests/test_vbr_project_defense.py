"""Tests for Project Defense (Phase 1 — individual project defense MVP).

Covers:
  - creating an individual project defense identity (repo_url required,
    derivable from an attached GitHub proof)
  - storing safe attached-proof summaries in vbr_projects.metadata
  - generating deterministic defense questions
  - saving manual/pasted answers as a transcript + segments (no video)
  - deterministic transcript analysis
  - ownership checks (404 for other users)

Skill Graph artifact sync is covered separately in
test_project_defense_artifact_sync.py.

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


def _seed_skill_pipeline(pipeline_db: dict, student_id: str = USER_ID, **overrides) -> str:
    pipeline_id = str(uuid4())
    now_iso = datetime.now(UTC).isoformat()
    row = {
        "id": pipeline_id,
        "student_id": student_id,
        "skill_name": "Python",
        "skill_category": "technical",
        "confidence_score": 70,
        "support_status": "partially_supported",
        "evidence_count": 1,
        "strongest_proof": {},
        "weakest_proof": {},
        "missing_evidence": [],
        "next_actions": [],
        "evidence_sources": [],
        "recruiter_summary": "",
        "student_summary": "",
        "visibility_status": "public",
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    row.update(overrides)
    pipeline_db.setdefault("skill_evidence_pipelines", {})[pipeline_id] = row
    return pipeline_id


def _generate_questions(client: TestClient, project_id: str):
    return client.post(f"/api/v1/student/vbr/projects/{project_id}/generate-defense-questions")


def _submit_defense(client: TestClient, session_id: str, **body):
    return client.post(f"/api/v1/student/vbr/sessions/{session_id}/submit-defense", json=body)


# ── Project identity creation ────────────────────────────────────────────────

def test_create_individual_project_with_repo_url(client: TestClient) -> None:
    response = _create_project_defense(client)
    assert response.status_code == 201, response.text
    body = response.json()

    project = body["project"]
    assert project["title"] == "Skill Evidence Tracker"
    assert project["repo_url"] == "https://github.com/octocat/Hello-World"
    assert project["repo_full_name"] == "octocat/Hello-World"
    assert project["status"] == "draft"

    metadata = body["metadata"]
    assert metadata["individual_project_only"] is True
    assert metadata["phase"] == "project_defense_mvp_v1"
    assert metadata["claimed_skills"] == ["Python", "React"]
    assert metadata["description"] == "A platform that tracks student skill evidence across proof sources."
    assert metadata["student_role"] == "I built the backend API and the React dashboard."
    assert metadata["attached_proofs"] == {}


def test_create_rejects_missing_repo_url_and_github_proof(client: TestClient) -> None:
    response = _create_project_defense(client, repo_url=None)
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "vbr_repo_url_required"


def test_create_derives_repo_url_from_attached_github_proof(client: TestClient, mem_store: dict) -> None:
    proof_id = _seed_github_proof(mem_store)

    response = _create_project_defense(
        client,
        repo_url=None,
        attached_proofs={"github_proof_id": proof_id},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["project"]["repo_url"] == "https://github.com/octocat/Hello-World"
    assert body["project"]["repo_full_name"] == "octocat/Hello-World"

    github_summary = body["metadata"]["attached_proofs"]["github_proof"]
    assert github_summary["github_proof_id"] == proof_id
    assert github_summary["repo_url"] == "https://github.com/octocat/Hello-World"
    assert github_summary["detected_skills"] == ["Python", "React"]

    # Raw analysis snapshot / repo metadata must never be copied into vbr_projects.metadata
    serialized = str(body["metadata"])
    assert "should-never-leak" not in serialized
    assert "analysis_snapshot" not in github_summary
    assert "repo_metadata" not in github_summary


def test_create_rejects_other_users_github_proof(client: TestClient, mem_store: dict) -> None:
    proof_id = _seed_github_proof(mem_store, user_id=OTHER_USER_ID)

    response = _create_project_defense(
        client,
        repo_url=None,
        attached_proofs={"github_proof_id": proof_id},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "vbr_github_proof_not_found"


def test_create_stores_safe_document_summary(client: TestClient, mem_store: dict) -> None:
    doc_id = _seed_document_evidence(mem_store)

    response = _create_project_defense(
        client,
        attached_proofs={"document_evidence_ids": [doc_id]},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    documents = body["metadata"]["attached_proofs"]["documents"]
    assert documents == [
        {
            "document_evidence_id": doc_id,
            "title": "Final Year Project Report",
            "source_type": "document",
            "status": "analyzed",
        }
    ]


def test_create_rejects_unknown_document_evidence(client: TestClient) -> None:
    response = _create_project_defense(
        client,
        attached_proofs={"document_evidence_ids": [str(uuid4())]},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "vbr_document_evidence_not_found"


def test_create_project_defense_not_found_for_other_user(client: TestClient) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = _generate_questions(client, project_id)
    assert response.status_code == 404


# ── Deterministic defense question generation ────────────────────────────────

def test_generate_defense_questions(client: TestClient) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]

    response = _generate_questions(client, project_id)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["project_id"] == project_id
    assert body["status"] == "questions_ready"
    assert body["session_id"]

    questions = body["questions"]
    assert len(questions) >= 6

    kinds = {q["target_ref"].get("kind") for q in questions}
    assert "architecture" in kinds
    assert "contribution" in kinds
    assert "challenge" in kinds
    assert "improvement" in kinds
    # Both claimed skills get a dedicated question
    skills_in_questions = {q["target_ref"].get("skill") for q in questions if q["target_ref"].get("skill")}
    assert skills_in_questions == {"Python", "React"}

    # Project status advances
    project_after = client.get(f"/api/v1/student/vbr/projects/{project_id}").json()
    assert project_after["status"] == "questions_ready"


def test_generate_defense_questions_references_attached_proofs(client: TestClient, mem_store: dict) -> None:
    github_proof_id = _seed_github_proof(mem_store)
    doc_id = _seed_document_evidence(mem_store)

    created = _create_project_defense(
        client,
        repo_url=None,
        attached_proofs={
            "github_proof_id": github_proof_id,
            "document_evidence_ids": [doc_id],
        },
    ).json()
    project_id = created["project"]["id"]

    response = _generate_questions(client, project_id)
    assert response.status_code == 200, response.text
    questions = response.json()["questions"]

    kinds = {q["target_ref"].get("kind") for q in questions}
    assert "skill_repo_link" in kinds  # GitHub proof attached → repo-linked skill questions
    assert "document_link" in kinds    # Document proof attached

    repo_question = next(q for q in questions if q["target_ref"].get("kind") == "skill_repo_link")
    assert "https://github.com/octocat/Hello-World" in repo_question["question_text"]


# ── Attached proof ownership gaps (website proof / skill pipelines) ─────────

def test_create_rejects_website_proof_session_id(client: TestClient) -> None:
    response = _create_project_defense(
        client,
        attached_proofs={"website_proof_session_id": "ws-session-1"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "vbr_website_proof_not_supported"


def test_create_rejects_skill_pipeline_owned_by_other_user(client: TestClient, pipeline_db: dict) -> None:
    pipeline_id = _seed_skill_pipeline(pipeline_db, student_id=OTHER_USER_ID)

    response = _create_project_defense(
        client,
        attached_proofs={"skill_pipeline_ids": [pipeline_id]},
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "vbr_skill_pipeline_not_found"


def test_create_rejects_unknown_skill_pipeline_id(client: TestClient) -> None:
    response = _create_project_defense(
        client,
        attached_proofs={"skill_pipeline_ids": [str(uuid4())]},
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "vbr_skill_pipeline_not_found"


def test_create_stores_owned_skill_pipeline_ids(client: TestClient, pipeline_db: dict) -> None:
    pipeline_id = _seed_skill_pipeline(pipeline_db, student_id=USER_ID)

    response = _create_project_defense(
        client,
        attached_proofs={"skill_pipeline_ids": [pipeline_id]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["metadata"]["attached_proofs"]["skill_pipeline_ids"] == [pipeline_id]


# ── Manual transcript + deterministic analysis ───────────────────────────────

def test_submit_defense_rejects_empty_answers(client: TestClient) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]

    response = _submit_defense(client, session_id)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_no_answers_provided"


def test_submit_defense_with_combined_text_stores_transcript_and_analyzes(client: TestClient, mem_store: dict) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]

    response = _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["project_id"] == project_id
    assert body["session_id"] == session_id
    assert body["segment_count"] == 1
    assert body["transcript_id"]

    # No video/keyframes required — manual transcript only.
    transcripts = mem_store["vbr_transcripts"]
    assert len(transcripts) == 1
    transcript_row = next(iter(transcripts.values()))
    assert transcript_row["full_text"] == DEFENSE_TRANSCRIPT
    assert transcript_row["session_id"] == session_id

    segments = mem_store["vbr_transcript_segments"]
    assert len(segments) == 1

    analysis = body["analysis"]
    assert analysis["overall_defense_score"] >= 60
    assert "Python" in analysis["skills_mentioned"]
    assert "React" in analysis["skills_mentioned"]
    assert analysis["privacy_scan_status"] == "clean"

    # Analysis is stored on the session telemetry for later sync.
    session_row = mem_store["vbr_verification_sessions"][session_id]
    assert session_row["telemetry"]["project_defense_analysis"]["overall_defense_score"] == analysis["overall_defense_score"]


def test_submit_defense_with_per_question_answers_marks_questions_answered(client: TestClient, mem_store: dict) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    gen = _generate_questions(client, project_id).json()
    session_id = gen["session_id"]
    questions = gen["questions"]

    answers = [
        {"question_id": q["id"], "answer_text": f"Answer for: {q['question_text']}"}
        for q in questions[:2]
    ]

    response = _submit_defense(client, session_id, answers=answers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answered_question_count"] == 2
    assert body["segment_count"] == 2

    answered_ids = {q["id"] for q in questions[:2]}
    for q in mem_store["vbr_session_questions"].values():
        if q["id"] in answered_ids:
            assert q["answered"] is True
        else:
            assert q["answered"] is False


def test_submit_defense_marks_project_metadata_analyzed(client: TestClient) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]

    assert created["project"]["metadata"].get("project_defense_status") is None

    response = _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)
    assert response.status_code == 200, response.text

    project_after = client.get(f"/api/v1/student/vbr/projects/{project_id}").json()
    assert project_after["metadata"]["project_defense_status"] == "analyzed"
    # Phase 1 identity is preserved alongside the new status flag.
    assert project_after["metadata"]["phase"] == "project_defense_mvp_v1"


def test_submit_defense_not_found_for_other_user(client: TestClient) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)
    assert response.status_code == 404
