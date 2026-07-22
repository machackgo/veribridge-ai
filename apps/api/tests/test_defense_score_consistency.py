"""
Project Defense scoring coherence — regression tests.

Historical bug (observed on a real production analysis): the UI showed
"Overall Defense Score 100/100" while the component gauges beside it read
Ownership 60/100 and Technical Depth 65/100. Root cause: the overall was an
additive CHECKLIST score — ownership/depth granted their full +15 step credit
at a low threshold (2 ownership phrases / 4 depth phrases) even though the
published component gauges for the same dimensions were only 60 and 65.

Invariant under test: the overall must be derivable from — and can never
contradict — the published component scores:

    overall ≤ 20 (length) + 20 (skills) + 10 (limitations)
            + 20·consistency/100 + 15·ownership/100 + 15·depth/100

  1. ``analyze_defense_transcript`` awards ownership/depth/consistency credit
     PROPORTIONALLY to the component scores, so fresh results always satisfy
     the bound (overall == 100 requires all three gauges at 100).
  2. ``coherent_overall_defense_score`` derives a coherent overall from any
     STORED row (legacy prod rows are never mutated) — identity for coherent
     rows, capped for incoherent legacy rows.
"""

from __future__ import annotations

from dataclasses import asdict

from app.services.project_defense_analysis_service import (
    analyze_defense_transcript,
    coherent_overall_defense_score,
)


def _coherence_bound(result_dict: dict) -> int:
    return (
        20
        + 20
        + 10
        + round(20 * result_dict["consistency_with_evidence_score"] / 100)
        + round(15 * result_dict["ownership_signal_score"] / 100)
        + round(15 * result_dict["technical_depth_score"] / 100)
    )


# A transcript engineered to hit every binary rubric criterion at full credit
# while the ownership gauge stays partial: ≥100 words, claimed skill mentioned,
# exactly 2 distinct ownership phrases ("I built", "my approach"), ≥4 technical
# depth phrases, ≥2 limitation phrases, no vague/contradiction phrases.
# Pre-fix this scored overall=100 beside ownership=60 — the prod contradiction.
_PROD_PATTERN_TRANSCRIPT = (
    "I built the analytics dashboard as a three-tier system. The React frontend "
    "renders time-series charts, the api layer exposes aggregate endpoint routes "
    "for visitors and pageviews, and the postgresql database stores raw events. "
    "My approach for the architecture separates ingestion from querying so heavy "
    "reads never block writes. The caching layer keeps rolling aggregates warm, "
    "which reduced dashboard latency substantially under load. Data flows from the "
    "collect endpoint through a validation step into the events table, and the "
    "charts read only from pre-bucketed aggregates. One limitation is that the "
    "rollups are recomputed nightly rather than incrementally, and in the future "
    "the aggregation could move to streaming so numbers update in near real time. "
    "The dashboard groups events into sessions using a rolling thirty minute "
    "window and renders the breakdown lists for pages, sources and devices."
)

_CLAIMED_SKILLS = ["React", "PostgreSQL"]

# Evidence summary whose (non-stop-word) tokens all appear in the transcript,
# maximising the consistency component.
_GITHUB_SUMMARY = "React dashboard analytics postgresql charts events"


class TestFreshAnalysisCoherence:
    def test_prod_pattern_no_longer_scores_overall_100(self) -> None:
        result = analyze_defense_transcript(
            transcript_text=_PROD_PATTERN_TRANSCRIPT,
            claimed_skills=_CLAIMED_SKILLS,
            github_summary=_GITHUB_SUMMARY,
        )
        d = asdict(result)
        # The ownership gauge is partial (2 phrases → 60), so a full-marks
        # overall is impossible under the proportional rubric.
        assert d["ownership_signal_score"] == 60
        assert d["overall_defense_score"] < 100
        assert d["overall_defense_score"] <= _coherence_bound(d)

    def test_overall_never_exceeds_component_bound(self) -> None:
        transcripts = [
            _PROD_PATTERN_TRANSCRIPT,
            "I built it with react.",
            (
                "I built and I implemented and I designed the entire architecture. "
                "My approach used an api endpoint, database schema, caching, "
                "authentication, middleware, validation and error handling with unit "
                "test coverage across the pipeline and workflow. One limitation is "
                "scale; a future improvement would add streaming. "
            )
            * 3,
            "",
            "Great project, amazing app, works well.",
        ]
        for text in transcripts:
            result = analyze_defense_transcript(
                transcript_text=text,
                claimed_skills=_CLAIMED_SKILLS,
                github_summary=_GITHUB_SUMMARY,
            )
            d = asdict(result)
            assert d["overall_defense_score"] <= _coherence_bound(d), (
                f"overall {d['overall_defense_score']} exceeds coherent bound "
                f"{_coherence_bound(d)} for transcript: {text[:60]!r}"
            )

    def test_overall_100_requires_full_component_gauges(self) -> None:
        # Maximise every dimension: many distinct ownership phrases (≥10 → 100),
        # many depth phrases (≥17 → 100), full consistency overlap, limitations.
        text = (
            "I built the system and I implemented the core and I developed the api "
            "and I created the schema and I designed the architecture and I wrote "
            "the algorithm and I coded the middleware and I configured the "
            "deployment and I integrated the authentication and I optimized the "
            "caching and I refactored the pipeline and I handled the validation. "
            "My approach and my design and my implementation cover the database, "
            "each endpoint, every component, the workflow, the interface, "
            "concurrency, scalability, security, testing, performance, latency, "
            "throughput, error handling and the data flow between services. "
            "One limitation is scale; a future improvement would add streaming and "
            "the next step is incremental rollups. React and PostgreSQL power it."
        )
        result = analyze_defense_transcript(
            transcript_text=text,
            claimed_skills=_CLAIMED_SKILLS,
            github_summary="react postgresql api database caching",
        )
        d = asdict(result)
        if d["overall_defense_score"] == 100:
            assert d["ownership_signal_score"] == 100
            assert d["technical_depth_score"] == 100
            assert d["consistency_with_evidence_score"] == 100

    def test_fresh_results_pass_through_coherence_clamp_unchanged(self) -> None:
        result = analyze_defense_transcript(
            transcript_text=_PROD_PATTERN_TRANSCRIPT,
            claimed_skills=_CLAIMED_SKILLS,
            github_summary=_GITHUB_SUMMARY,
        )
        d = asdict(result)
        assert coherent_overall_defense_score(d) == d["overall_defense_score"]


