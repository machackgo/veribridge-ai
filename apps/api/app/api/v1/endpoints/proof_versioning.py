"""Proof evidence versioning endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.schemas.proof_versioning import ProofEvidenceVersionCreateRequest, ProofEvidenceVersionResponse
from app.services.extension_proof_service import ExtensionProofSessionNotFoundError
from app.services.proof_versioning_service import (
    ProofEvidenceVersionNotFoundError,
    ProofVersioningService,
)

router = APIRouter()


@router.post(
    "/{session_id}/versions",
    response_model=ProofEvidenceVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new proof evidence version",
)
def create_version(
    session_id: str,
    body: ProofEvidenceVersionCreateRequest | None = None,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ProofEvidenceVersionResponse:
    try:
        payload = body or ProofEvidenceVersionCreateRequest()
        return ProofVersioningService(db).create_resubmission_version(
            user_id,
            session_id,
            change_summary=payload.change_summary,
            resubmission_reason=payload.resubmission_reason,
        )
    except ExtensionProofSessionNotFoundError as exc:
        raise _session_not_found(session_id) from exc


@router.get(
    "/{session_id}/versions",
    response_model=list[ProofEvidenceVersionResponse],
    summary="List proof evidence versions",
)
def list_versions(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> list[ProofEvidenceVersionResponse]:
    try:
        return ProofVersioningService(db).get_versions(user_id, session_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise _session_not_found(session_id) from exc


@router.get(
    "/{session_id}/versions/active",
    response_model=ProofEvidenceVersionResponse,
    summary="Get the active proof evidence version",
)
def get_active_version(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ProofEvidenceVersionResponse:
    try:
        return ProofVersioningService(db).get_active_version(user_id, session_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise _session_not_found(session_id) from exc


@router.post(
    "/{session_id}/versions/{version_id}/activate",
    response_model=ProofEvidenceVersionResponse,
    summary="Activate a proof evidence version",
)
def activate_version(
    session_id: str,
    version_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ProofEvidenceVersionResponse:
    try:
        return ProofVersioningService(db).set_active_version(user_id, session_id, version_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise _session_not_found(session_id) from exc
    except ProofEvidenceVersionNotFoundError as exc:
        raise _version_not_found(str(exc)) from exc


@router.post(
    "/{session_id}/versions/{version_id}/archive",
    response_model=ProofEvidenceVersionResponse,
    summary="Archive a proof evidence version",
)
def archive_version(
    session_id: str,
    version_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ProofEvidenceVersionResponse:
    try:
        return ProofVersioningService(db).archive_version(user_id, session_id, version_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise _session_not_found(session_id) from exc
    except ProofEvidenceVersionNotFoundError as exc:
        raise _version_not_found(str(exc)) from exc


def _session_not_found(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "extension_proof_session_not_found",
            "message": "Extension proof session not found for the current user.",
            "session_id": session_id,
        },
    )


def _version_not_found(version_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "proof_evidence_version_not_found",
            "message": "Proof evidence version not found for the current session.",
            "version_id": version_id,
        },
    )
