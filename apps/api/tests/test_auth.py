"""
Tests for app/core/auth.py — JWT verification logic.

No real Supabase calls. All tokens are minted locally with PyJWT
using a test secret that is never used in production.
"""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest

from app.core.auth import (
    SUPABASE_AUDIENCE,
    AuthTokenExpired,
    AuthTokenInvalid,
    extract_user_id,
    verify_supabase_jwt,
)

_SECRET = "test-secret-do-not-use-in-production"
_USER_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _mint(
    sub: str = _USER_ID,
    aud: str = SUPABASE_AUDIENCE,
    exp_offset: int = 3600,
    extra: dict | None = None,
    secret: str = _SECRET,
    algorithm: str = "HS256",
) -> str:
    now = int(time.time())
    payload: dict = {
        "sub": sub,
        "aud": aud,
        "iat": now,
        "exp": now + exp_offset,
        "role": "authenticated",
    }
    if extra:
        payload.update(extra)
    return pyjwt.encode(payload, secret, algorithm=algorithm)


# ── verify_supabase_jwt ───────────────────────────────────────────────────────


class TestVerifySupabaseJwt:
    def test_valid_token_returns_payload(self) -> None:
        token = _mint()
        payload = verify_supabase_jwt(token, _SECRET)
        assert payload["sub"] == _USER_ID
        assert payload["aud"] == SUPABASE_AUDIENCE

    def test_expired_token_raises_expired(self) -> None:
        token = _mint(exp_offset=-1)
        with pytest.raises(AuthTokenExpired):
            verify_supabase_jwt(token, _SECRET)

    def test_wrong_secret_raises_invalid(self) -> None:
        token = _mint()
        with pytest.raises(AuthTokenInvalid):
            verify_supabase_jwt(token, "wrong-secret")

    def test_wrong_audience_raises_invalid(self) -> None:
        token = _mint(aud="anon")
        with pytest.raises(AuthTokenInvalid):
            verify_supabase_jwt(token, _SECRET)

    def test_malformed_token_raises_invalid(self) -> None:
        with pytest.raises(AuthTokenInvalid):
            verify_supabase_jwt("not.a.jwt", _SECRET)

    def test_empty_token_raises_invalid(self) -> None:
        with pytest.raises(AuthTokenInvalid):
            verify_supabase_jwt("", _SECRET)

    def test_empty_secret_raises_invalid(self) -> None:
        token = _mint()
        with pytest.raises(AuthTokenInvalid):
            verify_supabase_jwt(token, "")

    def test_missing_sub_claim_in_payload(self) -> None:
        # Build a token without 'sub' — PyJWT will raise because we require it.
        now = int(time.time())
        payload = {"aud": SUPABASE_AUDIENCE, "iat": now, "exp": now + 3600}
        token = pyjwt.encode(payload, _SECRET, algorithm="HS256")
        with pytest.raises(AuthTokenInvalid):
            verify_supabase_jwt(token, _SECRET)

    def test_missing_exp_claim_in_payload(self) -> None:
        now = int(time.time())
        payload = {"sub": _USER_ID, "aud": SUPABASE_AUDIENCE, "iat": now}
        token = pyjwt.encode(payload, _SECRET, algorithm="HS256")
        with pytest.raises(AuthTokenInvalid):
            verify_supabase_jwt(token, _SECRET)

    def test_algorithm_mismatch_raises_invalid(self) -> None:
        # RS256 token against HS256-only decoder.
        try:
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.backends import default_backend

            private_key = rsa.generate_private_key(
                public_exponent=65537, key_size=2048, backend=default_backend()
            )
            token = _mint(algorithm="RS256", secret=private_key)  # type: ignore[arg-type]
            with pytest.raises(AuthTokenInvalid):
                verify_supabase_jwt(token, _SECRET)
        except ImportError:
            pytest.skip("cryptography package not installed")

    def test_extra_claims_are_preserved(self) -> None:
        token = _mint(extra={"email": "user@example.com", "role": "authenticated"})
        payload = verify_supabase_jwt(token, _SECRET)
        assert payload.get("email") == "user@example.com"


# ── extract_user_id ───────────────────────────────────────────────────────────


class TestExtractUserId:
    def test_returns_sub_from_valid_token(self) -> None:
        token = _mint(sub=_USER_ID)
        assert extract_user_id(token, _SECRET) == _USER_ID

    def test_returns_string_type(self) -> None:
        token = _mint()
        result = extract_user_id(token, _SECRET)
        assert isinstance(result, str)

    def test_propagates_expired_error(self) -> None:
        token = _mint(exp_offset=-1)
        with pytest.raises(AuthTokenExpired):
            extract_user_id(token, _SECRET)

    def test_propagates_invalid_error(self) -> None:
        with pytest.raises(AuthTokenInvalid):
            extract_user_id("garbage", _SECRET)
