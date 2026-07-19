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


def _fake_transcribe_audio(_file_bytes: bytes, _filename: str, content_type: str | None = None) -> TranscriptionResult:
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


_NO_SPEECH_MESSAGE = (
    "No useful speech was detected. Please retry with clearer audio or use the "
    "manual transcript fallback."
)


def _fake_transcribe_returning(full_text: str, segment_texts: list[str]):
    """Build a stand-in transcribe_audio that returns fixed text/segments.

    Used to drive the no-speech / punctuation-only guard: a silent recording
    makes Whisper emit punctuation-only segments (a run of "." tokens) rather
    than an empty string.
    """

    def _fn(_file_bytes: bytes, _filename: str, content_type: str | None = None) -> TranscriptionResult:
        return TranscriptionResult(
            transcript_text=full_text,
            provider_used="local_whisper",
            language="en",
            transcript_segments=[
                TranscriptSegment(start_time=float(i * 7), end_time=float(i * 7 + 7), text=text)
                for i, text in enumerate(segment_texts)
            ],
        )

    return _fn


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


def test_transcribe_passes_video_webm_content_type(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VBR must call the shared provider with content_type='video/webm' so the
    combined screen+mic recording is routed through ffmpeg audio extraction
    instead of being decoded as an audio-only container."""
    captured: dict = {}

    def _spy(file_bytes: bytes, filename: str, content_type: str | None = None) -> TranscriptionResult:
        captured["filename"] = filename
        captured["content_type"] = content_type
        return _fake_transcribe_audio(file_bytes, filename, content_type)

    monkeypatch.setattr("app.services.transcription_service.transcribe_audio", _spy)

    _project_id, session_id = _setup_processed_session(client)
    response = _transcribe(client, session_id)

    assert response.status_code == 200, response.text
    assert captured["filename"] == "full.webm"
    assert captured["content_type"] == "video/webm"


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


def test_transcribe_retry_after_failure_succeeds(
    client: TestClient, mem_store: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed transcription is retryable: a later successful run produces a
    real transcript, and the failed attempt left no partial transcript behind."""
    calls = {"n": 0}

    def _flaky(*_args: object, **_kwargs: object) -> TranscriptionResult:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Local Whisper transcription failed: transient error.")
        return _fake_transcribe_audio(b"", "full.webm")

    monkeypatch.setattr("app.services.transcription_service.transcribe_audio", _flaky)

    _project_id, session_id = _setup_processed_session(client)

    first = _transcribe(client, session_id)
    assert first.status_code == 502, first.text
    session = mem_store["vbr_verification_sessions"][session_id]
    assert session["telemetry"]["transcript"]["status"] == "failed"
    assert "vbr_transcripts" not in mem_store or not mem_store["vbr_transcripts"]

    # Retry from the failed state (session is still 'processed') — now succeeds.
    second = _transcribe(client, session_id)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["status"] == "transcribed"
    assert body["segment_count"] == 2

    session = mem_store["vbr_verification_sessions"][session_id]
    assert session["telemetry"]["transcript"]["status"] == "transcribed"
    transcripts = [
        row for row in mem_store["vbr_transcripts"].values()
        if row["session_id"] == session_id
    ]
    assert len(transcripts) == 1


# ── No-speech / punctuation-only guard ───────────────────────────────────────


@pytest.mark.parametrize(
    "full_text, segment_texts",
    [
        ("", []),                              # empty transcript text
        ("   ", ["   "]),                       # whitespace-only
        (".", [".", ".", "."]),                # single-dot segments (the reported bug)
        ("...", ["..."]),                      # ellipsis only
        (". . . .", [".", ".", ".", "."]),     # dot-only per segment
        ("?! ...", ["?!", "..."]),             # mixed punctuation only
        ("a b", ["a", "b"]),                   # below the meaningful-word threshold
    ],
)
def test_transcribe_no_speech_is_not_success(
    client: TestClient,
    mem_store: dict,
    monkeypatch: pytest.MonkeyPatch,
    full_text: str,
    segment_texts: list[str],
) -> None:
    """A punctuation-only / no-speech provider result must fail safely — it is
    never persisted or reported as a saved transcript."""
    monkeypatch.setattr(
        "app.services.transcription_service.transcribe_audio",
        _fake_transcribe_returning(full_text, segment_texts),
    )

    _project_id, session_id = _setup_processed_session(client)

    response = _transcribe(client, session_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "no_speech"
    assert body["transcript_id"] is None
    assert body["segment_count"] == 0
    assert body["configured"] is True
    assert body["message"] == _NO_SPEECH_MESSAGE

    # Nothing was persisted — no transcript row, no segments.
    assert "vbr_transcripts" not in mem_store or not mem_store["vbr_transcripts"]
    assert (
        "vbr_transcript_segments" not in mem_store
        or not mem_store["vbr_transcript_segments"]
    )

    session = mem_store["vbr_verification_sessions"][session_id]
    assert session["telemetry"]["transcript"]["status"] == "no_speech"


def test_transcribe_three_meaningful_words_succeeds(
    client: TestClient, mem_store: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transcript with at least three meaningful words is a real success."""
    monkeypatch.setattr(
        "app.services.transcription_service.transcribe_audio",
        _fake_transcribe_returning("I built APIs.", ["I built APIs."]),
    )

    _project_id, session_id = _setup_processed_session(client)

    response = _transcribe(client, session_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "transcribed"
    assert body["segment_count"] == 1
    assert body["transcript_id"]
    assert mem_store["vbr_transcripts"]


_LOW_QUALITY_MESSAGE = "Transcript quality too low. Please re-record or use manual explanation."


def test_transcribe_repeated_token_hallucination_is_not_success(
    client: TestClient, mem_store: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repeated-token hallucination ("new new new …") must fail safely — it is
    never persisted or reported as a saved transcript."""
    # Mirrors the real observed failure: a burst of one repeated word between a
    # little real speech at the ends.
    hallucinated = "I'm going to start with the " + ("new " * 30) + "geographic and cloud API logic."
    segment_texts = ["I'm going to start with the"] + ["new"] * 28 + ["geographic and cloud API logic."]
    monkeypatch.setattr(
        "app.services.transcription_service.transcribe_audio",
        _fake_transcribe_returning(hallucinated, segment_texts),
    )

    _project_id, session_id = _setup_processed_session(client)

    response = _transcribe(client, session_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "low_quality"
    assert body["transcript_id"] is None
    assert body["segment_count"] == 0
    assert body["configured"] is True
    assert body["message"] == _LOW_QUALITY_MESSAGE

    # Nothing was persisted — no hallucinated transcript saved as evidence.
    assert "vbr_transcripts" not in mem_store or not mem_store["vbr_transcripts"]
    assert (
        "vbr_transcript_segments" not in mem_store
        or not mem_store["vbr_transcript_segments"]
    )

    session = mem_store["vbr_verification_sessions"][session_id]
    assert session["telemetry"]["transcript"]["status"] == "low_quality"


def test_transcribe_short_repeated_token_is_not_saved(
    client: TestClient, mem_store: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A short repeated-token hallucination ("new new new") clears the no-speech
    gate (3 meaningful words) but must still fail closed — never persisted as a
    saved transcript, so the UI never offers to analyze it."""
    monkeypatch.setattr(
        "app.services.transcription_service.transcribe_audio",
        _fake_transcribe_returning("new new new", ["new new new"]),
    )

    _project_id, session_id = _setup_processed_session(client)

    response = _transcribe(client, session_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "low_quality"
    assert body["transcript_id"] is None
    assert body["segment_count"] == 0
    assert body["message"] == _LOW_QUALITY_MESSAGE

    # Nothing was persisted — the short hallucination is not saved as evidence.
    assert "vbr_transcripts" not in mem_store or not mem_store["vbr_transcripts"]
    assert (
        "vbr_transcript_segments" not in mem_store
        or not mem_store["vbr_transcript_segments"]
    )
    session = mem_store["vbr_verification_sessions"][session_id]
    assert session["telemetry"]["transcript"]["status"] == "low_quality"


def test_transcribe_low_quality_response_is_sanitized(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The low-quality response exposes no storage paths, signed URLs, or text."""
    monkeypatch.setattr(
        "app.services.transcription_service.transcribe_audio",
        _fake_transcribe_returning("new " * 30, ["new"] * 30),
    )

    _project_id, session_id = _setup_processed_session(client)
    body = _transcribe(client, session_id).json()

    serialized = str(body)
    assert body["status"] == "low_quality"
    assert "new new" not in serialized  # hallucinated text never echoed back
    assert "storage" not in serialized.lower()
    assert "http" not in serialized.lower()


def test_transcribe_normal_multiword_transcript_passes_quality_guard(
    client: TestClient, mem_store: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A normal, varied explanation is NOT flagged as low quality — it is saved."""
    normal = (
        "I built the risk-scoring API with FastAPI and a PostgreSQL database, then "
        "wired the React front end to display accident-risk routes on a map."
    )
    monkeypatch.setattr(
        "app.services.transcription_service.transcribe_audio",
        _fake_transcribe_returning(normal, [normal]),
    )

    _project_id, session_id = _setup_processed_session(client)
    body = _transcribe(client, session_id).json()

    assert body["status"] == "transcribed"
    assert body["transcript_id"]
    assert mem_store["vbr_transcripts"]


def test_get_transcript_reflects_low_quality_status(
    client: TestClient, mem_store: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a low-quality result, the owner transcript endpoint reports it and
    returns no saved segments."""
    monkeypatch.setattr(
        "app.services.transcription_service.transcribe_audio",
        _fake_transcribe_returning("new " * 30, ["new"] * 30),
    )
    _project_id, session_id = _setup_processed_session(client)
    assert _transcribe(client, session_id).json()["status"] == "low_quality"

    response = client.get(f"/api/v1/student/vbr/sessions/{session_id}/transcript")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "low_quality"
    assert body["segments"] == []
    assert body["preview_text"] == ""


def test_transcribe_no_speech_response_is_sanitized(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The no-speech response exposes no storage paths, signed URLs, or text."""
    monkeypatch.setattr(
        "app.services.transcription_service.transcribe_audio",
        _fake_transcribe_returning(". . .", [".", ".", "."]),
    )

    _project_id, session_id = _setup_processed_session(client)

    response = _transcribe(client, session_id)

    assert response.status_code == 200, response.text
    raw = response.text
    assert "storage_path" not in raw
    assert "signed" not in raw
    assert "vbr/sessions" not in raw
    assert "full.webm" not in raw


def test_transcribe_retry_after_no_speech_succeeds(
    client: TestClient, mem_store: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A no-speech attempt is retryable: a later run with real speech succeeds,
    and the no-speech attempt left no partial transcript behind."""
    calls = {"n": 0}

    def _flaky(file_bytes: bytes, filename: str, content_type: str | None = None) -> TranscriptionResult:
        calls["n"] += 1
        if calls["n"] == 1:
            return _fake_transcribe_returning(". . .", [".", ".", "."])(file_bytes, filename, content_type)
        return _fake_transcribe_audio(file_bytes, filename, content_type)

    monkeypatch.setattr("app.services.transcription_service.transcribe_audio", _flaky)

    _project_id, session_id = _setup_processed_session(client)

    first = _transcribe(client, session_id)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "no_speech"
    session = mem_store["vbr_verification_sessions"][session_id]
    assert session["telemetry"]["transcript"]["status"] == "no_speech"
    assert "vbr_transcripts" not in mem_store or not mem_store["vbr_transcripts"]

    second = _transcribe(client, session_id)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["status"] == "transcribed"
    assert body["segment_count"] == 2

    session = mem_store["vbr_verification_sessions"][session_id]
    assert session["telemetry"]["transcript"]["status"] == "transcribed"
    transcripts = [
        row for row in mem_store["vbr_transcripts"].values()
        if row["session_id"] == session_id
    ]
    assert len(transcripts) == 1


# ── Owner-only transcript preview (GET /{session_id}/transcript) ──────────────


def _get_transcript(client: TestClient, session_id: str):
    return client.get(f"/api/v1/student/vbr/sessions/{session_id}/transcript")


def test_get_transcript_requires_owner(client: TestClient, configured_provider: None) -> None:
    _project_id, session_id = _setup_processed_session(client)
    assert _transcribe(client, session_id).status_code == 200

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    try:
        response = _get_transcript(client, session_id)
    finally:
        app.dependency_overrides[get_current_user_id] = lambda: USER_ID

    assert response.status_code == 404


def test_get_transcript_returns_not_generated_before_transcription(client: TestClient) -> None:
    _project_id, session_id = _setup_processed_session(client)

    response = _get_transcript(client, session_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == session_id
    assert body["status"] == "not_generated"
    assert body["transcript_id"] is None
    assert body["segment_count"] == 0
    assert body["preview_text"] == ""
    assert body["segments"] == []


def test_get_transcript_returns_owner_text_and_segments(
    client: TestClient, configured_provider: None
) -> None:
    _project_id, session_id = _setup_processed_session(client)
    assert _transcribe(client, session_id).status_code == 200

    response = _get_transcript(client, session_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "transcribed"
    assert body["transcript_id"]
    assert body["provider"] == "openai"
    assert body["segment_count"] == 2
    assert body["truncated"] is False

    # The owner's own private preview DOES include the transcript text/segments.
    assert body["preview_text"] == " ".join(_MOCK_SEGMENT_TEXTS)
    segment_texts = [segment["text"] for segment in body["segments"]]
    assert segment_texts == list(_MOCK_SEGMENT_TEXTS)
    # Segments are timestamp-ordered.
    starts = [segment["start_s"] for segment in body["segments"]]
    assert starts == sorted(starts)


def test_get_transcript_reflects_failed_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(*_args: object, **_kwargs: object) -> TranscriptionResult:
        raise RuntimeError("Transcription returned an empty result.")

    monkeypatch.setattr("app.services.transcription_service.transcribe_audio", _fail)

    _project_id, session_id = _setup_processed_session(client)
    assert _transcribe(client, session_id).status_code == 502

    response = _get_transcript(client, session_id)

    assert response.status_code == 200, response.text
    body = response.json()
    # A failed run must never look like a saved transcript.
    assert body["status"] == "failed"
    assert body["transcript_id"] is None
    assert body["preview_text"] == ""
    assert body["segments"] == []


def test_get_transcript_reflects_no_speech_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.transcription_service.transcribe_audio",
        _fake_transcribe_returning(". . .", [".", ".", "."]),
    )

    _project_id, session_id = _setup_processed_session(client)
    assert _transcribe(client, session_id).json()["status"] == "no_speech"

    response = _get_transcript(client, session_id)

    assert response.status_code == 200, response.text
    body = response.json()
    # A no-speech run must never look like a saved transcript.
    assert body["status"] == "no_speech"
    assert body["transcript_id"] is None
    assert body["preview_text"] == ""
    assert body["segments"] == []


def test_get_transcript_preview_is_capped(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import vbr_transcription

    # Varied long text (not a single repeated word) so it comfortably exceeds the
    # preview cap without tripping the repeated-token quality guard.
    long_text = " ".join(f"token{i % 60}" for i in range(2000))

    def _long(*_args: object, **_kwargs: object) -> TranscriptionResult:
        return TranscriptionResult(
            transcript_text=long_text,
            provider_used="openai",
            language="en",
            transcript_segments=[TranscriptSegment(start_time=0.0, end_time=5.0, text=long_text)],
        )

    monkeypatch.setattr("app.services.transcription_service.transcribe_audio", _long)

    _project_id, session_id = _setup_processed_session(client)
    assert _transcribe(client, session_id).status_code == 200

    response = _get_transcript(client, session_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["truncated"] is True
    assert len(body["preview_text"]) == vbr_transcription._PREVIEW_CHAR_LIMIT


# ── Meaningful-word helper (unit) ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, expected",
    [
        ("", 0),
        ("   ", 0),
        (".", 0),
        ("...", 0),
        (". . . .", 0),
        ("?! ...", 0),
        ("-- __", 0),
        ("a", 1),
        ("I built APIs.", 3),
        ("I built a REST API with JWT.", 7),
    ],
)
def test_count_meaningful_words(text: str, expected: int) -> None:
    from app.services.transcription_service import count_meaningful_words

    assert count_meaningful_words(text) == expected


def test_is_meaningful_transcript_threshold() -> None:
    from app.services.transcription_service import (
        MEANINGFUL_WORD_THRESHOLD,
        is_meaningful_transcript,
    )

    assert MEANINGFUL_WORD_THRESHOLD == 3
    assert is_meaningful_transcript("I built APIs.") is True
    assert is_meaningful_transcript(". . .") is False
    assert is_meaningful_transcript("just two") is False


@pytest.mark.parametrize(
    "text, expected_low",
    [
        # The reported failure: a burst of one repeated word dominates.
        ("I'm going to start with the " + ("new " * 30) + "geographic and cloud", True),
        ("new " * 12, True),
        # A normal, varied explanation is never flagged.
        (
            "I built the risk-scoring API with FastAPI and a PostgreSQL database and "
            "wired the React front end to display routes on a map",
            False,
        ),
        # Short repeated-token hallucinations at the meaningful-speech threshold
        # must fail closed rather than be persisted as evidence.
        ("new new new", True),
        ("new new new new", True),
        ("hello hello hello", True),
        ("test test test", True),
        # Short but meaningful — distinct words that clear the meaningful-speech
        # gate — must still pass, not be over-blocked.
        ("backend route scoring", False),
        ("I built APIs", False),
        ("route risk model", False),
        # Below the meaningful-speech floor: owned by the no-speech gate.
        ("just two", False),
        ("", False),
    ],
)
def test_is_low_quality_transcript(text: str, expected_low: bool) -> None:
    from app.services.transcription_service import is_low_quality_transcript

    assert is_low_quality_transcript(text) is expected_low


def test_repeated_token_ratio_scores() -> None:
    from app.services.transcription_service import (
        consecutive_repeat_ratio,
        dominant_token_ratio,
        repeated_token_ratio,
    )

    assert repeated_token_ratio("") == 0.0
    # Five of nine tokens are "new" → dominant 5/9; four adjacent repeats / 8.
    assert dominant_token_ratio("the new new new new new the a b") == pytest.approx(5 / 9)
    assert consecutive_repeat_ratio("the new new new new new the a b") == pytest.approx(4 / 8)
    # A varied sentence stays well below the 0.5 threshold.
    assert repeated_token_ratio("I built an API and a database and a front end") < 0.5
