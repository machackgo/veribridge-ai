"""Recruiter Talent Pool WORKSPACE (V6, migration 072).

Covers the four things that turn a pool from a collection into a workspace:

  * pool-scoped workflow STATUS (review / shortlisted / interview / hold /
    pass) and recruiter-private TAGS,
  * pool-scoped EVIDENCE FILTERING through the shared search engine,
  * pool-scoped COMPARISON with a derived evidence axis,
  * and — running through all of it — the invariant that recruiter judgement
    is never evidence and never leaks between recruiters.

Fixture corpus (three published candidates):

    alpha    Python (Demonstrated) + FastAPI (Demonstrated), GitHub + live site
    bravo    Python (Evidence observed), GitHub only
    charlie  Docker (Demonstrated), GitHub only
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.services.recruiter_talent_pool_service import (
    MAX_TAGS_PER_CANDIDATE,
    POOL_CANDIDATE_STATUSES,
)

RECRUITER_A = "00000000-0000-4000-8000-0000000000a1"
RECRUITER_B = "00000000-0000-4000-8000-0000000000b2"

API = "/api/v1/recruiter/pools"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict):
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: mem_store
    app.dependency_overrides[get_current_user_id] = lambda: RECRUITER_A
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _as_user(user_id: str) -> None:
    app.dependency_overrides[get_current_user_id] = lambda: user_id


# ── Fixture corpus ───────────────────────────────────────────────────────────


def _skill(name: str, slug: str, status: str, sources: list[str], **extra) -> dict:
    return {
        "skill": name,
        "skill_slug": slug,
        "category": "",
        "status": status,
        "evidence_sources": sources,
        "aliases": [],
        "projects": extra.get("projects", []),
        "traces": extra.get("traces", []),
    }


def _row(uid, slug, name, *, skills, flags=None) -> dict:
    evidence_flags = {
        "github": True,
        "live_site": False,
        "documents": False,
        "project_defense": False,
        "video": False,
    }
    evidence_flags.update(flags or {})
    return {
        "user_id": uid,
        "passport_id": f"pp-{uid}",
        "public_slug": slug,
        "display_name": name,
        "headline": None,
        "location": None,
        "availability": None,
        "availability_label": None,
        "institution": None,
        "degree": None,
        "graduation_year": None,
        "role_areas": [],
        "skills": skills,
        "projects": [
            {
                "title": f"{name} Capstone",
                "summary": "",
                "technologies": [],
                "evidence_sources": ["GitHub Proof"],
                "public_report_path": f"/r/{slug}",
                "has_live_url": bool(evidence_flags["live_site"]),
                "has_github_repo": True,
            }
        ],
        "evidence_flags": evidence_flags,
        "skill_count": len(skills),
        "project_count": 1,
        "text_skills": " ".join(s["skill"] for s in skills).lower(),
        "text_profile": name.lower(),
        "text_projects": "capstone",
        "text_meta": "",
        "search_text": " ".join([s["skill"] for s in skills] + [name]).lower(),
        "disclosure_version": 1,
        "passport_published_at": "2026-07-01T00:00:00+00:00",
        "projected_at": "2026-08-18T00:00:00+00:00",
    }


def _seed(mem_store: dict) -> None:
    rows = [
        _row(
            "u-alpha", "alpha", "Alpha Candidate",
            skills=[
                _skill(
                    "Python", "python", "Demonstrated", ["GitHub Proof"],
                    projects=[
                        {
                            "title": "Boston Rerouting",
                            "public_report_path": "/r/alpha",
                            "skill_status": "Demonstrated",
                            "proof_types": ["GitHub Proof", "Website Proof"],
                        }
                    ],
                    traces=[
                        {
                            "source_type": "GitHub Proof",
                            "source_title": "router.py",
                            "summary": "Routing service implementation",
                            "public_url": "/r/alpha#github",
                        }
                    ],
                ),
                _skill("FastAPI", "fastapi", "Demonstrated", ["GitHub Proof"]),
            ],
            flags={"live_site": True},
        ),
        _row(
            "u-bravo", "bravo", "Bravo Candidate",
            skills=[_skill("Python", "python", "Evidence observed", ["GitHub Proof"])],
        ),
        _row(
            "u-charlie", "charlie", "Charlie Candidate",
            skills=[_skill("Docker", "docker", "Demonstrated", ["GitHub Proof"])],
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
    mem_store["passport_profiles"] = {
        f"profile-{r['user_id']}": {
            "id": f"profile-{r['user_id']}",
            "user_id": r["user_id"],
            "full_name": r["display_name"],
            "preferred_name": None,
            "headline": "Student engineer",
            "bio": None,
            "institution": None,
            "degree": None,
            "graduation_year": None,
            "location": None,
            "github_url": None,
            "linkedin_url": None,
            "portfolio_url": None,
            "role_areas": [],
            "availability": None,
            "work_authorization_note": None,
            "show_location": False,
            "show_availability": False,
            "show_links": False,
            "show_work_authorization": False,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        for r in rows
    }


def _pool(client: TestClient, name="Fall 2026 — AI / ML") -> str:
    res = client.post(API, json={"name": name})
    assert res.status_code == 200, res.text
    return res.json()["pool"]["id"]


def _fill(client: TestClient, pool_id: str, slugs=("alpha", "bravo", "charlie")) -> None:
    res = client.post(
        f"{API}/{pool_id}/candidates", json={"candidate_slugs": list(slugs)}
    )
    assert res.status_code == 200, res.text


def _detail(client: TestClient, pool_id: str) -> dict:
    res = client.get(f"{API}/{pool_id}")
    assert res.status_code == 200, res.text
    return res.json()


def _by_id(payload: dict) -> dict:
    return {c["student_user_id"]: c for c in payload["candidates"]}


# ── Workflow status ──────────────────────────────────────────────────────────


def test_new_members_default_to_review_not_a_judgement(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id)
    payload = _detail(client, pool_id)
    assert {c["status"] for c in payload["candidates"]} == {"review"}
    assert payload["status_counts"]["review"] == 3
    assert payload["status_counts"]["shortlisted"] == 0


@pytest.mark.parametrize("status", POOL_CANDIDATE_STATUSES)
def test_every_status_in_the_closed_vocabulary_round_trips(client, mem_store, status):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id, slugs=("alpha",))
    res = client.patch(
        f"{API}/{pool_id}/candidates/u-alpha", json={"status": status}
    )
    assert res.status_code == 200, res.text
    assert res.json()["candidate"]["status"] == status
    assert _by_id(_detail(client, pool_id))["u-alpha"]["status"] == status


def test_unknown_status_is_rejected(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id, slugs=("alpha",))
    res = client.patch(
        f"{API}/{pool_id}/candidates/u-alpha", json={"status": "hired"}
    )
    assert res.status_code == 422, res.text


def test_status_is_pool_scoped_not_a_property_of_the_candidate(client, mem_store):
    """Passing someone in one pool says nothing about them in another."""
    _seed(mem_store)
    first = _pool(client, "Fall 2026 — AI / ML")
    second = _pool(client, "Backend Interns")
    _fill(client, first, slugs=("alpha",))
    _fill(client, second, slugs=("alpha",))

    client.patch(f"{API}/{first}/candidates/u-alpha", json={"status": "pass"})

    assert _by_id(_detail(client, first))["u-alpha"]["status"] == "pass"
    assert _by_id(_detail(client, second))["u-alpha"]["status"] == "review"


def test_status_change_never_touches_evidence_or_the_passport(client, mem_store):
    _seed(mem_store)
    before = json.dumps(mem_store["recruiter_search_index"], sort_keys=True)
    passports_before = json.dumps(mem_store["vbr_work_passports"], sort_keys=True)
    pool_id = _pool(client)
    _fill(client, pool_id, slugs=("alpha",))

    client.patch(
        f"{API}/{pool_id}/candidates/u-alpha",
        json={"status": "shortlisted", "note": "Excellent backend candidate",
              "tags": ["Backend", "Career Fair"]},
    )

    assert json.dumps(mem_store["recruiter_search_index"], sort_keys=True) == before
    assert json.dumps(mem_store["vbr_work_passports"], sort_keys=True) == passports_before
    card = _by_id(_detail(client, pool_id))["u-alpha"]
    # Evidence is unchanged and still exactly the public projection.
    assert card["evidence"]["skill_count"] == 2
    assert sorted(card["evidence"]["top_skills"]) == ["FastAPI", "Python"]


def test_recruiter_note_never_becomes_evidence_text(client, mem_store):
    """A recruiter's opinion must not end up anywhere searchable."""
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id, slugs=("alpha",))
    client.patch(
        f"{API}/{pool_id}/candidates/u-alpha",
        json={"note": "Kubernetes wizard", "tags": ["Kubernetes"]},
    )
    index_blob = json.dumps(mem_store["recruiter_search_index"]).lower()
    assert "kubernetes" not in index_blob
    # …and the pool filter refuses to invent the skill from the note/tag.
    res = client.get(f"{API}/{pool_id}/filter", params={"q": "kubernetes"})
    assert res.status_code == 200, res.text
    assert res.json()["candidates"] == []


