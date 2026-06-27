"""Skill normalization + categorization (small, deterministic, no LLM).

A student's proofs name the same skill many different ways — ``ml`` /
``machine learning`` / ``ML``; ``api`` / ``rest api`` / ``fastapi``. The Work
Passport groups proofs by skill, so without normalization the same real skill
splinters into several near-identical cards. This module collapses aliases to a
single canonical display name and assigns each skill a high-level category for
the Passport's category headings.

It is intentionally small — an alias table good enough for the proofs we have
today, plus a few keyword fallbacks — not a full skill ontology. The ORIGINAL
source skill label is always preserved by the caller for traceability; this
module only decides the *canonical grouping name* and *category*.
"""

from __future__ import annotations

import re

# ── Category labels (the Passport's category headings, in display order) ──────

CAT_AI_ML = "AI / Machine Learning"
CAT_GENAI = "GenAI / LLM"
CAT_MLOPS = "MLOps / Deployment"
CAT_BACKEND = "Backend / APIs"
CAT_FRONTEND = "Frontend"
CAT_DATA = "Data / Analytics"
CAT_DATABASE = "Database"
CAT_CLOUD = "Cloud / DevOps"
CAT_LANGUAGE = "Programming Language"
CAT_SECURITY = "Security / Privacy"
CAT_PRODUCT = "Product / System Design"
CAT_OTHER = "Other"

CATEGORY_ORDER = [
    CAT_AI_ML,
    CAT_GENAI,
    CAT_MLOPS,
    CAT_BACKEND,
    CAT_FRONTEND,
    CAT_DATA,
    CAT_DATABASE,
    CAT_CLOUD,
    CAT_LANGUAGE,
    CAT_SECURITY,
    CAT_PRODUCT,
    CAT_OTHER,
]


def _norm(value: str) -> str:
    """Lower-case, collapse separators — the alias-table lookup key."""
    return re.sub(r"[\s_\-/]+", " ", str(value or "").strip().lower())


# ── Alias table: normalized raw label → canonical display name ────────────────
# Keep entries lower-cased on the left (matched via ``_norm``). The right side is
# the canonical name shown on the skill card.

_ALIASES: dict[str, str] = {
    # AI / Machine Learning
    "ml": "Machine Learning",
    "machine learning": "Machine Learning",
    "deep learning": "Deep Learning",
    "dl": "Deep Learning",
    "neural networks": "Deep Learning",
    "computer vision": "Computer Vision",
    "cv": "Computer Vision",
    "nlp": "Natural Language Processing",
    "natural language processing": "Natural Language Processing",
    "ai": "Artificial Intelligence",
    "artificial intelligence": "Artificial Intelligence",
    "scikit learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "keras": "Keras",
    # GenAI / LLM
    "gen ai": "Generative AI",
    "genai": "Generative AI",
    "generative ai": "Generative AI",
    "llm": "Large Language Models",
    "llms": "Large Language Models",
    "large language models": "Large Language Models",
    "prompt engineering": "Prompt Engineering",
    "rag": "Retrieval-Augmented Generation",
    "retrieval augmented generation": "Retrieval-Augmented Generation",
    "langchain": "LangChain",
    "openai": "OpenAI API",
    "openai api": "OpenAI API",
    # MLOps / Deployment
    "mlops": "MLOps",
    "ml ops": "MLOps",
    "model deployment": "Model Deployment",
    "model serving": "Model Deployment",
    # Backend / APIs
    "api": "API Development",
    "apis": "API Development",
    "api development": "API Development",
    "rest api": "REST APIs",
    "rest apis": "REST APIs",
    "restful api": "REST APIs",
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "express": "Express.js",
    "express js": "Express.js",
    "node": "Node.js",
    "node js": "Node.js",
    "nodejs": "Node.js",
    "graphql": "GraphQL",
    "backend": "Backend Development",
    "backend development": "Backend Development",
    # Frontend
    "react": "React",
    "react js": "React",
    "reactjs": "React",
    "next": "Next.js",
    "next js": "Next.js",
    "nextjs": "Next.js",
    "vue": "Vue.js",
    "angular": "Angular",
    "frontend": "Frontend Development",
    "front end": "Frontend Development",
    "browser": "Frontend Development",
    "html": "HTML/CSS",
    "css": "HTML/CSS",
    "tailwind": "Tailwind CSS",
    "tailwind css": "Tailwind CSS",
    # Data / Analytics
    "data analysis": "Data Analysis",
    "data analytics": "Data Analysis",
    "data science": "Data Science",
    "pandas": "Pandas",
    "numpy": "NumPy",
    "data engineering": "Data Engineering",
    "etl": "Data Engineering",
    # Database
    "sql": "SQL",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "supabase": "Supabase",
    "mongodb": "MongoDB",
    "mongo": "MongoDB",
    "redis": "Redis",
    "database": "Databases",
    "databases": "Databases",
    # Cloud / DevOps
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "aws": "AWS",
    "gcp": "Google Cloud",
    "google cloud": "Google Cloud",
    "azure": "Azure",
    "cloud run": "Google Cloud Run",
    "vercel": "Vercel",
    "ci cd": "CI/CD",
    "cicd": "CI/CD",
    "github actions": "GitHub Actions",
    "deployment": "Deployment",
    "devops": "DevOps",
    # Programming Language
    "python": "Python",
    "javascript": "JavaScript",
    "js": "JavaScript",
    "typescript": "TypeScript",
    "ts": "TypeScript",
    "java": "Java",
    "c++": "C++",
    "cpp": "C++",
    "c#": "C#",
    "go": "Go",
    "golang": "Go",
    "rust": "Rust",
    "ruby": "Ruby",
    "php": "PHP",
    # Security / Privacy
    "security": "Security",
    "cybersecurity": "Security",
    "authentication": "Authentication",
    "auth": "Authentication",
    "privacy": "Privacy",
    "encryption": "Encryption",
    # Product / System Design
    "system design": "System Design",
    "product": "Product Design",
    "product design": "Product Design",
    "architecture": "Software Architecture",
    "software architecture": "Software Architecture",
}

