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

# local_whisper provider (all optional — defaults tuned for English quality)
LOCAL_WHISPER_MODEL_SIZE    = large-v3-turbo   (tiny|base|small|medium|large-v3|large-v3-turbo)
LOCAL_WHISPER_DEVICE        = cpu              (cpu|cuda|auto — no Metal/MPS backend)
LOCAL_WHISPER_COMPUTE_TYPE  = int8             (int8|float16|float32)
LOCAL_WHISPER_LANGUAGE      = en               ("" → auto-detect)
# Anti-hallucination decoding tuning (defaults suppress "new new new …" loops):
LOCAL_WHISPER_BEAM_SIZE                   = 5
LOCAL_WHISPER_VAD                         = true    (strip silence before decode)
LOCAL_WHISPER_CONDITION_ON_PREVIOUS_TEXT  = false   (stop repeated-token feedback)
LOCAL_WHISPER_TEMPERATURE                 = 0.0     (greedy, deterministic)
LOCAL_WHISPER_NO_SPEECH_THRESHOLD         = 0.6
LOCAL_WHISPER_COMPRESSION_RATIO_THRESHOLD = 2.4
LOCAL_WHISPER_LOG_PROB_THRESHOLD          = -1.0

Optional system dependencies
-----------------------------
faster-whisper  — required for local_whisper; install with:
                  pip install faster-whisper
ffmpeg          — required for video files (mp4/mov/video-webm) with
                  local_whisper; the audio track is extracted and normalised to
                  16 kHz mono WAV before Whisper runs.  Audio-only formats
                  (mp3/wav/audio-webm/m4a) are passed straight through.
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
# Forced transcription language ("" → auto-detect). Defaults to English for the
# Project Defense MVP so short/quiet clips do not misfire to obscure
# low-confidence languages (e.g. 'nn'), which destabilises transcription.
_LOCAL_WHISPER_LANGUAGE     = settings.local_whisper_language.strip().lower()
# Decoding / anti-hallucination tuning (see config.py for rationale).
_LOCAL_WHISPER_BEAM_SIZE                    = settings.local_whisper_beam_size
_LOCAL_WHISPER_VAD                          = settings.local_whisper_vad
_LOCAL_WHISPER_CONDITION_ON_PREVIOUS_TEXT   = settings.local_whisper_condition_on_previous_text
_LOCAL_WHISPER_TEMPERATURE                  = settings.local_whisper_temperature
_LOCAL_WHISPER_NO_SPEECH_THRESHOLD          = settings.local_whisper_no_speech_threshold
_LOCAL_WHISPER_COMPRESSION_RATIO_THRESHOLD  = settings.local_whisper_compression_ratio_threshold
_LOCAL_WHISPER_LOG_PROB_THRESHOLD           = settings.local_whisper_log_prob_threshold

_OPENAI_TRANSCRIPTION_URL = "https://api.openai.com/v1/audio/transcriptions"

# File extensions that are UNAMBIGUOUSLY video containers. Used only when the
# caller gives no content_type; a bare ".webm" is intentionally NOT here because
# it is ambiguous (browser screen+mic recordings are video/webm while
# microphone-only recordings are audio/webm) — see _is_video_input().
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
        return _transcribe_local_whisper(file_bytes, filename, content_type)

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


# ── Meaningful-speech detection ────────────────────────────────────────────────
#
# Whisper (local or API) run over a silent / near-silent recording does not
# return an empty string — it emits punctuation-only segments, typically a run of
# "." tokens ("00:00 .", "00:07 .", …). Those are NOT a successful transcript and
# must never be persisted or shown as "Transcript saved". These helpers let a
# caller distinguish real speech from that no-speech output before deciding
# success.

# Minimum number of meaningful (alphanumeric-bearing) words a transcript must
# contain to be treated as real speech. Below this we treat the output as
# no-speech / punctuation-only and fail safely.
MEANINGFUL_WORD_THRESHOLD = 3

# Runs of letters/digits (Unicode-aware, underscore excluded). Punctuation-only
# or whitespace-only tokens (".", "...", "?!", "-") produce zero matches, so a
# dot-only transcript counts as zero meaningful words.
_MEANINGFUL_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


def count_meaningful_words(text: str) -> int:
    """Count words that contain at least one letter or digit.

    Punctuation-only / whitespace-only output yields 0 (e.g. Whisper's "."
    no-speech segments). Used to tell a real transcript apart from a no-speech
    result before it is persisted as a success.
    """
    if not text:
        return 0
    return len(_MEANINGFUL_WORD_RE.findall(text))


def is_meaningful_transcript(text: str, threshold: int = MEANINGFUL_WORD_THRESHOLD) -> bool:
    """True when ``text`` contains at least ``threshold`` meaningful words."""
    return count_meaningful_words(text) >= threshold


