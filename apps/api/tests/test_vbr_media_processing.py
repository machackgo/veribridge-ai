"""Tests for the VBR uploaded-session media-processing skeleton (T5A + T5B)."""

from __future__ import annotations

import hashlib
import shutil

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.vbr_media_processing import (
    build_chunk_local_path,
    build_ffmpeg_remux_command,
    build_processing_work_dir,
    download_session_chunks_to_workdir,
    fake_chunk_bytes,
    ffmpeg_available,
    measure_media_duration_seconds,
    reassemble_chunks_into_stream,
    run_ffmpeg_concat,
    upload_processed_full_video,
    verify_full_video_output,
)

USER_ID = "00000000-0000-0000-0000-000000000042"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000099"

_FAKE_FULL_VIDEO_BYTES = b"fake-full-session-video-bytes"


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
    assert body["full_video_bytes"] == len(_FAKE_FULL_VIDEO_BYTES)
    assert body["full_video_sha256"] == hashlib.sha256(_FAKE_FULL_VIDEO_BYTES).hexdigest()
    assert body["next_steps"] == ["transcribe_audio", "extract_keyframes"]

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
    assert "processed/full.webm" not in raw
    assert "tmp" not in raw.lower()
    assert "veribridge_vbr_processing" not in raw


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
    assert media_processing["next_steps"] == ["transcribe_audio", "extract_keyframes"]

    assert media_processing["full_video_created"] is True
    assert media_processing["full_video_bytes"] == len(_FAKE_FULL_VIDEO_BYTES)
    assert media_processing["full_video_sha256"] == hashlib.sha256(_FAKE_FULL_VIDEO_BYTES).hexdigest()

    full_video = media_processing["full_video"]
    assert full_video["storage_path"] == f"vbr/sessions/{session_id}/processed/full.webm"
    assert full_video["bytes"] == len(_FAKE_FULL_VIDEO_BYTES)
    assert full_video["sha256"] == hashlib.sha256(_FAKE_FULL_VIDEO_BYTES).hexdigest()
    assert full_video["created_at"]


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


# ── T5B: storage download + concat preparation ──────────────────────────────


