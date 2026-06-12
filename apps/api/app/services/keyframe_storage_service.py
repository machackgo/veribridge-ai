"""Keyframe Storage Service.

Uploads extracted keyframe JPEGs (and thumbnails) to Supabase Storage and
provides a visibility-gated fetch for the recruiter-safe thumbnail proxy.

Storage layout (within the configured bucket):
  frame-evidence/{user_id}/{session_id}/{frame_id}.jpg        — full JPEG
  frame-evidence/{user_id}/{session_id}/{frame_id}_thumb.jpg  — 320 px wide thumbnail

Privacy guarantees
------------------
  • Storage paths are NEVER returned in any public API response.
  • The thumbnail proxy endpoint (keyframe_thumbnail.py) fetches bytes
    internally and streams them to the caller — the raw path stays server-side.
  • Visibility is enforced via skill_evidence_artifacts with TWO conditions:
      1. source_type must be 'keyframe', 'screenshot', or 'visual_frame'
      2. visibility must be 'public' or 'approved'
      All other values → 403
  • A public/approved artifact of a different source_type (workflow, github,
    document) in the same proof session does NOT grant thumbnail access.
  • When no matching keyframe-type artifact is found, access is denied by default.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_BUCKET_PREFIX = "frame-evidence"
_THUMB_WIDTH_PX = 320
_THUMBNAIL_QUALITY = 70

# Artifact visibility values that permit recruiter thumbnail access
_VISIBLE_STATES: frozenset[str] = frozenset({"public", "approved"})

# Only these source_types are considered for keyframe thumbnail access.
# A public/approved workflow, github, or document artifact in the same proof
# session must NOT grant access — prevents cross-artifact visibility leakage.
_KEYFRAME_SOURCE_TYPES: frozenset[str] = frozenset({"keyframe", "screenshot", "visual_frame"})


class KeyframeStorageService:
    """Upload keyframe JPEGs to Supabase Storage and serve them safely."""

    def upload_keyframe(
        self,
        db: Any,
        user_id: str,
        session_id: str,
        frame_id: str,
        jpeg_bytes: bytes,
        bucket: str,
    ) -> dict[str, str | None]:
        """Upload JPEG + thumbnail to storage. Returns paths (or None if upload fails).

        Returns:
            {"storage_path": str | None, "thumbnail_path": str | None}
        """
        result: dict[str, str | None] = {"storage_path": None, "thumbnail_path": None}

        storage_path = f"{_BUCKET_PREFIX}/{user_id}/{session_id}/{frame_id}.jpg"
        try:
            db.storage.from_(bucket).upload(
                storage_path,
                jpeg_bytes,
                file_options={"content-type": "image/jpeg"},
            )
            result["storage_path"] = storage_path
            logger.info(
                "[KeyframeStorage] Uploaded frame %s → %s", frame_id, storage_path
            )
        except Exception as exc:
            logger.warning(
                "[KeyframeStorage] Failed to upload frame %s: %s", frame_id, exc
            )
            return result

        # Generate and upload thumbnail
        thumb_bytes = self.generate_thumbnail(jpeg_bytes)
        if thumb_bytes:
            thumb_path = f"{_BUCKET_PREFIX}/{user_id}/{session_id}/{frame_id}_thumb.jpg"
            try:
                db.storage.from_(bucket).upload(
                    thumb_path,
                    thumb_bytes,
                    file_options={"content-type": "image/jpeg"},
                )
                result["thumbnail_path"] = thumb_path
                logger.info(
                    "[KeyframeStorage] Uploaded thumbnail %s → %s",
                    frame_id, thumb_path,
                )
            except Exception as exc:
                logger.warning(
                    "[KeyframeStorage] Failed to upload thumbnail for %s: %s",
                    frame_id, exc,
                )

        return result

    def generate_thumbnail(self, jpeg_bytes: bytes) -> bytes | None:
        """Resize JPEG to _THUMB_WIDTH_PX wide, maintaining aspect ratio.

        Returns None if PIL is unavailable or the image cannot be decoded.
        """
        try:
            import io
            from PIL import Image  # type: ignore[import]

            img = Image.open(io.BytesIO(jpeg_bytes))
            orig_w, orig_h = img.size
            if orig_w <= 0:
                return None
            new_h = max(1, int(orig_h * _THUMB_WIDTH_PX / orig_w))
            img = img.resize((_THUMB_WIDTH_PX, new_h), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=_THUMBNAIL_QUALITY)
            return buf.getvalue()
        except Exception as exc:
            logger.debug("[KeyframeStorage] Thumbnail generation failed: %s", exc)
            return None

    def get_thumbnail_bytes_if_visible(
        self,
        db: Any,
        frame_id: str,
        bucket: str,
        caller_user_id: str | None = None,
    ) -> bytes | None:
        """Fetch thumbnail bytes if access is allowed.

        Access rules:
          1. If caller_user_id matches the frame owner → always allowed.
          2. Otherwise, a keyframe/screenshot/visual_frame artifact linked to
             this frame's proof_session_id must have visibility 'public' or
             'approved'. A public/approved artifact of any other source_type
             (workflow, github, document) does NOT grant access.
          3. If no matching keyframe-type artifact exists, deny by default.

        Returns None (→ 403) when access is denied or no thumbnail is stored.
        """
        # Fetch the frame row
        try:
            frame_resp = (
                db.table("workflow_visual_frame_evidence")
                .select("user_id, proof_session_id, frame_thumbnail_storage_path")
                .eq("id", frame_id)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            logger.warning("[KeyframeStorage] Frame lookup failed: %s", exc)
            return None

        if not frame_resp or not frame_resp.data:
            return None

        row = frame_resp.data
        frame_user_id: str = row.get("user_id", "")
        proof_session_id: str = row.get("proof_session_id", "")
        thumb_path: str | None = row.get("frame_thumbnail_storage_path")

        if not thumb_path:
            return None

        # Owner bypass
        if caller_user_id and caller_user_id == frame_user_id:
            return self._download(db, bucket, thumb_path)

        # Artifact visibility check for non-owners (recruiter access)
        if not self._artifact_is_visible(db, proof_session_id):
            logger.info(
                "[KeyframeStorage] Thumbnail denied: no public/approved artifact "
                "for session %s", proof_session_id,
            )
            return None

        return self._download(db, bucket, thumb_path)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _artifact_is_visible(self, db: Any, proof_session_id: str) -> bool:
        """Return True only if a keyframe/screenshot/visual_frame artifact for this session is public or approved.

        Restricts the check to _KEYFRAME_SOURCE_TYPES so that unrelated public
        artifacts (workflow, github, document) in the same proof session cannot
        grant thumbnail access. Denies by default when no matching artifact exists.
        """
        if not proof_session_id:
            return False
        try:
            resp = (
                db.table("skill_evidence_artifacts")
                .select("visibility")
                .filter("artifact_data->>proof_session_id", "eq", proof_session_id)
                .in_("source_type", list(_KEYFRAME_SOURCE_TYPES))
                .in_("visibility", list(_VISIBLE_STATES))
                .limit(1)
                .execute()
            )
            return bool(resp and resp.data)
        except Exception as exc:
            logger.warning(
                "[KeyframeStorage] Artifact visibility check failed for session %s: %s",
                proof_session_id, exc,
            )
            return False

    def _download(self, db: Any, bucket: str, path: str) -> bytes | None:
        try:
            data = db.storage.from_(bucket).download(path)
            if isinstance(data, (bytes, bytearray)):
                return bytes(data)
            return None
        except Exception as exc:
            logger.warning(
                "[KeyframeStorage] Storage download failed path=%s: %s", path, exc
            )
            return None
