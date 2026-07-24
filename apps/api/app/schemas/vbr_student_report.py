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

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.canonical_evidence import ClaimEvidenceMap
from app.schemas.defense_answer_evidence import (
    DefenseAnswerEvidenceCard,
    ProjectDefenseInspectionCard,
)
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
    # Effective disclosure of this proof on the public surface: "summary"
    # (verified summary, repository access not enabled by the candidate) or
    # "viewable" (repository link may render). None on the owner preview.
    disclosure: str | None = None


class PublicArtifactViewRef(BaseModel):
    """Access-gated view route for one artifact the candidate chose to share.

    Never a storage path or signed URL — the route re-checks the disclosure
    policy on every request, so revoking the setting revokes the link.
    """

    view_path: str
    mime_type: str | None = None


class PublicDocumentSharedView(BaseModel):
    """Candidate-shared browser access to one document (view ≠ download)."""

    open_path: str
    mime_type: str | None = None
    page_count: int | None = None
    can_download: bool = False
    download_path: str | None = None


class VBRReportDocumentOriginalAccess(BaseModel):
    """Owner-only access descriptor for the RETAINED original document file.

    Present ONLY on the private student report — the public builder strips it,
    so recruiters keep safe excerpts/locators and never see a download action.
    Carries the opaque artifact id plus the access-gated view/download API
    routes; those routes re-check ownership on every request, so the descriptor
    is inert for anyone but the owner. Never a storage path, bucket, or signed
    URL. ``available=False`` is the honest not-retained state (older uploads,
    or retention storage unavailable), explained by ``note``.
    """

    available: bool = False
    artifact_id: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    page_count: int | None = None
    # Access-gated API routes (bytes stream after a per-request ownership
    # check) — never a storage path or signed URL.
    open_path: str | None = None
    download_path: str | None = None
    note: str | None = None

    model_config = {"extra": "forbid"}


class VBRReportDocumentSummary(BaseModel):
    title: str
    source_type: str | None = None
    status: str | None = None
    # Owner-only retained-original access (private report only; the public
    # projection strips it).
    original_document: VBRReportDocumentOriginalAccess | None = None
    # Effective public disclosure of this document ("summary" | "viewable").
    # The public projection sets it; the owner preview leaves the default.
    disclosure: str = "summary"
    # Candidate-shared browser access (public projection only, and only when
    # the document's disclosure is "viewable"). View and download are separate
    # grants — ``shared_view.can_download`` is False unless downloads were
    # explicitly enabled for this document.
    shared_view: PublicDocumentSharedView | None = None


class VBRReportWebsiteProofSummary(BaseModel):
    target_website: str = ""
    evidence_strength: str = "Not assessed"
    workflow_confidence: str = "insufficient"
    supported_skills: list[str] = Field(default_factory=list)
    # Candidate-shared screenshot/frame access (public projection only; empty
    # unless the website frames aspect is Viewable and frames were retained).
    frame_views: list[PublicArtifactViewRef] = Field(default_factory=list)
    # Candidate-shared walkthrough replay route (public projection only; None
    # unless the website video aspect is Viewable and a replay was retained).
    replay_path: str | None = None


class WebsiteProofSkillRelevance(BaseModel):
    """How ONE attached Website Proof's observed behaviour relates to ONE of the
    project's claimed skills — recomputed per report against the skill, never
    trusted from storage.

    Every field is a CLOSED-vocabulary label / already-safe helper sentence from
    ``website_skill_proof_focus`` — never a numeric score, never proof strength,
    never raw DOM/OCR/visual/provider text. Implementation-heavy skills (ML /
    GenAI / DevOps) can only ever read as *product behaviour / availability
    context* here (``is_direct_evidence`` stays False), so a demo UI can never
    overclaim source-code authorship or model/CI-CD internals."""

    skill_name: str
    relevance_key: str
    relevance_label: str
    relevance_summary: str
    limitation: str
    is_direct_evidence: bool = False
    # How this skill was mapped: "extracted" (named by the proof's stored
    # supported_skills) or "derived" (conservatively inferred from the safe
    # observed-behaviour classification). Honest provenance, never a score.
    mapping_basis: str = "extracted"

    model_config = {"extra": "forbid"}


class WebsiteProofSkillEvidence(BaseModel):
    """Skill-specific Website Behavior Evidence for ONE attached Website Proof —
    OWNER/PRIVATE project report only (kept off ``VBRReportWebsiteProofSummary``
    so it can never ride onto the public projection).

    ``behavior_claim`` / ``website_purpose_*`` classify WHAT the recorded page
    demonstrably showed, from a closed vocabulary derived only from the
    already-safe Website Proof summaries. ``skills`` carries an honest per-skill
    relevance ONLY for the project's claimed skills that the saved proof's
    EXTRACTED ``supported_skills`` name OR the observed behaviour genuinely
    demonstrates (conservative derivation — a generic/availability-only page maps
    nothing). Each row's ``mapping_basis`` records which. Empty ``skills`` with
    ``skill_mapping_available == False`` means the proof is captured but not
    mapped to a specific skill — the gap is stated honestly, never faked."""

    target_website: str = ""
    # Owner-only durable Website Proof navigation. Routes are access-gated; no
    # storage path or signed URL is serialized.
    website_replay_available: bool = False
    website_replay_path: str | None = None
    website_artifact_id: str | None = None
    website_analysis_path: str | None = None
    website_timeline: list[dict[str, Any]] = Field(default_factory=list)
    project_relationship_state: str = "legacy_unresolved"
    project_identity_state: str = "possible_match_review"
    project_identity_reasons: list[str] = Field(default_factory=list)
    counted_for_project: bool = False
    behavior_claim: str = ""
    website_purpose_key: str = ""
    website_purpose_label: str = ""
    website_purpose_summary: str = ""
    # ── Website Runtime Inspection (recruiter-facing deep inspection) ─────────
    # Section 1 skill-specific runtime claim (keyed by the PRIMARY mapped skill's
    # relevance; empty when nothing mapped). Section 2 target site / app / page
    # context + observed user action / visible output (closed per-purpose
    # sentences). Section 4 recruiter verification mode + checklist. All derived
    # from closed vocabularies + already-safe summaries — never raw payloads.
    runtime_claim_observed: str = ""
    target_domain: str = ""
    app_context: str = ""
    page_context_label: str = ""
    user_action_observed: str = ""
    output_observed: str = ""
    verification_mode: str = "recorded_replay_only"
    verification_mode_label: str = "Recorded replay only"
    recruiter_checklist: list[str] = Field(default_factory=list)
    # Which safe pipeline summaries backed this proof (closed labels only —
    # "Website DOM" / "Website OCR" / "Website visual analysis" / "Website NLP" /
    # "Website runtime behavior"). Never the raw text of any of them.
    evidence_source_types: list[str] = Field(default_factory=list)
    skills: list[WebsiteProofSkillRelevance] = Field(default_factory=list)
    skill_mapping_available: bool = False
    # Project-level-only explanation, populated ONLY when ``skill_mapping_available``
    # is False: a safe closed-vocabulary reason the observed behaviour did not map
    # to a specific skill, plus the concrete action to strengthen it. These make
    # the honest gap legible without ever faking a skill mapping. Empty when the
    # proof DID map a skill.
    unmapped_reason: str = ""
    strengthen_action: str = ""

    model_config = {"extra": "forbid"}



