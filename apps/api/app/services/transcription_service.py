"""
Transcription Service — provider abstraction for audio-to-text.

Converts audio/video bytes to a plain-text transcript.

Providers
---------
none          (default)   — transcription not configured; graceful fallback
openai                    — OpenAI Whisper API via httpx (no SDK required)
local_whisper             — faster-whisper running on the local machine (CPU/GPU)

Env vars
--------
TRANSCRIPTION_PROVIDER      = none | openai | local_whisper   (default: none)

# OpenAI provider
OPENAI_API_KEY              =                  (required for openai provider)
OPENAI_TRANSCRIPTION_MODEL  = whisper-1        (default: whisper-1)

# local_whisper provider (all optional — defaults are CPU-friendly)
LOCAL_WHISPER_MODEL_SIZE    = base             (tiny|base|small|medium|large-v3)
LOCAL_WHISPER_DEVICE        = cpu              (cpu|cuda)
LOCAL_WHISPER_COMPUTE_TYPE  = int8             (int8|float16|float32)

Optional system dependencies
-----------------------------
faster-whisper  — required for local_whisper; install with:
                  pip install faster-whisper
ffmpeg          — required only for video files (mp4/mov) with local_whisper;
                  audio formats (mp3/wav/webm/m4a) do not need it.
                  Install: brew install ffmpeg  /  apt install ffmpeg

Design principles
-----------------
- Project-agnostic: no hardcoded project names, fields, or domains.
- Never crashes on missing config or missing optional dep — typed exceptions only.
- All I/O optional: if faster-whisper or ffmpeg is absent, a clear message guides
  the student to paste their transcript manually instead.
- clean_transcript_for_project_defense() does mechanical normalisation only;
  it never invents or hallucinates missing content.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Config — read from pydantic-settings (which loads .env) ──────────────────
#
# IMPORTANT: do NOT use os.environ.get() for these values.
# pydantic-settings reads .env into the Settings object but does NOT inject
# those values into os.environ.  os.environ.get("TRANSCRIPTION_PROVIDER") would
# always return "" unless the variable was set in the actual shell environment.
#
# All callers (tests) that need to override these values should patch the
# module-level variable directly:
#   with patch.object(svc, "_PROVIDER", "openai"):
#       ...

_PROVIDER = settings.transcription_provider.strip().lower()

# OpenAI
_OPENAI_KEY   = settings.openai_api_key.get_secret_value().strip()
_OPENAI_MODEL = settings.openai_transcription_model.strip()

# local_whisper
_LOCAL_WHISPER_MODEL_SIZE   = settings.local_whisper_model_size.strip()
_LOCAL_WHISPER_DEVICE       = settings.local_whisper_device.strip()
_LOCAL_WHISPER_COMPUTE_TYPE = settings.local_whisper_compute_type.strip()

_OPENAI_TRANSCRIPTION_URL = "https://api.openai.com/v1/audio/transcriptions"

# File extensions whose transcription requires ffmpeg audio extraction
_VIDEO_EXTS: frozenset[str] = frozenset({"mp4", "mov"})

# MIME-type map (matches ALLOWED_MEDIA_EXTENSIONS in schemas)
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
    Raised when transcription cannot run because:
    - The provider is set to 'none'
    - An API key or optional dependency is missing
    - A required system tool (ffmpeg) is absent

    The caller should display a graceful fallback message and keep the
    transcript textarea editable — never crash.
    """


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass
class TranscriptSegment:
    """One time-aligned transcript segment from the provider."""

    start_time: float      # seconds
    end_time: float        # seconds
    text: str
    confidence: float | None = None  # word-level avg where available


