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

    # Both claimed skills were mentioned/explained in DEFENSE_TRANSCRIPT, so
    # the skill evidence table should reflect Demonstrated / Partially demonstrated
    # — never raw numeric scores.
    statuses = {row["skill"]: row["status"] for row in body["skill_evidence"]}
    assert statuses["Python"] in {"Demonstrated", "Partially demonstrated"}
    assert statuses["React"] in {"Demonstrated", "Partially demonstrated"}
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
