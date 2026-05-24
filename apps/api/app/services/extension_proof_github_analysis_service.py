"""Extension Proof GitHub Analysis Service.

Probes a public GitHub repository to detect the tech stack, match
claimed skills, compute a confidence score, and build a recruiter summary.
No authentication token is required — public repos only.
"""

from __future__ import annotations

import json
import logging
import re
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
    "streamlit": "Streamlit",
    "gradio": "Gradio",
    "dash": "Plotly Dash",
    "shiny": "R Shiny",
    "r-shiny": "R Shiny",
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

# normalized skill label → stack tech terms that count as matching
_SKILL_ALIASES: dict[str, list[str]] = {
    "python": ["FastAPI", "Django", "Flask", "Starlette", "aiohttp", "Pandas", "NumPy", "scikit-learn", "PyTorch", "TensorFlow", "Keras"],
    "javascript": ["React", "Next.js", "Vue", "Angular", "Express", "Fastify", "NestJS", "Socket.IO", "JavaScript"],
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
    "gcp": ["Google Cloud"],
    "google cloud": ["Google Cloud"],
    "google cloud platform": ["Google Cloud"],
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
    # ML/AI demo frameworks
    "streamlit": ["Streamlit"],
    "gradio": ["Gradio"],
    "hugging face": ["HuggingFace Transformers"],
    "huggingface": ["HuggingFace Transformers"],
    "hf": ["HuggingFace Transformers"],
    "plotly dash": ["Plotly Dash"],
    "dash": ["Plotly Dash"],
    # Data viz and analysis
    "plotly": ["Plotly"],
    "matplotlib": ["Matplotlib"],
    "seaborn": ["Seaborn"],
    "data visualization": ["Plotly", "Matplotlib", "Seaborn", "Plotly Dash"],
    "visualization": ["Plotly", "Matplotlib", "Seaborn"],
    "data analysis": ["Pandas", "NumPy", "Matplotlib", "Seaborn"],
    "jupyter": ["Pandas", "NumPy"],
    "jupyter notebook": ["Pandas", "NumPy"],
    # Frontend / build tools
    "vite": ["Vite"],
    "webpack": ["Webpack"],
    "html": ["HTML"],
    "css": ["CSS", "Tailwind CSS"],
    "expressjs": ["Express"],
    "nestjs": ["NestJS"],
}

# Files fetched from repo root and common frontend subdirectory locations
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
    "index.html",
    "app.py",
]

# ── Generic deployment platform matching ─────────────────────────────────────
#
# Each entry describes a hosting / cloud platform. A skill is "weakly matched"
# when ANY of: live URL contains a known pattern, README mentions a platform
# keyword, OR a stack indicator is detected AND deployment config is present.
#
# skill_names    — lowercase claim variants that map to this platform
# url_patterns   — substrings of the live URL that identify this platform
# readme_keywords — text substrings in the README that suggest this platform
# stack_indicators — detected_stack items that corroborate the platform claim