# ── Tags ─────────────────────────────────────────────────────────────────────


def test_tags_are_recruiter_scoped_and_travel_across_pools(client, mem_store):
    _seed(mem_store)
    first = _pool(client, "Career Fair")
    second = _pool(client, "Backend")
    _fill(client, first, slugs=("alpha",))
    _fill(client, second, slugs=("alpha",))

    client.patch(f"{API}/{first}/candidates/u-alpha", json={"tags": ["Backend", "Follow up"]})

    assert _by_id(_detail(client, first))["u-alpha"]["tags"] == ["Backend", "Follow up"]
    assert _by_id(_detail(client, second))["u-alpha"]["tags"] == ["Backend", "Follow up"]


def test_tags_dedupe_case_insensitively(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id, slugs=("alpha",))
    res = client.patch(
        f"{API}/{pool_id}/candidates/u-alpha",
        json={"tags": ["Backend", "backend", "BACK END", "  Backend  "]},
    )
    assert res.status_code == 200, res.text
    # "Backend"/"backend"/"  Backend  " collapse; "BACK END" is a different word.
    assert res.json()["candidate"]["tags"] == ["BACK END", "Backend"]


def test_setting_tags_replaces_the_set(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id, slugs=("alpha",))
    client.patch(f"{API}/{pool_id}/candidates/u-alpha", json={"tags": ["A", "B"]})
    res = client.patch(f"{API}/{pool_id}/candidates/u-alpha", json={"tags": ["B", "C"]})
    assert res.json()["candidate"]["tags"] == ["B", "C"]


