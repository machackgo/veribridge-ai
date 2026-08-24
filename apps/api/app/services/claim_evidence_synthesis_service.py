"""Claim→Evidence synthesis — the ONE canonical backend layer that turns the
per-source report evidence (GitHub / Website / Document / Project Defense /
Video) into a :class:`~app.schemas.canonical_evidence.ClaimEvidenceMap`.

Both report surfaces consume this module:

* :func:`build_skill_claim_evidence_map` — from the Skill Report
  (``collect_skill_report``'s connected project chains).
* :func:`build_project_claim_evidence_map` — from the Project Report
  (``build_student_vbr_report``'s skill matrix + evidence traces).

Everything here is DETERMINISTIC. It only reads locators and closed-vocabulary
labels the analyzers already stored — it never invents a file, line, commit,
timestamp, page, URL, deployment, or identity. The honesty rules it encodes:

1. **GitHub tiering** — a bare route decorator, import block, docstring, config
   constant, or repo-level fallback is never "primary implementation". Tiers
   derive from the VALIDATED ``evidence_quality_grade``.
2. **Website↔project identity** — same-project ATTACHMENT is not identity. A
   recording only counts as direct runtime evidence when its recorded
   application identity (app context / page title / domain) genuinely matches
   the project (title / repo / deployed domain). A recording that names a
   DIFFERENT application is classified ``mismatched``: visible, flagged, never
   counted, never corroborating — and never silently deleted or moved.
3. **Corroboration** — requires claim-level alignment: two or more citations of
   different proof types that each independently COUNT for the same claim.
   Sharing a project id alone can never create a corroboration group.
4. **Defense pending** — a captured-but-unanalyzed defense renders as an
   explicit "Analysis pending" citation that is visible but never counted.
5. **Qualitative only** — statuses come from the closed ladder in
   ``canonical_evidence.QUALITATIVE_STATES``; no numeric scores exist anywhere.
6. **Claims are PROJECT-scoped; candidate attribution is separate** — every
   ``claim_text`` asserts what the project's artifacts show ("<skill> is
   demonstrated in the project <title>"), never who built it. The candidate
   side lives in ``SkillClaim.candidate_attribution`` /
   ``ClaimEvidenceMap.project_relationship`` and derives ONLY from
   candidate↔artifact relationship evidence (defense ownership stances, stored
   attribution evidence — see ``candidate_attribution_service``). An explicit
   denial blocks candidate implementation claims; aggregation of project-level
   sources can never create candidate-level attribution; corroboration
   preserves the project subject of the underlying claim.
"""

from __future__ import annotations

import re
from typing import Any

from app.schemas.canonical_evidence import (
    CandidateAttribution,
    ClaimEvidenceMap,
    Contradiction,
    CorroborationGroup,
    EvidenceCitation,
    EvidenceGap,
    EvidenceRelation,
    ProjectFeature,
    SkillClaim,
    SourceCounts,
)
from app.services.candidate_attribution_service import (
    assess_project_ownership,
    build_candidate_attribution,
    detect_ownership_stance,
)
from app.services.github_python_evidence_focus import is_countable_code_purpose

# ── Proof-type labels (must match student_proof_vault_service constants) ──────
_GITHUB = "GitHub Proof"
_DOCUMENT = "Document Proof"
_WEBSITE = "Website Proof"
_DEFENSE = "Project Defense"
_VIDEO = "Video Evidence"

# Validated GitHub grade → canonical implementation tier. Anything absent from
# this table (unknown/legacy grades, missing grade) is a weak signal.
_GRADE_TO_TIER = {
    "implementation_body": "primary_implementation",
    "supporting_logic": "supporting_implementation",
    "config_or_constant": "configuration_context",
    "comment_or_docstring": "weak_signal",
    "import_only": "weak_signal",
    "route_decorator_only": "weak_signal",
    "repo_level_fallback": "weak_signal",
}

_TIER_STRENGTH_LABEL = {
    "primary_implementation": "Primary implementation",
    "supporting_implementation": "Supporting implementation",
    "configuration_context": "Configuration / context",
    "weak_signal": "Weak signal",
    "not_relevant": "Not relevant to this skill",
}

# Tiers that COUNT as direct implementation evidence for a claim.
_COUNTING_TIERS = frozenset({"primary_implementation", "supporting_implementation"})

# Relevance keys that are still NEEDS-REVIEW: the block's relation to the skill
# has not been positively validated, so it may render and be inspected but can
# never occupy a counting tier (part of the countability contract above).
_NEEDS_REVIEW_RELEVANCES = frozenset(
    {"context_only_needs_review", "direct_candidate_needs_review"}
)

# Tokens too generic to identify an application (never let "app"/"ai"/"demo"
# create or break an identity match).
_IDENTITY_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "app", "web", "site", "website", "page",
        "home", "ai", "api", "dev", "demo", "test", "local", "localhost",
        "http", "https", "www", "com", "org", "net", "html", "index", "smart",
        "system", "project", "portal", "dashboard", "platform", "proof",
        "recording", "recorded", "session", "workflow", "evidence",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")


def _tokens(*texts: Any) -> set[str]:
    """Significant lowercase identity tokens across the given texts."""
    out: set[str] = set()
    for text in texts:
        if not text:
            continue
        for tok in _TOKEN_RE.findall(str(text).lower()):
            if tok not in _IDENTITY_STOPWORDS and not tok.isdigit():
                out.add(tok)
    return out


# ── GitHub implementation tiering ─────────────────────────────────────────────


def classify_github_tier(item: dict[str, Any]) -> tuple[str, str]:
    """Canonical implementation tier + honest reason for one GitHub evidence item.

    Reads only stored, validated fields (``evidence_quality_grade``,
    ``display_mode``, ``skill_relevance_key``, ``code_block_purpose_key``,
    ``file_path``). Route decorators, imports, docstrings, config, and
    repo-level fallbacks can never be primary — and the COUNTABILITY CONTRACT
    holds: a block whose purpose is unresolved (unknown / insufficient stored
    context / repository-level) or whose skill relevance is still needs-review
    can never reach a counting tier, whatever its structural grade says.
    "Purpose unknown + counted as direct evidence" must be impossible.
    """
    relevance_key = str(item.get("skill_relevance_key") or "")
    if relevance_key.endswith("_context"):
        return "not_relevant", (
            item.get("skill_relevance_label")
            or "This code relates to a different skill family — context, not implementation proof."
        )
    grade = str(item.get("evidence_quality_grade") or "")
    if not item.get("file_path") or item.get("display_mode") == "repo_level":
        return "weak_signal", "Repository-level signal only — no validated file/line code body was isolated."
    tier = _GRADE_TO_TIER.get(grade, "weak_signal")
    if tier in _COUNTING_TIERS:
        purpose_key = str(item.get("code_block_purpose_key") or "")
        if purpose_key and not is_countable_code_purpose(purpose_key):
            return "weak_signal", (
                "The purpose of this code block could not be determined from the "
                "stored context — needs review; it is never counted as "
                "implementation evidence until reanalysis resolves it."
            )
        if relevance_key in _NEEDS_REVIEW_RELEVANCES:
            return "weak_signal", (
                "This block's relation to the skill has not been validated — "
                "needs review, not counted as implementation evidence."
            )
    reasons = {
        "primary_implementation": "Validated implementation body at the cited lines.",
        "supporting_implementation": "Validated supporting implementation logic at the cited lines.",
        "configuration_context": "Configuration/constant definitions — context, not an implementation body.",
        "weak_signal": (
            "Weak code signal (imports / docstring / bare route decorator / repo fallback) — "
            "not implementation proof."
        ),
    }
    return tier, reasons[tier]


# ── Website ↔ project identity validation ─────────────────────────────────────


def classify_website_identity(
    *,
    identity_texts: list[str],
    target_domain: str | None,
    project_title: str | None,
    repo_name: str | None = None,
    repo_full: str | None = None,
    deployed_url: str | None = None,
) -> tuple[str, list[str]]:
    """Deterministic website↔project identity check.

    Returns ``(identity_state, reasons)``. Attachment to the project is assumed
    (callers only pass attached recordings) and deliberately contributes NOTHING
    — the recording must prove its identity from what was actually recorded.
    """
    reasons: list[str] = []
    project_tokens = _tokens(project_title, (repo_name or "").replace("-", " ").replace("_", " "))
    identity_tokens = _tokens(*identity_texts)
    domain = (target_domain or "").strip().lower()

    # 1 — recorded domain matches the project's declared deployment domain.
    if domain and deployed_url:
        deployed_domain = re.sub(r"^https?://", "", str(deployed_url).lower()).split("/")[0]
        if deployed_domain and (domain == deployed_domain or domain.endswith("." + deployed_domain)):
            reasons.append(f"Recorded domain '{domain}' matches the project's deployed URL.")
            return "matched_direct", reasons

    # 2 — recorded domain names the repository.
    repo_token = (repo_name or "").strip().lower().replace("_", "-")
    if domain and repo_token and repo_token in domain:
        reasons.append(f"Recorded domain '{domain}' names the project repository '{repo_token}'.")
        return "matched_direct", reasons

    # 3 — recorded application identity vs. project identity tokens.
    overlap = sorted(project_tokens & identity_tokens)
    if overlap:
        if len(overlap) >= 2:
            reasons.append(
                "Recorded application identity matches the project on: " + ", ".join(overlap) + "."
            )
            return "matched_direct", reasons
        reasons.append(
            f"Recorded application identity shares only one token ('{overlap[0]}') with the project — "
            "needs owner confirmation."
        )
        return "possible_match_review", reasons

    # 4 — the recording names a DIFFERENT application: a genuine mismatch.
    if identity_tokens:
        reasons.append(
            "The recorded application identifies as '"
            + " / ".join(t for t in identity_texts if t)[:120]
            + "', which does not match this project"
            + (f" ('{project_title}')" if project_title else "")
            + ". Same-project attachment alone does not make it project evidence."
        )
        return "mismatched", reasons

    # 5 — no identity signal at all: honest review-needed state.
    reasons.append(
        "The recording carries no application-identity signals (no app name, page title, or public "
        "domain) — its association with this project is attachment-only and needs owner review."
    )
    return "possible_match_review", reasons


