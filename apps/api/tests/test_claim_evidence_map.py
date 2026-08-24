"""Canonical claim→evidence map tests (claim_evidence_synthesis_service).

Covers the proof-native reporting rules:

* GitHub tiering — exact file/line/commit/excerpt citations survive; route
  decorators / imports / config / repo-level shells never count as primary
  implementation.
* Website↔project identity — same-project attachment alone never counts; a
  recording that identifies as a DIFFERENT application (the VeriBridge
  recording attached to the Boston project) is mismatched: visible, flagged,
  never counted, never corroborating, never deleted.
* Corroboration — requires claim-level alignment of independently-counting
  sources; two proofs sharing a project id do not corroborate.
* Project Defense — captured-but-unanalyzed defense renders as an explicit
  "Analysis pending" citation that never counts; analyzed, skill-mapped
  inspection cards contribute direct authorship evidence.
* Documents — page/section locators count; locator-less docs stay context;
  retention drives an honest excerpts-only vs open/download access state.
* No numeric trust scores anywhere; both report surfaces share ONE model;
  historical/partial rows degrade to limitations instead of crashing.

Everything is deterministic and in-memory — no network / LLM calls.
"""

from __future__ import annotations

import json
import re

import pytest

from app.schemas.canonical_evidence import (
    QUALITATIVE_STATES,
    ClaimEvidenceMap,
)
from app.schemas.vbr_student_report import SkillReportResponse
from app.services.claim_evidence_synthesis_service import (
    build_project_claim_evidence_map,
    build_skill_claim_evidence_map,
    classify_github_tier,
    classify_website_identity,
)


# ── Builders for hand-rolled report payloads ──────────────────────────────────

BOSTON = "Boston Smart Accident Risk Rerouting"


def _gh_item(**overrides) -> dict:
    item = {
        "proof_type": "GitHub Proof",
        "source_id": "gh-1",
        "title": "octocat/boston-rerouting",
        "safe_summary": "Model training implementation.",
        "safe_location": "train.py",
        "safe_snippet": "model = RandomForestClassifier()\nmodel.fit(X_train, y_train)",
        "file_path": "train.py",
        "line_start": 41,
        "line_end": 58,
        "function_name": "train_model",
        "commit_sha": "abc123def456",
        "display_mode": "code_line",
        "evidence_quality_grade": "implementation_body",
        "skill_relevance_key": "direct_ml_evidence",
        "skill_relevance_summary": "Trains the accident-risk model used by the rerouting API.",
        "code_block_purpose_summary": "Fits the risk classifier on the training set.",
        "github_line_url": "https://github.com/octocat/boston-rerouting/blob/main/train.py#L41-L58",
        "limitation": "",
        "attached_project_ids": ["p1"],
    }
    item.update(overrides)
    return item


def _route_shell_item(**overrides) -> dict:
    return _gh_item(
        source_id="gh-2",
        file_path="api.py",
        line_start=252,
        line_end=255,
        function_name="predict",
        safe_snippet='@app.route("/predict")\ndef predict():',
        evidence_quality_grade="route_decorator_only",
        selection_reason="API endpoint decorator",
        code_block_purpose_summary=None,
        skill_relevance_key=None,
        skill_relevance_summary=None,
        **overrides,
    )


def _web_item(*, app_context: str | None, page_title: str | None = None, relevance_key: str = "ml_product_context", **overrides) -> dict:
    item = {
        "proof_type": "Website Proof",
        "source_id": "web-1",
        "title": "Recorded session",
        "safe_summary": "Recorded workflow.",
        "website_skill_relevance_key": relevance_key,
        "website_skill_relevance_summary": "Observed product behaviour.",
        "workflow_steps": ["User submits route inputs", "Risk result appears"],
        "attached_project_ids": ["p1"],
        "website_evidence_card": {
            "card_key": "w1",
            "route_or_page": "Recorded session",
            "page_title": page_title,
            "app_context": app_context,
            "target_domain": None,
            "behavior_claim": "User input leads to a visible prediction result.",
            "user_action_observed": "User provides route inputs.",
            "output_observed": "A risk result appears.",
            "skill_relevance_key": relevance_key,
            "skill_relevance_summary": "Observed product behaviour.",
            "website_purpose_key": "prediction_result_display",
            "website_purpose_label": "Prediction / result display",
            "is_public_live_url": False,
            "is_local_or_private_url": True,
            "verification_mode_label": "Recorded replay only",
            "verification_note": "",
            "screenshot_available": False,
            "limitation": "Runtime behaviour alone does not prove training or authorship.",
        },
        "limitation": "",
    }
    item.update(overrides)
    return item


def _doc_correlation(**overrides) -> dict:
    doc = {
        "source_id": "doc-1",
        "document_title": "Final Report — Boston Smart Accident Risk Rerouting",
        "page_number": 5,
        "section_label": "Model architecture",
        "citation": "Section 4.2 Model architecture",
        "figure_reference": None,
        "safe_snippet": "The rerouting model is a random-forest classifier trained on crash records.",
        "corroborates": "GitHub implementation",
        "correlation_confidence": "direct attachment",
        "why_supported": "Names the exact model family implemented in train.py.",
        "reason": "",
        "limitation": "",
        "document_retained": False,
        "full_document_available": False,
    }
    doc.update(overrides)
    return doc


