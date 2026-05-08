"""
Student profile service.

Encapsulates all Supabase table operations for `student_profiles`.
The service accepts a Supabase client as a constructor argument so
that tests can inject a mock without touching the real database.

DB <-> API field mapping
------------------------
DB column              API field
---------------------  ------------------
school_name            university
work_authorization     visa_status
links->>'github_url'   github_url
links->>'linkedin_url' linkedin_url

Error contract
--------------
* Network/DNS failure  → ``SupabaseConnectionError`` → HTTP 503
* PostgREST API error  → ``SupabaseAPIError``          → HTTP 503 (with detail)
* FK / missing user    → ``SupabaseFKError``            → HTTP 409
* No profile found     → returns ``None``               → HTTP 404
* Programming errors   → propagate as-is               → HTTP 500 (JSON)

IMPORTANT — maybe_single() / execute() return type
---------------------------------------------------
``maybe_single().execute()`` returns:
  - ``None``                 when 0 rows match  (NOT an error)
  - ``SingleAPIResponse``    when exactly 1 row matches
  - raises ``APIError``      when >1 rows match

Always check ``if result is None`` — NOT ``if result.data is None`` —
because ``None.data`` raises ``AttributeError``.
"""

from __future__ import annotations

import logging
from typing import Any

from app.db.supabase import SupabaseAPIError, SupabaseConnectionError, SupabaseFKError
from app.schemas.student import StudentProfileResponse, StudentProfileUpsert

logger = logging.getLogger(__name__)

_TABLE = "student_profiles"
_USERS_TABLE = "users"

# These strings appear in PostgREST error messages for FK violations.
_FK_CODES = {"23503"}          # foreign_key_violation
_FK_HINTS = ("users",)         # table name mentioned in FK hint


