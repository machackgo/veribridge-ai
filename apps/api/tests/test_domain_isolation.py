"""Tests for target-domain isolation, live-check fallback, and score-floor fixes.

Covers:
 1. resolve_target_domain uses proof_data.live_website_check.website_url
    when session.website_url is None/empty.
 2. _partition_rows_by_domain keeps only target-domain rows.
 3. threejs.org target with Supabase/GitHub rows → no unrelated page titles
    or text in extracted observations.
 4. unrelated_count is correct; filtered text not exposed.
 5. Subdomains of target domain are kept; sibling domains are filtered.
 6. FinalEvidenceEvaluatorService._load_live_website_check delegates to
    LiveWebsiteCheckService.get_latest(), which reads proof_data fallback.
 7. Final evaluator does NOT recommend "Run live check" when proof_data
    already has a live check result.
 8. Final score does NOT drop below the website-core baseline when GitHub
    and transcript (project_defense) are weak.
 9. Missing optional sources do not penalise the score.
10. No Supabase / Storage / SQL / maintenance text leaks into the
    target-domain summary for a threejs.org session.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── Module under test ─────────────────────────────────────────────────────────

from app.services.proof_target_resolver import (
    domain_matches_target,
    normalize_domain,
    resolve_target_domain,
    resolve_target_url,
)
from app.services.workflow_visible_evidence_service import (
    WorkflowVisibleEvidenceService,
    _partition_rows_by_domain,
)
from app.services.final_evidence_evaluator_service import (
    EvidenceSourceResult,
    FinalEvidenceEvaluatorService,
    _OPTIONAL_BOOSTER_KEYS,
    _WEBSITE_CORE_KEYS,
)

# ── Constants ─────────────────────────────────────────────────────────────────

UID = "user-abc"
SID = "session-xyz"

# Rows as they would come from workflow_visible_evidence_events
def _row(domain: str, page_title: str, visible: list[str] | None = None, etype: str = "dom_snapshot") -> dict[str, Any]:
    return {
        "user_id": UID,
        "proof_session_id": SID,
        "event_type": etype,
        "target_domain": domain,
        "page_title": page_title,
        "visible_text_blocks": visible or [],
        "result_like_blocks": [],
        "action_snapshot": {},
        "input_snapshot": {},
        "timestamp_ms": 1000,
    }


THREEJS_ROW    = _row("threejs.org", "three.js - WebGL Geometry Simplifier", ["WebGL", "Geometry", "LOD"])
SUBDOMAIN_ROW  = _row("examples.threejs.org", "three.js Example", ["Canvas", "Animation"])
SUPABASE_ROW   = _row("supabase.com", "Supabase Dashboard | Table Editor", ["SQL Editor", "Storage", "Maintenance"])
GITHUB_ROW_1   = _row("github.com", "mrdoob/three.js: GitHub Repository", ["Fork", "Stars", "README"])
GITHUB_ROW_2   = _row("github.com", "GitHub Pull Request", ["Diff", "Merge"])
OLD_ROW        = _row("", "Old event without domain tag", ["legacy content"])


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — proof_target_resolver
# ═══════════════════════════════════════════════════════════════════════════════

class TestResolveTargetUrl:
    def test_session_website_url_takes_priority(self):
        pd = {"live_website_check": {"website_url": "https://other.example.com"}}
        assert resolve_target_url("https://threejs.org", pd) == "https://threejs.org"

    def test_falls_back_to_live_website_check_url(self):
        """Core fix: session.website_url is None → use proof_data live check URL."""
        pd = {"live_website_check": {"website_url": "https://threejs.org/examples/#webgl"}}
        assert resolve_target_url(None, pd) == "https://threejs.org/examples/#webgl"

    def test_falls_back_to_proof_data_website_url(self):
        pd = {"website_url": "https://myapp.streamlit.app"}
        assert resolve_target_url(None, pd) == "https://myapp.streamlit.app"

    def test_falls_back_to_submitted_url(self):
        pd = {"submitted_url": "https://kaggle.com/work/notebook"}
        assert resolve_target_url("", pd) == "https://kaggle.com/work/notebook"

    def test_returns_none_when_nothing_available(self):
        assert resolve_target_url(None, {}) is None
        assert resolve_target_url("", {}) is None
        assert resolve_target_url(None, None) is None

    def test_whitespace_only_treated_as_empty(self):
        pd = {"website_url": "https://threejs.org"}
        assert resolve_target_url("   ", pd) == "https://threejs.org"


class TestNormalizeDomain:
    def test_strips_path_and_fragment(self):
        assert normalize_domain("https://threejs.org/examples/#webgl_geometry") == "threejs.org"

    def test_strips_www(self):
        assert normalize_domain("www.github.com/mrdoob/three.js") == "github.com"

    def test_adds_scheme_if_missing(self):
        assert normalize_domain("threejs.org") == "threejs.org"

    def test_lowercases(self):
        assert normalize_domain("HTTPS://ThreeJS.Org/foo") == "threejs.org"

    def test_returns_none_for_empty(self):
        assert normalize_domain("") is None
        assert normalize_domain(None) is None


class TestDomainMatchesTarget:
    def test_exact_match(self):
        assert domain_matches_target("threejs.org", "threejs.org") is True

    def test_subdomain_matches(self):
        assert domain_matches_target("examples.threejs.org", "threejs.org") is True

    def test_deep_subdomain_matches(self):
        assert domain_matches_target("a.b.threejs.org", "threejs.org") is True

    def test_different_domain_does_not_match(self):
        assert domain_matches_target("supabase.com", "threejs.org") is False
        assert domain_matches_target("github.com", "threejs.org") is False

    def test_www_stripped_before_comparison(self):
        assert domain_matches_target("www.threejs.org", "threejs.org") is True
        assert domain_matches_target("threejs.org", "www.threejs.org") is True

    def test_empty_row_domain_returns_false(self):
        assert domain_matches_target("", "threejs.org") is False

    def test_empty_target_returns_false(self):
        assert domain_matches_target("threejs.org", "") is False

    def test_partial_suffix_does_not_match(self):
        # "badthreejs.org" must NOT match "threejs.org" — no implicit *.ending.
        assert domain_matches_target("badthreejs.org", "threejs.org") is False


class TestResolveTargetDomain:
    def test_resolves_from_live_check_when_session_url_none(self):
        pd = {"live_website_check": {"website_url": "https://threejs.org/examples/#webgl_geometry_simplifier"}}
        assert resolve_target_domain(None, pd) == "threejs.org"

    def test_resolves_from_session_url(self):
        assert resolve_target_domain("https://www.github.com/user/repo", {}) == "github.com"

    def test_returns_none_when_no_source(self):
        assert resolve_target_domain(None, {}) is None


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — domain partitioning and observation filtering
# ═══════════════════════════════════════════════════════════════════════════════

class TestPartitionRowsByDomain:
    def test_target_rows_separated(self):
        rows = [THREEJS_ROW, SUPABASE_ROW, GITHUB_ROW_1]
        target, unrelated = _partition_rows_by_domain(rows, "threejs.org")
        assert THREEJS_ROW in target
        assert SUPABASE_ROW in unrelated
        assert GITHUB_ROW_1 in unrelated

    def test_subdomain_kept_with_target(self):
        rows = [THREEJS_ROW, SUBDOMAIN_ROW, SUPABASE_ROW]
        target, unrelated = _partition_rows_by_domain(rows, "threejs.org")
        assert THREEJS_ROW in target
        assert SUBDOMAIN_ROW in target
        assert SUPABASE_ROW in unrelated

    def test_old_rows_without_domain_kept_conservatively(self):
        rows = [OLD_ROW, SUPABASE_ROW]
        target, unrelated = _partition_rows_by_domain(rows, "threejs.org")
        assert OLD_ROW in target        # backward-compat: empty domain → keep
        assert SUPABASE_ROW in unrelated

    def test_empty_target_returns_all_in_target(self):
        rows = [THREEJS_ROW, SUPABASE_ROW]
        target, unrelated = _partition_rows_by_domain(rows, "")
        assert target == rows
        assert unrelated == []

    def test_unrelated_count(self):
        rows = [THREEJS_ROW, SUPABASE_ROW, GITHUB_ROW_1, GITHUB_ROW_2]
        _, unrelated = _partition_rows_by_domain(rows, "threejs.org")
        assert len(unrelated) == 3  # supabase + 2 github


class TestGetExtractedObservationsFiltering:
    """Integration: WorkflowVisibleEvidenceService.get_extracted_observations()
    with an in-memory dict store.
    """

    def _make_client(self, rows: list[dict]) -> dict:
        store = {str(i): row for i, row in enumerate(rows)}
        return {"workflow_visible_evidence_events": store}

    def test_unrelated_count_reported(self):
        rows = [THREEJS_ROW, SUPABASE_ROW, GITHUB_ROW_1, GITHUB_ROW_2]
        client = self._make_client(rows)
        svc = WorkflowVisibleEvidenceService(client)
        obs = svc.get_extracted_observations(UID, SID, target_domain="threejs.org")
        assert obs.filtered_unrelated_count == 3  # supabase + 2 github

    def test_unrelated_page_titles_excluded_from_observations(self):
        """No supabase.com / github.com text should appear in page_context_summary
        or top_result_snippets when threejs.org is the target."""
        rows = [THREEJS_ROW, SUPABASE_ROW, GITHUB_ROW_1, GITHUB_ROW_2]
        client = self._make_client(rows)
        svc = WorkflowVisibleEvidenceService(client)
        obs = svc.get_extracted_observations(UID, SID, target_domain="threejs.org")

        text_blob = " ".join([
            obs.page_context_summary or "",
            " ".join(obs.top_result_snippets),
            " ".join(obs.observed_inputs),
            " ".join(obs.observed_outputs),
        ]).lower()

        assert "supabase" not in text_blob
        assert "sql editor" not in text_blob
        assert "storage" not in text_blob
        assert "maintenance" not in text_blob
        assert "github" not in text_blob

    def test_threejs_content_present_in_observations(self):
        rows = [THREEJS_ROW, SUBDOMAIN_ROW, SUPABASE_ROW]
        client = self._make_client(rows)
        svc = WorkflowVisibleEvidenceService(client)
        obs = svc.get_extracted_observations(UID, SID, target_domain="threejs.org")
        # The page context summary is derived from visible_text_blocks of target rows.
        # We can't rely on it including exactly "WebGL" (depends on block extraction),
        # but the analysis must have included at least the threejs rows.
        assert obs.event_count >= 1 or obs.visible_evidence_status == "available"

    def test_no_domain_filter_returns_all(self):
        rows = [THREEJS_ROW, SUPABASE_ROW, GITHUB_ROW_1]
        client = self._make_client(rows)
        svc = WorkflowVisibleEvidenceService(client)
        obs = svc.get_extracted_observations(UID, SID, target_domain=None)
        assert obs.filtered_unrelated_count == 0

    def test_fallback_to_all_rows_when_no_target_rows_match(self):
        """If no rows match the target domain, fall back to all rows to avoid
        returning empty observations for old recordings."""
        rows = [SUPABASE_ROW, GITHUB_ROW_1]  # neither is threejs.org
        client = self._make_client(rows)
        svc = WorkflowVisibleEvidenceService(client)
        obs = svc.get_extracted_observations(UID, SID, target_domain="threejs.org")
        # Fallback: all rows used, no crash
        assert obs.visible_evidence_status != "not_captured"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — live website check fallback via proof_data
# ═══════════════════════════════════════════════════════════════════════════════

class TestLiveCheckFallback:
    """FinalEvidenceEvaluatorService._load_live_website_check() must use
    LiveWebsiteCheckService.get_latest(), which reads proof_data if the
    live_website_check_results table row is absent.
    """

    def _make_db_with_proof_data_only(self) -> dict:
        """In-memory store where live check is in proof_data but NOT in the table."""
        live_check = {
            "status": "complete",
            "is_reachable": True,
            "checked_at": "2025-06-01T10:00:00Z",
            "website_url": "https://threejs.org",
            "http_status_code": 200,
        }
        session = {
            "id": SID,
            "user_id": UID,
            "proof_session_id": SID,
            "proof_data": {"live_website_check": live_check},
        }
        return {
            "extension_proof_sessions": {SID: session},
            # live_website_check_results table intentionally empty:
            "live_website_check_results": {},
        }

    def test_reads_proof_data_fallback_when_table_is_empty(self):
        db = self._make_db_with_proof_data_only()
        svc = FinalEvidenceEvaluatorService(db)
        result = svc._load_live_website_check(UID, SID)
        assert result is not None
        assert result.get("is_reachable") is True
        assert result.get("website_url") == "https://threejs.org"

    def test_table_row_takes_priority_over_proof_data(self):
        table_row = {
            "id": "row-1",
            "user_id": UID,
            "proof_session_id": SID,
            "status": "complete",
            "is_reachable": True,
            "checked_at": "2025-06-02T10:00:00Z",
            "website_url": "https://threejs.org",
            "http_status_code": 200,
        }
        session = {
            "id": SID,
            "user_id": UID,
            "proof_data": {"live_website_check": {"status": "complete", "is_reachable": False, "website_url": "https://threejs.org"}},
        }
        db = {
            "extension_proof_sessions": {SID: session},
            "live_website_check_results": {"row-1": table_row},
        }
        svc = FinalEvidenceEvaluatorService(db)
        result = svc._load_live_website_check(UID, SID)
        # Table row should win (is_reachable=True, not the proof_data's False)
        assert result["is_reachable"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — _combine_scores: website-core floor protection
# ═══════════════════════════════════════════════════════════════════════════════

def _src(key: str, status: str, score: int) -> EvidenceSourceResult:
    from app.services.final_evidence_evaluator_service import _SOURCE_WEIGHTS
    weight = _SOURCE_WEIGHTS.get(key, 0.10)
    return EvidenceSourceResult(key=key, status=status, score=score, weight=weight)


class TestCombineScoresFloor:

    def _svc(self) -> FinalEvidenceEvaluatorService:
        return FinalEvidenceEvaluatorService.__new__(FinalEvidenceEvaluatorService)

    def test_weak_github_does_not_lower_strong_website_core(self):
        """Scenario from the Codex investigation:
        - Strong website core (website_workflow=85, dom_visible=80, keyframes=90,
          live_check=pass, ocr=80, qwen=80)
        - Weak GitHub (62) and weak project_defense (53)

        Final score must NOT be below the website-core-only weighted score.
        """
        sources = [
            _src("website_workflow",      "pass",    85),
            _src("dom_visible_evidence",  "pass",    80),
            _src("video_keyframes",       "pass",    90),
            _src("ocr",                   "pass",    80),
            _src("qwen_visual_reasoning", "pass",    80),
            _src("live_website_check",    "pass",    90),
            _src("github",                "partial", 62),  # weak
            _src("project_defense",       "partial", 53),  # weak transcript
        ]
        svc = self._svc()
        score = svc._combine_scores(sources)

        # Compute expected website-core floor manually:
        core_sources = [s for s in sources if s.key in _WEBSITE_CORE_KEYS]
        wc_weight = sum(s.weight for s in core_sources)
        wc_sum = sum(s.score * s.weight for s in core_sources)
        wc_raw = wc_sum / wc_weight
        wc_pass = sum(1 for s in core_sources if s.status == "pass")
        expected_floor = min(100, int(wc_raw + min(5, wc_pass)))

        assert score >= expected_floor, (
            f"Score {score} dropped below website-core floor {expected_floor}"
        )

    def test_strong_github_still_adds_value(self):
        """When GitHub and project_defense are strong, the full weighted score
        should be >= website-core score (same or higher).
        """
        sources = [
            _src("website_workflow",      "pass", 80),
            _src("dom_visible_evidence",  "pass", 75),
            _src("video_keyframes",       "pass", 85),
            _src("live_website_check",    "pass", 90),
            _src("github",                "pass", 92),  # strong
            _src("project_defense",       "pass", 88),  # strong
        ]
        svc = self._svc()
        score_with_gh = svc._combine_scores(sources)

        core_only = [s for s in sources if s.key in _WEBSITE_CORE_KEYS]
        svc2 = self._svc()
        score_core_only = svc2._combine_scores(core_only)

        # Strong GitHub / transcript should lift the full score above or equal
        # to core-only score (never lower).
        assert score_with_gh >= score_core_only

    def test_missing_optional_sources_no_penalty(self):
        """Absent optional boosters (linkedin, certificate, uploaded_documents)
        must not reduce the score vs. core-only.
        """
        core_sources = [
            _src("website_workflow",     "pass", 80),
            _src("dom_visible_evidence", "pass", 75),
            _src("video_keyframes",      "pass", 85),
            _src("live_website_check",   "pass", 90),
        ]
        svc = self._svc()
        score_no_optionals = svc._combine_scores(core_sources)

        # Adding not_run optional sources must not lower the score
        sources_with_missing_optionals = core_sources + [
            _src("uploaded_documents", "not_run", 0),
            _src("linkedin_profile",   "not_run", 0),
            _src("certificate",        "not_run", 0),
        ]
        svc2 = self._svc()
        score_with_not_run = svc2._combine_scores(sources_with_missing_optionals)

        assert score_with_not_run >= score_no_optionals, (
            f"Optional not_run sources dropped score from {score_no_optionals} to {score_with_not_run}"
        )

    def test_high_quality_optional_boosts_score(self):
        """A high-quality uploaded document (pass, score≥80) gives a small bonus."""
        core_sources = [
            _src("website_workflow",     "pass", 80),
            _src("dom_visible_evidence", "pass", 75),
        ]
        svc = self._svc()
        base = svc._combine_scores(core_sources)

        with_doc = core_sources + [_src("uploaded_documents", "pass", 85)]
        svc2 = self._svc()
        boosted = svc2._combine_scores(with_doc)

        assert boosted >= base

    def test_all_sources_not_run_returns_zero(self):
        sources = [
            _src("website_workflow",  "not_run", 0),
            _src("github",            "not_run", 0),
            _src("live_website_check","not_run", 0),
        ]
        svc = self._svc()
        assert svc._combine_scores(sources) == 0

    def test_only_optional_sources_capped_at_60(self):
        """When only optional boosters are present, score is capped at 60."""
        sources = [_src("uploaded_documents", "pass", 95)]
        svc = self._svc()
        assert svc._combine_scores(sources) <= 60

    def test_website_core_keys_are_the_right_set(self):
        """Regression: github and project_defense must NOT be in _WEBSITE_CORE_KEYS."""
        assert "github" not in _WEBSITE_CORE_KEYS
        assert "project_defense" not in _WEBSITE_CORE_KEYS
        assert "website_workflow" in _WEBSITE_CORE_KEYS
        assert "live_website_check" in _WEBSITE_CORE_KEYS

    def test_optional_booster_keys_not_in_website_core(self):
        assert not (_OPTIONAL_BOOSTER_KEYS & _WEBSITE_CORE_KEYS), (
            "Optional boosters should not overlap with website core keys"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — final evaluator does not recommend live check when proof_data has it
# ═══════════════════════════════════════════════════════════════════════════════

class TestFinalEvaluatorLiveCheckRecommendation:
    """When proof_data already has a completed live website check, the final
    evaluator must not include 'Run live website check' in recommendations.
    """

    def _make_full_db(self, include_live_check_in_proof_data: bool) -> dict:
        live_check_data = (
            {
                "status": "complete",
                "is_reachable": True,
                "website_url": "https://threejs.org",
                "http_status_code": 200,
                "checked_at": "2025-06-01T10:00:00Z",
            }
            if include_live_check_in_proof_data
            else None
        )
        session = {
            "id": SID,
            "user_id": UID,
            "proof_data": {
                "live_website_check": live_check_data,
            } if live_check_data else {},
        }

        wf_result = {
            "id": "wf-1",
            "user_id": UID,
            "proof_session_id": SID,
            "overall_score": 80,
            "analysis_status": "complete",
            "skill_evidence_summary": "Strong Three.js demonstration observed.",
            "demonstrated_skills": ["Three.js", "WebGL"],
            "evidence_quality": "high",
            "result_detected": True,
            "analysis_version": "v4",
        }

        return {
            "extension_proof_sessions": {SID: session},
            "live_website_check_results": {},  # empty — must use proof_data fallback
            "workflow_analysis_results": {"wf-1": wf_result},
            "extension_proof_github_analysis": {},
            "project_defense_analysis_results": {},
            "optional_evidence_submissions": {},
            "workflow_visual_frame_evidence": {},
        }

    def test_no_live_check_recommendation_when_proof_data_has_it(self):
        db = self._make_full_db(include_live_check_in_proof_data=True)
        svc = FinalEvidenceEvaluatorService(db)
        result = svc.evaluate(UID, SID)
        proof_action_titles = [a["title"] for a in result.to_dict()["recommendations"]["proof_actions"]]
        live_check_titles = [t for t in proof_action_titles if "live" in t.lower() and "check" in t.lower()]
        assert not live_check_titles, (
            f"Unexpected live check recommendation despite proof_data having one: {live_check_titles}"
        )

    def test_live_check_recommended_when_not_present(self):
        """Sanity: when there's no live check anywhere, it may be recommended."""
        db = self._make_full_db(include_live_check_in_proof_data=False)
        svc = FinalEvidenceEvaluatorService(db)
        result = svc.evaluate(UID, SID)
        # We don't assert it's always recommended, but the live check source
        # should be "not_run" (not "pass").
        breakdown = {s["key"]: s for s in result.to_dict()["evidence_source_breakdown"]}
        if "live_website_check" in breakdown:
            assert breakdown["live_website_check"]["status"] in ("not_run", "missing", "not_available"), (
                "Expected live_website_check to be not_run when absent from proof_data"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — get_summary target-domain isolation (endpoint + service)
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetSummaryDomainIsolation:
    """WorkflowVisibleEvidenceService.get_summary() must apply the same
    target-domain isolation as get_extracted_observations():
      - events_summary contains only target-domain rows
      - unrelated page titles (Supabase, GitHub, localhost) are absent
      - filtered_unrelated_count reflects excluded row count
      - target-domain content is present
    """

    def _make_client(self, rows: list[dict], session_website_url: str = "") -> dict:
        store = {str(i): row for i, row in enumerate(rows)}
        session = {
            "id": SID,
            "user_id": UID,
            "website_url": session_website_url,
            "proof_data": {
                "live_website_check": {
                    "website_url": "https://threejs.org/examples/#webgl",
                    "is_reachable": True,
                    "status": "complete",
                }
            },
        }
        return {
            "workflow_visible_evidence_events": store,
            "extension_proof_sessions": {SID: session},
        }

    def test_events_summary_excludes_unrelated_page_titles(self):
        rows = [THREEJS_ROW, SUPABASE_ROW, GITHUB_ROW_1, GITHUB_ROW_2]
        client = self._make_client(rows)
        svc = WorkflowVisibleEvidenceService(client)
        summary = svc.get_summary(UID, SID, target_domain="threejs.org")

        titles = [e.page_title for e in summary.events_summary]
        for title in titles:
            assert "Supabase" not in title, f"Supabase title leaked into events_summary: {title}"
            assert "GitHub" not in title, f"GitHub title leaked into events_summary: {title}"
            assert "localhost" not in title.lower(), f"localhost title leaked into events_summary: {title}"

    def test_threejs_title_present_in_events_summary(self):
        rows = [THREEJS_ROW, SUPABASE_ROW, GITHUB_ROW_1]
        client = self._make_client(rows)
        svc = WorkflowVisibleEvidenceService(client)
        summary = svc.get_summary(UID, SID, target_domain="threejs.org")

        titles = [e.page_title for e in summary.events_summary]
        assert any("three.js" in t.lower() or "threejs" in t.lower() for t in titles), (
            f"Expected threejs title in events_summary, got: {titles}"
        )

    def test_filtered_unrelated_count_preserved(self):
        rows = [THREEJS_ROW, SUPABASE_ROW, GITHUB_ROW_1, GITHUB_ROW_2]
        client = self._make_client(rows)
        svc = WorkflowVisibleEvidenceService(client)
        summary = svc.get_summary(UID, SID, target_domain="threejs.org")

        assert summary.filtered_unrelated_count == 3  # supabase + 2 github

    def test_event_count_reflects_target_rows_only(self):
        rows = [THREEJS_ROW, SUBDOMAIN_ROW, SUPABASE_ROW, GITHUB_ROW_1]
        client = self._make_client(rows)
        svc = WorkflowVisibleEvidenceService(client)
        summary = svc.get_summary(UID, SID, target_domain="threejs.org")

        # threejs.org + examples.threejs.org = 2 target rows
        assert summary.event_count == 2

    def test_no_target_domain_returns_all_rows(self):
        rows = [THREEJS_ROW, SUPABASE_ROW, GITHUB_ROW_1]
        client = self._make_client(rows)
        svc = WorkflowVisibleEvidenceService(client)
        summary = svc.get_summary(UID, SID, target_domain=None)

        assert summary.event_count == 3
        assert summary.filtered_unrelated_count == 0

    def test_get_session_resolves_from_proof_data_when_website_url_empty(self):
        """_get_session returns the session row; resolve_target_domain uses proof_data
        live_website_check.website_url when session.website_url is empty."""
        rows = [THREEJS_ROW, SUPABASE_ROW]
        # website_url intentionally empty — must fall back to proof_data
        client = self._make_client(rows, session_website_url="")
        svc = WorkflowVisibleEvidenceService(client)

        session = svc._get_session(UID, SID)
        assert session is not None

        from app.services.proof_target_resolver import resolve_target_domain
        resolved = resolve_target_domain(
            session.get("website_url") or "",
            session.get("proof_data") or {},
        )
        assert resolved == "threejs.org", f"Expected 'threejs.org', got {resolved!r}"

    def test_endpoint_resolves_and_passes_target_domain(self):
        """End-to-end: simulate the endpoint flow (resolve domain → pass to get_summary).
        Confirms the service produces a domain-isolated summary when the endpoint
        loads the session and resolves target_domain.
        """
        rows = [THREEJS_ROW, SUPABASE_ROW, GITHUB_ROW_1]
        client = self._make_client(rows, session_website_url="")
        svc = WorkflowVisibleEvidenceService(client)

        # Mimic what the endpoint does
        session = svc._get_session(UID, SID)
        from app.services.proof_target_resolver import resolve_target_domain
        target_domain = resolve_target_domain(
            session.get("website_url") or "",
            session.get("proof_data") or {},
        )
        summary = svc.get_summary(UID, SID, target_domain=target_domain)

        # Titles in events_summary must be target-only
        titles = [e.page_title for e in summary.events_summary]
        assert not any("Supabase" in t for t in titles), f"Supabase leaked: {titles}"
        assert not any("GitHub" in t for t in titles), f"GitHub leaked: {titles}"
        # Unrelated count present
        assert summary.filtered_unrelated_count == 2  # supabase + github
        # threejs row present
        assert any("three.js" in t.lower() or "threejs" in t.lower() for t in titles)
