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
    AdminRequesterVerificationUpdate,
    EvidenceAccessGrantResponse,
    EvidenceAccessRequestResponse,
    ProtectedEvidenceResponse,
    PublicPassportSafeResponse,
    PublicWorkPassportCreateRequest,
    PublicWorkPassportStudentResponse,
    RecruiterPassportViewResponse,
    RecruiterProofSourceResponse,
    RecruiterRequesterProfileResponse,
    RecruiterSkillGroupResponse,
    RecruiterSkillResponse,
)
from app.services.extension_proof_service import ExtensionProofSessionNotFoundError
from app.services.notification_service import NotificationService
from app.services.verification_readiness_service import compute_readiness_report

_PASSPORTS = "public_work_passports"
_REQUESTS = "evidence_access_requests"
_GRANTS = "evidence_access_grants"
_AUDIT_EVENTS = "evidence_access_audit_events"
_PASSPORT_VIEW_EVENTS = "public_passport_view_events"
_REQUESTER_PROFILES = "recruiter_requester_profiles"
_USERS = "users"
_SESSIONS = "extension_proof_sessions"
_SKILL_EVIDENCE = "skill_evidence"
_PROFILES = "student_profiles"
_AI_DOMAIN = "ai_domain_review_results"
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
_ALLOWED_REQUESTER_TYPES = {
    "recruiter",
    "hiring_manager",
    "faculty",
    "mentor",
    "company_reviewer",
    "domain_expert",
    "other",
}
_FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "icloud.com",
    "proton.me",
}
_REPEATED_REQUEST_THRESHOLD = 3


class PublicWorkPassportNotFoundError(LookupError):
    """Passport not found or not public."""


class EvidenceAccessRequestNotFoundError(LookupError):
    """Access request not found for the scoped student."""


class EvidenceAccessGrantNotFoundError(LookupError):
    """Access grant not found for the scoped student."""


class EvidenceAccessDeniedError(PermissionError):
    """Access token is missing, expired, revoked, or otherwise invalid."""


