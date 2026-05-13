"""Website verification run API endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.db.supabase import SupabaseError
from app.schemas.website_verification_run import (
    WebsiteVerificationRunExecuteRequest,
    WebsiteVerificationRunListResponse,
    WebsiteVerificationRunResponse,
)
from app.services.skill_evidence_service import SkillEvidenceNotFoundError
from app.services.website_verification_executor_service import (
    WebsiteVerificationExecutorService,
    WebsiteVerificationRunNotFoundError,
)
from app.services.website_verification_guide_service import WebsiteVerificationGuideNotAllowedError
from app.services.website_verification_plan_service import WebsiteVerificationPlanNotFoundError

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/{evidence_id}/website-verification-runs",
    response_model=WebsiteVerificationRunResponse,
    summary="Execute a static website verification run",
)
def execute_website_verification_run(
    evidence_id: str,
    body: WebsiteVerificationRunExecuteRequest | None = None,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WebsiteVerificationRunResponse:
    try:
        service = WebsiteVerificationExecutorService(db)
        if body and body.plan_id:
            return service.execute_website_verification_plan(user_id, evidence_id, body.plan_id)
        return service.execute_latest_website_verification_plan(user_id, evidence_id)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except WebsiteVerificationPlanNotFoundError as exc:
        raise _plan_not_found(evidence_id) from exc
    except WebsiteVerificationGuideNotAllowedError as exc:
        raise _website_run_not_allowed(str(exc), evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("POST /student/skill-evidence/%s/website-verification-runs: unexpected error", evidence_id)
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}/website-verification-runs/latest",
    response_model=WebsiteVerificationRunResponse,
    summary="Get the latest website verification run",
)
def get_latest_website_verification_run(
    evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WebsiteVerificationRunResponse:
    try:
        return WebsiteVerificationExecutorService(db).get_latest_run(user_id, evidence_id)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except WebsiteVerificationRunNotFoundError as exc:
        raise _run_not_found(evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("GET /student/skill-evidence/%s/website-verification-runs/latest: unexpected error", evidence_id)
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}/website-verification-runs",
    response_model=WebsiteVerificationRunListResponse,
    summary="List website verification runs",
)
def list_website_verification_runs(
    evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WebsiteVerificationRunListResponse:
    try:
        runs = WebsiteVerificationExecutorService(db).list_runs(user_id, evidence_id)
        return WebsiteVerificationRunListResponse(runs=runs)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("GET /student/skill-evidence/%s/website-verification-runs: unexpected error", evidence_id)
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}/website-verification-runs/{run_id}",
    response_model=WebsiteVerificationRunResponse,
    summary="Get one website verification run",
)
def get_website_verification_run(
    evidence_id: str,
    run_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WebsiteVerificationRunResponse:
    try:
        return WebsiteVerificationExecutorService(db).get_run(user_id, evidence_id, run_id)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except WebsiteVerificationRunNotFoundError as exc:
        raise _run_not_found(run_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("GET /student/skill-evidence/%s/website-verification-runs/%s: unexpected error", evidence_id, run_id)
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


def _run_not_found(run_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "website_verification_run_not_found",
            "message": "Website verification run not found for the current user.",
            "run_id": run_id,
        },
    )


def _website_run_not_allowed(message: str, evidence_id: str) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": "website_verification_run_not_allowed",
            "message": message,
            "evidence_id": evidence_id,
        },
    )


def _database_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "database_unavailable",
            "message": "The website verification run store is temporarily unavailable.",
        },
    )
