"""VeriBridge Proof Synthesis Agent — connects evidence into proof *chains*.

The Student Proof Vault Skill Report (:mod:`student_proof_vault_service`) already
collects every safe, owned proof for one skill and groups it into project-anchored
chains (GitHub code + Website runtime + Project Defense/Video + Document
corroboration). This module is the **synthesis layer** on top of that: it does not
re-read source tables and never exposes anything the Skill Report has not already
scrubbed. Instead it *reasons across* the already-safe evidence of one skill to
produce a connected, recruiter-verifiable synthesis:

* a qualitative **confidence tier** per chain — never a numeric score —
  (``Strongly corroborated`` / ``Corroborated`` / ``Supporting evidence`` /
  ``Needs review`` / ``Insufficient evidence``);
* a deterministic **synthesis result** + per-source **synthesis statements**,
  where every statement cites the real evidence ``source_id``\\s it is built from
  (the agent can never invent evidence — it only references provided IDs);
* a plain-language **why_linked** explaining why these independent sources refer
  to the same project/skill (project attachment, repo match, title match);
* the **subskills** the chain's GitHub evidence surfaced;
* a re-classification of unattached/standalone proofs into a capped
  **unlinked supporting evidence** bucket, so unrelated evidence is never forced
  into a strong chain.

The agent is **deterministic-first**: grouping and tiering never call an LLM. An
LLM may later be used ONLY to polish ``synthesis_result`` prose from the same
provided evidence IDs (it must never add evidence); if no LLM utility/credential
is available the deterministic synthesis is returned as-is. Product rule honored
throughout: GitHub proves implementation, Website proves runtime behavior, Defense
proves understanding, and Documents *corroborate* — they are never primary proof.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Recruiter-facing proof-source labels (mirror student_proof_vault_service).
PROOF_GITHUB = "GitHub Proof"
PROOF_DOCUMENT = "Document Proof"
PROOF_WEBSITE = "Website Proof"
PROOF_DEFENSE = "Project Defense"
PROOF_VIDEO = "Video Evidence"
PROOF_SKILL_GRAPH = "Skill Graph"

# Qualitative confidence tiers (NEVER a numeric score), strongest → weakest.
TIER_STRONG = "Strongly corroborated"
TIER_CORROBORATED = "Corroborated"
TIER_SUPPORTING = "Supporting evidence"
TIER_NEEDS_REVIEW = "Needs review"
TIER_INSUFFICIENT = "Insufficient evidence"

# Unlinked supporting evidence is capped so the report never dumps every loose
# proof; the overflow is reported as ``more_count``.
_MAX_UNLINKED_ITEMS = 6

__all__ = [
    "build_skill_proof_synthesis",
    "synthesize_skill_report",
    "TIER_STRONG",
    "TIER_CORROBORATED",
    "TIER_SUPPORTING",
    "TIER_NEEDS_REVIEW",
    "TIER_INSUFFICIENT",
]


# ── Evidence helpers (operate ONLY on already-safe Skill Report items) ────────


def _has_precise_code(github: list[dict[str, Any]]) -> bool:
    """True when a chain carries precise, line-level GitHub code evidence."""
    return any(
        g.get("display_mode") == "code_line" and g.get("has_precise_line_evidence")
        for g in github
    )


def _github_location(item: dict[str, Any]) -> str:
    """Human "file · lines/function" label for a GitHub code item (already safe)."""
    fp = item.get("file_path") or "repo-level"
    if item.get("function_name"):
        return f"{fp} · {item['function_name']}()"
    if item.get("line_start"):
        end = item.get("line_end")
        suffix = f"-{end}" if end and end != item["line_start"] else ""
        return f"{fp} · lines {item['line_start']}{suffix}"
    return fp


def _chain_evidence_ids(chain: dict[str, Any]) -> set[str]:
    """Every real evidence ``source_id`` present in a chain (anti-fabrication set).

    A synthesis statement may ONLY cite ids drawn from here, so the agent can
    never reference evidence that is not actually in the chain.
    """
    ids: set[str] = set()
    for key in ("github_evidence", "website_evidence", "defense_evidence", "video_evidence"):
        for e in chain.get(key) or []:
            sid = str(e.get("source_id") or "")
            if sid:
                ids.add(sid)
    for d in chain.get("document_correlations") or []:
        sid = str(d.get("source_id") or "")
        if sid:
            ids.add(sid)
    return ids


# ── Confidence tier (qualitative, deterministic) ──────────────────────────────


def _confidence_tier(
    *,
    has_precise_code: bool,
    has_github_any: bool,
    has_website: bool,
    has_defense: bool,
    has_document: bool,
    has_skill_graph: bool,
) -> str:
    """Map a chain's source mix to a qualitative tier — never a numeric score.

    Independent *strong* sources are: precise GitHub code (implementation), a
    Website runtime workflow (behaviour), and a Project Defense/Video
    (understanding). Documents corroborate but are never counted as a strong,
    independent source on their own.
    """
    strong = [
        name
        for name, present in (
            ("github_code", has_precise_code),
            ("website", has_website),
            ("defense", has_defense),
        )
        if present
    ]
    if len(strong) >= 2:
        # Two+ independent strong sources, anchored by real code → strongest.
        return TIER_STRONG if "github_code" in strong else TIER_CORROBORATED
    if len(strong) == 1:
        # One strong source plus a corroborating document reads as corroborated.
        return TIER_CORROBORATED if has_document else TIER_SUPPORTING
    if has_github_any or has_document or has_skill_graph:
        # Only repo-level GitHub, documents, or aggregated graph evidence → review.
        return TIER_NEEDS_REVIEW
    return TIER_INSUFFICIENT


# ── Synthesis statements (each cites the evidence ids it is built from) ────────


def _build_statements(
    skill: str, chain: dict[str, Any], allowed_ids: set[str]
) -> list[dict[str, Any]]:
    """Deterministic, evidence-cited statements for one chain.

    Each statement references the concrete ``evidence_ids`` it summarizes; the
    caller asserts every cited id is in ``allowed_ids`` so the agent can never
    fabricate evidence.
    """
    statements: list[dict[str, Any]] = []

    def _add(text: str, source: str, ids: list[str]) -> None:
        cited = [i for i in ids if i in allowed_ids]
        if cited:
            statements.append({"text": text, "source": source, "evidence_ids": cited})

    for g in chain.get("github_evidence") or []:
        sid = str(g.get("source_id") or "")
        if g.get("display_mode") == "code_line" and g.get("has_precise_line_evidence"):
            reason = g.get("selection_reason") or g.get("safe_summary") or "skill-relevant logic"
            _add(
                f"GitHub code at {_github_location(g)} shows {reason}.",
                PROOF_GITHUB,
                [sid],
            )
        else:
            _add(
                "GitHub repository evidence supports this skill at repository level "
                "(no precise line-level code located).",
                PROOF_GITHUB,
                [sid],
            )

    for w in chain.get("website_evidence") or []:
        sid = str(w.get("source_id") or "")
        behaviour = w.get("workflow_summary") or w.get("safe_summary") or "the working deployment"
        _add(
            f"A recorded website workflow demonstrates runtime behaviour: {behaviour}",
            PROOF_WEBSITE,
            [sid],
        )

    defense_ids = [
        str(e.get("source_id") or "")
        for e in (chain.get("defense_evidence") or []) + (chain.get("video_evidence") or [])
    ]
    defense_ids = [i for i in defense_ids if i]
    if defense_ids:
        _add(
            "The candidate explained this work in the Project Defense, evidencing personal understanding.",
            PROOF_DEFENSE,
            defense_ids,
        )

    for d in chain.get("document_correlations") or []:
        sid = str(d.get("source_id") or "")
        corro = d.get("corroborates") or "the implementation"
        _add(
            f"A document corroborates {corro} (supporting evidence, not primary proof).",
            PROOF_DOCUMENT,
            [sid],
        )

    return statements


def _synthesis_result(skill: str, project_title: str, tier: str, statements: list[dict[str, Any]]) -> str:
    """One safe sentence summarizing how the chain's sources corroborate the skill."""
    sources = sorted({s["source"] for s in statements})
    if not sources:
        return f"No connected evidence was found for {skill} in {project_title}."
    if len(sources) == 1:
        joined = sources[0]
    else:
        joined = ", ".join(sources[:-1]) + " and " + sources[-1]
    return (
        f"In {project_title}, {joined} independently corroborate {skill} "
        f"({tier.lower()})."
    )


