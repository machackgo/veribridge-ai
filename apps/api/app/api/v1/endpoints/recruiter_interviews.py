"""Recruiter Interview Workspace endpoints (migration 069).

Authenticated with the standard Supabase JWT and mounted under
``/api/v1/recruiter/briefs`` beside the Hiring Brief routes. Every route
resolves ownership through the owning brief (foreign == missing → the
same generic 404); the verification checklist and question grading are
re-run from LIVE public evidence on every load — nothing here can serve
evidence the candidate has since unpublished.

Analytics: coarse counts only via the existing brief-event discipline —
``interview_opened`` on workspace load and ``interview_questions`` on
generation. NEVER notes, titles, or candidate identity. The autosave
PATCH records no analytics at all.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user_id, get_db
from app.api.v1.endpoints.recruiter_hiring_briefs import (
    _brief_error,
    _not_found,
    _record_brief_event,
)
from app.schemas.recruiter_interviews import (
    ChecklistMarksResponse,
    GenerateQuestionsRequest,
    InterviewQuestionsResponse,
    InterviewResponse,
    InterviewWorkspaceResponse,
    SetChecklistMarkRequest,
    UpdateInterviewRequest,
)
from app.services.recruiter_hiring_brief_service import BriefError, BriefNotFound
from app.services.recruiter_interview_service import (
    generate_questions,
    get_interview_workspace,
    set_checklist_mark,
    update_interview,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/{brief_id}/candidates/{student_user_id}/interview",
    response_model=InterviewWorkspaceResponse,
    summary="The pair's interview workspace with the live evidence checklist",
)
def get_interview_workspace_route(
    brief_id: str,
    student_user_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> InterviewWorkspaceResponse:
    try:
        payload = get_interview_workspace(db, str(user_id), brief_id, student_user_id)
    except BriefNotFound:
        raise _not_found()
    except BriefError as exc:
        raise _brief_error(exc)
    _record_brief_event(db, str(user_id), "interview_opened", count=0)
    return InterviewWorkspaceResponse(**payload)


@router.patch(
    "/{brief_id}/candidates/{student_user_id}/interview",
    response_model=InterviewResponse,
    summary="Upsert the pair's recruiter-private interview details",
)
def update_interview_route(
    brief_id: str,
    student_user_id: str,
    payload: UpdateInterviewRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> InterviewResponse:
    sent = payload.model_fields_set
    try:
        view = update_interview(
            db,
            str(user_id),
            brief_id,
            student_user_id,
            scheduled_at=payload.scheduled_at if "scheduled_at" in sent else ...,
            interviewer_name=payload.interviewer_name
            if "interviewer_name" in sent
            else ...,
            prep_notes=payload.prep_notes if "prep_notes" in sent else ...,
            notes=payload.notes if "notes" in sent else ...,
            decision_notes=payload.decision_notes
            if "decision_notes" in sent
            else ...,
            clear_scheduled_at=payload.clear_scheduled_at,
            clear_interviewer_name=payload.clear_interviewer_name,
            clear_prep_notes=payload.clear_prep_notes,
            clear_notes=payload.clear_notes,
            clear_decision_notes=payload.clear_decision_notes,
        )
    except BriefNotFound:
        raise _not_found()
    except BriefError as exc:
        raise _brief_error(exc)
    # Deliberately NO analytics here: this is a debounced autosave target.
    return InterviewResponse(interview=view)


@router.post(
    "/{brief_id}/candidates/{student_user_id}/interview/questions",
    response_model=InterviewQuestionsResponse,
    summary="Generate evidence-grounded interview questions (never a score)",
)
def generate_questions_route(
    brief_id: str,
    student_user_id: str,
    payload: GenerateQuestionsRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> InterviewQuestionsResponse:
    try:
        questions = generate_questions(
            db,
            str(user_id),
            brief_id,
            student_user_id,
            regenerate=payload.regenerate,
        )
    except BriefNotFound:
        raise _not_found()
    except BriefError as exc:
        raise _brief_error(exc)
    _record_brief_event(
        db,
        str(user_id),
        "interview_questions",
        count=len(questions.get("items") or []),
    )
    return InterviewQuestionsResponse(questions=questions)


@router.post(
    "/{brief_id}/candidates/{student_user_id}/interview/checklist",
    response_model=ChecklistMarksResponse,
    summary="Set or clear one recruiter-private checklist mark",
)
def set_checklist_mark_route(
    brief_id: str,
    student_user_id: str,
    payload: SetChecklistMarkRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ChecklistMarksResponse:
    try:
        marks = set_checklist_mark(
            db,
            str(user_id),
            brief_id,
            student_user_id,
            requirement_key=payload.requirement_key,
            state=payload.state,
        )
    except BriefNotFound:
        raise _not_found()
    except BriefError as exc:
        raise _brief_error(exc)
    return ChecklistMarksResponse(marks=marks)


__all__ = ["router"]
