"""Skill Evidence Pipeline endpoints.

Student endpoints:
  GET  /student/skill-pipelines
    List all skill pipelines for the current student.

  GET  /student/skill-pipelines/{pipeline_id}
    Get a single pipeline with its artifacts.

  POST /student/skill-pipelines/upsert
    Create or update a skill pipeline (upsert by skill_name).

  POST /student/skill-pipelines/{pipeline_id}/artifacts
    Add an evidence artifact to a pipeline.

  POST /student/skill-pipelines/seed-mock
    Seed MVP deterministic pipelines for the current student (WPI demo).

Recruiter endpoint:
  GET  /student/skill-pipelines/{pipeline_id}/recruiter-view
    Return a sanitized, recruiter-safe pipeline payload.
    Private/locked artifacts are excluded.
    No student_id, student_summary, or unsafe storage paths are returned.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_pipeline_db
from app.schemas.skill_evidence_pipeline import (
    RecruiterPipelineSummary,
    SkillEvidenceArtifactCreate,
    SkillEvidenceArtifactResponse,
    SkillEvidencePipelineCreate,
    SkillEvidencePipelineResponse,
    UpdateArtifactVisibilityRequest,
    UpdatePipelineVisibilityRequest,
)
from app.services.skill_evidence_pipeline_service import (
    ArtifactNotFoundError,
    PipelineNotFoundError,
    SkillEvidencePipelineService,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── GET /student/skill-pipelines ──────────────────────────────────────────────


@router.get(
    "",
    response_model=list[SkillEvidencePipelineResponse],
    summary="List all skill evidence pipelines for the current student",
)
def list_pipelines(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_pipeline_db),
) -> list[SkillEvidencePipelineResponse]:
    """Return skill evidence pipelines for the authenticated student,
    ordered by confidence_score descending."""
    try:
        return SkillEvidencePipelineService(db).list_pipelines_for_student(user_id)
    except Exception as exc:
        logger.exception("GET skill-pipelines: unexpected error for user %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "list_failed", "message": str(exc)},
        ) from exc


# ── POST /student/skill-pipelines/seed-mock ───────────────────────────────────


@router.post(
    "/seed-mock",
    response_model=list[SkillEvidencePipelineResponse],
    status_code=status.HTTP_200_OK,
    summary="Seed deterministic MVP pipelines for the current student (WPI demo)",
)
def seed_mock_pipelines(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_pipeline_db),
) -> list[SkillEvidencePipelineResponse]:
    """Create or refresh the standard set of MVP skill pipelines for this student.

    Idempotent: re-running updates existing pipelines without duplicating.
    Designed for WPI career fair testing.
    """
    try:
        return SkillEvidencePipelineService(db).build_mock_pipelines_for_student(user_id)
    except Exception as exc:
        logger.exception("POST skill-pipelines/seed-mock: unexpected error for user %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "seed_failed", "message": str(exc)},
        ) from exc


# ── POST /student/skill-pipelines/upsert ──────────────────────────────────────


@router.post(
    "/upsert",
    response_model=SkillEvidencePipelineResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or update a skill evidence pipeline",
)
def upsert_pipeline(
    body: SkillEvidencePipelineCreate,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_pipeline_db),
) -> SkillEvidencePipelineResponse:
    """Upsert a skill pipeline for the authenticated student.

    Uses (student_id, skill_name) as the unique key.
    If a pipeline for this skill already exists, its fields are updated.
    """
    try:
        return SkillEvidencePipelineService(db).upsert_pipeline(user_id, body)
    except Exception as exc:
        logger.exception("POST skill-pipelines/upsert: unexpected error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "internal_error", "message": str(exc)},
        ) from exc


# ── GET /student/skill-pipelines/{pipeline_id} ───────────────────────────────


@router.get(
    "/{pipeline_id}",
    response_model=SkillEvidencePipelineResponse,
    summary="Get a single skill evidence pipeline",
)
def get_pipeline(
    pipeline_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_pipeline_db),
) -> SkillEvidencePipelineResponse:
    try:
        return SkillEvidencePipelineService(db).get_pipeline(pipeline_id, user_id)
    except PipelineNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "pipeline_not_found", "message": str(exc)},
        ) from exc


# ── POST /student/skill-pipelines/{pipeline_id}/artifacts ────────────────────


@router.post(
    "/{pipeline_id}/artifacts",
    response_model=SkillEvidenceArtifactResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add an evidence artifact to a skill pipeline",
)
def add_artifact(
    pipeline_id: str,
    body: SkillEvidenceArtifactCreate,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_pipeline_db),
) -> SkillEvidenceArtifactResponse:
    """Add a new evidence artifact (GitHub, transcript, document, workflow, etc.)
    to the specified pipeline.

    The pipeline must belong to the authenticated student.
    """
    if body.pipeline_id != pipeline_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "pipeline_id_mismatch",
                "message": "pipeline_id in body must match the URL parameter.",
            },
        )
    try:
        return SkillEvidencePipelineService(db).add_artifact(user_id, body)
    except PipelineNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "pipeline_not_found", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("POST /%s/artifacts: unexpected error", pipeline_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "internal_error", "message": str(exc)},
        ) from exc


# ── PATCH /student/skill-pipelines/artifacts/{artifact_id}/visibility ────────
# Must be defined before /{pipeline_id}/visibility to avoid routing ambiguity.


@router.patch(
    "/artifacts/{artifact_id}/visibility",
    response_model=SkillEvidenceArtifactResponse,
    summary="Update an artifact's visibility",
)
def update_artifact_visibility(
    artifact_id: str,
    body: UpdateArtifactVisibilityRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_pipeline_db),
) -> SkillEvidenceArtifactResponse:
    """Set visibility for a single evidence artifact.

    Ownership is verified by checking that the artifact's parent pipeline
    belongs to the authenticated student.
    """
    svc = SkillEvidencePipelineService(db)
    try:
        return svc.update_artifact_visibility(artifact_id, user_id, body.visibility)
    except ArtifactNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "artifact_not_found", "message": str(exc)},
        ) from exc
    except PipelineNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "pipeline_not_found", "message": str(exc)},
        ) from exc


# ── PATCH /student/skill-pipelines/{pipeline_id}/visibility ──────────────────


@router.patch(
    "/{pipeline_id}/visibility",
    response_model=SkillEvidencePipelineResponse,
    summary="Update a skill pipeline's visibility",
)
def update_pipeline_visibility(
    pipeline_id: str,
    body: UpdatePipelineVisibilityRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_pipeline_db),
) -> SkillEvidencePipelineResponse:
    """Set visibility_status (public / protected / private) for a pipeline.

    Allowed values:
      public    — recruiter can see skill summary and safe public evidence.
      protected — recruiter sees a locked card; must request access for details.
      private   — pipeline is hidden from all recruiter-facing views.
    """
    svc = SkillEvidencePipelineService(db)
    try:
        return svc.update_pipeline_visibility(pipeline_id, user_id, body.visibility)
    except PipelineNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "pipeline_not_found", "message": str(exc)},
        ) from exc


# ── GET /student/skill-pipelines/{pipeline_id}/recruiter-view ────────────────


@router.get(
    "/{pipeline_id}/recruiter-view",
    response_model=RecruiterPipelineSummary,
    summary="Recruiter-safe view of a skill pipeline",
)
def recruiter_view(
    pipeline_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_pipeline_db),
) -> RecruiterPipelineSummary:
    """Return a sanitized pipeline payload suitable for recruiter sharing.

    Strips: student_id, profile_id, student_summary, private/locked artifacts,
    and any unsafe artifact_data keys (storage paths, signed URLs, tokens).
    """
    svc = SkillEvidencePipelineService(db)
    try:
        pipeline = svc.get_pipeline(pipeline_id, user_id)
    except PipelineNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "pipeline_not_found", "message": str(exc)},
        ) from exc

    artifacts = svc.list_artifacts_for_pipeline(pipeline_id, user_id)
    return svc.sanitize_recruiter_payload(pipeline, artifacts)
