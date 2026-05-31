"""Video Keyframe Extractor Service.

Extracts evenly-spaced keyframes from browser-recorded workflow videos
(WebM, MP4, etc.) for downstream visual analysis.

Architecture
------------
The service is provider-agnostic for its extraction backend:

  cv2     — pip install opencv-python-headless  (recommended; pure Python, no codec deps)
  ffmpeg  — system binary (brew install ffmpeg / apt install ffmpeg)  fallback

When neither is installed the service returns VIDEO_STATUS_NOT_AVAILABLE and
logs a clear install instruction.  DOM evidence continues to work unchanged.

Privacy guarantees
------------------
  • Raw video bytes are NEVER persisted to the database or external storage.
    They are processed in-memory; the temporary file used by cv2 is deleted
    immediately after extraction.
  • Extracted keyframes (JPEG) are stored only via WorkflowVisualAnalysisService
    which keeps them as private metadata records — no public-facing storage URL.
  • VideoKeyframeResult._extracted_frames is a private attribute excluded from
    to_public_dict().  It is intentionally undocumented in the API response.
  • to_public_dict() is the only serialisation allowed in API responses.

Limits (all configurable via env — see config.py)
--------------------------------------------------
  MAX_VIDEO_SIZE_BYTES         — default 100 MB
  MAX_VIDEO_DURATION_SECONDS   — default 300 s (5 min)
  MAX_VIDEO_KEYFRAMES          — default 10
"""

from __future__ import annotations

import glob
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Status values ──────────────────────────────────────────────────────────────

VIDEO_STATUS_ANALYZED       = "analyzed"
VIDEO_STATUS_FAILED         = "failed"
VIDEO_STATUS_NOT_AVAILABLE  = "not_available"
VIDEO_STATUS_UNSUPPORTED    = "unsupported_format"
VIDEO_STATUS_LIMIT_EXCEEDED = "limit_exceeded"


# ── Allowed formats ────────────────────────────────────────────────────────────

# MIME types accepted from browser-recorded videos.
# application/octet-stream is included because some browsers send it for WebM.
_ALLOWED_MIME_TYPES: frozenset[str] = frozenset({
    "video/webm",
    "video/mp4",
    "video/x-matroska",
    "video/ogg",
    "video/x-msvideo",
    "application/octet-stream",
})

_ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".webm", ".mp4", ".mkv", ".ogg", ".ogv", ".avi",
})


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class VideoKeyframeResult:
    """Output from video keyframe extraction.

    Public fields (safe for API responses):
        video_analysis_status, keyframe_count, selected_frame_timestamps_ms,
        extraction_method, duration_ms, limitations

    Private field (_extracted_frames):
        In-memory JPEG frame bytes for internal use only.
        NEVER serialised; excluded from to_public_dict().
    """

    video_analysis_status: str
    keyframe_count: int
    selected_frame_timestamps_ms: list[int]
    extraction_method: str       # "cv2_interval" | "ffmpeg_interval" | "none"
    duration_ms: int | None
    frame_width: int | None
    frame_height: int | None
    limitations: list[str]

    # Private: (timestamp_ms, jpeg_bytes) pairs.
    # The leading underscore is intentional — callers should access this
    # only for internal storage, never for public serialisation.
    _extracted_frames: list[tuple[int, bytes]] = field(
        default_factory=list, repr=False,
    )

    def to_public_dict(self) -> dict[str, Any]:
        """Return a recruiter / student-safe representation.

        Guarantees:
          - No _extracted_frames (raw pixel data).
          - No frame_storage_path, no access tokens, no private debug metadata.
          - Only status/count/timestamp metadata that is safe to log or display.
        """
        return {
            "video_analysis_status":      self.video_analysis_status,
            "keyframe_count":             self.keyframe_count,
            "selected_frame_timestamps_ms": self.selected_frame_timestamps_ms,
            "extraction_method":          self.extraction_method,
            "duration_ms":               self.duration_ms,
            "limitations":               self.limitations,
        }


