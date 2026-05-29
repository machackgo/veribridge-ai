"""Workflow Visual Frame Analysis Service.

Provider-agnostic visual analysis of screenshot frames captured by the browser
extension during website proof recordings.

Architecture
------------
The service exposes a single VisualAnalysisProvider interface.  Multiple
concrete providers implement that interface:

  NoneProvider             — always returns not_configured; safe default
  LocalOCRProvider         — PaddleOCR / EasyOCR / Tesseract (optional install)
  LocalVisionProvider      — LLaVA / Qwen2.5-VL / MiniCPM-V / BLIP (optional)
  OpenAIVisionProvider     — OpenAI Vision API (requires OPENAI_API_KEY)
  VeriBridgeFutureProvider — reserved for VeriBridge fine-tuned model

Provider selection
------------------
Set the environment variable:
  VISUAL_ANALYSIS_PROVIDER=none|local_ocr|local_vision|openai|veribridge_future
Default is "none".

If the requested provider's packages are NOT installed, the service falls back
gracefully to not_configured WITHOUT crashing.  DOM evidence continues to work.

Local OCR setup (optional)
--------------------------
  PaddleOCR:  pip install paddleocr paddlepaddle
  EasyOCR:    pip install easyocr
  Tesseract:  pip install pytesseract  +  brew install tesseract (or apt)

Set: LOCAL_OCR_PROVIDER=paddleocr|easyocr|tesseract

Local Vision setup (optional)
------------------------------
  LLaVA / Qwen2.5-VL / MiniCPM-V / BLIP:
    pip install transformers torch pillow accelerate

Set: LOCAL_VISION_PROVIDER=llava|qwen_vl|minicpm_v|blip

Frame capture throttling
------------------------
  ENABLE_WORKFLOW_FRAME_CAPTURE=true
  MAX_WORKFLOW_FRAMES=15   (default)

Evidence priority (used by workflow analysis)
---------------------------------------------
  1. DOM exact result values (highest confidence)
  2. Local OCR exact result values
  3. Local vision frame summaries
  4. Browser events
  5. Claimed skills / GitHub context

Privacy guarantees
------------------
  • frame_storage_path is NEVER exposed publicly.
  • extracted_result_values only contain what was visually captured.
  • PII detected during OCR is masked and recorded in privacy_flags.
  • Exact values are NOT invented — if unsure, value is omitted.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_TABLE = "workflow_visual_frame_evidence"

# ── Allowed status values ──────────────────────────────────────────────────────

VISUAL_STATUS_PENDING        = "pending"
VISUAL_STATUS_ANALYZED       = "analyzed"
VISUAL_STATUS_SKIPPED        = "skipped"
VISUAL_STATUS_FAILED         = "failed"
VISUAL_STATUS_NOT_CONFIGURED = "not_configured"

# ── Sensitive pattern masking (applied to OCR output) ─────────────────────────

_SENSITIVE_MASK_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)password\s*[:=]\s*\S+"), "[PASSWORD REDACTED]"),
    (re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*\S+"), "[SECRET REDACTED]"),
    (re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"), "[EMAIL REDACTED]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[CARD REDACTED]"),
    (re.compile(r"(?i)(\/users\/|\/home\/|C:\\Users\\)\S+"), "[PATH REDACTED]"),
    (re.compile(r"https?://[a-z0-9]+\.supabase\.(co|io)\S*"), "[INTERNAL URL REDACTED]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN REDACTED]"),
]


def _mask_sensitive_text(text: str) -> tuple[str, list[str]]:
    """Apply PII/secret masking to raw OCR text.  Returns (cleaned, flags)."""
    flags: list[str] = []
    for pattern, replacement in _SENSITIVE_MASK_PATTERNS:
        if pattern.search(text):
            flags.append(replacement.strip("[]"))
            text = pattern.sub(replacement, text)
    return text, flags


# ── Result-value extraction from OCR text ─────────────────────────────────────

# Generic patterns that match "label: 0.89", "dog 0.89", "accuracy: 92%", etc.
_RESULT_VALUE_RE = re.compile(
    r"""
    (?P<label>[A-Za-z][A-Za-z0-9 _\-]{0,40}?)   # label (letters, spaces)
    \s*[:\-]?\s*                                   # optional separator
    (?P<value>
        \d{1,3}(?:\.\d{1,4})?                     # decimal number 0.89 / 72.3
        |
        \d{1,3}%                                   # percentage 92%
    )
    (?:\s|$|,|\.|;)
    """,
    re.VERBOSE,
)


def extract_result_values_from_ocr(
    ocr_lines: list[str],
) -> list[dict[str, Any]]:
    """Extract structured result values from a list of OCR text lines.

    Conservative: only returns values with a clear label+number pattern.
    Does NOT invent values.  Returns [] if nothing matches.

    Example:
        ["dog 0.89", "person 0.77", "accuracy: 94%"]
        → [{"label": "dog", "value": "0.89", "confidence": 0.9, "source": "ocr"},
           {"label": "person", "value": "0.77", "confidence": 0.9, "source": "ocr"},
           {"label": "accuracy", "value": "94%", "confidence": 0.9, "source": "ocr"}]
    """
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for line in ocr_lines:
        line = line.strip()
        if not line:
            continue
        for m in _RESULT_VALUE_RE.finditer(line):
            label = m.group("label").strip(" :-").strip()
            value = m.group("value").strip()
            if not label or len(label) < 2:
                continue
            key = f"{label.lower()}:{value}"
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "label": label,
                "value": value,
                "confidence": 0.9,   # conservative, fixed for OCR extraction
                "source": "ocr",
            })

    return results


# ── Output schema ──────────────────────────────────────────────────────────────

@dataclass
class VisualFrameObservation:
    """Structured output from visual analysis of a single frame."""

    timestamp_ms: int | None = None
    screen_summary: str = ""
    visible_inputs: list[dict[str, Any]] = field(default_factory=list)
    visible_outputs: list[dict[str, Any]] = field(default_factory=list)
    detected_objects_or_ui_elements: list[dict[str, Any]] = field(default_factory=list)
    extracted_text: list[str] = field(default_factory=list)
    extracted_result_values: list[dict[str, Any]] = field(default_factory=list)
    workflow_interpretation: str = ""
    confidence: str = "low"          # high | medium | low
    limitations: list[str] = field(default_factory=list)
    privacy_flags: list[str] = field(default_factory=list)
    provider_used: str = "none"
    status: str = VISUAL_STATUS_NOT_CONFIGURED

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp_ms":                     self.timestamp_ms,
            "screen_summary":                   self.screen_summary,
            "visible_inputs":                   self.visible_inputs,
            "visible_outputs":                  self.visible_outputs,
            "detected_objects_or_ui_elements":  self.detected_objects_or_ui_elements,
            "extracted_text":                   self.extracted_text,
            "extracted_result_values":          self.extracted_result_values,
            "workflow_interpretation":          self.workflow_interpretation,
            "confidence":                       self.confidence,
            "limitations":                      self.limitations,
            "privacy_flags":                    self.privacy_flags,
            "provider_used":                    self.provider_used,
            "status":                           self.status,
        }


# ── Provider interface ─────────────────────────────────────────────────────────

class VisualAnalysisProvider(ABC):
    """Abstract base class for all visual analysis providers.

    Implementing a new provider:
        1. Subclass VisualAnalysisProvider
        2. Implement is_configured() — return False if packages are missing
        3. Implement analyze_frame(frame_bytes_or_path, context) → VisualFrameObservation

    is_configured() MUST NOT raise exceptions — if the required package is
    not installed, catch ImportError and return False.
    """

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True only when this provider can actually run analysis."""
        ...

    @abstractmethod
    def analyze_frame(
        self,
        frame_bytes_or_path: bytes | str,
        context: dict[str, Any] | None = None,
    ) -> VisualFrameObservation:
        """Analyze one frame.  Never raises — returns a failed/not_configured observation."""
        ...

    @property
    def provider_name(self) -> str:
        return self.__class__.__name__


