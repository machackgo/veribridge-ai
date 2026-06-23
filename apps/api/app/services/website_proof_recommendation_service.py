"""Deterministic Website Proof recommendation service.

Ranks a student's saved Website Proof sessions against the Project Defense
they are currently describing, so the Project Defense form only promotes
proofs that are actually about *this* project — never every unrelated saved
proof.

Design constraints (intentional):
  - Deterministic only. No LLM, no network calls. Pure word/URL overlap.
  - Owner-scoped: only the caller's own Website Proof summaries are read,
    via :func:`list_website_proof_summaries`.
  - Returns only safe summary fields plus a derived ``match_label`` /
    ``match_reason``. Never screenshots, storage paths, signed URLs, tokens,
    raw artifact_data, or provider payloads.

Matching rules:
  - Generic words (website, proof, app, demo, project, data, api, cloud,
    google, machine, learning, analysis, high/medium/low, confidence, common
    English stopwords) are ignored — they carry no project signal.
  - Generic *skill* overlap alone never promotes a proof to recommended or
    possible; it is only a tiebreaker for ordering within a tier.
  - A strong (recommended) match needs project-specific overlap: a
    project-specific keyword from the title/description/repo slug appears in
    the proof's domain, or two or more appear anywhere in the proof URL.
  - Known generic doc/playground domains (teachablemachine.withgoogle.com,
    vega.github.io, tensorflow.org, ml5js.org, observablehq.com, …) are only
    promoted when the project context explicitly names them.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.services.website_proof_summary_service import list_website_proof_summaries

# ── Token vocabularies ──────────────────────────────────────────────────────

# Generic words that should never, on their own, make a Website Proof a
# recommended/possible match for a project.
_GENERIC_TOKENS: frozenset[str] = frozenset(
    {
        # domain-specific generics from the product spec
        "website", "proof", "app", "apps", "demo", "project", "projects", "data",
        "api", "apis", "cloud", "google", "machine", "learning", "analysis",
        "high", "medium", "low", "confidence", "web", "site", "online",
        "platform", "tool", "tools", "system", "systems", "application",
        # common English stopwords (length >= 3) that add noise, not signal
        "the", "and", "for", "with", "that", "this", "you", "your", "its",
        "not", "only", "but", "use", "uses", "using", "used", "into",
        "instead", "than", "then", "over", "more", "are", "was", "were",
        "has", "have", "had", "their", "them", "they", "can", "will", "just",
        "also", "such", "like", "via", "per", "etc", "from", "out", "our",
    }
)

# Domain label tokens that never identify a project (hosts/registrars).
_STOP_DOMAIN_TOKENS: frozenset[str] = frozenset(
    {
        "com", "org", "net", "io", "dev", "app", "www", "co", "ai", "xyz",
        "github", "gitlab", "bitbucket", "vercel", "netlify", "pages",
        "herokuapp", "web", "withgoogle", "firebaseapp", "render", "fly",
    }
)

# Generic docs / playgrounds that are almost never the student's own project.
# Only treated as relevant when the project explicitly names the tool.
_GENERIC_WEBSITE_PROOF_DOMAINS: frozenset[str] = frozenset(
    {
        "teachablemachine.withgoogle.com",
        "vega.github.io",
        "tensorflow.org",
        "playground.tensorflow.org",
        "ml5js.org",
        "observablehq.com",
        "threejs.org",
        "p5js.org",
    }
)

_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall((text or "").lower()) if len(w) >= 3]


def _domain_of(url: str) -> str:
    raw = (url or "").strip()
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    host = (parsed.hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _repo_slug_words(repo_url: str) -> list[str]:
    """Extract the owner/repo slug words from a repository URL."""
    if not repo_url:
        return []
    parsed = urlparse(repo_url if "://" in repo_url else f"http://{repo_url}")
    path = (parsed.path or "").strip("/")
    # Drop a trailing ".git" and take the path segments (owner/repo/...).
    path = re.sub(r"\.git$", "", path)
    return _words(path.replace("/", " "))


def _project_specific_tokens(
    project_title: str, project_description: str, repo_url: str
) -> set[str]:
    tokens = set(_words(project_title))
    tokens.update(_words(project_description))
    tokens.update(_repo_slug_words(repo_url))
    return {t for t in tokens if t not in _GENERIC_TOKENS}


def _skill_overlap(supported_skills: Any, project_tokens: set[str]) -> int:
    overlap = 0
    for skill in supported_skills or []:
        skill_words = [w for w in _words(str(skill)) if w not in _GENERIC_TOKENS]
        if any(w in project_tokens for w in skill_words):
            overlap += 1
    return overlap


def _score_proof(summary: dict[str, Any], project_tokens: set[str]) -> dict[str, Any]:
    """Score one safe Website Proof summary against the project tokens."""
    target = str(summary.get("target_website") or "")
    domain = _domain_of(target)
    url_lower = target.lower()

    matched: list[str] = []
    project_score = 0

    # Project-specific keyword appearing as a domain label — strongest signal.
    domain_tokens = [
        w for w in _words(domain)
        if w not in _STOP_DOMAIN_TOKENS and w not in _GENERIC_TOKENS
    ]
    for token in domain_tokens:
        if token in project_tokens and token not in matched:
            project_score += 2
            matched.append(token)

    # Project-specific keyword appearing anywhere in the URL (repo/deploy name).
    for token in project_tokens:
        if len(token) >= 4 and token in url_lower and token not in matched:
            project_score += 1
            matched.append(token)

    is_generic = domain in _GENERIC_WEBSITE_PROOF_DOMAINS
    # A known doc/playground domain is only relevant if the project clearly
    # names it (a domain-label match worth >= 2), never on a coincidental
    # substring hit.
    if is_generic and project_score < 2:
        project_score = 0
        matched = []

    skill_overlap = _skill_overlap(summary.get("supported_skills"), project_tokens)

    if project_score >= 2:
        label = "recommended"
    elif project_score == 1:
        label = "possible"
    else:
        label = "other"

    if matched:
        reason = "Matches project keywords: " + ", ".join(matched[:5])
    else:
        reason = "No project-specific match — generic saved Website Proof."

    enriched = dict(summary)
    enriched["match_label"] = label
    enriched["match_reason"] = reason
    enriched["_project_score"] = project_score
    enriched["_skill_overlap"] = skill_overlap
    return enriched


def _dedupe_by_url(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one summary per normalized target URL — the strongest evidence."""
    by_url: dict[str, dict[str, Any]] = {}
    for summary in summaries:
        target = str(summary.get("target_website") or "").strip().lower()
        key = f"{_domain_of(target)}|{target}"
        existing = by_url.get(key)
        if existing is None or int(summary.get("evidence_strength_score") or 0) > int(
            existing.get("evidence_strength_score") or 0
        ):
            by_url[key] = summary
    return list(by_url.values())


