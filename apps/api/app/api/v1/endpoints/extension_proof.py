"""Extension Proof Session endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.db.supabase import SupabaseError
from app.schemas.extension_proof import (
    ExtensionProofSessionCreate,
    ExtensionProofSessionResponse,
)
from app.services.extension_proof_service import (
    ExtensionProofSessionNotFoundError,
    ExtensionProofSessionService,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "",
    response_model=ExtensionProofSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an extension proof session",
)
def create_session(
    body: ExtensionProofSessionCreate,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ExtensionProofSessionResponse:
    try:
        return ExtensionProofSessionService(db).create_session(user_id, body)
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


def _not_found(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "extension_proof_session_not_found",
            "message": "Extension proof session not found for the current user.",
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
