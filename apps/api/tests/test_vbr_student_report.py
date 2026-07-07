"""Tests for the student-owned Final VBR Report (v1) preview.

``GET /api/v1/student/vbr/projects/{project_id}/report`` returns a private,
student-owned summary of the evidence package collected for a Project
Defense project. It is NOT the public tokenized recruiter report.

Covers:
  - ownership enforcement (404 for other users / unknown projects)
  - safe summaries only — no raw transcript text, document text, GitHub
    snapshots, storage paths, signed URLs, upload URLs, bucket names, env
    values, tokens, file bytes, or full artifact_data
  - GitHub / document / website attachment summaries
  - Project Defense analysis summary + qualitative (non-numeric) skill
    evidence table
  - sanitized video evidence chips, with and without video
  - honest empty states when website proof / video / analysis are missing

All storage is in-memory (dict mode). No real network calls, no LLM calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app

from tests.test_vbr_project_defense import (
    DEFENSE_TRANSCRIPT,
    OTHER_USER_ID,
    USER_ID,
    VIDEO_TRANSCRIPT_SEGMENTS,
    _create_project_defense,
    _generate_questions,
    _seed_auto_video_transcript,
    _seed_document_evidence,
    _seed_github_proof,
    _seed_skill_pipeline,
    _seed_workflow_analysis,
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


def _get_report(client: TestClient, project_id: str):
    return client.get(f"/api/v1/student/vbr/projects/{project_id}/report")


# ── Document Proof inspection: skill-specific mapping ─────────────────────────


def _inspection_cards(report: dict) -> list[dict]:
    cards: list[dict] = []
    for chain in report.get("projects") or []:
        for corr in chain.get("document_correlations") or []:
            if corr.get("inspection_card"):
                cards.append(corr["inspection_card"])
    for corr in (report.get("standalone_evidence") or {}).get("documents") or []:
        if corr.get("inspection_card"):
            cards.append(corr["inspection_card"])
    return cards


def test_document_inspection_maps_only_matched_skill(mem_store: dict, pipeline_db: dict) -> None:
    """E. The inspection card is built for the selected skill only — a document that
    matched two skills yields a card whose matched_skill is the report's skill."""
    from app.services.student_proof_vault_service import collect_skill_report

    _seed_document_evidence(
        mem_store,
        evidence_objects=[
            {"skill_name": "Machine Learning", "snippet": "trained a model", "page_number": 3},
            {"skill_name": "Python", "snippet": "wrote the training loop", "page_number": 5},
        ],
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "Machine Learning")
    cards = _inspection_cards(report)
    assert cards, "an ML inspection card must exist"
    assert all(c["matched_skill"] == "Machine Learning" for c in cards)
    # The Python-only locator (page 5) must not appear in the ML report.
    assert all(c["page_number"] != 5 for c in cards)


def test_document_inspection_gives_selected_skill_specific_locator(
    mem_store: dict, pipeline_db: dict
) -> None:
    """F. The selected skill receives ITS skill-specific locator (its page/snippet)."""
    from app.services.student_proof_vault_service import collect_skill_report

    _seed_document_evidence(
        mem_store,
        evidence_objects=[
            {"skill_name": "Machine Learning", "snippet": "trained a model", "page_number": 3},
            {"skill_name": "Python", "snippet": "wrote the training loop", "page_number": 5},
        ],
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "Machine Learning")
    card = _inspection_cards(report)[0]
    assert card["page_number"] == 3
    assert card["safe_snippet"] == "trained a model"


def test_unrelated_skill_has_no_document_inspection_card(
    mem_store: dict, pipeline_db: dict
) -> None:
    """G. A skill the document never cited receives no document inspection card."""
    from app.services.student_proof_vault_service import collect_skill_report

    _seed_document_evidence(
        mem_store,
        evidence_objects=[{"skill_name": "Machine Learning", "snippet": "trained a model", "page_number": 3}],
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "Rust")
    assert _inspection_cards(report) == []


def test_document_inspection_limitation_copy_appears(mem_store: dict, pipeline_db: dict) -> None:
    """H. Every inspection card carries the corroboration/limitation copy."""
    from app.services.student_proof_vault_service import collect_skill_report

    _seed_document_evidence(
        mem_store,
        evidence_objects=[{"skill_name": "Machine Learning", "snippet": "trained a model", "page_number": 3}],
    )
    report = collect_skill_report(mem_store, pipeline_db, USER_ID, "Machine Learning")
    card = _inspection_cards(report)[0]
    assert "does not" in card["limitation"]
    assert "independently prove" in card["limitation"]
    assert "GitHub Proof" in card["limitation"]


def test_skill_specific_details_do_not_leak_across_skills(
    mem_store: dict, pipeline_db: dict
) -> None:
    """I. A document that matched both API Development and Machine Learning yields,
    for the ML report, ML detail only — never the API endpoint/request lists."""
    from app.services.student_proof_vault_service import collect_skill_report

    _seed_document_evidence(
        mem_store,
        evidence_objects=[
            {
                "skill_name": "API Development",
                "snippet": "The service exposes REST API endpoints for the workflow.",
                "reason": "The request payload and response schema are described.",
                "page_number": 7,
            },
            {
                "skill_name": "Machine Learning",
                "snippet": "We trained a gradient-boosted model on the dataset.",
                "reason": "Describes the ML model and evaluation.",
                "page_number": 4,
            },
        ],
    )

    ml_card = _inspection_cards(
        collect_skill_report(mem_store, pipeline_db, USER_ID, "Machine Learning")
    )[0]
    assert ml_card["matched_skill"] == "Machine Learning"
    # ML card carries ML detail and NONE of the API-only lists.
    assert ml_card["api_endpoints"] == []
    assert ml_card["request_response_details"] == []
    assert any("model" in d.lower() for d in ml_card["technical_details"])
    # The API-only excerpt/locator never appears in the ML card.
    blob = repr(ml_card)
    assert "REST API endpoints" not in blob
    assert ml_card["page_number"] == 4

    api_card = _inspection_cards(
        collect_skill_report(mem_store, pipeline_db, USER_ID, "API Development")
    )[0]
    assert api_card["matched_skill"] == "API Development"
    assert api_card["api_endpoints"], "API card must carry its own endpoint detail"
    assert "gradient-boosted model" not in repr(api_card)


# ── Ownership ────────────────────────────────────────────────────────────────

def test_report_returns_404_for_unknown_project(client: TestClient) -> None:
    response = _get_report(client, str(uuid4()))
    assert response.status_code == 404


def test_report_not_found_for_other_user(client: TestClient) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = _get_report(client, project_id)
    assert response.status_code == 404


# ── Minimal project (no proofs, no session) ─────────────────────────────────

def test_report_minimal_project_safe_defaults(client: TestClient) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]

    response = _get_report(client, project_id)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["project_id"] == project_id
    assert body["project_title"] == "Skill Evidence Tracker"
    assert body["repo_url"] == "https://github.com/octocat/Hello-World"
    assert body["claimed_skills"] == ["Python", "React"]
    assert body["session_id"] is None

    pkg = body["evidence_package"]
    assert pkg["github_proof_attached"] is False
    assert pkg["documents_count"] == 0
    assert pkg["website_proofs_count"] == 0
    assert pkg["project_defense_completed"] is False
    assert pkg["video_defense_recorded"] is False
    assert pkg["video_evidence_chip_count"] == 0

    assert body["github_proof"] is None
    assert body["documents"] == []
    assert body["website_proofs"] == []
    assert body["project_defense_analysis"] is None
    assert body["defense_questions"] == []
    assert body["video_evidence_chips"] == []

    # Skill evidence table uses qualitative labels, never numeric scores.
    statuses = {row["skill"]: row["status"] for row in body["skill_evidence"]}
    assert statuses == {"Python": "Not assessed", "React": "Not assessed"}
    for row in body["skill_evidence"]:
        assert isinstance(row["status"], str)
        assert "score" not in row

    # Honest empty states.
    assert "Website proof not attached." in body["limitations"]
    assert "Video defense not recorded yet." in body["limitations"]
    assert "No timestamped video evidence chips yet." in body["limitations"]
    assert "No document proof attached." in body["limitations"]
    assert "Project Defense has not been analyzed yet." in body["limitations"]

    assert body["preview_only"] is True
    assert body["public_recruiter_sharing_enabled"] is False
    assert "student preview" in body["note"].lower()


# ── Attached proof summaries ─────────────────────────────────────────────────

def test_report_includes_github_document_website_summaries(client: TestClient, mem_store: dict) -> None:
    github_proof_id = _seed_github_proof(mem_store)
    document_id = _seed_document_evidence(mem_store)
    website_proof_session_id = _seed_workflow_analysis(mem_store)

    created = _create_project_defense(
        client,
        attached_proofs={
            "github_proof_id": github_proof_id,
            "document_evidence_ids": [document_id],
            "website_proof_session_ids": [website_proof_session_id],
        },
    ).json()
    project_id = created["project"]["id"]

    response = _get_report(client, project_id)
    assert response.status_code == 200, response.text
    body = response.json()

    pkg = body["evidence_package"]
    assert pkg["github_proof_attached"] is True
    assert pkg["documents_count"] == 1
    assert pkg["website_proofs_count"] == 1

    github_proof = body["github_proof"]
    assert github_proof["repo_owner"] == "octocat"
    assert github_proof["repo_name"] == "Hello-World"
    assert github_proof["detected_skills"] == ["Python", "React"]
    assert "octocat/Hello-World" in github_proof["public_safe_summary"]
    assert "72/100" not in github_proof["public_safe_summary"]
    assert "confidence" not in github_proof["public_safe_summary"].lower()
    assert "with." not in github_proof["public_safe_summary"]
    # No raw GitHub snapshot / internal IDs in the safe summary.
    assert "github_proof_id" not in github_proof
    assert "repo_metadata" not in github_proof
    assert "analysis_snapshot" not in github_proof

    documents = body["documents"]
    assert documents == [{"title": "Final Year Project Report", "source_type": "document", "status": "analyzed"}]
    assert "document_evidence_id" not in documents[0]

    website_proofs = body["website_proofs"]
    assert website_proofs == [
        {
            "target_website": "http://demo.example.com",
            "evidence_strength": "Evidence observed",
            "workflow_confidence": "high",
            "supported_skills": ["Machine Learning", "React"],
        }
    ]
    assert "proof_session_id" not in website_proofs[0]
    assert "evidence_strength_score" not in website_proofs[0]

    # Website proof attached now, but not video/analysis yet.
    assert "Website proof not attached." not in body["limitations"]
    assert "No document proof attached." not in body["limitations"]