# ── Repeated-token hallucination detection ────────────────────────────────────
#
# A weak/mis-configured Whisper run over degraded audio does not error — it
# emits a real-looking transcript that is actually a single word repeated dozens
# of times ("… new new new new new …"). That is a hallucination, not speech, and
# must never be persisted as good evidence. These helpers quantify how repetitive
# a transcript is so a caller can reject it and offer re-record / manual fallback.
# (The decoding config in ``_transcribe_local_whisper`` — VAD, temperature=0,
# condition_on_previous_text=False, thresholds — is the *primary* defence; this
# guard is the safety net for whatever still slips through, including from other
# providers.)

# A transcript with fewer meaningful words than this is owned by the separate
# no-speech gate, not this one. At (and above) the meaningful-speech floor —
# including a short 3–5 word answer — a run of one repeated token ("new new
# new") is a hallucination and must fail closed, so this guard measures every
# transcript that clears no-speech rather than waiting for a longer sample.
MIN_WORDS_FOR_REPEAT_CHECK = MEANINGFUL_WORD_THRESHOLD

# If a single token accounts for at least this fraction of all tokens, OR at
# least this fraction of tokens are immediate repeats of the previous token, the
# transcript is treated as repeated-token hallucination.
REPEATED_TOKEN_RATIO_THRESHOLD = 0.5

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def dominant_token_ratio(text: str) -> float:
    """Fraction of tokens made up by the single most frequent token (0.0–1.0).

    ``"new new new the"`` → 0.75. Empty / no-token input → 0.0.
    """
    toks = _tokens(text)
    if not toks:
        return 0.0
    counts: dict[str, int] = {}
    for tok in toks:
        counts[tok] = counts.get(tok, 0) + 1
    return max(counts.values()) / len(toks)


def consecutive_repeat_ratio(text: str) -> float:
    """Fraction of tokens that immediately repeat the previous token (0.0–1.0).

    ``"new new new the"`` → 2/3 (two of the three transitions repeat). Fewer than
    two tokens → 0.0.
    """
    toks = _tokens(text)
    if len(toks) < 2:
        return 0.0
    repeats = sum(1 for i in range(1, len(toks)) if toks[i] == toks[i - 1])
    return repeats / (len(toks) - 1)


def repeated_token_ratio(text: str) -> float:
    """Single 0.0–1.0 repetitiveness score (the stronger of the two signals)."""
    return max(dominant_token_ratio(text), consecutive_repeat_ratio(text))


def is_low_quality_transcript(
    text: str,
    *,
    min_words: int = MIN_WORDS_FOR_REPEAT_CHECK,
    threshold: float = REPEATED_TOKEN_RATIO_THRESHOLD,
) -> bool:
    """True when ``text`` looks like repeated-token hallucination.

    Sub-meaningful output (below ``min_words``) is left to the no-speech gate.
    At or above that floor — including a short 3–5 word answer — a transcript
    dominated by one repeated token (``"new new new"``) fails closed, while a
    short phrase of distinct words (``"backend route scoring"``) scores well
    below ``threshold`` and passes. A normal explanation — many distinct words,
    few adjacent duplicates — passes as well.
    """
    toks = _tokens(text)
    if len(toks) < min_words:
        return False
    return repeated_token_ratio(text) >= threshold


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

def _is_video_input(filename: str, content_type: str | None) -> bool:
    """Decide whether media needs ffmpeg audio extraction before Whisper.

    content_type wins when present: ``video/*`` → video, ``audio/*`` → audio.
    This is what disambiguates ``.webm``: a browser screen+mic recording arrives
    as ``video/webm`` (VP8/VP9 video + Opus audio) and MUST have its audio track
    extracted, while a microphone-only recording arrives as ``audio/webm`` and
    can be decoded directly.

    Only when there is NO content_type do we fall back to the file extension, and
    there we stay conservative: just the unambiguous video containers (mp4/mov)
    are treated as video. A bare ``.webm`` with no content_type is treated as
    audio (the Extension Proof microphone default) so existing behaviour is
    preserved.
    """
    ct = (content_type or "").strip().lower()
    if ct.startswith("video/"):
        return True
    if ct.startswith("audio/"):
        return False
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in _VIDEO_EXTS


