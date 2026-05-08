#!/usr/bin/env python3
"""
create_demo_auth_user.py
========================
One-time local development helper.

Creates a Supabase Auth user for local demo/testing without using the
Supabase dashboard UI (useful when the dashboard shows
"Failed to retrieve users / Failed to run sql query").

What it does
------------
1. Loads SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from apps/api/.env.
2. Prompts you for a temporary password via getpass (never echoed).
3. Creates the auth user with email_confirm = True.
4. Prints only the user ID and email — never prints any secret value.
5. If the user already exists, finds it and shows the existing ID.

What it does NOT do
-------------------
- Does NOT print SUPABASE_SERVICE_ROLE_KEY or any other secret.
- Does NOT store the password anywhere.
- Does NOT insert into public.users (that is done by
  POST /api/v1/debug/bootstrap-demo-user).

Usage
-----
From the project root:
    python apps/api/scripts/create_demo_auth_user.py

Or from apps/api/:
    python scripts/create_demo_auth_user.py

Requirements
------------
supabase>=2.3.0 must be installed (it is in requirements.txt).
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path


# ── 1. Locate and load .env ───────────────────────────────────────────────────

def _load_env_file(env_path: Path) -> None:
    """
    Minimal .env loader — sets os.environ without printing values.

    Handles:
    - KEY=value
    - KEY="value"  (strips outer quotes)
    - KEY='value'  (strips outer quotes)
    - # comments and blank lines
    """
    if not env_path.exists():
        print(f"[error] .env file not found: {env_path}", file=sys.stderr)
        print(
            "        Copy .env.example to .env and fill in your credentials.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(env_path) as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, raw_value = line.partition("=")
            key = key.strip()
            # Strip inline comments (value ends at first unquoted #)
            value = raw_value.strip()
            # Strip matching outer quotes
            if len(value) >= 2 and (
                (value[0] == '"' and value[-1] == '"')
                or (value[0] == "'" and value[-1] == "'")
            ):
                value = value[1:-1]
            # Only set if not already in environment (env vars win over file)
            os.environ.setdefault(key, value)


def _find_env_file() -> Path:
    """
    Locate apps/api/.env regardless of where the script is called from.
    Searches upward from the script's location.
    """
    script_dir = Path(__file__).resolve().parent  # apps/api/scripts/
    api_dir = script_dir.parent                   # apps/api/
    candidate = api_dir / ".env"
    if candidate.exists():
        return candidate
    # Fallback: current working directory
    cwd_candidate = Path.cwd() / ".env"
    if cwd_candidate.exists():
        return cwd_candidate
    return candidate  # will fail with a clear message in _load_env_file


# ── 2. Validate config (without printing secrets) ────────────────────────────

def _get_required_env(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        print(f"[error] {key} is not set in .env", file=sys.stderr)
        sys.exit(1)
    return value


def _validate_supabase_url(url: str) -> None:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme != "https":
        print(
            f"[error] SUPABASE_URL must start with 'https://'. "
            f"Found scheme: {parsed.scheme!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    host = parsed.netloc.lower()
    if not host.endswith(".supabase.co"):
        print(
            f"[error] SUPABASE_URL host must end with '.supabase.co'. "
            f"Got: {host!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    if host.startswith("db."):
        print(
            f"[error] SUPABASE_URL looks like the Postgres host (db.*). "
            f"Use the REST API host: https://{host[3:]}",
            file=sys.stderr,
        )
        sys.exit(1)


# ── 3. Create or find the auth user ──────────────────────────────────────────

DEMO_EMAIL = "mohammedmubashir@wpi.edu"
DEMO_FULL_NAME = "Mohammed Mubashir Uddin Faraz"


def _find_existing_user(admin_client, email: str):
    """
    Search for an existing auth user by email.
    Returns the User object or None.
    """
    page = 1
    per_page = 50
    while True:
        users = admin_client.list_users(page=page, per_page=per_page)
        if not users:
            return None
        for user in users:
            if (user.email or "").lower() == email.lower():
                return user
        if len(users) < per_page:
            return None  # exhausted all pages
        page += 1


def main() -> None:
    print()
    print("VeriBridge AI — Demo Auth User Setup")
    print("=" * 42)

    # ── Load env ──────────────────────────────────────────────────
    env_path = _find_env_file()
    _load_env_file(env_path)
    print(f"[ok] Loaded environment from: {env_path}")

    supabase_url = _get_required_env("SUPABASE_URL")
    service_role_key = _get_required_env("SUPABASE_SERVICE_ROLE_KEY")

    _validate_supabase_url(supabase_url)
    from urllib.parse import urlparse
    host = urlparse(supabase_url).netloc
    print(f"[ok] Supabase host: {host}")

    # ── Prompt for password (never echoed, never stored) ──────────
    print()
    print(f"Creating auth user: {DEMO_EMAIL}")
    print("Enter a temporary password for this demo account.")
    print("(Must be ≥ 8 characters. It will not be printed or saved.)")
    print()
    password = getpass.getpass("Password: ")
    if len(password) < 8:
        print("[error] Password must be at least 8 characters.", file=sys.stderr)
        sys.exit(1)
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("[error] Passwords do not match.", file=sys.stderr)
        sys.exit(1)

    # ── Build client ──────────────────────────────────────────────
    try:
        from supabase import create_client
    except ImportError:
        print(
            "[error] supabase package not installed. "
            "Run: pip install 'supabase>=2.3.0,<3.0.0'",
            file=sys.stderr,
        )
        sys.exit(1)

    client = create_client(
        supabase_url=supabase_url,
        supabase_key=service_role_key,  # service role — never printed
    )
    admin = client.auth.admin

    # ── Attempt creation ──────────────────────────────────────────
    print()
    print("[...] Creating auth user ...")

    try:
        from supabase_auth import AdminUserAttributes
        response = admin.create_user(
            AdminUserAttributes(
                email=DEMO_EMAIL,
                password=password,
                email_confirm=True,         # skip email verification link
                user_metadata={
                    "full_name": DEMO_FULL_NAME,
                },
            )
        )
        user = response.user
        _print_success(user, created=True)

    except Exception as exc:
        exc_name = type(exc).__name__
        exc_msg = str(exc)

        # Handle "already registered" gracefully
        if _is_already_exists_error(exc_msg):
            print(f"[info] A user with email {DEMO_EMAIL!r} already exists.")
            print("[...] Looking up the existing user ...")
            existing = _find_existing_user(admin, DEMO_EMAIL)
            if existing:
                _print_success(existing, created=False)
            else:
                print(
                    "[warn] Could not retrieve the existing user via list_users. "
                    "Check Supabase dashboard → Authentication → Users manually.",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            # Unexpected error — print class name and message, NOT the key
            print(
                f"[error] Auth user creation failed ({exc_name}): {exc_msg}",
                file=sys.stderr,
            )
            print(
                "        If this is a permissions error, verify that "
                "SUPABASE_SERVICE_ROLE_KEY is correct in .env.",
                file=sys.stderr,
            )
            sys.exit(1)


def _is_already_exists_error(message: str) -> bool:
    low = message.lower()
    return any(phrase in low for phrase in (
        "user already registered",
        "already been registered",
        "already exists",
        "email address is already",
        "duplicate key",
        "unique constraint",
    ))


def _print_success(user, created: bool) -> None:
    action = "Created" if created else "Found existing"
    print()
    print("=" * 42)
    print(f"[ok] {action} auth user")
    print(f"     ID    : {user.id}")
    print(f"     Email : {user.email}")
    print("=" * 42)
    print()
    print("Next steps:")
    print()
    print("  1. Copy the user ID above, then open apps/api/.env and set:")
    print()
    print(f"         DEMO_USER_ID={user.id}")
    print()
    print("  2. Restart the backend:")
    print()
    print("         uvicorn app.main:app --reload --port 8000")
    print()
    print("  3. Bootstrap the public.users row:")
    print()
    print("         curl -s -X POST http://localhost:8000/api/v1/debug/bootstrap-demo-user \\")
    print("           | python3 -m json.tool")
    print()
    print("  4. Create your student profile:")
    print()
    print("         curl -s -X PUT http://localhost:8000/api/v1/student/profile \\")
    print("           -H 'Content-Type: application/json' \\")
    print("           -d '{\"full_name\":\"Mohammed Mubashir Uddin Faraz\"," )
    print('                "university":"WPI","degree":"M.S.","major":"Computer Science"}\' \\')
    print("           | python3 -m json.tool")
    print()
    print("  5. Verify:")
    print()
    print("         curl -s http://localhost:8000/api/v1/student/profile \\")
    print("           | python3 -m json.tool")
    print()


if __name__ == "__main__":
    main()
