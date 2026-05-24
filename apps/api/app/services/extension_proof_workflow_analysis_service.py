"""Extension Proof Workflow Analysis Service.

Performs deep timeline-based analysis of a recorded browser workflow to
produce recruiter-readable evidence about what the student demonstrated,
which claimed skills are supported, and what is still missing.

Current analysis_type: 'timeline_only'
  — uses workflow events, URLs, page titles, and recording metadata.
  — does NOT perform video frame extraction or screenshot analysis (yet).
  — the output schema is designed so video/multimodal analysis can be
    dropped in later without changing the API surface.

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

ANALYZER_VERSION = "workflow-analysis-v1"

# Status values from which workflow analysis is allowed.
_VALID_ANALYZE_FROM = frozenset({"uploaded_pending_analysis", "analyzing"})


# ── Tech detection maps ───────────────────────────────────────────────────────

# Known deployment domains → likely tech signals (partial match on netloc)
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

# localhost port → likely tech signals
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

# Substrings in page titles → likely tech (lowercase match)
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

# Normalize claimed skills → canonical form for comparison
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
}


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

        Transitions the session from uploaded_pending_analysis → analyzing
        (if not already analyzing), then computes and stores the analysis.
        Returns the stored row dict.
        """
        session = self._get_session(user_id, session_id)
        current_status = session.get("status", "")

        if current_status not in _VALID_ANALYZE_FROM:
            raise InvalidAnalysisStateError(
                f"Cannot analyze a session with status '{current_status}'. "
                f"Allowed from: {sorted(_VALID_ANALYZE_FROM)}."
            )

        # Advance session to 'analyzing' if it hasn't moved yet.
        if current_status == "uploaded_pending_analysis":
            self._update_session_status(user_id, session_id, "analyzing")

        proof_data: dict[str, Any] = session.get("proof_data") or {}
        result = _analyze_workflow(
            proof_data=proof_data,
            claimed_skills=claimed_skills,
            proof_objective=proof_objective,
            original_url=original_url,
            url_type=url_type,
            github_url=github_url,
        )

        row = self._upsert_result(user_id, session_id, result)
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

    # ── Internals ─────────────────────────────────────────────────────────────

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

        # Upsert: update if exists, insert if not
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

    # ── Categorize events ─────────────────────────────────────────────────────
    page_visits  = [e for e in events if e.get("type") == "page_visit"]
    clicks       = [e for e in events if e.get("type") == "click"]
    inputs       = [e for e in events if e.get("type") == "input_change"]
    tab_opens    = [e for e in events if e.get("type") == "tab_opened"]
    navigations  = [e for e in events if e.get("type") == "navigation"]

    # ── Unique pages and domains ──────────────────────────────────────────────
    visited_urls: list[str] = list(dict.fromkeys(
        e.get("page_url", "")
        for e in (page_visits + navigations)
        if e.get("page_url") and not _is_chrome_internal(e.get("page_url", ""))
    ))
    visited_domains = list(dict.fromkeys(_extract_domain(u) for u in visited_urls if u))
    visited_titles = list(dict.fromkeys(
        t for e in (page_visits + navigations)
        if (t := (e.get("page_title") or "").strip())
    ))

    # ── Recording duration ────────────────────────────────────────────────────
    duration_secs = _compute_duration(started_at_str, stopped_at_str)

    # ── Infer tech from observable signals ───────────────────────────────────
    inferred_tech = _infer_tech_stack(visited_urls, visited_titles, original_url)

    # ── Skill matching ────────────────────────────────────────────────────────
    supported, weakly, unsupported = _match_skills(
        claimed_skills, inferred_tech, proof_objective, original_url, url_type
    )

    # ── Evidence strength score ───────────────────────────────────────────────
    score = _compute_score(
        total_events=len(events),
        page_count=len(visited_urls),
        click_count=len(clicks),
        input_count=len(inputs),
        tab_opens=len(tab_opens),
        duration_secs=duration_secs,
        url_type=url_type,
        supported_count=len(supported),
        claimed_count=max(1, len(claimed_skills)),
    )

    # ── Confidence ────────────────────────────────────────────────────────────
    confidence = _determine_confidence(score, url_type, len(events), duration_secs)

    # ── Demonstrated actions (human-readable bullets) ─────────────────────────
    demonstrated_actions = _extract_demonstrated_actions(
        page_visits, clicks, inputs, tab_opens, navigations, visited_titles
    )

    # ── Missing evidence ──────────────────────────────────────────────────────
    missing_evidence = _determine_missing_evidence(
        claimed_skills, supported, weakly, url_type, github_url, visited_urls
    )

    # ── Risk flags ────────────────────────────────────────────────────────────
    risk_flags = _determine_risk_flags(
        duration_secs, len(events), url_type, visited_urls, len(clicks), len(inputs)
    )

    # ── Narrative text ────────────────────────────────────────────────────────
    workflow_summary = _build_workflow_summary(
        visited_urls, visited_titles, duration_secs, len(events),
        len(tab_opens), url_type, proof_objective
    )
    recruiter_summary = _build_recruiter_summary(
        proof_objective, visited_urls, supported, weakly, unsupported,
        url_type, duration_secs, score, confidence, github_url
    )
    suggestions = _build_suggestions(
        url_type, duration_secs, len(events), len(clicks), len(inputs),
        supported, weakly, unsupported, github_url
    )

    human_review_needed = confidence in ("low", "insufficient") or score < 35

    return {
        "analysis_type": "timeline_only",
        "workflow_summary": workflow_summary,
        "demonstrated_actions": demonstrated_actions,
        "supported_skills": supported,
        "weakly_supported_skills": weakly,
        "unsupported_skills": unsupported,
        "evidence_strength_score": score,
        "workflow_confidence": confidence,
        "missing_evidence": missing_evidence,
        "risk_flags": risk_flags,
        "recruiter_summary": recruiter_summary,
        "student_improvement_suggestions": suggestions,
        "human_review_needed": human_review_needed,
    }