def _defense_card(**overrides) -> dict:
    card = {
        "evidence_id_safe": "def-1",
        "question_text": "How did you train and validate the accident-risk model?",
        "project_title": BOSTON,
        "mapped_skill": "Machine Learning",
        "qualitative_status": "Explained with evidence",
        "safe_answer_summary": "Described the training pipeline, features, and validation split.",
        "what_this_demonstrates": "Understanding of the model's training and evaluation choices.",
        "timestamp_label": "02:14",
        "transcript_excerpt_start_label": "02:10",
        "transcript_excerpt_end_label": "02:41",
        "safe_transcript_excerpt": "We trained a random forest on three years of crash data…",
        "clip_available": True,
        "video_available": True,
        "video_playback_url": None,
        "transcript_excerpt_available": True,
        "limitation": "Self-explanation — not independent proof of authorship.",
        "recording_access_note": "",
        "transcript_access_note": "",
    }
    card.update(overrides)
    return card


def _chain(**overrides) -> dict:
    chain = {
        "project_id": "p1",
        "project_title": BOSTON,
        "attached": True,
        "github_evidence": [],
        "website_evidence": [],
        "document_correlations": [],
        "defense_evidence": [],
        "video_evidence": [],
        "video_proofs": [],
        "project_defense_inspection": [],
    }
    chain.update(overrides)
    return chain


def _skill_report(chains: list[dict], skill: str = "Machine Learning") -> dict:
    return {
        "skill": skill,
        "skill_slug": "machine-learning",
        "projects": chains,
        "gaps": [],
    }


_META = {"p1": {"title": BOSTON, "repo_full": "octocat/boston-rerouting", "repo_name": "boston-rerouting"}}


def _map(report: dict) -> dict:
    out = build_skill_claim_evidence_map(report, project_meta=_META)
    # Every emitted map must round-trip the canonical contract.
    ClaimEvidenceMap(**out)
    return out


# ── GitHub tiering ─────────────────────────────────────────────────────────────


def test_implementation_body_is_primary_and_cites_exact_lines() -> None:
    cem = _map(_skill_report([_chain(github_evidence=[_gh_item()])]))
    [cit] = [c for c in cem["citations"] if c["proof_type"] == "GitHub Proof"]
    assert cit["github_tier"] == "primary_implementation"
    assert cit["counted_as_direct_evidence"] is True
    # Exact stored locators survive verbatim — never invented, never dropped.
    assert cit["file_path"] == "train.py"
    assert (cit["start_line"], cit["end_line"]) == (41, 58)
    assert cit["symbol_name"] == "train_model"
    assert cit["commit_sha"] == "abc123def456"
    assert "RandomForestClassifier" in cit["code_excerpt"]
    assert cit["access"]["url"].endswith("#L41-L58")
    # Skill-specific explanation + relevance (never one generic sentence).
    assert "risk classifier" in cit["explanation"]
    assert "rerouting" in cit["relevance"]


def test_route_decorator_shell_is_weak_signal_and_never_counts() -> None:
    cem = _map(_skill_report([_chain(github_evidence=[_route_shell_item()])]))
    [cit] = [c for c in cem["citations"] if c["proof_type"] == "GitHub Proof"]
    assert cit["github_tier"] == "weak_signal"
    assert cit["counted_as_direct_evidence"] is False
    claim = cem["claims"][0]
    assert claim["qualitative_status"] in {"Context only", "Insufficient evidence"}
    assert claim["strongest_evidence_tier"] != "Primary implementation"


@pytest.mark.parametrize(
    ("grade", "tier"),
    [
        ("implementation_body", "primary_implementation"),
        ("supporting_logic", "supporting_implementation"),
        ("config_or_constant", "configuration_context"),
        ("comment_or_docstring", "weak_signal"),
        ("import_only", "weak_signal"),
        ("route_decorator_only", "weak_signal"),
        ("repo_level_fallback", "weak_signal"),
    ],
)
def test_grade_to_tier_table(grade: str, tier: str) -> None:
    got, _ = classify_github_tier(_gh_item(evidence_quality_grade=grade))
    assert got == tier


def test_repo_level_display_mode_caps_to_weak_signal() -> None:
    tier, _ = classify_github_tier(_gh_item(display_mode="repo_level"))
    assert tier == "weak_signal"


def test_cross_family_context_relevance_is_not_relevant() -> None:
    tier, _ = classify_github_tier(_gh_item(skill_relevance_key="product_ui_context"))
    assert tier == "not_relevant"


def test_github_citation_maps_to_code_symbol_feature() -> None:
    cem = _map(_skill_report([_chain(github_evidence=[_gh_item()])]))
    [feat] = [f for f in cem["features"] if f["feature_type"] == "code_symbol"]
    assert feat["title"] == "train_model() · train.py"
    assert "train.py" in feat["repo_paths"]
    [cit] = [c for c in cem["citations"] if c["proof_type"] == "GitHub Proof"]
    assert cit["feature_id"] == feat["id"]
    assert feat["id"] in cem["claims"][0]["feature_ids"]


# ── Website identity validation ────────────────────────────────────────────────


