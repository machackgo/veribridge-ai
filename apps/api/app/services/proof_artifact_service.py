"""Proof Artifact Retention Service.

The single write/read path for RETAINED original proof artifacts
(migration 056: ``proof_artifacts``) — document originals, video proof
originals/frames/transcripts, website replay videos, defense media.

Privacy guarantees
------------------
  • ``storage_path`` / ``storage_bucket`` are server-side only. The safe DTO
    (:func:`safe_artifact_dto`) never carries them, and no endpoint response
    ever includes them.
  • All byte access flows through :func:`fetch_artifact_bytes` (server-side
    download → streamed response) or :func:`create_short_lived_signed_url`
    (short-lived, capped at 5 minutes).
  • Access control is a closed policy set enforced in ONE place
    (:func:`can_access_artifact`):
        owner_only     — only the owning student
        recruiter_safe — owner + any AUTHENTICATED non-owner
        public_safe    — anyone (including anonymous)
        expired        — owner only (no longer served outward)
    ``retained = false`` rows are honest tombstones → treated as absent.
  • Nothing is ever faked: when storage is not configured, registration of
    byte-backed artifacts is refused instead of writing dangling metadata.

Dict-mode (hermetic tests / dev fallback): when ``db`` is a plain dict the
table lives under ``db["proof_artifacts"]`` and object bytes under
``db["_proof_artifact_objects"]`` keyed by storage path — mirroring the
``_vbr_media_objects`` precedent in ``vbr_session_recording``.
"""

from __future__ import annotations

import logging
import os
import re

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.config import settings

logger = logging.getLogger(__name__)

_TABLE = "proof_artifacts"
_OBJECTS_TABLE = "_proof_artifact_objects"

# Closed vocabularies — must stay in sync with migration 056 CHECK constraints.
PROOF_TYPES: frozenset[str] = frozenset({"website", "document", "project_defense", "video"})
ARTIFACT_TYPES: frozenset[str] = frozenset(
    {
        "website_replay_video",
        "website_frame",
        "document_original",
        "document_redacted",
        "defense_transcript",
        "defense_video",
        "defense_audio",
        "video_proof_original",
        "video_proof_frame",
        "video_proof_transcript",
    }
)
ACCESS_POLICIES: frozenset[str] = frozenset({"owner_only", "public_safe", "recruiter_safe", "expired"})

# Signed URLs are short-lived by contract. Default 120 s, hard cap 300 s.
SIGNED_URL_DEFAULT_TTL_S = 120
SIGNED_URL_MAX_TTL_S = 300

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def storage_available(db: Any) -> bool:
    """True when retained bytes can actually be stored/served."""
    if isinstance(db, dict):
        return True
    return bool(settings.supabase_proof_artifact_bucket)


def _bucket() -> str:
    return settings.supabase_proof_artifact_bucket


def safe_filename(name: str | None) -> str:
    """Collapse an arbitrary client filename into a safe storage basename."""
    base = (name or "artifact").strip().rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    cleaned = _SAFE_FILENAME_RE.sub("_", base).strip("._") or "artifact"
    return cleaned[:120]


def build_storage_path(owner_user_id: str, proof_type: str, artifact_id: str, file_name: str | None) -> str:
    """Server-computed private path: proof-artifacts/{user}/{proof_type}/{artifact_id}/{name}."""
    return f"proof-artifacts/{owner_user_id}/{proof_type}/{artifact_id}/{safe_filename(file_name)}"


# ── Storage primitives (Supabase Storage or dict-mode memory) ─────────────────


def _storage_upload(db: Any, storage_path: str, data: bytes, content_type: str) -> bool:
    if isinstance(db, dict):
        db.setdefault(_OBJECTS_TABLE, {})[storage_path] = bytes(data)
        return True
    try:
        db.storage.from_(_bucket()).upload(
            storage_path,
            data,
            file_options={"content-type": content_type},
        )
        return True
    except Exception as exc:
        logger.warning("[ProofArtifact] Upload failed for artifact object: %s", exc)
        return False


def _storage_download(db: Any, storage_path: str) -> bytes | None:
    if isinstance(db, dict):
        data = db.get(_OBJECTS_TABLE, {}).get(storage_path)
        return bytes(data) if data is not None else None
    try:
        return db.storage.from_(_bucket()).download(storage_path)
    except Exception as exc:
        logger.warning("[ProofArtifact] Download failed for artifact object: %s", exc)
        return None


