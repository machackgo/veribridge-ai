"""Pydantic schemas for Skill Evidence Pipelines.

Security note:
  Recruiter-facing payloads must never include raw storage paths,
  signed URLs, private media URLs, access_token, service-role keys,
  or any field prefixed with 'storage_' or '_private'.
"""

from __future__ import annotations

from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Enums-as-literals ─────────────────────────────────────────────────────────

SupportStatus = Literal["strongly_supported", "partially_supported", "needs_review"]
VisibilityStatus = Literal["public", "protected", "private"]
ArtifactVisibility = Literal["public", "protected", "private", "approved", "locked", "unavailable"]
SourceType = Literal[
    "github", "workflow", "keyframe", "ocr", "dom",
    "qwen", "transcript", "document", "review", "certificate", "coursework"
]

# ── Nested shapes stored in jsonb columns ─────────────────────────────────────

class ProofLabel(BaseModel):
    label: str
    reason: str = ""


class EvidenceSourceCoverage(BaseModel):
    key: str
    label: str
    status: Literal["supported", "partial", "missing", "protected"]
    score: Optional[int] = None
    reason: str = ""


class GitHubArtifactData(BaseModel):
    """Recruiter-safe GitHub line-level artifact.

    Security: repo_url must be a public GitHub URL (/blob/main/…).
    Never store signed storage URLs here.
    """
    repo_url: str = ""
    branch: str = "main"
    file_path: str = ""
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    symbol_name: Optional[str] = None
    code_reason: str = ""

    @property
    def exact_code_url(self) -> str:
        if not self.repo_url or not self.file_path:
            return ""
        base = f"{self.repo_url}/blob/{self.branch}/{self.file_path}"
        if self.start_line is not None and self.end_line is not None:
            return f"{base}#L{self.start_line}-L{self.end_line}"
        return base

    @property
    def full_file_url(self) -> str:
        if not self.repo_url or not self.file_path:
            return ""
        return f"{self.repo_url}/blob/{self.branch}/{self.file_path}"


class TranscriptArtifactData(BaseModel):
    excerpt: str = ""
    highlighted_segments: list[str] = Field(default_factory=list)
    full_transcript_available: bool = False
    ownership_signals: list[str] = Field(default_factory=list)
    technical_depth_signals: list[str] = Field(default_factory=list)


class DocumentArtifactData(BaseModel):
    document_title: str = ""
    document_type: str = ""
    extracted_sections: list[str] = Field(default_factory=list)
    download_available: bool = False
    open_available: bool = False


class WorkflowArtifactData(BaseModel):
    """Recruiter-safe workflow/visual/OCR/DOM/Qwen artifact.

    Security: keyframe_available is a boolean flag only.
    Raw keyframe storage paths and signed URLs must not be stored here.
    """
    timestamp: str = ""
    frame_label: str = ""
    ocr_snippet: str = ""
    dom_summary: str = ""
    qwen_observation: str = ""
    keyframe_available: bool = False


# ── Pipeline schemas ──────────────────────────────────────────────────────────

class SkillEvidencePipelineCreate(BaseModel):
    skill_name: str
    skill_category: str = "technical"
    confidence_score: int = Field(default=0, ge=0, le=100)
    support_status: SupportStatus = "needs_review"
    evidence_count: int = Field(default=0, ge=0)
    strongest_proof: dict[str, Any] = Field(default_factory=dict)
    weakest_proof: dict[str, Any] = Field(default_factory=dict)
    missing_evidence: list[Any] = Field(default_factory=list)
    next_actions: list[Any] = Field(default_factory=list)
    evidence_sources: list[Any] = Field(default_factory=list)
    recruiter_summary: str = ""
    student_summary: str = ""
    visibility_status: VisibilityStatus = "public"


class StudentArtifactSummary(BaseModel):
    """Safe, student-facing artifact summary.

    Excludes artifact_data entirely — no raw document text, storage paths,
    signed URLs, or tokens. Only the fields needed to group and label a
    student's own evidence artifacts in the Manage Skill Evidence UI.
    """
    id: str
    source_type: str
    source_title: str
    project_name: str
    visibility: str
    confidence_score: int
    proof_reason: str
    exact_code_url: Optional[str] = None
    full_file_url: Optional[str] = None


class SkillEvidencePipelineResponse(BaseModel):
    id: str
    student_id: Optional[str] = None
    profile_id: Optional[str] = None
    skill_name: str
    skill_category: str
    confidence_score: int
    support_status: str
    evidence_count: int
    strongest_proof: dict[str, Any]
    weakest_proof: dict[str, Any]
    missing_evidence: list[Any]
    next_actions: list[Any]
    evidence_sources: list[Any]
    recruiter_summary: str
    student_summary: str
    visibility_status: str
    created_at: str
    updated_at: str
    artifacts: list[StudentArtifactSummary] = Field(default_factory=list)


# ── Artifact schemas ──────────────────────────────────────────────────────────

class SkillEvidenceArtifactCreate(BaseModel):
    pipeline_id: str
    proof_session_id: Optional[str] = None
    source_type: SourceType
    source_title: str
    project_name: str = ""
    visibility: ArtifactVisibility = "public"
    confidence_score: int = Field(default=0, ge=0, le=100)
    relevance_to_skill: str = ""
    proof_reason: str = ""
    artifact_data: dict[str, Any] = Field(default_factory=dict)


class SkillEvidenceArtifactResponse(BaseModel):
    id: str
    pipeline_id: str
    proof_session_id: Optional[str] = None
    source_type: str
    source_title: str
    project_name: str
    visibility: str
    confidence_score: int
    relevance_to_skill: str
    proof_reason: str
    artifact_data: dict[str, Any]
    created_at: str
    updated_at: str

    # Computed safe URLs for GitHub artifacts (never signed URLs)
    exact_code_url: Optional[str] = None
    full_file_url: Optional[str] = None


# ── Visibility update request schemas ────────────────────────────────────────

class UpdatePipelineVisibilityRequest(BaseModel):
    visibility: VisibilityStatus


class UpdateArtifactVisibilityRequest(BaseModel):
    visibility: ArtifactVisibility


# ── Recruiter-safe pipeline response ─────────────────────────────────────────

class RecruiterPipelineSummary(BaseModel):
    """Sanitized pipeline view for recruiters.

    Fields excluded: student_id, profile_id, student_summary,
    private artifact_data, any internal storage references.

    is_locked_for_recruiter is True when visibility_status == "protected"
    and the recruiter has not yet received student approval.  In this state
    recruiter_summary is replaced with a generic locked message and
    artifact_data is stripped to empty for all artifacts.
    """
    id: str
    skill_name: str
    skill_category: str
    confidence_score: int
    support_status: str
    evidence_count: int
    strongest_proof: dict[str, Any]
    weakest_proof: dict[str, Any]
    missing_evidence: list[Any]
    next_actions: list[Any] = Field(default_factory=list)
    evidence_sources: list[Any] = Field(default_factory=list)
    recruiter_summary: str
    visibility_status: str
    is_locked_for_recruiter: bool = False
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
