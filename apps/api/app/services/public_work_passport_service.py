"""Public Work Passport and protected evidence access service."""

from __future__ import annotations

import re
import secrets
from hashlib import sha256
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.schemas.public_work_passport import (
    AccessRequestCreate,
    AccessRequestDecision,
    AccessRequestPublicResponse,
    EvidenceAccessGrantResponse,
    EvidenceAccessRequestResponse,
    ProtectedEvidenceResponse,
    PublicPassportSafeResponse,
    PublicWorkPassportCreateRequest,
    PublicWorkPassportStudentResponse,
)
from app.services.extension_proof_service import ExtensionProofSessionNotFoundError
from app.services.verification_readiness_service import compute_readiness_report

_PASSPORTS = "public_work_passports"
_REQUESTS = "evidence_access_requests"
_GRANTS = "evidence_access_grants"
_AUDIT_EVENTS = "evidence_access_audit_events"
_NOTIFICATION_EVENTS = "notification_events"
_PASSPORT_VIEW_EVENTS = "public_passport_view_events"
_USERS = "users"
_SESSIONS = "extension_proof_sessions"
_SKILL_EVIDENCE = "skill_evidence"
_PROFILES = "student_profiles"
_AI_DOMAIN = "ai_domain_review_results"
_VERIFICATION_REVIEWS = "verification_review_requests"
_WORKFLOW = "workflow_analysis_results"
_GITHUB = "extension_proof_github_analysis"
_LIVE = "live_website_check_results"
_PRIVACY = "workflow_privacy_scan_results"
_DEFENSE = "project_defense_analysis_results"

_PUBLIC_DISCLOSURE = (
    "This public Work Passport shows a safe summary only. Protected evidence, "
    "private media, full transcripts, hidden files, and sensitive data are not "
    "publicly exposed. Access to protected evidence requires approval."
)
_PROTECTED_DISCLOSURE = (
    "Protected evidence is shown only for approved, unexpired, non-revoked access "
    "grants and only for the sections included in the grant."
)
_DEFAULT_VISIBLE = [
    "summary",
    "ai_domain_review",
    "readiness",
    "skills",
    "public_links",
]
_DEFAULT_REQUEST_SECTIONS = [
    "ai_domain_review",
    "readiness_report",
    "github_analysis",
    "workflow_analysis",
    "project_defense_summary",
]
_ALLOWED_SECTIONS = {
    "ai_domain_review",
    "readiness_report",
    "github_analysis",
    "workflow_analysis",
    "live_website_check",
    "privacy_scan_summary",
    "project_defense_summary",
    "project_defense_transcript",
}


class PublicWorkPassportNotFoundError(LookupError):
    """Passport not found or not public."""


class EvidenceAccessRequestNotFoundError(LookupError):
    """Access request not found for the scoped student."""


class EvidenceAccessGrantNotFoundError(LookupError):
    """Access grant not found for the scoped student."""


class EvidenceAccessDeniedError(PermissionError):
    """Access token is missing, expired, revoked, or otherwise invalid."""


