"""Per-thread Supabase clients — the Work Passport concurrency regression.

Live production defect (2026-08-24, API @ e3fdea90): the Work Passport surface
issues two Supabase-backed reads at once (the passport endpoint and the
disclosure endpoint). Both landed in FastAPI's AnyIO worker thread pool, and
both received the SAME process-wide ``lru_cache``-d Supabase client — so two
requests read from one synchronous httpx transport at the same moment.

Reproduction against production before the fix:

    GET /api/v1/public/p/{slug} x25, serial      -> 25x 200
    GET /api/v1/public/p/{slug} x50, 16-way conc ->  6x 500

with ``httpcore.ReadError: [Errno 11] Resource temporarily unavailable`` in the
server log for each 500. Real user traffic on
``GET /student/vbr/projects/{id}/questions`` hit the same traceback that day.

The fix is the root cause, not a retry: a client is now cached PER THREAD, so
two concurrently-running requests can never share a transport. These tests pin
that property.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.db import supabase as supabase_module


class _FakeClient:
    """Stand-in for supabase-py's Client — identity is all that matters here."""

    _counter = 0
    _lock = threading.Lock()

    def __init__(self) -> None:
        with _FakeClient._lock:
            _FakeClient._counter += 1
            self.serial = _FakeClient._counter


def _install_fake_factory(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        supabase_module, "create_service_role_client", lambda: _FakeClient()
    )
    monkeypatch.setattr(supabase_module, "create_anon_client", lambda: _FakeClient())
    # Start from a clean per-thread cache on the calling thread.
    supabase_module.reset_supabase_clients()


def test_same_thread_reuses_one_client(monkeypatch: Any) -> None:
    """Connection reuse is preserved: repeat calls on one thread are cached."""
    _install_fake_factory(monkeypatch)
    first = supabase_module.get_supabase_client()
    assert supabase_module.get_supabase_client() is first
    assert supabase_module.get_supabase_client() is first


def test_concurrent_threads_never_share_a_client(monkeypatch: Any) -> None:
    """THE regression: no two worker threads may hold the same transport.

    Every thread is held at a barrier until all of them have obtained a
    client, so the clients provably coexist — a process-wide cache would hand
    back one shared object and fail this outright.
    """
    _install_fake_factory(monkeypatch)
    workers = 8
    barrier = threading.Barrier(workers)

    def obtain() -> int:
        client = supabase_module.get_supabase_client()
        barrier.wait(timeout=10)
        # Still the same object after the barrier: caching is per thread, not
        # per call, so the thread keeps reusing its own connection.
        assert supabase_module.get_supabase_client() is client
        return id(client)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        ids = list(pool.map(lambda _: obtain(), range(workers)))

    assert len(set(ids)) == workers, (
        "concurrent threads shared a Supabase client — the httpx transport "
        "would be raced and surface httpcore.ReadError as an unhandled 500"
    )


def test_anon_client_is_also_per_thread(monkeypatch: Any) -> None:
    _install_fake_factory(monkeypatch)
    workers = 4
    barrier = threading.Barrier(workers)

    def obtain() -> int:
        client = supabase_module.get_supabase_anon_client()
        barrier.wait(timeout=10)
        return id(client)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        ids = list(pool.map(lambda _: obtain(), range(workers)))

    assert len(set(ids)) == workers


def test_service_and_anon_clients_are_distinct(monkeypatch: Any) -> None:
    """Different key scopes must never collapse onto one cached client."""
    _install_fake_factory(monkeypatch)
    assert (
        supabase_module.get_supabase_client()
        is not supabase_module.get_supabase_anon_client()
    )


def test_reset_drops_this_threads_clients(monkeypatch: Any) -> None:
    _install_fake_factory(monkeypatch)
    first = supabase_module.get_supabase_client()
    supabase_module.reset_supabase_clients()
    assert supabase_module.get_supabase_client() is not first


def test_get_db_dependency_is_per_thread(monkeypatch: Any) -> None:
    """The FastAPI dependency itself — every sync endpoint resolves through it."""
    from app.api.deps import get_db

    _install_fake_factory(monkeypatch)
    workers = 6
    barrier = threading.Barrier(workers)

    def obtain() -> int:
        db = get_db()
        barrier.wait(timeout=10)
        return id(db)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        ids = list(pool.map(lambda _: obtain(), range(workers)))

    assert len(set(ids)) == workers
