"""Schemas for the Verified Work Passport (v1).

Three surfaces:

* ``PublishPassportRequest`` / ``WorkPassportStatusResponse`` — owner-only
  publish controls. ``public_slug`` / ``public_path`` are only ever returned to
  the authenticated owner, and only while the passport is published.
* ``PrivateWorkPassportResponse`` — the owner-only evidence wallet. Reuses the
  already-sanitized qualitative skill labels; never numeric trust scores.
* ``PublicWorkPassportResponse`` — the recruiter-safe public profile. Omits the
  candidate's email, auth user id, internal project/session ids, raw evidence,
  storage paths, tokens (other than the intentionally-linked public report
  paths), and any numeric trust score.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.vbr_student_report import VaultSkillSummary, VBREvidenceTrace


# ── Owner-only publish controls ──────────────────────────────────────────────


class PublishPassportRequest(BaseModel):
    """Optional public-safe profile text supplied when publishing."""

    headline: str | None = Field(default=None, max_length=160)
    summary: str | None = Field(default=None, max_length=600)

    model_config = {"extra": "forbid"}


class WorkPassportStatusResponse(BaseModel):
    is_published: bool = False
    public_slug: str | None = None
    public_path: str | None = None
    published_at: str | None = None
    headline: str = ""
    summary: str = ""

    model_config = {"extra": "forbid"}


# ── Shared evidence-summary models ───────────────────────────────────────────


class PassportSkillEvidenceChip(BaseModel):
    """A sanitized skill-evidence snippet (no timestamps tied to raw media,
    no storage paths). Used in the skill drilldown."""

    label: str = ""
    short_summary: str = ""
    source: str = ""

    model_config = {"extra": "forbid"}


class PassportSkillProjectRef(BaseModel):
    """A project that supports a skill, as shown in the skill drilldown.

    ``project_id`` is owner-only (used to link to the private report preview)
    and is omitted from the public projection. ``public_report_path`` is the
    recruiter-safe link, present only when the project's report is published.
    """

    project_title: str = ""
    project_id: str | None = None
    # This project's qualitative status FOR THIS SKILL (not the cross-project best).
    skill_status: str = "Not assessed"
    evidence_sources: list[str] = Field(default_factory=list)
    report_is_public: bool = False
    public_report_path: str | None = None
    # The proof-native trace cards this project contributes for this skill.
    evidence_traces: list[VBREvidenceTrace] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class PassportStrongestProjectLink(BaseModel):
    """Skill → Project cross-link: the project where a skill is most strongly
    evidenced, as a linkable reference.

    ``project_id`` / ``project_report_path`` are owner-only (the private report
    preview route) and are never present on the public projection — the public
    shape carries only the published ``public_report_path``.
    """

    project_title: str = ""
    # This project's qualitative label FOR THIS SKILL (never a numeric score).
    skill_status: str = "Not assessed"
    evidence_sources: list[str] = Field(default_factory=list)
    report_is_public: bool = False
    public_report_path: str | None = None
    project_id: str | None = None
    project_report_path: str | None = None

    model_config = {"extra": "forbid"}


class PassportSkillSummary(BaseModel):
    """A grouped, evidence-backed skill. ``status`` is always a qualitative
    label — never a numeric trust/confidence score."""

    skill: str
    status: str
    evidence_chip_count: int = 0
    project_count: int = 1
    # Skill drilldown detail (safe, qualitative-only).
    evidence_sources: list[str] = Field(default_factory=list)
    projects: list[PassportSkillProjectRef] = Field(default_factory=list)
    evidence_chips: list[PassportSkillEvidenceChip] = Field(default_factory=list)
    # Aggregated claim→evidence traces across this candidate's projects.
    evidence_traces: list[VBREvidenceTrace] = Field(default_factory=list)
    # The single project where this skill is most strongly evidenced (title +
    # that project's qualitative label for this skill). Owner-only.
    strongest_project_title: str | None = None
    strongest_project_status: str | None = None
    # The same strongest project as a linkable reference (owner-only routes).
    strongest_project: PassportStrongestProjectLink | None = None
    notes: str = ""
    limitations: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class PublicPassportStrongestProject(BaseModel):
    """Public strongest-project reference — title, per-skill qualitative label
    and the published report path only. Never an internal id or private route."""

    project_title: str = ""
    skill_status: str = "Not assessed"
    evidence_sources: list[str] = Field(default_factory=list)
    public_report_path: str

    model_config = {"extra": "forbid"}


class PublicPassportSkillProjectRef(BaseModel):
    """A published project supporting a public skill — no internal ids."""

    project_title: str = ""
    # Per-project qualitative status for this skill (label only).
    skill_status: str = "Not assessed"
    evidence_sources: list[str] = Field(default_factory=list)
    public_report_path: str
    # Per-project trace cards (published, recruiter-safe) for this skill.
    evidence_traces: list[VBREvidenceTrace] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class PublicPassportSkill(BaseModel):
    """Public top-skill row — qualitative label only, no counts.

    Drilldown detail is sourced ONLY from published public reports.
    """

    skill: str
    status: str
    evidence_sources: list[str] = Field(default_factory=list)
    projects: list[PublicPassportSkillProjectRef] = Field(default_factory=list)
    evidence_chips: list[PassportSkillEvidenceChip] = Field(default_factory=list)
    # Claim→evidence traces sourced ONLY from published public reports.
    evidence_traces: list[VBREvidenceTrace] = Field(default_factory=list)
    # Where this skill is most strongly evidenced — published projects only.
    strongest_project: PublicPassportStrongestProject | None = None
    limitations: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class PassportProjectReportStatus(BaseModel):
    """Owner-only publish status for one project's recruiter link."""

    is_public: bool = False
    public_token: str | None = None
    public_path: str | None = None
    published_at: str | None = None

    model_config = {"extra": "forbid"}


