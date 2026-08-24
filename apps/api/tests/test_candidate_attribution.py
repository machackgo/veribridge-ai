"""Candidate ownership / claim-attribution integrity — adversarial regression suite.

Core trust rule under test: PROJECT EVIDENCE != CANDIDATE OWNERSHIP.

Regression case: the Excalidraw end-to-end test — a candidate demonstrated the
public Excalidraw project through VeriBridge's proof system while EXPLICITLY
denying authorship ("I did not personally build or contribute to Excalidraw"),
yet the generated report claimed "React was implemented and demonstrated in
excalidraw" and labelled defense answers "Authorship explanation".

Scenario coverage (per the trust-model spec):
  A — third-party project + explicit denial: technology/runtime/understanding
      evidence allowed; candidate implementation claims blocked.
  B — verified candidate attribution evidence: strong claims allowed.
  C — unknown ownership: project claims allowed, candidate claims withheld.
  D — candidate self-assertion: represented as CLAIMED, never auto-verified.
  E — explicit denial represented correctly (honest, shareable, never punished).
  F — conflicting ownership evidence: surfaced, strong claims blocked, never
      auto-resolved in the candidate's favour.
  G/H — multi-source project corroboration never manufactures candidate-level
      attribution; corroboration preserves the claim's project subject.
  I — recruiter-safe wording: the ambiguous sentences cannot appear.
  J — control: a legitimately candidate-claimed project keeps strong project
      statuses and gains an honest claimed-contribution attribution.

Everything is deterministic and in-memory — no network / LLM calls.
"""

from __future__ import annotations

import json

from app.schemas.canonical_evidence import ClaimEvidenceMap
from app.services.candidate_attribution_service import (
    assess_project_ownership,
    build_candidate_attribution,
    detect_ownership_stance,
    ownership_blocks_candidate_implementation,
)
from app.services.claim_evidence_synthesis_service import (
    build_project_claim_evidence_map,
    build_skill_claim_evidence_map,
)
from app.services.defense_answer_evidence_service import (
    OWNERSHIP_DENIAL_LIMITATION,
    ROLE_OWNERSHIP_CLARIFICATION,
    build_defense_answer_evidence,
)
from app.services.project_defense_analysis_service import analyze_defense_transcript
from app.services.project_defense_inspection_service import (
    build_project_defense_inspection_cards,
)

EXCALIDRAW = "excalidraw"

# ── Fixture builders ───────────────────────────────────────────────────────────


def _gh_item(**overrides) -> dict:
    item = {
        "proof_type": "GitHub Proof",
        "source_id": "gh-1",
        "title": "excalidraw/excalidraw",
        "safe_summary": "React component implementation.",
        "safe_location": "src/components/App.tsx",
        "safe_snippet": "export const App = () => {\n  const [state, setState] = useState(initial)\n  return <Canvas … />\n}",
        "file_path": "src/components/App.tsx",
        "line_start": 100,
        "line_end": 140,
        "function_name": "App",
        "commit_sha": "abc123def456",
        "display_mode": "code_line",
        "evidence_quality_grade": "implementation_body",
        "skill_relevance_key": "direct_react_evidence",
        "skill_relevance_summary": "Implements the main React component tree.",
        "code_block_purpose_summary": "Renders the canvas application shell.",
        "github_line_url": "https://github.com/excalidraw/excalidraw/blob/master/src/components/App.tsx#L100-L140",
        "limitation": "",
        "attached_project_ids": ["p1"],
    }
    item.update(overrides)
    return item