# ── Tech stack inference ──────────────────────────────────────────────────────

def _infer_tech_stack(
    visited_urls: list[str],
    visited_titles: list[str],
    original_url: str,
) -> set[str]:
    tech: set[str] = set()

    for url in ([original_url] + visited_urls):
        if not url:
            continue
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower()
            port = parsed.port

            # Domain pattern matching
            for domain_suffix, skills in _DOMAIN_TECH.items():
                if netloc.endswith(domain_suffix):
                    tech.update(skills)

            # Port-based inference (localhost and 127.0.0.1 only)
            if port and netloc in ("localhost", "127.0.0.1"):
                port_skills = _PORT_TECH.get(str(port), [])
                tech.update(port_skills)

            # Path hints
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

    # Title keyword matching
    titles_lower = " ".join(visited_titles).lower()
    for keyword, canonical in _TITLE_TECH.items():
        if keyword in titles_lower:
            tech.add(canonical)

    return tech


# ── Skill matching ────────────────────────────────────────────────────────────

def _normalize_skill(skill: str) -> str:
    """Return canonical skill name, or best-effort title-case."""
    lower = skill.strip().lower()
    canonical = _SKILL_ALIASES.get(lower)
    if canonical:
        return canonical
    # Check partial alias matches
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
) -> tuple[list[str], list[str], list[str]]:
    supported: list[str] = []
    weakly: list[str] = []
    unsupported: list[str] = []

    objective_lower = proof_objective.lower()
    inferred_lower = {t.lower() for t in inferred_tech}

    is_local = url_type in ("localhost_url", "local_network_url")

    for raw in claimed_skills:
        if not raw.strip():
            continue
        canonical = _normalize_skill(raw)
        canonical_lower = canonical.lower()

        # Check direct match with inferred tech
        direct_match = (
            canonical_lower in inferred_lower
            or any(canonical_lower in t or t in canonical_lower for t in inferred_lower)
        )

        # Check if proof_objective mentions this skill
        objective_mentions = (
            canonical_lower in objective_lower
            or raw.lower() in objective_lower
        )

        if direct_match:
            if is_local:
                # For localhost, even a direct match is only weakly supported —
                # we can see the app is running but not verify the implementation.
                weakly.append(canonical)
            else:
                supported.append(canonical)
        elif objective_mentions:
            weakly.append(canonical)
        else:
            unsupported.append(canonical)

    # Deduplicate while preserving order
    def _dedup(lst: list[str]) -> list[str]:
        seen: set[str] = set()
        return [x for x in lst if not (x in seen or seen.add(x))]  # type: ignore[func-returns-value]

    return _dedup(supported), _dedup(weakly), _dedup(unsupported)


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

    # Recording activity (max 20 pts)
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

    # Page/URL diversity (max 15 pts)
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

    # User interaction depth (max 20 pts)
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

    # Timeline-only cap: max 80 — visual/video evidence needed for higher
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
    page_visits: list[dict],
    clicks: list[dict],
    inputs: list[dict],
    tab_opens: list[dict],
    navigations: list[dict],
    visited_titles: list[str],
) -> list[str]:
    actions: list[str] = []

    # Page visits summary
    unique_pages = list(dict.fromkeys(
        e.get("page_url", "") for e in page_visits if e.get("page_url")
    ))
    if unique_pages:
        if len(unique_pages) == 1:
            actions.append(f"Visited 1 page: {_format_url(unique_pages[0])}")
        else:
            actions.append(f"Visited {len(unique_pages)} distinct pages")
            for url in unique_pages[:5]:
                actions.append(f"  • {_format_url(url)}")
            if len(unique_pages) > 5:
                actions.append(f"  • … and {len(unique_pages) - 5} more")

    # Click interactions
    if clicks:
        significant = [c for c in clicks if c.get("element_text") or c.get("element_id")]
        if significant:
            sample = significant[:3]
            label = ", ".join(
                f'"{(c.get("element_text") or c.get("element_id") or "")[:40]}"'
                for c in sample
            )
            actions.append(f"Clicked {len(clicks)} element(s) including: {label}")
        else:
            actions.append(f"Performed {len(clicks)} click interaction(s)")

    # Input interactions
    if inputs:
        actions.append(f"Interacted with {len(inputs)} form field(s) or input element(s)")

    # Tab opens
    for t in tab_opens:
        url = t.get("page_url", "")
        if url:
            actions.append(f"Opened new tab: {_format_url(url)}")
        else:
            actions.append("Opened a new browser tab")

    # Navigations
    if navigations:
        actions.append(f"Navigated between {len(navigations)} page(s) within tracked tabs")

    # Page titles as context
    meaningful_titles = [t for t in visited_titles if len(t) > 5 and "://" not in t]
    if meaningful_titles:
        actions.append(f"Page context: {'; '.join(meaningful_titles[:3])}")

    return actions if actions else ["No workflow events were captured"]


