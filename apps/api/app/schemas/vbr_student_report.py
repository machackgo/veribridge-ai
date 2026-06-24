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
    # Safe repository-relative file path, only for file-level GitHub traces.
    file_path: str | None = None
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
    "VBRReportSkillEvidenceRow",
    "VBRReportProjectDefenseAnalysis",
    "VBRStudentProjectReportResponse",
]
