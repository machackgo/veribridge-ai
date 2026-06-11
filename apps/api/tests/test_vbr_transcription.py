"""Tests for the VBR transcript-generation skeleton (T5D)."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app

USER_ID = "00000000-0000-0000-0000-000000000042"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000099"

_FAKE_FULL_VIDEO_BYTES = b"fake-full-session-video-bytes"

_SKELETON_SEGMENT_TEXTS = [
    "Candidate introduced the project and repository.",
    "Candidate explained a key implementation decision.",
]


def _fake_run_ffmpeg_concat(_manifest_path, output_path) -> None:
    """Deterministic stand-in for ffmpeg concat execution in tests."""
    output_path.write_bytes(_FAKE_FULL_VIDEO_BYTES)


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        "app.services.vbr_media_processing.run_ffmpeg_concat", _fake_run_ffmpeg_concat
    )
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
    import hashlib

    from app.services.vbr_media_processing import fake_chunk_bytes

    chunk_bytes = int(overrides.get("bytes", 1024))
    sha256 = overrides.get("sha256") or hashlib.sha256(
        fake_chunk_bytes(session_id, chunk_index, chunk_bytes)
    ).hexdigest()
    payload = {
        "chunk_index": chunk_index,
        "storage_path": f"vbr/sessions/{session_id}/chunks/{chunk_index:03d}.webm",
        "bytes": chunk_bytes,
        "sha256": sha256,
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


def _setup_processed_session(client: TestClient, chunk_count: int = 1) -> tuple[str, str]:
    """Create a project/session and run it through /process so it is 'processed'."""
    project_id, session_id = _setup_session(client)
    _start_session(client, session_id)
    for chunk_index in range(chunk_count):
        _upload_chunk(client, session_id, chunk_index)
    _finalize(client, session_id, duration_s=120)

    process_response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/process")
    assert process_response.status_code == 200, process_response.text

    return project_id, session_id


def _transcribe(client: TestClient, session_id: str):
    return client.post(f"/api/v1/student/vbr/sessions/{session_id}/transcribe")


def test_transcribe_requires_owner(client: TestClient) -> None:
    _project_id, session_id = _setup_processed_session(client)

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = _transcribe(client, session_id)

    assert response.status_code == 404


def test_transcribe_requires_processed_status(client: TestClient) -> None:
    _project_id, session_id = _setup_session(client)

    response = _transcribe(client, session_id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "vbr_session_not_processed"


def test_transcribe_requires_full_video_telemetry(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_processed_session(client)

    # Simulate a processed session whose telemetry is missing the full-video entry.
    telemetry = mem_store["vbr_verification_sessions"][session_id]["telemetry"]
    del telemetry["media_processing"]["full_video"]

    response = _transcribe(client, session_id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "vbr_session_full_video_missing"


def test_transcribe_creates_transcript_and_segments(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_processed_session(client)

    response = _transcribe(client, session_id)

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["session_id"] == session_id
    assert body["status"] == "transcribed"
    assert body["segment_count"] == 2
    assert body["duration_s"] == 20.0
    assert body["transcript_id"]

    transcripts = list(mem_store["vbr_transcripts"].values())
    assert len(transcripts) == 1
    transcript = transcripts[0]
    assert transcript["session_id"] == session_id
    assert transcript["id"] == body["transcript_id"]

    segments = [
        row for row in mem_store["vbr_transcript_segments"].values()
        if row["transcript_id"] == transcript["id"]
    ]
    assert len(segments) == 2
    segment_texts = {row["text"] for row in segments}
    assert segment_texts == set(_SKELETON_SEGMENT_TEXTS)

    # Session status remains 'processed' (migration has no 'transcribed' status);
    # transcript status is recorded in telemetry instead.
    session = mem_store["vbr_verification_sessions"][session_id]
    assert session["status"] == "processed"
    assert session["telemetry"]["transcript"]["status"] == "transcribed"
    assert session["telemetry"]["transcript"]["segment_count"] == 2

    project_after = client.get(f"/api/v1/student/vbr/projects/{_project_id}").json()
    assert project_after["status"] == "media_processed"


def test_transcribe_is_idempotent_and_does_not_duplicate(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_processed_session(client)

    first = _transcribe(client, session_id)
    assert first.status_code == 200, first.text
    first_transcript_id = first.json()["transcript_id"]

    second = _transcribe(client, session_id)
    assert second.status_code == 200, second.text
    second_transcript_id = second.json()["transcript_id"]

    assert first_transcript_id == second_transcript_id

    transcripts = [
        row for row in mem_store["vbr_transcripts"].values()
        if row["session_id"] == session_id
    ]
    assert len(transcripts) == 1

    segments = [
        row for row in mem_store["vbr_transcript_segments"].values()
        if row["transcript_id"] == first_transcript_id
    ]
    assert len(segments) == 2


def test_transcribe_response_does_not_expose_storage_paths_or_text(client: TestClient) -> None:
    _project_id, session_id = _setup_processed_session(client)

    response = _transcribe(client, session_id)

    assert response.status_code == 200, response.text
    raw = response.text
    assert "storage_path" not in raw
    assert "signed" not in raw
    assert "vbr/sessions" not in raw
    assert "processed/full.webm" not in raw
    for text in _SKELETON_SEGMENT_TEXTS:
        assert text not in raw


def test_transcribe_does_not_log_transcript_text(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    _project_id, session_id = _setup_processed_session(client)

    with caplog.at_level(logging.DEBUG):
        response = _transcribe(client, session_id)

    assert response.status_code == 200, response.text
    for text in _SKELETON_SEGMENT_TEXTS:
        assert text not in caplog.text
