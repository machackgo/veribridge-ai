"""
Transcription Service — provider abstraction for audio-to-text.

Converts audio/video bytes to a plain-text transcript.

Providers
---------
none   (default)  — transcription not configured; raises TranscriptionUnavailableError
openai            — OpenAI Whisper API via httpx (no openai SDK required)

Env vars
--------
TRANSCRIPTION_PROVIDER      = none | openai   (default: none)
OPENAI_API_KEY              =                  (required for openai provider)
OPENAI_TRANSCRIPTION_MODEL  = whisper-1        (default: whisper-1)

Design principles
-----------------
- Project-agnostic: no hardcoded project names, fields, or domains.
- Never crashes if provider is unconfigured; raises a typed exception instead.
- No mandatory dependency on the openai Python package; httpx is used directly.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_PROVIDER = os.environ.get("TRANSCRIPTION_PROVIDER", "none").strip().lower()
_OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
_OPENAI_MODEL = os.environ.get("OPENAI_TRANSCRIPTION_MODEL", "whisper-1").strip()

_OPENAI_TRANSCRIPTION_URL = "https://api.openai.com/v1/audio/transcriptions"

# Supported file extension → MIME type mapping (matches ALLOWED_MEDIA_EXTENSIONS)
_MIME_MAP: dict[str, str] = {
    "mp4":  "video/mp4",
    "mov":  "video/quicktime",
    "webm": "audio/webm",
    "mp3":  "audio/mpeg",
    "wav":  "audio/wav",
    "m4a":  "audio/mp4",
}


# ── Exceptions ────────────────────────────────────────────────────────────────

class TranscriptionUnavailableError(Exception):
    """
    Raised when transcription cannot run because the provider is not configured
    or the API key is missing.  The caller should show a graceful fallback, not
    crash.
    """


# ── Result ─────────────────────────────────────────────────────────────────────

@dataclass
class TranscriptionResult:
    """Successful transcription output."""

    transcript_text: str
    provider_used: str


# ── Public API ────────────────────────────────────────────────────────────────

def transcribe_audio(
    file_bytes: bytes,
    filename: str,
    content_type: str | None = None,
) -> TranscriptionResult:
    """
    Transcribe audio/video bytes to text using the configured provider.

    Parameters
    ----------
    file_bytes:   Raw file content.
    filename:     Original filename — used for MIME-type inference and the
                  multipart Content-Disposition header.
    content_type: Optional MIME type override.

    Returns
    -------
    TranscriptionResult with transcript_text and provider_used.

    Raises
    ------
    TranscriptionUnavailableError
        Provider is 'none', unknown, or API key is missing.
    RuntimeError
        Provider is configured but the request failed (network, rate-limit, etc.).
    """
    provider = _PROVIDER

    if not provider or provider == "none":
        raise TranscriptionUnavailableError(
            "Automatic transcription is not configured. "
            "Set TRANSCRIPTION_PROVIDER=openai and OPENAI_API_KEY to enable it."
        )

    if provider == "openai":
        return _transcribe_openai(file_bytes, filename, content_type)

    raise TranscriptionUnavailableError(
        f"Unknown transcription provider '{provider}'. "
        "Supported values: none, openai."
    )


# ── OpenAI provider ───────────────────────────────────────────────────────────

def _transcribe_openai(
    file_bytes: bytes,
    filename: str,
    content_type: str | None = None,
) -> TranscriptionResult:
    """Call OpenAI Whisper via httpx (avoids the openai package as a hard dep)."""
    import httpx  # already in requirements.txt

    if not _OPENAI_KEY:
        raise TranscriptionUnavailableError(
            "OPENAI_API_KEY is not set. "
            "Automatic transcription is unavailable. "
            "Paste or edit your transcript manually."
        )

    mime = content_type or _guess_mime(filename)

    try:
        with httpx.Client(timeout=120.0) as http:
            resp = http.post(
                _OPENAI_TRANSCRIPTION_URL,
                headers={"Authorization": f"Bearer {_OPENAI_KEY}"},
                files={"file": (filename, file_bytes, mime)},
                data={"model": _OPENAI_MODEL},
            )
    except httpx.RequestError as exc:
        logger.error("OpenAI transcription network error: %s", exc)
        raise RuntimeError(
            "Transcription request failed due to a network error. Please try again."
        ) from exc

    if resp.status_code == 401:
        raise TranscriptionUnavailableError(
            "OpenAI API key is invalid or expired. "
            "Check OPENAI_API_KEY and try again."
        )
    if resp.status_code == 429:
        raise RuntimeError(
            "OpenAI rate limit reached. Please wait a moment and try again."
        )
    if not resp.is_success:
        logger.error(
            "OpenAI transcription error %s: %s",
            resp.status_code,
            resp.text[:400],
        )
        raise RuntimeError(
            f"Transcription failed (OpenAI returned HTTP {resp.status_code}). "
            "Please try again or paste your transcript manually."
        )

    data = resp.json()
    text = (data.get("text") or "").strip()
    if not text:
        raise RuntimeError(
            "Transcription returned an empty result. "
            "Ensure the file contains clear speech, or paste your transcript manually."
        )

    return TranscriptionResult(transcript_text=text, provider_used="openai")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _guess_mime(filename: str) -> str:
    """Infer MIME type from filename extension."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _MIME_MAP.get(ext, "application/octet-stream")