class PassportProofChain(BaseModel):
    """Proof-chain completeness for one project card.

    Derived purely from the already-safe evidence source badges — booleans and
    missing-source labels only, never a numeric completeness score.
    """

    github: bool = False
    website: bool = False
    document: bool = False
    project_defense: bool = False
    video: bool = False
    attached_count: int = 0
    total_count: int = 5
    missing: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class PassportProofChainGap(BaseModel):
    """One missing proof-chain source on a project card, as a qualitative gap
    with safe action copy. Owner-only (never on the public projection)."""

    source: str = ""
    gap_label: str = ""
    action: str = ""

    model_config = {"extra": "forbid"}


class PassportSuggestedAttachment(BaseModel):
    """A compact per-project attachment suggestion (owner-only).

    Derived deterministically from safe metadata; ``confidence_label`` is a
    closed qualitative label ("Likely match" / "Possible match" / "Needs
    review") — never a numeric score. Suggestions never attach anything —
    they only describe a safe next action for the student to review.
    """

    suggestion_id_safe: str = ""
    proof_type: str = ""
    proof_title: str = ""
    confidence_label: str = ""
    suggestion_reason: str = ""
    action_label: str = ""

    model_config = {"extra": "forbid"}


class ProofAttachmentSuggestion(BaseModel):
    """One owner-only Proof Attachment Intelligence suggestion.

    Connects an *unattached* proof group to the project it likely belongs to,
    with the deterministic evidence-basis chips that produced the match, an
    honest hedged reason, a closed qualitative confidence label, and an explicit
    limitation. Never carries a raw source id, raw evidence, or a numeric
    confidence — and never appears on the public projection.
    """

    suggestion_id_safe: str = ""
    proof_type: str = ""
    proof_title: str = ""
    # How many underlying vault rows grouped into this one suggestion.
    proof_count: int = 1
    likely_project_title: str = ""
    # Owner-only project-report route (private passport surface only).
    likely_project_ref_safe: str | None = None
    likely_skill_names: list[str] = Field(default_factory=list)
    suggestion_reason: str = ""
    evidence_basis_chips: list[str] = Field(default_factory=list)
    confidence_label: str = ""
    attachment_status: str = ""
    limitation: str = ""
    action_label: str = ""

    model_config = {"extra": "forbid"}


