"""Passport Profile schemas — the consented candidate identity behind the
public Verified Work Passport (migration 062, ``public.passport_profiles``).

Every field is student-authored and optional. The public surface omits empty
fields — it never invents or placeholders identity data. Publish-sensitive
fields carry explicit visibility toggles; work authorization is opt-in only.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# Closed availability vocabulary (stored value → recruiter-facing label lives
# in the service). Empty string / None means "don't show availability".
AVAILABILITY_VALUES = (
    "seeking_internship",
    "seeking_full_time",
    "open_to_opportunities",
)


class PassportProfileData(BaseModel):
    """A student's passport profile as stored (owner view)."""

    full_name: str | None = None
    preferred_name: str | None = None
    pronunciation: str | None = None
    headline: str | None = None
    bio: str | None = None

    institution: str | None = None
    degree: str | None = None
    graduation_year: int | None = None
    location: str | None = None

    github_url: str | None = None
    linkedin_url: str | None = None
    portfolio_url: str | None = None

    role_areas: list[str] = Field(default_factory=list)
    availability: str | None = None
    work_authorization_note: str | None = None

    show_location: bool = True
    show_availability: bool = True
    show_links: bool = True
    show_work_authorization: bool = False

    updated_at: str | None = None

    model_config = {"extra": "forbid"}


class PassportProfilePrefill(BaseModel):
    """Best-effort prefill suggestions from existing account data
    (student_profiles / onboarding). Editor-only hints — never published
    directly and never invented; empty when nothing is known."""

    full_name: str | None = None
    headline: str | None = None
    institution: str | None = None
    degree: str | None = None
    graduation_year: int | None = None
    location: str | None = None
    github_url: str | None = None
    linkedin_url: str | None = None

    model_config = {"extra": "forbid"}


class PassportProfileResponse(BaseModel):
    """Owner view of the passport profile + editor context."""

    profile: PassportProfileData
    has_profile: bool = False
    # Existing passport photo (migration-054 path), if any.
    avatar_url: str | None = None
    prefill: PassportProfilePrefill = Field(default_factory=PassportProfilePrefill)

    model_config = {"extra": "forbid"}


class PassportProfileUpsert(BaseModel):
    """Owner update. Omitted fields are left unchanged; explicit ``null`` /
    empty string clears a field. Validation happens in the service so error
    messages stay field-specific and friendly."""

    full_name: str | None = None
    preferred_name: str | None = None
    pronunciation: str | None = None
    headline: str | None = None
    bio: str | None = None

    institution: str | None = None
    degree: str | None = None
    graduation_year: int | None = None
    location: str | None = None

    github_url: str | None = None
    linkedin_url: str | None = None
    portfolio_url: str | None = None

    role_areas: list[str] | None = None
    availability: str | None = None
    work_authorization_note: str | None = None

    show_location: bool | None = None
    show_availability: bool | None = None
    show_links: bool | None = None
    show_work_authorization: bool | None = None

    model_config = {"extra": "forbid"}