def recommend_website_proofs(
    db: Any,
    user_id: str,
    *,
    project_title: str = "",
    project_description: str = "",
    repo_url: str = "",
    claimed_skills: list[str] | None = None,
) -> dict[str, Any]:
    """Return grouped, owner-scoped Website Proof recommendations.

    Only the caller's own saved Website Proof summaries are considered, and
    only safe summary fields (plus a derived ``match_label`` / ``match_reason``)
    are returned.
    """
    summaries = list_website_proof_summaries(db, user_id)
    summaries = _dedupe_by_url(summaries)

    # claimed_skills are folded into the project context so that a skill the
    # student claims which is *also* project-specific (e.g. an unusual library
    # name) still counts — generic skills are stripped by _GENERIC_TOKENS.
    skill_text = " ".join(claimed_skills or [])
    project_tokens = _project_specific_tokens(
        project_title, f"{project_description} {skill_text}", repo_url
    )

    scored = [_score_proof(s, project_tokens) for s in summaries]
    # Order within each group by project score, then skill overlap, then
    # evidence strength — deterministic.
    scored.sort(
        key=lambda s: (
            s["_project_score"],
            s["_skill_overlap"],
            int(s.get("evidence_strength_score") or 0),
        ),
        reverse=True,
    )

    def _clean(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for item in group:
            row = {k: v for k, v in item.items() if not k.startswith("_")}
            out.append(row)
        return out

    recommended = _clean([s for s in scored if s["match_label"] == "recommended"])
    possible = _clean([s for s in scored if s["match_label"] == "possible"])
    other = _clean([s for s in scored if s["match_label"] == "other"])

    return {
        "recommended_website_proofs": recommended,
        "possible_website_proofs": possible,
        "other_website_proofs": other,
        "has_strong_match": len(recommended) > 0,
    }