def _website_identity_for_card(
    card: dict[str, Any] | None,
    item: dict[str, Any],
    *,
    project_title: str | None,
    repo_name: str | None,
    repo_full: str | None,
    deployed_url: str | None,
) -> tuple[str, list[str]]:
    card = card or {}
    return classify_website_identity(
        identity_texts=[
            str(card.get("app_context") or ""),
            str(card.get("page_title") or ""),
            str(item.get("title") or ""),
        ],
        target_domain=card.get("target_domain"),
        project_title=project_title,
        repo_name=repo_name,
        repo_full=repo_full,
        deployed_url=deployed_url,
    )


# ── Shared assembly helpers ───────────────────────────────────────────────────


def _claim_status(
    *,
    counted: list[EvidenceCitation],
    has_primary_impl: bool,
    corroborated: bool,
    pending: bool,
    mismatched: bool,
    context_only: bool,
) -> str:
    if has_primary_impl and corroborated:
        return "Demonstrated"
    if corroborated:
        return "Corroborated"
    if counted:
        return "Partially demonstrated"
    if pending:
        return "Analysis pending"
    if mismatched:
        return "Mismatch detected"
    if context_only:
        return "Context only"
    return "Insufficient evidence"


def _strongest_tier_label(counted: list[EvidenceCitation], pending: bool) -> str:
    if any(c.github_tier == "primary_implementation" for c in counted):
        return "Primary implementation"
    if any(c.github_tier == "supporting_implementation" for c in counted):
        return "Supporting implementation"
    if any(c.proof_type == _WEBSITE for c in counted):
        return "Runtime demonstration"
    if any(c.proof_type == _DOCUMENT for c in counted):
        return "Design documentation"
    if any(c.proof_type in (_DEFENSE, _VIDEO) for c in counted):
        # Defense/video is candidate EXPLANATION — an affirmed contribution
        # description at most, understanding otherwise. Never authorship proof.
        if any(c.strength == "Contribution explanation" for c in counted):
            return "Contribution explanation"
        return "Understanding explanation"
    if pending:
        return "Analysis pending"
    return "None" if not counted else "Context only"


def _defense_strength_label(claim_type: str, ownership_stance: str) -> str:
    """Closed strength label for ONE counted defense citation.

    A denial that still explains the skill counts as UNDERSTANDING evidence —
    the ownership clarification rides along as a limitation, and the claim's
    candidate attribution carries the denial. An affirmed personal-contribution
    answer is a contribution EXPLANATION (self-description, never authorship
    proof). Everything else demonstrates understanding.
    """
    if ownership_stance in ("affirmed", "mixed") and claim_type == "personal_contribution":
        return "Contribution explanation"
    return "Understanding explanation"


_SOURCE_CONTRIBUTION = {
    _GITHUB: "shows the implementation code at exact cited lines",
    _WEBSITE: "shows the behaviour running at recording time",
    _DOCUMENT: "explains the design/method with a page/section citation",
    _DEFENSE: "shows the candidate explaining the project in their own words",
    _VIDEO: "shows a recorded demonstration",
}

# Deterministic "strongest first" rank for counted citations — decides which
# counted proof type is the claim's DIRECT source vs. its corroborating sources.
def _counted_rank(c: EvidenceCitation) -> int:
    if c.github_tier == "primary_implementation":
        return 0
    if c.github_tier == "supporting_implementation":
        return 1
    if c.proof_type == _WEBSITE:
        return 2
    if c.proof_type == _DOCUMENT:
        return 3
    return 4  # defense / video candidate explanation (understanding/contribution)


def compute_source_counts(citations: list[EvidenceCitation]) -> SourceCounts:
    """Honest, deduplicated per-bucket SOURCE counts for one claim.

    Counts distinct proof types per bucket. Rules:
      • counted citations split into direct (the strongest counted tier) and
        corroborating (every other counted proof type);
      • a video citation marked ``duplicate_of_evidence_id`` is a citation
        layer into an existing defense source — it lands in NO bucket;
      • pending / vault-only / mismatched sources are visible, never counted;
      • a proof type already direct/corroborating never re-appears as context.
    """
    counted = [
        c for c in citations if c.counted_as_direct_evidence and not c.duplicate_of_evidence_id
    ]
    direct_types: set[str] = set()
    corroborating_types: set[str] = set()
    if counted:
        best = min(_counted_rank(c) for c in counted)
        for c in counted:
            (direct_types if _counted_rank(c) == best else corroborating_types).add(c.proof_type)
        corroborating_types -= direct_types
    pending_types: set[str] = set()
    vault_types: set[str] = set()
    unsupported_types: set[str] = set()
    context_types: set[str] = set()
    for c in citations:
        if c.counted_as_direct_evidence or c.duplicate_of_evidence_id:
            continue
        if c.analysis_pending:
            pending_types.add(c.proof_type)
        elif (c.project_relationship and c.project_relationship.state == "vault_only") or (
            c.project_relationship is None and not c.project_id
        ):
            vault_types.add(c.proof_type)
        elif c.identity_state == "mismatched" or (
            c.project_relationship and c.project_relationship.state == "mismatched_project"
        ):
            unsupported_types.add(c.proof_type)
        else:
            context_types.add(c.proof_type)
    counted_types = direct_types | corroborating_types
    context_types -= counted_types
    pending_types -= counted_types
    vault_types -= counted_types
    return SourceCounts(
        direct=len(direct_types),
        corroborating=len(corroborating_types),
        context_only=len(context_types),
        pending=len(pending_types),
        vault_only=len(vault_types),
        unsupported=len(unsupported_types),
        direct_sources=sorted(direct_types),
        corroborating_sources=sorted(corroborating_types),
        context_only_sources=sorted(context_types),
        pending_sources=sorted(pending_types),
        vault_only_sources=sorted(vault_types),
        unsupported_sources=sorted(unsupported_types),
    )


def _aggregate_source_counts(claims: list[SkillClaim]) -> SourceCounts:
    """Map-level union of the per-claim buckets (distinct proof types)."""
    buckets: dict[str, set[str]] = {
        "direct": set(), "corroborating": set(), "context_only": set(),
        "pending": set(), "vault_only": set(), "unsupported": set(),
    }
    for claim in claims:
        sc = claim.source_counts
        buckets["direct"].update(sc.direct_sources)
        buckets["corroborating"].update(sc.corroborating_sources)
        buckets["context_only"].update(sc.context_only_sources)
        buckets["pending"].update(sc.pending_sources)
        buckets["vault_only"].update(sc.vault_only_sources)
        buckets["unsupported"].update(sc.unsupported_sources)
    buckets["corroborating"] -= buckets["direct"]
    counted = buckets["direct"] | buckets["corroborating"]
    buckets["context_only"] -= counted
    buckets["pending"] -= counted
    buckets["vault_only"] -= counted
    return SourceCounts(
        **{name: len(types) for name, types in buckets.items()},
        **{f"{name}_sources": sorted(types) for name, types in buckets.items()},
    )


def _group_weak_context(
    claims: list[SkillClaim],
    citations: list[EvidenceCitation],
    relations: list[EvidenceRelation],
) -> tuple[list[EvidenceCitation], list[EvidenceRelation]]:
    """Deduplicate weak/repo-level GitHub context into ONE map-level group.

    The same README/requirements/Dockerfile/import signal must not repeat under
    every skill claim. The first citation per unique source becomes the grouped
    representative (``grouped_context=True``, detached from any single claim);
    the repeats are dropped along with their relations. Counted citations are
    never touched.
    """
    kept: list[EvidenceCitation] = []
    dropped_ids: set[str] = set()
    seen_context: dict[tuple[str, str, str], EvidenceCitation] = {}
    grouped_any = False
    for c in citations:
        is_weak_github = (
            c.proof_type == _GITHUB
            and not c.counted_as_direct_evidence
            and (c.github_tier in ("weak_signal", "not_relevant") or not c.file_path)
        )
        if not is_weak_github:
            kept.append(c)
            continue
        key = (c.source_title, str(c.file_path or ""), str(c.start_line or ""))
        existing = seen_context.get(key)
        if existing is None:
            c.grouped_context = True
            c.claim_id = None
            c.limitations = _dedupe(
                [
                    *c.limitations,
                    "Repository-level / weak code signal — grouped once for the whole report and never counted.",
                ]
            )
            seen_context[key] = c
            kept.append(c)
            grouped_any = True
        else:
            dropped_ids.add(c.evidence_id)
    if not grouped_any:
        return citations, relations
    remaining_relations = [
        r
        for r in relations
        if r.source_evidence_id not in dropped_ids
        and (r.target_evidence_id or "") not in dropped_ids
    ]
    return kept, remaining_relations


def _mark_duplicate_video_citations(citations: list[EvidenceCitation]) -> None:
    """Fold video citations that only point into the SAME defense recording.

    A video timestamp citing the same question/answer as an existing Project
    Defense citation for the same claim is a citation layer, not an independent
    proof source: it stays visible, is marked ``duplicate_of_evidence_id``, and
    can never be counted or bucketed as its own source.
    """
    def _key(c: EvidenceCitation) -> tuple[str, str, str]:
        return (
            str(c.claim_id or ""),
            " ".join(str(c.question_text or "").lower().split())[:120],
            str(c.timestamp_start_label or ""),
        )

    defense_by_key: dict[tuple[str, str, str], EvidenceCitation] = {}
    defense_by_session: dict[tuple[str, str], EvidenceCitation] = {}
    defense_by_claim: dict[str, EvidenceCitation] = {}
    for c in citations:
        if c.proof_type == _DEFENSE:
            defense_by_key.setdefault(_key(c), c)
            if c.source_proof_id and c.claim_id:
                defense_by_session.setdefault((c.claim_id, c.source_proof_id), c)
            if c.claim_id:
                defense_by_claim.setdefault(c.claim_id, c)
    for c in citations:
        if c.proof_type != _VIDEO:
            continue
        match = defense_by_key.get(_key(c)) if c.question_text else None
        if match is None and c.source_proof_id and c.claim_id:
            match = defense_by_session.get((c.claim_id, c.source_proof_id))
        if match is None and c.claim_id and c.timestamp_start_label and not c.source_proof_id:
            # Timestamped video chips are BY CONSTRUCTION moments inside the
            # recorded Project Defense (their builder stores no other source) —
            # when the claim already cites that defense they are a citation
            # layer, never a second independent source.
            match = defense_by_claim.get(c.claim_id)
        if match is not None:
            c.duplicate_of_evidence_id = match.evidence_id
            c.counted_as_direct_evidence = False
            c.evidence_quality = "context"
            c.limitations = _dedupe(
                [
                    *c.limitations,
                    "Video timestamp citation into the same Project Defense recording — not an "
                    "independent proof source.",
                ]
            )


