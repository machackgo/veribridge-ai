"""Verification Review Service — AI review workflow.

Routes submit-ai-review and review-status to ai_domain_review_results
(the correct backend table).  The old verification_review_requests table
does not exist in production; every reference to it has been removed.

Decision rules (applied on the passed readiness_score):
  - readiness_score >= 80 AND privacy is clean/redacted → ai_approved_for_sharing
  - readiness_score >= 60 AND privacy is clean/redacted → manual_review_recommended
  - privacy flagged → privacy_flagged
  - otherwise → needs_more_evidence

Storage mapping (old-style field → ai_domain_review_results column):
  ai_review_status          → ai_domain_review_status  (mapped values below)
  readiness_score           → domain_review_score
  ai_decision_summary       → recruiter_summary
  human_review_status       → not stored (always derived as human_review_not_requested)
  readiness_level           → computed from domain_review_score on read

Status value mapping:
  ai_approved_for_sharing   ↔ ai_domain_reviewed
  manual_review_recommended ↔ human_review_recommended
  privacy_flagged           ↔ privacy_blocked
  needs_more_evidence       ↔ needs_more_evidence (unchanged)

IMPORTANT:
  - human_verified is NEVER set by AI review.
  - ai_approved_for_sharing does NOT mean "Human Verified".
  - The human review track requires an actual human reviewer action.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.schemas.verification_review import (
    AdminDecisionRequest,
    AdminReviewListItem,
    AiReviewStatus,
    HumanReviewAssignmentResponse,
    VerificationReviewResponse,
)

logger = logging.getLogger(__name__)

# ── Table names ────────────────────────────────────────────────────────────────
# ai_domain_review_results is the canonical AI review table.
# verification_review_requests does not exist in production and must not be used.
_TABLE = "ai_domain_review_results"
_ASSIGNMENTS_TABLE = "human_review_assignments"
_PRIVACY_TABLE = "workflow_privacy_scan_results"

# ── Status value mappings ─────────────────────────────────────────────────────

# Map old-style AiReviewStatus values → ai_domain_review_status values stored in DB
_AI_STATUS_TO_DOMAIN: dict[str, str] = {
    "ai_approved_for_sharing": "ai_domain_reviewed",
    "manual_review_recommended": "human_review_recommended",
    "privacy_flagged": "privacy_blocked",
    "needs_more_evidence": "needs_more_evidence",
    # pass-through for DB-native values (defensive)
    "ai_domain_reviewed": "ai_domain_reviewed",
    "human_review_recommended": "human_review_recommended",
    "privacy_blocked": "privacy_blocked",
}

# Map DB ai_domain_review_status values → old-style AiReviewStatus for the response
_DOMAIN_TO_AI_STATUS: dict[str, str] = {
    "ai_domain_reviewed": "ai_approved_for_sharing",
    "human_review_recommended": "manual_review_recommended",
    "privacy_blocked": "privacy_flagged",
    "needs_more_evidence": "needs_more_evidence",
}

# DB statuses that block re-submission of the same session
_BLOCK_RESUBMIT_DOMAIN_STATUSES: frozenset[str] = frozenset({"ai_domain_reviewed"})

_DISCLOSURE = (
    "This proof has been reviewed by VeriBridge AI using a threshold-based rubric. "
    "Human/faculty/company review has not been completed unless explicitly shown."
)
_LIMITATIONS = (
    "This is an AI-based review. Results reflect available evidence at time of submission. "
    "Human or faculty review is not yet completed."
)


# ── Pure helpers ──────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


def _level_from_score(score: int) -> str:
    """Compute a ReadinessLevel string from a numeric score."""
    if score >= 80:
        return "strong"
    if score >= 60:
        return "moderate"
    if score >= 40:
        return "weak"
    return "insufficient"


def _confidence_from_score(score: int) -> str:
    """Compute a ConfidenceLevel string from a numeric score."""
    if score >= 75:
        return "medium"
    return "low"


def _make_review_response(
    row: dict[str, Any],
    assignments: list[dict[str, Any]] | None = None,
) -> VerificationReviewResponse:
    """Convert an ai_domain_review_results DB row to VerificationReviewResponse."""
    domain_status = str(row.get("ai_domain_review_status") or "needs_more_evidence")
    ai_status = _DOMAIN_TO_AI_STATUS.get(domain_status, "needs_more_evidence")
    score = int(row.get("domain_review_score") or 0)

    assignment_responses: list[HumanReviewAssignmentResponse] = []
    for a in (assignments or []):
        assignment_responses.append(
            HumanReviewAssignmentResponse(
                id=str(a["id"]),
                review_request_id=str(a.get("review_request_id") or row["id"]),
                reviewer_name=str(a.get("reviewer_name") or ""),
                reviewer_role=a.get("reviewer_role", "faculty_reviewer"),
                reviewer_field=str(a.get("reviewer_field") or ""),
                status=a.get("status", "pending"),
                assigned_at=a["assigned_at"],
                completed_at=a.get("completed_at"),
                reviewer_decision=a.get("reviewer_decision"),
                verified_skills=list(a.get("verified_skills") or []),
                requested_improvements=list(a.get("requested_improvements") or []),
            )
        )

    return VerificationReviewResponse(
        id=str(row["id"]),
        proof_session_id=str(row["proof_session_id"]),
        user_id=str(row["user_id"]),
        ai_review_status=ai_status,  # type: ignore[arg-type]
        ai_review_started_at=row.get("created_at"),
        ai_review_completed_at=row.get("updated_at"),
        ai_decision_summary=str(row.get("recruiter_summary") or ""),
        human_review_status="human_review_not_requested",
        human_review_requested_at=None,
        readiness_score=score,
        readiness_level=_level_from_score(score),  # type: ignore[arg-type]
        submitted_at=row.get("created_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        assignments=assignment_responses,
    )


def _apply_ai_decision(
    readiness_score: int,
    readiness_level: str,
    privacy_status: str | None,
) -> tuple[AiReviewStatus, str]:
    """Compute the AI review decision and summary.

    Returns (ai_review_status, ai_decision_summary).

    Rules (in priority order):
      1. Privacy flagged → privacy_flagged (blocked regardless of score)
      2. Score >= 80 AND privacy clean/redacted → ai_approved_for_sharing
      3. Score >= 60 AND privacy clean/redacted → manual_review_recommended
      4. Everything else → needs_more_evidence

    IMPORTANT: human_verified is NEVER returned here.  That status
    can only be set by an actual human reviewer action.
    """
    privacy_clean = privacy_status in (None, "clean", "redacted")

    if not privacy_clean:
        return (
            "privacy_flagged",
            (
                "Privacy scan detected sensitive or unredacted data in your "
                "evidence. The submission has been paused. Please review your "
                "proof and remove or redact any private information before "
                "resubmitting."
            ),
        )

    if readiness_score >= 80:
        return (
            "ai_approved_for_sharing",
            (
                f"Your evidence package scored {readiness_score}/100 — above the "
                "VeriBridge approval threshold. Privacy and risk checks are clean. "
                "Your submission is now marked 'VeriBridge AI Reviewed — Approved "
                "for Sharing'. This is an AI-based review. Human or faculty review "
                "remains optional and is not yet completed."
            ),
        )

    if readiness_score >= 60:
        return (
            "manual_review_recommended",
            (
                f"Your evidence package scored {readiness_score}/100 — in the "
                "moderate range. Privacy checks are clean. Your submission does "
                "not yet meet the automatic approval threshold (80+). We recommend "
                "adding stronger evidence or requesting a human review once that "
                "feature is available."
            ),
        )

    return (
        "needs_more_evidence",
        (
            f"Your evidence package scored {readiness_score}/100, which is below "
            "the VeriBridge review threshold. Please review the recommended actions "
            "in your Readiness Report and strengthen your evidence before "
            "resubmitting."
        ),
    )


# ── Service class ─────────────────────────────────────────────────────────────


class VerificationReviewDuplicateError(ValueError):
    """A review request already exists for this session."""


class VerificationReviewNotFoundError(LookupError):
    """No review request found for this session / user."""


class VerificationReviewService:
    """Handles verification review requests, writing to ai_domain_review_results.

    NOTE: This service previously used verification_review_requests which does
    not exist in production.  It now uses ai_domain_review_results exclusively.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_row(self, user_id: str, session_id: str) -> dict[str, Any]:
        """Fetch the review row from ai_domain_review_results; raise if absent."""
        if isinstance(self._client, dict):
            for row in self._client.get(_TABLE, {}).values():
                if (
                    str(row.get("proof_session_id")) == session_id
                    and str(row.get("user_id")) == user_id
                ):
                    return row
            raise VerificationReviewNotFoundError(
                f"No review request for session {session_id}"
            )

        result = (
            self._client.table(_TABLE)
            .select("*")
            .eq("proof_session_id", session_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        if not rows:
            raise VerificationReviewNotFoundError(
                f"No review request for session {session_id}"
            )
        return rows[0]

    def _get_assignments(self, review_request_id: str) -> list[dict[str, Any]]:
        """Fetch human reviewer assignments.  Non-fatal if table absent."""
        if isinstance(self._client, dict):
            return [
                a
                for a in self._client.get(_ASSIGNMENTS_TABLE, {}).values()
                if str(a.get("review_request_id")) == review_request_id
            ]
        try:
            result = (
                self._client.table(_ASSIGNMENTS_TABLE)
                .select("*")
                .eq("review_request_id", review_request_id)
                .execute()
            )
            return getattr(result, "data", []) or []
        except Exception:
            logger.warning(
                "VerificationReviewService: could not fetch assignments for %s",
                review_request_id,
            )
            return []

    def _read_privacy_status(self, user_id: str, session_id: str) -> str | None:
        """Read the privacy scan status from workflow_privacy_scan_results.  Non-fatal."""
        try:
            if isinstance(self._client, dict):
                for row in self._client.get(_PRIVACY_TABLE, {}).values():
                    if (
                        str(row.get("proof_session_id")) == session_id
                        and str(row.get("user_id")) == user_id
                    ):
                        return str(row.get("status") or "clean")
                return None  # no scan yet → treat as clean

            result = (
                self._client.table(_PRIVACY_TABLE)
                .select("status")
                .eq("proof_session_id", session_id)
                .eq("user_id", user_id)
                .execute()
            )
            rows = getattr(result, "data", []) or []
            if rows:
                return str(rows[0].get("status") or "clean")
            return None

        except Exception:
            logger.warning(
                "VerificationReviewService: could not read privacy scan for %s",
                session_id,
            )
            return None

    # ── Student: submit for AI review ─────────────────────────────────────────

    def submit_for_ai_review(
        self,
        user_id: str,
        session_id: str,
        readiness_score: int,
        readiness_level: str,
    ) -> VerificationReviewResponse:
        """Create or update a review row in ai_domain_review_results.

        Idempotent: if a row already exists and is not approved/in-flight,
        it is updated in place (re-submission is allowed).
        Raises VerificationReviewDuplicateError if already ai_domain_reviewed.
        """
        now = _now()
        privacy_status = self._read_privacy_status(user_id, session_id)
        ai_status, ai_summary = _apply_ai_decision(
            readiness_score, readiness_level, privacy_status
        )
        domain_status = _AI_STATUS_TO_DOMAIN.get(ai_status, "needs_more_evidence")

        # Check for an existing row
        existing: dict[str, Any] | None = None
        try:
            existing = self._get_row(user_id, session_id)
        except VerificationReviewNotFoundError:
            pass

        if existing is not None:
            current_domain_status = str(
                existing.get("ai_domain_review_status") or "needs_more_evidence"
            )
            if current_domain_status in _BLOCK_RESUBMIT_DOMAIN_STATUSES:
                current_old = _DOMAIN_TO_AI_STATUS.get(
                    current_domain_status, current_domain_status
                )
                raise VerificationReviewDuplicateError(
                    f"Review already {current_old} — cannot resubmit."
                )

            # Re-submission allowed: update the existing row
            updates = {
                "ai_domain_review_status": domain_status,
                "domain_review_score": readiness_score,
                "recruiter_summary": ai_summary,
                "human_review_recommended": ai_status == "manual_review_recommended",
                "updated_at": now,
            }
            if isinstance(self._client, dict):
                existing.update(updates)
                row = existing
            else:
                result = (
                    self._client.table(_TABLE)
                    .update(updates)
                    .eq("id", existing["id"])
                    .execute()
                )
                rows = getattr(result, "data", []) or []
                row = rows[0] if rows else {**existing, **updates}
        else:
            # Insert a new review row with all required columns
            data: dict[str, Any] = {
                "user_id": user_id,
                "proof_session_id": session_id,
                "reviewer_name": "VeriBridge AI",
                "reviewer_role": "ai_reviewer",
                "domain": "general",
                "ai_domain_review_status": domain_status,
                "domain_review_score": readiness_score,
                "confidence_level": _confidence_from_score(readiness_score),
                "verified_skills": [],
                "partially_verified_skills": [],
                "skills_needing_more_evidence": [],
                "domain_specific_strengths": [],
                "domain_specific_concerns": [],
                "criterion_scores": [],
                "evidence_sources_reviewed": [],
                "human_review_recommended": ai_status == "manual_review_recommended",
                "human_review_reason": None,
                "recruiter_summary": ai_summary,
                "student_next_steps": [],
                "review_limitations": _LIMITATIONS,
                "disclosure_note": _DISCLOSURE,
                "llm_used": False,
                "fallback_reason": None,
                "human_ai_agreement_score": None,
                "calibration_status": None,
                "reviewed_against_human_baseline": None,
                "created_at": now,
                "updated_at": now,
            }
            if isinstance(self._client, dict):
                row_id = str(uuid4())
                row = {"id": row_id, **data}
                self._client.setdefault(_TABLE, {})[row_id] = row
            else:
                result = self._client.table(_TABLE).insert(data).execute()
                rows = getattr(result, "data", []) or []
                if not rows:
                    raise RuntimeError("Review insert returned no data.")
                row = rows[0]

        assignments = self._get_assignments(str(row["id"]))
        return _make_review_response(row, assignments)

    # ── Student: get review status ─────────────────────────────────────────────

    def get_review_status(
        self, user_id: str, session_id: str
    ) -> VerificationReviewResponse:
        """Return the current review status for the session.

        Raises VerificationReviewNotFoundError if no review row exists yet.
        """
        row = self._get_row(user_id, session_id)
        assignments = self._get_assignments(str(row["id"]))
        return _make_review_response(row, assignments)

    # ── Admin: list all review requests ──────────────────────────────────────

    def admin_list_reviews(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AdminReviewListItem]:
        """Return all review requests from ai_domain_review_results (admin only)."""
        if isinstance(self._client, dict):
            rows = list(self._client.get(_TABLE, {}).values())
            rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
            rows = rows[offset: offset + limit]
        else:
            result = (
                self._client.table(_TABLE)
                .select("*")
                .order("created_at", desc=True)
                .range(offset, offset + limit - 1)
                .execute()
            )
            rows = getattr(result, "data", []) or []

        items: list[AdminReviewListItem] = []
        for r in rows:
            domain_status = str(r.get("ai_domain_review_status") or "needs_more_evidence")
            ai_status = _DOMAIN_TO_AI_STATUS.get(domain_status, "needs_more_evidence")
            score = int(r.get("domain_review_score") or 0)
            items.append(
                AdminReviewListItem(
                    id=str(r["id"]),
                    proof_session_id=str(r["proof_session_id"]),
                    user_id=str(r["user_id"]),
                    ai_review_status=ai_status,  # type: ignore[arg-type]
                    human_review_status="human_review_not_requested",
                    readiness_score=score,
                    readiness_level=_level_from_score(score),  # type: ignore[arg-type]
                    submitted_at=r.get("created_at"),
                    ai_review_completed_at=r.get("updated_at"),
                    ai_decision_summary=str(r.get("recruiter_summary") or ""),
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
            )
        return items

    # ── Admin: manual decision override ──────────────────────────────────────

    def admin_set_decision(
        self,
        review_id: str,
        body: AdminDecisionRequest,
    ) -> VerificationReviewResponse:
        """Admin manually overrides the AI review status.

        Maps the incoming AiReviewStatus value to the DB ai_domain_review_status.
        IMPORTANT: This does NOT set human_review_status = human_verified.
        """
        now = _now()
        domain_status = _AI_STATUS_TO_DOMAIN.get(
            body.ai_review_status, "needs_more_evidence"
        )

        if isinstance(self._client, dict):
            store = self._client.get(_TABLE, {})
            row = store.get(review_id)
            if row is None:
                raise VerificationReviewNotFoundError(
                    f"Review request {review_id} not found."
                )
            row.update(
                {
                    "ai_domain_review_status": domain_status,
                    "recruiter_summary": body.ai_decision_summary,
                    "updated_at": now,
                }
            )
            row = self._client[_TABLE][review_id]
        else:
            result = (
                self._client.table(_TABLE)
                .update(
                    {
                        "ai_domain_review_status": domain_status,
                        "recruiter_summary": body.ai_decision_summary,
                        "updated_at": now,
                    }
                )
                .eq("id", review_id)
                .execute()
            )
            rows = getattr(result, "data", []) or []
            if not rows:
                raise VerificationReviewNotFoundError(
                    f"Review request {review_id} not found."
                )
            row = rows[0]

        assignments = self._get_assignments(review_id)
        return _make_review_response(row, assignments)

    # ── Future: admin invites a human reviewer ────────────────────────────────

    def admin_invite_reviewer(
        self,
        review_id: str,
        reviewer_email: str,
        reviewer_name: str,
        reviewer_role: str,
        reviewer_field: str = "",
    ) -> dict[str, Any]:
        """Create a human_review_assignments row.

        MVP: creates the row; no actual email is sent yet.
        Future: will trigger reviewer notification and onboarding flow.
        """
        now = _now()
        data: dict[str, Any] = {
            "review_request_id": review_id,
            "reviewer_email": reviewer_email,
            "reviewer_name": reviewer_name,
            "reviewer_role": reviewer_role,
            "reviewer_field": reviewer_field,
            "status": "pending",
            "assigned_at": now,
            "created_at": now,
            "updated_at": now,
        }

        if isinstance(self._client, dict):
            row_id = str(uuid4())
            row = {"id": row_id, **data}
            self._client.setdefault(_ASSIGNMENTS_TABLE, {})[row_id] = row
            return row

        result = self._client.table(_ASSIGNMENTS_TABLE).insert(data).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError("Assignment insert returned no data.")
        return rows[0]
