"""Ownership gates for Website Proof live-feedback push/poll.

The live-feedback store is in-memory (no DB), so both routes must fail closed
on the authoritative extension_proof_sessions ownership row BEFORE touching
the store, and the store itself is keyed per (user_id, session_id) so a stale
entry can never be served cross-user.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.api.v1.endpoints import live_feedback as live_feedback_module
from app.main import app
from app.schemas.live_feedback import EvidenceChecklist, LiveFeedbackState


OWNER = "00000000-0000-0000-0000-000000000001"
FOREIGN = "00000000-0000-0000-0000-000000000002"
SESSION_ID = "00000000-0000-0000-0000-000000000099"

FOREIGN_SECRET_SUGGESTION = "foreign-user-private-live-suggestion"

SIGNALS_BODY = {
    "claimed_skills": ["React"],
    "current_url": "https://app.example.com/dashboard",
    "page_title": "Dashboard",
    "click_count": 3,
    "input_count": 1,
}


def _session_store(owner_user_id: str) -> dict:
    return {
        "extension_proof_sessions": {
            SESSION_ID: {
                "id": SESSION_ID,
                "user_id": owner_user_id,
                "status": "recording",
                "metadata": {},
            }
        }
    }


def _foreign_feedback_state() -> LiveFeedbackState:
    return LiveFeedbackState(
        session_id=SESSION_ID,
        recording_status="recording",
        checklist=EvidenceChecklist(website_loaded=True),
        live_score=87,
        claimed_skill_support=[],
        suggestions=[FOREIGN_SECRET_SUGGESTION],
        sensitive_warning=False,
        last_updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture(autouse=True)
def clean_store():
    live_feedback_module._store.clear()
    yield
    live_feedback_module._store.clear()


def _client(db_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: OWNER
    app.dependency_overrides[get_db] = lambda: db_store
    return TestClient(app)


@pytest.fixture()
def foreign_client():
    """Caller is OWNER; the session belongs to FOREIGN."""
    try:
        yield _client(_session_store(FOREIGN))
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def owner_client():
    """Caller is OWNER and owns the session."""
    try:
        yield _client(_session_store(OWNER))
    finally:
        app.dependency_overrides.clear()


def assert_indistinct_not_found(response) -> None:
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "extension_proof_session_not_found"


URL = f"/api/v1/student/extension-proof/sessions/{SESSION_ID}/live-feedback"


def test_foreign_push_is_denied_and_stores_nothing(foreign_client: TestClient) -> None:
    response = foreign_client.post(URL, json=SIGNALS_BODY)
    assert_indistinct_not_found(response)
    assert not live_feedback_module._store


def test_foreign_poll_is_denied_and_leaks_nothing(foreign_client: TestClient) -> None:
    # The foreign owner already has a live snapshot for this session.
    live_feedback_module._store[(FOREIGN, SESSION_ID)] = _foreign_feedback_state()

    response = foreign_client.get(URL)
    assert_indistinct_not_found(response)
    assert FOREIGN_SECRET_SUGGESTION not in response.text


def test_missing_session_is_indistinguishable_from_foreign(foreign_client: TestClient) -> None:
    missing = "00000000-0000-0000-0000-0000000000aa"
    response = foreign_client.get(
        f"/api/v1/student/extension-proof/sessions/{missing}/live-feedback"
    )
    assert_indistinct_not_found(response)


def test_stale_cross_user_entry_is_never_served_to_session_owner(
    owner_client: TestClient,
) -> None:
    """Even a poisoned/stale entry stored under another user's key stays invisible."""
    live_feedback_module._store[(FOREIGN, SESSION_ID)] = _foreign_feedback_state()

    response = owner_client.get(URL)
    assert response.status_code == 200
    body = response.json()
    # Owner gets the zero-state placeholder, not the foreign snapshot.
    assert body["live_score"] == 0
    assert FOREIGN_SECRET_SUGGESTION not in response.text


def test_owner_push_then_poll_round_trips(owner_client: TestClient) -> None:
    pushed = owner_client.post(URL, json=SIGNALS_BODY)
    assert pushed.status_code == 200
    pushed_body = pushed.json()
    assert pushed_body["session_id"] == SESSION_ID

    polled = owner_client.get(URL)
    assert polled.status_code == 200
    polled_body = polled.json()
    assert polled_body["session_id"] == SESSION_ID
    assert polled_body["live_score"] == pushed_body["live_score"]
    assert polled_body["checklist"] == pushed_body["checklist"]
    assert (OWNER, SESSION_ID) in live_feedback_module._store
