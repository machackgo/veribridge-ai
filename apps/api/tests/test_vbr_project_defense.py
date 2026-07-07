"""Tests for Project Defense (Phase 1 — individual project defense MVP).

Covers:
  - creating an individual project defense identity (repo_url required,
    derivable from an attached GitHub proof)
  - storing safe attached-proof summaries in vbr_projects.metadata
  - generating deterministic defense questions
  - saving manual/pasted answers as a transcript + segments (no video)
  - deterministic transcript analysis
  - ownership checks (404 for other users)

Skill Graph artifact sync is covered separately in
test_project_defense_artifact_sync.py.

All storage is in-memory (dict mode). No real network calls, no LLM calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app

USER_ID = "00000000-0000-0000-0000-000000000042"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000099"


DEFENSE_TRANSCRIPT = (
    "I built this project to solve the problem of tracking student skill evidence. "
    "My approach was to design a REST API backend using Python and FastAPI with a "
    "PostgreSQL database, and a React frontend for the dashboard. I implemented the "
    "authentication middleware myself and designed the database schema for storing "
    "evidence records. I also configured the API endpoints and built the component "
    "architecture for the React frontend. One limitation of the current version is "
    "that it does not yet support real-time updates, and in the future I would "
    "improve the caching layer for better performance."
)


VIDEO_TRANSCRIPT_SEGMENTS = [
    {"start_s": 0.0, "end_s": 8.0, "text": "Hi everyone, let me walk through my project."},
    {
        "start_s": 8.0,
        "end_s": 25.0,
        "text": "I built the backend risk-scoring API using Python and FastAPI with a PostgreSQL database.",
    },
    {
        "start_s": 25.0,
        "end_s": 45.0,
        "text": "For the frontend, I used React to build the dashboard components.",
    },
    {
        "start_s": 45.0,
        "end_s": 60.0,
        "text": "One limitation of the current version is that it lacks real-time updates.",
    },
]

VIDEO_TRANSCRIPT_FULL_TEXT = " ".join(seg["text"] for seg in VIDEO_TRANSCRIPT_SEGMENTS)


# A hostile transcript segment a speaker might accidentally read aloud while
# screen-sharing (storage paths, signed URLs, tokens, local file paths).
HOSTILE_VIDEO_TRANSCRIPT_SEGMENTS = [
    {
        "start_s": 8.0,
        "end_s": 25.0,
        "text": (
            "Python demo storage_path=vbr/sessions/abc123/recording.webm "
            "signed_url=https://storage.example.co/object/sign/videos/abc?token=eyJxyz "
            "access_token=shhh123 Authorization: Bearer eyJsecrettoken"
        ),
    },
]


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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_project_defense(client: TestClient, **overrides: object):
    payload = {
        "title": "Skill Evidence Tracker",
        "description": "A platform that tracks student skill evidence across proof sources.",
        "claimed_skills": ["Python", "React"],
        "student_role": "I built the backend API and the React dashboard.",
        "repo_url": "https://github.com/octocat/Hello-World",
        **overrides,
    }
    return client.post("/api/v1/student/vbr/project-defense", json=payload)


def _seed_github_proof(mem_store: dict, user_id: str = USER_ID, **overrides) -> str:
    proof_id = str(uuid4())
    now_iso = datetime.now(UTC).isoformat()
    row = {
        "id": proof_id,
        "user_id": user_id,
        "proof_session_id": None,
        "repo_url": "https://github.com/octocat/Hello-World",
        "repo_owner": "octocat",
        "repo_name": "Hello-World",
        "default_branch": "main",
        "visibility": "public",
        "status": "analyzed",
        "submitted_skill_claims": ["Python", "React"],
        "detected_skills": ["Python", "React"],
        "repo_metadata": {"secret_token": "should-never-leak"},
        "analysis_summary": "Repo demonstrates backend and frontend work.",
        "evidence_strength": "partial",
        "confidence_score": 72,
        "risk_flags": [],
        "missing_evidence": [],
        "public_safe_summary": "GitHub proof for octocat/Hello-World is partial evidence with 72/100 confidence.",
        "analysis_snapshot": {"raw_dump": "should-never-leak"},
        "last_analyzed_at": now_iso,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    row.update(overrides)
    mem_store.setdefault("github_proof_submissions", {})[proof_id] = row
    return proof_id


def _seed_document_evidence(mem_store: dict, user_id: str = USER_ID, **overrides) -> str:
    doc_id = str(uuid4())
    now_iso = datetime.now(UTC).isoformat()
    row = {
        "id": doc_id,
        "user_id": user_id,
        "proof_session_id": None,
        "source_type": "document",
        "status": "analyzed",
        "analysis_json": {"title": "Final Year Project Report"},
        "file_path": None,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    row.update(overrides)
    mem_store.setdefault("optional_evidence_submissions", {})[doc_id] = row
    return doc_id


def _seed_workflow_analysis(mem_store: dict, user_id: str = USER_ID, **overrides) -> str:
    proof_session_id = str(uuid4())
    now_iso = datetime.now(UTC).isoformat()
    row = {
        "id": str(uuid4()),
        "user_id": user_id,
        "proof_session_id": proof_session_id,
        "target_website": "http://demo.example.com",
        "evidence_strength_score": 75,
        "workflow_confidence": "high",
        "supported_skills": ["Machine Learning", "React"],
        "weakly_supported_skills": ["TypeScript"],
        "created_at": now_iso,
    }
    row.update(overrides)
    mem_store.setdefault("workflow_analysis_results", {})[row["id"]] = row
    return str(row["proof_session_id"])


def _seed_skill_pipeline(pipeline_db: dict, student_id: str = USER_ID, **overrides) -> str:
    pipeline_id = str(uuid4())
    now_iso = datetime.now(UTC).isoformat()
    row = {
        "id": pipeline_id,
        "student_id": student_id,
        "skill_name": "Python",
        "skill_category": "technical",
        "confidence_score": 70,
        "support_status": "partially_supported",
        "evidence_count": 1,
        "strongest_proof": {},
        "weakest_proof": {},
        "missing_evidence": [],
        "next_actions": [],
        "evidence_sources": [],
        "recruiter_summary": "",
        "student_summary": "",
        "visibility_status": "public",
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    row.update(overrides)
    pipeline_db.setdefault("skill_evidence_pipelines", {})[pipeline_id] = row
    return pipeline_id


def _seed_auto_video_transcript(
    mem_store: dict, session_id: str, segments: list[dict] = VIDEO_TRANSCRIPT_SEGMENTS
) -> str:
    """Seed an auto-generated (provider='openai') video transcript + segments.

    Mirrors the shape produced by ``vbr_transcription.transcribe_session``, so
    ``_get_auto_generated_transcript`` (and therefore evidence-chip building)
    picks it up.
    """
    transcript_id = str(uuid4())
    now_iso = datetime.now(UTC).isoformat()
    mem_store.setdefault("vbr_transcripts", {})[transcript_id] = {
        "id": transcript_id,
        "session_id": session_id,
        "provider": "openai",
        "language": "en",
        "full_text": " ".join(seg["text"] for seg in segments),
        "raw": {},
        "created_at": now_iso,
    }
    for i, seg in enumerate(segments):
        seg_id = f"seg-{i}"
        mem_store.setdefault("vbr_transcript_segments", {})[seg_id] = {
            "id": seg_id,
            "transcript_id": transcript_id,
            "question_id": None,
            "start_s": seg["start_s"],
            "end_s": seg["end_s"],
            "text": seg["text"],
            "created_at": now_iso,
        }
    return transcript_id


def _generate_questions(client: TestClient, project_id: str):
    return client.post(f"/api/v1/student/vbr/projects/{project_id}/generate-defense-questions")


def _submit_defense(client: TestClient, session_id: str, **body):
    return client.post(f"/api/v1/student/vbr/sessions/{session_id}/submit-defense", json=body)


# ── Evidence file-path sanitizer (must-fix: no absolute/local path leak) ──────

def test_safe_evidence_file_paths_rejects_absolute_and_local_paths() -> None:
    from app.services.vbr_project_defense import _safe_evidence_file_paths

    out = _safe_evidence_file_paths(
        {
            "evidence_files": [
                "/Users/alice/private/secret.py",
                "/etc/passwd",
                "C:\\Users\\alice\\private\\secret.py",
                "C:/Users/alice/private/secret.py",
                "file:///Users/alice/private/secret.py",
                "../secrets.py",
                "..\\secrets.py",
                # Safe repo-relative paths that MUST survive.
                "apps/api/main.py",
                "src/components/Button.tsx",
                "README.md",
            ]
        }
    )
    assert out == ["apps/api/main.py", "src/components/Button.tsx", "README.md"]
    # No absolute/local fragment may survive — not even lstrip("/")-ed.
    blob = "\n".join(out)
    for leaked in ("Users/alice", "etc/passwd", "secret.py", ".."):
        assert leaked not in blob


# ── Project identity creation ────────────────────────────────────────────────

def test_create_individual_project_with_repo_url(client: TestClient) -> None:
    response = _create_project_defense(client)
    assert response.status_code == 201, response.text
    body = response.json()

    project = body["project"]
    assert project["title"] == "Skill Evidence Tracker"
    assert project["repo_url"] == "https://github.com/octocat/Hello-World"
    assert project["repo_full_name"] == "octocat/Hello-World"
    assert project["status"] == "draft"

    metadata = body["metadata"]
    assert metadata["individual_project_only"] is True
    assert metadata["phase"] == "project_defense_mvp_v1"
    assert metadata["claimed_skills"] == ["Python", "React"]
    assert metadata["description"] == "A platform that tracks student skill evidence across proof sources."
    assert metadata["student_role"] == "I built the backend API and the React dashboard."
    assert metadata["attached_proofs"] == {}


def test_create_rejects_missing_repo_url_and_github_proof(client: TestClient) -> None:
    response = _create_project_defense(client, repo_url=None)
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "vbr_repo_url_required"


def test_create_derives_repo_url_from_attached_github_proof(client: TestClient, mem_store: dict) -> None:
    proof_id = _seed_github_proof(mem_store)

    response = _create_project_defense(
        client,
        repo_url=None,
        attached_proofs={"github_proof_id": proof_id},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["project"]["repo_url"] == "https://github.com/octocat/Hello-World"
    assert body["project"]["repo_full_name"] == "octocat/Hello-World"

    github_summary = body["metadata"]["attached_proofs"]["github_proof"]
    assert github_summary["github_proof_id"] == proof_id
    assert github_summary["repo_url"] == "https://github.com/octocat/Hello-World"
    assert github_summary["detected_skills"] == ["Python", "React"]

    # Raw analysis snapshot / repo metadata must never be copied into vbr_projects.metadata
    serialized = str(body["metadata"])
    assert "should-never-leak" not in serialized
    assert "analysis_snapshot" not in github_summary
    assert "repo_metadata" not in github_summary


def test_create_rejects_other_users_github_proof(client: TestClient, mem_store: dict) -> None:
    proof_id = _seed_github_proof(mem_store, user_id=OTHER_USER_ID)

    response = _create_project_defense(
        client,
        repo_url=None,
        attached_proofs={"github_proof_id": proof_id},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "vbr_github_proof_not_found"


def test_create_stores_safe_document_summary(client: TestClient, mem_store: dict) -> None:
    doc_id = _seed_document_evidence(mem_store)

    response = _create_project_defense(
        client,
        attached_proofs={"document_evidence_ids": [doc_id]},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    documents = body["metadata"]["attached_proofs"]["documents"]
    assert documents == [
        {
            "document_evidence_id": doc_id,
            "title": "Final Year Project Report",
            "source_type": "document",
            "status": "analyzed",
            # No structured evidence_objects → no analyzer-matched skills, so the
            # document is stored as project-level context (empty skills list).
            "skills": [],
        }
    ]


def test_create_stores_safe_document_matched_skills(client: TestClient, mem_store: dict) -> None:
    """When the analyzer matched skills in a document, only those safe skill
    names (never raw snippets) are persisted for per-skill report mapping."""
    doc_id = _seed_document_evidence(
        mem_store,
        evidence_objects=[
            {"skill_name": "Python", "confidence": "high", "snippet": "raw text should never persist"},
            {"skill_name": "Python", "confidence": "low"},  # duplicate is deduped
            {"skill_name": "React", "confidence": "medium"},
        ],
    )

    response = _create_project_defense(
        client,
        attached_proofs={"document_evidence_ids": [doc_id]},
    )
    assert response.status_code == 201, response.text
    documents = response.json()["metadata"]["attached_proofs"]["documents"]
    assert documents[0]["skills"] == ["Python", "React"]
    assert "raw text should never persist" not in response.text


def test_create_rejects_unknown_document_evidence(client: TestClient) -> None:
    response = _create_project_defense(
        client,
        attached_proofs={"document_evidence_ids": [str(uuid4())]},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "vbr_document_evidence_not_found"


def test_create_project_defense_not_found_for_other_user(client: TestClient) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = _generate_questions(client, project_id)
    assert response.status_code == 404


# ── Deterministic defense question generation ────────────────────────────────

def test_generate_defense_questions(client: TestClient) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]

    response = _generate_questions(client, project_id)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["project_id"] == project_id
    assert body["status"] == "questions_ready"
    assert body["session_id"]

    questions = body["questions"]
    assert len(questions) >= 6

    kinds = {q["target_ref"].get("kind") for q in questions}
    assert "architecture" in kinds
    assert "contribution" in kinds
    assert "challenge" in kinds
    assert "improvement" in kinds
    # Both claimed skills get a dedicated question
    skills_in_questions = {q["target_ref"].get("skill") for q in questions if q["target_ref"].get("skill")}
    assert skills_in_questions == {"Python", "React"}

    # Project status advances
    project_after = client.get(f"/api/v1/student/vbr/projects/{project_id}").json()
    assert project_after["status"] == "questions_ready"


def test_generate_defense_questions_references_attached_proofs(client: TestClient, mem_store: dict) -> None:
    github_proof_id = _seed_github_proof(mem_store)
    doc_id = _seed_document_evidence(mem_store)

    created = _create_project_defense(
        client,
        repo_url=None,
        attached_proofs={
            "github_proof_id": github_proof_id,
            "document_evidence_ids": [doc_id],
        },
    ).json()
    project_id = created["project"]["id"]

    response = _generate_questions(client, project_id)
    assert response.status_code == 200, response.text
    questions = response.json()["questions"]

    kinds = {q["target_ref"].get("kind") for q in questions}
    assert "skill_repo_link" in kinds  # GitHub proof attached → repo-linked skill questions
    assert "document_link" in kinds    # Document proof attached

    repo_question = next(q for q in questions if q["target_ref"].get("kind") == "skill_repo_link")
    assert "https://github.com/octocat/Hello-World" in repo_question["question_text"]


# ── Attached proof ownership gaps (website proof / skill pipelines) ─────────

def test_create_rejects_unknown_website_proof_session_id(client: TestClient) -> None:
    response = _create_project_defense(
        client,
        attached_proofs={"website_proof_session_ids": [str(uuid4())]},
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "vbr_website_proof_not_found"


def test_create_rejects_other_users_website_proof(client: TestClient, mem_store: dict) -> None:
    proof_session_id = _seed_workflow_analysis(mem_store, user_id=OTHER_USER_ID)

    response = _create_project_defense(
        client,
        attached_proofs={"website_proof_session_ids": [proof_session_id]},
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "vbr_website_proof_not_found"


def test_create_stores_safe_website_proof_summary(client: TestClient, mem_store: dict) -> None:
    proof_session_id = _seed_workflow_analysis(mem_store)

    response = _create_project_defense(
        client,
        attached_proofs={"website_proof_session_ids": [proof_session_id]},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    website_proofs = body["metadata"]["attached_proofs"]["website_proofs"]
    assert website_proofs == [
        {
            "proof_session_id": proof_session_id,
            "target_website": "http://demo.example.com",
            "evidence_strength_score": 75,
            "workflow_confidence": "high",
            "supported_skills": ["Machine Learning", "React"],
            "created_at": website_proofs[0]["created_at"],
        }
    ]

    # No raw artifact data, screenshots, storage paths, or tokens leak into metadata.
    serialized = str(body["metadata"])
    assert "weakly_supported_skills" not in serialized
    assert "storage_path" not in serialized
    assert "signed_url" not in serialized


def test_generate_defense_questions_references_attached_website_proof(client: TestClient, mem_store: dict) -> None:
    proof_session_id = _seed_workflow_analysis(mem_store)

    created = _create_project_defense(
        client,
        attached_proofs={"website_proof_session_ids": [proof_session_id]},
    ).json()
    project_id = created["project"]["id"]

    response = _generate_questions(client, project_id)
    assert response.status_code == 200, response.text
    questions = response.json()["questions"]

    kinds = {q["target_ref"].get("kind") for q in questions}
    assert "live_demo_link" in kinds


def test_create_rejects_skill_pipeline_owned_by_other_user(client: TestClient, pipeline_db: dict) -> None:
    pipeline_id = _seed_skill_pipeline(pipeline_db, student_id=OTHER_USER_ID)

    response = _create_project_defense(
        client,
        attached_proofs={"skill_pipeline_ids": [pipeline_id]},
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "vbr_skill_pipeline_not_found"


def test_create_rejects_unknown_skill_pipeline_id(client: TestClient) -> None:
    response = _create_project_defense(
        client,
        attached_proofs={"skill_pipeline_ids": [str(uuid4())]},
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "vbr_skill_pipeline_not_found"


def test_create_stores_owned_skill_pipeline_ids(client: TestClient, pipeline_db: dict) -> None:
    pipeline_id = _seed_skill_pipeline(pipeline_db, student_id=USER_ID)

    response = _create_project_defense(
        client,
        attached_proofs={"skill_pipeline_ids": [pipeline_id]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["metadata"]["attached_proofs"]["skill_pipeline_ids"] == [pipeline_id]


# ── Manual transcript + deterministic analysis ───────────────────────────────

def test_submit_defense_rejects_empty_answers(client: TestClient) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]

    response = _submit_defense(client, session_id)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_no_answers_provided"


def test_submit_defense_with_combined_text_stores_transcript_and_analyzes(client: TestClient, mem_store: dict) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]

    response = _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["project_id"] == project_id
    assert body["session_id"] == session_id
    assert body["segment_count"] == 1
    assert body["transcript_id"]

    # No video/keyframes required — manual transcript only.
    transcripts = mem_store["vbr_transcripts"]
    assert len(transcripts) == 1
    transcript_row = next(iter(transcripts.values()))
    assert transcript_row["full_text"] == DEFENSE_TRANSCRIPT
    assert transcript_row["session_id"] == session_id

    segments = mem_store["vbr_transcript_segments"]
    assert len(segments) == 1

    analysis = body["analysis"]
    assert analysis["overall_defense_score"] >= 60
    assert "Python" in analysis["skills_mentioned"]
    assert "React" in analysis["skills_mentioned"]
    assert analysis["privacy_scan_status"] == "clean"

    # Analysis is stored on the session telemetry for later sync.
    session_row = mem_store["vbr_verification_sessions"][session_id]
    assert session_row["telemetry"]["project_defense_analysis"]["overall_defense_score"] == analysis["overall_defense_score"]


def test_submit_defense_with_per_question_answers_marks_questions_answered(client: TestClient, mem_store: dict) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    gen = _generate_questions(client, project_id).json()
    session_id = gen["session_id"]
    questions = gen["questions"]

    answers = [
        {"question_id": q["id"], "answer_text": f"Answer for: {q['question_text']}"}
        for q in questions[:2]
    ]

    response = _submit_defense(client, session_id, answers=answers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answered_question_count"] == 2
    assert body["segment_count"] == 2

    answered_ids = {q["id"] for q in questions[:2]}
    for q in mem_store["vbr_session_questions"].values():
        if q["id"] in answered_ids:
            assert q["answered"] is True
        else:
            assert q["answered"] is False


def test_submit_defense_marks_project_metadata_analyzed(client: TestClient) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]

    assert created["project"]["metadata"].get("project_defense_status") is None

    response = _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)
    assert response.status_code == 200, response.text

    project_after = client.get(f"/api/v1/student/vbr/projects/{project_id}").json()
    assert project_after["metadata"]["project_defense_status"] == "analyzed"
    # Phase 1 identity is preserved alongside the new status flag.
    assert project_after["metadata"]["phase"] == "project_defense_mvp_v1"


def test_submit_defense_falls_back_to_auto_generated_transcript(client: TestClient, mem_store: dict) -> None:
    """If no manual answers/combined_text are provided, but a recording was already
    transcribed (Transcript Phase 1, provider in {openai, local_whisper}), use that
    transcript as the Project Defense explanation source.
    """
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]

    transcript_id = str(uuid4())
    mem_store.setdefault("vbr_transcripts", {})[transcript_id] = {
        "id": transcript_id,
        "session_id": session_id,
        "provider": "openai",
        "language": "en",
        "full_text": DEFENSE_TRANSCRIPT,
        "raw": {},
        "created_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("vbr_transcript_segments", {})["seg-1"] = {
        "id": "seg-1",
        "transcript_id": transcript_id,
        "question_id": None,
        "start_s": 0.0,
        "end_s": 8.0,
        "text": "Candidate introduced the project and repository.",
        "created_at": datetime.now(UTC).isoformat(),
    }

    response = _submit_defense(client, session_id)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["project_id"] == project_id
    assert body["session_id"] == session_id
    assert body["transcript_id"] == transcript_id
    assert body["segment_count"] == 1

    # No new transcript row created — the auto-generated one was reused.
    assert len(mem_store["vbr_transcripts"]) == 1

    analysis = body["analysis"]
    assert "Python" in analysis["skills_mentioned"]
    assert "React" in analysis["skills_mentioned"]


def test_submit_defense_ignores_manual_provider_transcript_for_fallback(client: TestClient, mem_store: dict) -> None:
    """A manually-pasted transcript (provider == 'manual') from a *different*
    submission must not be picked up as an auto-generated fallback source.
    """
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]

    transcript_id = str(uuid4())
    mem_store.setdefault("vbr_transcripts", {})[transcript_id] = {
        "id": transcript_id,
        "session_id": session_id,
        "provider": "manual",
        "language": "en",
        "full_text": DEFENSE_TRANSCRIPT,
        "raw": {},
        "created_at": datetime.now(UTC).isoformat(),
    }

    response = _submit_defense(client, session_id)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_no_answers_provided"


def test_submit_defense_not_found_for_other_user(client: TestClient) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)
    assert response.status_code == 404


# ── Timestamped video evidence chips (Phase 1.5) ─────────────────────────────

def test_submit_defense_builds_video_evidence_chips_from_transcript_segments(
    client: TestClient, mem_store: dict
) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]
    _seed_auto_video_transcript(mem_store, session_id)

    response = _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)
    assert response.status_code == 200, response.text
    body = response.json()

    chips = body["video_evidence_chips"]
    assert len(chips) == 2

    labels = {chip["label"] for chip in chips}
    assert labels == {"Video 00:08", "Video 00:25"}

    related_skills = {chip["related_skill"] for chip in chips}
    assert related_skills == {"Python", "React"}

    for chip in chips:
        assert chip["source"] == "project_defense_video"
        assert chip["source_type"] == "video_transcript"
        assert chip["timestamp_start_s"] >= 0
        assert chip["timestamp_end_s"] >= chip["timestamp_start_s"]

    # Stored on session telemetry (no migration) for the recording page / Skill Graph sync.
    session_row = mem_store["vbr_verification_sessions"][session_id]
    assert session_row["telemetry"]["video_evidence_chips"] == chips


def test_submit_defense_without_video_transcript_produces_no_chips_no_error(
    client: TestClient,
) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]

    response = _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)
    assert response.status_code == 200, response.text
    assert response.json()["video_evidence_chips"] == []


def test_video_evidence_chips_are_short_safe_snippets_not_full_transcript(
    client: TestClient, mem_store: dict
) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]
    _seed_auto_video_transcript(mem_store, session_id)

    response = _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)
    assert response.status_code == 200, response.text
    body = response.json()
    chips = body["video_evidence_chips"]
    assert chips

    raw = response.text
    for chip in chips:
        assert len(chip["short_summary"]) <= 160
        assert chip["short_summary"] != VIDEO_TRANSCRIPT_FULL_TEXT

    assert VIDEO_TRANSCRIPT_FULL_TEXT not in raw
    for unsafe in ("storage_path", "signed_url", "access_token", "vbr/sessions", "full_text"):
        assert unsafe not in raw


def test_video_evidence_chips_sanitize_unsafe_transcript_segment_text(
    client: TestClient, mem_store: dict
) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]
    _seed_auto_video_transcript(mem_store, session_id, segments=HOSTILE_VIDEO_TRANSCRIPT_SEGMENTS)

    response = _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)
    assert response.status_code == 200, response.text
    body = response.json()
    chips = body["video_evidence_chips"]
    assert chips
    chip = chips[0]
    assert chip["related_skill"] == "Python"

    unsafe_substrings = (
        "storage_path",
        "vbr/sessions",
        "signed_url",
        "upload_url",
        "access_token",
        "token=",
        "Bearer",
        "eyJxyz",
        "eyJsecrettoken",
        ".webm",
    )

    submit_raw = response.text
    for unsafe in unsafe_substrings:
        assert unsafe not in submit_raw, f"{unsafe!r} leaked into submit-defense response: {submit_raw}"

    assert "Python" in chip["short_summary"]
    assert "[redacted]" in chip["short_summary"]

    session_row = mem_store["vbr_verification_sessions"][session_id]
    telemetry_raw = str(session_row["telemetry"]["video_evidence_chips"])
    for unsafe in unsafe_substrings:
        assert unsafe not in telemetry_raw, f"{unsafe!r} leaked into session telemetry: {telemetry_raw}"

    session_response = client.get(f"/api/v1/student/vbr/sessions/{session_id}")
    assert session_response.status_code == 200, session_response.text
    session_raw = session_response.text
    for unsafe in unsafe_substrings:
        assert unsafe not in session_raw, f"{unsafe!r} leaked into session response: {session_raw}"


def test_video_evidence_chips_rerun_is_idempotent(client: TestClient, mem_store: dict) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]
    _seed_auto_video_transcript(mem_store, session_id)

    first = _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT).json()
    second = _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT).json()

    assert first["video_evidence_chips"] == second["video_evidence_chips"]

    session_row = mem_store["vbr_verification_sessions"][session_id]
    assert session_row["telemetry"]["video_evidence_chips"] == first["video_evidence_chips"]


def test_vbr_session_response_includes_video_evidence_chips(
    client: TestClient, mem_store: dict
) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]
    _seed_auto_video_transcript(mem_store, session_id)
    _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)

    session_response = client.get(f"/api/v1/student/vbr/sessions/{session_id}")
    assert session_response.status_code == 200, session_response.text
    chips = session_response.json()["video_evidence_chips"]
    assert len(chips) == 2
    assert {chip["related_skill"] for chip in chips} == {"Python", "React"}


def test_vbr_session_response_has_no_chips_before_analysis(
    client: TestClient, mem_store: dict
) -> None:
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]
    _seed_auto_video_transcript(mem_store, session_id)

    session_response = client.get(f"/api/v1/student/vbr/sessions/{session_id}")
    assert session_response.status_code == 200, session_response.text
    assert session_response.json()["video_evidence_chips"] == []


def test_build_evidence_chips_maps_to_question_id_when_no_claimed_skill_match() -> None:
    from app.services.project_defense_evidence_chips import build_evidence_chips

    segments = [
        {"start_s": 0.0, "end_s": 8.0, "text": "Let's talk about how I deployed this using Docker."},
        {"start_s": 8.0, "end_s": 20.0, "text": "This part is unrelated to any specific skill."},
    ]
    questions = [
        {"id": "q-docker", "target_ref": {"kind": "skill_link", "skill": "Docker"}},
    ]

    chips = build_evidence_chips(segments, claimed_skills=["Python"], questions=questions)

    assert len(chips) == 1
    assert chips[0]["label"] == "Video 00:00"
    assert chips[0]["related_skill"] == "Docker"
    assert chips[0]["question_id"] == "q-docker"


def test_build_evidence_chips_with_no_segments_returns_empty_list() -> None:
    from app.services.project_defense_evidence_chips import build_evidence_chips

    assert build_evidence_chips([], claimed_skills=["Python"], questions=[]) == []


# ── Evidence chip summary sanitization (privacy fix) ─────────────────────────

def test_sanitize_transcript_text_redacts_unsafe_patterns_but_keeps_useful_words() -> None:
    from app.services.project_defense_evidence_chips import _sanitize_transcript_text

    text = (
        "Python demo storage_path=vbr/sessions/abc123/recording.webm "
        "signed_url=https://storage.example.co/object/sign/videos/abc?token=eyJxyz "
        "upload_url=https://api.example.com/upload?token=def456 "
        "access_token=ghijk789 SUPABASE_SERVICE_ROLE_KEY=eyJzdWIiOiJzZXJ2aWNl "
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig "
        "service_role anon_key=eyJanon123 "
        "see /Users/student/Videos/demo.mp4 and C:\\Users\\student\\demo.mp4 "
        "also vbr/sessions/xyz/clip.mp4 and http://example.com/x?y=1 "
        "for the FastAPI backend risk scoring and geospatial API."
    )

    sanitized = _sanitize_transcript_text(text)

    for unsafe in (
        "storage_path",
        "signed_url",
        "upload_url",
        "access_token",
        "token=",
        "Bearer",
        "service_role",
        "anon_key",
        "SUPABASE_SERVICE_ROLE_KEY",
        "vbr/sessions",
        "/Users/",
        "C:\\Users",
        ".mp4",
        ".webm",
        "http://",
        "https://",
        "eyJ",
    ):
        assert unsafe not in sanitized, f"{unsafe!r} leaked into sanitized text: {sanitized!r}"

    for safe in ("Python", "demo", "FastAPI", "backend", "risk scoring", "geospatial", "API"):
        assert safe in sanitized, f"{safe!r} missing from sanitized text: {sanitized!r}"

    assert "[redacted]" in sanitized


def test_build_evidence_chips_sanitizes_unsafe_transcript_segment_text() -> None:
    from app.services.project_defense_evidence_chips import build_evidence_chips

    segments = [
        {
            "start_s": 0.0,
            "end_s": 8.0,
            "text": (
                "Python demo storage_path=vbr/sessions/abc "
                "signed_url=https://storage.example/x?token=abc"
            ),
        },
    ]

    chips = build_evidence_chips(segments, claimed_skills=["Python"], questions=[])

    assert len(chips) == 1
    summary = chips[0]["short_summary"]
    assert summary == "Python demo [redacted] [redacted]"
    for unsafe in ("storage_path", "vbr/sessions", "signed_url", "token=", "https://"):
        assert unsafe not in summary


# ── Project Defense inspection cards (recruiter inspection layer) ─────────────
#
# The inspection builder is a pure projection over the answer-evidence objects,
# adding the safe clip locator, "what this demonstrates" / corroboration wording,
# and the ``public_safe`` gate. These tests exercise the exact-mapping and
# safe-locator rules directly on the builder.


def _ml_answer_objects():
    """One ML-mapped answered question + one untargeted generic answer."""
    from app.services.defense_answer_evidence_service import (
        build_defense_answer_evidence,
    )

    return build_defense_answer_evidence(
        questions=[
            {
                "id": "q-ml",
                "question_text": "How does your model make predictions?",
                "target_ref": {"kind": "skill_link", "skill": "Machine Learning"},
                "sort_order": 0,
            }
        ],
        segments=[
            {
                "question_id": "q-ml",
                "text": (
                    "I trained a regression model on the housing dataset and use it "
                    "for inference; the prediction endpoint returns the model output "
                    "after feature validation."
                ),
            },
            # Untargeted transcript moment (no question_id) — becomes at most one
            # generic project-level object that maps NO skill.
            {"text": "Overall it was a really fun project and I learned a lot about deployment."},
        ],
        claimed_skills=["Machine Learning"],
        attached_proofs={},
        privacy_scan_status="clean",
    )


def test_inspection_untargeted_transcript_never_maps_to_a_skill() -> None:
    from app.services.project_defense_inspection_service import (
        build_project_defense_inspection_cards,
    )

    answers = _ml_answer_objects()
    cards = build_project_defense_inspection_cards(
        answer_evidence=answers, video_chips=[], project_title="Boston"
    )
    # The ML-targeted answer maps ML; the untargeted moment maps no skill.
    mapped = [c["mapped_skill"] for c in cards]
    assert "Machine Learning" in mapped
    generic = [c for c in cards if c["mapped_skill"] is None]
    assert generic, "expected one generic, un-skilled project-context card"
    # A generic answer is framed as 'not assessed', never as skill proof.
    assert "not assessed" in generic[0]["what_this_demonstrates"].lower()


def test_inspection_skill_scoped_view_drops_untargeted_and_other_skills() -> None:
    from app.services.project_defense_inspection_service import (
        build_project_defense_inspection_cards,
    )

    answers = _ml_answer_objects()
    # Scope to Machine Learning: only the ML-mapped Q/A survives.
    ml_only = build_project_defense_inspection_cards(
        answer_evidence=answers, video_chips=[], only_skill="Machine Learning"
    )
    assert [c["mapped_skill"] for c in ml_only] == ["Machine Learning"]

    # Scope to an UNRELATED skill: nothing maps (no generic transcript leaks in).
    frontend_only = build_project_defense_inspection_cards(
        answer_evidence=answers, video_chips=[], only_skill="Frontend Development"
    )
    assert frontend_only == []


def test_inspection_clip_locator_is_safe_and_carries_no_content() -> None:
    from app.services.project_defense_inspection_service import (
        build_project_defense_inspection_cards,
    )

    answers = _ml_answer_objects()
    chips = [
        {
            "label": "Video 03:12",
            "timestamp_start_s": 192.0,
            "timestamp_end_s": 205.0,
            # The chip summary is answer-derived and must NEVER reach the card.
            "short_summary": "secret spoken sentence about my model",
            "related_skill": "Machine Learning",
            "question_id": "q-ml",
        }
    ]
    cards = build_project_defense_inspection_cards(
        answer_evidence=answers, video_chips=chips, only_skill="Machine Learning"
    )
    card = cards[0]
    assert card["clip_available"] is True
    assert card["timestamp_label"] == "Video 03:12"
    assert card["clip_start_seconds"] == 192.0
    assert card["clip_end_seconds"] == 205.0
    # The clip is a locator only — the chip's spoken summary is never copied in.
    assert "secret spoken sentence" not in str(card)


def test_inspection_labels_defense_as_explanation_not_implementation() -> None:
    from app.services.project_defense_inspection_service import (
        PROJECT_DEFENSE_INSPECTION_LIMITATION,
        build_project_defense_inspection_cards,
    )

    answers = _ml_answer_objects()
    cards = build_project_defense_inspection_cards(
        answer_evidence=answers, video_chips=[], only_skill="Machine Learning"
    )
    card = cards[0]
    # Conservative framing: explanation / understanding, never verified impl.
    demo = card["what_this_demonstrates"].lower()
    assert "explained" in demo
    for banned in ("verified implementation", "proves authorship", "guarantee"):
        assert banned not in demo
    # A GitHub-less skill answer stays honest about the missing artifact evidence.
    assert card["limitation"]
    # No numeric confidence anywhere on the card.
    assert "confidence" not in str(card).lower()


# ── Owner playable evidence: safe transcript excerpt + recording playback ─────


def test_inspection_owner_view_includes_bounded_transcript_excerpt() -> None:
    from app.services.project_defense_inspection_service import (
        TRANSCRIPT_EXCERPT_NOTE,
        build_project_defense_inspection_cards,
    )

    answers = _ml_answer_objects()
    excerpts = {
        "q-ml": {
            "safe_transcript_excerpt": "I trained a regression model and validated features before inference.",
            "transcript_excerpt_start_label": "03:10",
            "transcript_excerpt_end_label": "03:25",
        }
    }
    cards = build_project_defense_inspection_cards(
        answer_evidence=answers,
        video_chips=[],
        only_skill="Machine Learning",
        answer_excerpts=excerpts,
        is_owner_view=True,
    )
    card = cards[0]
    assert card["transcript_excerpt_available"] is True
    assert "regression model" in card["safe_transcript_excerpt"]
    # Bounded — never a full transcript dump.
    assert len(card["safe_transcript_excerpt"]) <= 800
    assert card["transcript_excerpt_start_label"] == "03:10"
    assert card["transcript_excerpt_end_label"] == "03:25"
    assert card["transcript_access_note"] == TRANSCRIPT_EXCERPT_NOTE
    assert card["is_private_owner_view"] is True
    # The raw segments array is never carried on the card.
    assert "transcript_segments" not in card


def test_inspection_transcript_excerpt_only_in_owner_view() -> None:
    from app.services.project_defense_inspection_service import (
        TRANSCRIPT_NONE_NOTE,
        build_project_defense_inspection_cards,
    )

    answers = _ml_answer_objects()
    excerpts = {"q-ml": {"safe_transcript_excerpt": "secret answer text"}}
    # Not owner view (e.g. the plain builder default) → excerpt is NOT attached.
    cards = build_project_defense_inspection_cards(
        answer_evidence=answers,
        video_chips=[],
        only_skill="Machine Learning",
        answer_excerpts=excerpts,
        is_owner_view=False,
    )
    card = cards[0]
    assert card["transcript_excerpt_available"] is False
    assert card["safe_transcript_excerpt"] is None
    assert card["transcript_access_note"] == TRANSCRIPT_NONE_NOTE
    assert "secret answer text" not in str(card)


def test_inspection_recording_playback_is_owner_only() -> None:
    from app.services.project_defense_inspection_service import (
        RECORDING_PLAYABLE_NOTE,
        build_project_defense_inspection_cards,
    )

    answers = _ml_answer_objects()
    chips = [
        {
            "label": "Video 03:12",
            "timestamp_start_s": 192.0,
            "timestamp_end_s": 205.0,
            "related_skill": "Machine Learning",
            "question_id": "q-ml",
        }
    ]
    recording = {"available": True, "playback_url": "https://signed.example/full.webm?token=xyz"}

    owner = build_project_defense_inspection_cards(
        answer_evidence=answers,
        video_chips=chips,
        only_skill="Machine Learning",
        recording=recording,
        is_owner_view=True,
    )[0]
    assert owner["video_available"] is True
    assert owner["video_playback_url"] == "https://signed.example/full.webm?token=xyz"
    # The clip playback URL is the same signed URL plus a #t media fragment.
    assert owner["clip_playback_url"] == "https://signed.example/full.webm?token=xyz#t=192.0,205.0"
    assert owner["recording_access_note"] == RECORDING_PLAYABLE_NOTE

    # Same recording, NOT owner view → no playback URL is attached.
    non_owner = build_project_defense_inspection_cards(
        answer_evidence=answers,
        video_chips=chips,
        only_skill="Machine Learning",
        recording=recording,
        is_owner_view=False,
    )[0]
    assert non_owner["video_playback_url"] is None
    assert non_owner["clip_playback_url"] is None
    assert non_owner["video_available"] is False


def test_inspection_recording_exists_but_no_playback_url() -> None:
    from app.services.project_defense_inspection_service import (
        RECORDING_EXISTS_NO_PLAYBACK_NOTE,
        build_project_defense_inspection_cards,
    )

    answers = _ml_answer_objects()
    # Recording exists (available) but no signed URL could be minted.
    recording = {"available": True, "playback_url": None}
    card = build_project_defense_inspection_cards(
        answer_evidence=answers,
        video_chips=[],
        only_skill="Machine Learning",
        recording=recording,
        is_owner_view=True,
    )[0]
    assert card["video_available"] is True
    assert card["video_playback_url"] is None
    assert card["recording_access_note"] == RECORDING_EXISTS_NO_PLAYBACK_NOTE


def test_build_safe_answer_excerpts_is_bounded_and_sanitized() -> None:
    """The excerpt helper concatenates a question's segments into ONE bounded,
    sanitized snippet with safe mm:ss labels — never the raw segment array."""
    from app.services.defense_evidence_access_service import (
        TRANSCRIPT_EXCERPT_MAX_CHARS,
        build_safe_answer_excerpts,
    )

    long_text = "I explained the model in detail. " * 60  # > cap
    db = {
        "vbr_transcripts": {"t1": {"id": "t1", "session_id": "sess-1"}},
        "vbr_transcript_segments": {
            "seg1": {
                "transcript_id": "t1",
                "question_id": "q-ml",
                "text": long_text + " see storage_path=vbr/sessions/abc token=secret123",
                "start_s": 190.0,
                "end_s": 210.0,
            },
        },
    }
    out = build_safe_answer_excerpts(db, "sess-1")
    assert "q-ml" in out
    excerpt = out["q-ml"]["safe_transcript_excerpt"]
    assert len(excerpt) <= TRANSCRIPT_EXCERPT_MAX_CHARS + 1  # +1 for the ellipsis
    # Storage path / token fragments are redacted out of the excerpt.
    assert "storage_path=vbr/sessions/abc" not in excerpt
    assert "secret123" not in excerpt
    assert out["q-ml"]["transcript_excerpt_start_label"] == "03:10"
    assert out["q-ml"]["transcript_excerpt_end_label"] == "03:30"
