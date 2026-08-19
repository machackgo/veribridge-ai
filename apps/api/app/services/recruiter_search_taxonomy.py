"""Recruiter-search concept taxonomy (deterministic, no LLM).

Skill *normalization* (``skill_normalization``) answers "what is the one
canonical name for this label?". This module answers the recruiter-search
questions that normalization alone cannot:

  * RECOGNITION — which known concepts appear in a free-text recruiter
    query? ("Python FastAPI API development" → three distinct concepts,
    longest phrase wins, never double-counted).
  * SATISFACTION — does published evidence for concept X satisfy a
    requirement for concept Y? The rules are deliberately asymmetric:

      - alias           → YES (``nlp`` ⇄ ``Natural Language Processing``)
      - child evidence  → satisfies a PARENT requirement (FastAPI evidence
                          satisfies "API development" — the specific proves
                          the general)
      - parent evidence → NEVER satisfies a CHILD requirement ("API
                          development" evidence does NOT satisfy "FastAPI";
                          Machine Learning does NOT satisfy "NLP")
      - related concept → NEVER satisfies anything; used only to widen
                          retrieval recall and phrase suggestions.

    This asymmetry is the anti-hallucination contract: search may never
    claim a candidate has a skill the published evidence does not support.
  * EXPANSION — which extra terms should the retrieval prefilter include so
    that candidates who could satisfy a requirement (via alias or child
    evidence) are pulled into the ranking pool?

Everything is keyed on the canonical skill slug (``skill_slug``), so the
graph automatically agrees with the Work Passport's own grouping.
"""

from __future__ import annotations

from app.services.skill_normalization import canonical_skill, skill_slug

# ── Parent edges: child slug → direct parent slugs ────────────────────────────
# Semantics: real evidence of the CHILD demonstrates competence in the PARENT.
# Kept conservative — an edge is only added when the implication is factual
# (FastAPI is a Python framework) or overwhelmingly true in practice for the
# student population this product serves. The reverse implication NEVER holds.

_PARENTS: dict[str, tuple[str, ...]] = {
    # AI / ML
    "natural-language-processing": ("machine-learning",),
    "computer-vision": ("machine-learning",),
    "deep-learning": ("machine-learning",),
    "machine-learning": ("artificial-intelligence",),
    "generative-ai": ("artificial-intelligence",),
    "large-language-models": ("generative-ai",),
    "retrieval-augmented-generation": ("large-language-models",),
    "prompt-engineering": ("generative-ai",),
    "model-training": ("machine-learning",),
    "model-evaluation": ("machine-learning",),
    "model-deployment": ("mlops", "deployment"),
    "feature-engineering": ("machine-learning",),
    "scikit-learn": ("machine-learning", "python"),
    "pytorch": ("deep-learning", "python"),
    "tensorflow": ("deep-learning", "python"),
    "keras": ("deep-learning", "python"),
    "ocr": ("computer-vision",),
    # Backend / APIs
    "fastapi": ("api-development", "backend-development", "python"),
    "flask": ("api-development", "backend-development", "python"),
    "django": ("api-development", "backend-development", "python"),
    "express-js": ("api-development", "backend-development", "javascript"),
    "node-js": ("backend-development", "javascript"),
    "rest-apis": ("api-development",),
    "graphql": ("api-development",),
    "api-development": ("backend-development",),
    # Frontend
    "react": ("frontend-development", "javascript"),
    "next-js": ("react",),
    "vue-js": ("frontend-development", "javascript"),
    "angular": ("frontend-development", "typescript"),
    "typescript": ("javascript",),
    "html-css": ("frontend-development",),
    "tailwind-css": ("frontend-development",),
    "responsive-ui": ("frontend-development",),
    # Data
    "pandas": ("data-analysis", "python"),
    "numpy": ("python",),
    "data-visualization": ("data-analysis",),
    "data-science": ("data-analysis",),
    "geospatial-analysis": ("data-analysis",),
    # Database
    "postgresql": ("sql", "databases"),
    "mysql": ("sql", "databases"),
    "sql": ("databases",),
    "supabase": ("postgresql",),
    "mongodb": ("databases",),
    "redis": ("databases",),
    # Cloud / DevOps
    "docker": ("deployment",),
    "kubernetes": ("deployment",),
    "github-actions": ("ci-cd",),
    "ci-cd": ("deployment", "devops"),
    "vercel": ("deployment",),
    "google-cloud-run": ("google-cloud", "deployment"),
    "mlops": ("deployment",),
    # Quality
    "pytest": ("testing", "python"),
    "jest": ("testing", "javascript"),
    "playwright": ("test-automation",),
    "test-automation": ("testing",),
}

# ── Related edges: retrieval-recall only — NEVER satisfaction ────────────────
# "A recruiter asking for X may also want to see candidates indexed under Y
# in the CANDIDATE POOL (they still get verified against X afterwards)."

_RELATED: dict[str, tuple[str, ...]] = {
    "natural-language-processing": (
        "large-language-models",
        "generative-ai",
        "machine-learning",
    ),
    "machine-learning": (
        "natural-language-processing",
        "computer-vision",
        "deep-learning",
        "data-science",
    ),
    "computer-vision": ("machine-learning", "deep-learning", "ocr"),
    "generative-ai": ("large-language-models", "natural-language-processing"),
    "api-development": ("fastapi", "flask", "django", "rest-apis"),
    "backend-development": ("api-development", "fastapi", "node-js"),
    "python": ("fastapi", "django", "flask", "pandas", "machine-learning"),
    "javascript": ("react", "next-js", "node-js", "typescript"),
    "frontend-development": ("react", "next-js", "html-css"),
    "databases": ("postgresql", "sql", "supabase"),
    "deployment": ("docker", "vercel", "ci-cd", "mlops"),
    "data-analysis": ("data-visualization", "pandas", "data-science"),
}

