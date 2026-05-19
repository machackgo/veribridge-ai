"""GitHub claim-to-code semantic verification service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any
from uuid import uuid4

from app.services.github_code_evidence_segmentation_service import (
    GitHubCodeEvidenceSegment,
    GitHubCodeEvidenceSegmentationResult,
    github_code_evidence_segmentation_to_snapshot,
)
from app.schemas.github_semantic_verification_result import GitHubSemanticVerificationResultResponse
from app.services.github_claim_capability_match_service import (
    GitHubClaimCapabilityMatchResult,
    evaluate_github_claim_capability_match,
    github_claim_capability_match_to_snapshot,
)
from app.services.github_code_evidence_segmentation_service import (
    github_code_evidence_segment_to_snapshot,
    segment_github_code_evidence,
)
from app.services.github_evidence_service import (
    GitHubFileFetchResult,
    extract_line_range,
    fetch_public_github_file,
    parse_github_repo_url,
)
from app.services.skill_evidence_service import SkillEvidenceNotFoundError
from app.services.website_semantic_similarity_service import (
    SentenceEmbeddingProvider,
    compute_embedding_similarity,
    normalize_semantic_text,
    semantic_similarity_label,
)

_RESULT_TABLE = "github_semantic_verification_results"
_EVIDENCE_TABLE = "skill_evidence"
_EVALUATOR_VERSION = "github-claim-code-semantic-v1"
_EVALUATOR_PROVIDER = "local_deterministic_embedding"
_PREVIEW_LIMIT = 500


class GitHubSemanticVerificationResultNotFoundError(LookupError):
    """No GitHub semantic verification result exists for the scoped evidence row."""


class GitHubSemanticVerificationNotAllowedError(ValueError):
    """GitHub evidence is not compatible with claim-to-code semantic verification."""


@dataclass(frozen=True)
class GitHubClaimCodeSegmentMatch:
    line_start: int
    line_end: int
    segment_type: str
    summary: str
    detected_signals: list[str]
    semantic_score: float | None
    semantic_label: str
    supports_skill: bool
    confidence_hint: str


@dataclass(frozen=True)
class GitHubClaimCodeSemanticEvaluationResult:
    semantic_status: str
    confidence_score: float
    recruiter_facing_summary: str
    evidence_summary: str
    limitations: str
    recommended_next_action: str
    internal_reasoning_summary: str
    strongest_matching_segment_start: int | None
    strongest_matching_segment_end: int | None
    strongest_matching_segment_summary: str | None
    matched_segments: list[GitHubClaimCodeSegmentMatch]
    evaluator_provider: str = _EVALUATOR_PROVIDER
    evaluator_version: str = _EVALUATOR_VERSION


class GitHubSemanticVerificationService:
    def __init__(self, client: Any, embedding_provider: SentenceEmbeddingProvider | None = None) -> None:
        self._client = client
        self._embedding_provider = embedding_provider
        self._similarity_fallback_used = False

    def evaluate_latest_github_semantic_verification(self, user_id: str, evidence_id: str) -> GitHubSemanticVerificationResultResponse:
        return self.evaluate_github_semantic_verification(user_id, evidence_id)

    def evaluate_github_semantic_verification(self, user_id: str, evidence_id: str) -> GitHubSemanticVerificationResultResponse:
        context = self.load_github_semantic_evaluation_context(user_id, evidence_id)
        try:
            evaluation = self.evaluate_semantically(context)
        except Exception:
            evaluation = GitHubClaimCodeSemanticEvaluationResult(
                semantic_status="evaluation_error",
                confidence_score=0.0,
                recruiter_facing_summary="VeriBridge could not complete GitHub semantic evaluation because of an internal error.",
                evidence_summary=self.build_github_evidence_summary(context, [], None),
                limitations=self.build_github_limitations(context, "evaluation_error"),
                recommended_next_action="Retry semantic evaluation after checking service health.",
                internal_reasoning_summary="GitHub semantic evaluator raised an internal runtime error.",
                strongest_matching_segment_start=None,
                strongest_matching_segment_end=None,
                strongest_matching_segment_summary=None,
                matched_segments=[],
            )
        return self.persist_github_semantic_verification_result(user_id, evidence_id, context, evaluation)

    def load_github_semantic_evaluation_context(self, user_id: str, evidence_id: str) -> dict[str, Any]:
        self._similarity_fallback_used = False
        evidence = self._get_evidence_row(user_id, evidence_id)
        self._validate_github_evidence(evidence)
        claim_text = self.build_github_claim_text({"evidence": evidence})

        repository_url = str(evidence.get("repository_url") or evidence.get("evidence_url") or "").strip()
        file_path = str(evidence.get("file_path") or "").strip()
        if not repository_url or parse_github_repo_url(repository_url) is None or not file_path:
            raise GitHubSemanticVerificationNotAllowedError(
                "GitHub semantic verification requires a public repository URL and a selected file path."
            )

        fetch_result = fetch_public_github_file(repository_url, file_path)
        if not fetch_result.ok or not fetch_result.content:
            return {
                "available": False,
                "evidence": evidence,
                "claim_text": claim_text,
                "repository_url": repository_url,
                "file_path": file_path,
                "fetch_result": fetch_result,
                "line_range": None,
                "segmentation": GitHubCodeEvidenceSegmentationResult(
                    available=False,
                    skill_name=str(evidence.get("skill_name") or ""),
                    total_segments=0,
                    segments=[],
                    overall_summary="",
                    notes="GitHub file content could not be fetched.",
                ),
            }

        line_range = extract_line_range(fetch_result.content, evidence.get("line_start"), evidence.get("line_end"))
        if not line_range.ok:
            return {
                "available": False,
                "evidence": evidence,
                "claim_text": claim_text,
                "repository_url": repository_url,
                "file_path": file_path,
                "fetch_result": fetch_result,
                "line_range": line_range,
                "segmentation": GitHubCodeEvidenceSegmentationResult(
                    available=False,
                    skill_name=str(evidence.get("skill_name") or ""),
                    total_segments=0,
                    segments=[],
                    overall_summary="",
                    notes=line_range.error,
                ),
            }

        segmentation = segment_github_code_evidence(
            line_range.content,
            line_range.line_start,
            str(evidence.get("skill_name") or ""),
            str(evidence.get("evidence_description") or ""),
        )
        return {
            "available": True,
            "evidence": evidence,
            "claim_text": claim_text,
            "repository_url": repository_url,
            "file_path": file_path,
            "fetch_result": fetch_result,
            "line_range": line_range,
            "segmentation": segmentation,
        }

    def build_github_claim_text(self, context: dict[str, Any]) -> str:
        evidence = context.get("evidence") or {}
        skill_name = normalize_semantic_text(str(evidence.get("skill_name") or ""))
        description = normalize_semantic_text(str(evidence.get("evidence_description") or ""))
        title = ""
        metadata = evidence.get("metadata") or {}
        if isinstance(metadata, dict):
            title = normalize_semantic_text(str(metadata.get("title") or metadata.get("name") or ""))
        fragments: list[str] = []
        if description:
            fragments.append(description)
        if title and title.lower() not in description.lower():
            fragments.append(title)
        if skill_name:
            fragments.append(f"Skill: {skill_name}.")
        claim = normalize_semantic_text(" ".join(fragments))
        return claim or f"The student claims GitHub code proof for {skill_name or 'the selected skill'}."

    def build_code_segment_match_inputs(self, context: dict[str, Any]) -> list[str]:
        segmentation = context.get("segmentation")
        if not segmentation or not segmentation.available:
            return []
        formatted: list[str] = []
        for segment in segmentation.segments:
            formatted.append(self._format_segment_for_matching(segment))
        return formatted

    def evaluate_claim_capability_match(self, context: dict[str, Any]) -> GitHubClaimCapabilityMatchResult:
        return evaluate_github_claim_capability_match(context)

    def evaluate_claim_against_segments(self, context: dict[str, Any]) -> list[GitHubClaimCodeSegmentMatch]:
        claim_text = context.get("claim_text") or ""
        matches: list[GitHubClaimCodeSegmentMatch] = []
        segmentation = context.get("segmentation")
        if not segmentation or not segmentation.available:
            return matches
        for segment in segmentation.segments:
            segment_text = self._format_segment_for_matching(segment)
            score = self._score_text_pair(claim_text, segment_text)
            matches.append(
                GitHubClaimCodeSegmentMatch(
                    line_start=segment.line_start,
                    line_end=segment.line_end,
                    segment_type=segment.segment_type,
                    summary=segment.summary,
                    detected_signals=list(segment.detected_signals),
                    semantic_score=score,
                    semantic_label=semantic_similarity_label(score),
                    supports_skill=segment.supports_skill,
                    confidence_hint=segment.confidence_hint,
                )
            )
        return sorted(matches, key=lambda item: (item.semantic_score or 0.0, item.supports_skill), reverse=True)

    def evaluate_claim_against_overall_code_summary(self, context: dict[str, Any]) -> dict[str, Any]:
        claim_text = context.get("claim_text") or ""
        segmentation = context.get("segmentation")
        if not segmentation or not segmentation.available:
            return {"available": False, "score": None, "label": "unavailable"}
        overall_text = self._build_overall_code_text(segmentation)
        score = self._score_text_pair(claim_text, overall_text)
        return {
            "available": score is not None,
            "score": score,
            "label": semantic_similarity_label(score),
            "overall_text": overall_text,
        }

    def determine_github_semantic_status(
        self,
        context: dict[str, Any],
        overall_match: dict[str, Any],
        segment_matches: list[GitHubClaimCodeSegmentMatch],
        capability_match: GitHubClaimCapabilityMatchResult | None = None,
    ) -> str:
        if not context.get("available"):
            return "insufficient_evidence"
        claim_text = context.get("claim_text") or ""
        if not normalize_semantic_text(claim_text):
            return "insufficient_evidence"
        if not segment_matches:
            return "insufficient_evidence"

        supportive = [match for match in segment_matches if self._is_supportive_match(match)]
        strongest = self._strongest_match(segment_matches)
        overall_score = overall_match.get("score")
        strongest_score = strongest.semantic_score if strongest else None
        generic = self._is_generic_evidence(segment_matches)
        total_support = len(supportive)
        capability_status = capability_match.capability_match_status if capability_match else "unavailable"
        capability_missing_critical = bool(capability_match and capability_match.missing_critical_requirements)
        capability_supports_full = bool(capability_match and capability_match.supports_full_verification)
        capability_blocks_full = bool(capability_match and capability_match.blocks_full_verification)

        if capability_status == "unavailable" and total_support == 0 and (overall_score or 0.0) < 0.55:
            return "not_verified"
        if capability_status == "capability_mismatch":
            if total_support and (overall_score or 0.0) >= 0.55:
                return "needs_human_review"
            return "not_verified"
        if capability_missing_critical:
            if total_support and any(match.supports_skill for match in segment_matches):
                return "partially_verified"
            if generic or (overall_score or 0.0) >= 0.55 or (strongest_score or 0.0) >= 0.55:
                return "needs_human_review"
            return "not_verified"
        if capability_status == "weak_capability_match" or capability_blocks_full:
            if total_support >= 2 and strongest_score is not None and strongest_score >= 0.68:
                return "partially_verified"
            if total_support >= 1 and strongest_score is not None and strongest_score >= 0.55:
                return "needs_human_review"
            return "not_verified"

        if overall_score is not None and strongest_score is not None:
            if (
                overall_score >= 0.82
                and strongest_score >= 0.82
                and total_support >= 2
                and not generic
                and capability_supports_full
            ):
                return "verified"
            if (
                overall_score >= 0.68
                and strongest_score >= 0.68
                and total_support >= 1
                and not generic
            ):
                return "partially_verified"
        if total_support >= 2 and strongest_score is not None and strongest_score >= 0.68:
            return "partially_verified"
        if total_support >= 1 and strongest_score is not None and strongest_score >= 0.55:
            return "partially_verified"
        if generic:
            return "needs_human_review"
        if (overall_score or 0.0) < 0.50 and not total_support:
            return "not_verified"
        if strongest_score is not None and strongest_score >= 0.55:
            return "needs_human_review"
        return "not_verified"

    def calculate_github_semantic_confidence(
        self,
        context: dict[str, Any],
        overall_match: dict[str, Any],
        segment_matches: list[GitHubClaimCodeSegmentMatch],
        capability_match: GitHubClaimCapabilityMatchResult | None = None,
        status: str | None = None,
    ) -> float:
        status = status or self.determine_github_semantic_status(context, overall_match, segment_matches, capability_match)
        overall_score = overall_match.get("score") or 0.0
        strongest = self._strongest_match(segment_matches)
        strongest_score = strongest.semantic_score if strongest else 0.0
        support_count = len([match for match in segment_matches if self._is_supportive_match(match)])
        generic = self._is_generic_evidence(segment_matches)
        capability_status = capability_match.capability_match_status if capability_match else "unavailable"
        capability_missing_critical = bool(capability_match and capability_match.missing_critical_requirements)
        capability_supports_full = bool(capability_match and capability_match.supports_full_verification)

        if status == "verified":
            score = 0.88
            score += min(support_count, 4) * 0.02
            score += max(0.0, overall_score - 0.7) * 0.1
            score += max(0.0, strongest_score - 0.75) * 0.08
            if capability_supports_full:
                score += 0.03
            return _clamp(score, 0.85, 0.98)
        if status == "partially_verified":
            score = 0.60 + min(support_count, 3) * 0.05
            score += max(0.0, overall_score - 0.55) * 0.15
            score += max(0.0, strongest_score - 0.55) * 0.08
            if capability_status == "partial_capability_match":
                score += 0.03
            return _clamp(score, 0.55, 0.84)
        if status == "needs_human_review":
            score = 0.42
            score += max(0.0, overall_score - 0.40) * 0.08
            score += min(support_count, 2) * 0.04
            if generic:
                score -= 0.03
            if capability_missing_critical:
                score -= 0.02
            return _clamp(score, 0.35, 0.70)
        if status == "not_verified":
            score = 0.76
            if overall_score < 0.30 and strongest_score < 0.30:
                score += 0.1
            if capability_status in {"capability_mismatch", "weak_capability_match"}:
                score += 0.02
            return _clamp(score, 0.70, 0.95)
        if status == "insufficient_evidence":
            return _clamp(0.20 + min(support_count, 2) * 0.05, 0.10, 0.40)
        return 0.0

    def build_github_recruiter_summary(
        self,
        context: dict[str, Any],
        status: str,
        segment_matches: list[GitHubClaimCodeSegmentMatch],
        capability_match: GitHubClaimCapabilityMatchResult | None = None,
    ) -> str:
        strongest = self._strongest_match(segment_matches)
        missing_critical = [item.get("requirement_label") for item in (capability_match.missing_critical_requirements if capability_match else [])]
        satisfied = [item.get("requirement_label") for item in (capability_match.satisfied_requirements if capability_match else [])]
        if status == "verified":
            capability_text = ""
            if satisfied:
                capability_text = " It includes " + ", ".join(satisfied[:3]).lower() + "."
            if strongest:
                return (
                    "VeriBridge found that the selected GitHub code supports the student's claim. "
                    f"The strongest evidence appears in lines {strongest.line_start}-{strongest.line_end}, "
                    f"where the code {strongest.summary.lower()}."
                    f"{capability_text}"
                )
            return "VeriBridge found that the selected GitHub code supports the student's claim." + capability_text
        if status == "partially_verified":
            if missing_critical:
                return (
                    "VeriBridge found code evidence for part of the student's claim, but the selected lines did not "
                    f"clearly demonstrate the required capability: {', '.join(missing_critical[:3]).lower()}."
                )
            return (
                "VeriBridge found code evidence that supports part of the student's claim, but some described "
                "functionality was not clearly demonstrated in the selected lines."
            )
        if status == "not_verified":
            if missing_critical:
                return (
                    "VeriBridge could not confirm the student's claim because the selected code did not include "
                    f"the required capabilities described: {', '.join(missing_critical[:3]).lower()}."
                )
            return "VeriBridge could not confirm the student's claim from the selected GitHub code evidence."
        if status == "needs_human_review":
            if missing_critical:
                return (
                    "The selected code is related to the student's claim, but one or more required capabilities were "
                    f"not clearly demonstrated in the provided line range: {', '.join(missing_critical[:3]).lower()}."
                )
            return "The selected code contains potentially relevant signals, but the available evidence is not strong enough for an automated verification judgment."
        if status == "insufficient_evidence":
            return "Not enough structured GitHub evidence was available to perform a reliable semantic verification."
        return "VeriBridge could not complete semantic evaluation because of an internal error."

    def build_github_evidence_summary(
        self,
        context: dict[str, Any],
        segment_matches: list[GitHubClaimCodeSegmentMatch],
        overall_match: dict[str, Any] | None,
        capability_match: GitHubClaimCapabilityMatchResult | None = None,
    ) -> str:
        segmentation = context.get("segmentation")
        claim = context.get("claim_text") or ""
        parts: list[str] = []
        if claim:
            parts.append(f"Claim: {claim}")
        if segmentation and segmentation.available and segmentation.overall_summary:
            parts.append(f"Overall code summary: {segmentation.overall_summary}")
        if capability_match is not None:
            parts.append(f"Capability match: {capability_match.capability_match_status}.")
            if capability_match.satisfied_requirements:
                summary = ", ".join(item.get("requirement_label") or item.get("requirement_key") for item in capability_match.satisfied_requirements[:3])
                parts.append(f"Satisfied capabilities: {summary}.")
            if capability_match.missing_critical_requirements:
                summary = ", ".join(item.get("requirement_label") or item.get("requirement_key") for item in capability_match.missing_critical_requirements[:3])
                parts.append(f"Missing critical capabilities: {summary}.")
        if overall_match and overall_match.get("score") is not None:
            parts.append(
                "Claim to overall summary similarity was {label} ({score:.2f}).".format(
                    label=overall_match.get("label") or "unavailable",
                    score=float(overall_match["score"]),
                )
            )
        if segment_matches:
            top = segment_matches[:3]
            fragments = []
            for match in top:
                fragments.append(f"Lines {match.line_start}-{match.line_end}: {match.summary}")
            parts.append("Matched segments: " + " ".join(fragments))
        if not parts:
            return "No structured GitHub evidence was available."
        return " ".join(parts)

    def build_github_limitations(
        self,
        context: dict[str, Any],
        status: str,
        capability_match: GitHubClaimCapabilityMatchResult | None = None,
    ) -> str:
        limitations = [
            "This evaluation compares the student's claim against plain-English summaries of selected GitHub code, not against a live execution trace.",
            "It does not independently validate runtime behavior, hidden tests, or broader repository correctness.",
        ]
        if status in {"needs_human_review", "insufficient_evidence"}:
            limitations.append("Sparse, generic, or ambiguous code evidence may require human review.")
        if capability_match and capability_match.missing_critical_requirements:
            limitations.append("One or more critical claimed capabilities were not demonstrated in the selected line range.")
        if not context.get("available"):
            limitations.append("The selected code could not be fetched or segmented reliably.")
        return " ".join(limitations)

    def build_github_recommended_next_action(
        self,
        context: dict[str, Any],
        status: str,
        capability_match: GitHubClaimCapabilityMatchResult | None = None,
    ) -> str:
        if status == "verified":
            return "No further action required."
        if status == "partially_verified":
            return "Human review recommended to confirm the remaining claim details."
        if status == "needs_human_review":
            return "Human review recommended because the code signals are mixed or generic."
        if status == "insufficient_evidence":
            return "Provide a more complete public GitHub file or a clearer selected line range."
        return "Review the code evidence before treating the claim as verified."

    def evaluate_semantically(self, context: dict[str, Any]) -> GitHubClaimCodeSemanticEvaluationResult:
        if not context.get("available"):
            return GitHubClaimCodeSemanticEvaluationResult(
                semantic_status="insufficient_evidence",
                confidence_score=0.18,
                recruiter_facing_summary=self.build_github_recruiter_summary(context, "insufficient_evidence", []),
                evidence_summary=self.build_github_evidence_summary(context, [], None),
                limitations=self.build_github_limitations(context, "insufficient_evidence"),
                recommended_next_action=self.build_github_recommended_next_action(context, "insufficient_evidence"),
                internal_reasoning_summary="Selected GitHub evidence was too sparse or unavailable for semantic matching.",
                strongest_matching_segment_start=None,
                strongest_matching_segment_end=None,
                strongest_matching_segment_summary=None,
                matched_segments=[],
            )

        overall_match = self.evaluate_claim_against_overall_code_summary(context)
        segment_matches = self.evaluate_claim_against_segments(context)
        capability_match = self.evaluate_claim_capability_match(context)
        status = self.determine_github_semantic_status(context, overall_match, segment_matches, capability_match)
        confidence = self.calculate_github_semantic_confidence(context, overall_match, segment_matches, capability_match, status)
        strongest = self._strongest_match(segment_matches)

        reasoning = self._build_internal_reasoning_summary(context, status, overall_match, segment_matches, capability_match)
        return GitHubClaimCodeSemanticEvaluationResult(
            semantic_status=status,
            confidence_score=confidence,
            recruiter_facing_summary=self.build_github_recruiter_summary(context, status, segment_matches, capability_match),
            evidence_summary=self.build_github_evidence_summary(context, segment_matches, overall_match, capability_match),
            limitations=self.build_github_limitations(context, status, capability_match),
            recommended_next_action=self.build_github_recommended_next_action(context, status, capability_match),
            internal_reasoning_summary=reasoning,
            strongest_matching_segment_start=strongest.line_start if strongest else None,
            strongest_matching_segment_end=strongest.line_end if strongest else None,
            strongest_matching_segment_summary=strongest.summary if strongest else None,
            matched_segments=segment_matches,
        )

    def persist_github_semantic_verification_result(
        self,
        user_id: str,
        evidence_id: str,
        context: dict[str, Any],
        evaluation: GitHubClaimCodeSemanticEvaluationResult,
    ) -> GitHubSemanticVerificationResultResponse:
        snapshot = self._source_snapshot(context, evaluation)
        data = {
            "evidence_id": evidence_id,
            "user_id": user_id,
            "semantic_status": evaluation.semantic_status,
            "confidence_score": evaluation.confidence_score,
            "evaluator_version": evaluation.evaluator_version,
            "evaluator_provider": evaluation.evaluator_provider,
            "recruiter_facing_summary": evaluation.recruiter_facing_summary,
            "evidence_summary": evaluation.evidence_summary,
            "limitations": evaluation.limitations,
            "recommended_next_action": evaluation.recommended_next_action,
            "strongest_matching_segment_start": evaluation.strongest_matching_segment_start,
            "strongest_matching_segment_end": evaluation.strongest_matching_segment_end,
            "strongest_matching_segment_summary": evaluation.strongest_matching_segment_summary,
            "source_snapshot": snapshot,
        }

        if isinstance(self._client, dict):
            now = _now()
            row = {"id": str(uuid4()), "created_at": now, "updated_at": now, **data}
            self._client.setdefault(_RESULT_TABLE, {})[row["id"]] = row
            return _to_response(row)

        result = self._client.table(_RESULT_TABLE).insert(data).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError("GitHub semantic verification result insert returned no data.")
        return _to_response(rows[0])

    def get_latest_result(self, user_id: str, evidence_id: str) -> GitHubSemanticVerificationResultResponse:
        self._get_evidence_row(user_id, evidence_id)
        results = self.list_results(user_id, evidence_id)
        if not results:
            raise GitHubSemanticVerificationResultNotFoundError(evidence_id)
        return results[0]

    def list_results(self, user_id: str, evidence_id: str) -> list[GitHubSemanticVerificationResultResponse]:
        self._get_evidence_row(user_id, evidence_id)
        if isinstance(self._client, dict):
            rows = [
                row
                for row in self._client.setdefault(_RESULT_TABLE, {}).values()
                if row.get("user_id") == user_id and row.get("evidence_id") == evidence_id
            ]
            rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
            return [_to_response(row) for row in rows]

        result = (
            self._client.table(_RESULT_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("evidence_id", evidence_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [_to_response(row) for row in (getattr(result, "data", []) or [])]

    def get_result(self, user_id: str, evidence_id: str, result_id: str) -> GitHubSemanticVerificationResultResponse:
        self._get_evidence_row(user_id, evidence_id)
        if isinstance(self._client, dict):
            row = self._client.setdefault(_RESULT_TABLE, {}).get(result_id)
            if not row or row.get("user_id") != user_id or row.get("evidence_id") != evidence_id:
                raise GitHubSemanticVerificationResultNotFoundError(result_id)
            return _to_response(row)

        result = (
            self._client.table(_RESULT_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("evidence_id", evidence_id)
            .eq("id", result_id)
            .maybe_single()
            .execute()
        )
        if result is None or not result.data:
            raise GitHubSemanticVerificationResultNotFoundError(result_id)
        return _to_response(result.data)

    def _source_snapshot(self, context: dict[str, Any], evaluation: GitHubClaimCodeSemanticEvaluationResult) -> dict[str, Any]:
        segmentation = context.get("segmentation")
        overall_match = self.evaluate_claim_against_overall_code_summary(context)
        capability_match = self.evaluate_claim_capability_match(context)
        matched_segments = evaluation.matched_segments[:3]
        return {
            "claim_preview": _preview(context.get("claim_text")),
            "overall_code_summary_preview": _preview((segmentation.overall_summary if segmentation else "")),
            "overall_code_summary_score": overall_match.get("score"),
            "overall_code_summary_label": overall_match.get("label"),
            "claim_capability_match": github_claim_capability_match_to_snapshot(capability_match),
            "matched_segments": [
                {
                    "line_start": segment.line_start,
                    "line_end": segment.line_end,
                    "segment_type": segment.segment_type,
                    "summary": segment.summary,
                    "detected_signals": list(segment.detected_signals),
                    "semantic_score": segment.semantic_score,
                    "semantic_label": segment.semantic_label,
                    "supports_skill": segment.supports_skill,
                    "confidence_hint": segment.confidence_hint,
                }
                for segment in matched_segments
            ],
            "all_segment_types": [segment.segment_type for segment in (segmentation.segments if segmentation else [])],
            "semantic_model": getattr(self._embedding_provider, "model_name", "local-fallback"),
            "semantic_method": "sentence_transformers_cosine_similarity",
            "fallback_used": self._similarity_fallback_used or self._embedding_provider is None,
            "segmentation": github_code_evidence_segmentation_to_snapshot(segmentation),
        }

    def _get_evidence_row(self, user_id: str, evidence_id: str) -> dict[str, Any]:
        if isinstance(self._client, dict):
            row = self._client.setdefault(_EVIDENCE_TABLE, {}).get(evidence_id)
            if not row or row.get("user_id") != user_id:
                raise SkillEvidenceNotFoundError(evidence_id)
            return row

        result = self._client.table(_EVIDENCE_TABLE).select("*").eq("user_id", user_id).eq("id", evidence_id).maybe_single().execute()
        if result is None or not result.data:
            raise SkillEvidenceNotFoundError(evidence_id)
        return result.data

    def _validate_github_evidence(self, evidence: dict[str, Any]) -> None:
        repository_url = str(evidence.get("repository_url") or evidence.get("evidence_url") or "").strip()
        file_path = str(evidence.get("file_path") or "").strip()
        if parse_github_repo_url(repository_url) is None or not file_path:
            raise GitHubSemanticVerificationNotAllowedError(
                "GitHub semantic verification requires a public GitHub repository URL and selected file path."
            )

    def _build_overall_code_text(self, segmentation: GitHubCodeEvidenceSegmentationResult) -> str:
        fragments = [f"Overall code summary: {segmentation.overall_summary}"]
        top_segments = segmentation.segments[:5]
        for segment in top_segments:
            fragments.append(self._format_segment_for_matching(segment))
        return normalize_semantic_text(" ".join(fragment for fragment in fragments if fragment))

    def _format_segment_for_matching(self, segment: GitHubCodeEvidenceSegment) -> str:
        signals = ", ".join(segment.detected_signals[:6]) if segment.detected_signals else "none"
        return (
            f"Lines {segment.line_start}-{segment.line_end}: {segment.summary} "
            f"Segment type: {segment.segment_type}. Detected signals: {signals}."
        )

    def _score_text_pair(self, text_a: str, text_b: str) -> float | None:
        try:
            score = compute_embedding_similarity(text_a, text_b, self._embedding_provider)
        except Exception:
            self._similarity_fallback_used = True
            score = None
        if score is not None:
            return score
        self._similarity_fallback_used = True
        return self._token_overlap_score(text_a, text_b)

    def _token_overlap_score(self, text_a: str, text_b: str) -> float | None:
        tokens_a = set(_meaningful_tokens(text_a))
        tokens_b = set(_meaningful_tokens(text_b))
        if not tokens_a or not tokens_b:
            return None
        overlap = len(tokens_a & tokens_b)
        return round((2 * overlap) / (len(tokens_a) + len(tokens_b)), 4)

    def _is_supportive_match(self, match: GitHubClaimCodeSegmentMatch) -> bool:
        if match.semantic_score is None:
            return False
        if match.semantic_score >= 0.68:
            return True
        return match.supports_skill and match.semantic_score >= 0.55

    def _strongest_match(self, matches: list[GitHubClaimCodeSegmentMatch]) -> GitHubClaimCodeSegmentMatch | None:
        if not matches:
            return None
        return max(matches, key=lambda match: (match.semantic_score or 0.0, match.supports_skill, -match.line_start))

    def _is_generic_evidence(self, matches: list[GitHubClaimCodeSegmentMatch]) -> bool:
        if not matches:
            return True
        generic_types = {"generic_logic", "unknown"}
        if all(match.segment_type in generic_types for match in matches):
            return True
        if all((match.semantic_score or 0.0) < 0.55 for match in matches):
            return True
        return False

    def _build_internal_reasoning_summary(
        self,
        context: dict[str, Any],
        status: str,
        overall_match: dict[str, Any],
        segment_matches: list[GitHubClaimCodeSegmentMatch],
        capability_match: GitHubClaimCapabilityMatchResult | None = None,
    ) -> str:
        strongest = self._strongest_match(segment_matches)
        pieces = []
        if overall_match.get("score") is not None:
            pieces.append(f"Overall code summary similarity was {overall_match.get('label')} ({float(overall_match['score']):.2f}).")
        if strongest and strongest.semantic_score is not None:
            pieces.append(
                f"Strongest segment match was lines {strongest.line_start}-{strongest.line_end} with {strongest.semantic_label} ({strongest.semantic_score:.2f})."
            )
        if capability_match is not None:
            pieces.append(f"Capability match status was {capability_match.capability_match_status}.")
            if capability_match.missing_critical_requirements:
                missing = ", ".join(item.get("requirement_label") or item.get("requirement_key") for item in capability_match.missing_critical_requirements[:3])
                pieces.append(f"Missing critical requirements: {missing}.")
        if segment_matches:
            supportive_count = len([match for match in segment_matches if self._is_supportive_match(match)])
            pieces.append(f"{supportive_count} segments provided meaningful support.")
        pieces.append(f"Final semantic status: {status}.")
        return " ".join(pieces)


def _to_response(row: dict[str, Any]) -> GitHubSemanticVerificationResultResponse:
    snapshot = row.get("source_snapshot") or {}
    matched_segments = [_matched_segment_to_response(segment) for segment in snapshot.get("matched_segments") or []]
    return GitHubSemanticVerificationResultResponse(
        id=str(row["id"]),
        evidence_id=str(row["evidence_id"]),
        user_id=str(row["user_id"]),
        semantic_status=row.get("semantic_status") or "insufficient_evidence",
        confidence_score=row.get("confidence_score"),
        evaluator_version=row.get("evaluator_version") or _EVALUATOR_VERSION,
        evaluator_provider=row.get("evaluator_provider") or _EVALUATOR_PROVIDER,
        recruiter_facing_summary=row.get("recruiter_facing_summary"),
        evidence_summary=row.get("evidence_summary"),
        limitations=row.get("limitations"),
        recommended_next_action=row.get("recommended_next_action"),
        strongest_matching_segment_start=row.get("strongest_matching_segment_start"),
        strongest_matching_segment_end=row.get("strongest_matching_segment_end"),
        strongest_matching_segment_summary=row.get("strongest_matching_segment_summary"),
        matched_segments=matched_segments,
        source_snapshot=snapshot,
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


def _matched_segment_to_response(segment: dict[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(segment, dict):
        segment = getattr(segment, "__dict__", {}) or {}
    score = segment.get("semantic_score")
    return {
        "line_start": int(segment.get("line_start") or 1),
        "line_end": int(segment.get("line_end") or segment.get("line_start") or 1),
        "segment_type": str(segment.get("segment_type") or "generic_logic"),
        "summary": str(segment.get("summary") or segment.get("code_excerpt") or "Selected GitHub code segment."),
        "detected_signals": list(segment.get("detected_signals") or []),
        "semantic_score": score,
        "semantic_label": str(segment.get("semantic_label") or semantic_similarity_label(score)),
        "supports_skill": bool(segment.get("supports_skill", False)),
        "confidence_hint": str(segment.get("confidence_hint") or "low"),
    }


def _preview(value: Any, limit: int = _PREVIEW_LIMIT) -> str | None:
    if value is None:
        return None
    text = normalize_semantic_text(str(value))
    return text[:limit] if text else None


def _meaningful_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+(?:[-'][a-z0-9]+)?", normalize_semantic_text(value).lower())
    seen: list[str] = []
    for token in tokens:
        if len(token) < 3 or token in {"the", "and", "for", "with", "from", "that", "this", "code", "line", "lines"}:
            continue
        if token not in seen:
            seen.append(token)
    return seen


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return round(max(minimum, min(maximum, value)), 4)


def _now() -> str:
    return datetime.now(UTC).isoformat()
