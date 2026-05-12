"""Public GitHub repository and blob inspection for proof verification."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.services.github_evidence_service import GitHubRepoRef, parse_github_repo_url

GITHUB_PUBLIC_INSPECTOR_VERSION = "github-public-inspection-v1"
GITHUB_API_BASE_URL = "https://api.github.com"
MAX_README_CHARS = 20_000
MAX_FILE_CHARS = 20_000
MAX_FILE_BYTES = 300_000


@dataclass(frozen=True)
class GitHubInspectionResult:
    inspection_used: bool
    owner: str | None = None
    repo: str | None = None
    repo_description: str | None = None
    primary_language: str | None = None
    default_branch: str | None = None
    readme_text: str | None = None
    file_path: str | None = None
    file_text: str | None = None
    file_name: str | None = None
    matched_signals: list[str] = field(default_factory=list)
    missing_signals: list[str] = field(default_factory=list)
    error: str | None = None
    status_code: int | None = None

    @property
    def text(self) -> str:
        parts = [
            self.owner,
            self.repo,
            self.repo_description,
            self.primary_language,
            self.readme_text,
            self.file_path,
            self.file_name,
            self.file_text,
        ]
        return " ".join(part for part in parts if part)


class GitHubPublicInspectionService:
    def __init__(self, timeout_seconds: float = 8.0) -> None:
        self._timeout_seconds = timeout_seconds

    def inspect_url(self, url: str | None) -> GitHubInspectionResult:
        repo_ref = parse_github_repo_url(url)
        if repo_ref is None:
            return GitHubInspectionResult(
                inspection_used=False,
                error="invalid_github_url",
                missing_signals=["URL is not a supported public GitHub repository or blob URL."],
            )

        try:
            with httpx.Client(
                base_url=GITHUB_API_BASE_URL,
                timeout=self._timeout_seconds,
                follow_redirects=True,
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "veribridge-ai-public-proof-verifier",
                },
            ) as client:
                return self._inspect_repo_ref(client, repo_ref)
        except httpx.HTTPError:
            return GitHubInspectionResult(
                inspection_used=False,
                owner=repo_ref.owner,
                repo=repo_ref.repo,
                file_path=repo_ref.file_path,
                error="github_api_error",
                missing_signals=["GitHub API request failed; falling back to stored proof metadata."],
            )

    def _inspect_repo_ref(self, client: httpx.Client, repo_ref: GitHubRepoRef) -> GitHubInspectionResult:
        repo_response = client.get(f"/repos/{repo_ref.owner}/{repo_ref.repo}")
        if repo_response.status_code == 404:
            return GitHubInspectionResult(
                inspection_used=False,
                owner=repo_ref.owner,
                repo=repo_ref.repo,
                file_path=repo_ref.file_path,
                error="github_repo_not_found",
                status_code=repo_response.status_code,
                missing_signals=["GitHub repository was not found or is not public."],
            )
        if repo_response.status_code == 403:
            return GitHubInspectionResult(
                inspection_used=False,
                owner=repo_ref.owner,
                repo=repo_ref.repo,
                file_path=repo_ref.file_path,
                error="github_rate_limited_or_forbidden",
                status_code=repo_response.status_code,
                missing_signals=["GitHub API access was rate-limited or forbidden; falling back to stored proof metadata."],
            )
        if repo_response.status_code >= 400:
            return GitHubInspectionResult(
                inspection_used=False,
                owner=repo_ref.owner,
                repo=repo_ref.repo,
                file_path=repo_ref.file_path,
                error="github_api_error",
                status_code=repo_response.status_code,
                missing_signals=["GitHub API returned an error; falling back to stored proof metadata."],
            )

        repo_data = repo_response.json()
        default_branch = _clean(repo_data.get("default_branch")) or repo_ref.branch or "main"
        readme_text, readme_signal = self._fetch_readme(client, repo_ref, default_branch)
        file_text = None
        file_signal = None
        if repo_ref.file_path:
            file_text, file_signal = self._fetch_blob_file(client, repo_ref, default_branch)

        matched = [
            f"GitHub repository inspected: {repo_ref.owner}/{repo_ref.repo}.",
        ]
        missing: list[str] = []
        if repo_data.get("description"):
            matched.append("GitHub repository description is available.")
        else:
            missing.append("GitHub repository description is missing.")
        if repo_data.get("language"):
            matched.append(f"GitHub primary language is {repo_data['language']}.")
        else:
            missing.append("GitHub primary language is unavailable.")
        if readme_signal:
            matched.append(readme_signal)
        else:
            missing.append("GitHub README is unavailable or empty.")
        if file_signal:
            matched.append(file_signal)
        elif repo_ref.file_path:
            missing.append("GitHub blob file could not be inspected.")

        return GitHubInspectionResult(
            inspection_used=True,
            owner=repo_ref.owner,
            repo=repo_ref.repo,
            repo_description=_clean(repo_data.get("description")) or None,
            primary_language=_clean(repo_data.get("language")) or None,
            default_branch=default_branch,
            readme_text=readme_text,
            file_path=repo_ref.file_path,
            file_text=file_text,
            file_name=_file_name(repo_ref.file_path),
            matched_signals=matched,
            missing_signals=missing,
            status_code=repo_response.status_code,
        )

    def _fetch_readme(
        self,
        client: httpx.Client,
        repo_ref: GitHubRepoRef,
        default_branch: str,
    ) -> tuple[str | None, str | None]:
        response = client.get(f"/repos/{repo_ref.owner}/{repo_ref.repo}/readme", params={"ref": default_branch})
        if response.status_code >= 400:
            return None, None
        text = _decode_contents_response(response.json(), max_chars=MAX_README_CHARS)
        if not text:
            return None, None
        return text, "GitHub README was inspected."

    def _fetch_blob_file(
        self,
        client: httpx.Client,
        repo_ref: GitHubRepoRef,
        default_branch: str,
    ) -> tuple[str | None, str | None]:
        path = (repo_ref.file_path or "").lstrip("/")
        if not path:
            return None, None
        branch = repo_ref.branch or default_branch
        response = client.get(f"/repos/{repo_ref.owner}/{repo_ref.repo}/contents/{path}", params={"ref": branch})
        if response.status_code >= 400:
            return None, None
        payload = response.json()
        if isinstance(payload, list) or payload.get("type") != "file":
            return None, None
        if int(payload.get("size") or 0) > MAX_FILE_BYTES:
            return None, "GitHub blob filename was inspected; file content exceeded the MVP size limit."
        text = _decode_contents_response(payload, max_chars=MAX_FILE_CHARS)
        if text:
            return text, f"GitHub blob file content was inspected: {path}."
        return None, f"GitHub blob filename was inspected: {path}."


def _decode_contents_response(payload: dict[str, Any], max_chars: int) -> str | None:
    content = payload.get("content")
    if not content or payload.get("encoding") != "base64":
        return None
    try:
        decoded = base64.b64decode(str(content), validate=False)
    except (ValueError, TypeError):
        return None
    return decoded.decode("utf-8", errors="replace")[:max_chars].strip() or None


def _file_name(path: str | None) -> str | None:
    if not path:
        return None
    return path.rstrip("/").split("/")[-1] or None


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
