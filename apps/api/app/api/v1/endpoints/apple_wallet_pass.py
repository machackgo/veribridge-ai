"""Apple Wallet Passport Pass endpoints — owner-only, feature-flag gated.

  ``GET /api/v1/student/vbr/wallet/apple/availability``  — readiness booleans
  ``GET /api/v1/student/vbr/wallet/apple/pass-json``     — dev/test field-mapping preview
  ``GET /api/v1/student/vbr/wallet/apple/pass.pkpass``   — REAL signed pass (gated)

All three require owner auth (the user id always comes from the token). The
pass QR is the caller's existing revocable Beam short link (``/b/{code}``) —
created/reused exactly like the Beam Card does, so rotating/revoking the link
disables the QR inside every previously added Wallet pass at scan time.

Honesty gates:
 - ``pass.pkpass`` with the feature flag off → 404 ``apple_wallet_not_enabled``;
   with certificates missing → 503 ``apple_wallet_not_configured``. It never
   returns an unsigned bundle pretending to be a Wallet pass.
 - ``pass-json`` is a development aid: it serves the certificate-free field
   mapping only when the feature flag is on OR the server is not production.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.core.config import settings
from app.schemas.apple_wallet import AppleWalletAvailabilityResponse
from app.services.apple_wallet_pass_service import (
    PKPASS_MEDIA_TYPE,
    apple_wallet_availability,
    build_apple_pass_json,
    build_signed_pkpass,
    signing_files_present,
)

router = APIRouter()


def _require_pass_preview_allowed() -> None:
    """Gate for the dev pass.json preview: feature flag on OR non-production.

    Declared as a dependency BEFORE the db dependencies so a disabled
    production server answers the honest 404 without ever touching the DB.
    """
    if not settings.apple_wallet_enabled and settings.environment.strip().lower() == "production":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "apple_wallet_not_enabled",
                "message": "Apple Wallet passes are not enabled on this server.",
            },
        )


def _require_pkpass_configured() -> None:
    """Config gates for the signed pass, mirrored from the service (which keeps
    its own checks as defence in depth). Running them as a dependency BEFORE
    the db dependencies means flag-off / cert-missing servers answer their
    honest 404/503 even when the database itself is unreachable."""
    if not settings.apple_wallet_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "apple_wallet_not_enabled",
                "message": "Apple Wallet passes are not enabled on this server.",
            },
        )
    if not settings.apple_wallet_identifiers_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "apple_wallet_not_configured",
                "message": (
                    "Apple Wallet is enabled but APPLE_PASS_TYPE_IDENTIFIER / "
                    "APPLE_TEAM_IDENTIFIER are not set."
                ),
            },
        )
    if not signing_files_present():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "apple_wallet_not_configured",
                "message": (
                    "Apple Wallet is enabled but the signing certificate, "
                    "private key, or WWDR certificate file is missing."
                ),
            },
        )


@router.get(
    "/availability",
    response_model=AppleWalletAvailabilityResponse,
    summary="Whether this server can issue a real signed Apple Wallet pass",
)
def apple_wallet_availability_route(
    user_id: str = Depends(get_current_user_id),
) -> AppleWalletAvailabilityResponse:
    return AppleWalletAvailabilityResponse(**apple_wallet_availability())


@router.get(
    "/pass-json",
    summary="Dev/test preview of the Wallet pass.json field mapping (no signing)",
)
def apple_wallet_pass_json_route(
    user_id: str = Depends(get_current_user_id),
    _gate: None = Depends(_require_pass_preview_allowed),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> dict[str, Any]:
    """Certificate-free preview so the mapping can be verified before any Apple
    Developer material exists. Only served when the wallet feature flag is on
    OR the environment is non-production — production keeps it dark unless the
    feature is intentionally live."""
    return build_apple_pass_json(db, pipeline_db, user_id)


@router.get(
    "/pass.pkpass",
    summary="Download the signed Apple Wallet Work Passport pass (feature-gated)",
)
def apple_wallet_pkpass_route(
    user_id: str = Depends(get_current_user_id),
    _gate: None = Depends(_require_pkpass_configured),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> Response:
    pkpass_bytes = build_signed_pkpass(db, pipeline_db, user_id)
    return Response(
        content=pkpass_bytes,
        media_type=PKPASS_MEDIA_TYPE,
        headers={
            "Content-Disposition": 'attachment; filename="veribridge-work-passport.pkpass"',
            # A pass carries personal (public-safe) identity — never cache it
            # on shared infrastructure.
            "Cache-Control": "no-store",
        },
    )
