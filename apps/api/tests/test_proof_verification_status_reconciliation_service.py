from __future__ import annotations

from app.services.proof_verification_status_reconciliation_service import (
    proof_verification_display_label,
    proof_verification_reconciliation_snapshot,
    reconcile_proof_verification_status,
)


def test_verified_strong_support_maps_to_verified_display_status() -> None:
    result = reconcile_proof_verification_status(
        {
            "available": True,
            "base_evidence_status": "verified",
            "semantic_status": "verified",
            "report_status": "verified",
            "capability_match_status": "strong_capability_match",
            "expected_output_match_status": "strong_expected_output_match",
        }
    )

    assert result.display_status == "verified"
    assert result.confidence_band == "high"
    assert result.review_recommended is False
    assert proof_verification_display_label(result.display_status, "student") == "Evidence accepted"


def test_supported_with_review_is_used_for_materially_supportive_but_cautious_cases() -> None:
    result = reconcile_proof_verification_status(
        {
            "available": True,
            "base_evidence_status": "verified",
            "semantic_status": "needs_human_review",
            "report_status": "needs_human_review",
            "browser_status": "browser_partially_verified",
            "expected_output_match_status": "moderate_expected_output_match",
            "supportingEvidence": True,
        }
    )

    assert result.display_status == "supported_with_review"
    assert result.confidence_band == "medium"
    assert result.review_recommended is True


def test_partially_supported_for_partial_capability_coverage() -> None:
    result = reconcile_proof_verification_status(
        {
            "available": True,
            "base_evidence_status": "verified",
            "semantic_status": "partially_verified",
            "report_status": "partially_verified",
            "capability_match_status": "partial_capability_match",
            "supportingEvidence": True,
        }
    )

    assert result.display_status == "partially_supported"
    assert result.confidence_band == "medium"
    assert result.review_recommended is True


def test_not_verified_blocks_when_critical_capability_missing() -> None:
    result = reconcile_proof_verification_status(
        {
            "available": True,
            "base_evidence_status": "verified",
            "semantic_status": "partially_verified",
            "capability_match_status": "capability_mismatch",
            "missingCriticalRequirements": True,
            "blocksFullVerification": True,
            "supportingEvidence": True,
        }
    )

    assert result.display_status == "not_verified"
    assert result.confidence_band == "low"
    assert result.review_recommended is False
    assert proof_verification_display_label(result.display_status, "recruiter") == "Not verified"


def test_pending_analysis_when_no_result_is_available() -> None:
    result = reconcile_proof_verification_status({"available": False})

    assert result.display_status == "pending_analysis"
    assert result.confidence_band == "low"
    assert result.review_recommended is True


def test_snapshot_round_trip_includes_reconciled_fields() -> None:
    snapshot = proof_verification_reconciliation_snapshot(
        {
            "available": True,
            "base_evidence_status": "verified",
            "semantic_status": "needs_human_review",
            "report_status": "needs_human_review",
            "supportingEvidence": True,
        }
    )

    assert snapshot["display_status"] == "supported_with_review"
    assert snapshot["short_display_label"] == "Supported with review"
    assert snapshot["technical_statuses"]["semantic_status"] == "needs_human_review"
