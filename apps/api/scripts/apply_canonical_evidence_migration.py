"""Preflight or apply migration 058 to a non-production Supabase database.

Usage::

    cd apps/api
    python scripts/apply_canonical_evidence_migration.py --env-file .env --check
    python scripts/apply_canonical_evidence_migration.py --env-file .env --apply

The command never prints credentials or connection URLs. Application is one
PostgreSQL transaction followed by a PostgREST schema-cache reload request.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.parse
from typing import Any

from dotenv import load_dotenv

try:
    import psycopg2
except ImportError:
    sys.exit("psycopg2 is required; install the API development dependencies first.")


API_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIGRATION = API_ROOT / "app/db/migrations/058_canonical_evidence_relationships.sql"
MIGRATION_TABLES = (
    "vbr_project_skill_claims",
    "proof_project_relationships",
    "vbr_claim_evidence_links",
)
REQUIRED_COLUMNS = {
    "users": {"id"},
    "vbr_projects": {"id", "user_id", "title", "repo_url", "metadata"},
    "vbr_evidence_items": {"id", "project_id"},
    "proof_artifacts": {
        "id",
        "owner_user_id",
        "proof_type",
        "artifact_type",
        "proof_id",
        "project_id",
        "retained",
    },
    "extension_proof_sessions": {"id", "user_id", "status", "metadata"},
}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="Run read-only schema preflight.")
    action.add_argument("--apply", action="store_true", help="Apply migration 058 transactionally.")
    parser.add_argument(
        "--env-file",
        type=pathlib.Path,
        default=API_ROOT / ".env",
        help="Development environment file containing DATABASE_URL.",
    )
    return parser.parse_args()


def _parse_database_url(raw: str) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(raw.replace("postgresql+asyncpg://", "postgresql://", 1))
    return {
        "user": urllib.parse.unquote(parsed.username or "postgres"),
        "password": urllib.parse.unquote(parsed.password or ""),
        "host": parsed.hostname or "",
        "port": parsed.port or 5432,
        "dbname": (parsed.path or "/postgres").lstrip("/") or "postgres",
    }


def _connect(database_url: str):
    params = _parse_database_url(database_url)
    ref = params["host"].removeprefix("db.").split(".supabase.co")[0]
    pooler_user = f"postgres.{ref}" if ref else params["user"]
    attempts = [{"host": params["host"], "port": params["port"], "user": params["user"]}]
    for host in (
        "aws-1-us-east-1.pooler.supabase.com",
        "aws-0-us-east-1.pooler.supabase.com",
    ):
        attempts.extend(
            [
                {"host": host, "port": 5432, "user": pooler_user},
                {"host": host, "port": 6543, "user": pooler_user},
            ]
        )
    for attempt in attempts:
        try:
            connection = psycopg2.connect(
                host=attempt["host"],
                port=attempt["port"],
                dbname=params["dbname"],
                user=attempt["user"],
                password=params["password"],
                sslmode="require",
                connect_timeout=10,
            )
            return connection, {
                "host": attempt["host"],
                "port": attempt["port"],
                "database": params["dbname"],
            }
        except psycopg2.OperationalError:
            continue
    raise RuntimeError("Could not connect to the configured development database.")


def _schema_state(cursor) -> dict[str, Any]:
    cursor.execute(
        """
        select table_name, column_name
        from information_schema.columns
        where table_schema = 'public'
          and table_name = any(%s)
        """,
        (list(REQUIRED_COLUMNS) + list(MIGRATION_TABLES),),
    )
    columns: dict[str, set[str]] = {}
    for table, column in cursor.fetchall():
        columns.setdefault(table, set()).add(column)

    prerequisite_tables: dict[str, Any] = {}
    for table, required in REQUIRED_COLUMNS.items():
        present = columns.get(table, set())
        prerequisite_tables[table] = {
            "exists": bool(present),
            "required_columns_present": sorted(required & present),
            "missing_columns": sorted(required - present),
        }

    migration_tables = {table: bool(columns.get(table)) for table in MIGRATION_TABLES}
    cursor.execute(
        """
        select conname
        from pg_constraint
        where conname = any(%s)
        order by conname
        """,
        (
            [
                "proof_project_relationships_project_state_ck",
                "proof_project_relationships_owner_project_fk",
                "proof_artifacts_owner_project_fk",
            ],
        ),
    )
    constraints = [row[0] for row in cursor.fetchall()]
    cursor.execute(
        """
        select indexname
        from pg_indexes
        where schemaname = 'public'
          and indexname = any(%s)
        order by indexname
        """,
        (
            [
                "proof_project_relationships_scoped_unique_idx",
                "proof_project_relationships_one_direct_idx",
                "vbr_projects_id_user_unique_idx",
            ],
        ),
    )
    indexes = [row[0] for row in cursor.fetchall()]
    return {
        "prerequisites": prerequisite_tables,
        "migration_tables": migration_tables,
        "migration_applied": all(migration_tables.values()),
        "integrity_constraints": constraints,
        "uniqueness_indexes": indexes,
    }


def main() -> None:
    args = _arguments()
    env_file = args.env_file.expanduser().resolve()
    if not env_file.is_file():
        sys.exit(f"Environment file not found: {env_file}")
    load_dotenv(env_file, override=False)
    environment = os.environ.get("ENVIRONMENT", "development").strip().lower()
    if environment == "production":
        sys.exit("Refusing to inspect or apply migration 058 with ENVIRONMENT=production.")
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        sys.exit("DATABASE_URL is not configured in the selected environment.")

    connection, target = _connect(database_url)
    try:
        cursor = connection.cursor()
        before = _schema_state(cursor)
        missing = {
            table: state["missing_columns"]
            for table, state in before["prerequisites"].items()
            if not state["exists"] or state["missing_columns"]
        }
        result: dict[str, Any] = {
            "mode": "check" if args.check else "apply",
            "environment": environment,
            "target": target,
            "migration_file": str(MIGRATION),
            "before": before,
        }
        if missing:
            connection.rollback()
            result["result"] = "FAIL"
            result["missing_prerequisites"] = missing
            print(json.dumps(result, indent=2))
            raise SystemExit(1)

        if args.check:
            connection.rollback()
            result["result"] = "PASS"
            print(json.dumps(result, indent=2))
            return

        cursor.execute(MIGRATION.read_text())
        cursor.execute("NOTIFY pgrst, 'reload schema';")
        connection.commit()
        after = _schema_state(cursor)
        result["after"] = after
        result["result"] = "PASS" if after["migration_applied"] else "FAIL"
        print(json.dumps(result, indent=2))
        if result["result"] != "PASS":
            raise SystemExit(1)
    except BaseException:
        if not connection.closed:
            connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
