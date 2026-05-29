"""Recruiter saved Work Passport and shortlist service."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.schemas.recruiter_shortlist import (
    RecruiterSavedPassportCreate,
    RecruiterSavedPassportResponse,
    RecruiterSavedPassportUpdate,
)
from app.services.public_work_passport_service import PublicWorkPassportNotFoundError

_SAVED = "recruiter_saved_passports"
_PASSPORTS = "public_work_passports"
_REQUESTER_PROFILES = "recruiter_requester_profiles"
_AUDIT_EVENTS = "evidence_access_audit_events"
_PASSPORT_VIEW_EVENTS = "public_passport_view_events"

_ALLOWED_REQUESTER_TYPES = {
    "recruiter",
    "hiring_manager",
    "faculty",
    "mentor",
    "company_reviewer",
    "domain_expert",
    "other",
}
_FREE_EMAIL_DOMAINS = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "proton.me"}


class RecruiterSavedPassportNotFoundError(LookupError):
    """Saved passport row was not found for the scoped requester."""


class RecruiterShortlistService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def save_passport(self, public_slug: str, payload: RecruiterSavedPassportCreate) -> RecruiterSavedPassportResponse:
        passport = self._public_passport(public_slug)
        now = _now()
        profile = self._upsert_requester_profile(
            requester_email=str(payload.requester_email),
            requester_name=payload.requester_name,
            organization_name=payload.organization_name,
            now=now,
        )
        existing = self._saved_by_profile_and_passport(str(profile["id"]), str(passport["id"]))
        row = {
            "id": str((existing or {}).get("id") or uuid4()),
            "requester_profile_id": str(profile["id"]),
            "passport_id": str(passport["id"]),
            "proof_session_id": str(passport["proof_session_id"]),
            "student_user_id": str(passport["user_id"]),
            "requester_email": str(profile["email"]),
            "organization_name": payload.organization_name or profile.get("organization_name"),
            "status": payload.status,
            "tags": _clean_tags(payload.tags),
            "private_notes": payload.private_notes,
            "reviewed_sections": list((existing or {}).get("reviewed_sections") or []),
            "fit_score": (existing or {}).get("fit_score"),
            "fit_reason": (existing or {}).get("fit_reason"),
            "last_viewed_at": now,
            "created_at": (existing or {}).get("created_at") or now,
            "updated_at": now,
        }
        saved = self._save(_SAVED, row)
        self._write_audit_event(saved, "candidate_shortlisted" if saved["status"] == "shortlisted" else "passport_saved")
        self._write_view_event(passport, payload)
        return self._response(saved)

    def list_saved_passports(self, requester_email: str) -> list[RecruiterSavedPassportResponse]:
        email = _normalize_email(requester_email)
        rows = [row for row in self._rows(_SAVED) if str(row.get("requester_email")) == email]
        rows.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
        return [self._response(row) for row in rows]

    def update_saved_passport(self, saved_id: str, payload: RecruiterSavedPassportUpdate, requester_email: str) -> RecruiterSavedPassportResponse:
        """Update a saved passport.  *requester_email* must come from a validated
        session — do NOT pass it from untrusted request bodies."""
        row = self._saved_for_email(saved_id, requester_email)
        previous_status = row.get("status")
        previous_notes = row.get("private_notes")
        if payload.status is not None:
            row["status"] = payload.status
        if payload.tags is not None:
            row["tags"] = _clean_tags(payload.tags)
        if payload.private_notes is not None:
            row["private_notes"] = payload.private_notes
        if payload.reviewed_sections is not None:
            row["reviewed_sections"] = _clean_sections(payload.reviewed_sections)
        if payload.fit_score is not None:
            row["fit_score"] = payload.fit_score
        if payload.fit_reason is not None:
            row["fit_reason"] = payload.fit_reason
        row["updated_at"] = _now()
        saved = self._save(_SAVED, row)
        if saved.get("status") == "shortlisted" and previous_status != "shortlisted":
            self._write_audit_event(saved, "candidate_shortlisted")
        elif saved.get("status") == "archived" and previous_status != "archived":
            self._write_audit_event(saved, "saved_passport_archived")
        elif payload.private_notes is not None and payload.private_notes != previous_notes:
            self._write_audit_event(saved, "recruiter_note_updated")
        return self._response(saved)

    def archive_saved_passport(self, saved_id: str, requester_email: str) -> RecruiterSavedPassportResponse:
        row = self._saved_for_email(saved_id, requester_email)
        row["status"] = "archived"
        row["updated_at"] = _now()
        saved = self._save(_SAVED, row)
        self._write_audit_event(saved, "saved_passport_archived")
        return self._response(saved)

    def delete_saved_passport(self, saved_id: str, requester_email: str) -> None:
        row = self._saved_for_email(saved_id, requester_email)
        self._delete(_SAVED, str(row["id"]))

    def record_passport_reviewed_section(self, saved_id: str, requester_email: str, section: str) -> RecruiterSavedPassportResponse:
        row = self._saved_for_email(saved_id, requester_email)
        sections = _clean_sections([*list(row.get("reviewed_sections") or []), section])
        row["reviewed_sections"] = sections
        row["last_viewed_at"] = _now()
        row["updated_at"] = _now()
        return self._response(self._save(_SAVED, row))

    def _public_passport(self, public_slug: str) -> dict[str, Any]:
        passport = self._first_where(_PASSPORTS, "public_slug", public_slug)
        if not passport or not passport.get("is_public", True):
            raise PublicWorkPassportNotFoundError(public_slug)
        return passport

    def _upsert_requester_profile(
        self,
        *,
        requester_email: str,
        requester_name: str | None,
        organization_name: str | None,
        now: datetime,
    ) -> dict[str, Any]:
        email = _normalize_email(requester_email)
        existing = self._first_where(_REQUESTER_PROFILES, "email", email)
        row = {
            "id": str((existing or {}).get("id") or uuid4()),
            "email": email,
            "full_name": requester_name or (existing or {}).get("full_name"),
            "organization_name": organization_name or (existing or {}).get("organization_name"),
            "organization_domain": _email_domain(email),
            "requester_role": (existing or {}).get("requester_role"),
            "requester_type": (existing or {}).get("requester_type") or "recruiter",
            "email_verified": bool((existing or {}).get("email_verified", False)),
            "domain_verified": bool((existing or {}).get("domain_verified", False)),
            "verification_status": (existing or {}).get("verification_status") or "unverified",
            "first_seen_at": (existing or {}).get("first_seen_at") or now,
            "last_seen_at": now,
            "total_access_requests": int((existing or {}).get("total_access_requests") or 0),
            "approved_access_requests": int((existing or {}).get("approved_access_requests") or 0),
            "denied_access_requests": int((existing or {}).get("denied_access_requests") or 0),
            "risk_score": 0,
            "risk_flags": [],
            "notes": (existing or {}).get("notes"),
            "created_at": (existing or {}).get("created_at") or now,
            "updated_at": now,
        }
        row["requester_type"] = _requester_type(row.get("requester_role"))
        row.update(_risk_profile_fields(row))
        return self._save(_REQUESTER_PROFILES, row)

    def _saved_by_profile_and_passport(self, profile_id: str, passport_id: str) -> dict[str, Any] | None:
        for row in self._rows(_SAVED):
            if str(row.get("requester_profile_id")) == profile_id and str(row.get("passport_id")) == passport_id:
                return row
        return None

    def _saved_for_email(self, saved_id: str, requester_email: str) -> dict[str, Any]:
        row = self._by_id(_SAVED, saved_id)
        if not row or str(row.get("requester_email")) != _normalize_email(requester_email):
            raise RecruiterSavedPassportNotFoundError(saved_id)
        return row

    def _write_audit_event(self, saved: dict[str, Any], event_type: str) -> None:
        self._insert(
            _AUDIT_EVENTS,
            {
                "id": str(uuid4()),
                "user_id": saved.get("student_user_id"),
                "proof_session_id": saved.get("proof_session_id"),
                "passport_id": saved.get("passport_id"),
                "access_request_id": None,
                "access_grant_id": None,
                "event_type": event_type,
                "actor_type": "recruiter",
                "actor_email": saved.get("requester_email"),
                "actor_user_id": None,
                "event_summary": _event_summary(event_type),
                "metadata": {
                    "saved_passport_id": saved.get("id"),
                    "requester_profile_id": saved.get("requester_profile_id"),
                    "status": saved.get("status"),
                    "tags": list(saved.get("tags") or []),
                    "reviewed_sections": list(saved.get("reviewed_sections") or []),
                },
                "created_at": _now(),
            },
        )

    def _write_view_event(self, passport: dict[str, Any], payload: RecruiterSavedPassportCreate) -> None:
        self._insert(
            _PASSPORT_VIEW_EVENTS,
            {
                "id": str(uuid4()),
                "passport_id": str(passport["id"]),
                "public_slug": str(passport["public_slug"]),
                "viewer_type": "recruiter",
                "viewer_email": _normalize_email(str(payload.requester_email)),
                "viewer_organization": payload.organization_name,
                "ip_hash": None,
                "user_agent_hash": None,
                "viewed_sections": ["saved_passport"],
                "created_at": _now(),
            },
        )

    def _response(self, row: dict[str, Any]) -> RecruiterSavedPassportResponse:
        passport = self._by_id(_PASSPORTS, str(row.get("passport_id")))
        return RecruiterSavedPassportResponse(
            id=str(row["id"]),
            requester_profile_id=str(row["requester_profile_id"]),
            passport_id=str(row["passport_id"]),
            proof_session_id=str(row["proof_session_id"]),
            student_user_id=str(row["student_user_id"]),
            requester_email=str(row["requester_email"]),
            organization_name=row.get("organization_name"),
            status=row.get("status") or "saved",
            tags=list(row.get("tags") or []),
            private_notes=row.get("private_notes"),
            reviewed_sections=list(row.get("reviewed_sections") or []),
            fit_score=row.get("fit_score"),
            fit_reason=row.get("fit_reason"),
            last_viewed_at=row.get("last_viewed_at"),
            public_slug=(passport or {}).get("public_slug"),
            public_title=(passport or {}).get("public_title"),
            public_summary=(passport or {}).get("public_summary"),
            field=(passport or {}).get("field"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _rows(self, table: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            return list(self._client.get(table, {}).values())
        result = self._client.table(table).select("*").execute()
        return getattr(result, "data", []) or []

    def _first_where(self, table: str, field: str, value: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            for row in self._client.get(table, {}).values():
                if str(row.get(field)) == value:
                    return row
            return None
        result = self._client.table(table).select("*").eq(field, value).limit(1).execute()
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _by_id(self, table: str, row_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            return self._client.get(table, {}).get(row_id)
        result = self._client.table(table).select("*").eq("id", row_id).limit(1).execute()
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        if isinstance(self._client, dict):
            self._client.setdefault(table, {})[str(row["id"])] = row
            return row
        result = self._client.table(table).insert(row).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError(f"{table} insert returned no data.")
        return rows[0]

    def _save(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        if isinstance(self._client, dict):
            self._client.setdefault(table, {})[str(row["id"])] = row
            return row
        result = self._client.table(table).upsert(row).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError(f"{table} upsert returned no data.")
        return rows[0]

    def _delete(self, table: str, row_id: str) -> None:
        if isinstance(self._client, dict):
            self._client.setdefault(table, {}).pop(row_id, None)
            return
        self._client.table(table).delete().eq("id", row_id).execute()


def _clean_tags(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))[:25]


def _clean_sections(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))[:50]


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _email_domain(email: str) -> str | None:
    cleaned = _normalize_email(email)
    if "@" not in cleaned:
        return None
    domain = cleaned.rsplit("@", 1)[-1].strip(".")
    return domain or None


def _requester_type(role: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(role or "").strip().lower()).strip("_")
    return normalized if normalized in _ALLOWED_REQUESTER_TYPES else "recruiter"


def _risk_profile_fields(row: dict[str, Any]) -> dict[str, Any]:
    flags = set(str(flag) for flag in row.get("risk_flags") or [])
    domain = str(row.get("organization_domain") or "").lower()
    if domain in _FREE_EMAIL_DOMAINS:
        flags.add("free_email_domain")
    else:
        flags.discard("free_email_domain")
    if not row.get("organization_name"):
        flags.add("missing_organization")
    else:
        flags.discard("missing_organization")
    if row.get("verification_status") == "blocked":
        flags.add("blocked_domain_future_placeholder")
    else:
        flags.discard("blocked_domain_future_placeholder")

    score = 0
    if "free_email_domain" in flags:
        score += 10
    if "missing_organization" in flags:
        score += 10
    if row.get("verification_status") == "blocked":
        score += 100
    return {"risk_flags": sorted(flags), "risk_score": score}


def _event_summary(event_type: str) -> str:
    return {
        "passport_saved": "Recruiter saved a public Work Passport.",
        "candidate_shortlisted": "Recruiter shortlisted a candidate Work Passport.",
        "recruiter_note_updated": "Recruiter updated private saved-candidate notes.",
        "saved_passport_archived": "Recruiter archived a saved Work Passport.",
    }.get(event_type, "Recruiter saved-passport workflow event.")


def _now() -> datetime:
    return datetime.now(UTC)
