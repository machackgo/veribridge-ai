"""Video Proof endpoints — first-class uploaded/recorded demo video proof.

Routes (mounted under ``/api/v1/proofs/video``):

  POST   ""                          — upload + retain + analyze (owner)
  GET    ""                          — list the owner's video proofs
  GET    /{proof_id}                 — detail (owner, or anyone when shared)
  GET    /{proof_id}/transcript      — timestamped narration segments (gated)
  GET    /{proof_id}/frames          — safe frame descriptors (gated)
  POST   /{proof_id}/visibility      — owner toggles recruiter sharing

Playback: the retained original streams through the gated artifact routes
(``/api/v1/proofs/artifacts/{original_artifact_id}/view``) — this module never
returns storage paths or signed URLs.

Gating: unknown / private-to-someone-else proofs answer the SAME indistinct
404 so existence can't be probed.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.api.deps import (
    get_current_user_id,
    get_db,
    get_optional_user_id,
    get_provisioned_user_id,
)
from app.core.config import settings
from app.services import video_proof_service as videos
from app.services.passport_disclosure import video_proof_public_access

logger = logging.getLogger(__name__)
router = APIRouter()

# Bounded streaming chunk size — same OOM-safe pattern as the workflow-video
# upload (workflow_visual_frames.py): never whole-body read before the size gate.
_UPLOAD_CHUNK_BYTES = 1024 * 1024

_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail={
        "code": "video_proof_not_available",
        "message": "This video proof does not exist or is not available to you.",
    },
)


class VideoProofResponse(BaseModel):
    """Safe projection of one video proof — never storage paths or signed URLs."""

    id: str
    title: str = ""
    description: str | None = None
    source_kind: str = "uploaded_demo"
    source_kind_label: str = "Demo video"
    status: str = "uploaded"
    project_id: str | None = None
    claimed_skills: list[str] = Field(default_factory=list)
    mime_type: str | None = None
    file_name: str | None = None
    size_bytes: int | None = None
    duration_seconds: float | None = None
    duration_label: str | None = None
    transcript_status: str = "pending"
    frames_status: str = "pending"
    analysis_status: str = "pending"
    analysis: dict[str, Any] | None = None
    needs_review: bool = True
    public_safe: bool = False
    original_artifact_id: str | None = None
    segment_count: int = 0
    frame_count: int = 0
    created_at: str | None = None


class VideoProofTranscriptSegment(BaseModel):
    seq: int = 0
    start_s: float = 0.0
    end_s: float = 0.0
    text: str = ""
    speaker: str | None = None


class VideoProofTranscriptResponse(BaseModel):
    video_proof_id: str
    transcript_status: str = "pending"
    segment_count: int = 0
    segments: list[VideoProofTranscriptSegment] = Field(default_factory=list)


class VideoProofFrameDescriptor(BaseModel):
    """One safe frame locator. Bytes stream via the gated artifact view route."""

    frame_id: str
    timestamp_s: float | None = None
    timestamp_label: str | None = None
    frame_artifact_id: str | None = None
    ocr_text: str | None = None
    activity_summary: str | None = None
    relevance_to_skill: str | None = None


class VideoProofFramesResponse(BaseModel):
    video_proof_id: str
    frames_status: str = "pending"
    frame_count: int = 0
    frames: list[VideoProofFrameDescriptor] = Field(default_factory=list)


class VideoProofVisibilityRequest(BaseModel):
    public_safe: bool


def _timestamp_label(seconds: float | None) -> str | None:
    if seconds is None or seconds < 0:
        return None
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


def _get_gated_proof(db: Any, proof_id: str, caller_user_id: str | None) -> dict[str, Any]:
    """Owner sees their proof; others only per the canonical disclosure gate.

    Non-owner access requires a PUBLIC passport, then: custom disclosure
    mode requires the project's ``video_full`` aspect to be Viewable, while
    recruiter-safe mode keeps the legacy ``public_safe`` sharing flag
    (``passport_disclosure.video_proof_public_access``). Denial is the same
    indistinct 404 as an unknown id.
    """
    proof = videos.get_video_proof(db, proof_id)
    if proof is None:
        raise _NOT_FOUND
    is_owner = caller_user_id is not None and caller_user_id == proof.get("user_id")
    if not is_owner and not video_proof_public_access(db, proof):
        raise _NOT_FOUND
    return proof


@router.post(
    "",
    response_model=VideoProofResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a project demonstration video as a first-class Video Proof",
)
async def upload_video_proof(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    description: str | None = Form(default=None),
    source_kind: str = Form(default="uploaded_demo"),
    claimed_skills: str | None = Form(default=None),
    project_id: str | None = Form(default=None),
    # First-write flow: a fresh user's video proof FKs public.users — provision.
    user_id: str = Depends(get_provisioned_user_id),
    db: Any = Depends(get_db),
) -> VideoProofResponse:
    filename = file.filename or "demo-video"
    limit_bytes = settings.max_video_size_bytes
    # Format/MIME rejects fire BEFORE the body is touched; the size limit is
    # then enforced while streaming in bounded chunks — a bare
    # ``await file.read()`` would materialize an oversized body in memory
    # before the check (the workflow-video OOM failure mode).
    videos.validate_upload(filename, file.content_type, 0, limit_bytes)
    buffer = bytearray()
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > limit_bytes:
            # Raises the endpoint's canonical 413 (code: video_too_large).
            videos.validate_upload(filename, file.content_type, len(buffer), limit_bytes)
    data = bytes(buffer)

    proof = videos.create_video_proof(
        db,
        user_id=user_id,
        data=data,
        filename=filename,
        mime_type=file.content_type or "video/mp4",
        title=title,
        description=description,
        source_kind=source_kind,
        claimed_skills=(claimed_skills or "").split(",") if claimed_skills else [],
        project_id=(project_id or "").strip() or None,
    )
    return VideoProofResponse(**videos.safe_video_proof_dto(db, proof, include_private_detail=True))


@router.get(
    "",
    response_model=list[VideoProofResponse],
    summary="List the current student's video proofs",
)
def list_video_proofs(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> list[VideoProofResponse]:
    return [
        VideoProofResponse(**videos.safe_video_proof_dto(db, proof, include_private_detail=True))
        for proof in videos.list_video_proofs_for_user(db, user_id)
    ]


@router.get(
    "/{proof_id}",
    response_model=VideoProofResponse,
    summary="Video proof detail (owner, or anyone once shared)",
)
def get_video_proof_detail(
    proof_id: str,
    user_id: str | None = Depends(get_optional_user_id),
    db: Any = Depends(get_db),
) -> VideoProofResponse:
    proof = _get_gated_proof(db, proof_id, user_id)
    is_owner = user_id is not None and user_id == proof.get("user_id")
    return VideoProofResponse(**videos.safe_video_proof_dto(db, proof, include_private_detail=is_owner))


@router.get(
    "/{proof_id}/transcript",
    response_model=VideoProofTranscriptResponse,
    summary="Timestamped narration transcript for a video proof (gated)",
)
def get_video_proof_transcript(
    proof_id: str,
    user_id: str | None = Depends(get_optional_user_id),
    db: Any = Depends(get_db),
) -> VideoProofTranscriptResponse:
    proof = _get_gated_proof(db, proof_id, user_id)
    segments = videos.list_transcript_segments(db, proof_id)
    return VideoProofTranscriptResponse(
        video_proof_id=proof_id,
        transcript_status=str(proof.get("transcript_status") or "pending"),
        segment_count=len(segments),
        segments=[
            VideoProofTranscriptSegment(
                seq=int(s.get("seq") or 0),
                start_s=float(s.get("start_s") or 0.0),
                end_s=float(s.get("end_s") or 0.0),
                text=str(s.get("text") or ""),
                speaker=s.get("speaker"),
            )
            for s in segments
        ],
    )


@router.get(
    "/{proof_id}/frames",
    response_model=VideoProofFramesResponse,
    summary="Safe extracted-frame descriptors for a video proof (gated)",
)
def get_video_proof_frames(
    proof_id: str,
    user_id: str | None = Depends(get_optional_user_id),
    db: Any = Depends(get_db),
) -> VideoProofFramesResponse:
    proof = _get_gated_proof(db, proof_id, user_id)
    frames = videos.list_frames(db, proof_id)
    return VideoProofFramesResponse(
        video_proof_id=proof_id,
        frames_status=str(proof.get("frames_status") or "pending"),
        frame_count=len(frames),
        frames=[
            VideoProofFrameDescriptor(
                frame_id=str(f.get("id")),
                timestamp_s=f.get("timestamp_s"),
                timestamp_label=_timestamp_label(f.get("timestamp_s")),
                frame_artifact_id=f.get("frame_artifact_id"),
                ocr_text=f.get("ocr_text"),
                activity_summary=f.get("activity_summary"),
                relevance_to_skill=f.get("relevance_to_skill"),
            )
            for f in frames
        ],
    )


@router.post(
    "/{proof_id}/visibility",
    response_model=VideoProofResponse,
    summary="Owner toggles recruiter sharing for a video proof",
)
def set_video_proof_visibility(
    proof_id: str,
    body: VideoProofVisibilityRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VideoProofResponse:
    proof = videos.set_video_proof_visibility(
        db, user_id=user_id, video_proof_id=proof_id, public_safe=body.public_safe
    )
    return VideoProofResponse(**videos.safe_video_proof_dto(db, proof, include_private_detail=True))
