"""Public recruiter-safe VBR report link for a Project Defense project (v1).

This module turns the *student-owned* Final VBR Report preview
(``vbr_student_report.build_student_vbr_report``, built from a ``vbr_projects``
row + its Project Defense evidence) into a read-only, tokenized public
recruiter link.

Two surfaces live here:

* Owner-only operations — ``publish_project_report`` /
  ``unpublish_project_report`` / ``get_project_report_publish_status``. These
  mint / clear / report the project's ``public_report_token``. Ownership is
  always enforced via ``get_owned_vbr_project_or_404`` because ``get_db``
  returns the service-role client which bypasses RLS.
* Public read — ``build_public_project_report`` resolves a project by its
  active ``public_report_token`` (no auth) and returns a sanitized public
  projection of the report-safe summary.

The public projection re-uses the already-sanitized student report summaries
(qualitative evidence labels only — never numeric trust scores) and runs an
additional defence-in-depth scan so it never returns:

* raw transcript / document text, raw GitHub snapshots, full ``artifact_data``
* storage paths, signed/upload URLs, bucket names, local/temp paths
* any token other than the public token the recruiter already has
* internal IDs not needed publicly (project_id, session_id, question_id),
  the student's private email, or the auth user ID

This module never calls any LLM.
"""

from __future__ import annotations

import logging
import re
import secrets

from datetime import UTC, datetime
from typing import Any, Callable

from fastapi import HTTPException, status

from app.api.v1.endpoints.vbr_projects import get_owned_vbr_project_or_404
from app.services.passport_disclosure import (
    HIDDEN,
    SUMMARY,
    VIEWABLE,
    VISIBLE,
    EffectiveDisclosure,
    load_effective_disclosure,
)
from app.services.passport_visibility import owner_passport_is_public
from app.services.safe_public_url import is_safe_public_url
from app.services.skill_normalization import canonical_skill, skill_category, skill_slug
from app.services.vbr_student_report import build_student_vbr_report

logger = logging.getLogger(__name__)

_PROJECTS_TABLE = "vbr_projects"
_USERS_TABLE = "users"
_PASSPORTS_TABLE = "vbr_work_passports"

_TOKEN_GENERATION_ATTEMPTS = 5

# Cheap plausibility gate for inbound public tokens: minted tokens are
# ``secrets.token_urlsafe(24)`` (32 URL-safe chars), so anything outside this
# shape can be rejected before touching the database. Bounds are deliberately
# loose so historical/legacy token lengths keep working.
_PLAUSIBLE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def is_plausible_public_token(token: Any) -> bool:
    """True when ``token`` is shaped like a mintable public report token."""
    return isinstance(token, str) and bool(_PLAUSIBLE_TOKEN_RE.match(token))

_REPORT_TITLE = "Verified Build Report"
_PUBLIC_PATH_PREFIX = "/vbr/report/"
_PASSPORT_PATH_PREFIX = "/p/"

_VERIFICATION_NOTE = (
    "This is an evidence-backed Verified Build Report shared by the candidate. "
    "Evidence is described as observed, supporting, or process evidence — never "
    "as a number, percentage, or ranking — and is not a guarantee of employment, "
    "skill mastery, or identity. Project Defense reflects the candidate's own "
    "explanation of their work, not independent proof of code authorship."
)