def _web_item(**overrides) -> dict:
    item = {
        "proof_type": "Website Proof",
        "source_id": "web-1",
        "title": "Recorded session",
        "safe_summary": "Recorded drawing workflow.",
        "website_skill_relevance_key": "react_evidence",
        "website_skill_relevance_summary": "Interactive canvas behaviour observed.",
        "workflow_steps": ["Draw a rectangle", "Shape renders"],
        "attached_project_ids": ["p1"],
        "website_evidence_card": {
            "card_key": "w1",
            "route_or_page": "Recorded session",
            "page_title": "Excalidraw",
            "app_context": "Excalidraw whiteboard",
            "target_domain": None,
            "behavior_claim": "Drawing input renders shapes interactively.",
            "user_action_observed": "User draws shapes.",
            "output_observed": "Shapes render on the canvas.",
            "skill_relevance_key": "react_evidence",
            "skill_relevance_summary": "Interactive canvas behaviour observed.",
            "website_purpose_key": "interactive_canvas",
            "website_purpose_label": "Interactive canvas",
            "is_public_live_url": False,
            "is_local_or_private_url": True,
            "verification_mode_label": "Recorded replay only",
            "verification_note": "",
            "screenshot_available": False,
            "limitation": "Runtime behaviour alone does not prove authorship.",
        },
        "limitation": "",
    }
    item.update(overrides)
    return item


def _doc_correlation(**overrides) -> dict:
    doc = {
        "source_id": "doc-1",
        "document_title": "Excalidraw architecture notes",
        "page_number": 2,
        "section_label": "Rendering architecture",
        "citation": "Section 2 Rendering architecture",
        "figure_reference": None,
        "safe_snippet": "The canvas is a React component tree with a custom renderer.",
        "corroborates": "GitHub implementation",
        "correlation_confidence": "direct attachment",
        "why_supported": "Describes the React rendering architecture.",
        "reason": "",
        "limitation": "",
        "document_retained": False,
        "full_document_available": False,
    }
    doc.update(overrides)
    return doc


def _defense_card(
    *,
    stance: str = "none",
    status: str = "Explained with evidence",
    mapped_skill: str | None = "React",
    claim_type: str = "skill_understanding",
    summary: str = "Explained the React component architecture and state flow.",
    **overrides,
) -> dict:
    card = {
        "evidence_id_safe": "def-1",
        "question_text": "Explain how this project demonstrates React.",
        "project_title": EXCALIDRAW,
        "mapped_skill": mapped_skill,
        "claim_type": claim_type,
        "qualitative_status": status,
        "ownership_stance": stance,
        "contradiction_flag": False,
        "safe_answer_summary": summary,
        "what_this_demonstrates": "Understanding of the React architecture.",
        "timestamp_label": "01:10",
        "clip_available": False,
        "video_available": False,
        "video_playback_url": None,
        "transcript_excerpt_available": False,
        "limitation": "Self-explanation — not independent proof of authorship.",
        "recording_access_note": "",
        "transcript_access_note": "",
    }
    card.update(overrides)
    return card


