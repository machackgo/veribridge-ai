"""Apply Website Proof retention prerequisites (migrations 056 + 058 + storage bucket).

Usage:
    cd apps/api
    python scripts/apply_proof_artifact_retention_migration.py

Reads DATABASE_URL from .env and connects via the Supabase pooler (same
strategy as apply_vbr_public_report_migration.py). It is idempotent:

  * verifies / creates public.proof_artifacts (migration 056)
  * verifies / creates public.video_proofs (migration 057, dependency of 056 set)
  * applies migration 058 (workflow_analysis_results.filtered_unrelated_activity)
  * creates the PRIVATE `proof-artifacts` Storage bucket if absent
  * NOTIFY pgrst so PostgREST picks up the new column immediately

No secrets are printed. Bucket name (`proof-artifacts`) is not a secret; set it
in .env as SUPABASE_PROOF_ARTIFACT_BUCKET=proof-artifacts to enable retention.
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
        "Then re-run: python scripts/apply_proof_artifact_retention_migration.py"
    )

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

BUCKET = os.environ.get("SUPABASE_PROOF_ARTIFACT_BUCKET", "").strip() or "proof-artifacts"


def _parse_pg_url(url: str) -> dict:
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

migrations_dir = pathlib.Path(__file__).parent.parent / "app" / "db" / "migrations"
# 056/057 are additive + idempotent (create table if not exists) — re-applying
# them is a no-op that guarantees the retention spine exists before 058.
MIGRATIONS = [
    "056_proof_artifacts.sql",
    "057_video_proofs.sql",
    "058_workflow_filtered_unrelated_activity.sql",
]

try:
    cur = conn.cursor()

    # ── Verify 056 table presence before/after ────────────────────────────────
    cur.execute("select to_regclass('public.proof_artifacts') is not null;")
    had_056 = cur.fetchone()[0]
    print(f"proof_artifacts present before: {had_056}")

    for filename in MIGRATIONS:
        path = migrations_dir / filename
        if not path.exists():
            conn.rollback()
            sys.exit(f"Migration file not found: {path}")
        cur.execute(path.read_text())
        conn.commit()
        print(f"  {filename} applied.")

    # ── Verify 058 column ─────────────────────────────────────────────────────
    cur.execute(
        """
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'workflow_analysis_results'
          and column_name = 'filtered_unrelated_activity';
        """
    )
    has_col = cur.fetchone() is not None
    print(f"workflow_analysis_results.filtered_unrelated_activity present: {has_col}")
    if not has_col:
        conn.rollback()
        sys.exit("filtered_unrelated_activity column missing after 058 — aborting.")

    # ── Create the private storage bucket if absent ───────────────────────────
    cur.execute("select 1 from storage.buckets where id = %s;", (BUCKET,))
    if cur.fetchone() is None:
        cur.execute(
            """
            insert into storage.buckets (id, name, public)
            values (%s, %s, false)
            on conflict (id) do nothing;
            """,
            (BUCKET, BUCKET),
        )
        conn.commit()
        print(f"  Created PRIVATE storage bucket '{BUCKET}'.")
    else:
        print(f"  Storage bucket '{BUCKET}' already exists (left unchanged).")

    cur.execute("NOTIFY pgrst, 'reload schema';")
    conn.commit()
    print("\nPostgREST schema reload requested.")
    print(f"\nDone. Ensure .env has: SUPABASE_PROOF_ARTIFACT_BUCKET={BUCKET}")
except Exception as exc:
    conn.rollback()
    sys.exit(f"Migration failed: {exc}")
finally:
    conn.close()
