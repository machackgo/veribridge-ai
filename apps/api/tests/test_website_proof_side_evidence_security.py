"""Ownership gates for Website Proof side-evidence ingress."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app


OWNER = "00000000-0000-0000-0000-000000000001"
FOREIGN = "00000000-0000-0000-0000-000000000002"
SESSION_ID = "00000000-0000-0000-0000-000000000099"


@pytest.fixture()
def foreign_session_store() -> dict:
    return {
        "extension_proof_sessions": {
            SESSION_ID: {
                "id": SESSION_ID,
                "user_id": FOREIGN,
                "status": "recording",
                "metadata": {"project_id": "00000000-0000-0000-0000-000000000077"},
            }
        }
    }


@pytest.fixture()
def client(foreign_session_store: dict):
    app.dependency_overrides[get_current_user_id] = lambda: OWNER
    app.dependency_overrides[get_db] = lambda: foreign_session_store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def assert_indistinct_not_found(response) -> None:
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "extension_proof_session_not_found"


def test_foreign_visible_evidence_is_denied_without_insertion(
    client: TestClient, foreign_session_store: dict,
) -> None:
    response = client.post(
        f"/api/v1/student/extension-proof/sessions/{SESSION_ID}/workflow/visible-evidence",
        json={"events": []},
    )
    assert_indistinct_not_found(response)
    assert not foreign_session_store.get("workflow_visible_evidence_events")


def test_foreign_visual_frames_are_denied_without_insertion(
    client: TestClient, foreign_session_store: dict,
) -> None:
    response = client.post(
        f"/api/v1/student/extension-proof/sessions/{SESSION_ID}/workflow/visual-frames",
        json={"frames": []},
    )
    assert_indistinct_not_found(response)
    assert not foreign_session_store.get("workflow_visual_frame_evidence")


def test_foreign_video_is_denied_before_extraction_or_retention(
    client: TestClient, foreign_session_store: dict,
) -> None:
    response = client.post(
        f"/api/v1/student/extension-proof/sessions/{SESSION_ID}/workflow/video",
        files={"video": ("recording.webm", io.BytesIO(b"foreign-video"), "video/webm")},
    )
    assert_indistinct_not_found(response)
    assert not foreign_session_store.get("proof_artifacts")
    assert not foreign_session_store.get("_proof_artifact_objects")