def test_veribridge_recording_attached_to_boston_is_mismatched() -> None:
    state, reasons = classify_website_identity(
        identity_texts=["VeriBridge AI", "VeriBridge AI — Work Passport"],
        target_domain=None,
        project_title=BOSTON,
        repo_name="boston-rerouting",
    )
    assert state == "mismatched"
    assert any("does not match" in r for r in reasons)


def test_matching_identity_tokens_classify_as_matched() -> None:
    state, _ = classify_website_identity(
        identity_texts=["Boston Accident Risk Rerouting"],
        target_domain=None,
        project_title=BOSTON,
        repo_name="boston-rerouting",
    )
    assert state == "matched_direct"


def test_deployed_domain_match_classifies_as_matched() -> None:
    state, _ = classify_website_identity(
        identity_texts=[],
        target_domain="boston-reroute.fly.dev",
        project_title=BOSTON,
        repo_name="other",
        deployed_url="https://boston-reroute.fly.dev",
    )
    assert state == "matched_direct"


def test_no_identity_signal_requires_review_never_counts() -> None:
    state, reasons = classify_website_identity(
        identity_texts=["", None],  # type: ignore[list-item]
        target_domain=None,
        project_title=BOSTON,
        repo_name="boston-rerouting",
    )
    assert state == "possible_match_review"
    assert any("attachment-only" in r for r in reasons)


def test_mismatched_recording_is_visible_flagged_and_not_counted() -> None:
    cem = _map(
        _skill_report(
            [_chain(github_evidence=[_gh_item()], website_evidence=[_web_item(app_context="VeriBridge AI")])]
        )
    )
    [web] = [c for c in cem["citations"] if c["proof_type"] == "Website Proof"]
    # Preserved and visible — never silently deleted or moved.
    assert web["identity_state"] == "mismatched"
    assert web["counted_as_direct_evidence"] is False
    assert web["identity_reasons"]
    # A visible contradiction with an owner action, and a claim limitation.
    assert cem["contradictions"], "mismatch must surface as a contradiction"
    contra = cem["contradictions"][0]
    assert web["evidence_id"] in contra["evidence_ids"]
    assert "detach" in contra["recommended_action"]
    assert any("identity check" in lim for lim in cem["claims"][0]["limitations"])


def test_mismatched_recording_creates_no_corroboration() -> None:
    # Primary GitHub + mismatched website: NO corroboration group may form.
    cem = _map(
        _skill_report(
            [_chain(github_evidence=[_gh_item()], website_evidence=[_web_item(app_context="VeriBridge AI")])]
        )
    )
    assert cem["corroborations"] == []
    # The GitHub implementation still counts on its own.
    assert cem["claims"][0]["qualitative_status"] == "Partially demonstrated"


def test_matched_recording_with_direct_relevance_counts_and_corroborates() -> None:
    cem = _map(
        _skill_report(
            [
                _chain(
                    github_evidence=[_gh_item()],
                    website_evidence=[
                        _web_item(
                            app_context="Boston Accident Risk Rerouting",
                            relevance_key="data_visualization_evidence",
                        )
                    ],
                )
            ]
        )
    )
    [web] = [c for c in cem["citations"] if c["proof_type"] == "Website Proof"]
    assert web["identity_state"] == "matched_direct"
    assert web["counted_as_direct_evidence"] is True
    [group] = cem["corroborations"]
    assert set(group["sources"]) == {"GitHub Proof", "Website Proof"}
    assert "claim level" in group["alignment_reason"]
    assert cem["claims"][0]["qualitative_status"] == "Demonstrated"


def test_matched_identity_with_context_relevance_still_does_not_count() -> None:
    # Identity matches the project, but the observed behaviour is product
    # CONTEXT for this skill (an ML report looking at a UI demo) — visible,
    # never counted, never corroborating.
    cem = _map(
        _skill_report(
            [
                _chain(
                    github_evidence=[_gh_item()],
                    website_evidence=[
                        _web_item(app_context="Boston Accident Risk Rerouting", relevance_key="ml_product_context")
                    ],
                )
            ]
        )
    )
    [web] = [c for c in cem["citations"] if c["proof_type"] == "Website Proof"]
    assert web["counted_as_direct_evidence"] is False
    assert cem["corroborations"] == []


# ── Corroboration rules ────────────────────────────────────────────────────────


def test_same_project_attachment_alone_never_corroborates() -> None:
    # A weak route shell + a locator-less document share the project — neither
    # counts, so nothing corroborates.
    cem = _map(
        _skill_report(
            [
                _chain(
                    github_evidence=[_route_shell_item()],
                    document_correlations=[
                        _doc_correlation(page_number=None, section_label=None, citation=None)
                    ],
                )
            ]
        )
    )
    assert cem["corroborations"] == []
    assert cem["claims"][0]["qualitative_status"] in {"Context only", "Insufficient evidence"}


def test_corroboration_group_states_alignment_and_unique_contributions() -> None:
    cem = _map(
        _skill_report(
            [
                _chain(
                    github_evidence=[_gh_item()],
                    document_correlations=[_doc_correlation()],
                    project_defense_inspection=[_defense_card()],
                )
            ]
        )
    )
    [group] = cem["corroborations"]
    assert set(group["sources"]) == {"GitHub Proof", "Document Proof", "Project Defense"}
    assert group["independent_sources"] is True
    assert len(group["unique_contributions"]) == 3
    assert group["alignment_reason"]
    assert group["limitations"]