class RealUnmappedProofContext(BaseModel):
    """One REAL, analyzed, project-attached proof source that no exact claimed
    skill row consumed — PRIVATE surfaces only (owner report + owner passport).

    The honesty layer between exact skill evidence and hiding proof entirely:
    exact skill-mapped evidence stays exact; real analyzed-but-unmapped proof is
    shown separately with an honest reason. Strictly context — it is NEVER skill
    evidence, never counted in proof filter counts / capability aggregates /
    graph nodes, and never present on any public payload. Only closed labels and
    already-safe summaries: no proof/session/evidence ids, storage paths, signed
    URLs, raw transcripts/docs/DOM/OCR/provider text, or numeric scores. Fake
    metadata (a repo URL, a website URL, a filename, an unanswered question
    plan) can never produce an entry."""

    # Canonical proof-type label: "GitHub Proof" / "Website Proof" /
    # "Document Proof" / "Project Defense".
    proof_type: str
    project_id: str
    project_title: str = ""
    # Owner-only private route to this project's report preview.
    report_url: str | None = None
    # Honest closed reason the proof did not map to an exact skill row.
    reason: str = ""
    # One safe, bounded sentence describing the real analyzed proof.
    safe_summary: str = ""
    # Short label for the kind of analyzed evidence ("Analyzed source evidence",
    # a website observed-behaviour label, …).
    evidence_label: str | None = None
    observed_at: str | None = None
    # Count of analyzed evidence items backing this entry (never a score).
    source_count: int | None = None
    # In-page anchor of the matching proof section on the project report
    # ("github-proof" / "website-proof" / "documents" / "project-defense").
    inspection_anchor: str | None = None

    model_config = {"extra": "forbid"}


class VBRReportEvidencePackageSummary(BaseModel):
    github_proof_attached: bool = False
    documents_count: int = 0
    website_proofs_count: int = 0
    website_proofs_excluded_count: int = 0
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
    # ── Source-native document BLOCK locator (block-aware extraction) ─────────
    # The exact typed block the skill evidence came from (table / chart /
    # architecture_diagram / code_block / metric_result / …), its block index,
    # bounded table cells, an honest visual description, and the nearby caption.
    # ``has_exact_locator`` is the single counting gate: a document trace with
    # no exact locator is "text mentions skill" and stays context-only.
    block_type: str | None = None
    block_index: int | None = None
    table_cells: list[list[str]] = Field(default_factory=list)
    visual_description: str | None = None
    nearby_caption: str | None = None
    figure_reference: str | None = None
    has_exact_locator: bool = False
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
    # Website Proof owner-only retained replay/analysis descriptors. Never a
    # storage path or signed URL; routes re-check ownership at access time.
    website_replay_available: bool = False
    website_replay_path: str | None = None
    website_artifact_id: str | None = None
    website_replay_duration_seconds: float | None = None
    website_replay_mime_type: str | None = None
    website_analysis_path: str | None = None
    website_timeline: list[dict[str, Any]] = Field(default_factory=list)
    # Document Proof owner-only retained-original access descriptor (private
    # report only — the public trace projection blanks it).
    document_original: VBRReportDocumentOriginalAccess | None = None
    # Stable per-document disclosure key (owner surfaces only — every public
    # trace projection pops it before serialization).
    document_key: str | None = None
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
    evidence_quality_grade: str | None = None
    # Conservative DESCRIPTIVE code role (``documentation_header`` /
    # ``imports_setup`` / ``model_training`` / …) + its recruiter-readable label
    # ("Documentation / usage header"). Says what the block appears to be — never
    # proof strength; the quality grade above still governs that.
    code_role_key: str | None = None
    code_role_label: str | None = None
    # Block-level PURPOSE (finer than the role): what THIS exact block appears
    # to do, from a closed safe vocabulary ("Documentation describing retraining
    # pipeline", "Imports / dependency setup"), plus one short helper sentence.
    # Never proof strength; the quality grade above still governs that.
    code_block_purpose_key: str | None = None
    code_block_purpose_label: str | None = None
    code_block_purpose_summary: str | None = None
    # SKILL RELEVANCE: how this block relates to the skill it is filed under
    # ("Direct … implementation evidence", "Product UI context, not …
    # implementation"), from a closed template vocabulary. Descriptive only —
    # it never changes the quality grade above.
    skill_relevance_key: str | None = None
    skill_relevance_label: str | None = None
    skill_relevance_summary: str | None = None
    # Grade-time ML verdict from the trusted provenance body (plain tri-state bool /
    # None — never the raw snippet). Drives read-time ML semantic validation.
    ml_executable_signal: bool | None = None
    # Symbol identity + the ANALYZED context window from trusted provenance
    # (safe names/line numbers only). ``context_*`` may be wider than the cited
    # target lines; the citation itself is never rewritten to hide that.
    symbol_type: str | None = None
    context_start_line: int | None = None
    context_end_line: int | None = None
    analysis_version: str | None = None
    evidence_kind: str | None = None
    has_precise_line_evidence: bool | None = None
    github_line_url: str | None = None
    repo_url: str | None = None
    # Website-only canonical project/replay descriptors. Paths are owner-gated
    # application routes, never storage paths or signed URLs.
    project_hint: str | None = None
    project_relationship_state: str | None = None
    website_replay_available: bool | None = None
    website_replay_path: str | None = None
    website_artifact_id: str | None = None
    website_replay_duration_seconds: float | None = None
    website_replay_mime_type: str | None = None
    website_analysis_path: str | None = None
    # Canonical (old GitHub Profile & Proof engine) fields — precise
    # ``selection_reason`` + optional subskill / system-graph node.
    selection_reason: str | None = None
    subskill_name: str | None = None
    skill_graph_node: str | None = None
    page_number: int | None = None
    section_label: str | None = None
    citation: str | None = None
    # Safe document figure/diagram/table reference label + student recruiter-share
    # opt-in (documents only; ``None`` for every other proof type). Never a path.
    figure_reference: str | None = None
    full_document_available: bool | None = None
    # Source-native document BLOCK locator (block-aware extraction; documents
    # only, ``None`` elsewhere): the typed block, its index, bounded table
    # cells, an honest visual description, and the nearby caption.
    block_type: str | None = None
    block_index: int | None = None
    table_cells: list[list[str]] | None = None
    visual_description: str | None = None
    nearby_caption: str | None = None
    # Extra bounded, already-safe skill-related snippets/reasons for THIS skill
    # (documents only; ``None`` otherwise). Owner-only raw material the Document
    # Proof inspection card mines for deeper detail — never raw/full document text.
    detail_snippets: list[str] | None = None
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
    # Grouped, on-passport project relationship (the honest connected-project set).
    # ``project_ids`` above are RAW ``vbr_projects`` rows — one per Project Defense
    # attempt — so their count is inflated by duplicate attempts of the same real
    # project. These resolve those raw ids to the deduplicated representative
    # projects that actually appear on this passport, so the Skills Evidence Map can
    # show a truthful connected-project count and link to a real project card.
    connected_project_ids: list[str] = Field(default_factory=list)
    connected_project_titles: list[str] = Field(default_factory=list)
    # True when at least one retained, first-class proof source (GitHub / Document /
    # Website / Project Defense / Video) backs this skill — i.e. NOT only a derived
    # Skill-Graph/AI signal. A skill with ``has_retained_proof == False`` is a bare
    # suggestion: it must never render as "Evidence observed" and is kept out of the
    # default evidence map.
    has_retained_proof: bool = False
    proof_source_counts: dict[str, int] = Field(default_factory=dict)
    proof_count: int = 0
    attached_count: int = 0
    unattached_count: int = 0
    has_unattached: bool = False
    summary: str = ""
    previews: list[VaultSkillPreview] = Field(default_factory=list)
    more_count: int = 0
    limitations: list[str] = Field(default_factory=list)
    # Owner-only "how to strengthen this skill" sentences — deterministic,
    # qualitative, honest about unattached evidence. Never numeric, never on a
    # public surface (the compact vault dashboard is private-only).
    strengthening_actions: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


