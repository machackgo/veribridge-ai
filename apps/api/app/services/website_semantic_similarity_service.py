"""Local semantic similarity support for website proof verification."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_METHOD = "sentence_transformers_cosine_similarity"
_TEXT_LIMIT = 2500
_BUNDLE_TEXT_LIMIT = 1800
_PREVIEW_LIMIT = 500


class SentenceEmbeddingProvider(Protocol):
    model_name: str

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""


@dataclass(frozen=True)
class SemanticSimilarityResult:
    available: bool
    score: float | None
    model_name: str | None
    method: str
    claim_text: str
    observed_text: str
    interpretation: str
    supports_verification: bool
    notes: str | None = None
    claim_bundle_source_fields: list[str] | None = None
    observed_bundle_source_fields: list[str] | None = None


class LocalSentenceEmbeddingProvider:
    """Lazy local Sentence Transformers embedding provider.

    By default this only uses locally cached model files. Set
    VERIBRIDGE_ALLOW_MODEL_DOWNLOAD=true in a development environment if
    you want Sentence Transformers to fetch the model cache explicitly.
    """

    def __init__(self, model_name: str = _DEFAULT_MODEL, allow_download: bool | None = None) -> None:
        self.model_name = model_name
        self._model: Any | None = None
        if allow_download is None:
            allow_download = os.getenv("VERIBRIDGE_ALLOW_MODEL_DOWNLOAD", "").lower() in {"1", "true", "yes"}
        self._allow_download = allow_download

    def encode(self, texts: list[str]) -> list[list[float]]:
        model = self._load_model()
        embeddings = model.encode(texts, convert_to_numpy=False, normalize_embeddings=False)
        return [_as_float_list(embedding) for embedding in embeddings]

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        from sentence_transformers import SentenceTransformer

        kwargs = {} if self._allow_download else {"local_files_only": True}
        self._model = SentenceTransformer(self.model_name, **kwargs)
        return self._model


def normalize_semantic_text(text: str) -> str:
    fragments = [fragment.strip() for fragment in re.split(r"[\r\n\t]+", text or "")]
    return re.sub(r"\s+", " ", " ".join(fragment for fragment in fragments if fragment)).strip()


def extract_candidate_semantic_texts(context: dict[str, Any]) -> list[str]:
    observed_parts = _observed_text_parts(context)
    return [part for part in (normalize_semantic_text(str(value)) for value in observed_parts) if part]


def compact_semantic_fragments(fragments: list[str], max_chars: int = _BUNDLE_TEXT_LIMIT) -> str:
    """Join semantic fragments without repeated text or oversized raw page dumps."""
    compacted: list[str] = []
    seen: set[str] = set()
    for fragment in fragments:
        normalized = normalize_semantic_text(fragment)
        if not normalized:
            continue
        dedupe_key = normalized.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        candidate = " ".join([*compacted, normalized]).strip()
        if len(candidate) > max_chars:
            remaining = max_chars - len(" ".join(compacted)) - (1 if compacted else 0)
            if remaining > 80:
                compacted.append(normalized[:remaining].rstrip())
            break
        compacted.append(normalized)
    return normalize_semantic_text(" ".join(compacted))[:max_chars]


def build_claim_semantic_bundle(context: dict[str, Any]) -> str:
    evidence = context.get("evidence") or {}
    plan = context.get("plan") or {}
    fragments: list[str] = []

    feature = normalize_semantic_text(str(plan.get("feature_to_verify") or ""))
    expected = normalize_semantic_text(str(plan.get("expected_output") or ""))
    description = normalize_semantic_text(str(evidence.get("evidence_description") or ""))
    step_summary = _summarize_plan_steps(plan.get("normalized_test_steps") or [])
    sample_summary = _summarize_sample_inputs(plan.get("sample_inputs"))

    if feature:
        fragments.append(f"The student claims that this website {feature}.")
    if expected:
        fragments.append(f"The expected visible outcome is {expected}.")
    if description and description.lower() not in " ".join(fragments).lower():
        fragments.append(f"The student described the proof as: {description}.")
    if step_summary:
        fragments.append(f"The intended verification flow includes {step_summary}.")
    if sample_summary:
        fragments.append(f"Sample inputs clarify the interaction: {sample_summary}.")

    return compact_semantic_fragments(fragments, _BUNDLE_TEXT_LIMIT)


def build_observed_semantic_bundle(context: dict[str, Any]) -> str:
    static_run = context.get("static_run") or {}
    browser_run = context.get("browser_run") or {}
    fragments: list[str] = []

    browser_status = browser_run.get("browser_execution_status")
    if browser_run:
        fragments.append(_browser_status_sentence(browser_status))
        if browser_run.get("execution_summary"):
            fragments.append(f"Browser execution summary: {browser_run.get('execution_summary')}.")
        step_summary = _summarize_browser_steps(context.get("browser_steps") or [])
        if step_summary:
            fragments.append(f"Browser step evidence included {step_summary}.")
        visible_output = _summarize_visible_output(browser_run)
        if visible_output:
            fragments.append(f"The observed page/output included {visible_output}.")
    else:
        fragments.append("No browser execution result was available.")

    if static_run:
        status = static_run.get("execution_status") or "unknown"
        if static_run.get("execution_summary"):
            fragments.append(f"Static verification status was {status}; static summary: {static_run.get('execution_summary')}.")
        else:
            fragments.append(f"Static verification status was {status}.")
        static_summary = _summarize_static_checks(context.get("static_checks") or [])
        if static_summary:
            fragments.append(f"Passed static checks found {static_summary}.")
    elif not browser_run:
        fragments.append("No static verification result was available.")

    return compact_semantic_fragments(fragments, _BUNDLE_TEXT_LIMIT)


def claim_bundle_source_fields(context: dict[str, Any]) -> list[str]:
    evidence = context.get("evidence") or {}
    plan = context.get("plan") or {}
    fields: list[str] = []
    if evidence.get("evidence_description"):
        fields.append("skill_evidence.description")
    if plan.get("feature_to_verify"):
        fields.append("plan.feature_to_verify")
    if plan.get("expected_output"):
        fields.append("plan.expected_output")
    if plan.get("normalized_test_steps"):
        fields.append("plan.normalized_test_steps")
    if plan.get("sample_inputs"):
        fields.append("plan.sample_inputs")
    return fields


def observed_bundle_source_fields(context: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    browser_run = context.get("browser_run") or {}
    static_run = context.get("static_run") or {}
    if browser_run.get("browser_execution_status"):
        fields.append("browser_run.browser_execution_status")
    if browser_run.get("execution_summary"):
        fields.append("browser_run.execution_summary")
    if context.get("browser_steps"):
        fields.append("browser_steps.step_summary")
        fields.append("browser_steps.observed_result")
    if browser_run.get("safe_text_snapshot"):
        fields.append("browser_run.safe_text_snapshot")
    if browser_run.get("page_title"):
        fields.append("browser_run.page_title")
    if static_run.get("execution_status"):
        fields.append("static_run.execution_status")
    if static_run.get("execution_summary"):
        fields.append("static_run.execution_summary")
    if context.get("static_checks"):
        fields.append("static_checks.check_summary")
        fields.append("static_checks.observed_value")
    return fields


def build_claim_text(context: dict[str, Any]) -> str:
    return build_claim_semantic_bundle(context)


def build_observed_text(context: dict[str, Any]) -> str:
    return build_observed_semantic_bundle(context)


def compute_embedding_similarity(
    text_a: str,
    text_b: str,
    embedding_provider: SentenceEmbeddingProvider | None = None,
) -> float | None:
    normalized_a = normalize_semantic_text(text_a)
    normalized_b = normalize_semantic_text(text_b)
    if not normalized_a or not normalized_b:
        return None
    provider = embedding_provider or LocalSentenceEmbeddingProvider()
    embeddings = provider.encode([normalized_a, normalized_b])
    if len(embeddings) != 2:
        return None
    return round(_cosine_similarity(embeddings[0], embeddings[1]), 4)


def evaluate_semantic_similarity(
    context: dict[str, Any],
    embedding_provider: SentenceEmbeddingProvider | None = None,
) -> SemanticSimilarityResult:
    claim_text = build_claim_text(context)
    observed_text = build_observed_text(context)
    if not claim_text or not observed_text:
        return SemanticSimilarityResult(
            available=False,
            score=None,
            model_name=getattr(embedding_provider, "model_name", _DEFAULT_MODEL),
            method=_METHOD,
            claim_text=claim_text,
            observed_text=observed_text,
            interpretation="unavailable",
            supports_verification=False,
            notes="Claim or observed text was too sparse for local semantic similarity.",
            claim_bundle_source_fields=claim_bundle_source_fields(context),
            observed_bundle_source_fields=observed_bundle_source_fields(context),
        )
    provider = embedding_provider or LocalSentenceEmbeddingProvider()
    try:
        score = compute_embedding_similarity(claim_text, observed_text, provider)
    except Exception as exc:
        return SemanticSimilarityResult(
            available=False,
            score=None,
            model_name=getattr(provider, "model_name", _DEFAULT_MODEL),
            method=_METHOD,
            claim_text=claim_text,
            observed_text=observed_text,
            interpretation="unavailable",
            supports_verification=False,
            notes=f"Local semantic similarity unavailable: {type(exc).__name__}.",
            claim_bundle_source_fields=claim_bundle_source_fields(context),
            observed_bundle_source_fields=observed_bundle_source_fields(context),
        )
    if score is None:
        return SemanticSimilarityResult(
            available=False,
            score=None,
            model_name=getattr(provider, "model_name", _DEFAULT_MODEL),
            method=_METHOD,
            claim_text=claim_text,
            observed_text=observed_text,
            interpretation="unavailable",
            supports_verification=False,
            notes="Local semantic similarity could not produce a score.",
            claim_bundle_source_fields=claim_bundle_source_fields(context),
            observed_bundle_source_fields=observed_bundle_source_fields(context),
        )
    label = semantic_similarity_label(score)
    return SemanticSimilarityResult(
        available=True,
        score=score,
        model_name=getattr(provider, "model_name", _DEFAULT_MODEL),
        method=_METHOD,
        claim_text=claim_text,
        observed_text=observed_text,
        interpretation=label,
        supports_verification=score >= 0.68,
        notes=None,
        claim_bundle_source_fields=claim_bundle_source_fields(context),
        observed_bundle_source_fields=observed_bundle_source_fields(context),
    )


def semantic_similarity_label(score: float | None) -> str:
    if score is None:
        return "unavailable"
    if score >= 0.82:
        return "strong_semantic_match"
    if score >= 0.68:
        return "moderate_semantic_match"
    if score >= 0.50:
        return "weak_semantic_match"
    return "low_semantic_match"


def semantic_similarity_to_snapshot(result: SemanticSimilarityResult | dict[str, Any] | None) -> dict[str, Any]:
    if result is None:
        return {
            "available": False,
            "score": None,
            "label": "unavailable",
            "model": None,
            "method": _METHOD,
        }
    if isinstance(result, dict):
        score = result.get("score")
        return {
            "available": bool(result.get("available")),
            "score": score,
            "label": result.get("interpretation") or semantic_similarity_label(score),
            "model": result.get("model_name") or result.get("model"),
            "method": result.get("method") or _METHOD,
            "notes": result.get("notes"),
            "claim_bundle_preview": result.get("claim_bundle_preview") or _preview(result.get("claim_text")),
            "observed_bundle_preview": result.get("observed_bundle_preview") or _preview(result.get("observed_text")),
            "claim_bundle_source_fields": list(result.get("claim_bundle_source_fields") or []),
            "observed_bundle_source_fields": list(result.get("observed_bundle_source_fields") or []),
        }
    return {
        "available": result.available,
        "score": result.score,
        "label": result.interpretation,
        "model": result.model_name,
        "method": result.method,
        "notes": result.notes,
        "claim_bundle_preview": _preview(result.claim_text),
        "observed_bundle_preview": _preview(result.observed_text),
        "claim_bundle_source_fields": list(result.claim_bundle_source_fields or []),
        "observed_bundle_source_fields": list(result.observed_bundle_source_fields or []),
    }


def _observed_text_parts(context: dict[str, Any]) -> list[Any]:
    static_run = context.get("static_run") or {}
    browser_run = context.get("browser_run") or {}
    parts: list[Any] = [
        browser_run.get("safe_text_snapshot"),
        browser_run.get("execution_summary"),
        browser_run.get("page_title"),
        static_run.get("execution_summary"),
    ]
    for check in context.get("static_checks") or []:
        if check.get("check_status") == "passed":
            parts.extend([check.get("observed_value"), check.get("check_summary")])
    for step in context.get("browser_steps") or []:
        if step.get("step_status") == "passed":
            parts.extend([step.get("observed_result"), step.get("step_summary")])
    return parts


def _summarize_plan_steps(steps: list[Any]) -> str:
    fragments: list[str] = []
    for step in steps[:4]:
        if isinstance(step, dict):
            value = step.get("instruction") or step.get("description") or step.get("step") or step.get("expected_result")
        else:
            value = step
        normalized = normalize_semantic_text(str(value or ""))
        if normalized:
            fragments.append(normalized.rstrip("."))
    if not fragments:
        return ""
    return "; then ".join(fragments)


def _summarize_sample_inputs(sample_inputs: Any) -> str:
    if not sample_inputs:
        return ""
    if isinstance(sample_inputs, dict):
        fragments = [f"{key}: {value}" for key, value in list(sample_inputs.items())[:4] if value not in (None, "", [])]
    elif isinstance(sample_inputs, list):
        fragments = [str(value) for value in sample_inputs[:4] if value not in (None, "", [])]
    else:
        fragments = [str(sample_inputs)]
    return compact_semantic_fragments(fragments, 300)


def _browser_status_sentence(status: str | None) -> str:
    if status == "browser_verified":
        return "VeriBridge successfully completed the browser flow and observed supporting output signals."
    if status == "browser_partially_verified":
        return "VeriBridge completed part of the browser flow and observed some supporting signals."
    if status == "browser_failed":
        return "VeriBridge attempted the browser flow but did not observe the expected result."
    if status == "blocked_by_login":
        return "VeriBridge could not complete the flow because the website required login."
    if status == "needs_human_review":
        return "VeriBridge observed mixed or ambiguous browser execution signals that may need human review."
    if status:
        return f"Browser execution status was {status}."
    return "Browser execution status was unknown."


def _summarize_browser_steps(steps: list[dict[str, Any]]) -> str:
    fragments: list[str] = []
    for step in steps[:6]:
        status = step.get("step_status")
        summary = normalize_semantic_text(str(step.get("step_summary") or step.get("observed_result") or ""))
        if not summary:
            continue
        if status == "passed":
            fragments.append(f"passed step: {summary}")
        elif status:
            fragments.append(f"{status} step: {summary}")
        else:
            fragments.append(summary)
    return compact_semantic_fragments(fragments, 600)


def _summarize_visible_output(browser_run: dict[str, Any]) -> str:
    fragments: list[str] = []
    if browser_run.get("page_title"):
        fragments.append(f"page title '{browser_run.get('page_title')}'")
    if browser_run.get("safe_text_snapshot"):
        fragments.append(f"visible text '{_preview(browser_run.get('safe_text_snapshot'), 350)}'")
    return compact_semantic_fragments(fragments, 500)


def _summarize_static_checks(checks: list[dict[str, Any]]) -> str:
    fragments: list[str] = []
    for check in checks:
        if check.get("check_status") != "passed":
            continue
        summary = normalize_semantic_text(str(check.get("check_summary") or ""))
        observed = normalize_semantic_text(str(check.get("observed_value") or ""))
        if summary and observed:
            fragments.append(f"{summary}: {observed}")
        elif summary or observed:
            fragments.append(summary or observed)
    return compact_semantic_fragments(fragments[:6], 600)


def _cosine_similarity(vector_a: list[float], vector_b: list[float]) -> float:
    try:
        from sklearn.metrics.pairwise import cosine_similarity

        return float(cosine_similarity([vector_a], [vector_b])[0][0])
    except Exception:
        numerator = sum(a * b for a, b in zip(vector_a, vector_b))
        denominator = math.sqrt(sum(a * a for a in vector_a)) * math.sqrt(sum(b * b for b in vector_b))
        if denominator == 0:
            return 0.0
        return numerator / denominator


def _as_float_list(value: Any) -> list[float]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    return [float(item) for item in value]


def _cap_text(text: str) -> str:
    normalized = normalize_semantic_text(text)
    return normalized[:_TEXT_LIMIT]


def _preview(value: Any, limit: int = _PREVIEW_LIMIT) -> str | None:
    if value is None:
        return None
    text = normalize_semantic_text(str(value))
    return text[:limit] if text else None
