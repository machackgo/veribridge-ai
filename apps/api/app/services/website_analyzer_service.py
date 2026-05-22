"""Website AI Analyzer Service — Phase J4D / J4E / J4F / J4G.

Fetches a public URL, inspects common API routes, parses OpenAPI specs,
extracts evidence candidates, runs safe functional verification, and groups
all evidence into high-level skill cards.

Security:
- SSRF protection: blocks private IP ranges and localhost.
- Timeout on every external fetch (8 seconds).
- Response size capped at 150 KB.
- Only http/https; no credentials accepted.
- Functional verification only calls safe inference/health endpoints (GET/POST).
- Skips auth, admin, payment, delete, mutating endpoints.
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
    FunctionalTestPlan,
    FunctionalVerificationCandidate,
    GroupedWebsiteSkill,
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
    web_by_skill: dict[str, WebsiteAnalysisCandidate] = {}
    for c in website:
        web_by_skill.setdefault(c.skill_name, c)

    repo_by_skill: dict[str, WebsiteAnalysisCandidate] = {}
    for c in repo:
        repo_by_skill.setdefault(c.skill_name, c)

    _conf_rank = {"high": 2, "medium": 1, "low": 0}
    merged: list[WebsiteAnalysisCandidate] = []

    for skill in sorted(set(web_by_skill) | set(repo_by_skill)):
        w = web_by_skill.get(skill)
        r = repo_by_skill.get(skill)

        if w and r:
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
        elif w:
            merged.append(w)
        elif r:
            merged.append(r)

    _status_rank = {"suggested": 0, "needs_review": 1}
    _source_rank = {"combined": 0, "website": 1, "github_repo": 2}
    merged.sort(key=lambda c: (
        _source_rank.get(c.evidence_source, 9),
        _status_rank.get(c.suggested_status, 9),
        -_conf_rank.get(c.confidence, 0),
    ))
    return merged


# ── J4F: Functional verification safety helpers ───────────────────────────────

# Fragments in path that make an endpoint unsafe to call
_UNSAFE_PATH_FRAGMENTS = frozenset([
    "admin", "auth", "login", "logout", "signup", "register",
    "password", "reset", "delete", "remove", "payment", "billing",
    "email", "send", "export", "import", "migrate", "webhook",
    "token", "secret", "credential", "refresh", "revoke",
    "user/create", "user/update", "user/delete", "account",
])

# Path fragments that indicate a safe inference/demo endpoint
_SAFE_INFERENCE_FRAGMENTS = frozenset([
    "predict", "classify", "recommend", "inference", "infer",
    "health", "status", "ping", "check", "example", "demo",
    "score", "analyze", "risk", "route", "forecast", "detect",
    "segment", "cluster", "rank", "crashes", "hotspot",
])


def _is_safe_endpoint(method: str, path: str) -> bool:
    """Return True if this endpoint is safe to call for functional verification."""
    m = method.upper()
    if m not in ("GET", "POST"):
        return False
    path_lower = path.lower()
    for frag in _UNSAFE_PATH_FRAGMENTS:
        if frag in path_lower:
            return False
    if m == "GET":
        return True  # All non-destructive GETs are safe
    # POST: must match at least one safe inference fragment
    return any(frag in path_lower for frag in _SAFE_INFERENCE_FRAGMENTS)


def _resolve_schema_ref(openapi_data: dict, schema: dict) -> dict:
    """Resolve a #/components/schemas/... $ref in place."""
    if "$ref" not in schema:
        return schema
    ref = schema.get("$ref", "")
    if ref.startswith("#/components/schemas/"):
        name = ref.split("/")[-1]
        return (openapi_data.get("components", {}).get("schemas", {}).get(name, schema))
    return schema


