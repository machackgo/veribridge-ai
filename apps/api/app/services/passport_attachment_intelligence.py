"""Proof Attachment Intelligence (Passport Phase 3) — owner-only guidance.

Turns "N proof items are not attached" into safe, actionable suggestions:
which unattached proof likely belongs to which project, which skill it
supports, why (evidence basis chips), and what the student should do next.

Design constraints (hard rules):

* **Deterministic only.** Matching uses safe metadata already on vault items
  and project cards — repository identity, website domain, document/project
  titles, and overlapping claimed skills. No LLM calls, no crawling, no
  provider calls, and nothing is recomputed from raw evidence.
* **Non-destructive.** This module only *derives* suggestions; it never
  attaches a proof, never writes to the database, and never mutates its
  inputs. Attaching stays an explicit student action elsewhere.
* **Qualitative only.** Confidence is a closed label ("Likely match" /
  "Possible match" / "Needs review") — never a numeric score.
* **Private surface only.** Every suggestion (and every per-project
  strengthening field derived here) is added ONLY to the private passport
  payload. The public projection carries at most an honest, count-free
  limitation sentence — never suggestion objects, private ids, or routes.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlparse

from app.services.skill_normalization import canonical_skill

__all__ = [
    "build_attachment_suggestions",
    "proof_chain_gaps",
    "chain_label",
    "suggested_attachments_for_project",
    "next_best_action",
    "PUBLIC_UNATTACHED_LIMITATION",
    "SKILL_TIE_REVIEW_REASON",
]

# Canonical proof-source labels (mirrors student_proof_vault_service).
_PROOF_GITHUB = "GitHub Proof"
_PROOF_DOCUMENT = "Document Proof"
_PROOF_WEBSITE = "Website Proof"
_PROOF_DEFENSE = "Project Defense"
_PROOF_VIDEO = "Video Evidence"
_PROOF_SKILL_GRAPH = "Skill Graph"

# Defense/video proofs are created inside a project session, so they are never
# "unattached" — they can never need an attachment suggestion.
_SUGGESTIBLE_PROOF_TYPES = {
    _PROOF_GITHUB,
    _PROOF_DOCUMENT,
    _PROOF_WEBSITE,
    _PROOF_SKILL_GRAPH,
}

# Closed evidence-basis chip vocabulary (safe, recruiter-style labels).
CHIP_MATCHING_REPOSITORY = "Matching repository"
CHIP_MATCHING_WEBSITE_DOMAIN = "Matching website domain"
CHIP_MATCHING_DOCUMENT_TITLE = "Matching document title"
CHIP_MATCHING_PROJECT_TITLE = "Matching project title"
CHIP_MATCHING_SKILL = "Matching skill"

# Qualitative confidence labels (closed set — never numeric).
LABEL_LIKELY = "Likely match"
LABEL_POSSIBLE = "Possible match"
LABEL_NEEDS_REVIEW = "Needs review"

_LABEL_RANK = {LABEL_LIKELY: 0, LABEL_POSSIBLE: 1, LABEL_NEEDS_REVIEW: 2}

# Every suggestion carries the same honest limitation: it is metadata matching,
# not a verified link, and nothing happens without the student's confirmation.
_SUGGESTION_LIMITATION = (
    "Suggested match only — based on matching safe metadata (titles, repository, "
    "domain, skills), not verified evidence. Review before attaching; nothing is "
    "attached automatically."
)

_ACTION_LABEL = "Review and attach proof"

# Shown when an unattached proof's ONLY signal is skill overlap and several
# projects tie — a weak signal must never guess a specific project.
SKILL_TIE_REVIEW_REASON = (
    "Multiple projects share this skill; review manually before attaching."
)

_MAX_SUGGESTIONS = 12
_MAX_SUGGESTION_SKILLS = 4
_MAX_PROJECT_SUGGESTIONS = 3

# The single, count-free sentence the PUBLIC passport may carry when unattached
# vault evidence exists. No ids, counts of specific proofs, or suggestion logic.
PUBLIC_UNATTACHED_LIMITATION = (
    "Additional proof evidence exists in the candidate's private vault that is "
    "not attached to the featured projects, so it is not shown here."
)

_PRIVATE_PROJECT_REPORT_PREFIX = "/student/vbr/projects/"

# Captures ``owner/name`` from any github.com URL — repo root, ``.git`` clone
# URL, or a deep blob/line link (the char class stops at the next ``/``).
_REPO_RE = re.compile(r"github\.com[/:]+([\w.-]+/[\w.-]+)", re.IGNORECASE)

# Generic host / TLD fragments that never identify a project by themselves.
_DOMAIN_NOISE = {
    "www", "com", "org", "net", "io", "app", "dev", "ai", "co", "in", "us", "uk",
    "me", "xyz", "site", "web", "cloud", "pages", "github", "gitlab", "vercel",
    "netlify", "herokuapp", "onrender", "render", "railway", "streamlit",
    "huggingface", "spaces", "firebaseapp", "azurewebsites", "amazonaws",
    "withgoogle", "google", "repl", "replit",
}


def _norm(text: Any) -> str:
    """Lowercased, alphanumeric-word normalization for fuzzy-free comparison."""
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def _squash(text: Any) -> str:
    return _norm(text).replace(" ", "")


def _repo_identity(url_or_full: Any) -> str:
    """Normalized ``owner/name`` from a repo URL or an already-full name."""
    raw = str(url_or_full or "").strip().lower()
    if not raw:
        return ""
    match = _REPO_RE.search(raw)
    if match:
        name = match.group(1)
        return name[:-4] if name.endswith(".git") else name
    if "/" in raw and "://" not in raw and " " not in raw:
        return raw.rstrip("/")
    return ""


def _item_domain(item: dict[str, Any]) -> str:
    """The safe website domain for a vault item (from its safe public URL/title)."""
    for field in ("public_url", "title"):
        raw = str(item.get(field) or "").strip()
        if "://" in raw:
            host = urlparse(raw).hostname or ""
            if host:
                return host.lower()
    loc = str(item.get("safe_location") or "").strip().lower()
    if "." in loc and " " not in loc:
        return loc
    return ""


def _domain_matches_title(domain: str, title_norm: str) -> bool:
    """True when a website domain plausibly names a project title.

    Deterministic: a meaningful (non-noise) domain token must either appear
    squashed inside the squashed title (``teachablemachine`` ⊂
    ``teachablemachineimageclassificationdemo``) or share 2+ hyphen-split words
    with the title (``stroke-prediction-app`` ↔ "Stroke Prediction App").
    """
    if not domain or not title_norm:
        return False
    squashed_title = title_norm.replace(" ", "")
    title_words = set(title_norm.split())
    for token in domain.split("."):
        token = token.strip().lower()
        if not token or token in _DOMAIN_NOISE:
            continue
        words = [w for w in re.split(r"[-_\d]+", token) if len(w) > 2 and w not in _DOMAIN_NOISE]
        flat = re.sub(r"[-_]", "", token)
        if len(flat) >= 6 and (flat in squashed_title or squashed_title in flat):
            return True
        overlap = [w for w in words if w in title_words]
        if len(overlap) >= 2:
            return True
        if len(words) == 1 and words[0] in title_words and len(words[0]) >= 6:
            return True
    return False


def _title_contains(haystack_norm: str, needle_norm: str) -> bool:
    """True when a normalized title meaningfully appears inside another text.

    Requires the needle to be a real title (2+ words or 8+ chars) so short
    generic words ("app", "demo") can never create a match on their own.
    """
    if not needle_norm or not haystack_norm:
        return False
    if len(needle_norm) < 8 and len(needle_norm.split()) < 2:
        return False
    return needle_norm in haystack_norm


def _canonical_skills(names: Any) -> set[str]:
    out: set[str] = set()
    for name in names or []:
        text = str(name or "").strip()
        if text:
            out.add(_norm(canonical_skill(text)))
    return out


# ── Unattached-proof grouping ─────────────────────────────────────────────────


def _group_key(item: dict[str, Any]) -> tuple[str, str]:
    """Group duplicate unattached rows of the same proof source into ONE
    suggestion (a repo's many code rows, a doc's many skill matches).

    GitHub rows merge ONLY on a stable repository identity (a repo URL or an
    ``owner/name`` full name). A title alone is never identity — two unrelated
    ownerless rows that happen to share a title stay separate rows.
    """
    proof_type = str(item.get("proof_type") or "")
    if proof_type == _PROOF_GITHUB:
        ident = (
            _repo_identity(item.get("repo_url"))
            or _repo_identity(item.get("public_url"))
            # Vault GitHub rows often carry the repo full name as their title
            # ("octocat/Hello-World") — that IS a stable owner/name identity.
            # _repo_identity returns "" for plain title text, never matching it.
            or _repo_identity(item.get("title"))
        )
        if ident:
            return (proof_type, f"repo:{ident}")
        # No stable repo identity — keep the row on its own source row so
        # unrelated evidence is never combined just because titles match.
        return (proof_type, f"row:{item.get('source_table')}:{item.get('source_id')}")
    return (proof_type, f"{item.get('source_table')}:{item.get('source_id')}")


def _group_unattached(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for item in items:
        if item.get("is_attached_to_project"):
            continue
        proof_type = str(item.get("proof_type") or "")
        if proof_type not in _SUGGESTIBLE_PROOF_TYPES:
            continue
        key = _group_key(item)
        group = groups.get(key)
        if group is None:
            group = {
                "proof_type": proof_type,
                # Stable group identity (repo identity or source-row ref) —
                # feeds the suggestion-id digest so same-title distinct proofs
                # can never collide. Hashed before exposure, never shown raw.
                "ident": f"{key[0]}|{key[1]}",
                "title": "",
                "skills": [],
                "repo_id": "",
                "domain": "",
                "text_norm": "",
                "item_count": 0,
            }
            groups[key] = group
            order.append(key)
        group["item_count"] += 1
        title = str(item.get("title") or "").strip()
        if title and not group["title"]:
            group["title"] = title
        skill = str(item.get("skill_name") or "").strip()
        if skill and skill not in group["skills"]:
            group["skills"].append(skill)
        if proof_type == _PROOF_GITHUB and not group["repo_id"]:
            group["repo_id"] = (
                _repo_identity(item.get("repo_url"))
                or _repo_identity(item.get("public_url"))
                or _repo_identity(item.get("title"))
            )
        if proof_type == _PROOF_WEBSITE and not group["domain"]:
            group["domain"] = _item_domain(item)
        if proof_type == _PROOF_DOCUMENT:
            # Safe, already-sanitized document text only (title/summary/snippet).
            text = " ".join(
                _norm(item.get(f)) for f in ("title", "safe_summary", "safe_snippet")
            )
            if len(text) > len(group["text_norm"]):
                group["text_norm"] = text
    return [groups[key] for key in order]


# ── Matching one proof group against one project card ────────────────────────


def _match_signals(group: dict[str, Any], project: dict[str, Any]) -> list[str]:
    """The deterministic evidence-basis chips connecting a proof group to a
    project card. Safe metadata only — never raw evidence."""
    chips: list[str] = []
    proof_type = group["proof_type"]
    project_title_norm = _norm(project.get("project_title"))
    project_repo = str(project.get("repo_full_name") or "").strip().lower()
    group_title_norm = _norm(group.get("title"))

    if proof_type == _PROOF_GITHUB and group.get("repo_id") and project_repo:
        if group["repo_id"] == project_repo:
            chips.append(CHIP_MATCHING_REPOSITORY)

    if proof_type == _PROOF_WEBSITE and group.get("domain"):
        if _domain_matches_title(group["domain"], project_title_norm) or (
            project_repo and _domain_matches_title(group["domain"], _norm(project_repo.split("/")[-1]))
        ):
            chips.append(CHIP_MATCHING_WEBSITE_DOMAIN)

    if proof_type == _PROOF_DOCUMENT and group.get("text_norm"):
        if _title_contains(group["text_norm"], project_title_norm):
            chips.append(CHIP_MATCHING_DOCUMENT_TITLE)

    # Title correspondence works for every proof type (e.g. a GitHub proof whose
    # scanner title equals the project title, without a stored repo id).
    if CHIP_MATCHING_DOCUMENT_TITLE not in chips and group_title_norm and project_title_norm:
        if _title_contains(group_title_norm, project_title_norm) or _title_contains(
            project_title_norm, group_title_norm
        ):
            chips.append(CHIP_MATCHING_PROJECT_TITLE)

    group_skills = _canonical_skills(group.get("skills"))
    claimed = _canonical_skills(project.get("claimed_skills"))
    if group_skills & claimed:
        chips.append(CHIP_MATCHING_SKILL)

    return chips


_STRONG_CHIPS = {
    CHIP_MATCHING_REPOSITORY,
    CHIP_MATCHING_WEBSITE_DOMAIN,
    CHIP_MATCHING_DOCUMENT_TITLE,
    CHIP_MATCHING_PROJECT_TITLE,
}


def _confidence_label(chips: list[str], overlapping_skill_count: int) -> str:
    """Closed qualitative label from the matched signals — never numeric.

    * Repository identity alone is decisive → Likely match.
    * Any other strong signal (domain / title) + a shared skill → Likely match.
    * A strong signal alone → Possible match.
    * Shared skills only → Possible (2+) or Needs review (1).
    """
    strong = [c for c in chips if c in _STRONG_CHIPS]
    has_skill = CHIP_MATCHING_SKILL in chips
    if CHIP_MATCHING_REPOSITORY in chips:
        return LABEL_LIKELY
    if strong and has_skill:
        return LABEL_LIKELY
    if strong:
        return LABEL_POSSIBLE
    if has_skill and overlapping_skill_count >= 2:
        return LABEL_POSSIBLE
    return LABEL_NEEDS_REVIEW


_CHIP_REASON = {
    CHIP_MATCHING_REPOSITORY: "the proof points at this project's repository",
    CHIP_MATCHING_WEBSITE_DOMAIN: "the website domain matches the project title",
    CHIP_MATCHING_DOCUMENT_TITLE: "the document mentions the project title",
    CHIP_MATCHING_PROJECT_TITLE: "the proof title matches the project title",
}


def _suggestion_reason(
    proof_type: str, proof_title: str, project_title: str, chips: list[str], skills: list[str]
) -> str:
    """One honest sentence: '<proof> may belong to <project> because …'.

    Always hedged ("may belong") — a suggestion is never presented as a
    guaranteed link.
    """
    clauses = [_CHIP_REASON[c] for c in chips if c in _CHIP_REASON]
    if CHIP_MATCHING_SKILL in chips:
        named = ", ".join(skills[:_MAX_SUGGESTION_SKILLS])
        clauses.append(
            f"the proof and the project share claimed skills ({named})" if named
            else "the proof and the project share claimed skills"
        )
    if not clauses:
        clauses.append("safe metadata partially overlaps")
    joined = clauses[0] if len(clauses) == 1 else "; ".join(clauses[:-1]) + " and " + clauses[-1]
    subject = f"{proof_type} “{proof_title}”" if proof_title else proof_type
    return f"{subject} may belong to “{project_title}” because {joined}."


def _safe_suggestion_id(group: dict[str, Any], project_id: str) -> str:
    """Deterministic, non-reversible, collision-safe suggestion id.

    The digest mixes the group's STABLE identity (repo identity or source-row
    ref), its safe discriminators (repo, website domain), the proof type and
    title, and the target project — never the proof title alone, so two
    distinct proofs that happen to share a title get distinct ids. The sha256
    digest is one-way: a private source id feeds it but is never exposed.
    """
    parts = "|".join(
        [
            str(group.get("proof_type") or ""),
            str(group.get("ident") or ""),
            str(group.get("repo_id") or ""),
            str(group.get("domain") or ""),
            _norm(group.get("title")) or "untitled",
            str(project_id or "no-project"),
        ]
    )
    return f"attach-{hashlib.sha256(parts.encode()).hexdigest()[:12]}"


def _suggestion_display_identity(group: dict[str, Any]) -> str:
    """Canonical DISPLAY identity of a proof group, for suggestion dedupe.

    Collapses duplicate-looking suggestions — the same repository, the same
    website domain, or the same document/proof title — into ONE card, while
    keeping genuinely distinct evidence apart. A GitHub group WITHOUT a stable
    repository identity falls back to its per-source-row group ident, so two
    distinct file/line proofs that merely share a title never merge. The value
    is only ever mixed into a dedupe key here (never shown); the group ident is
    itself already hashed before exposure.
    """
    proof_type = str(group.get("proof_type") or "")
    ident = str(group.get("ident") or "")
    if proof_type == _PROOF_GITHUB:
        repo = str(group.get("repo_id") or "")
        return f"repo:{repo}" if repo else ident
    if proof_type == _PROOF_WEBSITE:
        domain = str(group.get("domain") or "")
        if domain:
            return f"domain:{domain}"
        squashed = _squash(group.get("title"))
        return f"site:{squashed}" if squashed else ident
    # Document / Skill Graph / any other suggestible type: same safe title is the
    # same displayed proof.
    title = _norm(group.get("title"))
    return f"title:{title}" if title else ident


def build_attachment_suggestions(
    vault_items: list[dict[str, Any]],
    project_summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Derive owner-only proof-attachment suggestions.

    For each *unattached* proof group, find the best-matching project card via
    deterministic safe-metadata signals and emit one suggestion with a
    qualitative confidence label, evidence-basis chips, an honest reason and
    limitation, and the owner-only project-report route. Purely derived — no
    mutation, no network, no LLM. Groups that match no project are omitted
    (the passport's existing unattached counts still cover them).

    Skill-only overlap is a WEAK signal: when several projects tie on nothing
    but a shared skill, no project is suggested — the proof surfaces as a
    "review manually" row instead of a guess at the first project.
    """
    if not project_summaries:
        return []

    # Suggestions are merged by DISPLAY identity + target project, so two
    # duplicate-looking cards (same repo / website domain / document title
    # pointing at the same project) collapse into one row with the honest
    # grouped proof count summed. The SAME proof suggested to two DIFFERENT
    # projects stays two rows (the target ref is part of the key).
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, str, str]] = []

    def _record(suggestion: dict[str, Any], group: dict[str, Any], project_ref: str) -> None:
        key = (
            str(group.get("proof_type") or ""),
            _suggestion_display_identity(group),
            project_ref,
        )
        existing = merged.get(key)
        if existing is None:
            merged[key] = suggestion
            order.append(key)
            return
        existing["proof_count"] = int(existing.get("proof_count") or 1) + int(
            suggestion.get("proof_count") or 1
        )
        for skill in suggestion.get("likely_skill_names") or []:
            if (
                skill not in existing["likely_skill_names"]
                and len(existing["likely_skill_names"]) < _MAX_SUGGESTION_SKILLS
            ):
                existing["likely_skill_names"].append(skill)

    for group in _group_unattached(vault_items):
        candidates: list[dict[str, Any]] = []
        for project in project_summaries:
            chips = _match_signals(group, project)
            if not chips:
                continue
            overlap = len(
                _canonical_skills(group.get("skills"))
                & _canonical_skills(project.get("claimed_skills"))
            )
            label = _confidence_label(chips, overlap)
            candidates.append(
                {
                    "project": project,
                    "chips": chips,
                    "label": label,
                    "skill_only": not any(c in _STRONG_CHIPS for c in chips),
                    "rank": (_LABEL_RANK.get(label, 9), -len(chips), -overlap),
                }
            )
        if not candidates:
            continue
        candidates.sort(key=lambda c: c["rank"])  # stable: keeps project order on ties
        best = candidates[0]

        proof_title = str(group.get("title") or "").strip()
        likely_skills = [s for s in group.get("skills", []) if str(s).strip()]
        base = {
            "proof_type": group["proof_type"],
            "proof_title": proof_title or group["proof_type"],
            "proof_count": int(group.get("item_count") or 1),
            "likely_skill_names": likely_skills[:_MAX_SUGGESTION_SKILLS],
            "attachment_status": "Not attached to a VBR project",
            "limitation": _SUGGESTION_LIMITATION,
            "action_label": _ACTION_LABEL,
        }

        tied = [c for c in candidates if c["rank"] == best["rank"]]
        if best["skill_only"] and len(tied) > 1:
            # Several projects tie on nothing but skill overlap — never guess
            # one of them. Surface the proof without a suggested project.
            _record(
                {
                    **base,
                    "suggestion_id_safe": _safe_suggestion_id(group, ""),
                    "likely_project_title": "",
                    "likely_project_ref_safe": None,
                    "suggestion_reason": SKILL_TIE_REVIEW_REASON,
                    "evidence_basis_chips": [CHIP_MATCHING_SKILL],
                    "confidence_label": LABEL_NEEDS_REVIEW,
                },
                group,
                "",
            )
            continue

        project = best["project"]
        project_id = str(project.get("project_id") or "")
        # Owner-only report-preview route (private passport surface only).
        project_ref = (
            f"{_PRIVATE_PROJECT_REPORT_PREFIX}{project_id}/report" if project_id else None
        )
        _record(
            {
                **base,
                "suggestion_id_safe": _safe_suggestion_id(group, project_id),
                "likely_project_title": str(project.get("project_title") or ""),
                "likely_project_ref_safe": project_ref,
                "suggestion_reason": _suggestion_reason(
                    group["proof_type"],
                    proof_title,
                    str(project.get("project_title") or ""),
                    best["chips"],
                    likely_skills,
                ),
                "evidence_basis_chips": list(best["chips"]),
                "confidence_label": best["label"],
            },
            group,
            project_ref or "",
        )

    suggestions = [merged[key] for key in order]
    suggestions.sort(
        key=lambda s: (
            _LABEL_RANK.get(s["confidence_label"], 9),
            -len(s["evidence_basis_chips"]),
            s["proof_title"].lower(),
        )
    )
    return suggestions[:_MAX_SUGGESTIONS]


