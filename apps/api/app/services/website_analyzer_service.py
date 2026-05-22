"""Website AI Analyzer Service — Phase J4D.

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
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.schemas.website_analyzer import (
    WebsiteAnalysisCandidate,
    WebsiteAnalyzeResponse,
)

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

    def analyze(self, url: str, skill_focus: str | None = None) -> WebsiteAnalyzeResponse:
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
            if route == "/":
                full_url = url if url.endswith("/") else url + "/"
            else:
                full_url = base.rstrip("/") + route
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

        candidates = self._generate(base, url, route_results, openapi_data, skill_focus, warnings)
        return WebsiteAnalyzeResponse(
            base_url=url,
            candidates=candidates,
            checked_urls=checked_urls,
            warnings=warnings,
            candidate_count=len(candidates),
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
