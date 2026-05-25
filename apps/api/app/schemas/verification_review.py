"""Pydantic schemas for the Verification Review workflow.

Track A — AI Review MVP:
  Statuses: not_submitted → submitted_for_ai_review → ai_review_in_progress
            → ai_approved_for_sharing | needs_more_evidence
               | manual_review_recommended | privacy_flagged

Track B — Human / Faculty / Expert Review (architecture-ready, MVP placeholders):
  Statuses: human_review_not_requested → human_review_requested
            → faculty_review_pending | company_review_pending
               | domain_expert_review_pending
            → faculty_reviewed | company_reviewed | domain_expert_reviewed
               | human_verified | human_review_rejected

Wording rules enforced here:
  - "human_verified" is ONLY set when an actual human approved the submission.
  - AI review NEVER sets human_verified.
  - "ai_approved_for_sharing" is the correct label for MVP AI approval.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ── Status type aliases ───────────────────────────────────────────────────────

AiReviewStatus = Literal[
    "not_submitted",
    "submitted_for_ai_review",
    "ai_review_in_progress",
    "ai_approved_for_sharing",
    "needs_more_evidence",
    "manual_review_recommended",
    "privacy_flagged",
]

HumanReviewStatus = Literal[
    "human_review_not_requested",
    "human_review_requested",
    "faculty_review_pending",
    "company_review_pending",
    "domain_expert_review_pending",
    "faculty_reviewed",
    "company_reviewed",
    "domain_expert_reviewed",
    "human_verified",
    "human_review_rejected",
]

ReviewerRole = Literal[
    "veribridge_admin",
    "faculty_reviewer",
    "company_reviewer",
    "domain_expert",
    "recruiter_reviewer",
]

ReviewerDecision = Literal["approved", "rejected", "needs_revision", "escalate"]

AssignmentStatus = Literal[
    "pending", "accepted", "declined", "completed", "withdrawn"
]

ReadinessLevel = Literal["strong", "moderate", "weak", "insufficient"]


# ── Request schemas ───────────────────────────────────────────────────────────


class SubmitAiReviewRequest(BaseModel):
    """Body for POST .../submit-ai-review.

    The student submits their proof session for AI review.  The backend
    reads the current readiness score and privacy scan from existing data;
    the frontend does not need to send them.
    """

    pass  # no body fields needed; session_id in path, user from JWT


class AdminDecisionRequest(BaseModel):
    """Admin manually overrides the AI review decision."""

    ai_review_status: AiReviewStatus = Field(
        ...,
        description=(
            "Target AI review status.  Admin may set "
            "ai_approved_for_sharing, needs_more_evidence, or privacy_flagged."
        ),
    )
    ai_decision_summary: str = Field(
        default="",
        max_length=2000,
        description="Optional admin note explaining the decision.",
    )


# ── Response schemas ──────────────────────────────────────────────────────────


class HumanReviewAssignmentResponse(BaseModel):
    """Read-only summary of one human reviewer assignment.

    IMPORTANT: reviewer_decision is only present when status=completed.
    Do NOT surface this as "Human Verified" in recruiter UI unless
    reviewer_decision == 'approved'.
    """

    id: str
    review_request_id: str
    reviewer_name: str
    reviewer_role: ReviewerRole
    reviewer_field: str
    status: AssignmentStatus
    assigned_at: datetime
    completed_at: Optional[datetime] = None
    reviewer_decision: Optional[ReviewerDecision] = None
    # reviewer_notes intentionally omitted from this response — admin-only field
    verified_skills: list[str] = Field(default_factory=list)
    requested_improvements: list[str] = Field(default_factory=list)


class VerificationReviewResponse(BaseModel):
    """Full review status for one proof session.

    This is the primary response for GET .../review-status and
    POST .../submit-ai-review.

    Wording guarantees:
      - ai_approved_for_sharing → student badge shows "VeriBridge AI Reviewed"
      - human_verified → ONLY when an actual human approved; never set by AI review
      - faculty_reviewed, company_reviewed, domain_expert_reviewed → only when
        actual reviewer with that role completed their review
    """

    id: str
    proof_session_id: str
    user_id: str

    # Track A
    ai_review_status: AiReviewStatus
    ai_review_started_at: Optional[datetime] = None
    ai_review_completed_at: Optional[datetime] = None
    ai_decision_summary: str

    # Track B
    human_review_status: HumanReviewStatus
    human_review_requested_at: Optional[datetime] = None

    # Readiness snapshot at submission time
    readiness_score: int
    readiness_level: ReadinessLevel

    # Lifecycle
    submitted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    # Human reviewer assignments (empty in MVP)
    assignments: list[HumanReviewAssignmentResponse] = Field(default_factory=list)

    # Derived display helpers
    @property
    def display_ai_label(self) -> str:
        """Human-readable label for the AI review status."""
        _labels: dict[str, str] = {
            "not_submitted": "Not Submitted",
            "submitted_for_ai_review": "Submitted for AI Review",
            "ai_review_in_progress": "AI Review In Progress",
            "ai_approved_for_sharing": "VeriBridge AI Reviewed — Approved for Sharing",
            "needs_more_evidence": "Needs More Evidence",
            "manual_review_recommended": "Manual Review Recommended",
            "privacy_flagged": "Privacy Flag — Review Paused",
        }
        return _labels.get(self.ai_review_status, self.ai_review_status)

    @property
    def display_human_label(self) -> str:
        """Human-readable label for the human review status."""
        _labels: dict[str, str] = {
            "human_review_not_requested": "Human Review Not Requested",
            "human_review_requested": "Human Review Requested",
            "faculty_review_pending": "Faculty Review Pending",
            "company_review_pending": "Company / Mentor Review Pending",
            "domain_expert_review_pending": "Domain Expert Review Pending",
            "faculty_reviewed": "Faculty Reviewed",
            "company_reviewed": "Company / Mentor Reviewed",
            "domain_expert_reviewed": "Domain Expert Reviewed",
            "human_verified": "Human Verified",
            "human_review_rejected": "Human Review — Rejected",
        }
        return _labels.get(self.human_review_status, self.human_review_status)


# ── Admin list response ───────────────────────────────────────────────────────


class AdminReviewListItem(BaseModel):
    """Lightweight item for admin review queue list."""

    id: str
    proof_session_id: str
    user_id: str
    ai_review_status: AiReviewStatus
    human_review_status: HumanReviewStatus
    readiness_score: int
    readiness_level: ReadinessLevel
    submitted_at: Optional[datetime] = None
    ai_review_completed_at: Optional[datetime] = None
    ai_decision_summary: str
    created_at: datetime
    updated_at: datetime
