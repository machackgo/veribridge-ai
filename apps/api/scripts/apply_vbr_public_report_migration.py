"""Apply VBR public-report + Work Passport migrations (051 + 052 + 053) to Supabase.

Usage:
    cd apps/api
    python scripts/apply_vbr_public_report_migration.py

Reads DATABASE_URL from .env.  Connects via the Supabase connection pooler
(aws-0-us-east-1.pooler.supabase.com) which works even when the direct
Postgres host (db.<ref>.supabase.co) is unavailable.

Migrations applied (each is idempotent / additive-only):
  051_vbr_project_public_report_token.sql — adds vbr_projects.public_report_token
      + public_report_published_at columns (+ partial unique index). Without
      these the "Publish recruiter-safe link" POST 500s, which surfaces in the
      browser as "Failed to fetch" (the 500 carries no CORS header).
  052_vbr_work_passport.sql — creates the vbr_work_passports table + RLS so the
      public Work Passport can be published.
  053_trusted_github_evidence_analysis.sql — creates the service-role-only
      trusted_github_evidence_analysis table (+ RLS). Without it the GitHub
      scanner's trusted-provenance write and the read-time grade trust check
      both fail closed, so imported evidence silently degrades to weak grading.
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
        "Then re-run: python scripts/apply_vbr_public_report_migration.py"
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

# The direct db.<ref>.supabase.co host resolves here; try it first, then the
# pooler as a fallback (pooler username format is postgres.<project-ref>).
pooler_host = "aws-0-us-east-1.pooler.supabase.com"
ref = params["host"].removeprefix("db.").split(".supabase.co")[0]
pooler_user = f"postgres.{ref}" if ref else params["user"]

connect_attempts = [
    {"host": params["host"], "port": params["port"], "user": params["user"]},
    {"host": pooler_host, "port": 5432, "user": pooler_user},
    {"host": pooler_host, "port": 6543, "user": pooler_user},
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
    "051_vbr_project_public_report_token.sql",
    "052_vbr_work_passport.sql",
    "053_trusted_github_evidence_analysis.sql",
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
        "vbr_projects.public_report_token + vbr_work_passports "
        "+ trusted_github_evidence_analysis are ready."
    )

    # Tell PostgREST to refresh its schema cache so the newly created
    # columns/tables (e.g. public.vbr_work_passports) become visible without a
    # full backend restart. Without this, the table exists in Postgres but
    # PostgREST still 404s/500s until its cache is reloaded.
    cur.execute("NOTIFY pgrst, 'reload schema';")
    conn.commit()
    print("\nPostgREST schema reload requested: NOTIFY pgrst, 'reload schema';")
except Exception as exc:
    conn.rollback()
    sys.exit(f"Migration failed: {exc}")
finally:
    conn.close()
