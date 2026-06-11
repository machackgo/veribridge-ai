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
    build_ffmpeg_concat_manifest,
    build_processing_work_dir,
    download_session_chunks_to_workdir,
    fake_chunk_bytes,
)

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


# ── T5B: storage download + concat preparation ──────────────────────────────


def test_process_downloads_and_verifies_chunks(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_uploaded_session(client, chunk_count=2)

    response = _process(client, session_id)

    assert response.status_code == 200, response.text

    media_processing = mem_store["vbr_verification_sessions"][session_id]["telemetry"]["media_processing"]
    assert media_processing["chunks_downloaded"] is True
    assert media_processing["download_verified"] is True
    assert media_processing["concat_manifest_created"] is True


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


def test_build_ffmpeg_concat_manifest_uses_safe_local_paths(tmp_path) -> None:
    work_dir = tmp_path / "session-abc"
    work_dir.mkdir()

    local_paths = []
    for chunk_index in range(2):
        path = build_chunk_local_path(work_dir, chunk_index)
        path.write_bytes(b"x")
        local_paths.append(path)

    manifest_path = build_ffmpeg_concat_manifest(local_paths, work_dir)

    assert manifest_path.parent == work_dir
    content = manifest_path.read_text()
    for path in local_paths:
        assert f"file '{path.as_posix()}'" in content


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

        def download(self, storage_path: str) -> bytes:
            self.downloaded_paths.append(storage_path)
            return chunk_bytes

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
    app.dependency_overrides[get_db] = lambda: FakeRealDb(mem_store)

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/process")

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert mem_store["vbr_verification_sessions"][session_id]["status"] == "processed"
    assert mem_store["vbr_projects"][project_id]["status"] == "media_processed"
