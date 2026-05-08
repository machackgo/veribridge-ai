"""
Supabase Auth JWT verification.

Supabase issues JWTs signed with HS256 using the project-specific JWT Secret
found at: Supabase dashboard → Settings → API → JWT Settings → JWT Secret.

Token structure
---------------
{
  "sub":  "<user-uuid>",          ← the user's ID (what we need)
  "aud":  "authenticated",
  "role": "authenticated",
  "iss":  "https://<ref>.supabase.co/auth/v1",
  "email": "user@example.com",
  "exp":  <unix-timestamp>,
  "iat":  <unix-timestamp>
}

Error types raised
------------------
AuthTokenMissing    — no Authorization header (dev: falls back to demo user)
AuthTokenExpired    — valid token but past expiry
AuthTokenInvalid    — signature invalid, malformed, wrong audience, etc.

These are mapped to HTTP 401 by the dependency layer.
"""

from __future__ import annotations

import logging

try:
    import jwt
    from jwt.exceptions import (
        DecodeError,
        ExpiredSignatureError,
        InvalidAudienceError,
        InvalidSignatureError,
        InvalidTokenError,
    )
    _JWT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _JWT_AVAILABLE = False

logger = logging.getLogger(__name__)

# Supabase signs all user JWTs with this audience claim.
SUPABASE_AUDIENCE = "authenticated"


# ── Typed auth exceptions ─────────────────────────────────────────────────────


class AuthError(Exception):
    """Base class for authentication errors."""


class AuthTokenMissing(AuthError):
    """No Authorization header was provided."""


class AuthTokenExpired(AuthError):
    """Token is structurally valid but past its expiry time."""


class AuthTokenInvalid(AuthError):
    """Token has invalid signature, wrong audience, or is malformed."""


# ── Verification ──────────────────────────────────────────────────────────────


def verify_supabase_jwt(token: str, secret: str) -> dict:
    """
    Decode and verify a Supabase Auth JWT.

    Parameters
    ----------
    token:  The raw JWT string from the Authorization header.
    secret: The SUPABASE_JWT_SECRET (HS256 signing key).

    Returns
    -------
    The decoded payload dict.  The caller extracts ``payload["sub"]``
    as the user UUID.

    Raises
    ------
    AuthTokenExpired  — token is past its ``exp`` claim.
    AuthTokenInvalid  — signature mismatch, wrong audience, malformed.
    RuntimeError      — PyJWT is not installed.
    """
    if not _JWT_AVAILABLE:  # pragma: no cover
        raise RuntimeError(
            "PyJWT is not installed. Run: pip install 'PyJWT>=2.8.0'"
        )

    if not secret:
        raise AuthTokenInvalid(
            "SUPABASE_JWT_SECRET is not configured — cannot verify token."
        )

    try:
        payload: dict = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=SUPABASE_AUDIENCE,
            options={"require": ["sub", "exp", "iat"]},
        )
        return payload

    except ExpiredSignatureError:
        raise AuthTokenExpired("Token has expired. Please sign in again.")

    except (InvalidAudienceError,):
        raise AuthTokenInvalid(
            f"Token audience is invalid. Expected: {SUPABASE_AUDIENCE!r}."
        )

    except (InvalidSignatureError,):
        raise AuthTokenInvalid(
            "Token signature is invalid. "
            "Verify SUPABASE_JWT_SECRET matches your Supabase project."
        )

    except (DecodeError, InvalidTokenError) as exc:
        raise AuthTokenInvalid(f"Token is malformed or invalid: {exc}") from exc


def extract_user_id(token: str, secret: str) -> str:
    """
    Verify a JWT and return the ``sub`` claim (Supabase user UUID).

    Convenience wrapper around ``verify_supabase_jwt``.
    """
    payload = verify_supabase_jwt(token, secret)
    sub = payload.get("sub")
    if not sub:
        raise AuthTokenInvalid("Token is missing the 'sub' (user ID) claim.")
    return str(sub)
