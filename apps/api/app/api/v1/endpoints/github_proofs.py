"""Standalone GitHub proof submission endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import AuthenticatedUser, get_current_user_id, get_current_user_identity, get_db
from app.db.supabase import SupabaseError, SupabaseFKError
from app.schemas.github_proof_submission import GitHubProofSubmissionCreate, GitHubProofSubmissionResponse
from app.services.canonical_project_evidence import github_identity_conflict, project_repo_identity
from app.services.extension_proof_service import ExtensionProofSessionNotFoundError
from app.services.github_proof_service import (
    GitHubProofNotFoundError,
    GitHubProofService,
    GitHubProofValidationError,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _github_relationships(db: Any, user_id: str) -> dict[str, dict[str, Any]]:
    """github_proof_id → canonical relationship, from the SAME sources the
    Passport/report attachment index reads: normalized 058 rows first, then the
    projects' ``attached_proofs.github_proof`` metadata. Owner-scoped;
    best-effort (a pre-058 database simply yields metadata-only results).

    Each mapping carries the project's ``project_repo_identity`` so the caller
    can apply the SAME repository-identity read gate the canonical resolver
    uses: a legacy relationship row that attaches a proof to a project whose own
    declared repository contradicts the proof's repository must never surface
    as "Attached to <project>" (it would both mislead the student and lock the
    proof out of being attached to its real project)."""
    out: dict[str, dict[str, Any]] = {}
    projects: dict[str, str] = {}
    project_identities: dict[str, str] = {}
    try:
        if isinstance(db, dict):
            project_rows = [
                row for row in db.get("vbr_projects", {}).values()
                if str(row.get("user_id") or "") == str(user_id)
            ]
        else:
            resp = (
                db.table("vbr_projects")
                .select("id,title,repo_url,repo_full_name,metadata")
                .eq("user_id", user_id)
                .execute()
            )
            project_rows = list(getattr(resp, "data", []) or [])
        for project in project_rows:
            pid = str(project.get("id") or "")
            projects[pid] = str(project.get("title") or "Project")
            project_identities[pid] = project_repo_identity(project)
            attached = ((project.get("metadata") or {}).get("attached_proofs") or {})
            github_summary = attached.get("github_proof")
            proof_id = str((github_summary or {}).get("github_proof_id") or "")
            if proof_id and proof_id not in out:
                out[proof_id] = {
                    "project_id": pid,
                    "project_title": projects[pid],
                    "project_repo_identity": project_identities[pid],
                    "state": "directly_linked",
                }
    except Exception:
        pass
    try:
        if isinstance(db, dict):
            relation_rows = [
                row for row in db.get("proof_project_relationships", {}).values()
                if str(row.get("owner_user_id") or "") == str(user_id)
                and row.get("proof_type") == "github"
            ]
        else:
            resp = (
                db.table("proof_project_relationships")
                .select("proof_id,project_id,relationship_state")
                .eq("owner_user_id", user_id)
                .eq("proof_type", "github")
                .execute()
            )
            relation_rows = list(getattr(resp, "data", []) or [])
        for relation in relation_rows:
            proof_id = str(relation.get("proof_id") or "")
            pid = str(relation.get("project_id") or "")
            if proof_id and relation.get("relationship_state") == "directly_linked" and pid in projects:
                out[proof_id] = {
                    "project_id": pid,
                    "project_title": projects[pid],
                    "project_repo_identity": project_identities.get(pid, ""),
                    "state": "directly_linked",
                }
    except Exception:
        pass
    return out


@router.post(
    "",
    response_model=GitHubProofSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a standalone GitHub proof",
)
def submit_github_proof(
    body: GitHubProofSubmissionCreate,
    identity: AuthenticatedUser = Depends(get_current_user_identity),
    db: Any = Depends(get_db),
) -> GitHubProofSubmissionResponse:
    try:
        return GitHubProofService(db).submit_github_proof(
            user_id=identity.id,
            repo_url=body.repo_url,
            proof_session_id=body.proof_session_id,
            submitted_skill_claims=body.submitted_skill_claims,
            email=identity.email,
        )
    except ExtensionProofSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "extension_proof_session_not_found",
                "message": "Extension proof session not found for the current user.",
                "session_id": body.proof_session_id,
            },
        ) from exc
    except GitHubProofValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "github_proof_invalid", "message": str(exc)},
        ) from exc
    except SupabaseFKError as exc:
        # A required parent row is missing despite provisioning (e.g. the auth
        # user id is not in auth.users). Surface a clear, safe conflict — never
        # a raw traceback — instead of a generic 500.
        logger.warning("POST /student/github-proofs: FK violation for user %s", identity.id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "github_proof_account_not_ready",
                "message": "Your account is still being set up. Please try again in a moment.",
            },
        ) from exc
    except SupabaseError as exc:
        logger.error(
            "POST /student/github-proofs: database error for user %s (%s)",
            identity.id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "github_proof_unavailable",
                "message": "GitHub proof service is temporarily unavailable. Please try again.",
            },
        ) from exc
    except Exception as exc:
        logger.exception("POST /student/github-proofs: unexpected error for user %s", identity.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "GitHub proof submission failed unexpectedly."},
        ) from exc


@router.get(
    "",
    response_model=list[GitHubProofSubmissionResponse],
    summary="List standalone GitHub proofs for the current student",
)
def list_github_proofs(
    proof_session_id: str | None = Query(default=None),
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> list[GitHubProofSubmissionResponse]:
    proofs = GitHubProofService(db).list_github_proofs(user_id, proof_session_id)
    relationships = _github_relationships(db, user_id)
    for proof in proofs:
        relationship = relationships.get(str(proof.id))
        # Repository-identity read gate (same rule as the canonical resolver):
        # a legacy relationship attaching this proof to a project whose own
        # repository contradicts the proof's repository is excluded, so the
        # proof honestly shows as attachable to its real project.
        if relationship and github_identity_conflict(
            str(relationship.get("project_repo_identity") or ""), proof.repo_url
        ):
            relationship = None
        if relationship:
            proof.project_id = relationship["project_id"]
            proof.project_title = relationship["project_title"]
            proof.project_relationship_state = relationship["state"]
    return proofs


@router.get(
    "/{github_proof_id}",
    response_model=GitHubProofSubmissionResponse,
    summary="Get a standalone GitHub proof",
)
def get_github_proof(
    github_proof_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> GitHubProofSubmissionResponse:
    try:
        return GitHubProofService(db).get_github_proof(user_id, github_proof_id)
    except GitHubProofNotFoundError as exc:
        raise _proof_not_found(str(exc)) from exc


@router.post(
    "/{github_proof_id}/analyze",
    response_model=GitHubProofSubmissionResponse,
    summary="Analyze a standalone GitHub proof",
)
def analyze_github_proof(
    github_proof_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> GitHubProofSubmissionResponse:
    try:
        return GitHubProofService(db).analyze_github_proof(user_id, github_proof_id)
    except GitHubProofNotFoundError as exc:
        raise _proof_not_found(str(exc)) from exc
    except GitHubProofValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "github_proof_invalid", "message": str(exc)},
        ) from exc


@router.post(
    "/{github_proof_id}/archive",
    response_model=GitHubProofSubmissionResponse,
    summary="Archive a standalone GitHub proof",
)
def archive_github_proof(
    github_proof_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> GitHubProofSubmissionResponse:
    try:
        return GitHubProofService(db).archive_github_proof(user_id, github_proof_id)
    except GitHubProofNotFoundError as exc:
        raise _proof_not_found(str(exc)) from exc


def _proof_not_found(proof_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "github_proof_not_found",
            "message": "GitHub proof was not found for the current user.",
            "github_proof_id": proof_id,
        },
    )