class PublicWorkPassportService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def create_or_update_passport(
        self,
        user_id: str,
        session_id: str,
        payload: PublicWorkPassportCreateRequest | None = None,
    ) -> PublicWorkPassportStudentResponse:
        body = payload or PublicWorkPassportCreateRequest()
        session = self._get_session(user_id, session_id)
        evidence = self._gather_evidence(user_id, session_id, session)
        existing = self._passport_by_session(user_id, session_id)
        now = _now()
        row = {
            "id": existing.get("id") if existing else str(uuid4()),
            "user_id": user_id,
            "proof_session_id": session_id,
            "public_slug": existing.get("public_slug") if existing else self._new_slug(evidence),
            "is_public": body.is_public,
            "public_title": body.public_title or _default_title(evidence),
            "public_summary": body.public_summary or _default_public_summary(evidence),
            "field": body.field or _field(evidence),
            "visible_sections": _sections_or_default(body.visible_sections, _DEFAULT_VISIBLE),
            "created_at": existing.get("created_at") if existing else now,
            "updated_at": now,
        }
        saved = self._upsert_passport(row)
        if existing is None:
            self._write_audit_event(
                user_id=user_id,
                proof_session_id=session_id,
                passport_id=str(saved["id"]),
                event_type="passport_created",
                actor_type="student",
                actor_user_id=user_id,
                event_summary="Public Work Passport created.",
                metadata={"public_slug": saved.get("public_slug"), "is_public": saved.get("is_public", True)},
            )
        return _passport_student_response(saved)

    def get_student_passport(self, user_id: str, session_id: str) -> PublicWorkPassportStudentResponse:
        self._get_session(user_id, session_id)
        row = self._passport_by_session(user_id, session_id)
        if row is None:
            raise PublicWorkPassportNotFoundError(session_id)
        return _passport_student_response(row)

    def get_public_passport(
        self,
        public_slug: str,
        viewer_context: dict[str, Any] | None = None,
    ) -> PublicPassportSafeResponse:
        passport = self._passport_by_slug(public_slug)
        if not passport or not passport.get("is_public", True):
            raise PublicWorkPassportNotFoundError(public_slug)
        session = self._get_session(str(passport["user_id"]), str(passport["proof_session_id"]))
        evidence = self._gather_evidence(str(passport["user_id"]), str(passport["proof_session_id"]), session)
        response = _public_response(passport, evidence)
        context = viewer_context or {}
        self._insert(
            _PASSPORT_VIEW_EVENTS,
            {
                "id": str(uuid4()),
                "passport_id": str(passport["id"]),
                "public_slug": str(passport["public_slug"]),
                "viewer_type": str(context.get("viewer_type") or "anonymous"),
                "viewer_email": context.get("viewer_email"),
                "viewer_organization": context.get("viewer_organization"),
                "ip_hash": _hash_optional(context.get("ip_address")),
                "user_agent_hash": _hash_optional(context.get("user_agent")),
                "viewed_sections": list(response.visible_sections or []),
                "created_at": _now(),
            },
        )
        return response

    def create_access_request(
        self,
        public_slug: str,
        payload: AccessRequestCreate,
    ) -> AccessRequestPublicResponse:
        passport = self._passport_by_slug(public_slug)
        if not passport or not passport.get("is_public", True):
            raise PublicWorkPassportNotFoundError(public_slug)
        requested_sections = _sections_or_default(payload.requested_sections, _DEFAULT_REQUEST_SECTIONS)
        now = _now()
        row = {
            "id": str(uuid4()),
            "user_id": str(passport["user_id"]),
            "proof_session_id": str(passport["proof_session_id"]),
            "passport_id": str(passport["id"]),
            "requester_name": payload.requester_name,
            "requester_email": payload.requester_email,
            "requester_organization": payload.requester_organization,
            "requester_role": payload.requester_role,
            "request_reason": payload.request_reason,
            "status": "pending",
            "requested_sections": requested_sections,
            "decision_notes": None,
            "decided_at": None,
            "expires_at": None,
            "created_at": now,
            "updated_at": now,
        }
        saved = self._insert(_REQUESTS, row)
        self._write_audit_event(
            user_id=str(passport["user_id"]),
            proof_session_id=str(passport["proof_session_id"]),
            passport_id=str(passport["id"]),
            access_request_id=str(saved["id"]),
            event_type="access_requested",
            actor_type="recruiter",
            actor_email=payload.requester_email,
            event_summary="Recruiter requested access to protected evidence.",
            metadata={
                "requester_organization": payload.requester_organization,
                "requester_role": payload.requester_role,
                "requested_sections": requested_sections,
            },
        )
        self._write_notification_event(
            user_id=str(passport["user_id"]),
            event_type="access_requested",
            recipient_email=self._user_email(str(passport["user_id"])),
            subject="Protected evidence access requested",
            body=f"{payload.requester_name} requested access to protected evidence for {passport.get('public_title') or 'a public Work Passport'}.",
            metadata={
                "passport_id": str(passport["id"]),
                "access_request_id": str(saved["id"]),
                "requester_email": payload.requester_email,
                "requested_sections": requested_sections,
            },
        )
        return AccessRequestPublicResponse(
            id=str(saved["id"]),
            status="pending",
            message="Access request submitted for student review.",
        )

    def list_access_requests(self, user_id: str, session_id: str) -> list[EvidenceAccessRequestResponse]:
        self._get_session(user_id, session_id)
        rows = self._rows_by_session(_REQUESTS, user_id, session_id)
        rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
        return [_request_response(r) for r in rows]

    def approve_request(
        self,
        user_id: str,
        request_id: str,
        payload: AccessRequestDecision | None = None,
    ) -> EvidenceAccessGrantResponse:
        body = payload or AccessRequestDecision()
        request = self._request_for_user(user_id, request_id)
        now = _now()
        sections = _sections_or_default(body.sections or request.get("requested_sections") or [], _DEFAULT_REQUEST_SECTIONS)
        request.update(
            {
                "status": "approved",
                "decision_notes": body.decision_notes,
                "decided_at": now,
                "expires_at": body.expires_at,
                "updated_at": now,
            }
        )
        self._save(_REQUESTS, request)
        existing = self._grant_by_request(str(request["id"]))
        grant = {
            "id": existing.get("id") if existing else str(uuid4()),
            "access_request_id": str(request["id"]),
            "user_id": user_id,
            "proof_session_id": str(request["proof_session_id"]),
            "requester_email": str(request["requester_email"]),
            "granted_sections": sections,
            "access_token": existing.get("access_token") if existing else _new_token(),
            "expires_at": body.expires_at,
            "revoked_at": None,
            "created_at": existing.get("created_at") if existing else now,
            "updated_at": now,
        }
        saved = self._save(_GRANTS, grant)
        self._write_audit_event(
            user_id=user_id,
            proof_session_id=str(request["proof_session_id"]),
            passport_id=str(request["passport_id"]),
            access_request_id=str(request["id"]),
            event_type="access_approved",
            actor_type="student",
            actor_user_id=user_id,
            event_summary="Student approved protected evidence access request.",
            metadata={"granted_sections": sections, "expires_at": body.expires_at.isoformat() if body.expires_at else None},
        )
        self._write_audit_event(
            user_id=user_id,
            proof_session_id=str(request["proof_session_id"]),
            passport_id=str(request["passport_id"]),
            access_request_id=str(request["id"]),
            access_grant_id=str(saved["id"]),
            event_type="access_granted",
            actor_type="student",
            actor_user_id=user_id,
            event_summary="Protected evidence access grant created.",
            metadata={"granted_sections": sections, "expires_at": body.expires_at.isoformat() if body.expires_at else None},
        )
        self._write_notification_event(
            user_id=user_id,
            event_type="access_approved",
            recipient_email=str(request["requester_email"]),
            subject="Protected evidence access approved",
            body="Your request to view protected evidence was approved.",
            metadata={
                "passport_id": str(request["passport_id"]),
                "access_request_id": str(request["id"]),
                "access_grant_id": str(saved["id"]),
                "granted_sections": sections,
                "expires_at": body.expires_at.isoformat() if body.expires_at else None,
            },
        )
        return _grant_response(saved)

    def deny_request(
        self,
        user_id: str,
        request_id: str,
        payload: AccessRequestDecision | None = None,
    ) -> EvidenceAccessRequestResponse:
        body = payload or AccessRequestDecision()
        request = self._request_for_user(user_id, request_id)
        now = _now()
        request.update(
            {
                "status": "denied",
                "decision_notes": body.decision_notes,
                "decided_at": now,
                "expires_at": body.expires_at,
                "updated_at": now,
            }
        )
        saved = self._save(_REQUESTS, request)
        self._write_audit_event(
            user_id=user_id,
            proof_session_id=str(request["proof_session_id"]),
            passport_id=str(request["passport_id"]),
            access_request_id=str(request["id"]),
            event_type="access_denied",
            actor_type="student",
            actor_user_id=user_id,
            event_summary="Student denied protected evidence access request.",
            metadata={"decision_notes_provided": bool(body.decision_notes)},
        )
        self._write_notification_event(
            user_id=user_id,
            event_type="access_denied",
            recipient_email=str(request["requester_email"]),
            subject="Protected evidence access denied",
            body="Your request to view protected evidence was denied.",
            metadata={"passport_id": str(request["passport_id"]), "access_request_id": str(request["id"])},
        )
        return _request_response(saved)

    def revoke_grant(self, user_id: str, grant_id: str) -> EvidenceAccessGrantResponse:
        grant = self._grant_for_user(user_id, grant_id)
        grant.update({"revoked_at": _now(), "updated_at": _now()})
        saved = self._save(_GRANTS, grant)
        request = self._by_id(_REQUESTS, str(grant["access_request_id"]))
        passport_id = str(request["passport_id"]) if request else None
        self._write_audit_event(
            user_id=user_id,
            proof_session_id=str(grant["proof_session_id"]),
            passport_id=passport_id,
            access_request_id=str(grant["access_request_id"]),
            access_grant_id=str(grant["id"]),
            event_type="access_revoked",
            actor_type="student",
            actor_user_id=user_id,
            event_summary="Student revoked protected evidence access grant.",
            metadata={"granted_sections": list(grant.get("granted_sections") or [])},
        )
        self._write_notification_event(
            user_id=user_id,
            event_type="access_revoked",
            recipient_email=str(grant["requester_email"]),
            subject="Protected evidence access revoked",
            body="A protected evidence access grant was revoked.",
            metadata={
                "passport_id": passport_id,
                "access_request_id": str(grant["access_request_id"]),
                "access_grant_id": str(grant["id"]),
            },
        )
        return _grant_response(saved)

    def get_protected_evidence(self, access_token: str) -> ProtectedEvidenceResponse:
        grant = self._grant_by_token(access_token)
        if not grant or grant.get("revoked_at"):
            raise EvidenceAccessDeniedError("Access token is invalid or revoked.")
        expires_at = _parse_dt(grant.get("expires_at"))
        if expires_at and expires_at <= _now():
            self._write_access_expired_event(grant)
            raise EvidenceAccessDeniedError("Access token is expired.")
        user_id = str(grant["user_id"])
        session_id = str(grant["proof_session_id"])
        session = self._get_session(user_id, session_id)
        evidence = self._gather_evidence(user_id, session_id, session)
        sections = [s for s in list(grant.get("granted_sections") or []) if s in _ALLOWED_SECTIONS]
        request = self._by_id(_REQUESTS, str(grant["access_request_id"]))
        self._write_audit_event(
            user_id=user_id,
            proof_session_id=session_id,
            passport_id=str(request["passport_id"]) if request else None,
            access_request_id=str(grant["access_request_id"]),
            access_grant_id=str(grant["id"]),
            event_type="protected_evidence_viewed",
            actor_type="recruiter",
            actor_email=str(grant["requester_email"]),
            event_summary="Protected evidence viewed with an approved access grant.",
            metadata={"viewed_sections": sections},
        )
        return ProtectedEvidenceResponse(
            proof_session_id=session_id,
            requester_email=str(grant["requester_email"]),
            granted_sections=sections,
            expires_at=grant.get("expires_at"),
            evidence=_protected_evidence(evidence, sections),
            disclosure_note=_PROTECTED_DISCLOSURE,
        )

    def _write_audit_event(
        self,
        *,
        user_id: str,
        proof_session_id: str,
        passport_id: str | None,
        event_type: str,
        actor_type: str,
        access_request_id: str | None = None,
        access_grant_id: str | None = None,
        actor_email: str | None = None,
        actor_user_id: str | None = None,
        event_summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._insert(
            _AUDIT_EVENTS,
            {
                "id": str(uuid4()),
                "user_id": user_id,
                "proof_session_id": proof_session_id,
                "passport_id": passport_id,
                "access_request_id": access_request_id,
                "access_grant_id": access_grant_id,
                "event_type": event_type,
                "actor_type": actor_type,
                "actor_email": actor_email,
                "actor_user_id": actor_user_id,
                "event_summary": event_summary,
                "metadata": metadata or {},
                "created_at": _now(),
            },
        )

    def _write_notification_event(
        self,
        *,
        user_id: str,
        event_type: str,
        recipient_email: str,
        subject: str,
        body: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._insert(
            _NOTIFICATION_EVENTS,
            {
                "id": str(uuid4()),
                "user_id": user_id,
                "event_type": event_type,
                "channel": "email",
                "recipient_email": recipient_email,
                "subject": subject,
                "body": body,
                "status": "pending",
                "metadata": metadata or {},
                "created_at": _now(),
                "sent_at": None,
                "failure_reason": None,
            },
        )

    def _write_access_expired_event(self, grant: dict[str, Any]) -> None:
        request = self._by_id(_REQUESTS, str(grant["access_request_id"]))
        self._write_audit_event(
            user_id=str(grant["user_id"]),
            proof_session_id=str(grant["proof_session_id"]),
            passport_id=str(request["passport_id"]) if request else None,
            access_request_id=str(grant["access_request_id"]),
            access_grant_id=str(grant["id"]),
            event_type="access_expired",
            actor_type="system",
            actor_email=str(grant["requester_email"]),
            event_summary="Protected evidence access grant expired.",
            metadata={"expires_at": grant.get("expires_at")},
        )

    def _gather_evidence(self, user_id: str, session_id: str, session: dict[str, Any]) -> dict[str, Any]:
        skill = self._skill_evidence(user_id, str(session.get("skill_evidence_id") or ""))
        workflow = self._row_by_session(_WORKFLOW, user_id, session_id)
        github = self._row_by_session(_GITHUB, user_id, session_id)
        live = self._row_by_session(_LIVE, user_id, session_id)
        privacy = self._row_by_session(_PRIVACY, user_id, session_id)
        defense = self._row_by_session(_DEFENSE, user_id, session_id)
        ai_domain = self._row_by_session(_AI_DOMAIN, user_id, session_id)
        ai_review = self._row_by_session(_VERIFICATION_REVIEWS, user_id, session_id)
        profile = self._profile(user_id)
        claimed = _claimed_skills(session, skill, workflow, github, ai_domain)
        readiness = compute_readiness_report(
            proof_session_id=session_id,
            session_status=str(session.get("status") or ""),
            website_url=_website_url(session, skill),
            claimed_skills=claimed,
            workflow_analysis=workflow,
            live_check=live,
            github_analysis=github,
            privacy_scan=privacy,
            defense_analysis=defense,
        )
        return {
            "session": session,
            "skill_evidence": skill,
            "workflow_analysis": workflow,
            "github_analysis": github,
            "live_website_check": live,
            "privacy_scan": privacy,
            "project_defense_analysis": defense,
            "ai_domain_review": ai_domain,
            "ai_review": ai_review,
            "student_profile": profile,
            "claimed_skills": claimed,
            "readiness_report": readiness,
        }

    def _get_session(self, user_id: str, session_id: str) -> dict[str, Any]:
        if isinstance(self._client, dict):
            row = self._client.setdefault(_SESSIONS, {}).get(session_id)
            if not row or str(row.get("user_id")) != user_id:
                raise ExtensionProofSessionNotFoundError(session_id)
            return row
        result = (
            self._client.table(_SESSIONS)
            .select("*")
            .eq("id", session_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if result is None or not getattr(result, "data", None):
            raise ExtensionProofSessionNotFoundError(session_id)
        return result.data

    def _new_slug(self, evidence: dict[str, Any]) -> str:
        base = _slug_base(_default_title(evidence) or _field(evidence) or "work-passport")
        for _ in range(10):
            slug = f"{base}-{secrets.token_urlsafe(5).lower().replace('_', '-')}"
            if self._passport_by_slug(slug) is None:
                return slug
        return f"work-passport-{secrets.token_urlsafe(12).lower().replace('_', '-')}"

    def _passport_by_session(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            for row in self._client.get(_PASSPORTS, {}).values():
                if str(row.get("user_id")) == user_id and str(row.get("proof_session_id")) == session_id:
                    return row
            return None
        result = (
            self._client.table(_PASSPORTS)
            .select("*")
            .eq("user_id", user_id)
            .eq("proof_session_id", session_id)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _passport_by_slug(self, slug: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            for row in self._client.get(_PASSPORTS, {}).values():
                if str(row.get("public_slug")) == slug:
                    return row
            return None
        result = (
            self._client.table(_PASSPORTS)
            .select("*")
            .eq("public_slug", slug)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _request_for_user(self, user_id: str, request_id: str) -> dict[str, Any]:
        row = self._by_id(_REQUESTS, request_id)
        if not row or str(row.get("user_id")) != user_id:
            raise EvidenceAccessRequestNotFoundError(request_id)
        return row

    def _grant_for_user(self, user_id: str, grant_id: str) -> dict[str, Any]:
        row = self._by_id(_GRANTS, grant_id)
        if not row or str(row.get("user_id")) != user_id:
            raise EvidenceAccessGrantNotFoundError(grant_id)
        return row

    def _grant_by_request(self, request_id: str) -> dict[str, Any] | None:
        return self._first_where(_GRANTS, "access_request_id", request_id)

    def _grant_by_token(self, token: str) -> dict[str, Any] | None:
        return self._first_where(_GRANTS, "access_token", token)

    def _row_by_session(self, table: str, user_id: str, session_id: str) -> dict[str, Any] | None:
        rows = self._rows_by_session(table, user_id, session_id)
        return rows[0] if rows else None

    def _rows_by_session(self, table: str, user_id: str, session_id: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            return [
                row for row in self._client.get(table, {}).values()
                if str(row.get("user_id")) == user_id and str(row.get("proof_session_id")) == session_id
            ]
        result = (
            self._client.table(table)
            .select("*")
            .eq("user_id", user_id)
            .eq("proof_session_id", session_id)
            .execute()
        )
        return getattr(result, "data", []) or []

    def _skill_evidence(self, user_id: str, evidence_id: str) -> dict[str, Any] | None:
        if not evidence_id:
            return None
        if isinstance(self._client, dict):
            row = self._client.get(_SKILL_EVIDENCE, {}).get(evidence_id)
            return row if row and str(row.get("user_id")) == user_id else None
        result = (
            self._client.table(_SKILL_EVIDENCE)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", evidence_id)
            .maybe_single()
            .execute()
        )
        return getattr(result, "data", None) if result is not None else None

    def _profile(self, user_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            for row in self._client.get(_PROFILES, {}).values():
                if str(row.get("user_id")) == user_id:
                    return row
            return None
        result = (
            self._client.table(_PROFILES)
            .select("*")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return getattr(result, "data", None) if result is not None else None

    def _user_email(self, user_id: str) -> str:
        if isinstance(self._client, dict):
            row = self._client.get(_USERS, {}).get(user_id)
            if row and row.get("email"):
                return str(row["email"])
            profile = self._profile(user_id) or {}
            return str(profile.get("email") or "")
        result = self._client.table(_USERS).select("email").eq("id", user_id).maybe_single().execute()
        data = getattr(result, "data", None) if result is not None else None
        return str((data or {}).get("email") or "")

    def _upsert_passport(self, row: dict[str, Any]) -> dict[str, Any]:
        if isinstance(self._client, dict):
            return self._save(_PASSPORTS, row)
        result = (
            self._client.table(_PASSPORTS)
            .upsert(row, on_conflict="proof_session_id")
            .execute()
        )
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError("public_work_passports upsert returned no data.")
        return rows[0]

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

    def _by_id(self, table: str, row_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            return self._client.get(table, {}).get(row_id)
        result = self._client.table(table).select("*").eq("id", row_id).limit(1).execute()
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _first_where(self, table: str, field: str, value: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            for row in self._client.get(table, {}).values():
                if str(row.get(field)) == value:
                    return row
            return None
        result = self._client.table(table).select("*").eq(field, value).limit(1).execute()
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None


def _public_response(passport: dict[str, Any], evidence: dict[str, Any]) -> PublicPassportSafeResponse:
    readiness = evidence["readiness_report"]
    ai_domain = evidence.get("ai_domain_review") or {}
    ai_review = evidence.get("ai_review") or {}
    profile = evidence.get("student_profile") or {}
    return PublicPassportSafeResponse(
        id=str(passport["id"]),
        public_slug=str(passport["public_slug"]),
        proof_session_id=str(passport["proof_session_id"]),
        student_display_name=_public_display_name(profile),
        field=passport.get("field") or _field(evidence),
        public_title=passport.get("public_title"),
        public_summary=passport.get("public_summary"),
        visible_sections=list(passport.get("visible_sections") or []),
        ai_reviewed_status=ai_review.get("ai_review_status"),
        ai_domain_review_summary=ai_domain.get("recruiter_summary"),
        ai_domain_reviewer_name=ai_domain.get("reviewer_name"),
        ai_domain_review_status=ai_domain.get("ai_domain_review_status"),
        verified_skills=list(ai_domain.get("verified_skills") or readiness.strongly_supported_skills),
        partially_verified_skills=list(ai_domain.get("partially_verified_skills") or readiness.partially_supported_skills),
        skills_needing_more_evidence=list(ai_domain.get("skills_needing_more_evidence") or [_clean_need_more(s) for s in readiness.needs_more_evidence]),
        readiness_score=readiness.readiness_score,
        readiness_level=readiness.readiness_level,
        public_project_links=_public_links(evidence),
        disclosure_note=_PUBLIC_DISCLOSURE,
    )


def _protected_evidence(evidence: dict[str, Any], sections: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    readiness = evidence["readiness_report"]
    defense = evidence.get("project_defense_analysis") or {}
    if "ai_domain_review" in sections and evidence.get("ai_domain_review"):
        out["ai_domain_review"] = _safe_dict(evidence["ai_domain_review"])
    if "readiness_report" in sections:
        out["readiness_report"] = {
            "readiness_score": readiness.readiness_score,
            "readiness_level": readiness.readiness_level,
            "strongly_supported_skills": readiness.strongly_supported_skills,
            "partially_supported_skills": readiness.partially_supported_skills,
            "needs_more_evidence": readiness.needs_more_evidence,
            "risk_flags": readiness.risk_flags,
            "recommended_next_actions": readiness.recommended_next_actions,
            "recruiter_summary": readiness.recruiter_summary,
        }
    if "github_analysis" in sections and evidence.get("github_analysis"):
        out["github_analysis"] = _safe_dict(evidence["github_analysis"])
    if "workflow_analysis" in sections and evidence.get("workflow_analysis"):
        out["workflow_analysis"] = _safe_dict(evidence["workflow_analysis"])
    if "live_website_check" in sections and evidence.get("live_website_check"):
        out["live_website_check"] = _safe_dict(evidence["live_website_check"])
    if "privacy_scan_summary" in sections and evidence.get("privacy_scan"):
        scan = evidence["privacy_scan"]
        out["privacy_scan_summary"] = {
            "status": scan.get("status"),
            "scan_summary": scan.get("scan_summary"),
            "redaction_count": scan.get("redaction_count"),
        }
    if "project_defense_summary" in sections and defense:
        out["project_defense_summary"] = {
            "transcript_summary": defense.get("transcript_summary"),
            "skills_mentioned": defense.get("skills_mentioned") or [],
            "skills_explained_well": defense.get("skills_explained_well") or [],
            "skills_missing_from_explanation": defense.get("skills_missing_from_explanation") or [],
            "overall_defense_score": defense.get("overall_defense_score"),
            "recruiter_summary": defense.get("recruiter_summary"),
            "risk_flags": defense.get("risk_flags") or [],
        }
    if "project_defense_transcript" in sections and defense:
        out["project_defense_transcript"] = {
            "transcript_text": defense.get("transcript_text"),
            "transcript_reviewed": defense.get("transcript_reviewed"),
            "transcription_status": defense.get("transcription_status"),
        }
    return out


def _safe_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        k: _safe_value(v)
        for k, v in row.items()
        if not _blocked_private_key(k)
    }


def _safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _safe_value(v) for k, v in value.items() if not _blocked_private_key(k)}
    if isinstance(value, list):
        return [_safe_value(v) for v in value]
    return value


def _blocked_private_key(key: str) -> bool:
    normalized = key.lower()
    blocked_exact = {
        "media_storage_path",
        "media_url",
        "video_url",
        "transcript_text",
        "proof_data",
        "access_token",
    }
    blocked_fragments = ("private", "internal", "debug", "raw_risk", "raw_metadata")
    return normalized in blocked_exact or any(fragment in normalized for fragment in blocked_fragments)


def _passport_student_response(row: dict[str, Any]) -> PublicWorkPassportStudentResponse:
    return PublicWorkPassportStudentResponse(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        proof_session_id=str(row["proof_session_id"]),
        public_slug=str(row["public_slug"]),
        is_public=bool(row.get("is_public", True)),
        public_title=row.get("public_title"),
        public_summary=row.get("public_summary"),
        field=row.get("field"),
        visible_sections=list(row.get("visible_sections") or []),
        public_url_path=f"/passport/{row['public_slug']}",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _request_response(row: dict[str, Any]) -> EvidenceAccessRequestResponse:
    return EvidenceAccessRequestResponse(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        proof_session_id=str(row["proof_session_id"]),
        passport_id=str(row["passport_id"]),
        requester_name=str(row["requester_name"]),
        requester_email=str(row["requester_email"]),
        requester_organization=row.get("requester_organization"),
        requester_role=row.get("requester_role"),
        request_reason=row.get("request_reason"),
        status=row.get("status", "pending"),
        requested_sections=list(row.get("requested_sections") or []),
        decision_notes=row.get("decision_notes"),
        decided_at=row.get("decided_at"),
        expires_at=row.get("expires_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _grant_response(row: dict[str, Any]) -> EvidenceAccessGrantResponse:
    return EvidenceAccessGrantResponse(
        id=str(row["id"]),
        access_request_id=str(row["access_request_id"]),
        user_id=str(row["user_id"]),
        proof_session_id=str(row["proof_session_id"]),
        requester_email=str(row["requester_email"]),
        granted_sections=list(row.get("granted_sections") or []),
        access_token=str(row["access_token"]),
        expires_at=row.get("expires_at"),
        revoked_at=row.get("revoked_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _claimed_skills(*rows: dict[str, Any] | None) -> list[str]:
    values: list[str] = []
    for row in rows:
        if not row:
            continue
        if row.get("skill_name"):
            values.append(str(row["skill_name"]))
        for key in ("claimed_skills", "supported_skills", "matched_claimed_skills", "verified_skills", "partially_verified_skills"):
            raw = row.get(key)
            if isinstance(raw, list):
                values.extend(str(v) for v in raw if str(v).strip())
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        for key in ("claimed_skills", "skills"):
            raw = metadata.get(key)
            if isinstance(raw, list):
                values.extend(str(v) for v in raw if str(v).strip())
    return _dedupe([v.strip() for v in values if v.strip()])


def _default_title(evidence: dict[str, Any]) -> str:
    skill = evidence.get("skill_evidence") or {}
    metadata = skill.get("metadata") if isinstance(skill.get("metadata"), dict) else {}
    return str(metadata.get("evidence_title") or metadata.get("title") or skill.get("skill_name") or "Verified Work Passport")


def _default_public_summary(evidence: dict[str, Any]) -> str:
    ai_domain = evidence.get("ai_domain_review") or {}
    if ai_domain.get("recruiter_summary"):
        return str(ai_domain["recruiter_summary"])
    readiness = evidence["readiness_report"]
    if readiness.recruiter_summary:
        return readiness.recruiter_summary
    skills = evidence.get("claimed_skills") or []
    if skills:
        return f"Public work passport for evidence related to {', '.join(skills[:5])}."
    return "Public work passport with safe summary evidence."


def _field(evidence: dict[str, Any]) -> str | None:
    for row_key in ("skill_evidence", "student_profile"):
        row = evidence.get(row_key) or {}
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        for key in ("field", "discipline", "domain", "major"):
            value = metadata.get(key) or row.get(key)
            if value:
                return str(value)
    ai = evidence.get("ai_domain_review") or {}
    return ai.get("domain")


def _public_links(evidence: dict[str, Any]) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    skill = evidence.get("skill_evidence") or {}
    github = evidence.get("github_analysis") or {}
    live = evidence.get("live_website_check") or {}
    for label, url in [
        ("Project URL", skill.get("evidence_url")),
        ("Repository", skill.get("repository_url") or github.get("repo_url")),
        ("Live Project", live.get("url") or live.get("website_url")),
    ]:
        if isinstance(url, str) and url.startswith(("https://", "http://")) and not _private_url(url):
            links.append({"label": label, "url": url})
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for link in links:
        if link["url"] not in seen:
            seen.add(link["url"])
            out.append(link)
    return out


def _website_url(session: dict[str, Any], skill: dict[str, Any] | None) -> str:
    proof_data = session.get("proof_data") if isinstance(session.get("proof_data"), dict) else {}
    return str(proof_data.get("website_url") or proof_data.get("url") or (skill or {}).get("evidence_url") or "")


def _public_display_name(profile: dict[str, Any]) -> str | None:
    preferences = profile.get("preferences") if isinstance(profile.get("preferences"), dict) else {}
    if preferences.get("show_public_name") is False:
        return None
    return profile.get("full_name")


def _sections_or_default(sections: list[str], default: list[str]) -> list[str]:
    cleaned = [s for s in _dedupe([str(s).strip() for s in sections]) if s in _ALLOWED_SECTIONS or s in _DEFAULT_VISIBLE]
    return cleaned or list(default)


def _clean_need_more(value: str) -> str:
    return value.split(" — ", 1)[0].strip()


def _slug_base(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48] or "work-passport"


def _private_url(url: str) -> bool:
    return any(host in url.lower() for host in ("localhost", "127.0.0.1", "192.168.", "10."))


def _new_token() -> str:
    return f"vbpa_{secrets.token_urlsafe(32)}"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _parse_dt(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _now() -> datetime:
    return datetime.now(UTC)


def _hash_optional(value: Any) -> str | None:
    if not value:
        return None
    return sha256(str(value).encode("utf-8")).hexdigest()
