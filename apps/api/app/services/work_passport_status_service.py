"""Central Work Passport status orchestration service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.schemas.work_passport_status import (
    PublicWorkPassportStatusResponse,
    WorkPassportIssue,
    WorkPassportStatusResponse,
)
from app.services.extension_proof_service import ExtensionProofSessionNotFoundError
from app.services.skill_evidence_timeline_service import SkillEvidenceTimelineService
from app.services.verification_readiness_service import compute_readiness_report

_SESSIONS = "extension_proof_sessions"
_SKILL_EVIDENCE = "skill_evidence"
_WORKFLOW = "workflow_analysis_results"
_PRIVACY = "workflow_privacy_scan_results"
_LIVE = "live_website_check_results"
_GITHUB = "extension_proof_github_analysis"
_DEFENSE = "project_defense_analysis_results"
_AI_DOMAIN = "ai_domain_review_results"
_REVIEWS = "verification_review_requests"
_VERSIONS = "proof_evidence_versions"
_PASSPORTS = "public_work_passports"
_REQUESTS = "evidence_access_requests"
_GRANTS = "evidence_access_grants"
_ADMIN_CASES = "admin_quality_review_cases"
_NOTIFICATIONS = "notification_events"
_REQUESTER_PROFILES = "recruiter_requester_profiles"

_OPEN_ADMIN_STATUSES = {"open", "under_review", "needs_student_action", "escalated"}
_ARCHIVED_VERSION_STATUSES = {"archived"}


class WorkPassportStatusService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def get_work_passport_status(self, user_id: str, proof_session_id: str) -> WorkPassportStatusResponse:
        session = self._get_session(user_id, proof_session_id)
        skill = self._skill_evidence(user_id, str(session.get("skill_evidence_id") or ""))
        workflow = self._row_by_session(_WORKFLOW, user_id, proof_session_id)
        privacy = self._row_by_session(_PRIVACY, user_id, proof_session_id)
        live = self._row_by_session(_LIVE, user_id, proof_session_id)
        github = self._row_by_session(_GITHUB, user_id, proof_session_id)
        defense = self._row_by_session(_DEFENSE, user_id, proof_session_id)
        ai_domain = self._row_by_session(_AI_DOMAIN, user_id, proof_session_id)
        ai_review = self._row_by_session(_REVIEWS, user_id, proof_session_id)
        active_version = self._active_version(user_id, proof_session_id)
        passport = self._row_by_session(_PASSPORTS, user_id, proof_session_id)
        requests = self._rows_by_session(_REQUESTS, user_id, proof_session_id)
        grants = self._rows_by_session(_GRANTS, user_id, proof_session_id)
        admin_cases = self._rows_by_session(_ADMIN_CASES, user_id, proof_session_id)
        notifications = self._rows_for_user(_NOTIFICATIONS, user_id)
        readiness = compute_readiness_report(
            proof_session_id=proof_session_id,
            session_status=str(session.get("status") or ""),
            website_url=_website_url(session, skill),
            claimed_skills=_claimed_skills(session, skill, workflow, github, ai_domain),
            workflow_analysis=workflow,
            live_check=live,
            github_analysis=github,
            privacy_scan=privacy,
            defense_analysis=defense,
        )
        open_admin_cases = [row for row in admin_cases if row.get("status") in _OPEN_ADMIN_STATUSES]
        pending_requests = [row for row in requests if row.get("status") == "pending"]
        active_grants = [row for row in grants if not row.get("revoked_at")]
        blocking_issues = self._blocking_issues(
            readiness=readiness,
            privacy=privacy,
            defense=defense,
            ai_domain=ai_domain,
            passport=passport,
            active_version=active_version,
            open_admin_cases=open_admin_cases,
            requests=requests,
        )
        warnings = self._warnings(
            live=live,
            github=github,
            defense=defense,
            ai_domain=ai_domain,
            active_version=active_version,
            requests=requests,
        )
        skill_evidence_summary = _skill_evidence_summary(self._client, user_id, proof_session_id)
        completed_steps = _completed_steps(workflow, privacy, live, github, defense, ai_domain, passport, active_version, notifications)
        missing_steps = _missing_steps(workflow, privacy, defense, ai_domain, passport, active_version, pending_requests, open_admin_cases)
        overall_status = _overall_status(
            session=session,
            readiness_score=readiness.readiness_score,
            privacy=privacy,
            ai_domain=ai_domain,
            passport=passport,
            active_version=active_version,
            open_admin_cases=open_admin_cases,
            pending_requests=pending_requests,
        )
        label, description = _status_copy(overall_status)
        next_action = _recommended_next_action(blocking_issues, warnings, missing_steps, overall_status)
        return WorkPassportStatusResponse(
            proof_session_id=proof_session_id,
            overall_status=overall_status,
            status_label=label,
            status_description=description,
            readiness_score=readiness.readiness_score,
            readiness_level=readiness.readiness_level,
            ai_review_status=ai_review.get("ai_review_status") if ai_review else None,
            ai_domain_review_status=ai_domain.get("ai_domain_review_status") if ai_domain else None,
            ai_domain_reviewer_name=ai_domain.get("reviewer_name") if ai_domain else None,
            ai_domain_review_score=_first_int(ai_domain or {}, ["domain_review_score", "overall_score"]),
            project_defense_status=_project_defense_status(defense),
            project_defense_score=_first_int(defense or {}, ["overall_defense_score"]),
            privacy_status=_privacy_status(privacy),
            public_passport_status=_passport_status(passport),
            public_slug=passport.get("public_slug") if passport else None,
            active_version_id=str(active_version["id"]) if active_version else None,
            active_version_number=int(active_version["version_number"]) if active_version else None,
            admin_review_status=_admin_review_status(open_admin_cases),
            open_admin_case_count=len(open_admin_cases),
            pending_access_request_count=len(pending_requests),
            active_access_grant_count=len(active_grants),
            unread_notification_count=len([row for row in notifications if row.get("read_at") is None and row.get("archived_at") is None]),
            skill_evidence_summary=skill_evidence_summary,
            blocking_issues=blocking_issues,
            warnings=warnings,
            completed_steps=completed_steps,
            missing_steps=missing_steps,
            recommended_next_action=next_action,
            recruiter_safe_summary=_recruiter_safe_summary(readiness.readiness_level, ai_domain, passport, overall_status),
            student_next_steps=_student_next_steps(blocking_issues, warnings, missing_steps, next_action),
            generated_at=_now(),
        )

    def get_public_passport_status(self, public_slug: str) -> PublicWorkPassportStatusResponse:
        passport = self._passport_by_slug(public_slug)
        if not passport or not passport.get("is_public", True):
            raise ExtensionProofSessionNotFoundError(public_slug)
        full = self.get_work_passport_status(str(passport["user_id"]), str(passport["proof_session_id"]))
        return PublicWorkPassportStatusResponse(
            overall_status=full.overall_status,
            status_label=full.status_label,
            readiness_level=full.readiness_level,
            ai_review_status=full.ai_review_status,
            ai_domain_review_status=full.ai_domain_review_status,
            privacy_status=_public_privacy_status(full.privacy_status),
            public_passport_status=full.public_passport_status,
            recruiter_safe_summary=full.recruiter_safe_summary,
            generated_at=full.generated_at,
        )

    def _blocking_issues(
        self,
        *,
        readiness: Any,
        privacy: dict[str, Any] | None,
        defense: dict[str, Any] | None,
        ai_domain: dict[str, Any] | None,
        passport: dict[str, Any] | None,
        active_version: dict[str, Any] | None,
        open_admin_cases: list[dict[str, Any]],
        requests: list[dict[str, Any]],
    ) -> list[WorkPassportIssue]:
        issues: list[WorkPassportIssue] = []
        privacy_status = _privacy_status(privacy)
        if privacy_status in {"flagged", "unsafe"}:
            issues.append(_issue("privacy_flagged", "Privacy review required", "Potential sensitive evidence needs review before stronger sharing claims.", "privacy_scan", "urgent", "Resolve or redact privacy findings."))
        if not defense:
            issues.append(_issue("missing_project_defense", "Project defense missing", "A project defense explanation has not been completed.", "project_defense", "high", "Submit a project defense recording or transcript."))
        if readiness.readiness_score < 60:
            issues.append(_issue("needs_more_evidence", "More evidence needed", "Current evidence readiness is below the threshold for strong sharing.", "readiness", "high", "Add stronger proof for unsupported skills."))
        if ai_domain and str(ai_domain.get("confidence_level") or "").lower() == "low":
            issues.append(_issue("low_ai_confidence", "Low AI review confidence", "The AI domain review reported low confidence.", "ai_domain_review", "normal", "Add clearer evidence or request review again."))
        for case in open_admin_cases:
            issues.append(_issue("admin_case_open", "Admin review open", case.get("summary") or "An internal quality review case is open.", "admin_quality_review", "high", "Address the admin review outcome."))
        if not passport:
            issues.append(_issue("no_public_passport", "Public passport not created", "No public Work Passport exists for this proof session.", "public_work_passport", "normal", "Create a public Work Passport when ready."))
        if active_version and active_version.get("status") in _ARCHIVED_VERSION_STATUSES:
            issues.append(_issue("active_version_archived", "Active version archived", "The active evidence version is archived.", "proof_versioning", "high", "Activate a non-archived evidence version."))
        if self._has_suspicious_requester(requests):
            issues.append(_issue("suspicious_requester", "Requester risk detected", "One or more requester profiles have risk flags.", "requester_profile", "normal", "Review requester identity before granting access."))
        return issues

    def _warnings(
        self,
        *,
        live: dict[str, Any] | None,
        github: dict[str, Any] | None,
        defense: dict[str, Any] | None,
        ai_domain: dict[str, Any] | None,
        active_version: dict[str, Any] | None,
        requests: list[dict[str, Any]],
    ) -> list[WorkPassportIssue]:
        warnings: list[WorkPassportIssue] = []
        if live and live.get("is_reachable") is False:
            warnings.append(_issue("live_site_not_available", "Live site unavailable", "The live project check could not reach the site.", "live_website_check", "normal", "Confirm the public project URL is reachable."))
        if github and (github.get("weakly_matched_claimed_skills") or github.get("status") not in {None, "success"}):
            warnings.append(_issue("github_partial_evidence", "GitHub evidence partial", "Repository evidence only partially supports claimed skills.", "github_analysis", "low", "Add clearer source files or documentation."))
        if defense and _first_int(defense, ["overall_defense_score"]) is not None and _first_int(defense, ["overall_defense_score"]) < 60:
            warnings.append(_issue("transcript_clarity_low", "Project defense clarity low", "The project defense score is below a strong threshold.", "project_defense", "normal", "Improve the explanation of ownership and decisions."))
        if not ai_domain:
            warnings.append(_issue("no_domain_review_yet", "Domain review not run", "No AI Domain Review has been completed yet.", "ai_domain_review", "low", "Run AI Domain Review when evidence is ready."))
        if not active_version:
            warnings.append(_issue("no_active_version", "No active evidence version", "No active evidence version is available.", "proof_versioning", "low", "Create an evidence version."))
        if not requests:
            warnings.append(_issue("no_access_requests_yet", "No access requests", "No requester has asked for protected evidence yet.", "access_requests", "info", None))
        return warnings

    def _has_suspicious_requester(self, requests: list[dict[str, Any]]) -> bool:
        for request in requests:
            profile_id = request.get("requester_profile_id")
            if not profile_id:
                continue
            profile = self._by_id(_REQUESTER_PROFILES, str(profile_id))
            if profile and (int(profile.get("risk_score") or 0) >= 30 or profile.get("verification_status") in {"suspicious", "blocked"}):
                return True
        return False

    def _get_session(self, user_id: str, proof_session_id: str) -> dict[str, Any]:
        if isinstance(self._client, dict):
            row = self._client.setdefault(_SESSIONS, {}).get(proof_session_id)
            if not row or str(row.get("user_id")) != user_id:
                raise ExtensionProofSessionNotFoundError(proof_session_id)
            return row
        result = self._client.table(_SESSIONS).select("*").eq("id", proof_session_id).eq("user_id", user_id).maybe_single().execute()
        if result is None or not getattr(result, "data", None):
            raise ExtensionProofSessionNotFoundError(proof_session_id)
        return result.data

    def _skill_evidence(self, user_id: str, evidence_id: str) -> dict[str, Any] | None:
        if not evidence_id:
            return None
        if isinstance(self._client, dict):
            row = self._client.get(_SKILL_EVIDENCE, {}).get(evidence_id)
            return row if row and str(row.get("user_id")) == user_id else None
        result = self._client.table(_SKILL_EVIDENCE).select("*").eq("id", evidence_id).eq("user_id", user_id).maybe_single().execute()
        return getattr(result, "data", None) if result is not None else None

    def _row_by_session(self, table: str, user_id: str, proof_session_id: str) -> dict[str, Any] | None:
        rows = self._rows_by_session(table, user_id, proof_session_id)
        return rows[0] if rows else None

    def _rows_by_session(self, table: str, user_id: str, proof_session_id: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            return [row for row in self._client.get(table, {}).values() if str(row.get("user_id")) == user_id and str(row.get("proof_session_id")) == proof_session_id]
        result = self._client.table(table).select("*").eq("user_id", user_id).eq("proof_session_id", proof_session_id).execute()
        return getattr(result, "data", []) or []

    def _rows_for_user(self, table: str, user_id: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            return [row for row in self._client.get(table, {}).values() if str(row.get("user_id")) == user_id]
        result = self._client.table(table).select("*").eq("user_id", user_id).execute()
        return getattr(result, "data", []) or []

    def _active_version(self, user_id: str, proof_session_id: str) -> dict[str, Any] | None:
        for row in self._rows_by_session(_VERSIONS, user_id, proof_session_id):
            if row.get("is_active"):
                return row
        return None

    def _passport_by_slug(self, public_slug: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            for row in self._client.get(_PASSPORTS, {}).values():
                if str(row.get("public_slug")) == public_slug:
                    return row
            return None
        result = self._client.table(_PASSPORTS).select("*").eq("public_slug", public_slug).limit(1).execute()
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _by_id(self, table: str, row_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            return self._client.get(table, {}).get(row_id)
        result = self._client.table(table).select("*").eq("id", row_id).limit(1).execute()
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None


def _overall_status(
    *,
    session: dict[str, Any],
    readiness_score: int,
    privacy: dict[str, Any] | None,
    ai_domain: dict[str, Any] | None,
    passport: dict[str, Any] | None,
    active_version: dict[str, Any] | None,
    open_admin_cases: list[dict[str, Any]],
    pending_requests: list[dict[str, Any]],
) -> str:
    if active_version and active_version.get("status") == "archived":
        return "archived"
    privacy_status = _privacy_status(privacy)
    if privacy_status == "unsafe":
        return "blocked"
    if privacy_status == "flagged":
        return "privacy_review_required"
    if open_admin_cases:
        if any(case.get("status") == "needs_student_action" for case in open_admin_cases):
            return "needs_more_evidence"
        return "admin_review_pending"
    if pending_requests:
        return "access_requests_pending"
    if passport and passport.get("is_public", True):
        return "public_passport_active"
    if ai_domain:
        return "ai_domain_reviewed"
    if readiness_score >= 80:
        return "ai_reviewed"
    if readiness_score < 60 and session.get("status") not in {"created", "recording"}:
        return "needs_more_evidence"
    if session.get("status") == "analyzing":
        return "analysis_in_progress"
    if session.get("status") in {"uploaded_pending_analysis", "completed"}:
        return "evidence_collected"
    if session.get("status") in {"recording", "waiting_for_extension"}:
        return "evidence_in_progress"
    return "draft"


def _completed_steps(workflow: Any, privacy: Any, live: Any, github: Any, defense: Any, ai_domain: Any, passport: Any, active_version: Any, notifications: list[dict[str, Any]]) -> list[str]:
    steps = []
    if workflow:
        steps.append("workflow_recorded")
    if privacy:
        steps.append("privacy_scan_complete")
    if live:
        steps.append("live_site_checked")
    if github:
        steps.append("github_analyzed")
    if defense:
        steps.append("project_defense_completed")
    if defense and (defense.get("transcript_text") or defense.get("transcript_summary")):
        steps.append("transcript_generated")
    if ai_domain:
        steps.append("ai_domain_review_completed")
    if passport:
        steps.append("public_passport_created")
    if active_version:
        steps.append("active_version_available")
    if notifications is not None:
        steps.append("notifications_enabled")
    return steps


def _missing_steps(workflow: Any, privacy: Any, defense: Any, ai_domain: Any, passport: Any, active_version: Any, pending_requests: list[Any], open_admin_cases: list[Any]) -> list[str]:
    steps = []
    if not ai_domain:
        steps.append("run_ai_domain_review")
    if not passport:
        steps.append("create_public_passport")
    if not defense:
        steps.append("submit_project_defense")
    if privacy and _privacy_status(privacy) in {"flagged", "unsafe"}:
        steps.append("resolve_privacy_issue")
    if pending_requests:
        steps.append("review_access_requests")
    if not active_version:
        steps.append("create_evidence_version")
    if open_admin_cases:
        steps.append("address_admin_review_case")
    return steps


def _issue(code: str, label: str, description: str, source: str, severity: str, recommended_fix: str | None) -> WorkPassportIssue:
    return WorkPassportIssue(code=code, label=label, description=description, source=source, severity=severity, recommended_fix=recommended_fix)


def _status_copy(status: str) -> tuple[str, str]:
    labels = {
        "draft": ("Draft", "Evidence collection has not started yet."),
        "evidence_in_progress": ("Evidence in progress", "Evidence is currently being collected."),
        "evidence_collected": ("Evidence collected", "Evidence has been collected and is ready for analysis."),
        "analysis_in_progress": ("Analysis in progress", "Evidence analysis is currently running."),
        "needs_more_evidence": ("Needs more evidence", "More or clearer evidence is needed before stronger sharing."),
        "privacy_review_required": ("Privacy review required", "Potential privacy issues need review before sharing."),
        "ai_reviewed": ("AI reviewed", "The evidence package has a readiness review."),
        "ai_domain_reviewed": ("AI Domain Reviewed", "A field-aware AI domain review is available."),
        "admin_review_pending": ("Admin review pending", "Internal VeriBridge review is open."),
        "approved_for_sharing": ("Approved for sharing", "The package appears ready for controlled sharing."),
        "public_passport_active": ("Public Passport active", "The public Work Passport is active."),
        "access_requests_pending": ("Access requests pending", "One or more evidence access requests need review."),
        "blocked": ("Blocked", "A blocking issue prevents safe sharing."),
        "archived": ("Archived", "The active evidence version is archived."),
    }
    return labels.get(status, ("Status available", "Work Passport status is available."))


def _recommended_next_action(blocking: list[WorkPassportIssue], warnings: list[WorkPassportIssue], missing: list[str], status: str) -> str | None:
    if blocking:
        return blocking[0].recommended_fix or blocking[0].label
    if "review_access_requests" in missing:
        return "Review pending access requests."
    if "run_ai_domain_review" in missing:
        return "Run AI Domain Review when your evidence is ready."
    if "create_public_passport" in missing:
        return "Create a public Work Passport."
    if warnings:
        return warnings[0].recommended_fix
    if status == "public_passport_active":
        return "Monitor access requests and analytics."
    return None


def _student_next_steps(blocking: list[WorkPassportIssue], warnings: list[WorkPassportIssue], missing: list[str], next_action: str | None) -> list[str]:
    steps = []
    if next_action:
        steps.append(next_action)
    steps.extend(issue.recommended_fix for issue in blocking[1:] if issue.recommended_fix)
    if not steps:
        steps.extend(step.replace("_", " ") for step in missing[:3])
    if not steps:
        steps.extend(issue.recommended_fix for issue in warnings[:2] if issue.recommended_fix)
    return [step for step in steps if step]


def _skill_evidence_summary(client: Any, user_id: str, proof_session_id: str) -> dict[str, int] | None:
    try:
        timeline = SkillEvidenceTimelineService(client).get_skill_evidence_timeline(user_id, proof_session_id)
    except Exception:
        return None
    return {
        "strong_skill_count": len([skill for skill in timeline.skills if skill.support_level == "strong"]),
        "partial_skill_count": len([skill for skill in timeline.skills if skill.support_level == "partial"]),
        "missing_skill_count": len([skill for skill in timeline.skills if skill.support_level in {"weak", "missing"}]),
    }


def _recruiter_safe_summary(readiness_level: str, ai_domain: dict[str, Any] | None, passport: dict[str, Any] | None, status: str) -> str:
    if ai_domain and ai_domain.get("recruiter_summary"):
        return str(ai_domain["recruiter_summary"])
    if passport and passport.get("public_summary"):
        return str(passport["public_summary"])
    return f"Work Passport status is {status.replace('_', ' ')} with {readiness_level} readiness."


def _privacy_status(row: dict[str, Any] | None) -> str | None:
    return str(row.get("status") or row.get("privacy_scan_status")) if row else None


def _public_privacy_status(status: str | None) -> str | None:
    if status in {"flagged", "unsafe"}:
        return "review_required"
    return status


def _project_defense_status(row: dict[str, Any] | None) -> str | None:
    if not row:
        return None
    return str(row.get("status") or row.get("transcription_status") or "completed")


def _passport_status(row: dict[str, Any] | None) -> str | None:
    if not row:
        return None
    return "public" if row.get("is_public", True) else "private"


def _admin_review_status(open_cases: list[dict[str, Any]]) -> str | None:
    if not open_cases:
        return "clear"
    if any(row.get("status") == "needs_student_action" for row in open_cases):
        return "needs_student_action"
    if any(row.get("status") == "escalated" for row in open_cases):
        return "escalated"
    return "open"


def _website_url(session: dict[str, Any], skill: dict[str, Any] | None) -> str:
    return str(session.get("website_url") or (skill or {}).get("evidence_url") or "")


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
                values.extend(str(value) for value in raw if str(value).strip())
    return list(dict.fromkeys(values))


def _first_int(row: dict[str, Any], keys: list[str]) -> int | None:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return int(value)
    return None


def _now() -> datetime:
    return datetime.now(UTC)