class RecruiterRequesterProfileNotFoundError(LookupError):
    """Requester profile was not found."""


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

    def get_recruiter_passport_view(
        self,
        public_slug: str,
    ) -> RecruiterPassportViewResponse:
        """Return an evidence-enriched, recruiter-safe Work Passport view.

        Aggregates the public passport metadata with final evidence scores,
        grouped skill evidence (with source attribution), and recruiter
        decision helpers (why credible, suggested interview questions).

        Privacy: no media_storage_path, raw transcripts, access tokens,
        or debug metadata are ever included.
        """
        from app.services.final_evidence_evaluator_service import FinalEvidenceEvaluatorService

        passport = self._passport_by_slug(public_slug)
        if not passport or not passport.get("is_public", True):
            raise PublicWorkPassportNotFoundError(public_slug)

        user_id = str(passport["user_id"])
        session_id = str(passport["proof_session_id"])
        session = self._get_session(user_id, session_id)
        evidence = self._gather_evidence(user_id, session_id, session)

        # Run the final evidence evaluator (read-only — does not mutate state).
        try:
            eval_svc = FinalEvidenceEvaluatorService(self._client)
            claimed_skills = list(evidence.get("claimed_skills") or [])
            github = evidence.get("github_analysis") or {}
            github_url = str(github.get("repo_url") or "") or None
            final_eval = eval_svc.evaluate(
                user_id=user_id,
                session_id=session_id,
                claimed_skills=claimed_skills,
                github_url=github_url,
            )
        except Exception:
            final_eval = None

        return _recruiter_view_response(passport, evidence, final_eval)

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
        requester_profile = self._upsert_requester_profile(payload, now)
        requester_identity = _requester_identity_summary(requester_profile)
        row = {
            "id": str(uuid4()),
            "user_id": str(passport["user_id"]),
            "proof_session_id": str(passport["proof_session_id"]),
            "passport_id": str(passport["id"]),
            "requester_profile_id": str(requester_profile["id"]),
            "requester_name": payload.requester_name,
            "requester_email": str(requester_profile["email"]),
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
            actor_email=str(requester_profile["email"]),
            event_summary="Recruiter requested access to protected evidence.",
            metadata={
                **requester_identity,
                "requester_organization": payload.requester_organization,
                "requester_role": payload.requester_role,
                "requested_sections": requested_sections,
            },
        )
        self._write_notification_event(
            user_id=str(passport["user_id"]),
            event_type="access_request_received",
            recipient_email=self._user_email(str(passport["user_id"])),
            title="New evidence access request",
            message=_access_request_message(payload.requester_name, payload.requester_organization),
            category="access_request",
            priority="high",
            action_label="Review request",
            metadata={
                "passport_id": str(passport["id"]),
                "request_id": str(saved["id"]),
                "access_request_id": str(saved["id"]),
                "requester_profile_id": str(requester_profile["id"]),
                "requester_email": str(requester_profile["email"]),
                "organization": payload.requester_organization,
                "requester_identity": requester_identity,
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
        # Generate a new plaintext token only on first approval.
        # Store only the SHA-256 hash — never store the plaintext in the DB.
        if existing:
            plaintext_token: str | None = None  # not re-emitted after first creation
            token_hash = existing.get("access_token_hash") or _hash_token(str(existing.get("access_token") or ""))
        else:
            plaintext_token = _new_token()
            token_hash = _hash_token(plaintext_token)
        grant = {
            "id": existing.get("id") if existing else str(uuid4()),
            "access_request_id": str(request["id"]),
            "user_id": user_id,
            "proof_session_id": str(request["proof_session_id"]),
            "requester_email": str(request["requester_email"]),
            "granted_sections": sections,
            # access_token is kept for legacy back-compat (NULL for new grants)
            "access_token": existing.get("access_token") if existing else None,
            "access_token_hash": token_hash,
            "expires_at": body.expires_at,
            "revoked_at": None,
            "created_at": existing.get("created_at") if existing else now,
            "updated_at": now,
        }
        saved = self._save(_GRANTS, grant)
        self._increment_requester_decision_count(request.get("requester_profile_id"), "approved_access_requests")
        requester_identity = self._requester_identity_for_request(request)
        self._write_audit_event(
            user_id=user_id,
            proof_session_id=str(request["proof_session_id"]),
            passport_id=str(request["passport_id"]),
            access_request_id=str(request["id"]),
            event_type="access_approved",
            actor_type="student",
            actor_user_id=user_id,
            event_summary="Student approved protected evidence access request.",
            metadata={
                **requester_identity,
                "granted_sections": sections,
                "expires_at": body.expires_at.isoformat() if body.expires_at else None,
            },
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
            metadata={
                **requester_identity,
                "granted_sections": sections,
                "expires_at": body.expires_at.isoformat() if body.expires_at else None,
            },
        )
        self._write_notification_event(
            user_id=user_id,
            event_type="access_approved",
            recipient_email=self._user_email(user_id),
            title="Evidence access approved",
            message=f"Access was approved for {request['requester_email']}.",
            category="access_decision",
            priority="normal",
            metadata={
                "passport_id": str(request["passport_id"]),
                "request_id": str(request["id"]),
                "access_request_id": str(request["id"]),
                "access_grant_id": str(saved["id"]),
                "requester_profile_id": request.get("requester_profile_id"),
                "requester_email": str(request["requester_email"]),
                "requester_identity": requester_identity,
                "granted_sections": sections,
                "expires_at": body.expires_at.isoformat() if body.expires_at else None,
            },
        )
        return _grant_response(saved, plaintext_token=plaintext_token)

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
        self._increment_requester_decision_count(request.get("requester_profile_id"), "denied_access_requests")
        requester_identity = self._requester_identity_for_request(request)
        self._write_audit_event(
            user_id=user_id,
            proof_session_id=str(request["proof_session_id"]),
            passport_id=str(request["passport_id"]),
            access_request_id=str(request["id"]),
            event_type="access_denied",
            actor_type="student",
            actor_user_id=user_id,
            event_summary="Student denied protected evidence access request.",
            metadata={**requester_identity, "decision_notes_provided": bool(body.decision_notes)},
        )
        self._write_notification_event(
            user_id=user_id,
            event_type="access_denied",
            recipient_email=self._user_email(user_id),
            title="Evidence access denied",
            message=f"Access was denied for {request['requester_email']}.",
            category="access_decision",
            priority="normal",
            metadata={
                "passport_id": str(request["passport_id"]),
                "request_id": str(request["id"]),
                "access_request_id": str(request["id"]),
                "requester_profile_id": request.get("requester_profile_id"),
                "requester_email": str(request["requester_email"]),
                "requester_identity": requester_identity,
            },
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
            recipient_email=self._user_email(user_id),
            title="Evidence access revoked",
            message=f"Access was revoked for {grant['requester_email']}.",
            category="access_decision",
            priority="normal",
            metadata={
                "passport_id": passport_id,
                "request_id": str(grant["access_request_id"]),
                "access_request_id": str(grant["access_request_id"]),
                "access_grant_id": str(grant["id"]),
                "requester_profile_id": request.get("requester_profile_id") if request else None,
                "requester_email": str(grant["requester_email"]),
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

    def list_access_requesters(self, user_id: str) -> list[RecruiterRequesterProfileResponse]:
        requests = self._rows_for_user(_REQUESTS, user_id)
        profile_ids = _dedupe([
            str(row.get("requester_profile_id"))
            for row in requests
            if row.get("requester_profile_id")
        ])
        profiles = [self._by_id(_REQUESTER_PROFILES, profile_id) for profile_id in profile_ids]
        rows = [profile for profile in profiles if profile]
        rows.sort(key=lambda row: str(row.get("last_seen_at") or ""), reverse=True)
        return [_requester_profile_response(row) for row in rows]

    def admin_list_requester_profiles(self, limit: int = 100, offset: int = 0) -> list[RecruiterRequesterProfileResponse]:
        if isinstance(self._client, dict):
            rows = list(self._client.get(_REQUESTER_PROFILES, {}).values())
            rows.sort(key=lambda row: str(row.get("last_seen_at") or ""), reverse=True)
            return [_requester_profile_response(row) for row in rows[offset:offset + limit]]
        result = (
            self._client.table(_REQUESTER_PROFILES)
            .select("*")
            .order("last_seen_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return [_requester_profile_response(row) for row in (getattr(result, "data", []) or [])]

    def admin_update_requester_verification(
        self,
        profile_id: str,
        payload: AdminRequesterVerificationUpdate,
    ) -> RecruiterRequesterProfileResponse:
        profile = self._by_id(_REQUESTER_PROFILES, profile_id)
        if not profile:
            raise RecruiterRequesterProfileNotFoundError(profile_id)
        profile.update(
            {
                "verification_status": payload.verification_status,
                "notes": payload.notes,
                "updated_at": _now(),
            }
        )
        if payload.domain_verified is not None:
            profile["domain_verified"] = payload.domain_verified
        if payload.email_verified is not None:
            profile["email_verified"] = payload.email_verified
        profile.update(_risk_profile_fields(profile))
        saved = self._save(_REQUESTER_PROFILES, profile)
        return _requester_profile_response(saved)

    def _upsert_requester_profile(self, payload: AccessRequestCreate, now: datetime) -> dict[str, Any]:
        email = _normalize_email(payload.requester_email)
        domain = _email_domain(email)
        existing = self._requester_profile_by_email(email)
        total_requests = int((existing or {}).get("total_access_requests") or 0) + 1
        status = str((existing or {}).get("verification_status") or "unverified")
        row = {
            "id": str((existing or {}).get("id") or uuid4()),
            "email": email,
            "full_name": payload.requester_name,
            "organization_name": payload.requester_organization,
            "organization_domain": domain,
            "requester_role": payload.requester_role,
            "requester_type": _requester_type(payload.requester_role),
            "email_verified": bool((existing or {}).get("email_verified", False)),
            "domain_verified": bool((existing or {}).get("domain_verified", False)),
            "verification_status": status,
            "first_seen_at": (existing or {}).get("first_seen_at") or now,
            "last_seen_at": now,
            "total_access_requests": total_requests,
            "approved_access_requests": int((existing or {}).get("approved_access_requests") or 0),
            "denied_access_requests": int((existing or {}).get("denied_access_requests") or 0),
            "risk_score": 0,
            "risk_flags": [],
            "notes": (existing or {}).get("notes"),
            "created_at": (existing or {}).get("created_at") or now,
            "updated_at": now,
        }
        row.update(_risk_profile_fields(row, request_reason=payload.request_reason or ""))
        return self._save(_REQUESTER_PROFILES, row)

    def _requester_profile_by_email(self, email: str) -> dict[str, Any] | None:
        return self._first_where(_REQUESTER_PROFILES, "email", _normalize_email(email))

    def _increment_requester_decision_count(self, profile_id: Any, field: str) -> None:
        if not profile_id:
            return
        profile = self._by_id(_REQUESTER_PROFILES, str(profile_id))
        if not profile:
            return
        profile[field] = int(profile.get(field) or 0) + 1
        profile["updated_at"] = _now()
        profile.update(_risk_profile_fields(profile))
        self._save(_REQUESTER_PROFILES, profile)

    def _requester_identity_for_request(self, request: dict[str, Any]) -> dict[str, Any]:
        profile_id = request.get("requester_profile_id")
        profile = self._by_id(_REQUESTER_PROFILES, str(profile_id)) if profile_id else None
        return _requester_identity_summary(profile) if profile else {
            "requester_profile_id": None,
            "requester_type": "recruiter",
            "organization_domain": _email_domain(str(request.get("requester_email") or "")),
            "verification_status": "unverified",
            "risk_flags": [],
        }

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
        title: str,
        message: str,
        category: str = "general",
        priority: str = "normal",
        action_label: str | None = None,
        action_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        return NotificationService(self._client).create_notification_event(
            user_id=user_id,
            event_type=event_type,
            recipient_email=recipient_email,
            title=title,
            message=message,
            subject=title,
            body=message,
            category=category,
            priority=priority,
            action_label=action_label,
            action_url=action_url,
            metadata=metadata or {},
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
        """Look up a grant by token.

        For new grants the hash is stored in ``access_token_hash``.
        For legacy grants (pre-migration) the plaintext is in ``access_token``.
        Both lookup paths are supported for backward compatibility.
        """
        token_hash = _hash_token(token)
        row = self._first_where(_GRANTS, "access_token_hash", token_hash)
        if row:
            return row
        # Legacy fallback: rows back-filled or created before migration 037
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

    def _rows_for_user(self, table: str, user_id: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            return [
                row for row in self._client.get(table, {}).values()
                if str(row.get("user_id")) == user_id
            ]
        result = self._client.table(table).select("*").eq("user_id", user_id).execute()
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
        # ai_reviewed_status comes from ai_domain_review_results (verification_review_requests does not exist)
        ai_reviewed_status=ai_domain.get("ai_domain_review_status"),
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


_SOURCE_LABEL_MAP: dict[str, str] = {
    "website_workflow":      "Website Workflow",
    "dom_visible_evidence":  "DOM Evidence",
    "video_keyframes":       "Video Keyframes",
    "ocr":                   "OCR",
    "qwen_visual_reasoning": "AI Visual Analysis",
    "github":                "GitHub",
    "live_website_check":    "Live Website",
    "project_defense":       "Project Defense",
    "uploaded_documents":    "Documents",
    "linkedin_profile":      "LinkedIn",
    "certificate":           "Certificate",
}


def _recruiter_view_response(
    passport: dict[str, Any],
    evidence: dict[str, Any],
    final_eval: Any | None,
) -> RecruiterPassportViewResponse:
    """Build a recruiter-safe, evidence-enriched view of a Work Passport.

    Combines public passport metadata, readiness report, and (when available)
    the final evidence evaluator output into a single recruiter-first payload.
    Never exposes private fields.
    """
    readiness = evidence.get("readiness_report")
    profile = evidence.get("student_profile") or {}

    # Scores and confidence
    overall_score = 0
    evidence_confidence: str = "low"
    if final_eval is not None:
        overall_score = getattr(final_eval, "final_score", 0)
        evidence_confidence = getattr(final_eval, "confidence", "low")
    elif readiness is not None:
        overall_score = getattr(readiness, "readiness_score", 0) or 0

    # Skills from readiness (always available)
    verified_skills = list(getattr(readiness, "strongly_supported_skills", []) if readiness else [])
    partially_verified = list(getattr(readiness, "partially_supported_skills", []) if readiness else [])
    needs_review = [_clean_need_more(s) for s in (getattr(readiness, "needs_more_evidence", []) if readiness else [])]

    # Grouped skill evidence from final evaluator
    skill_groups: list[RecruiterSkillGroupResponse] = []
    if final_eval is not None:
        for group in (getattr(final_eval, "grouped_skill_evidence", []) or []):
            skills_out = [
                RecruiterSkillResponse(
                    skill=str(sk.skill),
                    confidence=sk.confidence,
                    status_label=str(sk.status_label or ""),
                    source_labels=list(sk.source_labels or []),
                )
                for sk in (group.skills or [])
            ]
            skill_groups.append(RecruiterSkillGroupResponse(
                group_name=str(group.group_name),
                category=str(group.category),
                confidence=group.confidence,
                evidence_count=group.evidence_count,
                source_labels=list(group.source_labels or []),
                skills=skills_out,
            ))

    # Proof sources from final evaluator (exclude private/admin sources)
    proof_sources: list[RecruiterProofSourceResponse] = []
    if final_eval is not None:
        _shown_keys = {
            "website_workflow", "video_keyframes", "ocr", "qwen_visual_reasoning",
            "github", "live_website_check", "project_defense", "uploaded_documents",
        }
        for src in (getattr(final_eval, "evidence_source_breakdown", []) or []):
            src_key = src.get("key") if isinstance(src, dict) else getattr(src, "key", "")
            if src_key not in _shown_keys:
                continue
            src_status = src.get("status") if isinstance(src, dict) else getattr(src, "status", "not_run")
            src_score = src.get("score") if isinstance(src, dict) else getattr(src, "score", 0)
            proof_sources.append(RecruiterProofSourceResponse(
                key=str(src_key),
                label=_SOURCE_LABEL_MAP.get(str(src_key), str(src_key).replace("_", " ").title()),
                status=str(src_status),
                score=int(src_score or 0),
                is_run=str(src_status) not in ("not_run", "not_available"),
            ))

    # Recruiter decision helpers
    why_credible = _why_credible(final_eval, verified_skills, evidence)
    strongest = verified_skills[:5] or partially_verified[:5]
    areas_review = needs_review[:5] or [s for s in partially_verified if s not in verified_skills][:5]
    interview_questions = _suggested_interview_questions(
        verified_skills=verified_skills,
        partially_verified=partially_verified,
        needs_review=needs_review,
        final_eval=final_eval,
        evidence=evidence,
    )

    # Project type from final evaluator
    project_type: str | None = None
    if final_eval is not None:
        cap = getattr(final_eval, "detected_capability", None)
        if cap:
            project_type = getattr(cap, "role_title", None)

    return RecruiterPassportViewResponse(
        public_slug=str(passport["public_slug"]),
        student_display_name=_public_display_name(profile),
        field=passport.get("field") or _field(evidence),
        public_title=passport.get("public_title"),
        public_summary=passport.get("public_summary"),
        overall_score=overall_score,
        evidence_confidence=evidence_confidence,  # type: ignore[arg-type]
        verification_status=_verification_status(evidence),
        readiness_level=getattr(readiness, "readiness_level", None) if readiness else None,
        skill_groups=skill_groups,
        verified_skills=verified_skills,
        partially_verified_skills=partially_verified,
        skills_needing_review=needs_review,
        proof_sources=proof_sources,
        why_credible=why_credible,
        strongest_skills=strongest,
        areas_needing_review=areas_review,
        suggested_interview_questions=interview_questions,
        public_project_links=_public_links(evidence),
        project_type=project_type,
        access_request_available=True,
        has_protected_evidence=True,
        disclosure_note=_PUBLIC_DISCLOSURE,
    )


def _why_credible(
    final_eval: Any | None,
    verified_skills: list[str],
    evidence: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if final_eval is not None:
        cap = getattr(final_eval, "detected_capability", None)
        if cap:
            reasons.extend(list(getattr(cap, "why_detected", []) or [])[:3])
    if not reasons:
        if verified_skills:
            reasons.append(
                f"AI evidence analysis confirms strong support for: {', '.join(verified_skills[:3])}."
            )
        if evidence.get("github_analysis"):
            reasons.append("GitHub repository evidence was analyzed and supports claimed skills.")
        if evidence.get("project_defense_analysis"):
            reasons.append("Project defense transcript was analyzed for ownership and explanation clarity.")
        if evidence.get("workflow_analysis"):
            reasons.append("Website workflow recording was captured and analyzed for demonstrated skills.")
    return reasons[:5]


def _verification_status(evidence: dict[str, Any]) -> str | None:
    ai_domain = evidence.get("ai_domain_review") or {}
    return ai_domain.get("ai_domain_review_status") or None


def _suggested_interview_questions(
    verified_skills: list[str],
    partially_verified: list[str],
    needs_review: list[str],
    final_eval: Any | None,
    evidence: dict[str, Any],
) -> list[str]:
    questions: list[str] = []

    # Skills with only partial evidence → probe depth
    for skill in (partially_verified or [])[:2]:
        questions.append(
            f"Tell me about a specific challenge you faced while working with {skill}."
        )

    # Skills needing more evidence → verify ownership
    for skill in (needs_review or [])[:2]:
        questions.append(
            f"Walk me through how you used {skill} in your project — what problem did it solve?"
        )

    # Detected capability / project type → role fit
    if final_eval is not None:
        cap = getattr(final_eval, "detected_capability", None)
        if cap:
            role = getattr(cap, "role_title", "")
            if role:
                questions.append(
                    f"Based on your work, how would you approach a {role} role differently than what you've done so far?"
                )

    # Defense / transcript evidence → ownership
    defense = evidence.get("project_defense_analysis") or {}
    skills_explained = defense.get("skills_explained_well") or []
    if skills_explained:
        s = skills_explained[0]
        questions.append(
            f"You explained {s} in your project defense — how would you improve that aspect if starting over?"
        )

    # Generic ownership question if list is short
    if len(questions) < 3 and verified_skills:
        questions.append(
            f"What was the most technically difficult part of building your {verified_skills[0]} project?"
        )

    return questions[:5]


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
        requester_profile_id=str(row["requester_profile_id"]) if row.get("requester_profile_id") else None,
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


def _grant_response(row: dict[str, Any], *, plaintext_token: str | None = None) -> EvidenceAccessGrantResponse:
    """Build a grant response.

    *plaintext_token* is set only when a brand-new grant is created
    (``approve_request`` first call).  On re-approvals or revocations the
    plaintext is no longer available and ``access_token`` is returned as
    ``None`` so the token is never re-exposed after initial issuance.
    """
    return EvidenceAccessGrantResponse(
        id=str(row["id"]),
        access_request_id=str(row["access_request_id"]),
        user_id=str(row["user_id"]),
        proof_session_id=str(row["proof_session_id"]),
        requester_email=str(row["requester_email"]),
        granted_sections=list(row.get("granted_sections") or []),
        access_token=plaintext_token,  # None on re-reads/revoke — see schema docs
        expires_at=row.get("expires_at"),
        revoked_at=row.get("revoked_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _requester_profile_response(row: dict[str, Any]) -> RecruiterRequesterProfileResponse:
    return RecruiterRequesterProfileResponse(
        requester_profile_id=str(row["id"]),
        email=str(row["email"]),
        full_name=row.get("full_name"),
        organization_name=row.get("organization_name"),
        organization_domain=row.get("organization_domain"),
        requester_role=row.get("requester_role"),
        requester_type=row.get("requester_type") or "recruiter",
        verification_status=row.get("verification_status") or "unverified",
        email_verified=bool(row.get("email_verified", False)),
        domain_verified=bool(row.get("domain_verified", False)),
        total_access_requests=int(row.get("total_access_requests") or 0),
        approved_access_requests=int(row.get("approved_access_requests") or 0),
        denied_access_requests=int(row.get("denied_access_requests") or 0),
        risk_score=int(row.get("risk_score") or 0),
        risk_flags=list(row.get("risk_flags") or []),
        last_seen_at=row["last_seen_at"],
    )


def _requester_identity_summary(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {
            "requester_profile_id": None,
            "requester_type": "recruiter",
            "organization_domain": None,
            "verification_status": "unverified",
            "risk_flags": [],
        }
    return {
        "requester_profile_id": str(row["id"]),
        "requester_type": row.get("requester_type") or "recruiter",
        "organization_domain": row.get("organization_domain"),
        "organization_domain_matches_name": _organization_matches_domain(
            row.get("organization_name"),
            row.get("organization_domain"),
        ),
        "verification_status": row.get("verification_status") or "unverified",
        "risk_flags": list(row.get("risk_flags") or []),
    }


def _risk_profile_fields(row: dict[str, Any], request_reason: str | None = None) -> dict[str, Any]:
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
    if request_reason is not None and not request_reason:
        flags.add("missing_reason")
    if int(row.get("total_access_requests") or 0) > _REPEATED_REQUEST_THRESHOLD:
        flags.add("repeated_requests")
    else:
        flags.discard("repeated_requests")
    if row.get("verification_status") == "blocked":
        flags.add("blocked_domain_future_placeholder")
    else:
        flags.discard("blocked_domain_future_placeholder")

    score = 0
    if "free_email_domain" in flags:
        score += 10
    if "missing_organization" in flags:
        score += 10
    if "missing_reason" in flags:
        score += 10
    if "repeated_requests" in flags:
        score += 10
    if row.get("verification_status") == "blocked":
        score += 100
    return {"risk_flags": sorted(flags), "risk_score": score}


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _email_domain(email: str) -> str | None:
    cleaned = _normalize_email(email)
    if "@" not in cleaned:
        return None
    domain = cleaned.rsplit("@", 1)[-1].strip(".")
    return domain or None


def _requester_type(role: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", (role or "").strip().lower()).strip("_")
    return normalized if normalized in _ALLOWED_REQUESTER_TYPES else "recruiter"


def _access_request_message(requester_name: str, organization_name: str | None) -> str:
    organization = organization_name or "an organization not listed"
    return f"{requester_name} from {organization} requested access to your Work Passport evidence."


def _organization_matches_domain(organization_name: Any, domain: Any) -> bool:
    if not organization_name or not domain:
        return False
    if str(domain).lower() in _FREE_EMAIL_DOMAINS:
        return False
    org_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", str(organization_name).lower())
        if len(token) >= 3
    }
    domain_root = str(domain).lower().split(".", 1)[0]
    return bool(domain_root and domain_root in org_tokens)


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


def _hash_token(plaintext: str) -> str:
    """Return the SHA-256 hex digest of a bearer token for safe DB storage."""
    return sha256(plaintext.encode("utf-8")).hexdigest()


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
