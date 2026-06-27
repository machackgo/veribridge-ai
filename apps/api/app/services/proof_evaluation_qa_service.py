"""Evaluation / QA Agent (Step 8) — an internal, deterministic proof evaluator.

Steps 2–7 *build* proof reports (normalized evidence, linked chains, synthesis
claims) and *project* them to recruiter-safe public payloads. This module does
neither: it is the internal **QA / evaluator** that audits those already-built
artifacts and tells us — before we trust or publish anything — whether they are
correct, internally consistent, and safe.

It answers two kinds of question, both **deterministically** (pure dict-walking
and the Step 7 regexes — no LLM, no local model, no network):

1. **Internal correctness** (``evaluate_internal_report``) — over the rich
   internal report shape (Steps 2–6 ``to_dict()`` output): are synthesis claims
   actually supported by evidence that exists? Do linked chains accidentally
   combine unrelated projects? Is document-only evidence being treated as
   implementation proof? Is a repo-level fallback being promoted above precise
   code? Are enum-like labels valid?

2. **Public safety** (``evaluate_public_output``) — over an already-projected
   public payload (Step 7 output): does anything still leak — secrets, signed
   URLs, storage/local paths, emails, raw payload markers, score/ranking/"fully
   verified" language, raw (non-opaque) ids, or ``public_safe=False`` items?

The evaluator is **fail-closed**: an unsupported claim, a cross-project chain, a
document overclaim, or *any* whiff of a private/secret string in a public
payload produces a ``blocker``. It reuses the Step 7 single-source-of-truth
helpers (``contains_unsafe_fields``, the secret/score regexes, the opaque-id
validators, the enum allowlists) so it can never drift from the sanitizer it is
auditing. Crucially, it **never echoes a leaked secret** back: every issue
message describes the *pattern* detected, never the offending value.

This is an internal/admin/testing layer. It is not a public-facing product
feature and is never exposed on a public route.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

# Reuse the Step 7 single source of truth for every safety primitive so the
# evaluator can never disagree with the sanitizer it is auditing: the fail-closed
# whole-payload gate, the secret/email/URI/score regexes, the unsafe key/value
# sets, the approved opaque-id validators, and the enum allowlists.
from app.services.public_report_safety_service import (
    _ALLOWED_PROOF_STRENGTHS,
    _ALLOWED_QUALITATIVE_TIERS,
    _ALLOWED_SOURCE_TYPES,
    _BEARER_RE,
    _DANGEROUS_URI_RE,
    _EMAIL_RE,
    _EXTRA_UNSAFE_KEYS,
    _EXTRA_UNSAFE_VALUE_SUBSTRINGS,
    _SECRET_KV_RE,
    _TOKEN_TRIM,
    _URL_RE,
    _is_public_safe_chain_id,
    _is_public_safe_claim_id,
    _is_public_safe_evidence_id,
    _looks_like_private_identifier,
    _normalize_key,
    _scrub_score_fragments,
    _scrub_score_rank_language,
    contains_unsafe_fields,
)
from app.services.evidence_normalization_service import (
    SOURCE_DOCUMENT,
    STRENGTH_PRECISE_CODE,
    STRENGTH_REPO_LEVEL,
    STRENGTH_RUNTIME,
)
from app.services.llm_proof_synthesis_service import TIER_STRONG

__all__ = [
    "EvaluationSeverity",
    "EvaluationVerdict",
    "EvaluationCategory",
    "EvaluationIssue",
    "EvaluationReport",
    "evaluate_internal_report",
    "evaluate_public_output",
    "evaluate_report",
]


# ── Enums / categories ────────────────────────────────────────────────────────


class EvaluationSeverity(str, Enum):
    """How serious an issue is. ``blocker`` fails the verdict; ``warning`` softens it."""

    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"


class EvaluationVerdict(str, Enum):
    """The overall QA outcome derived from the issue severities."""

    PASS = "pass"
    PASS_WITH_WARNINGS = "pass_with_warnings"
    FAIL = "fail"


class EvaluationCategory(str, Enum):
    """The closed set of issue categories this evaluator can emit."""

    UNSUPPORTED_CLAIM = "unsupported_claim"
    MISSING_CITATION = "missing_citation"
    INVALID_PUBLIC_ID = "invalid_public_id"
    UNSAFE_PUBLIC_LEAK = "unsafe_public_leak"
    UNSAFE_ENUM_VALUE = "unsafe_enum_value"
    UNRELATED_CHAIN_LINK = "unrelated_chain_link"
    DOCUMENT_OVERCLAIM = "document_overclaim"
    REPO_FALLBACK_OVERCLAIM = "repo_fallback_overclaim"
    PUBLIC_SAFE_FALSE_LEAK = "public_safe_false_leak"
    RAW_PAYLOAD_LEAK = "raw_payload_leak"
    SCORE_OR_RANKING_LANGUAGE = "score_or_ranking_language"
    STALE_MARKER_LEAK = "stale_marker_leak"
    UNKNOWN = "unknown"


# Strengths that assert *implementation* proof. Document evidence
# (``corroboration`` only) must never carry one of these.
_STRONG_IMPLEMENTATION_STRENGTHS = frozenset({STRENGTH_PRECISE_CODE, STRENGTH_RUNTIME})

# Marker substrings that signal a raw/internal payload leaked into prose (keys are
# handled separately via ``_EXTRA_UNSAFE_KEYS``). Lower-cased value match.
_RAW_PAYLOAD_VALUE_MARKERS = (
    "raw_payload",
    "rawpayload",
    "provider_response",
    "providerresponse",
    "provider_payload",
    "raw_metadata",
    "raw_response",
    "raw_transcript",
    "dom_snapshot",
    "ocr_text",
)

# Keys that identify a stale / reanalysis marker shape (Step 6). Used to tag a
# leaked marker with the more specific ``stale_marker_leak`` category. Compared
# against the underscore-stripped form of each key.
_STALE_MARKER_KEYS = {"recommendedaction", "stalereason"}

# Numeric-confidence wording the Step 7 score scrubbers do not catch (they handle
# scores / ranks / percentiles / "fully verified", but not a bare
# ``confidence: 0.95``). Additive detection only — never relaxes the sanitizer.
_NUMERIC_CONFIDENCE_RE = re.compile(r"(?i)\bconfidence\b\s*[:=]?\s*\d*\.?\d+%?")


# ── Issue / report models ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class EvaluationIssue:
    """One finding. ``public_safe`` asserts the message itself leaks nothing.

    ``message`` describes the *pattern* detected, never the offending value, so an
    issue is itself safe to surface — even when it reports a leaked secret. Any
    ``evidence_ids`` attached are only ever approved opaque ``ev_…`` ids (a raw /
    private id is described in prose, never echoed here).
    """

    issue_id: str
    severity: EvaluationSeverity
    category: EvaluationCategory
    message: str
    location: str
    evidence_ids: tuple[str, ...] = ()
    recommended_fix: str = ""
    public_safe: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "severity": self.severity.value,
            "category": self.category.value,
            "message": self.message,
            "location": self.location,
            "evidence_ids": list(self.evidence_ids),
            "recommended_fix": self.recommended_fix,
            "public_safe": self.public_safe,
        }


@dataclass(frozen=True)
class EvaluationReport:
    """The structured QA verdict for an evaluated artifact."""

    verdict: EvaluationVerdict
    issues: tuple[EvaluationIssue, ...]
    blocker_count: int
    warning_count: int
    info_count: int
    evaluated_sections: tuple[str, ...]
    public_safe: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "issues": [issue.to_dict() for issue in self.issues],
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "evaluated_sections": list(self.evaluated_sections),
            "public_safe": self.public_safe,
        }


# ── Issue construction ────────────────────────────────────────────────────────


def _issue(
    severity: EvaluationSeverity,
    category: EvaluationCategory,
    message: str,
    location: str,
    *,
    evidence_ids: Iterable[str] = (),
    recommended_fix: str = "",
) -> EvaluationIssue:
    """Build an issue with a deterministic, content-derived id.

    Only approved opaque ``ev_…`` ids are retained in ``evidence_ids`` — a raw /
    private id passed in is dropped so the issue itself never leaks one.
    """
    safe_ids = tuple(eid for eid in evidence_ids if _is_public_safe_evidence_id(eid))
    digest = hashlib.sha1(
        "␟".join((category.value, location, message)).encode("utf-8")
    ).hexdigest()[:12]
    return EvaluationIssue(
        issue_id=f"qa_{digest}",
        severity=severity,
        category=category,
        message=message,
        location=location,
        evidence_ids=safe_ids,
        recommended_fix=recommended_fix,
        public_safe=True,
    )


def _build_report(
    issues: list[EvaluationIssue], sections: Iterable[str]
) -> EvaluationReport:
    """Tally severities into a verdict (fail-closed on any blocker)."""
    blocker = sum(1 for i in issues if i.severity is EvaluationSeverity.BLOCKER)
    warning = sum(1 for i in issues if i.severity is EvaluationSeverity.WARNING)
    info = sum(1 for i in issues if i.severity is EvaluationSeverity.INFO)
    if blocker:
        verdict = EvaluationVerdict.FAIL
    elif warning:
        verdict = EvaluationVerdict.PASS_WITH_WARNINGS
    else:
        verdict = EvaluationVerdict.PASS
    return EvaluationReport(
        verdict=verdict,
        issues=tuple(issues),
        blocker_count=blocker,
        warning_count=warning,
        info_count=info,
        evaluated_sections=tuple(sections),
        # Conservative / fail-closed: anything that produced a blocker is treated
        # as not-safe-to-rely-on / not-safe-to-publish.
        public_safe=blocker == 0,
    )


# ── Small accessors (backward-compatible, tolerant of older shapes) ───────────


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce an internal object with ``to_dict()`` (or a plain dict) to a dict."""
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        if isinstance(result, dict):
            return result
    return {}


