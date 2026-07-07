"""Website Proof detail hydration — safe rich summaries for the VBR report.

The attach-time Website Proof summary (``website_proof_summary_service``) only
carries scoring fields (``evidence_strength_score``, ``workflow_confidence``,
``supported_skills``). The deeper, recruiter-safe artifacts the Website Proof
pipeline produces — the workflow/NLP narrative, the demonstrated workflow steps,
a safe DOM summary, an OCR text summary, a visual/Qwen reasoning summary, and the
live-website reachability check — live in ``workflow_analysis_results`` and
``live_website_check_results``. This module re-reads those at report-build time
and projects ONLY safe summary fields so the report can render proof-native
Website trace cards.

Security invariants (mirrors ``website_proof_artifact_sync_service``):
  - Never returns screenshots, storage paths, signed URLs, tokens, raw DOM
    dumps, raw OCR dumps, raw provider payloads, or media paths.
  - Browser/recorder-UI noise is filtered out of OCR / DOM / visual summaries.
  - Ownership is always scoped to ``user_id``.
  - Any lookup problem returns ``None`` (honest fallback to the scoring-only
    Website card).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.services.website_proof_artifact_sync_service import (
    _extract_domain,
    _is_recorder_ui_text,
    _sanitize_text_segments,
    _truncate,
)

logger = logging.getLogger(__name__)

_WF_TABLE = "workflow_analysis_results"
_LIVE_TABLE = "live_website_check_results"


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _safe_steps(observed: dict[str, Any], demonstrated_actions: Any, domain: str) -> list[str]:
    """Safe, deduped workflow step labels (noise-filtered, bounded)."""
    raw: list[str] = []
    steps = observed.get("steps") if isinstance(observed, dict) else None
    for s in steps or []:
        if isinstance(s, str):
            raw.append(s)
        elif isinstance(s, dict):
            label = s.get("label") or s.get("action") or s.get("description") or ""
            if label:
                raw.append(str(label))
    if not raw and isinstance(demonstrated_actions, list):
        raw = [str(s) for s in demonstrated_actions if isinstance(s, (str, int, float))]

    out: list[str] = []
    seen: set[str] = set()
    for label in raw:
        clean, quality = _sanitize_text_segments(label, domain)
        clean = _truncate(clean, 160).strip()
        key = clean.lower()
        if clean and quality != "noisy" and key not in seen:
            seen.add(key)
            out.append(clean)
        if len(out) >= 8:
            break
    return out


def _safe_ocr_summary(wf: dict[str, Any], domain: str) -> str | None:
    ocr = _coerce_dict(wf.get("frame_ocr_evidence_summary"))
    if not ocr.get("has_ocr_evidence"):
        return None
    snippets = ocr.get("top_ocr_snippets") or []
    joined = "; ".join(str(s)[:100] for s in snippets[:3])
    clean, quality = _sanitize_text_segments(joined, domain)
    clean = _truncate(clean, 320).strip()
    if not clean or quality == "noisy":
        # Honest signal that OCR ran but produced no clean target-app text.
        labels = [str(x) for x in (ocr.get("matched_ui_labels") or [])][:6]
        if labels:
            return _truncate("Text detected on screen: " + ", ".join(labels), 320)
        return None
    return clean


_DOMAIN_TOKEN_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9-]+)+")


def _context_is_on_target(text: str, target_domain: str) -> bool:
    """True when ``text`` does not clearly describe a *different* site.

    The ``page_context_summary`` fallback can capture an off-target page the
    student briefly visited mid-recording (e.g. a Google Docs tab). Surfacing
    that as the target's DOM summary is misleading and leaks unrelated browsing,
    so we drop it when it names a domain that is not the proof target. When no
    competing domain is mentioned we trust it.
    """
    if not target_domain:
        return True
    lower = text.lower()
    domains = set(_DOMAIN_TOKEN_RE.findall(lower))
    if not domains:
        return True
    td = target_domain.lower()
    return any(d in td or td in d for d in domains)


def _safe_dom_summary(wf: dict[str, Any], domain: str) -> str | None:
    observed = _coerce_dict(wf.get("observed_demonstration"))
    raw = str(observed.get("dom_summary") or "") if observed else ""
    clean, quality = _sanitize_text_segments(raw, domain)
    clean = _truncate(clean, 320).strip()
    if clean and quality != "noisy":
        return clean
    page_ctx = _truncate(str(wf.get("page_context_summary") or ""), 320).strip()
    if page_ctx and _context_is_on_target(page_ctx, domain):
        return page_ctx
    return None


def _safe_visual_summary(wf: dict[str, Any], domain: str) -> str | None:
    vrs = _coerce_dict(wf.get("visual_reasoning_summary"))
    if vrs.get("status") == "analyzed":
        summary = _truncate(str(vrs.get("summary") or ""), 320).strip()
        if summary and not _is_recorder_ui_text(summary):
            return summary
        if summary and _is_recorder_ui_text(summary):
            segs = [s.strip() for s in summary.replace(" | ", ";").replace("\n", ";").split(";") if s.strip()]
            clean = "; ".join(s for s in segs if not _is_recorder_ui_text(s))
            return _truncate(clean, 320).strip() or None
    # Fall back to the plain visual_summary text column when present + clean.
    plain = _truncate(str(wf.get("visual_summary") or ""), 320).strip()
    if plain and not _is_recorder_ui_text(plain):
        return plain
    return None


# Closed OCR page-context enum values that are safe to surface as a page-context
# signal for the read-time purpose classifier (the raw enum, no free text).
_ALLOWED_PAGE_CONTEXTS = frozenset(
    {
        "homepage_marketing",
        "training_ui",
        "prediction_output",
        "demo_content",
        "unknown",
        "filtered_non_target_frame",
    }
)


def _safe_page_context(wf: dict[str, Any]) -> str | None:
    """The pipeline's own closed OCR page-context classification (safe enum only)."""
    ocr = _coerce_dict(wf.get("frame_ocr_evidence_summary"))
    ctx = str(ocr.get("detected_page_context") or "").strip().lower()
    return ctx if ctx in _ALLOWED_PAGE_CONTEXTS else None


