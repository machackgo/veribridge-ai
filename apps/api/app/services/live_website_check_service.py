"""Live Website Check Service.

Performs a real HTTP reachability check for a deployed website URL.
Only runs on live public URLs — rejects localhost and private IP ranges.

Stores result in live_website_check_results table (migration 016).
If the table does not exist yet, degrades gracefully to updating the
session proof_data with the check result so it persists after refresh.

Guardrails:
  — does NOT access GitHub
  — does NOT mark Final Verification complete
  — only checks live_deployed_url; callers must gate on url_type
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx

from app.services.url_classification_service import (
    classify_website_url,
    local_private_live_check_note,
)

logger = logging.getLogger(__name__)

_TABLE = "live_website_check_results"
_SESSION_TABLE = "extension_proof_sessions"
_CHECKER_VERSION = "live-check-v1"

_TIMEOUT_SECONDS = 20.0
_MAX_HTML_BYTES = 200_000

class LiveWebsiteCheckService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def run_check(self, user_id: str, session_id: str, website_url: str) -> dict[str, Any]:
        """Run a live HTTP check on website_url and persist the result.

        Always returns a result dict. On DB failure degrades gracefully:
        stores result in session proof_data as fallback.
        Sets '_db_saved' key on the returned dict.
        """
        logger.info("LIVE_WEBSITE_CHECK_START session=%s url=%r", session_id, website_url[:80])

        classification = classify_website_url(website_url)
        if not classification.is_public_live_url:
            result = _not_applicable_result(website_url, classification.reason)
            logger.info(
                "LIVE_WEBSITE_CHECK_NOT_APPLICABLE session=%s reason=%r",
                session_id,
                classification.reason,
            )
            return self._persist(user_id, session_id, result)

        result = _perform_check(website_url)
        logger.info(
            "LIVE_WEBSITE_CHECK_DONE session=%s reachable=%s code=%s time=%sms conf=%s",
            session_id,
            result["is_reachable"],
            result.get("status_code"),
            result.get("response_time_ms"),
            result.get("confidence"),
        )
        return self._persist(user_id, session_id, result)

    def get_latest(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        """Return the latest live check result for this session, or None."""
        # 1. Try the dedicated table
        try:
            row = self._fetch_from_table(user_id, session_id)
            if row is not None:
                return row
        except Exception:
            logger.warning(
                "LIVE_WEBSITE_CHECK_FETCH_TABLE_FAILED session=%s",
                session_id, exc_info=True,
            )

        # 2. Fallback: check session proof_data
        try:
            return self._fetch_from_proof_data(user_id, session_id)
        except Exception:
            logger.warning(
                "LIVE_WEBSITE_CHECK_FETCH_PROOF_DATA_FAILED session=%s",
                session_id, exc_info=True,
            )
            return None

    # ── Persistence helpers ────────────────────────────────────────────────────

    def _persist(self, user_id: str, session_id: str, result: dict[str, Any]) -> dict[str, Any]:
        db_saved = False
        row: dict[str, Any]

        # 1. Try dedicated table
        try:
            row = self._upsert_to_table(user_id, session_id, result)
            db_saved = True
            logger.info("LIVE_WEBSITE_CHECK_DB_SAVED session=%s", session_id)
        except Exception:
            logger.warning(
                "LIVE_WEBSITE_CHECK_DB_FAILED session=%s — falling back to proof_data",
                session_id, exc_info=True,
            )
            row = {
                "id": f"mem-{session_id[:8]}",
                "user_id": user_id,
                "proof_session_id": session_id,
                **result,
            }
            # 2. Fallback: persist into session proof_data so it survives refresh
            try:
                self._patch_proof_data(user_id, session_id, result)
                db_saved = True
                logger.info("LIVE_WEBSITE_CHECK_PROOF_DATA_SAVED session=%s", session_id)
            except Exception:
                logger.warning(
                    "LIVE_WEBSITE_CHECK_PROOF_DATA_FAILED session=%s — result is in-memory only",
                    session_id, exc_info=True,
                )

        row["_db_saved"] = db_saved
        return row

    def _upsert_to_table(
        self, user_id: str, session_id: str, result: dict[str, Any]
    ) -> dict[str, Any]:
        now = _now()
        data = {
            "user_id": user_id,
            "proof_session_id": session_id,
            "checker_version": _CHECKER_VERSION,
            **result,
            "checked_at": result.get("checked_at", now),
        }
        # Remove synthetic keys before DB write
        data.pop("_db_saved", None)

        if isinstance(self._client, dict):
            existing = None
            store = self._client.setdefault(_TABLE, {})
            for r in store.values():
                if str(r.get("proof_session_id")) == session_id and str(r.get("user_id")) == user_id:
                    existing = r
                    break
            if existing:
                updated = {**existing, **data, "updated_at": now}
                store[existing["id"]] = updated
                return updated
            row = {"id": str(uuid4()), "created_at": now, "updated_at": now, **data}
            store[row["id"]] = row
            return row

        # Upsert via on_conflict on proof_session_id unique index
        try:
            result_db = (
                self._client.table(_TABLE)
                .upsert(data, on_conflict="proof_session_id")
                .execute()
            )
            rows = getattr(result_db, "data", []) or []
            if rows:
                return rows[0]
        except Exception:
            # Table might not have unique index yet — fall back to insert
            pass

        result_db = self._client.table(_TABLE).insert(data).execute()
        rows = getattr(result_db, "data", []) or []
        if not rows:
            raise RuntimeError("live_website_check_results insert returned no data.")
        return rows[0]

    def _fetch_from_table(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            store = self._client.get(_TABLE, {})
            for r in store.values():
                if str(r.get("proof_session_id")) == session_id and str(r.get("user_id")) == user_id:
                    return r
            return None

        result = (
            self._client.table(_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("proof_session_id", session_id)
            .order("checked_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _fetch_from_proof_data(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            session = self._client.get(_SESSION_TABLE, {}).get(session_id)
            if not session or session.get("user_id") != user_id:
                return None
            check = (session.get("proof_data") or {}).get("live_website_check")
            if check:
                return {"id": f"pd-{session_id[:8]}", "user_id": user_id, "proof_session_id": session_id, **check}
            return None

        result = (
            self._client.table(_SESSION_TABLE)
            .select("proof_data")
            .eq("user_id", user_id)
            .eq("id", session_id)
            .maybe_single()
            .execute()
        )
        if result is None or not isinstance(result.data, dict):
            return None
        proof_data = (result.data.get("proof_data") or {})
        if not isinstance(proof_data, dict):
            return None
        check = proof_data.get("live_website_check")
        if check and isinstance(check, dict):
            return {"id": f"pd-{session_id[:8]}", "user_id": user_id, "proof_session_id": session_id, **check}
        return None

    def _patch_proof_data(self, user_id: str, session_id: str, result: dict[str, Any]) -> None:
        if isinstance(self._client, dict):
            session = self._client.get(_SESSION_TABLE, {}).get(session_id)
            if session and session.get("user_id") == user_id:
                pd = dict(session.get("proof_data") or {})
                pd["live_website_check"] = result
                session["proof_data"] = pd
            return

        # Fetch current proof_data then merge
        fetch_result = (
            self._client.table(_SESSION_TABLE)
            .select("proof_data")
            .eq("user_id", user_id)
            .eq("id", session_id)
            .maybe_single()
            .execute()
        )
        if fetch_result is None:
            return
        current_pd: dict[str, Any] = dict((fetch_result.data or {}).get("proof_data") or {})
        current_pd["live_website_check"] = result
        self._client.table(_SESSION_TABLE).update(
            {"proof_data": current_pd, "updated_at": _now()}
        ).eq("user_id", user_id).eq("id", session_id).execute()


# ── URL validation ─────────────────────────────────────────────────────────────


def _validate_public_url(url: str) -> str | None:
    """Return an error string if the URL is not a checkable public URL, else None."""
    classification = classify_website_url(url)
    if classification.is_public_live_url:
        return None
    return f"{classification.reason} Only public deployed URLs are checked."


# ── HTTP check ────────────────────────────────────────────────────────────────


def _perform_check(url: str) -> dict[str, Any]:
    now = _now()
    start = time.monotonic()

    try:
        with httpx.Client(
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=True,
            max_redirects=5,
            headers={
                "Accept": "text/html,application/xhtml+xml,*/*",
                "User-Agent": "veribridge-proof-checker/1.0",
            },
        ) as client:
            response = client.get(url)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        final_url = str(response.url)
        status_code = response.status_code
        content_type = response.headers.get("content-type", "")[:200]

        page_title: str | None = None
        if "html" in content_type.lower():
            try:
                page_title = _extract_title(response.text[:_MAX_HTML_BYTES])
            except Exception:
                pass

        is_reachable = 100 <= status_code < 400
        risk_flags: list[str] = []

        if status_code >= 400:
            risk_flags.append(f"HTTP {status_code} response — site may be down or restricted.")
        if status_code in (401, 403):
            risk_flags.append("Site returned an auth-required or forbidden response. It may not be publicly accessible.")
        if elapsed_ms > 5000:
            risk_flags.append(f"Slow response time ({elapsed_ms}ms). Site may be under load or cold-starting.")

        # Check redirect
        if final_url.rstrip("/") != url.rstrip("/"):
            risk_flags.append(f"URL redirected to {final_url}")

        confidence = _compute_confidence(is_reachable, status_code, elapsed_ms, risk_flags)
        recruiter_summary = _build_summary(
            url=url,
            final_url=final_url,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
            page_title=page_title,
            confidence=confidence,
            is_reachable=is_reachable,
        )

        return {
            "status": "complete" if is_reachable else "failed",
            "website_url": url,
            "final_url": final_url if final_url != url else None,
            "status_code": status_code,
            "response_time_ms": elapsed_ms,
            "content_type": content_type or None,
            "page_title": page_title,
            "is_reachable": is_reachable,
            "confidence": confidence,
            "risk_flags": risk_flags,
            "recruiter_summary": recruiter_summary,
            "error_message": None,
            "checked_at": now,
        }

    except httpx.TimeoutException:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return _failed_result(url, f"Request timed out after {elapsed_ms // 1000}s.", now)
    except httpx.ConnectError as exc:
        return _failed_result(url, f"Could not connect to the server: {_safe_exc(exc)}", now)
    except httpx.HTTPError as exc:
        return _failed_result(url, f"HTTP error: {_safe_exc(exc)}", now)
    except Exception as exc:
        logger.warning("LIVE_WEBSITE_CHECK_UNEXPECTED url=%r err=%s", url, exc)
        return _failed_result(url, f"Unexpected error during check: {_safe_exc(exc)}", now)


def _failed_result(url: str, error: str, now: str | None = None) -> dict[str, Any]:
    return {
        "status": "failed",
        "website_url": url,
        "final_url": None,
        "status_code": None,
        "response_time_ms": None,
        "content_type": None,
        "page_title": None,
        "is_reachable": False,
        "confidence": "failed",
        "risk_flags": [error],
        "recruiter_summary": f"Live website check could not complete: {error} Check whether the deployed app is running, public, and not behind authentication.",
        "error_message": error,
        "checked_at": now or _now(),
    }


def _not_applicable_result(url: str, reason: str, now: str | None = None) -> dict[str, Any]:
    note = local_private_live_check_note()
    return {
        "status": "not_applicable",
        "website_url": url,
        "final_url": None,
        "status_code": None,
        "response_time_ms": None,
        "content_type": None,
        "page_title": None,
        "is_reachable": False,
        "confidence": "not_applicable",
        "risk_flags": [reason],
        "recruiter_summary": note,
        "error_message": None,
        "checked_at": now or _now(),
    }


def _compute_confidence(
    is_reachable: bool, status_code: int, elapsed_ms: int, risk_flags: list[str]
) -> str:
    if not is_reachable:
        return "failed"
    if status_code == 200 and elapsed_ms < 3000 and not risk_flags:
        return "high"
    if status_code < 400:
        return "medium"
    return "low"


def _build_summary(
    url: str,
    final_url: str,
    status_code: int,
    elapsed_ms: int,
    page_title: str | None,
    confidence: str,
    is_reachable: bool,
) -> str:
    if not is_reachable:
        return (
            f"Live website check failed — HTTP {status_code}. "
            "Check whether the deployed app is running, public, and not behind authentication."
        )
    parts = [f"Website is reachable and returned HTTP {status_code} in {elapsed_ms}ms."]
    if page_title:
        parts.append(f"Page title: {page_title}.")
    if final_url and final_url.rstrip("/") != url.rstrip("/"):
        parts.append(f"Request redirected to {final_url}.")
    parts.append("This supports that the deployed app is publicly accessible.")
    return " ".join(parts)


def _extract_title(html: str) -> str | None:
    import re
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        return " ".join(m.group(1).strip().split())[:200] or None
    return None


def _safe_exc(exc: Exception) -> str:
    return str(exc)[:120]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def build_completed_stages(is_reachable: bool, status: str = "") -> list[dict[str, Any]]:
    if status == "not_applicable":
        return [
            {"key": "validating_url",      "label": "Validating URL",              "status": "complete"},
            {"key": "checking_access",     "label": "Checking public accessibility","status": "complete"},
            {"key": "saving_result",       "label": "Saving not-applicable result", "status": "complete"},
        ]
    return [
        {"key": "validating_url",      "label": "Validating URL",              "status": "complete"},
        {"key": "checking_access",     "label": "Checking public accessibility","status": "complete"},
        {"key": "following_redirects", "label": "Following redirects",          "status": "complete"},
        {"key": "reading_metadata",    "label": "Reading page metadata",        "status": "complete"},
        {"key": "saving_result",       "label": "Saving result",                "status": "complete" if is_reachable else "failed"},
    ]
