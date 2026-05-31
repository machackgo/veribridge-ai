"""Test: frame_ocr_evidence_summary is exposed safely by the API endpoint layer."""
import pytest
from app.api.v1.endpoints.extension_proof_workflow_analysis import (
    _enrich_frame_ocr_evidence,
    _safe_frame_ocr_summary,
)
from app.schemas.extension_proof_workflow_analysis import WorkflowAnalysisResponse


# ── _safe_frame_ocr_summary ──────────────────────────────────────────────────

def test_safe_summary_strips_private_fields():
    raw = {
        "has_ocr_evidence": True,
        "ocr_provider": "local_ocr",
        "frames_analyzed": 5,
        "top_ocr_snippets": ["Teachable Machine"],
        "detected_page_context": "homepage_marketing",
        "observed_summary": "OCR text from 5 frames shows homepage.",
        "what_was_not_observed": ["training UI"],
        "skill_signals": [],
        # private — must be stripped
        "frame_storage_path": "/tmp/secret/frame0.jpg",
        "storage_url": "https://storage.example.com/secret",
        "access_token": "supersecret",
        "raw_dom": "<html>...",
        "debug_metadata": {"internal": True},
        "admin_notes": "do not expose",
    }
    safe = _safe_frame_ocr_summary(raw)
    assert safe is not None
    assert "frame_storage_path" not in safe
    assert "storage_url" not in safe
    assert "access_token" not in safe
    assert "raw_dom" not in safe
    assert "debug_metadata" not in safe
    assert "admin_notes" not in safe
    assert safe["has_ocr_evidence"] is True
    assert safe["ocr_provider"] == "local_ocr"
    assert safe["top_ocr_snippets"] == ["Teachable Machine"]


def test_safe_summary_returns_none_for_non_dict():
    assert _safe_frame_ocr_summary(None) is None
    assert _safe_frame_ocr_summary("string") is None
    assert _safe_frame_ocr_summary(42) is None


# ── _enrich_frame_ocr_evidence ───────────────────────────────────────────────

def test_enrich_uses_existing_summary():
    """If frame_ocr_evidence_summary already in row, do not recompute."""
    row = {
        "frame_ocr_evidence_summary": {"has_ocr_evidence": True, "ocr_provider": "local_ocr",
                                        "frames_analyzed": 3, "top_ocr_snippets": ["hello"],
                                        "detected_page_context": "training_ui",
                                        "observed_summary": "training", "what_was_not_observed": [],
                                        "skill_signals": []},
        "visual_analysis_status": "analyzed",
        "visual_analysis_provider": "local_ocr",
        "visual_frame_count": 3,
        "visual_summary": "hello",
        "supported_skills": [], "weakly_supported_skills": [], "unsupported_skills": [],
    }
    result = _enrich_frame_ocr_evidence(row)
    assert result["frame_ocr_evidence_summary"]["ocr_provider"] == "local_ocr"


def test_enrich_reconstructs_when_missing():
    """Reconstructs from visual_summary when frame_ocr_evidence_summary not in row."""
    row = {
        # No frame_ocr_evidence_summary
        "visual_analysis_status": "analyzed",
        "visual_analysis_provider": "local_ocr",
        "visual_frame_count": 10,
        "visual_summary": "Teachable Machine | train a computer | Browser-based AI",
        "supported_skills": [], "weakly_supported_skills": [],
        "unsupported_skills": ["Machine Learning", "Image Classification"],
    }
    result = _enrich_frame_ocr_evidence(row)
    ocr = result["frame_ocr_evidence_summary"]
    assert ocr is not None
    assert ocr["frames_analyzed"] == 10
    assert ocr["ocr_provider"] == "local_ocr"


def test_enrich_no_ocr_when_not_configured():
    """Not-configured status yields has_ocr_evidence=False."""
    row = {
        "visual_analysis_status": "not_configured",
        "visual_analysis_provider": "none",
        "visual_frame_count": 0,
        "visual_summary": "",
        "supported_skills": [], "weakly_supported_skills": [], "unsupported_skills": [],
    }
    result = _enrich_frame_ocr_evidence(row)
    ocr = result["frame_ocr_evidence_summary"]
    assert ocr["has_ocr_evidence"] is False


# ── Schema field present ──────────────────────────────────────────────────────

def test_schema_has_frame_ocr_evidence_summary_field():
    fields = WorkflowAnalysisResponse.model_fields
    assert "frame_ocr_evidence_summary" in fields
    field = fields["frame_ocr_evidence_summary"]
    assert field.default is None


# ── OCR skill signal reasoning (Teachable Machine terms) ─────────────────────

def test_teachable_machine_terms_partially_support_machine_learning():
    """Teachable Machine / 'train a computer' partially supports Machine Learning."""
    from app.services.extension_proof_workflow_analysis_service import _ocr_skill_signals
    visual_summary = "Teachable Machine | train a computer | Browser-based AI"
    signals = _ocr_skill_signals(["Machine Learning", "Browser-Based AI"], visual_summary, "homepage_marketing")
    ml_sig = next((s for s in signals if s["skill"] == "Machine Learning"), None)
    assert ml_sig is not None
    assert ml_sig["ocr_support"] == "partial"


def test_image_classification_insufficient_without_class_labels():
    """Image Classification stays insufficient when no class labels detected."""
    from app.services.extension_proof_workflow_analysis_service import _ocr_skill_signals
    visual_summary = "Teachable Machine | train a computer"
    signals = _ocr_skill_signals(["Image Classification"], visual_summary, "homepage_marketing")
    ic_sig = next((s for s in signals if s["skill"] == "Image Classification"), None)
    assert ic_sig is not None
    assert ic_sig["ocr_support"] == "insufficient"


def test_model_testing_insufficient_without_prediction_output():
    """Model Testing stays insufficient when no prediction/confidence terms detected."""
    from app.services.extension_proof_workflow_analysis_service import _ocr_skill_signals
    visual_summary = "Teachable Machine | machine learning"
    signals = _ocr_skill_signals(["Model Testing"], visual_summary, "homepage_marketing")
    mt_sig = next((s for s in signals if s["skill"] == "Model Testing"), None)
    assert mt_sig is not None
    assert mt_sig["ocr_support"] == "insufficient"


# ── Public/recruiter view: no private paths ───────────────────────────────────

def test_no_private_paths_in_safe_summary():
    """_safe_frame_ocr_summary never leaks raw_frame, frame_bytes, frame_path."""
    raw = {
        "has_ocr_evidence": True, "ocr_provider": "local_ocr", "frames_analyzed": 1,
        "top_ocr_snippets": [], "detected_page_context": "unknown", "observed_summary": "",
        "what_was_not_observed": [], "skill_signals": [],
        "frame_path": "/private/frame0.jpg",
        "raw_frame": b"\x00\x00",
        "frame_bytes": b"\xff",
    }
    safe = _safe_frame_ocr_summary(raw)
    assert "frame_path" not in safe
    assert "raw_frame" not in safe
    assert "frame_bytes" not in safe
