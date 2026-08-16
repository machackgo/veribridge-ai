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

from app.api.deps import (
    get_current_user_id,
    get_db,
    get_pipeline_db,
    get_provisioned_user_id,
)
from app.api.v1.endpoints.vbr_projects import (
    _advance_project_status,
    _to_project_response,
    _to_question_response,
    get_owned_vbr_project_or_404,
)
from app.schemas.vbr_project_defense import (
    AttachedProofsRequest,
    AttachProofsResponse,
    DefenseAnalysisResponse,
    EligibleProjectResponse,
    EligibleProjectsResponse,
    GenerateDefenseQuestionsResponse,
    ProjectDefenseContextResponse,
    ProjectDefenseCreateRequest,
    ProjectDefenseCreateResponse,
    ProjectDefenseMetadataResponse,
    SafeProjectDefenseMetadataResponse,
    SubmitDefenseAnswersRequest,
    SubmitDefenseAnswersResponse,
)
from app.schemas.vbr_public_project_report import ProjectReportPublishStatusResponse
from app.schemas.vbr_student_report import VBRStudentProjectReportResponse
from app.services.project_defense_artifact_sync_service import ProjectDefenseArtifactSyncService
from app.services.recruiter_search_service import refresh_search_projection
from app.services.vbr_project_defense import (
    attach_proofs_to_project,
    build_project_defense_context,
    create_new_defense_session,
    create_project_defense,
    generate_defense_questions,
    list_deduped_eligible_summaries,
    merge_owned_project,
    submit_defense_answers,
)
from app.services.vbr_public_project_report import (
    get_project_report_publish_status,
    publish_project_report,
    unpublish_project_report,
)
from app.services.vbr_session_recording import get_owned_vbr_session_or_404
from app.services.vbr_student_report import build_student_vbr_report

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
    "github_proof_repo_mismatch": (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "vbr_github_proof_repo_mismatch",
        "This GitHub proof's repository does not match the project's repository. "
        "Attach the GitHub proof for the project's own repository, or select/create "
        "the project that matches this proof.",
    ),
}


