"""Schemas for the explicit Proof Backfill / Reanalysis endpoint (Step 6).

Owner-only: the authenticated student triggers a reanalysis of THEIR OWN proofs.
The request body intentionally does NOT carry a ``student_id`` — the owner is
always derived from the auth token, so a caller can never reanalyze another
student's proofs. The response is the recruiter-safe public projection of the
:class:`~app.services.proof_reanalysis_service.ProofReanalysisResult`: aggregate
counts, safe deterministic reasons and safe ``ev_…`` evidence-id hashes only —
never a raw payload, storage path, signed URL or private id.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ProofTypeLiteral = Literal[
    "github", "website", "document", "defense", "video", "skill_graph"
]


class ProofReanalysisRequestBody(BaseModel):
    """Explicit reanalysis request for the authenticated owner's proofs.

    No ``student_id`` field by design — the owner is taken from the auth token.
    """

    project_id: str | None = Field(default=None, max_length=128)
    skill_name: str | None = Field(default=None, max_length=160)
    proof_types: list[ProofTypeLiteral] | None = Field(default=None, max_length=6)
    include_llm_synthesis: bool = False
    dry_run: bool = False

    model_config = {"extra": "forbid"}


class StaleEvidenceMarkerResponse(BaseModel):
    evidence_id: str
    reason: str
    recommended_action: str
    source_type: str
    skill_name: str | None = None

    model_config = {"extra": "forbid"}


class ProofReanalysisResultResponse(BaseModel):
    run_id: str
    processed_proof_counts: dict[str, int] = Field(default_factory=dict)
    normalized_evidence_count: int = 0
    linked_chain_count: int = 0
    synthesis_count: int = 0
    stale_evidence_count: int = 0
    skipped_items: int = 0
    warnings: list[str] = Field(default_factory=list)
    public_safe: bool = True
    dry_run: bool = False
    stale_evidence: list[StaleEvidenceMarkerResponse] = Field(default_factory=list)

    model_config = {"extra": "forbid"}