def _build_test_body(path: str, request_body: dict | None, openapi_data: dict | None) -> dict | None:
    """Build a minimal safe test body from an OpenAPI request body schema."""
    if request_body:
        content = request_body.get("content", {})
        json_schema = content.get("application/json", {}).get("schema", {})
        # Resolve $ref if present
        if openapi_data and "$ref" in json_schema:
            json_schema = _resolve_schema_ref(openapi_data, json_schema)

        if "example" in json_schema:
            return json_schema["example"]

        properties = json_schema.get("properties", {})
        if properties:
            body: dict[str, Any] = {}
            for name, prop in properties.items():
                prop_type = prop.get("type", "string")
                ex = prop.get("example")
                if ex is not None:
                    body[name] = ex
                    continue
                nl = name.lower()
                if prop_type in ("string", None):
                    if any(k in nl for k in ("origin", "start", "from", "source")):
                        body[name] = "Fenway Park, Boston, MA"
                    elif any(k in nl for k in ("dest", "end", "to", "target", "goal")):
                        body[name] = "Boston Logan International Airport, MA"
                    elif any(k in nl for k in ("time", "date", "timestamp", "departure", "_at", "when")):
                        body[name] = "2024-10-15T08:00:00Z"
                    elif any(k in nl for k in ("text", "input", "query", "message", "content", "prompt")):
                        body[name] = "sample input"
                    elif "url" in nl or "link" in nl:
                        body[name] = "https://example.com"
                    else:
                        body[name] = "test"
                elif prop_type in ("integer", "number"):
                    if any(k in nl for k in ("segment", "count", "num", "n_")):
                        body[name] = 5
                    elif any(k in nl for k in ("limit", "max", "top", "k")):
                        body[name] = 10
                    elif "page" in nl:
                        body[name] = 1
                    else:
                        body[name] = 1
                elif prop_type == "boolean":
                    body[name] = True
                elif prop_type == "array":
                    body[name] = []
                elif prop_type == "object":
                    body[name] = {}
            return body or None

    # Path-based heuristic fallback for common inference APIs
    path_lower = path.lower()
    if "segment" in path_lower and ("predict" in path_lower or "route" in path_lower):
        return {
            "origin": "Fenway Park, Boston, MA",
            "destination": "Boston Logan International Airport, MA",
            "num_segments": 5,
        }
    if "predict" in path_lower or "inference" in path_lower or "infer" in path_lower:
        return {
            "origin": "Fenway Park, Boston, MA",
            "destination": "Boston Logan International Airport, MA",
            "departure_time": "2024-10-15T08:00:00Z",
        }
    if "classify" in path_lower:
        return {"text": "sample text for classification"}
    if "recommend" in path_lower:
        return {"user_id": "test_user"}
    return None


def _extract_response_fields(data: Any, depth: int = 0) -> list[str]:
    """Recursively extract top-level field names from a JSON response."""
    if depth > 2:
        return []
    fields: list[str] = []
    if isinstance(data, dict):
        for k, v in data.items():
            fields.append(k)
            if isinstance(v, (dict, list)) and depth < 2:
                sub = _extract_response_fields(v, depth + 1)
                fields.extend(f"{k}.{s}" for s in sub[:2])
    elif isinstance(data, list) and data:
        fields.extend(_extract_response_fields(data[0], depth + 1))
    return fields[:20]


def _infer_skill_from_endpoint(path: str, response_fields: list[str]) -> str:
    path_lower = path.lower()
    fields_lower = [f.lower() for f in response_fields]
    if any(f in fields_lower for f in ["risk_class", "risk_score", "accident_risk", "crash_risk"]):
        return "Risk Analytics / Model Inference"
    if "predict" in path_lower or "inference" in path_lower or "infer" in path_lower:
        return "Model Inference"
    if "classify" in path_lower:
        return "Classification Model"
    if "recommend" in path_lower:
        return "Recommendation System"
    if "health" in path_lower or "status" in path_lower or "ping" in path_lower:
        return "Health Check / Observability"
    return "API Endpoint Verification"


def _infer_category_from_skill(skill: str) -> str:
    sl = skill.lower()
    if "inference" in sl or "model" in sl or "classif" in sl or "predict" in sl or "risk" in sl:
        return "Machine Learning Engineering"
    if "health" in sl or "observ" in sl:
        return "Monitoring / Observability"
    return "Backend / API Engineering"


# ── J4G: High-level skill grouping ───────────────────────────────────────────

_ATOMIC_TO_HIGH_LEVEL: dict[str, str] = {
    # Machine Learning Engineering
    "Machine Learning Engineering": "Machine Learning Engineering",
    "Model Inference": "Machine Learning Engineering",
    "Model Serving": "Machine Learning Engineering",
    "Classification Model": "Machine Learning Engineering",
    "Prediction Endpoint": "Machine Learning Engineering",
    "Deep Learning": "Machine Learning Engineering",
    "Computer Vision": "Machine Learning Engineering",
    "NLP": "Machine Learning Engineering",
    "Machine Learning": "Machine Learning Engineering",
    "Risk Analytics / Model Inference": "Machine Learning Engineering",
    # Backend / API Engineering
    "FastAPI / REST API": "Backend / API Engineering",
    "Backend / API Engineering": "Backend / API Engineering",
    "Flask / REST API": "Backend / API Engineering",
    "Django": "Backend / API Engineering",
    "PostgreSQL": "Backend / API Engineering",
    "Health Check / Observability": "Backend / API Engineering",
    "API Endpoint Verification": "Backend / API Engineering",
    # AI Product Deployment (live deployed product)
    "AI Product Deployment": "AI Product Deployment",
    # Cloud Deployment
    "Cloud Deployment": "Cloud Deployment",
    "Cloud Run / GCP": "Cloud Deployment",
    # MLOps
    "Docker / Containerization": "MLOps",
    "MLOps": "MLOps",
    "Kubernetes": "MLOps",
    # Domain AI — route risk, analytics, safety, geospatial
    "Risk Analytics": "Domain AI / Analytics",
    "Safety Analytics": "Domain AI / Analytics",
    "Route Optimization": "Domain AI / Analytics",
    "Forecasting": "Domain AI / Analytics",
    "Data Analytics": "Domain AI / Analytics",
    # Monitoring
    "Monitoring / Observability": "Monitoring / Observability",
    "Prometheus": "Monitoring / Observability",
    "Health Check": "Monitoring / Observability",
    # Full-Stack
    "React": "Full-Stack Development",
    "Next.js": "Full-Stack Development",
    "Gradio": "Full-Stack Development",
    "Streamlit": "Full-Stack Development",
}

