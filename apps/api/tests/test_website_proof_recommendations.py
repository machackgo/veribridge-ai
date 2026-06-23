"""Tests for deterministic Website Proof recommendations (Project Defense).

Covers:
  - owner scoping (a student never sees another student's proofs)
  - the Boston project does NOT recommend unrelated generic doc/playground
    websites (teachablemachine / vega / harryli)
  - the Boston project DOES recommend a proof whose URL/title matches the
    project (boston / accident / rerouting)
  - empty saved proofs returns a safe no-match grouped response
  - the response never includes raw/private fields
  - generic skill overlap alone never promotes a proof

All storage is in-memory (dict mode). No real network calls, no LLM.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.website_proof_recommendation_service import recommend_website_proofs

USER_ID = "00000000-0000-0000-0000-000000000042"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000099"

BOSTON_CONTEXT = {
    "project_title": "Boston Smart Accident Risk Rerouting",
    "project_description": (
        "A smart rerouting project that uses accident-risk, traffic, geospatial, "
        "and cloud/API logic to recommend safer routes instead of only optimizing "
        "for shortest or fastest travel time."
    ),
    "repo_url": "https://github.com/machackgo/boston-smart-accident-risk-rerouting-google-cloud",
    "claimed_skills": ["Python", "Machine Learning", "Google Cloud", "Geospatial"],
}


THREEJS_CONTEXT = {
    "project_title": "Three.js Interactive 3D Website Demo",
    "project_description": (
        "An interactive 3D website/demo built around Three.js concepts, browser-based "
        "rendering, scene setup, camera controls, lighting, and user interaction. The "
        "project demonstrates how WebGL/Three.js can be used to create visual, "
        "interactive web experiences."
    ),
    "repo_url": "https://github.com/mrdoob/three.js",
    "claimed_skills": [
        "JavaScript", "Three.js", "WebGL", "Frontend Development",
        "Interactive UI", "3D Visualization", "Browser APIs",
    ],
}


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_proof(
    mem_store: dict,
    target_website: str,
    *,
    user_id: str = USER_ID,
    supported_skills: list[str] | None = None,
    evidence_strength_score: int = 70,
    workflow_confidence: str = "high",
) -> str:
    proof_session_id = str(uuid4())
    row = {
        "id": str(uuid4()),
        "user_id": user_id,
        "proof_session_id": proof_session_id,
        "target_website": target_website,
        "evidence_strength_score": evidence_strength_score,
        "workflow_confidence": workflow_confidence,
        "supported_skills": supported_skills if supported_skills is not None else ["Machine Learning"],
        "weakly_supported_skills": [],
        # Hostile private fields that must never surface in the response.
        "signed_url": "https://storage.example.co/object/sign/x?token=secret",
        "storage_path": "vbr/sessions/abc/recording.webm",
        "screenshot_url": "https://storage.example.co/shot.png",
        "raw_artifact_data": {"secret": "nope"},
        "created_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("workflow_analysis_results", {})[row["id"]] = row
    return proof_session_id


def _all_session_ids(grouped: dict) -> set[str]:
    ids = set()
    for key in ("recommended_website_proofs", "possible_website_proofs", "other_website_proofs"):
        ids.update(p["proof_session_id"] for p in grouped[key])
    return ids


# ── Owner scoping ────────────────────────────────────────────────────────────

def test_recommendations_are_owner_scoped(client: TestClient, mem_store: dict) -> None:
    mine = _seed_proof(mem_store, "https://boston-smart-accident.vercel.app")
    theirs = _seed_proof(
        mem_store, "https://boston-smart-accident.vercel.app", user_id=OTHER_USER_ID
    )
    resp = client.post("/api/v1/student/website-proof/recommendations", json=BOSTON_CONTEXT)
    assert resp.status_code == 200
    ids = _all_session_ids(resp.json())
    assert mine in ids
    assert theirs not in ids


# ── Strict matching ──────────────────────────────────────────────────────────

def test_boston_does_not_recommend_unrelated_generic_websites(
    client: TestClient, mem_store: dict
) -> None:
    teachable = _seed_proof(
        mem_store, "https://teachablemachine.withgoogle.com", supported_skills=["Machine Learning"]
    )
    vega = _seed_proof(mem_store, "https://vega.github.io", supported_skills=["Data Visualization"])
    harry = _seed_proof(mem_store, "https://harryli0088.github.io", supported_skills=["JavaScript"])

    resp = client.post("/api/v1/student/website-proof/recommendations", json=BOSTON_CONTEXT)
    data = resp.json()

    promoted = {
        p["proof_session_id"]
        for p in data["recommended_website_proofs"] + data["possible_website_proofs"]
    }
    assert teachable not in promoted
    assert vega not in promoted
    assert harry not in promoted

    other_ids = {p["proof_session_id"] for p in data["other_website_proofs"]}
    assert {teachable, vega, harry} <= other_ids
    assert data["has_strong_match"] is False


def test_boston_recommends_matching_project_proof(client: TestClient, mem_store: dict) -> None:
    boston = _seed_proof(
        mem_store, "https://boston-smart-accident.vercel.app", supported_skills=["Machine Learning"]
    )
    teachable = _seed_proof(mem_store, "https://teachablemachine.withgoogle.com")

    resp = client.post("/api/v1/student/website-proof/recommendations", json=BOSTON_CONTEXT)
    data = resp.json()

    recommended_ids = {p["proof_session_id"] for p in data["recommended_website_proofs"]}
    assert boston in recommended_ids
    assert teachable not in recommended_ids
    assert data["has_strong_match"] is True

    # The match reason is safe and explains *why* (project keyword overlap).
    boston_row = next(p for p in data["recommended_website_proofs"] if p["proof_session_id"] == boston)
    assert boston_row["match_label"] == "recommended"
    assert "boston" in boston_row["match_reason"].lower()


def test_threejs_context_recommends_threejs_org(client: TestClient, mem_store: dict) -> None:
    # threejs.org is a known generic/playground domain, but when the project is
    # explicitly about Three.js the saved threejs.org proof must be Recommended —
    # the "three.js" / "threejs" / "threejs.org" spellings all normalise together.
    threejs = _seed_proof(
        mem_store, "https://threejs.org", supported_skills=["JavaScript", "WebGL"]
    )
    resp = client.post("/api/v1/student/website-proof/recommendations", json=THREEJS_CONTEXT)
    data = resp.json()

    recommended_ids = {p["proof_session_id"] for p in data["recommended_website_proofs"]}
    assert threejs in recommended_ids
    assert data["has_strong_match"] is True

    row = next(p for p in data["recommended_website_proofs"] if p["proof_session_id"] == threejs)
    assert row["match_label"] == "recommended"
    assert "threejs" in row["match_reason"].lower()


def test_threejs_context_does_not_recommend_unrelated_generic_sites(
    client: TestClient, mem_store: dict
) -> None:
    # A Three.js project must not pull in *other* unrelated generic playgrounds.
    tensorflow = _seed_proof(mem_store, "https://tensorflow.org", supported_skills=["Machine Learning"])
    teachable = _seed_proof(mem_store, "https://teachablemachine.withgoogle.com")
    resp = client.post("/api/v1/student/website-proof/recommendations", json=THREEJS_CONTEXT)
    data = resp.json()
    promoted = {
        p["proof_session_id"]
        for p in data["recommended_website_proofs"] + data["possible_website_proofs"]
    }
    assert tensorflow not in promoted
    assert teachable not in promoted


def test_generic_project_terms_alone_do_not_match_threejs(client: TestClient, mem_store: dict) -> None:
    # A generic "interactive web app demo" project (no Three.js mention) must not
    # recommend threejs.org just because it is a known web/demo playground.
    threejs = _seed_proof(mem_store, "https://threejs.org", supported_skills=["JavaScript"])
    generic_context = {
        "project_title": "Interactive Web App Demo",
        "project_description": "A generic interactive web application demo project.",
        "repo_url": "https://github.com/someone/web-app-demo",
        "claimed_skills": ["JavaScript", "Web Development"],
    }
    resp = client.post("/api/v1/student/website-proof/recommendations", json=generic_context)
    data = resp.json()
    promoted = {
        p["proof_session_id"]
        for p in data["recommended_website_proofs"] + data["possible_website_proofs"]
    }
    assert threejs not in promoted
    assert threejs in {p["proof_session_id"] for p in data["other_website_proofs"]}


def test_repo_slug_match_in_deploy_url_is_recommended(client: TestClient, mem_store: dict) -> None:
    # A deploy URL that embeds the repo slug words rather than the domain label.
    proof = _seed_proof(mem_store, "https://app.example.com/boston-rerouting-demo")
    resp = client.post("/api/v1/student/website-proof/recommendations", json=BOSTON_CONTEXT)
    data = resp.json()
    promoted = {
        p["proof_session_id"]
        for p in data["recommended_website_proofs"] + data["possible_website_proofs"]
    }
    assert proof in promoted


def test_generic_skill_overlap_alone_does_not_promote(client: TestClient, mem_store: dict) -> None:
    # Proof shares "Machine Learning" with the claimed skills but has nothing
    # project-specific in its URL → must stay in "other".
    proof = _seed_proof(
        mem_store, "https://my-unrelated-ml-portfolio.com", supported_skills=["Machine Learning", "Python"]
    )
    resp = client.post("/api/v1/student/website-proof/recommendations", json=BOSTON_CONTEXT)
    data = resp.json()
    assert proof not in {p["proof_session_id"] for p in data["recommended_website_proofs"]}
    assert proof not in {p["proof_session_id"] for p in data["possible_website_proofs"]}
    assert proof in {p["proof_session_id"] for p in data["other_website_proofs"]}


# ── Empty + safety ───────────────────────────────────────────────────────────

def test_empty_saved_proofs_returns_no_match(client: TestClient) -> None:
    resp = client.post("/api/v1/student/website-proof/recommendations", json=BOSTON_CONTEXT)
    assert resp.status_code == 200
    data = resp.json()
    assert data["recommended_website_proofs"] == []
    assert data["possible_website_proofs"] == []
    assert data["other_website_proofs"] == []
    assert data["has_strong_match"] is False


def test_response_never_includes_private_fields(client: TestClient, mem_store: dict) -> None:
    _seed_proof(mem_store, "https://boston-smart-accident.vercel.app")
    _seed_proof(mem_store, "https://teachablemachine.withgoogle.com")
    resp = client.post("/api/v1/student/website-proof/recommendations", json=BOSTON_CONTEXT)
    body = resp.text
    for leaked in ("signed_url", "storage_path", "screenshot", "raw_artifact_data", "token=", "secret"):
        assert leaked not in body

    # Every returned row exposes only the safe summary + match fields.
    data = resp.json()
    allowed = {
        "proof_session_id", "target_website", "evidence_strength_score",
        "workflow_confidence", "supported_skills", "created_at",
        "match_label", "match_reason",
    }
    for key in ("recommended_website_proofs", "possible_website_proofs", "other_website_proofs"):
        for row in data[key]:
            assert set(row.keys()) <= allowed


# ── Service-level unit checks ────────────────────────────────────────────────

def test_service_dedupes_repeated_urls_keeping_strongest(mem_store: dict) -> None:
    _seed_proof(mem_store, "https://boston-smart-accident.vercel.app", evidence_strength_score=40)
    _seed_proof(mem_store, "https://boston-smart-accident.vercel.app", evidence_strength_score=90)
    result = recommend_website_proofs(mem_store, USER_ID, **BOSTON_CONTEXT)
    recs = result["recommended_website_proofs"]
    assert len(recs) == 1
    assert recs[0]["evidence_strength_score"] == 90
