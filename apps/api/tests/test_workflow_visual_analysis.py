"""Tests for Workflow Visual Frame Analysis (v5 — provider-agnostic).

Coverage:
1.  NoneProvider.is_configured() returns False.
2.  NoneProvider.analyze_frame() returns not_configured, does not raise.
3.  extract_result_values_from_ocr("dog 0.89") → result value dict.
4.  extract_result_values_from_ocr("accuracy: 94%") → result value dict.
5.  extract_result_values_from_ocr(empty) → [].
6.  No provider configured → WorkflowVisualAnalysisService.analyze_frames_for_session
    returns visual_frame_analysis_status = "not_configured".
7.  Visual frame record can be created (store_visual_frame).
8.  LocalOCRProvider.is_configured() returns False gracefully when paddleocr
    is not installed.
9.  OCR text "dog 0.89" becomes extracted_result_values via LocalOCRProvider
    (using a stubbed OCR engine).
10. Sensitive text in OCR output is masked (password, API key, email).
11. build_visual_workflow_summary merges DOM values (priority) over OCR values.
12. Exact values are NOT invented — only present when captured.
13. get_visual_observations on session with no frames returns not_captured.
14. Public summary / status endpoint does not expose frame_storage_path.
15. Old recordings still work — visual_analysis_status = "not_configured"
    in workflow analysis when no visual frames exist.
16. get_visual_provider() with unknown provider name returns NoneProvider safely.
17. _mask_sensitive_text masks password, email, card, SSN, local path, supabase URL.
18. VeriBridgeFutureProvider.is_configured() returns False with clear message.
19. LocalOCRProvider falls back to not_configured when engine init fails.
20. WorkflowVisualAnalysisService.get_provider_status() returns correct fields.
21. analyze_visual_frame() with None bytes returns skipped (not crash).
22. Workflow analysis integration: visual_analysis_status propagates from
    visual_frame_observations dict.

LocalVisionProvider (fixed implementation — tests 23-27):
23. is_configured() returns False when required packages (torch) are missing.
24. analyze_frame() returns not_configured without raising when packages missing.
25. analyze_frame() with stubbed _run_vision() returning text → analyzed + result values.
26. analyze_frame() with stubbed _run_vision() returning "" → failed status.
27. PII in vision model output is masked before being stored.

visual_analysis_status fix (tests 28-30):
28. _build_observed_demonstration() with analyzed visual_frame_observations
    → visual_analysis_status = "analyzed", ocr_status = "analyzed" (OCR provider).
29. _build_observed_demonstration() with no visual_frame_observations
    → visual_analysis_status = "not_configured" (backward compat).
30. _analyze_workflow() with analyzed frames → observed_demonstration reflects
    "analyzed" status; vision provider (non-OCR) sets ocr_status = "not_configured".
"""

from __future__ import annotations

import base64
import io
import pytest
from unittest.mock import MagicMock, patch

from app.services.workflow_visual_analysis_service import (
    NoneProvider,
    LocalOCRProvider,
    LocalVisionProvider,
    OpenAIVisionProvider,
    VeriBridgeFutureProvider,
    WorkflowVisualAnalysisService,
    VisualFrameObservation,
    extract_result_values_from_ocr,
    get_visual_provider,
    _mask_sensitive_text,
    VISUAL_STATUS_ANALYZED,
    VISUAL_STATUS_NOT_CONFIGURED,
    VISUAL_STATUS_PENDING,
    VISUAL_STATUS_SKIPPED,
    VISUAL_STATUS_FAILED,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(rows: list[dict] | None = None) -> MagicMock:
    """Create a minimal mock Supabase client."""
    rows = rows or []
    db = MagicMock()
    chain = MagicMock()
    chain.execute.return_value.data = rows
    db.table.return_value.select.return_value = chain
    db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{}])
    db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])
    # Support chained .eq calls
    chain.eq.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    return db


