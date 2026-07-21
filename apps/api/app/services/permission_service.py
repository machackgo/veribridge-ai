"""Role-based access control and permission service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable
from uuid import uuid4

from fastapi import HTTPException, status

from app.core.serialization import make_json_safe
from app.schemas.permissions import (
    CurrentUserPermissionsResponse,
    DashboardAccess,
    UserRoleName,
    UserRoleResponse,
    UserRoleScope,
)

_USER_ROLES = "user_roles"
_AUDIT_EVENTS = "role_permission_audit_events"
_USERS = "users"

_ROLE_PERMISSION_MAP = {
    "student": [
        "view_student_dashboard",
        "manage_own_profile",
        "view_own_passport",
    ],
    "recruiter": [
        "view_recruiter_dashboard",
        "save_candidates",
        "create_candidate_comparisons",
        "request_access",
    ],
    "admin": [
        "view_admin_dashboard",
        "manage_user_roles",
        "review_quality_cases",
        "manage_notifications",
    ],
    "reviewer": [
        "view_reviewer_dashboard",
        "review_quality_cases",
    ],
    "faculty_reviewer": [
        "view_reviewer_dashboard",
        "review_quality_cases",
    ],
    "company_reviewer": [
        "view_reviewer_dashboard",
        "review_quality_cases",
    ],
    "support": [
        "view_admin_dashboard",
        "manage_notifications",
        "review_quality_cases",
    ],
}

_DASHBOARD_ROLE_MAP = {
    "student_dashboard": {"student"},
    "recruiter_dashboard": {"recruiter"},
    "admin_dashboard": {"admin", "support"},
    "reviewer_dashboard": {"reviewer", "faculty_reviewer", "company_reviewer"},
}

_MANAGEMENT_ROLES = {"admin", "support"}
_ADMIN_ROLES = {"admin", "support", "reviewer"}


class PermissionNotFoundError(LookupError):
    """Permission row or role assignment not found."""


class PermissionService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def get_user_roles(self, user_id: str) -> list[UserRoleResponse]:
        rows = [row for row in self._active_role_rows(user_id)]
        rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        if not rows:
            fallback = self._fallback_user_role(user_id)
            if fallback:
                rows = [fallback]
        return [self._role_response(row) for row in rows]

    def has_role(
        self,
        user_id: str,
        role: UserRoleName | str | Iterable[UserRoleName | str],
        scope: UserRoleScope | str | None = None,
        scope_id: str | None = None,
    ) -> bool:
        roles = {str(item) for item in ([role] if isinstance(role, str) else list(role))}
        for row in self._active_role_rows(user_id):
            if str(row.get("role")) not in roles:
                continue
            if not _scope_matches(row, scope, scope_id):
                continue
            return True
        fallback = self._fallback_user_role(user_id)
        if fallback and str(fallback.get("role")) in roles and _scope_matches(fallback, scope, scope_id):
            return True
        return False

    def require_role(
        self,
        user_id: str,
        allowed_roles: Iterable[UserRoleName | str],
        scope: UserRoleScope | str | None = None,
        scope_id: str | None = None,
    ) -> None:
        allowed = [str(item) for item in allowed_roles]
        if self.has_role(user_id, allowed, scope=scope, scope_id=scope_id):
            return
        self.log_permission_event(
            user_id=user_id,
            target_user_id=user_id,
            event_type="unauthorized_access_attempt",
            role=allowed[0] if allowed else None,
            scope=scope,
            scope_id=scope_id,
            event_summary="Unauthorized access attempt blocked by permission service.",
            metadata={"allowed_roles": allowed},
            actor_user_id=user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "permission_denied",
                "message": "You do not have permission to access this resource.",
            },
        )

    def grant_role(
        self,
        target_user_id: str,
        role: UserRoleName | str,
        granted_by: str | None,
        *,
        scope: UserRoleScope | str = "global",
        scope_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UserRoleResponse:
        row = self._exact_role_row(target_user_id, str(role), str(scope), scope_id, active_only=True)
        now = _now()
        if row:
            row["is_active"] = True
            row["revoked_at"] = None
            row["granted_by"] = granted_by
            row["metadata"] = metadata or row.get("metadata") or {}
            row["created_at"] = row.get("created_at") or now
            saved = self._save(_USER_ROLES, row)
        else:
            saved = self._save(
                _USER_ROLES,
                {
                    "id": str(uuid4()),
                    "user_id": target_user_id,
                    "role": str(role),
                    "scope": str(scope),
                    "scope_id": scope_id,
                    "granted_by": granted_by,
                    "is_active": True,
                    "created_at": now,
                    "revoked_at": None,
                    "metadata": metadata or {},
                },
            )
        self.log_permission_event(
            user_id=target_user_id,
            target_user_id=target_user_id,
            event_type=_event_type_for_role(str(role)),
            role=str(role),
            scope=str(scope),
            scope_id=scope_id,
            event_summary=f"Role {role} granted.",
            metadata={"granted_by": granted_by, "metadata": metadata or {}},
            actor_user_id=granted_by,
        )
        return self._role_response(saved)

    def revoke_role(
        self,
        target_user_id: str,
        role: UserRoleName | str,
        revoked_by: str | None,
        *,
        scope: UserRoleScope | str = "global",
        scope_id: str | None = None,
    ) -> UserRoleResponse:
        row = self._exact_role_row(target_user_id, str(role), str(scope), scope_id, active_only=True)
        if not row:
            raise PermissionNotFoundError(f"{target_user_id}:{role}:{scope}")
        row["is_active"] = False
        row["revoked_at"] = _now()
        row["granted_by"] = row.get("granted_by")
        saved = self._save(_USER_ROLES, row)
        self.log_permission_event(
            user_id=target_user_id,
            target_user_id=target_user_id,
            event_type="role_revoked",
            role=str(role),
            scope=str(scope),
            scope_id=scope_id,
            event_summary=f"Role {role} revoked.",
            metadata={"revoked_by": revoked_by},
            actor_user_id=revoked_by,
        )
        return self._role_response(saved)

    def get_current_user_permissions(self, user_id: str) -> CurrentUserPermissionsResponse:
        roles = self._active_role_rows(user_id)
        role_names = self._role_names(user_id)
        permissions = self._permissions_for_roles(role_names)
        dashboard_access = DashboardAccess(
            student_dashboard="student" in role_names,
            recruiter_dashboard="recruiter" in role_names,
            admin_dashboard=bool({"admin", "support"} & set(role_names)),
            reviewer_dashboard=bool({"reviewer", "faculty_reviewer", "company_reviewer"} & set(role_names)),
        )
        self.log_permission_event(
            user_id=user_id,
            target_user_id=user_id,
            event_type="permission_checked",
            event_summary="Current user permissions were requested.",
            metadata={
                "roles": role_names,
                "permissions": permissions,
                "dashboard_access": dashboard_access.model_dump(mode="json"),
            },
            actor_user_id=user_id,
        )
        return CurrentUserPermissionsResponse(
            user_id=user_id,
            roles=role_names,
            permissions=permissions,
            dashboard_access=dashboard_access,
            generated_at=_now(),
        )

    def log_permission_event(
        self,
        *,
        user_id: str,
        target_user_id: str,
        event_type: str,
        role: str | None = None,
        scope: str | None = None,
        scope_id: str | None = None,
        actor_user_id: str | None = None,
        event_summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "id": str(uuid4()),
            "user_id": user_id,
            "target_user_id": target_user_id,
            "event_type": event_type,
            "role": role,
            "scope": scope,
            "scope_id": scope_id,
            "actor_user_id": actor_user_id,
            "event_summary": event_summary,
            "metadata": metadata or {},
            "created_at": _now(),
        }
        return self._insert(_AUDIT_EVENTS, row)

    def _role_names(self, user_id: str) -> list[str]:
        names = [str(row.get("role")) for row in self._active_role_rows(user_id)]
        fallback = self._fallback_user_role(user_id)
        if fallback:
            names.append(str(fallback.get("role")))
        if not names:
            names = ["student"]
        return _unique(names)

    def _permissions_for_roles(self, role_names: list[str]) -> list[str]:
        permissions: list[str] = []
        for role in role_names:
            permissions.extend(_ROLE_PERMISSION_MAP.get(role, []))
        return _unique(permissions)

    def _active_role_rows(self, user_id: str) -> list[dict[str, Any]]:
        rows = [row for row in self._rows(_USER_ROLES) if str(row.get("user_id")) == user_id and row.get("is_active", True)]
        rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return rows

    def _fallback_user_role(self, user_id: str) -> dict[str, Any] | None:
        user = self._by_id(_USERS, user_id)
        if user and user.get("role"):
            role = str(user["role"])
            if role in _ROLE_PERMISSION_MAP:
                return {
                    "id": f"fallback:{user_id}:{role}",
                    "user_id": user_id,
                    "role": role,
                    "scope": "global",
                    "scope_id": None,
                    "granted_by": None,
                    "is_active": True,
                    "created_at": user.get("created_at") or _now(),
                    "revoked_at": None,
                    "metadata": {},
                }
        if not self._active_role_rows(user_id):
            return {
                "id": f"fallback:{user_id}:student",
                "user_id": user_id,
                "role": "student",
                "scope": "global",
                "scope_id": None,
                "granted_by": None,
                "is_active": True,
                "created_at": _now(),
                "revoked_at": None,
                "metadata": {},
            }
        return None

    def _exact_role_row(
        self,
        user_id: str,
        role: str,
        scope: str,
        scope_id: str | None,
        *,
        active_only: bool,
    ) -> dict[str, Any] | None:
        for row in self._rows(_USER_ROLES):
            if str(row.get("user_id")) != user_id:
                continue
            if str(row.get("role")) != role:
                continue
            if str(row.get("scope")) != scope:
                continue
            if scope == "global" and scope_id is None:
                if row.get("scope_id") is not None:
                    continue
            elif scope_id is not None and str(row.get("scope_id") or "") != str(scope_id):
                continue
            if active_only and not row.get("is_active", True):
                continue
            return row
        return None

    def _role_response(self, row: dict[str, Any]) -> UserRoleResponse:
        return UserRoleResponse(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            role=str(row["role"]),
            scope=str(row.get("scope") or "global"),
            scope_id=str(row["scope_id"]) if row.get("scope_id") else None,
            granted_by=str(row["granted_by"]) if row.get("granted_by") else None,
            is_active=bool(row.get("is_active", True)),
            created_at=row["created_at"],
            revoked_at=row.get("revoked_at"),
            metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
        )

    def _rows(self, table: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            return list(self._client.get(table, {}).values())
        result = self._client.table(table).select("*").execute()
        return getattr(result, "data", []) or []

    def _by_id(self, table: str, row_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            return self._client.get(table, {}).get(row_id)
        result = self._client.table(table).select("*").eq("id", row_id).limit(1).execute()
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _save(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        row = make_json_safe(row)
        if isinstance(self._client, dict):
            self._client.setdefault(table, {})[str(row["id"])] = row
            return row
        result = self._client.table(table).upsert(row).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError(f"{table} upsert returned no data.")
        return rows[0]

    def _insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        row = make_json_safe(row)
        if isinstance(self._client, dict):
            self._client.setdefault(table, {})[str(row["id"])] = row
            return row
        result = self._client.table(table).insert(row).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError(f"{table} insert returned no data.")
        return rows[0]


def _scope_matches(row: dict[str, Any], scope: UserRoleScope | str | None, scope_id: str | None) -> bool:
    if scope is not None and str(row.get("scope")) != str(scope):
        return False
    if scope is None:
        return True
    if scope_id is not None:
        return str(row.get("scope_id") or "") == str(scope_id)
    if str(scope) == "global":
        return row.get("scope_id") is None
    return True


def _event_type_for_role(role: str) -> str:
    if role == "admin":
        return "admin_access_granted"
    if role in {"reviewer", "faculty_reviewer", "company_reviewer"}:
        return "reviewer_access_granted"
    return "role_granted"


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _now() -> datetime:
    return datetime.now(UTC)
