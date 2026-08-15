"""Recruiter ↔ candidate connection API tests (migration 065).

Covers:
  * Save requires authentication (401 without a token).
  * Authenticated save of a published passport creates one connection with
    the recorded acquisition source and a public-only candidate payload.
  * Saves are idempotent: repeat saves return already_saved and never create
    a duplicate row, including under a simulated unique-constraint race.
  * Unknown and unpublished slugs both fail with the same generic 404.
  * Workspace listing returns only the caller's own connections (recruiter
    isolation), newest first, and never leaks emails/auth ids/private
    profile fields.
  * A candidate who unpublishes stays listed but their public_slug goes dark.
  * Status probe reflects saved/unsaved and reveals nothing for unknown slugs.
  * Delete removes only the caller's own connection; another recruiter's id
    404s indistinguishably.
  * Public passport view tracker records coarse events, attributes signed-in
    viewers, dedupes, and never errors for unknown slugs.

All storage is in-memory (dict mode). No network / LLM calls.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from tests.conftest import seed_published_passport
from tests.test_vbr_project_defense import OTHER_USER_ID, USER_ID

RECRUITER_ID = "00000000-0000-0000-0000-0000000000a1"
OTHER_RECRUITER_ID = "00000000-0000-0000-0000-0000000000b2"

CONNECTIONS_URL = "/api/v1/recruiter/connections"


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


def _as_user(user_id: str) -> None:
    app.dependency_overrides[get_current_user_id] = lambda: user_id


def _seed_profile(store: dict, user_id: str, **overrides) -> dict:
    row = {
        "id": f"profile-{user_id}",
        "user_id": str(user_id),
        "full_name": "Ada Lovelace",
        "preferred_name": None,
        "pronunciation": None,
        "headline": "Backend engineer",
        "bio": None,
        "institution": "Analytical Engine U",
        "degree": None,
        "graduation_year": None,
        "location": "London",
        "github_url": None,
        "linkedin_url": None,
        "portfolio_url": None,
        "role_areas": ["backend"],
        "availability": "seeking_internship",
        "work_authorization_note": None,
        "show_location": True,
        "show_availability": True,
        "show_links": True,
        "show_work_authorization": False,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    row.update(overrides)
    store.setdefault("passport_profiles", {})[row["id"]] = row
    return row


# ── Authentication ───────────────────────────────────────────────────────────


def test_save_requires_authentication(mem_store: dict, pipeline_db: dict) -> None:
    """No token → 401; nothing is written."""
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: pipeline_db
    try:
        anonymous = TestClient(app)
        passport = seed_published_passport(mem_store, USER_ID)
        response = anonymous.post(
            CONNECTIONS_URL, json={"passport_slug": passport["public_slug"]}
        )
        assert response.status_code == 401
        assert not mem_store.get("recruiter_candidate_connections")
    finally:
        app.dependency_overrides.clear()


def test_list_requires_authentication(mem_store: dict, pipeline_db: dict) -> None:
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: pipeline_db
    try:
        anonymous = TestClient(app)
        assert anonymous.get(CONNECTIONS_URL).status_code == 401
    finally:
        app.dependency_overrides.clear()


# ── Save ─────────────────────────────────────────────────────────────────────


def test_save_creates_connection_with_source(
    client: TestClient, mem_store: dict
) -> None:
    passport = seed_published_passport(mem_store, USER_ID)
    _seed_profile(mem_store, USER_ID)

    response = client.post(
        CONNECTIONS_URL,
        json={"passport_slug": passport["public_slug"], "source": "qr_scan"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["saved"] is True
    assert body["already_saved"] is False
    assert body["source"] == "qr_scan"
    assert body["candidate"]["display_name"] == "Ada Lovelace"
    assert body["candidate"]["public_slug"] == passport["public_slug"]

    rows = list(mem_store["recruiter_candidate_connections"].values())
    assert len(rows) == 1
    assert rows[0]["recruiter_user_id"] == RECRUITER_ID
    assert rows[0]["student_user_id"] == USER_ID
    assert rows[0]["passport_id"] == passport["id"]


def test_save_is_idempotent(client: TestClient, mem_store: dict) -> None:
    passport = seed_published_passport(mem_store, USER_ID)

    first = client.post(
        CONNECTIONS_URL, json={"passport_slug": passport["public_slug"]}
    )
    second = client.post(
        CONNECTIONS_URL,
        json={"passport_slug": passport["public_slug"], "source": "qr_scan"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["already_saved"] is True
    assert second.json()["id"] == first.json()["id"]
    # Original acquisition source is preserved, not overwritten by repeats.
    assert second.json()["source"] == first.json()["source"]
    assert len(mem_store["recruiter_candidate_connections"]) == 1


def test_save_race_recovers_to_existing_connection(
    mem_store: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two tabs racing the same first save: the loser's unique-violation
    insert recovers by re-reading the winner's row."""
    from app.services import recruiter_connection_service as svc

    passport = seed_published_passport(mem_store, USER_ID)
    winner = svc.save_candidate(mem_store, RECRUITER_ID, passport["public_slug"])

    real_lookup = svc._connection_for_pair
    calls = {"n": 0}

    def racy_lookup(db, recruiter_id, student_id):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # the pre-check misses the winner (race window)
        return real_lookup(db, recruiter_id, student_id)

    def failing_insert(db, row):
        raise Exception("duplicate key value violates unique constraint")

    monkeypatch.setattr(svc, "_connection_for_pair", racy_lookup)
    monkeypatch.setattr(svc, "_insert_connection", failing_insert)

    result = svc.save_candidate(mem_store, RECRUITER_ID, passport["public_slug"])
    assert result["already_saved"] is True
    assert result["id"] == winner["id"]
    assert len(mem_store["recruiter_candidate_connections"]) == 1


