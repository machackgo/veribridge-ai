"""Product-facing proof verification status reconciliation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ProofDisplayStatus = Literal[
    "verified",
    "supported_with_review",
    "partially_supported",
    "not_verified",
    "pending_analysis",
]

ConfidenceBand = Literal["high", "medium", "low"]
DisplayAudience = Literal["student", "recruiter"]

_POSITIVE_STATUSES = {"verified", "strong_match", "strong_semantic_match", "browser_verified", "ready"}
_REVIEW_STATUSES = {"needs_human_review", "needs_more_detail", "partially_verified", "browser_partially_verified", "partial_verification", "weak_match", "moderate_semantic_match"}
_NEGATIVE_STATUSES = {"not_verified", "skill_usage_not_found", "rejected", "browser_failed", "execution_error", "execution_timeout", "unsupported", "unsupported_plan", "blocked_by_login", "evaluation_error"}


@dataclass(frozen=True)
class ProofVerificationStatusReconciliationResult:
    available: bool
    display_status: ProofDisplayStatus
    confidence_band: ConfidenceBand
    short_display_label: str
    student_facing_message: str
    recruiter_facing_message: str
    review_recommended: bool
    notes: str | None = None
    technical_statuses: dict[str, str | None] | None = None

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "display_status": self.display_status,
            "confidence_band": self.confidence_band,
            "short_display_label": self.short_display_label,
            "student_facing_message": self.student_facing_message,
            "recruiter_facing_message": self.recruiter_facing_message,
            "review_recommended": self.review_recommended,
            "notes": self.notes,
            "technical_statuses": self.technical_statuses or {},
        }


def _clean_status(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return str(value).strip() or None


def reconcile_proof_verification_status(context: dict[str, Any]) -> ProofVerificationStatusReconciliationResult:
    technical_statuses = {
        "base_evidence_status": _clean_status(context.get("base_evidence_status")),
        "semantic_status": _clean_status(context.get("semantic_status")),
        "report_status": _clean_status(context.get("report_status")),
        "browser_status": _clean_status(context.get("browser_status")),
        "static_status": _clean_status(context.get("static_status")),
        "capability_match_status": _clean_status(context.get("capability_match_status")),
        "expected_output_match_status": _clean_status(context.get("expected_output_match_status")),
    }

    available = bool(context.get("available", True))
    if not available:
        return _result(
            "pending_analysis",
            "low",
            "Pending analysis",
            "Proof analysis is still pending.",
            "Proof analysis is still pending or unavailable.",
            review_recommended=True,
            notes="The proof pipeline has not produced enough structured evidence yet.",
            technical_statuses=technical_statuses,
        )

    if _has_explicit_negative(context, technical_statuses):
        return _result(
            "not_verified",
            "low",
            "Not verified",
            "The selected evidence does not currently support the student's claim.",
            "The selected evidence does not currently support the student's claim.",
            review_recommended=False,
            notes="A contradiction, critical missing capability, or blocking verification failure was detected.",
            technical_statuses=technical_statuses,
        )

    support_level = _support_level(context, technical_statuses)
    if support_level == "strong":
        return _result(
            "verified",
            "high",
            "Verified",
            "The proof is strongly supported by the automated evidence.",
            "The proof is strongly supported by the automated evidence.",
            review_recommended=False,
            notes="The semantic and capability signals align without a material warning.",
            technical_statuses=technical_statuses,
        )

    if support_level == "review":
        return _result(
            "supported_with_review",
            "medium",
            "Supported with review",
            "Relevant evidence was found, but some claim details still benefit from review.",
            "Relevant evidence was found, but some claim details still benefit from review.",
            review_recommended=True,
            notes="The evidence is materially supportive, but one or more verifier layers remained cautious.",
            technical_statuses=technical_statuses,
        )

    if support_level == "partial":
        return _result(
            "partially_supported",
            "medium",
            "Partially supported",
            "Only part of the claim is supported by the current evidence.",
            "Only part of the claim is supported by the current evidence.",
            review_recommended=True,
            notes="Some capabilities or outputs were confirmed, but the full claim was not.",
            technical_statuses=technical_statuses,
        )

    return _result(
        "pending_analysis",
        "low",
        "Pending analysis",
        "Proof analysis is still in progress.",
        "Proof analysis is still in progress.",
        review_recommended=True,
        notes="The available signals are sparse or incomplete.",
        technical_statuses=technical_statuses,
    )


def proof_verification_reconciliation_snapshot(context: dict[str, Any]) -> dict[str, Any]:
    return reconcile_proof_verification_status(context).to_snapshot()


def proof_verification_display_label(
    display_status: ProofDisplayStatus,
    audience: DisplayAudience = "student",
) -> str:
    if audience == "recruiter":
        return {
            "verified": "Verified",
            "supported_with_review": "Supported with review",
            "partially_supported": "Partially supported",
            "not_verified": "Not verified",
            "pending_analysis": "Pending analysis",
        }[display_status]
    return {
        "verified": "Evidence accepted",
        "supported_with_review": "Supported with review",
        "partially_supported": "Partially supported",
        "not_verified": "Not verified",
        "pending_analysis": "Pending analysis",
    }[display_status]


def _result(
    display_status: ProofDisplayStatus,
    confidence_band: ConfidenceBand,
    short_display_label: str,
    student_facing_message: str,
    recruiter_facing_message: str,
    *,
    review_recommended: bool,
    notes: str | None,
    technical_statuses: dict[str, str | None],
) -> ProofVerificationStatusReconciliationResult:
    return ProofVerificationStatusReconciliationResult(
        available=True,
        display_status=display_status,
        confidence_band=confidence_band,
        short_display_label=short_display_label,
        student_facing_message=student_facing_message,
        recruiter_facing_message=recruiter_facing_message,
        review_recommended=review_recommended,
        notes=notes,
        technical_statuses=technical_statuses,
    )


def _support_level(context: dict[str, Any], technical_statuses: dict[str, str | None]) -> str:
    semantic_status = technical_statuses["semantic_status"]
    report_status = technical_statuses["report_status"]
    browser_status = technical_statuses["browser_status"]
    static_status = technical_statuses["static_status"]
    capability_match_status = technical_statuses["capability_match_status"]
    expected_output_match_status = technical_statuses["expected_output_match_status"]

    if semantic_status in {"verified"} or report_status in {"verified"}:
        if capability_match_status in {None, "", "strong_capability_match", "partial_capability_match"} and expected_output_match_status not in {"low_expected_output_match", "weak_expected_output_match"}:
            if semantic_status == "verified" and report_status == "verified":
                return "strong"
            if any(status in _REVIEW_STATUSES for status in (browser_status, static_status)):
                return "review"
            return "strong"

    if semantic_status in {"partially_verified"} or report_status in {"partially_verified"}:
        return "partial"

    if semantic_status in {"needs_human_review"} or report_status in {"needs_human_review"}:
        if _has_supporting_evidence(context, technical_statuses):
            return "review"
        return "partial"

    if browser_status in {"browser_partially_verified"} or static_status in {"partial_verification"}:
        if _has_supporting_evidence(context, technical_statuses):
            return "partial"

    if any(status in _POSITIVE_STATUSES for status in technical_statuses.values() if status):
        return "review"

    if _has_supporting_evidence(context, technical_statuses):
        return "partial"

    return "pending"


def _has_supporting_evidence(context: dict[str, Any], technical_statuses: dict[str, str | None]) -> bool:
    has_semantic = technical_statuses["semantic_status"] in {"verified", "partially_verified", "needs_human_review"}
    has_report = technical_statuses["report_status"] in {"verified", "partially_verified", "needs_human_review"}
    has_browser = technical_statuses["browser_status"] in {"browser_verified", "browser_partially_verified"}
    has_static = technical_statuses["static_status"] in {"static_verified", "partial_verification"}
    has_base = technical_statuses["base_evidence_status"] == "verified"
    has_capability = technical_statuses["capability_match_status"] in {"strong_capability_match", "partial_capability_match"}
    has_expected = technical_statuses["expected_output_match_status"] in {"strong_expected_output_match", "moderate_expected_output_match", "weak_expected_output_match"}
    return any([has_semantic, has_report, has_browser, has_static, has_base, has_capability, has_expected, bool(context.get("supporting_line_ranges"))])


def _has_explicit_negative(context: dict[str, Any], technical_statuses: dict[str, str | None]) -> bool:
    capability_status = technical_statuses["capability_match_status"]
    expected_status = technical_statuses["expected_output_match_status"]
    if capability_status in {"capability_mismatch"}:
        return True
    if context.get("missing_critical_requirements"):
        return True
    if bool(context.get("blocks_full_verification")):
        return True
    if expected_status in {"low_expected_output_match"}:
        return True
    if expected_status == "weak_expected_output_match" and bool(context.get("expected_output_blocks_verification")):
        return True
    if technical_statuses["semantic_status"] in {"not_verified", "evaluation_error"}:
        return True
    if technical_statuses["report_status"] in {"not_verified", "report_error"}:
        return True
    if technical_statuses["browser_status"] in {"browser_failed", "execution_error", "execution_timeout", "blocked_by_login"}:
        return True
    if technical_statuses["static_status"] in {"failed_static_checks", "execution_error"}:
        return True
    if capability_status == "weak_capability_match" and not _has_supporting_evidence(context, technical_statuses):
        return True
    return False
