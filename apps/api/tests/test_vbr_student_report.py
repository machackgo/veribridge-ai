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


def test_report_skill_matrix_maps_skills_to_evidence_sources(client: TestClient, mem_store: dict) -> None:
    """Each skill row carries the canonical evidence-source labels that support
    it (GitHub / Website / Project Defense / Video) — never numeric scores."""
    github_proof_id = _seed_github_proof(mem_store)  # detects Python + React
    website_proof_session_id = _seed_workflow_analysis(mem_store)  # supports React

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

    # Python is detected by the GitHub Proof only.
    assert rows["Python"]["supporting_sources"] == ["GitHub Proof"]
    # React is detected by GitHub Proof and supported by the Website Proof,
    # in canonical (GitHub → Website) order.
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
        "skill-evidence",
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