def _tiny_jpeg() -> bytes:
    """Return a minimal valid 1x1 JPEG bytes."""
    try:
        from PIL import Image
        buf = io.BytesIO()
        img = Image.new("RGB", (1, 1), color=(128, 128, 128))
        img.save(buf, format="JPEG")
        return buf.getvalue()
    except ImportError:
        # Return raw minimal JPEG header bytes for tests that don't need PIL
        return b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 100


# ---------------------------------------------------------------------------
# 1. NoneProvider.is_configured()
# ---------------------------------------------------------------------------

def test_none_provider_is_not_configured():
    p = NoneProvider()
    assert p.is_configured() is False


# ---------------------------------------------------------------------------
# 2. NoneProvider.analyze_frame() returns not_configured without raising
# ---------------------------------------------------------------------------

def test_none_provider_analyze_frame_does_not_raise():
    p = NoneProvider()
    obs = p.analyze_frame(b"fake_bytes")
    assert obs.status == VISUAL_STATUS_NOT_CONFIGURED
    assert not obs.extracted_result_values
    assert obs.limitations


# ---------------------------------------------------------------------------
# 3. extract_result_values_from_ocr — "dog 0.89"
# ---------------------------------------------------------------------------

def test_extract_result_values_dog_score():
    results = extract_result_values_from_ocr(["dog 0.89"])
    assert len(results) == 1
    rv = results[0]
    assert rv["label"].lower() == "dog"
    assert rv["value"] == "0.89"
    assert rv["source"] == "ocr"
    assert rv["confidence"] > 0


# ---------------------------------------------------------------------------
# 4. extract_result_values_from_ocr — "accuracy: 94%"
# ---------------------------------------------------------------------------

def test_extract_result_values_percentage():
    results = extract_result_values_from_ocr(["accuracy: 94%"])
    assert any(r["label"].lower() == "accuracy" and r["value"] == "94%" for r in results)


# ---------------------------------------------------------------------------
# 5. extract_result_values_from_ocr — empty → []
# ---------------------------------------------------------------------------

def test_extract_result_values_empty():
    assert extract_result_values_from_ocr([]) == []
    assert extract_result_values_from_ocr([""]) == []
    assert extract_result_values_from_ocr(["no numbers here"]) == []


# ---------------------------------------------------------------------------
# 6. No provider → analyze_frames_for_session returns not_configured
# ---------------------------------------------------------------------------

def test_no_provider_analyze_frames_returns_not_configured():
    db = _make_db()
    with patch("app.services.workflow_visual_analysis_service.settings") as mock_settings:
        mock_settings.visual_analysis_provider = "none"
        mock_settings.enable_workflow_frame_capture = True
        mock_settings.max_workflow_frames = 15
        mock_settings.local_ocr_provider = "paddleocr"
        mock_settings.local_vision_provider = "llava"

        # Reset singleton for this test
        import app.services.workflow_visual_analysis_service as svc_mod
        svc_mod._PROVIDER_SINGLETON = None

        svc = WorkflowVisualAnalysisService(db)
        svc._provider = NoneProvider()
        result = svc.analyze_frames_for_session("user-1", "session-1")

    assert result["visual_frame_analysis_status"] == VISUAL_STATUS_NOT_CONFIGURED
    assert result["frames_analyzed"] == 0
    assert result["extracted_result_values"] == []
    assert "not configured" in result["limitations"][0].lower()


# ---------------------------------------------------------------------------
# 7. store_visual_frame creates a DB record
# ---------------------------------------------------------------------------

def test_store_visual_frame_creates_record():
    db = _make_db()
    with patch("app.services.workflow_visual_analysis_service.settings") as mock_settings:
        mock_settings.visual_analysis_provider = "none"
        mock_settings.enable_workflow_frame_capture = True
        mock_settings.max_workflow_frames = 15
        mock_settings.local_ocr_provider = "paddleocr"
        mock_settings.local_vision_provider = "llava"

        svc = WorkflowVisualAnalysisService(db)
        svc._provider = NoneProvider()
        frame_id = svc.store_visual_frame(
            user_id="user-1",
            session_id="session-1",
            frame_type="after_click",
            frame_bytes=b"fake_bytes",
            timestamp_ms=5000,
        )

    assert isinstance(frame_id, str)
    assert len(frame_id) > 0
    db.table.assert_called_with("workflow_visual_frame_evidence")
    db.table().insert.assert_called_once()


