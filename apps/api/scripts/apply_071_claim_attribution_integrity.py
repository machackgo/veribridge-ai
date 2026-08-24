"""Apply the claim-attribution-integrity data migration (071) to Supabase.

Usage:
    cd apps/api
    python scripts/apply_071_claim_attribution_integrity.py

Reads DATABASE_URL from .env. Connects via the direct host first, then the
Supabase connection poolers (both aws-1-/aws-0- generations), URL-decoding the
percent-encoded password.

Migration applied (data-only, non-destructive, idempotent):
  071_claim_attribution_integrity.sql —
      rewrites vbr_project_skill_claims.claim_text from the subject-ambiguous
      "<skill> was implemented and demonstrated in <project>." to the
      PROJECT-scoped "<skill> is demonstrated in the project <project>."
      (candidate attribution is carried separately with its own evidence bar).
      Touches only the sentence template; skill_key/skill_name/claim_state/
      evidence_status and every evidence link row are untouched.
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
        "Then re-run: python scripts/apply_071_claim_attribution_integrity.py"
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

# ── Apply the data migration with before/after accounting ────────────────────

MIGRATION = "071_claim_attribution_integrity.sql"
OLD_PATTERN = "% was implemented and demonstrated in %"

migrations_dir = pathlib.Path(__file__).parent.parent / "app" / "db" / "migrations"

try:
    cur = conn.cursor()
    cur.execute(
        "select count(*) from public.vbr_project_skill_claims where claim_text like %s",
        (OLD_PATTERN,),
    )
    before = cur.fetchone()[0]
    cur.execute("select count(*) from public.vbr_project_skill_claims")
    total = cur.fetchone()[0]
    print(f"vbr_project_skill_claims: {total} rows total, {before} with the legacy template.")

    path = migrations_dir / MIGRATION
    if not path.exists():
        conn.rollback()
        sys.exit(f"Migration file not found: {path}")
    cur.execute(path.read_text())
    conn.commit()
    print(f"  {MIGRATION} applied.")

    cur.execute(
        "select count(*) from public.vbr_project_skill_claims where claim_text like %s",
        (OLD_PATTERN,),
    )
    after = cur.fetchone()[0]
    print(f"Legacy-template rows remaining: {after} (rewrote {before - after}).")
    if after:
        print("WARNING: some rows still carry the legacy template — inspect manually.")

    cur.execute(
        "select claim_text from public.vbr_project_skill_claims order by updated_at desc limit 5"
    )
    print("\nNewest claim_text samples:")
    for (text,) in cur.fetchall():
        print(f"  · {text}")
except Exception as exc:
    conn.rollback()
    sys.exit(f"Migration failed: {exc}")
finally:
    conn.close()