# ── Missing evidence ──────────────────────────────────────────────────────────

def _determine_missing_evidence(
    claimed_skills: list[str],
    supported: list[str],
    weakly: list[str],
    url_type: str,
    github_url: str | None,
    visited_urls: list[str],
) -> list[str]:
    missing: list[str] = []

    is_local = url_type in ("localhost_url", "local_network_url")

    if is_local:
        missing.append(
            "Live deployed URL — recruiters cannot access the app independently from a localhost recording"
        )
    if not github_url:
        missing.append("GitHub repository URL for source code evidence")
    elif not any("github.com" in u for u in visited_urls):
        missing.append("GitHub repository was not visited during the recording session")

    unsupported_skills = [
        s for s in claimed_skills
        if s not in supported and s not in weakly
    ]
    if unsupported_skills:
        for skill in unsupported_skills[:3]:
            missing.append(f"Observable evidence for claimed skill: {skill}")

    if not visited_urls:
        missing.append("Any recorded page visits — no pages were captured in the workflow")

    return missing


# ── Risk flags ────────────────────────────────────────────────────────────────

def _determine_risk_flags(
    duration_secs: float,
    total_events: int,
    url_type: str,
    visited_urls: list[str],
    click_count: int,
    input_count: int,
) -> list[str]:
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

    if click_count == 0 and input_count == 0 and total_events > 0:
        flags.append(
            "No click or form interactions recorded — workflow shows page visits but no app usage"
        )

    if not visited_urls:
        flags.append("No page URLs were recorded in the workflow")

    return flags


