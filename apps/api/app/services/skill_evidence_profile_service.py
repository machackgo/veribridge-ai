"""Skill Evidence Profile Service.

Groups extension proof evidence records by project (normalized URL) and
computes a clean SkillEvidenceProfile per project. One profile per unique
project URL replaces the repeated per-submission rows shown on the profile
page.

Guardrails:
  — does NOT delete or modify any evidence records
  — does NOT touch GitHub Evidence Analysis (reserved for future)
  — does NOT mark Final Verification complete
  — uses "AI Reviewed", "Workflow Evidence Analysis", "Evidence supports"
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from app.schemas.skill_evidence_profile import (
    EVIDENCE_LEVEL_LABELS,
    EvidenceAttemptSummary,
    EvidenceLevel,
    EvidenceSourceStatus,
    SkillEvidenceProfile,
)
from app.services.canonical_project_evidence import USABLE_WEBSITE_SESSION_STATUSES

logger = logging.getLogger(__name__)

_EVIDENCE_TABLE = "skill_evidence"
_SESSION_TABLE = "extension_proof_sessions"
_ANALYSIS_TABLE = "workflow_analysis_results"

# Evidence types that identify extension proof records.
_EXTENSION_PROOF_EVIDENCE_TYPES = (
    "local development (extension proof)",
    "private website (extension proof)",
)

# Sessions in these states carry an uploaded recording that is still being
# analyzed — they HAVE produced evidence and their stubs stay visible while
# analysis finishes. Anything earlier (created / waiting_for_extension /
# recording) or archived ('expired') has produced no evidence at all.
_EVIDENCE_IN_FLIGHT_STATUSES = frozenset({"uploaded_pending_analysis", "analyzing"})


class SkillEvidenceProfileService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def compute_skill_evidence_profiles(self, user_id: str) -> list[SkillEvidenceProfile]:
        """Return one SkillEvidenceProfile per unique project URL for this user.

        Groups all extension proof evidence by normalized URL, joins sessions
        and analyses, and returns clean per-project profile objects.
        Always returns a list — never raises; on any DB failure returns [].
        """
        logger.info("SKILL_EVIDENCE_PROFILE_START user=%s", user_id)

        evidence_rows = self._fetch_extension_proof_evidence(user_id)
        if not evidence_rows:
            logger.info("SKILL_EVIDENCE_PROFILE_NO_EVIDENCE user=%s", user_id)
            return []

        # Honesty gate: a Website Proof session writes its skill_evidence stub
        # at CREATE time, before any recording is uploaded. A still-pending
        # stub whose owning session never reached a usable (completed) state —
        # abandoned mid-recording, or soft-archived as 'expired' — has produced
        # no evidence and must not surface as an evidence profile.
        evidence_rows = self._filter_unusable_session_stubs(user_id, evidence_rows)
        if not evidence_rows:
            logger.info("SKILL_EVIDENCE_PROFILE_NO_USABLE_EVIDENCE user=%s", user_id)
            return []

        session_ids = [
            r["metadata"]["session_id"]
            for r in evidence_rows
            if isinstance(r.get("metadata"), dict) and r["metadata"].get("session_id")
        ]

        sessions_by_id: dict[str, dict[str, Any]] = {}
        if session_ids:
            sessions_by_id = self._fetch_sessions_by_ids(user_id, session_ids)

        analysis_by_session: dict[str, dict[str, Any]] = {}
        if sessions_by_id:
            analysis_by_session = self._fetch_analyses_by_session_ids(
                user_id, list(sessions_by_id.keys())
            )

        groups = _group_by_project(evidence_rows)

        profiles: list[SkillEvidenceProfile] = []
        for project_key, group_rows in groups.items():
            profile = _build_profile(
                project_key=project_key,
                rows=group_rows,
                sessions_by_id=sessions_by_id,
                analysis_by_session=analysis_by_session,
            )
            profiles.append(profile)

        profiles.sort(key=lambda p: p.last_updated_at, reverse=True)
        logger.info(
            "SKILL_EVIDENCE_PROFILE_COMPLETE user=%s profiles=%d",
            user_id, len(profiles),
        )
        return profiles

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _fetch_extension_proof_evidence(self, user_id: str) -> list[dict[str, Any]]:
        try:
            if isinstance(self._client, dict):
                rows = [
                    r
                    for r in self._client.get(_EVIDENCE_TABLE, {}).values()
                    if r.get("user_id") == user_id
                    and r.get("evidence_type") in _EXTENSION_PROOF_EVIDENCE_TYPES
                ]
                rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
                return rows

            result = (
                self._client.table(_EVIDENCE_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .in_("evidence_type", list(_EXTENSION_PROOF_EVIDENCE_TYPES))
                .order("created_at", desc=True)
                .execute()
            )
            return getattr(result, "data", []) or []
        except Exception:
            logger.warning(
                "SKILL_EVIDENCE_PROFILE_FETCH_EVIDENCE_FAILED user=%s",
                user_id, exc_info=True,
            )
            return []

    def _filter_unusable_session_stubs(
        self, user_id: str, evidence_rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Drop still-pending stubs of sessions that never produced evidence.

        A row is excluded only when ALL of the following hold:
          — its ``verification_status`` is still ``pending_review`` (nothing
            downstream has verified it), AND
          — an owning session is found (via the session's
            ``skill_evidence_id`` backlink, or the row's
            ``metadata.session_id``), AND
          — that session's status is neither usable (``completed``) nor
            evidence-in-flight (uploaded, awaiting analysis) — i.e. the
            recording was abandoned before upload or archived as expired.

        Legacy rows with no discoverable session keep their current behavior.
        """
        sessions = self._fetch_all_sessions(user_id)
        if not sessions:
            return evidence_rows
        session_by_evidence_id = {
            str(s.get("skill_evidence_id") or ""): s
            for s in sessions
            if s.get("skill_evidence_id")
        }
        session_by_id = {str(s.get("id") or ""): s for s in sessions if s.get("id")}

        def _owning_session(row: dict[str, Any]) -> dict[str, Any] | None:
            session = session_by_evidence_id.get(str(row.get("id") or ""))
            if session is not None:
                return session
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            return session_by_id.get(str(meta.get("session_id") or ""))

        kept: list[dict[str, Any]] = []
        for row in evidence_rows:
            if str(row.get("verification_status") or "") == "pending_review":
                session = _owning_session(row)
                if session is not None:
                    status = str(session.get("status") or "").strip().lower()
                    if (
                        status not in USABLE_WEBSITE_SESSION_STATUSES
                        and status not in _EVIDENCE_IN_FLIGHT_STATUSES
                    ):
                        continue
            kept.append(row)
        return kept

    def _fetch_all_sessions(self, user_id: str) -> list[dict[str, Any]]:
        try:
            if isinstance(self._client, dict):
                return [
                    r
                    for r in self._client.get(_SESSION_TABLE, {}).values()
                    if r.get("user_id") == user_id
                ]
            result = (
                self._client.table(_SESSION_TABLE)
                .select("id,skill_evidence_id,status")
                .eq("user_id", user_id)
                .execute()
            )
            return getattr(result, "data", []) or []
        except Exception:
            logger.warning(
                "SKILL_EVIDENCE_PROFILE_FETCH_ALL_SESSIONS_FAILED user=%s",
                user_id, exc_info=True,
            )
            return []

    def _fetch_sessions_by_ids(
        self, user_id: str, session_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        try:
            if isinstance(self._client, dict):
                store = self._client.get(_SESSION_TABLE, {})
                return {
                    r["id"]: r
                    for r in store.values()
                    if r.get("id") in session_ids and r.get("user_id") == user_id
                }

            result = (
                self._client.table(_SESSION_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .in_("id", session_ids)
                .execute()
            )
            rows = getattr(result, "data", []) or []
            return {r["id"]: r for r in rows}
        except Exception:
            logger.warning(
                "SKILL_EVIDENCE_PROFILE_FETCH_SESSIONS_FAILED user=%s",
                user_id, exc_info=True,
            )
            return {}

    def _fetch_analyses_by_session_ids(
        self, user_id: str, session_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        try:
            if isinstance(self._client, dict):
                store = self._client.get(_ANALYSIS_TABLE, {})
                return {
                    r["proof_session_id"]: r
                    for r in store.values()
                    if r.get("proof_session_id") in session_ids
                    and r.get("user_id") == user_id
                }

            result = (
                self._client.table(_ANALYSIS_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .in_("proof_session_id", session_ids)
                .order("created_at", desc=True)
                .execute()
            )
            rows = getattr(result, "data", []) or []
            # Keep only the latest analysis per session.
            by_session: dict[str, dict[str, Any]] = {}
            for r in rows:
                sid = r.get("proof_session_id", "")
                if sid not in by_session:
                    by_session[sid] = r
            return by_session
        except Exception:
            logger.warning(
                "SKILL_EVIDENCE_PROFILE_FETCH_ANALYSES_FAILED user=%s",
                user_id, exc_info=True,
            )
            return {}


# ── Pure grouping/building helpers ───────────────────────────────────────────


def _normalize_project_key(evidence_url: str | None) -> str:
    """Return a stable key for grouping evidence records by project.

    Strips scheme, www prefix, trailing slashes, and lowercases everything
    so that http://www.MyApp.com/ and https://myapp.com both map to the same key.
    Falls back to the raw URL string when parsing fails.
    """
    if not evidence_url:
        return "__no_url__"
    try:
        parsed = urlparse(evidence_url.strip())
        netloc = parsed.netloc.lower().removeprefix("www.")
        path = parsed.path.rstrip("/")
        return f"{netloc}{path}" or evidence_url.lower().strip()
    except Exception:
        return evidence_url.lower().strip()


def _group_by_project(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = _normalize_project_key(row.get("evidence_url") or row.get("url"))
        groups.setdefault(key, []).append(row)
    return groups


def _compute_evidence_level(
    has_session: bool,
    has_analysis: bool,
    has_github: bool = False,
) -> EvidenceLevel:
    if has_analysis:
        if has_github:
            return "multi_source_ai_reviewed"
        return "workflow_analysis_ai_reviewed"
    if has_session:
        return "workflow_evidence_complete"
    return "self_claimed"


def _build_profile(
    project_key: str,
    rows: list[dict[str, Any]],
    sessions_by_id: dict[str, dict[str, Any]],
    analysis_by_session: dict[str, dict[str, Any]],
) -> SkillEvidenceProfile:
    rows_sorted = sorted(rows, key=lambda r: r.get("created_at", ""), reverse=True)
    latest_row = rows_sorted[0]

    evidence_url: str | None = latest_row.get("evidence_url") or latest_row.get("url")
    github_url: str | None = latest_row.get("github_url")
    url_type: str = latest_row.get("url_type") or "invalid_url"
    proof_objective: str | None = latest_row.get("proof_objective")

    all_skill_names = list(
        dict.fromkeys(
            r.get("skill_name") or "" for r in rows_sorted if r.get("skill_name")
        )
    )
    primary_skill_name = all_skill_names[0] if all_skill_names else "Unknown Skill"

    # Gather sessions and analyses for this group.
    session_ids_for_group: list[str] = []
    for r in rows_sorted:
        meta = r.get("metadata") or {}
        sid = meta.get("session_id") if isinstance(meta, dict) else None
        if sid and sid in sessions_by_id:
            session_ids_for_group.append(sid)

    sessions_for_group = [sessions_by_id[sid] for sid in dict.fromkeys(session_ids_for_group)]
    analyses_for_group = [
        analysis_by_session[sid]
        for sid in dict.fromkeys(session_ids_for_group)
        if sid in analysis_by_session
    ]

    has_workflow_proof = bool(sessions_for_group)
    has_workflow_analysis = bool(analyses_for_group)

    latest_session = sessions_for_group[0] if sessions_for_group else None
    latest_analysis = analyses_for_group[0] if analyses_for_group else None

    latest_session_id: str | None = latest_session["id"] if latest_session else None
    latest_session_status: str | None = latest_session.get("status") if latest_session else None

    # Prefer session-stored proof objective / github URL if not on evidence row.
    if not proof_objective and latest_session:
        proof_objective = latest_session.get("proof_objective")
    if not github_url and latest_session:
        github_url = latest_session.get("github_url")

    confidence = "unknown"
    evidence_strength_score: int | None = None
    workflow_analysis_summary: str | None = None
    missing_evidence: list[str] = []

    if latest_analysis:
        confidence = latest_analysis.get("workflow_confidence") or "unknown"
        score = latest_analysis.get("evidence_strength_score")
        evidence_strength_score = int(score) if score is not None else None
        workflow_analysis_summary = latest_analysis.get("recruiter_summary") or latest_analysis.get("workflow_summary")
        missing_evidence = latest_analysis.get("missing_evidence") or []

    evidence_level = _compute_evidence_level(
        has_session=has_workflow_proof,
        has_analysis=has_workflow_analysis,
        has_github=False,
    )

    evidence_sources = _build_evidence_sources(
        has_workflow_proof=has_workflow_proof,
        has_workflow_analysis=has_workflow_analysis,
    )

    history = _build_history(rows_sorted, sessions_by_id, analysis_by_session)

    first_submitted = rows_sorted[-1].get("created_at") or ""
    last_updated = rows_sorted[0].get("updated_at") or rows_sorted[0].get("created_at") or ""

    if latest_session:
        session_updated = latest_session.get("updated_at") or latest_session.get("created_at") or ""
        if session_updated > last_updated:
            last_updated = session_updated

    return SkillEvidenceProfile(
        profile_id=project_key,
        primary_skill_name=primary_skill_name,
        all_skill_names=all_skill_names,
        proof_objective=proof_objective,
        evidence_url=evidence_url,
        github_url=github_url,
        url_type=url_type,
        evidence_level=evidence_level,
        evidence_level_label=EVIDENCE_LEVEL_LABELS[evidence_level],
        has_workflow_proof=has_workflow_proof,
        has_workflow_analysis=has_workflow_analysis,
        has_github_evidence=False,
        confidence=confidence,
        evidence_strength_score=evidence_strength_score,
        workflow_analysis_summary=workflow_analysis_summary,
        latest_session_id=latest_session_id,
        latest_session_status=latest_session_status,
        evidence_sources=evidence_sources,
        missing_evidence=missing_evidence,
        submission_count=len(rows_sorted),
        first_submitted_at=first_submitted,
        last_updated_at=last_updated,
        history=history,
    )


def _build_evidence_sources(
    has_workflow_proof: bool,
    has_workflow_analysis: bool,
) -> list[EvidenceSourceStatus]:
    return [
        EvidenceSourceStatus(
            key="self_claimed",
            label="Self Claimed",
            status="complete",
        ),
        EvidenceSourceStatus(
            key="workflow_recording",
            label="Workflow Recording",
            status="complete" if has_workflow_proof else "pending",
        ),
        EvidenceSourceStatus(
            key="workflow_analysis",
            label="Workflow Analysis — AI Reviewed",
            status="complete" if has_workflow_analysis else "pending",
        ),
        EvidenceSourceStatus(
            key="github_evidence",
            label="GitHub Code Evidence",
            status="unavailable",
        ),
        EvidenceSourceStatus(
            key="final_verification",
            label="Final Verification",
            status="unavailable",
        ),
    ]


def _build_history(
    rows_sorted: list[dict[str, Any]],
    sessions_by_id: dict[str, dict[str, Any]],
    analysis_by_session: dict[str, dict[str, Any]],
) -> list[EvidenceAttemptSummary]:
    history: list[EvidenceAttemptSummary] = []
    for row in rows_sorted:
        meta = row.get("metadata") or {}
        sid = meta.get("session_id") if isinstance(meta, dict) else None
        session = sessions_by_id.get(sid) if sid else None
        has_analysis = bool(sid and sid in analysis_by_session)
        history.append(
            EvidenceAttemptSummary(
                evidence_id=str(row.get("id", "")),
                session_id=session["id"] if session else None,
                session_status=session.get("status") if session else None,
                has_analysis=has_analysis,
                skill_name=row.get("skill_name") or "Unknown",
                submitted_at=row.get("created_at") or "",
            )
        )
    return history
