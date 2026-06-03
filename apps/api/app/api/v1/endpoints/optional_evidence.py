"""Optional evidence booster endpoints."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, HttpUrl

from app.api.deps import get_current_user_id, get_db
from app.services.extension_proof_service import (
    ExtensionProofSessionNotFoundError,
    ExtensionProofSessionService,
)
from app.services.optional_evidence_service import (
    OptionalEvidenceService,
    SourceType,
    _SUPPORTED_EXTENSIONS,
)

_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

router = APIRouter()


class OptionalEvidenceSubmitRequest(BaseModel):
    source_type: SourceType
    raw_text: str = Field(default="", max_length=80_000)
    profile_url: HttpUrl | None = None
    section_label: str | None = Field(default=None, max_length=120)
    file_path: str | None = Field(default=None, max_length=500)


class OptionalEvidenceResponse(BaseModel):
    user_id: str
    proof_session_id: str | None = None
    source_type: SourceType
    status: str
    file_path: str | None = None
    profile_url: str | None = None
    analysis_json: dict[str, Any] = Field(default_factory=dict)
    evidence_objects: list[dict[str, Any]] = Field(default_factory=list)


def _verify_session(user_id: str, session_id: str, db: Any) -> None:
    try:
        ExtensionProofSessionService(db)._get_row(user_id, session_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "session_not_found", "message": "Extension proof session not found."},
        ) from exc


def _to_response(row: dict[str, Any], user_id: str, session_id: str | None) -> OptionalEvidenceResponse:
    return OptionalEvidenceResponse(
        user_id=str(row.get("user_id") or user_id),
        proof_session_id=str(row.get("proof_session_id") or session_id) if (row.get("proof_session_id") or session_id) else None,
        source_type=row.get("source_type"),
        status=str(row.get("status") or "not_added"),
        file_path=row.get("file_path"),
        profile_url=row.get("profile_url"),
        analysis_json=row.get("analysis_json") or {},
        evidence_objects=row.get("evidence_objects") or [],
    )


@router.post(
    "/{session_id}/optional-evidence",
    response_model=OptionalEvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit optional document/profile/certificate evidence text for a proof session",
)
def submit_optional_evidence(
    session_id: str,
    body: OptionalEvidenceSubmitRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> OptionalEvidenceResponse:
    _verify_session(user_id, session_id, db)
    row = OptionalEvidenceService(db).submit_text(
        user_id=user_id,
        proof_session_id=session_id,
        source_type=body.source_type,
        raw_text=body.raw_text,
        profile_url=str(body.profile_url) if body.profile_url else None,
        section_label=body.section_label,
        file_path=body.file_path,
    )
    return _to_response(row, user_id, session_id)


@router.post(
    "/{session_id}/optional-evidence/upload",
    response_model=OptionalEvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document file (PDF/DOCX/TXT/MD) and extract evidence",
)
async def upload_optional_evidence_file(
    session_id: str,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> OptionalEvidenceResponse:
    _verify_session(user_id, session_id, db)

    filename = file.filename or "upload"
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "unsupported_file",
                "message": f"File type '{ext}' is not supported. Upload PDF, DOCX, TXT, or MD.",
            },
        )

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"code": "file_too_large", "message": "File exceeds 20 MB limit."},
        )

    row = OptionalEvidenceService(db).submit_file(
        user_id=user_id,
        proof_session_id=session_id,
        file_bytes=content,
        filename=filename,
    )
    return _to_response(row, user_id, session_id)


@router.get(
    "/{session_id}/optional-evidence",
    response_model=list[OptionalEvidenceResponse],
    summary="List optional evidence submissions for a proof session",
)
def list_optional_evidence(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> list[OptionalEvidenceResponse]:
    _verify_session(user_id, session_id, db)
    rows = OptionalEvidenceService(db).list_for_session(user_id=user_id, proof_session_id=session_id)
    return [_to_response(row, user_id, session_id) for row in rows]