# ── Provider: None (safe default) ─────────────────────────────────────────────

class NoneProvider(VisualAnalysisProvider):
    """Default provider — visual analysis disabled.

    Always returns not_configured.  Safe to use in production when no local
    model is installed.  DOM evidence continues to work.
    """

    def is_configured(self) -> bool:
        return False

    def analyze_frame(
        self,
        frame_bytes_or_path: bytes | str,
        context: dict[str, Any] | None = None,
    ) -> VisualFrameObservation:
        return VisualFrameObservation(
            status=VISUAL_STATUS_NOT_CONFIGURED,
            limitations=["Visual analysis provider is not configured (VISUAL_ANALYSIS_PROVIDER=none)."],
            provider_used="none",
        )


# ── Provider: Local OCR ────────────────────────────────────────────────────────

class LocalOCRProvider(VisualAnalysisProvider):
    """OCR-based visual analysis using PaddleOCR, EasyOCR, or Tesseract.

    Setup (choose one):
        pip install paddleocr paddlepaddle   # PaddleOCR (recommended, fast)
        pip install easyocr                  # EasyOCR (good accuracy)
        pip install pytesseract              # Tesseract (plus brew/apt install tesseract)

    Set LOCAL_OCR_PROVIDER=paddleocr|easyocr|tesseract in your .env.

    When the selected package is missing, is_configured() returns False
    and the service falls back to not_configured gracefully.
    """

    def __init__(self) -> None:
        self._backend = settings.local_ocr_provider.lower()
        self._ocr_engine: Any = None
        self._available: bool | None = None   # lazily set on first call

    def _try_init_engine(self) -> bool:
        """Attempt to initialise the OCR engine.  Returns True if successful."""
        if self._available is not None:
            return self._available

        try:
            if self._backend == "paddleocr":
                from paddleocr import PaddleOCR  # type: ignore[import]
                # use_angle_cls=True handles rotated text; lang='en' for English
                self._ocr_engine = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
                self._available = True

            elif self._backend == "easyocr":
                import easyocr  # type: ignore[import]
                self._ocr_engine = easyocr.Reader(["en"], gpu=False)
                self._available = True

            elif self._backend == "tesseract":
                import pytesseract  # type: ignore[import]
                from PIL import Image  # type: ignore[import]
                # Quick smoke-test: check tesseract binary is available
                pytesseract.get_tesseract_version()
                self._ocr_engine = pytesseract
                self._available = True

            else:
                logger.warning("[LocalOCR] Unknown LOCAL_OCR_PROVIDER=%r — falling back to not_configured", self._backend)
                self._available = False

        except ImportError as exc:
            logger.info(
                "[LocalOCR] OCR package not installed (LOCAL_OCR_PROVIDER=%r). "
                "Returning not_configured. Install with: pip install %s\n"
                "Original error: %s",
                self._backend,
                {"paddleocr": "paddleocr paddlepaddle", "easyocr": "easyocr",
                 "tesseract": "pytesseract pillow"}.get(self._backend, self._backend),
                exc,
            )
            self._available = False
        except Exception as exc:
            logger.warning("[LocalOCR] OCR engine init failed: %s", exc)
            self._available = False

        return bool(self._available)

    def is_configured(self) -> bool:
        return self._try_init_engine()

    def _run_ocr(self, image_bytes: bytes) -> list[str]:
        """Run OCR and return a list of text lines."""
        lines: list[str] = []

        try:
            if self._backend == "paddleocr":
                import numpy as np  # type: ignore[import]
                from PIL import Image  # type: ignore[import]
                img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                arr = np.array(img)
                result = self._ocr_engine.ocr(arr, cls=True)
                if result and result[0]:
                    for item in result[0]:
                        # item = [[bbox], (text, confidence)]
                        if item and len(item) == 2:
                            text_conf = item[1]
                            if text_conf and text_conf[0]:
                                lines.append(str(text_conf[0]))

            elif self._backend == "easyocr":
                import numpy as np  # type: ignore[import]
                from PIL import Image  # type: ignore[import]
                img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                arr = np.array(img)
                result = self._ocr_engine.readtext(arr, detail=0)
                lines = [str(t) for t in result]

            elif self._backend == "tesseract":
                from PIL import Image  # type: ignore[import]
                import pytesseract  # type: ignore[import]
                img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                raw = pytesseract.image_to_string(img)
                lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]

        except Exception as exc:
            logger.warning("[LocalOCR] OCR run error: %s", exc)

        return lines

    def analyze_frame(
        self,
        frame_bytes_or_path: bytes | str,
        context: dict[str, Any] | None = None,
    ) -> VisualFrameObservation:
        if not self._try_init_engine():
            return VisualFrameObservation(
                status=VISUAL_STATUS_NOT_CONFIGURED,
                limitations=[
                    f"Local OCR provider '{self._backend}' is not installed. "
                    f"Install with: pip install {self._backend}.",
                ],
                provider_used=f"local_ocr:{self._backend}",
            )

        # Resolve bytes
        try:
            if isinstance(frame_bytes_or_path, str):
                with open(frame_bytes_or_path, "rb") as fh:
                    frame_bytes: bytes = fh.read()
            else:
                frame_bytes = frame_bytes_or_path
        except Exception as exc:
            logger.warning("[LocalOCR] Could not load frame: %s", exc)
            return VisualFrameObservation(
                status=VISUAL_STATUS_FAILED,
                limitations=[f"Could not load frame: {exc}"],
                provider_used=f"local_ocr:{self._backend}",
            )

        # Run OCR
        raw_lines = self._run_ocr(frame_bytes)

        # Mask sensitive content
        cleaned_lines: list[str] = []
        all_flags: list[str] = []
        for line in raw_lines:
            cleaned, flags = _mask_sensitive_text(line)
            cleaned_lines.append(cleaned)
            all_flags.extend(flags)

        # Extract result values
        result_values = extract_result_values_from_ocr(cleaned_lines)

        # Build summary from non-empty lines (max 300 chars)
        summary_text = " | ".join(cleaned_lines[:8])[:300]

        confidence = "medium" if result_values else "low"

        return VisualFrameObservation(
            screen_summary=summary_text,
            extracted_text=cleaned_lines,
            extracted_result_values=result_values,
            confidence=confidence,
            limitations=[] if result_values else [
                "No structured result values detected in this frame via OCR.",
            ],
            privacy_flags=list(set(all_flags)),
            provider_used=f"local_ocr:{self._backend}",
            status=VISUAL_STATUS_ANALYZED,
        )


