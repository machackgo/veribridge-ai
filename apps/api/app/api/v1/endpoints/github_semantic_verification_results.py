"""GitHub claim-to-code semantic verification result API endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.db.supabase import SupabaseError
from app.schemas.github_semantic_verification_result import (
    GitHubSemanticVerificationEvaluationRequest,
    GitHubSemanticVerificationResultListResponse,
    GitHubSemanticVerificationResultResponse,
)
from app.services.github_claim_code_semantic_verification_service import (
    GitHubSemanticVerificationNotAllowedError,
    GitHubSemanticVerificationResultNotFoundError,
    GitHubSemanticVerificationService,
)
from app.services.skill_evidence_service import SkillEvidenceNotFoundError

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/{evidence_id}/github-semantic-verification-results",
    response_model=GitHubSemanticVerificationResultResponse,
    summary="Evaluate semantic GitHub claim-to-code evidence",
)
def evaluate_github_semantic_verification_result(
    evidence_id: str,
    body: GitHubSemanticVerificationEvaluationRequest | None = None,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> GitHubSemanticVerificationResultResponse:
    try:
        return GitHubSemanticVerificationService(db).evaluate_github_semantic_verification(user_id, evidence_id)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except GitHubSemanticVerificationNotAllowedError as exc:
        raise _semantic_verification_not_allowed(str(exc), evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("POST /student/skill-evidence/%s/github-semantic-verification-results: unexpected error", evidence_id)
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}/github-semantic-verification-results/latest",
    response_model=GitHubSemanticVerificationResultResponse,
    summary="Get the latest GitHub claim-to-code semantic verification result",
)
def get_latest_github_semantic_verification_result(
    evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> GitHubSemanticVerificationResultResponse:
    try:
        return GitHubSemanticVerificationService(db).get_latest_result(user_id, evidence_id)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except GitHubSemanticVerificationResultNotFoundError as exc:
        raise _result_not_found(evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception(
            "GET /student/skill-evidence/%s/github-semantic-verification-results/latest: unexpected error",
            evidence_id,
        )
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}/github-semantic-verification-results",
    response_model=GitHubSemanticVerificationResultListResponse,
    summary="List GitHub claim-to-code semantic verification results",
)
def list_github_semantic_verification_results(
    evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> GitHubSemanticVerificationResultListResponse:
    try:
        results = GitHubSemanticVerificationService(db).list_results(user_id, evidence_id)
        return GitHubSemanticVerificationResultListResponse(results=results)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("GET /student/skill-evidence/%s/github-semantic-verification-results: unexpected error", evidence_id)
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}/github-semantic-verification-results/{result_id}",
    response_model=GitHubSemanticVerificationResultResponse,
    summary="Get one GitHub claim-to-code semantic verification result",
)
def get_github_semantic_verification_result(
    evidence_id: str,
    result_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> GitHubSemanticVerificationResultResponse:
    try:
        return GitHubSemanticVerificationService(db).get_result(user_id, evidence_id, result_id)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except GitHubSemanticVerificationResultNotFoundError as exc:
        raise _result_not_found(result_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception(
            "GET /student/skill-evidence/%s/github-semantic-verification-results/%s: unexpected error",
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


def _result_not_found(result_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "github_semantic_verification_result_not_found",
            "message": "GitHub semantic verification result not found for the current user.",
            "result_id": result_id,
        },
    )


def _semantic_verification_not_allowed(message: str, evidence_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "github_semantic_verification_not_allowed",
            "message": message,
            "evidence_id": evidence_id,
        },
    )


def _database_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "database_unavailable",
            "message": "The GitHub semantic verification result store is temporarily unavailable.",
        },
    )
