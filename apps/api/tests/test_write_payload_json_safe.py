"""Regression tests: Supabase write payloads must be JSON-serializable.

Root cause locked here: several services built insert/upsert rows containing raw
``datetime`` objects (their module-level ``_now()`` returned a ``datetime``).
supabase-py hands request bodies to httpx, which calls ``json.dumps()`` with no
custom encoder, so a raw ``datetime`` raised
``TypeError: Object of type datetime is not JSON serializable`` and surfaced as a
500. This was observed in production on ``GET /api/v1/me/permissions`` (failed
for *every* user) and latent on the recruiter/passport/admin/export write paths.

The dict-backed in-memory test store does NOT exercise this — it stores rows
without serialization. These tests use a fake client that mimics the real
supabase client's JSON boundary so the failure is reproduced and the fix
(``make_json_safe`` at every write helper) is enforced.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.serialization import make_json_safe
from app.services.permission_service import PermissionService


# ── make_json_safe unit coverage ───────────────────────────────────────────────


def test_make_json_safe_coerces_datetime_uuid_nested() -> None:
    now = datetime.now(UTC)
    uid = uuid4()
    payload = {
        "created_at": now,
        "id": uid,
        "meta": {"nested_at": now, "ids": [uid, uid]},
        "list": [now, {"deep": now}],
        "plain": "value",
        "num": 3,
        "flag": True,
        "none": None,
    }
    safe = make_json_safe(payload)
    # Must be json-serializable with the SAME encoder profile httpx uses.
    json.dumps(safe)  # would raise before the fix
    assert safe["created_at"] == now.isoformat()
    assert safe["id"] == str(uid)
    assert safe["meta"]["nested_at"] == now.isoformat()
    assert safe["list"][1]["deep"] == now.isoformat()
    assert safe["plain"] == "value" and safe["num"] == 3 and safe["flag"] is True


# ── Fake Supabase client that enforces the JSON boundary ────────────────────────


class _JsonBoundaryQuery:
    def __init__(self, store: dict, table: str) -> None:
        self._store = store
        self._table = table
        self._filters: list[tuple[str, object]] = []

    def select(self, *_a, **_k):  # noqa: ANN002, ANN003
        return self

    def eq(self, col: str, val: object):
        self._filters.append((col, val))
        return self

    def limit(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def _assert_json(self, row: dict) -> None:
        # Reproduce httpx's json.dumps boundary — raw datetime/UUID would raise.
        json.dumps(row)

    def insert(self, row: dict):
        self._assert_json(row)
        self._store.setdefault(self._table, []).append(row)
        self._pending = [row]
        return self

    def upsert(self, row: dict, **_k):
        self._assert_json(row)
        self._store.setdefault(self._table, []).append(row)
        self._pending = [row]
        return self

    def update(self, row: dict):
        self._assert_json(row)
        self._pending = [row]
        return self

    def execute(self):
        if hasattr(self, "_pending"):
            data = self._pending
        else:
            rows = self._store.get(self._table, [])
            data = [
                r
                for r in rows
                if all(str(r.get(c)) == str(v) for c, v in self._filters)
            ]
        return type("Result", (), {"data": data})()


class _JsonBoundaryClient:
    """Minimal stand-in for the supabase client that raises on non-JSON writes."""

    def __init__(self, seed: dict | None = None) -> None:
        self._store: dict[str, list[dict]] = {}
        for table, rows in (seed or {}).items():
            self._store[table] = list(rows)

    def table(self, name: str) -> _JsonBoundaryQuery:
        return _JsonBoundaryQuery(self._store, name)


# ── End-to-end: /me/permissions write path ─────────────────────────────────────


def test_get_current_user_permissions_writes_json_safe_audit_event() -> None:
    user_id = "11111111-1111-1111-1111-111111111111"
    client = _JsonBoundaryClient(
        seed={
            "users": [{"id": user_id, "email": "u@example.edu", "role": "student"}],
            "user_roles": [],
        }
    )
    svc = PermissionService(client)

    # Before the fix this raised TypeError inside the audit-event insert.
    resp = svc.get_current_user_permissions(user_id)

    assert resp.user_id == user_id
    assert "student" in resp.roles
    # The audit event was actually persisted (not silently dropped) and json-safe.
    events = client._store.get("role_permission_audit_events", [])
    assert len(events) == 1
    assert events[0]["event_type"] == "permission_checked"
    json.dumps(events[0])  # created_at must be a string now


def test_permission_service_insert_helper_serializes_datetime() -> None:
    client = _JsonBoundaryClient()
    svc = PermissionService(client)
    row = {"id": str(uuid4()), "created_at": datetime.now(UTC), "event_type": "x"}
    # Must not raise; created_at coerced to isoformat string.
    svc._insert("role_permission_audit_events", dict(row))
    stored = client._store["role_permission_audit_events"][0]
    assert isinstance(stored["created_at"], str)
