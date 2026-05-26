"""Student Work Passport status endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user_id, get_db
from app.schemas.work_passport_status import WorkPassportStatusResponse
from app.services.extension_proof_service import ExtensionProofSessionNotFoundError
from app.services.work_passport_status_service import WorkPassportStatusService

router = APIRouter()


@router.get(
    "/{session_id}/work-passport-status",
    response_model=WorkPassportStatusResponse,
    summary="Get centralized Work Passport status for a proof session",
)
def get_work_passport_status(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WorkPassportStatusResponse:
    try:
        return WorkPassportStatusService(db).get_work_passport_status(user_id, session_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "extension_proof_session_not_found",
                "message": "Extension proof session not found for the current user.",
                "session_id": session_id,
            },
        ) from exc
