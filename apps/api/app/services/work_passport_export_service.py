"""Work Passport export payload generation and export record service."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import uuid4

from app.core.serialization import make_json_safe
from app.services.extension_proof_service import ExtensionProofSessionNotFoundError
from app.services.public_work_passport_service import (
    EvidenceAccessDeniedError,
    PublicWorkPassportNotFoundError,
)
from app.services.skill_evidence_timeline_service import SkillEvidenceTimelineService
from app.services.work_passport_analytics_service import WorkPassportAnalyticsService
from app.services.work_passport_status_service import WorkPassportStatusService

_EXPORTS = "work_passport_exports"
_PASSPORTS = "public_work_passports"
_SESSIONS = "extension_proof_sessions"
_SKILL_EVIDENCE = "skill_evidence"
_USERS = "users"
_PROFILES = "student_profiles"
_GRANTS = "evidence_access_grants"
_REQUESTS = "evidence_access_requests"
_AI_DOMAIN = "ai_domain_review_results"
_VERSIONS = "proof_evidence_versions"
_WORKFLOW = "workflow_analysis_results"
_GITHUB = "extension_proof_github_analysis"
_LIVE = "live_website_check_results"
_PRIVACY = "workflow_privacy_scan_results"
_DEFENSE = "project_defense_analysis_results"

_DISCLAIMER = (
    "This Work Passport uses VeriBridge AI evidence review. Human/faculty/company review "
    "is only shown when explicitly completed."
)


class WorkPassportExportService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def build_student_export_payload(self, user_id: str, proof_session_id: str) -> dict[str, Any]:
        session = self._session_for_user(user_id, proof_session_id)
        passport = self._passport_for_session(user_id, proof_session_id)
        status = WorkPassportStatusService(self._client).get_work_passport_status(user_id, proof_session_id)
        timeline = SkillEvidenceTimelineService(self._client).get_skill_evidence_timeline(user_id, proof_session_id)
        analytics = WorkPassportAnalyticsService(self._client).get_student_passport_analytics(user_id, proof_session_id)
        active_version = self._active_version(user_id, proof_session_id)
        public_slug = str(passport.get("public_slug")) if passport and passport.get("is_public", True) else None
        payload = self._compose_payload(
            export_type="student",
            export_format="json",
            user_id=user_id,
            proof_session_id=proof_session_id,
            passport=passport,
            session=session,
            status=status,
            timeline=timeline,
            analytics=analytics,
            active_version=active_version,
            public_slug=public_slug,
            public_safe=True,
            protected_sections=[],
            export_context="student",
        )
        self.create_export_record(
            user_id=user_id,
            proof_session_id=proof_session_id,
            passport_id=str(passport["id"]) if passport else None,
            export_type="student",
            export_payload=payload,
            generated_by_type="student",
            generated_by_email=self._user_email(user_id),
            public_slug=public_slug,
        )
        return payload

    def build_public_export_payload(self, public_slug: str) -> dict[str, Any]:
        passport = self._public_passport(public_slug)
        user_id = str(passport["user_id"])
        proof_session_id = str(passport["proof_session_id"])
        session = self._session_for_user(user_id, proof_session_id)
        status = WorkPassportStatusService(self._client).get_public_passport_status(public_slug)
        timeline = SkillEvidenceTimelineService(self._client).get_public_skill_evidence_timeline(public_slug)
        active_version = self._active_version(user_id, proof_session_id)
        payload = self._compose_payload(
            export_type="public",
            export_format="json",
            user_id=user_id,
            proof_session_id=proof_session_id,
            passport=passport,
            session=session,
            status=status,
            timeline=timeline,
            analytics=None,
            active_version=active_version,
            public_slug=public_slug,
            public_safe=True,
            protected_sections=[],
            export_context="public",
        )
        self.create_export_record(
            user_id=user_id,
            proof_session_id=proof_session_id,
            passport_id=str(passport["id"]),
            export_type="public",
            export_payload=payload,
            generated_by_type="public",
            generated_by_email=self._user_email(user_id),
            public_slug=public_slug,
        )
        return payload

    def build_protected_export_payload(self, access_token: str) -> dict[str, Any]:
        grant = self._grant_by_token(access_token)
        if not grant or grant.get("revoked_at"):
            raise EvidenceAccessDeniedError("Access token is invalid or revoked.")
        expires_at = _parse_dt(grant.get("expires_at"))
        if expires_at and expires_at <= _now():
            raise EvidenceAccessDeniedError("Access token is expired.")
        passport_id = grant.get("passport_id")
        if not passport_id and grant.get("access_request_id"):
            request = self._first_where(_REQUESTS, "id", str(grant["access_request_id"]))
            passport_id = (request or {}).get("passport_id")
        passport = self._passport_by_id(str(passport_id)) if passport_id else None
        if not passport:
            raise PublicWorkPassportNotFoundError(str(passport_id or grant.get("access_request_id")))
        user_id = str(grant["user_id"])
        proof_session_id = str(grant["proof_session_id"])
        session = self._session_for_user(user_id, proof_session_id)
        timeline = SkillEvidenceTimelineService(self._client).get_protected_skill_evidence_timeline(access_token)
        status = WorkPassportStatusService(self._client).get_public_passport_status(str(passport["public_slug"]))
        active_version = self._active_version(user_id, proof_session_id)
        protected_sections = [str(section) for section in list(grant.get("granted_sections") or []) if str(section).strip()]
        payload = self._compose_payload(
            export_type="protected_recruiter",
            export_format="json",
            user_id=user_id,
            proof_session_id=proof_session_id,
            passport=passport,
            session=session,
            status=status,
            timeline=timeline,
            analytics=None,
            active_version=active_version,
            public_slug=str(passport.get("public_slug") or ""),
            public_safe=False,
            protected_sections=protected_sections,
            export_context="protected",
        )
        self.create_export_record(
            user_id=user_id,
            proof_session_id=proof_session_id,
            passport_id=str(passport["id"]),
            access_grant_id=str(grant["id"]),
            export_type="protected_recruiter",
            export_payload=payload,
            generated_by_type="recruiter",
            generated_by_email=str(grant.get("requester_email") or ""),
            public_slug=str(passport.get("public_slug") or ""),
            access_token=access_token,
            expires_at=grant.get("expires_at"),
        )
        return payload

    def create_export_record(
        self,
        *,
        user_id: str,
        proof_session_id: str,
        export_type: str,
        export_payload: dict[str, Any],
        passport_id: str | None = None,
        access_grant_id: str | None = None,
        public_slug: str | None = None,
        access_token: str | None = None,
        generated_by_type: str = "student",
        generated_by_email: str | None = None,
        expires_at: datetime | str | None = None,
        export_format: str = "json",
        status: str = "generated",
        file_storage_path: str | None = None,
    ) -> dict[str, Any]:
        row = {
            "id": str(uuid4()),
            "user_id": user_id,
            "proof_session_id": proof_session_id,
            "passport_id": passport_id,
            "access_grant_id": access_grant_id,
            "export_type": export_type,
            "export_format": export_format,
            "status": status,
            "public_slug": public_slug,
            "access_token_hash": _hash_access_token(access_token) if access_token else None,
            "export_payload": export_payload,
            "file_storage_path": file_storage_path,
            "generated_by_type": generated_by_type,
            "generated_by_email": generated_by_email,
            "created_at": _now(),
            "expires_at": expires_at,
        }
        return self._insert(row)

    def get_latest_export_record(self, user_id: str, proof_session_id: str) -> dict[str, Any] | None:
        rows = [
            row for row in self._rows_for_user(_EXPORTS, user_id)
            if str(row.get("proof_session_id")) == proof_session_id
        ]
        rows.sort(key=lambda row: _parse_dt(row.get("created_at")) or datetime.min.replace(tzinfo=UTC), reverse=True)
        return rows[0] if rows else None

    def _compose_payload(
        self,
        *,
        export_type: str,
        export_format: str,
        user_id: str,
        proof_session_id: str,
        passport: dict[str, Any] | None,
        session: dict[str, Any],
        status: Any,
        timeline: Any,
        analytics: Any,
        active_version: dict[str, Any] | None,
        public_slug: str | None,
        public_safe: bool,
        protected_sections: list[str],
        export_context: str,
    ) -> dict[str, Any]:
        status_payload = status.model_dump(mode="json") if hasattr(status, "model_dump") else dict(status or {})
        timeline_payload = timeline.model_dump(mode="json") if hasattr(timeline, "model_dump") else dict(timeline or {})
        analytics_payload = analytics.model_dump(mode="json") if analytics and hasattr(analytics, "model_dump") else None
        skills = [_skill_summary(skill) for skill in list(timeline_payload.get("skills") or [])]
        evidence_summary = _evidence_summary(skills, analytics_payload, export_context)
        profile = self._profile_summary(user_id, passport, session)
        ai_domain = self._ai_domain_summary(status_payload, user_id, proof_session_id, passport)
        versions = self._version_summary(active_version, user_id, proof_session_id)
        limitations = _export_limitations(export_context, passport, protected_sections, status_payload, timeline_payload)
        export_metadata = {
            "export_type": export_type,
            "export_format": export_format,
            "generated_at": _now().isoformat(),
            "passport_slug": public_slug,
            "proof_session_id": proof_session_id,
            "limitations": limitations,
        }
        return {
            "export_metadata": export_metadata,
            "profile": profile,
            "passport_status": _passport_status_summary(status_payload, proof_session_id, public_slug),
            "ai_domain_review": ai_domain,
            "skills": skills,
            "evidence_summary": evidence_summary,
            "versions": versions,
            "access_and_privacy": {
                "privacy_status": status_payload.get("privacy_status"),
                "public_safe": public_safe,
                "protected_sections_available": protected_sections,
            },
            "verification_disclaimer": _DISCLAIMER,
        }

    def _public_passport(self, public_slug: str) -> dict[str, Any]:
        passport = self._first_where(_PASSPORTS, "public_slug", public_slug)
        if not passport or not passport.get("is_public", True):
            raise PublicWorkPassportNotFoundError(public_slug)
        return passport

    def _passport_for_session(self, user_id: str, proof_session_id: str) -> dict[str, Any] | None:
        rows = self._rows_by_session(_PASSPORTS, user_id, proof_session_id)
        return rows[0] if rows else None

    def _passport_by_id(self, passport_id: str) -> dict[str, Any] | None:
        return self._by_id(_PASSPORTS, passport_id)

    def _session_for_user(self, user_id: str, proof_session_id: str) -> dict[str, Any]:
        row = self._by_id(_SESSIONS, proof_session_id)
        if not row or str(row.get("user_id")) != user_id:
            raise ExtensionProofSessionNotFoundError(proof_session_id)
        return row

    def _grant_by_token(self, token: str) -> dict[str, Any] | None:
        return self._first_where(_GRANTS, "access_token", token)

    def _active_version(self, user_id: str, proof_session_id: str) -> dict[str, Any] | None:
        versions = self._rows_by_session(_VERSIONS, user_id, proof_session_id)
        active = [row for row in versions if row.get("is_active")]
        if active:
            active.sort(key=lambda row: int(row.get("version_number") or 0), reverse=True)
            return active[0]
        versions.sort(key=lambda row: int(row.get("version_number") or 0), reverse=True)
        return versions[0] if versions else None

    def _ai_domain_summary(
        self,
        status_payload: dict[str, Any],
        user_id: str,
        proof_session_id: str,
        passport: dict[str, Any] | None,
    ) -> dict[str, Any]:
        row = self._row_by_session(_AI_DOMAIN, user_id, proof_session_id)
        confidence = None
        summary = None
        limitations = None
        if row:
            confidence = row.get("confidence_level")
            summary = row.get("recruiter_summary") or row.get("summary")
            limitations = row.get("limitations")
        return {
            "reviewer_name": status_payload.get("ai_domain_reviewer_name") or (row or {}).get("reviewer_name"),
            "status": status_payload.get("ai_domain_review_status") or (row or {}).get("ai_domain_review_status"),
            "score": status_payload.get("ai_domain_review_score") or _first_int(row or {}, ["domain_review_score", "overall_score"]) or 0,
            "confidence": confidence,
            "summary": summary or status_payload.get("recruiter_safe_summary"),
            "limitations": limitations or (
                "High-level summary only. Sensitive transcript details and private media fields are omitted."
                if passport
                else "No AI Domain Review has been completed yet."
            ),
        }

    def _version_summary(self, active_version: dict[str, Any] | None, user_id: str, proof_session_id: str) -> dict[str, Any]:
        latest = active_version
        if latest is None:
            latest = self._active_version(user_id, proof_session_id)
        return {
            "active_version_number": int(latest.get("version_number") or 0) if latest else None,
            "latest_change_summary": latest.get("change_summary") if latest else None,
        }

    def _profile_summary(self, user_id: str, passport: dict[str, Any] | None, session: dict[str, Any]) -> dict[str, Any]:
        profile = self._student_profile(user_id) or {}
        field = (passport or {}).get("field") or profile.get("major") or session.get("field")
        display_name = profile.get("full_name") or "Student"
        headline = (passport or {}).get("public_title") or f"{field or 'Work Passport'} report"
        return {
            "display_name": display_name,
            "field": field,
            "headline": headline,
            "public_links": _public_links(passport, session),
        }

    def _student_profile(self, user_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            for row in self._client.get(_PROFILES, {}).values():
                if str(row.get("user_id")) == user_id:
                    return row
            return None
        result = self._client.table(_PROFILES).select("*").eq("user_id", user_id).maybe_single().execute()
        return getattr(result, "data", None) if result is not None else None

    def _user_email(self, user_id: str) -> str | None:
        if isinstance(self._client, dict):
            row = self._client.get(_USERS, {}).get(user_id)
            if row and row.get("email"):
                return str(row["email"])
            return None
        result = self._client.table(_USERS).select("email").eq("id", user_id).maybe_single().execute()
        data = getattr(result, "data", None) if result is not None else None
        return str((data or {}).get("email")) if data and data.get("email") else None

    def _rows_by_session(self, table: str, user_id: str, proof_session_id: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            return [
                row for row in self._client.get(table, {}).values()
                if str(row.get("user_id")) == user_id and str(row.get("proof_session_id")) == proof_session_id
            ]
        result = self._client.table(table).select("*").eq("user_id", user_id).eq("proof_session_id", proof_session_id).execute()
        return getattr(result, "data", []) or []

    def _rows_for_user(self, table: str, user_id: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            return [row for row in self._client.get(table, {}).values() if str(row.get("user_id")) == user_id]
        result = self._client.table(table).select("*").eq("user_id", user_id).execute()
        return getattr(result, "data", []) or []

    def _row_by_session(self, table: str, user_id: str, proof_session_id: str) -> dict[str, Any] | None:
        rows = self._rows_by_session(table, user_id, proof_session_id)
        rows.sort(key=lambda row: str(row.get("created_at") or row.get("updated_at") or row.get("submitted_at") or ""), reverse=True)
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

    def _by_id(self, table: str, row_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            return self._client.get(table, {}).get(row_id)
        result = self._client.table(table).select("*").eq("id", row_id).limit(1).execute()
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _insert(self, row: dict[str, Any]) -> dict[str, Any]:
        row = make_json_safe(row)
        if isinstance(self._client, dict):
            self._client.setdefault(_EXPORTS, {})[str(row["id"])] = row
            return row
        result = self._client.table(_EXPORTS).insert(row).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError("work_passport_exports insert returned no data.")
        return rows[0]


def _skill_summary(skill: dict[str, Any]) -> dict[str, Any]:
    evidence_items = list(skill.get("evidence_items") or [])
    summary = None
    if evidence_items:
        first = evidence_items[0]
        if isinstance(first, dict):
            summary = first.get("summary")
    if summary is None:
        gaps = skill.get("gaps") or []
        summary = gaps[0] if gaps else "Skill evidence summary available."
    return {
        "skill_name": skill.get("skill_name"),
        "normalized_skill_name": skill.get("normalized_skill_name"),
        "support_level": skill.get("support_level"),
        "confidence_score": skill.get("confidence_score"),
        "evidence_count": skill.get("evidence_count"),
        "evidence_sources": list(skill.get("evidence_sources") or []),
        "public_safe": skill.get("public_safe", True),
        "recruiter_visible": skill.get("recruiter_visible", False),
        "gaps": list(skill.get("gaps") or []),
        "recommended_next_steps": list(skill.get("recommended_next_steps") or []),
        "last_updated_at": skill.get("last_updated_at"),
        "summary": summary,
    }


def _evidence_summary(
    skills: list[dict[str, Any]],
    analytics: dict[str, Any] | None,
    export_context: str,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    ordered = sorted(skills, key=lambda row: (-int(row.get("confidence_score") or 0), str(row.get("skill_name") or "")))
    for skill in ordered[:3]:
        summaries.append(
            {
                "type": "skill",
                "label": skill.get("skill_name"),
                "summary": skill.get("summary") or "Skill evidence summary available.",
                "support_level": skill.get("support_level"),
                "confidence_score": skill.get("confidence_score"),
                "source_labels": list(skill.get("evidence_sources") or []),
            }
        )
    if export_context == "student" and analytics:
        summaries.append(
            {
                "type": "analytics",
                "label": "Passport engagement",
                "summary": (
                    f"{analytics.get('total_public_views', 0)} public views, "
                    f"{analytics.get('total_access_requests', 0)} access requests, "
                    f"{analytics.get('protected_evidence_views', 0)} protected evidence views."
                ),
                "source_labels": ["analytics"],
            }
        )
    return summaries


def _passport_status_summary(
    status_payload: dict[str, Any],
    proof_session_id: str,
    public_slug: str | None,
) -> dict[str, Any]:
    summary = {
        "overall_status": status_payload.get("overall_status"),
        "status_label": status_payload.get("status_label"),
        "readiness_score": status_payload.get("readiness_score"),
        "readiness_level": status_payload.get("readiness_level"),
        "ai_review_status": status_payload.get("ai_review_status"),
        "ai_domain_review_status": status_payload.get("ai_domain_review_status"),
        "ai_domain_reviewer_name": status_payload.get("ai_domain_reviewer_name"),
        "ai_domain_review_score": status_payload.get("ai_domain_review_score"),
        "project_defense_status": status_payload.get("project_defense_status"),
        "project_defense_score": status_payload.get("project_defense_score"),
        "privacy_status": status_payload.get("privacy_status"),
        "public_passport_status": status_payload.get("public_passport_status"),
        "public_slug": public_slug or status_payload.get("public_slug"),
        "active_version_number": status_payload.get("active_version_number"),
        "active_version_id": status_payload.get("active_version_id"),
        "skill_evidence_summary": _skill_evidence_summary_from_status(status_payload),
        "proof_session_id": proof_session_id,
    }
    return summary


def _skill_evidence_summary_from_status(status_payload: dict[str, Any]) -> dict[str, int] | None:
    summary = status_payload.get("skill_evidence_summary")
    if isinstance(summary, dict):
        return {
            "strong_skill_count": int(summary.get("strong_skill_count") or 0),
            "partial_skill_count": int(summary.get("partial_skill_count") or 0),
            "missing_skill_count": int(summary.get("missing_skill_count") or 0),
        }
    return None


def _export_limitations(
    export_context: str,
    passport: dict[str, Any] | None,
    protected_sections: list[str],
    status_payload: dict[str, Any],
    timeline_payload: dict[str, Any],
) -> list[str]:
    limitations = [
        "Sensitive transcript details and storage paths are omitted.",
        "Human/faculty/company review is only shown when explicitly completed.",
    ]
    if export_context == "protected":
        limitations.append("Protected evidence is limited to approved grant sections.")
        limitations.append("Sections not included in the grant are omitted from the export.")
    if not passport or not passport.get("is_public", True):
        limitations.append("A public share slug is not available yet.")
    if not timeline_payload.get("skills"):
        limitations.append("Skill evidence timeline is not available yet.")
    if not status_payload.get("ai_domain_review_status"):
        limitations.append("AI Domain Review has not been completed yet.")
    if protected_sections:
        limitations.append("Protected sections were restricted to the approved recruiter grant.")
    return list(dict.fromkeys(limitations))


def _public_links(passport: dict[str, Any] | None, session: dict[str, Any]) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    if passport and passport.get("is_public", True) and passport.get("public_slug"):
        slug = str(passport["public_slug"])
        links.append({"label": "Public passport", "path": f"/public/passports/{slug}"})
        links.append({"label": "Skill evidence timeline", "path": f"/public/passports/{slug}/skill-evidence-timeline"})
    website_url = str(session.get("website_url") or "").strip()
    if website_url:
        links.append({"label": "Live project", "url": website_url})
    github_url = str(session.get("github_url") or "").strip()
    if github_url:
        links.append({"label": "GitHub", "url": github_url})
    return links


def _hash_access_token(access_token: str) -> str:
    return sha256(access_token.encode("utf-8")).hexdigest()


def _first_int(row: dict[str, Any], keys: list[str]) -> int | None:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _parse_dt(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _now() -> datetime:
    return datetime.now(UTC)
