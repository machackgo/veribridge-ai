"""Public GitHub file fetching and Phase 2 skill evidence inspection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse

import httpx

GITHUB_FILE_VERIFIER_VERSION = "github-file-v1"
MAX_GITHUB_FILE_BYTES = 1_000_000
DEFAULT_BRANCH_CANDIDATES = ("main", "master")


@dataclass(frozen=True)
class GitHubRepoRef:
    owner: str
    repo: str
    branch: str | None = None
    file_path: str | None = None


@dataclass(frozen=True)
class GitHubFileFetchResult:
    ok: bool
    content: str | None = None
    branch: str | None = None
    raw_url: str | None = None
    error: str | None = None
    status_code: int | None = None


@dataclass(frozen=True)
class LineRangeResult:
    ok: bool
    content: str
    line_start: int | None
    line_end: int | None
    summary_range: str
    error: str | None = None


def parse_github_repo_url(url: str | None) -> GitHubRepoRef | None:
    if not url:
        return None

    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    parts = [part for part in parsed.path.strip("/").split("/") if part]

    if host == "github.com":
        if len(parts) < 2:
            return None
        branch = None
        file_path = None
        if len(parts) >= 4 and parts[2] in {"tree", "blob"}:
            branch = parts[3]
            if parts[2] == "blob" and len(parts) > 4:
                file_path = "/".join(parts[4:])
        return GitHubRepoRef(owner=parts[0], repo=parts[1], branch=branch, file_path=file_path)

    if host == "raw.githubusercontent.com":
        if len(parts) < 4:
            return None
        return GitHubRepoRef(
            owner=parts[0],
            repo=parts[1],
            branch=parts[2],
            file_path="/".join(parts[3:]),
        )

    return None


def build_raw_github_url(repository_url: str, file_path: str, branch: str = "main") -> str:
    repo_ref = parse_github_repo_url(repository_url)
    if repo_ref is None:
        raise ValueError("Unsupported GitHub repository URL.")

    normalized_path = (file_path or repo_ref.file_path or "").strip().lstrip("/")
    if not normalized_path:
        raise ValueError("GitHub file path is required.")

    encoded_path = "/".join(quote(part) for part in normalized_path.split("/"))
    return f"https://raw.githubusercontent.com/{repo_ref.owner}/{repo_ref.repo}/{branch}/{encoded_path}"


def fetch_public_github_file(
    repository_url: str,
    file_path: str,
    branch_candidates: list[str] | tuple[str, ...] | None = None,
) -> GitHubFileFetchResult:
    repo_ref = parse_github_repo_url(repository_url)
    if repo_ref is None:
        return GitHubFileFetchResult(ok=False, error="unsupported_github_url")

    requested_path = (file_path or repo_ref.file_path or "").strip().lstrip("/")
    if not requested_path:
        return GitHubFileFetchResult(ok=False, error="missing_file_path")

    branches = _branch_candidates(repo_ref.branch, branch_candidates)
    last_status: int | None = None
    last_error: str | None = None

    for branch in branches:
        raw_url = build_raw_github_url(repository_url, requested_path, branch)
        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                with client.stream("GET", raw_url) as response:
                    last_status = response.status_code
                    if response.status_code == 404:
                        last_error = "file_not_found"
                        continue
                    if response.status_code >= 400:
                        last_error = "fetch_failed"
                        continue

                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > MAX_GITHUB_FILE_BYTES:
                        return GitHubFileFetchResult(
                            ok=False,
                            branch=branch,
                            raw_url=raw_url,
                            error="file_too_large",
                            status_code=response.status_code,
                        )

                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > MAX_GITHUB_FILE_BYTES:
                            return GitHubFileFetchResult(
                                ok=False,
                                branch=branch,
                                raw_url=raw_url,
                                error="file_too_large",
                                status_code=response.status_code,
                            )
                        chunks.append(chunk)

                    content = b"".join(chunks).decode("utf-8", errors="replace")
                    return GitHubFileFetchResult(
                        ok=True,
                        content=content,
                        branch=branch,
                        raw_url=raw_url,
                        status_code=response.status_code,
                    )
        except (httpx.HTTPError, ValueError):
            last_error = "network_error"

    return GitHubFileFetchResult(ok=False, error=last_error or "fetch_failed", status_code=last_status)


def extract_line_range(content: str, line_start: int | None, line_end: int | None) -> LineRangeResult:
    lines = content.splitlines()
    line_count = len(lines)

    if line_start is None and line_end is None:
        return LineRangeResult(
            ok=True,
            content=content,
            line_start=None,
            line_end=None,
            summary_range="full file inspected",
        )

    start = line_start or 1
    end = line_end or line_count

    if start > line_count:
        return LineRangeResult(
            ok=False,
            content="",
            line_start=start,
            line_end=end,
            summary_range=f"lines {start}-{end}",
            error=f"Line range starts at {start}, but the GitHub file only has {line_count} lines.",
        )

    clamped_end = min(end, line_count)
    selected = "\n".join(lines[start - 1 : clamped_end])
    summary_range = f"lines {start}-{clamped_end}"
    if end > line_count:
        summary_range = f"lines {start}-{clamped_end} (requested end line {end} was beyond file length)"

    return LineRangeResult(
        ok=True,
        content=selected,
        line_start=start,
        line_end=clamped_end,
        summary_range=summary_range,
    )


def inspect_skill_usage(skill_name: str, content_or_lines: str, evidence_description: str | None = None) -> bool:
    skill = (skill_name or "").lower()
    content = f"{content_or_lines or ''}\n{evidence_description or ''}".lower()

    if "python" in skill:
        return _contains_any(content, ("import ", "def ", "class ", "pandas", "numpy", "sklearn", "torch", "tensorflow", "fastapi"))

    if _contains_any(skill, ("machine learning", "ml", "deep learning", "data science", "artificial intelligence", "ai")):
        return _contains_any(
            content,
            (
                "sklearn",
                "scikit-learn",
                "decisiontree",
                "randomforest",
                "logisticregression",
                "linearregression",
                "train_test_split",
                "fit(",
                "predict(",
                "model",
                "classification",
                "regression",
                "xgboost",
                "lightgbm",
                "tensorflow",
                "keras",
                "torch",
            ),
        )

    if _contains_any(skill, ("rag", "llm", "genai", "generative ai", "prompt engineering", "vector databases")):
        return _contains_any(
            content,
            (
                "openai",
                "anthropic",
                "langchain",
                "llamaindex",
                "embedding",
                "embeddings",
                "vector",
                "retrieval",
                "rag",
                "prompt",
                "llm",
                "chroma",
                "pinecone",
                "faiss",
            ),
        )

    if _contains_any(skill, ("mlops", "fastapi", "docker", "cloud", "ci/cd", "github actions", "deployment")):
        return _contains_any(
            content,
            ("fastapi", "uvicorn", "docker", "dockerfile", "github actions", "cloudrun", "deploy", "prometheus", "grafana", "monitoring", "api"),
        )

    if "sql" in skill:
        return _contains_any(content, ("select", "from", "where", "join", "group by", "create table", "insert into"))

    if _contains_any(skill, ("javascript", "typescript")):
        return _contains_any(content, ("import ", "export ", "function", "const ", "let ", "react", "next.js"))

    return False


def verify_github_file_evidence(payload_or_record: Any) -> dict[str, str] | None:
    data = _as_dict(payload_or_record)
    repository_url = data.get("repository_url") or data.get("evidence_url")
    file_path = data.get("file_path")
    if not repository_url or not file_path or parse_github_repo_url(str(repository_url)) is None:
        return None

    fetch_result = fetch_public_github_file(str(repository_url), str(file_path))
    if not fetch_result.ok:
        if fetch_result.error == "file_too_large":
            summary = "GitHub file is larger than the 1 MB Phase 2 limit and needs review."
        else:
            summary = "Could not fetch the public GitHub file. Please check the repository URL, file path, and branch."
        return {
            "status": "needs_review",
            "summary": summary,
            "verifier_version": GITHUB_FILE_VERIFIER_VERSION,
        }

    line_range = extract_line_range(fetch_result.content or "", data.get("line_start"), data.get("line_end"))
    if not line_range.ok:
        return {
            "status": "needs_review",
            "summary": line_range.error or "The selected line range could not be inspected.",
            "verifier_version": GITHUB_FILE_VERIFIER_VERSION,
        }

    content_for_inspection = line_range.content
    skill_name = str(data.get("skill_name") or "")
    description = str(data.get("evidence_description") or "")
    if _extension_confirms_skill(skill_name, str(file_path)) or inspect_skill_usage(skill_name, content_for_inspection, description):
        return {
            "status": "verified",
            "summary": f"Verified from public GitHub file. Relevant evidence found in {line_range.summary_range}.",
            "verifier_version": GITHUB_FILE_VERIFIER_VERSION,
        }

    return {
        "status": "skill_usage_not_found",
        "summary": f"GitHub file was fetched, but the selected lines did not clearly demonstrate {skill_name}.",
        "verifier_version": GITHUB_FILE_VERIFIER_VERSION,
    }


def _branch_candidates(
    preferred_branch: str | None,
    branch_candidates: list[str] | tuple[str, ...] | None,
) -> list[str]:
    candidates = list(branch_candidates or DEFAULT_BRANCH_CANDIDATES)
    if preferred_branch:
        candidates.insert(0, preferred_branch)

    deduped: list[str] = []
    for branch in candidates:
        if branch and branch not in deduped:
            deduped.append(branch)
    return deduped


def _extension_confirms_skill(skill_name: str, file_path: str) -> bool:
    skill = skill_name.lower()
    path = file_path.lower()
    if "python" in skill and path.endswith((".py", ".ipynb")):
        return True
    if "sql" in skill and path.endswith(".sql"):
        return True
    if _contains_any(skill, ("javascript", "typescript")) and path.endswith((".js", ".jsx", ".ts", ".tsx")):
        return True
    return False


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


def _as_dict(payload_or_record: Any) -> dict[str, Any]:
    if isinstance(payload_or_record, dict):
        return payload_or_record
    if hasattr(payload_or_record, "model_dump"):
        return payload_or_record.model_dump()
    return dict(payload_or_record)
