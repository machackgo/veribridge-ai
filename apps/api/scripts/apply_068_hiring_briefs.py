"""Apply the Recruiter Hiring Briefs migration (068) to Supabase.

Usage:
    cd apps/api
    python scripts/apply_068_hiring_briefs.py

Reads DATABASE_URL from .env. Connects via the direct host first, then the
Supabase connection poolers (both aws-1-/aws-0- generations), URL-decoding the
percent-encoded password.

Migrations applied (idempotent / additive-only):
  068_recruiter_hiring_briefs.sql —
      * creates public.recruiter_hiring_briefs (title, raw role text,
        structured requirement plan jsonb, lifecycle status — NO evidence
        snapshots of any kind);
      * creates public.recruiter_hiring_brief_candidates (the role-scoped
        candidate pool: per-(brief, student) review status + private note).
"""

from __future__ import annotations

import os
import pathlib
import sys

try:
    import psycopg2
except ImportError:
    sys.exit(
        "psycopg2 not installed. Run: pip install psycopg2-binary\n"
        "Then re-run: python scripts/apply_068_hiring_briefs.py"
    )

# ── Load .env ─────────────────────────────────────────────────────────────────

env_path = pathlib.Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

database_url = os.environ.get("DATABASE_URL", "")
if not database_url:
    sys.exit("DATABASE_URL not found in .env or environment.")

# ── Parse the URL (handles literal ? in password) ────────────────────────────

def _parse_pg_url(url: str) -> dict:
    """Parse a postgresql:// URL, URL-decoding the (often percent-encoded) password."""
    import urllib.parse

    p = urllib.parse.urlparse(url)
    return {
        "user": urllib.parse.unquote(p.username or "postgres"),
        "password": urllib.parse.unquote(p.password or ""),
        "host": p.hostname or "",
        "port": p.port or 5432,
        "dbname": (p.path or "/postgres").lstrip("/") or "postgres",
    }

params = _parse_pg_url(database_url)

ref = params["host"].removeprefix("db.").split(".supabase.co")[0]
pooler_user = f"postgres.{ref}" if ref else params["user"]

connect_attempts = [
    {"host": params["host"], "port": params["port"], "user": params["user"]},
]
for pooler_host in (
    "aws-1-us-east-1.pooler.supabase.com",
    "aws-0-us-east-1.pooler.supabase.com",
):
    connect_attempts.append({"host": pooler_host, "port": 5432, "user": pooler_user})
    connect_attempts.append({"host": pooler_host, "port": 6543, "user": pooler_user})

conn = None
for attempt in connect_attempts:
    try:
        conn = psycopg2.connect(
            host=attempt["host"],
            port=attempt["port"],
            dbname=params["dbname"],
            user=attempt["user"],
            password=params["password"],
            sslmode="require",
            connect_timeout=15,
        )
        print(f"Connected to {attempt['host']}:{attempt['port']}")
        break
    except psycopg2.OperationalError as exc:
        print(f"  Could not connect to {attempt['host']}:{attempt['port']}: {exc}")

if conn is None:
    sys.exit("All connection attempts failed. Check DATABASE_URL in .env.")

# ── Read and apply migrations ─────────────────────────────────────────────────

MIGRATIONS = [
    "068_recruiter_hiring_briefs.sql",
]

migrations_dir = pathlib.Path(__file__).parent.parent / "app" / "db" / "migrations"

try:
    cur = conn.cursor()
    for filename in MIGRATIONS:
        path = migrations_dir / filename
        if not path.exists():
            conn.rollback()
            sys.exit(f"Migration file not found: {path}")
        sql = path.read_text()
        cur.execute(sql)
        conn.commit()
        print(f"  {filename} applied.")
    print("\nAll migrations applied successfully.")
    print(
        "recruiter_hiring_briefs and recruiter_hiring_brief_candidates are ready."
    )

    # Refresh PostgREST's schema cache so the new tables are visible without a
    # backend restart.
    cur.execute("NOTIFY pgrst, 'reload schema';")
    conn.commit()
    print("\nPostgREST schema reload requested: NOTIFY pgrst, 'reload schema';")
except Exception as exc:
    conn.rollback()
    sys.exit(f"Migration failed: {exc}")
finally:
    conn.close()
