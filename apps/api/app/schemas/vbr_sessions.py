"""Schemas for VBR session recording/upload endpoints (T4A skeleton)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.vbr_questions import VBRSessionQuestionResponse


class VideoEvidenceChipResponse(BaseModel):
    """A safe, timestamped reference into a Project Defense video transcript.

    Never includes storage paths, signed URLs, access tokens, or full
    transcript text — ``short_summary`` is a short snippet of a single
    transcript segment.
    """

    label: str
    timestamp_start_s: float
    timestamp_end_s: float
    short_summary: str
    related_skill: str | None = None
    question_id: str | None = None
    source: str = "project_defense_video"
    source_type: str = "video_transcript"


class VBRSessionResponse(BaseModel):
    id: str
    project_id: str
    attempt_no: int
    status: str
    started_at: str | None = None
    ended_at: str | None = None
    duration_s: int | None = None
    webcam_present: bool
    chunk_count: int
    created_at: str
    updated_at: str
    transcript_status: str | None = None
    video_evidence_chips: list[VideoEvidenceChipResponse] = Field(default_factory=list)


class VBRSessionDetailResponse(VBRSessionResponse):
    questions: list[VBRSessionQuestionResponse] = Field(default_factory=list)


class VBRRecordingReadinessResponse(BaseModel):
    """Safe readiness summary for browser recording — no internal details.

    Never includes bucket names, storage paths, signed URLs, or env values.
    """

    ready: bool
    code: str | None = None
    message: str


class VBRConsentRequest(BaseModel):
    text_version: str | None = Field(default=None, min_length=1, max_length=100)


class VBRConsentResponse(BaseModel):
    id: str
    user_id: str
    kind: str
    granted: bool
    text_version: str
    created_at: str


class VBRChunkUploadRequest(BaseModel):
    chunk_index: int = Field(..., ge=0)
    storage_path: str = Field(..., min_length=1, max_length=500)
    bytes: int = Field(..., gt=0)
    sha256: str = Field(..., min_length=1, max_length=128)


class VBRChunkResponse(BaseModel):
    id: str
    session_id: str
    chunk_index: int
    bytes: int | None = None
    sha256: str | None = None
    received_at: str


class VBRChunkUploadUrlRequest(BaseModel):
    chunk_index: int = Field(..., ge=0)
    bytes: int = Field(..., gt=0)
    sha256: str = Field(..., min_length=1, max_length=128)


class VBRChunkUploadUrlResponse(BaseModel):
    upload_url: str
    storage_path: str
    chunk_index: int
    expires_in: int | None


class VBRTelemetryRequest(BaseModel):
    telemetry: dict[str, Any] = Field(default_factory=dict)
    merge: bool = Field(default=True)


class VBRTelemetryResponse(BaseModel):
    session_id: str
    telemetry: dict[str, Any] = Field(default_factory=dict)


class VBRFinalizeRequest(BaseModel):
    duration_s: int | None = Field(default=None, ge=0)


class VBRMediaProcessingResponse(BaseModel):
    session_id: str
    status: str
    chunk_count: int
    total_bytes: int
    full_video_bytes: int
    full_video_sha256: str
    next_steps: list[str] = Field(default_factory=list)
    message: str


class VBRTranscriptionResponse(BaseModel):
    session_id: str
    status: str
    transcript_id: str | None = None
    segment_count: int = 0
    duration_s: float | None = None
    provider: str | None = None
    configured: bool = True
    message: str


class VBRTranscriptSegmentResponse(BaseModel):
    start_s: float
    end_s: float
    text: str


class VBRSessionTranscriptResponse(BaseModel):
    """Owner-only private transcript preview for a recorded session.

    Served to the student who owns the session so the recorder/workspace page
    can render their generated transcript. Never used by the public recruiter
    report path (which sanitizes independently).
    """

    session_id: str
    status: str
    transcript_id: str | None = None
    provider: str | None = None
    language: str | None = None
    segment_count: int = 0
    duration_s: float | None = None
    preview_text: str = ""
    truncated: bool = False
    segments: list[VBRTranscriptSegmentResponse] = Field(default_factory=list)


class VBRKeyframeExtractionResponse(BaseModel):
    session_id: str
    frame_count: int
    status: str
    message: str


class VBREvidenceBuildResponse(BaseModel):
    session_id: str
    evidence_count: int
    source_counts: dict[str, int] = Field(default_factory=dict)
    status: str
    message: str


class VBRJudgmentResponse(BaseModel):
    session_id: str
    judged_claim_count: int
    judged_question_count: int
    status: str
    message: str


class VBRReportDraftResponse(BaseModel):
    session_id: str
    report_id: str
    status: str
    claim_count: int
    evidence_count: int
    message: str


class VBRReportReviewResponse(BaseModel):
    session_id: str
    report_id: str
    status: str
    message: str


class VBRReportPublishResponse(BaseModel):
    session_id: str
    report_id: str
    status: str
    public_token_created: bool
    message: str


class VBRReportUnpublishResponse(BaseModel):
    session_id: str
    report_id: str
    status: str
    message: str


class VBRReportStatusResponse(BaseModel):
    session_id: str
    report_id: str
    status: str
    has_public_token: bool
    claim_count: int
    updated_at: str
    published_at: str | None = None
