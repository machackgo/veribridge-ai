"""Reclassify stored GitHub code evidence with the current analyzer version.

Idempotent, tenant-scoped reanalysis of the SERVER-ONLY trusted provenance for
a user's canonical ``skill_evidence`` GitHub rows (migration 053/059 table).
For each owned row that already carries trusted provenance:

1. Re-fetch the cited file from the PUBLIC GitHub repository (raw endpoint) so
   the analyzer can expand context symbol-first: the complete containing
   function/class body, or — for a module-level anchor — the complete
   containing statement (a multi-line ``from x import (…)`` is captured whole,
   never as a bare-name fragment).
2. Re-grade the analyzed window with the CURRENT deterministic logic and stamp
   ``ANALYZER_VERSION`` provenance: grade, redacted excerpt, symbol name/type,
   and the analyzed context lines (``context_start/end_line``) when they differ
   from the cited target lines. The ``skill_evidence`` row itself — its file,
   target lines, description, project identity, ownership — is NEVER modified,
   so no evidence is duplicated, moved, or re-owned.
3. When the file cannot be fetched (deleted/private/offline), fall back to
   re-grading the ALREADY-STORED excerpt with current logic — a fragment
   excerpt then honestly downgrades to import-only / insufficient-context.
4. The prior analysis is appended to ``analysis_history`` (migration 059), so
   reclassification preserves provenance history and supports retry.

Already-current records (same analyzer version + same snippet hash + same
context lines) are skipped, so re-running is a no-op.

Usage:
    python scripts/reclassify_github_evidence_purposes.py --user-id <uuid> [--apply]

Dry-run by default; pass --apply to write.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from app.services.github_python_evidence_focus import (  # noqa: E402
    ANALYZER_NAME,
    ANALYZER_VERSION,
    TRUSTED_ANALYSIS_TABLE,
    build_server_provenance,
    focus_python_range,
    focus_python_symbol,
    grade_evidence,
)

_REPO_RE = re.compile(r"github\.com[/:]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", re.IGNORECASE)


def _fetch_raw(owner: str, repo: str, branch: str, path: str) -> str | None:
    import httpx

    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                return resp.text
    except Exception:
        return None
    return None


def _analyze(
    row: dict[str, Any], prov: dict[str, Any]
) -> dict[str, Any] | None:
    """Build the new provenance record for one skill_evidence row, or None."""
    file_path = str(row.get("file_path") or "").strip()
    line_start = row.get("line_start")
    line_end = row.get("line_end") or line_start
    if not file_path or not isinstance(line_start, int):
        return None
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    repo_url = str(row.get("repository_url") or "").strip()
    m = _REPO_RE.search(repo_url)
    branch = str(metadata.get("branch_ref") or "main")

    content = _fetch_raw(m.group(1), m.group(2), branch, file_path) if m else None
    is_python = file_path.lower().endswith(".py")

    symbol_name = symbol_type = None
    context_start = context_end = None
    excerpt: str | None = None
    grade: str | None = None

    if content and is_python:
        focused = focus_python_range(
            content, line_start, line_end, max_lines=80, include_signature=True
        )
        if focused is not None:
            c_start, c_end, grade = focused
            excerpt = "\n".join(content.splitlines()[c_start - 1 : c_end]) or None
            if (c_start, c_end) != (line_start, line_end):
                context_start, context_end = c_start, c_end
        symbol_name, symbol_type = focus_python_symbol(content, line_start)
    elif content:
        window = content.splitlines()[line_start - 1 : (line_end or line_start)]
        excerpt = "\n".join(window) or None

    if excerpt is None:
        # Fetch failed — re-grade the already-stored excerpt with current logic.
        excerpt = str(prov.get("safe_excerpt") or "").strip() or None
        if excerpt is None:
            return None

    if grade is None:
        grade = grade_evidence(
            file_path=file_path,
            code_snippet=excerpt,
            selection_reason=str(metadata.get("selection_reason") or "") or None,
            line_start=line_start,
            line_end=line_end,
        )

    return build_server_provenance(
        grade=grade,
        code_snippet=excerpt,
        focused_start_line=line_start,
        focused_end_line=line_end,
        focused_reason=str(metadata.get("selection_reason") or "") or None,
        symbol_name=symbol_name,
        symbol_type=symbol_type,
        context_start_line=context_start,
        context_end_line=context_end,
    )


def reclassify_user(db: Any, user_id: str, *, apply: bool) -> dict[str, int]:
    """Reanalyze one user's GitHub evidence provenance. Returns counters."""
    rows = (
        db.table("skill_evidence").select("*").eq("user_id", user_id).execute().data
        or []
    )
    prov_rows = (
        db.table(TRUSTED_ANALYSIS_TABLE)
        .select("*")
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )
    prov_by_eid = {str(p.get("skill_evidence_id")): p for p in prov_rows}
    counters = {"examined": 0, "skipped_current": 0, "updated": 0, "no_source": 0}

    for row in rows:
        eid = str(row.get("id") or "")
        prov = prov_by_eid.get(eid)
        if prov is None:
            continue  # never invent provenance for rows the scanner never graded
        counters["examined"] += 1

        new_prov = _analyze(row, prov)
        if new_prov is None:
            counters["no_source"] += 1
            continue

        new_hash = new_prov.get("snippet_hash")
        same_version = str(prov.get("analyzer_version") or "") == ANALYZER_VERSION
        same_hash = new_hash and prov.get("snippet_hash") == new_hash
        same_context = (
            prov.get("context_start_line") == new_prov.get("context_start_line")
            and prov.get("context_end_line") == new_prov.get("context_end_line")
        )
        if same_version and same_hash and same_context:
            counters["skipped_current"] += 1
            continue

        # Preserve the prior analysis in the append-only history.
        history = list(prov.get("analysis_history") or [])
        history.append(
            {
                "analyzer_name": prov.get("analyzer_name"),
                "analyzer_version": prov.get("analyzer_version"),
                "evidence_quality_grade": prov.get("evidence_quality_grade"),
                "focused_start_line": prov.get("focused_start_line"),
                "focused_end_line": prov.get("focused_end_line"),
                "context_start_line": prov.get("context_start_line"),
                "context_end_line": prov.get("context_end_line"),
                "snippet_hash": prov.get("snippet_hash"),
                "superseded_at": prov.get("updated_at") or prov.get("created_at"),
            }
        )
        record = {
            **new_prov,
            "skill_evidence_id": eid,
            "user_id": user_id,
            "analysis_history": history[-20:],  # bounded
        }
        loc = f"{row.get('file_path')}:{row.get('line_start')}-{row.get('line_end')}"
        if apply:
            db.table(TRUSTED_ANALYSIS_TABLE).upsert(
                record, on_conflict="skill_evidence_id"
            ).execute()
            print(f"UPDATED  {loc}  grade={new_prov.get('evidence_quality_grade')} "
                  f"symbol={new_prov.get('symbol_name')} "
                  f"context={new_prov.get('context_start_line')}-{new_prov.get('context_end_line')}")
        else:
            print(f"DRY-RUN  {loc}  grade={new_prov.get('evidence_quality_grade')} "
                  f"symbol={new_prov.get('symbol_name')} "
                  f"context={new_prov.get('context_start_line')}-{new_prov.get('context_end_line')}")
        counters["updated"] += 1

    return counters


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True, help="Owner user id (tenant scope)")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    args = parser.parse_args()

    from app.db.supabase import get_supabase_client

    db = get_supabase_client()
    counters = reclassify_user(db, args.user_id, apply=args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(
        f"[{mode}] analyzer v{ANALYZER_VERSION} ({ANALYZER_NAME}) — "
        f"examined={counters['examined']} updated={counters['updated']} "
        f"already-current={counters['skipped_current']} no-source={counters['no_source']}"
    )


if __name__ == "__main__":
    main()
