"""Schemas for the Verification Readiness Report."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class VerificationReadinessReport(BaseModel):
    """
    Computed readiness report for a proof session.

    Summarises evidence strength, skill support, risk flags, and
    recommends the next actions to improve recruiter readiness.

    NOTE: ``final_verification_status`` can only be "pending" or
    "ready_for_review".  It is NEVER set to "complete" by this feature —
    Final Verification completion requires a separate VeriBridge reviewer step.
    """

    proof_session_id: str
    readiness_score: int = Field(ge=0, le=100, description="0–100 readiness score")
    readiness_level: Literal["strong", "moderate", "weak", "insufficient"]
    final_verification_status: Literal["pending", "ready_for_review"]

    strongly_supported_skills: list[str] = Field(default_factory=list)
    partially_supported_skills: list[str] = Field(default_factory=list)
    needs_more_evidence: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    recommended_next_actions: list[str] = Field(default_factory=list)

    recruiter_summary: str = ""
    is_local_only: bool = False
    has_github_evidence: bool = False
    computed_at: str = ""

    # ── Personalized recommendations ──────────────────────────────────────
    score_contributors: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Per-contributor breakdown of the score. "
            "Each entry: {label, points, type} where type is "
            "'positive' (earned), 'negative' (deduction), or 'info' (not yet earned)."
        ),
    )
    score_explanation: list[str] = Field(
        default_factory=list,
        description=(
            "Human-readable sentences explaining why the score is what it is, "
            "e.g. 'Workflow evidence was uploaded and analyzed.' or "
            "'Recording was brief, which lowered confidence.'"
        ),
    )
    skill_improvement_tips: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Skill-specific improvement tips for partially- or unsupported skills. "
            "Each entry: {skill, status, category, tip}."
        ),
    )
