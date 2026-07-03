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

import json
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


def test_public_report_exposes_safe_links_only(client: TestClient, mem_store: dict) -> None:
    project_id = _make_full_project(client, mem_store)
    token = _publish(client, project_id).json()["public_token"]

    app.dependency_overrides.pop(get_current_user_id, None)
    body = _get_public(client, token).json()

    # The deployed_url field is always present (None when not provided).
    assert "deployed_url" in body
    # A public github proof is flagged so the UI may surface a direct repo link.
    assert body["github_proof"] is not None
    assert body["github_proof"]["repo_is_public"] is True
    assert body["github_proof"]["repo_url"].startswith("https://github.com/")
    # Still no raw private fields leak alongside the safe link.
    raw = str(body).lower()
    assert "should-never-leak" not in raw
    assert "storage_path" not in raw


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


# ── Direct verification link safety gate (must-fix) ──────────────────────────


def _minimal_report(**overrides) -> dict:
    """A small student-report-shaped payload for direct-link safety tests."""
    base = {
        "project_title": "Demo Project",
        "project_description": "",
        "student_role": "",
        "repo_full_name": "octocat/Hello-World",
        "deployed_url": None,
        "claimed_skills": [],
        "evidence_package": {
            "github_proof_attached": False,
            "documents_count": 0,
            "website_proofs_count": 0,
            "project_defense_completed": False,
            "video_defense_recorded": False,
            "video_evidence_chip_count": 0,
        },
        "github_proof": None,
        "documents": [],
        "website_proofs": [],
        "project_defense_analysis": None,
        "skill_evidence": [],
        "video_evidence_chips": [],
        "limitations": [],
        "generated_at": "2026-01-02T00:00:00Z",
    }
    base.update(overrides)
    return base


def _publish_and_get_with_report(client, mem_store, monkeypatch, report):
    project_id = _create_project_defense(client).json()["project"]["id"]
    token = _publish(client, project_id).json()["public_token"]
    monkeypatch.setattr(
        "app.services.vbr_public_project_report.build_student_vbr_report",
        lambda *args, **kwargs: report,
    )
    app.dependency_overrides.pop(get_current_user_id, None)
    return _get_public(client, token)


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://localhost:3000",
        "http://127.0.0.1:8000",
        "http://192.168.1.10/app",
        "http://10.0.0.5",
        "http://172.16.0.4/dashboard",
        "http://169.254.1.1",
        "https://staging.internal/app",
        "https://dev.local",
        "http://intranet/app",
        "file:///etc/passwd",
        "data:text/html,<script>alert(1)</script>",
        "blob:https://example.com/uuid",
        "javascript:alert(1)",
    ],
)
def test_public_report_omits_unsafe_deployed_url(
    client: TestClient, mem_store: dict, monkeypatch, unsafe_url: str
) -> None:
    response = _publish_and_get_with_report(
        client, mem_store, monkeypatch, _minimal_report(deployed_url=unsafe_url)
    )
    assert response.status_code == 200, response.text
    body = response.json()

    # The unsafe direct link is dropped, never echoed back as the raw URL.
    assert body["deployed_url"] is None
    assert unsafe_url not in response.text
    # The omission is reflected honestly in limitations.
    assert any("private or internal" in line.lower() for line in body["limitations"])