def _as_list(value: Any) -> list[Any]:
    """Coerce to a list; missing / wrong-typed sections become an empty list."""
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _evidence_dicts(chain: dict[str, Any]) -> list[dict[str, Any]]:
    """Member artifact dicts of a chain (each coerced via ``_as_dict``)."""
    return [_as_dict(e) for e in _as_list(chain.get("evidence"))]


# ── Internal checks (Steps 2–6 correctness) ───────────────────────────────────


@dataclass(frozen=True)
class _ChainScope:
    """One chain's *local* evidence universe (ids + id→artifact index).

    Citation validity is **chain-local**: a synthesis claim attached to chain A
    may cite only the evidence ids that belong to chain A. Building the allowed
    set from each chain's own evidence (never report-wide) is what stops a claim
    in chain A from "borrowing" evidence that lives only in chain B.
    """

    ids: frozenset[str]
    index: dict[str, dict[str, Any]]


def _chain_scope(chain: dict[str, Any]) -> _ChainScope:
    """Build a chain's local evidence id set + id→artifact index from its own
    ``linked_evidence_ids`` and member artifacts only."""
    ids: set[str] = set()
    index: dict[str, dict[str, Any]] = {}
    for eid in _as_list(chain.get("linked_evidence_ids")):
        if isinstance(eid, str):
            ids.add(eid)
    for art in _evidence_dicts(chain):
        eid = art.get("evidence_id")
        if isinstance(eid, str):
            ids.add(eid)
            index.setdefault(eid, art)
    return _ChainScope(ids=frozenset(ids), index=index)


