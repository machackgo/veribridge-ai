"""Standalone Document Proof / supporting evidence endpoints.

Students can submit pasted report/explanation text or upload a document
(PDF/DOCX/TXT/MD) as supporting evidence — independent of any Website Proof
session. Submissions are persisted via OptionalEvidenceService with
proof_session_id=None and never expose raw document text to the client.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.api.deps import get_current_user_id, get_db, get_provisioned_user_id
from app.schemas.document_proof import DocumentProofResponse, DocumentProofTextSubmit
from app.services import proof_artifact_service
from app.services.optional_evidence_service import (
    OptionalEvidencePersistError,
    OptionalEvidenceService,
    _SUPPORTED_EXTENSIONS,
)

_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
_STANDALONE_SOURCE_TYPES = ("document", "certificate_transcript")

_DOCUMENT_MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}

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
    # First-write flow: a fresh user's submission FKs public.users — provision.
    user_id: str = Depends(get_provisioned_user_id),
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
    # Explicit, student-controlled recruiter-share consent for the ORIGINAL
    # file. Default closed: the retained original stays owner-only.
    share_with_recruiters: bool = Form(default=False),
    # First-write flow: a fresh user's upload FKs public.users — provision.
    user_id: str = Depends(get_provisioned_user_id),
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
    extra_metadata: dict[str, Any] = {
        "title": title or filename,
        "claimed_skills": skills,
        "description": description,
    }
    if share_with_recruiters:
        # The dedicated download-consent field the vault's document gating reads
        # (see _DOWNLOAD_CONSENT_FIELDS in student_proof_vault_service) — an
        # actual boolean True, recorded only on explicit opt-in.
        extra_metadata["recruiter_shareable"] = True
    try:
        row = OptionalEvidenceService(db).submit_file(
            user_id=user_id,
            proof_session_id=None,
            file_bytes=content,
            filename=filename,
            source_type=source_type,  # type: ignore[arg-type]
            extra_metadata=extra_metadata,
            strict=True,
        )
    except OptionalEvidencePersistError as exc:
        raise _persist_error() from exc

    # ── Retain the ORIGINAL file as a gated proof artifact (migration 056) ────
    # Best-effort and honest: when retention storage is not configured the
    # submission stays verified-excerpts-only (original_retained=False) — the
    # analysis above is unaffected either way. Consent maps to the access
    # policy: shared → public_safe (served to recruiters via the gated
    # artifact routes), otherwise owner-only.
    artifact = proof_artifact_service.register_artifact_with_bytes(
        db,
        owner_user_id=user_id,
        proof_type="document",
        artifact_type="document_original",
        data=content,
        file_name=filename,
        mime_type=file.content_type or _DOCUMENT_MIME_BY_EXT.get(ext, "application/octet-stream"),
        proof_id=str(row.get("id") or ""),
        access_policy="public_safe" if share_with_recruiters else "owner_only",
    )

    response = _to_response(row, user_id)
    if artifact is not None:
        response.original_retained = True
        response.original_artifact_id = str(artifact["id"])
    return response


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
