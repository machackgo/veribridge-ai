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
    notes: str = ""
    limitations: list[str] = Field(default_factory=list)

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


class PassportProjectTopSkill(BaseModel):
    """One of the strongest skills a project's evidence demonstrates —
    qualitative label only."""

    skill: str
    status: str = "Not assessed"

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
    # The strongest evidence-backed skills this project demonstrates (capped).
    top_skills: list[PassportProjectTopSkill] = Field(default_factory=list)
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
    "PassportSkillSummary",
    "PublicPassportSkillProjectRef",
    "PublicPassportSkill",
    "PassportProjectReportStatus",
    "PassportProofChain",
    "PassportProjectTopSkill",
    "EvidenceGraphOverview",
    "PassportProjectSummary",
    "PublicPassportProject",
    "PrivateWorkPassportResponse",
    "PublicWorkPassportResponse",
]