def _storage_signed_url(db: Any, storage_path: str, expires_in: int, artifact_id: str) -> str | None:
    if isinstance(db, dict):
        # Hermetic placeholder: carries the artifact id + a random token — never
        # the storage path (tests assert path never leaks).
        return f"memory-signed://proof-artifact/{artifact_id}/{uuid4().hex}?expires_in={expires_in}"
    try:
        signed = db.storage.from_(_bucket()).create_signed_url(storage_path, expires_in)
        if isinstance(signed, dict):
            url = signed.get("signedURL") or signed.get("signedUrl") or signed.get("signed_url")
            return str(url) if url else None
        return str(signed) if signed else None
    except Exception as exc:
        logger.warning("[ProofArtifact] Signed URL mint failed: %s", exc)
        return None


# ── Row access ─────────────────────────────────────────────────────────────────


def get_artifact(db: Any, artifact_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return db.get(_TABLE, {}).get(artifact_id)
    try:
        resp = db.table(_TABLE).select("*").eq("id", artifact_id).maybe_single().execute()
        return getattr(resp, "data", None) if resp is not None else None
    except Exception as exc:
        logger.warning("[ProofArtifact] Artifact lookup failed: %s", exc)
        return None


def list_artifacts_for_proof(
    db: Any,
    *,
    proof_type: str,
    proof_id: str,
    artifact_type: str | None = None,
    retained_only: bool = True,
) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        rows = [
            r
            for r in db.get(_TABLE, {}).values()
            if r.get("proof_type") == proof_type and r.get("proof_id") == proof_id
        ]
    else:
        try:
            query = db.table(_TABLE).select("*").eq("proof_type", proof_type).eq("proof_id", proof_id)
            resp = query.execute()
            rows = list(getattr(resp, "data", None) or [])
        except Exception as exc:
            logger.warning("[ProofArtifact] Artifact listing failed: %s", exc)
            return []
    if artifact_type is not None:
        rows = [r for r in rows if r.get("artifact_type") == artifact_type]
    if retained_only:
        rows = [r for r in rows if r.get("retained", False)]
    rows.sort(key=lambda r: str(r.get("created_at") or ""))
    return rows


def _insert_row(db: Any, row: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(db, dict):
        db.setdefault(_TABLE, {})[row["id"]] = row
        return row
    try:
        resp = db.table(_TABLE).insert(row).execute()
        data = getattr(resp, "data", None)
        return data[0] if data else row
    except Exception as exc:
        logger.warning("[ProofArtifact] Artifact insert failed: %s", exc)
        return None


def update_artifact(db: Any, artifact_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    patch = {**patch, "updated_at": _now()}
    if isinstance(db, dict):
        row = db.get(_TABLE, {}).get(artifact_id)
        if row is None:
            return None
        row.update(patch)
        return row
    try:
        resp = db.table(_TABLE).update(patch).eq("id", artifact_id).execute()
        data = getattr(resp, "data", None)
        return data[0] if data else None
    except Exception as exc:
        logger.warning("[ProofArtifact] Artifact update failed: %s", exc)
        return None


# ── Registration ───────────────────────────────────────────────────────────────


def register_artifact_with_bytes(
    db: Any,
    *,
    owner_user_id: str,
    proof_type: str,
    artifact_type: str,
    data: bytes,
    file_name: str | None,
    mime_type: str,
    proof_id: str | None = None,
    report_id: str | None = None,
    project_id: str | None = None,
    access_policy: str = "owner_only",
    redacted: bool = False,
    duration_seconds: float | None = None,
    page_count: int | None = None,
) -> dict[str, Any] | None:
    """Store bytes + insert the registry row. Returns the row, or None on failure.

    Refuses (returns None) when storage is not configured — a byte-backed
    artifact row without bytes would be a fake retained artifact.
    """
    if proof_type not in PROOF_TYPES or artifact_type not in ARTIFACT_TYPES:
        logger.warning("[ProofArtifact] Rejected unknown type %s/%s", proof_type, artifact_type)
        return None
    if access_policy not in ACCESS_POLICIES:
        logger.warning("[ProofArtifact] Rejected unknown access policy %s", access_policy)
        return None
    if not storage_available(db):
        logger.info("[ProofArtifact] Storage not configured — refusing to register %s", artifact_type)
        return None

    artifact_id = str(uuid4())
    storage_path = build_storage_path(owner_user_id, proof_type, artifact_id, file_name)
    if not _storage_upload(db, storage_path, data, mime_type):
        return None

    row = {
        "id": artifact_id,
        "owner_user_id": owner_user_id,
        "proof_type": proof_type,
        "artifact_type": artifact_type,
        "proof_id": proof_id,
        "report_id": report_id,
        "project_id": project_id,
        "storage_bucket": None if isinstance(db, dict) else _bucket(),
        "storage_path": storage_path,
        "retained": True,
        "public_safe": access_policy == "public_safe",
        "redacted": redacted,
        "access_policy": access_policy,
        "mime_type": mime_type,
        "file_name": safe_filename(file_name),
        "size_bytes": len(data),
        "duration_seconds": duration_seconds,
        "page_count": page_count,
        "created_at": _now(),
        "updated_at": _now(),
    }
    inserted = _insert_row(db, row)
    if inserted is None:
        return None
    logger.info(
        "[ProofArtifact] Retained %s (%s, %d bytes) for user %s",
        artifact_type,
        artifact_id,
        len(data),
        owner_user_id,
    )
    return inserted


def register_artifact_with_file(
    db: Any,
    *,
    owner_user_id: str,
    proof_type: str,
    artifact_type: str,
    file_path: str,
    file_name: str | None,
    mime_type: str,
    proof_id: str | None = None,
    report_id: str | None = None,
    project_id: str | None = None,
    access_policy: str = "owner_only",
    redacted: bool = False,
    duration_seconds: float | None = None,
    page_count: int | None = None,
) -> dict[str, Any] | None:
    """Like register_artifact_with_bytes, but streams from a file on disk.

    The media is never materialised as a whole in Python memory — the storage
    client streams the open file handle. Use this for large uploads (video).
    """
    if proof_type not in PROOF_TYPES or artifact_type not in ARTIFACT_TYPES:
        logger.warning("[ProofArtifact] Rejected unknown type %s/%s", proof_type, artifact_type)
        return None
    if access_policy not in ACCESS_POLICIES:
        logger.warning("[ProofArtifact] Rejected unknown access policy %s", access_policy)
        return None
    if not storage_available(db):
        logger.info("[ProofArtifact] Storage not configured — refusing to register %s", artifact_type)
        return None

    try:
        size_bytes = os.path.getsize(file_path)
    except OSError as exc:
        logger.warning("[ProofArtifact] Cannot stat %s: %s", file_path, exc)
        return None

    artifact_id = str(uuid4())
    storage_path = build_storage_path(owner_user_id, proof_type, artifact_id, file_name)

    if isinstance(db, dict):
        with open(file_path, "rb") as fh:
            db.setdefault(_OBJECTS_TABLE, {})[storage_path] = fh.read()
    else:
        try:
            with open(file_path, "rb") as fh:
                db.storage.from_(_bucket()).upload(
                    storage_path,
                    fh,
                    file_options={"content-type": mime_type},
                )
        except Exception as exc:
            logger.warning("[ProofArtifact] Streamed upload failed for artifact object: %s", exc)
            return None

    row = {
        "id": artifact_id,
        "owner_user_id": owner_user_id,
        "proof_type": proof_type,
        "artifact_type": artifact_type,
        "proof_id": proof_id,
        "report_id": report_id,
        "project_id": project_id,
        "storage_bucket": None if isinstance(db, dict) else _bucket(),
        "storage_path": storage_path,
        "retained": True,
        "public_safe": access_policy == "public_safe",
        "redacted": redacted,
        "access_policy": access_policy,
        "mime_type": mime_type,
        "file_name": safe_filename(file_name),
        "size_bytes": size_bytes,
        "duration_seconds": duration_seconds,
        "page_count": page_count,
        "created_at": _now(),
        "updated_at": _now(),
    }
    inserted = _insert_row(db, row)
    if inserted is None:
        return None
    logger.info(
        "[ProofArtifact] Retained %s (%s, %d bytes, streamed) for user %s",
        artifact_type,
        artifact_id,
        size_bytes,
        owner_user_id,
    )
    return inserted


def update_artifact_duration(
    db: Any, artifact_id: str, duration_seconds: float | None
) -> None:
    """Best-effort duration backfill after deferred extraction. Never raises."""
    if duration_seconds is None:
        return
    try:
        if isinstance(db, dict):
            row = db.get(_TABLE, {}).get(artifact_id)
            if row is not None:
                row["duration_seconds"] = duration_seconds
            return
        db.table(_TABLE).update(
            {"duration_seconds": duration_seconds, "updated_at": _now()}
        ).eq("id", artifact_id).execute()
    except Exception as exc:
        logger.warning("[ProofArtifact] Duration backfill failed (non-fatal): %s", exc)


# ── Access control (single source of truth) ────────────────────────────────────


def can_access_artifact(
    artifact: dict[str, Any],
    caller_user_id: str | None,
    *,
    caller_is_privileged: bool = False,
) -> bool:
    """Closed-policy access decision. Non-retained rows are treated as absent.

    ``recruiter_safe`` is reserved for the owner and *privileged* viewers
    (recruiters / admins / reviewers — ``caller_is_privileged``). A plain
    authenticated non-owner (another student) is treated like an anonymous
    caller and may reach only ``public_safe`` artifacts, so one student can never
    pull another student's recruiter-safe media by guessing its id.
    """
    if not artifact.get("retained", False):
        return False
    owner = artifact.get("owner_user_id")
    if caller_user_id is not None and caller_user_id == owner:
        return True
    policy = artifact.get("access_policy", "owner_only")
    if policy == "public_safe":
        return True
    if policy == "recruiter_safe":
        return caller_user_id is not None and caller_is_privileged
    # owner_only / expired / anything unknown → deny
    return False


def get_accessible_artifact(
    db: Any,
    artifact_id: str,
    caller_user_id: str | None,
    *,
    caller_is_privileged: bool = False,
) -> dict[str, Any] | None:
    """Fetch + gate in one step. None means 'serve an indistinct 404'."""
    artifact = get_artifact(db, artifact_id)
    if artifact is None:
        return None
    if not can_access_artifact(
        artifact, caller_user_id, caller_is_privileged=caller_is_privileged
    ):
        return None
    return artifact


# ── Byte / URL serving ─────────────────────────────────────────────────────────


def fetch_artifact_bytes(db: Any, artifact: dict[str, Any]) -> bytes | None:
    """Server-side download of a (pre-gated) artifact's bytes."""
    storage_path = artifact.get("storage_path")
    if not storage_path:
        return None
    return _storage_download(db, str(storage_path))


def create_short_lived_signed_url(
    db: Any, artifact: dict[str, Any], expires_in: int = SIGNED_URL_DEFAULT_TTL_S
) -> tuple[str | None, int]:
    """Mint a short-lived signed URL for a (pre-gated) artifact.

    TTL is clamped to [1, SIGNED_URL_MAX_TTL_S]. Returns (url, ttl) —
    url is None when storage refuses.
    """
    ttl = max(1, min(int(expires_in), SIGNED_URL_MAX_TTL_S))
    storage_path = artifact.get("storage_path")
    if not storage_path:
        return None, ttl
    url = _storage_signed_url(db, str(storage_path), ttl, str(artifact.get("id")))
    return url, ttl


# ── Safe projection ────────────────────────────────────────────────────────────

_SAFE_FIELDS = (
    "id",
    "proof_type",
    "artifact_type",
    "proof_id",
    "project_id",
    "retained",
    "public_safe",
    "redacted",
    "access_policy",
    "mime_type",
    "file_name",
    "size_bytes",
    "duration_seconds",
    "page_count",
    "created_at",
)


def safe_artifact_dto(artifact: dict[str, Any]) -> dict[str, Any]:
    """The ONLY serialization of an artifact row allowed in API responses.

    Deliberately rebuilt field-by-field from an allowlist — ``storage_path``,
    ``storage_bucket`` and ``owner_user_id`` can never leak through.
    """
    return {key: artifact.get(key) for key in _SAFE_FIELDS}
