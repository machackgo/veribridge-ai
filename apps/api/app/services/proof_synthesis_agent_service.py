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

from app.services.cross_proof_linking_service import link_proof_chains
from app.services.github_python_evidence_focus import (
    GRADE_IMPLEMENTATION_BODY,
    GRADE_SUPPORTING_LOGIC,
    classify_skill_relevance,
    effective_code_block_purpose,
    effective_evidence_grade,
    grade_rank,
    is_skill_code_relevance,
    is_skill_implementation_relevance,
    is_weak_grade,
    safe_selection_reason,
)
from app.services.github_skill_evidence_service import is_ml_skill
from app.services.llm_proof_synthesis_service import (
    synthesize_chain,
    synthesize_linked_chains_bounded,
)
from app.services.evidence_normalization_service import (
    SOURCE_DEFENSE,
    SOURCE_DOCUMENT,
    SOURCE_GITHUB,
    SOURCE_VIDEO,
    SOURCE_WEBSITE,
    has_precise_code,
    has_source,
    normalize_chain,
    normalize_skill_report,
)

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

# GitHub Smart-Evidence proof-strength labels (honest proof language, no scores).
# implementation_body → primary; supporting_logic → supporting; anything weaker →
# not enough on its own.
GH_PRIMARY = "Primary implementation evidence"
GH_SUPPORTING = "Supporting code evidence"
GH_INSUFFICIENT = "Insufficient precise evidence"

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


def _github_reason(item: dict[str, Any]) -> str:
    """The safe "why this line" text for a GitHub code row.

    Read-time neutralised via :func:`safe_selection_reason`: a WEAK / fallback /
    ungraded row can NEVER present a stale keyword reason ("ML model instantiation",
    "Cloud deployment command") as implementation evidence — it is replaced with an
    honest grade-based / repository-level label. Only a validated strong body
    (implementation_body / supporting_logic) keeps its precise stored reason.
    """
    reason = safe_selection_reason(
        item.get("evidence_quality_grade"),
        item.get("selection_reason") or item.get("safe_summary"),
    )
    return reason or "skill-relevant implementation"