_DOMAIN_AI_KEYWORDS = frozenset([
    "risk", "accident", "crash", "route", "safety", "hotspot",
    "geospatial", "routing", "navigation", "transport", "traffic",
    "alert", "emergency", "segment risk",
])

_GROUP_SYSTEM_GRAPHS: dict[str, dict[str, Any]] = {
    "Machine Learning Engineering": {
        "nodes": ["Input / Request", "Feature Engineering", "ML Model", "Prediction / Inference", "API Response"],
        "edges": [
            ("Input / Request", "Feature Engineering"),
            ("Feature Engineering", "ML Model"),
            ("ML Model", "Prediction / Inference"),
            ("Prediction / Inference", "API Response"),
        ],
    },
    "Backend / API Engineering": {
        "nodes": ["API Code (FastAPI)", "OpenAPI Specification", "REST Endpoints", "Request Validation", "Response"],
        "edges": [
            ("API Code (FastAPI)", "OpenAPI Specification"),
            ("OpenAPI Specification", "REST Endpoints"),
            ("REST Endpoints", "Request Validation"),
            ("Request Validation", "Response"),
        ],
    },
    "Cloud Deployment": {
        "nodes": ["Container", "Cloud Platform (GCP/AWS)", "Live URL", "Public Access"],
        "edges": [
            ("Container", "Cloud Platform (GCP/AWS)"),
            ("Cloud Platform (GCP/AWS)", "Live URL"),
            ("Live URL", "Public Access"),
        ],
    },
    "MLOps": {
        "nodes": ["Model Artifact", "Dockerfile", "Container Build", "Cloud Deploy", "Live Model Serving"],
        "edges": [
            ("Model Artifact", "Dockerfile"),
            ("Dockerfile", "Container Build"),
            ("Container Build", "Cloud Deploy"),
            ("Cloud Deploy", "Live Model Serving"),
        ],
    },
    "AI Product Deployment": {
        "nodes": ["Trained Model", "REST API", "Containerized Deploy", "Live Product", "Verified Workflow"],
        "edges": [
            ("Trained Model", "REST API"),
            ("REST API", "Containerized Deploy"),
            ("Containerized Deploy", "Live Product"),
            ("Live Product", "Verified Workflow"),
        ],
    },
    "Domain AI / Analytics": {
        "nodes": ["Route / Context Inputs", "Risk Analysis Engine", "Segment Analytics", "Prediction Output", "Actionable Result"],
        "edges": [
            ("Route / Context Inputs", "Risk Analysis Engine"),
            ("Risk Analysis Engine", "Segment Analytics"),
            ("Segment Analytics", "Prediction Output"),
            ("Prediction Output", "Actionable Result"),
        ],
    },
    "Full-Stack Development": {
        "nodes": ["Frontend (React/Next.js)", "API Client", "Backend API", "Data Layer", "User Interface"],
        "edges": [
            ("Frontend (React/Next.js)", "API Client"),
            ("API Client", "Backend API"),
            ("Backend API", "Data Layer"),
            ("Data Layer", "User Interface"),
        ],
    },
    "Monitoring / Observability": {
        "nodes": ["Application", "Metrics Exporter", "Prometheus", "Alerts / Dashboard"],
        "edges": [
            ("Application", "Metrics Exporter"),
            ("Metrics Exporter", "Prometheus"),
            ("Prometheus", "Alerts / Dashboard"),
        ],
    },
    "Data Engineering": {
        "nodes": ["Raw Data", "ETL Pipeline", "Feature Store", "Model Input", "Output"],
        "edges": [
            ("Raw Data", "ETL Pipeline"),
            ("ETL Pipeline", "Feature Store"),
            ("Feature Store", "Model Input"),
            ("Model Input", "Output"),
        ],
    },
    "DevOps / CI-CD": {
        "nodes": ["Code Push", "CI Pipeline", "Tests", "Container Build", "Deployment"],
        "edges": [
            ("Code Push", "CI Pipeline"),
            ("CI Pipeline", "Tests"),
            ("Tests", "Container Build"),
            ("Container Build", "Deployment"),
        ],
    },
}


