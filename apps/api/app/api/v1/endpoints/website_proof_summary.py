"""Safe Website Proof summary listing — for attaching to Project Defense.

Lists the current student's completed Website Proof sessions
(``workflow_analysis_results`` rows) using only safe summary fields. Never
exposes screenshots, storage paths, signed URLs, tokens, or raw artifact
data.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user_id, get_db
from app.schemas.website_proof_session import (
    WebsiteProofRecommendationRequest,
    WebsiteProofRecommendationResponse,
    WebsiteProofSummaryResponse,
)
from app.services.website_proof_recommendation_service import recommend_website_proofs
from app.services.website_proof_summary_service import list_website_proof_summaries

router = APIRouter()


@router.get(
    "/proofs",
    response_model=list[WebsiteProofSummaryResponse],
    summary="List the current student's completed Website Proof sessions (safe summaries)",
)
def list_my_website_proofs(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> list[WebsiteProofSummaryResponse]:
    rows = list_website_proof_summaries(db, user_id)
    return [WebsiteProofSummaryResponse(**row) for row in rows]


@router.post(
    "/recommendations",
    response_model=WebsiteProofRecommendationResponse,
    summary="Recommend the student's saved Website Proofs for a Project Defense (deterministic)",
)
def recommend_my_website_proofs(
    body: WebsiteProofRecommendationRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WebsiteProofRecommendationResponse:
    result = recommend_website_proofs(
        db,
        user_id,
        project_title=body.project_title,
        project_description=body.project_description,
        repo_url=body.repo_url,
        claimed_skills=body.claimed_skills,
    )
    return WebsiteProofRecommendationResponse(**result)
