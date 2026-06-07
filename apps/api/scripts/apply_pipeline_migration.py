"""Apply skill-pipeline migrations (047 + 048) to Supabase.

Usage:
    cd apps/api
    python scripts/apply_pipeline_migration.py

Reads DATABASE_URL from .env.  Connects via the Supabase connection pooler
(aws-0-us-east-1.pooler.supabase.com:5432) which works even when the direct
Postgres host (db.<ref>.supabase.co) is unavailable.

Migrations applied (each is idempotent):
  047_skill_evidence_pipelines.sql      — creates tables + partial unique index
  048_skill_pipeline_unique_constraints.sql — replaces partial index with a
      non-partial unique constraint so ON CONFLICT (student_id, skill_name)
      resolves correctly (fixes Postgres error 42P10).
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
        "Then re-run: python scripts/apply_pipeline_migration.py"
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
    """Parse a postgresql:// URL, handling ? in the password."""
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        url = url.split("//", 1)[1]
    at_idx = url.rfind("@")
    userpass = url[:at_idx]
    hostdb = url[at_idx + 1:]
    user, _, password = userpass.partition(":")
    host_port, _, dbname = hostdb.partition("/")
    host, _, port = host_port.partition(":")
    return {
        "user": user,
        "password": password,
        "host": host,
        "port": int(port) if port else 5432,
        "dbname": dbname or "postgres",
    }

params = _parse_pg_url(database_url)

# Try the pooler host first (resolves when the direct db.* host does not).
pooler_host = "aws-0-us-east-1.pooler.supabase.com"
# Pooler username format: postgres.<project-ref>
ref = params["host"].removeprefix("db.").split(".supabase.co")[0]
pooler_user = f"postgres.{ref}" if ref else params["user"]

connect_attempts = [
    {"host": pooler_host, "port": 5432, "user": pooler_user},
    {"host": pooler_host, "port": 6543, "user": pooler_user},
    {"host": params["host"], "port": params["port"], "user": params["user"]},
]

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
    "047_skill_evidence_pipelines.sql",
    "048_skill_pipeline_unique_constraints.sql",
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
    print("skill_evidence_pipelines and skill_evidence_artifacts tables are ready.")
    print("\nRestart the backend server so it detects the new tables:")
    print("  cd apps/api && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000")
except Exception as exc:
    conn.rollback()
    sys.exit(f"Migration failed: {exc}")
finally:
    conn.close()
