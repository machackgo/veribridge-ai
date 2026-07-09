"""Regression tests for cross-tenant auth isolation.

These lock down the root cause of the "every new email sees the original
user's proofs" bug: the ``get_current_user_id`` / ``get_optional_user_id``
dependencies used to fall back to the real ``DEMO_USER_ID`` account whenever a
token was absent, expired, OR unverifiable (e.g. SUPABASE_JWT_SECRET not
configured). That silently attributed every request — including a validly
logged-in *different* user's — to one shared, data-bearing account.

Contract enforced here:
  • A valid token resolves to *its own* ``sub`` — user A and user B never
    collapse to the same identity.
  • A present-but-bad token (expired / wrong signature / unverifiable because
    no secret) always fails closed (401 for required, None for optional) and is
    NEVER downgraded to the demo user, even with the dev fallback enabled.
  • The no-token demo fallback is off unless explicitly enabled AND
    non-production; production ignores it entirely.
  • End-to-end: user B, with a genuine token, cannot see user A's GitHub proof.
"""

from __future__ import annotations

import time
from uuid import uuid4

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

import app.core.auth as auth_module
from app.api.deps import get_current_user_id, get_db, get_optional_user_id
from app.core.auth import SUPABASE_AUDIENCE
from app.core.config import settings
from app.main import app as main_app

_SECRET = "unit-test-jwt-secret-not-for-production"
USER_A = "aaaaaaaa-0000-0000-0000-000000000001"
USER_B = "bbbbbbbb-0000-0000-0000-000000000002"
DEMO_ID = "dddddddd-0000-0000-0000-0000000000de"


def _mint(
    sub: str,
    *,
    secret: str = _SECRET,
    exp_offset: int = 3600,
    aud: str = SUPABASE_AUDIENCE,
) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {
            "sub": sub,
            "aud": aud,
            "iat": now,
            "exp": now + exp_offset,
            "role": "authenticated",
        },
        secret,
        algorithm="HS256",
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── A tiny probe app that exercises the REAL dependencies ─────────────────────
# (not overridden — so the token → identity resolution is what is under test).

_probe = FastAPI()


@_probe.get("/whoami")
def _whoami(uid: str = Depends(get_current_user_id)) -> dict[str, str]:
    return {"user_id": uid}


@_probe.get("/whoami-optional")
def _whoami_optional(uid: str | None = Depends(get_optional_user_id)) -> dict[str, str | None]:
    return {"user_id": uid}


@pytest.fixture()
def probe_client() -> TestClient:
    return TestClient(_probe, raise_server_exceptions=True)


@pytest.fixture()
def dev_auth(monkeypatch: pytest.MonkeyPatch):
    """Development environment, correct secret configured, fallback OFF."""
    monkeypatch.setattr(settings, "supabase_jwt_secret", SecretStr(_SECRET))
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "enable_demo_user_fallback", False)
    monkeypatch.setattr(settings, "demo_user_id", DEMO_ID)
    return settings


# ── get_current_user_id: per-user identity ────────────────────────────────────


def test_valid_token_resolves_to_its_own_user(probe_client: TestClient, dev_auth) -> None:
    a = probe_client.get("/whoami", headers=_bearer(_mint(USER_A)))
    b = probe_client.get("/whoami", headers=_bearer(_mint(USER_B)))
    assert a.status_code == 200 and a.json()["user_id"] == USER_A
    assert b.status_code == 200 and b.json()["user_id"] == USER_B
    # The core anti-regression: two different valid users never collapse.
    assert a.json()["user_id"] != b.json()["user_id"]
    assert DEMO_ID not in (a.json()["user_id"], b.json()["user_id"])


# ── get_current_user_id: bad tokens never become the demo user ────────────────


def test_expired_token_never_downgrades_to_demo(probe_client: TestClient, dev_auth, monkeypatch) -> None:
    # Even with the dev fallback explicitly enabled, a present-but-expired token
    # must fail closed rather than silently become the demo user.
    monkeypatch.setattr(settings, "enable_demo_user_fallback", True)
    res = probe_client.get("/whoami", headers=_bearer(_mint(USER_A, exp_offset=-10)))
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "token_expired"


