"""Recruiter Query Understanding — natural language → structured search plan.

Deterministic, dependency-free, always available: this is the layer that
turns "Find me an entry-level AI engineer with Python, FastAPI and NLP who
has deployed a project" into

    role        : AI Engineer            (soft signal)
    seniority   : entry level            (soft signal)
    required    : Python AND FastAPI AND Natural Language Processing
    evidence    : live deployed project

It is intentionally a recruiter-hiring-intent grammar, not a general English
parser. Anything it cannot map to a known concept, role, seniority level,
evidence expectation, or location stays a *residual lexical term* — matched
the same way Search V1 matched everything, and never promoted to a hard
requirement. An LLM interpreter can later be slotted IN FRONT of this parser
(producing the same plan shape, validated against the same taxonomy); this
module is the guaranteed fallback and today's production path, because the
production environment deliberately runs with no external AI provider.

HARD SEMANTICS (the product contract):
  * required concepts combine with AND; "X or Y" forms one OR-group;
  * "not / without / but not X" excludes candidates with X evidence;
  * "prefer / nice to have / ideally X" is preferred, never required;
  * role, seniority, and location are SOFT signals (ranking + explanation)
    because they live in profile prose, not verifiable evidence;
  * evidence expectations ("deployed", "GitHub evidence", "real projects")
    become hard evidence requirements checked against evidence flags.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.recruiter_search_taxonomy import (
    PHRASE_TO_CONCEPT,
    concept_display,
)

MAX_QUERY_LENGTH = 320

# ── Vocabulary ────────────────────────────────────────────────────────────────

# Words that carry recruiter phrasing, not meaning. Only consulted for tokens
# that did NOT match a concept / role / evidence phrase, so they can never
# swallow a real technology term.
_INTENT_WORDS = {
    "a", "an", "and", "are", "as", "at", "can", "do", "does", "for", "from",
    "give", "had", "has", "have", "i", "in", "is", "it", "know", "knows",
    "looking", "me", "my", "need", "needs", "of", "on", "or", "our",
    "please", "search", "seeking", "show", "some", "somebody", "someone",
    "that", "the", "their", "them", "they", "this", "through", "to", "us",
    "want", "wants", "we", "who", "whos", "with", "works", "worked",
    "find", "get", "hire", "hiring", "candidates", "candidate", "people",
    "person", "profiles", "profile", "students", "student", "folks",
    "experience", "experienced", "expertise", "skills", "skilled", "skill",
    "background", "knowledge", "strong", "solid", "good", "great",
    "demonstrated", "demonstrates", "demonstrating", "proven", "actually",
    "really", "must", "should", "also", "both", "either", "well",
    "projects", "project", "real", "work", "using", "used", "uses",
    "only", "role", "roles", "position", "positions", "job", "jobs",
    "but", "if", "when", "where", "which", "whose", "been", "be",
    "i'm", "im", "we're", "i've", "we've", "who's", "it's", "that's",
    "what's", "they're", "you're", "he's", "she's", "let's", "dont",
    "don't", "doesn't", "isn't", "aren't",
}

# Tokens that read as role nouns when a role phrase did not match; dropped
# from residual noise ("engineer" alone should not lexically outrank skills).
_ROLE_NOUNS = {"engineer", "engineers", "developer", "developers", "dev", "devs"}

_ROLE_PHRASES: dict[str, str] = {
    "ai engineer": "AI Engineer",
    "artificial intelligence engineer": "AI Engineer",
    "machine learning engineer": "Machine Learning Engineer",
    "ml engineer": "Machine Learning Engineer",
    "nlp engineer": "NLP Engineer",
    "computer vision engineer": "Computer Vision Engineer",
    "data scientist": "Data Scientist",
    "data engineer": "Data Engineer",
    "data analyst": "Data Analyst",
    "backend engineer": "Backend Engineer",
    "backend developer": "Backend Engineer",
    "back end engineer": "Backend Engineer",
    "back end developer": "Backend Engineer",
    "frontend engineer": "Frontend Engineer",
    "frontend developer": "Frontend Engineer",
    "front end engineer": "Frontend Engineer",
    "front end developer": "Frontend Engineer",
    "full stack engineer": "Full-Stack Engineer",
    "full stack developer": "Full-Stack Engineer",
    "fullstack engineer": "Full-Stack Engineer",
    "fullstack developer": "Full-Stack Engineer",
    "software engineer": "Software Engineer",
    "software developer": "Software Engineer",
    "web developer": "Web Developer",
    "devops engineer": "DevOps Engineer",
    "qa engineer": "QA Engineer",
}

# Role phrase → concepts a matching candidate plausibly carries. Used ONLY to
# widen retrieval + soft ranking, never as hard requirements.
_ROLE_HINT_CONCEPTS: dict[str, tuple[str, ...]] = {
    "AI Engineer": ("artificial-intelligence", "machine-learning"),
    "Machine Learning Engineer": ("machine-learning",),
    "NLP Engineer": ("natural-language-processing",),
    "Computer Vision Engineer": ("computer-vision",),
    "Data Scientist": ("data-science", "machine-learning"),
    "Data Engineer": ("data-engineering",),
    "Data Analyst": ("data-analysis",),
    "Backend Engineer": ("backend-development", "api-development"),
    "Frontend Engineer": ("frontend-development",),
    "Full-Stack Engineer": ("full-stack-engineering",),
    "DevOps Engineer": ("devops",),
    "Web Developer": ("frontend-development",),
}

_SENIORITY_PHRASES: dict[str, tuple[str, str]] = {
    # phrase → (key, display)
    "entry level": ("entry_level", "Entry level"),
    "entry-level": ("entry_level", "Entry level"),
    "new grad": ("entry_level", "Entry level / new grad"),
    "new graduate": ("entry_level", "Entry level / new grad"),
    "recent graduate": ("entry_level", "Entry level / new grad"),
    "junior": ("entry_level", "Entry level / junior"),
    "intern": ("intern", "Intern"),
    "interns": ("intern", "Intern"),
    "internship": ("intern", "Intern"),
    "co op": ("intern", "Co-op / intern"),
    "coop": ("intern", "Co-op / intern"),
}

# Evidence-expectation phrases → evidence requirement keys.
#   github / live_site / documents / project_defense / video  → evidence flags
#   project                                                    → ≥1 public project
_EVIDENCE_PHRASES: dict[str, str] = {
    "github evidence": "github",
    "github proof": "github",
    "github proofs": "github",
    "github code": "github",
    "github repo": "github",
    "github repos": "github",
    "github repository": "github",
    "github": "github",
    "live deployment": "live_site",
    "live deployments": "live_site",
    "live deployed site": "live_site",
    "live deployed project": "live_site",
    "live site": "live_site",
    "live sites": "live_site",
    "live project": "live_site",
    "live projects": "live_site",
    "live demo": "live_site",
    "live app": "live_site",
    "deployed": "live_site",
    "deployed a project": "live_site",
    "deployed project": "live_site",
    "deployed projects": "live_site",
    "deployed site": "live_site",
    "deployed app": "live_site",
    "deployment evidence": "live_site",
    "live": "live_site",
    "project defense": "project_defense",
    "project defenses": "project_defense",
    "defended a project": "project_defense",
    "defended projects": "project_defense",
    "video evidence": "video",
    "video proof": "video",
    "document proof": "documents",
    "document evidence": "documents",
    "real projects": "project",
    "real project": "project",
    "project evidence": "project",
    "built something": "project",
    "built things": "project",
    "has built": "project",
    "built": "project",
    "portfolio": "project",
}

EVIDENCE_REQUIREMENT_DISPLAY: dict[str, str] = {
    "github": "GitHub evidence",
    "live_site": "Live deployed project",
    "documents": "Document evidence",
    "project_defense": "Project defense",
    "video": "Video evidence",
    "project": "Published project evidence",
}

_NEGATION_STARTERS = ("but not", "and not", "not", "without", "excluding", "except", "no")
_PREFER_STARTERS = (
    "nice to have", "preferably", "prefer", "prefers", "preferred",
    "ideally", "bonus if", "bonus", "a plus",
)
_REQUIRE_STARTERS = ("must have", "must know", "required", "require", "requires")

_LOCATION_STARTERS = ("around", "near", "based in", "located in", "location")

_MODE_MARKERS: dict[str, str] = (
    {p: "excluded" for p in _NEGATION_STARTERS}
    | {p: "preferred" for p in _PREFER_STARTERS}
    | {p: "required" for p in _REQUIRE_STARTERS}
)

_TOKEN_RE = re.compile(r"[a-z0-9+#.']+|,")

_MAX_PHRASE_WORDS = 4


def _split_plus(token: str) -> list[str]:
    """"python+fastapi" → ["python", "fastapi"]; "c++" stays intact."""
    if "+" not in token:
        return [token]
    parts = re.split(r"\+(?=[a-z0-9]{2})", token)
    return [p for p in parts if p]


def _tokenize(text: str) -> list[str]:
    """Lowercased word tokens with "," kept as a boundary marker."""
    lowered = str(text or "").strip().lower()[:MAX_QUERY_LENGTH]
    lowered = lowered.replace("/", " ").replace("&", " and ")
    out: list[str] = []
    for raw in _TOKEN_RE.findall(lowered):
        if raw == ",":
            out.append(",")
            continue
        token = raw.strip("'.")
        for part in _split_plus(token):
            if part:
                out.append(part)
    return out


def _phrase_at(
    tokens: list[str], i: int, table: dict[str, Any]
) -> tuple[str, Any, int] | None:
    """Greedy longest-match of a known phrase starting at ``tokens[i]``.
    Returns (phrase, value, word_count) or None."""
    max_len = min(_MAX_PHRASE_WORDS, len(tokens) - i)
    for length in range(max_len, 0, -1):
        window = tokens[i : i + length]
        if "," in window:
            continue
        phrase = " ".join(window)
        if phrase in table:
            return phrase, table[phrase], length
    return None


def parse_recruiter_query(q: Any) -> dict[str, Any]:
    """Parse a recruiter's free-text request into a structured search plan.

    Returns a plain dict (dual-mode friendly):
      raw, mode ("browse" | "lexical" | "structured"),
      required_groups: [[concept, ...], ...]   # AND of OR-groups
      preferred: [concept, ...]
      excluded: [concept, ...]
      evidence: [evidence requirement key, ...]
      role: {"display": str, "hint_concepts": [...]} | None
      seniority: {"key": str, "display": str} | None
      location: str | None
      residual_terms: [str, ...]
    """
    raw = str(q or "").strip()[:MAX_QUERY_LENGTH]
    tokens = _tokenize(raw)

    required_groups: list[list[str]] = []
    preferred: list[str] = []
    excluded: list[str] = []
    evidence: list[str] = []
    preferred_evidence: list[str] = []
    residual: list[str] = []
    role: dict[str, Any] | None = None
    seniority: dict[str, str] | None = None
    location: str | None = None

    seen_concepts: set[str] = set()
    mode_stack = "required"  # required | preferred | excluded
    pending_or = False  # next concept joins the previous group

    i = 0
    n = len(tokens)
    while i < n:
        token = tokens[i]

        if token == ",":
            # A comma ends an OR run but keeps the requirement mode: "Python,
            # FastAPI and NLP" is AND of three. A negation/preference span
            # also ends at a comma.
            pending_or = False
            mode_stack = "required"
            i += 1
            continue

        # Mode markers (longest first so "but not" wins over "not").
        marker = _phrase_at(tokens, i, _MODE_MARKERS)
        if marker is not None:
            phrase, mode, length = marker
            mode_stack = str(mode)
            pending_or = False
            i += length
            continue

        if token in ("or", "either"):
            pending_or = True
            i += 1
            continue

        # Location: "around Worcester" — take the next non-keyword token.
        loc = _phrase_at(tokens, i, {p: True for p in _LOCATION_STARTERS})
        if loc is not None and location is None:
            _, _, length = loc
            j = i + length
            if j < n and tokens[j] != "," and tokens[j] not in PHRASE_TO_CONCEPT:
                location = tokens[j]
                i = j + 1
                continue

        # Role phrases (may be longer than an embedded concept — try first).
        role_hit = _phrase_at(tokens, i, _ROLE_PHRASES)
        concept_hit = _phrase_at(tokens, i, PHRASE_TO_CONCEPT)
        if role_hit is not None and (
            concept_hit is None or role_hit[2] > concept_hit[2]
        ):
            _, display, length = role_hit
            if role is None:
                role = {
                    "display": str(display),
                    "hint_concepts": list(_ROLE_HINT_CONCEPTS.get(str(display), ())),
                }
            i += length
            continue

        # Seniority.
        sen_hit = _phrase_at(tokens, i, _SENIORITY_PHRASES)
        if sen_hit is not None and (
            concept_hit is None or sen_hit[2] >= concept_hit[2]
        ):
            _, (key, display), length = sen_hit
            if seniority is None:
                seniority = {"key": key, "display": display}
            i += length
            continue

        # Evidence expectations — but only when the phrase beats any concept
        # match at this position ("github actions" is a skill, "github
        # evidence" is an evidence expectation).
        ev_hit = _phrase_at(tokens, i, _EVIDENCE_PHRASES)
        if ev_hit is not None and (
            concept_hit is None or ev_hit[2] >= concept_hit[2]
        ):
            _, ev_key, length = ev_hit
            target = preferred_evidence if mode_stack == "preferred" else evidence
            if ev_key not in target:
                target.append(str(ev_key))
            pending_or = False
            i += length
            continue

        # Known concept.
        if concept_hit is not None:
            _, slug, length = concept_hit
            slug = str(slug)
            if slug not in seen_concepts:
                seen_concepts.add(slug)
                if mode_stack == "excluded":
                    excluded.append(slug)
                elif mode_stack == "preferred":
                    preferred.append(slug)
                elif pending_or and required_groups:
                    required_groups[-1].append(slug)
                else:
                    required_groups.append([slug])
            pending_or = False
            # A negation span covers ONE concept ("machine learning but not
            # computer vision and Python" — Python is required again).
            if mode_stack == "excluded":
                mode_stack = "required"
            i += length
            continue

        # Unknown token → intent noise or residual lexical term.
        if token not in _INTENT_WORDS and token not in _ROLE_NOUNS and len(token) >= 2:
            if token not in residual:
                residual.append(token)
        i += 1

    structured = bool(
        required_groups or preferred or excluded or evidence
        or preferred_evidence or role or seniority or location
    )
    if not raw:
        mode = "browse"
    elif structured:
        mode = "structured"
    else:
        mode = "lexical"

    return {
        "raw": raw,
        "mode": mode,
        "required_groups": required_groups,
        "preferred": preferred,
        "excluded": excluded,
        "evidence": evidence,
        "preferred_evidence": preferred_evidence,
        "role": role,
        "seniority": seniority,
        "location": location,
        "residual_terms": residual[:12],
    }


def describe_group(group: list[str]) -> str:
    """Human display for one requirement group ("Python" / "Python or Go")."""
    return " or ".join(concept_display(slug) for slug in group)


__all__ = [
    "EVIDENCE_REQUIREMENT_DISPLAY",
    "MAX_QUERY_LENGTH",
    "describe_group",
    "parse_recruiter_query",
]
