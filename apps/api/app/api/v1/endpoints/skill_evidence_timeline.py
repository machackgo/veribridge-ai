"""Student Skill Evidence Timeline endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.schemas.skill_evidence_timeline import SkillEvidenceTimelineResponse
from app.services.extension_proof_service import ExtensionProofSessionNotFoundError
from app.services.skill_evidence_timeline_service import SkillEvidenceTimelineService

router = APIRouter()


@router.get(
    "/{session_id}/skill-evidence-timeline",
    response_model=SkillEvidenceTimelineResponse,
    summary="Get skill-level evidence timeline for a proof session",
)
def get_skill_evidence_timeline(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> SkillEvidenceTimelineResponse:
    try:
        return SkillEvidenceTimelineService(db).get_skill_evidence_timeline(user_id, session_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "extension_proof_session_not_found",
                "message": "Extension proof session not found for the current user.",
                "session_id": session_id,
            },
        ) from exc
