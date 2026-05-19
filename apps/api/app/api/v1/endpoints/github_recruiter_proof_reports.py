"""Recruiter-friendly GitHub proof report API endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.db.supabase import SupabaseError
from app.schemas.github_recruiter_proof_report import (
    GitHubRecruiterProofReportGenerateRequest,
    GitHubRecruiterProofReportListResponse,
    GitHubRecruiterProofReportResponse,
)
from app.services.github_claim_code_semantic_verification_service import GitHubSemanticVerificationResultNotFoundError
from app.services.github_recruiter_proof_report_service import (
    GitHubRecruiterProofReportNotAllowedError,
    GitHubRecruiterProofReportNotFoundError,
    GitHubRecruiterProofReportService,
)
from app.services.skill_evidence_service import SkillEvidenceNotFoundError

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/{evidence_id}/github-recruiter-proof-reports",
    response_model=GitHubRecruiterProofReportResponse,
    summary="Generate a recruiter-friendly GitHub proof report",
)
def generate_github_recruiter_proof_report(
    evidence_id: str,
    body: GitHubRecruiterProofReportGenerateRequest | None = None,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> GitHubRecruiterProofReportResponse:
    try:
        request = body or GitHubRecruiterProofReportGenerateRequest()
        return GitHubRecruiterProofReportService(db).generate_github_recruiter_proof_report(
            user_id=user_id,
            evidence_id=evidence_id,
            semantic_result_id=request.semantic_result_id,
        )
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except GitHubSemanticVerificationResultNotFoundError as exc:
        raise _semantic_result_not_found(str(exc)) from exc
    except GitHubRecruiterProofReportNotAllowedError as exc:
        raise _report_not_allowed(str(exc), evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception(
            "POST /student/skill-evidence/%s/github-recruiter-proof-reports: unexpected error",
            evidence_id,
        )
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}/github-recruiter-proof-reports/latest",
    response_model=GitHubRecruiterProofReportResponse,
    summary="Get the latest recruiter-friendly GitHub proof report",
)
def get_latest_github_recruiter_proof_report(
    evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> GitHubRecruiterProofReportResponse:
    try:
        return GitHubRecruiterProofReportService(db).get_latest_report(user_id, evidence_id)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except GitHubRecruiterProofReportNotFoundError as exc:
        raise _report_not_found(evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception(
            "GET /student/skill-evidence/%s/github-recruiter-proof-reports/latest: unexpected error",
            evidence_id,
        )
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}/github-recruiter-proof-reports",
    response_model=GitHubRecruiterProofReportListResponse,
    summary="List recruiter-friendly GitHub proof reports",
)
def list_github_recruiter_proof_reports(
    evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> GitHubRecruiterProofReportListResponse:
    try:
        results = GitHubRecruiterProofReportService(db).list_reports(user_id, evidence_id)
        return GitHubRecruiterProofReportListResponse(results=results)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception(
            "GET /student/skill-evidence/%s/github-recruiter-proof-reports: unexpected error",
            evidence_id,
        )
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}/github-recruiter-proof-reports/{report_id}",
    response_model=GitHubRecruiterProofReportResponse,
    summary="Get one recruiter-friendly GitHub proof report",
)
def get_github_recruiter_proof_report(
    evidence_id: str,
    report_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> GitHubRecruiterProofReportResponse:
    try:
        return GitHubRecruiterProofReportService(db).get_report(user_id, evidence_id, report_id)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except GitHubRecruiterProofReportNotFoundError as exc:
        raise _report_not_found(report_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception(
            "GET /student/skill-evidence/%s/github-recruiter-proof-reports/%s: unexpected error",
            evidence_id,
            report_id,
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


def _semantic_result_not_found(result_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "github_semantic_verification_result_not_found",
            "message": "GitHub semantic verification result not found for the current user.",
            "result_id": result_id,
        },
    )


def _report_not_found(report_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "github_recruiter_proof_report_not_found",
            "message": "GitHub recruiter proof report not found for the current user.",
            "report_id": report_id,
        },
    )


def _report_not_allowed(message: str, evidence_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "github_recruiter_proof_report_not_allowed",
            "message": message,
            "evidence_id": evidence_id,
        },
    )


def _database_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "database_unavailable",
            "message": "The GitHub recruiter proof report store is temporarily unavailable.",
        },
    )
