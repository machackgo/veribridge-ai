"""Tests for the VBR report review/publish backend flow (T7A)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app

USER_ID = "00000000-0000-0000-0000-000000000042"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000099"


def _fake_run_ffmpeg_concat(_manifest_path, output_path) -> None:
    """Deterministic stand-in for ffmpeg concat execution in tests."""
    output_path.write_bytes(b"fake-full-session-video-bytes")


def _fake_run_ffmpeg_frame_extraction(_input_path, _timestamp_s, output_path) -> None:
    """Deterministic stand-in for ffmpeg frame extraction in tests."""
    output_path.write_bytes(b"fake-jpeg-frame-bytes")


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


def _setup_judgment_ready_session(client: TestClient, chunk_count: int = 1) -> tuple[str, str]:
    """Create a session with evidence items already built (ready for /judge)."""
    project_id, session_id = _setup_evidence_ready_session(client, chunk_count)
    evidence_response = _build_evidence(client, session_id)
    assert evidence_response.status_code == 200, evidence_response.text
    return project_id, session_id


def _judge(client: TestClient, session_id: str):
    return client.post(f"/api/v1/student/vbr/sessions/{session_id}/judge")


def _setup_report_ready_session(client: TestClient, chunk_count: int = 1) -> tuple[str, str]:
    """Create a session with a judgment skeleton already built (ready for /draft-report)."""
    project_id, session_id = _setup_judgment_ready_session(client, chunk_count)
    judge_response = _judge(client, session_id)
    assert judge_response.status_code == 200, judge_response.text
    return project_id, session_id


def _draft_report(client: TestClient, session_id: str):
    return client.post(f"/api/v1/student/vbr/sessions/{session_id}/draft-report")


def _setup_draft_report(client: TestClient, chunk_count: int = 1) -> tuple[str, str, str]:
    """Create a session with a private report draft (ready for review/publish)."""
    project_id, session_id = _setup_report_ready_session(client, chunk_count)
    draft_response = _draft_report(client, session_id)
    assert draft_response.status_code == 200, draft_response.text
    return project_id, session_id, draft_response.json()["report_id"]


def _submit_review(client: TestClient, session_id: str):
    return client.post(f"/api/v1/student/vbr/sessions/{session_id}/submit-report-review")


def _publish(client: TestClient, session_id: str):
    return client.post(f"/api/v1/student/vbr/sessions/{session_id}/publish-report")


def _unpublish(client: TestClient, session_id: str):
    return client.post(f"/api/v1/student/vbr/sessions/{session_id}/unpublish-report")


def _report_status(client: TestClient, session_id: str):
    return client.get(f"/api/v1/student/vbr/sessions/{session_id}/report-status")


# ── submit-report-review ─────────────────────────────────────────────────────


def test_submit_review_requires_owner(client: TestClient) -> None:
    _project_id, session_id, _report_id = _setup_draft_report(client)

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = _submit_review(client, session_id)

    assert response.status_code == 404


def test_submit_review_requires_draft_report(client: TestClient) -> None:
    # /draft-report has not been called yet.
    _project_id, session_id = _setup_report_ready_session(client)

    response = _submit_review(client, session_id)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "vbr_report_not_found"


def test_submit_review_requires_report_in_draft_status(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id, report_id = _setup_draft_report(client)

    mem_store["vbr_reports"][report_id]["status"] = "published"

    response = _submit_review(client, session_id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "vbr_report_not_draft"


def test_submit_review_sets_status_in_review(client: TestClient, mem_store: dict) -> None:
    project_id, session_id, report_id = _setup_draft_report(client)

    response = _submit_review(client, session_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == session_id
    assert body["report_id"] == report_id
    assert body["status"] == "in_review"

    report_row = mem_store["vbr_reports"][report_id]
    assert report_row["status"] == "in_review"
    assert report_row["public_token"] is None

    # Project status advances without invalidating the report draft.
    project_row = mem_store["vbr_projects"][project_id]
    assert project_row["status"] == "in_review"

    # Idempotent: calling again while already in_review succeeds and is a no-op.
    second = _submit_review(client, session_id)
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "in_review"


# ── publish-report ───────────────────────────────────────────────────────────


def test_publish_requires_report_body(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id, report_id = _setup_draft_report(client)
    _submit_review(client, session_id)

    mem_store["vbr_reports"][report_id]["body"] = None

    response = _publish(client, session_id)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "vbr_report_not_found"


def test_publish_requires_report_claims(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id, report_id = _setup_draft_report(client)
    _submit_review(client, session_id)

    mem_store["vbr_report_claims"] = {
        claim_id: claim
        for claim_id, claim in mem_store["vbr_report_claims"].items()
        if claim["report_id"] != report_id
    }

    response = _publish(client, session_id)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_report_claims_missing"


def test_publish_refuses_unsafe_body(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id, report_id = _setup_draft_report(client)
    _submit_review(client, session_id)

    mem_store["vbr_reports"][report_id]["body"]["storage_path"] = (
        f"vbr/sessions/{session_id}/chunks/000.webm"
    )

    response = _publish(client, session_id)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_report_unsafe_body"

    # Report must remain unpublished after a rejected publish attempt.
    assert mem_store["vbr_reports"][report_id]["status"] == "in_review"
    assert mem_store["vbr_reports"][report_id]["public_token"] is None


def test_publish_creates_public_token_only_at_publish_time(client: TestClient, mem_store: dict) -> None:
    project_id, session_id, report_id = _setup_draft_report(client)

    # No public token exists for the draft.
    assert mem_store["vbr_reports"][report_id]["public_token"] is None

    _submit_review(client, session_id)
    assert mem_store["vbr_reports"][report_id]["public_token"] is None

    response = _publish(client, session_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == session_id
    assert body["report_id"] == report_id
    assert body["status"] == "published"
    assert body["public_token_created"] is True

    report_row = mem_store["vbr_reports"][report_id]
    assert report_row["status"] == "published"
    assert report_row["public_token"]
    assert isinstance(report_row["public_token"], str)
    assert report_row["published_at"]

    project_row = mem_store["vbr_projects"][project_id]
    assert project_row["status"] == "published"


def test_publish_response_does_not_expose_internals(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id, report_id = _setup_draft_report(client)
    _submit_review(client, session_id)

    response = _publish(client, session_id)

    assert response.status_code == 200, response.text
    raw = response.text
    public_token = mem_store["vbr_reports"][report_id]["public_token"]

    assert public_token not in raw
    assert '"public_token"' not in raw
    assert "storage_path" not in raw
    assert "signed" not in raw
    assert "vbr/sessions" not in raw
    assert "tmp" not in raw.lower()
    assert "body" not in raw
    assert "claims" not in raw

    body = response.json()
    assert set(body.keys()) == {
        "session_id",
        "report_id",
        "status",
        "public_token_created",
        "message",
    }


def test_publish_is_idempotent_and_does_not_regenerate_token(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id, report_id = _setup_draft_report(client)
    _submit_review(client, session_id)

    first = _publish(client, session_id)
    assert first.status_code == 200, first.text
    first_token = mem_store["vbr_reports"][report_id]["public_token"]
    first_published_at = mem_store["vbr_reports"][report_id]["published_at"]

    second = _publish(client, session_id)
    assert second.status_code == 200, second.text
    second_body = second.json()

    assert second_body["status"] == "published"
    assert second_body["public_token_created"] is True

    report_row = mem_store["vbr_reports"][report_id]
    assert report_row["public_token"] == first_token
    assert report_row["published_at"] == first_published_at


def test_publish_does_not_modify_report_body(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id, report_id = _setup_draft_report(client)
    _submit_review(client, session_id)

    body_before = mem_store["vbr_reports"][report_id]["body"]
    import copy

    snapshot = copy.deepcopy(body_before)

    response = _publish(client, session_id)
    assert response.status_code == 200, response.text

    body_after = mem_store["vbr_reports"][report_id]["body"]
    assert body_after == snapshot


# ── unpublish-report ──────────────────────────────────────────────────────────


def test_unpublish_requires_published_report(client: TestClient) -> None:
    _project_id, session_id, _report_id = _setup_draft_report(client)
    _submit_review(client, session_id)

    response = _unpublish(client, session_id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "vbr_report_not_published"


def test_unpublish_clears_public_token_and_sets_status(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id, report_id = _setup_draft_report(client)
    _submit_review(client, session_id)
    publish_response = _publish(client, session_id)
    assert publish_response.status_code == 200, publish_response.text

    response = _unpublish(client, session_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == session_id
    assert body["report_id"] == report_id
    assert body["status"] == "unpublished"

    report_row = mem_store["vbr_reports"][report_id]
    assert report_row["status"] == "unpublished"
    assert report_row["public_token"] is None

    # Report body must not be deleted.
    assert report_row["body"]

    # Idempotent: calling again while already unpublished succeeds and is a no-op.
    second = _unpublish(client, session_id)
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "unpublished"
    assert mem_store["vbr_reports"][report_id]["public_token"] is None


def test_unpublish_requires_owner(client: TestClient) -> None:
    _project_id, session_id, _report_id = _setup_draft_report(client)
    _submit_review(client, session_id)
    _publish(client, session_id)

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = _unpublish(client, session_id)

    assert response.status_code == 404


# ── report-status ─────────────────────────────────────────────────────────────


def test_report_status_requires_owner(client: TestClient) -> None:
    _project_id, session_id, _report_id = _setup_draft_report(client)

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = _report_status(client, session_id)

    assert response.status_code == 404


def test_report_status_does_not_expose_token_or_body(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id, report_id = _setup_draft_report(client)
    _submit_review(client, session_id)
    publish_response = _publish(client, session_id)
    assert publish_response.status_code == 200, publish_response.text

    response = _report_status(client, session_id)

    assert response.status_code == 200, response.text
    raw = response.text
    public_token = mem_store["vbr_reports"][report_id]["public_token"]

    assert public_token not in raw
    assert '"public_token"' not in raw
    assert "body" not in raw
    assert "storage_path" not in raw

    body = response.json()
    assert set(body.keys()) == {
        "session_id",
        "report_id",
        "status",
        "has_public_token",
        "claim_count",
        "updated_at",
        "published_at",
    }
    assert body["session_id"] == session_id
    assert body["report_id"] == report_id
    assert body["status"] == "published"
    assert body["has_public_token"] is True
    assert body["claim_count"] == len(
        [row for row in mem_store["vbr_report_claims"].values() if row["report_id"] == report_id]
    )


def test_report_status_reflects_draft_state(client: TestClient) -> None:
    _project_id, session_id, report_id = _setup_draft_report(client)

    response = _report_status(client, session_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["report_id"] == report_id
    assert body["status"] == "draft"
    assert body["has_public_token"] is False
    assert body["published_at"] is None


# ── Sanity: existing T6C draft-report flow still works ───────────────────────


def test_existing_draft_report_flow_still_works(client: TestClient) -> None:
    _project_id, session_id, _report_id = _setup_draft_report(client)

    response = _draft_report(client, session_id)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "draft"


def test_publish_report_rejects_latest_report_from_different_session(client: TestClient, mem_store: dict) -> None:
    project_id, session_id = _setup_draft_report(client)[:2]

    other_session_id = "other-session-attempt"
    report = next(row for row in mem_store["vbr_reports"].values() if row.get("project_id") == project_id)
    report["body"]["summary"]["session_id"] = other_session_id

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/publish-report")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "vbr_report_not_found"


def test_publish_report_rejects_camelcase_and_storage_url_unsafe_body(client: TestClient, mem_store: dict) -> None:
    project_id, session_id = _setup_draft_report(client)[:2]

    report = next(row for row in mem_store["vbr_reports"].values() if row.get("project_id") == project_id)
    report["body"]["claims"][0]["signedUrl"] = "https://example.supabase.co/storage/v1/object/sign/private-file"

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/publish-report")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_report_unsafe_body"


def test_publish_rejects_camelcase_signed_url_body(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id, report_id = _setup_draft_report(client)
    _submit_review(client, session_id)

    mem_store["vbr_reports"][report_id]["body"]["claims"][0]["signedUrl"] = (
        "https://example.supabase.co/storage/v1/object/sign/private/video.webm"
    )

    response = _publish(client, session_id)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_report_unsafe_body"
