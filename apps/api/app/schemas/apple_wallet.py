"""Apple Wallet Passport Pass schemas.

The availability response is booleans ONLY — never certificate paths, secret
refs, identifiers, or filesystem detail. It exists so the frontend can decide
whether to render the "Add to Apple Wallet" button without ever guessing
(no button unless the backend can actually produce a real signed pass).
"""

from __future__ import annotations

from pydantic import BaseModel


class AppleWalletAvailabilityResponse(BaseModel):
    """Owner-only readiness summary for Apple Wallet passes."""

    # The single flag the frontend button obeys: feature flag on AND pass
    # identifiers set AND signing material present.
    enabled: bool
    # Granular readiness for owner-facing diagnostics (booleans only).
    feature_flag: bool
    identifiers_configured: bool
    signing_ready: bool