def _chain_scopes(report: dict[str, Any]) -> tuple[dict[str, _ChainScope], _ChainScope | None]:
    """Per-chain evidence scopes keyed by ``chain_id``, plus the lone scope (if any).

    Returns ``(scopes_by_chain_id, single_scope)``. ``single_scope`` is populated
    only when the report contains exactly one chain — it is the *nearest* scope
    used to evaluate a top-level synthesis result that carries no ``chain_id``.
    With zero or many chains and no ``chain_id`` to disambiguate, scope is
    undetermined and citation checks **fail closed** rather than fall back to a
    report-wide set.
    """
    scopes: dict[str, _ChainScope] = {}
    all_scopes: list[_ChainScope] = []
    for key in ("linked_proof_chains", "proof_chains"):
        for chain in _as_list(report.get(key)):
            chain = _as_dict(chain)
            scope = _chain_scope(chain)
            all_scopes.append(scope)
            cid = chain.get("chain_id")
            if isinstance(cid, str):
                existing = scopes.get(cid)
                if existing is None:
                    scopes[cid] = scope
                else:
                    merged_index = dict(existing.index)
                    for k, v in scope.index.items():
                        merged_index.setdefault(k, v)
                    scopes[cid] = _ChainScope(
                        ids=existing.ids | scope.ids, index=merged_index
                    )
    single = all_scopes[0] if len(all_scopes) == 1 else None
    return scopes, single


def _check_public_id(
    value: Any,
    validator: Any,
    location: str,
    field_label: str,
    issues: list[EvaluationIssue],
) -> None:
    """Validate one report id against an approved opaque format, *independent of
    existence*. An invalid-format id is a blocker even if the same malformed id
    appears consistently elsewhere in the report. The raw id is never echoed.
    """
    if value is None:
        return
    if not validator(value):
        issues.append(
            _issue(
                EvaluationSeverity.BLOCKER,
                EvaluationCategory.INVALID_PUBLIC_ID,
                f"Report {field_label} is not an approved opaque id "
                f"(invalid format, independent of whether it appears elsewhere).",
                location,
                recommended_fix="Use only approved opaque ev_/chain_/claim_ ids.",
            )
        )


def _check_citation_ids(
    value: Any,
    location: str,
    field_label: str,
    issues: list[EvaluationIssue],
) -> None:
    """Validate an evidence-citation list: every item must be an approved opaque
    ``ev_…`` id *string*.

    Two distinct failure modes are both blockers (and both INVALID_PUBLIC_ID):

    * a **non-string** value (``123``, ``None``, a dict, a list, ``False`` …) — it
      is never a valid id and must not be silently ignored; and
    * a **string of the wrong format** (a raw UUID, a path/email, an arbitrary
      token).

    Only counts/types are reported — the raw value or object is never echoed, so
    the issue stays public-safe even when an item is a secret-bearing object.
    """
    items = _as_list(value)
    non_string = sum(1 for item in items if not isinstance(item, str))
    bad_format = sum(
        1 for item in items if isinstance(item, str) and not _is_public_safe_evidence_id(item)
    )
    if non_string or bad_format:
        issues.append(
            _issue(
                EvaluationSeverity.BLOCKER,
                EvaluationCategory.INVALID_PUBLIC_ID,
                f"{field_label} contains {non_string + bad_format} entry/entries that "
                "are not approved opaque ev_ ids "
                f"({non_string} non-string value(s), {bad_format} invalid-format id(s)).",
                location,
                recommended_fix="Keep only approved opaque ev_ id strings in citation lists.",
            )
        )


def _check_evidence_artifact(
    art: dict[str, Any], location: str, issues: list[EvaluationIssue]
) -> None:
    """Per-artifact internal checks: id format + document overclaim + enum labels."""
    source_type = art.get("source_type")
    strength = art.get("proof_strength")

    # Evidence id must be an approved opaque ``ev_…`` id, independent of whether
    # the same (malformed) id is reused as a citation elsewhere.
    _check_public_id(
        art.get("evidence_id"),
        _is_public_safe_evidence_id,
        f"{location}.evidence_id",
        "evidence_id",
        issues,
    )

    # Document-only evidence dressed up as implementation proof.
    if source_type == SOURCE_DOCUMENT and strength in _STRONG_IMPLEMENTATION_STRENGTHS:
        issues.append(
            _issue(
                EvaluationSeverity.BLOCKER,
                EvaluationCategory.DOCUMENT_OVERCLAIM,
                "Document-only evidence is classified with an implementation-strength "
                "proof label; document evidence may only corroborate.",
                location,
                evidence_ids=[art.get("evidence_id")]
                if isinstance(art.get("evidence_id"), str)
                else [],
                recommended_fix="Set document evidence proof_strength to a corroboration label.",
            )
        )

    if isinstance(source_type, str) and source_type not in _ALLOWED_SOURCE_TYPES:
        issues.append(
            _issue(
                EvaluationSeverity.WARNING,
                EvaluationCategory.UNSAFE_ENUM_VALUE,
                "Evidence source_type is not a known source label.",
                f"{location}.source_type",
                recommended_fix="Emit a known source_type or omit the field.",
            )
        )
    if isinstance(strength, str) and strength not in _ALLOWED_PROOF_STRENGTHS:
        issues.append(
            _issue(
                EvaluationSeverity.WARNING,
                EvaluationCategory.UNSAFE_ENUM_VALUE,
                "Evidence proof_strength is not a known strength label.",
                f"{location}.proof_strength",
                recommended_fix="Emit a known proof_strength or omit the field.",
            )
        )


