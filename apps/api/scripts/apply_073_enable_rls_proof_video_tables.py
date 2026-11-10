"""Apply the proof/video RLS migration (073) to Supabase.

Usage:
    cd apps/api
    python scripts/apply_073_enable_rls_proof_video_tables.py

Reads DATABASE_URL from .env. Connects via the direct host first, then the
Supabase connection poolers (both aws-1-/aws-0- generations), URL-decoding the
percent-encoded password.

Migrations applied (idempotent):
  073_enable_rls_proof_video_tables.sql —
      enables Row Level Security (no policies) on proof_artifacts,
      video_proofs, video_proof_transcript_segments and video_proof_frames,
      so the anon/authenticated roles can no longer reach them directly.
      The API uses the service-role client and is unaffected.
      The file manages its own transaction (BEGIN ... COMMIT with a 5 s
      lock_timeout) and uses ALTER TABLE IF EXISTS, so tables that were never
      created are reported as absent instead of failing the whole run.
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
        "Then re-run: python scripts/apply_073_enable_rls_proof_video_tables.py"
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
    "073_enable_rls_proof_video_tables.sql",
]

TABLES = (
    "proof_artifacts",
    "video_proofs",
    "video_proof_transcript_segments",
    "video_proof_frames",
)

migrations_dir = pathlib.Path(__file__).parent.parent / "app" / "db" / "migrations"

# The migration file contains its own BEGIN/COMMIT, so run it in autocommit
# mode rather than inside psycopg2's implicit transaction.
conn.autocommit = True

try:
    cur = conn.cursor()
    for filename in MIGRATIONS:
        path = migrations_dir / filename
        if not path.exists():
            sys.exit(f"Migration file not found: {path}")
        sql = path.read_text()
        cur.execute(sql)
        print(f"  {filename} applied.")

    cur.execute(
        "select c.relname, c.relrowsecurity from pg_class c "
        "join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'public' and c.relkind in ('r', 'p') and c.relname = any(%s)",
        (list(TABLES),),
    )
    present = dict(cur.fetchall())
    absent = [t for t in TABLES if t not in present]
    remaining = [t for t, rls in present.items() if not rls]
    if absent:
        print("Absent (never created, nothing to protect): " + ", ".join(absent))
    if remaining:
        sys.exit(f"RLS still disabled on: {', '.join(remaining)}")
    print("\nRLS enabled on: " + (", ".join(t for t in TABLES if t in present) or "(none present)"))
except Exception as exc:
    sys.exit(f"Migration failed: {exc}")
finally:
    conn.close()