def _build_corroboration(
    claim: SkillClaim, counted: list[EvidenceCitation], group_id: str
) -> CorroborationGroup | None:
    """One corroboration group per claim — ONLY when ≥2 distinct proof types each
    independently count for the claim. Same-project attachment alone never
    reaches here, because mismatched / context-only / pending citations are not
    counted in the first place."""
    by_type: dict[str, list[EvidenceCitation]] = {}
    for c in counted:
        by_type.setdefault(c.proof_type, []).append(c)
    if len(by_type) < 2:
        return None
    sources = sorted(by_type)
    contributions = [
        f"{ptype}: {_SOURCE_CONTRIBUTION.get(ptype, 'independent supporting evidence')}"
        for ptype in sources
    ]
    return CorroborationGroup(
        group_id=group_id,
        claim_id=claim.id,
        feature_id=claim.feature_ids[0] if claim.feature_ids else None,
        evidence_ids=[c.evidence_id for c in counted],
        sources=sources,
        alignment_reason=(
            f"Each source independently supports the claim '{claim.claim_text}' — every citation "
            "here passed its own skill-relevance and identity checks; alignment is at claim level, "
            "not merely shared project attachment."
        ),
        independent_sources=True,
        unique_contributions=contributions,
        limitations=[
            "Corroboration shows the sources agree on this PROJECT-scoped claim; it never "
            "verifies who built the artifact. Candidate attribution is assessed separately "
            "from candidate↔artifact relationship evidence and is unchanged by corroboration."
        ],
    )


def _register_feature(
    features: dict[tuple[str, str], ProjectFeature],
    *,
    project_id: str | None,
    title: str,
    feature_type: str,
    skill: str | None = None,
    repo_path: str | None = None,
    route: str | None = None,
    workflow: str | None = None,
    document_section: str | None = None,
    description: str = "",
) -> str:
    key = (feature_type, title.strip().lower())
    feat = features.get(key)
    if feat is None:
        feat = ProjectFeature(
            id=f"feat-{feature_type}-{len(features) + 1}",
            project_id=project_id,
            title=title,
            description=description,
            feature_type=feature_type,
        )
        features[key] = feat
    if skill and skill not in feat.related_skills:
        feat.related_skills.append(skill)
    if repo_path and repo_path not in feat.repo_paths:
        feat.repo_paths.append(repo_path)
    if route and route not in feat.routes:
        feat.routes.append(route)
    if workflow and workflow not in feat.runtime_workflows:
        feat.runtime_workflows.append(workflow)
    if document_section and document_section not in feat.document_sections:
        feat.document_sections.append(document_section)
    return feat.id


def _project_relationship(
    *,
    project_id: str | None,
    attached: bool,
    state: str | None = None,
    reason: str | None = None,
    project_title: str | None = None,
) -> dict[str, Any]:
    resolved = state or ("directly_linked" if attached and project_id else "vault_only")
    counted = resolved == "directly_linked" and bool(project_id)
    action = None
    if resolved == "suggested_match":
        action = "Review and confirm project"
    elif resolved == "mismatched_project":
        action = "Review project mismatch"
    elif resolved in ("vault_only", "legacy_unresolved"):
        action = "Attach to a project"
    return {
        "state": resolved,
        "project_id": project_id,
        "project_title": project_title,
        "match_method": (
            "explicit_project_id" if resolved == "directly_linked" else "legacy"
        ),
        "counted": counted,
        "confirmed_by_user": resolved == "directly_linked",
        "reasons": [reason] if reason else [],
        "action_label": action,
    }


def _document_block(doc: dict[str, Any]) -> dict[str, Any]:
    """Normalize one stored document locator into a block-aware citation.

    Block type is copied when explicitly stored. Otherwise only explicit labels
    such as "Table 2" or "architecture diagram" are classified; an ambiguous
    figure fails closed to ``unknown_visual_region`` and carries a limitation.
    """
    card = doc.get("inspection_card") if isinstance(doc.get("inspection_card"), dict) else {}
    explicit = str(doc.get("block_type") or card.get("block_type") or "").strip().lower()
    allowed = {
        "paragraph", "heading", "table", "chart", "graph", "image", "screenshot",
        "architecture_diagram", "code_block", "metric_result", "equation", "caption",
        "list", "mixed_region", "unknown_visual_region",
    }
    reference = str(
        doc.get("figure_reference")
        or card.get("table_reference")
        or card.get("diagram_reference")
        or card.get("figure_reference")
        or ""
    )
    ref_lower = reference.lower()
    if explicit in allowed:
        block_type = explicit
    elif ref_lower.startswith("table"):
        block_type = "table"
    elif "architecture" in ref_lower or "diagram" in ref_lower:
        block_type = "architecture_diagram"
    elif ref_lower.startswith(("figure", "image", "chart", "graph")):
        block_type = "unknown_visual_region"
    else:
        block_type = "paragraph"
    visual = card.get("visual_or_table_summary") or doc.get("visual_description")
    model_limitation = doc.get("model_limitation")
    if block_type == "unknown_visual_region" and not model_limitation:
        model_limitation = (
            "The stored locator identifies a visual region but does not reliably classify or "
            "extract its values; no chart/table values are inferred."
        )
    return {
        "document_id": str(doc.get("source_id") or "") or None,
        "document_title": str(doc.get("document_title") or card.get("title") or "Document"),
        "page_number": doc.get("page_number") or card.get("page_number"),
        "block_type": block_type,
        "bounding_box": doc.get("bounding_box") or card.get("bounding_box"),
        "extracted_text": doc.get("safe_snippet") or card.get("safe_snippet"),
        "table_cells": doc.get("table_cells") or card.get("table_cells") or [],
        "visual_description": visual,
        "nearby_caption": doc.get("nearby_caption") or card.get("visual_or_table_summary"),
        "extraction_confidence": str(doc.get("extraction_confidence") or "not_available"),
        "model_limitation": model_limitation,
        "preview_url": card.get("document_preview_url"),
        "open_page_url": card.get("document_open_url"),
    }


# ── Skill Report entry point ──────────────────────────────────────────────────


