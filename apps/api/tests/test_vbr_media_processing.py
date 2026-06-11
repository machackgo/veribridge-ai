"""Tests for the VBR uploaded-session media-processing skeleton (T5A)."""

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
        "storage_path": f"vbr/sessions/{session_id}/chunks/{chunk_index:03d}.webm",
        "bytes": 1024,
        "sha256": "a" * 64,
        **overrides,
    }
    return payload


def _upload_chunk(client: TestClient, session_id: str, chunk_index: int, **overrides: object) -> dict:
    response = client.post(
        f"/api/v1/student/vbr/sessions/{session_id}/chunk",
        json=_chunk_payload(session_id, chunk_index, **overrides),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _finalize(client: TestClient, session_id: str, **kwargs: object) -> dict:
    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/finalize", json=kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def _setup_uploaded_session(client: TestClient, chunk_count: int = 1) -> tuple[str, str]:
    project_id, session_id = _setup_session(client)
    _start_session(client, session_id)
    for chunk_index in range(chunk_count):
        _upload_chunk(client, session_id, chunk_index)
    _finalize(client, session_id, duration_s=120)
    return project_id, session_id


def _process(client: TestClient, session_id: str):
    return client.post(f"/api/v1/student/vbr/sessions/{session_id}/process")


def test_process_requires_owner(client: TestClient) -> None:
    _project_id, session_id = _setup_uploaded_session(client)

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = _process(client, session_id)

    assert response.status_code == 404


def test_process_requires_uploaded_session(client: TestClient) -> None:
    _project_id, session_id = _setup_session(client)

    response = _process(client, session_id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "vbr_session_not_uploaded"


def test_process_requires_at_least_one_chunk(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_session(client)
    _start_session(client, session_id)

    # Force the session into 'uploaded' status without any chunks (finalize
    # would normally reject this, so mutate the fake store directly).
    mem_store["vbr_verification_sessions"][session_id]["status"] = "uploaded"

    response = _process(client, session_id)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_manifest_empty"


def test_process_rejects_non_contiguous_chunk_indexes(client: TestClient) -> None:
    project_id, session_id = _setup_session(client)
    _start_session(client, session_id)
    _upload_chunk(client, session_id, 0)
    _upload_chunk(client, session_id, 2)
    _finalize(client, session_id)

    response = _process(client, session_id)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_manifest_non_contiguous"


def test_process_rejects_duplicate_chunk_index(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_uploaded_session(client, chunk_count=1)

    chunks = mem_store["vbr_video_chunks"]
    original = next(iter(chunks.values()))
    duplicate = {**original, "id": "duplicate-chunk-id"}
    chunks[duplicate["id"]] = duplicate

    response = _process(client, session_id)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_manifest_duplicate_chunk_index"


def test_process_rejects_invalid_sha256(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_uploaded_session(client, chunk_count=1)

    chunk = next(iter(mem_store["vbr_video_chunks"].values()))
    chunk["sha256"] = "not-a-real-sha"

    response = _process(client, session_id)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_manifest_invalid_sha256"


def test_process_rejects_wrong_storage_path_for_chunk_index(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_uploaded_session(client, chunk_count=1)

    chunk = next(iter(mem_store["vbr_video_chunks"].values()))
    chunk["storage_path"] = f"vbr/sessions/{session_id}/chunks/999.webm"

    response = _process(client, session_id)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_manifest_invalid_storage_path"


def test_process_succeeds_and_sets_session_and_project_status(client: TestClient, mem_store: dict) -> None:
    project_id, session_id = _setup_uploaded_session(client, chunk_count=2)

    response = _process(client, session_id)

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["session_id"] == session_id
    assert body["status"] == "processed"
    assert body["chunk_count"] == 2
    assert body["total_bytes"] == 2048
    assert body["next_steps"] == ["concat_video", "transcribe_audio", "extract_keyframes"]

    assert mem_store["vbr_verification_sessions"][session_id]["status"] == "processed"

    project_after = client.get(f"/api/v1/student/vbr/projects/{project_id}").json()
    assert project_after["status"] == "media_processed"


def test_process_response_does_not_expose_storage_paths_or_signed_urls(client: TestClient) -> None:
    _project_id, session_id = _setup_uploaded_session(client, chunk_count=1)

    response = _process(client, session_id)

    assert response.status_code == 200, response.text
    raw = response.text
    assert "storage_path" not in raw
    assert "signed" not in raw
    assert "vbr/sessions" not in raw


def test_manifest_summary_is_stored_in_session_telemetry(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_uploaded_session(client, chunk_count=1)

    response = _process(client, session_id)
    assert response.status_code == 200, response.text

    telemetry = mem_store["vbr_verification_sessions"][session_id]["telemetry"]
    media_processing = telemetry["media_processing"]

    assert media_processing["manifest_verified"] is True
    assert media_processing["chunk_count"] == 1
    assert media_processing["total_bytes"] == 1024
    assert media_processing["started_at"]
    assert media_processing["completed_at"]
    assert media_processing["next_steps"] == ["concat_video", "transcribe_audio", "extract_keyframes"]


def test_process_rejects_invalid_chunk_index(client: TestClient, mem_store: dict) -> None:
    project_id, session_id = _setup_uploaded_session(client)
    chunk = next(iter(mem_store["vbr_video_chunks"].values()))
    chunk["chunk_index"] = "0"

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/process")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_manifest_invalid_chunk_index"
    assert mem_store["vbr_verification_sessions"][session_id]["status"] == "uploaded"
    assert mem_store["vbr_projects"][project_id]["status"] != "media_processed"


def test_process_rejects_invalid_chunk_bytes(client: TestClient, mem_store: dict) -> None:
    project_id, session_id = _setup_uploaded_session(client)
    chunk = next(iter(mem_store["vbr_video_chunks"].values()))
    chunk["bytes"] = 0

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/process")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_manifest_invalid_bytes"
    assert mem_store["vbr_verification_sessions"][session_id]["status"] == "uploaded"
    assert mem_store["vbr_projects"][project_id]["status"] != "media_processed"


def test_process_rejects_total_bytes_cap(client: TestClient, mem_store: dict) -> None:
    project_id, session_id = _setup_uploaded_session(client)
    chunk = next(iter(mem_store["vbr_video_chunks"].values()))
    chunk["bytes"] = 2 * 1024 * 1024 * 1024

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/process")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_manifest_total_bytes_exceeded"
    assert mem_store["vbr_verification_sessions"][session_id]["status"] == "uploaded"
    assert mem_store["vbr_projects"][project_id]["status"] != "media_processed"
