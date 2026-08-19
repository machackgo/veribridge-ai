"""Recruiter Hiring Briefs (V3, migration 068).

Covers: requirement parsing (trailing markers, edited chips, OR-groups,
evidence routing), brief CRUD + recruiter isolation, the ROLE-SCOPED
candidate pool (per-(brief, candidate) status + private note — shortlisted
for one role, merely saved for another), the deterministic evidence matrix
as a live view over the brief (proven / claimed / none / unavailable —
never a score), proof provenance, related-not-proof hints, live
fail-closed re-evaluation (unpublish / disclosure bump / exclusion),
brief-scoped search annotation, and privacy-safe analytics.

The matrix fixture corpus and engine assertions are ported from the V2
comparison suite — they encode the product's honesty contract.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.services.recruiter_requirement_plan import (
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


# ── Fixture corpus (ported from the V2 comparison suite) ─────────────────────


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
    # Consented public identity for the workspace/pool projection.
    mem_store["passport_profiles"] = {
        f"profile-{r['user_id']}": {
            "id": f"profile-{r['user_id']}",
            "user_id": r["user_id"],
            "full_name": r["display_name"],
            "preferred_name": None,
            "pronunciation": None,
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
    # Recruiter A has saved all three to the workspace.
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

ALL_CONNECTIONS = ["conn-u-alpha", "conn-u-bravo", "conn-u-charlie"]


def _create_brief(client: TestClient, **overrides) -> dict:
    payload = {"role_text": ROLE_TEXT, **overrides}
    res = client.post("/api/v1/recruiter/briefs", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["brief"]


def _add(client: TestClient, brief_id: str, connection_ids: list[str]) -> dict:
    res = client.post(
        f"/api/v1/recruiter/briefs/{brief_id}/candidates",
        json={"connection_ids": connection_ids},
    )
    assert res.status_code == 200, res.text
    return res.json()


def _brief_with_pool(client: TestClient, **overrides) -> dict:
    brief = _create_brief(client, **overrides)
    _add(client, brief["id"], ALL_CONNECTIONS)
    return brief


def _matrix(client: TestClient, brief_id: str, candidates: str | None = None) -> dict:
    url = f"/api/v1/recruiter/briefs/{brief_id}/comparison"
    if candidates:
        url += f"?candidates={candidates}"
    res = client.get(url)
    assert res.status_code == 200, res.text
    return res.json()["matrix"]


def _column(matrix: dict, slug: str) -> dict:
    return next(c for c in matrix["columns"] if c["public_slug"] == slug)


def _cell(matrix: dict, slug: str, display: str) -> dict:
    req = next(r for r in matrix["requirements"] if r["display"] == display)
    return _column(matrix, slug)["cells"][req["key"]]


# ── Requirement parsing (canonical plan module) ──────────────────────────────


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


# ── Brief CRUD ───────────────────────────────────────────────────────────────


def test_create_brief_from_role_text(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    brief = _create_brief(client)
    assert brief["title"]  # deterministic default title, never empty
    assert brief["role_text"] == ROLE_TEXT
    assert brief["status"] == "active"
    view = brief["requirements_view"]
    assert [c["display"] for c in view["required"]] == [
        "Python", "FastAPI", "Machine Learning",
    ]
    assert [c["display"] for c in view["preferred"]] == [
        "Natural Language Processing"
    ]
    assert [c["display"] for c in view["preferred_evidence"]] == [
        "Live deployed project"
    ]
    assert brief["candidate_count"] == 0


def test_create_brief_with_explicit_title_and_chips(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    brief = _create_brief(
        client,
        title="AI Engineer — Fall 2026",
        role_text=None,
        requirements={"required": ["Python", "FastAPI"], "remote": True},
    )
    assert brief["title"] == "AI Engineer — Fall 2026"
    view = brief["requirements_view"]
    assert [c["display"] for c in view["required"]] == ["Python", "FastAPI"]
    # `remote` survives the plan → view round trip (the V2 schema dropped it).
    assert view["remote"] is True


def test_brief_lifecycle_status(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    brief = _create_brief(client)
    res = client.patch(
        f"/api/v1/recruiter/briefs/{brief['id']}", json={"status": "closed"}
    )
    assert res.status_code == 200
    assert res.json()["brief"]["status"] == "closed"
    res = client.patch(
        f"/api/v1/recruiter/briefs/{brief['id']}", json={"status": "hired"}
    )
    assert res.status_code == 422


def test_brief_list_and_delete(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    brief = _brief_with_pool(client, title="AI Engineer — Fall 2026")
    listing = client.get("/api/v1/recruiter/briefs").json()
    assert listing["total"] == 1
    item = listing["briefs"][0]
    assert item["title"] == "AI Engineer — Fall 2026"
    assert item["candidate_count"] == 3
    assert item["shortlisted_count"] == 0

    res = client.delete(f"/api/v1/recruiter/briefs/{brief['id']}")
    assert res.status_code == 200 and res.json()["deleted"] is True
    assert client.get(f"/api/v1/recruiter/briefs/{brief['id']}").status_code == 404
    assert client.get("/api/v1/recruiter/briefs").json()["total"] == 0


def test_brief_isolation(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    brief = _brief_with_pool(client)
    _as_user(RECRUITER_B)
    assert client.get("/api/v1/recruiter/briefs").json()["total"] == 0
    base = f"/api/v1/recruiter/briefs/{brief['id']}"
    assert client.get(base).status_code == 404
    assert client.patch(base, json={"title": "mine"}).status_code == 404
    assert client.delete(base).status_code == 404
    assert client.get(f"{base}/candidates").status_code == 404
    assert (
        client.post(
            f"{base}/candidates", json={"connection_ids": ["conn-u-alpha"]}
        ).status_code
        == 404
    )
    assert client.get(f"{base}/comparison").status_code == 404
    assert client.get(f"{base}/search").status_code == 404


# ── Role-scoped candidate pool ───────────────────────────────────────────────


def test_add_candidates_idempotent_and_deduped(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    brief = _create_brief(client)
    result = _add(client, brief["id"], ALL_CONNECTIONS)
    assert result["added"] == 3
    assert result["already_in_brief"] == 0

    # Re-add one by connection AND slug (same human): nothing duplicates.
    res = client.post(
        f"/api/v1/recruiter/briefs/{brief['id']}/candidates",
        json={"connection_ids": ["conn-u-alpha"], "candidate_slugs": ["alpha"]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["added"] == 0
    assert body["already_in_brief"] == 1

    listing = client.get(
        f"/api/v1/recruiter/briefs/{brief['id']}/candidates"
    ).json()
    assert listing["total"] == 3
    assert listing["status_counts"] == {
        "saved": 3, "reviewing": 0, "shortlisted": 0, "contacted": 0,
        "interview": 0, "decision": 0, "hired": 0, "passed": 0, "archived": 0,
    }


def test_pool_candidates_carry_live_evaluation(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    brief = _brief_with_pool(client)
    listing = client.get(
        f"/api/v1/recruiter/briefs/{brief['id']}/candidates"
    ).json()
    alpha = next(
        c for c in listing["candidates"] if c["student_user_id"] == "u-alpha"
    )
    assert alpha["candidate"]["display_name"] == "Alpha Candidate"
    assert alpha["connection_id"] == "conn-u-alpha"
    evaluation = alpha["evaluation"]
    assert evaluation["available"] is True
    assert evaluation["counts"]["required_proven"] == 3
    assert evaluation["counts"]["required_total"] == 3
    assert "Natural Language Processing" in evaluation["missing_preferred"]


def test_foreign_connection_add_is_not_found(
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
    brief = _create_brief(client)
    res = client.post(
        f"/api/v1/recruiter/briefs/{brief['id']}/candidates",
        json={"connection_ids": ["conn-foreign"]},
    )
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "candidate_not_found"


def test_role_scoped_status_and_note(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    brief = _brief_with_pool(client)
    res = client.patch(
        f"/api/v1/recruiter/briefs/{brief['id']}/candidates/u-alpha",
        json={"status": "shortlisted", "note": "Strong FastAPI + ML."},
    )
    assert res.status_code == 200, res.text
    candidate = res.json()["candidate"]
    assert candidate["status"] == "shortlisted"
    assert candidate["note"] == "Strong FastAPI + ML."

    listing = client.get(
        f"/api/v1/recruiter/briefs/{brief['id']}/candidates"
    ).json()
    assert listing["status_counts"]["shortlisted"] == 1
    assert listing["status_counts"]["saved"] == 2

    # Note clears explicitly, status untouched.
    res = client.patch(
        f"/api/v1/recruiter/briefs/{brief['id']}/candidates/u-alpha",
        json={"clear_note": True},
    )
    assert res.json()["candidate"]["note"] is None
    assert res.json()["candidate"]["status"] == "shortlisted"

    # V4 pipeline stages are accepted (9-stage vocabulary, migration 069).
    res = client.patch(
        f"/api/v1/recruiter/briefs/{brief['id']}/candidates/u-alpha",
        json={"status": "hired"},
    )
    assert res.status_code == 200
    assert res.json()["candidate"]["status"] == "hired"

    # Unknown status rejected at the schema boundary.
    res = client.patch(
        f"/api/v1/recruiter/briefs/{brief['id']}/candidates/u-alpha",
        json={"status": "onboarded"},
    )
    assert res.status_code == 422


def test_status_is_role_scoped_not_global(
    client: TestClient, mem_store: dict
) -> None:
    """Shortlisted for AI Engineer, merely saved for Backend Engineer."""
    _seed(mem_store)
    ai_brief = _brief_with_pool(client, title="AI Engineer")
    backend_brief = _create_brief(
        client, title="Backend Engineer", role_text="Python and FastAPI required."
    )
    _add(client, backend_brief["id"], ["conn-u-alpha"])

    client.patch(
        f"/api/v1/recruiter/briefs/{ai_brief['id']}/candidates/u-alpha",
        json={"status": "shortlisted"},
    )

    ai_listing = client.get(
        f"/api/v1/recruiter/briefs/{ai_brief['id']}/candidates"
    ).json()
    backend_listing = client.get(
        f"/api/v1/recruiter/briefs/{backend_brief['id']}/candidates"
    ).json()
    ai_alpha = next(
        c for c in ai_listing["candidates"] if c["student_user_id"] == "u-alpha"
    )
    backend_alpha = next(
        c for c in backend_listing["candidates"] if c["student_user_id"] == "u-alpha"
    )
    assert ai_alpha["status"] == "shortlisted"
    assert backend_alpha["status"] == "saved"

    # The workspace connection itself carries NO status anywhere.
    workspace = client.get("/api/v1/recruiter/connections").json()
    assert all("status" not in c for c in workspace["connections"])


def test_remove_candidate_from_pool(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    brief = _brief_with_pool(client)
    res = client.delete(
        f"/api/v1/recruiter/briefs/{brief['id']}/candidates/u-charlie"
    )
    assert res.status_code == 200 and res.json()["removed"] is True
    listing = client.get(
        f"/api/v1/recruiter/briefs/{brief['id']}/candidates"
    ).json()
    assert listing["total"] == 2
    # Removing again: indistinguishable from never-there.
    res = client.delete(
        f"/api/v1/recruiter/briefs/{brief['id']}/candidates/u-charlie"
    )
    assert res.status_code == 404


# ── Matrix evaluation (live view over the brief) ─────────────────────────────


def test_matrix_states_match_scenario_one(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    brief = _brief_with_pool(client)
    matrix = _matrix(client, brief["id"])

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
    brief = _brief_with_pool(client)
    res = client.get(f"/api/v1/recruiter/briefs/{brief['id']}/comparison")
    text = str(res.json())
    assert "score" not in text.lower()
    assert "%" not in text
    counts = _column(res.json()["matrix"], "alpha")["counts"]
    assert counts["required_proven"] == 3
    assert counts["required_total"] == 3
    assert counts["preferred_proven"] == 0
    assert counts["preferred_total"] == 2


def test_proven_cells_carry_provenance(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    brief = _brief_with_pool(client)
    matrix = _matrix(client, brief["id"])
    cell = _cell(matrix, "alpha", "FastAPI")
    assert cell["proof_path"] == "/p/alpha/skills/fastapi"
    assert cell["projects"][0]["public_report_path"] == "/r/fastapi"
    assert cell["traces"][0]["summary"].startswith("Uses FastAPI")
    assert cell["evidence_sources"] == ["GitHub Proof"]


def test_missing_evidence_shows_related_not_proof(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    brief = _brief_with_pool(client)
    matrix = _matrix(client, brief["id"])
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
    brief = _create_brief(
        client, role_text=None, requirements={"required": ["Docker"]}
    )
    _add(client, brief["id"], ["conn-u-alpha", "conn-u-charlie"])
    matrix = _matrix(client, brief["id"])
    cell = _cell(matrix, "charlie", "Docker")
    assert cell["state"] == "claimed"
    assert "not verified" in cell["note"]
    assert cell["proof_path"] is None
    assert _cell(matrix, "alpha", "Docker")["state"] == "none"


def test_zero_coverage_note_when_everyone_lacks_proof(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    brief = _create_brief(
        client, role_text=None, requirements={"required": ["Data Engineering"]}
    )
    _add(client, brief["id"], ALL_CONNECTIONS)
    matrix = _matrix(client, brief["id"])
    assert any(
        "No selected candidate has published Data Engineering evidence" in n
        for n in matrix["notes"]
    )


def test_excluded_concept_flags_but_keeps_column(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    brief = _create_brief(
        client,
        role_text=None,
        requirements={"required": ["Python"], "excluded": ["Computer Vision"]},
    )
    _add(client, brief["id"], ALL_CONNECTIONS)
    matrix = _matrix(client, brief["id"])
    charlie = _column(matrix, "charlie")
    assert charlie["excluded_hits"] == ["Computer Vision"]
    assert charlie["available"] is True
    assert _column(matrix, "alpha")["excluded_hits"] == []


def test_comparison_limits(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    brief = _create_brief(client)
    _add(client, brief["id"], ["conn-u-alpha"])
    res = client.get(f"/api/v1/recruiter/briefs/{brief['id']}/comparison")
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "too_few_candidates"

    # Six pool candidates explicitly selected → too many.
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
    _add(client, brief["id"], [f"conn-u-x{i}" for i in range(6)])
    selected = ",".join(f"u-x{i}" for i in range(6))
    res = client.get(
        f"/api/v1/recruiter/briefs/{brief['id']}/comparison?candidates={selected}"
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "too_many_candidates"


def test_comparison_rejects_non_pool_candidate(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    brief = _create_brief(client)
    _add(client, brief["id"], ["conn-u-alpha", "conn-u-bravo"])
    # u-charlie is saved to the workspace but NOT in this brief's pool.
    res = client.get(
        f"/api/v1/recruiter/briefs/{brief['id']}/comparison"
        "?candidates=u-alpha,u-charlie"
    )
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "candidate_not_found"


def test_default_comparison_skips_archived(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    brief = _brief_with_pool(client)
    client.patch(
        f"/api/v1/recruiter/briefs/{brief['id']}/candidates/u-charlie",
        json={"status": "archived"},
    )
    matrix = _matrix(client, brief["id"])
    user_ids = [c["user_id"] for c in matrix["columns"]]
    assert user_ids == ["u-alpha", "u-bravo"]


def test_matrix_column_carries_role_scoped_status(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    brief = _brief_with_pool(client)
    client.patch(
        f"/api/v1/recruiter/briefs/{brief['id']}/candidates/u-alpha",
        json={"status": "shortlisted"},
    )
    matrix = _matrix(client, brief["id"])
    alpha = _column(matrix, "alpha")
    assert alpha["connection"] == {"id": "conn-u-alpha"}
    assert alpha["brief_status"] == "shortlisted"
    assert _column(matrix, "bravo")["brief_status"] == "saved"


def test_requirements_edit_re_evaluates(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    brief = _brief_with_pool(client)
    # Edit chips: drop ML, promote NLP to required — the next comparison
    # load reflects it (comparison is a live view; nothing is snapshotted).
    res = client.patch(
        f"/api/v1/recruiter/briefs/{brief['id']}",
        json={"requirements": {"required": ["Python", "FastAPI", "NLP"]}},
    )
    assert res.status_code == 200
    matrix = _matrix(client, brief["id"])
    displays = [r["display"] for r in matrix["requirements"]]
    assert displays == ["Python", "FastAPI", "Natural Language Processing"]
    assert _cell(matrix, "bravo", "Natural Language Processing")["state"] == "proven"


# ── Live fail-closed re-evaluation ───────────────────────────────────────────


def test_unpublished_candidate_degrades_on_reload(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    brief = _brief_with_pool(client)
    mem_store["vbr_work_passports"]["pp-u-bravo"]["is_published"] = False

    matrix = _matrix(client, brief["id"])
    bravo = next(c for c in matrix["columns"] if c["user_id"] == "u-bravo")
    assert bravo["available"] is False
    assert bravo["cells"] == {}
    assert bravo["public_slug"] is None
    assert "no longer publicly available" in bravo["unavailable_note"]
    assert any("no longer publicly available" in n for n in matrix["notes"])
    assert _column(matrix, "alpha")["available"] is True

    # The pool listing evaluates honestly as unavailable too.
    listing = client.get(
        f"/api/v1/recruiter/briefs/{brief['id']}/candidates"
    ).json()
    bravo_row = next(
        c for c in listing["candidates"] if c["student_user_id"] == "u-bravo"
    )
    assert bravo_row["evaluation"]["available"] is False
    assert bravo_row["candidate"]["public_slug"] is None


def test_disclosure_version_bump_fails_closed(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    brief = _brief_with_pool(client)
    mem_store["passport_disclosure_policies"] = {
        "pol-1": {"user_id": "u-alpha", "disclosure_version": 7}
    }
    matrix = _matrix(client, brief["id"])
    assert next(
        c for c in matrix["columns"] if c["user_id"] == "u-alpha"
    )["available"] is False


def test_discovery_exclusion_fails_closed(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    brief = _brief_with_pool(client)
    mem_store["recruiter_discovery_exclusions"] = {
        "u-charlie": {"user_id": "u-charlie", "reason": "qa fixture"}
    }
    matrix = _matrix(client, brief["id"])
    assert next(
        c for c in matrix["columns"] if c["user_id"] == "u-charlie"
    )["available"] is False


# ── Brief-scoped search ──────────────────────────────────────────────────────


def test_brief_search_runs_stored_plan(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    brief = _create_brief(client)
    _add(client, brief["id"], ["conn-u-alpha"])
    client.patch(
        f"/api/v1/recruiter/briefs/{brief['id']}/candidates/u-alpha",
        json={"status": "shortlisted"},
    )

    res = client.get(f"/api/v1/recruiter/briefs/{brief['id']}/search")
    assert res.status_code == 200, res.text
    body = res.json()
    # The stored plan drives the search: same interpretation as the brief.
    assert [c["display"] for c in body["interpretation"]["required"]] == [
        "Python", "FastAPI", "Machine Learning",
    ]
    slugs = [r["public_slug"] for r in body["results"]]
    assert "alpha" in slugs

    alpha = next(r for r in body["results"] if r["public_slug"] == "alpha")
    assert alpha["in_brief"] is True
    assert alpha["brief_status"] == "shortlisted"
    outside = [r for r in body["results"] if r["public_slug"] != "alpha"]
    assert all(r["in_brief"] is False and r["brief_status"] is None for r in outside)


def test_brief_search_refinement_is_temporary(
    client: TestClient, mem_store: dict
) -> None:
    _seed(mem_store)
    brief = _create_brief(client, role_text="Python required.")
    res = client.get(
        f"/api/v1/recruiter/briefs/{brief['id']}/search",
        params={"q": "NLP required"},
    )
    assert res.status_code == 200
    required = [c["display"] for c in res.json()["interpretation"]["required"]]
    assert "Natural Language Processing" in required
    # The stored brief was NOT mutated by the refinement.
    stored = client.get(f"/api/v1/recruiter/briefs/{brief['id']}").json()["brief"]
    assert [c["display"] for c in stored["requirements_view"]["required"]] == [
        "Python"
    ]


# ── Analytics ────────────────────────────────────────────────────────────────


def test_brief_events_are_privacy_safe(client: TestClient, mem_store: dict) -> None:
    _seed(mem_store)
    brief = _brief_with_pool(client, title="Secret Internal Req Name")
    client.patch(
        f"/api/v1/recruiter/briefs/{brief['id']}/candidates/u-alpha",
        json={"note": "private candidate note"},
    )
    client.get(f"/api/v1/recruiter/briefs/{brief['id']}/comparison")

    events = list(mem_store.get("recruiter_search_events", {}).values())
    assert any(e["filters"].get("brief") == "created" for e in events)
    assert any(e["filters"].get("brief") == "comparison" for e in events)
    dump = str(events)
    # Never titles, notes, or candidate identity in events.
    assert "Secret Internal Req Name" not in dump
    assert "private candidate note" not in dump
    assert "Alpha Candidate" not in dump