class UnattachedProofSummary(BaseModel):
    """Owner-only summary of unattached vault evidence + attachment suggestions.

    ``unmatched_count`` counts unattached proofs no suggestion could safely
    match — they stay visible in the vault, honestly labelled, never guessed."""

    unattached_count: int = 0
    suggestion_count: int = 0
    unmatched_count: int = 0
    suggestions: list[ProofAttachmentSuggestion] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class PassportProjectTopSkill(BaseModel):
    """One of the strongest skills a project's evidence demonstrates —
    qualitative label only.

    ``skill_slug`` is the skill's stable, URL-safe slug (derived from the
    canonical skill name — safe on both surfaces). ``skill_report_path`` is the
    owner-only Skill Report route and is stripped from the public projection.
    """

    skill: str
    status: str = "Not assessed"
    skill_slug: str | None = None
    skill_report_path: str | None = None

    model_config = {"extra": "forbid"}


class PublicPassportProjectTopSkill(BaseModel):
    """Public Project → Skill chip: skill + qualitative status + stable slug
    only. Never carries the owner-only ``skill_report_path`` route."""

    skill: str
    status: str = "Not assessed"
    skill_slug: str | None = None

    model_config = {"extra": "forbid"}


class PassportProjectSummary(BaseModel):
    """Owner-only project evidence card."""

    project_id: str
    project_title: str = ""
    project_summary: str = ""
    repo_full_name: str | None = None
    claimed_skills: list[str] = Field(default_factory=list)
    evidence_sources: list[str] = Field(default_factory=list)
    evidence_package: dict = Field(default_factory=dict)
    # Proof-chain completeness across the five attachable evidence sources.
    proof_chain: PassportProofChain = Field(default_factory=PassportProofChain)
    # Qualitative proof-chain label ("Strong chain", "Missing runtime proof", …)
    # plus the concrete gaps and per-project attachment suggestions. Owner-only,
    # deterministic, never numeric.
    chain_label: str = ""
    proof_chain_gaps: list[PassportProofChainGap] = Field(default_factory=list)
    suggested_attachments: list[PassportSuggestedAttachment] = Field(default_factory=list)
    next_best_action: str | None = None
    # The strongest evidence-backed skills this project demonstrates (capped).
    # Each entry links to its owner-only Skill Report route (Project → Skill).
    top_skills: list[PassportProjectTopSkill] = Field(default_factory=list)
    # One safe sentence relating this project's skills to its proof sources —
    # composed from qualitative labels only (never ids, scores, raw evidence).
    evidence_relationship_note: str | None = None
    # How many underlying evidence attempts (duplicate rows) merged into this
    # card. 1 when the project is a single row.
    attempt_count: int = 1
    report: PassportProjectReportStatus

    model_config = {"extra": "forbid"}


class PublicPassportProject(BaseModel):
    """Public featured project — links to its public VBR report, no internal ids."""

    project_title: str = ""
    project_summary: str = ""
    claimed_skills: list[str] = Field(default_factory=list)
    evidence_sources: list[str] = Field(default_factory=list)
    # Safe proof-chain completeness (booleans + source labels; no ids/scores).
    proof_chain: PassportProofChain = Field(default_factory=PassportProofChain)
    # Public Project → Skill chips: skill + qualitative status + stable slug
    # only. ``skill_report_path`` (an owner-only route) is never present here.
    top_skills: list[PublicPassportProjectTopSkill] = Field(default_factory=list)
    # Safe relationship sentence (qualitative labels only).
    evidence_relationship_note: str | None = None
    public_report_path: str
    published_at: str | None = None

    model_config = {"extra": "forbid"}


class EvidenceGraphOverview(BaseModel):
    """Compact top-of-passport summary of the evidence graph
    (projects ↔ skills ↔ proofs). Counts and next actions only — no scores."""

    project_count: int = 0
    published_report_count: int = 0
    skills_with_evidence: int = 0
    proof_count: int = 0
    attached_proof_count: int = 0
    unattached_proof_count: int = 0
    next_actions: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


# ── Passport identity header (recruiter-safe candidate identity) ─────────────


