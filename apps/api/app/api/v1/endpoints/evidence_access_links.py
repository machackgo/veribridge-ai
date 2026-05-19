"""Direct evidence access link API endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.db.supabase import SupabaseError
from app.schemas.evidence_access_link import (
    EvidenceAccessLinkCreateResponse,
    EvidenceAccessLinkListResponse,
    EvidenceAccessLinkResponse,
)
from app.services.evidence_access_link_service import (
    EvidenceAccessLinkNotAllowedError,
    EvidenceAccessLinkNotFoundError,
    EvidenceAccessLinkService,
)
from app.services.skill_evidence_service import SkillEvidenceNotFoundError

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/{evidence_id}/evidence-access-links",
    response_model=EvidenceAccessLinkCreateResponse,
    summary="Generate recruiter-safe direct evidence access links",
)
def generate_evidence_access_links(
    evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> EvidenceAccessLinkCreateResponse:
    try:
        results = EvidenceAccessLinkService(db).generate_evidence_access_links(user_id, evidence_id)
        return EvidenceAccessLinkCreateResponse(results=results)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except EvidenceAccessLinkNotAllowedError as exc:
        raise _not_allowed(str(exc), evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("POST /student/skill-evidence/%s/evidence-access-links: unexpected error", evidence_id)
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}/evidence-access-links/latest",
    response_model=EvidenceAccessLinkListResponse,
    summary="Get the latest generated direct evidence access links",
)
def get_latest_evidence_access_links(
    evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> EvidenceAccessLinkListResponse:
    try:
        results = EvidenceAccessLinkService(db).list_latest_evidence_access_links(user_id, evidence_id)
        return EvidenceAccessLinkListResponse(results=results)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("GET /student/skill-evidence/%s/evidence-access-links/latest: unexpected error", evidence_id)
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}/evidence-access-links",
    response_model=EvidenceAccessLinkListResponse,
    summary="List direct evidence access links",
)
def list_evidence_access_links(
    evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> EvidenceAccessLinkListResponse:
    try:
        results = EvidenceAccessLinkService(db).list_evidence_access_links(user_id, evidence_id)
        return EvidenceAccessLinkListResponse(results=results)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("GET /student/skill-evidence/%s/evidence-access-links: unexpected error", evidence_id)
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}/evidence-access-links/{link_id}",
    response_model=EvidenceAccessLinkResponse,
    summary="Get one direct evidence access link",
)
def get_evidence_access_link(
    evidence_id: str,
    link_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> EvidenceAccessLinkResponse:
    try:
        return EvidenceAccessLinkService(db).get_evidence_access_link(user_id, evidence_id, link_id)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except EvidenceAccessLinkNotFoundError as exc:
        raise _link_not_found(str(exc)) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception(
            "GET /student/skill-evidence/%s/evidence-access-links/%s: unexpected error",
            evidence_id,
            link_id,
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


def _link_not_found(link_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "evidence_access_link_not_found",
            "message": "Evidence access link not found for the current user.",
            "link_id": link_id,
        },
    )


def _not_allowed(message: str, evidence_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "evidence_access_link_not_allowed",
            "message": message,
            "evidence_id": evidence_id,
        },
    )


def _database_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "database_unavailable",
            "message": "The evidence access link store is temporarily unavailable.",
        },
    )
