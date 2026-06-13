"""Standalone Document Proof / supporting evidence endpoints.

Students can submit pasted report/explanation text or upload a document
(PDF/DOCX/TXT/MD) as supporting evidence — independent of any Website Proof
session. Submissions are persisted via OptionalEvidenceService with
proof_session_id=None and never expose raw document text to the client.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.api.deps import get_current_user_id, get_db
from app.schemas.document_proof import DocumentProofResponse, DocumentProofTextSubmit
from app.services.optional_evidence_service import (
    OptionalEvidencePersistError,
    OptionalEvidenceService,
    _SUPPORTED_EXTENSIONS,
)

_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
_STANDALONE_SOURCE_TYPES = ("document", "certificate_transcript")

router = APIRouter()


def _clean_skills(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if text and text not in out:
            out.append(text)
    return out[:20]


def _persist_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"code": "persist_failed", "message": "Could not save document proof. Please try again."},
    )


def _to_response(row: dict[str, Any], user_id: str) -> DocumentProofResponse:
    analysis_json = row.get("analysis_json") or {}
    return DocumentProofResponse(
        id=str(row.get("id") or ""),
        user_id=str(row.get("user_id") or user_id),
        source_type=row.get("source_type") or "document",
        status=str(row.get("status") or "not_added"),
        filename=row.get("file_path"),
        title=analysis_json.get("title"),
        claimed_skills=analysis_json.get("claimed_skills") or [],
        description=analysis_json.get("description"),
        analysis_json=analysis_json,
        evidence_objects=row.get("evidence_objects") or [],
        created_at=str(row.get("created_at")) if row.get("created_at") else None,
    )


@router.post(
    "",
    response_model=DocumentProofResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit pasted document/report text as standalone supporting evidence",
)
def submit_document_proof(
    body: DocumentProofTextSubmit,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> DocumentProofResponse:
    try:
        row = OptionalEvidenceService(db).submit_text(
            user_id=user_id,
            proof_session_id=None,
            source_type=body.source_type,
            raw_text=body.raw_text,
            section_label=body.title,
            extra_metadata={
                "title": body.title,
                "claimed_skills": _clean_skills(body.claimed_skills),
                "description": body.description,
            },
            strict=True,
        )
    except OptionalEvidencePersistError as exc:
        raise _persist_error() from exc
    return _to_response(row, user_id)


@router.post(
    "/upload",
    response_model=DocumentProofResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document file (PDF/DOCX/TXT/MD) as standalone supporting evidence",
)
async def upload_document_proof(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    claimed_skills: str | None = Form(default=None),
    description: str | None = Form(default=None),
    source_type: str = Form(default="document"),
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> DocumentProofResponse:
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

    if source_type not in _STANDALONE_SOURCE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "unsupported_source_type",
                "message": "source_type must be 'document' or 'certificate_transcript'.",
            },
        )

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"code": "file_too_large", "message": "File exceeds 20 MB limit."},
        )

    skills = _clean_skills((claimed_skills or "").split(",")) if claimed_skills else []
    try:
        row = OptionalEvidenceService(db).submit_file(
            user_id=user_id,
            proof_session_id=None,
            file_bytes=content,
            filename=filename,
            source_type=source_type,  # type: ignore[arg-type]
            extra_metadata={
                "title": title or filename,
                "claimed_skills": skills,
                "description": description,
            },
            strict=True,
        )
    except OptionalEvidencePersistError as exc:
        raise _persist_error() from exc
    return _to_response(row, user_id)


@router.get(
    "",
    response_model=list[DocumentProofResponse],
    summary="List standalone document proofs for the current student",
)
def list_document_proofs(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> list[DocumentProofResponse]:
    rows = OptionalEvidenceService(db).list_standalone_for_user(
        user_id=user_id, source_types=_STANDALONE_SOURCE_TYPES
    )
    return [_to_response(row, user_id) for row in rows]
