"""Recruiter-safe keyframe thumbnail proxy.

Endpoint:
  GET /api/v1/proof/frame-thumbnail/{frame_id}

Access rules:
  • Authenticated caller who owns the frame (student verifying their own evidence)
    → always allowed.
  • Authenticated caller who does NOT own the frame (recruiter viewing a candidate)
    → allowed only when a keyframe/screenshot/visual_frame artifact linked to this
      frame's proof_session_id has visibility = 'public' or 'approved'.
      A public/approved artifact of a different source_type (workflow, github,
      document) in the same proof session does NOT grant access.
  • If no matching keyframe-type artifact is found, deny by default.
  • All other cases → 403.

Privacy:
  • The raw frame_thumbnail_storage_path is NEVER returned.
  • Supabase Storage bytes are fetched server-side and streamed to the caller.
  • No signed URL or storage path appears in any response.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from app.api.deps import get_current_user_id, get_db
from app.core.config import settings
from app.services.keyframe_storage_service import KeyframeStorageService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/frame-thumbnail/{frame_id}",
    summary="Recruiter-safe keyframe thumbnail proxy",
    description=(
        "Returns a JPEG thumbnail for the given frame_id. "
        "Access is allowed when the caller owns the frame, OR when the frame's "
        "associated keyframe/screenshot/visual_frame artifact has visibility='public' "
        "or 'approved'. Unrelated public artifacts in the same session do not grant "
        "access. Raw storage paths are never exposed."
    ),
    response_class=Response,
    responses={
        200: {"content": {"image/jpeg": {}}},
        403: {"description": "Thumbnail not available or access denied"},
        404: {"description": "No thumbnail stored for this frame"},
        503: {"description": "Storage not configured"},
    },
)
def get_frame_thumbnail(
    frame_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> Response:
    bucket = settings.supabase_frame_evidence_bucket
    if not bucket:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Frame thumbnail storage is not configured.",
        )

    svc = KeyframeStorageService()
    thumbnail_bytes = svc.get_thumbnail_bytes_if_visible(
        db=db,
        frame_id=frame_id,
        bucket=bucket,
        caller_user_id=user_id,
    )

    if thumbnail_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Thumbnail not available for this frame.",
        )

    return Response(content=thumbnail_bytes, media_type="image/jpeg")
