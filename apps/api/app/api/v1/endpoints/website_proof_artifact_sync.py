"""Website Proof → Skill Evidence Artifact Sync endpoint.

POST /student/skill-pipelines/from-website-proof/{proof_session_id}

Converts completed Website Proof analysis outputs into structured
skill_evidence_artifacts linked to the student's skill_evidence_pipelines.

Idempotent: safe to call multiple times for the same proof session.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.services.website_proof_artifact_sync_service import WebsiteProofArtifactSyncService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/from-website-proof/{proof_session_id}",
    summary="Sync Website Proof analysis to Skill Graph",
    status_code=status.HTTP_200_OK,
)
def sync_proof_to_skill_graph(
    proof_session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> dict[str, Any]:
    """Convert completed Website Proof analysis into skill_evidence_artifacts.

    Loads all persisted analysis for the proof session and creates structured
    artifacts in the student's Skill Graph.  Idempotent — safe to call
    multiple times; returns already_synced=true if artifacts already exist.

    Returns a summary of what was created or a confirmation of idempotent skip.
    """
    try:
        svc = WebsiteProofArtifactSyncService(db=db, pipeline_db=pipeline_db)
        result = svc.sync(user_id=user_id, proof_session_id=proof_session_id)
        return {
            "ok": True,
            "already_synced": result.already_synced,
            "skills_synced": result.skills_synced,
            "pipelines_upserted": result.pipelines_upserted,
            "artifacts_created": result.artifacts_created,
            "artifact_types_created": result.artifact_types_created,
            "errors": result.errors,
        }
    except Exception as exc:
        logger.exception(
            "sync_proof_to_skill_graph: unexpected error for user %s, session %s",
            user_id,
            proof_session_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "sync_failed", "message": str(exc)},
        ) from exc
