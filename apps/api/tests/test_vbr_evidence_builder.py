"""Tests for the VBR evidence-item builder (T6A)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app

USER_ID = "00000000-0000-0000-0000-000000000042"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000099"

_FAKE_FULL_VIDEO_BYTES = b"fake-full-session-video-bytes"
_FAKE_FRAME_BYTES = b"fake-jpeg-frame-bytes"

_SKELETON_SEGMENT_TEXTS = [
    "Candidate introduced the project and repository.",
    "Candidate explained a key implementation decision.",
]


def _fake_run_ffmpeg_concat(_manifest_path, output_path) -> None:
    """Deterministic stand-in for ffmpeg concat execution in tests."""
    output_path.write_bytes(_FAKE_FULL_VIDEO_BYTES)


def _fake_run_ffmpeg_frame_extraction(_input_path, _timestamp_s, output_path) -> None:
    """Deterministic stand-in for ffmpeg frame extraction in tests."""
    output_path.write_bytes(_FAKE_FRAME_BYTES)


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        "app.services.vbr_media_processing.run_ffmpeg_concat", _fake_run_ffmpeg_concat
    )
    monkeypatch.setattr(
        "app.services.vbr_keyframes.run_ffmpeg_frame_extraction", _fake_run_ffmpeg_frame_extraction
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


def _transcribe(client: TestClient, session_id: str) -> dict:
    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/transcribe")
    assert response.status_code == 200, response.text
    return response.json()


def _extract_keyframes(client: TestClient, session_id: str) -> dict:
    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/extract-keyframes")
    assert response.status_code == 200, response.text
    return response.json()


def _setup_evidence_ready_session(client: TestClient, chunk_count: int = 1) -> tuple[str, str]:
    """Create a processed session with a transcript and keyframes already extracted."""
    project_id, session_id = _setup_processed_session(client, chunk_count)
    _transcribe(client, session_id)
    _extract_keyframes(client, session_id)
    return project_id, session_id


def _build_evidence(client: TestClient, session_id: str):
    return client.post(f"/api/v1/student/vbr/sessions/{session_id}/build-evidence")


def test_build_evidence_requires_owner(client: TestClient) -> None:
    _project_id, session_id = _setup_evidence_ready_session(client)

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = _build_evidence(client, session_id)

    assert response.status_code == 404


def test_build_evidence_requires_processed_session(client: TestClient) -> None:
    _project_id, session_id = _setup_session(client)

    response = _build_evidence(client, session_id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "vbr_session_not_processed"


def test_build_evidence_requires_transcript_and_keyframes(client: TestClient) -> None:
    _project_id, session_id = _setup_processed_session(client)

    # Neither transcript nor keyframes exist yet.
    response = _build_evidence(client, session_id)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_evidence_transcript_missing"

    # Transcript exists, but keyframes do not.
    _transcribe(client, session_id)
    response = _build_evidence(client, session_id)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_evidence_keyframes_missing"

    # Both exist: build-evidence succeeds.
    _extract_keyframes(client, session_id)
    response = _build_evidence(client, session_id)
    assert response.status_code == 200, response.text


def test_build_evidence_creates_transcript_segment_evidence(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_evidence_ready_session(client)

    response = _build_evidence(client, session_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_counts"]["transcript_segment"] == 2

    rows = [
        row
        for row in mem_store["vbr_evidence_items"].values()
        if row["evidence_type"] == "transcript_segment" and row["pointer"]["session_id"] == session_id
    ]
    assert len(rows) == 2
    for row in rows:
        assert row["project_id"] == _project_id
        assert row["evidence_class"] == "process"
        assert row["interpretation"] == "deterministic"
        assert row["sensitivity"] == "sensitive"
        assert "start_s" in row["pointer"]
        assert "end_s" in row["pointer"]
        assert len(row["summary"]) <= 200


def test_build_evidence_creates_keyframe_evidence_without_storage_path_in_response(
    client: TestClient, mem_store: dict
) -> None:
    _project_id, session_id = _setup_evidence_ready_session(client)

    response = _build_evidence(client, session_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_counts"]["keyframe"] == 8

    rows = [
        row
        for row in mem_store["vbr_evidence_items"].values()
        if row["evidence_type"] == "keyframe" and row["pointer"]["session_id"] == session_id
    ]
    assert len(rows) == 8
    for row in rows:
        assert row["project_id"] == _project_id
        assert row["evidence_class"] == "process"
        assert row["sensitivity"] == "sensitive"
        # storage_path may live in internal pointer metadata only.
        assert row["pointer"]["storage_path"].startswith(f"vbr/sessions/{session_id}/frames/")

    raw = response.text
    assert "storage_path" not in raw
    assert "vbr/sessions" not in raw
    assert "frames/" not in raw


def test_build_evidence_creates_question_evidence(client: TestClient, mem_store: dict) -> None:
    project_id, session_id = _setup_evidence_ready_session(client)

    response = _build_evidence(client, session_id)
    assert response.status_code == 200, response.text
    body = response.json()

    questions_response = client.get(f"/api/v1/student/vbr/sessions/{session_id}")
    assert questions_response.status_code == 200, questions_response.text
    question_count = len(questions_response.json()["questions"])
    assert question_count > 0
    assert body["source_counts"]["question"] == question_count

    rows = [
        row
        for row in mem_store["vbr_evidence_items"].values()
        if row["evidence_type"] == "session_telemetry"
        and row["source"] == "vbr_session_questions"
        and row["pointer"]["session_id"] == session_id
    ]
    assert len(rows) == question_count
    for row in rows:
        assert row["project_id"] == project_id
        assert "question_id" in row["pointer"]
        assert "sort_order" in row["pointer"]
        assert "claim_ids" in row["pointer"]


def test_build_evidence_creates_media_processing_evidence(client: TestClient, mem_store: dict) -> None:
    project_id, session_id = _setup_evidence_ready_session(client)

    response = _build_evidence(client, session_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_counts"]["media_processing"] == 1

    rows = [
        row
        for row in mem_store["vbr_evidence_items"].values()
        if row["evidence_type"] == "session_telemetry"
        and row["source"] == "vbr_verification_sessions.telemetry"
        and row["pointer"]["session_id"] == session_id
    ]
    assert len(rows) == 1
    pointer = rows[0]["pointer"]
    assert pointer["manifest_verified"] is True
    assert pointer["full_video_created"] is True
    assert pointer["transcript_extracted"] is True
    assert pointer["keyframes_extracted"] is True
    assert rows[0]["project_id"] == project_id


def test_build_evidence_is_idempotent_and_does_not_duplicate(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_evidence_ready_session(client)

    first = _build_evidence(client, session_id)
    assert first.status_code == 200, first.text
    first_count = first.json()["evidence_count"]

    second = _build_evidence(client, session_id)
    assert second.status_code == 200, second.text
    second_count = second.json()["evidence_count"]

    assert first_count == second_count

    rows = [
        row
        for row in mem_store["vbr_evidence_items"].values()
        if row["pointer"].get("session_id") == session_id
    ]
    assert len(rows) == first_count


def test_build_evidence_response_does_not_expose_internals(client: TestClient) -> None:
    _project_id, session_id = _setup_evidence_ready_session(client)

    response = _build_evidence(client, session_id)

    assert response.status_code == 200, response.text
    raw = response.text
    assert "storage_path" not in raw
    assert "signed" not in raw
    assert "vbr/sessions" not in raw
    assert "processed/full.webm" not in raw
    assert "tmp" not in raw.lower()
    for text in _SKELETON_SEGMENT_TEXTS:
        assert text not in raw


def test_build_evidence_includes_repo_analysis_evidence(client: TestClient, mem_store: dict) -> None:
    project_id, session_id = _setup_evidence_ready_session(client)

    response = _build_evidence(client, session_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_counts"]["repo_analysis"] == 1

    rows = [
        row
        for row in mem_store["vbr_evidence_items"].values()
        if row["evidence_type"] == "repo_stat" and row["pointer"]["session_id"] == session_id
    ]
    assert len(rows) == 1
    assert rows[0]["project_id"] == project_id
    assert rows[0]["evidence_class"] == "artifact"


def test_build_evidence_total_count_matches_source_counts(client: TestClient) -> None:
    _project_id, session_id = _setup_evidence_ready_session(client)

    response = _build_evidence(client, session_id)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["session_id"] == session_id
    assert body["status"] == "processed"
    assert sum(body["source_counts"].values()) == body["evidence_count"]


def test_build_evidence_rejects_when_transcript_row_missing(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_evidence_ready_session(client)
    mem_store["vbr_transcripts"].clear()
    mem_store["vbr_transcript_segments"].clear()

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/build-evidence")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_evidence_transcript_missing"


def test_build_evidence_rejects_when_transcript_segments_missing(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_evidence_ready_session(client)
    mem_store["vbr_transcript_segments"].clear()

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/build-evidence")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_evidence_transcript_missing"


def test_build_evidence_rejects_when_keyframe_rows_missing(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_evidence_ready_session(client)
    mem_store["vbr_keyframes"].clear()

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/build-evidence")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_evidence_keyframes_missing"
