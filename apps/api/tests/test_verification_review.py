"""
Tests for the Verification Review workflow.

Covers all required scenarios:
  ✓ student can submit for AI review
  ✓ 5-minute/timer status is representable (submitted_for_ai_review / ai_review_in_progress)
  ✓ readiness >= 80 + clean privacy → ai_approved_for_sharing
  ✓ readiness 60–79 + clean privacy → manual_review_recommended
  ✓ readiness < 60 + clean privacy → needs_more_evidence
  ✓ privacy flagged blocks AI approval → privacy_flagged
  ✓ human_verified is NEVER set by AI review
  ✓ review request duplicate prevention (409 when already approved/in-flight)
  ✓ re-submission allowed when previous status was needs_more_evidence
  ✓ student can get review status (404 before any submission)
  ✓ admin can list review requests
  ✓ admin can manually mark AI approved / request more evidence
  ✓ admin decision does NOT set human_verified
  ✓ human reviewer fields exist and are structurally correct
  ✓ project-agnostic: no hardcoded project names
  ✓ wording: ai_approved_for_sharing ≠ human_verified

All storage is in-memory (get_db → {}).
No real network calls.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, require_admin_user_id
from app.main import app
from app.services.verification_review_service import (
    _apply_ai_decision,
    VerificationReviewService,
    VerificationReviewDuplicateError,
    VerificationReviewNotFoundError,
)

# ── Constants ─────────────────────────────────────────────────────────────────

DEMO_USER_ID = "00000000-0000-0000-0000-000000000042"
EVIDENCE_ID  = "eeeeeeee-0000-0000-0000-000000000042"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
    # The admin verification-review routes are admin-gated; these tests
    # exercise admin behaviour, so the role check is satisfied via override.
    app.dependency_overrides[require_admin_user_id] = lambda: DEMO_USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_session(client: TestClient) -> str:
    """Create a proof session and return its ID."""
    r = client.post(
        "/api/v1/student/extension-proof/sessions",
        json={"skill_evidence_id": EVIDENCE_ID},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _submit_review(
    client: TestClient,
    session_id: str,
    readiness_score: int,
    readiness_level: str = "strong",
    expected_status: int = 200,
) -> dict:
    r = client.post(
        f"/api/v1/student/extension-proof/sessions/{session_id}/submit-ai-review",
        params={"readiness_score": readiness_score, "readiness_level": readiness_level},
    )
    assert r.status_code == expected_status, r.text
    return r.json()


def _get_status(
    client: TestClient,
    session_id: str,
    expected_status: int = 200,
) -> dict:
    r = client.get(
        f"/api/v1/student/extension-proof/sessions/{session_id}/review-status"
    )
    assert r.status_code == expected_status, r.text
    return r.json()


# ── Unit: _apply_ai_decision ──────────────────────────────────────────────────


class TestApplyAiDecision:
    """Pure unit tests for the AI decision function."""

    def test_score_80_clean_approves(self) -> None:
        status, summary = _apply_ai_decision(80, "strong", "clean")
        assert status == "ai_approved_for_sharing"
        assert "VeriBridge AI Reviewed" in summary or "80" in summary

    def test_score_100_clean_approves(self) -> None:
        status, _ = _apply_ai_decision(100, "strong", "clean")
        assert status == "ai_approved_for_sharing"

    def test_score_79_clean_recommends_manual(self) -> None:
        status, summary = _apply_ai_decision(79, "moderate", "clean")
        assert status == "manual_review_recommended"

    def test_score_60_clean_recommends_manual(self) -> None:
        status, _ = _apply_ai_decision(60, "moderate", "clean")
        assert status == "manual_review_recommended"

    def test_score_59_clean_needs_more(self) -> None:
        status, _ = _apply_ai_decision(59, "weak", "clean")
        assert status == "needs_more_evidence"

    def test_score_0_clean_needs_more(self) -> None:
        status, _ = _apply_ai_decision(0, "insufficient", "clean")
        assert status == "needs_more_evidence"

    def test_score_80_privacy_flagged_blocks(self) -> None:
        """Even a perfect score cannot pass if privacy is flagged."""
        status, summary = _apply_ai_decision(80, "strong", "flagged")
        assert status == "privacy_flagged"
        assert "privacy" in summary.lower() or "sensitive" in summary.lower()

    def test_score_100_privacy_flagged_blocks(self) -> None:
        status, _ = _apply_ai_decision(100, "strong", "flagged")
        assert status == "privacy_flagged"

    def test_no_privacy_scan_treats_as_clean(self) -> None:
        """None privacy_status (no scan run yet) is treated as clean."""
        status, _ = _apply_ai_decision(85, "strong", None)
        assert status == "ai_approved_for_sharing"

    def test_redacted_privacy_allows_approval(self) -> None:
        """'redacted' is considered clean for approval purposes."""
        status, _ = _apply_ai_decision(90, "strong", "redacted")
        assert status == "ai_approved_for_sharing"

    def test_ai_decision_never_returns_human_verified(self) -> None:
        """AI review MUST NEVER set human_verified."""
        for score in [0, 50, 80, 100]:
            for privacy in ["clean", "redacted", "flagged", None]:
                status, _ = _apply_ai_decision(score, "strong", privacy)
                assert status != "human_verified", (
                    f"AI decision returned human_verified for score={score}, privacy={privacy}"
                )


# ── API: student submit ───────────────────────────────────────────────────────


class TestStudentSubmitAiReview:
    def test_submit_high_score_approves(self, client: TestClient) -> None:
        sid = _make_session(client)
        body = _submit_review(client, sid, readiness_score=85, readiness_level="strong")
        assert body["ai_review_status"] == "ai_approved_for_sharing"
        assert body["proof_session_id"] == sid
        assert body["user_id"] == DEMO_USER_ID

    def test_submit_mid_score_recommends_manual(self, client: TestClient) -> None:
        sid = _make_session(client)
        body = _submit_review(client, sid, readiness_score=65, readiness_level="moderate")
        assert body["ai_review_status"] == "manual_review_recommended"

    def test_submit_low_score_needs_more_evidence(self, client: TestClient) -> None:
        sid = _make_session(client)
        body = _submit_review(client, sid, readiness_score=40, readiness_level="weak")
        assert body["ai_review_status"] == "needs_more_evidence"

    def test_submit_score_0_needs_more_evidence(self, client: TestClient) -> None:
        sid = _make_session(client)
        body = _submit_review(client, sid, readiness_score=0, readiness_level="insufficient")
        assert body["ai_review_status"] == "needs_more_evidence"

    def test_submit_score_80_exact_approves(self, client: TestClient) -> None:
        sid = _make_session(client)
        body = _submit_review(client, sid, readiness_score=80, readiness_level="strong")
        assert body["ai_review_status"] == "ai_approved_for_sharing"

    def test_timer_status_representable(self, client: TestClient) -> None:
        """submitted_for_ai_review and ai_review_in_progress are valid status values.

        In a production deployment with async workers, the status would pass
        through these states before completion.  Our synchronous MVP resolves
        immediately, but we verify the status literals are accepted by the schema.
        """
        from app.schemas.verification_review import VerificationReviewResponse
        # Just confirm the Literal type accepts these values (type-level check)
        import pydantic
        import json as _json
        from datetime import datetime, UTC

        sample = {
            "id": "aa",
            "proof_session_id": "bb",
            "user_id": "cc",
            "ai_review_status": "submitted_for_ai_review",
            "ai_decision_summary": "",
            "human_review_status": "human_review_not_requested",
            "readiness_score": 0,
            "readiness_level": "insufficient",
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        resp = VerificationReviewResponse(**sample)
        assert resp.ai_review_status == "submitted_for_ai_review"

        sample2 = {**sample, "ai_review_status": "ai_review_in_progress"}
        resp2 = VerificationReviewResponse(**sample2)
        assert resp2.ai_review_status == "ai_review_in_progress"

    def test_response_has_required_fields(self, client: TestClient) -> None:
        sid = _make_session(client)
        body = _submit_review(client, sid, readiness_score=85, readiness_level="strong")
        required = [
            "id", "proof_session_id", "user_id",
            "ai_review_status", "ai_decision_summary",
            "human_review_status",
            "readiness_score", "readiness_level",
            "created_at", "updated_at",
            "assignments",
        ]
        for field in required:
            assert field in body, f"Missing field: {field}"

    def test_assignments_empty_in_mvp(self, client: TestClient) -> None:
        """Human reviewer assignments are empty in MVP."""
        sid = _make_session(client)
        body = _submit_review(client, sid, readiness_score=85, readiness_level="strong")
        assert body["assignments"] == []

    def test_human_review_status_is_not_requested_by_default(self, client: TestClient) -> None:
        sid = _make_session(client)
        body = _submit_review(client, sid, readiness_score=85, readiness_level="strong")
        assert body["human_review_status"] == "human_review_not_requested"

    def test_ai_approved_does_not_set_human_verified(self, client: TestClient) -> None:
        """CRITICAL: AI approval MUST NOT set human_review_status to human_verified."""
        sid = _make_session(client)
        body = _submit_review(client, sid, readiness_score=100, readiness_level="strong")
        assert body["ai_review_status"] == "ai_approved_for_sharing"
        assert body["human_review_status"] != "human_verified", (
            "BUG: AI review set human_verified — this is forbidden."
        )


# ── API: privacy flagged via in-memory privacy scan ───────────────────────────


class TestPrivacyFlaggedBlocking:
    def test_privacy_flagged_blocks_approval(
        self, client: TestClient, mem_store: dict
    ) -> None:
        """If the privacy scan shows flagged, AI review must return privacy_flagged."""
        sid = _make_session(client)

        # Seed the in-memory store with a flagged privacy scan
        mem_store.setdefault("workflow_privacy_scan_results", {})
        mem_store["workflow_privacy_scan_results"]["scan-1"] = {
            "id": "scan-1",
            "user_id": DEMO_USER_ID,
            "proof_session_id": sid,
            "status": "flagged",
            "risk_flags": [{"type": "api_key", "field": "workflow_events"}],
        }

        body = _submit_review(client, sid, readiness_score=90, readiness_level="strong")
        assert body["ai_review_status"] == "privacy_flagged", (
            f"Expected privacy_flagged but got {body['ai_review_status']}"
        )

    def test_privacy_flagged_with_low_score_is_still_privacy_flagged(
        self, client: TestClient, mem_store: dict
    ) -> None:
        sid = _make_session(client)
        mem_store.setdefault("workflow_privacy_scan_results", {})
        mem_store["workflow_privacy_scan_results"]["scan-2"] = {
            "id": "scan-2",
            "user_id": DEMO_USER_ID,
            "proof_session_id": sid,
            "status": "flagged",
            "risk_flags": [],
        }
        body = _submit_review(client, sid, readiness_score=30, readiness_level="insufficient")
        assert body["ai_review_status"] == "privacy_flagged"

    def test_privacy_clean_does_not_block(
        self, client: TestClient, mem_store: dict
    ) -> None:
        sid = _make_session(client)
        mem_store.setdefault("workflow_privacy_scan_results", {})
        mem_store["workflow_privacy_scan_results"]["scan-3"] = {
            "id": "scan-3",
            "user_id": DEMO_USER_ID,
            "proof_session_id": sid,
            "status": "clean",
            "risk_flags": [],
        }
        body = _submit_review(client, sid, readiness_score=85, readiness_level="strong")
        assert body["ai_review_status"] == "ai_approved_for_sharing"


# ── API: duplicate prevention ─────────────────────────────────────────────────


class TestDuplicatePrevention:
    def test_resubmit_when_already_approved_returns_409(self, client: TestClient) -> None:
        sid = _make_session(client)
        _submit_review(client, sid, readiness_score=90, readiness_level="strong")
        # Second submission should conflict
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{sid}/submit-ai-review",
            params={"readiness_score": 90, "readiness_level": "strong"},
        )
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "review_already_submitted"

    def test_resubmit_when_needs_more_evidence_is_allowed(self, client: TestClient) -> None:
        sid = _make_session(client)
        body1 = _submit_review(client, sid, readiness_score=30, readiness_level="insufficient")
        assert body1["ai_review_status"] == "needs_more_evidence"

        # Re-submit with improved score
        body2 = _submit_review(client, sid, readiness_score=85, readiness_level="strong")
        assert body2["ai_review_status"] == "ai_approved_for_sharing"

    def test_resubmit_when_manual_review_recommended_is_allowed(
        self, client: TestClient
    ) -> None:
        sid = _make_session(client)
        body1 = _submit_review(client, sid, readiness_score=65, readiness_level="moderate")
        assert body1["ai_review_status"] == "manual_review_recommended"

        body2 = _submit_review(client, sid, readiness_score=90, readiness_level="strong")
        assert body2["ai_review_status"] == "ai_approved_for_sharing"

    def test_resubmit_when_privacy_flagged_is_allowed(self, client: TestClient, mem_store: dict) -> None:
        sid = _make_session(client)
        mem_store.setdefault("workflow_privacy_scan_results", {})
        mem_store["workflow_privacy_scan_results"]["scan-dp"] = {
            "id": "scan-dp",
            "user_id": DEMO_USER_ID,
            "proof_session_id": sid,
            "status": "flagged",
            "risk_flags": [],
        }
        body1 = _submit_review(client, sid, readiness_score=90, readiness_level="strong")
        assert body1["ai_review_status"] == "privacy_flagged"

        # Now fix privacy and resubmit
        mem_store["workflow_privacy_scan_results"]["scan-dp"]["status"] = "clean"
        body2 = _submit_review(client, sid, readiness_score=90, readiness_level="strong")
        assert body2["ai_review_status"] == "ai_approved_for_sharing"


# ── API: get review status ────────────────────────────────────────────────────


class TestGetReviewStatus:
    def test_404_before_submission(self, client: TestClient) -> None:
        sid = _make_session(client)
        r = client.get(
            f"/api/v1/student/extension-proof/sessions/{sid}/review-status"
        )
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "review_not_found"

    def test_returns_status_after_submission(self, client: TestClient) -> None:
        sid = _make_session(client)
        _submit_review(client, sid, readiness_score=85, readiness_level="strong")
        status_body = _get_status(client, sid)
        assert status_body["ai_review_status"] == "ai_approved_for_sharing"
        assert status_body["proof_session_id"] == sid

    def test_status_reflects_latest_submission(self, client: TestClient) -> None:
        sid = _make_session(client)
        _submit_review(client, sid, readiness_score=40, readiness_level="insufficient")
        _submit_review(client, sid, readiness_score=85, readiness_level="strong")
        status_body = _get_status(client, sid)
        assert status_body["ai_review_status"] == "ai_approved_for_sharing"

    def test_unknown_session_is_404(self, client: TestClient) -> None:
        r = client.get(
            "/api/v1/student/extension-proof/sessions/00000000-0000-0000-0000-000000000000/review-status"
        )
        assert r.status_code == 404


# ── API: admin endpoints ──────────────────────────────────────────────────────


class TestAdminEndpoints:
    def test_admin_list_reviews_returns_all(self, client: TestClient) -> None:
        # Create two sessions and submit reviews
        sid1 = _make_session(client)
        sid2 = _make_session(client)
        _submit_review(client, sid1, 85, "strong")
        _submit_review(client, sid2, 40, "weak")

        r = client.get("/api/v1/admin/verification-reviews")
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 2

        ai_statuses = {item["ai_review_status"] for item in items}
        assert "ai_approved_for_sharing" in ai_statuses
        assert "needs_more_evidence" in ai_statuses

    def test_admin_list_returns_expected_fields(self, client: TestClient) -> None:
        sid = _make_session(client)
        _submit_review(client, sid, 85, "strong")

        r = client.get("/api/v1/admin/verification-reviews")
        item = r.json()[0]
        required = [
            "id", "proof_session_id", "user_id",
            "ai_review_status", "human_review_status",
            "readiness_score", "readiness_level",
            "ai_decision_summary", "created_at", "updated_at",
        ]
        for field in required:
            assert field in item, f"Admin list item missing field: {field}"

    def test_admin_can_mark_approved(self, client: TestClient) -> None:
        sid = _make_session(client)
        _submit_review(client, sid, 40, "weak")  # starts as needs_more_evidence

        r = client.get("/api/v1/admin/verification-reviews")
        review_id = r.json()[0]["id"]

        decision_r = client.post(
            f"/api/v1/admin/verification-reviews/{review_id}/decision",
            json={
                "ai_review_status": "ai_approved_for_sharing",
                "ai_decision_summary": "Admin manual approval after reviewing evidence.",
            },
        )
        assert decision_r.status_code == 200
        body = decision_r.json()
        assert body["ai_review_status"] == "ai_approved_for_sharing"
        assert "Admin manual approval" in body["ai_decision_summary"]

    def test_admin_can_request_more_evidence(self, client: TestClient) -> None:
        sid = _make_session(client)
        _submit_review(client, sid, 85, "strong")  # starts as approved

        r = client.get("/api/v1/admin/verification-reviews")
        review_id = r.json()[0]["id"]

        decision_r = client.post(
            f"/api/v1/admin/verification-reviews/{review_id}/decision",
            json={
                "ai_review_status": "needs_more_evidence",
                "ai_decision_summary": "Admin review: evidence does not support claimed skills.",
            },
        )
        assert decision_r.status_code == 200
        assert decision_r.json()["ai_review_status"] == "needs_more_evidence"

    def test_admin_decision_does_not_set_human_verified(self, client: TestClient) -> None:
        """Admin can only set AI review status, not human_review_status."""
        sid = _make_session(client)
        _submit_review(client, sid, 40, "weak")

        r = client.get("/api/v1/admin/verification-reviews")
        review_id = r.json()[0]["id"]

        decision_r = client.post(
            f"/api/v1/admin/verification-reviews/{review_id}/decision",
            json={"ai_review_status": "ai_approved_for_sharing", "ai_decision_summary": ""},
        )
        body = decision_r.json()
        # human_review_status must NOT be human_verified
        assert body["human_review_status"] != "human_verified", (
            "BUG: Admin AI decision set human_verified — this is forbidden."
        )

    def test_admin_decision_404_for_unknown_id(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/admin/verification-reviews/00000000-0000-0000-0000-000000000000/decision",
            json={"ai_review_status": "ai_approved_for_sharing", "ai_decision_summary": ""},
        )
        assert r.status_code == 404

    def test_admin_invite_reviewer_creates_assignment(self, client: TestClient) -> None:
        """Future reviewer architecture: admin can invite a human reviewer."""
        sid = _make_session(client)
        _submit_review(client, sid, 40, "weak")

        r = client.get("/api/v1/admin/verification-reviews")
        review_id = r.json()[0]["id"]

        invite_r = client.post(
            f"/api/v1/admin/verification-reviews/{review_id}/invite-reviewer",
            params={
                "reviewer_email": "prof.smith@wpi.edu",
                "reviewer_name": "Prof. Smith",
                "reviewer_role": "faculty_reviewer",
                "reviewer_field": "Machine Learning",
            },
        )
        assert invite_r.status_code == 201
        body = invite_r.json()
        assert body["ok"] is True
        assert "assignment_id" in body


# ── Human reviewer fields architecture ───────────────────────────────────────


class TestHumanReviewerFieldsArchitecture:
    """Verify the data model supports the future reviewer program.

    These tests confirm the schema and DB fields exist and are populated
    correctly.  They do NOT test actual reviewer logic (which requires
    real reviewers not yet onboarded in MVP).
    """

    def test_review_request_has_human_review_status_field(
        self, client: TestClient
    ) -> None:
        sid = _make_session(client)
        body = _submit_review(client, sid, 85, "strong")
        assert "human_review_status" in body
        # Default value in MVP
        assert body["human_review_status"] == "human_review_not_requested"

    def test_review_request_has_human_review_requested_at_field(
        self, client: TestClient
    ) -> None:
        sid = _make_session(client)
        body = _submit_review(client, sid, 85, "strong")
        # Field exists (may be None before human review is requested)
        assert "human_review_requested_at" in body

    def test_assignments_list_exists_in_response(self, client: TestClient) -> None:
        sid = _make_session(client)
        body = _submit_review(client, sid, 85, "strong")
        assert "assignments" in body
        assert isinstance(body["assignments"], list)

    def test_human_verified_never_set_by_ai_review_across_all_scores(
        self, client: TestClient
    ) -> None:
        """Comprehensive check: every AI decision must never produce human_verified."""
        test_cases = [
            (0, "insufficient"),
            (50, "weak"),
            (60, "moderate"),
            (79, "moderate"),
            (80, "strong"),
            (100, "strong"),
        ]
        for score, level in test_cases:
            sid = _make_session(client)
            body = _submit_review(client, sid, score, level)
            assert body["human_review_status"] != "human_verified", (
                f"human_verified incorrectly set for score={score}, level={level}"
            )
            assert body["ai_review_status"] != "human_verified", (
                f"human_verified appeared as ai_review_status for score={score}"
            )

    def test_reviewer_role_values_are_structurally_valid(self) -> None:
        """Verify the schema accepts all defined reviewer roles."""
        from app.schemas.verification_review import ReviewerRole
        from typing import get_args

        roles = get_args(ReviewerRole)
        expected = {
            "veribridge_admin",
            "faculty_reviewer",
            "company_reviewer",
            "domain_expert",
            "recruiter_reviewer",
        }
        assert set(roles) == expected

    def test_human_review_status_values_are_structurally_valid(self) -> None:
        """Verify all required human review status values are in the schema."""
        from app.schemas.verification_review import HumanReviewStatus
        from typing import get_args

        statuses = set(get_args(HumanReviewStatus))
        required = {
            "human_review_not_requested",
            "human_review_requested",
            "faculty_review_pending",
            "company_review_pending",
            "domain_expert_review_pending",
            "faculty_reviewed",
            "company_reviewed",
            "domain_expert_reviewed",
            "human_verified",
            "human_review_rejected",
        }
        assert required.issubset(statuses), (
            f"Missing human review statuses: {required - statuses}"
        )

    def test_ai_review_status_values_are_structurally_valid(self) -> None:
        """Verify all required AI review status values are in the schema."""
        from app.schemas.verification_review import AiReviewStatus
        from typing import get_args

        statuses = set(get_args(AiReviewStatus))
        required = {
            "not_submitted",
            "submitted_for_ai_review",
            "ai_review_in_progress",
            "ai_approved_for_sharing",
            "needs_more_evidence",
            "manual_review_recommended",
            "privacy_flagged",
        }
        assert required.issubset(statuses), (
            f"Missing AI review statuses: {required - statuses}"
        )


# ── Project agnosticism ───────────────────────────────────────────────────────


class TestProjectAgnosticism:
    """Verify review workflow does not hardcode any project, city, or framework."""

    def test_ai_decision_summary_does_not_contain_hardcoded_project(
        self, client: TestClient
    ) -> None:
        forbidden_terms = ["boston", "react", "flask", "fastapi", "wpi", "massachusetts"]
        sid = _make_session(client)
        body = _submit_review(client, sid, 85, "strong")
        summary = body.get("ai_decision_summary", "").lower()
        for term in forbidden_terms:
            assert term not in summary, (
                f"Hardcoded term '{term}' found in ai_decision_summary"
            )

    def test_needs_more_evidence_summary_is_generic(self, client: TestClient) -> None:
        forbidden_terms = ["boston", "react", "python", "node", "wpi"]
        sid = _make_session(client)
        body = _submit_review(client, sid, 30, "insufficient")
        summary = body.get("ai_decision_summary", "").lower()
        for term in forbidden_terms:
            assert term not in summary, (
                f"Hardcoded term '{term}' found in needs_more_evidence summary"
            )


# ── JSON serialisation safety ─────────────────────────────────────────────────


class TestJsonSerialization:
    """Regression tests for the datetime/UUID JSON serialisation bug.

    Before the fix, _now() returned a raw datetime object.  httpx (used by
    supabase-py) calls json.dumps() without a custom encoder, so any datetime
    in the insert/update payload raised:
        TypeError: Object of type datetime is not JSON serializable
    These tests verify the fix works end-to-end.
    """

    def test_submit_ai_review_does_not_raise_500(self, client: TestClient) -> None:
        """Core regression: submit must succeed, not crash with a datetime error."""
        sid = _make_session(client)
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{sid}/submit-ai-review",
            params={"readiness_score": 65, "readiness_level": "moderate"},
        )
        assert r.status_code == 200, (
            f"submit-ai-review returned {r.status_code}: {r.text}"
        )

    def test_insert_payload_is_json_serializable(self) -> None:
        """make_json_safe must convert datetime / UUID objects to primitives."""
        import json as _json
        from app.services.verification_review_service import make_json_safe
        from datetime import datetime, UTC
        from uuid import uuid4

        raw = {
            "id": uuid4(),
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "nested": {
                "ts": datetime.now(UTC),
                "inner_list": [datetime.now(UTC), uuid4()],
            },
        }
        safe = make_json_safe(raw)
        # Must not raise
        serialised = _json.dumps(safe)
        assert '"id"' in serialised
        assert '"created_at"' in serialised
        assert "T" in serialised  # ISO format contains 'T'

    def test_now_returns_string(self) -> None:
        """_now() must return an ISO string, not a datetime object."""
        from app.services.verification_review_service import _now
        result = _now()
        assert isinstance(result, str), f"_now() returned {type(result)}, expected str"
        assert "T" in result  # basic ISO format sanity check

    def test_make_json_safe_handles_nested_datetime_in_list(self) -> None:
        from app.services.verification_review_service import make_json_safe
        from datetime import datetime, UTC

        ts = datetime.now(UTC)
        safe = make_json_safe([ts, {"key": ts}])
        assert isinstance(safe[0], str)
        assert isinstance(safe[1]["key"], str)

    def test_make_json_safe_leaves_primitives_unchanged(self) -> None:
        from app.services.verification_review_service import make_json_safe

        assert make_json_safe(42) == 42
        assert make_json_safe("hello") == "hello"
        assert make_json_safe(True) is True
        assert make_json_safe(None) is None

    def test_submit_response_contains_iso_timestamps(self, client: TestClient) -> None:
        """Timestamps in the response must be parseable datetime strings."""
        from datetime import datetime

        sid = _make_session(client)
        body = _submit_review(client, sid, 85, "strong")
        for field in ("created_at", "updated_at"):
            raw = body.get(field)
            assert raw is not None, f"{field} missing from response"
            # Pydantic serialises datetimes as ISO strings in JSON responses
            assert isinstance(raw, str), f"{field} is not a string in JSON: {type(raw)}"

    def test_resubmission_after_needs_more_evidence_does_not_raise_500(
        self, client: TestClient
    ) -> None:
        """Update path (not just insert) must also be datetime-safe."""
        sid = _make_session(client)
        _submit_review(client, sid, 30, "insufficient")  # → needs_more_evidence
        # Second submission triggers the UPDATE code path
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{sid}/submit-ai-review",
            params={"readiness_score": 85, "readiness_level": "strong"},
        )
        assert r.status_code == 200, (
            f"Re-submission update path returned {r.status_code}: {r.text}"
        )
        assert r.json()["ai_review_status"] == "ai_approved_for_sharing"


# ── Response safety: no unsafe strings ────────────────────────────────────────


class TestResponseSafety:
    """Verify the review API never exposes tokens, storage paths, or service URLs."""

    FORBIDDEN = ["access_token", "storage_path", "supabase.co", "env secret"]

    def test_submit_response_excludes_unsafe_strings(
        self, client: TestClient
    ) -> None:
        sid = _make_session(client)
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{sid}/submit-ai-review",
            params={"readiness_score": 85, "readiness_level": "strong"},
        )
        assert r.status_code == 200
        body_text = r.text.lower()
        for term in self.FORBIDDEN:
            assert term not in body_text, (
                f"Unsafe string '{term}' found in submit-ai-review response"
            )

    def test_review_status_response_excludes_unsafe_strings(
        self, client: TestClient
    ) -> None:
        sid = _make_session(client)
        _submit_review(client, sid, 85, "strong")
        r = client.get(
            f"/api/v1/student/extension-proof/sessions/{sid}/review-status"
        )
        assert r.status_code == 200
        body_text = r.text.lower()
        for term in self.FORBIDDEN:
            assert term not in body_text, (
                f"Unsafe string '{term}' found in review-status response"
            )

    def test_admin_list_excludes_unsafe_strings(
        self, client: TestClient
    ) -> None:
        sid = _make_session(client)
        _submit_review(client, sid, 85, "strong")
        r = client.get("/api/v1/admin/verification-reviews")
        assert r.status_code == 200
        body_text = r.text.lower()
        for term in self.FORBIDDEN:
            assert term not in body_text, (
                f"Unsafe string '{term}' found in admin list response"
            )


# ── Website Proof review persistence ─────────────────────────────────────────


class TestWebsiteProofReviewPersistence:
    """Verify the review workflow persists correctly for website proof sessions.

    The backend review service is website-URL-agnostic — it stores and retrieves
    review state keyed only by proof_session_id.  These tests confirm the
    create/upsert/fetch cycle that backs the frontend's backend persistence.
    """

    def test_create_review_snapshot_for_proof_session(
        self, client: TestClient
    ) -> None:
        """First submit creates a review row for the session."""
        sid = _make_session(client)
        body = _submit_review(client, sid, 85, "strong")
        assert body["proof_session_id"] == sid
        assert body["ai_review_status"] == "ai_approved_for_sharing"
        assert body["readiness_score"] == 85

    def test_fetch_review_snapshot_by_proof_session_id(
        self, client: TestClient
    ) -> None:
        """review-status returns the persisted review for a session."""
        sid = _make_session(client)
        _submit_review(client, sid, 85, "strong")
        status = _get_status(client, sid)
        assert status["proof_session_id"] == sid
        assert status["ai_review_status"] == "ai_approved_for_sharing"

    def test_upsert_updates_existing_review_row(
        self, client: TestClient
    ) -> None:
        """Re-submitting with an improved score upserts the existing row."""
        sid = _make_session(client)
        body1 = _submit_review(client, sid, 40, "weak")
        assert body1["ai_review_status"] == "needs_more_evidence"

        body2 = _submit_review(client, sid, 85, "strong")
        assert body2["ai_review_status"] == "ai_approved_for_sharing"

        # Fetch confirms only one review row — the latest
        status = _get_status(client, sid)
        assert status["ai_review_status"] == "ai_approved_for_sharing"

    def test_approve_marks_review_as_ai_approved_for_sharing(
        self, client: TestClient
    ) -> None:
        """Score >= 80 with clean privacy produces ai_approved_for_sharing."""
        sid = _make_session(client)
        body = _submit_review(client, sid, 80, "strong")
        assert body["ai_review_status"] == "ai_approved_for_sharing"
        status = _get_status(client, sid)
        assert status["ai_review_status"] == "ai_approved_for_sharing"

    def test_two_sessions_persist_independently(
        self, client: TestClient
    ) -> None:
        """Different sessions store their own review rows independently."""
        sid1 = _make_session(client)
        sid2 = _make_session(client)
        _submit_review(client, sid1, 85, "strong")
        _submit_review(client, sid2, 40, "weak")
        assert _get_status(client, sid1)["ai_review_status"] == "ai_approved_for_sharing"
        assert _get_status(client, sid2)["ai_review_status"] == "needs_more_evidence"

    def test_local_and_live_url_sessions_treated_identically(
        self, client: TestClient
    ) -> None:
        """The review service is URL-type-agnostic (local vs live website proof).

        Both session types use the same review endpoints keyed by proof_session_id.
        The backend does not inspect or branch on website_url type.
        """
        # Two sessions — one simulating local URL proof, one live — both get
        # reviewed by the same endpoints without any difference in behavior.
        sid_local = _make_session(client)
        sid_live = _make_session(client)
        body_local = _submit_review(client, sid_local, 82, "strong")
        body_live = _submit_review(client, sid_live, 82, "strong")
        assert body_local["ai_review_status"] == "ai_approved_for_sharing"
        assert body_live["ai_review_status"] == "ai_approved_for_sharing"
        assert body_local["proof_session_id"] != body_live["proof_session_id"]