# ── Provider: Local Vision ─────────────────────────────────────────────────────

class LocalVisionProvider(VisualAnalysisProvider):
    """Local/open-source vision model provider.

    Primary targets (recommended):
        qwen_vl     — Qwen2.5-VL-7B-Instruct  (strong VQA, good CPU/GPU balance)
        qwen3_vl    — Qwen3-VL-7B-Instruct     (latest Qwen3 vision series)

    Additional supported backends:
        llava       — LLaVA-1.5-7B  (widely tested, good general VQA)
        minicpm_v   — MiniCPM-V-2.6 (compact, resource-constrained hosts)
        blip        — BLIP-2         (caption + VQA, lightweight)

    Setup — all backends:
        pip install "transformers>=4.45" torch pillow accelerate
        Set VISUAL_ANALYSIS_PROVIDER=local_vision
        Set LOCAL_VISION_PROVIDER=qwen_vl  (or qwen3_vl|llava|minicpm_v|blip)

    Qwen2.5-VL / Qwen3-VL requirement:
        transformers >= 4.45.0  (provides Qwen2_5_VLForConditionalGeneration)

    Design:
      _try_init()   verifies package importability only — never loads weights.
                    Safe and fast to call at server start / singleton creation.
      _load_model() lazy weight load on first _run_vision() call.
                    Handles MemoryError gracefully; returns FAILED on OOM.
      _run_vision() per-backend dispatch to model-specific inference methods.

    If required packages are missing, is_configured() returns False and
    analyze_frame() returns not_configured — no exception is ever raised.

    No GPU required.  CPU inference is ~10–60× slower but fully supported.
    Model weights (~2–14 GB) download on first use to ~/.cache/huggingface.
    """

    _MODEL_IDS: dict[str, str] = {
        "qwen_vl":   "Qwen/Qwen2.5-VL-7B-Instruct",
        "qwen3_vl":  "Qwen/Qwen3-VL-7B-Instruct",
        "llava":     "llava-hf/llava-1.5-7b-hf",
        "minicpm_v": "openbmb/MiniCPM-V-2_6",
        "blip":      "Salesforce/blip2-opt-2.7b",
    }

    _INSTALL_HINTS: dict[str, str] = {
        "qwen_vl":   '"transformers>=4.45" torch pillow accelerate',
        "qwen3_vl":  '"transformers>=4.45" torch pillow accelerate',
        "llava":     "transformers torch pillow accelerate",
        "minicpm_v": "transformers torch pillow accelerate",
        "blip":      "transformers torch pillow accelerate",
    }

    # Shared VQA prompt — instructs the model without domain-specific hints
    _VQA_PROMPT: str = (
        "Look at this screenshot of a web application. "
        "Describe: (1) what inputs are visible, (2) what outputs or results are shown, "
        "(3) any numbers, labels, percentages, or prediction values visible. "
        "Be concise and factual. Do not invent values not visible in the image."
    )

    def __init__(self) -> None:
        self._backend: str = settings.local_vision_provider.lower()
        self._available: bool | None = None
        # Model and processor are loaded lazily on first inference call
        self._model: Any = None
        self._processor: Any = None

    # ── Init: package-importability check (fast, no weight loading) ──────────────

    def _try_init(self) -> bool:
        """Verify that backend-specific packages can be imported.

        Does NOT load model weights — just checks that the Python packages
        are installed.  Safe to call at startup.  Returns True only when
        the correct packages are present.
        """
        if self._available is not None:
            return self._available

        model_id = self._MODEL_IDS.get(self._backend)
        if not model_id:
            logger.warning(
                "[LocalVision] Unknown LOCAL_VISION_PROVIDER=%r.  "
                "Valid values: %s",
                self._backend, ", ".join(self._MODEL_IDS),
            )
            self._available = False
            return False

        try:
            import torch  # type: ignore[import]  # noqa: F401
            from PIL import Image  # type: ignore[import]  # noqa: F401

            if self._backend in ("qwen_vl", "qwen3_vl"):
                # Qwen2.5-VL / Qwen3-VL require transformers >= 4.45
                from transformers import (  # type: ignore[import]  # noqa: F401
                    Qwen2_5_VLForConditionalGeneration,
                    AutoProcessor,
                )
            elif self._backend == "llava":
                from transformers import (  # type: ignore[import]  # noqa: F401
                    LlavaForConditionalGeneration,
                    AutoProcessor,
                )
            elif self._backend == "minicpm_v":
                from transformers import AutoModel, AutoTokenizer  # type: ignore[import]  # noqa: F401
            elif self._backend == "blip":
                from transformers import (  # type: ignore[import]  # noqa: F401
                    Blip2ForConditionalGeneration,
                    Blip2Processor,
                )
            else:
                logger.warning("[LocalVision] No import path for backend %r", self._backend)
                self._available = False
                return False

            logger.info(
                "[LocalVision] Backend %r packages verified.  "
                "Model weights (%s) download on first inference (~2–14 GB).  "
                "GPU recommended; CPU supported.",
                self._backend, model_id,
            )
            self._available = True

        except ImportError as exc:
            logger.info(
                "[LocalVision] Required packages missing for backend %r.  "
                "Install: pip install %s\n  Error: %s",
                self._backend,
                self._INSTALL_HINTS.get(
                    self._backend, "transformers torch pillow accelerate"
                ),
                exc,
            )
            self._available = False
        except Exception as exc:
            logger.warning("[LocalVision] Init check failed for %r: %s", self._backend, exc)
            self._available = False

        return bool(self._available)

    def is_configured(self) -> bool:
        return self._try_init()

    # ── Lazy model loading ────────────────────────────────────────────────────────

    def _load_model(self) -> bool:
        """Load model weights on first inference call.

        Returns True if already loaded or loads successfully.
        Handles MemoryError and other load failures — returns False and logs.
        """
        if self._model is not None:
            return True

        model_id = self._MODEL_IDS.get(self._backend, "")

        try:
            import torch  # type: ignore[import]
            device = "cuda" if torch.cuda.is_available() else "cpu"
            # float16 on GPU (speed/VRAM), float32 on CPU (numerical stability)
            dtype = torch.float16 if device == "cuda" else torch.float32

            if self._backend in ("qwen_vl", "qwen3_vl"):
                self._load_qwen_vl(model_id, device)
            elif self._backend == "llava":
                self._load_llava(model_id, device, dtype)
            elif self._backend == "minicpm_v":
                self._load_minicpm_v(model_id, device, dtype)
            elif self._backend == "blip":
                self._load_blip(model_id, device, dtype)
            else:
                logger.warning("[LocalVision] No loader for backend %r", self._backend)
                return False

            logger.info(
                "[LocalVision] %r loaded (device=%s model=%s).",
                self._backend, device, model_id,
            )
            return True

        except MemoryError:
            logger.warning(
                "[LocalVision] Out of memory loading %r (%s).  "
                "Try a smaller model or reduce MAX_WORKFLOW_FRAMES.",
                self._backend, model_id,
            )
            self._model = None
            self._processor = None
            return False
        except Exception as exc:
            logger.warning(
                "[LocalVision] Model load failed for %r: %s", self._backend, exc
            )
            self._model = None
            self._processor = None
            return False

    def _load_qwen_vl(self, model_id: str, device: str) -> None:
        from transformers import (  # type: ignore[import]
            Qwen2_5_VLForConditionalGeneration,
            AutoProcessor,
        )
        logger.info("[LocalVision] Loading Qwen VL model from %s …", model_id)
        self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            model_id,
            torch_dtype="auto",
            device_map="auto" if device == "cuda" else "cpu",
        )
        self._processor = AutoProcessor.from_pretrained(model_id)

    def _load_llava(self, model_id: str, device: str, dtype: Any) -> None:
        from transformers import (  # type: ignore[import]
            LlavaForConditionalGeneration,
            AutoProcessor,
        )
        logger.info("[LocalVision] Loading LLaVA model from %s …", model_id)
        self._model = LlavaForConditionalGeneration.from_pretrained(
            model_id, torch_dtype=dtype
        )
        if device == "cuda":
            self._model = self._model.to(device)
        self._processor = AutoProcessor.from_pretrained(model_id)

    def _load_minicpm_v(self, model_id: str, device: str, dtype: Any) -> None:
        from transformers import AutoModel, AutoTokenizer  # type: ignore[import]
        logger.info("[LocalVision] Loading MiniCPM-V model from %s …", model_id)
        self._model = AutoModel.from_pretrained(
            model_id,
            trust_remote_code=True,
            torch_dtype=dtype,
            device_map="auto" if device == "cuda" else "cpu",
        )
        self._model.eval()
        self._processor = AutoTokenizer.from_pretrained(
            model_id, trust_remote_code=True
        )

    def _load_blip(self, model_id: str, device: str, dtype: Any) -> None:
        from transformers import (  # type: ignore[import]
            Blip2ForConditionalGeneration,
            Blip2Processor,
        )
        logger.info("[LocalVision] Loading BLIP-2 model from %s …", model_id)
        self._model = Blip2ForConditionalGeneration.from_pretrained(
            model_id, torch_dtype=dtype
        )
        if device == "cuda":
            self._model = self._model.to(device)
        self._processor = Blip2Processor.from_pretrained(model_id)

    # ── Per-backend inference methods ─────────────────────────────────────────────

    def _run_vision(self, frame_bytes: bytes) -> str:
        """Run per-backend VQA inference.

        Returns a non-empty description string on success, "" on any failure.
        Never raises — all exceptions are caught and logged.
        """
        if not self._load_model():
            return ""

        try:
            from PIL import Image  # type: ignore[import]
            img = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
        except Exception as exc:
            logger.warning("[LocalVision] Could not decode image bytes: %s", exc)
            return ""

        try:
            if self._backend in ("qwen_vl", "qwen3_vl"):
                return self._infer_qwen_vl(img)
            elif self._backend == "llava":
                return self._infer_llava(img)
            elif self._backend == "minicpm_v":
                return self._infer_minicpm_v(img)
            elif self._backend == "blip":
                return self._infer_blip(img)
            else:
                return ""
        except Exception as exc:
            logger.warning(
                "[LocalVision] Inference error for backend %r: %s", self._backend, exc
            )
            return ""

    def _infer_qwen_vl(self, img: Any) -> str:
        """Qwen2.5-VL / Qwen3-VL: chat-message format + AutoProcessor."""
        import torch  # type: ignore[import]

        # Qwen VL chat template: list of content items per turn
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": img},
                    {"type": "text",  "text":  self._VQA_PROMPT},
                ],
            }
        ]

        # apply_chat_template adds <|im_start|>/<|im_end|> tokens
        text = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

        # Encode text + image together
        inputs = self._processor(
            text=[text],
            images=[img],
            padding=True,
            return_tensors="pt",
        )
        inputs = inputs.to(self._model.device)

        with torch.no_grad():
            generated_ids = self._model.generate(
                **inputs,
                max_new_tokens=256,
                do_sample=False,
            )

        # Trim the prompt tokens — keep only the newly generated tokens
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

    def _infer_llava(self, img: Any) -> str:
        """LLaVA-1.5: USER/<image>/ASSISTANT prompt format."""
        import torch  # type: ignore[import]

        full_prompt = f"USER: <image>\n{self._VQA_PROMPT}\nASSISTANT:"
        inputs = self._processor(text=full_prompt, images=img, return_tensors="pt")
        inputs = {k: v.to(self._model.device) for k, v in inputs.items()}

        with torch.no_grad():
            output = self._model.generate(
                **inputs,
                max_new_tokens=256,
                do_sample=False,
            )

        # Slice off input tokens → return only the generated response
        input_len = inputs["input_ids"].shape[1]
        text = self._processor.decode(
            output[0][input_len:], skip_special_tokens=True
        )
        return text.strip()

    def _infer_minicpm_v(self, img: Any) -> str:
        """MiniCPM-V: model.chat() API with image in content list."""
        msgs = [{"role": "user", "content": [img, self._VQA_PROMPT]}]
        result = self._model.chat(
            image=None,          # image embedded in msgs[0]["content"]
            msgs=msgs,
            tokenizer=self._processor,
        )
        return str(result).strip() if result else ""

    def _infer_blip(self, img: Any) -> str:
        """BLIP-2: Blip2ForConditionalGeneration VQA."""
        import torch  # type: ignore[import]

        inputs = self._processor(
            images=img,
            text=self._VQA_PROMPT,
            return_tensors="pt",
        )
        inputs = {k: v.to(self._model.device) for k, v in inputs.items()}

        with torch.no_grad():
            output = self._model.generate(
                **inputs,
                max_new_tokens=256,
                do_sample=False,
            )
        text = self._processor.decode(output[0], skip_special_tokens=True)
        return text.strip()

    # ── Public API ────────────────────────────────────────────────────────────────

    def analyze_frame(
        self,
        frame_bytes_or_path: bytes | str,
        context: dict[str, Any] | None = None,
    ) -> VisualFrameObservation:
        if not self._try_init():
            hint = self._INSTALL_HINTS.get(
                self._backend, "transformers torch pillow accelerate"
            )
            return VisualFrameObservation(
                status=VISUAL_STATUS_NOT_CONFIGURED,
                limitations=[
                    f"Local vision provider '{self._backend}' packages are not installed.  "
                    f"Install: pip install {hint}",
                ],
                provider_used=f"local_vision:{self._backend}",
            )

        try:
            if isinstance(frame_bytes_or_path, str):
                with open(frame_bytes_or_path, "rb") as fh:
                    frame_bytes: bytes = fh.read()
            else:
                frame_bytes = frame_bytes_or_path
        except Exception as exc:
            return VisualFrameObservation(
                status=VISUAL_STATUS_FAILED,
                limitations=[f"Could not load frame: {exc}"],
                provider_used=f"local_vision:{self._backend}",
            )

        description = self._run_vision(frame_bytes)
        if not description:
            return VisualFrameObservation(
                status=VISUAL_STATUS_FAILED,
                limitations=[
                    "Vision model returned empty output.  "
                    "Check that model weights are downloaded and device has sufficient memory."
                ],
                provider_used=f"local_vision:{self._backend}",
            )

        cleaned, flags = _mask_sensitive_text(description)
        result_values = extract_result_values_from_ocr([cleaned])

        return VisualFrameObservation(
            screen_summary=cleaned[:500],
            extracted_text=[cleaned],
            extracted_result_values=result_values,
            workflow_interpretation=cleaned[:300],
            confidence="medium",
            limitations=[],
            privacy_flags=flags,
            provider_used=f"local_vision:{self._backend}",
            status=VISUAL_STATUS_ANALYZED,
        )


