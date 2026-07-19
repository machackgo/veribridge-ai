"""Evidence-derived claimed skills for the project-first Project Defense flow.

Projects created through the plain Projects flow (POST /vbr/projects) start
with empty metadata and the project-first workspace never collects a
claimed-skills list. These tests lock in the fix for the resulting pipeline
break — "Save explanation evidence to Skill Graph" failed with
"No claimed skills on this project — nothing to sync." for every
project-first defense:

  - derive_claimed_skills_from_attached: deterministic skill list from SAFE
    attached-proof summaries only (GitHub detected_skills, document skills,
    website supported_skills), junk labels filtered, deduped, capped
  - effective_claimed_skills: explicit claimed_skills always win untouched
  - merged context / eligible cards expose the derived skills
  - defense questions include skill-grounded questions for derived skills
  - Skill Graph sync succeeds end-to-end for a plain project with attached
    proofs but no typed claimed skills
  - sync resolves the merged duplicate group (evidence attached to a sibling
    row is included; skills derived across the whole group)
  - a project with no skills anywhere still reports an honest, actionable
    error message (never an unexplained failure)

All storage is in-memory (dict mode). No real network calls, no LLM calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.services.vbr_project_defense import (
    derive_claimed_skills_from_attached,
    effective_claimed_skills,
)

USER_ID = "00000000-0000-0000-0000-000000000042"

BASE = "/api/v1/student/vbr"

DEFENSE_TRANSCRIPT = (
    "I built the sticky notes app myself using React and JavaScript. "
    "I designed the drag and drop board, implemented the note components, "
    "and wired the frontend state management by hand."
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

def _now() -> str:
    return datetime.now(UTC).isoformat()


def _seed_plain_project(
    mem_store: dict,
    *,
    title: str = "Sticky Notes",
    repo_url: str = "https://github.com/octocat/Hello-World",
    metadata: dict | None = None,
) -> str:
    """A project exactly as the plain Projects flow creates it: empty metadata."""
    project_id = str(uuid4())
    now = _now()
    owner_repo = "/".join(repo_url.rstrip("/").split("/")[-2:])
    mem_store.setdefault("vbr_projects", {})[project_id] = {
        "id": project_id,
        "user_id": USER_ID,
        "title": title,
        "repo_url": repo_url,
        "repo_full_name": owner_repo,
        "deployed_url": None,
        "head_sha": None,
        "status": "draft",
        "metadata": metadata if metadata is not None else {},
        "created_at": now,
        "updated_at": now,
    }
    return project_id


def _seed_github_proof(mem_store: dict, **overrides) -> str:
    proof_id = str(uuid4())
    now = _now()
    row = {
        "id": proof_id,
        "user_id": USER_ID,
        "proof_session_id": None,
        "repo_url": "https://github.com/octocat/Hello-World",
        "repo_owner": "octocat",
        "repo_name": "Hello-World",
        "default_branch": "main",
        "visibility": "public",
        "status": "analyzed",
        "submitted_skill_claims": [],
        "detected_skills": [
            # Junk concatenated label a real analyzer emitted — must be filtered.
            "React JavaScript Context API State Management Drag and Drop CRUD Operations",
            "JavaScript",
            "React",
            "Frontend Development",
        ],
        "repo_metadata": {},
        "analysis_summary": "Repo demonstrates frontend work.",
        "evidence_strength": "partial",
        "confidence_score": 48,
        "risk_flags": [],
        "missing_evidence": [],
        "public_safe_summary": "GitHub proof for octocat/Hello-World is weak evidence.",
        "analysis_snapshot": {},
        "last_analyzed_at": now,
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    mem_store.setdefault("github_proof_submissions", {})[proof_id] = row
    return proof_id


def _seed_document_evidence(mem_store: dict, *, skills: list[str] | None = None) -> str:
    doc_id = str(uuid4())
    now = _now()
    mem_store.setdefault("optional_evidence_submissions", {})[doc_id] = {
        "id": doc_id,
        "user_id": USER_ID,
        "proof_session_id": None,
        "source_type": "document",
        "status": "analyzed",
        "analysis_json": {"title": "Sticky Notes Technical Overview"},
        "evidence_objects": [
            {"skill_name": s, "evidence_text": "…"} for s in (skills or [])
        ],
        "file_path": None,
        "created_at": now,
        "updated_at": now,
    }
    return doc_id


def _attach(client: TestClient, project_id: str, **body):
    return client.post(
        f"{BASE}/project-defense/projects/{project_id}/attach-proofs", json=body
    )


def _generate_questions(client: TestClient, project_id: str):
    return client.post(f"{BASE}/projects/{project_id}/generate-defense-questions")


def _submit_defense(client: TestClient, session_id: str, **body):
    return client.post(f"{BASE}/sessions/{session_id}/submit-defense", json=body)


def _sync(client: TestClient, session_id: str):
    return client.post(
        f"/api/v1/student/skill-pipelines/from-project-defense/{session_id}"
    )


# ── Unit: derivation helpers ─────────────────────────────────────────────────

def test_derive_skills_from_all_three_proof_summaries() -> None:
    attached = {
        "github_proof": {"detected_skills": ["Python", "FastAPI"]},
        "documents": [{"skills": ["SQL", "python"]}],  # dedupes case-insensitively
        "website_proofs": [{"supported_skills": ["Web Development"]}],
    }
    assert derive_claimed_skills_from_attached(attached) == [
        "Python",
        "FastAPI",
        "SQL",
        "Web Development",
    ]


def test_derive_skills_filters_junk_labels_and_caps() -> None:
    attached = {
        "github_proof": {
            "detected_skills": [
                "React JavaScript Context API State Management Drag and Drop CRUD",
                "A" * 41,  # too long
                "React",
            ]
        },
        "documents": [{"skills": [f"Skill {i}" for i in range(20)]}],
    }
    derived = derive_claimed_skills_from_attached(attached)
    assert derived[0] == "React"
    assert len(derived) == 12  # capped
    assert all(len(s) <= 40 and len(s.split()) <= 4 for s in derived)


def test_derive_skills_empty_for_no_attached() -> None:
    assert derive_claimed_skills_from_attached(None) == []
    assert derive_claimed_skills_from_attached({}) == []


def test_effective_claimed_skills_explicit_always_wins() -> None:
    metadata = {
        "claimed_skills": ["Rust"],
        "attached_proofs": {"github_proof": {"detected_skills": ["Python"]}},
    }
    assert effective_claimed_skills(metadata) == ["Rust"]


# ── Project-first flow: derived skills flow through every surface ────────────

def test_context_and_questions_use_derived_skills(client: TestClient, mem_store: dict) -> None:
    project_id = _seed_plain_project(mem_store)
    github_id = _seed_github_proof(mem_store)
    assert _attach(client, project_id, github_proof_id=github_id).status_code == 200

    context = client.get(
        f"{BASE}/project-defense/projects/{project_id}/context"
    ).json()
    assert context["metadata"]["claimed_skills"] == [
        "JavaScript",
        "React",
        "Frontend Development",
    ]

    questions = _generate_questions(client, project_id).json()["questions"]
    skill_questions = [
        q for q in questions if q["target_ref"].get("kind") == "skill_repo_link"
    ]
    assert {q["target_ref"]["skill"] for q in skill_questions} == {
        "JavaScript",
        "React",
        "Frontend Development",
    }


def test_eligible_card_exposes_derived_skills(client: TestClient, mem_store: dict) -> None:
    project_id = _seed_plain_project(mem_store)
    github_id = _seed_github_proof(mem_store)
    _attach(client, project_id, github_proof_id=github_id)

    cards = client.get(f"{BASE}/project-defense/eligible-projects").json()["projects"]
    card = next(c for c in cards if c["id"] == project_id)
    assert card["claimed_skills"] == ["JavaScript", "React", "Frontend Development"]


def test_sync_succeeds_for_plain_project_with_derived_skills(
    client: TestClient, mem_store: dict, pipeline_db: dict
) -> None:
    """THE regression: project-first defense (no typed claimed skills) must save."""
    from app.services.skill_evidence_pipeline_service import SkillEvidencePipelineService

    project_id = _seed_plain_project(mem_store)
    github_id = _seed_github_proof(mem_store)
    _attach(client, project_id, github_proof_id=github_id)

    session_id = _generate_questions(client, project_id).json()["session_id"]
    submit = _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)
    assert submit.status_code == 200, submit.text
    analysis = submit.json()["analysis"]
    # Analysis now has a skill vocabulary to match the transcript against.
    assert "React" in analysis["skills_mentioned"]
    assert "JavaScript" in analysis["skills_mentioned"]

    response = _sync(client, session_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["errors"] == []
    assert sorted(body["skills_synced"]) == [
        "Frontend Development",
        "JavaScript",
        "React",
    ]
    assert body["artifacts_created"] == 3

    pipeline_svc = SkillEvidencePipelineService(pipeline_db)
    pipelines = pipeline_svc.list_pipelines_for_student(USER_ID)
    assert {p.skill_name for p in pipelines} == {
        "JavaScript",
        "React",
        "Frontend Development",
    }
    for pipeline in pipelines:
        assert pipeline.visibility_status == "protected"
        assert pipeline.confidence_score <= 50


def test_sync_resolves_merged_duplicate_group(
    client: TestClient, mem_store: dict, pipeline_db: dict
) -> None:
    """Evidence attached to a sibling duplicate row is part of the sync package."""
    from app.services.skill_evidence_pipeline_service import SkillEvidencePipelineService

    # Two rows for the same logical project (same repo identity).
    project_a = _seed_plain_project(mem_store, title="Sticky Notes")
    project_b = _seed_plain_project(mem_store, title="Sticky Notes")
    github_id = _seed_github_proof(mem_store)
    doc_id = _seed_document_evidence(mem_store, skills=["Technical Writing"])
    _attach(client, project_a, github_proof_id=github_id)
    _attach(client, project_b, document_evidence_ids=[doc_id])

    # Defense session binds to row A; row B holds the document.
    session_id = _generate_questions(client, project_a).json()["session_id"]
    _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)

    body = _sync(client, session_id).json()
    assert body["errors"] == []
    # Skills derived across the WHOLE group: GitHub row + document row.
    assert "Technical Writing" in body["skills_synced"]

    pipeline_svc = SkillEvidencePipelineService(pipeline_db)
    pipelines = pipeline_svc.list_pipelines_for_student(USER_ID)
    any_pipeline = pipelines[0]
    artifacts = pipeline_svc.list_artifacts_for_pipeline(any_pipeline.id, USER_ID)
    artifact = next(a for a in artifacts if a.artifact_data.get("kind") == "project_defense")
    refs = artifact.artifact_data["attached_proof_refs"]
    # The sibling row's document is referenced, not lost.
    assert refs.get("document_evidence_ids") == [doc_id]
    assert refs.get("github_proof_id") == github_id


def test_context_reports_skill_graph_synced_state(
    client: TestClient, mem_store: dict, pipeline_db: dict
) -> None:
    """A reloaded workspace shows the honest saved/not-saved Skill Graph state."""
    project_id = _seed_plain_project(mem_store)
    github_id = _seed_github_proof(mem_store)
    _attach(client, project_id, github_proof_id=github_id)
    session_id = _generate_questions(client, project_id).json()["session_id"]
    _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)

    context_url = f"{BASE}/project-defense/projects/{project_id}/context"
    before = client.get(context_url).json()
    assert before["session_id"] == session_id
    assert before["skill_graph_synced"] is False

    assert _sync(client, session_id).json()["errors"] == []

    after = client.get(context_url).json()
    assert after["skill_graph_synced"] is True


def test_sync_with_no_skills_anywhere_reports_actionable_error(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _seed_plain_project(mem_store)
    github_id = _seed_github_proof(mem_store, detected_skills=[])
    _attach(client, project_id, github_proof_id=github_id)

    session_id = _generate_questions(client, project_id).json()["session_id"]
    _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)

    body = _sync(client, session_id).json()
    assert body["ok"] is True
    assert body["skills_synced"] == []
    assert len(body["errors"]) == 1
    # Honest, actionable message — the UI surfaces this verbatim.
    assert "attach github, website, or document proof" in body["errors"][0].lower()
