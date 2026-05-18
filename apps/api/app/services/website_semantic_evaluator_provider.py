"""Provider abstraction for website semantic verification evaluators."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.services.website_semantic_similarity_service import semantic_similarity_label

_EVALUATOR_PROVIDER = "deterministic_mock"
_EVALUATOR_VERSION = "website-semantic-evaluator-mock-v1"


@dataclass(frozen=True)
class WebsiteSemanticEvaluationResult:
    semantic_status: str
    confidence_score: float
    recruiter_facing_summary: str
    evidence_summary: str
    limitations: str
    recommended_next_action: str
    internal_reasoning_summary: str
    evaluator_provider: str = _EVALUATOR_PROVIDER
    evaluator_version: str = _EVALUATOR_VERSION


class WebsiteSemanticEvaluatorProvider(Protocol):
    evaluator_provider: str
    evaluator_version: str

    def evaluate(self, context: dict[str, Any]) -> WebsiteSemanticEvaluationResult:
        """Return a semantic verification judgment from structured evidence."""


class DeterministicMockWebsiteSemanticEvaluator:
    """Conservative deterministic evaluator until model-backed providers are added."""

    evaluator_provider = _EVALUATOR_PROVIDER
    evaluator_version = _EVALUATOR_VERSION

    def evaluate(self, context: dict[str, Any]) -> WebsiteSemanticEvaluationResult:
        status = determine_semantic_status(context)
        confidence = calculate_confidence_score(context, status)
        return WebsiteSemanticEvaluationResult(
            semantic_status=status,
            confidence_score=confidence,
            recruiter_facing_summary=build_recruiter_facing_summary(context, status),
            evidence_summary=build_evidence_summary(context),
            limitations=build_limitations(context, status),
            recommended_next_action=build_recommended_next_action(context, status),
            internal_reasoning_summary=build_internal_reasoning_summary(context, status),
            evaluator_provider=self.evaluator_provider,
            evaluator_version=self.evaluator_version,
        )


def determine_semantic_status(context: dict[str, Any]) -> str:
    plan = context.get("plan") or {}
    static_run = context.get("static_run")
    browser_run = context.get("browser_run")
    browser_status = (browser_run or {}).get("browser_execution_status")
    static_status = (static_run or {}).get("execution_status")

    if not static_run and not browser_run:
        return "insufficient_evidence"
    if _plan_is_sparse(plan):
        return "insufficient_evidence"
    if plan.get("requires_login") or browser_status == "blocked_by_login":
        return "needs_human_review"
    if _plan_is_ambiguous(plan):
        return "needs_human_review"
    if browser_status == "needs_human_review" and _strong_semantic_similarity(context):
        return "partially_verified"
    if browser_status in {"needs_human_review", "unsupported_plan", "execution_timeout", "execution_error"}:
        return "needs_human_review"
    if browser_status == "browser_verified" and _expected_signals_found(context) and not _has_major_blocking_warnings(plan):
        if _expected_output_match_blocks_full_verification(context):
            return "needs_human_review"
        return "verified"
    if browser_status == "browser_partially_verified":
        return "partially_verified"
    if static_status == "partial_verification" and browser_status in {None, "needs_human_review", "unsupported_plan"}:
        return "partially_verified"
    if _expected_signals_found(context) and browser_status != "browser_failed":
        return "partially_verified"
    if browser_status == "browser_failed" and static_status == "failed_static_checks":
        return "not_verified"
    if browser_status == "browser_failed" and not _expected_signals_found(context):
        return "not_verified"
    if static_status == "failed_static_checks" and not browser_run:
        return "not_verified"
    if static_status == "static_verified" and not browser_run:
        return "partially_verified"
    return "needs_human_review"


def calculate_confidence_score(context: dict[str, Any], status: str | None = None) -> float:
    status = status or determine_semantic_status(context)
    static_run = context.get("static_run") or {}
    browser_run = context.get("browser_run") or {}
    plan = context.get("plan") or {}
    signal_hits = len(_expected_signal_hits(context))
    similarity_score = _semantic_similarity_score(context)

    if status == "verified":
        score = 0.88 + min(signal_hits, 5) * 0.015
        if int(browser_run.get("steps_failed") or 0) == 0:
            score += 0.03
        score += _semantic_similarity_confidence_boost(similarity_score, maximum=0.04)
        if _expected_output_match_supports_verification(context):
            score += 0.03
        return _clamp(score, 0.85, 0.98)
    if status == "partially_verified":
        score = 0.58 + min(signal_hits, 4) * 0.04
        if (static_run.get("execution_status") == "partial_verification") or (browser_run.get("browser_execution_status") == "browser_partially_verified"):
            score += 0.08
        score += _semantic_similarity_confidence_boost(similarity_score, maximum=0.08)
        return _clamp(score, 0.55, 0.84)
    if status == "not_verified":
        score = 0.74
        if static_run.get("execution_status") == "failed_static_checks" and browser_run.get("browser_execution_status") == "browser_failed":
            score += 0.12
        return _clamp(score, 0.70, 0.95)
    if status == "needs_human_review":
        score = 0.42
        if plan.get("requires_login") or browser_run.get("browser_execution_status") == "blocked_by_login":
            score += 0.1
        if signal_hits:
            score += 0.08
        if _expected_output_match_blocks_full_verification(context):
            score += 0.05
        score += _semantic_similarity_confidence_boost(similarity_score, maximum=0.04)
        return _clamp(score, 0.35, 0.70)
    if status == "insufficient_evidence":
        return _clamp(0.18 + min(signal_hits, 2) * 0.05, 0.10, 0.40)
    return 0.0


def build_recruiter_facing_summary(context: dict[str, Any], status: str) -> str:
    output_match = context.get("expected_output_match") or {}
    output_mismatch = output_match.get("blocks_full_verification")
    if status == "verified":
        if output_match.get("supports_verification"):
            hits = output_match.get("exact_signal_hits") or []
            suffix = f": {', '.join(hits[:3])}." if hits else "."
            return f"VeriBridge verified that the website completed the guided browser flow and displayed output matching the student's claimed result{suffix}"
        return "VeriBridge verified that the deployed website demonstrated the claimed feature through a completed browser execution flow and matching output signals."
    if status == "partially_verified":
        if output_mismatch:
            return "VeriBridge observed some supporting website behavior, but the resulting output did not fully match the student's expected verification result."
        return "VeriBridge observed supporting evidence for the claimed website feature, but the automated execution could not fully confirm every expected step."
    if status == "not_verified":
        if output_mismatch:
            return "VeriBridge could not confirm the claimed feature because the observed website output did not match the stated expected result."
        return "VeriBridge could not confirm the claimed website behavior from the available static and browser execution evidence."
    if status == "needs_human_review":
        if output_mismatch:
            return "The site produced an output after execution, but the output did not clearly demonstrate the exact claimed feature and should be reviewed manually."
        return "The website proof produced mixed or incomplete signals and should be reviewed by a human before being treated as verified."
    if status == "insufficient_evidence":
        return "Not enough verification evidence is available yet to make a reliable judgment."
    return "VeriBridge could not complete semantic evaluation because of an internal evaluation error."


def build_evidence_summary(context: dict[str, Any]) -> str:
    parts: list[str] = []
    static_run = context.get("static_run") or {}
    browser_run = context.get("browser_run") or {}
    hits = _expected_signal_hits(context)
    if static_run:
        parts.append(
            "Static run {status}: {passed}/{attempted} checks passed.".format(
                status=static_run.get("execution_status"),
                passed=int(static_run.get("checks_passed") or 0),
                attempted=int(static_run.get("checks_attempted") or 0),
            )
        )
    if browser_run:
        parts.append(
            "Browser run {status}: {passed}/{attempted} safe steps passed.".format(
                status=browser_run.get("browser_execution_status"),
                passed=int(browser_run.get("steps_passed") or 0),
                attempted=int(browser_run.get("steps_attempted") or 0),
            )
        )
    if hits:
        parts.append(f"Observed expected output signals: {', '.join(hits[:8])}.")
    similarity = context.get("semantic_similarity") or {}
    if similarity.get("available") and similarity.get("score") is not None:
        parts.append(f"Claim/output semantic similarity was {similarity.get('interpretation') or semantic_similarity_label(similarity.get('score'))} ({float(similarity['score']):.2f}).")
    output_match = context.get("expected_output_match") or {}
    if output_match:
        parts.append(
            "Expected-output match was {label}{score}.".format(
                label=output_match.get("label") or "unavailable",
                score=f" ({float(output_match['score']):.2f})" if output_match.get("score") is not None else "",
            )
        )
    if not parts:
        return "No static or browser verification run evidence is available yet."
    return " ".join(parts)


def build_limitations(context: dict[str, Any], status: str) -> str:
    limitations = [
        "This evaluation confirms visible website behavior, not the correctness of hidden backend logic.",
        "It does not independently validate model accuracy, business correctness, or production reliability.",
        "Semantic evaluation is currently based on structured evidence and deterministic logic, not a live external LLM provider.",
    ]
    plan = context.get("plan") or {}
    browser_run = context.get("browser_run") or {}
    if status in {"needs_human_review", "insufficient_evidence"} or plan.get("requires_login") or browser_run.get("browser_execution_status") == "blocked_by_login":
        limitations.append("Login-required, sparse, or ambiguous flows may need human review.")
    if (context.get("expected_output_match") or {}).get("blocks_full_verification"):
        limitations.append("The observed output did not fully match the student's stated expected result.")
    return " ".join(limitations)


def build_recommended_next_action(context: dict[str, Any], status: str) -> str:
    if status == "verified":
        return "No further action required."
    if status == "partially_verified":
        return "Review the remaining unconfirmed steps or rerun verification with clearer expected outputs."
    if status == "not_verified":
        return "Ask the student to provide a working public flow or clearer proof evidence."
    if status == "needs_human_review":
        return "Human review recommended because the website required ambiguous interactive interpretation."
    if status == "insufficient_evidence":
        return "Run static and browser website verification before relying on this proof."
    return "Retry semantic evaluation after checking service health."


def build_internal_reasoning_summary(context: dict[str, Any], status: str) -> str:
    static_status = ((context.get("static_run") or {}).get("execution_status")) or "none"
    browser_status = ((context.get("browser_run") or {}).get("browser_execution_status")) or "none"
    hits = _expected_signal_hits(context)
    similarity = context.get("semantic_similarity") or {}
    output_match = context.get("expected_output_match") or {}
    similarity_note = ""
    if similarity.get("available") and similarity.get("score") is not None:
        label = similarity.get("interpretation") or semantic_similarity_label(similarity.get("score"))
        if label == "strong_semantic_match":
            similarity_note = " Claim/output semantic similarity was strong."
        elif label == "moderate_semantic_match":
            similarity_note = " Claim/output semantic similarity was moderate."
        else:
            similarity_note = f" Claim/output semantic similarity was {label}."
    elif similarity:
        similarity_note = " Claim/output semantic similarity was unavailable."
    output_note = ""
    if output_match:
        output_note = (
            f" Expected-output match was {output_match.get('label') or 'unavailable'} "
            f"with hits={', '.join((output_match.get('exact_signal_hits') or [])[:5]) or 'none'} "
            f"and misses={', '.join((output_match.get('missing_required_signals') or [])[:5]) or 'none'}."
        )
    return (
        f"Status {status} based on plan_status={((context.get('plan') or {}).get('plan_status') or 'unknown')}, "
        f"static_status={static_status}, browser_status={browser_status}, "
        f"expected_signal_hits={', '.join(hits[:6]) if hits else 'none'}."
        f"{similarity_note}"
        f"{output_note}"
    )


def _expected_signals_found(context: dict[str, Any]) -> bool:
    return bool(_expected_signal_hits(context))


def _expected_signal_hits(context: dict[str, Any]) -> list[str]:
    plan = context.get("plan") or {}
    expected_keywords = _meaningful_keywords(plan.get("expected_output") or "")
    if not expected_keywords:
        return []
    observed_text = " ".join(
        [
            str((context.get("static_run") or {}).get("execution_summary") or ""),
            " ".join(str(check.get("check_summary") or "") for check in (context.get("static_checks") or [])),
            " ".join(str(check.get("observed_value") or "") for check in (context.get("static_checks") or [])),
            str((context.get("browser_run") or {}).get("execution_summary") or ""),
            str((context.get("browser_run") or {}).get("page_title") or ""),
            str((context.get("browser_run") or {}).get("safe_text_snapshot") or ""),
            " ".join(str(step.get("step_summary") or "") for step in (context.get("browser_steps") or [])),
            " ".join(str(step.get("observed_result") or "") for step in (context.get("browser_steps") or [])),
        ]
    ).lower()
    return [keyword for keyword in expected_keywords if keyword in observed_text]


def _plan_is_sparse(plan: dict[str, Any]) -> bool:
    return not str(plan.get("expected_output") or "").strip() or not (plan.get("normalized_test_steps") or [])


def _plan_is_ambiguous(plan: dict[str, Any]) -> bool:
    warnings = set(plan.get("validation_warnings") or [])
    return bool(warnings & {"vague_verification_steps", "expected_output_too_generic", "missing_sample_inputs"})


def _has_major_blocking_warnings(plan: dict[str, Any]) -> bool:
    warnings = set(plan.get("validation_warnings") or [])
    return bool(warnings & {"unsupported_instruction_detected", "login_required_without_safe_access_notes"})


def _semantic_similarity_score(context: dict[str, Any]) -> float | None:
    similarity = context.get("semantic_similarity") or {}
    if not similarity.get("available"):
        return None
    score = similarity.get("score")
    return float(score) if score is not None else None


def _strong_semantic_similarity(context: dict[str, Any]) -> bool:
    score = _semantic_similarity_score(context)
    return score is not None and score >= 0.82


def _expected_output_match_supports_verification(context: dict[str, Any]) -> bool:
    match = context.get("expected_output_match")
    if not match:
        return True
    return bool(match.get("supports_verification")) and not bool(match.get("blocks_full_verification"))


def _expected_output_match_blocks_full_verification(context: dict[str, Any]) -> bool:
    match = context.get("expected_output_match")
    if not match:
        return False
    return bool(match.get("blocks_full_verification")) or match.get("label") in {
        "weak_expected_output_match",
        "low_expected_output_match",
        "unavailable",
    }


def _semantic_similarity_confidence_boost(score: float | None, maximum: float) -> float:
    if score is None:
        return 0.0
    if score >= 0.82:
        return maximum
    if score >= 0.68:
        return maximum / 2
    return 0.0


def _meaningful_keywords(value: str) -> list[str]:
    stopwords = {
        "after",
        "with",
        "that",
        "this",
        "from",
        "into",
        "appears",
        "shows",
        "show",
        "display",
        "displays",
        "page",
        "website",
        "user",
        "users",
        "input",
        "output",
        "card",
        "result",
        "results",
        "visible",
        "confirm",
        "public",
    }
    tokens = re.findall(r"[a-z0-9]+", (value or "").lower())
    deduped: list[str] = []
    for token in tokens:
        if len(token) < 4 or token in stopwords:
            continue
        if token.endswith("ing") and len(token) > 6:
            token = token[:-3]
        if token.endswith("ed") and len(token) > 5:
            token = token[:-2]
        if token not in deduped:
            deduped.append(token)
    return deduped[:20]


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return round(max(minimum, min(maximum, value)), 4)