def test_standalone_vault_bucket_never_corroborates() -> None:
    vault_chain = _chain(
        project_id=None,
        project_title="Student Proof Vault (not attached to a VBR project)",
        attached=False,
        github_evidence=[_gh_item(attached_project_ids=[])],
        document_correlations=[_doc_correlation()],
    )
    cem = _map(_skill_report([vault_chain]))
    assert cem["corroborations"] == []
    [claim] = cem["claims"]
    assert claim["claim_scope"] == "skill"
    assert any("never treated as corroborating" in lim for lim in claim["limitations"])


# ── Documents ──────────────────────────────────────────────────────────────────


def test_document_with_page_and_section_counts_as_design_evidence() -> None:
    cem = _map(_skill_report([_chain(document_correlations=[_doc_correlation()])]))
    [doc] = [c for c in cem["citations"] if c["proof_type"] == "Document Proof"]
    assert doc["counted_as_direct_evidence"] is True
    assert doc["page_number"] == 5
    assert doc["section_title"] == "Model architecture"
    assert "random-forest" in doc["transcript_excerpt"]
    [rel] = [r for r in cem["relations"] if r["source_evidence_id"] == doc["evidence_id"]]
    assert rel["relation_type"] == "explains_design"


def test_locatorless_document_is_context_with_honest_limitation() -> None:
    cem = _map(
        _skill_report(
            [_chain(document_correlations=[_doc_correlation(page_number=None, section_label=None, citation=None)])]
        )
    )
    [doc] = [c for c in cem["citations"] if c["proof_type"] == "Document Proof"]
    assert doc["counted_as_direct_evidence"] is False
    assert any("locator" in lim for lim in doc["limitations"])


def test_historical_unretained_document_shows_excerpts_only_access() -> None:
    cem = _map(_skill_report([_chain(document_correlations=[_doc_correlation(document_retained=False)])]))
    [doc] = [c for c in cem["citations"] if c["proof_type"] == "Document Proof"]
    access = doc["document_access"]
    assert access["retained"] is False
    assert access["excerpts_only"] is True
    assert access["open_available"] is False
    assert any("not retained" in lim for lim in access["limitations"])


def test_retained_shared_document_supports_open_and_download() -> None:
    cem = _map(
        _skill_report(
            [_chain(document_correlations=[_doc_correlation(document_retained=True, full_document_available=True)])]
        )
    )
    [doc] = [c for c in cem["citations"] if c["proof_type"] == "Document Proof"]
    access = doc["document_access"]
    assert access == {
        "retained": True,
        "excerpts_only": False,
        "open_available": True,
        "download_available": True,
        "publication_state": "published",
        "original_filename": None,
        "mime_type": None,
        "limitations": [],
    }


# ── Project Defense ────────────────────────────────────────────────────────────


def test_pending_defense_renders_but_never_counts() -> None:
    chain = _chain(
        defense_evidence=[{"proof_type": "Project Defense", "source_id": "s1"}],
        project_defense_inspection=[],
    )
    cem = _map(_skill_report([chain]))
    [cit] = [c for c in cem["citations"] if c["proof_type"] == "Project Defense"]
    assert cit["analysis_pending"] is True
    assert cit["counted_as_direct_evidence"] is False
    assert "analysis pending" in cit["explanation"].lower()
    assert cem["claims"][0]["qualitative_status"] == "Analysis pending"
    assert any(g["proof_type"] == "Project Defense" and "not yet analyzed" in g["description"] for g in cem["gaps"])


def test_analyzed_skill_mapped_defense_counts_with_timestamped_transcript() -> None:
    cem = _map(_skill_report([_chain(project_defense_inspection=[_defense_card()])]))
    [cit] = [c for c in cem["citations"] if c["proof_type"] == "Project Defense"]
    assert cit["counted_as_direct_evidence"] is True
    assert cit["question_text"].startswith("How did you train")
    assert cit["timestamp_start_label"] == "02:10"
    assert "random forest" in cit["transcript_excerpt"]
    # Canonical video descriptor drives playback state — retained, no URL stored.
    assert cit["video"]["proof_type"] == "Project Defense"
    assert cit["video"]["recording_available"] is True
    assert cit["video"]["cited_segments"][0]["start_label"] == "02:10"


def test_unmapped_defense_card_is_context_only() -> None:
    cem = _map(
        _skill_report(
            [_chain(project_defense_inspection=[_defense_card(mapped_skill=None, qualitative_status="Not explained")])]
        )
    )
    [cit] = [c for c in cem["citations"] if c["proof_type"] == "Project Defense"]
    assert cit["counted_as_direct_evidence"] is False


# ── Stability, honesty, and shared-model guarantees ────────────────────────────


def test_empty_chain_yields_stable_gap_sections_not_crashes() -> None:
    cem = _map(_skill_report([_chain()]))
    [claim] = cem["claims"]
    assert claim["qualitative_status"] == "Insufficient evidence"
    gap_types = {g["proof_type"] for g in cem["gaps"]}
    assert {"GitHub Proof", "Website Proof", "Document Proof", "Project Defense"} <= gap_types