# ── Provider: OpenAI Vision (optional cloud) ──────────────────────────────────

class OpenAIVisionProvider(VisualAnalysisProvider):
    """OpenAI Vision API — cloud fallback, optional.

    Requires:
        pip install openai
        OPENAI_API_KEY=sk-...

    Used only when VISUAL_ANALYSIS_PROVIDER=openai.
    """

    _SYSTEM_PROMPT = (
        "You are a visual analysis assistant for VeriBridge AI. "
        "Analyze a screenshot of a web application. "
        "Identify: inputs provided, outputs or results shown, any numbers/labels/percentages. "
        "Be concise and factual. Do not invent values that are not visible."
    )

    def __init__(self) -> None:
        self._client: Any = None
        self._available: bool | None = None

    def _try_init(self) -> bool:
        if self._available is not None:
            return self._available
        api_key = settings.openai_api_key.get_secret_value()
        if not api_key:
            logger.info("[OpenAIVision] OPENAI_API_KEY not set — provider unavailable.")
            self._available = False
            return False
        try:
            from openai import OpenAI  # type: ignore[import]
            self._client = OpenAI(api_key=api_key)
            self._available = True
        except ImportError as exc:
            logger.info("[OpenAIVision] openai package not installed. pip install openai. %s", exc)
            self._available = False
        except Exception as exc:
            logger.warning("[OpenAIVision] Init failed: %s", exc)
            self._available = False
        return bool(self._available)

    def is_configured(self) -> bool:
        return self._try_init()

    def analyze_frame(
        self,
        frame_bytes_or_path: bytes | str,
        context: dict[str, Any] | None = None,
    ) -> VisualFrameObservation:
        if not self._try_init():
            return VisualFrameObservation(
                status=VISUAL_STATUS_NOT_CONFIGURED,
                limitations=["OpenAI Vision provider is not configured (OPENAI_API_KEY missing or openai package not installed)."],
                provider_used="openai_vision",
            )
        try:
            if isinstance(frame_bytes_or_path, str):
                with open(frame_bytes_or_path, "rb") as fh:
                    frame_bytes: bytes = fh.read()
            else:
                frame_bytes = frame_bytes_or_path

            b64 = base64.b64encode(frame_bytes).decode()
            response = self._client.chat.completions.create(
                model="gpt-4o",
                max_tokens=400,
                messages=[
                    {"role": "system", "content": self._SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                            {"type": "text", "text": "Describe the inputs and outputs visible in this screenshot."},
                        ],
                    },
                ],
            )
            description = response.choices[0].message.content or ""
        except Exception as exc:
            logger.warning("[OpenAIVision] API call failed: %s", exc)
            return VisualFrameObservation(
                status=VISUAL_STATUS_FAILED,
                limitations=[f"OpenAI Vision API error: {exc}"],
                provider_used="openai_vision",
            )

        cleaned, flags = _mask_sensitive_text(description)
        result_values = extract_result_values_from_ocr([cleaned])

        return VisualFrameObservation(
            screen_summary=cleaned[:500],
            extracted_text=[cleaned],
            extracted_result_values=result_values,
            workflow_interpretation=cleaned[:300],
            confidence="high",
            limitations=[],
            privacy_flags=flags,
            provider_used="openai_vision",
            status=VISUAL_STATUS_ANALYZED,
        )


