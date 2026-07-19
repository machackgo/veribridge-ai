"""Beam Link schemas — dynamic revocable short links for the Passport handoff.

Owner responses carry the short path and the caller's OWN passport path only.
The public resolve response is deliberately minimal: link state plus the live
public Passport path — never a user id, link id, holder name, or reason detail.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreateBeamLinkRequest(BaseModel):
    """Optional creation metadata. `event_tag` is a coarse campaign label
    (e.g. "career-fair-2026") for future event links — sanitized server-side."""

    event_tag: str | None = Field(default=None, max_length=64)


class BeamLinkResponse(BaseModel):
    """Owner-only view of one Beam link."""

    id: str
    code: str
    status: str
    short_path: str
    public_passport_path: str
    event_tag: str | None = None
    expires_at: str | None = None
    revoked_at: str | None = None
    created_at: str | None = None


class BeamResolveResponse(BaseModel):
    """Public scan-time resolution: state + live target path, nothing else."""

    status: str
    public_passport_path: str
