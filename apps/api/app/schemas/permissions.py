"""Schemas for role-based access control and permissions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


UserRoleName = Literal[
    "student",
    "recruiter",
    "admin",
    "reviewer",
    "faculty_reviewer",
    "company_reviewer",
    "support",
]
UserRoleScope = Literal["global", "organization", "proof_session", "passport", "quality_case"]


class DashboardAccess(BaseModel):
    student_dashboard: bool = False
    recruiter_dashboard: bool = False
    admin_dashboard: bool = False
    reviewer_dashboard: bool = False


class CurrentUserPermissionsResponse(BaseModel):
    user_id: str
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    dashboard_access: DashboardAccess
    generated_at: datetime | str


class UserRoleResponse(BaseModel):
    id: str
    user_id: str
    role: UserRoleName
    scope: UserRoleScope
    scope_id: str | None = None
    granted_by: str | None = None
    is_active: bool
    created_at: datetime | str
    revoked_at: datetime | str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UserRoleGrantRequest(BaseModel):
    role: UserRoleName
    scope: UserRoleScope = "global"
    scope_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