def test_omitting_tags_leaves_them_unchanged(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id, slugs=("alpha",))
    client.patch(f"{API}/{pool_id}/candidates/u-alpha", json={"tags": ["Keep"]})
    res = client.patch(f"{API}/{pool_id}/candidates/u-alpha", json={"status": "hold"})
    assert res.json()["candidate"]["tags"] == ["Keep"]


def test_tag_count_is_capped(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id, slugs=("alpha",))
    res = client.patch(
        f"{API}/{pool_id}/candidates/u-alpha",
        json={"tags": [f"tag-{i}" for i in range(MAX_TAGS_PER_CANDIDATE + 1)]},
    )
    assert res.status_code == 400, res.text
    assert res.json()["detail"]["code"] == "too_many_tags"


def test_tag_vocabulary_lists_only_the_callers_tags(client, mem_store):
    _seed(mem_store)
    pool_a = _pool(client, "A pool")
    _fill(client, pool_a, slugs=("alpha", "bravo"))
    client.patch(f"{API}/{pool_a}/candidates/u-alpha", json={"tags": ["Backend"]})
    client.patch(f"{API}/{pool_a}/candidates/u-bravo", json={"tags": ["Backend", "ML"]})

    res = client.get(f"{API}/tags")
    assert res.status_code == 200, res.text
    vocab = {t["tag"]: t["candidate_count"] for t in res.json()["tags"]}
    assert vocab == {"Backend": 2, "ML": 1}

    _as_user(RECRUITER_B)
    assert client.get(f"{API}/tags").json()["tags"] == []


def test_long_and_special_character_tags_are_bounded(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id, slugs=("alpha",))
    res = client.patch(
        f"{API}/{pool_id}/candidates/u-alpha",
        json={"tags": ["x" * 200, "<script>alert(1)</script>", "   ", "café ☕"]},
    )
    assert res.status_code == 200, res.text
    tags = res.json()["candidate"]["tags"]
    assert all(len(t) <= 40 for t in tags)
    assert "" not in tags
    # Stored verbatim as data — never interpreted, never turned into evidence.
    assert "café ☕" in tags