# ── Project strengthening (proof-chain gaps + next best action) ──────────────

# Missing proof-chain source → (qualitative gap label, safe action copy).
_GAP_INFO: dict[str, tuple[str, str]] = {
    _PROOF_GITHUB: (
        "Missing implementation proof",
        "GitHub Proof missing — repository implementation evidence not attached.",
    ),
    _PROOF_WEBSITE: (
        "Missing runtime proof",
        "Attach Website Proof to complete runtime behavior evidence.",
    ),
    _PROOF_DOCUMENT: (
        "Missing corroboration proof",
        "Attach Document Proof to corroborate the project claim.",
    ),
    _PROOF_DEFENSE: (
        "Missing explanation proof",
        "Add Project Defense to explain candidate understanding.",
    ),
    _PROOF_VIDEO: (
        "Missing recorded explanation",
        "Record a Project Defense video to add recorded explanation evidence.",
    ),
}


def proof_chain_gaps(proof_chain: dict[str, Any]) -> list[dict[str, str]]:
    """Qualitative gap objects for a project card's missing proof sources."""
    gaps: list[dict[str, str]] = []
    for source in proof_chain.get("missing") or []:
        label, action = _GAP_INFO.get(str(source), ("Evidence unattached", f"Attach {source}."))
        gaps.append({"source": str(source), "gap_label": label, "action": action})
    return gaps


