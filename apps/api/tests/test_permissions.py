"""Tests for role-based access control and permissions."""

from __future__ import annotations

import inspect
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.schemas.permissions import UserRoleGrantRequest
from app.services.permission_service import PermissionService


ADMIN_ID = "00000000-0000-0000-0000-000000000777"
STUDENT_ID = "00000000-0000-0000-0000-000000000042"
OTHER_ID = "00000000-0000-0000-0000-000000000099"


@pytest.fixture()
def mem_store() -> dict:
    return {
        "users": {
            ADMIN_ID: {"id": ADMIN_ID, "email": "admin@example.edu", "role": "admin"},
            STUDENT_ID: {"id": STUDENT_ID, "email": "student@example.edu"},
            OTHER_ID: {"id": OTHER_ID, "email": "other@example.edu"},
        }
    }


@pytest.fixture()
def state() -> dict:
    return {"user_id": STUDENT_ID}


@pytest.fixture()
def client(mem_store: dict, state: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: state["user_id"]
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_grant_role_creates_active_role(mem_store: dict) -> None:
    service = PermissionService(mem_store)
    role = service.grant_role(STUDENT_ID, "recruiter", ADMIN_ID, metadata={"source": "test"})

    assert role.user_id == STUDENT_ID
    assert role.role == "recruiter"
    assert role.is_active is True
    assert service.has_role(STUDENT_ID, "recruiter") is True
    assert len(mem_store["role_permission_audit_events"]) == 1


def test_revoke_role_deactivates_role(mem_store: dict) -> None:
    service = PermissionService(mem_store)
    service.grant_role(STUDENT_ID, "recruiter", ADMIN_ID)
    revoked = service.revoke_role(STUDENT_ID, "recruiter", ADMIN_ID)

    assert revoked.is_active is False
    assert service.has_role(STUDENT_ID, "recruiter") is False
    assert len(mem_store["role_permission_audit_events"]) == 2


def test_has_role_returns_true_for_active_role_and_false_for_revoked(mem_store: dict) -> None:
    service = PermissionService(mem_store)
    service.grant_role(STUDENT_ID, "reviewer", ADMIN_ID)
    assert service.has_role(STUDENT_ID, "reviewer") is True
    service.revoke_role(STUDENT_ID, "reviewer", ADMIN_ID)
    assert service.has_role(STUDENT_ID, "reviewer") is False


def test_me_permissions_returns_student_dashboard_by_default(client: TestClient, state: dict) -> None:
    state["user_id"] = STUDENT_ID
    response = client.get("/api/v1/me/permissions")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["user_id"] == STUDENT_ID
    assert "student" in payload["roles"]
    assert payload["dashboard_access"]["student_dashboard"] is True


def test_admin_can_view_user_roles(client: TestClient, mem_store: dict, state: dict) -> None:
    PermissionService(mem_store).grant_role(STUDENT_ID, "recruiter", ADMIN_ID)
    state["user_id"] = ADMIN_ID

    response = client.get(f"/api/v1/admin/users/{STUDENT_ID}/roles")

    assert response.status_code == 200, response.text
    assert any(role["role"] == "recruiter" for role in response.json())


def test_admin_can_grant_role(client: TestClient, mem_store: dict, state: dict) -> None:
    state["user_id"] = ADMIN_ID

    response = client.post(
        f"/api/v1/admin/users/{STUDENT_ID}/roles",
        json={
            "role": "recruiter",
            "scope": "global",
            "scope_id": None,
            "metadata": {"source": "admin-test"},
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "recruiter"
    assert PermissionService(mem_store).has_role(STUDENT_ID, "recruiter") is True


def test_admin_can_revoke_role(client: TestClient, mem_store: dict, state: dict) -> None:
    PermissionService(mem_store).grant_role(STUDENT_ID, "recruiter", ADMIN_ID)
    state["user_id"] = ADMIN_ID

    response = client.delete(f"/api/v1/admin/users/{STUDENT_ID}/roles/recruiter")

    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False
    assert PermissionService(mem_store).has_role(STUDENT_ID, "recruiter") is False


def test_normal_user_cannot_manage_roles(client: TestClient, state: dict) -> None:
    state["user_id"] = STUDENT_ID
    response = client.post(
        f"/api/v1/admin/users/{OTHER_ID}/roles",
        json={
            "role": "recruiter",
            "scope": "global",
            "scope_id": None,
            "metadata": {},
        },
    )

    assert response.status_code == 403


def test_role_audit_events_are_created(mem_store: dict) -> None:
    service = PermissionService(mem_store)
    service.grant_role(STUDENT_ID, "admin", ADMIN_ID)
    service.get_current_user_permissions(STUDENT_ID)
    service.revoke_role(STUDENT_ID, "admin", ADMIN_ID)

    assert len(mem_store["role_permission_audit_events"]) >= 3


def test_no_project_specific_hardcoding() -> None:
    import app.services.permission_service as service

    source = inspect.getsource(service).lower()
    assert "boston" not in source
    assert "react demo" not in source
    assert "repo name" not in source