def _check_chain(chain: dict[str, Any], location: str, issues: list[EvaluationIssue]) -> None:
    """Per-chain internal checks: id formats + cross-project linking + repo overclaim."""
    artifacts = _evidence_dicts(chain)

    # Chain id and every linked-evidence citation id must be approved opaque ids,
    # validated by format independent of existence.
    _check_public_id(
        chain.get("chain_id"),
        _is_public_safe_chain_id,
        f"{location}.chain_id",
        "chain_id",
        issues,
    )
    # Every linked-evidence citation must be an approved opaque ev_ id *string* —
    # a non-string value (123 / null / dict / list / bool) is just as invalid as a
    # malformed string and must not be silently ignored.
    _check_citation_ids(
        chain.get("linked_evidence_ids"),
        f"{location}.linked_evidence_ids",
        "Chain linked_evidence_ids",
        issues,
    )

    # Unrelated-link protection (Step 3): a chain must describe ONE project. If its
    # member artifacts disagree on a *visible* project_id / project_title, the link
    # combined unrelated work.
    for field_name in ("project_id", "project_title"):
        distinct = {
            str(art.get(field_name)).strip()
            for art in artifacts
            if art.get(field_name) not in (None, "")
        }
        if len(distinct) > 1:
            issues.append(
                _issue(
                    EvaluationSeverity.BLOCKER,
                    EvaluationCategory.UNRELATED_CHAIN_LINK,
                    f"Linked chain combines evidence from multiple distinct "
                    f"{field_name} values (unrelated work linked together).",
                    location,
                    recommended_fix="Only link evidence that shares one project identity.",
                )
            )

    # Repo identity conflict (visible only in internal artifact metadata).
    repos = set()
    for art in artifacts:
        meta = art.get("metadata")
        if isinstance(meta, dict) and meta.get("repo_url"):
            repos.add(str(meta["repo_url"]).strip())
    if len(repos) > 1:
        issues.append(
            _issue(
                EvaluationSeverity.BLOCKER,
                EvaluationCategory.UNRELATED_CHAIN_LINK,
                "Linked chain combines evidence from multiple distinct repositories.",
                location,
                recommended_fix="Only link evidence that shares one repository identity.",
            )
        )

    # Repo-level fallback promoted without precise code (Step 2 protection).
    strengths = {
        art.get("proof_strength") for art in artifacts if art.get("proof_strength")
    }
    summary = chain.get("proof_strength_summary")
    repo_level_only = bool(summary.get("repo_level_only")) if isinstance(summary, dict) else False
    has_repo_level = STRENGTH_REPO_LEVEL in strengths or repo_level_only
    has_precise = STRENGTH_PRECISE_CODE in strengths or (
        isinstance(summary, dict) and summary.get("has_precise_code")
    )
    if has_repo_level and not has_precise:
        issues.append(
            _issue(
                EvaluationSeverity.WARNING,
                EvaluationCategory.REPO_FALLBACK_OVERCLAIM,
                "Chain relies on repo-level fallback evidence without precise "
                "code-level evidence.",
                location,
                recommended_fix="Locate precise code evidence or label the chain as repo-level.",
            )
        )

    for idx, art in enumerate(artifacts):
        _check_evidence_artifact(art, f"{location}.evidence[{idx}]", issues)

    # Legacy / internal ``proof_chains`` may embed claims directly on the chain
    # (rather than in ``llm_synthesis``). Validate the public-facing id *formats*
    # defensively so an invalid claim_id or citation inside an older chain shape
    # fails closed instead of slipping through as PASS. Missing fields are simply
    # skipped (``_check_public_id`` no-ops on ``None``).
    for cidx, claim in enumerate(_as_list(chain.get("claims"))):
        claim = _as_dict(claim)
        claim_loc = f"{location}.claims[{cidx}]"
        _check_public_id(
            claim.get("claim_id"),
            _is_public_safe_claim_id,
            f"{claim_loc}.claim_id",
            "claim_id",
            issues,
        )
        if "supporting_evidence_ids" in claim:
            _check_citation_ids(
                claim.get("supporting_evidence_ids"),
                f"{claim_loc}.supporting_evidence_ids",
                "Chain claim supporting_evidence_ids",
                issues,
            )


