"""Verified Build Report (VBR) project endpoints — student-owned project foundation.

MVP scope only: project CRUD, GitHub repo ingestion skeleton (placeholder
facts, no API/LLM calls), a basic deployed-URL reachability check, and
placeholder claim/question generation (no LLM calls yet).

``get_db`` returns the service-role Supabase client which bypasses RLS, so
every route here manually checks ``user_id`` ownership via
``get_owned_vbr_project_or_404``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db, get_provisioned_user_id
from app.schemas.vbr_project import (
    VBRDeployedUrlCheckResponse,
    VBRProjectCreateRequest,
    VBRProjectResponse,
    VBRRepoAnalysisResponse,
)
from app.schemas.vbr_questions import (
    VBRClaimPatchRequest,
    VBRClaimResponse,
    VBRGenerateClaimsResponse,
    VBRGenerateQuestionsResponse,
    VBRQuestionsListResponse,
    VBRSessionQuestionResponse,
)
from app.services.vbr_github_ingestion import (
    check_deployed_url,
    ingest_repo,
    parse_github_repo_url,
)
from app.services.vbr_question_generation import (
    generate_claims,
    generate_questions,
    get_claim,
    get_latest_session,
    list_claims,
    list_session_questions,
    update_claim,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_STATUS_ORDER = {
    "draft": 0,
    "repo_ingested": 1,
    "url_checked": 2,
    "claims_ready": 3,
    "claims_confirmed": 4,
    "questions_ready": 5,
    "session_recording": 6,
    "session_uploaded": 7,
    "media_processed": 8,
    "judged": 9,
    "report_drafted": 10,
    "in_review": 11,
    "published": 12,
    "unpublished": 12,
    "failed": 12,
}


def _advance_project_status(db: Any, project: dict[str, Any], new_status: str) -> None:
    """Advance project status without allowing workflow regression."""
    current = project.get("status") or "draft"
    if _STATUS_ORDER.get(current, 0) < _STATUS_ORDER[new_status]:
        _set_project_status(db, str(project["id"]), new_status)
        project["status"] = new_status


_PROJECTS_TABLE = "vbr_projects"


# ── Helpers ──────────────────────────────────────────────────────────────────


def get_owned_vbr_project_or_404(db: Any, project_id: str, user_id: str) -> dict[str, Any]:
    """Return the vbr_projects row if owned by ``user_id``, else raise 404.

    Returns 404 (not 403) for rows owned by other users so existence of
    other students' projects is never revealed.
    """
    if isinstance(db, dict):
        row = db.setdefault(_PROJECTS_TABLE, {}).get(project_id)
        if not row or str(row.get("user_id")) != str(user_id):
            raise _project_not_found(project_id)
        return row

    result = (
        db.table(_PROJECTS_TABLE)
        .select("*")
        .eq("id", project_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    data = getattr(result, "data", None) if result is not None else None
    if not data:
        raise _project_not_found(project_id)
    return data


def _project_not_found(project_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "vbr_project_not_found",
            "message": "Verified Build Report project not found.",
            "project_id": project_id,
        },
    )


def _claim_not_found(project_id: str, claim_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "vbr_claim_not_found",
            "message": "Project claim not found.",
            "project_id": project_id,
            "claim_id": claim_id,
        },
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _to_project_response(row: dict[str, Any]) -> VBRProjectResponse:
    return VBRProjectResponse(
        id=str(row["id"]),
        title=row.get("title") or "",
        repo_url=row.get("repo_url") or "",
        repo_full_name=row.get("repo_full_name"),
        deployed_url=row.get("deployed_url"),
        head_sha=row.get("head_sha"),
        status=row.get("status") or "draft",
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
        metadata=row.get("metadata") or {},
    )


def _to_repo_analysis_response(row: dict[str, Any]) -> VBRRepoAnalysisResponse:
    return VBRRepoAnalysisResponse(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        head_sha=row.get("head_sha"),
        facts=row.get("facts") or {},
        fork=row.get("fork"),
        authorship_match_pct=row.get("authorship_match_pct"),
        computed_at=str(row.get("computed_at") or ""),
    )


def _to_url_check_response(row: dict[str, Any]) -> VBRDeployedUrlCheckResponse:
    return VBRDeployedUrlCheckResponse(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        url=row.get("url") or "",
        status_code=row.get("status_code"),
        title=row.get("title"),
        result=row.get("result") or "unknown",
        detail=row.get("detail"),
        checked_at=str(row.get("checked_at") or ""),
    )


def _to_claim_response(row: dict[str, Any]) -> VBRClaimResponse:
    return VBRClaimResponse(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        claim_text=row.get("claim_text") or "",
        source=row.get("source") or "llm_proposed",
        status=row.get("status") or "proposed",
        anchors=row.get("anchors") or [],
        skill_refs=row.get("skill_refs") or [],
        sort_order=row.get("sort_order") or 0,
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


def _to_question_response(row: dict[str, Any]) -> VBRSessionQuestionResponse:
    return VBRSessionQuestionResponse(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        sort_order=row.get("sort_order") or 0,
        question_text=row.get("question_text") or "",
        target_ref=row.get("target_ref") or {},
        claim_ids=row.get("claim_ids") or [],
        asked_at_s=row.get("asked_at_s"),
        answered=bool(row.get("answered")),
        created_at=str(row.get("created_at") or ""),
    )


def _set_project_status(db: Any, project_id: str, new_status: str) -> None:
    """Internal-only status transition helper. Never exposed directly to clients."""
    now = _now()
    if isinstance(db, dict):
        row = db.setdefault(_PROJECTS_TABLE, {}).get(project_id)
        if row is not None:
            row["status"] = new_status
            row["updated_at"] = now
        return

    db.table(_PROJECTS_TABLE).update({"status": new_status, "updated_at": now}).eq("id", project_id).execute()


# ── Routes ───────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=VBRProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a Verified Build Report project",
)
def create_project(
    body: VBRProjectCreateRequest,
    # First-write flow: vbr_projects FKs public.users — provision fresh users.
    user_id: str = Depends(get_provisioned_user_id),
    db: Any = Depends(get_db),
) -> VBRProjectResponse:
    repo_ref = parse_github_repo_url(body.repo_url)
    if repo_ref is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_invalid_github_repo_url",
                "message": "repo_url must be a supported GitHub repository URL.",
            },
        )

    repo_full_name = f"{repo_ref.owner}/{repo_ref.repo}"

    now = _now()
    row = {
        "id": str(uuid4()),
        "user_id": user_id,
        "title": body.title.strip(),
        "repo_url": body.repo_url.strip(),
        "repo_full_name": repo_full_name,
        "deployed_url": (body.deployed_url or "").strip() or None,
        "head_sha": None,
        "status": "draft",
        "metadata": {},
        "created_at": now,
        "updated_at": now,
    }

    if isinstance(db, dict):
        db.setdefault(_PROJECTS_TABLE, {})[row["id"]] = row
        return _to_project_response(row)

    result = db.table(_PROJECTS_TABLE).insert(row).execute()
    inserted = getattr(result, "data", []) or []
    if not inserted:
        raise RuntimeError("vbr_projects insert returned no data.")
    return _to_project_response(inserted[0])


@router.get(
    "",
    response_model=list[VBRProjectResponse],
    summary="List the current user's Verified Build Report projects",
)
def list_projects(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> list[VBRProjectResponse]:
    if isinstance(db, dict):
        rows = [row for row in db.setdefault(_PROJECTS_TABLE, {}).values() if str(row.get("user_id")) == str(user_id)]
        rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
        return [_to_project_response(row) for row in rows]

    result = (
        db.table(_PROJECTS_TABLE)
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return [_to_project_response(row) for row in rows]


@router.get(
    "/{project_id}",
    response_model=VBRProjectResponse,
    summary="Get a Verified Build Report project owned by the current user",
)
def get_project(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRProjectResponse:
    row = get_owned_vbr_project_or_404(db, project_id, user_id)
    return _to_project_response(row)


@router.post(
    "/{project_id}/ingest-repo",
    response_model=VBRRepoAnalysisResponse,
    summary="Ingest the project's GitHub repo (MVP skeleton, placeholder facts)",
)
def ingest_repo_route(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRRepoAnalysisResponse:
    project = get_owned_vbr_project_or_404(db, project_id, user_id)

    analysis_row = ingest_repo(
        db,
        project_id=project_id,
        repo_url=project.get("repo_url") or "",
        repo_full_name=project.get("repo_full_name"),
    )

    if project.get("status") == "draft":
        _set_project_status(db, project_id, "repo_ingested")

    return _to_repo_analysis_response(analysis_row)


@router.post(
    "/{project_id}/check-url",
    response_model=VBRDeployedUrlCheckResponse,
    summary="Check reachability of the project's deployed URL",
)
def check_url_route(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRDeployedUrlCheckResponse:
    project = get_owned_vbr_project_or_404(db, project_id, user_id)

    deployed_url = (project.get("deployed_url") or "").strip()
    if not deployed_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_no_deployed_url",
                "message": "This project has no deployed URL to check.",
            },
        )

    check_row = check_deployed_url(db, project_id=project_id, url=deployed_url)

    if project.get("status") == "repo_ingested":
        _set_project_status(db, project_id, "url_checked")

    return _to_url_check_response(check_row)


@router.post(
    "/{project_id}/generate-claims",
    response_model=VBRGenerateClaimsResponse,
    summary="Generate placeholder project claims from repo analysis (MVP skeleton)",
)
def generate_claims_route(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRGenerateClaimsResponse:
    project = get_owned_vbr_project_or_404(db, project_id, user_id)

    claims = generate_claims(db, project)
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_repo_analysis_required",
                "message": "Run repo ingestion before generating claims.",
            },
        )

    _advance_project_status(db, project, "claims_ready")

    return VBRGenerateClaimsResponse(
        project_id=project_id,
        status="claims_ready",
        claims=[_to_claim_response(row) for row in claims],
    )


@router.get(
    "/{project_id}/claims",
    response_model=list[VBRClaimResponse],
    summary="List project claims ordered by sort order",
)
def list_claims_route(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> list[VBRClaimResponse]:
    get_owned_vbr_project_or_404(db, project_id, user_id)

    rows = list_claims(db, project_id)
    return [_to_claim_response(row) for row in rows]


@router.patch(
    "/{project_id}/claims/{claim_id}",
    response_model=VBRClaimResponse,
    summary="Edit a claim's text or confirm/drop it",
)
def patch_claim_route(
    project_id: str,
    claim_id: str,
    body: VBRClaimPatchRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRClaimResponse:
    get_owned_vbr_project_or_404(db, project_id, user_id)

    existing = get_claim(db, project_id, claim_id)
    if existing is None:
        raise _claim_not_found(project_id, claim_id)

    updates: dict[str, Any] = {}
    if body.claim_text is not None:
        updates["claim_text"] = body.claim_text.strip()
        updates["source"] = "student_edited"
    if body.status is not None:
        updates["status"] = body.status

    if not updates:
        return _to_claim_response(existing)

    updated = update_claim(db, project_id, claim_id, updates)
    if updated is None:
        raise _claim_not_found(project_id, claim_id)

    return _to_claim_response(updated)


@router.post(
    "/{project_id}/generate-questions",
    response_model=VBRGenerateQuestionsResponse,
    summary="Generate placeholder repo-specific questions from confirmed claims (MVP skeleton)",
)
def generate_questions_route(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRGenerateQuestionsResponse:
    project = get_owned_vbr_project_or_404(db, project_id, user_id)

    try:
        result = generate_questions(db, project)
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

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_no_confirmed_claims",
                "message": "Confirm at least one claim before generating questions.",
            },
        )

    session_id, questions = result
    _advance_project_status(db, project, "questions_ready")

    return VBRGenerateQuestionsResponse(
        project_id=project_id,
        session_id=session_id,
        status="questions_ready",
        questions=[_to_question_response(row) for row in questions],
    )


@router.get(
    "/{project_id}/questions",
    response_model=VBRQuestionsListResponse,
    summary="Get the latest verification session's questions for this project",
)
def list_questions_route(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRQuestionsListResponse:
    get_owned_vbr_project_or_404(db, project_id, user_id)

    session = get_latest_session(db, project_id)
    if session is None:
        return VBRQuestionsListResponse(project_id=project_id, session_id=None, questions=[])

    rows = list_session_questions(db, session["id"])
    return VBRQuestionsListResponse(
        project_id=project_id,
        session_id=str(session["id"]),
        questions=[_to_question_response(row) for row in rows],
    )