def _safe_extra_signals(wf: dict[str, Any], domain: str) -> list[str]:
    """Additional already-safe signal phrases for the purpose classifier.

    Surfaces two richer-but-safe workflow-analysis fields that the fixed
    ``ocr_summary`` / ``visual_summary`` projections do not: the OCR stage's
    ``observed_summary`` narrative and the visual-reasoning ``supported_signals``.
    Both are noise-filtered/sanitized here so only clean, target-app text reaches
    the classifier — never raw OCR/provider payloads. Bounded and deduped.
    """
    out: list[str] = []
    seen: set[str] = set()

    def _add(raw: Any) -> None:
        text = str(raw or "").strip()
        if not text:
            return
        clean, quality = _sanitize_text_segments(text, domain)
        clean = _truncate(clean, 200).strip()
        key = clean.lower()
        if clean and quality != "noisy" and key not in seen:
            seen.add(key)
            out.append(clean)

    ocr = _coerce_dict(wf.get("frame_ocr_evidence_summary"))
    if ocr.get("has_ocr_evidence"):
        _add(ocr.get("observed_summary"))

    vrs = _coerce_dict(wf.get("visual_reasoning_summary"))
    if vrs.get("status") == "analyzed":
        for sig in (vrs.get("supported_signals") or [])[:8]:
            _add(sig)

    return out[:10]


