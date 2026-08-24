"""
Supabase client factory and typed exception hierarchy.

Exception hierarchy
-------------------
SupabaseError              (base — catch-all for all Supabase-originated errors)
  SupabaseConnectionError  — network failure (DNS, refused, timeout)
  SupabaseAPIError         — PostgREST returned a non-2xx error
  SupabaseFKError          — 23503 foreign-key constraint violation

Endpoints map these to HTTP status codes:
  SupabaseConnectionError → 503
  SupabaseAPIError        → 503
  SupabaseFKError         → 409
  (unknown exceptions)    → 500 JSON

Client functions
----------------
get_supabase_client()      — service-role key, bypasses RLS.
                             Use for server-side writes (parsers, AI, etc.).
                             Never expose to browsers.
get_supabase_anon_client() — anon key, RLS applies.
                             Use when acting as an end user.

Both are cached PER THREAD so the HTTP session is reused across requests
without ever being shared by two requests in flight at the same time — the
underlying ``httpx`` sync transport is not concurrency-safe (see
:func:`get_supabase_client`).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

try:
    from supabase import Client, create_client
    _SUPABASE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SUPABASE_AVAILABLE = False
    Client = object  # type: ignore[assignment,misc]

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Typed exception hierarchy ─────────────────────────────────────────────────


class SupabaseError(RuntimeError):
    """Base class for all Supabase-originated errors."""


class SupabaseConnectionError(SupabaseError):
    """
    Network failure — DNS resolution, connection refused, timeout.
    Maps to HTTP 503 Service Unavailable.
    """


class SupabaseAPIError(SupabaseError):
    """
    PostgREST returned a non-2xx response (bad query, permission denied, …).
    Maps to HTTP 503 Service Unavailable.
    """


class SupabaseFKError(SupabaseError):
    """
    PostgreSQL error 23503 — foreign-key constraint violation.
    Typically means the demo user row does not exist in public.users.
    Maps to HTTP 409 Conflict.
    """


# ── Config guard ──────────────────────────────────────────────────────────────


def _require_supabase() -> None:
    if not _SUPABASE_AVAILABLE:
        raise RuntimeError(
            "The 'supabase' package is not installed. "
            "Run: pip install 'supabase>=2.3.0,<3.0.0'"
        )
    if not settings.supabase_url:
        raise RuntimeError(
            "SUPABASE_URL is not set. "
            "Add it to .env: https://yourref.supabase.co"
        )
    if not settings.supabase_service_role_key.get_secret_value():
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY is not set. "
            "Find it in: Supabase dashboard → Settings → API → service_role."
        )
    logger.debug("Supabase target: %s", settings.supabase_url_host)


# ── Client factories ──────────────────────────────────────────────────────────


def create_service_role_client() -> "Client":
    """
    Create a NEW (uncached) server-side Supabase client using the service-role
    key. Bypasses all RLS policies.

    A Supabase client is NOT safe to use from multiple threads concurrently —
    racing requests through its single sync httpx transport surfaces
    ``httpx.ReadError: [Errno 11/35] Resource temporarily unavailable``.
    :func:`get_supabase_client` therefore hands out one client PER THREAD;
    callers that fan work out to their own thread pool use this factory
    directly to give each worker its own client. Construction is purely local
    (no network call).
    """
    _require_supabase()
    return create_client(
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_service_role_key.get_secret_value(),
    )


def is_transient_transport_error(exc: Exception) -> bool:
    """True for socket/transport-level failures of a Supabase client's sync
    httpx transport.

    A request that hits a stale keepalive/HTTP2 connection surfaces
    ``httpx/httpcore ReadError: [Errno 11/35] Resource temporarily
    unavailable`` and similar — the request may or may not have reached
    PostgREST, but the CLIENT never saw a response. Retrying once on a fresh
    client is safe for reads and for idempotent absolute-value writes.

    Since :func:`get_supabase_client` became per-thread these are residual
    (stale-connection) failures rather than the systematic concurrency race
    that used to make two in-flight requests 500.

    (Verified in production 2026-08-20: POST /student/extension-proof/
    sessions/{id}/start returned 503 from exactly this ReadError while the
    underlying status UPDATE had actually committed — a lost response.)
    """
    text = f"{type(exc).__module__}.{type(exc).__name__}: {exc}"
    return any(
        marker in text
        for marker in (
            "httpx.", "httpcore.", "ReadError", "WriteError",
            "Resource temporarily unavailable", "ConnectionTerminated",
            "RemoteProtocolError", "ConnectError",
        )
    )


def run_with_transient_retry(db: "Client | Any", fn: Any, *, op: str = "db operation") -> Any:
    """Run ``fn(db)``; on a transient transport race, retry ONCE on a fresh
    service-role client. ``fn`` must be a read or an idempotent write (absolute
    values, ownership-scoped filters) — the original attempt may have already
    been applied server-side when the response was lost.

    Dict-backed test stores run ``fn`` directly (no transport to race).
    """
    if isinstance(db, dict):
        return fn(db)
    try:
        return fn(db)
    except Exception as exc:
        if not is_transient_transport_error(exc):
            raise
        logger.warning(
            "%s hit a transient Supabase transport error; retrying once on a "
            "fresh client: %s", op, exc,
        )
        return fn(create_service_role_client())


# ── Per-thread client cache ────────────────────────────────────────────
#
# A supabase-py Client owns ONE synchronous httpx transport, and that
# transport is not safe for concurrent use. FastAPI runs every ``def``
# (non-async) endpoint in AnyIO's worker thread pool, so a single
# process-wide client meant that two requests in flight at the same moment
# read from the same socket — which surfaces as
#
#     httpcore.ReadError: [Errno 11] Resource temporarily unavailable
#
# and an unhandled 500, while the very same request succeeds when issued
# serially. (Reproduced against production 2026-08-24: 25/25 serial reads of
# GET /api/v1/public/p/{slug} returned 200; run 16-way concurrent, 6 of 50
# returned 500 with exactly that traceback. Real user traffic on
# GET /student/vbr/projects/{id}/questions hit it the same day.)
#
# Caching PER THREAD keeps connection reuse (the worker pool is bounded and
# its threads are long-lived) while guaranteeing no two concurrent requests
# ever share a transport. Retries elsewhere in the codebase remain as a
# belt-and-braces guard for genuinely stale connections; they are no longer
# load-bearing for correctness under concurrency.

_thread_state = threading.local()


def get_supabase_client() -> "Client":
    """
    Return a server-side Supabase client using the service-role key.
    Bypasses all RLS policies.

    One client per calling THREAD (never shared with a concurrently running
    request — see the note above). The client does not make a network call on
    construction; the first actual query triggers the connection.
    """
    client = getattr(_thread_state, "service_client", None)
    if client is None:
        client = create_service_role_client()
        _thread_state.service_client = client
    return client


def create_anon_client() -> "Client":
    """Create a NEW (uncached) Supabase client using the public anon key."""
    _require_supabase()
    anon_key = settings.supabase_anon_key.get_secret_value()
    if not anon_key:
        raise RuntimeError(
            "SUPABASE_ANON_KEY is not set. "
            "Find it in: Supabase dashboard → Settings → API → anon key."
        )
    return create_client(
        supabase_url=settings.supabase_url,
        supabase_key=anon_key,
    )


def get_supabase_anon_client() -> "Client":
    """
    Return a Supabase client using the public anon key.
    RLS policies apply — use for operations that act as an end user.

    One client per calling THREAD, for the same reason as
    :func:`get_supabase_client`.
    """
    client = getattr(_thread_state, "anon_client", None)
    if client is None:
        client = create_anon_client()
        _thread_state.anon_client = client
    return client


def reset_supabase_clients() -> None:
    """Drop this thread's cached clients (tests / config changes)."""
    _thread_state.service_client = None
    _thread_state.anon_client = None
