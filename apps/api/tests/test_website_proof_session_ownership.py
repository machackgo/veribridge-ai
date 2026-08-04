"""Ownership gates for controlled browser (Playwright) proof sessions.

The session store is a process-global dict keyed by session_id, so every
lifecycle route must bind the caller to the session's owner user_id.
Foreign callers get responses indistinguishable from a missing session and
can never mutate or destroy another user's live session.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id
from app.main import app
from app.services import website_proof_session_service as svc


OWNER = "00000000-0000-0000-0000-000000000001"
FOREIGN = "00000000-0000-0000-0000-000000000002"
SESSION_ID = "wps-ownership-test-session"

FOREIGN_SECRET_TEXT = "foreign-user-private-page-text"

BASE = "/api/v1/student/website-proof/sessions"


def _seed_session(user_id: str, *, status: str = "waiting_for_manual_login") -> svc._ActiveSession:
    now = datetime.now(UTC)
    session = svc._ActiveSession(
        session_id=SESSION_ID,
        user_id=user_id,
        auth_mode="manual_login_handoff",
        website_url="https://app.example.com",
        frontend_url=None,
        test_input=None,
        expected_output=None,
        workflow_instructions=None,
        status=status,
        created_at=now,
        expires_at=now + timedelta(seconds=svc._SESSION_TTL_SECONDS),
        user_data_dir=None,
        final_page_text=FOREIGN_SECRET_TEXT if user_id == FOREIGN else None,
    )
    with svc._LOCK:
        svc._SESSIONS[SESSION_ID] = session
    return session


@pytest.fixture(autouse=True)
def clean_sessions():
    with svc._LOCK:
        svc._SESSIONS.clear()
    yield
    with svc._LOCK:
        svc._SESSIONS.clear()


@pytest.fixture()
def client():
    app.dependency_overrides[get_current_user_id] = lambda: OWNER
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def assert_indistinct_not_found(response) -> None:
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "proof_session_not_found"
    assert FOREIGN_SECRET_TEXT not in response.text


# ── Foreign callers are denied without side effects ──────────────────────────

def test_foreign_get_is_denied_and_leaks_nothing(client: TestClient) -> None:
    _seed_session(FOREIGN)
    response = client.get(f"{BASE}/{SESSION_ID}")
    assert_indistinct_not_found(response)


def test_foreign_get_matches_missing_session_shape(client: TestClient) -> None:
    _seed_session(FOREIGN)
    foreign = client.get(f"{BASE}/{SESSION_ID}").json()
    missing = client.get(f"{BASE}/does-not-exist").json()
    assert foreign["detail"]["code"] == missing["detail"]["code"]
    assert foreign["detail"]["message"] == missing["detail"]["message"]


def test_foreign_resume_is_denied_without_side_effects(client: TestClient) -> None:
    session = _seed_session(FOREIGN)
    response = client.post(f"{BASE}/{SESSION_ID}/resume")
    assert_indistinct_not_found(response)
    with svc._LOCK:
        assert svc._SESSIONS.get(SESSION_ID) is session
    assert session.status == "waiting_for_manual_login"
    assert session.steps_run == []


def test_foreign_close_is_a_no_op_and_does_not_destroy_session(client: TestClient) -> None:
    session = _seed_session(FOREIGN)
    response = client.post(f"{BASE}/{SESSION_ID}/close")
    # Same response as closing an unknown session: no existence leak.
    assert response.status_code == 200
    assert response.json() == {"status": "closed", "session_id": SESSION_ID}
    with svc._LOCK:
        assert svc._SESSIONS.get(SESSION_ID) is session
    assert session.status == "waiting_for_manual_login"


def test_close_unknown_session_returns_same_response(client: TestClient) -> None:
    response = client.post(f"{BASE}/unknown-session/close")
    assert response.status_code == 200
    assert response.json() == {"status": "closed", "session_id": "unknown-session"}


# ── Owner flow still works ────────────────────────────────────────────────────

def test_owner_get_returns_session(client: TestClient) -> None:
    _seed_session(OWNER)
    response = client.get(f"{BASE}/{SESSION_ID}")
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == SESSION_ID
    assert body["status"] == "waiting_for_manual_login"


def test_owner_resume_of_terminal_session_returns_snapshot(client: TestClient) -> None:
    _seed_session(OWNER, status="completed")
    response = client.post(f"{BASE}/{SESSION_ID}/resume")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_owner_close_destroys_session(client: TestClient) -> None:
    _seed_session(OWNER)
    response = client.post(f"{BASE}/{SESSION_ID}/close")
    assert response.status_code == 200
    assert response.json() == {"status": "closed", "session_id": SESSION_ID}
    with svc._LOCK:
        assert SESSION_ID not in svc._SESSIONS


def test_owner_expired_session_ttl_semantics_unchanged(client: TestClient) -> None:
    session = _seed_session(OWNER)
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    response = client.get(f"{BASE}/{SESSION_ID}")
    # The stale-session sweep evicts it before lookup, exactly as before.
    assert response.status_code in (404, 410)
    with svc._LOCK:
        assert SESSION_ID not in svc._SESSIONS
