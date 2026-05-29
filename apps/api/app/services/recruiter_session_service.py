"""Recruiter session token service.

Issues server-side, cryptographically random session tokens for recruiters.
Tokens are stored only as SHA-256 hashes — the plaintext is returned once
on creation and never re-readable from the database.

Usage flow:
    POST /public/recruiter/sessions  →  {session_token: "vrec_..."}
    GET  /public/recruiter/saved-passports  [X-Recruiter-Token: vrec_...]
    PATCH /public/recruiter/saved-passports/{id}  [X-Recruiter-Token: vrec_...]
    etc.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

_SESSIONS = "recruiter_session_tokens"

# Tokens are valid for 30 days from creation.
_SESSION_TTL_DAYS = 30


class RecruiterSessionInvalidError(PermissionError):
    """Session token is missing, expired, revoked, or not found."""


class RecruiterSessionService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def create_session(self, requester_email: str) -> tuple[str, str]:
        """Create and persist a session for *requester_email*.

        Returns ``(plaintext_token, normalized_email)``.  The plaintext token
        is returned to the caller exactly once; only its SHA-256 hash is
        stored in the database.
        """
        email = _normalize_email(requester_email)
        plaintext = _new_session_token()
        token_hash = _hash_token(plaintext)
        now = _now()
        row: dict[str, Any] = {
            "id": str(uuid4()),
            "requester_email": email,
            "token_hash": token_hash,
            "expires_at": (now + timedelta(days=_SESSION_TTL_DAYS)).isoformat(),
            "revoked_at": None,
            "created_at": now.isoformat(),
        }
        self._insert(_SESSIONS, row)
        return plaintext, email

    def validate_token(self, plaintext_token: str) -> str | None:
        """Validate *plaintext_token* and return the ``requester_email``.

        Returns ``None`` if the token is unknown, expired, or revoked.
        """
        token_hash = _hash_token(plaintext_token)
        row = self._first_where(_SESSIONS, "token_hash", token_hash)
        if not row:
            return None
        if row.get("revoked_at"):
            return None
        expires_at = _parse_dt(row.get("expires_at"))
        if expires_at and expires_at <= _now():
            return None
        return str(row["requester_email"])

    # ── persistence helpers ───────────────────────────────────────────────────

    def _insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        if isinstance(self._client, dict):
            self._client.setdefault(table, {})[str(row["id"])] = row
            return row
        result = self._client.table(table).insert(row).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError(f"{table} insert returned no data.")
        return rows[0]

    def _first_where(self, table: str, field: str, value: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            for row in self._client.get(table, {}).values():
                if str(row.get(field)) == value:
                    return row
            return None
        result = (
            self._client.table(table)
            .select("*")
            .eq(field, value)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None


# ── module-level helpers ──────────────────────────────────────────────────────

def _new_session_token() -> str:
    return f"vrec_{secrets.token_urlsafe(32)}"


def _hash_token(plaintext: str) -> str:
    return sha256(plaintext.encode("utf-8")).hexdigest()


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _parse_dt(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _now() -> datetime:
    return datetime.now(UTC)
