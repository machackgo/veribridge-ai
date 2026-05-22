"""Website AI Analyzer API endpoint (Phase J4D).

POST /api/v1/student/website-analysis/analyze
  Fetches a public URL, checks common routes, parses OpenAPI specs,
  and returns evidence candidates for the review screen.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id
from app.schemas.website_analyzer import WebsiteAnalyzeRequest, WebsiteAnalyzeResponse
from app.services.website_analyzer_service import WebsiteAnalyzerService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/analyze",
    response_model=WebsiteAnalyzeResponse,
    summary="Analyze a public website URL and extract skill evidence candidates",
)
def analyze_website(
    body: WebsiteAnalyzeRequest,
    user_id: str = Depends(get_current_user_id),
) -> WebsiteAnalyzeResponse:
    """
    Fetch a public URL and inspect common routes (/docs, /openapi.json, /health)
    to extract evidence candidates.  Only public http/https URLs; private IPs
    and localhost are blocked.
    """
    logger.info(
        "POST /student/website-analysis/analyze: user=%s url=%s",
        user_id,
        body.url,
    )
    try:
        svc = WebsiteAnalyzerService()
        return svc.analyze(url=body.url, skill_focus=body.skill_focus)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_url", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception(
            "POST /student/website-analysis/analyze: unexpected error for user=%s url=%s",
            user_id,
            body.url,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "analysis_failed", "message": "Website analysis could not be completed."},
        ) from exc