def chain_label(proof_chain: dict[str, Any]) -> str:
    """Qualitative proof-chain label for a project card — never a score.

    "Strong chain" requires CORE evidence, never source count alone: GitHub
    (implementation) and Website (runtime/product behavior) must both be
    attached before four-plus sources can read as strong. Document / Defense /
    Video sources on their own top out at the safer labels below, however many
    of them are attached.
    """
    attached = int(proof_chain.get("attached_count") or 0)
    total = int(proof_chain.get("total_count") or 5)
    if attached == 0:
        return "Evidence unattached"
    if not proof_chain.get("github"):
        return "Needs implementation proof"
    if not proof_chain.get("website"):
        return "Needs runtime proof"
    # Core evidence (GitHub + Website) is present from here down.
    if attached >= total or attached >= 4:
        return "Strong chain"
    if attached >= 3:
        return "Good supporting chain"
    return "Evidence chain incomplete"


def suggested_attachments_for_project(
    project_id: str, suggestions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The compact per-project view of the suggestions that target this project."""
    ref = f"{_PRIVATE_PROJECT_REPORT_PREFIX}{project_id}/report"
    rows = [
        {
            "suggestion_id_safe": s["suggestion_id_safe"],
            "proof_type": s["proof_type"],
            "proof_title": s["proof_title"],
            "confidence_label": s["confidence_label"],
            "suggestion_reason": s["suggestion_reason"],
            "action_label": s["action_label"],
        }
        for s in suggestions
        if s.get("likely_project_ref_safe") == ref
    ]
    return rows[:_MAX_PROJECT_SUGGESTIONS]


def next_best_action(
    proof_chain: dict[str, Any], project_suggestions: list[dict[str, Any]]
) -> str | None:
    """One safe 'do this next' sentence for a project card, or None when the
    chain is complete and nothing is suggested."""
    if project_suggestions:
        top = project_suggestions[0]
        return (
            f"Review and attach the suggested {top['proof_type']} "
            f"“{top['proof_title']}” ({top['confidence_label'].lower()})."
        )
    gaps = proof_chain_gaps(proof_chain)
    if gaps:
        return gaps[0]["action"]
    return None
