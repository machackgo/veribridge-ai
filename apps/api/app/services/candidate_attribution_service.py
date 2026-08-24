"""Candidate ↔ project attribution — the ONE place ownership semantics live.

VeriBridge's core trust rule: PROJECT EVIDENCE != CANDIDATE OWNERSHIP.
Technology detected in a repository, behaviour recorded at runtime, or a
document describing a design prove facts about the PROJECT. A claim about the
CANDIDATE ("implemented", "built", "contributed") additionally requires
candidate↔artifact relationship evidence. This module:

1. Detects the ownership STANCE of one candidate statement (a Project Defense
   answer): ``affirmed`` / ``denied`` / ``mixed`` / ``none``. Detection is
   deterministic and conservative — only explicit statements match.
2. Assesses the project-level OWNERSHIP STATE (see
   ``canonical_evidence.OWNERSHIP_STATES``) from the candidate's own defense
   statements plus any stored candidate-specific attribution evidence
   (``vbr_repo_analyses.authorship_match_pct`` — written by the future real
   GitHub ingestion; ``None`` today, so ``verified_*`` states are reserved).
3. Builds the per-claim :class:`CandidateAttribution` block from closed
   templates ONLY, so a candidate implementation sentence can never be
   assembled for a state that does not support it (enforceable invariant).

Invariants encoded here:
  • No candidate authorship claim without candidate↔artifact relationship
    evidence — self-assertion caps at ``claimed_contributor``.
  • An explicit denial (``denied_by_candidate``) blocks every candidate
    implementation/authorship claim and is presented as honest delimitation,
    never as a suspicious contradiction.
  • Conflicting ownership statements are surfaced (``conflicted``) and never
    auto-resolved in the candidate's favour.
  • Aggregating project-level evidence can never change the ownership state —
    this module never reads artifact evidence as an ownership input.

Pure: no DB, no LLM, no I/O.
"""

from __future__ import annotations

import re
from typing import Any

from app.schemas.canonical_evidence import OWNERSHIP_STATE_LABELS

__all__ = [
    "detect_ownership_stance",
    "assess_project_ownership",
    "build_candidate_attribution",
    "ownership_blocks_candidate_implementation",
    "OWNERSHIP_DENIAL_RE",
    "OWNERSHIP_AFFIRMATION_RE",
    "VERIFIED_CONTRIBUTOR_MATCH_PCT",
    "VERIFIED_AUTHOR_MATCH_PCT",
]


# ── Stance detection (deterministic, conservative) ────────────────────────────
#
# Only EXPLICIT ownership statements match. A denial is an honest delimitation
# of the candidate's contribution ("I did not build Excalidraw") — it is not
# plagiarism language (copy/paste, borrowed code), which stays a separate
# provenance-risk signal in the defense answer engine.

_BUILD_VERBS = r"(?:build|built|create[d]?|make|made|write|written|wrote|design(?:ed)?|develop(?:ed)?|implement(?:ed)?|code[d]?|author(?:ed)?)"