def test_process_downloads_and_verifies_chunks(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_uploaded_session(client, chunk_count=2)

    response = _process(client, session_id)

    assert response.status_code == 200, response.text

    media_processing = mem_store["vbr_verification_sessions"][session_id]["telemetry"]["media_processing"]
    assert media_processing["chunks_downloaded"] is True
    assert media_processing["download_verified"] is True
    assert media_processing["chunks_reassembled"] is True


def test_process_rejects_downloaded_hash_mismatch(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_uploaded_session(client, chunk_count=1)

    chunk = next(iter(mem_store["vbr_video_chunks"].values()))
    # Valid sha256 format, but does not match the (deterministic) downloaded bytes.
    chunk["sha256"] = "b" * 64

    response = _process(client, session_id)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_media_chunk_hash_mismatch"
    assert mem_store["vbr_verification_sessions"][session_id]["status"] == "uploaded"


def test_process_rejects_downloaded_size_mismatch(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_uploaded_session(client, chunk_count=1)

    chunk = next(iter(mem_store["vbr_video_chunks"].values()))
    storage_path = chunk["storage_path"]

    # Simulate stored bytes whose length doesn't match the recorded chunk size.
    blob = fake_chunk_bytes(session_id, 0, 2048)
    mem_store.setdefault("vbr_video_chunk_blobs", {})[storage_path] = blob
    chunk["sha256"] = hashlib.sha256(blob).hexdigest()

    response = _process(client, session_id)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_media_chunk_size_mismatch"
    assert mem_store["vbr_verification_sessions"][session_id]["status"] == "uploaded"


def test_reassemble_chunks_into_stream_byte_concatenates_in_order(tmp_path) -> None:
    """MediaRecorder continuation fragments must be rebuilt by ordered raw byte
    concatenation — the single header chunk followed by every headerless
    continuation, byte-for-byte, with nothing dropped."""
    work_dir = tmp_path / "session-abc"
    work_dir.mkdir()

    # chunk 0 = header fragment; chunks 1..2 = headerless continuation fragments.
    fragments = [b"WEBM-HEADER+cluster0", b"cluster1-bytes", b"cluster2-bytes"]
    local_paths = []
    for chunk_index, fragment in enumerate(fragments):
        path = build_chunk_local_path(work_dir, chunk_index)
        path.write_bytes(fragment)
        local_paths.append(path)

    output_path = work_dir / "reassembled.webm"
    reassemble_chunks_into_stream(local_paths, output_path)

    # Exact byte-concatenation in order — this is what the ffmpeg concat demuxer
    # failed to do (it kept only the first fragment).
    assert output_path.read_bytes() == b"".join(fragments)


def test_download_fails_closed_without_configured_bucket() -> None:
    """Real (non-dict) DBs must fail closed if the media bucket isn't configured."""

    class _FakeRealDb:
        """Stand-in for a real Supabase client with no storage configured."""

    session_id = "fake-session-id"
    chunks = [
        {
            "chunk_index": 0,
            "storage_path": f"vbr/sessions/{session_id}/chunks/000.webm",
            "bytes": 1024,
            "sha256": "a" * 64,
        }
    ]

    try:
        with pytest.raises(HTTPException) as exc_info:
            download_session_chunks_to_workdir(_FakeRealDb(), session_id, chunks)

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["code"] == "vbr_media_bucket_not_configured"
    finally:
        shutil.rmtree(build_processing_work_dir(session_id), ignore_errors=True)


def test_process_downloads_from_configured_storage_client(client: TestClient, mem_store: dict, monkeypatch) -> None:
    import hashlib
    from app.core.config import settings

    project_id, session_id = _setup_uploaded_session(client)
    chunk = next(iter(mem_store["vbr_video_chunks"].values()))
    chunk_bytes = b"configured-storage-client-bytes"
    chunk["bytes"] = len(chunk_bytes)
    chunk["sha256"] = hashlib.sha256(chunk_bytes).hexdigest()

    class FakeBucket:
        def __init__(self) -> None:
            self.downloaded_paths: list[str] = []
            self.uploaded: dict[str, bytes] = {}

        def download(self, storage_path: str) -> bytes:
            self.downloaded_paths.append(storage_path)
            return chunk_bytes

        def upload(self, storage_path: str, data: bytes, file_options: dict | None = None) -> None:
            self.uploaded[storage_path] = bytes(data)

    class FakeStorage:
        def __init__(self) -> None:
            self.bucket = FakeBucket()

        def from_(self, bucket_name: str) -> FakeBucket:
            assert bucket_name == "test-vbr-media"
            return self.bucket

    class FakeTableQuery:
        def __init__(self, store: dict, table_name: str) -> None:
            self.store = store
            self.table_name = table_name
            self.filters: list[tuple[str, object]] = []
            self.update_payload: dict | None = None
            self.return_single = False

        def select(self, *_args, **_kwargs):
            return self

        def update(self, payload: dict):
            self.update_payload = payload
            return self

        def eq(self, key: str, value: object):
            self.filters.append((key, value))
            return self

        def order(self, *_args, **_kwargs):
            return self

        def execute(self):
            table = self.store[self.table_name]
            rows = list(table.values()) if isinstance(table, dict) else list(table)

            for key, value in self.filters:
                rows = [row for row in rows if row.get(key) == value]

            if self.update_payload is not None:
                for row in rows:
                    row.update(self.update_payload)
                data = rows[0] if self.return_single and rows else rows
                return type("Result", (), {"data": data})()

            data = rows[0] if self.return_single and rows else rows
            return type("Result", (), {"data": data})()

        def maybe_single(self):
            self.return_single = True
            return self

        def single(self):
            result = self.execute()
            data = result.data[0] if result.data else None
            return type("SingleResult", (), {"data": data})()

    class FakeRealDb:
        def __init__(self, store: dict) -> None:
            self._store = store
            self.storage = FakeStorage()

        def table(self, table_name: str):
            return FakeTableQuery(self._store, table_name)

    monkeypatch.setattr(settings, "supabase_vbr_media_bucket", "test-vbr-media")
    fake_db = FakeRealDb(mem_store)
    app.dependency_overrides[get_db] = lambda: fake_db

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/process")

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert mem_store["vbr_verification_sessions"][session_id]["status"] == "processed"
    assert mem_store["vbr_projects"][project_id]["status"] == "media_processed"

    expected_storage_path = f"vbr/sessions/{session_id}/processed/full.webm"
    assert fake_db.storage.bucket.uploaded[expected_storage_path] == _FAKE_FULL_VIDEO_BYTES


# ── T5C: ffmpeg concat execution + full video upload ────────────────────────


def test_process_ffmpeg_failure_returns_controlled_error_and_leaves_status_unchanged(
    client: TestClient, mem_store: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id, session_id = _setup_uploaded_session(client, chunk_count=1)

    def _failing_concat(_manifest_path, _output_path) -> None:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "vbr_media_concat_failed",
                "message": "Could not assemble the recording. Please try again.",
            },
        )

    monkeypatch.setattr("app.services.vbr_media_processing.run_ffmpeg_concat", _failing_concat)

    response = _process(client, session_id)

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "vbr_media_concat_failed"
    assert "Could not assemble the recording" in response.json()["detail"]["message"]

    assert mem_store["vbr_verification_sessions"][session_id]["status"] == "uploaded"
    assert mem_store["vbr_projects"][project_id]["status"] != "media_processed"


def test_verify_full_video_output_computes_sha256_from_bytes(tmp_path) -> None:
    output_path = tmp_path / "full.webm"
    data = b"some-full-session-video-bytes"
    output_path.write_bytes(data)

    summary = verify_full_video_output(output_path)

    assert summary["bytes"] == len(data)
    assert summary["sha256"] == hashlib.sha256(data).hexdigest()


def test_fake_db_upload_stores_full_video_bytes(tmp_path) -> None:
    mem_store: dict = {}
    output_path = tmp_path / "full.webm"
    output_path.write_bytes(_FAKE_FULL_VIDEO_BYTES)

    storage_path = upload_processed_full_video(mem_store, "session-xyz", output_path)

    assert storage_path == "vbr/sessions/session-xyz/processed/full.webm"
    assert mem_store["_vbr_media_objects"][storage_path] == _FAKE_FULL_VIDEO_BYTES


def test_upload_full_video_fails_closed_without_configured_bucket(tmp_path) -> None:
    """Real (non-dict) DBs must fail closed if the media bucket isn't configured."""

    class _FakeRealDb:
        """Stand-in for a real Supabase client with no storage configured."""

    output_path = tmp_path / "full.webm"
    output_path.write_bytes(_FAKE_FULL_VIDEO_BYTES)

    with pytest.raises(HTTPException) as exc_info:
        upload_processed_full_video(_FakeRealDb(), "fake-session-id", output_path)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "vbr_media_bucket_not_configured"


def test_build_ffmpeg_remux_command_is_single_input_not_concat_demuxer(tmp_path) -> None:
    input_path = tmp_path / "reassembled.webm"
    output_path = tmp_path / "full.webm"

    command = build_ffmpeg_remux_command(input_path, output_path)

    assert isinstance(command, list)
    assert all(isinstance(part, str) for part in command)
    assert command[0] == "ffmpeg"
    assert "-c" in command and "copy" in command
    # Single-input remux of the byte-reassembled stream, NOT the concat demuxer.
    assert "concat" not in command
    assert command.count("-i") == 1
    assert str(input_path) in command
    assert str(output_path) in command


def test_duration_validation_fails_loudly_on_truncation(monkeypatch, tmp_path) -> None:
    """If the remuxed output loses most of the reassembled stream's duration
    (the ~81s → ~9s regression), assembly must fail with the controlled concat
    error instead of silently continuing to transcription."""
    from app.services import vbr_media_processing as mp

    measured = iter([81.02, 9.33])  # (reassembled input, remuxed output)
    monkeypatch.setattr(mp, "measure_media_duration_seconds", lambda _path: next(measured))

    with pytest.raises(HTTPException) as exc_info:
        mp._validate_reassembled_duration(tmp_path / "reassembled.webm", tmp_path / "full.webm")

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail["code"] == "vbr_media_concat_failed"


def test_duration_validation_passes_when_duration_preserved(monkeypatch, tmp_path) -> None:
    from app.services import vbr_media_processing as mp

    measured = iter([81.02, 80.4])  # remux preserved essentially all duration
    monkeypatch.setattr(mp, "measure_media_duration_seconds", lambda _path: next(measured))

    # Must not raise.
    mp._validate_reassembled_duration(tmp_path / "reassembled.webm", tmp_path / "full.webm")


def test_duration_validation_skips_when_reference_too_short(monkeypatch, tmp_path) -> None:
    """A genuinely tiny reassembled clip is below the judgement floor, so the
    ratio guard is skipped rather than risk a false truncation failure."""
    from app.services import vbr_media_processing as mp

    measured = iter([1.2, 0.1])  # input under _DURATION_CHECK_FLOOR_SECONDS
    monkeypatch.setattr(mp, "measure_media_duration_seconds", lambda _path: next(measured))

    # Must not raise despite the low output/input ratio.
    mp._validate_reassembled_duration(tmp_path / "reassembled.webm", tmp_path / "full.webm")


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg is required for this regression test")
def test_run_ffmpeg_concat_reassembles_full_duration_from_fragments(tmp_path) -> None:
    """End-to-end regression for the MediaRecorder fragment-concatenation bug.

    Synthesise ONE real ~6s WebM stream, then split it into a header chunk plus
    headerless continuation fragments exactly the way MediaRecorder's timeslice
    does (byte ranges of a single stream). run_ffmpeg_concat must byte-reassemble
    them and produce a full ~6s recording — NOT the truncated first fragment the
    old ffmpeg concat demuxer emitted.
    """
    import subprocess

    source = tmp_path / "source.webm"
    subprocess.run(
        [
            "ffmpeg", "-y", "-nostdin",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
            "-c:a", "libopus",
            "-f", "webm",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    source_bytes = source.read_bytes()
    source_duration = measure_media_duration_seconds(source)
    assert source_duration is not None and source_duration >= 5.0

    # Split the single stream into 4 byte ranges: fragment 0 keeps the WebM
    # header; fragments 1..3 are headerless continuations (not standalone files).
    n_parts = 4
    step = len(source_bytes) // n_parts
    local_paths = []
    for chunk_index in range(n_parts):
        start = chunk_index * step
        end = len(source_bytes) if chunk_index == n_parts - 1 else start + step
        path = build_chunk_local_path(tmp_path, chunk_index)
        path.write_bytes(source_bytes[start:end])
        local_paths.append(path)

    # A single continuation fragment is NOT decodable on its own — proof that the
    # concat demuxer (one file at a time) could only ever recover the first one.
    assert measure_media_duration_seconds(local_paths[1]) in (None, 0.0)

    output_path = tmp_path / "full.webm"
    run_ffmpeg_concat(local_paths, output_path)

    assert output_path.is_file() and output_path.stat().st_size > 0
    output_duration = measure_media_duration_seconds(output_path)
    assert output_duration is not None
    # Full recording recovered (~6s), not truncated to the first fragment (~1.5s).
    assert output_duration >= source_duration * 0.9


def test_process_fails_if_full_video_upload_returns_error(client: TestClient, mem_store: dict, monkeypatch) -> None:
    import hashlib
    from app.core.config import settings
    from app.services import vbr_media_processing

    project_id, session_id = _setup_uploaded_session(client)
    chunk = next(iter(mem_store["vbr_video_chunks"].values()))
    chunk_bytes = b"chunk-for-upload-error-test"
    chunk["bytes"] = len(chunk_bytes)
    chunk["sha256"] = hashlib.sha256(chunk_bytes).hexdigest()

    def fake_run_ffmpeg_concat(_manifest_path, output_path):
        output_path.write_bytes(b"assembled-video-bytes")

    monkeypatch.setattr(vbr_media_processing, "run_ffmpeg_concat", fake_run_ffmpeg_concat)

    class FakeBucket:
        def download(self, _storage_path: str) -> bytes:
            return chunk_bytes

        def upload(self, *_args, **_kwargs):
            return {"error": {"message": "simulated storage failure with hidden path"}}

    class FakeStorage:
        def from_(self, _bucket_name: str) -> FakeBucket:
            return FakeBucket()

    class FakeTableQuery:
        def __init__(self, store: dict, table_name: str) -> None:
            self.store = store
            self.table_name = table_name
            self.filters: list[tuple[str, object]] = []
            self.update_payload: dict | None = None
            self.return_single = False

        def select(self, *_args, **_kwargs):
            return self

        def update(self, payload: dict):
            self.update_payload = payload
            return self

        def eq(self, key: str, value: object):
            self.filters.append((key, value))
            return self

        def order(self, *_args, **_kwargs):
            return self

        def maybe_single(self):
            self.return_single = True
            return self

        def execute(self):
            table = self.store[self.table_name]
            rows = list(table.values()) if isinstance(table, dict) else list(table)
            for key, value in self.filters:
                rows = [row for row in rows if row.get(key) == value]
            if self.update_payload is not None:
                for row in rows:
                    row.update(self.update_payload)
                data = rows[0] if self.return_single and rows else rows
                return type("Result", (), {"data": data})()
            data = rows[0] if self.return_single and rows else rows
            return type("Result", (), {"data": data})()

    class FakeRealDb:
        storage = FakeStorage()

        def table(self, table_name: str):
            return FakeTableQuery(mem_store, table_name)

    monkeypatch.setattr(settings, "supabase_vbr_media_bucket", "test-vbr-media")
    app.dependency_overrides[get_db] = lambda: FakeRealDb()

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/process")

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "vbr_media_full_video_upload_failed"
    assert mem_store["vbr_verification_sessions"][session_id]["status"] == "uploaded"
    assert mem_store["vbr_projects"][project_id]["status"] != "media_processed"