# ── Provider: VeriBridge Future ────────────────────────────────────────────────

class VeriBridgeFutureProvider(VisualAnalysisProvider):
    """Placeholder for the future VeriBridge fine-tuned visual model.

    Currently always returns not_configured with a clear message.
    This stub exists so the architecture is wired up and ready.
    """

    def is_configured(self) -> bool:
        return False

    def analyze_frame(
        self,
        frame_bytes_or_path: bytes | str,
        context: dict[str, Any] | None = None,
    ) -> VisualFrameObservation:
        return VisualFrameObservation(
            status=VISUAL_STATUS_NOT_CONFIGURED,
            limitations=["VeriBridge fine-tuned visual model is not yet available."],
            provider_used="veribridge_future",
        )


# ── Provider factory ───────────────────────────────────────────────────────────

def get_visual_provider() -> VisualAnalysisProvider:
    """Instantiate and return the configured visual analysis provider.

    Never raises.  If the configured provider's packages are missing,
    returns NoneProvider (safe default) with a logged warning.

    Environment variable: VISUAL_ANALYSIS_PROVIDER=none|local_ocr|local_vision|openai|veribridge_future
    """
    provider_name = settings.visual_analysis_provider.lower().strip()

    _PROVIDERS: dict[str, type[VisualAnalysisProvider]] = {
        "none":             NoneProvider,
        "local_ocr":        LocalOCRProvider,
        "local_vision":     LocalVisionProvider,
        "openai":           OpenAIVisionProvider,
        "veribridge_future": VeriBridgeFutureProvider,
    }

    cls = _PROVIDERS.get(provider_name)
    if cls is None:
        logger.warning(
            "[VisualAnalysis] Unknown VISUAL_ANALYSIS_PROVIDER=%r; defaulting to NoneProvider. "
            "Valid values: %s",
            provider_name, ", ".join(_PROVIDERS),
        )
        return NoneProvider()

    return cls()


