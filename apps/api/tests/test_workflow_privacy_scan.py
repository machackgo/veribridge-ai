"""
Tests for the Workflow Privacy Scan feature.

Covers:
- Input field redaction (password, api_key, token, etc.)
- URL query parameter redaction
- Sensitive pattern detection (JWT, AWS key, credit card, SSN, etc.)
- Clean workflow detection
- Privacy scan service (store / get)
- Upload endpoint returns privacy_scan_status
- Privacy scan API endpoints
- Existing workflow analysis still passes after privacy scan integration
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.deps import get_current_user_id, get_db
from app.services.workflow_privacy_scan_service import (
    WorkflowPrivacyScanService,
    PrivacyScanResult,
    scan_proof_data,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

DEMO_USER_ID = "00000000-0000-0000-0000-000000000001"
EVIDENCE_ID = "eeeeeeee-0000-0000-0000-000000000001"
SESSION_ID = "ssssssss-0000-0000-0000-000000000001"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _create_and_upload_session(client: TestClient, extra_events: list | None = None) -> dict:
    """Helper: create, start, and upload a proof session; return upload response."""
    r = client.post(
        "/api/v1/student/extension-proof/sessions",
        json={"skill_evidence_id": EVIDENCE_ID},
    )
    assert r.status_code == 201
    session_id = r.json()["id"]

    r = client.post(f"/api/v1/student/extension-proof/sessions/{session_id}/start")
    assert r.status_code == 200

    events = extra_events or [
        {"type": "page_visit", "page_url": "https://example.com/dashboard", "page_title": "App"},
        {"type": "click", "element_tag": "button", "element_text": "Submit"},
    ]
    r = client.post(
        f"/api/v1/student/extension-proof/sessions/{session_id}/upload",
        json={"workflow_events": events, "extension_version": "1.0.0"},
    )
    assert r.status_code == 200
    return r.json()


# ── Unit: scan_proof_data (pure function) ─────────────────────────────────────


class TestScanProofData:
    # ── Clean workflows ───────────────────────────────────────────────────────

    def test_clean_workflow_returns_clean(self) -> None:
        data = {
            "workflow_events": [
                {"type": "page_visit", "page_url": "https://example.com/dashboard", "page_title": "App"},
                {"type": "click", "element_tag": "button", "element_text": "Run Test"},
            ]
        }
        result = scan_proof_data(data)
        assert result.status == "clean"
        assert result.risk_flags == []
        assert result.contains_sensitive_data is False

    def test_empty_data_is_clean(self) -> None:
        result = scan_proof_data({})
        assert result.status == "clean"
        assert result.contains_sensitive_data is False

    # ── Input field redaction markers ─────────────────────────────────────────

    def test_redacted_sensitive_field_marker_sets_redacted_status(self) -> None:
        """[REDACTED_SENSITIVE_FIELD] means the content script already masked an input."""
        data = {
            "workflow_events": [
                {"type": "input_change", "value": "[REDACTED_SENSITIVE_FIELD]", "element_name": "password"},
            ]
        }
        result = scan_proof_data(data)
        assert result.status == "redacted"
        assert result.redacted_fields_count >= 1
        assert result.contains_sensitive_data is False  # already masked — not a leak

    def test_redacted_backend_marker_sets_redacted_status(self) -> None:
        """[REDACTED] means the backend mask_sensitive() already masked a key."""
        data = {"auth_token": "[REDACTED]", "url": "https://example.com"}
        result = scan_proof_data(data)
        assert result.status == "redacted"
        assert result.redacted_fields_count >= 1

    def test_multiple_redacted_fields_counted(self) -> None:
        data = {
            "f1": "[REDACTED_SENSITIVE_FIELD]",
            "f2": "[REDACTED_SENSITIVE_FIELD]",
            "f3": "[REDACTED]",
        }
        result = scan_proof_data(data)
        assert result.redacted_fields_count >= 3

    # ── URL query param redaction ─────────────────────────────────────────────

    def test_redacted_url_param_sets_redacted_status(self) -> None:
        """?access_token=[REDACTED] means the extension/background already redacted the URL."""
        data = {
            "workflow_events": [
                {"type": "navigation", "page_url": "https://app.example.com/callback?access_token=[REDACTED]&user=test"},
            ]
        }
        result = scan_proof_data(data)
        assert result.status == "redacted"
        assert result.redacted_urls_count >= 1

    def test_raw_access_token_in_url_is_flagged(self) -> None:
        """access_token=abc123 (not redacted) should flag the proof."""
        data = {
            "workflow_events": [
                {"type": "navigation", "page_url": "https://app.example.com/callback?access_token=eyJhbGciOiJSUzI1NiJ9.payload.sig"},
            ]
        }
        result = scan_proof_data(data)
        assert result.status == "flagged"
        assert result.contains_sensitive_data is True

    def test_api_key_in_url_param_is_flagged(self) -> None:
        """api_key= with a real value in a URL should be flagged."""
        data = {
            "workflow_events": [
                {"type": "page_visit", "page_url": "https://maps.example.com/?api_key=AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ12345678"},
            ]
        }
        result = scan_proof_data(data)
        assert result.status == "flagged"
        assert any("Google API key" in f or "API key" in f.lower() or "api" in f.lower() for f in result.risk_flags), result.risk_flags

    # ── JWT detection ─────────────────────────────────────────────────────────

    def test_jwt_like_string_is_flagged(self) -> None:
        """A JWT-format string (three base64url segments) should be flagged."""
        jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyXzEyMyJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        data = {
            "workflow_events": [
                {"type": "input_change", "value": jwt, "element_name": "token"},
            ]
        }
        result = scan_proof_data(data)
        assert result.status == "flagged"
        assert result.contains_sensitive_data is True
        assert any("JWT" in f for f in result.risk_flags)

    # ── API key detection ─────────────────────────────────────────────────────

    def test_aws_access_key_is_flagged(self) -> None:
        data = {"config": {"aws_key": "AKIAIOSFODNN7EXAMPLE"}}
        result = scan_proof_data(data)
        assert result.status == "flagged"
        assert any("AWS" in f for f in result.risk_flags)

    def test_openai_key_is_flagged(self) -> None:
        data = {"metadata": {"api_key": "sk-proj-abcdefghijklmnopqrstuvwxyz123456789"}}
        result = scan_proof_data(data)
        assert result.status == "flagged"
        assert any("OpenAI" in f for f in result.risk_flags)

    def test_anthropic_key_is_flagged(self) -> None:
        data = {"metadata": {"api_key": "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789ABCD"}}
        result = scan_proof_data(data)
        assert result.status == "flagged"
        assert any("Anthropic" in f for f in result.risk_flags)

    def test_bearer_token_is_flagged(self) -> None:
        data = {
            "workflow_events": [
                {"type": "page_visit", "headers": {"Authorization": "Bearer eyJhbGciOiJSUzI1NiJ9testtoken12345678901234"}}
            ]
        }
        result = scan_proof_data(data)
        assert result.status == "flagged"
        assert any("Bearer" in f or "JWT" in f for f in result.risk_flags)

    # ── PII / payment detection ───────────────────────────────────────────────

    def test_ssn_pattern_is_flagged(self) -> None:
        data = {"form_data": {"ssn": "123-45-6789"}}
        result = scan_proof_data(data)
        assert result.status == "flagged"
        assert any("SSN" in f for f in result.risk_flags)

    def test_credit_card_pattern_is_flagged(self) -> None:
        # Classic Visa test card number
        data = {"payment": {"card": "4111111111111111"}}
        result = scan_proof_data(data)
        assert result.status == "flagged"
        assert any("credit card" in f.lower() or "card" in f.lower() for f in result.risk_flags)

    def test_private_key_block_is_flagged(self) -> None:
        data = {"config": {"key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA..."}}
        result = scan_proof_data(data)
        assert result.status == "flagged"
        assert any("private key" in f.lower() for f in result.risk_flags)

    def test_github_token_is_flagged(self) -> None:
        data = {"tokens": {"gh": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef1234"}}
        result = scan_proof_data(data)
        assert result.status == "flagged"
        assert any("GitHub" in f for f in result.risk_flags)

    def test_stripe_key_is_flagged(self) -> None:
        data = {"payment_config": {"key": "sk_live_abcdefghijklmnopqrstuvwxyz"}}
        result = scan_proof_data(data)
        assert result.status == "flagged"
        assert any("Stripe" in f for f in result.risk_flags)

    # ── Summary messages ──────────────────────────────────────────────────────

    def test_clean_summary(self) -> None:
        result = scan_proof_data({"url": "https://example.com"})
        assert "No sensitive data" in result.scan_summary

    def test_redacted_summary_mentions_count(self) -> None:
        result = scan_proof_data({"f": "[REDACTED_SENSITIVE_FIELD]"})
        assert "Privacy Guard" in result.scan_summary or "masked" in result.scan_summary

    def test_flagged_summary_mentions_hidden(self) -> None:
        data = {"token": "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyXzEyMyJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"}
        result = scan_proof_data(data)
        assert "hidden" in result.scan_summary.lower() or "sensitive" in result.scan_summary.lower()


# ── Unit: WorkflowPrivacyScanService ─────────────────────────────────────────


class TestWorkflowPrivacyScanService:
    def test_store_and_get_in_memory(self) -> None:
        store: dict = {}
        svc = WorkflowPrivacyScanService(store)
        result = PrivacyScanResult(
            status="clean",
            risk_flags=[],
            redacted_fields_count=0,
            redacted_urls_count=0,
            contains_sensitive_data=False,
            scan_summary="No sensitive data detected.",
        )
        svc.store_scan(DEMO_USER_ID, SESSION_ID, result)
        retrieved = svc.get_scan(DEMO_USER_ID, SESSION_ID)
        assert retrieved is not None
        assert retrieved["status"] == "clean"

    def test_get_returns_none_for_missing_session(self) -> None:
        store: dict = {}
        svc = WorkflowPrivacyScanService(store)
        assert svc.get_scan(DEMO_USER_ID, "nonexistent") is None

    def test_store_overwrites_on_same_session(self) -> None:
        store: dict = {}
        svc = WorkflowPrivacyScanService(store)
        r1 = PrivacyScanResult(status="clean", scan_summary="clean")
        r2 = PrivacyScanResult(status="flagged", risk_flags=["JWT detected"], scan_summary="flagged")
        svc.store_scan(DEMO_USER_ID, SESSION_ID, r1)
        svc.store_scan(DEMO_USER_ID, SESSION_ID, r2)
        retrieved = svc.get_scan(DEMO_USER_ID, SESSION_ID)
        assert retrieved["status"] == "flagged"


# ── Integration: upload returns privacy_scan_status ───────────────────────────


class TestUploadPrivacyScanIntegration:
    def test_upload_returns_privacy_scan_status_for_clean_workflow(
        self, client: TestClient
    ) -> None:
        upload_resp = _create_and_upload_session(client)
        assert "privacy_scan_status" in upload_resp
        assert upload_resp["privacy_scan_status"] in ("clean", "redacted", "flagged", None)

    def test_upload_clean_workflow_has_clean_status(self, client: TestClient) -> None:
        events = [
            {"type": "page_visit", "page_url": "https://example.com/", "page_title": "Home"},
            {"type": "click", "element_tag": "button", "element_text": "Submit"},
        ]
        upload_resp = _create_and_upload_session(client, extra_events=events)
        assert upload_resp["privacy_scan_status"] == "clean"

    def test_upload_with_redacted_field_marker_returns_redacted_status(
        self, client: TestClient
    ) -> None:
        events = [
            {"type": "input_change", "value": "[REDACTED_SENSITIVE_FIELD]", "element_name": "password"},
            {"type": "page_visit", "page_url": "https://app.example.com/", "page_title": "App"},
        ]
        upload_resp = _create_and_upload_session(client, extra_events=events)
        assert upload_resp["privacy_scan_status"] == "redacted"

    def test_upload_with_jwt_in_events_returns_flagged_status(
        self, client: TestClient
    ) -> None:
        jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyXzEyMyJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        events = [
            {"type": "page_visit", "page_url": "https://example.com/", "page_title": "App"},
            {"type": "input_change", "value": jwt, "element_name": "token_field"},
        ]
        upload_resp = _create_and_upload_session(client, extra_events=events)
        assert upload_resp["privacy_scan_status"] == "flagged"


# ── Integration: privacy scan API endpoints ───────────────────────────────────


class TestPrivacyScanEndpoints:
    def test_get_privacy_scan_returns_404_before_upload(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/student/extension-proof/sessions",
            json={"skill_evidence_id": EVIDENCE_ID},
        )
        session_id = r.json()["id"]
        resp = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}/privacy-scan"
        )
        assert resp.status_code == 404

    def test_post_privacy_scan_returns_404_for_unknown_session(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            "/api/v1/student/extension-proof/sessions/nonexistent-session/privacy-scan"
        )
        assert resp.status_code == 404

    def test_get_privacy_scan_after_upload_returns_200(self, client: TestClient) -> None:
        upload_resp = _create_and_upload_session(client)
        session_id = upload_resp["id"]
        resp = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}/privacy-scan"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("clean", "redacted", "flagged")
        assert "proof_session_id" in data
        assert "risk_flags" in data
        assert "scan_summary" in data

    def test_post_privacy_scan_re_runs_and_returns_result(
        self, client: TestClient
    ) -> None:
        upload_resp = _create_and_upload_session(client)
        session_id = upload_resp["id"]
        resp = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/privacy-scan"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["proof_session_id"] == session_id
        assert data["status"] in ("clean", "redacted", "flagged")

    def test_privacy_scan_result_has_required_fields(self, client: TestClient) -> None:
        upload_resp = _create_and_upload_session(client)
        session_id = upload_resp["id"]
        resp = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}/privacy-scan"
        )
        data = resp.json()
        required_fields = [
            "status", "proof_session_id", "user_id", "risk_flags",
            "redacted_fields_count", "redacted_urls_count",
            "contains_sensitive_data", "scan_summary",
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

    def test_privacy_scan_endpoint_in_openapi(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]
        found = any("/privacy-scan" in p for p in paths)
        assert found, "privacy-scan route not in OpenAPI spec"


# ── Recruiter / public safety ─────────────────────────────────────────────────


class TestFlaggedProofIsNotPubliclyVisible:
    """
    Verify that a flagged proof signals that it should be hidden from public view.
    The scan result carries contains_sensitive_data=True and status='flagged',
    which the UI and recruiter views check before displaying.
    """

    def test_flagged_proof_has_contains_sensitive_data_true(
        self, client: TestClient
    ) -> None:
        jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyXzEyMyJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        events = [{"type": "input_change", "value": jwt}]
        upload_resp = _create_and_upload_session(client, extra_events=events)
        session_id = upload_resp["id"]

        # Upload should already flag it
        assert upload_resp["privacy_scan_status"] == "flagged"

        # And the stored scan result should agree
        scan_resp = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}/privacy-scan"
        ).json()
        assert scan_resp["status"] == "flagged"
        assert scan_resp["contains_sensitive_data"] is True

    def test_clean_proof_has_contains_sensitive_data_false(
        self, client: TestClient
    ) -> None:
        events = [
            {"type": "page_visit", "page_url": "https://example.com/", "page_title": "App"},
        ]
        upload_resp = _create_and_upload_session(client, extra_events=events)
        session_id = upload_resp["id"]

        scan_resp = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}/privacy-scan"
        ).json()
        assert scan_resp["contains_sensitive_data"] is False


# ── Regression: existing workflow analysis still works ────────────────────────


class TestExistingWorkflowAnalysisUnaffected:
    """
    Smoke-test that the existing upload→complete→analysis chain still works
    after the privacy scan integration.  The scan is non-critical and must
    never prevent a valid upload from succeeding.
    """

    def test_upload_still_returns_200_after_privacy_scan_integration(
        self, client: TestClient
    ) -> None:
        upload_resp = _create_and_upload_session(client)
        assert upload_resp["status"] == "uploaded_pending_analysis"
        assert upload_resp["proof_upload_id"] is not None

    def test_complete_still_works_after_upload_with_privacy_scan(
        self, client: TestClient
    ) -> None:
        upload_resp = _create_and_upload_session(client)
        session_id = upload_resp["id"]
        resp = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/complete"
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "analyzing"

    def test_upload_does_not_fail_on_malformed_proof_data(
        self, client: TestClient
    ) -> None:
        """Even if proof_data contains odd types, the upload must succeed."""
        events = [{"deeply_nested": {"a": {"b": {"c": None}}}}]
        upload_resp = _create_and_upload_session(client, extra_events=events)
        assert upload_resp["status"] == "uploaded_pending_analysis"
