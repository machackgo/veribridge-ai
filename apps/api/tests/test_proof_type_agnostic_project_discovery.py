"""Proof-type-agnostic Passport project discovery.

The Work Passport must recognize an owned project from ANY explicitly linked
proof type — never only from Website Proof. These tests pin the eligibility
contract end-to-end over the real API surface (dict-mode storage, no network):

  owned project AND (an explicitly finalized owned proof OR canonical
  project claim/evidence relationships) ⇒ the project appears on the private
  passport with its proof-type sources, honest limitations, and a report.

Also pinned:
  - a GitHub/Document proof linked ONLY by canonical ``proof_project_relationships``
    rows (legacy ``attached_proofs`` metadata missing) still surfaces;
  - vault-only proof never creates or joins a project;
  - finalization is idempotent (no duplicate claims/links);
  - tenant isolation for same-repo / same-title projects across users.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app

from tests.test_vbr_project_defense import (
    OTHER_USER_ID,
    USER_ID,
    _seed_document_evidence,
    _seed_github_proof,
)


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


def _as_user(user_id: str) -> None:
    app.dependency_overrides[get_current_user_id] = lambda: user_id


REPO_URL = "https://github.com/IsaacGemal/wikitok"


def _create_project(client: TestClient, title: str = "WikiTok Open-Source Pipeline Test") -> str:
    res = client.post(
        "/api/v1/student/vbr/projects",
        json={"title": title, "repo_url": REPO_URL},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _finalize(client: TestClient, proof_type: str, proof_id: str, project_id: str):
    return client.post(
        "/api/v1/student/vbr/passport/proofs/finalize",
        json={"proof_type": proof_type, "proof_id": proof_id, "project_id": project_id},
    )


def _passport(client: TestClient) -> dict:
    res = client.get("/api/v1/student/vbr/passport")
    assert res.status_code == 200, res.text
    return res.json()


def _report(client: TestClient, project_id: str) -> dict:
    res = client.get(f"/api/v1/student/vbr/projects/{project_id}/report")
    assert res.status_code == 200, res.text
    return res.json()


def _seed_wikitok_github_proof(mem_store: dict, **overrides) -> str:
    return _seed_github_proof(
        mem_store,
        repo_url=REPO_URL,
        repo_owner="IsaacGemal",
        repo_name="wikitok",
        detected_skills=["React", "TypeScript"],
        submitted_skill_claims=["React", "TypeScript"],
        public_safe_summary="Public GitHub repository with React/TypeScript evidence.",
        analysis_snapshot={},
        **overrides,
    )


def _seed_wikitok_document(mem_store: dict, **overrides) -> str:
    return _seed_document_evidence(
        mem_store,
        analysis_json={"title": "WikiTok Architecture and Evidence Validation Report"},
        evidence_objects=[
            {
                "skill_name": "React",
                "page_number": 3,
                "section_label": "Frontend Architecture",
                "block_type": "table",
                "snippet": "The feed component tree uses React hooks for state.",
            },
            {
                "skill_name": "TypeScript",
                "page_number": 5,
                "section_label": "Type Safety",
                "block_type": "code_block",
                "snippet": "Interfaces cover the Wikipedia API response types.",
            },
        ],
        **overrides,
    )


# ── GitHub-only project ───────────────────────────────────────────────────────


def test_github_only_project_appears_in_passport_with_report(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _create_project(client)
    proof_id = _seed_wikitok_github_proof(mem_store)

    res = _finalize(client, "github", proof_id, project_id)
    assert res.status_code == 200, res.text

    body = _passport(client)
    assert [p["project_id"] for p in body["projects"]] == [project_id]
    project = body["projects"][0]
    assert "GitHub Proof" in project["evidence_sources"]
    assert "Website Proof" not in project["evidence_sources"]

    report = _report(client, project_id)
    assert report["evidence_package"]["github_proof_attached"] is True
    assert report["evidence_package"]["website_proofs_count"] == 0
    # Honest missing-proof limitations — Website Proof absence never blocks.
    assert any("Website proof not attached" in item for item in report["limitations"])
    assert any("No document proof attached" in item for item in report["limitations"])
    # No claimed skills on the project ⇒ the matrix derives rows from the
    # attached GitHub Proof's analyzed detected skills (marked as detection).
    matrix_skills = {row["skill"] for row in report["skill_evidence"]}
    assert {"React", "TypeScript"} <= matrix_skills
    github_rows = [
        row for row in report["skill_evidence"] if "GitHub Proof" in row["supporting_sources"]
    ]
    assert github_rows, "GitHub-backed skills must carry the GitHub Proof source"


def test_github_only_project_skills_reach_passport_skill_cards(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _create_project(client)
    proof_id = _seed_wikitok_github_proof(mem_store)
    assert _finalize(client, "github", proof_id, project_id).status_code == 200

    body = _passport(client)
    skills_by_name = {s["skill"]: s for s in body["skills"]}
    assert "React" in skills_by_name
    react_projects = {
        ref["project_id"] for ref in skills_by_name["React"].get("projects") or []
    }
    assert project_id in react_projects


# ── Document-only project ─────────────────────────────────────────────────────


def test_document_only_project_appears_in_passport_with_report(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _create_project(client)
    doc_id = _seed_wikitok_document(mem_store)

    res = _finalize(client, "document", doc_id, project_id)
    assert res.status_code == 200, res.text

    body = _passport(client)
    assert [p["project_id"] for p in body["projects"]] == [project_id]
    project = body["projects"][0]
    assert "Document Proof" in project["evidence_sources"]
    assert "Website Proof" not in project["evidence_sources"]

    report = _report(client, project_id)
    assert report["evidence_package"]["documents_count"] == 1
    assert report["evidence_package"]["github_proof_attached"] is False
    assert any("GitHub Proof not attached" in item for item in report["limitations"])
    assert any("Website proof not attached" in item for item in report["limitations"])
    matrix_skills = {row["skill"] for row in report["skill_evidence"]}
    assert {"React", "TypeScript"} <= matrix_skills
    doc_rows = [
        row for row in report["skill_evidence"] if "Document Proof" in row["supporting_sources"]
    ]
    assert doc_rows, "Document-backed skills must carry the Document Proof source"


# ── Mixed proof types stay ONE project ────────────────────────────────────────


def test_github_plus_document_stay_one_project_with_both_sources(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _create_project(client)
    gh_id = _seed_wikitok_github_proof(mem_store)
    doc_id = _seed_wikitok_document(mem_store)
    assert _finalize(client, "github", gh_id, project_id).status_code == 200
    assert _finalize(client, "document", doc_id, project_id).status_code == 200

    body = _passport(client)
    assert len(body["projects"]) == 1
    sources = body["projects"][0]["evidence_sources"]
    assert "GitHub Proof" in sources
    assert "Document Proof" in sources
    assert "Website Proof" not in sources

    report = _report(client, project_id)
    assert report["evidence_package"]["github_proof_attached"] is True
    assert report["evidence_package"]["documents_count"] == 1


# ── Canonical relationship rows alone are authoritative (read fallback) ──────


def test_github_proof_linked_only_by_canonical_row_still_surfaces(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _create_project(client)
    proof_id = _seed_wikitok_github_proof(mem_store)
    # Canonical 058 relationship row WITHOUT the legacy metadata write.
    mem_store.setdefault("proof_project_relationships", {})[str(uuid4())] = {
        "owner_user_id": USER_ID,
        "proof_type": "github",
        "proof_id": proof_id,
        "project_id": project_id,
        "relationship_state": "directly_linked",
        "match_method": "user_confirmation",
        "confirmed_by_user": True,
    }

    report = _report(client, project_id)
    assert report["evidence_package"]["github_proof_attached"] is True
    assert report["github_proof"]["repo_url"] == REPO_URL

    body = _passport(client)
    assert "GitHub Proof" in body["projects"][0]["evidence_sources"]


def test_document_proof_linked_only_by_canonical_row_still_surfaces(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _create_project(client)
    doc_id = _seed_wikitok_document(mem_store)
    mem_store.setdefault("proof_project_relationships", {})[str(uuid4())] = {
        "owner_user_id": USER_ID,
        "proof_type": "document",
        "proof_id": doc_id,
        "project_id": project_id,
        "relationship_state": "directly_linked",
        "match_method": "user_confirmation",
        "confirmed_by_user": True,
    }

    report = _report(client, project_id)
    assert report["evidence_package"]["documents_count"] == 1
    assert report["documents"][0]["title"] == "WikiTok Architecture and Evidence Validation Report"

    body = _passport(client)
    assert "Document Proof" in body["projects"][0]["evidence_sources"]


def test_canonical_row_and_legacy_metadata_never_duplicate_a_document(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _create_project(client)
    doc_id = _seed_wikitok_document(mem_store)
    # Finalize writes BOTH the legacy metadata and the canonical row.
    assert _finalize(client, "document", doc_id, project_id).status_code == 200

    report = _report(client, project_id)
    assert report["evidence_package"]["documents_count"] == 1
    assert len(report["documents"]) == 1


# ── Vault-only proof creates nothing ─────────────────────────────────────────


def test_vault_only_github_and_document_create_no_project(
    client: TestClient, mem_store: dict
) -> None:
    _seed_wikitok_github_proof(mem_store)
    _seed_wikitok_document(mem_store)

    body = _passport(client)
    assert body["projects"] == []
    assert not mem_store.get("vbr_projects")
    assert not mem_store.get("proof_project_relationships")
    # The proof is still preserved (visible) in the vault, honestly unattached.
    assert body["vault_unattached_count"] >= 1


# ── Idempotency / no duplicate claims or links ────────────────────────────────


def test_github_finalization_is_idempotent_no_duplicate_claims_or_links(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _create_project(client)
    proof_id = _seed_wikitok_github_proof(mem_store)

    first = _finalize(client, "github", proof_id, project_id)
    claims_after_first = dict(mem_store.get("vbr_project_skill_claims") or {})
    links_after_first = dict(mem_store.get("vbr_claim_evidence_links") or {})
    relationships_after_first = dict(mem_store.get("proof_project_relationships") or {})

    second = _finalize(client, "github", proof_id, project_id)

    assert first.status_code == 200 and second.status_code == 200
    assert (mem_store.get("vbr_project_skill_claims") or {}) == claims_after_first
    assert (mem_store.get("vbr_claim_evidence_links") or {}) == links_after_first
    assert len(mem_store.get("proof_project_relationships") or {}) == len(
        relationships_after_first
    )

    body = _passport(client)
    assert len(body["projects"]) == 1


def test_document_finalization_conflict_on_second_project(
    client: TestClient, mem_store: dict
) -> None:
    first_project = _create_project(client, title="WikiTok Open-Source Pipeline Test")
    second_project = _create_project(client, title="Another Owned Project")
    doc_id = _seed_wikitok_document(mem_store)

    assert _finalize(client, "document", doc_id, first_project).status_code == 200
    conflict = _finalize(client, "document", doc_id, second_project)
    assert conflict.status_code == 409


# ── Tenant + project isolation ────────────────────────────────────────────────


def test_same_repo_and_title_under_two_users_stay_isolated(
    client: TestClient, mem_store: dict
) -> None:
    # Other user: same repo, same title, with an attached GitHub proof.
    _as_user(OTHER_USER_ID)
    other_project = _create_project(client)
    other_proof = _seed_wikitok_github_proof(mem_store, user_id=OTHER_USER_ID)
    assert _finalize(client, "github", other_proof, other_project).status_code == 200

    # Current user: same repo/title project, NO attached proof.
    _as_user(USER_ID)
    my_project = _create_project(client)

    body = _passport(client)
    assert [p["project_id"] for p in body["projects"]] == [my_project]
    assert body["projects"][0]["evidence_sources"] == []

    report = _report(client, my_project)
    assert report["evidence_package"]["github_proof_attached"] is False


def test_foreign_github_proof_and_foreign_project_denied(
    client: TestClient, mem_store: dict
) -> None:
    my_project = _create_project(client)
    foreign_proof = _seed_wikitok_github_proof(mem_store, user_id=OTHER_USER_ID)

    _as_user(OTHER_USER_ID)
    foreign_project = _create_project(client, title="Foreign WikiTok")
    _as_user(USER_ID)
    my_proof = _seed_wikitok_github_proof(mem_store)

    denied_proof = _finalize(client, "github", foreign_proof, my_project)
    denied_project = _finalize(client, "github", my_proof, foreign_project)
    assert denied_proof.status_code == 404
    assert denied_project.status_code == 404
    # Nothing was written for either denied call.
    assert not mem_store.get("proof_project_relationships")


def test_foreign_canonical_relationship_row_never_leaks_into_my_report(
    client: TestClient, mem_store: dict
) -> None:
    my_project = _create_project(client)
    foreign_proof = _seed_wikitok_github_proof(mem_store, user_id=OTHER_USER_ID)
    # A (hypothetical/corrupt) relationship row owned by ANOTHER user pointing
    # at my project id must not surface anything on my report.
    mem_store.setdefault("proof_project_relationships", {})[str(uuid4())] = {
        "owner_user_id": OTHER_USER_ID,
        "proof_type": "github",
        "proof_id": foreign_proof,
        "project_id": my_project,
        "relationship_state": "directly_linked",
    }

    report = _report(client, my_project)
    assert report["evidence_package"]["github_proof_attached"] is False


# ── GitHub proof list carries the canonical relationship state ───────────────


def test_github_proof_list_exposes_relationship_state(
    client: TestClient, mem_store: dict
) -> None:
    proof_id = _seed_wikitok_github_proof(mem_store)

    before = client.get("/api/v1/student/github-proofs")
    assert before.status_code == 200
    entry = next(p for p in before.json() if p["id"] == proof_id)
    assert entry["project_relationship_state"] == "vault_only"
    assert entry["project_id"] is None

    project_id = _create_project(client)
    assert _finalize(client, "github", proof_id, project_id).status_code == 200

    after = client.get("/api/v1/student/github-proofs")
    entry = next(p for p in after.json() if p["id"] == proof_id)
    assert entry["project_relationship_state"] == "directly_linked"
    assert entry["project_id"] == project_id
    assert entry["project_title"] == "WikiTok Open-Source Pipeline Test"
