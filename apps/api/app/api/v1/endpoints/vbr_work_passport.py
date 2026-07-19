"""Verified Work Passport (v1) endpoints.

Owner-only (auth required, ownership enforced because ``get_db`` is the
service-role client):
  ``GET    /api/v1/student/vbr/passport``          — private evidence wallet
  ``GET    /api/v1/student/vbr/passport/status``   — publish status
  ``POST   /api/v1/student/vbr/passport/publish``  — publish / re-publish
  ``POST   /api/v1/student/vbr/passport/unpublish``— hide the public passport

Public (no auth, requires an actively published passport):
  ``GET    /api/v1/public/p/{public_slug}``                 — recruiter-safe profile
  ``GET    /api/v1/public/p/{public_slug}/skills/{skill}``  — recruiter-safe skill report
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.core.config import settings
from app.schemas.proof_reanalysis import (
    ProofReanalysisRequestBody,
    ProofReanalysisResultResponse,
)
from app.schemas.canonical_evidence import (
    ProofFinalizationResponse,
    ProjectRelationshipConfirmRequest,
    ProjectRelationshipDescriptor,
)
from app.schemas.vbr_student_report import SkillReportResponse
from app.schemas.vbr_work_passport import (
    PassportPhotoResponse,
    PrivateWorkPassportResponse,
    PublicSkillReportResponse,
    PublicWorkPassportResponse,
    PublishPassportRequest,
    WorkPassportStatusResponse,
)
from app.services.passport_avatar_service import (
    MAX_AVATAR_BYTES,
    AvatarStorageError,
    AvatarStorageUnavailable,
    AvatarValidationError,
    clear_avatar,
    set_avatar,
)
from app.services.proof_reanalysis_service import (
    ProofReanalysisRequest,
    reanalyze_student_proofs,
)
from app.services.student_proof_vault_service import collect_skill_report
from app.services.canonical_evidence_service import (
    CanonicalEvidenceConflictError,
    CanonicalEvidenceNotFoundError,
    CanonicalEvidencePersistenceError,
    CanonicalEvidencePreconditionError,
    confirm_project_relationship,
    finalize_proof_evidence,
)
from app.services.vbr_work_passport_service import (
    build_private_passport,
    build_public_passport,
    build_public_skill_report,
    get_passport_status,
    publish_passport,
    unpublish_passport,
)

student_router = APIRouter()
public_router = APIRouter()


@student_router.get(
    "/passport",
    response_model=PrivateWorkPassportResponse,
    summary="Get the current user's private Verified Work Passport",
)
def get_private_passport_route(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> PrivateWorkPassportResponse:
    return PrivateWorkPassportResponse(**build_private_passport(db, pipeline_db, user_id))


@student_router.post(
    "/passport/proof-relationships/confirm",
    response_model=ProjectRelationshipDescriptor,
    summary="Confirm an owned proof belongs to an owned project",
)
def confirm_proof_project_relationship_route(
    body: ProjectRelationshipConfirmRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ProjectRelationshipDescriptor:
    try:
        result = confirm_project_relationship(
            db,
            user_id=user_id,
            proof_type=body.proof_type,
            proof_id=body.proof_id,
            project_id=body.project_id,
        )
    except CanonicalEvidenceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "proof_or_project_not_found", "message": "Proof or project not found."},
        ) from exc
    except CanonicalEvidenceConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "proof_relationship_conflict", "message": str(exc)},
        ) from exc
    except CanonicalEvidencePreconditionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "proof_relationship_precondition", "message": str(exc)},
        ) from exc
    except CanonicalEvidencePersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "proof_relationship_unavailable", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "unsupported_proof_relationship", "message": str(exc)},
        ) from exc
    return ProjectRelationshipDescriptor(**result)


@student_router.post(
    "/passport/proofs/finalize",
    response_model=ProofFinalizationResponse,
    summary="Finalize an owned proof against an owned project",
)
def finalize_proof_route(
    body: ProjectRelationshipConfirmRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> ProofFinalizationResponse:
    """The single authenticated API boundary for canonical proof finalization."""
    try:
        result = finalize_proof_evidence(
            db,
            user_id=user_id,
            proof_type=body.proof_type,
            proof_id=body.proof_id,
            project_id=body.project_id,
            pipeline_db=pipeline_db,
        )
    except CanonicalEvidenceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "proof_or_project_not_found", "message": "Proof or project not found."},
        ) from exc
    except CanonicalEvidenceConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "proof_relationship_conflict", "message": str(exc)},
        ) from exc
    except CanonicalEvidencePreconditionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "proof_finalization_precondition", "message": str(exc)},
        ) from exc
    except CanonicalEvidencePersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "proof_finalization_unavailable", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "unsupported_proof_type", "message": str(exc)},
        ) from exc
    return ProofFinalizationResponse(**result)


@student_router.get(
    "/passport/skill-report",
    response_model=SkillReportResponse,
    summary="Get the full Student Proof Vault evidence for one selected skill",
)
def get_skill_report_route(
    skill: str = Query(..., min_length=1, max_length=160),
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> SkillReportResponse:
    return SkillReportResponse(**collect_skill_report(db, pipeline_db, user_id, skill))


@student_router.post(
    "/passport/reanalyze",
    response_model=ProofReanalysisResultResponse,
    summary="Explicitly reanalyze (backfill) the current user's own proofs",
)
def reanalyze_passport_route(
    body: ProofReanalysisRequestBody | None = None,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> ProofReanalysisResultResponse:
    """Owner-only, explicit Step-6 reanalysis of the caller's existing proofs.

    ``student_id`` is taken from the auth token (never the request body), so a
    caller can only ever reanalyze their OWN proofs. Returns the recruiter-safe
    public projection — aggregate counts, safe reasons and safe evidence-id
    hashes only.
    """
    payload = body or ProofReanalysisRequestBody()
    request = ProofReanalysisRequest(
        student_id=user_id,
        project_id=payload.project_id,
        skill_name=payload.skill_name,
        proof_types=tuple(payload.proof_types) if payload.proof_types else None,
        include_llm_synthesis=payload.include_llm_synthesis,
        dry_run=payload.dry_run,
    )
    result = reanalyze_student_proofs(db, pipeline_db, request)
    return ProofReanalysisResultResponse(**result.public_view())


@student_router.get(
    "/passport/status",
    response_model=WorkPassportStatusResponse,
    summary="Get the publish status of the current user's Work Passport",
)
def get_passport_status_route(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WorkPassportStatusResponse:
    return WorkPassportStatusResponse(**get_passport_status(db, user_id))


@student_router.post(
    "/passport/publish",
    response_model=WorkPassportStatusResponse,
    summary="Publish (or re-publish) the current user's public Work Passport",
)
def publish_passport_route(
    body: PublishPassportRequest | None = None,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WorkPassportStatusResponse:
    payload = body or PublishPassportRequest()
    result = publish_passport(db, user_id, headline=payload.headline, summary=payload.summary)
    return WorkPassportStatusResponse(**result)


@student_router.post(
    "/passport/unpublish",
    response_model=WorkPassportStatusResponse,
    summary="Hide the current user's public Work Passport",
)
def unpublish_passport_route(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WorkPassportStatusResponse:
    return WorkPassportStatusResponse(**unpublish_passport(db, user_id))


@student_router.put(
    "/passport/identity/photo",
    response_model=PassportPhotoResponse,
    summary="Upload / replace the current user's Passport Card profile photo",
)
async def set_passport_photo_route(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> PassportPhotoResponse:
    """Validate and store the caller's OWN profile photo (auth token → owner).

    Accepts JPEG / PNG / WebP up to the size cap; the photo is written to the
    public ``passport-avatars`` bucket under the caller's own prefix and its
    public URL is persisted on the identity header. When storage is not
    configured the call succeeds with ``persisted=false`` so the client can keep
    a local-only preview rather than erroring.
    """
    content = await file.read()
    # Guard the size before any storage work (authoritative server-side check).
    if len(content) > MAX_AVATAR_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "avatar_too_large",
                "message": "Please upload a JPG, PNG, or WebP image under 5MB.",
            },
        )
    try:
        url = set_avatar(
            db,
            str(user_id),
            content=content,
            content_type=file.content_type,
            bucket=settings.supabase_passport_avatar_bucket,
        )
    except AvatarValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "avatar_invalid", "message": str(exc)},
        )
    except AvatarStorageUnavailable:
        # Storage not provisioned yet — not an error for the caller; the client
        # keeps the live local preview and labels it device-local.
        return PassportPhotoResponse(avatar_url=None, persisted=False)
    except AvatarStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "avatar_storage_failed", "message": str(exc)},
        )
    return PassportPhotoResponse(avatar_url=url, persisted=True)


@student_router.delete(
    "/passport/identity/photo",
    response_model=PassportPhotoResponse,
    summary="Remove the current user's Passport Card profile photo",
)
def remove_passport_photo_route(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> PassportPhotoResponse:
    """Clear the caller's OWN profile photo (object + persisted URL). Idempotent."""
    clear_avatar(db, str(user_id), bucket=settings.supabase_passport_avatar_bucket)
    return PassportPhotoResponse(avatar_url=None, persisted=True)


@public_router.get(
    "/p/{public_slug}",
    response_model=PublicWorkPassportResponse,
    summary="Get a published recruiter-safe Verified Work Passport (no auth required)",
)
def get_public_passport_route(
    public_slug: str,
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> PublicWorkPassportResponse:
    return PublicWorkPassportResponse(**build_public_passport(db, pipeline_db, public_slug))


@public_router.get(
    "/p/{public_slug}/skills/{skill}",
    response_model=PublicSkillReportResponse,
    summary="Get one skill's recruiter-safe public Skill Report (no auth required)",
)
def get_public_skill_report_route(
    public_slug: str,
    skill: str,
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> PublicSkillReportResponse:
    """Public drilldown behind a passport skill row. ``skill`` accepts either a
    canonical name or a URL slug. Fail-closed: unpublished/unknown passports,
    skills with no proof, and payloads that trip the public unsafe-field scan all
    return the same generic 404. Deterministic — never calls an LLM provider."""
    return PublicSkillReportResponse(
        **build_public_skill_report(db, pipeline_db, public_slug, skill)
    )
