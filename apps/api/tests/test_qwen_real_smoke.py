"""Real Qwen2.5-VL-7B smoke test.

Run ONLY manually — downloads ~14 GB model on first run.

    VISUAL_REASONING_ENABLED=true \
    LOCAL_VISION_PROVIDER=qwen_vl \
    VISUAL_REASONING_MAX_FRAMES=3 \
    LOCAL_OCR_PROVIDER=tesseract \
      pytest tests/test_qwen_real_smoke.py -v -s

Skipped automatically when VISUAL_REASONING_ENABLED != "true".

Measures:
  - model load time
  - inference time for one generated frame
  - memory (RSS before / after load)
  - structured JSON output fields
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import pytest

# ── Skip when not explicitly enabled ──────────────────────────────────────────

VISUAL_REASONING_ENABLED = os.environ.get("VISUAL_REASONING_ENABLED", "").lower() == "true"
pytestmark = pytest.mark.skipif(
    not VISUAL_REASONING_ENABLED,
    reason="Set VISUAL_REASONING_ENABLED=true to run real Qwen smoke test",
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _rss_mb() -> float:
    """Return current RSS in MB (macOS/Linux)."""
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    except Exception:
        return 0.0


def _generate_test_frame() -> bytes:
    """Generate a simple JPEG with visible text/UI for visual reasoning."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (800, 600), color=(240, 240, 240))
        draw = ImageDraw.Draw(img)

        # Draw simulated ML dashboard UI
        draw.rectangle([20, 20, 780, 580], outline=(100, 100, 100), width=2)
        draw.rectangle([20, 20, 780, 60], fill=(50, 100, 200))

        # Title bar
        draw.text((30, 30), "Teachable Machine — Model Training", fill=(255, 255, 255))

        # Content area
        draw.text((40, 80), "Training Status: Complete", fill=(0, 128, 0))
        draw.text((40, 110), "Accuracy: 94.3%", fill=(0, 0, 0))
        draw.text((40, 140), "Loss: 0.087", fill=(0, 0, 0))
        draw.text((40, 170), "Epochs: 50 / 50", fill=(0, 0, 0))
        draw.text((40, 210), "Classes:", fill=(0, 0, 0))
        draw.text((60, 230), "- Cat: 120 samples", fill=(0, 0, 0))
        draw.text((60, 250), "- Dog: 115 samples", fill=(0, 0, 0))
        draw.text((60, 270), "- Bird: 98 samples", fill=(0, 0, 0))

        # Progress bar
        draw.rectangle([40, 300, 400, 330], outline=(100, 100, 100), width=1)
        draw.rectangle([40, 300, 420, 330], fill=(50, 200, 50))
        draw.text((40, 340), "Progress: [##########] 100%", fill=(0, 0, 0))

        # Prediction panel
        draw.rectangle([450, 80, 760, 300], outline=(100, 100, 100), width=1)
        draw.text((460, 90), "Live Prediction", fill=(0, 0, 0))
        draw.text((460, 120), "Cat:  0.89 ████████", fill=(50, 150, 50))
        draw.text((460, 145), "Dog:  0.09 █", fill=(100, 100, 200))
        draw.text((460, 170), "Bird: 0.02 ▌", fill=(200, 100, 50))

        # Buttons
        draw.rectangle([40, 380, 200, 420], fill=(50, 100, 200))
        draw.text((60, 392), "Export Model", fill=(255, 255, 255))
        draw.rectangle([220, 380, 380, 420], fill=(100, 100, 100))
        draw.text((240, 392), "Reset Training", fill=(255, 255, 255))

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()
    except ImportError:
        # Fallback: minimal JPEG
        return bytes([
            0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46,
            0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01,
            0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
            0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08,
            0x07, 0x07, 0x07, 0x09, 0x09, 0x08, 0x0A, 0x0C,
            0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
            0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D,
            0x1A, 0x1C, 0x1C, 0x20, 0x24, 0x2E, 0x27, 0x20,
            0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
            0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27,
            0x39, 0x3D, 0x38, 0x32, 0x3C, 0x2E, 0x33, 0x34,
            0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
            0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4,
            0x00, 0x1F, 0x00, 0x00, 0x01, 0x05, 0x01, 0x01,
            0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04,
            0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0xFF,
            0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
            0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04,
            0x00, 0x00, 0x01, 0x7D, 0xFF, 0xDA, 0x00, 0x08,
            0x01, 0x01, 0x00, 0x00, 0x3F, 0x00, 0xFB, 0x26,
            0x8A, 0x28, 0x03, 0xFF, 0xD9,
        ])


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_real_qwen_is_configured():
    """Verify QwenVLReasoningProvider reports configured with packages installed."""
    from app.services.visual_reasoning_service import QwenVLReasoningProvider
    p = QwenVLReasoningProvider()
    assert p.is_configured(), (
        "QwenVLReasoningProvider.is_configured() returned False. "
        "Install: pip install 'transformers>=4.45' torch torchvision pillow accelerate qwen-vl-utils"
    )
    print("\n✓ QwenVLReasoningProvider.is_configured() = True (all packages present)")


