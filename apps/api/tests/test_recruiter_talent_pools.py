"""Recruiter Talent Pools (V5, migration 070).

Covers: pool CRUD + caps + archived semantics, idempotent membership across
every resolution path (published slugs, own connections, already-visible
student ids), multi-pool membership, private notes, fail-closed evidence
context (unpublished candidates degrade to consented identity), recruiter
isolation on every verb, the memberships picker endpoint, source
vocabulary (065 + saved_search), deletion never touching connections or
briefs, privacy-safe analytics, and the no-scores sweep.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.services.recruiter_talent_pool_service import (
    MAX_POOL_CANDIDATES,
    MAX_TALENT_POOLS,
)

RECRUITER_A = "00000000-0000-4000-8000-0000000000a1"
RECRUITER_B = "00000000-0000-4000-8000-0000000000b2"


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


# ── Fixture corpus (same shape as the briefs suite) ──────────────────────────


def _skill(name: str, slug: str, status: str, sources: list[str]) -> dict:
    return {
        "skill": name,
        "skill_slug": slug,
        "category": "",
        "status": status,
        "evidence_sources": sources,
        "aliases": [],
        "projects": [],
        "traces": [],
    }


def _row(uid: str, slug: str, name: str, *, skills: list[dict]) -> dict:
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
                "has_live_url": False,
                "has_github_repo": True,
            }
        ],
        "evidence_flags": {
            "github": True,
            "live_site": False,
            "documents": False,
            "project_defense": False,
            "video": False,
        },
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
                _skill("Python", "python", "Demonstrated", ["GitHub Proof"]),
                _skill("FastAPI", "fastapi", "Demonstrated", ["GitHub Proof"]),
            ],
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
    # Recruiter A has saved alpha to the workspace (a connection).
    mem_store["recruiter_candidate_connections"] = {
        "conn-u-alpha": {
            "id": "conn-u-alpha",
            "recruiter_user_id": RECRUITER_A,
            "student_user_id": "u-alpha",
            "passport_id": "pp-u-alpha",
            "source": "search",
            "source_context": {},
            "created_at": "2026-08-10T00:00:00+00:00",
            "updated_at": "2026-08-10T00:00:00+00:00",
        }
    }


def _create_pool(client: TestClient, name: str = "AI / ML Early Talent") -> dict:
    res = client.post("/api/v1/recruiter/pools", json={"name": name})
    assert res.status_code == 200, res.text
    return res.json()["pool"]


def _add(client: TestClient, pool_id: str, **payload) -> dict:
    res = client.post(f"/api/v1/recruiter/pools/{pool_id}/candidates", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


# ── Pool CRUD ────────────────────────────────────────────────────────────────


def test_create_list_update_delete_pool(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    pool = _create_pool(client)
    assert pool["name"] == "AI / ML Early Talent"
    assert pool["status"] == "active"
    assert pool["candidate_count"] == 0

    res = client.get("/api/v1/recruiter/pools")
    assert res.status_code == 200
    listing = res.json()
    assert listing["total"] == 1
    assert listing["pools"][0]["id"] == pool["id"]

    res = client.patch(
        f"/api/v1/recruiter/pools/{pool['id']}",
        json={"name": "Fall 2026 Prospects", "description": "Career fair"},
    )
    assert res.status_code == 200
    updated = res.json()["pool"]
    assert updated["name"] == "Fall 2026 Prospects"
    assert updated["description"] == "Career fair"

    res = client.patch(
        f"/api/v1/recruiter/pools/{pool['id']}", json={"clear_description": True}
    )
    assert res.json()["pool"]["description"] is None

    res = client.delete(f"/api/v1/recruiter/pools/{pool['id']}")
    assert res.status_code == 200 and res.json()["deleted"] is True
    assert client.get(f"/api/v1/recruiter/pools/{pool['id']}").status_code == 404


def test_pool_name_required(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    assert client.post("/api/v1/recruiter/pools", json={"name": ""}).status_code == 422
    res = client.post("/api/v1/recruiter/pools", json={"name": "   "})
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "invalid_name"
    pool = _create_pool(client)
    res = client.patch(f"/api/v1/recruiter/pools/{pool['id']}", json={"name": "  "})
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "invalid_name"


def test_pool_cap(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    now = "2026-08-19T00:00:00+00:00"
    mem_store["recruiter_talent_pools"] = {
        f"pool-{i}": {
            "id": f"pool-{i}",
            "recruiter_user_id": RECRUITER_A,
            "name": f"Pool {i}",
            "description": None,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        for i in range(MAX_TALENT_POOLS)
    }
    res = client.post("/api/v1/recruiter/pools", json={"name": "One too many"})
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "too_many_pools"


def test_archived_semantics(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    pool = _create_pool(client)
    res = client.patch(
        f"/api/v1/recruiter/pools/{pool['id']}", json={"status": "archived"}
    )
    assert res.json()["pool"]["status"] == "archived"
    # Archived pools stay listed (the UI groups them) and are restorable.
    listing = client.get("/api/v1/recruiter/pools").json()
    assert listing["pools"][0]["status"] == "archived"
    res = client.patch(
        f"/api/v1/recruiter/pools/{pool['id']}", json={"status": "active"}
    )
    assert res.json()["pool"]["status"] == "active"
    res = client.patch(
        f"/api/v1/recruiter/pools/{pool['id']}", json={"status": "closed"}
    )
    assert res.status_code == 422  # closed Literal in the schema


# ── Membership ───────────────────────────────────────────────────────────────


def test_add_candidates_slugs_and_idempotency(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    pool = _create_pool(client)
    result = _add(client, pool["id"], candidate_slugs=["alpha", "bravo"])
    assert result["added"] == 2 and result["already_in_pool"] == 0
    assert {c["student_user_id"] for c in result["candidates"]} == {"u-alpha", "u-bravo"}

    again = _add(client, pool["id"], candidate_slugs=["alpha"])
    assert again["added"] == 0 and again["already_in_pool"] == 1

    detail = client.get(f"/api/v1/recruiter/pools/{pool['id']}").json()
    assert detail["total"] == 2
    alpha = next(
        c for c in detail["candidates"] if c["student_user_id"] == "u-alpha"
    )
    assert alpha["candidate"]["display_name"] == "Alpha Candidate"
    assert alpha["evidence"]["skill_count"] == 2
    assert "Python" in alpha["evidence"]["top_skills"]
    assert alpha["evidence"]["public_slug"] == "alpha"


def test_add_via_connection_ids(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    pool = _create_pool(client)
    result = _add(client, pool["id"], connection_ids=["conn-u-alpha"])
    assert result["added"] == 1
    res = client.post(
        f"/api/v1/recruiter/pools/{pool['id']}/candidates",
        json={"connection_ids": ["conn-foreign"]},
    )
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "candidate_not_found"


def test_add_via_student_user_ids_requires_visibility(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    pool = _create_pool(client)
    # u-alpha is visible (own connection) — accepted, with saved_search source.
    result = _add(
        client, pool["id"], student_user_ids=["u-alpha"], source="saved_search"
    )
    assert result["added"] == 1
    assert result["candidates"][0]["source"] == "saved_search"
    # u-bravo is published but NOT visible to A through any owned surface.
    res = client.post(
        f"/api/v1/recruiter/pools/{pool['id']}/candidates",
        json={"student_user_ids": ["u-bravo"]},
    )
    assert res.status_code == 404
    # Once bravo is a member of one of A's pools, the id becomes visible.
    other = _create_pool(client, name="Second pool")
    _add(client, other["id"], candidate_slugs=["bravo"])
    result = _add(client, pool["id"], student_user_ids=["u-bravo"])
    assert result["added"] == 1


def test_multi_pool_membership_and_memberships_endpoint(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    first = _create_pool(client, name="First")
    second = _create_pool(client, name="Second")
    _add(client, first["id"], candidate_slugs=["alpha"])
    _add(client, second["id"], candidate_slugs=["alpha", "bravo"])

    res = client.get(
        "/api/v1/recruiter/pools/memberships",
        params={"student_user_ids": "u-alpha,u-bravo,u-missing"},
    )
    assert res.status_code == 200
    memberships = res.json()["memberships"]
    assert set(memberships["u-alpha"]) == {first["id"], second["id"]}
    assert memberships["u-bravo"] == [second["id"]]
    assert "u-missing" not in memberships


def test_invalid_source_rejected(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    pool = _create_pool(client)
    res = client.post(
        f"/api/v1/recruiter/pools/{pool['id']}/candidates",
        json={"candidate_slugs": ["alpha"], "source": "scraped"},
    )
    assert res.status_code == 422  # closed Literal in the schema


def test_pool_candidate_cap(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    pool = _create_pool(client)
    members = {}
    for i in range(MAX_POOL_CANDIDATES):
        uid = f"u-fill-{i}"
        members[f"{pool['id']}:{uid}"] = {
            "pool_id": pool["id"],
            "student_user_id": uid,
            "source": "direct",
            "note": None,
            "added_at": "2026-08-19T00:00:00+00:00",
        }
    mem_store["recruiter_talent_pool_candidates"] = members
    res = client.post(
        f"/api/v1/recruiter/pools/{pool['id']}/candidates",
        json={"candidate_slugs": ["alpha"]},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "pool_full"


def test_note_update_and_clear(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    pool = _create_pool(client)
    _add(client, pool["id"], candidate_slugs=["alpha"])
    res = client.patch(
        f"/api/v1/recruiter/pools/{pool['id']}/candidates/u-alpha",
        json={"note": "Strong FastAPI evidence — revisit for platform team"},
    )
    assert res.status_code == 200
    assert res.json()["candidate"]["note"].startswith("Strong FastAPI")
    res = client.patch(
        f"/api/v1/recruiter/pools/{pool['id']}/candidates/u-alpha",
        json={"clear_note": True},
    )
    assert res.json()["candidate"]["note"] is None


def test_remove_candidate(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    pool = _create_pool(client)
    _add(client, pool["id"], candidate_slugs=["alpha"])
    res = client.delete(f"/api/v1/recruiter/pools/{pool['id']}/candidates/u-alpha")
    assert res.status_code == 200 and res.json()["removed"] is True
    res = client.delete(f"/api/v1/recruiter/pools/{pool['id']}/candidates/u-alpha")
    assert res.status_code == 404


def test_unpublished_candidate_fails_closed(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    pool = _create_pool(client)
    _add(client, pool["id"], candidate_slugs=["alpha"])
    mem_store["vbr_work_passports"]["pp-u-alpha"]["is_published"] = False

    detail = client.get(f"/api/v1/recruiter/pools/{pool['id']}").json()
    alpha = detail["candidates"][0]
    # Consented identity survives; evidence context and the public link do not.
    assert alpha["evidence"] is None
    assert alpha["candidate"]["is_published"] is False
    assert alpha["candidate"]["public_slug"] is None


def test_delete_pool_leaves_connections_and_briefs(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    brief = client.post(
        "/api/v1/recruiter/briefs", json={"role_text": "Python required."}
    ).json()["brief"]
    client.post(
        f"/api/v1/recruiter/briefs/{brief['id']}/candidates",
        json={"candidate_slugs": ["alpha"]},
    )
    pool = _create_pool(client)
    _add(client, pool["id"], candidate_slugs=["alpha"])

    res = client.delete(f"/api/v1/recruiter/pools/{pool['id']}")
    assert res.json()["deleted"] is True
    # Connection and brief pool row are untouched.
    assert "conn-u-alpha" in mem_store["recruiter_candidate_connections"]
    brief_pool = client.get(
        f"/api/v1/recruiter/briefs/{brief['id']}/candidates"
    ).json()
    assert brief_pool["total"] == 1


# ── Isolation ────────────────────────────────────────────────────────────────


def test_cross_recruiter_isolation_on_every_verb(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    pool = _create_pool(client)
    _add(client, pool["id"], candidate_slugs=["alpha"])

    _as_user(RECRUITER_B)
    assert client.get("/api/v1/recruiter/pools").json()["total"] == 0
    assert client.get(f"/api/v1/recruiter/pools/{pool['id']}").status_code == 404
    assert (
        client.patch(
            f"/api/v1/recruiter/pools/{pool['id']}", json={"name": "Hijack"}
        ).status_code
        == 404
    )
    assert client.delete(f"/api/v1/recruiter/pools/{pool['id']}").status_code == 404
    assert (
        client.post(
            f"/api/v1/recruiter/pools/{pool['id']}/candidates",
            json={"candidate_slugs": ["bravo"]},
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/recruiter/pools/{pool['id']}/candidates/u-alpha",
            json={"note": "x"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/recruiter/pools/{pool['id']}/candidates/u-alpha"
        ).status_code
        == 404
    )
    memberships = client.get(
        "/api/v1/recruiter/pools/memberships",
        params={"student_user_ids": "u-alpha"},
    ).json()["memberships"]
    assert memberships == {}

    _as_user(RECRUITER_A)
    assert client.get(f"/api/v1/recruiter/pools/{pool['id']}").json()["total"] == 1


def test_anonymous_is_unauthorized(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    del app.dependency_overrides[get_current_user_id]
    assert client.get("/api/v1/recruiter/pools").status_code == 401
    assert (
        client.post("/api/v1/recruiter/pools", json={"name": "Nope"}).status_code
        == 401
    )


# ── Privacy sweeps ───────────────────────────────────────────────────────────


def test_no_scores_or_percentages_in_pool_payloads(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    pool = _create_pool(client)
    _add(client, pool["id"], candidate_slugs=["alpha", "bravo"])
    for payload in (
        client.get("/api/v1/recruiter/pools").json(),
        client.get(f"/api/v1/recruiter/pools/{pool['id']}").json(),
    ):
        text = json.dumps(payload)
        assert "%" not in text
        assert '"score"' not in text and '"match_score"' not in text


def test_pool_analytics_are_privacy_safe(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    pool = _create_pool(client)
    _add(client, pool["id"], candidate_slugs=["alpha"])
    client.delete(f"/api/v1/recruiter/pools/{pool['id']}/candidates/u-alpha")
    client.delete(f"/api/v1/recruiter/pools/{pool['id']}")

    events = list(mem_store.get("recruiter_search_events", {}).values())
    pool_events = [e for e in events if (e.get("filters") or {}).get("pool")]
    assert {e["filters"]["pool"] for e in pool_events} >= {
        "created",
        "candidates_added",
        "candidate_removed",
        "deleted",
    }
    text = json.dumps(pool_events)
    # Counts + recruiter-authored pool name only — never candidate identity.
    assert "u-alpha" not in text
    assert "Alpha Candidate" not in text
    assert "alpha" not in text.replace("AI / ML Early Talent", "")
