"""Passport Card profile photo storage (owner-only).

Uploads a student's chosen profile photo to the PUBLIC ``passport-avatars``
Supabase Storage bucket (migration 054) and persists its public URL on the
student's onboarding-profile row so the Verified Work Passport / Passport Card
can render it. Only ever produces a plain, non-signed public URL — the photo is
deliberately public (it appears on the recruiter-safe public card).

Safety:
  * Content type is restricted to JPEG / PNG / WebP; size is capped.
  * Objects live under a per-user ``<user_id>/…`` prefix, matching the bucket's
    RLS (a student can only write/replace/delete their own avatar).
  * The stored value is always a public URL — never a signed URL, storage path,
    or raw key. The passport service additionally sanitizes it before emitting.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_ONBOARDING_TABLE = "student_onboarding_profiles"

# Allowed image content types → canonical file extension.
ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

# Max upload size (bytes). Mirrors the client-side limit so a friendly error is
# shown before upload, with the server as the authoritative guard.
MAX_AVATAR_BYTES = 5 * 1024 * 1024  # 5 MB


class AvatarValidationError(ValueError):
    """The uploaded file failed a type / size check (maps to HTTP 400)."""


class AvatarStorageUnavailable(RuntimeError):
    """Profile-photo storage is not configured (bucket unset / memory db)."""


class AvatarStorageError(RuntimeError):
    """The storage upload/remove itself failed (maps to HTTP 502)."""


def validate_avatar(content: bytes, content_type: str | None) -> str:
    """Validate an uploaded image and return its canonical extension.

    Raises :class:`AvatarValidationError` with a friendly, user-facing message
    when the type or size is not acceptable.
    """
    normalized = (content_type or "").split(";")[0].strip().lower()
    ext = ALLOWED_CONTENT_TYPES.get(normalized)
    if not ext:
        raise AvatarValidationError(
            "Please upload a JPG, PNG, or WebP image under 5MB."
        )
    if not content:
        raise AvatarValidationError("The selected image appears to be empty.")
    if len(content) > MAX_AVATAR_BYTES:
        raise AvatarValidationError(
            "Please upload a JPG, PNG, or WebP image under 5MB."
        )
    return ext


def _persist_avatar_url(db: Any, user_id: str, avatar_url: str | None) -> None:
    """Store (or clear) the avatar URL on the student's onboarding profile."""
    if isinstance(db, dict):
        table = db.setdefault(_ONBOARDING_TABLE, {})
        row = next(
            (r for r in table.values() if str(r.get("user_id")) == str(user_id)),
            None,
        )
        if row is None:
            row = {"user_id": str(user_id)}
            table[str(user_id)] = row
        row["avatar_url"] = avatar_url
        return
    db.table(_ONBOARDING_TABLE).upsert(
        {"user_id": str(user_id), "avatar_url": avatar_url},
        on_conflict="user_id",
    ).execute()


def _object_paths(user_id: str) -> list[str]:
    """Every possible avatar object path for a user (one per allowed ext)."""
    return [f"{user_id}/avatar.{ext}" for ext in ALLOWED_CONTENT_TYPES.values()]


def set_avatar(
    db: Any,
    user_id: str,
    *,
    content: bytes,
    content_type: str | None,
    bucket: str,
) -> str:
    """Validate, upload, and persist a new profile photo. Returns its public URL.

    The object is written to ``<user_id>/avatar.<ext>`` (upsert), any stale
    avatar under a *different* extension is best-effort removed, and the public
    URL (with a cache-busting version) is saved on the onboarding profile.
    """
    ext = validate_avatar(content, content_type)

    if not bucket or isinstance(db, dict):
        # No real storage backend — surface a clear, non-fatal signal so the
        # caller can degrade gracefully (the client keeps a local preview).
        raise AvatarStorageUnavailable("Profile-photo storage is not configured.")

    path = f"{user_id}/avatar.{ext}"
    normalized_type = (content_type or "").split(";")[0].strip().lower()

    # Remove stale avatars under other extensions so only one photo persists.
    stale = [p for p in _object_paths(user_id) if p != path]
    try:
        db.storage.from_(bucket).remove(stale)
    except Exception:  # pragma: no cover - best-effort cleanup
        pass

    try:
        db.storage.from_(bucket).upload(
            path,
            content,
            file_options={"content-type": normalized_type, "upsert": "true"},
        )
    except Exception as exc:
        logger.error(
            "passport-avatar: upload failed (bucket=%s path=%s): %s",
            bucket, path, exc,
        )
        raise AvatarStorageError("Could not store the profile photo.") from exc

    try:
        raw = db.storage.from_(bucket).get_public_url(path)
        public_url = raw if isinstance(raw, str) and raw else None
    except Exception as exc:  # pragma: no cover - URL retrieval is non-fatal
        logger.warning("passport-avatar: public URL lookup failed for %s: %s", path, exc)
        public_url = None

    if not public_url:
        raise AvatarStorageError("Could not resolve the profile photo URL.")

    # Cache-bust so an updated photo (same path) is not served stale. `v` is a
    # plain version param — never a signature/token, so it stays public-safe.
    sep = "&" if "?" in public_url else "?"
    versioned = f"{public_url.rstrip('?&')}{sep}v={int(time.time())}"

    _persist_avatar_url(db, user_id, versioned)
    return versioned


def clear_avatar(db: Any, user_id: str, *, bucket: str) -> None:
    """Remove the student's profile photo (object + persisted URL). Idempotent."""
    if bucket and not isinstance(db, dict):
        try:
            db.storage.from_(bucket).remove(_object_paths(user_id))
        except Exception:  # pragma: no cover - best-effort removal
            pass
    _persist_avatar_url(db, user_id, None)
