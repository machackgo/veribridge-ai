"""Beam Link endpoints — the dynamic revocable short QR for the Beam Card.

Owner-only (auth required; the link's ``user_id`` always comes from the token,
never the request):
  ``POST /api/v1/student/vbr/beam/links``                    — create / reuse the active link
  ``POST /api/v1/student/vbr/beam/links/{link_id}/rotate``   — revoke old code, mint a new one
  ``POST /api/v1/student/vbr/beam/links/{link_id}/revoke``   — kill the link

Public (no auth — the ONLY public read path for beam codes):
  ``GET  /api/v1/public/beam/{code}``                        — resolve a scanned code

The public resolver is the single authority on where a scanned QR goes. The web
app's ``/b/{code}`` route calls it and 30x-redirects to the returned public
Passport path; every invalid/revoked/expired/unpublished-target code gets the
same generic 404 (``beam_link_inactive``) with zero holder data.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_current_user_id, get_db
from app.schemas.beam_link import (
    BeamLinkResponse,
    BeamResolveResponse,
    CreateBeamLinkRequest,
)
from app.services.beam_link_service import (
    create_or_reuse_beam_link,
    resolve_beam_code,
    revoke_beam_link,
    rotate_beam_link,
)

student_router = APIRouter()
public_router = APIRouter()


@student_router.post(
    "/links",
    response_model=BeamLinkResponse,
    summary="Create (or reuse) the current user's active Beam short link",
)
def create_beam_link_route(
    body: CreateBeamLinkRequest | None = None,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> BeamLinkResponse:
    payload = body or CreateBeamLinkRequest()
    return BeamLinkResponse(**create_or_reuse_beam_link(db, user_id, event_tag=payload.event_tag))


@student_router.post(
    "/links/{link_id}/rotate",
    response_model=BeamLinkResponse,
    summary="Rotate a Beam link: the old code stops resolving, a new code is minted",
)
def rotate_beam_link_route(
    link_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> BeamLinkResponse:
    return BeamLinkResponse(**rotate_beam_link(db, user_id, link_id))


@student_router.post(
    "/links/{link_id}/revoke",
    response_model=BeamLinkResponse,
    summary="Revoke a Beam link: every shared copy of the QR goes inactive",
)
def revoke_beam_link_route(
    link_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> BeamLinkResponse:
    return BeamLinkResponse(**revoke_beam_link(db, user_id, link_id))


@public_router.get(
    "/{code}",
    response_model=BeamResolveResponse,
    summary="Resolve a scanned Beam code to the live public Passport path (no auth)",
)
def resolve_beam_code_route(
    code: str,
    request: Request,
    db: Any = Depends(get_db),
) -> BeamResolveResponse:
    """Scan-time resolution. Logs one coarse ``opened`` event (user-agent CLASS
    and referrer HOST only — never raw IPs or full user agents)."""
    result = resolve_beam_code(
        db,
        code,
        user_agent=request.headers.get("user-agent"),
        referrer=request.headers.get("referer"),
    )
    return BeamResolveResponse(**result)
