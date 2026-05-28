"""Extension Proof Workflow Analysis Service.

Performs deep timeline-based analysis of a recorded browser workflow to
produce recruiter-readable evidence about what the student demonstrated,
which claimed skills are supported, and what is still missing.

Current analysis_type: 'timeline_only'
  — uses workflow events, URLs, page titles, and recording metadata.
  — does NOT perform video frame extraction or screenshot analysis (yet).
  — the output schema is designed so video/multimodal analysis can be
    dropped in later without changing the API surface.

Target-site filtering (v2):
  — only events on the proof target domain are analysed for skill evidence.
  — VeriBridge internal dashboard pages, Supabase, and unrelated browser
    tabs are classified as "noise" and excluded from recruiter-facing output.
  — GitHub pages are classified as "supporting evidence" and noted separately.
  — raw noise counts are stored internally for debugging; never surfaced to
    recruiters.

Guardrails:
  — never claims skills are "verified" or "guaranteed"
  — uses "evidence supports", "AI Reviewed", "workflow analysis"
  — human_review_needed is set conservatively
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

logger = logging.getLogger(__name__)

_TABLE = "workflow_analysis_results"
_SESSION_TABLE = "extension_proof_sessions"

ANALYZER_VERSION = "workflow-analysis-v2"

# Status values from which workflow analysis is allowed.
_VALID_ANALYZE_FROM = frozenset({"uploaded_pending_analysis", "analyzing"})


# ── Tech detection maps ───────────────────────────────────────────────────────

_DOMAIN_TECH: dict[str, list[str]] = {
    "vercel.app":        ["Next.js", "React", "Vercel"],
    "netlify.app":       ["React", "Netlify"],
    "railway.app":       ["Railway"],
    "render.com":        ["Render"],
    "fly.dev":           ["Fly.io"],
    "herokuapp.com":     ["Heroku"],
    "streamlit.app":     ["Streamlit", "Python"],
    "huggingface.co":    ["HuggingFace", "Machine Learning", "Python"],
    "github.com":        ["GitHub", "Git"],
    "github.io":         ["GitHub Pages"],
    "supabase.io":       ["Supabase", "PostgreSQL"],
    "supabase.co":       ["Supabase", "PostgreSQL"],
    "firebase.google.com": ["Firebase"],
    "replit.com":        ["Replit"],
}

_PORT_TECH: dict[str, list[str]] = {
    "3000": ["React", "Node.js", "Next.js"],
    "3001": ["React", "Node.js"],
    "4000": ["Node.js", "Express"],
    "4200": ["Angular"],
    "5000": ["Flask", "Python"],
    "5001": ["Flask", "Python"],
    "5173": ["Vite", "React"],
    "8000": ["FastAPI", "Django", "Python"],
    "8001": ["FastAPI", "Django", "Python"],
    "8080": ["Spring Boot", "Java", "Go"],
    "8501": ["Streamlit", "Python"],
    "8888": ["Jupyter Notebook", "Python"],
    "9000": ["Node.js"],
}

_TITLE_TECH: dict[str, str] = {
    "fastapi":       "FastAPI",
    "swagger":       "FastAPI",
    "openapi":       "API",
    "django":        "Django",
    "flask":         "Flask",
    "react":         "React",
    "next.js":       "Next.js",
    "angular":       "Angular",
    "vue":           "Vue",
    "streamlit":     "Streamlit",
    "jupyter":       "Jupyter Notebook",
    "grafana":       "Grafana",
    "postgres":      "PostgreSQL",
    "pgadmin":       "PostgreSQL",
    "mongodb":       "MongoDB",
    "redis":         "Redis",
    "graphql":       "GraphQL",
    "storybook":     "Storybook",
    "prisma":        "Prisma",
    "supabase":      "Supabase",
}

_SKILL_ALIASES: dict[str, str] = {
    "react.js": "React",
    "reactjs": "React",
    "react js": "React",
    "next.js": "Next.js",
    "nextjs": "Next.js",
    "node.js": "Node.js",
    "nodejs": "Node.js",
    "fastapi": "FastAPI",
    "fast api": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "python": "Python",
    "typescript": "TypeScript",
    "javascript": "JavaScript",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "mongodb": "MongoDB",
    "mongo": "MongoDB",
    "angular": "Angular",
    "vue.js": "Vue",
    "vuejs": "Vue",
    "streamlit": "Streamlit",
    "jupyter": "Jupyter Notebook",
    "machine learning": "Machine Learning",
    "ml": "Machine Learning",
    "deep learning": "Deep Learning",
    "tensorflow": "TensorFlow",
    "pytorch": "PyTorch",
    "scikit-learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "github": "GitHub",
    "git": "Git",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "graphql": "GraphQL",
    "supabase": "Supabase",
    "firebase": "Firebase",
    "redis": "Redis",
    "celery": "Celery",
    "langchain": "LangChain",
    "huggingface": "HuggingFace",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "sqlalchemy": "SQLAlchemy",
    "mlops": "MLOps",
    "google cloud": "Google Cloud",
    "cloud run": "Google Cloud",
    "gcp": "Google Cloud",
    "aws": "AWS",
    "azure": "Azure",
    "google maps": "Google Maps API",
}

_REQUIRES_CODE_EVIDENCE: frozenset[str] = frozenset({
    "fastapi", "django", "flask", "starlette", "aiohttp", "tornado",
    "sqlalchemy", "alembic", "prisma", "drizzle",
    "docker", "docker compose", "kubernetes",
    "pytorch", "tensorflow", "keras", "scikit-learn", "sklearn",
    "xgboost", "lightgbm", "machine learning", "ml", "deep learning", "mlops",
    "celery", "redis", "mongodb", "postgresql", "postgres",
    "langchain", "llamaindex", "huggingface", "openai", "anthropic",
    "google cloud", "cloud run", "gcp", "aws", "azure",
    "python",
    "sqlalchemy", "alembic",
    "fastai", "ray", "dask", "airflow", "prefect",
    "github actions", "ci/cd",
})


# ── URL filtering: noise patterns ─────────────────────────────────────────────

# Exact netlocs that are always noise (no matter what path)
_NOISE_NETLOCS: frozenset[str] = frozenset({
    "app.supabase.io",
    "studio.supabase.com",
    "supabase.com",
    "api.supabase.io",
})

# Netloc suffixes → always noise
_NOISE_NETLOC_SUFFIXES: tuple[str, ...] = (
    ".supabase.io",
    ".supabase.co",
)

# Netloc + path prefix combos that are VeriBridge internal routes
# (VeriBridge app runs on localhost:3000 in development)
_VERIBRIDGE_LOCALHOST_NETLOCS: frozenset[str] = frozenset({
    "localhost:3000",
    "127.0.0.1:3000",
})

# Path prefixes that mark a URL as a VeriBridge internal dashboard page
_VERIBRIDGE_INTERNAL_PATH_PREFIXES: tuple[str, ...] = (
    "/dashboard/",
    "/dashboard",
)


def _safe_netloc(url: str) -> str:
    """Extract netloc (host:port) from a URL, lowercased. Returns '' on failure."""
    if not url:
        return ""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _is_veribridge_internal(url: str) -> bool:
    """Return True if this URL is a VeriBridge internal dashboard page."""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        path = parsed.path.lower()
        if netloc in _VERIBRIDGE_LOCALHOST_NETLOCS:
            for prefix in _VERIBRIDGE_INTERNAL_PATH_PREFIXES:
                if path.startswith(prefix) or path == prefix.rstrip("/"):
                    return True
    except Exception:
        pass
    return False


def _classify_url(
    url: str,
    target_netloc: str,
    github_netloc: str | None,
) -> str:
    """Classify a URL into 'target', 'supporting', or 'noise'.

    target:     URL is on the same domain/netloc as the proof target site.
    supporting: URL is on GitHub and a github_url was provided.
    noise:      Everything else — VeriBridge internal, Supabase, unrelated tabs.
    """
    if not url:
        return "noise"
    if _is_chrome_internal(url):
        return "noise"

    # VeriBridge internal dashboard routes → always noise
    if _is_veribridge_internal(url):
        return "noise"

    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()

        # Known noise netlocs
        if netloc in _NOISE_NETLOCS:
            return "noise"
        for suffix in _NOISE_NETLOC_SUFFIXES:
            if netloc.endswith(suffix):
                return "noise"

        # Target site match (exact netloc)
        if target_netloc and netloc == target_netloc:
            return "target"

        # GitHub supporting evidence (only when github_url is configured)
        if github_netloc:
            if netloc in ("github.com", "raw.githubusercontent.com", "gist.github.com"):
                return "supporting"
            if netloc == github_netloc:
                return "supporting"

        # Everything else: unrelated tab → noise
        return "noise"

    except Exception:
        return "noise"


class ExtensionProofWorkflowAnalysisService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def run_analysis(
        self,
        user_id: str,
        session_id: str,
        claimed_skills: list[str],
        proof_objective: str,
        original_url: str,
        url_type: str,
        github_url: str | None,
    ) -> dict[str, Any]:
        """Run workflow analysis and persist the result.

        Computes the analysis in-memory first, then persists best-effort.
        Always returns a result dict — never raises due to DB failures.
        A '_db_saved' key indicates whether the result was persisted.
        """
        logger.info("WORKFLOW_ANALYSIS_START session=%s user=%s", session_id, user_id)

        session = self._get_session(user_id, session_id)
        current_status = session.get("status", "")

        if current_status not in _VALID_ANALYZE_FROM:
            raise InvalidAnalysisStateError(
                f"Cannot analyze a session with status '{current_status}'. "
                f"Allowed from: {sorted(_VALID_ANALYZE_FROM)}."
            )

        if current_status == "uploaded_pending_analysis":
            try:
                self._update_session_status(user_id, session_id, "analyzing")
            except Exception:
                logger.warning(
                    "WORKFLOW_ANALYSIS_STATUS_ANALYZING_FAILED session=%s",
                    session_id, exc_info=True,
                )

        logger.info("WORKFLOW_ANALYSIS_LOADING_METADATA session=%s", session_id)
        proof_data: dict[str, Any] = session.get("proof_data") or {}

        event_count = len(proof_data.get("workflow_events") or [])
        logger.info(
            "WORKFLOW_ANALYSIS_READING_TIMELINE session=%s events=%d",
            session_id, event_count,
        )
        logger.info(
            "WORKFLOW_ANALYSIS_MATCHING_OBJECTIVE session=%s objective=%r",
            session_id, (proof_objective or "")[:80],
        )
        logger.info(
            "WORKFLOW_ANALYSIS_MATCHING_SKILLS session=%s skills=%s",
            session_id, claimed_skills,
        )
        logger.info("WORKFLOW_ANALYSIS_GENERATING_SUMMARY session=%s", session_id)

        result = _analyze_workflow(
            proof_data=proof_data,
            claimed_skills=claimed_skills,
            proof_objective=proof_objective,
            original_url=original_url,
            url_type=url_type,
            github_url=github_url,
        )

        logger.info("WORKFLOW_ANALYSIS_DB_INSERT_START session=%s", session_id)
        db_saved = False
        row: dict[str, Any]
        try:
            row = self._upsert_result(user_id, session_id, result)
            db_saved = True
            logger.info("WORKFLOW_ANALYSIS_DB_INSERT_SUCCESS session=%s", session_id)
        except Exception:
            logger.warning(
                "WORKFLOW_ANALYSIS_DB_INSERT_FAILED session=%s — degrading to in-memory result",
                session_id, exc_info=True,
            )
            now = _now()
            row = {
                "id": f"mem-{session_id[:8]}",
                "user_id": user_id,
                "proof_session_id": session_id,
                "analyzer_version": ANALYZER_VERSION,
                "created_at": now,
                "updated_at": now,
                **result,
            }

        try:
            self._update_session_status(user_id, session_id, "completed")
        except Exception:
            logger.warning(
                "WORKFLOW_ANALYSIS_STATUS_COMPLETED_FAILED session=%s",
                session_id, exc_info=True,
            )

        row["_db_saved"] = db_saved
        logger.info(
            "WORKFLOW_ANALYSIS_COMPLETE session=%s score=%d confidence=%s db_saved=%s",
            session_id,
            result.get("evidence_strength_score", 0),
            result.get("workflow_confidence", ""),
            db_saved,
        )
        return row

    def get_latest(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            store = self._client.get(_TABLE, {})
            for row in store.values():
                if (
                    str(row.get("proof_session_id")) == session_id
                    and str(row.get("user_id")) == user_id
                ):
                    return row
            return None

        try:
            result = (
                self._client.table(_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .eq("proof_session_id", session_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = getattr(result, "data", []) or []
            return rows[0] if rows else None
        except Exception:
            logger.warning(
                "WORKFLOW_ANALYSIS_GET_LATEST_FAILED session=%s — table may not exist yet",
                session_id, exc_info=True,
            )
            return None

    def _get_session(self, user_id: str, session_id: str) -> dict[str, Any]:
        if isinstance(self._client, dict):
            row = self._client.get(_SESSION_TABLE, {}).get(session_id)
            if not row or str(row.get("user_id")) != user_id:
                raise SessionNotFoundError(session_id)
            return row

        result = (
            self._client.table(_SESSION_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", session_id)
            .maybe_single()
            .execute()
        )
        if result is None or result.data is None:
            raise SessionNotFoundError(session_id)
        return result.data

    def _update_session_status(
        self, user_id: str, session_id: str, new_status: str
    ) -> None:
        if isinstance(self._client, dict):
            store = self._client.setdefault(_SESSION_TABLE, {})
            if session_id in store:
                store[session_id]["status"] = new_status
            return

        self._client.table(_SESSION_TABLE).update(
            {"status": new_status, "updated_at": _now()}
        ).eq("user_id", user_id).eq("id", session_id).execute()

    def _upsert_result(
        self,
        user_id: str,
        session_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        now = _now()
        data: dict[str, Any] = {
            "user_id": user_id,
            "proof_session_id": session_id,
            "analyzer_version": ANALYZER_VERSION,
            "updated_at": now,
            **result,
        }

        if isinstance(self._client, dict):
            store = self._client.setdefault(_TABLE, {})
            existing = next(
                (r for r in store.values() if str(r.get("proof_session_id")) == session_id),
                None,
            )
            if existing:
                updated = {**existing, **data}
                store[existing["id"]] = updated
                return updated
            row = {"id": str(uuid4()), "created_at": now, **data}
            store[row["id"]] = row
            return row

        existing = self.get_latest(user_id, session_id)
        if existing:
            res = (
                self._client.table(_TABLE)
                .update(data)
                .eq("proof_session_id", session_id)
                .eq("user_id", user_id)
                .execute()
            )
            rows = getattr(res, "data", []) or []
            return rows[0] if rows else {**existing, **data}

        insert_data = {"created_at": now, **data}
        res = self._client.table(_TABLE).insert(insert_data).execute()
        rows = getattr(res, "data", []) or []
        if rows:
            return rows[0]
        return insert_data


# ── Stage helpers ─────────────────────────────────────────────────────────────

def _build_completed_stages(db_saved: bool = True) -> list[dict[str, Any]]:
    return [
        {"key": "loading_metadata",   "label": "Loading session metadata",   "status": "complete"},
        {"key": "reading_timeline",   "label": "Reading workflow timeline",   "status": "complete"},
        {"key": "matching_objective", "label": "Matching proof objective",    "status": "complete"},
        {"key": "matching_skills",    "label": "Matching claimed skills",     "status": "complete"},
        {"key": "generating_summary", "label": "Generating evidence summary", "status": "complete"},
        {"key": "db_insert",          "label": "Saving results",             "status": "complete" if db_saved else "failed"},
        {"key": "video_to_text",      "label": "Video to text analysis",      "status": "coming_soon"},
        {"key": "github_analysis",    "label": "GitHub code analysis",        "status": "coming_soon"},
    ]


# ── Exceptions ────────────────────────────────────────────────────────────────

class SessionNotFoundError(LookupError):
    pass


class InvalidAnalysisStateError(ValueError):
    pass


# ── Core analysis algorithm ───────────────────────────────────────────────────

def _analyze_workflow(
    proof_data: dict[str, Any],
    claimed_skills: list[str],
    proof_objective: str,
    original_url: str,
    url_type: str,
    github_url: str | None,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = proof_data.get("workflow_events") or []
    started_at_str: str | None = proof_data.get("started_at")
    stopped_at_str: str | None = proof_data.get("stopped_at")

    # Normalise: split any comma-separated skill strings
    normalized_skills: list[str] = []
    for s in (claimed_skills or []):
        normalized_skills.extend(part.strip() for part in s.split(",") if part.strip())
    claimed_skills = normalized_skills

    # ── URL classification: separate target / supporting / noise ──────────────
    target_netloc = _safe_netloc(original_url)
    github_netloc = _safe_netloc(github_url) if github_url else None

    target_events: list[dict[str, Any]] = []
    supporting_events: list[dict[str, Any]] = []
    noise_events: list[dict[str, Any]] = []

    for event in events:
        url = event.get("page_url") or event.get("url") or ""
        category = _classify_url(url, target_netloc, github_netloc)
        if category == "target":
            target_events.append(event)
        elif category == "supporting":
            supporting_events.append(event)
        else:
            noise_events.append(event)

    # ── Categorize target-site events by type ─────────────────────────────────
    target_page_visits = [e for e in target_events if e.get("type") == "page_visit"]
    target_clicks      = [e for e in target_events if e.get("type") == "click"]
    target_inputs      = [e for e in target_events if e.get("type") == "input_change"]
    target_tab_opens   = [e for e in target_events if e.get("type") == "tab_opened"]
    target_navigations = [e for e in target_events if e.get("type") == "navigation"]

    # All-event counts (for activity / duration signal)
    all_tab_opens = [e for e in events if e.get("type") == "tab_opened"]

    # ── Unique target-site pages and titles ───────────────────────────────────
    target_visited_urls: list[str] = list(dict.fromkeys(
        e.get("page_url", "")
        for e in (target_page_visits + target_navigations)
        if e.get("page_url") and not _is_chrome_internal(e.get("page_url", ""))
    ))
    target_visited_titles: list[str] = list(dict.fromkeys(
        t for e in (target_page_visits + target_navigations)
        if (t := (e.get("page_title") or "").strip())
    ))

    # ── Unique supporting evidence (GitHub) pages ─────────────────────────────
    supporting_visited_urls: list[str] = list(dict.fromkeys(
        e.get("page_url", "")
        for e in supporting_events
        if e.get("page_url") and not _is_chrome_internal(e.get("page_url", ""))
    ))

    # ── Noise URLs (internal/debug only — never surfaced to recruiter) ────────
    noise_urls: list[str] = list(dict.fromkeys(
        e.get("page_url", "")
        for e in noise_events
        if e.get("page_url") and not _is_chrome_internal(e.get("page_url", ""))
    ))

    # ── Recording duration ────────────────────────────────────────────────────
    duration_secs = _compute_duration(started_at_str, stopped_at_str)

    # ── Infer tech stack from TARGET + SUPPORTING URLs only ───────────────────
    inferred_tech = _infer_tech_stack(
        target_visited_urls + supporting_visited_urls,
        target_visited_titles,
        original_url,
    )

    # ── Skill matching ────────────────────────────────────────────────────────
    supported, weakly, unsupported, skill_obs = _match_skills(
        claimed_skills, inferred_tech, proof_objective, original_url, url_type
    )

    # ── Evidence strength score (uses TARGET site counts, not noise) ──────────
    score = _compute_score(
        total_events=len(events),               # all events — activity signal
        page_count=len(target_visited_urls),    # TARGET pages only
        click_count=len(target_clicks),         # TARGET clicks only
        input_count=len(target_inputs),         # TARGET inputs only
        tab_opens=len(all_tab_opens),
        duration_secs=duration_secs,
        url_type=url_type,
        supported_count=len(supported),
        claimed_count=max(1, len(claimed_skills)),
    )

    # ── Confidence ────────────────────────────────────────────────────────────
    confidence = _determine_confidence(score, url_type, len(events), duration_secs)

    # ── Demonstrated actions (TARGET site events only) ────────────────────────
    demonstrated_actions = _extract_demonstrated_actions(
        target_page_visits, target_clicks, target_inputs,
        target_tab_opens, target_navigations, target_visited_titles,
        supporting_visited_urls=supporting_visited_urls,
        noise_count=len(noise_urls),
    )

    # ── Missing evidence ──────────────────────────────────────────────────────
    missing_evidence = _determine_missing_evidence(
        claimed_skills, supported, weakly, url_type, github_url,
        target_visited_urls, skill_obs,
        supporting_visited_urls=supporting_visited_urls,
    )

    # ── Risk flags (uses TARGET site data) ───────────────────────────────────
    risk_flags = _determine_risk_flags(
        duration_secs, len(events), url_type,
        target_visited_urls,
        len(target_clicks), len(target_inputs),
    )

    # ── Narrative text ────────────────────────────────────────────────────────
    workflow_summary = _build_workflow_summary(
        target_visited_urls, target_visited_titles, duration_secs, len(events),
        len(all_tab_opens), url_type, proof_objective,
        target_website=target_netloc,
        noise_count=len(noise_urls),
    )
    recruiter_summary = _build_recruiter_summary(
        proof_objective, target_visited_urls, supported, weakly, unsupported,
        url_type, duration_secs, score, confidence, github_url, skill_obs,
        target_visited_titles=target_visited_titles,
        supporting_visited_urls=supporting_visited_urls,
        original_url=original_url,
    )
    suggestions = _build_suggestions(
        url_type, duration_secs, len(events),
        len(target_clicks), len(target_inputs),
        supported, weakly, unsupported, github_url, skill_obs,
    )

    human_review_needed = confidence in ("low", "insufficient") or score < 35

    return {
        "analysis_type":              "timeline_only",
        "workflow_summary":           workflow_summary,
        "demonstrated_actions":       demonstrated_actions,
        "supported_skills":           supported,
        "weakly_supported_skills":    weakly,
        "unsupported_skills":         unsupported,
        "evidence_strength_score":    score,
        "workflow_confidence":        confidence,
        "missing_evidence":           missing_evidence,
        "risk_flags":                 risk_flags,
        "recruiter_summary":          recruiter_summary,
        "student_improvement_suggestions": suggestions,
        "human_review_needed":        human_review_needed,
        # ── Internal / debug fields (not surfaced in recruiter summary) ────────
        "target_website":             target_netloc or _extract_domain(original_url),
        "target_site_pages_count":    len(target_visited_urls),
        "supporting_evidence_count":  len(supporting_visited_urls),
        "noise_filtered_count":       len(noise_urls),
    }


# ── Tech stack inference ──────────────────────────────────────────────────────

def _infer_tech_stack(
    relevant_urls: list[str],
    relevant_titles: list[str],
    original_url: str,
) -> set[str]:
    """Infer tech signals from target-site + supporting URLs only."""
    tech: set[str] = set()

    for url in ([original_url] + relevant_urls):
        if not url:
            continue
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower()
            port = parsed.port

            for domain_suffix, skills in _DOMAIN_TECH.items():
                if netloc.endswith(domain_suffix):
                    tech.update(skills)

            if port and netloc in ("localhost", "127.0.0.1"):
                port_skills = _PORT_TECH.get(str(port), [])
                tech.update(port_skills)

            path = parsed.path.lower()
            if "/docs" in path or "/redoc" in path or "/openapi" in path:
                tech.add("FastAPI")
            if "/admin" in path:
                tech.add("Django")
            if "/api/" in path or "/api" == path:
                tech.add("API")
            if "jupyter" in path or "lab" in path:
                tech.add("Jupyter Notebook")
        except Exception:
            pass

    titles_lower = " ".join(relevant_titles).lower()
    for keyword, canonical in _TITLE_TECH.items():
        if keyword in titles_lower:
            tech.add(canonical)

    return tech


# ── Skill observability helpers ───────────────────────────────────────────────

def _is_code_evidence_skill(canonical: str) -> bool:
    return canonical.lower() in _REQUIRES_CODE_EVIDENCE


def _normalize_skill(skill: str) -> str:
    lower = skill.strip().lower()
    canonical = _SKILL_ALIASES.get(lower)
    if canonical:
        return canonical
    for alias, canon in _SKILL_ALIASES.items():
        if alias in lower or lower in alias:
            return canon
    return skill.strip().title()


def _match_skills(
    claimed_skills: list[str],
    inferred_tech: set[str],
    proof_objective: str,
    original_url: str,
    url_type: str,
) -> tuple[list[str], list[str], list[str], dict[str, str]]:
    supported: list[str] = []
    weakly: list[str] = []
    unsupported: list[str] = []
    observability: dict[str, str] = {}

    objective_lower = proof_objective.lower()
    inferred_lower = {t.lower() for t in inferred_tech}

    is_local = url_type in ("localhost_url", "local_network_url")

    for raw in claimed_skills:
        if not raw.strip():
            continue
        canonical = _normalize_skill(raw)
        canonical_lower = canonical.lower()

        direct_match = (
            canonical_lower in inferred_lower
            or any(canonical_lower in t or t in canonical_lower for t in inferred_lower)
        )
        objective_mentions = (
            canonical_lower in objective_lower
            or raw.lower() in objective_lower
        )
        is_code_skill = _is_code_evidence_skill(canonical)

        if direct_match:
            if is_local:
                weakly.append(canonical)
                observability[canonical] = "from_objective" if objective_mentions else "requires_code_evidence"
            else:
                supported.append(canonical)
                observability[canonical] = "supported"
        elif is_code_skill:
            weakly.append(canonical)
            observability[canonical] = "requires_code_evidence"
        elif objective_mentions:
            weakly.append(canonical)
            observability[canonical] = "from_objective"
        else:
            unsupported.append(canonical)
            observability[canonical] = "unsupported"

    def _dedup(lst: list[str]) -> list[str]:
        seen: set[str] = set()
        return [x for x in lst if not (x in seen or seen.add(x))]  # type: ignore[func-returns-value]

    return _dedup(supported), _dedup(weakly), _dedup(unsupported), observability


# ── Evidence strength scoring ─────────────────────────────────────────────────

def _compute_score(
    total_events: int,
    page_count: int,
    click_count: int,
    input_count: int,
    tab_opens: int,
    duration_secs: float,
    url_type: str,
    supported_count: int,
    claimed_count: int,
) -> int:
    score = 0

    # Recording activity (max 20 pts) — uses all events as activity signal
    if total_events >= 30:
        score += 20
    elif total_events >= 20:
        score += 16
    elif total_events >= 10:
        score += 11
    elif total_events >= 5:
        score += 6
    elif total_events > 0:
        score += 3

    # Target-site page diversity (max 15 pts)
    if page_count >= 5:
        score += 15
    elif page_count >= 3:
        score += 10
    elif page_count >= 2:
        score += 7
    elif page_count >= 1:
        score += 4

    # Recording duration (max 20 pts)
    if duration_secs >= 300:
        score += 20
    elif duration_secs >= 180:
        score += 16
    elif duration_secs >= 90:
        score += 11
    elif duration_secs >= 45:
        score += 7
    elif duration_secs >= 15:
        score += 4

    # Target-site user interaction depth (max 20 pts)
    interactions = click_count + input_count
    if interactions >= 20:
        score += 20
    elif interactions >= 10:
        score += 15
    elif interactions >= 5:
        score += 10
    elif interactions >= 2:
        score += 6
    elif interactions >= 1:
        score += 3

    # Multi-tab depth bonus (max 5 pts)
    score += min(5, tab_opens * 2)

    # URL type (max 15 pts for live, less for local)
    if url_type == "live_deployed_url":
        score += 15
    elif url_type in ("localhost_url", "local_network_url"):
        score += 5

    # Skill coverage ratio (max 5 pts)
    ratio = supported_count / claimed_count if claimed_count > 0 else 0
    score += int(ratio * 5)

    return min(80, max(0, score))


# ── Confidence determination ──────────────────────────────────────────────────

def _determine_confidence(
    score: int,
    url_type: str,
    total_events: int,
    duration_secs: float,
) -> str:
    if total_events < 3 or duration_secs < 10:
        return "insufficient"
    if score < 20:
        return "insufficient"
    if score < 35:
        return "low"
    if url_type == "live_deployed_url" and score >= 55 and duration_secs >= 120:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


# ── Demonstrated actions ──────────────────────────────────────────────────────

def _extract_demonstrated_actions(
    target_page_visits: list[dict],
    target_clicks: list[dict],
    target_inputs: list[dict],
    target_tab_opens: list[dict],
    target_navigations: list[dict],
    target_visited_titles: list[str],
    *,
    supporting_visited_urls: list[str] | None = None,
    noise_count: int = 0,
) -> list[str]:
    """Build human-readable action bullets — TARGET site events only.

    Noise events are excluded entirely.
    Supporting GitHub evidence is noted separately.
    """
    actions: list[str] = []
    supporting_visited_urls = supporting_visited_urls or []

    # Target site page visits
    target_urls = list(dict.fromkeys(
        e.get("page_url", "") for e in target_page_visits if e.get("page_url")
    ))

    if not target_urls and not target_navigations:
        actions.append(
            "No interactions with the target application were observed in the recording."
        )
    else:
        if target_urls:
            first_url = target_urls[0]
            actions.append(f"Target application loaded: {_format_url(first_url)}")
            if len(target_urls) > 1:
                actions.append(
                    f"{len(target_urls)} pages navigated within the target application"
                )
                for url in target_urls[1:4]:
                    actions.append(f"  • {_format_url(url)}")
                if len(target_urls) > 4:
                    actions.append(f"  • … and {len(target_urls) - 4} more")

    # Meaningful page titles (context, not noise)
    meaningful_titles = [
        t for t in target_visited_titles if len(t) > 5 and "://" not in t
    ]
    if meaningful_titles:
        actions.append(f"Page context: {'; '.join(meaningful_titles[:3])}")

    # Interactions on target site
    click_count = len(target_clicks)
    input_count = len(target_inputs)
    if click_count > 0 or input_count > 0:
        interaction_parts: list[str] = []
        if click_count:
            significant = [
                c for c in target_clicks if c.get("element_text") or c.get("element_id")
            ]
            if significant:
                sample = significant[:3]
                label = ", ".join(
                    f'"{(c.get("element_text") or c.get("element_id") or "")[:40]}"'
                    for c in sample
                )
                interaction_parts.append(f"{click_count} click(s) including {label}")
            else:
                interaction_parts.append(f"{click_count} click(s)")
        if input_count:
            interaction_parts.append(f"{input_count} form/input interaction(s)")
        actions.append(f"User interactions: {', '.join(interaction_parts)}")
    elif target_urls:
        actions.append(
            "No click or input interactions were recorded on the target application — "
            "page load only was observed."
        )

    # Supporting GitHub evidence
    if supporting_visited_urls:
        actions.append(
            f"Supporting evidence: {len(supporting_visited_urls)} GitHub page(s) also visited "
            "during the session"
        )

    # Navigations within target
    if target_navigations:
        actions.append(
            f"Navigated through {len(target_navigations)} page(s) within the target application"
        )

    return actions if actions else ["No workflow events were captured"]


# ── Missing evidence ──────────────────────────────────────────────────────────

def _determine_missing_evidence(
    claimed_skills: list[str],
    supported: list[str],
    weakly: list[str],
    url_type: str,
    github_url: str | None,
    target_visited_urls: list[str],
    skill_obs: dict[str, str] | None = None,
    *,
    supporting_visited_urls: list[str] | None = None,
) -> list[str]:
    missing: list[str] = []
    skill_obs = skill_obs or {}
    supporting_visited_urls = supporting_visited_urls or []

    is_local = url_type in ("localhost_url", "local_network_url")

    if is_local:
        missing.append(
            "Live deployed URL — recruiters cannot access the app independently from a localhost recording"
        )
    if not github_url:
        missing.append("GitHub repository URL for source code evidence")
    elif not supporting_visited_urls:
        missing.append(
            "GitHub repository was not visited during the recording session"
        )

    code_evidence_skills = [
        s for s in weakly if skill_obs.get(s) == "requires_code_evidence"
    ]
    if code_evidence_skills:
        skills_str = ", ".join(code_evidence_skills[:3])
        missing.append(
            f"GitHub repository analysis to verify back-end/code skill(s): {skills_str} "
            "(these skills are implemented in code, not directly visible in a browser recording)"
        )

    truly_unsupported = [
        s for s in claimed_skills if s not in supported and s not in weakly
    ]
    for skill in truly_unsupported[:3]:
        missing.append(f"Observable evidence for claimed skill: {skill}")

    if not target_visited_urls:
        missing.append(
            "Any recorded interactions with the target application — "
            "no target site pages were captured in the workflow"
        )

    return missing


# ── Risk flags ────────────────────────────────────────────────────────────────

def _determine_risk_flags(
    duration_secs: float,
    total_events: int,
    url_type: str,
    target_visited_urls: list[str],
    target_click_count: int,
    target_input_count: int,
) -> list[str]:
    """Generate risk flags based on TARGET site evidence only."""
    flags: list[str] = []

    if total_events == 0:
        flags.append("No workflow events captured — recording may not have started correctly")
    elif total_events < 5:
        flags.append(f"Very few events captured ({total_events}) — recording may be incomplete")

    if duration_secs < 20 and total_events > 0:
        flags.append(f"Very short recording ({int(duration_secs)}s) — limited workflow demonstrated")
    elif duration_secs < 60 and total_events > 0:
        flags.append(f"Short recording ({int(duration_secs)}s) — consider a more complete walkthrough")

    if url_type in ("localhost_url", "local_network_url"):
        flags.append(
            "Localhost/local URL — app runs only on the student's machine; "
            "recruiters cannot independently open or verify the deployed application"
        )

    if not target_visited_urls and total_events > 0:
        flags.append(
            "No interactions with the target application were recorded — "
            "the recording appears to show only unrelated browser tabs or development tools"
        )
    elif target_visited_urls and target_click_count == 0 and target_input_count == 0:
        flags.append(
            "Target application page loaded but no user interactions (clicks, form inputs) "
            "were recorded — workflow shows page load only; deeper app functionality "
            "was not demonstrated"
        )

    return flags


# ── Narrative builders ────────────────────────────────────────────────────────

def _build_workflow_summary(
    target_visited_urls: list[str],
    target_visited_titles: list[str],
    duration_secs: float,
    total_events: int,
    tab_opens_total: int,
    url_type: str,
    proof_objective: str,
    *,
    target_website: str = "",
    noise_count: int = 0,
) -> str:
    """Target-site-focused workflow summary.

    Only describes what was demonstrated on the proof target website.
    Noise events (unrelated tabs, Supabase, VeriBridge dashboard) are not mentioned.
    """
    duration_label = _fmt_duration(duration_secs)
    page_count = len(target_visited_urls)
    url_label = (
        "a locally-running application"
        if url_type in ("localhost_url", "local_network_url")
        else "a live web application"
    )

    if total_events == 0:
        return "No workflow events were recorded. The recording may not have captured any activity."

    if not target_visited_urls:
        base = f"The student recorded a {duration_label} workflow session."
        if noise_count > 0:
            base += (
                f" {noise_count} event(s) from unrelated browser tabs or development tools "
                "were captured but are excluded from this analysis as they fall outside "
                "the target proof application."
            )
        return base

    site_label = f"'{target_website}'" if target_website else url_label
    parts: list[str] = [
        f"The student recorded a {duration_label} workflow session "
        f"demonstrating {site_label}."
    ]

    if page_count == 1:
        parts.append("1 page within the target application was visited.")
    elif page_count > 1:
        parts.append(f"{page_count} pages within the target application were visited.")

    meaningful_titles = [t for t in target_visited_titles if len(t) > 5 and "://" not in t]
    if meaningful_titles:
        parts.append(f"Application context: {'; '.join(meaningful_titles[:3])}.")

    if proof_objective:
        parts.append(f"The stated proof objective was: \"{proof_objective.strip()[:200]}\".")

    if url_type in ("localhost_url", "local_network_url"):
        parts.append(
            "Because this is a local recording, the application is not publicly accessible — "
            "this demonstrates the project running on the student's development machine."
        )

    if noise_count > 0:
        parts.append(
            f"Note: {noise_count} background event(s) from unrelated browser tabs "
            "were filtered out and are not included in this evidence analysis."
        )

    return " ".join(parts)


def _build_recruiter_summary(
    proof_objective: str,
    target_visited_urls: list[str],
    supported: list[str],
    weakly: list[str],
    unsupported: list[str],
    url_type: str,
    duration_secs: float,
    score: int,
    confidence: str,
    github_url: str | None,
    skill_obs: dict[str, str] | None = None,
    *,
    target_visited_titles: list[str] | None = None,
    supporting_visited_urls: list[str] | None = None,
    original_url: str = "",
) -> str:
    """Recruiter-facing summary focused on the proof target website.

    Never mentions unrelated browser tabs, Supabase, VeriBridge dashboard,
    or any noise URLs. Only describes what was observed on the target app
    and any supporting GitHub evidence.
    """
    is_local = url_type in ("localhost_url", "local_network_url")
    duration_label = _fmt_duration(duration_secs)
    skill_obs = skill_obs or {}
    target_visited_titles = target_visited_titles or []
    supporting_visited_urls = supporting_visited_urls or []

    target_domain = _extract_domain(original_url) or ""
    app_label = f"'{target_domain}'" if target_domain else "the target application"
    app_type_label = (
        "locally-running application" if is_local else "live web application"
    )

    lines: list[str] = []

    # ── Opening: what was demonstrated ───────────────────────────────────────
    if not target_visited_urls:
        lines.append(
            f"The {duration_label} recording was captured, but no interactions with "
            f"{app_label} were observed in the workflow. The recording may show navigation "
            f"to unrelated browser tabs; the target application workflow was not captured."
        )
    else:
        page_count = len(target_visited_urls)
        meaningful_titles = [t for t in target_visited_titles if len(t) > 5]

        title_context = ""
        if meaningful_titles:
            title_context = f" ({'; '.join(meaningful_titles[:2])})"

        lines.append(
            f"The recording shows the student demonstrating {app_label}{title_context}, "
            f"a {app_type_label}."
        )
        if page_count > 1:
            lines.append(
                f"{page_count} pages within the target application were observed in the session."
            )

    # ── Proof objective ───────────────────────────────────────────────────────
    if proof_objective:
        lines.append(
            f"The student intended to demonstrate: \"{proof_objective.strip()[:200]}\"."
        )

    # ── Skills directly supported by target-site workflow ────────────────────
    if supported:
        lines.append(
            f"The observed workflow supports evidence for: {', '.join(supported)}."
        )

    # ── Skills weakly supported: split code vs. objective-mentioned ───────────
    if weakly:
        code_evidence_skills = [
            s for s in weakly if skill_obs.get(s) == "requires_code_evidence"
        ]
        indirect_skills = [
            s for s in weakly if skill_obs.get(s) not in ("requires_code_evidence",)
        ]

        if code_evidence_skills:
            skill_word = "skill" if len(code_evidence_skills) == 1 else "skills"
            it_them = "it" if len(code_evidence_skills) == 1 else "them"
            is_are = "is" if len(code_evidence_skills) == 1 else "are"
            lines.append(
                f"{', '.join(code_evidence_skills)} {is_are} back-end or code-level "
                f"{skill_word} not directly observable in a browser recording. "
                f"GitHub repository analysis is recommended to verify {it_them}."
            )
        if indirect_skills:
            lines.append(
                f"Partial evidence is available for: {', '.join(indirect_skills)}. "
                "These skills are consistent with the observed workflow but require "
                "additional evidence for full confirmation."
            )

    # ── No observable evidence ────────────────────────────────────────────────
    if unsupported:
        lines.append(
            f"No observable evidence was found for: {', '.join(unsupported)}. "
            "Consider a more focused demonstration or add GitHub and live deployment evidence."
        )

    # ── Supporting GitHub evidence ────────────────────────────────────────────
    if supporting_visited_urls and github_url:
        lines.append(
            "GitHub repository evidence was also visited during the recording, "
            "providing additional context for code-level skills."
        )

    # ── Localhost caveat ──────────────────────────────────────────────────────
    if is_local:
        lines.append(
            "This is a local (localhost) recording — the application is not publicly accessible. "
            "A live deployment URL would significantly strengthen this proof."
        )

    # ── Score / confidence footer ─────────────────────────────────────────────
    confidence_label = {
        "high": "High",
        "medium": "Medium",
        "low": "Low",
        "insufficient": "Insufficient",
    }.get(confidence, confidence.capitalize())
    lines.append(
        f"Evidence strength: {score}/100 · Confidence: {confidence_label} "
        f"(Workflow Timeline Analysis — visual video evidence not yet available)."
    )

    return " ".join(lines)


def _build_suggestions(
    url_type: str,
    duration_secs: float,
    total_events: int,
    click_count: int,
    input_count: int,
    supported: list[str],
    weakly: list[str],
    unsupported: list[str],
    github_url: str | None,
    skill_obs: dict[str, str] | None = None,
) -> list[str]:
    suggestions: list[str] = []
    skill_obs = skill_obs or {}

    if url_type in ("localhost_url", "local_network_url"):
        suggestions.append(
            "Deploy the application to a live URL (e.g., Vercel, Railway, Render) so recruiters "
            "can independently access and verify it"
        )

    code_evidence_skills = [s for s in weakly if skill_obs.get(s) == "requires_code_evidence"]
    if code_evidence_skills and not github_url:
        skills_str = ", ".join(code_evidence_skills[:3])
        suggestions.append(
            f"Add a public GitHub repository URL — back-end/code skill(s) {skills_str} cannot "
            "be verified from the browser recording alone and require repository analysis"
        )
    elif not github_url:
        suggestions.append(
            "Add a GitHub repository URL to allow code-level verification of your implementation"
        )

    if duration_secs < 90:
        suggestions.append(
            "Record a longer, more comprehensive walkthrough (at least 2–3 minutes) "
            "showing the core features end-to-end"
        )

    if click_count + input_count < 5:
        suggestions.append(
            "Interact more with the application — submit forms, trigger API calls, "
            "and show real results to demonstrate the app working"
        )

    if unsupported:
        skills_str = ", ".join(unsupported[:3])
        suggestions.append(
            f"Demonstrate evidence for unsupported claimed skill(s): {skills_str} — "
            "navigate to the relevant part of your app during the recording"
        )

    indirect_weakly = [s for s in weakly if skill_obs.get(s) == "from_objective"]
    if indirect_weakly and not unsupported:
        suggestions.append(
            "Consider showing specific features that directly demonstrate your claimed skills "
            "(e.g., triggering an API call, running a model inference, submitting a database query)"
        )

    if github_url:
        suggestions.append(
            "Run GitHub Evidence Analysis to verify back-end and code skills from your repository"
        )
    else:
        suggestions.append(
            "Once GitHub evidence is added, run GitHub analysis to strengthen the overall verification score"
        )

    return suggestions


# ── Utility helpers ───────────────────────────────────────────────────────────

def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc
    except Exception:
        return url


def _is_chrome_internal(url: str) -> bool:
    return url.startswith(("chrome://", "chrome-extension://", "about:", "data:"))


def _compute_duration(started_at: str | None, stopped_at: str | None) -> float:
    if not started_at:
        return 0.0
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = (
            datetime.fromisoformat(stopped_at.replace("Z", "+00:00"))
            if stopped_at
            else datetime.now(timezone.utc)
        )
        delta = (end - start).total_seconds()
        return max(0.0, delta)
    except Exception:
        return 0.0


def _fmt_duration(secs: float) -> str:
    if secs < 5:
        return "brief"
    if secs < 60:
        return f"{int(secs)}-second"
    minutes = int(secs // 60)
    return f"{minutes}-minute"


def _format_url(url: str) -> str:
    try:
        p = urlparse(url)
        if p.netloc:
            path = p.path.rstrip("/") or "/"
            return f"{p.netloc}{path[:60]}"
    except Exception:
        pass
    return url[:80]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