def _chain(**overrides) -> dict:
    chain = {
        "project_id": "p1",
        "project_title": EXCALIDRAW,
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


def _skill_report(chains: list[dict], skill: str = "React") -> dict:
    return {"skill": skill, "skill_slug": "react", "projects": chains, "gaps": []}


_META = {"p1": {"title": EXCALIDRAW, "repo_full": "excalidraw/excalidraw", "repo_name": "excalidraw"}}


def _map(report: dict, meta: dict | None = None) -> dict:
    out = build_skill_claim_evidence_map(report, project_meta=meta or _META)
    ClaimEvidenceMap(**out)
    return out


DENIAL_SUMMARY = (
    "I did not personally build or contribute to the Excalidraw repository; "
    "I am using this public project to demonstrate the proof workflow."
)
AFFIRM_SUMMARY = "I built the rerouting API and I implemented the model training pipeline."


# ── Ownership stance detection (unit) ─────────────────────────────────────────


def test_stance_detects_explicit_denials() -> None:
    for text in [
        "I did not personally design Excalidraw.",
        "I did not personally build or contribute to the Excalidraw repository.",
        "I didn't build this project.",
        "I have not contributed to this repository.",
        "This is not my project; it was built by the community.",
        "I am not a contributor to this repo.",
        "It was created by someone else.",
        "I do not claim to have built any of this.",
    ]:
        assert detect_ownership_stance(text) == "denied", text


def test_stance_detects_affirmations() -> None:
    for text in [
        "I built the API layer from scratch.",
        "I implemented the caching strategy.",
        "My contribution was the export feature.",
        "I was responsible for the deployment pipeline.",
    ]:
        assert detect_ownership_stance(text) == "affirmed", text


def test_stance_mixed_for_scoped_contribution() -> None:
    text = "I did not build the whole application, but I implemented the export feature."
    assert detect_ownership_stance(text) == "mixed"


def test_stance_none_for_neutral_explanations() -> None:
    for text in [
        "The application uses React with a custom canvas renderer.",
        "Requests flow through the API layer into the database.",
        "",
    ]:
        assert detect_ownership_stance(text) == "none", text


def test_denial_words_never_read_as_affirmation() -> None:
    # "not my project" contains the affirmation token "my project" — the denial
    # span must be masked before affirmation matching.
    assert detect_ownership_stance("This is not my project.") == "denied"


# ── Ownership state machine (unit) ─────────────────────────────────────────────


def _answer(stance: str, summary: str) -> dict:
    return {"ownership_stance": stance, "safe_answer_summary": summary}


def test_denial_yields_denied_state_and_blocks_implementation() -> None:
    ownership = assess_project_ownership(answer_items=[_answer("denied", DENIAL_SUMMARY)])
    assert ownership["state"] == "denied_by_candidate"
    assert ownership_blocks_candidate_implementation(ownership["state"])
    assert ownership["denial_statements"]


def test_self_assertion_caps_at_claimed_never_verified() -> None:
    # TEST D — candidate claims ownership without corroboration.
    ownership = assess_project_ownership(answer_items=[_answer("affirmed", AFFIRM_SUMMARY)])
    assert ownership["state"] == "claimed_contributor"
    attribution = build_candidate_attribution(ownership=ownership)
    assert attribution["label"] == "Contribution claimed (unverified)"
    assert "not independently verified" in attribution["candidate_claim_text"]
    assert any("not" in lim and "verifie" in lim for lim in attribution["limitations"])


def test_no_statements_yields_unknown() -> None:
    ownership = assess_project_ownership(answer_items=[])
    assert ownership["state"] == "unknown"
    assert ownership_blocks_candidate_implementation("unknown")


def test_verified_attribution_evidence_enables_strong_states() -> None:
    # TEST B — candidate-specific attribution evidence (stored repo analysis).
    contributor = assess_project_ownership(
        answer_items=[_answer("affirmed", AFFIRM_SUMMARY)],
        repo_analysis={"authorship_match_pct": 35.0},
    )
    assert contributor["state"] == "verified_contributor"
    author = assess_project_ownership(
        answer_items=[_answer("affirmed", AFFIRM_SUMMARY)],
        repo_analysis={"authorship_match_pct": 92.0},
    )
    assert author["state"] == "verified_author"
    assert not ownership_blocks_candidate_implementation(author["state"])


def test_verified_attribution_plus_denial_is_conflicted() -> None:
    # TEST F — conflicting ownership evidence is surfaced, never auto-resolved.
    ownership = assess_project_ownership(
        answer_items=[_answer("denied", DENIAL_SUMMARY)],
        repo_analysis={"authorship_match_pct": 92.0},
    )
    assert ownership["state"] == "conflicted"
    assert ownership_blocks_candidate_implementation("conflicted")


def test_placeholder_repo_analysis_never_verifies() -> None:
    # The placeholder ingestion stores None — it can never manufacture a
    # verified state.
    ownership = assess_project_ownership(
        answer_items=[_answer("affirmed", AFFIRM_SUMMARY)],
        repo_analysis={"authorship_match_pct": None, "fork": None},
    )
    assert ownership["state"] == "claimed_contributor"


def test_attribution_sentences_come_only_from_closed_templates() -> None:
    # Invariant: an implementation sentence is structurally impossible for a
    # non-attributed candidate.
    for state in ("unknown", "denied_by_candidate", "conflicted"):
        attribution = build_candidate_attribution(ownership={"state": state})
        text = attribution["candidate_claim_text"].lower()
        assert "not attributed" in text or "not established" in text
        assert "the candidate personally implemented" not in text
        assert "the candidate contributed to this implementation" not in text


# ── TEST A — the Excalidraw regression (third-party project + denial) ─────────


def _excalidraw_chain() -> dict:
    return _chain(
        github_evidence=[_gh_item()],
        website_evidence=[_web_item()],
        document_correlations=[_doc_correlation()],
        project_defense_inspection=[
            _defense_card(stance="denied", summary=DENIAL_SUMMARY + " The canvas is a React tree with a custom renderer and state management."),
            _defense_card(
                evidence_id_safe="def-2",
                stance="denied",
                status="Generic explanation",
                mapped_skill=None,
                claim_type="personal_contribution",
                summary=DENIAL_SUMMARY,
            ),
        ],
    )


def test_excalidraw_claim_text_is_project_scoped() -> None:
    cem = _map(_skill_report([_excalidraw_chain()]))
    [claim] = cem["claims"]
    assert claim["claim_text"] == "React is demonstrated in the project excalidraw."
    assert claim["claim_subject"] == "project"
    assert "was implemented and demonstrated" not in json.dumps(cem)


def test_excalidraw_denial_blocks_candidate_attribution() -> None:
    cem = _map(_skill_report([_excalidraw_chain()]))
    [claim] = cem["claims"]
    attribution = claim["candidate_attribution"]
    assert attribution["state"] == "denied_by_candidate"
    assert attribution["label"] == "Contribution explicitly not claimed"
    assert "did not build or contribute" in attribution["candidate_claim_text"]
    assert any("no candidate implementation claim" in lim for lim in claim["limitations"])


def test_excalidraw_keeps_project_and_understanding_evidence() -> None:
    # Technology detection, runtime evidence, and understanding evidence are all
    # preserved — only ownership attribution is blocked.
    cem = _map(_skill_report([_excalidraw_chain()]))
    [claim] = cem["claims"]
    assert claim["qualitative_status"] in {"Demonstrated", "Corroborated", "Partially demonstrated"}
    counted_defense = [
        c
        for c in cem["citations"]
        if c["proof_type"] == "Project Defense" and c["counted_as_direct_evidence"]
    ]
    assert counted_defense, "an explained answer still counts as understanding evidence"
    assert all(c["strength"] == "Understanding explanation" for c in counted_defense)
    assert claim["candidate_attribution"]["understanding_demonstrated"] is True


def test_no_authorship_explanation_label_anywhere() -> None:
    cem = _map(_skill_report([_excalidraw_chain()]))
    payload = json.dumps(cem)
    assert "Authorship explanation" not in payload
    assert "explains_authorship" not in payload


def test_pure_denial_card_is_ownership_clarification_not_counted() -> None:
    cem = _map(_skill_report([_excalidraw_chain()]))
    clarifications = [c for c in cem["citations"] if c["strength"] == "Ownership clarification"]
    assert clarifications
    assert all(not c["counted_as_direct_evidence"] for c in clarifications)
    assert any(
        r["relation_type"] == "clarifies_ownership"
        for r in cem["relations"]
        if r["source_evidence_id"] in {c["evidence_id"] for c in clarifications}
    )


# ── TEST C — unknown ownership ─────────────────────────────────────────────────


def test_unknown_ownership_allows_project_claim_withholds_candidate_claim() -> None:
    cem = _map(_skill_report([_chain(github_evidence=[_gh_item()])]))
    [claim] = cem["claims"]
    assert claim["qualitative_status"] == "Partially demonstrated"
    attribution = claim["candidate_attribution"]
    assert attribution["state"] == "unknown"
    assert "not established" in attribution["candidate_claim_text"]


# ── TEST G / H — corroboration preserves the project subject ──────────────────


def test_multi_source_corroboration_never_creates_candidate_attribution() -> None:
    # GitHub + Website + Document all show React → the PROJECT claim is
    # strongly supported, but candidate implementation stays unsupported.
    cem = _map(
        _skill_report(
            [
                _chain(
                    github_evidence=[_gh_item()],
                    website_evidence=[_web_item()],
                    document_correlations=[_doc_correlation()],
                )
            ]
        )
    )
    [claim] = cem["claims"]
    assert cem["corroborations"], "project-level corroboration is expected"
    assert claim["qualitative_status"] in {"Demonstrated", "Corroborated"}
    assert claim["candidate_attribution"]["state"] == "unknown"
    [group] = cem["corroborations"]
    assert any("never" in lim and "who built" in lim for lim in group["limitations"])


# ── TEST J — control: candidate-claimed project keeps strong project claims ───


def test_control_project_keeps_strong_statuses_with_claimed_attribution() -> None:
    chain = _chain(
        github_evidence=[_gh_item()],
        website_evidence=[_web_item()],
        document_correlations=[_doc_correlation()],
        project_defense_inspection=[
            _defense_card(
                stance="affirmed",
                claim_type="personal_contribution",
                summary=AFFIRM_SUMMARY + " The architecture separates ingestion from the API endpoint layer.",
            )
        ],
    )
    cem = _map(_skill_report([chain]))
    [claim] = cem["claims"]
    assert claim["qualitative_status"] == "Demonstrated"
    attribution = claim["candidate_attribution"]
    assert attribution["state"] == "claimed_contributor"
    assert attribution["label"] == "Contribution claimed (unverified)"
    contribution_citations = [
        c for c in cem["citations"] if c["strength"] == "Contribution explanation"
    ]
    assert contribution_citations
    assert all(c["counted_as_direct_evidence"] for c in contribution_citations)


def test_verified_attribution_in_project_meta_enables_strong_attribution() -> None:
    meta = {
        "p1": {
            **_META["p1"],
            "repo_analysis": {"authorship_match_pct": 90.0},
        }
    }
    chain = _chain(
        github_evidence=[_gh_item()],
        project_defense_inspection=[
            _defense_card(stance="affirmed", claim_type="personal_contribution", summary=AFFIRM_SUMMARY)
        ],
    )
    cem = _map(_skill_report([chain]), meta=meta)
    [claim] = cem["claims"]
    assert claim["candidate_attribution"]["state"] == "verified_author"
    assert "personally implemented" in claim["candidate_attribution"]["candidate_claim_text"]


# ── Counting fix — a needs-review / generic answer can never count ─────────────


def test_needs_review_and_generic_answers_never_count() -> None:
    for status in ("Needs review", "Generic explanation", "Withheld for privacy"):
        cem = _map(
            _skill_report(
                [_chain(project_defense_inspection=[_defense_card(status=status)])]
            )
        )
        defense = [c for c in cem["citations"] if c["proof_type"] == "Project Defense"]
        assert defense
        assert all(not c["counted_as_direct_evidence"] for c in defense), status


# ── Project-report map path ────────────────────────────────────────────────────


def _project_report(*, ownership: dict | None = None, answer_items: list[dict] | None = None) -> dict:
    report = {
        "project_id": "p1",
        "project_title": EXCALIDRAW,
        "repo_full_name": "excalidraw/excalidraw",
        "deployed_url": None,
        "evidence_package": {"project_defense_completed": True},
        "project_defense_analysis": {"privacy_scan_status": "clean"},
        "skill_evidence": [{"skill": "React", "evidence_traces": ["t1"], "limitations": []}],
        "evidence_traces": [
            {
                "trace_id": "t1",
                "source_type": "GitHub Proof",
                "source_title": "excalidraw/excalidraw",
                "file_path": "src/components/App.tsx",
                "line_start": 100,
                "line_end": 140,
                "function_name": "App",
                "code_snippet": "export const App = () => {\n  const [state, setState] = useState(initial)\n  return element\n}",
                "safe_summary": "React component implementation.",
                "safe_detail": "Implements the main component tree.",
            }
        ],
        "website_skill_evidence": [],
        "limitations": [],
    }
    if ownership is not None:
        report["candidate_ownership"] = ownership
    if answer_items is not None:
        report["defense_answer_evidence"] = answer_items
    return report


def test_project_map_carries_denied_relationship() -> None:
    report = _project_report(answer_items=[_answer("denied", DENIAL_SUMMARY)])
    cem = build_project_claim_evidence_map(report)
    ClaimEvidenceMap(**cem)
    assert cem["project_relationship"]["state"] == "denied_by_candidate"
    [claim] = cem["claims"]
    assert claim["claim_text"] == "React is demonstrated in the project excalidraw."
    assert claim["candidate_attribution"]["state"] == "denied_by_candidate"


def test_project_map_conflict_is_surfaced_once() -> None:
    report = _project_report(ownership={"state": "conflicted", "label": "Conflicting ownership evidence", "basis": [], "limitations": []})
    report["skill_evidence"].append({"skill": "TypeScript", "evidence_traces": ["t1"], "limitations": []})
    cem = build_project_claim_evidence_map(report)
    conflicts = [x for x in cem["contradictions"] if x["kind"] == "ownership_conflict"]
    assert len(conflicts) == 1
    for claim in cem["claims"]:
        assert claim["candidate_attribution"]["state"] == "conflicted"


def test_defense_trace_with_denial_is_clarification_never_counted() -> None:
    report = _project_report()
    report["evidence_traces"].append(
        {
            "trace_id": "t2",
            "source_type": "Project Defense",
            "source_title": f"Project Defense — {EXCALIDRAW}",
            "question_text": "Walk through the part you personally built.",
            "answer_excerpt": DENIAL_SUMMARY,
            "safe_summary": "Ownership clarification.",
        }
    )
    report["skill_evidence"][0]["evidence_traces"].append("t2")
    cem = build_project_claim_evidence_map(report)
    defense = [c for c in cem["citations"] if c["proof_type"] == "Project Defense"]
    assert defense
    assert all(c["strength"] == "Ownership clarification" for c in defense)
    assert all(not c["counted_as_direct_evidence"] for c in defense)


# ── Defense answer engine — denial is honest evidence, not a contradiction ────


def _questions_and_segments(answer_text: str, kind: str = "contribution") -> tuple[list[dict], list[dict]]:
    questions = [
        {
            "id": "q1",
            "question_text": "Walk through the part of this project you personally built.",
            "target_ref": {"type": "project_defense", "kind": kind},
            "sort_order": 1,
        }
    ]
    segments = [{"question_id": "q1", "text": answer_text}]
    return questions, segments


def test_denial_answer_is_not_a_contradiction_and_stays_shareable() -> None:
    questions, segments = _questions_and_segments(DENIAL_SUMMARY)
    [item] = build_defense_answer_evidence(
        questions=questions,
        segments=segments,
        claimed_skills=["React"],
        attached_proofs=None,
        project_title=EXCALIDRAW,
    )
    assert item["ownership_stance"] == "denied"
    assert item["contradiction_flag"] is False
    assert item["qualitative_status"] != "Needs review"
    assert item["public_shareable"] is True
    assert item["limitation"] == OWNERSHIP_DENIAL_LIMITATION
    assert item["evidence_role"] == ROLE_OWNERSHIP_CLARIFICATION


def test_provenance_risk_still_flags_needs_review() -> None:
    questions, segments = _questions_and_segments(
        "Honestly I copy-pasted most of the backend and borrowed code found online."
    )
    [item] = build_defense_answer_evidence(
        questions=questions,
        segments=segments,
        claimed_skills=["React"],
        attached_proofs=None,
        project_title=EXCALIDRAW,
    )
    assert item["contradiction_flag"] is True
    assert item["qualitative_status"] == "Needs review"
    assert item["public_shareable"] is False


def test_inspection_card_carries_stance_and_denial_wording() -> None:
    questions, segments = _questions_and_segments(DENIAL_SUMMARY)
    items = build_defense_answer_evidence(
        questions=questions,
        segments=segments,
        claimed_skills=["React"],
        attached_proofs=None,
        project_title=EXCALIDRAW,
    )
    [card] = build_project_defense_inspection_cards(
        answer_evidence=items, project_title=EXCALIDRAW
    )
    assert card["ownership_stance"] == "denied"
    assert "did not build or contribute" in card["what_this_demonstrates"]
    assert "honest ownership clarification" in card["what_this_demonstrates"]


# ── Analysis service — denial never punished, never coached into false claims ─


def test_analysis_records_denial_without_contradiction_penalty() -> None:
    transcript = (
        DENIAL_SUMMARY
        + " The architecture uses a React component tree, a canvas renderer, and a "
        "collaboration workflow over websocket endpoints with state management "
        "and caching for performance."
    )
    result = analyze_defense_transcript(
        transcript_text=transcript, claimed_skills=["React"], github_summary=""
    )
    assert result.ownership_stance == "denied"
    assert result.authorship_denied is True
    assert not any("contradict" in flag.lower() for flag in result.risk_flags)
    assert not any("your own work" in flag for flag in result.risk_flags)
    assert not any("I built" in tip for tip in result.recommended_improvements)
    assert any("honest" in tip for tip in result.recommended_improvements)


def test_analysis_still_flags_provenance_risk() -> None:
    result = analyze_defense_transcript(
        transcript_text="I copy-pasted the model code I found online and downloaded from a tutorial.",
        claimed_skills=["Machine Learning"],
        github_summary="",
    )
    assert any("contradict" in flag.lower() for flag in result.risk_flags)


# ── TEST I — recruiter-safe wording sweep ──────────────────────────────────────


def test_no_ambiguous_ownership_wording_when_unattributed() -> None:
    # Adversarial sweep: with denial + every project-level source attached, the
    # serialized map must never carry candidate-implementation phrasing.
    cem = _map(_skill_report([_excalidraw_chain()]))
    payload = json.dumps(cem).lower()
    for forbidden in (
        "was implemented and demonstrated",
        "authorship explanation",
        "candidate implemented",
        "candidate built",
        "candidate authored",
        "the candidate personally implemented",
    ):
        assert forbidden not in payload, forbidden


# ── Persisted claim rows (canonical_evidence_service) ──────────────────────────


def test_persisted_claim_text_is_project_scoped() -> None:
    from app.services.canonical_evidence_service import _upsert_skill_claims_and_links

    db: dict = {}
    _upsert_skill_claims_and_links(
        db,
        project={"id": "p1", "title": EXCALIDRAW},
        proof_type="github",
        proof_id="gh-1",
        supported_skills=["React"],
        pending_skills=[],
        context_skills=["TypeScript"],
        citation_type="github_code_lines",
        counted_quality="primary",
        link_reason="Validated implementation body.",
        pending_reason="Detected only.",
    )
    claims = list(db["vbr_project_skill_claims"].values())
    assert claims
    for claim in claims:
        assert "was implemented and demonstrated" not in claim["claim_text"]
        assert claim["claim_text"].endswith(f"is demonstrated in the project {EXCALIDRAW}.")