# ── Student Proof Vault: Layer 2 (full Skill Report) ─────────────────────────


class WebsiteEvidenceCard(BaseModel):
    """ONE recruiter-inspectable Website Evidence Card — the Website counterpart
    of GitHub's "View code lines" row.

    Answers: what page/route was observed, what behaviour was visible, what
    evidence backs it (basis chips), how it relates to THIS report's skill, and
    what it does NOT prove. Every field is a closed-vocabulary label, an
    already-sanitized summary, or a revalidated safe public URL. OCR/DOM/visual
    evidence appears ONLY as derived closed-template sentences — never raw
    payloads. Screenshot/keyframe evidence is an availability flag + closed
    access status; ``screenshot_preview_url`` stays ``None`` while keyframes
    live in private storage behind the candidate-permission thumbnail proxy."""

    # Stable key over safe display fields only — never a session/private ID.
    card_key: str
    route_or_page: str = "Recorded session"
    page_title: str | None = None
    # Date-only (YYYY-MM-DD) observation date; full timestamps are provenance
    # metadata the card does not carry.
    observed_at: str | None = None
    # Recruiter-first behaviour claim (closed vocabulary keyed by purpose) — the
    # first line the card renders: what live behaviour was demonstrably shown,
    # phrased as a checkable statement.
    behavior_claim: str = ""
    # ── Website Runtime Inspection (recruiter-facing deep inspection) ─────────
    # Section 1 — a concise SKILL-SPECIFIC claim about the recorded runtime
    # behaviour (closed template keyed by the conservative website→skill
    # relevance; ML/GenAI/DevOps can never overclaim).
    runtime_claim_observed: str = ""
    # Section 2 — target site / app context. ``target_url_safe`` survives only
    # when it passed the safe-public-url gate; ``target_domain`` is derived from a
    # safe URL only (a local/private capture leaves both None). ``app_context`` is
    # a recognised hosted-app name / page title / domain. ``page_context_label``
    # is a safe label for the pipeline's own closed OCR page-context enum.
    target_url_safe: str | None = None
    target_domain: str | None = None
    app_context: str | None = None
    page_context_label: str | None = None
    is_public_live_url: bool = False
    is_local_or_private_url: bool = False
    # Section 2 — the exact observed user action and visible output/result
    # (closed per-purpose sentences; None when the purpose demonstrates neither).
    # ``visible_text_observed`` is the SAFE OCR-derived closed sentence — never
    # raw OCR text; ``visited_pages_count`` stays None until a page count is
    # actually captured (the card never invents one).
    user_action_observed: str | None = None
    output_observed: str | None = None
    visible_text_observed: str | None = None
    visited_pages_count: int | None = None
    website_purpose_key: str
    website_purpose_label: str
    website_purpose_summary: str
    skill_relevance_key: str
    skill_relevance_label: str
    skill_relevance_summary: str
    # Section 4 — the recruiter verification checklist (open-and-reproduce for a
    # live proof; recorded-package/deploy guidance for a recorded-only proof).
    recruiter_checklist: list[str] = Field(default_factory=list)
    # Section 5/6 — honest note naming the missing runtime evidence + next step.
    missing_evidence_note: str | None = None
    observed_behavior_summary: str | None = None
    visual_evidence_summary: str | None = None
    ocr_evidence_summary_safe: str | None = None
    dom_evidence_summary_safe: str | None = None
    evidence_basis_chips: list[str] = Field(default_factory=list)
    limitation: str
    # Recruiter verification mode (GitHub-Proof-style inspection split).
    # "directly_verifiable_live" when a public safe live URL is available (the
    # recruiter can open the current site); "recorded_replay_only" when the proof
    # was captured from a local/private/preview host so only VeriBridge's recorded
    # replay is available. ``verification_mode_label`` / ``verification_note`` are
    # closed recruiter copy; ``deployment_recommended`` flags the replay-only case.
    verification_mode: str = "recorded_replay_only"
    verification_mode_label: str = "Recorded replay only"
    verification_note: str = ""
    deployment_recommended: bool = False
    open_website_url: str | None = None
    screenshot_available: bool = False
    # "private_candidate_permission_required" | "unavailable" (closed enum).
    screenshot_access_label: str = "unavailable"
    screenshot_preview_url: str | None = None
    # Cross-proof corroboration — set ONLY by the vault service's confirmed
    # project-chain pass (``attach_website_corroboration``): whether GitHub /
    # Defense / Document evidence for the SAME VBR project backs this behaviour,
    # a closed-fragment sentence naming those companions, and the already-safe
    # connected project title. Always false/None for unattached proofs.
    corroborates_github: bool = False
    corroborates_defense: bool = False
    corroborates_document: bool = False
    corroboration_note: str | None = None
    connected_project_title: str | None = None

    model_config = {"extra": "forbid"}


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
    evidence_quality_grade: str | None = None
    # Conservative DESCRIPTIVE code role, resolved at read time against the
    # VALIDATED grade (``documentation_header`` / ``imports_setup`` /
    # ``model_training`` / …) + its recruiter-readable label ("Documentation /
    # usage header"). Says what the block appears to be — never proof strength;
    # a weak row keeps an honest role label while staying under Needs review.
    code_role_key: str | None = None
    code_role_label: str | None = None
    # Block-level PURPOSE, resolved at read time against the VALIDATED grade:
    # what THIS exact block appears to do (closed vocabulary — "Documentation
    # describing retraining pipeline", "Imports / dependency setup", "Model
    # training") plus one short safe helper sentence. A label only; it never
    # promotes a weak row out of Needs review.
    code_block_purpose_key: str | None = None
    code_block_purpose_label: str | None = None
    code_block_purpose_summary: str | None = None
    # SKILL RELEVANCE, computed at read time from the resolved purpose × this
    # report's skill family × the VALIDATED grade ("Direct Machine Learning
    # implementation evidence", "Product UI context, not Machine Learning
    # implementation"), plus one short safe helper sentence. A label only; it
    # never promotes a weak row out of Needs review, and cross-family evidence
    # never counts toward the selected skill.
    skill_relevance_key: str | None = None
    skill_relevance_label: str | None = None
    skill_relevance_summary: str | None = None
    # Grade-time ML verdict from the trusted provenance body (a plain tri-state
    # bool / None — never the raw snippet). Drives read-time ML semantic validation
    # so a deployment-only body can never present as ML primary implementation proof.
    ml_executable_signal: bool | None = None
    # Symbol identity + the ANALYZED context window from trusted provenance
    # (safe names/line numbers only). ``context_start/end_line`` may be wider
    # than the cited target lines — shown as "Analyzed context" so the target
    # citation is never rewritten to pretend the wider window was the target.
    symbol_type: str | None = None
    context_start_line: int | None = None
    context_end_line: int | None = None
    analysis_version: str | None = None
    evidence_kind: str | None = None
    has_precise_line_evidence: bool | None = None
    github_line_url: str | None = None
    repo_url: str | None = None
    project_hint: str | None = None
    project_relationship_state: str | None = None
    website_replay_available: bool = False
    website_replay_path: str | None = None
    website_artifact_id: str | None = None
    website_replay_duration_seconds: float | None = None
    website_replay_mime_type: str | None = None
    website_analysis_path: str | None = None
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
    # Safe figure/diagram/table reference label (documents only; never the raw
    # figure). ``full_document_available`` reflects the student's explicit
    # recruiter-share opt-in — a plain bool, never a storage path or signed URL.
    figure_reference: str | None = None
    full_document_available: bool = False
    # Source-native document BLOCK locator (block-aware extraction; documents
    # only): typed block, block index, bounded table cells, visual description,
    # nearby caption. Never raw file bytes or storage paths.
    block_type: str | None = None
    block_index: int | None = None
    table_cells: list[list[str]] = Field(default_factory=list)
    visual_description: str | None = None
    nearby_caption: str | None = None
    # Defense / video locators
    question_text: str | None = None
    answer_excerpt: str | None = None
    timestamp_label: str | None = None
    # Website-only hydrated safe summaries
    workflow_summary: str | None = None
    workflow_steps: list[str] = Field(default_factory=list)
    workflow_timeline: list[dict[str, Any]] = Field(default_factory=list)
    dom_summary: str | None = None
    ocr_summary: str | None = None
    visual_summary: str | None = None
    live_check: dict | None = None
    # Website semantic proof fields (website items only; ``None`` for every other
    # proof type). PURPOSE: what the recorded page demonstrably showed, from a
    # closed vocabulary ("Chat / prompt interface", "Prediction / result
    # display") derived only from already-safe summaries. SKILL RELEVANCE: how
    # that observed behaviour relates to THIS report's selected skill, recomputed
    # at read time ("Direct React evidence", "Machine Learning product behaviour
    # context — not implementation proof"). Labels only — never proof strength,
    # and a UI demo can never read as ML/GenAI/DevOps implementation proof.
    website_purpose_key: str | None = None
    website_purpose_label: str | None = None
    website_purpose_summary: str | None = None
    website_skill_relevance_key: str | None = None
    website_skill_relevance_label: str | None = None
    website_skill_relevance_summary: str | None = None
    # ONE structured, recruiter-inspectable Website Evidence Card (website items
    # only) — the Website counterpart of GitHub's "View code lines" row. Built
    # entirely from closed vocabularies + already-safe summaries; never raw
    # DOM/OCR/frame/provider payloads, storage paths, signed URLs or private IDs.
    website_evidence_card: WebsiteEvidenceCard | None = None

    model_config = {"extra": "forbid"}


