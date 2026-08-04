"""GitHub repo ingestion skeleton + deployed URL check for VBR projects.

MVP scope only:
  - parse_github_repo_url(): re-exported helper to extract owner/repo/branch
    from a GitHub URL.
  - ingest_repo(): writes deterministic placeholder facts to
    vbr_repo_analyses. Does NOT call the GitHub API or any LLM yet.
  - check_deployed_url(): performs a basic server-side reachability check
    for a project's deployed_url and writes vbr_deployed_url_checks.

TODO (future milestones):
  - Replace placeholder facts with real GitHub API ingestion (commits,
    languages, README, contributors, fork status, authorship match).
  - Add screenshot capture for deployed URL checks.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin
from uuid import uuid4

import httpx

from app.services.github_evidence_service import GitHubRepoRef, parse_github_repo_url
from app.services.url_classification_service import classify_website_url

logger = logging.getLogger(__name__)

_REPO_ANALYSES_TABLE = "vbr_repo_analyses"
_URL_CHECKS_TABLE = "vbr_deployed_url_checks"

_HTTP_TIMEOUT_SECONDS = 10.0

__all__ = [
    "GitHubRepoRef",
    "parse_github_repo_url",
    "build_placeholder_repo_facts",
    "ingest_repo",
    "check_deployed_url",
]


def build_placeholder_repo_facts(repo_url: str, repo_full_name: str | None) -> dict[str, Any]:
    """Build deterministic placeholder facts from a repo URL.

    No GitHub API calls are made — this is an MVP skeleton so that
    vbr_repo_analyses rows exist for downstream flows to build on.
    """
    repo_ref = parse_github_repo_url(repo_url)
    owner = repo_ref.owner if repo_ref else None
    repo = repo_ref.repo if repo_ref else None
    branch = (repo_ref.branch if repo_ref else None) or "main"

    resolved_full_name = repo_full_name or (f"{owner}/{repo}" if owner and repo else None)

    return {
        "source": "placeholder",
        "owner": owner,
        "repo": repo,
        "repo_full_name": resolved_full_name,
        "default_branch": branch,
        # TODO: replace with real GitHub API data once ingestion is implemented.
        "languages": {},
        "commit_count": None,
        "contributors": [],
        "notes": "Repo ingestion skeleton — placeholder facts only, no GitHub API call performed.",
    }


def ingest_repo(
    db: Any,
    project_id: str,
    repo_url: str,
    repo_full_name: str | None,
) -> dict[str, Any]:
    """Create or update the vbr_repo_analyses row for a project.

    MVP skeleton: writes deterministic placeholder facts derived from the
    repo URL. Does not call the GitHub API or any LLM.
    """
    facts = build_placeholder_repo_facts(repo_url, repo_full_name)
    now = _now()

    if isinstance(db, dict):
        table = db.setdefault(_REPO_ANALYSES_TABLE, {})
        existing = next((row for row in table.values() if row.get("project_id") == project_id), None)
        row = {
            "id": existing["id"] if existing else str(uuid4()),
            "project_id": project_id,
            "head_sha": None,
            "facts": facts,
            "fork": None,
            "authorship_match_pct": None,
            "computed_at": now,
        }
        table[row["id"]] = row
        return row

    existing_result = (
        db.table(_REPO_ANALYSES_TABLE)
        .select("id")
        .eq("project_id", project_id)
        .limit(1)
        .execute()
    )
    existing_rows = getattr(existing_result, "data", []) or []

    payload = {
        "project_id": project_id,
        "head_sha": None,
        "facts": facts,
        "fork": None,
        "authorship_match_pct": None,
        "computed_at": now,
    }

    if existing_rows:
        result = (
            db.table(_REPO_ANALYSES_TABLE)
            .update(payload)
            .eq("id", existing_rows[0]["id"])
            .execute()
        )
    else:
        result = db.table(_REPO_ANALYSES_TABLE).insert(payload).execute()

    rows = getattr(result, "data", []) or []
    if not rows:
        raise RuntimeError("vbr_repo_analyses upsert returned no data.")
    return rows[0]



def _host_resolves_public(host: str) -> bool:
    """Return True only if all DNS answers are public routable addresses."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False

    if not infos:
        return False

    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False

        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_unspecified
            or ip.is_multicast
            or ip.is_reserved
        ):
            return False

    return True


