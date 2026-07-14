"""Attachment Intelligence Cleanup (Passport 1B Step 4) — centralized state.

One place that answers, for every proof in the student's vault: is it
**attached**, **suggested**, or **unattached** — and why?

* **Attached** — the student explicitly attached the proof to a project
  (``vbr_projects.metadata.attached_proofs``) or it was created inside a
  project session (Project Defense / Video). Deterministic, owner-safe links
  only; these are the ONLY proofs that may count as project evidence.
* **Suggested** — safe metadata (repository identity, website domain, titles,
  shared skills) points at a likely project, but nothing is confirmed.
  Suggested evidence is NEVER counted as attached or verified, and never
  reaches a public surface.
* **Unattached** — valid vault proof with no project link and no safe
  suggestion. Shown honestly, never guessed onto a project.

Hard rules (same contract as ``passport_attachment_intelligence``):

* Deterministic only — no LLM calls, no crawling, no recomputation from raw
  evidence. Derivation only; nothing is mutated or attached here.
* Qualitative only — closed relation-strength labels (``deterministic`` /
  ``likely`` / ``weak`` / ``none``), never numeric scores.
* Safe display fields only — an entry never carries a source id, source
  table, storage path, signed URL, raw text, or provider payload. Entry ids
  are one-way sha256 digests.
* Duplicate rows of the same real-world proof collapse into ONE entry
  (``duplicate_count`` keeps the honest row count) — but the same repository
  attached to two DIFFERENT projects stays two entries.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlsplit

from app.services.safe_public_url import is_safe_public_url
from app.services.passport_attachment_intelligence import (
    CHIP_MATCHING_REPOSITORY,
    LABEL_LIKELY,
    SKILL_TIE_REVIEW_REASON,
    _canonical_skills,
    _confidence_label,
    _group_unattached,
    _item_domain,
    _LABEL_RANK,
    _match_signals,
    _norm,
    _repo_identity,
    _STRONG_CHIPS,
)

__all__ = [
    "classify_vault_attachments",
    "suggested_evidence_for_project",
    "STATE_ATTACHED",
    "STATE_SUGGESTED",
    "STATE_UNATTACHED",
    "STRENGTH_DETERMINISTIC",
    "STRENGTH_LIKELY",
    "STRENGTH_WEAK",
    "STRENGTH_NONE",
    "SUGGESTED_STATUS_LABEL",
    "REASON_LABELS",
]

# ── Closed vocabularies ───────────────────────────────────────────────────────

STATE_ATTACHED = "attached"
STATE_SUGGESTED = "suggested"
STATE_UNATTACHED = "unattached"

# Relation strength is a closed label set — never a numeric confidence.
STRENGTH_DETERMINISTIC = "deterministic"
STRENGTH_LIKELY = "likely"
STRENGTH_WEAK = "weak"
STRENGTH_NONE = "none"

# Reason codes (closed set).
REASON_USER_ATTACHED = "user_attached"
REASON_EXACT_PROJECT_ID = "exact_project_id_match"
REASON_EXACT_REPO = "exact_repo_match"
REASON_EXACT_DOCUMENT = "exact_document_attachment"
REASON_EXACT_WEBSITE = "exact_website_attachment"
REASON_DEFENSE_SESSION = "project_defense_session"
REASON_TITLE_SIMILARITY = "title_similarity_suggestion"
REASON_SKILL_OVERLAP = "skill_overlap_suggestion"
REASON_REPO_SUGGESTION = "repo_owner_repo_suggestion"
REASON_NO_MATCH = "no_match"

# Safe, recruiter-style display labels for each reason code.
REASON_LABELS: dict[str, str] = {
    REASON_USER_ATTACHED: "Attached by the candidate",
    REASON_EXACT_PROJECT_ID: "Linked to this project",
    REASON_EXACT_REPO: "Repository matches the project",
    REASON_EXACT_DOCUMENT: "Document attached to the project",
    REASON_EXACT_WEBSITE: "Website proof attached to the project",
    REASON_DEFENSE_SESSION: "Recorded in this project's defense session",
    REASON_TITLE_SIMILARITY: "Titles look similar — review before attaching",
    REASON_SKILL_OVERLAP: "Shares claimed skills — review before attaching",
    REASON_REPO_SUGGESTION: "Repository name matches — review before attaching",
    REASON_NO_MATCH: "No matching project found",
}

ATTACHED_STATUS_LABEL = "Attached"
SUGGESTED_STATUS_LABEL = "Suggested — not counted until attached"
UNATTACHED_STATUS_LABEL = "Not attached to a project"

# Canonical proof-source labels (mirrors student_proof_vault_service).
_PROOF_GITHUB = "GitHub Proof"
_PROOF_DOCUMENT = "Document Proof"
_PROOF_WEBSITE = "Website Proof"
_PROOF_DEFENSE = "Project Defense"
_PROOF_VIDEO = "Video Evidence"

_PRIVATE_PROJECT_REPORT_PREFIX = "/student/vbr/projects/"

_MAX_ENTRY_SKILLS = 4
_MAX_ATTACHED_ENTRIES = 40
_MAX_SUGGESTED_ENTRIES = 12
_MAX_UNATTACHED_ENTRIES = 40

# ── Safe display-value sanitizer (fail closed) ────────────────────────────────
# Every display string an entry carries (title, project titles, skill names) is
# ultimately user/metadata derived — a document "title" can literally be a local
# ``file_path`` (student_proof_vault_service falls back to it), a skill label can
# carry a pasted secret, a website title can be a signed storage URL. Field-name
# whitelisting alone therefore isn't enough: every display VALUE is scrubbed
# here, and anything that still smells private is replaced with a neutral
# proof-type label (never echoed). Mirrors the value rules of
# ``public_report_safety_service`` without importing it (that module reaches
# back through the report builders into this one — import cycle).

# The only proof-type labels this vault mints; an unknown label is metadata-
# derived and falls back to the neutral "Proof".
_KNOWN_PROOF_TYPES = {
    _PROOF_GITHUB,
    _PROOF_DOCUMENT,
    _PROOF_WEBSITE,
    _PROOF_DEFENSE,
    _PROOF_VIDEO,
    "Skill Graph",
}
_NEUTRAL_PROOF_LABEL = "Proof"
_NEUTRAL_PROJECT_LABEL = "Project"

# A display string longer than any honest title is treated as leaked raw
# document/transcript text and replaced, never truncated-and-shown.
_MAX_DISPLAY_CHARS = 160

# Local absolute paths (``/Users/…``, ``/home/…``, ``/tmp/…``, …) and bare
# multi-segment paths (``/a/b/c.pdf``), Windows/UNC paths (``C:\Users\…``).
_LOCAL_PATH_RE = re.compile(
    r"(?i)(?:^|[\s\"'(<])/(?:users|home|tmp|private|var|etc|opt|srv|mnt|volumes|data|uploads|storage)/\S+"
)
_BARE_PATH_RE = re.compile(r"^/(?:[\w.@ -]+/)+[\w.@ -]+$")
_WINDOWS_PATH_RE = re.compile(r"\b[a-zA-Z]:[\\/]\S+|\\\\[\w.-]+\\\S+")

# Non-web URI schemes (``s3://``, ``gs://``, ``file://``, ``blob:``, …) and
# storage/signed-object URL fragments (Supabase, generic signed objects).
_STORAGE_SCHEME_RE = re.compile(r"(?i)\b(?:s3|gs|wasb|abfss?|file|blob|ftp)://\S*|\bdata:[\w.+-]+/[\w.+-]+")
_STORAGE_FRAGMENTS = (
    "/storage/v1/object",
    "/object/sign",
    "supabase.co/storage",
    "vbr/sessions/",
    "/tmp/",
    "-----begin",
)

# Credential material: ``api_key=…`` / ``token: …`` / ``Bearer …`` /
# ``sk-…`` / ``ghp_…`` / ``github_pat_…`` style secrets.
_SECRET_KV_RE = re.compile(
    r"(?i)(?<![\w-])(?:api[_-]?keys?|access[_-]?tokens?|refresh[_-]?tokens?|auth[_-]?tokens?|"
    r"session[_-]?tokens?|client[_-]?secrets?|secret[_-]?keys?|service[_-]?role[_-]?keys?|"
    r"private[_-]?keys?|anon[_-]?keys?|secrets?|passwords?|passwd|pwd|tokens?|signatures?|sig|"
    r"x-amz-[\w-]+|x-goog-[\w-]+)\s*[=:]\s*\S+"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[\w.\-~+/=]{6,}")
_SECRET_TOKEN_RE = re.compile(r"(?i)\b(?:sk|ghp|gho|ghs|ghu|github_pat)[-_][A-Za-z0-9_\-]{6,}")

# Private identifiers: ``source_id=…`` / ``user_id: …`` fragments, bare UUIDs,
# long hex blobs, and ``user_<blob>`` / ``project_<blob>`` prefixed ids.
_PRIVATE_ID_KV_RE = re.compile(
    r"(?i)\b(?:source|private|provider|user|student|project|session|account|owner|internal|row|record)"
    r"[_-]?ids?\s*[=:]\s*\S+"
)
_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_HEX_BLOB_RE = re.compile(r"\b[0-9a-fA-F]{16,}\b")
_PREFIXED_ID_RE = re.compile(
    r"(?i)\b(?:user|student|project|source|provider|session|account|artifact|report)[_-][A-Za-z0-9]{12,}\b"
)

_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# Numeric score/confidence-style strings (``87%``, ``0.92``, ``score: 87``,
# ``87/100``) — the vault is qualitative-only, so these never belong on display.
_SCORE_FRAGMENT_RE = re.compile(
    r"(?i)\b(?:score|confidence|rating|rank(?:ing)?|percentile|accuracy|trust)s?\b\s*[:=]?\s*\d"
    r"|\b\d+(?:\.\d+)?\s*%|\b\d+(?:\.\d+)?\s*/\s*\d+\b"
)

_URL_MARKER_RE = re.compile(r"(?i)\b(?:https?://|www\.)")

# Safe ``owner/repo`` display shape (what ``_repo_identity`` mints).
_SAFE_REPO_DISPLAY_RE = re.compile(r"^[a-z0-9][\w.-]*/[\w.-]+$")

# Relative storage/uploaded-file paths — a ``file_path`` fallback title needn't
# be absolute to leak (``private-bucket/users/alice/report.pdf``,
# ``uploads/user-123/report.pdf``). Any multi-segment slash path that ends in a
# common document/media file extension is treated as a storage path, as is any
# value rooted at a known storage/upload directory. A safe ``owner/repo`` has a
# single slash and no file extension, so it never matches.
_RELATIVE_STORAGE_PATH_RE = re.compile(
    r"(?:^|[\s\"'(<])[\w.@-]+(?:/[\w.@ -]+)*/[\w.@ -]*"
    r"\.(?:pdf|docx?|txt|json|csv|png|jpe?g|webm|mp4|wav)\b",
    re.IGNORECASE,
)
_STORAGE_ROOT_PATH_RE = re.compile(
    r"^(?:private-bucket|uploads?|storage|buckets?|documents?|files?|media|assets|"
    r"attachments?|objects?)/\S+",
    re.IGNORECASE,
)

# JSON-shaped / provider payloads — a title that is really a serialized provider
# blob (``{"provider":"openai","model":"gpt-4"}``, ``["raw","provider"]``) or
# that carries obvious provider JSON keys is never an honest display value.
_JSON_SHAPE_RE = re.compile(r"^\s*[\{\[].*[\}\]]\s*$", re.DOTALL)
_PROVIDER_JSON_KEY_RE = re.compile(
    r'"(?:provider|model|source_id|metadata|raw_text)"\s*:', re.IGNORECASE
)

# Raw transcript/document-shaped text — a display value that is really pasted
# raw evidence content (``Raw transcript: …``, ``OCR text: …``) or leaks
# internal-deployment phrasing rather than a title.
_RAW_EVIDENCE_RE = re.compile(
    r"\b(?:raw\s+|full\s+)?transcript\s*:"
    r"|\braw\s+document\s*:"
    r"|\bdocument\s+text\s*:"
    r"|\bocr\s+text\s*:"
    r"|\bextracted\s+text\s*:"
    r"|\binternal\s+deployment\b"
    r"|\bprivate\s+endpoint\b",
    re.IGNORECASE,
)


def _display_value_unsafe(raw: str) -> bool:
    """True when a display string still smells like a path/secret/private id."""
    lowered = raw.lower()
    if len(raw) > _MAX_DISPLAY_CHARS:
        return True
    if any(fragment in lowered for fragment in _STORAGE_FRAGMENTS):
        return True
    return bool(
        _LOCAL_PATH_RE.search(raw)
        or _BARE_PATH_RE.match(raw)
        or _WINDOWS_PATH_RE.search(raw)
        or _STORAGE_SCHEME_RE.search(raw)
        or _RELATIVE_STORAGE_PATH_RE.search(raw)
        or _STORAGE_ROOT_PATH_RE.match(raw)
        or _JSON_SHAPE_RE.match(raw)
        or _PROVIDER_JSON_KEY_RE.search(raw)
        or _RAW_EVIDENCE_RE.search(raw)
        or _SECRET_KV_RE.search(raw)
        or _BEARER_RE.search(raw)
        or _SECRET_TOKEN_RE.search(raw)
        or _PRIVATE_ID_KV_RE.search(raw)
        or _UUID_RE.search(raw)
        or _HEX_BLOB_RE.search(raw)
        or _PREFIXED_ID_RE.search(raw)
        or _EMAIL_RE.search(raw)
        or _SCORE_FRAGMENT_RE.search(raw)
    )


def _safe_url_display(raw: str, fallback: str) -> str:
    """Display form of a URL-shaped value — never a signed/tokenized/private URL.

    A safe GitHub repo URL displays as ``owner/repo``; a genuinely public URL
    passes through; anything else degrades to its bare public hostname when one
    exists, otherwise to the neutral proof-type label.
    """
    candidate = raw if "://" in raw else f"https://{raw}"
    ident = _repo_identity(candidate)
    if "github.com" in candidate.lower() and ident and _SAFE_REPO_DISPLAY_RE.match(ident):
        return ident
    if is_safe_public_url(candidate) and not _display_value_unsafe(raw):
        return raw
    try:
        host = (urlsplit(candidate).hostname or "").lower()
    except ValueError:
        return fallback
    # Hostname only — never the path or query of a signed/storage URL.
    if host and is_safe_public_url(f"https://{host}/"):
        return host
    return fallback


def _neutral_proof_label(proof_type: str) -> str:
    return proof_type if proof_type in _KNOWN_PROOF_TYPES else _NEUTRAL_PROOF_LABEL


def _safe_display_title(value: Any, proof_type: str) -> str:
    """Public-safe entry title; falls back to the neutral proof-type label."""
    fallback = _neutral_proof_label(proof_type)
    raw = " ".join(str(value or "").split()).strip()
    if not raw:
        return fallback
    if _URL_MARKER_RE.search(raw) and len(raw.split()) == 1:
        return _safe_url_display(raw, fallback)
    if proof_type == _PROOF_GITHUB and _SAFE_REPO_DISPLAY_RE.match(raw.lower()):
        return raw
    if _display_value_unsafe(raw) or not any(ch.isalpha() for ch in raw):
        return fallback
    return raw


def _safe_project_title_display(value: Any) -> str:
    """Public-safe project title; an unsafe title becomes the neutral 'Project'."""
    raw = " ".join(str(value or "").split()).strip()
    if not raw:
        return ""
    if _URL_MARKER_RE.search(raw) or _display_value_unsafe(raw) or not any(ch.isalpha() for ch in raw):
        return _NEUTRAL_PROJECT_LABEL
    return raw


def _safe_skill_display(value: Any) -> str:
    """Public-safe skill label; an unsafe label is dropped, never echoed."""
    raw = " ".join(str(value or "").split()).strip()
    if not raw:
        return ""
    if _URL_MARKER_RE.search(raw) or _display_value_unsafe(raw) or not any(ch.isalpha() for ch in raw):
        return ""
    return raw


def _project_ref(project_id: str) -> str:
    """Owner-only project-report route (private surfaces only)."""
    return f"{_PRIVATE_PROJECT_REPORT_PREFIX}{project_id}/report"


def _entry_id(*parts: str) -> str:
    """Deterministic, one-way, collision-safe entry id (never a raw source id)."""
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]
    return f"att-{digest}"


def _item_identity(item: dict[str, Any]) -> str:
    """The stable real-world identity of one vault row, per proof type.

    Duplicate rows of the same proof share this identity so they collapse into
    one display entry:

    * GitHub — normalized ``owner/name`` repo identity (a title alone is never
      identity; ownerless rows stay on their own source row).
    * Website — safe hostname, else normalized title.
    * Document — normalized safe title.
    * Project Defense / Video — the owning project (attempts collapse).
    * Everything else — the source row itself.

    The source-row fallback feeds only the one-way entry-id digest — it is
    never exposed in output.
    """
    proof_type = str(item.get("proof_type") or "")
    row_ref = f"row:{item.get('source_table')}:{item.get('source_id')}"
    if proof_type == _PROOF_GITHUB:
        ident = (
            _repo_identity(item.get("repo_url"))
            or _repo_identity(item.get("public_url"))
            or _repo_identity(item.get("title"))
        )
        return f"repo:{ident}" if ident else row_ref
    if proof_type == _PROOF_WEBSITE:
        domain = _item_domain(item)
        if domain:
            return f"domain:{domain}"
        title = _norm(item.get("title"))
        return f"site:{title}" if title else row_ref
    if proof_type == _PROOF_DOCUMENT:
        title = _norm(item.get("title"))
        return f"doc:{title}" if title else row_ref
    if proof_type in (_PROOF_DEFENSE, _PROOF_VIDEO):
        pids = item.get("attached_project_ids") or []
        return f"session:{pids[0]}" if pids else row_ref
    return row_ref


def _group_display_identity(group: dict[str, Any]) -> str:
    """Display-level identity for one unattached proof group.

    ``_group_unattached`` merges GitHub rows by repo identity but keeps
    document/website/skill-graph rows one group per source row. For DISPLAY,
    duplicate documents with the same safe title (re-uploads, per-skill rows)
    and duplicate websites with the same hostname collapse into one entry.
    """
    proof_type = str(group.get("proof_type") or "")
    if proof_type == _PROOF_GITHUB:
        return str(group.get("ident") or "")
    if proof_type == _PROOF_WEBSITE and group.get("domain"):
        return f"domain:{group['domain']}"
    if proof_type == _PROOF_WEBSITE and group.get("repo_id"):
        return f"repo:{group['repo_id']}"
    if proof_type == _PROOF_WEBSITE and group.get("text_norm"):
        return f"hint:{group['text_norm']}"
    title = _norm(group.get("title"))
    if title:
        return f"title:{title}"
    return str(group.get("ident") or "")


def _merge_unattached_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse unattached groups that share the same display identity."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for group in groups:
        key = (str(group.get("proof_type") or ""), _group_display_identity(group))
        target = merged.get(key)
        if target is None:
            merged[key] = dict(group)
            merged[key]["skills"] = list(group.get("skills") or [])
            order.append(key)
            continue
        target["item_count"] = int(target.get("item_count") or 0) + int(group.get("item_count") or 0)
        for skill in group.get("skills") or []:
            if skill not in target["skills"]:
                target["skills"].append(skill)
        if not target.get("title") and group.get("title"):
            target["title"] = group["title"]
        if len(str(group.get("text_norm") or "")) > len(str(target.get("text_norm") or "")):
            target["text_norm"] = group["text_norm"]
        for field in ("repo_id", "domain"):
            if not target.get(field) and group.get(field):
                target[field] = group[field]
    return [merged[key] for key in order]


def _attached_reason(item: dict[str, Any], projects_by_id: dict[str, dict[str, Any]]) -> str:
    """Reason code for a deterministically attached vault item."""
    proof_type = str(item.get("proof_type") or "")
    if proof_type in (_PROOF_DEFENSE, _PROOF_VIDEO):
        return REASON_DEFENSE_SESSION
    if proof_type == _PROOF_DOCUMENT:
        return REASON_EXACT_DOCUMENT
    if proof_type == _PROOF_WEBSITE:
        return REASON_EXACT_WEBSITE
    if proof_type == _PROOF_GITHUB:
        ident = (
            _repo_identity(item.get("repo_url"))
            or _repo_identity(item.get("public_url"))
            or _repo_identity(item.get("title"))
        )
        if ident:
            for pid in item.get("attached_project_ids") or []:
                project = projects_by_id.get(str(pid)) or {}
                if _repo_identity(project.get("repo_full_name")) == ident:
                    return REASON_EXACT_REPO
        return REASON_USER_ATTACHED
    # Skill Graph pipelines and any future source: attached via an explicit
    # project-id link in the project's attached_proofs metadata.
    return REASON_EXACT_PROJECT_ID


def _suggestion_reason_code(chips: list[str]) -> str:
    """Reason code for a suggested (non-deterministic) match."""
    if CHIP_MATCHING_REPOSITORY in chips:
        return REASON_REPO_SUGGESTION
    if any(chip in _STRONG_CHIPS for chip in chips):
        return REASON_TITLE_SIMILARITY
    return REASON_SKILL_OVERLAP


def _merge_skills(existing: list[str], item: dict[str, Any]) -> None:
    skill = str(item.get("skill_name") or "").strip()
    if skill and skill not in existing:
        existing.append(skill)


def _make_entry(
    *,
    state: str,
    proof_type: str,
    display_title: str,
    reason: str,
    strength: str,
    project_titles: list[str],
    project_refs: list[str],
    skill_names: list[str],
    duplicate_count: int,
    identity: str,
) -> dict[str, Any]:
    """One safe display entry — whitelisted fields only, no raw metadata.

    Field names are whitelisted AND every display VALUE is sanitized here: a
    title/project/skill string that still looks like a path, storage/signed
    URL, secret, private id, raw text, or numeric score is replaced with a
    neutral label (or dropped), never echoed.
    """
    status_label = {
        STATE_ATTACHED: ATTACHED_STATUS_LABEL,
        STATE_SUGGESTED: SUGGESTED_STATUS_LABEL,
        STATE_UNATTACHED: UNATTACHED_STATUS_LABEL,
    }[state]
    safe_proof_label = _neutral_proof_label(proof_type)
    safe_skills: list[str] = []
    for skill in skill_names:
        cleaned = _safe_skill_display(skill)
        if cleaned and cleaned not in safe_skills:
            safe_skills.append(cleaned)
    return {
        "entry_id_safe": _entry_id(state, proof_type, identity, *project_refs),
        "proof_type": safe_proof_label,
        "display_title": _safe_display_title(display_title, proof_type),
        "source_label": safe_proof_label,
        "attachment_state": state,
        "relation_reason": reason,
        "relation_strength": strength,
        "reason_label": REASON_LABELS.get(reason, ""),
        "status_label": status_label,
        "project_titles": [
            _safe_project_title_display(title) for title in project_titles if str(title or "").strip()
        ],
        "project_refs_safe": project_refs,
        "skill_names": safe_skills[:_MAX_ENTRY_SKILLS],
        "duplicate_count": max(1, duplicate_count),
    }


def classify_vault_attachments(
    vault_items: list[dict[str, Any]],
    project_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify every vault proof into attached / suggested / unattached.

    ``project_summaries`` entries need only safe card metadata: ``project_id``,
    ``project_title``, ``repo_full_name`` and ``claimed_skills``.

    Returns disjoint, deduplicated display buckets plus their counts — each
    real-world proof appears in exactly ONE bucket, so counts never inflate
    from duplicate rows and suggested evidence never counts as attached.
    Purely derived: no mutation, no network, no LLM.
    """
    projects_by_id = {str(p.get("project_id") or ""): p for p in project_summaries}
    titles_by_id = {
        pid: str(p.get("project_title") or "") for pid, p in projects_by_id.items()
    }

    # ── Attached: deterministic project links, deduped by identity + projects ──
    attached_groups: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]] = {}
    attached_order: list[tuple[str, str, tuple[str, ...]]] = []
    for item in vault_items:
        if not item.get("is_attached_to_project"):
            continue
        proof_type = str(item.get("proof_type") or "")
        pids = tuple(sorted(str(p) for p in (item.get("attached_project_ids") or []) if p))
        # Same repo attached to two DIFFERENT projects must stay two entries —
        # the project scope is part of the dedupe key.
        key = (proof_type, _item_identity(item), pids)
        group = attached_groups.get(key)
        if group is None:
            group = {
                "proof_type": proof_type,
                "identity": _item_identity(item),
                "title": "",
                "skills": [],
                "reason": _attached_reason(item, projects_by_id),
                "project_ids": list(pids),
                "row_count": 0,
                "session_ids": set(),
            }
            attached_groups[key] = group
            attached_order.append(key)
        group["row_count"] += 1
        # Defense/video attempts: count distinct sessions, not per-skill rows.
        if proof_type in (_PROOF_DEFENSE, _PROOF_VIDEO):
            group["session_ids"].add(str(item.get("source_id") or ""))
        title = str(item.get("title") or "").strip()
        if title and not group["title"]:
            group["title"] = title
        _merge_skills(group["skills"], item)

    attached_entries: list[dict[str, Any]] = []
    for key in attached_order:
        group = attached_groups[key]
        if group["proof_type"] in (_PROOF_DEFENSE, _PROOF_VIDEO):
            duplicate_count = len(group["session_ids"]) or 1
        else:
            duplicate_count = group["row_count"]
        attached_entries.append(
            _make_entry(
                state=STATE_ATTACHED,
                proof_type=group["proof_type"],
                display_title=group["title"],
                reason=group["reason"],
                strength=STRENGTH_DETERMINISTIC,
                project_titles=[
                    titles_by_id.get(pid, "") for pid in group["project_ids"] if titles_by_id.get(pid)
                ],
                project_refs=[_project_ref(pid) for pid in group["project_ids"]],
                skill_names=group["skills"],
                duplicate_count=duplicate_count,
                identity=group["identity"],
            )
        )

    # ── Unattached rows: group duplicates, then split suggested vs unmatched ──
    suggested_entries: list[dict[str, Any]] = []
    unattached_entries: list[dict[str, Any]] = []
    for group in _merge_unattached_groups(_group_unattached(vault_items)):
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

        title = str(group.get("title") or "").strip()
        skills = [s for s in group.get("skills", []) if str(s).strip()]
        identity = str(group.get("ident") or "")
        duplicate_count = int(group.get("item_count") or 1)

        if not candidates:
            unattached_entries.append(
                _make_entry(
                    state=STATE_UNATTACHED,
                    proof_type=group["proof_type"],
                    display_title=title,
                    reason=REASON_NO_MATCH,
                    strength=STRENGTH_NONE,
                    project_titles=[],
                    project_refs=[],
                    skill_names=skills,
                    duplicate_count=duplicate_count,
                    identity=identity,
                )
            )
            continue

        candidates.sort(key=lambda c: c["rank"])  # stable: keeps project order on ties
        best = candidates[0]
        tied = [c for c in candidates if c["rank"] == best["rank"]]
        if best["skill_only"] and len(tied) > 1:
            # Several projects tie on nothing but a shared skill — never guess
            # one. The proof stays a suggestion WITHOUT a named project.
            entry = _make_entry(
                state=STATE_SUGGESTED,
                proof_type=group["proof_type"],
                display_title=title,
                reason=REASON_SKILL_OVERLAP,
                strength=STRENGTH_WEAK,
                project_titles=[],
                project_refs=[],
                skill_names=skills,
                duplicate_count=duplicate_count,
                identity=identity,
            )
            entry["reason_label"] = SKILL_TIE_REVIEW_REASON
            suggested_entries.append(entry)
            continue

        project = best["project"]
        project_id = str(project.get("project_id") or "")
        suggested_entries.append(
            _make_entry(
                state=STATE_SUGGESTED,
                proof_type=group["proof_type"],
                display_title=title,
                reason=_suggestion_reason_code(best["chips"]),
                # likely/weak may ONLY ever be suggested — never attached.
                strength=STRENGTH_LIKELY if best["label"] == LABEL_LIKELY else STRENGTH_WEAK,
                project_titles=[str(project.get("project_title") or "")],
                project_refs=[_project_ref(project_id)] if project_id else [],
                skill_names=skills,
                duplicate_count=duplicate_count,
                identity=identity,
            )
        )

    # Defense/video rows are always attached at collection time, but fail safe:
    # an unattached row of a non-suggestible type (which ``_group_unattached``
    # skips) still lands honestly in the unattached bucket.
    _suggestible = {_PROOF_GITHUB, _PROOF_DOCUMENT, _PROOF_WEBSITE, "Skill Graph"}
    leftovers: dict[tuple[str, str], dict[str, Any]] = {}
    for item in vault_items:
        if item.get("is_attached_to_project"):
            continue
        if str(item.get("proof_type") or "") in _suggestible:
            continue
        key = (str(item.get("proof_type") or ""), _item_identity(item))
        group = leftovers.get(key)
        if group is None:
            group = {"title": str(item.get("title") or ""), "skills": [], "count": 0}
            leftovers[key] = group
        group["count"] += 1
        _merge_skills(group["skills"], item)
    for (proof_type, identity), group in leftovers.items():
        unattached_entries.append(
            _make_entry(
                state=STATE_UNATTACHED,
                proof_type=proof_type,
                display_title=group["title"],
                reason=REASON_NO_MATCH,
                strength=STRENGTH_NONE,
                project_titles=[],
                project_refs=[],
                skill_names=group["skills"],
                duplicate_count=group["count"],
                identity=identity,
            )
        )

    attached_entries = attached_entries[:_MAX_ATTACHED_ENTRIES]
    suggested_entries = suggested_entries[:_MAX_SUGGESTED_ENTRIES]
    unattached_entries = unattached_entries[:_MAX_UNATTACHED_ENTRIES]
    return {
        "attached": attached_entries,
        "suggested": suggested_entries,
        "unattached": unattached_entries,
        # Disjoint deduplicated counts: suggested/unattached NEVER count as
        # attached, and duplicate rows never inflate any bucket.
        "attached_count": len(attached_entries),
        "suggested_count": len(suggested_entries),
        "unattached_count": len(unattached_entries),
        "note": SUGGESTED_STATUS_LABEL,
    }


def suggested_evidence_for_project(
    overview: dict[str, Any], project_id: str
) -> list[dict[str, Any]]:
    """The suggested entries pointing at ONE project (for its report preview).

    Owner-only; the public project report never carries these.
    """
    ref = _project_ref(str(project_id))
    return [
        entry
        for entry in overview.get("suggested") or []
        if ref in (entry.get("project_refs_safe") or [])
    ]
