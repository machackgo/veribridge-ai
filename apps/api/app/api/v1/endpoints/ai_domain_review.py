"""AI Domain Reviewer Agent endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.schemas.ai_domain_review import AiDomainReviewResultResponse
from app.services.ai_domain_review_service import (
    AiDomainReviewNotFoundError,
    AiDomainReviewService,
)
from app.services.extension_proof_service import ExtensionProofSessionNotFoundError

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/{session_id}/ai-domain-review",
    response_model=AiDomainReviewResultResponse,
    status_code=status.HTTP_200_OK,
    summary="Run or fetch an AI Domain Review for a proof session",
)
def run_ai_domain_review(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> AiDomainReviewResultResponse:
    try:
        return AiDomainReviewService(db).run_or_fetch_review(user_id, session_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise _not_found(session_id) from exc
    except Exception as exc:
        logger.exception("POST ai-domain-review failed for session %s", session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "ai_domain_review_failed",
                "message": "AI domain review could not be completed.",
            },
        ) from exc


@router.get(
    "/{session_id}/ai-domain-review",
    response_model=AiDomainReviewResultResponse,
    summary="Get the saved AI Domain Review for a proof session",
)
def get_ai_domain_review(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> AiDomainReviewResultResponse:
    try:
        return AiDomainReviewService(db).get_review(user_id, session_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise _not_found(session_id) from exc
    except AiDomainReviewNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "ai_domain_review_not_found",
                "message": "No AI domain review exists for this session yet.",
                "session_id": session_id,
            },
        ) from exc


def _not_found(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "extension_proof_session_not_found",
            "message": "Extension proof session not found for the current user.",
            "session_id": session_id,
        },
    )
