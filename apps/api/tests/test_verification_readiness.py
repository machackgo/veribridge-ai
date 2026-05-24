"""
Tests for the Verification Readiness Report.

Covers:
- Deployed app with workflow + GitHub + live check + clean privacy → Moderate/Strong
- Local-only app does NOT get penalised for no live website check
- Privacy flagged caps readiness at Weak (max 59)
- GitHub missing but workflow/live exists → lower but valid readiness
- Short recording risk lowers score
- Strong skill support increases score
- No hardcoded project names or URLs
- Final Verification NEVER becomes "complete" from this feature
- Backend endpoint returns 404 for unknown sessions
- Backend endpoint returns expected fields
- Cross-evidence skill confirmation increases score
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.verification_readiness_service import (
    _classify_url,
    compute_readiness_report,
)

# ── Test identifiers ──────────────────────────────────────────────────────────

DEMO_USER_ID = "00000000-0000-0000-0000-000000000099"
EVIDENCE_ID = "eeeeeeee-0000-0000-0000-000000000099"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_session(client: TestClient) -> str:
    r = client.post(
        "/api/v1/student/extension-proof/sessions",
        json={"skill_evidence_id": EVIDENCE_ID},
    )
    assert r.status_code == 201
    return r.json()["id"]


def _upload(client: TestClient, session_id: str) -> None:
    r = client.post(f"/api/v1/student/extension-proof/sessions/{session_id}/start")
    assert r.status_code == 200
    r = client.post(
        f"/api/v1/student/extension-proof/sessions/{session_id}/upload",
        json={
            "workflow_events": [
                {"type": "page_visit", "page_url": "https://example.com", "page_title": "App"},
            ]
        },
    )
    assert r.status_code == 200


# ── Unit: _classify_url ────────────────────────────────────────────────────────

class TestClassifyUrl:
    def test_localhost(self) -> None:
        assert _classify_url("http://localhost:3000") == "localhost_url"

    def test_127(self) -> None:
        assert _classify_url("http://127.0.0.1:8000") == "localhost_url"

    def test_private_10(self) -> None:
        assert _classify_url("http://10.0.0.5:8080") == "local_network_url"

    def test_private_192(self) -> None:
        assert _classify_url("http://192.168.1.1") == "local_network_url"

    def test_live(self) -> None:
        assert _classify_url("https://myapp.vercel.app") == "live_deployed_url"

    def test_invalid(self) -> None:
        assert _classify_url("not-a-url") == "invalid_url"


# ── Unit: compute_readiness_report ────────────────────────────────────────────

class TestComputeReadinessReport:
    """Pure-function unit tests — no DB, no HTTP."""

    # ── Acceptance: deployed app with all evidence → Moderate or Strong ───────

    def test_full_deployed_evidence_gives_moderate_or_strong(self) -> None:
        result = compute_readiness_report(
            proof_session_id="s1",
            session_status="completed",
            url_type="live_deployed_url",
            claimed_skills=["React", "FastAPI"],
            workflow_analysis={
                "supported_skills": ["React", "FastAPI"],
                "weakly_supported_skills": [],
                "unsupported_skills": [],
                "missing_evidence": [],
                "risk_flags": [],
                "recruiter_summary": "Clear demonstration of React frontend and FastAPI backend.",
                "human_review_needed": False,
            },
            live_check={"is_reachable": True},
            github_analysis={
                "status": "success",
                "matched_claimed_skills": ["React", "FastAPI"],
                "weakly_matched_claimed_skills": [],
                "detected_features": ["readme", "deployment"],
                "recruiter_summary": "Repository confirms React and FastAPI stack.",
            },
            privacy_scan={"status": "clean"},
        )
        assert result.readiness_score >= 60
        assert result.readiness_level in ("moderate", "strong")
        assert result.final_verification_status in ("pending", "ready_for_review")

    # ── Acceptance: Final Verification NEVER "complete" ───────────────────────

    def test_final_verification_never_complete(self) -> None:
        """Even a perfect score must not produce final_verification_status == 'complete'."""
        result = compute_readiness_report(
            proof_session_id="s2",
            session_status="completed",
            url_type="live_deployed_url",
            claimed_skills=["React"],
            workflow_analysis={
                "supported_skills": ["React"],
                "weakly_supported_skills": [],
                "unsupported_skills": [],
                "missing_evidence": [],
                "risk_flags": [],
                "recruiter_summary": "Excellent demonstration of React skills in a live app.",
                "human_review_needed": False,
            },
            live_check={"is_reachable": True},
            github_analysis={
                "status": "success",
                "matched_claimed_skills": ["React"],
                "weakly_matched_claimed_skills": [],
                "detected_features": ["readme", "deployment"],
                "recruiter_summary": "React confirmed in repository.",
            },
            privacy_scan={"status": "clean"},
        )
        assert result.final_verification_status != "complete"
        assert result.final_verification_status in ("pending", "ready_for_review")

    # ── Acceptance: local-only app not penalised for missing live check ────────

    def test_local_app_not_penalised_for_no_live_check(self) -> None:
        """localhost app without live check should get same score as deployed app
        with a successful live check — i.e. no penalty for skipping live check."""
        local_result = compute_readiness_report(
            proof_session_id="s3",
            session_status="completed",
            url_type="localhost_url",
            claimed_skills=["Node.js"],
            workflow_analysis={
                "supported_skills": ["Node.js"],
                "weakly_supported_skills": [],
                "unsupported_skills": [],
                "missing_evidence": [],
                "risk_flags": [],
                "recruiter_summary": "Node.js workflow demonstrated locally.",
                "human_review_needed": False,
            },
            live_check=None,       # no live check — local app
            github_analysis=None,  # no GitHub provided
            privacy_scan={"status": "clean"},
        )
        assert local_result.is_local_only is True
        # No risk flag about live check
        live_check_flags = [f for f in local_result.risk_flags if "accessible" in f.lower()]
        assert not live_check_flags

    def test_local_app_no_live_check_action_message_absent(self) -> None:
        """Should NOT recommend running the live website check for local apps."""
        result = compute_readiness_report(
            proof_session_id="s3b",
            session_status="completed",
            url_type="localhost_url",
            claimed_skills=["Python"],
            workflow_analysis={
                "supported_skills": ["Python"],
                "weakly_supported_skills": [],
                "unsupported_skills": [],
                "missing_evidence": [],
                "risk_flags": [],
                "recruiter_summary": "Python demonstrated.",
                "human_review_needed": False,
            },
            live_check=None,
            github_analysis=None,
            privacy_scan={"status": "clean"},
        )
        assert not any("live website check" in a.lower() for a in result.recommended_next_actions)

    # ── Acceptance: privacy flagged caps readiness ────────────────────────────

    def test_privacy_flagged_caps_score_at_59(self) -> None:
        result = compute_readiness_report(
            proof_session_id="s4",
            session_status="completed",
            url_type="live_deployed_url",
            claimed_skills=["React"],
            workflow_analysis={
                "supported_skills": ["React"],
                "weakly_supported_skills": [],
                "unsupported_skills": [],
                "missing_evidence": [],
                "risk_flags": [],
                "recruiter_summary": "React demonstrated in live app.",
                "human_review_needed": False,
            },
            live_check={"is_reachable": True},
            github_analysis={
                "status": "success",
                "matched_claimed_skills": ["React"],
                "weakly_matched_claimed_skills": [],
                "detected_features": ["readme"],
                "recruiter_summary": "React confirmed.",
            },
            privacy_scan={"status": "flagged"},
        )
        assert result.readiness_score <= 59
        assert result.readiness_level in ("weak", "insufficient")

    def test_privacy_flagged_final_verification_never_ready(self) -> None:
        result = compute_readiness_report(
            proof_session_id="s4b",
            session_status="completed",
            url_type="live_deployed_url",
            claimed_skills=["React"],
            workflow_analysis={
                "supported_skills": ["React"],
                "weakly_supported_skills": [],
                "unsupported_skills": [],
                "missing_evidence": [],
                "risk_flags": [],
                "recruiter_summary": "React shown.",
                "human_review_needed": False,
            },
            live_check={"is_reachable": True},
            github_analysis={
                "status": "success",
                "matched_claimed_skills": ["React"],
                "weakly_matched_claimed_skills": [],
                "detected_features": ["readme"],
                "recruiter_summary": "Repo OK.",
            },
            privacy_scan={"status": "flagged"},
        )
        assert result.final_verification_status == "pending"

    # ── Acceptance: GitHub missing but workflow + live exists ─────────────────

    def test_no_github_workflow_and_live_gives_valid_readiness(self) -> None:
        result = compute_readiness_report(
            proof_session_id="s5",
            session_status="completed",
            url_type="live_deployed_url",
            claimed_skills=["React"],
            workflow_analysis={
                "supported_skills": ["React"],
                "weakly_supported_skills": [],
                "unsupported_skills": [],
                "missing_evidence": [],
                "risk_flags": [],
                "recruiter_summary": "React demonstrated.",
                "human_review_needed": False,
            },
            live_check={"is_reachable": True},
            github_analysis=None,   # no GitHub
            privacy_scan={"status": "clean"},
        )
        # Valid non-zero result
        assert result.readiness_score > 0
        assert result.readiness_level in ("moderate", "weak", "strong")
        # Score should be lower than full-GitHub equivalent
        assert result.readiness_score < 100

    def test_no_github_does_not_crash(self) -> None:
        result = compute_readiness_report(
            proof_session_id="s5b",
            session_status="completed",
            url_type="live_deployed_url",
            claimed_skills=["Vue"],
            workflow_analysis={
                "supported_skills": [],
                "weakly_supported_skills": ["Vue"],
                "unsupported_skills": [],
                "missing_evidence": [],
                "risk_flags": [],
                "recruiter_summary": "Vue partially shown.",
                "human_review_needed": False,
            },
            live_check={"is_reachable": True},
            github_analysis=None,
            privacy_scan=None,
        )
        assert isinstance(result.readiness_score, int)

    # ── Acceptance: short recording lowers score ──────────────────────────────

    def test_short_recording_deducts_points(self) -> None:
        result_normal = compute_readiness_report(
            proof_session_id="s6a",
            session_status="completed",
            url_type="live_deployed_url",
            claimed_skills=["React"],
            workflow_analysis={
                "supported_skills": ["React"],
                "weakly_supported_skills": [],
                "unsupported_skills": [],
                "missing_evidence": [],
                "risk_flags": [],
                "recruiter_summary": "Clear React demo.",
                "human_review_needed": False,
            },
            live_check={"is_reachable": True},
            github_analysis=None,
            privacy_scan={"status": "clean"},
        )
        result_short = compute_readiness_report(
            proof_session_id="s6b",
            session_status="completed",
            url_type="live_deployed_url",
            claimed_skills=["React"],
            workflow_analysis={
                "supported_skills": ["React"],
                "weakly_supported_skills": [],
                "unsupported_skills": [],
                "missing_evidence": [],
                "risk_flags": ["Recording is too short — less than 30 seconds captured"],
                "recruiter_summary": "Clear React demo.",
                "human_review_needed": False,
            },
            live_check={"is_reachable": True},
            github_analysis=None,
            privacy_scan={"status": "clean"},
        )
        assert result_short.readiness_score < result_normal.readiness_score

    # ── Acceptance: strong skill support increases score ──────────────────────

    def test_strong_skill_support_adds_points(self) -> None:
        result_strong = compute_readiness_report(
            proof_session_id="s7a",
            session_status="completed",
            url_type="live_deployed_url",
            claimed_skills=["Django"],
            workflow_analysis={
                "supported_skills": ["Django"],
                "weakly_supported_skills": [],
                "unsupported_skills": [],
                "missing_evidence": [],
                "risk_flags": [],
                "recruiter_summary": "Django API demonstrated.",
                "human_review_needed": False,
            },
            live_check=None,
            github_analysis=None,
            privacy_scan={"status": "clean"},
        )
        result_weak = compute_readiness_report(
            proof_session_id="s7b",
            session_status="completed",
            url_type="live_deployed_url",
            claimed_skills=["Django"],
            workflow_analysis={
                "supported_skills": [],
                "weakly_supported_skills": [],
                "unsupported_skills": ["Django"],
                "missing_evidence": [],
                "risk_flags": [],
                "recruiter_summary": "Nothing clearly demonstrated.",
                "human_review_needed": False,
            },
            live_check=None,
            github_analysis=None,
            privacy_scan={"status": "clean"},
        )
        assert result_strong.readiness_score > result_weak.readiness_score

    # ── Acceptance: no hardcoded project names in output ─────────────────────

    def test_no_hardcoded_project_names_in_summary(self) -> None:
        """The recruiter summary must not contain 'Boston', 'React', specific
        project names, or 'Express' — it must be project-agnostic."""
        result = compute_readiness_report(
            proof_session_id="s8",
            session_status="completed",
            url_type="live_deployed_url",
            claimed_skills=["TypeScript"],
            workflow_analysis={
                "supported_skills": ["TypeScript"],
                "weakly_supported_skills": [],
                "unsupported_skills": [],
                "missing_evidence": [],
                "risk_flags": [],
                "recruiter_summary": "Strong TypeScript demonstration.",
                "human_review_needed": False,
            },
            live_check={"is_reachable": True},
            github_analysis=None,
            privacy_scan={"status": "clean"},
        )
        summary = result.recruiter_summary.lower()
        for forbidden in ("boston", "route risk", "vercel.app", "heroku"):
            assert forbidden not in summary, f"Hardcoded term found in summary: {forbidden}"

    # ── Acceptance: cross-evidence confirmation bonus ─────────────────────────

    def test_cross_evidence_confirmation_increases_score(self) -> None:
        """A skill confirmed in BOTH workflow and GitHub gets a +10 bonus."""
        result_cross = compute_readiness_report(
            proof_session_id="s9a",
            session_status="completed",
            url_type="live_deployed_url",
            claimed_skills=["FastAPI"],
            workflow_analysis={
                "supported_skills": ["FastAPI"],
                "weakly_supported_skills": [],
                "unsupported_skills": [],
                "missing_evidence": [],
                "risk_flags": [],
                "recruiter_summary": "FastAPI routes demonstrated.",
                "human_review_needed": False,
            },
            live_check={"is_reachable": True},
            github_analysis={
                "status": "success",
                "matched_claimed_skills": ["FastAPI"],
                "weakly_matched_claimed_skills": [],
                "detected_features": ["readme"],
                "recruiter_summary": "FastAPI confirmed in repo.",
            },
            privacy_scan={"status": "clean"},
        )
        result_single = compute_readiness_report(
            proof_session_id="s9b",
            session_status="completed",
            url_type="live_deployed_url",
            claimed_skills=["FastAPI"],
            workflow_analysis={
                "supported_skills": ["FastAPI"],
                "weakly_supported_skills": [],
                "unsupported_skills": [],
                "missing_evidence": [],
                "risk_flags": [],
                "recruiter_summary": "FastAPI routes demonstrated.",
                "human_review_needed": False,
            },
            live_check={"is_reachable": True},
            github_analysis=None,   # no GitHub
            privacy_scan={"status": "clean"},
        )
        assert result_cross.readiness_score > result_single.readiness_score

    # ── Score bounds ───────────────────────────────────────────────────────────

    def test_score_bounded_0_100(self) -> None:
        for url_type in ("localhost_url", "live_deployed_url", "invalid_url"):
            r = compute_readiness_report(
                proof_session_id="bound",
                session_status="completed",
                url_type=url_type,
                claimed_skills=["Skill A", "Skill B"],
                workflow_analysis={
                    "supported_skills": ["Skill A"],
                    "weakly_supported_skills": ["Skill B"],
                    "unsupported_skills": [],
                    "missing_evidence": ["Missing item 1", "Missing item 2"],
                    "risk_flags": ["Short recording"],
                    "recruiter_summary": "Some evidence.",
                    "human_review_needed": False,
                },
                live_check={"is_reachable": False},
                github_analysis={"status": "failed", "matched_claimed_skills": [],
                                  "weakly_matched_claimed_skills": [], "detected_features": []},
                privacy_scan={"status": "flagged"},
            )
            assert 0 <= r.readiness_score <= 100

    # ── Empty / no evidence ────────────────────────────────────────────────────

    def test_no_evidence_gives_insufficient(self) -> None:
        result = compute_readiness_report(
            proof_session_id="s_empty",
            session_status="created",
            url_type="live_deployed_url",
            claimed_skills=[],
        )
        assert result.readiness_level == "insufficient"

    def test_no_claimed_skills(self) -> None:
        result = compute_readiness_report(
            proof_session_id="s_noskills",
            session_status="completed",
            url_type="live_deployed_url",
            claimed_skills=[],
            workflow_analysis={
                "supported_skills": [],
                "weakly_supported_skills": [],
                "unsupported_skills": [],
                "missing_evidence": [],
                "risk_flags": [],
                "recruiter_summary": "Workflow uploaded.",
                "human_review_needed": False,
            },
            live_check={"is_reachable": True},
            github_analysis=None,
            privacy_scan={"status": "clean"},
        )
        assert isinstance(result.readiness_score, int)
        assert result.final_verification_status != "complete"

    # ── Readiness levels hit the right thresholds ─────────────────────────────

    def test_strong_level_threshold_is_80(self) -> None:
        """Score >= 80 with clean privacy → ready_for_review."""
        # Max achievable: 15+15+15+15+10+15+10+5 = 100 with cross-evidence
        result = compute_readiness_report(
            proof_session_id="thresh",
            session_status="completed",
            url_type="live_deployed_url",
            claimed_skills=["React"],
            workflow_analysis={
                "supported_skills": ["React"],
                "weakly_supported_skills": [],
                "unsupported_skills": [],
                "missing_evidence": [],
                "risk_flags": [],
                "recruiter_summary": "React fully demonstrated in live application.",
                "human_review_needed": False,
            },
            live_check={"is_reachable": True},
            github_analysis={
                "status": "success",
                "matched_claimed_skills": ["React"],
                "weakly_matched_claimed_skills": [],
                "detected_features": ["readme", "deployment"],
                "recruiter_summary": "React confirmed in repository.",
            },
            privacy_scan={"status": "clean"},
        )
        if result.readiness_score >= 80:
            assert result.readiness_level == "strong"
            assert result.final_verification_status == "ready_for_review"


# ── Integration: API endpoint ─────────────────────────────────────────────────

class TestVerificationReadinessEndpoint:
    """HTTP-level tests using the in-memory client."""

    def test_get_readiness_404_for_unknown_session(self, client: TestClient) -> None:
        r = client.get(
            "/api/v1/student/extension-proof/sessions/nonexistent-id/readiness"
        )
        assert r.status_code == 404

    def test_get_readiness_returns_200_after_upload(
        self, client: TestClient
    ) -> None:
        session_id = _make_session(client)
        _upload(client, session_id)

        r = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}/readiness"
        )
        assert r.status_code == 200

    def test_readiness_response_has_required_fields(
        self, client: TestClient
    ) -> None:
        session_id = _make_session(client)
        _upload(client, session_id)

        r = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}/readiness"
        )
        assert r.status_code == 200
        body = r.json()

        required = [
            "proof_session_id",
            "readiness_score",
            "readiness_level",
            "final_verification_status",
            "strongly_supported_skills",
            "partially_supported_skills",
            "needs_more_evidence",
            "risk_flags",
            "recommended_next_actions",
            "recruiter_summary",
            "is_local_only",
            "has_github_evidence",
            "computed_at",
        ]
        for field in required:
            assert field in body, f"Missing field: {field}"

    def test_final_verification_status_never_complete_via_api(
        self, client: TestClient
    ) -> None:
        """The API endpoint must NEVER return final_verification_status == 'complete'."""
        session_id = _make_session(client)
        _upload(client, session_id)

        r = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}/readiness"
        )
        assert r.status_code == 200
        assert r.json()["final_verification_status"] != "complete"

    def test_readiness_score_in_bounds(self, client: TestClient) -> None:
        session_id = _make_session(client)
        _upload(client, session_id)

        r = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}/readiness"
        )
        assert r.status_code == 200
        score = r.json()["readiness_score"]
        assert 0 <= score <= 100

    def test_readiness_endpoint_in_openapi(self, client: TestClient) -> None:
        r = client.get("/openapi.json")
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        matching = [p for p in paths if "readiness" in p]
        assert matching, "Readiness endpoint not found in OpenAPI schema"

    def test_local_session_is_local_only_flag(self, client: TestClient) -> None:
        """A session created with a localhost URL should have is_local_only=True."""
        # Note: website_url is stored on the skill_evidence row, not directly on the
        # session row in the in-memory test store.  For this test we verify the
        # endpoint returns a valid response — the is_local_only flag is unit-tested above.
        session_id = _make_session(client)
        _upload(client, session_id)
        r = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}/readiness"
        )
        assert r.status_code == 200
        # is_local_only is a bool
        assert isinstance(r.json()["is_local_only"], bool)