def _why_linked(chain: dict[str, Any]) -> str:
    """Plain-language reason these sources are treated as the same project/skill."""
    title = chain.get("project_title") or "this project"
    grouped = int(chain.get("grouped_attempt_count", 1) or 1)
    collapsed = int(chain.get("collapsed_project_count", 1) or 1)
    base = (
        f"These sources are connected because they belong to the same project, "
        f"“{title}”, via project attachment, matching repository, and matching project title."
    )
    if grouped > 1 or collapsed > 1:
        base += " Repeated attempts for the same project were merged into one chain."
    return base


def _subskills(github: list[dict[str, Any]]) -> list[str]:
    """Distinct subskills the chain's canonical GitHub evidence named."""
    out: list[str] = []
    for g in github:
        name = str(g.get("subskill_name") or "").strip()
        if name and name not in out:
            out.append(name)
    return out


# ── Chain enrichment ──────────────────────────────────────────────────────────


def _enrich_chain(skill: str, chain: dict[str, Any]) -> dict[str, Any]:
    """Annotate one Skill Report chain in place with synthesis fields.

    Adds ``confidence_tier``, ``synthesis_result``, ``why_linked``, ``subskills``
    and evidence-cited ``synthesis_statements`` — the chain keeps every original
    field, so existing consumers are unaffected.
    """
    github = chain.get("github_evidence") or []
    website = chain.get("website_evidence") or []
    defense = (chain.get("defense_evidence") or []) + (chain.get("video_evidence") or [])
    documents = chain.get("document_correlations") or []

    tier = _confidence_tier(
        has_precise_code=_has_precise_code(github),
        has_github_any=bool(github),
        has_website=bool(website),
        has_defense=bool(defense),
        has_document=bool(documents),
        has_skill_graph=False,
    )
    allowed_ids = _chain_evidence_ids(chain)
    statements = _build_statements(skill, chain, allowed_ids)

    chain["confidence_tier"] = tier
    chain["subskills"] = _subskills(github)
    chain["synthesis_statements"] = statements
    chain["synthesis_result"] = _synthesis_result(
        skill, chain.get("project_title") or "this project", tier, statements
    )
    chain["why_linked"] = _why_linked(chain) if chain.get("attached") else (
        "Not attached to a VBR project — shown for context only."
    )
    return chain