def test_report_skill_matrix_maps_skills_to_evidence_sources(client: TestClient, mem_store: dict) -> None:
    """Each skill row carries the canonical evidence-source labels that support
    it (GitHub / Website / Project Defense / Video) — never numeric scores."""
    github_proof_id = _seed_github_proof(mem_store)  # detects Python + React
    # A Website Proof only earns a skill its OBSERVED behaviour supports (hint-only
    # stored ``supported_skills`` never maps by itself). This capture demonstrates an
    # interactive product UI, which is direct Frontend (React) evidence.
    website_proof_session_id = _seed_workflow_analysis(
        mem_store,
        workflow_summary=(
            "The user interacted with the app's interface, filled in the form and a "
            "result was displayed on screen."
        ),
    )

    created = _create_project_defense(
        client,
        attached_proofs={
            "github_proof_id": github_proof_id,
            "website_proof_session_ids": [website_proof_session_id],
        },
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    rows = {row["skill"]: row for row in body["skill_evidence"]}

    # Python is detected by the GitHub Proof only (the website behaviour does not
    # demonstrate a Python-specific skill, so it earns no Website Proof chip).
    assert rows["Python"]["supporting_sources"] == ["GitHub Proof"]
    # React is detected by GitHub Proof and supported by the Website Proof (the
    # observed interactive UI is direct Frontend evidence), in canonical
    # (GitHub → Website) order.
    assert rows["React"]["supporting_sources"] == ["GitHub Proof", "Website Proof"]

    # Supporting-source labels carry no numeric score fragments.
    for row in body["skill_evidence"]:
        for src in row["supporting_sources"]:
            assert "/100" not in src and "%" not in src
        assert isinstance(row["limitations"], list)


def test_report_unevidenced_skill_carries_honest_limitation(client: TestClient) -> None:
    """A skill with no reviewed evidence is flagged as a pending claim, not proof."""
    project_id = _create_project_defense(client).json()["project"]["id"]
    body = _get_report(client, project_id).json()

    for row in body["skill_evidence"]:
        assert row["status"] == "Not assessed"
        assert row["supporting_sources"] == []
        assert any("pending more proof" in line for line in row["limitations"])


# ── Project Defense analysis + skill evidence table ─────────────────────────

def test_report_includes_project_defense_analysis_and_skill_evidence(client: TestClient) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]

    submit = _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)
    assert submit.status_code == 200, submit.text
    analysis = submit.json()["analysis"]

    response = _get_report(client, project_id)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["session_id"] == session_id
    assert body["evidence_package"]["project_defense_completed"] is True

    report_analysis = body["project_defense_analysis"]
    assert report_analysis is not None
    assert report_analysis["recruiter_summary"] == analysis["recruiter_summary"]
    assert report_analysis["privacy_scan_status"] == "clean"

    # Numeric analysis scores must never be returned — only qualitative labels.
    numeric_score_fields = [
        "overall_defense_score",
        "explanation_clarity_score",
        "ownership_signal_score",
        "technical_depth_score",
        "consistency_with_evidence_score",
    ]
    for field in numeric_score_fields:
        assert field not in report_analysis

    qualitative_labels = {
        "Demonstrated",
        "Partially demonstrated",
        "Supporting evidence",
        "Needs review",
        "Not assessed",
    }
    assert analysis["overall_defense_score"] >= 60
    assert report_analysis["overall_assessment"] in qualitative_labels
    for area in ["explanation_clarity", "ownership_signal", "technical_depth", "consistency_with_evidence"]:
        assert report_analysis[area] in qualitative_labels

    assert len(body["defense_questions"]) >= 1
    for q in body["defense_questions"]:
        assert isinstance(q["question_text"], str)
        assert "answered" in q

    # DEFENSE_TRANSCRIPT names Python/React only inside generic-infrastructure
    # sentences ("REST API backend using Python … PostgreSQL database"), which the
    # tightened transcript-only fallback treats as project context — not a
    # substantive, project-specific skill explanation. Both skills are therefore
    # *mentioned* but not *explained well*, so the matrix shows Supporting evidence
    # (never a raw numeric score, and never promoted to Demonstrated on generic
    # vocabulary alone).
    statuses = {row["skill"]: row["status"] for row in body["skill_evidence"]}
    assert statuses["Python"] == "Supporting evidence"
    assert statuses["React"] == "Supporting evidence"
    for row in body["skill_evidence"]:
        assert row["status"] in {
            "Demonstrated",
            "Partially demonstrated",
            "Supporting evidence",
            "Needs review",
            "Not assessed",
        }

    # No longer "not analyzed yet".
    assert "Project Defense has not been analyzed yet." not in body["limitations"]
    # Always present — Project Defense is process/explanation evidence.
    assert any("process and explanation" in note for note in body["limitations"])
    assert any("private by default" in note.lower() for note in body["limitations"])


# ── Video evidence chips ──────────────────────────────────────────────────────

def test_report_includes_video_evidence_chips_and_video_recorded_flag(client: TestClient, mem_store: dict) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]

    # Simulate an uploaded video chunk so video_defense_recorded is true.
    chunk_id = str(uuid4())
    mem_store.setdefault("vbr_video_chunks", {})[chunk_id] = {
        "id": chunk_id,
        "session_id": session_id,
        "chunk_index": 0,
        "bytes": 1024,
        "sha256": "deadbeef",
    }

    _seed_auto_video_transcript(mem_store, session_id, VIDEO_TRANSCRIPT_SEGMENTS)

    submit = _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)
    assert submit.status_code == 200, submit.text
    expected_chips = submit.json()["video_evidence_chips"]
    assert expected_chips

    response = _get_report(client, project_id)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["evidence_package"]["video_defense_recorded"] is True
    assert body["evidence_package"]["video_evidence_chip_count"] == len(expected_chips)
    assert body["video_evidence_chips"] == expected_chips

    for chip in body["video_evidence_chips"]:
        assert chip["label"].startswith("Video ")
        assert len(chip["short_summary"]) <= 160

    assert "Video defense not recorded yet." not in body["limitations"]
    assert "No timestamped video evidence chips yet." not in body["limitations"]


def test_report_works_without_video_or_chips(client: TestClient) -> None:
    """Manual defense submitted with no video recording at all."""
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]

    submit = _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)
    assert submit.status_code == 200, submit.text
    assert submit.json()["video_evidence_chips"] == []

    response = _get_report(client, project_id)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["evidence_package"]["video_defense_recorded"] is False
    assert body["evidence_package"]["video_evidence_chip_count"] == 0
    assert body["video_evidence_chips"] == []
    assert "Video defense not recorded yet." in body["limitations"]
    assert "No timestamped video evidence chips yet." in body["limitations"]

    # Analysis is still present from the manual/text-only defense.
    assert body["project_defense_analysis"] is not None


# ── Skill Graph pipeline cross-reference ─────────────────────────────────────

def test_report_skill_evidence_uses_skill_pipeline_support_status(client: TestClient, pipeline_db: dict) -> None:
    pipeline_id = _seed_skill_pipeline(pipeline_db, skill_name="Python", support_status="strongly_supported")

    created = _create_project_defense(
        client, attached_proofs={"skill_pipeline_ids": [pipeline_id]}
    ).json()
    project_id = created["project"]["id"]

    response = _get_report(client, project_id)
    assert response.status_code == 200, response.text
    body = response.json()

    statuses = {row["skill"]: row["status"] for row in body["skill_evidence"]}
    assert statuses["Python"] == "Demonstrated"
    assert statuses["React"] == "Not assessed"

    # Numeric confidence_score from the pipeline must never leak into the report.
    raw = response.text
    assert "confidence_score" not in raw
    assert "70" not in [str(v) for v in body["skill_evidence"]]


# ── Privacy / safety: nothing unsafe is ever returned ────────────────────────

def test_report_does_not_leak_unsafe_fields(client: TestClient, mem_store: dict) -> None:
    github_proof_id = _seed_github_proof(mem_store)
    document_id = _seed_document_evidence(mem_store)
    website_proof_session_id = _seed_workflow_analysis(mem_store)

    created = _create_project_defense(
        client,
        attached_proofs={
            "github_proof_id": github_proof_id,
            "document_evidence_ids": [document_id],
            "website_proof_session_ids": [website_proof_session_id],
        },
    ).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]

    chunk_id = str(uuid4())
    mem_store.setdefault("vbr_video_chunks", {})[chunk_id] = {
        "id": chunk_id,
        "session_id": session_id,
        "chunk_index": 0,
        "bytes": 1024,
        "sha256": "deadbeef",
    }
    _seed_auto_video_transcript(mem_store, session_id, VIDEO_TRANSCRIPT_SEGMENTS)
    _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)

    response = _get_report(client, project_id)
    assert response.status_code == 200, response.text
    raw = response.text

    unsafe_substrings = [
        "storage_path",
        "signed_url",
        "access_token",
        "vbr/sessions",
        "full_text",
        "raw_dump",
        "repo_metadata",
        "analysis_snapshot",
        "secret_token",
        "document_evidence_id",
        "proof_session_id",
        "github_proof_id",
        "skill_pipeline_id",
        "confidence_score",
        "Bearer ",
        "supabase.co",
        ".webm",
        ".mp4",
        "should-never-leak",
        # Numeric analysis / evidence-strength scores must never leak — only
        # qualitative labels are returned.
        "overall_defense_score",
        "explanation_clarity_score",
        "ownership_signal_score",
        "technical_depth_score",
        "consistency_with_evidence_score",
        "evidence_strength_score",
    ]
    for unsafe in unsafe_substrings:
        assert unsafe not in raw, f"Unsafe field/value leaked into student report: {unsafe!r}"

    # Full raw transcript text must never appear verbatim.
    assert DEFENSE_TRANSCRIPT not in raw


# ── Evidence traceability (claim → evidence → source) ────────────────────────

def _full_evidence_project(client: TestClient, mem_store: dict) -> str:
    """A project with GitHub + document + website proof, analysis, and video."""
    github_proof_id = _seed_github_proof(mem_store)
    document_id = _seed_document_evidence(mem_store)
    website_proof_session_id = _seed_workflow_analysis(mem_store)

    created = _create_project_defense(
        client,
        attached_proofs={
            "github_proof_id": github_proof_id,
            "document_evidence_ids": [document_id],
            "website_proof_session_ids": [website_proof_session_id],
        },
    ).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]

    chunk_id = str(uuid4())
    mem_store.setdefault("vbr_video_chunks", {})[chunk_id] = {
        "id": chunk_id,
        "session_id": session_id,
        "chunk_index": 0,
        "bytes": 1024,
        "sha256": "deadbeef",
    }
    _seed_auto_video_transcript(mem_store, session_id, VIDEO_TRANSCRIPT_SEGMENTS)
    _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)
    return project_id


