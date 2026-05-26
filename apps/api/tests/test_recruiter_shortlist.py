"""Tests for recruiter saved passport / shortlist backend."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.recruiter_shortlist_service import RecruiterShortlistService


USER_ID = "00000000-0000-0000-0000-000000000042"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_public_passport(mem_store: dict, slug: str = "saved-passport") -> dict[str, str]:
    session_id = str(uuid4())
    passport_id = str(uuid4())
    mem_store.setdefault("extension_proof_sessions", {})[session_id] = {
        "id": session_id,
        "user_id": USER_ID,
        "status": "completed",
    }
    mem_store.setdefault("public_work_passports", {})[passport_id] = {
        "id": passport_id,
        "user_id": USER_ID,
        "proof_session_id": session_id,
        "public_slug": slug,
        "is_public": True,
        "public_title": "Evidence portfolio",
        "public_summary": "Public-safe summary.",
        "field": "General",
        "access_token": "private-passport-token",
        "media_storage_path": "private/media/path.webm",
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("project_defense_analysis_results", {})["defense"] = {
        "id": "defense",
        "user_id": USER_ID,
        "proof_session_id": session_id,
        "transcript_text": "Private transcript must not appear.",
        "media_storage_path": "private/defense/audio.mp3",
    }
    return {"session_id": session_id, "passport_id": passport_id}


def _save(client: TestClient, slug: str = "saved-passport", **overrides: object) -> dict:
    payload = {
        "requester_email": "Recruiter@Example.com",
        "requester_name": "Recruiter Person",
        "organization_name": "Example Org",
        "status": "saved",
        "tags": ["backend"],
        "private_notes": "Promising candidate.",
        **overrides,
    }
    response = client.post(f"/api/v1/public/passports/{slug}/save", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _audit_events(mem_store: dict, event_type: str) -> list[dict]:
    return [
        event for event in mem_store.get("evidence_access_audit_events", {}).values()
        if event.get("event_type") == event_type
    ]


def test_recruiter_can_save_public_passport(client: TestClient, mem_store: dict) -> None:
    ids = _seed_public_passport(mem_store)

    saved = _save(client)

    assert saved["passport_id"] == ids["passport_id"]
    assert saved["requester_email"] == "recruiter@example.com"
    assert saved["status"] == "saved"
    assert len(mem_store["recruiter_saved_passports"]) == 1
    assert len(_audit_events(mem_store, "passport_saved")) == 1


def test_saving_same_passport_twice_updates_existing_record(client: TestClient, mem_store: dict) -> None:
    _seed_public_passport(mem_store)
    first = _save(client, tags=["first"])
    second = _save(client, tags=["second"], private_notes="Updated note.")

    assert second["id"] == first["id"]
    assert second["tags"] == ["second"]
    assert second["private_notes"] == "Updated note."
    assert len(mem_store["recruiter_saved_passports"]) == 1


def test_recruiter_can_shortlist_passport_and_audit_event_is_created(client: TestClient, mem_store: dict) -> None:
    _seed_public_passport(mem_store)

    saved = _save(client, status="shortlisted")

    assert saved["status"] == "shortlisted"
    assert len(_audit_events(mem_store, "candidate_shortlisted")) == 1


def test_recruiter_can_add_tags_private_notes_and_reviewed_sections(client: TestClient, mem_store: dict) -> None:
    _seed_public_passport(mem_store)
    saved = _save(client)

    response = client.patch(
        f"/api/v1/public/recruiter/saved-passports/{saved['id']}",
        json={
            "requester_email": "recruiter@example.com",
            "tags": ["priority", "backend"],
            "private_notes": "Follow up after technical screen.",
            "reviewed_sections": ["github_analysis", "project_defense_summary"],
            "fit_score": 87,
            "fit_reason": "Strong evidence fit.",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["tags"] == ["priority", "backend"]
    assert payload["private_notes"] == "Follow up after technical screen."
    assert payload["reviewed_sections"] == ["github_analysis", "project_defense_summary"]
    assert payload["fit_score"] == 87
    assert len(_audit_events(mem_store, "recruiter_note_updated")) == 1


def test_recruiter_can_list_only_their_saved_passports(client: TestClient, mem_store: dict) -> None:
    _seed_public_passport(mem_store, "one")
    _save(client, slug="one", requester_email="one@example.com")
    _seed_public_passport(mem_store, "two")
    _save(client, slug="two", requester_email="two@example.com")

    response = client.get("/api/v1/public/recruiter/saved-passports", params={"requester_email": "one@example.com"})

    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["requester_email"] == "one@example.com"
    assert rows[0]["public_slug"] == "one"


def test_recruiter_cannot_update_another_requesters_saved_passport(client: TestClient, mem_store: dict) -> None:
    _seed_public_passport(mem_store)
    saved = _save(client, requester_email="owner@example.com")

    response = client.patch(
        f"/api/v1/public/recruiter/saved-passports/{saved['id']}",
        json={"requester_email": "other@example.com", "status": "shortlisted"},
    )

    assert response.status_code == 404


def test_saved_passport_response_does_not_expose_private_evidence_or_tokens(client: TestClient, mem_store: dict) -> None:
    _seed_public_passport(mem_store)

    saved = _save(client)

    serialized = json.dumps(saved).lower()
    assert "private-passport-token" not in serialized
    assert "media_storage_path" not in serialized
    assert "private transcript" not in serialized
    assert "private/media" not in serialized


def test_requester_profile_is_created_and_updated(client: TestClient, mem_store: dict) -> None:
    _seed_public_passport(mem_store)

    _save(client, requester_email="Recruiter@Example.com", organization_name="Example Org")

    profiles = list(mem_store["recruiter_requester_profiles"].values())
    assert len(profiles) == 1
    assert profiles[0]["email"] == "recruiter@example.com"
    assert profiles[0]["organization_domain"] == "example.com"
    assert profiles[0]["organization_name"] == "Example Org"


def test_no_project_specific_hardcoding() -> None:
    source = inspect.getsource(RecruiterShortlistService).lower()

    assert "boston" not in source
    assert "react demo" not in source
    assert "repo name" not in source
