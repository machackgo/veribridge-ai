"""Unit tests for browser_screenshot_service baseline-aware output detection.

These tests verify the NEW-content detection logic introduced in Part B:
- Static legend terms ("risk", "route", "low", "medium", "high") that exist
  BEFORE clicking must NOT trigger a false-positive detection.
- Only terms / phrases that appear AFTER clicking count as result evidence.
- browser_workflow_status must be "partial" when no new content is detected.

No Playwright browser is launched — all page interaction is mocked.
"""
from __future__ import annotations

import pytest

from app.services.browser_screenshot_service import (
    _capture_baseline_text,
    _RESULT_INDICATOR_PHRASES,
    _wait_for_new_content,
)


# ── Minimal page stub ─────────────────────────────────────────────────────────

class _PageStub:
    """Synchronous page stub that returns a sequence of body texts."""

    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self._idx = 0

    def locator(self, selector: str) -> "_LocatorStub":
        text = self._texts[min(self._idx, len(self._texts) - 1)]
        self._idx += 1
        return _LocatorStub(text)

    def wait_for_timeout(self, ms: int) -> None:  # noqa: ARG002
        pass  # instant in tests


class _LocatorStub:
    def __init__(self, text: str) -> None:
        self._text = text

    def inner_text(self, timeout: int = 3000) -> str:  # noqa: ARG002
        return self._text


# ── Helpers ───────────────────────────────────────────────────────────────────

_STATIC_PAGE = (
    "Boston Smart Accident Risk\n"
    "From:\nTo:\n"
    "Low  Medium  High\n"
    "Route risk predictor — enter your route to predict accident risk.\n"
    "Predict Route Risk"
)

_RESULT_PAGE = (
    "Boston Smart Accident Risk\n"
    "From: Fenway Park  To: Logan Airport\n"
    "Low  Medium  High\n"
    "Default route: Fenway Park → Logan Airport  12 miles  18 min\n"
    "Risk class: High  Confidence: 0.82\n"
    "Alternative route: via I-90 E  safer option detected\n"
    "Route 1: Direct  Route 2: Via Tunnel\n"
    "Accident hotspot: 3 hotspot areas on this path\n"
    "Recommended route: take I-90 E to avoid hotspot areas\n"
)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_baseline_excludes_static_legend_terms():
    """Terms already visible before click must not count as new output."""
    baseline = _STATIC_PAGE.lower()
    # All of these are in the static page — they should be in baseline
    for term in ("risk", "route", "low", "medium", "high"):
        assert term in baseline, f"Expected '{term}' in baseline fixture"


def test_result_phrases_detected_after_click():
    """Result-indicator phrases present after click trigger detection."""
    baseline = _STATIC_PAGE.lower()
    result_body = _RESULT_PAGE.lower()
    # At least one phrase from _RESULT_INDICATOR_PHRASES must be in result
    found = [p for p in _RESULT_INDICATOR_PHRASES if p in result_body]
    assert found, (
        f"No result phrases found in result page. Phrases checked: {_RESULT_INDICATOR_PHRASES}"
    )
    # None of them should be in the static baseline
    in_baseline = [p for p in found if p in baseline]
    assert not in_baseline, (
        f"These result phrases were already in the static page: {in_baseline}"
    )


def test_wait_for_new_content_passes_when_result_appears():
    """_wait_for_new_content returns (True, terms) when result card appears."""
    # Page returns static text first, then result text on second call
    page = _PageStub([_STATIC_PAGE, _RESULT_PAGE, _RESULT_PAGE])
    baseline = _STATIC_PAGE.lower()

    detected, terms = _wait_for_new_content(
        page, baseline, user_expected=None, max_wait_ms=5_000
    )
    assert detected is True
    assert len(terms) > 0


def test_wait_for_new_content_partial_when_no_result():
    """_wait_for_new_content returns (False, []) when page never changes."""
    # Page always returns the same static text
    page = _PageStub([_STATIC_PAGE] * 10)
    baseline = _STATIC_PAGE.lower()

    detected, terms = _wait_for_new_content(
        page, baseline, user_expected=None, max_wait_ms=200  # very short timeout
    )
    assert detected is False
    # Static legend terms ("risk", "route") must NOT appear in terms
    for t in ("risk", "route", "low", "medium", "high"):
        assert t not in terms, (
            f"Static term '{t}' leaked into output terms — baseline filtering failed"
        )


def test_user_expected_terms_excluded_when_in_baseline():
    """User-provided expected terms that already appear in static page are excluded."""
    # If the user says "risk" is the expected output, but "risk" is in the baseline,
    # it should be filtered out — otherwise a false positive occurs.
    baseline = _STATIC_PAGE.lower()
    page = _PageStub([_STATIC_PAGE] * 5)

    detected, terms = _wait_for_new_content(
        page, baseline, user_expected="risk, route", max_wait_ms=200
    )
    assert detected is False


def test_user_expected_terms_counted_when_new():
    """User-provided expected terms that appear only in result page count."""
    baseline = _STATIC_PAGE.lower()
    # User says "confidence: 0.82" is expected — only appears in result page
    page = _PageStub([_STATIC_PAGE, _RESULT_PAGE, _RESULT_PAGE])

    detected, terms = _wait_for_new_content(
        page, baseline, user_expected="confidence, recommended", max_wait_ms=5_000
    )
    assert detected is True
