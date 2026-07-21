"""Public recruiter-safe VBR project report read endpoint (v1).

No authentication required. Resolves a published ``vbr_projects`` row by its
active ``public_report_token`` and serves the sanitized public projection of
the Final VBR Report. Revoked / unknown tokens return 404.

Also hosts the companion fire-and-forget view tracker: a tiny POST that
records a privacy-conscious view event (coarse categories only) and never
fails loudly — analytics must never block or break report access.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_db, get_pipeline_db
from app.schemas.vbr_public_project_report import (
    PublicReportViewAck,
    PublicReportViewEvent,
    PublicVBRProjectReportResponse,
)
from app.services.vbr_public_project_report import (
    build_public_project_report,
    resolve_published_project_id,
)
from app.services.vbr_report_view_service import record_public_report_view

logger = logging.getLogger(__name__)

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


@router.post(
    "/vbr/reports/{public_token}/view",
    response_model=PublicReportViewAck,
    summary="Record a privacy-conscious view event for a published report (no auth required)",
)
def record_public_vbr_report_view_route(
    public_token: str,
    request: Request,
    event: PublicReportViewEvent | None = None,
    db: Any = Depends(get_db),
) -> PublicReportViewAck:
    """Best-effort view tracking; never an error surface.

    Any token that does not resolve to an actively published report — and any
    persistence failure — returns the same content-free ``recorded: false``
    ack, so this route can't be used as a token oracle beyond what the public
    GET already reveals, and a broken analytics table can never break the
    recruiter's page load.
    """
    try:
        project_id = resolve_published_project_id(db, public_token)
        if project_id is None:
            return PublicReportViewAck(recorded=False)
        recorded = record_public_report_view(
            db,
            project_id,
            source=event.source if event else None,
            dedupe_key=event.dedupe_key if event else None,
            referrer=request.headers.get("referer"),
            user_agent=request.headers.get("user-agent"),
        )
        return PublicReportViewAck(recorded=bool(recorded))
    except Exception:
        logger.warning("public report view tracking failed", exc_info=True)
        return PublicReportViewAck(recorded=False)
