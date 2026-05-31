"""Advanced Visual Reasoning Service — Level 3.

Provides structured, skill-evidence-aware visual reasoning on top of the
existing OCR pipeline.  Uses open-weight vision models (Qwen2.5-VL is the
recommended backend) to produce structured per-frame JSON observations and
an aggregated session-level summary.

Architecture
------------
  DisabledReasoningProvider   — VISUAL_REASONING_ENABLED=false (safe default)
  QwenVLReasoningProvider     — Qwen2.5-VL / Qwen3-VL via LocalVisionProvider
  MockReasoningProvider       — injected during tests (never used in production)

Provider selection
------------------
  VISUAL_REASONING_ENABLED=true   (default: false)
  LOCAL_VISION_PROVIDER=qwen_vl   (or qwen3_vl — reuses existing setting)
  VISUAL_REASONING_MAX_FRAMES=3   (default: 3 representative frames)

Pipeline position
-----------------
  keyframes
    → OCR (Level 1)                 — text extraction, result values
    → Visual Reasoning (Level 3)    — structured skill-evidence analysis

Generalization
--------------
The service is completely project-agnostic.  It does NOT detect Teachable
Machine, Google Colab, or any specific app.  It reports what is VISUALLY
OBSERVABLE: UI elements, workflow stages, outputs, skill evidence signals.
The caller is responsible for mapping those signals to claimed skills.

Privacy
-------
  • frame_bytes are never persisted by this service.
  • Sensitive text detected in model output is masked before storage.
  • to_public_dict() is the ONLY serialisation used in API responses.
    It never includes raw frame paths, access tokens, or debug metadata.

Setup (Mac / NVIDIA)
--------------------
  pip install "transformers>=4.45" torch pillow accelerate
  export VISUAL_REASONING_ENABLED=true
  export LOCAL_VISION_PROVIDER=qwen_vl    # or qwen3_vl

  First run downloads Qwen/Qwen2.5-VL-7B-Instruct (~14 GB) to
  ~/.cache/huggingface.  Mac M-series supported via CPU / MPS.
  NVIDIA GPU recommended for interactive speed (float16 on GPU).

Memory guidance
---------------
  Qwen2.5-VL-7B  — ~14 GB (float32 CPU) / ~7 GB (float16 GPU)
  Qwen2.5-VL-3B  — ~6 GB  (float32 CPU) / ~3 GB (float16 GPU)  [lighter]
  Qwen3-VL-7B    — ~14 GB (float32 CPU) / ~7 GB (float16 GPU)

  If running alongside local_ocr, allocate extra RAM for both processes.
  On resource-constrained hosts, set VISUAL_REASONING_ENABLED=false and
  rely on OCR alone.
"""

from __future__ import annotations

import io
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Status values ──────────────────────────────────────────────────────────────

REASONING_STATUS_ANALYZED           = "analyzed"
REASONING_STATUS_FAILED             = "failed"
REASONING_STATUS_DISABLED           = "disabled"
REASONING_STATUS_MISSING_DEPENDENCY = "missing_dependency"
REASONING_STATUS_NOT_CONFIGURED     = "not_configured"

# ── Valid workflow stage labels ────────────────────────────────────────────────

VALID_WORKFLOW_STAGES = frozenset({
    "data_input",
    "processing",
    "model_training",
    "results_display",
    "prediction_output",
    "navigation",
    "browsing",
    "idle",
    "unknown",
})

# ── Structured JSON prompt (generic, project-agnostic) ────────────────────────

