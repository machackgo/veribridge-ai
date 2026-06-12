"""Tests for VBR project claim + question generation skeleton (T3)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app

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


def _ingest_repo(client: TestClient, project_id: str) -> dict:
    response = client.post(f"/api/v1/student/vbr/projects/{project_id}/ingest-repo")
    assert response.status_code == 200, response.text
    return response.json()


def _generate_claims(client: TestClient, project_id: str) -> dict:
    response = client.post(f"/api/v1/student/vbr/projects/{project_id}/generate-claims")
    assert response.status_code == 200, response.text
    return response.json()


def _confirm_all_claims(client: TestClient, project_id: str) -> list[dict]:
    claims = _generate_claims(client, project_id)["claims"]
    confirmed = []
    for claim in claims:
        response = client.patch(
            f"/api/v1/student/vbr/projects/{project_id}/claims/{claim['id']}",
            json={"status": "confirmed"},
        )
        assert response.status_code == 200, response.text
        confirmed.append(response.json())
    return confirmed


def test_generate_claims_requires_owned_project(client: TestClient) -> None:
    project = _create_project(client)
    project_id = project["id"]
    _ingest_repo(client, project_id)

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = client.post(f"/api/v1/student/vbr/projects/{project_id}/generate-claims")

    assert response.status_code == 404


def test_generate_claims_requires_repo_analysis_first(client: TestClient) -> None:
    project = _create_project(client)
    project_id = project["id"]

    response = client.post(f"/api/v1/student/vbr/projects/{project_id}/generate-claims")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_repo_analysis_required"


def test_generate_claims_creates_rows_and_sets_status(client: TestClient, mem_store: dict) -> None:
    project = _create_project(client)
    project_id = project["id"]
    _ingest_repo(client, project_id)

    body = _generate_claims(client, project_id)

    assert body["project_id"] == project_id
    assert body["status"] == "claims_ready"
    assert 4 <= len(body["claims"]) <= 6
    for claim in body["claims"]:
        assert claim["status"] == "proposed"
        assert claim["source"] == "llm_proposed"
        assert claim["anchors"]

    assert len(mem_store["vbr_project_claims"]) == len(body["claims"])

    project_after = client.get(f"/api/v1/student/vbr/projects/{project_id}").json()
    assert project_after["status"] == "claims_ready"

    # Re-running is idempotent: proposed claims are replaced, not duplicated.
    body2 = _generate_claims(client, project_id)
    assert len(mem_store["vbr_project_claims"]) == len(body2["claims"])


def test_list_claims_returns_only_owned_project_claims(client: TestClient) -> None:
    project = _create_project(client)
    project_id = project["id"]
    _ingest_repo(client, project_id)
    generated = _generate_claims(client, project_id)["claims"]

    response = client.get(f"/api/v1/student/vbr/projects/{project_id}/claims")
    assert response.status_code == 200, response.text
    claims = response.json()

    assert [c["id"] for c in claims] == [c["id"] for c in generated]
    sort_orders = [c["sort_order"] for c in claims]
    assert sort_orders == sorted(sort_orders)

    other_project = _create_project(client, title="Other project")
    _ingest_repo(client, other_project["id"])
    _generate_claims(client, other_project["id"])

    response = client.get(f"/api/v1/student/vbr/projects/{project_id}/claims")
    claim_ids = {c["id"] for c in response.json()}
    assert claim_ids == {c["id"] for c in generated}


def test_patch_claim_can_confirm_edit_and_drop_only_own_claim(client: TestClient) -> None:
    project = _create_project(client)
    project_id = project["id"]
    _ingest_repo(client, project_id)
    claims = _generate_claims(client, project_id)["claims"]
    claim_id = claims[0]["id"]
    other_claim_id = claims[1]["id"]

    confirm_response = client.patch(
        f"/api/v1/student/vbr/projects/{project_id}/claims/{claim_id}",
        json={"status": "confirmed"},
    )
    assert confirm_response.status_code == 200, confirm_response.text
    assert confirm_response.json()["status"] == "confirmed"

    edit_response = client.patch(
        f"/api/v1/student/vbr/projects/{project_id}/claims/{claim_id}",
        json={"claim_text": "Edited claim text describing the project."},
    )
    assert edit_response.status_code == 200, edit_response.text
    assert edit_response.json()["claim_text"] == "Edited claim text describing the project."

    drop_response = client.patch(
        f"/api/v1/student/vbr/projects/{project_id}/claims/{other_claim_id}",
        json={"status": "dropped"},
    )
    assert drop_response.status_code == 200, drop_response.text
    assert drop_response.json()["status"] == "dropped"

    invalid_status_response = client.patch(
        f"/api/v1/student/vbr/projects/{project_id}/claims/{claim_id}",
        json={"status": "not_a_real_status"},
    )
    assert invalid_status_response.status_code == 422

    # Other user cannot patch this project's claims.
    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    other_user_response = client.patch(
        f"/api/v1/student/vbr/projects/{project_id}/claims/{claim_id}",
        json={"status": "confirmed"},
    )
    assert other_user_response.status_code == 404


def test_generate_questions_requires_confirmed_claim(client: TestClient) -> None:
    project = _create_project(client)
    project_id = project["id"]
    _ingest_repo(client, project_id)
    _generate_claims(client, project_id)

    response = client.post(f"/api/v1/student/vbr/projects/{project_id}/generate-questions")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_no_confirmed_claims"


def test_generate_questions_creates_session_and_questions(client: TestClient, mem_store: dict) -> None:
    project = _create_project(client, deployed_url="https://example.com")
    project_id = project["id"]
    _ingest_repo(client, project_id)
    _confirm_all_claims(client, project_id)

    response = client.post(f"/api/v1/student/vbr/projects/{project_id}/generate-questions")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["project_id"] == project_id
    assert body["status"] == "questions_ready"
    assert body["session_id"]
    assert 6 <= len(body["questions"]) <= 10
    for question in body["questions"]:
        assert question["session_id"] == body["session_id"]
        assert question["claim_ids"]

    assert len(mem_store["vbr_verification_sessions"]) == 1
    assert len(mem_store["vbr_session_questions"]) == len(body["questions"])

    project_after = client.get(f"/api/v1/student/vbr/projects/{project_id}").json()
    assert project_after["status"] == "questions_ready"

    questions_response = client.get(f"/api/v1/student/vbr/projects/{project_id}/questions")
    assert questions_response.status_code == 200, questions_response.text
    questions_body = questions_response.json()
    assert questions_body["session_id"] == body["session_id"]
    assert len(questions_body["questions"]) == len(body["questions"])

    # Re-running reuses the same created session rather than creating a new one.
    response2 = client.post(f"/api/v1/student/vbr/projects/{project_id}/generate-questions")
    assert response2.status_code == 200, response2.text
    assert response2.json()["session_id"] == body["session_id"]
    assert len(mem_store["vbr_verification_sessions"]) == 1


def test_generate_questions_not_found_for_other_user(client: TestClient) -> None:
    project = _create_project(client)
    project_id = project["id"]
    _ingest_repo(client, project_id)
    _confirm_all_claims(client, project_id)

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = client.post(f"/api/v1/student/vbr/projects/{project_id}/generate-questions")

    assert response.status_code == 404


def test_generate_claims_does_not_regress_questions_ready_status(
    client: TestClient, mem_store: dict
) -> None:
    project = _create_project(client)
    project_id = project["id"]
    _ingest_repo(client, project_id)

    # Move project forward first.
    project_row = mem_store["vbr_projects"][project_id]
    project_row["status"] = "questions_ready"

    response = client.post(f"/api/v1/student/vbr/projects/{project_id}/generate-claims")

    assert response.status_code == 200
    assert project_row["status"] == "questions_ready"


def test_generate_questions_conflicts_when_active_session_already_started(
    client: TestClient, mem_store: dict
) -> None:
    project = _create_project(client)
    project_id = project["id"]
    _ingest_repo(client, project_id)

    response = client.post(f"/api/v1/student/vbr/projects/{project_id}/generate-claims")
    assert response.status_code == 200

    claims = client.get(f"/api/v1/student/vbr/projects/{project_id}/claims").json()
    claim_id = claims[0]["id"]
    confirm = client.patch(
        f"/api/v1/student/vbr/projects/{project_id}/claims/{claim_id}",
        json={"status": "confirmed"},
    )
    assert confirm.status_code == 200

    first = client.post(f"/api/v1/student/vbr/projects/{project_id}/generate-questions")
    assert first.status_code == 200
    session_id = first.json()["session_id"]

    session_row = mem_store["vbr_verification_sessions"][session_id]
    session_row["status"] = "recording"

    second = client.post(f"/api/v1/student/vbr/projects/{project_id}/generate-questions")
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "vbr_active_session_already_started"
