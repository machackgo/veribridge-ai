"""Typed contracts for the Recruiter Interview Workspace (migration 069).

One interview workspace per (Hiring Brief, candidate): recruiter-private
schedule / notes / decision fields, per-requirement checklist marks, a
compact activity trail, and interview questions grounded EXCLUSIVELY in
the candidate's live published evidence. Everything here is
recruiter-private workflow data — never written to any index, embedding,
public projection, or candidate-facing surface.

The checklist reuses the comparison matrix's requirement/cell models —
same deterministic engine, single candidate. Question ``grounding`` is
always rebuilt server-side from the CURRENT checklist; a question whose
cited requirement is no longer proven arrives with
``evidence_available=False``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.recruiter_comparisons import (
    ColumnCounts,
    MatrixCell,
    MatrixRequirement,
)
from app.schemas.recruiter_hiring_briefs import (
    BriefCandidateIdentity,
    HiringBriefListItem,
)

ChecklistMarkState = Literal["discussed", "verified", "follow_up"]
InterviewQuestionKind = Literal["evidence", "gap"]


class InterviewChecklist(BaseModel):
    """The live single-candidate verification checklist — the same
    deterministic axis/cell engine as the comparison matrix, re-run with
    the fail-closed triple on every load. ``available=False`` means the
    candidate's evidence is no longer publicly comparable and the cells
    are empty (fail-closed, never stale)."""

    requirements: list[MatrixRequirement] = Field(default_factory=list)
    cells: dict[str, MatrixCell] = Field(default_factory=dict)
    counts: ColumnCounts = Field(default_factory=ColumnCounts)
    available: bool = False
    unavailable_note: str | None = None
    summary: str = ""

    model_config = {"extra": "forbid"}


class InterviewChecklistMark(BaseModel):
    """One recruiter-private per-requirement interview mark. Never public
    proof, never candidate-visible."""

    requirement_key: str
    state: ChecklistMarkState
    marked_at: Any = None

    model_config = {"extra": "forbid"}


class InterviewDetails(BaseModel):
    """The pair's recruiter-private interview record."""

    scheduled_at: Any = None
    interviewer_name: str | None = None
    prep_notes: str | None = None
    notes: str | None = None
    decision_notes: str | None = None
    updated_at: Any = None

    model_config = {"extra": "forbid"}


class InterviewQuestionGrounding(BaseModel):
    """Why this question exists — rebuilt server-side from the CURRENT
    checklist on every load; never trusted from an LLM or stored jsonb."""

    requirement_display: str = ""
    state: str = "none"  # proven | claimed | none
    matched_label: str | None = None
    evidence_sources: list[str] = Field(default_factory=list)
    project_titles: list[str] = Field(default_factory=list)
    proof_path: str | None = None

    model_config = {"extra": "forbid"}


class InterviewQuestion(BaseModel):
    """One generated interview question. ``evidence_available=False``
    means the cited requirement's evidence is not (or no longer)
    published-and-proven — the UI shows the honest state instead of stale
    proof."""

    id: str
    requirement_key: str
    kind: InterviewQuestionKind
    question: str
    grounding: InterviewQuestionGrounding = Field(
        default_factory=InterviewQuestionGrounding
    )
    evidence_available: bool = False

    model_config = {"extra": "forbid"}


class InterviewQuestions(BaseModel):
    """The stored + re-graded question set with honest provenance:
    ``source`` is "llm" only when a validated LLM output replaced the
    deterministic template set; ``fallback_reason`` is set when the LLM
    was attempted and failed (advisory notice, never an error)."""

    items: list[InterviewQuestion] = Field(default_factory=list)
    source: str = "deterministic"  # llm | deterministic — provenance, not a score
    generated_at: Any = None
    model: str | None = None
    fallback_reason: str | None = None

    model_config = {"extra": "forbid"}


class InterviewActivityEvent(BaseModel):
    """Compact recruiter-private activity entry. ``detail`` is a closed
    small shape (stage names, requirement keys, counts) — never note text,
    never candidate content."""

    event_type: str
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: Any = None

    model_config = {"extra": "forbid"}


class InterviewWorkspaceResponse(BaseModel):
    """Everything the interview page needs in one load."""

    brief: HiringBriefListItem
    candidate: BriefCandidateIdentity = Field(
        default_factory=BriefCandidateIdentity
    )
    pool_status: str = "saved"
    checklist: InterviewChecklist = Field(default_factory=InterviewChecklist)
    marks: list[InterviewChecklistMark] = Field(default_factory=list)
    interview: InterviewDetails | None = None
    questions: InterviewQuestions | None = None
    activity: list[InterviewActivityEvent] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class UpdateInterviewRequest(BaseModel):
    """Autosave-friendly partial update; omitted fields stay unchanged and
    ``clear_*`` flags remove a value (mirroring the pool-note pattern)."""

    scheduled_at: str | None = Field(default=None, max_length=64)
    interviewer_name: str | None = Field(default=None, max_length=120)
    prep_notes: str | None = Field(default=None, max_length=4000)
    notes: str | None = Field(default=None, max_length=4000)
    decision_notes: str | None = Field(default=None, max_length=4000)
    clear_scheduled_at: bool = False
    clear_interviewer_name: bool = False
    clear_prep_notes: bool = False
    clear_notes: bool = False
    clear_decision_notes: bool = False

    model_config = {"extra": "forbid"}


class InterviewResponse(BaseModel):
    interview: InterviewDetails

    model_config = {"extra": "forbid"}


class SetChecklistMarkRequest(BaseModel):
    """Set (state) or clear (state=null) one per-requirement mark. The key
    travels in the body — axis keys contain ``:`` and ``|``."""

    requirement_key: str = Field(min_length=1, max_length=160)
    state: ChecklistMarkState | None = None

    model_config = {"extra": "forbid"}


class ChecklistMarksResponse(BaseModel):
    marks: list[InterviewChecklistMark] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class GenerateQuestionsRequest(BaseModel):
    """Generate (or return stored, unless ``regenerate``) the pair's
    interview questions."""

    regenerate: bool = False

    model_config = {"extra": "forbid"}


class InterviewQuestionsResponse(BaseModel):
    questions: InterviewQuestions

    model_config = {"extra": "forbid"}


__all__ = [
    "ChecklistMarkState",
    "ChecklistMarksResponse",
    "GenerateQuestionsRequest",
    "InterviewActivityEvent",
    "InterviewChecklist",
    "InterviewChecklistMark",
    "InterviewDetails",
    "InterviewQuestion",
    "InterviewQuestionGrounding",
    "InterviewQuestionKind",
    "InterviewQuestions",
    "InterviewQuestionsResponse",
    "InterviewResponse",
    "InterviewWorkspaceResponse",
    "SetChecklistMarkRequest",
    "UpdateInterviewRequest",
]
