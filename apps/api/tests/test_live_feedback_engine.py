"""
Tests for the Live Proof Feedback Engine and API endpoint.

Scenarios:
1. Data visualization proof — chart + click + output → score increases and
   suggests GitHub/code if claimed.
2. JavaScript claimed but no code/repo → suggestion asks to show code or GitHub.
3. GitHub URL visited → Open Source Project support becomes partial/likely.
4. Interaction without output → suggestion asks to show result/output.
5. Sensitive token text → privacy warning appears but raw value is not returned.
6. Generic website with no interaction → low score and suggestion to interact.
7. No overfitting to TensorFlow/p5.js/Gapminder only — tests use Observable + Vega.
8. Live feedback API endpoint — POST pushes snapshot, GET retrieves it.
9. Live feedback API endpoint — GET returns zero-state when no snapshot exists.
10. Data visualization skill — partial support when chart seen but no interaction.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.deps import get_current_user_id, get_db
from app.schemas.live_feedback import LiveSignalsInput
from app.services.live_feedback_engine import compute_live_feedback, _build_checklist

# ── Fixtures ──────────────────────────────────────────────────────────────────

DEMO_USER_ID = "00000000-0000-0000-0000-000000000001"
SESSION_ID   = "llllllll-0000-0000-0000-000000000001"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Helper ────────────────────────────────────────────────────────────────────

def _sig(**kwargs) -> LiveSignalsInput:
    defaults = dict(
        claimed_skills=[],
        current_url="https://example.com",
        page_title="Test Page",
        dom_text_snippets=[],
        click_count=0,
        input_count=0,
        form_submit_count=0,
        output_block_count=0,
        canvas_count=0,
        svg_count=0,
        github_url_seen=False,
        recording_duration_s=30.0,
        sensitive_warning_seen=False,
    )
    defaults.update(kwargs)
    return LiveSignalsInput(**defaults)


# ── Scenario 1: Data visualization proof ──────────────────────────────────────

def test_dataviz_proof_with_chart_click_output_increases_score():
    """Chart + click + output → high score; suggests GitHub/code for JS skill."""
    sig = _sig(
        claimed_skills=["Data Visualization", "JavaScript"],
        current_url="https://observablehq.com/plot/",
        page_title="Observable Plot",
        dom_text_snippets=["chart rendered", "axis labels", "tooltip value"],
        click_count=3,
        output_block_count=2,
        svg_count=1,
    )
    result = compute_live_feedback(SESSION_ID, sig)

    assert result.live_score >= 60, f"Expected score >= 60, got {result.live_score}"
    assert result.checklist.chart_or_visual_seen is True
    assert result.checklist.interaction_seen is True
    assert result.checklist.output_or_result_seen is True

    # Data Visualization skill should be likely
    dataviz = next(s for s in result.claimed_skill_support if "visualization" in s.skill.lower() or "Data" in s.skill)
    assert dataviz.support_level in ("likely", "partial")

    # JavaScript skill should be missing (no code text seen) — suggestion should appear
    js = next(s for s in result.claimed_skill_support if "javascript" in s.skill.lower() or "JavaScript" in s.skill)
    assert js.support_level in ("missing", "partial")

    # There should be a suggestion about code/GitHub for JavaScript
    suggestion_text = " ".join(result.suggestions).lower()
    assert any(
        kw in suggestion_text for kw in ["code", "github", "javascript", "repo"]
    ), f"Expected code/GitHub suggestion, got: {result.suggestions}"


# ── Scenario 2: JavaScript claimed, no code seen ──────────────────────────────

def test_javascript_claimed_no_code_suggests_code_or_github():
    """JavaScript skill claimed but no code or repo visible → suggestion prompts."""
    sig = _sig(
        claimed_skills=["JavaScript"],
        current_url="https://myapp.example.com",
        dom_text_snippets=["welcome to my app", "click here to start"],
        click_count=1,
        output_block_count=0,
    )
    result = compute_live_feedback(SESSION_ID, sig)

    js = next(s for s in result.claimed_skill_support if "javascript" in s.skill.lower() or "JavaScript" in s.skill)
    assert js.support_level == "missing"

    suggestion_text = " ".join(result.suggestions).lower()
    assert any(kw in suggestion_text for kw in ["code", "github"]), \
        f"Expected code/GitHub suggestion for JavaScript, got: {result.suggestions}"


# ── Scenario 3: GitHub URL visited → Open Source support ─────────────────────

def test_github_url_visited_open_source_becomes_likely():
    """GitHub URL in current_url → Open Source Project support becomes likely."""
    sig = _sig(
        claimed_skills=["Open Source Project"],
        current_url="https://github.com/myuser/myrepo",
        page_title="myuser/myrepo — GitHub",
        dom_text_snippets=["README", "commits", "branches", "pull requests"],
        click_count=2,
    )
    result = compute_live_feedback(SESSION_ID, sig)

    assert result.checklist.github_seen is True

    open_source = next(
        s for s in result.claimed_skill_support
        if "open" in s.skill.lower() or "source" in s.skill.lower() or "github" in s.skill.lower()
    )
    assert open_source.support_level == "likely", \
        f"Expected 'likely' for Open Source after GitHub visit, got: {open_source.support_level}"


# ── Scenario 4: Interaction without output ────────────────────────────────────

def test_interaction_without_output_suggests_show_result():
    """Clicks captured but no result text → suggestion to show output."""
    sig = _sig(
        claimed_skills=["Machine Learning"],
        current_url="https://ml-demo.example.com",
        dom_text_snippets=["upload image", "select model"],
        click_count=4,
        output_block_count=0,
    )
    result = compute_live_feedback(SESSION_ID, sig)

    assert result.checklist.interaction_seen is True
    assert result.checklist.output_or_result_seen is False

    suggestion_text = " ".join(result.suggestions).lower()
    assert any(kw in suggestion_text for kw in ["result", "output"]), \
        f"Expected output suggestion, got: {result.suggestions}"


# ── Scenario 5: Sensitive token text ──────────────────────────────────────────

def test_sensitive_warning_appears_without_raw_value():
    """Sensitive-looking label text triggers privacy warning; raw value not returned."""
    sig = _sig(
        claimed_skills=[],
        current_url="https://dashboard.example.com",
        dom_text_snippets=["API Key:", "Secret Token:", "Authorization Bearer"],
        sensitive_warning_seen=True,
    )
    result = compute_live_feedback(SESSION_ID, sig)

    assert result.sensitive_warning is True
    assert result.checklist.sensitive_warning is True

    # Raw secret values must NOT appear in any suggestion or output field
    all_text = " ".join(result.suggestions)
    assert "sk-" not in all_text
    assert "Bearer " not in all_text

    # Warning suggestion should be the first
    assert len(result.suggestions) > 0
    assert any(kw in result.suggestions[0].lower() for kw in ["avoid", "sensitive", "token", "key"]), \
        f"Expected privacy warning suggestion first, got: {result.suggestions}"


# ── Scenario 6: Generic website with no interaction ───────────────────────────

def test_generic_website_no_interaction_low_score_and_interact_suggestion():
    """No interaction on generic page → low score + suggestion to interact."""
    sig = _sig(
        claimed_skills=[],
        current_url="https://generic-site.example.com",
        page_title="Some Website",
        dom_text_snippets=["welcome to our website", "about us"],
        click_count=0,
        website_loaded=True,
    )
    result = compute_live_feedback(SESSION_ID, sig)

    assert result.live_score < 45, f"Expected score < 45 for no-interaction site, got {result.live_score}"
    assert result.checklist.interaction_seen is False

    suggestion_text = " ".join(result.suggestions).lower()
    assert any(kw in suggestion_text for kw in ["interact", "click", "start"]), \
        f"Expected interaction suggestion, got: {result.suggestions}"


# ── Scenario 7: No overfitting — Observable Plot + Vega-Lite ─────────────────

def test_observable_and_vega_not_hardcoded():
    """Engine handles Observable Plot and Vega-Lite without hardcoded names."""
    for url, title, skill in [
        ("https://observablehq.com/plot/", "Observable Plot", "Data Visualization"),
        ("https://vega.github.io/vega-lite/", "Vega-Lite", "Data Visualization"),
        ("https://d3js.org/", "D3.js", "Data Visualization"),
    ]:
        sig = _sig(
            claimed_skills=[skill],
            current_url=url,
            page_title=title,
            dom_text_snippets=["chart", "bar chart", "axis", "legend", "data"],
            click_count=2,
            svg_count=1,
            output_block_count=1,
        )
        result = compute_live_feedback(SESSION_ID, sig)

        assert result.live_score >= 50, \
            f"Expected score >= 50 for {url}, got {result.live_score}"
        assert result.checklist.chart_or_visual_seen is True, \
            f"chart_or_visual_seen should be True for {url}"


# ── Scenario 10: Partial support — chart seen but no interaction ───────────────

def test_dataviz_chart_seen_no_interaction_is_partial():
    """Chart detected but no user interaction → partial support for data viz."""
    sig = _sig(
        claimed_skills=["Data Visualization"],
        current_url="https://plot.example.com",
        dom_text_snippets=["interactive chart", "select region"],
        svg_count=1,
        click_count=0,
    )
    result = compute_live_feedback(SESSION_ID, sig)

    dataviz = next(
        s for s in result.claimed_skill_support
        if "visualization" in s.skill.lower() or "Data" in s.skill
    )
    assert dataviz.support_level == "partial", \
        f"Expected 'partial' for chart-seen but no interaction, got: {dataviz.support_level}"


# ── API endpoint tests ────────────────────────────────────────────────────────

def test_live_feedback_get_returns_zero_state_when_no_snapshot(client: TestClient):
    """GET /live-feedback returns zero-state when no snapshot has been pushed yet."""
    r = client.get(f"/api/v1/student/extension-proof/sessions/{SESSION_ID}/live-feedback")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == SESSION_ID
    assert body["live_score"] == 0
    assert body["recording_status"] == "recording"
    assert "waiting" in " ".join(body["suggestions"]).lower() or len(body["suggestions"]) >= 1


def test_live_feedback_post_stores_and_returns_state(client: TestClient):
    """POST /live-feedback computes and stores feedback; GET retrieves it."""
    session_id_2 = "llllllll-0000-0000-0000-000000000002"

    payload = {
        "claimed_skills": ["Data Visualization"],
        "current_url": "https://observablehq.com/plot/",
        "page_title": "Observable Plot",
        "dom_text_snippets": ["chart", "axis", "tooltip"],
        "click_count": 3,
        "svg_count": 2,
        "output_block_count": 1,
        "github_url_seen": False,
        "recording_duration_s": 45.0,
        "sensitive_warning_seen": False,
    }

    r = client.post(
        f"/api/v1/student/extension-proof/sessions/{session_id_2}/live-feedback",
        json=payload,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == session_id_2
    assert body["live_score"] >= 40
    assert body["checklist"]["chart_or_visual_seen"] is True

    # GET should return the same stored state
    r2 = client.get(f"/api/v1/student/extension-proof/sessions/{session_id_2}/live-feedback")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["live_score"] == body["live_score"]
    assert body2["checklist"]["chart_or_visual_seen"] is True