def _assert_public_fetch_url(url: str) -> tuple[bool, str | None]:
    """Validate URL before every outbound fetch, including redirects."""
    classification = classify_website_url(url)
    if not classification.is_public_live_url:
        return False, classification.reason
    if not classification.hostname or not _host_resolves_public(classification.hostname):
        return False, "URL hostname resolves to a private or internal address."
    return True, None

def check_deployed_url(db: Any, project_id: str, url: str) -> dict[str, Any]:
    """Perform a basic server-side reachability check for a deployed URL.

    Rejects local/private hosts and validates every redirect hop to avoid SSRF.
    Writes a row to vbr_deployed_url_checks and returns it.
    """
    ok, reason = _assert_public_fetch_url(url)
    if not ok:
        return _persist_url_check(db, {
            "project_id": project_id,
            "url": url,
            "status_code": None,
            "title": None,
            "screenshot_path": None,
            "phash": None,
            "result": "unable",
            "detail": reason,
            "checked_at": _now(),
        })

    status_code: int | None = None
    page_title: str | None = None
    result = "unable"
    detail: str | None = None

    try:
        with httpx.Client(
            timeout=_HTTP_TIMEOUT_SECONDS,
            follow_redirects=False,
            headers={
                "Accept": "text/html,application/xhtml+xml,*/*",
                "User-Agent": "veribridge-vbr-checker/1.0",
            },
        ) as client:
            current_url = url
            response: httpx.Response | None = None

            for _ in range(5):
                ok, reason = _assert_public_fetch_url(current_url)
                if not ok:
                    result = "unable"
                    detail = reason
                    response = None
                    break

                response = client.get(current_url)
                if response.status_code not in {301, 302, 303, 307, 308}:
                    break

                location = response.headers.get("location")
                if not location:
                    break

                current_url = urljoin(current_url, location)
            else:
                result = "unable"
                detail = "Too many redirects."
                response = None

        if response is not None:
            status_code = response.status_code
            if 200 <= status_code < 400:
                result = "pass"
            else:
                result = "note"
                detail = f"HTTP {status_code} response."

            page_title = (
                _extract_title(response.text[:20_000])
                if "html" in response.headers.get("content-type", "").lower()
                else None
            )

    except httpx.TimeoutException:
        result = "unable"
        detail = "Request timed out."
    except httpx.HTTPError as exc:
        result = "unable"
        detail = f"HTTP error: {exc}"[:300]
    except Exception:
        logger.exception("VBR_CHECK_URL_UNEXPECTED project_id=%s url=%s", project_id, url)
        result = "unable"
        detail = "Unexpected error during check."

    row_data = {
        "project_id": project_id,
        "url": url,
        "status_code": status_code,
        "title": page_title,
        "screenshot_path": None,
        "phash": None,
        "result": result,
        "detail": detail,
        "checked_at": _now(),
    }
    return _persist_url_check(db, row_data)


def _persist_url_check(db: Any, row_data: dict[str, Any]) -> dict[str, Any]:
    if isinstance(db, dict):
        row = {"id": str(uuid4()), **row_data}
        db.setdefault(_URL_CHECKS_TABLE, {})[row["id"]] = row
        return row

    result = db.table(_URL_CHECKS_TABLE).insert(row_data).execute()
    rows = getattr(result, "data", []) or []
    if not rows:
        raise RuntimeError("vbr_deployed_url_checks insert returned no data.")
    return rows[0]


def _extract_title(html: str) -> str | None:
    start = html.lower().find("<title")
    if start == -1:
        return None
    start = html.find(">", start)
    if start == -1:
        return None
    end = html.lower().find("</title>", start)
    if end == -1:
        return None
    title = html[start + 1 : end].strip()
    return title[:300] or None


def _now() -> str:
    return datetime.now(UTC).isoformat()