def _github_code_rows(github: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Precise ``code_line`` GitHub rows (located line evidence), any grade."""
    return [
        g
        for g in github
        if g.get("display_mode") == "code_line" and g.get("has_precise_line_evidence")
    ]


def _row_effective_grade(skill: str, row: dict[str, Any]) -> str | None:
    """Read-time ML-validated grade for a GitHub row (defense in depth).

    A trusted ``implementation_body`` that lacks actual ML executable signals — a
    deployment-only / serving-only / cloud-only body — is downgraded to
    ``supporting_logic`` for a Machine Learning skill, so it can never be classified
    as Machine Learning primary implementation proof. Non-ML skills and every other
    grade are returned unchanged.
    """
    return effective_evidence_grade(
        row.get("evidence_quality_grade"),
        is_ml=is_ml_skill(skill),
        reason=row.get("selection_reason") or row.get("safe_summary"),
        code_snippet=row.get("safe_snippet"),
        file_path=row.get("file_path"),
        function_name=row.get("function_name"),
        ml_signal=row.get("ml_executable_signal"),
    )


def _row_skill_relevance(skill: str, row: dict[str, Any], grade: str | None) -> str:
    """Read-time SKILL RELEVANCE of a GitHub row for the report's selected skill.

    Recomputed here (defense in depth, exactly like :func:`_row_effective_grade`)
    from the row's resolved block purpose × the skill's family × the VALIDATED
    grade — never trusted from a stored label — so a cross-skill implementation
    row (React UI code in a Machine Learning report, ML training in a DevOps
    report) can never be consumed as the selected skill's own implementation.
    """
    purpose_key = effective_code_block_purpose(
        row.get("code_block_purpose_key"),
        grade=grade,
        code_snippet=row.get("safe_snippet"),
        selection_reason=row.get("selection_reason"),
        file_path=row.get("file_path"),
        function_name=row.get("function_name"),
    )
    return classify_skill_relevance(
        purpose_key,
        skill=skill,
        grade=grade,
        ml_signal=row.get("ml_executable_signal"),
    )


def _row_is_skill_implementation(
    skill: str, row: dict[str, Any], grade: str | None = None
) -> bool:
    """True when a row is a VALIDATED implementation body whose RELEVANCE marks it
    as the selected skill's OWN implementation work (grade + relevance, both
    recomputed at read time, fail closed). Only such rows may anchor the strongest
    confidence tier or be synthesized as primary implementation proof — a
    cross-skill / product-UI / deployment-context implementation row never can.

    Skills with no recognizable family (``general`` — unknown/unmapped/future
    IT skills) FAIL CLOSED like every other skill (mirrors the Vault's
    coherent-chain gate): relevance for a ``general`` family resolves to at
    most ``supporting_context``, so an ``implementation_body`` grade ALONE can
    never mark a row as primary/direct proof — direct relevance requires a
    deterministic purpose × family mapping in the central taxonomy.
    ``grade`` may be passed when already computed."""
    if grade is None:
        grade = _row_effective_grade(skill, row)
    if grade != GRADE_IMPLEMENTATION_BODY:
        return False
    return is_skill_implementation_relevance(_row_skill_relevance(skill, row, grade))


def _github_evidence_assessment(skill: str, github: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify a chain's GitHub code evidence by Smart-Evidence quality band.

    Deterministic, no LLM. Consumes the Smart GitHub Evidence output already on
    each row (``evidence_quality_grade`` + safe file/line/``selection_reason``) and
    distinguishes, honestly:

    * a real **implementation body** (grade ``implementation_body``) → *primary*
      GitHub implementation proof;
    * **supporting logic** (grade ``supporting_logic``, or a precise line whose
      grade is not yet established) → *supporting* code proof, never primary;
    * only **weak / repo-level** rows (import/docstring/config/route-decorator/
      repo-fallback, or no located line at all) → precise implementation evidence
      is *insufficient by itself*.

    Returns a small dict with a ``strength`` key, a recruiter-facing ``label`` and
    an honest ``note`` sentence (empty when the chain has no GitHub evidence).
    """
    rows = _github_code_rows(github)
    # Read-time ML-validate each row AND require the selected skill's own
    # relevance: a deployment-only body stored as implementation_body, or a
    # cross-skill implementation row (React UI code in an ML report), is never
    # classified as the skill's primary — or even supporting — code proof.
    impl: list[dict[str, Any]] = []
    support: list[dict[str, Any]] = []
    ungraded: list[dict[str, Any]] = []
    for g in rows:
        grade = _row_effective_grade(skill, g)
        if _row_is_skill_implementation(skill, g, grade=grade):
            impl.append(g)
        elif not is_skill_code_relevance(_row_skill_relevance(skill, g, grade)):
            continue  # cross-skill / UI / deployment / docs — not code proof here
        elif grade in (GRADE_SUPPORTING_LOGIC, GRADE_IMPLEMENTATION_BODY):
            # A real body whose relevance never resolves past supporting/needs-
            # review (unknown/unmapped skill family) is honest supporting code,
            # never this skill's primary implementation proof.
            support.append(g)
        elif not g.get("evidence_quality_grade"):
            # A precise line with no grade at all is precise but its quality is
            # unproven — treat as supporting, never promote to primary.
            ungraded.append(g)

    if impl:
        best = min(impl, key=lambda g: grade_rank(g.get("evidence_quality_grade")))
        return {
            "strength": "implementation",
            "label": GH_PRIMARY,
            "note": (
                f"Primary GitHub implementation evidence: {_github_location(best)} "
                f"shows {_github_reason(best)}."
            ),
        }
    if support or ungraded:
        best = (support or ungraded)[0]
        return {
            "strength": "supporting",
            "label": GH_SUPPORTING,
            "note": (
                f"Supporting GitHub evidence: {_github_location(best)} shows "
                f"{_github_reason(best)}. No primary implementation body was isolated, "
                "so GitHub evidence is partial/supporting."
            ),
        }
    if github:
        # Some GitHub evidence exists, but only weak precise lines or repo-level rows.
        return {
            "strength": "weak",
            "label": GH_INSUFFICIENT,
            "note": (
                "GitHub evidence is repository-level, weak, or not relevant to this "
                "skill (imports/config/decorators/cross-skill code/no located line); "
                "precise implementation evidence is insufficient by itself."
            ),
        }
    return {"strength": "none", "label": "", "note": ""}


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
    has_implementation_body: bool,
    has_supporting_code: bool,
    has_github_any: bool,
    has_website: bool,
    has_defense: bool,
    has_document: bool,
    has_skill_graph: bool,
) -> str:
    """Map a chain's source mix to a qualitative tier — never a numeric score.

    Independent *strong, primary* sources are: a located GitHub implementation
    **body** (Smart-Evidence grade ``implementation_body``), a Website runtime
    workflow (behaviour), and a Project Defense/Video (understanding). Only a real
    implementation body counts as primary GitHub implementation proof — so a
    "Strongly corroborated" tier can only be reached with a primary implementation
    artifact anchoring it.

    ``supporting_logic`` / as-yet-ungraded precise GitHub lines
    (``has_supporting_code``) are corroborative code evidence, never primary: they
    can lift a single strong source to *corroborated* but can never, on their own,
    create the strongest tier. This keeps the tier consistent with the honest
    "No primary implementation body was isolated" limitation — that limitation is
    only emitted when no implementation body exists, and in that case this function
    never returns :data:`TIER_STRONG`. Documents likewise corroborate but are never
    a strong, independent source on their own.
    """
    strong = [
        name
        for name, present in (
            ("github_code", has_implementation_body),
            ("website", has_website),
            ("defense", has_defense),
        )
        if present
    ]
    if len(strong) >= 2:
        # Two+ independent strong sources; only a primary GitHub implementation
        # body anchors the strongest tier (Website + Defense alone → corroborated).
        return TIER_STRONG if "github_code" in strong else TIER_CORROBORATED
    if len(strong) == 1:
        # One strong source; a corroborating document OR supporting GitHub code
        # (supporting_logic / ungraded precise line) lifts it to corroborated but
        # never to strong.
        return TIER_CORROBORATED if (has_document or has_supporting_code) else TIER_SUPPORTING
    if has_supporting_code:
        # Precise supporting GitHub code with no strong source to anchor it reads
        # as supporting evidence, never a strong claim.
        return TIER_SUPPORTING
    if has_github_any or has_document or has_skill_graph:
        # Only repo-level/weak GitHub, documents, or aggregated graph evidence → review.
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
        cited = list(dict.fromkeys(i for i in ids if i in allowed_ids))
        if cited:
            statements.append({"text": text, "source": source, "evidence_ids": cited})

    # Aggregate GitHub evidence by quality class so a repo with many rows produces
    # AT MOST one primary-code statement, one supporting-code statement, and one
    # weak/repo-level limitation — never one repeated paragraph per row. Cited
    # evidence ids are deduplicated (via ``_add``) so the same row is never chipped
    # twice. Rows are already ranked strongest-first by the vault grouper, so the
    # first primary/supporting row is the best exemplar to describe.
    github = chain.get("github_evidence") or []
    primary_rows: list[dict[str, Any]] = []
    supporting_rows: list[dict[str, Any]] = []
    weak_line_rows: list[dict[str, Any]] = []
    repo_level_rows: list[dict[str, Any]] = []
    for g in github:
        # Read-time ML-validated grade AND skill relevance: a deployment-only
        # implementation_body is downgraded, and a cross-skill implementation row
        # (React UI code in an ML report) is never synthesized as this skill's
        # primary — or supporting — code proof; it joins the weak/limitation band.
        grade = _row_effective_grade(skill, g)
        is_code_line = g.get("display_mode") == "code_line" and g.get("has_precise_line_evidence")
        if is_code_line and _row_is_skill_implementation(skill, g, grade=grade):
            primary_rows.append(g)
        elif (
            is_code_line
            and not is_weak_grade(grade)
            and is_skill_code_relevance(_row_skill_relevance(skill, g, grade))
        ):
            supporting_rows.append(g)
        elif is_code_line:
            weak_line_rows.append(g)
        else:
            repo_level_rows.append(g)

    def _ids(rows: list[dict[str, Any]]) -> list[str]:
        return [str(r.get("source_id") or "") for r in rows]

    if primary_rows:
        best = primary_rows[0]
        _add(
            f"Primary GitHub implementation evidence: {_github_location(best)} shows "
            f"{_github_reason(best)}.",
            PROOF_GITHUB,
            _ids(primary_rows),
        )
    if supporting_rows:
        best = supporting_rows[0]
        _add(
            f"Supporting GitHub evidence: {_github_location(best)} shows {_github_reason(best)}.",
            PROOF_GITHUB,
            _ids(supporting_rows),
        )
    if weak_line_rows:
        # ONE aggregated limitation for every weak or non-skill-relevant precise
        # line (import/docstring/config/route-decorator/cross-skill code), never one
        # paragraph per weak row. A representative row's location + reason is named
        # so the honest limitation is still concrete.
        n = len(weak_line_rows)
        best = weak_line_rows[0]
        noun = "GitHub code signal was" if n == 1 else "GitHub code signals were"
        _add(
            f"{n} weak/repository-level {noun} found (e.g. {_github_location(best)} — "
            f"{_github_reason(best)}): imports, comments, configuration, endpoint "
            "scaffolding, or code for a different skill — not sufficient by itself "
            f"as {skill} implementation proof.",
            PROOF_GITHUB,
            _ids(weak_line_rows),
        )
    if repo_level_rows:
        _add(
            "GitHub repository evidence supports this skill at repository level "
            "(no precise line-level code located).",
            PROOF_GITHUB,
            _ids(repo_level_rows),
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
            "The candidate explained this project in the Project Defense, evidencing "
            "personal understanding (never, by itself, authorship).",
            PROOF_DEFENSE,
            defense_ids,
        )

    # Aggregate EVERY document correlation into ONE corroboration statement per
    # chain — documents corroborate the skill claim but never independently prove
    # implementation, so the report must not emit one nearly identical paragraph per
    # document. Cited evidence ids are deduplicated so the same document is chipped
    # once, and the singular/plural phrasing reflects the distinct cited count.
    doc_ids = [str(d.get("source_id") or "") for d in (chain.get("document_correlations") or [])]
    cited_docs = list(dict.fromkeys(i for i in doc_ids if i in allowed_ids))
    if cited_docs:
        if len(cited_docs) == 1:
            text = (
                f"A document corroborates the {skill} skill claim, but does not "
                "independently prove implementation (supporting evidence, not primary proof)."
            )
        else:
            text = (
                f"Documents corroborate the {skill} skill claim, but do not "
                "independently prove implementation (supporting evidence, not primary proof)."
            )
        _add(text, PROOF_DOCUMENT, cited_docs)

    return statements


