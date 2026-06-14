"""Project Defense endpoints (Phase 1 — individual project defense MVP).

Lets a student create an individual Project Defense identity, attach
existing GitHub/Website/Document/Skill Graph proof sources, generate
deterministic defense questions, submit pasted/manual answers, and run a
deterministic (non-LLM) analysis.

Team proof, live screen/camera recording, speaker diarization, and final
public report publishing are out of scope for Phase 1.

``get_db`` returns the service-role Supabase client which bypasses RLS, so
every route here manually checks ``user_id`` ownership via
``get_owned_vbr_project_or_404`` / ``get_owned_vbr_session_or_404``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.api.v1.endpoints.vbr_projects import (
    _advance_project_status,
    _to_project_response,
    _to_question_response,
    get_owned_vbr_project_or_404,
)
from app.schemas.vbr_project_defense import (
    DefenseAnalysisResponse,
    GenerateDefenseQuestionsResponse,
    ProjectDefenseCreateRequest,
    ProjectDefenseCreateResponse,
    ProjectDefenseMetadataResponse,
    SubmitDefenseAnswersRequest,
    SubmitDefenseAnswersResponse,
)
from app.services.vbr_project_defense import (
    create_project_defense,
    generate_defense_questions,
    submit_defense_answers,
)
from app.services.vbr_session_recording import get_owned_vbr_session_or_404

router = APIRouter()


_CREATE_ERROR_DETAILS: dict[str, tuple[int, str, str]] = {
    "repo_url_required": (
        status.HTTP_400_BAD_REQUEST,
        "vbr_repo_url_required",
        "Provide a repo_url or attach a GitHub proof with a repository URL to create a project defense.",
    ),
    "invalid_github_repo_url": (
        status.HTTP_400_BAD_REQUEST,
        "vbr_invalid_github_repo_url",
        "repo_url must be a supported GitHub repository URL.",
    ),
    "github_proof_not_found": (
        status.HTTP_404_NOT_FOUND,
        "vbr_github_proof_not_found",
        "GitHub proof was not found for the current user.",
    ),
    "document_evidence_not_found": (
        status.HTTP_404_NOT_FOUND,
        "vbr_document_evidence_not_found",
        "One or more attached documents were not found for the current user.",
    ),
    "website_proof_not_found": (
        status.HTTP_404_NOT_FOUND,
        "vbr_website_proof_not_found",
        "One or more attached Website Proof sessions were not found for the current user.",
    ),
    "skill_pipeline_not_found": (
        status.HTTP_404_NOT_FOUND,
        "vbr_skill_pipeline_not_found",
        "One or more attached skill pipelines were not found for the current user.",
    ),
}


@router.post(
    "/project-defense",
    response_model=ProjectDefenseCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an individual Project Defense identity",
)
def create_project_defense_route(
    body: ProjectDefenseCreateRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> ProjectDefenseCreateResponse:
    try:
        row = create_project_defense(db, pipeline_db, user_id, body)
    except ValueError as exc:
        detail = _CREATE_ERROR_DETAILS.get(str(exc))
        if detail is None:
            raise
        code_status, code, message = detail
        raise HTTPException(status_code=code_status, detail={"code": code, "message": message}) from exc

    return ProjectDefenseCreateResponse(
        project=_to_project_response(row),
        metadata=ProjectDefenseMetadataResponse(**(row.get("metadata") or {})),
    )


@router.post(
    "/projects/{project_id}/generate-defense-questions",
    response_model=GenerateDefenseQuestionsResponse,
    summary="Generate deterministic project defense questions",
)
def generate_defense_questions_route(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> GenerateDefenseQuestionsResponse:
    project = get_owned_vbr_project_or_404(db, project_id, user_id)

    try:
        session_id, questions = generate_defense_questions(db, project)
    except ValueError as exc:
        if str(exc) == "active_session_already_started":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "vbr_active_session_already_started",
                    "message": "A recording session has already started for this project.",
                },
            ) from exc
        raise

    _advance_project_status(db, project, "questions_ready")

    return GenerateDefenseQuestionsResponse(
        project_id=project_id,
        session_id=session_id,
        status="questions_ready",
        questions=[_to_question_response(row) for row in questions],
    )


@router.post(
    "/sessions/{session_id}/submit-defense",
    response_model=SubmitDefenseAnswersResponse,
    summary="Submit pasted/manual project defense answers and run deterministic analysis",
)
def submit_defense_answers_route(
    session_id: str,
    body: SubmitDefenseAnswersRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> SubmitDefenseAnswersResponse:
    session, project = get_owned_vbr_session_or_404(db, session_id, user_id)

    try:
        result = submit_defense_answers(db, session, project, body)
    except ValueError as exc:
        if str(exc) == "no_answers_provided":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "vbr_no_answers_provided",
                    "message": "Provide at least one answer or a combined explanation before submitting.",
                },
            ) from exc
        raise

    return SubmitDefenseAnswersResponse(
        project_id=str(project["id"]),
        session_id=session_id,
        transcript_id=result["transcript_id"],
        segment_count=result["segment_count"],
        answered_question_count=result["answered_question_count"],
        analysis=DefenseAnalysisResponse(**result["analysis"]),
        video_evidence_chips=result.get("video_evidence_chips", []),
    )
