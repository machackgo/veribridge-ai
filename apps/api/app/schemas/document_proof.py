"""Schemas for standalone Document Proof / supporting evidence submissions.

These wrap ``optional_evidence_submissions`` rows (proof_session_id IS NULL)
for the standalone Document Proof flow. Raw document text is never exposed
in these response models.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

DocumentProofSourceType = Literal["document", "certificate_transcript"]


class DocumentProofTextSubmit(BaseModel):
    source_type: DocumentProofSourceType = "document"
    raw_text: str = Field(default="", max_length=80_000)
    title: str | None = Field(default=None, max_length=200)
    claimed_skills: list[str] = Field(default_factory=list)
    description: str | None = Field(default=None, max_length=2000)


class DocumentProofResponse(BaseModel):
    id: str
    user_id: str
    source_type: DocumentProofSourceType
    status: str
    filename: str | None = None
    title: str | None = None
    claimed_skills: list[str] = Field(default_factory=list)
    description: str | None = None
    analysis_json: dict[str, Any] = Field(default_factory=dict)
    evidence_objects: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str | None = None
    # ── Artifact retention (migration 056) ────────────────────────────────────
    # Whether the ORIGINAL uploaded file was retained as a gated proof artifact,
    # and its opaque artifact id for the authorized view/download routes —
    # never a storage path or signed URL. False/None when retention storage is
    # not configured (verified-excerpts-only remains the honest state).
    original_retained: bool = False
    original_artifact_id: str | None = None
    # ── Canonical project relationship (migration 058 + attach metadata) ──────
    # The document's REAL relationship state — the same canonical rows the
    # Passport and reports read. The UI must render attachment status from
    # these fields only, never from a display title, so "shown under a project"
    # and "attached to a project" can never diverge again.
    project_id: str | None = None
    project_title: str | None = None
    project_relationship_state: str = "vault_only"
