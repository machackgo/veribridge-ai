"""Tests for the VBR private report draft generation (T6C)."""

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


def test_draft_report_requires_owner(client: TestClient) -> None:
    _project_id, session_id = _setup_report_ready_session(client)

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = _draft_report(client, session_id)

    assert response.status_code == 404


def test_draft_report_requires_processed_session(client: TestClient) -> None:
    _project_id, session_id = _setup_session(client)

    response = _draft_report(client, session_id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "vbr_session_not_processed"


def test_draft_report_requires_judgment_skeleton(client: TestClient) -> None:
    _project_id, session_id = _setup_judgment_ready_session(client)

    # /judge has not been run yet.
    response = _draft_report(client, session_id)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_report_judgment_missing"


def test_draft_report_requires_evidence_items(client: TestClient, mem_store: dict) -> None:
    project_id, session_id = _setup_report_ready_session(client)

    mem_store["vbr_evidence_items"] = {
        evidence_id: evidence
        for evidence_id, evidence in mem_store["vbr_evidence_items"].items()
        if not (
            evidence.get("project_id") == project_id
            and (evidence.get("pointer") or {}).get("session_id") == session_id
        )
    }

    response = _draft_report(client, session_id)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_report_evidence_missing"


def test_draft_report_requires_confirmed_claims(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_report_ready_session(client)

    mem_store["vbr_project_claims"].clear()

    response = _draft_report(client, session_id)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_report_claims_missing"


def test_draft_report_creates_report_row(client: TestClient, mem_store: dict) -> None:
    project_id, session_id = _setup_report_ready_session(client)

    confirmed_claims = [
        row
        for row in mem_store["vbr_project_claims"].values()
        if row["project_id"] == project_id and row["status"] == "confirmed"
    ]
    evidence_items = [
        row
        for row in mem_store["vbr_evidence_items"].values()
        if row["project_id"] == project_id and (row.get("pointer") or {}).get("session_id") == session_id
    ]

    response = _draft_report(client, session_id)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["session_id"] == session_id
    assert body["status"] == "draft"
    assert body["claim_count"] == len(confirmed_claims)
    assert body["evidence_count"] == len(evidence_items)

    report_id = body["report_id"]
    report_row = mem_store["vbr_reports"][report_id]
    assert report_row["project_id"] == project_id
    assert report_row["status"] == "draft"
    assert report_row["public_token"] is None
    assert report_row["human_reviewed"] is False

    draft_body = report_row["body"]
    assert draft_body["version"] == "vbr_draft_v1"
    assert draft_body["method"] == "deterministic_skeleton_no_llm"
    assert draft_body["summary"]["session_id"] == session_id
    assert draft_body["summary"]["claim_count"] == len(confirmed_claims)
    assert draft_body["summary"]["evidence_count"] == len(evidence_items)
    assert len(draft_body["claims"]) == len(confirmed_claims)
    for claim in draft_body["claims"]:
        assert claim["judgment"] in {"demonstrated", "partially_demonstrated", "not_assessed"}
        assert claim["claim_text"]
        assert isinstance(claim["evidence_item_ids"], list)


def test_draft_report_creates_report_claim_rows(client: TestClient, mem_store: dict) -> None:
    project_id, session_id = _setup_report_ready_session(client)

    confirmed_claims = [
        row
        for row in mem_store["vbr_project_claims"].values()
        if row["project_id"] == project_id and row["status"] == "confirmed"
    ]
    confirmed_claim_ids = {str(row["id"]) for row in confirmed_claims}

    response = _draft_report(client, session_id)
    assert response.status_code == 200, response.text
    report_id = response.json()["report_id"]

    report_claims = [row for row in mem_store.setdefault("vbr_report_claims", {}).values() if row["report_id"] == report_id]
    assert len(report_claims) == len(confirmed_claims)

    for row in report_claims:
        assert row["claim_id"] in confirmed_claim_ids
        assert row["tier"] in {"demonstrated", "partially_demonstrated", "not_assessed", "insufficient_evidence"}
        assert row["inconsistency_noted"] is False
        assert isinstance(row["evidence_item_ids"], list)


def test_draft_report_is_idempotent_and_does_not_duplicate(client: TestClient, mem_store: dict) -> None:
    project_id, session_id = _setup_report_ready_session(client)

    first = _draft_report(client, session_id)
    assert first.status_code == 200, first.text
    first_body = first.json()

    second = _draft_report(client, session_id)
    assert second.status_code == 200, second.text
    second_body = second.json()

    assert first_body["report_id"] == second_body["report_id"]
    assert first_body["claim_count"] == second_body["claim_count"]
    assert first_body["evidence_count"] == second_body["evidence_count"]

    reports = [row for row in mem_store["vbr_reports"].values() if row["project_id"] == project_id]
    assert len(reports) == 1

    report_claims = [row for row in mem_store.setdefault("vbr_report_claims", {}).values() if row["report_id"] == first_body["report_id"]]
    assert len(report_claims) == first_body["claim_count"]


def test_draft_report_does_not_modify_published_report(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_report_ready_session(client)

    first = _draft_report(client, session_id)
    assert first.status_code == 200, first.text
    report_id = first.json()["report_id"]

    mem_store["vbr_reports"][report_id]["status"] = "published"
    mem_store["vbr_reports"][report_id]["public_token"] = "some-public-token"

    response = _draft_report(client, session_id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "vbr_report_already_published"

    # Published report row must be untouched.
    assert mem_store["vbr_reports"][report_id]["status"] == "published"
    assert mem_store["vbr_reports"][report_id]["public_token"] == "some-public-token"


def test_draft_report_response_does_not_expose_internals(client: TestClient) -> None:
    _project_id, session_id = _setup_report_ready_session(client)

    response = _draft_report(client, session_id)

    assert response.status_code == 200, response.text
    raw = response.text
    assert "public_token" not in raw
    assert "storage_path" not in raw
    assert "signed" not in raw
    assert "vbr/sessions" not in raw
    assert "tmp" not in raw.lower()
    for text in _SKELETON_SEGMENT_TEXTS:
        assert text not in raw

    body = response.json()
    assert set(body.keys()) == {
        "session_id",
        "report_id",
        "status",
        "claim_count",
        "evidence_count",
        "message",
    }


def test_draft_report_body_does_not_contain_storage_paths_or_transcript_text(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_report_ready_session(client)

    response = _draft_report(client, session_id)
    assert response.status_code == 200, response.text

    report_id = response.json()["report_id"]
    draft_body = mem_store["vbr_reports"][report_id]["body"]

    import json

    serialized = json.dumps(draft_body)
    assert "storage_path" not in serialized
    assert "signed" not in serialized
    assert "vbr/sessions" not in serialized
    assert "tmp" not in serialized.lower()
    for text in _SKELETON_SEGMENT_TEXTS:
        assert text not in serialized


# ── Sanity checks: existing T6A/T6B endpoints still behave ──────────────────


def test_existing_judge_flow_still_works(client: TestClient) -> None:
    _project_id, session_id = _setup_judgment_ready_session(client)

    response = _judge(client, session_id)

    assert response.status_code == 200, response.text


def test_existing_build_evidence_flow_still_works(client: TestClient) -> None:
    _project_id, session_id = _setup_evidence_ready_session(client)

    response = _build_evidence(client, session_id)

    assert response.status_code == 200, response.text


def test_draft_report_rejects_if_any_published_report_exists(client: TestClient, mem_store: dict) -> None:
    project_id, session_id = _setup_report_ready_session(client)

    mem_store.setdefault("vbr_reports", {})["published-old"] = {
        "id": "published-old",
        "project_id": project_id,
        "status": "published",
        "public_token": "public-token",
        "body": {"version": "old"},
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    mem_store.setdefault("vbr_reports", {})["latest-draft"] = {
        "id": "latest-draft",
        "project_id": project_id,
        "status": "draft",
        "public_token": None,
        "body": {"version": "draft"},
        "created_at": "2026-01-02T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
    }

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/draft-report")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "vbr_report_already_published"


def test_draft_report_clears_public_token_when_reusing_unpublished_report(client: TestClient, mem_store: dict) -> None:
    project_id, session_id = _setup_report_ready_session(client)

    mem_store.setdefault("vbr_reports", {})["unpublished-with-token"] = {
        "id": "unpublished-with-token",
        "project_id": project_id,
        "status": "unpublished",
        "public_token": "stale-token",
        "published_at": "2026-01-01T00:00:00Z",
        "body": {"version": "old"},
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/draft-report")

    assert response.status_code == 200
    report = mem_store.setdefault("vbr_reports", {})["unpublished-with-token"]
    assert report["status"] == "draft"
    assert report.get("public_token") is None
    assert report.get("published_at") is None


def test_draft_report_filters_foreign_evidence_ids_from_judgment_skeleton(
    client: TestClient, mem_store: dict
) -> None:
    _project_id, session_id = _setup_report_ready_session(client)

    session = mem_store["vbr_verification_sessions"][session_id]
    judgment = session["telemetry"]["judgment_skeleton"]
    judgment["claim_judgments"][0]["evidence_item_ids"].append("foreign-evidence-id")

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/draft-report")

    assert response.status_code == 200
    report_id = response.json()["report_id"]
    report_claims = [
        row for row in mem_store.setdefault("vbr_report_claims", {}).values()
        if row.get("report_id") == report_id
    ]
    assert report_claims
    assert all("foreign-evidence-id" not in (row.get("evidence_item_ids") or []) for row in report_claims)
