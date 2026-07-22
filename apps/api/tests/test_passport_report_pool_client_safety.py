"""The passport report thread pool must never share one Supabase client across workers.

Racing the shared sync client from ThreadPoolExecutor workers surfaces
``httpx.ReadError: [Errno 11] Resource temporarily unavailable`` in production
(deterministically for accounts with many projects — the whole private passport
500'd). Each worker thread must build reports with its OWN client from
``create_service_role_client``; dict stores (tests/dev) are shared as-is; a
failing factory falls back to the shared client instead of failing the passport.
"""

from __future__ import annotations

import threading

import pytest

from app.services import vbr_work_passport_service as svc


class _FakeClient:
    """Stands in for a real (non-dict) Supabase client."""

    def __init__(self, name: str) -> None:
        self.name = name


def _projects(n: int) -> list[dict[str, str]]:
    return [{"id": f"p{i}", "title": f"Project {i}"} for i in range(n)]


@pytest.fixture()
def capture_reports(monkeypatch):
    """Record (db, pipeline_db, project id, thread name) for every report build."""
    calls: list[tuple[object, object, str, str]] = []
    lock = threading.Lock()

    def fake_build(db, pipeline_db, project, user_id, include_cross_proof=True):
        with lock:
            calls.append((db, pipeline_db, project["id"], threading.current_thread().name))
        return {"report_for": project["id"]}

    monkeypatch.setattr(svc, "build_student_vbr_report", fake_build)
    return calls


def test_each_worker_thread_gets_its_own_client(monkeypatch, capture_reports):
    shared = _FakeClient("shared-request-client")
    created: list[_FakeClient] = []
    lock = threading.Lock()

    def fake_factory():
        with lock:
            c = _FakeClient(f"fresh-{len(created)}")
            created.append(c)
        return c

    monkeypatch.setattr(svc, "create_service_role_client", fake_factory)

    projects = _projects(6)
    pairs = svc._build_report_pairs(shared, shared, projects, "user-1")

    # Order preserved, one report per project.
    assert [p["id"] for p, _ in pairs] == [p["id"] for p in projects]
    assert [r["report_for"] for _, r in pairs] == [p["id"] for p in projects]

    # No worker ever used the shared request client.
    assert all(db is not shared for db, _, _, _ in capture_reports)
    assert all(db in created for db, _, _, _ in capture_reports)
    # pipeline_db is db in production — workers must keep that identity.
    assert all(pdb is db for db, pdb, _, _ in capture_reports)

    # One fresh client per worker THREAD (not per project).
    by_thread = {}
    for db, _, _, thread_name in capture_reports:
        by_thread.setdefault(thread_name, set()).add(db)
    assert all(len(clients) == 1 for clients in by_thread.values())
    assert len(created) == len(by_thread)


def test_dict_store_is_shared_and_factory_untouched(monkeypatch, capture_reports):
    factory_calls: list[bool] = []
    monkeypatch.setattr(
        svc, "create_service_role_client", lambda: factory_calls.append(True)
    )

    store: dict = {"vbr_projects": {}}
    pipeline_store: dict = {"skill_evidence_pipelines": {}}
    svc._build_report_pairs(store, pipeline_store, _projects(4), "user-1")

    assert factory_calls == []
    assert all(db is store and pdb is pipeline_store for db, pdb, _, _ in capture_reports)


def test_factory_failure_falls_back_to_shared_client(monkeypatch, capture_reports):
    shared = _FakeClient("shared-request-client")

    def broken_factory():
        raise RuntimeError("SUPABASE_URL is not set")

    monkeypatch.setattr(svc, "create_service_role_client", broken_factory)

    pairs = svc._build_report_pairs(shared, shared, _projects(4), "user-1")

    assert len(pairs) == 4
    assert all(db is shared and pdb is shared for db, pdb, _, _ in capture_reports)


def test_single_project_stays_inline_with_shared_client(monkeypatch, capture_reports):
    shared = _FakeClient("shared-request-client")
    monkeypatch.setattr(
        svc,
        "create_service_role_client",
        lambda: (_ for _ in ()).throw(AssertionError("factory must not be called")),
    )

    pairs = svc._build_report_pairs(shared, shared, _projects(1), "user-1")

    assert len(pairs) == 1
    assert capture_reports[0][0] is shared


def test_distinct_pipeline_db_client_also_isolated(monkeypatch, capture_reports):
    """A real pipeline client distinct from db must not leak into workers either."""
    shared_db = _FakeClient("shared-db")
    shared_pipeline = _FakeClient("shared-pipeline")
    created: list[_FakeClient] = []
    lock = threading.Lock()

    def fake_factory():
        with lock:
            c = _FakeClient(f"fresh-{len(created)}")
            created.append(c)
        return c

    monkeypatch.setattr(svc, "create_service_role_client", fake_factory)

    svc._build_report_pairs(shared_db, shared_pipeline, _projects(4), "user-1")

    for db, pdb, _, _ in capture_reports:
        assert db is not shared_db
        assert pdb is not shared_pipeline
