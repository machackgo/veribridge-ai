"""Schemas for claim-level Project Defense Answer Evidence.

One card per answered defense question: what was asked (``question_kind`` /
``target_ref``), what claim the answer addresses (``claim_type``), what the
answer is evidence *of* (``evidence_role``), a conservative qualitative status
(never numeric), a privacy-safe answer summary, and high-level corroboration
flags against the attached GitHub / Website / Document proofs.

Two shapes:

* ``DefenseAnswerEvidenceCard`` — owner/private report card. May carry the
  internal ``question_id`` and the deterministic question text.
* ``PublicDefenseAnswerEvidence`` — recruiter-safe public projection. Carries
  no internal IDs; when the transcript privacy review is not clean the public
  builder replaces answer-derived text with a fixed withheld placeholder
  (see ``public_report_safety_service.public_safe_defense_answer_evidence``).

Framing rule: these cards are self-explanation / corroboration evidence — the
wording never claims implementation or authorship proof.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DefenseAnswerEvidenceCard(BaseModel):
    """Owner-visible claim-level answer evidence for one defense question."""

    evidence_id_safe: str
    question_id: str | None = None
    question_kind: str = "unknown_or_generic"
    question_text: str = ""
    target_ref_kind: str | None = None
    target_ref_label_safe: str | None = None
    project_title: str = ""
    mapped_skill: str | None = None
    claim_type: str = "project_architecture"
    answer_purpose: str = "unknown_or_generic"
    evidence_role: str = "insufficient_or_generic"
    qualitative_status: str = "Not explained"
    safe_answer_summary: str = ""
    evidence_basis_chips: list[str] = Field(default_factory=list)
    corroborates_github: bool = False
    corroborates_website: bool = False
    corroborates_document: bool = False
    contradiction_flag: bool = False
    limitation: str = ""
    public_shareable: bool = False
    privacy_status: str = "unknown"

    model_config = {"extra": "forbid"}


class PublicDefenseAnswerEvidence(BaseModel):
    """Recruiter-safe public projection of one answer evidence card.

    Intentionally omits ``question_id`` (internal), ``public_shareable`` and
    the raw ``privacy_status`` (the public value is always ``"clean"`` or the
    fixed ``"withheld"``). ``question_text`` is the deterministic generated
    question — it is kept only when the privacy review passed and is dropped
    on a withheld card.
    """

    evidence_id_safe: str
    question_kind: str = "unknown_or_generic"
    question_text: str | None = None
    target_ref_label_safe: str | None = None
    mapped_skill: str | None = None
    claim_type: str = "project_architecture"
    answer_purpose: str = "unknown_or_generic"
    evidence_role: str = "insufficient_or_generic"
    qualitative_status: str = "Not explained"
    safe_answer_summary: str = ""
    evidence_basis_chips: list[str] = Field(default_factory=list)
    corroborates_github: bool = False
    corroborates_website: bool = False
    corroborates_document: bool = False
    limitation: str = ""
    privacy_status: str = "clean"

    model_config = {"extra": "forbid"}


class ProjectDefenseInspectionCard(BaseModel):
    """Owner/private recruiter-inspection card for one defended question.

    A first-class inspection projection over one ``DefenseAnswerEvidenceCard``
    that answers the recruiter's questions the same way GitHub / Website /
    Document inspection do: *what was asked*, *what the student explained*,
    *which skill/project claim it supports*, *what safe clip locator exists*,
    *what corroborates it*, *what it demonstrates*, and — conservatively — *what
    it does not prove by itself*.

    Framing rule (product): Project Defense is explanation / corroboration
    evidence. The wording never claims verified implementation, runtime
    behavior, or authorship. Carries no ``question_id`` or any internal id — the
    stable ``evidence_id_safe`` is the only handle. ``clip_*`` fields are a safe
    time-range locator only; they never carry raw transcript, media paths, or
    signed URLs.
    """

    evidence_id_safe: str
    question_text: str = ""
    question_kind: str = "unknown_or_generic"
    project_title: str = ""
    mapped_skill: str | None = None
    claim_type: str = "project_architecture"
    answer_purpose: str = "unknown_or_generic"
    evidence_role: str = "insufficient_or_generic"
    qualitative_status: str = "Not explained"
    safe_answer_summary: str = ""
    evidence_basis_chips: list[str] = Field(default_factory=list)
    timestamp_label: str | None = None
    clip_start_seconds: float | None = None
    clip_end_seconds: float | None = None
    clip_available: bool = False
    corroborates_github: bool = False
    corroborates_website: bool = False
    corroborates_document: bool = False
    corroboration_summary: str = ""
    what_this_demonstrates: str = ""
    limitation: str = ""
    public_safe: bool = False
    withheld_reason: str | None = None

    model_config = {"extra": "forbid"}


class PublicProjectDefenseInspectionCard(BaseModel):
    """Recruiter-safe public projection of one Project Defense inspection card.

    Omits every internal handle. When the session's transcript privacy review
    did not pass — or the individual card is not shareable — the public builder
    replaces answer-derived content with a fixed withheld placeholder, drops the
    clip locator, and sets ``withheld_reason`` (see
    ``public_report_safety_service.public_safe_project_defense_inspection``).
    """

    evidence_id_safe: str
    question_text: str | None = None
    question_kind: str = "unknown_or_generic"
    project_title: str = ""
    mapped_skill: str | None = None
    claim_type: str = "project_architecture"
    answer_purpose: str = "unknown_or_generic"
    evidence_role: str = "insufficient_or_generic"
    qualitative_status: str = "Not explained"
    safe_answer_summary: str = ""
    evidence_basis_chips: list[str] = Field(default_factory=list)
    timestamp_label: str | None = None
    clip_start_seconds: float | None = None
    clip_end_seconds: float | None = None
    clip_available: bool = False
    corroborates_github: bool = False
    corroborates_website: bool = False
    corroborates_document: bool = False
    corroboration_summary: str = ""
    what_this_demonstrates: str = ""
    limitation: str = ""
    public_safe: bool = True
    withheld_reason: str | None = None

    model_config = {"extra": "forbid"}


__all__ = [
    "DefenseAnswerEvidenceCard",
    "PublicDefenseAnswerEvidence",
    "ProjectDefenseInspectionCard",
    "PublicProjectDefenseInspectionCard",
]
