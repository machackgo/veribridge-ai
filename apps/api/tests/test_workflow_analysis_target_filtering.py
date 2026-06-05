"""
Tests for workflow analysis target-site filtering (v2).

Verifies that:
- Only target-proof-website events are used for skill evidence and recruiter summary.
- VeriBridge internal dashboard pages (localhost:3000/dashboard/*) are filtered as noise.
- Supabase dashboard URLs are filtered as noise.
- Unrelated browser tabs are filtered as noise.
- GitHub pages are classified as supporting evidence (not noise, not target).
- Recruiter summary never mentions noise URLs.
- Short recording produces a meaningful risk flag.
- Page-load-only produces an appropriate risk flag (no overclaiming).
- noise_filtered_count / target_site_pages_count are returned correctly.
- Public-safe summary does not leak private/internal URLs.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.extension_proof_workflow_analysis_service import (
    _analyze_workflow,
    _classify_url,
    _is_veribridge_internal,
    _safe_netloc,
)

# ── Constants ─────────────────────────────────────────────────────────────────

DEMO_USER_ID = "00000000-0000-0000-0000-000000000099"

TARGET_URL      = "https://mlexplainer.streamlit.app"
GITHUB_URL      = "https://github.com/user/ml-explainer"
SUPABASE_URL    = "https://app.supabase.io/project/abc123/editor"
VB_DASH_URL     = "http://localhost:3000/dashboard/profile"
VB_PASSPORT_URL = "http://localhost:3000/dashboard/passport/skills"
STACKOVERFLOW   = "https://stackoverflow.com/questions/123456"
LOCALHOST_APP   = "http://localhost:8501"
LOCAL_VERIBRIDGE_APP = "http://localhost:3000"


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


def _make_session(client: TestClient, mem_store: dict, proof_data: dict) -> str:
    """Create an extension-proof session pre-loaded with proof_data."""
    from app.services.extension_proof_workflow_analysis_service import _SESSION_TABLE
    import uuid

    session_id = str(uuid.uuid4())
    mem_store.setdefault(_SESSION_TABLE, {})[session_id] = {
        "id": session_id,
        "user_id": DEMO_USER_ID,
        "status": "uploaded_pending_analysis",
        "proof_data": proof_data,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }
    return session_id


def _mixed_proof_data(
    target_url: str = TARGET_URL,
    include_github: bool = True,
    include_supabase: bool = True,
    include_vb_dashboard: bool = True,
    include_unrelated: bool = True,
    duration_secs: int = 180,
) -> dict:
    """Build proof_data with a mixed timeline: target + GitHub + noise."""
    from datetime import datetime, timezone, timedelta

    start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    stop  = start + timedelta(seconds=duration_secs)

    events = [
        # ── Target site (should be included) ─────────────────────────────────
        {
            "type": "page_visit",
            "page_url": target_url,
            "page_title": "MLExplainer — Streamlit",
        },
        {
            "type": "click",
            "page_url": target_url,
            "element_text": "Run Prediction",
        },
        {
            "type": "input_change",
            "page_url": target_url,
            "element_id": "input-features",
        },
        {
            "type": "page_visit",
            "page_url": target_url + "/results",
            "page_title": "MLExplainer — Results",
        },
    ]

    if include_github:
        events += [
            {
                "type": "page_visit",
                "page_url": GITHUB_URL,
                "page_title": "ml-explainer — GitHub",
            },
            {
                "type": "page_visit",
                "page_url": GITHUB_URL + "/blob/main/app.py",
                "page_title": "app.py — GitHub",
            },
        ]

    if include_supabase:
        events += [
            {
                "type": "page_visit",
                "page_url": SUPABASE_URL,
                "page_title": "Supabase — SQL Editor",
            },
            {
                "type": "click",
                "page_url": SUPABASE_URL,
                "element_text": "Run Query",
            },
        ]

    if include_vb_dashboard:
        events += [
            {
                "type": "page_visit",
                "page_url": VB_DASH_URL,
                "page_title": "VeriBridge — Profile",
            },
            {
                "type": "page_visit",
                "page_url": VB_PASSPORT_URL,
                "page_title": "VeriBridge — Passport",
            },
        ]

    if include_unrelated:
        events += [
            {
                "type": "page_visit",
                "page_url": STACKOVERFLOW,
                "page_title": "Stack Overflow — How to use Streamlit",
            },
        ]

    return {
        "workflow_events": events,
        "started_at": start.isoformat(),
        "stopped_at": stop.isoformat(),
    }


# ── Unit tests: _classify_url ─────────────────────────────────────────────────

class TestClassifyUrl:

    def test_target_url_classified_as_target(self):
        target_netloc = _safe_netloc(TARGET_URL)
        assert _classify_url(TARGET_URL, target_netloc, None) == "target"

    def test_target_subpage_classified_as_target(self):
        target_netloc = _safe_netloc(TARGET_URL)
        assert _classify_url(TARGET_URL + "/results", target_netloc, None) == "target"

    def test_github_classified_as_supporting_when_github_configured(self):
        github_netloc = _safe_netloc(GITHUB_URL)
        assert _classify_url(GITHUB_URL, "", github_netloc) == "supporting"

    def test_github_classified_as_noise_when_no_github_url(self):
        assert _classify_url(GITHUB_URL, "", None) == "noise"

    def test_supabase_classified_as_noise(self):
        assert _classify_url(SUPABASE_URL, "", None) == "noise"

    def test_supabase_studio_classified_as_noise(self):
        assert _classify_url(
            "https://studio.supabase.com/project/abc", "", None
        ) == "noise"

    def test_veribridge_dashboard_profile_classified_as_noise(self):
        assert _classify_url(VB_DASH_URL, "", None) == "noise"

    def test_veribridge_passport_classified_as_noise(self):
        assert _classify_url(VB_PASSPORT_URL, "", None) == "noise"

    def test_localhost_target_app_classified_as_target(self):
        target_netloc = _safe_netloc(LOCALHOST_APP)
        assert _classify_url(LOCALHOST_APP, target_netloc, None) == "target"

    def test_localhost_veribridge_port_classified_as_noise(self):
        assert _classify_url(VB_DASH_URL, "localhost:8501", None) == "noise"

    def test_submitted_veribridge_localhost_hash_route_classified_as_target(self):
        target_netloc = _safe_netloc(LOCAL_VERIBRIDGE_APP)
        assert _classify_url(f"{LOCAL_VERIBRIDGE_APP}/#platform", target_netloc, None) == "target"

    def test_submitted_veribridge_localhost_path_classified_as_target(self):
        target_netloc = _safe_netloc(LOCAL_VERIBRIDGE_APP)
        assert _classify_url(f"{LOCAL_VERIBRIDGE_APP}/students", target_netloc, None) == "target"

    def test_submitted_veribridge_localhost_dashboard_classified_as_target(self):
        target_netloc = _safe_netloc(LOCAL_VERIBRIDGE_APP)
        assert _classify_url(VB_DASH_URL, target_netloc, None) == "target"

    def test_unrelated_tab_classified_as_noise(self):
        assert _classify_url(STACKOVERFLOW, _safe_netloc(TARGET_URL), None) == "noise"

    def test_chrome_internal_classified_as_noise(self):
        assert _classify_url("chrome://extensions/", "", None) == "noise"

    def test_empty_url_classified_as_noise(self):
        assert _classify_url("", "", None) == "noise"


# ── Unit tests: _is_veribridge_internal ───────────────────────────────────────

class TestIsVeriBridgeInternal:

    def test_dashboard_profile_is_internal(self):
        assert _is_veribridge_internal(VB_DASH_URL) is True

    def test_dashboard_passport_is_internal(self):
        assert _is_veribridge_internal(VB_PASSPORT_URL) is True

    def test_dashboard_root_is_internal(self):
        assert _is_veribridge_internal("http://localhost:3000/dashboard") is True

    def test_dashboard_subpath_is_internal(self):
        assert _is_veribridge_internal("http://localhost:3000/dashboard/skills") is True

    def test_target_app_is_not_internal(self):
        assert _is_veribridge_internal(TARGET_URL) is False

    def test_localhost_app_is_not_internal(self):
        assert _is_veribridge_internal(LOCALHOST_APP) is False

    def test_vb_home_is_not_internal(self):
        # Root "/" is NOT a dashboard path
        assert _is_veribridge_internal("http://localhost:3000/") is False


# ── Unit tests: _analyze_workflow (target filtering) ─────────────────────────

class TestAnalyzeWorkflowTargetFiltering:

    def _run(
        self,
        proof_data: dict,
        target_url: str = TARGET_URL,
        github_url: str | None = GITHUB_URL,
        claimed_skills: list[str] | None = None,
        proof_objective: str = "Demonstrate ML explainability Streamlit app",
        url_type: str = "live_deployed_url",
    ) -> dict:
        return _analyze_workflow(
            proof_data=proof_data,
            claimed_skills=claimed_skills or ["Streamlit", "Python", "Machine Learning"],
            proof_objective=proof_objective,
            original_url=target_url,
            url_type=url_type,
            github_url=github_url,
        )

    # ── Noise filtering ───────────────────────────────────────────────────────

    def test_supabase_url_filtered_to_noise(self):
        """Supabase dashboard events must be counted as noise."""
        data = _mixed_proof_data(
            include_github=False, include_vb_dashboard=False, include_unrelated=False
        )
        result = self._run(data)
        # Supabase events should be noise
        assert result["noise_filtered_count"] > 0

    def test_veribridge_dashboard_filtered_to_noise(self):
        """VeriBridge internal dashboard URLs must be classified as noise."""
        data = _mixed_proof_data(
            include_github=False, include_supabase=False, include_unrelated=False
        )
        result = self._run(data)
        assert result["noise_filtered_count"] >= 2  # profile + passport

    def test_unrelated_tabs_filtered_to_noise(self):
        """Unrelated browser tabs (Stack Overflow, etc.) must be noise."""
        data = _mixed_proof_data(
            include_github=False, include_supabase=False, include_vb_dashboard=False
        )
        result = self._run(data)
        assert result["noise_filtered_count"] >= 1

    def test_target_domain_preserved(self):
        """Events on the target domain must be classified as target, not noise."""
        data = _mixed_proof_data()
        result = self._run(data)
        assert result["target_site_pages_count"] >= 2  # at least / and /results

    def test_localhost_same_origin_hash_and_paths_preserved(self):
        """Internal navigation under submitted localhost origin stays target evidence."""
        from datetime import datetime, timezone, timedelta
        start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        stop = start + timedelta(seconds=150)
        proof_data = {
            "workflow_events": [
                {"type": "page_visit", "page_url": LOCAL_VERIBRIDGE_APP, "page_title": "VeriBridge"},
                {"type": "page_visit", "page_url": f"{LOCAL_VERIBRIDGE_APP}/#platform", "page_title": "VeriBridge — Platform"},
                {"type": "page_visit", "page_url": f"{LOCAL_VERIBRIDGE_APP}/students", "page_title": "VeriBridge — Students"},
                {"type": "page_visit", "page_url": f"{LOCAL_VERIBRIDGE_APP}/dashboard/profile", "page_title": "VeriBridge — Profile"},
                {"type": "click", "page_url": f"{LOCAL_VERIBRIDGE_APP}/students", "element_text": "Students"},
                {"type": "page_visit", "page_url": "https://google.com/search?q=veribridge", "page_title": "Google"},
            ],
            "started_at": start.isoformat(),
            "stopped_at": stop.isoformat(),
        }

        result = self._run(
            proof_data,
            target_url=LOCAL_VERIBRIDGE_APP,
            github_url=None,
            claimed_skills=["Next.js", "React"],
            proof_objective="Demonstrate local VeriBridge navigation and workflow recording",
            url_type="localhost_url",
        )

        assert result["target_site_pages_count"] == 4
        assert result["noise_filtered_count"] == 1
        summary = result["recruiter_summary"].lower()
        assert "google" not in summary
        actions_text = " ".join(result["demonstrated_actions"]).lower()
        assert "google" not in actions_text

    def test_github_classified_as_supporting(self):
        """GitHub events must be supporting evidence, not target and not noise."""
        data = _mixed_proof_data(
            include_supabase=False, include_vb_dashboard=False, include_unrelated=False
        )
        result = self._run(data)
        assert result["supporting_evidence_count"] >= 1

    def test_github_classified_as_noise_when_no_github_url_configured(self):
        """GitHub events become noise when no github_url is configured."""
        data = _mixed_proof_data(
            include_supabase=False, include_vb_dashboard=False, include_unrelated=False
        )
        result = self._run(data, github_url=None)
        # Without github_url, GitHub pages → noise
        assert result["noise_filtered_count"] >= 1  # GitHub pages become noise

    # ── target_website field ──────────────────────────────────────────────────

    def test_target_website_field_set(self):
        """target_website must contain the domain of the proof target."""
        data = _mixed_proof_data()
        result = self._run(data)
        assert "mlexplainer.streamlit.app" in result["target_website"]

    # ── Recruiter summary must NOT mention noise ──────────────────────────────

    def test_recruiter_summary_does_not_mention_supabase(self):
        """Recruiter summary must NOT mention Supabase URLs."""
        data = _mixed_proof_data()
        result = self._run(data)
        summary = result["recruiter_summary"].lower()
        assert "supabase" not in summary, (
            "Supabase must not appear in the recruiter summary"
        )

    def test_recruiter_summary_does_not_mention_veribridge_dashboard(self):
        """Recruiter summary must NOT mention VeriBridge internal dashboard pages."""
        data = _mixed_proof_data()
        result = self._run(data)
        summary = result["recruiter_summary"].lower()
        assert "dashboard/profile" not in summary
        assert "dashboard/passport" not in summary
        assert "veribridge" not in summary or "veribridge" in summary.lower() and result["recruiter_summary"].count("VeriBridge") <= 0

    def test_recruiter_summary_does_not_mention_stackoverflow(self):
        """Recruiter summary must NOT mention unrelated browser tabs."""
        data = _mixed_proof_data()
        result = self._run(data)
        summary = result["recruiter_summary"].lower()
        assert "stackoverflow" not in summary

    def test_recruiter_summary_does_not_include_visited_n_pages_with_noise(self):
        """Recruiter summary must NOT say 'visited N pages including GitHub, Supabase...'."""
        data = _mixed_proof_data()
        result = self._run(data)
        summary = result["recruiter_summary"]
        # Should NOT list noise pages in page counts
        assert "Supabase" not in summary
        assert "Stack Overflow" not in summary
        assert "localhost:3000/dashboard" not in summary

    def test_recruiter_summary_mentions_target_app(self):
        """Recruiter summary must mention the target application domain."""
        data = _mixed_proof_data()
        result = self._run(data)
        assert "mlexplainer.streamlit.app" in result["recruiter_summary"]

    def test_recruiter_summary_mentions_github_when_configured(self):
        """Recruiter summary should acknowledge GitHub supporting evidence."""
        data = _mixed_proof_data(
            include_supabase=False, include_vb_dashboard=False, include_unrelated=False
        )
        result = self._run(data)
        summary = result["recruiter_summary"].lower()
        assert "github" in summary

    # ── Demonstrated actions must be target-site-only ─────────────────────────

    def test_demonstrated_actions_does_not_list_noise_pages(self):
        """demonstrated_actions must not list Supabase or VeriBridge dashboard pages."""
        data = _mixed_proof_data()
        result = self._run(data)
        actions_text = " ".join(result["demonstrated_actions"]).lower()
        assert "supabase" not in actions_text
        assert "dashboard/profile" not in actions_text
        assert "stackoverflow" not in actions_text

    def test_demonstrated_actions_lists_target_app(self):
        """demonstrated_actions must show the target application was loaded."""
        data = _mixed_proof_data()
        result = self._run(data)
        actions_text = " ".join(result["demonstrated_actions"]).lower()
        assert "mlexplainer.streamlit.app" in actions_text or "target application" in actions_text

    # ── Risk flags ────────────────────────────────────────────────────────────

    def test_short_recording_produces_risk_flag(self):
        """A short recording must produce a meaningful risk flag."""
        data = _mixed_proof_data(duration_secs=15)
        result = self._run(data)
        flags_text = " ".join(result["risk_flags"]).lower()
        assert "short" in flags_text or "second" in flags_text, (
            "Short recording must produce a risk flag"
        )

    def test_page_load_only_produces_risk_flag(self):
        """If only page loads (no clicks/inputs), a risk flag must note page-load-only."""
        from datetime import datetime, timezone, timedelta
        start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        stop = start + timedelta(seconds=120)
        proof_data = {
            "workflow_events": [
                {"type": "page_visit", "page_url": TARGET_URL, "page_title": "MLExplainer"},
            ],
            "started_at": start.isoformat(),
            "stopped_at": stop.isoformat(),
        }
        result = self._run(proof_data)
        flags_text = " ".join(result["risk_flags"]).lower()
        assert "page load" in flags_text or "interaction" in flags_text or "click" in flags_text, (
            "Page-load-only session must produce a risk flag about missing interactions"
        )

    def test_risk_flag_does_not_mention_noise_urls(self):
        """Risk flags must not include Supabase or VeriBridge internal page names."""
        data = _mixed_proof_data(duration_secs=30)
        result = self._run(data)
        flags_text = " ".join(result["risk_flags"]).lower()
        assert "supabase" not in flags_text
        assert "dashboard/profile" not in flags_text

    # ── Workflow summary ──────────────────────────────────────────────────────

    def test_workflow_summary_is_target_site_focused(self):
        """Workflow summary must describe the target site, not browser history."""
        data = _mixed_proof_data()
        result = self._run(data)
        summary = result["workflow_summary"].lower()
        # Must describe target
        assert "mlexplainer.streamlit.app" in summary or "streamlit" in summary
        # Must NOT describe noise
        assert "supabase" not in summary
        assert "dashboard/profile" not in summary

    # ── Raw timeline preserved internally ─────────────────────────────────────

    def test_noise_count_stored_internally(self):
        """noise_filtered_count must be stored in the result dict."""
        data = _mixed_proof_data()
        result = self._run(data)
        assert "noise_filtered_count" in result
        assert isinstance(result["noise_filtered_count"], int)
        assert result["noise_filtered_count"] > 0

    def test_target_site_pages_count_accurate(self):
        """target_site_pages_count should count only target site page visits."""
        from datetime import datetime, timezone, timedelta
        start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        stop = start + timedelta(seconds=120)
        proof_data = {
            "workflow_events": [
                {"type": "page_visit", "page_url": TARGET_URL,          "page_title": "App"},
                {"type": "page_visit", "page_url": TARGET_URL + "/docs", "page_title": "App Docs"},
                {"type": "page_visit", "page_url": SUPABASE_URL,         "page_title": "Supabase"},
                {"type": "page_visit", "page_url": VB_DASH_URL,          "page_title": "VB"},
                {"type": "page_visit", "page_url": STACKOVERFLOW,        "page_title": "SO"},
            ],
            "started_at": start.isoformat(),
            "stopped_at": stop.isoformat(),
        }
        result = self._run(proof_data)
        assert result["target_site_pages_count"] == 2   # only TARGET_URL and /docs
        assert result["noise_filtered_count"] == 3      # Supabase + VB + SO

    # ── Skill evidence based on target site only ──────────────────────────────

    def test_streamlit_supported_from_target_url(self):
        """Streamlit skill should be supported from streamlit.app target URL."""
        from datetime import datetime, timezone, timedelta
        start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        stop = start + timedelta(seconds=120)
        proof_data = {
            "workflow_events": [
                {"type": "page_visit", "page_url": TARGET_URL, "page_title": "MLExplainer"},
                {"type": "click",      "page_url": TARGET_URL, "element_text": "Predict"},
            ],
            "started_at": start.isoformat(),
            "stopped_at": stop.isoformat(),
        }
        result = self._run(
            proof_data,
            claimed_skills=["Streamlit", "Python"],
            url_type="live_deployed_url",
        )
        # TARGET URL is streamlit.app → Streamlit inferred
        all_evidence = result["supported_skills"] + result["weakly_supported_skills"]
        assert any("Streamlit" in s for s in all_evidence), (
            "Streamlit should be supported from the streamlit.app target URL"
        )

    # ── Privacy / public safety ───────────────────────────────────────────────

    def test_recruiter_summary_does_not_expose_internal_routes(self):
        """Public recruiter summary must not expose VeriBridge internal routes."""
        data = _mixed_proof_data()
        result = self._run(data)
        sensitive = [
            "localhost:3000/dashboard",
            "dashboard/passport",
            "dashboard/profile",
            "supabase.io",
            "supabase.com",
            "app.supabase",
        ]
        summary = result["recruiter_summary"]
        for pattern in sensitive:
            assert pattern not in summary, (
                f"Private route '{pattern}' must not appear in recruiter summary"
            )

    def test_missing_evidence_does_not_expose_internal_routes(self):
        """missing_evidence list must not expose internal VeriBridge routes."""
        data = _mixed_proof_data()
        result = self._run(data)
        missing_text = " ".join(result["missing_evidence"])
        sensitive = ["localhost:3000/dashboard", "supabase.io", "dashboard/profile"]
        for pattern in sensitive:
            assert pattern not in missing_text


# ── HTTP endpoint tests ───────────────────────────────────────────────────────

class TestWorkflowAnalysisEndpoint:

    def test_endpoint_returns_noise_filtered_count(
        self, client: TestClient, mem_store: dict
    ):
        """The analyze/workflow endpoint must return noise_filtered_count."""
        session_id = _make_session(client, mem_store, _mixed_proof_data())

        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/workflow",
            json={
                "claimed_skills": ["Streamlit", "Python"],
                "proof_objective": "ML explainability demo",
                "original_url": TARGET_URL,
                "url_type": "live_deployed_url",
                "github_url": GITHUB_URL,
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "noise_filtered_count" in data
        assert data["noise_filtered_count"] > 0

    def test_endpoint_returns_target_site_pages_count(
        self, client: TestClient, mem_store: dict
    ):
        """The analyze/workflow endpoint must return target_site_pages_count."""
        session_id = _make_session(client, mem_store, _mixed_proof_data())

        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/workflow",
            json={
                "claimed_skills": ["Streamlit", "Python"],
                "proof_objective": "ML explainability demo",
                "original_url": TARGET_URL,
                "url_type": "live_deployed_url",
                "github_url": GITHUB_URL,
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "target_site_pages_count" in data
        assert data["target_site_pages_count"] >= 2

    def test_endpoint_recruiter_summary_clean_from_noise(
        self, client: TestClient, mem_store: dict
    ):
        """Endpoint recruiter_summary must not contain noise URLs."""
        session_id = _make_session(client, mem_store, _mixed_proof_data())

        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/workflow",
            json={
                "claimed_skills": ["Streamlit", "Python"],
                "proof_objective": "ML explainability demo",
                "original_url": TARGET_URL,
                "url_type": "live_deployed_url",
                "github_url": GITHUB_URL,
            },
        )
        assert r.status_code == 200, r.text
        summary = r.json()["recruiter_summary"]
        assert "supabase" not in summary.lower()
        assert "dashboard/profile" not in summary
        assert "stackoverflow" not in summary.lower()

    def test_endpoint_returns_target_website_field(
        self, client: TestClient, mem_store: dict
    ):
        """target_website field must be returned in the response."""
        session_id = _make_session(client, mem_store, _mixed_proof_data())

        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/workflow",
            json={
                "claimed_skills": ["Streamlit"],
                "proof_objective": "Demo",
                "original_url": TARGET_URL,
                "url_type": "live_deployed_url",
                "github_url": None,
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "target_website" in data
        assert "mlexplainer.streamlit.app" in data["target_website"]


# ── Localhost target site tests ───────────────────────────────────────────────

class TestLocalhostTargetFiltering:
    """Verify filtering works correctly when target is a localhost app."""

    def _run_localhost(self, extra_events: list[dict] | None = None) -> dict:
        from datetime import datetime, timezone, timedelta
        start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        stop = start + timedelta(seconds=90)
        events = [
            {"type": "page_visit", "page_url": LOCALHOST_APP, "page_title": "My App"},
            {"type": "click",      "page_url": LOCALHOST_APP, "element_text": "Submit"},
        ]
        if extra_events:
            events.extend(extra_events)
        proof_data = {
            "workflow_events": events,
            "started_at": start.isoformat(),
            "stopped_at": stop.isoformat(),
        }
        return _analyze_workflow(
            proof_data=proof_data,
            claimed_skills=["FastAPI", "Python"],
            proof_objective="Backend API demo",
            original_url=LOCALHOST_APP,
            url_type="localhost_url",
            github_url=None,
        )

    def test_localhost_target_events_classified_correctly(self):
        result = self._run_localhost()
        assert result["target_site_pages_count"] >= 1

    def test_veribridge_dashboard_noise_on_localhost_target(self):
        """Even when target is localhost:8501, VB dashboard (localhost:3000) is noise."""
        result = self._run_localhost(extra_events=[
            {"type": "page_visit", "page_url": VB_DASH_URL, "page_title": "VB"},
        ])
        assert result["noise_filtered_count"] >= 1

    def test_localhost_target_recruiter_summary_no_noise(self):
        result = self._run_localhost(extra_events=[
            {"type": "page_visit", "page_url": VB_DASH_URL,    "page_title": "VB Profile"},
            {"type": "page_visit", "page_url": SUPABASE_URL,   "page_title": "Supabase"},
        ])
        summary = result["recruiter_summary"]
        assert "dashboard/profile" not in summary
        assert "supabase" not in summary.lower()


# ── Chatbot / HuggingChat scoring tests ──────────────────────────────────────

HUGGINGCHAT_URL = "https://huggingface.co/chat/"


def _make_huggingchat_proof(duration_secs: int = 120, include_input: bool = False) -> dict:
    """Build minimal proof_data for a HuggingChat workflow."""
    from datetime import datetime, timezone, timedelta

    start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    stop = start + timedelta(seconds=duration_secs)

    events: list[dict] = [
        {
            "type": "page_visit",
            "page_url": HUGGINGCHAT_URL,
            "page_title": "HuggingChat",
        },
    ]
    if include_input:
        events.append({
            "type": "input_change",
            "page_url": HUGGINGCHAT_URL,
            "element_id": "message-input",
        })
        events.append({
            "type": "click",
            "page_url": HUGGINGCHAT_URL,
            "element_text": "Send",
        })

    return {
        "workflow_events": events,
        "started_at": start.isoformat(),
        "stopped_at": stop.isoformat(),
    }


def _run_chatbot_analysis(proof_data: dict, include_input: bool = False) -> dict:
    return _analyze_workflow(
        proof_data=proof_data,
        claimed_skills=["Natural Language Processing", "Chatbot UI", "Large Language Models", "React", "TypeScript"],
        proof_objective="Demonstrate HuggingChat chatbot UI",
        original_url=HUGGINGCHAT_URL,
        url_type="live_deployed_url",
        github_url=None,
    )


class TestChatbotWorkflowScoring:
    """Chatbot/LLM proof: page-load + chat UI visible must produce partial score."""

    def test_chatbot_page_load_gives_nonzero_score(self):
        """Target chatbot page loaded → evidence_strength_score > 0."""
        proof = _make_huggingchat_proof(duration_secs=120)
        result = _run_chatbot_analysis(proof)
        assert result["evidence_strength_score"] > 0, (
            f"Chatbot page load must give > 0 score, got {result['evidence_strength_score']}"
        )

    def test_chatbot_page_load_gives_partial_workflow(self):
        """Target chatbot page loaded → evidence_strength_score >= 40."""
        proof = _make_huggingchat_proof(duration_secs=120)
        result = _run_chatbot_analysis(proof)
        assert result["evidence_strength_score"] >= 40, (
            f"Chatbot page load must give >= 40 score, got {result['evidence_strength_score']}"
        )

    def test_chatbot_page_load_plus_input_gives_higher_score(self):
        """Target chatbot page + input interaction → score >= page-load-only score."""
        proof_page = _make_huggingchat_proof(duration_secs=120, include_input=False)
        proof_input = _make_huggingchat_proof(duration_secs=120, include_input=True)
        score_page = _run_chatbot_analysis(proof_page)["evidence_strength_score"]
        score_input = _run_chatbot_analysis(proof_input)["evidence_strength_score"]
        assert score_input >= score_page, (
            f"Input interaction must not lower score: page={score_page} input={score_input}"
        )

    def test_chatbot_target_events_classified_correctly(self):
        proof = _make_huggingchat_proof()
        result = _run_chatbot_analysis(proof)
        assert result["target_site_pages_count"] >= 1, "HuggingChat page_visit must be classified as target"

    def test_chatbot_adjust_runs_when_title_has_huggingchat(self):
        """_adjust_chatbot_workflow_score must fire when HuggingChat is in title."""
        from app.services.extension_proof_workflow_analysis_service import _adjust_chatbot_workflow_score
        score = _adjust_chatbot_workflow_score(
            20,
            page_count=1,
            input_count=0,
            click_count=0,
            target_titles=["HuggingChat"],
            evidence_text="",
            iao_patterns=[],
        )
        assert score >= 55, f"Chatbot title must boost score to >= 55, got {score}"

    def test_chatbot_adjust_runs_without_page_events_if_chat_in_text(self):
        """_adjust_chatbot_workflow_score must not bail when page_count=0 but chat content in text."""
        from app.services.extension_proof_workflow_analysis_service import _adjust_chatbot_workflow_score
        score = _adjust_chatbot_workflow_score(
            15,
            page_count=0,
            input_count=0,
            click_count=0,
            target_titles=[],
            evidence_text="huggingchat chat window visible with input field",
            iao_patterns=[],
        )
        assert score >= 35, f"Chat content in evidence text must give >= 35, got {score}"

    def test_chatbot_adjust_skips_when_no_chat_signals_and_no_page(self):
        """_adjust_chatbot_workflow_score must skip adjustment when no chat signals and page_count=0."""
        from app.services.extension_proof_workflow_analysis_service import _adjust_chatbot_workflow_score
        score = _adjust_chatbot_workflow_score(
            15,
            page_count=0,
            input_count=0,
            click_count=0,
            target_titles=[],
            evidence_text="some unrelated text here",
            iao_patterns=[],
        )
        assert score == 15, f"No chat signals + no page events must return original score 15, got {score}"


class TestQwenChatbotFiltering:
    """Qwen observations showing chatbot UI must not be blanket-filtered."""

    def test_qwen_chatbot_observations_not_filtered_when_no_dom_events(self):
        """HuggingChat Qwen obs must survive filter even when has_target_events=False."""
        from app.services.extension_proof_workflow_analysis_service import (
            _filter_visual_reasoning_summary_for_target,
        )
        summary = {
            "status": "analyzed",
            "frames_analyzed": 2,
            "observations": [
                {
                    "visual_summary": "The HuggingChat interface is open, showing a chat window with 'hi' typed.",
                    "visible_ui_elements": ["chat window", "input field"],
                    "detected_user_action": "user typed 'hi' in message input",
                    "confidence_score": 0.75,
                },
            ],
            "supported_signals": ["Chatbot UI"],
        }
        filtered = _filter_visual_reasoning_summary_for_target(
            summary,
            has_target_events=False,
            noise_hosts=[],
        )
        assert filtered is not None
        assert filtered.get("status") != "filtered_non_target_frame", (
            "HuggingChat chatbot observations must survive filter even without DOM events"
        )
        assert len(filtered.get("observations") or []) > 0, "Observations must be preserved"

    def test_non_chatbot_qwen_obs_filtered_when_no_dom_events(self):
        """Person/irrelevant Qwen obs must still be filtered when has_target_events=False."""
        from app.services.extension_proof_workflow_analysis_service import (
            _filter_visual_reasoning_summary_for_target,
        )
        summary = {
            "status": "analyzed",
            "frames_analyzed": 1,
            "observations": [
                {
                    "visual_summary": "A person is sitting at a desk looking at their phone.",
                    "visible_ui_elements": [],
                    "detected_user_action": "person is idle",
                    "confidence_score": 0.3,
                },
            ],
        }
        filtered = _filter_visual_reasoning_summary_for_target(
            summary,
            has_target_events=False,
            noise_hosts=[],
        )
        assert filtered is not None
        assert filtered.get("status") == "filtered_non_target_frame", (
            "Non-chatbot Qwen observation must be filtered when no DOM events"
        )