def test_wrong_signature_token_never_downgrades_to_demo(probe_client: TestClient, dev_auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_demo_user_fallback", True)
    forged = _mint(USER_A, secret="attacker-secret")
    res = probe_client.get("/whoami", headers=_bearer(forged))
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "invalid_token"


def test_unverifiable_token_when_secret_missing_returns_401_not_demo(
    probe_client: TestClient, dev_auth, monkeypatch
) -> None:
    # THE reported bug: SUPABASE_JWT_SECRET not configured. A real user's valid
    # token can't be verified -> must 401, NOT resolve to DEMO_USER_ID.
    monkeypatch.setattr(settings, "supabase_jwt_secret", SecretStr(""))
    monkeypatch.setattr(settings, "enable_demo_user_fallback", True)
    res = probe_client.get("/whoami", headers=_bearer(_mint(USER_A)))
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "invalid_token"


# ── get_current_user_id: no-token fallback is gated ───────────────────────────


def test_no_token_without_fallback_is_401(probe_client: TestClient, dev_auth) -> None:
    res = probe_client.get("/whoami")
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "unauthorized"


def test_no_token_with_fallback_enabled_returns_demo(probe_client: TestClient, dev_auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_demo_user_fallback", True)
    res = probe_client.get("/whoami")
    assert res.status_code == 200
    assert res.json()["user_id"] == DEMO_ID


def test_production_ignores_demo_fallback_even_if_enabled(probe_client: TestClient, dev_auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "enable_demo_user_fallback", True)
    res = probe_client.get("/whoami")
    assert res.status_code == 401


# ── get_optional_user_id: anonymous is None, never the demo owner ─────────────


def test_optional_no_token_without_fallback_is_anonymous(probe_client: TestClient, dev_auth) -> None:
    res = probe_client.get("/whoami-optional")
    assert res.status_code == 200
    # Anonymous — must NOT be treated as the demo OWNER on dual owner/public routes.
    assert res.json()["user_id"] is None


def test_optional_invalid_token_is_anonymous(probe_client: TestClient, dev_auth) -> None:
    res = probe_client.get("/whoami-optional", headers=_bearer(_mint(USER_A, secret="attacker")))
    assert res.status_code == 200
    assert res.json()["user_id"] is None


def test_optional_valid_token_resolves_owner(probe_client: TestClient, dev_auth) -> None:
    res = probe_client.get("/whoami-optional", headers=_bearer(_mint(USER_A)))
    assert res.status_code == 200
    assert res.json()["user_id"] == USER_A


# ── Asymmetric (ES256 / JWKS) verification — the current Supabase scheme ─────
# Current Supabase projects sign access tokens with an ES256 key published via
# the project JWKS, NOT the legacy HS256 secret. These tests lock down the
# real-world dev config: SUPABASE_JWT_SECRET empty, SUPABASE_URL set, tokens
# verified against the JWKS public key — and every unverifiable variant still
# failing closed.

_EC_KEY = ec.generate_private_key(ec.SECP256R1())
_EC_KID = "unit-test-es256-kid"
_ATTACKER_EC_KEY = ec.generate_private_key(ec.SECP256R1())


def _mint_es256(
    sub: str,
    *,
    key=_EC_KEY,
    exp_offset: int = 3600,
    aud: str = SUPABASE_AUDIENCE,
) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {
            "sub": sub,
            "aud": aud,
            "iat": now,
            "exp": now + exp_offset,
            "role": "authenticated",
        },
        key,
        algorithm="ES256",
        headers={"kid": _EC_KID},
    )


class _StubSigningKey:
    def __init__(self, key) -> None:
        self.key = key


class _StubJWKSClient:
    """Stands in for PyJWKClient — returns the unit-test EC public key."""

    def get_signing_key_from_jwt(self, token: str) -> _StubSigningKey:
        return _StubSigningKey(_EC_KEY.public_key())


class _BrokenJWKSClient:
    """JWKS endpoint unreachable / kid unknown — resolution always fails."""

    def get_signing_key_from_jwt(self, token: str) -> _StubSigningKey:
        raise RuntimeError("JWKS endpoint unreachable")


@pytest.fixture()
def es256_auth(monkeypatch: pytest.MonkeyPatch):
    """Real-world config: no HS256 secret, JWKS-backed ES256 verification."""
    monkeypatch.setattr(settings, "supabase_jwt_secret", SecretStr(""))
    monkeypatch.setattr(settings, "supabase_url", "https://unit-test.supabase.co")
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "enable_demo_user_fallback", False)
    monkeypatch.setattr(settings, "demo_user_id", DEMO_ID)
    monkeypatch.setattr(auth_module, "_jwks_client", lambda url: _StubJWKSClient())
    return settings


def test_es256_token_resolves_to_its_own_user_without_hs256_secret(
    probe_client: TestClient, es256_auth
) -> None:
    a = probe_client.get("/whoami", headers=_bearer(_mint_es256(USER_A)))
    b = probe_client.get("/whoami", headers=_bearer(_mint_es256(USER_B)))
    assert a.status_code == 200 and a.json()["user_id"] == USER_A
    assert b.status_code == 200 and b.json()["user_id"] == USER_B
    assert a.json()["user_id"] != b.json()["user_id"]


