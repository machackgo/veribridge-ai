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
# Bounded streaming chunk size — same OOM-safe pattern as the workflow-video
# upload (workflow_visual_frames.py): never whole-body read before the size gate.
_UPLOAD_CHUNK_BYTES = 1024 * 1024
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


def _document_relationships(db: Any, user_id: str) -> dict[str, dict[str, Any]]:
    """document_evidence_id → canonical relationship, from the SAME sources the
    Passport/report attachment index reads: normalized 058 rows first, then the
    projects' ``attached_proofs.documents`` metadata. Owner-scoped; best-effort
    (a pre-058 database simply yields metadata-only results)."""
    out: dict[str, dict[str, Any]] = {}
    projects: dict[str, str] = {}
    try:
        if isinstance(db, dict):
            project_rows = [
                row for row in db.get("vbr_projects", {}).values()
                if str(row.get("user_id") or "") == str(user_id)
            ]
        else:
            resp = db.table("vbr_projects").select("id,title,metadata").eq("user_id", user_id).execute()
            project_rows = list(getattr(resp, "data", []) or [])
        for project in project_rows:
            pid = str(project.get("id") or "")
            projects[pid] = str(project.get("title") or "Project")
            attached = ((project.get("metadata") or {}).get("attached_proofs") or {})
            for doc in attached.get("documents") or []:
                doc_id = str((doc or {}).get("document_evidence_id") or "")
                if doc_id and doc_id not in out:
                    out[doc_id] = {
                        "project_id": pid,
                        "project_title": projects[pid],
                        "state": "directly_linked",
                    }
    except Exception:
        pass
    try:
        if isinstance(db, dict):
            relation_rows = [
                row for row in db.get("proof_project_relationships", {}).values()
                if str(row.get("owner_user_id") or "") == str(user_id)
                and row.get("proof_type") == "document"
            ]
        else:
            resp = (
                db.table("proof_project_relationships")
                .select("proof_id,project_id,relationship_state")
                .eq("owner_user_id", user_id)
                .eq("proof_type", "document")
                .execute()
            )
            relation_rows = list(getattr(resp, "data", []) or [])
        for relation in relation_rows:
            doc_id = str(relation.get("proof_id") or "")
            pid = str(relation.get("project_id") or "")
            if doc_id and relation.get("relationship_state") == "directly_linked" and pid in projects:
                out[doc_id] = {
                    "project_id": pid,
                    "project_title": projects[pid],
                    "state": "directly_linked",
                }
    except Exception:
        pass
    return out


def _to_response(
    row: dict[str, Any],
    user_id: str,
    relationships: dict[str, dict[str, Any]] | None = None,
) -> DocumentProofResponse:
    analysis_json = row.get("analysis_json") or {}
    relationship = (relationships or {}).get(str(row.get("id") or "")) or {}
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
        project_id=relationship.get("project_id"),
        project_title=relationship.get("project_title"),
        project_relationship_state=str(relationship.get("state") or "vault_only"),
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

    # Stream the body in bounded chunks — a bare ``await file.read()`` would
    # materialize an oversized body in memory BEFORE the size check (the same
    # failure mode as the workflow-video OOM incident). The 413 fires as soon
    # as the limit is crossed, without ever buffering more than limit + chunk.
    buffer = bytearray()
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={"code": "file_too_large", "message": "File exceeds 20 MB limit."},
            )
    content = bytes(buffer)

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
    # policy: shared → recruiter_safe (owner + AUTHENTICATED privileged
    # recruiter/reviewer callers via the gated artifact routes — the consented
    # scope is recruiters, never anonymous), otherwise owner-only.
    # Data repair for rows written before this fix mapped consent to
    # public_safe: see docs/data-repairs/2026-08-recruiter-share-access-policy.md.
    artifact = proof_artifact_service.register_artifact_with_bytes(
        db,
        owner_user_id=user_id,
        proof_type="document",
        artifact_type="document_original",
        data=content,
        file_name=filename,
        mime_type=file.content_type or _DOCUMENT_MIME_BY_EXT.get(ext, "application/octet-stream"),
        proof_id=str(row.get("id") or ""),
        access_policy="recruiter_safe" if share_with_recruiters else "owner_only",
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
    relationships = _document_relationships(db, user_id)
    return [_to_response(row, user_id, relationships) for row in rows]


@router.post(
    "/{evidence_id}/reextract-blocks",
    response_model=DocumentProofResponse,
    summary="Re-extract block-typed evidence from the retained original document",
)
def reextract_document_blocks(
    evidence_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> DocumentProofResponse:
    """Deterministic, additive block re-extraction (tables / charts / diagrams /
    code blocks / metrics with section+block locators) from the retained
    original. Idempotent; the original analysis is preserved. 404 when the
    submission is not owned; unchanged when no retained original exists."""
    service = OptionalEvidenceService(db)
    try:
        row = service.reextract_blocks_from_retained_original(
            user_id=user_id, evidence_id=evidence_id
        )
    except OptionalEvidencePersistError as exc:
        raise _persist_error() from exc
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "document_not_found", "message": "Document proof not found."},
        )
    relationships = _document_relationships(db, user_id)
    return _to_response(row, user_id, relationships)