@router.get(
    "/project-defense/eligible-projects",
    response_model=EligibleProjectsResponse,
    summary="List the current user's projects that can be defended",
)
def list_eligible_projects_route(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> EligibleProjectsResponse:
    summaries = list_deduped_eligible_summaries(db, user_id)
    return EligibleProjectsResponse(
        projects=[EligibleProjectResponse(**summary) for summary in summaries]
    )


@router.get(
    "/project-defense/projects/{project_id}/context",
    response_model=ProjectDefenseContextResponse,
    summary="Get the defense context (evidence + status) for a selected project",
)
def get_project_defense_context_route(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> ProjectDefenseContextResponse:
    project = get_owned_vbr_project_or_404(db, project_id, user_id)
    context = build_project_defense_context(db, project, user_id)

    # Honest Skill Graph state on reload: the workspace's "Saved / Not saved"
    # indicator reflects whether this session's defense evidence artifact
    # already exists, instead of always resetting to "Not saved".
    skill_graph_synced = False
    if context["session_id"]:
        sync_svc = ProjectDefenseArtifactSyncService(db=db, pipeline_db=pipeline_db)
        skill_graph_synced = sync_svc.artifact_exists_for_session(user_id, context["session_id"])
    # Allowlisted metadata only — the raw stored ``metadata.attached_proofs`` may
    # contain legacy unsafe fields (raw provider JSON, storage paths, signed
    # URLs, private IDs, numeric scores) that must never reach the workspace UI.
    # ``VBRProjectResponse.metadata`` echoes the raw project metadata, so it is
    # replaced with the same safe projection before serializing the response.
    safe_project = {**project, "metadata": context["safe_metadata"]}
    return ProjectDefenseContextResponse(
        project=_to_project_response(safe_project),
        metadata=SafeProjectDefenseMetadataResponse(**context["safe_metadata"]),
        evidence=context["evidence"],
        defense_status=context["defense_status"],
        report_ready=context["report_ready"],
        session_id=context["session_id"],
        questions=[_to_question_response(row) for row in context["questions"]],
        skill_graph_synced=skill_graph_synced,
    )


@router.post(
    "/project-defense/projects/{project_id}/attach-proofs",
    response_model=AttachProofsResponse,
    summary="Attach existing owned proofs to a selected project",
)
def attach_project_defense_proofs_route(
    project_id: str,
    body: AttachedProofsRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> AttachProofsResponse:
    project = get_owned_vbr_project_or_404(db, project_id, user_id)
    try:
        result = attach_proofs_to_project(db, pipeline_db, user_id, project, body)
    except ValueError as exc:
        detail = _CREATE_ERROR_DETAILS.get(str(exc))
        if detail is None:
            raise
        code_status, code, message = detail
        raise HTTPException(status_code=code_status, detail={"code": code, "message": message}) from exc

    # Return the same safe projection as the context endpoint. The raw stored
    # ``metadata.attached_proofs`` may carry legacy unsafe fields (raw provider
    # JSON, storage paths, signed URLs, private ids, raw text, numeric scores);
    # both the echoed ``project.metadata`` and the ``metadata`` DTO are replaced
    # with the allowlisted/sanitized projection so none of it reaches the client.
    safe_metadata = result["safe_metadata"]
    safe_project = {**project, "metadata": safe_metadata}
    return AttachProofsResponse(
        project=_to_project_response(safe_project),
        metadata=SafeProjectDefenseMetadataResponse(**safe_metadata),
        evidence=result["evidence"],
    )


@router.post(
    "/project-defense",
    response_model=ProjectDefenseCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an individual Project Defense identity",
)
def create_project_defense_route(
    body: ProjectDefenseCreateRequest,
    # First-write flow: inserts a vbr_projects row (FKs public.users) and does
    # not require any pre-existing owned proof — provision fresh users.
    user_id: str = Depends(get_provisioned_user_id),
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
    # Ground questions in the merged evidence across any duplicate rows for this
    # logical project (keeps the canonical id, so the session still binds here)
    # — the plan must reflect GitHub / documents / website attached to ANY
    # duplicate, not only whatever the selected row happens to carry.
    merged_project = merge_owned_project(db, user_id, project)

    try:
        session_id, questions = generate_defense_questions(db, merged_project)
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
    "/projects/{project_id}/defense-sessions",
    response_model=GenerateDefenseQuestionsResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a fresh Project Defense recording session (new attempt)",
)
def create_defense_session_route(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> GenerateDefenseQuestionsResponse:
    """Always create a new defense session attempt for "Record another defense".

    A completed/processed session is non-retryable (the recorder only starts from
    ``created``), so this allocates a brand-new session + questions rather than
    reusing the finished one.
    """
    project = get_owned_vbr_project_or_404(db, project_id, user_id)
    # Ground the questions in the merged evidence across any duplicate rows for
    # this logical project, exactly like generate-defense-questions.
    merged_project = merge_owned_project(db, user_id, project)

    session_id, questions = create_new_defense_session(db, merged_project)
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
        # user_id grounds the analysis in the merged canonical evidence package
        # (claimed skills + attached proofs across the duplicate group).
        result = submit_defense_answers(db, session, project, body, user_id=user_id)
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
        defense_answer_evidence=result.get("defense_answer_evidence", []),
    )


@router.get(
    "/projects/{project_id}/report",
    response_model=VBRStudentProjectReportResponse,
    summary="Get a private student preview of the Final VBR Report for a project",
)
def get_student_vbr_report_route(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> VBRStudentProjectReportResponse:
    project = get_owned_vbr_project_or_404(db, project_id, user_id)
    report = build_student_vbr_report(db, pipeline_db, project, user_id)
    return VBRStudentProjectReportResponse(**report)


@router.post(
    "/projects/{project_id}/public-report",
    response_model=ProjectReportPublishStatusResponse,
    summary="Publish a recruiter-safe public link for this project's VBR report",
)
def publish_project_report_route(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> ProjectReportPublishStatusResponse:
    result = publish_project_report(db, project_id, user_id)
    # A newly published report changes what the public passport features —
    # keep the recruiter search projection in step.
    refresh_search_projection(db, pipeline_db, str(user_id))
    return ProjectReportPublishStatusResponse(**result)


@router.delete(
    "/projects/{project_id}/public-report",
    response_model=ProjectReportPublishStatusResponse,
    summary="Revoke the recruiter-safe public link for this project's VBR report",
)
def unpublish_project_report_route(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> ProjectReportPublishStatusResponse:
    result = unpublish_project_report(db, project_id, user_id)
    # A revoked report must disappear from recruiter search immediately.
    refresh_search_projection(db, pipeline_db, str(user_id))
    return ProjectReportPublishStatusResponse(**result)


@router.get(
    "/projects/{project_id}/public-report/status",
    response_model=ProjectReportPublishStatusResponse,
    summary="Get the publish status of this project's recruiter-safe public link",
)
def get_project_report_publish_status_route(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ProjectReportPublishStatusResponse:
    result = get_project_report_publish_status(db, project_id, user_id)
    return ProjectReportPublishStatusResponse(**result)
