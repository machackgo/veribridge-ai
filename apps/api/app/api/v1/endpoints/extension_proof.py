"""Extension Proof Session endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db, get_provisioned_user_id
from app.db.supabase import SupabaseError
from app.schemas.extension_proof import (
    ExtensionProofCompleteResponse,
    ExtensionProofSessionCreate,
    ExtensionProofSessionResponse,
    ExtensionProofStartResponse,
    ExtensionProofUploadRequest,
    ExtensionProofUploadResponse,
)
from app.services.extension_proof_service import (
    ExtensionProofSessionNotFoundError,
    ExtensionProofSessionService,
    InvalidSessionTransitionError,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "",
    response_model=list[ExtensionProofSessionResponse],
    summary="List the current student's Website Proof sessions",
)
def list_sessions(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> list[ExtensionProofSessionResponse]:
    try:
        return ExtensionProofSessionService(db).list_sessions(user_id)
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("GET /student/extension-proof/sessions: unexpected error")
        raise _database_unavailable(exc) from exc


@router.post(
    "",
    response_model=ExtensionProofSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an extension proof session",
)
def create_session(
    body: ExtensionProofSessionCreate,
    # First write of the Website Proof flow: provision the fresh caller's own
    # public.users row so the session insert never hits a 23503 FK violation.
    user_id: str = Depends(get_provisioned_user_id),
    db: Any = Depends(get_db),
) -> ExtensionProofSessionResponse:
    try:
        if body.project_id:
            # get_db is service-role scoped, so ownership must be checked
            # explicitly before an external project id can become evidence.
            from app.api.v1.endpoints.vbr_projects import get_owned_vbr_project_or_404

            get_owned_vbr_project_or_404(db, body.project_id, user_id)
        return ExtensionProofSessionService(db).create_session(user_id, body)
    except HTTPException:
        # Preserve the ownership-safe 404 from the project lookup. Converting it
        # to a database 503 would hide the actual validation result and make a
        # foreign project relationship indistinguishable from an outage.
        raise
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("POST /student/extension-proof/sessions: unexpected error")
        raise _database_unavailable(exc) from exc


@router.get(
    "/{session_id}",
    response_model=ExtensionProofSessionResponse,
    summary="Get an extension proof session",
)
def get_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ExtensionProofSessionResponse:
    try:
        return ExtensionProofSessionService(db).get_session(user_id, session_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise _not_found(session_id) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("GET /student/extension-proof/sessions/%s: unexpected error", session_id)
        raise _database_unavailable(exc) from exc


@router.post(
    "/{session_id}/start",
    response_model=ExtensionProofStartResponse,
    summary="Start recording for an extension proof session",
)
def start_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ExtensionProofStartResponse:
    try:
        return ExtensionProofSessionService(db).start_session(user_id, session_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise _not_found(session_id) from exc
    except InvalidSessionTransitionError as exc:
        raise _invalid_transition(session_id, str(exc)) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("POST /student/extension-proof/sessions/%s/start: unexpected error", session_id)
        raise _database_unavailable(exc) from exc


@router.post(
    "/{session_id}/upload",
    response_model=ExtensionProofUploadResponse,
    summary="Upload proof data to an extension proof session",
)
def upload_proof(
    session_id: str,
    body: ExtensionProofUploadRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ExtensionProofUploadResponse:
    try:
        return ExtensionProofSessionService(db).upload_proof(user_id, session_id, body)
    except ExtensionProofSessionNotFoundError as exc:
        raise _not_found(session_id) from exc
    except InvalidSessionTransitionError as exc:
        raise _invalid_transition(session_id, str(exc)) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("POST /student/extension-proof/sessions/%s/upload: unexpected error", session_id)
        raise _database_unavailable(exc) from exc


@router.post(
    "/{session_id}/complete",
    response_model=ExtensionProofCompleteResponse,
    summary="Complete an extension proof session and queue for analysis",
)
def complete_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ExtensionProofCompleteResponse:
    try:
        return ExtensionProofSessionService(db).complete_session(user_id, session_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise _not_found(session_id) from exc
    except InvalidSessionTransitionError as exc:
        raise _invalid_transition(session_id, str(exc)) from exc
    except SupabaseError as exc:
        raise _database_unavailable(exc) from exc
    except Exception as exc:
        logger.exception("POST /student/extension-proof/sessions/%s/complete: unexpected error", session_id)
        raise _database_unavailable(exc) from exc


# ── Error helpers ─────────────────────────────────────────────────────────────

def _not_found(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "extension_proof_session_not_found",
            "message": "Extension proof session not found for the current user.",
            "session_id": session_id,
        },
    )


def _invalid_transition(session_id: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "invalid_session_transition",
            "message": message,
            "session_id": session_id,
        },
    )


def _database_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "database_unavailable",
            "message": "The extension proof session store is temporarily unavailable.",
        },
    )
