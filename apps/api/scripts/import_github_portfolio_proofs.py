#!/usr/bin/env python3
"""
import_github_portfolio_proofs.py
===================================
Phase J3A — VeriBridge Personal GitHub Portfolio Importer.

Scans a public GitHub profile, detects high-signal evidence, and creates
real VeriBridge proof records for a target student user.

Usage examples:
    # Dry-run (no DB writes, prints JSON report)
    python apps/api/scripts/import_github_portfolio_proofs.py \\
        --github-user machackgo \\
        --target-user-id <uuid> \\
        --dry-run

    # Full import for the demo user (reads DEMO_USER_ID from .env)
    python apps/api/scripts/import_github_portfolio_proofs.py \\
        --github-user machackgo \\
        --use-demo-user

    # Limit repos, exclude forks, write JSON report
    python apps/api/scripts/import_github_portfolio_proofs.py \\
        --github-user machackgo \\
        --use-demo-user \\
        --max-repos 10 \\
        --dry-run \\
        --output apps/api/tmp/github_portfolio_import_dry_run_machackgo.json

    # Import only a specific repo
    python apps/api/scripts/import_github_portfolio_proofs.py \\
        --github-user machackgo \\
        --use-demo-user \\
        --include-repos boston-smart-accident-risk-rerouting-google-cloud

Requirements:
    pip install httpx supabase   (already in requirements.txt)
    SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY in apps/api/.env
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Add apps/api to sys.path so we can import app.*
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_env_file(env_path: Path) -> None:
    """Minimal .env loader — never prints secret values."""
    if not env_path.exists():
        return
    with open(env_path) as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, raw_value = line.partition("=")
            key = key.strip()
            value = raw_value.strip()
            if len(value) >= 2 and (
                (value[0] == '"' and value[-1] == '"')
                or (value[0] == "'" and value[-1] == "'")
            ):
                value = value[1:-1]
            os.environ.setdefault(key, value)


def _find_and_load_env() -> None:
    script_dir = Path(__file__).resolve().parent
    api_dir = script_dir.parent
    env_path = api_dir / ".env"
    if env_path.exists():
        _load_env_file(env_path)
    else:
        cwd_env = Path.cwd() / ".env"
        if cwd_env.exists():
            _load_env_file(cwd_env)


def _build_supabase_client():
    """Build a Supabase service-role client from environment variables."""
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        print(
            "[error] SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        from supabase import create_client
        return create_client(supabase_url=url, supabase_key=key)
    except ImportError:
        print("[error] supabase package not installed.", file=sys.stderr)
        sys.exit(1)


def _resolve_target_user_id(args: argparse.Namespace) -> str:
    if args.target_user_id:
        return args.target_user_id.strip()
    if args.use_demo_user:
        uid = os.environ.get("DEMO_USER_ID", "").strip()
        if not uid:
            print(
                "[error] --use-demo-user requires DEMO_USER_ID in .env",
                file=sys.stderr,
            )
            sys.exit(1)
        return uid
    print(
        "[error] Provide --target-user-id <uuid> or --use-demo-user",
        file=sys.stderr,
    )
    sys.exit(1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VeriBridge GitHub Portfolio Importer (Phase J3A)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--github-user", required=True,
        help="GitHub username to scan (e.g. machackgo)",
    )
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument(
        "--target-user-id",
        help="VeriBridge user UUID to create evidence records for",
    )
    target_group.add_argument(
        "--use-demo-user", action="store_true",
        help="Use DEMO_USER_ID from .env as the target user",
    )
    parser.add_argument(
        "--max-repos", type=int, default=25,
        help="Maximum number of repos to scan (default: 25)",
    )
    parser.add_argument(
        "--include-repos", nargs="+", default=None,
        help="Only scan these specific repo names",
    )
    parser.add_argument(
        "--exclude-repos", nargs="+", default=None,
        help="Skip these repo names",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be imported without writing to the database",
    )
    parser.add_argument(
        "--refresh-provenance", action="store_true",
        help=(
            "For candidates that already exist as this user's evidence rows, "
            "re-stamp the server-only trusted provenance (analyzer grade + "
            "redacted excerpt) instead of skipping them. Owner/repo-scoped and "
            "non-destructive: the user-owned skill_evidence rows are never "
            "modified or deleted. Combine with --dry-run to preview."
        ),
    )
    parser.add_argument(
        "--output",
        help="Write dry-run JSON report to this path instead of stdout",
    )
    parser.add_argument(
        "--github-token",
        help="GitHub personal access token (optional, raises rate limit)",
    )
    return parser.parse_args()


def main() -> None:
    _find_and_load_env()
    args = _parse_args()

    # Build GitHub client
    from scripts.github_portfolio_scanner import (
        GitHubAPIClient,
        PortfolioScanner,
        build_dry_run_report,
        import_candidates,
    )

    github_token = args.github_token or os.environ.get("GITHUB_TOKEN", "").strip() or None
    github_client = GitHubAPIClient(token=github_token)
    scanner = PortfolioScanner(github_client)

    print()
    print("VeriBridge AI — GitHub Portfolio Importer")
    print("=" * 46)
    print(f"[github user ] {args.github_user}")
    print(f"[max repos   ] {args.max_repos}")
    print(f"[dry run     ] {args.dry_run}")
    print()

    # Scan
    print("[...] Scanning GitHub profile ...")
    candidates = scanner.scan(
        username=args.github_user,
        max_repos=args.max_repos,
        include_repos=args.include_repos,
        exclude_repos=args.exclude_repos,
    )
    print(f"[ok]  Found {len(candidates)} evidence candidates.")
    print()

    if not candidates:
        print("No candidates found. Check that the GitHub user has public repos.")
        return

    # Build and output dry-run report
    report = build_dry_run_report(args.github_user, candidates)

    if args.dry_run:
        if args.refresh_provenance:
            # READ-ONLY preview of the refresh path: which existing rows would
            # gain re-stamped trusted provenance, which candidates are new.
            target_user_id = _resolve_target_user_id(args)
            supabase_client = _build_supabase_client()
            preview = import_candidates(
                supabase_client=supabase_client,
                user_id=target_user_id,
                candidates=candidates,
                dry_run=True,
                refresh_provenance=True,
            )
            report["refresh_preview"] = {
                "would_create": preview.created,
                "would_refresh": preview.refreshed,
                "skipped": preview.skipped,
            }
            print(f"[dry-run] would create : {len(preview.created)}")
            print(f"[dry-run] would refresh: {len(preview.refreshed)}")
            print(f"[dry-run] skipped      : {len(preview.skipped)}")
        # Print or write report
        report_json = json.dumps(report, indent=2)
        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(report_json)
            print(f"[ok]  Dry-run report written to: {out_path}")
        else:
            print(report_json)
        print()
        print(f"[dry-run] {len(candidates)} candidates identified. No DB writes.")
        print("Run without --dry-run to create real evidence records.")
        return

    # Real import
    target_user_id = _resolve_target_user_id(args)
    print(f"[target user ] {target_user_id}")
    print()

    supabase_client = _build_supabase_client()
    print("[...] Importing evidence records ...")
    result = import_candidates(
        supabase_client=supabase_client,
        user_id=target_user_id,
        candidates=candidates,
        dry_run=False,
        refresh_provenance=args.refresh_provenance,
    )

    print()
    print("=" * 46)
    print(f"[created  ] {len(result.created)}")
    print(f"[refreshed] {len(result.refreshed)}")
    print(f"[skipped  ] {len(result.skipped)}")
    print(f"[errors   ] {len(result.errors)}")
    print()

    for msg in result.created:
        print(f"  ✓ {msg}")
    for msg in result.refreshed:
        print(f"  ↻ {msg}")
    for msg in result.skipped:
        print(f"  ~ {msg}")
    for msg in result.errors:
        print(f"  ✗ {msg}", file=sys.stderr)

    if args.output:
        # Also write a final report to the output path
        report["import_result"] = {
            "created": result.created,
            "refreshed": result.refreshed,
            "skipped": result.skipped,
            "errors": result.errors,
        }
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2))
        print(f"\n[ok]  Report written to: {out_path}")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
