"""Apply the Full-access Passport disclosure mode migration (064) to Supabase.

Usage:
    cd apps/api
    python scripts/apply_064_full_access_mode.py [--check-only]

Reads DATABASE_URL from .env. Connects via the direct host first, then the
Supabase connection poolers (both aws-1-/aws-0- generations), URL-decoding the
percent-encoded password.

Migration applied (idempotent, constraint-only, no data rewritten):
  064_passport_disclosure_full_access.sql — replaces the mode CHECK on
      public.passport_disclosure_policies so the closed vocabulary becomes
      ('recruiter_safe', 'full_access', 'custom'). Deploy BEFORE the API
      that writes 'full_access'.

--check-only prints the pre-flight state (063 tables, current constraint,
mode distribution) without changing anything.
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
        "Then re-run: python scripts/apply_064_full_access_mode.py"
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

check_only = "--check-only" in sys.argv

# ── Pre-flight state ──────────────────────────────────────────────────────────

PREFLIGHT = """
select
  (select count(*) from information_schema.tables
    where table_schema = 'public'
      and table_name in ('passport_disclosure_policies',
                         'passport_disclosure_overrides',
                         'passport_disclosure_audit')) as disclosure_tables,
  (select coalesce(json_agg(json_build_object('name', conname,
                                              'def', pg_get_constraintdef(oid))), '[]'::json)
     from pg_constraint
    where conrelid = 'public.passport_disclosure_policies'::regclass
      and contype = 'c') as mode_checks
"""

MODE_DISTRIBUTION = """
select mode, count(*) from public.passport_disclosure_policies group by mode order by mode
"""


def print_state(cur, label: str) -> None:
    cur.execute(PREFLIGHT)
    tables, checks = cur.fetchone()
    print(f"\n[{label}] disclosure tables present: {tables}/3")
    print(f"[{label}] CHECK constraints on passport_disclosure_policies:")
    for c in checks:
        print(f"    {c['name']}: {c['def']}")
    cur.execute(MODE_DISTRIBUTION)
    rows = cur.fetchall()
    print(f"[{label}] mode distribution: "
          + (", ".join(f"{m}={n}" for m, n in rows) if rows else "(no rows)"))


try:
    cur = conn.cursor()
    print_state(cur, "before")
    if check_only:
        print("\n--check-only: no changes made.")
        sys.exit(0)

    path = (
        pathlib.Path(__file__).parent.parent
        / "app" / "db" / "migrations" / "064_passport_disclosure_full_access.sql"
    )
    if not path.exists():
        sys.exit(f"Migration file not found: {path}")
    cur.execute(path.read_text())
    conn.commit()
    print("\n  064_passport_disclosure_full_access.sql applied.")

    print_state(cur, "after")

    # The constraint must now admit exactly the three-mode vocabulary.
    cur.execute(
        """
        select pg_get_constraintdef(oid) from pg_constraint
         where conrelid = 'public.passport_disclosure_policies'::regclass
           and conname = 'passport_disclosure_policies_mode_allowed'
        """
    )
    row = cur.fetchone()
    if not row or "full_access" not in row[0]:
        sys.exit("VERIFICATION FAILED: mode_allowed constraint missing or lacks full_access.")
    print("\nVerified: passport_disclosure_policies_mode_allowed admits full_access.")

    cur.execute("NOTIFY pgrst, 'reload schema';")
    conn.commit()
    print("PostgREST schema reload requested: NOTIFY pgrst, 'reload schema';")
except SystemExit:
    raise
except Exception as exc:
    conn.rollback()
    sys.exit(f"Migration failed: {exc}")
finally:
    conn.close()