# ── Internal sentinel exceptions ───────────────────────────────────────────────

class _Cv2Unavailable(Exception):
    """cv2 (opencv-python-headless) is not installed."""


class _FfmpegUnavailable(Exception):
    """ffmpeg binary is not found on PATH."""


# ── Service ────────────────────────────────────────────────────────────────────

class VideoKeyframeExtractorService:
    """Extract evenly-spaced keyframes from a recorded workflow video.

    Usage:
        svc = VideoKeyframeExtractorService()
        result = svc.extract_keyframes(
            video_bytes=file_bytes,
            filename="recording.webm",
            mime_type="video/webm",
        )
        if result.video_analysis_status == VIDEO_STATUS_ANALYZED:
            for ts_ms, jpeg_bytes in result._extracted_frames:
                frame_id = va_svc.store_visual_frame(
                    user_id=uid, session_id=sid,
                    frame_type="video_keyframe",
                    frame_bytes=jpeg_bytes,
                    timestamp_ms=ts_ms,
                )

    Constructor arguments override the env settings — useful for tests.
    """

    def __init__(
        self,
        max_size_bytes: int | None = None,
        max_duration_seconds: int | None = None,
        max_keyframes: int | None = None,
    ) -> None:
        from app.core.config import settings
        self._max_size      = max_size_bytes      or settings.max_video_size_bytes
        self._max_duration  = max_duration_seconds or settings.max_video_duration_seconds
        self._max_keyframes = max_keyframes        or settings.max_video_keyframes

    # ── Public API ─────────────────────────────────────────────────────────────

    def extract_keyframes(
        self,
        video_bytes: bytes | None,
        filename: str = "recording.webm",
        mime_type: str = "video/webm",
    ) -> VideoKeyframeResult:
        """Extract up to max_keyframes evenly-spaced frames.

        Never raises — returns a VideoKeyframeResult with an appropriate
        status code even when the video is invalid or backends are unavailable.
        """

        # ── 1. Null / empty bytes ──────────────────────────────────────────────
        if not video_bytes:
            return _make_failed(
                "No video bytes provided.",
                extraction_method="none",
            )

        # ── 2. Size limit ──────────────────────────────────────────────────────
        size_bytes = len(video_bytes)
        if size_bytes > self._max_size:
            mb       = size_bytes           // (1024 * 1024)
            limit_mb = self._max_size       // (1024 * 1024)
            return VideoKeyframeResult(
                video_analysis_status=VIDEO_STATUS_LIMIT_EXCEEDED,
                keyframe_count=0,
                selected_frame_timestamps_ms=[],
                extraction_method="none",
                duration_ms=None,
                frame_width=None,
                frame_height=None,
                limitations=[
                    f"Video size {mb} MB exceeds the limit of {limit_mb} MB. "
                    "Please record a shorter workflow demonstration."
                ],
            )

        # ── 3. Format / MIME validation ────────────────────────────────────────
        clean_mime = (mime_type or "").split(";")[0].strip().lower()
        ext        = os.path.splitext(filename.lower())[1] if filename else ""

        if clean_mime not in _ALLOWED_MIME_TYPES and ext not in _ALLOWED_EXTENSIONS:
            return VideoKeyframeResult(
                video_analysis_status=VIDEO_STATUS_UNSUPPORTED,
                keyframe_count=0,
                selected_frame_timestamps_ms=[],
                extraction_method="none",
                duration_ms=None,
                frame_width=None,
                frame_height=None,
                limitations=[
                    f"Unsupported video format '{clean_mime or ext}'. "
                    "Supported: WebM (video/webm), MP4 (video/mp4), MKV, OGG."
                ],
            )

        # ── 4. Try cv2, then ffmpeg, then not_available ────────────────────────
        # IMPORTANT: If cv2 *returns* a non-ANALYZED result (e.g. frame_count=0
        # for browser WebM streaming format), we still fall through to ffmpeg.
        # Previously the early `return` prevented this fallback — now fixed.
        cv2_error: str | None = None
        ffmpeg_error: str | None = None

        try:
            cv2_result = self._extract_with_cv2(video_bytes, filename)
            if cv2_result.video_analysis_status == VIDEO_STATUS_ANALYZED:
                return cv2_result
            # Limit exceeded: no point trying ffmpeg (it would hit the same limit).
            if cv2_result.video_analysis_status == VIDEO_STATUS_LIMIT_EXCEEDED:
                return cv2_result
            # cv2 is installed and ran but failed to decode this video (e.g.
            # total_frames=0 or negative for browser MediaRecorder WebM streaming
            # format). Fall through to ffmpeg which handles this format better.
            cv2_error = (
                cv2_result.limitations[0]
                if cv2_result.limitations
                else "cv2 decode produced no frames"
            )
            logger.info(
                "[VideoKeyframes] cv2 returned %s — trying ffmpeg fallback: %s",
                cv2_result.video_analysis_status, cv2_error,
            )
        except _Cv2Unavailable:
            pass   # not installed — fall through to ffmpeg
        except Exception as exc:
            cv2_error = str(exc)
            logger.warning("[VideoKeyframes] cv2 extraction raised: %s", exc)

        try:
            return self._extract_with_ffmpeg(video_bytes, filename)
        except _FfmpegUnavailable:
            pass   # not installed — fall through to not_available
        except Exception as exc:
            ffmpeg_error = str(exc)
            logger.warning("[VideoKeyframes] ffmpeg extraction failed: %s", exc)

        # Both backends were tried (and not merely unavailable) → report failure
        if cv2_error or ffmpeg_error:
            detail = cv2_error or ffmpeg_error or "unknown error"
            return _make_failed(
                f"Keyframe extraction failed. Detail: {detail[:200]}",
                extraction_method="none",
            )

        # Neither cv2 nor ffmpeg is installed
        return VideoKeyframeResult(
            video_analysis_status=VIDEO_STATUS_NOT_AVAILABLE,
            keyframe_count=0,
            selected_frame_timestamps_ms=[],
            extraction_method="none",
            duration_ms=None,
            frame_width=None,
            frame_height=None,
            limitations=[
                "Video keyframe extraction requires opencv-python-headless or ffmpeg. "
                "Install cv2: pip install opencv-python-headless  "
                "Install ffmpeg: brew install ffmpeg (macOS) / apt install ffmpeg (Linux)"
            ],
        )

    # ── cv2 backend ────────────────────────────────────────────────────────────

    def _extract_with_cv2(
        self, video_bytes: bytes, filename: str
    ) -> VideoKeyframeResult:
        """Extract keyframes using OpenCV.

        Raises _Cv2Unavailable when cv2 is not installed.
        Raises other exceptions for decoding errors (caller handles these).
        """
        try:
            import cv2  # type: ignore[import]
        except ImportError as exc:
            raise _Cv2Unavailable() from exc

        ext = os.path.splitext(filename.lower())[1] or ".webm"

        # cv2.VideoCapture requires a file path; write bytes to a temp file.
        # The file is deleted in the finally block even if decoding fails.
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
                tf.write(video_bytes)
                tmp_path = tf.name

            cap = cv2.VideoCapture(tmp_path)
            if not cap.isOpened():
                return _make_failed(
                    "Could not open video file. "
                    "The file may be corrupt or use an unsupported codec.",
                    extraction_method="cv2_interval",
                )

            fps          = cap.get(cv2.CAP_PROP_FPS) or 25.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            frame_width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            # duration_ms: estimated from frame count if available; set later from
            # actual last-frame timestamp when total_frames is 0 (streaming format).
            duration_ms  = int((total_frames / fps) * 1000) if total_frames > 0 else None

            # Duration limit check (skip when unknown — enforce after extraction)
            if duration_ms is not None:
                duration_s = duration_ms / 1000
                if duration_s > self._max_duration:
                    cap.release()
                    return VideoKeyframeResult(
                        video_analysis_status=VIDEO_STATUS_LIMIT_EXCEEDED,
                        keyframe_count=0,
                        selected_frame_timestamps_ms=[],
                        extraction_method="cv2_interval",
                        duration_ms=duration_ms,
                        frame_width=frame_width,
                        frame_height=frame_height,
                        limitations=[
                            f"Video duration {duration_s:.0f}s exceeds the limit of "
                            f"{self._max_duration}s. "
                            "Record a shorter workflow demonstration."
                        ],
                    )

            extracted_frames: list[tuple[int, bytes]] = []

            if total_frames <= 0:
                # Browser MediaRecorder WebM: streaming format with unknown frame count.
                # CAP_PROP_FRAME_COUNT returns 0 for live/streaming WebM containers.
                # Fall back to sequential reading — read every Nth frame.
                logger.info(
                    "[VideoKeyframes] cv2: total_frames=0 for %s (streaming format), "
                    "using sequential read", filename,
                )
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                frame_pos = 0
                # We don't know duration; sample at a fixed interval.
                # Target: read up to max_keyframes frames spaced ~1s apart.
                # At unknown fps, sample every ~10 decoded frames as a heuristic.
                sample_every = max(1, int(fps / 2)) if fps > 0 else 5
                while len(extracted_frames) < self._max_keyframes:
                    ret, frame = cap.read()
                    if not ret:
                        break
                    if frame_pos % sample_every == 0:
                        ts_ms = int(cap.get(cv2.CAP_PROP_POS_MSEC))
                        ok, buf = cv2.imencode(
                            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80]
                        )
                        if ok:
                            extracted_frames.append((ts_ms, bytes(buf)))
                    frame_pos += 1
            else:
                # Select evenly-distributed frame positions (capped to max_keyframes)
                n = min(self._max_keyframes, max(1, total_frames))
                if total_frames <= n:
                    positions = list(range(total_frames))
                else:
                    step      = total_frames / n
                    positions = [int(i * step) for i in range(n)]

                for pos in positions:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
                    ret, frame = cap.read()
                    if not ret:
                        continue
                    ts_ms = int((pos / fps) * 1000)
                    success, buf = cv2.imencode(
                        ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80]
                    )
                    if success:
                        extracted_frames.append((ts_ms, bytes(buf)))

            cap.release()

            if not extracted_frames:
                return _make_failed(
                    "No frames could be decoded from the video. "
                    "The file may be corrupt, truncated, or use an unsupported codec.",
                    extraction_method="cv2_interval",
                    duration_ms=duration_ms,
                    frame_width=frame_width,
                    frame_height=frame_height,
                )

            # For streaming format (total_frames=0), derive duration from last frame ts
            if duration_ms is None and extracted_frames:
                duration_ms = extracted_frames[-1][0]

            logger.info(
                "[VideoKeyframes] cv2 extracted %d frames from %s (%.1f s)",
                len(extracted_frames), filename, (duration_ms or 0) / 1000,
            )
            return VideoKeyframeResult(
                video_analysis_status=VIDEO_STATUS_ANALYZED,
                keyframe_count=len(extracted_frames),
                selected_frame_timestamps_ms=[f[0] for f in extracted_frames],
                extraction_method="cv2_interval",
                duration_ms=duration_ms,
                frame_width=frame_width,
                frame_height=frame_height,
                limitations=[],
                _extracted_frames=extracted_frames,
            )

        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # ── ffmpeg backend ─────────────────────────────────────────────────────────

    def _extract_with_ffmpeg(
        self, video_bytes: bytes, filename: str
    ) -> VideoKeyframeResult:
        """Extract keyframes using the ffmpeg system binary.

        Raises _FfmpegUnavailable when ffmpeg is not on PATH.
        Raises other exceptions for decoding errors.
        """
        # Quick availability check
        try:
            probe_check = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                timeout=10,
                check=False,
            )
            if probe_check.returncode != 0:
                raise _FfmpegUnavailable()
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise _FfmpegUnavailable() from exc

        ext = os.path.splitext(filename.lower())[1] or ".webm"
        tmp_path: str | None = None

        try:
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
                tf.write(video_bytes)
                tmp_path = tf.name

            # ── Probe duration ─────────────────────────────────────────────────
            duration_ms: int | None = None
            duration_s  = 60.0   # fallback if probe fails

            try:
                probe_result = subprocess.run(
                    [
                        "ffprobe", "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        tmp_path,
                    ],
                    capture_output=True, text=True, timeout=30, check=False,
                )
                if probe_result.returncode == 0 and probe_result.stdout.strip():
                    duration_s  = float(probe_result.stdout.strip())
                    duration_ms = int(duration_s * 1000)
            except Exception as exc:
                logger.debug("[VideoKeyframes] ffprobe failed (non-fatal): %s", exc)

            # Duration limit check
            if duration_ms is not None and duration_s > self._max_duration:
                return VideoKeyframeResult(
                    video_analysis_status=VIDEO_STATUS_LIMIT_EXCEEDED,
                    keyframe_count=0,
                    selected_frame_timestamps_ms=[],
                    extraction_method="ffmpeg_interval",
                    duration_ms=duration_ms,
                    frame_width=None,
                    frame_height=None,
                    limitations=[
                        f"Video duration {duration_s:.0f}s exceeds the limit of "
                        f"{self._max_duration}s. "
                        "Record a shorter workflow demonstration."
                    ],
                )

            # ── Extract frames ─────────────────────────────────────────────────
            n        = self._max_keyframes
            interval = max(0.1, duration_s / n)   # seconds between extracted frames

            with tempfile.TemporaryDirectory() as output_dir:
                output_pattern = os.path.join(output_dir, "frame_%04d.jpg")

                ffmpeg_result = subprocess.run(
                    [
                        "ffmpeg", "-i", tmp_path,
                        "-vf", f"fps=1/{interval:.3f}",
                        "-vframes", str(n),
                        "-q:v", "3",
                        "-y",
                        output_pattern,
                    ],
                    capture_output=True,
                    timeout=120,
                    check=False,
                )

                if ffmpeg_result.returncode != 0:
                    return _make_failed(
                        "ffmpeg failed to extract frames. File may be corrupt.",
                        extraction_method="ffmpeg_interval",
                        duration_ms=duration_ms,
                    )

                frame_files = sorted(
                    glob.glob(os.path.join(output_dir, "frame_*.jpg"))
                )
                extracted_frames: list[tuple[int, bytes]] = []

                for i, fpath in enumerate(frame_files[:n]):
                    ts_ms = int(i * interval * 1000)
                    try:
                        with open(fpath, "rb") as fh:
                            extracted_frames.append((ts_ms, fh.read()))
                    except OSError:
                        continue

                if not extracted_frames:
                    return _make_failed(
                        "ffmpeg produced no output frames.",
                        extraction_method="ffmpeg_interval",
                        duration_ms=duration_ms,
                    )

                logger.info(
                    "[VideoKeyframes] ffmpeg extracted %d frames from %s (%.1f s)",
                    len(extracted_frames), filename, duration_s,
                )
                return VideoKeyframeResult(
                    video_analysis_status=VIDEO_STATUS_ANALYZED,
                    keyframe_count=len(extracted_frames),
                    selected_frame_timestamps_ms=[f[0] for f in extracted_frames],
                    extraction_method="ffmpeg_interval",
                    duration_ms=duration_ms,
                    frame_width=None,
                    frame_height=None,
                    limitations=[],
                    _extracted_frames=extracted_frames,
                )

        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_failed(
    limitation: str,
    extraction_method: str = "none",
    duration_ms: int | None = None,
    frame_width: int | None = None,
    frame_height: int | None = None,
) -> VideoKeyframeResult:
    return VideoKeyframeResult(
        video_analysis_status=VIDEO_STATUS_FAILED,
        keyframe_count=0,
        selected_frame_timestamps_ms=[],
        extraction_method=extraction_method,
        duration_ms=duration_ms,
        frame_width=frame_width,
        frame_height=frame_height,
        limitations=[limitation],
    )
