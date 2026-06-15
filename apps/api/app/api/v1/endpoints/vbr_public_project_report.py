"""Public recruiter-safe VBR project report read endpoint (v1).

No authentication required. Resolves a published ``vbr_projects`` row by its
active ``public_report_token`` and serves the sanitized public projection of
the Final VBR Report. Revoked / unknown tokens return 404.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_db, get_pipeline_db
from app.schemas.vbr_public_project_report import PublicVBRProjectReportResponse
from app.services.vbr_public_project_report import build_public_project_report

router = APIRouter()


@router.get(
    "/vbr/reports/{public_token}",
    response_model=PublicVBRProjectReportResponse,
    summary="Get a published recruiter-safe VBR project report by its public token (no auth required)",
)
def get_public_vbr_project_report_route(
    public_token: str,
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> PublicVBRProjectReportResponse:
    result = build_public_project_report(db, pipeline_db, public_token)
    return PublicVBRProjectReportResponse(**result)
