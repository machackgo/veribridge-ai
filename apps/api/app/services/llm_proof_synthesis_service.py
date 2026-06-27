"""LLM Synthesis Layer (Step 4) — recruiter-readable claims over linked proof.

Steps 2 (:mod:`evidence_normalization_service`) and 3
(:mod:`cross_proof_linking_service`) are *purely deterministic*: Step 2 collapses
every proof surface into one uniform :class:`~app.services.evidence_normalization_service.NormalizedEvidenceArtifact`
and Step 3 links the related artifacts into a :class:`~app.services.cross_proof_linking_service.LinkedProofChain`.
This module is the **last** layer: it takes an already-linked chain and produces
recruiter-readable :class:`SynthesisClaim`\\s that explain — in plain language —
what the connected evidence shows, why the items are related, which skill/subskill
is demonstrated, what limitations remain, and what is corroborated versus not
assessed.

The LLM runs **only after** deterministic normalization and linking, and it is
fenced in hard:

* **It never invents evidence.** Every claim must cite ``evidence_id``\\s that are
  actually present in the input chain (``chain.linked_evidence_ids``). Any unknown
  citation is stripped; a claim that cited an unknown id is downgraded to
  ``Needs review``; a claim left with no valid citation is dropped entirely.
* **It never overrides deterministic proof strength.** Each chain has a
  deterministic *ceiling* tier derived from its source mix (precise GitHub code is
  strongest; a document-only chain can never exceed ``Needs review``); a claim's
  ``qualitative_tier`` is clamped so the LLM can only ever weaken it, never
  promote evidence past what the deterministic engines allow.
* **It never claims a skill is fully verified and never emits a numeric score.**
  Over-claim phrases ("fully verified", "100% proven") are neutralised and any
  score-like fragment is scrubbed out.
* **It can never leak private data.** Every returned string is re-scrubbed with the
  same canonical sensitive-data scrubber Steps 2/3 use, so no raw transcript /
  document text / DOM / OCR / provider JSON / storage path / signed URL / private
  id / email / raw payload can reach a recruiter-facing claim. Document evidence
  stays corroboration-only and never anchors an "implementation demonstrated"
  claim.

**Fail-closed:** if the LLM is disabled, unavailable, slow/timed out, raises,
returns invalid JSON, cites unknown evidence ids, or yields no usable claim, a
deterministic rule-based synthesis is returned from the chain metadata instead —
the product never fails just because the LLM failed. The LLM is injected as a
simple callable (``llm_fn``) so tests never touch the network.

**Provider-agnostic.** Anthropic is never required. The provider is chosen by
config (:data:`settings.llm_synthesis_provider`): ``disabled`` (deterministic
only — the default), ``local_openai`` (a local OpenAI-compatible
``/chat/completions`` endpoint — Ollama / vLLM / LM Studio serving Qwen, etc., at
zero API cost) or ``anthropic`` (only when Anthropic is *also* explicitly
configured). The whole layer stays disabled unless
:data:`settings.llm_synthesis_enabled` is true.

**Bounded parallelism.** :func:`synthesize_linked_chains` runs chains
sequentially (safe inside a request handler). :func:`synthesize_linked_chains_async`
runs independent chains under an :class:`asyncio.Semaphore` (default concurrency 1
for a single local model; raise via env for a GPU server). Either way each chain
synthesizes through the *same* per-chain pipeline, so one chain's LLM failure only
falls that chain back — it never aborts the run — and output order is always the
input order. Only the already-safe public projection of a chain is ever sent to a
provider; raw/private evidence never leaves the process.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.services.cross_proof_linking_service import LinkedProofChain
from app.services.evidence_normalization_service import (
    SOURCE_DEFENSE,
    SOURCE_DOCUMENT,
    SOURCE_GITHUB,
    SOURCE_SKILL_GRAPH,
    SOURCE_VIDEO,
    SOURCE_WEBSITE,
    STRENGTH_AGGREGATED,
    STRENGTH_PRECISE_CODE,
    STRENGTH_REPO_LEVEL,
    STRENGTH_RUNTIME,
    STRENGTH_SELF_EXPLANATION,
    STRENGTH_SUPPORTING_MOMENT,
    NormalizedEvidenceArtifact,
    _scrub_sensitive,
)
from app.services.vbr_student_report import _scrub_score_fragments, _trace_text

logger = logging.getLogger(__name__)

# ── Qualitative tiers (NEVER a numeric score), strongest → weakest ─────────────
TIER_STRONG = "Strongly corroborated"
TIER_CORROBORATED = "Corroborated"
TIER_SUPPORTING = "Supporting evidence"
TIER_NEEDS_REVIEW = "Needs review"
TIER_INSUFFICIENT = "Insufficient evidence"

# Rank 0 = strongest. Used to clamp a claim so it can never EXCEED the chain's
# deterministic ceiling (a higher rank number is weaker).
_TIER_RANK = {
    TIER_STRONG: 0,
    TIER_CORROBORATED: 1,
    TIER_SUPPORTING: 2,
    TIER_NEEDS_REVIEW: 3,
    TIER_INSUFFICIENT: 4,
}
_RANK_TIER = {rank: tier for tier, rank in _TIER_RANK.items()}
_VALID_TIERS = frozenset(_TIER_RANK)

# Phrases the LLM must never assert (we can never claim a skill is fully verified).
_OVERCLAIM_RE = re.compile(
    r"\b(fully|completely|totally|definitively|conclusively|100%|absolutely)\s+"
    r"(verified|proven|proved|confirmed|validated|guaranteed)\b",
    re.IGNORECASE,
)
_OVERCLAIM_WORDS_RE = re.compile(
    r"\b(guaranteed|infallible|irrefutable)\b", re.IGNORECASE
)

# Score / ranking / rating / percentile language must NEVER reach a recruiter-facing
# string — VeriBridge presents qualitative tiers only, never a numeric score, rank,
# or rating.  The shared ``_scrub_score_fragments`` already strips ``X/100``, ``X%``
# and the word "confidence"; these patterns additionally neutralise score, rank,
# rating, "out of N", "N stars", "top N%", and percentile phrasing.  Legitimate
# technical numbers (line numbers, file names, versions, timestamps, counts) are not
# matched by these patterns, so they survive — but safety always wins over a number.
_SCORE_RANK_PATTERNS = (
    # "trust score 98", "verification score: 92", "score of 88", "rating 4.9"
    re.compile(
        r"\b(?:[a-z]+\s+){0,2}(?:scor(?:e|ed|ing)|rating|rated)s?\b"
        r"(?:\s*(?:of|is|are|was|:|=|at))?\s*\d{1,3}(?:\.\d+)?\b",
        re.IGNORECASE,
    ),
    # "ranked #1", "rank #1", "ranked number 1", "ranking 1", "rank 1"
    re.compile(
        r"\b(?:ranked|ranks|ranking|rank)\b\s*(?:#|no\.?|number)?\s*\d+\b",
        re.IGNORECASE,
    ),
    # bare "#1" (a leftover rank token)
    re.compile(r"#\s*\d+\b"),
    # "9.8 out of 10", "98 out of 100"
    re.compile(r"\b\d{1,3}(?:\.\d+)?\s+out of\s+\d{1,3}\b", re.IGNORECASE),
    # "9.8/10" (decimal ratios; integer X/100 also handled by the shared scrubber)
    re.compile(r"\b\d{1,3}(?:\.\d+)?\s*/\s*\d{1,3}\b"),
    # "4.9 stars", "5 star"
    re.compile(r"\b\d(?:\.\d+)?\s*stars?\b", re.IGNORECASE),
    # "top 1%", "top 1 percent", "top 0.5 percentile" (no trailing \b — "%" is not
    # a word char, so a \b after it would never match when a space/emdash follows).
    re.compile(r"\btop\s+\d{1,3}(?:\.\d+)?\s*(?:%|percent(?:ile)?)", re.IGNORECASE),
    # "98th percentile", or a bare "percentile" claim
    re.compile(r"\b\d{1,3}(?:st|nd|rd|th)?\s*percentile\b", re.IGNORECASE),
    re.compile(r"\bpercentile\b", re.IGNORECASE),
)


def _scrub_score_rank_language(text: str) -> str:
    """Neutralise score / ranking / rating / percentile phrasing in public strings."""
    for pattern in _SCORE_RANK_PATTERNS:
        text = pattern.sub(" ", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([.,;:])", r"\1", text)
    return text.strip()


# Email addresses — not caught by the shared transcript scrubber, so we redact them
# here too (strengthening, never weakening, the public-safety rules).
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# Max length for any single recruiter-facing synthesis string.
_TEXT_LIMIT = 400

# A callable that maps (system_prompt, user_message) -> raw model text (or None).
LlmFn = Callable[[str, str], "str | None"]

__all__ = [
    "SynthesisClaim",
    "SynthesisResult",
    "synthesize_chain",
    "synthesize_linked_chains",
    "synthesize_linked_chains_async",
    "synthesize_linked_chains_bounded",
    "TIER_STRONG",
    "TIER_CORROBORATED",
    "TIER_SUPPORTING",
    "TIER_NEEDS_REVIEW",
    "TIER_INSUFFICIENT",
]


# ── Output models ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SynthesisClaim:
    """One recruiter-readable claim, fully cited to existing evidence ids.

    ``supporting_evidence_ids`` only ever holds ``ev_…`` ids that are present in the
    source chain — an LLM can never smuggle an invented citation through. Every
    string field is already scrubbed/clamped by the time the claim is built.
    """

    claim_id: str
    claim: str
    supporting_evidence_ids: tuple[str, ...]
    why_connected: str
    limitations: tuple[str, ...]
    qualitative_tier: str
    public_safe: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "claim": self.claim,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "why_connected": self.why_connected,
            "limitations": list(self.limitations),
            "qualitative_tier": self.qualitative_tier,
            "public_safe": self.public_safe,
        }

    def public_view(self) -> dict[str, Any]:
        """Public-safe projection — re-scrub every retained string defensively."""
        return {
            "claim_id": self.claim_id,
            "claim": _safe_text(self.claim),
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "why_connected": _safe_text(self.why_connected),
            "limitations": [_safe_text(lim) for lim in self.limitations],
            "qualitative_tier": self.qualitative_tier,
            "public_safe": self.public_safe,
        }


@dataclass(frozen=True)
class SynthesisResult:
    """The synthesis for ONE linked proof chain."""

    chain_id: str
    skill_name: str | None
    canonical_skill_name: str | None
    project_title: str | None
    claims: tuple[SynthesisClaim, ...]
    overall_summary: str
    limitations: tuple[str, ...]
    public_safe: bool
    source: str = "deterministic"  # "llm" | "deterministic" — provenance, not a score
    artifacts: tuple[NormalizedEvidenceArtifact, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "skill_name": self.skill_name,
            "canonical_skill_name": self.canonical_skill_name,
            "project_title": self.project_title,
            "claims": [c.to_dict() for c in self.claims],
            "overall_summary": self.overall_summary,
            "limitations": list(self.limitations),
            "public_safe": self.public_safe,
            "source": self.source,
        }

    def public_view(self) -> dict[str, Any]:
        """Public-safe projection — drops private project_id, re-scrubs strings."""
        return {
            "chain_id": self.chain_id,
            "canonical_skill_name": self.canonical_skill_name,
            "project_title": _scrub_sensitive(self.project_title),
            "claims": [c.public_view() for c in self.claims if c.public_safe],
            "overall_summary": _safe_text(self.overall_summary),
            "limitations": [_safe_text(lim) for lim in self.limitations],
            "public_safe": self.public_safe,
            "source": self.source,
        }


# ── Safety helpers ────────────────────────────────────────────────────────────


def _safe_text(value: Any, limit: int = _TEXT_LIMIT) -> str:
    """Fully scrub a recruiter-facing string.

    Applies, in order: over-claim neutralisation (no "fully verified"), score /
    rank / rating / percentile language removal (no fake scores or rankings), score
    fragment removal (no fake confidence numbers), the canonical sensitive-data
    scrubber (no tokens / signed URLs / storage or local paths / emails / private
    ids) and a length bound. Deterministic — pure regex, never an LLM.
    """
    text = str(value or "")
    text = _OVERCLAIM_RE.sub("demonstrated by", text)
    text = _OVERCLAIM_WORDS_RE.sub("evidenced", text)
    text = _scrub_score_rank_language(text)
    text = _EMAIL_RE.sub("[redacted]", text)
    scrubbed = _scrub_sensitive(_scrub_score_fragments(text)) or ""
    return _trace_text(scrubbed, limit)


def _clamp_tier(tier: str, ceiling: str) -> str:
    """Clamp ``tier`` so it can never be STRONGER than ``ceiling``.

    The LLM may only ever *weaken* a tier relative to the deterministic ceiling, so
    it can never promote evidence past what Steps 2/3 allow (e.g. it can never call
    a document-only chain "Strongly corroborated").
    """
    if tier not in _VALID_TIERS:
        tier = TIER_NEEDS_REVIEW
    rank = max(_TIER_RANK[tier], _TIER_RANK[ceiling])
    return _RANK_TIER[rank]


# ── Deterministic ceiling (mirrors the proof-strength rules of Steps 2/3) ──────


def _ceiling_tier(chain: LinkedProofChain) -> str:
    """The strongest tier this chain may carry, from its deterministic source mix.

    Independent *strong* sources are precise GitHub code (implementation), a Website
    runtime workflow (behaviour) and a Project Defense / Video (understanding).
    Documents corroborate but are never a strong source, so a document-only chain
    can never exceed ``Needs review``. Precise code anchors the strongest tier.
    """
    summary = chain.proof_strength_summary or {}
    has_precise = bool(summary.get("has_precise_code"))
    has_runtime = bool(summary.get("has_runtime_behavior"))
    has_understanding = bool(summary.get("has_self_explanation")) or bool(
        summary.get("has_supporting_moment")
    )
    has_doc = int(summary.get("corroborating_document_count") or 0) > 0
    strengths = set(summary.get("strengths_present") or [])
    has_repo_level = STRENGTH_REPO_LEVEL in strengths
    has_aggregated = STRENGTH_AGGREGATED in strengths

    strong = sum((has_precise, has_runtime, has_understanding))
    if strong >= 2:
        return TIER_STRONG if has_precise else TIER_CORROBORATED
    if strong == 1:
        return TIER_CORROBORATED if has_doc else TIER_SUPPORTING
    if has_repo_level or has_doc or has_aggregated:
        # Only repo-level GitHub, documents, or aggregated graph evidence remains.
        return TIER_NEEDS_REVIEW
    return TIER_INSUFFICIENT


def _cited_ceiling_tier(artifacts: list[NormalizedEvidenceArtifact]) -> str:
    """Strongest tier a claim may carry given ONLY the evidence it actually cites.

    The whole-chain ceiling (:func:`_ceiling_tier`) is necessary but not sufficient:
    a claim inside a strong, mixed chain might cite only its *weakest* evidence (e.g.
    only a document), and must then be clamped to what *that* evidence can support —
    never to the strong chain's ceiling. So we recompute the ceiling from the cited
    subset, mirroring the same proof-strength rules:

    * precise GitHub code, a runtime website workflow and a defense/video explanation
      are independent *strong* sources; two or more (with precise code present) reach
      ``Strongly corroborated``;
    * a document on its own is corroboration-only and can never exceed
      ``Supporting evidence``;
    * repo-level or aggregated evidence on its own stays at ``Needs review``
      (always weaker than precise code-line evidence).

    An empty subset returns ``TIER_STRONG`` (rank 0, the identity for the
    weaker-of-two clamp) so it never *strengthens* the chain ceiling.
    """
    if not artifacts:
        return TIER_STRONG
    groups = {_artifact_group(a) for a in artifacts}
    has_precise = _PRECISE in groups
    has_runtime = _RUNTIME in groups
    has_understanding = _UNDERSTANDING in groups
    has_doc = _DOCUMENT in groups
    has_repo_level = _REPO in groups
    has_aggregated = _AGGREGATED in groups

    strong = sum((has_precise, has_runtime, has_understanding))
    if strong >= 2:
        return TIER_STRONG if has_precise else TIER_CORROBORATED
    if strong == 1:
        return TIER_CORROBORATED if has_doc else TIER_SUPPORTING
    if has_repo_level or has_aggregated:
        return TIER_NEEDS_REVIEW
    if has_doc:
        # Document-only citation: corroboration-only, never implementation proof.
        return TIER_SUPPORTING
    return TIER_INSUFFICIENT


def _weaker_ceiling(a: str, b: str) -> str:
    """Return the weaker (higher-rank) of two tiers — the effective clamp ceiling."""
    return _RANK_TIER[max(_TIER_RANK[a], _TIER_RANK[b])]


# ── Deterministic, rule-based synthesis (the always-available fallback) ────────

# Source groups in strongest → weakest order. Each maps to a claim template and the
# strongest tier a claim from that group alone may carry (before clamping to the
# chain ceiling). Documents and repo-level/aggregated evidence are capped weak so
# they can never alone create an "implementation demonstrated" claim.
_PRECISE = "precise_implementation"
_REPO = "repo_level"
_RUNTIME = "runtime"
_UNDERSTANDING = "understanding"
_AGGREGATED = "aggregated"
_DOCUMENT = "document"

_GROUP_NATURAL_TIER = {
    _PRECISE: TIER_STRONG,
    _RUNTIME: TIER_STRONG,
    _UNDERSTANDING: TIER_STRONG,
    _REPO: TIER_NEEDS_REVIEW,
    _AGGREGATED: TIER_NEEDS_REVIEW,
    _DOCUMENT: TIER_SUPPORTING,
}

# Order claims are emitted in (strong implementation first).
_GROUP_ORDER = (_PRECISE, _RUNTIME, _UNDERSTANDING, _REPO, _AGGREGATED, _DOCUMENT)


def _artifact_group(artifact: NormalizedEvidenceArtifact) -> str:
    strength = artifact.proof_strength
    if strength == STRENGTH_PRECISE_CODE:
        return _PRECISE
    if strength == STRENGTH_REPO_LEVEL:
        return _REPO
    if strength == STRENGTH_RUNTIME:
        return _RUNTIME
    if strength in (STRENGTH_SELF_EXPLANATION, STRENGTH_SUPPORTING_MOMENT):
        return _UNDERSTANDING
    if strength == STRENGTH_AGGREGATED:
        return _AGGREGATED
    return _DOCUMENT


def _group_claim_text(group: str, skill: str, project: str) -> str:
    if group == _PRECISE:
        return (
            f"Precise, line-level GitHub code demonstrates the implementation of "
            f"{skill} in {project}."
        )
    if group == _RUNTIME:
        return (
            f"A recorded website workflow shows {skill} working at runtime in {project}."
        )
    if group == _UNDERSTANDING:
        return (
            f"The candidate explained {skill} in their Project Defense for {project}, "
            "evidencing personal understanding."
        )
    if group == _REPO:
        return (
            f"Repository-level GitHub evidence supports {skill} in {project} "
            "(no precise code line was located)."
        )
    if group == _AGGREGATED:
        return f"Aggregated skill-graph evidence references {skill} in {project}."
    return (
        f"A document corroborates {skill} in {project} "
        "(supporting evidence only — never primary implementation proof)."
    )


def _deterministic_synthesis(chain: LinkedProofChain, ceiling: str) -> SynthesisResult:
    """A safe, rule-based synthesis built only from the chain's own metadata.

    Always available — this is what runs when the LLM is unavailable, returns
    invalid JSON, or yields nothing usable. Pure and deterministic: identical input
    always yields an identical result.
    """
    skill = chain.canonical_skill_name or chain.skill_name or "this skill"
    project = chain.project_title or "this project"
    why = " ".join(chain.connection_reasons) if chain.connection_reasons else (
        "Connected through shared deterministic evidence signals."
    )

    grouped: dict[str, list[NormalizedEvidenceArtifact]] = {}
    for artifact in chain.artifacts:
        grouped.setdefault(_artifact_group(artifact), []).append(artifact)

    claims: list[SynthesisClaim] = []
    for group in _GROUP_ORDER:
        members = grouped.get(group)
        if not members:
            continue
        ev_ids = tuple(sorted(m.evidence_id for m in members))
        tier = _clamp_tier(_GROUP_NATURAL_TIER[group], ceiling)
        claims.append(
            _make_claim(
                chain_id=chain.chain_id,
                claim=_group_claim_text(group, skill, project),
                evidence_ids=ev_ids,
                why_connected=why,
                limitations=chain.limitations,
                tier=tier,
                public_safe=all(m.public_safe for m in members),
            )
        )

    summary = _overall_summary(skill, project, claims, ceiling)
    return SynthesisResult(
        chain_id=chain.chain_id,
        skill_name=chain.skill_name,
        canonical_skill_name=chain.canonical_skill_name,
        project_title=chain.project_title,
        claims=tuple(claims),
        overall_summary=summary,
        limitations=tuple(_safe_text(limit) for limit in chain.limitations),
        public_safe=chain.public_safe,
        source="deterministic",
        artifacts=chain.artifacts,
    )


# ── Claim construction (shared by both paths — always scrubbed/clamped) ────────


def _claim_id(chain_id: str, evidence_ids: tuple[str, ...], salt: str = "") -> str:
    raw = "␟".join((chain_id, salt, *sorted(evidence_ids)))
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"claim_{digest}"


def _make_claim(
    *,
    chain_id: str,
    claim: str,
    evidence_ids: tuple[str, ...],
    why_connected: str,
    limitations: tuple[str, ...] | list[str],
    tier: str,
    public_safe: bool,
    salt: str = "",
) -> SynthesisClaim:
    """Build a fully scrubbed, tier-validated claim. Single choke point for safety."""
    if tier not in _VALID_TIERS:
        tier = TIER_NEEDS_REVIEW
    safe_limits = tuple(
        dict.fromkeys(t for limit in limitations if (t := _safe_text(limit)))
    )
    return SynthesisClaim(
        claim_id=_claim_id(chain_id, evidence_ids, salt),
        claim=_safe_text(claim),
        supporting_evidence_ids=tuple(evidence_ids),
        why_connected=_safe_text(why_connected),
        limitations=safe_limits,
        qualitative_tier=tier,
        public_safe=bool(public_safe),
    )


def _overall_summary(
    skill: str, project: str, claims: list[SynthesisClaim], ceiling: str
) -> str:
    if not claims:
        return f"No connected evidence was synthesized for {skill} in {project}."
    strongest = min(claims, key=lambda c: _TIER_RANK[c.qualitative_tier])
    return (
        f"In {project}, {len(claims)} synthesized claim(s) describe {skill}; the "
        f"strongest is {strongest.qualitative_tier.lower()}."
    )


# ── LLM path ──────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are VeriBridge's proof-synthesis writer. You are given a deterministic, "
    "already-linked proof chain — a set of evidence items that VeriBridge has "
    "ALREADY connected and ALREADY scrubbed. Your only job is to write short, "
    "recruiter-readable synthesis claims that explain what the connected evidence "
    "shows, why the items are related, which skill/subskill is demonstrated, and "
    "what limitations remain.\n\n"
    "HARD RULES — you must obey every one:\n"
    "1. NEVER invent evidence. Every claim must cite one or more evidence_id values "
    "   that appear EXACTLY in the provided evidence list. Do not invent ids.\n"
    "2. NEVER say a skill is 'fully verified', 'proven', '100%', or similar. Use "
    "   qualitative language only.\n"
    "3. NEVER output a numeric confidence score. Use ONLY these qualitative tiers: "
    "   'Strongly corroborated', 'Corroborated', 'Supporting evidence', "
    "   'Needs review', 'Insufficient evidence'.\n"
    "4. Document evidence is CORROBORATION ONLY — it can never be the basis for an "
    "   'implementation demonstrated' claim and never raises a chain above "
    "   'Supporting evidence' on its own.\n"
    "5. Prefer precise GitHub code as the strongest implementation proof; website, "
    "   defense and video corroborate or explain; repository-level GitHub is weaker.\n"
    "6. NEVER expose raw transcripts, document text, DOM, OCR, provider JSON, "
    "   storage paths, signed URLs, file paths, emails, or private ids.\n\n"
    "Return ONLY valid JSON (no markdown fences) in this exact shape:\n"
    "{\n"
    '  "claims": [\n'
    "    {\n"
    '      "claim": "...",\n'
    '      "supporting_evidence_ids": ["ev_..."],\n'
    '      "why_connected": "...",\n'
    '      "limitations": ["..."],\n'
    '      "qualitative_tier": "Corroborated"\n'
    "    }\n"
    "  ],\n"
    '  "overall_summary": "..."\n'
    "}\n"
)


def _build_user_message(chain: LinkedProofChain) -> str:
    """A safe, public-only description of the chain for the LLM to reason over.

    Only already-safe fields are sent (the chain's public view of each artifact),
    so even the prompt can never carry a private id / raw payload to the provider.
    """
    evidence = [
        {
            "evidence_id": a.evidence_id,
            "source_type": a.source_type,
            "source_label": a.source_label,
            "proof_strength": a.proof_strength,
            "skill": a.canonical_skill_name or a.skill_name,
            "subskill": a.subskill_name,
            "exact_location": _safe_text(a.exact_location, 160),
            "summary": _safe_text(a.safe_summary, 240),
            "is_document": a.source_type == SOURCE_DOCUMENT,
        }
        for a in chain.artifacts
    ]
    payload = {
        "skill": chain.canonical_skill_name or chain.skill_name,
        "project_title": _safe_text(chain.project_title, 160),
        "connection_reasons": [_safe_text(r, 160) for r in chain.connection_reasons],
        "deterministic_proof_strength": chain.proof_strength_summary.get("label"),
        "limitations": [_safe_text(limit, 160) for limit in chain.limitations],
        "valid_evidence_ids": list(chain.linked_evidence_ids),
        "evidence": evidence,
    }
    return (
        "Write synthesis claims for this already-linked proof chain. You may ONLY "
        "cite evidence_id values from valid_evidence_ids.\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def _parse_llm_synthesis(
    raw: str, chain: LinkedProofChain, ceiling: str
) -> SynthesisResult | None:
    """Validate + scrub LLM JSON into a safe result, or ``None`` if unusable.

    Enforces, per claim: every cited id must exist in the chain; unknown ids are
    stripped; a claim that cited any unknown id is downgraded to ``Needs review``; a
    claim left with no valid id is dropped; the tier is clamped to the chain ceiling;
    every string is scrubbed; ``public_safe`` requires the chain and every cited
    artifact to be public-safe. Returns ``None`` (→ deterministic fallback) when the
    JSON is invalid or no usable claim survives.
    """
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        logger.info("LLM proof synthesis returned invalid JSON; using fallback")
        return None
    if not isinstance(parsed, dict):
        return None

    valid_ids = set(chain.linked_evidence_ids)
    by_id = {a.evidence_id: a for a in chain.artifacts}
    raw_claims = parsed.get("claims")
    if not isinstance(raw_claims, list):
        return None

    claims: list[SynthesisClaim] = []
    for idx, item in enumerate(raw_claims):
        if not isinstance(item, dict):
            continue
        cited_raw = item.get("supporting_evidence_ids") or []
        if not isinstance(cited_raw, list):
            cited_raw = [cited_raw]
        cited = tuple(str(c) for c in cited_raw)
        kept = tuple(c for c in cited if c in valid_ids)
        if not kept:
            # No real evidence backs this claim → never let it into the output.
            continue
        had_unknown = any(c not in valid_ids for c in cited)

        claim_text = str(item.get("claim") or "").strip()
        if not _safe_text(claim_text):
            continue

        tier = str(item.get("qualitative_tier") or TIER_NEEDS_REVIEW)
        if had_unknown:
            # A claim that referenced an invented id can never read as strong.
            tier = TIER_NEEDS_REVIEW
        # Clamp to the WEAKER of the whole-chain ceiling and the ceiling implied by
        # only the evidence THIS claim cites. A document-only citation inside a
        # strong, mixed chain is therefore capped at the document's strength
        # (Supporting evidence) and can never become Strongly corroborated.
        cited_artifacts = [by_id[c] for c in kept if c in by_id]
        effective_ceiling = _weaker_ceiling(
            ceiling, _cited_ceiling_tier(cited_artifacts)
        )
        tier = _clamp_tier(tier, effective_ceiling)

        limitations = item.get("limitations") or []
        if not isinstance(limitations, list):
            limitations = [limitations]

        public_safe = chain.public_safe and all(
            by_id[c].public_safe for c in kept if c in by_id
        )
        claims.append(
            _make_claim(
                chain_id=chain.chain_id,
                claim=claim_text,
                evidence_ids=kept,
                why_connected=str(item.get("why_connected") or ""),
                limitations=limitations,
                tier=tier,
                public_safe=public_safe,
                salt=f"llm-{idx}",
            )
        )

    if not claims:
        return None

    skill = chain.canonical_skill_name or chain.skill_name or "this skill"
    project = chain.project_title or "this project"
    summary = str(parsed.get("overall_summary") or "").strip()
    safe_summary = _safe_text(summary) if summary else _overall_summary(
        skill, project, claims, ceiling
    )
    return SynthesisResult(
        chain_id=chain.chain_id,
        skill_name=chain.skill_name,
        canonical_skill_name=chain.canonical_skill_name,
        project_title=chain.project_title,
        claims=tuple(claims),
        overall_summary=safe_summary,
        limitations=tuple(_safe_text(limit) for limit in chain.limitations),
        public_safe=chain.public_safe,
        source="llm",
        artifacts=chain.artifacts,
    )


# ── Provider resolution (provider-agnostic; Anthropic never required) ──────────


def _anthropic_llm_fn() -> LlmFn | None:
    """Resolve the Anthropic client into an ``LlmFn``, or ``None`` if unconfigured.

    Returns ``None`` unless BOTH ``ANTHROPIC_API_KEY`` and ``AI_REVIEWER_MODEL`` are
    set, so Anthropic is *optional only* — never required by default. Local dev and
    the whole test suite run with zero credentials and never touch the network.
    """
    if not settings.anthropic_configured:
        return None

    def _call(system_prompt: str, user_message: str) -> str | None:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
        response = client.messages.create(
            model=settings.ai_reviewer_model or "claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return (response.content[0].text or "").strip() if response.content else None

    return _call


def _local_openai_llm_fn() -> LlmFn | None:
    """An ``LlmFn`` that calls a local OpenAI-compatible ``/chat/completions``.

    Works unchanged against Ollama / vLLM / LM Studio (or any OpenAI-compatible
    server) by pointing ``LOCAL_LLM_BASE_URL`` / ``LOCAL_LLM_MODEL`` at it. Sends
    ``response_format={"type": "json_object"}`` to nudge JSON output, but if the
    server rejects that field it retries once without it — the caller parses JSON
    from the returned content either way and falls back safely if it is invalid.
    Returns ``None`` only if the endpoint/model is not configured.
    """
    base = (settings.local_llm_base_url or "").strip()
    model = (settings.local_llm_model or "").strip()
    if not base or not model:
        return None
    url = base.rstrip("/") + "/chat/completions"
    timeout = float(settings.llm_synthesis_timeout_seconds or 30)
    api_key = settings.local_llm_api_key.get_secret_value()

    def _call(system_prompt: str, user_message: str) -> str | None:
        import httpx

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        base_body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0,
        }
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                url,
                json={**base_body, "response_format": {"type": "json_object"}},
                headers=headers,
            )
            if resp.status_code == 400:
                # Some local servers/models don't support response_format — retry
                # once without it; we parse JSON from the content regardless.
                resp = client.post(url, json=base_body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return None
        message = choices[0].get("message") or {}
        content = message.get("content")
        return content.strip() if isinstance(content, str) else None

    return _call


def _resolve_llm_fn() -> LlmFn | None:
    """Pick the configured provider's ``LlmFn``, or ``None`` for deterministic-only.

    ``None`` means "use the deterministic fallback for every chain". The layer is
    off (→ ``None``) unless ``LLM_SYNTHESIS_ENABLED`` is true, and Anthropic is only
    ever used when explicitly selected AND configured — so nothing reaches the
    network unless deliberately turned on.
    """
    if not settings.llm_synthesis_enabled:
        return None
    provider = (settings.llm_synthesis_provider or "disabled").strip().lower()
    if provider == "local_openai":
        return _local_openai_llm_fn()
    if provider == "anthropic":
        return _anthropic_llm_fn()
    return None  # "disabled" or any unknown value → deterministic only


def _provider_signature() -> str:
    """Identity of the active provider/model — part of the per-run cache key.

    Keeps cache entries from one provider/model from being reused for another in the
    same run (a different model is a different synthesis).
    """
    return ":".join(
        (
            str(settings.llm_synthesis_enabled),
            (settings.llm_synthesis_provider or "disabled").strip().lower(),
            settings.local_llm_model or "",
            settings.ai_reviewer_model or "",
        )
    )


def _resolved_concurrency() -> int:
    """Configured bounded-parallel concurrency (defaults to 1 when unset/invalid)."""
    try:
        return max(1, int(settings.llm_synthesis_max_concurrency or 1))
    except (TypeError, ValueError):
        return 1


def _resolved_max_chains() -> int | None:
    """Max chains that may use the LLM per run; ``None`` means unlimited."""
    raw = settings.llm_synthesis_max_chains_per_run
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return max(0, value)


# ── Public API ────────────────────────────────────────────────────────────────


# A per-run cache: (chain_id, sorted evidence ids, provider signature) -> result.
_SynthesisCache = dict[tuple[str, tuple[str, ...], str], SynthesisResult]


def _cache_key(chain: LinkedProofChain, signature: str) -> tuple[str, tuple[str, ...], str]:
    return (chain.chain_id, tuple(sorted(chain.linked_evidence_ids)), signature)


def synthesize_chain(
    chain: LinkedProofChain,
    *,
    llm_fn: LlmFn | None = None,
    force_deterministic: bool = False,
    cache: _SynthesisCache | None = None,
    cache_signature: str = "",
) -> SynthesisResult:
    """Synthesize ONE deterministic linked proof chain into recruiter-readable claims.

    Runs strictly after Steps 2/3. ``llm_fn`` is injected for testability: when it is
    ``None`` the configured provider is resolved (and resolves to ``None`` — i.e.
    deterministic — unless ``LLM_SYNTHESIS_ENABLED`` is true and a provider is set up,
    so tests stay offline). If the LLM is disabled, unavailable, raises, returns
    invalid/unsafe JSON, or yields no usable claim, the deterministic rule-based
    synthesis is returned instead — the call never fails.

    ``force_deterministic`` skips the LLM entirely (used to cap LLM usage per run).
    ``cache`` is an optional per-run cache keyed by chain id + evidence ids +
    ``cache_signature`` so an identical chain is only synthesized once per run.
    """
    ceiling = _ceiling_tier(chain)

    if cache is not None:
        key = _cache_key(chain, cache_signature)
        cached = cache.get(key)
        if cached is not None:
            return cached

    fallback = _deterministic_synthesis(chain, ceiling)

    use_fn = None if force_deterministic else (
        llm_fn if llm_fn is not None else _resolve_llm_fn()
    )

    result = fallback
    if use_fn is not None:
        try:
            raw = use_fn(_SYSTEM_PROMPT, _build_user_message(chain))
        except Exception:  # noqa: BLE001 — fail closed: any LLM error → deterministic
            logger.exception(
                "LLM proof synthesis call failed; using deterministic fallback"
            )
            raw = None
        if raw:
            parsed = _parse_llm_synthesis(raw, chain, ceiling)
            if parsed is not None:
                result = parsed

    if cache is not None:
        cache[_cache_key(chain, cache_signature)] = result
    return result


def synthesize_linked_chains(
    chains: list[LinkedProofChain],
    *,
    llm_fn: LlmFn | None = None,
) -> list[SynthesisResult]:
    """Synthesize a list of linked proof chains (Step 3 output) in input order.

    Sequential and safe to call from inside a request handler. Each chain runs
    through the same per-chain pipeline, so one chain's LLM failure only falls that
    chain back deterministically — it never aborts the run. Chains beyond
    ``LLM_SYNTHESIS_MAX_CHAINS_PER_RUN`` still get a deterministic synthesis (the LLM
    is simply not used for them). A per-run cache dedupes identical chains.
    """
    resolved = llm_fn if llm_fn is not None else _resolve_llm_fn()
    cap = _resolved_max_chains()
    signature = _provider_signature()
    cache: _SynthesisCache = {}
    results: list[SynthesisResult] = []
    for idx, chain in enumerate(chains):
        results.append(
            synthesize_chain(
                chain,
                llm_fn=resolved,
                force_deterministic=cap is not None and idx >= cap,
                cache=cache,
                cache_signature=signature,
            )
        )
    return results


async def synthesize_linked_chains_async(
    chains: list[LinkedProofChain],
    *,
    llm_fn: LlmFn | None = None,
    concurrency: int | None = None,
    max_chains: int | None = None,
) -> list[SynthesisResult]:
    """Bounded-parallel synthesis of independent chains, preserving input order.

    Independent chains synthesize concurrently under an :class:`asyncio.Semaphore`
    (``concurrency`` defaults to ``LLM_SYNTHESIS_MAX_CONCURRENCY``, itself 1 unless
    raised via env). Each chain runs through the same per-chain pipeline in a worker
    thread, so a slow/failed provider on one chain only falls THAT chain back — it
    never aborts the others — and the returned list is always in input order. Chains
    beyond the per-run cap get a deterministic synthesis. A shared per-run cache
    dedupes identical chains.
    """
    resolved = llm_fn if llm_fn is not None else _resolve_llm_fn()
    limit = _resolved_concurrency() if concurrency is None else max(1, int(concurrency))
    cap = _resolved_max_chains() if max_chains is None else max_chains
    signature = _provider_signature()
    cache: _SynthesisCache = {}
    semaphore = asyncio.Semaphore(limit)

    async def _run(index: int, chain: LinkedProofChain) -> tuple[int, SynthesisResult]:
        async with semaphore:
            result = await asyncio.to_thread(
                synthesize_chain,
                chain,
                llm_fn=resolved,
                force_deterministic=cap is not None and index >= cap,
                cache=cache,
                cache_signature=signature,
            )
        return index, result

    pairs = await asyncio.gather(
        *(_run(i, chain) for i, chain in enumerate(chains))
    )
    # Restore deterministic input order even though chains ran concurrently.
    return [result for _, result in sorted(pairs, key=lambda p: p[0])]


def synthesize_linked_chains_bounded(
    chains: list[LinkedProofChain],
    *,
    llm_fn: LlmFn | None = None,
) -> list[SynthesisResult]:
    """Sync entry point that drives the BOUNDED-CONCURRENCY orchestrator.

    This is the production integration point: it runs
    :func:`synthesize_linked_chains_async` so the configured
    ``LLM_SYNTHESIS_MAX_CONCURRENCY`` is actually honoured, while staying safe to
    call from a synchronous service function (the proof-synthesis agent). It
    preserves deterministic input order, per-chain fallback, and the per-run cache,
    exactly like the async orchestrator.

    Event-loop safety: a synchronous FastAPI handler runs in a worker thread with no
    running loop, so we drive the coroutine with :func:`asyncio.run`. If a loop *is*
    already running in this thread (we were called from async code), we run the
    orchestrator to completion on a dedicated worker thread with its own loop —
    never calling ``asyncio.run`` inside a live loop, which would raise.
    """
    if not chains:
        return []

    def _drive() -> list[SynthesisResult]:
        return asyncio.run(synthesize_linked_chains_async(chains, llm_fn=llm_fn))

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running event loop in this thread → safe to drive directly.
        return _drive()
    # A loop is already running here; offload to a separate thread with its own loop.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_drive).result()
