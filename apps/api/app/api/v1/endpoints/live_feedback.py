"""Live Proof Feedback Agent endpoints.

POST /{session_id}/live-feedback  — extension pushes lightweight live signals;
                                     returns computed live feedback (in-memory, no DB).
GET  /{session_id}/live-feedback  — frontend polls for current live feedback state.

State is kept in-memory. Evicted when the process restarts or exceeds MAX_SESSIONS.
No migration required.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.schemas.live_feedback import LiveFeedbackState, LiveSignalsInput
from app.services.extension_proof_service import (
    ExtensionProofSessionNotFoundError,
    ExtensionProofSessionService,
)
from app.services.live_feedback_engine import compute_live_feedback

logger = logging.getLogger(__name__)
router = APIRouter()

# ── In-memory store ((user_id, session_id) → LiveFeedbackState) ───────────────
# Keyed per owner so a stale entry can never be served cross-user, even if the
# ownership gate below were ever bypassed. LRU-style eviction: once
# MAX_SESSIONS reached, evict the oldest entry.
MAX_SESSIONS = 500
_store: OrderedDict[tuple[str, str], LiveFeedbackState] = OrderedDict()


def _store_feedback(user_id: str, session_id: str, state: LiveFeedbackState) -> None:
    key = (user_id, session_id)
    if key in _store:
        _store.move_to_end(key)
    _store[key] = state
    if len(_store) > MAX_SESSIONS:
        _store.popitem(last=False)


def _require_owned_session(db: Any, user_id: str, session_id: str) -> None:
    """Fail closed before any live-feedback read/write for a Website Proof.

    Foreign and missing sessions must be indistinguishable: both raise the
    same 404 used by every other Website Proof side-evidence endpoint.
    """
    try:
        ExtensionProofSessionService(db).require_owned_session(user_id, session_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "extension_proof_session_not_found",
                "message": "Website Proof session not found.",
            },
        ) from exc


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/{session_id}/live-feedback",
    response_model=LiveFeedbackState,
    status_code=200,
    summary="Push live recording signals and receive live feedback",
)
def push_live_feedback(
    session_id: str,
    body: LiveSignalsInput,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> LiveFeedbackState:
    """
    Called by the Chrome extension every few events during recording.

    Accepts lightweight live signals (no raw DOM, no secrets), computes
    feedback in-memory using the live feedback engine, stores the result,
    and returns it so the extension popup can show it immediately.
    """
    _require_owned_session(db, user_id, session_id)
    state = compute_live_feedback(session_id, body)
    _store_feedback(user_id, session_id, state)
    logger.debug(
        "live_feedback: session=%s score=%d skills=%d suggestions=%d",
        session_id[:12], state.live_score, len(state.claimed_skill_support),
        len(state.suggestions),
    )
    return state


@router.get(
    "/{session_id}/live-feedback",
    response_model=LiveFeedbackState,
    summary="Poll current live feedback state",
)
def get_live_feedback(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> LiveFeedbackState:
    """
    Called by the frontend every few seconds while session.status === 'recording'.

    Returns the most recent live feedback snapshot pushed by the extension.
    If no snapshot exists yet (recording just started or extension hasn't pushed),
    returns a default zero-state so the frontend can show a 'waiting for signals'
    placeholder.
    """
    _require_owned_session(db, user_id, session_id)
    key = (user_id, session_id)
    if key in _store:
        return _store[key]
    # No snapshot yet — return a safe default so the frontend can render
    return LiveFeedbackState(
        session_id=session_id,
        recording_status="recording",
        checklist={},  # type: ignore[arg-type]
        live_score=0,
        claimed_skill_support=[],
        suggestions=["Start recording — waiting for live signals from the extension."],
        sensitive_warning=False,
        last_updated_at=datetime.now(timezone.utc),
    )
