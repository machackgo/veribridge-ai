"""GitHub claim capability extraction and line-level capability matching."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.services.github_code_evidence_segmentation_service import GitHubCodeEvidenceSegment, GitHubCodeEvidenceSegmentationResult
from app.services.website_semantic_similarity_service import normalize_semantic_text


@dataclass(frozen=True)
class GitHubClaimRequirement:
    requirement_key: str
    requirement_label: str
    source_phrase: str
    requirement_type: str
    importance: str


@dataclass(frozen=True)
class GitHubClaimCapabilityMatchResult:
    available: bool
    extracted_requirements: list[GitHubClaimRequirement]
    satisfied_requirements: list[dict[str, Any]]
    missing_critical_requirements: list[dict[str, Any]]
    missing_supporting_requirements: list[dict[str, Any]]
    capability_match_status: str
    supports_full_verification: bool
    blocks_full_verification: bool
    notes: str | None = None


class GitHubClaimCapabilityMatchService:
    def evaluate_github_claim_capability_match(self, context: dict[str, Any]) -> GitHubClaimCapabilityMatchResult:
        claim_text = build_claim_text(context)
        segmentation = context.get("segmentation")
        if not normalize_semantic_text(claim_text):
            return GitHubClaimCapabilityMatchResult(
                available=False,
                extracted_requirements=[],
                satisfied_requirements=[],
                missing_critical_requirements=[],
                missing_supporting_requirements=[],
                capability_match_status="unavailable",
                supports_full_verification=False,
                blocks_full_verification=True,
                notes="No meaningful claim text was available for capability extraction.",
            )
        if not segmentation or not getattr(segmentation, "available", False):
            return GitHubClaimCapabilityMatchResult(
                available=False,
                extracted_requirements=[],
                satisfied_requirements=[],
                missing_critical_requirements=[],
                missing_supporting_requirements=[],
                capability_match_status="unavailable",
                supports_full_verification=False,
                blocks_full_verification=True,
                notes="GitHub code segmentation was unavailable.",
            )

        requirements = extract_claim_requirements(context)
        if not requirements:
            return GitHubClaimCapabilityMatchResult(
                available=False,
                extracted_requirements=[],
                satisfied_requirements=[],
                missing_critical_requirements=[],
                missing_supporting_requirements=[],
                capability_match_status="unavailable",
                supports_full_verification=False,
                blocks_full_verification=True,
                notes="The claim was too generic to extract specific capabilities safely.",
            )

        satisfied: list[dict[str, Any]] = []
        missing_critical: list[dict[str, Any]] = []
        missing_supporting: list[dict[str, Any]] = []

        segments = list(getattr(segmentation, "segments", []) or [])
        for requirement in requirements:
            match = _best_segment_match(requirement, segments)
            if match is not None:
                satisfied.append(
                    {
                        "requirement_key": requirement.requirement_key,
                        "requirement_label": requirement.requirement_label,
                        "requirement_type": requirement.requirement_type,
                        "importance": requirement.importance,
                        "source_phrase": requirement.source_phrase,
                        "matching_segment_start": match.line_start,
                        "matching_segment_end": match.line_end,
                        "matching_segment_type": match.segment_type,
                        "matching_segment_summary": match.summary,
                        "matching_signals": list(match.detected_signals),
                    }
                )
            elif requirement.importance == "critical":
                missing_critical.append(
                    {
                        "requirement_key": requirement.requirement_key,
                        "requirement_label": requirement.requirement_label,
                        "requirement_type": requirement.requirement_type,
                        "importance": requirement.importance,
                        "source_phrase": requirement.source_phrase,
                    }
                )
            else:
                missing_supporting.append(
                    {
                        "requirement_key": requirement.requirement_key,
                        "requirement_label": requirement.requirement_label,
                        "requirement_type": requirement.requirement_type,
                        "importance": requirement.importance,
                        "source_phrase": requirement.source_phrase,
                    }
                )

        if not satisfied:
            status = "capability_mismatch"
        elif missing_critical:
            status = "partial_capability_match"
        elif missing_supporting:
            status = "weak_capability_match"
        else:
            status = "strong_capability_match"

        supports_full = status == "strong_capability_match"
        blocks_full = status in {"weak_capability_match", "capability_mismatch"}
        if missing_critical:
            blocks_full = True
        notes = _build_notes(status, satisfied, missing_critical, missing_supporting)
        return GitHubClaimCapabilityMatchResult(
            available=True,
            extracted_requirements=requirements,
            satisfied_requirements=satisfied,
            missing_critical_requirements=missing_critical,
            missing_supporting_requirements=missing_supporting,
            capability_match_status=status,
            supports_full_verification=supports_full,
            blocks_full_verification=blocks_full,
            notes=notes,
        )


def evaluate_github_claim_capability_match(context: dict[str, Any]) -> GitHubClaimCapabilityMatchResult:
    return GitHubClaimCapabilityMatchService().evaluate_github_claim_capability_match(context)


def build_claim_text(context: dict[str, Any]) -> str:
    evidence = context.get("evidence") or {}
    pieces = [
        str(evidence.get("skill_name") or ""),
        str(evidence.get("evidence_description") or ""),
        str(context.get("claim_text") or ""),
    ]
    return normalize_semantic_text(" ".join(piece for piece in pieces if piece))


def extract_claim_requirements(context: dict[str, Any]) -> list[GitHubClaimRequirement]:
    claim_text = build_claim_text(context)
    skill_name = normalize_semantic_text(str((context.get("evidence") or {}).get("skill_name") or ""))
    text = claim_text.lower()

    requirements: list[GitHubClaimRequirement] = []
    add = requirements.append

    if _contains_any(text, ("trained", "training", "fit a model", "fit(", "built a classifier", "built a model", "model training", "classifier", "regressor", "machine learning model")):
        add(_req("model_training", "Model training", _phrase(text, ("trained", "training", "fit a model", "fit(", "built a classifier", "built a model", "model training", "classifier", "regressor")), "model_training", "critical"))

    if _contains_any(text, ("evaluated", "evaluation", "accuracy", "f1", "precision", "recall", "confusion matrix", "classification report", "roc auc", "roc_auc")):
        add(_req("model_evaluation", "Model evaluation", _phrase(text, ("evaluated", "evaluation", "accuracy", "f1", "precision", "recall", "confusion matrix", "classification report", "roc auc", "roc_auc")), "model_evaluation", "critical"))

    if _contains_any(text, ("predicted", "predict ", "predict(", "predicts", "inference", "generated predictions")):
        add(_req("prediction_inference", "Prediction inference", _phrase(text, ("predicted", "predict ", "predict(", "predicts", "inference", "generated predictions")), "prediction_inference", "critical"))

    if _contains_any(text, ("preprocessed", "preprocessing", "cleaned data", "scaled", "encoded", "feature engineering", "normalized", "data preparation", "data cleaning")):
        add(_req("data_preprocessing", "Data preprocessing", _phrase(text, ("preprocessed", "preprocessing", "cleaned data", "scaled", "encoded", "feature engineering", "normalized", "data preparation", "data cleaning")), "data_preprocessing", "supporting"))

    if _contains_any(text, ("api", "endpoint", "rest api", "fastapi", "flask", "route", "routes", "router")):
        add(_req("api_endpoint", "API endpoint", _phrase(text, ("fastapi", "flask", "endpoint", "rest api", "api", "route", "router")), "api_endpoint", "critical"))

    if _contains_any(text, ("database", "database write", "stored", "save", "saved", "insert", "upsert", "update", "persist", "records", "submissions")):
        add(_req("database_write", "Database write", _phrase(text, ("database", "stored", "save", "saved", "insert", "upsert", "update", "persist", "records", "submissions")), "database_write", "critical"))

    if _contains_any(text, ("authentication", "authenticate", "login", "jwt", "token", "session", "protected", "oauth", "bcrypt")):
        add(_req("authentication", "Authentication", _phrase(text, ("authentication", "authenticate", "login", "jwt", "token", "session", "protected", "oauth", "bcrypt")), "authentication", "critical"))

    if _contains_any(text, ("visualization", "visualization", "chart", "dashboard", "plot", "graph", "figure", "tableau", "matplotlib", "seaborn")):
        add(_req("visualization", "Visualization", _phrase(text, ("visualization", "chart", "dashboard", "plot", "graph", "figure", "tableau", "matplotlib", "seaborn")), "visualization", "supporting"))

    if _contains_any(skill_name.lower(), ("deploy", "deployment", "devops", "ci/cd", "docker", "kubernetes", "vercel", "render", "cloud")) or _contains_any(text, ("deployment", "deployed", "docker", "kubernetes", "vercel", "render", "aws", "gcp", "azure", "ci/cd")):
        add(_req("deployment_logic", "Deployment logic", _phrase(text, ("deployment", "deployed", "docker", "kubernetes", "vercel", "render", "aws", "gcp", "azure", "ci/cd")), "deployment_logic", "supporting"))

    return _dedupe_requirements(requirements)


def github_claim_capability_match_to_snapshot(result: GitHubClaimCapabilityMatchResult | dict[str, Any] | None) -> dict[str, Any]:
    if result is None:
        return {
            "available": False,
            "capability_match_status": "unavailable",
            "supports_full_verification": False,
            "blocks_full_verification": True,
            "extracted_requirements": [],
            "satisfied_requirements": [],
            "missing_critical_requirements": [],
            "missing_supporting_requirements": [],
            "notes": None,
        }
    if isinstance(result, dict):
        return {
            "available": bool(result.get("available")),
            "capability_match_status": result.get("capability_match_status") or "unavailable",
            "supports_full_verification": bool(result.get("supports_full_verification")),
            "blocks_full_verification": bool(result.get("blocks_full_verification")),
            "extracted_requirements": _requirement_snapshot_list(result.get("extracted_requirements") or []),
            "satisfied_requirements": _satisfied_snapshot_list(result.get("satisfied_requirements") or []),
            "missing_critical_requirements": _simple_requirement_snapshot_list(result.get("missing_critical_requirements") or []),
            "missing_supporting_requirements": _simple_requirement_snapshot_list(result.get("missing_supporting_requirements") or []),
            "notes": result.get("notes"),
        }
    return {
        "available": result.available,
        "capability_match_status": result.capability_match_status,
        "supports_full_verification": result.supports_full_verification,
        "blocks_full_verification": result.blocks_full_verification,
        "extracted_requirements": [
            {
                "requirement_key": requirement.requirement_key,
                "requirement_label": requirement.requirement_label,
                "requirement_type": requirement.requirement_type,
                "importance": requirement.importance,
            }
            for requirement in result.extracted_requirements
        ],
        "satisfied_requirements": result.satisfied_requirements,
        "missing_critical_requirements": result.missing_critical_requirements,
        "missing_supporting_requirements": result.missing_supporting_requirements,
        "notes": result.notes,
    }


def _best_segment_match(requirement: GitHubClaimRequirement, segments: list[GitHubCodeEvidenceSegment]) -> GitHubCodeEvidenceSegment | None:
    scored: list[tuple[int, GitHubCodeEvidenceSegment]] = []
    for segment in segments:
        score = _segment_requirement_score(requirement.requirement_type, segment)
        if score > 0:
            scored.append((score, segment))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1].line_end - item[1].line_start), reverse=True)
    return scored[0][1]


def _segment_requirement_score(requirement_type: str, segment: GitHubCodeEvidenceSegment) -> int:
    text = normalize_semantic_text(f"{segment.segment_type} {segment.summary} {' '.join(segment.detected_signals)}").lower()
    signals = {signal.lower() for signal in segment.detected_signals}
    segment_type = segment.segment_type

    if requirement_type == "model_training":
        if segment_type == "model_training" or _contains_any(text, ("fit(", "train(", "classifier", "regressor", "epochs", "optimizer.step", "backward(")):
            return 3
        return 0
    if requirement_type == "model_evaluation":
        if segment_type == "evaluation_metrics" or _contains_any(text, ("accuracy_score", "f1_score", "precision_score", "recall_score", "confusion_matrix", "classification_report", "roc_auc_score", "roc_auc")):
            return 3
        return 0
    if requirement_type == "prediction_inference":
        if segment_type == "prediction_inference" or _contains_any(text, ("predict(", "predict_proba(", "infer(", "y_pred", "y_predicted")):
            return 3
        return 0
    if requirement_type == "data_preprocessing":
        if segment_type == "data_preprocessing" or _contains_any(text, ("standardscaler", "minmaxscaler", "labelencoder", "onehotencoder", "dropna", "fillna", "preprocess", "normalize(", "astype(")):
            return 3
        if "train_test_split" in signals:
            return 1
        return 0
    if requirement_type == "api_endpoint":
        if segment_type == "api_endpoint" or _contains_any(text, ("fastapi", "flask", "@app.get", "@app.post", "@router.get", "@router.post", "route(", "router = apirouter")):
            return 3
        return 0
    if requirement_type == "database_write":
        if segment_type == "database_logic" or _contains_any(text, ("insert(", "update(", "upsert(", "commit(", "save(", "write(", "session", "supabase")):
            return 3
        return 0
    if requirement_type == "authentication":
        if segment_type == "authentication_logic" or _contains_any(text, ("login", "auth", "jwt", "token", "session", "bcrypt", "oauth", "protected")):
            return 3
        return 0
    if requirement_type == "visualization":
        if segment_type == "visualization" or _contains_any(text, ("matplotlib", "seaborn", "plt.", "plot(", "chart", "graph", "dashboard")):
            return 3
        return 0
    if requirement_type == "deployment_logic":
        if _contains_any(text, ("docker", "kubernetes", "deploy", "vercel", "render", "aws", "gcp", "azure", "ci/cd")):
            return 3
        return 0
    if requirement_type == "generic_capability":
        return 1 if segment.supports_skill else 0
    return 0


def _req(requirement_key: str, requirement_label: str, source_phrase: str, requirement_type: str, importance: str) -> GitHubClaimRequirement:
    return GitHubClaimRequirement(
        requirement_key=requirement_key,
        requirement_label=requirement_label,
        source_phrase=source_phrase,
        requirement_type=requirement_type,
        importance=importance,
    )


def _phrase(text: str, phrases: tuple[str, ...]) -> str:
    for phrase in phrases:
        if phrase in text:
            return phrase
    return phrases[0] if phrases else ""


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _dedupe_requirements(requirements: list[GitHubClaimRequirement]) -> list[GitHubClaimRequirement]:
    deduped: list[GitHubClaimRequirement] = []
    seen: set[str] = set()
    for requirement in requirements:
        if requirement.requirement_key in seen:
            continue
        seen.add(requirement.requirement_key)
        deduped.append(requirement)
    return deduped


def _requirement_snapshot_list(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "requirement_key": item.get("requirement_key"),
            "requirement_label": item.get("requirement_label"),
            "requirement_type": item.get("requirement_type"),
            "importance": item.get("importance"),
        }
        for item in requirements
    ]


def _simple_requirement_snapshot_list(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "requirement_key": item.get("requirement_key"),
            "requirement_label": item.get("requirement_label"),
            "requirement_type": item.get("requirement_type"),
            "importance": item.get("importance"),
        }
        for item in requirements
    ]


def _satisfied_snapshot_list(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "requirement_key": item.get("requirement_key"),
            "requirement_label": item.get("requirement_label"),
            "requirement_type": item.get("requirement_type"),
            "importance": item.get("importance"),
            "matching_segment_start": item.get("matching_segment_start"),
            "matching_segment_end": item.get("matching_segment_end"),
            "matching_segment_type": item.get("matching_segment_type"),
            "matching_segment_summary": item.get("matching_segment_summary"),
            "matching_signals": list(item.get("matching_signals") or []),
        }
        for item in requirements
    ]


def _build_notes(
    status: str,
    satisfied: list[dict[str, Any]],
    missing_critical: list[dict[str, Any]],
    missing_supporting: list[dict[str, Any]],
) -> str | None:
    parts: list[str] = []
    if satisfied:
        parts.append(f"Satisfied {len(satisfied)} extracted capability requirement(s).")
    if missing_critical:
        parts.append("Missing critical requirements: " + ", ".join(item["requirement_label"] for item in missing_critical[:4]) + ".")
    if missing_supporting:
        parts.append("Missing supporting requirements: " + ", ".join(item["requirement_label"] for item in missing_supporting[:4]) + ".")
    parts.append(f"Capability match status: {status}.")
    return " ".join(parts) if parts else None