def _resolve_synthesis_scope(
    result: dict[str, Any],
    chain_scopes: dict[str, _ChainScope],
    single_scope: _ChainScope | None,
) -> tuple[_ChainScope | None, bool]:
    """Pick the chain-local evidence scope for a synthesis result (fail-closed).

    A result attached to a chain (``chain_id`` matches a chain) is evaluated
    against *that chain's* evidence only. A result with no ``chain_id`` falls back
    to the single chain when the report has exactly one (the nearest scope). Any
    other case — a ``chain_id`` that names no chain, or no ``chain_id`` with
    multiple chains — leaves scope undetermined, so citation checks fail closed.
    """
    cid = result.get("chain_id")
    if isinstance(cid, str):
        scope = chain_scopes.get(cid)
        return (scope, True) if scope is not None else (None, False)
    if single_scope is not None:
        return single_scope, True
    return None, False


def _check_synthesis_result(
    result: dict[str, Any],
    location: str,
    chain_scopes: dict[str, _ChainScope],
    single_scope: _ChainScope | None,
    issues: list[EvaluationIssue],
) -> None:
    """Per-synthesis-result checks: id formats, unsupported / out-of-scope citations,
    and document overclaim — all validated **chain-locally**."""
    if isinstance(result.get("qualitative_tier"), str) and result["qualitative_tier"] not in _ALLOWED_QUALITATIVE_TIERS:
        issues.append(
            _issue(
                EvaluationSeverity.WARNING,
                EvaluationCategory.UNSAFE_ENUM_VALUE,
                "Synthesis qualitative_tier is not a known tier label.",
                f"{location}.qualitative_tier",
            )
        )

    scope, scope_known = _resolve_synthesis_scope(result, chain_scopes, single_scope)
    allowed_ids = scope.ids if scope is not None else frozenset()
    evidence_index = scope.index if scope is not None else {}

    for idx, claim in enumerate(_as_list(result.get("claims"))):
        claim = _as_dict(claim)
        claim_loc = f"{location}.claims[{idx}]"

        # Claim id must be an approved opaque id, independent of existence.
        _check_public_id(
            claim.get("claim_id"),
            _is_public_safe_claim_id,
            f"{claim_loc}.claim_id",
            "claim_id",
            issues,
        )

        raw_cited = _as_list(claim.get("supporting_evidence_ids"))
        str_cited = [c for c in raw_cited if isinstance(c, str)]

        # 1) No citations at all → unsupported.
        if not raw_cited:
            issues.append(
                _issue(
                    EvaluationSeverity.BLOCKER,
                    EvaluationCategory.UNSUPPORTED_CLAIM,
                    "Synthesis claim has no supporting evidence citations.",
                    claim_loc,
                    recommended_fix="Cite at least one existing evidence id or drop the claim.",
                )
            )
            continue

        # 2) Every citation must be an approved opaque ev_ id *string* — a
        #    non-string value (123 / null / dict / list / bool) is invalid and is
        #    never silently ignored, and a malformed string is a blocker even if
        #    reused consistently across the report. Only counts/types are
        #    reported, never the raw value/object.
        _check_citation_ids(
            raw_cited,
            f"{claim_loc}.supporting_evidence_ids",
            "Synthesis claim supporting_evidence_ids",
            issues,
        )
        well_formed = [c for c in str_cited if _is_public_safe_evidence_id(c)]

        # 3) Chain-local citation existence. Each cited id must belong to THIS
        #    claim's own chain — never another chain, never the report at large.
        #    If scope could not be determined, fail closed: citations cannot be
        #    validated against an in-scope evidence set.
        if not scope_known:
            issues.append(
                _issue(
                    EvaluationSeverity.BLOCKER,
                    EvaluationCategory.MISSING_CITATION,
                    "Synthesis claim citations cannot be validated against an "
                    "in-scope (chain-local) evidence set; scope is undetermined.",
                    claim_loc,
                    recommended_fix="Attach the synthesis result to its chain so "
                    "citations resolve chain-locally.",
                )
            )
        else:
            out_of_scope = [c for c in well_formed if c not in allowed_ids]
            if out_of_scope:
                issues.append(
                    _issue(
                        EvaluationSeverity.BLOCKER,
                        EvaluationCategory.MISSING_CITATION,
                        f"Synthesis claim cites {len(out_of_scope)} evidence id(s) "
                        "not present in this claim's own chain "
                        "(missing / out-of-scope citation).",
                        claim_loc,
                        recommended_fix="Cite only evidence ids that belong to this chain.",
                    )
                )

        # 4) Claim asserts strong corroboration but every (in-scope) cited piece
        #    is a document → document overclaim. Resolution is chain-local.
        resolved = [evidence_index.get(c) for c in well_formed]
        resolved = [r for r in resolved if isinstance(r, dict)]
        if (
            claim.get("qualitative_tier") == TIER_STRONG
            and resolved
            and all(r.get("source_type") == SOURCE_DOCUMENT for r in resolved)
        ):
            issues.append(
                _issue(
                    EvaluationSeverity.BLOCKER,
                    EvaluationCategory.DOCUMENT_OVERCLAIM,
                    "Synthesis claim asserts strong corroboration from "
                    "document-only evidence.",
                    claim_loc,
                    evidence_ids=well_formed,
                    recommended_fix="Strong claims need non-document implementation evidence.",
                )
            )


