"""Extension Proof Session service — in-memory storage for now."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.schemas.extension_proof import (
    ExtensionProofSessionCreate,
    ExtensionProofSessionResponse,
)

_TABLE = "extension_proof_sessions"


class ExtensionProofSessionNotFoundError(LookupError):
    """Session not found for the scoped user."""


class ExtensionProofSessionService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def create_session(
        self, user_id: str, payload: ExtensionProofSessionCreate
    ) -> ExtensionProofSessionResponse:
        now = _now()
        data = {
            "user_id": user_id,
            "skill_evidence_id": payload.skill_evidence_id,
            "status": "pending",
        }

        if isinstance(self._client, dict):
            row = {"id": str(uuid4()), "created_at": now, "updated_at": now, **data}
            self._client.setdefault(_TABLE, {})[row["id"]] = row
            return _to_response(row)

        result = self._client.table(_TABLE).insert(data).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError("Extension proof session insert returned no data.")
        return _to_response(rows[0])

    def get_session(
        self, user_id: str, session_id: str
    ) -> ExtensionProofSessionResponse:
        return _to_response(self._get_row(user_id, session_id))

    def _get_row(self, user_id: str, session_id: str) -> dict[str, Any]:
        if isinstance(self._client, dict):
            row = self._client.setdefault(_TABLE, {}).get(session_id)
            if not row or row.get("user_id") != user_id:
                raise ExtensionProofSessionNotFoundError(session_id)
            return row

        result = (
            self._client.table(_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", session_id)
            .maybe_single()
            .execute()
        )
        if result is None:
            raise ExtensionProofSessionNotFoundError(session_id)
        return result.data


def _to_response(row: dict[str, Any]) -> ExtensionProofSessionResponse:
    return ExtensionProofSessionResponse(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        skill_evidence_id=str(row["skill_evidence_id"]),
        status=row.get("status") or "pending",
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