def _classify_high_level_group(skill_name: str, skill_category: str) -> str:
    """Map an atomic skill name + category to a high-level group."""
    if skill_name in _ATOMIC_TO_HIGH_LEVEL:
        return _ATOMIC_TO_HIGH_LEVEL[skill_name]
    name_lower = skill_name.lower()
    if any(kw in name_lower for kw in _DOMAIN_AI_KEYWORDS):
        return "Domain AI / Analytics"
    category_map: dict[str, str] = {
        "Machine Learning Engineering": "Machine Learning Engineering",
        "Backend / API Engineering": "Backend / API Engineering",
        "Cloud Deployment": "Cloud Deployment",
        "MLOps": "MLOps",
        "Full-Stack Development": "Full-Stack Development",
        "Monitoring / Observability": "Monitoring / Observability",
        "Data Engineering": "Data Engineering",
        "DevOps / CI-CD": "DevOps / CI-CD",
        "Computer Vision": "Machine Learning Engineering",
        "NLP / Language Processing": "Machine Learning Engineering",
        "AI / LLM Engineering": "Machine Learning Engineering",
    }
    return category_map.get(skill_category, skill_category or "General")


def _parse_user_test_input(text: str) -> dict[str, Any] | None:
    """Parse a user-provided test input string into a dict.

    Accepts:
    - JSON:          {"origin": "Fenway Park, Boston, MA", "destination": "..."}
    - key=value:     origin=Fenway Park, Boston, MA; destination=Logan Airport; num_segments=5
    - newline-sep:   same as semicolon-separated, one pair per line
    """
    text = text.strip()
    if not text:
        return None
    # Try JSON first
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    # key=value or key: value pairs split on ; or newlines
    result: dict[str, Any] = {}
    delimiters = re.compile(r"[;\n]+")
    kv_sep = re.compile(r"[=:]")
    for raw in delimiters.split(text):
        raw = raw.strip()
        if not raw:
            continue
        m = kv_sep.search(raw)
        if not m:
            continue
        key = raw[: m.start()].strip()
        value = raw[m.end() :].strip()
        if not key:
            continue
        # Coerce simple types
        if value.lower() in ("true", "false"):
            result[key] = value.lower() == "true"
        elif re.fullmatch(r"-?\d+", value):
            result[key] = int(value)
        elif re.fullmatch(r"-?\d+\.\d+", value):
            result[key] = float(value)
        else:
            result[key] = value
    return result or None


def _build_request_body_summary(body: dict[str, Any] | None) -> str:
    """Build a compact human-readable summary of the test request body."""
    if not body:
        return ""
    parts: list[str] = []
    for k, v in list(body.items())[:7]:
        v_str = str(v)
        if len(v_str) > 55:
            v_str = v_str[:55] + "…"
        parts.append(f"{k}={v_str}")
    summary = "; ".join(parts)
    if len(body) > 7:
        summary += f" (+{len(body) - 7} more)"
    return summary


