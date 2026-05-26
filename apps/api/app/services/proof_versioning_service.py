"""Proof evidence versioning and resubmission service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.schemas.proof_versioning import ProofEvidenceVersionResponse
from app.services.extension_proof_service import ExtensionProofSessionNotFoundError
from app.services.notification_service import NotificationService
from app.services.verification_readiness_service import compute_readiness_report

_VERSIONS = "proof_evidence_versions"
_SESSIONS = "extension_proof_sessions"
_SKILL_EVIDENCE = "skill_evidence"
_WORKFLOW = "workflow_analysis_results"
_PRIVACY = "workflow_privacy_scan_results"
_LIVE = "live_website_check_results"
_GITHUB = "extension_proof_github_analysis"
_DEFENSE = "project_defense_analysis_results"
_AI_DOMAIN = "ai_domain_review_results"
_REVIEWS = "verification_review_requests"
_PASSPORTS = "public_work_passports"
_USERS = "users"

_BLOCKED_KEYS = {
    "access_token",
    "media_storage_path",
    "media_url",
    "video_url",
    "proof_data",
    "transcript_text",
    "raw_metadata",
    "debug",
}


class ProofEvidenceVersionNotFoundError(LookupError):
    """Proof evidence version not found for the scoped student/session."""


class ProofVersioningService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def create_initial_version(self, user_id: str, proof_session_id: str) -> ProofEvidenceVersionResponse:
        self._get_session(user_id, proof_session_id)
        existing = self._versions_for_session(user_id, proof_session_id)
        if existing:
            return _version_response(sorted(existing, key=lambda row: int(row["version_number"]))[0])
        return _version_response(
            self._create_version(
                user_id=user_id,
                proof_session_id=proof_session_id,
                version_number=1,
                version_label="Version 1",
                status=self._status_for_current_state(user_id, proof_session_id),
                change_summary="Initial evidence version.",
                resubmission_reason=None,
                created_from_version_id=None,
                make_active=True,
            )
        )

    def create_resubmission_version(
        self,
        user_id: str,
        proof_session_id: str,
        change_summary: str | None = None,
        resubmission_reason: str | None = None,
    ) -> ProofEvidenceVersionResponse:
        self._get_session(user_id, proof_session_id)
        versions = self._versions_for_session(user_id, proof_session_id)
        if not versions:
            self.create_initial_version(user_id, proof_session_id)
            versions = self._versions_for_session(user_id, proof_session_id)
        latest = max(versions, key=lambda row: int(row.get("version_number") or 0))
        active = self._active_version_row(user_id, proof_session_id) or latest
        saved = self._create_version(
            user_id=user_id,
            proof_session_id=proof_session_id,
            version_number=int(latest.get("version_number") or 0) + 1,
            version_label=f"Version {int(latest.get('version_number') or 0) + 1}",
            status=self._status_for_current_state(user_id, proof_session_id),
            change_summary=change_summary,
            resubmission_reason=resubmission_reason,
            created_from_version_id=str(active["id"]),
            make_active=True,
        )
        self._create_version_notification(user_id, proof_session_id, saved)
        return _version_response(saved)

    def get_versions(self, user_id: str, proof_session_id: str) -> list[ProofEvidenceVersionResponse]:
        self._get_session(user_id, proof_session_id)
        rows = self._versions_for_session(user_id, proof_session_id)
        rows.sort(key=lambda row: int(row.get("version_number") or 0), reverse=True)
        return [_version_response(row) for row in rows]

    def get_active_version(self, user_id: str, proof_session_id: str) -> ProofEvidenceVersionResponse:
        self._get_session(user_id, proof_session_id)
        row = self._active_version_row(user_id, proof_session_id)
        if row is None:
            return self.create_initial_version(user_id, proof_session_id)
        return _version_response(row)

    def set_active_version(
        self,
        user_id: str,
        proof_session_id: str,
        version_id: str,
    ) -> ProofEvidenceVersionResponse:
        self._get_session(user_id, proof_session_id)
        target = self._version_for_session(user_id, proof_session_id, version_id)
        self._deactivate_versions(user_id, proof_session_id)
        target.update({"is_active": True, "updated_at": _now()})
        return _version_response(self._save(target))

    def archive_version(
        self,
        user_id: str,
        proof_session_id: str,
        version_id: str,
    ) -> ProofEvidenceVersionResponse:
        self._get_session(user_id, proof_session_id)
        target = self._version_for_session(user_id, proof_session_id, version_id)
        target.update({"status": "archived", "is_active": False, "updated_at": _now()})
        saved = self._save(target)
        if self._active_version_row(user_id, proof_session_id) is None:
            candidates = [
                row for row in self._versions_for_session(user_id, proof_session_id)
                if row.get("status") != "archived" and str(row["id"]) != version_id
            ]
            if candidates:
                replacement = max(candidates, key=lambda row: int(row.get("version_number") or 0))
                replacement.update({"is_active": True, "updated_at": _now()})
                self._save(replacement)
        return _version_response(saved)

    def build_evidence_snapshot(self, user_id: str, proof_session_id: str) -> dict[str, Any]:
        session = self._get_session(user_id, proof_session_id)
        skill = self._skill_evidence(user_id, str(session.get("skill_evidence_id") or ""))
        passport = self._row_by_session(_PASSPORTS, user_id, proof_session_id)
        return _safe_snapshot({
            "proof_session": {
                "id": session.get("id"),
                "status": session.get("status"),
                "skill_evidence_id": session.get("skill_evidence_id"),
                "website_url": session.get("website_url"),
                "github_url": session.get("github_url"),
                "claimed_skills": session.get("claimed_skills") or [],
                "title": session.get("title"),
                "description": session.get("description"),
                "proof_objective": session.get("proof_objective"),
                "metadata": session.get("metadata") if isinstance(session.get("metadata"), dict) else {},
            },
            "skill_evidence": _safe_row(skill or {}, include_keys={
                "id",
                "skill_name",
                "evidence_type",
                "evidence_url",
                "repository_url",
                "evidence_description",
                "verification_status",
                "metadata",
            }),
            "public_work_passport": _safe_row(passport or {}, include_keys={
                "id",
                "public_slug",
                "is_public",
                "public_title",
                "public_summary",
                "field",
                "visible_sections",
            }),
        })

    def build_analysis_snapshot(self, user_id: str, proof_session_id: str) -> dict[str, Any]:
        session = self._get_session(user_id, proof_session_id)
        workflow = self._row_by_session(_WORKFLOW, user_id, proof_session_id)
        privacy = self._row_by_session(_PRIVACY, user_id, proof_session_id)
        live = self._row_by_session(_LIVE, user_id, proof_session_id)
        github = self._row_by_session(_GITHUB, user_id, proof_session_id)
        defense = self._row_by_session(_DEFENSE, user_id, proof_session_id)
        ai_domain = self._row_by_session(_AI_DOMAIN, user_id, proof_session_id)
        review = self._row_by_session(_REVIEWS, user_id, proof_session_id)
        skill = self._skill_evidence(user_id, str(session.get("skill_evidence_id") or ""))
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
        return _safe_snapshot({
            "readiness": {
                "readiness_score": readiness.readiness_score,
                "readiness_level": readiness.readiness_level,
                "strongly_supported_skills": readiness.strongly_supported_skills,
                "partially_supported_skills": readiness.partially_supported_skills,
                "needs_more_evidence": readiness.needs_more_evidence,
                "risk_flags": readiness.risk_flags,
                "recruiter_summary": readiness.recruiter_summary,
            },
            "workflow_analysis": _safe_row(workflow or {}),
            "privacy_scan": _safe_row(privacy or {}),
            "live_website_check": _safe_row(live or {}),
            "github_analysis": _safe_row(github or {}),
            "project_defense": _safe_row(defense or {}, include_keys={
                "id",
                "status",
                "transcript_summary",
                "skills_mentioned",
                "skills_explained_well",
                "skills_missing_from_explanation",
                "overall_defense_score",
                "recruiter_summary",
                "risk_flags",
                "privacy_scan_status",
                "transcription_status",
                "transcript_reviewed",
            }),
            "ai_domain_review": _safe_row(ai_domain or {}),
            "verification_review": _safe_row(review or {}, include_keys={
                "id",
                "ai_review_status",
                "readiness_score",
                "readiness_level",
                "privacy_status",
                "human_review_status",
            }),
        })

    def _create_version(
        self,
        *,
        user_id: str,
        proof_session_id: str,
        version_number: int,
        version_label: str,
        status: str,
        change_summary: str | None,
        resubmission_reason: str | None,
        created_from_version_id: str | None,
        make_active: bool,
    ) -> dict[str, Any]:
        now = _now()
        evidence_snapshot = self.build_evidence_snapshot(user_id, proof_session_id)
        analysis_snapshot = self.build_analysis_snapshot(user_id, proof_session_id)
        if make_active:
            self._deactivate_versions(user_id, proof_session_id)
        row = {
            "id": str(uuid4()),
            "user_id": user_id,
            "proof_session_id": proof_session_id,
            "version_number": version_number,
            "version_label": version_label,
            "status": status,
            "change_summary": change_summary,
            "resubmission_reason": resubmission_reason,
            "evidence_snapshot": evidence_snapshot,
            "analysis_snapshot": analysis_snapshot,
            "readiness_score": _nested_int(analysis_snapshot, "readiness", "readiness_score"),
            "ai_domain_review_score": _first_int(analysis_snapshot.get("ai_domain_review") or {}, ["domain_review_score", "overall_score"]),
            "project_defense_score": _first_int(analysis_snapshot.get("project_defense") or {}, ["overall_defense_score"]),
            "privacy_status": _first_text(analysis_snapshot.get("privacy_scan") or {}, ["status", "privacy_scan_status"]),
            "created_from_version_id": created_from_version_id,
            "is_active": make_active,
            "submitted_at": now,
            "created_at": now,
            "updated_at": now,
        }
        return self._insert(row)

    def _status_for_current_state(self, user_id: str, proof_session_id: str) -> str:
        review = self._row_by_session(_REVIEWS, user_id, proof_session_id)
        ai_domain = self._row_by_session(_AI_DOMAIN, user_id, proof_session_id)
        readiness_score = int((review or {}).get("readiness_score") or 0)
        ai_status = str((review or {}).get("ai_review_status") or "")
        if ai_status == "ai_approved_for_sharing":
            return "approved_for_sharing"
        if ai_domain:
            return "ai_domain_reviewed"
        if readiness_score and readiness_score < 80:
            return "needs_more_evidence"
        return "submitted"

    def _create_version_notification(self, user_id: str, proof_session_id: str, version: dict[str, Any]) -> None:
        try:
            NotificationService(self._client).create_notification_event(
                user_id=user_id,
                event_type="verification_needs_more_evidence",
                recipient_email=self._user_email(user_id),
                title="Evidence version created",
                message="A new evidence version was created for your Work Passport.",
                category="verification",
                priority="normal",
                metadata={
                    "proof_session_id": proof_session_id,
                    "version_id": str(version["id"]),
                    "version_number": int(version["version_number"]),
                },
            )
        except Exception:
            return

    def _get_session(self, user_id: str, proof_session_id: str) -> dict[str, Any]:
        if isinstance(self._client, dict):
            row = self._client.setdefault(_SESSIONS, {}).get(proof_session_id)
            if not row or str(row.get("user_id")) != user_id:
                raise ExtensionProofSessionNotFoundError(proof_session_id)
            return row
        result = (
            self._client.table(_SESSIONS)
            .select("*")
            .eq("id", proof_session_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if result is None or not getattr(result, "data", None):
            raise ExtensionProofSessionNotFoundError(proof_session_id)
        return result.data

    def _versions_for_session(self, user_id: str, proof_session_id: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            return [
                row for row in self._client.get(_VERSIONS, {}).values()
                if str(row.get("user_id")) == user_id and str(row.get("proof_session_id")) == proof_session_id
            ]
        result = (
            self._client.table(_VERSIONS)
            .select("*")
            .eq("user_id", user_id)
            .eq("proof_session_id", proof_session_id)
            .execute()
        )
        return getattr(result, "data", []) or []

    def _version_for_session(self, user_id: str, proof_session_id: str, version_id: str) -> dict[str, Any]:
        for row in self._versions_for_session(user_id, proof_session_id):
            if str(row.get("id")) == version_id:
                return row
        raise ProofEvidenceVersionNotFoundError(version_id)

    def _active_version_row(self, user_id: str, proof_session_id: str) -> dict[str, Any] | None:
        for row in self._versions_for_session(user_id, proof_session_id):
            if row.get("is_active"):
                return row
        return None

    def _deactivate_versions(self, user_id: str, proof_session_id: str) -> None:
        for row in self._versions_for_session(user_id, proof_session_id):
            if row.get("is_active"):
                row.update({"is_active": False, "updated_at": _now()})
                self._save(row)

    def _row_by_session(self, table: str, user_id: str, proof_session_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            for row in self._client.get(table, {}).values():
                if str(row.get("user_id")) == user_id and str(row.get("proof_session_id")) == proof_session_id:
                    return row
            return None
        result = (
            self._client.table(table)
            .select("*")
            .eq("user_id", user_id)
            .eq("proof_session_id", proof_session_id)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _skill_evidence(self, user_id: str, evidence_id: str) -> dict[str, Any] | None:
        if not evidence_id:
            return None
        if isinstance(self._client, dict):
            row = self._client.get(_SKILL_EVIDENCE, {}).get(evidence_id)
            return row if row and str(row.get("user_id")) == user_id else None
        result = (
            self._client.table(_SKILL_EVIDENCE)
            .select("*")
            .eq("id", evidence_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return getattr(result, "data", None) if result is not None else None

    def _user_email(self, user_id: str) -> str:
        if isinstance(self._client, dict):
            return str((self._client.get(_USERS, {}).get(user_id) or {}).get("email") or "")
        result = self._client.table(_USERS).select("email").eq("id", user_id).maybe_single().execute()
        return str((getattr(result, "data", None) or {}).get("email") or "")

    def _insert(self, row: dict[str, Any]) -> dict[str, Any]:
        if isinstance(self._client, dict):
            self._client.setdefault(_VERSIONS, {})[str(row["id"])] = row
            return row
        result = self._client.table(_VERSIONS).insert(row).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError("proof_evidence_versions insert returned no data.")
        return rows[0]

    def _save(self, row: dict[str, Any]) -> dict[str, Any]:
        if isinstance(self._client, dict):
            self._client.setdefault(_VERSIONS, {})[str(row["id"])] = row
            return row
        result = self._client.table(_VERSIONS).upsert(row).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError("proof_evidence_versions upsert returned no data.")
        return rows[0]


def _version_response(row: dict[str, Any]) -> ProofEvidenceVersionResponse:
    return ProofEvidenceVersionResponse(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        proof_session_id=str(row["proof_session_id"]),
        version_number=int(row["version_number"]),
        version_label=row.get("version_label"),
        status=row.get("status") or "draft",
        change_summary=row.get("change_summary"),
        resubmission_reason=row.get("resubmission_reason"),
        evidence_snapshot=row.get("evidence_snapshot") if isinstance(row.get("evidence_snapshot"), dict) else {},
        analysis_snapshot=row.get("analysis_snapshot") if isinstance(row.get("analysis_snapshot"), dict) else {},
        readiness_score=row.get("readiness_score"),
        ai_domain_review_score=row.get("ai_domain_review_score"),
        project_defense_score=row.get("project_defense_score"),
        privacy_status=row.get("privacy_status"),
        created_from_version_id=str(row["created_from_version_id"]) if row.get("created_from_version_id") else None,
        is_active=bool(row.get("is_active", False)),
        submitted_at=row.get("submitted_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _safe_row(row: dict[str, Any], include_keys: set[str] | None = None) -> dict[str, Any]:
    if include_keys is not None:
        row = {key: row.get(key) for key in include_keys if key in row}
    return _safe_snapshot(row)


def _safe_snapshot(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, nested in value.items():
            if _is_blocked_key(str(key)):
                continue
            out[key] = _safe_snapshot(nested)
        return out
    if isinstance(value, list):
        return [_safe_snapshot(item) for item in value]
    return value


def _is_blocked_key(key: str) -> bool:
    normalized = key.lower()
    return normalized in _BLOCKED_KEYS or any(fragment in normalized for fragment in ("private", "internal", "debug"))


def _website_url(session: dict[str, Any], skill: dict[str, Any] | None) -> str:
    return str(session.get("website_url") or (skill or {}).get("evidence_url") or "")


def _claimed_skills(*rows: dict[str, Any] | None) -> list[str]:
    values: list[str] = []
    for row in rows:
        if not row:
            continue
        for key in ("claimed_skills", "supported_skills", "matched_claimed_skills", "verified_skills", "partially_verified_skills"):
            raw = row.get(key)
            if isinstance(raw, list):
                values.extend(str(v) for v in raw if str(v).strip())
        if row.get("skill_name"):
            values.append(str(row["skill_name"]))
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        raw = metadata.get("claimed_skills") or metadata.get("skills")
        if isinstance(raw, list):
            values.extend(str(v) for v in raw if str(v).strip())
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _nested_int(row: dict[str, Any], parent: str, key: str) -> int | None:
    value = (row.get(parent) if isinstance(row.get(parent), dict) else {}).get(key)
    return int(value) if value is not None else None


def _first_int(row: dict[str, Any], keys: list[str]) -> int | None:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return int(value)
    return None


def _first_text(row: dict[str, Any], keys: list[str]) -> str | None:
    for key in keys:
        value = row.get(key)
        if value:
            return str(value)
    return None


def _now() -> datetime:
    return datetime.now(UTC)
