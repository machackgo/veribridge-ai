"""Tests for the Student Proof Vault (proof-native, student-wide aggregator).

Proves the passport/report are NO LONGER attached-proof-only:

* ``collect_vault_items`` reads GitHub / Document / Website / Skill-Graph proofs
  directly from their source tables — attached to a VBR project or not.
* The Private Work Passport surfaces unattached proofs under the relevant skill,
  clearly labelled "not attached to a VBR project".
* Unattached proofs never leak into the conservative Public Work Passport.
* No raw/private fields (raw snapshots, storage paths, signed URLs, secrets)
  ever ride through a vault item.

All storage is in-memory (dict mode). No network / LLM calls.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.services.skill_normalization import canonical_skill, skill_category, skill_slug
from app.services.student_proof_vault_service import (
    collect_skill_report,
    collect_skill_summaries,
    collect_vault_items,
    group_vault_by_skill,
)
from app.services.vbr_work_passport_service import build_private_passport

from tests.test_vbr_project_defense import (
    OTHER_USER_ID,
    USER_ID,
    _seed_document_evidence,
    _seed_github_proof,
    _seed_skill_pipeline,
    _seed_workflow_analysis,
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


def _by_type(items: list[dict], proof_type: str) -> list[dict]:
    return [i for i in items if i["proof_type"] == proof_type]


# ── Vault collection: unattached proofs are still collected ───────────────────


def test_vault_collects_unattached_github_proof(mem_store: dict, pipeline_db: dict) -> None:
    _seed_github_proof(mem_store)  # never attached to any VBR project

    items = collect_vault_items(mem_store, pipeline_db, USER_ID)
    gh = _by_type(items, "GitHub Proof")
    assert gh, "unattached GitHub Proof must be collected"
    assert {i["skill_name"] for i in gh} >= {"Python", "React"}
    assert all(i["is_attached_to_project"] is False for i in gh)
    assert all(i["attached_project_ids"] == [] for i in gh)


def test_vault_collects_unattached_document_proof(mem_store: dict, pipeline_db: dict) -> None:
    _seed_document_evidence(
        mem_store,
        evidence_objects=[
            {"skill_name": "Python", "confidence": "high", "snippet": "matched passage", "page_number": 3},
        ],
    )

    items = collect_vault_items(mem_store, pipeline_db, USER_ID)
    docs = _by_type(items, "Document Proof")
    assert docs
    py = next(i for i in docs if i["skill_name"] == "Python")
    assert py["is_attached_to_project"] is False
    assert py["safe_location"] and "Page 3" in py["safe_location"]
    assert py["public_safe"] is False  # documents are never publicly linkable


def test_vault_collects_unattached_website_proof(mem_store: dict, pipeline_db: dict) -> None:
    _seed_workflow_analysis(
        mem_store,
        target_website="https://demo.example.com",
        supported_skills=["Python", "React"],
    )

    items = collect_vault_items(mem_store, pipeline_db, USER_ID)
    web = _by_type(items, "Website Proof")
    assert {i["skill_name"] for i in web} == {"Python", "React"}
    assert all(i["is_attached_to_project"] is False for i in web)
    assert all(i["public_safe"] is True for i in web)  # safe public target URL


def test_vault_collects_skill_graph_pipeline(mem_store: dict, pipeline_db: dict) -> None:
    _seed_skill_pipeline(pipeline_db, skill_name="Python", support_status="strongly_supported")

    items = collect_vault_items(mem_store, pipeline_db, USER_ID)
    graph = _by_type(items, "Skill Graph")
    assert graph and graph[0]["skill_name"] == "Python"
    assert graph[0]["public_safe"] is False


def test_vault_is_owner_scoped(mem_store: dict, pipeline_db: dict) -> None:
    _seed_github_proof(mem_store, user_id=OTHER_USER_ID)
    assert collect_vault_items(mem_store, pipeline_db, USER_ID) == []


def test_vault_collects_at_least_five_proof_types(mem_store: dict, pipeline_db: dict) -> None:
    _seed_github_proof(mem_store)
    _seed_document_evidence(
        mem_store, evidence_objects=[{"skill_name": "Python", "confidence": "high"}]
    )
    _seed_workflow_analysis(mem_store, supported_skills=["React"])
    _seed_skill_pipeline(pipeline_db, skill_name="Django")

    items = collect_vault_items(mem_store, pipeline_db, USER_ID)
    types = {i["proof_type"] for i in items}
    assert {"GitHub Proof", "Document Proof", "Website Proof", "Skill Graph"} <= types


# ── Grouping ──────────────────────────────────────────────────────────────────


def test_group_vault_by_skill_labels_unattached(mem_store: dict, pipeline_db: dict) -> None:
    _seed_workflow_analysis(mem_store, supported_skills=["Python"])

    groups = group_vault_by_skill(collect_vault_items(mem_store, pipeline_db, USER_ID))
    py = next(g for g in groups if g["skill"] == "Python")
    assert py["has_unattached"] is True
    assert py["unattached_count"] >= 1
    assert "Website Proof" in py["proof_types"]


# ── Skill normalization / categorization helper ───────────────────────────────


def test_skill_normalization_collapses_aliases() -> None:
    assert canonical_skill("ml") == "Machine Learning"
    assert canonical_skill("machine learning") == "Machine Learning"
    assert canonical_skill("ML") == "Machine Learning"
    assert canonical_skill("gen ai") == "Generative AI"
    assert canonical_skill("fastapi") == "FastAPI"
    # Unknown skills are preserved (nothing lost).
    assert canonical_skill("Quantum Wizardry") == "Quantum Wizardry"


def test_skill_categorization_high_and_low_level() -> None:
    assert skill_category("Machine Learning") == "AI / Machine Learning"
    assert skill_category("API Development") == "Backend / APIs"
    assert skill_category("MLOps") == "MLOps / Deployment"
    assert skill_category("Python") == "Programming Language"
    assert skill_category("JavaScript") == "Programming Language"
    assert skill_category("React") == "Frontend"
    assert skill_category("PostgreSQL") == "Database"


# ── Layer 1: compact skill summaries (main Passport) ──────────────────────────


def test_collect_skill_summaries_are_compact_not_a_raw_dump(mem_store: dict, pipeline_db: dict) -> None:
    _seed_github_proof(mem_store)  # Python + React
    _seed_workflow_analysis(mem_store, supported_skills=["Python"])
    _seed_document_evidence(
        mem_store, evidence_objects=[{"skill_name": "Python", "confidence": "high", "page_number": 2}]
    )

    summaries = collect_skill_summaries(mem_store, pipeline_db, USER_ID)
    py = next(s for s in summaries if s["skill"] == "Python")
    # Compact: it carries counts + a capped preview list, NOT every proof card.
    assert "proofs" not in py
    assert py["category"] == "Programming Language"
    assert py["project_count"] == 0
    assert py["proof_count"] >= 3
    assert py["proof_source_counts"]["GitHub Proof"] >= 1
    assert py["proof_source_counts"]["Website Proof"] >= 1
    assert len(py["previews"]) <= 3
    # The "+N more" overflow count keeps the main page from rendering all cards.
    assert py["more_count"] == py["proof_count"] - len(py["previews"])


def test_collect_skill_summaries_normalize_and_categorize_high_level_skills(
    mem_store: dict, pipeline_db: dict
) -> None:
    # Same skill named two different ways must collapse into one canonical card.
    _seed_workflow_analysis(mem_store, supported_skills=["ml"])
    _seed_document_evidence(
        mem_store, evidence_objects=[{"skill_name": "Machine Learning", "confidence": "high"}]
    )

    summaries = collect_skill_summaries(mem_store, pipeline_db, USER_ID)
    ml = [s for s in summaries if s["skill"] == "Machine Learning"]
    assert len(ml) == 1, "alias 'ml' and 'Machine Learning' must collapse into one card"
    assert ml[0]["category"] == "AI / Machine Learning"
    assert "ml" in ml[0]["source_labels"]  # original labels preserved for traceability


def test_private_passport_uses_compact_skill_summaries(mem_store: dict, pipeline_db: dict) -> None:
    _seed_workflow_analysis(
        mem_store, target_website="https://demo.example.com", supported_skills=["Python"]
    )

    passport = build_private_passport(mem_store, pipeline_db, USER_ID)
    # No VBR project exists, so the old attached-only passport would be empty.
    assert passport["project_count"] == 0
    assert passport["vault_proof_count"] >= 1
    assert passport["vault_unattached_count"] >= 1
    # The passport returns compact summaries, never a full proof dump.
    assert "vault_skills" not in passport
    py = next(s for s in passport["vault_skill_summaries"] if s["skill"] == "Python")
    assert py["has_unattached"] is True
    assert py["unattached_count"] >= 1
    assert any("not attached to any vbr project" in lim.lower() for lim in passport["limitations"])


# ── Layer 2: full Skill Report for one selected skill ─────────────────────────


def test_collect_skill_report_returns_actual_github_evidence(mem_store: dict, pipeline_db: dict) -> None:
    _seed_github_proof(
        mem_store,
        detected_skills=["Machine Learning"],
        analysis_snapshot={
            "raw_dump": "should-never-leak",
            "skill_code_evidence": [
                {
                    "skill": "Machine Learning",
                    "file_path": "src/model/train.py",
                    "line_start": 10,
                    "line_end": 24,
                    "function_name": "train_model",
                    "code_snippet": "def train_model(): ...",
                    "commit_sha": "abc1234",
                }
            ],
        },
    )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "Machine Learning")
    assert report["skill"] == "Machine Learning"
    assert report["github"], "GitHub evidence must be present"
    gh = report["github"][0]
    assert gh["file_path"] == "src/model/train.py"
    assert gh["line_start"] == 10
    assert gh["function_name"] == "train_model"
    # Public repo → a direct GitHub line link + safe snippet.
    assert gh["public_url"] and "src/model/train.py" in gh["public_url"]
    assert gh["safe_snippet"]


def test_collect_skill_report_hydrates_website_detail_only_here(
    mem_store: dict, pipeline_db: dict, monkeypatch
) -> None:
    """Website detail is hydrated ONLY inside collect_skill_report — never during
    compact summary collection (the performance contract)."""
    import app.services.student_proof_vault_service as svc

    calls: list[str] = []
    real = svc.get_website_proof_detail

    def _spy(db, user_id, session_id):
        calls.append(session_id)
        return {"workflow_summary": "User logged in and ran a prediction.", "workflow_steps": ["Log in", "Predict"],
                "dom_summary": "Dashboard rendered.", "ocr_summary": "Prediction: 0.92",
                "visual_summary": "A working ML dashboard.", "live_check": {"is_reachable": True}}

    monkeypatch.setattr(svc, "get_website_proof_detail", _spy)
    _seed_workflow_analysis(
        mem_store, target_website="https://demo.example.com", supported_skills=["Python"]
    )

    # Compact summaries must NOT hydrate website detail.
    collect_skill_summaries(mem_store, pipeline_db, USER_ID)
    assert calls == [], "compact summaries must not hydrate website detail"

    # The Skill Report hydrates the rich website summaries.
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "Python")
    assert len(calls) == 1
    web = report["website"][0]
    assert web["workflow_summary"] == "User logged in and ran a prediction."
    assert web["workflow_steps"] == ["Log in", "Predict"]
    assert web["ocr_summary"] == "Prediction: 0.92"
    assert web["visual_summary"] == "A working ML dashboard."
    assert web["live_check"] == {"is_reachable": True}
    svc.get_website_proof_detail = real


def test_collect_skill_report_returns_document_citation(mem_store: dict, pipeline_db: dict) -> None:
    _seed_document_evidence(
        mem_store,
        evidence_objects=[
            {
                "skill_name": "Python",
                "confidence": "high",
                "snippet": "Implemented the training loop in Python.",
                "page_number": 4,
                "section_label": "Methodology",
                "reason": "Describes the Python implementation.",
            }
        ],
    )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "Python")
    assert report["documents"]
    doc = report["documents"][0]
    assert doc["page_number"] == 4
    assert doc["citation"] == "Methodology"
    assert doc["safe_snippet"] == "Implemented the training loop in Python."


def test_collect_skill_report_lists_project_usage_and_gaps(mem_store: dict, pipeline_db: dict) -> None:
    _seed_workflow_analysis(mem_store, supported_skills=["Python"])
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "Python")
    # An unattached proof shows under the standalone-vault project-usage bucket.
    assert any(not p["attached"] for p in report["projects"])
    assert report["gaps"], "honest gaps/limitations must be surfaced"
    assert any("not attached" in g.lower() for g in report["gaps"])


# ── Skill Report endpoint ─────────────────────────────────────────────────────


def test_skill_report_endpoint_returns_actual_evidence(
    client: TestClient, mem_store: dict, pipeline_db: dict
) -> None:
    _seed_github_proof(mem_store)  # Python + React, public repo
    res = client.get("/api/v1/student/vbr/passport/skill-report", params={"skill": "python"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["skill"] == "Python"
    assert body["category"] == "Programming Language"
    assert body["github"], "skill report must surface actual GitHub evidence, not just headings"
    assert "overview" in body and body["overview"]["proof_count"] >= 1


def test_skill_report_endpoint_resolves_url_slug(
    client: TestClient, mem_store: dict, pipeline_db: dict
) -> None:
    # The route key is a URL slug ("machine-learning"); it must resolve to the
    # alias-collapsed canonical skill even though the proof named it "ml".
    _seed_workflow_analysis(mem_store, supported_skills=["ml"])
    res = client.get("/api/v1/student/vbr/passport/skill-report", params={"skill": "machine-learning"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["skill"] == "Machine Learning"
    assert body["skill_slug"] == "machine-learning"
    assert body["website"], "the slug must resolve to the alias-collapsed skill's evidence"
    # Documents are connected as corroboration, never dumped as a standalone field
    # bigger than the cap.
    assert "standalone_evidence" in body


# ── Slug resolution ───────────────────────────────────────────────────────────


def test_skill_slug_round_trips_aliases() -> None:
    assert skill_slug("Machine Learning") == "machine-learning"
    assert skill_slug("ml") == "machine-learning"
    assert skill_slug("API Development") == "api-development"
    assert skill_slug("api") == "api-development"


def test_skill_report_resolves_slug_to_canonical(mem_store: dict, pipeline_db: dict) -> None:
    # A Website Proof maps the alias "ml"; the report is requested by URL slug.
    _seed_workflow_analysis(mem_store, supported_skills=["ml"])

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    assert report["skill"] == "Machine Learning"
    assert report["skill_slug"] == "machine-learning"
    # The requested skill is echoed back, and the website proof is matched.
    assert report["requested_skill"] == "machine-learning"
    assert report["website"], "the slug must resolve to the alias-collapsed skill"


# ── Connected proof chains + document correlation ─────────────────────────────


def _seed_project(
    mem_store: dict,
    *,
    title: str,
    user_id: str = USER_ID,
    repo_full_name: str | None = None,
    attached_proofs: dict | None = None,
) -> str:
    pid = str(uuid4())
    mem_store.setdefault("vbr_projects", {})[pid] = {
        "id": pid,
        "user_id": user_id,
        "title": title,
        "repo_full_name": repo_full_name,
        "repo_url": f"https://github.com/{repo_full_name}" if repo_full_name else None,
        "metadata": {"attached_proofs": attached_proofs or {}},
        "created_at": "2026-01-01T00:00:00Z",
    }
    return pid


def test_attached_document_maps_into_project_proof_chain(mem_store: dict, pipeline_db: dict) -> None:
    doc_id = _seed_document_evidence(
        mem_store,
        evidence_objects=[
            {"skill_name": "Machine Learning", "confidence": "high", "snippet": "ML pipeline", "page_number": 2}
        ],
    )
    # The project has GitHub code for ML and the document attached to it.
    gh_id = _seed_github_proof(
        mem_store,
        detected_skills=["Machine Learning"],
        analysis_snapshot={
            "skill_code_evidence": [
                {"skill": "Machine Learning", "file_path": "api.py", "line_start": 252, "line_end": 255}
            ]
        },
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

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    chain = next(p for p in report["projects"] if p["project_id"] == pid)
    # The document is connected as corroboration inside the chain — never dumped.
    assert chain["document_correlations"], "attached doc must show as corroboration in the chain"
    corr = chain["document_correlations"][0]
    assert corr["corroborates"] == "GitHub implementation"
    assert corr["page_number"] == 2
    assert "GitHub Proof" in chain["sources"] and "Document Proof" in chain["sources"]


def test_document_matched_by_project_title_maps_into_chain(mem_store: dict, pipeline_db: dict) -> None:
    # A GitHub-evidenced project, plus an UNATTACHED document whose title names it.
    _seed_github_proof(
        mem_store,
        detected_skills=["Machine Learning"],
        analysis_snapshot={
            "skill_code_evidence": [
                {"skill": "Machine Learning", "file_path": "api.py", "line_start": 252, "line_end": 255}
            ]
        },
    )
    pid = _seed_project(
        mem_store, title="Boston Smart Rerouting", repo_full_name="octocat/Hello-World",
        attached_proofs={"github_proof": {"github_proof_id": list(mem_store["github_proof_submissions"])[0]}},
    )
    _seed_document_evidence(
        mem_store,
        analysis_json={"title": "Boston Smart Rerouting — Final Report"},
        evidence_objects=[
            {"skill_name": "Machine Learning", "confidence": "high", "snippet": "model endpoint", "page_number": 5}
        ],
    )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    chain = next(p for p in report["projects"] if p["project_id"] == pid)
    titles = [c["document_title"] for c in chain["document_correlations"]]
    assert any("Boston Smart Rerouting" in t for t in titles), "doc must correlate by project title"


def test_duplicate_document_snippets_are_deduped(mem_store: dict, pipeline_db: dict) -> None:
    _seed_document_evidence(
        mem_store,
        evidence_objects=[
            {"skill_name": "Python", "confidence": "high", "snippet": "same passage", "page_number": 3},
            {"skill_name": "python", "confidence": "high", "snippet": "same passage", "page_number": 3},
        ],
    )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "python")
    docs = report["standalone_evidence"]["documents"]
    assert len(docs) == 1, "identical document snippets must be de-duplicated"


def test_standalone_documents_are_capped_with_more_count(mem_store: dict, pipeline_db: dict) -> None:
    # 8 separate, unattached documents each citing Python (one item per doc).
    for n in range(8):
        _seed_document_evidence(
            mem_store,
            analysis_json={"title": f"Report {n}"},
            evidence_objects=[
                {"skill_name": "Python", "confidence": "high", "snippet": f"passage {n}", "page_number": n}
            ],
        )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "python")
    docs = report["standalone_evidence"]["documents"]
    assert len(docs) == 5, "standalone document corroborations are capped at 5"
    assert report["standalone_evidence"]["document_more_count"] == 3


def test_project_document_correlations_capped_at_three(mem_store: dict, pipeline_db: dict) -> None:
    doc_ids = [
        _seed_document_evidence(
            mem_store,
            analysis_json={"title": f"Report {n}"},
            evidence_objects=[
                {"skill_name": "Python", "confidence": "high", "snippet": f"passage {n}", "page_number": n}
            ],
        )
        for n in range(6)
    ]
    pid = _seed_project(
        mem_store,
        title="Tracker",
        attached_proofs={"documents": [{"document_evidence_id": d} for d in doc_ids]},
    )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "python")
    chain = next(p for p in report["projects"] if p["project_id"] == pid)
    assert len(chain["document_correlations"]) == 3
    assert chain["document_more_count"] == 3


def test_skill_report_never_dumps_documents_as_primary_cards(mem_store: dict, pipeline_db: dict) -> None:
    """Documents must only appear as connected correlations, never as a flat dump
    of one card per snippet bigger than the cap."""
    for n in range(10):
        _seed_document_evidence(
            mem_store,
            analysis_json={"title": f"Report {n}"},
            evidence_objects=[
                {"skill_name": "Python", "confidence": "high", "snippet": f"passage {n}", "page_number": n}
            ],
        )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "python")
    # No project chain or standalone bucket ever shows more than its cap.
    assert len(report["standalone_evidence"]["documents"]) <= 5
    for p in report["projects"]:
        cap = 3 if p["attached"] else 5
        assert len(p["document_correlations"]) <= cap


# ── GitHub weak-line downgrade (canonical filter, shared with VBR report) ─────


def _github_items(report: dict) -> list[dict]:
    """All GitHub evidence items across chains + standalone + flat list."""
    out = list(report.get("github") or [])
    for p in report.get("projects") or []:
        out += p.get("github_evidence") or []
    out += (report.get("standalone_evidence") or {}).get("github") or []
    return out


def test_skill_report_downgrades_import_only_github_evidence(mem_store: dict, pipeline_db: dict) -> None:
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
                    "code_snippet": "import sys\nimport io\nimport time",
                }
            ]
        },
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "python")
    gh = _github_items(report)
    assert gh, "the GitHub repo still surfaces for Python (as repo-level support)"
    # No item exposes the import lines as a strong, line-level code card.
    for item in gh:
        assert item.get("line_start") in (None, 0), "import-only lines must not be shown as line proof"
        assert not item.get("safe_snippet"), "the import snippet must never be rendered"
    assert "import sys" not in str(report)


def test_skill_report_downgrades_notebook_markdown_github_evidence(mem_store: dict, pipeline_db: dict) -> None:
    _seed_github_proof(
        mem_store,
        detected_skills=["API Development"],
        analysis_snapshot={
            "skill_code_evidence": [
                {
                    "skill": "API Development",
                    "file_path": "notebooks/overview.ipynb",
                    "line_start": 1,
                    "code_snippet": "## API Design\n- describes the endpoints\nhttps://example.com",
                }
            ]
        },
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "api-development")
    gh = _github_items(report)
    for item in gh:
        assert not item.get("safe_snippet")
        assert item.get("line_start") in (None, 0)
    assert "API Design" not in str(report)


def test_skill_report_prefers_strong_github_function_over_weak_import(mem_store: dict, pipeline_db: dict) -> None:
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
                },
                {
                    "skill": "Python",
                    "file_path": "src/train.py",
                    "line_start": 40,
                    "line_end": 44,
                    "function_name": "train_model",
                    "code_snippet": "def train_model(df):\n    return clf.fit(df)",
                },
            ]
        },
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "python")
    gh = [i for i in _github_items(report) if i.get("file_path")]
    assert gh, "the strong function evidence must surface"
    strong = next(i for i in gh if i.get("function_name") == "train_model")
    assert strong["file_path"] == "src/train.py"
    assert strong["line_start"] == 40
    assert strong["safe_snippet"] and "train_model" in strong["safe_snippet"]
    # The import line is never surfaced as a code snippet anywhere.
    assert "import sys" not in str(report)


def test_skill_report_uses_repo_level_fallback_for_weak_only_skill(mem_store: dict, pipeline_db: dict) -> None:
    _seed_github_proof(
        mem_store,
        detected_skills=["Python"],
        analysis_snapshot={
            "skill_code_evidence": [
                {
                    "skill": "Python",
                    "file_path": "src/predict.py",
                    "line_start": 1,
                    "code_snippet": "sys.path.insert(0, str(Path(__file__).resolve().parents[2]))",
                }
            ]
        },
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "python")
    gh = _github_items(report)
    assert gh, "a repo-level GitHub item must remain for Python"
    item = gh[0]
    assert not item.get("safe_snippet")
    assert item.get("line_start") in (None, 0)
    # The honest repo-level limitation explains the weak-only downgrade.
    assert "repository-level" in (item.get("limitation") or "").lower()


def test_documents_remain_corroboration_not_primary_dump(mem_store: dict, pipeline_db: dict) -> None:
    # A project with STRONG GitHub evidence + several attached documents.
    gh_id = _seed_github_proof(
        mem_store,
        detected_skills=["Machine Learning"],
        analysis_snapshot={
            "skill_code_evidence": [
                {
                    "skill": "Machine Learning",
                    "file_path": "api.py",
                    "line_start": 252,
                    "line_end": 255,
                    "function_name": "predict",
                    "code_snippet": "def predict(req):\n    return model.predict(req)",
                }
            ]
        },
    )
    doc_ids = [
        _seed_document_evidence(
            mem_store,
            analysis_json={"title": f"Report {n}"},
            evidence_objects=[
                {"skill_name": "Machine Learning", "confidence": "high", "snippet": f"passage {n}", "page_number": n}
            ],
        )
        for n in range(5)
    ]
    pid = _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={
            "github_proof": {"github_proof_id": gh_id},
            "documents": [{"document_evidence_id": d} for d in doc_ids],
        },
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    chain = next(p for p in report["projects"] if pid in (p.get("collapsed_project_ids") or [p.get("project_id")]))
    # Documents are capped corroboration, every one marked supporting (not primary).
    assert len(chain["document_correlations"]) <= 3
    assert chain["document_more_count"] >= 1
    for corr in chain["document_correlations"]:
        assert corr["support_label"] == "Supporting evidence"
        assert corr["correlation_confidence"] == "direct attachment"
        assert "does not independently prove" in corr["limitation"]


def test_skill_report_collapses_duplicate_project_chains_with_same_proof_package(
    mem_store: dict, pipeline_db: dict
) -> None:
    # ONE GitHub proof + ONE document, attached to THREE VBR project rows that all
    # share the same title and the same proof package (repeated Boston attempts).
    gh_id = _seed_github_proof(
        mem_store,
        detected_skills=["Machine Learning"],
        analysis_snapshot={
            "skill_code_evidence": [
                {
                    "skill": "Machine Learning",
                    "file_path": "api.py",
                    "line_start": 252,
                    "line_end": 255,
                    "function_name": "predict",
                    "code_snippet": "def predict(req):\n    return model.predict(req)",
                }
            ]
        },
    )
    doc_id = _seed_document_evidence(
        mem_store,
        analysis_json={"title": "Boston Report"},
        evidence_objects=[
            {"skill_name": "Machine Learning", "confidence": "high", "snippet": "ML pipeline", "page_number": 2}
        ],
    )
    attached = {
        "github_proof": {"github_proof_id": gh_id},
        "documents": [{"document_evidence_id": doc_id}],
    }
    pids = [
        _seed_project(
            mem_store,
            title="Boston Smart Accident Risk Rerouting",
            repo_full_name="octocat/Hello-World",
            attached_proofs=attached,
        )
        for _ in range(3)
    ]
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    attached_chains = [p for p in report["projects"] if p.get("attached")]
    # The three identical project rows collapse into ONE representative chain.
    assert len(attached_chains) == 1
    chain = attached_chains[0]
    assert chain["collapsed_project_count"] == 3
    assert set(chain["collapsed_project_ids"]) == set(pids)
    assert any("collapsed" in lim.lower() for lim in chain["limitations"])
    # Document corroboration is shown once, not repeated per duplicate row.
    assert len(chain["document_correlations"]) == 1


# ── GitHub explicit display-mode fields (code_line vs repo_level) ─────────────


def test_github_precise_evidence_exposes_display_mode_code_line(mem_store: dict, pipeline_db: dict) -> None:
    _seed_github_proof(
        mem_store,
        detected_skills=["Machine Learning"],
        analysis_snapshot={
            "skill_code_evidence": [
                {
                    "skill": "Machine Learning",
                    "file_path": "api.py",
                    "line_start": 252,
                    "line_end": 255,
                    "function_name": "predict",
                    "code_snippet": "def predict(req):\n    return model.predict(req)",
                    "commit_sha": "abc1234",
                }
            ]
        },
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    precise = [i for i in _github_items(report) if i.get("display_mode") == "code_line"]
    assert precise, "strong evidence must expose display_mode=code_line"
    item = precise[0]
    assert item["has_precise_line_evidence"] is True
    assert item["github_line_url"] and "api.py" in item["github_line_url"]
    assert item["file_path"] == "api.py"
    assert item["line_start"] == 252
    assert item["function_name"] == "predict"
    assert item["safe_snippet"] and "predict" in item["safe_snippet"]
    assert item["evidence_strength"] in ("strong", "medium")


def test_github_weak_evidence_exposes_repo_level_only(mem_store: dict, pipeline_db: dict) -> None:
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
                    "code_snippet": "import sys\nimport io\nimport time",
                }
            ]
        },
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "python")
    gh = _github_items(report)
    assert gh, "the GitHub repo still surfaces for Python (as repo-level support)"
    for item in gh:
        assert item["display_mode"] == "repo_level"
        assert item["has_precise_line_evidence"] is False
        # The repo URL is exposed for the honest "View repository" link.
        assert item["repo_url"] and "github.com" in item["repo_url"]
        # No fabricated precise evidence: no weak snippet, line range, or line URL.
        assert not item.get("safe_snippet")
        assert item.get("line_start") in (None, 0)
        assert item.get("github_line_url") is None
        assert item["evidence_strength"] in ("weak", "repo_level")


# ── Display-level grouping of same-title project attempts ─────────────────────


def _seed_ml_strong_github(mem_store: dict) -> str:
    return _seed_github_proof(
        mem_store,
        detected_skills=["Machine Learning"],
        analysis_snapshot={
            "skill_code_evidence": [
                {
                    "skill": "Machine Learning",
                    "file_path": "api.py",
                    "line_start": 252,
                    "line_end": 255,
                    "function_name": "predict",
                    "code_snippet": "def predict(req):\n    return model.predict(req)",
                }
            ]
        },
    )


def test_skill_report_groups_same_title_project_attempts(mem_store: dict, pipeline_db: dict) -> None:
    # Several VBR attempts for the SAME project (same title) but with DIFFERENT
    # proof combinations (GitHub-only, GitHub+Document, Document-only). Exact
    # proof-package collapse keeps them separate; title grouping must merge them
    # into ONE display chain.
    gh_id = _seed_ml_strong_github(mem_store)
    doc_id = _seed_document_evidence(
        mem_store,
        analysis_json={"title": "Boston Report"},
        evidence_objects=[
            {"skill_name": "Machine Learning", "confidence": "high", "snippet": "ML pipeline", "page_number": 2}
        ],
    )
    title = "Boston Smart Accident Risk Rerouting"
    _seed_project(
        mem_store, title=title, repo_full_name="octocat/Hello-World",
        attached_proofs={"github_proof": {"github_proof_id": gh_id}},
    )
    _seed_project(
        mem_store, title=title, repo_full_name="octocat/Hello-World",
        attached_proofs={
            "github_proof": {"github_proof_id": gh_id},
            "documents": [{"document_evidence_id": doc_id}],
        },
    )
    _seed_project(
        mem_store, title=title,
        attached_proofs={"documents": [{"document_evidence_id": doc_id}]},
    )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    attached_chains = [p for p in report["projects"] if p.get("attached")]
    assert len(attached_chains) == 1, "same-title attempts must group into ONE display chain"
    chain = attached_chains[0]
    assert chain["grouped_attempt_count"] == 3
    assert len(chain["grouped_project_ids"]) == 3
    assert any("related project attempts grouped" in lim.lower() for lim in chain["limitations"])
    # Merged + deduped: ONE precise GitHub code item, ONE document corroboration.
    assert sum(1 for e in chain["github_evidence"] if e.get("display_mode") == "code_line") == 1
    assert len(chain["document_correlations"]) == 1
    assert "GitHub Proof" in chain["sources"] and "Document Proof" in chain["sources"]


def test_document_correlations_deduped_after_grouping(mem_store: dict, pipeline_db: dict) -> None:
    gh_id = _seed_ml_strong_github(mem_store)

    def _doc(doc_title: str, snippet: str, page: int) -> str:
        return _seed_document_evidence(
            mem_store,
            analysis_json={"title": doc_title},
            evidence_objects=[
                {"skill_name": "Machine Learning", "confidence": "high", "snippet": snippet, "page_number": page}
            ],
        )

    # Two separate doc rows carry the SAME citation (the "Shared Memo"); the rest
    # are distinct. Across two grouped attempts the duplicate must appear once.
    shared_1 = _doc("Shared Memo", "identical ML passage", 2)
    distinct_b = _doc("Report B", "passage B", 3)
    shared_2 = _doc("Shared Memo", "identical ML passage", 2)
    distinct_c = _doc("Report C", "passage C", 4)
    distinct_d = _doc("Report D", "passage D", 5)

    title = "Boston Smart Rerouting"
    _seed_project(
        mem_store, title=title, repo_full_name="octocat/Hello-World",
        attached_proofs={
            "github_proof": {"github_proof_id": gh_id},
            "documents": [{"document_evidence_id": shared_1}, {"document_evidence_id": distinct_b}],
        },
    )
    _seed_project(
        mem_store, title=title, repo_full_name="octocat/Hello-World",
        attached_proofs={
            "github_proof": {"github_proof_id": gh_id},
            "documents": [
                {"document_evidence_id": shared_2},
                {"document_evidence_id": distinct_c},
                {"document_evidence_id": distinct_d},
            ],
        },
    )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    attached_chains = [p for p in report["projects"] if p.get("attached")]
    assert len(attached_chains) == 1
    chain = attached_chains[0]
    titles = [c["document_title"] for c in chain["document_correlations"]]
    # The identical "Shared Memo" passage is NOT repeated across grouped attempts.
    assert titles.count("Shared Memo") == 1
    # 4 distinct documents survive dedupe → capped at 3 with a +1 more.
    assert len(chain["document_correlations"]) == 3
    assert chain["document_more_count"] == 1


# ── No raw/private leakage ────────────────────────────────────────────────────

_FORBIDDEN = (
    "should-never-leak",  # repo_metadata.secret_token / analysis_snapshot.raw_dump
    "secret_token",
    "raw_dump",
    "analysis_snapshot",
    "/storage/v1/object",
    "supabase.co/storage",
)


def test_vault_never_leaks_raw_or_private_fields(mem_store: dict, pipeline_db: dict) -> None:
    _seed_github_proof(mem_store)  # carries repo_metadata + analysis_snapshot secrets
    _seed_document_evidence(
        mem_store, evidence_objects=[{"skill_name": "Python", "confidence": "high"}]
    )
    _seed_workflow_analysis(mem_store, supported_skills=["React"])

    serialized = str(collect_vault_items(mem_store, pipeline_db, USER_ID)).lower()
    for needle in _FORBIDDEN:
        assert needle.lower() not in serialized, f"vault leaked {needle!r}"
    # Numeric confidence scores are never surfaced as bare strings.
    assert "/100" not in serialized


def test_skill_report_never_leaks_raw_or_private_fields(mem_store: dict, pipeline_db: dict) -> None:
    _seed_github_proof(
        mem_store,
        detected_skills=["Python"],
        analysis_snapshot={"raw_dump": "should-never-leak", "skill_code_evidence": []},
    )
    _seed_document_evidence(
        mem_store, evidence_objects=[{"skill_name": "Python", "confidence": "high", "snippet": "ok"}]
    )
    _seed_workflow_analysis(mem_store, supported_skills=["Python"])

    serialized = str(collect_skill_report(mem_store, pipeline_db, USER_ID, "python")).lower()
    for needle in _FORBIDDEN:
        assert needle.lower() not in serialized, f"skill report leaked {needle!r}"
    assert "/100" not in serialized


# ── Public Work Passport stays conservative (no unattached vault evidence) ────


# ── Canonical skill_evidence GitHub rows (old Profile & Proof engine) ─────────
#
# The precise, high-signal GitHub code evidence the older GitHub Portfolio & Proof
# scanner persisted lives in the canonical ``skill_evidence`` table (exact
# file/line + ``github_highlight_url`` + ``selection_reason``). The Skill Report
# must read THOSE first and let them beat the weaker ``github_proof_submissions``
# snapshot fallback.


def _seed_skill_evidence(
    mem_store: dict,
    *,
    user_id: str = USER_ID,
    skill_name: str = "API Development",
    repository_url: str = "https://github.com/octocat/Hello-World",
    file_path: str = "app/api/routes.py",
    line_start: int | None = 10,
    line_end: int | None = 20,
    evidence_description: str = "API route handler with request validation.",
    selection_reason: str = "API endpoint decorator",
    github_highlight_url: str | None = None,
    evidence_title: str | None = "Boston Smart Accident Risk Rerouting",
    evidence_type: str = "github repository",
    proof_visibility: str = "public",
    **meta_extra,
) -> str:
    """Seed one canonical ``skill_evidence`` GitHub row (PortfolioScanner import)."""
    evidence_id = str(uuid4())
    highlight = github_highlight_url
    if highlight is None and line_start:
        suffix = f"-L{line_end}" if line_end and line_end != line_start else ""
        highlight = f"{repository_url}/blob/main/{file_path}#L{line_start}{suffix}"
    metadata = {
        "evidence_title": evidence_title,
        "submission_source": "github_portfolio_scan",
        "import_source": "github_portfolio_scan_ui",
        "branch_ref": "main",
        "github_highlight_url": highlight,
        "selection_reason": selection_reason,
        "confidence_label": "high",
        "secret_token": "should-never-leak",
        **meta_extra,
    }
    mem_store.setdefault("skill_evidence", {})[evidence_id] = {
        "id": evidence_id,
        "user_id": user_id,
        "skill_name": skill_name,
        "evidence_type": evidence_type,
        "repository_url": repository_url,
        "file_path": file_path,
        "line_start": line_start,
        "line_end": line_end,
        "evidence_description": evidence_description,
        "proof_visibility": proof_visibility,
        "verification_status": "verified",
        "metadata": metadata,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    return evidence_id


def test_skill_report_reads_canonical_skill_evidence_github_rows(
    mem_store: dict, pipeline_db: dict
) -> None:
    _seed_skill_evidence(
        mem_store,
        skill_name="API Development",
        file_path="app/api/routes.py",
        line_start=10,
        line_end=20,
    )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "api-development")
    gh = _github_items(report)
    assert gh, "canonical skill_evidence GitHub row must surface in the Skill Report"
    code_line = [i for i in gh if i.get("display_mode") == "code_line"]
    assert code_line, "canonical evidence must be precise code_line evidence"
    item = code_line[0]
    assert item["file_path"] == "app/api/routes.py"
    assert item["line_start"] == 10 and item["line_end"] == 20
    assert item["has_precise_line_evidence"] is True
    assert item["github_line_url"] and "app/api/routes.py" in item["github_line_url"]
    assert item["evidence_kind"] == "portfolio_skill_evidence"


def test_canonical_skill_evidence_beats_github_proof_snapshot_fallback(
    mem_store: dict, pipeline_db: dict
) -> None:
    # Strong, precise canonical row for Python on octocat/Hello-World …
    _seed_skill_evidence(
        mem_store,
        skill_name="Python",
        file_path="src/train.py",
        line_start=40,
        line_end=44,
        selection_reason="ML training call",
    )
    # … plus a WEAK github_proof_submissions snapshot (import-only) for the SAME
    # repo + skill. The canonical precise row must win; the snapshot is suppressed.
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
                    "code_snippet": "import sys\nimport io\nimport time",
                }
            ]
        },
    )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "python")
    gh = _github_items(report)
    assert gh, "Python GitHub evidence must be present"
    # Every Python GitHub item is the canonical precise row — no repo-level fallback.
    assert all(i.get("display_mode") == "code_line" for i in gh), "fallback must be suppressed"
    item = gh[0]
    assert item["evidence_kind"] == "portfolio_skill_evidence"  # came from skill_evidence
    assert item["file_path"] == "src/train.py"
    # The weak snapshot import line never leaks anywhere.
    assert "import sys" not in str(report)


def test_skill_report_uses_repo_level_fallback_when_no_canonical_skill_evidence(
    mem_store: dict, pipeline_db: dict
) -> None:
    # No canonical skill_evidence; only a weak github_proof snapshot exists.
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
                    "code_snippet": "import sys\nimport io\nimport time",
                }
            ]
        },
    )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "python")
    gh = _github_items(report)
    assert gh, "the GitHub repo still surfaces for Python as repo-level support"
    for item in gh:
        assert item["display_mode"] == "repo_level"
        assert item["has_precise_line_evidence"] is False
        assert not item.get("safe_snippet")
        assert item.get("line_start") in (None, 0)


def test_skill_report_exposes_selection_reason_and_highlight_url(
    mem_store: dict, pipeline_db: dict
) -> None:
    _seed_skill_evidence(
        mem_store,
        skill_name="API Development",
        repository_url="https://github.com/octocat/Hello-World",
        file_path="app/api/routes.py",
        line_start=12,
        line_end=30,
        selection_reason="API endpoint decorator",
        github_highlight_url="https://github.com/octocat/Hello-World/blob/main/app/api/routes.py#L12-L30",
    )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "api-development")
    item = next(i for i in _github_items(report) if i.get("display_mode") == "code_line")
    # selection_reason + highlight URL became frontend-safe fields on the item.
    assert item["selection_reason"] == "API endpoint decorator"
    assert (
        item["github_line_url"]
        == "https://github.com/octocat/Hello-World/blob/main/app/api/routes.py#L12-L30"
    )


def test_duplicate_project_chains_group_after_canonical_github_merge(
    mem_store: dict, pipeline_db: dict
) -> None:
    # One canonical precise GitHub row on octocat/Hello-World, plus THREE same-title
    # VBR project rows that all point at that repo. The canonical lines correlate
    # into each chain; duplicate chains then collapse/group into ONE.
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        repository_url="https://github.com/octocat/Hello-World",
        file_path="src/model/predict.py",
        line_start=100,
        line_end=120,
        selection_reason="ML prediction/inference",
    )
    pids = [
        _seed_project(
            mem_store,
            title="Boston Smart Accident Risk Rerouting",
            repo_full_name="octocat/Hello-World",
        )
        for _ in range(3)
    ]

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    attached_chains = [p for p in report["projects"] if p.get("attached")]
    assert len(attached_chains) == 1, "same-repo same-title attempts must collapse into ONE chain"
    chain = attached_chains[0]
    grouped_ids = set(chain.get("collapsed_project_ids") or []) | set(chain.get("grouped_project_ids") or [])
    assert grouped_ids == set(pids)
    code_line = [e for e in chain["github_evidence"] if e.get("display_mode") == "code_line"]
    assert len(code_line) == 1, "the canonical code line is merged + deduped to one"
    assert code_line[0]["file_path"] == "src/model/predict.py"


def test_documents_remain_corroboration_when_canonical_github_exists(
    mem_store: dict, pipeline_db: dict
) -> None:
    # Canonical precise GitHub evidence on a project's repo + several attached docs.
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        repository_url="https://github.com/octocat/Hello-World",
        file_path="api.py",
        line_start=252,
        line_end=255,
        selection_reason="ML prediction/inference",
    )
    doc_ids = [
        _seed_document_evidence(
            mem_store,
            analysis_json={"title": f"Report {n}"},
            evidence_objects=[
                {"skill_name": "Machine Learning", "confidence": "high", "snippet": f"passage {n}", "page_number": n}
            ],
        )
        for n in range(5)
    ]
    pid = _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={"documents": [{"document_evidence_id": d} for d in doc_ids]},
    )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    chain = next(
        p for p in report["projects"] if pid in (p.get("grouped_project_ids") or [p.get("project_id")])
    )
    # Canonical GitHub code is the primary evidence …
    assert any(e.get("display_mode") == "code_line" for e in chain["github_evidence"])
    # … and documents stay capped corroboration, each marked supporting.
    assert len(chain["document_correlations"]) <= 3
    assert chain["document_more_count"] >= 1
    for corr in chain["document_correlations"]:
        assert corr["support_label"] == "Supporting evidence"
        assert "does not independently prove" in corr["limitation"]


def test_canonical_github_evidence_never_leaks_metadata_secret(
    mem_store: dict, pipeline_db: dict
) -> None:
    _seed_skill_evidence(mem_store, skill_name="Python", file_path="src/app.py")
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "python")
    assert "should-never-leak" not in str(report)


def test_public_passport_excludes_unattached_vault_evidence(
    client: TestClient, mem_store: dict, pipeline_db: dict
) -> None:
    """The public passport features only published-report projects; an unattached
    standalone proof (with a distinctive URL) must never surface there, and the
    public projection carries no private vault structure at all."""
    # A standalone, never-attached Website Proof with a recognizable URL.
    _seed_workflow_analysis(
        mem_store, target_website="https://standalone-leak.example.com", supported_skills=["Python"]
    )
    # Publish the passport (no published project reports → nothing featured).
    slug = client.post("/api/v1/student/vbr/passport/publish").json()["public_slug"]

    app.dependency_overrides.pop(get_current_user_id, None)
    res = client.get(f"/api/v1/public/p/{slug}")
    assert res.status_code == 200, res.text
    body = res.json()

    # Conservative: the standalone proof is not published, so it is excluded.
    assert "standalone-leak.example.com" not in res.text
    assert body["featured_project_count"] == 0
    # The public schema exposes no private vault structure.
    assert "vault_skills" not in body
    assert "vault_proof_count" not in body
