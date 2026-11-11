"""Evidence-access grant tokens: minting and the single lookup path.

Every protected recruiter endpoint (``/public/access/{token}/evidence``,
``/skill-evidence-timeline``, ``/export`` and ``/github-proofs``) resolves its
bearer token through :func:`resolve_grant`, so all of them apply the same
rules:

* The presented token is hashed (SHA-256, hex) and looked up by
  ``access_token_hash``. New grants store only that hash; ``access_token`` is
  NULL.
* Legacy fallback: a lookup by plaintext ``access_token`` is attempted only
  when no hash matched, and only rows whose ``access_token_hash`` is NULL may
  match it (rows created before migration 037 and never back-filled). Once a
  row has a hash, its plaintext column is never an alternative credential.
* Tokens beginning with ``revoked-`` are rejected outright: that prefix is the
  marker written over retired legacy plaintext tokens in production.
* A grant with ``revoked_at`` set, or whose ``expires_at`` has passed, is
  denied.
* Values read back from the database are compared with
  :func:`hmac.compare_digest`.

Error messages never include the presented token, its hash or the grant id.
"""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

GRANTS_TABLE = "evidence_access_grants"
TOKEN_PREFIX = "vbpa_"
REVOKED_MARKER_PREFIX = "revoked-"
# secrets.token_urlsafe(32) → 43 url-safe characters (256 bits of entropy).
_TOKEN_RANDOM_BYTES = 32
# Generous upper bound on what we are willing to hash / send to PostgREST.
_MAX_TOKEN_LENGTH = 512

INVALID_MESSAGE = "Access token is invalid or revoked."
EXPIRED_MESSAGE = "Access token is expired."


class EvidenceAccessDeniedError(PermissionError):
    """Access token is missing, expired, revoked, or otherwise invalid."""


def hash_token(token: str) -> str:
    """SHA-256 hex digest of a bearer token (the only form stored at rest)."""
    return sha256(token.encode("utf-8")).hexdigest()


def mint_token() -> tuple[str, str]:
    """Return a fresh ``(token, token_hash)`` pair. Only the hash is stored."""
    token = f"{TOKEN_PREFIX}{secrets.token_urlsafe(_TOKEN_RANDOM_BYTES)}"
    return token, hash_token(token)


def is_retired_marker(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(REVOKED_MARKER_PREFIX)


def has_stored_plaintext(grant: dict[str, Any]) -> bool:
    """True when the row still carries something in ``access_token`` (a legacy
    plaintext credential or a ``revoked-`` retirement marker)."""
    return grant.get("access_token") is not None


def parse_timestamp(value: Any) -> datetime | None:
    """Parse a stored timestamp; raises ``ValueError`` if it is not one."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    raise ValueError("unsupported timestamp value")


def is_expired(grant: dict[str, Any], now: datetime | None = None) -> bool:
    """True when ``expires_at`` has passed. An unparseable ``expires_at`` is
    treated as expired (fail closed)."""
    try:
        expires_at = parse_timestamp(grant.get("expires_at"))
    except (TypeError, ValueError):
        return True
    return bool(expires_at and expires_at <= (now or datetime.now(UTC)))


def needs_rotation(grant: dict[str, Any], now: datetime | None = None) -> bool:
    """Whether re-approving this grant must mint a new credential.

    A revoked or expired grant's token must never become valid again, and a row
    that still stores plaintext (legacy token or retirement marker) is moved to
    a hash-only credential. A row without a hash has no usable credential.
    """
    return bool(
        grant.get("revoked_at")
        or is_expired(grant, now)
        or has_stored_plaintext(grant)
        or not grant.get("access_token_hash")
    )


def resolve_grant(
    db: Any,
    presented_token: str,
    *,
    on_expired: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Return the active grant for ``presented_token`` or raise
    :class:`EvidenceAccessDeniedError`.

    ``on_expired`` is called with the grant row before the expiry denial is
    raised (used to write the ``access_expired`` audit event).
    """
    if (
        not isinstance(presented_token, str)
        or not presented_token
        or len(presented_token) > _MAX_TOKEN_LENGTH
        or is_retired_marker(presented_token)
    ):
        raise EvidenceAccessDeniedError(INVALID_MESSAGE)

    grant = _lookup(db, presented_token)
    if grant is None or grant.get("revoked_at") or is_retired_marker(grant.get("access_token")):
        raise EvidenceAccessDeniedError(INVALID_MESSAGE)
    if is_expired(grant):
        if on_expired is not None:
            on_expired(grant)
        raise EvidenceAccessDeniedError(EXPIRED_MESSAGE)
    return grant


def _lookup(db: Any, presented_token: str) -> dict[str, Any] | None:
    token_hash = hash_token(presented_token)
    for row in _rows_where(db, "access_token_hash", token_hash):
        stored = row.get("access_token_hash")
        if isinstance(stored, str) and hmac.compare_digest(stored, token_hash):
            return row
    # Legacy fallback: only rows that never received a hash.
    for row in _rows_where(db, "access_token", presented_token):
        if row.get("access_token_hash") is not None:
            continue
        stored = row.get("access_token")
        if isinstance(stored, str) and hmac.compare_digest(
            stored.encode("utf-8"), presented_token.encode("utf-8")
        ):
            return row
    return None


def _rows_where(db: Any, field: str, value: str) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        # In-memory store used by tests and local fakes. Match on real strings
        # only, so a NULL column never equals the text "None".
        return [
            row
            for row in db.get(GRANTS_TABLE, {}).values()
            if isinstance(row.get(field), str) and row.get(field) == value
        ]
    result = db.table(GRANTS_TABLE).select("*").eq(field, value).limit(1).execute()
    return list(getattr(result, "data", None) or [])
