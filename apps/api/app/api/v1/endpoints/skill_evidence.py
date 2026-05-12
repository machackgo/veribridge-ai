"""Skill Proof Evidence API endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.db.supabase import SupabaseError
from app.schemas.skill_evidence import (
    PublicProofVerificationResponse,
    SkillEvidenceCreate,
    SkillEvidenceResponse,
    SkillEvidenceUpdate,
    SkillEvidenceVerifyResponse,
)
from app.services.public_proof_verification_service import (
    PublicProofNotVerifiableError,
    PublicProofVerificationNotFoundError,
    PublicProofVerificationService,
)
from app.services.skill_evidence_service import (
    SkillEvidenceNotFoundError,
    SkillEvidenceService,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "",
    response_model=list[SkillEvidenceResponse],
    summary="List current user's skill proof evidence",
)
def list_skill_evidence(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> list[SkillEvidenceResponse]:
    try:
        return SkillEvidenceService(db).list_skill_evidence(user_id)
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("GET /student/skill-evidence: unexpected error")
        raise _database_unavailable(exc) from exc


@router.post(
    "",
    response_model=SkillEvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create skill proof evidence",
)
def create_skill_evidence(
    body: SkillEvidenceCreate,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> SkillEvidenceResponse:
    try:
        return SkillEvidenceService(db).create_skill_evidence(user_id, body)
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("POST /student/skill-evidence: unexpected error")
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}",
    response_model=SkillEvidenceResponse,
    summary="Get one skill proof evidence record",
)
def get_skill_evidence(
    evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> SkillEvidenceResponse:
    try:
        return SkillEvidenceService(db).get_skill_evidence(user_id, evidence_id)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("GET /student/skill-evidence/%s: unexpected error", evidence_id)
        raise _database_unavailable(exc) from exc


@router.put(
    "/{evidence_id}",
    response_model=SkillEvidenceResponse,
    summary="Update skill proof evidence",
)
def update_skill_evidence(
    evidence_id: str,
    body: SkillEvidenceUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> SkillEvidenceResponse:
    try:
        return SkillEvidenceService(db).update_skill_evidence(user_id, evidence_id, body)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("PUT /student/skill-evidence/%s: unexpected error", evidence_id)
        raise _database_unavailable(exc) from exc


@router.delete(
    "/{evidence_id}",
    summary="Delete skill proof evidence",
)
def delete_skill_evidence(
    evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> dict[str, str | bool]:
    try:
        SkillEvidenceService(db).delete_skill_evidence(user_id, evidence_id)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("DELETE /student/skill-evidence/%s: unexpected error", evidence_id)
        raise _database_unavailable(exc) from exc

    return {"success": True, "message": "Skill evidence deleted."}


@router.post(
    "/{evidence_id}/verify",
    response_model=SkillEvidenceVerifyResponse,
    summary="Rerun mock verification for one evidence record",
)
def verify_skill_evidence(
    evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> SkillEvidenceVerifyResponse:
    try:
        evidence = SkillEvidenceService(db).verify_skill_evidence(user_id, evidence_id)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("POST /student/skill-evidence/%s/verify: unexpected error", evidence_id)
        raise _database_unavailable(exc) from exc

    return SkillEvidenceVerifyResponse(
        id=evidence.id,
        verification_status=evidence.verification_status,
        verification_summary=evidence.verification_summary or "",
        verifier_version=evidence.verifier_version or "",
        evidence=evidence,
    )


@router.post(
    "/{evidence_id}/public-verification",
    response_model=PublicProofVerificationResponse,
    summary="Run public proof verification for one evidence record",
)
def verify_public_proof_evidence(
    evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> PublicProofVerificationResponse:
    try:
        return PublicProofVerificationService(db).verify_public_proof(user_id, evidence_id)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except PublicProofNotVerifiableError as exc:
        raise _public_verification_not_allowed(str(exc), evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("POST /student/skill-evidence/%s/public-verification: unexpected error", evidence_id)
        raise _database_unavailable(exc) from exc


@router.get(
    "/{evidence_id}/public-verification/latest",
    response_model=PublicProofVerificationResponse,
    summary="Get the latest public proof verification result",
)
def get_latest_public_proof_verification(
    evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> PublicProofVerificationResponse:
    try:
        return PublicProofVerificationService(db).get_latest_public_verification(user_id, evidence_id)
    except SkillEvidenceNotFoundError as exc:
        raise _not_found(evidence_id) from exc
    except PublicProofVerificationNotFoundError as exc:
        raise _public_verification_not_found(evidence_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("GET /student/skill-evidence/%s/public-verification/latest: unexpected error", evidence_id)
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


def _database_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "database_unavailable",
            "message": "The skill evidence store is temporarily unavailable.",
        },
    )


def _public_verification_not_allowed(message: str, evidence_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "code": "public_proof_not_verifiable",
            "message": message,
            "evidence_id": evidence_id,
        },
    )


def _public_verification_not_found(evidence_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "public_proof_verification_not_found",
            "message": "No public proof verification result exists for this evidence record.",
            "evidence_id": evidence_id,
        },
    )