class PassportIdentity(BaseModel):
    """Recruiter-safe candidate identity header for the Verified Work Passport.

    Carries ONLY non-PII identity context — never the student's email, auth ID,
    private profile fields (visa / sponsorship / work-authorization), or a raw
    institution name beyond the safe ``region`` (country). Missing fields fall
    back to safe placeholders so the header always reads like a verified passport.
    """

    display_name: str | None = None
    headline: str = ""
    # Education context (safe onboarding fields only): degree program (major),
    # degree level, graduation year, and region (country) — never a raw school
    # name or any private field.
    program: str | None = None
    degree_level: str | None = None
    graduation_year: int | None = None
    region: str | None = None
    education_summary: str = ""
    # Public passport status + link (owner view); the public surface never carries
    # a private link here.
    public_status: str = ""
    public_path: str | None = None
    last_updated: str | None = None
    # Compact evidence-source summary badges, e.g. "GitHub Proof · 3".
    evidence_source_summary: list[str] = Field(default_factory=list)
    verification_label: str = "Verified Work Passport"

    model_config = {"extra": "forbid"}


# ── Private / public passport responses ──────────────────────────────────────


class PrivateWorkPassportResponse(BaseModel):
    candidate_display_name: str | None = None
    headline: str = ""
    summary: str = ""
    identity: PassportIdentity | None = None

    is_published: bool = False
    public_slug: str | None = None
    public_path: str | None = None
    published_at: str | None = None

    # Compact evidence-graph summary rendered at the top of the passport.
    evidence_graph_overview: EvidenceGraphOverview | None = None

    skills: list[PassportSkillSummary] = Field(default_factory=list)
    projects: list[PassportProjectSummary] = Field(default_factory=list)
    evidence_source_counts: dict[str, int] = Field(default_factory=dict)

    # Student Proof Vault — Layer 1: COMPACT per-skill summaries (the main
    # dashboard). Each card carries category, qualitative status, counts, and a
    # few representative previews — never every proof card. The full evidence for
    # one skill is loaded lazily via the Skill Report endpoint. Unattached proofs
    # are reflected in ``has_unattached`` / ``unattached_count`` per summary.
    vault_skill_summaries: list[VaultSkillSummary] = Field(default_factory=list)
    vault_proof_count: int = 0
    vault_unattached_count: int = 0

    # Proof Attachment Intelligence (owner-only): unattached evidence with
    # deterministic, qualitative attachment suggestions. Never on the public
    # projection.
    unattached_proof_summary: UnattachedProofSummary | None = None

    project_count: int = 0
    published_report_count: int = 0
    limitations: list[str] = Field(default_factory=list)
    generated_at: str = ""

    model_config = {"extra": "forbid"}


class PublicWorkPassportResponse(BaseModel):
    candidate_display_name: str | None = None
    headline: str = ""
    summary: str = ""
    identity: PassportIdentity | None = None

    top_skills: list[PublicPassportSkill] = Field(default_factory=list)
    featured_projects: list[PublicPassportProject] = Field(default_factory=list)
    evidence_source_counts: dict[str, int] = Field(default_factory=dict)
    featured_project_count: int = 0

    limitations: list[str] = Field(default_factory=list)
    published_at: str | None = None
    generated_at: str = ""
    verification_note: str = ""

    model_config = {"extra": "forbid"}


__all__ = [
    "PublishPassportRequest",
    "WorkPassportStatusResponse",
    "PassportSkillEvidenceChip",
    "PassportSkillProjectRef",
    "PassportStrongestProjectLink",
    "PassportSkillSummary",
    "PublicPassportStrongestProject",
    "PublicPassportSkillProjectRef",
    "PublicPassportSkill",
    "PassportProjectReportStatus",
    "PassportProofChain",
    "PassportProofChainGap",
    "PassportSuggestedAttachment",
    "ProofAttachmentSuggestion",
    "UnattachedProofSummary",
    "PassportProjectTopSkill",
    "PublicPassportProjectTopSkill",
    "EvidenceGraphOverview",
    "PassportProjectSummary",
    "PublicPassportProject",
    "PrivateWorkPassportResponse",
    "PublicWorkPassportResponse",
]
