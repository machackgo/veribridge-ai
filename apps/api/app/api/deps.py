"""
FastAPI shared dependencies.

Override these in tests via ``app.dependency_overrides``:

    from app.api.deps import get_db, get_current_user_id
    app.dependency_overrides[get_db] = lambda: mock_supabase_client
    app.dependency_overrides[get_current_user_id] = lambda: "some-uuid"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth import (
    AuthTokenExpired,
    AuthTokenInvalid,
    extract_user_id,
    verify_supabase_jwt,
)
from app.core.config import settings
from app.db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

# auto_error=False so we can inspect the token ourselves and return structured errors,
# and also allow the dev-mode fallback when no header is present at all.
_bearer = HTTPBearer(auto_error=False)

# ── Skill-pipeline dev store ──────────────────────────────────────────────────
# Process-lifetime in-memory store used in non-production when the
# skill_evidence_pipelines table has not yet been migrated (migration 047).
# The service already handles dict-mode; this store persists across browser
# refreshes for the same server process session.
_DEV_PIPELINE_STORE: dict[str, Any] = {}
_pipeline_table_checked: bool = False
_pipeline_use_dev_store: bool = False


def get_db() -> Any:
    """
    Return the Supabase service-role client.

    Overridden in unit tests with a mock so no real network calls are made.
    """
    return get_supabase_client()


def get_pipeline_db(
    db: Any = Depends(get_db),
) -> Any:
    """Return a DB client suitable for the skill-pipeline endpoints.

    Resolution order:
      1. If ``db`` is a plain dict (test override or explicit mock), return it as-is.
      2. In production, always return the real Supabase client.
      3. In non-production, check once whether ``skill_evidence_pipelines`` exists.
         If the table is missing (migration 047 not applied), return a module-level
         in-memory dict so that seed/list/PATCH all work without a real DB.
         The dict persists for the server process session (survives browser refreshes).
         Run ``python scripts/apply_pipeline_migration.py`` to switch to Supabase.
    """
    global _pipeline_table_checked, _pipeline_use_dev_store

    if isinstance(db, dict):
        return db  # test-mode dict or explicit override

    if settings.environment == "production":
        return db

    if not _pipeline_table_checked:
        _pipeline_table_checked = True
        try:
            db.table("skill_evidence_pipelines").select("id").limit(0).execute()
            _pipeline_use_dev_store = False
            logger.info("[dev] skill_evidence_pipelines table found in Supabase")
        except Exception as exc:
            msg = str(exc)
            if "PGRST205" in msg or "schema cache" in msg.lower():
                _pipeline_use_dev_store = True
                logger.warning(
                    "[dev] skill_evidence_pipelines table not found in Supabase schema cache. "
                    "Using in-memory store for this server session. "
                    "Run: cd apps/api && python scripts/apply_pipeline_migration.py"
                )
            else:
                logger.warning("[dev] Unexpected error checking pipeline table: %s", exc)
                _pipeline_use_dev_store = False

    return _DEV_PIPELINE_STORE if _pipeline_use_dev_store else db


def _demo_fallback_enabled() -> bool:
    """Whether the DEMO_USER_ID no-token fallback may apply for this request.

    SECURITY: this must be a hard, explicit opt-in. The demo user is a real,
    data-bearing account; letting an unauthenticated request resolve to it is a
    cross-tenant data leak. It is therefore only ever active in non-production
    when ``ENABLE_DEMO_USER_FALLBACK=true`` is set. It applies ONLY to requests
    with no Authorization header — a present-but-invalid/expired token always
    fails closed (401 / anonymous), never silently downgrades to the demo user.
    """
    return (
        settings.environment != "production"
        and settings.enable_demo_user_fallback
        and bool(settings.demo_user_id)
    )


def get_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> str:
    """
    Resolve the authenticated user ID from the request.

    Priority:
      1. If an Authorization: Bearer <token> header is present, verify the
         Supabase JWT — HS256 via SUPABASE_JWT_SECRET or ES256/RS256 via the
         project JWKS — and return the ``sub`` claim. A token that is
         expired, malformed, wrongly signed, or unverifiable (e.g. neither
         secret nor JWKS available) → 401. It is NEVER downgraded to
         the demo user — doing so would attribute a real user's request, or a
         stranger's, to one shared account.
      2. With NO token: only when the explicit dev demo fallback is enabled
         (see ``_demo_fallback_enabled``) return ``DEMO_USER_ID`` so curl /
         Swagger can poke the API without a session. Otherwise → 401.

    Raises HTTP 401 with a structured JSON body on any auth failure.
    """
    if credentials is not None:
        secret = settings.supabase_jwt_secret.get_secret_value()
        try:
            return extract_user_id(
                credentials.credentials, secret, settings.supabase_jwks_url
            )
        except AuthTokenExpired:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "token_expired",
                    "message": "Your session has expired. Please sign in again.",
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
        except AuthTokenInvalid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "invalid_token",
                    "message": "Invalid authentication token.",
                },
                headers={"WWW-Authenticate": "Bearer"},
            )

    # No token supplied.
    if _demo_fallback_enabled():
        return settings.demo_user_id

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "unauthorized",
            "message": "Authentication required. Provide a Bearer token.",
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


@dataclass(frozen=True)
class AuthenticatedUser:
    """The verified identity of the calling user.

    ``email`` is the JWT ``email`` claim when present (used to self-provision the
    caller's own ``public.users`` row on first write); it is ``None`` when the
    token omits it or for the no-token dev demo fallback.
    """

    id: str
    email: Optional[str] = None


def get_current_user_identity(
    user_id: str = Depends(get_current_user_id),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> AuthenticatedUser:
    """Resolve the caller's verified id AND (best-effort) email.

    Authentication — including all fail-closed 401s and the opt-in no-token demo
    fallback — is delegated entirely to :func:`get_current_user_id`, so this
    dependency inherits that audited behavior unchanged and honors any test
    override of it. The token's ``email`` claim is then read best-effort (the
    token was already verified by ``get_current_user_id``) so first-write
    endpoints can self-provision the caller's own ``public.users`` row. Email is
    ``None`` when no token is present (demo fallback) or it carries no email
    claim; it is never required for authorization.
    """
    email: Optional[str] = None
    if credentials is not None:
        secret = settings.supabase_jwt_secret.get_secret_value()
        try:
            payload = verify_supabase_jwt(
                credentials.credentials, secret, settings.supabase_jwks_url
            )
            claim = payload.get("email")
            email = str(claim) if claim else None
        except (AuthTokenExpired, AuthTokenInvalid):
            # Unreachable in practice (get_current_user_id already accepted the
            # token), but never let email extraction turn a valid request into
            # an error — the id is already authoritative.
            email = None
    return AuthenticatedUser(id=user_id, email=email)


def get_optional_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[str]:
    """Resolve the caller's user id when a valid token is present, else None.

    For endpoints that serve BOTH the owner (full private access) and anonymous
    public/recruiter surfaces (gated to public-safe artifacts only). An invalid
    or expired token degrades to anonymous instead of raising — the endpoint's
    own access policy then decides what an anonymous caller may see.

    Note: unlike ``get_current_user_id`` this never falls back to
    ``DEMO_USER_ID`` on a *present-but-invalid* token; the dev fallback applies
    only when no token is supplied at all AND the explicit demo fallback is
    enabled. Without that opt-in, no token → anonymous (``None``) — an
    unauthenticated caller must never be treated as the demo *owner*, or these
    dual owner/public endpoints would hand a stranger the owner's private view.

    Override in tests:
        app.dependency_overrides[get_optional_user_id] = lambda: None  # anonymous
    """
    if credentials is not None:
        secret = settings.supabase_jwt_secret.get_secret_value()
        try:
            return extract_user_id(
                credentials.credentials, secret, settings.supabase_jwks_url
            )
        except (AuthTokenExpired, AuthTokenInvalid):
            return None

    if _demo_fallback_enabled():
        return settings.demo_user_id

    return None


def require_recruiter_session(
    x_recruiter_token: Optional[str] = Header(None, alias="X-Recruiter-Token"),
    db: Any = Depends(get_db),
) -> str:
    """Validate a recruiter session token and return the ``requester_email``.

    Recruiters obtain a session token via ``POST /public/recruiter/sessions``.
    The token must be supplied as the ``X-Recruiter-Token`` request header on
    every private recruiter endpoint (list / update / delete saved passports,
    list / get / archive candidate comparisons).

    Raises HTTP 401 if the token is absent, unknown, expired, or revoked.

    Override in tests:
        from app.api.deps import require_recruiter_session
        app.dependency_overrides[require_recruiter_session] = lambda: "test@example.com"
    """
    if not x_recruiter_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "recruiter_session_required",
                "message": (
                    "A recruiter session token is required. "
                    "Obtain one via POST /api/v1/public/recruiter/sessions."
                ),
            },
        )
    from app.services.recruiter_session_service import RecruiterSessionService

    email = RecruiterSessionService(db).validate_token(x_recruiter_token)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "recruiter_session_invalid",
                "message": "Recruiter session token is invalid or expired.",
            },
        )
    return email


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
        from app.services.permission_service import PermissionService

        permission_service = PermissionService(db)
        if not permission_service.has_role(user_id, ["admin", "support", "reviewer"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "admin_required",
                    "message": "Admin access is required.",
                },
            )
    return user_id


def require_admin_or_university_admin_user_id(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> str:
    """
    Require a full admin or university_admin for high-sensitivity surfaces.

    Stricter than :func:`require_admin_user_id`: it deliberately does NOT admit
    ``support`` or ``reviewer`` grants. Candidate discovery (search/detail) dumps
    other students' private evidence, so it is limited to ``admin`` and
    ``university_admin`` only.
    """
    role = None
    if isinstance(db, dict):
        role = (db.get("users", {}).get(user_id) or {}).get("role")
    else:
        result = db.table("users").select("role").eq("id", user_id).maybe_single().execute()
        data = getattr(result, "data", None) if result is not None else None
        role = (data or {}).get("role")
    if role not in {"admin", "university_admin"}:
        from app.services.permission_service import PermissionService

        permission_service = PermissionService(db)
        if not permission_service.has_role(user_id, ["admin", "university_admin"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "admin_required",
                    "message": "Admin or university admin access is required.",
                },
            )
    return user_id