class DocumentProofInspectionCard(BaseModel):
    """Skill-specific, recruiter-facing *inspection* view of one Document Proof.

    The Document-Proof analogue of the GitHub / Website "inspection" card: it shows
    a recruiter exactly WHAT the document says (a bounded safe snippet), WHERE it
    says it (page / section / citation / figure-table locator), and WHY that
    supports the SELECTED skill — never a whole-document dump. It is deliberately
    a closed set of safe fields: it NEVER carries raw document text, OCR/provider
    JSON, storage/bucket paths, signed URLs, or internal document ids. The only
    URLs it may carry are ``document_download_url`` / ``document_open_url``, and
    only when :attr:`can_download_document` is true and the URL is an intentionally
    authorized/safe link (a public projection forces both to ``None``).

    ``safe_snippet`` is shown to the owner but is stripped on a public projection
    unless :attr:`is_public_safe` is explicitly true — recruiters otherwise see
    only the locator + why-supported, never the excerpt."""

    title: str = ""
    source_type: str | None = None
    status: str | None = None
    # The selected skill this card was built for, and the project it is attached to.
    matched_skill: str | None = None
    project_title: str | None = None
    # "Supporting evidence" (default) / "Corroborating document" (attached chain).
    evidence_role: str = "Supporting evidence"
    # Safe locators (never a storage path / raw text): page, section, citation.
    page_number: int | None = None
    section_label: str | None = None
    citation_label: str | None = None
    # Bounded, skill-related excerpt only — never the raw/full document. Stripped
    # on a public projection unless ``is_public_safe`` is explicitly true.
    safe_snippet: str | None = None
    # Safe figure/table/diagram REFERENCE labels (e.g. "Figure 3", "Table 1") —
    # never the raw image/text — plus a short safe caption/summary when available.
    figure_reference: str | None = None
    table_reference: str | None = None
    diagram_reference: str | None = None
    visual_or_table_summary: str | None = None
    # Why this document supports the selected skill (safe reason, deterministic
    # fallback), the stronger evidence it corroborates, and the limitation copy.
    why_supported: str = ""
    corroborates: str | None = None
    limitation: str = ""
    # ── Skill-specific detail lists (bounded, normalized, already-safe strings) ──
    # Deeper-than-one-sentence evidence for the SELECTED skill, mined ONLY from the
    # analyzer's own bounded safe snippets/reasons for THIS skill — never raw/full
    # document text, and never invented. Each list is deduped and capped. When the
    # document only supports the skill at the claim level, the technical lists stay
    # empty and ``missing_detail_note`` explains exactly what was not extracted.
    #
    # ``skill_specific_claims``  — claim-level statements about the skill.
    # ``technical_details``      — concrete mechanism statements (deeper than a claim).
    # ``api_endpoints``          — endpoint/route/REST mentions (API skills only).
    # ``request_response_details`` — request/response/schema mentions (API skills).
    # ``architecture_details``   — backend/service/architecture/integration mentions.
    # ``implementation_hints``   — other bounded implementation-flavored detail.
    skill_specific_claims: list[str] = Field(default_factory=list)
    technical_details: list[str] = Field(default_factory=list)
    api_endpoints: list[str] = Field(default_factory=list)
    request_response_details: list[str] = Field(default_factory=list)
    architecture_details: list[str] = Field(default_factory=list)
    implementation_hints: list[str] = Field(default_factory=list)
    # Safe "what is still missing" note when exact (e.g. endpoint-level) detail was
    # not extracted — points the recruiter at GitHub Proof / Project Defense.
    missing_detail_note: str | None = None
    # Whether ANY skill-specific detail (claim or technical) was found for the skill.
    has_skill_specific_details: bool = False
    # Safe, human download/open gating note — never a path or signed URL. The legacy
    # ``access_note`` is kept for back-compat; ``document_access_note`` carries the
    # fuller, honest explanation and ``document_access_label`` the button label.
    access_note: str = ""
    document_access_label: str | None = None
    document_access_note: str = ""
    # Download/open is gated on explicit student consent AND a safe endpoint. When
    # no safe URL exists both URLs stay ``None`` and the UI shows a disabled state.
    can_download_document: bool = False
    document_download_url: str | None = None
    document_open_url: str | None = None
    # Whether the safe_snippet is explicitly public-safe, and whether the document
    # is attached to a VBR project.
    is_public_safe: bool = False
    is_attached_to_project: bool = False
    # ── Artifact retention (migration 056) ────────────────────────────────────
    # Whether the ORIGINAL uploaded file is retained as a gated proof artifact.
    # ``document_artifact_id`` is the opaque artifact id for the authorized
    # view/download routes (/api/v1/proofs/artifacts/{id}/…) — NEVER a storage
    # path or signed URL; access is still enforced server-side per request, so
    # a non-owner holding the id of a private artifact gets an indistinct 404.
    document_retained: bool = False
    document_artifact_id: str | None = None

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
    # Safe figure/diagram/table reference label (e.g. "Figure 3") — never the raw
    # figure/image/text.
    figure_reference: str | None = None
    # Source-native document BLOCK locator (block-aware extraction; ``None`` on
    # pre-block documents): typed block, block index, bounded table cells,
    # honest visual description, nearby caption. Never file bytes or paths.
    block_type: str | None = None
    block_index: int | None = None
    table_cells: list[list[str]] = Field(default_factory=list)
    visual_description: str | None = None
    nearby_caption: str | None = None
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
    # Why this page/section supports the skill (safe analyzer reason, with a
    # deterministic fallback).
    why_supported: str = ""
    # Full-document download is gated on the student's explicit recruiter-share
    # opt-in. ``full_document_available`` is a plain bool; ``document_access_note``
    # carries the safe gating message — never a storage path or signed URL.
    full_document_available: bool = False
    document_access_note: str = ""
    limitation: str = ""
    # Skill-specific inspection view of this document (what it says, where, and why
    # it supports the SELECTED skill) — the recruiter-facing Document Proof
    # inspection card. ``None`` on legacy payloads built before this field existed.
    inspection_card: DocumentProofInspectionCard | None = None
    # Whether the ORIGINAL uploaded file is retained as a gated proof artifact
    # (see DocumentProofInspectionCard.document_retained for the access detail).
    document_retained: bool = False

    model_config = {"extra": "forbid"}


