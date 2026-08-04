"""Controlled browser proof session endpoints — Manual Login Handoff."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id
from app.schemas.website_proof_session import (
    WebsiteProofSessionCreateRequest,
    WebsiteProofSessionResumeResponse,
)
from app.services.website_proof_session_service import (
    SessionExpiredError,
    SessionNotFoundError,
    close_proof_session,
    create_proof_session,
    get_proof_session,
    resume_proof_session,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "",
    response_model=WebsiteProofSessionResumeResponse,
    summary="Create a controlled browser proof session",
)
def create_session(
    body: WebsiteProofSessionCreateRequest,
    user_id: str = Depends(get_current_user_id),
) -> WebsiteProofSessionResumeResponse:
    """
    Launch a Playwright browser session for the given URL.

    - If a login wall is detected, returns `status=waiting_for_manual_login`.
      The browser window stays open for the user to log in manually.
    - If no login wall is detected, runs the workflow immediately and
      returns `status=completed` with a screenshot.
    """
    try:
        return create_proof_session(body, user_id)
    except Exception as exc:
        logger.exception("POST /website-proof/sessions: unexpected error")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "session_create_failed", "message": str(exc)[:300]},
        ) from exc


@router.get(
    "/{session_id}",
    response_model=WebsiteProofSessionResumeResponse,
    summary="Get proof session status",
)
def get_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
) -> WebsiteProofSessionResumeResponse:
    try:
        return get_proof_session(session_id, user_id)
    except SessionNotFoundError as exc:
        raise _session_not_found(session_id) from exc
    except SessionExpiredError as exc:
        raise _session_expired(session_id) from exc


@router.post(
    "/{session_id}/resume",
    response_model=WebsiteProofSessionResumeResponse,
    summary="Resume proof session after manual login",
)
def resume_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
) -> WebsiteProofSessionResumeResponse:
    """
    After the user has manually logged in, call this endpoint to:
    1. Re-check if the login wall is gone.
    2. If still on login page: return `status=waiting_for_manual_login`.
    3. If authenticated: run the browser workflow and capture proof.
    """
    try:
        return resume_proof_session(session_id, user_id)
    except SessionNotFoundError as exc:
        raise _session_not_found(session_id) from exc
    except SessionExpiredError as exc:
        raise _session_expired(session_id) from exc
    except Exception as exc:
        logger.exception("POST /website-proof/sessions/%s/resume: unexpected error", session_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "session_resume_failed", "message": str(exc)[:300]},
        ) from exc


@router.post(
    "/{session_id}/close",
    summary="Close and clean up a proof session",
)
def close_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, str]:
    """
    Close the Playwright context, delete the temp user_data_dir (cookies),
    and remove the session from memory. Safe to call at any time.

    A foreign or unknown session is a silent no-op with the same response,
    so callers cannot probe for other users' sessions.
    """
    close_proof_session(session_id, user_id)
    return {"status": "closed", "session_id": session_id}


# ── Error helpers ─────────────────────────────────────────────────────────────

def _session_not_found(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "proof_session_not_found",
            "message": "Proof session not found. It may have expired or been closed.",
            "session_id": session_id,
        },
    )


def _session_expired(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "proof_session_expired",
            "message": "Proof session expired (15 min TTL). Create a new session to retry.",
            "session_id": session_id,
        },
    )
