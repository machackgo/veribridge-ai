"""Tests for the VeriBridge Proof Synthesis Agent.

The agent connects a skill's already-safe proof evidence (collected by the Student
Proof Vault) into recruiter-verifiable proof *chains*: GitHub code (implementation)
+ Website workflow (runtime) + Project Defense (understanding), with documents as
*corroboration* — never primary proof. It assigns a qualitative confidence tier
(never a numeric score), cites every synthesis statement to real evidence ids
(never fabricating), and pushes unrelated/unattached proofs into a capped
"unlinked supporting evidence" bucket.

All storage is in-memory (dict mode). No network / LLM calls.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.proof_synthesis_agent_service import (
    TIER_NEEDS_REVIEW,
    TIER_STRONG,
    build_skill_proof_synthesis,
)

from tests.test_vbr_project_defense import (
    USER_ID,
    _seed_document_evidence,
    _seed_github_proof,
    _seed_workflow_analysis,
)

_SESSIONS_TABLE = "vbr_verification_sessions"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def pipeline_db() -> dict:
    return {}


# ── Seed helpers ──────────────────────────────────────────────────────────────


def _seed_project(
    mem_store: dict,
    *,
    title: str,
    repo_full_name: str | None = None,
    attached_proofs: dict | None = None,
) -> str:
    pid = str(uuid4())
    mem_store.setdefault("vbr_projects", {})[pid] = {
        "id": pid,
        "user_id": USER_ID,
        "title": title,
        "repo_full_name": repo_full_name,
        "repo_url": f"https://github.com/{repo_full_name}" if repo_full_name else None,
        "metadata": {"attached_proofs": attached_proofs or {}},
        "created_at": "2026-01-01T00:00:00Z",
    }
    return pid


def _seed_defense_session(
    mem_store: dict,
    *,
    project_id: str,
    skills_explained: list[str],
    summary: str = "The candidate clearly explained how the prediction route works.",
) -> str:
    session_id = str(uuid4())
    mem_store.setdefault(_SESSIONS_TABLE, {})[session_id] = {
        "id": session_id,
        "user_id": USER_ID,
        "project_id": project_id,
        "attempt_no": 1,
        "telemetry": {
            "project_defense_analysis": {
                "skills_explained_well": skills_explained,
                "skills_mentioned": [],
                "recruiter_summary": summary,
            }
        },
        "created_at": "2026-01-01T00:00:00Z",
    }
    return session_id


def _strong_github(mem_store: dict, skill: str = "Python") -> str:
    return _seed_github_proof(
        mem_store,
        detected_skills=[skill],
        analysis_snapshot={
            "skill_code_evidence": [
                {
                    "skill": skill,
                    "file_path": "api.py",
                    "line_start": 252,
                    "line_end": 255,
                    "function_name": "predict",
                    "code_snippet": "def predict(req):\n    return model.predict(req)",
                }
            ]
        },
    )


def _all_evidence_ids(chain: dict) -> set[str]:
    ids: set[str] = set()
    for key in ("github_evidence", "website_evidence", "defense_evidence", "video_evidence"):
        ids |= {str(e["source_id"]) for e in chain.get(key, [])}
    ids |= {str(d["source_id"]) for d in chain.get("document_correlations", [])}
    return ids


# ── 1. Link GitHub + Document + Defense by project ────────────────────────────


def test_synthesis_links_github_document_defense_by_project(mem_store: dict, pipeline_db: dict) -> None:
    gh_id = _strong_github(mem_store, "Python")
    doc_id = _seed_document_evidence(
        mem_store,
        analysis_json={"title": "Boston Report"},
        evidence_objects=[
            {"skill_name": "Python", "confidence": "high", "snippet": "prediction API", "page_number": 2}
        ],
    )
    pid = _seed_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={
            "github_proof": {"github_proof_id": gh_id},
            "documents": [{"document_evidence_id": doc_id}],
        },
    )
    _seed_defense_session(mem_store, project_id=pid, skills_explained=["Python"])

    report = build_skill_proof_synthesis(mem_store, pipeline_db, USER_ID, "python")
    chains = report["proof_chains"]
    assert len(chains) == 1, "GitHub + Document + Defense for one project = ONE chain"
    chain = chains[0]
    assert chain["github_evidence"], "code implementation present"
    assert chain["defense_evidence"], "defense understanding present"
    # The document is corroboration, never primary proof.
    assert chain["document_correlations"]
    assert all(c["support_label"] == "Supporting evidence" for c in chain["document_correlations"])
    assert chain["confidence_tier"] == TIER_STRONG
    assert "corroborate" in chain["synthesis_result"].lower()
    assert report["source_coverage"]["GitHub"] and report["source_coverage"]["Defense"]


# ── 2. Link Website runtime to GitHub by project + skill ──────────────────────


def test_synthesis_links_website_runtime_to_github_by_project_and_skill(
    mem_store: dict, pipeline_db: dict
) -> None:
    gh_id = _strong_github(mem_store, "Python")
    session_id = _seed_workflow_analysis(
        mem_store,
        target_website="https://demo.example.com",
        supported_skills=["Python"],
    )
    pid = _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={
            "github_proof": {"github_proof_id": gh_id},
            "website_proofs": [{"proof_session_id": session_id}],
        },
    )

    report = build_skill_proof_synthesis(mem_store, pipeline_db, USER_ID, "python")
    chain = next(c for c in report["proof_chains"] if c["project_id"] == pid)
    assert chain["github_evidence"], "code implementation present in the chain"
    assert chain["website_evidence"], "runtime behaviour present in the same chain"
    assert chain["confidence_tier"] == TIER_STRONG
    assert report["source_coverage"]["Website"] and report["source_coverage"]["GitHub"]


# ── 3. Unrelated document stays unlinked ──────────────────────────────────────


def test_synthesis_keeps_unrelated_document_unlinked(mem_store: dict, pipeline_db: dict) -> None:
    gh_id = _strong_github(mem_store, "Python")
    _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={"github_proof": {"github_proof_id": gh_id}},
    )
    # A document about the SAME skill but a totally different, unattached project.
    _seed_document_evidence(
        mem_store,
        analysis_json={"title": "Unrelated Weather Dashboard Writeup"},
        evidence_objects=[
            {"skill_name": "Python", "confidence": "high", "snippet": "unrelated passage", "page_number": 7}
        ],
    )

    report = build_skill_proof_synthesis(mem_store, pipeline_db, USER_ID, "python")
    chain = report["proof_chains"][0]
    chain_doc_titles = [c["document_title"] for c in chain["document_correlations"]]
    assert "Unrelated Weather Dashboard Writeup" not in chain_doc_titles
    # It appears under unlinked supporting evidence instead.
    unlinked_titles = [i["title"] for i in report["unlinked_supporting_evidence"]["items"]]
    assert any("Unrelated Weather Dashboard" in t for t in unlinked_titles)


# ── 4. Prefers canonical precise GitHub code evidence ─────────────────────────


def test_synthesis_prefers_canonical_github_code_evidence(mem_store: dict, pipeline_db: dict) -> None:
    evidence_id = str(uuid4())
    mem_store.setdefault("skill_evidence", {})[evidence_id] = {
        "id": evidence_id,
        "user_id": USER_ID,
        "skill_name": "API Development",
        "evidence_type": "github repository",
        "repository_url": "https://github.com/octocat/Hello-World",
        "file_path": "app/api/routes.py",
        "line_start": 10,
        "line_end": 20,
        "evidence_description": "API route handler with request validation.",
        "proof_visibility": "public",
        "metadata": {
            "selection_reason": "API endpoint decorator",
            "github_highlight_url": "https://github.com/octocat/Hello-World/blob/main/app/api/routes.py#L10-L20",
            "confidence_label": "high",
        },
        "created_at": "2026-01-01T00:00:00Z",
    }
    _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo_full_name="octocat/Hello-World",
    )

    report = build_skill_proof_synthesis(mem_store, pipeline_db, USER_ID, "api-development")
    chain = report["proof_chains"][0]
    code = [g for g in chain["github_evidence"] if g.get("display_mode") == "code_line"]
    assert code, "canonical precise code evidence is the code implementation"
    assert code[0]["file_path"] == "app/api/routes.py"
    # A synthesis statement cites the canonical selection reason.
    gh_statements = [s for s in chain["synthesis_statements"] if s["source"] == "GitHub Proof"]
    assert any("API endpoint decorator" in s["text"] for s in gh_statements)


# ── 5. Never fabricates evidence (statements cite real ids) ───────────────────


def test_synthesis_does_not_fabricate_evidence(mem_store: dict, pipeline_db: dict) -> None:
    gh_id = _strong_github(mem_store, "Python")
    doc_id = _seed_document_evidence(
        mem_store,
        analysis_json={"title": "Boston Report"},
        evidence_objects=[
            {"skill_name": "Python", "confidence": "high", "snippet": "prediction API", "page_number": 2}
        ],
    )
    pid = _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={
            "github_proof": {"github_proof_id": gh_id},
            "documents": [{"document_evidence_id": doc_id}],
        },
    )
    _seed_defense_session(mem_store, project_id=pid, skills_explained=["Python"])

    report = build_skill_proof_synthesis(mem_store, pipeline_db, USER_ID, "python")
    for chain in report["proof_chains"]:
        allowed = _all_evidence_ids(chain)
        for stmt in chain["synthesis_statements"]:
            assert stmt["evidence_ids"], "every statement must cite at least one evidence id"
            for eid in stmt["evidence_ids"]:
                assert eid in allowed, f"statement cited a non-existent evidence id {eid!r}"


# ── 6. Caps unlinked supporting evidence ──────────────────────────────────────


def test_synthesis_caps_unlinked_supporting_evidence(mem_store: dict, pipeline_db: dict) -> None:
    # Many unattached website proofs for the same skill, none tied to a project.
    for n in range(9):
        _seed_workflow_analysis(
            mem_store,
            target_website=f"https://demo-{n}.example.com",
            supported_skills=["Python"],
        )

    report = build_skill_proof_synthesis(mem_store, pipeline_db, USER_ID, "python")
    unlinked = report["unlinked_supporting_evidence"]
    assert len(unlinked["items"]) == 6, "unlinked supporting evidence is capped at 6"
    assert unlinked["more_count"] == 3
    assert unlinked["count"] == len(unlinked["items"]) + unlinked["more_count"]


# ── 7. No raw/private leakage through synthesis ───────────────────────────────

_FORBIDDEN = (
    "should-never-leak",
    "secret_token",
    "raw_dump",
    "analysis_snapshot",
    "/storage/v1/object",
    "supabase.co/storage",
)


def test_synthesis_private_safety(mem_store: dict, pipeline_db: dict) -> None:
    _seed_github_proof(
        mem_store,
        detected_skills=["Python"],
        analysis_snapshot={"raw_dump": "should-never-leak", "skill_code_evidence": []},
    )
    _seed_document_evidence(
        mem_store, evidence_objects=[{"skill_name": "Python", "confidence": "high", "snippet": "ok"}]
    )
    _seed_workflow_analysis(mem_store, supported_skills=["Python"])

    report = build_skill_proof_synthesis(mem_store, pipeline_db, USER_ID, "python")
    serialized = str(
        {
            "synthesis_summary": report["synthesis_summary"],
            "proof_chains": report["proof_chains"],
            "unlinked": report["unlinked_supporting_evidence"],
        }
    ).lower()
    for needle in _FORBIDDEN:
        assert needle.lower() not in serialized, f"synthesis leaked {needle!r}"
    assert "/100" not in serialized


# ── Weak-only evidence reads as "Needs review" (no over-claiming) ─────────────


def test_synthesis_weak_only_github_is_needs_review(mem_store: dict, pipeline_db: dict) -> None:
    # Import-only GitHub evidence downgrades to repo-level → not a strong source.
    _seed_github_proof(
        mem_store,
        detected_skills=["Python"],
        analysis_snapshot={
            "skill_code_evidence": [
                {
                    "skill": "Python",
                    "file_path": "api.py",
                    "line_start": 6,
                    "line_end": 9,
                    "code_snippet": "import sys\nimport io",
                }
            ]
        },
    )
    pid = _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={"github_proof": {"github_proof_id": list(mem_store["github_proof_submissions"])[0]}},
    )

    report = build_skill_proof_synthesis(mem_store, pipeline_db, USER_ID, "python")
    chain = next(c for c in report["proof_chains"] if c["project_id"] == pid)
    assert chain["confidence_tier"] == TIER_NEEDS_REVIEW
