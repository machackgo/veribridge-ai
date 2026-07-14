"""Idempotent, tenant-safe backfill of canonical proof→project relationships.

Usage::

    cd apps/api
    python scripts/backfill_canonical_evidence.py --env-file .env --check
    python scripts/backfill_canonical_evidence.py --env-file .env --apply

Repairs ONLY deterministic edges that already exist in explicit source
metadata — never inferred from titles, filenames, or skill text:

  1. Website sessions whose ``metadata.project_id`` names a project owned by
     the SAME user → a ``directly_linked`` relationship row.
  2. Website/document artifacts whose ``project_id`` names a project owned by
     the same user → a ``directly_linked`` relationship row.
  3. Projects' ``metadata.attached_proofs`` (github_proof / documents /
     website_proofs) → the matching relationship rows, but only when the
     referenced proof row exists AND belongs to the same user.
  4. Document artifacts with a NULL ``project_id`` whose proof has exactly one
     ``directly_linked`` relationship → stamped with that project id.

It never crosses users, never duplicates (scoped unique index + pre-check),
never rewrites analysis rows, and never promotes ambiguous evidence — a proof
with no explicit source edge simply stays vault_only/legacy_unresolved.
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
    import psycopg2.extras
except ImportError:
    sys.exit("psycopg2 is required; install the API development dependencies first.")

API_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="Dry run: report what would be written.")
    action.add_argument("--apply", action="store_true", help="Write the missing deterministic rows.")
    parser.add_argument("--env-file", type=pathlib.Path, default=API_ROOT / ".env")
    return parser.parse_args()


def _connect(database_url: str):
    parsed = urllib.parse.urlparse(database_url.replace("postgresql+asyncpg://", "postgresql://", 1))
    params = {
        "user": urllib.parse.unquote(parsed.username or "postgres"),
        "password": urllib.parse.unquote(parsed.password or ""),
        "host": parsed.hostname or "",
        "port": parsed.port or 5432,
        "dbname": (parsed.path or "/postgres").lstrip("/") or "postgres",
    }
    ref = params["host"].removeprefix("db.").split(".supabase.co")[0]
    pooler_user = f"postgres.{ref}" if ref else params["user"]
    attempts = [(params["host"], params["port"], params["user"])]
    for host in ("aws-1-us-east-1.pooler.supabase.com", "aws-0-us-east-1.pooler.supabase.com"):
        attempts += [(host, 5432, pooler_user), (host, 6543, pooler_user)]
    for host, port, user in attempts:
        try:
            return psycopg2.connect(
                host=host, port=port, dbname=params["dbname"], user=user,
                password=params["password"], sslmode="require", connect_timeout=10,
            )
        except psycopg2.OperationalError:
            continue
    raise RuntimeError("Could not connect to the configured development database.")


def _existing_relationships(cur) -> set[tuple[str, str, str, str]]:
    cur.execute(
        "select owner_user_id::text, proof_type, proof_id, coalesce(project_id::text, '') "
        "from public.proof_project_relationships"
    )
    return set(cur.fetchall())


def _owned_projects(cur) -> dict[str, dict[str, Any]]:
    cur.execute("select id::text, user_id::text, title, metadata from public.vbr_projects")
    return {row[0]: {"user_id": row[1], "title": row[2], "metadata": row[3] or {}} for row in cur.fetchall()}


def main() -> None:
    args = _arguments()
    env_file = args.env_file.expanduser().resolve()
    if not env_file.is_file():
        sys.exit(f"Environment file not found: {env_file}")
    load_dotenv(env_file, override=False)
    if os.environ.get("ENVIRONMENT", "development").strip().lower() == "production":
        sys.exit("Refusing to backfill with ENVIRONMENT=production.")
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        sys.exit("DATABASE_URL is not configured.")

    conn = _connect(database_url)
    conn.autocommit = False
    cur = conn.cursor()

    projects = _owned_projects(cur)
    existing = _existing_relationships(cur)
    planned: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    def plan(owner: str, proof_type: str, proof_id: str, project_id: str, method: str, source: str) -> None:
        if not owner or not proof_id or not project_id:
            return
        project = projects.get(project_id)
        if project is None or project["user_id"] != owner:
            skipped.append({"proof_type": proof_type, "proof_id": proof_id, "reason": "cross_user_or_missing_project"})
            return
        # One proof may already be directly linked (to any project): never add a second.
        for row in existing:
            if row[0] == owner and row[1] == proof_type and row[2] == proof_id:
                return
        existing.add((owner, proof_type, proof_id, project_id))
        planned.append(
            {
                "owner_user_id": owner,
                "proof_type": proof_type,
                "proof_id": proof_id,
                "project_id": project_id,
                "match_method": method,
                "provenance": {"source": source, "backfill": "canonical_evidence_v1"},
            }
        )

    # 1 — website sessions with explicit project metadata.
    cur.execute("select id::text, user_id::text, metadata from public.extension_proof_sessions")
    for sid, owner, metadata in cur.fetchall():
        pid = str(((metadata or {}).get("project_id")) or "")
        if pid:
            plan(owner, "website", sid, pid, "proof_session_project_id", "extension_proof_sessions.metadata")

    # 2 — artifacts carrying an explicit project id.
    cur.execute(
        "select owner_user_id::text, proof_type, proof_id, project_id::text from public.proof_artifacts "
        "where project_id is not null and proof_id is not null"
    )
    for owner, proof_type, proof_id, pid in cur.fetchall():
        if proof_type in ("website", "document", "github", "project_defense", "video"):
            plan(owner, proof_type, proof_id, pid, "artifact_project_id", "proof_artifacts.project_id")

    # 3 — projects' attached_proofs metadata (ownership of the referenced proof is re-checked).
    cur.execute("select id::text, user_id::text from public.optional_evidence_submissions")
    document_owner = {row[0]: row[1] for row in cur.fetchall()}
    cur.execute("select id::text, user_id::text from public.github_proof_submissions")
    github_owner = {row[0]: row[1] for row in cur.fetchall()}
    cur.execute("select id::text, user_id::text from public.extension_proof_sessions")
    session_owner = {row[0]: row[1] for row in cur.fetchall()}
    for project_id, project in projects.items():
        owner = project["user_id"]
        attached = (project["metadata"] or {}).get("attached_proofs") or {}
        github = attached.get("github_proof") or {}
        gid = str(github.get("github_proof_id") or "")
        if gid and github_owner.get(gid) == owner:
            plan(owner, "github", gid, project_id, "explicit_project_id", "vbr_projects.attached_proofs.github_proof")
        for doc in attached.get("documents") or []:
            did = str((doc or {}).get("document_evidence_id") or "")
            if did and document_owner.get(did) == owner:
                plan(owner, "document", did, project_id, "explicit_project_id", "vbr_projects.attached_proofs.documents")
        for wp in attached.get("website_proofs") or []:
            sid = str((wp or {}).get("proof_session_id") or "")
            if sid and session_owner.get(sid) == owner:
                plan(owner, "website", sid, project_id, "explicit_project_id", "vbr_projects.attached_proofs.website_proofs")

    # 4 — document artifacts inheriting the (single) direct relationship of their proof.
    direct_by_proof: dict[tuple[str, str, str], set[str]] = {}
    cur.execute(
        "select owner_user_id::text, proof_type, proof_id, project_id::text "
        "from public.proof_project_relationships where relationship_state = 'directly_linked'"
    )
    for owner, proof_type, proof_id, pid in cur.fetchall():
        direct_by_proof.setdefault((owner, proof_type, proof_id), set()).add(pid)
    for row in planned:
        direct_by_proof.setdefault(
            (row["owner_user_id"], row["proof_type"], row["proof_id"]), set()
        ).add(row["project_id"])
    cur.execute(
        "select id::text, owner_user_id::text, proof_type, proof_id from public.proof_artifacts "
        "where project_id is null and proof_id is not null"
    )
    artifact_updates: list[tuple[str, str]] = []
    for artifact_id, owner, proof_type, proof_id in cur.fetchall():
        targets = direct_by_proof.get((owner, proof_type, proof_id)) or set()
        if len(targets) == 1:
            artifact_updates.append((artifact_id, next(iter(targets))))

    result = {
        "mode": "check" if args.check else "apply",
        "planned_relationship_rows": len(planned),
        "planned_artifact_project_stamps": len(artifact_updates),
        "skipped_cross_user_or_missing": len(skipped),
        "planned_detail": [
            {k: row[k] for k in ("proof_type", "proof_id", "project_id", "match_method")}
            for row in planned[:50]
        ],
        "artifact_stamp_detail": artifact_updates[:50],
    }
    if args.check:
        conn.rollback()
        print(json.dumps(result, indent=2))
        return

    for row in planned:
        cur.execute(
            """
            insert into public.proof_project_relationships
              (owner_user_id, proof_type, proof_id, project_id, relationship_state,
               match_method, confirmed_by_user, provenance)
            values (%s, %s, %s, %s, 'directly_linked', %s, true, %s::jsonb)
            on conflict do nothing
            """,
            (
                row["owner_user_id"], row["proof_type"], row["proof_id"], row["project_id"],
                row["match_method"], json.dumps(row["provenance"]),
            ),
        )
    for artifact_id, project_id in artifact_updates:
        cur.execute(
            "update public.proof_artifacts set project_id = %s, updated_at = now() "
            "where id = %s and project_id is null",
            (project_id, artifact_id),
        )
    conn.commit()
    result["result"] = "APPLIED"
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