class SkillReportDefenseMoment(BaseModel):
    """One cited Project Defense / video moment inside the grouped defense section.

    A safe, timestamped explanation moment — never raw transcript text. Only the
    label, optional timestamp/question, and a bounded safe summary are surfaced."""

    label: str = ""
    timestamp_label: str | None = None
    question_text: str | None = None
    short_summary: str = ""
    source_id: str = ""

    model_config = {"extra": "forbid"}


class SkillReportDefenseGroup(BaseModel):
    """All Project Defense + Video evidence for one chain, grouped into ONE section.

    Repeated defense attempts for the same project produced many near-identical
    "the candidate explained their work" cards. This collapses them into a single
    "Defense / video explanation" section: one concise explanation, the combined
    cited moments/chips, one limitation, and the count of grouped evidence items
    (no evidence is lost — the raw ``defense_evidence`` / ``video_evidence`` lists
    are still present on the chain)."""

    explanation: str = ""
    moments: list[SkillReportDefenseMoment] = Field(default_factory=list)
    grouped_count: int = 0
    limitation: str = ""
    source_ids: list[str] = Field(default_factory=list)

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


class NormalizedEvidenceArtifact(BaseModel):
    """One proof normalized into the Evidence Normalization Engine's uniform shape.

    A single internal model across every proof surface (GitHub / Website /
    Document / Defense / Video / Skill Graph) that the Proof Synthesis Agent
    consumes instead of each source's own messy shape. ``metadata`` holds only
    already-safe internal locators; it is dropped from any public-safe projection.
    """

    evidence_id: str = ""
    source_type: str = ""
    skill_name: str | None = None
    canonical_skill_name: str | None = None
    subskill_name: str | None = None
    project_id: str | None = None
    project_title: str | None = None
    source_id: str = ""
    source_label: str = ""
    exact_location: str | None = None
    safe_summary: str = ""
    proof_strength: str = ""
    public_safe: bool = False
    limitations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class GitHubEvidenceAssessment(BaseModel):
    """Smart GitHub Evidence quality assessment for one proof chain.

    Deterministic, qualitative (never a numeric score). ``strength`` is one of
    ``implementation`` / ``supporting`` / ``weak`` / ``none``; ``label`` and
    ``note`` are recruiter-facing honest proof wording ("Primary GitHub
    implementation evidence: …", "Supporting GitHub evidence: …", or an honest
    insufficiency limitation)."""

    strength: str = "none"
    label: str = ""
    note: str = ""

    model_config = {"extra": "forbid"}


