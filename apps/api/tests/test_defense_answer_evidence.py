"""Tests for the Project Defense Answer Evidence Engine.

Covers:
  - question_id / target_ref grounded mapping (skill / GitHub / website /
    document / challenge / tradeoff / improvement questions)
  - conservative qualitative statuses (never numeric)
  - removal of weak keyword promotion (no half-of-mentioned fallback, no
    "broad mention == explained", no first-person-alone promotion)
  - cross-proof corroboration flags (high-level, never invented citations)
  - contradiction handling (neutral "Needs review", never accusation)
  - public fail-closed projection (withheld cards for flagged / missing /
    legacy analyses; clean cards never echo answer text or question_id)
  - private report cards + public report integration end-to-end

All storage is in-memory (dict mode). No network calls, no LLM calls.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.services.defense_answer_evidence_service import (
    ANSWER_STATUS_EXPLAINED_WITH_EVIDENCE,
    ANSWER_STATUS_GENERIC,
    ANSWER_STATUS_NEEDS_REVIEW,
    ANSWER_STATUS_PARTIALLY_EXPLAINED,
    MISSING_IMPLEMENTATION_EVIDENCE_LIMITATION,
    build_defense_answer_evidence,
    explained_skills_from_answer_evidence,
)
from app.services.project_defense_analysis_service import analyze_defense_transcript
from app.services.public_report_safety_service import (
    DEFENSE_ANSWER_WITHHELD_MESSAGE,
    public_safe_defense_answer_evidence,
)

from tests.test_vbr_project_defense import (
    USER_ID,
    _create_project_defense,
    _generate_questions,
    _seed_document_evidence,
    _seed_github_proof,
    _submit_defense,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def pipeline_db() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict, pipeline_db: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: pipeline_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Unit helpers ──────────────────────────────────────────────────────────────

_SPECIFIC_PYTHON_ANSWER = (
    "I implemented the FastAPI backend in Python with a layered architecture: "
    "each endpoint validates the request schema, calls a service module, and "
    "returns a typed response with error handling."
)
_SPECIFIC_WEBSITE_ANSWER = (
    "On the live site you can submit the form, the request hits the API "
    "endpoint, and the dashboard component updates with the response data "
    "after validation."
)
_SPECIFIC_DOCUMENT_ANSWER = (
    "The design document describes the database schema and the data flow "
    "between the API and the dashboard, which matches what I implemented."
)
_SPECIFIC_CHALLENGE_ANSWER = (
    "The hardest challenge was a race condition in the asynchronous queue: I "
    "added a per-session lock and integration tests around the workflow to fix it."
)
_GENERIC_ANSWER = "It is a very good project and I learned a lot building it."


def _question(qid: str, kind: str, sort_order: int = 0, **target_extra) -> dict:
    return {
        "id": qid,
        "question_text": f"Question about {kind}",
        "target_ref": {"type": "project_defense", "kind": kind, **target_extra},
        "sort_order": sort_order,
    }


def _segment(qid: str | None, text: str) -> dict:
    return {"question_id": qid, "text": text}


_GITHUB_ATTACHED = {
    "github_proof": {
        "github_proof_id": "gh-1",
        "repo_url": "https://github.com/octocat/Hello-World",
        "detected_skills": ["Python"],
        "public_safe_summary": "Repo shows backend API work.",
    }
}
_WEBSITE_ATTACHED = {
    "website_proofs": [
        {
            "proof_session_id": "ws-1",
            "target_website": "https://example.com",
            "supported_skills": ["React"],
        }
    ]
}
_DOCUMENT_ATTACHED = {
    "documents": [
        {
            "document_evidence_id": "doc-1",
            "title": "Design Notes",
            "skills": ["Python"],
        }
    ]
}


# ── target_ref-grounded mapping ───────────────────────────────────────────────


def test_skill_targeted_question_maps_answer_evidence_to_that_skill() -> None:
    items = build_defense_answer_evidence(
        questions=[_question("q1", "skill_link", skill="Python")],
        segments=[_segment("q1", _SPECIFIC_PYTHON_ANSWER)],
        claimed_skills=["Python", "React"],
        attached_proofs={},
    )
    assert len(items) == 1
    item = items[0]
    assert item["mapped_skill"] == "Python"
    assert item["question_kind"] == "skill_explanation"
    assert item["claim_type"] == "skill_understanding"
    assert item["evidence_role"] == "candidate_explanation"
    assert item["qualitative_status"] == ANSWER_STATUS_PARTIALLY_EXPLAINED
    # No implementation proof attached → the limitation says so honestly.
    assert item["limitation"] == MISSING_IMPLEMENTATION_EVIDENCE_LIMITATION
    assert explained_skills_from_answer_evidence(items) == ["Python"]


def test_skill_target_not_in_claimed_skills_is_not_mapped() -> None:
    items = build_defense_answer_evidence(
        questions=[_question("q1", "skill_link", skill="Kubernetes")],
        segments=[_segment("q1", _SPECIFIC_PYTHON_ANSWER)],
        claimed_skills=["Python"],
        attached_proofs={},
    )
    assert items[0]["mapped_skill"] is None
    assert explained_skills_from_answer_evidence(items) == []


def test_github_targeted_question_is_implementation_context_only_with_github() -> None:
    with_github = build_defense_answer_evidence(
        questions=[_question("q1", "skill_repo_link", skill="Python")],
        segments=[_segment("q1", _SPECIFIC_PYTHON_ANSWER)],
        claimed_skills=["Python"],
        attached_proofs=_GITHUB_ATTACHED,
    )[0]
    assert with_github["question_kind"] == "implementation_explanation"
    assert with_github["claim_type"] == "implementation_reasoning"
    assert with_github["evidence_role"] == "implementation_explanation_context"
    assert with_github["corroborates_github"] is True
    assert with_github["qualitative_status"] == ANSWER_STATUS_EXPLAINED_WITH_EVIDENCE
    assert "Attached GitHub proof" in with_github["evidence_basis_chips"]

    # Same question shape but no GitHub proof attached → plain self-explanation,
    # never implementation context, never GitHub corroboration.
    without_github = build_defense_answer_evidence(
        questions=[_question("q1", "skill_repo_link", skill="Python")],
        segments=[_segment("q1", _SPECIFIC_PYTHON_ANSWER)],
        claimed_skills=["Python"],
        attached_proofs={},
    )[0]
    assert without_github["evidence_role"] == "candidate_explanation"
    assert without_github["corroborates_github"] is False
    assert without_github["limitation"] == MISSING_IMPLEMENTATION_EVIDENCE_LIMITATION


def test_website_targeted_question_maps_to_runtime_behavior_context() -> None:
    item = build_defense_answer_evidence(
        questions=[_question("q1", "live_demo_link")],
        segments=[_segment("q1", _SPECIFIC_WEBSITE_ANSWER)],
        claimed_skills=["Python", "React"],
        attached_proofs=_WEBSITE_ATTACHED,
    )[0]
    assert item["question_kind"] == "website_behavior_explanation"
    assert item["claim_type"] == "runtime_behavior_explanation"
    assert item["evidence_role"] == "runtime_behavior_explanation_context"
    assert item["corroborates_website"] is True
    assert item["mapped_skill"] is None  # untargeted skill stays project-level


def test_document_targeted_question_maps_to_document_corroboration_context() -> None:
    item = build_defense_answer_evidence(
        questions=[
            _question("q1", "document_link", document_evidence_id="doc-1")
        ],
        segments=[_segment("q1", _SPECIFIC_DOCUMENT_ANSWER)],
        claimed_skills=["Python"],
        attached_proofs=_DOCUMENT_ATTACHED,
    )[0]
    assert item["question_kind"] == "document_explanation"
    assert item["claim_type"] == "document_claim_explanation"
    assert item["evidence_role"] == "document_corroboration_context"
    assert item["corroborates_document"] is True
    assert item["target_ref_label_safe"] == "Design Notes"


def test_challenge_and_improvement_questions_stay_project_level() -> None:
    items = build_defense_answer_evidence(
        questions=[
            _question("q1", "challenge", sort_order=0),
            _question("q2", "improvement", sort_order=1),
        ],
        segments=[
            _segment("q1", _SPECIFIC_CHALLENGE_ANSWER),
            _segment("q2", "I would add caching and a queue to improve the API latency."),
        ],
        claimed_skills=["Python", "React"],
        attached_proofs={},
    )
    challenge, improvement = items
    assert challenge["question_kind"] == "challenge_debugging"
    assert challenge["claim_type"] == "challenge_resolution"
    assert challenge["evidence_role"] == "challenge_tradeoff_context"
    assert challenge["mapped_skill"] is None
    assert "Challenge/tradeoff explanation" in challenge["evidence_basis_chips"]

    assert improvement["question_kind"] == "improvement_next_step"
    assert improvement["claim_type"] == "future_improvement"
    assert improvement["evidence_role"] == "process_reflection"
    assert improvement["mapped_skill"] is None

    # Neither promotes any skill.
    assert explained_skills_from_answer_evidence(items) == []


def test_tradeoff_question_kind_maps_to_tradeoff_reasoning() -> None:
    item = build_defense_answer_evidence(
        questions=[_question("q1", "tradeoff")],
        segments=[
            _segment(
                "q1",
                "I chose PostgreSQL over a document database because the schema "
                "is relational and the query patterns need joins and validation.",
            )
        ],
        claimed_skills=["Python"],
        attached_proofs={},
    )[0]
    assert item["question_kind"] == "tradeoff_decision"
    assert item["claim_type"] == "tradeoff_reasoning"
    assert item["evidence_role"] == "challenge_tradeoff_context"


# ── Weak promotion removed ────────────────────────────────────────────────────


def test_generic_architecture_answer_does_not_promote_skills() -> None:
    items = build_defense_answer_evidence(
        questions=[_question("q1", "architecture")],
        segments=[_segment("q1", _GENERIC_ANSWER)],
        claimed_skills=["Python", "React"],
        attached_proofs=_GITHUB_ATTACHED,
    )
    item = items[0]
    assert item["qualitative_status"] == ANSWER_STATUS_GENERIC
    assert item["evidence_role"] == "insufficient_or_generic"
    assert item["answer_purpose"] == "unknown_or_generic"
    assert item["corroborates_github"] is False  # generic answers corroborate nothing
    assert explained_skills_from_answer_evidence(items) == []


def test_untargeted_combined_text_never_maps_skills() -> None:
    items = build_defense_answer_evidence(
        questions=[_question("q1", "skill_link", skill="Python")],
        segments=[_segment(None, "I used Python and React and PostgreSQL and Docker in this project.")],
        claimed_skills=["Python", "React"],
        attached_proofs={},
    )
    assert len(items) == 1
    item = items[0]
    assert item["question_kind"] == "unknown_or_generic"
    assert item["mapped_skill"] is None
    assert explained_skills_from_answer_evidence(items) == []


def test_broad_keyword_mention_is_not_an_explained_skill() -> None:
    """A transcript that merely name-drops skills must not mark them explained."""
    result = analyze_defense_transcript(
        transcript_text=(
            "This project uses Python and React and many other technologies. "
            "Python is great and React is popular. It was fun to make and I "
            "think everyone should try building something like this some day."
        ),
        claimed_skills=["Python", "React"],
    )
    assert "Python" in result.skills_mentioned
    assert result.skills_explained_well == []


def test_half_skill_promotion_fallback_removed() -> None:
    """No explanation context → NO portion of mentioned skills is promoted."""
    result = analyze_defense_transcript(
        transcript_text=(
            "We used Python, React, PostgreSQL and Docker. "
            "Python and React and PostgreSQL and Docker were all involved. "
            "It went fine and everyone liked the result quite a lot overall. "
            "There were four of us and we all shared the work between us."
        ),
        claimed_skills=["Python", "React", "PostgreSQL", "Docker"],
    )
    assert len(result.skills_mentioned) == 4
    assert result.skills_explained_well == []


def test_first_person_language_alone_is_not_explanation() -> None:
    """Ownership wording without technical substance promotes nothing."""
    result = analyze_defense_transcript(
        transcript_text=(
            "I built Python things and I wrote React parts. I created it all "
            "myself and I designed it and I coded it and it is my project. "
            "I handled everything and I was responsible for all of it too."
        ),
        claimed_skills=["Python", "React"],
    )
    assert result.skills_explained_well == []

    # Same rule at answer level: a first-person-only targeted answer is generic.
    items = build_defense_answer_evidence(
        questions=[_question("q1", "skill_link", skill="Python")],
        segments=[_segment("q1", "I built it myself and I wrote all of it and it is my own work honestly.")],
        claimed_skills=["Python"],
        attached_proofs={},
    )
    assert items[0]["qualitative_status"] == ANSWER_STATUS_GENERIC
    assert explained_skills_from_answer_evidence(items) == []


def test_repeating_skill_name_alone_is_not_partially_explained() -> None:
    """Naming/repeating the targeted skill is not substance: "Python Python …"
    must never grade as Partially explained or promote Python."""
    items = build_defense_answer_evidence(
        questions=[_question("q1", "skill_link", skill="Python")],
        segments=[_segment("q1", " ".join(["Python"] * 12))],
        claimed_skills=["Python"],
        attached_proofs=_GITHUB_ATTACHED,
    )
    assert items[0]["qualitative_status"] == ANSWER_STATUS_GENERIC
    assert items[0]["qualitative_status"] != ANSWER_STATUS_PARTIALLY_EXPLAINED
    assert items[0]["corroborates_github"] is False
    assert explained_skills_from_answer_evidence(items) == []


def test_naming_machine_learning_skill_alone_is_not_partially_explained() -> None:
    """A skill-targeted answer that only restates "Machine Learning" carries no
    technical substance and must not be promoted."""
    items = build_defense_answer_evidence(
        questions=[_question("q1", "skill_link", skill="Machine Learning")],
        segments=[_segment("q1", " ".join(["Machine Learning"] * 6))],
        claimed_skills=["Machine Learning"],
        attached_proofs={},
    )
    assert items[0]["qualitative_status"] == ANSWER_STATUS_GENERIC
    assert explained_skills_from_answer_evidence(items) == []


def test_real_project_specific_technical_answer_still_qualifies() -> None:
    """A genuine, project-specific technical explanation (mechanism, data, model
    detail) still grades as Partially explained / Explained with evidence."""
    ml_answer = (
        "I trained the classification model on our labelled dataset, tuned the "
        "hyperparameter for the pipeline, and evaluated precision and recall "
        "before exposing the inference endpoint with request validation."
    )
    items = build_defense_answer_evidence(
        questions=[_question("q1", "skill_link", skill="Machine Learning")],
        segments=[_segment("q1", ml_answer)],
        claimed_skills=["Machine Learning"],
        attached_proofs={},
    )
    assert items[0]["qualitative_status"] in {
        ANSWER_STATUS_PARTIALLY_EXPLAINED,
        ANSWER_STATUS_EXPLAINED_WITH_EVIDENCE,
    }
    assert explained_skills_from_answer_evidence(items) == ["Machine Learning"]


def test_question_grounded_mode_overrides_keyword_heuristic() -> None:
    """Grounded skills replace sentence-level keyword matching entirely."""
    result = analyze_defense_transcript(
        transcript_text=(
            "I implemented the Python API with a layered architecture and "
            "React components with hooks, caching and error handling."
        ),
        claimed_skills=["Python", "React"],
        question_grounded_explained_skills=["Python"],
    )
    # React has depth-adjacent wording in the transcript, but only the
    # question-grounded skill counts as explained.
    assert result.skills_explained_well == ["Python"]


def test_contradiction_flags_needs_review_not_promotion() -> None:
    items = build_defense_answer_evidence(
        questions=[_question("q1", "skill_link", skill="Python")],
        segments=[
            _segment(
                "q1",
                "Honestly the backend endpoint code was found online and I "
                "downloaded from a tutorial repository for the database schema.",
            )
        ],
        claimed_skills=["Python"],
        attached_proofs=_GITHUB_ATTACHED,
    )
    item = items[0]
    assert item["contradiction_flag"] is True
    assert item["qualitative_status"] == ANSWER_STATUS_NEEDS_REVIEW
    assert item["public_shareable"] is False
    assert explained_skills_from_answer_evidence(items) == []
    # Neutral wording only — no fraud/cheating language.
    lowered = (item["limitation"] + item["safe_answer_summary"]).lower()
    assert "cheat" not in lowered and "fraud" not in lowered


# ── Public fail-closed projection ─────────────────────────────────────────────


def _clean_items() -> list[dict]:
    return build_defense_answer_evidence(
        questions=[_question("q1", "skill_link", skill="Python")],
        segments=[_segment("q1", _SPECIFIC_PYTHON_ANSWER)],
        claimed_skills=["Python"],
        attached_proofs=_GITHUB_ATTACHED,
        privacy_scan_status="clean",
    )


def test_public_projection_clean_defense_produces_safe_cards() -> None:
    items = _clean_items()
    public = public_safe_defense_answer_evidence(
        items, {"privacy_scan_status": "clean"}
    )
    assert len(public) == 1
    card = public[0]
    # GitHub proof is attached and detects Python → the targeted, specific
    # answer is corroborated and reads "Explained with evidence".
    assert card["qualitative_status"] == ANSWER_STATUS_EXPLAINED_WITH_EVIDENCE
    assert card["mapped_skill"] == "Python"
    assert card["privacy_status"] == "clean"
    # Internal IDs never reach the public card.
    assert "question_id" not in card
    assert "public_shareable" not in card
    # The candidate's answer text (even sanitized) is never echoed publicly —
    # the public summary is a derived description.
    assert "layered architecture" not in card["safe_answer_summary"]
    assert "explained" in card["safe_answer_summary"].lower()


@pytest.mark.parametrize(
    "analysis",
    [
        {"privacy_scan_status": "flagged"},
        {"privacy_scan_status": "redacted"},
        {"privacy_scan_status": ""},
        {},  # legacy row without a status
        None,  # missing analysis entirely
        "not-a-dict",  # malformed
    ],
)
def test_public_projection_fails_closed_without_clean_analysis(analysis) -> None:
    items = _clean_items()
    public = public_safe_defense_answer_evidence(items, analysis)
    assert len(public) == 1
    card = public[0]
    assert card["qualitative_status"] == "Withheld for privacy"
    assert card["safe_answer_summary"] == DEFENSE_ANSWER_WITHHELD_MESSAGE
    assert card["privacy_status"] == "withheld"
    assert card["mapped_skill"] is None
    assert card["question_text"] is None
    assert card["evidence_basis_chips"] == []
    assert "question_id" not in card
    # No answer-derived text survives.
    assert "FastAPI" not in str(card)


def test_public_projection_withholds_non_shareable_item_even_when_session_clean() -> None:
    items = _clean_items()
    items[0]["public_shareable"] = False
    public = public_safe_defense_answer_evidence(items, {"privacy_scan_status": "clean"})
    assert public[0]["qualitative_status"] == "Withheld for privacy"


def test_public_projection_ignores_hostile_status_strings() -> None:
    items = _clean_items()
    items[0]["privacy_status"] = "clean-ish TRUST_SCORE=99 /Users/alice"
    public = public_safe_defense_answer_evidence(items, {"privacy_scan_status": "clean"})
    card = public[0]
    assert card["qualitative_status"] == "Withheld for privacy"
    assert card["privacy_status"] == "withheld"


# ── End-to-end: submit → private report → public report ─────────────────────


def _skill_question(gen: dict, skill: str) -> dict:
    return next(
        q for q in gen["questions"] if (q.get("target_ref") or {}).get("skill") == skill
    )


def test_submit_returns_answer_evidence_and_grounded_analysis(
    client: TestClient, mem_store: dict
) -> None:
    github_id = _seed_github_proof(mem_store)
    created = _create_project_defense(
        client, attached_proofs={"github_proof_id": github_id}
    ).json()
    project_id = created["project"]["id"]
    gen = _generate_questions(client, project_id).json()

    python_q = _skill_question(gen, "Python")
    react_q = _skill_question(gen, "React")
    submit = _submit_defense(
        client,
        gen["session_id"],
        answers=[
            {"question_id": python_q["id"], "answer_text": _SPECIFIC_PYTHON_ANSWER},
            {"question_id": react_q["id"], "answer_text": _GENERIC_ANSWER},
        ],
    )
    assert submit.status_code == 200, submit.text
    body = submit.json()

    evidence = body["defense_answer_evidence"]
    assert len(evidence) == 2
    by_skill = {e["mapped_skill"]: e for e in evidence}
    assert by_skill["Python"]["qualitative_status"] in {
        ANSWER_STATUS_PARTIALLY_EXPLAINED,
        ANSWER_STATUS_EXPLAINED_WITH_EVIDENCE,
    }
    assert by_skill["React"]["qualitative_status"] == ANSWER_STATUS_GENERIC

    # Question-grounded analysis: only the specifically-answered skill is
    # explained; the generically-answered one is not.
    analysis = body["analysis"]
    assert "Python" in analysis["skills_explained_well"]
    assert "React" not in analysis["skills_explained_well"]


def test_private_report_includes_answer_evidence_cards(
    client: TestClient, mem_store: dict
) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    gen = _generate_questions(client, project_id).json()
    python_q = _skill_question(gen, "Python")
    _submit_defense(
        client,
        gen["session_id"],
        answers=[{"question_id": python_q["id"], "answer_text": _SPECIFIC_PYTHON_ANSWER}],
    )

    report = client.get(f"/api/v1/student/vbr/projects/{project_id}/report")
    assert report.status_code == 200, report.text
    cards = report.json()["defense_answer_evidence"]
    assert len(cards) == 1
    card = cards[0]
    assert card["mapped_skill"] == "Python"
    assert card["question_text"]
    assert card["safe_answer_summary"]
    assert card["evidence_basis_chips"]
    assert card["limitation"]
    # Skill matrix stays conservative: defense alone never yields "Demonstrated".
    statuses = {row["skill"]: row["status"] for row in report.json()["skill_evidence"]}
    assert statuses["Python"] == "Partially demonstrated"
    python_row = next(r for r in report.json()["skill_evidence"] if r["skill"] == "Python")
    assert MISSING_IMPLEMENTATION_EVIDENCE_LIMITATION in python_row["limitations"]


def test_public_report_shows_safe_answer_evidence_and_strips_answers(
    client: TestClient, mem_store: dict
) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    gen = _generate_questions(client, project_id).json()
    python_q = _skill_question(gen, "Python")
    _submit_defense(
        client,
        gen["session_id"],
        answers=[{"question_id": python_q["id"], "answer_text": _SPECIFIC_PYTHON_ANSWER}],
    )

    token = client.post(
        f"/api/v1/student/vbr/projects/{project_id}/public-report"
    ).json()["public_token"]
    response = client.get(f"/api/v1/public/vbr/reports/{token}")
    assert response.status_code == 200, response.text

    # Raw answer text and internal question id never reach the public payload.
    assert _SPECIFIC_PYTHON_ANSWER not in response.text
    assert python_q["id"] not in response.text

    cards = response.json()["defense_answer_evidence"]
    assert len(cards) == 1
    card = cards[0]
    assert card["mapped_skill"] == "Python"
    assert card["privacy_status"] == "clean"
    assert "explained" in card["safe_answer_summary"].lower()


def test_public_report_withholds_answer_evidence_for_flagged_defense(
    client: TestClient, mem_store: dict
) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    gen = _generate_questions(client, project_id).json()
    python_q = _skill_question(gen, "Python")
    flagged_answer = (
        _SPECIFIC_PYTHON_ANSWER
        + " My AWS key is AKIAIOSFODNN7EXAMPLE and it lives in the config."
    )
    submit = _submit_defense(
        client,
        gen["session_id"],
        answers=[{"question_id": python_q["id"], "answer_text": flagged_answer}],
    )
    assert submit.json()["analysis"]["privacy_scan_status"] == "flagged"

    token = client.post(
        f"/api/v1/student/vbr/projects/{project_id}/public-report"
    ).json()["public_token"]
    response = client.get(f"/api/v1/public/vbr/reports/{token}")
    assert response.status_code == 200, response.text

    assert "AKIAIOSFODNN7EXAMPLE" not in response.text
    assert _SPECIFIC_PYTHON_ANSWER not in response.text

    cards = response.json()["defense_answer_evidence"]
    assert cards, "withheld cards should still be present"
    for card in cards:
        assert card["qualitative_status"] == "Withheld for privacy"
        assert card["safe_answer_summary"] == DEFENSE_ANSWER_WITHHELD_MESSAGE
        assert card["mapped_skill"] is None
        assert card["privacy_status"] == "withheld"


# ── Video chip / question_id alignment ────────────────────────────────────────


def test_video_chip_prefers_segment_question_id_over_keyword_match() -> None:
    from app.services.project_defense_evidence_chips import build_evidence_chips

    questions = [
        {
            "id": "q-python",
            "target_ref": {"kind": "skill_link", "skill": "Python"},
        }
    ]
    # The text keyword-matches React, but the segment answers the Python
    # question — question_id anchoring must win.
    segments = [
        {
            "question_id": "q-python",
            "start_s": 10.0,
            "end_s": 20.0,
            "text": "For this one I also used React components on the frontend.",
        }
    ]
    chips = build_evidence_chips(segments, claimed_skills=["React", "Python"], questions=questions)
    assert len(chips) == 1
    assert chips[0]["question_id"] == "q-python"
    assert chips[0]["related_skill"] == "Python"


def test_video_chip_without_question_id_keeps_keyword_mapping() -> None:
    from app.services.project_defense_evidence_chips import build_evidence_chips

    segments = [
        {"start_s": 5.0, "end_s": 9.0, "text": "Here I show the Python API code."}
    ]
    chips = build_evidence_chips(segments, claimed_skills=["Python"], questions=[])
    assert len(chips) == 1
    assert chips[0]["related_skill"] == "Python"
    assert chips[0]["question_id"] is None