# ---------------------------------------------------------------------------
# 8. LocalOCRProvider gracefully returns False when package missing
# ---------------------------------------------------------------------------

def test_local_ocr_provider_not_configured_when_package_missing():
    p = LocalOCRProvider.__new__(LocalOCRProvider)
    p._backend = "paddleocr"
    p._ocr_engine = None
    p._available = None

    # Simulate ImportError for paddleocr
    with patch.dict("sys.modules", {"paddleocr": None}):
        result = p.is_configured()

    # Should return False, not raise
    assert result is False


# ---------------------------------------------------------------------------
# 9. OCR text "dog 0.89" becomes result value via stubbed engine
# ---------------------------------------------------------------------------

def test_local_ocr_provider_extracts_dog_score_with_stub():
    """Stub the OCR engine to return 'dog 0.89' and verify extraction."""
    p = LocalOCRProvider.__new__(LocalOCRProvider)
    p._backend = "easyocr"
    p._ocr_engine = MagicMock()
    p._available = True

    # Stub _run_ocr to return the OCR text
    with patch.object(p, "_run_ocr", return_value=["dog 0.89", "person 0.77"]):
        obs = p.analyze_frame(b"fake_bytes")

    assert obs.status == VISUAL_STATUS_ANALYZED
    labels = [r["label"].lower() for r in obs.extracted_result_values]
    assert "dog" in labels
    assert "person" in labels

    dog_rv = next(r for r in obs.extracted_result_values if r["label"].lower() == "dog")
    assert dog_rv["value"] == "0.89"
    assert dog_rv["source"] == "ocr"


# ---------------------------------------------------------------------------
# 10. Sensitive text in OCR output is masked
# ---------------------------------------------------------------------------

def test_mask_sensitive_text_password():
    text = "password: supersecret123"
    cleaned, flags = _mask_sensitive_text(text)
    assert "supersecret123" not in cleaned
    assert "PASSWORD REDACTED" in flags or any("PASSWORD" in f for f in flags)


def test_mask_sensitive_text_email():
    text = "user@example.com logged in"
    cleaned, flags = _mask_sensitive_text(text)
    assert "user@example.com" not in cleaned
    assert any("EMAIL" in f for f in flags)


def test_mask_sensitive_text_supabase_url():
    text = "internal: https://abc.supabase.co/project/editor"
    cleaned, flags = _mask_sensitive_text(text)
    assert "abc.supabase.co" not in cleaned


def test_mask_sensitive_text_ssn():
    text = "SSN: 123-45-6789"
    cleaned, flags = _mask_sensitive_text(text)
    assert "123-45-6789" not in cleaned


def test_mask_sensitive_text_api_key():
    text = "api_key=sk-abc123def456"
    cleaned, flags = _mask_sensitive_text(text)
    assert "sk-abc123def456" not in cleaned


# ---------------------------------------------------------------------------
# 11. build_visual_workflow_summary merges DOM (priority) over OCR values
# ---------------------------------------------------------------------------

