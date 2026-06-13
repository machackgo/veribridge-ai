"""Document Proof → Skill Evidence Artifact Sync endpoint.

POST /student/skill-pipelines/from-document-proof/{document_evidence_id}

Converts an analyzed standalone document/certificate submission
(optional_evidence_submissions, proof_session_id IS NULL) into structured
skill_evidence_artifacts linked to the student's skill_evidence_pipelines.

Idempotent: safe to call multiple times for the same document_evidence_id.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.services.document_proof_artifact_sync_service import (
    DocumentProofArtifactSyncService,
    DocumentProofNotFoundError,
    DocumentProofSyncStatusError,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/from-document-proof/{document_evidence_id}",
    summary="Sync Document Proof analysis to Skill Graph",
    status_code=status.HTTP_200_OK,
)
def sync_document_proof_to_skill_graph(
    document_evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> dict[str, Any]:
    """Convert an analyzed document proof into skill_evidence_artifacts.

    Loads the standalone document evidence submission for the current user
    and creates structured artifacts in the student's Skill Graph. Idempotent
    — safe to call multiple times; returns already_synced=true if an artifact
    for this document already exists.

    Returns a summary of what was created or a confirmation of idempotent skip.
    """
    svc = DocumentProofArtifactSyncService(db=db, pipeline_db=pipeline_db)
    try:
        result = svc.sync(user_id=user_id, document_evidence_id=document_evidence_id)
    except DocumentProofNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "document_proof_not_found",
                "message": "Document proof was not found for the current user.",
                "document_evidence_id": document_evidence_id,
            },
        ) from exc
    except DocumentProofSyncStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "document_proof_not_ready",
                "message": f"Document proof with status '{exc}' cannot be synced to the Skill Graph yet.",
            },
        ) from exc
    except Exception as exc:
        logger.exception(
            "sync_document_proof_to_skill_graph: unexpected error for user %s, evidence %s",
            user_id,
            document_evidence_id,
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
