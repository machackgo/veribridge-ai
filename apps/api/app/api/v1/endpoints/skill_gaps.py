"""Evidence-derived Skill Gaps endpoints (owner-scoped).

GET  /api/v1/student/skill-gaps                         — all my projects
GET  /api/v1/student/skill-gaps/projects/{project_id}   — one owned project

Tenant isolation matches the existing student surfaces: every read is scoped
by the authenticated user_id, and a project owned by another user returns 404
(never 403, never data) via ``get_owned_vbr_project_or_404``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user_id, get_db
from app.api.v1.endpoints.vbr_projects import get_owned_vbr_project_or_404
from app.schemas.skill_gaps import ProjectSkillGapReport, SkillGapsOverviewResponse
from app.services.skill_gap_service import (
    build_project_skill_gap_report,
    build_user_skill_gaps,
)

router = APIRouter()


@router.get(
    "",
    response_model=SkillGapsOverviewResponse,
    summary="Evidence-derived skill gaps across the current user's projects",
)
def list_skill_gaps(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> SkillGapsOverviewResponse:
    return SkillGapsOverviewResponse(**build_user_skill_gaps(db, user_id=user_id))


@router.get(
    "/projects/{project_id}",
    response_model=ProjectSkillGapReport,
    summary="Evidence-derived skill gaps for one owned project",
)
def get_project_skill_gaps(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ProjectSkillGapReport:
    project = get_owned_vbr_project_or_404(db, project_id, user_id)
    return ProjectSkillGapReport(
        **build_project_skill_gap_report(db, user_id=user_id, project=project)
    )
