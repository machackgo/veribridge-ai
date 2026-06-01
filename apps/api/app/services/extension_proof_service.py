"""Extension Proof Session service — in-memory storage for now."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.schemas.extension_proof import (
    ExtensionProofCompleteResponse,
    ExtensionProofSessionCreate,
    ExtensionProofSessionResponse,
    ExtensionProofStartResponse,
    ExtensionProofUploadRequest,
    ExtensionProofUploadResponse,
)

logger = logging.getLogger(__name__)

_TABLE = "extension_proof_sessions"

_VALID_START_FROM = frozenset({"created", "waiting_for_extension"})
_VALID_UPLOAD_FROM = frozenset({"recording"})
_VALID_COMPLETE_FROM = frozenset({"uploaded_pending_analysis"})

# Values replaced with [REDACTED] — matched case-insensitively on key name
_SENSITIVE_KEYS = frozenset({
    "password", "token", "secret", "api_key", "apikey", "card", "cvv",
    "ssn", "otp", "2fa", "mfa", "authorization", "bearer",
})

# Keys dropped entirely — never persisted under any form
_BLOCKED_KEYS = frozenset({
    "cookies", "cookie", "localstorage", "sessionstorage",
    "auth_headers", "authheaders",
})


class ExtensionProofSessionNotFoundError(LookupError):
    """Session not found for the scoped user."""


class InvalidSessionTransitionError(ValueError):
    """Session status does not allow the requested transition."""


class ExtensionProofSessionService:
    def __init__(self, client: Any) -> None:
        self._client = client

    # ── Create ────────────────────────────────────────────────────────────────

    def create_session(
        self, user_id: str, payload: ExtensionProofSessionCreate
    ) -> ExtensionProofSessionResponse:
        now = _now()
        data: dict = {
            "user_id": user_id,
            "skill_evidence_id": payload.skill_evidence_id,
            "status": "created",
        }
        if payload.parent_proof_session_id:
            data["parent_proof_session_id"] = payload.parent_proof_session_id
        if payload.followup_target_skill:
            data["followup_target_skill"] = payload.followup_target_skill
        if payload.followup_objective:
            data["followup_objective"] = payload.followup_objective
        if payload.proof_attempt_type == "followup":
            data["proof_attempt_type"] = "followup"

        if isinstance(self._client, dict):
            row = {"id": str(uuid4()), "created_at": now, "updated_at": now, **data}
            self._client.setdefault(_TABLE, {})[row["id"]] = row
            return _to_response(row)

        result = self._client.table(_TABLE).insert(data).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError("Extension proof session insert returned no data.")
        return _to_response(rows[0])

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_session(
        self, user_id: str, session_id: str
    ) -> ExtensionProofSessionResponse:
        return _to_response(self._get_row(user_id, session_id))

    # ── Start ─────────────────────────────────────────────────────────────────

    def start_session(
        self, user_id: str, session_id: str
    ) -> ExtensionProofStartResponse:
        row = self._get_row(user_id, session_id)
        if row["status"] not in _VALID_START_FROM:
            raise InvalidSessionTransitionError(
                f"Cannot start a session with status '{row['status']}'. "
                f"Allowed from: {sorted(_VALID_START_FROM)}."
            )
        now = _now()
        row = self._apply_updates(
            row, user_id, session_id,
            {"status": "recording", "started_at": now, "updated_at": now},
        )
        return ExtensionProofStartResponse(**_to_response(row).model_dump())

    # ── Upload ────────────────────────────────────────────────────────────────

    def upload_proof(
        self, user_id: str, session_id: str, payload: ExtensionProofUploadRequest
    ) -> ExtensionProofUploadResponse:
        row = self._get_row(user_id, session_id)
        if row["status"] not in _VALID_UPLOAD_FROM:
            raise InvalidSessionTransitionError(
                f"Cannot upload to a session with status '{row['status']}'. "
                f"Allowed from: {sorted(_VALID_UPLOAD_FROM)}."
            )
        proof_upload_id = str(uuid4())
        safe_data = {
            "workflow_events": mask_sensitive(payload.workflow_events),
            "screenshots": mask_sensitive(payload.screenshots) if payload.screenshots is not None else None,
            "browser_metadata": mask_sensitive(payload.browser_metadata) if payload.browser_metadata is not None else None,
            "extension_version": payload.extension_version,
            "started_at": payload.started_at,
            "stopped_at": payload.stopped_at,
            "student_final_note": payload.student_final_note,
            # Multi-tab tracking metadata
            "tracked_tab_count": payload.tracked_tab_count,
            "tracked_urls": payload.tracked_urls,
            "external_tabs_opened": payload.external_tabs_opened,
        }

        # ── Privacy scan (run before committing to DB) ─────────────────────
        from app.services.workflow_privacy_scan_service import (  # local import avoids circular
            WorkflowPrivacyScanService,
            scan_proof_data,
        )
        scan_result = scan_proof_data(safe_data)

        row = self._apply_updates(
            row, user_id, session_id,
            {
                "status": "uploaded_pending_analysis",
                "proof_upload_id": proof_upload_id,
                "proof_data": safe_data,
                "updated_at": _now(),
            },
        )

        # Store scan result in dedicated table (non-critical — never fails the upload)
        try:
            WorkflowPrivacyScanService(self._client).store_scan(
                user_id, session_id, scan_result
            )
        except Exception as exc:
            logger.warning("Privacy scan store failed (non-critical): %s", exc)

        return _to_upload_response(row, scan_result)

    # ── Complete ──────────────────────────────────────────────────────────────

    def complete_session(
        self, user_id: str, session_id: str
    ) -> ExtensionProofCompleteResponse:
        row = self._get_row(user_id, session_id)
        if row["status"] not in _VALID_COMPLETE_FROM:
            raise InvalidSessionTransitionError(
                f"Cannot complete a session with status '{row['status']}'. "
                f"Allowed from: {sorted(_VALID_COMPLETE_FROM)}."
            )
        row = self._apply_updates(
            row, user_id, session_id,
            {"status": "analyzing", "updated_at": _now()},
        )
        return ExtensionProofCompleteResponse(**_to_response(row).model_dump())

    # ── Internals ─────────────────────────────────────────────────────────────

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

    def _apply_updates(
        self,
        row: dict[str, Any],
        user_id: str,
        session_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        if isinstance(self._client, dict):
            updated = {**row, **updates}
            self._client.setdefault(_TABLE, {})[session_id] = updated
            return updated

        result = (
            self._client.table(_TABLE)
            .update(updates)
            .eq("user_id", user_id)
            .eq("id", session_id)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        if not rows:
            raise ExtensionProofSessionNotFoundError(session_id)
        return rows[0]


# ── Masking ────────────────────────────────────────────────────────────────────

def mask_sensitive(obj: Any) -> Any:
    """Recursively redact sensitive keys and drop blocked keys from any structure."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            key_lower = k.lower()
            if key_lower in _BLOCKED_KEYS:
                continue
            out[k] = "[REDACTED]" if key_lower in _SENSITIVE_KEYS else mask_sensitive(v)
        return out
    if isinstance(obj, list):
        return [mask_sensitive(item) for item in obj]
    return obj


# ── Response builders ─────────────────────────────────────────────────────────

def _to_response(row: dict[str, Any]) -> ExtensionProofSessionResponse:
    return ExtensionProofSessionResponse(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        skill_evidence_id=str(row["skill_evidence_id"]),
        status=row.get("status") or "created",
        started_at=row.get("started_at"),
        proof_upload_id=row.get("proof_upload_id"),
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


def _to_upload_response(
    row: dict[str, Any],
    scan_result: "Any | None" = None,
) -> ExtensionProofUploadResponse:
    from app.services.workflow_privacy_scan_service import PrivacyScanResult
    privacy_status = scan_result.status if isinstance(scan_result, PrivacyScanResult) else None
    privacy_summary = scan_result.scan_summary if isinstance(scan_result, PrivacyScanResult) else None
    return ExtensionProofUploadResponse(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        skill_evidence_id=str(row["skill_evidence_id"]),
        status=row.get("status") or "uploaded_pending_analysis",
        started_at=row.get("started_at"),
        proof_upload_id=str(row["proof_upload_id"]),
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
        privacy_scan_status=privacy_status,
        privacy_scan_summary=privacy_summary,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
