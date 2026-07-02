"""Evidence Normalization Engine — ONE clean internal evidence shape.

Every proof surface speaks its own dialect: the Student Proof Vault renders a
GitHub code item, a hydrated Website workflow, a Defense skill, a Video chip and
a Skill-Graph row as differently-shaped (already-safe) dicts, while a Document is
modelled as a "corroboration card". The Proof Synthesis Agent (and, later, the
Step-3 cross-proof linker) should not have to re-learn each of those shapes.

This module collapses all of them into a single internal type —
:class:`NormalizedEvidenceArtifact` — so downstream consumers reason over one
uniform evidence model instead of six messy ones. It is a *pure, deterministic*
adapter: it never re-reads source tables, never calls an LLM, and never invents a
field. It only re-projects fields the Vault already scrubbed.

Product rules preserved verbatim:

* **GitHub proves implementation.** Precise, line-level GitHub code becomes
  ``proof_strength == "precise_code"``; a repository-level row (no located line)
  is the *fallback only*, ``proof_strength == "repo_level"`` — never upgraded.
* **Website proves runtime behaviour** (``"runtime_behavior"``), **Defense proves
  understanding** (``"self_explanation"``), **Video corroborates a moment**
  (``"supporting_moment"``), **Skill Graph is aggregated** (``"aggregated"``).
* **Documents corroborate — never primary proof.** A document is always
  ``proof_strength == "corroboration"`` and ``public_safe == False``; it can never
  be promoted into implementation proof.

Safety: a normalized artifact carries ONLY already-safe fields. The internal
representation (:meth:`NormalizedEvidenceArtifact.to_dict`) may include the safe
source ``source_id`` and safe locators (repo-relative path, line numbers, public
URLs). The public-safe projection (:meth:`NormalizedEvidenceArtifact.public_view`)
additionally strips the private ``source_id`` and all internal ``metadata`` — so
no raw transcript / document text / DOM / OCR / provider JSON / storage path /
signed URL / private id can ever appear in public-safe output. Only a genuinely
public URL survives into the public projection.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from app.services.github_python_evidence_focus import (
    GRADE_IMPLEMENTATION_BODY,
    is_skill_implementation_relevance,
    is_weak_grade,
)
from app.services.project_defense_evidence_chips import _sanitize_transcript_text
from app.services.safe_public_url import is_safe_public_url
from app.services.skill_normalization import canonical_skill
from app.services.vbr_student_report import _scrub_score_fragments, _trace_text
from app.services.website_skill_proof_focus import (
    ALLOWED_WEBSITE_EVIDENCE_CHIPS,
    ALLOWED_WEBSITE_PURPOSE_KEYS,
    ALLOWED_WEBSITE_RELEVANCE_KEYS,
    describe_website_purpose,
    describe_website_skill_relevance,
    public_screenshot_access_label,
    website_behavior_claim,
    website_corroboration_note,
)

# ── Source types (one per proof surface) ──────────────────────────────────────
SOURCE_GITHUB = "github"
SOURCE_WEBSITE = "website"
SOURCE_DOCUMENT = "document"
SOURCE_DEFENSE = "defense"
SOURCE_VIDEO = "video"
SOURCE_SKILL_GRAPH = "skill_graph"

# Recruiter-facing source labels (mirror the Vault / report badges exactly).
_SOURCE_LABELS = {
    SOURCE_GITHUB: "GitHub Proof",
    SOURCE_WEBSITE: "Website Proof",
    SOURCE_DOCUMENT: "Document Proof",
    SOURCE_DEFENSE: "Project Defense",
    SOURCE_VIDEO: "Video Evidence",
    SOURCE_SKILL_GRAPH: "Skill Graph",
}

# ── Proof strength (qualitative — NEVER a numeric score), strongest → weakest ──
STRENGTH_PRECISE_CODE = "precise_code"  # GitHub line/function-level implementation
STRENGTH_RUNTIME = "runtime_behavior"  # Website workflow at inspection time
STRENGTH_SELF_EXPLANATION = "self_explanation"  # Project Defense understanding
STRENGTH_SUPPORTING_MOMENT = "supporting_moment"  # Video chip
STRENGTH_REPO_LEVEL = "repo_level"  # GitHub fallback — no precise line located
STRENGTH_AGGREGATED = "aggregated"  # Skill Graph pipeline summary
STRENGTH_CORROBORATION = "corroboration"  # Document — supporting, never primary

# Whitelisted safe locator keys copied into a GitHub artifact's internal metadata.
# Each is already safe (repo-relative path, ints, public-only URLs, deterministic
# reason text). Never a raw snapshot, DOM, OCR dump or provider payload.
_GITHUB_META_KEYS = (
    "file_path",
    "line_start",
    "line_end",
    "function_name",
    "commit_sha",
    "github_line_url",
    "repo_url",
    "evidence_kind",
    "evidence_strength",
    "selection_reason",
    "skill_graph_node",
    "display_mode",
    # The deterministic Smart-Evidence quality band (implementation_body /
    # supporting_logic / … / repo_level_fallback). Carried so the Synthesis Agent
    # can distinguish primary implementation code from weaker precise lines.
    "evidence_quality_grade",
    # Closed-vocabulary semantic keys resolved at hydration against the report's
    # selected skill (never stored text): what the block does, and how it relates
    # to THIS skill. Carried so the Synthesis Agent can require skill-relevant
    # implementation before treating a body as primary proof.
    "code_block_purpose_key",
    "skill_relevance_key",
)

__all__ = [
    "NormalizedEvidenceArtifact",
    "SOURCE_GITHUB",
    "SOURCE_WEBSITE",
    "SOURCE_DOCUMENT",
    "SOURCE_DEFENSE",
    "SOURCE_VIDEO",
    "SOURCE_SKILL_GRAPH",
    "STRENGTH_PRECISE_CODE",
    "STRENGTH_RUNTIME",
    "STRENGTH_SELF_EXPLANATION",
    "STRENGTH_SUPPORTING_MOMENT",
    "STRENGTH_REPO_LEVEL",
    "STRENGTH_AGGREGATED",
    "STRENGTH_CORROBORATION",
    "normalize_report_item",
    "normalize_document_correlation",
    "normalize_chain",
    "normalize_skill_report",
    "has_precise_code",
    "has_implementation_body",
    "has_source",
]


# ── The one internal evidence model ───────────────────────────────────────────


@dataclass(frozen=True)
class NormalizedEvidenceArtifact:
    """One proof, normalized into a single uniform internal shape.

    ``metadata`` holds ONLY already-safe internal locators (whitelisted per
    source). The public-safe projection (:meth:`public_view`) drops it together
    with the private ``source_id`` so it never reaches a recruiter-facing report.
    """

    evidence_id: str
    source_type: str
    skill_name: str | None
    canonical_skill_name: str | None
    subskill_name: str | None
    project_id: str | None
    project_title: str | None
    source_id: str
    source_label: str
    exact_location: str | None
    safe_summary: str
    proof_strength: str
    public_safe: bool
    limitations: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Full INTERNAL representation (safe locators + safe source id)."""
        return {
            "evidence_id": self.evidence_id,
            "source_type": self.source_type,
            "skill_name": self.skill_name,
            "canonical_skill_name": self.canonical_skill_name,
            "subskill_name": self.subskill_name,
            "project_id": self.project_id,
            "project_title": self.project_title,
            "source_id": self.source_id,
            "source_label": self.source_label,
            "exact_location": self.exact_location,
            "safe_summary": self.safe_summary,
            "proof_strength": self.proof_strength,
            "public_safe": self.public_safe,
            "limitations": list(self.limitations),
            "metadata": dict(self.metadata),
        }

    def public_view(self) -> dict[str, Any]:
        """PUBLIC-SAFE projection — no private ids, no internal metadata.

        Strips ``source_id`` and the whole ``metadata`` bag (which could carry
        internal locators), keeping only the recruiter-safe summary fields — and
        each retained string (``safe_summary``, ``exact_location``, every
        ``limitation``) is additionally re-scrubbed with the canonical
        sensitive-data scrubber so no token / signed URL / storage or local path
        can leak even if a hostile upstream item smuggled one in. A genuinely
        public URL (and only that) survives, so a public report can still
        deep-link to the GitHub line or the live deployment.
        """
        public_url = self.metadata.get("github_line_url") or self.metadata.get("public_url")
        if not (public_url and self.public_safe and is_safe_public_url(str(public_url))):
            public_url = None
        # Website semantic proof labels: only a KEY from the closed vocabularies
        # survives (fail-closed — an arbitrary/stale key is dropped), and the
        # public label is DERIVED from that vocabulary at projection time — never
        # echoed from stored text. The relevance label interpolates only the
        # already-public canonical skill name.
        purpose_key = str(self.metadata.get("website_purpose_key") or "") or None
        if purpose_key not in ALLOWED_WEBSITE_PURPOSE_KEYS:
            purpose_key = None
        relevance_key = str(self.metadata.get("website_skill_relevance_key") or "") or None
        if relevance_key not in ALLOWED_WEBSITE_RELEVANCE_KEYS:
            relevance_key = None
        # Re-scrub every retained public string defensively: even though these
        # fields are meant to be already-safe, a hostile upstream item could have
        # smuggled a token / signed URL / storage or local path into them. The
        # private source_id and the whole metadata bag are dropped entirely.
        view = {
            "evidence_id": self.evidence_id,
            "source_type": self.source_type,
            "source_label": self.source_label,
            "canonical_skill_name": self.canonical_skill_name,
            "subskill_name": self.subskill_name,
            "project_title": self.project_title,
            "exact_location": _scrub_sensitive(self.exact_location),
            "safe_summary": _scrub_sensitive(self.safe_summary) or "",
            "proof_strength": self.proof_strength,
            "public_safe": self.public_safe,
            "limitations": [_scrub_sensitive(lim) for lim in self.limitations],
            "public_url": public_url,
        }
        # Website fields are only ever PRESENT on a website artifact carrying a
        # validated key (other artifacts never grow website-shaped keys).
        if purpose_key:
            view["website_purpose_key"] = purpose_key
            view["website_purpose_label"] = describe_website_purpose(purpose_key)
            # Recruiter-first behaviour claim — DERIVED from the validated
            # purpose key's closed vocabulary, never echoed from stored text.
            view["website_behavior_claim"] = website_behavior_claim(purpose_key)
        if relevance_key:
            view["website_skill_relevance_key"] = relevance_key
            view["website_skill_relevance_label"] = describe_website_skill_relevance(
                relevance_key, self.canonical_skill_name
            )
        # Website evidence-card extras (chips + screenshot access), each validated
        # against its closed vocabulary here — a smuggled chip is dropped and any
        # preview-shaped access label collapses to the permission-gated status.
        # The public card never carries preview URLs, page titles, or the
        # observed-behaviour narrative — only closed-vocabulary facts.
        chips = [
            str(c)
            for c in (self.metadata.get("website_evidence_chips") or [])
            if str(c) in ALLOWED_WEBSITE_EVIDENCE_CHIPS
        ]
        if chips:
            view["website_evidence_chips"] = chips
        if purpose_key or chips:
            available = bool(self.metadata.get("website_screenshot_available"))
            view["website_screenshot_available"] = available
            view["website_screenshot_access_label"] = public_screenshot_access_label(
                self.metadata.get("website_screenshot_access_label"),
                screenshot_available=available,
            )
            # Cross-proof corroboration: booleans only, and the public note is
            # RE-DERIVED from those booleans through the closed fragments —
            # stored note text is never echoed to the public surface.
            gh = bool(self.metadata.get("website_corroborates_github"))
            dfn = bool(self.metadata.get("website_corroborates_defense"))
            doc = bool(self.metadata.get("website_corroborates_document"))
            if gh or dfn or doc:
                view["website_corroborates_github"] = gh
                view["website_corroborates_defense"] = dfn
                view["website_corroborates_document"] = doc
                view["website_corroboration_note"] = website_corroboration_note(
                    has_github=gh, has_defense=dfn, has_document=doc
                )
        return view