# ── Pool-scoped evidence filtering ───────────────────────────────────────────


def test_no_filter_returns_the_whole_pool(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id)
    res = client.get(f"{API}/{pool_id}/filter")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 3
    assert body["pool_total"] == 3
    assert all(c["match"] is None for c in body["candidates"])


def test_skill_filter_is_evidence_grounded(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id)
    res = client.get(f"{API}/{pool_id}/filter", params={"q": "Show candidates with FastAPI"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert [c["student_user_id"] for c in body["candidates"]] == ["u-alpha"]
    match = body["candidates"][0]["match"]
    assert match["match_type"] == "exact"
    # The reason is inspectable evidence, not prose.
    assert any(
        r.get("requirement") == "fastapi" or "FastAPI" in str(r.get("display"))
        for r in match["requirements"]
    )


def test_filter_combines_skill_and_proof_source(client, mem_store):
    """'FastAPI and deployed website evidence' — alpha only."""
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id)
    res = client.get(
        f"{API}/{pool_id}/filter",
        params={"q": "candidates with FastAPI", "evidence": "live_site"},
    )
    assert [c["student_user_id"] for c in res.json()["candidates"]] == ["u-alpha"]

    # bravo has Python but no live site: the proof-source gate excludes them.
    res = client.get(
        f"{API}/{pool_id}/filter",
        params={"q": "candidates with Python", "evidence": "live_site"},
    )
    assert [c["student_user_id"] for c in res.json()["candidates"]] == ["u-alpha"]


def test_filter_never_fabricates_a_match(client, mem_store):
    """Prefer an honest empty result over a fuzzy near-miss."""
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id)
    res = client.get(f"{API}/{pool_id}/filter", params={"q": "Rust systems programming"})
    assert res.status_code == 200, res.text
    assert res.json()["candidates"] == []


