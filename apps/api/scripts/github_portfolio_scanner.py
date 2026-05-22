"""
github_portfolio_scanner.py
============================
Core library for the VeriBridge GitHub Portfolio Importer (Phase J3A).

Scans a public GitHub profile, detects skills from repository content,
and selects precise high-signal line ranges for proof evidence creation.

Design principles:
- Fully testable: inject a mock GitHubAPIClient in tests (no live HTTP required)
- No external LLM calls — deterministic rule-based heuristics
- Avoids weak line ranges (import-only, comment-only, boilerplate)
- Prefers function bodies, ML training calls, API endpoints, deployment configs
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class RepoInfo:
    name: str
    url: str
    description: str | None
    homepage: str | None
    default_branch: str
    languages: dict[str, int]        # {lang: bytes_of_code}
    topics: list[str]
    stars: int
    owner: str


@dataclass
class EvidenceCandidate:
    skill_name: str
    project_title: str
    repo_url: str
    repo_name: str
    file_path: str
    line_start: int
    line_end: int
    evidence_description: str
    student_claim: str
    evidence_type: str               # "github repository"
    website_url: str | None
    detection_reason: str
    github_highlight_url: str
    import_key: str                  # deduplicate key


@dataclass
class ImportResult:
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ── GitHub API client (injectable / mockable) ─────────────────────────────────

class GitHubAPIClient:
    """
    Thin wrapper around the GitHub REST API.

    Pass a dict-based mock in tests:
        mock = {"repos/machackgo": [...], "tree/...": [...], "file/...": "..."}
    """

    GITHUB_API = "https://api.github.com"
    GITHUB_RAW = "https://raw.githubusercontent.com"

    def __init__(
        self,
        token: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._token = token
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _rate_limit_error(self, resp: Any) -> ValueError:
        """Build a helpful ValueError from a 403/429 rate-limit response."""
        import datetime

        remaining = resp.headers.get("X-RateLimit-Remaining", "?")
        reset_ts = resp.headers.get("X-RateLimit-Reset")
        reset_msg = ""
        if reset_ts:
            try:
                dt = datetime.datetime.utcfromtimestamp(int(reset_ts))
                reset_msg = f" Rate limit resets at {dt.strftime('%H:%M UTC')}."
            except (ValueError, OSError):
                pass

        if self._token:
            hint = (
                "Authenticated GitHub rate limit reached."
                f"{reset_msg} Try again after the reset or reduce Max Repos."
            )
        else:
            hint = (
                "Unauthenticated GitHub requests are limited to 60 per hour."
                f"{reset_msg} "
                "Add GITHUB_TOKEN to the backend .env for reliable scanning."
            )

        return ValueError(f"GitHub API rate limit reached. {hint}")

    def get_repo(self, owner: str, repo: str) -> dict[str, Any] | None:
        """Fetch metadata for a single repo; normalises language fields for _parse_repo."""
        url = f"{self.GITHUB_API}/repos/{owner}/{repo}"
        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                resp = client.get(url, headers=self._headers())
                if resp.status_code == 200:
                    data = resp.json()
                    if "languages" not in data:
                        primary = data.get("language") or ""
                        data["languages"] = {primary: 100} if primary else {}
                    return data
                if resp.status_code == 404:
                    raise ValueError(f"GitHub repository '{owner}/{repo}' not found.")
                if resp.status_code in (403, 429):
                    raise self._rate_limit_error(resp)
                return None
        except ValueError:
            raise
        except (httpx.HTTPError, Exception):
            return None

    def list_repos(self, username: str) -> list[dict[str, Any]]:
        url = f"{self.GITHUB_API}/users/{username}/repos"
        params = {"per_page": 100, "sort": "updated", "direction": "desc"}
        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                resp = client.get(url, headers=self._headers(), params=params)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 404:
                    raise ValueError(f"GitHub user '{username}' not found.")
                if resp.status_code in (403, 429):
                    raise self._rate_limit_error(resp)
                # Other non-200 — return empty, do not raise
                return []
        except ValueError:
            raise
        except (httpx.HTTPError, Exception):
            return []

    def get_file_tree(
        self, owner: str, repo: str, branch: str
    ) -> list[dict[str, Any]]:
        url = f"{self.GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}"
        params = {"recursive": "1"}
        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                resp = client.get(url, headers=self._headers(), params=params)
                if resp.status_code != 200:
                    return []
                data = resp.json()
                return data.get("tree", [])
        except (httpx.HTTPError, ValueError):
            return []

    def get_raw_file(
        self, owner: str, repo: str, branch: str, path: str
    ) -> str | None:
        encoded_path = "/".join(quote(p) for p in path.split("/"))
        url = f"{self.GITHUB_RAW}/{owner}/{repo}/{branch}/{encoded_path}"
        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                resp = client.get(url, headers=self._headers())
                if resp.status_code != 200:
                    return None
                if len(resp.content) > 500_000:
                    return None
                return resp.text
        except (httpx.HTTPError, ValueError):
            return None


class MockGitHubAPIClient:
    """
    Dict-based mock for tests. Stores data in nested dicts so tests
    inject precise content without any network calls.
    """

    def __init__(
        self,
        repos_by_user: dict[str, list[dict]] | None = None,
        trees_by_repo: dict[str, list[dict]] | None = None,
        files_by_path: dict[str, str] | None = None,
    ) -> None:
        self._repos = repos_by_user or {}
        self._trees = trees_by_repo or {}
        self._files = files_by_path or {}

    def list_repos(self, username: str) -> list[dict[str, Any]]:
        return self._repos.get(username, [])

    def get_file_tree(
        self, owner: str, repo: str, branch: str
    ) -> list[dict[str, Any]]:
        key = f"{owner}/{repo}"
        return self._trees.get(key, [])

    def get_repo(self, owner: str, repo: str) -> dict[str, Any] | None:
        """Not implemented in mock — returns None."""
        return None

    def get_raw_file(
        self, owner: str, repo: str, branch: str, path: str
    ) -> str | None:
        key = f"{owner}/{repo}/{path}"
        return self._files.get(key)


# ── Skill detector ────────────────────────────────────────────────────────────

# Map from lowercase language name → VeriBridge skill label
_LANGUAGE_TO_SKILL: dict[str, str] = {
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "go": "Go",
    "java": "Java",
    "rust": "Rust",
    "c++": "C++",
    "c": "C",
    "shell": "Shell Scripting",
    "dockerfile": "Docker",
    "yaml": "CI/CD",
    "html": "Web Development",
    "css": "Web Development",
    "sql": "SQL",
    "r": "R",
    "julia": "Julia",
}

# README / description keyword → skill label
_KEYWORD_SKILLS: list[tuple[tuple[str, ...], str]] = [
    (("machine learning", "sklearn", "scikit-learn", "xgboost", "lightgbm",
      "decision tree", "random forest", "neural network", "deep learning"), "Machine Learning"),
    (("fastapi", "flask", "django", "api endpoint", "rest api"), "FastAPI"),
    (("docker", "dockerfile", "containeriz"), "Docker"),
    (("kubernetes", "k8s", "helm"), "Kubernetes"),
    (("rag", "retrieval augmented", "langchain", "llm", "openai", "anthropic",
      "embedding", "vector database", "llamaindex"), "RAG / LLM"),
    (("natural language", "nlp", "text classification", "sentiment", "spacy",
      "nltk", "bert", "transformer"), "NLP"),
    (("computer vision", "image classification", "object detection", "opencv",
      "yolo", "cnn"), "Computer Vision"),
    (("react", "next.js", "nextjs", "frontend", "jsx", "tsx"), "React"),
    (("cloud run", "google cloud", "gcp", "app engine"), "GCP"),
    (("aws", "lambda", "ec2", "s3", "sagemaker"), "AWS"),
    (("azure",), "Azure"),
    (("supabase", "postgresql", "postgres"), "PostgreSQL"),
    (("github actions", "ci/cd", "workflow", "pipeline"), "CI/CD"),
    (("mlops", "monitoring", "prometheus", "mlflow", "bentoml"), "MLOps"),
    (("data engineering", "etl", "pipeline", "spark", "airflow"), "Data Engineering"),
]


def detect_skills_from_repo(
    repo: RepoInfo,
    file_paths: list[str],
    readme_text: str | None = None,
) -> list[str]:
    """
    Return a deduplicated list of VeriBridge skill labels for the repo.
    Uses repo languages, file paths, topics, description, and README.
    """
    skills: list[str] = []
    seen: set[str] = set()

    def add(skill: str) -> None:
        if skill not in seen:
            seen.add(skill)
            skills.append(skill)

    # From repo primary languages
    for lang, count in sorted(repo.languages.items(), key=lambda kv: kv[1], reverse=True):
        skill = _LANGUAGE_TO_SKILL.get(lang.lower())
        if skill:
            add(skill)

    # File-path heuristics
    path_lower = " ".join(f.lower() for f in file_paths)
    if "dockerfile" in path_lower:
        add("Docker")
    if ".github/workflows" in path_lower:
        add("CI/CD")
    if "requirements.txt" in path_lower or "pyproject.toml" in path_lower:
        add("Python")
    if "package.json" in path_lower:
        pass  # already handled by language
    if "terraform" in path_lower or ".tf" in path_lower:
        add("Cloud Deployment")
    if any(p.endswith(".sql") for p in file_paths):
        add("SQL")

    # Topic heuristics
    topic_str = " ".join(repo.topics).lower()
    for keywords, skill in _KEYWORD_SKILLS:
        if any(kw in topic_str for kw in keywords):
            add(skill)

    # Description + README heuristics
    text = " ".join(
        filter(None, [repo.description, readme_text])
    ).lower()
    for keywords, skill in _KEYWORD_SKILLS:
        if any(kw in text for kw in keywords):
            add(skill)

    return skills


# ── Line range selector ───────────────────────────────────────────────────────

# High-signal patterns per category with priority scores
_SIGNAL_PATTERNS: list[tuple[re.Pattern, int, str]] = [
    # ML training
    (re.compile(r"\.fit\(|\.fit_transform\(|train_test_split\("), 10, "ML training call"),
    (re.compile(r"DecisionTree|RandomForest|LogisticRegression|XGB|LightGBM|GradientBoosting|SVC\(|KNeighbors"), 9, "ML model instantiation"),
    # ML inference & evaluation
    (re.compile(r"\.predict\(|\.predict_proba\(|y_pred\s*="), 9, "ML prediction/inference"),
    (re.compile(r"accuracy_score|f1_score|classification_report|roc_auc_score|confusion_matrix|precision_score|recall_score|mean_squared_error|r2_score"), 8, "ML evaluation metrics"),
    # FastAPI / Flask endpoints
    (re.compile(r"@(app|router)\.(get|post|put|delete|patch)\("), 10, "API endpoint decorator"),
    (re.compile(r"async def |def [a-z_]+\(.*request|def [a-z_]+\(.*Response"), 6, "API handler function"),
    # Docker
    (re.compile(r"^(FROM|RUN|CMD|ENTRYPOINT|COPY|WORKDIR|EXPOSE|ENV)\s", re.MULTILINE), 8, "Dockerfile instruction"),
    # GitHub Actions / CI/CD
    (re.compile(r"^\s+(run:|uses:|steps:)", re.MULTILINE), 7, "CI/CD workflow step"),
    # Cloud deployment
    (re.compile(r"gcloud |kubectl |helm |terraform |aws |az "), 7, "Cloud deployment command"),
    # Database / Supabase
    (re.compile(r"\.table\(|\.select\(|supabase|create_engine|SQLAlchemy|execute\(|db\.session"), 7, "Database query"),
    # RAG / LLM
    (re.compile(r"openai\.|anthropic\.|langchain|llamaindex|Chroma|Pinecone|FAISS|embedding|retrieval|vectorstore"), 9, "RAG/LLM logic"),
    # NLP
    (re.compile(r"tokenizer\.|\.encode\(|\.decode\(|BertModel|pipeline\(|spacy\.load|nlp\("), 8, "NLP processing"),
    # React / Next.js
    (re.compile(r"useState|useEffect|useCallback|useMemo|export default function|return \(.*jsx|<[A-Z][a-zA-Z]+"), 7, "React component logic"),
    # Monitoring
    (re.compile(r"prometheus_client|Counter\(|Gauge\(|Histogram\(|push_to_gateway|@metrics\."), 7, "Monitoring/metrics"),
    # Data preprocessing
    (re.compile(r"read_csv|\.dropna\(|\.fillna\(|StandardScaler|MinMaxScaler|LabelEncoder|\.merge\(|\.groupby\("), 6, "Data preprocessing"),
]

_IMPORT_PATTERN = re.compile(r"^(import |from .+ import )")
_COMMENT_PATTERN = re.compile(r"^\s*(#|//|/\*|\*|<!--|$)")


def _score_line(line: str) -> tuple[int, str]:
    """Return (score, reason) for a single line. Higher = more signal."""
    stripped = line.strip()
    if not stripped:
        return 0, ""
    # Import-only lines get a negative score (we want to avoid them)
    if _IMPORT_PATTERN.match(stripped):
        return -2, "import statement"
    if _COMMENT_PATTERN.match(stripped):
        return 0, ""

    for pattern, score, reason in _SIGNAL_PATTERNS:
        if pattern.search(line):
            return score, reason
    return 1, "code line"


def is_weak_range(lines: list[str]) -> bool:
    """
    Return True if a line range is not worth submitting as evidence.

    A range is weak when:
    - It is empty / all whitespace
    - >70% of non-empty lines are import statements
    - >80% are pure comments
    """
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return True

    import_count = sum(1 for l in non_empty if _IMPORT_PATTERN.match(l.strip()))
    comment_count = sum(1 for l in non_empty if _COMMENT_PATTERN.match(l.strip()))

    if import_count / len(non_empty) > 0.70:
        return True
    if comment_count / len(non_empty) > 0.80:
        return True
    return False


def _group_anchors(
    anchors: list[tuple[int, int, str]], gap: int = 12
) -> list[list[tuple[int, int, str]]]:
    """Cluster anchor lines that are within `gap` lines of each other."""
    if not anchors:
        return []
    groups: list[list[tuple[int, int, str]]] = [[anchors[0]]]
    for anchor in anchors[1:]:
        if anchor[0] - groups[-1][-1][0] <= gap:
            groups[-1].append(anchor)
        else:
            groups.append([anchor])
    return groups


def select_high_signal_ranges(
    content: str,
    file_path: str,
    skill: str,
    max_ranges: int = 3,
) -> list[tuple[int, int, str]]:
    """
    Scan `content` and return up to `max_ranges` high-signal line ranges.

    Each result is (line_start, line_end, detection_reason) — 1-indexed.

    Guarantees:
    - No import-only or comment-only ranges
    - Line ranges are valid (start <= end, within file bounds)
    - At most `max_ranges` results
    """
    lines = content.splitlines()
    if not lines:
        return []

    total = len(lines)

    # Score each line
    anchor_lines: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        score, reason = _score_line(line)
        if score >= 5:  # only high-signal lines become anchors
            anchor_lines.append((i + 1, score, reason))

    if not anchor_lines:
        return []

    # Sort by score descending, then cluster by proximity
    anchor_lines.sort(key=lambda t: t[1], reverse=True)
    # Re-sort by line number for grouping
    anchor_lines.sort(key=lambda t: t[0])

    groups = _group_anchors(anchor_lines, gap=15)

    results: list[tuple[int, int, str]] = []
    seen_starts: set[int] = set()

    for group in groups:
        if not group:
            continue
        anchor_start = group[0][0]
        anchor_end = group[-1][0]
        best_reason = max(group, key=lambda t: t[1])[2]

        # Expand range: 3 lines before the first anchor, 15 lines after the last
        exp_start = max(1, anchor_start - 3)
        exp_end = min(total, anchor_end + 15)

        # Avoid duplicating ranges that start very close together
        if any(abs(exp_start - s) < 8 for s in seen_starts):
            continue

        range_lines = lines[exp_start - 1 : exp_end]

        # Skip weak ranges
        if is_weak_range(range_lines):
            continue

        seen_starts.add(exp_start)
        results.append((exp_start, exp_end, best_reason))

        if len(results) >= max_ranges:
            break

    return results


# ── Dockerfile range selector ─────────────────────────────────────────────────

def select_dockerfile_range(content: str) -> tuple[int, int] | None:
    """
    Return the best (start, end) range from a Dockerfile.

    Prefers the last FROM...CMD block which usually describes the runtime image.
    """
    lines = content.splitlines()
    if not lines:
        return None

    # Find all FROM lines
    from_positions = [i + 1 for i, l in enumerate(lines) if l.strip().upper().startswith("FROM ")]
    if not from_positions:
        return None

    # Use the last FROM block (runtime stage in multi-stage builds)
    start = from_positions[-1]
    end = len(lines)

    # Cap at 40 lines
    end = min(end, start + 39)

    range_lines = lines[start - 1 : end]
    if is_weak_range(range_lines):
        return None

    return (start, end)


# ── YAML workflow range selector ───────────────────────────────────────────────

def select_workflow_range(content: str) -> tuple[int, int] | None:
    """
    Return the best (start, end) range from a GitHub Actions YAML file.

    Finds the first job's steps section.
    """
    lines = content.splitlines()
    if not lines:
        return None

    steps_start: int | None = None
    for i, line in enumerate(lines):
        if re.match(r"\s+steps:", line):
            steps_start = i + 1
            break

    if steps_start is None:
        return None

    # Include up to 35 lines of steps
    end = min(len(lines), steps_start + 34)
    range_lines = lines[steps_start - 1 : end]

    # Must have at least one run: or uses: line
    if not any(re.search(r"\s+(run:|uses:)", l) for l in range_lines):
        return None

    return (steps_start, end)


# ── GitHub URL builder ─────────────────────────────────────────────────────────

def build_github_highlight_url(
    owner: str,
    repo: str,
    branch: str,
    file_path: str,
    line_start: int,
    line_end: int,
) -> str:
    """Build a GitHub blob URL with line-range highlight anchor."""
    encoded_path = "/".join(quote(p) for p in file_path.split("/"))
    fragment = (
        f"#L{line_start}"
        if line_start == line_end
        else f"#L{line_start}-L{line_end}"
    )
    return f"https://github.com/{owner}/{repo}/blob/{branch}/{encoded_path}{fragment}"


# ── Import key / duplicate detection ─────────────────────────────────────────

def make_import_key(
    user_id: str,
    repo_url: str,
    file_path: str,
    line_start: int,
    line_end: int,
    skill_name: str,
) -> str:
    """Deterministic dedup key for an evidence candidate."""
    return f"{user_id}|{repo_url}|{file_path}|{line_start}|{line_end}|{skill_name}"


def check_duplicate(
    supabase_client: Any,
    user_id: str,
    candidate: EvidenceCandidate,
) -> bool:
    """
    Return True if this evidence already exists for the user.

    Checks by import_key stored in metadata, or by exact field match.
    """
    if isinstance(supabase_client, dict):
        table = supabase_client.get("skill_evidence", {})
        for row in table.values():
            if row.get("user_id") != user_id:
                continue
            meta = row.get("metadata") or {}
            if isinstance(meta, dict) and meta.get("import_key") == candidate.import_key:
                return True
        return False

    result = (
        supabase_client.table("skill_evidence")
        .select("id")
        .eq("user_id", user_id)
        .eq("repository_url", candidate.repo_url)
        .eq("file_path", candidate.file_path)
        .eq("line_start", candidate.line_start)
        .eq("line_end", candidate.line_end)
        .eq("skill_name", candidate.skill_name)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return len(rows) > 0


# ── High-signal file filter ───────────────────────────────────────────────────

_HIGH_SIGNAL_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs",
    ".sql", ".yaml", ".yml",
}

_HIGH_SIGNAL_FILENAMES = {
    "dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "requirements.txt", "pyproject.toml", "package.json",
    "main.py", "app.py", "api.py", "server.py", "model.py",
    "train.py", "predict.py", "inference.py", "pipeline.py",
    "index.ts", "index.tsx", "index.js",
}

_SKIP_PATH_PATTERNS = (
    "node_modules/", ".git/", "__pycache__/", "venv/", ".venv/",
    "dist/", "build/", ".next/", "coverage/", ".pytest_cache/",
    "migrations/", "static/", "assets/",
)

_SKIP_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
                    ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".zip",
                    ".tar", ".gz", ".lock", ".sum"}


def is_high_signal_file(path: str) -> bool:
    """Return True for files worth scanning for evidence."""
    path_lower = path.lower()

    # Skip obvious non-code paths
    if any(skip in path_lower for skip in _SKIP_PATH_PATTERNS):
        return False

    # Known high-signal filenames
    filename = path_lower.split("/")[-1]
    if filename in _HIGH_SIGNAL_FILENAMES:
        return True

    # Dockerfile (no extension)
    if filename == "dockerfile" or filename.startswith("dockerfile."):
        return True

    # GitHub Actions workflows
    if ".github/workflows/" in path_lower and path_lower.endswith((".yml", ".yaml")):
        return True

    # Extension-based inclusion
    for ext in _HIGH_SIGNAL_EXTENSIONS:
        if path_lower.endswith(ext):
            # Skip minified/generated files
            if ".min." in path_lower or ".bundle." in path_lower or "generated" in path_lower:
                return False
            return True

    # Skip everything else
    _, dot, ext = path_lower.rpartition(".")
    if dot and f".{ext}" in _SKIP_EXTENSIONS:
        return False

    return False


# ── Website URL detection ─────────────────────────────────────────────────────

_KNOWN_DEPLOY_PATTERNS = (
    ".vercel.app", ".netlify.app", ".render.com",
    ".run.app", ".web.app", ".firebase.app",
    ".heroku.com", ".pages.dev",
)


def extract_website_url(repo: RepoInfo, readme: str | None) -> str | None:
    """
    Return a public deployment URL for the repo, or None.

    Checks repo.homepage first, then scans README for known deploy patterns.
    """
    homepage = (repo.homepage or "").strip()
    if homepage and homepage.startswith(("https://", "http://")) and "localhost" not in homepage:
        return homepage

    if readme:
        # Look for URLs matching known deployment platforms
        urls = re.findall(r"https?://[^\s\)\]\"']+", readme)
        for url in urls:
            url_lower = url.lower().rstrip(".,)")
            if any(pat in url_lower for pat in _KNOWN_DEPLOY_PATTERNS):
                if "localhost" not in url_lower and "127.0.0.1" not in url_lower:
                    return url_lower

    return None


# ── Evidence description generator ────────────────────────────────────────────

def build_evidence_description(
    skill: str,
    repo_name: str,
    file_path: str,
    line_start: int,
    line_end: int,
    detection_reason: str,
) -> str:
    """Generate a readable evidence description for a proof record."""
    line_ref = (
        f"line {line_start}"
        if line_start == line_end
        else f"lines {line_start}–{line_end}"
    )
    filename = file_path.split("/")[-1]
    return (
        f"I used {skill} in the {repo_name} repository. "
        f"The evidence is in {filename} ({line_ref}), which contains {detection_reason}."
    )


def build_student_claim(
    skill: str,
    repo_name: str,
    detection_reason: str,
) -> str:
    """Generate a first-person student claim for a proof record."""
    return (
        f"I built and worked with {skill} in {repo_name}. "
        f"The selected code demonstrates {detection_reason}."
    )


# ── Smart Scan ranking ────────────────────────────────────────────────────────

def _smart_rank_repos(repos: list[RepoInfo]) -> list[RepoInfo]:
    """
    Rank repos by evidence-richness signals so the cap (max_repos) selects the
    most proof-bearing repositories for large GitHub profiles.

    Signal weights:
    - Has non-empty description   → +4
    - Has topics                  → +1.5 per topic, capped at +6
    - Stars                       → +0.1 per star, capped at +3
    - Recently updated order preserved as stable tie-breaker (GitHub API returns
      repos sorted by pushed_at desc, so the slice after sorting keeps that bias
      for equal-scored repos via Python's stable sort).
    """
    def score(r: RepoInfo) -> float:
        s = 0.0
        if r.description and r.description.strip():
            s += 4.0
        if r.topics:
            s += min(len(r.topics) * 1.5, 6.0)
        s += min(r.stars * 0.1, 3.0)
        return s

    return sorted(repos, key=score, reverse=True)


# ── Portfolio scanner (main orchestrator) ─────────────────────────────────────

class ScanStats:
    """Populated by PortfolioScanner.scan() so the service layer can report metadata."""
    repos_available: int = 0    # repos returned by list_repos (after fork/archived filter)
    repos_selected: int = 0     # repos after smart_scan ranking + max_repos cap
    repos_with_evidence: int = 0  # repos that produced ≥1 EvidenceCandidate


class PortfolioScanner:
    """
    Orchestrates a full GitHub profile scan and produces EvidenceCandidates.

    Usage:
        client = GitHubAPIClient(token=os.getenv("GITHUB_TOKEN"))
        scanner = PortfolioScanner(client)
        candidates = scanner.scan("machackgo", max_repos=20)
    """

    def __init__(self, github_client: GitHubAPIClient | MockGitHubAPIClient) -> None:
        self._github = github_client
        self.stats = ScanStats()

    def scan(
        self,
        username: str,
        max_repos: int = 25,
        include_repos: list[str] | None = None,
        exclude_repos: list[str] | None = None,
        smart_scan: bool = True,
    ) -> list[EvidenceCandidate]:
        """Scan `username`'s public GitHub repos and return evidence candidates."""
        raw_repos = self._github.list_repos(username)
        repo_infos = [_parse_repo(r) for r in raw_repos if _parse_repo(r) is not None]

        # Filter by explicit include/exclude lists
        if include_repos:
            repo_infos = [r for r in repo_infos if r.name in include_repos]
        if exclude_repos:
            repo_infos = [r for r in repo_infos if r.name not in exclude_repos]

        self.stats.repos_available = len(repo_infos)

        # Smart Scan: rank repos by evidence-richness signals before applying the cap.
        # This ensures the most proof-bearing repos are prioritised for large profiles.
        if smart_scan:
            repo_infos = _smart_rank_repos(repo_infos)

        repo_infos = repo_infos[:max_repos]
        self.stats.repos_selected = len(repo_infos)

        candidates: list[EvidenceCandidate] = []
        for repo in repo_infos:
            repo_candidates = self._scan_repo(username, repo)
            if repo_candidates:
                self.stats.repos_with_evidence += 1
            candidates.extend(repo_candidates)

        return candidates

    def scan_repo_by_url(self, owner: str, repo_name: str) -> list[EvidenceCandidate]:
        """Scan a single known repository without listing all user repos first.

        Uses GET /repos/{owner}/{repo} for metadata, then scans the file tree
        with the same logic as the full portfolio scan.
        """
        raw = self._github.get_repo(owner, repo_name)
        if raw is None:
            return []
        repo_info = _parse_repo(raw)
        if repo_info is None:
            return []
        return self._scan_repo(owner, repo_info)

    def _scan_repo(
        self, username: str, repo: RepoInfo
    ) -> list[EvidenceCandidate]:
        branch = repo.default_branch or "main"
        tree = self._github.get_file_tree(username, repo.name, branch)
        file_paths = [item["path"] for item in tree if item.get("type") == "blob"]

        # Fetch README for skill detection context
        readme_text: str | None = None
        for readme_name in ("README.md", "readme.md", "README.rst", "README"):
            if readme_name in file_paths:
                readme_text = self._github.get_raw_file(username, repo.name, branch, readme_name)
                if readme_text:
                    break

        skills = detect_skills_from_repo(repo, file_paths, readme_text)
        if not skills:
            return []

        website_url = extract_website_url(repo, readme_text)
        candidates: list[EvidenceCandidate] = []
        seen_file_paths: set[str] = set()

        # Pick the high-signal files worth scanning
        scannable = sorted(
            [p for p in file_paths if is_high_signal_file(p)],
            key=_file_priority,
        )

        for file_path in scannable[:20]:  # scan at most 20 files per repo
            if file_path in seen_file_paths:
                continue

            content = self._github.get_raw_file(username, repo.name, branch, file_path)
            if not content:
                continue

            file_candidates = self._extract_candidates_from_file(
                repo, branch, file_path, content, skills, website_url
            )
            if file_candidates:
                seen_file_paths.add(file_path)
                candidates.extend(file_candidates)

        return candidates

    def _extract_candidates_from_file(
        self,
        repo: RepoInfo,
        branch: str,
        file_path: str,
        content: str,
        skills: list[str],
        website_url: str | None,
    ) -> list[EvidenceCandidate]:
        path_lower = file_path.lower()
        candidates: list[EvidenceCandidate] = []

        # Dockerfile
        if path_lower.endswith(("dockerfile", "dockerfile.prod", "dockerfile.dev")) or path_lower.split("/")[-1] == "dockerfile":
            if "Docker" in skills:
                result = select_dockerfile_range(content)
                if result:
                    start, end = result
                    candidates.append(self._make_candidate(
                        repo, branch, file_path, start, end,
                        "Docker", "Dockerfile instruction",
                        website_url,
                    ))

        # GitHub Actions workflow
        elif ".github/workflows/" in path_lower and path_lower.endswith((".yml", ".yaml")):
            if "CI/CD" in skills:
                result = select_workflow_range(content)
                if result:
                    start, end = result
                    candidates.append(self._make_candidate(
                        repo, branch, file_path, start, end,
                        "CI/CD", "CI/CD workflow step",
                        website_url,
                    ))

        # Python / ML / FastAPI files
        elif path_lower.endswith((".py", ".ipynb")):
            relevant_skills = [
                s for s in skills
                if s in ("Python", "Machine Learning", "FastAPI", "Deep Learning",
                         "NLP", "Computer Vision", "RAG / LLM", "MLOps",
                         "Data Engineering", "PostgreSQL")
            ]
            if not relevant_skills:
                relevant_skills = [skills[0]] if skills else []

            best_skill = relevant_skills[0]
            ranges = select_high_signal_ranges(content, file_path, best_skill, max_ranges=2)
            for start, end, reason in ranges:
                candidates.append(self._make_candidate(
                    repo, branch, file_path, start, end,
                    best_skill, reason, website_url,
                ))

        # TypeScript / JavaScript / React
        elif path_lower.endswith((".ts", ".tsx", ".js", ".jsx")):
            react_skills = [s for s in skills if s in ("React", "TypeScript", "JavaScript")]
            if react_skills:
                skill = react_skills[0]
                ranges = select_high_signal_ranges(content, file_path, skill, max_ranges=2)
                for start, end, reason in ranges:
                    candidates.append(self._make_candidate(
                        repo, branch, file_path, start, end,
                        skill, reason, website_url,
                    ))

        # YAML (non-workflow) — skip for now, too noisy
        return candidates

    def _make_candidate(
        self,
        repo: RepoInfo,
        branch: str,
        file_path: str,
        line_start: int,
        line_end: int,
        skill_name: str,
        detection_reason: str,
        website_url: str | None,
    ) -> EvidenceCandidate:
        project_title = _prettify_repo_name(repo.name)
        highlight_url = build_github_highlight_url(
            repo.owner, repo.name, branch, file_path, line_start, line_end
        )
        description = build_evidence_description(
            skill_name, repo.name, file_path, line_start, line_end, detection_reason
        )
        claim = build_student_claim(skill_name, project_title, detection_reason)
        import_key = make_import_key(
            "",  # user_id filled in at import time
            repo.url, file_path, line_start, line_end, skill_name,
        )
        return EvidenceCandidate(
            skill_name=skill_name,
            project_title=project_title,
            repo_url=repo.url,
            repo_name=repo.name,
            file_path=file_path,
            line_start=line_start,
            line_end=line_end,
            evidence_description=description,
            student_claim=claim,
            evidence_type="github repository",
            website_url=website_url,
            detection_reason=detection_reason,
            github_highlight_url=highlight_url,
            import_key=import_key,
        )


# ── Import pipeline ───────────────────────────────────────────────────────────

def import_candidates(
    supabase_client: Any,
    user_id: str,
    candidates: list[EvidenceCandidate],
    dry_run: bool = True,
) -> ImportResult:
    """
    Create skill_evidence records for each candidate.

    In dry_run mode, returns what WOULD be created without inserting anything.
    Uses SkillEvidenceService for real inserts (same path as the UI).
    """
    result = ImportResult()

    for candidate in candidates:
        # Re-stamp import key with the real user_id
        real_import_key = make_import_key(
            user_id,
            candidate.repo_url,
            candidate.file_path,
            candidate.line_start,
            candidate.line_end,
            candidate.skill_name,
        )
        candidate_with_key = EvidenceCandidate(
            **{**candidate.__dict__, "import_key": real_import_key}
        )

        if check_duplicate(supabase_client, user_id, candidate_with_key):
            result.skipped.append(
                f"SKIP (duplicate): {candidate.skill_name} in {candidate.file_path}:{candidate.line_start}-{candidate.line_end}"
            )
            continue

        if dry_run:
            result.created.append(
                f"DRY-RUN: would create {candidate.skill_name} from {candidate.file_path}:{candidate.line_start}-{candidate.line_end}"
            )
            continue

        # Real insert via SkillEvidenceService
        try:
            from app.schemas.skill_evidence import SkillEvidenceCreate
            from app.services.skill_evidence_service import SkillEvidenceService

            metadata: dict[str, Any] = {
                "evidence_title": candidate.project_title,
                "submission_source": "student_profile_proof_modal",
                "import_source": "github_portfolio_importer",
                "import_key": real_import_key,
                "branch_ref": "main",
            }

            payload = SkillEvidenceCreate(
                skill_name=candidate.skill_name,
                evidence_type=candidate.evidence_type,
                repository_url=candidate.repo_url,
                file_path=candidate.file_path,
                line_start=candidate.line_start,
                line_end=candidate.line_end,
                evidence_description=candidate.evidence_description,
                proof_visibility="public",
                metadata=metadata,
            )
            evidence = SkillEvidenceService(supabase_client).create_skill_evidence(
                user_id, payload
            )
            result.created.append(
                f"CREATED: {evidence.id} — {candidate.skill_name} "
                f"from {candidate.file_path}:{candidate.line_start}-{candidate.line_end} "
                f"[{evidence.verification_status}]"
            )
        except Exception as exc:
            result.errors.append(
                f"ERROR: {candidate.skill_name} in {candidate.file_path}: {exc}"
            )

    return result


# ── Dry-run report builder ─────────────────────────────────────────────────────

def build_dry_run_report(
    username: str,
    candidates: list[EvidenceCandidate],
) -> dict[str, Any]:
    """Build a structured dry-run report dict (suitable for JSON serialization)."""
    items = []
    for c in candidates:
        items.append({
            "repo": c.repo_name,
            "skill": c.skill_name,
            "project_title": c.project_title,
            "file_path": c.file_path,
            "line_start": c.line_start,
            "line_end": c.line_end,
            "github_highlight_url": c.github_highlight_url,
            "detection_reason": c.detection_reason,
            "evidence_description": c.evidence_description,
            "student_claim": c.student_claim,
            "website_url": c.website_url,
        })
    return {
        "github_username": username,
        "total_candidates": len(candidates),
        "candidates": items,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_repo(raw: dict[str, Any]) -> RepoInfo | None:
    """Convert a raw GitHub API repo dict to a RepoInfo. Returns None if incomplete."""
    name = raw.get("name")
    url = raw.get("html_url") or raw.get("clone_url")
    owner_obj = raw.get("owner") or {}
    owner = owner_obj.get("login") or ""
    if not name or not url or not owner:
        return None
    return RepoInfo(
        name=str(name),
        url=str(url),
        description=raw.get("description"),
        homepage=raw.get("homepage"),
        default_branch=raw.get("default_branch") or "main",
        languages=raw.get("languages") or {},
        topics=raw.get("topics") or [],
        stars=int(raw.get("stargazers_count") or 0),
        owner=str(owner),
    )


def _prettify_repo_name(name: str) -> str:
    """Turn 'boston-smart-accident-risk' → 'Boston Smart Accident Risk'."""
    return " ".join(
        word.capitalize()
        for word in re.split(r"[-_]+", name)
    )


def _file_priority(path: str) -> int:
    """
    Assign a scan priority to a file path.
    Lower number = scanned first (most important).
    """
    path_lower = path.lower()
    filename = path_lower.split("/")[-1]

    # Highest priority: core application files
    if filename in ("api.py", "app.py", "main.py", "server.py", "model.py",
                    "train.py", "predict.py", "inference.py"):
        return 0
    if filename == "dockerfile":
        return 1
    if ".github/workflows/" in path_lower:
        return 2
    # Other Python files
    if path_lower.endswith(".py"):
        return 3
    # TypeScript/JavaScript
    if path_lower.endswith((".ts", ".tsx", ".js", ".jsx")):
        return 4
    # Other
    return 10