def test_partial_historical_rows_degrade_to_limitations() -> None:
    # A legacy GitHub row with nothing but a summary must not crash and must
    # carry the honest no-locator limitation.
    legacy = {"proof_type": "GitHub Proof", "source_id": "old", "safe_summary": "old row"}
    cem = _map(_skill_report([_chain(github_evidence=[legacy])]))
    [cit] = [c for c in cem["citations"] if c["proof_type"] == "GitHub Proof"]
    assert cit["counted_as_direct_evidence"] is False
    assert any("No file/line-level" in lim for lim in cit["limitations"])


def test_no_numeric_scores_and_only_closed_status_vocabulary() -> None:
    cem = _map(
        _skill_report(
            [
                _chain(
                    github_evidence=[_gh_item()],
                    website_evidence=[_web_item(app_context="VeriBridge AI")],
                    document_correlations=[_doc_correlation()],
                    project_defense_inspection=[_defense_card()],
                )
            ]
        )
    )
    for claim in cem["claims"]:
        assert claim["qualitative_status"] in QUALITATIVE_STATES
    payload = json.dumps(cem)
    assert not re.search(r"(?i)\b(trust|confidence)[ _-]?score\b", payload)
    assert "/100" not in payload


def test_skill_report_response_carries_the_map() -> None:
    report_dict = _skill_report([_chain(github_evidence=[_gh_item()])])
    cem = _map(report_dict)
    # The response schema accepts the canonical map (and None for legacy rows).
    resp = SkillReportResponse(
        skill="Machine Learning",
        overview={"skill": "Machine Learning"},
        claim_evidence_map=cem,
    )
    assert resp.claim_evidence_map is not None
    assert SkillReportResponse(skill="X", overview={"skill": "X"}).claim_evidence_map is None


# ── Project Report entry point (same canonical model) ─────────────────────────


def _project_report(**overrides) -> dict:
    report = {
        "project_id": "p1",
        "project_title": BOSTON,
        "repo_full_name": "octocat/boston-rerouting",
        "deployed_url": None,
        "evidence_package": {"project_defense_completed": False},
        "project_defense_analysis": None,
        "website_skill_evidence": [],
        "skill_evidence": [
            {
                "skill": "Machine Learning",
                "status": "Evidence observed",
                "evidence_traces": ["t-gh", "t-web"],
                "limitations": [],
            }
        ],
        "evidence_traces": [
            {
                "trace_id": "t-gh",
                "source_type": "GitHub Proof",
                "source_title": "octocat/boston-rerouting",
                "file_path": "train.py",
                "line_start": 41,
                "line_end": 58,
                "function_name": "train_model",
                "commit_sha": "abc123def456",
                "code_snippet": "model.fit(X_train, y_train)",
                "public_url": "https://github.com/octocat/boston-rerouting/blob/main/train.py#L41-L58",
                "public_url_label": "View code lines",
                "is_publicly_openable": True,
                "safe_summary": "Model training implementation.",
                "safe_detail": "Trains the risk classifier.",
                "limitation": "",
            },
            {
                "trace_id": "t-web",
                "source_type": "Website Proof",
                "source_title": "http://localhost:3000",
                "location_label": "Live URL",
                "safe_summary": "Recorded workflow.",
                "safe_detail": "",
                "limitation": "",
                "is_publicly_openable": False,
            },
        ],
        "limitations": [],
    }
    report.update(overrides)
    return report


def _pmap(report: dict) -> dict:
    out = build_project_claim_evidence_map(report)
    ClaimEvidenceMap(**out)
    return out


def test_project_map_uses_same_canonical_model_with_exact_github_citation() -> None:
    cem = _pmap(_project_report())
    assert cem["scope"] == "project_report"
    [claim] = cem["claims"]
    assert claim["skill_name"] == "Machine Learning"
    [gh] = [c for c in cem["citations"] if c["proof_type"] == "GitHub Proof"]
    assert gh["counted_as_direct_evidence"] is True
    assert gh["github_tier"] == "primary_implementation"
    assert (gh["file_path"], gh["start_line"], gh["end_line"]) == ("train.py", 41, 58)
    assert gh["access"]["url"].endswith("#L41-L58")


def test_project_map_flags_mismatched_veribridge_recording() -> None:
    report = _project_report(
        website_skill_evidence=[
            {
                "target_website": "http://localhost:3000",
                "app_context": "VeriBridge AI",
                "page_context_label": "",
                "behavior_claim": "",
                "target_domain": "",
            }
        ]
    )
    cem = _pmap(report)
    [web] = [c for c in cem["citations"] if c["proof_type"] == "Website Proof"]
    assert web["identity_state"] == "mismatched"
    assert web["counted_as_direct_evidence"] is False
    assert cem["contradictions"]
    assert cem["corroborations"] == []  # GitHub alone cannot corroborate
    assert cem["claims"][0]["qualitative_status"] == "Partially demonstrated"
    assert any("identity check" in lim for lim in cem["claims"][0]["limitations"])


