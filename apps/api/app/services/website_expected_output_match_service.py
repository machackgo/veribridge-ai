"""Expected-output matching for semantic website verification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.services.website_semantic_similarity_service import (
    SentenceEmbeddingProvider,
    compact_semantic_fragments,
    compute_embedding_similarity,
    normalize_semantic_text,
)

_METHOD = "expected_output_sentence_transformers_cosine_similarity"
_TEXT_LIMIT = 1200
_PREVIEW_LIMIT = 400

_STOPWORDS = {
    "after",
    "appear",
    "appears",
    "available",
    "confirm",
    "display",
    "displayed",
    "displays",
    "found",
    "output",
    "page",
    "result",
    "results",
    "section",
    "should",
    "show",
    "shown",
    "that",
    "this",
    "visible",
    "website",
    "with",
}

_DOMAIN_PHRASES = [
    "risk score",
    "accident risk",
    "risk prediction",
    "safer route",
    "safer rerouting",
    "rerouting recommendation",
    "route recommendation",
    "route risk",
    "verification result",
    "selected skill",
    "skill found",
    "python usage",
    "github evidence",
    "submitted project",
    "prediction probability",
    "predicted label",
    "disease label",
    "salary range",
    "market comparison",
    "salary recommendation",
    "customized resume",
    "resume draft",
    "job description",
]

_GENERIC_OUTPUTS = {
    "success",
    "successful",
    "completed",
    "complete",
    "done",
    "submitted",
    "loaded",
    "saved",
    "uploaded",
    "finished",
}


@dataclass(frozen=True)
class ExpectedOutputMatchResult:
    available: bool
    score: float | None
    label: str
    expected_output_text: str
    observed_output_text: str
    exact_signal_hits: list[str]
    missing_required_signals: list[str]
    supports_verification: bool
    blocks_full_verification: bool
    notes: str | None = None
    model_name: str | None = None
    method: str = _METHOD


def build_expected_output_text(context: dict[str, Any]) -> str:
    plan = context.get("plan") or {}
    fragments = [
        str(plan.get("expected_output") or ""),
    ]
    feature = normalize_semantic_text(str(plan.get("feature_to_verify") or ""))
    if feature:
        fragments.append(f"Feature context: {feature}.")
    return compact_semantic_fragments(fragments, _TEXT_LIMIT)


def build_observed_output_text(context: dict[str, Any]) -> str:
    browser_run = context.get("browser_run") or {}
    browser_steps = context.get("browser_steps") or []
    static_run = context.get("static_run") or {}
    static_checks = context.get("static_checks") or []
    fragments: list[str] = []

    if browser_steps:
        for step in browser_steps[:8]:
            if step.get("observed_result"):
                fragments.append(str(step.get("observed_result")))
            if step.get("step_status") in {"passed", "failed", "needs_human_review"} and step.get("step_summary"):
                fragments.append(str(step.get("step_summary")))
    if browser_run:
        if browser_run.get("safe_text_snapshot"):
            fragments.append(str(browser_run.get("safe_text_snapshot")))
        if browser_run.get("execution_summary"):
            fragments.append(str(browser_run.get("execution_summary")))
    if not fragments and static_run:
        if static_run.get("execution_summary"):
            fragments.append(str(static_run.get("execution_summary")))
        for check in static_checks[:8]:
            if check.get("observed_value"):
                fragments.append(str(check.get("observed_value")))
            if check.get("check_summary"):
                fragments.append(str(check.get("check_summary")))
    return compact_semantic_fragments(fragments, _TEXT_LIMIT)


def extract_required_output_signals(expected_output_text: str) -> list[str]:
    normalized = normalize_semantic_text(expected_output_text).lower()
    # Feature context helps embeddings, but required output signals should come
    # from the student's stated visible output rather than the broader claim.
    normalized = normalized.split("feature context:", 1)[0].strip()
    signals: list[str] = []
    for phrase in _DOMAIN_PHRASES:
        if phrase in normalized and phrase not in signals:
            signals.append(phrase)
    if "predicted" in normalized and "label" in normalized and "predicted label" not in signals:
        signals.append("predicted label")
    tokens = _meaningful_tokens(normalized)
    for token in tokens:
        if any(token in phrase.split() for phrase in signals):
            continue
        if token not in signals:
            signals.append(token)
    return signals[:12]


def detect_exact_output_signal_hits(expected_signals: list[str], observed_output_text: str) -> list[str]:
    observed = normalize_semantic_text(observed_output_text).lower()
    hits: list[str] = []
    for signal in expected_signals:
        if _signal_present(signal, observed):
            hits.append(signal)
    return hits


def detect_missing_required_signals(expected_signals: list[str], observed_output_text: str) -> list[str]:
    hits = set(detect_exact_output_signal_hits(expected_signals, observed_output_text))
    return [signal for signal in expected_signals if signal not in hits]


def compute_expected_output_semantic_similarity(
    expected_text: str,
    observed_text: str,
    embedding_provider: SentenceEmbeddingProvider | None = None,
) -> float | None:
    return compute_embedding_similarity(expected_text, observed_text, embedding_provider)


def interpret_expected_output_match(
    score: float | None,
    hits: list[str],
    misses: list[str],
    expected_output_text: str,
    observed_output_text: str,
    *,
    model_name: str | None = None,
    notes: str | None = None,
) -> ExpectedOutputMatchResult:
    if not expected_output_text or not observed_output_text:
        return ExpectedOutputMatchResult(
            available=False,
            score=score,
            label="unavailable",
            expected_output_text=expected_output_text,
            observed_output_text=observed_output_text,
            exact_signal_hits=hits,
            missing_required_signals=misses,
            supports_verification=False,
            blocks_full_verification=True,
            notes=notes or "Expected or observed output text was unavailable.",
            model_name=model_name,
        )

    generic = _is_generic_observed_output(observed_output_text)
    miss_ratio = len(misses) / max(1, len(hits) + len(misses))
    if score is None and hits and miss_ratio <= 0.35 and not generic:
        label = "moderate_expected_output_match"
    elif score is None and hits:
        label = "weak_expected_output_match"
    elif score is None:
        label = "unavailable"
    elif score >= 0.80 and hits and miss_ratio <= 0.35 and not generic:
        label = "strong_expected_output_match"
    elif score >= 0.65 and hits and miss_ratio <= 0.55 and not generic:
        label = "moderate_expected_output_match"
    elif score >= 0.50 and len(hits) >= 2 and miss_ratio <= 0.20 and not generic:
        label = "moderate_expected_output_match"
    elif score >= 0.50 or hits:
        label = "weak_expected_output_match"
    else:
        label = "low_expected_output_match"

    supports = label in {"strong_expected_output_match", "moderate_expected_output_match"} and not generic
    blocks = label in {"weak_expected_output_match", "low_expected_output_match", "unavailable"} or generic or (len(misses) > len(hits) and len(misses) >= 2)
    if generic:
        notes = "Observed output was generic and did not demonstrate the specific expected result."
    return ExpectedOutputMatchResult(
        available=score is not None,
        score=score,
        label=label,
        expected_output_text=expected_output_text,
        observed_output_text=observed_output_text,
        exact_signal_hits=hits,
        missing_required_signals=misses,
        supports_verification=supports,
        blocks_full_verification=blocks,
        notes=notes,
        model_name=model_name,
    )


def evaluate_expected_output_match(
    context: dict[str, Any],
    embedding_provider: SentenceEmbeddingProvider | None = None,
) -> ExpectedOutputMatchResult:
    expected_text = build_expected_output_text(context)
    observed_text = build_observed_output_text(context)
    signals = extract_required_output_signals(expected_text)
    hits = detect_exact_output_signal_hits(signals, observed_text)
    misses = [signal for signal in signals if signal not in set(hits)]
    provider = embedding_provider
    try:
        score = compute_expected_output_semantic_similarity(expected_text, observed_text, provider)
    except Exception as exc:
        return interpret_expected_output_match(
            None,
            hits,
            misses,
            expected_text,
            observed_text,
            model_name=getattr(provider, "model_name", None),
            notes=f"Local expected-output similarity unavailable: {type(exc).__name__}. Exact signal fallback was used.",
        )
    return interpret_expected_output_match(
        score,
        hits,
        misses,
        expected_text,
        observed_text,
        model_name=getattr(provider, "model_name", None),
    )


def expected_output_match_to_snapshot(result: ExpectedOutputMatchResult | dict[str, Any] | None) -> dict[str, Any]:
    if result is None:
        return {
            "available": False,
            "score": None,
            "label": "unavailable",
            "exact_signal_hits": [],
            "missing_required_signals": [],
            "supports_verification": False,
            "blocks_full_verification": True,
        }
    if isinstance(result, dict):
        return {
            "available": bool(result.get("available")),
            "score": result.get("score"),
            "label": result.get("label") or "unavailable",
            "exact_signal_hits": list(result.get("exact_signal_hits") or []),
            "missing_required_signals": list(result.get("missing_required_signals") or []),
            "supports_verification": bool(result.get("supports_verification")),
            "blocks_full_verification": bool(result.get("blocks_full_verification")),
            "notes": result.get("notes"),
            "model": result.get("model_name") or result.get("model"),
            "method": result.get("method") or _METHOD,
            "expected_output_preview": _preview(result.get("expected_output_text")),
            "observed_output_preview": _preview(result.get("observed_output_text")),
        }
    return {
        "available": result.available,
        "score": result.score,
        "label": result.label,
        "exact_signal_hits": result.exact_signal_hits,
        "missing_required_signals": result.missing_required_signals,
        "supports_verification": result.supports_verification,
        "blocks_full_verification": result.blocks_full_verification,
        "notes": result.notes,
        "model": result.model_name,
        "method": result.method,
        "expected_output_preview": _preview(result.expected_output_text),
        "observed_output_preview": _preview(result.observed_output_text),
    }


def _meaningful_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+(?:[-'][a-z0-9]+)?", value.lower())
    deduped: list[str] = []
    for token in tokens:
        if len(token) < 4 or token in _STOPWORDS:
            continue
        if token.endswith("ing") and len(token) > 6:
            token = token[:-3]
        if token.endswith("ed") and len(token) > 5:
            token = token[:-2]
        if token not in deduped:
            deduped.append(token)
    return deduped


def _signal_present(signal: str, observed: str) -> bool:
    if signal in observed:
        return True
    if signal in {"route recommendation", "rerouting recommendation"} and ("route" in observed or "rerouting" in observed) and "available" in observed:
        return True
    if signal == "recommendation" and "available" in observed:
        return True
    words = _meaningful_tokens(signal)
    if not words:
        return False
    return all(word in observed for word in words)


def _is_generic_observed_output(observed_output_text: str) -> bool:
    tokens = _meaningful_tokens(observed_output_text)
    if not tokens:
        return True
    generic_count = sum(1 for token in tokens if token in _GENERIC_OUTPUTS)
    return len(tokens) <= 5 and generic_count >= 1


def _preview(value: Any, limit: int = _PREVIEW_LIMIT) -> str | None:
    if value is None:
        return None
    text = normalize_semantic_text(str(value))
    return text[:limit] if text else None