# Canonical name (normalized) → category.
_CANONICAL_CATEGORY: dict[str, str] = {
    # AI / Machine Learning
    "machine learning": CAT_AI_ML,
    "deep learning": CAT_AI_ML,
    "computer vision": CAT_AI_ML,
    "natural language processing": CAT_AI_ML,
    "artificial intelligence": CAT_AI_ML,
    "scikit learn": CAT_AI_ML,
    "pytorch": CAT_AI_ML,
    "tensorflow": CAT_AI_ML,
    "keras": CAT_AI_ML,
    # GenAI / LLM
    "generative ai": CAT_GENAI,
    "large language models": CAT_GENAI,
    "prompt engineering": CAT_GENAI,
    "retrieval augmented generation": CAT_GENAI,
    "langchain": CAT_GENAI,
    "openai api": CAT_GENAI,
    # MLOps / Deployment
    "mlops": CAT_MLOPS,
    "model deployment": CAT_MLOPS,
    # Backend / APIs
    "api development": CAT_BACKEND,
    "rest apis": CAT_BACKEND,
    "fastapi": CAT_BACKEND,
    "flask": CAT_BACKEND,
    "django": CAT_BACKEND,
    "express js": CAT_BACKEND,
    "node js": CAT_BACKEND,
    "graphql": CAT_BACKEND,
    "backend development": CAT_BACKEND,
    # Frontend
    "react": CAT_FRONTEND,
    "next js": CAT_FRONTEND,
    "vue js": CAT_FRONTEND,
    "angular": CAT_FRONTEND,
    "frontend development": CAT_FRONTEND,
    "html css": CAT_FRONTEND,
    "tailwind css": CAT_FRONTEND,
    # Data / Analytics
    "data analysis": CAT_DATA,
    "data science": CAT_DATA,
    "pandas": CAT_DATA,
    "numpy": CAT_DATA,
    "data engineering": CAT_DATA,
    # Database
    "sql": CAT_DATABASE,
    "postgresql": CAT_DATABASE,
    "mysql": CAT_DATABASE,
    "supabase": CAT_DATABASE,
    "mongodb": CAT_DATABASE,
    "redis": CAT_DATABASE,
    "databases": CAT_DATABASE,
    # Cloud / DevOps
    "docker": CAT_CLOUD,
    "kubernetes": CAT_CLOUD,
    "aws": CAT_CLOUD,
    "google cloud": CAT_CLOUD,
    "azure": CAT_CLOUD,
    "google cloud run": CAT_CLOUD,
    "vercel": CAT_CLOUD,
    "ci cd": CAT_CLOUD,
    "github actions": CAT_CLOUD,
    "deployment": CAT_CLOUD,
    "devops": CAT_CLOUD,
    # Programming Language
    "python": CAT_LANGUAGE,
    "javascript": CAT_LANGUAGE,
    "typescript": CAT_LANGUAGE,
    "java": CAT_LANGUAGE,
    "c++": CAT_LANGUAGE,
    "c#": CAT_LANGUAGE,
    "go": CAT_LANGUAGE,
    "rust": CAT_LANGUAGE,
    "ruby": CAT_LANGUAGE,
    "php": CAT_LANGUAGE,
    # Security / Privacy
    "security": CAT_SECURITY,
    "authentication": CAT_SECURITY,
    "privacy": CAT_SECURITY,
    "encryption": CAT_SECURITY,
    # Product / System Design
    "system design": CAT_PRODUCT,
    "product design": CAT_PRODUCT,
    "software architecture": CAT_PRODUCT,
}

