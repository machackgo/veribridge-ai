"""Recruiter Search & Discovery tests (migration 066).

Covers:
  * Search requires authentication (401 without a token).
  * The index row is derived from the real public passport projection:
    publishing a full project makes the candidate discoverable with their
    actual evidence-backed skills; unpublishing removes them.
  * Disclosure changes re-project immediately (hook), and a stale row whose
    recorded disclosure_version is behind the live policy is excluded at
    query time (fail closed).
  * Live is_published is re-checked at query time — an index row whose
    passport has since been unpublished is never served.
  * Refresh failures delete the row (fail closed), never leave stale data.
  * Deterministic explainable ranking: evidence-backed skill matches beat
    claimed project technologies beat profile prose; statuses and evidence
    provenance strengthen matches; ties are stable.
  * Structured filters (skills / evidence / availability), pagination,
    validation limits, malicious input safety, zero-result honesty.
  * Match explanations trace back to real indexed public data.
  * Search events are recorded coarsely (recruiter-authored inputs only).
  * A search result can be saved through the EXISTING connection system
    with source="search".

All storage is in-memory (dict mode). No network / LLM calls.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.services.recruiter_search_service import (
    build_index_row,
    rebuild_search_index,
    refresh_search_projection,
    search_candidates,
    tokenize_query,
)
from tests.test_vbr_project_defense import USER_ID
from tests.test_vbr_work_passport import (
    _make_full_project,
    _publish,
    _publish_project_report,
)

RECRUITER_ID = "00000000-0000-0000-0000-0000000000a1"

SEARCH_URL = "/api/v1/recruiter/search"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def pipeline_db() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict, pipeline_db: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: RECRUITER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: pipeline_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def owner_client(mem_store: dict, pipeline_db: dict) -> TestClient:
    """Client authenticated as the passport-owning student."""
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: pipeline_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as_user(user_id: str) -> None:
    app.dependency_overrides[get_current_user_id] = lambda: user_id


# ── Synthetic candidate fixtures ─────────────────────────────────────────────
#
# Hand-seeded index rows exercise build_index_row from a synthetic PUBLIC
# projection payload (the exact shape build_public_passport serves), plus a
# real published vbr_work_passports row so the live re-validation passes.
# The full-pipeline integration test below proves the same machinery against
# the genuine projection.


def _public_projection(
    *,
    name: str,
    headline: str,
    skills: list[dict],
    projects: list[dict],
    availability_label: str | None = None,
    institution: str | None = None,
    degree: str | None = None,
    location: str | None = None,
    role_areas: list[str] | None = None,
    disclosure_version: int = 1,
) -> dict:
    return {
        "identity": {
            "display_name": name,
            "headline": headline,
            "institution": institution,
            "degree": degree,
            "graduation_year": 2026,
            "location": location,
            "availability_label": availability_label,
            "role_areas": role_areas or [],
            "bio": None,
            "program": None,
            "education_summary": " ".join(p for p in [degree, institution] if p),
        },
        "top_skills": skills,
        "featured_projects": projects,
        "disclosure_version": disclosure_version,
    }


def _skill(name: str, status: str, sources: list[str]) -> dict:
    return {
        "skill": name,
        "skill_slug": name.lower().replace(" ", "-"),
        "category": "technical",
        "status": status,
        "evidence_sources": sources,
        "aliases": [],
    }


def _project(
    title: str,
    summary: str,
    technologies: list[str],
    sources: list[str],
    *,
    live_url: str | None = None,
    github_repo_url: str | None = None,
) -> dict:
    return {
        "project_title": title,
        "project_summary": summary,
        "claimed_skills": technologies,
        "evidence_sources": sources,
        "public_report_path": f"/vbr/report/{uuid4().hex[:12]}",
        "live_url": live_url,
        "github_repo_url": github_repo_url,
    }


def _seed_candidate(
    store: dict,
    user_id: str,
    slug: str,
    public: dict,
    *,
    is_published: bool = True,
    published_at: str = "2026-06-01T00:00:00+00:00",
) -> dict:
    passport = {
        "id": str(uuid4()),
        "user_id": user_id,
        "public_slug": slug,
        "headline": None,
        "summary": None,
        "is_published": is_published,
        "published_at": published_at,
        "created_at": published_at,
        "updated_at": published_at,
    }
    store.setdefault("vbr_work_passports", {})[passport["id"]] = passport
    row = build_index_row(passport, public)
    store.setdefault("recruiter_search_index", {})[user_id] = row
    return row


def _seed_matrix(store: dict) -> None:
    """Candidates A–F with deliberately overlapping attributes."""
    _seed_candidate(
        store,
        "aaaaaaaa-0000-0000-0000-000000000001",
        "cand-a",
        _public_projection(
            name="Ava Ramirez",
            headline="Backend Engineer",
            availability_label="Seeking full-time roles",
            institution="WPI",
            degree="M.S. Computer Science",
            location="Boston, MA",
            role_areas=["Backend"],
            skills=[
                _skill("Python", "Demonstrated", ["GitHub Proof", "Website Proof"]),
                _skill("FastAPI", "Evidence observed", ["GitHub Proof"]),
            ],
            projects=[
                _project(
                    "Deployment API",
                    "A production FastAPI service deployed to the cloud.",
                    ["Python", "FastAPI", "PostgreSQL"],
                    ["GitHub Proof", "Website Proof", "Project Defense"],
                    live_url="https://api.example.com",
                    github_repo_url="https://github.com/ava/deployment-api",
                )
            ],
        ),
        published_at="2026-06-03T00:00:00+00:00",
    )
    _seed_candidate(
        store,
        "bbbbbbbb-0000-0000-0000-000000000002",
        "cand-b",
        _public_projection(
            name="Ben Osei",
            headline="ML Engineer",
            availability_label="Seeking internship",
            institution="MIT",
            degree="B.S. Computer Science",
            skills=[
                _skill("Python", "Evidence observed", ["GitHub Proof"]),
                _skill("PyTorch", "Demonstrated", ["GitHub Proof"]),
            ],
            projects=[
                _project(
                    "Vision Classifier",
                    "An image classification model trained with PyTorch.",
                    ["Python", "PyTorch"],
                    ["GitHub Proof"],
                )
            ],
        ),
        published_at="2026-06-02T00:00:00+00:00",
    )
    _seed_candidate(
        store,
        "cccccccc-0000-0000-0000-000000000003",
        "cand-c",
        _public_projection(
            name="Cara Lin",
            headline="Frontend Engineer",
            availability_label="Open to opportunities",
            skills=[
                _skill("React", "Demonstrated", ["GitHub Proof", "Website Proof"]),
                _skill("TypeScript", "Evidence observed", ["GitHub Proof"]),
            ],
            projects=[
                _project(
                    "Design System",
                    "A reusable React component library.",
                    ["React", "TypeScript"],
                    ["GitHub Proof", "Website Proof"],
                    live_url="https://design.example.com",
                )
            ],
        ),
        published_at="2026-06-01T00:00:00+00:00",
    )
    # D: Python appears only as a claimed project technology — no
    # evidence-backed passport skill.
    _seed_candidate(
        store,
        "dddddddd-0000-0000-0000-000000000004",
        "cand-d",
        _public_projection(
            name="Dev Patel",
            headline="CS Student",
            skills=[],
            projects=[
                _project(
                    "Course Scheduler",
                    "A scheduling tool for course selection.",
                    ["Python"],
                    ["Document Proof"],
                )
            ],
        ),
        published_at="2026-05-30T00:00:00+00:00",
    )
    # E: matching evidence exists but the passport is UNPUBLISHED — the index
    # row is seeded anyway to simulate the worst case (stale row), and the
    # live re-validation must exclude it.
    _seed_candidate(
        store,
        "eeeeeeee-0000-0000-0000-000000000005",
        "cand-e",
        _public_projection(
            name="Eve Stone",
            headline="Backend Engineer",
            skills=[_skill("Python", "Demonstrated", ["GitHub Proof"])],
            projects=[],
        ),
        is_published=False,
    )
    # F: published, but the LIVE disclosure_version (5) is ahead of the
    # indexed row (1) — the row may contain since-hidden data → excluded.
    _seed_candidate(
        store,
        "ffffffff-0000-0000-0000-000000000006",
        "cand-f",
        _public_projection(
            name="Finn Wolfe",
            headline="Backend Engineer",
            skills=[_skill("Python", "Demonstrated", ["GitHub Proof"])],
            projects=[],
        ),
    )
    store.setdefault("passport_disclosure_policies", {})["pol-f"] = {
        "id": "pol-f",
        "user_id": "ffffffff-0000-0000-0000-000000000006",
        "mode": "custom",
        "disclosure_version": 5,
    }


def _search(client: TestClient, **params):
    return client.get(SEARCH_URL, params=params)


def _slugs(body: dict) -> list[str]:
    return [r["public_slug"] for r in body["results"]]


# ── Auth ─────────────────────────────────────────────────────────────────────


def test_search_requires_authentication(mem_store: dict, pipeline_db: dict) -> None:
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: pipeline_db
    try:
        anonymous = TestClient(app)
        assert anonymous.get(SEARCH_URL).status_code == 401
    finally:
        app.dependency_overrides.clear()


# ── Projection sync (real pipeline) ──────────────────────────────────────────


def test_publish_projects_real_skills_and_unpublish_removes(
    owner_client: TestClient, mem_store: dict
) -> None:
    """Full pipeline → publish → the candidate is discoverable with their
    REAL evidence-backed skills; unpublish removes them from discovery."""
    project_id = _make_full_project(owner_client, mem_store)
    assert _publish_project_report(owner_client, project_id).status_code == 200
    assert _publish(owner_client).status_code == 200

    rows = list(mem_store.get("recruiter_search_index", {}).values())
    assert len(rows) == 1
    row = rows[0]
    skill_names = {s["skill"] for s in row["skills"]}
    assert "Python" in skill_names  # from the real defense/github evidence
    assert row["public_slug"]
    assert row["project_count"] >= 1

    # The searchable text mirrors the public projection — never auth ids or
    # emails.
    assert USER_ID not in row["search_text"]
    assert "@" not in row["search_text"]

    _as_user(RECRUITER_ID)
    found = search_candidates(mem_store, q="python")
    assert [r["public_slug"] for r in found["results"]] == [row["public_slug"]]

    # Unpublish → gone from discovery, row deleted.
    _as_user(USER_ID)
    assert owner_client.post("/api/v1/student/vbr/passport/unpublish").status_code == 200
    assert not mem_store.get("recruiter_search_index")
    assert search_candidates(mem_store, q="python")["total"] == 0


def test_disclosure_change_reprojects_immediately(
    owner_client: TestClient, mem_store: dict
) -> None:
    """Hiding a skill through the Privacy Center removes it from the search
    projection in the same request (hook), and bumps the recorded version."""
    project_id = _make_full_project(owner_client, mem_store)
    assert _publish_project_report(owner_client, project_id).status_code == 200
    assert _publish(owner_client).status_code == 200
    row = next(iter(mem_store["recruiter_search_index"].values()))
    assert any(s["skill"] == "Python" for s in row["skills"])

    assert (
        owner_client.put(
            "/api/v1/student/vbr/passport/disclosure/mode", json={"mode": "custom"}
        ).status_code
        == 200
    )
    response = owner_client.put(
        "/api/v1/student/vbr/passport/disclosure/overrides",
        json={
            "changes": [
                {
                    "resource_type": "skill",
                    "resource_key": "python",
                    "visibility": "hidden",
                }
            ]
        },
    )
    assert response.status_code == 200, response.text

    row = next(iter(mem_store["recruiter_search_index"].values()))
    assert all(s["skill"] != "Python" for s in row["skills"])
    assert "python" not in row["text_skills"].lower()
    found = search_candidates(mem_store, q="python")
    # The candidate may still match via claimed project technologies (which
    # remain public on the passport card), but never via the hidden skill.
    for result in found["results"]:
        assert all(r["type"] != "skill" or "python" not in r["label"].lower()
                   for r in result["matched_reasons"])
        assert all("python" not in (s["skill"] or "").lower() for s in result["skills"])


def test_refresh_failure_fails_closed(
    mem_store: dict, pipeline_db: dict, monkeypatch
) -> None:
    _seed_matrix(mem_store)
    uid = "aaaaaaaa-0000-0000-0000-000000000001"
    assert uid in mem_store["recruiter_search_index"]

    import app.services.vbr_work_passport_service as passport_service

    def _boom(*args, **kwargs):
        raise RuntimeError("projection unavailable")

    monkeypatch.setattr(passport_service, "build_public_passport", _boom)
    assert refresh_search_projection(mem_store, pipeline_db, uid) is False
    assert uid not in mem_store.get("recruiter_search_index", {})


def test_rebuild_search_index_refreshes_and_sweeps(
    owner_client: TestClient, mem_store: dict, pipeline_db: dict
) -> None:
    project_id = _make_full_project(owner_client, mem_store)
    assert _publish_project_report(owner_client, project_id).status_code == 200
    assert _publish(owner_client).status_code == 200
    # Orphan row whose owner has no published passport → swept.
    mem_store["recruiter_search_index"]["ghost"] = {
        "user_id": "99999999-0000-0000-0000-000000000009",
        "public_slug": "ghost",
        "search_text": "python",
        "skills": [],
        "projects": [],
        "disclosure_version": 1,
    }
    summary = rebuild_search_index(mem_store, pipeline_db)
    assert summary["refreshed"] == 1
    assert summary["removed"] == 1
    assert "ghost" not in mem_store["recruiter_search_index"]


# ── Query-time privacy (fail closed) ─────────────────────────────────────────


def test_unpublished_candidate_never_appears(client: TestClient, mem_store: dict) -> None:
    _seed_matrix(mem_store)
    body = _search(client, q="python").json()
    assert "cand-e" not in _slugs(body)
    # Even searching the candidate's exact name reveals nothing.
    assert _search(client, q="Eve Stone").json()["total"] == 0


def test_stale_disclosure_version_excluded(client: TestClient, mem_store: dict) -> None:
    _seed_matrix(mem_store)
    body = _search(client, q="python").json()
    assert "cand-f" not in _slugs(body)
    assert _search(client, q="Finn").json()["total"] == 0


def test_passport_unpublished_after_indexing_is_excluded(
    client: TestClient, mem_store: dict
) -> None:
    """Simulates a missed refresh: the passport flips private but the index
    row survives — the live re-check must still exclude the candidate."""
    _seed_matrix(mem_store)
    for row in mem_store["vbr_work_passports"].values():
        if row["public_slug"] == "cand-a":
            row["is_published"] = False
    body = _search(client, q="python").json()
    assert "cand-a" not in _slugs(body)


# ── Ranking + explanations ───────────────────────────────────────────────────


def test_evidence_backed_ranking_order(client: TestClient, mem_store: dict) -> None:
    """Demonstrated+evidence Python (A) > observed Python (B) > claimed-only
    technology Python (D); React-only C absent; E/F never appear."""
    _seed_matrix(mem_store)
    body = _search(client, q="python").json()
    assert _slugs(body) == ["cand-a", "cand-b", "cand-d"]

    reasons_a = body["results"][0]["matched_reasons"]
    skill_reason = next(r for r in reasons_a if r["type"] == "skill")
    assert skill_reason["label"] == "Python"
    assert skill_reason["skill_status"] == "Demonstrated"
    assert "GitHub Proof" in skill_reason["evidence_sources"]

    reasons_d = body["results"][2]["matched_reasons"]
    assert reasons_d[0]["type"] == "technology"
    assert reasons_d[0]["label"] == "Python"
    assert reasons_d[0]["project_title"] == "Course Scheduler"


def test_multi_term_query_prefers_fuller_matches(
    client: TestClient, mem_store: dict
) -> None:
    _seed_matrix(mem_store)
    body = _search(client, q="python fastapi").json()
    assert _slugs(body)[0] == "cand-a"
    labels = {r["label"] for r in body["results"][0]["matched_reasons"]}
    assert {"Python", "FastAPI"} <= labels


def test_explanations_trace_to_indexed_public_data(
    client: TestClient, mem_store: dict
) -> None:
    _seed_matrix(mem_store)
    body = _search(client, q="react frontend").json()
    result = next(r for r in body["results"] if r["public_slug"] == "cand-c")
    for reason in result["matched_reasons"]:
        assert reason["label"]
        if reason["type"] == "skill":
            assert reason["label"] in {s["skill"] for s in result["skills"]}
        if reason["type"] == "headline":
            assert reason["label"] == result["headline"]


def test_deterministic_ordering_and_tiebreak(client: TestClient, mem_store: dict) -> None:
    _seed_matrix(mem_store)
    first = _search(client, q="engineer").json()
    second = _search(client, q="engineer").json()
    assert _slugs(first) == _slugs(second)
    # Browse mode (no q): newest published first, slug ascending tiebreak.
    browse = _search(client).json()
    assert _slugs(browse) == ["cand-a", "cand-b", "cand-c", "cand-d"]


def test_no_numeric_scores_in_response(client: TestClient, mem_store: dict) -> None:
    """Ranking is internal — the payload carries no score/percent fields."""
    _seed_matrix(mem_store)
    body = _search(client, q="python").json()
    text = str(body)
    assert "score" not in text.lower()
    assert "%" not in text


# ── Filters ──────────────────────────────────────────────────────────────────


def test_evidence_filters(client: TestClient, mem_store: dict) -> None:
    _seed_matrix(mem_store)
    live = _search(client, evidence="live_site").json()
    assert set(_slugs(live)) == {"cand-a", "cand-c"}
    docs = _search(client, evidence="documents").json()
    assert _slugs(docs) == ["cand-d"]
    combined = _search(client, q="python", evidence="live_site").json()
    assert _slugs(combined) == ["cand-a"]


def test_skills_filter_requires_all(client: TestClient, mem_store: dict) -> None:
    _seed_matrix(mem_store)
    both = _search(client, skills="Python,FastAPI").json()
    assert _slugs(both) == ["cand-a"]
    react = _search(client, skills="React").json()
    assert _slugs(react) == ["cand-c"]


def test_availability_filter(client: TestClient, mem_store: dict) -> None:
    _seed_matrix(mem_store)
    interns = _search(client, availability="seeking_internship").json()
    assert _slugs(interns) == ["cand-b"]
    unknown = _search(client, availability="totally_invalid").json()
    # Unknown availability values are ignored, never an error.
    assert unknown["total"] == 4


# ── Pagination + validation ──────────────────────────────────────────────────


def test_pagination_is_stable(client: TestClient, mem_store: dict) -> None:
    _seed_matrix(mem_store)
    page1 = _search(client, page=1, page_size=2).json()
    page2 = _search(client, page=2, page_size=2).json()
    assert page1["total"] == 4 and page2["total"] == 4
    assert page1["has_more"] is True and page2["has_more"] is False
    assert _slugs(page1) + _slugs(page2) == ["cand-a", "cand-b", "cand-c", "cand-d"]


def test_query_limits_and_malicious_input(client: TestClient, mem_store: dict) -> None:
    _seed_matrix(mem_store)
    assert _search(client, q="x" * 500).status_code == 422
    assert _search(client, page_size=999).status_code == 422
    assert _search(client, page=0).status_code == 422
    sqlish = _search(client, q="'; DROP TABLE users;--").json()
    assert sqlish["results"] == []
    weird = _search(client, q="ilike.*,or=(").json()
    assert weird["total"] == 0


def test_zero_results_are_honest(client: TestClient, mem_store: dict) -> None:
    _seed_matrix(mem_store)
    body = _search(client, q="nonexistent-technology-xyz").json()
    assert body["total"] == 0
    assert body["results"] == []
    assert body["has_more"] is False


# ── Observability ────────────────────────────────────────────────────────────


def test_search_events_recorded_coarsely(client: TestClient, mem_store: dict) -> None:
    _seed_matrix(mem_store)
    _search(client, q="python", evidence="live_site")
    _search(client, q="nonexistent-xyz")
    events = list(mem_store.get("recruiter_search_events", {}).values())
    assert len(events) == 2
    hit = next(e for e in events if e["query_text"] == "python")
    assert hit["result_count"] == 1
    assert hit["zero_results"] is False
    miss = next(e for e in events if e["query_text"] == "nonexistent-xyz")
    assert miss["zero_results"] is True
    # Coarse only: no candidate data in the event rows.
    for event in events:
        assert "cand-" not in str(event)


# ── Search → Save (existing connection system) ───────────────────────────────


def test_search_result_saves_through_existing_connections(
    client: TestClient, mem_store: dict
) -> None:
    _seed_matrix(mem_store)
    body = _search(client, q="python").json()
    slug = body["results"][0]["public_slug"]
    save = client.post(
        "/api/v1/recruiter/connections",
        json={"passport_slug": slug, "source": "search", "source_context": {"q": "python"}},
    )
    assert save.status_code == 200, save.text
    payload = save.json()
    assert payload["saved"] is True and payload["already_saved"] is False
    assert payload["source"] == "search"
    # Idempotent repeat.
    again = client.post(
        "/api/v1/recruiter/connections", json={"passport_slug": slug, "source": "search"}
    )
    assert again.json()["already_saved"] is True
    rows = list(mem_store["recruiter_candidate_connections"].values())
    assert len(rows) == 1 and rows[0]["source"] == "search"


# ── Unit: transient transport-race retry ─────────────────────────────────────


def test_transient_transport_error_retries_on_fresh_client(monkeypatch) -> None:
    """The shared Supabase client's httpx transport races under concurrent
    requests (ReadError Errno 11). Search reads retry ONCE on a fresh
    client; non-transient errors propagate untouched."""
    from app.services import recruiter_search_service as svc

    class FakeReadError(Exception):
        pass

    FakeReadError.__module__ = "httpx"
    FakeReadError.__name__ = "ReadError"

    fresh = object()
    monkeypatch.setattr(
        "app.db.supabase.create_service_role_client", lambda: fresh
    )

    calls: list[Any] = []

    def flaky(client: Any) -> str:
        calls.append(client)
        if len(calls) == 1:
            raise FakeReadError("[Errno 11] Resource temporarily unavailable")
        return "ok"

    class NotADict:  # non-dict db → the retry path is active
        pass

    assert svc._read_with_transient_retry(NotADict(), flaky) == "ok"
    assert calls[1] is fresh

    def hard_failure(client: Any) -> str:
        raise ValueError("real bug — must not be retried/swallowed")

    with pytest.raises(ValueError):
        svc._read_with_transient_retry(NotADict(), hard_failure)


# ── Unit: tokenization ───────────────────────────────────────────────────────


def test_tokenize_query() -> None:
    assert tokenize_query("Python and FastAPI") == ["python", "fastapi"]
    assert tokenize_query("C++ / c# .NET") == ["c++", "c#", "net"]
    assert tokenize_query("  ") == []
    assert tokenize_query(None) == []
    assert tokenize_query("the a of") == []
    assert tokenize_query("Python python PYTHON") == ["python"]