def _transcribe_local_whisper(
    file_bytes: bytes,
    filename: str,
    content_type: str | None = None,
) -> TranscriptionResult:
    """
    Transcribe using faster-whisper running locally on CPU or GPU.

    Requires:
      pip install faster-whisper

    Video inputs (mp4/mov and browser ``video/webm`` screen+mic recordings)
    require ffmpeg: the audio track is extracted and normalised to 16 kHz mono
    WAV before Whisper runs.  Classification is content_type-first via
    ``_is_video_input`` — this is what lets a VBR ``video/webm`` recording be
    handled as video while an Extension Proof ``audio/webm`` recording is decoded
    directly.

      brew install ffmpeg   /   apt install ffmpeg

    Audio inputs (mp3/wav/audio-webm/m4a) are passed directly to Whisper.
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

    # Keep the original extension on the temp input file so ffmpeg (and Whisper's
    # own decoder for the audio path) can identify the container.
    safe_name = os.path.basename(filename) or "input"

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, safe_name)
        with open(input_path, "wb") as fh:
            fh.write(file_bytes)

        # ── Video → audio extraction + normalisation via ffmpeg ───────────────
        # content_type-first so a browser video/webm (screen+mic) recording is
        # extracted to clean 16 kHz mono WAV instead of being handed to Whisper
        # as an undecodable video container.
        if _is_video_input(filename, content_type):
            audio_path = os.path.join(tmpdir, "audio_extracted.wav")
            try:
                extract = subprocess.run(
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
                # Server-side diagnostic only: did the recording actually carry a
                # microphone/audio stream, and how long is it? A screen capture
                # with no mic track produces silence → a no-speech transcript.
                # We log booleans/duration parsed from ffmpeg's probe output; we
                # never log the raw stderr (it contains temp file paths).
                _log_audio_stream_summary(extract.stderr)
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
        # Force a language (default English for the MVP) so short/quiet clips do
        # not misfire to obscure low-confidence languages; language=None restores
        # Whisper auto-detection.
        forced_language = _LOCAL_WHISPER_LANGUAGE or None
        try:
            model = WhisperModel(
                _LOCAL_WHISPER_MODEL_SIZE,
                device=_LOCAL_WHISPER_DEVICE,
                compute_type=_LOCAL_WHISPER_COMPUTE_TYPE,
            )
            # Anti-hallucination decoding config (see config.py):
            #   - vad_filter strips silence (no dead air to hallucinate over)
            #   - condition_on_previous_text=False stops a repeated token from
            #     feeding itself forward into a "new new new …" loop
            #   - temperature=0 greedy decoding; thresholds drop low-confidence /
            #     degenerate (highly compressible ⇒ repetitive) segments
            segments_iter, info = model.transcribe(
                audio_path,
                language=forced_language,
                beam_size=_LOCAL_WHISPER_BEAM_SIZE,
                temperature=_LOCAL_WHISPER_TEMPERATURE,
                vad_filter=_LOCAL_WHISPER_VAD,
                condition_on_previous_text=_LOCAL_WHISPER_CONDITION_ON_PREVIOUS_TEXT,
                no_speech_threshold=_LOCAL_WHISPER_NO_SPEECH_THRESHOLD,
                compression_ratio_threshold=_LOCAL_WHISPER_COMPRESSION_RATIO_THRESHOLD,
                log_prob_threshold=_LOCAL_WHISPER_LOG_PROB_THRESHOLD,
                word_timestamps=False,
            )
            # Materialise the generator so we can iterate twice
            raw_segments = list(segments_iter)
            raw_text = " ".join(seg.text for seg in raw_segments).strip()
            detected_language: str | None = forced_language or getattr(info, "language", None)
        except Exception as exc:
            # logger.exception records the full traceback for local/server debugging.
            # The message contains no transcript text, storage paths, or signed URLs.
            logger.exception(
                "local_whisper transcription failed (stage=transcribe, model=%s, device=%s, "
                "compute_type=%s, language=%s)",
                _LOCAL_WHISPER_MODEL_SIZE,
                _LOCAL_WHISPER_DEVICE,
                _LOCAL_WHISPER_COMPUTE_TYPE,
                forced_language or "auto",
            )
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


# ffmpeg prints stream/duration info to stderr, e.g.
#   Duration: 00:00:23.45, start: ...
#   Stream #0:1(eng): Audio: opus, 48000 Hz, mono ...
_FFMPEG_AUDIO_STREAM_RE = re.compile(r"Stream #\d+:\d+.*: Audio:", re.IGNORECASE)
_FFMPEG_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def _log_audio_stream_summary(stderr: bytes | None) -> None:
    """Log a safe yes/no audio-stream + duration summary from ffmpeg stderr.

    Diagnostics only — used to investigate whether a screen+mic recording
    actually carried a microphone/audio track (a mic-less screen capture
    produces silence → a no-speech transcript). Only parsed booleans and a
    duration are logged; the raw stderr (which contains temp file paths) is
    never logged, and nothing here reaches any API response. Never raises.
    """
    try:
        text = (stderr or b"").decode(errors="replace")
        audio_stream_detected = bool(_FFMPEG_AUDIO_STREAM_RE.search(text))
        duration_match = _FFMPEG_DURATION_RE.search(text)
        duration_s: float | None = None
        if duration_match:
            hours, minutes, seconds = duration_match.groups()
            duration_s = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        logger.info(
            "audio extraction summary (stage=ffmpeg_extract, audio_stream_detected=%s, duration_s=%s)",
            audio_stream_detected,
            f"{duration_s:.2f}" if duration_s is not None else "unknown",
        )
    except Exception:
        # A diagnostic log must never break transcription.
        logger.debug("audio extraction summary parse skipped", exc_info=True)
