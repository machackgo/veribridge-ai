"""Recruiter candidate comparison service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.serialization import make_json_safe
from app.schemas.recruiter_candidate_comparison import (
    RecruiterCandidateComparisonCreate,
    RecruiterCandidateComparisonResponse,
    RecruiterCandidateComparisonRoleRequirements,
    RecruiterCandidateComparisonSnapshot,
    RecruiterCandidateSnapshot,
)
from app.services.skill_evidence_timeline_service import SkillEvidenceTimelineService
from app.services.work_passport_status_service import WorkPassportStatusService

_COMPARISONS = "recruiter_candidate_comparisons"
_SAVED = "recruiter_saved_passports"
_PASSPORTS = "public_work_passports"
_REQUESTER_PROFILES = "recruiter_requester_profiles"
_AUDIT_EVENTS = "evidence_access_audit_events"
_REQUESTS = "evidence_access_requests"
_GRANTS = "evidence_access_grants"
_USERS = "users"
_PROFILES = "student_profiles"
_AI_DOMAIN = "ai_domain_review_results"


class RecruiterCandidateComparisonNotFoundError(LookupError):
    """Candidate comparison not found for the scoped requester."""


class RecruiterCandidateComparisonService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def create_candidate_comparison(
        self,
        payload: RecruiterCandidateComparisonCreate,
    ) -> RecruiterCandidateComparisonResponse:
        requester_email = _normalize_email(payload.requester_email)
        profile = self._upsert_requester_profile(requester_email)
        candidate_ids = _normalize_id_list(payload.saved_passport_ids)
        snapshot = self.build_candidate_comparison_snapshot(
            requester_email=requester_email,
            role_requirements=payload.role_requirements,
            saved_passport_ids=candidate_ids,
            comparison_name=payload.comparison_name,
            role_title=payload.role_title,
            requester_profile=profile,
        )
        row = {
            "id": str(uuid4()),
            "requester_profile_id": str(profile["id"]),
            "requester_email": requester_email,
            "comparison_name": payload.comparison_name,
            "role_title": payload.role_title,
            "role_requirements": _role_requirements_dict(payload.role_requirements),
            "candidate_passport_ids": [str(candidate["passport_id"]) for candidate in snapshot.get("candidates", [])],
            "comparison_snapshot": snapshot,
            "status": "generated",
            "created_at": _now(),
            "updated_at": _now(),
        }
        saved = self._insert(_COMPARISONS, row)
        self._write_audit_event(saved, "candidate_comparison_created")
        return self._response(saved)

    def build_candidate_comparison_snapshot(
        self,
        *,
        requester_email: str,
        role_requirements: RecruiterCandidateComparisonRoleRequirements | dict[str, Any] | None,
        saved_passport_ids: list[str],
        comparison_name: str | None = None,
        role_title: str | None = None,
        requester_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        email = _normalize_email(requester_email)
        profile = requester_profile or self._upsert_requester_profile(email)
        requirements = _role_requirements_dict(role_requirements)
        requested_ids = _normalize_id_list(saved_passport_ids)
        saved_rows = self._saved_rows_for_requester(str(profile["id"]), email)
        saved_rows = [row for row in saved_rows if str(row.get("id")) in requested_ids] if requested_ids else saved_rows
        if requested_ids and not saved_rows:
            raise RecruiterCandidateComparisonNotFoundError("No saved passports matched the requested comparison.")
        candidates = []
        for saved_row in saved_rows:
            candidate = self._candidate_snapshot(saved_row, requirements)
            if candidate is not None:
                candidates.append(candidate)
        candidates.sort(key=lambda row: (-int(row.candidate_match_score or 0), str(row.student_display_name or row.public_slug or "")))
        return RecruiterCandidateComparisonSnapshot(
            comparison_name=comparison_name,
            role_title=role_title,
            role_requirements=requirements,
            generated_at=_now(),
            candidate_count=len(candidates),
            candidates=candidates,
        ).model_dump(mode="json")

    def compare_saved_passports(
        self,
        *,
        requester_email: str,
        saved_passport_ids: list[str],
        role_requirements: RecruiterCandidateComparisonRoleRequirements | dict[str, Any] | None = None,
        comparison_name: str | None = None,
        role_title: str | None = None,
    ) -> dict[str, Any]:
        return self.build_candidate_comparison_snapshot(
            requester_email=requester_email,
            role_requirements=role_requirements,
            saved_passport_ids=saved_passport_ids,
            comparison_name=comparison_name,
            role_title=role_title,
        )

    def get_candidate_comparison(self, comparison_id: str, requester_email: str) -> RecruiterCandidateComparisonResponse:
        row = self._comparison_for_email(comparison_id, requester_email)
        self._write_audit_event(row, "candidate_comparison_viewed")
        return self._response(row)

    def list_candidate_comparisons(self, requester_email: str) -> list[RecruiterCandidateComparisonResponse]:
        email = _normalize_email(requester_email)
        rows = [row for row in self._rows(_COMPARISONS) if str(row.get("requester_email")) == email]
        rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return [self._response(row) for row in rows]

    def archive_candidate_comparison(self, comparison_id: str, requester_email: str) -> RecruiterCandidateComparisonResponse:
        row = self._comparison_for_email(comparison_id, requester_email)
        row["status"] = "archived"
        row["updated_at"] = _now()
        saved = self._save(_COMPARISONS, row)
        self._write_audit_event(saved, "candidate_comparison_archived")
        return self._response(saved)

    def _candidate_snapshot(
        self,
        saved_row: dict[str, Any],
        role_requirements: dict[str, Any],
    ) -> RecruiterCandidateSnapshot | None:
        passport = self._passport_by_id(str(saved_row.get("passport_id")))
        if not passport:
            return None
        session_id = str(passport.get("proof_session_id") or "")
        user_id = str(passport.get("user_id") or "")
        if not session_id or not user_id:
            return None
        status_service = WorkPassportStatusService(self._client)
        timeline_service = SkillEvidenceTimelineService(self._client)
        status = status_service.get_work_passport_status(user_id, session_id)
        timeline = timeline_service.get_skill_evidence_timeline(user_id, session_id)
        ai_row = self._row_by_session(_AI_DOMAIN, user_id, session_id)
        skills = list(timeline.skills or [])
        skill_index = {str(skill.normalized_skill_name).lower(): skill for skill in skills}
        required_skills = _string_list(role_requirements.get("required_skills"))
        preferred_skills = _string_list(role_requirements.get("preferred_skills"))
        matched_required, partially_matched_required, missing_required = _match_skills(required_skills, skill_index)
        matched_preferred, _, _ = _match_skills(preferred_skills, skill_index, allow_partial=True)
        strong_count = len([skill for skill in skills if skill.support_level == "strong"])
        partial_count = len([skill for skill in skills if skill.support_level == "partial"])
        missing_count = len([skill for skill in skills if skill.support_level == "missing"])
        candidate_match_score = _candidate_match_score(
            required_skills=required_skills,
            preferred_skills=preferred_skills,
            matched_required=matched_required,
            partially_matched_required=partially_matched_required,
            matched_preferred=matched_preferred,
            readiness_score=int(status.readiness_score or 0),
            ai_domain_score=int(status.ai_domain_review_score or 0),
        )
        access_status = self._access_status(str(saved_row.get("requester_email") or ""), str(passport["id"]))
        student_name = _student_display_name(self._client, user_id)
        safe_summary = (
            passport.get("public_summary")
            or status.recruiter_safe_summary
            or "Recruiter-safe summary available."
        )
        recommended_follow_up = _recommended_follow_up(
            missing_required=missing_required,
            candidate_match_score=candidate_match_score,
            access_status=access_status,
            ai_row=ai_row,
        )
        return RecruiterCandidateSnapshot(
            saved_passport_id=str(saved_row["id"]),
            passport_id=str(passport["id"]),
            public_slug=str(passport.get("public_slug") or ""),
            student_display_name=student_name,
            field=passport.get("field"),
            overall_status=status.overall_status,
            readiness_score=status.readiness_score,
            ai_domain_review_score=status.ai_domain_review_score,
            ai_domain_reviewer_name=status.ai_domain_reviewer_name,
            strong_skill_count=strong_count,
            partial_skill_count=partial_count,
            missing_skill_count=missing_count,
            matched_required_skills=matched_required,
            partially_matched_required_skills=partially_matched_required,
            missing_required_skills=missing_required,
            matched_preferred_skills=matched_preferred,
            candidate_match_score=candidate_match_score,
            recruiter_fit_score=_first_int(saved_row, ["fit_score"]) or candidate_match_score,
            recruiter_tags=list(saved_row.get("tags") or []),
            recruiter_status=saved_row.get("status"),
            access_status=access_status,
            last_viewed_at=saved_row.get("last_viewed_at"),
            safe_summary=safe_summary,
            recommended_follow_up=recommended_follow_up,
        )

    def _comparison_for_email(self, comparison_id: str, requester_email: str) -> dict[str, Any]:
        row = self._by_id(_COMPARISONS, comparison_id)
        if not row or str(row.get("requester_email")) != _normalize_email(requester_email):
            raise RecruiterCandidateComparisonNotFoundError(comparison_id)
        return row

    def _upsert_requester_profile(self, requester_email: str) -> dict[str, Any]:
        email = _normalize_email(requester_email)
        existing = self._first_where(_REQUESTER_PROFILES, "email", email)
        now = _now()
        row = {
            "id": str((existing or {}).get("id") or uuid4()),
            "email": email,
            "full_name": (existing or {}).get("full_name"),
            "organization_name": (existing or {}).get("organization_name"),
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
            "risk_score": int((existing or {}).get("risk_score") or 0),
            "risk_flags": list(existing.get("risk_flags") or []) if existing else [],
            "notes": (existing or {}).get("notes"),
            "created_at": (existing or {}).get("created_at") or now,
            "updated_at": now,
        }
        return self._save(_REQUESTER_PROFILES, row)

    def _saved_rows_for_requester(self, requester_profile_id: str, requester_email: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            return [
                row for row in self._client.get(_SAVED, {}).values()
                if str(row.get("requester_profile_id")) == requester_profile_id and str(row.get("requester_email")) == requester_email
            ]
        result = self._client.table(_SAVED).select("*").eq("requester_profile_id", requester_profile_id).eq("requester_email", requester_email).execute()
        return getattr(result, "data", []) or []

    def _access_status(self, requester_email: str, passport_id: str) -> str:
        grants = [
            row for row in self._rows(_GRANTS)
            if str(row.get("requester_email")) == requester_email and str(row.get("passport_id")) == passport_id
        ]
        if any(row.get("revoked_at") for row in grants):
            return "revoked"
        for row in grants:
            if not row.get("revoked_at") and not _is_expired(row.get("expires_at")):
                return "approved"
        requests = [
            row for row in self._rows(_REQUESTS)
            if str(row.get("requester_email")) == requester_email and str(row.get("passport_id")) == passport_id
        ]
        if any(str(row.get("status")) == "pending" for row in requests):
            return "pending"
        if any(str(row.get("status")) == "denied" for row in requests):
            return "denied"
        return "not_requested"

    def _write_audit_event(self, comparison: dict[str, Any], event_type: str) -> None:
        self._insert(
            _AUDIT_EVENTS,
            {
                "id": str(uuid4()),
                "user_id": None,
                "proof_session_id": None,
                "passport_id": None,
                "access_request_id": None,
                "access_grant_id": None,
                "event_type": event_type,
                "actor_type": "recruiter",
                "actor_email": comparison.get("requester_email"),
                "actor_user_id": None,
                "event_summary": _event_summary(event_type, comparison),
                "metadata": {
                    "comparison_id": comparison.get("id"),
                    "comparison_name": comparison.get("comparison_name"),
                    "role_title": comparison.get("role_title"),
                    "requester_profile_id": comparison.get("requester_profile_id"),
                    "candidate_passport_ids": list(comparison.get("candidate_passport_ids") or []),
                },
                "created_at": _now(),
            },
        )

    def _response(self, row: dict[str, Any]) -> RecruiterCandidateComparisonResponse:
        snapshot = row.get("comparison_snapshot")
        if not isinstance(snapshot, dict):
            snapshot = {}
        return RecruiterCandidateComparisonResponse(
            id=str(row["id"]),
            requester_profile_id=str(row["requester_profile_id"]),
            requester_email=str(row["requester_email"]),
            comparison_name=row.get("comparison_name"),
            role_title=row.get("role_title"),
            role_requirements=_role_requirements_dict(row.get("role_requirements") or {}),
            candidate_passport_ids=[str(value) for value in list(row.get("candidate_passport_ids") or [])],
            comparison_snapshot=RecruiterCandidateComparisonSnapshot(
                comparison_name=snapshot.get("comparison_name"),
                role_title=snapshot.get("role_title"),
                role_requirements=_role_requirements_dict(snapshot.get("role_requirements") or {}),
                generated_at=snapshot.get("generated_at") or row.get("created_at"),
                candidate_count=int(snapshot.get("candidate_count") or len(snapshot.get("candidates") or [])),
                candidates=[RecruiterCandidateSnapshot.model_validate(candidate) for candidate in list(snapshot.get("candidates") or [])],
            ),
            status=row.get("status") or "draft",
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

    def _save(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        row = make_json_safe(row)
        if isinstance(self._client, dict):
            self._client.setdefault(table, {})[str(row["id"])] = row
            return row
        result = self._client.table(table).upsert(row).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError(f"{table} upsert returned no data.")
        return rows[0]

    def _insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        row = make_json_safe(row)
        if isinstance(self._client, dict):
            self._client.setdefault(table, {})[str(row["id"])] = row
            return row
        result = self._client.table(table).insert(row).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError(f"{table} insert returned no data.")
        return rows[0]

    def _passport_by_id(self, passport_id: str) -> dict[str, Any] | None:
        return self._by_id(_PASSPORTS, passport_id)

    def _row_by_session(self, table: str, user_id: str, proof_session_id: str) -> dict[str, Any] | None:
        rows = self._rows_by_session(table, user_id, proof_session_id)
        rows.sort(key=lambda row: str(row.get("created_at") or row.get("updated_at") or ""), reverse=True)
        return rows[0] if rows else None

    def _rows_by_session(self, table: str, user_id: str, proof_session_id: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            return [
                row for row in self._client.get(table, {}).values()
                if str(row.get("user_id")) == user_id and str(row.get("proof_session_id")) == proof_session_id
            ]
        result = self._client.table(table).select("*").eq("user_id", user_id).eq("proof_session_id", proof_session_id).execute()
        return getattr(result, "data", []) or []


def _role_requirements_dict(value: RecruiterCandidateComparisonRoleRequirements | dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, RecruiterCandidateComparisonRoleRequirements):
        return value.model_dump(mode="json")
    return {
        "required_skills": _string_list(value.get("required_skills")),
        "preferred_skills": _string_list(value.get("preferred_skills")),
        "field": _trim_to_none(value.get("field")),
    }


def _match_skills(
    desired_skills: list[str],
    skill_index: dict[str, Any],
    *,
    allow_partial: bool = False,
) -> tuple[list[str], list[str], list[str]]:
    matched: list[str] = []
    partial: list[str] = []
    missing: list[str] = []
    for skill in desired_skills:
        key = _normalize_skill(skill)
        record = skill_index.get(key)
        if record is None:
            missing.append(skill)
            continue
        if allow_partial:
            matched.append(skill)
            continue
        if record.support_level == "strong":
            matched.append(skill)
        elif allow_partial or record.support_level in {"partial", "weak"}:
            partial.append(skill)
        else:
            missing.append(skill)
    return matched, partial, missing


def _candidate_match_score(
    *,
    required_skills: list[str],
    preferred_skills: list[str],
    matched_required: list[str],
    partially_matched_required: list[str],
    matched_preferred: list[str],
    readiness_score: int,
    ai_domain_score: int,
) -> int:
    required_total = max(len(required_skills), 1)
    preferred_total = max(len(preferred_skills), 1)
    required_points = ((len(matched_required) * 1.0) + (len(partially_matched_required) * 0.5)) / required_total * 60
    preferred_points = len(matched_preferred) / preferred_total * 20
    readiness_points = max(0, min(readiness_score, 100)) / 100 * 10
    ai_points = max(0, min(ai_domain_score, 100)) / 100 * 10
    return max(0, min(100, int(round(required_points + preferred_points + readiness_points + ai_points))))


def _recommended_follow_up(
    *,
    missing_required: list[str],
    candidate_match_score: int,
    access_status: str,
    ai_row: dict[str, Any] | None,
) -> str:
    if missing_required:
        return f"Review missing required skills: {', '.join(missing_required[:3])}."
    if access_status in {"not_requested", "pending"}:
        return "Request protected evidence access to review additional sections."
    if ai_row and str(ai_row.get("confidence_level") or "").lower() == "low":
        return "Review the AI Domain Review output and consider requesting stronger evidence."
    if candidate_match_score < 60:
        return "Compare this candidate against other saved passports and review recruiter notes."
    return "Review recruiter notes and protected evidence before making a final shortlist decision."


def _student_display_name(client: Any, user_id: str) -> str | None:
    profile = _student_profile(client, user_id)
    if profile and profile.get("full_name"):
        return str(profile["full_name"])
    user = _by_id_from_client(client, _USERS, user_id)
    if user and user.get("email"):
        return str(user["email"]).split("@", 1)[0]
    return None


def _student_profile(client: Any, user_id: str) -> dict[str, Any] | None:
    if isinstance(client, dict):
        for row in client.get(_PROFILES, {}).values():
            if str(row.get("user_id")) == user_id:
                return row
        return None
    result = client.table(_PROFILES).select("*").eq("user_id", user_id).limit(1).execute()
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _by_id_from_client(client: Any, table: str, row_id: str) -> dict[str, Any] | None:
    if isinstance(client, dict):
        return client.get(table, {}).get(row_id)
    result = client.table(table).select("*").eq("id", row_id).limit(1).execute()
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _event_summary(event_type: str, comparison: dict[str, Any] | None = None) -> str:
    if event_type == "candidate_comparison_created":
        return "Recruiter candidate comparison created."
    if event_type == "candidate_comparison_viewed":
        return "Recruiter candidate comparison viewed."
    if event_type == "candidate_comparison_archived":
        return "Recruiter candidate comparison archived."
    if comparison:
        return f"Recruiter candidate comparison event recorded for {comparison.get('comparison_name') or 'comparison'}."
    return "Recruiter candidate comparison event recorded."


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _email_domain(email: str) -> str | None:
    if "@" not in email:
        return None
    domain = email.rsplit("@", 1)[-1].strip().lower()
    return domain or None


def _normalize_id_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _string_list(values: Any) -> list[str]:
    if not values:
        return []
    if isinstance(values, list):
        return [str(value).strip() for value in values if str(value).strip()]
    return [str(values).strip()] if str(values).strip() else []


def _normalize_skill(value: str) -> str:
    return "".join(ch.lower() for ch in str(value).strip() if ch.isalnum())


def _trim_to_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_expired(value: Any) -> bool:
    parsed = _parse_dt(value)
    return bool(parsed and parsed <= _now())


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
