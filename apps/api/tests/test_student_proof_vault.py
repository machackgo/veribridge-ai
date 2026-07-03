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
from app.services.github_python_evidence_focus import (
    TRUSTED_ANALYSIS_TABLE,
    build_server_provenance,
)
from app.services.skill_normalization import canonical_skill, skill_category, skill_slug
from app.services.github_python_evidence_focus import GRADE_IMPLEMENTATION_BODY
from app.services.student_proof_vault_service import (
    _collect_documents,
    _github_repo_identity,
    _group_github_evidence,
    _has_coherent_impl_chain,
    _match_github_to_project,
    _skill_status,
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


def test_skill_report_downgrades_deployment_only_ml_implementation_body(
    mem_store: dict, pipeline_db: dict
) -> None:
    """A TRUSTED implementation_body that is deployment/serving-only (no ML executable
    signal) is downgraded at read time for an ML skill, so it can never render as
    Machine Learning primary implementation proof (must-fix: read-time ML validation)."""
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="serving/main.py",
        line_start=1,
        line_end=8,
        evidence_description="model serving inference handler",
        selection_reason="model serving inference handler",
        evidence_quality_grade=GRADE_IMPLEMENTATION_BODY,
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    row = next(i for i in _github_items(report) if i.get("file_path") == "serving/main.py")
    # Downgraded from the trusted implementation_body → supporting (not primary ML).
    assert row["evidence_quality_grade"] == "supporting_logic"


def test_skill_report_keeps_real_ml_implementation_body(
    mem_store: dict, pipeline_db: dict
) -> None:
    """A REAL ML implementation body (fit/predict/training signals) stays primary and
    keeps its useful reason — only deployment-only bodies are downgraded."""
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="src/model/train.py",
        line_start=10,
        line_end=20,
        evidence_description="model.fit training loop",
        selection_reason="model.fit training loop",
        evidence_quality_grade=GRADE_IMPLEMENTATION_BODY,
        code_snippet="def train_model(df):\n    return clf.fit(df)",
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    row = next(i for i in _github_items(report) if i.get("file_path") == "src/model/train.py")
    assert row["evidence_quality_grade"] == GRADE_IMPLEMENTATION_BODY
    assert row["selection_reason"] == "model.fit training loop"


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


def test_standalone_github_is_grouped_by_repository(mem_store: dict, pipeline_db: dict) -> None:
    """Standalone code evidence is grouped into ONE compact block per repository.

    Two distinct repositories that both evidence the skill form two separate
    groups (never merged), each with its own public "View repository" link and
    compact, de-duplicated code-line rows — so the report reads as a few grouped
    blocks instead of one full card per code line.
    """
    _seed_github_proof(
        mem_store,
        repo_url="https://github.com/alice/stroke-prediction",
        repo_owner="alice",
        repo_name="stroke-prediction",
        detected_skills=["Machine Learning"],
        analysis_snapshot={
            "skill_code_evidence": [
                {
                    "skill": "Machine Learning",
                    "file_path": "Tree.py",
                    "line_start": 13,
                    "line_end": 72,
                    "function_name": "train_tree",
                    "code_snippet": "def train_tree(X, y):\n    model = DecisionTreeClassifier().fit(X, y)\n    return model",
                }
            ]
        },
    )
    _seed_github_proof(
        mem_store,
        repo_url="https://github.com/bob/risk-rerouting",
        repo_owner="bob",
        repo_name="risk-rerouting",
        detected_skills=["Machine Learning"],
        analysis_snapshot={
            "skill_code_evidence": [
                {
                    "skill": "Machine Learning",
                    "file_path": "model.py",
                    "line_start": 40,
                    "line_end": 88,
                    "function_name": "fit_model",
                    "code_snippet": "def fit_model(X, y):\n    return RandomForestClassifier().fit(X, y)",
                }
            ]
        },
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    groups = report["standalone_evidence"]["github_groups"]
    # Two repositories ⇒ two separate groups (different owners never merge).
    assert len(groups) == 2
    repos = sorted(g["repo_url"] for g in groups)
    assert any("alice/stroke-prediction" in r for r in repos)
    assert any("bob/risk-rerouting" in r for r in repos)
    for group in groups:
        assert group["repo_is_public"] is True
        assert group["rows"], "each repo group surfaces its compact code rows"
        # Rows are de-duplicated within a group.
        keys = [(r["source_id"], r["label"]) for r in group["rows"]]
        assert len(keys) == len(set(keys))


def test_standalone_github_groups_never_duplicate_chain_evidence(
    mem_store: dict, pipeline_db: dict
) -> None:
    """GitHub evidence folded into a project chain is not regrouped as standalone."""
    proof_id = _seed_github_proof(
        mem_store,
        detected_skills=["Machine Learning"],
        analysis_snapshot={
            "skill_code_evidence": [
                {
                    "skill": "Machine Learning",
                    "file_path": "api.py",
                    "line_start": 10,
                    "line_end": 20,
                    "function_name": "predict",
                    "code_snippet": "def predict(x):\n    return model.predict(x)",
                }
            ]
        },
    )
    # Attach the same repo to a VBR project so it becomes a connected chain.
    _seed_project(
        mem_store,
        title="Hello World ML",
        repo_full_name="octocat/Hello-World",
        attached_proofs={"github_proof": {"github_proof_id": proof_id}},
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    # The evidence lives in the connected chain — the standalone group is empty.
    assert report["standalone_evidence"]["github_groups"] == []
    chain_gh = [g for p in report["projects"] for g in (p.get("github_evidence") or [])]
    assert any(g.get("file_path") == "api.py" for g in chain_gh)


def test_connected_chain_github_uses_grouped_model(mem_store: dict, pipeline_db: dict) -> None:
    """A connected chain's GitHub evidence is projected through the grouped model.

    Boston-style: even when only ``api.py``/``predict`` exists, the connected
    "Code implementation" is rendered through the SAME repository-grouped model as
    standalone GitHub — one group per canonical owner/repo with a compact row."""
    proof_id = _seed_ml_strong_github(mem_store)  # api.py · predict, octocat/Hello-World
    _seed_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={"github_proof": {"github_proof_id": proof_id}},
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    attached_chains = [p for p in report["projects"] if p.get("attached")]
    assert len(attached_chains) == 1
    chain = attached_chains[0]
    groups = chain["github_groups"]
    # One grouped block for the single canonical repo, with a compact api.py row.
    assert len(groups) == 1
    group = groups[0]
    assert "octocat/Hello-World" in (group["repo_url"] or "")
    assert group["rows"], "the grouped block surfaces a compact code row"
    assert any("api.py" in r["label"] and "predict" in r["label"] for r in group["rows"])
    # The flat list is kept for back-compat — but the grouped model is preferred.
    assert any(g.get("file_path") == "api.py" for g in chain["github_evidence"])


# ── Connected GitHub fallback: bounded multi-row ranked evidence ──────────────


def _seed_ml_multirow_github(mem_store: dict) -> str:
    """A ``github_proof_submissions`` snapshot with several genuine ML pipeline
    rows (training, preprocessing, model, inference, metrics), one generic helper,
    and a weak import — so the connected fallback has real multi-row evidence to
    rank and bound (it must surface the precise rows, ML-pipeline-first)."""
    return _seed_github_proof(
        mem_store,
        detected_skills=["Machine Learning"],
        analysis_snapshot={
            "skill_code_evidence": [
                # Generic helper (strong code, but NOT an ML pipeline stage).
                {
                    "skill": "Machine Learning",
                    "file_path": "src/util.py",
                    "line_start": 3,
                    "line_end": 5,
                    "function_name": "format_row",
                    "code_snippet": "def format_row(r):\n    return dict(r)",
                },
                # Weak import-only line — must never become a precise row.
                {
                    "skill": "Machine Learning",
                    "file_path": "setup.py",
                    "line_start": 1,
                    "line_end": 2,
                    "code_snippet": "import numpy as np\nimport pandas as pd",
                },
                # Inference endpoint.
                {
                    "skill": "Machine Learning",
                    "file_path": "api.py",
                    "line_start": 40,
                    "line_end": 44,
                    "function_name": "predict",
                    "code_snippet": "def predict(req):\n    return model.predict(req)",
                },
                # Training pipeline.
                {
                    "skill": "Machine Learning",
                    "file_path": "src/train.py",
                    "line_start": 10,
                    "line_end": 14,
                    "function_name": "train_model",
                    "code_snippet": "def train_model(X, y):\n    return model.fit(X, y)",
                },
                # Preprocessing / feature engineering.
                {
                    "skill": "Machine Learning",
                    "file_path": "src/preprocess.py",
                    "line_start": 20,
                    "line_end": 24,
                    "function_name": "prepare_features",
                    "code_snippet": "def prepare_features(df):\n    return train_test_split(df)",
                },
                # Evaluation metrics.
                {
                    "skill": "Machine Learning",
                    "file_path": "src/evaluate.py",
                    "line_start": 30,
                    "line_end": 34,
                    "function_name": "evaluate",
                    "code_snippet": "def evaluate(y, p):\n    return f1_score(y, p)",
                },
            ]
        },
    )


def _connected_chain(report: dict) -> dict:
    attached = [p for p in report["projects"] if p.get("attached")]
    assert len(attached) == 1
    return attached[0]


def test_connected_fallback_emits_multiple_strong_ml_rows(
    mem_store: dict, pipeline_db: dict
) -> None:
    """A connected GitHub fallback proof with several strong ML rows produces a
    single repo group with MULTIPLE rows — not the one-row group the old
    ``best_strong_for_skill`` single-row pick produced."""
    proof_id = _seed_ml_multirow_github(mem_store)
    _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={"github_proof": {"github_proof_id": proof_id}},
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    chain = _connected_chain(report)
    groups = chain["github_groups"]
    assert len(groups) == 1, "one canonical repo → one group"
    rows = groups[0]["rows"]
    # Multiple precise rows surface (not a single best row), bounded by the cap.
    precise = [r for r in rows if r.get("display_mode") == "code_line"]
    assert len(precise) >= 4
    files = {r.get("file_path") for r in precise}
    assert {"src/train.py", "src/preprocess.py", "api.py"} <= files


def test_connected_fallback_ranks_ml_pipeline_before_generic_helper(
    mem_store: dict, pipeline_db: dict
) -> None:
    """ML-pipeline rows (training/preprocessing/model/inference/metrics) precede the
    generic helper; file-path alphabetical order never overrides ML relevance."""
    proof_id = _seed_ml_multirow_github(mem_store)
    _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={"github_proof": {"github_proof_id": proof_id}},
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    rows = _connected_chain(report)["github_groups"][0]["rows"]
    precise_files = [r.get("file_path") for r in rows if r.get("display_mode") == "code_line"]
    helper_idx = precise_files.index("src/util.py")
    # Every genuine pipeline stage that is present outranks the generic helper.
    for ml_file in ("src/train.py", "src/preprocess.py", "api.py", "src/evaluate.py"):
        assert precise_files.index(ml_file) < helper_idx


def test_connected_fallback_excludes_weak_imports_when_precise_exist(
    mem_store: dict, pipeline_db: dict
) -> None:
    """Weak import/setup rows never appear as precise rows when strong/medium
    precise evidence exists for the same repo+skill."""
    proof_id = _seed_ml_multirow_github(mem_store)
    _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={"github_proof": {"github_proof_id": proof_id}},
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    rows = _connected_chain(report)["github_groups"][0]["rows"]
    assert all(r.get("file_path") != "setup.py" for r in rows)
    assert "import numpy" not in str(report)


def test_connected_fallback_populates_selection_reason(
    mem_store: dict, pipeline_db: dict
) -> None:
    """Each precise fallback row carries ``selection_reason`` derived from the
    analyzer's ``mapping_reason`` (safely scrubbed)."""
    proof_id = _seed_ml_multirow_github(mem_store)
    _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={"github_proof": {"github_proof_id": proof_id}},
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    rows = _connected_chain(report)["github_groups"][0]["rows"]
    train_row = next(r for r in rows if r.get("file_path") == "src/train.py")
    assert train_row["selection_reason"]
    assert "src/train.py" in train_row["selection_reason"]


def test_connected_repo_level_fallback_only_when_no_precise(
    mem_store: dict, pipeline_db: dict
) -> None:
    """A repo-level fallback row appears ONLY when there is no strong/medium precise
    evidence for the skill — never alongside precise rows."""
    # Precise evidence present → no repo-level fallback row for Machine Learning.
    proof_id = _seed_ml_multirow_github(mem_store)
    _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={"github_proof": {"github_proof_id": proof_id}},
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    rows = _connected_chain(report)["github_groups"][0]["rows"]
    assert all(r.get("display_mode") != "repo_level" for r in rows)

    # Weak-only evidence → the single honest repo-level fallback IS used.
    weak_store: dict = {}
    weak_proof = _seed_github_proof(
        weak_store,
        detected_skills=["Python"],
        analysis_snapshot={
            "skill_code_evidence": [
                {
                    "skill": "Python",
                    "file_path": "setup.py",
                    "line_start": 1,
                    "code_snippet": "import os\nimport sys",
                }
            ]
        },
    )
    _seed_project(
        weak_store,
        title="Weak Only",
        repo_full_name="octocat/Hello-World",
        attached_proofs={"github_proof": {"github_proof_id": weak_proof}},
    )
    weak_report = collect_skill_report(weak_store, {}, USER_ID, "python")
    weak_rows = _connected_chain(weak_report)["github_groups"][0]["rows"]
    assert weak_rows and all(r.get("display_mode") == "repo_level" for r in weak_rows)


def test_same_title_merge_omits_no_github_code_evidence(
    mem_store: dict, pipeline_db: dict
) -> None:
    """When same-title attempts merge and the union has GitHub evidence, the derived
    "No GitHub code evidence…" limitation from a GitHub-less attempt is dropped."""
    title = "Boston Smart Rerouting"
    gh_proof = _seed_ml_multirow_github(mem_store)
    # Attempt A: has the GitHub proof attached.
    _seed_project(
        mem_store,
        title=title,
        repo_full_name="octocat/Hello-World",
        attached_proofs={"github_proof": {"github_proof_id": gh_proof}},
    )
    # Attempt B: same title, but only a document (NO GitHub) — would carry the
    # derived "No GitHub code evidence…" limitation on its own.
    doc_id = _seed_document_evidence(
        mem_store,
        analysis_json={"title": "Boston Report"},
        evidence_objects=[
            {"skill_name": "Machine Learning", "confidence": "high", "snippet": "ML write-up", "page_number": 2}
        ],
    )
    _seed_project(
        mem_store,
        title=title,
        attached_proofs={"documents": [{"document_evidence_id": doc_id}]},
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    chain = _connected_chain(report)
    assert chain["github_evidence"], "merged chain has GitHub evidence"
    assert "No GitHub code evidence in this project for this skill." not in chain["limitations"]


def test_connected_multirow_fallback_not_duplicated_in_standalone(
    mem_store: dict, pipeline_db: dict
) -> None:
    """The multi-row connected GitHub evidence is not also regrouped as standalone."""
    proof_id = _seed_ml_multirow_github(mem_store)
    _seed_project(
        mem_store,
        title="Boston Smart Rerouting",
        repo_full_name="octocat/Hello-World",
        attached_proofs={"github_proof": {"github_proof_id": proof_id}},
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    assert report["standalone_evidence"]["github_groups"] == []


def test_skill_status_ml_without_implementation_body_not_demonstrated() -> None:
    """Weak GitHub + document + defense for an implementation-oriented skill (ML)
    must NOT read as "Demonstrated" when no primary implementation body exists."""
    proof_types = ["GitHub Proof", "Document Proof", "Project Defense"]
    status = _skill_status(
        proof_types, attached_count=1, skill="Machine Learning", has_implementation_body=False
    )
    assert status == "Evidence observed"


def test_skill_status_ml_with_implementation_body_is_demonstrated() -> None:
    """A real GitHub implementation body lifts an ML skill to "Demonstrated"."""
    proof_types = ["GitHub Proof", "Project Defense"]
    status = _skill_status(
        proof_types, attached_count=1, skill="Machine Learning", has_implementation_body=True
    )
    assert status == "Demonstrated"


def test_skill_status_non_code_skill_unaffected_by_body_gate() -> None:
    """A skill with no code profile (e.g. Communication) is not gated on a GitHub
    implementation body — it keeps the original multi-source demonstration rule."""
    proof_types = ["Project Defense", "Document Proof"]
    status = _skill_status(
        proof_types, attached_count=1, skill="Communication", has_implementation_body=False
    )
    assert status == "Demonstrated"


def _item(proof_type: str, *, pid: str | None, grade: str | None = None) -> dict:
    return {
        "proof_type": proof_type,
        "is_attached_to_project": pid is not None,
        "attached_project_ids": [pid] if pid else [],
        "evidence_quality_grade": grade,
    }


def test_coherent_chain_true_for_impl_body_plus_corroboration_same_project() -> None:
    """A single attached project with a SKILL-RELEVANT GitHub implementation body
    AND a defense (>= 2 distinct sources) is a coherent chain → eligible for
    Demonstrated. The body must prove the selected skill's own work (here: an
    authoritative grade-time ML signal for a Machine Learning report) — a bare
    implementation_body grade with no skill relevance no longer qualifies."""
    items = [
        _ml_github_item(pid="proj-a", grade=GRADE_IMPLEMENTATION_BODY, ml_signal=True),
        _item("Project Defense", pid="proj-a"),
    ]
    assert _has_coherent_impl_chain(items, skill="Machine Learning") is True


def test_coherent_chain_false_when_impl_body_standalone_and_weak_attached_elsewhere() -> None:
    """A standalone implementation body (project A) plus weak attached evidence from
    a DIFFERENT project (Boston) is NOT a coherent chain — it must not upgrade the
    unrelated Boston chain to Demonstrated."""
    items = [
        # Standalone (unattached) implementation body — supports standalone proof only.
        _item("GitHub Proof", pid=None, grade=GRADE_IMPLEMENTATION_BODY),
        # Boston attached chain: weak GitHub + document + defense (no impl body).
        _item("GitHub Proof", pid="boston", grade="import_only"),
        _item("Document Proof", pid="boston"),
        _item("Project Defense", pid="boston"),
    ]
    assert _has_coherent_impl_chain(items) is False


def test_coherent_chain_false_for_single_source_even_with_impl_body() -> None:
    """An implementation body alone (only one distinct source in the chain) is not
    yet a coherent multi-source chain."""
    items = [_item("GitHub Proof", pid="proj-a", grade=GRADE_IMPLEMENTATION_BODY)]
    assert _has_coherent_impl_chain(items) is False


def test_skill_status_standalone_impl_plus_weak_boston_not_demonstrated() -> None:
    """End-to-end status: standalone ML implementation + weak attached Boston chain
    stays capped (not Demonstrated) because there is no coherent chain."""
    items = [
        _item("GitHub Proof", pid=None, grade=GRADE_IMPLEMENTATION_BODY),
        _item("GitHub Proof", pid="boston", grade="import_only"),
        _item("Document Proof", pid="boston"),
        _item("Project Defense", pid="boston"),
    ]
    has_impl = _has_coherent_impl_chain(items)
    status = _skill_status(
        ["GitHub Proof", "Document Proof", "Project Defense"],
        attached_count=3,
        skill="Machine Learning",
        has_implementation_body=has_impl,
    )
    assert status == "Evidence observed"


def test_skill_status_coherent_ml_chain_is_demonstrated() -> None:
    """A single coherent project (skill-relevant implementation body + defense)
    reads Demonstrated — the known-skill happy path stays intact."""
    items = [
        _ml_github_item(pid="proj-a", grade=GRADE_IMPLEMENTATION_BODY, ml_signal=True),
        _item("Project Defense", pid="proj-a"),
    ]
    status = _skill_status(
        ["GitHub Proof", "Project Defense"],
        attached_count=2,
        skill="Machine Learning",
        has_implementation_body=_has_coherent_impl_chain(items, skill="Machine Learning"),
    )
    assert status == "Demonstrated"


def _ml_github_item(
    *, pid: str | None, grade: str | None, snippet: str = "", ml_signal: bool | None = None
) -> dict:
    """A GitHub vault item carrying the fields read-time ML validation inspects."""
    return {
        "proof_type": "GitHub Proof",
        "is_attached_to_project": pid is not None,
        "attached_project_ids": [pid] if pid else [],
        "evidence_quality_grade": grade,
        "safe_snippet": snippet,
        "ml_executable_signal": ml_signal,
    }


def test_coherent_chain_false_for_deployment_only_impl_body_downgraded() -> None:
    """A deployment-only GitHub row persisted as implementation_body but whose trusted
    body carries NO executable ML signal is downgraded at read time — it must not
    count as coherent implementation evidence even with defense corroboration."""
    items = [
        _ml_github_item(
            pid="proj-a",
            grade=GRADE_IMPLEMENTATION_BODY,
            snippet="@app.post('/predict')\ndef serve(req):\n    return {'ok': True}",
            ml_signal=False,
        ),
        _item("Project Defense", pid="proj-a"),
    ]
    assert _has_coherent_impl_chain(items, skill="Machine Learning") is False


def test_coherent_chain_downgraded_ml_row_plus_defense_document_capped() -> None:
    """A downgraded ML implementation_body row combined with a defense AND a document
    (same project) still does not form a coherent implementation chain."""
    items = [
        _ml_github_item(
            pid="boston",
            grade=GRADE_IMPLEMENTATION_BODY,
            snippet='"""Later call model.fit(...) and predict_proba(...)."""',
            ml_signal=None,
        ),
        _item("Document Proof", pid="boston"),
        _item("Project Defense", pid="boston"),
    ]
    assert _has_coherent_impl_chain(items, skill="Machine Learning") is False
    status = _skill_status(
        ["GitHub Proof", "Document Proof", "Project Defense"],
        attached_count=3,
        skill="Machine Learning",
        has_implementation_body=_has_coherent_impl_chain(items, skill="Machine Learning"),
    )
    assert status == "Evidence observed"


def test_coherent_chain_validated_ml_body_plus_corroboration_still_demonstrated() -> None:
    """A real validated ML implementation_body (executable fit call) plus defense in
    the same project still forms a coherent chain → Demonstrated is preserved."""
    items = [
        _ml_github_item(
            pid="proj-a",
            grade=GRADE_IMPLEMENTATION_BODY,
            snippet="clf = LGBMClassifier()\nclf.fit(X_train, y_train)",
            ml_signal=None,
        ),
        _item("Project Defense", pid="proj-a"),
    ]
    assert _has_coherent_impl_chain(items, skill="Machine Learning") is True
    status = _skill_status(
        ["GitHub Proof", "Project Defense"],
        attached_count=2,
        skill="Machine Learning",
        has_implementation_body=_has_coherent_impl_chain(items, skill="Machine Learning"),
    )
    assert status == "Demonstrated"


def test_coherent_chain_downgraded_standalone_ml_cannot_upgrade_weak_attached() -> None:
    """An unrelated standalone ML body (even if executable) cannot upgrade a weak
    attached chain from a DIFFERENT project — grouping by project keeps them apart."""
    items = [
        _ml_github_item(
            pid=None,
            grade=GRADE_IMPLEMENTATION_BODY,
            snippet="clf.fit(X_train, y_train)",
            ml_signal=None,
        ),
        _ml_github_item(pid="boston", grade="import_only", snippet="import sklearn"),
        _item("Document Proof", pid="boston"),
        _item("Project Defense", pid="boston"),
    ]
    assert _has_coherent_impl_chain(items, skill="Machine Learning") is False


# ── Skill-relevance gate on "Demonstrated" (Codex must-fix regressions) ────────
#
# A coherent implementation chain now requires the implementation body to be the
# SELECTED skill's own work (read-time relevance), never just any strong grade.


def _purpose_github_item(
    *,
    pid: str | None,
    grade: str | None,
    purpose_key: str | None = None,
    snippet: str = "",
    ml_signal: bool | None = None,
) -> dict:
    """A GitHub vault item carrying the trusted purpose/relevance inputs."""
    item = _ml_github_item(pid=pid, grade=grade, snippet=snippet, ml_signal=ml_signal)
    item["code_block_purpose_key"] = purpose_key
    return item


def test_coherent_chain_false_for_cross_skill_impl_body_in_devops_report() -> None:
    """CROSS-SKILL REGRESSION: a real, executable ML training implementation body
    plus a document AND a defense in the same project must NOT produce Demonstrated
    for a DevOps report — model training is cross_skill_context for DevOps."""
    items = [
        _purpose_github_item(
            pid="proj-a",
            grade=GRADE_IMPLEMENTATION_BODY,
            snippet="clf = LGBMClassifier()\nclf.fit(X_train, y_train)",
        ),
        _item("Document Proof", pid="proj-a"),
        _item("Project Defense", pid="proj-a"),
    ]
    assert _has_coherent_impl_chain(items, skill="DevOps") is False
    status = _skill_status(
        ["GitHub Proof", "Document Proof", "Project Defense"],
        attached_count=3,
        skill="DevOps",
        has_implementation_body=_has_coherent_impl_chain(items, skill="DevOps"),
    )
    assert status == "Evidence observed"
    # The SAME chain still demonstrates Machine Learning — relevance is per skill.
    assert _has_coherent_impl_chain(items, skill="Machine Learning") is True


def test_coherent_chain_false_for_frontend_ui_row_in_ml_report() -> None:
    """A React risk-input form (frontend UI purpose) + document + defense can never
    produce Demonstrated for Machine Learning — it is product UI context."""
    items = [
        _purpose_github_item(
            pid="proj-a",
            grade=GRADE_IMPLEMENTATION_BODY,
            purpose_key="frontend_ui_component",
            snippet="const RiskForm = () => {\n  return <form onSubmit={submit} />\n}",
        ),
        _item("Document Proof", pid="proj-a"),
        _item("Project Defense", pid="proj-a"),
    ]
    assert _has_coherent_impl_chain(items, skill="Machine Learning") is False
    # For a React report the same row IS direct implementation → coherent chain.
    assert _has_coherent_impl_chain(items, skill="React") is True


def test_coherent_chain_relevance_blocks_even_when_grade_survives() -> None:
    """Defense in depth: even a contradictory stale row whose grade survives via the
    grade-time ML verdict is still blocked for the selected skill when its resolved
    purpose is another skill's (API route shell → cross_skill_context for ML)."""
    items = [
        _purpose_github_item(
            pid="proj-a",
            grade=GRADE_IMPLEMENTATION_BODY,
            purpose_key="api_route_shell",
            ml_signal=True,
        ),
        _item("Project Defense", pid="proj-a"),
    ]
    assert _has_coherent_impl_chain(items, skill="Machine Learning") is False


def test_coherent_chain_ml_signal_row_without_snippet_stays_demonstrated() -> None:
    """A canonical ML row whose raw snippet is not re-exposed at read time (purpose
    unknown) but whose grade-time verdict proved executable ML stays a coherent
    implementation chain for Machine Learning."""
    items = [
        _purpose_github_item(pid="proj-a", grade=GRADE_IMPLEMENTATION_BODY, ml_signal=True),
        _item("Project Defense", pid="proj-a"),
    ]
    assert _has_coherent_impl_chain(items, skill="Machine Learning") is True


def test_coherent_chain_python_language_skill_still_demonstrable() -> None:
    """A real executable Python implementation body (language family → supporting
    implementation relevance) still forms a coherent chain for a Python report."""
    items = [
        _purpose_github_item(
            pid="proj-a",
            grade=GRADE_IMPLEMENTATION_BODY,
            snippet="clf = LGBMClassifier()\nclf.fit(X_train, y_train)",
        ),
        _item("Project Defense", pid="proj-a"),
    ]
    assert _has_coherent_impl_chain(items, skill="Python") is True


# ── Unknown/unmapped skill fail-closed (Codex blocker regressions) ─────────────
#
# An unknown/future IT skill (no family regex, no code profile) must FAIL CLOSED:
# its relevance resolves to at most supporting_context, so an implementation_body
# grade ALONE can never anchor a coherent chain or "Demonstrated". The grade-only
# bypass (`skill_family(skill) == general → True`) is removed.


def test_unknown_skill_impl_body_supporting_context_not_demonstrated() -> None:
    """BLOCKER TEST 1: unknown skill + implementation_body whose relevance resolves
    only to supporting_context → no coherent chain, capped at Evidence observed."""
    items = [
        _purpose_github_item(
            pid="proj-a",
            grade=GRADE_IMPLEMENTATION_BODY,
            snippet=(
                "def transfer_funds(a, b, amount):\n"
                "    ledger.apply(a, b, amount)\n"
                "    return ledger.balance(a)"
            ),
        ),
        _item("Project Defense", pid="proj-a"),
    ]
    assert _has_coherent_impl_chain(items, skill="Blockchain Development") is False
    status = _skill_status(
        ["GitHub Proof", "Project Defense"],
        attached_count=2,
        skill="Blockchain Development",
        has_implementation_body=_has_coherent_impl_chain(
            items, skill="Blockchain Development"
        ),
    )
    assert status == "Evidence observed"


def test_unknown_skill_impl_body_document_defense_not_demonstrated() -> None:
    """BLOCKER TEST 2: unknown skill + implementation_body + document + defense
    (three attached sources, same project) is still NOT Demonstrated — GitHub-backed
    skills require direct skill relevance even when no code profile knows the name."""
    items = [
        _purpose_github_item(
            pid="proj-a",
            grade=GRADE_IMPLEMENTATION_BODY,
            snippet="def handle(event):\n    queue.push(event)\n    return ack(event.id)",
        ),
        _item("Document Proof", pid="proj-a"),
        _item("Project Defense", pid="proj-a"),
    ]
    assert _has_coherent_impl_chain(items, skill="Elixir") is False
    status = _skill_status(
        ["GitHub Proof", "Document Proof", "Project Defense"],
        attached_count=3,
        skill="Elixir",
        has_implementation_body=_has_coherent_impl_chain(items, skill="Elixir"),
    )
    assert status == "Evidence observed"


def test_unknown_skill_without_github_evidence_keeps_original_rule() -> None:
    """A skill proven WITHOUT GitHub code (document + defense, e.g. Communication)
    keeps the original multi-source demonstration rule — the implementation gate
    only applies to code-backed claims."""
    status = _skill_status(
        ["Document Proof", "Project Defense"],
        attached_count=2,
        skill="Communication",
        has_implementation_body=False,
    )
    assert status == "Demonstrated"


def test_supporting_logic_never_anchors_demonstrated() -> None:
    """BLOCKER TEST 6 (vault half): supporting_logic remains supporting — even with
    an in-family purpose it is not an implementation body, so it can never anchor
    a coherent chain / Demonstrated, for known AND unknown skills."""
    for skill in ("React", "Blockchain Development"):
        items = [
            _purpose_github_item(
                pid="proj-a",
                grade="supporting_logic",
                purpose_key="frontend_form_component",
                snippet="const [risk, setRisk] = useState(0)",
            ),
            _item("Project Defense", pid="proj-a"),
        ]
        assert _has_coherent_impl_chain(items, skill=skill) is False


def test_group_github_evidence_keeps_distinct_owner_repos_apart() -> None:
    """The shared grouper keys on canonical owner/repo, never the bare repo name.

    Used for BOTH standalone and connected chain GitHub, so two different owners'
    same-named repos never merge (``bob/shared-app`` ≠ ``alice/shared-app``)."""
    groups = _group_github_evidence(
        [
            {"source_id": "a", "repo_url": "https://github.com/alice/shared-app",
             "public_url": "https://github.com/alice/shared-app", "file_path": "train.py",
             "line_start": 1, "line_end": 9},
            {"source_id": "b", "repo_url": "https://github.com/bob/shared-app",
             "public_url": "https://github.com/bob/shared-app", "file_path": "infer.py",
             "line_start": 1, "line_end": 9},
        ]
    )
    assert len(groups) == 2
    repo_urls = sorted(g["repo_url"] for g in groups)
    assert any("alice/shared-app" in r for r in repo_urls)
    assert any("bob/shared-app" in r for r in repo_urls)


def test_group_github_ownerless_same_title_rows_stay_separate() -> None:
    """Two legacy rows with the SAME title but no canonical owner/repo must NOT
    merge by title alone — ambiguous ownerless evidence falls back to stable
    evidence identity, so they render as two separate groups."""
    groups = _group_github_evidence(
        [
            {"source_id": "a", "title": "shared-app", "file_path": "train.py",
             "line_start": 1, "line_end": 9},
            {"source_id": "b", "title": "shared-app", "file_path": "infer.py",
             "line_start": 20, "line_end": 30},
        ]
    )
    assert len(groups) == 2


def test_group_github_exact_owner_repo_rows_group_together() -> None:
    """Rows sharing a canonical ``owner/repo`` identity collapse into ONE group."""
    groups = _group_github_evidence(
        [
            {"source_id": "a", "repo_url": "https://github.com/alice/app",
             "public_url": "https://github.com/alice/app", "file_path": "train.py",
             "line_start": 1, "line_end": 9},
            {"source_id": "b", "repo_url": "https://github.com/alice/app",
             "public_url": "https://github.com/alice/app", "file_path": "infer.py",
             "line_start": 20, "line_end": 30},
        ]
    )
    assert len(groups) == 1
    assert len(groups[0]["rows"]) == 2


def test_group_github_overflow_rows_kept_for_inline_expansion() -> None:
    """Rows beyond the visible window are KEPT in the payload (not dropped) so the
    "+N more code locations" toggle can reveal them inline; ``row_more_count``
    reports how many are initially collapsed."""
    rows = [
        {
            "source_id": "s",
            "repo_url": "https://github.com/alice/app",
            "public_url": "https://github.com/alice/app",
            "file_path": f"mod{i}.py",
            "line_start": i + 1,
            "line_end": i + 5,
            "display_mode": "code_line",
        }
        for i in range(9)
    ]
    groups = _group_github_evidence(rows)
    assert len(groups) == 1
    group = groups[0]
    # All 9 distinct rows are present in the payload (visible 6 + 3 collapsed).
    assert len(group["rows"]) == 9
    assert group["row_more_count"] == 3


def test_group_github_no_more_count_when_within_window() -> None:
    """A repo with at most the visible number of rows reports no overflow."""
    rows = [
        {
            "source_id": "s",
            "repo_url": "https://github.com/alice/app",
            "public_url": "https://github.com/alice/app",
            "file_path": f"mod{i}.py",
            "line_start": i + 1,
            "line_end": i + 5,
            "display_mode": "code_line",
        }
        for i in range(3)
    ]
    groups = _group_github_evidence(rows)
    assert groups[0]["row_more_count"] == 0
    assert len(groups[0]["rows"]) == 3


def test_group_github_unknown_owner_uses_stable_identity_not_title() -> None:
    """Ownerless fallback keys on stable evidence identity, never the title.

    Same-title rows with DISTINCT evidence stay separate; rows with an identical
    stable identity (same source/file/line) still de-dupe into a single row."""
    distinct = _group_github_evidence(
        [
            {"source_id": "x", "title": "legacy", "file_path": "a.py", "line_start": 1},
            {"source_id": "y", "title": "legacy", "file_path": "b.py", "line_start": 2},
        ]
    )
    assert len(distinct) == 2
    same = _group_github_evidence(
        [
            {"source_id": "x", "title": "legacy", "file_path": "a.py",
             "line_start": 1, "line_end": 5},
            {"source_id": "x", "title": "legacy", "file_path": "a.py",
             "line_start": 1, "line_end": 5},
        ]
    )
    assert len(same) == 1
    assert len(same[0]["rows"]) == 1


def test_group_github_orders_precise_line_above_repo_level() -> None:
    """Within one repo group a precise file/line code row ranks ABOVE a repo-level
    fallback card — repo-level evidence is never the strongest item when precise
    line-level evidence exists for the same repo."""
    groups = _group_github_evidence(
        [
            {"source_id": "r", "repo_url": "https://github.com/alice/app",
             "title": "alice/app", "display_mode": "repo_level"},
            {"source_id": "c", "repo_url": "https://github.com/alice/app",
             "title": "alice/app", "file_path": "model.py", "line_start": 5,
             "line_end": 10, "function_name": "train", "display_mode": "code_line"},
        ]
    )
    assert len(groups) == 1
    rows = groups[0]["rows"]
    assert rows[0]["display_mode"] == "code_line"
    assert rows[-1]["display_mode"] == "repo_level"


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
    # Route scanner-owned provenance (snippet/grade/focused range) into the
    # SERVICE-ROLE-ONLY protected table, mirroring how ``import_candidates``
    # persists a real PortfolioScanner row — skill_evidence.metadata is never
    # trusted for provenance, so it never carries the analyzer marker / grade /
    # snippet.
    prov_kwargs = {
        "code_snippet": meta_extra.pop("code_snippet", None),
        "grade": meta_extra.pop("evidence_quality_grade", None),
        "focused_start_line": meta_extra.pop("focused_start_line", None),
        "focused_end_line": meta_extra.pop("focused_end_line", None),
        "focused_reason": meta_extra.pop("focused_reason", None),
    }
    meta_extra.pop("evidence_analyzer", None)
    meta_extra.pop("evidence_analyzer_version", None)
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
    if any(v is not None for v in prov_kwargs.values()):
        mem_store.setdefault(TRUSTED_ANALYSIS_TABLE, {})[evidence_id] = {
            "skill_evidence_id": evidence_id,
            "user_id": user_id,
            **build_server_provenance(**prov_kwargs),
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
    # Strong, precise canonical row for Python on octocat/Hello-World — a real
    # implementation body (the scanner persists the focused source snippet), so it
    # grades implementation_body and is allowed to suppress the weaker fallback.
    _seed_skill_evidence(
        mem_store,
        skill_name="Python",
        file_path="src/train.py",
        line_start=40,
        line_end=44,
        selection_reason="ML training call",
        code_snippet="\n".join([
            "def train(df):",
            "    clf = RandomForestClassifier(n_estimators=200)",
            "    clf.fit(df.X, df.y)",
            "    return f1_score(df.y, clf.predict(df.X))",
        ]),
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


def test_weak_canonical_does_not_suppress_strong_snapshot_fallback(
    mem_store: dict, pipeline_db: dict
) -> None:
    # A WEAK canonical row (import-only, no body/provenance → grades weak) for ML on
    # octocat/Hello-World …
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="api.py",
        line_start=1,
        line_end=5,
        selection_reason="module imports and setup",
        evidence_description="Imports and module setup.",
    )
    # … must NOT hide a STRONGER github_proof_submissions snapshot (a real predict
    # handler body with precise lines) for the SAME repo + skill.
    _seed_ml_strong_github(mem_store)

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    gh = _github_items(report)
    assert gh, "ML GitHub evidence must be present"
    # The strong snapshot body survives as precise code_line evidence — the weak
    # canonical import row did not suppress it.
    code_line = [i for i in gh if i.get("display_mode") == "code_line"]
    assert code_line, "weak canonical row must NOT suppress the strong snapshot fallback"
    assert any(
        (i.get("file_path") == "api.py" and i.get("line_start") == 252)
        or i.get("function_name") == "predict"
        for i in code_line
    ), "the strong predict handler body from the snapshot must surface"


def test_strong_canonical_still_suppresses_redundant_fallback(
    mem_store: dict, pipeline_db: dict
) -> None:
    # A STRONG canonical row (real implementation body with a focused snippet) for
    # ML on octocat/Hello-World still suppresses the weaker snapshot fallback for the
    # SAME repo + skill — strong canonical wins, as before.
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="src/train.py",
        line_start=40,
        line_end=44,
        selection_reason="ML training call",
        code_snippet="\n".join([
            "def train(df):",
            "    clf = RandomForestClassifier(n_estimators=200)",
            "    clf.fit(df.X, df.y)",
            "    return f1_score(df.y, clf.predict(df.X))",
        ]),
    )
    # Weak import-only snapshot for the same repo + skill.
    _seed_github_proof(
        mem_store,
        detected_skills=["Machine Learning"],
        analysis_snapshot={
            "skill_code_evidence": [
                {
                    "skill": "Machine Learning",
                    "file_path": "api.py",
                    "line_start": 6,
                    "line_end": 9,
                    "code_snippet": "import sys\nimport io\nimport time",
                }
            ]
        },
    )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    gh = _github_items(report)
    assert gh, "ML GitHub evidence must be present"
    # Only the canonical precise row — the redundant weak fallback is suppressed.
    assert all(i.get("display_mode") == "code_line" for i in gh)
    assert gh[0]["file_path"] == "src/train.py"
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
    # selection_reason + highlight URL became frontend-safe fields on the item. The
    # bare route-decorator row is WEAK, so its stored "API endpoint decorator" reason
    # is neutralised to an honest grade-derived label (never preserved on a weak row).
    assert item["selection_reason"] == "route decorator without a handler body"
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


# ── #6: standalone GitHub evidence integrates into the same-repo project chain ─


def test_unattached_github_integrates_into_same_repo_project_chain(
    mem_store: dict, pipeline_db: dict
) -> None:
    """An UNATTACHED GitHub proof for the SAME repo as a project that already has
    a chain must be folded into that main chain — not shown as a duplicate
    standalone supporting proof. No evidence is lost or duplicated."""
    # Unattached GitHub proof (same repo as the project; NOT in attached_proofs).
    _seed_github_proof(
        mem_store,
        detected_skills=["Machine Learning"],
        analysis_snapshot={
            "skill_code_evidence": [
                {
                    "skill": "Machine Learning",
                    "file_path": "src/train.py",
                    "line_start": 10,
                    "line_end": 20,
                    "function_name": "train_model",
                    "code_snippet": "def train_model():\n    return clf.fit(X, y)",
                }
            ]
        },
    )
    # The project chain exists via an attached document (same repo/skill).
    doc_id = _seed_document_evidence(
        mem_store,
        evidence_objects=[
            {"skill_name": "Machine Learning", "confidence": "high", "snippet": "ML design", "page_number": 3}
        ],
    )
    pid = _seed_project(
        mem_store,
        title="Stroke Prediction",
        repo_full_name="octocat/Hello-World",
        attached_proofs={"documents": [{"document_evidence_id": doc_id}]},
    )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    chain = next(p for p in report["projects"] if p.get("project_id") == pid)
    # Integrated into the main chain…
    assert chain["github_evidence"], "same-repo GitHub proof should join the main chain"
    assert any(g.get("file_path") == "src/train.py" for g in chain["github_evidence"])
    # …and never duplicated in the standalone bucket.
    assert report["standalone_evidence"]["github"] == []


def test_unrelated_github_stays_standalone(mem_store: dict, pipeline_db: dict) -> None:
    """A GitHub proof whose repo/title matches no project chain stays standalone."""
    _seed_github_proof(
        mem_store,
        repo_url="https://github.com/someone/unrelated-lib",
        repo_owner="someone",
        repo_name="unrelated-lib",
        detected_skills=["Machine Learning"],
        analysis_snapshot={
            "skill_code_evidence": [
                {"skill": "Machine Learning", "file_path": "m.py", "line_start": 1, "line_end": 2,
                 "function_name": "f", "code_snippet": "def f():\n    return clf.predict(x)"}
            ]
        },
    )
    doc_id = _seed_document_evidence(
        mem_store,
        evidence_objects=[{"skill_name": "Machine Learning", "snippet": "design", "page_number": 1}],
    )
    _seed_project(
        mem_store, title="Totally Different Project", repo_full_name="octocat/Hello-World",
        attached_proofs={"documents": [{"document_evidence_id": doc_id}]},
    )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    assert report["standalone_evidence"]["github"], "unrelated GitHub proof must remain standalone"


# ── #4: Project Defense + Video evidence is grouped into one section ──────────


def _seed_session_with_defense(
    mem_store: dict, project_id: str, *, skill: str, chips: list[dict], session_id: str | None = None
) -> str:
    sid = session_id or str(uuid4())
    mem_store.setdefault("vbr_verification_sessions", {})[sid] = {
        "id": sid,
        "project_id": project_id,
        "attempt_no": 1,
        "telemetry": {
            "project_defense_analysis": {
                "skills_explained_well": [skill],
                "recruiter_summary": "The candidate explained the model training and prediction route.",
            },
            "video_evidence_chips": chips,
        },
    }
    return sid


def test_defense_evidence_is_grouped_into_one_section(mem_store: dict, pipeline_db: dict) -> None:
    pid = _seed_project(mem_store, title="Stroke Prediction", repo_full_name="octocat/Hello-World")
    _seed_session_with_defense(
        mem_store,
        pid,
        skill="Machine Learning",
        chips=[
            {"related_skill": "Machine Learning", "label": "Explains training loop", "timestamp": "01:20", "short_summary": "Walks through model.fit."},
            {"related_skill": "Machine Learning", "label": "Explains prediction", "timestamp": "02:05", "short_summary": "Shows the predict endpoint."},
        ],
    )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    chain = next(p for p in report["projects"] if p.get("project_id") == pid)
    group = chain["defense_group"]
    assert group is not None
    # 1 defense explanation + 2 video chips grouped.
    assert group["grouped_count"] == 3
    assert group["explanation"], "a single concise explanation should be surfaced"
    # The two timestamped video chips are the cited moments (defense overall card folded in).
    assert len(group["moments"]) == 2
    assert {m["timestamp_label"] for m in group["moments"]} == {"01:20", "02:05"}
    # One merged limitation, raw lists preserved (no evidence lost).
    assert group["limitation"]
    assert len(chain["video_evidence"]) == 2


def test_defense_group_absent_when_no_defense_or_video(mem_store: dict, pipeline_db: dict) -> None:
    _seed_github_proof(
        mem_store,
        detected_skills=["Machine Learning"],
        analysis_snapshot={"skill_code_evidence": [
            {"skill": "Machine Learning", "file_path": "t.py", "line_start": 1, "line_end": 2,
             "function_name": "train", "code_snippet": "def train():\n    clf.fit(X, y)"}
        ]},
    )
    doc_id = _seed_document_evidence(mem_store, evidence_objects=[{"skill_name": "Machine Learning", "snippet": "x", "page_number": 1}])
    pid = _seed_project(mem_store, title="P", repo_full_name="octocat/Hello-World",
                        attached_proofs={"documents": [{"document_evidence_id": doc_id}]})
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    chain = next(p for p in report["projects"] if p.get("project_id") == pid)
    assert chain["defense_group"] is None


# ── #5: skill-specific document context + download permission gating ─────────


def _doc_correlations(report: dict) -> list[dict]:
    out: list[dict] = []
    for chain in report.get("projects") or []:
        out.extend(chain.get("document_correlations") or [])
    out.extend(report.get("standalone_evidence", {}).get("documents") or [])
    return out


def test_document_context_surfaces_page_section_figure_and_gated_download(
    mem_store: dict, pipeline_db: dict
) -> None:
    _seed_document_evidence(
        mem_store,
        analysis_json={"title": "Stroke Prediction — Final Report"},  # no share opt-in
        evidence_objects=[
            {
                "skill_name": "Machine Learning",
                "page_number": 7,
                "section_label": "Model Evaluation",
                "snippet": "Reported F1 and confusion matrix for the classifier.",
                "figure_reference": "Figure 4",
                "reason": "Documents the evaluation metrics used to assess the model.",
            }
        ],
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    corrs = _doc_correlations(report)
    assert corrs, "document must surface as corroboration"
    corr = corrs[0]
    assert corr["page_number"] == 7
    assert corr["section_label"] == "Model Evaluation"
    assert corr["figure_reference"] == "Figure 4"
    assert corr["why_supported"], "must explain why the section supports the skill"
    # Download is gated by default (no explicit student opt-in).
    assert corr["full_document_available"] is False
    assert corr["document_access_note"] == "Full document available only with candidate permission."
    # Never a storage path or signed URL.
    blob = " ".join(str(v) for v in corr.values())
    assert "/storage/" not in blob and "://" not in blob.replace("Self-explanation", "")


def test_document_full_download_allowed_when_student_opted_in(
    mem_store: dict, pipeline_db: dict
) -> None:
    _seed_document_evidence(
        mem_store,
        analysis_json={"title": "Shared Report", "recruiter_shareable": True},
        evidence_objects=[
            {"skill_name": "Machine Learning", "page_number": 1, "snippet": "x", "reason": "supports"}
        ],
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    corr = _doc_correlations(report)[0]
    assert corr["full_document_available"] is True
    assert "candidate permission" not in corr["document_access_note"]


# ── Must-fix: full-document download needs an EXPLICIT opt-in, not public_safe ──
#
# ``public_safe`` only means a document is safe to summarize/cite in a projection
# — it is NOT consent to expose the full document for download. Only a dedicated
# student-controlled download opt-in may enable availability; default is closed.


def _doc_download_available(mem_store: dict, analysis_json: dict) -> bool:
    """Collect a single seeded document and return its full-download availability."""
    _seed_document_evidence(mem_store, analysis_json=analysis_json)
    items = _collect_documents(mem_store, USER_ID, {})
    assert items, "document proof must be collected"
    return bool(items[0]["full_document_available"])


def test_public_safe_alone_does_not_enable_full_document_download(mem_store: dict) -> None:
    # public_safe=True with NO dedicated download opt-in must stay download-gated.
    assert _doc_download_available(mem_store, {"title": "Report", "public_safe": True}) is False


def test_dedicated_download_opt_in_enables_full_document_availability(mem_store: dict) -> None:
    assert _doc_download_available(mem_store, {"title": "Report", "allow_public_download": True}) is True


def test_dedicated_download_opt_in_false_disables_full_document_availability(mem_store: dict) -> None:
    assert _doc_download_available(mem_store, {"title": "Report", "allow_public_download": False}) is False


def test_missing_download_opt_in_disables_full_document_availability(mem_store: dict) -> None:
    assert _doc_download_available(mem_store, {"title": "Report"}) is False


def test_document_proof_never_exposes_signed_url_or_storage_path(mem_store: dict) -> None:
    # Even WITH explicit consent, no storage path / signed URL is ever surfaced.
    _seed_document_evidence(
        mem_store,
        analysis_json={"title": "Report", "allow_public_download": True},
        file_path="/private/storage/users/secret/report.pdf",
    )
    items = _collect_documents(mem_store, USER_ID, {})
    assert items and items[0]["full_document_available"] is True
    blob = str(items)
    assert "/private/storage" not in blob
    assert "report.pdf" not in blob
    # No raw storage path / signed URL value is ever surfaced on the item.
    for it in items:
        assert it.get("file_path") is None
        assert it.get("public_url") is None


# ── Hostile: full-document consent requires an actual boolean True ──────────────
#
# Consent must be a real Python ``True`` on a dedicated opt-in field. Truthy
# strings/numbers/containers ("true", "false", "yes", "no", "1", "0", 1, 0, [],
# {}, any non-empty string) are NEVER consent; ``analysis_json.public_safe`` alone
# never enables download. A signed URL / storage path is never surfaced regardless.


def test_explicit_boolean_true_enables_download_indicator(mem_store: dict) -> None:
    assert _doc_download_available(mem_store, {"title": "R", "explicit_download_consent": True}) is True


def test_explicit_boolean_false_disables_download(mem_store: dict) -> None:
    assert _doc_download_available(mem_store, {"title": "R", "explicit_download_consent": False}) is False


@pytest.mark.parametrize(
    "analysis_json",
    [
        {"title": "R", "explicit_download_consent": "true"},
        {"title": "R", "explicit_download_consent": "false"},
        {"title": "R", "recruiter_shareable": "yes"},
        {"title": "R", "recruiter_shareable": "no"},
        {"title": "R", "allow_public_download": "1"},
        {"title": "R", "allow_public_download": "0"},
        {"title": "R", "allow_public_download": 1},
        {"title": "R", "allow_public_download": 0},
        {"title": "R", "allow_full_download": "enabled"},
        {"title": "R", "recruiter_download_enabled": []},
        {"title": "R", "student_allowed_public_download": {}},
        {"title": "R", "public_download_enabled": "True"},
    ],
)
def test_truthy_non_boolean_consent_never_enables_download(
    mem_store: dict, analysis_json: dict
) -> None:
    # Truthy strings/numbers/containers are NOT consent — only boolean True counts.
    assert _doc_download_available(mem_store, analysis_json) is False


def test_public_safe_true_alone_does_not_enable_download(mem_store: dict) -> None:
    # The generic ``public_safe`` flag is never consulted as download consent.
    assert _doc_download_available(mem_store, {"title": "R", "public_safe": True}) is False


def test_signed_url_never_exposed_when_download_disabled(mem_store: dict) -> None:
    # A non-boolean consent value leaves download disabled AND never leaks a path.
    _seed_document_evidence(
        mem_store,
        analysis_json={"title": "R", "explicit_download_consent": "true"},
        file_path="/private/storage/users/secret/report.pdf",
    )
    items = _collect_documents(mem_store, USER_ID, {})
    assert items and items[0]["full_document_available"] is False
    blob = str(items)
    assert "/private/storage" not in blob and "report.pdf" not in blob
    for it in items:
        assert it.get("file_path") is None
        assert it.get("public_url") is None


# ── Must-fix: standalone GitHub evidence only folds in on EXACT owner/repo ─────
#
# A GitHub proof carries its own authoritative repo identity. It may fold into a
# project's main chain ONLY when it is the *exact same* canonical ``owner/name``
# repository — never by repo name alone (``bob/shared-app`` must not fold into a
# project built on ``alice/shared-app``).


def _project_repo_meta(pid: str, repo_full: str) -> dict:
    return {
        pid: {
            "title": "Shared App",
            "title_norm": "shared app",
            "repo_full": repo_full,
            "repo_name": repo_full.split("/")[-1],
        }
    }


def test_github_evidence_not_folded_into_different_owner_same_repo_name() -> None:
    meta = _project_repo_meta("p-alice", "alice/shared-app")
    assert _match_github_to_project({"repo_url": "https://github.com/bob/shared-app"}, meta) is None


def test_github_evidence_folds_into_exact_same_owner_repo() -> None:
    meta = _project_repo_meta("p-alice", "alice/shared-app")
    assert _match_github_to_project({"repo_url": "https://github.com/alice/shared-app"}, meta) == "p-alice"


def test_github_evidence_owner_missing_stays_standalone() -> None:
    # A bare repo name (no owner) is ambiguous → fail closed, keep it standalone.
    meta = _project_repo_meta("p-alice", "alice/shared-app")
    assert _match_github_to_project({"repo_url": "shared-app"}, meta) is None


def test_github_evidence_matches_across_url_formats_when_owner_repo_same() -> None:
    meta = _project_repo_meta("p-alice", "alice/shared-app")
    for url in (
        "alice/shared-app",
        "git@github.com:alice/shared-app.git",
        "https://github.com/Alice/Shared-App",
        "https://github.com/alice/shared-app.git/",
    ):
        assert _match_github_to_project({"repo_url": url}, meta) == "p-alice", url


def test_github_evidence_format_normalization_does_not_cross_owners() -> None:
    # Case/format normalization must only match when owner AND repo are the same.
    meta = _project_repo_meta("p-alice", "alice/shared-app")
    for url in (
        "git@github.com:bob/shared-app.git",
        "https://github.com/BOB/Shared-App",
        "bob/shared-app",
    ):
        assert _match_github_to_project({"repo_url": url}, meta) is None, url


def test_github_repo_identity_canonicalizes_ssh_https_and_shorthand() -> None:
    assert _github_repo_identity({"repo_url": "git@github.com:alice/shared-app.git"})[0] == "alice/shared-app"
    assert _github_repo_identity({"repo_url": "https://github.com/Alice/Shared-App"})[0] == "alice/shared-app"
    assert _github_repo_identity({"repo_url": "alice/shared-app"})[0] == "alice/shared-app"


# ── Conservative GitHub evidence skill relation (ML connected reports) ────────
#
# A connected Machine-Learning project's GitHub evidence is often spread across
# canonical rows the analyzer tagged ``Python`` / ``Machine Learning Engineering``
# (model instantiation, prediction/inference, training, evaluation) rather than
# ``Machine Learning`` exactly. The relation layer folds those ML-specific rows
# from the SAME confirmed owner/repo into the ML report's connected
# ``github_groups`` — without weakening exact owner/repo routing and without
# admitting generic Python helpers/imports/setup.


def _seed_boston_like_repo(mem_store: dict, *, repo: str = "octocat/Hello-World") -> str:
    """A Boston-like repo: one exact ML row + several ML-specific canonical rows
    the analyzer tagged Python / Machine Learning Engineering, plus a generic
    Python row that must NOT be related into Machine Learning."""
    repo_url = f"https://github.com/{repo}"
    # Exact Machine Learning anchor row.
    _seed_skill_evidence(
        mem_store, skill_name="Machine Learning", repository_url=repo_url,
        file_path="api.py", line_start=252, line_end=255,
        selection_reason="prediction endpoint", evidence_description="Prediction inference endpoint.",
    )
    # ML-specific rows the analyzer tagged Python.
    _seed_skill_evidence(
        mem_store, skill_name="Python", repository_url=repo_url,
        file_path="src/model/train.py", line_start=10, line_end=20,
        selection_reason="model instantiation", evidence_description="Instantiates the model.",
    )
    _seed_skill_evidence(
        mem_store, skill_name="Python", repository_url=repo_url,
        file_path="src/model/evaluate.py", line_start=30, line_end=40,
        selection_reason="evaluation metrics", evidence_description="Computes evaluation metrics.",
    )
    _seed_skill_evidence(
        mem_store, skill_name="Python", repository_url=repo_url,
        file_path="scripts/pipeline_retrain.py", line_start=5, line_end=15,
        selection_reason="pipeline retrain", evidence_description="Retraining pipeline.",
    )
    # ML-specific row tagged Machine Learning Engineering.
    _seed_skill_evidence(
        mem_store, skill_name="Machine Learning Engineering", repository_url=repo_url,
        file_path="serving/main.py", line_start=8, line_end=18,
        selection_reason="model serving / inference", evidence_description="Model serving endpoint.",
    )
    # Generic Python row — MUST be rejected from Machine Learning.
    _seed_skill_evidence(
        mem_store, skill_name="Python", repository_url=repo_url,
        file_path="src/config.py", line_start=1, line_end=4,
        selection_reason="configuration constants", evidence_description="App configuration constants.",
    )
    return repo


def _ml_connected_rows(report: dict) -> list[dict]:
    chain = _connected_chain(report)
    rows: list[dict] = []
    for group in chain.get("github_groups") or []:
        rows += group.get("rows") or []
    return rows


def test_related_python_and_mle_rows_join_connected_ml_group(
    mem_store: dict, pipeline_db: dict
) -> None:
    """Boston-like: ML-specific rows tagged Python / Machine Learning Engineering
    join the connected Machine Learning ``github_groups`` — a multi-row group, not
    the single exact-ML row."""
    repo = _seed_boston_like_repo(mem_store)
    _seed_project(
        mem_store, title="Boston Smart Accident Risk Rerouting", repo_full_name=repo,
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    chain = _connected_chain(report)
    groups = chain["github_groups"]
    assert len(groups) == 1, "one canonical repo → one group"
    files = {r.get("file_path") for r in groups[0]["rows"]}
    # The exact ML row AND the related Python / MLE ML-specific rows are present.
    assert {"api.py", "src/model/train.py", "src/model/evaluate.py",
            "scripts/pipeline_retrain.py", "serving/main.py"} <= files
    assert len(groups[0]["rows"]) >= 5, "the connected group has multiple rows"


def test_generic_python_row_excluded_from_connected_ml_group(
    mem_store: dict, pipeline_db: dict
) -> None:
    """A generic Python row (config/constants) never joins Machine Learning."""
    repo = _seed_boston_like_repo(mem_store)
    _seed_project(mem_store, title="Boston Smart Rerouting", repo_full_name=repo)
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    files = {r.get("file_path") for r in _ml_connected_rows(report)}
    assert "src/config.py" not in files


def test_related_rows_require_exact_owner_repo(
    mem_store: dict, pipeline_db: dict
) -> None:
    """A ML-specific Python row in a DIFFERENT owner's repo is never folded into a
    Machine Learning report anchored on another owner's repo."""
    # Anchor ML repo owned by alice, attached to the project.
    _seed_skill_evidence(
        mem_store, skill_name="Machine Learning",
        repository_url="https://github.com/alice/shared-app",
        file_path="api.py", line_start=10, line_end=14, selection_reason="prediction endpoint",
    )
    # ML-specific Python row in bob/shared-app — same NAME, different owner.
    _seed_skill_evidence(
        mem_store, skill_name="Python",
        repository_url="https://github.com/bob/shared-app",
        file_path="src/model/train.py", line_start=5, line_end=9,
        selection_reason="model instantiation",
    )
    _seed_project(mem_store, title="Shared App", repo_full_name="alice/shared-app")
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    chain = _connected_chain(report)
    repo_urls = " ".join(g.get("repo_url") or "" for g in chain["github_groups"])
    files = {r.get("file_path") for r in _ml_connected_rows(report)}
    assert "bob/shared-app" not in repo_urls
    # bob's train.py must not ride into alice's connected ML group.
    bob_rows = [
        r for g in chain["github_groups"] for r in (g.get("rows") or [])
        if "bob/shared-app" in (r.get("github_line_url") or r.get("public_url") or "")
    ]
    assert not bob_rows


def test_related_rows_only_for_ml_target_skill(
    mem_store: dict, pipeline_db: dict
) -> None:
    """The relation layer does not broaden a non-ML target skill (e.g. Python):
    a Machine-Learning-tagged row never folds into the Python report by relation."""
    repo = _seed_boston_like_repo(mem_store)
    _seed_project(mem_store, title="Boston Smart Rerouting", repo_full_name=repo)
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "python")
    files = {r.get("file_path") for r in _ml_connected_rows(report)}
    # Python report shows the genuinely-Python rows but NOT the ML anchor (api.py
    # tagged Machine Learning) nor the MLE serving row by relation.
    assert "src/model/train.py" in files  # genuinely Python
    assert "api.py" not in files          # Machine Learning — not related into Python
    assert "serving/main.py" not in files  # Machine Learning Engineering


def test_connected_ml_group_drops_no_github_code_evidence_limitation(
    mem_store: dict, pipeline_db: dict
) -> None:
    """When related rows give the connected chain GitHub evidence, the chain never
    carries the contradictory "No GitHub code evidence…" limitation."""
    repo = _seed_boston_like_repo(mem_store)
    _seed_project(mem_store, title="Boston Smart Rerouting", repo_full_name=repo)
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    chain = _connected_chain(report)
    assert chain["github_groups"], "connected chain has grouped GitHub evidence"
    assert all(
        "No GitHub code evidence" not in lim for lim in (chain.get("limitations") or [])
    )


def test_related_connected_rows_not_duplicated_in_standalone(
    mem_store: dict, pipeline_db: dict
) -> None:
    """A related row folded into the connected chain is never also shown in the
    standalone/unlinked bucket."""
    repo = _seed_boston_like_repo(mem_store)
    _seed_project(mem_store, title="Boston Smart Rerouting", repo_full_name=repo)
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    standalone_files = {
        r.get("file_path")
        for g in (report["standalone_evidence"].get("github_groups") or [])
        for r in (g.get("rows") or [])
    }
    # All related ML rows are connected (the repo is attached) → standalone empty
    # of them.
    for f in ("src/model/train.py", "serving/main.py", "scripts/pipeline_retrain.py"):
        assert f not in standalone_files


def test_repo_level_fallback_only_when_no_precise_related(
    mem_store: dict, pipeline_db: dict
) -> None:
    """The relation layer only folds in PRECISE rows — a weak-only adjacent row is
    never related in, leaving the honest repo-level fallback behaviour intact."""
    repo_url = "https://github.com/octocat/Hello-World"
    # Exact ML anchor (precise).
    _seed_skill_evidence(
        mem_store, skill_name="Machine Learning", repository_url=repo_url,
        file_path="api.py", line_start=10, line_end=14, selection_reason="prediction endpoint",
    )
    # Adjacent Python proof whose ONLY stored line evidence is a weak import — it
    # has no precise line evidence, so it is never related into Machine Learning.
    _seed_github_proof(
        mem_store, detected_skills=["Python"], repo_owner="octocat", repo_name="Hello-World",
        repo_url=repo_url,
        analysis_snapshot={
            "skill_code_evidence": [
                {"skill": "Python", "file_path": "setup.py", "line_start": 1,
                 "code_snippet": "import os\nimport sys"}
            ]
        },
    )
    _seed_project(mem_store, title="Boston Smart Rerouting", repo_full_name="octocat/Hello-World")
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    files = {r.get("file_path") for r in _ml_connected_rows(report)}
    assert "api.py" in files
    assert "setup.py" not in files, "weak-only adjacent row must not be related in"


# ── End-to-end Boston regression: stale canonical rows never become top evidence ──
#
# These exercise the ACTIVE report path (collect_skill_report → canonical
# skill_evidence read → github_groups grouping/ranking), not isolated helpers, so
# they catch the live canonical-data failure: an import-only / docstring / config
# canonical range with no source snippet must never enter the visible top rows
# while a real training/inference/evaluation body exists for the same repo+skill.

_STRONG_GRADES = {"implementation_body", "supporting_logic"}


def _only_group(report: dict) -> dict:
    groups = report["standalone_evidence"]["github_groups"]
    assert len(groups) == 1, f"expected one canonical repo group, got {len(groups)}"
    return groups[0]


def _visible_rows(group: dict) -> list[dict]:
    """The rows shown by default (before the "+N more" expansion)."""
    visible = len(group["rows"]) - group["row_more_count"]
    return group["rows"][:visible]


def test_boston_stale_canonical_import_rows_are_not_visible_top_evidence(
    mem_store: dict, pipeline_db: dict
) -> None:
    # A STALE canonical row for an import-only api.py:19-23 range — NO source
    # snippet, but a reason that reads like real model serving — alongside a
    # genuine training body for the same repo+skill.
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        repository_url="https://github.com/octocat/Hello-World",
        file_path="api.py",
        line_start=19,
        line_end=23,
        evidence_description="Model serving inference endpoint.",
        selection_reason="model serving inference handler",
    )  # no code_snippet → stale row
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        repository_url="https://github.com/octocat/Hello-World",
        file_path="src/model/train.py",
        line_start=40,
        line_end=52,
        evidence_description="Train and evaluate the model.",
        selection_reason="model training",
        code_snippet=(
            "def train(df):\n"
            "    clf = RandomForestClassifier(n_estimators=200)\n"
            "    clf.fit(df.X, df.y)\n"
            "    return f1_score(df.y, clf.predict(df.X))"
        ),
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    group = _only_group(report)
    by_file = {r["file_path"]: r for r in group["rows"]}
    import_row = by_file["api.py"]
    body_row = by_file["src/model/train.py"]

    # The stale import-only row failed closed — never implementation/supporting.
    assert import_row["evidence_quality_grade"] not in _STRONG_GRADES
    assert import_row["evidence_quality_grade"] == "repo_level_fallback"
    # The genuine body kept a strong grade and is the visible top row.
    assert body_row["evidence_quality_grade"] in _STRONG_GRADES
    assert group["rows"][0] is body_row
    # The import row is demoted out of the visible window into "+N more".
    visible = _visible_rows(group)
    assert body_row in visible
    assert import_row not in visible
    # The import lines are never rendered as a snippet anywhere in the report.
    assert "import " not in (import_row.get("selection_reason") or "")


def test_boston_docstring_and_config_ranges_are_demoted_when_implementation_exists(
    mem_store: dict, pipeline_db: dict
) -> None:
    repo = "https://github.com/octocat/Hello-World"
    # Module docstring range (prose only).
    _seed_skill_evidence(
        mem_store, skill_name="Machine Learning", repository_url=repo,
        file_path="src/model/__init__.py", line_start=1, line_end=4,
        selection_reason="module docstring",
        code_snippet='"""Boston rerouting model package.\n\nProse only.\n"""',
    )
    # Config/constant + path-setup range.
    _seed_skill_evidence(
        mem_store, skill_name="Machine Learning", repository_url=repo,
        file_path="src/config.py", line_start=10, line_end=12,
        selection_reason="config constants",
        code_snippet='MODEL_PATH = os.environ.get("MODEL_PATH", "m.joblib")\nBATCH_SIZE = 32',
    )
    # Real training/evaluation body.
    _seed_skill_evidence(
        mem_store, skill_name="Machine Learning", repository_url=repo,
        file_path="src/model/train.py", line_start=40, line_end=52,
        selection_reason="model training",
        code_snippet=(
            "def train(df):\n"
            "    clf = RandomForestClassifier(n_estimators=200)\n"
            "    clf.fit(df.X, df.y)\n"
            "    return f1_score(df.y, clf.predict(df.X))"
        ),
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    group = _only_group(report)
    by_file = {r["file_path"]: r for r in group["rows"]}

    # The docstring and config ranges grade weak and are demoted off the top.
    assert by_file["src/model/__init__.py"]["evidence_quality_grade"] not in _STRONG_GRADES
    assert by_file["src/config.py"]["evidence_quality_grade"] not in _STRONG_GRADES
    # Only the real implementation body is visible top evidence.
    visible_files = {r["file_path"] for r in _visible_rows(group)}
    assert visible_files == {"src/model/train.py"}
    assert group["rows"][0]["evidence_quality_grade"] in _STRONG_GRADES


def test_github_groups_preserve_quality_grade_and_filter_visible_rows(
    mem_store: dict, pipeline_db: dict
) -> None:
    # Mixed canonical rows: a real inference body + a weak import-only range for the
    # same repo+skill. Every row must carry evidence_quality_grade, and the weak row
    # must not rank/appear like normal implementation code while a strong row exists.
    repo = "https://github.com/octocat/Hello-World"
    _seed_skill_evidence(
        mem_store, skill_name="Machine Learning", repository_url=repo,
        file_path="src/model/infer.py", line_start=12, line_end=20,
        selection_reason="model inference",
        code_snippet=(
            "def predict(model, df):\n"
            "    X = df.drop('risk', axis=1)\n"
            "    return model.predict(X)"
        ),
    )
    _seed_skill_evidence(
        mem_store, skill_name="Machine Learning", repository_url=repo,
        file_path="src/model/imports.py", line_start=1, line_end=3,
        selection_reason="imports",
        code_snippet="import os\nimport joblib\nfrom sklearn.ensemble import RandomForestClassifier",
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    group = _only_group(report)

    # Every row carries the quality grade (must-fix 2 acceptance).
    assert all("evidence_quality_grade" in r for r in group["rows"])
    # A strong row exists → the weak import row is not in the visible top rows.
    visible_grades = [r["evidence_quality_grade"] for r in _visible_rows(group)]
    assert visible_grades and all(g in _STRONG_GRADES for g in visible_grades)
    weak = next(r for r in group["rows"] if r["file_path"] == "src/model/imports.py")
    assert weak["evidence_quality_grade"] not in _STRONG_GRADES
    assert weak not in _visible_rows(group)


# ── Code role labels on Skill Report GitHub rows (descriptive, never strength) ─

from app.services.github_python_evidence_focus import (  # noqa: E402
    GRADE_COMMENT_OR_DOCSTRING,
    GRADE_IMPORT_ONLY,
    GRADE_ROUTE_DECORATOR_ONLY,
)


def _grouped_rows(report: dict) -> list[dict]:
    """All grouped GitHub rows across standalone groups + chain groups."""
    rows: list[dict] = []
    for g in (report.get("standalone_evidence") or {}).get("github_groups") or []:
        rows += g.get("rows") or []
    for p in report.get("projects") or []:
        for g in p.get("github_groups") or []:
            rows += g.get("rows") or []
    return rows


def test_weak_docstring_row_gets_documentation_header_role(
    mem_store: dict, pipeline_db: dict
) -> None:
    # A usage-header docstring that MENTIONS model.fit — trusted provenance grades
    # it comment_or_docstring; the role label must be documentation, never training.
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="scripts/pipeline_retrain.py",
        line_start=2,
        line_end=20,
        selection_reason="ML training call",
        evidence_quality_grade=GRADE_COMMENT_OR_DOCSTRING,
        code_snippet='"""Usage: model.fit(X, y) then model.predict(X)."""',
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    item = next(i for i in _github_items(report) if i.get("display_mode") == "code_line")
    assert item["evidence_quality_grade"] == GRADE_COMMENT_OR_DOCSTRING
    assert item["code_role_key"] == "documentation_header"
    assert item["code_role_label"] == "Documentation / usage header"
    # Grouped rows carry the same safe role fields for the frontend.
    row = next(r for r in _grouped_rows(report) if r.get("file_path") == "scripts/pipeline_retrain.py")
    assert row["code_role_key"] == "documentation_header"
    assert row["code_role_label"] == "Documentation / usage header"
    # The stale overclaiming reason is never the recruiter-facing label.
    assert item["selection_reason"] != "ML training call"


def test_weak_import_row_gets_imports_setup_role(mem_store: dict, pipeline_db: dict) -> None:
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="scripts/pipeline_retrain.py",
        line_start=29,
        line_end=47,
        selection_reason="ML training call",
        evidence_quality_grade=GRADE_IMPORT_ONLY,
        code_snippet="import pandas as pd\nfrom lightgbm import LGBMClassifier\n",
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    item = next(i for i in _github_items(report) if i.get("display_mode") == "code_line")
    assert item["code_role_key"] == "imports_setup"
    assert item["code_role_label"] == "Imports / setup context"
    assert item["evidence_quality_grade"] == GRADE_IMPORT_ONLY


def test_route_shell_row_gets_api_route_shell_role(mem_store: dict, pipeline_db: dict) -> None:
    _seed_skill_evidence(
        mem_store,
        skill_name="API Development",
        file_path="api.py",
        line_start=12,
        line_end=14,
        selection_reason="API endpoint decorator",
        evidence_quality_grade=GRADE_ROUTE_DECORATOR_ONLY,
        code_snippet="@app.post('/predict')\ndef predict(req):\n    ...",
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "api-development")
    item = next(i for i in _github_items(report) if i.get("display_mode") == "code_line")
    assert item["code_role_key"] == "api_route_shell"
    assert item["code_role_label"] == "API route shell"
    assert item["evidence_quality_grade"] == GRADE_ROUTE_DECORATOR_ONLY


def test_stale_ungraded_row_with_overclaiming_reason_gets_repository_context_role(
    mem_store: dict, pipeline_db: dict
) -> None:
    # A legacy row with NO trusted provenance at all — only a stale, overclaiming
    # stored reason. It must fall to repository-level context: the stale reason is
    # never trusted as the role, and never surfaces as the main label.
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="legacy/model_pipeline.py",
        line_start=1,
        line_end=9,
        selection_reason="ML training call",
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    item = next(i for i in _github_items(report) if i.get("display_mode") == "code_line")
    assert item["code_role_key"] == "repository_context"
    assert item["code_role_label"] == "Repository-level context"
    assert item["selection_reason"] != "ML training call"
    row = next(r for r in _grouped_rows(report) if r.get("file_path") == "legacy/model_pipeline.py")
    assert row["code_role_label"] == "Repository-level context"
    # Safe location + link survive for inspection.
    assert row["label"]
    assert row["github_line_url"]


def test_real_training_body_gets_model_training_role_and_stays_primary(
    mem_store: dict, pipeline_db: dict
) -> None:
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="src/model/train.py",
        line_start=19,
        line_end=37,
        selection_reason="ML training call",
        evidence_quality_grade=GRADE_IMPLEMENTATION_BODY,
        code_snippet=(
            "clf = LGBMClassifier(n_estimators=200)\n"
            "clf.fit(X_train, y_train)\n"
            "joblib.dump(clf, MODEL_PATH)\n"
        ),
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    item = next(i for i in _github_items(report) if i.get("display_mode") == "code_line")
    # The validated strong grade stands, and the role describes the body honestly.
    assert item["evidence_quality_grade"] == GRADE_IMPLEMENTATION_BODY
    assert item["code_role_key"] == "model_training"
    assert item["code_role_label"] == "Model training context"


def test_deployment_only_trusted_body_downgraded_with_deployment_role(
    mem_store: dict, pipeline_db: dict
) -> None:
    # Persisted as implementation_body but the TRUSTED body is deployment-only
    # plumbing: the ML gate downgrades the grade at read time, and the role reads
    # honestly as deployment/serving — never ML primary implementation.
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="serving/main.py",
        line_start=8,
        line_end=26,
        selection_reason="ML model serving",
        evidence_quality_grade=GRADE_IMPLEMENTATION_BODY,
        code_snippet='uvicorn.run(app, host="0.0.0.0", port=8080)\n',
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    item = next(i for i in _github_items(report) if i.get("display_mode") == "code_line")
    assert item["evidence_quality_grade"] != GRADE_IMPLEMENTATION_BODY
    assert item["code_role_key"] == "deployment_serving"
    assert item["code_role_label"] == "Deployment / serving context"


def test_code_role_fields_never_leak_raw_snippet_or_private_metadata(
    mem_store: dict, pipeline_db: dict
) -> None:
    # The role fields are enum-derived strings; the payload still never carries
    # the raw provenance snippet or the seeded secret metadata.
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="src/model/train.py",
        line_start=19,
        line_end=37,
        evidence_quality_grade=GRADE_IMPLEMENTATION_BODY,
        code_snippet="clf.fit(X_train, y_train)  # SECRET_TRAIN_MARKER\n",
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    import json

    payload = json.dumps(report)
    assert "SECRET_TRAIN_MARKER" not in payload
    assert "should-never-leak" not in payload
    item = next(i for i in _github_items(report) if i.get("display_mode") == "code_line")
    assert item["code_role_key"] in {
        "documentation_header", "imports_setup", "config_constants", "api_route_shell",
        "data_loading", "feature_engineering", "model_training", "evaluation_metrics",
        "prediction_inference", "deployment_serving", "repository_context",
        "unknown_needs_review",
    }


# ── Code block purpose on Skill Report GitHub rows (block-level, never proof) ──

from app.services.github_python_evidence_focus import (  # noqa: E402
    CODE_BLOCK_PURPOSE_KEYS,
    CODE_BLOCK_PURPOSE_LABELS,
)


def test_retraining_docstring_row_gets_specific_documentation_purpose(
    mem_store: dict, pipeline_db: dict
) -> None:
    # The manual-validation flagship: scripts/pipeline_retrain.py lines 2-20 is a
    # module docstring describing the retraining pipeline. The row must say so —
    # "Documentation describing retraining pipeline" — while staying weak.
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="scripts/pipeline_retrain.py",
        line_start=2,
        line_end=20,
        selection_reason="ML training call",
        evidence_quality_grade=GRADE_COMMENT_OR_DOCSTRING,
        code_snippet=(
            '"""Retraining pipeline.\n\n'
            "Reads the merged challenger dataset, runs spatial features +\n"
            "preprocessing + LightGBM + threshold tuning, evaluates against the\n"
            'champion, and writes artifacts/reports to GCS.\n"""'
        ),
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    item = next(i for i in _github_items(report) if i.get("display_mode") == "code_line")
    assert item["evidence_quality_grade"] == GRADE_COMMENT_OR_DOCSTRING
    assert item["code_block_purpose_key"] == "retraining_documentation"
    assert item["code_block_purpose_label"] == "Documentation describing retraining pipeline"
    assert "not executable training code" in item["code_block_purpose_summary"]
    # Grouped rows carry the same purpose fields for the frontend.
    row = next(r for r in _grouped_rows(report) if r.get("file_path") == "scripts/pipeline_retrain.py")
    assert row["code_block_purpose_label"] == "Documentation describing retraining pipeline"
    assert row["code_block_purpose_summary"]
    # Still weak / never primary, and the stale reason never surfaces.
    assert item["evidence_quality_grade"] not in _STRONG_GRADES
    assert item["selection_reason"] != "ML training call"
    assert row["github_line_url"]


def test_import_block_row_gets_imports_dependency_purpose(
    mem_store: dict, pipeline_db: dict
) -> None:
    # scripts/pipeline_retrain.py lines 29-47: imports/setup — the purpose says
    # "Imports / dependency setup", never model training.
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="scripts/pipeline_retrain.py",
        line_start=29,
        line_end=47,
        selection_reason="ML training call",
        evidence_quality_grade=GRADE_IMPORT_ONLY,
        code_snippet="import pandas as pd\nfrom lightgbm import LGBMClassifier\n",
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    item = next(i for i in _github_items(report) if i.get("display_mode") == "code_line")
    assert item["code_block_purpose_key"] == "imports_dependencies"
    assert item["code_block_purpose_label"] == "Imports / dependency setup"
    assert "not implementation proof" in item["code_block_purpose_summary"]
    assert item["evidence_quality_grade"] == GRADE_IMPORT_ONLY


def test_training_body_row_gets_model_training_purpose_and_stays_primary(
    mem_store: dict, pipeline_db: dict
) -> None:
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="src/model/train.py",
        line_start=19,
        line_end=37,
        selection_reason="ML training call",
        evidence_quality_grade=GRADE_IMPLEMENTATION_BODY,
        code_snippet="clf = LGBMClassifier(n_estimators=200)\nclf.fit(X_train, y_train)\n",
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    item = next(i for i in _github_items(report) if i.get("display_mode") == "code_line")
    assert item["evidence_quality_grade"] == GRADE_IMPLEMENTATION_BODY
    assert item["code_block_purpose_key"] == "model_training"
    assert item["code_block_purpose_label"] == "Model training"


def test_deployment_only_row_purpose_reads_deployment_never_ml_implementation(
    mem_store: dict, pipeline_db: dict
) -> None:
    # Persisted as implementation_body but the trusted body is serving plumbing:
    # the ML gate downgrades the grade, and the purpose reads deployment/serving.
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="scripts/vertex_deploy.py",
        line_start=85,
        line_end=103,
        selection_reason="ML model serving",
        evidence_quality_grade=GRADE_IMPLEMENTATION_BODY,
        code_snippet='uvicorn.run(app, host="0.0.0.0", port=8080)\n',
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    item = next(i for i in _github_items(report) if i.get("display_mode") == "code_line")
    assert item["evidence_quality_grade"] != GRADE_IMPLEMENTATION_BODY
    assert item["code_block_purpose_key"] == "deployment_serving"
    assert item["code_block_purpose_label"] == "Deployment / serving"
    assert "not ML" in item["code_block_purpose_summary"]


def test_stale_ungraded_row_purpose_fails_closed_to_repository_context(
    mem_store: dict, pipeline_db: dict
) -> None:
    # A legacy row with no trusted provenance and only a stale overclaiming
    # reason: the purpose fails closed and the stale text never surfaces.
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="legacy/model_pipeline.py",
        line_start=1,
        line_end=9,
        selection_reason="ML training call",
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    item = next(i for i in _github_items(report) if i.get("display_mode") == "code_line")
    assert item["code_block_purpose_key"] == "repository_context"
    assert item["code_block_purpose_label"] == "Repository-level context"
    assert item["selection_reason"] != "ML training call"
    row = next(r for r in _grouped_rows(report) if r.get("file_path") == "legacy/model_pipeline.py")
    assert row["code_block_purpose_label"] == "Repository-level context"


def test_purpose_fields_are_closed_vocabulary_and_never_leak_raw_data(
    mem_store: dict, pipeline_db: dict
) -> None:
    # Purpose fields are enum-derived strings from the closed vocabulary; the
    # payload never carries the raw provenance snippet or secret metadata.
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="scripts/pipeline_retrain.py",
        line_start=2,
        line_end=20,
        evidence_quality_grade=GRADE_COMMENT_OR_DOCSTRING,
        code_snippet='"""Retraining pipeline SECRET_DOC_MARKER."""',
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    import json

    payload = json.dumps(report)
    assert "SECRET_DOC_MARKER" not in payload
    assert "should-never-leak" not in payload
    item = next(i for i in _github_items(report) if i.get("display_mode") == "code_line")
    assert item["code_block_purpose_key"] in set(CODE_BLOCK_PURPOSE_KEYS)
    assert item["code_block_purpose_label"] in set(CODE_BLOCK_PURPOSE_LABELS.values())


# ── Skill relevance on Skill Report GitHub rows (selected-skill relation) ─────

from app.services.github_python_evidence_focus import (  # noqa: E402
    SKILL_RELEVANCE_KEYS,
)


def test_training_row_reads_direct_ml_relevance_on_validated_strong_grade(
    mem_store: dict, pipeline_db: dict
) -> None:
    # Tree.py-style executable training body: for a Machine Learning report the
    # relevance reads direct implementation — computed at read time, in the
    # closed vocabulary, alongside (never instead of) the validated grade.
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="Tree.py",
        line_start=13,
        line_end=72,
        selection_reason="ML training call",
        evidence_quality_grade=GRADE_IMPLEMENTATION_BODY,
        code_snippet=(
            "model = DecisionTreeClassifier(max_depth=5)\n"
            "model.fit(X_train, y_train)\n"
        ),
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    item = next(i for i in _github_items(report) if i.get("display_mode") == "code_line")
    assert item["evidence_quality_grade"] == GRADE_IMPLEMENTATION_BODY
    assert item["code_block_purpose_key"] == "model_training"
    assert item["skill_relevance_key"] == "direct_implementation"
    assert item["skill_relevance_label"] == "Direct Machine Learning implementation evidence"
    assert "directly implements Machine Learning" in item["skill_relevance_summary"]
    # Grouped rows carry the same relevance fields for the frontend.
    row = next(r for r in _grouped_rows(report) if r.get("file_path") == "Tree.py")
    assert row["skill_relevance_key"] == "direct_implementation"
    assert row["skill_relevance_label"] == "Direct Machine Learning implementation evidence"


def test_docstring_and_import_rows_read_context_relevance_never_direct(
    mem_store: dict, pipeline_db: dict
) -> None:
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="scripts/pipeline_retrain.py",
        line_start=2,
        line_end=20,
        selection_reason="ML training call",
        evidence_quality_grade=GRADE_COMMENT_OR_DOCSTRING,
        code_snippet='"""Retraining pipeline for the champion model."""',
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    item = next(i for i in _github_items(report) if i.get("display_mode") == "code_line")
    assert item["skill_relevance_key"] == "documentation_context"
    assert (
        item["skill_relevance_label"]
        == "Documentation context, not executable Machine Learning proof"
    )
    assert item["evidence_quality_grade"] not in _STRONG_GRADES


def test_stale_stored_relevance_is_recomputed_at_read_time(
    mem_store: dict, pipeline_db: dict
) -> None:
    # HARD RULE: a stored (stale/forged) "direct_implementation" relevance riding
    # on an import-only row is discarded — read time recomputes from the resolved
    # purpose × validated grade, and imports are setup context for every skill.
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="scripts/pipeline_retrain.py",
        line_start=29,
        line_end=47,
        selection_reason="ML training call",
        evidence_quality_grade=GRADE_IMPORT_ONLY,
        code_snippet="import pandas as pd\nfrom lightgbm import LGBMClassifier\n",
        skill_relevance_key="direct_implementation",
        skill_relevance_label="Direct Machine Learning implementation evidence",
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    item = next(i for i in _github_items(report) if i.get("display_mode") == "code_line")
    assert item["skill_relevance_key"] == "setup_context"
    assert item["skill_relevance_label"] == "Setup context, not Machine Learning implementation proof"


def test_relevance_is_relative_to_the_reports_selected_skill(
    mem_store: dict, pipeline_db: dict
) -> None:
    # The same executable training row filed under "Python": in the Python report
    # it reads as supporting language evidence, never as a direct-Python claim.
    _seed_skill_evidence(
        mem_store,
        skill_name="Python",
        file_path="src/model/train.py",
        line_start=19,
        line_end=37,
        selection_reason="ML training call",
        evidence_quality_grade=GRADE_IMPLEMENTATION_BODY,
        code_snippet="clf = LGBMClassifier(n_estimators=200)\nclf.fit(X_train, y_train)\n",
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "python")
    item = next(i for i in _github_items(report) if i.get("display_mode") == "code_line")
    assert item["code_block_purpose_key"] == "model_training"
    assert item["skill_relevance_key"] == "supporting_implementation"
    assert item["skill_relevance_label"] == "Supporting Python implementation evidence"


def test_relevance_fields_are_closed_vocabulary_and_never_leak_raw_data(
    mem_store: dict, pipeline_db: dict
) -> None:
    _seed_skill_evidence(
        mem_store,
        skill_name="Machine Learning",
        file_path="scripts/pipeline_retrain.py",
        line_start=2,
        line_end=20,
        evidence_quality_grade=GRADE_COMMENT_OR_DOCSTRING,
        code_snippet='"""Retraining pipeline SECRET_REL_MARKER."""',
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning")
    import json

    payload = json.dumps(report)
    assert "SECRET_REL_MARKER" not in payload
    assert "should-never-leak" not in payload
    item = next(i for i in _github_items(report) if i.get("display_mode") == "code_line")
    assert item["skill_relevance_key"] in set(SKILL_RELEVANCE_KEYS)
    # Rendered labels never carry template braces or markup.
    for banned in ("{", "}", "<", ">"):
        assert banned not in item["skill_relevance_label"]
        assert banned not in item["skill_relevance_summary"]


# ── Phase 3: skill strengthening actions (Proof Attachment Intelligence) ──────
#
# Each compact skill card carries owner-only, deterministic "strengthen this
# skill" sentences derived from the already-computed counts / status — never a
# score, never counting unattached evidence as attached project proof.


def _vault_item(
    skill: str,
    proof_type: str,
    *,
    pid: str | None = None,
    source_id: str = "src-1",
    source_table: str = "tbl",
    title: str = "Proof",
) -> dict:
    return {
        "skill_name": skill,
        "proof_type": proof_type,
        "source_id": source_id,
        "source_table": source_table,
        "project_id": pid,
        "attached_project_ids": [pid] if pid else [],
        "title": title,
        "safe_summary": "",
        "safe_location": None,
        "public_safe": False,
        "limitation": "",
        "is_attached_to_project": pid is not None,
    }


def test_skill_summary_unattached_only_action_without_counting_as_attached(
    mem_store: dict, pipeline_db: dict
) -> None:
    """A skill whose evidence is entirely unattached gets an honest attach
    action, while attached_count stays 0 — unattached proof never reads as
    attached project proof."""
    items = [_vault_item("Kubernetes", "Document Proof")]
    summaries = collect_skill_summaries(mem_store, pipeline_db, USER_ID, items=items)

    card = next(s for s in summaries if s["skill"] == "Kubernetes")
    assert card["attached_count"] == 0
    assert card["unattached_count"] == 1
    actions = card["strengthening_actions"]
    assert actions
    assert any("none of it is attached to a project" in a for a in actions)


def test_skill_summary_demonstrated_action_names_strongest_project(
    mem_store: dict, pipeline_db: dict
) -> None:
    """A demonstrated skill names the attached project it is proven through."""
    project_id = "proj-strong"
    mem_store["vbr_projects"] = {
        project_id: {"id": project_id, "user_id": USER_ID, "title": "Stroke Prediction App"}
    }
    # Non-code skill: two distinct attached sources → Demonstrated.
    items = [
        _vault_item("Communication", "Document Proof", pid=project_id, source_id="d1"),
        _vault_item("Communication", "Project Defense", pid=project_id, source_id="s1"),
    ]
    summaries = collect_skill_summaries(mem_store, pipeline_db, USER_ID, items=items)

    card = next(s for s in summaries if s["skill"] == "Communication")
    assert card["status"] == "Demonstrated"
    assert any(
        "strong attached project proof through Stroke Prediction App" in a
        for a in card["strengthening_actions"]
    )


def test_skill_summary_mixed_attached_and_unattached_gets_review_action(
    mem_store: dict, pipeline_db: dict
) -> None:
    project_id = "proj-1"
    mem_store["vbr_projects"] = {
        project_id: {"id": project_id, "user_id": USER_ID, "title": "ML Project"}
    }
    items = [
        _vault_item("Machine Learning", "Project Defense", pid=project_id, source_id="s1"),
        _vault_item("Machine Learning", "Document Proof", source_id="d9"),
    ]
    summaries = collect_skill_summaries(mem_store, pipeline_db, USER_ID, items=items)

    card = next(s for s in summaries if s["skill"] == "Machine Learning")
    assert card["unattached_count"] == 1
    assert any("1 proof item(s) are not attached" in a for a in card["strengthening_actions"])


def test_skill_summary_implementation_skill_hints_github_proof(
    mem_store: dict, pipeline_db: dict
) -> None:
    """An implementation-oriented skill with no GitHub proof is told to attach
    repository implementation evidence (qualitative copy, no scores)."""
    items = [_vault_item("Kubernetes", "Document Proof")]
    summaries = collect_skill_summaries(mem_store, pipeline_db, USER_ID, items=items)

    card = next(s for s in summaries if s["skill"] == "Kubernetes")
    assert any("attach GitHub proof" in a for a in card["strengthening_actions"])
    # Never numeric: qualitative sentences only.
    for action in card["strengthening_actions"]:
        assert "%" not in action and "score" not in action.lower()


def test_skill_summary_non_code_skill_never_told_to_attach_code(
    mem_store: dict, pipeline_db: dict
) -> None:
    items = [_vault_item("Communication", "Document Proof")]
    summaries = collect_skill_summaries(mem_store, pipeline_db, USER_ID, items=items)

    card = next(s for s in summaries if s["skill"] == "Communication")
    assert not any("GitHub" in a for a in card["strengthening_actions"])