OWNERSHIP_DENIAL_RE = re.compile(
    "|".join(
        [
            # "I did not (personally) build/create/design/…"
            rf"\bi\s+did\s+not\s+(?:personally\s+)?{_BUILD_VERBS}\b",
            rf"\bi\s+didn'?t\s+(?:personally\s+)?{_BUILD_VERBS}\b",
            rf"\bi\s+have\s+not\s+(?:personally\s+)?{_BUILD_VERBS}\b",
            rf"\bi\s+haven'?t\s+(?:personally\s+)?{_BUILD_VERBS}\b",
            rf"\bwe\s+did\s+not\s+{_BUILD_VERBS}\b",
            # "I did not / didn't / never contribute(d)"
            r"\bi\s+did\s+not\s+(?:personally\s+)?contribute\b",
            r"\bi\s+didn'?t\s+(?:personally\s+)?contribute\b",
            r"\bi\s+have\s+not\s+contributed\b",
            r"\bi\s+haven'?t\s+contributed\b",
            r"\bi\s+never\s+contributed\b",
            r"\bi\s+am\s+not\s+a\s+contributor\b",
            r"\bi'?m\s+not\s+a\s+contributor\b",
            # "not my project / work / code / repo(sitory)"
            r"\bnot\s+my\s+(?:own\s+)?(?:project|work|code|codebase|repo|repository|implementation)\b",
            r"\bnot\s+mine\b",
            r"\bnot\s+built\s+by\s+me\b",
            r"\bnot\s+written\s+by\s+me\b",
            # "built/created by someone else / its maintainers / the community / a third party"
            r"\b(?:built|created|developed|written|made)\s+by\s+(?:someone\s+else|the\s+community|its\s+(?:maintainers|authors|creators)|a\s+third\s+party|the\s+original\s+(?:authors|team|developers))\b",
            # "this is an open-source / public / third-party project (that) I did not…"
            r"\bi\s+was\s+not\s+involved\s+in\s+(?:building|creating|developing|writing|designing)\b",
            r"\bi\s+do\s+not\s+claim\s+(?:to\s+have\s+)?(?:built|created|authored|written|implemented)\b",
            r"\bi\s+don'?t\s+claim\s+(?:to\s+have\s+)?(?:built|created|authored|written|implemented)\b",
        ]
    ),
    re.IGNORECASE,
)

# Affirmations mirror the defense analysis service's first-person ownership
# vocabulary. Denial spans are masked out BEFORE affirmation matching so a
# phrase inside a denial ("…not my project…") can never read as an affirmation.
OWNERSHIP_AFFIRMATION_RE = re.compile(
    "|".join(
        [
            r"\bi\s+built\b",
            r"\bi\s+implemented\b",
            r"\bi\s+developed\b",
            r"\bi\s+created\b",
            r"\bi\s+designed\b",
            r"\bi\s+wrote\b",
            r"\bi\s+coded\b",
            r"\bi\s+authored\b",
            r"\bi\s+contributed\b",
            r"\bmy\s+implementation\b",
            r"\bmy\s+contribution\b",
            r"\bmy\s+project\b",
            r"\bmy\s+design\b",
            r"\bi\s+was\s+responsible\s+for\b",
            r"\bi\s+personally\s+(?:built|implemented|developed|created|designed|wrote)\b",
        ]
    ),
    re.IGNORECASE,
)

# Candidate-specific attribution evidence thresholds (read from stored repo
# analysis rows — written only by real, candidate-identity-verified ingestion;
# the current placeholder ingestion stores ``None`` so these stay unreachable
# until that evidence genuinely exists).
VERIFIED_CONTRIBUTOR_MATCH_PCT = 20.0
VERIFIED_AUTHOR_MATCH_PCT = 80.0


def detect_ownership_stance(text: Any) -> str:
    """Ownership stance of one candidate statement.

    Returns ``denied`` / ``affirmed`` / ``mixed`` / ``none``. ``mixed`` means
    the statement both delimits and claims scope ("I did not build the app,
    but I implemented the export feature") — an honest scoped contribution.
    """
    value = str(text or "")
    if not value.strip():
        return "none"
    denial_spans = list(OWNERSHIP_DENIAL_RE.finditer(value))
    denied = bool(denial_spans)
    # Mask denial spans so their inner words never match as affirmations.
    masked = value
    for match in reversed(denial_spans):
        masked = masked[: match.start()] + (" " * (match.end() - match.start())) + masked[match.end() :]
    affirmed = bool(OWNERSHIP_AFFIRMATION_RE.search(masked))
    if denied and affirmed:
        return "mixed"
    if denied:
        return "denied"
    if affirmed:
        return "affirmed"
    return "none"


# ── Project-level ownership assessment ────────────────────────────────────────


