"""Schemas for the student-owned Final VBR Report (v1) preview.

This is a private, student-owned preview of the evidence package collected
for a Project Defense project. It is NOT the public tokenized recruiter
report (see ``vbr_public_report``) — public recruiter sharing is not enabled
by this endpoint.

Only safe summary data is returned: no raw transcript text, document text,
GitHub snapshots, storage paths, signed/upload URLs, bucket names, env
values, tokens, or provider payloads. Evidence strength is expressed using
qualitative labels (``Demonstrated`` / ``Partially demonstrated`` /
``Supporting evidence`` / ``Not assessed`` / ``Needs review``) — never
numeric trust scores.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.vbr_sessions import VideoEvidenceChipResponse


class VBRReportGitHubProofSummary(BaseModel):
    repo_url: str | None = None
    repo_owner: str | None = None
    repo_name: str | None = None
    status: str | None = None
    detected_skills: list[str] = Field(default_factory=list)
    public_safe_summary: str = ""
    # Only true when the repo is a public GitHub repo, so the UI may surface a
    # direct "View repository" link. Private repos are never linked.
    repo_is_public: bool = False


class VBRReportDocumentSummary(BaseModel):
    title: str
    source_type: str | None = None
    status: str | None = None


class VBRReportWebsiteProofSummary(BaseModel):
    target_website: str = ""
    evidence_strength: str = "Not assessed"
    workflow_confidence: str = "insufficient"
    supported_skills: list[str] = Field(default_factory=list)


class VBRReportEvidencePackageSummary(BaseModel):
    github_proof_attached: bool = False
    documents_count: int = 0
    website_proofs_count: int = 0
    project_defense_completed: bool = False
    video_defense_recorded: bool = False
    video_evidence_chip_count: int = 0


class VBRReportQuestionSummary(BaseModel):
    id: str
    question_text: str
    kind: str | None = None
    skill: str | None = None
    answered: bool = False


class VBREvidenceTrace(BaseModel):
    """A single recruiter-safe claim→evidence trace.

    Each trace ties a concrete evidence *source* (a repo, a document, a website
    proof, a defense answer, a video chip) to the skills it supports, with a
    safe explanation, an in-page anchor, and — only when the target is genuinely
    public — a directly-openable link. It never carries raw evidence, storage
    paths, signed URLs, media URLs, tokens, or numeric scores.
    """

    trace_id: str
    # GitHub Proof / Document Proof / Website Proof / Project Defense / Video Evidence
    source_type: str
    source_title: str
    skill_names: list[str] = Field(default_factory=list)
    qualitative_status: str = "Supporting evidence"
    safe_summary: str = ""
    safe_detail: str = ""
    # In-page anchor id of the trace card. Always namespaced under "trace-" so it
    # can never collide with a coarse evidence *section* id (e.g. "github-proof").
    evidence_anchor: str = ""
    # ── Proof-native location (where inside the source this trace points) ──────
    # Coarse machine label: repo_level / document / document_page /
    # document_snippet / website_url / defense_overview / defense_question /
    # video_timestamp / project_level.
    location_type: str | None = None
    # Short human label used to render a precise matrix link (e.g. "repo-level",
    # "Q3", "Live URL", "Video 02:14", "Page 2").
    location_label: str | None = None
    # A slightly longer, still-safe locator detail (e.g. "owner/name on branch
    # main"). For documents this is redacted on public surfaces.
    location_detail: str | None = None
    # ── Per-source safe detail (never raw evidence) ───────────────────────────
    # The deterministic Project Defense question text (safe — never the answer
    # transcript).
    question_text: str | None = None
    # A short, safe excerpt of the candidate's own answer, when available. Never
    # the full transcript; stripped on public surfaces.
    answer_excerpt: str | None = None
    # Document page locator, when the analyzer recorded one.
    page_number: int | None = None
    # A short, safe document snippet, only when one is safe to show. Stripped on
    # public surfaces.
    snippet: str | None = None
    # Safe document citation (matched section heading). Kept on public surfaces.
    citation: str | None = None
    # Safe repository-relative file path, for file/line-level GitHub traces.
    file_path: str | None = None
    # Line range for line-level GitHub code evidence, when the analyzer recorded
    # one (never invented).
    line_start: int | None = None
    line_end: int | None = None
    # Matched function name for GitHub code evidence, when recorded.
    function_name: str | None = None
    # Commit SHA the GitHub Proof analyzer pinned this evidence to, when recorded.
    # A safe hex reference (no path/url/content); kept on public surfaces.
    commit_sha: str | None = None
    # Safe code snippet from a *public* GitHub file. Stripped on public surfaces
    # (the public ``…#L`` link is the recruiter-facing proof instead).
    code_snippet: str | None = None
    # Only set when the target is a safe public URL (repo / live site).
    public_url: str | None = None
    public_url_label: str | None = None
    # Only for video / defense chips when a timestamp label is available.
    timestamp: str | None = None
    # Human timestamp label for video traces (e.g. "02:14").
    timestamp_label: str | None = None
    limitation: str = ""
    is_publicly_openable: bool = False
    # Generic note shown when the source is not publicly openable.
    private_evidence_note: str | None = None
    # Skills whose only stored GitHub line evidence was too weak (imports/setup/
    # notebook narrative) to surface as line-level proof — they fall back to this
    # repo-level card and need reanalysis/backfill. Only set on the GitHub
    # repo-level trace; empty everywhere else.
    weak_line_evidence_skills: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class VaultProofItem(BaseModel):
    """One safe, student-owned proof from the Student Proof Vault.

    Normalized from any proof source (GitHub / Document / Website / Project
    Defense / Video / Skill Graph) — attached to a VBR project or standalone.
    Never carries raw transcripts/docs/snapshots, storage paths, signed URLs,
    media paths, private ids, or numeric trust scores.
    """

    # Null when the proof is project-level context not mapped to a single skill.
    skill_name: str | None = None
    proof_type: str
    source_id: str
    source_table: str
    # Owner-only: the primary VBR project this proof is attached to, if any.
    project_id: str | None = None
    attached_project_ids: list[str] = Field(default_factory=list)
    title: str = ""
    source_label: str = ""
    safe_summary: str = ""
    safe_snippet: str | None = None
    safe_location: str | None = None
    public_safe: bool = False
    visibility: str = "private"
    limitation: str = ""
    is_attached_to_project: bool = False
    # Safe structured locators (populated cheaply at collection — no hydration).
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    function_name: str | None = None
    commit_sha: str | None = None
    public_url: str | None = None
    # Explicit GitHub display-mode fields (only set for GitHub items).
    display_mode: str | None = None
    evidence_strength: str | None = None
    evidence_kind: str | None = None
    has_precise_line_evidence: bool | None = None
    github_line_url: str | None = None
    repo_url: str | None = None
    # Canonical (old GitHub Profile & Proof engine) fields — precise
    # ``selection_reason`` + optional subskill / system-graph node.
    selection_reason: str | None = None
    subskill_name: str | None = None
    skill_graph_node: str | None = None
    page_number: int | None = None
    section_label: str | None = None
    citation: str | None = None
    question_text: str | None = None
    answer_excerpt: str | None = None
    timestamp_label: str | None = None

    model_config = {"extra": "forbid"}


class VaultSkillGroup(BaseModel):
    """Student-vault proofs grouped under one skill (attached + unattached)."""

    skill: str
    proofs: list[VaultProofItem] = Field(default_factory=list)
    proof_types: list[str] = Field(default_factory=list)
    attached_count: int = 0
    unattached_count: int = 0
    has_unattached: bool = False

    model_config = {"extra": "forbid"}


# ── Student Proof Vault: Layer 1 (compact skill summary) ─────────────────────


class VaultSkillPreview(BaseModel):
    """A compact, safe preview of one vault proof, for the main Passport card."""

    proof_type: str
    title: str = ""
    safe_location: str | None = None
    safe_summary: str = ""
    is_attached_to_project: bool = False
    public_safe: bool = False

    model_config = {"extra": "forbid"}


class VaultSkillSummary(BaseModel):
    """Layer 1 — one compact skill card for the main Work Passport dashboard.

    Carries counts and a few representative previews only — NOT every proof. The
    full evidence is loaded lazily via the Skill Report endpoint. ``status`` is a
    qualitative label, never a numeric score."""

    skill: str
    # Stable, URL-safe slug (derived from the canonical name) — the Skill Report
    # route key. ``machine-learning`` ↔ ``Machine Learning``.
    skill_slug: str = ""
    category: str = "Other"
    status: str = "Supporting evidence"
    # Original source skill labels collapsed into this canonical skill (kept for
    # traceability — the canonical name is ``skill``).
    source_labels: list[str] = Field(default_factory=list)
    project_ids: list[str] = Field(default_factory=list)
    project_titles: list[str] = Field(default_factory=list)
    project_count: int = 0
    proof_source_counts: dict[str, int] = Field(default_factory=dict)
    proof_count: int = 0
    attached_count: int = 0
    unattached_count: int = 0
    has_unattached: bool = False
    summary: str = ""
    previews: list[VaultSkillPreview] = Field(default_factory=list)
    more_count: int = 0
    limitations: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


# ── Student Proof Vault: Layer 2 (full Skill Report) ─────────────────────────


class SkillReportEvidenceItem(BaseModel):
    """One rich, recruiter-verifiable evidence item inside a Skill Report section.

    Carries the concrete stored locators (GitHub file/line/function/commit/link,
    Document page/section/citation, Defense/Video chips) and — for Website proofs
    only — the safe hydrated workflow/OCR/DOM/visual/live-check summaries. Never
    raw transcripts/docs/snapshots, storage paths, signed URLs, or media paths."""

    proof_type: str
    source_id: str
    title: str = ""
    safe_summary: str = ""
    safe_location: str | None = None
    safe_snippet: str | None = None
    public_safe: bool = False
    is_attached_to_project: bool = False
    attached_project_ids: list[str] = Field(default_factory=list)
    project_titles: list[str] = Field(default_factory=list)
    limitation: str = ""
    # GitHub locators
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    function_name: str | None = None
    commit_sha: str | None = None
    public_url: str | None = None
    # Explicit GitHub display-mode fields (the frontend renders precise "View code
    # lines" vs. honest "View repository" from these, never re-inferring). Only set
    # for GitHub items; ``None`` for every other proof type.
    #   ``display_mode``: "code_line" (precise) | "repo_level" (weak/repo-only).
    display_mode: str | None = None
    evidence_strength: str | None = None
    evidence_kind: str | None = None
    has_precise_line_evidence: bool | None = None
    github_line_url: str | None = None
    repo_url: str | None = None
    # Canonical (old GitHub Profile & Proof engine) fields — the precise
    # ``selection_reason`` ("API endpoint decorator") + optional subskill /
    # system-graph node the PortfolioScanner stored on ``skill_evidence``.
    selection_reason: str | None = None
    subskill_name: str | None = None
    skill_graph_node: str | None = None
    # Document locators
    page_number: int | None = None
    section_label: str | None = None
    citation: str | None = None
    # Defense / video locators
    question_text: str | None = None
    answer_excerpt: str | None = None
    timestamp_label: str | None = None
    # Website-only hydrated safe summaries
    workflow_summary: str | None = None
    workflow_steps: list[str] = Field(default_factory=list)
    dom_summary: str | None = None
    ocr_summary: str | None = None
    visual_summary: str | None = None
    live_check: dict | None = None

    model_config = {"extra": "forbid"}


class SkillReportDocumentCorrelation(BaseModel):
    """A document shown as *corroboration*, connected to stronger artifact evidence.

    Never a standalone line-by-line document dump — it answers "what does this
    document corroborate?" with a single safe citation. The raw document is never
    exposed; only a bounded safe snippet/citation."""

    source_id: str
    document_title: str = ""
    page_number: int | None = None
    section_label: str | None = None
    citation: str | None = None
    safe_snippet: str | None = None
    # What stronger evidence this doc corroborates: "GitHub implementation" /
    # "Website workflow behavior" / "Skill explanation" / "Project architecture".
    corroborates: str = ""
    # Qualitative correlation confidence: "direct attachment" / "title/project
    # match" / "skill-only match" / "weak/standalone".
    correlation_confidence: str = "weak/standalone"
    # Documents corroborate; they are supporting evidence, never primary proof.
    support_label: str = "Supporting evidence"
    reason: str = ""
    limitation: str = ""

    model_config = {"extra": "forbid"}


class SkillProofSynthesisStatement(BaseModel):
    """One synthesis sentence with the evidence ids it was built from.

    The Proof Synthesis Agent may ONLY cite ``evidence_ids`` that are actually
    present in the chain — it can never invent evidence — so a recruiter can map
    each statement back to a concrete proof card."""

    text: str = ""
    source: str = ""
    evidence_ids: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class SkillReportProjectChain(BaseModel):
    """One project's connected proof chain for a skill — artifacts + corroboration.

    Documents are connected here as ``document_correlations`` (capped, with a
    ``document_more_count`` overflow) rather than dumped, so the chain reads as a
    set of sources that corroborate the same skill claim."""

    project_id: str | None = None
    project_title: str = ""
    attached: bool = False
    attached_status: str = ""
    sources: list[str] = Field(default_factory=list)
    evidence_chain_summary: str = ""
    github_evidence: list[SkillReportEvidenceItem] = Field(default_factory=list)
    website_evidence: list[SkillReportEvidenceItem] = Field(default_factory=list)
    document_correlations: list[SkillReportDocumentCorrelation] = Field(default_factory=list)
    document_more_count: int = 0
    defense_evidence: list[SkillReportEvidenceItem] = Field(default_factory=list)
    video_evidence: list[SkillReportEvidenceItem] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    # When several VBR project rows share the same proof package, duplicate chains
    # are collapsed into one representative; these record how many were merged.
    collapsed_project_count: int = 1
    collapsed_project_ids: list[str] = Field(default_factory=list)
    # When several same-title VBR attempts (different proof combinations) are
    # merged into one display chain, these record how many attempts were grouped.
    grouped_attempt_count: int = 1
    grouped_project_ids: list[str] = Field(default_factory=list)
    # ── Proof Synthesis Agent fields (qualitative, deterministic) ─────────────
    # A qualitative confidence tier (NEVER a numeric score): "Strongly
    # corroborated" / "Corroborated" / "Supporting evidence" / "Needs review" /
    # "Insufficient evidence".
    confidence_tier: str = ""
    # A one-sentence synthesis of how the chain's sources corroborate the skill.
    synthesis_result: str = ""
    # Plain-language reason these independent sources refer to the same project.
    why_linked: str = ""
    # Subskills the chain's canonical GitHub evidence named.
    subskills: list[str] = Field(default_factory=list)
    # Evidence-cited synthesis statements (each references real evidence ids).
    synthesis_statements: list[SkillProofSynthesisStatement] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class SkillReportStandaloneEvidence(BaseModel):
    """Proofs supporting a skill that are not attached to any VBR project."""

    github: list[SkillReportEvidenceItem] = Field(default_factory=list)
    website: list[SkillReportEvidenceItem] = Field(default_factory=list)
    documents: list[SkillReportDocumentCorrelation] = Field(default_factory=list)
    document_more_count: int = 0
    defense: list[SkillReportEvidenceItem] = Field(default_factory=list)
    video: list[SkillReportEvidenceItem] = Field(default_factory=list)
    skill_graph: list[SkillReportEvidenceItem] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class SkillProofSynthesisUnlinkedItem(BaseModel):
    """A standalone proof that links to no chain — shown under unlinked support.

    Compact + safe: a source badge, a bounded summary/location and (for documents)
    what it corroborates. Never raw evidence, storage paths or signed URLs."""

    proof_type: str
    source_id: str = ""
    title: str = ""
    safe_summary: str = ""
    safe_location: str | None = None
    corroborates: str = ""
    limitation: str = ""

    model_config = {"extra": "forbid"}


class SkillProofSynthesisUnlinked(BaseModel):
    """Capped bucket of proofs that support the skill but join no proof chain.

    Capped so the report never dumps every loose proof; the remainder is reported
    as ``more_count`` and a recruiter can request the full Skill Report sections."""

    items: list[SkillProofSynthesisUnlinkedItem] = Field(default_factory=list)
    count: int = 0
    more_count: int = 0

    model_config = {"extra": "forbid"}


class SkillReportOverview(BaseModel):
    skill: str
    category: str = "Other"
    status: str = "Supporting evidence"
    proof_source_counts: dict[str, int] = Field(default_factory=dict)
    proof_count: int = 0
    attached_count: int = 0
    unattached_count: int = 0
    project_count: int = 0
    why_supported: str = ""
    gaps: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class SkillReportResponse(BaseModel):
    """Layer 2 — the full, recruiter-verifiable evidence for one selected skill."""

    skill: str
    skill_slug: str = ""
    requested_skill: str = ""
    category: str = "Other"
    status: str = "Supporting evidence"
    summary: str = ""
    source_counts: dict[str, int] = Field(default_factory=dict)
    overview: SkillReportOverview
    # Connected proof chains, one per project (plus a standalone-vault bucket).
    projects: list[SkillReportProjectChain] = Field(default_factory=list)
    # Proofs not attached to any VBR project, grouped by source.
    standalone_evidence: SkillReportStandaloneEvidence = Field(
        default_factory=SkillReportStandaloneEvidence
    )
    # ── Proof Synthesis Agent output ──────────────────────────────────────────
    # Recruiter-facing summary of the whole synthesis (qualitative, no scores).
    synthesis_summary: str = ""
    # Boolean coverage across the five evidence surfaces (GitHub/Website/Document/
    # Defense/Video) — never counts or numeric scores.
    source_coverage: dict[str, bool] = Field(default_factory=dict)
    # The project-anchored connected proof chains (the attached subset of
    # ``projects``, strongest-tier first), each carrying its synthesis fields.
    proof_chains: list[SkillReportProjectChain] = Field(default_factory=list)
    # Capped supporting proofs that join no chain.
    unlinked_supporting_evidence: SkillProofSynthesisUnlinked = Field(
        default_factory=SkillProofSynthesisUnlinked
    )
    # Flat per-source lists (back-compat; the connected chains above are primary).
    github: list[SkillReportEvidenceItem] = Field(default_factory=list)
    website: list[SkillReportEvidenceItem] = Field(default_factory=list)
    documents: list[SkillReportEvidenceItem] = Field(default_factory=list)
    defense: list[SkillReportEvidenceItem] = Field(default_factory=list)
    video: list[SkillReportEvidenceItem] = Field(default_factory=list)
    skill_graph: list[SkillReportEvidenceItem] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    generated_at: str = ""

    model_config = {"extra": "forbid"}


class VBRReportSkillEvidenceRow(BaseModel):
    skill: str
    status: str
    evidence_chip_count: int = 0
    notes: str = ""
    # Canonical recruiter-facing evidence-source labels that support this skill
    # (e.g. "GitHub Proof", "Website Proof", "Project Defense", "Video
    # Evidence"). Never a numeric score.
    supporting_sources: list[str] = Field(default_factory=list)
    # Honest per-skill caveats (e.g. a weakly-evidenced claim pending more proof).
    limitations: list[str] = Field(default_factory=list)
    # Plain-language justification for the qualitative status above.
    why_this_status: str = ""
    # What a recruiter can safely inspect to verify this skill claim.
    recruiter_can_verify: str = ""
    # IDs of the evidence traces (see ``VBREvidenceTrace``) that support this skill.
    evidence_traces: list[str] = Field(default_factory=list)


class VBRReportProjectDefenseAnalysis(BaseModel):
    """Report-safe summary of a ``DefenseAnalysisResponse``.

    Numeric analysis scores (``overall_defense_score``,
    ``explanation_clarity_score``, ``ownership_signal_score``,
    ``technical_depth_score``, ``consistency_with_evidence_score``) are
    intentionally never included here — they are mapped to qualitative
    labels (``Demonstrated`` / ``Partially demonstrated`` /
    ``Supporting evidence`` / ``Needs review`` / ``Not assessed``).
    """

    transcript_summary: str = ""
    skills_mentioned: list[str] = Field(default_factory=list)
    skills_explained_well: list[str] = Field(default_factory=list)
    skills_missing_from_explanation: list[str] = Field(default_factory=list)
    overall_assessment: str = "Not assessed"
    explanation_clarity: str = "Not assessed"
    ownership_signal: str = "Not assessed"
    technical_depth: str = "Not assessed"
    consistency_with_evidence: str = "Not assessed"
    risk_flags: list[str] = Field(default_factory=list)
    recruiter_summary: str = ""
    recommended_improvements: list[str] = Field(default_factory=list)
    privacy_scan_status: str = "clean"

    model_config = {"extra": "forbid"}


class VBRStudentProjectReportResponse(BaseModel):
    project_id: str
    project_title: str
    project_description: str = ""
    repo_url: str = ""
    repo_full_name: str | None = None
    # A public deployed app URL, when the candidate provided one. Safe to link.
    deployed_url: str | None = None
    student_role: str = ""
    claimed_skills: list[str] = Field(default_factory=list)
    project_status: str = "draft"
    session_id: str | None = None
    generated_at: str

    evidence_package: VBRReportEvidencePackageSummary

    github_proof: VBRReportGitHubProofSummary | None = None
    documents: list[VBRReportDocumentSummary] = Field(default_factory=list)
    website_proofs: list[VBRReportWebsiteProofSummary] = Field(default_factory=list)

    project_defense_analysis: VBRReportProjectDefenseAnalysis | None = None
    defense_questions: list[VBRReportQuestionSummary] = Field(default_factory=list)
    video_evidence_chips: list[VideoEvidenceChipResponse] = Field(default_factory=list)

    skill_evidence: list[VBRReportSkillEvidenceRow] = Field(default_factory=list)
    # Flat list of every claim→evidence trace referenced by the skill matrix.
    evidence_traces: list[VBREvidenceTrace] = Field(default_factory=list)

    # "Other student proofs for related skills" — safe student-vault proofs that
    # match this report's claimed skills but are NOT attached to this project.
    # They are cross-proof / vault evidence, never folded into the primary
    # attached-proof skill matrix above, so the report stays project-honest.
    other_student_proofs: list[VaultSkillGroup] = Field(default_factory=list)

    limitations: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)

    preview_only: bool = True
    public_recruiter_sharing_enabled: bool = False
    note: str = (
        "This is a student preview of the evidence package collected for this project. "
        "It is private by default — use the controls below to publish a recruiter-safe "
        "link when you're ready to share."
    )

    model_config = {"extra": "forbid"}


__all__ = [
    "VBRReportGitHubProofSummary",
    "VBRReportDocumentSummary",
    "VBRReportWebsiteProofSummary",
    "VBRReportEvidencePackageSummary",
    "VBRReportQuestionSummary",
    "VBREvidenceTrace",
    "VaultProofItem",
    "VaultSkillGroup",
    "VaultSkillPreview",
    "VaultSkillSummary",
    "SkillReportEvidenceItem",
    "SkillReportProjectUsage",
    "SkillReportDocumentCorrelation",
    "SkillProofSynthesisStatement",
    "SkillProofSynthesisUnlinkedItem",
    "SkillProofSynthesisUnlinked",
    "SkillReportProjectChain",
    "SkillReportStandaloneEvidence",
    "SkillReportOverview",
    "SkillReportResponse",
    "VBRReportSkillEvidenceRow",
    "VBRReportProjectDefenseAnalysis",
    "VBRStudentProjectReportResponse",
]
