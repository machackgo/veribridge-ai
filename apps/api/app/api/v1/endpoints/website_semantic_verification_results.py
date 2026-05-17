"""Semantic website verification result API endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.db.supabase import SupabaseError
from app.schemas.website_semantic_verification_result import (
    WebsiteSemanticVerificationEvaluationRequest,
    WebsiteSemanticVerificationResultListResponse,
    WebsiteSemanticVerificationResultResponse,
)
from app.services.skill_evidence_service import SkillEvidenceNotFoundError
from app.services.website_browser_verification_executor_service import WebsiteBrowserVerificationRunNotFoundError
from app.services.website_semantic_verification_service import (
    WebsiteSemanticVerificationResultNotFoundError,
    WebsiteSemanticVerificationService,
)
from app.services.website_verification_executor_service import WebsiteVerificationRunNotFoundError
from app.services.website_verification_guide_service import WebsiteVerificationGuideNotAllowedError
from app.services.website_verification_plan_service import WebsiteVerificationPlanNotFoundError

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/{evidence_id}/website-semantic-verification-results",
    response_model=WebsiteSemanticVerificationResultResponse,
    summary="Evaluate semantic website verification evidence",
)
def evaluate_website_semantic_verification_result(
    evidence_id: str,
    body: WebsiteSemanticVerificationEvaluationRequest | None = None,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WebsiteSemanticVerificationResultResponse:
    try:
        request = body or WebsiteSemanticVerificationEvaluationRequest()
        return WebsiteSemanticVerificationService(db).evaluate_website_semantic_verification(
            user_id=user_id,
            evidence_id=evidence_id,
            plan_id=request.plan_id,
            static_run_id=request.static_run_id,
            browser_run_id=request.browser_run_id,
        )
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except WebsiteVerificationPlanNotFoundError as exc:
        raise _plan_not_found(evidence_id) from exc
    except WebsiteVerificationRunNotFoundError as exc:
        raise _static_run_not_found(str(exc)) from exc
    except WebsiteBrowserVerificationRunNotFoundError as exc:
        raise _browser_run_not_found(str(exc)) from exc
    except WebsiteVerificationGuideNotAllowedError as exc:
        raise _semantic_verification_not_allowed(str(exc), evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("POST /student/skill-evidence/%s/website-semantic-verification-results: unexpected error", evidence_id)
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}/website-semantic-verification-results/latest",
    response_model=WebsiteSemanticVerificationResultResponse,
    summary="Get the latest semantic website verification result",
)
def get_latest_website_semantic_verification_result(
    evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WebsiteSemanticVerificationResultResponse:
    try:
        return WebsiteSemanticVerificationService(db).get_latest_result(user_id, evidence_id)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except WebsiteSemanticVerificationResultNotFoundError as exc:
        raise _result_not_found(evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("GET /student/skill-evidence/%s/website-semantic-verification-results/latest: unexpected error", evidence_id)
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}/website-semantic-verification-results",
    response_model=WebsiteSemanticVerificationResultListResponse,
    summary="List semantic website verification results",
)
def list_website_semantic_verification_results(
    evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WebsiteSemanticVerificationResultListResponse:
    try:
        results = WebsiteSemanticVerificationService(db).list_results(user_id, evidence_id)
        return WebsiteSemanticVerificationResultListResponse(results=results)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("GET /student/skill-evidence/%s/website-semantic-verification-results: unexpected error", evidence_id)
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}/website-semantic-verification-results/{result_id}",
    response_model=WebsiteSemanticVerificationResultResponse,
    summary="Get one semantic website verification result",
)
def get_website_semantic_verification_result(
    evidence_id: str,
    result_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WebsiteSemanticVerificationResultResponse:
    try:
        return WebsiteSemanticVerificationService(db).get_result(user_id, evidence_id, result_id)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except WebsiteSemanticVerificationResultNotFoundError as exc:
        raise _result_not_found(result_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception(
            "GET /student/skill-evidence/%s/website-semantic-verification-results/%s: unexpected error",
            evidence_id,
            result_id,
        )
        raise _database_unavailable(exc) from exc


def _not_found(evidence_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "skill_evidence_not_found",
            "message": "Skill evidence not found for the current user.",
            "evidence_id": evidence_id,
        },
    )


def _plan_not_found(evidence_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "website_verification_plan_not_found",
            "message": "No website verification plan exists for this evidence record.",
            "evidence_id": evidence_id,
        },
    )


def _static_run_not_found(run_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "website_verification_run_not_found",
            "message": "Website verification run not found for the current user.",
            "run_id": run_id,
        },
    )


def _browser_run_not_found(run_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "website_browser_verification_run_not_found",
            "message": "Website browser verification run not found for the current user.",
            "run_id": run_id,
        },
    )


def _result_not_found(result_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "website_semantic_verification_result_not_found",
            "message": "Website semantic verification result not found for the current user.",
            "result_id": result_id,
        },
    )


def _semantic_verification_not_allowed(message: str, evidence_id: str) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": "website_semantic_verification_not_allowed",
            "message": message,
            "evidence_id": evidence_id,
        },
    )


def _database_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "database_unavailable",
            "message": "The website semantic verification result store is temporarily unavailable.",
        },
    )
