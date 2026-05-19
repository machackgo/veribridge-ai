"""Recruiter-friendly GitHub proof report generation service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.schemas.github_recruiter_proof_report import GitHubRecruiterProofReportResponse
from app.services.github_claim_capability_match_service import github_claim_capability_match_to_snapshot
from app.services.github_evidence_service import parse_github_repo_url
from app.services.github_claim_code_semantic_verification_service import (
    GitHubSemanticVerificationResultNotFoundError,
    GitHubSemanticVerificationService,
)
from app.services.skill_evidence_service import SkillEvidenceNotFoundError, SkillEvidenceService
from app.services.website_semantic_similarity_service import normalize_semantic_text

_REPORT_TABLE = "github_recruiter_proof_reports"
_REPORT_VERSION = "github-recruiter-proof-report-v1"
_PREVIEW_LIMIT = 500


class GitHubRecruiterProofReportNotFoundError(LookupError):
    """A recruiter proof report was not found for the scoped evidence row."""


class GitHubRecruiterProofReportNotAllowedError(ValueError):
    """The evidence or semantic result cannot be used to create a recruiter proof report."""


@dataclass(frozen=True)
class GitHubRecruiterProofReportEvaluationResult:
    report_status: str
    confidence_score: float | None
    student_claim: str | None
    headline: str
    recruiter_summary: str
    evidence_summary: str
    limitations: str
    recommended_next_action: str
    confirmed_capabilities: list[dict[str, Any]]
    missing_capabilities: list[dict[str, Any]]
    supporting_line_ranges: list[dict[str, Any]]
    report_snapshot: dict[str, Any]
    report_version: str = _REPORT_VERSION


class GitHubRecruiterProofReportService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def generate_latest_github_recruiter_proof_report(self, user_id: str, evidence_id: str) -> GitHubRecruiterProofReportResponse:
        return self.generate_github_recruiter_proof_report(user_id, evidence_id)

    def generate_github_recruiter_proof_report(
        self,
        user_id: str,
        evidence_id: str,
        semantic_result_id: str | None = None,
    ) -> GitHubRecruiterProofReportResponse:
        context = self.load_github_report_context(user_id, evidence_id, semantic_result_id)
        try:
            evaluation = self.evaluate_report(context)
        except Exception:
            evaluation = GitHubRecruiterProofReportEvaluationResult(
                report_status="report_error",
                confidence_score=0.0,
                student_claim=self.build_student_claim(context),
                headline="GitHub proof report generation encountered an internal issue.",
                recruiter_summary="VeriBridge could not complete the GitHub proof report because of an internal error.",
                evidence_summary="GitHub proof evidence was available, but report synthesis failed safely.",
                limitations=self.build_limitations(context, "report_error"),
                recommended_next_action="Retry report generation after checking service health.",
                confirmed_capabilities=[],
                missing_capabilities=[],
                supporting_line_ranges=[],
                report_snapshot=self._report_snapshot(context, "report_error", 0.0, []),
            )
        return self.persist_github_recruiter_proof_report(user_id, evidence_id, context, evaluation)

    def load_github_report_context(
        self,
        user_id: str,
        evidence_id: str,
        semantic_result_id: str | None = None,
    ) -> dict[str, Any]:
        evidence = SkillEvidenceService(self._client).get_skill_evidence(user_id, evidence_id)
        self._validate_github_evidence(evidence.model_dump())

        semantic_service = GitHubSemanticVerificationService(self._client)
        if semantic_result_id:
            semantic_result = semantic_service.get_result(user_id, evidence_id, semantic_result_id)
        else:
            try:
                semantic_result = semantic_service.get_latest_result(user_id, evidence_id)
            except GitHubSemanticVerificationResultNotFoundError as exc:
                raise GitHubRecruiterProofReportNotAllowedError(
                    "No GitHub semantic verification result exists yet for this evidence record."
                ) from exc

        semantic_snapshot = semantic_result.source_snapshot or {}
        capability_snapshot = semantic_snapshot.get("claim_capability_match") or {}
        segmentation_snapshot = semantic_snapshot.get("segmentation") or {}
        return {
            "evidence": evidence,
            "semantic_result": semantic_result,
            "semantic_snapshot": semantic_snapshot,
            "capability_snapshot": capability_snapshot,
            "segmentation_snapshot": segmentation_snapshot,
            "matched_segments": list(semantic_result.matched_segments or []),
        }

    def evaluate_report(self, context: dict[str, Any]) -> GitHubRecruiterProofReportEvaluationResult:
        semantic_result = context["semantic_result"]
        status = self.build_report_status(context)
        confidence = semantic_result.confidence_score
        student_claim = self.build_student_claim(context)
        headline = self.build_report_headline(context)
        confirmed = self.build_confirmed_capabilities(context)
        missing = self.build_missing_capabilities(context)
        supporting_ranges = self.build_supporting_line_ranges(context)
        recruiter_summary = self.build_recruiter_summary(context)
        evidence_summary = self.build_evidence_summary(context)
        limitations = self.build_limitations(context, status)
        recommended_next_action = self.build_recommended_next_action(context)
        report_snapshot = self._report_snapshot(context, status, confidence or 0.0, supporting_ranges)
        return GitHubRecruiterProofReportEvaluationResult(
            report_status=status,
            confidence_score=confidence,
            student_claim=student_claim,
            headline=headline,
            recruiter_summary=recruiter_summary,
            evidence_summary=evidence_summary,
            limitations=limitations,
            recommended_next_action=recommended_next_action,
            confirmed_capabilities=confirmed,
            missing_capabilities=missing,
            supporting_line_ranges=supporting_ranges,
            report_snapshot=report_snapshot,
            report_version=_REPORT_VERSION,
        )

    def build_report_status(self, context: dict[str, Any]) -> str:
        status = str(context["semantic_result"].semantic_status or "insufficient_evidence")
        return "report_error" if status == "evaluation_error" else status

    def build_report_headline(self, context: dict[str, Any]) -> str:
        status = self.build_report_status(context)
        if status == "verified":
            return "Selected GitHub code supports the student’s claim."
        if status == "partially_verified":
            return "Selected GitHub code supports part of the student’s claim."
        if status == "not_verified":
            return "Selected GitHub code did not clearly support the student’s claim."
        if status == "needs_human_review":
            return "Selected GitHub code may be relevant, but review is recommended."
        if status == "insufficient_evidence":
            return "Not enough GitHub evidence was available for a reliable report."
        return "GitHub proof report generation encountered an internal issue."

    def build_student_claim(self, context: dict[str, Any]) -> str | None:
        evidence = context["evidence"]
        claim = normalize_semantic_text(str(getattr(evidence, "evidence_description", "") or ""))
        if claim:
            return claim
        claim_preview = context["semantic_snapshot"].get("claim_preview")
        if isinstance(claim_preview, str) and claim_preview.strip():
            return claim_preview.strip()
        skill_name = normalize_semantic_text(str(getattr(evidence, "skill_name", "") or ""))
        if skill_name:
            return f"The student claims GitHub proof for {skill_name}."
        return None

    def build_recruiter_summary(self, context: dict[str, Any]) -> str:
        status = self.build_report_status(context)
        confirmed = context.get("capability_snapshot", {}).get("satisfied_requirements") or []
        missing = context.get("capability_snapshot", {}).get("missing_critical_requirements") or []
        if status == "verified":
            if confirmed:
                return (
                    "VeriBridge found that the selected code supports the student's claim. "
                    "The code demonstrates the required capabilities through line-level evidence, including "
                    f"{_join_labels(confirmed[:3])}."
                )
            return "VeriBridge found that the selected code supports the student's claim."
        if status == "partially_verified":
            if missing:
                return (
                    "VeriBridge found evidence for part of the student's claim, but one or more described capabilities "
                    f"were not clearly demonstrated in the selected code: {_join_labels(missing[:3])}."
                )
            return "VeriBridge found evidence for part of the student's claim, but one or more described capabilities were not clearly demonstrated in the selected code."
        if status == "not_verified":
            return "VeriBridge could not confirm the student's claim from the selected GitHub code evidence."
        if status == "needs_human_review":
            return "The selected code contains potentially relevant signals, but the available evidence is not strong enough for a fully automated verification judgment."
        if status == "insufficient_evidence":
            return "Not enough structured GitHub evidence was available to create a reliable proof report."
        return "VeriBridge could not complete GitHub proof report generation because of an internal error."

    def build_evidence_summary(self, context: dict[str, Any]) -> str:
        status = self.build_report_status(context)
        line_ranges = self.build_supporting_line_ranges(context)
        confirmed = self.build_confirmed_capabilities(context)
        parts: list[str] = []
        if status == "verified":
            parts.append("Selected code demonstrates a complete capability chain that supports the claim.")
        elif status == "partially_verified":
            parts.append("Selected code demonstrates part of the claimed capability chain.")
        elif status == "needs_human_review":
            parts.append("Selected code contains relevant signals, but the proof is not fully conclusive.")
        elif status == "not_verified":
            parts.append("Selected code did not demonstrate the claimed capability chain.")
        else:
            parts.append("GitHub evidence was too sparse for a reliable report.")
        if line_ranges:
            fragments = [f"Lines {item['line_start']}-{item['line_end']}: {item['summary']}" for item in line_ranges[:3]]
            parts.append("Supporting evidence includes " + "; ".join(fragments) + ".")
        if confirmed:
            parts.append("Confirmed capabilities: " + _join_labels(confirmed[:3]) + ".")
        return " ".join(parts)

    def build_confirmed_capabilities(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        capability_snapshot = context.get("capability_snapshot") or {}
        satisfied = capability_snapshot.get("satisfied_requirements") or []
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in satisfied:
            key = str(item.get("requirement_key") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            start = item.get("matching_segment_start")
            end = item.get("matching_segment_end")
            result.append(
                {
                    "requirement_key": key,
                    "label": item.get("requirement_label") or key,
                    "supporting_line_range": f"{start}-{end}" if start and end else None,
                }
            )
        return result

    def build_missing_capabilities(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        capability_snapshot = context.get("capability_snapshot") or {}
        missing: list[dict[str, Any]] = []
        seen: set[str] = set()
        for key_name in ("missing_critical_requirements", "missing_supporting_requirements"):
            for item in capability_snapshot.get(key_name) or []:
                key = str(item.get("requirement_key") or "").strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                missing.append(
                    {
                        "requirement_key": key,
                        "label": item.get("requirement_label") or key,
                        "importance": item.get("importance") or "unknown",
                    }
                )
        return missing

    def build_supporting_line_ranges(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        semantic_result = context["semantic_result"]
        capability_snapshot = context.get("capability_snapshot") or {}
        range_map: dict[tuple[int, int], dict[str, Any]] = {}

        for match in semantic_result.matched_segments or []:
            key = (int(match.line_start), int(match.line_end))
            current = range_map.get(key)
            candidate = {
                "line_start": int(match.line_start),
                "line_end": int(match.line_end),
                "segment_type": str(match.segment_type or "generic_logic"),
                "summary": str(match.summary or ""),
                "detected_signals": list(match.detected_signals or []),
                "supports_claim": bool(match.supports_skill or (match.semantic_score or 0.0) >= 0.55),
                "semantic_score": match.semantic_score,
            }
            if current is None:
                range_map[key] = candidate
                continue
            current["detected_signals"] = _dedupe_strings(list(current.get("detected_signals") or []) + list(candidate["detected_signals"] or []))
            if not current.get("summary"):
                current["summary"] = candidate["summary"]
            if current.get("semantic_score") is None or (candidate["semantic_score"] or 0.0) > (current["semantic_score"] or 0.0):
                current["semantic_score"] = candidate["semantic_score"]
            current["supports_claim"] = bool(current.get("supports_claim")) or bool(candidate["supports_claim"])

        for item in capability_snapshot.get("satisfied_requirements") or []:
            start = item.get("matching_segment_start")
            end = item.get("matching_segment_end")
            if not isinstance(start, int) or not isinstance(end, int):
                continue
            summary = str(item.get("matching_segment_summary") or item.get("requirement_label") or "").strip()
            key = (start, end)
            current = range_map.get(key)
            if current is None:
                range_map[key] = {
                    "line_start": start,
                    "line_end": end,
                    "segment_type": str(item.get("matching_segment_type") or item.get("requirement_type") or "generic_logic"),
                    "summary": summary or str(item.get("requirement_label") or item.get("requirement_key") or "Selected GitHub code segment."),
                    "detected_signals": list(item.get("matching_signals") or []),
                    "supports_claim": True,
                    "semantic_score": item.get("semantic_score"),
                }
            else:
                current["detected_signals"] = _dedupe_strings(list(current.get("detected_signals") or []) + list(item.get("matching_signals") or []))
                current["supports_claim"] = True

        ranges = list(range_map.values())
        ranges.sort(key=lambda item: (item["semantic_score"] is None, -(item["semantic_score"] or 0.0), item["line_start"], item["line_end"]))
        return ranges[:5]

    def build_limitations(self, context: dict[str, Any], status: str) -> str:
        limitations = [
            "This report reflects selected GitHub lines and plain-English evidence summaries, not a full runtime audit of the repository.",
            "It does not independently validate hidden tests, production deployment, or correctness beyond the selected evidence.",
        ]
        capability_snapshot = context.get("capability_snapshot") or {}
        if status in {"needs_human_review", "insufficient_evidence"}:
            limitations.append("Sparse, generic, or ambiguous code evidence may require human review.")
        if capability_snapshot.get("missing_critical_requirements"):
            limitations.append("One or more critical capabilities were not demonstrated in the selected line range.")
        return " ".join(limitations)

    def build_recommended_next_action(self, context: dict[str, Any]) -> str:
        status = self.build_report_status(context)
        if status == "verified":
            return "No further action required."
        if status == "partially_verified":
            return "Human review recommended to confirm the missing claim details."
        if status == "needs_human_review":
            return "Human review recommended because the code signals are mixed or generic."
        if status == "insufficient_evidence":
            return "Provide a more complete GitHub file or a clearer selected line range."
        if status == "not_verified":
            return "Provide stronger GitHub proof evidence before treating the claim as verified."
        return "Retry report generation after checking service health."

    def persist_github_recruiter_proof_report(
        self,
        user_id: str,
        evidence_id: str,
        context: dict[str, Any],
        evaluation: GitHubRecruiterProofReportEvaluationResult,
    ) -> GitHubRecruiterProofReportResponse:
        semantic_result = context["semantic_result"]
        data = {
            "evidence_id": evidence_id,
            "github_semantic_result_id": semantic_result.id,
            "user_id": user_id,
            "report_status": evaluation.report_status,
            "confidence_score": evaluation.confidence_score,
            "report_version": evaluation.report_version,
            "student_claim": evaluation.student_claim,
            "headline": evaluation.headline,
            "recruiter_summary": evaluation.recruiter_summary,
            "evidence_summary": evaluation.evidence_summary,
            "limitations": evaluation.limitations,
            "recommended_next_action": evaluation.recommended_next_action,
            "confirmed_capabilities": evaluation.confirmed_capabilities,
            "missing_capabilities": evaluation.missing_capabilities,
            "supporting_line_ranges": evaluation.supporting_line_ranges,
            "report_snapshot": evaluation.report_snapshot,
        }

        if isinstance(self._client, dict):
            now = _now()
            row = {"id": str(uuid4()), "created_at": now, "updated_at": now, **data}
            self._client.setdefault(_REPORT_TABLE, {})[row["id"]] = row
            return _to_response(row)

        result = self._client.table(_REPORT_TABLE).insert(data).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError("GitHub recruiter proof report insert returned no data.")
        return _to_response(rows[0])

    def get_latest_report(self, user_id: str, evidence_id: str) -> GitHubRecruiterProofReportResponse:
        self._get_evidence_row(user_id, evidence_id)
        results = self.list_reports(user_id, evidence_id)
        if not results:
            raise GitHubRecruiterProofReportNotFoundError(evidence_id)
        return results[0]

    def list_reports(self, user_id: str, evidence_id: str) -> list[GitHubRecruiterProofReportResponse]:
        self._get_evidence_row(user_id, evidence_id)
        if isinstance(self._client, dict):
            rows = [
                row
                for row in self._client.setdefault(_REPORT_TABLE, {}).values()
                if row.get("user_id") == user_id and row.get("evidence_id") == evidence_id
            ]
            rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
            return [_to_response(row) for row in rows]

        result = (
            self._client.table(_REPORT_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("evidence_id", evidence_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [_to_response(row) for row in (getattr(result, "data", []) or [])]

    def get_report(self, user_id: str, evidence_id: str, report_id: str) -> GitHubRecruiterProofReportResponse:
        self._get_evidence_row(user_id, evidence_id)
        if isinstance(self._client, dict):
            row = self._client.setdefault(_REPORT_TABLE, {}).get(report_id)
            if not row or row.get("user_id") != user_id or row.get("evidence_id") != evidence_id:
                raise GitHubRecruiterProofReportNotFoundError(report_id)
            return _to_response(row)

        result = (
            self._client.table(_REPORT_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("evidence_id", evidence_id)
            .eq("id", report_id)
            .maybe_single()
            .execute()
        )
        if result is None or not result.data:
            raise GitHubRecruiterProofReportNotFoundError(report_id)
        return _to_response(result.data)

    def _get_evidence_row(self, user_id: str, evidence_id: str) -> Any:
        if isinstance(self._client, dict):
            row = self._client.setdefault("skill_evidence", {}).get(evidence_id)
            if not row or row.get("user_id") != user_id:
                raise SkillEvidenceNotFoundError(evidence_id)
            return row
        result = (
            self._client.table("skill_evidence")
            .select("*")
            .eq("user_id", user_id)
            .eq("id", evidence_id)
            .maybe_single()
            .execute()
        )
        if result is None or not result.data:
            raise SkillEvidenceNotFoundError(evidence_id)
        return result.data

    def _validate_github_evidence(self, evidence: dict[str, Any]) -> None:
        repository_url = str(evidence.get("repository_url") or evidence.get("evidence_url") or "").strip()
        file_path = str(evidence.get("file_path") or "").strip()
        if parse_github_repo_url(repository_url) is None or not file_path:
            raise GitHubRecruiterProofReportNotAllowedError(
                "GitHub recruiter proof reports require a public GitHub repository URL and selected file path."
            )

    def _report_snapshot(
        self,
        context: dict[str, Any],
        status: str,
        confidence: float,
        supporting_line_ranges: list[dict[str, Any]],
    ) -> dict[str, Any]:
        semantic_result = context["semantic_result"]
        semantic_snapshot = context.get("semantic_snapshot") or {}
        capability_snapshot = semantic_snapshot.get("claim_capability_match") or {}
        return {
            "semantic_status": status,
            "confidence_score": confidence,
            "semantic_result_id": semantic_result.id,
            "source_matched_segments": [
                {
                    "line_start": item.get("line_start"),
                    "line_end": item.get("line_end"),
                    "segment_type": item.get("segment_type"),
                    "summary": _preview(item.get("summary")),
                    "semantic_score": item.get("semantic_score"),
                }
                for item in supporting_line_ranges[:5]
            ],
            "capability_match_status": capability_snapshot.get("capability_match_status"),
            "supports_full_verification": capability_snapshot.get("supports_full_verification"),
            "blocks_full_verification": capability_snapshot.get("blocks_full_verification"),
        }


def generate_latest_github_recruiter_proof_report(user_id: str, evidence_id: str, client: Any) -> GitHubRecruiterProofReportResponse:
    return GitHubRecruiterProofReportService(client).generate_latest_github_recruiter_proof_report(user_id, evidence_id)


def generate_github_recruiter_proof_report(
    user_id: str,
    evidence_id: str,
    client: Any,
    semantic_result_id: str | None = None,
) -> GitHubRecruiterProofReportResponse:
    return GitHubRecruiterProofReportService(client).generate_github_recruiter_proof_report(user_id, evidence_id, semantic_result_id)


def _to_response(row: dict[str, Any]) -> GitHubRecruiterProofReportResponse:
    return GitHubRecruiterProofReportResponse(
        id=str(row["id"]),
        evidence_id=str(row["evidence_id"]),
        github_semantic_result_id=str(row["github_semantic_result_id"]),
        user_id=str(row["user_id"]),
        report_status=row.get("report_status") or "report_error",
        confidence_score=row.get("confidence_score"),
        report_version=row.get("report_version") or _REPORT_VERSION,
        student_claim=row.get("student_claim"),
        headline=row.get("headline"),
        recruiter_summary=row.get("recruiter_summary"),
        evidence_summary=row.get("evidence_summary"),
        limitations=row.get("limitations"),
        recommended_next_action=row.get("recommended_next_action"),
        confirmed_capabilities=list(row.get("confirmed_capabilities") or []),
        missing_capabilities=list(row.get("missing_capabilities") or []),
        supporting_line_ranges=list(row.get("supporting_line_ranges") or []),
        report_snapshot=row.get("report_snapshot") or {},
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


def _join_labels(items: list[dict[str, Any]]) -> str:
    labels = [str(item.get("label") or item.get("requirement_label") or item.get("requirement_key") or "").strip() for item in items]
    labels = [label for label in labels if label]
    if not labels:
        return "selected GitHub evidence"
    return ", ".join(labels[:3]).lower()


def _preview(value: Any, limit: int = _PREVIEW_LIMIT) -> str | None:
    if value is None:
        return None
    text = normalize_semantic_text(str(value))
    return text[:limit] if text else None


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value).strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def _now() -> str:
    return datetime.now(UTC).isoformat()
