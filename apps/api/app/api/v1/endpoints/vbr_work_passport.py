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

import logging

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)

from app.db.supabase import run_with_transient_retry
from app.api.deps import (
    get_current_user_id,
    get_db,
    get_optional_user_id,
    get_pipeline_db,
    get_provisioned_user_id,
)
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
from app.schemas.passport_disclosure import (
    DisclosureContextResponse,
    DisclosureModeRequest,
    DisclosureOverridesRequest,
    DisclosurePresetRequest,
)
from app.schemas.passport_profile import (
    PassportProfileResponse,
    PassportProfileUpsert,
)
from app.schemas.vbr_student_report import SkillReportResponse
from app.schemas.vbr_work_passport import (
    PassportPhotoResponse,
    PrivateWorkPassportResponse,
    PublicPassportViewAck,
    PublicPassportViewEvent,
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
from app.services.passport_profile_service import (
    PassportProfileValidationError,
    get_editor_context,
    upsert_passport_profile,
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
from app.services.passport_disclosure import (
    MODE_CUSTOM,
    MODE_RECRUITER_SAFE,
    DisclosureValidationError,
    apply_disclosure_overrides,
    clear_disclosure_overrides,
    set_disclosure_mode,
)
from app.services.passport_disclosure_editor import (
    PRESETS,
    build_disclosure_context,
    preset_changes,
)
from app.services.recruiter_search_service import refresh_search_projection
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
    # Pure read. The transport race that used to make this 500 whenever the
    # page's concurrent disclosure call was in flight is fixed at the root
    # (clients are per-thread now, and the report pool reuses that cache
    # instead of churning a new client per request). What remains is the
    # unavoidable case: a keepalive connection the peer closed while idle,
    # which surfaces as [Errno 11] on first reuse and cannot be prevented
    # client-side. Retrying a read once on a fresh client is the correct
    # handling for that — not a mask for the race.
    return PrivateWorkPassportResponse(
        **run_with_transient_retry(
            db,
            lambda client: build_private_passport(client, pipeline_db, user_id),
            op="GET /student/vbr/passport",
        )
    )


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
    # First write for a brand-new account: vbr_work_passports.user_id FKs
    # public.users(id), so the caller's row must exist before the insert.
    user_id: str = Depends(get_provisioned_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> WorkPassportStatusResponse:
    payload = body or PublishPassportRequest()
    result = publish_passport(db, user_id, headline=payload.headline, summary=payload.summary)
    refresh_search_projection(db, pipeline_db, str(user_id))
    return WorkPassportStatusResponse(**result)


@student_router.post(
    "/passport/unpublish",
    response_model=WorkPassportStatusResponse,
    summary="Hide the current user's public Work Passport",
)
def unpublish_passport_route(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> WorkPassportStatusResponse:
    result = unpublish_passport(db, user_id)
    # Unpublish must remove the candidate from recruiter discovery too.
    refresh_search_projection(db, pipeline_db, str(user_id))
    return WorkPassportStatusResponse(**result)


# ── Granular disclosure (Privacy & Sharing center) ───────────────────────────


def _disclosure_validation_http_error(exc: DisclosureValidationError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "disclosure_invalid",
            "field": exc.field,
            "message": exc.message,
        },
    )


@student_router.get(
    "/passport/disclosure",
    response_model=DisclosureContextResponse,
    summary="Get the current user's full Privacy & Sharing editor context",
)
def get_disclosure_context_route(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> DisclosureContextResponse:
    """Owner view of the hierarchical disclosure policy: per-project proof
    aspects, per-document view/download states, the skills tree, and the
    effective public-access summary — configured AND effective at every node.

    Pure read; retried once on a fresh client for a peer-closed keepalive
    connection, exactly like the passport endpoint it is issued alongside."""
    return DisclosureContextResponse(
        **run_with_transient_retry(
            db,
            lambda client: build_disclosure_context(client, pipeline_db, user_id),
            op="GET /student/vbr/passport/disclosure",
        )
    )


@student_router.put(
    "/passport/disclosure/mode",
    response_model=DisclosureContextResponse,
    summary="Switch the disclosure mode (recruiter_safe | custom)",
)
def set_disclosure_mode_route(
    body: DisclosureModeRequest,
    # First write for a brand-new account: the policy row FKs public.users(id).
    user_id: str = Depends(get_provisioned_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> DisclosureContextResponse:
    try:
        set_disclosure_mode(db, str(user_id), body.mode)
    except DisclosureValidationError as exc:
        raise _disclosure_validation_http_error(exc) from exc
    refresh_search_projection(db, pipeline_db, str(user_id))
    return DisclosureContextResponse(**build_disclosure_context(db, pipeline_db, user_id))


@student_router.put(
    "/passport/disclosure/overrides",
    response_model=DisclosureContextResponse,
    summary="Apply a batch of per-resource disclosure overrides",
)
def apply_disclosure_overrides_route(
    body: DisclosureOverridesRequest,
    user_id: str = Depends(get_provisioned_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> DisclosureContextResponse:
    """Batch upsert/clear (``visibility: null`` clears). Every change is
    validated against the closed vocabulary before any write; the whole batch
    shares one ``disclosure_version`` bump, and each change is audited."""
    try:
        apply_disclosure_overrides(
            db, str(user_id), [change.model_dump() for change in body.changes]
        )
    except DisclosureValidationError as exc:
        raise _disclosure_validation_http_error(exc) from exc
    refresh_search_projection(db, pipeline_db, str(user_id))
    return DisclosureContextResponse(**build_disclosure_context(db, pipeline_db, user_id))


@student_router.post(
    "/passport/disclosure/preset",
    response_model=DisclosureContextResponse,
    summary="Apply a safe disclosure preset",
)
def apply_disclosure_preset_route(
    body: DisclosurePresetRequest,
    user_id: str = Depends(get_provisioned_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> DisclosureContextResponse:
    """``recruiter_safe`` switches the mode back to the recommended defaults
    (stored overrides are kept but inactive). ``portfolio_open`` and
    ``maximum_privacy`` switch to custom mode and write the preset's override
    set over the CURRENT published projects."""
    preset = body.preset
    if preset not in PRESETS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "disclosure_invalid",
                "field": "preset",
                "message": f"Unknown preset: {preset!r}",
            },
        )
    if preset == "recruiter_safe":
        set_disclosure_mode(db, str(user_id), MODE_RECRUITER_SAFE)
    else:
        set_disclosure_mode(db, str(user_id), MODE_CUSTOM)
        context = build_disclosure_context(db, pipeline_db, user_id)
        changes = preset_changes(context, preset)
        if changes:
            apply_disclosure_overrides(db, str(user_id), changes)
    refresh_search_projection(db, pipeline_db, str(user_id))
    return DisclosureContextResponse(**build_disclosure_context(db, pipeline_db, user_id))


@student_router.post(
    "/passport/disclosure/reset",
    response_model=DisclosureContextResponse,
    summary="Clear every disclosure override (reset to recommended defaults)",
)
def reset_disclosure_route(
    user_id: str = Depends(get_provisioned_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> DisclosureContextResponse:
    clear_disclosure_overrides(db, str(user_id))
    refresh_search_projection(db, pipeline_db, str(user_id))
    return DisclosureContextResponse(**build_disclosure_context(db, pipeline_db, user_id))


@student_router.get(
    "/passport/profile",
    response_model=PassportProfileResponse,
    summary="Get the current user's Passport Profile (public identity editor)",
)
def get_passport_profile_route(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> PassportProfileResponse:
    """Owner view of the consented candidate identity shown on the public
    passport, plus best-effort prefill from existing account data."""
    return PassportProfileResponse(**get_editor_context(db, str(user_id)))


@student_router.put(
    "/passport/profile",
    response_model=PassportProfileResponse,
    summary="Update the current user's Passport Profile",
)
def update_passport_profile_route(
    body: PassportProfileUpsert,
    # First write for a brand-new account: passport_profiles.user_id FKs
    # public.users(id), so the caller's row must exist before the insert.
    user_id: str = Depends(get_provisioned_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> PassportProfileResponse:
    """PATCH-style upsert: only the provided fields change; explicit ``null``
    or empty clears a field. Field-level validation errors return 422."""
    updates = body.model_dump(exclude_unset=True)
    try:
        upsert_passport_profile(db, str(user_id), updates)
    except PassportProfileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "passport_profile_invalid",
                "field": exc.field,
                "message": exc.message,
            },
        ) from exc
    # Identity edits (name, headline, visibility toggles) feed recruiter
    # search — keep the projection in step with the live profile.
    refresh_search_projection(db, pipeline_db, str(user_id))
    return PassportProfileResponse(**get_editor_context(db, str(user_id)))


@student_router.put(
    "/passport/identity/photo",
    response_model=PassportPhotoResponse,
    summary="Upload / replace the current user's Passport Card profile photo",
)
async def set_passport_photo_route(
    file: UploadFile = File(...),
    # Upserts student_onboarding_profiles, which FKs public.users(id) — a fresh
    # account's first photo upload must provision that row first.
    user_id: str = Depends(get_provisioned_user_id),
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


@public_router.post(
    "/p/{public_slug}/view",
    response_model=PublicPassportViewAck,
    summary="Record a privacy-conscious view event for a published passport (no auth required)",
)
def record_public_passport_view_route(
    public_slug: str,
    request: Request,
    event: PublicPassportViewEvent | None = None,
    viewer_user_id: str | None = Depends(get_optional_user_id),
    db: Any = Depends(get_db),
) -> PublicPassportViewAck:
    """Best-effort view tracking; never an error surface.

    Mirrors the public report tracker: any slug that does not resolve to an
    actively published passport — and any persistence failure — returns the
    same content-free ``recorded: false`` ack, so this route can't be used as
    a slug oracle beyond what the public GET already reveals, and a broken
    analytics table can never break the passport page load. Authenticated
    viewers are attributed by user id; anonymous viewers stay anonymous.
    """
    from app.services.vbr_passport_view_service import (
        record_public_passport_view,
        resolve_published_passport_id,
    )

    logger = logging.getLogger(__name__)
    try:
        passport_id = resolve_published_passport_id(db, public_slug)
        if passport_id is None:
            return PublicPassportViewAck(recorded=False)
        recorded = record_public_passport_view(
            db,
            passport_id,
            source=event.source if event else None,
            dedupe_key=event.dedupe_key if event else None,
            referrer=request.headers.get("referer"),
            user_agent=request.headers.get("user-agent"),
            recruiter_user_id=viewer_user_id,
        )
        return PublicPassportViewAck(recorded=bool(recorded))
    except Exception:
        logger.warning("public passport view tracking failed", exc_info=True)
        return PublicPassportViewAck(recorded=False)
