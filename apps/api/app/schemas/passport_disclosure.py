"""Schemas for the granular Passport disclosure API (migration 063).

The editor context is a rich owner-only tree (projects → aspects/documents,
skill groups → skills → project claims). Its leaves are intentionally typed as
dicts — the canonical shape is produced by ONE builder
(``passport_disclosure_editor.build_disclosure_context``) and consumed by ONE
owner UI; the write payloads, which cross a trust boundary, are strictly
typed and validated again in the service layer.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DisclosureContextResponse(BaseModel):
    """The full Privacy & Sharing editor context (owner-only)."""

    passport: dict[str, Any] = Field(default_factory=dict)
    projects: list[dict[str, Any]] = Field(default_factory=list)
    skill_groups: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)


class DisclosureModeRequest(BaseModel):
    """Switch between the recruiter-safe and custom disclosure modes."""

    mode: str = Field(min_length=1, max_length=32)

    model_config = {"extra": "forbid"}


class DisclosureOverrideChange(BaseModel):
    """One override upsert (``visibility`` set) or clear (``visibility`` null)."""

    resource_type: str = Field(min_length=1, max_length=64)
    resource_key: str = Field(min_length=1, max_length=300)
    visibility: str | None = Field(default=None, max_length=32)

    model_config = {"extra": "forbid"}


class DisclosureOverridesRequest(BaseModel):
    """Batch of override changes applied atomically (one version bump)."""

    changes: list[DisclosureOverrideChange] = Field(min_length=1, max_length=500)

    model_config = {"extra": "forbid"}


class DisclosurePresetRequest(BaseModel):
    """Apply one safe preset (recruiter_safe | portfolio_open | maximum_privacy)."""

    preset: str = Field(min_length=1, max_length=32)

    model_config = {"extra": "forbid"}


__all__ = [
    "DisclosureContextResponse",
    "DisclosureModeRequest",
    "DisclosureOverrideChange",
    "DisclosureOverridesRequest",
    "DisclosurePresetRequest",
]