def _post_process_groups(
    groups: list[GroupedWebsiteSkill],
    base_url: str,
    atomic: list[WebsiteAnalysisCandidate],
    functional: list[FunctionalVerificationCandidate],
) -> list[GroupedWebsiteSkill]:
    """Apply honesty corrections, partial-proof messages, and cloud-platform
    inference to groups that have incomplete pipeline evidence."""
    atomic_by_id: dict[str, WebsiteAnalysisCandidate] = {c.candidate_id: c for c in atomic}
    functional_by_id: dict[str, FunctionalVerificationCandidate] = {fc.candidate_id: fc for fc in functional}

    # Detect cloud platform from base URL domain
    hostname = (urlparse(base_url).hostname or "").lower()
    inferred_cloud: str | None = None
    if hostname.endswith(".run.app"):
        inferred_cloud = "Google Cloud Run"
    elif hostname.endswith(".azurewebsites.net"):
        inferred_cloud = "Azure App Service"
    elif hostname.endswith(".elasticbeanstalk.com"):
        inferred_cloud = "AWS Elastic Beanstalk"
    elif hostname.endswith(".herokuapp.com"):
        inferred_cloud = "Heroku"
    elif hostname.endswith(".onrender.com"):
        inferred_cloud = "Render"
    elif hostname.endswith(".railway.app"):
        inferred_cloud = "Railway"

    result: list[GroupedWebsiteSkill] = []
    for group in groups:
        group_atomic = [atomic_by_id[cid] for cid in group.candidate_ids if cid in atomic_by_id]
        group_functional = [functional_by_id[cid] for cid in group.candidate_ids if cid in functional_by_id]

        combined_text = " ".join(
            f"{c.skill_name} {c.route_path} {c.evidence_snippet}".lower()
            for c in group_atomic
        )

        def _has(*tokens: str) -> bool:
            return any(t in combined_text for t in tokens)

        has_dockerfile    = _has("dockerfile", "docker / containerization")
        has_cicd          = _has(".github/workflows", "ci/cd", "github actions", "workflow")
        has_cloud_config  = _has("cloud-run-service", "cloud_run", "cloudrun", "deploy.yaml", "cloud run", "terraform")
        has_func_passed   = any(fc.verified for fc in group_functional)
        has_live_url      = group.website_count > 0 or _has("live deployment", "deployed_website")

        partial_proof_message: str | None = None
        missing_proof_suggestions: list[str] = []
        is_partial = False
        inferred_platform: str | None = None
        override_confidence: str | None = None
        override_status: str | None = None

        if group.skill_name == "MLOps":
            found_parts: list[str] = []
            missing_parts: list[str] = []

            if has_dockerfile:
                found_parts.append("Dockerfile")
            if has_cicd:
                found_parts.append("CI/CD workflow")
            else:
                missing_parts.append("CI/CD workflow (GitHub Actions / Cloud Build)")
            if has_cloud_config:
                found_parts.append("cloud deployment config")
            else:
                missing_parts.append("cloud deployment config (cloud-run-service.yaml / Terraform)")
            if has_func_passed:
                found_parts.append("live model serving — verified")
            elif has_live_url:
                found_parts.append("live API deployment")

            missing_parts += [
                "Artifact Registry / Container Registry configuration",
                "deployment screenshots or architecture diagram",
            ]

            found_str = " + ".join(found_parts) if found_parts else "live deployment"
            is_partial = not (has_dockerfile and has_cicd and has_cloud_config)
            partial_proof_message = (
                f"Partial MLOps pipeline evidence detected: {found_str}. "
                "Add documentation, a deployment report, or screenshots to prove the full GCP deployment workflow."
            )
            missing_proof_suggestions = (
                [f"Missing: {m}" for m in missing_parts]
                + [
                    "Add architecture diagram or deployment report (PDF/slides) showing Cloud Run / Cloud Build workflow",
                    "Add deployment screenshots (Artifact Registry, Cloud Build logs, Cloud Run service dashboard)",
                    "📄 Documentation / Report / Slides proof — coming next in VeriBridge",
                ]
            )
            if is_partial and not has_cicd and not has_cloud_config:
                override_confidence = "medium"
                override_status = "needs_review"

        elif group.skill_name in ("Cloud Deployment", "AI Product Deployment"):
            if inferred_cloud:
                inferred_platform = inferred_cloud
                is_partial = not has_cloud_config
                partial_proof_message = (
                    f"Likely {inferred_cloud} deployment inferred from public URL domain "
                    f"({hostname}). The live URL confirms a cloud-hosted API, but supporting "
                    "documentation is needed for full deployment pipeline proof."
                )
                missing_proof_suggestions = [
                    f"Add a README, deployment report, or slides showing the {inferred_cloud} setup",
                    "Add Cloud Run service YAML or Terraform config to the GitHub repo",
                    "Add deployment screenshots (service dashboard, build logs, resource configuration)",
                    "Add an architecture diagram showing the full deployment pipeline",
                    "📄 Documentation / Report / Slides proof — coming next in VeriBridge",
                ]
                if is_partial and group.confidence == "high":
                    override_confidence = "medium"
            elif has_live_url and not has_cloud_config:
                is_partial = True
                partial_proof_message = (
                    "Live deployment URL detected. Add supporting documentation or configuration "
                    "files to prove the full cloud deployment pipeline."
                )
                missing_proof_suggestions = [
                    "Add cloud deployment config (cloud-run-service.yaml, Terraform, etc.) to the GitHub repo",
                    "Add deployment screenshots or architecture diagram",
                    "📄 Documentation / Report / Slides proof — coming next in VeriBridge",
                ]
                override_status = "needs_review"

        updates: dict[str, Any] = {
            "is_partial": is_partial,
            "partial_proof_message": partial_proof_message,
            "missing_proof_suggestions": missing_proof_suggestions,
            "inferred_cloud_platform": inferred_platform,
        }
        if override_confidence:
            updates["confidence"] = override_confidence
        if override_status:
            updates["suggested_status"] = override_status
        result.append(group.model_copy(update=updates))

    return result


