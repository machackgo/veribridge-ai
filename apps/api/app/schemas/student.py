"""
Pydantic schemas for the Student Profile API.

API field names differ from DB column names in a few places:
  API               DB (student_profiles table)
  -----------       ---------------------------
  university        school_name
  visa_status       work_authorization
  github_url        links->>'github_url'  (jsonb)
  linkedin_url      links->>'linkedin_url' (jsonb)

The service layer performs this mapping so the router stays thin.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


# ── Request (PUT body) ────────────────────────────────────────


class StudentProfileUpsert(BaseModel):
    """Fields accepted when creating or updating a student profile."""

    full_name: str = Field(..., min_length=1, max_length=255)
    university: str = Field(..., min_length=1, max_length=255)
    degree: str = Field(..., min_length=1, max_length=255)
    major: str = Field(..., min_length=1, max_length=255)

    graduation_year: int | None = Field(
        default=None,
        ge=1900,
        le=2100,
        description="Expected graduation year, e.g. 2026.",
    )
    visa_status: str | None = Field(
        default=None,
        max_length=100,
        description="Work authorisation status, e.g. 'F-1', 'OPT', 'US Citizen'.",
    )
    target_roles: list[str] = Field(
        default_factory=list,
        description="Desired job titles or role families.",
    )
    target_locations: list[str] = Field(
        default_factory=list,
        description="Preferred job locations.",
    )
    github_url: str | None = Field(
        default=None,
        max_length=500,
        description="GitHub profile URL.",
    )
    linkedin_url: str | None = Field(
        default=None,
        max_length=500,
        description="LinkedIn profile URL.",
    )

    @field_validator("target_roles", "target_locations", mode="before")
    @classmethod
    def _coerce_list(cls, v: object) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(item).strip() for item in v if str(item).strip()]
        return []

    @field_validator("github_url", "linkedin_url", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v: object) -> str | None:
        if isinstance(v, str) and not v.strip():
            return None
        return v  # type: ignore[return-value]


# ── Response ──────────────────────────────────────────────────


class StudentProfileResponse(BaseModel):
    """Shape returned for every student profile read or write."""

    id: str
    user_id: str

    full_name: str
    university: str
    degree: str
    major: str

    graduation_year: int | None
    visa_status: str | None

    target_roles: list[str]
    target_locations: list[str]

    github_url: str | None
    linkedin_url: str | None

    created_at: str
    updated_at: str
