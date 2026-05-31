"""Tests for smart Qwen frame selection logic.

Covers:
1.  limit=1 selects frame at 50% of recording
2.  limit=2 selects frames at ~25% and ~80%
3.  limit=3 selects frames at ~20%, ~50%, ~85%
4.  limit > 3 falls back to evenly-spaced midpoints
5.  Fewer frames than limit → all frames returned
6.  Single frame → that frame returned for any limit
7.  No duplicate indices in returned selection
8.  VisualReasoningService respects VISUAL_REASONING_MAX_FRAMES
9.  MockProvider analyzes all selected frames
10. Session summary has correct frames_analyzed count
11. Two-session isolation: frames from session A not returned for session B
12. Private fields never appear in to_public_dict()
"""

from __future__ import annotations

import pytest

from app.services.visual_reasoning_service import (
    MockReasoningProvider,
    VisualReasoningObservation,
    VisualReasoningService,
    VisualReasoningSessionSummary,
    REASONING_STATUS_ANALYZED,
    REASONING_STATUS_DISABLED,
    _select_frames_smart,
)

# ── Tiny valid JPEG fixture ────────────────────────────────────────────────────

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


def _make_frames(n: int) -> list[tuple[int, bytes]]:
    """Create n synthetic frames with timestamps 0, 1000, 2000, ..."""
    return [(i * 1000, _TINY_JPEG) for i in range(n)]


# ── 1–4. _select_frames_smart percentile logic ────────────────────────────────

def test_limit_1_picks_middle():
    frames = _make_frames(10)
    selected = _select_frames_smart(frames, limit=1)
    assert len(selected) == 1
    # Should pick index 5 (50% of 10)
    ts = selected[0][0]
    assert ts == frames[5][0]


def test_limit_2_picks_25_and_80_percent():
    frames = _make_frames(10)
    selected = _select_frames_smart(frames, limit=2)
    assert len(selected) == 2
    ts_list = [ts for ts, _ in selected]
    # ~25% → index 2, ~80% → index 8
    assert frames[2][0] in ts_list
    assert frames[8][0] in ts_list


def test_limit_3_picks_20_50_85_percent():
    frames = _make_frames(10)
    selected = _select_frames_smart(frames, limit=3)
    assert len(selected) == 3
    ts_list = [ts for ts, _ in selected]
    # ~20% → index 2, ~50% → index 5, ~85% → index 8
    assert frames[2][0] in ts_list
    assert frames[5][0] in ts_list
    assert frames[8][0] in ts_list


def test_limit_4_uses_fallback_evenly_spaced():
    frames = _make_frames(12)
    selected = _select_frames_smart(frames, limit=4)
    # Should return 4 unique frames
    assert len(selected) == 4
    indices = [ts // 1000 for ts, _ in selected]
    assert len(set(indices)) == 4  # all unique


def test_fewer_frames_than_limit_returns_all():
    frames = _make_frames(2)
    selected = _select_frames_smart(frames, limit=5)
    assert len(selected) == 2


def test_single_frame_returned_regardless_of_limit():
    frames = _make_frames(1)
    for limit in (1, 2, 3):
        selected = _select_frames_smart(frames, limit=limit)
        assert len(selected) == 1
        assert selected[0][0] == frames[0][0]


def test_no_duplicate_timestamps_in_selection():
    """Selected frames must all have distinct timestamps."""
    frames = _make_frames(20)
    for limit in (1, 2, 3, 4, 5):
        selected = _select_frames_smart(frames, limit=limit)
        ts_list = [ts for ts, _ in selected]
        assert len(ts_list) == len(set(ts_list)), \
            f"Duplicate timestamps for limit={limit}: {ts_list}"


# ── 5–7. Empty / edge cases ────────────────────────────────────────────────────

def test_empty_frames_list_returns_empty():
    selected = _select_frames_smart([], limit=3)
    assert selected == []


# ── 8–9. VisualReasoningService respects max_frames ───────────────────────────

def test_service_respects_max_frames():
    """Service analyzes exactly max_frames (or fewer if not enough frames)."""
    provider = MockReasoningProvider()
    svc = VisualReasoningService(provider=provider)
    frames = _make_frames(20)
    summary = svc.analyze_frames(frames, max_frames=3)
    assert summary.frames_analyzed == 3


def test_service_analyzes_all_when_fewer_frames_than_max():
    provider = MockReasoningProvider()
    svc = VisualReasoningService(provider=provider)
    frames = _make_frames(2)
    summary = svc.analyze_frames(frames, max_frames=5)
    assert summary.frames_analyzed == 2


# ── 10. Session summary has correct frames_analyzed count ─────────────────────

def test_session_summary_frames_analyzed_matches_selected():
    provider = MockReasoningProvider()
    svc = VisualReasoningService(provider=provider)
    frames = _make_frames(10)
    summary = svc.analyze_frames(frames, max_frames=3)
    assert summary.status == REASONING_STATUS_ANALYZED
    assert summary.frames_analyzed == 3


# ── 11. Two-session isolation ─────────────────────────────────────────────────

def test_two_sessions_have_independent_results():
    """Each analyze_frames call is independent — no cross-session contamination."""
    obs_a = VisualReasoningObservation(
        frame_index=0, timestamp_ms=1000, model_provider="mock",
        visual_summary="Session A: training UI visible",
        supported_skills=["Machine Learning"],
        detected_workflow_stage="model_training",
        confidence_score=0.9, status=REASONING_STATUS_ANALYZED,
    )
    obs_b = VisualReasoningObservation(
        frame_index=0, timestamp_ms=2000, model_provider="mock",
        visual_summary="Session B: dashboard with charts",
        supported_skills=["Data Visualization"],
        detected_workflow_stage="results_display",
        confidence_score=0.8, status=REASONING_STATUS_ANALYZED,
    )
    svc_a = VisualReasoningService(provider=MockReasoningProvider(observations=[obs_a]))
    svc_b = VisualReasoningService(provider=MockReasoningProvider(observations=[obs_b]))

    summary_a = svc_a.analyze_frames(_make_frames(1))
    summary_b = svc_b.analyze_frames(_make_frames(1))

    # Session A signals must not appear in session B
    assert "Machine Learning" in summary_a.supported_signals
    assert "Data Visualization" not in summary_a.supported_signals

    assert "Data Visualization" in summary_b.supported_signals
    assert "Machine Learning" not in summary_b.supported_signals


# ── 12. Private fields never in to_public_dict() ──────────────────────────────

def test_public_dict_no_private_fields():
    provider = MockReasoningProvider()
    svc = VisualReasoningService(provider=provider)
    frames = _make_frames(3)
    summary = svc.analyze_frames(frames, max_frames=2)
    public = summary.to_public_dict()

    private_keys = {"frame_storage_path", "raw_frame", "frame_bytes",
                    "access_token", "raw_dom", "debug_metadata"}
    for obs in public.get("observations", []):
        assert not any(k in obs for k in private_keys), \
            f"Private key found in public observation: {set(obs) & private_keys}"