@dataclass
class TranscriptionResult:
    """Successful transcription output."""

    transcript_text: str
    provider_used: str
    language: str | None = None
    transcript_segments: list[TranscriptSegment] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.transcript_segments is None:
            self.transcript_segments = []


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
    filename:     Original filename — used for MIME inference and temp-file naming.
    content_type: Optional MIME type override (used by openai provider).

    Returns
    -------
    TranscriptionResult with transcript_text and provider_used.

    Raises
    ------
    TranscriptionUnavailableError
        Provider is 'none', unknown, dependency is missing, or key absent.
    RuntimeError
        Provider is configured but the request/transcription itself failed.
    """
    provider = _PROVIDER

    if not provider or provider == "none":
        raise TranscriptionUnavailableError(
            "Automatic transcription is not configured. "
            "Set TRANSCRIPTION_PROVIDER=openai or TRANSCRIPTION_PROVIDER=local_whisper "
            "to enable it."
        )

    if provider == "openai":
        return _transcribe_openai(file_bytes, filename, content_type)

    if provider == "local_whisper":
        return _transcribe_local_whisper(file_bytes, filename)

    raise TranscriptionUnavailableError(
        f"Unknown transcription provider '{provider}'. "
        "Supported values: none, openai, local_whisper."
    )


# ── Transcript cleanup ────────────────────────────────────────────────────────

def clean_transcript_for_project_defense(
    raw: str,
    claimed_skills: list[str] | None = None,  # reserved for future smart cleanup
) -> str:
    """
    Light mechanical cleanup of a raw auto-transcript for project defense use.

    Rules (strict — never invent content):
    - Strip leading/trailing whitespace.
    - Collapse runs of spaces/tabs to a single space.
    - Collapse 3+ consecutive newlines to two (paragraph break preserved).
    - Normalize long ellipsis runs (3+ dots) to the … character.
    - Ensure a space between sentence-ending punctuation and the next capital
      letter (common ASR omission).

    claimed_skills is accepted for API stability and future use (e.g. fixing
    common ASR mis-spellings of known tool names) but is intentionally unused
    in the MVP so no technical terms are invented or modified.
    """
    if not raw:
        return ""
    text = raw.strip()
    text = re.sub(r"[ \t]+", " ", text)          # collapse horizontal whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)        # max two consecutive newlines
    text = re.sub(r"\.{3,}", "…", text)           # long ellipsis → unicode …
    text = re.sub(r"([.!?])([A-Z])", r"\1 \2", text)  # missing space after sentence
    return text


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
    text = clean_transcript_for_project_defense((data.get("text") or "").strip())
    if not text:
        raise RuntimeError(
            "Transcription returned an empty result. "
            "Ensure the file contains clear speech, or paste your transcript manually."
        )

    return TranscriptionResult(transcript_text=text, provider_used="openai")


# ── local_whisper provider ────────────────────────────────────────────────────

def _transcribe_local_whisper(
    file_bytes: bytes,
    filename: str,
) -> TranscriptionResult:
    """
    Transcribe using faster-whisper running locally on CPU or GPU.

    Requires:
      pip install faster-whisper

    For video files (mp4/mov), requires ffmpeg to extract the audio track first:
      brew install ffmpeg   /   apt install ffmpeg

    Audio files (mp3/wav/webm/m4a) are passed directly to Whisper — no ffmpeg needed.
    """
    # ── Check optional dependency ─────────────────────────────────────────────
    try:
        from faster_whisper import WhisperModel  # optional dep
    except ImportError:
        raise TranscriptionUnavailableError(
            "Local Whisper transcription is not installed. "
            "Install faster-whisper (pip install faster-whisper) "
            "or use manual transcript."
        )

    import subprocess
    import tempfile

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "wav"

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, filename)
        with open(input_path, "wb") as fh:
            fh.write(file_bytes)

        # ── Video → audio extraction via ffmpeg ───────────────────────────────
        if ext in _VIDEO_EXTS:
            audio_path = os.path.join(tmpdir, "audio_extracted.wav")
            try:
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-i", input_path,
                        "-vn",                  # no video stream
                        "-ar", "16000",         # 16 kHz sample rate (Whisper native)
                        "-ac", "1",             # mono
                        "-f", "wav",
                        audio_path,
                    ],
                    check=True,
                    capture_output=True,
                    timeout=120,
                )
            except FileNotFoundError:
                raise TranscriptionUnavailableError(
                    "Video transcription requires ffmpeg. "
                    "Upload audio (mp3/wav/webm/m4a) instead, or install ffmpeg."
                )
            except subprocess.CalledProcessError as exc:
                stderr = (exc.stderr or b"").decode(errors="replace")[:300]
                raise RuntimeError(
                    f"ffmpeg audio extraction failed: {stderr}. "
                    "Try uploading the file as mp3 or wav."
                )
            except subprocess.TimeoutExpired:
                raise RuntimeError(
                    "ffmpeg audio extraction timed out. "
                    "Try a shorter recording or upload audio directly."
                )
        else:
            audio_path = input_path

        # ── Whisper transcription ─────────────────────────────────────────────
        try:
            model = WhisperModel(
                _LOCAL_WHISPER_MODEL_SIZE,
                device=_LOCAL_WHISPER_DEVICE,
                compute_type=_LOCAL_WHISPER_COMPUTE_TYPE,
            )
            segments_iter, info = model.transcribe(audio_path, beam_size=5, word_timestamps=False)
            # Materialise the generator so we can iterate twice
            raw_segments = list(segments_iter)
            raw_text = " ".join(seg.text for seg in raw_segments).strip()
            detected_language: str | None = getattr(info, "language", None)
        except Exception as exc:
            logger.error("local_whisper transcription error: %s", exc)
            raise RuntimeError(
                f"Local Whisper transcription failed: {exc}. "
                "Try again or paste your transcript manually."
            )

    cleaned = clean_transcript_for_project_defense(raw_text)
    if not cleaned:
        raise RuntimeError(
            "Local Whisper returned an empty transcript. "
            "Ensure the recording contains clear speech, or paste your transcript manually."
        )

    timed_segments = [
        TranscriptSegment(
            start_time=round(seg.start, 3),
            end_time=round(seg.end, 3),
            text=seg.text.strip(),
        )
        for seg in raw_segments
        if seg.text.strip()
    ]

    return TranscriptionResult(
        transcript_text=cleaned,
        provider_used="local_whisper",
        language=detected_language,
        transcript_segments=timed_segments,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _guess_mime(filename: str) -> str:
    """Infer MIME type from filename extension."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _MIME_MAP.get(ext, "application/octet-stream")
