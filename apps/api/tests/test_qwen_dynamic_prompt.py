"""Tests for dynamic Qwen prompt and skill checklist generation (Task 1-4).

Coverage:
1. build_skill_checklist() returns ML-specific items for Machine Learning skill.
2. build_skill_checklist() returns neural-network items for Neural Networks skill.
3. build_skill_checklist() falls back to generic checklist for unknown skill.
4. build_skill_checklist() with no skills returns empty dict.
5. _build_proof_verification_prompt() includes claimed skills in output.
6. _build_proof_verification_prompt() includes proof objective when provided.
7. _build_proof_verification_prompt() includes OCR snippets when provided.
8. _build_proof_verification_prompt() includes DOM snippets when provided.
9. _build_proof_verification_prompt() includes skill checklist items.
10. _build_proof_verification_prompt() does NOT hallucinate — states unclear=true.
11. _normalize_parsed() handles new fields: visible_objects_or_diagrams, skill_evidence, supported_skills.
12. _normalize_parsed() maps supported_skills from legacy detected_skills_supported.
13. QwenVLReasoningProvider.analyze_frame_reasoning() uses dynamic prompt (stubbed inference).
14. TensorFlow Playground context produces neural-network-specific prompt (not generic).
15. Generic ecommerce context does NOT produce neural-network checklist.
16. analyze_frames() passes claimed_skills + proof_objective through to observations.
17. Fusion note appended to session summary when average confidence < 0.45.
18. _build_session_summary() uses supported_skills (new field) over detected_skills_supported.
19. VisualReasoningService.analyze_frames() accepts new context params without raising.
20. to_public_dict() includes new fields: skill_evidence, supported_skills, visible_objects_or_diagrams.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch

from app.services.visual_reasoning_service import (
    QwenVLReasoningProvider,
    MockReasoningProvider,
    VisualReasoningObservation,
    VisualReasoningSessionSummary,
    VisualReasoningService,
    _build_session_summary,
    build_skill_checklist,
    _build_proof_verification_prompt,
    REASONING_STATUS_ANALYZED,
    REASONING_STATUS_DISABLED,
    REASONING_STATUS_FAILED,
)

# ---------------------------------------------------------------------------
# Minimal JPEG fixture
# ---------------------------------------------------------------------------

_TINY_JPEG = bytes([
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


# ---------------------------------------------------------------------------
# 1-4: build_skill_checklist()
# ---------------------------------------------------------------------------

def test_checklist_machine_learning():
    cl = build_skill_checklist(["Machine Learning"])
    assert "Machine Learning" in cl
    items = cl["Machine Learning"]
    assert any("training" in i.lower() or "model" in i.lower() for i in items)


def test_checklist_neural_networks():
    cl = build_skill_checklist(["Neural Networks"])
    assert "Neural Networks" in cl
    items = cl["Neural Networks"]
    assert any("layer" in i.lower() or "neuron" in i.lower() for i in items)


def test_checklist_unknown_skill_falls_back():
    cl = build_skill_checklist(["Some Unknown Exotic Skill"])
    assert "Some Unknown Exotic Skill" in cl
    items = cl["Some Unknown Exotic Skill"]
    assert len(items) > 0  # falls back to generic checklist


def test_checklist_empty_skills():
    cl = build_skill_checklist([])
    assert cl == {}


def test_checklist_none_skills():
    cl = build_skill_checklist(None)
    assert cl == {}


# ---------------------------------------------------------------------------
# 5-10: _build_proof_verification_prompt()
# ---------------------------------------------------------------------------

def test_prompt_includes_claimed_skills():
    skills = ["Machine Learning", "Neural Networks"]
    checklist = build_skill_checklist(skills)
    prompt = _build_proof_verification_prompt(
        claimed_skills=skills,
        proof_objective="",
        website_context="",
        dom_snippets=[],
        ocr_snippets=[],
        timestamp_ms=5000,
        skill_checklist=checklist,
    )
    assert "Machine Learning" in prompt
    assert "Neural Networks" in prompt


def test_prompt_includes_proof_objective():
    skills = ["Data Visualization"]
    checklist = build_skill_checklist(skills)
    prompt = _build_proof_verification_prompt(
        claimed_skills=skills,
        proof_objective="Show a neural network training with visible loss curve",
        website_context="",
        dom_snippets=[],
        ocr_snippets=[],
        timestamp_ms=None,
        skill_checklist=checklist,
    )
    assert "neural network training" in prompt


def test_prompt_includes_ocr_snippets():
    skills = ["Machine Learning"]
    checklist = build_skill_checklist(skills)
    prompt = _build_proof_verification_prompt(
        claimed_skills=skills,
        proof_objective="",
        website_context="",
        dom_snippets=[],
        ocr_snippets=["Hidden layers: 3", "Test loss: 0.047"],
        timestamp_ms=3000,
        skill_checklist=checklist,
    )
    assert "Hidden layers: 3" in prompt
    assert "Test loss: 0.047" in prompt


def test_prompt_includes_dom_snippets():
    skills = ["Machine Learning"]
    checklist = build_skill_checklist(skills)
    prompt = _build_proof_verification_prompt(
        claimed_skills=skills,
        proof_objective="",
        website_context="playground.tensorflow.org",
        dom_snippets=["TensorFlow Playground - A Neural Network Playground"],
        ocr_snippets=[],
        timestamp_ms=None,
        skill_checklist=checklist,
    )
    assert "TensorFlow Playground" in prompt
    assert "playground.tensorflow.org" in prompt


def test_prompt_includes_skill_checklist_items():
    skills = ["Neural Networks"]
    checklist = build_skill_checklist(skills)
    prompt = _build_proof_verification_prompt(
        claimed_skills=skills,
        proof_objective="",
        website_context="",
        dom_snippets=[],
        ocr_snippets=[],
        timestamp_ms=None,
        skill_checklist=checklist,
    )
    # Should contain at least one neural network checklist item
    assert "layer" in prompt.lower() or "neuron" in prompt.lower()


def test_prompt_tells_model_not_to_hallucinate():
    skills = ["Machine Learning"]
    checklist = build_skill_checklist(skills)
    prompt = _build_proof_verification_prompt(
        claimed_skills=skills,
        proof_objective="",
        website_context="",
        dom_snippets=[],
        ocr_snippets=[],
        timestamp_ms=None,
        skill_checklist=checklist,
    )
    lower = prompt.lower()
    assert "do not invent" in lower or "hallucinate" in lower or "actually visible" in lower


def test_prompt_requests_json_only():
    skills = ["Data Visualization"]
    checklist = build_skill_checklist(skills)
    prompt = _build_proof_verification_prompt(
        claimed_skills=skills,
        proof_objective="",
        website_context="",
        dom_snippets=[],
        ocr_snippets=[],
        timestamp_ms=2000,
        skill_checklist=checklist,
    )
    assert "JSON" in prompt
    assert "skill_evidence" in prompt


# ---------------------------------------------------------------------------
# 11-12: _normalize_parsed() new fields
# ---------------------------------------------------------------------------

def test_normalize_parsed_new_fields():
    provider = QwenVLReasoningProvider.__new__(QwenVLReasoningProvider)
    parsed = {
        "visual_summary": "TensorFlow Playground with neural network diagram.",
        "visible_objects_or_diagrams": ["neural network diagram", "decision boundary"],
        "detected_workflow_stage": "model_training",
        "detected_user_action": "user adjusting hidden layers",
        "detected_outputs": ["test loss: 0.047"],
        "skill_evidence": {
            "Neural Networks": {
                "items_visible": ["layer structure"],
                "verdict": "supported",
            }
        },
        "supported_skills": ["Neural Networks", "Machine Learning"],
        "missing_or_unclear_evidence": ["activation functions not labeled"],
        "confidence_score": 0.85,
        "limitations": [],
    }
    norm = provider._normalize_parsed(parsed)
    assert norm["visible_objects_or_diagrams"] == ["neural network diagram", "decision boundary"]
    assert norm["detected_user_action"] == "user adjusting hidden layers"
    assert norm["skill_evidence"]["Neural Networks"]["verdict"] == "supported"
    assert "Neural Networks" in norm["supported_skills"]
    assert norm["detected_skills_supported"] == norm["supported_skills"]


def test_normalize_parsed_falls_back_to_legacy_skills():
    provider = QwenVLReasoningProvider.__new__(QwenVLReasoningProvider)
    parsed = {
        "visual_summary": "A web page.",
        "detected_skills_supported": ["Web Development"],
        "confidence_score": 0.6,
    }
    norm = provider._normalize_parsed(parsed)
    assert "Web Development" in norm["supported_skills"]
    assert "Web Development" in norm["detected_skills_supported"]


# ---------------------------------------------------------------------------
# 13-15: Dynamic prompt in actual inference (stubbed)
# ---------------------------------------------------------------------------

def test_qwen_analyze_frame_uses_dynamic_prompt():
    """Stubbed inference: verify dynamic prompt is built and passed to _run_inference."""
    provider = QwenVLReasoningProvider.__new__(QwenVLReasoningProvider)
    provider._backend = "qwen_vl"
    provider._available = True
    provider._model = MagicMock()
    provider._processor = MagicMock()
    provider._model_id_override = ""

    captured_prompts: list[str] = []

    def fake_run_inference(frame_bytes, prompt):
        captured_prompts.append(prompt)
        return json.dumps({
            "visual_summary": "Neural network training interface with hidden layers.",
            "visible_objects_or_diagrams": ["neural network diagram"],
            "detected_workflow_stage": "model_training",
            "detected_user_action": "adjusting hidden layers",
            "detected_outputs": ["test loss: 0.047"],
            "skill_evidence": {
                "Neural Networks": {"items_visible": ["layer structure"], "verdict": "supported"}
            },
            "supported_skills": ["Neural Networks", "Machine Learning"],
            "missing_or_unclear_evidence": [],
            "confidence_score": 0.85,
            "limitations": [],
        })

    provider._run_inference = fake_run_inference

    obs = provider.analyze_frame_reasoning(
        frame_bytes=_TINY_JPEG,
        claimed_skills=["Neural Networks", "Machine Learning"],
        context={
            "frame_index": 0,
            "timestamp_ms": 5000,
            "proof_objective": "Train a neural network on TensorFlow Playground",
            "website_context": "playground.tensorflow.org",
            "dom_snippets": ["TensorFlow Playground — Neural Network"],
            "ocr_snippets": ["Hidden layers: 3", "Test loss: 0.047"],
        },
    )

    assert len(captured_prompts) == 1
    prompt_used = captured_prompts[0]
    # Prompt must mention neural network context
    assert "Neural Networks" in prompt_used
    assert "TensorFlow Playground" in prompt_used
    assert "Hidden layers: 3" in prompt_used
    # Observation must have new fields
    assert obs.status == REASONING_STATUS_ANALYZED
    assert "Neural Networks" in obs.supported_skills
    assert obs.skill_evidence.get("Neural Networks", {}).get("verdict") == "supported"
    assert obs.visible_objects_or_diagrams == ["neural network diagram"]


def test_tensorflow_playground_context_produces_neural_network_prompt():
    """TensorFlow Playground context must produce a neural-network-specific checklist."""
    skills = ["Neural Networks", "Machine Learning", "Data Visualization"]
    checklist = build_skill_checklist(skills)
    prompt = _build_proof_verification_prompt(
        claimed_skills=skills,
        proof_objective="Demonstrate neural network training on TensorFlow Playground",
        website_context="playground.tensorflow.org",
        dom_snippets=["TensorFlow Playground – A Neural Network Playground"],
        ocr_snippets=["Hidden layers: 3", "Neurons: 4 4 2", "Test loss: 0.047"],
        timestamp_ms=12000,
        skill_checklist=checklist,
    )
    lower = prompt.lower()
    assert "layer" in lower or "neuron" in lower
    assert "chart" in lower or "plot" in lower or "visualization" in lower
    assert "training" in lower or "model" in lower
    # Must NOT be a generic ecommerce/shopping prompt
    assert "add to cart" not in lower
    assert "ecommerce" not in lower


def test_generic_ecommerce_context_does_not_produce_neural_network_checklist():
    """Ecommerce skills should not produce neural network checklist items in the skill section."""
    skills = ["Web Development", "E-commerce"]
    checklist = build_skill_checklist(skills)
    # The checklist itself must not contain neural-network-specific items
    all_checklist_items = " ".join(
        item for items in checklist.values() for item in items
    ).lower()
    assert "hidden layer" not in all_checklist_items
    assert "neurons" not in all_checklist_items
    assert "connections or weights" not in all_checklist_items
    # It should also NOT match neural network checklist
    from app.services.visual_reasoning_service import _SKILL_CHECKLIST
    nn_items = _SKILL_CHECKLIST.get("neural networks", [])
    assert checklist.get("E-commerce") != nn_items
    assert checklist.get("Web Development") != nn_items


# ---------------------------------------------------------------------------
# 16-17: analyze_frames() context pass-through and fusion note
# ---------------------------------------------------------------------------

def test_analyze_frames_passes_context_to_observations():
    """analyze_frames() must pass claimed_skills, proof_objective, context to each frame."""
    received_contexts: list[dict] = []

    class CapturingMockProvider(MockReasoningProvider):
        def analyze_frame_reasoning(self, frame_bytes, claimed_skills=None, context=None):
            received_contexts.append({
                "claimed_skills": claimed_skills,
                "context": context or {},
            })
            return VisualReasoningObservation(
                frame_index=(context or {}).get("frame_index", 0),
                timestamp_ms=(context or {}).get("timestamp_ms", 0),
                model_provider="mock",
                visual_summary="Neural network training UI visible.",
                supported_skills=["Neural Networks"],
                detected_skills_supported=["Neural Networks"],
                confidence_score=0.8,
                status=REASONING_STATUS_ANALYZED,
            )

    svc = VisualReasoningService(provider=CapturingMockProvider(is_available=True))
    svc.analyze_frames(
        frames=[_TINY_JPEG if False else (0, _TINY_JPEG), (5000, _TINY_JPEG)],
        claimed_skills=["Neural Networks", "Machine Learning"],
        proof_objective="Demonstrate neural network training",
        website_context="playground.tensorflow.org",
        dom_snippets=["TensorFlow Playground"],
        ocr_snippets=["Hidden layers: 3"],
    )

    assert len(received_contexts) > 0
    first = received_contexts[0]
    assert first["claimed_skills"] == ["Neural Networks", "Machine Learning"]
    assert first["context"]["proof_objective"] == "Demonstrate neural network training"
    assert first["context"]["website_context"] == "playground.tensorflow.org"
    assert "TensorFlow Playground" in first["context"]["dom_snippets"]
    assert "Hidden layers: 3" in first["context"]["ocr_snippets"]


def test_fusion_note_when_low_confidence():
    """Session summary should include fusion note when average confidence < 0.45."""
    low_conf_obs = [
        VisualReasoningObservation(
            frame_index=0, timestamp_ms=1000, model_provider="mock",
            visual_summary="A webpage is visible.",
            supported_skills=[],
            detected_skills_supported=[],
            confidence_score=0.3,
            status=REASONING_STATUS_ANALYZED,
        ),
        VisualReasoningObservation(
            frame_index=1, timestamp_ms=3000, model_provider="mock",
            visual_summary="Another webpage is visible.",
            supported_skills=[],
            detected_skills_supported=[],
            confidence_score=0.35,
            status=REASONING_STATUS_ANALYZED,
        ),
    ]
    summary = _build_session_summary(low_conf_obs, "mock")
    assert summary.status == REASONING_STATUS_ANALYZED
    # Fusion note should appear in summary text
    assert "low-confidence" in summary.summary.lower() or "reliable" in summary.summary.lower()


def test_no_fusion_note_when_high_confidence():
    """Session summary should NOT include fusion note when confidence >= 0.45."""
    high_conf_obs = [
        VisualReasoningObservation(
            frame_index=0, timestamp_ms=1000, model_provider="mock",
            visual_summary="TensorFlow Playground neural network visible.",
            supported_skills=["Neural Networks"],
            detected_skills_supported=["Neural Networks"],
            confidence_score=0.85,
            status=REASONING_STATUS_ANALYZED,
        ),
    ]
    summary = _build_session_summary(high_conf_obs, "mock")
    assert summary.status == REASONING_STATUS_ANALYZED
    assert "low-confidence" not in summary.summary.lower()


# ---------------------------------------------------------------------------
# 18: _build_session_summary uses supported_skills (new field)
# ---------------------------------------------------------------------------

def test_session_summary_uses_supported_skills():
    """_build_session_summary should aggregate from supported_skills field."""
    obs = [
        VisualReasoningObservation(
            frame_index=0, timestamp_ms=1000, model_provider="mock",
            visual_summary="Neural network training.",
            supported_skills=["Neural Networks", "Machine Learning"],
            detected_skills_supported=[],  # empty legacy field
            confidence_score=0.8,
            status=REASONING_STATUS_ANALYZED,
        ),
    ]
    summary = _build_session_summary(obs, "mock")
    assert "Neural Networks" in summary.supported_signals
    assert "Machine Learning" in summary.supported_signals


# ---------------------------------------------------------------------------
# 19: analyze_frames() accepts new context params without raising
# ---------------------------------------------------------------------------

def test_analyze_frames_new_params_no_raise():
    mock_provider = MockReasoningProvider(is_available=True)
    svc = VisualReasoningService(provider=mock_provider)
    summary = svc.analyze_frames(
        frames=[(0, _TINY_JPEG)],
        claimed_skills=["Machine Learning"],
        proof_objective="Demonstrate ML model training",
        website_context="colab.research.google.com",
        dom_snippets=["Google Colab — Python notebook"],
        ocr_snippets=["Training accuracy: 0.93"],
    )
    # Should not raise; returns a valid summary
    assert summary is not None
    assert summary.status in (REASONING_STATUS_ANALYZED, REASONING_STATUS_FAILED, REASONING_STATUS_DISABLED)


# ---------------------------------------------------------------------------
# 20: to_public_dict() includes new fields
# ---------------------------------------------------------------------------

def test_to_public_dict_includes_new_fields():
    obs = VisualReasoningObservation(
        frame_index=0,
        timestamp_ms=5000,
        model_provider="mock",
        visual_summary="Neural network playground.",
        visible_objects_or_diagrams=["neural network diagram", "decision boundary"],
        detected_user_action="adjusting hidden layers",
        skill_evidence={"Neural Networks": {"items_visible": ["layers"], "verdict": "supported"}},
        supported_skills=["Neural Networks"],
        detected_skills_supported=["Neural Networks"],
        confidence_score=0.85,
        status=REASONING_STATUS_ANALYZED,
    )
    d = obs.to_public_dict()
    assert "visible_objects_or_diagrams" in d
    assert d["visible_objects_or_diagrams"] == ["neural network diagram", "decision boundary"]
    assert "detected_user_action" in d
    assert d["detected_user_action"] == "adjusting hidden layers"
    assert "skill_evidence" in d
    assert d["skill_evidence"]["Neural Networks"]["verdict"] == "supported"
    assert "supported_skills" in d
    assert "Neural Networks" in d["supported_skills"]
    # No private fields
    for priv in ("frame_storage_path", "raw_frame", "frame_bytes", "access_token"):
        assert priv not in d
