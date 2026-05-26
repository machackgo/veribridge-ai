"""Schemas for Work Passport analytics."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RequestedSectionSummary(BaseModel):
    section: str
    count: int


class RequesterOrganizationSummary(BaseModel):
    organization_name: str | None = None
    organization_domain: str | None = None
    request_count: int
    unique_requester_emails: int


class WorkPassportActivityItem(BaseModel):
    event_type: str
    event_summary: str | None = None
    actor_type: str | None = None
    actor_email: str | None = None
    requester_organization: str | None = None
    proof_session_id: str | None = None
    passport_id: str | None = None
    created_at: datetime | str


class AccessRequestSummary(BaseModel):
    total_access_requests: int
    pending_access_requests: int
    approved_access_requests: int
    denied_access_requests: int
    revoked_access_grants: int
    active_access_grants: int


class WorkPassportAnalyticsResponse(BaseModel):
    total_passports: int
    total_public_views: int
    total_access_requests: int
    pending_access_requests: int
    approved_access_requests: int
    denied_access_requests: int
    revoked_access_grants: int
    active_access_grants: int
    protected_evidence_views: int
    unique_requester_emails: int
    unique_requester_organizations: int
    top_requested_sections: list[RequestedSectionSummary] = Field(default_factory=list)
    recent_activity: list[WorkPassportActivityItem] = Field(default_factory=list)
    requester_organizations: list[RequesterOrganizationSummary] = Field(default_factory=list)
    unread_notifications: int = 0
    generated_at: datetime | str
