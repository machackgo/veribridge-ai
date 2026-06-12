"""Tests for the VBR keyframe-extraction skeleton (T5E)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app

USER_ID = "00000000-0000-0000-0000-000000000042"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000099"

_FAKE_FULL_VIDEO_BYTES = b"fake-full-session-video-bytes"
_FAKE_FRAME_BYTES = b"fake-jpeg-frame-bytes"


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


def _extract_keyframes(client: TestClient, session_id: str):
    return client.post(f"/api/v1/student/vbr/sessions/{session_id}/extract-keyframes")


def test_extract_keyframes_requires_owner(client: TestClient) -> None:
    _project_id, session_id = _setup_processed_session(client)

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = _extract_keyframes(client, session_id)

    assert response.status_code == 404


def test_extract_keyframes_requires_processed_status(client: TestClient) -> None:
    _project_id, session_id = _setup_session(client)

    response = _extract_keyframes(client, session_id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "vbr_session_not_processed"


def test_extract_keyframes_requires_full_video_telemetry(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_processed_session(client)

    # Simulate a processed session whose telemetry is missing the full-video entry.
    telemetry = mem_store["vbr_verification_sessions"][session_id]["telemetry"]
    del telemetry["media_processing"]["full_video"]

    response = _extract_keyframes(client, session_id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "vbr_session_full_video_missing"


def test_extract_keyframes_creates_keyframe_rows(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_processed_session(client)

    response = _extract_keyframes(client, session_id)

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["session_id"] == session_id
    assert body["status"] == "processed"
    assert body["frame_count"] == 8

    keyframes = [
        row for row in mem_store["vbr_keyframes"].values()
        if row["session_id"] == session_id
    ]
    assert len(keyframes) == 8
    assert all(row["storage_path"].startswith(f"vbr/sessions/{session_id}/frames/") for row in keyframes)
    assert all(row["ts_s"] > 0 for row in keyframes)

    session = mem_store["vbr_verification_sessions"][session_id]
    assert session["telemetry"]["keyframes"]["extracted"] is True
    assert session["telemetry"]["keyframes"]["frame_count"] == 8
    assert session["telemetry"]["keyframes"]["strategy"] == "interval"
    assert session["telemetry"]["keyframes"]["completed_at"]

    # Status/project untouched by keyframe extraction.
    assert session["status"] == "processed"
    project_after = client.get(f"/api/v1/student/vbr/projects/{_project_id}").json()
    assert project_after["status"] == "media_processed"


def test_extract_keyframes_is_idempotent_and_does_not_duplicate(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_processed_session(client)

    first = _extract_keyframes(client, session_id)
    assert first.status_code == 200, first.text

    second = _extract_keyframes(client, session_id)
    assert second.status_code == 200, second.text
    assert second.json()["frame_count"] == 8

    keyframes = [
        row for row in mem_store["vbr_keyframes"].values()
        if row["session_id"] == session_id
    ]
    assert len(keyframes) == 8


def test_extract_keyframes_response_does_not_expose_internals(client: TestClient) -> None:
    _project_id, session_id = _setup_processed_session(client)

    response = _extract_keyframes(client, session_id)

    assert response.status_code == 200, response.text
    raw = response.text
    assert "storage_path" not in raw
    assert "signed" not in raw
    assert "vbr/sessions" not in raw
    assert "frames/" not in raw
    assert "processed/full.webm" not in raw
    assert "tmp" not in raw.lower()
    assert "veribridge_vbr_keyframes" not in raw
    assert _FAKE_FRAME_BYTES.decode() not in raw


def test_extract_keyframes_uploads_frame_bytes_privately(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_processed_session(client)

    response = _extract_keyframes(client, session_id)

    assert response.status_code == 200, response.text

    media_objects = mem_store["_vbr_media_objects"]
    frame_paths = [
        path for path in media_objects
        if path.startswith(f"vbr/sessions/{session_id}/frames/")
    ]
    assert len(frame_paths) == 8
    for path in frame_paths:
        assert media_objects[path] == _FAKE_FRAME_BYTES


def test_extract_keyframes_failure_returns_controlled_error_and_leaves_status_safe(
    client: TestClient, mem_store: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project_id, session_id = _setup_processed_session(client)

    def _failing_extraction(_input_path, _timestamp_s, _output_path) -> None:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "vbr_keyframes_extraction_failed",
                "message": "Could not extract keyframes. Please try again.",
            },
        )

    monkeypatch.setattr("app.services.vbr_keyframes.run_ffmpeg_frame_extraction", _failing_extraction)

    response = _extract_keyframes(client, session_id)

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "vbr_keyframes_extraction_failed"

    session = mem_store["vbr_verification_sessions"][session_id]
    assert session["status"] == "processed"
    assert "keyframes" not in session["telemetry"]
    assert session_id not in {
        row["session_id"] for row in mem_store.get("vbr_keyframes", {}).values()
    }


def test_extract_keyframes_uses_configured_storage_client(client: TestClient, mem_store: dict, monkeypatch) -> None:
    from app.core.config import settings
    from app.services import vbr_keyframes

    project_id, session_id = _setup_processed_session(client)

    full_video_bytes = b"fake-full-video"
    frame_bytes = b"fake-jpeg-frame"

    def fake_extract_frames(_video_path, output_dir, _timestamps):
        frame_path = output_dir / "frame_000.jpg"
        frame_path.write_bytes(frame_bytes)
        return [frame_path]

    monkeypatch.setattr(vbr_keyframes, "extract_keyframe_files", fake_extract_frames)
    monkeypatch.setattr(vbr_keyframes, "compute_keyframe_timestamps", lambda _duration_s: [0.0])

    class FakeBucket:
        def __init__(self) -> None:
            self.uploaded: dict[str, bytes] = {}

        def download(self, _storage_path: str) -> bytes:
            return full_video_bytes

        def upload(self, storage_path: str, data: bytes, file_options=None):
            self.uploaded[storage_path] = data
            return {"path": storage_path}

    class FakeStorage:
        def __init__(self) -> None:
            self.bucket = FakeBucket()

        def from_(self, bucket_name: str):
            assert bucket_name == "test-vbr-media"
            return self.bucket

    class FakeTableQuery:
        def __init__(self, store: dict, table_name: str) -> None:
            self.store = store
            self.table_name = table_name
            self.filters: list[tuple[str, object]] = []
            self.insert_payload = None
            self.update_payload = None
            self.return_single = False

        def select(self, *_args, **_kwargs): return self
        def delete(self): self._delete = True; return self
        def insert(self, payload): self.insert_payload = payload; return self
        def update(self, payload): self.update_payload = payload; return self
        def eq(self, key, value): self.filters.append((key, value)); return self
        def order(self, *_args, **_kwargs): return self
        def maybe_single(self): self.return_single = True; return self

        def execute(self):
            table = self.store.setdefault(self.table_name, {})
            rows = list(table.values()) if isinstance(table, dict) else list(table)
            for key, value in self.filters:
                rows = [row for row in rows if row.get(key) == value]

            if getattr(self, "_delete", False):
                if isinstance(table, dict):
                    for row in list(rows):
                        table.pop(row["id"], None)
                return type("Result", (), {"data": rows})()

            if self.insert_payload is not None:
                payloads = self.insert_payload if isinstance(self.insert_payload, list) else [self.insert_payload]
                inserted = []
                for payload in payloads:
                    row = dict(payload)
                    row.setdefault("id", f"fake-{len(table)+1}")
                    if isinstance(table, dict):
                        table[row["id"]] = row
                    else:
                        table.append(row)
                    inserted.append(row)
                return type("Result", (), {"data": inserted})()

            if self.update_payload is not None:
                for row in rows:
                    row.update(self.update_payload)
                data = rows[0] if self.return_single and rows else rows
                return type("Result", (), {"data": data})()

            data = rows[0] if self.return_single and rows else rows
            return type("Result", (), {"data": data})()

    class FakeRealDb:
        def __init__(self, store):
            self.store = store
            self.storage = FakeStorage()

        def table(self, table_name: str):
            return FakeTableQuery(self.store, table_name)

    fake_db = FakeRealDb(mem_store)
    monkeypatch.setattr(settings, "supabase_vbr_media_bucket", "test-vbr-media")
    app.dependency_overrides[get_db] = lambda: fake_db

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/extract-keyframes")

    assert response.status_code == 200
    assert response.json()["frame_count"] == 1
    assert fake_db.storage.bucket.uploaded


def test_extract_keyframes_cleans_uploaded_frames_on_partial_upload_failure(client: TestClient, mem_store: dict, monkeypatch) -> None:
    from app.services import vbr_keyframes

    _project_id, session_id = _setup_processed_session(client)

    def fake_extract_frames(_video_path, output_dir, _timestamps):
        first = output_dir / "frame_000.jpg"
        second = output_dir / "frame_001.jpg"
        first.write_bytes(b"first-frame")
        second.write_bytes(b"second-frame")
        return [first, second]

    monkeypatch.setattr(vbr_keyframes, "extract_keyframe_files", fake_extract_frames)
    monkeypatch.setattr(vbr_keyframes, "compute_keyframe_timestamps", lambda _duration_s: [0.0, 10.0])

    original_upload = vbr_keyframes.upload_keyframe_image

    def flaky_upload(db, storage_path, image_bytes):
        if storage_path.endswith("/001.jpg"):
            raise HTTPException(
                status_code=500,
                detail={"code": "vbr_keyframe_upload_failed", "message": "fail"},
            )
        return original_upload(db, storage_path, image_bytes)

    monkeypatch.setattr(vbr_keyframes, "upload_keyframe_image", flaky_upload)

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/extract-keyframes")

    assert response.status_code == 500
    media_objects = mem_store.get("_vbr_media_objects", {})
    assert not any("/frames/" in storage_path for storage_path in media_objects)
    assert media_objects.get(f"vbr/sessions/{session_id}/processed/full.webm") == b"fake-full-session-video-bytes"
    assert not mem_store.get("vbr_keyframes")
