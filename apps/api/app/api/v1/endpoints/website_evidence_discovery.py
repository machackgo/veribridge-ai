"""Website Evidence Discovery endpoint.

POST /student/website-analysis/discover

Scans a public website page and returns discovered evidence sources
(GitHub repos, video demos, PDFs, Google Docs/Drive, LinkedIn,
deployed apps, API docs, images/screenshots).

Privacy:
  - Only fetches public URLs.
  - Does NOT store raw HTML.
  - Returns only public-safe metadata.
  - Student chooses next action; nothing is auto-submitted.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, HttpUrl

from app.api.deps import get_current_user_id, get_db
from app.services.website_evidence_discovery_service import (
    WebsiteEvidenceDiscoveryService,
    DiscoveredEvidenceItem,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response schemas ─────────────────────────────────────────────────

class DiscoverRequest(BaseModel):
    website_url: str = Field(
        description="Public URL of the website/portfolio to scan.",
    )
    proof_session_id: str | None = Field(
        default=None,
        description="Optional: associate this discovery scan with an existing proof session.",
    )


class DiscoveredItemResponse(BaseModel):
    evidence_type: str
    url: str
    domain: str
    title: str | None
    confidence: float
    reason: str
    suggested_action: str
    raw_text: str | None


class DiscoverResponse(BaseModel):
    source_url: str
    final_url: str | None
    status_code: int | None
    page_title: str | None
    items: list[DiscoveredItemResponse]
    total_discovered: int
    js_heavy_warning: bool
    limitation: str | None
    error: str | None
    version: str


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post(
    "/discover",
    response_model=DiscoverResponse,
    summary="Discover evidence sources from a public website",
    description=(
        "Fetches a public website page and detects linked/embedded proof sources: "
        "GitHub repos, video demos, PDFs, Google Docs/Drive, LinkedIn, deployed apps, "
        "API docs, and images/screenshots. "
        "Returns classified evidence items with suggested next actions. "
        "Does NOT auto-submit evidence; student chooses next step. "
        "For JS-heavy sites with no static links, returns a clear limitation message."
    ),
    tags=["website-evidence-discovery"],
)
def discover_website_evidence(
    body: DiscoverRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> DiscoverResponse:
    logger.info(
        "[EvidenceDiscovery] request user=%s url=%r session=%s",
        user_id, body.website_url[:80], body.proof_session_id or "(none)",
    )

    svc = WebsiteEvidenceDiscoveryService()
    result = svc.discover(
        website_url=body.website_url,
        proof_session_id=body.proof_session_id,
    )

    items = [
        DiscoveredItemResponse(
            evidence_type=item.evidence_type,
            url=item.url,
            domain=item.domain,
            title=item.title,
            confidence=item.confidence,
            reason=item.reason,
            suggested_action=item.suggested_action,
            raw_text=item.raw_text,
        )
        for item in result.items
    ]

    return DiscoverResponse(
        source_url=result.source_url,
        final_url=result.final_url,
        status_code=result.status_code,
        page_title=result.page_title,
        items=items,
        total_discovered=len(items),
        js_heavy_warning=result.js_heavy_warning,
        limitation=result.limitation,
        error=result.error,
        version=result.version,
    )