def test_filter_cannot_reach_outside_the_pool(client, mem_store):
    """Non-members never appear, even when they satisfy the query better."""
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id, slugs=("bravo",))  # alpha and charlie stay OUT

    # Both alpha and bravo have Python evidence; only bravo is in this pool.
    res = client.get(f"{API}/{pool_id}/filter", params={"q": "candidates with Python"})
    assert res.status_code == 200, res.text
    ids = [c["student_user_id"] for c in res.json()["candidates"]]
    assert ids == ["u-bravo"]

    # An evidence-discovery-shaped phrase stays a pool-scoped candidate
    # filter and can never become the global proof-search payload.
    res = client.get(f"{API}/{pool_id}/filter", params={"q": "show me proof of Python"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert [c["student_user_id"] for c in body["candidates"]] == ["u-bravo"]
    assert "evidence" not in body


def test_filter_by_recruiter_status_and_tags(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id)
    client.patch(f"{API}/{pool_id}/candidates/u-alpha", json={"status": "shortlisted", "tags": ["Backend"]})
    client.patch(f"{API}/{pool_id}/candidates/u-bravo", json={"tags": ["Backend"]})

    res = client.get(f"{API}/{pool_id}/filter", params={"candidate_status": "shortlisted"})
    assert [c["student_user_id"] for c in res.json()["candidates"]] == ["u-alpha"]

    res = client.get(f"{API}/{pool_id}/filter", params={"tags": "Backend"})
    assert {c["student_user_id"] for c in res.json()["candidates"]} == {"u-alpha", "u-bravo"}

    # Tag filter is AND across tags.
    res = client.get(f"{API}/{pool_id}/filter", params={"tags": "Backend,Missing"})
    assert res.json()["candidates"] == []


def test_recruiter_and_evidence_filters_compose(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id)
    client.patch(f"{API}/{pool_id}/candidates/u-bravo", json={"status": "shortlisted"})
    res = client.get(
        f"{API}/{pool_id}/filter",
        params={"q": "FastAPI", "candidate_status": "shortlisted"},
    )
    # bravo is shortlisted but has no FastAPI evidence → honest empty result.
    assert res.json()["candidates"] == []


def test_unpublished_members_are_excluded_and_counted_honestly(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id)
    mem_store["vbr_work_passports"]["pp-u-bravo"]["is_published"] = False

    res = client.get(f"{API}/{pool_id}/filter", params={"q": "Python"})
    body = res.json()
    assert [c["student_user_id"] for c in body["candidates"]] == ["u-alpha"]
    assert body["unavailable_excluded"] == 1

    # Without an evidence filter they are still in the pool, just gone dark.
    res = client.get(f"{API}/{pool_id}/filter")
    dark = _by_id(res.json())["u-bravo"]
    assert dark["evidence"] is None
    assert dark["candidate"]["is_published"] is False


def test_filter_surfaces_unrecognized_terms(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id)
    res = client.get(f"{API}/{pool_id}/filter", params={"q": "candidates with Python"})
    assert res.json()["interpretation"] is not None


def test_filter_is_recruiter_isolated(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id)
    _as_user(RECRUITER_B)
    assert client.get(f"{API}/{pool_id}/filter").status_code == 404


# ── Comparison ───────────────────────────────────────────────────────────────


def test_comparison_derives_its_axis_from_published_evidence(client, mem_store):
    """A pool owns no requirement plan, so with no query the axis is what the
    SELECTED candidates have themselves published."""
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id)
    res = client.post(
        f"{API}/{pool_id}/comparison",
        json={"student_user_ids": ["u-alpha", "u-charlie"]},
    )
    assert res.status_code == 200, res.text
    matrix = res.json()["matrix"]
    displays = {r["display"] for r in matrix["requirements"]}
    assert {"Python", "FastAPI", "Docker"} <= displays
    assert all(r["origin"] == "observed" for r in matrix["requirements"])
    assert all(r["required"] is False for r in matrix["requirements"])
    # Never described as things the recruiter asked for.
    joined = " ".join(matrix["summaries"]).lower()
    assert "required" not in joined
    assert "preferred" not in joined


def test_comparison_preserves_evidence_states_not_checkmarks(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id)
    res = client.post(
        f"{API}/{pool_id}/comparison",
        json={"student_user_ids": ["u-alpha", "u-charlie"]},
    )
    matrix = res.json()["matrix"]
    columns = {c["user_id"]: c for c in matrix["columns"]}
    python_key = next(r["key"] for r in matrix["requirements"] if r["display"] == "Python")

    assert columns["u-alpha"]["cells"][python_key]["state"] == "proven"
    # Charlie has no Python evidence — stated as absence, never as a verdict.
    charlie_cell = columns["u-charlie"]["cells"][python_key]
    assert charlie_cell["state"] == "none"
    assert "No published" in (charlie_cell["note"] or "")
    # Qualitative verification state survives; it is not flattened to a tick.
    assert columns["u-alpha"]["cells"][python_key]["skill_status"] == "Demonstrated"


def test_comparison_cells_carry_the_full_proof_trail(client, mem_store):
    """SUMMARY → CLAIM → PROJECT → PROOF must stay navigable."""
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id)
    res = client.post(
        f"{API}/{pool_id}/comparison",
        json={"student_user_ids": ["u-alpha", "u-bravo"]},
    )
    matrix = res.json()["matrix"]
    alpha = next(c for c in matrix["columns"] if c["user_id"] == "u-alpha")
    python_key = next(r["key"] for r in matrix["requirements"] if r["display"] == "Python")
    cell = alpha["cells"][python_key]

    assert cell["proof_path"] == "/p/alpha/skills/python"          # skill report
    assert cell["projects"][0]["title"] == "Boston Rerouting"      # project
    assert cell["projects"][0]["public_report_path"] == "/r/alpha" # verified report
    assert cell["traces"][0]["source_type"] == "GitHub Proof"      # underlying proof
    assert cell["traces"][0]["public_url"] == "/r/alpha#github"
    assert alpha["passport_path"] == "/p/alpha"


def test_comparison_accepts_a_query_as_the_axis(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id)
    res = client.post(
        f"{API}/{pool_id}/comparison",
        json={"student_user_ids": ["u-alpha", "u-bravo"], "q": "FastAPI and Python"},
    )
    matrix = res.json()["matrix"]
    assert any(r["origin"] == "plan" and r["required"] for r in matrix["requirements"])
    bravo = next(c for c in matrix["columns"] if c["user_id"] == "u-bravo")
    assert "FastAPI" in bravo["missing_required"]