def test_save_unknown_and_unpublished_slug_same_404(
    client: TestClient, mem_store: dict
) -> None:
    unpublished = seed_published_passport(
        mem_store, OTHER_USER_ID, is_published=False
    )

    missing = client.post(CONNECTIONS_URL, json={"passport_slug": "no-such-slug"})
    private = client.post(
        CONNECTIONS_URL, json={"passport_slug": unpublished["public_slug"]}
    )
    assert missing.status_code == 404
    assert private.status_code == 404
    assert missing.json() == private.json()
    assert not mem_store.get("recruiter_candidate_connections")


def test_save_invalid_source_normalized(client: TestClient, mem_store: dict) -> None:
    passport = seed_published_passport(mem_store, USER_ID)
    response = client.post(
        CONNECTIONS_URL,
        json={"passport_slug": passport["public_slug"], "source": "evil<script>"},
    )
    assert response.status_code == 200
    assert response.json()["source"] == "direct"


# ── Workspace listing + isolation ────────────────────────────────────────────


def test_list_returns_own_connections_newest_first(
    client: TestClient, mem_store: dict
) -> None:
    passport_a = seed_published_passport(mem_store, USER_ID)
    passport_b = seed_published_passport(mem_store, OTHER_USER_ID)
    _seed_profile(mem_store, USER_ID)

    client.post(CONNECTIONS_URL, json={"passport_slug": passport_a["public_slug"]})
    client.post(
        CONNECTIONS_URL,
        json={"passport_slug": passport_b["public_slug"], "source": "qr_scan"},
    )
    # Force distinct created_at ordering in the dict store.
    rows = sorted(
        mem_store["recruiter_candidate_connections"].values(),
        key=lambda r: r["created_at"],
    )
    rows[0]["created_at"] = "2026-01-01T00:00:00+00:00"
    rows[1]["created_at"] = "2026-02-01T00:00:00+00:00"

    body = client.get(CONNECTIONS_URL).json()
    assert body["total"] == 2
    assert [c["candidate"]["public_slug"] for c in body["connections"]] == [
        passport_b["public_slug"],
        passport_a["public_slug"],
    ]


def test_recruiter_isolation(client: TestClient, mem_store: dict) -> None:
    """One recruiter can never see another recruiter's saved candidates."""
    passport = seed_published_passport(mem_store, USER_ID)
    client.post(CONNECTIONS_URL, json={"passport_slug": passport["public_slug"]})

    _as_user(OTHER_RECRUITER_ID)
    body = client.get(CONNECTIONS_URL).json()
    assert body["total"] == 0
    assert body["connections"] == []


def test_list_never_leaks_private_fields(client: TestClient, mem_store: dict) -> None:
    """Location hidden when show_location is off; never email/user ids."""
    passport = seed_published_passport(mem_store, USER_ID)
    _seed_profile(mem_store, USER_ID, show_location=False, show_availability=False)
    client.post(CONNECTIONS_URL, json={"passport_slug": passport["public_slug"]})

    body = client.get(CONNECTIONS_URL).json()
    candidate = body["connections"][0]["candidate"]
    assert candidate["location"] is None
    assert candidate["availability_label"] is None
    flattened = str(body)
    assert USER_ID not in flattened
    assert "@" not in flattened


def test_unpublished_candidate_stays_listed_without_slug(
    client: TestClient, mem_store: dict
) -> None:
    passport = seed_published_passport(mem_store, USER_ID)
    client.post(CONNECTIONS_URL, json={"passport_slug": passport["public_slug"]})

    passport["is_published"] = False
    body = client.get(CONNECTIONS_URL).json()
    assert body["total"] == 1
    candidate = body["connections"][0]["candidate"]
    assert candidate["is_published"] is False
    assert candidate["public_slug"] is None


