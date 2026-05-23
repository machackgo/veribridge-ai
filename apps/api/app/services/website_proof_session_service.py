"""Controlled browser proof session service — Manual Login Handoff.

Architecture (local MVP):
- Each proof session gets a Playwright persistent context in a temp directory.
- The browser window is visible (headful) so the user can log in manually.
- Sessions are kept alive in-memory until the user resumes or closes them.
- After proof is captured, context + temp directory are destroyed.

Security invariants:
- Passwords are never logged, stored, or transmitted.
- user_data_dir (cookies, storage) is deleted on session close.
- Sessions expire automatically after SESSION_TTL_SECONDS.
- No auth cookies are persisted to the database.

TODO(production): For cloud/headless deployment replace headful Playwright with
one of: remote browser streaming, noVNC, browserless.io, or an isolated ephemeral
container per proof session. The session lifecycle API stays the same.
"""

from __future__ import annotations

import base64
import logging
import os
import shutil
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.schemas.website_proof_session import (
    WebsiteProofSessionCreateRequest,
    WebsiteProofSessionResumeResponse,
)

logger = logging.getLogger(__name__)

_SESSION_TTL_SECONDS = 15 * 60  # 15 minutes
_SESSION_BASE_DIR = "/tmp/veribridge-proof-sessions"
_NAV_TIMEOUT = 15_000
_ACTION_TIMEOUT = 5_000

# In-memory session store: session_id → _ActiveSession
_SESSIONS: dict[str, "_ActiveSession"] = {}
_LOCK = threading.Lock()

# ── Login wall detection signals ─────────────────────────────────────────────

_LOGIN_URL_PATTERNS = (
    "/login", "/signin", "/sign-in", "/auth", "/oauth",
    "/account/login", "login?", "sign_in", "signIn",
)

_LOGIN_TEXT_SIGNALS = (
    "sign in", "log in", "welcome back", "continue with google",
    "continue with github", "enter your email", "enter your password",
    "forgot password", "remember me", "don't have an account",
    "create account", "login to continue", "please sign in",
)


class SessionNotFoundError(LookupError):
    """No active proof session found for the given session_id."""


class SessionExpiredError(RuntimeError):
    """Proof session has exceeded its TTL."""


# ── Internal session dataclass ────────────────────────────────────────────────

@dataclass
class _ActiveSession:
    session_id: str
    auth_mode: str
    website_url: str
    frontend_url: str | None
    test_input: str | None
    expected_output: str | None
    workflow_instructions: str | None
    status: str
    created_at: datetime
    expires_at: datetime
    user_data_dir: str | None = None
    _pw: Any = field(default=None, repr=False)
    _browser: Any = field(default=None, repr=False)
    _page: Any = field(default=None, repr=False)
    login_screenshot: str | None = None
    final_screenshot: str | None = None
    final_page_text: str | None = None
    steps_run: list[str] = field(default_factory=list)
    proof_summary: str | None = None
    error_message: str | None = None
    login_url: str | None = None


# ── Public API ────────────────────────────────────────────────────────────────

