"""Website AI Analyzer Service — Phase J4D / J4E.

Fetches a public URL, inspects common API routes, parses OpenAPI specs,
and extracts evidence candidates for the Skill Proof Center.

Security:
- SSRF protection: blocks private IP ranges and localhost.
- Timeout on every external fetch (8 seconds).
- Response size capped at 150 KB.
- Only http/https; no credentials accepted.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
import socket
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.schemas.website_analyzer import (
    WebsiteAnalysisCandidate,
    WebsiteAnalyzeResponse,
)

# Import scanner for single-repo analysis (J4E)
_API_ROOT = Path(__file__).resolve().parents[2]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from scripts.github_portfolio_scanner import (  # noqa: E402
    GitHubAPIClient,
    PortfolioScanner,
)

logger = logging.getLogger(__name__)

# ── SSRF protection ───────────────────────────────────────────────────────────

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("100.64.0.0/10"),   # CGNAT
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _is_safe_url(url: str) -> tuple[bool, str]:
    """Return (is_safe, reason_if_not_safe)."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL format."

    if parsed.scheme not in ("http", "https"):
        return False, "Only http and https URLs are supported."

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return False, "Could not parse hostname from URL."

    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False, "Local hostnames are not allowed."

    try:
        ip_str = socket.gethostbyname(hostname)
        addr = ipaddress.ip_address(ip_str)
        for net in _PRIVATE_NETWORKS:
            if addr in net:
                return False, f"Private/internal IP range is not allowed ({ip_str})."
    except (socket.gaierror, ValueError):
        pass  # Cannot resolve — will fail at fetch time with a clear error

    return True, ""


# ── HTML helpers ──────────────────────────────────────────────────────────────

_TITLE_RE = re.compile(r"<title[^>]*>([\s\S]{1,300}?)</title>", re.IGNORECASE)
_META_DESC_RE = re.compile(
    r'<meta\s+(?:[^>]*?\s)?name=["\']description["\']\s+(?:[^>]*?\s)?content=["\']([^"\']{0,500})["\']'
    r'|<meta\s+(?:[^>]*?\s)?content=["\']([^"\']{0,500})["\']\s+(?:[^>]*?\s)?name=["\']description["\']',
    re.IGNORECASE,
)
_STRIP_TAGS_RE = re.compile(r"<[^>]+>")


def _extract_title(html: str) -> str | None:
    m = _TITLE_RE.search(html)
    return m.group(1).strip() if m else None


def _extract_meta_description(html: str) -> str | None:
    m = _META_DESC_RE.search(html)
    text = (m.group(1) or m.group(2)) if m else None
    return text.strip() if text else None