_STRUCTURED_REASONING_PROMPT = """You are a visual evidence analyzer for a professional skill verification system.
Analyze this screenshot of a web application, tool, dashboard, or document.

Return ONLY a valid JSON object. No markdown, no code blocks, no explanation.

{
  "visual_summary": "<one clear sentence about what is visible>",
  "visible_ui_elements": ["<UI components: buttons, forms, charts, tables, etc>"],
  "visible_objects": ["<content types: images, graphs, text, code, data, etc>"],
  "detected_workflow_stage": "<data_input|processing|model_training|results_display|prediction_output|navigation|idle|unknown>",
  "detected_actions": ["<user workflow steps or actions visible>"],
  "detected_outputs": ["<output values, results, metrics, or conclusions visible>"],
  "detected_skills_supported": ["<skill categories evidenced by visible content>"],
  "missing_or_unclear_evidence": ["<things needed but not clearly visible>"],
  "confidence_score": 0.7,
  "limitations": ["<limitations in this analysis>"]
}

Rules:
1. Only report what is ACTUALLY VISIBLE in the image.
2. Do NOT invent values, labels, or results not shown.
3. detected_skills_supported must be based ONLY on visible content.
4. confidence_score: 0.9=very clear, 0.7=clear, 0.5=somewhat clear, 0.3=unclear.
5. Return ONLY the JSON object — no other text before or after."""


# ── Sensitive-text masking (mirrors workflow_visual_analysis_service) ──────────

