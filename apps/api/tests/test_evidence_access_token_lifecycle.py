"""Evidence-access grant token lifecycle (resurrection + lookup consistency).

Regression tests for:

* F1 — re-approving a revoked / expired / legacy-plaintext grant used to reuse
  the stored credential and clear ``revoked_at``, so a token that had been
  revoked (possibly because it leaked) started working again. Re-approval must
  now mint a NEW token and the old one must stay dead on every endpoint.
* F3 — the timeline, export and github-proofs services looked tokens up by the
  plaintext ``access_token`` column only, while new grants store only
  ``access_token_hash``. All four protected endpoints must resolve hash-only
  grants through the same helper.

Plus: the ``revoked-`` retirement marker, revoked/expired denial, the token
never reaching the logs, and the constant-time comparison path.

Only synthetic, randomly generated token values are used here.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from tests.test_public_work_passport_access import (
    USER_ID,
    _create_passport,
    _make_session,
    _request_access,
)

ENDPOINTS = ("evidence", "skill-evidence-timeline", "export", "github-proofs")
GRANTS = "evidence_access_grants"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _approved(client: TestClient, mem_store: dict, **approve_json) -> tuple[str, dict]:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    request = _request_access(client, passport["public_slug"], ["github_analysis"])
    response = client.post(
        f"/api/v1/student/access-requests/{request['id']}/approve",
        json=approve_json or None,
    )
    assert response.status_code == 200, response.text
    return request["id"], response.json()


def _reapprove(client: TestClient, request_id: str, **approve_json) -> dict:
    response = client.post(
        f"/api/v1/student/access-requests/{request_id}/approve",
        json=approve_json or None,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _status(client: TestClient, token: str, endpoint: str) -> int:
    return client.get(f"/api/v1/public/access/{token}/{endpoint}").status_code


def _grant_row(mem_store: dict, grant_id: str) -> dict:
    return mem_store[GRANTS][grant_id]


def _assert_allowed_everywhere(client: TestClient, token: str) -> None:
    for endpoint in ENDPOINTS:
        response = client.get(f"/api/v1/public/access/{token}/{endpoint}")
        assert response.status_code == 200, (endpoint, response.status_code, response.text[:300])


def _assert_denied_everywhere(client: TestClient, token: str) -> None:
    for endpoint in ENDPOINTS:
        response = client.get(f"/api/v1/public/access/{token}/{endpoint}")
        assert response.status_code == 403, (endpoint, response.status_code)
        assert token not in response.text


# ── F1: re-approval must rotate, never resurrect ──────────────────────────────


def test_revoke_then_reapprove_denies_old_token_on_all_endpoints(client: TestClient, mem_store: dict) -> None:
    request_id, grant = _approved(client, mem_store)
    old_token = grant["access_token"]
    _assert_allowed_everywhere(client, old_token)

    revoke = client.post(f"/api/v1/student/access-grants/{grant['id']}/revoke")
    assert revoke.status_code == 200, revoke.text
    _assert_denied_everywhere(client, old_token)

    regrant = _reapprove(client, request_id)
    new_token = regrant["access_token"]
    assert new_token and new_token.startswith("vbpa_")
    assert new_token != old_token
    assert regrant["revoked_at"] is None

    _assert_denied_everywhere(client, old_token)
    _assert_allowed_everywhere(client, new_token)

    row = _grant_row(mem_store, regrant["id"])
    assert row["access_token"] is None
    assert row["access_token_hash"] == _sha(new_token)
    assert row["access_token_hash"] != _sha(old_token)


def test_expired_then_reapprove_rotates(client: TestClient, mem_store: dict) -> None:
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    request_id, grant = _approved(client, mem_store, expires_at=past)
    old_token = grant["access_token"]
    _assert_denied_everywhere(client, old_token)

    future = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    regrant = _reapprove(client, request_id, expires_at=future)
    new_token = regrant["access_token"]
    assert new_token and new_token != old_token
    _assert_denied_everywhere(client, old_token)
    _assert_allowed_everywhere(client, new_token)
    assert _grant_row(mem_store, regrant["id"])["access_token_hash"] == _sha(new_token)


@pytest.mark.parametrize("backfilled_hash", [False, True], ids=["pre-037", "post-037-backfill"])
@pytest.mark.parametrize("revoke_first", [False, True], ids=["active", "revoked"])
def test_legacy_plaintext_grant_reapprove_rotates_and_clears_plaintext(
    client: TestClient,
    mem_store: dict,
    backfilled_hash: bool,
    revoke_first: bool,
) -> None:
    request_id, grant = _approved(client, mem_store)
    legacy = f"legacy-{secrets.token_urlsafe(18)}"
    row = _grant_row(mem_store, grant["id"])
    row["access_token"] = legacy
    row["access_token_hash"] = _sha(legacy) if backfilled_hash else None
    _assert_allowed_everywhere(client, legacy)

    if revoke_first:
        assert client.post(f"/api/v1/student/access-grants/{grant['id']}/revoke").status_code == 200
        _assert_denied_everywhere(client, legacy)

    regrant = _reapprove(client, request_id)
    new_token = regrant["access_token"]
    assert new_token and new_token.startswith("vbpa_") and new_token != legacy
    row = _grant_row(mem_store, regrant["id"])
    assert row["access_token"] is None, "legacy plaintext must be cleared on re-approval"
    assert row["access_token_hash"] == _sha(new_token)
    _assert_denied_everywhere(client, legacy)
    _assert_allowed_everywhere(client, new_token)


def test_reapprove_active_hash_only_grant_keeps_credential(client: TestClient, mem_store: dict) -> None:
    """Re-approving a still-active, hash-only grant only updates scope; the
    token is not re-emitted (unchanged contract) and keeps working."""
    request_id, grant = _approved(client, mem_store)
    token = grant["access_token"]
    before = dict(_grant_row(mem_store, grant["id"]))
    regrant = _reapprove(client, request_id)
    assert regrant["access_token"] is None
    after = _grant_row(mem_store, grant["id"])
    assert after["access_token_hash"] == before["access_token_hash"] == _sha(token)
    assert after["access_token"] is None
    _assert_allowed_everywhere(client, token)


def test_reapproval_of_retired_marker_row_rotates(client: TestClient, mem_store: dict) -> None:
    """Rows retired in production carry access_token='revoked-…' and a random
    hash. Re-approval must issue a fresh token and drop the marker."""
    request_id, grant = _approved(client, mem_store)
    row = _grant_row(mem_store, grant["id"])
    row["access_token"] = f"revoked-{secrets.token_hex(16)}"
    row["access_token_hash"] = secrets.token_hex(32)
    regrant = _reapprove(client, request_id)
    new_token = regrant["access_token"]
    assert new_token and new_token.startswith("vbpa_")
    row = _grant_row(mem_store, grant["id"])
    assert row["access_token"] is None
    assert row["access_token_hash"] == _sha(new_token)
    _assert_allowed_everywhere(client, new_token)


# ── New grants are hash-only and work on every endpoint (F3) ─────────────────


def test_new_grant_is_hash_only_and_works_on_all_endpoints(client: TestClient, mem_store: dict) -> None:
    _, grant = _approved(client, mem_store)
    token = grant["access_token"]
    row = _grant_row(mem_store, grant["id"])
    assert row["access_token"] is None
    assert row["access_token_hash"] == _sha(token)
    assert token not in str(mem_store)
    _assert_allowed_everywhere(client, token)


def test_hash_only_grant_does_not_match_stringified_null(client: TestClient, mem_store: dict) -> None:
    """A hash-only row has access_token NULL; the literal string 'None' must not match it."""
    _approved(client, mem_store)
    _assert_denied_everywhere(client, "None")


# ── Denials ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("hash_state", ["null", "sha_of_marker", "random"])
def test_revoked_marker_token_is_denied(client: TestClient, mem_store: dict, hash_state: str) -> None:
    _, grant = _approved(client, mem_store)
    marker = f"revoked-{secrets.token_hex(16)}"
    row = _grant_row(mem_store, grant["id"])
    row["access_token"] = marker
    row["access_token_hash"] = {
        "null": None,
        "sha_of_marker": _sha(marker),
        "random": secrets.token_hex(32),
    }[hash_state]
    _assert_denied_everywhere(client, marker)


def test_legacy_plaintext_fallback_only_for_rows_without_hash(client: TestClient, mem_store: dict) -> None:
    """If a row has a hash, its plaintext column is not an alternative credential."""
    _, grant = _approved(client, mem_store)
    row = _grant_row(mem_store, grant["id"])
    stale = f"legacy-{secrets.token_urlsafe(18)}"
    row["access_token"] = stale  # hash still belongs to the issued token
    _assert_denied_everywhere(client, stale)
    _assert_allowed_everywhere(client, grant["access_token"])


def test_revoked_hash_only_grant_is_denied(client: TestClient, mem_store: dict) -> None:
    _, grant = _approved(client, mem_store)
    _grant_row(mem_store, grant["id"])["revoked_at"] = datetime.now(UTC).isoformat()
    _assert_denied_everywhere(client, grant["access_token"])


def test_expired_hash_only_grant_is_denied(client: TestClient, mem_store: dict) -> None:
    _, grant = _approved(client, mem_store)
    _grant_row(mem_store, grant["id"])["expires_at"] = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
    _assert_denied_everywhere(client, grant["access_token"])


def test_unparseable_expiry_fails_closed(client: TestClient, mem_store: dict) -> None:
    _, grant = _approved(client, mem_store)
    _grant_row(mem_store, grant["id"])["expires_at"] = "not-a-timestamp"
    _assert_denied_everywhere(client, grant["access_token"])


def test_unknown_token_is_denied(client: TestClient, mem_store: dict) -> None:
    _approved(client, mem_store)
    _assert_denied_everywhere(client, f"vbpa_{secrets.token_urlsafe(32)}")


# ── Logging / exception hygiene ──────────────────────────────────────────────


def test_token_never_logged_during_approve_and_resolve(
    client: TestClient,
    mem_store: dict,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.services.public_work_passport_service import (
        EvidenceAccessDeniedError,
        PublicWorkPassportService,
    )
    from app.services.evidence_access_tokens import resolve_grant

    caplog.set_level(logging.DEBUG)
    request_id, grant = _approved(client, mem_store)
    token = grant["access_token"]
    client.post(f"/api/v1/student/access-grants/{grant['id']}/revoke")
    new_token = _reapprove(client, request_id)["access_token"]

    service = PublicWorkPassportService(mem_store)
    assert resolve_grant(mem_store, new_token)["id"] == grant["id"]
    for presented in (token, f"revoked-{secrets.token_hex(8)}", "x" * 4096):
        with pytest.raises(EvidenceAccessDeniedError) as excinfo:
            resolve_grant(mem_store, presented)
        assert presented not in str(excinfo.value)
        assert presented not in repr(excinfo.value.args)
    with pytest.raises(EvidenceAccessDeniedError) as excinfo:
        service.get_protected_evidence(token)
    assert token not in str(excinfo.value)

    logged = caplog.text + "".join(str(r.__dict__) for r in caplog.records)
    for secret in (token, new_token, _sha(token), _sha(new_token)):
        assert secret not in logged


# ── Helper unit tests ─────────────────────────────────────────────────────────


def test_mint_token_format_and_hash() -> None:
    from app.services.evidence_access_tokens import hash_token, mint_token

    seen = set()
    for _ in range(50):
        token, token_hash = mint_token()
        assert token.startswith("vbpa_")
        assert len(token) >= len("vbpa_") + 32  # >= 24 random bytes, url-safe
        assert token_hash == hash_token(token) == _sha(token)
        assert len(token_hash) == 64 and all(c in "0123456789abcdef" for c in token_hash)
        seen.add(token)
    assert len(seen) == 50


@pytest.mark.parametrize(
    "bad",
    [None, "", 123, b"bytes", "revoked-abc", "revoked-", "y" * 2049],
    ids=["none", "empty", "int", "bytes", "marker", "bare-marker", "oversized"],
)
def test_resolve_grant_rejects_malformed_tokens(bad: object) -> None:
    from app.services.evidence_access_tokens import EvidenceAccessDeniedError, resolve_grant

    with pytest.raises(EvidenceAccessDeniedError):
        resolve_grant({}, bad)  # type: ignore[arg-type]


def test_constant_time_comparison_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import evidence_access_tokens as eat

    calls: list[tuple[int, int]] = []
    real = eat.hmac.compare_digest

    def spy(a, b):  # noqa: ANN001
        calls.append((len(a), len(b)))
        return real(a, b)

    monkeypatch.setattr(eat.hmac, "compare_digest", spy)

    legacy = f"legacy-{secrets.token_urlsafe(18)}"
    token, token_hash = eat.mint_token()
    store = {
        GRANTS: {
            "g-legacy": {"id": "g-legacy", "access_token": legacy, "access_token_hash": None, "revoked_at": None, "expires_at": None},
            "g-hash": {"id": "g-hash", "access_token": None, "access_token_hash": token_hash, "revoked_at": None, "expires_at": None},
        }
    }
    assert eat.resolve_grant(store, legacy)["id"] == "g-legacy"
    assert calls, "plaintext comparison must go through hmac.compare_digest"
    calls.clear()
    assert eat.resolve_grant(store, token)["id"] == "g-hash"
    assert calls, "hash comparison must go through hmac.compare_digest"


class _FakeQuery:
    """Minimal PostgREST-style chain recording the filters it was given."""

    def __init__(self, rows: list[dict], log: list[tuple[str, str]]) -> None:
        self._rows = rows
        self._log = log
        self._filters: list[tuple[str, str]] = []

    def select(self, *_a):
        return self

    def eq(self, field: str, value: str):
        self._filters.append((field, value))
        self._log.append((field, value))
        return self

    def limit(self, _n: int):
        return self

    def execute(self):
        rows = [r for r in self._rows if all(str(r.get(f)) == v for f, v in self._filters)]

        class _R:
            data = rows

        return _R()


class _FakeClient:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.log: list[tuple[str, str]] = []

    def table(self, name: str) -> _FakeQuery:
        assert name == GRANTS
        return _FakeQuery(self.rows, self.log)


def test_resolve_grant_queries_by_hash_then_legacy_only_for_hashless_rows() -> None:
    from app.services.evidence_access_tokens import EvidenceAccessDeniedError, mint_token, resolve_grant

    token, token_hash = mint_token()
    legacy = f"legacy-{secrets.token_urlsafe(18)}"
    shadowed = f"legacy-{secrets.token_urlsafe(18)}"
    client = _FakeClient(
        [
            {"id": "h", "access_token": None, "access_token_hash": token_hash, "revoked_at": None, "expires_at": None},
            {"id": "l", "access_token": legacy, "access_token_hash": None, "revoked_at": None, "expires_at": None},
            {"id": "s", "access_token": shadowed, "access_token_hash": "0" * 64, "revoked_at": None, "expires_at": None},
        ]
    )
    assert resolve_grant(client, token)["id"] == "h"
    assert client.log[0] == ("access_token_hash", token_hash)
    assert all(field != "access_token" for field, _ in client.log), "no plaintext query when the hash matches"
    assert resolve_grant(client, legacy)["id"] == "l"
    with pytest.raises(EvidenceAccessDeniedError):
        resolve_grant(client, shadowed)
