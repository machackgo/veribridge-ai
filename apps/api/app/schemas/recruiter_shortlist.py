"""Schemas for recruiter saved Work Passports and shortlists."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


SavedPassportStatus = Literal["saved", "shortlisted", "reviewing", "contacted", "rejected", "archived"]


class RecruiterSavedPassportCreate(BaseModel):
    requester_email: str
    requester_name: str | None = None
    organization_name: str | None = None
    status: SavedPassportStatus = "saved"
    tags: list[str] = Field(default_factory=list)
    private_notes: str | None = None


class RecruiterSavedPassportUpdate(BaseModel):
    requester_email: str
    status: SavedPassportStatus | None = None
    tags: list[str] | None = None
    private_notes: str | None = None
    reviewed_sections: list[str] | None = None
    fit_score: int | None = Field(default=None, ge=0, le=100)
    fit_reason: str | None = None


class RecruiterReviewedSectionCreate(BaseModel):
    requester_email: str
    section: str


class RecruiterSavedPassportResponse(BaseModel):
    id: str
    requester_profile_id: str
    passport_id: str
    proof_session_id: str
    student_user_id: str
    requester_email: str
    organization_name: str | None = None
    status: SavedPassportStatus
    tags: list[str] = Field(default_factory=list)
    private_notes: str | None = None
    reviewed_sections: list[str] = Field(default_factory=list)
    fit_score: int | None = None
    fit_reason: str | None = None
    last_viewed_at: datetime | str | None = None
    public_slug: str | None = None
    public_title: str | None = None
    public_summary: str | None = None
    field: str | None = None
    created_at: datetime | str
    updated_at: datetime | str