# Display names for concepts that are not skills in the alias table but can
# still be requirement targets (kept minimal — most displays come from
# canonical_skill via the alias table).
_EXTRA_DISPLAY: dict[str, str] = {}


def _slugify_phrase(phrase: str) -> str:
    return skill_slug(phrase)


def concept_display(slug: str) -> str:
    """Human display name for a concept slug ("natural-language-processing"
    → "Natural Language Processing")."""
    if slug in _EXTRA_DISPLAY:
        return _EXTRA_DISPLAY[slug]
    words = slug.replace("-", " ")
    canon = canonical_skill(words)
    if skill_slug(canon) == slug:
        return canon
    # Fallback: title-case the slug words.
    return " ".join(w.upper() if len(w) <= 3 and w in {"sql", "ocr", "aws", "gcp", "php", "ai"} else w.capitalize() for w in words.split())


def ancestors(slug: str) -> frozenset[str]:
    """All transitive parents of a concept (never includes the concept)."""
    return _ANCESTORS.get(slug, frozenset())


def descendants(slug: str) -> frozenset[str]:
    """All transitive children of a concept (never includes the concept)."""
    return _DESCENDANTS.get(slug, frozenset())


def related(slug: str) -> tuple[str, ...]:
    return _RELATED.get(slug, ())


def satisfies(evidence_slug: str, requirement_slug: str) -> bool:
    """True when published evidence for ``evidence_slug`` legitimately
    satisfies a requirement for ``requirement_slug``.

    Alias equivalence is already collapsed by ``skill_slug`` upstream, so:
    exact slug match, or the requirement is an ANCESTOR of the evidence
    (child proves parent). Parent evidence never satisfies a child
    requirement; related concepts never satisfy anything.
    """
    if not evidence_slug or not requirement_slug:
        return False
    if evidence_slug == requirement_slug:
        return True
    return requirement_slug in _ANCESTORS.get(evidence_slug, frozenset())


def expansion_terms(slug: str) -> list[str]:
    """Retrieval prefilter terms for a requirement concept: the concept's
    own words, its known alias spellings, every descendant (candidates whose
    child evidence would satisfy it), and related concepts (recall only —
    verification happens after retrieval, so over-pulling is safe and
    under-pulling is not)."""
    seen: list[str] = []

    def add(text: str) -> None:
        t = text.replace("-", " ").strip().lower()
        if t and t not in seen:
            seen.append(t)

    add(slug)
    for alias_norm, canonical in _ALIAS_ITEMS:
        if skill_slug(canonical) == slug:
            add(alias_norm)
    for child in descendants(slug):
        add(child)
    for rel in related(slug):
        add(rel)
    return seen


# ── Query-phrase recognition table ────────────────────────────────────────────
# normalized phrase (space-separated words) → concept slug. Built from the
# skill_normalization alias table plus the canonical names themselves, so any
# skill a passport can display is also recognizable in a recruiter query.


def _build_phrase_table() -> dict[str, str]:
    from app.services.skill_normalization import _ALIASES  # intentional: one source of truth

    table: dict[str, str] = {}
    for alias_norm, canonical in _ALIASES.items():
        table[alias_norm] = skill_slug(canonical)
        canon_norm = " ".join(canonical.lower().replace("/", " ").replace("-", " ").replace(".", " ").split())
        table.setdefault(canon_norm, skill_slug(canonical))
    # Concept slugs referenced by the graph that may not be alias-table keys.
    for slug in set(_PARENTS) | {p for ps in _PARENTS.values() for p in ps} | set(_RELATED):
        table.setdefault(slug.replace("-", " "), slug)
    return table


def _build_alias_items() -> tuple[tuple[str, str], ...]:
    from app.services.skill_normalization import _ALIASES

    return tuple(_ALIASES.items())


def _transitive(edges: dict[str, tuple[str, ...]]) -> dict[str, frozenset[str]]:
    closure: dict[str, frozenset[str]] = {}

    def walk(node: str, trail: frozenset[str]) -> frozenset[str]:
        if node in closure:
            return closure[node]
        out: set[str] = set()
        for nxt in edges.get(node, ()):
            if nxt in trail:  # cycle guard — a taxonomy bug must not hang
                continue
            out.add(nxt)
            out |= walk(nxt, trail | {node})
        result = frozenset(out)
        closure[node] = result
        return result

    for node in edges:
        walk(node, frozenset())
    return closure


_ALIAS_ITEMS = _build_alias_items()
PHRASE_TO_CONCEPT: dict[str, str] = _build_phrase_table()
_ANCESTORS = _transitive(_PARENTS)
_DESCENDANTS_MUT: dict[str, set[str]] = {}
for _child, _anc in _ANCESTORS.items():
    for _a in _anc:
        _DESCENDANTS_MUT.setdefault(_a, set()).add(_child)
_DESCENDANTS: dict[str, frozenset[str]] = {
    k: frozenset(v) for k, v in _DESCENDANTS_MUT.items()
}

# Longest phrase first for greedy longest-match recognition.
PHRASES_BY_LENGTH: list[tuple[tuple[str, ...], str]] = sorted(
    ((tuple(p.split()), c) for p, c in PHRASE_TO_CONCEPT.items()),
    key=lambda item: -len(item[0]),
)

__all__ = [
    "PHRASE_TO_CONCEPT",
    "PHRASES_BY_LENGTH",
    "ancestors",
    "concept_display",
    "descendants",
    "expansion_terms",
    "related",
    "satisfies",
]
