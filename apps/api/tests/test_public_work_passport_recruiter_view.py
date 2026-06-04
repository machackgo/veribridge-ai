"""Tests for the recruiter-view Work Passport endpoint.

Covers:
1. GET /api/v1/public/passports/{slug}/recruiter-view returns 200 with
   recruiter-safe fields.
2. Private fields (media_storage_path, access tokens, raw transcripts, debug
   metadata) are never present in the response.
3. Skill groups are included with confidence and source labels when
   workflow / final evidence data exists.
4. Proof sources are included with score and status.
5. 404 is returned for unknown or private slugs.
6. access_required flag is present.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.public_work_passport_service import PublicWorkPassportService

USER_ID   = "00000000-0000-0000-0000-000000000042"
SLUG      = "test-candidate-abc12"
SESSION_ID = "10000000-0000-0000-0000-000000000001"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def public_client(mem_store: dict) -> TestClient:
    """Client with no student auth — simulates recruiter hitting the public route."""
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_passport(mem_store: dict, slug: str = SLUG) -> None:
    """Seed the minimum DB state for a public Work Passport."""
    mem_store.setdefault("users", {})[USER_ID] = {
        "id": USER_ID, "email": "student@example.edu", "role": "student",
    }
    mem_store.setdefault("student_profiles", {})[f"prof-{USER_ID}"] = {
        "id": f"prof-{USER_ID}", "user_id": USER_ID,
        "full_name": "Alex Candidate",
        "preferences": {"show_public_name": True},
    }
    mem_store.setdefault("extension_proof_sessions", {})[SESSION_ID] = {
        "id": SESSION_ID, "user_id": USER_ID, "status": "completed",
        "proof_data": {
            "proof_objective": "Demonstrate chatbot UI skills",
            "workflow_events": [],
        },
    }
    mem_store.setdefault("public_work_passports", {})[f"pass-{slug}"] = {
        "id": f"pass-{slug}",
        "user_id": USER_ID,
        "proof_session_id": SESSION_ID,
        "public_slug": slug,
        "is_public": True,
        "public_title": "AI Chatbot Developer",
        "public_summary": "Full-stack engineer with NLP and chatbot experience.",
        "field": "AI / Machine Learning",
        "visible_sections": ["summary", "skills", "public_links"],
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    # Workflow analysis row (what the analyzer produces)
    mem_store.setdefault("workflow_analysis_results", {})[f"wf-{SESSION_ID}"] = {
        "id": f"wf-{SESSION_ID}",
        "user_id": USER_ID,
        "proof_session_id": SESSION_ID,
        "evidence_strength_score": 60,
        "workflow_confidence": "medium",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["Target application loaded: huggingface.co/chat"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Chatbot UI"],
        "weakly_supported_skills": ["Natural Language Processing"],
        "unsupported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "recruiter_summary": "Student demonstrated a chatbot workflow.",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    # GitHub analysis row
    mem_store.setdefault("extension_proof_github_analysis", {})[SESSION_ID] = {
        "id": f"gh-{SESSION_ID}",
        "user_id": USER_ID,
        "proof_session_id": SESSION_ID,
        "status": "success",
        "repo_url": "https://github.com/alex/chatbot-app",
        "confidence_score": 0.75,
        "matched_claimed_skills": ["Chatbot UI", "React"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["React", "Python", "OpenAI"],
        "skill_code_evidence": [],
        "created_at": "2026-01-01T00:00:00+00:00",
    }


# ── 1. Endpoint returns 200 with recruiter-safe structure ─────────────────────

def test_recruiter_view_returns_200(public_client, mem_store):
    _seed_passport(mem_store)
    r = public_client.get(f"/api/v1/public/passports/{SLUG}/recruiter-view")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["public_slug"] == SLUG
    assert "overall_score" in data
    assert "evidence_confidence" in data
    assert "skill_groups" in data
    assert "proof_sources" in data
    assert "why_credible" in data
    assert "suggested_interview_questions" in data
    assert "disclosure_note" in data
    assert "access_request_available" in data
    assert "has_protected_evidence" in data


# ── 2. No private fields exposed ─────────────────────────────────────────────

_PRIVATE_KEYS = {
    "media_storage_path", "media_url", "video_url", "transcript_text",
    "proof_data", "access_token", "raw_risk", "raw_metadata",
    "internal_notes", "debug_metadata", "private_details",
}


def _contains_private_key(obj: object) -> list[str]:
    """Recursively find any private key present in a response body."""
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in _PRIVATE_KEYS or any(p in k.lower() for p in ("private", "debug", "raw_risk")):
                found.append(k)
            found.extend(_contains_private_key(v))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_contains_private_key(item))
    return found


def test_recruiter_view_no_private_fields(public_client, mem_store):
    _seed_passport(mem_store)
    # Add a defense row with transcript_text to confirm it is blocked
    mem_store.setdefault("project_defense_analysis_results", {})[SESSION_ID] = {
        "user_id": USER_ID, "proof_session_id": SESSION_ID,
        "analysis_status": "analyzed",
        "overall_score": 70,
        "transcript_text": "PRIVATE TRANSCRIPT — must not appear in recruiter view",
        "recruiter_summary": "Good ownership signals.",
        "skills_explained_well": ["Chatbot UI"],
        "skills_missing_from_explanation": [],
    }
    r = public_client.get(f"/api/v1/public/passports/{SLUG}/recruiter-view")
    assert r.status_code == 200, r.text
    leaks = _contains_private_key(r.json())
    assert not leaks, f"Private keys found in recruiter-view response: {leaks}"

    body_text = r.text
    assert "PRIVATE TRANSCRIPT" not in body_text, "Raw transcript text must not appear in recruiter view"
    assert "media_storage_path" not in body_text
    assert "access_token" not in body_text


# ── 3. Skill groups present when workflow evidence exists ──────────────────────

def test_recruiter_view_skill_groups_from_evidence(public_client, mem_store):
    _seed_passport(mem_store)
    r = public_client.get(f"/api/v1/public/passports/{SLUG}/recruiter-view")
    assert r.status_code == 200, r.text
    data = r.json()
    # Either skill_groups or flat verified/partial skills must be present
    has_evidence = (
        data.get("skill_groups")
        or data.get("verified_skills")
        or data.get("partially_verified_skills")
    )
    assert has_evidence, "At least one skill evidence list must be populated"


# ── 4. Proof sources present ──────────────────────────────────────────────────

def test_recruiter_view_proof_sources_present(public_client, mem_store):
    _seed_passport(mem_store)
    r = public_client.get(f"/api/v1/public/passports/{SLUG}/recruiter-view")
    assert r.status_code == 200, r.text
    sources = r.json().get("proof_sources", [])
    keys = {s["key"] for s in sources}
    # When workflow analysis was seeded, website_workflow must appear
    assert "website_workflow" in keys or "github" in keys, (
        f"Expected at least website_workflow or github in proof_sources; got {keys}"
    )
    for src in sources:
        assert "key" in src
        assert "label" in src
        assert "status" in src
        assert "score" in src
        assert "is_run" in src


# ── 5. 404 for unknown slug ───────────────────────────────────────────────────

def test_recruiter_view_unknown_slug_returns_404(public_client, mem_store):
    r = public_client.get("/api/v1/public/passports/totally-unknown-xyz/recruiter-view")
    assert r.status_code == 404


# ── 6. access_required flag present ──────────────────────────────────────────

def test_recruiter_view_has_protected_evidence_flag(public_client, mem_store):
    _seed_passport(mem_store)
    r = public_client.get(f"/api/v1/public/passports/{SLUG}/recruiter-view")
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data["has_protected_evidence"], bool)
    assert isinstance(data["access_request_available"], bool)


# ── 7. Non-public passport returns 404 ───────────────────────────────────────

def test_recruiter_view_private_passport_returns_404(public_client, mem_store):
    _seed_passport(mem_store, slug="private-slug-xyz")
    # Mark as non-public
    for row in mem_store["public_work_passports"].values():
        if row["public_slug"] == "private-slug-xyz":
            row["is_public"] = False
    r = public_client.get("/api/v1/public/passports/private-slug-xyz/recruiter-view")
    assert r.status_code == 404


# ── 8. Response is project-agnostic ──────────────────────────────────────────

def test_recruiter_view_does_not_hardcode_project_names(public_client, mem_store):
    _seed_passport(mem_store)
    r = public_client.get(f"/api/v1/public/passports/{SLUG}/recruiter-view")
    assert r.status_code == 200, r.text
    body = r.text
    # Must not hardcode any specific test project names
    for name in ("Three.js", "Hugging Face", "D3", "Leaflet", "Gapminder"):
        assert name not in body, f"Hardcoded project name '{name}' found in response"
