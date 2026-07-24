"""Safe access routes for retained proof artifacts (migration 056).

Routes (mounted under ``/api/v1/proofs``):

  GET /artifacts/{artifact_id}/view        — stream bytes inline (gated)
  GET /artifacts/{artifact_id}/download    — stream bytes as attachment (gated)
  GET /artifacts/{artifact_id}/signed-url  — short-lived signed URL (gated)
  GET /website/{proof_id}/replay           — stream the retained website
                                             walkthrough replay video, when one
                                             was captured and retained

Access model (enforced in ``proof_artifact_service.can_access_artifact``):
  • owner → full access to their retained artifacts
  • privileged non-owner (recruiter / admin / reviewer) → ``recruiter_safe`` /
    ``public_safe``
  • plain authenticated non-owner (another student) → only ``public_safe``
    (treated like anonymous, so one student can never pull another student's
    recruiter-safe media by guessing its id)
  • anonymous → only ``public_safe``
  • unknown / not-retained / denied → the SAME indistinct 404, so a caller
    can never probe which private artifacts exist

Privacy: raw storage paths and buckets never appear in any response — bytes
are downloaded server-side and streamed; signed URLs are minted short-lived
(≤ 5 minutes) and only for callers the policy already admits.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.deps import get_db, get_optional_user_id
from app.services import proof_artifact_service as artifacts
from app.services.passport_disclosure import artifact_action_allowed
from app.services.permission_service import PermissionService

logger = logging.getLogger(__name__)
router = APIRouter()

# Roles allowed to view another user's ``recruiter_safe`` artifacts. A plain
# ``student`` (or the default student fallback) is deliberately excluded.
_PRIVILEGED_ARTIFACT_ROLES = frozenset(
    {"recruiter", "admin", "support", "reviewer", "faculty_reviewer", "company_reviewer"}
)

_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail={
        "code": "artifact_not_available",
        "message": "This artifact does not exist or is not available to you.",
    },
)


def _caller_is_privileged(db: Any, caller_user_id: str | None) -> bool:
    """True when the caller holds a recruiter/admin/reviewer role (never a plain student)."""
    if caller_user_id is None:
        return False
    try:
        return PermissionService(db).has_role(caller_user_id, _PRIVILEGED_ARTIFACT_ROLES)
    except Exception:  # pragma: no cover - fail closed on any role-lookup issue
        return False


def _get_gated_artifact(
    db: Any,
    artifact_id: str,
    caller_user_id: str | None,
    *,
    caller_is_privileged: bool = False,
    action: str = "view",
) -> dict[str, Any]:
    """Fetch + gate through the canonical disclosure-aware access decision.

    ``artifact_action_allowed`` composes the migration-056 retention policy
    with the migration-063 granular disclosure policy (owner always allowed;
    custom-mode disclosure authoritative for anonymous callers; download a
    separate grant from view). Denials stay the same indistinct 404.
    """
    artifact = artifacts.get_artifact(db, artifact_id)
    if artifact is None or not artifact_action_allowed(
        db,
        artifact,
        caller_user_id,
        caller_is_privileged=caller_is_privileged,
        action=action,
    ):
        raise _NOT_FOUND
    return artifact


def _stream(db: Any, artifact: dict[str, Any], *, as_attachment: bool) -> Response:
    data = artifacts.fetch_artifact_bytes(db, artifact)
    if data is None:
        # Registered but bytes unavailable (storage outage / misconfig) —
        # honest 404, never a broken placeholder.
        raise _NOT_FOUND
    headers: dict[str, str] = {}
    file_name = str(artifact.get("file_name") or "artifact")
    if as_attachment:
        headers["Content-Disposition"] = f'attachment; filename="{file_name}"'
    else:
        headers["Content-Disposition"] = f'inline; filename="{file_name}"'
    return Response(
        content=data,
        media_type=str(artifact.get("mime_type") or "application/octet-stream"),
        headers=headers,
    )


@router.get(
    "/artifacts/{artifact_id}/view",
    summary="Stream a retained proof artifact inline (access-gated)",
    response_class=Response,
    responses={
        200: {"description": "Artifact bytes"},
        404: {"description": "Unknown, not retained, or not available to this caller"},
    },
)
def view_artifact(
    artifact_id: str,
    user_id: str | None = Depends(get_optional_user_id),
    db: Any = Depends(get_db),
) -> Response:
    artifact = _get_gated_artifact(
        db, artifact_id, user_id, caller_is_privileged=_caller_is_privileged(db, user_id)
    )
    return _stream(db, artifact, as_attachment=False)


@router.get(
    "/artifacts/{artifact_id}/download",
    summary="Download a retained proof artifact (access-gated)",
    response_class=Response,
    responses={
        200: {"description": "Artifact bytes as attachment"},
        404: {"description": "Unknown, not retained, or not available to this caller"},
    },
)
def download_artifact(
    artifact_id: str,
    user_id: str | None = Depends(get_optional_user_id),
    db: Any = Depends(get_db),
) -> Response:
    artifact = _get_gated_artifact(
        db,
        artifact_id,
        user_id,
        caller_is_privileged=_caller_is_privileged(db, user_id),
        action="download",
    )
    return _stream(db, artifact, as_attachment=True)


class SignedUrlResponse(BaseModel):
    """Short-lived signed access to one artifact. Never a raw storage path."""

    artifact_id: str
    signed_url: str
    expires_in_seconds: int


@router.get(
    "/artifacts/{artifact_id}/signed-url",
    response_model=SignedUrlResponse,
    summary="Mint a short-lived signed URL for a retained artifact (access-gated)",
)
def artifact_signed_url(
    artifact_id: str,
    expires_in: int = Query(
        default=artifacts.SIGNED_URL_DEFAULT_TTL_S,
        ge=1,
        le=artifacts.SIGNED_URL_MAX_TTL_S,
        description="TTL in seconds (capped at 300).",
    ),
    user_id: str | None = Depends(get_optional_user_id),
    db: Any = Depends(get_db),
) -> SignedUrlResponse:
    artifact = _get_gated_artifact(
        db, artifact_id, user_id, caller_is_privileged=_caller_is_privileged(db, user_id)
    )
    url, ttl = artifacts.create_short_lived_signed_url(db, artifact, expires_in)
    if not url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "signed_url_unavailable",
                "message": "Signed access is not available right now.",
            },
        )
    return SignedUrlResponse(artifact_id=artifact_id, signed_url=url, expires_in_seconds=ttl)


@router.get(
    "/website/{proof_id}/replay",
    summary="Stream the retained website walkthrough replay video for a Website Proof",
    response_class=Response,
    responses={
        200: {"content": {"video/webm": {}, "video/mp4": {}}},
        404: {"description": "No replay video was retained for this proof, or not available"},
    },
)
def website_replay(
    proof_id: str,
    user_id: str | None = Depends(get_optional_user_id),
    db: Any = Depends(get_db),
) -> Response:
    """Honest replay access: serves ONLY a genuinely retained
    ``website_replay_video`` artifact for this website proof session. Website
    Proof capture does not retain walkthrough video for older sessions — those
    return 404 and the report says "frames/summary only" instead."""
    rows = artifacts.list_artifacts_for_proof(
        db, proof_type="website", proof_id=proof_id, artifact_type="website_replay_video"
    )
    privileged = _caller_is_privileged(db, user_id)
    accessible = [
        r
        for r in rows
        if artifact_action_allowed(
            db, r, user_id, caller_is_privileged=privileged, action="view"
        )
    ]
    if not accessible:
        raise _NOT_FOUND
    return _stream(db, accessible[-1], as_attachment=False)
