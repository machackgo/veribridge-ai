"""Recruiter Comparison + Shortlisting (V2, migration 068).

Covers: requirement parsing (trailing markers, edited chips, OR-groups,
evidence routing), the deterministic evidence matrix (proven / claimed /
none / unavailable — never a score), proof provenance, related-not-proof
hints, transparent counts, comparison session CRUD + isolation, live
fail-closed re-evaluation (unpublish / disclosure bump / exclusion),
candidate identity dedup, shortlist + private-note persistence, and the
talent-pool foundation.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.services.recruiter_comparison_service import (
    normalize_requirement_term,
    plan_from_requirements,
    plan_from_role_text,
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


# ── Fixture corpus (Part-35 Scenario 1 shape) ────────────────────────────────


def _skill(name: str, slug: str, status: str, sources: list[str]) -> dict:
    return {
        "skill": name,
        "skill_slug": slug,
        "category": "",
        "status": status,
        "evidence_sources": sources,
        "aliases": [],
        "projects": [
            {
                "title": f"{name} Project",
                "public_report_path": f"/r/{slug}",
                "skill_status": status,
                "proof_types": sources,
            }
        ],
        "traces": [
            {
                "source_type": sources[0] if sources else "GitHub Proof",
                "source_title": f"{name.lower()}.py",
                "summary": f"Uses {name} in production code",
                "public_url": None,
            }
        ],
    }


def _row(
    uid: str,
    slug: str,
    name: str,
    *,
    skills: list[dict],
    technologies: list[str] | None = None,
    live: bool = False,
    github: bool = True,
) -> dict:
    projects = [
        {
            "title": f"{name} Capstone",
            "summary": "",
            "technologies": technologies or [],
            "evidence_sources": (["GitHub Proof"] if github else [])
            + (["Website Proof"] if live else []),
            "public_report_path": f"/r/{slug}",
            "has_live_url": live,
            "has_github_repo": github,
        }
    ]
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
        "text_profile": name.lower(),
        "text_projects": "capstone",
        "text_meta": "",
        "search_text": " ".join(
            [s["skill"] for s in skills] + (technologies or []) + [name]
        ).lower(),
        "disclosure_version": 1,
        "passport_published_at": "2026-07-01T00:00:00+00:00",
        "projected_at": "2026-08-18T00:00:00+00:00",
    }


def _seed(mem_store: dict) -> dict[str, str]:
    """Alpha: Python+FastAPI+ML (GitHub). Bravo: Python+ML+NLP (GitHub+live).
    Charlie: Python+FastAPI+Computer Vision (live); Docker only claimed."""
    rows = [
        _row(
            "u-alpha", "alpha", "Alpha Candidate",
            skills=[
                _skill("Python", "python", "Demonstrated", ["GitHub Proof"]),
                _skill("FastAPI", "fastapi", "Demonstrated", ["GitHub Proof"]),
                _skill(
                    "Machine Learning", "machine-learning", "Demonstrated",
                    ["GitHub Proof", "Document Proof"],
                ),
            ],
        ),
        _row(
            "u-bravo", "bravo", "Bravo Candidate",
            skills=[
                _skill("Python", "python", "Evidence observed", ["GitHub Proof"]),
                _skill(
                    "Machine Learning", "machine-learning",
                    "Partially demonstrated", ["GitHub Proof"],
                ),
                _skill(
                    "Natural Language Processing", "natural-language-processing",
                    "Demonstrated", ["GitHub Proof"],
                ),
            ],
            live=True,
        ),
        _row(
            "u-charlie", "charlie", "Charlie Candidate",
            skills=[
                _skill("Python", "python", "Demonstrated", ["GitHub Proof"]),
                _skill("FastAPI", "fastapi", "Evidence observed", ["GitHub Proof"]),
                _skill(
                    "Computer Vision", "computer-vision", "Demonstrated",
                    ["GitHub Proof"],
                ),
            ],
            technologies=["Docker"],
            live=True,
            github=False,
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
    # Recruiter A has saved all three.
    connections = {}
    for i, r in enumerate(rows):
        cid = f"conn-{r['user_id']}"
        connections[cid] = {
            "id": cid,
            "recruiter_user_id": RECRUITER_A,
            "student_user_id": r["user_id"],
            "passport_id": f"pp-{r['user_id']}",
            "source": "search",
            "source_context": {},
            "created_at": f"2026-08-1{i}T00:00:00+00:00",
            "updated_at": f"2026-08-1{i}T00:00:00+00:00",
        }
    mem_store["recruiter_candidate_connections"] = connections
    return {r["public_slug"]: r["user_id"] for r in rows}


ROLE_TEXT = (
    "Entry-level AI Engineer. Python, FastAPI and Machine Learning are "
    "required. NLP and live deployment are preferred."
)


def _create(client: TestClient, **overrides) -> dict:
    payload = {
        "role_text": ROLE_TEXT,
        "connection_ids": ["conn-u-alpha", "conn-u-bravo", "conn-u-charlie"],
        **overrides,
    }
    res = client.post("/api/v1/recruiter/comparisons", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


def _column(matrix: dict, slug: str) -> dict:
    return next(c for c in matrix["columns"] if c["public_slug"] == slug)


def _cell(matrix: dict, slug: str, display: str) -> dict:
    req = next(r for r in matrix["requirements"] if r["display"] == display)
    return _column(matrix, slug)["cells"][req["key"]]


# ── Requirement parsing ──────────────────────────────────────────────────────


def test_trailing_markers_parse_as_preferred() -> None:
    plan = plan_from_role_text(ROLE_TEXT)
    assert plan["required_groups"] == [["python"], ["fastapi"], ["machine-learning"]]
    assert plan["preferred"] == ["natural-language-processing"]
    assert plan["preferred_evidence"] == ["live_site"]
    assert plan["evidence"] == []


def test_trailing_required_marker() -> None:
    plan = plan_from_role_text("Docker required. Kubernetes is a plus.")
    assert ["docker"] in plan["required_groups"]
    assert "kubernetes" in plan["preferred"]


def test_normalize_requirement_term_routes_evidence() -> None:
    assert normalize_requirement_term("live deployment") == ("evidence", "live_site")
    assert normalize_requirement_term("GitHub proof") == ("evidence", "github")
    assert normalize_requirement_term("FastAPI") == ("concept", "fastapi")
    assert normalize_requirement_term("Fast API") == ("concept", "fastapi")
    assert normalize_requirement_term("  ") is None


def test_plan_from_requirements_chips() -> None:
    plan = plan_from_requirements(
        {
            "required": ["Python", ["FastAPI", "Flask"], "live deployment"],
            "preferred": ["NLP", "GitHub evidence"],
            "excluded": ["Computer Vision"],
        }
    )
    assert plan["required_groups"] == [["python"], ["fastapi", "flask"]]
    assert plan["evidence"] == ["live_site"]
    assert plan["preferred"] == ["natural-language-processing"]
    assert plan["preferred_evidence"] == ["github"]
    assert plan["excluded"] == ["computer-vision"]


def test_unknown_requirement_still_normalizes() -> None:
    plan = plan_from_requirements({"required": ["Quantum Basketweaving"]})
    assert plan["required_groups"] == [["quantum-basketweaving"]]


# ── Matrix evaluation ────────────────────────────────────────────────────────


def test_matrix_states_match_scenario_one(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    body = _create(client)
    matrix = body["matrix"]

    displays = [r["display"] for r in matrix["requirements"]]
    assert displays == [
        "Python", "FastAPI", "Machine Learning",
        "Natural Language Processing", "Live deployed project",
    ]

    assert _cell(matrix, "alpha", "Python")["state"] == "proven"
    assert _cell(matrix, "alpha", "FastAPI")["state"] == "proven"
    assert _cell(matrix, "alpha", "Machine Learning")["state"] == "proven"
    assert _cell(matrix, "alpha", "Natural Language Processing")["state"] == "none"
    assert _cell(matrix, "alpha", "Live deployed project")["state"] == "none"

    assert _cell(matrix, "bravo", "FastAPI")["state"] == "none"
    assert _cell(matrix, "bravo", "Natural Language Processing")["state"] == "proven"
    assert _cell(matrix, "bravo", "Live deployed project")["state"] == "proven"

    # Charlie's Computer Vision evidence satisfies the ML requirement via the
    # child ⇒ parent taxonomy edge, and the indirect note says so.
    ml_cell = _cell(matrix, "charlie", "Machine Learning")
    assert ml_cell["state"] == "proven"
    assert ml_cell["direct"] is False
    assert "Computer Vision" in (ml_cell["note"] or "")


def test_no_fake_scores_anywhere(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    body = _create(client)
    text = str(body)
    assert "score" not in text.lower()
    assert "%" not in text
    counts = _column(body["matrix"], "alpha")["counts"]
    assert counts["required_proven"] == 3
    assert counts["required_total"] == 3
    assert counts["preferred_proven"] == 0
    assert counts["preferred_total"] == 2


def test_proven_cells_carry_provenance(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    matrix = _create(client)["matrix"]
    cell = _cell(matrix, "alpha", "FastAPI")
    assert cell["proof_path"] == "/p/alpha/skills/fastapi"
    assert cell["projects"][0]["public_report_path"] == "/r/fastapi"
    assert cell["traces"][0]["summary"].startswith("Uses FastAPI")
    assert cell["evidence_sources"] == ["GitHub Proof"]


def test_missing_evidence_shows_related_not_proof(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    matrix = _create(client)["matrix"]
    nlp_cell = _cell(matrix, "alpha", "Natural Language Processing")
    assert nlp_cell["state"] == "none"
    assert nlp_cell["note"] == "No published Natural Language Processing evidence"
    # Alpha has Machine Learning — adjacent, but explicitly NOT NLP proof.
    assert "Machine Learning" in nlp_cell["related"]
    assert nlp_cell["proof_path"] is None


def test_claimed_technology_is_labeled_not_verified(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    body = _create(
        client,
        role_text=None,
        requirements={"required": ["Docker"]},
        connection_ids=["conn-u-alpha", "conn-u-charlie"],
    )
    cell = _cell(body["matrix"], "charlie", "Docker")
    assert cell["state"] == "claimed"
    assert "not verified" in cell["note"]
    assert cell["proof_path"] is None
    assert _cell(body["matrix"], "alpha", "Docker")["state"] == "none"


def test_zero_coverage_note_when_everyone_lacks_proof(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    body = _create(
        client,
        role_text=None,
        requirements={"required": ["Data Engineering"]},
    )
    assert any(
        "No selected candidate has published Data Engineering evidence" in n
        for n in body["matrix"]["notes"]
    )


def test_excluded_concept_flags_but_keeps_column(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    body = _create(
        client,
        role_text=None,
        requirements={"required": ["Python"], "excluded": ["Computer Vision"]},
    )
    charlie = _column(body["matrix"], "charlie")
    assert charlie["excluded_hits"] == ["Computer Vision"]
    assert charlie["available"] is True
    assert _column(body["matrix"], "alpha")["excluded_hits"] == []


def test_comparison_limits(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    res = client.post(
        "/api/v1/recruiter/comparisons",
        json={"connection_ids": ["conn-u-alpha"]},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "too_few_candidates"

    # Six distinct saved candidates → too many.
    for i in range(6):
        uid = f"u-x{i}"
        mem_store["recruiter_candidate_connections"][f"conn-{uid}"] = {
            "id": f"conn-{uid}",
            "recruiter_user_id": RECRUITER_A,
            "student_user_id": uid,
            "passport_id": f"pp-{uid}",
            "source": "search",
            "created_at": "2026-08-18T00:00:00+00:00",
        }
    res = client.post(
        "/api/v1/recruiter/comparisons",
        json={"connection_ids": [f"conn-u-x{i}" for i in range(6)]},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "too_many_candidates"


def test_candidate_identity_dedupes_across_inputs(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    body = _create(
        client,
        connection_ids=["conn-u-alpha", "conn-u-bravo"],
        candidate_slugs=["alpha"],  # same human as conn-u-alpha
    )
    user_ids = [c["user_id"] for c in body["matrix"]["columns"]]
    assert user_ids == ["u-alpha", "u-bravo"]


def test_foreign_connection_id_is_not_found(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    mem_store["recruiter_candidate_connections"]["conn-foreign"] = {
        "id": "conn-foreign",
        "recruiter_user_id": RECRUITER_B,
        "student_user_id": "u-alpha",
        "passport_id": "pp-u-alpha",
        "source": "search",
        "created_at": "2026-08-18T00:00:00+00:00",
    }
    res = client.post(
        "/api/v1/recruiter/comparisons",
        json={"connection_ids": ["conn-foreign", "conn-u-bravo"]},
    )
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "candidate_not_found"


def test_interpretation_chips_round_trip(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    body = _create(client)
    view = body["matrix"]["requirements_view"]
    assert [c["display"] for c in view["required"]] == [
        "Python", "FastAPI", "Machine Learning",
    ]
    assert [c["display"] for c in view["preferred"]] == [
        "Natural Language Processing"
    ]
    assert [c["display"] for c in view["preferred_evidence"]] == [
        "Live deployed project"
    ]

    # Edit chips: drop ML, promote NLP to required — PATCH re-evaluates.
    comparison_id = body["comparison"]["id"]
    res = client.patch(
        f"/api/v1/recruiter/comparisons/{comparison_id}",
        json={"requirements": {"required": ["Python", "FastAPI", "NLP"]}},
    )
    assert res.status_code == 200
    matrix = res.json()["matrix"]
    displays = [r["display"] for r in matrix["requirements"]]
    assert displays == ["Python", "FastAPI", "Natural Language Processing"]
    assert _cell(matrix, "bravo", "Natural Language Processing")["state"] == "proven"


# ── Session persistence + isolation ──────────────────────────────────────────


def test_session_persists_and_lists(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    body = _create(client, title="AI Engineer — Fall 2026")
    comparison_id = body["comparison"]["id"]

    res = client.get("/api/v1/recruiter/comparisons")
    assert res.status_code == 200
    listing = res.json()
    assert listing["total"] == 1
    assert listing["comparisons"][0]["title"] == "AI Engineer — Fall 2026"
    assert listing["comparisons"][0]["candidate_count"] == 3

    res = client.get(f"/api/v1/recruiter/comparisons/{comparison_id}")
    assert res.status_code == 200
    assert len(res.json()["matrix"]["columns"]) == 3


def test_recruiter_isolation_on_sessions(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    comparison_id = _create(client)["comparison"]["id"]

    _as_user(RECRUITER_B)
    assert client.get("/api/v1/recruiter/comparisons").json()["total"] == 0
    assert (
        client.get(f"/api/v1/recruiter/comparisons/{comparison_id}").status_code == 404
    )
    assert (
        client.patch(
            f"/api/v1/recruiter/comparisons/{comparison_id}", json={"title": "mine"}
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/v1/recruiter/comparisons/{comparison_id}").status_code
        == 404
    )


def test_delete_comparison(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    comparison_id = _create(client)["comparison"]["id"]
    res = client.delete(f"/api/v1/recruiter/comparisons/{comparison_id}")
    assert res.status_code == 200 and res.json()["deleted"] is True
    assert (
        client.get(f"/api/v1/recruiter/comparisons/{comparison_id}").status_code == 404
    )


# ── Live fail-closed re-evaluation ───────────────────────────────────────────


def test_unpublished_candidate_degrades_on_reload(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    comparison_id = _create(client)["comparison"]["id"]

    mem_store["vbr_work_passports"]["pp-u-bravo"]["is_published"] = False
    matrix = client.get(
        f"/api/v1/recruiter/comparisons/{comparison_id}"
    ).json()["matrix"]

    bravo = next(c for c in matrix["columns"] if c["user_id"] == "u-bravo")
    assert bravo["available"] is False
    assert bravo["cells"] == {}
    assert bravo["public_slug"] is None
    assert "no longer publicly available" in bravo["unavailable_note"]
    assert any("no longer publicly available" in n for n in matrix["notes"])
    # The other columns still evaluate.
    assert _column(matrix, "alpha")["available"] is True


def test_disclosure_version_bump_fails_closed(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    comparison_id = _create(client)["comparison"]["id"]
    mem_store["passport_disclosure_policies"] = {
        "pol-1": {"user_id": "u-alpha", "disclosure_version": 7}
    }
    matrix = client.get(
        f"/api/v1/recruiter/comparisons/{comparison_id}"
    ).json()["matrix"]
    assert next(
        c for c in matrix["columns"] if c["user_id"] == "u-alpha"
    )["available"] is False


def test_discovery_exclusion_fails_closed(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    comparison_id = _create(client)["comparison"]["id"]
    mem_store["recruiter_discovery_exclusions"] = {
        "u-charlie": {"user_id": "u-charlie", "reason": "qa fixture"}
    }
    matrix = client.get(
        f"/api/v1/recruiter/comparisons/{comparison_id}"
    ).json()["matrix"]
    assert next(
        c for c in matrix["columns"] if c["user_id"] == "u-charlie"
    )["available"] is False


# ── Analytics ────────────────────────────────────────────────────────────────


def test_comparison_records_privacy_safe_event(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    _create(client)
    events = list(mem_store.get("recruiter_search_events", {}).values())
    assert len(events) == 1
    event = events[0]
    assert event["filters"]["comparison"] == "created"
    assert event["filters"]["candidates"] == 3
    # Never raw evidence or notes in events.
    assert "note" not in str(event).lower()


# ── Shortlisting ─────────────────────────────────────────────────────────────


def test_shortlist_persists_and_round_trips(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    res = client.patch(
        "/api/v1/recruiter/connections/conn-u-alpha",
        json={"status": "shortlisted", "recruiter_note": "Strong FastAPI + ML."},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "shortlisted"
    assert body["recruiter_note"] == "Strong FastAPI + ML."
    assert body["status_updated_at"] is not None

    listing = client.get("/api/v1/recruiter/connections").json()
    alpha = next(c for c in listing["connections"] if c["id"] == "conn-u-alpha")
    assert alpha["status"] == "shortlisted"
    others = [c for c in listing["connections"] if c["id"] != "conn-u-alpha"]
    assert all(c["status"] == "saved" for c in others)


def test_archive_and_restore(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    assert (
        client.patch(
            "/api/v1/recruiter/connections/conn-u-bravo", json={"status": "archived"}
        ).json()["status"]
        == "archived"
    )
    assert (
        client.patch(
            "/api/v1/recruiter/connections/conn-u-bravo", json={"status": "saved"}
        ).json()["status"]
        == "saved"
    )


def test_invalid_status_rejected(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    res = client.patch(
        "/api/v1/recruiter/connections/conn-u-alpha", json={"status": "hired"}
    )
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "invalid_status"


def test_note_clears_explicitly(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    client.patch(
        "/api/v1/recruiter/connections/conn-u-alpha",
        json={"recruiter_note": "temp"},
    )
    res = client.patch(
        "/api/v1/recruiter/connections/conn-u-alpha", json={"clear_note": True}
    )
    assert res.json()["recruiter_note"] is None


def test_shortlist_isolation(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    _as_user(RECRUITER_B)
    res = client.patch(
        "/api/v1/recruiter/connections/conn-u-alpha",
        json={"status": "shortlisted"},
    )
    assert res.status_code == 404


def test_matrix_column_carries_connection_status(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    client.patch(
        "/api/v1/recruiter/connections/conn-u-alpha", json={"status": "shortlisted"}
    )
    matrix = _create(client)["matrix"]
    alpha = _column(matrix, "alpha")
    assert alpha["connection"] == {"id": "conn-u-alpha", "status": "shortlisted"}


# ── Talent pools ─────────────────────────────────────────────────────────────


def test_pool_lifecycle(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    res = client.post(
        "/api/v1/recruiter/pools", json={"name": "AI Engineer — Fall 2026"}
    )
    assert res.status_code == 200, res.text
    pool = res.json()
    assert pool["name"] == "AI Engineer — Fall 2026"

    # Idempotent create.
    again = client.post(
        "/api/v1/recruiter/pools", json={"name": "AI Engineer — Fall 2026"}
    ).json()
    assert again["id"] == pool["id"]

    res = client.post(
        f"/api/v1/recruiter/pools/{pool['id']}/members",
        json={"connection_id": "conn-u-alpha"},
    )
    assert res.status_code == 200
    assert res.json()["member_user_ids"] == ["u-alpha"]

    # Idempotent add.
    res = client.post(
        f"/api/v1/recruiter/pools/{pool['id']}/members",
        json={"connection_id": "conn-u-alpha"},
    )
    assert res.json()["member_count"] == 1

    res = client.delete(
        f"/api/v1/recruiter/pools/{pool['id']}/members/u-alpha"
    )
    assert res.json()["member_count"] == 0

    assert (
        client.delete(f"/api/v1/recruiter/pools/{pool['id']}").json()["deleted"]
        is True
    )
    assert client.get("/api/v1/recruiter/pools").json()["total"] == 0


def test_pool_member_requires_own_connection(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    pool = client.post("/api/v1/recruiter/pools", json={"name": "Pool"}).json()
    mem_store["recruiter_candidate_connections"]["conn-foreign"] = {
        "id": "conn-foreign",
        "recruiter_user_id": RECRUITER_B,
        "student_user_id": "u-alpha",
        "created_at": "2026-08-18T00:00:00+00:00",
    }
    res = client.post(
        f"/api/v1/recruiter/pools/{pool['id']}/members",
        json={"connection_id": "conn-foreign"},
    )
    assert res.status_code == 404


def test_pool_isolation(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    pool = client.post("/api/v1/recruiter/pools", json={"name": "Mine"}).json()
    _as_user(RECRUITER_B)
    assert client.get("/api/v1/recruiter/pools").json()["total"] == 0
    assert client.delete(f"/api/v1/recruiter/pools/{pool['id']}").status_code == 404
    assert (
        client.post(
            f"/api/v1/recruiter/pools/{pool['id']}/members",
            json={"connection_id": "conn-u-alpha"},
        ).status_code
        == 404
    )
