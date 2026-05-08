"""
Supabase client factory.

Two clients are exposed:

* ``get_supabase_client``  — server-side client using the **service-role key**.
  Bypasses RLS. Use only for server-initiated writes (parsers, matchers,
  AI generators). Never return this client or its key to a browser.

* ``get_supabase_anon_client`` — client using the **anon key**.
  Respects RLS. Suitable for operations that must behave as an
  authenticated user (e.g. when forwarding a user JWT).

Both functions are cached with ``lru_cache`` so the underlying HTTP
client is reused across requests.

Usage
-----
from app.db.supabase import get_supabase_client

client = get_supabase_client()
result = client.table("users").select("id").eq("id", user_id).execute()
"""

from __future__ import annotations

import logging
from functools import lru_cache

try:
    from supabase import Client, create_client
    _SUPABASE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SUPABASE_AVAILABLE = False
    Client = object  # type: ignore[assignment,misc]

from app.core.config import settings

logger = logging.getLogger(__name__)


def _require_supabase() -> None:
    if not _SUPABASE_AVAILABLE:
        raise RuntimeError(
            "The 'supabase' package is not installed. "
            "Run: pip install supabase"
        )
    if not settings.supabase_configured:
        raise RuntimeError(
            "Supabase is not configured. "
            "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in your .env file."
        )


@lru_cache(maxsize=1)
def get_supabase_client() -> "Client":
    """
    Return a server-side Supabase client authenticated with the
    service-role key.  Bypasses all RLS policies.

    Never expose this client or its key to frontend code.
    """
    _require_supabase()
    return create_client(
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_service_role_key.get_secret_value(),
    )


@lru_cache(maxsize=1)
def get_supabase_anon_client() -> "Client":
    """
    Return a Supabase client authenticated with the public anon key.
    RLS policies apply — suitable for operations that should behave
    as an end user.  Pass a user JWT via ``client.auth.set_session``
    when acting on behalf of a specific user.
    """
    _require_supabase()
    anon_key = settings.supabase_anon_key.get_secret_value()
    if not anon_key:
        raise RuntimeError(
            "SUPABASE_ANON_KEY is not set. "
            "Set it in your .env file."
        )
    return create_client(
        supabase_url=settings.supabase_url,
        supabase_key=anon_key,
    )