def test_student_report_includes_evidence_traces_per_skill(client: TestClient, mem_store: dict) -> None:
    project_id = _full_evidence_project(client, mem_store)
    body = _get_report(client, project_id).json()

    traces = body["evidence_traces"]
    assert traces, "expected evidence traces to be generated"
    source_types = {t["source_type"] for t in traces}
    # Every evidence source is represented as a concrete trace.
    assert {"GitHub Proof", "Document Proof", "Website Proof", "Project Defense", "Video Evidence"} <= source_types

    trace_ids = {t["trace_id"] for t in traces}
    # Each skill row carries a justification, a recruiter-verify line, and trace ids.
    for row in body["skill_evidence"]:
        assert row["why_this_status"], f"missing why_this_status for {row['skill']}"
        assert row["recruiter_can_verify"]
        for tid in row["evidence_traces"]:
            assert tid in trace_ids, f"skill {row['skill']} references unknown trace {tid}"

    # At least one skill is actually backed by traceable evidence.
    assert any(row["evidence_traces"] for row in body["skill_evidence"])


def test_skill_evidence_groups_by_proof_source_are_skill_specific(
    client: TestClient, mem_store: dict
) -> None:
    """The skill-first Project Report renders, per skill, evidence rows grouped by
    proof source. This guards the data contract those cards depend on: for each
    skill, the proof *source types* of its attached traces are a subset of that
    skill's own ``supporting_sources`` chips — never the whole project's proof
    union applied blindly to every skill."""
    project_id = _full_evidence_project(client, mem_store)
    body = _get_report(client, project_id).json()

    traces_by_id = {t["trace_id"]: t for t in body["evidence_traces"]}
    skill_rows = body["skill_evidence"]
    assert skill_rows, "expected claimed skills on the project"

    for row in skill_rows:
        chips = set(row["supporting_sources"])
        # The source types this skill's grouped evidence rows would render under.
        grouped_source_types = {
            traces_by_id[tid]["source_type"]
            for tid in row["evidence_traces"]
            if tid in traces_by_id
        }
        # No skill ever surfaces an evidence group for a proof source it does not
        # claim as a supporting chip — the breakdown is honest and skill-specific.
        assert grouped_source_types <= chips, (
            f"skill {row['skill']!r} groups evidence from {grouped_source_types - chips} "
            f"with no matching supporting-source chip"
        )
        # Every trace attributed to this skill actually names it (or is honest
        # project-level context with no skill claim) — never another skill's proof.
        for tid in row["evidence_traces"]:
            names = traces_by_id[tid]["skill_names"]
            assert (not names) or (row["skill"] in names), (
                f"skill {row['skill']!r} references trace {tid} scoped to {names}"
            )

    # The full-evidence project genuinely produces a multi-source breakdown for at
    # least one skill (so the grouped-by-source cards are exercised, not vacuous).
    assert any(
        len(
            {
                traces_by_id[tid]["source_type"]
                for tid in row["evidence_traces"]
                if tid in traces_by_id
            }
        )
        >= 2
        for row in skill_rows
    )


def test_github_trace_is_publicly_openable_with_safe_url(client: TestClient, mem_store: dict) -> None:
    project_id = _full_evidence_project(client, mem_store)
    body = _get_report(client, project_id).json()

    gh = next(t for t in body["evidence_traces"] if t["source_type"] == "GitHub Proof")
    assert gh["is_publicly_openable"] is True
    assert gh["public_url"].startswith("https://github.com/")
    assert gh["public_url_label"] == "View public repository"
    # The anchor is namespaced so it never collides with the "github-proof"
    # evidence *section* id in the report UI.
    assert gh["evidence_anchor"] == "trace-github-proof"
    assert gh["location_label"] == "repo-level"
    assert "Python" in gh["skill_names"]


def test_evidence_anchors_unique_and_never_collide_with_section_ids(
    client: TestClient, mem_store: dict
) -> None:
    """Every trace anchor is unique and namespaced under "trace-", so a matrix
    link can never resolve to a coarse evidence *section* header (the report UI
    renders ``id="github-proof"``/``id="project-defense"`` etc.)."""
    reserved_section_ids = {
        "evidence-by-source",
        "github-proof",
        "documents",
        "website-proof",
        "project-defense",
        # The skill-first main section id (was "skill-evidence" before the
        # Project Report skill-card redesign).
        "skills-demonstrated",
        "evidence-traceability",
        "limitations",
    }
    project_id = _full_evidence_project(client, mem_store)
    body = _get_report(client, project_id).json()

    anchors = [t["evidence_anchor"] for t in body["evidence_traces"]]
    assert anchors, "expected at least one evidence trace"
    assert len(anchors) == len(set(anchors)), "duplicate evidence_anchor values"
    for anchor in anchors:
        assert anchor.startswith("trace-")
        assert anchor not in reserved_section_ids

    # Every skill-row trace reference resolves to a real trace.
    trace_ids = {t["trace_id"] for t in body["evidence_traces"]}
    for row in body["skill_evidence"]:
        for tid in row["evidence_traces"]:
            assert tid in trace_ids


def test_document_trace_is_safe_and_not_publicly_openable(client: TestClient, mem_store: dict) -> None:
    project_id = _full_evidence_project(client, mem_store)
    body = _get_report(client, project_id).json()

    doc = next(t for t in body["evidence_traces"] if t["source_type"] == "Document Proof")
    # No raw document, no public download link — only a safe summary + note.
    assert doc["is_publicly_openable"] is False
    assert doc["public_url"] is None
    assert doc["private_evidence_note"]
    assert "evidence vault" in doc["private_evidence_note"].lower()
    assert doc["safe_summary"]


def test_project_defense_answer_creates_process_evidence_trace(client: TestClient, mem_store: dict) -> None:
    project_id = _full_evidence_project(client, mem_store)
    body = _get_report(client, project_id).json()

    defense_traces = [t for t in body["evidence_traces"] if t["source_type"] == "Project Defense"]
    assert defense_traces
    assert all(t["is_publicly_openable"] is False for t in defense_traces)
    assert any("self-explanation" in t["limitation"].lower() for t in defense_traces)


def test_video_chip_trace_carries_timestamp(client: TestClient, mem_store: dict) -> None:
    project_id = _full_evidence_project(client, mem_store)
    body = _get_report(client, project_id).json()

    video_traces = [t for t in body["evidence_traces"] if t["source_type"] == "Video Evidence"]
    assert video_traces
    assert all(t["timestamp"] for t in video_traces)
    assert all(t["trace_id"].startswith("video-chip-") for t in video_traces)


def test_traces_never_leak_raw_or_score_content(client: TestClient, mem_store: dict) -> None:
    project_id = _full_evidence_project(client, mem_store)
    raw = _get_report(client, project_id).text
    assert DEFENSE_TRANSCRIPT not in raw
    for unsafe in ["storage_path", "signed_url", ".webm", ".mp4", "/100", "fully verified"]:
        assert unsafe not in raw, f"unsafe fragment leaked into report traces: {unsafe!r}"


def test_missing_website_and_video_render_honest_limitations(client: TestClient) -> None:
    project_id = _create_project_defense(client).json()["project"]["id"]
    body = _get_report(client, project_id).json()
    assert "Website proof not attached." in body["limitations"]
    assert "Video defense not recorded yet." in body["limitations"]


# ── Document Proof traceability consistency (must-fix) ───────────────────────


def _rows_by_skill(body: dict) -> dict[str, dict]:
    return {row["skill"]: row for row in body["skill_evidence"]}