# ── Unlinked supporting evidence (capped, never forced into a chain) ──────────


def _unlinked_card(proof_type: str, item: dict[str, Any], *, is_document: bool = False) -> dict[str, Any]:
    """A compact, safe card for a standalone proof that links to no chain."""
    if is_document:
        return {
            "proof_type": PROOF_DOCUMENT,
            "source_id": str(item.get("source_id") or ""),
            "title": item.get("document_title") or "Document",
            "safe_summary": item.get("reason") or "",
            "safe_location": item.get("citation")
            or (f"Page {item['page_number']}" if item.get("page_number") else None),
            "corroborates": item.get("corroborates") or "",
            "limitation": item.get("limitation") or "",
        }
    return {
        "proof_type": proof_type,
        "source_id": str(item.get("source_id") or ""),
        "title": item.get("title") or "",
        "safe_summary": item.get("workflow_summary") or item.get("safe_summary") or "",
        "safe_location": item.get("safe_location"),
        "corroborates": "",
        "limitation": item.get("limitation") or "",
    }


def _build_unlinked(report: dict[str, Any]) -> dict[str, Any]:
    """Flatten the Skill Report's standalone bucket into a capped unlinked list.

    Strong-first ordering (GitHub → Website → Defense → Video → Skill Graph →
    Documents). Documents come last because they only corroborate. Capped at
    :data:`_MAX_UNLINKED_ITEMS`, with the remainder reported as ``more_count``.
    """
    std = report.get("standalone_evidence") or {}
    cards: list[dict[str, Any]] = []
    for it in std.get("github") or []:
        cards.append(_unlinked_card(PROOF_GITHUB, it))
    for it in std.get("website") or []:
        cards.append(_unlinked_card(PROOF_WEBSITE, it))
    for it in std.get("defense") or []:
        cards.append(_unlinked_card(PROOF_DEFENSE, it))
    for it in std.get("video") or []:
        cards.append(_unlinked_card(PROOF_VIDEO, it))
    for it in std.get("skill_graph") or []:
        cards.append(_unlinked_card(PROOF_SKILL_GRAPH, it))
    for it in std.get("documents") or []:
        cards.append(_unlinked_card(PROOF_DOCUMENT, it, is_document=True))

    # Account for documents already truncated upstream (their own more_count).
    total = len(cards) + int(std.get("document_more_count", 0) or 0)
    shown = cards[:_MAX_UNLINKED_ITEMS]
    return {
        "items": shown,
        "count": total,
        "more_count": max(0, total - len(shown)),
    }


