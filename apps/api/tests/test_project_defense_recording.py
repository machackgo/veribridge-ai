"""Tests for recorded individual Project Defense sessions (Phase 2A).

Project Defense sessions are rows in the same ``vbr_verification_sessions``
table used by the general VBR walkthrough flow, created via
``/projects/{project_id}/generate-defense-questions``. The browser-recording
lifecycle (consent/start/chunk-upload-url/chunk/telemetry/finalize) is the
same generic, ownership-checked session machinery covered in
test_vbr_sessions.py — these tests confirm it behaves the same way for
Project Defense sessions specifically, and that recording does not affect
the manual transcript fallback or leak storage details into the Skill Graph.

All storage is in-memory (dict mode). No real network calls, no LLM calls.
"""

from __future__ import annotations

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
    "evidence records."
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


def _setup_defense_session(client: TestClient) -> tuple[str, str]:
    """Create a Project Defense project and generate its session/questions.

    Returns ``(project_id, session_id)``.
    """
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]

    response = client.post(f"/api/v1/student/vbr/projects/{project_id}/generate-defense-questions")
    assert response.status_code == 200, response.text
    return project_id, response.json()["session_id"]


def _grant_consent(client: TestClient, session_id: str) -> dict:
    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/consent", json={})
    assert response.status_code == 201, response.text
    return response.json()


def _start_session(client: TestClient, session_id: str) -> dict:
    _grant_consent(client, session_id)
    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/start")
    assert response.status_code == 200, response.text
    return response.json()


def _chunk_payload(session_id: str, chunk_index: int = 0, **overrides: object) -> dict:
    payload = {
        "chunk_index": chunk_index,
        "storage_path": f"vbr/sessions/{session_id}/chunks/{chunk_index:03d}.webm",
        "bytes": 1024,
        "sha256": "a" * 64,
        **overrides,
    }
    return payload


def _upload_url_payload(chunk_index: int = 0, **overrides: object) -> dict:
    payload = {
        "chunk_index": chunk_index,
        "bytes": 1024,
        "sha256": "a" * 64,
        **overrides,
    }
    return payload


def _submit_defense(client: TestClient, session_id: str, **body):
    return client.post(f"/api/v1/student/vbr/sessions/{session_id}/submit-defense", json=body)


def _sync(client: TestClient, session_id: str):
    return client.post(f"/api/v1/student/skill-pipelines/from-project-defense/{session_id}")


# ── Recording lifecycle ──────────────────────────────────────────────────────

def test_project_defense_session_recording_lifecycle_happy_path(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_defense_session(client)

    _start_session(client, session_id)

    upload_target = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk-upload-url",
        json=_upload_url_payload(chunk_index=0),
    )
    assert upload_target.status_code == 200, upload_target.text
    assert upload_target.json()["storage_path"] == f"vbr/sessions/{session_id}/chunks/000.webm"

    chunk_response = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json=_chunk_payload(session_id, chunk_index=0),
    )
    assert chunk_response.status_code == 200, chunk_response.text

    finalize_response = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/finalize",
        json={"duration_s": 90},
    )
    assert finalize_response.status_code == 200, finalize_response.text
    body = finalize_response.json()
    assert body["status"] == "uploaded"
    assert body["chunk_count"] == 1
    assert body["duration_s"] == 90


def test_consent_required_before_start_for_project_defense_session(client: TestClient) -> None:
    _project_id, session_id = _setup_defense_session(client)

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/start")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_recording_consent_required"


def test_start_only_works_for_created_project_defense_session(client: TestClient) -> None:
    _project_id, session_id = _setup_defense_session(client)

    first = _start_session(client, session_id)
    assert first["status"] == "recording"

    second = client.post(f"/api/v1/student/vbr/sessions/{session_id}/start")
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "vbr_session_not_startable"


def test_chunk_upload_url_only_works_while_recording_for_project_defense_session(client: TestClient) -> None:
    _project_id, session_id = _setup_defense_session(client)

    not_recording = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk-upload-url",
        json=_upload_url_payload(),
    )
    assert not_recording.status_code == 409
    assert not_recording.json()["detail"]["code"] == "vbr_session_not_recording"

    _start_session(client, session_id)

    recording = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk-upload-url",
        json=_upload_url_payload(),
    )
    assert recording.status_code == 200, recording.text


def test_chunk_metadata_rejects_invalid_sha_oversized_and_wrong_path_for_project_defense_session(
    client: TestClient,
) -> None:
    _project_id, session_id = _setup_defense_session(client)
    _start_session(client, session_id)

    bad_sha = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json=_chunk_payload(session_id, sha256="not-a-real-sha"),
    )
    assert bad_sha.status_code == 400
    assert bad_sha.json()["detail"]["code"] == "vbr_invalid_chunk_sha256"

    oversized = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json=_chunk_payload(session_id, bytes=25 * 1024 * 1024 + 1),
    )
    assert oversized.status_code == 400
    assert oversized.json()["detail"]["code"] == "vbr_invalid_chunk_size"

    wrong_path = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json=_chunk_payload(session_id, chunk_index=0, storage_path=f"vbr/sessions/{session_id}/chunks/099.webm"),
    )
    assert wrong_path.status_code == 400
    assert wrong_path.json()["detail"]["code"] == "vbr_invalid_chunk_storage_path"


