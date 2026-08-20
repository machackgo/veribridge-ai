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

Both are lru_cache-ed so the HTTP session is reused across requests.
"""

from __future__ import annotations

import logging
from functools import lru_cache
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

    The process-wide cached client from :func:`get_supabase_client` is NOT safe
    to use from multiple threads concurrently — racing requests through its
    single sync httpx transport surfaces ``httpx.ReadError: [Errno 11/35]
    Resource temporarily unavailable``. Callers that fan work out to a thread
    pool must give each worker thread its own client from this factory.
    Construction is purely local (no network call).
    """
    _require_supabase()
    return create_client(
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_service_role_key.get_secret_value(),
    )


def is_transient_transport_error(exc: Exception) -> bool:
    """True for socket/transport-level failures of the SHARED sync httpx
    transport inside the process-wide cached Supabase client.

    Requests racing that single transport (or hitting a stale keepalive/HTTP2
    connection) surface ``httpx/httpcore ReadError: [Errno 11/35] Resource
    temporarily unavailable`` and similar — the request may or may not have
    reached PostgREST, but the CLIENT never saw a response. Retrying once on a
    fresh client is safe for reads and for idempotent absolute-value writes.

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


@lru_cache(maxsize=1)
def get_supabase_client() -> "Client":
    """
    Return a server-side Supabase client using the service-role key.
    Bypasses all RLS policies.

    The client does not make a network call on construction — the first
    actual query call triggers the connection.
    """
    return create_service_role_client()


@lru_cache(maxsize=1)
def get_supabase_anon_client() -> "Client":
    """
    Return a Supabase client using the public anon key.
    RLS policies apply — use for operations that act as an end user.
    """
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