# ── Source coverage + overall summary ─────────────────────────────────────────


def _source_coverage(report: dict[str, Any]) -> dict[str, bool]:
    """Boolean coverage across the five evidence surfaces (no counts/scores)."""
    counts = report.get("source_counts") or {}
    return {
        "GitHub": bool(counts.get(PROOF_GITHUB)),
        "Website": bool(counts.get(PROOF_WEBSITE)),
        "Document": bool(counts.get(PROOF_DOCUMENT)),
        "Defense": bool(counts.get(PROOF_DEFENSE)),
        "Video": bool(counts.get(PROOF_VIDEO)),
    }


def _synthesis_summary(skill: str, chains: list[dict[str, Any]], coverage: dict[str, bool]) -> str:
    """A short, recruiter-facing summary of the whole synthesis (no numbers)."""
    covered = [name for name, present in coverage.items() if present]
    n = len(chains)
    if n == 0:
        if covered:
            return (
                f"{skill} has supporting evidence ({', '.join(covered)}) but none of it is "
                "connected into a project proof chain yet."
            )
        return f"No connected proof chains were found for {skill}."
    strongest = chains[0].get("confidence_tier", TIER_SUPPORTING)
    chain_word = "connected proof chain" if n == 1 else "connected proof chains"
    coverage_note = f" Evidence spans {', '.join(covered)}." if covered else ""
    return (
        f"{skill} is supported by {n} {chain_word}; the strongest is "
        f"{strongest.lower()}.{coverage_note}"
    )


# ── Public API ────────────────────────────────────────────────────────────────


def synthesize_skill_report(report: dict[str, Any]) -> dict[str, Any]:
    """Synthesize an already-built Skill Report dict into connected proof chains.

    Pure function over the safe :func:`collect_skill_report` output. Enriches each
    attached chain in place, builds the capped unlinked bucket, and returns the
    synthesis sub-report (``proof_chains`` / ``unlinked_supporting_evidence`` /
    ``synthesis_summary`` / ``source_coverage``). Called by ``collect_skill_report``
    to embed these fields; also reachable directly via :func:`build_skill_proof_synthesis`.
    """
    skill = str(report.get("skill") or "")
    # Enrich EVERY chain (attached + the standalone pseudo-chain) so each carries a
    # tier; the synthesis ``proof_chains`` are the project-anchored (attached) ones.
    for chain in report.get("projects") or []:
        _enrich_chain(skill, chain)

    proof_chains = [c for c in (report.get("projects") or []) if c.get("attached")]
    # Strongest tier first so the summary and UI lead with the best evidence.
    tier_rank = {
        TIER_STRONG: 0,
        TIER_CORROBORATED: 1,
        TIER_SUPPORTING: 2,
        TIER_NEEDS_REVIEW: 3,
        TIER_INSUFFICIENT: 4,
    }
    proof_chains = sorted(proof_chains, key=lambda c: tier_rank.get(c.get("confidence_tier"), 9))

    coverage = _source_coverage(report)
    unlinked = _build_unlinked(report)
    summary = _synthesis_summary(skill, proof_chains, coverage)

    return {
        "synthesis_summary": summary,
        "source_coverage": coverage,
        "proof_chains": proof_chains,
        "unlinked_supporting_evidence": unlinked,
    }


def build_skill_proof_synthesis(
    db: Any, pipeline_db: Any, user_id: str, skill_name: str
) -> dict[str, Any]:
    """Build the full proof-synthesis report for ONE skill.

    Collects the safe Skill Report (every owned proof for the skill, hydrated and
    scrubbed) and runs the synthesis agent over it. Returns the same dict
    ``collect_skill_report`` returns, now carrying the synthesis fields
    (``proof_chains``, ``unlinked_supporting_evidence``, ``synthesis_summary``,
    ``source_coverage``). Deterministic — never calls an LLM, never re-reads raw
    source tables.
    """
    # Lazy import avoids a module import cycle (the vault service imports us).
    from app.services.student_proof_vault_service import collect_skill_report

    report = collect_skill_report(db, pipeline_db, user_id, skill_name)
    # collect_skill_report already embeds the synthesis fields; if a caller passes
    # a pre-synthesis dict, synthesize defensively.
    if "proof_chains" not in report:
        report.update(synthesize_skill_report(report))
    return report