__all__ = [
    "publish_project_report",
    "unpublish_project_report",
    "get_project_report_publish_status",
    "build_public_project_report",
    "_scrub_public_report",
    "_scrub_text",
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ── Unsafe-field scan (defence in depth) ─────────────────────────────────────

_UNSAFE_KEYS = {
    "storagepath",
    "storage_path",
    "mediastoragepath",
    "media_storage_path",
    "videopath",
    "video_path",
    "signedurl",
    "signed_url",
    "signedpath",
    "signed_path",
    "uploadurl",
    "upload_url",
    "bucket",
    "bucketname",
    "bucket_name",
    "publictoken",
    "public_token",
    "publicreporttoken",
    "public_report_token",
    "accesstoken",
    "access_token",
    "localpath",
    "local_path",
    "temppath",
    "temp_path",
    "tmppath",
    "tmp_path",
    "raw",
    "rawmetadata",
    "raw_metadata",
    "artifactdata",
    "artifact_data",
    "fulltext",
    "full_text",
    "fulltranscript",
    "full_transcript",
    "transcripttext",
    "transcript_text",
    "email",
    "useremail",
    "user_email",
    "userid",
    "user_id",
    "authuserid",
    "auth_user_id",
}

_UNSAFE_VALUE_PATTERNS = (
    "vbr/sessions/",
    "/tmp/",
    "supabase.co/storage",
    "/storage/v1/object",
    "signed_url",
    "signedurl",
    "signedurl",
    "bearer ",
)

# A world-readable Supabase Storage *public-bucket* object URL
# (``/storage/v1/object/public/<bucket>/…``) is safe to surface publicly — e.g.
# the recruiter-facing passport avatar photo. It is deliberately NOT treated as a
# private storage/signed URL: only public buckets serve via ``/object/public/``,
# whereas private objects use ``/object/sign/`` (token-bearing),
# ``/object/authenticated/``, or ``/object/upload/`` — all of which remain blocked
# by the patterns above. Anchored end-to-end so no other content can ride along.
_PUBLIC_STORAGE_OBJECT_URL_RE = re.compile(
    r"^https://[a-z0-9.-]+/storage/v1/object/public/[^\s\"'<>]+$",
    re.IGNORECASE,
)
_STORAGE_SECRET_QUERY_KEYS = (
    "token=",
    "api_key=",
    "apikey=",
    "secret=",
    "signature=",
    "bearer ",
)


def _is_public_storage_object_url(value: str) -> bool:
    """True for a clean, world-readable public-bucket object URL (safe to expose).

    Rejects signed / authenticated / upload storage URLs and any URL carrying a
    credential-bearing query string, so the private-storage boundary is intact.
    """
    text = value.strip()
    if not _PUBLIC_STORAGE_OBJECT_URL_RE.match(text):
        return False
    lowered = text.lower()
    if any(
        marker in lowered
        for marker in ("/object/sign", "/object/authenticated", "/object/upload")
    ):
        return False
    query = lowered.partition("?")[2]
    return not any(key in query for key in _STORAGE_SECRET_QUERY_KEYS)


def _normalize_key(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum() or ch == "_")


def _contains_unsafe_fields(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = _normalize_key(str(key))
            compact = normalized.replace("_", "")
            if normalized in _UNSAFE_KEYS or compact in _UNSAFE_KEYS:
                return True
            if _contains_unsafe_fields(nested):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_unsafe_fields(item) for item in value)
    if isinstance(value, str):
        if _is_public_storage_object_url(value):
            return False
        lowered = value.lower()
        return any(pattern in lowered for pattern in _UNSAFE_VALUE_PATTERNS)
    return False


# ── Lookups / persistence ────────────────────────────────────────────────────


def _find_project_by_token(db: Any, token: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return next(
            (
                row
                for row in db.setdefault(_PROJECTS_TABLE, {}).values()
                if row.get("public_report_token") == token
            ),
            None,
        )

    result = (
        db.table(_PROJECTS_TABLE)
        .select("*")
        .eq("public_report_token", token)
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _token_exists(db: Any, token: str) -> bool:
    if isinstance(db, dict):
        return any(
            row.get("public_report_token") == token
            for row in db.setdefault(_PROJECTS_TABLE, {}).values()
        )

    result = db.table(_PROJECTS_TABLE).select("id").eq("public_report_token", token).limit(1).execute()
    rows = getattr(result, "data", []) or []
    return bool(rows)


def _update_project(db: Any, project_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    if isinstance(db, dict):
        row = db.setdefault(_PROJECTS_TABLE, {}).get(project_id)
        if row is not None:
            row.update(updates)
        return row or {}

    result = db.table(_PROJECTS_TABLE).update(updates).eq("id", project_id).execute()
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else {}


def _generate_token(db: Any) -> str:
    for _ in range(_TOKEN_GENERATION_ATTEMPTS):
        token = secrets.token_urlsafe(24)
        if not _token_exists(db, token):
            return token
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "code": "vbr_public_report_token_generation_failed",
            "message": "Could not generate a unique public link. Please try again.",
        },
    )


def _lookup_public_passport_path(db: Any, user_id: str) -> str | None:
    """Best-effort recruiter-safe link back to the owner's *published* passport.

    Returns ``/p/{slug}`` only when the owner has an actively published Work
    Passport with a slug; any uncertainty (no passport, unpublished, missing
    slug, lookup error) returns ``None`` so a private passport is never linked.
    Kept inline (rather than importing the passport service) to avoid a circular
    import — ``vbr_work_passport_service`` already imports from this module.
    """
    if not user_id:
        return None
    try:
        if isinstance(db, dict):
            row = next(
                (
                    r
                    for r in db.setdefault(_PASSPORTS_TABLE, {}).values()
                    if str(r.get("user_id")) == str(user_id)
                ),
                None,
            )
        else:
            result = (
                db.table(_PASSPORTS_TABLE)
                .select("public_slug,is_published")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            rows = getattr(result, "data", []) or []
            row = rows[0] if rows else None
    except Exception:  # pragma: no cover - passport backlink is optional
        return None

    if not isinstance(row, dict) or not row.get("is_published"):
        return None
    slug = row.get("public_slug")
    if isinstance(slug, str) and slug.strip():
        return f"{_PASSPORT_PATH_PREFIX}{slug.strip()}"
    return None


def _table_full_name(db: Any, table: str, user_id: str, *, by_user_id: bool) -> str | None:
    """``full_name`` from one table (by ``user_id`` column or primary key)."""
    try:
        if isinstance(db, dict):
            if by_user_id:
                row = next(
                    (
                        r
                        for r in db.setdefault(table, {}).values()
                        if str(r.get("user_id")) == str(user_id)
                    ),
                    None,
                )
            else:
                row = db.setdefault(table, {}).get(user_id)
        else:
            query = db.table(table).select("full_name")
            query = query.eq("user_id", user_id) if by_user_id else query.eq("id", user_id)
            result = query.limit(1).execute()
            rows = getattr(result, "data", []) or []
            row = rows[0] if rows else None
    except Exception:  # pragma: no cover - display name is optional
        return None
    if not isinstance(row, dict):
        return None
    name = row.get("full_name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _lookup_display_name(db: Any, user_id: str) -> str | None:
    """Best-effort safe candidate display name; omitted (None) on any issue.

    The CANONICAL candidate-name resolver for every public surface (passport,
    project report, skill report), so a student's identity always matches
    across them: the consented Passport Profile first, then the legacy
    student-maintained profile, then the users row. Only ``full_name`` is ever
    read — never the student's email or auth ID.
    """
    return (
        _table_full_name(db, "passport_profiles", user_id, by_user_id=True)
        or _table_full_name(db, "student_profiles", user_id, by_user_id=True)
        or _table_full_name(db, _USERS_TABLE, user_id, by_user_id=False)
    )


# ── Response builders ────────────────────────────────────────────────────────


def _public_path(token: str) -> str:
    return f"{_PUBLIC_PATH_PREFIX}{token}"


def _status_response(project: dict[str, Any]) -> dict[str, Any]:
    token = project.get("public_report_token")
    is_public = bool(token)
    return {
        "project_id": str(project["id"]),
        "is_public": is_public,
        "public_token": token,
        "public_path": _public_path(token) if is_public else None,
        "published_at": project.get("public_report_published_at"),
    }


# ── Owner-only operations ────────────────────────────────────────────────────


def publish_project_report(db: Any, project_id: str, user_id: str) -> dict[str, Any]:
    """Publish a recruiter-safe public link for the project's VBR report.

    Idempotent: if the project already has an active public token it is
    returned unchanged (the link is stable and not rotated). Ownership is
    enforced; other users' projects 404.
    """
    project = get_owned_vbr_project_or_404(db, project_id, user_id)

    existing = project.get("public_report_token")
    if existing:
        return _status_response(project)

    token = _generate_token(db)
    now = _now()
    updated = _update_project(
        db,
        str(project["id"]),
        {"public_report_token": token, "public_report_published_at": now, "updated_at": now},
    )
    # Keep the in-memory project dict in sync for the response.
    project.update(updated or {"public_report_token": token, "public_report_published_at": now})

    logger.info("[VBR] Public report link published for project %s", project_id)
    return _status_response(project)


def unpublish_project_report(db: Any, project_id: str, user_id: str) -> dict[str, Any]:
    """Revoke the public link, clearing the token so old links stop resolving.

    Idempotent: a project with no active token is returned unchanged.
    """
    project = get_owned_vbr_project_or_404(db, project_id, user_id)

    if not project.get("public_report_token"):
        return _status_response(project)

    now = _now()
    updated = _update_project(
        db,
        str(project["id"]),
        {"public_report_token": None, "public_report_published_at": None, "updated_at": now},
    )
    project.update(updated or {})
    project["public_report_token"] = None
    project["public_report_published_at"] = None

    logger.info("[VBR] Public report link revoked for project %s", project_id)
    return _status_response(project)


def get_project_report_publish_status(db: Any, project_id: str, user_id: str) -> dict[str, Any]:
    """Return the project's publish status, including the owner's own token."""
    project = get_owned_vbr_project_or_404(db, project_id, user_id)
    return _status_response(project)


# ── Public read ──────────────────────────────────────────────────────────────


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "vbr_public_report_not_found",
            "message": "This report is not available.",
        },
    )


def resolve_published_project_id(db: Any, token: str) -> str | None:
    """Project id for an *active* public token, else None.

    Shares the exact publication/revocation semantics of the public read:
    a project resolves only while its ``public_report_token`` is set, so a
    revoked or never-published report can never be referenced (e.g. by the
    view-tracking endpoint) through a stale token.
    """
    if not is_plausible_public_token(token):
        return None
    project = _find_project_by_token(db, token)
    if project is None or not project.get("public_report_token"):
        return None
    if not owner_passport_is_public(db, project.get("user_id")):
        return None
    project_id = str(project.get("id") or "")
    return project_id or None


def _sanitize_video_chips(chips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop internal references (``question_id``) from video evidence chips."""
    sanitized: list[dict[str, Any]] = []
    for chip in chips:
        if not isinstance(chip, dict):
            continue
        sanitized.append(
            {
                "label": chip.get("label"),
                "timestamp_start_s": chip.get("timestamp_start_s"),
                "timestamp_end_s": chip.get("timestamp_end_s"),
                "short_summary": chip.get("short_summary"),
                "related_skill": chip.get("related_skill"),
                "source": chip.get("source") or "project_defense_video",
                "source_type": chip.get("source_type") or "video_transcript",
            }
        )
    return sanitized


# Numeric / score-style fragments must never reach the public recruiter report
# (product rule: no /100 bars, percentages-as-scores, "trust score" wording,
# ranking fragments, or "fully verified"). Upstream summaries (GitHub Proof,
# defense recruiter summaries, document/website text, skill notes, etc.) are
# free text and may embed any of these, so we redact them from *every* public
# string field — recursively — leaving the qualitative wording intact.
#
# Order matters: composite patterns (fraction, percent, "trust score", "score
# 91") run before the bare "score" word so numbers are stripped alongside it.
_SCORE_FRACTION_RE = re.compile(r"\b\d{1,3}\s*/\s*100\b", re.IGNORECASE)
_PERCENT_RE = re.compile(r"\b\d{1,3}(?:\.\d+)?\s*%")
_TRUST_SCORE_RE = re.compile(r"\btrust[\s_-]*scores?\b", re.IGNORECASE)
_FULLY_VERIFIED_RE = re.compile(r"\bfully[\s_-]+verified\b", re.IGNORECASE)
_SCORE_WITH_NUMBER_RE = re.compile(r"\bscor(?:e|es|ed|ing)\s*:?\s*\d{1,3}\b", re.IGNORECASE)
_NUMBER_WITH_SCORE_RE = re.compile(r"\b\d{1,3}\s*(?:/\s*\d{1,3}\s*)?scor(?:e|es|ed|ing)\b", re.IGNORECASE)
_RANK_RE = re.compile(r"\branke(?:d|ing)?\s*#?\s*\d+\b", re.IGNORECASE)
_RANK_HASH_RE = re.compile(r"#\s*\d+\b")
# Covers score / scores / scored / scoring so no "score" substring survives.
_SCORE_WORD_RE = re.compile(r"\bscor(?:e|es|ed|ing)\b", re.IGNORECASE)

# Filler words that become dangling after a fragment is stripped (e.g.
# "scored 91/100 confidence" → "confidence"). Removed only when adjacent to a
# now-empty fragment via the whitespace collapse below; kept simple on purpose.
_CONNECTOR_RE = re.compile(r"\b(?:with|at|of)\s+(?=[.,;:]|$)", re.IGNORECASE)


def _scrub_text(text: str) -> str:
    out = _SCORE_FRACTION_RE.sub(" ", text)
    out = _PERCENT_RE.sub(" ", out)
    out = _TRUST_SCORE_RE.sub(" ", out)
    out = _FULLY_VERIFIED_RE.sub("verified", out)
    out = _SCORE_WITH_NUMBER_RE.sub(" ", out)
    out = _NUMBER_WITH_SCORE_RE.sub(" ", out)
    out = _RANK_RE.sub(" ", out)
    out = _RANK_HASH_RE.sub(" ", out)
    out = _SCORE_WORD_RE.sub(" ", out)
    out = _CONNECTOR_RE.sub("", out)
    out = re.sub(r"\s+", " ", out)
    out = re.sub(r"\s+([.,;:!?])", r"\1", out)
    return out.strip()


def _scrub_numeric_scores(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    return _scrub_text(text)


def _scrub_public_report(value: Any) -> Any:
    """Recursively redact score-style fragments from every public string value.

    Walks the fully-built public projection (dicts, lists, strings) and scrubs
    each string in place. Keys are never altered, so the defence-in-depth
    unsafe-key scan still operates on the original structure.
    """
    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, dict):
        return {key: _scrub_public_report(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub_public_report(item) for item in value]
    return value


# Generic, non-leaking limitation appended when a direct verification link was
# dropped because its target was not safely public (never reveals the raw URL).
_OMITTED_LINK_LIMITATION = (
    "One or more direct verification links were private or internal and have been "
    "omitted from this public report."
)


def _public_github_proof(
    github_proof: dict[str, Any] | None, state: str = VIEWABLE
) -> dict[str, Any] | None:
    """Project the GitHub Proof per the effective disclosure ``state``.

    * ``hidden``   → the section does not exist publicly (None).
    * ``summary``  → verified summary only: repository identity and link are
      withheld ("Repository access is not enabled by the candidate").
    * ``viewable`` → current truth-gated behavior: the link renders only when
      the repository is actually public AND passes the safe-public-url gate.
    """
    if not isinstance(github_proof, dict) or state == HIDDEN:
        return None
    scrubbed = dict(github_proof)
    scrubbed["public_safe_summary"] = _scrub_numeric_scores(github_proof.get("public_safe_summary") or "")
    if state == SUMMARY:
        scrubbed["repo_url"] = None
        scrubbed["repo_owner"] = None
        scrubbed["repo_name"] = None
        scrubbed["repo_is_public"] = False
        scrubbed["disclosure"] = "summary"
        return scrubbed
    # A repo URL is only kept (and only advertised as directly linkable) when
    # the repository is genuinely public AND the URL is a public-safe http(s)
    # target — a private repo's URL is withheld entirely (fail-closed), and a
    # private/internal raw URL is never echoed.
    repo_url = github_proof.get("repo_url")
    repo_url_is_safe = is_safe_public_url(repo_url)
    repo_is_public = bool(github_proof.get("repo_is_public")) and repo_url_is_safe
    scrubbed["repo_url"] = repo_url if repo_is_public else None
    scrubbed["repo_is_public"] = repo_is_public
    scrubbed["disclosure"] = "viewable"
    return scrubbed


def _public_website_proofs(
    proofs: list[dict[str, Any]],
    db: Any,
    disclosure: EffectiveDisclosure,
    project_id: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Project website proofs per effective disclosure.

    Returns the safe proofs plus a flag indicating whether at least one target
    URL was omitted, so limitations can honestly reflect the omission.

    Aspect handling (each independently controllable):
    * ``website_summary`` hidden → no website proofs at all (handled by the
      caller; this function is only reached when the summary is visible).
    * ``website_url`` hidden → the live target link is withheld (silently —
      a student choice is not an "omitted private link" limitation).
    * ``website_frames`` viewable → attach access-gated frame view routes for
      genuinely retained screenshot artifacts.
    * ``website_video`` viewable → attach the access-gated replay route ONLY
      when a replay video was actually retained — never a dead link.

    The internal ``website_key`` (proof session id) never rides through
    unless an access descriptor was explicitly granted (the descriptor route
    paths necessarily embed it, and the routes re-gate every request).
    """
    from app.services import proof_artifact_service as artifacts

    url_state = disclosure.aspect(project_id, "website_url")
    frames_state = disclosure.aspect(project_id, "website_frames")
    video_state = disclosure.aspect(project_id, "website_video")

    safe: list[dict[str, Any]] = []
    omitted = False
    for proof in proofs:
        if not isinstance(proof, dict):
            continue
        row = dict(proof)
        website_key = str(row.pop("website_key", "") or "")
        target = row.get("target_website") or ""
        if url_state == HIDDEN:
            row["target_website"] = ""  # student chose to keep the URL private
        elif target and not is_safe_public_url(target):
            row["target_website"] = ""  # never echo a raw private/internal URL
            omitted = True

        row["frame_views"] = []
        row["replay_path"] = None
        if website_key and frames_state == VIEWABLE:
            frame_rows = artifacts.list_artifacts_for_proof(
                db, proof_type="website", proof_id=website_key, artifact_type="website_frame"
            )
            row["frame_views"] = [
                {
                    "view_path": f"/api/v1/proofs/artifacts/{frame.get('id')}/view",
                    "mime_type": frame.get("mime_type"),
                }
                for frame in frame_rows[:12]
                if frame.get("id")
            ]
        if website_key and video_state == VIEWABLE:
            replay_rows = artifacts.list_artifacts_for_proof(
                db,
                proof_type="website",
                proof_id=website_key,
                artifact_type="website_replay_video",
            )
            if replay_rows:
                row["replay_path"] = f"/api/v1/proofs/website/{website_key}/replay"
        safe.append(row)
    return safe, omitted


def _public_documents(
    documents: list[dict[str, Any]],
    disclosure: EffectiveDisclosure,
    project_id: str,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Allowlist projection of the report's documents per effective disclosure.

    Returns ``(public_documents, state_by_key)`` where ``state_by_key`` maps
    each document key to its effective state so the evidence-trace filter and
    counts stay consistent with the document list.

    * ``hidden``   → the document does not appear at all.
    * ``summary``  → title/type/status only — the pre-063 behavior. The
      owner-only ``original_document`` descriptor never reaches recruiters.
    * ``viewable`` → additionally carries a ``shared_view`` descriptor with the
      access-gated view route (and the download route ONLY when the separate
      download grant is on). Honest fallback: a document whose original was
      never retained degrades to ``summary`` rather than advertising a dead
      "View" action.
    """
    public_docs: list[dict[str, Any]] = []
    state_by_key: dict[str, str] = {}
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        key = str(doc.get("document_key") or "")
        state = disclosure.document_state(project_id, key) if key else SUMMARY
        if key:
            state_by_key[key] = state
        if state == HIDDEN:
            continue
        row: dict[str, Any] = {
            "title": doc.get("title"),
            "source_type": doc.get("source_type"),
            "status": doc.get("status"),
            "disclosure": SUMMARY,
            "shared_view": None,
        }
        if state == VIEWABLE:
            original = doc.get("original_document") or {}
            if isinstance(original, dict) and original.get("available") and original.get("open_path"):
                can_download = disclosure.document_downloadable(project_id, key)
                row["disclosure"] = VIEWABLE
                row["shared_view"] = {
                    "open_path": original.get("open_path"),
                    "mime_type": original.get("mime_type"),
                    "page_count": original.get("page_count"),
                    "can_download": can_download,
                    "download_path": original.get("download_path") if can_download else None,
                }
            else:
                # Nothing retained to open — honest summary, never a dead link.
                state_by_key[key] = SUMMARY
        public_docs.append(row)
    return public_docs, state_by_key


_GITHUB_TRACE_SOURCE_TYPE = "GitHub Proof"
_WEBSITE_TRACE_SOURCE_TYPE = "Website Proof"
_DOCUMENT_TRACE_SOURCE_TYPE = "Document Proof"

# Non-error wording for a code reference whose exact-line link the candidate
# chose not to publish (distinct from the "omitted because private" note).
_GITHUB_LINES_WITHHELD_NOTE = (
    "The exact code reference is verified but the candidate has not enabled "
    "public repository access for it."
)


def _strip_github_code_reference(row: dict[str, Any], *, summary_only: bool) -> None:
    """Blank the repo/file/line/link fields of one GitHub trace in place."""
    row["file_path"] = None
    row["line_start"] = None
    row["line_end"] = None
    row["commit_sha"] = None
    row["public_url"] = None
    row["public_url_label"] = None
    row["is_publicly_openable"] = False
    row["location_detail"] = None
    row["private_evidence_note"] = _GITHUB_LINES_WITHHELD_NOTE
    if summary_only:
        # Summary-only GitHub: the repository identity is withheld too, so a
        # repo-named trace title must not leak it.
        row["source_title"] = _GITHUB_TRACE_SOURCE_TYPE
        row["location_label"] = "verified summary"


def _public_evidence_traces(
    traces: list[dict[str, Any]],
    *,
    github_state: str = VIEWABLE,
    github_lines_state: str = VIEWABLE,
    website_state: str = VISIBLE,
    website_url_state: str = VISIBLE,
    document_state_by_key: dict[str, str] | None = None,
    defense_state: str = VISIBLE,
    video_state: str = VISIBLE,
    visible_skill: Callable[[str], bool] | None = None,
) -> list[dict[str, Any]]:
    """Re-gate each evidence trace per the effective disclosure policy.

    Hidden sources drop their traces entirely (no count/badge leak); summary
    states blank exact locators; the safe-public-url re-check stays as defence
    in depth so an unsafe link can never be advertised as openable. Trace
    skill-name lists are filtered so a hidden skill never leaks through a
    trace label.
    """
    document_states = document_state_by_key or {}
    safe: list[dict[str, Any]] = []
    for trace in traces:
        if not isinstance(trace, dict):
            continue
        row = dict(trace)
        source_type = row.get("source_type")

        if source_type == _GITHUB_TRACE_SOURCE_TYPE:
            if github_state == HIDDEN:
                continue
            if github_state == SUMMARY:
                _strip_github_code_reference(row, summary_only=True)
            elif github_lines_state != VIEWABLE and (
                row.get("file_path") or row.get("public_url") or row.get("commit_sha")
            ):
                _strip_github_code_reference(row, summary_only=False)
        elif source_type == _WEBSITE_TRACE_SOURCE_TYPE:
            if website_state == HIDDEN:
                continue
            if website_url_state == HIDDEN:
                row["public_url"] = None
                row["public_url_label"] = None
                row["is_publicly_openable"] = False
                # The student hid the live URL — it must not leak through the
                # trace's title or human-readable locator either.
                title = str(row.get("source_title") or "")
                if "://" in title or "." in title:
                    row["source_title"] = _WEBSITE_TRACE_SOURCE_TYPE
                row["location_detail"] = None
        elif source_type == _DOCUMENT_TRACE_SOURCE_TYPE:
            document_key = str(row.get("document_key") or "")
            if document_key and document_states.get(document_key, SUMMARY) == HIDDEN:
                continue
        elif source_type == _DEFENSE_TRACE_SOURCE_TYPE:
            if defense_state == HIDDEN:
                continue
        elif source_type == _VIDEO_TRACE_SOURCE_TYPE:
            if video_state == HIDDEN:
                continue

        # A hidden skill must not leak through a trace's skill labels. A trace
        # whose every named skill is hidden degrades to project-level context.
        if visible_skill is not None:
            row["skill_names"] = [
                name for name in (row.get("skill_names") or []) if visible_skill(str(name))
            ]

        # The per-document disclosure key is internal — never serialized.
        row.pop("document_key", None)

        if not is_safe_public_url(row.get("public_url")):
            row["public_url"] = None
            row["public_url_label"] = None
            row["is_publicly_openable"] = False
            if not row.get("private_evidence_note"):
                row["private_evidence_note"] = "A direct link was omitted because it was private or internal."
        # Never echo a raw private/internal URL in the human-readable title.
        title = str(row.get("source_title") or "")
        if "://" in title and not is_safe_public_url(title):
            row["source_title"] = str(row.get("source_type") or "Evidence source")
        # Strip the safe-but-detailed proof excerpts that are only meant for the
        # private student preview. The human-readable ``location_label`` (e.g.
        # "Q3", "Live URL", "repo-level") and the deterministic ``question_text``
        # stay — they carry the recruiter-facing reference without exposing raw
        # answers, document passages, or internal paths.
        row["snippet"] = None
        row["answer_excerpt"] = None
        # GitHub code snippet is dropped on the public surface — the public
        # ``…#L`` blob link is the recruiter-facing proof of the exact lines.
        row["code_snippet"] = None
        if row.get("source_type") == "Document Proof" and row.get("location_detail"):
            row["location_detail"] = (
                "The matched passage is retained privately; only the document reference is shown."
            )
        # The owner-only retained-original access descriptor never reaches the
        # public surface — recruiters keep excerpts/locators, no download action.
        row["document_original"] = None
        safe.append(row)
    return safe


# Evidence-trace ``source_type`` values that are DERIVED FROM the Project Defense
# transcript (mirrors ``vbr_student_report._SRC_DEFENSE`` / ``_SRC_VIDEO``). Kept
# as local constants so the public builder does not import private names from the
# student-report module. Both must fail closed when the transcript is privacy-
# flagged: the "Project Defense" trace's ``safe_summary`` can fall back to the
# transcript summary and its ``answer_excerpt`` / ``question_text`` echo answer
# content; the "Video Evidence" (timestamped chip) trace's ``safe_summary`` is a
# snippet of a raw transcript segment. A non-transcript trace (GitHub / Website /
# Document) is never touched.
_DEFENSE_TRACE_SOURCE_TYPE = "Project Defense"
_VIDEO_TRACE_SOURCE_TYPE = "Video Evidence"
_TRANSCRIPT_DERIVED_TRACE_SOURCE_TYPES = frozenset(
    {_DEFENSE_TRACE_SOURCE_TYPE, _VIDEO_TRACE_SOURCE_TYPE}
)

# Non-leaking replacement for a Project Defense trace's free text when the
# defense privacy review is not clean — carries no transcript-derived content.
_DEFENSE_TRACE_HIDDEN_SUMMARY = (
    "Project Defense answer content is hidden from this public report because the "
    "transcript did not pass privacy review."
)

# Non-leaking replacement for a timestamped video-chip trace's free text — the
# timestamp/label structure is kept, but the transcript-derived snippet is not.
_VIDEO_TRACE_HIDDEN_SUMMARY = (
    "This Project Defense video moment is hidden from the public report because "
    "the transcript did not pass privacy review."
)


def _redact_unsafe_defense_traces(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Blank transcript-derived trace free-text when the defense privacy review failed.

    Fail-closed companion to :func:`public_safe_defense_analysis`: the analysis
    object is not the only public surface that carries transcript-derived text. The
    evidence-trace list also holds a Project Defense overview/question trace whose
    ``safe_summary`` can fall back to the transcript summary (and whose
    ``answer_excerpt`` / ``question_text`` echo answer content), AND timestamped
    "Video Evidence" traces whose ``safe_summary`` is a snippet of a raw transcript
    segment. When the transcript is privacy-flagged, every such trace's derived
    free text is replaced with a fixed placeholder (non-transcript traces —
    GitHub / Website / Document — pass through untouched). Timestamp/label fields
    are left intact so the report still shows *that* a moment exists, never *what*
    was said.
    """
    redacted: list[dict[str, Any]] = []
    for trace in traces:
        if not isinstance(trace, dict):
            continue
        source_type = trace.get("source_type")
        if source_type in _TRANSCRIPT_DERIVED_TRACE_SOURCE_TYPES:
            placeholder = (
                _DEFENSE_TRACE_HIDDEN_SUMMARY
                if source_type == _DEFENSE_TRACE_SOURCE_TYPE
                else _VIDEO_TRACE_HIDDEN_SUMMARY
            )
            row = dict(trace)
            row["safe_summary"] = placeholder
            row["safe_detail"] = ""
            row["answer_excerpt"] = None
            row["question_text"] = None
            row["private_evidence_note"] = placeholder
            redacted.append(row)
        else:
            redacted.append(trace)
    return redacted


def _public_limitations(limitations: list[str]) -> list[str]:
    """Keep honest empty-state / disclaimer lines, drop preview-only wording."""
    return [
        line
        for line in limitations
        if isinstance(line, str) and "private student preview" not in line.lower()
    ]


def build_public_project_report(db: Any, pipeline_db: Any, token: str) -> dict[str, Any]:
    """Resolve a published project by ``token`` and return its public report.

    Raises 404 unless a project with this exact active ``public_report_token``
    exists. The report is built from the same report-safe summaries the student
    preview uses, then projected to public fields and scanned for unsafe
    content as defence in depth.
    """
    if not is_plausible_public_token(token):
        raise _not_found()

    project = _find_project_by_token(db, token)
    if project is None or not project.get("public_report_token"):
        raise _not_found()

    # Passport visibility is the master privacy switch: a published report link
    # only resolves while the owner's Work Passport is Public. The token itself
    # is preserved across Private/Public toggles, so flipping back to Public
    # restores exactly the reports the student had selected.
    if not owner_passport_is_public(db, project.get("user_id")):
        raise _not_found()

    owner_id = str(project.get("user_id") or "")
    project_id = str(project.get("id") or "")

    # ── Granular disclosure (migration 063) ──────────────────────────────────
    # The canonical resolver decides, per node, what an anonymous recruiter may
    # see. A hidden project or hidden report 404s exactly like a bad token —
    # non-disclosure. Aspect states below drive every section, count, link,
    # and access descriptor in this projection.
    disclosure = load_effective_disclosure(db, owner_id, passport_public=True)
    if not disclosure.report_visible(project_id):
        raise _not_found()

    github_state = disclosure.aspect(project_id, "github_repo")
    github_lines_state = disclosure.aspect(project_id, "github_lines")
    website_state = disclosure.aspect(project_id, "website_summary")
    defense_state = disclosure.aspect(project_id, "defense_summary")
    defense_transcript_state = disclosure.aspect(project_id, "defense_transcript")
    defense_video_state = disclosure.aspect(project_id, "defense_video")
    video_state = disclosure.aspect(project_id, "video_summary")

    def _skill_is_visible(skill_name: str) -> bool:
        """Effective visibility of one skill claim within THIS project."""
        name = str(skill_name or "").strip()
        if not name:
            return False
        canonical = canonical_skill(name)
        return disclosure.project_skill_visible(
            project_id, skill_category(canonical), skill_slug(canonical)
        )

    report = build_student_vbr_report(db, pipeline_db, project, owner_id)

    # Central Public Safety layer. Lazily imported because that module imports this
    # module's low-level primitives (``_scrub_text`` / ``_contains_unsafe_fields``),
    # so a top-level import would be circular.
    from app.services.public_report_safety_service import (
        PublicReportUnsafeError,
        defense_privacy_is_clean,
        enforce_public_safe,
        public_safe_defense_analysis,
        public_safe_defense_answer_evidence,
        public_safe_project_defense_inspection,
    )

    # ── Project Defense privacy fail-closed (must-fix) ────────────────────────
    # A privacy-flagged Project Defense transcript must never leak transcript-
    # derived text (its ``transcript_summary`` is the raw transcript's first
    # sentence). The analysis object is projected fail-closed to a placeholder, and
    # the defense evidence traces are stripped of their derived text, whenever the
    # transcript's privacy review is not clean.
    raw_defense_analysis = report.get("project_defense_analysis")
    defense_privacy_clean = defense_privacy_is_clean(raw_defense_analysis)

    if defense_state == HIDDEN:
        # The student hid Project Defense: no analysis, no cards, no badge.
        defense_analysis = None
        defense_answer_evidence: list[dict[str, Any]] = []
        project_defense_inspection: list[dict[str, Any]] = []
    else:
        defense_analysis = public_safe_defense_analysis(raw_defense_analysis)

        # Claim-level Defense Answer Evidence rides the same fail-closed gate: the
        # projection publishes an answer summary only when the session analysis is
        # explicitly clean AND the object itself is marked shareable; everything
        # else becomes a fixed withheld card with no answer-derived text and no
        # internal question_id.
        defense_answer_evidence = public_safe_defense_answer_evidence(
            report.get("defense_answer_evidence") or [], raw_defense_analysis
        )

        # Project Defense inspection cards ride the SAME fail-closed gate: a card is
        # published with content only when the session analysis is clean AND the
        # card is public-safe; otherwise it becomes a fixed withheld placeholder
        # with no answer text, no clip locator, and no internal ids.
        project_defense_inspection = public_safe_project_defense_inspection(
            report.get("project_defense_inspection") or [], raw_defense_analysis
        )

    # Documents first: their per-key effective states also drive the document
    # evidence-trace filter below, so list and traces can never disagree.
    public_documents, document_state_by_key = _public_documents(
        report.get("documents") or [], disclosure, project_id
    )

    evidence_traces = _public_evidence_traces(
        report.get("evidence_traces") or [],
        github_state=github_state,
        github_lines_state=github_lines_state,
        website_state=website_state,
        website_url_state=disclosure.aspect(project_id, "website_url"),
        document_state_by_key=document_state_by_key,
        defense_state=defense_state,
        video_state=video_state,
        visible_skill=_skill_is_visible,
    )
    # Video evidence chips are built from the SAME Project Defense transcript
    # segments, so their ``short_summary`` / ``label`` are transcript-derived. When
    # the transcript is privacy-flagged they must fail closed too: the timestamped
    # chips are omitted entirely (and their "Video Evidence" traces are redacted
    # alongside the "Project Defense" traces below). The student's own
    # ``video_summary`` aspect hides them as a choice, not an error.
    raw_video_chips = report.get("video_evidence_chips") or []
    if video_state == HIDDEN:
        raw_video_chips = []
    if not defense_privacy_clean:
        evidence_traces = _redact_unsafe_defense_traces(evidence_traces)
        raw_video_chips = []
    # A chip labeled with a hidden skill must not leak that skill's name.
    raw_video_chips = [
        chip
        for chip in raw_video_chips
        if not chip.get("related_skill") or _skill_is_visible(str(chip.get("related_skill")))
    ]

    # ── Direct verification links: public-safe gate (must-fix) ───────────────
    # Only genuinely public http(s) targets may be linked from an anonymous
    # recruiter view. Unsafe targets (localhost, private/internal hosts, private
    # IPs, file/data/blob/javascript, storage/signed URLs) are dropped here so
    # the raw URL never reaches the response JSON.
    raw_deployed_url = report.get("deployed_url") or None
    deployed_url = raw_deployed_url if is_safe_public_url(raw_deployed_url) else None
    if disclosure.aspect(project_id, "website_url") == HIDDEN:
        # The live-site link is a website aspect the student controls.
        deployed_url = None
        raw_deployed_url = None
    if website_state == HIDDEN:
        website_proofs: list[dict[str, Any]] = []
        website_link_omitted = False
    else:
        website_proofs, website_link_omitted = _public_website_proofs(
            report.get("website_proofs") or [], db, disclosure, project_id
        )
    deployed_link_omitted = bool(raw_deployed_url) and deployed_url is None

    limitations = _public_limitations(report.get("limitations") or [])
    if (deployed_link_omitted or website_link_omitted) and _OMITTED_LINK_LIMITATION not in limitations:
        limitations.append(_OMITTED_LINK_LIMITATION)

    # GitHub truth model: the repository identity is only surfaced publicly when
    # an actual GitHub Proof backs it. A project registered against a private /
    # unverified repo (no attached GitHub Proof) must never present that repo
    # name to recruiters as if a repository were available — that is exactly the
    # "report says GitHub but nothing opens" trust failure.
    github_proof_public = _public_github_proof(report.get("github_proof"), github_state)

    # Hidden skills never leak through claim lists, matrix rows, or detected-
    # skill labels — anywhere a skill name would appear.
    claimed_skills = [s for s in (report.get("claimed_skills") or []) if _skill_is_visible(str(s))]
    # A hidden proof source must not leak through a skill row's source badges.
    hidden_source_labels: set[str] = set()
    if github_state == HIDDEN:
        hidden_source_labels.add(_GITHUB_TRACE_SOURCE_TYPE)
    if website_state == HIDDEN:
        hidden_source_labels.add(_WEBSITE_TRACE_SOURCE_TYPE)
    if defense_state == HIDDEN:
        hidden_source_labels.add(_DEFENSE_TRACE_SOURCE_TYPE)
    if video_state == HIDDEN:
        hidden_source_labels.add(_VIDEO_TRACE_SOURCE_TYPE)
    if not public_documents:
        hidden_source_labels.add(_DOCUMENT_TRACE_SOURCE_TYPE)
    skill_evidence = [
        {
            **row,
            "supporting_sources": [
                s
                for s in (row.get("supporting_sources") or [])
                if str(s) not in hidden_source_labels
            ],
        }
        for row in (report.get("skill_evidence") or [])
        if isinstance(row, dict) and _skill_is_visible(str(row.get("skill") or ""))
    ]
    if isinstance(github_proof_public, dict):
        github_proof_public["detected_skills"] = [
            s for s in (github_proof_public.get("detected_skills") or []) if _skill_is_visible(str(s))
        ]
    website_proofs = [
        {
            **row,
            "supported_skills": [
                s for s in (row.get("supported_skills") or []) if _skill_is_visible(str(s))
            ],
        }
        for row in website_proofs
    ]
    if isinstance(defense_analysis, dict):
        for skills_field in (
            "skills_mentioned",
            "skills_explained_well",
            "skills_missing_from_explanation",
        ):
            defense_analysis[skills_field] = [
                s for s in (defense_analysis.get(skills_field) or []) if _skill_is_visible(str(s))
            ]

    # Effective-visibility-true evidence package: counts and badges reflect
    # ONLY what this projection actually renders — hidden data never inflates
    # a public count.
    evidence_package = dict(report.get("evidence_package") or {})
    evidence_package["github_proof_attached"] = github_proof_public is not None
    evidence_package["documents_count"] = len(public_documents)
    if website_state == HIDDEN:
        evidence_package["website_proofs_count"] = 0
        evidence_package["website_proofs_excluded_count"] = 0
    if defense_state == HIDDEN:
        evidence_package["project_defense_completed"] = False
        evidence_package["video_defense_recorded"] = False

    # ── Defense media access descriptors (explicit grants only) ──────────────
    # A transcript/recording descriptor is attached ONLY when the student's
    # custom policy opened that aspect AND a retained artifact actually exists
    # AND the defense privacy review is clean — never a dead or unsafe link.
    from app.services import proof_artifact_service as artifacts_service

    defense_transcript_view: dict[str, Any] | None = None
    defense_video_view: dict[str, Any] | None = None
    if defense_state != HIDDEN and defense_privacy_clean:
        if defense_transcript_state == VIEWABLE:
            transcript_rows = artifacts_service.list_artifacts_for_project(
                db, project_id=project_id, artifact_type="defense_transcript"
            )
            if transcript_rows:
                defense_transcript_view = {
                    "view_path": f"/api/v1/proofs/artifacts/{transcript_rows[-1].get('id')}/view",
                    "mime_type": transcript_rows[-1].get("mime_type"),
                }
        if defense_video_state == VIEWABLE:
            video_rows = artifacts_service.list_artifacts_for_project(
                db, project_id=project_id, artifact_type="defense_video"
            ) or artifacts_service.list_artifacts_for_project(
                db, project_id=project_id, artifact_type="defense_audio"
            )
            if video_rows:
                defense_video_view = {
                    "view_path": f"/api/v1/proofs/artifacts/{video_rows[-1].get('id')}/view",
                    "mime_type": video_rows[-1].get("mime_type"),
                }

    video_chips = _sanitize_video_chips(raw_video_chips)
    evidence_package["video_evidence_chip_count"] = len(video_chips)

    public = {
        "report_title": _REPORT_TITLE,
        "project_title": report.get("project_title") or "",
        "candidate_display_name": _lookup_display_name(db, owner_id),
        "project_summary": report.get("project_description") or "",
        "student_role": report.get("student_role") or "",
        "repo_full_name": (
            report.get("repo_full_name")
            if github_proof_public and github_state == VIEWABLE
            else None
        ),
        "deployed_url": deployed_url,
        "claimed_skills": claimed_skills,
        "evidence_package": evidence_package,
        "github_proof": github_proof_public,
        "documents": public_documents,
        "website_proofs": website_proofs,
        "project_defense_analysis": defense_analysis,
        "defense_answer_evidence": defense_answer_evidence,
        "project_defense_inspection": project_defense_inspection,
        "defense_transcript_view": defense_transcript_view,
        "defense_video_view": defense_video_view,
        "skill_evidence": skill_evidence,
        "evidence_traces": evidence_traces,
        "video_evidence_chips": video_chips,
        "limitations": limitations,
        "published_at": project.get("public_report_published_at"),
        "generated_at": report.get("generated_at"),
        "public_passport_path": _lookup_public_passport_path(db, owner_id),
        "verification_note": _VERIFICATION_NOTE,
        # Monotonic policy version — public caches key off it so a disclosure
        # change invalidates previously served representations immediately.
        "disclosure_version": disclosure.disclosure_version,
    }

    # Recursively scrub score-style fragments from every public string field
    # (must-fix: the scrubber is no longer limited to github_proof). Applied
    # after the projection is built and before the response is returned.
    public = _scrub_public_report(public)

    # Step 7: route the final gate through the centralized Public Safety layer —
    # a strict superset of the inline scan that also strengthens scrubbing
    # (rank/rating/percentile + emails) and rejects private source_id / metadata /
    # raw-payload / provider-config keys, ``/Users/…`` & ``file://`` paths, and raw
    # emails. (``enforce_public_safe`` / ``PublicReportUnsafeError`` were imported
    # with the defense fail-closed helpers above.)
    try:
        public = enforce_public_safe(public)
    except PublicReportUnsafeError:
        logger.warning("[VBR] Public project report failed the unsafe-field scan; refusing to serve.")
        raise _not_found()

    return public