def _synthesis_result(
    skill: str,
    project_title: str,
    tier: str,
    statements: list[dict[str, Any]],
    github_note: str = "",
) -> str:
    """One-to-two safe sentences summarizing how the chain's sources corroborate.

    The optional ``github_note`` (from :func:`_github_evidence_assessment`) is
    appended verbatim so the recruiter-facing result states honestly whether GitHub
    is *primary* implementation proof, *supporting* code, or *insufficient* — never
    over-claiming when only weak/repo-level GitHub evidence exists.
    """
    sources = sorted({s["source"] for s in statements})
    if not sources:
        base = f"No connected evidence was found for {skill} in {project_title}."
        return f"{base} {github_note}".strip() if github_note else base
    if len(sources) == 1:
        joined = sources[0]
    else:
        joined = ", ".join(sources[:-1]) + " and " + sources[-1]
    base = (
        f"In {project_title}, {joined} independently corroborate {skill} "
        f"({tier.lower()})."
    )
    return f"{base} {github_note}".strip() if github_note else base


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

    Adds ``confidence_tier``, ``synthesis_result``, ``why_linked``, ``subskills``,
    evidence-cited ``synthesis_statements`` and the uniform ``normalized_evidence``
    set (Step 2's Evidence Normalization Engine output) — the chain keeps every
    original field, so existing consumers are unaffected.
    """
    github = chain.get("github_evidence") or []

    # Step 2: collapse this chain's mixed-shape evidence into the single internal
    # NormalizedEvidenceArtifact model, then tier from THAT uniform set so the
    # source/strength logic lives in one place (the normalizer), not per-source here.
    artifacts = normalize_chain(chain, skill)

    # Only a located, SKILL-RELEVANT implementation *body* is primary GitHub
    # implementation proof; a precise line that is only supporting_logic /
    # not-yet-graded / cross-skill corroborates but can never anchor the strongest
    # tier (kept separate so the tier stays honest). Grade AND relevance are
    # recomputed per row (read-time, fail-closed) exactly as the assessment and
    # statement builders do, so the tier can never disagree with them.
    impl_body = any(_row_is_skill_implementation(skill, g) for g in _github_code_rows(github))
    tier = _confidence_tier(
        has_implementation_body=impl_body,
        has_supporting_code=has_precise_code(artifacts) and not impl_body,
        has_github_any=has_source(artifacts, SOURCE_GITHUB),
        has_website=has_source(artifacts, SOURCE_WEBSITE),
        has_defense=has_source(artifacts, SOURCE_DEFENSE, SOURCE_VIDEO),
        has_document=has_source(artifacts, SOURCE_DOCUMENT),
        has_skill_graph=False,
    )
    allowed_ids = _chain_evidence_ids(chain)
    statements = _build_statements(skill, chain, allowed_ids)

    # Smart GitHub Evidence assessment: primary implementation body vs supporting
    # logic vs weak/repo-level — drives honest recruiter wording (never over-claims).
    gh_assessment = _github_evidence_assessment(skill, github)

    chain["confidence_tier"] = tier
    chain["normalized_evidence"] = [a.to_dict() for a in artifacts]
    chain["subskills"] = _subskills(github)
    chain["synthesis_statements"] = statements
    chain["github_evidence_assessment"] = gh_assessment
    chain["has_primary_github_implementation"] = impl_body
    chain["synthesis_result"] = _synthesis_result(
        skill,
        chain.get("project_title") or "this project",
        tier,
        statements,
        gh_assessment.get("note", ""),
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


def synthesize_skill_report(report: dict[str, Any], *, use_llm: bool = True) -> dict[str, Any]:
    """Synthesize an already-built Skill Report dict into connected proof chains.

    Pure function over the safe :func:`collect_skill_report` output. Enriches each
    attached chain in place, builds the capped unlinked bucket, and returns the
    synthesis sub-report (``proof_chains`` / ``unlinked_supporting_evidence`` /
    ``synthesis_summary`` / ``source_coverage``). Called by ``collect_skill_report``
    to embed these fields; also reachable directly via :func:`build_skill_proof_synthesis`.

    ``use_llm=False`` forces the Step-4 synthesis claims to the deterministic
    rule-based path (never resolving/calling any LLM provider). Used by the
    public, unauthenticated Skill Report surface so an anonymous request can
    never trigger a paid provider call.
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

    # Step 3: collapse the whole report into the uniform artifact set and link
    # related evidence (same project / repo / endpoint / function) into connected
    # proof chains. Additive — existing keys above are untouched, so every prior
    # consumer of the synthesis output is unaffected.
    linked_chains = link_proof_chains(normalize_skill_report(report))

    # Step 4: LLM Synthesis Layer — produce recruiter-readable synthesis claims
    # over the deterministic linked chains. Runs strictly AFTER linking; with no
    # injected LLM and no Anthropic credentials it returns the safe, deterministic
    # rule-based synthesis (so tests and local dev never touch the network). Purely
    # additive: every existing key above is untouched, keeping all prior consumers
    # backward compatible. Uses the bounded-concurrency orchestrator so the
    # configured LLM_SYNTHESIS_MAX_CONCURRENCY is honoured, while staying safe to
    # call from this synchronous service (deterministic order + per-chain fallback).
    # ``use_llm=False`` (public/anonymous surfaces) skips provider resolution
    # entirely: every chain gets the same safe deterministic synthesis, run
    # sequentially (no concurrency machinery needed without a provider).
    if use_llm:
        llm_synthesis = synthesize_linked_chains_bounded(linked_chains)
    else:
        llm_synthesis = [
            synthesize_chain(chain, force_deterministic=True) for chain in linked_chains
        ]

    return {
        "synthesis_summary": summary,
        "source_coverage": coverage,
        "proof_chains": proof_chains,
        "unlinked_supporting_evidence": unlinked,
        "linked_proof_chains": [c.to_dict() for c in linked_chains],
        "llm_synthesis": [s.to_dict() for s in llm_synthesis],
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
