"""Browser UI workflow screenshot service — Phase J4I / J4J.

Opens a frontend URL, auto-detects and fills input fields, clicks a safe
submit button, waits for output to appear, then captures a JPEG screenshot
as visual proof of the completed workflow.

Fix history (J4J):
- Multi-strategy button detection handles "Predict Route Risk" and similar
- Screenshot captured AFTER output/result appears, not at input-fill time
- Autocomplete / Places dropdown handling after field fill
- Active output waiting with generic + user-provided indicator terms
- Proof summary generated from completed steps
- browser_workflow_status: passed / partial / failed

Builds on sync_playwright infrastructure already in this project.
Setup: pip install playwright && playwright install chromium
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Safety constants ──────────────────────────────────────────────────────────

# Compiled regex for safe action buttons
_SAFE_BUTTON_RE = re.compile(
    r"predict|analyz|analy[sz]e route|submit|search|route|risk|calculate|calc|"
    r"\brun\b|\bgo\b|find|generate|check|process|get result|view result|compute|"
    r"start|forecast|plan|optimize|verify|apply route|get prediction|"
    r"get route|analyze route|route risk|predict risk",
    re.IGNORECASE,
)

_UNSAFE_CLICK_TERMS = (
    "delete", "remove", "purchase", "pay", "buy", "subscribe",
    "confirm order", "transfer", "login", "sign in", "sign out",
    "logout", "password", "apply for job", "submit application",
    "clear all", "reset all", "cancel subscription",
)

# Generic output indicator terms — used as a BASELINE FILTER, not direct detectors.
# Terms already visible before clicking (legend items, static labels) are excluded
# dynamically via baseline comparison.
_OUTPUT_INDICATOR_TERMS = frozenset([
    "risk", "confidence", "route", "weather", "recommendation",
    "result", "prediction", "score", "low", "medium", "high",
    "safer", "distance", "duration", "output", "analysis",
    "class", "probability", "percent", "minutes", "miles",
    "km", "level", "alert", "warning", "segment", "accident",
    "danger", "safe", "optimal", "fastest",
])

# Phrases that indicate a RESULT card / new output appeared.
# Must be specific enough that they only appear in result output, NOT in
# static header/legend text. Each phrase is also filtered against the baseline
# page capture before being counted as evidence of new content.
_RESULT_INDICATOR_PHRASES = [
    "default route", "alternative route",
    "showing result", "showing route", "route comparison",
    "safer route", "risk class:", "confidence:", "risk level:",
    "risk score:", "route result", "accident hotspot",
    "fastest route", "optimal route", "recommended route",
    "route 1", "route 2", "route option",
    "hotspot area", "avoid hotspot",
]

# ── Field detection patterns ──────────────────────────────────────────────────

_ORIGIN_HINTS = ["origin", "source", "start", "from", "departure", "pickup", "begin"]
_DEST_HINTS   = ["destination", "dest", "end", "to", "arrival", "dropoff", "goal"]

_NAV_TIMEOUT       = 15_000
_ACTION_TIMEOUT    = 5_000
_POST_CLICK_WAIT   = 3_000   # min wait after click before starting output detection
_OUTPUT_WAIT_MAX   = 45_000  # max wait for NEW output after click (45s for cold starts)
_LOADING_WAIT_MAX  = 15_000  # max wait for loading spinners to disappear


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class BrowserScreenshotResult:
    success: bool = False
    steps_run: list[str] = field(default_factory=list)
    expected_output_found: bool = False
    output_text_found: str | None = None
    output_terms_found: list[str] = field(default_factory=list)
    button_text_clicked: str | None = None
    browser_workflow_status: str = "failed"   # "passed" | "partial" | "failed"
    proof_summary: str = ""
    screenshot_data_url: str | None = None   # "data:image/jpeg;base64,..."
    error_message: str | None = None
    no_ui_detected: bool = False
    frontend_visible_output_text: str | None = None  # body.innerText after workflow


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_unsafe(text: str) -> bool:
    tl = text.lower()
    return any(u in tl for u in _UNSAFE_CLICK_TERMS)


def _try_fill(page: Any, hints: list[str], value: str) -> bool:
    """Try multiple strategies to find and fill an input field."""
    pattern = re.compile("|".join(re.escape(h) for h in hints), re.IGNORECASE)

    # Strategy 1: label / placeholder union (mirrors existing _input_locator)
    try:
        loc = (
            page.get_by_label(pattern)
            .or_(page.get_by_placeholder(pattern))
            .first
        )
        if loc.count() > 0 and loc.is_visible():
            loc.fill(value, timeout=_ACTION_TIMEOUT)
            return True
    except Exception:
        pass

    # Strategy 2: CSS attribute selectors
    for hint in hints:
        for attr in ("name", "id", "aria-label", "placeholder"):
            try:
                sel = (
                    f"input[{attr}*='{hint}' i]:visible,"
                    f" textarea[{attr}*='{hint}' i]:visible"
                )
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    loc.fill(value, timeout=_ACTION_TIMEOUT)
                    return True
            except Exception:
                continue
    return False


def _handle_autocomplete(page: Any) -> None:
    """After filling a field, dismiss or select any autocomplete dropdown."""
    try:
        page.wait_for_timeout(800)
        # Common autocomplete dropdown selectors
        for sel in [
            ".pac-item:visible",          # Google Places
            "[role='option']:visible",
            "[role='listbox'] li:visible",
            ".suggestion:visible",
            "[class*='suggestion']:visible",
            "[class*='autocomplete'] li:visible",
            "[class*='dropdown'] li:visible",
        ]:
            try:
                option = page.locator(sel).first
                if option.count() > 0 and option.is_visible():
                    option.click(timeout=2_000)
                    page.wait_for_timeout(400)
                    return
            except Exception:
                continue
    except Exception:
        pass


def _click_safe_button(page: Any) -> str | None:
    """Find and click a safe submit button using five strategies.

    Priority: role+regex > filter(has_text) > input[type=submit] >
              iterate buttons > [role=button] elements
    """
    # Strategy 1: get_by_role with compiled regex (most reliable)
    try:
        btn = page.get_by_role("button", name=_SAFE_BUTTON_RE).first
        if btn.count() > 0 and btn.is_visible():
            text = btn.inner_text(timeout=2_000).strip()
            if text and not _is_unsafe(text):
                btn.click(timeout=_ACTION_TIMEOUT)
                return text
    except Exception:
        pass

    # Strategy 2: button.filter(has_text=regex)
    try:
        btn = page.locator("button").filter(has_text=_SAFE_BUTTON_RE).first
        if btn.count() > 0 and btn.is_visible():
            text = btn.inner_text(timeout=2_000).strip()
            if text and not _is_unsafe(text):
                btn.click(timeout=_ACTION_TIMEOUT)
                return text
    except Exception:
        pass

    # Strategy 3: input[type=submit]
    try:
        for submit in page.locator("input[type='submit']:visible").all()[:5]:
            try:
                val = (submit.get_attribute("value") or "").strip()
                if val and _SAFE_BUTTON_RE.search(val) and not _is_unsafe(val):
                    submit.click(timeout=_ACTION_TIMEOUT)
                    return val
            except Exception:
                continue
    except Exception:
        pass

    # Strategy 4: iterate all visible buttons + [role='button']
    try:
        for btn in page.locator("button:visible, [role='button']:visible").all()[:30]:
            try:
                text = btn.inner_text(timeout=1_000).strip()
                if not text:
                    text = (btn.get_attribute("aria-label") or btn.get_attribute("title") or "").strip()
                if not text or _is_unsafe(text):
                    continue
                if _SAFE_BUTTON_RE.search(text):
                    btn.click(timeout=_ACTION_TIMEOUT)
                    return text
            except Exception:
                continue
    except Exception:
        pass

    # Strategy 5: any clickable element with safe text
    try:
        for loc in page.locator("[onclick]:visible, [type='submit']:visible").all()[:10]:
            try:
                text = loc.inner_text(timeout=1_000).strip()
                if text and not _is_unsafe(text) and _SAFE_BUTTON_RE.search(text):
                    loc.click(timeout=_ACTION_TIMEOUT)
                    return text
            except Exception:
                continue
    except Exception:
        pass

    return None


def _capture_baseline_text(page: Any) -> str:
    """Capture visible body text before the submit action.

    Used to compute which terms / phrases are already present in static UI
    (e.g. legend labels "Low / Medium / High", header text "Route Risk") so
    they are excluded from new-content detection after clicking.
    """
    try:
        return page.locator("body").inner_text(timeout=3_000).lower()
    except Exception:
        return ""


def _wait_for_new_content(
    page: Any,
    baseline_text: str,
    user_expected: str | None,
    max_wait_ms: int = _OUTPUT_WAIT_MAX,
) -> tuple[bool, list[str]]:
    """Wait for NEW output content to appear after the submit click.

    Strategy:
    1. Exclude terms already present in ``baseline_text`` so static legend
       words ("risk", "route", "low", "medium", "high") don't trigger a false
       positive.
    2. Check for result-indicator *phrases* (e.g. "default route",
       "recommended", "risk class:") — these only appear in result cards.
    3. Track body text length growth as a coarse change signal.
    4. Return (new_content_detected, list_of_new_terms).
    """
    # Build candidate terms — only those absent from the baseline page
    candidate_terms: set[str] = set()
    for t in _OUTPUT_INDICATOR_TERMS:
        if t not in baseline_text:
            candidate_terms.add(t)
    # Add user-provided expected output terms
    if user_expected:
        for t in re.split(r"[,/\n ]+", user_expected):
            t = t.strip().lower()
            if len(t) >= 3 and t not in baseline_text:
                candidate_terms.add(t)

    baseline_len = len(baseline_text)
    end_time = time.time() + max_wait_ms / 1000.0
    best_terms: list[str] = []

    while time.time() < end_time:
        try:
            body = page.locator("body").inner_text(timeout=3_000).lower()

            # ── Phrase detection: only NEW phrases absent from baseline ────────
            found_phrases = [
                p for p in _RESULT_INDICATOR_PHRASES
                if p in body and p not in baseline_text
            ]

            # ── Term detection: only terms absent from baseline ───────────────
            found_terms = [t for t in candidate_terms if t in body]

            # ── Text growth signal ────────────────────────────────────────────
            text_grew = (len(body) - baseline_len) > 200

            # A new result phrase is the strongest signal — return immediately
            if found_phrases:
                return True, found_phrases + found_terms[:3]

            if len(found_terms) > len(best_terms):
                best_terms = found_terms

            # Many new terms + substantial text growth also confirms a result
            if len(found_terms) >= 3 and text_grew:
                return True, found_terms

        except Exception:
            pass

        try:
            page.wait_for_timeout(1_500)
        except Exception:
            break

    # Timeout — only report detected if we have multiple new terms (weak signal)
    detected = len(best_terms) >= 3
    return detected, best_terms


def _generate_proof_summary(
    frontend_url: str,
    origin: str | None,
    destination: str | None,
    button_text: str | None,
    expected_output_found: bool,
    output_terms_found: list[str],
    no_ui_detected: bool,
    error_message: str | None,
) -> str:
    """Build a natural-language proof summary of what Playwright did."""
    if no_ui_detected:
        return (
            f"VeriBridge opened {frontend_url} but could not detect interactive input fields. "
            "Provide a frontend URL where users can enter data."
        )
    if error_message and not button_text:
        return (
            f"VeriBridge opened {frontend_url} but the browser workflow could not complete. "
            f"Reason: {error_message[:200]}"
        )

    parts: list[str] = [f"VeriBridge opened the live frontend at {frontend_url}"]
    if origin:
        parts.append(f"filled the From/Origin field with \"{origin}\"")
    if destination:
        parts.append(f"filled the To/Destination field with \"{destination}\"")
    if button_text:
        parts.append(f"clicked \"{button_text}\"")
        parts.append("waited for the result to appear")
    parts.append("and captured a screenshot of the browser state")

    summary = ", ".join(parts) + "."

    if expected_output_found and output_terms_found:
        summary += (
            " VeriBridge captured the final UI output after the workflow completed."
            f" New output detected: {', '.join(output_terms_found[:6])}."
        )
    elif expected_output_found:
        summary += " VeriBridge captured the final UI output after the workflow completed."
    else:
        summary += (
            " VeriBridge captured the current browser state, but final output was not"
            " confirmed before the screenshot was taken. Review the screenshot manually"
            " to confirm the result appeared."
        )

    return summary


def _wait_for_loading_to_finish(page: Any, max_ms: int = _LOADING_WAIT_MAX) -> bool:
    """Wait for loading/analyzing spinners and text to disappear.

    Returns True if loading finished cleanly within max_ms.
    Common patterns: "Analyzing...", spinner elements, aria-busy, disabled buttons.
    """
    _LOADING_TEXT_RE = re.compile(
        r"\banalyzing\b|\bloading\b|\bplease wait\b|\bcalculating\b|\bprocessing\b",
        re.IGNORECASE,
    )
    _SPINNER_SELECTORS = [
        "[class*='spinner']:visible",
        "[class*='loading']:visible",
        "[class*='progress']:visible",
        "[aria-busy='true']:visible",
        "[class*='skeleton']:visible",
    ]
    end = time.time() + max_ms / 1000.0
    while time.time() < end:
        try:
            # Check for loading text in visible page body
            body = page.locator("body").inner_text(timeout=2_000)
            has_loading_text = bool(_LOADING_TEXT_RE.search(body))

            # Check for spinner elements
            has_spinner = False
            for sel in _SPINNER_SELECTORS:
                try:
                    if page.locator(sel).count() > 0:
                        has_spinner = True
                        break
                except Exception:
                    continue

            if not has_loading_text and not has_spinner:
                return True
        except Exception:
            pass
        try:
            page.wait_for_timeout(1_200)
        except Exception:
            break
    return False


def _extract_visible_output_text(page: Any, max_chars: int = 3_000) -> str | None:
    """Capture visible body text for API metric-to-visual matching."""
    try:
        text = page.locator("body").inner_text(timeout=3_000)
        if len(text) > max_chars:
            text = text[:max_chars] + "…"
        return text.strip() or None
    except Exception:
        return None


def _attach_screenshot(page: Any, result: BrowserScreenshotResult) -> None:
    """Capture JPEG screenshot and attach as data URL."""
    try:
        jpeg_bytes = page.screenshot(full_page=False, type="jpeg", quality=65)
        b64 = base64.b64encode(jpeg_bytes).decode("utf-8")
        result.screenshot_data_url = f"data:image/jpeg;base64,{b64}"
    except Exception as exc:
        logger.warning("Screenshot capture failed: %s", exc)


# ── Public API ─────────────────────────────────────────────────────────────────

def run_browser_screenshot(
    frontend_url: str,
    origin: str | None = None,
    destination: str | None = None,
    extra_fields: dict[str, str] | None = None,
    expected_output: str | None = None,
) -> BrowserScreenshotResult:
    """Open a frontend URL, fill inputs, click submit, wait for output, capture screenshot.

    Screenshot is taken AFTER the submit button is clicked and output is waited for —
    not at the input-fill stage.
    """
    result = BrowserScreenshotResult()

    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        result.error_message = (
            "Playwright is not installed. "
            "Run: pip install playwright && playwright install chromium"
        )
        return result

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 "
                        "VeriBridge-UI-Verifier/1.0"
                    ),
                    ignore_https_errors=False,
                )
                page = ctx.new_page()
                page.set_default_timeout(_ACTION_TIMEOUT)
                page.set_default_navigation_timeout(_NAV_TIMEOUT)

                # ── Step 1: Navigate ──────────────────────────────────────────
                page.goto(frontend_url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
                result.steps_run.append(f"Opened {frontend_url}")

                # ── Step 2: Verify interactive fields exist ───────────────────
                visible_inputs = page.locator("input:visible, textarea:visible").count()
                if visible_inputs == 0:
                    result.no_ui_detected = True
                    result.error_message = (
                        "No interactive input fields detected on this page. "
                        "Provide a frontend URL where users can enter data. "
                        "API/docs URLs support endpoint verification but may not "
                        "have a visible UI workflow."
                    )
                    result.steps_run.append("No visible input fields found")
                    _attach_screenshot(page, result)
                    result.proof_summary = _generate_proof_summary(
                        frontend_url, origin, destination, None,
                        False, [], True, result.error_message,
                    )
                    return result

                result.steps_run.append(f"Found {visible_inputs} visible input field(s)")

                # ── Step 3: Fill origin field ─────────────────────────────────
                if origin:
                    if _try_fill(page, _ORIGIN_HINTS, origin):
                        result.steps_run.append(f"Filled origin/source field: \"{origin}\"")
                        _handle_autocomplete(page)
                    else:
                        result.steps_run.append(
                            f"Origin field not found — tried: {', '.join(_ORIGIN_HINTS)}"
                        )

                # ── Step 4: Fill destination field ────────────────────────────
                if destination:
                    if _try_fill(page, _DEST_HINTS, destination):
                        result.steps_run.append(f"Filled destination/to field: \"{destination}\"")
                        _handle_autocomplete(page)
                    else:
                        result.steps_run.append(
                            f"Destination field not found — tried: {', '.join(_DEST_HINTS)}"
                        )

                # ── Step 5: Fill any extra named fields ───────────────────────
                for fk, fv in (extra_fields or {}).items():
                    if _try_fill(page, [fk], fv):
                        result.steps_run.append(f"Filled field '{fk}': \"{fv}\"")

                # ── Step 6: Capture baseline text BEFORE clicking ─────────────
                result.steps_run.append("Capturing baseline page state before clicking...")
                baseline_text = _capture_baseline_text(page)

                # ── Step 7: Click safe submit button ──────────────────────────
                btn_text = _click_safe_button(page)
                if btn_text:
                    result.button_text_clicked = btn_text
                    result.steps_run.append(f"Clicked button: \"{btn_text}\"")
                else:
                    result.steps_run.append(
                        "No safe submit button found — looked for: predict, analyze, "
                        "submit, search, route, risk, calculate, run, find, generate"
                    )

                # ── Step 8: Wait for network / loading to settle ───────────────
                try:
                    page.wait_for_load_state("networkidle", timeout=8_000)
                    result.steps_run.append("Network settled after click")
                except Exception:
                    page.wait_for_timeout(_POST_CLICK_WAIT)
                    result.steps_run.append("Waited for page to stabilize after click")

                result.steps_run.append("Waiting for loading/analyzing state to finish...")
                loading_done = _wait_for_loading_to_finish(page, _LOADING_WAIT_MAX)
                if loading_done:
                    result.steps_run.append("Loading state finished — page ready for output detection")
                else:
                    result.steps_run.append("Loading may still be active — proceeding to output detection")

                # ── Step 9: Wait for NEW content after click (up to 45s) ───────
                result.steps_run.append(
                    "Waiting for new output/result cards to appear (up to 45s for cold starts)..."
                )
                new_content_found, output_terms = _wait_for_new_content(
                    page, baseline_text, expected_output, _OUTPUT_WAIT_MAX
                )
                result.output_terms_found = output_terms

                if new_content_found and output_terms:
                    result.expected_output_found = True
                    result.output_text_found = ", ".join(output_terms[:5])
                    result.steps_run.append(
                        f"Final output detected — new content: {', '.join(output_terms[:6])}"
                    )
                else:
                    result.steps_run.append(
                        "Final output not confirmed before timeout — capturing current state"
                    )

                # ── Step 10: Capture screenshot (AFTER output detection) ────────
                result.steps_run.append("Capturing screenshot of final browser state")
                _attach_screenshot(page, result)
                # Also capture visible body text for metric-to-visual matching
                result.frontend_visible_output_text = _extract_visible_output_text(page)
                if result.screenshot_data_url:
                    result.success = True
                    if result.expected_output_found:
                        result.steps_run.append("Screenshot captured — final output visible")
                        result.browser_workflow_status = "passed"
                    else:
                        result.steps_run.append(
                            "Screenshot captured — final output not confirmed before timeout"
                        )
                        result.browser_workflow_status = "partial"
                else:
                    result.steps_run.append("Screenshot could not be captured")
                    result.browser_workflow_status = "partial" if btn_text else "failed"

            finally:
                browser.close()

    except Exception as exc:
        result.error_message = str(exc)[:400]
        result.browser_workflow_status = "failed"
        logger.warning("Browser screenshot workflow failed: %s", exc)

    # ── Generate proof summary ────────────────────────────────────────────────
    result.proof_summary = _generate_proof_summary(
        frontend_url=frontend_url,
        origin=origin,
        destination=destination,
        button_text=result.button_text_clicked,
        expected_output_found=result.expected_output_found,
        output_terms_found=result.output_terms_found,
        no_ui_detected=result.no_ui_detected,
        error_message=result.error_message,
    )

    return result


# ── Test input parser ─────────────────────────────────────────────────────────

def parse_test_input_for_browser(
    test_input: str | None,
) -> tuple[str | None, str | None, dict[str, str]]:
    """Parse free-form test input → (origin, destination, extra_fields)."""
    if not test_input:
        return None, None, {}

    parsed: dict[str, Any] = {}
    t = test_input.strip()

    if t.startswith("{"):
        try:
            parsed = json.loads(t)
        except Exception:
            pass

    if not parsed:
        for raw in re.split(r"[;\n]+", t):
            raw = raw.strip()
            m = re.search(r"[=:]", raw)
            if m:
                key = raw[: m.start()].strip()
                val = raw[m.end():].strip()
                if key and val:
                    parsed[key] = val

    origin: str | None = None
    destination: str | None = None
    extra: dict[str, str] = {}

    for k, v in parsed.items():
        kl = k.lower()
        vs = str(v)
        if any(h in kl for h in _ORIGIN_HINTS):
            origin = vs
        elif any(h in kl for h in _DEST_HINTS):
            destination = vs
        else:
            extra[k] = vs

    return origin, destination, extra