class SkillReportVideoProofSkillSupport(BaseModel):
    """One claimed skill on a Video Proof and its honest evidential basis.

    ``basis`` is a closed set: ``mentioned_in_narration`` (the skill name
    literally appears in the transcript) or ``claimed_only``. ``verified`` is
    ALWAYS false — a demo video never verifies a skill by itself."""

    skill: str = ""
    basis: str = "claimed_only"
    verified: bool = False

    model_config = {"extra": "forbid"}


class SkillReportVideoProofCard(BaseModel):
    """One first-class Video Proof (uploaded/recorded demo video) in a Skill Report.

    A safe projection of a ``video_proofs`` row (migration 057): availability
    flags + the deterministic analysis summary. It never carries storage paths,
    signed URLs, raw transcript text, or frame bytes — playback/transcript/frames
    load lazily through the gated artifact / video-proof routes using the opaque
    ids here (access re-checked server-side per request).

    Epistemics: ``proof_strength_label`` and ``limitations`` state verbatim what
    a demo video can and cannot prove; ``needs_review`` defaults true and
    ``skills_supported`` entries are never verified."""

    proof_id: str = ""
    title: str = ""
    source_kind: str = "uploaded_demo"
    source_kind_label: str = "Demo video"
    duration_label: str | None = None
    # Availability flags — derived ONLY from genuinely retained/extracted data.
    replay_available: bool = False
    transcript_available: bool = False
    frames_available: bool = False
    segment_count: int = 0
    frame_count: int = 0
    # Opaque artifact id for gated playback (never a path / signed URL).
    original_artifact_id: str | None = None
    # Deterministic analysis (facts only — see video_proof_service).
    demo_summary: str = ""
    proof_strength_label: str = ""
    skills_supported: list[SkillReportVideoProofSkillSupport] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    corroborates_with: list[str] = Field(default_factory=list)
    needs_review: bool = True
    public_safe: bool = False

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
    # This chain's GitHub implementation evidence grouped by canonical owner/repo —
    # the SAME compact, repository-grouped projection used for standalone GitHub
    # (``SkillReportStandaloneGitHubGroup``) so connected "Code implementation"
    # renders one grouped block per repo with compact file/line rows. Additive:
    # ``github_evidence`` above stays for back-compat; the UI prefers these groups.
    github_groups: list["SkillReportStandaloneGitHubGroup"] = Field(default_factory=list)
    website_evidence: list[SkillReportEvidenceItem] = Field(default_factory=list)
    document_correlations: list[SkillReportDocumentCorrelation] = Field(default_factory=list)
    document_more_count: int = 0
    defense_evidence: list[SkillReportEvidenceItem] = Field(default_factory=list)
    video_evidence: list[SkillReportEvidenceItem] = Field(default_factory=list)
    # First-class Video Proofs (uploaded/recorded demo videos, migration 057)
    # attached to this chain's project(s) and claiming this report's skill.
    # Distinct from ``video_evidence`` (timestamped moments inside a Project
    # Defense recording) — these are standalone demo videos with their own
    # retention + honest deterministic analysis.
    video_proofs: list[SkillReportVideoProofCard] = Field(default_factory=list)
    # Project Defense + Video evidence collapsed into ONE grouped section so the
    # chain never renders many repeated "the candidate explained their work"
    # cards. ``None`` when the chain has no defense/video evidence.
    defense_group: SkillReportDefenseGroup | None = None
    # First-class Project Defense inspection cards for THIS chain, scoped to the
    # report's skill (owner view). Explanation / corroboration evidence only;
    # untargeted transcript moments never appear here.
    project_defense_inspection: list[ProjectDefenseInspectionCard] = Field(default_factory=list)
    # One safe sentence explaining how this chain's Website Proof corroborates
    # its other sources ("the website demonstrates the product behaviour, GitHub
    # code shows the implementation, the Project Defense shows the candidate's
    # own understanding"). ``None`` when the chain has no website evidence or
    # nothing to connect it to.
    website_connection_note: str | None = None
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
    # Step 2: this chain's evidence collapsed into the uniform normalized model.
    normalized_evidence: list[NormalizedEvidenceArtifact] = Field(default_factory=list)
    # Smart GitHub Evidence assessment for this chain: whether GitHub is primary
    # implementation proof (``implementation_body``), supporting code
    # (``supporting_logic``), or only weak/repo-level — with honest wording.
    github_evidence_assessment: GitHubEvidenceAssessment | None = None
    # True only when this chain has a real GitHub implementation *body* (the
    # strongest artifact proof) — never merely supporting/weak precise lines.
    has_primary_github_implementation: bool = False

    model_config = {"extra": "forbid"}