def _live_check(db: Any, user_id: str, proof_session_id: str) -> dict[str, Any] | None:
    row: dict[str, Any] | None = None
    try:
        if isinstance(db, dict):
            for r in db.get(_LIVE_TABLE, {}).values():
                if str(r.get("user_id")) == user_id and str(r.get("proof_session_id")) == proof_session_id:
                    row = r
                    break
        else:
            resp = (
                db.table(_LIVE_TABLE)
                .select("final_url,page_title,is_reachable,confidence,recruiter_summary")
                .eq("user_id", user_id)
                .eq("proof_session_id", proof_session_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = getattr(resp, "data", []) or []
            row = rows[0] if rows else None
    except Exception:  # pragma: no cover - live check is best-effort
        return None
    if not isinstance(row, dict):
        return None
    from app.services.safe_public_url import is_safe_public_url

    final_url = str(row.get("final_url") or "").strip()
    return {
        "is_reachable": bool(row.get("is_reachable")),
        "confidence": str(row.get("confidence") or "failed"),
        "page_title": _truncate(str(row.get("page_title") or ""), 160).strip() or None,
        "final_url": final_url if is_safe_public_url(final_url) else None,
        "summary": _truncate(str(row.get("recruiter_summary") or ""), 320).strip() or None,
    }


def _load_workflow(db: Any, user_id: str, proof_session_id: str) -> dict[str, Any] | None:
    try:
        if isinstance(db, dict):
            for r in db.get(_WF_TABLE, {}).values():
                if str(r.get("user_id")) == user_id and str(r.get("proof_session_id")) == proof_session_id:
                    return r
            return None
        resp = (
            db.table(_WF_TABLE)
            .select(
                "target_website,workflow_summary,recruiter_summary,demonstrated_actions,"
                "observed_demonstration,page_context_summary,dom_evidence_status,"
                "visible_evidence_status,frame_ocr_evidence_summary,visual_reasoning_summary,"
                "visual_summary,visual_analysis_status,visual_analysis_provider,created_at"
            )
            .eq("user_id", user_id)
            .eq("proof_session_id", proof_session_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", []) or []
        return rows[0] if rows else None
    except Exception:  # pragma: no cover - detail is best-effort
        return None


def get_website_proof_detail(db: Any, user_id: str, proof_session_id: str) -> dict[str, Any] | None:
    """Return safe rich Website Proof summaries for one session, or ``None``.

    Shape::

        {
          "workflow_summary": str | None,   # NLP / workflow narrative
          "workflow_steps": [str],          # demonstrated workflow steps
          "dom_summary": str | None,        # safe DOM summary
          "ocr_summary": str | None,        # safe OCR text summary
          "visual_summary": str | None,     # safe visual / Qwen reasoning
          "live_check": {...} | None,       # live reachability check
          "observed_at": str | None,        # date-only (YYYY-MM-DD) capture date
        }

    Returns ``None`` when no workflow analysis row exists for the session.
    """
    if not proof_session_id:
        return None
    wf = _load_workflow(db, user_id, str(proof_session_id))
    live = _live_check(db, user_id, str(proof_session_id))
    if wf is None and live is None:
        return None
    wf = wf or {}
    domain = _extract_domain(str(wf.get("target_website") or ""))

    workflow_summary = _truncate(
        str(wf.get("workflow_summary") or wf.get("recruiter_summary") or ""), 320
    ).strip() or None

    # Date precision only — a full timestamp is provenance metadata the report
    # does not need.
    observed_at = str(wf.get("created_at") or "").strip()[:10] or None

    return {
        "workflow_summary": workflow_summary,
        "observed_at": observed_at,
        "workflow_steps": _safe_steps(
            _coerce_dict(wf.get("observed_demonstration")),
            wf.get("demonstrated_actions"),
            domain,
        ),
        "dom_summary": _safe_dom_summary(wf, domain) if wf else None,
        "ocr_summary": _safe_ocr_summary(wf, domain) if wf else None,
        "visual_summary": _safe_visual_summary(wf, domain) if wf else None,
        # The pipeline's own closed OCR page-context classification + additional
        # already-safe signal phrases (OCR observed-summary, visual supported
        # signals). Feed the read-time purpose classifier so a genuinely strong
        # prediction/training/API/data capture maps precisely even when the fixed
        # summary projections above were too noisy to surface it.
        "page_context": _safe_page_context(wf) if wf else None,
        "extra_signals": _safe_extra_signals(wf, domain) if wf else [],
        "live_check": live,
    }