def create_proof_session(
    request: WebsiteProofSessionCreateRequest,
) -> WebsiteProofSessionResumeResponse:
    """Launch a controlled browser session and detect login wall."""
    _expire_stale_sessions()

    session_id = uuid4().hex
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=_SESSION_TTL_SECONDS)
    user_data_dir = os.path.join(_SESSION_BASE_DIR, session_id)
    os.makedirs(user_data_dir, exist_ok=True)

    session = _ActiveSession(
        session_id=session_id,
        auth_mode=request.auth_mode,
        website_url=request.website_url,
        frontend_url=request.frontend_url,
        test_input=request.test_input,
        expected_output=request.expected_output,
        workflow_instructions=request.workflow_instructions,
        status="created",
        created_at=now,
        expires_at=expires_at,
        user_data_dir=user_data_dir,
    )

    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        session.status = "failed"
        session.error_message = (
            "Playwright not installed. "
            "Run: pip install playwright && playwright install chromium"
        )
        with _LOCK:
            _SESSIONS[session_id] = session
        return _to_response(session)

    try:
        # TODO(production): For cloud, replace headful launch with remote streaming.
        pw = sync_playwright().start()
        session._pw = pw

        # Persistent context: keeps cookies/storage across navigation in the same session.
        # headless=False: user can see and interact with the visible browser window.
        browser_context = pw.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 "
                "VeriBridge-Proof-Session/1.0"
            ),
            ignore_https_errors=False,
        )
        session._browser = browser_context

        page = browser_context.pages[0] if browser_context.pages else browser_context.new_page()
        session._page = page
        page.set_default_timeout(_ACTION_TIMEOUT)
        page.set_default_navigation_timeout(_NAV_TIMEOUT)

        target_url = request.frontend_url or request.website_url
        page.goto(target_url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
        session.steps_run.append(f"Opened {target_url}")
        session.status = "running"

        if _detect_login_wall(page):
            session.status = "waiting_for_manual_login"
            session.login_url = page.url
            session.login_screenshot = _screenshot_b64(page)
            session.steps_run.append(
                "Login wall detected — browser is open, waiting for manual login"
            )
        else:
            # No login wall: run workflow immediately
            session.status = "authenticated_ready"
            session.steps_run.append("No login wall detected — running workflow immediately")
            _run_browser_workflow(session, page)

    except Exception as exc:
        session.error_message = str(exc)[:400]
        session.status = "failed"
        logger.exception("Proof session %s failed during creation", session_id)
        _destroy_session_context(session)

    with _LOCK:
        _SESSIONS[session_id] = session

    return _to_response(session)


def resume_proof_session(session_id: str) -> WebsiteProofSessionResumeResponse:
    """Check login status and continue workflow if authenticated."""
    _expire_stale_sessions()

    with _LOCK:
        session = _SESSIONS.get(session_id)

    if session is None:
        raise SessionNotFoundError(session_id)

    if datetime.now(UTC) > session.expires_at:
        _cleanup_and_remove(session_id)
        raise SessionExpiredError(session_id)

    if session.status in ("completed", "partial", "failed", "expired"):
        return _to_response(session)

    page = session._page
    if page is None:
        session.status = "failed"
        session.error_message = "Browser page no longer available."
        return _to_response(session)

    # Re-check login wall
    if _detect_login_wall(page):
        session.login_url = page.url
        session.steps_run.append("Resume: login still detected — complete login and try again")
        return _to_response(session)

    # Login complete — run the workflow
    session.status = "resumed"
    session.steps_run.append("Resume: login no longer detected — running workflow")
    _run_browser_workflow(session, page)

    # Schedule cleanup 60s after completion so response can be retrieved
    if session.status in ("completed", "partial"):
        _schedule_cleanup(session_id, delay_seconds=60)

    return _to_response(session)


def close_proof_session(session_id: str) -> None:
    """Close and permanently destroy a proof session."""
    _cleanup_and_remove(session_id)


def get_proof_session(session_id: str) -> WebsiteProofSessionResumeResponse:
    """Return current session status."""
    _expire_stale_sessions()
    with _LOCK:
        session = _SESSIONS.get(session_id)
    if session is None:
        raise SessionNotFoundError(session_id)
    return _to_response(session)


# ── Browser workflow ──────────────────────────────────────────────────────────

def _run_browser_workflow(session: _ActiveSession, page: Any) -> None:
    """Fill inputs, click action button, wait for output, capture screenshot."""
    try:
        from app.services.browser_screenshot_service import (  # noqa: PLC0415
            _DEST_HINTS,
            _LOADING_WAIT_MAX,
            _ORIGIN_HINTS,
            _OUTPUT_WAIT_MAX,
            _capture_baseline_text,
            _click_safe_button,
            _dest_keywords,
            _handle_autocomplete_smart,
            _keyword_in_value,
            _origin_keywords,
            _read_field_value,
            _try_fill,
            _type_into_field,
            _wait_for_loading_to_finish,
            _wait_for_new_content,
            parse_test_input_for_browser,
        )
    except ImportError as exc:
        session.error_message = f"browser_screenshot_service import failed: {exc}"
        session.status = "partial"
        return

    try:
        origin, destination, extra = parse_test_input_for_browser(session.test_input)

        # Fill origin
        origin_confirmed = False
        if origin:
            origin_kw = _origin_keywords(origin)
            session.steps_run.append(f"Filling origin field: \"{origin}\"")
            loc = _type_into_field(page, _ORIGIN_HINTS, origin)
            if loc is not None:
                _handle_autocomplete_smart(page, origin_kw)
                actual = _read_field_value(page, _ORIGIN_HINTS)
                origin_confirmed = _keyword_in_value(actual, origin_kw)
                session.steps_run.append(
                    f"Origin confirmed: \"{actual}\"" if origin_confirmed
                    else f"Origin unconfirmed (got: \"{actual}\")"
                )
            else:
                _try_fill(page, _ORIGIN_HINTS, origin)
                session.steps_run.append("Origin field filled (no locator found)")

        # Fill destination
        dest_confirmed = False
        if destination:
            dest_kw = _dest_keywords(destination)
            session.steps_run.append(f"Filling destination field: \"{destination}\"")
            loc = _type_into_field(page, _DEST_HINTS, destination)
            if loc is not None:
                _handle_autocomplete_smart(page, dest_kw)
                actual = _read_field_value(page, _DEST_HINTS)
                dest_confirmed = _keyword_in_value(actual, dest_kw)
                session.steps_run.append(
                    f"Destination confirmed: \"{actual}\"" if dest_confirmed
                    else f"Destination unconfirmed (got: \"{actual}\")"
                )
            else:
                _try_fill(page, _DEST_HINTS, destination)
                session.steps_run.append("Destination field filled (no locator found)")

        # Capture baseline before clicking
        baseline_text = _capture_baseline_text(page)

        # Click safe button
        btn_text = _click_safe_button(page)
        if btn_text:
            session.steps_run.append(f"Clicked: \"{btn_text}\"")
        else:
            session.steps_run.append("No safe action button found")

        # Wait for output
        if btn_text:
            try:
                page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                page.wait_for_timeout(3_000)
            _wait_for_loading_to_finish(page, _LOADING_WAIT_MAX)
            new_content, output_terms = _wait_for_new_content(
                page, baseline_text, session.expected_output, _OUTPUT_WAIT_MAX
            )
            if new_content:
                session.steps_run.append(f"Output detected: {', '.join(output_terms[:5])}")
            else:
                session.steps_run.append("Output not confirmed before timeout")

        # Capture final screenshot + page text
        session.final_screenshot = _screenshot_b64(page)
        session.final_page_text = _extract_page_text(page)
        session.status = "completed"

        auth_desc = "Authenticated workflow" if session.auth_mode == "manual_login_handoff" else "Workflow"
        session.proof_summary = (
            f"{auth_desc} proof captured at {session.frontend_url or session.website_url}. "
            f"{len(session.steps_run)} steps run."
        )
        session.steps_run.append("Screenshot captured — workflow complete")

    except Exception as exc:
        session.error_message = str(exc)[:300]
        session.status = "partial"
        session.steps_run.append(f"Workflow error: {type(exc).__name__}")
        try:
            session.final_screenshot = _screenshot_b64(page)
        except Exception:
            pass


# ── Login detection ───────────────────────────────────────────────────────────

def _detect_login_wall(page: Any) -> bool:
    """Return True if the page appears to be a login/auth wall."""
    url = (page.url or "").lower()
    if any(p in url for p in _LOGIN_URL_PATTERNS):
        return True
    try:
        if page.locator("input[type='password']:visible").count() > 0:
            return True
    except Exception:
        pass
    try:
        body = page.locator("body").inner_text(timeout=3_000).lower()
        hit_count = sum(1 for sig in _LOGIN_TEXT_SIGNALS if sig in body)
        if hit_count >= 2:
            return True
    except Exception:
        pass
    return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _screenshot_b64(page: Any) -> str | None:
    try:
        jpeg_bytes = page.screenshot(full_page=False, type="jpeg", quality=65)
        return "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode()
    except Exception:
        return None


def _extract_page_text(page: Any, max_chars: int = 3_000) -> str | None:
    try:
        text = page.locator("body").inner_text(timeout=3_000)
        return (text[:max_chars] + "…") if len(text) > max_chars else text.strip() or None
    except Exception:
        return None


def _to_response(session: _ActiveSession) -> WebsiteProofSessionResumeResponse:
    return WebsiteProofSessionResumeResponse(
        session_id=session.session_id,
        status=session.status,
        auth_mode=session.auth_mode,
        login_url=session.login_url,
        login_screenshot=session.login_screenshot,
        final_screenshot=session.final_screenshot,
        final_page_text=session.final_page_text,
        steps_run=list(session.steps_run),
        proof_summary=session.proof_summary,
        error_message=session.error_message,
        expires_at=session.expires_at.isoformat(),
        created_at=session.created_at.isoformat(),
    )


def _destroy_session_context(session: _ActiveSession) -> None:
    """Close Playwright context and delete temp user_data_dir."""
    try:
        if session._browser:
            session._browser.close()
    except Exception:
        pass
    try:
        if session._pw:
            session._pw.stop()
    except Exception:
        pass
    if session.user_data_dir:
        import shutil as _shutil  # noqa: PLC0415
        _shutil.rmtree(session.user_data_dir, ignore_errors=True)
    session._browser = None
    session._pw = None
    session._page = None


def _cleanup_and_remove(session_id: str) -> None:
    with _LOCK:
        session = _SESSIONS.pop(session_id, None)
    if session:
        _destroy_session_context(session)
        session.status = "expired"
        logger.info("Proof session %s closed and cleaned up", session_id)


def _expire_stale_sessions() -> None:
    """Evict expired sessions on each API call."""
    now = datetime.now(UTC)
    with _LOCK:
        expired = [sid for sid, s in _SESSIONS.items() if now > s.expires_at]
    for sid in expired:
        logger.info("Expiring stale proof session %s", sid)
        _cleanup_and_remove(sid)


def _schedule_cleanup(session_id: str, delay_seconds: int = 60) -> None:
    """Schedule async cleanup in a daemon thread after delay."""
    import threading as _threading  # noqa: PLC0415
    import time as _time  # noqa: PLC0415

    def _do_cleanup() -> None:
        _time.sleep(delay_seconds)
        _cleanup_and_remove(session_id)

    t = _threading.Thread(target=_do_cleanup, daemon=True, name=f"session-cleanup-{session_id}")
    t.start()