def _attribution_match_pct(repo_analysis: dict[str, Any] | None) -> float | None:
    if not isinstance(repo_analysis, dict):
        return None
    value = repo_analysis.get("authorship_match_pct")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def assess_project_ownership(
    *,
    answer_items: list[dict[str, Any]] | None,
    repo_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assess the candidate↔project ownership state for ONE project.

    ``answer_items`` are defense answer evidence objects (each may carry an
    ``ownership_stance`` set by the answer engine; when absent the stance is
    detected here from the safe answer summary). ``repo_analysis`` is the
    project's stored ``vbr_repo_analyses`` row — the ONLY input that can reach
    a ``verified_*`` state, because it is the only candidate↔artifact
    attribution evidence the platform stores.

    Returns a JSON-safe dict: ``state``, ``label``, ``basis`` (deterministic
    reason strings), ``denial_statements`` / ``affirmation_statements`` (safe
    answer summaries), ``limitations``.
    """
    denial_statements: list[str] = []
    affirmation_statements: list[str] = []
    for item in answer_items or []:
        if not isinstance(item, dict):
            continue
        stance = str(item.get("ownership_stance") or "").strip().lower()
        summary = str(item.get("safe_answer_summary") or "").strip()
        if stance not in ("affirmed", "denied", "mixed", "none"):
            stance = detect_ownership_stance(summary)
        if stance == "denied" and summary:
            denial_statements.append(summary)
        elif stance == "affirmed" and summary:
            affirmation_statements.append(summary)
        elif stance == "mixed" and summary:
            # A scoped statement both delimits and claims — record both sides.
            denial_statements.append(summary)
            affirmation_statements.append(summary)

    basis: list[str] = []
    limitations: list[str] = []

    # 1 — candidate-specific attribution evidence (the only path to verified).
    match_pct = _attribution_match_pct(repo_analysis)
    if match_pct is not None and match_pct >= VERIFIED_CONTRIBUTOR_MATCH_PCT:
        verified_author = match_pct >= VERIFIED_AUTHOR_MATCH_PCT
        state = "verified_author" if verified_author else "verified_contributor"
        basis.append(
            "Candidate-specific repository attribution evidence links the candidate "
            "to this project's commit history."
        )
        if denial_statements and not affirmation_statements:
            # Verified attribution + explicit denial is a genuine conflict —
            # never resolved in either direction automatically.
            return {
                "state": "conflicted",
                "label": OWNERSHIP_STATE_LABELS["conflicted"],
                "basis": basis
                + [
                    "The candidate explicitly denied contributing, but stored attribution "
                    "evidence links them to the repository — review required."
                ],
                "denial_statements": denial_statements[:3],
                "affirmation_statements": affirmation_statements[:3],
                "limitations": ["Conflicting ownership evidence blocks candidate implementation claims."],
            }
        return {
            "state": state,
            "label": OWNERSHIP_STATE_LABELS[state],
            "basis": basis,
            "denial_statements": denial_statements[:3],
            "affirmation_statements": affirmation_statements[:3],
            "limitations": limitations,
        }

    # 2 — statement-only assessment (self-description; never verified).
    whole_denial = bool(denial_statements) and not affirmation_statements
    whole_affirmation = bool(affirmation_statements) and not denial_statements

    if whole_denial:
        state = "denied_by_candidate"
        basis.append(
            "The candidate explicitly stated they did not build or contribute to "
            "this project."
        )
        limitations.append(
            "Candidate implementation/authorship claims are blocked for this project."
        )
    elif denial_statements and affirmation_statements:
        # Both sides present across the defense. A single 'mixed' statement is
        # an honestly scoped contribution; denial in one answer and a
        # whole-project affirmation in another is a conflict. We cannot always
        # tell scope apart deterministically, so the conservative reading wins:
        # the contribution stands as CLAIMED (never verified) and the explicit
        # delimitation is preserved verbatim for the recruiter.
        state = "claimed_contributor"
        basis.append(
            "The candidate described a scoped contribution while explicitly "
            "delimiting parts of the project they did not build."
        )
        limitations.append(
            "Self-described contribution — not independently verified; the candidate "
            "also explicitly delimited the scope of their work."
        )
    elif whole_affirmation:
        state = "claimed_contributor"
        basis.append(
            "The candidate affirmatively described their own contribution during "
            "the Project Defense."
        )
        limitations.append(
            "Self-described contribution — not independently verified against the "
            "artifact's history."
        )
    else:
        state = "unknown"
        basis.append(
            "No candidate statement or attribution evidence connects the candidate "
            "to this project's implementation."
        )
        limitations.append(
            "Candidate implementation claims are withheld until contribution "
            "evidence exists."
        )

    return {
        "state": state,
        "label": OWNERSHIP_STATE_LABELS[state],
        "basis": basis,
        "denial_statements": denial_statements[:3],
        "affirmation_statements": affirmation_statements[:3],
        "limitations": limitations,
    }


def ownership_blocks_candidate_implementation(state: Any) -> bool:
    """True when the state forbids ANY candidate implementation/authorship claim."""
    return str(state or "unknown") in ("unknown", "denied_by_candidate", "conflicted")


# ── Per-claim candidate attribution (closed templates ONLY) ──────────────────
#
# The candidate-level sentence is assembled exclusively from these templates,
# keyed by ownership state — so an implementation sentence for a non-attributed
# candidate is structurally impossible, not merely discouraged.

_STATE_SENTENCES = {
    "verified_author": "The candidate personally implemented this work (verified attribution evidence).",
    "verified_contributor": "The candidate contributed to this implementation (verified attribution evidence).",
    "claimed_contributor": (
        "The candidate describes contributing to this project; this self-description "
        "is not independently verified."
    ),
    "unknown": (
        "No evidence connects the candidate to this project's implementation — "
        "candidate contribution is not established."
    ),
    "denied_by_candidate": (
        "The candidate explicitly stated they did not build or contribute to this "
        "project — implementation is not attributed to the candidate."
    ),
    "conflicted": (
        "Ownership evidence for this project conflicts — implementation is not "
        "attributed to the candidate until the conflict is resolved."
    ),
}


def build_candidate_attribution(
    *,
    ownership: dict[str, Any] | None,
    skill_name: str | None = None,
    understanding_demonstrated: bool = False,
    usage_demonstrated: bool = False,
) -> dict[str, Any]:
    """Build one JSON-safe :class:`CandidateAttribution` block.

    ``ownership`` is an :func:`assess_project_ownership` result (or ``None`` →
    ``unknown``). ``understanding_demonstrated`` / ``usage_demonstrated`` are
    set from COUNTED candidate-explanation / runtime-workflow citations for the
    claim — they describe what the candidate demonstrably did, and never change
    the ownership state.
    """
    ownership = ownership if isinstance(ownership, dict) else {}
    state = str(ownership.get("state") or "unknown")
    if state not in _STATE_SENTENCES:
        state = "unknown"
    skill = str(skill_name or "").strip()

    parts = [_STATE_SENTENCES[state]]
    if understanding_demonstrated:
        parts.append(
            f"The candidate demonstrated understanding of {skill or 'this skill'} "
            "in the Project Defense."
        )
    if usage_demonstrated:
        parts.append(
            "The candidate demonstrated the application's behaviour in a recorded "
            "workflow."
        )

    limitations = [str(x) for x in (ownership.get("limitations") or [])]
    if state == "claimed_contributor":
        # Invariant 7: self-assertion never silently becomes verified authorship.
        limitations.append(
            "Contribution is candidate-claimed; no candidate-specific artifact "
            "attribution evidence verifies it."
        )

    return {
        "state": state,
        "label": OWNERSHIP_STATE_LABELS[state],
        "candidate_claim_text": " ".join(parts),
        "understanding_demonstrated": bool(understanding_demonstrated),
        "usage_demonstrated": bool(usage_demonstrated),
        "basis": [str(x) for x in (ownership.get("basis") or [])],
        "limitations": _dedupe(limitations),
    }


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