# ── Module-level singleton (lazy) ──────────────────────────────────────────────
# One provider instance is shared across requests to avoid re-loading models.
_PROVIDER_SINGLETON: VisualAnalysisProvider | None = None


def _get_provider_singleton() -> VisualAnalysisProvider:
    global _PROVIDER_SINGLETON
    if _PROVIDER_SINGLETON is None:
        _PROVIDER_SINGLETON = get_visual_provider()
    return _PROVIDER_SINGLETON


# ── Module-level DB helpers ────────────────────────────────────────────────────

def _count_stored_frames(db: Any, user_id: str, session_id: str) -> int:
    """Count every stored frame for a session, regardless of analysis status.

    Used to populate visual_frames_stored in the analysis result, which lets
    the UI distinguish "frames captured but OCR not configured" from "no frames at all".
    """
    try:
        resp = (
            db.table(_TABLE)
            .select("id")
            .eq("user_id", user_id)
            .eq("proof_session_id", session_id)
            .execute()
        )
        return len(resp.data or [])
    except Exception:
        return 0


# ── Service ────────────────────────────────────────────────────────────────────

class WorkflowVisualAnalysisService:
    """Main service for visual frame storage and analysis.

    Usage:
        svc = WorkflowVisualAnalysisService(db_client)

        # Store a raw frame from the extension
        frame_id = svc.store_visual_frame(
            user_id="...",
            session_id="...",
            frame_type="after_click",
            frame_bytes=b"...",
            timestamp_ms=1234,
        )

        # Analyze a stored frame
        obs = svc.analyze_visual_frame(frame_id, user_id)

        # Analyze all pending frames for a session
        summary = svc.analyze_frames_for_session(user_id, session_id)

        # Get visual summary for workflow analysis integration
        obs_list = svc.get_visual_observations(user_id, session_id)
    """

    def __init__(self, db: Any) -> None:
        self._db = db
        self._provider = _get_provider_singleton()

    # ── Status ──────────────────────────────────────────────────────────────

    def get_provider_status(self) -> dict[str, Any]:
        """Return provider configuration status for frontend display."""
        provider = self._provider
        is_configured = provider.is_configured()

        provider_name = settings.visual_analysis_provider.lower()
        ocr_provider = settings.local_ocr_provider if provider_name == "local_ocr" else None
        vision_provider = settings.local_vision_provider if provider_name == "local_vision" else None

        return {
            "visual_analysis_provider": provider_name,
            "provider_configured": is_configured,
            "frame_capture_enabled": settings.enable_workflow_frame_capture,
            "max_frames": settings.max_workflow_frames,
            "local_ocr_provider": ocr_provider,
            "local_vision_provider": vision_provider,
        }

    # ── Store ────────────────────────────────────────────────────────────────

    def store_visual_frame(
        self,
        user_id: str,
        session_id: str,
        frame_type: str,
        frame_bytes: bytes | None = None,
        frame_base64: str | None = None,
        timestamp_ms: int | None = None,
        frame_width: int | None = None,
        frame_height: int | None = None,
        visible_evidence_event_id: str | None = None,
    ) -> str:
        """Store a raw frame record.  Returns the new frame row id.

        The frame is stored as pending — call analyze_visual_frame() to run
        actual analysis, or analyze_frames_for_session() to batch-analyze.

        Privacy: frame_bytes are NOT stored in the database row.  If storage
        integration (Supabase Storage) is added, the storage path goes in
        frame_storage_path.  This method stores metadata only.
        """
        if not settings.enable_workflow_frame_capture:
            # Frame capture disabled — still create a record with not_configured
            pass

        # Decode base64 if needed (for frame size info)
        if frame_bytes is None and frame_base64:
            try:
                frame_bytes = base64.b64decode(frame_base64)
            except Exception:
                frame_bytes = None

        # Derive dimensions from image if not provided
        if frame_bytes and (frame_width is None or frame_height is None):
            try:
                from PIL import Image  # type: ignore[import]
                img = Image.open(io.BytesIO(frame_bytes))
                frame_width, frame_height = img.size
            except Exception:
                pass

        # Set the initial status based on whether the provider is configured.
        # Not-configured frames are immediately marked so get_visual_observations()
        # can distinguish "frames stored but no provider" from "no frames at all".
        provider = _get_provider_singleton()
        initial_status = (
            VISUAL_STATUS_PENDING
            if provider.is_configured()
            else VISUAL_STATUS_NOT_CONFIGURED
        )

        row: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "proof_session_id": session_id,
            "timestamp_ms": timestamp_ms,
            "frame_type": frame_type,
            "frame_width": frame_width,
            "frame_height": frame_height,
            "visual_analysis_provider": settings.visual_analysis_provider,
            "visual_analysis_status": initial_status,
            "ocr_text": [],
            "visual_objects": [],
            "extracted_result_values": [],
            "privacy_flags": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if visible_evidence_event_id:
            row["visible_evidence_event_id"] = visible_evidence_event_id

        try:
            self._db.table(_TABLE).insert(row).execute()
        except Exception as exc:
            logger.warning("[VisualAnalysis] Failed to store frame record: %s", exc)

        return row["id"]

    # ── Analyse a single frame ───────────────────────────────────────────────

    def analyze_visual_frame(
        self,
        frame_id: str,
        user_id: str,
        frame_bytes: bytes | None = None,
    ) -> VisualFrameObservation:
        """Run visual analysis on a stored frame record.

        frame_bytes: the raw image bytes (if not yet stored in blob storage).
        """
        provider = self._provider

        if not provider.is_configured():
            # Update row to not_configured
            try:
                self._db.table(_TABLE).update({
                    "visual_analysis_status": VISUAL_STATUS_NOT_CONFIGURED,
                    "analyzed_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", frame_id).eq("user_id", user_id).execute()
            except Exception:
                pass
            return VisualFrameObservation(
                status=VISUAL_STATUS_NOT_CONFIGURED,
                limitations=[
                    "Visual analysis provider is not configured. "
                    "DOM evidence is still used for workflow analysis.",
                ],
                provider_used=settings.visual_analysis_provider,
            )

        if frame_bytes is None:
            # No bytes provided and no storage integration yet
            try:
                self._db.table(_TABLE).update({
                    "visual_analysis_status": VISUAL_STATUS_SKIPPED,
                    "analyzed_at": datetime.now(timezone.utc).isoformat(),
                    "visual_summary": "Frame bytes not available for analysis.",
                }).eq("id", frame_id).eq("user_id", user_id).execute()
            except Exception:
                pass
            return VisualFrameObservation(
                status=VISUAL_STATUS_SKIPPED,
                limitations=["Frame bytes not available for analysis."],
                provider_used=provider.provider_name,
            )

        observation = provider.analyze_frame(frame_bytes)

        # Persist results
        try:
            self._db.table(_TABLE).update({
                "visual_analysis_status": observation.status,
                "visual_analysis_provider": observation.provider_used,
                "ocr_text": [{"text": t} for t in observation.extracted_text],
                "visual_objects": observation.detected_objects_or_ui_elements,
                "visual_summary": observation.screen_summary,
                "extracted_result_values": observation.extracted_result_values,
                "privacy_flags": observation.privacy_flags,
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", frame_id).eq("user_id", user_id).execute()
        except Exception as exc:
            logger.warning("[VisualAnalysis] Failed to persist analysis: %s", exc)

        return observation

    # ── Batch analysis ───────────────────────────────────────────────────────

    def analyze_frames_for_session(
        self,
        user_id: str,
        session_id: str,
        frame_bytes_map: dict[str, bytes] | None = None,
    ) -> dict[str, Any]:
        """Analyze all pending frames for a proof session.

        frame_bytes_map: optional {frame_id: bytes} if frames were submitted
                         in-memory (before storage integration).

        Returns a summary dict for integration with workflow analysis.
        """
        frame_bytes_map = frame_bytes_map or {}
        provider = self._provider

        if not provider.is_configured():
            return {
                "visual_frame_analysis_status": VISUAL_STATUS_NOT_CONFIGURED,
                "frames_analyzed": 0,
                "extracted_result_values": [],
                "visual_summary": "",
                "provider_used": settings.visual_analysis_provider,
                "limitations": [
                    "Visual frame analysis is not configured. "
                    "Set VISUAL_ANALYSIS_PROVIDER and install the required packages. "
                    "DOM evidence is still used for workflow analysis."
                ],
            }

        # Fetch pending frames
        try:
            resp = (
                self._db.table(_TABLE)
                .select("id, frame_type, timestamp_ms, visual_analysis_status")
                .eq("user_id", user_id)
                .eq("proof_session_id", session_id)
                .eq("visual_analysis_status", VISUAL_STATUS_PENDING)
                .order("timestamp_ms", desc=False)
                .limit(settings.max_workflow_frames)
                .execute()
            )
            pending_rows: list[dict[str, Any]] = resp.data or []
        except Exception as exc:
            logger.warning("[VisualAnalysis] Failed to fetch pending frames: %s", exc)
            pending_rows = []

        all_result_values: list[dict[str, Any]] = []
        all_summaries: list[str] = []
        analyzed_count = 0

        for row in pending_rows:
            frame_id = row["id"]
            fb = frame_bytes_map.get(frame_id)
            obs = self.analyze_visual_frame(frame_id, user_id, frame_bytes=fb)
            if obs.status == VISUAL_STATUS_ANALYZED:
                analyzed_count += 1
                all_result_values.extend(obs.extracted_result_values)
                if obs.screen_summary:
                    all_summaries.append(obs.screen_summary)

        # Deduplicate result values
        seen: set[str] = set()
        unique_values: list[dict[str, Any]] = []
        for rv in all_result_values:
            key = f"{rv.get('label', '').lower()}:{rv.get('value', '')}"
            if key not in seen:
                seen.add(key)
                unique_values.append(rv)

        combined_summary = " | ".join(all_summaries[:4])[:600]

        return {
            "visual_frame_analysis_status": VISUAL_STATUS_ANALYZED if analyzed_count > 0 else VISUAL_STATUS_SKIPPED,
            "frames_analyzed": analyzed_count,
            "frames_pending": len(pending_rows) - analyzed_count,
            "extracted_result_values": unique_values,
            "visual_summary": combined_summary,
            "provider_used": settings.visual_analysis_provider,
            "limitations": [],
        }

    # ── Count all stored frames ──────────────────────────────────────────────

    def count_stored_frames(self, user_id: str, session_id: str) -> int:
        """Count every stored frame for a session, regardless of analysis status."""
        return _count_stored_frames(self._db, user_id, session_id)

    # ── Get observations for workflow analysis integration ───────────────────

    def get_visual_observations(
        self,
        user_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        """Fetch analyzed visual evidence for a session (for workflow analysis merge).

        Returns a dict compatible with the workflow analysis result builder.
        """
        try:
            resp = (
                self._db.table(_TABLE)
                .select(
                    "id, frame_type, timestamp_ms, visual_analysis_status, "
                    "ocr_text, visual_objects, visual_summary, extracted_result_values"
                )
                .eq("user_id", user_id)
                .eq("proof_session_id", session_id)
                .eq("visual_analysis_status", VISUAL_STATUS_ANALYZED)
                .order("timestamp_ms", desc=False)
                .execute()
            )
            rows: list[dict[str, Any]] = resp.data or []
        except Exception as exc:
            logger.warning("[VisualAnalysis] Failed to fetch observations: %s", exc)
            rows = []

        if not rows:
            # Check if any frames exist at all (to distinguish not_configured vs no frames)
            try:
                any_resp = (
                    self._db.table(_TABLE)
                    .select("id, visual_analysis_status")
                    .eq("user_id", user_id)
                    .eq("proof_session_id", session_id)
                    .limit(1)
                    .execute()
                )
                any_rows = any_resp.data or []
            except Exception:
                any_rows = []

            if not any_rows:
                status = "not_captured"
                stored_count = 0
            else:
                any_status = any_rows[0].get("visual_analysis_status", "")
                stored_count = _count_stored_frames(self._db, user_id, session_id)
                if any_status == VISUAL_STATUS_NOT_CONFIGURED:
                    status = VISUAL_STATUS_NOT_CONFIGURED
                else:
                    status = VISUAL_STATUS_SKIPPED

            return {
                "visual_frame_count": 0,          # analyzed frames (0 here)
                "visual_frames_stored": stored_count,  # total stored frames
                "visual_frame_analysis_status": status,
                "extracted_result_values": [],
                "visual_summary": "",
                "provider_used": settings.visual_analysis_provider,
            }

        all_result_values: list[dict[str, Any]] = []
        all_summaries: list[str] = []

        for row in rows:
            rvs = row.get("extracted_result_values") or []
            if isinstance(rvs, list):
                all_result_values.extend(rvs)
            summary = row.get("visual_summary") or ""
            if summary:
                all_summaries.append(summary)

        # Deduplicate
        seen: set[str] = set()
        unique_values: list[dict[str, Any]] = []
        for rv in all_result_values:
            key = f"{rv.get('label', '').lower()}:{rv.get('value', '')}"
            if key not in seen:
                seen.add(key)
                unique_values.append(rv)

        return {
            "visual_frame_count": len(rows),
            "visual_frames_stored": _count_stored_frames(self._db, user_id, session_id),
            "visual_frame_analysis_status": VISUAL_STATUS_ANALYZED,
            "extracted_result_values": unique_values,
            "visual_summary": " | ".join(all_summaries[:4])[:600],
            "provider_used": settings.visual_analysis_provider,
        }

    # ── Build workflow summary ────────────────────────────────────────────────

    def build_visual_workflow_summary(
        self,
        user_id: str,
        session_id: str,
        dom_result_values: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Merge visual frame evidence with DOM evidence.

        Evidence priority:
          1. DOM exact result values (highest confidence)
          2. Local OCR exact result values
          3. Local vision frame summaries
          4. (Browser events — handled by workflow analysis service)

        Returns a merged evidence dict for workflow analysis consumption.
        """
        dom_values = dom_result_values or []
        visual_obs = self.get_visual_observations(user_id, session_id)
        ocr_values = visual_obs.get("extracted_result_values", [])

        # Merge: DOM values take priority over visual/OCR values
        dom_labels = {v.get("label", "").lower() for v in dom_values}
        merged: list[dict[str, Any]] = list(dom_values)

        for rv in ocr_values:
            label = rv.get("label", "").lower()
            if label not in dom_labels:
                # Add with source tag
                merged.append({**rv, "source": rv.get("source", "ocr")})

        return {
            "merged_result_values": merged,
            "dom_result_count": len(dom_values),
            "ocr_result_count": len(ocr_values),
            "visual_frame_count": visual_obs.get("visual_frame_count", 0),
            "visual_frame_analysis_status": visual_obs.get("visual_frame_analysis_status", "not_captured"),
            "visual_summary": visual_obs.get("visual_summary", ""),
            "provider_used": visual_obs.get("provider_used", "none"),
        }
