"""Tests for the public VBR report read endpoint (T7B)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app

USER_ID = "00000000-0000-0000-0000-000000000042"


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
    project_id, session_id = _setup_processed_session(client, chunk_count)
    _transcribe(client, session_id)
    _extract_keyframes(client, session_id)
    return project_id, session_id


def _build_evidence(client: TestClient, session_id: str):
    return client.post(f"/api/v1/student/vbr/sessions/{session_id}/build-evidence")


def _setup_judgment_ready_session(client: TestClient, chunk_count: int = 1) -> tuple[str, str]:
    project_id, session_id = _setup_evidence_ready_session(client, chunk_count)
    evidence_response = _build_evidence(client, session_id)
    assert evidence_response.status_code == 200, evidence_response.text
    return project_id, session_id


def _judge(client: TestClient, session_id: str):
    return client.post(f"/api/v1/student/vbr/sessions/{session_id}/judge")


def _setup_report_ready_session(client: TestClient, chunk_count: int = 1) -> tuple[str, str]:
    project_id, session_id = _setup_judgment_ready_session(client, chunk_count)
    judge_response = _judge(client, session_id)
    assert judge_response.status_code == 200, judge_response.text
    return project_id, session_id


def _draft_report(client: TestClient, session_id: str):
    return client.post(f"/api/v1/student/vbr/sessions/{session_id}/draft-report")


def _setup_draft_report(client: TestClient, chunk_count: int = 1) -> tuple[str, str, str]:
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


def _setup_published_report(client: TestClient, mem_store: dict, chunk_count: int = 1) -> tuple[str, str, str, str]:
    """Create a project/session/report and publish it. Returns (project_id, session_id, report_id, public_token)."""
    project_id, session_id, report_id = _setup_draft_report(client, chunk_count)
    _submit_review(client, session_id)
    publish_response = _publish(client, session_id)
    assert publish_response.status_code == 200, publish_response.text

    public_token = mem_store["vbr_reports"][report_id]["public_token"]
    assert isinstance(public_token, str) and public_token

    return project_id, session_id, report_id, public_token


def _get_public_report(client: TestClient, public_token: str):
    return client.get(f"/api/v1/public/vbr/legacy-reports/{public_token}")


# ── public report read ───────────────────────────────────────────────────────


def test_public_report_returns_200_for_published_report(client: TestClient, mem_store: dict) -> None:
    _project_id, _session_id, _report_id, public_token = _setup_published_report(client, mem_store)

    response = _get_public_report(client, public_token)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "published"
    assert body["project_title"] == "My Capstone Project"
    assert body["claim_count"] > 0
    assert body["claims"]
    assert body["verification_note"]


def test_public_report_does_not_require_auth(client: TestClient, mem_store: dict) -> None:
    _project_id, _session_id, _report_id, public_token = _setup_published_report(client, mem_store)

    # Remove the authenticated-user override entirely; the public endpoint
    # must not depend on get_current_user_id.
    del app.dependency_overrides[get_current_user_id]

    response = client.get(f"/api/v1/public/vbr/legacy-reports/{public_token}")

    assert response.status_code == 200, response.text


def test_public_report_does_not_expose_public_token(client: TestClient, mem_store: dict) -> None:
    _project_id, _session_id, _report_id, public_token = _setup_published_report(client, mem_store)

    response = _get_public_report(client, public_token)

    assert response.status_code == 200, response.text
    raw = response.text

    assert public_token not in raw
    assert '"public_token"' not in raw


def test_public_report_does_not_expose_private_internals(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id, _report_id, public_token = _setup_published_report(client, mem_store)

    response = _get_public_report(client, public_token)

    assert response.status_code == 200, response.text
    raw = response.text

    assert "storage_path" not in raw
    assert "signed" not in raw.lower()
    assert "vbr/sessions" not in raw
    assert "/tmp/" not in raw
    assert session_id not in raw
    assert "full_transcript" not in raw.lower()
    assert "transcript_text" not in raw.lower()
    assert "Candidate introduced the project and repository." not in raw
    assert "Candidate explained a key implementation decision." not in raw
    assert "evidence_item_ids" not in raw


def test_public_report_returns_404_for_unpublished_report(client: TestClient, mem_store: dict) -> None:
    _project_id, _session_id, report_id = _setup_draft_report(client)

    # Mint a token without publishing (simulating a report that never went public).
    mem_store["vbr_reports"][report_id]["public_token"] = "unpublished-token"

    response = _get_public_report(client, "unpublished-token")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "vbr_public_report_not_found"


def test_public_report_returns_404_after_unpublish(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id, _report_id, public_token = _setup_published_report(client, mem_store)

    unpublish_response = _unpublish(client, session_id)
    assert unpublish_response.status_code == 200, unpublish_response.text

    response = _get_public_report(client, public_token)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "vbr_public_report_not_found"


def test_public_report_returns_404_for_unsafe_body(client: TestClient, mem_store: dict) -> None:
    _project_id, _session_id, report_id, public_token = _setup_published_report(client, mem_store)

    # Simulate a body that somehow contains an unsafe field after publish.
    mem_store["vbr_reports"][report_id]["body"]["storage_path"] = "vbr/sessions/abc/chunks/000.webm"

    response = _get_public_report(client, public_token)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "vbr_public_report_not_found"
    assert "storage_path" not in response.text


def test_public_report_returns_404_for_unknown_token(client: TestClient) -> None:
    response = _get_public_report(client, "this-token-does-not-exist")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "vbr_public_report_not_found"


def test_public_report_response_shape(client: TestClient, mem_store: dict) -> None:
    _project_id, _session_id, _report_id, public_token = _setup_published_report(client, mem_store)

    response = _get_public_report(client, public_token)

    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body.keys()) == {
        "project_title",
        "repo_full_name",
        "status",
        "published_at",
        "claim_count",
        "evidence_count",
        "claims",
        "methodology",
        "verification_note",
    }

    for claim in body["claims"]:
        assert set(claim.keys()) == {"claim_text", "judgment", "rationale", "evidence_count"}
        assert claim["judgment"] in {"demonstrated", "partially_demonstrated", "not_assessed"}


def test_public_report_rejects_camelcase_unsafe_keys(client: TestClient, mem_store: dict) -> None:
    _project_id, _session_id, _report_id, token = _setup_published_report(client, mem_store)

    report = next(row for row in mem_store["vbr_reports"].values() if row.get("public_token") == token)
    report["body"]["claims"][0]["signedUrl"] = "https://example.com/private"

    response = client.get(f"/api/v1/public/vbr/legacy-reports/{token}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "vbr_public_report_not_found"


def test_public_report_rejects_supabase_storage_url_values(client: TestClient, mem_store: dict) -> None:
    _project_id, _session_id, _report_id, token = _setup_published_report(client, mem_store)

    report = next(row for row in mem_store["vbr_reports"].values() if row.get("public_token") == token)
    report["body"]["claims"][0]["evidence_url"] = (
        "https://example.supabase.co/storage/v1/object/sign/private/video.webm"
    )

    response = client.get(f"/api/v1/public/vbr/legacy-reports/{token}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "vbr_public_report_not_found"


def _progress_session_to_report_ready(client: TestClient, session_id: str, chunk_count: int = 1) -> None:
    """Progress an existing 'created' session through to judgment-ready (for /draft-report)."""
    _start_session(client, session_id)
    for chunk_index in range(chunk_count):
        _upload_chunk(client, session_id, chunk_index)
    _finalize(client, session_id, duration_s=120)

    process_response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/process")
    assert process_response.status_code == 200, process_response.text

    _transcribe(client, session_id)
    _extract_keyframes(client, session_id)

    evidence_response = _build_evidence(client, session_id)
    assert evidence_response.status_code == 200, evidence_response.text

    judge_response = _judge(client, session_id)
    assert judge_response.status_code == 200, judge_response.text


def test_public_report_unaffected_by_second_session_draft(client: TestClient, mem_store: dict) -> None:
    project_id, session1_id, report1_id, public_token = _setup_published_report(client, mem_store)

    # Start a second verification attempt for the same project while the
    # first session's report is published.
    questions_response = client.post(f"/api/v1/student/vbr/projects/{project_id}/generate-questions")
    assert questions_response.status_code == 200, questions_response.text
    session2_id = questions_response.json()["session_id"]
    assert session2_id != session1_id

    _progress_session_to_report_ready(client, session2_id)

    # Drafting session2's report is blocked while a published report exists
    # for this project (one published report per project policy).
    draft2 = _draft_report(client, session2_id)
    assert draft2.status_code == 409
    assert draft2.json()["detail"]["code"] == "vbr_report_already_published"

    # The first session's public report page is unaffected.
    response = _get_public_report(client, public_token)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "published"

    # The real session_id column is never returned in the public projection.
    raw = response.text
    assert "session_id" not in raw
    assert session1_id not in raw
    assert mem_store["vbr_reports"][report1_id]["session_id"] == session1_id


def test_public_report_rejects_public_token_inside_body(client: TestClient, mem_store: dict) -> None:
    _project_id, _session_id, _report_id, token = _setup_published_report(client, mem_store)

    report = next(row for row in mem_store["vbr_reports"].values() if row.get("public_token") == token)
    report["body"]["summary"]["publicToken"] = "should-not-be-public-body"

    response = client.get(f"/api/v1/public/vbr/legacy-reports/{token}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "vbr_public_report_not_found"
