"""Dev/admin utility: safely archive or delete a single proof session.

Default mode is dry-run — NO data is changed unless --delete --confirm is passed.

Usage
-----
    cd apps/api

    # Dry-run (safe — prints counts only):
    python scripts/cleanup_proof_session.py --session-id d592f7fb-6aee-47d6-a549-a7192268574e

    # Soft archive (sets extension_proof_sessions.status = 'expired' AND
    # detaches the project linkage: session metadata project edge moved to
    # detached_project_id, proof_project_relationships rows downgraded to
    # vault_only with a provenance trail — nothing is deleted):
    python scripts/cleanup_proof_session.py --session-id d592f7fb-... --archive

    # Export backup JSON then delete (requires --confirm):
    python scripts/cleanup_proof_session.py \\
        --session-id d592f7fb-... \\
        --delete \\
        --confirm \\
        --backup-path /tmp/session_backup_d592f7fb.json

Reads DATABASE_URL from apps/api/.env or the environment.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

# ── Load .env ──────────────────────────────────────────────────────────────────

_env_path = pathlib.Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

_NOISY_SESSION = "d592f7fb-6aee-47d6-a549-a7192268574e"

# ── CLI args ───────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(
    description="Dry-run / archive / delete a single proof session and all its dependent data."
)
parser.add_argument(
    "--session-id",
    default=_NOISY_SESSION,
    help=f"Proof session UUID to target (default: {_NOISY_SESSION})",
)
parser.add_argument(
    "--archive",
    action="store_true",
    default=False,
    help=(
        "Soft-archive: set extension_proof_sessions.status = 'expired' and detach the "
        "project linkage (metadata + proof_project_relationships → vault_only, with a "
        "provenance trail). No data is deleted."
    ),
)
parser.add_argument(
    "--delete",
    action="store_true",
    default=False,
    help="Delete all rows for the session.  Requires --confirm.",
)
parser.add_argument(
    "--confirm",
    action="store_true",
    default=False,
    help="Required alongside --delete to actually perform deletion.",
)
parser.add_argument(
    "--backup-path",
    default=None,
    help="Path to write a JSON backup before deletion (recommended with --delete).",
)
args = parser.parse_args()

session_id = args.session_id

# ── Import Supabase client (needs DATABASE_URL in env) ────────────────────────

try:
    from supabase import create_client
except ImportError:
    sys.exit(
        "supabase-py not installed.  Run: pip install supabase\n"
        "Then re-run the script."
    )

supabase_url = os.environ.get("SUPABASE_URL", "")
supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "") or os.environ.get("SUPABASE_KEY", "")

if not supabase_url or not supabase_key:
    sys.exit(
        "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env or environment.\n"
        "See apps/api/.env."
    )

db = create_client(supabase_url, supabase_key)

# ── Import service ─────────────────────────────────────────────────────────────

_repo_root = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_repo_root))

from app.services.proof_session_cleanup_service import ProofSessionCleanupService

svc = ProofSessionCleanupService(db)

# ── Dry-run (always printed first) ────────────────────────────────────────────

print(f"\n=== Dry-run for session: {session_id} ===")
report = svc.dry_run(session_id)
print(json.dumps(report.to_dict(), indent=2))

if not report.session_exists:
    print("\nWARNING: Session row not found in extension_proof_sessions.")

if report.warnings:
    print("\nWarnings:")
    for w in report.warnings:
        print(f"  • {w}")

if report.affected_pipeline_ids:
    print(
        f"\nAfter artifact deletion, these pipelines may need evidence_count refresh:\n"
        + "\n".join(f"  • {pid}" for pid in report.affected_pipeline_ids)
    )

# ── Archive mode ───────────────────────────────────────────────────────────────

if args.archive:
    if args.delete:
        sys.exit("ERROR: --archive and --delete are mutually exclusive.")
    print(f"\n=== Soft-archive: expiring + detaching {session_id} ===")
    updated = svc.archive_session(session_id)
    if updated:
        print("Done — session status set to 'expired' and project linkage detached")
        print("(session metadata edge → detached_project_id; relationship rows → vault_only).")
        print("Note: nothing was deleted — skill_evidence stub, text-column tables (frames,")
        print("events) and synced artifacts all remain.")
        print("Run with --delete --confirm to remove them after archiving.")
    else:
        print("No session row found — nothing archived.")
    sys.exit(0)

# ── Delete mode ────────────────────────────────────────────────────────────────

if args.delete:
    if not args.confirm:
        print(
            "\nTo actually delete, re-run with --confirm.\n"
            "It is strongly recommended to also pass --backup-path /tmp/backup.json first.\n"
        )
        sys.exit(0)

    # Backup first if path provided
    if args.backup_path:
        print(f"\n=== Exporting backup to {args.backup_path} ===")
        backup_data = svc.backup(session_id)
        with open(args.backup_path, "w") as fh:
            json.dump(backup_data, fh, indent=2, default=str)
        print(f"Backup written to {args.backup_path}")

    print(f"\n=== Deleting session {session_id} and all dependent rows ===")
    delete_report = svc.delete(session_id, confirm=True)
    print(json.dumps(delete_report.to_dict(), indent=2))

    if delete_report.errors:
        print("\nErrors during deletion:")
        for err in delete_report.errors:
            print(f"  • {err}")
        sys.exit(1)

    print("\nDeletion complete.")
    if delete_report.affected_pipeline_ids:
        print(
            "ACTION REQUIRED — recalculate evidence_count on affected pipelines:\n"
            + "\n".join(f"  • {pid}" for pid in delete_report.affected_pipeline_ids)
        )
    sys.exit(0)

# ── Dry-run only (default) ─────────────────────────────────────────────────────

print(
    "\nDry-run complete.  No data was changed.\n"
    "Pass --archive to soft-archive, or --delete --confirm to delete.\n"
    "Recommended: also pass --backup-path /tmp/backup.json with --delete.\n"
)
