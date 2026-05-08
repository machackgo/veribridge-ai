"""
Development-only debug endpoints.

GET  /api/v1/debug/config
    Returns a safe config summary — shows URL host and key presence,
    never key values.  Returns 403 in production.

POST /api/v1/debug/bootstrap-demo-user
    Creates the demo user row in public.users if it does not exist.
    Required before PUT /api/v1/student/profile works in development,
    because student_profiles.user_id has a FK to users.id.
    Returns 403 in production.

Both endpoints are disabled (return 403) when ENVIRONMENT=production.
"""

from __future__ import annotations

from urllib.parse import urlparse
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.core.config import settings
from app.db.supabase import SupabaseError
from app.services.student_service import StudentProfileService

router = APIRouter()


def _block_in_production() -> None:
    if settings.environment == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Debug endpoints are disabled in production.",
        )


# ── GET /debug/config ─────────────────────────────────────────────────────────


@router.get(
    "/config",
    summary="Safe config status (dev only)",
)
def debug_config() -> dict[str, Any]:
    """
    Shows which environment variables are loaded and whether Supabase
    is configured correctly.

    Shows: URL host, key presence (boolean), DEMO_USER_ID, hints.
    Never shows: key values, secrets, DATABASE_URL contents.
    """
    _block_in_production()

    url = settings.supabase_url
    parsed = urlparse(url) if url else None
    host = parsed.netloc if parsed else ""

    url_valid = bool(
        parsed
        and parsed.scheme == "https"
        and host.endswith(".supabase.co")
        and not host.startswith("db.")
    )

    service_key_ok = bool(settings.supabase_service_role_key.get_secret_value())
    anon_key_ok = bool(settings.supabase_anon_key.get_secret_value())

    hint: str | None = None
    if url and not url_valid:
        if url.startswith(("postgresql", "postgres")):
            hint = (
                "SUPABASE_URL looks like a Postgres connection string. "
                "Use the REST URL: https://yourref.supabase.co"
            )
        elif host.startswith("db."):
            hint = f"Remove 'db.' prefix. Change to: https://{host[3:]}"
        elif parsed and parsed.scheme != "https":
            hint = "Add 'https://' prefix to SUPABASE_URL."
        else:
            hint = "SUPABASE_URL host must end with '.supabase.co'."
    elif url_valid and not service_key_ok:
        hint = "SUPABASE_SERVICE_ROLE_KEY is missing."
    elif not url:
        hint = "SUPABASE_URL is missing."

    jwt_secret_ok = settings.auth_configured

    if hint is None and not jwt_secret_ok:
        hint = (
            "SUPABASE_JWT_SECRET is missing. "
            "JWT auth will not work — dev fallback (DEMO_USER_ID) is active. "
            "Find it at: Supabase dashboard → Settings → API → JWT Settings → JWT Secret."
        )

    return {
        "environment": settings.environment,
        "supabase": {
            "url_present": bool(url),
            "url_host": host or None,
            "url_scheme": parsed.scheme if parsed else None,
            "url_valid_format": url_valid,
            "service_role_key_present": service_key_ok,
            "anon_key_present": anon_key_ok,
            "configured": settings.supabase_configured,
        },
        "auth": {
            "jwt_secret_present": jwt_secret_ok,
            "mode": "jwt" if jwt_secret_ok else "demo_fallback",
            "demo_user_id": settings.demo_user_id if not jwt_secret_ok else None,
        },
        "hint": hint,
    }


# ── POST /debug/bootstrap-demo-user ──────────────────────────────────────────


@router.post(
    "/bootstrap-demo-user",
    status_code=status.HTTP_200_OK,
    summary="Create demo user row in public.users (dev only)",
)
def bootstrap_demo_user(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> dict[str, Any]:
    """
    Creates the demo user row in ``public.users`` if it does not exist.

    This is required before ``PUT /api/v1/student/profile`` will work,
    because ``student_profiles.user_id`` has a foreign-key constraint
    pointing to ``users.id``.

    In development, this is safe to call multiple times — it is idempotent.
    Returns 403 in production.
    """
    _block_in_production()

    service = StudentProfileService(db)

    try:
        created = service.ensure_user_exists(
            user_id=user_id,
            email="demo@veribridge.local",
            role="student",
        )
    except SupabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "bootstrap_failed",
                "message": str(exc),
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "internal_error",
                "message": f"Unexpected error: {type(exc).__name__}",
            },
        ) from exc

    return {
        "user_id": user_id,
        "created": created,
        "message": (
            "Demo user created in public.users."
            if created
            else "Demo user already exists in public.users."
        ),
        "next_step": "You can now call PUT /api/v1/student/profile.",
    }