# Keyword fallbacks for unknown skills (substring on the normalized label).
# Ordered: first match wins. Kept conservative to avoid mis-categorizing.
_KEYWORD_CATEGORY: list[tuple[str, str]] = [
    ("llm", CAT_GENAI),
    ("gpt", CAT_GENAI),
    ("prompt", CAT_GENAI),
    ("generative", CAT_GENAI),
    ("machine learning", CAT_AI_ML),
    ("neural", CAT_AI_ML),
    ("deep learning", CAT_AI_ML),
    ("ml model", CAT_AI_ML),
    ("mlops", CAT_MLOPS),
    ("api", CAT_BACKEND),
    ("backend", CAT_BACKEND),
    ("server", CAT_BACKEND),
    ("react", CAT_FRONTEND),
    ("frontend", CAT_FRONTEND),
    ("css", CAT_FRONTEND),
    ("ui", CAT_FRONTEND),
    ("sql", CAT_DATABASE),
    ("database", CAT_DATABASE),
    ("postgres", CAT_DATABASE),
    ("data", CAT_DATA),
    ("analytics", CAT_DATA),
    ("docker", CAT_CLOUD),
    ("kubernetes", CAT_CLOUD),
    ("cloud", CAT_CLOUD),
    ("deploy", CAT_MLOPS),
    ("devops", CAT_CLOUD),
    ("security", CAT_SECURITY),
    ("auth", CAT_SECURITY),
    ("privacy", CAT_SECURITY),
    ("design", CAT_PRODUCT),
    ("architecture", CAT_PRODUCT),
]


def canonical_skill(raw: str) -> str:
    """Canonical display name for a raw skill label (alias-collapsed).

    Unknown skills are returned title-cased-as-given (original casing preserved
    when it already looks intentional) so nothing is lost — only known aliases
    are rewritten.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    alias = _ALIASES.get(_norm(text))
    if alias:
        return alias
    return text


def skill_slug(skill: str) -> str:
    """Stable, URL-safe slug for a skill, derived from its *canonical* name.

    Aliases collapse first (``ml`` and ``Machine Learning`` → ``machine-learning``)
    so the same real skill always resolves to the same slug. Resolving a slug back
    to a canonical skill is done by comparing slugs (``skill_slug(a) == slug``),
    which round-trips through ``canonical_skill`` so ``machine-learning`` →
    ``Machine Learning`` even though the alias table is keyed on spaces.
    """
    canon = canonical_skill(skill)
    slug = re.sub(r"[^a-z0-9]+", "-", canon.lower()).strip("-")
    return slug or "skill"


def skill_category(skill: str) -> str:
    """High-level category for a skill (canonical or raw)."""
    canonical = canonical_skill(skill)
    key = _norm(canonical)
    if key in _CANONICAL_CATEGORY:
        return _CANONICAL_CATEGORY[key]
    # Try the raw normalized form too (in case it wasn't an alias).
    raw_key = _norm(skill)
    if raw_key in _CANONICAL_CATEGORY:
        return _CANONICAL_CATEGORY[raw_key]
    for needle, category in _KEYWORD_CATEGORY:
        if needle in key:
            return category
    return CAT_OTHER


__all__ = [
    "canonical_skill",
    "skill_slug",
    "skill_category",
    "CATEGORY_ORDER",
    "CAT_AI_ML",
    "CAT_GENAI",
    "CAT_MLOPS",
    "CAT_BACKEND",
    "CAT_FRONTEND",
    "CAT_DATA",
    "CAT_DATABASE",
    "CAT_CLOUD",
    "CAT_LANGUAGE",
    "CAT_SECURITY",
    "CAT_PRODUCT",
    "CAT_OTHER",
]
