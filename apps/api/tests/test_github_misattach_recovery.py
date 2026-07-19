"""Recovery from legacy identity-conflicting GitHub proof→project attachments.

A relationship row recorded before the repository-identity write gate can
attach a GitHub proof to a project whose own declared repository contradicts
the proof's repository (the historical "wikitok attached to Sticky Notes"
mis-attach). Such an edge is already excluded by every canonical read path,
but it used to:

  1. surface a false "Attached to <wrong project>" chip on the GitHub proofs
     listing (no identity gate there), and
  2. permanently block attaching the proof to its REAL project — the
     finalization boundary treated the stale edge as a hard conflict.

These tests lock in both fixes: the listing applies the same identity read
gate, and finalization downgrades the provably-wrong edge to
``mismatched_project`` (the 058 schema's state for exactly this) instead of
refusing forever.

All storage is in-memory (dict mode). No real network calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app

USER_ID = "00000000-0000-0000-0000-000000000042"

BASE = "/api/v1/student"


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


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _seed_project(mem_store: dict, *, title: str, repo_url: str) -> str:
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
        "metadata": {},
        "created_at": now,
        "updated_at": now,
    }
    return project_id


def _seed_github_proof(mem_store: dict, *, repo_url: str) -> str:
    proof_id = str(uuid4())
    now = _now()
    owner, repo = repo_url.rstrip("/").split("/")[-2:]
    mem_store.setdefault("github_proof_submissions", {})[proof_id] = {
        "id": proof_id,
        "user_id": USER_ID,
        "proof_session_id": None,
        "repo_url": repo_url,
        "repo_owner": owner,
        "repo_name": repo,
        "default_branch": "main",
        "visibility": "public",
        "status": "analyzed",
        "submitted_skill_claims": [],
        "detected_skills": ["React", "TypeScript"],
        "repo_metadata": {},
        "analysis_summary": "ok",
        "evidence_strength": "partial",
        "confidence_score": 50,
        "risk_flags": [],
        "missing_evidence": [],
        "public_safe_summary": f"GitHub proof for {owner}/{repo}.",
        "analysis_snapshot": {},
        "last_analyzed_at": now,
        "created_at": now,
        "updated_at": now,
    }
    return proof_id


def _seed_direct_relationship(mem_store: dict, *, proof_id: str, project_id: str) -> str:
    rel_id = str(uuid4())
    now = _now()
    mem_store.setdefault("proof_project_relationships", {})[rel_id] = {
        "id": rel_id,
        "owner_user_id": USER_ID,
        "proof_type": "github",
        "proof_id": proof_id,
        "project_id": project_id,
        "relationship_state": "directly_linked",
        "match_method": "user_confirmation",
        "confirmed_by_user": True,
        "provenance": {"source": "github_attach_finalization"},
        "created_at": now,
        "updated_at": now,
    }
    return rel_id


def test_listing_hides_identity_conflicting_attachment(client: TestClient, mem_store: dict) -> None:
    wrong_project = _seed_project(
        mem_store, title="Sticky Notes", repo_url="https://github.com/dennisivy/Sticky-Notes-React"
    )
    proof_id = _seed_github_proof(mem_store, repo_url="https://github.com/IsaacGemal/wikitok")
    _seed_direct_relationship(mem_store, proof_id=proof_id, project_id=wrong_project)

    proofs = client.get(f"{BASE}/github-proofs").json()
    proof = next(p for p in proofs if p["id"] == proof_id)
    # The stale identity-conflicting edge must NOT surface as an attachment.
    assert proof.get("project_id") in (None, "")
    assert proof.get("project_title") in (None, "")
    assert proof.get("project_relationship_state") in (None, "", "vault_only")


def test_listing_keeps_identity_valid_attachment(client: TestClient, mem_store: dict) -> None:
    project = _seed_project(
        mem_store, title="WikiTok", repo_url="https://github.com/IsaacGemal/wikitok"
    )
    proof_id = _seed_github_proof(mem_store, repo_url="https://github.com/IsaacGemal/wikitok")
    _seed_direct_relationship(mem_store, proof_id=proof_id, project_id=project)

    proofs = client.get(f"{BASE}/github-proofs").json()
    proof = next(p for p in proofs if p["id"] == proof_id)
    assert proof["project_id"] == project
    assert proof["project_title"] == "WikiTok"
    assert proof["project_relationship_state"] == "directly_linked"


def test_finalize_downgrades_stale_invalid_edge_and_attaches_real_project(
    client: TestClient, mem_store: dict
) -> None:
    wrong_project = _seed_project(
        mem_store, title="Sticky Notes", repo_url="https://github.com/dennisivy/Sticky-Notes-React"
    )
    real_project = _seed_project(
        mem_store, title="WikiTok", repo_url="https://github.com/IsaacGemal/wikitok"
    )
    proof_id = _seed_github_proof(mem_store, repo_url="https://github.com/IsaacGemal/wikitok")
    stale_id = _seed_direct_relationship(mem_store, proof_id=proof_id, project_id=wrong_project)

    response = client.post(
        f"{BASE}/vbr/passport/proofs/finalize",
        json={"proof_type": "github", "proof_id": proof_id, "project_id": real_project},
    )
    assert response.status_code == 200, response.text

    rows = mem_store["proof_project_relationships"]
    stale = rows[stale_id]
    assert stale["relationship_state"] == "mismatched_project"
    assert stale["confirmed_by_user"] is False
    assert stale["provenance"]["downgraded_reason"] == "repo_identity_conflict"

    direct = [
        r for r in rows.values()
        if r["proof_id"] == proof_id and r["relationship_state"] == "directly_linked"
    ]
    assert len(direct) == 1
    assert direct[0]["project_id"] == real_project

    # And the listing now shows the honest attachment.
    proofs = client.get(f"{BASE}/github-proofs").json()
    proof = next(p for p in proofs if p["id"] == proof_id)
    assert proof["project_title"] == "WikiTok"


def test_finalize_still_conflicts_for_same_repo_projects(client: TestClient, mem_store: dict) -> None:
    """A directly_linked edge to a SAME-repo project is a genuine conflict."""
    project_a = _seed_project(
        mem_store, title="WikiTok A", repo_url="https://github.com/IsaacGemal/wikitok"
    )
    project_b = _seed_project(
        mem_store, title="WikiTok B", repo_url="https://github.com/IsaacGemal/wikitok"
    )
    proof_id = _seed_github_proof(mem_store, repo_url="https://github.com/IsaacGemal/wikitok")
    _seed_direct_relationship(mem_store, proof_id=proof_id, project_id=project_a)

    response = client.post(
        f"{BASE}/vbr/passport/proofs/finalize",
        json={"proof_type": "github", "proof_id": proof_id, "project_id": project_b},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "proof_relationship_conflict"