class SkillReportStandaloneGitHubRow(BaseModel):
    """One compact code-location row inside a standalone GitHub repository group.

    A single safe line/file locator (never a full evidence card) so several code
    lines from the same repo render as compact grouped rows instead of one
    repeated card per line. Carries only safe locators + a public ``…#L`` link."""

    source_id: str = ""
    # Human "file · lines / function()" label (e.g. "Tree.py · lines 13-72").
    label: str = ""
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    function_name: str | None = None
    display_mode: str | None = None
    # Deterministic quality band (implementation_body / supporting_logic /
    # config_or_constant / comment_or_docstring / import_only / route_decorator_only
    # / repo_level_fallback). The frontend ranks/excludes weak rows by this grade so
    # a route-decorator / docstring / import / fallback row never renders like real
    # implementation code when a strong row exists for the same repo.
    evidence_quality_grade: str | None = None
    # Conservative DESCRIPTIVE code role for this block (already resolved against
    # the validated grade): key ("documentation_header" / "imports_setup" /
    # "model_training" / …) + recruiter-readable label ("Documentation / usage
    # header"). A weak row renders this honest role instead of a stale
    # ``selection_reason``; it never changes the quality grade above.
    code_role_key: str | None = None
    code_role_label: str | None = None
    # Block-level PURPOSE for this exact row (closed safe vocabulary + one short
    # helper sentence). The frontend prefers this over the role label on weak
    # rows; it is descriptive only and never changes the quality grade above.
    code_block_purpose_key: str | None = None
    code_block_purpose_label: str | None = None
    code_block_purpose_summary: str | None = None
    # SKILL RELEVANCE for this row relative to the report's skill (closed template
    # vocabulary + one short helper sentence). Descriptive only; it never promotes
    # a weak row out of Needs review.
    skill_relevance_key: str | None = None
    skill_relevance_label: str | None = None
    skill_relevance_summary: str | None = None
    # Precise "why selected" reason ("ML training call"), when the analyzer set it.
    selection_reason: str | None = None
    github_line_url: str | None = None
    public_url: str | None = None

    model_config = {"extra": "forbid"}


class SkillReportStandaloneGitHubGroup(BaseModel):
    """Standalone GitHub evidence grouped by repository (compact rows, not cards).

    Several code lines that belong to the same standalone repository are collapsed
    into ONE repository group with compact ``rows`` instead of one full evidence
    card per line — so "Standalone GitHub evidence — Stroke Prediction Model" reads
    as a single grouped block. ``repo_url`` is only set when the repo is public."""

    repo_label: str = ""
    repo_url: str | None = None
    repo_is_public: bool = False
    rows: list[SkillReportStandaloneGitHubRow] = Field(default_factory=list)
    # How many of ``rows`` are initially collapsed behind the "+N more code
    # locations" toggle. ALL counted rows are present in ``rows`` (the overflow is
    # not dropped) so the frontend can reveal them inline; ``0`` means every row
    # is shown by default.
    row_more_count: int = 0

    model_config = {"extra": "forbid"}


class SkillReportStandaloneEvidence(BaseModel):
    """Proofs supporting a skill that are not attached to any VBR project."""

    github: list[SkillReportEvidenceItem] = Field(default_factory=list)
    # Standalone GitHub evidence grouped by repository — compact rows per repo so
    # multiple lines from one repo never render as repeated full cards. Additive:
    # ``github`` above stays for back-compat; ``github_groups`` is the primary,
    # de-duplicated, repository-grouped projection the UI should render.
    github_groups: list[SkillReportStandaloneGitHubGroup] = Field(default_factory=list)
    website: list[SkillReportEvidenceItem] = Field(default_factory=list)
    documents: list[SkillReportDocumentCorrelation] = Field(default_factory=list)
    document_more_count: int = 0
    defense: list[SkillReportEvidenceItem] = Field(default_factory=list)
    video: list[SkillReportEvidenceItem] = Field(default_factory=list)
    # First-class Video Proofs claiming this skill that are not attached to any
    # chain project (or whose project has no chain in this report).
    video_proofs: list[SkillReportVideoProofCard] = Field(default_factory=list)
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
    # ── Cross-Proof Linking Engine output (Step 3) ────────────────────────────
    # Deterministically linked proof chains across normalized evidence (same
    # project / repo / endpoint / function). Each carries safe ``ev_…`` evidence
    # ids so later synthesis can cite the exact evidence. Additive — the existing
    # ``proof_chains`` above remain the primary recruiter-facing chains.
    linked_proof_chains: list[dict[str, Any]] = Field(default_factory=list)
    # ── LLM Synthesis Layer output (Step 4) ───────────────────────────────────
    # Recruiter-readable synthesis claims over the linked proof chains. Every claim
    # cites existing ``ev_…`` evidence ids (never invented), its qualitative tier is
    # clamped to the deterministic ceiling (never promoted), and all strings are
    # scrubbed. Falls back to a deterministic rule-based synthesis when no LLM is
    # available. Additive — the deterministic chains above remain primary.
    llm_synthesis: list[dict[str, Any]] = Field(default_factory=list)
    # Flat per-source lists (back-compat; the connected chains above are primary).
    github: list[SkillReportEvidenceItem] = Field(default_factory=list)
    website: list[SkillReportEvidenceItem] = Field(default_factory=list)
    documents: list[SkillReportEvidenceItem] = Field(default_factory=list)
    defense: list[SkillReportEvidenceItem] = Field(default_factory=list)
    video: list[SkillReportEvidenceItem] = Field(default_factory=list)
    skill_graph: list[SkillReportEvidenceItem] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    generated_at: str = ""
    # Canonical claim→evidence map (deterministic; shared contract with the
    # Project Report — see ``app.schemas.canonical_evidence``). ``None`` on
    # legacy payloads built before this field existed.
    claim_evidence_map: ClaimEvidenceMap | None = None

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


