"""Public VBR report read endpoint (T7B).

No authentication required. Serves the sanitized public projection of a
published ``vbr_reports`` row by its ``public_token``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_db
from app.schemas.vbr_public_report import VBRPublicReportResponse
from app.services.vbr_public_report import get_public_report

router = APIRouter()


@router.get(
    "/vbr/legacy-reports/{public_token}",
    response_model=VBRPublicReportResponse,
    summary="Get a published Verified Build Report by its public token (no auth required)",
)
def get_public_vbr_report_route(
    public_token: str,
    db: Any = Depends(get_db),
) -> VBRPublicReportResponse:
    result = get_public_report(db, public_token)
    return VBRPublicReportResponse(**result)
