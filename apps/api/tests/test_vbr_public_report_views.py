"""Tests for public report view tracking + public token hardening (v1).

Public (no auth):
  ``POST /api/v1/public/vbr/reports/{public_token}/view``
  ``GET  /api/v1/public/vbr/reports/{public_token}``

Covers:
  - a view event is recorded for an actively published token only
  - draft (never published) and revoked tokens record nothing and stay 404
  - malformed / oversized / implausible tokens fail safely (no 500s)
  - the tracker is fail-open: a broken analytics table never blocks the
    report GET and never surfaces an error to the recruiter
  - dedupe: the same (project, dedupe_key) records exactly one row
  - source attribution is a closed enum; junk collapses to "unknown"
  - referrer / user-agent are stored as coarse categories only — never raw
  - token confusion: one student's token can never resolve another's report
  - no sequential enumeration path (numeric / short ids never resolve)

All storage is in-memory (dict mode). No real network calls, no LLM calls.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.services import vbr_report_view_service
from app.services.vbr_report_view_service import (
    classify_referrer,
    classify_user_agent,
    normalize_dedupe_key,
    normalize_view_source,
)

from tests.conftest import seed_published_passport
from tests.test_vbr_project_defense import (
    OTHER_USER_ID,
    USER_ID,
    _create_project_defense,
)

_VIEWS_TABLE = "vbr_project_report_views"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def mem_store() -> dict:
    store: dict = {}
    # View tracking resolves tokens with the same visibility gate as the
    # public read: the owner's Passport must be Public.
    seed_published_passport(store, USER_ID)
    seed_published_passport(store, OTHER_USER_ID)
    return store


@pytest.fixture()
def pipeline_db() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict, pipeline_db: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: pipeline_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _publish(client: TestClient, project_id: str) -> str:
    response = client.post(f"/api/v1/student/vbr/projects/{project_id}/public-report")
    assert response.status_code == 200, response.text
    return response.json()["public_token"]


def _unpublish(client: TestClient, project_id: str) -> None:
    assert client.delete(
        f"/api/v1/student/vbr/projects/{project_id}/public-report"
    ).status_code == 200


def _post_view(client: TestClient, token: str, body: dict | None = None):
    return client.post(f"/api/v1/public/vbr/reports/{token}/view", json=body)


def _view_rows(mem_store: dict) -> list[dict]:
    return list(mem_store.get(_VIEWS_TABLE, {}).values())


def _published_project(client: TestClient) -> tuple[str, str]:
    project_id = _create_project_defense(client).json()["project"]["id"]
    return project_id, _publish(client, project_id)


# ── Recording ────────────────────────────────────────────────────────────────

def test_view_recorded_for_published_token(client: TestClient, mem_store: dict) -> None:
    project_id, token = _published_project(client)

    response = _post_view(client, token, {"source": "direct"})
    assert response.status_code == 200
    assert response.json() == {"recorded": True}

    rows = _view_rows(mem_store)
    assert len(rows) == 1
    assert rows[0]["project_id"] == project_id
    assert rows[0]["source"] == "direct"


def test_view_works_without_body(client: TestClient, mem_store: dict) -> None:
    _, token = _published_project(client)
    response = _post_view(client, token)
    assert response.status_code == 200
    assert response.json()["recorded"] is True
    assert _view_rows(mem_store)[0]["source"] == "unknown"


def test_view_requires_no_auth(client: TestClient) -> None:
    _, token = _published_project(client)
    app.dependency_overrides.pop(get_current_user_id, None)
    assert _post_view(client, token, {"source": "recruiter_open"}).json()["recorded"] is True


def test_draft_report_records_nothing(client: TestClient, mem_store: dict) -> None:
    # Project exists but was never published — no active token can exist, so
    # even a correctly-shaped guess must record nothing.
    _create_project_defense(client)
    response = _post_view(client, "A" * 32, {"source": "direct"})
    assert response.status_code == 200
    assert response.json() == {"recorded": False}
    assert _view_rows(mem_store) == []


def test_revoked_token_records_nothing(client: TestClient, mem_store: dict) -> None:
    project_id, token = _published_project(client)
    _unpublish(client, project_id)

    assert client.get(f"/api/v1/public/vbr/reports/{token}").status_code == 404
    assert _post_view(client, token, {"source": "direct"}).json() == {"recorded": False}
    assert _view_rows(mem_store) == []


# ── Fail-safety ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "bad_token",
    [
        "x",                     # implausibly short
        "a" * 5000,              # oversized
        "..%2f..%2fetc",         # traversal-ish / bad charset
        "tok en",                # whitespace
        "<script>alert(1)</script>",
        "javascript:alert(1)",
    ],
)
def test_malformed_tokens_fail_safely(client: TestClient, mem_store: dict, bad_token: str) -> None:
    # Tokens with encoded slashes (%2f) or embedded "/" miss the route and get
    # the framework's plain 404; everything else gets the safe report-not-found
    # body. Either way: 404, no 500, no stack trace, nothing recorded.
    get_response = client.get(f"/api/v1/public/vbr/reports/{bad_token}")
    assert get_response.status_code == 404
    detail = get_response.json()["detail"]
    if isinstance(detail, dict):
        assert detail["code"] == "vbr_public_report_not_found"

    view_response = _post_view(client, bad_token, {"source": "direct"})
    assert view_response.status_code in (200, 404)
    if view_response.status_code == 200:
        assert view_response.json() == {"recorded": False}
    assert _view_rows(mem_store) == []


def test_no_sequential_enumeration_path(client: TestClient) -> None:
    project_id, _ = _published_project(client)
    # Neither the internal project id nor small sequential ids may resolve.
    for guess in ("1", "2", "0001", project_id):
        assert client.get(f"/api/v1/public/vbr/reports/{guess}").status_code == 404


def test_tracking_failure_never_blocks_report(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, token = _published_project(client)

    def _boom(*args, **kwargs):
        raise RuntimeError("analytics table missing")

    # Patch where the endpoint looked the symbol up (imported into the module).
    import app.api.v1.endpoints.vbr_public_project_report as endpoint_module

    monkeypatch.setattr(endpoint_module, "record_public_report_view", _boom)

    view_response = _post_view(client, token, {"source": "direct"})
    assert view_response.status_code == 200
    assert view_response.json() == {"recorded": False}

    # The report itself remains fully readable.
    assert client.get(f"/api/v1/public/vbr/reports/{token}").status_code == 200


def test_unknown_body_fields_rejected_safely(client: TestClient) -> None:
    _, token = _published_project(client)
    response = _post_view(client, token, {"source": "direct", "camera_frame": "AAAA"})
    assert response.status_code == 422  # schema is closed; no silent storage


# ── Dedupe / attribution ─────────────────────────────────────────────────────

def test_same_dedupe_key_records_once(client: TestClient, mem_store: dict) -> None:
    _, token = _published_project(client)
    body = {"source": "direct", "dedupe_key": "session-key-1234"}

    assert _post_view(client, token, body).json()["recorded"] is True
    assert _post_view(client, token, body).json()["recorded"] is False
    assert len(_view_rows(mem_store)) == 1


def test_distinct_dedupe_keys_record_separately(client: TestClient, mem_store: dict) -> None:
    _, token = _published_project(client)
    assert _post_view(client, token, {"dedupe_key": "recruiter-aaa1"}).json()["recorded"] is True
    assert _post_view(client, token, {"dedupe_key": "recruiter-bbb2"}).json()["recorded"] is True
    assert len(_view_rows(mem_store)) == 2


def test_source_enum_is_closed(client: TestClient, mem_store: dict) -> None:
    _, token = _published_project(client)
    for junk in ("qr'; drop table users;--", "DIRECT_MAIL", "a" * 64):
        _post_view(client, token, {"source": junk})
    sources = {row["source"] for row in _view_rows(mem_store)}
    assert sources == {"unknown"}


def test_recruiter_sources_accepted(client: TestClient, mem_store: dict) -> None:
    _, token = _published_project(client)
    _post_view(client, token, {"source": "recruiter_open"})
    _post_view(client, token, {"source": "recruiter_scan"})
    assert {row["source"] for row in _view_rows(mem_store)} == {
        "recruiter_open",
        "recruiter_scan",
    }


def test_no_raw_referrer_or_user_agent_stored(client: TestClient, mem_store: dict) -> None:
    _, token = _published_project(client)
    client.post(
        f"/api/v1/public/vbr/reports/{token}/view",
        json={"source": "direct"},
        headers={
            "referer": "https://evil.example.com/some/private/path?q=secret",
            "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
        },
    )
    (row,) = _view_rows(mem_store)
    assert row["referrer_category"] == "external"
    assert row["ua_class"] == "mobile"
    flattened = " ".join(str(v) for v in row.values())
    assert "evil.example.com" not in flattened
    assert "Mozilla" not in flattened
    assert "secret" not in flattened


# ── Token confusion / isolation ──────────────────────────────────────────────

def test_token_confusion_between_users_is_impossible(
    client: TestClient, mem_store: dict
) -> None:
    my_project_id, my_token = _published_project(client)

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    other_project_id = _create_project_defense(
        client, title="Other Student Project"
    ).json()["project"]["id"]
    other_token = _publish(client, other_project_id)
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID

    assert my_token != other_token

    mine = client.get(f"/api/v1/public/vbr/reports/{my_token}").json()
    theirs = client.get(f"/api/v1/public/vbr/reports/{other_token}").json()
    assert mine["project_title"] != theirs["project_title"]
    assert theirs["project_title"] == "Other Student Project"

    # Views land on the correct project for each token.
    _post_view(client, my_token, {"source": "direct"})
    _post_view(client, other_token, {"source": "direct"})
    by_project = {row["project_id"] for row in _view_rows(mem_store)}
    assert by_project == {my_project_id, other_project_id}


def test_qr_and_direct_resolve_to_same_report(client: TestClient) -> None:
    # The QR encodes the exact canonical URL, so both arrival paths hit the
    # same GET with the same token — the payload must be identical.
    _, token = _published_project(client)
    first = client.get(f"/api/v1/public/vbr/reports/{token}").json()
    second = client.get(f"/api/v1/public/vbr/reports/{token}").json()
    first.pop("generated_at", None)
    second.pop("generated_at", None)
    assert first == second


# ── Classifier units ─────────────────────────────────────────────────────────

def test_classify_referrer_categories() -> None:
    assert classify_referrer(None) == "none"
    assert classify_referrer("") == "none"
    assert classify_referrer("http://localhost:3000/recruiters/open") == "internal"
    assert classify_referrer("https://evil.example.com/") == "external"
    assert classify_referrer("javascript:alert(1)") == "external"
    assert classify_referrer("not a url") == "external"


def test_classify_user_agent_categories() -> None:
    assert classify_user_agent(None) == "unknown"
    assert classify_user_agent("Mozilla/5.0 (Macintosh)") == "desktop"
    assert classify_user_agent("Mozilla/5.0 (Linux; Android 14)") == "mobile"
    assert classify_user_agent("Googlebot/2.1") == "bot"
    assert classify_user_agent("curl/8.4.0") == "bot"


def test_normalizers_collapse_junk() -> None:
    assert normalize_view_source(" Recruiter_Open ") == "recruiter_open"
    assert normalize_view_source({"nested": True}) == "unknown"
    assert normalize_dedupe_key("ok_key-12345") == "ok_key-12345"
    assert normalize_dedupe_key("short") is None
    assert normalize_dedupe_key("x" * 300) is None
    assert normalize_dedupe_key("<script>") is None


def test_record_view_helper_is_project_scoped(mem_store: dict) -> None:
    recorded = vbr_report_view_service.record_public_report_view(
        mem_store, "proj-1", source="direct", dedupe_key="dedupe-key-1"
    )
    duplicate = vbr_report_view_service.record_public_report_view(
        mem_store, "proj-1", source="direct", dedupe_key="dedupe-key-1"
    )
    other_project = vbr_report_view_service.record_public_report_view(
        mem_store, "proj-2", source="direct", dedupe_key="dedupe-key-1"
    )
    assert recorded is True and duplicate is False and other_project is True
    assert len(_view_rows(mem_store)) == 2