class StudentProfileService:
    """CRUD operations for student_profiles via the Supabase client."""

    def __init__(self, client: Any) -> None:
        self._client = client

    # ── Read ──────────────────────────────────────────────────────

    def get_profile(self, user_id: str) -> StudentProfileResponse | None:
        """
        Return the profile for ``user_id``, or ``None`` if it does not exist.

        ``maybe_single().execute()`` returns ``None`` (not an error object)
        when 0 rows match.  We must check ``if result is None``, not
        ``if result.data is None``, because the latter raises AttributeError.
        """
        try:
            result = (
                self._client
                .table(_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            raise _classify(exc, "GET", _TABLE) from exc

        # maybe_single().execute() returns None when the query finds 0 rows.
        if result is None:
            return None

        return self._to_response(result.data)

    # ── Write ─────────────────────────────────────────────────────

    def upsert_profile(
        self,
        user_id: str,
        data: StudentProfileUpsert,
    ) -> StudentProfileResponse:
        """
        Insert or update the profile for ``user_id``.

        Raises ``SupabaseFKError`` if the user row does not exist in
        ``public.users`` (foreign-key constraint).  Call
        ``ensure_user_exists()`` first to avoid this.
        """
        payload = self._to_db_payload(user_id, data)
        try:
            result = (
                self._client
                .table(_TABLE)
                .upsert(payload, on_conflict="user_id")
                .execute()
            )
        except Exception as exc:
            raise _classify(exc, "UPSERT", _TABLE) from exc

        rows = result.data
        if not rows:
            raise RuntimeError(
                "Supabase upsert returned no data. "
                "Check RLS policies and that the service-role key is in use."
            )
        return self._to_response(rows[0])

    # ── Demo-user bootstrap ───────────────────────────────────────

    def ensure_user_exists(
        self,
        user_id: str,
        email: str = "demo@veribridge.local",
        role: str = "student",
    ) -> bool:
        """
        Upsert a minimal row in ``public.users`` for development use.

        Returns True if the row was newly created, False if it already existed.
        This is a no-op if the user already exists.
        """
        try:
            before = (
                self._client
                .table(_USERS_TABLE)
                .select("id")
                .eq("id", user_id)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            raise _classify(exc, "GET", _USERS_TABLE) from exc

        if before is not None:
            return False  # already exists

        try:
            self._client.table(_USERS_TABLE).insert(
                {"id": user_id, "email": email, "role": role, "status": "active"}
            ).execute()
        except Exception as exc:
            raise _classify(exc, "INSERT", _USERS_TABLE) from exc

        return True

    # ── Private helpers ───────────────────────────────────────────

    @staticmethod
    def _to_db_payload(user_id: str, data: StudentProfileUpsert) -> dict[str, Any]:
        return {
            "user_id": user_id,
            "full_name": data.full_name,
            "school_name": data.university,          # university → school_name
            "degree": data.degree,
            "major": data.major,
            "graduation_year": data.graduation_year,
            "work_authorization": data.visa_status,  # visa_status → work_authorization
            "target_roles": data.target_roles,
            "target_locations": data.target_locations,
            "links": {
                "github_url": data.github_url,
                "linkedin_url": data.linkedin_url,
            },
        }

    @staticmethod
    def _to_response(row: dict[str, Any]) -> StudentProfileResponse:
        links: dict[str, Any] = row.get("links") or {}
        return StudentProfileResponse(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            full_name=row.get("full_name") or "",
            university=row.get("school_name") or "",       # school_name → university
            degree=row.get("degree") or "",
            major=row.get("major") or "",
            graduation_year=row.get("graduation_year"),
            visa_status=row.get("work_authorization"),     # work_authorization → visa_status
            target_roles=row.get("target_roles") or [],
            target_locations=row.get("target_locations") or [],
            github_url=links.get("github_url"),
            linkedin_url=links.get("linkedin_url"),
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
        )


# ── Exception classifier ──────────────────────────────────────────────────────

def _classify(exc: Exception, op: str, table: str) -> Exception:
    """
    Convert a raw Supabase/httpx exception to a typed service exception.

    This runs outside the try block so we log only the class name and
    a sanitised message — never a full traceback with credentials.
    """
    exc_name = type(exc).__name__
    exc_str = str(exc)

    # Foreign-key violation from PostgREST (code 23503)
    if _is_fk_error(exc_str):
        logger.warning(
            "Supabase %s %s: foreign-key violation (%s)", op, table, exc_name
        )
        return SupabaseFKError(
            f"{op} {table} failed: a required parent row is missing "
            f"(foreign-key constraint). Run POST /api/v1/debug/bootstrap-demo-user "
            f"to create the demo user, then retry."
        )

    # Network-level failure (DNS, connection refused, timeout)
    if _is_network_error(exc, exc_str):
        logger.error(
            "Supabase %s %s: network error (%s)", op, table, exc_name
        )
        return SupabaseConnectionError(
            f"{op} {table} failed: network error ({exc_name}). "
            "Check SUPABASE_URL and confirm the project is not paused."
        )

    # PostgREST returned a non-2xx response (permission denied, bad query, …)
    logger.error(
        "Supabase %s %s: API error (%s): %.200s", op, table, exc_name, exc_str
    )
    return SupabaseAPIError(
        f"{op} {table} failed: Supabase returned an error ({exc_name}). "
        "Check server logs for details."
    )


def _is_fk_error(msg: str) -> bool:
    low = msg.lower()
    return "23503" in msg or (
        "foreign" in low and "key" in low
    ) or "violates foreign key" in low


def _is_network_error(exc: Exception, msg: str) -> bool:
    exc_name = type(exc).__name__
    network_types = {
        "ConnectError", "ConnectTimeout", "ReadTimeout", "RemoteProtocolError",
        "ConnectionError", "TimeoutError", "OSError", "gaierror",
    }
    if exc_name in network_types:
        return True
    low = msg.lower()
    return any(phrase in low for phrase in (
        "nodename nor servname",
        "name or service not known",
        "connection refused",
        "timed out",
        "errno 8",
        "errno 111",
    ))
