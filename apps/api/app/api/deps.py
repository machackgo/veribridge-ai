"""
FastAPI shared dependencies.

Override these in tests via ``app.dependency_overrides``:

    from app.api.deps import get_db, get_current_user_id
    app.dependency_overrides[get_db] = lambda: mock_supabase_client
    app.dependency_overrides[get_current_user_id] = lambda: "some-uuid"
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.db.supabase import get_supabase_client


def get_db() -> Any:
    """
    Return the Supabase service-role client.

    Overridden in unit tests with a mock so no real network calls are made.
    """
    return get_supabase_client()


def get_current_user_id() -> str:
    """
    Return the ID of the currently acting user.

    Pre-auth placeholder: reads DEMO_USER_ID from settings.
    Default value is ``00000000-0000-0000-0000-000000000001`` — a
    clearly fake UUID that will not collide with real Supabase users.

    Replace this dependency with a real JWT-validation dependency
    once Supabase Auth is integrated.
    """
    return settings.demo_user_id