def test_comparison_requires_two_to_five_candidates(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id)
    res = client.post(f"{API}/{pool_id}/comparison", json={"student_user_ids": ["u-alpha"]})
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "too_few_candidates"

    res = client.post(
        f"{API}/{pool_id}/comparison",
        json={"student_user_ids": ["u-a", "u-b", "u-c", "u-d", "u-e", "u-f"]},
    )
    assert res.status_code == 422  # schema cap


def test_comparison_rejects_candidates_outside_this_pool(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id, slugs=("alpha", "bravo"))
    res = client.post(
        f"{API}/{pool_id}/comparison",
        json={"student_user_ids": ["u-alpha", "u-charlie"]},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "candidate_not_found"


def test_comparison_shows_unavailable_candidates_instead_of_hiding_them(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id)
    mem_store["vbr_work_passports"]["pp-u-bravo"]["is_published"] = False
    res = client.post(
        f"{API}/{pool_id}/comparison",
        json={"student_user_ids": ["u-alpha", "u-bravo"]},
    )
    matrix = res.json()["matrix"]
    bravo = next(c for c in matrix["columns"] if c["user_id"] == "u-bravo")
    assert bravo["available"] is False
    assert bravo["cells"] == {}
    assert "no longer publicly available" in (bravo["unavailable_note"] or "")


def test_comparison_carries_pool_workflow_metadata_separately(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id)
    client.patch(
        f"{API}/{pool_id}/candidates/u-alpha",
        json={"status": "shortlisted", "note": "Strong walkthrough", "tags": ["Backend"]},
    )
    res = client.post(
        f"{API}/{pool_id}/comparison",
        json={"student_user_ids": ["u-alpha", "u-bravo"]},
    )
    alpha = next(c for c in res.json()["matrix"]["columns"] if c["user_id"] == "u-alpha")
    assert alpha["pool_status"] == "shortlisted"
    assert alpha["pool_note"] == "Strong walkthrough"
    assert alpha["tags"] == ["Backend"]
    # …and it never contaminates the evidence cells or counts.
    assert "Strong walkthrough" not in json.dumps(alpha["cells"])
    assert "Backend" not in json.dumps(alpha["counts"])


def test_comparison_is_recruiter_isolated(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id)
    _as_user(RECRUITER_B)
    res = client.post(
        f"{API}/{pool_id}/comparison",
        json={"student_user_ids": ["u-alpha", "u-bravo"]},
    )
    assert res.status_code == 404


# ── The no-scores sweep ──────────────────────────────────────────────────────


def test_no_scores_percentages_or_rankings_anywhere_in_v6_payloads(client, mem_store):
    _seed(mem_store)
    pool_id = _pool(client)
    _fill(client, pool_id)
    client.patch(f"{API}/{pool_id}/candidates/u-alpha", json={"status": "shortlisted", "tags": ["Backend"]})

    blobs = [
        client.get(f"{API}/{pool_id}").text,
        client.get(f"{API}/{pool_id}/filter", params={"q": "Python"}).text,
        client.get(f"{API}/tags").text,
        client.post(
            f"{API}/{pool_id}/comparison",
            json={"student_user_ids": ["u-alpha", "u-bravo"]},
        ).text,
    ]
    banned = (
        '"score"', '"rating"', '"rank"', '"percent"', '"match_percentage"',
        '"employability"', '"best_candidate"', '"fit_score"',
    )
    for blob in blobs:
        lowered = blob.lower()
        for token in banned:
            assert token not in lowered, f"{token} leaked into a recruiter payload"


def test_cross_recruiter_metadata_is_invisible(client, mem_store):
    """Recruiter B must not see A's status, notes, or tags for a shared candidate."""
    _seed(mem_store)
    pool_a = _pool(client, "A pool")
    _fill(client, pool_a, slugs=("alpha",))
    client.patch(
        f"{API}/{pool_a}/candidates/u-alpha",
        json={"status": "pass", "note": "A's private note", "tags": ["A-only"]},
    )

    _as_user(RECRUITER_B)
    pool_b = _pool(client, "B pool")
    _fill(client, pool_b, slugs=("alpha",))
    card = _by_id(_detail(client, pool_b))["u-alpha"]

    assert card["status"] == "review"
    assert card["note"] is None
    assert card["tags"] == []
    assert "A's private note" not in _detail(client, pool_b).__str__()