def test_finalize_rejects_zero_chunks_for_project_defense_session(client: TestClient) -> None:
    _project_id, session_id = _setup_defense_session(client)
    _start_session(client, session_id)

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/finalize", json={})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_session_no_chunks"


def test_finalize_with_chunks_moves_project_defense_session_to_uploaded(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_defense_session(client)
    _start_session(client, session_id)

    chunk_response = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json=_chunk_payload(session_id, chunk_index=0),
    )
    assert chunk_response.status_code == 200, chunk_response.text

    finalize_response = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/finalize",
        json={"duration_s": 60},
    )
    assert finalize_response.status_code == 200, finalize_response.text
    assert finalize_response.json()["status"] == "uploaded"
    assert mem_store["vbr_verification_sessions"][session_id]["status"] == "uploaded"


def test_other_user_cannot_record_project_defense_session(client: TestClient) -> None:
    _project_id, session_id = _setup_defense_session(client)
    _start_session(client, session_id)

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID

    consent = client.post(f"/api/v1/student/vbr/sessions/{session_id}/consent", json={})
    assert consent.status_code == 404

    upload_url = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk-upload-url",
        json=_upload_url_payload(),
    )
    assert upload_url.status_code == 404

    chunk = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json=_chunk_payload(session_id, chunk_index=0),
    )
    assert chunk.status_code == 404

    finalize = client.post(f"/api/v1/student/vbr/sessions/{session_id}/finalize", json={})
    assert finalize.status_code == 404


# ── Recording does not expose storage details ───────────────────────────────

def test_project_defense_session_detail_does_not_expose_storage_paths_or_signed_urls(
    client: TestClient,
) -> None:
    _project_id, session_id = _setup_defense_session(client)
    _start_session(client, session_id)

    client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json=_chunk_payload(session_id, chunk_index=0),
    )

    response = client.get(f"/api/v1/student/vbr/sessions/{session_id}")
    assert response.status_code == 200, response.text
    body = response.json()

    serialized = str(body)
    assert "storage_path" not in serialized
    assert "signed_url" not in serialized
    assert "signedUrl" not in serialized
    assert "upload_url" not in serialized


# ── Manual transcript fallback after recording ───────────────────────────────

def test_manual_transcript_fallback_still_works_after_recording_finalize(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_defense_session(client)
    _start_session(client, session_id)

    client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json=_chunk_payload(session_id, chunk_index=0),
    )
    finalize_response = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/finalize",
        json={"duration_s": 60},
    )
    assert finalize_response.status_code == 200, finalize_response.text
    assert finalize_response.json()["status"] == "uploaded"

    submit_response = _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)
    assert submit_response.status_code == 200, submit_response.text
    body = submit_response.json()
    assert body["session_id"] == session_id
    assert body["segment_count"] == 1
    assert body["analysis"]["overall_defense_score"] >= 0

    transcripts = mem_store["vbr_transcripts"]
    assert len(transcripts) == 1
    assert next(iter(transcripts.values()))["full_text"] == DEFENSE_TRANSCRIPT


# ── Skill Graph sync after recording ─────────────────────────────────────────

def test_skill_graph_sync_after_recording_does_not_include_video_paths_or_signed_urls(
    client: TestClient, mem_store: dict, pipeline_db: dict
) -> None:
    from app.services.skill_evidence_pipeline_service import SkillEvidencePipelineService

    _project_id, session_id = _setup_defense_session(client)
    _start_session(client, session_id)

    client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json=_chunk_payload(session_id, chunk_index=0),
    )
    client.post(f"/api/v1/student/vbr/sessions/{session_id}/finalize", json={"duration_s": 60})

    _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)

    sync_response = _sync(client, session_id)
    assert sync_response.status_code == 200, sync_response.text
    assert sync_response.json()["ok"] is True

    pipeline_svc = SkillEvidencePipelineService(pipeline_db)
    pipelines = pipeline_svc.list_pipelines_for_student(USER_ID)
    assert pipelines

    for pipeline in pipelines:
        artifacts = pipeline_svc.list_artifacts_for_pipeline(pipeline.id, USER_ID)
        artifact = next(a for a in artifacts if a.artifact_data.get("kind") == "project_defense")
        data = artifact.artifact_data

        for unsafe_key in (
            "storage_path", "signed_url", "signedUrl", "upload_url",
            "video_path", "chunk_count", "recorded_video_present",
        ):
            assert unsafe_key not in data

        serialized = str(data)
        assert f"vbr/sessions/{session_id}" not in serialized
        assert ".webm" not in serialized
