"""Extension Proof GitHub Analysis Service.

Probes a public GitHub repository to detect the tech stack, match
claimed skills, compute a confidence score, and build a recruiter summary.
No authentication token is required — public repos only.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.services.github_evidence_service import (
    fetch_public_github_file,
    parse_github_repo_url,
)

logger = logging.getLogger(__name__)

# ── Stack detection maps ──────────────────────────────────────────────────────

# keyword (lowercase, partial match) → canonical tech name
_REQS_STACK: dict[str, str] = {
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "starlette": "Starlette",
    "tornado": "Tornado",
    "aiohttp": "aiohttp",
    "torch": "PyTorch",
    "tensorflow": "TensorFlow",
    "keras": "Keras",
    "scikit-learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "xgboost": "XGBoost",
    "lightgbm": "LightGBM",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "langchain": "LangChain",
    "llamaindex": "LlamaIndex",
    "transformers": "HuggingFace Transformers",
    "pandas": "Pandas",
    "numpy": "NumPy",
    "matplotlib": "Matplotlib",
    "seaborn": "Seaborn",
    "plotly": "Plotly",
    "sqlalchemy": "SQLAlchemy",
    "alembic": "Alembic",
    "supabase": "Supabase",
    "pymongo": "MongoDB",
    "motor": "MongoDB",
    "redis": "Redis",
    "celery": "Celery",
    "pydantic": "Pydantic",
    "boto3": "AWS",
    "google-cloud": "Google Cloud",
    "azure": "Azure",
    "stripe": "Stripe",
    "twilio": "Twilio",
    "pytest": "pytest",
    "hypothesis": "Hypothesis",
}

_NPM_STACK: dict[str, str] = {
    "react": "React",
    "next": "Next.js",
    "vue": "Vue",
    "@angular": "Angular",
    "svelte": "Svelte",
    "solid-js": "SolidJS",
    "remix": "Remix",
    "astro": "Astro",
    "express": "Express",
    "fastify": "Fastify",
    "koa": "Koa",
    "hapi": "Hapi",
    "nestjs": "NestJS",
    "@nestjs": "NestJS",
    "typescript": "TypeScript",
    "tailwindcss": "Tailwind CSS",
    "@tailwind": "Tailwind CSS",
    "prisma": "Prisma",
    "drizzle-orm": "Drizzle ORM",
    "graphql": "GraphQL",
    "apollo": "Apollo",
    "@trpc": "tRPC",
    "trpc": "tRPC",
    "supabase": "Supabase",
    "@supabase": "Supabase",
    "firebase": "Firebase",
    "stripe": "Stripe",
    "openai": "OpenAI",
    "langchain": "LangChain",
    "jest": "Jest",
    "vitest": "Vitest",
    "playwright": "Playwright",
    "cypress": "Cypress",
    "storybook": "Storybook",
    "electron": "Electron",
    "redis": "Redis",
    "ioredis": "Redis",
    "mongoose": "MongoDB",
    "socket.io": "Socket.IO",
    "vite": "Vite",
    "webpack": "Webpack",
    "esbuild": "esbuild",
}

# normalized skill label → tech terms that count as matching
_SKILL_ALIASES: dict[str, list[str]] = {
    "python": ["FastAPI", "Django", "Flask", "Starlette", "aiohttp", "Pandas", "NumPy", "scikit-learn", "PyTorch", "TensorFlow", "Keras"],
    "javascript": ["React", "Next.js", "Vue", "Angular", "Express", "Fastify", "NestJS", "Socket.IO"],
    "typescript": ["TypeScript", "React", "Next.js", "NestJS", "tRPC"],
    "react": ["React", "Next.js", "Remix"],
    "next.js": ["Next.js"],
    "nextjs": ["Next.js"],
    "vue": ["Vue"],
    "angular": ["Angular"],
    "svelte": ["Svelte"],
    "node": ["Express", "Fastify", "NestJS", "Koa"],
    "nodejs": ["Express", "Fastify", "NestJS", "Koa"],
    "fastapi": ["FastAPI"],
    "django": ["Django"],
    "flask": ["Flask"],
    "machine learning": ["scikit-learn", "PyTorch", "TensorFlow", "Keras", "XGBoost", "LightGBM", "Pandas", "NumPy"],
    "ml": ["scikit-learn", "PyTorch", "TensorFlow", "Keras", "XGBoost", "LightGBM"],
    "deep learning": ["PyTorch", "TensorFlow", "Keras", "HuggingFace Transformers"],
    "ai": ["OpenAI", "Anthropic", "LangChain", "LlamaIndex", "HuggingFace Transformers", "PyTorch", "TensorFlow"],
    "llm": ["OpenAI", "Anthropic", "LangChain", "LlamaIndex", "HuggingFace Transformers"],
    "data science": ["Pandas", "NumPy", "Matplotlib", "Seaborn", "Plotly", "scikit-learn"],
    "backend": ["FastAPI", "Django", "Flask", "Express", "Fastify", "NestJS", "Starlette"],
    "frontend": ["React", "Next.js", "Vue", "Angular", "Svelte", "Tailwind CSS", "Storybook"],
    "fullstack": ["React", "Next.js", "FastAPI", "Django", "Express", "NestJS"],
    "database": ["SQLAlchemy", "Prisma", "Drizzle ORM", "Supabase", "MongoDB", "Redis"],
    "sql": ["SQLAlchemy", "Prisma", "Drizzle ORM", "Alembic"],
    "docker": ["Docker"],
    "devops": ["Docker", "AWS", "Google Cloud", "Azure"],
    "aws": ["AWS"],
    "cloud": ["AWS", "Google Cloud", "Azure", "Supabase", "Firebase"],
    "testing": ["pytest", "Jest", "Vitest", "Playwright", "Cypress", "Hypothesis"],
    "graphql": ["GraphQL", "Apollo"],
    "redis": ["Redis"],
    "mongodb": ["MongoDB"],
    "supabase": ["Supabase"],
    "stripe": ["Stripe"],
    "openai": ["OpenAI"],
    "pytorch": ["PyTorch"],
    "tensorflow": ["TensorFlow"],
    "tailwind": ["Tailwind CSS"],
    "tailwindcss": ["Tailwind CSS"],
    "prisma": ["Prisma"],
}

# Files to fetch from the repo root and common subdirectory locations
_FILES_TO_PROBE = [
    "README.md",
    "requirements.txt",
    "package.json",
    "pyproject.toml",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    ".env.example",
    "Makefile",
    "frontend/package.json",
    "client/package.json",
]

# ── Context-aware skill matching helpers ─────────────────────────────────────

# ML stack tech terms (lowercase) used to confirm domain skills
_ML_STACK_TERMS_LOWER = frozenset({
    "scikit-learn", "pytorch", "tensorflow", "keras", "xgboost", "lightgbm",
})

# Domain skills that can be matched from page title / proof objective + ML stack
# "strong" keywords → matched when ML stack present; "weak" keywords → weakly matched
_DOMAIN_RISK_SKILLS: dict[str, dict[str, list[str]]] = {
    "route risk prediction": {
        "title_keywords": ["route risk", "accident risk", "risk predictor", "risk prediction", "route predictor"],
        "readme_keywords": ["route risk", "accident risk", "risk prediction", "rerouting", "route", "accident", "prediction"],
    },
    "route risk": {
        "title_keywords": ["route risk", "accident risk"],
        "readme_keywords": ["route risk", "accident risk", "route", "risk"],
    },
    "accident risk prediction": {
        "title_keywords": ["accident risk", "route risk", "risk predictor"],
        "readme_keywords": ["accident risk", "route risk", "accident", "prediction"],
    },
}

# Fallback README keywords for skills not specially handled above
# Provides weak evidence when the skill isn't found in detected_stack
_README_WEAK_SKILLS: dict[str, list[str]] = {
    "react": ["react", "jsx", "reactjs", "create-react-app"],
    "vue": ["vue.js", "vuejs", "vue 3", "vue 2"],
    "angular": ["angular", "angularjs"],
    "svelte": ["svelte", "sveltekit"],
    "google cloud": ["google cloud", "gcp", "gcloud", "cloud storage", "bigquery"],
}

# Live URL substring patterns that weakly support a skill
_LIVE_URL_WEAK_SKILLS: dict[str, list[str]] = {
    "google cloud run": ["run.app", "appspot.com"],
    "cloud run": ["run.app", "appspot.com"],
    "google cloud": ["run.app", "appspot.com"],
}


# ── Pure analysis function ────────────────────────────────────────────────────

def analyze_github_repo(
    repo_url: str,
    claimed_skills: list[str],
    live_website_url: str = "",
    live_page_title: str = "",
    proof_objective: str = "",
) -> dict[str, Any]:
    """Probe a public GitHub repo and return an analysis result dict."""

    now = datetime.now(timezone.utc).isoformat()

    # Normalise: split comma-separated skill strings so "FastAPI, React" → two entries.
    normalized: list[str] = []
    for s in (claimed_skills or []):
        normalized.extend(part.strip() for part in s.split(",") if part.strip())
    claimed_skills = normalized

    repo_ref = parse_github_repo_url(repo_url)
    if repo_ref is None:
        return {
            "repo_url": repo_url,
            "status": "failed",
            "detected_stack": [],
            "detected_features": [],
            "matched_claimed_skills": [],
            "weakly_matched_claimed_skills": [],
            "missing_claimed_skills": list(claimed_skills),
            "evidence_files": [],
            "confidence_score": 0.0,
            "warnings": ["Could not parse GitHub URL. Ensure it is a valid github.com link."],
            "recruiter_summary": "Repository URL could not be parsed.",
            "created_at": now,
        }

    # Normalise to base repo URL (strip branch/blob/file paths).
    normalized_repo_url = f"https://github.com/{repo_ref.owner}/{repo_ref.repo}"

    fetched: dict[str, str | None] = {}
    for file_path in _FILES_TO_PROBE:
        result = fetch_public_github_file(normalized_repo_url, file_path)
        if result.ok and result.content:
            fetched[file_path] = result.content
        elif result.status_code and result.status_code == 404:
            fetched[file_path] = None
        else:
            fetched[file_path] = None

    accessible_files = [f for f, c in fetched.items() if c is not None]

    if not accessible_files:
        return {
            "repo_url": normalized_repo_url,
            "status": "private_or_unavailable",
            "detected_stack": [],
            "detected_features": [],
            "matched_claimed_skills": [],
            "weakly_matched_claimed_skills": [],
            "missing_claimed_skills": list(claimed_skills),
            "evidence_files": [],
            "confidence_score": 0.0,
            "warnings": ["Repository appears to be private or unavailable. No files could be fetched."],
            "recruiter_summary": "Repository is private or unavailable.",
            "created_at": now,
        }

    detected_stack = _detect_stack(fetched)
    detected_features = _detect_features(fetched, detected_stack)
    matched, weakly, missing = _match_skills(
        claimed_skills,
        detected_stack,
        detected_features=detected_features,
        fetched_files=fetched,
        live_website_url=live_website_url,
        live_page_title=live_page_title,
        proof_objective=proof_objective,
    )
    confidence = _compute_confidence(accessible_files, detected_stack, matched, claimed_skills, weakly)
    warnings = _build_warnings(accessible_files, detected_stack, matched, claimed_skills, weakly)
    summary = _build_summary(
        normalized_repo_url, detected_stack, detected_features,
        matched, missing, confidence, weakly,
    )

    return {
        "repo_url": normalized_repo_url,
        "status": "success",
        "detected_stack": detected_stack,
        "detected_features": detected_features,
        "matched_claimed_skills": matched,
        "weakly_matched_claimed_skills": weakly,
        "missing_claimed_skills": missing,
        "evidence_files": accessible_files,
        "confidence_score": round(confidence, 3),
        "warnings": warnings,
        "recruiter_summary": summary,
        "created_at": now,
    }


# ── Detection helpers ─────────────────────────────────────────────────────────

def _parse_package_json_deps(pkg_content: str, stack: set[str]) -> None:
    """Parse a package.json string and add detected techs to stack in-place."""
    stack.add("JavaScript")
    try:
        data = json.loads(pkg_content)
        all_deps: dict[str, str] = {}
        all_deps.update(data.get("dependencies", {}))
        all_deps.update(data.get("devDependencies", {}))
        dep_str = " ".join(all_deps.keys()).lower()
        for keyword, tech in _NPM_STACK.items():
            if keyword in dep_str:
                stack.add(tech)
        if "typescript" in dep_str or pkg_content.lower().find('"ts"') >= 0:
            stack.add("TypeScript")
    except (json.JSONDecodeError, AttributeError):
        pass


def _detect_stack(fetched: dict[str, str | None]) -> list[str]:
    stack: set[str] = set()

    reqs = fetched.get("requirements.txt")
    if reqs:
        reqs_lower = reqs.lower()
        for keyword, tech in _REQS_STACK.items():
            if keyword in reqs_lower:
                stack.add(tech)
        stack.add("Python")

    pyproject = fetched.get("pyproject.toml")
    if pyproject:
        pyproject_lower = pyproject.lower()
        for keyword, tech in _REQS_STACK.items():
            if keyword in pyproject_lower:
                stack.add(tech)
        if not any(t == "Python" for t in stack):
            stack.add("Python")

    # Parse package.json from root and common frontend subdirectories
    for pkg_key in ("package.json", "frontend/package.json", "client/package.json"):
        pkg = fetched.get(pkg_key)
        if pkg:
            _parse_package_json_deps(pkg, stack)

    if fetched.get("Dockerfile"):
        stack.add("Docker")
    if fetched.get("docker-compose.yml") or fetched.get("docker-compose.yaml"):
        stack.add("Docker Compose")

    return sorted(stack)


def _detect_features(fetched: dict[str, str | None], stack: list[str]) -> list[str]:
    features: list[str] = []

    if fetched.get("README.md"):
        features.append("readme")

    if fetched.get("Dockerfile"):
        features.append("docker")

    if fetched.get("docker-compose.yml") or fetched.get("docker-compose.yaml"):
        features.append("docker_compose")

    if fetched.get(".env.example"):
        features.append("env_config")

    if fetched.get("Makefile"):
        features.append("makefile")

    reqs_content = fetched.get("requirements.txt", "") or ""
    npm_content = fetched.get("package.json", "") or ""
    if "pytest" in reqs_content.lower() or any(t in npm_content.lower() for t in ("jest", "vitest", "playwright", "cypress")):
        features.append("testing")

    ml_techs = {"scikit-learn", "PyTorch", "TensorFlow", "Keras", "XGBoost", "LightGBM"}
    if any(t in stack for t in ml_techs):
        features.append("machine_learning")

    llm_techs = {"OpenAI", "Anthropic", "LangChain", "LlamaIndex", "HuggingFace Transformers"}
    if any(t in stack for t in llm_techs):
        features.append("ai_llm")

    api_techs = {"FastAPI", "Django", "Flask", "Starlette", "Express", "Fastify", "NestJS", "Koa"}
    if any(t in stack for t in api_techs):
        features.append("api_framework")

    db_techs = {"SQLAlchemy", "Prisma", "Drizzle ORM", "Supabase", "MongoDB", "Redis", "Alembic"}
    if any(t in stack for t in db_techs):
        features.append("database")

    if fetched.get("Dockerfile"):
        features.append("deployment")

    return features


def _match_skills(
    claimed_skills: list[str],
    detected_stack: list[str],
    detected_features: list[str] | None = None,
    fetched_files: dict[str, str | None] | None = None,
    live_website_url: str = "",
    live_page_title: str = "",
    proof_objective: str = "",
) -> tuple[list[str], list[str], list[str]]:
    """Return (matched, weakly_matched, missing) for each claimed skill.

    matched      — confirmed by dependency files (strongest evidence)
    weakly_matched — suggested by README text, live URL, page title, or deployment context
    missing      — no evidence found in any source
    """
    if not claimed_skills:
        return [], [], []

    stack_lower = {t.lower() for t in detected_stack}
    features_set = set(detected_features or [])
    readme = ((fetched_files or {}).get("README.md") or "").lower()
    url_lower = (live_website_url or "").lower()
    context_lower = (live_page_title or "").lower() + " " + (proof_objective or "").lower()

    matched: list[str] = []
    weakly: list[str] = []
    missing: list[str] = []

    for skill in claimed_skills:
        sk = skill.lower().strip()
        aliases = _SKILL_ALIASES.get(sk, [skill])

        # 1. Direct stack match — dependency files confirmed
        if any(a.lower() in stack_lower for a in aliases) or sk in stack_lower:
            matched.append(skill)
            continue

        # 2. Domain skill: route / accident risk prediction
        #    Full match when page title/objective confirms it AND ML stack is present.
        #    Weak match when README mentions relevant domain terms.
        if sk in _DOMAIN_RISK_SKILLS:
            spec = _DOMAIN_RISK_SKILLS[sk]
            has_ml = bool(stack_lower & _ML_STACK_TERMS_LOWER)
            title_hit = any(kw in context_lower for kw in spec["title_keywords"])
            readme_hit = any(kw in readme for kw in spec["readme_keywords"])
            if title_hit and has_ml:
                matched.append(skill)
            elif title_hit or (readme_hit and has_ml):
                weakly.append(skill)
            elif readme_hit:
                weakly.append(skill)
            else:
                missing.append(skill)
            continue

        # 3. Google Cloud Run — weakly supported from deployment context
        if sk in ("google cloud run", "cloud run"):
            has_gcloud = "google cloud" in stack_lower
            has_docker = bool({"docker", "docker compose"} & stack_lower)
            has_deploy = "deployment" in features_set
            url_hit = any(p in url_lower for p in ("run.app", "appspot.com"))
            readme_hit = any(
                kw in readme
                for kw in ("cloud run", "google cloud", "gcp", "gcloud", "container registry", "cloud build")
            )
            if (has_gcloud or readme_hit) and (has_docker or has_deploy or url_hit):
                weakly.append(skill)
            elif url_hit or readme_hit:
                weakly.append(skill)
            else:
                missing.append(skill)
            continue

        # 4. Google Maps API — weakly supported from README mentions
        if sk in ("google maps api", "google maps", "maps api"):
            readme_hit = any(
                kw in readme
                for kw in ("google maps", "maps api", "geocod", "gmaps", "directions api", "places api", "maps javascript")
            )
            if readme_hit:
                weakly.append(skill)
            else:
                missing.append(skill)
            continue

        # 5. Generic README keyword weak match
        readme_kws = _README_WEAK_SKILLS.get(sk)
        if readme_kws and any(kw in readme for kw in readme_kws):
            weakly.append(skill)
            continue

        # 6. Live URL weak match
        url_patterns = _LIVE_URL_WEAK_SKILLS.get(sk)
        if url_patterns and any(p in url_lower for p in url_patterns):
            weakly.append(skill)
            continue

        missing.append(skill)

    return matched, weakly, missing


def _compute_confidence(
    accessible_files: list[str],
    detected_stack: list[str],
    matched_skills: list[str],
    claimed_skills: list[str],
    weakly_matched_skills: list[str] | None = None,
) -> float:
    score = 0.25  # base for accessible repo

    # file richness: up to 0.20
    score += min(len(accessible_files) * 0.04, 0.20)

    # skill match ratio: up to 0.45 (weakly matched count at half weight)
    if claimed_skills:
        full_count = len(matched_skills)
        weak_count = len(weakly_matched_skills or [])
        effective = full_count + weak_count * 0.5
        match_ratio = min(effective / len(claimed_skills), 1.0)
        score += match_ratio * 0.45

    # bonus for having key indicator files
    if "README.md" in accessible_files:
        score += 0.04
    if any(f in accessible_files for f in ("requirements.txt", "package.json", "pyproject.toml")):
        score += 0.04
    if "Dockerfile" in accessible_files:
        score += 0.02

    return min(score, 0.95)


def _build_warnings(
    accessible_files: list[str],
    detected_stack: list[str],
    matched_skills: list[str],
    claimed_skills: list[str],
    weakly_matched_skills: list[str] | None = None,
) -> list[str]:
    warnings: list[str] = []

    if not detected_stack:
        warnings.append("No recognizable tech stack detected. Repo may use unrecognized tools or have minimal dependency files.")

    if claimed_skills and not matched_skills and not (weakly_matched_skills or []):
        warnings.append("None of the claimed skills were detected in the repository. Verify the repo matches the claimed work.")

    if "README.md" not in accessible_files:
        warnings.append("No README.md found. Adding documentation would improve recruiter visibility.")

    if not any(f in accessible_files for f in ("requirements.txt", "package.json", "pyproject.toml")):
        warnings.append("No dependency file found (requirements.txt, package.json, or pyproject.toml). Stack detection may be incomplete.")

    return warnings


def _build_summary(
    repo_url: str,
    detected_stack: list[str],
    detected_features: list[str],
    matched_skills: list[str],
    missing_skills: list[str],
    confidence: float,
    weakly_matched_skills: list[str] | None = None,
) -> str:
    parts: list[str] = []
    weakly = weakly_matched_skills or []

    if detected_stack:
        stack_str = ", ".join(detected_stack[:6])
        if len(detected_stack) > 6:
            stack_str += f" and {len(detected_stack) - 6} more"
        parts.append(f"This repository demonstrates use of {stack_str}.")
    else:
        parts.append("No recognizable tech stack was detected in this repository.")

    feature_labels = {
        "docker": "Docker containerisation",
        "docker_compose": "Docker Compose orchestration",
        "testing": "automated testing",
        "machine_learning": "machine learning",
        "ai_llm": "AI/LLM integration",
        "api_framework": "a web API framework",
        "database": "database integration",
        "env_config": "environment configuration",
        "deployment": "deployment configuration",
    }
    notable = [feature_labels[f] for f in detected_features if f in feature_labels]
    if notable:
        if len(notable) == 1:
            parts.append(f"The codebase includes {notable[0]}.")
        else:
            parts.append(f"The codebase includes {', '.join(notable[:-1])}, and {notable[-1]}.")

    total = len(matched_skills) + len(weakly) + len(missing_skills)

    if matched_skills and weakly and missing_skills:
        parts.append(
            f"{len(matched_skills)} of {total} claimed skills were directly verified "
            f"({', '.join(matched_skills)}). "
            f"{len(weakly)} had partial or contextual evidence: {', '.join(weakly)}. "
            f"Missing evidence for: {', '.join(missing_skills)}."
        )
    elif matched_skills and weakly:
        parts.append(
            f"{len(matched_skills)} of {total} claimed skills were directly verified "
            f"({', '.join(matched_skills)}). "
            f"{len(weakly)} had partial or contextual evidence: {', '.join(weakly)}."
        )
    elif matched_skills and missing_skills:
        parts.append(
            f"{len(matched_skills)} of {total} claimed skills were verified "
            f"({', '.join(matched_skills)}). "
            f"Missing evidence for: {', '.join(missing_skills)}."
        )
    elif matched_skills:
        parts.append(f"All claimed skills were verified: {', '.join(matched_skills)}.")
    elif weakly and missing_skills:
        parts.append(
            f"No claimed skills were directly verified from dependency files. "
            f"{len(weakly)} had partial contextual evidence: {', '.join(weakly)}. "
            f"Missing evidence for: {', '.join(missing_skills)}."
        )
    elif weakly:
        parts.append(
            f"No claimed skills were directly verified, but {len(weakly)} had partial or contextual evidence: {', '.join(weakly)}."
        )
    elif missing_skills:
        parts.append("No claimed skills could be verified from the repository contents.")

    confidence_pct = int(confidence * 100)
    parts.append(f"Overall confidence: {confidence_pct}%.")

    return " ".join(parts)


# ── Service class ─────────────────────────────────────────────────────────────

class ExtensionProofGitHubAnalysisService:
    def __init__(self, db: Any) -> None:
        self._client = db

    def run_analysis(
        self,
        user_id: str,
        session_id: str,
        github_url: str,
        claimed_skills: list[str],
        live_website_url: str = "",
        live_page_title: str = "",
        proof_objective: str = "",
    ) -> dict[str, Any]:
        result = analyze_github_repo(
            github_url,
            claimed_skills,
            live_website_url=live_website_url,
            live_page_title=live_page_title,
            proof_objective=proof_objective,
        )
        result["proof_session_id"] = session_id
        return self._store_result(user_id, session_id, result)

    def get_latest(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            store = self._client.setdefault("extension_proof_github_analysis", {})
            return store.get(session_id)

        try:
            resp = (
                self._client
                .table("extension_proof_github_analysis")
                .select("*")
                .eq("proof_session_id", session_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            if not rows:
                return None
            row = rows[0]
            return self._normalize_row(row)
        except Exception:
            logger.exception("get_latest: failed to query extension_proof_github_analysis")
            return None

    def _store_result(self, user_id: str, session_id: str, result: dict[str, Any]) -> dict[str, Any]:
        if isinstance(self._client, dict):
            store = self._client.setdefault("extension_proof_github_analysis", {})
            row = {
                "id": str(uuid4()),
                **result,
                "user_id": user_id,
            }
            store[session_id] = row
            return row

        try:
            now = datetime.now(timezone.utc).isoformat()
            payload = {
                "proof_session_id": session_id,
                "user_id": user_id,
                "repo_url": result["repo_url"],
                "status": result["status"],
                "detected_stack": result["detected_stack"],
                "detected_features": result["detected_features"],
                "matched_claimed_skills": result["matched_claimed_skills"],
                "weakly_matched_claimed_skills": result.get("weakly_matched_claimed_skills", []),
                "missing_claimed_skills": result["missing_claimed_skills"],
                "evidence_files": result["evidence_files"],
                "confidence_score": result["confidence_score"],
                "warnings": result["warnings"],
                "recruiter_summary": result["recruiter_summary"],
                "created_at": result.get("created_at", now),
                "updated_at": now,
            }
            resp = (
                self._client
                .table("extension_proof_github_analysis")
                .upsert(payload, on_conflict="proof_session_id")
                .execute()
            )
            rows = resp.data or []
            if rows:
                return self._normalize_row(rows[0])
            return {**result, "id": "", "user_id": user_id}
        except Exception:
            logger.exception("_store_result: failed to upsert extension_proof_github_analysis")
            return {**result, "id": str(uuid4()), "user_id": user_id}

    @staticmethod
    def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
        for list_col in (
            "detected_stack",
            "detected_features",
            "matched_claimed_skills",
            "weakly_matched_claimed_skills",
            "missing_claimed_skills",
            "evidence_files",
            "warnings",
        ):
            val = row.get(list_col)
            if isinstance(val, str):
                try:
                    row[list_col] = json.loads(val)
                except json.JSONDecodeError:
                    row[list_col] = []
            elif val is None:
                row[list_col] = []
        return row