def test_build_visual_workflow_summary_dom_priority():
    db = _make_db(rows=[{
        "id": "frame-1",
        "frame_type": "after_result_detected",
        "timestamp_ms": 5000,
        "visual_analysis_status": VISUAL_STATUS_ANALYZED,
        "ocr_text": [{"text": "dog 0.89"}],
        "visual_objects": [],
        "visual_summary": "Dog detected with high confidence",
        "extracted_result_values": [
            {"label": "dog", "value": "0.89", "confidence": 0.9, "source": "ocr"}
        ],
    }])

    with patch("app.services.workflow_visual_analysis_service.settings") as mock_settings:
        mock_settings.visual_analysis_provider = "local_ocr"
        mock_settings.enable_workflow_frame_capture = True
        mock_settings.max_workflow_frames = 15
        mock_settings.local_ocr_provider = "paddleocr"
        mock_settings.local_vision_provider = "llava"

        svc = WorkflowVisualAnalysisService(db)
        svc._provider = NoneProvider()

        dom_values = [
            {"label": "dog", "value": "0.91", "confidence": 1.0, "source": "dom"},
            {"label": "cat", "value": "0.10", "confidence": 1.0, "source": "dom"},
        ]
        result = svc.build_visual_workflow_summary("user-1", "session-1", dom_result_values=dom_values)

    merged = result["merged_result_values"]
    # DOM "dog" value (0.91) should take priority over OCR "dog" (0.89)
    dog_entries = [r for r in merged if r.get("label", "").lower() == "dog"]
    assert dog_entries, "Dog should be in merged values"
    # DOM value (source=dom) should appear
    assert any(r.get("source") == "dom" for r in dog_entries)


# ---------------------------------------------------------------------------
# 12. Exact values are NOT invented
# ---------------------------------------------------------------------------

def test_extract_result_values_does_not_invent_values():
    # Vague text without a clear number
    results = extract_result_values_from_ocr(["The model ran successfully"])
    assert results == []

    results = extract_result_values_from_ocr(["Processing complete. See results above."])
    assert results == []


# ---------------------------------------------------------------------------
# 13. get_visual_observations on session with no frames → not_captured
# ---------------------------------------------------------------------------

def test_get_visual_observations_no_frames():
    # Both queries return empty
    db = MagicMock()
    chain = MagicMock()
    chain.execute.return_value.data = []
    chain.eq.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    db.table.return_value.select.return_value = chain

    with patch("app.services.workflow_visual_analysis_service.settings") as mock_settings:
        mock_settings.visual_analysis_provider = "none"
        mock_settings.enable_workflow_frame_capture = False
        mock_settings.max_workflow_frames = 15
        mock_settings.local_ocr_provider = "paddleocr"
        mock_settings.local_vision_provider = "llava"

        svc = WorkflowVisualAnalysisService(db)
        svc._provider = NoneProvider()
        obs = svc.get_visual_observations("user-1", "session-1")

    assert obs["visual_frame_count"] == 0
    assert obs["visual_frame_analysis_status"] == "not_captured"
    assert obs["extracted_result_values"] == []


# ---------------------------------------------------------------------------
# 14. Status response does not expose frame_storage_path
# ---------------------------------------------------------------------------

def test_get_provider_status_no_storage_paths():
    db = _make_db()
    with patch("app.services.workflow_visual_analysis_service.settings") as mock_settings:
        mock_settings.visual_analysis_provider = "none"
        mock_settings.enable_workflow_frame_capture = False
        mock_settings.max_workflow_frames = 15
        mock_settings.local_ocr_provider = "paddleocr"
        mock_settings.local_vision_provider = "llava"

        svc = WorkflowVisualAnalysisService(db)
        status = svc.get_provider_status()

    assert "frame_storage_path" not in status
    assert "frame_thumbnail_storage_path" not in status
    assert "visual_analysis_provider" in status
    assert "provider_configured" in status


# ---------------------------------------------------------------------------
# 15. Old recordings still work — visual_analysis_status = not_configured
# ---------------------------------------------------------------------------

