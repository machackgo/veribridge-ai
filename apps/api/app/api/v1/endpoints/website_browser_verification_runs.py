"""Safe browser website verification run API endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.db.supabase import SupabaseError
from app.schemas.website_browser_verification_run import (
    WebsiteBrowserVerificationExecutionRequest,
    WebsiteBrowserVerificationRunListResponse,
    WebsiteBrowserVerificationRunResponse,
)
from app.services.skill_evidence_service import SkillEvidenceNotFoundError
from app.services.website_browser_verification_executor_service import (
    WebsiteBrowserVerificationExecutorService,
    WebsiteBrowserVerificationRunNotFoundError,
)
from app.services.website_verification_guide_service import WebsiteVerificationGuideNotAllowedError
from app.services.website_verification_plan_service import WebsiteVerificationPlanNotFoundError

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/{evidence_id}/website-browser-verification-runs",
    response_model=WebsiteBrowserVerificationRunResponse,
    summary="Execute a safe browser website verification run",
)
def execute_website_browser_verification_run(
    evidence_id: str,
    body: WebsiteBrowserVerificationExecutionRequest | None = None,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WebsiteBrowserVerificationRunResponse:
    try:
        service = WebsiteBrowserVerificationExecutorService(db)
        if body and body.plan_id:
            return service.execute_browser_verification_plan(user_id, evidence_id, body.plan_id)
        return service.execute_latest_browser_verification_plan(user_id, evidence_id)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except WebsiteVerificationPlanNotFoundError as exc:
        raise _plan_not_found(evidence_id) from exc
    except WebsiteVerificationGuideNotAllowedError as exc:
        raise _browser_run_not_allowed(str(exc), evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("POST /student/skill-evidence/%s/website-browser-verification-runs: unexpected error", evidence_id)
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}/website-browser-verification-runs/latest",
    response_model=WebsiteBrowserVerificationRunResponse,
    summary="Get the latest safe browser website verification run",
)
def get_latest_website_browser_verification_run(
    evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WebsiteBrowserVerificationRunResponse:
    try:
        return WebsiteBrowserVerificationExecutorService(db).get_latest_run(user_id, evidence_id)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except WebsiteBrowserVerificationRunNotFoundError as exc:
        raise _run_not_found(evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("GET /student/skill-evidence/%s/website-browser-verification-runs/latest: unexpected error", evidence_id)
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}/website-browser-verification-runs",
    response_model=WebsiteBrowserVerificationRunListResponse,
    summary="List safe browser website verification runs",
)
def list_website_browser_verification_runs(
    evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WebsiteBrowserVerificationRunListResponse:
    try:
        runs = WebsiteBrowserVerificationExecutorService(db).list_runs(user_id, evidence_id)
        return WebsiteBrowserVerificationRunListResponse(runs=runs)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("GET /student/skill-evidence/%s/website-browser-verification-runs: unexpected error", evidence_id)
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}/website-browser-verification-runs/{run_id}",
    response_model=WebsiteBrowserVerificationRunResponse,
    summary="Get one safe browser website verification run",
)
def get_website_browser_verification_run(
    evidence_id: str,
    run_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WebsiteBrowserVerificationRunResponse:
    try:
        return WebsiteBrowserVerificationExecutorService(db).get_run(user_id, evidence_id, run_id)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except WebsiteBrowserVerificationRunNotFoundError as exc:
        raise _run_not_found(run_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("GET /student/skill-evidence/%s/website-browser-verification-runs/%s: unexpected error", evidence_id, run_id)
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
            "code": "website_browser_verification_run_not_found",
            "message": "Website browser verification run not found for the current user.",
            "run_id": run_id,
        },
    )


def _browser_run_not_allowed(message: str, evidence_id: str) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": "website_browser_verification_run_not_allowed",
            "message": message,
            "evidence_id": evidence_id,
        },
    )


def _database_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "database_unavailable",
            "message": "The website browser verification run store is temporarily unavailable.",
        },
    )
