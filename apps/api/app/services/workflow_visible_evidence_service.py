"""Workflow Visible Evidence Service.

Handles ingestion, sanitization, storage, and extraction of DOM-visible
evidence captured by the browser extension during website proof recordings.

Privacy guarantees:
  - Server-side sanitization runs on EVERY event before storage, even if the
    extension already sanitized client-side.
  - Sensitive patterns (passwords, API keys, tokens, emails, local paths,
    Supabase URLs, credit cards, SSNs) are masked or removed.
  - Recruiter-facing surfaces never receive raw visible_text_blocks.

Design:
  - Dynamic extraction — no hardcoded app types, labels, or domain-specific logic.
  - Result values are extracted using generic regex patterns that match
    "label: number", "label number%", table-like structures, etc.
  - Extraction is conservative: if a value is not clearly captured in visible
    text, it is NOT reported.

Usage:
  svc = WorkflowVisibleEvidenceService(db_client)
  svc.ingest(user_id, session_id, events)          # stores events
  obs = svc.get_extracted_observations(user_id, session_id)  # for workflow analysis
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any
from uuid import uuid4

from app.schemas.workflow_visible_evidence import (
    ExtractedObservations,
    ExtractedResultValue,
    FileUploadMeta,
    VisibleEvidenceBatchRequest,
    VisibleEvidenceEventInput,
    VisibleEvidenceSummaryEvent,
    VisibleEvidenceSummaryResponse,
    VisibleEvidenceStatus,
)

logger = logging.getLogger(__name__)

_TABLE = "workflow_visible_evidence_events"

# ---------------------------------------------------------------------------
# Sanitization patterns
# ---------------------------------------------------------------------------

# Patterns that indicate a text block contains sensitive information.
# When matched, the specific part is REPLACED with a placeholder.

_SENSITIVE_REPLACE: list[tuple[re.Pattern[str], str]] = [
    # API keys / tokens in key=value form (covers Authorization headers, env vars, etc.)
    (
        re.compile(
            r'\b(password|passwd|pwd|secret|api[_\-]?key|auth[_\-]?token|bearer'
            r'|jwt|session[_\-]?id|access[_\-]?token|refresh[_\-]?token'
            r'|private[_\-]?key|client[_\-]?secret|x\-api\-key)\s*[:=]\s*\S+',
            re.IGNORECASE,
        ),
        r'\1: [REDACTED]',
    ),
    # Local file paths (Windows + Unix)
    (
        re.compile(r'(?:[A-Z]:\\|/(?:home|Users|var|tmp|root|private)/)[^\s,;>"\'<]+', re.IGNORECASE),
        '[LOCAL_PATH]',
    ),
    # Credit card-like strings (13-16 digit sequences)
    (
        re.compile(r'\b(?:\d[ \-]?){13,16}\b'),
        '[CARD_REDACTED]',
    ),
    # SSN-like strings
    (
        re.compile(r'\b\d{3}[\- ]\d{2}[\- ]\d{4}\b'),
        '[SSN_REDACTED]',
    ),
    # Supabase / internal service URLs
    (
        re.compile(r'https?://[a-z0-9\-]+\.supabase\.(co|io)[^\s,;>"\'<]*', re.IGNORECASE),
        '[INTERNAL_URL]',
    ),
    # VeriBridge localhost dashboard paths
    (
        re.compile(r'https?://localhost(?::\d+)?/(?:dashboard|admin|api/v1)[^\s,;>"\'<]*', re.IGNORECASE),
        '[INTERNAL_URL]',
    ),
    # Long hex strings that look like tokens (32+ hex chars)
    (
        re.compile(r'\b[0-9a-fA-F]{32,}\b'),
        '[TOKEN_REDACTED]',
    ),
    # JWT-shaped strings (three base64url segments)
    (
        re.compile(r'ey[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+'),
        '[JWT_REDACTED]',
    ),
]

# Patterns that FULLY DISCARD a text block (block is removed, not just replaced)
_DISCARD_BLOCK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'\b(password|passwd|auth[_\-]?token|bearer token)\b', re.IGNORECASE),
    re.compile(r'\bsupabase\b', re.IGNORECASE),
    re.compile(r'localhost:\d+/dashboard', re.IGNORECASE),
    re.compile(r'\bphpmyadmin\b', re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Result / output extraction patterns
# ---------------------------------------------------------------------------

# Keywords that suggest a text block is output-relevant
_RESULT_KEYWORDS: tuple[str, ...] = (
    "prediction", "result", "output", "score", "confidence", "probability",
    "risk", "detected", "label", "class", "classification", "summary",
    "answer", "response", "route", "recommendation", "generated", "analysis",
    "extracted", "accuracy", "precision", "recall", "sentiment", "entity",
    "detected objects", "inference", "bounding box", "segmentation",
    "alert", "severity", "likelihood", "grade", "rating", "estimate",
)

# Regex patterns to extract "label: value" or "label value" pairs
_RESULT_VALUE_REGEXES: list[re.Pattern[str]] = [
    # "dog: 0.89"  or  "dog: 89%"  (label: number)
    re.compile(r'\b([A-Za-z][A-Za-z0-9 _\-]{1,40}?):\s*([\d.]+)\s*(%|score|probability|confidence)?', re.IGNORECASE),
    # "risk score 72"  or  "confidence 0.91"  (keyword number)
    re.compile(
        r'\b(risk[_ ]?score|confidence|probability|accuracy|score|severity|likelihood|rating|grade)\s+:?\s*([\d.]+)\s*(%?)',
        re.IGNORECASE,
    ),
    # "Detected: dog (0.89)"
    re.compile(r'\bDetected\b[:\s]+([A-Za-z][A-Za-z0-9 _\-]{0,40}?)\s*\(?([\d.]+%?)\)?', re.IGNORECASE),
    # "Fatal: 45%"  or  "High: 72%"  severity-type
    re.compile(r'\b(fatal|high|medium|low|critical|moderate|elevated)\s*:\s*([\d.]+%?)\b', re.IGNORECASE),
]

# Max blocks to store / pass to analysis (keep cost manageable)
_MAX_VISIBLE_BLOCKS = 30
_MAX_RESULT_BLOCKS = 15
_MAX_TEXT_BLOCK_LEN = 400

# ---------------------------------------------------------------------------
# Sanitization helpers
# ---------------------------------------------------------------------------


def sanitize_text(text: str) -> tuple[str, list[str]]:
    """Apply server-side sanitization to a single text string.

    Returns (sanitized_text, privacy_flags_raised).
    Returns ("", ["discarded"]) when the block should be completely removed.
    """
    if not text or not text.strip():
        return "", []

    flags: list[str] = []

    # Discard entire block if it contains certain high-sensitivity patterns
    for pat in _DISCARD_BLOCK_PATTERNS:
        if pat.search(text):
            flags.append(f"discarded:{pat.pattern[:40]}")
            return "", flags

    # Apply replacements
    for pat, replacement in _SENSITIVE_REPLACE:
        if pat.search(text):
            text = pat.sub(replacement, text)
            flags.append(f"replaced:{pat.pattern[:40]}")

    # Truncate overly long blocks
    if len(text) > _MAX_TEXT_BLOCK_LEN:
        text = text[:_MAX_TEXT_BLOCK_LEN] + "…"
        flags.append("truncated")

    return text.strip(), flags


def sanitize_blocks(blocks: list[str]) -> tuple[list[str], list[str]]:
    """Sanitize a list of text blocks.  Returns (clean_blocks, all_flags)."""
    clean: list[str] = []
    all_flags: list[str] = []
    for block in (blocks or []):
        s, flags = sanitize_text(str(block))
        all_flags.extend(flags)
        if s:
            clean.append(s)
    return clean[:_MAX_VISIBLE_BLOCKS], all_flags


def sanitize_dict(d: dict) -> tuple[dict, list[str]]:
    """Recursively sanitize a dict (form inputs, action metadata, etc.)."""
    if not isinstance(d, dict):
        return {}, []
    result: dict = {}
    flags: list[str] = []

    _SKIP_KEYS = frozenset({
        "password", "passwd", "pwd", "secret", "token", "api_key",
        "apikey", "authorization", "credit_card", "card_number", "cvv", "ssn",
    })
    for k, v in d.items():
        k_lower = str(k).lower()
        # Redact entire value if key looks sensitive
        if any(skip in k_lower for skip in _SKIP_KEYS):
            result[k] = "[REDACTED]"
            flags.append(f"key_redacted:{k}")
            continue
        if isinstance(v, str):
            s, vf = sanitize_text(v)
            result[k] = s
            flags.extend(vf)
        elif isinstance(v, dict):
            nested, vf = sanitize_dict(v)
            result[k] = nested
            flags.extend(vf)
        elif isinstance(v, list):
            clean, vf = sanitize_blocks([str(i) for i in v])
            result[k] = clean
            flags.extend(vf)
        else:
            result[k] = v
    return result, flags


def sanitize_event(event: VisibleEvidenceEventInput) -> tuple[dict[str, Any], list[str]]:
    """Sanitize one event and return (row_dict, privacy_flags)."""
    all_flags: list[str] = []

    visible_blocks, vf = sanitize_blocks(event.visible_text_blocks)
    all_flags.extend(vf)

    result_blocks, rf = sanitize_blocks(event.result_like_blocks)
    all_flags.extend(rf)
    result_blocks = result_blocks[:_MAX_RESULT_BLOCKS]

    input_snap, isf = sanitize_dict(event.input_snapshot or {})
    all_flags.extend(isf)

    action_snap, asf = sanitize_dict(event.action_snapshot or {})
    all_flags.extend(asf)

    # URL: mask supabase/internal
    url_clean = str(event.url or "")
    for pat, _ in _SENSITIVE_REPLACE:
        url_clean = pat.sub("[REDACTED]", url_clean)

    # File upload meta — never store local path
    file_meta: dict = {}
    if event.file_upload_meta:
        fm = event.file_upload_meta
        masked_name: str | None = None
        if fm.file_name_masked:
            # Hash the filename so it's never reversible
            masked_name = "f:" + hashlib.sha256(fm.file_name_masked.encode()).hexdigest()[:12]
        file_meta = {
            "file_category": fm.file_category,
            "file_extension": fm.file_extension,
            "file_name_hash": masked_name,
        }

    target_domain = ""
    try:
        from urllib.parse import urlparse
        target_domain = urlparse(url_clean).netloc.lower()
    except Exception:
        pass

    # Canvas / SVG counts — stored safely in action_snapshot metadata
    if event.canvas_count is not None:
        action_snap["canvas_count"] = int(event.canvas_count)
    if event.svg_count is not None:
        action_snap["svg_count"] = int(event.svg_count)

    return {
        "event_type": event.event_type,
        "event_id": event.event_id,
        "timestamp_ms": event.timestamp_ms,
        "url": url_clean,
        "target_domain": target_domain,
        "page_title": (event.page_title or "")[:200],
        "visible_text_blocks": visible_blocks,
        "result_like_blocks": result_blocks,
        "input_snapshot": {**input_snap, **file_meta},
        "action_snapshot": action_snap,
        "sanitized": True,
        "privacy_flags": all_flags,
    }, all_flags


# ---------------------------------------------------------------------------
# Result-value extraction
# ---------------------------------------------------------------------------

def _is_result_relevant(block: str) -> bool:
    """Return True if this text block is likely to contain output/result data."""
    lower = block.lower()
    return any(kw in lower for kw in _RESULT_KEYWORDS)


def extract_result_values(result_like_blocks: list[str]) -> list[ExtractedResultValue]:
    """Extract (label, value) pairs from result-like text blocks.

    Conservative: only extracts clearly formatted numeric values.
    Does NOT invent values — if pattern doesn't match, returns empty.
    """
    results: list[ExtractedResultValue] = []
    seen_labels: set[str] = set()

    for block in (result_like_blocks or []):
        if not block.strip():
            continue

        for pat in _RESULT_VALUE_REGEXES:
            for match in pat.finditer(block):
                groups = match.groups()
                if len(groups) < 2:
                    continue
                label = groups[0].strip().lower()
                value_str = groups[1].strip()
                unit = (groups[2] or "").strip() if len(groups) > 2 else ""

                # Skip trivially short or numeric labels
                if len(label) < 2 or label.isdigit():
                    continue

                # Deduplicate
                key = f"{label}:{value_str}"
                if key in seen_labels:
                    continue
                seen_labels.add(key)

                results.append(ExtractedResultValue(
                    label=label,
                    value=value_str,
                    unit=unit,
                    raw_text=block[:120],
                    source="dom",
                ))

                if len(results) >= 20:
                    break
            if len(results) >= 20:
                break

    return results


# ---------------------------------------------------------------------------
# Observation extraction from stored events
# ---------------------------------------------------------------------------

_INPUT_KEYWORDS: tuple[str, ...] = (
    "upload", "select", "choose", "browse", "type", "enter", "input",
    "search", "origin", "destination", "query", "message", "prompt",
)

_ACTION_KEYWORDS: tuple[str, ...] = (
    "predict", "analyze", "analyse", "detect", "run", "classify",
    "submit", "search", "generate", "compute", "calculate", "process",
    "check", "scan", "start", "execute", "infer", "translate",
    "summarize", "evaluate", "test", "send", "upload", "recommend",
    "extract", "classify",
)


def _summarize_visible_blocks_for_context(
    all_visible_blocks: list[str],
    page_titles: list[str],
    target_domain: str,
) -> str | None:
    """Derive a human-readable context summary from captured DOM text blocks.

    Used when result values weren't extracted numerically but DOM text was
    captured — lets the analysis describe what kind of site/page was visited.
    """
    if not all_visible_blocks:
        return None

    # Pick up to 8 unique, meaningful blocks (>= 5 chars, not a URL, not a number)
    unique: list[str] = []
    seen: set[str] = set()
    for b in all_visible_blocks:
        b = b.strip()
        if len(b) < 5 or b.lower() in seen:
            continue
        if b.startswith("http") or b.replace(".", "").replace(",", "").isdigit():
            continue
        seen.add(b.lower())
        unique.append(b)
        if len(unique) >= 10:
            break

    if not unique:
        return None

    title_hint = f"'{page_titles[0]}' " if page_titles else ""
    domain_hint = f"({target_domain}) " if target_domain else ""
    snippet = "; ".join(unique[:5])
    return (
        f"DOM text was captured from {title_hint}{domain_hint}page. "
        f"Visible text included: {snippet}."
    )


def _detect_graphical_rendering(rows: list[dict[str, Any]]) -> tuple[bool, str | None]:
    """Detect whether the page appears to render outputs graphically (canvas/SVG).

    Returns (has_graphical_rendering, note_for_user).
    """
    max_canvas = 0
    max_svg = 0
    for row in rows:
        snap = row.get("action_snapshot") or {}
        canvas = int(snap.get("canvas_count") or 0)
        svg = int(snap.get("svg_count") or 0)
        max_canvas = max(max_canvas, canvas)
        max_svg = max(max_svg, svg)

    has_graphical = (max_canvas + max_svg) > 0
    if not has_graphical:
        return False, None

    parts: list[str] = []
    if max_canvas > 0:
        parts.append(f"{max_canvas} canvas element{'s' if max_canvas > 1 else ''}")
    if max_svg > 0:
        parts.append(f"{max_svg} SVG element{'s' if max_svg > 1 else ''}")
    note = (
        f"This page uses graphical visualization elements ({', '.join(parts)}). "
        "Exact chart, bar, or plot values may not be readable from DOM text. "
        "OCR/frame analysis would be required to extract precise visual output values."
    )
    return True, note


def _derive_observations_from_rows(rows: list[dict[str, Any]]) -> ExtractedObservations:
    """Build structured observations from stored evidence event rows."""
    observed_inputs: list[str] = []
    observed_actions: list[str] = []
    observed_outputs: list[str] = []
    all_result_blocks: list[str] = []
    all_visible_blocks: list[str] = []
    demonstrated_features: list[str] = []
    all_page_titles: list[str] = []
    all_target_domains: list[str] = []
    file_upload_count = 0
    form_submit_count = 0
    result_event_count = 0

    for row in rows:
        etype = row.get("event_type", "")
        action_snap = row.get("action_snapshot") or {}
        input_snap = row.get("input_snapshot") or {}
        result_blocks = row.get("result_like_blocks") or []
        visible_blocks = row.get("visible_text_blocks") or []
        page_title = row.get("page_title") or ""
        target_domain = row.get("target_domain") or ""

        if page_title and page_title not in all_page_titles:
            all_page_titles.append(page_title)
        if target_domain and target_domain not in all_target_domains:
            all_target_domains.append(target_domain)

        # Accumulate visible blocks for context summary
        all_visible_blocks.extend(visible_blocks)

        # ── File upload ────────────────────────────────────────────────────
        if etype == "file_upload":
            file_category = (input_snap.get("file_category") or "unknown")
            file_ext = (input_snap.get("file_extension") or "").upper()
            desc = f"File uploaded: {file_category}"
            if file_ext:
                desc += f" ({file_ext})"
            observed_inputs.append(desc)
            file_upload_count += 1

        # ── Click / action ─────────────────────────────────────────────────
        elif etype == "click":
            element_text = str(action_snap.get("element_text") or action_snap.get("text") or "").strip()
            if element_text:
                element_lower = element_text.lower()
                if any(kw in element_lower for kw in _ACTION_KEYWORDS):
                    observed_actions.append(f'Action triggered: "{element_text}"')
                elif any(kw in element_lower for kw in _INPUT_KEYWORDS):
                    observed_inputs.append(f'Input interaction: "{element_text}"')
                else:
                    observed_actions.append(f'Clicked: "{element_text}"')

        # ── Input change ───────────────────────────────────────────────────
        elif etype == "input_change":
            field_id = str(action_snap.get("element_id") or action_snap.get("id") or "").strip()
            if field_id:
                observed_inputs.append(f"Input field changed: {field_id}")
            elif input_snap:
                keys = list(input_snap.keys())[:3]
                observed_inputs.append(f"Form fields updated: {', '.join(keys)}")

        # ── Form submit ────────────────────────────────────────────────────
        elif etype == "form_submit":
            observed_actions.append("Form submitted")
            form_submit_count += 1

        # ── DOM snapshot / result detected ─────────────────────────────────
        elif etype in ("dom_snapshot", "result_detected"):
            if result_blocks:
                result_event_count += 1
                all_result_blocks.extend(result_blocks)
                preview = result_blocks[0][:80] if result_blocks else ""
                if preview:
                    suffix = "..." if len(result_blocks[0]) > 80 else ""
                    observed_outputs.append(f"Output visible: {preview}{suffix}")

        # ── Page load ──────────────────────────────────────────────────────
        elif etype == "page_load":
            if page_title:
                demonstrated_features.append(f"Page loaded: {page_title}")
            # Surface notable navigation labels from DOM text on page load
            nav_labels = [
                b for b in visible_blocks
                if 3 < len(b) <= 60 and not b.startswith("http") and not b.replace(".", "").isdigit()
            ][:4]
            for label in nav_labels:
                if label not in demonstrated_features:
                    demonstrated_features.append(label)

        # ── Recording end ──────────────────────────────────────────────────
        elif etype == "recording_end":
            if visible_blocks:
                relevant = [b for b in visible_blocks if _is_result_relevant(b)]
                all_result_blocks.extend(relevant[:5])

        # Accumulate result blocks from any event type
        if result_blocks and etype not in ("dom_snapshot", "result_detected"):
            relevant = [b for b in result_blocks if _is_result_relevant(b)]
            all_result_blocks.extend(relevant[:3])

    # Extract result values from all accumulated result-like blocks
    detected_result_values = extract_result_values(all_result_blocks[:50])

    # Build skill support reasoning from what we observed
    skill_support_reasoning: list[str] = []
    if detected_result_values:
        value_preview = ", ".join(f"{v.label}: {v.value}{v.unit}" for v in detected_result_values[:4])
        skill_support_reasoning.append(f"Output values captured from DOM: {value_preview}")
    if file_upload_count > 0:
        skill_support_reasoning.append(f"{file_upload_count} file upload(s) observed in recording")
    if form_submit_count > 0:
        skill_support_reasoning.append(f"{form_submit_count} form submission(s) observed")
    if observed_actions:
        skill_support_reasoning.append(f"Actions triggered: {', '.join(observed_actions[:3])}")

    # Detect graphical rendering (canvas/SVG)
    has_graphical_rendering, graphical_note = _detect_graphical_rendering(rows)

    # Derive page context summary from DOM text when result values weren't found
    primary_domain = all_target_domains[0] if all_target_domains else ""
    page_context_summary = _summarize_visible_blocks_for_context(
        all_visible_blocks, all_page_titles, primary_domain
    )

    # Top result snippets — safe to surface in UI (up to 5)
    top_result_snippets = list(dict.fromkeys(all_result_blocks))[:5]

    # Determine status
    has_results = bool(all_result_blocks or detected_result_values)
    has_interactions = bool(observed_inputs or observed_actions)
    has_any_blocks = bool(all_visible_blocks)

    if has_results and has_interactions:
        status: VisibleEvidenceStatus = "available"
    elif has_results or has_interactions or has_any_blocks:
        status = "partial"
    else:
        status = "not_captured" if not rows else "partial"

    return ExtractedObservations(
        observed_inputs=list(dict.fromkeys(observed_inputs))[:10],
        observed_actions=list(dict.fromkeys(observed_actions))[:10],
        observed_outputs=list(dict.fromkeys(observed_outputs))[:10],
        detected_result_values=detected_result_values,
        demonstrated_features=list(dict.fromkeys(demonstrated_features))[:8],
        skill_support_reasoning=skill_support_reasoning,
        visible_evidence_status=status,
        dom_evidence_status=status,            # explicit alias
        visual_frame_analysis_status="not_available",
        ocr_status="not_available",
        has_graphical_rendering=has_graphical_rendering,
        graphical_rendering_note=graphical_note,
        top_result_snippets=top_result_snippets,
        page_context_summary=page_context_summary,
        event_count=len(rows),
        result_event_count=result_event_count,
        file_upload_count=file_upload_count,
        form_submit_count=form_submit_count,
    )


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------

class WorkflowVisibleEvidenceService:
    def __init__(self, client: Any) -> None:
        self._client = client

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(
        self,
        user_id: str,
        session_id: str,
        request: VisibleEvidenceBatchRequest,
    ) -> dict[str, Any]:
        """Sanitize and store a batch of visible evidence events.

        Returns a summary dict with counts and status.
        """
        stored = 0
        privacy_flags_total: list[str] = []

        for event in request.events:
            try:
                row_data, flags = sanitize_event(event)
                privacy_flags_total.extend(flags)
                self._insert_event(user_id, session_id, row_data)
                stored += 1
            except Exception:
                logger.warning(
                    "VISIBLE_EVIDENCE_INGEST_EVENT_FAILED session=%s event_type=%s",
                    session_id, event.event_type, exc_info=True,
                )

        logger.info(
            "VISIBLE_EVIDENCE_INGEST_DONE session=%s stored=%d/%d",
            session_id, stored, len(request.events),
        )
        return {
            "session_id": session_id,
            "events_received": len(request.events),
            "events_stored": stored,
            "privacy_flags_raised": len(privacy_flags_total),
            "status": "accepted",
        }

    # ── Retrieve for analysis ─────────────────────────────────────────────────

    def get_extracted_observations(
        self,
        user_id: str,
        session_id: str,
    ) -> ExtractedObservations:
        """Return structured observations for workflow analysis.

        If no visible evidence exists for this session, returns an
        ExtractedObservations with status = "not_captured".
        """
        rows = self._get_rows(user_id, session_id)
        if not rows:
            return ExtractedObservations(visible_evidence_status="not_captured")
        return _derive_observations_from_rows(rows)

    # ── Summary endpoint ──────────────────────────────────────────────────────

    def get_summary(
        self,
        user_id: str,
        session_id: str,
    ) -> VisibleEvidenceSummaryResponse:
        """Build a student/debug-facing summary of all captured events.

        This is NOT surfaced to recruiters — only student + admin use.
        """
        rows = self._get_rows(user_id, session_id)
        observations = _derive_observations_from_rows(rows)

        events_summary: list[VisibleEvidenceSummaryEvent] = []
        for row in rows:
            events_summary.append(VisibleEvidenceSummaryEvent(
                event_type=row.get("event_type", ""),
                timestamp_ms=row.get("timestamp_ms"),
                page_title=row.get("page_title", ""),
                result_block_count=len(row.get("result_like_blocks") or []),
                visible_block_count=len(row.get("visible_text_blocks") or []),
                has_file_upload=row.get("event_type") == "file_upload",
                privacy_flags=list(row.get("privacy_flags") or []),
            ))

        return VisibleEvidenceSummaryResponse(
            proof_session_id=session_id,
            event_count=len(rows),
            result_event_count=observations.result_event_count,
            file_upload_count=observations.file_upload_count,
            visible_evidence_status=observations.visible_evidence_status,
            dom_evidence_status=observations.dom_evidence_status,
            visual_frame_analysis_status=observations.visual_frame_analysis_status,
            ocr_status=observations.ocr_status,
            has_graphical_rendering=observations.has_graphical_rendering,
            graphical_rendering_note=observations.graphical_rendering_note,
            top_result_snippets=observations.top_result_snippets,
            page_context_summary=observations.page_context_summary,
            events_summary=events_summary,
            extracted_observations=observations,
        )

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _insert_event(
        self, user_id: str, session_id: str, row_data: dict[str, Any]
    ) -> None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        insert: dict[str, Any] = {
            "id": str(uuid4()),
            "user_id": user_id,
            "proof_session_id": session_id,
            "created_at": now,
            **row_data,
        }

        if isinstance(self._client, dict):
            store = self._client.setdefault(_TABLE, {})
            store[insert["id"]] = insert
            return

        self._client.table(_TABLE).insert(insert).execute()

    def _get_rows(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            store = self._client.get(_TABLE, {})
            return [
                row for row in store.values()
                if str(row.get("proof_session_id")) == session_id
                and str(row.get("user_id")) == user_id
            ]

        try:
            result = (
                self._client.table(_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .eq("proof_session_id", session_id)
                .order("timestamp_ms", nullsfirst=True)
                .execute()
            )
            return getattr(result, "data", []) or []
        except Exception:
            logger.warning(
                "VISIBLE_EVIDENCE_GET_ROWS_FAILED session=%s — table may not exist",
                session_id, exc_info=True,
            )
            return []