def build_skill_claim_evidence_map(
    report: dict[str, Any], *, project_meta: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Build the canonical claim→evidence map from a ``collect_skill_report``
    payload (its connected project chains). Purely deterministic."""
    skill = str(report.get("skill") or "")
    meta = project_meta or {}

    claims: list[SkillClaim] = []
    citations: list[EvidenceCitation] = []
    relations: list[EvidenceRelation] = []
    corroborations: list[CorroborationGroup] = []
    contradictions: list[Contradiction] = []
    gaps: list[EvidenceGap] = []
    features: dict[tuple[str, str], ProjectFeature] = {}
    recruiter_actions: list[str] = []
    ev_seq = 0

    def _next_id(prefix: str) -> str:
        nonlocal ev_seq
        ev_seq += 1
        return f"{prefix}-{ev_seq}"

    for chain in report.get("projects") or []:
        pid = chain.get("project_id")
        project_title = str(chain.get("project_title") or "Project")
        attached = bool(chain.get("attached"))
        pmeta = meta.get(str(pid)) if pid else None
        # Candidate↔project ownership for THIS chain: a precomputed assessment
        # in project_meta wins; otherwise assessed from the chain's own defense
        # inspection cards (which carry per-answer ownership stances). Project
        # artifact evidence contributes NOTHING here by design.
        ownership = (pmeta or {}).get("candidate_attribution")
        if not isinstance(ownership, dict):
            ownership = assess_project_ownership(
                answer_items=chain.get("project_defense_inspection") or [],
                repo_analysis=(pmeta or {}).get("repo_analysis"),
            )
        claim = SkillClaim(
            id=_next_id("claim"),
            project_id=str(pid) if pid else None,
            skill_id=str(report.get("skill_slug") or ""),
            skill_name=skill,
            claim_scope="project" if pid else "skill",
            claim_subject="project",
            claim_text=(
                # PROJECT-scoped by construction: the sentence asserts what the
                # project's artifacts show. Who built it is a separate claim
                # carried by ``candidate_attribution`` with its own evidence bar.
                f"{skill} is demonstrated in the project {project_title}."
                if pid
                else f"{skill} is supported by standalone proof in the Proof Vault "
                "(not attached to a project)."
            ),
        )
        chain_counted: list[EvidenceCitation] = []
        chain_pending = False
        chain_mismatch = False
        chain_context = False

        # ── GitHub implementation evidence ─────────────────────────────────
        for item in chain.get("github_evidence") or []:
            tier, tier_reason = classify_github_tier(item)
            counted = tier in _COUNTING_TIERS
            feature_id = None
            if item.get("file_path"):
                symbol = item.get("function_name")
                feature_id = _register_feature(
                    features,
                    project_id=str(pid) if pid else None,
                    title=(f"{symbol}() · {item['file_path']}" if symbol else str(item["file_path"])),
                    feature_type="code_symbol",
                    skill=skill,
                    repo_path=str(item["file_path"]),
                    description=str(item.get("code_block_purpose_label") or ""),
                )
            cit = EvidenceCitation(
                evidence_id=_next_id("ev-gh"),
                proof_type=_GITHUB,
                citation_type=(
                    "github_code_lines"
                    if item.get("file_path") and item.get("line_start")
                    else "github_repository"
                ),
                source_proof_id=str(item.get("source_id") or "") or None,
                project_id=str(pid) if pid else None,
                skill_id=claim.skill_id,
                claim_id=claim.id,
                feature_id=feature_id,
                source_title=str(item.get("title") or "GitHub repository"),
                source_locator=item.get("safe_location"),
                file_path=item.get("file_path"),
                symbol_name=item.get("function_name"),
                start_line=item.get("line_start"),
                end_line=item.get("line_end"),
                context_start_line=item.get("context_start_line"),
                context_end_line=item.get("context_end_line"),
                analysis_version=item.get("analysis_version"),
                commit_sha=item.get("commit_sha"),
                code_excerpt=item.get("safe_snippet"),
                explanation=str(
                    item.get("code_block_purpose_summary")
                    or item.get("selection_reason")
                    or item.get("safe_summary")
                    or ""
                ),
                relevance=str(item.get("skill_relevance_summary") or tier_reason),
                strength=_TIER_STRENGTH_LABEL[tier],
                github_tier=tier,
                counted_as_direct_evidence=counted and attached,
                project_relationship=_project_relationship(
                    project_id=str(pid) if pid else None,
                    attached=attached,
                    project_title=project_title if pid else None,
                ),
                evidence_status="ready" if counted and attached else "excluded",
                evidence_quality=(
                    "primary"
                    if tier == "primary_implementation"
                    else "supporting"
                    if tier == "supporting_implementation"
                    else "context"
                ),
                access=_github_access(item),
                actions=_github_actions(item),
                limitations=_listify(item.get("limitation"))
                + ([] if item.get("file_path") else ["No file/line-level code citation is stored for this row."]),
            )
            citations.append(cit)
            chain_counted += [cit] if cit.counted_as_direct_evidence else []
            chain_context = chain_context or not counted
            relations.append(
                EvidenceRelation(
                    source_evidence_id=cit.evidence_id,
                    claim_id=claim.id,
                    feature_id=feature_id,
                    relation_type="implements" if counted else "contextual_only",
                    reason=tier_reason,
                )
            )
            if counted and cit.access and cit.access.url:
                recruiter_actions.append(
                    f"Open the exact cited lines: {cit.file_path}"
                    + (f" L{cit.start_line}–L{cit.end_line}" if cit.start_line else "")
                )

        # ── Website runtime evidence (identity-validated) ───────────────────
        for item in chain.get("website_evidence") or []:
            card = item.get("website_evidence_card") or {}
            if pid:
                identity_state, identity_reasons = _website_identity_for_card(
                    card,
                    item,
                    project_title=project_title,
                    repo_name=(pmeta or {}).get("repo_name"),
                    repo_full=(pmeta or {}).get("repo_full"),
                    deployed_url=(pmeta or {}).get("deployed_url"),
                )
            else:
                identity_state, identity_reasons = "unrelated", [
                    "This recording is not attached to any project — vault-only context."
                ]
            relevance_key = str(
                item.get("website_skill_relevance_key") or card.get("skill_relevance_key") or ""
            )
            skill_direct = relevance_key.endswith("_evidence")
            counted = identity_state == "matched_direct" and skill_direct and attached
            feature_id = None
            workflow_label = str(card.get("website_purpose_label") or "")
            if workflow_label and identity_state == "matched_direct":
                feature_id = _register_feature(
                    features,
                    project_id=str(pid) if pid else None,
                    title=workflow_label,
                    feature_type="runtime_workflow",
                    skill=skill,
                    route=card.get("route_or_page"),
                    workflow=str(card.get("behavior_claim") or "") or None,
                )
            video = _website_video_descriptor(item, card)
            cited_start = next(
                (
                    seg.get("start_label")
                    for seg in (video.get("cited_segments") or [])
                    if seg.get("start_label")
                ),
                None,
            )
            actions = []
            live_access = _website_access(card)
            if live_access and live_access.get("available"):
                actions.append(live_access)
            if video.get("access"):
                actions.append(video["access"])
            if item.get("website_analysis_path"):
                actions.append(
                    {
                        "kind": "website_analysis",
                        "label": "Open Website Proof analysis",
                        "available": True,
                        "action_label": "View analysis",
                        "url": str(item["website_analysis_path"]),
                        "requires_owner_permission": True,
                    }
                )
            cit = EvidenceCitation(
                evidence_id=_next_id("ev-web"),
                proof_type=_WEBSITE,
                citation_type=("website_video_timestamp" if cited_start else "website_workflow"),
                source_proof_id=str(item.get("source_id") or "") or None,
                source_artifact_id=item.get("website_artifact_id"),
                project_id=str(pid) if pid else None,
                skill_id=claim.skill_id,
                claim_id=claim.id,
                feature_id=feature_id,
                source_title=str(item.get("title") or "Website recording"),
                source_locator=card.get("route_or_page"),
                route_or_page=card.get("route_or_page"),
                observed_action=card.get("user_action_observed"),
                observed_output=card.get("output_observed"),
                timestamp_start_label=cited_start,
                explanation=str(card.get("behavior_claim") or item.get("safe_summary") or ""),
                relevance=str(
                    item.get("website_skill_relevance_summary")
                    or card.get("skill_relevance_summary")
                    or ""
                ),
                strength=(
                    "Runtime demonstration" if counted else "Context only"
                ),
                identity_state=identity_state,
                identity_reasons=identity_reasons,
                counted_as_direct_evidence=counted,
                project_relationship=_project_relationship(
                    project_id=str(pid) if pid else None,
                    attached=attached,
                    state=(
                        "mismatched_project"
                        if identity_state == "mismatched"
                        else str(item.get("project_relationship_state") or "") or None
                    ),
                    reason=identity_reasons[0] if identity_reasons else None,
                    project_title=project_title if pid else None,
                ),
                evidence_status=(
                    "ready" if counted else "needs_confirmation"
                    if identity_state == "possible_match_review"
                    else "excluded" if identity_state == "mismatched" else "ready"
                ),
                evidence_quality="supporting" if counted else "context",
                privacy_state="public" if item.get("public_safe") else "private",
                publication_state="published" if item.get("public_safe") else "private",
                access=live_access,
                actions=actions,
                video=video,
                limitations=_listify(card.get("limitation") or item.get("limitation")),
            )
            citations.append(cit)
            if counted:
                chain_counted.append(cit)
                relations.append(
                    EvidenceRelation(
                        source_evidence_id=cit.evidence_id,
                        claim_id=claim.id,
                        feature_id=feature_id,
                        relation_type="demonstrates_runtime",
                        reason="Identity-matched recording demonstrating the claimed behaviour at runtime.",
                    )
                )
            elif identity_state == "mismatched":
                chain_mismatch = True
                relations.append(
                    EvidenceRelation(
                        source_evidence_id=cit.evidence_id,
                        claim_id=claim.id,
                        relation_type="mismatched",
                        reason=identity_reasons[0] if identity_reasons else "Identity mismatch.",
                    )
                )
                contradictions.append(
                    Contradiction(
                        contradiction_id=_next_id("contra"),
                        kind="identity_mismatch",
                        claim_id=claim.id,
                        evidence_ids=[cit.evidence_id],
                        description=(
                            f"A website recording attached to '{project_title}' identifies as a different "
                            "application. It is excluded from this claim and does not corroborate anything."
                        )
                        + (" " + identity_reasons[0] if identity_reasons else ""),
                        recommended_action=(
                            "Review this recording in the Proof Vault: detach it, reassign it to the "
                            "project it actually shows, or confirm the association explicitly."
                        ),
                    )
                )
            else:
                chain_context = True
                relations.append(
                    EvidenceRelation(
                        source_evidence_id=cit.evidence_id,
                        claim_id=claim.id,
                        relation_type=(
                            "same_project_unmapped" if not skill_direct else "contextual_only"
                        ),
                        reason=(
                            identity_reasons[0]
                            if identity_state == "possible_match_review" and identity_reasons
                            else "Observed behaviour is product context for this skill, not direct runtime proof."
                        ),
                        confidence_label=(
                            "needs review" if identity_state == "possible_match_review" else "deterministic"
                        ),
                    )
                )

        # ── Document evidence ───────────────────────────────────────────────
        for doc in chain.get("document_correlations") or []:
            # An exact source-native locator is required to COUNT: a page, a
            # typed block (table/chart/diagram/code/…), a figure reference, or a
            # real section heading. "The text mentions the skill" never counts.
            has_locator = bool(
                doc.get("page_number")
                or doc.get("section_label")
                or doc.get("citation")
                or doc.get("figure_reference")
                or str(doc.get("block_type") or "").strip().lower()
                not in ("", "paragraph", "heading")
            )
            counted = has_locator and attached
            feature_id = None
            if doc.get("section_label"):
                feature_id = _register_feature(
                    features,
                    project_id=str(pid) if pid else None,
                    title=str(doc["section_label"]),
                    feature_type="document_section",
                    skill=skill,
                    document_section=str(doc["section_label"]),
                )
            cit = EvidenceCitation(
                evidence_id=_next_id("ev-doc"),
                proof_type=_DOCUMENT,
                citation_type=(
                    f"document_{_document_block(doc)['block_type']}"
                ),
                source_proof_id=str(doc.get("source_id") or "") or None,
                project_id=str(pid) if pid else None,
                skill_id=claim.skill_id,
                claim_id=claim.id,
                feature_id=feature_id,
                source_title=str(doc.get("document_title") or "Document"),
                page_number=doc.get("page_number"),
                section_title=doc.get("section_label"),
                figure_or_table=doc.get("figure_reference"),
                transcript_excerpt=None,
                code_excerpt=None,
                explanation=str(doc.get("why_supported") or doc.get("reason") or ""),
                relevance=str(doc.get("corroborates") or ""),
                strength="Design documentation" if counted else "Context only",
                counted_as_direct_evidence=counted,
                project_relationship=_project_relationship(
                    project_id=str(pid) if pid else None,
                    attached=attached,
                    project_title=project_title if pid else None,
                ),
                evidence_status="ready" if counted else "excluded",
                evidence_quality="supporting" if counted else "context",
                document_access=_document_access(doc),
                document_block=_document_block(doc),
                actions=_document_actions(doc),
                limitations=_listify(doc.get("limitation"))
                + ([] if has_locator else ["No page/section locator was extracted for this document."]),
            )
            # Keep the safe snippet as the citation excerpt (bounded by builder).
            cit.transcript_excerpt = doc.get("safe_snippet")
            citations.append(cit)
            if counted:
                chain_counted.append(cit)
            else:
                chain_context = True
            relations.append(
                EvidenceRelation(
                    source_evidence_id=cit.evidence_id,
                    claim_id=claim.id,
                    feature_id=feature_id,
                    relation_type="explains_design" if counted else "contextual_only",
                    reason=str(doc.get("why_supported") or "Document correlation without an exact locator."),
                    confidence_label=(
                        "deterministic"
                        if doc.get("correlation_confidence") == "direct attachment"
                        else "likely"
                    ),
                )
            )

        # ── Project Defense evidence ────────────────────────────────────────
        inspection = chain.get("project_defense_inspection") or []
        for card in inspection:
            mapped = str(card.get("mapped_skill") or "")
            # Only a genuine, targeted explanation counts — "Needs review",
            # "Generic explanation", and privacy-withheld answers are visible
            # but never counted (the old `!= "Not explained"` check let a
            # needs-review denial count as authorship evidence).
            explained = str(card.get("qualitative_status") or "Not explained") in (
                "Explained with evidence",
                "Partially explained",
            )
            stance = str(card.get("ownership_stance") or "none")
            counted = bool(mapped) and explained and attached
            feature_id = None
            if card.get("question_text"):
                feature_id = _register_feature(
                    features,
                    project_id=str(pid) if pid else None,
                    title=str(card["question_text"])[:90],
                    feature_type="defense_topic",
                    skill=skill,
                )
            defense_video = _defense_video_descriptor(card)
            defense_actions = []
            if defense_video and defense_video.get("access"):
                defense_actions.append(defense_video["access"])
            cit = EvidenceCitation(
                evidence_id=_next_id("ev-def"),
                proof_type=_DEFENSE,
                citation_type="defense_timestamp" if card.get("timestamp_label") else "defense_transcript",
                source_proof_id=str(card.get("session_id") or "") or None,
                project_id=str(pid) if pid else None,
                skill_id=claim.skill_id,
                claim_id=claim.id,
                feature_id=feature_id,
                source_title=f"Project Defense — {project_title}",
                question_text=card.get("question_text"),
                transcript_excerpt=card.get("safe_transcript_excerpt"),
                timestamp_start_label=card.get("transcript_excerpt_start_label")
                or card.get("timestamp_label"),
                timestamp_end_label=card.get("transcript_excerpt_end_label"),
                explanation=str(card.get("safe_answer_summary") or ""),
                relevance=str(card.get("what_this_demonstrates") or ""),
                strength=(
                    _defense_strength_label(str(card.get("claim_type") or ""), stance)
                    if counted
                    else "Ownership clarification"
                    if stance == "denied"
                    else "Context only"
                ),
                counted_as_direct_evidence=counted,
                project_relationship=_project_relationship(
                    project_id=str(pid) if pid else None,
                    attached=attached,
                    project_title=project_title if pid else None,
                ),
                evidence_status="ready" if counted else "excluded",
                evidence_quality="supporting" if counted else "context",
                actions=defense_actions,
                video=defense_video,
                limitations=_listify(card.get("limitation")),
            )
            citations.append(cit)
            if counted:
                chain_counted.append(cit)
            else:
                chain_context = True
            relations.append(
                EvidenceRelation(
                    source_evidence_id=cit.evidence_id,
                    claim_id=claim.id,
                    feature_id=feature_id,
                    relation_type=(
                        "clarifies_ownership"
                        if stance == "denied"
                        else "explains_authorship"
                        if counted and cit.strength == "Contribution explanation"
                        else "explains_understanding"
                        if counted
                        else "contextual_only"
                    ),
                    reason=str(card.get("what_this_demonstrates") or "Defense answer without a skill mapping."),
                )
            )
        # Defense/video items present but no analyzed inspection card → the
        # captured-pending state: visible, never counted.
        raw_defense = (chain.get("defense_evidence") or []) + (chain.get("video_evidence") or [])
        if raw_defense and not inspection:
            chain_pending = True
            cit = EvidenceCitation(
                evidence_id=_next_id("ev-def"),
                proof_type=_DEFENSE,
                project_id=str(pid) if pid else None,
                skill_id=claim.skill_id,
                claim_id=claim.id,
                source_title=f"Project Defense — {project_title}",
                explanation="Defense captured, analysis pending.",
                relevance=(
                    "A defense session exists for this project but has no analyzed, skill-mapped "
                    "answers yet — it is shown for transparency and not counted as skill evidence."
                ),
                strength="Analysis pending",
                analysis_pending=True,
                counted_as_direct_evidence=False,
                project_relationship=_project_relationship(
                    project_id=str(pid) if pid else None,
                    attached=attached,
                    project_title=project_title if pid else None,
                ),
                evidence_status="analysis_pending",
                evidence_quality="insufficient",
                limitations=["Not counted until Q/A analysis maps answers to this skill."],
            )
            citations.append(cit)
            relations.append(
                EvidenceRelation(
                    source_evidence_id=cit.evidence_id,
                    claim_id=claim.id,
                    relation_type="contextual_only",
                    reason="Captured defense awaiting analysis.",
                )
            )
            gaps.append(
                EvidenceGap(
                    claim_id=claim.id,
                    proof_type=_DEFENSE,
                    description=f"Project Defense for {project_title} is captured but not yet analyzed.",
                    recommended_action="Run defense analysis to map answers to skill claims.",
                )
            )

        # ── First-class Video Proofs (migration 057 cards) ──────────────────
        for vcard in chain.get("video_proofs") or []:
            cit = EvidenceCitation(
                evidence_id=_next_id("ev-vid"),
                proof_type=_VIDEO,
                project_id=str(pid) if pid else None,
                skill_id=claim.skill_id,
                claim_id=claim.id,
                source_title=str(vcard.get("title") or "Video Proof"),
                explanation=str(vcard.get("demo_summary") or ""),
                relevance=str(vcard.get("proof_strength_label") or ""),
                strength="Context only",
                counted_as_direct_evidence=False,
                video=_video_proof_descriptor(vcard),
                limitations=[str(x) for x in (vcard.get("limitations") or [])],
            )
            citations.append(cit)
            chain_context = True
            relations.append(
                EvidenceRelation(
                    source_evidence_id=cit.evidence_id,
                    claim_id=claim.id,
                    relation_type="contextual_only",
                    reason="A demo video shows behaviour but does not by itself verify a skill.",
                )
            )

        # ── Claim synthesis ─────────────────────────────────────────────────
        claim.feature_ids = sorted(
            {c.feature_id for c in citations if c.claim_id == claim.id and c.feature_id}
        )
        group: CorroborationGroup | None = None
        if pid:  # standalone vault proofs share no confirmed project → never corroborate
            group = _build_corroboration(claim, chain_counted, _next_id("corro"))
            if group:
                corroborations.append(group)
                for cit in chain_counted[1:]:
                    relations.append(
                        EvidenceRelation(
                            source_evidence_id=cit.evidence_id,
                            target_evidence_id=chain_counted[0].evidence_id,
                            claim_id=claim.id,
                            relation_type="corroborates",
                            reason=group.alignment_reason,
                        )
                    )
        claim.qualitative_status = _claim_status(
            counted=chain_counted,
            has_primary_impl=any(c.github_tier == "primary_implementation" for c in chain_counted),
            corroborated=group is not None,
            pending=chain_pending,
            mismatched=chain_mismatch,
            context_only=chain_context,
        )
        claim.strongest_evidence_tier = _strongest_tier_label(chain_counted, chain_pending)
        # Candidate attribution — the separately-evidenced candidate side of
        # this project-scoped claim. Understanding/usage flags come ONLY from
        # counted candidate-explanation / runtime citations; the ownership
        # state comes ONLY from candidate↔artifact relationship evidence.
        if pid:
            claim.candidate_attribution = CandidateAttribution(
                **build_candidate_attribution(
                    ownership=ownership,
                    skill_name=skill,
                    understanding_demonstrated=any(
                        c.proof_type in (_DEFENSE, _VIDEO) for c in chain_counted
                    ),
                    usage_demonstrated=any(c.proof_type == _WEBSITE for c in chain_counted),
                )
            )
            state = claim.candidate_attribution.state
            if state == "denied_by_candidate":
                claim.limitations.append(
                    "The candidate explicitly stated they did not build or contribute to this "
                    "project — no candidate implementation claim is made."
                )
            elif state == "conflicted":
                claim.limitations.append(
                    "Ownership evidence for this project conflicts — candidate implementation "
                    "claims are blocked until resolved."
                )
                contradictions.append(
                    Contradiction(
                        contradiction_id=_next_id("contra"),
                        kind="ownership_conflict",
                        claim_id=claim.id,
                        description=(
                            "Ownership statements/evidence for this project conflict. The conflict "
                            "is surfaced, never auto-resolved in the candidate's favour, and blocks "
                            "candidate implementation claims."
                        ),
                        recommended_action=(
                            "Review the candidate's defense statements and attribution evidence "
                            "before relying on any contribution claim."
                        ),
                    )
                )
        if not pid:
            claim.limitations.append(
                "Standalone vault proof — unattached sources share no confirmed project, so they are "
                "never treated as corroborating each other."
            )
        if chain_mismatch:
            claim.limitations.append(
                "An attached recording failed the project-identity check and is excluded from this claim."
            )
        # Missing-proof gaps per claim (stable sections for future proof types).
        present = {c.proof_type for c in citations if c.claim_id == claim.id}
        for ptype, action in (
            (_GITHUB, "Attach a GitHub Proof with validated implementation lines."),
            (_WEBSITE, "Record a Website Proof of this project's own application."),
            (_DOCUMENT, "Attach a document that cites this skill with page/section locators."),
            (_DEFENSE, "Complete an analyzed Project Defense mapping answers to this skill."),
        ):
            if pid and ptype not in present:
                gaps.append(
                    EvidenceGap(
                        claim_id=claim.id,
                        proof_type=ptype,
                        description=f"No {ptype} evidence supports this claim yet.",
                        recommended_action=action,
                    )
                )
        claims.append(claim)

    # Post-passes: fold duplicate video-of-defense citations, group weak
    # repo-level context ONCE for the whole report, then compute the honest
    # per-claim + map-level source counts from what remains.
    _mark_duplicate_video_citations(citations)
    citations, relations = _group_weak_context(claims, citations, relations)
    for claim in claims:
        claim.source_counts = compute_source_counts(
            [c for c in citations if c.claim_id == claim.id]
        )
    cem = ClaimEvidenceMap(
        scope="skill_report",
        skill_name=skill,
        claims=claims,
        features=list(features.values()),
        citations=citations,
        relations=relations,
        corroborations=corroborations,
        contradictions=contradictions,
        gaps=gaps,
        source_counts=_aggregate_source_counts(claims),
        recruiter_actions=_dedupe(recruiter_actions)[:8],
        limitations=[str(g) for g in (report.get("gaps") or [])][:8],
    )
    return cem.model_dump()


# ── Project Report entry point ────────────────────────────────────────────────


def build_project_claim_evidence_map(report: dict[str, Any]) -> dict[str, Any]:
    """Build the canonical claim→evidence map from a ``build_student_vbr_report``
    payload (skill matrix + evidence traces). Purely deterministic."""
    project_id = str(report.get("project_id") or "")
    project_title = str(report.get("project_title") or "Project")
    repo_full = str(report.get("repo_full_name") or "")
    repo_name = repo_full.split("/")[-1] if repo_full else ""
    deployed_url = report.get("deployed_url")

    traces = {str(t.get("trace_id")): t for t in (report.get("evidence_traces") or [])}
    website_identity_by_target = _project_website_identities(
        report, project_title=project_title, repo_name=repo_name, deployed_url=deployed_url
    )

    claims: list[SkillClaim] = []
    citations: list[EvidenceCitation] = []
    relations: list[EvidenceRelation] = []
    corroborations: list[CorroborationGroup] = []
    contradictions: list[Contradiction] = []
    gaps: list[EvidenceGap] = []
    features: dict[tuple[str, str], ProjectFeature] = {}
    ev_seq = 0

    def _next_id(prefix: str) -> str:
        nonlocal ev_seq
        ev_seq += 1
        return f"{prefix}-{ev_seq}"

    defense_pending = bool(
        (report.get("evidence_package") or {}).get("project_defense_completed")
        and report.get("project_defense_analysis") is None
    )

    # Candidate↔project ownership for the whole report: the report builder
    # passes its precomputed assessment; otherwise assess from the report's own
    # defense answer evidence. Artifact evidence contributes NOTHING here.
    ownership = report.get("candidate_ownership")
    if not isinstance(ownership, dict):
        ownership = assess_project_ownership(
            answer_items=report.get("defense_answer_evidence") or [],
            repo_analysis=report.get("repo_analysis"),
        )
    ownership_conflict_logged = False

    for row in report.get("skill_evidence") or []:
        skill = str(row.get("skill") or "")
        claim = SkillClaim(
            id=_next_id("claim"),
            project_id=project_id,
            skill_id=skill.lower().replace(" ", "-"),
            skill_name=skill,
            claim_scope="project",
            claim_subject="project",
            # PROJECT-scoped by construction — candidate attribution is a
            # separate claim with its own evidence bar (see below).
            claim_text=f"{skill} is demonstrated in the project {project_title}.",
        )
        counted: list[EvidenceCitation] = []
        mismatch = False
        context_only = False

        for tid in row.get("evidence_traces") or []:
            trace = traces.get(str(tid))
            if not trace:
                continue
            cit, relation, flags = _citation_from_trace(
                trace,
                claim=claim,
                project_id=project_id,
                project_title=project_title,
                skill=skill,
                features=features,
                website_identity_by_target=website_identity_by_target,
                next_id=_next_id,
            )
            citations.append(cit)
            relations.append(relation)
            if cit.counted_as_direct_evidence:
                counted.append(cit)
            if flags.get("mismatch"):
                mismatch = True
                contradictions.append(
                    Contradiction(
                        contradiction_id=_next_id("contra"),
                        kind="identity_mismatch",
                        claim_id=claim.id,
                        evidence_ids=[cit.evidence_id],
                        description=(
                            f"A website recording attached to '{project_title}' identifies as a different "
                            "application; it is excluded from this skill claim. "
                            + (cit.identity_reasons[0] if cit.identity_reasons else "")
                        ),
                        recommended_action=(
                            "Review the recording: detach it, reassign it to the project it actually "
                            "shows, or explicitly confirm the association."
                        ),
                    )
                )
            if flags.get("context"):
                context_only = True

        if defense_pending:
            cit = EvidenceCitation(
                evidence_id=_next_id("ev-def"),
                proof_type=_DEFENSE,
                project_id=project_id,
                skill_id=claim.skill_id,
                claim_id=claim.id,
                source_title=f"Project Defense — {project_title}",
                explanation="Defense captured, analysis pending.",
                relevance=(
                    "Answers were recorded but not yet analyzed — shown for transparency, "
                    "not counted as skill evidence."
                ),
                strength="Analysis pending",
                analysis_pending=True,
                counted_as_direct_evidence=False,
                limitations=["Not counted until Q/A analysis maps answers to this skill."],
            )
            citations.append(cit)
            relations.append(
                EvidenceRelation(
                    source_evidence_id=cit.evidence_id,
                    claim_id=claim.id,
                    relation_type="contextual_only",
                    reason="Captured defense awaiting analysis.",
                )
            )

        claim.feature_ids = sorted(
            {c.feature_id for c in citations if c.claim_id == claim.id and c.feature_id}
        )
        group = _build_corroboration(claim, counted, _next_id("corro"))
        if group:
            corroborations.append(group)
        claim.qualitative_status = _claim_status(
            counted=counted,
            has_primary_impl=any(c.github_tier == "primary_implementation" for c in counted),
            corroborated=group is not None,
            pending=defense_pending and not counted,
            mismatched=mismatch,
            context_only=context_only,
        )
        claim.strongest_evidence_tier = _strongest_tier_label(counted, defense_pending)
        claim.candidate_attribution = CandidateAttribution(
            **build_candidate_attribution(
                ownership=ownership,
                skill_name=skill,
                understanding_demonstrated=any(
                    c.proof_type in (_DEFENSE, _VIDEO) for c in counted
                ),
                usage_demonstrated=any(c.proof_type == _WEBSITE for c in counted),
            )
        )
        state = claim.candidate_attribution.state
        if state == "denied_by_candidate":
            claim.limitations.append(
                "The candidate explicitly stated they did not build or contribute to this "
                "project — no candidate implementation claim is made."
            )
        elif state == "conflicted":
            claim.limitations.append(
                "Ownership evidence for this project conflicts — candidate implementation "
                "claims are blocked until resolved."
            )
            if not ownership_conflict_logged:
                ownership_conflict_logged = True
                contradictions.append(
                    Contradiction(
                        contradiction_id=_next_id("contra"),
                        kind="ownership_conflict",
                        description=(
                            "Ownership statements/evidence for this project conflict. The conflict "
                            "is surfaced, never auto-resolved in the candidate's favour, and blocks "
                            "candidate implementation claims."
                        ),
                        recommended_action=(
                            "Review the candidate's defense statements and attribution evidence "
                            "before relying on any contribution claim."
                        ),
                    )
                )
        if mismatch:
            claim.limitations.append(
                "An attached recording failed the project-identity check and is excluded from this claim."
            )
        for lim in row.get("limitations") or []:
            claim.limitations.append(str(lim))
        claims.append(claim)

    if defense_pending:
        gaps.append(
            EvidenceGap(
                proof_type=_DEFENSE,
                description="Project Defense is captured but not yet analyzed.",
                recommended_action="Run defense analysis to map answers to skill claims.",
            )
        )

    # Post-passes shared with the Skill Report: fold duplicate video-of-defense
    # citations, group weak repo-level context once, compute honest counts.
    _mark_duplicate_video_citations(citations)
    citations, relations = _group_weak_context(claims, citations, relations)
    for claim in claims:
        claim.source_counts = compute_source_counts(
            [c for c in citations if c.claim_id == claim.id]
        )
    cem = ClaimEvidenceMap(
        scope="project_report",
        project_id=project_id,
        # The ONE block a recruiter reads to understand the candidate↔project
        # relationship — built from ownership evidence only, never inferred
        # from artifact evidence.
        project_relationship=CandidateAttribution(
            **build_candidate_attribution(ownership=ownership)
        ),
        claims=claims,
        features=list(features.values()),
        citations=citations,
        relations=relations,
        corroborations=corroborations,
        contradictions=contradictions,
        gaps=gaps,
        source_counts=_aggregate_source_counts(claims),
        limitations=[str(x) for x in (report.get("limitations") or [])][:8],
    )
    return cem.model_dump()


def _project_website_identities(
    report: dict[str, Any], *, project_title: str, repo_name: str, deployed_url: Any
) -> dict[str, tuple[str, list[str]]]:
    """Identity classification per attached website proof, keyed by target label.

    Uses the richer ``website_skill_evidence`` entries (app context / domain /
    purpose) when present; entries without runtime identity fall back to a
    review-needed state — never silently counted."""
    out: dict[str, tuple[str, list[str]]] = {}
    for entry in report.get("website_skill_evidence") or []:
        target = str(entry.get("target_website") or "").strip()
        if entry.get("project_identity_state"):
            state = str(entry["project_identity_state"])
            reasons = [str(r) for r in (entry.get("project_identity_reasons") or [])]
        else:
            state, reasons = classify_website_identity(
                identity_texts=[str(entry.get("app_context") or "")],
                target_domain=entry.get("target_domain") or target,
                project_title=project_title,
                repo_name=repo_name,
                deployed_url=deployed_url,
            )
        out[target.lower()] = (state, reasons)
        if entry.get("proof_session_id"):
            out[f"session:{entry['proof_session_id']}"] = (state, reasons)
    return out


def _website_video_from_trace(trace: dict[str, Any]) -> dict[str, Any]:
    retained = bool(trace.get("website_replay_available") and trace.get("website_replay_path"))
    duration = trace.get("website_replay_duration_seconds")
    duration_label = None
    if isinstance(duration, (int, float)) and duration >= 0:
        whole = int(duration)
        duration_label = f"{whole // 60:02d}:{whole % 60:02d}"
    timeline = [
        {
            "timestamp_label": event.get("timestamp_label"),
            "description": str(event.get("description") or ""),
        }
        for event in (trace.get("website_timeline") or [])
        if isinstance(event, dict) and event.get("description")
    ]
    cited = [e for e in timeline if e.get("timestamp_label")][:1]
    limitations: list[str] = []
    if not trace.get("is_publicly_openable"):
        limitations.append(
            "Local/private recording: recruiters cannot independently open the localhost application; "
            "the replay is permission-gated evidence of what ran at recording time."
        )
    if not retained:
        limitations.append(
            "No retained replay artifact is registered for this historical Website Proof."
        )
    return {
        "proof_type": _WEBSITE,
        "recording_available": retained,
        "availability": "retained" if retained else "not_retained",
        "duration_label": duration_label,
        "mime_type": trace.get("website_replay_mime_type"),
        "transcript_available": False,
        "poster_available": False,
        "timeline_events": timeline,
        "cited_segments": [
            {
                "start_label": e.get("timestamp_label"),
                "end_label": None,
                "description": e.get("description"),
            }
            for e in cited
        ],
        "access": (
            {
                "kind": "recorded_replay",
                "label": "Play retained Website Proof",
                "available": True,
                "action_label": "Play cited moment" if cited else "Open full recording",
                "url": trace.get("website_replay_path"),
                "requires_owner_permission": True,
                "note": "Playback is served through the owner-gated proof artifact route.",
            }
            if retained
            else None
        ),
        "limitations": limitations,
    }


def _citation_from_trace(
    trace: dict[str, Any],
    *,
    claim: SkillClaim,
    project_id: str,
    project_title: str,
    skill: str,
    features: dict[tuple[str, str], ProjectFeature],
    website_identity_by_target: dict[str, tuple[str, list[str]]],
    next_id: Any,
) -> tuple[EvidenceCitation, EvidenceRelation, dict[str, bool]]:
    """Normalize ONE project-report evidence trace into a canonical citation."""
    source_type = str(trace.get("source_type") or "")
    flags = {"mismatch": False, "context": False}
    feature_id = None
    counted = False
    relation_type = "contextual_only"
    strength = "Context only"
    github_tier = None
    identity_state = None
    identity_reasons: list[str] = []

    if source_type == _GITHUB:
        line_level = bool(trace.get("line_start") and trace.get("file_path"))
        if line_level:
            # Grade the stored snippet structurally (the same deterministic
            # grader the Skill Report uses) — a bare route decorator, import
            # block, docstring, or config constant at exact lines is still not
            # an implementation body and must never count as one.
            from app.services.github_python_evidence_focus import (
                classify_code_block_purpose,
                effective_evidence_grade,
            )
            from app.services.github_skill_evidence_service import (
                evidence_quality_grade,
                is_ml_skill,
            )

            grade = evidence_quality_grade(
                skill,
                trace.get("file_path"),
                trace.get("code_snippet"),
                symbol_name=trace.get("function_name"),
                line_start=trace.get("line_start"),
                line_end=trace.get("line_end"),
            )
            # Read-time ML semantic validation (same gate as the Skill Report):
            # a serving-only / route-only body can never present as Machine
            # Learning primary implementation — it fails closed to supporting.
            grade = effective_evidence_grade(
                grade,
                is_ml=is_ml_skill(skill),
                reason=trace.get("safe_summary"),
                code_snippet=trace.get("code_snippet"),
                file_path=trace.get("file_path"),
                function_name=trace.get("function_name"),
            )
            github_tier = _GRADE_TO_TIER.get(grade, "weak_signal")
            # Countability contract (same rule as the Skill Report): a block
            # whose purpose cannot be concretely resolved from its stored
            # snippet is visible but never counted as implementation evidence.
            if github_tier in _COUNTING_TIERS:
                purpose_key = classify_code_block_purpose(
                    grade=grade,
                    code_snippet=trace.get("code_snippet"),
                    file_path=trace.get("file_path"),
                    function_name=trace.get("function_name"),
                )
                if not is_countable_code_purpose(purpose_key):
                    github_tier = "weak_signal"
        else:
            github_tier = "weak_signal"
        counted = github_tier in _COUNTING_TIERS
        relation_type = "implements" if counted else "contextual_only"
        strength = _TIER_STRENGTH_LABEL[github_tier]
        if trace.get("file_path"):
            feature_id = _register_feature(
                features,
                project_id=project_id,
                title=(
                    f"{trace['function_name']}() · {trace['file_path']}"
                    if trace.get("function_name")
                    else str(trace["file_path"])
                ),
                feature_type="code_symbol",
                skill=skill,
                repo_path=str(trace["file_path"]),
            )
    elif source_type == _WEBSITE:
        session_key = (
            f"session:{trace.get('proof_session_id')}" if trace.get("proof_session_id") else ""
        )
        key = str(trace.get("source_title") or "").split(" — ", 1)[0].strip().lower()
        identity_state, identity_reasons = website_identity_by_target.get(
            session_key,
            website_identity_by_target.get(
                key,
            (
                "possible_match_review",
                [
                    "No recorded application-identity signals were stored for this proof — "
                    "association is attachment-only and needs owner review."
                ],
            ),
            ),
        )
        counted = identity_state == "matched_direct"
        relation_type = "demonstrates_runtime" if counted else (
            "mismatched" if identity_state == "mismatched" else "contextual_only"
        )
        strength = "Runtime demonstration" if counted else "Context only"
        flags["mismatch"] = identity_state == "mismatched"
    document_block: dict[str, Any] | None = None
    if source_type == _DOCUMENT:
        # COUNT only with an exact source-native locator: an extraction-flagged
        # exact locator, a page, a typed block, a figure reference, or a real
        # section citation. "Text mentions the skill" stays context-only.
        has_locator = bool(
            trace.get("has_exact_locator")
            or trace.get("page_number")
            or trace.get("citation")
            or trace.get("figure_reference")
            or str(trace.get("block_type") or "").strip().lower()
            not in ("", "paragraph", "heading")
        )
        counted = has_locator
        relation_type = "explains_design" if counted else "contextual_only"
        strength = "Design documentation" if counted else "Context only"
        # Block-aware locator built from the SAME stored trace fields (never
        # invented): stored block types pass through verbatim, explicit
        # "Table …"/diagram references classify, ambiguous figures fail closed
        # to unknown_visual_region, prose stays paragraph.
        document_block = _document_block(
            {
                "document_title": trace.get("source_title"),
                "page_number": trace.get("page_number"),
                "block_type": trace.get("block_type"),
                "figure_reference": trace.get("figure_reference") or trace.get("citation"),
                "safe_snippet": trace.get("snippet"),
                "table_cells": trace.get("table_cells") or [],
                "visual_description": trace.get("visual_description"),
                "nearby_caption": trace.get("nearby_caption"),
            }
        )
        if trace.get("citation"):
            feature_id = _register_feature(
                features,
                project_id=project_id,
                title=str(trace["citation"])[:90],
                feature_type="document_section",
                skill=skill,
                document_section=str(trace["citation"]),
            )
    elif source_type in (_DEFENSE, _VIDEO):
        answered = bool(trace.get("question_text") and trace.get("answer_excerpt"))
        stance = detect_ownership_stance(trace.get("answer_excerpt"))
        if stance == "denied":
            # An explicit ownership denial is visible ownership-clarification
            # evidence — it never counts as skill evidence and never reads as
            # an authorship explanation.
            counted = False
            relation_type = "clarifies_ownership"
            strength = "Ownership clarification"
        else:
            counted = answered
            relation_type = "explains_understanding" if answered else "contextual_only"
            strength = "Understanding explanation" if answered else "Context only"

    if not counted:
        flags["context"] = flags["context"] or not flags["mismatch"]

    website_video = _website_video_from_trace(trace) if source_type == _WEBSITE else None
    actions: list[dict[str, Any]] = []
    trace_access = _trace_access(trace)
    if trace_access:
        actions.append(trace_access)
    if source_type == _DOCUMENT:
        # Owner-gated retained-original actions; empty on public surfaces
        # because the descriptor is blanked there.
        actions.extend(_document_original_actions_from_trace(trace))
    if website_video and website_video.get("access"):
        actions.append(website_video["access"])
    if source_type == _WEBSITE and trace.get("website_analysis_path"):
        actions.append(
            {
                "kind": "website_analysis",
                "label": "Open Website Proof analysis",
                "available": True,
                "action_label": "View analysis",
                "url": trace.get("website_analysis_path"),
                "requires_owner_permission": True,
            }
        )
    cit = EvidenceCitation(
        evidence_id=next_id("ev"),
        proof_type=source_type,
        citation_type=(
            "github_code_lines" if source_type == _GITHUB and trace.get("line_start")
            else "website_video_timestamp" if source_type == _WEBSITE and trace.get("timestamp_label")
            else "website_workflow" if source_type == _WEBSITE
            else f"document_{document_block['block_type']}" if document_block
            else "defense_timestamp" if source_type in (_DEFENSE, _VIDEO) and trace.get("timestamp_label")
            else "source"
        ),
        source_proof_id=str(trace.get("proof_session_id") or "") or None,
        source_artifact_id=trace.get("website_artifact_id"),
        project_id=project_id,
        skill_id=claim.skill_id,
        claim_id=claim.id,
        feature_id=feature_id,
        source_title=str(trace.get("source_title") or source_type),
        source_locator=trace.get("location_label"),
        file_path=trace.get("file_path"),
        symbol_name=trace.get("function_name"),
        start_line=trace.get("line_start"),
        end_line=trace.get("line_end"),
        commit_sha=trace.get("commit_sha"),
        code_excerpt=trace.get("code_snippet"),
        page_number=trace.get("page_number"),
        section_title=trace.get("citation"),
        question_text=trace.get("question_text"),
        transcript_excerpt=trace.get("answer_excerpt") or trace.get("snippet"),
        timestamp_start_label=trace.get("timestamp_label") or trace.get("timestamp"),
        explanation=str(trace.get("safe_summary") or ""),
        relevance=str(trace.get("safe_detail") or ""),
        strength=strength,
        github_tier=github_tier,
        identity_state=identity_state,
        identity_reasons=identity_reasons,
        counted_as_direct_evidence=counted,
        project_relationship=_project_relationship(
            project_id=project_id,
            attached=True,
            state="mismatched_project" if identity_state == "mismatched" else None,
            reason=identity_reasons[0] if identity_reasons else None,
            project_title=project_title,
        ),
        evidence_status=(
            "excluded" if flags["mismatch"] else "needs_confirmation"
            if identity_state == "possible_match_review" else "ready" if counted else "excluded"
        ),
        evidence_quality=(
            "primary" if github_tier == "primary_implementation"
            else "supporting" if counted else "context"
        ),
        access=trace_access,
        actions=actions,
        video=website_video,
        document_block=document_block,
        document_access=(
            _document_access_from_trace(trace) if source_type == _DOCUMENT else None
        ),
        limitations=_listify(trace.get("limitation")),
    )
    relation = EvidenceRelation(
        source_evidence_id=cit.evidence_id,
        claim_id=claim.id,
        feature_id=feature_id,
        relation_type=relation_type,
        reason=(
            identity_reasons[0]
            if identity_reasons
            else str(trace.get("safe_summary") or "")[:200]
        ),
        confidence_label=(
            "needs review" if identity_state == "possible_match_review" else "deterministic"
        ),
    )
    return cit, relation, flags


# ── Access / video descriptor helpers (never store private URLs) ──────────────


def _listify(value: Any) -> list[str]:
    return [str(value)] if value else []


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _github_access(item: dict[str, Any]) -> dict[str, Any] | None:
    url = item.get("github_line_url") or item.get("public_url") or item.get("repo_url")
    if not url:
        return None
    line_level = bool(item.get("github_line_url"))
    return {
        "kind": "github_lines" if line_level else "github_repo",
        "label": "Open exact lines on GitHub" if line_level else "Open repository",
        "available": True,
        "action_label": "View code",
        "url": str(url),
    }


def _github_actions(item: dict[str, Any]) -> list[dict[str, Any]]:
    """All deterministic GitHub actions available for one citation."""
    actions: list[dict[str, Any]] = []
    exact = _github_access(item)
    if exact:
        actions.append(exact)
    repo = str(item.get("repo_url") or "").rstrip("/")
    if repo.startswith("https://github.com/"):
        if not any(a.get("url") == repo for a in actions):
            actions.append(
                {
                    "kind": "github_repo",
                    "label": "Open repository",
                    "available": True,
                    "action_label": "Open repository",
                    "url": repo,
                }
            )
        commit = str(item.get("commit_sha") or "").strip()
        if commit:
            actions.append(
                {
                    "kind": "github_commit",
                    "label": "Open cited commit",
                    "available": True,
                    "action_label": "Open commit",
                    "url": f"{repo}/commit/{commit}",
                }
            )
    return actions


def _document_actions(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Owner-gated document/page actions; never a storage or signed URL."""
    card = doc.get("inspection_card") if isinstance(doc.get("inspection_card"), dict) else {}
    actions: list[dict[str, Any]] = []
    open_url = card.get("document_open_url")
    page = doc.get("page_number") or card.get("page_number")
    if open_url:
        page_url = str(open_url) + (f"#page={page}" if page else "")
        actions.append(
            {
                "kind": "document_original",
                "label": "Open document at page" if page else "Open document",
                "available": True,
                "action_label": "Open document at page" if page else "Open document",
                "url": page_url,
                "requires_owner_permission": True,
            }
        )
        if page:
            actions.append(
                {
                    "kind": "document_block",
                    "label": "View cited source block",
                    "available": True,
                    "action_label": "View source block",
                    "url": page_url,
                    "requires_owner_permission": True,
                }
            )
    return actions


def _document_original_actions_from_trace(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """Owner-gated Open/Download actions for a document trace's RETAINED original.

    Built from the private report trace's ``document_original`` descriptor — an
    opaque artifact id + access-gated API routes (ownership re-checked on every
    request), never a storage path or signed URL. The public projection blanks
    the descriptor, so these actions can never appear on a public surface.
    """
    original = trace.get("document_original")
    if not isinstance(original, dict) or not original.get("available"):
        return []
    actions: list[dict[str, Any]] = []
    open_path = original.get("open_path")
    download_path = original.get("download_path")
    page = trace.get("page_number")
    # #page=N is honoured by in-browser PDF viewers; the fragment never reaches
    # the server. Non-PDF formats open from the top — the page/block locator on
    # the citation still says where to look.
    pdf = str(original.get("mime_type") or "").lower() == "application/pdf"
    if open_path:
        actions.append(
            {
                "kind": "document_original",
                "label": "Open original document",
                "available": True,
                "action_label": "Open original document",
                "url": str(open_path),
                "requires_owner_permission": True,
            }
        )
        if page and pdf:
            actions.append(
                {
                    "kind": "document_cited_page",
                    "label": f"Open cited page {page}",
                    "available": True,
                    "action_label": f"Open cited page {page}",
                    "url": f"{open_path}#page={page}",
                    "requires_owner_permission": True,
                }
            )
    if download_path:
        actions.append(
            {
                "kind": "document_download",
                "label": "Download original",
                "available": True,
                "action_label": "Download original",
                "url": str(download_path),
                "requires_owner_permission": True,
            }
        )
    return actions


def _document_access_from_trace(trace: dict[str, Any]) -> dict[str, Any]:
    """Honest retention/access state for a project-report document citation.

    Owner view: the private report trace carries the ``document_original``
    descriptor, so open/download availability reflects the genuinely retained
    artifact. Public view: the descriptor is blanked upstream, so this fails
    closed to the excerpts-only state.
    """
    original = trace.get("document_original")
    retained = bool(isinstance(original, dict) and original.get("available"))
    return {
        "retained": retained,
        "excerpts_only": not retained,
        "open_available": retained,
        "download_available": retained,
        "publication_state": "private",
        "original_filename": (original or {}).get("file_name") if retained else None,
        "mime_type": (original or {}).get("mime_type") if retained else None,
        "limitations": (
            []
            if retained
            else [
                "The original file was not retained for this document — only extracted "
                "excerpts and locators exist."
            ]
        ),
    }


def _trace_access(trace: dict[str, Any]) -> dict[str, Any] | None:
    if not trace.get("is_publicly_openable") or not trace.get("public_url"):
        return None
    return {
        "kind": "github_lines" if trace.get("line_start") else "live_site",
        "label": str(trace.get("public_url_label") or "Open source"),
        "available": True,
        "action_label": str(trace.get("public_url_label") or "Open"),
        "url": str(trace.get("public_url")),
    }


def _website_access(card: dict[str, Any]) -> dict[str, Any] | None:
    if card.get("is_public_live_url") and card.get("open_website_url"):
        return {
            "kind": "live_site",
            "label": "Open the live site",
            "available": True,
            "action_label": "Open live site",
            "url": str(card["open_website_url"]),
        }
    return {
        "kind": "recorded_replay",
        "label": str(card.get("verification_mode_label") or "Recorded replay only"),
        "available": False,
        "action_label": None,
        "note": str(card.get("verification_note") or "") or None,
    }


def _website_video_descriptor(item: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    """Honest retained-video state for a Website Proof.

    Availability comes only from the proof_artifacts registry hydrated by the
    canonical vault service. The replay path is an owner-gated API route, never a
    storage path or signed URL. Historical proofs still fail closed to
    ``not_retained``.
    """
    steps = [str(s) for s in (item.get("workflow_steps") or [])]
    timeline = [
        {
            "timestamp_label": event.get("timestamp_label"),
            "description": str(event.get("description") or ""),
        }
        for event in (item.get("workflow_timeline") or [])
        if isinstance(event, dict) and event.get("description")
    ]
    if not timeline:
        timeline = [{"timestamp_label": None, "description": s} for s in steps[:10]]
    cited = [event for event in timeline if event.get("timestamp_label")][:1]
    retained = bool(item.get("website_replay_available") and item.get("website_replay_path"))
    duration = item.get("website_replay_duration_seconds")
    duration_label = None
    if isinstance(duration, (int, float)) and duration >= 0:
        whole = int(duration)
        duration_label = f"{whole // 60:02d}:{whole % 60:02d}"
    local = str(card.get("verification_mode_key") or "") == "recorded_local" or str(
        card.get("target_domain") or ""
    ).lower() in {"localhost", "127.0.0.1"}
    limitations = []
    if local:
        limitations.append(
            "Local/private recording: recruiters cannot independently open the localhost application; "
            "the retained replay is permission-gated evidence of what ran at recording time."
        )
    if not retained:
        limitations.append(
            "No retained replay artifact is registered for this historical session; only derived "
            "workflow summaries and captured evidence are available."
        )
    return {
        "proof_type": _WEBSITE,
        "recording_available": retained,
        "availability": "retained" if retained else "not_retained",
        "duration_label": duration_label,
        "mime_type": item.get("website_replay_mime_type"),
        "transcript_available": False,
        "poster_available": bool(card.get("screenshot_available")),
        "timeline_events": timeline,
        "cited_segments": [
            {
                "start_label": event.get("timestamp_label"),
                "end_label": None,
                "description": event.get("description"),
            }
            for event in cited
        ],
        "access": (
            {
                "kind": "recorded_replay",
                "label": "Play retained Website Proof",
                "available": True,
                "action_label": "Play cited moment" if cited else "Open full recording",
                "url": str(item.get("website_replay_path")),
                "requires_owner_permission": True,
                "note": "Playback is served through the owner-gated proof artifact route.",
            }
            if retained
            else None
        ),
        "limitations": limitations,
    }


def _defense_video_descriptor(card: dict[str, Any]) -> dict[str, Any] | None:
    if not (card.get("video_available") or card.get("clip_available")):
        return None
    segments = []
    if card.get("clip_available") and card.get("timestamp_label"):
        segments.append(
            {
                "start_label": card.get("transcript_excerpt_start_label") or card.get("timestamp_label"),
                "end_label": card.get("transcript_excerpt_end_label"),
                "description": str(card.get("question_text") or "Cited defense moment")[:120],
            }
        )
    return {
        "proof_type": _DEFENSE,
        "recording_available": bool(card.get("video_available")),
        "availability": "retained" if card.get("video_available") else "not_retained",
        "transcript_available": bool(card.get("transcript_excerpt_available")),
        "cited_segments": segments,
        "access": {
            "kind": "defense_recording",
            "label": "Play defense recording",
            "available": bool(card.get("video_playback_url")),
            "action_label": "Play recording",
            # Owner-authorized playback URL produced by the defense access
            # service (bounded, never a raw storage path).
            "url": card.get("video_playback_url"),
            "requires_owner_permission": True,
            "note": str(card.get("recording_access_note") or "") or None,
        },
        "limitations": _listify(card.get("transcript_access_note")),
    }


def _video_proof_descriptor(vcard: dict[str, Any]) -> dict[str, Any]:
    return {
        "proof_type": _VIDEO,
        "recording_available": bool(vcard.get("replay_available")),
        "availability": "retained" if vcard.get("replay_available") else "not_retained",
        "duration_label": vcard.get("duration_label"),
        "transcript_available": bool(vcard.get("transcript_available")),
        "poster_available": bool(vcard.get("frames_available")),
        "cited_segments": [],
        "access": {
            "kind": "recorded_replay",
            "label": "Play demo video",
            "available": bool(vcard.get("replay_available")),
            "action_label": "Play video" if vcard.get("replay_available") else None,
            "requires_owner_permission": True,
            "note": "Playback resolves through the gated video-proof routes.",
        },
        "limitations": [str(x) for x in (vcard.get("limitations") or [])][:4],
    }


def _document_access(doc: dict[str, Any]) -> dict[str, Any]:
    retained = bool(doc.get("document_retained"))
    shareable = bool(doc.get("full_document_available"))
    return {
        "retained": retained,
        "excerpts_only": not retained,
        "open_available": retained,
        "download_available": retained and shareable,
        "publication_state": "published" if shareable else "private",
        "limitations": (
            []
            if retained
            else [
                "The original file was not retained for this historical document — only extracted "
                "excerpts exist. Future uploads retain the original for authorized open/download."
            ]
        ),
    }


__all__ = [
    "build_skill_claim_evidence_map",
    "build_project_claim_evidence_map",
    "classify_github_tier",
    "classify_website_identity",
]
