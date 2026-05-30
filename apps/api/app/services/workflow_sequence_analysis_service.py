"""Workflow Sequence Analysis Service — Week 3.

Analyses extracted video keyframes as a temporal sequence, merging them with
DOM events, visible evidence, and browser events to produce a structured
input → action → output workflow proof.

Architecture
------------
  Inputs (all optional — degrades gracefully):
    keyframe_result     VideoKeyframeResult | None   (Week 2 keyframe extractor)
    dom_events          list[dict]                   (browser extension events)
    visible_observations ExtractedObservations | None (v4 DOM visible evidence)
    visual_frame_obs    dict | None                  (v5 visual frame analysis)

  Evidence priority (highest → lowest):
    1. DOM exact result values (dom_snapshot)
    2. Visible text observations  (dom_snapshot)
    3. OCR / visual model output  (visual_frame_obs)
    4. Browser events             (page_visit, click, input_change)
    5. Keyframe timestamps        (temporal ordering only)

Privacy guarantees
------------------
  • Raw frame paths, storage URLs, access tokens, private debug metadata are
    NEVER included in public-safe or recruiter-safe output fields.
  • to_public_dict() is the safe serialisation path; callers must use it for
    any API response.
  • private_review_flags is internal-only and must not be sent to the client.

Outputs
-------
  SequenceAnalysisResult  dataclass with to_public_dict() / to_private_dict()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Stage labels ───────────────────────────────────────────────────────────────

STAGE_INITIAL_STATE          = "initial_state"
STAGE_INPUT_OR_SETUP         = "input_or_setup"
STAGE_USER_ACTION            = "user_action"
STAGE_PROCESSING_TRANSITION  = "processing_or_transition"
STAGE_OUTPUT_OR_RESULT       = "output_or_result"
STAGE_FINAL_STATE            = "final_state"

_ALL_STAGES = (
    STAGE_INITIAL_STATE,
    STAGE_INPUT_OR_SETUP,
    STAGE_USER_ACTION,
    STAGE_PROCESSING_TRANSITION,
    STAGE_OUTPUT_OR_RESULT,
    STAGE_FINAL_STATE,
)

# ── Status values ──────────────────────────────────────────────────────────────

SEQ_STATUS_ANALYZED      = "analyzed"
SEQ_STATUS_NOT_AVAILABLE = "not_available"
SEQ_STATUS_FAILED        = "failed"

# Evidence strength tiers
STRENGTH_STRONG      = "strong"
STRENGTH_MODERATE    = "moderate"
STRENGTH_WEAK        = "weak"
STRENGTH_INSUFFICIENT = "insufficient"

# ── Event type matchers (generic — no app/domain hardcoding) ──────────────────

_INPUT_EVENT_TYPES    = frozenset({"input_change", "file_upload"})
_ACTION_EVENT_TYPES   = frozenset({"click"})
_NAVIGATE_EVENT_TYPES = frozenset({"page_visit", "navigation"})

_ACTION_TRIGGER_WORDS = frozenset({
    "predict", "analyze", "analyse", "detect", "run", "classify",
    "submit", "search", "generate", "compute", "calculate", "process",
    "check", "scan", "start", "execute", "infer", "translate",
    "summarize", "evaluate", "test", "upload", "send", "apply",
})

_OUTPUT_PAGE_WORDS = frozenset({
    "result", "output", "prediction", "detection", "classification",
    "response", "answer", "report", "analysis", "evaluation",
    "score", "summary", "insights",
})

# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class SequenceAnalysisResult:
    """Full sequence analysis output.

    Public fields are safe for API / recruiter responses.
    private_review_flags must NOT be sent to clients.
    """
    sequence_analysis_status: str
    analyzed_frame_count: int
    workflow_stage_summaries: list[dict[str, Any]]
    input_action_output_chain: dict[str, Any]
    before_after_changes: list[str]
    observed_outputs: list[str]
    supported_skills: list[str]
    unsupported_claims: list[str]
    evidence_strength: str
    confidence_score: int
    public_safe_summary: str
    recruiter_safe_summary: str
    limitations: list[str]

    # Internal only — never serialised publicly
    private_review_flags: list[str] = field(default_factory=list, repr=False)

    def to_public_dict(self) -> dict[str, Any]:
        """Recruiter / public-safe serialisation.

        Guarantees: no frame paths, no private URLs, no raw DOM,
        no tokens, no private_review_flags.
        """
        return {
            "sequence_analysis_status":  self.sequence_analysis_status,
            "analyzed_frame_count":      self.analyzed_frame_count,
            "workflow_stage_summaries":  self.workflow_stage_summaries,
            "input_action_output_chain": self.input_action_output_chain,
            "before_after_changes":      self.before_after_changes,
            "observed_outputs":          self.observed_outputs,
            "supported_skills":          self.supported_skills,
            "unsupported_claims":        self.unsupported_claims,
            "evidence_strength":         self.evidence_strength,
            "confidence_score":          self.confidence_score,
            "public_safe_summary":       self.public_safe_summary,
            "recruiter_safe_summary":    self.recruiter_safe_summary,
            "limitations":               self.limitations,
        }

    def to_private_dict(self) -> dict[str, Any]:
        """Internal-only view — includes review flags. Never send to client."""
        return {
            **self.to_public_dict(),
            "private_review_flags": self.private_review_flags,
        }


# ── Service ────────────────────────────────────────────────────────────────────

class WorkflowSequenceAnalysisService:
    """Analyse a session's keyframes + events as a temporal sequence.

    Usage:
        svc = WorkflowSequenceAnalysisService()
        result = svc.analyze(
            keyframe_result=kf_result,
            dom_events=proof_data.get("workflow_events", []),
            visible_observations=obs,      # ExtractedObservations or None
            visual_frame_obs=vf_obs,       # dict or None
        )
        public_output = result.to_public_dict()
    """

    def analyze(
        self,
        *,
        keyframe_result: Any | None = None,
        dom_events: list[dict[str, Any]] | None = None,
        visible_observations: Any | None = None,
        visual_frame_obs: dict[str, Any] | None = None,
    ) -> SequenceAnalysisResult:
        """Run sequence analysis.  Never raises — returns not_available on error."""
        try:
            return self._analyze(
                keyframe_result=keyframe_result,
                dom_events=dom_events or [],
                visible_observations=visible_observations,
                visual_frame_obs=visual_frame_obs,
            )
        except Exception as exc:
            logger.warning("[SequenceAnalysis] unexpected error: %s", exc, exc_info=True)
            return SequenceAnalysisResult(
                sequence_analysis_status=SEQ_STATUS_FAILED,
                analyzed_frame_count=0,
                workflow_stage_summaries=[],
                input_action_output_chain={},
                before_after_changes=[],
                observed_outputs=[],
                supported_skills=[],
                unsupported_claims=[],
                evidence_strength=STRENGTH_INSUFFICIENT,
                confidence_score=0,
                public_safe_summary="Sequence analysis encountered an error.",
                recruiter_safe_summary="Sequence analysis could not be completed.",
                limitations=["Internal error during sequence analysis."],
                private_review_flags=[f"exception: {str(exc)[:200]}"],
            )

    # ── Internal ───────────────────────────────────────────────────────────────

    def _analyze(
        self,
        *,
        keyframe_result: Any | None,
        dom_events: list[dict[str, Any]],
        visible_observations: Any | None,
        visual_frame_obs: dict[str, Any] | None,
    ) -> SequenceAnalysisResult:

        # ── 1. Check keyframe availability ────────────────────────────────────
        has_keyframes = _has_valid_keyframes(keyframe_result)
        frame_timestamps: list[int] = (
            list(keyframe_result.selected_frame_timestamps_ms)
            if has_keyframes else []
        )
        frame_count = len(frame_timestamps)

        # ── 2. Gather evidence from all sources ───────────────────────────────
        vis_inputs:  list[str] = _get_list(visible_observations, "observed_inputs")
        vis_actions: list[str] = _get_list(visible_observations, "observed_actions")
        vis_outputs: list[str] = _get_list(visible_observations, "observed_outputs")
        vis_result_values: list[Any] = _get_list(visible_observations, "detected_result_values")
        vis_ev_status: str = _get_str(visible_observations, "visible_evidence_status", "not_captured")

        ocr_result_values: list[dict] = []
        visual_summary: str = ""
        vf_status: str = "not_configured"
        if visual_frame_obs:
            ocr_result_values = visual_frame_obs.get("extracted_result_values") or []
            visual_summary    = visual_frame_obs.get("visual_summary") or ""
            vf_status         = visual_frame_obs.get("visual_frame_analysis_status", "not_configured")

        has_dom_evidence    = vis_ev_status in ("available", "partial")
        has_result_values   = bool(vis_result_values)
        has_ocr_values      = bool(ocr_result_values)
        has_visual_summary  = bool(visual_summary.strip())
        has_events          = bool(dom_events)

        # Not available when no frames AND no DOM evidence AND no events
        if not has_keyframes and not has_dom_evidence and not has_events:
            return SequenceAnalysisResult(
                sequence_analysis_status=SEQ_STATUS_NOT_AVAILABLE,
                analyzed_frame_count=0,
                workflow_stage_summaries=[],
                input_action_output_chain={},
                before_after_changes=[],
                observed_outputs=[],
                supported_skills=[],
                unsupported_claims=[],
                evidence_strength=STRENGTH_INSUFFICIENT,
                confidence_score=0,
                public_safe_summary="No keyframes or evidence available for sequence analysis.",
                recruiter_safe_summary="Sequence analysis is not available for this recording.",
                limitations=[
                    "No video keyframes were extracted and no DOM events were captured. "
                    "Record a new workflow demonstration to enable sequence analysis."
                ],
            )

        # ── 3. Build temporal event map ───────────────────────────────────────
        duration_ms = _get_duration_ms(keyframe_result, dom_events)
        event_map   = _build_event_map(dom_events)

        # ── 4. Classify keyframes into stages (or fallback to event-only) ─────
        stage_frame_map = _assign_frames_to_stages(frame_timestamps, event_map, duration_ms)

        # ── 5. Build stage summaries ──────────────────────────────────────────
        stage_summaries = _build_stage_summaries(
            stage_frame_map, event_map, vis_inputs, vis_actions, vis_outputs,
        )

        # ── 6. Detect IAO chain ───────────────────────────────────────────────
        iao_chain = _detect_iao_chain(
            event_map=event_map,
            vis_inputs=vis_inputs,
            vis_actions=vis_actions,
            vis_outputs=vis_outputs,
            vis_result_values=vis_result_values,
            ocr_result_values=ocr_result_values,
            visual_summary=visual_summary,
            has_keyframes=has_keyframes,
        )

        # ── 7. Before/after changes ───────────────────────────────────────────
        before_after = _detect_before_after(
            stage_frame_map, event_map, vis_inputs, vis_outputs,
        )

        # ── 8. Observed outputs ───────────────────────────────────────────────
        observed_outputs = _collect_observed_outputs(
            vis_outputs, vis_result_values, ocr_result_values, visual_summary, event_map,
        )

        # ── 9. Skill signals ──────────────────────────────────────────────────
        supported_skills, unsupported_claims = _derive_skill_signals(
            iao_chain=iao_chain,
            has_dom_evidence=has_dom_evidence,
            has_result_values=has_result_values,
            has_ocr_values=has_ocr_values,
        )

        # ── 10. Evidence strength + confidence ────────────────────────────────
        evidence_strength, confidence_score = _compute_evidence_strength(
            has_keyframes=has_keyframes,
            has_dom_evidence=has_dom_evidence,
            has_result_values=has_result_values,
            has_ocr_values=has_ocr_values,
            has_visual_summary=has_visual_summary,
            has_events=has_events,
            iao_chain=iao_chain,
            frame_count=frame_count,
        )

        # ── 11. Limitations ───────────────────────────────────────────────────
        limitations = _build_limitations(
            has_keyframes=has_keyframes,
            has_dom_evidence=has_dom_evidence,
            has_result_values=has_result_values,
            vf_status=vf_status,
            iao_chain=iao_chain,
        )

        # ── 12. Private flags ─────────────────────────────────────────────────
        private_flags = _build_private_flags(
            has_keyframes=has_keyframes,
            has_dom_evidence=has_dom_evidence,
            evidence_strength=evidence_strength,
            iao_chain=iao_chain,
        )

        # ── 13. Summaries ─────────────────────────────────────────────────────
        public_summary, recruiter_summary = _build_summaries(
            iao_chain=iao_chain,
            stage_summaries=stage_summaries,
            observed_outputs=observed_outputs,
            evidence_strength=evidence_strength,
            confidence_score=confidence_score,
            has_keyframes=has_keyframes,
            frame_count=frame_count,
        )

        return SequenceAnalysisResult(
            sequence_analysis_status=SEQ_STATUS_ANALYZED,
            analyzed_frame_count=frame_count,
            workflow_stage_summaries=stage_summaries,
            input_action_output_chain=iao_chain,
            before_after_changes=before_after,
            observed_outputs=observed_outputs,
            supported_skills=supported_skills,
            unsupported_claims=unsupported_claims,
            evidence_strength=evidence_strength,
            confidence_score=confidence_score,
            public_safe_summary=public_summary,
            recruiter_safe_summary=recruiter_summary,
            limitations=limitations,
            private_review_flags=private_flags,
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_attr(obj: Any, attr: str, default: Any) -> Any:
    if obj is None:
        return default
    return list(getattr(obj, attr, None) or default)


def _get_list(obj: Any, attr: str) -> list:
    if obj is None:
        return []
    val = getattr(obj, attr, None)
    if not val:
        return []
    return list(val)


def _get_str(obj: Any, attr: str, default: str = "") -> str:
    if obj is None:
        return default
    val = getattr(obj, attr, None)
    if val is None:
        return default
    return str(val)


def _has_valid_keyframes(kf: Any) -> bool:
    if kf is None:
        return False
    status = getattr(kf, "video_analysis_status", "") or ""
    timestamps = getattr(kf, "selected_frame_timestamps_ms", []) or []
    return status == "analyzed" and len(timestamps) > 0


def _get_duration_ms(kf: Any, events: list[dict]) -> int:
    """Estimate timeline duration (ms) from keyframe result or events."""
    if kf is not None:
        dur = getattr(kf, "duration_ms", None)
        if dur and dur > 0:
            return int(dur)

    # Fall back to event timestamps
    timestamps = []
    for e in events:
        if not isinstance(e, dict):
            continue
        ts = e.get("timestamp_ms") or e.get("timestamp")
        if ts and isinstance(ts, (int, float)) and ts > 0:
            timestamps.append(int(ts))
    if timestamps:
        return max(timestamps)
    return 60_000   # 60s default


class _EventMap:
    """Lightweight index of dom_events by category."""

    def __init__(
        self,
        input_events: list[dict],
        action_events: list[dict],
        nav_events: list[dict],
        all_events: list[dict],
    ) -> None:
        self.input_events  = input_events
        self.action_events = action_events
        self.nav_events    = nav_events
        self.all_events    = all_events

    # Timestamp (ms) of first action trigger, or None
    @property
    def first_action_ms(self) -> int | None:
        for e in self.action_events:
            ts = _ts(e)
            if ts is not None:
                return ts
        return None

    # Timestamp (ms) of first output page visit, or None
    @property
    def first_output_ms(self) -> int | None:
        for e in self.nav_events:
            title = (e.get("page_title") or "").lower()
            url   = (e.get("page_url") or "").lower()
            if any(w in title or w in url for w in _OUTPUT_PAGE_WORDS):
                ts = _ts(e)
                if ts is not None:
                    return ts
        return None


def _ts(event: dict | None) -> int | None:
    if not isinstance(event, dict):
        return None
    val = event.get("timestamp_ms") or event.get("timestamp")
    if val and isinstance(val, (int, float)) and val > 0:
        return int(val)
    return None


def _build_event_map(events: list[dict]) -> _EventMap:
    input_events:  list[dict] = []
    action_events: list[dict] = []
    nav_events:    list[dict] = []

    for e in events:
        if not isinstance(e, dict):
            continue
        etype = (e.get("type") or "").lower()
        etext = (e.get("element_text") or "").lower()

        if etype in _INPUT_EVENT_TYPES:
            input_events.append(e)
        elif etype in _ACTION_EVENT_TYPES:
            if any(w in etext for w in _ACTION_TRIGGER_WORDS):
                action_events.append(e)
        elif etype in _NAVIGATE_EVENT_TYPES:
            nav_events.append(e)

    return _EventMap(input_events, action_events, nav_events, events)


def _assign_frames_to_stages(
    timestamps_ms: list[int],
    event_map: _EventMap,
    duration_ms: int,
) -> dict[str, list[int]]:
    """Map each frame timestamp to a workflow stage.

    If key DOM events carry timestamps, use them as stage boundaries.
    Otherwise, divide the timeline proportionally.
    """
    if not timestamps_ms:
        return {s: [] for s in _ALL_STAGES}

    result: dict[str, list[int]] = {s: [] for s in _ALL_STAGES}

    # Try event-driven boundaries
    action_ms = event_map.first_action_ms
    output_ms = event_map.first_output_ms
    total     = duration_ms or max(timestamps_ms)

    if action_ms and output_ms and action_ms < output_ms:
        # Use action + output as pivot points
        setup_end     = action_ms
        action_end    = action_ms + max(1000, (output_ms - action_ms) // 4)
        proc_end      = output_ms
        result_end    = output_ms + max(5000, (total - output_ms) * 3 // 4)
        final_start   = result_end

        for ts in timestamps_ms:
            if ts <= int(total * 0.08):
                result[STAGE_INITIAL_STATE].append(ts)
            elif ts <= setup_end:
                result[STAGE_INPUT_OR_SETUP].append(ts)
            elif ts <= action_end:
                result[STAGE_USER_ACTION].append(ts)
            elif ts <= proc_end:
                result[STAGE_PROCESSING_TRANSITION].append(ts)
            elif ts <= result_end:
                result[STAGE_OUTPUT_OR_RESULT].append(ts)
            else:
                result[STAGE_FINAL_STATE].append(ts)
    elif action_ms:
        # Only action pivot available
        for ts in timestamps_ms:
            if ts <= int(total * 0.1):
                result[STAGE_INITIAL_STATE].append(ts)
            elif ts < action_ms:
                result[STAGE_INPUT_OR_SETUP].append(ts)
            elif ts <= action_ms + max(2000, total // 10):
                result[STAGE_USER_ACTION].append(ts)
            elif ts <= action_ms + total // 3:
                result[STAGE_PROCESSING_TRANSITION].append(ts)
            elif ts <= total * 0.9:
                result[STAGE_OUTPUT_OR_RESULT].append(ts)
            else:
                result[STAGE_FINAL_STATE].append(ts)
    else:
        # Proportional split: 0-8% / 8-30% / 30-50% / 50-70% / 70-90% / 90-100%
        thresholds = (0.08, 0.30, 0.50, 0.70, 0.90)
        for ts in timestamps_ms:
            ratio = ts / total if total > 0 else 0
            if ratio <= thresholds[0]:
                result[STAGE_INITIAL_STATE].append(ts)
            elif ratio <= thresholds[1]:
                result[STAGE_INPUT_OR_SETUP].append(ts)
            elif ratio <= thresholds[2]:
                result[STAGE_USER_ACTION].append(ts)
            elif ratio <= thresholds[3]:
                result[STAGE_PROCESSING_TRANSITION].append(ts)
            elif ratio <= thresholds[4]:
                result[STAGE_OUTPUT_OR_RESULT].append(ts)
            else:
                result[STAGE_FINAL_STATE].append(ts)

    return result


def _build_stage_summaries(
    stage_frame_map: dict[str, list[int]],
    event_map: _EventMap,
    vis_inputs: list[str],
    vis_actions: list[str],
    vis_outputs: list[str],
) -> list[dict[str, Any]]:
    """Produce a summary dict for each stage."""
    stage_labels = {
        STAGE_INITIAL_STATE:         "Initial state",
        STAGE_INPUT_OR_SETUP:        "Input / setup",
        STAGE_USER_ACTION:           "User action",
        STAGE_PROCESSING_TRANSITION: "Processing / transition",
        STAGE_OUTPUT_OR_RESULT:      "Output / result",
        STAGE_FINAL_STATE:           "Final state",
    }

    stage_dom_hints: dict[str, list[str]] = {
        STAGE_INITIAL_STATE:         [],
        STAGE_INPUT_OR_SETUP:        vis_inputs[:2],
        STAGE_USER_ACTION:           vis_actions[:2],
        STAGE_PROCESSING_TRANSITION: [],
        STAGE_OUTPUT_OR_RESULT:      vis_outputs[:3],
        STAGE_FINAL_STATE:           vis_outputs[-1:] if vis_outputs else [],
    }

    summaries: list[dict[str, Any]] = []
    for stage in _ALL_STAGES:
        frame_ts = stage_frame_map.get(stage) or []
        dom_hints = stage_dom_hints.get(stage) or []

        # Evidence description — prefer DOM hints, fall back to generic
        if dom_hints:
            evidence_desc = "; ".join(dom_hints[:2])
        elif frame_ts:
            evidence_desc = f"{len(frame_ts)} keyframe(s) in this stage"
        else:
            evidence_desc = "No keyframes captured for this stage"

        summaries.append({
            "stage":       stage,
            "label":       stage_labels[stage],
            "frame_count": len(frame_ts),
            "has_evidence": bool(frame_ts or dom_hints),
            "evidence_description": evidence_desc,
        })

    return summaries


def _detect_iao_chain(
    *,
    event_map: _EventMap,
    vis_inputs: list[str],
    vis_actions: list[str],
    vis_outputs: list[str],
    vis_result_values: list[Any],
    ocr_result_values: list[dict],
    visual_summary: str,
    has_keyframes: bool,
) -> dict[str, Any]:
    """Detect the input → action → output chain.

    Evidence priority:
      1. DOM visible observations (vis_inputs/outputs/result_values)
      2. OCR result values
      3. Visual summary
      4. Browser events
    """
    detected_input:  str | None = None
    detected_action: str | None = None
    detected_output: str | None = None
    output_values:   list[str]  = []
    chain_source:    str        = "none"

    # Input: DOM first, then events
    if vis_inputs:
        detected_input = vis_inputs[0]
        chain_source = "dom_snapshot"
    elif event_map.input_events:
        e = event_map.input_events[0]
        detected_input = e.get("element_text") or e.get("element_id") or "form input"
        chain_source = "browser_event"

    # Action: DOM first, then events
    if vis_actions:
        detected_action = vis_actions[0]
    elif event_map.action_events:
        e = event_map.action_events[0]
        detected_action = e.get("element_text") or "action triggered"
        if chain_source == "none":
            chain_source = "browser_event"

    # Output: DOM result values > DOM outputs > OCR > visual > nav events
    if vis_result_values:
        # Convert to simple strings (label: value)
        for rv in vis_result_values[:3]:
            label = getattr(rv, "label", "") or (rv.get("label") if isinstance(rv, dict) else "")
            value = getattr(rv, "value", "") or (rv.get("value") if isinstance(rv, dict) else "")
            if label and value:
                output_values.append(f"{label}: {value}")
            elif label:
                output_values.append(label)
        detected_output = output_values[0] if output_values else "result displayed"
        chain_source = "dom_snapshot"
    elif vis_outputs:
        detected_output = vis_outputs[0]
        output_values   = vis_outputs[:3]
        chain_source = chain_source or "dom_snapshot"
    elif ocr_result_values:
        for rv in ocr_result_values[:3]:
            label = rv.get("label", "")
            value = rv.get("value", "")
            if label and value:
                output_values.append(f"{label}: {value}")
        detected_output = output_values[0] if output_values else "result (from OCR)"
        chain_source = chain_source or "visual_frame_ocr"
    elif visual_summary:
        detected_output = visual_summary[:200].strip()
        chain_source = chain_source or "visual_frame_model"
    elif event_map.nav_events:
        for e in event_map.nav_events:
            title = (e.get("page_title") or "").lower()
            url   = (e.get("page_url") or "").lower()
            if any(w in title or w in url for w in _OUTPUT_PAGE_WORDS):
                detected_output = e.get("page_title") or "result page"
                chain_source = chain_source or "browser_event"
                break

    is_complete = bool(detected_input and detected_action and detected_output)

    return {
        "detected_input":   detected_input,
        "detected_action":  detected_action,
        "detected_output":  detected_output,
        "output_values":    output_values,
        "chain_complete":   is_complete,
        "chain_source":     chain_source,
        "has_keyframes":    has_keyframes,
    }


def _detect_before_after(
    stage_frame_map: dict[str, list[int]],
    event_map: _EventMap,
    vis_inputs: list[str],
    vis_outputs: list[str],
) -> list[str]:
    """Describe observable before/after changes."""
    changes: list[str] = []

    has_initial = bool(stage_frame_map.get(STAGE_INITIAL_STATE))
    has_result  = bool(
        stage_frame_map.get(STAGE_OUTPUT_OR_RESULT)
        or stage_frame_map.get(STAGE_FINAL_STATE)
    )

    if has_initial and has_result:
        changes.append("Application state changed between initial and output frames.")

    if vis_inputs and vis_outputs:
        changes.append(
            f"Input was provided ({vis_inputs[0][:80]}) and "
            f"output was observed ({vis_outputs[0][:80]})."
        )
    elif vis_inputs:
        changes.append(f"Input was provided: {vis_inputs[0][:80]}.")
    elif vis_outputs:
        changes.append(f"Output was observed: {vis_outputs[0][:80]}.")

    if event_map.action_events and (vis_outputs or event_map.first_output_ms):
        changes.append("User triggered an action and a result state was reached.")

    return changes


def _collect_observed_outputs(
    vis_outputs: list[str],
    vis_result_values: list[Any],
    ocr_result_values: list[dict],
    visual_summary: str,
    event_map: _EventMap,
) -> list[str]:
    outputs: list[str] = []

    # DOM result values — highest priority
    for rv in vis_result_values[:5]:
        label = getattr(rv, "label", "") or (rv.get("label") if isinstance(rv, dict) else "")
        value = getattr(rv, "value", "") or (rv.get("value") if isinstance(rv, dict) else "")
        if label and value:
            outputs.append(f"{label}: {value}")
        elif label:
            outputs.append(label)

    # DOM visible text outputs
    for o in vis_outputs[:3]:
        if o not in outputs:
            outputs.append(o)

    # OCR values (if no DOM values)
    if not outputs:
        for rv in ocr_result_values[:3]:
            label = rv.get("label", "")
            value = rv.get("value", "")
            if label and value:
                outputs.append(f"{label}: {value}")

    # Visual summary (if nothing else)
    if not outputs and visual_summary:
        outputs.append(visual_summary[:200].strip())

    # Event-derived output page titles (last resort)
    if not outputs:
        for e in event_map.nav_events:
            title = e.get("page_title") or ""
            url   = (e.get("page_url") or "").lower()
            title_l = title.lower()
            if any(w in title_l or w in url for w in _OUTPUT_PAGE_WORDS):
                outputs.append(title or "result page")
                break

    return outputs


def _derive_skill_signals(
    *,
    iao_chain: dict[str, Any],
    has_dom_evidence: bool,
    has_result_values: bool,
    has_ocr_values: bool,
) -> tuple[list[str], list[str]]:
    """Return (supported_skills, unsupported_claims).

    Conservative: only signals that are actually evidenced are listed.
    Never invents skill labels from model guesses alone.
    """
    supported: list[str] = []
    unsupported: list[str] = []

    chain_complete  = iao_chain.get("chain_complete", False)
    chain_source    = iao_chain.get("chain_source", "none")
    has_strong      = chain_source == "dom_snapshot" and has_dom_evidence

    if chain_complete:
        if has_result_values or has_ocr_values:
            supported.append("End-to-end workflow demonstrated with captured output values")
        elif has_strong:
            supported.append("End-to-end input → action → output workflow observed via DOM evidence")
        else:
            supported.append("Input → action → output sequence detected from browser events")
    else:
        if iao_chain.get("detected_input"):
            supported.append("Input interaction observed")
        if iao_chain.get("detected_action"):
            supported.append("Action trigger observed")
        if iao_chain.get("detected_output"):
            supported.append("Output state reached")
        # Missing parts go to unsupported
        if not iao_chain.get("detected_input"):
            unsupported.append("No clear input interaction detected in this recording")
        if not iao_chain.get("detected_output"):
            unsupported.append("No clear output or result observed in this recording")

    return supported, unsupported


def _compute_evidence_strength(
    *,
    has_keyframes: bool,
    has_dom_evidence: bool,
    has_result_values: bool,
    has_ocr_values: bool,
    has_visual_summary: bool,
    has_events: bool,
    iao_chain: dict[str, Any],
    frame_count: int,
) -> tuple[str, int]:
    """Return (evidence_strength, confidence_score 0-100)."""
    score = 0

    # DOM result values: highest signal
    if has_result_values:
        score += 40
    elif has_dom_evidence:
        score += 25

    # OCR / visual
    if has_ocr_values:
        score += 15
    elif has_visual_summary:
        score += 8

    # Keyframes
    if has_keyframes and frame_count >= 5:
        score += 15
    elif has_keyframes:
        score += 8

    # IAO chain completeness
    if iao_chain.get("chain_complete"):
        score += 20
    else:
        if iao_chain.get("detected_input"):
            score += 5
        if iao_chain.get("detected_action"):
            score += 5
        if iao_chain.get("detected_output"):
            score += 5

    # Events
    if has_events:
        score += 5

    score = min(100, max(0, score))

    if score >= 70:
        strength = STRENGTH_STRONG
    elif score >= 45:
        strength = STRENGTH_MODERATE
    elif score >= 20:
        strength = STRENGTH_WEAK
    else:
        strength = STRENGTH_INSUFFICIENT

    return strength, score


def _build_limitations(
    *,
    has_keyframes: bool,
    has_dom_evidence: bool,
    has_result_values: bool,
    vf_status: str,
    iao_chain: dict[str, Any],
) -> list[str]:
    lims: list[str] = []

    if not has_keyframes:
        lims.append(
            "No video keyframes were extracted. Sequence analysis is based on "
            "DOM events and visible evidence only."
        )

    if not has_dom_evidence:
        lims.append(
            "DOM visible evidence was not captured. "
            "Re-record using a new session to enable richer sequence analysis."
        )
    elif not has_result_values:
        lims.append(
            "Visible page text was captured but no specific output values "
            "(labels, scores, numbers) were identified."
        )

    if vf_status == "not_configured":
        lims.append(
            "Visual frame analysis provider is not configured. "
            "Set VISUAL_ANALYSIS_PROVIDER to enable screenshot-level analysis."
        )
    elif vf_status == "failed":
        lims.append("Visual frame analysis encountered an error during processing.")

    if not iao_chain.get("chain_complete"):
        missing_parts: list[str] = []
        if not iao_chain.get("detected_input"):
            missing_parts.append("input")
        if not iao_chain.get("detected_action"):
            missing_parts.append("action")
        if not iao_chain.get("detected_output"):
            missing_parts.append("output")
        if missing_parts:
            lims.append(
                f"Incomplete workflow chain: {', '.join(missing_parts)} not clearly "
                "detected. The recording may not show a full end-to-end demonstration."
            )

    return lims


def _build_private_flags(
    *,
    has_keyframes: bool,
    has_dom_evidence: bool,
    evidence_strength: str,
    iao_chain: dict[str, Any],
) -> list[str]:
    flags: list[str] = []
    if not has_keyframes:
        flags.append("no_keyframes")
    if not has_dom_evidence:
        flags.append("no_dom_evidence")
    if evidence_strength == STRENGTH_INSUFFICIENT:
        flags.append("insufficient_evidence_for_proof")
    if not iao_chain.get("chain_complete"):
        flags.append("incomplete_iao_chain")
    return flags


def _build_summaries(
    *,
    iao_chain: dict[str, Any],
    stage_summaries: list[dict],
    observed_outputs: list[str],
    evidence_strength: str,
    confidence_score: int,
    has_keyframes: bool,
    frame_count: int,
) -> tuple[str, str]:
    """Return (public_safe_summary, recruiter_safe_summary)."""
    chain_complete = iao_chain.get("chain_complete", False)
    chain_source   = iao_chain.get("chain_source", "none")
    stages_with_evidence = sum(1 for s in stage_summaries if s.get("has_evidence"))

    kf_note = (
        f"Analysis used {frame_count} keyframe(s) from the recording video."
        if has_keyframes else
        "No video keyframes were available; analysis based on DOM and event evidence."
    )

    if chain_complete:
        chain_desc = (
            "A complete input → action → output workflow was detected. "
            f"Input: {iao_chain.get('detected_input', 'provided')}. "
            f"Action: {iao_chain.get('detected_action', 'triggered')}. "
            f"Output: {iao_chain.get('detected_output', 'observed')}."
        )
    else:
        parts: list[str] = []
        if iao_chain.get("detected_input"):
            parts.append(f"input ({iao_chain['detected_input']})")
        if iao_chain.get("detected_action"):
            parts.append(f"action ({iao_chain['detected_action']})")
        if iao_chain.get("detected_output"):
            parts.append(f"output ({iao_chain['detected_output']})")
        chain_desc = (
            f"Partial workflow detected: {', '.join(parts)}. "
            "A complete end-to-end chain was not confirmed."
            if parts else
            "No clear workflow chain was detected in this recording."
        )

    output_note = (
        f"Observed output(s): {', '.join(observed_outputs[:2])}."
        if observed_outputs else
        "No specific output values were captured."
    )

    src_label = {
        "dom_snapshot":      "DOM visible evidence",
        "visual_frame_ocr":  "OCR analysis of keyframes",
        "visual_frame_model":"visual model analysis of keyframes",
        "browser_event":     "browser event timeline",
        "none":              "available evidence",
    }.get(chain_source, "available evidence")

    public_summary = (
        f"Sequence analysis completed ({evidence_strength} evidence, "
        f"confidence {confidence_score}%). "
        f"{chain_desc} "
        f"{output_note} "
        f"Evidence source: {src_label}. "
        f"{kf_note}"
    )

    recruiter_summary = (
        f"The workflow recording was analysed across {stages_with_evidence} evidence stage(s). "
        f"{chain_desc} "
        f"{output_note} "
        f"Evidence confidence: {evidence_strength} ({confidence_score}%)."
    )

    return public_summary, recruiter_summary