_SENSITIVE_MASK_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)password\s*[:=]\s*\S+"), "[PASSWORD REDACTED]"),
    (re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*\S+"), "[SECRET REDACTED]"),
    (re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"), "[EMAIL REDACTED]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[CARD REDACTED]"),
    (re.compile(r"(?i)(\/users\/|\/home\/|C:\\Users\\)\S+"), "[PATH REDACTED]"),
    (re.compile(r"https?://[a-z0-9]+\.supabase\.(co|io)\S*"), "[INTERNAL URL REDACTED]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN REDACTED]"),
]

_PRIVATE_FIELDS = frozenset({
    "frame_storage_path", "raw_frame", "frame_bytes",
    "access_token", "raw_dom", "debug_metadata",
})


def _mask_sensitive_text(text: str) -> tuple[str, list[str]]:
    flags: list[str] = []
    for pattern, replacement in _SENSITIVE_MASK_PATTERNS:
        if pattern.search(text):
            flags.append(replacement.strip("[]"))
            text = pattern.sub(replacement, text)
    return text, flags


# ── Output dataclass ───────────────────────────────────────────────────────────

@dataclass
class VisualReasoningObservation:
    """Structured output from advanced visual reasoning on a single frame.

    All string fields are PII-masked before storage.
    to_public_dict() is the ONLY method used in API responses.
    """

    frame_index: int | None = None
    timestamp_ms: int | None = None
    model_provider: str = "none"

    # Core reasoning output
    visual_summary: str = ""
    visible_ui_elements: list[str] = field(default_factory=list)
    visible_objects: list[str] = field(default_factory=list)
    detected_workflow_stage: str = "unknown"
    detected_actions: list[str] = field(default_factory=list)
    detected_outputs: list[str] = field(default_factory=list)
    detected_skills_supported: list[str] = field(default_factory=list)
    missing_or_unclear_evidence: list[str] = field(default_factory=list)
    confidence_score: float = 0.0
    limitations: list[str] = field(default_factory=list)

    # Meta
    status: str = REASONING_STATUS_DISABLED
    privacy_flags: list[str] = field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        """Public-safe serialisation — never includes raw frames or tokens."""
        return {
            "frame_index":              self.frame_index,
            "timestamp_ms":             self.timestamp_ms,
            "model_provider":           self.model_provider,
            "visual_summary":           self.visual_summary,
            "visible_ui_elements":      self.visible_ui_elements,
            "visible_objects":          self.visible_objects,
            "detected_workflow_stage":  self.detected_workflow_stage,
            "detected_actions":         self.detected_actions,
            "detected_outputs":         self.detected_outputs,
            "detected_skills_supported": self.detected_skills_supported,
            "missing_or_unclear_evidence": self.missing_or_unclear_evidence,
            "confidence_score":         self.confidence_score,
            "limitations":              self.limitations,
            "status":                   self.status,
        }


@dataclass
class VisualReasoningSessionSummary:
    """Aggregated visual reasoning result for a recording session."""

    status: str = REASONING_STATUS_DISABLED
    provider: str = "none"
    frames_analyzed: int = 0
    summary: str = ""
    observations: list[dict[str, Any]] = field(default_factory=list)
    supported_signals: list[str] = field(default_factory=list)
    missing_claims: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        """Public-safe serialisation.  Strips _PRIVATE_FIELDS if any leak in."""
        return {
            "status":            self.status,
            "provider":          self.provider,
            "frames_analyzed":   self.frames_analyzed,
            "summary":           self.summary,
            "observations":      [
                {k: v for k, v in obs.items() if k not in _PRIVATE_FIELDS}
                for obs in self.observations
            ],
            "supported_signals": self.supported_signals,
            "missing_claims":    self.missing_claims,
            "limitations":       self.limitations,
        }


# ── Provider interface ─────────────────────────────────────────────────────────

class VisualReasoningProvider(ABC):
    """Abstract base for visual reasoning providers.

    All implementations must be safe to call even when packages are missing.
    is_configured() MUST NOT raise; analyze_frame_reasoning() MUST NOT raise.
    """

    @abstractmethod
    def is_configured(self) -> bool:
        """True only when this provider can actually run analysis."""
        ...

    @abstractmethod
    def analyze_frame_reasoning(
        self,
        frame_bytes: bytes,
        claimed_skills: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> VisualReasoningObservation:
        """Analyze one frame.  Never raises."""
        ...

    @property
    def provider_name(self) -> str:
        return self.__class__.__name__


# ── Provider: Disabled (safe default) ─────────────────────────────────────────

class DisabledReasoningProvider(VisualReasoningProvider):
    """Default provider — advanced visual reasoning disabled.

    Used when VISUAL_REASONING_ENABLED=false (the default).
    Always returns disabled status.  OCR evidence continues to work.
    """

    def is_configured(self) -> bool:
        return False

    def analyze_frame_reasoning(
        self,
        frame_bytes: bytes,
        claimed_skills: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> VisualReasoningObservation:
        return VisualReasoningObservation(
            status=REASONING_STATUS_DISABLED,
            limitations=["Advanced visual reasoning is not enabled (VISUAL_REASONING_ENABLED=false)."],
            model_provider="none",
        )


# ── Provider: Qwen-VL (structured reasoning) ──────────────────────────────────

class QwenVLReasoningProvider(VisualReasoningProvider):
    """Advanced visual reasoning using Qwen2.5-VL / Qwen3-VL.

    Uses the same model infrastructure as LocalVisionProvider but with a
    structured JSON-output prompt for skill-evidence reasoning.

    Setup:
        pip install "transformers>=4.45" torch pillow accelerate
        export VISUAL_REASONING_ENABLED=true
        export LOCAL_VISION_PROVIDER=qwen_vl    # or qwen3_vl

    Memory: ~14 GB (CPU float32) or ~7 GB (GPU float16).
    Mac M-series: supported via CPU/MPS.  NVIDIA GPU: recommended for speed.

    If required packages are not installed, is_configured() returns False and
    analyze_frame_reasoning() returns missing_dependency — never raises.
    """

    _MODEL_IDS: dict[str, str] = {
        "qwen_vl":  "Qwen/Qwen2.5-VL-7B-Instruct",
        "qwen3_vl": "Qwen/Qwen3-VL-7B-Instruct",
    }

    def __init__(self) -> None:
        self._backend: str = settings.local_vision_provider.lower()
        self._available: bool | None = None
        self._model: Any = None
        self._processor: Any = None
        # Allow LOCAL_VISION_MODEL to override the default model ID for the provider.
        # E.g. Qwen/Qwen2.5-VL-3B-Instruct as a lighter fallback.
        self._model_id_override: str = settings.local_vision_model.strip()

    def _resolved_model_id(self) -> str | None:
        """Return the HF model ID to use, respecting LOCAL_VISION_MODEL override."""
        if self._model_id_override:
            return self._model_id_override
        return self._MODEL_IDS.get(self._backend)

    # ── Package importability check (fast, no weight loading) ─────────────────

    def _try_init(self) -> bool:
        if self._available is not None:
            return self._available

        model_id = self._resolved_model_id()
        if not model_id:
            logger.warning(
                "[VisionReasoning] LOCAL_VISION_PROVIDER=%r is not a supported backend "
                "for visual reasoning.  Supported: %s",
                self._backend, ", ".join(self._MODEL_IDS),
            )
            self._available = False
            return False

        try:
            import torch  # type: ignore[import]  # noqa: F401
            from PIL import Image  # type: ignore[import]  # noqa: F401
            from transformers import (  # type: ignore[import]  # noqa: F401
                Qwen2_5_VLForConditionalGeneration,
                AutoProcessor,
            )
            import torchvision  # type: ignore[import]  # noqa: F401
            from qwen_vl_utils import process_vision_info  # type: ignore[import]  # noqa: F401
            logger.info(
                "[VisionReasoning] Packages verified for %r.  "
                "Model weights (%s) download on first inference.",
                self._backend, model_id,
            )
            self._available = True
        except ImportError as exc:
            logger.info(
                "[VisionReasoning] Required packages missing for %r.  "
                "Install: pip install 'transformers>=4.45' torch torchvision pillow accelerate qwen-vl-utils\n"
                "Error: %s",
                self._backend, exc,
            )
            self._available = False
        except Exception as exc:
            logger.warning("[VisionReasoning] Init check failed: %s", exc)
            self._available = False

        return bool(self._available)

    def is_configured(self) -> bool:
        return self._try_init()

    # ── Lazy model loading ─────────────────────────────────────────────────────

    def _load_model(self) -> bool:
        if self._model is not None:
            return True

        model_id = self._resolved_model_id() or ""
        try:
            import torch  # type: ignore[import]
            from transformers import (  # type: ignore[import]
                Qwen2_5_VLForConditionalGeneration,
                AutoProcessor,
            )

            # Device selection: CUDA > MPS (Apple Silicon) > CPU
            if torch.cuda.is_available():
                device = "cuda"
                dtype = torch.float16
            elif torch.backends.mps.is_available():
                device = "mps"
                dtype = torch.float16  # float16 on MPS; bfloat16 also supported in PyTorch 2.x
            else:
                device = "cpu"
                dtype = torch.float32

            logger.info(
                "[VisionReasoning] Loading %s from %s … (device=%s, dtype=%s)",
                self._backend, model_id, device, dtype,
            )

            # For CUDA use device_map="auto" (multi-GPU friendly).
            # For MPS/CPU load on CPU first (device_map not supported for MPS),
            # then move to target device.
            if device == "cuda":
                self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                    model_id,
                    dtype=dtype,
                    device_map="auto",
                )
            else:
                self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                    model_id,
                    dtype=dtype,
                )
                self._model = self._model.to(device)

            self._processor = AutoProcessor.from_pretrained(model_id)
            logger.info(
                "[VisionReasoning] %r loaded (device=%s, dtype=%s).",
                self._backend, device, dtype,
            )
            return True
        except MemoryError:
            logger.warning(
                "[VisionReasoning] Out of memory loading %r (%s). "
                "Try smaller model or reduce VISUAL_REASONING_MAX_FRAMES.",
                self._backend, model_id,
            )
            self._model = None
            self._processor = None
            return False
        except Exception as exc:
            logger.warning("[VisionReasoning] Model load failed: %s", exc)
            self._model = None
            self._processor = None
            return False

    # ── Inference ──────────────────────────────────────────────────────────────

    def _run_inference(self, frame_bytes: bytes) -> str:
        """Run Qwen-VL inference with structured JSON prompt.  Returns raw output."""
        if not self._load_model():
            return ""
        try:
            from PIL import Image  # type: ignore[import]
            img = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
        except Exception as exc:
            logger.warning("[VisionReasoning] Could not decode image bytes: %s", exc)
            return ""

        try:
            import torch  # type: ignore[import]
            from qwen_vl_utils import process_vision_info  # type: ignore[import]

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": img},
                        {"type": "text",  "text":  _STRUCTURED_REASONING_PROMPT},
                    ],
                }
            ]

            # Build chat text
            text = self._processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )

            # Use qwen_vl_utils to extract image/video tensors (official Qwen2.5-VL path)
            image_inputs, video_inputs = process_vision_info(messages)

            inputs = self._processor(
                text=[text],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt",
            )
            inputs = inputs.to(self._model.device)

            with torch.no_grad():
                generated_ids = self._model.generate(
                    **inputs,
                    max_new_tokens=512,
                    do_sample=False,
                )

            generated_ids_trimmed = [
                out_ids[len(in_ids):]
                for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            output = self._processor.batch_decode(
                generated_ids_trimmed,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )
            return output[0].strip() if output else ""
        except Exception as exc:
            logger.warning("[VisionReasoning] Inference error: %s", exc)
            return ""

    # ── JSON parsing (robust, multi-strategy) ─────────────────────────────────

    @staticmethod
    def _parse_json_output(text: str) -> dict[str, Any]:
        """Parse JSON from model output with multiple fallback strategies."""
        if not text:
            return {}

        # Strategy 1: Direct parse
        try:
            return json.loads(text.strip())
        except (json.JSONDecodeError, ValueError):
            pass

        # Strategy 2: Extract first JSON object (handles leading/trailing text)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except (json.JSONDecodeError, ValueError):
                pass

        # Strategy 3: Line-by-line field extraction (last resort)
        partial: dict[str, Any] = {}
        for line in text.splitlines():
            for field_name in (
                "visual_summary", "detected_workflow_stage", "confidence_score"
            ):
                if f'"{field_name}"' in line:
                    val_match = re.search(r':\s*"([^"]*)"', line)
                    if val_match:
                        partial[field_name] = val_match.group(1)
        return partial

    @staticmethod
    def _normalize_parsed(parsed: dict[str, Any]) -> dict[str, Any]:
        """Normalise field types / values from parsed JSON."""

        def to_str_list(v: Any) -> list[str]:
            if isinstance(v, list):
                return [str(x)[:200] for x in v if x]
            if isinstance(v, str) and v:
                return [v]
            return []

        stage = str(parsed.get("detected_workflow_stage", "unknown")).lower()
        if stage not in VALID_WORKFLOW_STAGES:
            stage = "unknown"

        raw_score = parsed.get("confidence_score", 0.5)
        try:
            score = float(raw_score)
            score = max(0.0, min(1.0, score))
        except (TypeError, ValueError):
            score = 0.5

        return {
            "visual_summary":              str(parsed.get("visual_summary", ""))[:500],
            "visible_ui_elements":         to_str_list(parsed.get("visible_ui_elements")),
            "visible_objects":             to_str_list(parsed.get("visible_objects")),
            "detected_workflow_stage":     stage,
            "detected_actions":            to_str_list(parsed.get("detected_actions")),
            "detected_outputs":            to_str_list(parsed.get("detected_outputs")),
            "detected_skills_supported":   to_str_list(parsed.get("detected_skills_supported")),
            "missing_or_unclear_evidence": to_str_list(parsed.get("missing_or_unclear_evidence")),
            "confidence_score":            score,
            "limitations":                 to_str_list(parsed.get("limitations")),
        }

    # ── Public analysis method ─────────────────────────────────────────────────

    def analyze_frame_reasoning(
        self,
        frame_bytes: bytes,
        claimed_skills: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> VisualReasoningObservation:
        ctx = context or {}
        frame_index: int | None = ctx.get("frame_index")
        timestamp_ms: int | None = ctx.get("timestamp_ms")
        provider_label = f"qwen_vl:{self._backend}"

        if not self._try_init():
            return VisualReasoningObservation(
                frame_index=frame_index,
                timestamp_ms=timestamp_ms,
                model_provider=provider_label,
                status=REASONING_STATUS_MISSING_DEPENDENCY,
                limitations=[
                    "Qwen-VL packages not installed.  "
                    "Install: pip install 'transformers>=4.45' torch pillow accelerate",
                ],
            )

        raw = self._run_inference(frame_bytes)
        if not raw:
            return VisualReasoningObservation(
                frame_index=frame_index,
                timestamp_ms=timestamp_ms,
                model_provider=provider_label,
                status=REASONING_STATUS_FAILED,
                limitations=[
                    "Vision model returned empty output.  "
                    "Check model is downloaded and device has sufficient memory."
                ],
            )

        # Mask sensitive content in model output
        cleaned, privacy_flags = _mask_sensitive_text(raw)

        parsed = self._parse_json_output(cleaned)
        norm = self._normalize_parsed(parsed)

        return VisualReasoningObservation(
            frame_index=frame_index,
            timestamp_ms=timestamp_ms,
            model_provider=provider_label,
            visual_summary=norm["visual_summary"],
            visible_ui_elements=norm["visible_ui_elements"],
            visible_objects=norm["visible_objects"],
            detected_workflow_stage=norm["detected_workflow_stage"],
            detected_actions=norm["detected_actions"],
            detected_outputs=norm["detected_outputs"],
            detected_skills_supported=norm["detected_skills_supported"],
            missing_or_unclear_evidence=norm["missing_or_unclear_evidence"],
            confidence_score=norm["confidence_score"],
            limitations=norm["limitations"],
            status=REASONING_STATUS_ANALYZED,
            privacy_flags=privacy_flags,
        )


# ── Provider: Mock (tests only) ────────────────────────────────────────────────

class MockReasoningProvider(VisualReasoningProvider):
    """Deterministic mock for tests.

    Pass a list of canned observations to be returned in order.
    If observations is empty, returns a default analyzed observation.

    NEVER used in production — injected only via VisualReasoningService
    constructor during tests.
    """

    def __init__(
        self,
        observations: list[VisualReasoningObservation] | None = None,
        is_available: bool = True,
    ) -> None:
        self._observations = observations or []
        self._call_count = 0
        self._is_available = is_available

    def is_configured(self) -> bool:
        return self._is_available

    def analyze_frame_reasoning(
        self,
        frame_bytes: bytes,
        claimed_skills: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> VisualReasoningObservation:
        ctx = context or {}
        if not self._is_available:
            return VisualReasoningObservation(
                frame_index=ctx.get("frame_index"),
                timestamp_ms=ctx.get("timestamp_ms"),
                model_provider="mock:unavailable",
                status=REASONING_STATUS_MISSING_DEPENDENCY,
                limitations=["Mock provider configured as unavailable."],
            )

        if self._observations and self._call_count < len(self._observations):
            obs = self._observations[self._call_count]
            self._call_count += 1
            return obs

        # Default analyzed observation
        self._call_count += 1
        return VisualReasoningObservation(
            frame_index=ctx.get("frame_index"),
            timestamp_ms=ctx.get("timestamp_ms"),
            model_provider="mock",
            visual_summary="Mock visual analysis: a web application is visible.",
            visible_ui_elements=["button", "form", "result-panel"],
            visible_objects=["text", "chart"],
            detected_workflow_stage="results_display",
            detected_actions=["user submitted input"],
            detected_outputs=["result: 0.89"],
            detected_skills_supported=["web_development"],
            missing_or_unclear_evidence=[],
            confidence_score=0.8,
            limitations=[],
            status=REASONING_STATUS_ANALYZED,
        )


# ── Session-level aggregation ──────────────────────────────────────────────────

def _build_session_summary(
    observations: list[VisualReasoningObservation],
    provider_name: str,
) -> VisualReasoningSessionSummary:
    """Aggregate per-frame observations into a session-level summary."""
    analyzed = [o for o in observations if o.status == REASONING_STATUS_ANALYZED]

    if not analyzed:
        status = REASONING_STATUS_FAILED if observations else REASONING_STATUS_DISABLED
        first_limitation = (
            observations[0].limitations[0]
            if observations and observations[0].limitations
            else "No frames analyzed."
        )
        return VisualReasoningSessionSummary(
            status=status,
            provider=provider_name,
            frames_analyzed=0,
            summary="Advanced visual reasoning did not produce results for this session.",
            limitations=[first_limitation],
        )

    # Aggregate skill signals across frames (deduplicated)
    all_skills: list[str] = []
    seen_skills: set[str] = set()
    for obs in analyzed:
        for s in obs.detected_skills_supported:
            key = s.strip().lower()
            if key not in seen_skills:
                seen_skills.add(key)
                all_skills.append(s.strip())

    # Aggregate missing evidence (deduplicated)
    all_missing: list[str] = []
    seen_missing: set[str] = set()
    for obs in analyzed:
        for m in obs.missing_or_unclear_evidence:
            key = m.strip().lower()
            if key not in seen_missing:
                seen_missing.add(key)
                all_missing.append(m.strip())

    # Build narrative summary from visual summaries
    summaries = [o.visual_summary for o in analyzed if o.visual_summary]
    combined_summary = " | ".join(summaries[:4])[:600] if summaries else ""

    # Detect dominant workflow stage
    stage_votes: dict[str, int] = {}
    for obs in analyzed:
        stage_votes[obs.detected_workflow_stage] = (
            stage_votes.get(obs.detected_workflow_stage, 0) + 1
        )
    dominant_stage = max(stage_votes, key=stage_votes.get) if stage_votes else "unknown"

    if combined_summary and dominant_stage != "unknown":
        combined_summary = f"[{dominant_stage}] {combined_summary}"

    # Aggregate limitations
    all_limits: list[str] = []
    seen_limits: set[str] = set()
    for obs in analyzed:
        for lim in obs.limitations:
            key = lim.strip().lower()[:80]
            if key not in seen_limits:
                seen_limits.add(key)
                all_limits.append(lim.strip())

    return VisualReasoningSessionSummary(
        status=REASONING_STATUS_ANALYZED,
        provider=provider_name,
        frames_analyzed=len(analyzed),
        summary=combined_summary,
        observations=[obs.to_public_dict() for obs in analyzed],
        supported_signals=all_skills,
        missing_claims=all_missing,
        limitations=all_limits,
    )


# ── Provider factory ───────────────────────────────────────────────────────────

def get_visual_reasoning_provider() -> VisualReasoningProvider:
    """Return the configured visual reasoning provider.

    Never raises.  Defaults to DisabledReasoningProvider when
    VISUAL_REASONING_ENABLED=false (the safe default).

    Environment:
        VISUAL_REASONING_ENABLED=true      — enable (default: false)
        LOCAL_VISION_PROVIDER=qwen_vl      — model backend (default: qwen_vl)
    """
    if not settings.visual_reasoning_enabled:
        return DisabledReasoningProvider()

    backend = settings.local_vision_provider.lower()
    # Allow if either the backend is known OR a direct LOCAL_VISION_MODEL override is set.
    model_override = settings.local_vision_model.strip()
    if backend not in QwenVLReasoningProvider._MODEL_IDS and not model_override:
        logger.warning(
            "[VisionReasoning] LOCAL_VISION_PROVIDER=%r is not supported for reasoning "
            "and LOCAL_VISION_MODEL is not set. "
            "Supported providers: %s.  Falling back to DisabledReasoningProvider.",
            backend, ", ".join(QwenVLReasoningProvider._MODEL_IDS),
        )
        return DisabledReasoningProvider()

    return QwenVLReasoningProvider()


# ── Module-level singleton ─────────────────────────────────────────────────────

_REASONING_PROVIDER_SINGLETON: VisualReasoningProvider | None = None


def _get_reasoning_provider_singleton() -> VisualReasoningProvider:
    global _REASONING_PROVIDER_SINGLETON
    if _REASONING_PROVIDER_SINGLETON is None:
        _REASONING_PROVIDER_SINGLETON = get_visual_reasoning_provider()
    return _REASONING_PROVIDER_SINGLETON


# ── Main service ───────────────────────────────────────────────────────────────

class VisualReasoningService:
    """Main service for advanced visual reasoning on keyframe sessions.

    Usage:
        svc = VisualReasoningService()

        # Analyze selected frames from a session
        summary = svc.analyze_frames(
            frames=[(ts_ms, jpeg_bytes), ...],
            claimed_skills=["Machine Learning", "TensorFlow.js"],
        )

        # Check if provider is available
        status = svc.get_provider_status()

    The service is safe to instantiate even when no model is installed.
    When disabled / packages missing, all methods return appropriate status
    without raising exceptions.

    For tests, inject a MockReasoningProvider:
        svc = VisualReasoningService(provider=MockReasoningProvider(...))
    """

    def __init__(
        self,
        provider: VisualReasoningProvider | None = None,
    ) -> None:
        self._provider = provider or _get_reasoning_provider_singleton()

    def get_provider_status(self) -> dict[str, Any]:
        """Return provider configuration status for the frontend."""
        is_configured = self._provider.is_configured()
        return {
            "visual_reasoning_enabled": settings.visual_reasoning_enabled,
            "visual_reasoning_configured": is_configured,
            "local_vision_provider": settings.local_vision_provider,
            "visual_reasoning_max_frames": settings.visual_reasoning_max_frames,
        }

    def analyze_frames(
        self,
        frames: list[tuple[int, bytes]],
        claimed_skills: list[str] | None = None,
        max_frames: int | None = None,
    ) -> VisualReasoningSessionSummary:
        """Analyze up to max_frames representative keyframes.

        Args:
            frames:       list of (timestamp_ms, jpeg_bytes) pairs
            claimed_skills: skills the student claims to demonstrate
            max_frames:   cap on frames to analyze (default: VISUAL_REASONING_MAX_FRAMES)

        Returns:
            VisualReasoningSessionSummary — never raises.
        """
        provider = self._provider
        limit = max_frames or settings.visual_reasoning_max_frames

        if not provider.is_configured():
            return VisualReasoningSessionSummary(
                status=REASONING_STATUS_DISABLED
                if not settings.visual_reasoning_enabled
                else REASONING_STATUS_MISSING_DEPENDENCY,
                provider="none",
                frames_analyzed=0,
                summary="",
                limitations=[
                    "Advanced visual reasoning is not enabled. "
                    "OCR-based frame analysis was used."
                    if not settings.visual_reasoning_enabled else
                    "Qwen-VL packages not installed.  "
                    "Install: pip install 'transformers>=4.45' torch pillow accelerate"
                ],
            )

        # Select representative frames (evenly spaced up to limit)
        if not frames:
            return VisualReasoningSessionSummary(
                status=REASONING_STATUS_FAILED,
                provider=provider.provider_name,
                frames_analyzed=0,
                summary="No frames provided for visual reasoning.",
                limitations=["No keyframes were available for analysis."],
            )

        if len(frames) <= limit:
            selected = list(frames)
        else:
            step = len(frames) / limit
            selected = [frames[int(i * step)] for i in range(limit)]

        observations: list[VisualReasoningObservation] = []
        for idx, (ts_ms, jpeg_bytes) in enumerate(selected):
            ctx = {"frame_index": idx, "timestamp_ms": ts_ms}
            try:
                obs = provider.analyze_frame_reasoning(
                    frame_bytes=jpeg_bytes,
                    claimed_skills=claimed_skills,
                    context=ctx,
                )
            except Exception as exc:
                logger.warning(
                    "[VisionReasoning] analyze_frame_reasoning raised (frame %d): %s",
                    idx, exc,
                )
                obs = VisualReasoningObservation(
                    frame_index=idx,
                    timestamp_ms=ts_ms,
                    model_provider=provider.provider_name,
                    status=REASONING_STATUS_FAILED,
                    limitations=[f"Frame analysis raised an unexpected error: {exc}"],
                )
            observations.append(obs)

        return _build_session_summary(observations, provider.provider_name)
