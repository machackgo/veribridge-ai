"""Verification Review Service — AI review workflow + human reviewer architecture.

Track A (MVP):
  Student submits proof session for AI review.  The service:
    1. Creates a review request row (prevents duplicates).
    2. Reads the current readiness score + privacy scan.
    3. Applies the decision rules and sets ai_review_status.

Decision rules:
  - readiness_score >= 80 AND privacy is clean/redacted
      → ai_approved_for_sharing
  - readiness_score >= 60 AND privacy is clean/redacted
      → manual_review_recommended
  - privacy flagged
      → privacy_flagged
  - otherwise
      → needs_more_evidence

IMPORTANT:
  - human_verified is NEVER set by AI review.
  - ai_approved_for_sharing does NOT mean "Human Verified".
  - The human review track (Track B) is stored in the same row but
    requires an actual human reviewer action to progress.

Track B (architecture-ready, MVP: table exists, no reviewers yet):
  human_review_assignments is created by admin endpoints.
  Students can request human review (sets human_review_requested).
  Actual review completion is done by a future reviewer program.
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

_TABLE = "verification_review_requests"
_ASSIGNMENTS_TABLE = "human_review_assignments"

# ── In-memory key helpers ────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


def _make_review_response(
    row: dict[str, Any],
    assignments: list[dict[str, Any]] | None = None,
) -> VerificationReviewResponse:
    """Convert a DB row dict to the public response schema."""
    assignment_responses = []
    for a in (assignments or []):
        assignment_responses.append(
            HumanReviewAssignmentResponse(
                id=str(a["id"]),
                review_request_id=str(a["review_request_id"]),
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
        ai_review_status=row.get("ai_review_status", "not_submitted"),
        ai_review_started_at=row.get("ai_review_started_at"),
        ai_review_completed_at=row.get("ai_review_completed_at"),
        ai_decision_summary=str(row.get("ai_decision_summary") or ""),
        human_review_status=row.get("human_review_status", "human_review_not_requested"),
        human_review_requested_at=row.get("human_review_requested_at"),
        readiness_score=int(row.get("readiness_score") or 0),
        readiness_level=row.get("readiness_level", "insufficient"),
        submitted_at=row.get("submitted_at"),
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
    """Handles verification review requests for proof sessions."""

    def __init__(self, client: Any) -> None:
        self._client = client

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_row(self, user_id: str, session_id: str) -> dict[str, Any]:
        """Fetch the review request row; raise VerificationReviewNotFoundError if absent."""
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
            .execute()
        )
        rows = getattr(result, "data", []) or []
        if not rows:
            raise VerificationReviewNotFoundError(
                f"No review request for session {session_id}"
            )
        return rows[0]

    def _get_assignments(self, review_request_id: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            return [
                a
                for a in self._client.get(_ASSIGNMENTS_TABLE, {}).values()
                if str(a.get("review_request_id")) == review_request_id
            ]

        result = (
            self._client.table(_ASSIGNMENTS_TABLE)
            .select("*")
            .eq("review_request_id", review_request_id)
            .execute()
        )
        return getattr(result, "data", []) or []

    def _read_privacy_status(self, user_id: str, session_id: str) -> str | None:
        """Read the privacy scan status from existing data.  Non-fatal if absent."""
        _PRIVACY_TABLE = "workflow_privacy_scan_results"
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
        """Create (or re-use) a review request and run the AI decision.

        Idempotent: if a request already exists and is not_submitted or
        needs_more_evidence (re-submission allowed), it updates in place.
        Raises VerificationReviewDuplicateError if already approved/in-flight.
        """
        now = _now()
        privacy_status = self._read_privacy_status(user_id, session_id)
        ai_status, ai_summary = _apply_ai_decision(
            readiness_score, readiness_level, privacy_status
        )

        # Check for existing request
        existing: dict[str, Any] | None = None
        try:
            existing = self._get_row(user_id, session_id)
        except VerificationReviewNotFoundError:
            pass

        if existing is not None:
            current_status = existing.get("ai_review_status", "not_submitted")
            # Block re-submission if already approved or in-flight
            if current_status in (
                "submitted_for_ai_review",
                "ai_review_in_progress",
                "ai_approved_for_sharing",
            ):
                raise VerificationReviewDuplicateError(
                    f"Review already {current_status} — cannot resubmit."
                )

            # Re-submission allowed (was needs_more_evidence / manual_review_recommended / privacy_flagged)
            updates = {
                "ai_review_status": ai_status,
                "ai_review_started_at": now,
                "ai_review_completed_at": now,
                "ai_decision_summary": ai_summary,
                "readiness_score": readiness_score,
                "readiness_level": readiness_level,
                "submitted_at": existing.get("submitted_at") or now,
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
            # Create new review request
            data: dict[str, Any] = {
                "user_id": user_id,
                "proof_session_id": session_id,
                "ai_review_status": ai_status,
                "ai_review_started_at": now,
                "ai_review_completed_at": now,
                "ai_decision_summary": ai_summary,
                "human_review_status": "human_review_not_requested",
                "readiness_score": readiness_score,
                "readiness_level": readiness_level,
                "submitted_at": now,
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
                    raise RuntimeError("Review request insert returned no data.")
                row = rows[0]

        assignments = self._get_assignments(str(row["id"]))
        return _make_review_response(row, assignments)

    # ── Student: get review status ─────────────────────────────────────────────

    def get_review_status(
        self, user_id: str, session_id: str
    ) -> VerificationReviewResponse:
        """Return the current review status for the session.

        Raises VerificationReviewNotFoundError if no request exists yet.
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
        """Return all review requests (admin only, no user_id filter)."""
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

        return [
            AdminReviewListItem(
                id=str(r["id"]),
                proof_session_id=str(r["proof_session_id"]),
                user_id=str(r["user_id"]),
                ai_review_status=r.get("ai_review_status", "not_submitted"),
                human_review_status=r.get("human_review_status", "human_review_not_requested"),
                readiness_score=int(r.get("readiness_score") or 0),
                readiness_level=r.get("readiness_level", "insufficient"),
                submitted_at=r.get("submitted_at"),
                ai_review_completed_at=r.get("ai_review_completed_at"),
                ai_decision_summary=str(r.get("ai_decision_summary") or ""),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    # ── Admin: manual decision override ──────────────────────────────────────

    def admin_set_decision(
        self,
        review_id: str,
        body: AdminDecisionRequest,
    ) -> VerificationReviewResponse:
        """Admin manually overrides the AI review status.

        IMPORTANT: This does NOT set human_review_status = human_verified.
        That requires a human reviewer action in human_review_assignments.
        """
        now = _now()

        if isinstance(self._client, dict):
            row: dict[str, Any] | None = self._client.get(_TABLE, {}).get(review_id)
            if row is None:
                raise VerificationReviewNotFoundError(
                    f"Review request {review_id} not found."
                )
            row.update(
                {
                    "ai_review_status": body.ai_review_status,
                    "ai_decision_summary": body.ai_decision_summary,
                    "ai_review_completed_at": now,
                    "updated_at": now,
                }
            )
        else:
            result = (
                self._client.table(_TABLE)
                .update(
                    {
                        "ai_review_status": body.ai_review_status,
                        "ai_decision_summary": body.ai_decision_summary,
                        "ai_review_completed_at": now,
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

        if isinstance(self._client, dict):
            row = self._client[_TABLE][review_id]

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
        """Create a human_review_assignments row (MVP: always invited, not yet active).

        This method exists to support the future reviewer program architecture.
        In MVP, this will create the row but no real email is sent.
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