def test_public_report_keeps_safe_public_deployed_url(
    client: TestClient, mem_store: dict, monkeypatch
) -> None:
    response = _publish_and_get_with_report(
        client, mem_store, monkeypatch, _minimal_report(deployed_url="https://threejs.org")
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deployed_url"] == "https://threejs.org"
    # No spurious omission limitation when every link is public-safe.
    assert not any("private or internal" in line.lower() for line in body["limitations"])


def test_public_report_keeps_safe_public_github_repo_link(
    client: TestClient, mem_store: dict, monkeypatch
) -> None:
    report = _minimal_report(
        github_proof={
            "repo_url": "https://github.com/octocat/Hello-World",
            "repo_owner": "octocat",
            "repo_name": "Hello-World",
            "status": "analyzed",
            "detected_skills": ["Python"],
            "public_safe_summary": "Public repo evidence observed.",
            "repo_is_public": True,
        }
    )
    response = _publish_and_get_with_report(client, mem_store, monkeypatch, report)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["github_proof"]["repo_url"] == "https://github.com/octocat/Hello-World"
    assert body["github_proof"]["repo_is_public"] is True


def test_public_report_drops_repo_link_when_repo_url_not_public(
    client: TestClient, mem_store: dict, monkeypatch
) -> None:
    report = _minimal_report(
        github_proof={
            "repo_url": "http://localhost:8080/repo",
            "repo_owner": "octocat",
            "repo_name": "Hello-World",
            "status": "analyzed",
            "detected_skills": ["Python"],
            "public_safe_summary": "Repo evidence observed.",
            "repo_is_public": True,
        }
    )
    response = _publish_and_get_with_report(client, mem_store, monkeypatch, report)
    assert response.status_code == 200, response.text
    body = response.json()
    # Flagged "public" but the URL is not public-safe → never advertised as linkable.
    assert body["github_proof"]["repo_is_public"] is False


def test_public_report_blanks_unsafe_website_targets_but_keeps_safe_ones(
    client: TestClient, mem_store: dict, monkeypatch
) -> None:
    report = _minimal_report(
        website_proofs=[
            {
                "target_website": "https://threejs.org",
                "evidence_strength": "Evidence observed",
                "workflow_confidence": "high",
                "supported_skills": ["React"],
            },
            {
                "target_website": "http://192.168.1.50/app",
                "evidence_strength": "Supporting evidence",
                "workflow_confidence": "medium",
                "supported_skills": ["Node"],
            },
        ]
    )
    response = _publish_and_get_with_report(client, mem_store, monkeypatch, report)
    assert response.status_code == 200, response.text
    body = response.json()
    proofs = body["website_proofs"]
    assert len(proofs) == 2
    # The public target survives; the private one is blanked (never echoed raw).
    assert proofs[0]["target_website"] == "https://threejs.org"
    assert proofs[1]["target_website"] == ""
    assert "192.168.1.50" not in response.text
    # Qualitative evidence on the omitted-link proof is preserved.
    assert proofs[1]["evidence_strength"] == "Supporting evidence"
    assert proofs[1]["supported_skills"] == ["Node"]
    assert any("private or internal" in line.lower() for line in body["limitations"])


def test_public_report_returns_no_unsafe_raw_url_anywhere(
    client: TestClient, mem_store: dict, monkeypatch
) -> None:
    report = _minimal_report(
        deployed_url="http://localhost:3000",
        website_proofs=[
            {
                "target_website": "http://10.0.0.5/internal",
                "evidence_strength": "Supporting evidence",
                "workflow_confidence": "low",
                "supported_skills": [],
            }
        ],
        github_proof={
            "repo_url": "file:///private/repo",
            "repo_owner": None,
            "repo_name": None,
            "status": "analyzed",
            "detected_skills": [],
            "public_safe_summary": "Repo evidence observed.",
            "repo_is_public": True,
        },
    )
    response = _publish_and_get_with_report(client, mem_store, monkeypatch, report)
    assert response.status_code == 200, response.text
    raw = response.text
    for unsafe in ["localhost:3000", "10.0.0.5", "file://"]:
        assert unsafe not in raw, f"Unsafe raw URL leaked into public report: {unsafe!r}"
    assert response.json()["github_proof"]["repo_is_public"] is False


def test_public_report_links_back_to_published_passport(client: TestClient, mem_store: dict) -> None:
    """The public report links back to the candidate's Work Passport — but only
    once that passport is itself published, never to a private passport."""
    from app.services.vbr_work_passport_service import publish_passport

    project_id = _create_project_defense(client).json()["project"]["id"]
    token = _publish(client, project_id).json()["public_token"]
    app.dependency_overrides.pop(get_current_user_id, None)

    # No passport published yet → no backlink.
    body = _get_public(client, token).json()
    assert body["public_passport_path"] is None

    # Publish the passport, then the report links back to /p/{slug}.
    status = publish_passport(mem_store, USER_ID)
    slug = status["public_slug"]
    assert slug
    body = _get_public(client, token).json()
    assert body["public_passport_path"] == f"/p/{slug}"


# ── Evidence traceability (public projection) ────────────────────────────────

def test_public_report_includes_evidence_traces_per_skill(client: TestClient, mem_store: dict) -> None:
    project_id = _make_full_project(client, mem_store)
    token = _publish(client, project_id).json()["public_token"]
    app.dependency_overrides.pop(get_current_user_id, None)

    body = _get_public(client, token).json()
    traces = body["evidence_traces"]
    assert traces
    source_types = {t["source_type"] for t in traces}
    assert {"GitHub Proof", "Document Proof", "Project Defense"} <= source_types

    trace_ids = {t["trace_id"] for t in traces}
    # Every supported skill row references concrete, resolvable traces.
    assert any(row["evidence_traces"] for row in body["skill_evidence"])
    for row in body["skill_evidence"]:
        assert row["why_this_status"]
        for tid in row["evidence_traces"]:
            assert tid in trace_ids


def test_public_report_trace_links_are_safe_public_only(client: TestClient, mem_store: dict, monkeypatch) -> None:
    """A trace with an unsafe public_url is never advertised as openable."""
    report = _minimal_report(
        github_proof={
            "repo_url": "https://github.com/octocat/Hello-World",
            "repo_owner": "octocat",
            "repo_name": "Hello-World",
            "status": "analyzed",
            "detected_skills": ["Python"],
            "public_safe_summary": "Public repo evidence observed.",
            "repo_is_public": True,
        },
        claimed_skills=["Python"],
        evidence_traces=[
            {
                "trace_id": "github-proof",
                "source_type": "GitHub Proof",
                "source_title": "octocat/Hello-World",
                "skill_names": ["Python"],
                "qualitative_status": "Supporting evidence",
                "safe_summary": "Repo analyzed.",
                "safe_detail": "Static analysis.",
                "evidence_anchor": "github-proof",
                "public_url": "https://github.com/octocat/Hello-World",
                "public_url_label": "View public repository",
                "timestamp": None,
                "limitation": "Not sole authorship.",
                "is_publicly_openable": True,
                "private_evidence_note": None,
            },
            {
                "trace_id": "website-proof-1",
                "source_type": "Website Proof",
                "source_title": "http://localhost:3000",
                "skill_names": ["Python"],
                "qualitative_status": "Supporting evidence",
                "safe_summary": "Local deploy.",
                "safe_detail": "Checked.",
                "evidence_anchor": "website-proof-1",
                "public_url": "http://localhost:3000",
                "public_url_label": "Open live website",
                "timestamp": None,
                "limitation": "Check time only.",
                "is_publicly_openable": True,
                "private_evidence_note": None,
            },
        ],
    )
    response = _publish_and_get_with_report(client, mem_store, monkeypatch, report)
    assert response.status_code == 200, response.text
    body = response.json()
    traces = {t["trace_id"]: t for t in body["evidence_traces"]}

    # Safe github link survives and is openable.
    assert traces["github-proof"]["is_publicly_openable"] is True
    assert traces["github-proof"]["public_url"] == "https://github.com/octocat/Hello-World"
    # Unsafe localhost link is dropped, never echoed, and marked not openable.
    assert traces["website-proof-1"]["is_publicly_openable"] is False
    assert traces["website-proof-1"]["public_url"] is None
    assert traces["website-proof-1"]["private_evidence_note"]
    assert "localhost:3000" not in response.text


def test_public_report_traces_have_no_score_language(client: TestClient, mem_store: dict) -> None:
    project_id = _make_full_project(client, mem_store)
    token = _publish(client, project_id).json()["public_token"]
    app.dependency_overrides.pop(get_current_user_id, None)
    raw = _get_public(client, token).text.lower()
    for forbidden in ["/100", "trust score", "fully verified"]:
        assert forbidden not in raw, f"score-like fragment leaked into public traces: {forbidden!r}"


def test_public_report_document_proof_is_consistent_and_safe(
    client: TestClient, mem_store: dict
) -> None:
    """The public projection keeps the same Document Proof consistency as the
    student report and never leaks raw document content."""
    document_id = _seed_document_evidence(
        mem_store,
        evidence_objects=[{"skill_name": "Python", "confidence": "high", "snippet": "raw-doc-text-should-never-leak"}],
    )
    created = _create_project_defense(
        client, attached_proofs={"document_evidence_ids": [document_id]}
    ).json()
    project_id = created["project"]["id"]
    token = _publish(client, project_id).json()["public_token"]

    app.dependency_overrides.pop(get_current_user_id, None)
    response = _get_public(client, token)
    assert response.status_code == 200, response.text
    body = response.json()
    raw = response.text

    rows = {row["skill"]: row for row in body["skill_evidence"]}
    assert "Document Proof" in rows["Python"]["supporting_sources"]
    assert "Document Proof" not in rows["React"]["supporting_sources"]

    # Public document traces stay safe/conservative: never openable, never raw.
    doc_traces = [t for t in body["evidence_traces"] if t["source_type"] == "Document Proof"]
    assert doc_traces
    for trace in doc_traces:
        assert trace["is_publicly_openable"] is False
        assert trace["public_url"] is None
        assert trace["private_evidence_note"]
        assert trace["skill_names"] == ["Python"]
    assert "raw-doc-text-should-never-leak" not in raw

    # Invariant survives the public projection.
    traces_by_id = {t["trace_id"]: t for t in body["evidence_traces"]}
    for row in body["skill_evidence"]:
        skill_l = row["skill"].lower()
        row_has_doc = "Document Proof" in row["supporting_sources"]
        trace_claims = any(
            traces_by_id[tid]["source_type"] == "Document Proof"
            and skill_l in {s.lower() for s in traces_by_id[tid]["skill_names"]}
            for tid in row.get("evidence_traces", [])
        )
        assert row_has_doc == trace_claims


def test_public_report_strips_document_snippet_and_answer_excerpt(
    client: TestClient, mem_store: dict
) -> None:
    """Private-only proof excerpts (document snippet, defense answer excerpt) are
    never exposed on the public recruiter surface, while the location label /
    question text reference is preserved."""
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
    gen = _generate_questions(client, project_id).json()
    q = next(q for q in gen["questions"] if q["target_ref"].get("skill"))
    _submit_defense(
        client,
        gen["session_id"],
        answers=[{"question_id": q["id"], "answer_text": "I personally wrote the routing layer."}],
    )

    token = _publish(client, project_id).json()["public_token"]
    raw = _get_public(client, token).text
    assert "Implements the FastAPI routing layer." not in raw
    assert "I personally wrote the routing layer." not in raw

    body = _get_public(client, token).json()
    for trace in body["evidence_traces"]:
        assert trace.get("snippet") is None
        assert trace.get("answer_excerpt") is None


# ── Step 7: centralized Public Safety gate (strengthened, fail-closed) ────────


def test_public_report_fail_closed_on_nested_source_id(
    client: TestClient, mem_store: dict, monkeypatch
) -> None:
    """A private ``source_id`` smuggled into a nested report field must trip the
    strengthened central scan and 404 the public report (fail-closed)."""
    report = _minimal_report(
        skill_evidence=[{"skill": "Python", "status": "Demonstrated", "source_id": "private-row-uuid"}]
    )
    response = _publish_and_get_with_report(client, mem_store, monkeypatch, report)
    assert response.status_code == 404, response.text


def test_public_report_fail_closed_on_raw_metadata(
    client: TestClient, mem_store: dict, monkeypatch
) -> None:
    """A raw ``metadata`` / ``raw_payload`` bag must never reach a public report.

    The defense carries an explicit clean privacy status so the fail-closed privacy
    projection passes it through unchanged — the raw metadata bag therefore reaches
    the whole-payload gate, which must still 404. (A missing/flagged status would
    instead be withheld to a safe placeholder that drops the bag earlier; this
    exercises the gate itself.)
    """
    report = _minimal_report(
        project_defense_analysis={
            "privacy_scan_status": "clean",
            "metadata": {"provider_response": {"model": "x"}},
        }
    )
    response = _publish_and_get_with_report(client, mem_store, monkeypatch, report)
    assert response.status_code == 404, response.text


def test_public_report_fail_closed_on_local_path_value(
    client: TestClient, mem_store: dict, monkeypatch
) -> None:
    """A local ``/Users/…`` path lurking in a non-scrubbed position fails closed."""
    report = _minimal_report(documents=[{"title": "Doc", "local_path": "/Users/me/secret.pdf"}])
    response = _publish_and_get_with_report(client, mem_store, monkeypatch, report)
    assert response.status_code == 404, response.text


def test_public_report_scrubs_email_in_free_text(
    client: TestClient, mem_store: dict, monkeypatch
) -> None:
    """An email address in a free-text field is scrubbed, and the report still
    serves (the central gate redacts recoverable content rather than 404-ing)."""
    report = _minimal_report(project_description="Reach the author at private@example.com for a demo.")
    response = _publish_and_get_with_report(client, mem_store, monkeypatch, report)
    assert response.status_code == 200, response.text
    assert "private@example.com" not in response.text


# ── Project Defense privacy fail-closed (audit finding) ──────────────────────

# An SSN-shaped value the generic scrubbers do NOT catch (not a token/path/URL/
# email/score). It survives generic scrubbing, so only the privacy fail-closed
# projection keeps it out of the public report.
_DEFENSE_SSN = "123-45-6789"


def _flagged_defense_report(status: str = "flagged") -> dict:
    """A student-report-shaped payload whose Project Defense failed privacy review.

    The SSN-shaped marker appears in every place a flagged transcript could leak
    it: the analysis ``transcript_summary`` (first sentence of the raw transcript)
    and the defense evidence trace's ``safe_summary`` / ``answer_excerpt``.
    """
    first_sentence = f"Transcript (11 words): my social security number is {_DEFENSE_SSN} and I built it."
    return _minimal_report(
        claimed_skills=["Python"],
        project_defense_analysis={
            "transcript_summary": first_sentence,
            "skills_mentioned": ["Python"],
            "skills_explained_well": ["Python"],
            "skills_missing_from_explanation": [],
            "overall_assessment": "Partially demonstrated",
            "explanation_clarity": "Demonstrated",
            "ownership_signal": "Partially demonstrated",
            "technical_depth": "Supporting evidence",
            "consistency_with_evidence": "Needs review",
            "risk_flags": ["Transcript contains potential sensitive data."],
            "recruiter_summary": "Project defense transcript analyzed.",
            "recommended_improvements": [],
            "privacy_scan_status": status,
        },
        evidence_traces=[
            {
                "trace_id": "project-defense",
                "source_type": "Project Defense",
                "source_title": "Project Defense",
                "skill_names": ["Python"],
                "qualitative_status": "Supporting evidence",
                "safe_summary": first_sentence,
                "safe_detail": f"Answer text: my SSN is {_DEFENSE_SSN}.",
                "answer_excerpt": f"my SSN is {_DEFENSE_SSN}",
                "question_text": "What did you build?",
                "location_type": "defense_overview",
                "public_url": None,
                "public_url_label": None,
                "is_publicly_openable": False,
            }
        ],
    )


def test_public_report_hides_privacy_flagged_defense_transcript(
    client: TestClient, mem_store: dict, monkeypatch
) -> None:
    """The audit leak path: a privacy-flagged transcript's SSN-shaped value must
    not appear ANYWHERE in the public project report payload."""
    response = _publish_and_get_with_report(client, mem_store, monkeypatch, _flagged_defense_report())
    assert response.status_code == 200, response.text

    # The SSN-shaped value never appears anywhere in the serialized public payload.
    assert _DEFENSE_SSN not in response.text

    body = response.json()
    analysis = body["project_defense_analysis"]
    assert analysis is not None
    # transcript_summary is replaced with the safe placeholder wording.
    assert _DEFENSE_SSN not in analysis["transcript_summary"]
    assert "privacy review did not pass" in analysis["transcript_summary"].lower()
    assert "privacy review did not pass" in analysis["recruiter_summary"].lower()


def test_public_report_flagged_defense_omits_all_derived_text(
    client: TestClient, mem_store: dict, monkeypatch
) -> None:
    """Raw transcript / first sentence / answer text / recruiter+risk summaries are
    all absent from the public output when the defense privacy review is not clean."""
    response = _publish_and_get_with_report(client, mem_store, monkeypatch, _flagged_defense_report())
    assert response.status_code == 200, response.text
    body = response.json()
    raw = response.text

    analysis = body["project_defense_analysis"]
    # No transcript-derived content survives: free text is the safe placeholder,
    # list fields are emptied, labels are neutralized.
    assert _DEFENSE_SSN not in json.dumps(analysis)
    assert analysis["skills_mentioned"] == []
    assert analysis["skills_explained_well"] == []
    assert analysis["risk_flags"] == []
    assert analysis["overall_assessment"] == "Not assessed"
    assert "privacy review did not pass" in analysis["transcript_summary"].lower()

    # The defense evidence trace is scrubbed of its derived text.
    defense_traces = [t for t in body["evidence_traces"] if t.get("source_type") == "Project Defense"]
    assert defense_traces, "expected the project-defense trace to still be present"
    for trace in defense_traces:
        assert _DEFENSE_SSN not in json.dumps(trace)
        assert trace.get("answer_excerpt") is None
        assert trace.get("question_text") is None
        assert "hidden from this public report" in (trace.get("safe_summary") or "").lower()

    # Belt-and-braces: neither the first sentence nor the raw answer text leaks.
    assert "social security number" not in raw.lower()
    assert "answer text: my ssn" not in raw.lower()


def test_public_report_safe_defense_still_shows_summary_and_traces(
    client: TestClient, mem_store: dict, monkeypatch
) -> None:
    """A non-sensitive Project Defense (clean privacy scan) still produces the
    expected public-safe summary and qualitative labels — the fail-closed path is
    NOT triggered for clean transcripts."""
    clean = _flagged_defense_report(status="clean")
    clean["project_defense_analysis"]["transcript_summary"] = (
        "Transcript (11 words): I built a task manager with FastAPI and a React frontend."
    )
    clean["project_defense_analysis"]["risk_flags"] = []
    clean["evidence_traces"][0]["safe_summary"] = "The candidate explained how and why they built the project."
    clean["evidence_traces"][0]["safe_detail"] = "Process/ownership evidence."
    clean["evidence_traces"][0]["answer_excerpt"] = None

    response = _publish_and_get_with_report(client, mem_store, monkeypatch, clean)
    assert response.status_code == 200, response.text
    body = response.json()

    analysis = body["project_defense_analysis"]
    # Clean analysis keeps its qualitative labels and its (safe) transcript summary.
    assert analysis["overall_assessment"] == "Partially demonstrated"
    assert analysis["explanation_clarity"] == "Demonstrated"
    assert "content_hidden" not in analysis
    assert "task manager" in analysis["transcript_summary"].lower()

    # The defense trace keeps its safe summary (no hidden-content placeholder).
    defense_traces = [t for t in body["evidence_traces"] if t.get("source_type") == "Project Defense"]
    assert defense_traces
    assert "hidden from this public report" not in (defense_traces[0].get("safe_summary") or "").lower()


def _video_chip_with_ssn() -> dict:
    """A timestamped video-evidence chip whose transcript-derived summary carries
    the SSN-shaped marker (the chips are built from the SAME transcript segments)."""
    return {
        "label": "Video 00:12",
        "timestamp_start_s": 12.0,
        "timestamp_end_s": 25.0,
        "short_summary": f"my social security number is {_DEFENSE_SSN}",
        "related_skill": "Python",
        "source": "project_defense_video",
        "source_type": "video_transcript",
    }


def _video_trace_with_ssn() -> dict:
    """A ``Video Evidence`` evidence trace derived from the flagged transcript."""
    return {
        "trace_id": "video-chip-001",
        "source_type": "Video Evidence",
        "source_title": "Video 00:12",
        "skill_names": ["Python"],
        "qualitative_status": "Supporting evidence",
        "safe_summary": f"my social security number is {_DEFENSE_SSN}",
        "safe_detail": "A timestamped moment in the recorded Project Defense.",
        "location_type": "video_timestamp",
        "timestamp_label": "Video 00:12",
        "public_url": None,
        "public_url_label": None,
        "is_publicly_openable": False,
    }


def test_public_report_flagged_defense_omits_video_chips_and_traces(
    client: TestClient, mem_store: dict, monkeypatch
) -> None:
    """Requirement #3: video/timestamp chips (and their ``Video Evidence`` traces)
    are DERIVED from the same Project Defense transcript, so when its privacy review
    is not clean they must fail closed too — the SSN-shaped snippet must not leak."""
    report = _flagged_defense_report()
    report["video_evidence_chips"] = [_video_chip_with_ssn()]
    report["evidence_traces"].append(_video_trace_with_ssn())

    response = _publish_and_get_with_report(client, mem_store, monkeypatch, report)
    assert response.status_code == 200, response.text
    assert _DEFENSE_SSN not in response.text
    assert "social security number" not in response.text.lower()

    body = response.json()
    # Video chips derived from the flagged transcript are omitted entirely.
    assert body["video_evidence_chips"] == []
    # The Video Evidence trace survives structurally but its derived text is gone.
    video_traces = [t for t in body["evidence_traces"] if t.get("source_type") == "Video Evidence"]
    assert video_traces, "expected the video-evidence trace to still be present"
    for trace in video_traces:
        assert _DEFENSE_SSN not in json.dumps(trace)
        assert "hidden from the public report" in (trace.get("safe_summary") or "").lower()
        assert trace.get("safe_detail") == ""


def test_public_report_clean_defense_keeps_video_chips_and_traces(
    client: TestClient, mem_store: dict, monkeypatch
) -> None:
    """A clean Project Defense keeps its (safe) video chips and their traces — the
    video fail-closed path is NOT triggered for a clean transcript."""
    clean = _flagged_defense_report(status="clean")
    clean["project_defense_analysis"]["transcript_summary"] = (
        "Transcript (9 words): I built a task manager with FastAPI."
    )
    clean["project_defense_analysis"]["risk_flags"] = []
    clean["evidence_traces"][0]["safe_summary"] = "The candidate explained how they built the project."
    clean["evidence_traces"][0]["safe_detail"] = "Process/ownership evidence."
    clean["evidence_traces"][0]["answer_excerpt"] = None
    clean["video_evidence_chips"] = [
        {
            "label": "Video 00:12",
            "timestamp_start_s": 12.0,
            "timestamp_end_s": 25.0,
            "short_summary": "I built the backend API using FastAPI.",
            "related_skill": "Python",
            "source": "project_defense_video",
            "source_type": "video_transcript",
        }
    ]
    clean["evidence_traces"].append(
        {
            "trace_id": "video-chip-001",
            "source_type": "Video Evidence",
            "source_title": "Video 00:12",
            "skill_names": ["Python"],
            "qualitative_status": "Supporting evidence",
            "safe_summary": "I built the backend API using FastAPI.",
            "safe_detail": "A timestamped moment in the recorded Project Defense.",
            "location_type": "video_timestamp",
            "public_url": None,
            "is_publicly_openable": False,
        }
    )

    response = _publish_and_get_with_report(client, mem_store, monkeypatch, clean)
    assert response.status_code == 200, response.text
    body = response.json()

    # Clean transcript: video chips are preserved (with their safe summary).
    assert len(body["video_evidence_chips"]) == 1
    assert "fastapi" in body["video_evidence_chips"][0]["short_summary"].lower()
    video_traces = [t for t in body["evidence_traces"] if t.get("source_type") == "Video Evidence"]
    assert video_traces
    assert "hidden from the public report" not in (video_traces[0].get("safe_summary") or "").lower()


# ── P0: orphaned transcript-derived artifacts with NO analysis object ─────────
# A missing / non-dict ``project_defense_analysis`` carries NO explicit
# clean/shareable status, yet transcript-derived Video chips + Project Defense /
# Video Evidence traces can still exist (a legacy or partially-written row). These
# must fail CLOSED: without a clean analysis object, none of their derived text may
# reach the public report.


def _orphaned_transcript_report() -> dict:
    """A report with NO analysis object but live transcript-derived chips/traces.

    ``project_defense_analysis`` is ``None`` (missing/orphaned), while the SSN-shaped
    marker still rides on a Video chip ``short_summary``, a ``Project Defense`` trace
    ``safe_summary`` / ``answer_excerpt``, and a ``Video Evidence`` trace summary.
    """
    return _minimal_report(
        claimed_skills=["Python"],
        project_defense_analysis=None,
        video_evidence_chips=[_video_chip_with_ssn()],
        evidence_traces=[
            {
                "trace_id": "project-defense",
                "source_type": "Project Defense",
                "source_title": "Project Defense",
                "skill_names": ["Python"],
                "qualitative_status": "Supporting evidence",
                "safe_summary": (
                    f"Transcript (11 words): my social security number is {_DEFENSE_SSN} and I built it."
                ),
                "safe_detail": f"Answer text: my SSN is {_DEFENSE_SSN}.",
                "answer_excerpt": f"my SSN is {_DEFENSE_SSN}",
                "question_text": "What did you build?",
                "location_type": "defense_overview",
                "public_url": None,
                "public_url_label": None,
                "is_publicly_openable": False,
            },
            _video_trace_with_ssn(),
        ],
    )


def test_public_report_missing_analysis_withholds_orphaned_chips_and_traces(
    client: TestClient, mem_store: dict, monkeypatch
) -> None:
    """Requirements #3/#4/#5: with the analysis object missing (``None``), orphaned
    transcript-derived video chips and Defense/Video traces must fail closed — the
    SSN-shaped value must not appear anywhere, video chips are dropped, and the
    neutral withheld wording appears instead."""
    response = _publish_and_get_with_report(
        client, mem_store, monkeypatch, _orphaned_transcript_report()
    )
    assert response.status_code == 200, response.text

    # No transcript-derived sensitive text anywhere in the serialized payload.
    assert _DEFENSE_SSN not in response.text
    assert "social security number" not in response.text.lower()
    assert "answer text: my ssn" not in response.text.lower()

    body = response.json()
    # No analysis object to project — the missing row stays absent, never fabricated.
    assert body["project_defense_analysis"] is None
    # Orphaned video chips (requirement #3) are withheld entirely.
    assert body["video_evidence_chips"] == []

    # The Project Defense trace (requirement #4) keeps its structure but its derived
    # free text is replaced with the neutral withheld wording.
    defense_traces = [t for t in body["evidence_traces"] if t.get("source_type") == "Project Defense"]
    assert defense_traces
    for trace in defense_traces:
        assert _DEFENSE_SSN not in json.dumps(trace)
        assert trace.get("answer_excerpt") is None
        assert trace.get("question_text") is None
        assert "hidden from this public report" in (trace.get("safe_summary") or "").lower()

    # The Video Evidence trace is likewise redacted (requirement #4).
    video_traces = [t for t in body["evidence_traces"] if t.get("source_type") == "Video Evidence"]
    assert video_traces
    for trace in video_traces:
        assert _DEFENSE_SSN not in json.dumps(trace)
        assert "hidden from the public report" in (trace.get("safe_summary") or "").lower()


def test_public_report_non_dict_analysis_still_withholds_orphaned_artifacts(
    client: TestClient, mem_store: dict, monkeypatch
) -> None:
    """A non-dict (malformed) analysis is treated exactly like a missing one:
    transcript-derived artifacts still fail closed."""
    report = _orphaned_transcript_report()
    report["project_defense_analysis"] = "not-a-dict"
    response = _publish_and_get_with_report(client, mem_store, monkeypatch, report)
    assert response.status_code == 200, response.text
    assert _DEFENSE_SSN not in response.text
    body = response.json()
    assert body["video_evidence_chips"] == []
    defense_traces = [t for t in body["evidence_traces"] if t.get("source_type") == "Project Defense"]
    assert defense_traces
    assert all(
        "hidden from this public report" in (t.get("safe_summary") or "").lower()
        for t in defense_traces
    )