# ── Narrative builders ────────────────────────────────────────────────────────

def _build_workflow_summary(
    visited_urls: list[str],
    visited_titles: list[str],
    duration_secs: float,
    total_events: int,
    tab_opens: int,
    url_type: str,
    proof_objective: str,
) -> str:
    duration_label = _fmt_duration(duration_secs)
    page_count = len(visited_urls)
    url_label = (
        "a locally-running application" if url_type in ("localhost_url", "local_network_url")
        else "a live web application"
    )

    parts: list[str] = []
    if total_events == 0:
        return "No workflow events were recorded. The recording may not have captured any activity."

    parts.append(
        f"The student recorded a {duration_label} workflow session on {url_label}"
    )
    if page_count > 0:
        parts.append(f"visiting {page_count} distinct page(s)")
    if total_events > 0:
        interactions = total_events - page_count
        if interactions > 0:
            parts.append(f"with {interactions} user interaction(s) captured")
    if tab_opens > 0:
        parts.append(
            f"{'including' if tab_opens == 1 else 'including'} "
            f"{tab_opens} additional tab(s) opened during the session"
        )
    summary = ", ".join(parts) + "."

    if proof_objective:
        summary += f" The stated proof objective was: \"{proof_objective.strip()[:200]}\""

    meaningful_titles = [t for t in visited_titles if len(t) > 5 and "://" not in t]
    if meaningful_titles:
        summary += f" Pages visited include: {'; '.join(meaningful_titles[:3])}."

    if url_type in ("localhost_url", "local_network_url"):
        summary += (
            " Because this is a local recording, the application is not publicly accessible —"
            " this demonstrates the project running on the student's development machine."
        )

    return summary


def _build_recruiter_summary(
    proof_objective: str,
    visited_urls: list[str],
    supported: list[str],
    weakly: list[str],
    unsupported: list[str],
    url_type: str,
    duration_secs: float,
    score: int,
    confidence: str,
    github_url: str | None,
) -> str:
    is_local = url_type in ("localhost_url", "local_network_url")
    duration_label = _fmt_duration(duration_secs)
    page_label = f"{len(visited_urls)} page(s)" if visited_urls else "no recorded pages"
    app_label = "a locally-running application" if is_local else "a live web application"

    lines: list[str] = []

    # Opening
    lines.append(
        f"This workflow evidence captures a {duration_label} browser recording on {app_label}, "
        f"covering {page_label}."
    )

    # Proof objective
    if proof_objective:
        lines.append(f"The student intended to demonstrate: \"{proof_objective.strip()[:200]}\"")

    # Skills
    if supported:
        lines.append(
            f"The workflow provides supporting evidence for: {', '.join(supported)}."
        )
    if weakly:
        lines.append(
            f"The workflow provides partial or indirect evidence for: {', '.join(weakly)}. "
            "These skills are consistent with the recorded workflow but cannot be fully confirmed from timeline data alone."
        )
    if unsupported:
        lines.append(
            f"No observable evidence was found for: {', '.join(unsupported)}. "
            "Additional proof (GitHub repository, code review, or live demonstration) is recommended."
        )

    # Local caveat
    if is_local:
        lines.append(
            "This is a local (localhost) recording. The application cannot be independently "
            "accessed or verified by recruiters. GitHub evidence or a live deployment link "
            "would significantly strengthen this proof."
        )

    # Score/confidence
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
) -> list[str]:
    suggestions: list[str] = []

    if url_type in ("localhost_url", "local_network_url"):
        suggestions.append(
            "Deploy the application to a live URL (e.g., Vercel, Railway, Render) so recruiters "
            "can independently access and verify it"
        )

    if not github_url:
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

    if weakly and not unsupported:
        suggestions.append(
            "Consider showing specific features that directly demonstrate your claimed skills "
            "(e.g., triggering an API call, running a model inference, submitting a database query)"
        )

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