def test_workflow_analysis_visual_status_not_configured_for_old_recordings():
    """_analyze_workflow should return visual_analysis_status=not_configured
    when no visual_frame_observations dict is provided."""
    from app.services.extension_proof_workflow_analysis_service import _analyze_workflow

    import datetime
    start = datetime.datetime(2024, 1, 1, 10, 0, 0,
                               tzinfo=datetime.timezone.utc).isoformat()
    stop = datetime.datetime(2024, 1, 1, 10, 2, 0,
                              tzinfo=datetime.timezone.utc).isoformat()
    proof_data = {
        "workflow_events": [
            {"type": "page_visit", "page_url": "https://demo.vercel.app", "page_title": "Demo"},
        ],
        "started_at": start,
        "stopped_at": stop,
    }
    result = _analyze_workflow(
        proof_data=proof_data,
        claimed_skills=["Machine Learning"],
        proof_objective="Test ML inference",
        original_url="https://demo.vercel.app",
        url_type="live_url",
        github_url=None,
        visible_observations=None,
        visual_frame_observations=None,   # old recording — no frames
    )

    assert result["visual_analysis_status"] == "not_configured"
    assert result["ocr_status"] == "not_configured"


# ---------------------------------------------------------------------------
# 16. get_visual_provider() with unknown name → NoneProvider
# ---------------------------------------------------------------------------

def test_get_visual_provider_unknown_name():
    with patch("app.services.workflow_visual_analysis_service.settings") as mock_settings:
        mock_settings.visual_analysis_provider = "unknown_provider_xyz"
        provider = get_visual_provider()
    assert isinstance(provider, NoneProvider)


# ---------------------------------------------------------------------------
# 17. _mask_sensitive_text comprehensive
# ---------------------------------------------------------------------------

def test_mask_sensitive_text_local_path():
    text = "loaded from /home/user/data/model.pt"
    cleaned, flags = _mask_sensitive_text(text)
    assert "/home/user" not in cleaned


def test_mask_sensitive_text_credit_card():
    text = "card number 4111 1111 1111 1111"
    cleaned, flags = _mask_sensitive_text(text)
    assert "4111" not in cleaned


# ---------------------------------------------------------------------------
# 18. VeriBridgeFutureProvider.is_configured() → False
# ---------------------------------------------------------------------------

def test_veribridge_future_provider_not_configured():
    p = VeriBridgeFutureProvider()
    assert p.is_configured() is False
    obs = p.analyze_frame(b"test")
    assert obs.status == VISUAL_STATUS_NOT_CONFIGURED
    assert "VeriBridge" in obs.limitations[0]


# ---------------------------------------------------------------------------
# 19. LocalOCRProvider falls back gracefully when engine init fails
# ---------------------------------------------------------------------------

def test_local_ocr_provider_analyze_frame_when_not_configured():
    p = LocalOCRProvider.__new__(LocalOCRProvider)
    p._backend = "paddleocr"
    p._ocr_engine = None
    p._available = False

    obs = p.analyze_frame(b"some_bytes")
    # Should not raise; returns not_configured
    assert obs.status == VISUAL_STATUS_NOT_CONFIGURED
    assert "not installed" in obs.limitations[0].lower() or "not" in obs.limitations[0].lower()


# ---------------------------------------------------------------------------
# 20. get_provider_status() returns correct fields
# ---------------------------------------------------------------------------

def test_get_provider_status_fields():
    db = _make_db()
    with patch("app.services.workflow_visual_analysis_service.settings") as mock_settings:
        mock_settings.visual_analysis_provider = "local_ocr"
        mock_settings.enable_workflow_frame_capture = True
        mock_settings.max_workflow_frames = 10
        mock_settings.local_ocr_provider = "easyocr"
        mock_settings.local_vision_provider = "llava"

        svc = WorkflowVisualAnalysisService(db)
        svc._provider = NoneProvider()
        status = svc.get_provider_status()

    assert status["visual_analysis_provider"] == "local_ocr"
    assert status["frame_capture_enabled"] is True
    assert status["max_frames"] == 10
    assert status["local_ocr_provider"] == "easyocr"
    assert status["provider_configured"] is False   # NoneProvider


# ---------------------------------------------------------------------------
# 21. analyze_visual_frame() with None bytes → skipped (not crash)
# ---------------------------------------------------------------------------

