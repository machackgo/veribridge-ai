"""Backfill / Reanalysis Jobs (Step 6) — make OLD proofs useful again.

Steps 2–4 are a *read-time* pipeline: when a Skill Report is rendered, the
Student Proof Vault collects every safe owned proof, Step 2
(:mod:`evidence_normalization_service`) collapses them into the uniform
:class:`~app.services.evidence_normalization_service.NormalizedEvidenceArtifact`
shape, Step 3 (:mod:`cross_proof_linking_service`) links related artifacts into
:class:`~app.services.cross_proof_linking_service.LinkedProofChain`\\s, and Step 4
(:mod:`llm_proof_synthesis_service`) writes recruiter-readable claims. That all
happens lazily, on demand.

This module is the **explicit, controlled** counterpart: an admin- or
student-triggered *reanalysis* that walks a student's existing proofs and
re-runs the SAME deterministic pipeline over them — so old GitHub / website /
document / defense / video / skill-graph proofs are converted into normalized
evidence, rebuilt into linked proof chains, and (only when explicitly enabled)
re-synthesized — and reports what *would be* (or was) regenerated.

What this module is **NOT**:

* It is **not** a scanner. It never runs a live GitHub / website scan and never
  re-reads raw provider payloads. It reasons ONLY over the already-safe proof
  evidence the Vault has already collected and scrubbed.
* It never triggers an LLM in a render path. Synthesis (Step 4) runs **only**
  when ``include_llm_synthesis`` is true on the request; otherwise the LLM
  provider is never resolved or called.
* It is **deterministic and idempotent**. The same proofs always yield the same
  counts, so repeated dry-runs are stable.

Product rules preserved verbatim from Steps 2–4:

* GitHub precise line-level code is the strongest implementation proof; a
  repository-level GitHub row stays a weaker *fallback* and is flagged for
  reanalysis (it can never be promoted to precise code).
* Website proves runtime behaviour, Defense/Video prove understanding, and
  **documents corroborate only** — never primary implementation proof.
* No numeric score / ranking / "fully verified" language is ever produced.

Safety: a :class:`ProofReanalysisResult` (and every
:class:`StaleEvidenceMarker`) holds ONLY aggregate counts, safe deterministic
reason strings, and the safe ``ev_…`` evidence-id hashes — never a raw
transcript / document text / DOM / OCR / provider JSON / storage path / signed
URL / private id / email / raw payload. Its public projection
(:meth:`ProofReanalysisResult.public_view`) additionally drops the private
``student_id`` / ``project_id`` so nothing private can reach a public surface.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.services.cross_proof_linking_service import LinkedProofChain, link_proof_chains
from app.services.evidence_normalization_service import (
    SOURCE_DEFENSE,
    SOURCE_DOCUMENT,
    SOURCE_GITHUB,
    SOURCE_SKILL_GRAPH,
    SOURCE_VIDEO,
    SOURCE_WEBSITE,
    STRENGTH_AGGREGATED,
    STRENGTH_REPO_LEVEL,
    NormalizedEvidenceArtifact,
    _scrub_sensitive,
    normalize_skill_report,
)
from app.services.llm_proof_synthesis_service import LlmFn, synthesize_linked_chains
from app.services.student_proof_vault_service import (
    collect_skill_report,
    collect_skill_summaries,
)

logger = logging.getLogger(__name__)

# Recognised reanalysis proof-type selectors (mirror the Step-2 source types).
PROOF_TYPE_GITHUB = SOURCE_GITHUB
PROOF_TYPE_WEBSITE = SOURCE_WEBSITE
PROOF_TYPE_DOCUMENT = SOURCE_DOCUMENT
PROOF_TYPE_DEFENSE = SOURCE_DEFENSE
PROOF_TYPE_VIDEO = SOURCE_VIDEO
PROOF_TYPE_SKILL_GRAPH = SOURCE_SKILL_GRAPH

_VALID_PROOF_TYPES = frozenset(
    {
        PROOF_TYPE_GITHUB,
        PROOF_TYPE_WEBSITE,
        PROOF_TYPE_DOCUMENT,
        PROOF_TYPE_DEFENSE,
        PROOF_TYPE_VIDEO,
        PROOF_TYPE_SKILL_GRAPH,
    }
)

__all__ = [
    "ProofReanalysisRequest",
    "ProofReanalysisResult",
    "StaleEvidenceMarker",
    "reanalyze_student_proofs",
]

# Email-shaped strings can ride in on a hostile/garbage skill name; the canonical
# sensitive-data scrubber (storage paths / tokens / URLs / local paths) does not
# redact them, so the public projection scrubs emails too.
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# Identifier-shaped strings (bare UUIDs and private ids) are NOT redacted by the
# canonical sensitive-data scrubber — they are not paths / tokens / URLs — yet a
# raw ``user_…`` / ``project_…`` / ``artifact_…`` / ``ev_…`` id or a bare UUID is
# exactly the kind of private id that must never ride out on a public skill label.
# These match a SINGLE token (no internal whitespace):
#   * a canonical 8-4-4-4-12 UUID (with hyphens), e.g.
#     ``550e8400-e29b-41d4-a716-446655440000``;
#   * a bare hex blob of 16+ digits (a de-hyphenated UUID or raw hash), e.g.
#     ``550e8400e29b41d4a716446655440000``;
#   * a ``<word>_<12+ hex>`` / ``<word>-<12+ hex>`` private id, e.g.
#     ``user_1234567890abcdef`` / ``ev_1234567890abcdef``.
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_BARE_HEX_ID_RE = re.compile(r"^[0-9a-fA-F]{16,}$")
_PREFIXED_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*[_-][0-9a-fA-F]{12,}$")

# Punctuation stripped from a token before identifier-shape matching so a trailing
# "." / ")" / quote can't disguise a bare id.
_TOKEN_TRIM = " \t\r\n.,;:!?()[]{}<>\"'`"


def _looks_like_private_identifier(token: str) -> bool:
    """True when a single (whitespace-free) token is shaped like a private id.

    Matches bare UUIDs (hyphenated or de-hyphenated), 16+ char hex blobs, and
    ``<prefix>_<long-hex>`` private ids — never a human skill label like
    ``Python`` / ``FastAPI`` / ``Data Visualization`` (no 12+ char hex run).
    Deterministic — pure regex, never an LLM.
    """
    candidate = token.strip(_TOKEN_TRIM)
    if not candidate:
        return False
    return bool(
        _UUID_RE.match(candidate)
        or _BARE_HEX_ID_RE.match(candidate)
        or _PREFIXED_ID_RE.match(candidate)
    )


def _public_safe_skill_name(skill_name: str | None) -> str | None:
    """Scrub a ``skill_name`` before it reaches a PUBLIC surface.

    A skill name is meant to be a short human label ("Python", "FastAPI"), but it
    is derived from upstream artifact data and so must be treated as untrusted on a
    public projection. This:

    1. redacts email-shaped strings, then runs the canonical sensitive-data
       scrubber (storage paths / signed URLs / tokens / local paths); and
    2. drops any token shaped like a bare/private identifier — a UUID (hyphenated
       or not), a 16+ char hex blob, or a ``<prefix>_<long-hex>`` private id —
       because those are NOT redacted by the canonical scrubber.

    Returns ``None`` when nothing human-readable survives (e.g. the skill name was
    *only* a private id). Deterministic — pure regex, never an LLM.
    """
    if not skill_name:
        return None
    scrubbed = _EMAIL_RE.sub("[redacted]", str(skill_name))
    scrubbed = (_scrub_sensitive(scrubbed) or "").strip()
    if not scrubbed:
        return None
    kept = [tok for tok in scrubbed.split() if not _looks_like_private_identifier(tok)]
    cleaned = " ".join(kept).strip()
    return cleaned or None


# ── Request / result models ───────────────────────────────────────────────────


@dataclass(frozen=True)
class ProofReanalysisRequest:
    """An explicit reanalysis/backfill request for ONE student's proofs.

    ``student_id`` is always the *authenticated owner* — callers must never let an
    untrusted caller name another student here (the endpoint derives it from the
    auth token). ``proof_types`` optionally narrows reanalysis to a subset of the
    six proof surfaces; an empty / ``None`` value means "all". Synthesis (Step 4)
    runs ONLY when ``include_llm_synthesis`` is true.
    """

    student_id: str
    project_id: str | None = None
    skill_name: str | None = None
    proof_types: tuple[str, ...] | None = None
    include_llm_synthesis: bool = False
    dry_run: bool = False

    def selected_proof_types(self) -> frozenset[str]:
        """The validated set of proof types to reanalyze (all six when unset)."""
        if not self.proof_types:
            return _VALID_PROOF_TYPES
        wanted = {str(t).strip().lower() for t in self.proof_types if str(t).strip()}
        valid = wanted & _VALID_PROOF_TYPES
        return frozenset(valid) if valid else _VALID_PROOF_TYPES


@dataclass(frozen=True)
class StaleEvidenceMarker:
    """One piece of weak / stale evidence flagged for reanalysis.

    ``evidence_id`` is the safe Step-2 ``ev_…`` hash (never a raw source id), and
    ``reason`` / ``recommended_action`` are deterministic, recruiter-safe strings —
    so a marker can be surfaced to a student/admin without leaking anything private.
    """

    evidence_id: str
    reason: str
    recommended_action: str
    source_type: str
    project_id: str | None
    skill_name: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "reason": self.reason,
            "recommended_action": self.recommended_action,
            "source_type": self.source_type,
            "project_id": self.project_id,
            "skill_name": self.skill_name,
        }

    def public_view(self) -> dict[str, Any]:
        """Public-safe projection — drops the private ``project_id`` and scrubs the
        ``skill_name`` (untrusted upstream data) so an email-shaped / path-shaped /
        token-shaped skill can never leak on a public surface."""
        return {
            "evidence_id": self.evidence_id,
            "reason": self.reason,
            "recommended_action": self.recommended_action,
            "source_type": self.source_type,
            "skill_name": _public_safe_skill_name(self.skill_name),
        }


@dataclass(frozen=True)
class ProofReanalysisResult:
    """The outcome of one reanalysis run — counts, stale markers, warnings.

    Holds ONLY aggregate counts and safe strings/hashes. ``dry_run`` echoes the
    request: a dry-run reports what *would* be regenerated and persists nothing.
    Because the whole pipeline is deterministic, repeated dry-runs over unchanged
    proofs return identical counts (idempotent).
    """

    run_id: str
    student_id: str
    project_id: str | None
    processed_proof_counts: dict[str, int]
    normalized_evidence_count: int
    linked_chain_count: int
    synthesis_count: int
    stale_evidence_count: int
    skipped_items: int
    warnings: tuple[str, ...]
    public_safe: bool
    dry_run: bool
    stale_evidence: tuple[StaleEvidenceMarker, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Full INTERNAL representation (keeps ``student_id`` / ``project_id``)."""
        return {
            "run_id": self.run_id,
            "student_id": self.student_id,
            "project_id": self.project_id,
            "processed_proof_counts": dict(self.processed_proof_counts),
            "normalized_evidence_count": self.normalized_evidence_count,
            "linked_chain_count": self.linked_chain_count,
            "synthesis_count": self.synthesis_count,
            "stale_evidence_count": self.stale_evidence_count,
            "skipped_items": self.skipped_items,
            "warnings": list(self.warnings),
            "public_safe": self.public_safe,
            "dry_run": self.dry_run,
            "stale_evidence": [m.to_dict() for m in self.stale_evidence],
        }

    def public_view(self) -> dict[str, Any]:
        """Public-safe projection — drops the private ``student_id`` / ``project_id``."""
        return {
            "run_id": self.run_id,
            "processed_proof_counts": dict(self.processed_proof_counts),
            "normalized_evidence_count": self.normalized_evidence_count,
            "linked_chain_count": self.linked_chain_count,
            "synthesis_count": self.synthesis_count,
            "stale_evidence_count": self.stale_evidence_count,
            "skipped_items": self.skipped_items,
            "warnings": list(self.warnings),
            "public_safe": self.public_safe,
            "dry_run": self.dry_run,
            "stale_evidence": [m.public_view() for m in self.stale_evidence],
        }