# ── Status probe ─────────────────────────────────────────────────────────────


def test_status_probe(client: TestClient, mem_store: dict) -> None:
    passport = seed_published_passport(mem_store, USER_ID)

    before = client.get(
        f"{CONNECTIONS_URL}/status",
        params={"passport_slug": passport["public_slug"]},
    ).json()
    assert before == {"saved": False, "connection_id": None}

    saved = client.post(
        CONNECTIONS_URL, json={"passport_slug": passport["public_slug"]}
    ).json()
    after = client.get(
        f"{CONNECTIONS_URL}/status",
        params={"passport_slug": passport["public_slug"]},
    ).json()
    assert after == {"saved": True, "connection_id": saved["id"]}

    unknown = client.get(
        f"{CONNECTIONS_URL}/status", params={"passport_slug": "no-such-slug"}
    ).json()
    assert unknown == {"saved": False, "connection_id": None}


# ── Delete ───────────────────────────────────────────────────────────────────


def test_delete_own_connection(client: TestClient, mem_store: dict) -> None:
    passport = seed_published_passport(mem_store, USER_ID)
    saved = client.post(
        CONNECTIONS_URL, json={"passport_slug": passport["public_slug"]}
    ).json()

    response = client.delete(f"{CONNECTIONS_URL}/{saved['id']}")
    assert response.status_code == 200
    assert response.json() == {"deleted": True}
    assert not mem_store["recruiter_candidate_connections"]

    # Deleting again → 404 (idempotent from the client's perspective).
    assert client.delete(f"{CONNECTIONS_URL}/{saved['id']}").status_code == 404


def test_delete_other_recruiters_connection_404(
    client: TestClient, mem_store: dict
) -> None:
    passport = seed_published_passport(mem_store, USER_ID)
    saved = client.post(
        CONNECTIONS_URL, json={"passport_slug": passport["public_slug"]}
    ).json()

    _as_user(OTHER_RECRUITER_ID)
    assert client.delete(f"{CONNECTIONS_URL}/{saved['id']}").status_code == 404
    assert len(mem_store["recruiter_candidate_connections"]) == 1


# ── Public passport view tracker ─────────────────────────────────────────────


def test_passport_view_recorded_and_attributed(
    client: TestClient, mem_store: dict
) -> None:
    from app.api.deps import get_optional_user_id

    passport = seed_published_passport(mem_store, USER_ID)

    # Anonymous viewer → no attribution.
    app.dependency_overrides[get_optional_user_id] = lambda: None
    response = client.post(
        f"/api/v1/public/p/{passport['public_slug']}/view",
        json={"source": "qr_scan", "dedupe_key": "abcdefgh12345678"},
    )
    assert response.status_code == 200
    assert response.json() == {"recorded": True}
    rows = list(mem_store["vbr_passport_views"].values())
    assert len(rows) == 1
    assert rows[0]["passport_id"] == passport["id"]
    assert rows[0]["source"] == "qr_scan"
    assert rows[0]["recruiter_user_id"] is None

    # Signed-in viewer → attributed by user id.
    app.dependency_overrides[get_optional_user_id] = lambda: RECRUITER_ID
    client.post(
        f"/api/v1/public/p/{passport['public_slug']}/view",
        json={"source": "shared_link"},
    )
    attributed = [
        r
        for r in mem_store["vbr_passport_views"].values()
        if r["recruiter_user_id"] == RECRUITER_ID
    ]
    assert len(attributed) == 1


def test_passport_view_dedupes(client: TestClient, mem_store: dict) -> None:
    passport = seed_published_passport(mem_store, USER_ID)
    url = f"/api/v1/public/p/{passport['public_slug']}/view"
    payload = {"source": "shared_link", "dedupe_key": "abcdefgh12345678"}

    assert client.post(url, json=payload).json() == {"recorded": True}
    assert client.post(url, json=payload).json() == {"recorded": False}
    assert len(mem_store["vbr_passport_views"]) == 1


def test_passport_view_unknown_slug_is_silent(
    client: TestClient, mem_store: dict
) -> None:
    response = client.post("/api/v1/public/p/no-such-slug/view", json={})
    assert response.status_code == 200
    assert response.json() == {"recorded": False}
    assert not mem_store.get("vbr_passport_views")


def test_passport_view_unpublished_slug_is_silent(
    client: TestClient, mem_store: dict
) -> None:
    passport = seed_published_passport(mem_store, USER_ID, is_published=False)
    response = client.post(
        f"/api/v1/public/p/{passport['public_slug']}/view", json={}
    )
    assert response.json() == {"recorded": False}
    assert not mem_store.get("vbr_passport_views")