def test_analyze_visual_frame_none_bytes_returns_skipped():
    db = _make_db()
    with patch("app.services.workflow_visual_analysis_service.settings") as mock_settings:
        mock_settings.visual_analysis_provider = "local_ocr"
        mock_settings.enable_workflow_frame_capture = True
        mock_settings.max_workflow_frames = 15
        mock_settings.local_ocr_provider = "paddleocr"
        mock_settings.local_vision_provider = "llava"

        # Stub a "configured" provider that would need bytes
        stub_provider = MagicMock()
        stub_provider.is_configured.return_value = True

        svc = WorkflowVisualAnalysisService(db)
        svc._provider = stub_provider

        obs = svc.analyze_visual_frame("frame-id-1", "user-1", frame_bytes=None)

    assert obs.status == VISUAL_STATUS_SKIPPED
    assert "not available" in obs.limitations[0].lower()


# ---------------------------------------------------------------------------
# 22. Workflow analysis integration: visual_analysis_status propagates
# ---------------------------------------------------------------------------

def test_workflow_analysis_visual_status_from_visual_frame_observations():
    """When visual_frame_observations has status=analyzed, result reflects it."""
    from app.services.extension_proof_workflow_analysis_service import _analyze_workflow

    import datetime
    start = datetime.datetime(2024, 1, 1, 10, 0, 0,
                               tzinfo=datetime.timezone.utc).isoformat()
    stop = datetime.datetime(2024, 1, 1, 10, 5, 0,
                              tzinfo=datetime.timezone.utc).isoformat()
    proof_data = {
        "workflow_events": [
            {"type": "page_visit", "page_url": "https://ml-demo.vercel.app", "page_title": "ML Demo"},
            {"type": "click", "page_url": "https://ml-demo.vercel.app", "element_text": "Predict"},
        ],
        "started_at": start,
        "stopped_at": stop,
    }

    visual_frame_observations = {
        "visual_frame_analysis_status": "analyzed",
        "visual_frame_count": 3,
        "extracted_result_values": [
            {"label": "dog", "value": "0.89", "confidence": 0.9, "source": "ocr"}
        ],
        "visual_summary": "Image uploaded, prediction shown: dog 0.89",
        "provider_used": "local_ocr:paddleocr",
    }

    result = _analyze_workflow(
        proof_data=proof_data,
        claimed_skills=["Machine Learning", "Python"],
        proof_objective="Image classification demo",
        original_url="https://ml-demo.vercel.app",
        url_type="live_url",
        github_url=None,
        visible_observations=None,
        visual_frame_observations=visual_frame_observations,
    )

    assert result["visual_analysis_status"] == "analyzed"
    assert result["visual_analysis_provider"] == "local_ocr:paddleocr"
    assert result["visual_frame_count"] == 3
    assert len(result["visual_result_values"]) == 1
    assert result["visual_result_values"][0]["label"] == "dog"
    # OCR status should be "analyzed" when provider contains "ocr"
    assert result["ocr_status"] == "analyzed"


# ---------------------------------------------------------------------------
# 23. LocalVisionProvider.is_configured() → False when torch is missing
# ---------------------------------------------------------------------------

def test_local_vision_provider_not_configured_when_torch_missing():
    """is_configured() returns False gracefully when torch is not installed."""
    p = LocalVisionProvider.__new__(LocalVisionProvider)
    p._backend = "qwen_vl"
    p._available = None
    p._model = None
    p._processor = None

    # Block torch import — _try_init checks torch before anything else
    with patch.dict("sys.modules", {"torch": None}):
        p._available = None  # force re-check
        result = p.is_configured()

    assert result is False


# ---------------------------------------------------------------------------
# 24. LocalVisionProvider.analyze_frame() → not_configured without raising
# ---------------------------------------------------------------------------