# ── Run id (stable, non-leaking) ──────────────────────────────────────────────


def _run_id(request: ProofReanalysisRequest, skills: list[str]) -> str:
    """A stable, non-leaking run id derived from the request scope.

    Deterministic so that an identical dry-run of the same scope yields the same
    ``run_id`` (idempotent); it is a short hash and never reveals the raw
    ``student_id``.
    """
    raw = "␟".join(
        (
            str(request.student_id),
            str(request.project_id or ""),
            ",".join(sorted(request.selected_proof_types())),
            str(request.include_llm_synthesis),
            str(request.dry_run),
            ",".join(sorted(skills)),
        )
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"reanalysis_{digest}"


# ── Stale / weak evidence detection (deterministic) ───────────────────────────


def _stale_marker_for(
    artifact: NormalizedEvidenceArtifact,
) -> StaleEvidenceMarker | None:
    """Flag an artifact as stale/weak when reanalysis could strengthen it.

    Deterministic rules (no LLM):

    * **Repo-level GitHub** — a GitHub proof with no precise code line located is a
      weaker fallback than precise code-line evidence and should be reanalyzed to
      try to locate the exact implementation.
    * **Aggregated skill-graph only** — pipeline-aggregated evidence with no
      precise anchor should be backed by a concrete proof.
    * **Missing safe summary** — an artifact whose summary did not survive
      scrubbing carries no recruiter-readable signal and needs reanalysis.

    Documents are intentionally NOT flagged: they are corroboration-only by design,
    not stale evidence. Returns ``None`` when the artifact is healthy.
    """
    if artifact.proof_strength == STRENGTH_REPO_LEVEL:
        return StaleEvidenceMarker(
            evidence_id=artifact.evidence_id,
            reason=(
                "GitHub evidence is repository-level only — no precise code line was "
                "located, so it is weaker than precise code-line proof."
            ),
            recommended_action=(
                "Reanalyze this repository to locate precise, line-level code evidence."
            ),
            source_type=artifact.source_type,
            project_id=artifact.project_id,
            skill_name=artifact.canonical_skill_name or artifact.skill_name,
        )
    if artifact.proof_strength == STRENGTH_AGGREGATED:
        return StaleEvidenceMarker(
            evidence_id=artifact.evidence_id,
            reason=(
                "Aggregated skill-graph evidence only — not anchored to a concrete "
                "GitHub / website / defense proof."
            ),
            recommended_action=(
                "Attach a concrete proof (code, website workflow or defense) to "
                "strengthen this skill."
            ),
            source_type=artifact.source_type,
            project_id=artifact.project_id,
            skill_name=artifact.canonical_skill_name or artifact.skill_name,
        )
    if not (artifact.safe_summary or "").strip():
        return StaleEvidenceMarker(
            evidence_id=artifact.evidence_id,
            reason="Evidence has no recruiter-readable summary after scrubbing.",
            recommended_action="Reanalyze the source proof to regenerate a safe summary.",
            source_type=artifact.source_type,
            project_id=artifact.project_id,
            skill_name=artifact.canonical_skill_name or artifact.skill_name,
        )
    return None


# ── Filtering (proof-type + project scope) ────────────────────────────────────


def _in_scope(
    artifact: NormalizedEvidenceArtifact,
    *,
    selected_types: frozenset[str],
    project_id: str | None,
) -> bool:
    """True when an artifact is within the request's proof-type + project scope."""
    if artifact.source_type not in selected_types:
        return False
    if project_id is not None and str(artifact.project_id or "") != str(project_id):
        return False
    return True


# ── Public API ────────────────────────────────────────────────────────────────


def reanalyze_student_proofs(
    db: Any,
    pipeline_db: Any,
    request: ProofReanalysisRequest,
    *,
    llm_fn: LlmFn | None = None,
) -> ProofReanalysisResult:
    """Explicitly reanalyze ONE student's existing proofs through Steps 2–4.

    For each in-scope skill, this:

    1. collects the student's already-safe Skill Report (no live scan, no raw
       payload re-read) — the Vault is the single source of safe evidence;
    2. **normalizes** every proof into the Step-2 uniform artifact shape and
       filters it to the requested ``proof_types`` / ``project_id`` scope (old
       GitHub precise code preserved, repo-level kept as a weaker fallback,
       documents kept corroboration-only);
    3. **rebuilds linked proof chains** with the Step-3 linker;
    4. **rebuilds synthesis** with the Step-4 layer **only** when
       ``include_llm_synthesis`` is true (otherwise the LLM provider is never
       resolved or called); and
    5. **flags stale/weak evidence** (repo-level GitHub, aggregated-only,
       summary-less) for follow-up reanalysis.

    ``dry_run`` reports what would be regenerated without persisting anything.
    Derived evidence/chains/synthesis are recomputed on every read by Steps 2–4,
    so reanalysis is a deterministic regeneration: no migration or new table is
    introduced, and persistence is intentionally out of scope for this step.
    ``llm_fn`` is injected only for tests so they never touch the network.
    """
    student_id = str(request.student_id)
    selected_types = request.selected_proof_types()
    project_id = request.project_id

    # Resolve the in-scope skills. An explicit ``skill_name`` reanalyzes only that
    # skill; otherwise every skill the student has any safe proof for is reanalyzed.
    if request.skill_name:
        skills = [str(request.skill_name)]
    else:
        summaries = collect_skill_summaries(db, pipeline_db, student_id)
        skills = [str(s["skill"]) for s in summaries if s.get("skill")]

    processed_counts: dict[str, int] = {}
    normalized_count = 0
    skipped_items = 0
    all_chains: list[LinkedProofChain] = []
    stale_markers: list[StaleEvidenceMarker] = []
    warnings: list[str] = []
    seen_stale_ids: set[str] = set()

    for skill in skills:
        # The Vault collector returns already-safe, scrubbed evidence; it never
        # exposes raw payloads and never runs a live scanner. ``synthesize=False``
        # gets the deterministic, synthesis-free report so collection NEVER
        # resolves or calls an LLM provider — Step 4 runs ONLY through the explicit
        # gate below (when ``include_llm_synthesis`` is true).
        report = collect_skill_report(db, pipeline_db, student_id, skill, synthesize=False)

        # Step 2 — normalize this skill's mixed-shape proofs into the uniform model.
        artifacts = normalize_skill_report(report)
        in_scope: list[NormalizedEvidenceArtifact] = []
        for artifact in artifacts:
            if _in_scope(artifact, selected_types=selected_types, project_id=project_id):
                in_scope.append(artifact)
                processed_counts[artifact.source_type] = (
                    processed_counts.get(artifact.source_type, 0) + 1
                )
            else:
                skipped_items += 1

        normalized_count += len(in_scope)

        # Step 3 — rebuild linked proof chains from THIS skill's in-scope artifacts
        # (linking is scoped per skill, exactly as the read-time pipeline does it).
        if in_scope:
            all_chains.extend(link_proof_chains(in_scope))

        # Flag stale/weak evidence (deterministic; de-duped across skills by id).
        for artifact in in_scope:
            marker = _stale_marker_for(artifact)
            if marker is not None and marker.evidence_id not in seen_stale_ids:
                seen_stale_ids.add(marker.evidence_id)
                stale_markers.append(marker)

    # Step 4 — rebuild synthesis ONLY when explicitly requested. When disabled the
    # synthesis layer (and therefore any LLM provider) is never invoked at all.
    synthesis_count = 0
    if request.include_llm_synthesis and all_chains:
        results = synthesize_linked_chains(all_chains, llm_fn=llm_fn)
        synthesis_count = len(results)
    elif request.include_llm_synthesis and not all_chains:
        warnings.append("LLM synthesis requested but no linked proof chains were available.")

    if not skills:
        warnings.append("No skills with reanalyzable proofs were found for this student.")
    if request.proof_types and not (set(request.proof_types) & _VALID_PROOF_TYPES):
        warnings.append(
            "No recognised proof_types supplied — reanalyzed all proof types instead."
        )
    if not request.dry_run:
        # Derived evidence is recomputed on read by Steps 2–4, so there is no
        # separate persistence layer to write in this step; the run is a
        # deterministic regeneration. Surfaced honestly rather than implying a write.
        warnings.append(
            "Reanalysis regenerated derived evidence in-memory; derived data is "
            "recomputed on read, so no separate persistence write was performed."
        )

    return ProofReanalysisResult(
        run_id=_run_id(request, skills),
        student_id=student_id,
        project_id=project_id,
        processed_proof_counts=processed_counts,
        normalized_evidence_count=normalized_count,
        linked_chain_count=len(all_chains),
        synthesis_count=synthesis_count,
        stale_evidence_count=len(stale_markers),
        skipped_items=skipped_items,
        warnings=tuple(warnings),
        public_safe=True,
        dry_run=bool(request.dry_run),
        stale_evidence=tuple(stale_markers),
    )