class ProofAttachmentEntry(BaseModel):
    """One deduplicated proof entry from the attachment intelligence helper
    (owner-only surfaces: private passport overview, report "suggested
    evidence to attach").

    Safe display fields only: no source ids/tables, storage paths, signed URLs,
    raw text, or provider payloads. ``entry_id_safe`` is a one-way digest.
    ``relation_strength`` is a closed label ("deterministic" / "likely" /
    "weak" / "none") — never a numeric confidence. Only deterministic entries
    are ever counted as attached; suggested evidence is explicitly labelled
    "not counted until attached".
    """

    entry_id_safe: str = ""
    proof_type: str = ""
    display_title: str = ""
    source_label: str = ""
    attachment_state: str = ""
    relation_reason: str = ""
    relation_strength: str = ""
    reason_label: str = ""
    status_label: str = ""
    project_titles: list[str] = Field(default_factory=list)
    # Owner-only project-report routes (never on a public projection).
    project_refs_safe: list[str] = Field(default_factory=list)
    skill_names: list[str] = Field(default_factory=list)
    # How many duplicate vault rows collapsed into this one entry.
    duplicate_count: int = 1

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
    # Skill-specific Website Behavior Evidence (owner/private view only). One entry
    # per attached Website Proof: what the recorded page demonstrably showed plus,
    # for each claimed skill the saved proof's extracted supported-skills actually
    # name, an honest per-skill relevance + limitation. Never on the public
    # projection (the public builder whitelists fields and omits this one).
    website_skill_evidence: list[WebsiteProofSkillEvidence] = Field(default_factory=list)

    project_defense_analysis: VBRReportProjectDefenseAnalysis | None = None
    defense_questions: list[VBRReportQuestionSummary] = Field(default_factory=list)
    # Claim-level, question-grounded Defense Answer Evidence cards (owner view).
    defense_answer_evidence: list[DefenseAnswerEvidenceCard] = Field(default_factory=list)
    # First-class Project Defense inspection cards (owner view) — the defense
    # parallel to GitHub / Website / Document inspection.
    project_defense_inspection: list[ProjectDefenseInspectionCard] = Field(default_factory=list)
    video_evidence_chips: list[VideoEvidenceChipResponse] = Field(default_factory=list)

    skill_evidence: list[VBRReportSkillEvidenceRow] = Field(default_factory=list)
    # Flat list of every claim→evidence trace referenced by the skill matrix.
    evidence_traces: list[VBREvidenceTrace] = Field(default_factory=list)

    # REAL analyzed, project-attached proof that no exact skill row consumed —
    # "Attached proof not yet skill-mapped". Context only (never skill evidence,
    # never counted, never public); private student preview surface only.
    real_unmapped_proof_context: list[RealUnmappedProofContext] = Field(default_factory=list)

    # "Other student proofs for related skills" — safe student-vault proofs that
    # match this report's claimed skills but are NOT attached to this project.
    # They are cross-proof / vault evidence, never folded into the primary
    # attached-proof skill matrix above, so the report stays project-honest.
    other_student_proofs: list[VaultSkillGroup] = Field(default_factory=list)

    # "Suggested evidence to attach" (owner-only): unattached vault proofs whose
    # safe metadata points at this project. Clearly labelled "not counted until
    # attached" — never part of the attached evidence package above, and never
    # on the public report projection.
    suggested_evidence: list[ProofAttachmentEntry] = Field(default_factory=list)

    limitations: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)

    # Canonical claim→evidence map (deterministic; shared contract with the
    # Skill Report — see ``app.schemas.canonical_evidence``). ``None`` when the
    # builder skipped it (multi-project passport path) or on legacy payloads.
    claim_evidence_map: ClaimEvidenceMap | None = None

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
    "VBRReportDocumentOriginalAccess",
    "VBRReportDocumentSummary",
    "VBRReportWebsiteProofSummary",
    "WebsiteProofSkillRelevance",
    "WebsiteProofSkillEvidence",
    "RealUnmappedProofContext",
    "VBRReportEvidencePackageSummary",
    "VBRReportQuestionSummary",
    "VBREvidenceTrace",
    "VaultProofItem",
    "VaultSkillGroup",
    "VaultSkillPreview",
    "VaultSkillSummary",
    "SkillReportEvidenceItem",
    "SkillReportProjectUsage",
    "DocumentProofInspectionCard",
    "SkillReportDocumentCorrelation",
    "SkillProofSynthesisStatement",
    "SkillProofSynthesisUnlinkedItem",
    "SkillProofSynthesisUnlinked",
    "SkillReportVideoProofSkillSupport",
    "SkillReportVideoProofCard",
    "SkillReportProjectChain",
    "SkillReportStandaloneEvidence",
    "SkillReportOverview",
    "SkillReportResponse",
    "VBRReportSkillEvidenceRow",
    "VBRReportProjectDefenseAnalysis",
    "ProofAttachmentEntry",
    "VBRStudentProjectReportResponse",
]
