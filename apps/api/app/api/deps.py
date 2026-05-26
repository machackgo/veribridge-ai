"""
FastAPI shared dependencies.

Override these in tests via ``app.dependency_overrides``:

    from app.api.deps import get_db, get_current_user_id
    app.dependency_overrides[get_db] = lambda: mock_supabase_client
    app.dependency_overrides[get_current_user_id] = lambda: "some-uuid"
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth import AuthTokenExpired, AuthTokenInvalid, extract_user_id
from app.core.config import settings
from app.db.supabase import get_supabase_client

# auto_error=False so we can inspect the token ourselves and return structured errors,
# and also allow the dev-mode fallback when no header is present at all.
_bearer = HTTPBearer(auto_error=False)


def get_db() -> Any:
    """
    Return the Supabase service-role client.

    Overridden in unit tests with a mock so no real network calls are made.
    """
    return get_supabase_client()


def get_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> str:
    """
    Resolve the authenticated user ID from the request.

    Priority:
      1. If an Authorization: Bearer <token> header is present, verify the
         Supabase HS256 JWT and return the ``sub`` claim.
      2. In non-production environments without a token, fall back to
         ``DEMO_USER_ID`` so curl/Swagger still works without a real session.
      3. In production with no token → 401.

    Raises HTTP 401 with a structured JSON body on any auth failure.
    """
    if credentials is not None:
        secret = settings.supabase_jwt_secret.get_secret_value()
        try:
            return extract_user_id(credentials.credentials, secret)
        except AuthTokenExpired:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "token_expired",
                    "message": "Your session has expired. Please sign in again.",
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
        except AuthTokenInvalid as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "invalid_token",
                    "message": str(exc),
                },
                headers={"WWW-Authenticate": "Bearer"},
            )

    # No token supplied.
    if settings.environment != "production" and settings.demo_user_id:
        return settings.demo_user_id

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "unauthorized",
            "message": "Authentication required. Provide a Bearer token.",
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_admin_user_id(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> str:
    """
    Require an authenticated VeriBridge admin user for internal admin routes.

    TODO: replace this role check with the final admin auth/claims model once
    production admin identity management is finalized.
    """
    role = None
    if isinstance(db, dict):
        role = (db.get("users", {}).get(user_id) or {}).get("role")
    else:
        result = db.table("users").select("role").eq("id", user_id).maybe_single().execute()
        data = getattr(result, "data", None) if result is not None else None
        role = (data or {}).get("role")
    if role not in {"admin", "university_admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "admin_required",
                "message": "Admin access is required.",
            },
        )
    return user_id