def test_project_map_website_without_identity_needs_review_not_counted() -> None:
    cem = _pmap(_project_report())
    [web] = [c for c in cem["citations"] if c["proof_type"] == "Website Proof"]
    assert web["identity_state"] == "possible_match_review"
    assert web["counted_as_direct_evidence"] is False


def test_project_map_repo_level_trace_is_weak_and_not_counted() -> None:
    report = _project_report()
    report["evidence_traces"][0] = {
        "trace_id": "t-gh",
        "source_type": "GitHub Proof",
        "source_title": "octocat/boston-rerouting",
        "location_type": "repo_level",
        "safe_summary": "Repository-level evidence.",
        "limitation": "",
    }
    cem = _pmap(report)
    [gh] = [c for c in cem["citations"] if c["proof_type"] == "GitHub Proof"]
    assert gh["github_tier"] == "weak_signal"
    assert gh["counted_as_direct_evidence"] is False


def test_project_map_pending_defense_state_is_explicit_and_uncounted() -> None:
    report = _project_report(
        evidence_package={"project_defense_completed": True},
        project_defense_analysis=None,
    )
    cem = _pmap(report)
    pend = [c for c in cem["citations"] if c["proof_type"] == "Project Defense"]
    assert pend and all(c["analysis_pending"] and not c["counted_as_direct_evidence"] for c in pend)
    assert any(g["proof_type"] == "Project Defense" for g in cem["gaps"])


# ── End-to-end through the real report builders (in-memory DB) ────────────────


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def pipeline_db() -> dict:
    return {}


def test_collect_skill_report_embeds_canonical_map(mem_store: dict, pipeline_db: dict) -> None:
    """The real Skill Report pipeline embeds a valid canonical map whose GitHub
    citation carries the exact stored file/line locators."""
    from tests.test_student_proof_vault import _seed_project  # shared seed helper
    from tests.test_vbr_project_defense import USER_ID, _seed_github_proof
    from app.services.student_proof_vault_service import collect_skill_report

    gh_id = _seed_github_proof(
        mem_store,
        detected_skills=["Machine Learning"],
        submitted_skill_claims=["Machine Learning"],
        analysis_snapshot={
            "skill_code_evidence": [
                {
                    "skill": "Machine Learning",
                    "file_path": "train.py",
                    "line_start": 41,
                    "line_end": 58,
                    "code_snippet": "model.fit(X_train, y_train)",
                }
            ]
        },
    )
    _seed_project(
        mem_store,
        title=BOSTON,
        repo_full_name="octocat/Hello-World",
        attached_proofs={"github_proof": {"github_proof_id": gh_id}},
    )

    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "machine-learning", synthesize=False)
    cem = report["claim_evidence_map"]
    ClaimEvidenceMap(**cem)
    assert cem["scope"] == "skill_report"
    assert cem["skill_name"] == "Machine Learning"
    assert cem["claims"], "a claim must exist for the connected project"
    gh_cits = [c for c in cem["citations"] if c["proof_type"] == "GitHub Proof" and c["file_path"]]
    assert any((c["file_path"], c["start_line"], c["end_line"]) == ("train.py", 41, 58) for c in gh_cits)
    # The whole response (including the map) validates against the contract.
    SkillReportResponse(**report)


def test_build_student_vbr_report_embeds_canonical_map(mem_store: dict, pipeline_db: dict) -> None:
    from tests.test_student_proof_vault import _seed_project
    from tests.test_vbr_project_defense import USER_ID, _seed_github_proof
    from app.services.vbr_student_report import build_student_vbr_report

    gh_id = _seed_github_proof(mem_store, detected_skills=["Python"])
    pid = _seed_project(
        mem_store,
        title=BOSTON,
        repo_full_name="octocat/Hello-World",
        attached_proofs={"github_proof": {"github_proof_id": gh_id}},
    )
    mem_store["vbr_projects"][pid]["metadata"]["claimed_skills"] = ["Python"]

    project = mem_store["vbr_projects"][pid]
    report = build_student_vbr_report(mem_store, pipeline_db, project, USER_ID)
    cem = report["claim_evidence_map"]
    assert cem is not None
    ClaimEvidenceMap(**cem)
    assert cem["scope"] == "project_report"
    assert [c["skill_name"] for c in cem["claims"]] == ["Python"]

    # The passport path (include_cross_proof=False) skips the map entirely.
    fast = build_student_vbr_report(mem_store, pipeline_db, project, USER_ID, include_cross_proof=False)
    assert fast["claim_evidence_map"] is None


def test_project_map_route_decorator_at_exact_lines_never_counts() -> None:
    """Regression (real Boston data): the analyzer's only ML row is
    ``api.py L252–L255 @app.post("/predict")`` — a route shell at exact lines.
    Line-level presence alone must not make it implementation proof, and it
    must never corroborate the document into a 'Corroborated' ML claim."""
    report = _project_report()
    report["evidence_traces"][0] = {
        "trace_id": "t-gh",
        "source_type": "GitHub Proof",
        "source_title": "octocat/boston-rerouting",
        "file_path": "api.py",
        "line_start": 252,
        "line_end": 255,
        "function_name": "predict",
        "code_snippet": '@app.post("/predict")\ndef predict(request: PredictRequest):',
        "safe_summary": "API route.",
        "limitation": "",
    }
    cem = _pmap(report)
    [gh] = [c for c in cem["citations"] if c["proof_type"] == "GitHub Proof"]
    assert gh["github_tier"] == "weak_signal"
    assert gh["counted_as_direct_evidence"] is False
    assert cem["corroborations"] == []
    assert cem["claims"][0]["qualitative_status"] != "Corroborated"