def _group_candidates(
    atomic: list[WebsiteAnalysisCandidate],
    functional: list[FunctionalVerificationCandidate],
) -> list[GroupedWebsiteSkill]:
    """Group all candidates into high-level skill cards with system graphs."""
    _conf_to_int: dict[str, int] = {"high": 3, "medium": 2, "low": 1}

    groups: dict[str, dict[str, Any]] = {}

    def ensure_group(name: str) -> dict[str, Any]:
        if name not in groups:
            graph = _GROUP_SYSTEM_GRAPHS.get(name, {"nodes": [name], "edges": []})
            groups[name] = {
                "skill_name": name,
                "confidence_scores": [],
                "sources": set(),
                "subskills": [],
                "candidate_ids": [],
                "functional_candidate_ids": [],
                "website_count": 0,
                "repo_count": 0,
                "functional_count": 0,
                "combined_count": 0,
                "system_graph_nodes": graph["nodes"],
                "system_graph_edges": graph["edges"],
            }
        return groups[name]

    for c in atomic:
        gname = _classify_high_level_group(c.skill_name, c.skill_category)
        g = ensure_group(gname)
        g["candidate_ids"].append(c.candidate_id)
        if c.skill_name not in g["subskills"]:
            g["subskills"].append(c.skill_name)
        g["confidence_scores"].append(_conf_to_int.get(c.confidence, 1))
        src = c.evidence_source
        g["sources"].add(src)
        if src == "website":
            g["website_count"] += 1
        elif src == "github_repo":
            g["repo_count"] += 1
        elif src == "combined":
            g["combined_count"] += 1

    for fc in functional:
        gname = _classify_high_level_group(fc.skill_name, fc.skill_category)
        g = ensure_group(gname)
        g["candidate_ids"].append(fc.candidate_id)
        g["functional_candidate_ids"].append(fc.candidate_id)
        g["sources"].add("functional")
        g["functional_count"] += 1
        g["confidence_scores"].append(_conf_to_int.get(fc.confidence, 1))
        if fc.skill_name not in g["subskills"]:
            g["subskills"].append(fc.skill_name)

    result: list[GroupedWebsiteSkill] = []
    for name, g in groups.items():
        scores = g["confidence_scores"]
        avg = sum(scores) / len(scores) if scores else 1
        confidence: str = "high" if avg >= 2.5 else "medium" if avg >= 1.5 else "low"

        ordered_sources: list[str] = []
        for src in ("combined", "functional", "website", "github_repo"):
            if src in g["sources"]:
                ordered_sources.append(src)

        has_high = any(s >= 3 for s in scores)
        suggested_status: str = "suggested" if (has_high and len(g["candidate_ids"]) >= 1) else "needs_review"

        evidence_count = (
            g["website_count"] + g["repo_count"]
            + g["functional_count"] + g["combined_count"]
        )

        result.append(GroupedWebsiteSkill(
            group_id=hashlib.sha256(name.encode()).hexdigest()[:12],
            skill_name=g["skill_name"],
            category=g["skill_name"],
            confidence=confidence,
            sources=ordered_sources,
            subskills=g["subskills"][:8],
            evidence_count=evidence_count,
            website_count=g["website_count"],
            repo_count=g["repo_count"],
            functional_count=g["functional_count"],
            combined_count=g["combined_count"],
            candidate_ids=g["candidate_ids"],
            functional_candidate_ids=g["functional_candidate_ids"],
            system_graph_nodes=g["system_graph_nodes"],
            system_graph_edges=g["system_graph_edges"],
            suggested_status=suggested_status,
        ))

    # Sort: most evidence first, then by source strength
    _src_priority: dict[str, int] = {"combined": 0, "functional": 1, "website": 2, "github_repo": 3}
    result.sort(key=lambda g: (
        -g.evidence_count,
        min((_src_priority.get(s, 9) for s in g.sources), default=9),
    ))
    return result


# ── Route result ──────────────────────────────────────────────────────────────