def _strip_html(html: str, max_chars: int = 800) -> str:
    text = _STRIP_TAGS_RE.sub(" ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


# ── Skill keyword map ─────────────────────────────────────────────────────────

# (keyword_lower, skill_name, skill_category, evidence_type_hint)
_SKILL_KEYWORDS: list[tuple[str, str, str]] = [
    ("fastapi",          "FastAPI / REST API",          "Backend / API Engineering"),
    ("openapi",          "FastAPI / REST API",          "Backend / API Engineering"),
    ("swagger",          "FastAPI / REST API",          "Backend / API Engineering"),
    ("flask",            "Flask / REST API",            "Backend / API Engineering"),
    ("django",           "Django",                      "Backend / API Engineering"),
    ("rest api",         "Backend / API Engineering",   "Backend / API Engineering"),
    ("api",              "Backend / API Engineering",   "Backend / API Engineering"),
    ("machine learning", "Machine Learning Engineering","Machine Learning Engineering"),
    ("deep learning",    "Machine Learning Engineering","Machine Learning Engineering"),
    ("neural network",   "Machine Learning Engineering","Machine Learning Engineering"),
    ("prediction",       "Model Inference",             "Machine Learning Engineering"),
    ("inference",        "Model Serving",               "Machine Learning Engineering"),
    ("classifier",       "Classification Model",        "Machine Learning Engineering"),
    ("model",            "Machine Learning Engineering","Machine Learning Engineering"),
    ("docker",           "Docker / Containerization",   "MLOps"),
    ("kubernetes",       "Kubernetes",                  "DevOps / CI-CD"),
    ("cloud run",        "Cloud Run / GCP",             "Cloud Deployment"),
    ("deployment",       "Cloud Deployment",            "Cloud Deployment"),
    ("deployed",         "Cloud Deployment",            "Cloud Deployment"),
    ("react",            "React",                       "Full-Stack Development"),
    ("next.js",          "Next.js",                     "Full-Stack Development"),
    ("gradio",           "Gradio",                      "Full-Stack Development"),
    ("streamlit",        "Streamlit",                   "Full-Stack Development"),
    ("prometheus",       "Prometheus",                  "Monitoring / Observability"),
    ("monitoring",       "Monitoring / Observability",  "Monitoring / Observability"),
    ("analytics",        "Data Analytics",              "Data Engineering"),
    ("postgres",         "PostgreSQL",                  "Backend / API Engineering"),
    ("risk",             "Risk Analytics",              "Machine Learning Engineering"),
    ("accident",         "Safety Analytics",            "Machine Learning Engineering"),
    ("route",            "Route Optimization",          "Machine Learning Engineering"),
    ("forecast",         "Forecasting",                 "Machine Learning Engineering"),
    ("computer vision",  "Computer Vision",             "Computer Vision"),
    ("object detection", "Object Detection",            "Computer Vision"),
    ("nlp",              "NLP",                         "NLP / Language Processing"),
    ("certificate",      "Certificate Management",      "DevOps / CI-CD"),
    ("supabase",         "Supabase",                    "Backend / API Engineering"),
]


# ── Candidate ID ──────────────────────────────────────────────────────────────

def _cid(source_url: str, skill: str) -> str:
    return hashlib.sha256(f"{source_url}|{skill}".encode()).hexdigest()[:16]


# ── GitHub repo URL parser ─────────────────────────────────────────────────────

_GITHUB_REPO_RE = re.compile(
    r"(?:https?://)?github\.com/([a-zA-Z0-9_-]+)/([a-zA-Z0-9_.\-]+?)(?:\.git)?/?$"
)


def parse_github_repo_url(url: str) -> tuple[str, str] | None:
    """Extract (owner, repo) from a GitHub repo URL. Returns None if not parseable."""
    m = _GITHUB_REPO_RE.match(url.strip())
    return (m.group(1), m.group(2)) if m else None


# ── Repo evidence → WebsiteAnalysisCandidate conversion ──────────────────────

_DETECTION_TO_ACTION: dict[str, str] = {
    "Dockerfile instruction":   "Open Dockerfile",
    "CI/CD workflow step":      "Open CI/CD Config",
    "ML training call":         "Open Training Code",
    "ML model instantiation":   "Open Model Code",
    "ML prediction/inference":  "Open Inference Code",
    "ML evaluation metrics":    "Open Evaluation Code",
    "API endpoint decorator":   "Open API Code",
    "API handler function":     "Open API Handler",
    "Monitoring/metrics":       "Open Metrics Code",
    "Data preprocessing":       "Open Data Code",
    "React component logic":    "Open React Code",
    "RAG/LLM logic":            "Open LLM Code",
    "NLP processing":           "Open NLP Code",
}

_HIGH_CONFIDENCE_REASONS = frozenset([
    "ML training call", "ML prediction/inference", "ML model instantiation",
    "ML evaluation metrics", "API endpoint decorator", "Dockerfile instruction",
    "CI/CD workflow step", "RAG/LLM logic", "NLP processing",
])

_SKILL_TO_CATEGORY: dict[str, str] = {
    "Machine Learning": "Machine Learning Engineering",
    "Python":           "Machine Learning Engineering",
    "FastAPI":          "Backend / API Engineering",
    "Docker":           "MLOps",
    "CI/CD":            "DevOps / CI-CD",
    "React":            "Full-Stack Development",
    "TypeScript":       "Full-Stack Development",
    "JavaScript":       "Full-Stack Development",
    "GCP":              "Cloud Deployment",
    "AWS":              "Cloud Deployment",
    "Cloud Deployment": "Cloud Deployment",
    "MLOps":            "MLOps",
    "Computer Vision":  "Computer Vision",
    "NLP":              "NLP / Language Processing",
    "RAG / LLM":        "AI / LLM Engineering",
    "Data Engineering": "Data Engineering",
    "PostgreSQL":       "Backend / API Engineering",
    "SQL":              "Data Engineering",
    "Shell Scripting":  "DevOps / CI-CD",
    "Go":               "Backend / API Engineering",
    "Java":             "Backend / API Engineering",
}


def _skill_category(skill: str) -> str:
    return _SKILL_TO_CATEGORY.get(skill, "General")


def _evidence_candidate_to_website_candidate(c: Any) -> WebsiteAnalysisCandidate:
    """Convert a scanner EvidenceCandidate to a WebsiteAnalysisCandidate for the review screen."""
    confidence = "high" if c.detection_reason in _HIGH_CONFIDENCE_REASONS else "medium"
    status = "suggested" if confidence == "high" else "needs_review"
    action = _DETECTION_TO_ACTION.get(c.detection_reason, "Open GitHub Evidence")
    return WebsiteAnalysisCandidate(
        candidate_id=_cid(c.github_highlight_url, c.skill_name),
        skill_name=c.skill_name,
        skill_category=_skill_category(c.skill_name),
        confidence=confidence,
        evidence_title=f"{c.skill_name} — {c.project_title}",
        evidence_summary=c.evidence_description,
        source_url=c.github_highlight_url,
        route_path=f"{c.file_path} L{c.line_start}–L{c.line_end}",
        evidence_snippet=f"{c.file_path} ({c.detection_reason})",
        evidence_type="github_repo",
        action_label=action,
        suggested_status=status,
        evidence_source="github_repo",
    )


# ── Evidence merging (website + repo → combined review list) ─────────────────

def _merge_candidates(
    website: list[WebsiteAnalysisCandidate],
    repo: list[WebsiteAnalysisCandidate],
) -> list[WebsiteAnalysisCandidate]:
    """Merge website and repo candidates; create a combined record for shared skills."""
    web_by_skill: dict[str, WebsiteAnalysisCandidate] = {}
    for c in website:
        web_by_skill.setdefault(c.skill_name, c)

    repo_by_skill: dict[str, WebsiteAnalysisCandidate] = {}
    for c in repo:
        repo_by_skill.setdefault(c.skill_name, c)

    _conf_rank = {"high": 2, "medium": 1, "low": 0}

    merged: list[WebsiteAnalysisCandidate] = []
    seen: set[str] = set()

    for skill in sorted(set(web_by_skill) | set(repo_by_skill)):
        w = web_by_skill.get(skill)
        r = repo_by_skill.get(skill)

        if w and r:
            # Combined evidence — confidence is at least "medium", often "high"
            best = max(_conf_rank.get(w.confidence, 0), _conf_rank.get(r.confidence, 0))
            merged_conf: str = "high" if best >= 1 else "medium"
            merged.append(WebsiteAnalysisCandidate(
                candidate_id=_cid(w.source_url + r.source_url, skill),
                skill_name=skill,
                skill_category=w.skill_category or r.skill_category,
                confidence=merged_conf,
                evidence_title=f"{skill} — website + GitHub repo",
                evidence_summary=(
                    f"Website: {w.evidence_summary[:150]} | "
                    f"GitHub: {r.evidence_summary[:150]}"
                ),
                source_url=w.source_url,
                route_path=w.route_path,
                evidence_snippet=(
                    f"Website ({w.route_path}): {w.evidence_snippet[:100]} | "
                    f"GitHub ({r.route_path}): {r.evidence_snippet[:100]}"
                ),
                evidence_type="combined",
                action_label=w.action_label,
                suggested_status="suggested",
                evidence_source="combined",
                is_combined=True,
                related_source_url=r.source_url,
            ))
            seen.add(skill)
        elif w:
            merged.append(w)
            seen.add(skill)
        elif r:
            merged.append(r)
            seen.add(skill)

    # Sort: combined first (strongest), then by confidence, then suggested first
    _status_rank = {"suggested": 0, "needs_review": 1}
    _source_rank = {"combined": 0, "website": 1, "github_repo": 2}
    merged.sort(key=lambda c: (
        _source_rank.get(c.evidence_source, 9),
        _status_rank.get(c.suggested_status, 9),
        -_conf_rank.get(c.confidence, 0),
    ))
    return merged


# ── Route result ──────────────────────────────────────────────────────────────

class _RouteResult:
    def __init__(self, status: int, content_type: str, title: str | None, meta_desc: str | None, snippet: str, body: str):
        self.status = status
        self.content_type = content_type
        self.title = title
        self.meta_desc = meta_desc
        self.snippet = snippet
        self.body = body

    def is_json(self) -> bool:
        return "json" in self.content_type

    def is_html(self) -> bool:
        return "html" in self.content_type


# ── Main service ──────────────────────────────────────────────────────────────

class WebsiteAnalyzerService:
    FETCH_TIMEOUT = 8.0
    MAX_BODY_BYTES = 150_000
    ROUTES = ["/", "/docs", "/openapi.json", "/health", "/api"]

    _HEADERS = {
        "User-Agent": "VeriBridge-Portfolio-Analyzer/1.0 (public profile scan)",
        "Accept": "text/html,application/json,*/*;q=0.9",
    }

    def analyze(
        self,
        url: str,
        skill_focus: str | None = None,
        github_repo_url: str | None = None,
    ) -> WebsiteAnalyzeResponse:
        safe, reason = _is_safe_url(url)
        if not safe:
            return WebsiteAnalyzeResponse(
                base_url=url, candidates=[], checked_urls=[], warnings=[reason], candidate_count=0
            )

        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"

        checked_urls: list[str] = []
        warnings: list[str] = []
        route_results: dict[str, _RouteResult] = {}
        openapi_data: dict[str, Any] | None = None

        for route in self.ROUTES:
            full_url = (url if url.endswith("/") else url + "/") if route == "/" else base.rstrip("/") + route
            rr = self._fetch(full_url)
            if rr is None:
                continue
            checked_urls.append(full_url)
            route_results[route] = rr
            if route == "/openapi.json" and rr.is_json():
                try:
                    openapi_data = json.loads(rr.body)
                except Exception:
                    pass

        website_candidates = self._generate(base, url, route_results, openapi_data, skill_focus, warnings)

        # ── J4E: optional connected GitHub repo scan ─────────────────────────
        repo_candidates: list[WebsiteAnalysisCandidate] = []
        clean_repo_url = (github_repo_url or "").strip()
        if clean_repo_url:
            parsed_repo = parse_github_repo_url(clean_repo_url)
            if parsed_repo is None:
                warnings.append(
                    f"Could not parse GitHub repo URL '{clean_repo_url}'. "
                    "Expected format: https://github.com/owner/repo"
                )
            else:
                owner, repo_name = parsed_repo
                try:
                    from app.services.github_portfolio_scan_service import _ENV_GITHUB_TOKEN  # noqa: PLC0415
                    gh_client = GitHubAPIClient(token=_ENV_GITHUB_TOKEN)
                    scanner = PortfolioScanner(gh_client)
                    raw_evidence = scanner.scan_repo_by_url(owner, repo_name)
                    checked_urls.append(f"https://github.com/{owner}/{repo_name}")
                    # Deduplicate by (file_path, line_start, skill_name)
                    seen_repo: set[str] = set()
                    for ev in raw_evidence:
                        key = f"{ev.file_path}|{ev.line_start}|{ev.skill_name}"
                        if key not in seen_repo:
                            seen_repo.add(key)
                            repo_candidates.append(_evidence_candidate_to_website_candidate(ev))
                    if not raw_evidence:
                        warnings.append(
                            f"Connected repo '{owner}/{repo_name}' was scanned but no high-signal "
                            "evidence files were found. The repo may use a language or structure "
                            "the scanner does not yet recognise."
                        )
                except ValueError as exc:
                    warnings.append(f"Connected repo scan failed: {exc}")
                except Exception as exc:
                    logger.warning("Repo scan failed for %s/%s: %s", owner, repo_name, exc)
                    warnings.append(
                        f"Connected repo scan for '{owner}/{repo_name}' could not be completed. "
                        "Website evidence is shown below."
                    )

        # ── Merge website + repo candidates ──────────────────────────────────
        if repo_candidates:
            all_candidates = _merge_candidates(website_candidates, repo_candidates)
        else:
            all_candidates = website_candidates

        web_count = sum(1 for c in all_candidates if c.evidence_source == "website")
        repo_count = sum(1 for c in all_candidates if c.evidence_source == "github_repo")
        combined_count = sum(1 for c in all_candidates if c.evidence_source == "combined")

        return WebsiteAnalyzeResponse(
            base_url=url,
            candidates=all_candidates,
            checked_urls=checked_urls,
            warnings=warnings,
            candidate_count=len(all_candidates),
            website_candidate_count=web_count,
            repo_candidate_count=repo_count,
            combined_candidate_count=combined_count,
            github_repo_url=clean_repo_url or None,
        )

    # ── Fetch ──────────────────────────────────────────────────────────────────

    def _fetch(self, url: str) -> _RouteResult | None:
        try:
            with httpx.Client(timeout=self.FETCH_TIMEOUT, follow_redirects=True) as client:
                resp = client.get(url, headers=self._HEADERS)
                if resp.status_code not in (200, 201):
                    return None
                ct = resp.headers.get("content-type", "")
                body = resp.text[: self.MAX_BODY_BYTES]
                title = _extract_title(body) if "html" in ct else None
                meta = _extract_meta_description(body) if "html" in ct else None
                snippet = _strip_html(body, 800) if "html" in ct else body[:800]
                return _RouteResult(resp.status_code, ct, title, meta, snippet, body)
        except Exception:
            return None

    # ── Candidate generation ───────────────────────────────────────────────────

    def _generate(
        self,
        base: str,
        original_url: str,
        route_results: dict[str, _RouteResult],
        openapi_data: dict[str, Any] | None,
        skill_focus: str | None,
        warnings: list[str],
    ) -> list[WebsiteAnalysisCandidate]:
        candidates: list[WebsiteAnalysisCandidate] = []
        seen: set[str] = set()

        def add(
            skill: str,
            category: str,
            title: str,
            summary: str,
            source_url: str,
            route: str,
            snippet: str,
            confidence: str,
            ev_type: str,
            action: str,
            status: str = "suggested",
        ) -> None:
            if skill in seen:
                return
            seen.add(skill)
            candidates.append(WebsiteAnalysisCandidate(
                candidate_id=_cid(source_url, skill),
                skill_name=skill,
                skill_category=category,
                confidence=confidence,
                evidence_title=title,
                evidence_summary=summary,
                source_url=source_url,
                route_path=route,
                evidence_snippet=snippet[:400],
                evidence_type=ev_type,
                action_label=action,
                suggested_status=status,
            ))

        # 1. Base URL accessible → Live Deployment (always high confidence)
        if "/" in route_results:
            rr = route_results["/"]
            page_title = rr.title or "Live Application"
            meta_info = f" Description: {rr.meta_desc[:150]}." if rr.meta_desc else ""
            add(
                "AI Product Deployment",
                "Cloud Deployment",
                f"Live deployment: {page_title}",
                f"The application at {original_url} is publicly accessible. Title: {page_title}.{meta_info}",
                original_url if original_url.endswith("/") else original_url + "/",
                "/",
                rr.snippet,
                "high", "deployed_website", "Open Live Website",
            )
            # Scan homepage text for skill signals
            text_lower = rr.snippet.lower()
            for kw, skill, cat in _SKILL_KEYWORDS:
                if kw in text_lower:
                    add(
                        skill, cat,
                        f"{skill} — detected on homepage",
                        f"The homepage contains references to {skill}. Context: {rr.snippet[:200]}",
                        original_url if original_url.endswith("/") else original_url + "/",
                        "/", rr.snippet, "medium", "website_content", "Open Live Website", "needs_review",
                    )

        # 2. /docs → FastAPI API documentation (high confidence)
        if "/docs" in route_results:
            rr = route_results["/docs"]
            add(
                "FastAPI / REST API",
                "Backend / API Engineering",
                "FastAPI automatic API documentation",
                "This application provides auto-generated Swagger/OpenAPI documentation at /docs, "
                "indicating FastAPI or a compatible API framework.",
                base + "/docs",
                "/docs", rr.snippet, "high", "api_docs", "Open API Docs",
            )

        # 3. /openapi.json → parse spec (high confidence for FastAPI/REST API)
        if openapi_data and isinstance(openapi_data, dict):
            info = openapi_data.get("info", {})
            api_title = info.get("title", "API")
            api_desc = str(info.get("description", ""))
            paths = openapi_data.get("paths") or {}
            endpoint_paths = list(paths.keys())
            add(
                "Backend / API Engineering",
                "Backend / API Engineering",
                f"OpenAPI specification: {api_title}",
                f"Full OpenAPI spec found. API title: '{api_title}'. "
                f"{api_desc[:200]} "
                f"Endpoints: {', '.join(endpoint_paths[:6])}{'...' if len(endpoint_paths) > 6 else ''}",
                base + "/openapi.json",
                "/openapi.json",
                f"Title: {api_title} | Endpoints: {', '.join(endpoint_paths[:8])}",
                "high", "api_docs", "Open API Spec",
            )

            # Scan OpenAPI spec text for skill signals
            spec_text = json.dumps(openapi_data).lower()
            for kw, skill, cat in _SKILL_KEYWORDS:
                if kw in spec_text:
                    add(
                        skill, cat,
                        f"{skill} — detected in OpenAPI spec",
                        f"The OpenAPI specification for '{api_title}' contains references to {skill}. "
                        f"Endpoints: {', '.join(endpoint_paths[:5])}",
                        base + "/openapi.json",
                        "/openapi.json",
                        f"Endpoints: {', '.join(endpoint_paths[:8])}",
                        "medium", "api_endpoint", "Open API Spec", "needs_review",
                    )

        # 4. /health → observability evidence (medium confidence)
        if "/health" in route_results:
            rr = route_results["/health"]
            add(
                "Health Check / Observability",
                "Monitoring / Observability",
                "Health check endpoint (/health)",
                "A /health endpoint responds successfully, indicating production-ready deployment with monitoring support.",
                base + "/health",
                "/health", rr.snippet,
                "medium", "api_endpoint", "Open Health Check", "needs_review",
            )

        # 5. Skill focus: add candidates for explicitly mentioned skills if site is live
        if skill_focus and "/" in route_results:
            focus_terms = [f.strip().lower() for f in skill_focus.split(",") if f.strip()]
            rr = route_results["/"]
            for focus in focus_terms:
                for kw, skill, cat in _SKILL_KEYWORDS:
                    if focus in kw or kw in focus or focus in skill.lower():
                        add(
                            skill, cat,
                            f"{skill} — from skill focus",
                            f"Based on skill focus '{focus}' and the live application at {original_url}.",
                            original_url if original_url.endswith("/") else original_url + "/",
                            "/", rr.snippet,
                            "medium", "deployed_website", "Open Live Website", "needs_review",
                        )
                        break

        if not candidates:
            if not route_results:
                warnings.append("Could not reach the website. It may be offline, private, or behind authentication.")
            else:
                warnings.append("The website responded but no strong skill evidence was detected automatically.")

        # Sort: high-confidence suggested first
        _conf_order = {"high": 0, "medium": 1, "low": 2}
        _status_order = {"suggested": 0, "needs_review": 1}
        candidates.sort(key=lambda c: (_status_order.get(c.suggested_status, 9), _conf_order.get(c.confidence, 9)))
        return candidates
