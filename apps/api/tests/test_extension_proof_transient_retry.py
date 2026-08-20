"""Extension-proof transient-transport retry (V1.0.1 production 503 regression).

Live incident (2026-08-20, session 839c9464): POST /sessions/{id}/start hit
``httpcore.ReadError: [Errno 11] Resource temporarily unavailable`` on the
shared sync httpx transport while the underlying status UPDATE had actually
committed — the blanket except turned an already-successful transition into a
client-facing 503, splitting the web UI ("start failed") from the extension
(recording) and the backend (recording).

These tests pin the fix: owner-scoped reads and idempotent absolute-value
updates in ExtensionProofSessionService retry ONCE on a fresh client for
transient transport errors, and non-transient errors still fail closed.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.db import supabase as supabase_module
from app.db.supabase import is_transient_transport_error, run_with_transient_retry
from app.services.extension_proof_service import ExtensionProofSessionService


class ReadError(Exception):
    """Name-matched stand-in for httpcore.ReadError."""


class _Result:
    def __init__(self, data: Any) -> None:
        self.data = data


class _QueryChain:
    """Minimal PostgREST chain that raises per an injected schedule."""

    def __init__(self, owner: "_FakeClient", kind: str) -> None:
        self._owner = owner
        self._kind = kind

    def select(self, *_a: Any, **_k: Any) -> "_QueryChain":
        return self

    def update(self, updates: dict[str, Any]) -> "_QueryChain":
        self._owner.last_updates = dict(updates)
        return self

    def eq(self, *_a: Any, **_k: Any) -> "_QueryChain":
        return self

    def maybe_single(self) -> "_QueryChain":
        return self

    def execute(self) -> _Result:
        return self._owner.execute(self._kind)


class _FakeClient:
    """Non-dict client whose Nth call can raise a scheduled exception."""

    def __init__(self, row: dict[str, Any], fail_first: list[str]) -> None:
        self.row = row
        self.fail_first = list(fail_first)  # kinds that fail on their first call
        self.calls: list[str] = []
        self.last_updates: dict[str, Any] = {}

    def table(self, _name: str) -> Any:
        client = self

        class _Table:
            def select(self, *a: Any, **k: Any) -> _QueryChain:
                return _QueryChain(client, "select").select(*a, **k)

            def update(self, updates: dict[str, Any]) -> _QueryChain:
                return _QueryChain(client, "update").update(updates)

        return _Table()

    def execute(self, kind: str) -> _Result:
        self.calls.append(kind)
        if kind in self.fail_first:
            self.fail_first.remove(kind)
            raise ReadError("[Errno 11] Resource temporarily unavailable")
        if kind == "select":
            return _Result(dict(self.row))
        # update: apply absolute values, return updated row — mirrors the
        # lost-response reality where the first attempt already committed.
        self.row.update(self.last_updates)
        return _Result([dict(self.row)])


SESSION_ROW = {
    "id": "sess-1",
    "user_id": "user-1",
    "skill_evidence_id": "ev-1",
    "status": "created",
    "project_id": None,
    "website_url": "https://veribridgeai.com/",
    "claimed_skills": ["Research"],
    "proof_objective": "obj",
    "proof_upload_id": None,
    "started_at": None,
    "metadata": {},
    "created_at": "2026-08-20T00:00:00+00:00",
    "updated_at": "2026-08-20T00:00:00+00:00",
}


@pytest.fixture()
def fresh_client_patch(monkeypatch: pytest.MonkeyPatch):
    """Route the retry's fresh-client factory to the SAME fake so the second
    attempt is observable without a real Supabase environment."""

    def _patch(client: _FakeClient) -> None:
        monkeypatch.setattr(supabase_module, "create_service_role_client", lambda: client)

    return _patch


def test_transient_classifier_matches_transport_errors_only() -> None:
    assert is_transient_transport_error(ReadError("[Errno 11] Resource temporarily unavailable"))
    assert is_transient_transport_error(ReadError("boom"))  # name-matched
    assert not is_transient_transport_error(ValueError("Resource exhausted"))
    assert not is_transient_transport_error(KeyError("status"))


def test_run_with_transient_retry_retries_once_then_succeeds(fresh_client_patch) -> None:
    client = _FakeClient(dict(SESSION_ROW), fail_first=["select"])
    fresh_client_patch(client)
    calls: list[str] = []

    def op(db: Any) -> str:
        calls.append("attempt")
        return db.table("t").select("*").eq("a", "b").maybe_single().execute().data["id"]

    assert run_with_transient_retry(client, op) == "sess-1"
    assert calls == ["attempt", "attempt"]


def test_run_with_transient_retry_never_retries_non_transient() -> None:
    attempts: list[int] = []

    class _Boom:
        def table(self, _n: str) -> Any:
            raise ValueError("schema drift")

    def op(db: Any) -> Any:
        attempts.append(1)
        return db.table("t")

    with pytest.raises(ValueError):
        run_with_transient_retry(_Boom(), op)
    assert attempts == [1]


def test_start_session_survives_transient_read_error_on_update(fresh_client_patch) -> None:
    # The exact live 503: _get_row succeeds, the status UPDATE raises a
    # transport ReadError. The retry re-issues the idempotent absolute-value
    # update and the start completes instead of 503ing.
    client = _FakeClient(dict(SESSION_ROW), fail_first=["update"])
    fresh_client_patch(client)
    response = ExtensionProofSessionService(client).start_session("user-1", "sess-1")
    assert response.status == "recording"
    assert client.calls == ["select", "update", "update"]


def test_start_session_survives_transient_read_error_on_read(fresh_client_patch) -> None:
    client = _FakeClient(dict(SESSION_ROW), fail_first=["select"])
    fresh_client_patch(client)
    response = ExtensionProofSessionService(client).start_session("user-1", "sess-1")
    assert response.status == "recording"


def test_project_list_read_survives_transient_transport_error(fresh_client_patch) -> None:
    # GET /student/vbr/projects feeds the Website Proof completion flow's
    # attach-project UI; the same live transport race surfaced there as an
    # unhandled 500. The owner-scoped read retries once and succeeds.
    from app.api.v1.endpoints.vbr_projects import list_projects

    project_row = {
        "id": "proj-1",
        "user_id": "user-1",
        "title": "P",
        "repo_url": "https://github.com/a/b",
        "repo_full_name": "a/b",
        "deployed_url": None,
        "head_sha": None,
        "status": "draft",
        "metadata": {},
        "created_at": "2026-08-20T00:00:00+00:00",
        "updated_at": "2026-08-20T00:00:00+00:00",
    }

    class _ListClient(_FakeClient):
        def execute(self, kind: str) -> _Result:
            self.calls.append(kind)
            if kind in self.fail_first:
                self.fail_first.remove(kind)
                raise ReadError("[Errno 11] Resource temporarily unavailable")
            return _Result([dict(project_row)])

        def table(self, _name: str) -> Any:
            client = self

            class _Table:
                def select(self, *_a: Any, **_k: Any) -> Any:
                    class _Chain:
                        def eq(self, *_a: Any, **_k: Any) -> "_Chain":
                            return self

                        def order(self, *_a: Any, **_k: Any) -> "_Chain":
                            return self

                        def execute(self) -> _Result:
                            return client.execute("select")

                    return _Chain()

            return _Table()

    client = _ListClient({}, fail_first=["select"])
    fresh_client_patch(client)
    projects = list_projects(user_id="user-1", db=client)
    assert [p.id for p in projects] == ["proj-1"]
    assert client.calls == ["select", "select"]


def test_start_session_is_idempotent_after_lost_response_applied() -> None:
    # Lost-response reconciliation: the first attempt's UPDATE committed
    # server-side, so a client retry finds status already "recording" and gets
    # the same successful answer with the original started_at preserved.
    row = {**SESSION_ROW, "status": "recording", "started_at": "2026-08-20T05:00:20+00:00"}
    store: dict = {"extension_proof_sessions": {"sess-1": row}}
    response = ExtensionProofSessionService(store).start_session("user-1", "sess-1")
    assert response.status == "recording"
    assert response.started_at == "2026-08-20T05:00:20+00:00"
