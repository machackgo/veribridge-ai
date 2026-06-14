"""Tests for VBR transcript generation (Phase 1)."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.transcription_service import TranscriptionResult, TranscriptSegment

USER_ID = "00000000-0000-0000-0000-000000000042"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000099"

_FAKE_FULL_VIDEO_BYTES = b"fake-full-session-video-bytes"

_MOCK_SEGMENT_TEXTS = [
    "Candidate introduced the project and repository.",
    "Candidate explained a key implementation decision.",
]


def _fake_run_ffmpeg_concat(_manifest_path, output_path) -> None:
    """Deterministic stand-in for ffmpeg concat execution in tests."""
    output_path.write_bytes(_FAKE_FULL_VIDEO_BYTES)


def _fake_transcribe_audio(_file_bytes: bytes, _filename: str, _content_type: str | None = None) -> TranscriptionResult:
    """Deterministic stand-in for a configured transcription provider."""
    return TranscriptionResult(
        transcript_text=" ".join(_MOCK_SEGMENT_TEXTS),
        provider_used="openai",
        language="en",
        transcript_segments=[
            TranscriptSegment(start_time=0.0, end_time=8.0, text=_MOCK_SEGMENT_TEXTS[0]),
            TranscriptSegment(start_time=8.0, end_time=20.0, text=_MOCK_SEGMENT_TEXTS[1]),
        ],
    )


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


@pytest.fixture()
def configured_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend a transcription provider is configured and returns a fixed result."""
    monkeypatch.setattr("app.services.transcription_service.transcribe_audio", _fake_transcribe_audio)


@pytest.fixture()
def unconfigured_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend no transcription provider is configured, regardless of local .env."""
    monkeypatch.setattr("app.services.transcription_service._PROVIDER", "none")


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


def test_transcribe_without_provider_returns_safe_fallback(
    client: TestClient, mem_store: dict, unconfigured_provider: None
) -> None:
    """No TRANSCRIPTION_PROVIDER configured — safe 200 fallback, no transcript stored."""
    _project_id, session_id = _setup_processed_session(client)

    response = _transcribe(client, session_id)

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["session_id"] == session_id
    assert body["status"] == "not_configured"
    assert body["configured"] is False
    assert body["transcript_id"] is None
    assert body["segment_count"] == 0
    assert body["message"] == "Transcription provider is not configured. Use manual transcript fallback."

    assert "vbr_transcripts" not in mem_store or not mem_store["vbr_transcripts"]

    session = mem_store["vbr_verification_sessions"][session_id]
    assert session["telemetry"]["transcript"]["status"] == "not_configured"


def test_transcribe_creates_transcript_and_segments(
    client: TestClient, mem_store: dict, configured_provider: None
) -> None:
    _project_id, session_id = _setup_processed_session(client)

    response = _transcribe(client, session_id)

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["session_id"] == session_id
    assert body["status"] == "transcribed"
    assert body["configured"] is True
    assert body["provider"] == "openai"
    assert body["segment_count"] == 2
    assert body["duration_s"] == 20.0
    assert body["transcript_id"]

    transcripts = list(mem_store["vbr_transcripts"].values())
    assert len(transcripts) == 1
    transcript = transcripts[0]
    assert transcript["session_id"] == session_id
    assert transcript["id"] == body["transcript_id"]
    assert transcript["provider"] == "openai"
    assert transcript["full_text"] == " ".join(_MOCK_SEGMENT_TEXTS)

    segments = [
        row for row in mem_store["vbr_transcript_segments"].values()
        if row["transcript_id"] == transcript["id"]
    ]
    assert len(segments) == 2
    segment_texts = {row["text"] for row in segments}
    assert segment_texts == set(_MOCK_SEGMENT_TEXTS)

    # Session status remains 'processed' (migration has no 'transcribed' status);
    # transcript status is recorded in telemetry instead.
    session = mem_store["vbr_verification_sessions"][session_id]
    assert session["status"] == "processed"
    assert session["telemetry"]["transcript"]["status"] == "transcribed"
    assert session["telemetry"]["transcript"]["segment_count"] == 2
    assert session["telemetry"]["transcript"]["provider"] == "openai"

    project_after = client.get(f"/api/v1/student/vbr/projects/{_project_id}").json()
    assert project_after["status"] == "media_processed"


def test_transcribe_is_idempotent_and_does_not_duplicate(
    client: TestClient, mem_store: dict, configured_provider: None
) -> None:
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


def test_transcribe_response_does_not_expose_storage_paths_or_text(
    client: TestClient, configured_provider: None
) -> None:
    _project_id, session_id = _setup_processed_session(client)

    response = _transcribe(client, session_id)

    assert response.status_code == 200, response.text
    raw = response.text
    assert "storage_path" not in raw
    assert "signed" not in raw
    assert "vbr/sessions" not in raw
    assert "processed/full.webm" not in raw
    for text in _MOCK_SEGMENT_TEXTS:
        assert text not in raw


def test_transcribe_does_not_log_transcript_text(
    client: TestClient, caplog: pytest.LogCaptureFixture, configured_provider: None
) -> None:
    _project_id, session_id = _setup_processed_session(client)

    with caplog.at_level(logging.DEBUG):
        response = _transcribe(client, session_id)

    assert response.status_code == 200, response.text
    for text in _MOCK_SEGMENT_TEXTS:
        assert text not in caplog.text


def test_transcribe_provider_failure_returns_502(
    client: TestClient, mem_store: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(*_args: object, **_kwargs: object) -> TranscriptionResult:
        raise RuntimeError("Transcription returned an empty result. Try a longer recording.")

    monkeypatch.setattr("app.services.transcription_service.transcribe_audio", _fail)

    _project_id, session_id = _setup_processed_session(client)

    response = _transcribe(client, session_id)

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "vbr_transcription_failed"

    session = mem_store["vbr_verification_sessions"][session_id]
    assert session["telemetry"]["transcript"]["status"] == "failed"
    assert "vbr_transcripts" not in mem_store or not mem_store["vbr_transcripts"]


def test_transcribe_provider_failure_does_not_leak_runtime_details(
    client: TestClient, mem_store: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RuntimeError from transcription_service can contain ffmpeg stderr, local
    paths, or signed URLs (see transcription_service._transcribe_local_whisper).
    None of that may reach the API response — only a fixed safe message.
    """

    sensitive_message = (
        "Local Whisper transcription failed: ffmpeg stderr: "
        "Unable to open /Users/example/private/video.webm "
        "(signed_url=https://storage.example.com/vbr/sessions/secret-session?token=abc123). "
        "Try again or paste your transcript manually."
    )

    def _fail(*_args: object, **_kwargs: object) -> TranscriptionResult:
        raise RuntimeError(sensitive_message)

    monkeypatch.setattr("app.services.transcription_service.transcribe_audio", _fail)

    _project_id, session_id = _setup_processed_session(client)

    response = _transcribe(client, session_id)

    assert response.status_code == 502
    body = response.json()
    raw = response.text

    assert body["detail"]["code"] == "vbr_transcription_failed"
    assert body["detail"]["message"] == (
        "Transcription failed. Please try again later or use the manual transcript fallback."
    )

    for sensitive in (
        "/Users/example/private/video.webm",
        "signed_url=",
        "ffmpeg stderr",
        "token=abc123",
    ):
        assert sensitive not in raw

    session = mem_store["vbr_verification_sessions"][session_id]
    assert session["telemetry"]["transcript"]["status"] == "failed"
    assert "vbr_transcripts" not in mem_store or not mem_store["vbr_transcripts"]
