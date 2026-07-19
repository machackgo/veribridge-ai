"""Canonical proof-native evidence contracts — ONE claim→evidence model shared
by the Skill Report and the Project Report.

Every report surface answers the same questions through these schemas: what
exact claim is made, which project feature it concerns, which GitHub code
implements it, which Website Proof demonstrates it at runtime, which document
explains its design, which Project Defense answer demonstrates understanding,
how those sources corroborate (or fail to), what a recruiter can inspect, and
what is still missing, pending, or mismatched.

Hard rules encoded here:
  • Qualitative states only — no numeric trust scores anywhere.
  • Locators (file/line/commit/page/timestamp) are copied from stored analyzer
    records, never invented; a citation with no stored locator carries an honest
    limitation instead.
  • Same-project attachment alone NEVER creates corroboration — a
    ``CorroborationGroup`` must name the claim-level alignment reason.
  • Identity-mismatched evidence (e.g. a recording of a different application
    attached to this project) is kept, visibly flagged, and never counted.
  • No raw storage paths or permanently-stored signed URLs; access is described
    by descriptors and resolved on demand by the access-link services.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ── Closed vocabularies ────────────────────────────────────────────────────────

# Qualitative claim states (ordered strongest → weakest for display; NOT ranks).
QUALITATIVE_STATES = (
    "Demonstrated",
    "Corroborated",
    "Partially demonstrated",
    "Context only",
    "Analysis pending",
    "Mismatch detected",
    "Insufficient evidence",
    "Not assessed",
)

# How one piece of evidence relates to a claim / another piece of evidence.
RELATION_TYPES = (
    "implements",
    "demonstrates_runtime",
    "explains_design",
    "explains_authorship",
    "corroborates",
    "partially_corroborates",
    "contradicts",
    "contextual_only",
    "same_project_unmapped",
    "mismatched",
    "unrelated",
    "supersedes",
)

# GitHub implementation tier (derived from the VALIDATED evidence grade — a bare
# route decorator / import block / docstring is never primary implementation).
GITHUB_EVIDENCE_TIERS = (
    "primary_implementation",
    "supporting_implementation",
    "configuration_context",
    "weak_signal",
    "not_relevant",
)

# Website↔project identity classification. Same-project ATTACHMENT is not
# identity: a recording must genuinely match the project (repo / domain / app
# title / project title / confirmed association) before it can count.
IDENTITY_STATES = (
    "matched_direct",
    "possible_match_review",
    "project_context",
    "mismatched",
    "unrelated",
)

PROJECT_RELATIONSHIP_STATES = (
    "directly_linked",
    "suggested_match",
    "mismatched_project",
    "vault_only",
    "legacy_unresolved",
)

EVIDENCE_STATUSES = (
    "ready",
    "analysis_pending",
    "needs_confirmation",
    "excluded",
    "unavailable",
)

EVIDENCE_QUALITIES = (
    "primary",
    "supporting",
    "context",
    "insufficient",
)

DOCUMENT_BLOCK_TYPES = (
    "paragraph",
    "heading",
    "table",
    "chart",
    "graph",
    "image",
    "screenshot",
    "architecture_diagram",
    "code_block",
    "metric_result",
    "equation",
    "caption",
    "list",
    "mixed_region",
    "unknown_visual_region",
)

# Strongest-evidence tier labels for a claim (closed, recruiter-readable).
EVIDENCE_TIER_LABELS = (
    "Primary implementation",
    "Supporting implementation",
    "Runtime demonstration",
    "Design documentation",
    "Authorship explanation",
    "Context only",
    "Analysis pending",
    "None",
)


# ── Access descriptors (no stored signed URLs, ever) ──────────────────────────


class AccessDescriptor(BaseModel):
    """How a recruiter/owner can inspect the underlying source.

    ``url`` is set ONLY for genuinely public targets (a public GitHub ``…#L``
    line link, a safe public live site). Private artifacts carry
    ``available=True`` + an ``action_label`` and are resolved to a bounded
    signed URL on demand by the artifact access routes — never stored here.
    """

    kind: str = ""  # "github_lines" | "github_repo" | "live_site" | "recorded_replay" | "document_original" | "defense_recording" | "none"
    label: str = ""
    available: bool = False
    action_label: str | None = None
    url: str | None = None
    requires_owner_permission: bool = False
    note: str | None = None

    model_config = {"extra": "forbid"}


class VideoEvidenceDescriptor(BaseModel):
    """Canonical video contract shared by Website Proof and Project Defense.

    Playback URLs are generated on demand (bounded, signed) by the artifact
    access routes; this descriptor only states availability + safe metadata.
    """

    proof_type: str = ""
    recording_available: bool = False
    availability: str = "not_retained"  # "retained" | "not_retained" | "pending"
    duration_label: str | None = None
    mime_type: str | None = None
    transcript_available: bool = False
    poster_available: bool = False
    # Safe timestamped events across the whole recording ("00:18 — inputs set").
    timeline_events: list[dict[str, Any]] = Field(default_factory=list)
    # Segments cited by a specific claim ({start_label, end_label, description}).
    cited_segments: list[dict[str, Any]] = Field(default_factory=list)
    access: AccessDescriptor | None = None
    limitations: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class DocumentAccessDescriptor(BaseModel):
    """Honest document retention/access state.

    Historical documents whose original file was never retained stay
    ``excerpts_only`` — the report shows the extracted evidence and says so,
    instead of pretending an original can be opened.
    """

    retained: bool = False
    excerpts_only: bool = True
    open_available: bool = False
    download_available: bool = False
    publication_state: str = "private"  # "private" | "published"
    original_filename: str | None = None
    mime_type: str | None = None
    limitations: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class ProjectRelationshipDescriptor(BaseModel):
    """The explicit proof→project edge used by every downstream view."""

    state: str = "legacy_unresolved"
    project_id: str | None = None
    project_title: str | None = None
    match_method: str = "legacy"
    counted: bool = False
    confirmed_by_user: bool = False
    reasons: list[str] = Field(default_factory=list)
    action_label: str | None = None

    model_config = {"extra": "forbid"}


class ProjectRelationshipConfirmRequest(BaseModel):
    proof_type: str
    proof_id: str
    project_id: str

    model_config = {"extra": "forbid"}


class ProofFinalizationResponse(BaseModel):
    """Honest result from the shared proof-finalization boundary.

    ``already_finalized`` is persisted against the exact proof/project pair, so
    clients can distinguish the first save from an idempotent repeat across
    reloads and login sessions.
    """

    proof_id: str
    proof_type: str
    project_id: str
    project_relationship: ProjectRelationshipDescriptor
    evidence_item_count: int = 0
    supported_skill_count: int = 0
    unsupported_skill_count: int = 0
    claim_link_count: int = 0
    artifact_ids: list[str] = Field(default_factory=list)
    report_eligibility: str = "project_attached"
    warnings: list[str] = Field(default_factory=list)
    failure_category: str | None = None
    already_finalized: bool = False
    finalized_at: str | None = None

    model_config = {"extra": "forbid"}


class DocumentBlockCitation(BaseModel):
    """Block-aware document locator. Unknown visual content fails closed."""

    document_id: str | None = None
    document_title: str = "Document"
    page_number: int | None = None
    block_type: str = "paragraph"
    bounding_box: list[float] | None = None
    extracted_text: str | None = None
    table_cells: list[list[str]] = Field(default_factory=list)
    visual_description: str | None = None
    nearby_caption: str | None = None
    extraction_confidence: str = "not_available"
    model_limitation: str | None = None
    preview_url: str | None = None
    open_page_url: str | None = None

    model_config = {"extra": "forbid"}


# ── Core claim→evidence graph ─────────────────────────────────────────────────


class ProjectFeature(BaseModel):
    """A concrete, inspectable facet of a project that claims/evidence attach to
    (a code symbol, a runtime workflow, a document section, a defense topic).
    Features are DERIVED from real locators — never invented placeholders."""

    id: str
    project_id: str | None = None
    title: str
    description: str = ""
    feature_type: str = ""  # "code_symbol" | "runtime_workflow" | "document_section" | "defense_topic"
    related_skills: list[str] = Field(default_factory=list)
    repo_paths: list[str] = Field(default_factory=list)
    routes: list[str] = Field(default_factory=list)
    runtime_workflows: list[str] = Field(default_factory=list)
    document_sections: list[str] = Field(default_factory=list)
    defense_question_ids: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class SourceCounts(BaseModel):
    """Honest per-bucket proof-SOURCE counts for one claim (or a whole map).

    Counts DISTINCT proof types, never raw citation rows, so five weak snippets
    from one document can never read as "5 proofs". Only ``direct`` and
    ``corroborating`` contribute to a supported-proof count; every other bucket
    is visible but never counted. A video citation that only points into the
    same Project Defense recording is folded into that defense source — it can
    never appear as an extra independent source.
    """

    direct: int = 0
    corroborating: int = 0
    context_only: int = 0
    pending: int = 0
    vault_only: int = 0
    unsupported: int = 0
    # The distinct proof-type labels behind each bucket (recruiter-readable).
    direct_sources: list[str] = Field(default_factory=list)
    corroborating_sources: list[str] = Field(default_factory=list)
    context_only_sources: list[str] = Field(default_factory=list)
    pending_sources: list[str] = Field(default_factory=list)
    vault_only_sources: list[str] = Field(default_factory=list)
    unsupported_sources: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class SkillClaim(BaseModel):
    """One exact claim the report argues ("<skill> was implemented and
    demonstrated in <project>"), with a qualitative status derived ONLY from the
    counted citations below."""

    id: str
    project_id: str | None = None
    skill_id: str = ""
    skill_name: str = ""
    claim_text: str = ""
    claim_scope: str = "project"  # "project" | "skill" | "portfolio"
    feature_ids: list[str] = Field(default_factory=list)
    qualitative_status: str = "Not assessed"
    strongest_evidence_tier: str = "None"
    # Honest per-bucket source counts for THIS claim (distinct proof types).
    source_counts: SourceCounts = Field(default_factory=SourceCounts)
    limitations: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class EvidenceCitation(BaseModel):
    """One concrete, recruiter-inspectable piece of evidence tied to a claim.

    Locator fields are copied verbatim from stored analyzer records; whichever
    do not exist stay ``None`` and the citation carries the honest limitation.
    ``counted_as_direct_evidence`` is the single flag downstream consumers use —
    mismatched / context-only / pending citations are visible but never counted.
    """

    evidence_id: str
    proof_type: str = ""
    project_id: str | None = None
    skill_id: str | None = None
    claim_id: str | None = None
    feature_id: str | None = None
    source_title: str = ""
    citation_type: str = "source"
    source_proof_id: str | None = None
    source_artifact_id: str | None = None
    source_locator: str | None = None
    # GitHub locators
    file_path: str | None = None
    symbol_name: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    # The ANALYZED context window (from trusted analyzer provenance) when it is
    # wider than the cited target lines — e.g. the containing function that was
    # classified. The target citation above is never rewritten to hide this.
    context_start_line: int | None = None
    context_end_line: int | None = None
    # Analyzer version that produced the stored classification (provenance).
    analysis_version: str | None = None
    commit_sha: str | None = None
    code_excerpt: str | None = None
    # Video / defense locators (safe labels, never raw ms offsets from storage)
    timestamp_start_label: str | None = None
    timestamp_end_label: str | None = None
    transcript_excerpt: str | None = None
    question_text: str | None = None
    # Document locators
    page_number: int | None = None
    section_title: str | None = None
    figure_or_table: str | None = None
    # Website observations
    observed_action: str | None = None
    observed_output: str | None = None
    route_or_page: str | None = None
    # Explanation + relevance (plain language, skill-specific — never generic)
    explanation: str = ""
    relevance: str = ""
    # Qualitative strength label (closed; never numeric)
    strength: str = "Context only"
    # GitHub-only implementation tier (see GITHUB_EVIDENCE_TIERS)
    github_tier: str | None = None
    # Website-only identity classification (see IDENTITY_STATES) + reasons
    identity_state: str | None = None
    identity_reasons: list[str] = Field(default_factory=list)
    # THE flag: does this citation count as direct evidence for its claim?
    counted_as_direct_evidence: bool = False
    # True when this weak/repo-level context citation was deduplicated into the
    # map-level "grouped context" section instead of repeating under every claim.
    grouped_context: bool = False
    # Set when a video citation only points into the SAME Project Defense
    # recording as an existing defense citation — it renders as a citation
    # layer and never counts as an independent proof source.
    duplicate_of_evidence_id: str | None = None
    project_relationship: ProjectRelationshipDescriptor | None = None
    evidence_status: str = "ready"
    evidence_quality: str = "context"
    privacy_state: str = "private"
    publication_state: str = "private"
    analysis_pending: bool = False
    access: AccessDescriptor | None = None
    actions: list[AccessDescriptor] = Field(default_factory=list)
    video: VideoEvidenceDescriptor | None = None
    document_access: DocumentAccessDescriptor | None = None
    document_block: DocumentBlockCitation | None = None
    limitations: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class EvidenceRelation(BaseModel):
    """A typed edge between two citations (or a citation and its claim)."""

    source_evidence_id: str
    target_evidence_id: str | None = None
    relation_type: str = "contextual_only"
    claim_id: str | None = None
    feature_id: str | None = None
    reason: str = ""
    confidence_label: str = "deterministic"  # "deterministic" | "likely" | "needs review"

    model_config = {"extra": "forbid"}


class CorroborationGroup(BaseModel):
    """Sources that genuinely align on ONE claim/feature. Sharing a project id
    is NEVER sufficient — ``alignment_reason`` must state the claim-level
    alignment, and each member states its unique contribution."""

    group_id: str
    claim_id: str
    feature_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    alignment_reason: str = ""
    independent_sources: bool = False
    unique_contributions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class Contradiction(BaseModel):
    """A visible conflict — e.g. an attached recording whose application
    identity does not match the project. Never silently dropped or moved."""

    contradiction_id: str
    kind: str = ""  # "identity_mismatch" | "inconsistent_statement" | "stale_evidence"
    claim_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    description: str = ""
    recommended_action: str = ""

    model_config = {"extra": "forbid"}


class EvidenceGap(BaseModel):
    """What is honestly missing or pending for a claim."""

    claim_id: str | None = None
    proof_type: str | None = None
    description: str = ""
    recommended_action: str = ""

    model_config = {"extra": "forbid"}


class ClaimEvidenceMap(BaseModel):
    """The canonical claim→evidence argument for one report (skill or project).

    The frontend renders this structure directly — it never re-infers
    relationships, corroboration, or identity matches in React.
    """

    schema_version: int = 1
    scope: str = "skill_report"  # "skill_report" | "project_report"
    skill_name: str | None = None
    project_id: str | None = None
    claims: list[SkillClaim] = Field(default_factory=list)
    features: list[ProjectFeature] = Field(default_factory=list)
    citations: list[EvidenceCitation] = Field(default_factory=list)
    relations: list[EvidenceRelation] = Field(default_factory=list)
    corroborations: list[CorroborationGroup] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    gaps: list[EvidenceGap] = Field(default_factory=list)
    # Map-level union of the per-claim buckets (distinct proof types).
    source_counts: SourceCounts = Field(default_factory=SourceCounts)
    recruiter_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


__all__ = [
    "QUALITATIVE_STATES",
    "RELATION_TYPES",
    "GITHUB_EVIDENCE_TIERS",
    "IDENTITY_STATES",
    "PROJECT_RELATIONSHIP_STATES",
    "EVIDENCE_STATUSES",
    "EVIDENCE_QUALITIES",
    "DOCUMENT_BLOCK_TYPES",
    "EVIDENCE_TIER_LABELS",
    "AccessDescriptor",
    "VideoEvidenceDescriptor",
    "DocumentAccessDescriptor",
    "ProjectRelationshipDescriptor",
    "ProjectRelationshipConfirmRequest",
    "ProofFinalizationResponse",
    "DocumentBlockCitation",
    "ProjectFeature",
    "SkillClaim",
    "SourceCounts",
    "EvidenceCitation",
    "EvidenceRelation",
    "CorroborationGroup",
    "Contradiction",
    "EvidenceGap",
    "ClaimEvidenceMap",
]