# ── Small deterministic helpers ───────────────────────────────────────────────


def _evidence_id(source_type: str, source_id: str, location: str, summary: str) -> str:
    """Stable, non-leaking artifact id (a short hash, never a raw private id).

    Combines source type + source id + location + summary so two distinct GitHub
    code items from the SAME proof row get distinct ids, while the same artifact
    always hashes identically. The hash never reveals the underlying id.
    """
    raw = "␟".join((source_type, source_id, location or "", summary or ""))
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"ev_{source_type}_{digest}"


def _safe_text(value: Any, limit: int = 240) -> str:
    """Bound + score-scrub any summary text (defensive; the Vault already scrubs)."""
    return _trace_text(_scrub_score_fragments(str(value or "")), limit)


def _scrub_sensitive(value: str | None) -> str | None:
    """Defensively redact storage/auth/URL/path fragments from a public string.

    Every field retained by :meth:`NormalizedEvidenceArtifact.public_view`
    (``safe_summary``, ``exact_location``, each ``limitation``) is re-scrubbed with
    the canonical backend sensitive-data scrubber so a hostile upstream item can
    never leak an access/refresh token, a signed-URL query token, a Supabase /
    S3 / GCS storage URL, a local ``/Users/…`` or ``file://`` path, a private
    media/storage path, or a localhost/private callback through a public report.
    Deterministic (pure regex) — no LLM. ``None`` passes through unchanged.
    """
    if value is None:
        return None
    return _sanitize_transcript_text(str(value))