_DEPLOYMENT_PLATFORMS: list[dict[str, Any]] = [
    {
        "skill_names": {"google cloud run", "cloud run", "gcp cloud run"},
        "url_patterns": ["run.app", "appspot.com"],
        "readme_keywords": ["cloud run", "gcp", "gcloud", "google cloud", "container registry", "cloud build"],
        "stack_indicators": ["Google Cloud", "Docker"],
    },
    {
        "skill_names": {"google cloud", "gcp", "google cloud platform"},
        "url_patterns": ["run.app", "appspot.com", ".firebaseapp.com", ".web.app"],
        "readme_keywords": ["google cloud", "gcp", "gcloud", "bigquery", "cloud storage", "cloud sql", "cloud build"],
        "stack_indicators": ["Google Cloud"],
    },
    {
        "skill_names": {
            "aws", "amazon web services", "aws ecs", "aws ec2",
            "elastic beanstalk", "aws app runner", "aws lambda", "aws fargate",
        },
        "url_patterns": ["elasticbeanstalk.com", "apprunner.awsapps.com", ".amazonaws.com"],
        "readme_keywords": [
            "aws", "amazon web services", "ec2", "ecs", "elastic beanstalk",
            "app runner", "lambda", "cloudformation", "cdk", "fargate",
        ],
        "stack_indicators": ["AWS"],
    },
    {
        "skill_names": {
            "azure", "microsoft azure", "azure container apps",
            "azure app service", "azure kubernetes service", "aks",
        },
        "url_patterns": ["azurewebsites.net", "azurecontainerapps.io"],
        "readme_keywords": [
            "azure", "azure container apps", "azure app service",
            "aks", "acr", "azure functions", "bicep",
        ],
        "stack_indicators": ["Azure"],
    },
    {
        "skill_names": {"vercel"},
        "url_patterns": ["vercel.app", ".vercel.app"],
        "readme_keywords": ["vercel", "deploy to vercel", "deployed on vercel", "vercel deployment"],
        "stack_indicators": ["Next.js"],
    },
    {
        "skill_names": {"render", "render.com"},
        "url_patterns": ["onrender.com"],
        "readme_keywords": ["render.com", "onrender.com", "deploy on render", "deployed on render"],
        "stack_indicators": [],
    },
    {
        "skill_names": {"railway", "railway.app"},
        "url_patterns": ["railway.app", ".railway.app", "up.railway.app"],
        "readme_keywords": ["railway.app", "deploy on railway", "deployed on railway"],
        "stack_indicators": [],
    },
    {
        "skill_names": {"heroku"},
        "url_patterns": ["herokuapp.com"],
        "readme_keywords": ["heroku", "deployed on heroku", "procfile"],
        "stack_indicators": [],
    },
    {
        "skill_names": {"netlify"},
        "url_patterns": ["netlify.app", ".netlify.app"],
        "readme_keywords": ["netlify", "deployed on netlify", "netlify deployment"],
        "stack_indicators": [],
    },
    {
        "skill_names": {"fly.io", "fly", "flyio"},
        "url_patterns": [".fly.dev"],
        "readme_keywords": ["fly.io", "flyctl", "fly deploy"],
        "stack_indicators": [],
    },
    {
        "skill_names": {"digitalocean", "digital ocean", "digitalocean app platform"},
        "url_patterns": ["ondigitalocean.app", ".digitalocean.com"],
        "readme_keywords": ["digitalocean", "digital ocean", "doctl"],
        "stack_indicators": [],
    },
    {
        "skill_names": {"hugging face spaces", "hf spaces", "huggingface spaces"},
        "url_patterns": [".hf.space", "huggingface.co/spaces"],
        "readme_keywords": [
            "hugging face spaces", "hf spaces", "spaces.huggingface.co",
            "deployed on hugging face", "deploy to hugging face",
        ],
        "stack_indicators": ["HuggingFace Transformers", "Gradio"],
    },
    {
        "skill_names": {"streamlit cloud", "streamlit community cloud", "streamlit sharing"},
        "url_patterns": ["streamlit.app", ".streamlit.app"],
        "readme_keywords": ["streamlit cloud", "streamlit sharing", "streamlit.app", "share.streamlit.io"],
        "stack_indicators": ["Streamlit"],
    },
    {
        "skill_names": {"github pages"},
        "url_patterns": [".github.io"],
        "readme_keywords": ["github pages", "github.io", "deploy to github pages", "github-pages"],
        "stack_indicators": ["HTML"],
    },
]

# ── Frontend framework partial matching ───────────────────────────────────────
#
# When a student claims a frontend framework but it is not in the detected
# stack (no package.json or no framework dependency found), and a live website
# URL was recorded, we treat this as partial evidence: the live UI was
# observed but source files were not confirmed.

_FRONTEND_FRAMEWORK_SKILLS = frozenset({
    "react", "vue", "angular", "svelte", "solid", "solidjs",
    "next.js", "nextjs", "remix", "astro", "sveltekit",
    "nuxt", "nuxt.js", "nuxtjs", "gatsby",
})

# ── Generic domain-skill matching ─────────────────────────────────────────────
#
# For skills that are neither in the stack nor a known deployment platform
# nor a frontend framework, we extract significant terms from the claimed
# skill name and check whether those terms appear in the aggregated project
# context (README + page title + proof objective).
#
# This approach is project-agnostic: it works for any domain skill
# (e.g. "Product Recommendation", "Traffic Flow Analysis", "Fraud Detection")
# as long as the claimed terms appear in the available text signals.