def test_local_vision_provider_analyze_frame_not_configured_does_not_raise():
    """analyze_frame() returns not_configured and never raises when packages missing."""
    p = LocalVisionProvider.__new__(LocalVisionProvider)
    p._backend = "qwen_vl"
    p._available = False  # simulate packages missing
    p._model = None
    p._processor = None

    obs = p.analyze_frame(b"fake_bytes")

    assert obs.status == VISUAL_STATUS_NOT_CONFIGURED
    assert len(obs.limitations) > 0
    assert "local_vision:qwen_vl" in obs.provider_used
    # Limitation should mention how to install
    assert "pip install" in obs.limitations[0].lower() or "install" in obs.limitations[0].lower()


# ---------------------------------------------------------------------------
# 25. LocalVisionProvider: stubbed _run_vision → analyzed + result values
# ---------------------------------------------------------------------------

def test_local_vision_provider_stubbed_run_vision_returns_analyzed():
    """With packages available and a stubbed inference method, returns analyzed."""
    p = LocalVisionProvider.__new__(LocalVisionProvider)
    p._backend = "qwen_vl"
    p._available = True   # simulate packages present
    p._model = MagicMock()
    p._processor = MagicMock()

    with patch.object(p, "_run_vision", return_value="dog 0.89 confidence score"):
        obs = p.analyze_frame(b"fake_bytes")

    assert obs.status == VISUAL_STATUS_ANALYZED
    assert obs.screen_summary   # should have some text
    assert "local_vision:qwen_vl" in obs.provider_used
    # Result values should be extracted from the description
    labels = [r["label"].lower() for r in obs.extracted_result_values]
    assert "dog" in labels


# ---------------------------------------------------------------------------
# 26. LocalVisionProvider: _run_vision returns "" → failed status
# ---------------------------------------------------------------------------

def test_local_vision_provider_empty_run_vision_returns_failed():
    """When the vision model returns empty output, analyze_frame returns failed."""
    p = LocalVisionProvider.__new__(LocalVisionProvider)
    p._backend = "llava"
    p._available = True
    p._model = MagicMock()
    p._processor = MagicMock()

    with patch.object(p, "_run_vision", return_value=""):
        obs = p.analyze_frame(b"fake_bytes")

    assert obs.status == VISUAL_STATUS_FAILED
    assert len(obs.limitations) > 0
    assert "empty" in obs.limitations[0].lower() or "memory" in obs.limitations[0].lower()


# ---------------------------------------------------------------------------
# 27. PII in vision model output is masked before being stored
# ---------------------------------------------------------------------------

def test_local_vision_provider_masks_pii_in_vision_output():
    """Vision model output containing an email is masked before storage."""
    p = LocalVisionProvider.__new__(LocalVisionProvider)
    p._backend = "qwen_vl"
    p._available = True
    p._model = MagicMock()
    p._processor = MagicMock()

    sensitive_output = "Prediction: 0.92. Contact: user@example.com. Score: 88%"
    with patch.object(p, "_run_vision", return_value=sensitive_output):
        obs = p.analyze_frame(b"fake_bytes")

    assert obs.status == VISUAL_STATUS_ANALYZED
    assert "user@example.com" not in obs.screen_summary
    assert "user@example.com" not in "".join(obs.extracted_text)
    # Privacy flags should record that an email was redacted
    assert obs.privacy_flags


# ---------------------------------------------------------------------------
# 28. _build_observed_demonstration: analyzed frames → status = "analyzed"
# ---------------------------------------------------------------------------

