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


def build_claim_text(context: dict[str, Any]) -> str:
    evidence = context.get("evidence") or {}
    plan = context.get("plan") or {}
    parts = [
        evidence.get("evidence_description"),
        plan.get("feature_to_verify"),
        plan.get("expected_output"),
    ]
    return _cap_text(" ".join(part for part in (normalize_semantic_text(str(value or "")) for value in parts) if part))


def build_observed_text(context: dict[str, Any]) -> str:
    return _cap_text(" ".join(extract_candidate_semantic_texts(context)))


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
        }
    return {
        "available": result.available,
        "score": result.score,
        "label": result.interpretation,
        "model": result.model_name,
        "method": result.method,
        "notes": result.notes,
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