def test_es256_expired_token_returns_401(probe_client: TestClient, es256_auth) -> None:
    res = probe_client.get("/whoami", headers=_bearer(_mint_es256(USER_A, exp_offset=-10)))
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "token_expired"


def test_es256_token_signed_by_wrong_key_returns_401(
    probe_client: TestClient, es256_auth, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "enable_demo_user_fallback", True)
    forged = _mint_es256(USER_A, key=_ATTACKER_EC_KEY)
    res = probe_client.get("/whoami", headers=_bearer(forged))
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "invalid_token"


def test_es256_with_unreachable_jwks_fails_closed(
    probe_client: TestClient, es256_auth, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "enable_demo_user_fallback", True)
    monkeypatch.setattr(auth_module, "_jwks_client", lambda url: _BrokenJWKSClient())
    res = probe_client.get("/whoami", headers=_bearer(_mint_es256(USER_A)))
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "invalid_token"


def test_es256_without_supabase_url_fails_closed(
    probe_client: TestClient, es256_auth, monkeypatch
) -> None:
    # No SUPABASE_URL → no JWKS → an ES256 token is unverifiable → 401,
    # never the demo user.
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "enable_demo_user_fallback", True)
    res = probe_client.get("/whoami", headers=_bearer(_mint_es256(USER_A)))
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "invalid_token"


def test_unsupported_algorithm_fails_closed(probe_client: TestClient, es256_auth) -> None:
    # alg=none (unsigned) must never verify.
    now = int(time.time())
    unsigned = pyjwt.encode(
        {"sub": USER_A, "aud": SUPABASE_AUDIENCE, "iat": now, "exp": now + 3600},
        key=None,
        algorithm="none",
    )
    res = probe_client.get("/whoami", headers=_bearer(unsigned))
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "invalid_token"


def test_es256_optional_dependency_valid_owner_and_anonymous_degrade(
    probe_client: TestClient, es256_auth
) -> None:
    ok = probe_client.get("/whoami-optional", headers=_bearer(_mint_es256(USER_A)))
    assert ok.status_code == 200 and ok.json()["user_id"] == USER_A

    forged = probe_client.get(
        "/whoami-optional", headers=_bearer(_mint_es256(USER_A, key=_ATTACKER_EC_KEY))
    )
    assert forged.status_code == 200 and forged.json()["user_id"] is None


# ── End-to-end: token-driven isolation through the real GitHub proof route ────


@pytest.fixture()
def e2e_store(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Real deps + real service, dict-backed DB, token-driven identity."""
    monkeypatch.setattr(settings, "supabase_jwt_secret", SecretStr(_SECRET))
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "enable_demo_user_fallback", False)
    monkeypatch.setattr(settings, "demo_user_id", DEMO_ID)
    store: dict = {}
    main_app.dependency_overrides[get_db] = lambda: store
    yield store
    main_app.dependency_overrides.clear()


def _seed_session(store: dict, user_id: str) -> str:
    session_id = str(uuid4())
    store.setdefault("extension_proof_sessions", {})[session_id] = {
        "id": session_id,
        "user_id": user_id,
        "status": "completed",
        "website_url": "https://example.edu/project",
    }
    return session_id


def test_user_b_cannot_see_user_a_github_proof_end_to_end(e2e_store: dict) -> None:
    client = TestClient(main_app)

    # User A submits a GitHub proof with a genuine token.
    a_session = _seed_session(e2e_store, USER_A)
    submit = client.post(
        "/api/v1/student/github-proofs",
        headers=_bearer(_mint(USER_A)),
        json={
            "repo_url": "https://github.com/machackgo/boston-smart-accident-risk-rerouting-google-cloud",
            "proof_session_id": a_session,
            "submitted_skill_claims": ["FastAPI"],
        },
    )
    assert submit.status_code == 201, submit.text

    # User A sees their own proof.
    a_list = client.get("/api/v1/student/github-proofs", headers=_bearer(_mint(USER_A)))
    assert a_list.status_code == 200
    a_repos = [p["repo_url"] for p in a_list.json()]
    assert any("machackgo" in r for r in a_repos)

    # User B, with a genuine token, sees NOTHING of user A's.
    b_list = client.get("/api/v1/student/github-proofs", headers=_bearer(_mint(USER_B)))
    assert b_list.status_code == 200
    assert b_list.json() == []

    # And cannot fetch A's proof by id.
    proof_id = submit.json()["id"]
    b_get = client.get(f"/api/v1/student/github-proofs/{proof_id}", headers=_bearer(_mint(USER_B)))
    assert b_get.status_code == 404

    # An unauthenticated request (fallback off) is rejected, not served A's data.
    anon_list = client.get("/api/v1/student/github-proofs")
    assert anon_list.status_code == 401
