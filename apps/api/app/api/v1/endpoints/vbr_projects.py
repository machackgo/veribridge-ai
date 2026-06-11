"""Verified Build Report (VBR) project endpoints — student-owned project foundation.

MVP scope only: project CRUD, GitHub repo ingestion skeleton (placeholder
facts, no API/LLM calls), and a basic deployed-URL reachability check.

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

from app.api.deps import get_current_user_id, get_db
from app.schemas.vbr_project import (
    VBRDeployedUrlCheckResponse,
    VBRProjectCreateRequest,
    VBRProjectResponse,
    VBRRepoAnalysisResponse,
)
from app.services.vbr_github_ingestion import (
    check_deployed_url,
    ingest_repo,
    parse_github_repo_url,
)

logger = logging.getLogger(__name__)
router = APIRouter()

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
    user_id: str = Depends(get_current_user_id),
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
