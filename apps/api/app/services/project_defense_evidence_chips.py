"""Project Defense — Video Transcript Evidence Chips (Phase 1.5).

Builds small, safe, timestamped evidence references ("chips") from
``vbr_transcript_segments`` produced by ``vbr_transcription.transcribe_session``.

Each chip points to a short window of the video transcript and links it to a
claimed skill or a defense question, e.g.::

    {
        "label": "Video 03:12",
        "timestamp_start_s": 192.0,
        "timestamp_end_s": 205.0,
        "short_summary": "I built the backend risk-scoring API using FastAPI.",
        "related_skill": "Python",
        "question_id": None,
        "source": "project_defense_video",
        "source_type": "video_transcript",
    }

This is rule-based (no LLM) and project-agnostic. Chips never contain the
full transcript, storage paths, signed URLs, or raw provider payloads —
``short_summary`` is a short, whitespace-collapsed snippet of a single
segment's text, run through ``_sanitize_transcript_text`` to redact any
storage paths, signed/upload URLs, tokens, env-style key/value pairs, or
local filesystem paths a speaker might accidentally read aloud.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

__all__ = ["EvidenceChip", "build_evidence_chips"]

_MAX_CHIPS = 8
_SNIPPET_MAX_LEN = 160

_REDACTED = "[redacted]"

# Sensitive key=value / key: value fragments — e.g. ``storage_path=vbr/sessions/abc``,
# ``signed_url=https://...``, ``token=abc``, ``service_role_key: xyz``. The value side
# (``\S+``) is greedy so it also swallows any trailing query string.
_SENSITIVE_KEY_VALUE_RE = re.compile(
    r"\b(?:"
    r"storage[_-]?path|signed[_-]?url|upload[_-]?url|download[_-]?url|"
    r"access[_-]?token|refresh[_-]?token|auth[_-]?token|id[_-]?token|"
    r"service[_-]?role(?:[_-]?key)?|anon[_-]?key|api[_-]?key|"
    r"secret(?:[_-]?key)?|client[_-]?secret|bucket(?:[_-]?name)?|token"
    r")\s*[=:]\s*\S+",
    re.IGNORECASE,
)

# Bare sensitive identifiers that leak internal naming/architecture even without a
# value attached — e.g. a transcript saying "...uses the service_role key...".
_SENSITIVE_BARE_KEYWORD_RE = re.compile(
    r"\b(?:storage[_-]?path|signed[_-]?url|upload[_-]?url|download[_-]?url|"
    r"service[_-]?role(?:[_-]?key)?|anon[_-]?key|access[_-]?token|refresh[_-]?token)\b",
    re.IGNORECASE,
)

# "Bearer <token>" style auth headers.
_BEARER_TOKEN_RE = re.compile(r"\bBearer\s+\S+", re.IGNORECASE)

# Generic ENV_STYLE_KEY=value pairs (e.g. SUPABASE_SERVICE_ROLE_KEY=eyJ...).
_ENV_KEY_VALUE_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\s*=\s*\S+")

# http(s) URLs — covers Supabase/storage URLs and signed URLs with query strings.
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

# Bare ``vbr/sessions/...`` storage paths not already part of a URL or key=value.
_VBR_SESSIONS_PATH_RE = re.compile(r"\bvbr/sessions/\S+", re.IGNORECASE)

# Local filesystem paths: Windows drive paths and common Unix home/tmp/system paths.
_LOCAL_PATH_RE = re.compile(
    r"(?:[A-Za-z]:\\\S+|/(?:Users|home|var|tmp|etc|root|opt|private)/\S+)",
    re.IGNORECASE,
)

# Path-like strings ending in a media/document file extension.
_MEDIA_PATH_RE = re.compile(
    r"\b\S+\.(?:mp4|mov|webm|mkv|m4a|wav|mp3|aac|ogg|png|jpe?g|gif|pdf|zip)\b",
    re.IGNORECASE,
)

_SANITIZE_PATTERNS: tuple[re.Pattern[str], ...] = (
    _SENSITIVE_KEY_VALUE_RE,
    _ENV_KEY_VALUE_RE,
    _BEARER_TOKEN_RE,
    _SENSITIVE_BARE_KEYWORD_RE,
    _URL_RE,
    _VBR_SESSIONS_PATH_RE,
    _LOCAL_PATH_RE,
    _MEDIA_PATH_RE,
)


@dataclass
class EvidenceChip:
    label: str
    timestamp_start_s: float
    timestamp_end_s: float
    short_summary: str
    related_skill: str | None = None
    question_id: str | None = None
    source: str = "project_defense_video"
    source_type: str = "video_transcript"


def _format_timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _sanitize_transcript_text(text: str) -> str:
    """Redact storage/auth/URL/path fragments that must never leave the backend.

    Transcript text is user-spoken (often dictated while looking at a terminal or
    browser), so it can accidentally contain storage paths, signed URLs, tokens,
    or local file paths. These must not reach API responses, session telemetry,
    or Skill Graph artifacts. Ordinary technical vocabulary (Python, FastAPI,
    "risk scoring", etc.) is left untouched since none of these patterns match it.
    """
    sanitized = text
    for pattern in _SANITIZE_PATTERNS:
        sanitized = pattern.sub(_REDACTED, sanitized)
    return sanitized


def _snippet(text: str, max_len: int = _SNIPPET_MAX_LEN) -> str:
    collapsed = " ".join(_sanitize_transcript_text(text or "").split())
    if len(collapsed) <= max_len:
        return collapsed
    return collapsed[:max_len].rstrip() + "…"


def _skill_pattern(skill: str) -> re.Pattern[str] | None:
    """Build a case-insensitive match pattern for a skill name.

    Mirrors the matching logic in ``project_defense_analysis_service``: match
    on individual words (>= 3 chars) of the skill, falling back to the full
    skill string for short/single-token skill names (e.g. "Go", "C").
    """
    skill = (skill or "").strip()
    if not skill:
        return None
    words = [w for w in re.split(r"[\s/._-]+", skill) if len(w) >= 3]
    if words:
        pattern = "|".join(rf"\b{re.escape(w)}" for w in words)
    else:
        pattern = re.escape(skill)
    return re.compile(pattern, re.IGNORECASE)


def build_evidence_chips(
    segments: list[dict[str, Any]],
    claimed_skills: list[str] | None = None,
    questions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build safe timestamped evidence chips from video transcript segments.

    Rule-based: a segment becomes a chip only if its text matches a claimed
    skill or a defense question's linked skill (``target_ref.skill``).
    Returns at most ``_MAX_CHIPS`` chips, ordered by ``start_s``.

    Returns ``[]`` if ``segments`` is empty — callers should treat this as
    "no chips yet", not an error.
    """
    if not segments:
        return []

    skill_patterns: list[tuple[str, re.Pattern[str]]] = []
    for skill in claimed_skills or []:
        pattern = _skill_pattern(skill)
        if pattern is not None:
            skill_patterns.append((skill, pattern))

    question_patterns: list[tuple[str | None, str | None, re.Pattern[str]]] = []
    questions_by_id: dict[str, dict[str, Any]] = {}
    for question in questions or []:
        if question.get("id"):
            questions_by_id[str(question["id"])] = question
        target_ref = question.get("target_ref") or {}
        skill = target_ref.get("skill") if isinstance(target_ref, dict) else None
        if not skill:
            continue
        pattern = _skill_pattern(str(skill))
        if pattern is not None:
            question_patterns.append((question.get("id"), str(skill), pattern))

    chips: list[EvidenceChip] = []
    sorted_segments = sorted(segments, key=lambda s: float(s.get("start_s") or 0.0))

    for segment in sorted_segments:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue

        matched_skill: str | None = None
        matched_question_id: str | None = None

        # A segment that answers a known question is anchored to that question:
        # its chip maps to the question's own targeted skill (if any) and is
        # never keyword-mapped onto an unrelated skill.
        segment_question_id = str(segment.get("question_id") or "") or None
        if segment_question_id and segment_question_id in questions_by_id:
            matched_question_id = segment_question_id
            target_ref = questions_by_id[segment_question_id].get("target_ref") or {}
            q_skill = target_ref.get("skill") if isinstance(target_ref, dict) else None
            matched_skill = str(q_skill) if q_skill else None
        else:
            for skill, pattern in skill_patterns:
                if pattern.search(text):
                    matched_skill = skill
                    break

            if matched_skill is None:
                for question_id, q_skill, pattern in question_patterns:
                    if pattern.search(text):
                        matched_question_id = str(question_id) if question_id else None
                        matched_skill = q_skill
                        break

        if matched_skill is None and matched_question_id is None:
            continue

        start_s = float(segment.get("start_s") or 0.0)
        end_s = float(segment.get("end_s") or start_s)
        chips.append(
            EvidenceChip(
                label=f"Video {_format_timestamp(start_s)}",
                timestamp_start_s=round(start_s, 2),
                timestamp_end_s=round(end_s, 2),
                short_summary=_snippet(text),
                related_skill=matched_skill,
                question_id=matched_question_id,
            )
        )
        if len(chips) >= _MAX_CHIPS:
            break

    return [asdict(chip) for chip in chips]