class TestStoredRowCoherence:
    def test_legacy_prod_row_is_capped_not_mutated(self) -> None:
        # The exact values stored on the real prod analysis
        # (vbr_verification_sessions bdae349b…, telemetry.project_defense_analysis):
        row = {
            "overall_defense_score": 100,
            "consistency_with_evidence_score": 100,
            "ownership_signal_score": 60,
            "technical_depth_score": 65,
            "explanation_clarity_score": 75,
        }
        # bound = 20+20+10 + 20·1.00 + round(15·0.60) + round(15·0.65)
        #       = 50 + 20 + 9 + 10 = 89
        assert coherent_overall_defense_score(row) == 89
        # The input row is not modified.
        assert row["overall_defense_score"] == 100

    def test_coherent_row_is_identity(self) -> None:
        row = {
            "overall_defense_score": 72,
            "consistency_with_evidence_score": 80,
            "ownership_signal_score": 90,
            "technical_depth_score": 70,
        }
        # bound = 50 + 16 + 14 + 11 = 91 ≥ 72 → unchanged
        assert coherent_overall_defense_score(row) == 72

    def test_full_components_allow_full_overall(self) -> None:
        row = {
            "overall_defense_score": 100,
            "consistency_with_evidence_score": 100,
            "ownership_signal_score": 100,
            "technical_depth_score": 100,
        }
        assert coherent_overall_defense_score(row) == 100

    def test_missing_or_malformed_fields_fail_closed(self) -> None:
        assert coherent_overall_defense_score({}) == 0
        assert coherent_overall_defense_score({"overall_defense_score": 100}) == 50
        assert (
            coherent_overall_defense_score(
                {"overall_defense_score": -5, "ownership_signal_score": 60}
            )
            == 0
        )
        # Out-of-range component values are clamped before weighting.
        assert (
            coherent_overall_defense_score(
                {
                    "overall_defense_score": 100,
                    "consistency_with_evidence_score": 500,
                    "ownership_signal_score": 100,
                    "technical_depth_score": 100,
                }
            )
            == 100
        )


class TestFinalEvaluatorSourceScoreCoherence:
    """The final evaluator's project_defense source score is PREFERRED by the
    frontend over the (clamped) analysis overall — so it must obey the same
    coherence bound, or a legacy row would still display 100 beside 60/65."""

    def _svc(self):
        from unittest.mock import MagicMock

        from app.services.final_evidence_evaluator_service import (
            FinalEvidenceEvaluatorService,
        )

        return FinalEvidenceEvaluatorService(MagicMock())

    def test_legacy_prod_row_source_score_is_clamped_to_89(self) -> None:
        pd = {
            "analysis_status": "analyzed",
            "overall_defense_score": 100,
            "consistency_with_evidence_score": 100,
            "ownership_signal_score": 60,
            "technical_depth_score": 65,
        }
        result = self._svc()._score_project_defense(pd, claimed_skills=["React"])
        assert result.score == 89
        assert result.status == "pass"  # still ≥ 60 — gating unchanged

    def test_coherent_row_source_score_unchanged(self) -> None:
        pd = {
            "analysis_status": "analyzed",
            "overall_defense_score": 72,
            "consistency_with_evidence_score": 80,
            "ownership_signal_score": 90,
            "technical_depth_score": 70,
        }
        result = self._svc()._score_project_defense(pd, claimed_skills=["React"])
        assert result.score == 72

    def test_row_without_component_scores_is_not_clamped(self) -> None:
        # The bound is meaningless without component scores — a bare overall
        # must pass through untouched (never lowered to the 50 floor).
        pd = {"analysis_status": "analyzed", "overall_defense_score": 80}
        result = self._svc()._score_project_defense(pd, claimed_skills=["React"])
        assert result.score == 80
