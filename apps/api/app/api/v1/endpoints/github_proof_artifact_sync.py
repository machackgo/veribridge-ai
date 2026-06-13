"""GitHub Proof → Skill Evidence Artifact Sync endpoint.

POST /student/skill-pipelines/from-github-proof/{github_proof_id}

Converts an analyzed (or partially analyzed) standalone GitHub proof
submission into structured skill_evidence_artifacts linked to the student's
skill_evidence_pipelines.

Idempotent: safe to call multiple times for the same github_proof_id.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.services.github_proof_artifact_sync_service import (
    GitHubProofArtifactSyncService,
    GitHubProofNotFoundError,
    GitHubProofSyncStatusError,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/from-github-proof/{github_proof_id}",
    summary="Sync GitHub Proof analysis to Skill Graph",
    status_code=status.HTTP_200_OK,
)
def sync_github_proof_to_skill_graph(
    github_proof_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> dict[str, Any]:
    """Convert an analyzed GitHub proof into skill_evidence_artifacts.

    Loads the GitHub proof submission for the current user and creates
    structured artifacts in the student's Skill Graph. Idempotent — safe to
    call multiple times; returns already_synced=true if an artifact for this
    proof already exists.

    Returns a summary of what was created or a confirmation of idempotent skip.
    """
    svc = GitHubProofArtifactSyncService(db=db, pipeline_db=pipeline_db)
    try:
        result = svc.sync(user_id=user_id, github_proof_id=github_proof_id)
    except GitHubProofNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "github_proof_not_found",
                "message": "GitHub proof was not found for the current user.",
                "github_proof_id": github_proof_id,
            },
        ) from exc
    except GitHubProofSyncStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "github_proof_not_ready",
                "message": f"GitHub proof with status '{exc}' cannot be synced to the Skill Graph yet.",
            },
        ) from exc
    except Exception as exc:
        logger.exception(
            "sync_github_proof_to_skill_graph: unexpected error for user %s, proof %s",
            user_id,
            github_proof_id,
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