_STOPWORDS = frozenset({
    # Common English connectors
    "and", "or", "the", "a", "an", "for", "with", "using",
    "based", "in", "on", "of", "to", "via", "from", "by",
    "that", "this", "as", "at",
    # Generic tech suffixes that carry no signal on their own
    "api", "sdk", "app",
})


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

    # Split comma-separated skill strings so "FastAPI, React" → two entries.
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

    normalized_repo_url = f"https://github.com/{repo_ref.owner}/{repo_ref.repo}"

    fetched: dict[str, str | None] = {}
    for file_path in _FILES_TO_PROBE:
        result = fetch_public_github_file(normalized_repo_url, file_path)
        if result.ok and result.content:
            fetched[file_path] = result.content
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


# ── Stack detection ───────────────────────────────────────────────────────────

def _parse_package_json_deps(pkg_content: str, stack: set[str]) -> None:
    """Parse a package.json string and add detected techs into stack in-place."""
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

    if fetched.get("index.html"):
        stack.add("HTML")
        stack.add("CSS")
        stack.add("JavaScript")  # almost always co-present with a plain HTML site

    app_py = fetched.get("app.py")
    if app_py:
        app_py_lower = app_py.lower()
        if "import streamlit" in app_py_lower or "from streamlit" in app_py_lower:
            stack.add("Streamlit")
            stack.add("Python")
        if "import gradio" in app_py_lower or "from gradio" in app_py_lower:
            stack.add("Gradio")
            stack.add("Python")
        if not any(t == "Python" for t in stack) and (
            "import flask" in app_py_lower or "import fastapi" in app_py_lower
            or "from flask" in app_py_lower or "from fastapi" in app_py_lower
        ):
            stack.add("Python")

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

    # ML demo / interactive app frameworks
    if "Streamlit" in stack:
        features.append("streamlit_app")
    if "Gradio" in stack:
        features.append("gradio_app")

    # Data visualisation projects
    viz_techs = {"Plotly", "Matplotlib", "Seaborn", "Plotly Dash"}
    if any(t in stack for t in viz_techs):
        features.append("data_visualization")

    # Plain HTML/CSS/JS site (no Node or Python build system)
    if "HTML" in stack:
        features.append("html_frontend")

    return features


# ── Skill matching ─────────────────────────────────────────────────────────────

def _extract_significant_terms(skill: str) -> list[str]:
    """Split a skill name into meaningful tokens, removing stopwords and punctuation."""
    tokens = re.sub(r"[^a-z0-9\s]", "", skill.lower()).split()
    return [t for t in tokens if t not in _STOPWORDS and len(t) >= 3]


def _term_in_text(term: str, text: str) -> bool:
    """Return True if term appears as a whole word in text."""
    return bool(re.search(r"\b" + re.escape(term) + r"\b", text))


def _match_deployment_skill(
    sk: str,
    stack_lower: set[str],
    features_set: set[str],
    readme: str,
    url_lower: str,
) -> str | None:
    """Check if sk is a known deployment platform and whether evidence exists.

    Returns:
        "weakly"  — platform claim has supporting evidence
        "missing" — known platform but no evidence found
        None      — not a deployment platform claim at all
    """
    for platform in _DEPLOYMENT_PLATFORMS:
        if sk not in platform["skill_names"]:
            continue

        url_hit = any(p in url_lower for p in platform["url_patterns"])
        readme_hit = any(kw in readme for kw in platform["readme_keywords"])
        stack_hit = any(si.lower() in stack_lower for si in platform["stack_indicators"])
        has_deploy_config = "deployment" in features_set or "docker" in features_set

        # Any of: live URL confirms platform, README mentions it,
        # or relevant stack is detected alongside a deployment config.
        if url_hit or readme_hit or (stack_hit and has_deploy_config):
            return "weakly"
        return "missing"

    return None


def _match_domain_skill(sk: str, context_text: str) -> str:
    """Generic domain-skill matching by term overlap with project context.

    Extracts significant terms from the claimed skill name and checks whether
    they appear as whole words in the combined project context (README +
    page title + proof objective).

    Returns "weakly" when enough terms match, "missing" otherwise.
    This function is intentionally project-agnostic.
    """
    terms = _extract_significant_terms(sk)
    if not terms:
        return "missing"

    if len(terms) == 1:
        # Single-term skills need the term to be substantive (≥ 4 chars)
        # and appear literally in the context.
        term = terms[0]
        if len(term) < 4:
            return "missing"
        return "weakly" if _term_in_text(term, context_text) else "missing"

    # Multi-term skills: require at least 2 matching terms (covers ≥ 50% for
    # 2-word skills, ≥ 50% for longer ones).  Prevents single common-word hits
    # from producing false positives.
    hits = sum(1 for term in terms if _term_in_text(term, context_text))
    required = min(2, len(terms))
    return "weakly" if hits >= required else "missing"


