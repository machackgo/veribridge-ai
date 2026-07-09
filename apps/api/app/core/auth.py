"""
Supabase Auth JWT verification.

Supabase signs access tokens with one of two schemes, depending on the
project's JWT signing-key configuration:

  • Legacy projects: HS256 with the project-specific JWT Secret found at
    Supabase dashboard → Settings → API → JWT Settings → JWT Secret
    (``SUPABASE_JWT_SECRET``).
  • Current projects ("JWT signing keys"): an asymmetric key — ES256 or
    RS256 — whose PUBLIC half is published at
    ``{SUPABASE_URL}/auth/v1/.well-known/jwks.json``.

This module verifies both. The token's header ``alg`` selects the scheme, and
each scheme is pinned to its own key material — an HS256 token is only ever
checked against SUPABASE_JWT_SECRET, an ES256/RS256 token only against the
project JWKS — so algorithm-confusion downgrades are impossible. Anything
unverifiable (unknown alg, missing secret, unreachable JWKS, unknown ``kid``,
bad signature) fails closed with :class:`AuthTokenInvalid`.

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

# Asymmetric algorithms Supabase's "JWT signing keys" feature can issue.
# Symmetric algs must NEVER appear here — see the pinning note in the
# module docstring.
SUPABASE_ASYMMETRIC_ALGS = frozenset({"ES256", "RS256"})

# One PyJWKClient per JWKS URL for the process lifetime. The client caches the
# fetched key set (`lifespan` seconds), so steady-state requests verify without
# a network round-trip; rotated keys are picked up on the next refresh.
_JWKS_CLIENTS: dict[str, "jwt.PyJWKClient"] = {}
_JWKS_CACHE_LIFESPAN_S = 600


def _jwks_client(jwks_url: str) -> "jwt.PyJWKClient":
    client = _JWKS_CLIENTS.get(jwks_url)
    if client is None:
        client = jwt.PyJWKClient(
            jwks_url, cache_keys=True, lifespan=_JWKS_CACHE_LIFESPAN_S
        )
        _JWKS_CLIENTS[jwks_url] = client
    return client


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


def verify_supabase_jwt(token: str, secret: str, jwks_url: str = "") -> dict:
    """
    Decode and verify a Supabase Auth JWT.

    Parameters
    ----------
    token:    The raw JWT string from the Authorization header.
    secret:   The SUPABASE_JWT_SECRET (legacy HS256 signing key). May be empty
              when the project uses asymmetric signing keys.
    jwks_url: The project JWKS endpoint
              (``{SUPABASE_URL}/auth/v1/.well-known/jwks.json``) used to verify
              ES256/RS256 tokens. May be empty for legacy HS256-only projects.

    Returns
    -------
    The decoded payload dict.  The caller extracts ``payload["sub"]``
    as the user UUID.

    Raises
    ------
    AuthTokenExpired  — token is past its ``exp`` claim.
    AuthTokenInvalid  — signature mismatch, wrong audience, malformed,
                        unsupported algorithm, or no way to verify (missing
                        secret / JWKS).
    RuntimeError      — PyJWT is not installed.
    """
    if not _JWT_AVAILABLE:  # pragma: no cover
        raise RuntimeError(
            "PyJWT is not installed. Run: pip install 'PyJWT>=2.8.0'"
        )

    try:
        header = jwt.get_unverified_header(token)
    except (DecodeError, InvalidTokenError) as exc:
        raise AuthTokenInvalid(f"Token is malformed or invalid: {exc}") from exc

    alg = header.get("alg")

    if alg == "HS256":
        if not secret:
            raise AuthTokenInvalid(
                "SUPABASE_JWT_SECRET is not configured — cannot verify an "
                "HS256 token."
            )
        key: object = secret
        allowed_algs = ["HS256"]
    elif alg in SUPABASE_ASYMMETRIC_ALGS:
        if not jwks_url:
            raise AuthTokenInvalid(
                "SUPABASE_URL is not configured — cannot resolve the JWKS "
                f"needed to verify an {alg} token."
            )
        try:
            key = _jwks_client(jwks_url).get_signing_key_from_jwt(token).key
        except Exception as exc:
            # Unknown kid, unreachable endpoint, malformed JWKS, … — all of it
            # means "cannot verify", so all of it fails closed.
            raise AuthTokenInvalid(
                f"Unable to resolve the token's signing key from JWKS: {exc}"
            ) from exc
        allowed_algs = [alg]
    else:
        raise AuthTokenInvalid(f"Unsupported token algorithm: {alg!r}.")

    try:
        payload: dict = jwt.decode(
            token,
            key,
            algorithms=allowed_algs,
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
            "Token signature is invalid. Verify SUPABASE_JWT_SECRET (HS256) "
            "or the project JWKS (ES256/RS256) matches your Supabase project."
        )

    except (DecodeError, InvalidTokenError) as exc:
        raise AuthTokenInvalid(f"Token is malformed or invalid: {exc}") from exc


def extract_user_id(token: str, secret: str, jwks_url: str = "") -> str:
    """
    Verify a JWT and return the ``sub`` claim (Supabase user UUID).

    Convenience wrapper around ``verify_supabase_jwt``.
    """
    payload = verify_supabase_jwt(token, secret, jwks_url)
    sub = payload.get("sub")
    if not sub:
        raise AuthTokenInvalid("Token is missing the 'sub' (user ID) claim.")
    return str(sub)
