"""Rebuild the recruiter search index from source-of-truth data.

Usage:
    cd apps/api
    python scripts/rebuild_search_index.py

Reads Supabase credentials from .env (same environment the API runs with),
then re-projects EVERY published Work Passport through
recruiter_search_service.rebuild_search_index — the safe backfill / repair
path. The index is a cache: this never mutates passports, profiles,
disclosure, or evidence; it only rewrites recruiter_search_index rows and
removes rows whose owner is no longer published.

Run after applying migration 066 (scripts/apply_066_search_index.py) and any
time the index needs reconciling with reality.
"""

from __future__ import annotations

import os
import pathlib
import sys

# Make apps/api importable when invoked as `python scripts/rebuild_search_index.py`
# (python puts the script dir, not the cwd, on sys.path).
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

env_path = pathlib.Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


def main() -> None:
    from app.db.supabase import get_supabase_client
    from app.services.recruiter_search_service import rebuild_search_index

    db = get_supabase_client()
    # In production the pipeline store IS the main Supabase database.
    summary = rebuild_search_index(db, db)
    print(
        "Search index rebuilt: "
        f"{summary['refreshed']} refreshed, {summary['removed']} removed, "
        f"{summary['published']} published passports considered."
    )


if __name__ == "__main__":
    main()