def evaluate_internal_report(report: Any) -> EvaluationReport:
    """Audit a rich internal report (Steps 2–6 shapes) for correctness.

    Tolerant of older / partial reports: missing ``linked_proof_chains`` /
    ``llm_synthesis`` / ``proof_strength_summary`` / ``source_coverage`` sections
    simply contribute no issues rather than raising. Deterministic — no network,
    no LLM.
    """
    report = _as_dict(report)
    issues: list[EvaluationIssue] = []
    sections: list[str] = []

    # Chain-local evidence scopes: a claim may cite only its own chain's evidence.
    chain_scopes, single_scope = _chain_scopes(report)

    # Audit BOTH the current ``linked_proof_chains`` and the legacy / internal
    # ``proof_chains`` shape: invalid public-facing ids inside an older
    # ``proof_chains`` block must fail closed instead of producing PASS.
    for section_key in ("linked_proof_chains", "proof_chains"):
        chains = _as_list(report.get(section_key))
        if chains:
            sections.append(section_key)
        for idx, chain in enumerate(chains):
            _check_chain(_as_dict(chain), f"{section_key}[{idx}]", issues)

    synthesis = _as_list(report.get("llm_synthesis"))
    if synthesis:
        sections.append("llm_synthesis")
    for idx, result in enumerate(synthesis):
        _check_synthesis_result(
            _as_dict(result),
            f"llm_synthesis[{idx}]",
            chain_scopes,
            single_scope,
            issues,
        )

    return _build_report(issues, sections)


# ── Public-output checks (Step 7 leak scanning) ───────────────────────────────


def _has_score_language(text: str) -> bool:
    """``True`` when score / rank / rating / percentile / over-claim wording is present.

    Detected by re-running the Step 7 score scrubbers and seeing whether they
    changed the string — so the evaluator uses the exact same definition of
    "score-style fragment" as the sanitizer it audits.
    """
    if _scrub_score_rank_language(_scrub_score_fragments(text)) != text:
        return True
    return bool(_NUMERIC_CONFIDENCE_RE.search(text))


def _classify_string_leak(text: str) -> tuple[EvaluationCategory, str] | None:
    """Classify the *first* leak pattern in a public string (never echoing it).

    Returns ``(category, generic_message)`` or ``None`` when the string is clean.
    The message names the pattern, never the offending substring, so the issue is
    itself safe to surface.
    """
    if _SECRET_KV_RE.search(text) or _BEARER_RE.search(text):
        return (
            EvaluationCategory.UNSAFE_PUBLIC_LEAK,
            "Potential credential / secret-bearing token detected in public text.",
        )
    for match in _URL_RE.finditer(text):
        _, sep, query = match.group(0).partition("?")
        if sep and _SECRET_KV_RE.search(query):
            return (
                EvaluationCategory.UNSAFE_PUBLIC_LEAK,
                "Potential secret-bearing URL query parameter detected in public text.",
            )
    lowered = text.lower()
    if any(marker in lowered for marker in _RAW_PAYLOAD_VALUE_MARKERS):
        return (
            EvaluationCategory.RAW_PAYLOAD_LEAK,
            "Potential raw/internal payload marker detected in public text.",
        )
    if _DANGEROUS_URI_RE.search(text):
        return (
            EvaluationCategory.UNSAFE_PUBLIC_LEAK,
            "Potential dangerous URI scheme detected in public text.",
        )
    if _EMAIL_RE.search(text):
        return (
            EvaluationCategory.UNSAFE_PUBLIC_LEAK,
            "Potential email address detected in public text.",
        )
    for fragment in _EXTRA_UNSAFE_VALUE_SUBSTRINGS:
        if fragment in lowered:
            return (
                EvaluationCategory.UNSAFE_PUBLIC_LEAK,
                "Potential private path / storage / token fragment detected in public text.",
            )
    if _has_score_language(text):
        return (
            EvaluationCategory.SCORE_OR_RANKING_LANGUAGE,
            "Score / ranking / percentage / numeric-confidence / over-claim "
            "language detected in public text.",
        )
    return None


# ID-bearing keys held to the approved opaque format in a public payload.
_PUBLIC_ID_FIELDS = {
    "evidenceid": _is_public_safe_evidence_id,
    "chainid": _is_public_safe_chain_id,
    "claimid": _is_public_safe_claim_id,
}
_PUBLIC_ID_LIST_FIELDS = {
    "supportingevidenceids": _is_public_safe_evidence_id,
    "linkedevidenceids": _is_public_safe_evidence_id,
}


# Step-8-only stricter key detector. Step 7's ``_PREFIXED_ID_RE`` only catches a
# *hex* suffix (``prefix_<hex>``), so a long *alphanumeric* private id such as
# ``user_1234567890ghijkl`` or ``project_ABCXYZ1234567890`` slips past
# ``_looks_like_private_identifier``. For dictionary *keys* (an injection surface)
# we add a stricter, key-only rule on top of the Step 7 detector: a known private
# prefix followed by a long alphanumeric suffix. Prefixes are matched
# case-insensitively; the suffix must be >= 12 alphanumeric chars (an underscore
# breaks the run, so ``source_coverage`` / ``source_types_present`` are safe).
_PRIVATE_ID_KEY_RE = re.compile(
    r"(?i)^(?:user|project|artifact|student|source|provider|report)_[A-Za-z0-9]{12,}$"
)