def test_build_observed_demonstration_reflects_analyzed_status():
    """visual_analysis_status = 'analyzed' when visual_frame_observations say so."""
    from app.services.extension_proof_workflow_analysis_service import (
        _build_observed_demonstration,
    )

    vf_obs = {
        "visual_frame_analysis_status": "analyzed",
        "visual_frame_count": 2,
        "provider_used": "local_ocr:paddleocr",
        "extracted_result_values": [
            {"label": "dog", "value": "0.89", "source": "ocr"},
        ],
        "visual_summary": "Prediction shown: dog 0.89",
    }

    result = _build_observed_demonstration(
        target_events=[
            {"type": "page_visit", "page_url": "https://demo.app", "page_title": "Demo"},
        ],
        app_type="ml_app",
        target_app="demo.app",
        iao_patterns=[],
        visible_observations=None,
        visual_frame_observations=vf_obs,
    )

    assert result["visual_analysis_status"] == "analyzed"
    assert result["ocr_status"] == "analyzed"   # provider name contains "ocr"
    # The "not configured" limitation must NOT appear when analysis ran
    vis_lims = [
        l for l in result["limitations"]
        if "not configured" in l.lower() and "visual" in l.lower()
    ]
    assert not vis_lims, f"Unexpected not-configured limitation: {vis_lims}"


# ---------------------------------------------------------------------------
# 29. _build_observed_demonstration: no frames → not_configured (backward compat)
# ---------------------------------------------------------------------------

def test_build_observed_demonstration_not_configured_when_no_frames():
    """visual_analysis_status = 'not_configured' when no visual_frame_observations."""
    from app.services.extension_proof_workflow_analysis_service import (
        _build_observed_demonstration,
    )

    result = _build_observed_demonstration(
        target_events=[
            {"type": "page_visit", "page_url": "https://demo.app", "page_title": "Demo"},
        ],
        app_type="generic",
        target_app="demo.app",
        iao_patterns=[],
        visible_observations=None,
        visual_frame_observations=None,   # old recording — no frames passed
    )

    assert result["visual_analysis_status"] == "not_configured"
    assert result["ocr_status"] == "not_configured"
    # The "not configured" limitation SHOULD be present
    assert any("not configured" in l.lower() for l in result["limitations"])


# ---------------------------------------------------------------------------
# 30. _analyze_workflow: observed_demonstration reflects analyzed status
# ---------------------------------------------------------------------------

def test_analyze_workflow_observed_demonstration_visual_status_propagates():
    """observed_demonstration.visual_analysis_status = 'analyzed' for vision provider."""
    from app.services.extension_proof_workflow_analysis_service import _analyze_workflow
    import datetime

    start = datetime.datetime(2024, 1, 1, 10, 0, 0,
                               tzinfo=datetime.timezone.utc).isoformat()
    stop  = datetime.datetime(2024, 1, 1, 10, 5, 0,
                               tzinfo=datetime.timezone.utc).isoformat()

    proof_data = {
        "workflow_events": [
            {"type": "page_visit",
             "page_url": "https://ml.example.com",
             "page_title": "ML App"},
            {"type": "click",
             "page_url": "https://ml.example.com",
             "element_text": "Predict"},
        ],
        "started_at": start,
        "stopped_at": stop,
    }

    # Vision model (qwen_vl) analyzed frames — provider_used does NOT contain "ocr"
    visual_frame_observations = {
        "visual_frame_analysis_status": "analyzed",
        "visual_frame_count": 2,
        "visual_frames_stored": 2,
        "provider_used": "local_vision:qwen_vl",
        "extracted_result_values": [
            {"label": "cat", "value": "0.92", "source": "model_output_text"},
        ],
        "visual_summary": "Cat detected with 0.92 confidence",
    }

    result = _analyze_workflow(
        proof_data=proof_data,
        claimed_skills=["Machine Learning"],
        proof_objective="Image classification",
        original_url="https://ml.example.com",
        url_type="live_deployed_url",
        github_url=None,
        visible_observations=None,
        visual_frame_observations=visual_frame_observations,
    )

    od = result.get("observed_demonstration", {})
    # observed_demonstration must now reflect "analyzed" (was always "not_configured" before)
    assert od.get("visual_analysis_status") == "analyzed", (
        f"Expected 'analyzed', got {od.get('visual_analysis_status')!r}"
    )
    # Vision model used (not OCR pipeline) → ocr_status stays "not_configured"
    assert od.get("ocr_status") == "not_configured"
    # Top-level result is unchanged
    assert result["visual_analysis_status"] == "analyzed"
