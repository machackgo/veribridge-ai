"""Tests for VBR session recording/upload foundation (T4A)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app

USER_ID = "00000000-0000-0000-0000-000000000042"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000099"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _create_project(client: TestClient, **overrides: object) -> dict:
    payload = {
        "title": "My Capstone Project",
        "repo_url": "https://github.com/octocat/Hello-World",
        **overrides,
    }
    response = client.post("/api/v1/student/vbr/projects", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _setup_session(client: TestClient, project_id: str | None = None) -> tuple[str, str]:
    """Create a project (if not given), confirm claims, and generate questions.

    Returns ``(project_id, session_id)``.
    """
    if project_id is None:
        project_id = _create_project(client)["id"]

    response = client.post(f"/api/v1/student/vbr/projects/{project_id}/ingest-repo")
    assert response.status_code == 200, response.text

    claims_response = client.post(f"/api/v1/student/vbr/projects/{project_id}/generate-claims")
    assert claims_response.status_code == 200, claims_response.text
    for claim in claims_response.json()["claims"]:
        confirm = client.patch(
            f"/api/v1/student/vbr/projects/{project_id}/claims/{claim['id']}",
            json={"status": "confirmed"},
        )
        assert confirm.status_code == 200, confirm.text

    questions_response = client.post(f"/api/v1/student/vbr/projects/{project_id}/generate-questions")
    assert questions_response.status_code == 200, questions_response.text

    return project_id, questions_response.json()["session_id"]


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
        "storage_path": f"vbr/sessions/{session_id}/chunks/{chunk_index}.webm",
        "bytes": 1024,
        "sha256": "a" * 64,
        **overrides,
    }
    return payload


def test_get_session_requires_owner(client: TestClient) -> None:
    _project_id, session_id = _setup_session(client)

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = client.get(f"/api/v1/student/vbr/sessions/{session_id}")

    assert response.status_code == 404


def test_get_session_returns_metadata_and_questions(client: TestClient) -> None:
    _project_id, session_id = _setup_session(client)

    response = client.get(f"/api/v1/student/vbr/sessions/{session_id}")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["id"] == session_id
    assert body["status"] == "created"
    assert body["chunk_count"] == 0
    assert "questions" in body
    assert len(body["questions"]) >= 1
    assert "video_path" not in body


def test_start_session_fails_without_recording_consent(client: TestClient) -> None:
    _project_id, session_id = _setup_session(client)

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/start")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_recording_consent_required"


def test_consent_endpoint_creates_recording_consent(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_session(client)

    body = _grant_consent(client, session_id)

    assert body["user_id"] == USER_ID
    assert body["kind"] == "recording"
    assert body["granted"] is True
    assert body["text_version"] == "recording_v1"

    consent_rows = list(mem_store["consent_records"].values())
    assert len(consent_rows) == 1
    assert consent_rows[0]["kind"] == "recording"


def test_start_session_succeeds_after_consent_and_sets_recording(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_session(client)

    body = _start_session(client, session_id)

    assert body["status"] == "recording"
    assert body["started_at"] is not None
    assert mem_store["vbr_verification_sessions"][session_id]["status"] == "recording"

    # Cannot start again once already recording.
    second = client.post(f"/api/v1/student/vbr/sessions/{session_id}/start")
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "vbr_session_not_startable"


def test_chunk_insert_requires_recording_status(client: TestClient) -> None:
    _project_id, session_id = _setup_session(client)

    response = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json=_chunk_payload(session_id),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "vbr_session_not_recording"


def test_chunk_insert_rejects_oversized_chunk(client: TestClient) -> None:
    _project_id, session_id = _setup_session(client)
    _start_session(client, session_id)

    response = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json=_chunk_payload(session_id, bytes=25 * 1024 * 1024 + 1),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_invalid_chunk_size"


def test_chunk_insert_rejects_unsafe_storage_path(client: TestClient) -> None:
    _project_id, session_id = _setup_session(client)
    _start_session(client, session_id)

    response = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json=_chunk_payload(session_id, storage_path="../../etc/passwd"),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_invalid_chunk_storage_path"


def test_chunk_insert_succeeds_when_recording(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_session(client)
    _start_session(client, session_id)

    response = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json=_chunk_payload(session_id, chunk_index=0),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["session_id"] == session_id
    assert body["chunk_index"] == 0
    assert body["bytes"] == 1024
    assert len(mem_store["vbr_video_chunks"]) == 1

    # Re-uploading the same chunk index upserts rather than duplicating.
    response2 = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json=_chunk_payload(session_id, chunk_index=0, bytes=2048),
    )
    assert response2.status_code == 200, response2.text
    assert response2.json()["bytes"] == 2048
    assert len(mem_store["vbr_video_chunks"]) == 1


def test_telemetry_update_requires_owner_and_recording_status(client: TestClient) -> None:
    _project_id, session_id = _setup_session(client)

    # Not recording yet.
    response = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/telemetry",
        json={"telemetry": {"events": [{"q": 1, "t": 2.5}]}},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "vbr_session_not_recording"

    _start_session(client, session_id)

    # Other user cannot update telemetry.
    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    other_response = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/telemetry",
        json={"telemetry": {"events": [{"q": 1, "t": 2.5}]}},
    )
    assert other_response.status_code == 404

    # Owner can update telemetry once recording.
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    ok_response = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/telemetry",
        json={"telemetry": {"events": [{"q": 1, "t": 2.5}]}},
    )
    assert ok_response.status_code == 200, ok_response.text
    assert ok_response.json()["telemetry"]["events"] == [{"q": 1, "t": 2.5}]

    # Merge does not clobber other keys.
    merge_response = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/telemetry",
        json={"telemetry": {"webcam_present": True}},
    )
    assert merge_response.status_code == 200, merge_response.text
    body = merge_response.json()["telemetry"]
    assert body["webcam_present"] is True
    assert body["events"] == [{"q": 1, "t": 2.5}]


def test_finalize_requires_at_least_one_chunk(client: TestClient) -> None:
    _project_id, session_id = _setup_session(client)
    _start_session(client, session_id)

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/finalize", json={})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_session_no_chunks"


def test_finalize_sets_session_uploaded_and_project_status(client: TestClient, mem_store: dict) -> None:
    project_id, session_id = _setup_session(client)
    _start_session(client, session_id)

    chunk_response = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json=_chunk_payload(session_id, chunk_index=0),
    )
    assert chunk_response.status_code == 200, chunk_response.text

    response = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/finalize",
        json={"duration_s": 120},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] == "uploaded"
    assert body["ended_at"] is not None
    assert body["duration_s"] == 120
    assert body["chunk_count"] == 1

    project_after = client.get(f"/api/v1/student/vbr/projects/{project_id}").json()
    assert project_after["status"] == "session_uploaded"

    # Cannot finalize again once already uploaded.
    second = client.post(f"/api/v1/student/vbr/sessions/{session_id}/finalize", json={})
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "vbr_session_not_recording"


def test_other_user_cannot_start_chunk_or_finalize_session(client: TestClient) -> None:
    _project_id, session_id = _setup_session(client)
    _start_session(client, session_id)

    chunk_response = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json=_chunk_payload(session_id, chunk_index=0),
    )
    assert chunk_response.status_code == 200, chunk_response.text

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID

    start_response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/start")
    assert start_response.status_code == 404

    chunk_response2 = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json=_chunk_payload(session_id, chunk_index=1),
    )
    assert chunk_response2.status_code == 404

    finalize_response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/finalize", json={})
    assert finalize_response.status_code == 404


def test_get_session_for_other_user_returns_generic_session_not_found(client: TestClient) -> None:
    project_id, session_id = _setup_session(client)

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = client.get(f"/api/v1/student/vbr/sessions/{session_id}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "vbr_session_not_found"
    assert project_id not in str(response.json())

def test_chunk_rejects_storage_path_traversal(client: TestClient) -> None:
    _project_id, session_id = _setup_session(client)
    _start_session(client, session_id)

    response = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json={
            "chunk_index": 0,
            "storage_path": f"vbr/sessions/{session_id}/chunks/../../other/chunk.webm",
            "bytes": 1024,
            "sha256": "a" * 64,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_invalid_chunk_storage_path"

def test_chunk_rejects_malformed_sha256(client: TestClient) -> None:
    _project_id, session_id = _setup_session(client)
    _start_session(client, session_id)

    response = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json={
            "chunk_index": 0,
            "storage_path": f"vbr/sessions/{session_id}/chunks/000.webm",
            "bytes": 1024,
            "sha256": "not-a-real-sha",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_invalid_chunk_sha256"