def _looks_like_private_identifier_key(key: str) -> bool:
    """Step-8-only stricter private-id detector for dictionary *keys*.

    Returns ``True`` for anything the Step 7 single-source-of-truth detector
    flags (UUID / bare long hex / ``prefix_<hex>``) **or** for a known private
    prefix (``user_`` / ``project_`` / ``artifact_`` / ``student_`` / ``source_``
    / ``provider_`` / ``report_``, case-insensitive) followed by a long
    alphanumeric suffix (``[A-Za-z0-9]{12,}``).

    This is intentionally stricter than normal public-id validation, but it is
    **key-only and additive**: it never changes Step 7's shared identifier rules
    and is never applied to value fields, so valid public opaque ids are
    unaffected.
    """
    candidate = key.strip(_TOKEN_TRIM)
    if not candidate:
        return False
    return bool(
        _looks_like_private_identifier(candidate)
        or _PRIVATE_ID_KEY_RE.match(candidate)
    )


def _classify_key_leak(key: str) -> tuple[EvaluationCategory, str] | None:
    """Classify a leak carried by a dictionary *key* (never echoing the key).

    Keys are an injection surface too: ``{"api_key=sk-…": "safe"}`` hides the
    secret in the key, not the value, and ``{"550e8400-…": "safe"}`` /
    ``{"user_1234567890abcdef": "safe"}`` hide a raw UUID / private id there. We
    run the same Step 7 leak detectors *and* the Step 7 private-identifier matcher
    over the key text and return a generic, key-shaped message that names only the
    *pattern* — never the offending key — so the issue is itself safe to surface.
    """
    # A UUID / bare-hex blob / ``prefix_<hex>`` private id used as a key is unsafe
    # even though it carries no secret/email/path token — it leaks an internal
    # record id. Reuse the Step 7 single-source-of-truth detector so we can never
    # disagree with the sanitizer. Checked first because such keys are invisible
    # to the value-oriented ``_classify_string_leak`` detectors below.
    if _looks_like_private_identifier_key(key):
        return (
            EvaluationCategory.UNSAFE_PUBLIC_LEAK,
            "Unsafe public dictionary key detected: private-identifier-shaped key "
            "(UUID / hex blob / prefix_<hex> / prefix_<long-alphanumeric>)",
        )
    if _classify_string_leak(key) is None:
        return None
    if _SECRET_KV_RE.search(key) or _BEARER_RE.search(key):
        label = "secret-bearing key"
    elif _EMAIL_RE.search(key):
        label = "email-like key"
    elif _DANGEROUS_URI_RE.search(key) or any(
        fragment in key.lower() for fragment in _EXTRA_UNSAFE_VALUE_SUBSTRINGS
    ):
        label = "local path-like key"
    else:
        label = "unsafe key"
    return (
        EvaluationCategory.UNSAFE_PUBLIC_LEAK,
        f"Unsafe public dictionary key detected: {label}",
    )


def _safe_key_segment(key: str) -> str:
    """Return a location-/message-safe representation of a dictionary key.

    A dictionary key is an injection surface: a secret/email/path can hide *in the
    key itself* (``{"api_key=sk-…": {...}}``). When such a key is appended to an
    issue ``location`` path (or named in a message), it would echo the very secret
    we are meant to redact. So ordinary, safe keys (``claims``, ``evidence``,
    ``linked_proof_chains`` …) are echoed verbatim to keep locations debuggable,
    but any key that itself carries a leak is replaced with a neutral placeholder:

    * ``<secret_key>`` — a secret/token/credential key,
    * ``<email_key>`` — an email-like key,
    * ``<path_key>`` — a path / storage / dangerous-URI key,
    * ``<private_key>`` — a known private/internal field name,
    * ``<private_id_key>`` — a UUID / hex blob / ``prefix_<hex>`` /
      ``prefix_<long-alphanumeric>`` private id, or
    * ``<unsafe_key>`` — any other key the leak detectors flag.

    The offending key text therefore never reaches an issue's ``location``,
    ``message``, ``recommended_fix`` or any other field.
    """
    normalized = _normalize_key(key)
    compact = normalized.replace("_", "")
    if _SECRET_KV_RE.search(key) or _BEARER_RE.search(key):
        return "<secret_key>"
    if _EMAIL_RE.search(key):
        return "<email_key>"
    if _DANGEROUS_URI_RE.search(key) or any(
        fragment in key.lower() for fragment in _EXTRA_UNSAFE_VALUE_SUBSTRINGS
    ):
        return "<path_key>"
    if normalized in _EXTRA_UNSAFE_KEYS or compact in _EXTRA_UNSAFE_KEYS:
        return "<private_key>"
    # A raw UUID / hex blob / ``prefix_<hex>`` / ``prefix_<long-alphanumeric>``
    # private id used as a key is itself a leak: appended to a descendant
    # ``location`` it would echo the internal record id we must redact. Replace it
    # with a neutral placeholder.
    if _looks_like_private_identifier_key(key):
        return "<private_id_key>"
    if _classify_string_leak(key) is not None:
        return "<unsafe_key>"
    return key


def _looks_like_stale_marker(value: dict[str, Any]) -> bool:
    return any(
        _normalize_key(str(k)).replace("_", "") in _STALE_MARKER_KEYS for k in value
    )


