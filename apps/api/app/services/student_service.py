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
"""

from __future__ import annotations

import logging
from typing import Any

from app.schemas.student import StudentProfileResponse, StudentProfileUpsert

logger = logging.getLogger(__name__)

# Supabase table name
_TABLE = "student_profiles"


class StudentProfileService:
    """CRUD operations for student_profiles via the Supabase client."""

    def __init__(self, client: Any) -> None:
        # `client` is a supabase.Client in production and a MagicMock in tests.
        self._client = client

    # ── Read ──────────────────────────────────────────────────────

    def get_profile(self, user_id: str) -> StudentProfileResponse | None:
        """
        Return the profile for `user_id`, or None if it does not exist.

        Uses `maybe_single()` so the call returns None (not an error)
        when no row is found.
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
            logger.error("Supabase GET student_profiles failed: %s", exc)
            raise

        if result.data is None:
            return None

        return self._to_response(result.data)

    # ── Write ─────────────────────────────────────────────────────

    def upsert_profile(
        self,
        user_id: str,
        data: StudentProfileUpsert,
    ) -> StudentProfileResponse:
        """
        Insert or update the profile for `user_id`.

        Uses Supabase upsert with `on_conflict="user_id"` so repeated
        PUTs are idempotent.  Returns the persisted row.
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
            logger.error("Supabase UPSERT student_profiles failed: %s", exc)
            raise

        rows = result.data
        if not rows:
            raise RuntimeError(
                "Supabase upsert returned no data — check RLS policies "
                "and that the service-role key is in use."
            )

        return self._to_response(rows[0])

    # ── Private helpers ───────────────────────────────────────────

    @staticmethod
    def _to_db_payload(user_id: str, data: StudentProfileUpsert) -> dict[str, Any]:
        """Map API schema fields to database column names."""
        return {
            "user_id": user_id,
            "full_name": data.full_name,
            "school_name": data.university,       # API: university → DB: school_name
            "degree": data.degree,
            "major": data.major,
            "graduation_year": data.graduation_year,
            "work_authorization": data.visa_status,  # API: visa_status → DB: work_authorization
            "target_roles": data.target_roles,
            "target_locations": data.target_locations,
            "links": {
                "github_url": data.github_url,
                "linkedin_url": data.linkedin_url,
            },
        }

    @staticmethod
    def _to_response(row: dict[str, Any]) -> StudentProfileResponse:
        """Map a database row dict to the API response schema."""
        links: dict[str, Any] = row.get("links") or {}
        return StudentProfileResponse(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            full_name=row.get("full_name") or "",
            university=row.get("school_name") or "",     # DB: school_name → API: university
            degree=row.get("degree") or "",
            major=row.get("major") or "",
            graduation_year=row.get("graduation_year"),
            visa_status=row.get("work_authorization"),   # DB: work_authorization → API: visa_status
            target_roles=row.get("target_roles") or [],
            target_locations=row.get("target_locations") or [],
            github_url=links.get("github_url"),
            linkedin_url=links.get("linkedin_url"),
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
        )