def test_document_with_explicit_skill_is_consistent_supporting_evidence(
    client: TestClient, mem_store: dict
) -> None:
    """A document the analyzer matched to a skill becomes conservative Document
    Proof for ONLY that skill: the matrix row lists Document Proof, carries a
    matching trace, and is never marked 'no evidence reviewed'."""
    document_id = _seed_document_evidence(
        mem_store,
        evidence_objects=[{"skill_name": "Python", "confidence": "high", "snippet": "irrelevant"}],
    )
    created = _create_project_defense(
        client, attached_proofs={"document_evidence_ids": [document_id]}
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    rows = _rows_by_skill(body)

    # Python was explicitly matched → Document Proof, conservative status.
    py = rows["Python"]
    assert "Document Proof" in py["supporting_sources"]
    assert py["status"] == "Supporting evidence"
    assert py["notes"] != "No evidence has been reviewed for this skill yet."
    assert not any("pending more proof" in lim for lim in py["limitations"])

    # The document trace claims exactly Python (never every claimed skill).
    doc_traces = [t for t in body["evidence_traces"] if t["source_type"] == "Document Proof"]
    assert doc_traces
    assert all(t["skill_names"] == ["Python"] for t in doc_traces)

    # React was NOT matched by the document → no Document Proof for it.
    react = rows["React"]
    assert "Document Proof" not in react["supporting_sources"]


def test_document_without_explicit_skills_is_project_level_only(
    client: TestClient, mem_store: dict
) -> None:
    """A document with no analyzer-matched skills is project-level context: it is
    never mapped to a claimed skill, and unevidenced skills stay honest."""
    document_id = _seed_document_evidence(mem_store)  # no evidence_objects
    created = _create_project_defense(
        client, attached_proofs={"document_evidence_ids": [document_id]}
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    rows = _rows_by_skill(body)

    # No skill gets a fake per-skill Document Proof.
    for row in rows.values():
        assert "Document Proof" not in row["supporting_sources"]
        assert row["status"] == "Not assessed"

    # The document still appears, but as a project-level trace (no skills) with an
    # honest project-level limitation.
    doc_traces = [t for t in body["evidence_traces"] if t["source_type"] == "Document Proof"]
    assert doc_traces
    assert all(t["skill_names"] == [] for t in doc_traces)
    assert all("not mapped to specific skills" in t["limitation"] for t in doc_traces)


def test_document_proof_trace_and_row_never_disagree(client: TestClient, mem_store: dict) -> None:
    """Invariant: for every skill row, a Document Proof trace claims it iff the
    row lists Document Proof in supporting_sources — no one-directional drift."""
    document_id = _seed_document_evidence(
        mem_store,
        evidence_objects=[{"skill_name": "React", "confidence": "medium"}],
    )
    created = _create_project_defense(
        client, attached_proofs={"document_evidence_ids": [document_id]}
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    traces_by_id = {t["trace_id"]: t for t in body["evidence_traces"]}

    for row in body["skill_evidence"]:
        skill_l = row["skill"].lower()
        row_has_doc = "Document Proof" in row["supporting_sources"]
        trace_claims_skill = any(
            traces_by_id[tid]["source_type"] == "Document Proof"
            and skill_l in {s.lower() for s in traces_by_id[tid]["skill_names"]}
            for tid in row["evidence_traces"]
        )
        assert row_has_doc == trace_claims_skill, (
            f"Document Proof mismatch for {row['skill']!r}: "
            f"row={row_has_doc} trace={trace_claims_skill}"
        )
        if not row_has_doc:
            assert "no evidence reviewed" not in row["notes"].lower() or row["status"] == "Not assessed"


# ── Phase 1: GitHub file-level traces (real evidence_files) ──────────────────


def test_github_file_level_traces_when_evidence_files_present(
    client: TestClient, mem_store: dict
) -> None:
    """When the GitHub proof carries safe ``evidence_files`` paths, the report
    emits file-level traces (the recruiter lands on the exact file) with a
    public ``…/blob/<branch>/<path>`` link, instead of only a repo-level card."""
    github_proof_id = _seed_github_proof(
        mem_store,
        repo_metadata={
            "secret_token": "should-never-leak",
            "evidence_files": ["app/routes.py", "src/components/Chart.tsx", "https://evil.example/x"],
        },
    )
    created = _create_project_defense(
        client, repo_url=None, attached_proofs={"github_proof_id": github_proof_id}
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    file_traces = [t for t in body["evidence_traces"] if t["location_type"] == "github_file"]
    paths = {t["file_path"] for t in file_traces}
    # External URL entry is dropped; only safe repo-relative paths become traces.
    assert paths == {"app/routes.py", "src/components/Chart.tsx"}

    routes = next(t for t in file_traces if t["file_path"] == "app/routes.py")
    assert routes["location_label"] == "app/routes.py"
    assert routes["is_publicly_openable"] is True
    assert routes["public_url"] == "https://github.com/octocat/Hello-World/blob/main/app/routes.py"
    assert routes["evidence_anchor"] == "trace-github-file-app-routes-py"
    # Never claims line-level proof.
    assert "line" not in routes["location_label"].lower()
    assert "should-never-leak" not in _get_report(client, project_id).text


def test_github_repo_level_fallback_when_no_evidence_files(
    client: TestClient, mem_store: dict
) -> None:
    """With no ``evidence_files``, the report honestly falls back to a single
    repo-level GitHub trace and emits no file-level traces."""
    github_proof_id = _seed_github_proof(mem_store)  # repo_metadata has no evidence_files
    created = _create_project_defense(
        client, repo_url=None, attached_proofs={"github_proof_id": github_proof_id}
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    gh_traces = [t for t in body["evidence_traces"] if t["source_type"] == "GitHub Proof"]
    assert len(gh_traces) == 1
    assert gh_traces[0]["location_type"] == "repo_level"


# ── Phase 2: Document page/snippet traces (re-fetched at report time) ─────────


def test_document_page_and_snippet_trace_when_analyzer_recorded_them(
    client: TestClient, mem_store: dict
) -> None:
    """A document whose structured evidence carries a page + snippet produces a
    per-skill 'Doc: Page N' trace with a bounded snippet — never the raw file."""
    document_id = _seed_document_evidence(
        mem_store,
        evidence_objects=[
            {"skill_name": "Python", "page_number": 2, "snippet": "Implements the FastAPI routing layer."}
        ],
    )
    created = _create_project_defense(
        client, attached_proofs={"document_evidence_ids": [document_id]}
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    doc_traces = [t for t in body["evidence_traces"] if t["source_type"] == "Document Proof"]
    py = next(t for t in doc_traces if t["skill_names"] == ["Python"])
    assert py["page_number"] == 2
    assert py["location_label"] == "Page 2"
    assert py["snippet"] == "Implements the FastAPI routing layer."
    assert py["is_publicly_openable"] is False
    assert py["public_url"] is None


# ── Phase 4: Project Defense answer excerpts (private only) ───────────────────


def _project_with_answered_defense(client: TestClient, mem_store: dict) -> str:
    github_proof_id = _seed_github_proof(mem_store)
    created = _create_project_defense(
        client, repo_url=None, attached_proofs={"github_proof_id": github_proof_id}
    ).json()
    project_id = created["project"]["id"]
    gen = _generate_questions(client, project_id).json()
    session_id = gen["session_id"]
    q = next(q for q in gen["questions"] if q["target_ref"].get("skill"))
    _submit_defense(
        client,
        session_id,
        answers=[{"question_id": q["id"], "answer_text": "I built the routing layer and the React dashboard myself."}],
    )
    return project_id


def test_defense_answer_excerpt_present_in_private_report(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _project_with_answered_defense(client, mem_store)
    body = _get_report(client, project_id).json()
    q_traces = [
        t
        for t in body["evidence_traces"]
        if t["location_type"] == "defense_question" and t.get("answer_excerpt")
    ]
    assert q_traces, "expected an answered-question trace with a bounded answer excerpt"
    assert "routing layer" in q_traces[0]["answer_excerpt"]
    assert q_traces[0]["is_publicly_openable"] is False


# ── Owner-card answer summary: privacy-flagged / sensitive content redaction ──


def _answer_item(answer_text: str, privacy_scan_status: str) -> dict:
    """Build one stored defense answer evidence object for a Python skill Q."""
    from app.services.defense_answer_evidence_service import (
        build_defense_answer_evidence,
    )

    return build_defense_answer_evidence(
        questions=[
            {
                "id": "q1",
                "question_text": "Explain your Python work.",
                "target_ref": {"kind": "skill_link", "skill": "Python"},
                "sort_order": 0,
            }
        ],
        segments=[{"question_id": "q1", "text": answer_text}],
        claimed_skills=["Python"],
        attached_proofs={},
        privacy_scan_status=privacy_scan_status,
    )


_SSN_ANSWER = (
    "I built the FastAPI endpoint and the login schema validation with error "
    "handling; my SSN is 123-45-6789 and it is stored in the request module."
)


def test_private_answer_summary_redacts_flagged_ssn() -> None:
    """A privacy-flagged answer never keeps raw PII in the owner card's
    ``safe_answer_summary`` — even though it is the private report."""
    from app.services.vbr_student_report import (
        _ANSWER_SUMMARY_WITHHELD,
        _report_safe_answer_evidence,
    )

    items = _answer_item(_SSN_ANSWER, privacy_scan_status="flagged")
    # Precondition: the raw stored summary still carries the SSN (the transcript
    # sanitizer strips paths/tokens, not SSNs) — that is exactly what must not
    # survive into the owner card.
    assert "123-45-6789" in items[0]["safe_answer_summary"]

    cards = _report_safe_answer_evidence(items)
    assert cards[0]["safe_answer_summary"] == _ANSWER_SUMMARY_WITHHELD
    assert "123-45-6789" not in cards[0]["safe_answer_summary"]
    # The owner still learns privacy was flagged.
    assert cards[0]["privacy_status"] == "flagged"


def test_private_answer_summary_redacts_ssn_even_if_status_clean() -> None:
    """Defense in depth: a summary carrying an SSN-shaped value is neutralized
    even if the object's privacy status somehow reads clean."""
    from app.services.vbr_student_report import (
        _ANSWER_SUMMARY_WITHHELD,
        _report_safe_answer_evidence,
    )

    items = _answer_item(_SSN_ANSWER, privacy_scan_status="clean")
    cards = _report_safe_answer_evidence(items)
    assert cards[0]["safe_answer_summary"] == _ANSWER_SUMMARY_WITHHELD
    assert "123-45-6789" not in str(cards[0])


def test_public_answer_evidence_withholds_flagged_ssn() -> None:
    """The public projection still fails closed for the flagged SSN answer."""
    from app.services.public_report_safety_service import (
        DEFENSE_ANSWER_WITHHELD_MESSAGE,
        public_safe_defense_answer_evidence,
    )

    items = _answer_item(_SSN_ANSWER, privacy_scan_status="flagged")
    public = public_safe_defense_answer_evidence(items, {"privacy_scan_status": "flagged"})
    assert public[0]["qualitative_status"] == "Withheld for privacy"
    assert public[0]["safe_answer_summary"] == DEFENSE_ANSWER_WITHHELD_MESSAGE
    assert "123-45-6789" not in str(public[0])


def test_private_answer_summary_renders_for_clean_evidence() -> None:
    """A clean, non-sensitive answer still renders its safe summary on the
    owner card."""
    from app.services.vbr_student_report import (
        _ANSWER_SUMMARY_WITHHELD,
        _report_safe_answer_evidence,
    )

    clean_answer = (
        "I implemented the FastAPI endpoint in Python: it validates the request "
        "schema, calls a service module, and returns a typed response with error "
        "handling."
    )
    items = _answer_item(clean_answer, privacy_scan_status="clean")
    cards = _report_safe_answer_evidence(items)
    assert cards[0]["safe_answer_summary"]
    assert cards[0]["safe_answer_summary"] != _ANSWER_SUMMARY_WITHHELD
    # Real (sanitized) answer content is preserved for the owner.
    assert "endpoint" in cards[0]["safe_answer_summary"].lower()


# ── Phase 1: GitHub line/function code evidence (skill_code_evidence) ─────────


_PUBLIC_BLOB = "https://github.com/octocat/Hello-World/blob/main"


def _seed_github_proof_with_code_evidence(mem_store: dict, **overrides) -> str:
    """A GitHub proof whose ``analysis_snapshot`` carries deep line-level
    ``skill_code_evidence`` (file + line range + function + public ``#L`` link)."""
    snapshot = {
        "raw_dump": "should-never-leak",
        "skill_code_evidence": [
            {
                "skill": "Python",
                "file_path": "src/main.py",
                "line_start": 24,
                "line_end": 38,
                "function_name": "classify_image",
                "commit_sha": "ABCDEF0123456789abcdef0123456789abcdef01",
                "code_snippet": "def classify_image(img):\n    return model.predict(img)",
                "github_url": f"{_PUBLIC_BLOB}/src/main.py#L24-L38",
            },
            {
                "skill": "React",
                "file_path": "src/App.tsx",
                "line_start": 10,
                "line_end": 10,
                # Non-hex commit values are sanitized away (never echoed raw).
                "commit_sha": "not a sha!!",
                "code_snippet": "const [state, setState] = useState(null)",
                "github_url": f"{_PUBLIC_BLOB}/src/App.tsx#L10",
            },
            # Unsafe entries are dropped (traversal path + external URL).
            {"skill": "Python", "file_path": "../../etc/passwd", "line_start": 1},
            {"skill": "Python", "file_path": "ok.py", "github_url": "https://evil.example/x#L1"},
        ],
    }
    return _seed_github_proof(mem_store, analysis_snapshot=snapshot, **overrides)


_BLOB_HOSTILE_PATHS = [
    "/Users/alice/private/secret.py",
    "/etc/passwd",
    "C:\\Users\\alice\\private\\secret.py",
    "C:/Users/alice/private/secret.py",
    "file:///Users/alice/private/secret.py",
    "file:/Users/alice/private/secret.py",
    "../secrets.py",
    "..\\secrets.py",
    "~/secret.py",
    "%2e%2e/secrets.py",
    "%252e%252e/secrets.py",
]


@pytest.mark.parametrize("file_path", _BLOB_HOSTILE_PATHS)
def test_blob_url_rejects_unsafe_paths(file_path: str) -> None:
    """must-fix: ``_blob_url`` routes ``file_path`` through
    ``safe_repo_relative_path`` — an absolute / local / Windows / file:// /
    traversal / encoded path yields ``None``, never a fake repo-relative link."""
    from app.services.vbr_student_report import _blob_url

    repo_url = "https://github.com/octocat/Hello-World"
    assert _blob_url(repo_url, "main", file_path) is None


@pytest.mark.parametrize(
    "file_path",
    ["apps/api/main.py", "src/components/Button.tsx", "README.md"],
)
def test_blob_url_builds_link_for_safe_paths(file_path: str) -> None:
    """must-fix: ``_blob_url`` still builds a github blob link for genuine
    repo-relative paths."""
    from app.services.vbr_student_report import _blob_url

    repo_url = "https://github.com/octocat/Hello-World"
    assert _blob_url(repo_url, "main", file_path) == (
        f"https://github.com/octocat/Hello-World/blob/main/{file_path}"
    )


def test_blob_url_normalizes_safe_backslash_path() -> None:
    """A safe relative path with backslashes is normalized, not rejected."""
    from app.services.vbr_student_report import _blob_url

    repo_url = "https://github.com/octocat/Hello-World"
    assert _blob_url(repo_url, "main", "src\\components\\Button.tsx") == (
        "https://github.com/octocat/Hello-World/blob/main/src/components/Button.tsx"
    )


def test_github_code_evidence_drops_absolute_and_local_file_paths(
    client: TestClient, mem_store: dict
) -> None:
    """must-fix: an absolute / local / Windows / file:// file_path in
    ``skill_code_evidence`` must be dropped — never lstrip("/")-ed into a fake
    repo-relative locator that leaks a private filesystem path into the public
    report's evidence traces / blob links."""
    snapshot = {
        "raw_dump": "should-never-leak",
        "skill_code_evidence": [
            {"skill": "Python", "file_path": "/Users/alice/private/secret.py", "line_start": 1},
            {"skill": "Python", "file_path": "/etc/passwd", "line_start": 1},
            {"skill": "Python", "file_path": "C:\\Users\\alice\\private\\secret.py", "line_start": 1},
            {"skill": "Python", "file_path": "C:/Users/alice/private/secret.py", "line_start": 1},
            {"skill": "Python", "file_path": "file:///Users/alice/private/secret.py", "line_start": 1},
            {"skill": "Python", "file_path": "../secrets.py", "line_start": 1},
            {"skill": "Python", "file_path": "..\\secrets.py", "line_start": 1},
            # A genuine repo-relative path still survives end-to-end.
            {
                "skill": "Python",
                "file_path": "src/main.py",
                "line_start": 5,
                "line_end": 9,
                "function_name": "classify_image",
                "commit_sha": "ABCDEF0123456789abcdef0123456789abcdef01",
                "code_snippet": "def classify_image(img):\n    return model.predict(img)",
                "github_url": f"{_PUBLIC_BLOB}/src/main.py#L5-L9",
            },
        ],
    }
    github_proof_id = _seed_github_proof(mem_store, analysis_snapshot=snapshot)
    created = _create_project_defense(
        client, repo_url=None, attached_proofs={"github_proof_id": github_proof_id}
    ).json()
    project_id = created["project"]["id"]

    raw = _get_report(client, project_id).text
    for leaked in (
        "Users/alice",
        "etc/passwd",
        "secret.py",
        "C:",
        "file://",
    ):
        assert leaked not in raw, f"leaked fragment: {leaked!r}"

    body = _get_report(client, project_id).json()
    code_paths = [
        t["file_path"]
        for t in body["evidence_traces"]
        if str(t.get("location_type", "")).startswith("github_") and t.get("file_path")
    ]
    assert "src/main.py" in code_paths


def test_github_code_evidence_produces_line_and_function_traces(
    client: TestClient, mem_store: dict
) -> None:
    """When the GitHub proof recorded line-level ``skill_code_evidence``, the
    report emits exact line/function traces with public ``#L`` links — not just
    a repo-level card."""
    github_proof_id = _seed_github_proof_with_code_evidence(mem_store)
    created = _create_project_defense(
        client, repo_url=None, attached_proofs={"github_proof_id": github_proof_id}
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    code_traces = [t for t in body["evidence_traces"] if str(t["location_type"]).startswith("github_") and t["location_type"] != "github_file"]

    py = next(t for t in code_traces if t["file_path"] == "src/main.py")
    assert py["location_type"] == "github_function"
    assert py["location_label"] == "function classify_image"
    assert py["function_name"] == "classify_image"
    assert py["line_start"] == 24 and py["line_end"] == 38
    assert py["skill_names"] == ["Python"]
    assert py["is_publicly_openable"] is True
    assert py["public_url"] == f"{_PUBLIC_BLOB}/src/main.py#L24-L38"
    assert py["public_url_label"] == "View code on GitHub"
    # The analyzer-recorded commit SHA is surfaced (normalized to lowercase hex).
    assert py["commit_sha"] == "abcdef0123456789abcdef0123456789abcdef01"
    # Private student surface keeps the safe code snippet.
    assert "classify_image" in py["code_snippet"]

    # A non-hex commit value is sanitized to None rather than echoed raw.
    react = next(t for t in code_traces if t["file_path"] == "src/App.tsx")
    assert react["commit_sha"] is None

    react = next(t for t in code_traces if t["file_path"] == "src/App.tsx")
    assert react["location_type"] == "github_lines"
    assert react["location_label"] == "line 10"

    # Traversal path + external github_url entries are dropped entirely.
    paths = {t["file_path"] for t in code_traces}
    assert "../../etc/passwd" not in paths
    assert "should-never-leak" not in _get_report(client, project_id).text


def test_github_code_evidence_private_repo_hides_link_keeps_path(
    client: TestClient, mem_store: dict
) -> None:
    """A private repo never advertises an openable link, but still shows the
    file/line location without a public URL."""
    github_proof_id = _seed_github_proof_with_code_evidence(mem_store, visibility="private")
    created = _create_project_defense(
        client, repo_url=None, attached_proofs={"github_proof_id": github_proof_id}
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    code_traces = [t for t in body["evidence_traces"] if t["file_path"] in {"src/main.py", "src/App.tsx"}]
    assert code_traces
    for t in code_traces:
        assert t["is_publicly_openable"] is False
        assert t["public_url"] is None
        assert t["private_evidence_note"]


def test_github_code_evidence_public_report_strips_snippet_keeps_link(
    client: TestClient, mem_store: dict
) -> None:
    """The public project report drops the raw code snippet but keeps the public
    ``#L`` link as the recruiter-facing proof of the exact lines."""
    from app.services.vbr_student_report import build_student_vbr_report
    from app.services.vbr_public_project_report import _public_evidence_traces

    github_proof_id = _seed_github_proof_with_code_evidence(mem_store)
    created = _create_project_defense(
        client, repo_url=None, attached_proofs={"github_proof_id": github_proof_id}
    ).json()
    project = mem_store["vbr_projects"][created["project"]["id"]]
    report = build_student_vbr_report(mem_store, {}, project, USER_ID)
    public_traces = _public_evidence_traces(report["evidence_traces"])

    code = [t for t in public_traces if t.get("file_path") == "src/main.py"]
    assert code
    for t in code:
        assert t["code_snippet"] is None
        assert t["public_url"] == f"{_PUBLIC_BLOB}/src/main.py#L24-L38"
        # The commit SHA is a safe hex reference and is retained for recruiters.
        assert t["commit_sha"] == "abcdef0123456789abcdef0123456789abcdef01"


# ── Phase 2 (proof-native): weak GitHub line evidence is downgraded ──────────
#
# These fixtures mirror the REAL Boston project's stored ``skill_code_evidence``
# (proven via DB inspection): a Python entry pinned to ``import sys/io/time``, a
# "Google Cloud" entry pinned to a ``sys.path``/repo-root bootstrap comment, and
# notebook-markdown entries. Surfacing those as line-level skill proof is the
# browser bug; the report must drop them to the honest repo-level card.


def _seed_weak_github_proof(mem_store: dict, evidence: list[dict], **overrides) -> str:
    snapshot = {"raw_dump": "should-never-leak", "skill_code_evidence": evidence}
    return _seed_github_proof(mem_store, analysis_snapshot=snapshot, **overrides)


def _github_code_traces(body: dict) -> list[dict]:
    return [
        t
        for t in body["evidence_traces"]
        if str(t["location_type"]).startswith("github_") and t["location_type"] != "github_file"
    ]


def test_github_import_only_line_evidence_not_shown_as_strong_proof(
    client: TestClient, mem_store: dict
) -> None:
    """An import-only snippet (``import sys/io/time``) is never surfaced as
    line-level Python proof; the skill falls back to the repo-level card and the
    card honestly flags that reanalysis/backfill is needed."""
    gpid = _seed_weak_github_proof(
        mem_store,
        evidence=[
            {
                "skill": "Python",
                "file_path": "api.py",
                "line_start": 6,
                "line_end": 9,
                "code_snippet": "import sys\nimport io\nimport time",
                "github_url": f"{_PUBLIC_BLOB}/api.py#L6-L9",
            }
        ],
        detected_skills=["Python"],
    )
    created = _create_project_defense(
        client,
        repo_url=None,
        claimed_skills=["Python"],
        attached_proofs={"github_proof_id": gpid},
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    # No line/function-level trace for the weak import snippet.
    assert _github_code_traces(body) == []

    repo = next(t for t in body["evidence_traces"] if t["trace_id"] == "github-proof")
    assert "Python" in repo["weak_line_evidence_skills"]
    assert "reanalysis" in repo["limitation"].lower()

    # The import line itself must never appear anywhere in the report payload.
    assert "import sys" not in _get_report(client, project_id).text


def test_github_syspath_setup_line_evidence_downgraded(
    client: TestClient, mem_store: dict
) -> None:
    """A ``sys.path`` / repo-root bootstrap snippet is plumbing, not skill proof,
    and is downgraded to the repo-level card."""
    gpid = _seed_weak_github_proof(
        mem_store,
        evidence=[
            {
                "skill": "Google Cloud",
                "file_path": "api.py",
                "line_start": 14,
                "line_end": 17,
                "code_snippet": (
                    "# Ensure repo root is on sys.path so src.predict.predictor is importable\n"
                    "_REPO_ROOT = Path(__file__).resolve().parent"
                ),
                "github_url": f"{_PUBLIC_BLOB}/api.py#L14-L17",
            }
        ],
        detected_skills=["Google Cloud"],
    )
    created = _create_project_defense(
        client,
        repo_url=None,
        claimed_skills=["Google Cloud"],
        attached_proofs={"github_proof_id": gpid},
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    assert _github_code_traces(body) == []
    repo = next(t for t in body["evidence_traces"] if t["trace_id"] == "github-proof")
    assert "Google Cloud" in repo["weak_line_evidence_skills"]
    assert "sys.path" not in _get_report(client, project_id).text


def test_github_notebook_markdown_evidence_downgraded(
    client: TestClient, mem_store: dict
) -> None:
    """Raw ``.ipynb`` markdown narrative cells are not code and are downgraded."""
    gpid = _seed_weak_github_proof(
        mem_store,
        evidence=[
            {
                "skill": "APIs",
                "file_path": "second_model.ipynb",
                "line_start": 123,
                "line_end": 126,
                "code_snippet": '"**APIs**\\n", "* Zillow API: https://pypi.python.org/pypi/pyzillow\\n"',
                "github_url": f"{_PUBLIC_BLOB}/second_model.ipynb#L123-L126",
            }
        ],
        detected_skills=["APIs"],
    )
    created = _create_project_defense(
        client,
        repo_url=None,
        claimed_skills=["APIs"],
        attached_proofs={"github_proof_id": gpid},
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    assert _github_code_traces(body) == []
    repo = next(t for t in body["evidence_traces"] if t["trace_id"] == "github-proof")
    assert "APIs" in repo["weak_line_evidence_skills"]


def test_github_prefers_strong_function_over_weak_import_for_same_skill(
    client: TestClient, mem_store: dict
) -> None:
    """When a skill has BOTH a weak import snippet and a real function snippet,
    the report surfaces the function snippet and never the import line."""
    gpid = _seed_weak_github_proof(
        mem_store,
        evidence=[
            {
                "skill": "Python",
                "file_path": "api.py",
                "line_start": 6,
                "line_end": 9,
                "code_snippet": "import sys\nimport io",
                "github_url": f"{_PUBLIC_BLOB}/api.py#L6-L9",
            },
            {
                "skill": "Python",
                "file_path": "src/model.py",
                "line_start": 20,
                "line_end": 34,
                "function_name": "train_model",
                "code_snippet": "def train_model(df):\n    return clf.fit(df)",
                "github_url": f"{_PUBLIC_BLOB}/src/model.py#L20-L34",
            },
        ],
        detected_skills=["Python"],
    )
    created = _create_project_defense(
        client,
        repo_url=None,
        claimed_skills=["Python"],
        attached_proofs={"github_proof_id": gpid},
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    code = _github_code_traces(body)
    files = {t["file_path"] for t in code}
    assert files == {"src/model.py"}
    fn = code[0]
    assert fn["function_name"] == "train_model"
    assert fn["skill_names"] == ["Python"]

    # Python has strong evidence, so it is NOT flagged as needing reanalysis.
    repo = next(t for t in body["evidence_traces"] if t["trace_id"] == "github-proof")
    assert "Python" not in repo["weak_line_evidence_skills"]


def test_github_strong_route_evidence_still_surfaced(
    client: TestClient, mem_store: dict
) -> None:
    """Genuine code (a FastAPI route + predict function — the real Boston ML
    evidence) is still surfaced as a line-level trace (regression guard)."""
    gpid = _seed_weak_github_proof(
        mem_store,
        evidence=[
            {
                "skill": "Machine Learning",
                "file_path": "api.py",
                "line_start": 252,
                "line_end": 255,
                "code_snippet": '@app.post("/predict")\ndef predict(request):\n    """Predict accident risk severity."""',
                "github_url": f"{_PUBLIC_BLOB}/api.py#L252-L255",
            }
        ],
        detected_skills=["Machine Learning"],
    )
    created = _create_project_defense(
        client,
        repo_url=None,
        claimed_skills=["Machine Learning"],
        attached_proofs={"github_proof_id": gpid},
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    code = _github_code_traces(body)
    assert len(code) == 1
    ml = code[0]
    assert ml["skill_names"] == ["Machine Learning"]
    assert ml["line_start"] == 252 and ml["line_end"] == 255
    assert ml["is_publicly_openable"] is True

    repo = next(t for t in body["evidence_traces"] if t["trace_id"] == "github-proof")
    assert repo["weak_line_evidence_skills"] == []


def test_vbr_report_uses_shared_github_skill_evidence_filter() -> None:
    """The VBR Project Report's weak-line classifier IS the canonical shared one,
    so the Skill Report and the VBR Report downgrade weak GitHub evidence with the
    exact same logic (no divergent duplicate filter)."""
    from app.services import vbr_student_report
    from app.services.github_skill_evidence_service import (
        is_strong_code_snippet,
        safe_code_snippet,
        safe_commit_sha,
    )

    assert vbr_student_report._is_strong_code_snippet is is_strong_code_snippet
    assert vbr_student_report._safe_code_snippet is safe_code_snippet
    assert vbr_student_report._safe_commit_sha is safe_commit_sha


def test_website_dom_card_drops_off_target_page_context(
    client: TestClient, mem_store: dict
) -> None:
    """When the only DOM signal is an off-target page captured mid-session (e.g. a
    Google Docs tab on docs.google.com while proving teachablemachine.withgoogle.com),
    it is never surfaced as the target site's DOM summary."""
    session_id = _seed_workflow_analysis(
        mem_store,
        target_website="https://teachablemachine.withgoogle.com",
        supported_skills=["Machine Learning"],
        observed_demonstration={"dom_summary": ""},
        page_context_summary=(
            "DOM text was captured from 'MIT AI Ethics Curriculum - Google Docs' "
            "(docs.google.com) page. Visible text included: Request edit access; Share."
        ),
        workflow_summary="The student demonstrated teachablemachine.withgoogle.com.",
    )
    created = _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    ).json()
    project_id = created["project"]["id"]

    raw = _get_report(client, project_id).text
    assert "docs.google.com" not in raw
    assert "Google Docs" not in raw

    body = _get_report(client, project_id).json()
    dom_cards = [t for t in body["evidence_traces"] if t["location_type"] == "website_dom"]
    assert dom_cards == []


# ── Phase 2: Website OCR/DOM/Qwen/NLP/live-check/workflow trace cards ─────────


def _seed_rich_website(mem_store: dict, **overrides) -> str:
    """A Website Proof session with the deeper safe artifacts populated."""
    fields: dict = {
        "target_website": "https://demo.example.com",
        "supported_skills": ["Machine Learning", "React"],
        "workflow_summary": "The user uploaded an image and the model returned a classification.",
        "demonstrated_actions": ["Clicked Upload", "Selected an image", "Read the prediction"],
        "observed_demonstration": {"dom_summary": "A prediction label and confidence bar were rendered."},
        "page_context_summary": "Image classification demo page.",
        "dom_evidence_status": "available",
        "frame_ocr_evidence_summary": {
            "has_ocr_evidence": True,
            "top_ocr_snippets": ["Prediction: cat", "Confidence: high"],
            "matched_ui_labels": ["Upload", "Classify"],
            "frames_analyzed": 4,
        },
        "visual_reasoning_summary": {
            "status": "analyzed",
            "frames_analyzed": 4,
            "summary": "The interface shows an image being classified with a visible result.",
        },
    }
    fields.update(overrides)
    session_id = _seed_workflow_analysis(mem_store, **fields)
    # Live reachability check for the same session.
    row_id = str(uuid4())
    mem_store.setdefault("live_website_check_results", {})[row_id] = {
        "id": row_id,
        "user_id": USER_ID,
        "proof_session_id": session_id,
        "website_url": "https://demo.example.com",
        "final_url": "https://demo.example.com/",
        "page_title": "Image Classifier Demo",
        "is_reachable": True,
        "confidence": "high",
        "recruiter_summary": "The deployed site responded successfully.",
        "created_at": datetime.now(UTC).isoformat(),
    }
    return session_id


def test_website_rich_artifact_trace_cards(client: TestClient, mem_store: dict) -> None:
    """Saved OCR/DOM/visual/NLP/live-check/workflow summaries each become a
    Website trace card when available."""
    session_id = _seed_rich_website(mem_store)
    created = _create_project_defense(
        client,
        # The project must CLAIM the skill for the image-classification behaviour to
        # map to it — a Website Proof only ever supports a project's claimed skills.
        claimed_skills=["Machine Learning", "React"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    web = [t for t in body["evidence_traces"] if t["source_type"] == "Website Proof"]
    loc_types = {t["location_type"] for t in web}
    assert {
        "website_url",
        "website_live_check",
        "website_workflow",
        "website_dom",
        "website_ocr",
        "website_visual",
        "website_nlp",
    } <= loc_types

    ocr = next(t for t in web if t["location_type"] == "website_ocr")
    assert ocr["location_label"] == "OCR summary"
    assert "Prediction: cat" in ocr["safe_summary"]
    assert "behaviour" in ocr["limitation"].lower()
    # The image-classification behaviour maps ONLY to the project's claimed skills it
    # actually supports (the canonical Website→skill mapping) — never the raw stored
    # ``supported_skills``. Machine Learning is claimed here and the demonstrated
    # prediction/classification behaviour maps to it.
    assert "Machine Learning" in ocr["skill_names"]

    live = next(t for t in web if t["location_type"] == "website_live_check")
    assert "reachable" in live["safe_summary"].lower()


def test_website_trace_cards_never_expose_raw_payloads(client: TestClient, mem_store: dict) -> None:
    """Website trace cards never leak raw DOM/OCR/provider payloads or storage paths."""
    session_id = _seed_rich_website(
        mem_store,
        # Try to smuggle unsafe data into the saved artifact.
        observed_demonstration={
            "dom_summary": "A prediction label was rendered.",
            "screenshot_url": "https://bucket.example/secret.png",
            "storage_path": "/private/bucket/raw.html",
        },
    )
    created = _create_project_defense(
        client, attached_proofs={"website_proof_session_ids": [session_id]}
    ).json()
    project_id = created["project"]["id"]

    raw = _get_report(client, project_id).text
    for unsafe in ["screenshot_url", "storage_path", "secret.png", "/private/bucket", "signed_url"]:
        assert unsafe not in raw, f"unsafe website fragment leaked: {unsafe!r}"


def test_website_without_rich_artifacts_keeps_single_card(client: TestClient, mem_store: dict) -> None:
    """A bare Website Proof (no deeper artifacts) still renders the single live-URL
    card and no fabricated OCR/DOM/visual cards."""
    session_id = _seed_workflow_analysis(mem_store)  # scoring fields only
    created = _create_project_defense(
        client, attached_proofs={"website_proof_session_ids": [session_id]}
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    web = [t for t in body["evidence_traces"] if t["source_type"] == "Website Proof"]
    loc_types = {t["location_type"] for t in web}
    assert "website_url" in loc_types
    assert "website_ocr" not in loc_types
    assert "website_dom" not in loc_types
    # Bare proof carried no deeper artifacts, so the project-level card flags the
    # missing-summary limitation honestly rather than implying depth.
    url_card = next(t for t in web if t["location_type"] == "website_url")
    assert "no safe OCR/DOM/vision/NLP summaries" in url_card["limitation"]


def test_website_with_empty_supported_skills_is_project_level_evidence(
    client: TestClient, mem_store: dict
) -> None:
    """Website Proof attached with NO ``supported_skills`` still appears in Evidence
    Traceability as project-level evidence (it maps to no skill row) and carries the
    honest 'not mapped to specific skills' limitation."""
    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=[],
    )
    created = _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    web = [t for t in body["evidence_traces"] if t["source_type"] == "Website Proof"]
    # Still surfaced as a Website trace even with no supported skills.
    assert web, "Website Proof must still appear as project-level evidence"
    card = next(t for t in web if t["location_type"] in {"website_url", "website_proof"})
    # Project-level: it maps to no skill row, so it can never overstate a claim.
    assert card["skill_names"] == []
    assert "no supported_skills" in card["limitation"]
    # And it does NOT pollute any skill-matrix row's evidence traces.
    for row in body["skill_evidence"]:
        assert card["trace_id"] not in (row.get("evidence_traces") or [])


# ── Website Proof: skill mapping DERIVED from safe pipeline summaries ─────────
#
# Website Proof, like GitHub Proof, must surface skill-SPECIFIC evidence — GitHub
# maps code, Website maps observed runtime behaviour. When the pipeline persisted
# rich safe summaries but NO explicit ``supported_skills``, a mapping may still be
# conservatively DERIVED from the observed behaviour — but only when that behaviour
# genuinely demonstrates the skill (never a generic/landing/availability page, and
# never an unrelated claimed skill).


def _skill_row(body: dict, skill: str) -> dict:
    return next(r for r in body["skill_evidence"] if r["skill"] == skill)


def _website_skill_names(body: dict) -> set[str]:
    return {
        r["skill_name"]
        for e in body.get("website_skill_evidence", [])
        for r in e.get("skills", [])
    }


def test_website_derives_ml_skill_from_prediction_behavior(
    client: TestClient, mem_store: dict
) -> None:
    """A Website Proof with EMPTY ``supported_skills`` but a safe prediction-result
    narrative maps to the claimed ML skill (derived), and the skill matrix + the
    behavior-evidence card agree, so the passport can surface it."""
    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=[],
        workflow_summary="Entered input values and the model displayed a prediction result.",
    )
    created = _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()

    # Behavior-evidence card mapped the claimed skill, honestly flagged "derived".
    entry = next(e for e in body["website_skill_evidence"])
    assert entry["skill_mapping_available"] is True
    ml = next(r for r in entry["skills"] if r["skill_name"] == "Machine Learning")
    assert ml["mapping_basis"] == "derived"
    # A demo UI is product-behaviour context for ML — never implementation proof.
    assert ml["is_direct_evidence"] is False
    assert "not" in ml["limitation"].lower()
    # The safe NLP summary backed the mapping (closed label, not raw text).
    assert "Website NLP" in entry["evidence_source_types"]

    # Skill matrix row now lists Website Proof — this is what feeds the passport
    # ``supporting_proof_types`` and the Website Proof filter.
    assert "Website Proof" in _skill_row(body, "Machine Learning")["supporting_sources"]


def test_generic_website_stays_project_level_only(
    client: TestClient, mem_store: dict
) -> None:
    """A generic Website Proof (a landing page that only proves the site exists,
    empty ``supported_skills``) maps to NO skill — it stays project-level, and the
    skill matrix never gains a Website Proof source chip."""
    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=[],
        workflow_summary="A landing page describing the product and its features was shown.",
    )
    created = _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()

    entry = next(e for e in body["website_skill_evidence"])
    assert entry["skills"] == []
    assert entry["skill_mapping_available"] is False
    assert "Website Proof" not in _skill_row(body, "Machine Learning")["supporting_sources"]


def test_website_does_not_map_to_unrelated_claimed_skills(
    client: TestClient, mem_store: dict
) -> None:
    """A prediction-result demo derives the ML skill but NOT an unrelated claimed
    skill (Docker): a demo UI never proves Docker/CI-CD internals."""
    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=[],
        workflow_summary="Entered input values and the model displayed a prediction result.",
    )
    created = _create_project_defense(
        client,
        claimed_skills=["Machine Learning", "Docker"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()

    mapped = _website_skill_names(body)
    assert "Machine Learning" in mapped
    assert "Docker" not in mapped
    assert "Website Proof" in _skill_row(body, "Machine Learning")["supporting_sources"]
    assert "Website Proof" not in _skill_row(body, "Docker")["supporting_sources"]


def test_broad_stored_supported_skills_do_not_leak_into_matrix_or_passport_refs(
    client: TestClient, mem_store: dict
) -> None:
    """THE leak regression: a Website Proof whose STORED ``supported_skills`` is broad
    (React, Docker, AWS, SQL, NLP, Security …) must NOT paint every claimed skill with
    a Website Proof source. The stored list is a hint only — only the skills the
    observed image-classification behaviour genuinely supports earn the Website Proof
    chip, and the ``website_skill_evidence`` map is a strict subset of the validated
    skills (no project-level Website Proof becomes skill evidence)."""
    broad = ["Machine Learning", "React", "Docker", "AWS", "SQL", "Security"]
    session_id = _seed_workflow_analysis(
        mem_store,
        target_website="https://teachablemachine.withgoogle.com",
        supported_skills=broad,  # deliberately broad / dirty stored list
        weakly_supported_skills=[],
        workflow_summary="The user uploaded an image and the model displayed a classification result.",
    )
    created = _create_project_defense(
        client,
        claimed_skills=broad,
        attached_proofs={"website_proof_session_ids": [session_id]},
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()

    # The behaviour-evidence map is a STRICT SUBSET of validated skills: the
    # image-classification behaviour maps ML (model product-behaviour context) and
    # React (interactive UI), never the infra/data/security skills the stored list
    # also named — a demo UI carries no relevance to Docker/AWS/SQL/Security.
    mapped = set(_website_skill_names(body))
    assert "Machine Learning" in mapped
    assert not (mapped & {"Docker", "AWS", "SQL", "Security"})

    # Skill matrix supporting-sources agree — the passport ``supporting_proof_types``
    # is built from exactly this, so no unrelated skill gains a Website Proof chip.
    assert "Website Proof" in _skill_row(body, "Machine Learning")["supporting_sources"]
    for unrelated in ("Docker", "AWS", "SQL", "Security"):
        assert "Website Proof" not in _skill_row(body, unrelated)["supporting_sources"], unrelated

    # The website evidence TRACE cards are scoped to the same validated skills — a
    # broad stored list never rides through as a per-skill trace attribution either.
    web_traces = [t for t in body["evidence_traces"] if t["source_type"] == "Website Proof"]
    for t in web_traces:
        assert not (set(t["skill_names"]) & {"Docker", "AWS", "SQL", "Security"})


def test_website_derives_api_skill_from_api_behavior(
    client: TestClient, mem_store: dict
) -> None:
    """A request→result API narrative derives a FastAPI skill mapping (API-backed
    behaviour context), even with empty ``supported_skills``."""
    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=[],
        workflow_summary="A request was sent to the API endpoint and the JSON response was rendered on the page.",
    )
    created = _create_project_defense(
        client,
        claimed_skills=["FastAPI"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    assert "FastAPI" in _website_skill_names(body)
    api_row = next(r for e in body["website_skill_evidence"] for r in e["skills"] if r["skill_name"] == "FastAPI")
    assert api_row["relevance_key"] == "api_behavior_context"
    assert "Website Proof" in _skill_row(body, "FastAPI")["supporting_sources"]


def test_website_skill_evidence_exposes_only_safe_source_labels(
    client: TestClient, mem_store: dict
) -> None:
    """The derived skill evidence + source-type labels are closed-vocabulary only —
    never raw DOM/OCR/visual/provider text, storage paths, or scores."""
    from app.services.website_skill_proof_focus import (
        ALLOWED_WEBSITE_EVIDENCE_SOURCE_TYPES,
    )

    session_id = _seed_rich_website(
        mem_store,
        supported_skills=[],
        observed_demonstration={
            "dom_summary": "A prediction label was rendered.",
            "screenshot_url": "https://bucket.example/secret.png",
            "storage_path": "/private/bucket/raw.html",
        },
    )
    created = _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    entry = next(e for e in body["website_skill_evidence"])
    # Source-type labels are all from the closed vocabulary.
    for label in entry["evidence_source_types"]:
        assert label in ALLOWED_WEBSITE_EVIDENCE_SOURCE_TYPES
    # No smuggled raw fields anywhere in the website_skill_evidence payload.
    import json

    blob = json.dumps(body["website_skill_evidence"])
    for unsafe in ["screenshot_url", "storage_path", "secret.png", "/private/bucket", "signed_url"]:
        assert unsafe not in blob


def test_navigation_layout_entry_carries_unmapped_reason_and_action(
    client: TestClient, mem_store: dict
) -> None:
    """A navigation/layout Website Proof stays project-level (no skill row) and the
    entry carries a safe reason + strengthening action so the gap is legible."""
    from app.services.website_skill_proof_focus import WEBSITE_STRENGTHEN_ACTION

    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=[],
        workflow_summary="Navigated between the app's pages using the sidebar menu.",
    )
    created = _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    ).json()
    project_id = created["project"]["id"]

    entry = next(e for e in _get_report(client, project_id).json()["website_skill_evidence"])
    assert entry["skills"] == []
    assert entry["skill_mapping_available"] is False
    assert entry["website_purpose_key"] == "navigation_layout"
    assert entry["unmapped_reason"] == "Navigation/layout evidence only"
    assert entry["strengthen_action"] == WEBSITE_STRENGTHEN_ACTION


def test_mapped_website_entry_has_no_unmapped_reason(
    client: TestClient, mem_store: dict
) -> None:
    """When a Website Proof DID map a skill, the project-level-only fields stay empty
    (they describe the unmapped gap, never a mapped proof)."""
    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=[],
        workflow_summary="Entered input values and the model displayed a prediction result.",
    )
    created = _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    ).json()
    project_id = created["project"]["id"]

    entry = next(e for e in _get_report(client, project_id).json()["website_skill_evidence"])
    assert entry["skill_mapping_available"] is True
    assert entry["unmapped_reason"] == ""
    assert entry["strengthen_action"] == ""


# ── Phase 3: Document citation (matched section heading) ─────────────────────


def test_document_citation_trace_when_section_recorded(client: TestClient, mem_store: dict) -> None:
    """A document evidence object with a ``section_label`` (and no page) becomes a
    'Doc: Citation' trace carrying the safe section heading."""
    document_id = _seed_document_evidence(
        mem_store,
        evidence_objects=[
            {"skill_name": "Python", "section_label": "System Design", "snippet": "Built the API."}
        ],
    )
    created = _create_project_defense(
        client, attached_proofs={"document_evidence_ids": [document_id]}
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    doc = next(
        t for t in body["evidence_traces"]
        if t["source_type"] == "Document Proof" and t["skill_names"] == ["Python"]
    )
    assert doc["location_type"] == "document_citation"
    assert doc["location_label"] == "Citation"
    assert doc["citation"] == "System Design"
    assert doc["is_publicly_openable"] is False


# ── Stale attached-document metadata rehydration (Boston root cause) ──────────


def test_stale_attached_document_metadata_rehydrates_evidence_objects(
    client: TestClient, mem_store: dict
) -> None:
    """A document attached BEFORE per-skill evidence was recorded into project
    metadata (stale ``attached_proofs.documents`` with no ``skills``) still
    becomes skill-level Document Proof: the report re-reads the live
    ``optional_evidence_submissions.evidence_objects`` at build time.

    Mirrors the real Boston project — the attach-time summary lacks skills, but
    the document row carries rich ``evidence_objects`` (skill_name + page/section
    + snippet)."""
    # 1. Seed the document with NO evidence_objects → attach-time skills are empty.
    document_id = _seed_document_evidence(mem_store)

    # 2. Attach it. metadata.attached_proofs.documents now has the id/title/
    #    status/source_type but skills == [] (stale, pre-skills metadata).
    created = _create_project_defense(
        client, attached_proofs={"document_evidence_ids": [document_id]}
    ).json()
    project_id = created["project"]["id"]

    attached_docs = created["metadata"]["attached_proofs"]["documents"]
    assert attached_docs[0]["document_evidence_id"] == document_id
    assert attached_docs[0]["skills"] == [], "precondition: attach metadata has no skills"

    # 3. The REAL document row gains rich evidence_objects after attach (as in
    #    Boston, where the analyzer's structured evidence outlives the stale
    #    attach summary). Python is a claimed skill; "Rust" is not.
    mem_store["optional_evidence_submissions"][document_id]["evidence_objects"] = [
        {
            "skill_name": "Python",
            "snippet": "Implements the FastAPI routing and request validation layer.",
            "reason": "Describes the backend implementation.",
            "page_number": 3,
            "section_label": "Backend Architecture",
            "line_start": 12,
            "line_end": 40,
        },
        {
            "skill_name": "Rust",  # not a claimed skill → must never map.
            "snippet": "Unrelated systems note.",
            "page_number": 9,
        },
    ]

    body = _get_report(client, project_id).json()

    # Document Proof trace is now SKILL-LEVEL for the matched claimed skill.
    doc_traces = [t for t in body["evidence_traces"] if t["source_type"] == "Document Proof"]
    py = next(t for t in doc_traces if t["skill_names"] == ["Python"])
    assert py["page_number"] == 3
    assert py["location_label"] == "Page 3"
    assert "FastAPI routing" in py["snippet"]
    assert py["citation"] == "Backend Architecture"
    assert py["is_publicly_openable"] is False
    assert py["public_url"] is None

    # Skill matrix includes Document Proof for the matched skill only.
    rows = _rows_by_skill(body)
    assert "Document Proof" in rows["Python"]["supporting_sources"]
    assert rows["Python"]["status"] == "Supporting evidence"

    # The unrelated claimed skill (React) gets NO Document Proof, and the
    # unclaimed evidence_objects skill (Rust) never appears at all.
    assert "Document Proof" not in rows["React"]["supporting_sources"]
    assert all(t["skill_names"] == ["Python"] for t in doc_traces)
    assert "Rust" not in _get_report(client, project_id).text


# ── Website Proof: never auto-attached when not in project metadata ───────────


def test_report_does_not_auto_attach_unrelated_website_proofs(
    client: TestClient, mem_store: dict
) -> None:
    """Unrelated Website Proofs owned by the same user but NOT attached to this
    project must never be auto-attached into the PRIMARY attached-proof section:
    the attached matrix/traces read only the project's own
    ``attached_proofs.website_proofs``.

    They MAY, however, surface in the separate "Other student proofs for related
    skills" vault section — clearly labelled as not attached to this project — so
    the report stays project-honest without hiding the student's real evidence.
    """
    # An unrelated website proof exists for the same user, but is never attached.
    _seed_workflow_analysis(
        mem_store,
        target_website="https://unrelated.example.com",
        supported_skills=["Python", "React"],
    )

    created = _create_project_defense(client).json()  # no website_proofs attached
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()

    # Primary attached section: the unrelated proof is absent.
    assert body["website_proofs"] == []
    assert body["evidence_package"]["website_proofs_count"] == 0
    web_traces = [t for t in body["evidence_traces"] if t["source_type"] == "Website Proof"]
    assert web_traces == [], "unrelated Website Proof must not be auto-attached"
    assert "Website proof not attached." in body["limitations"]

    # Secondary vault section: it surfaces as a cross-proof match for the project's
    # claimed skills, clearly labelled as not attached to this project.
    vault_web = [
        proof
        for group in body["other_student_proofs"]
        for proof in group["proofs"]
        if proof["proof_type"] == "Website Proof"
    ]
    assert vault_web, "unrelated Website Proof should appear as an 'other student proof'"
    for proof in vault_web:
        assert proof["is_attached_to_project"] is False
        assert "Not attached to a VBR project." in proof["limitation"]


# ── Website Proof: attached + empty supported_skills ⇒ project-level trace ────


def test_attached_website_with_empty_supported_skills_still_counts_as_project_level_website_trace(
    client: TestClient, mem_store: dict
) -> None:
    """An attached Website Proof whose saved detail has empty ``supported_skills``
    still produces at least one Website Proof trace — project-level (no skill
    mapping) — with a limitation explaining it was not mapped because the saved
    proof carries no supported_skills."""
    session_id = _seed_workflow_analysis(
        mem_store,
        target_website="https://app.example.com",
        supported_skills=[],
        weakly_supported_skills=[],
    )
    created = _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    web = [t for t in body["evidence_traces"] if t["source_type"] == "Website Proof"]
    assert web, "attached Website Proof must still appear as project-level evidence"

    primary = next(t for t in web if t["location_type"] in {"website_url", "website_proof"})
    # Project-level: maps to no skill row, so it can never overstate a per-skill claim.
    assert primary["skill_names"] == []
    assert "not mapped to specific skills" in primary["limitation"]
    assert "supported_skills" in primary["limitation"]

    # It does not pollute any skill-matrix row.
    for row in body["skill_evidence"]:
        assert primary["trace_id"] not in (row.get("evidence_traces") or [])


# ── Website detail service is invoked for an attached Website Proof ──────────


def test_website_detail_service_is_used_for_attached_website_proof(
    client: TestClient, mem_store: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The report hydrates deeper Website Proof artifacts through
    ``website_proof_detail_service.get_website_proof_detail`` — confirmed by a spy
    — and emits the live/workflow/OCR/visual cards it returns."""
    import app.services.vbr_student_report as report_mod

    session_id = _seed_rich_website(mem_store)

    real = report_mod.get_website_proof_detail
    calls: list[str] = []

    def _spy(db, user_id, proof_session_id):
        calls.append(str(proof_session_id))
        return real(db, user_id, proof_session_id)

    monkeypatch.setattr(report_mod, "get_website_proof_detail", _spy)

    created = _create_project_defense(
        client, attached_proofs={"website_proof_session_ids": [session_id]}
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()

    # The detail service was invoked for the attached session.
    assert session_id in calls

    # The live/workflow/OCR/visual cards it produced are emitted.
    web = [t for t in body["evidence_traces"] if t["source_type"] == "Website Proof"]
    loc_types = {t["location_type"] for t in web}
    assert {
        "website_live_check",
        "website_workflow",
        "website_ocr",
        "website_visual",
    } <= loc_types


# ── Performance: passport summary skips the per-project cross-proof vault scan ─


def test_include_cross_proof_false_skips_whole_vault_scan(monkeypatch) -> None:
    """The Work Passport builds a report per project but never reads
    ``other_student_proofs``. ``include_cross_proof=False`` must skip the
    expensive whole-vault scan (``collect_vault_items``) entirely — and the
    single-report view must pay it exactly ONCE (shared by the cross-proof
    section and the suggested-evidence classification)."""
    import app.services.student_proof_vault_service as vault
    import app.services.vbr_student_report as report_mod

    calls = {"n": 0}

    def _spy(*args, **kwargs):  # pragma: no cover - should never run when gated
        calls["n"] += 1
        return []

    monkeypatch.setattr(vault, "collect_vault_items", _spy)

    project = {"id": str(uuid4()), "title": "P", "metadata": {"claimed_skills": ["Python"]}}

    gated = report_mod.build_student_vbr_report({}, {}, project, USER_ID, include_cross_proof=False)
    assert gated["other_student_proofs"] == []
    assert gated["suggested_evidence"] == []
    assert calls["n"] == 0

    # Default behaviour still runs the scan (backward compatible) — once.
    report_mod.build_student_vbr_report({}, {}, project, USER_ID)
    assert calls["n"] == 1


# ── Attachment Intelligence Cleanup (Step 4): suggested evidence separation ───


def test_report_separates_suggested_evidence_from_attached(
    client: TestClient, mem_store: dict
) -> None:
    """An unattached document whose safe title mentions the project appears ONLY
    under ``suggested_evidence`` ("not counted until attached") — never in the
    attached evidence package or the documents list."""
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]

    # Unattached document that clearly names the project.
    _seed_document_evidence(
        mem_store, analysis_json={"title": "Skill Evidence Tracker — Design Report"}
    )

    body = _get_report(client, project_id).json()
    assert body["evidence_package"]["documents_count"] == 0
    assert body["documents"] == []

    suggested = body["suggested_evidence"]
    assert suggested, "expected a suggested-evidence entry for the matching document"
    for entry in suggested:
        assert entry["attachment_state"] == "suggested"
        assert entry["status_label"] == "Suggested — not counted until attached"
        assert entry["relation_strength"] in ("likely", "weak")
        # Safe display fields only — never a raw source id or storage path.
        assert "source_id" not in entry
        assert "file_path" not in entry


def test_report_suggested_evidence_never_includes_attached_documents(
    client: TestClient, mem_store: dict
) -> None:
    """A document explicitly attached to the project stays ATTACHED evidence —
    it is never duplicated as a suggestion."""
    document_id = _seed_document_evidence(mem_store)
    created = _create_project_defense(
        client, attached_proofs={"document_evidence_ids": [document_id]}
    ).json()
    project_id = created["project"]["id"]

    body = _get_report(client, project_id).json()
    assert body["evidence_package"]["documents_count"] == 1
    titles = [e["display_title"] for e in body["suggested_evidence"]]
    assert "Final Year Project Report" not in titles


def test_public_project_report_never_carries_suggested_evidence(
    client: TestClient, mem_store: dict
) -> None:
    """The public report projection is a whitelist — suggested evidence and its
    reason/strength labels must never appear there."""
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    _seed_document_evidence(
        mem_store, analysis_json={"title": "Skill Evidence Tracker — Design Report"}
    )
    token = client.post(
        f"/api/v1/student/vbr/projects/{project_id}/public-report"
    ).json()["public_token"]

    public = client.get(f"/api/v1/public/vbr/reports/{token}")
    assert public.status_code == 200
    body = public.json()
    assert "suggested_evidence" not in body
    text = public.text
    assert "Suggested — not counted until attached" not in text
    assert "relation_reason" not in text
    assert "relation_strength" not in text
