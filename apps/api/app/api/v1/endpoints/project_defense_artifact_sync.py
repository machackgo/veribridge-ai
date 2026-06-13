"""Project Defense → Skill Evidence Artifact Sync endpoint (Phase 1).

POST /student/skill-pipelines/from-project-defense/{session_id}

Converts a deterministically-analyzed individual Project Defense session
into structured skill_evidence_artifacts linked to the student's
skill_evidence_pipelines.

Idempotent: safe to call multiple times for the same session_id.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.services.project_defense_artifact_sync_service import (
    ProjectDefenseArtifactSyncService,
    ProjectDefenseNotAnalyzedError,
    ProjectDefenseNotFoundError,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/from-project-defense/{session_id}",
    summary="Sync Project Defense evidence to Skill Graph",
    status_code=status.HTTP_200_OK,
)
def sync_project_defense_to_skill_graph(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> dict[str, Any]:
    """Convert an analyzed Project Defense session into skill_evidence_artifacts.

    Loads the verification session and its project for the current user and
    creates protected, conservative skill_evidence_artifacts (source_type
    "transcript", artifact_data.kind "project_defense") in the student's
    Skill Graph. Idempotent — safe to call multiple times; returns
    already_synced=true if an artifact for this session already exists.
    """
    svc = ProjectDefenseArtifactSyncService(db=db, pipeline_db=pipeline_db)
    try:
        result = svc.sync(user_id=user_id, session_id=session_id)
    except ProjectDefenseNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "project_defense_session_not_found",
                "message": "Project defense session was not found for the current user.",
                "session_id": session_id,
            },
        ) from exc
    except ProjectDefenseNotAnalyzedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "project_defense_not_analyzed",
                "message": "Submit and analyze your project defense answers before saving to the Skill Graph.",
            },
        ) from exc
    except Exception as exc:
        logger.exception(
            "sync_project_defense_to_skill_graph: unexpected error for user %s, session %s",
            user_id,
            session_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "sync_failed", "message": str(exc)},
        ) from exc

    return {
        "ok": True,
        "already_synced": result.already_synced,
        "skills_synced": result.skills_synced,
        "pipelines_upserted": result.pipelines_upserted,
        "artifacts_created": result.artifacts_created,
        "errors": result.errors,
    }
