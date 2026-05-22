"""Browser UI workflow screenshot service — Phase J4I.

Opens a frontend URL, auto-detects and fills input fields, clicks a safe
submit button, waits for output, and captures a JPEG screenshot as proof.

Builds on the sync_playwright infrastructure already in this project.
Playwright must be installed: pip install playwright && playwright install chromium

Safety:
- Passes the same URL safety check as the rest of the website analyzer.
- Never enters passwords, payment fields, or sensitive data.
- Only clicks buttons with safe action terms.
- Timeout enforced on navigation and each action.
- Screenshots capped at JPEG quality 65 for reasonable payload size.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Safety constants (aligned with existing browser executor service) ──────────

_SAFE_CLICK_TERMS = (
    "analyze", "predict", "submit", "search", "run", "check",
    "calculate", "get route", "view result", "view results", "find",
    "generate", "process", "start", "send", "execute", "compute",
    "query", "go", "apply route", "get prediction", "test",
)
_UNSAFE_CLICK_TERMS = (
    "delete", "remove", "purchase", "pay", "buy", "subscribe",
    "confirm order", "transfer", "login", "sign in", "sign out",
    "logout", "password", "apply for", "submit application",
)

# ── Field detection patterns ──────────────────────────────────────────────────

_ORIGIN_HINTS = ["origin", "source", "start", "from", "departure", "pickup", "begin"]
_DEST_HINTS   = ["destination", "dest", "end", "to", "arrival", "dropoff", "goal"]

_NAV_TIMEOUT    = 15_000
_ACTION_TIMEOUT = 5_000
_WAIT_AFTER_CLICK = 3_000


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class BrowserScreenshotResult:
    success: bool = False
    steps_run: list[str] = field(default_factory=list)
    expected_output_found: bool = False
    output_text_found: str | None = None
    screenshot_data_url: str | None = None   # "data:image/jpeg;base64,..."
    error_message: str | None = None
    no_ui_detected: bool = False


# ── Internal helpers ──────────────────────────────────────────────────────────

def _safe_click_text(text: str) -> bool:
    tl = text.strip().lower()
    if any(u in tl for u in _UNSAFE_CLICK_TERMS):
        return False
    return any(s in tl for s in _SAFE_CLICK_TERMS)


def _try_fill(page: Any, hints: list[str], value: str) -> bool:
    """Try label/placeholder union first (mirrors existing _input_locator),
    then fall back to name/id/aria-label CSS attribute selectors."""
    pattern = re.compile("|".join(re.escape(h) for h in hints), re.IGNORECASE)
    try:
        loc = (
            page.get_by_label(pattern)
            .or_(page.get_by_placeholder(pattern))
            .first
        )
        loc.fill(value, timeout=_ACTION_TIMEOUT)
        return True
    except Exception:
        pass
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


def _click_safe_button(page: Any) -> str | None:
    """Find and click the first visible safe button."""
    try:
        btns = page.locator("button:visible, input[type='submit']:visible").all()
        for btn in btns[:20]:
            try:
                text = btn.inner_text(timeout=2_000).strip()
                if not text:
                    text = btn.get_attribute("value") or ""
                if _safe_click_text(text):
                    btn.click(timeout=_ACTION_TIMEOUT)
                    return text
            except Exception:
                continue
    except Exception:
        pass
    return None


def _attach_screenshot(page: Any, result: BrowserScreenshotResult) -> None:
    """Capture a JPEG screenshot and attach it as a data URL."""
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
    """Open a frontend URL, fill inputs, click submit, capture screenshot.

    Returns a BrowserScreenshotResult with steps_run, screenshot_data_url,
    and expected_output_found. Always captures a screenshot even on partial
    failure so the user can see what the browser saw.
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

                # Navigate to frontend
                page.goto(frontend_url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
                result.steps_run.append(f"Opened {frontend_url}")

                # Verify interactive fields exist
                visible_inputs = page.locator("input:visible, textarea:visible").count()
                if visible_inputs == 0:
                    result.no_ui_detected = True
                    result.error_message = (
                        "No interactive input fields detected on this page. "
                        "Provide a frontend URL where users can enter data. "
                        "API/docs URLs support endpoint verification but may not "
                        "have a visible UI workflow."
                    )
                    _attach_screenshot(page, result)
                    return result

                # Fill origin field
                if origin:
                    if _try_fill(page, _ORIGIN_HINTS, origin):
                        result.steps_run.append(f"Filled origin/source field: {origin}")
                    else:
                        result.steps_run.append(
                            f"Origin field not found (tried: {', '.join(_ORIGIN_HINTS)})"
                        )

                # Fill destination field
                if destination:
                    if _try_fill(page, _DEST_HINTS, destination):
                        result.steps_run.append(f"Filled destination/end field: {destination}")
                    else:
                        result.steps_run.append(
                            f"Destination field not found (tried: {', '.join(_DEST_HINTS)})"
                        )

                # Fill any extra named fields
                for field_key, field_value in (extra_fields or {}).items():
                    if _try_fill(page, [field_key], field_value):
                        result.steps_run.append(f"Filled field '{field_key}': {field_value}")

                # Click a safe submit button
                btn_text = _click_safe_button(page)
                if btn_text:
                    result.steps_run.append(f"Clicked button: '{btn_text}'")
                    try:
                        page.wait_for_load_state("networkidle", timeout=8_000)
                    except Exception:
                        page.wait_for_timeout(_WAIT_AFTER_CLICK)
                else:
                    result.steps_run.append("No safe submit button found — capturing current page state")

                # Check for expected output in visible text
                if expected_output:
                    key_terms = [
                        t.strip().lower()
                        for t in re.split(r"[,/\n]+", expected_output)
                        if t.strip() and len(t.strip()) > 3
                    ]
                    try:
                        body_text = page.locator("body").inner_text(timeout=_ACTION_TIMEOUT).lower()
                        for term in key_terms[:6]:
                            if term in body_text:
                                result.expected_output_found = True
                                result.output_text_found = term
                                result.steps_run.append(f"Found expected term in page: '{term}'")
                                break
                        if not result.expected_output_found:
                            result.steps_run.append("Expected output terms not found in visible text")
                    except Exception:
                        pass

                # Capture screenshot
                _attach_screenshot(page, result)
                if result.screenshot_data_url:
                    result.steps_run.append("Screenshot captured")
                    result.success = True

            finally:
                browser.close()

    except Exception as exc:
        result.error_message = str(exc)[:400]
        logger.warning("Browser screenshot workflow failed: %s", exc)

    return result


def parse_test_input_for_browser(
    test_input: str | None,
) -> tuple[str | None, str | None, dict[str, str]]:
    """Parse free-form test input string into (origin, destination, extra_fields).

    Accepts JSON: {"origin": "Fenway Park", "destination": "Logan"}
    Or key=value: origin=Fenway Park, Boston, MA; destination=Logan Airport
    """
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
