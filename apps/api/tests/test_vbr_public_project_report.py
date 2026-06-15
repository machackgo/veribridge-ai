"""Tests for the public recruiter-safe VBR project report link (v1).

Owner-only:
  ``POST   /api/v1/student/vbr/projects/{project_id}/public-report``
  ``DELETE /api/v1/student/vbr/projects/{project_id}/public-report``
  ``GET    /api/v1/student/vbr/projects/{project_id}/public-report/status``

Public (no auth):
  ``GET  /api/v1/public/vbr/reports/{public_token}``

Covers:
  - student can publish their own project report; non-owner cannot
  - publish is idempotent (stable token, not rotated)
  - public token returns the report without authentication
  - invalid / revoked tokens return 404
  - public report omits raw/private fields, internal IDs, numeric scores,
    and ``evidence_strength_score``
  - public report works when video / transcript / website proof are missing
  - public report includes sanitized video chips (no ``question_id``) when
    available, and never exposes the token in its body

All storage is in-memory (dict mode). No real network calls, no LLM calls.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.services.vbr_public_project_report import _scrub_public_report

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


# ── Helpers ──────────────────────────────────────────────────────────────────

def _publish(client: TestClient, project_id: str):
    return client.post(f"/api/v1/student/vbr/projects/{project_id}/public-report")


def _unpublish(client: TestClient, project_id: str):
    return client.delete(f"/api/v1/student/vbr/projects/{project_id}/public-report")


def _publish_status(client: TestClient, project_id: str):
    return client.get(f"/api/v1/student/vbr/projects/{project_id}/public-report/status")


def _get_public(client: TestClient, token: str):
    return client.get(f"/api/v1/public/vbr/reports/{token}")


def _make_full_project(client: TestClient, mem_store: dict) -> str:
    """Create a project with GitHub/document/website proof, analysis, and video chips."""
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


# ── Publish ownership / idempotency ──────────────────────────────────────────

def test_student_can_publish_owned_project_report(client: TestClient) -> None:
    project_id = _create_project_defense(client).json()["project"]["id"]

    response = _publish(client, project_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_public"] is True
    assert body["public_token"]
    assert body["public_path"] == f"/vbr/report/{body['public_token']}"
    assert body["published_at"]


def test_non_owner_cannot_publish(client: TestClient) -> None:
    project_id = _create_project_defense(client).json()["project"]["id"]

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = _publish(client, project_id)
    assert response.status_code == 404


def test_publish_is_idempotent_and_token_is_stable(client: TestClient) -> None:
    project_id = _create_project_defense(client).json()["project"]["id"]

    first = _publish(client, project_id).json()
    second = _publish(client, project_id).json()
    assert first["public_token"] == second["public_token"]

    status_body = _publish_status(client, project_id).json()
    assert status_body["is_public"] is True
    assert status_body["public_token"] == first["public_token"]


def test_publish_status_unpublished_by_default(client: TestClient) -> None:
    project_id = _create_project_defense(client).json()["project"]["id"]

    status_body = _publish_status(client, project_id).json()
    assert status_body["is_public"] is False
    assert status_body["public_token"] is None
    assert status_body["public_path"] is None


def test_non_owner_cannot_read_publish_status(client: TestClient) -> None:
    project_id = _create_project_defense(client).json()["project"]["id"]

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    assert _publish_status(client, project_id).status_code == 404


# ── Public read (no auth) ────────────────────────────────────────────────────

def test_public_token_returns_report_without_auth(client: TestClient) -> None:
    project_id = _create_project_defense(client).json()["project"]["id"]
    token = _publish(client, project_id).json()["public_token"]

    # Prove no authentication is required: remove the auth override entirely.
    app.dependency_overrides.pop(get_current_user_id, None)

    response = _get_public(client, token)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["report_title"] == "Verified Build Report"
    assert body["project_title"] == "Skill Evidence Tracker"
    assert body["published_at"]


def test_invalid_token_returns_404(client: TestClient) -> None:
    assert _get_public(client, "definitely-not-a-real-token").status_code == 404


def test_revoked_token_returns_404(client: TestClient) -> None:
    project_id = _create_project_defense(client).json()["project"]["id"]
    token = _publish(client, project_id).json()["public_token"]

    assert _get_public(client, token).status_code == 200

    unpub = _unpublish(client, project_id).json()
    assert unpub["is_public"] is False
    assert unpub["public_token"] is None

    assert _get_public(client, token).status_code == 404


def test_unpublish_is_idempotent(client: TestClient) -> None:
    project_id = _create_project_defense(client).json()["project"]["id"]
    _publish(client, project_id)

    assert _unpublish(client, project_id).json()["is_public"] is False
    # Second unpublish on an already-revoked project is a safe no-op.
    assert _unpublish(client, project_id).json()["is_public"] is False


# ── Public report works with a minimal project ───────────────────────────────

def test_public_report_works_without_video_transcript_or_website(client: TestClient) -> None:
    project_id = _create_project_defense(client).json()["project"]["id"]
    token = _publish(client, project_id).json()["public_token"]

    response = _get_public(client, token)
    assert response.status_code == 200, response.text
    body = response.json()

    pkg = body["evidence_package"]
    assert pkg["website_proofs_count"] == 0
    assert pkg["video_defense_recorded"] is False
    assert pkg["video_evidence_chip_count"] == 0
    assert body["website_proofs"] == []
    assert body["video_evidence_chips"] == []
    assert body["project_defense_analysis"] is None

    # Honest empty states survive into the public report.
    assert "Website proof not attached." in body["limitations"]
    assert "Video defense not recorded yet." in body["limitations"]


# ── Sanitized video chips ────────────────────────────────────────────────────

def test_public_report_includes_sanitized_video_chips(client: TestClient, mem_store: dict) -> None:
    project_id = _make_full_project(client, mem_store)
    token = _publish(client, project_id).json()["public_token"]

    response = _get_public(client, token)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["evidence_package"]["video_defense_recorded"] is True
    chips = body["video_evidence_chips"]
    assert chips
    for chip in chips:
        assert chip["label"].startswith("Video ")
        assert len(chip["short_summary"]) <= 160
        # Internal references are stripped from public chips.
        assert "question_id" not in chip


# ── Privacy / score guardrails ───────────────────────────────────────────────

def test_public_report_omits_numeric_scores_and_evidence_strength_score(client: TestClient, mem_store: dict) -> None:
    project_id = _make_full_project(client, mem_store)
    token = _publish(client, project_id).json()["public_token"]

    response = _get_public(client, token)
    assert response.status_code == 200, response.text
    raw = response.text

    for field in [
        "overall_defense_score",
        "explanation_clarity_score",
        "ownership_signal_score",
        "technical_depth_score",
        "consistency_with_evidence_score",
        "evidence_strength_score",
        "confidence_score",
    ]:
        assert field not in raw, f"Numeric score leaked into public report: {field!r}"

    # Qualitative labels are used instead.
    analysis = response.json()["project_defense_analysis"]
    assert analysis is not None
    qualitative = {"Demonstrated", "Partially demonstrated", "Supporting evidence", "Needs review", "Not assessed"}
    assert analysis["overall_assessment"] in qualitative


def test_public_report_omits_raw_private_fields_and_token(client: TestClient, mem_store: dict) -> None:
    # Seed a candidate display name so it appears (and confirm email never does).
    mem_store.setdefault("users", {})[USER_ID] = {
        "id": USER_ID,
        "full_name": "Jordan Rivera",
        "email": "jordan.private@example.com",
    }

    project_id = _make_full_project(client, mem_store)
    token = _publish(client, project_id).json()["public_token"]

    response = _get_public(client, token)
    assert response.status_code == 200, response.text
    body = response.json()
    raw = response.text

    # Candidate display name surfaces; private email / auth id never do.
    assert body["candidate_display_name"] == "Jordan Rivera"
    assert "jordan.private@example.com" not in raw
    assert USER_ID not in raw

    # The public token must never be echoed back inside the report body.
    assert token not in raw

    # Internal IDs not needed publicly are omitted.
    assert "project_id" not in body
    assert "session_id" not in body
    assert "defense_questions" not in body
    assert "next_actions" not in body

    unsafe_substrings = [
        "storage_path",
        "signed_url",
        "access_token",
        "vbr/sessions",
        "full_text",
        "repo_metadata",
        "analysis_snapshot",
        "document_evidence_id",
        "proof_session_id",
        "github_proof_id",
        "skill_pipeline_id",
        "Bearer ",
        "supabase.co",
        ".webm",
        ".mp4",
        "should-never-leak",
        "/100",
        "fully verified",
    ]
    for unsafe in unsafe_substrings:
        assert unsafe not in raw, f"Unsafe field/value leaked into public report: {unsafe!r}"

    # Full raw transcript text must never appear verbatim.
    assert DEFENSE_TRANSCRIPT not in raw


# ── Recursive numeric-score scrubber ─────────────────────────────────────────

def test_recursive_scrubber_protects_multiple_nested_public_string_fields() -> None:
    """The scrubber redacts score-like strings in every nested string field,
    not just ``github_proof.public_safe_summary`` (must-fix #2)."""
    payload = {
        "project_summary": "Trust score 88/100 with 92% coverage.",
        "student_role": "Scored 95% on review and ranked #1 overall.",
        "github_proof": {"public_safe_summary": "fully verified; score 70/100 confidence."},
        "documents": [{"title": "Final report scored 80/100"}],
        "skill_evidence": [
            {"status": "Demonstrated", "notes": "trust score high, scored 9/10."},
            {"status": "Partially demonstrated", "notes": "Supporting evidence only."},
        ],
        "video_evidence_chips": [{"short_summary": "explains API with 75% coverage"}],
        "limitations": ["Ranked #3 overall with 60% accuracy."],
        "nested": {"deep": ["score 12", {"deeper": "85 %"}]},
        # Non-string values must pass through untouched.
        "count": 7,
        "flag": True,
        "ratio": 1.5,
        "empty": None,
    }

    scrubbed = _scrub_public_report(payload)

    import json

    blob = json.dumps(scrubbed).lower()
    for forbidden in ["/100", "%", "score", "trust score", "fully verified"]:
        assert forbidden not in blob, f"Score-like fragment leaked: {forbidden!r}"

    # Qualitative labels survive verbatim.
    assert scrubbed["skill_evidence"][0]["status"] == "Demonstrated"
    assert scrubbed["skill_evidence"][1]["status"] == "Partially demonstrated"
    assert "Supporting evidence" in scrubbed["skill_evidence"][1]["notes"]
    # Non-string types pass through unchanged.
    assert scrubbed["count"] == 7
    assert scrubbed["flag"] is True
    assert scrubbed["ratio"] == 1.5
    assert scrubbed["empty"] is None


def _score_laden_report() -> dict:
    """A student-report-shaped payload with score-like strings in every field."""
    return {
        "project_title": "Risk scoring platform 92/100",
        "project_description": "Achieved a trust score of 88/100 and ranked #1 overall.",
        "student_role": "Led the build; scored 95% on internal review.",
        "repo_full_name": "octocat/Hello-World",
        "claimed_skills": ["Python", "React"],
        "generated_at": "2026-01-02T00:00:00Z",
        "evidence_package": {
            "github_proof_attached": True,
            "documents_count": 1,
            "website_proofs_count": 1,
            "project_defense_completed": True,
            "video_defense_recorded": True,
            "video_evidence_chip_count": 1,
        },
        "github_proof": {
            "repo_url": "https://github.com/octocat/Hello-World",
            "repo_owner": "octocat",
            "repo_name": "Hello-World",
            "status": "analyzed",
            "detected_skills": ["Python"],
            "public_safe_summary": "GitHub proof scored 72/100 confidence; fully verified.",
        },
        "documents": [{"title": "Report scored 80/100", "source_type": "document", "status": "analyzed"}],
        "website_proofs": [
            {
                "target_website": "http://demo.example.com",
                "evidence_strength": "Evidence observed",
                "workflow_confidence": "high",
                "supported_skills": ["React"],
            }
        ],
        "project_defense_analysis": {
            "transcript_summary": "Explained the design; trust score 90% noted.",
            "skills_mentioned": ["Python"],
            "skills_explained_well": ["Python"],
            "skills_missing_from_explanation": [],
            "overall_assessment": "Partially demonstrated",
            "explanation_clarity": "Demonstrated",
            "ownership_signal": "Partially demonstrated",
            "technical_depth": "Supporting evidence",
            "consistency_with_evidence": "Needs review",
            "risk_flags": [],
            "recruiter_summary": "Strong candidate, ranked #2 with 85% confidence.",
            "recommended_improvements": [],
            "privacy_scan_status": "clean",
        },
        "skill_evidence": [
            {"skill": "Python", "status": "Demonstrated", "evidence_chip_count": 2, "notes": "Scored 9/10; trust score high."}
        ],
        "video_evidence_chips": [
            {
                "label": "Video 03:12",
                "timestamp_start_s": 192,
                "timestamp_end_s": 210,
                "short_summary": "explains API; 75% coverage",
                "related_skill": "Python",
                "source": "project_defense_video",
                "source_type": "video_transcript",
            }
        ],
        "limitations": ["Project Defense reflects the student's own explanation of their work."],
    }


def test_public_report_scrubs_score_strings_across_all_fields(
    client: TestClient, mem_store: dict, monkeypatch
) -> None:
    """End-to-end: the recursive scrubber is wired into the public endpoint and
    removes score-like fragments from every field, keeping qualitative labels."""
    mem_store.setdefault("users", {})[USER_ID] = {
        "id": USER_ID,
        "full_name": "Top scored candidate",
        "email": "private@example.com",
    }
    project_id = _create_project_defense(client).json()["project"]["id"]
    token = _publish(client, project_id).json()["public_token"]

    monkeypatch.setattr(
        "app.services.vbr_public_project_report.build_student_vbr_report",
        lambda *args, **kwargs: _score_laden_report(),
    )
    app.dependency_overrides.pop(get_current_user_id, None)

    response = _get_public(client, token)
    assert response.status_code == 200, response.text
    raw = response.text
    lowered = raw.lower()

    for forbidden in ["/100", "%", "score", "trust score", "fully verified", "evidence_strength_score", "ranked #"]:
        assert forbidden not in lowered, f"Score-like fragment leaked into public report: {forbidden!r}"

    body = response.json()
    # Qualitative labels and safe summaries survive.
    assert body["project_defense_analysis"]["overall_assessment"] == "Partially demonstrated"
    assert body["project_defense_analysis"]["explanation_clarity"] == "Demonstrated"
    assert any(row["status"] == "Demonstrated" for row in body["skill_evidence"])
    assert body["github_proof"]["public_safe_summary"].strip()
    assert body["candidate_display_name"] == "Top candidate"
    assert "private@example.com" not in raw