# ── Project Report document citations are block-aware ─────────────────────────


def _doc_trace(**overrides) -> dict:
    trace = {
        "trace_id": "t-doc",
        "source_type": "Document Proof",
        "source_title": "Boston Rerouting Project Report",
        "page_number": 7,
        "citation": None,
        "snippet": "The evaluation table compares model variants.",
        "safe_summary": "Document matched to the skill with a page locator.",
        "safe_detail": "",
        "limitation": "",
        "is_publicly_openable": False,
    }
    trace.update(overrides)
    return trace


def _project_report_with_doc(**doc_overrides) -> dict:
    report = _project_report()
    report["skill_evidence"][0]["evidence_traces"] = ["t-gh", "t-doc"]
    report["evidence_traces"].append(_doc_trace(**doc_overrides))
    return report


def test_project_map_document_citation_carries_block_locator() -> None:
    """[Document · Page 7 · Table] — an explicit "Table …" reference classifies
    as a table block with the stored page number; nothing is invented."""
    cem = _pmap(_project_report_with_doc(citation="Table 2 — model comparison"))
    [doc] = [c for c in cem["citations"] if c["proof_type"] == "Document Proof"]
    assert doc["counted_as_direct_evidence"] is True
    block = doc["document_block"]
    assert block is not None
    assert block["block_type"] == "table"
    assert block["page_number"] == 7
    assert doc["citation_type"] == "document_table"
    assert block["extracted_text"] == "The evaluation table compares model variants."


def test_project_map_document_architecture_diagram_block() -> None:
    cem = _pmap(_project_report_with_doc(citation="Figure 3 — architecture diagram"))
    [doc] = [c for c in cem["citations"] if c["proof_type"] == "Document Proof"]
    assert doc["document_block"]["block_type"] == "architecture_diagram"
    assert doc["citation_type"] == "document_architecture_diagram"


def test_project_map_ambiguous_figure_fails_closed_to_unknown_visual_region() -> None:
    """An ambiguous "Figure 5" is never promoted to a readable chart: it stays an
    unknown visual region and carries the honest extraction limitation."""
    cem = _pmap(_project_report_with_doc(citation="Figure 5"))
    [doc] = [c for c in cem["citations"] if c["proof_type"] == "Document Proof"]
    block = doc["document_block"]
    assert block["block_type"] == "unknown_visual_region"
    assert block["model_limitation"]


def test_project_map_document_prose_defaults_to_paragraph_block() -> None:
    cem = _pmap(_project_report_with_doc(citation=None))
    [doc] = [c for c in cem["citations"] if c["proof_type"] == "Document Proof"]
    assert doc["document_block"]["block_type"] == "paragraph"
    assert doc["counted_as_direct_evidence"] is True  # page locator still counts


def test_project_map_document_without_locator_not_counted_and_still_block_typed() -> None:
    cem = _pmap(_project_report_with_doc(page_number=None, citation=None))
    [doc] = [c for c in cem["citations"] if c["proof_type"] == "Document Proof"]
    assert doc["counted_as_direct_evidence"] is False
    assert doc["document_block"]["block_type"] == "paragraph"
    assert doc["document_block"]["page_number"] is None


# ── Honest source counts + duplicate/grouped-context handling ─────────────────
# (skill-evidence-map-fix: exact proof counts, video-of-defense dedup, weak
#  repo-level context grouped ONCE for the whole report.)


def test_claim_source_counts_split_direct_and_corroborating() -> None:
    cem = _map(
        _skill_report(
            [
                _chain(
                    github_evidence=[_gh_item()],
                    project_defense_inspection=[_defense_card()],
                )
            ]
        )
    )
    [claim] = cem["claims"]
    counts = claim["source_counts"]
    # GitHub primary implementation is THE direct source; the analyzed defense
    # is corroborating — never a second "direct proof".
    assert counts["direct"] == 1 and counts["direct_sources"] == ["GitHub Proof"]
    assert counts["corroborating"] == 1 and counts["corroborating_sources"] == ["Project Defense"]
    assert counts["pending"] == 0
    # Map-level union agrees.
    assert cem["source_counts"]["direct_sources"] == ["GitHub Proof"]


def test_pending_defense_is_counted_only_in_pending_bucket() -> None:
    cem = _map(
        _skill_report(
            [
                _chain(
                    github_evidence=[_gh_item()],
                    defense_evidence=[{"session_id": "s1"}],  # captured, unanalyzed
                )
            ]
        )
    )
    [claim] = cem["claims"]
    counts = claim["source_counts"]
    assert counts["pending"] == 1 and counts["pending_sources"] == ["Project Defense"]
    assert "Project Defense" not in counts["direct_sources"]
    assert "Project Defense" not in counts["corroborating_sources"]


