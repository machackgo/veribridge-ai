"""Tests for the VBR claim/question judgment skeleton (T6B)."""

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


def test_judge_requires_owner(client: TestClient) -> None:
    _project_id, session_id = _setup_judgment_ready_session(client)

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = _judge(client, session_id)

    assert response.status_code == 404


def test_judge_requires_processed_session(client: TestClient) -> None:
    _project_id, session_id = _setup_session(client)

    response = _judge(client, session_id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "vbr_session_not_processed"


def test_judge_requires_evidence_items(client: TestClient) -> None:
    _project_id, session_id = _setup_evidence_ready_session(client)

    # Evidence items have not been built yet.
    response = _judge(client, session_id)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_judgment_evidence_missing"


def test_judge_requires_confirmed_claims(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_judgment_ready_session(client)

    mem_store["vbr_project_claims"].clear()

    response = _judge(client, session_id)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_judgment_claims_missing"


def test_judge_requires_session_questions(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_judgment_ready_session(client)

    mem_store["vbr_session_questions"].clear()

    response = _judge(client, session_id)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_judgment_questions_missing"


def test_judge_creates_deterministic_claim_judgments(client: TestClient, mem_store: dict) -> None:
    project_id, session_id = _setup_judgment_ready_session(client)

    confirmed_claims = [
        row
        for row in mem_store["vbr_project_claims"].values()
        if row["project_id"] == project_id and row["status"] == "confirmed"
    ]
    assert confirmed_claims

    response = _judge(client, session_id)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["session_id"] == session_id
    assert body["judged_claim_count"] == len(confirmed_claims)
    assert body["status"] == "processed"

    skeleton = mem_store["vbr_verification_sessions"][session_id]["telemetry"]["judgment_skeleton"]
    assert skeleton["method"] == "deterministic_skeleton_no_llm"
    assert "created_at" in skeleton

    claim_judgments = skeleton["claim_judgments"]
    assert len(claim_judgments) == len(confirmed_claims)

    confirmed_claim_ids = {str(row["id"]) for row in confirmed_claims}
    for judgment in claim_judgments:
        assert judgment["claim_id"] in confirmed_claim_ids
        assert judgment["status"] in {"demonstrated", "partially_demonstrated", "not_assessed"}
        assert judgment["rationale"]
        assert isinstance(judgment["evidence_item_ids"], list)


def test_judge_creates_deterministic_question_judgments(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_judgment_ready_session(client)

    questions = [row for row in mem_store["vbr_session_questions"].values() if row["session_id"] == session_id]
    assert questions

    response = _judge(client, session_id)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["judged_question_count"] == len(questions)

    skeleton = mem_store["vbr_verification_sessions"][session_id]["telemetry"]["judgment_skeleton"]
    question_judgments = skeleton["question_judgments"]
    assert len(question_judgments) == len(questions)

    question_ids = {str(row["id"]) for row in questions}
    for judgment in question_judgments:
        assert judgment["question_id"] in question_ids
        assert judgment["status"] in {"answered_with_evidence", "needs_review"}
        assert judgment["rationale"]
        assert isinstance(judgment["evidence_item_ids"], list)


def test_judge_is_idempotent_and_does_not_duplicate(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_judgment_ready_session(client)

    first = _judge(client, session_id)
    assert first.status_code == 200, first.text
    first_body = first.json()

    second = _judge(client, session_id)
    assert second.status_code == 200, second.text
    second_body = second.json()

    assert first_body["judged_claim_count"] == second_body["judged_claim_count"]
    assert first_body["judged_question_count"] == second_body["judged_question_count"]

    skeleton = mem_store["vbr_verification_sessions"][session_id]["telemetry"]["judgment_skeleton"]
    assert len(skeleton["claim_judgments"]) == first_body["judged_claim_count"]
    assert len(skeleton["question_judgments"]) == first_body["judged_question_count"]


def test_judge_preserves_unrelated_telemetry_keys(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_judgment_ready_session(client)

    telemetry_before = mem_store["vbr_verification_sessions"][session_id]["telemetry"]
    assert "media_processing" in telemetry_before
    assert "transcript" in telemetry_before
    assert "keyframes" in telemetry_before

    response = _judge(client, session_id)
    assert response.status_code == 200, response.text

    telemetry_after = mem_store["vbr_verification_sessions"][session_id]["telemetry"]
    assert telemetry_after["media_processing"] == telemetry_before["media_processing"]
    assert telemetry_after["transcript"] == telemetry_before["transcript"]
    assert telemetry_after["keyframes"] == telemetry_before["keyframes"]
    assert "judgment_skeleton" in telemetry_after


def test_judge_response_does_not_expose_internals(client: TestClient) -> None:
    _project_id, session_id = _setup_judgment_ready_session(client)

    response = _judge(client, session_id)

    assert response.status_code == 200, response.text
    raw = response.text
    assert "storage_path" not in raw
    assert "signed" not in raw
    assert "vbr/sessions" not in raw
    assert "tmp" not in raw.lower()
    for text in _SKELETON_SEGMENT_TEXTS:
        assert text not in raw

    body = response.json()
    assert set(body.keys()) == {
        "session_id",
        "judged_claim_count",
        "judged_question_count",
        "status",
        "message",
    }


def test_judge_requires_transcript_or_question_evidence(client: TestClient, mem_store: dict) -> None:
    _project_id, session_id = _setup_judgment_ready_session(client)

    # Keep only non-answer-supporting evidence.
    mem_store["vbr_evidence_items"] = {
        evidence_id: evidence
        for evidence_id, evidence in mem_store["vbr_evidence_items"].items()
        if evidence.get("evidence_type") in {"repo_analysis", "deployed_url", "keyframe", "media_processing"}
    }

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/judge")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_judgment_supporting_evidence_missing"


def test_judge_ignores_evidence_from_other_session_or_project(client: TestClient, mem_store: dict) -> None:
    project_id, session_id = _setup_judgment_ready_session(client)

    # Remove this session's transcript/question evidence.
    mem_store["vbr_evidence_items"] = {
        evidence_id: evidence
        for evidence_id, evidence in mem_store["vbr_evidence_items"].items()
        if not (
            evidence.get("project_id") == project_id
            and (evidence.get("pointer") or {}).get("session_id") == session_id
            and evidence.get("evidence_type") in {"transcript_segment", "session_telemetry"}
        )
    }

    # Add strong-looking evidence for another session/project. It must not satisfy this session.
    mem_store["vbr_evidence_items"]["other-session-transcript"] = {
        "id": "other-session-transcript",
        "project_id": "00000000-0000-0000-0000-000000000999",
        "evidence_type": "transcript_segment",
        "source": "vbr_transcript_segments",
        "title": "Other transcript",
        "summary": "This should not count.",
        "pointer": {"session_id": "00000000-0000-0000-0000-000000000998"},
        "metadata": {},
    }

    response = client.post(f"/api/v1/student/vbr/sessions/{session_id}/judge")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_judgment_supporting_evidence_missing"
