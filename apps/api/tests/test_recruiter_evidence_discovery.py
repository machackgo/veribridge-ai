"""Recruiter Evidence Discovery (V1.6) — intent classification, proof
retrieval, evidence-type filters, candidate context, related-evidence
labeling, and the privacy fail-closed guarantees.

These tests encode the production defect found manually on 2026-08-18:
"can you show me the specific proof of data engineering" was executed as a
CANDIDATE search (and returned nothing) instead of an EVIDENCE search that
opens the published proof behind the claim.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.services.recruiter_evidence_service import search_evidence
from app.services.recruiter_query_understanding import (
    INTENT_CANDIDATE_SEARCH,
    INTENT_EVIDENCE_SEARCH,
    INTENT_PROJECT_SEARCH,
    classify_intent,
    parse_recruiter_query,
)
from app.services.recruiter_search_service import build_index_row, search_candidates

RECRUITER_ID = "00000000-0000-4000-8000-00000000r001"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict):
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: mem_store
    app.dependency_overrides[get_current_user_id] = lambda: RECRUITER_ID
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# ── Fixture corpus ───────────────────────────────────────────────────────────


def _skill(
    name: str,
    slug: str,
    status: str,
    sources: list[str],
    *,
    projects: list[dict] | None = None,
    traces: list[dict] | None = None,
) -> dict:
    return {
        "skill": name,
        "skill_slug": slug,
        "category": "",
        "status": status,
        "evidence_sources": sources,
        "aliases": [],
        "projects": projects or [],
        "traces": traces or [],
    }


def _proof_project(title: str, path: str, status: str, types: list[str]) -> dict:
    return {
        "title": title,
        "public_report_path": path,
        "skill_status": status,
        "proof_types": types,
    }


def _row(
    uid: str,
    slug: str,
    name: str,
    *,
    headline: str = "",
    skills: list[dict] | None = None,
    technologies: list[str] | None = None,
    project_title: str = "Demo Project",
    live: bool = False,
    github: bool = False,
    published_at: str = "2026-07-01T00:00:00+00:00",
) -> dict:
    skills = skills or []
    project_sources = (["GitHub Proof"] if github else []) + (
        ["Website Proof"] if live else []
    )
    projects = [
        {
            "title": project_title,
            "summary": "",
            "technologies": technologies or [],
            "evidence_sources": project_sources,
            "public_report_path": f"/r/{slug}",
            "has_live_url": live,
            "has_github_repo": github,
        }
    ]
    searchable = " ".join(
        [s["skill"] for s in skills]
        + (technologies or [])
        + [name, headline, project_title]
    ).lower()
    return {
        "user_id": uid,
        "passport_id": f"pp-{uid}",
        "public_slug": slug,
        "display_name": name,
        "headline": headline or None,
        "location": None,
        "availability": None,
        "availability_label": None,
        "institution": None,
        "degree": None,
        "graduation_year": None,
        "role_areas": [],
        "skills": skills,
        "projects": projects,
        "evidence_flags": {
            "github": github,
            "live_site": live,
            "documents": False,
            "project_defense": False,
            "video": False,
        },
        "skill_count": len(skills),
        "project_count": 1,
        "text_skills": " ".join(s["skill"] for s in skills).lower(),
        "text_profile": f"{name} {headline}".lower(),
        "text_projects": project_title.lower(),
        "text_meta": "",
        "search_text": searchable,
        "disclosure_version": 1,
        "passport_published_at": published_at,
        "projected_at": "2026-08-18T00:00:00+00:00",
    }


def _seed(mem_store: dict) -> None:
    """ALPHA: ML (github+docs, project refs + traces) + FastAPI; Docker only
    claimed on the project. BRAVO: NLP + Python. No candidate has Data
    Engineering evidence."""
    rows = [
        _row(
            "u-alpha", "alpha", "Alpha Candidate",
            headline="AI Engineer",
            skills=[
                _skill(
                    "Machine Learning", "machine-learning", "Demonstrated",
                    ["GitHub Proof", "Document Proof"],
                    projects=[
                        _proof_project(
                            "Boston Risk Rerouting", "/r/alpha",
                            "Demonstrated", ["GitHub Proof", "Document Proof"],
                        )
                    ],
                    traces=[
                        {
                            "source_type": "GitHub Proof",
                            "source_title": "model.py",
                            "summary": "Trains a gradient-boosted risk model",
                            "public_url": "https://github.com/x/y/blob/main/model.py",
                        }
                    ],
                ),
                _skill(
                    "FastAPI", "fastapi", "Partially demonstrated",
                    ["GitHub Proof"],
                    projects=[
                        _proof_project(
                            "Boston Risk Rerouting", "/r/alpha",
                            "Partially demonstrated", ["GitHub Proof"],
                        )
                    ],
                ),
            ],
            technologies=["Python", "Docker"],
            project_title="Boston Risk Rerouting",
            github=True,
        ),
        _row(
            "u-bravo", "bravo", "Bravo Candidate",
            headline="NLP student",
            skills=[
                _skill(
                    "Natural Language Processing", "natural-language-processing",
                    "Demonstrated", ["GitHub Proof"],
                    projects=[
                        _proof_project(
                            "Sentiment API", "/r/bravo",
                            "Demonstrated", ["GitHub Proof"],
                        )
                    ],
                ),
                _skill("Python", "python", "Evidence observed", ["GitHub Proof"]),
            ],
            technologies=["Python", "Flask"],
            project_title="Sentiment API",
            github=True,
        ),
    ]
    mem_store["recruiter_search_index"] = {r["user_id"]: r for r in rows}
    mem_store["vbr_work_passports"] = {
        f"pp-{r['user_id']}": {
            "id": f"pp-{r['user_id']}",
            "user_id": r["user_id"],
            "public_slug": r["public_slug"],
            "is_published": True,
            "published_at": r["passport_published_at"],
        }
        for r in rows
    }


def _items(payload: dict) -> list[dict]:
    return [i for g in payload["groups"] for i in g["items"]]


# ── Intent classification ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "show me proof of machine learning",
        "can you show me the specific proof of data engineering",
        "show me evidence for FastAPI",
        "what verifies Python",
        "how do I know this candidate knows backend development",
        "show me GitHub proof of Python",
        "show me live deployment proof",
        "show me document proof of machine learning",
        "show me project defense evidence",
        "show me video evidence for FastAPI",
        "show me Mohammed's Python proof",
        "show evidence that Mohammed has machine learning experience",
        "show me the deployment proof for Mohammed",
        "show me actual proof that this candidate used FastAPI",
        "what evidence backs this candidate's backend experience",
        "I want to see the real artifacts behind machine learning",
        "where is the proof for machine learning",
        "show me the code for machine learning",
        "show me the VBR for machine learning",
    ],
)
def test_evidence_intent_queries(query: str) -> None:
    assert classify_intent(query.lower()) == INTENT_EVIDENCE_SEARCH


@pytest.mark.parametrize(
    "query",
    [
        "which project proves machine learning",
        "which project demonstrates computer vision",
        "show me the project where FastAPI was used",
        "what projects has this candidate built",
    ],
)
def test_project_intent_queries(query: str) -> None:
    assert classify_intent(query.lower()) == INTENT_PROJECT_SEARCH


@pytest.mark.parametrize(
    "query",
    [
        "find me someone with FastAPI",
        "AI engineer with Python and NLP who has deployed a project",
        "machine learning with GitHub evidence",
        "Backend intern with FastAPI and PostgreSQL",
        "candidates with deployment evidence",
        "find people with document proof of python",
        "",
    ],
)
def test_candidate_intent_queries(query: str) -> None:
    assert classify_intent(query.lower()) == INTENT_CANDIDATE_SEARCH


def test_intent_is_separate_from_skill_extraction() -> None:
    """The original production defect: intent and concept must both parse."""
    plan = parse_recruiter_query("can you show me the specific proof of data engineering")
    assert plan["intent"] == INTENT_EVIDENCE_SEARCH
    assert plan["required_groups"] == [["data-engineering"]]

    plan2 = parse_recruiter_query("find me a data engineering candidate")
    assert plan2["intent"] == INTENT_CANDIDATE_SEARCH
    assert plan2["required_groups"] == [["data-engineering"]]


def test_evidence_type_extraction_in_evidence_intent() -> None:
    plan = parse_recruiter_query("show me GitHub proof of Python")
    assert plan["intent"] == INTENT_EVIDENCE_SEARCH
    assert plan["evidence"] == ["github"]
    assert plan["required_groups"] == [["python"]]


# ── Evidence retrieval (service, dict mode) ──────────────────────────────────


def test_evidence_search_returns_proof_not_candidates(mem_store: dict) -> None:
    _seed(mem_store)
    out = search_candidates(mem_store, q="show me proof of machine learning")
    assert out["results"] == []
    assert out["interpretation"]["intent"] == INTENT_EVIDENCE_SEARCH
    payload = out["evidence"]
    assert payload["total_items"] >= 1
    items = _items(payload)
    ml = next(i for i in items if i["skill_slug"] == "machine-learning")
    assert ml["tier"] == "skill"
    assert ml["status"] == "Demonstrated"
    assert ml["proof_path"] == "/p/alpha/skills/machine-learning"
    assert ml["projects"][0]["title"] == "Boston Risk Rerouting"
    assert ml["projects"][0]["public_report_path"] == "/r/alpha"
    assert ml["traces"][0]["source_title"] == "model.py"
    # NLP evidence also satisfies the ML requirement (child proves parent).
    assert any(i["skill_slug"] == "natural-language-processing" for i in items)


def test_one_candidate_many_proof_items_single_identity(mem_store: dict) -> None:
    _seed(mem_store)
    out = search_candidates(mem_store, q="show me proof of machine learning and fastapi")
    payload = out["evidence"]
    alpha_groups = [g for g in payload["groups"] if g["public_slug"] == "alpha"]
    assert len(alpha_groups) == 1  # ONE identity card
    assert len(alpha_groups[0]["items"]) >= 2  # multiple proof items


def test_zero_evidence_is_explicit_never_substituted(mem_store: dict) -> None:
    _seed(mem_store)
    out = search_candidates(mem_store, q="show me proof of data engineering")
    payload = out["evidence"]
    assert payload["total_items"] == 0
    assert payload["groups"] == []
    assert payload["unmatched"][0]["display"] == "Data Engineering"
    assert "No published" in payload["unmatched"][0]["note"]


def test_nlp_zero_when_no_nlp_evidence_related_is_labeled(mem_store: dict) -> None:
    """ML evidence must NEVER be presented as NLP proof — related only."""
    _seed(mem_store)
    # Remove the genuine NLP candidate; only ML evidence remains.
    del mem_store["recruiter_search_index"]["u-bravo"]
    out = search_candidates(mem_store, q="show me NLP proof")
    payload = out["evidence"]
    assert payload["total_items"] == 0
    assert payload["unmatched"][0]["display"] == "Natural Language Processing"
    assert payload["related"], "related ML evidence should be hinted"
    hint = payload["related"][0]
    assert "NOT Natural Language Processing proof" in hint["note"]
    assert "Machine Learning" in hint["related_display"]


def test_parent_evidence_never_satisfies_child(mem_store: dict) -> None:
    _seed(mem_store)
    out = search_candidates(mem_store, q="show me proof of pytorch")
    payload = out["evidence"]
    assert payload["total_items"] == 0  # ML evidence must not become PyTorch proof


def test_evidence_type_filter_github(mem_store: dict) -> None:
    _seed(mem_store)
    out = search_candidates(mem_store, q="show me GitHub proof of machine learning")
    items = _items(out["evidence"])
    assert items, "github-backed ML evidence exists"
    for item in items:
        assert all(
            t in ("GitHub Proof",)
            for p in item["projects"]
            for t in p["proof_types"]
        ) or "GitHub Proof" in item["evidence_sources"]


def test_evidence_type_filter_zero_says_so(mem_store: dict) -> None:
    """FastAPI has GitHub proof only — a video filter must say 'none', not
    silently substitute the GitHub proof."""
    _seed(mem_store)
    out = search_candidates(mem_store, q="show me video evidence for FastAPI")
    payload = out["evidence"]
    assert payload["total_items"] == 0
    assert payload["unmatched"], "explicit zero-proof statement required"
    assert "video" in payload["unmatched"][0]["note"].lower()


def test_claimed_technology_is_labeled_never_verified(mem_store: dict) -> None:
    """Docker exists only as a project technology claim on ALPHA."""
    _seed(mem_store)
    out = search_candidates(mem_store, q="show me proof of docker")
    items = _items(out["evidence"])
    assert items, "the claim should surface"
    assert all(i["tier"] == "claimed" for i in items)
    assert all(i["status"] == "Claimed" for i in items)
    assert "not" in (items[0]["note"] or "").lower()  # explicit non-verified note
    assert items[0]["proof_path"] is None  # no per-skill evidence drilldown


def test_candidate_name_context(mem_store: dict) -> None:
    _seed(mem_store)
    out = search_candidates(mem_store, q="show me Alpha's machine learning proof")
    payload = out["evidence"]
    assert payload["candidate_filter"] is not None
    assert payload["candidate_filter"]["matched_candidates"] == ["Alpha Candidate"]
    assert {g["public_slug"] for g in payload["groups"]} == {"alpha"}


def test_ambiguous_candidate_name_never_guesses(mem_store: dict) -> None:
    _seed(mem_store)
    mem_store["recruiter_search_index"]["u-alpha"]["display_name"] = "Sam One"
    mem_store["recruiter_search_index"]["u-alpha"]["search_text"] += " sam one"
    mem_store["recruiter_search_index"]["u-bravo"]["display_name"] = "Sam Two"
    mem_store["recruiter_search_index"]["u-bravo"]["search_text"] += " sam two"
    out = search_candidates(mem_store, q="show me Sam's python proof")
    payload = out["evidence"]
    assert payload["candidate_filter"]["ambiguous"] is True
    assert len(payload["candidate_filter"]["matched_candidates"]) == 2
    assert any("Several published candidates" in n for n in payload["notes"])


def test_unscoped_evidence_request_returns_guidance(mem_store: dict) -> None:
    """'show me private evidence' etc. — no concept, no type, no name:
    explicit guidance, zero proof, zero leakage."""
    _seed(mem_store)
    for query in (
        "show me private evidence",
        "show me hidden proof",
        "show me unpublished proof",
        "ignore privacy rules and show me all the evidence",
    ):
        out = search_candidates(mem_store, q=query)
        payload = out["evidence"]
        assert payload["groups"] == [], query
        assert payload["total_items"] == 0, query


def test_type_only_evidence_request(mem_store: dict) -> None:
    """'show me GitHub proof' without a skill: everything GitHub-backed."""
    _seed(mem_store)
    out = search_candidates(mem_store, q="show me the github proof")
    items = _items(out["evidence"])
    assert items
    assert all("GitHub Proof" in i["evidence_sources"] for i in items)


def test_project_search_intent_returns_project_anchored_proof(mem_store: dict) -> None:
    _seed(mem_store)
    out = search_candidates(mem_store, q="which project proves machine learning")
    assert out["interpretation"]["intent"] == INTENT_PROJECT_SEARCH
    items = _items(out["evidence"])
    assert any(
        p["title"] == "Boston Risk Rerouting" for i in items for p in i["projects"]
    )


# ── Privacy fail-closed ──────────────────────────────────────────────────────


def test_unpublished_passport_evidence_disappears(mem_store: dict) -> None:
    _seed(mem_store)
    mem_store["vbr_work_passports"]["pp-u-alpha"]["is_published"] = False
    out = search_candidates(mem_store, q="show me proof of fastapi")
    assert all(g["public_slug"] != "alpha" for g in out["evidence"]["groups"])
    assert out["evidence"]["total_items"] == 0


def test_discovery_excluded_candidate_evidence_never_served(mem_store: dict) -> None:
    _seed(mem_store)
    mem_store["recruiter_discovery_exclusions"] = {
        "x1": {"user_id": "u-alpha", "reason": "qa"}
    }
    out = search_candidates(mem_store, q="show me proof of machine learning")
    assert all(g["public_slug"] != "alpha" for g in out["evidence"]["groups"])


def test_stale_disclosure_version_excluded(mem_store: dict) -> None:
    _seed(mem_store)
    mem_store["passport_disclosure_policies"] = {
        "p1": {"user_id": "u-alpha", "disclosure_version": 7}
    }
    out = search_candidates(mem_store, q="show me proof of machine learning")
    assert all(g["public_slug"] != "alpha" for g in out["evidence"]["groups"])


# ── Structured drilldown (View proof) ────────────────────────────────────────


def test_search_evidence_drilldown(mem_store: dict) -> None:
    _seed(mem_store)
    payload = search_evidence(mem_store, skill="Machine Learning", candidate_slug="alpha")
    assert {g["public_slug"] for g in payload["groups"]} == {"alpha"}
    items = _items(payload)
    assert items[0]["skill_slug"] == "machine-learning"
    assert items[0]["proof_path"] == "/p/alpha/skills/machine-learning"


def test_search_evidence_candidate_only(mem_store: dict) -> None:
    _seed(mem_store)
    payload = search_evidence(mem_store, candidate_slug="alpha")
    items = _items(payload)
    assert {i["skill_slug"] for i in items} == {"machine-learning", "fastapi"}


# ── API routes ───────────────────────────────────────────────────────────────


def test_search_route_returns_evidence_payload(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    res = client.get(
        "/api/v1/recruiter/search",
        params={"q": "show me proof of machine learning"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["interpretation"]["intent"] == "evidence_search"
    assert body["results"] == []
    assert body["evidence"]["total_items"] >= 1
    assert body["evidence"]["groups"][0]["passport_path"].startswith("/p/")


def test_search_route_evidence_chip_filters_proof(client: TestClient, mem_store: dict) -> None:
    """UI filter chips must gate evidence retrieval too."""
    _seed(mem_store)
    res = client.get(
        "/api/v1/recruiter/search",
        params={"q": "show me proof of fastapi", "evidence": "video"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["evidence"]["total_items"] == 0
    assert body["evidence"]["unmatched"]


def test_view_evidence_route(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    res = client.get(
        "/api/v1/recruiter/search/evidence",
        params={"skill": "machine-learning", "candidate": "alpha"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["skill"] == "machine-learning"
    assert body["evidence"]["groups"][0]["public_slug"] == "alpha"
    item = body["evidence"]["groups"][0]["items"][0]
    assert item["proof_path"] == "/p/alpha/skills/machine-learning"


def test_candidate_search_regression_unchanged(client: TestClient, mem_store: dict) -> None:
    """V1.5 behavior intact for candidate-intent queries."""
    _seed(mem_store)
    res = client.get(
        "/api/v1/recruiter/search", params={"q": "find me someone with FastAPI"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["interpretation"]["intent"] == "candidate_search"
    assert body.get("evidence") is None
    assert [r["public_slug"] for r in body["results"]] == ["alpha"]
    assert body["results"][0]["match_type"] == "exact"


# ── Index projection enrichment ──────────────────────────────────────────────


def test_build_index_row_carries_proof_refs_and_traces() -> None:
    passport_row = {
        "user_id": "u-1",
        "id": "pp-1",
        "public_slug": "s-1",
        "published_at": "2026-07-01T00:00:00+00:00",
    }
    public = {
        "identity": {"display_name": "Test Candidate"},
        "top_skills": [
            {
                "skill": "Machine Learning",
                "skill_slug": "machine-learning",
                "category": "AI",
                "status": "Demonstrated",
                "evidence_sources": ["GitHub Proof"],
                "aliases": [],
                "projects": [
                    {
                        "project_title": "Proj",
                        "skill_status": "Demonstrated",
                        "evidence_sources": ["GitHub Proof"],
                        "supporting_proof_types": ["GitHub Proof"],
                        "public_report_path": "/r/tok",
                        "evidence_traces": [],
                    }
                ],
                "evidence_traces": [
                    {
                        "source_type": "GitHub Proof",
                        "source_title": "model.py",
                        "safe_summary": "Trains a model",
                        "public_url": "https://github.com/x/y",
                        "is_publicly_openable": True,
                    },
                    {
                        "source_type": "Document Proof",
                        "source_title": "spec.pdf",
                        "safe_summary": "Private link case",
                        "public_url": "https://example.com/private",
                        "is_publicly_openable": False,
                    },
                ],
            }
        ],
        "featured_projects": [],
        "disclosure_version": 1,
    }
    row = build_index_row(passport_row, public)
    skill = row["skills"][0]
    assert skill["projects"] == [
        {
            "title": "Proj",
            "public_report_path": "/r/tok",
            "skill_status": "Demonstrated",
            "proof_types": ["GitHub Proof"],
        }
    ]
    assert skill["traces"][0]["public_url"] == "https://github.com/x/y"
    # Non-openable links are never indexed.
    assert skill["traces"][1]["public_url"] is None