def test_weak_repo_context_is_grouped_once_across_claims() -> None:
    weak = _route_shell_item()
    cem = _map(
        _skill_report(
            [
                _chain(github_evidence=[_gh_item(), weak.copy()]),
                _chain(
                    project_id="p2",
                    project_title="Second project",
                    github_evidence=[weak.copy()],
                ),
            ]
        )
    )
    grouped = [c for c in cem["citations"] if c.get("grouped_context")]
    # The identical weak signal appears exactly ONCE, detached from any claim.
    assert len(grouped) == 1
    assert grouped[0]["claim_id"] is None
    assert any("grouped once" in lim.lower() for lim in grouped[0]["limitations"])
    weak_still_in_claims = [
        c
        for c in cem["citations"]
        if c["proof_type"] == "GitHub Proof"
        and c.get("github_tier") in ("weak_signal", "not_relevant")
        and c.get("claim_id")
    ]
    assert weak_still_in_claims == []
    # The counted primary citation is untouched.
    counted = [c for c in cem["citations"] if c["counted_as_direct_evidence"]]
    assert len(counted) == 1 and counted[0]["file_path"] == "train.py"


def test_video_chip_into_same_defense_recording_is_never_second_source() -> None:
    report = _project_report(
        evidence_package={"project_defense_completed": True},
        project_defense_analysis={"summary": "analyzed"},
        skill_evidence=[
            {
                "skill": "Machine Learning",
                "status": "Evidence observed",
                "evidence_traces": ["t-def", "t-vid"],
                "limitations": [],
            }
        ],
        evidence_traces=[
            {
                "trace_id": "t-def",
                "source_type": "Project Defense",
                "source_title": "Project Defense — Boston",
                "question_text": "How did you train the model?",
                "answer_excerpt": "We trained a random forest…",
                "timestamp_label": "02:14",
                "safe_summary": "Explained the training pipeline.",
                "safe_detail": "",
                "limitation": "",
                "is_publicly_openable": False,
            },
            {
                "trace_id": "t-vid",
                "source_type": "Video Evidence",
                "source_title": "Video 02:14",
                "timestamp_label": "02:14",
                "safe_summary": "Timestamped defense moment.",
                "safe_detail": "",
                "limitation": "",
                "is_publicly_openable": False,
            },
        ],
    )
    cem = _pmap(report)
    [claim] = cem["claims"]
    video = next(c for c in cem["citations"] if c["proof_type"] == "Video Evidence")
    defense = next(c for c in cem["citations"] if c["proof_type"] == "Project Defense")
    assert video["duplicate_of_evidence_id"] == defense["evidence_id"]
    assert video["counted_as_direct_evidence"] is False
    counts = claim["source_counts"]
    assert "Video Evidence" not in (
        counts["direct_sources"]
        + counts["corroborating_sources"]
        + counts["context_only_sources"]
    )
    assert counts["direct_sources"] == ["Project Defense"]


def test_document_block_locators_flow_into_project_map_cards() -> None:
    report = _project_report(
        skill_evidence=[
            {
                "skill": "FastAPI",
                "status": "Evidence observed",
                "evidence_traces": ["t-doc"],
                "limitations": [],
            }
        ],
        evidence_traces=[
            {
                "trace_id": "t-doc",
                "source_type": "Document Proof",
                "source_title": "VeriBridge Rich Document Proof Test",
                "page_number": None,
                "citation": "Architecture",
                "snippet": "API | FastAPI",
                "block_type": "table",
                "block_index": 7,
                "table_cells": [["Component", "Technology"], ["API", "FastAPI"]],
                "visual_description": None,
                "nearby_caption": None,
                "figure_reference": None,
                "has_exact_locator": True,
                "safe_summary": "Architecture table names FastAPI.",
                "safe_detail": "",
                "limitation": "",
                "is_publicly_openable": False,
            }
        ],
    )
    cem = _pmap(report)
    [doc] = [c for c in cem["citations"] if c["proof_type"] == "Document Proof"]
    assert doc["counted_as_direct_evidence"] is True
    block = doc["document_block"]
    assert block["block_type"] == "table"
    assert block["table_cells"] == [["Component", "Technology"], ["API", "FastAPI"]]
    assert doc["citation_type"] == "document_table"


def test_keyword_only_document_trace_never_counts_in_project_map() -> None:
    report = _project_report(
        skill_evidence=[
            {
                "skill": "Data Analysis",
                "status": "Evidence observed",
                "evidence_traces": ["t-doc"],
                "limitations": [],
            }
        ],
        evidence_traces=[
            {
                "trace_id": "t-doc",
                "source_type": "Document Proof",
                "source_title": "Some report",
                "page_number": None,
                "citation": None,
                "snippet": "Data analysis matters.",
                "block_type": None,
                "has_exact_locator": False,
                "safe_summary": "Mentions data analysis.",
                "safe_detail": "",
                "limitation": "",
                "is_publicly_openable": False,
            }
        ],
    )
    cem = _pmap(report)
    [doc] = [c for c in cem["citations"] if c["proof_type"] == "Document Proof"]
    assert doc["counted_as_direct_evidence"] is False
    [claim] = cem["claims"]
    assert claim["source_counts"]["direct"] == 0
    assert claim["source_counts"]["context_only_sources"] == ["Document Proof"]