class _RouteResult:
    def __init__(
        self,
        status: int,
        content_type: str,
        title: str | None,
        meta_desc: str | None,
        snippet: str,
        body: str,
    ):
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
    VERIFY_TIMEOUT = 8.0
    MAX_BODY_BYTES = 150_000
    MAX_ENDPOINTS_TO_TEST = 3
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
        run_safe_tests: bool = True,
        functional_test_plan: FunctionalTestPlan | None = None,
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
            full_url = (
                (url if url.endswith("/") else url + "/")
                if route == "/"
                else base.rstrip("/") + route
            )
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
                    seen_repo: set[str] = set()
                    for ev in raw_evidence:
                        key = f"{ev.file_path}|{ev.line_start}|{ev.skill_name}"
                        if key not in seen_repo:
                            seen_repo.add(key)
                            repo_candidates.append(_evidence_candidate_to_website_candidate(ev))
                    if not raw_evidence:
                        warnings.append(
                            f"Connected repo '{owner}/{repo_name}' was scanned but no high-signal "
                            "evidence files were found."
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

        # ── J4F: Functional verification ─────────────────────────────────────
        functional_candidates: list[FunctionalVerificationCandidate] = []
        test_mode = (functional_test_plan.test_mode if functional_test_plan else "auto")

        if test_mode == "browser_ui":
            warnings.append(
                "Browser UI workflow verification is not yet implemented. "
                "API endpoint evidence is shown below. "
                "Full browser UI testing coming soon."
            )
        elif test_mode == "plan_only":
            warnings.append(
                "Test mode is set to 'Save test plan only'. No live endpoint tests were run. "
                "Your test plan details have been recorded."
            )
        elif run_safe_tests:
            if openapi_data:
                try:
                    functional_candidates = self._run_functional_verification(
                        base, openapi_data, warnings, functional_test_plan
                    )
                except Exception as exc:
                    logger.warning("Functional verification error: %s", exc)
                    warnings.append(
                        "Functional verification could not be completed. "
                        "Website evidence is still available from public metadata and spec."
                    )
            else:
                warnings.append(
                    "Functional verification unavailable — no OpenAPI spec found at /openapi.json. "
                    "Browser UI workflow verification coming soon."
                )

        # ── J4G: Group into high-level skill cards ────────────────────────────
        grouped_skills = _group_candidates(all_candidates, functional_candidates)
        grouped_skills = _post_process_groups(grouped_skills, base, all_candidates, functional_candidates)

        return WebsiteAnalyzeResponse(
            base_url=url,
            candidates=all_candidates,
            functional_candidates=functional_candidates,
            grouped_skills=grouped_skills,
            checked_urls=checked_urls,
            warnings=warnings,
            candidate_count=len(all_candidates),
            website_candidate_count=web_count,
            repo_candidate_count=repo_count,
            combined_candidate_count=combined_count,
            functional_candidate_count=len(functional_candidates),
            functional_verification_available=bool(functional_candidates),
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

        _conf_order = {"high": 0, "medium": 1, "low": 2}
        _status_order = {"suggested": 0, "needs_review": 1}
        candidates.sort(key=lambda c: (_status_order.get(c.suggested_status, 9), _conf_order.get(c.confidence, 9)))
        return candidates

    # ── J4F: Functional verification ──────────────────────────────────────────

    def _run_functional_verification(
        self,
        base: str,
        openapi_data: dict[str, Any],
        warnings: list[str],
        test_plan: FunctionalTestPlan | None = None,
    ) -> list[FunctionalVerificationCandidate]:
        """Parse OpenAPI spec, find safe endpoints, and run live tests.

        If `test_plan.test_input` is provided and the method is POST, the
        user-supplied values are used as the request body (user-guided test).
        Otherwise the body is auto-generated from the OpenAPI schema.
        """
        paths = openapi_data.get("paths") or {}
        candidates: list[FunctionalVerificationCandidate] = []
        tested = 0

        # Parse user-provided input once (used for all POST endpoints if supplied)
        user_body: dict[str, Any] | None = None
        if test_plan and test_plan.test_input:
            user_body = _parse_user_test_input(test_plan.test_input)

        # Prioritize POST predict/inference, then GET health, then others
        path_items = list(paths.items())
        path_items.sort(key=lambda p: (
            0 if any(f in p[0].lower() for f in ("predict", "inference", "infer", "classify")) else
            1 if any(f in p[0].lower() for f in ("health", "status", "ping")) else 2
        ))

        for path, path_item in path_items:
            if tested >= self.MAX_ENDPOINTS_TO_TEST:
                break
            if not isinstance(path_item, dict):
                continue

            for method, operation in path_item.items():
                if tested >= self.MAX_ENDPOINTS_TO_TEST:
                    break
                if method.upper() not in ("GET", "POST"):
                    continue
                if not _is_safe_endpoint(method, path):
                    continue
                if not isinstance(operation, dict):
                    continue

                endpoint_url = base.rstrip("/") + path

                # ── Build test body + track source ─────────────────────────
                test_body: dict[str, Any] | None = None
                test_input_source = "auto_generated"
                is_user_guided = False

                if method.upper() == "POST":
                    if user_body:
                        test_body = user_body
                        test_input_source = "user_provided"
                        is_user_guided = True
                    else:
                        request_body = operation.get("requestBody", {})
                        test_body = _build_test_body(path, request_body, openapi_data)
                        if test_body is None:
                            continue  # Can't POST without a body

                body_summary = _build_request_body_summary(test_body)
                verification_label = "User-guided API test" if is_user_guided else "Auto-detected API test"

                result = self._call_endpoint_safely(endpoint_url, method, test_body)
                tested += 1

                skill = _infer_skill_from_endpoint(path, result["response_fields"])
                category = _infer_category_from_skill(skill)
                status_code: int | None = result["status_code"]
                response_fields: list[str] = result["response_fields"]
                verified = status_code == 200 and bool(response_fields)

                # ── Build evidence text ────────────────────────────────────
                if verified:
                    confidence = "high"
                    suggested_status = "suggested"
                    verification_message = (
                        f"VeriBridge sent a safe {method.upper()} request to {path} and "
                        f"verified the live API returned expected output. "
                        f"Response fields: {', '.join(response_fields[:6])}. "
                        f"This verifies: API endpoint responded with expected output. "
                        "Browser UI workflow was not tested."
                    )
                    evidence_title = f"{verification_label}: {method.upper()} {path} — API endpoint verified"
                elif status_code is not None:
                    confidence = "medium"
                    suggested_status = "needs_review"
                    if status_code == 422:
                        verification_message = (
                            f"Endpoint {path} returned HTTP 422 (validation error). "
                            "The endpoint exists but the test input may need adjustment. "
                            "Endpoint evidence is detected from the OpenAPI spec."
                        )
                    elif status_code >= 500:
                        verification_message = (
                            f"Endpoint {path} returned HTTP {status_code}. "
                            "The API may require external dependencies (API keys, services). "
                            "Endpoint evidence is detected from the OpenAPI spec."
                        )
                    else:
                        verification_message = (
                            f"Endpoint {path} responded with HTTP {status_code}. "
                            "Endpoint is accessible but response was not verified. "
                            "Browser UI workflow was not tested."
                        )
                    evidence_title = f"{verification_label}: {method.upper()} {path} — HTTP {status_code}"
                else:
                    confidence = "low"
                    suggested_status = "needs_review"
                    verification_message = (
                        f"Could not reach {path} (timeout or network error). "
                        "Endpoint evidence is still detected from the OpenAPI spec. "
                        "Browser UI workflow was not tested."
                    )
                    evidence_title = f"{verification_label}: {method.upper()} {path} — verification unavailable"

                cid = _cid(endpoint_url + method.upper(), skill)
                candidates.append(FunctionalVerificationCandidate(
                    candidate_id=cid,
                    skill_name=skill,
                    skill_category=category,
                    confidence=confidence,
                    evidence_title=evidence_title,
                    evidence_summary=verification_message,
                    endpoint_url=endpoint_url,
                    method=method.upper(),
                    request_summary=f"{method.upper()} {path}" + (f" ({len(test_body)} fields)" if test_body else ""),
                    response_fields_found=response_fields,
                    status_code=status_code,
                    verified=verified,
                    verification_message=verification_message,
                    action_label=f"Open {path}",
                    suggested_status=suggested_status,
                    # Transparency fields
                    test_input_source=test_input_source,
                    is_user_guided=is_user_guided,
                    verification_label=verification_label,
                    request_body_summary=body_summary,
                    what_to_test=test_plan.what_to_test if test_plan else None,
                    expected_output_description=test_plan.expected_output if test_plan else None,
                ))

        if tested == 0 and paths:
            warnings.append(
                "No safe testable endpoints found in the OpenAPI spec. "
                "Functional verification skipped. Website evidence still detected."
            )

        return candidates

    def _call_endpoint_safely(
        self,
        url: str,
        method: str,
        body: dict | None,
    ) -> dict[str, Any]:
        """Call an endpoint with SSRF protection and strict timeout."""
        result: dict[str, Any] = {"status_code": None, "response_fields": [], "error": None}
        safe, reason = _is_safe_url(url)
        if not safe:
            result["error"] = reason
            return result
        try:
            headers = {**self._HEADERS, "Accept": "application/json"}
            if method.upper() == "POST":
                headers["Content-Type"] = "application/json"
            with httpx.Client(timeout=self.VERIFY_TIMEOUT, follow_redirects=True) as client:
                if method.upper() == "POST":
                    resp = client.post(url, json=body, headers=headers)
                else:
                    resp = client.get(url, headers=headers)
                result["status_code"] = resp.status_code
                if resp.status_code == 200:
                    ct = resp.headers.get("content-type", "")
                    if "json" in ct:
                        try:
                            data = resp.json()
                            result["response_fields"] = _extract_response_fields(data)
                        except Exception:
                            pass
        except httpx.TimeoutException:
            result["error"] = "Request timed out"
        except Exception as exc:
            result["error"] = str(exc)
        return result
