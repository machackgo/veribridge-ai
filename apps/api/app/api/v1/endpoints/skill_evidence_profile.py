"""Skill Evidence Profile endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user_id, get_db
from app.schemas.skill_evidence_profile import SkillEvidenceProfile
from app.services.skill_evidence_profile_service import SkillEvidenceProfileService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "",
    response_model=list[SkillEvidenceProfile],
    summary="List skill evidence profiles grouped by project for the current user",
)
def list_skill_evidence_profiles(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> list[SkillEvidenceProfile]:
    try:
        return SkillEvidenceProfileService(db).compute_skill_evidence_profiles(user_id)
    except Exception:
        logger.exception("GET /student/skill-evidence-profiles: unexpected error")
        return []