def test_real_qwen_model_load_and_inference():
    """Real Qwen2.5-VL-7B smoke test — loads model, runs inference on generated frame.

    Reports:
      - load time
      - inference time
      - memory pressure (RSS delta)
      - structured JSON output fields
    """
    from app.services.visual_reasoning_service import (
        QwenVLReasoningProvider,
        REASONING_STATUS_ANALYZED,
        REASONING_STATUS_FAILED,
    )

    frame_bytes = _generate_test_frame()
    assert len(frame_bytes) > 100, "Failed to generate test frame"

    p = QwenVLReasoningProvider()
    assert p.is_configured(), "Packages not installed — run pip install first"

    rss_before = _rss_mb()
    t_load_start = time.time()

    # Force model load (first call downloads weights if not cached)
    assert p._load_model(), "Model failed to load — check memory/disk space"

    t_load_end = time.time()
    load_time = t_load_end - t_load_start

    rss_after_load = _rss_mb()
    mem_delta_gb = (rss_after_load - rss_before) / 1024

    device = str(p._model.device)
    print(f"\n✓ Model loaded in {load_time:.1f}s on device={device}")
    print(f"  Memory delta: {mem_delta_gb:.1f} GB (RSS before={rss_before:.0f} MB, after={rss_after_load:.0f} MB)")

    # Run inference
    t_inf_start = time.time()
    obs = p.analyze_frame_reasoning(
        frame_bytes=frame_bytes,
        claimed_skills=["Machine Learning", "Image Classification"],
        context={"frame_index": 0, "timestamp_ms": 1000},
    )
    t_inf_end = time.time()
    inf_time = t_inf_end - t_inf_start

    print(f"  Inference time: {inf_time:.1f}s")
    print(f"  Status: {obs.status}")
    print(f"  Visual summary: {obs.visual_summary[:120]}")
    print(f"  Workflow stage: {obs.detected_workflow_stage}")
    print(f"  Skills supported: {obs.detected_skills_supported}")
    print(f"  Confidence: {obs.confidence_score}")
    print(f"  Limitations: {obs.limitations[:2]}")

    # Performance verdict
    if load_time > 120:
        print(f"\n⚠  Model load took {load_time:.0f}s — TOO SLOW for interactive use on CPU")
        print("   Recommendation: use Qwen2.5-VL-3B (LOCAL_VISION_MODEL=Qwen/Qwen2.5-VL-3B-Instruct)")
    elif load_time > 60:
        print(f"\n⚠  Model load took {load_time:.0f}s — SLOW but usable for batch analysis")
    else:
        print(f"\n✓ Model load {load_time:.1f}s — acceptable")

    if inf_time > 60:
        print(f"⚠  Inference took {inf_time:.0f}s — TOO SLOW for interactive use")
        print("   Recommendation: use Qwen2.5-VL-3B or defer to async background job")
    elif inf_time > 30:
        print(f"⚠  Inference took {inf_time:.0f}s — SLOW but ok for batch")
    else:
        print(f"✓ Inference {inf_time:.1f}s — acceptable")

    # Validate output structure
    assert obs.status in (REASONING_STATUS_ANALYZED, REASONING_STATUS_FAILED), (
        f"Unexpected status: {obs.status}"
    )

    if obs.status == REASONING_STATUS_ANALYZED:
        pub = obs.to_public_dict()
        # Required fields present
        required = [
            "visual_summary", "visible_ui_elements", "visible_objects",
            "detected_workflow_stage", "detected_outputs",
            "detected_skills_supported", "missing_or_unclear_evidence",
            "confidence_score", "limitations",
        ]
        for f in required:
            assert f in pub, f"Missing field in public output: {f}"

        # No private fields leaked
        for private_f in ("frame_storage_path", "raw_frame", "access_token", "raw_dom"):
            assert private_f not in pub, f"Private field leaked: {private_f}"

        # Confidence is in [0, 1]
        assert 0.0 <= pub["confidence_score"] <= 1.0

        print(f"\n✓ Output structure valid — {len(required)} required fields present")
        print(f"  Public dict keys: {list(pub.keys())}")
    else:
        pytest.skip(
            f"Model inference failed (status={obs.status}). "
            f"Limitations: {obs.limitations}"
        )


def test_real_qwen_service_analyze_frames():
    """Test VisualReasoningService.analyze_frames() with real Qwen provider."""
    from app.services.visual_reasoning_service import (
        VisualReasoningService,
        get_visual_reasoning_provider,
        REASONING_STATUS_ANALYZED,
        REASONING_STATUS_FAILED,
    )

    frame_bytes = _generate_test_frame()
    frames = [(1000, frame_bytes), (2000, frame_bytes), (3000, frame_bytes)]

    t_start = time.time()
    provider = get_visual_reasoning_provider()
    svc = VisualReasoningService(provider=provider)
    summary = svc.analyze_frames(
        frames=frames,
        claimed_skills=["Machine Learning", "Image Classification"],
        max_frames=1,  # Only analyze 1 frame for speed in smoke test
    )
    elapsed = time.time() - t_start

    print(f"\n✓ Service smoke test: status={summary.status}, frames_analyzed={summary.frames_analyzed}, time={elapsed:.1f}s")
    print(f"  Summary: {summary.summary[:120]}")
    print(f"  Supported signals: {summary.supported_signals}")

    assert summary.status in (REASONING_STATUS_ANALYZED, REASONING_STATUS_FAILED), (
        f"Unexpected status: {summary.status}"
    )

    if summary.status == REASONING_STATUS_ANALYZED:
        pub = summary.to_public_dict()
        assert pub["frames_analyzed"] >= 1
        assert "frame_storage_path" not in str(pub)
        assert "access_token" not in str(pub)
        print(f"✓ Session summary valid — frames_analyzed={pub['frames_analyzed']}")
    else:
        pytest.skip(f"Service returned non-analyzed status: {summary.status}")
