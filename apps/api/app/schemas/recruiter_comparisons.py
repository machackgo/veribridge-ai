"""Typed contracts for the recruiter evidence-comparison matrix.

Comparison is a LIVE VIEW scoped to a Hiring Brief (migration 068): the
brief owns the requirement plan and the candidate pool; these models only
describe the requirement chips and the evaluated matrix. There is no
persisted comparison session.

Every payload is derived from public-projection evidence plus the caller's
own recruiter-private workflow rows. Cell states are a closed vocabulary
(proven / claimed / none / unavailable) — no scores, no percentages.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ComparisonRequirementsInput(BaseModel):
    """The recruiter's EDITED requirement chips. ``required`` entries may be
    a single term ("FastAPI") or a list forming an OR-group. Terms that are
    evidence expectations ("live deployment") are routed server-side."""

    required: list[str | list[str]] = Field(default_factory=list, max_length=16)
    preferred: list[str] = Field(default_factory=list, max_length=16)
    excluded: list[str] = Field(default_factory=list, max_length=16)
    evidence: list[str] = Field(default_factory=list, max_length=8)
    preferred_evidence: list[str] = Field(default_factory=list, max_length=8)
    role: str | None = Field(default=None, max_length=80)
    seniority: str | None = Field(default=None, max_length=40)
    location: str | None = Field(default=None, max_length=60)
    remote: bool = False

    model_config = {"extra": "forbid"}


class RequirementChip(BaseModel):
    display: str
    concepts: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class EvidenceChip(BaseModel):
    key: str
    display: str

    model_config = {"extra": "forbid"}


class ComparisonRequirementsView(BaseModel):
    """Editable-chips payload — exactly what the engine evaluated."""

    required: list[RequirementChip] = Field(default_factory=list)
    preferred: list[RequirementChip] = Field(default_factory=list)
    excluded: list[RequirementChip] = Field(default_factory=list)
    evidence: list[EvidenceChip] = Field(default_factory=list)
    preferred_evidence: list[EvidenceChip] = Field(default_factory=list)
    role: str | None = None
    seniority: str | None = None
    location: str | None = None
    remote: bool = False
    unrecognized_terms: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class MatrixRequirement(BaseModel):
    key: str
    kind: str  # concept | evidence
    display: str
    required: bool
    # "plan" (the recruiter asked for it) | "observed" (derived from the
    # compared candidates' own published evidence — Talent Pool comparison).
    origin: str = "plan"
    concepts: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class CellProjectRef(BaseModel):
    title: str | None = None
    public_report_path: str | None = None
    skill_status: str | None = None
    proof_types: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class CellTracePreview(BaseModel):
    source_type: str | None = None
    source_title: str | None = None
    summary: str | None = None
    public_url: str | None = None

    model_config = {"extra": "forbid"}


class MatrixCell(BaseModel):
    """One requirement × candidate evidence state. ``proven`` cells carry
    provenance (skill report deep link + project/trace refs); ``claimed``
    cells are explicitly labeled unverified; ``none`` cells may carry
    RELATED evidence labels that are explicitly NOT proof."""

    state: str  # proven | claimed | none | unavailable
    matched_label: str | None = None
    skill_status: str | None = None
    direct: bool = True
    evidence_sources: list[str] = Field(default_factory=list)
    project_titles: list[str] = Field(default_factory=list)
    note: str | None = None
    proof_path: str | None = None
    projects: list[CellProjectRef] = Field(default_factory=list)
    traces: list[CellTracePreview] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class ColumnCounts(BaseModel):
    """Transparent deterministic counts — never a percentage."""

    required_proven: int = 0
    required_claimed: int = 0
    required_total: int = 0
    preferred_proven: int = 0
    preferred_claimed: int = 0
    preferred_total: int = 0
    # OBSERVED rows are derived from the compared candidates' own published
    # evidence rather than from a recruiter requirement (Talent Pool
    # comparison). Counted apart so nothing reports them as asked-for.
    observed_proven: int = 0
    observed_claimed: int = 0
    observed_total: int = 0

    model_config = {"extra": "forbid"}


class ColumnConnection(BaseModel):
    """The caller's OWN workspace connection to this candidate, for save /
    deep-link in place. Workspace membership carries no status — role-scoped
    review status lives on ``MatrixColumn.brief_status``."""

    id: str

    model_config = {"extra": "forbid"}


class MatrixColumn(BaseModel):
    user_id: str
    available: bool = True
    public_slug: str | None = None
    display_name: str | None = None
    headline: str | None = None
    availability_label: str | None = None
    passport_path: str | None = None
    cells: dict[str, MatrixCell] = Field(default_factory=dict)
    counts: ColumnCounts = Field(default_factory=ColumnCounts)
    missing_required: list[str] = Field(default_factory=list)
    missing_preferred: list[str] = Field(default_factory=list)
    missing_observed: list[str] = Field(default_factory=list)
    excluded_hits: list[str] = Field(default_factory=list)
    unavailable_note: str | None = None
    connection: ColumnConnection | None = None
    # ROLE-SCOPED review status from the brief's candidate pool
    # (saved | reviewing | shortlisted | archived); None outside a brief.
    brief_status: str | None = None
    # ── RECRUITER-PRIVATE workflow metadata, present only when the matrix is
    # scoped to a Talent Pool. Kept in its own keys and never folded into
    # cells, counts or summaries: recruiter judgement is not evidence.
    pool_status: str | None = None
    pool_note: str | None = None
    tags: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class RequirementCoverage(BaseModel):
    key: str
    display: str
    required: bool
    # "plan" (the recruiter asked for it) | "observed" (derived from the
    # compared candidates' published evidence).
    origin: str = "plan"
    proven_count: int = 0
    claimed_count: int = 0
    candidate_total: int = 0

    model_config = {"extra": "forbid"}


class ComparisonMatrix(BaseModel):
    requirements: list[MatrixRequirement] = Field(default_factory=list)
    columns: list[MatrixColumn] = Field(default_factory=list)
    coverage: list[RequirementCoverage] = Field(default_factory=list)
    summaries: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    requirements_view: ComparisonRequirementsView = Field(
        default_factory=ComparisonRequirementsView
    )

    model_config = {"extra": "forbid"}


__all__ = [
    "CellProjectRef",
    "CellTracePreview",
    "ColumnConnection",
    "ColumnCounts",
    "ComparisonMatrix",
    "ComparisonRequirementsInput",
    "ComparisonRequirementsView",
    "EvidenceChip",
    "MatrixCell",
    "MatrixColumn",
    "MatrixRequirement",
    "RequirementChip",
]
