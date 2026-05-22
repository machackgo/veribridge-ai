"""Student-facing GitHub Portfolio Scan API endpoints (Phase J3B).

POST /api/v1/student/github-portfolio/scan            → dry-run scan preview
POST /api/v1/student/github-portfolio/import-selected → save approved candidates
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.db.supabase import SupabaseError
from app.schemas.github_portfolio import (
    GitHubPortfolioCandidateResult,
    GitHubPortfolioImportRequest,
    GitHubPortfolioImportResponse,
    GitHubPortfolioScanRequest,
    GitHubPortfolioScanResponse,
    extract_github_username,
)
from app.services.github_portfolio_scan_service import (
    import_selected_candidates,
    run_portfolio_scan,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/scan",
    response_model=GitHubPortfolioScanResponse,
    summary="Dry-run scan of a public GitHub profile — returns proof candidates without saving",
)
def scan_github_portfolio(
    body: GitHubPortfolioScanRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> GitHubPortfolioScanResponse:
    github_username = extract_github_username(body.github_profile_url, body.github_username)
    if not github_username:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_github_profile",
                "message": (
                    "Could not parse a GitHub username from the provided URL or username. "
                    "Provide a URL like https://github.com/username or a plain username."
                ),
            },
        )

    try:
        return run_portfolio_scan(
            github_username=github_username,
            max_repos=body.max_repos,
            include_forks=body.include_forks,
            include_archived=body.include_archived,
            smart_scan=body.smart_scan,
        )
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception(
            "POST /student/github-portfolio/scan: unexpected error for user=%s username=%s",
            user_id,
            github_username,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "scan_failed",
                "message": "GitHub portfolio scan could not be completed. Please try again.",
            },
        ) from exc


@router.post(
    "/import-selected",
    response_model=GitHubPortfolioImportResponse,
    status_code=status.HTTP_200_OK,
    summary="Save approved scan candidates as skill proof evidence for the current student",
)
def import_selected_github_candidates(
    body: GitHubPortfolioImportRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> GitHubPortfolioImportResponse:
    try:
        raw_results = import_selected_candidates(db, user_id, body.proof_candidates)
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception(
            "POST /student/github-portfolio/import-selected: unexpected error for user=%s",
            user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "import_failed",
                "message": "GitHub portfolio import could not be completed. Please try again.",
            },
        ) from exc

    per_candidate = [GitHubPortfolioCandidateResult(**r) for r in raw_results]
    imported = [r for r in per_candidate if r.status == "imported"]
    skipped = [r for r in per_candidate if r.status == "skipped_duplicate"]
    failed = [r for r in per_candidate if r.status == "failed"]

    return GitHubPortfolioImportResponse(
        imported_count=len(imported),
        skipped_duplicate_count=len(skipped),
        failed_count=len(failed),
        imported_evidence_ids=[r.evidence_id for r in imported if r.evidence_id],
        per_candidate_results=per_candidate,
    )


def _database_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "database_unavailable",
            "message": "The database is temporarily unavailable.",
        },
    )