def _limitations(*values: Any) -> tuple[str, ...]:
    """De-duped, order-preserving tuple of non-empty limitation strings."""
    out: list[str] = []
    for v in values:
        text = str(v or "").strip()
        if text and text not in out:
            out.append(text)
    return tuple(out)


def _canon(skill_name: str | None) -> str | None:
    return canonical_skill(str(skill_name)) if skill_name else None


def _safe_metadata(item: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """Copy ONLY whitelisted, present, non-null safe locator keys."""
    meta: dict[str, Any] = {}
    for key in keys:
        val = item.get(key)
        if val not in (None, ""):
            meta[key] = val
    return meta


# ── Per-source normalizers (operate on already-safe report items) ─────────────


def _github_strength(item: dict[str, Any]) -> str:
    """Precise line-level code wins; everything else is the repo-level fallback.

    Mirrors the Vault/Synthesis rule exactly: a GitHub artifact is only treated as
    implementation-grade code when it is an explicit ``code_line`` row carrying
    located line evidence. Any other GitHub row (repo-level, weak-only) stays a
    fallback and is NEVER promoted to ``precise_code``.

    The Smart-Evidence quality band is the final gate: a precise line whose
    deterministic ``evidence_quality_grade`` is a WEAK band (``import_only`` /
    ``comment_or_docstring`` / ``config_or_constant`` / ``route_decorator_only`` /
    ``repo_level_fallback``) is not implementation-grade code — it stays the
    repo-level fallback so a stale import / docstring / constant / bare-decorator
    line can never be counted as precise implementation proof (and so can never
    inflate the Synthesis Agent's confidence tier). A row with no grade at all
    (unknown) keeps ``precise_code`` for backward compatibility.
    """
    if item.get("display_mode") == "code_line" and item.get("has_precise_line_evidence"):
        if is_weak_grade(item.get("evidence_quality_grade")):
            return STRENGTH_REPO_LEVEL
        return STRENGTH_PRECISE_CODE
    return STRENGTH_REPO_LEVEL


_STRENGTH_BY_SOURCE = {
    SOURCE_WEBSITE: STRENGTH_RUNTIME,
    SOURCE_DEFENSE: STRENGTH_SELF_EXPLANATION,
    SOURCE_VIDEO: STRENGTH_SUPPORTING_MOMENT,
    SOURCE_SKILL_GRAPH: STRENGTH_AGGREGATED,
}

# Vault proof-type label → normalized source type.
_PROOF_TYPE_TO_SOURCE = {
    "GitHub Proof": SOURCE_GITHUB,
    "Website Proof": SOURCE_WEBSITE,
    "Document Proof": SOURCE_DOCUMENT,
    "Project Defense": SOURCE_DEFENSE,
    "Video Evidence": SOURCE_VIDEO,
    "Skill Graph": SOURCE_SKILL_GRAPH,
}


def normalize_report_item(
    item: dict[str, Any],
    *,
    skill_name: str | None = None,
    project_id: str | None = None,
    project_title: str | None = None,
) -> NormalizedEvidenceArtifact | None:
    """Normalize ONE safe Vault report item (GitHub/Website/Defense/Video/Skill
    Graph) into a :class:`NormalizedEvidenceArtifact`.

    Returns ``None`` for an unrecognised/document item (documents are normalized
    via :func:`normalize_document_correlation`, since the chain models them as
    corroboration cards rather than report items).
    """
    source_type = _PROOF_TYPE_TO_SOURCE.get(str(item.get("proof_type") or ""))
    if source_type is None or source_type == SOURCE_DOCUMENT:
        return None

    skill = skill_name or item.get("skill_name")
    source_id = str(item.get("source_id") or "")
    location = item.get("safe_location")
    summary = _safe_text(item.get("safe_summary"))

    if source_type == SOURCE_GITHUB:
        strength = _github_strength(item)
        metadata = _safe_metadata(item, _GITHUB_META_KEYS)
        subskill = item.get("subskill_name")
    else:
        strength = _STRENGTH_BY_SOURCE[source_type]
        metadata = {}
        subskill = None
        if source_type == SOURCE_WEBSITE and item.get("public_url"):
            metadata["public_url"] = item.get("public_url")
        if source_type == SOURCE_WEBSITE:
            # Website semantic proof KEYS only (closed vocabularies, validated
            # again at public projection time) — never the free-text summaries.
            for key in ("website_purpose_key", "website_skill_relevance_key"):
                if item.get(key):
                    metadata[key] = str(item.get(key))
            # Evidence-card extras: closed-vocabulary basis chips + screenshot
            # availability/access. Chips are filtered against the closed set
            # already here; the free-text card fields (narrative, page title,
            # derived sentences) deliberately never enter the metadata bag.
            card = item.get("website_evidence_card")
            if isinstance(card, dict):
                chips = [
                    str(c)
                    for c in (card.get("evidence_basis_chips") or [])
                    if str(c) in ALLOWED_WEBSITE_EVIDENCE_CHIPS
                ]
                if chips:
                    metadata["website_evidence_chips"] = chips
                metadata["website_screenshot_available"] = bool(card.get("screenshot_available"))
                metadata["website_screenshot_access_label"] = str(
                    card.get("screenshot_access_label") or ""
                )
                # Corroboration BOOLEANS only — the note itself is re-derived
                # from these at projection time, never carried as text.
                for corr in (
                    "corroborates_github",
                    "corroborates_defense",
                    "corroborates_document",
                ):
                    metadata[f"website_{corr}"] = bool(card.get(corr))
        if source_type == SOURCE_DEFENSE and item.get("question_text"):
            metadata["question_text"] = _safe_text(item.get("question_text"), 160)
        if source_type == SOURCE_VIDEO and item.get("timestamp_label"):
            metadata["timestamp_label"] = item.get("timestamp_label")

    pid = project_id if project_id is not None else (item.get("attached_project_ids") or [None])[0]
    return NormalizedEvidenceArtifact(
        evidence_id=_evidence_id(source_type, source_id, str(location or ""), summary),
        source_type=source_type,
        skill_name=str(skill) if skill else None,
        canonical_skill_name=_canon(skill),
        subskill_name=str(subskill) if subskill else None,
        project_id=pid,
        project_title=project_title,
        source_id=source_id,
        source_label=_SOURCE_LABELS[source_type],
        exact_location=location,
        safe_summary=summary,
        proof_strength=strength,
        public_safe=bool(item.get("public_safe")),
        limitations=_limitations(item.get("limitation")),
        metadata=metadata,
    )


def normalize_document_correlation(
    card: dict[str, Any],
    *,
    skill_name: str | None = None,
    project_id: str | None = None,
    project_title: str | None = None,
) -> NormalizedEvidenceArtifact:
    """Normalize ONE Document corroboration card into a corroboration-only artifact.

    A document is ALWAYS ``proof_strength == "corroboration"`` and
    ``public_safe == False`` — it supports stronger evidence but can never be
    promoted into primary implementation proof. The page/section ``citation`` and
    correlation confidence are kept as safe internal metadata.
    """
    source_id = str(card.get("source_id") or "")
    location = (
        card.get("citation")
        or card.get("section_label")
        or (f"Page {card['page_number']}" if card.get("page_number") else None)
    )
    summary = _safe_text(card.get("reason"))
    metadata: dict[str, Any] = {}
    for key in ("page_number", "section_label", "citation", "corroborates", "correlation_confidence"):
        val = card.get(key)
        if val not in (None, ""):
            metadata[key] = val
    return NormalizedEvidenceArtifact(
        evidence_id=_evidence_id(SOURCE_DOCUMENT, source_id, str(location or ""), summary),
        source_type=SOURCE_DOCUMENT,
        skill_name=str(skill_name) if skill_name else None,
        canonical_skill_name=_canon(skill_name),
        subskill_name=None,
        project_id=project_id,
        project_title=project_title,
        source_id=source_id,
        source_label=_SOURCE_LABELS[SOURCE_DOCUMENT],
        exact_location=location,
        safe_summary=summary,
        proof_strength=STRENGTH_CORROBORATION,
        # Documents are never publicly linkable; only a safe citation is shown.
        public_safe=False,
        limitations=_limitations(card.get("limitation")),
        metadata=metadata,
    )


# ── Chain / report level normalization ────────────────────────────────────────


def normalize_chain(
    chain: dict[str, Any], skill_name: str | None = None
) -> list[NormalizedEvidenceArtifact]:
    """Normalize every evidence item inside ONE proof chain into the uniform model.

    Walks the chain's GitHub / Website / Defense / Video report items and Document
    corroboration cards, returning a flat list of artifacts (strongest source
    types first: GitHub → Website → Defense → Video → Document). Pure — it mutates
    nothing and re-reads no source table.
    """
    project_id = chain.get("project_id")
    project_title = chain.get("project_title")
    artifacts: list[NormalizedEvidenceArtifact] = []

    for key in ("github_evidence", "website_evidence", "defense_evidence", "video_evidence"):
        for item in chain.get(key) or []:
            art = normalize_report_item(
                item,
                skill_name=skill_name,
                project_id=project_id,
                project_title=project_title,
            )
            if art is not None:
                artifacts.append(art)

    for card in chain.get("document_correlations") or []:
        artifacts.append(
            normalize_document_correlation(
                card,
                skill_name=skill_name,
                project_id=project_id,
                project_title=project_title,
            )
        )
    return artifacts


def normalize_skill_report(report: dict[str, Any]) -> list[NormalizedEvidenceArtifact]:
    """Normalize an ENTIRE Skill Report into one flat list of artifacts.

    Covers both the project-anchored chains (``report["projects"]``) and any
    standalone Skill-Graph rows (``report["skill_graph"]``) that live outside a
    chain, so a caller gets the student's whole normalized evidence set for the
    skill in one uniform shape. Deterministic; no source-table reads, no LLM.
    """
    skill = report.get("skill")
    artifacts: list[NormalizedEvidenceArtifact] = []
    for chain in report.get("projects") or []:
        artifacts.extend(normalize_chain(chain, skill))

    # Skill-Graph rows are aggregated evidence that isn't part of a proof chain.
    for item in report.get("skill_graph") or []:
        art = normalize_report_item(item, skill_name=skill)
        if art is not None:
            artifacts.append(art)
    return artifacts


# ── Boolean source helpers (for the Synthesis Agent's tiering) ────────────────


def has_precise_code(artifacts: list[NormalizedEvidenceArtifact]) -> bool:
    """True when any normalized GitHub artifact is precise, line-level code."""
    return any(a.proof_strength == STRENGTH_PRECISE_CODE for a in artifacts)


def has_implementation_body(artifacts: list[NormalizedEvidenceArtifact]) -> bool:
    """True when any precise GitHub artifact is a real, SKILL-RELEVANT
    implementation *body*.

    The strongest GitHub proof band: a located function/method/class body (Smart
    Evidence grade ``implementation_body``), as opposed to merely ``supporting_logic``
    or a weaker precise line — AND its hydration-time ``skill_relevance_key`` must
    mark it as the selected skill's own implementation work. A cross-skill
    implementation row (React UI code in a Machine Learning report), product-UI /
    deployment context, or a row with no resolved relevance at all FAILS CLOSED, so
    the Synthesis Agent never treats code for a different skill as *primary*
    implementation proof for this one.
    """
    return any(
        a.source_type == SOURCE_GITHUB
        and a.proof_strength == STRENGTH_PRECISE_CODE
        and a.metadata.get("evidence_quality_grade") == GRADE_IMPLEMENTATION_BODY
        and is_skill_implementation_relevance(a.metadata.get("skill_relevance_key"))
        for a in artifacts
    )


def has_source(artifacts: list[NormalizedEvidenceArtifact], *source_types: str) -> bool:
    """True when any artifact has one of the given ``source_types``."""
    wanted = set(source_types)
    return any(a.source_type in wanted for a in artifacts)