def _match_skills(
    claimed_skills: list[str],
    detected_stack: list[str],
    detected_features: list[str] | None = None,
    fetched_files: dict[str, str | None] | None = None,
    live_website_url: str = "",
    live_page_title: str = "",
    proof_objective: str = "",
) -> tuple[list[str], list[str], list[str]]:
    """Classify each claimed skill into one of three tiers.

    matched        — confirmed by dependency files (strongest, file-based evidence)
    weakly_matched — supported by deployment signals, live URL, README text,
                     page title, proof objective, or observed live frontend
    missing        — no evidence found in any source

    The matching pipeline is entirely project-agnostic:
    1. Direct stack match via _SKILL_ALIASES + detected_stack
    2. Deployment platform match (generic cloud/hosting patterns)
    3. Frontend framework partial match (live site observed, no source evidence)
    4. Generic domain-skill matching (claimed terms in project context)
    """
    if not claimed_skills:
        return [], [], []

    stack_lower = {t.lower() for t in detected_stack}
    features_set = set(detected_features or [])
    readme = ((fetched_files or {}).get("README.md") or "").lower()
    url_lower = (live_website_url or "").lower()

    # Aggregate context for domain-skill matching (README + page title + objective)
    context_text = (
        readme + " "
        + (live_page_title or "").lower() + " "
        + (proof_objective or "").lower()
    )

    matched: list[str] = []
    weakly: list[str] = []
    missing: list[str] = []

    for skill in claimed_skills:
        sk = skill.lower().strip()
        aliases = _SKILL_ALIASES.get(sk, [skill])

        # ── Step 1: Direct stack match (dependency files) ─────────────────────
        if any(a.lower() in stack_lower for a in aliases) or sk in stack_lower:
            matched.append(skill)
            continue

        # ── Step 2: Deployment platform (generic cloud / hosting) ─────────────
        deploy_result = _match_deployment_skill(sk, stack_lower, features_set, readme, url_lower)
        if deploy_result == "weakly":
            weakly.append(skill)
            continue
        elif deploy_result == "missing":
            # Recognised as a deployment claim but no evidence found
            missing.append(skill)
            continue

        # ── Step 3: Frontend framework — live UI without source evidence ───────
        # React/Vue/Angular etc. require source files for a full match.
        # If a live website was recorded but no framework files were found,
        # mark as partial: "live UI observed, but source not confirmed."
        if sk in _FRONTEND_FRAMEWORK_SKILLS:
            if live_website_url:
                weakly.append(skill)
            else:
                # No live URL either — fall back to generic domain matching
                # (handles the case where README describes the framework)
                if _match_domain_skill(sk, context_text) == "weakly":
                    weakly.append(skill)
                else:
                    missing.append(skill)
            continue

        # ── Step 4: Generic domain-skill matching ─────────────────────────────
        # Compare claimed skill terms against aggregated project context.
        # Works for any domain skill without project-specific hardcoding.
        if _match_domain_skill(sk, context_text) == "weakly":
            weakly.append(skill)
            continue

        missing.append(skill)

    return matched, weakly, missing


# ── Scoring and reporting ─────────────────────────────────────────────────────

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

    # bonus for key indicator files
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
        # Plain HTML/CSS/JS sites legitimately have no dependency file
        if "HTML" not in detected_stack:
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
        "streamlit_app": "a Streamlit web application",
        "gradio_app": "a Gradio ML demo",
        "data_visualization": "data visualisation",
        "html_frontend": "a plain HTML/CSS/JS frontend",
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
            return self._normalize_row(rows[0])
        except Exception:
            logger.exception("get_latest: failed to query extension_proof_github_analysis")
            return None

    def _store_result(self, user_id: str, session_id: str, result: dict[str, Any]) -> dict[str, Any]:
        if isinstance(self._client, dict):
            store = self._client.setdefault("extension_proof_github_analysis", {})
            row = {"id": str(uuid4()), **result, "user_id": user_id}
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