def _scan_public(value: Any, location: str, issues: list[EvaluationIssue]) -> None:
    """Recursively scan a public payload for every leak category (fail-closed)."""
    if isinstance(value, dict):
        # public_safe=False item must never appear in a public payload.
        if value.get("public_safe") is False:
            category = (
                EvaluationCategory.STALE_MARKER_LEAK
                if _looks_like_stale_marker(value)
                else EvaluationCategory.PUBLIC_SAFE_FALSE_LEAK
            )
            issues.append(
                _issue(
                    EvaluationSeverity.BLOCKER,
                    category,
                    "An item flagged public_safe=False appears in public output.",
                    location,
                    recommended_fix="Drop non-public-safe items before public projection.",
                )
            )

        for key, nested in value.items():
            key_text = str(key)
            normalized = _normalize_key(key_text)
            compact = normalized.replace("_", "")
            # Location-/message-safe form of this key: a raw unsafe key (secret,
            # email, path, private id) is replaced with a neutral placeholder so it
            # is never echoed in any issue field — including the descendant
            # ``location`` path we recurse with below.
            safe_seg = _safe_key_segment(key_text)
            # Keys carry leaks too: an email/secret/path/token hidden in the key
            # itself must fail closed, with a generic (non-echoing) message.
            key_leak = _classify_key_leak(key_text)
            if key_leak is not None:
                category, message = key_leak
                issues.append(
                    _issue(
                        EvaluationSeverity.BLOCKER,
                        category,
                        message,
                        location,
                        recommended_fix="Whitelist public keys; never emit secret/"
                        "email/path-bearing keys.",
                    )
                )
            # Private / raw-payload keys must never appear publicly.
            if normalized in _EXTRA_UNSAFE_KEYS or compact in _EXTRA_UNSAFE_KEYS:
                issues.append(
                    _issue(
                        EvaluationSeverity.BLOCKER,
                        EvaluationCategory.RAW_PAYLOAD_LEAK,
                        f"Private/internal key '{safe_seg}' appears in public output.",
                        location,
                        recommended_fix="Whitelist public fields; drop private keys.",
                    )
                )
            # Opaque-id validation for id-bearing fields.
            if compact in _PUBLIC_ID_FIELDS and nested is not None:
                if not _PUBLIC_ID_FIELDS[compact](nested):
                    issues.append(
                        _issue(
                            EvaluationSeverity.BLOCKER,
                            EvaluationCategory.INVALID_PUBLIC_ID,
                            f"Public field '{safe_seg}' is not an approved opaque id.",
                            location,
                            recommended_fix="Echo only approved opaque ids publicly.",
                        )
                    )
            if compact in _PUBLIC_ID_LIST_FIELDS and isinstance(nested, (list, tuple)):
                validator = _PUBLIC_ID_LIST_FIELDS[compact]
                if any(not validator(item) for item in nested):
                    issues.append(
                        _issue(
                            EvaluationSeverity.BLOCKER,
                            EvaluationCategory.INVALID_PUBLIC_ID,
                            f"Public field '{safe_seg}' contains a non-opaque id.",
                            location,
                            recommended_fix="Keep only approved opaque ids in citation lists.",
                        )
                    )
            _scan_public(nested, f"{location}.{safe_seg}", issues)
        return

    if isinstance(value, list):
        for idx, item in enumerate(value):
            _scan_public(item, f"{location}[{idx}]", issues)
        return

    if isinstance(value, str):
        leak = _classify_string_leak(value)
        if leak is not None:
            # Every public-output leak — including score/ranking wording, which is a
            # hard recruiter-UI contract violation — is a blocker.
            category, message = leak
            issues.append(_issue(EvaluationSeverity.BLOCKER, category, message, location))


def evaluate_public_output(payload: Any) -> EvaluationReport:
    """Audit an already-projected public payload (Step 7 output) for leaks.

    Walks every string / key for secrets, signed URLs, storage/local paths,
    emails, raw payload markers, dangerous URIs, score/ranking language, raw
    (non-opaque) ids, and ``public_safe=False`` items. As a fail-closed
    catch-all, the Step 7 whole-payload gate (:func:`contains_unsafe_fields`) is
    also consulted: if it trips but the targeted scan found nothing, a generic
    blocker is still raised so an unrecognised leak shape is never passed.
    Issue messages never echo the offending value. Deterministic — no network.
    """
    issues: list[EvaluationIssue] = []
    _scan_public(payload, "public", issues)

    if not issues and contains_unsafe_fields(payload):
        issues.append(
            _issue(
                EvaluationSeverity.BLOCKER,
                EvaluationCategory.UNSAFE_PUBLIC_LEAK,
                "Public payload tripped the fail-closed unsafe-field scan with an "
                "unrecognised pattern.",
                "public",
                recommended_fix="Re-project through the public safety layer.",
            )
        )
    return _build_report(issues, ("public_output",))


# ── Combined entry point ──────────────────────────────────────────────────────


def evaluate_report(report: Any, *, public_payload: Any = None) -> EvaluationReport:
    """Evaluate an internal report and (optionally) its public projection together.

    Runs :func:`evaluate_internal_report` over ``report`` and, when
    ``public_payload`` is supplied, :func:`evaluate_public_output` over it, then
    merges the findings into one verdict (fail-closed on any blocker). Use this
    when you have both the rich internal object and the public payload it produced
    and want a single QA report covering correctness *and* safety.
    """
    internal = evaluate_internal_report(report)
    issues = list(internal.issues)
    sections = list(internal.evaluated_sections)
    if public_payload is not None:
        public = evaluate_public_output(public_payload)
        issues.extend(public.issues)
        sections.extend(public.evaluated_sections)
    return _build_report(issues, sections)
