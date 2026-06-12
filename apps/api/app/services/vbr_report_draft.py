"""VBR private report draft generation (T6C).

T6C scope: build a private ``vbr_reports`` draft (and ``vbr_report_claims``
rows) from confirmed project claims, ``vbr_evidence_items`` (T6A), and the
deterministic judgment skeleton stored in session telemetry (T6B). This
module does NOT call any LLM, publish the report, mint a public token, or
expose storage paths/signed URLs/transcript text.

Idempotent: re-running updates the project's existing (non-published) report
draft and replaces its ``vbr_report_claims`` rows rather than duplicating
them. If the project's report is already published, a 409 is raised.
"""

from __future__ import annotations

import logging

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status

from app.api.v1.endpoints.vbr_projects import _advance_project_status
from app.services.vbr_question_generation import list_claims
from app.services.vbr_session_recording import get_owned_vbr_session_or_404

logger = logging.getLogger(__name__)

_EVIDENCE_TABLE = "vbr_evidence_items"
_REPORTS_TABLE = "vbr_reports"
_REPORT_CLAIMS_TABLE = "vbr_report_claims"

_DRAFT_VERSION = "vbr_draft_v1"
_DRAFT_METHOD = "deterministic_skeleton_no_llm"

_METHODOLOGY = [
    "Draft generated from repository, transcript, keyframe, question, and media-processing evidence.",
    "No LLM judgment has been applied yet.",
    "Report requires review before publishing.",
]
_LIMITATIONS = [
    "This is a private draft.",
    "Evidence has not yet been human-reviewed.",
]

__all__ = ["generate_report_draft"]


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ── Lookups ──────────────────────────────────────────────────────────────────


def _list_session_evidence(db: Any, project_id: str, session_id: str) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        return [
            row
            for row in db.setdefault(_EVIDENCE_TABLE, {}).values()
            if row.get("project_id") == project_id
            and (row.get("pointer") or {}).get("session_id") == session_id
        ]

    result = (
        db.table(_EVIDENCE_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .filter("pointer->>session_id", "eq", session_id)
        .execute()
    )
    return getattr(result, "data", []) or []


def _get_published_report(db: Any, project_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return next(
            (
                row
                for row in db.setdefault(_REPORTS_TABLE, {}).values()
                if row.get("project_id") == project_id and row.get("status") == "published"
            ),
            None,
        )

    result = (
        db.table(_REPORTS_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .eq("status", "published")
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _get_latest_report(db: Any, project_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        rows = [row for row in db.setdefault(_REPORTS_TABLE, {}).values() if row.get("project_id") == project_id]
        rows.sort(key=lambda row: row.get("version", 0), reverse=True)
        return rows[0] if rows else None

    result = (
        db.table(_REPORTS_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .order("version", desc=True)
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


# ── Persistence ──────────────────────────────────────────────────────────────


def _upsert_report(db: Any, project_id: str, existing_report: dict[str, Any] | None, body: dict[str, Any]) -> dict[str, Any]:
    now = _now()

    if existing_report is not None:
        updates = {
            "body": body,
            "status": "draft",
            "public_token": None,
            "published_at": None,
            "updated_at": now,
        }
        if isinstance(db, dict):
            existing_report.update(updates)
            return existing_report

        result = db.table(_REPORTS_TABLE).update(updates).eq("id", existing_report["id"]).execute()
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else existing_report

    row = {
        "id": str(uuid4()),
        "project_id": project_id,
        "version": 1,
        "body": body,
        "public_token": None,
        "status": "draft",
        "human_reviewed": False,
        "rerecord_count": 0,
        "view_count": 0,
        "published_at": None,
        "created_at": now,
        "updated_at": now,
    }

    if isinstance(db, dict):
        db.setdefault(_REPORTS_TABLE, {})[row["id"]] = row
        return row

    result = db.table(_REPORTS_TABLE).insert(row).execute()
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else row


def _replace_report_claims(db: Any, report_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        store = db.setdefault(_REPORT_CLAIMS_TABLE, {})
        for key in [key for key, row in store.items() if row.get("report_id") == report_id]:
            del store[key]
        for row in rows:
            store[row["id"]] = row
        return rows

    db.table(_REPORT_CLAIMS_TABLE).delete().eq("report_id", report_id).execute()
    if not rows:
        return []

    result = db.table(_REPORT_CLAIMS_TABLE).insert(rows).execute()
    return getattr(result, "data", []) or []


# ── Draft body ───────────────────────────────────────────────────────────────


def _build_draft_body(
    project: dict[str, Any],
    session_id: str,
    claim_judgments: list[dict[str, Any]],
    question_judgments: list[dict[str, Any]],
    claims_by_id: dict[str, dict[str, Any]],
    evidence_count: int,
    allowed_evidence_ids: set[str],
) -> dict[str, Any]:
    draft_claims = [
        {
            "claim_id": judgment.get("claim_id"),
            "claim_text": (claims_by_id.get(str(judgment.get("claim_id"))) or {}).get("claim_text"),
            "judgment": judgment.get("status"),
            "rationale": judgment.get("rationale"),
            "evidence_item_ids": [
                str(eid)
                for eid in (judgment.get("evidence_item_ids") or [])
                if str(eid) in allowed_evidence_ids
            ],
        }
        for judgment in claim_judgments
    ]

    draft_questions = [
        {"question_id": judgment.get("question_id"), "status": judgment.get("status")}
        for judgment in question_judgments
    ]

    return {
        "version": _DRAFT_VERSION,
        "method": _DRAFT_METHOD,
        "generated_at": _now(),
        "summary": {
            "project_title": project.get("title"),
            "repo_full_name": project.get("repo_full_name"),
            "session_id": session_id,
            "claim_count": len(draft_claims),
            "evidence_count": evidence_count,
        },
        "claims": draft_claims,
        "questions": draft_questions,
        "methodology": list(_METHODOLOGY),
        "limitations": list(_LIMITATIONS),
    }


# ── Orchestration ────────────────────────────────────────────────────────────


def generate_report_draft(db: Any, session_id: str, user_id: str) -> dict[str, Any]:
    """Generate or update a private VBR report draft for a processed session.

    Validates ownership, that the session is ``processed``, that a judgment
    skeleton, evidence items, and confirmed project claims all exist, then
    creates/updates a private ``vbr_reports`` draft row (``status="draft"``,
    no ``public_token``) and replaces its ``vbr_report_claims`` rows with the
    deterministic judgment skeleton results. Idempotent. Raises 409 if the
    project's report has already been published.
    """
    session, project = get_owned_vbr_session_or_404(db, session_id, user_id)

    if session.get("status") != "processed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_session_not_processed",
                "message": "Session must be in 'processed' status to draft a report.",
            },
        )

    telemetry = session.get("telemetry") or {}
    judgment_skeleton = telemetry.get("judgment_skeleton")
    if not judgment_skeleton:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_report_judgment_missing",
                "message": "A judgment skeleton is required before drafting a report.",
            },
        )

    project_id = str(project["id"])

    evidence_items = _list_session_evidence(db, project_id, session_id)
    allowed_evidence_ids = {str(item["id"]) for item in evidence_items}
    if not evidence_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_report_evidence_missing",
                "message": "Evidence items are required before drafting a report.",
            },
        )

    confirmed_claims = [row for row in list_claims(db, project_id) if row.get("status") == "confirmed"]
    if not confirmed_claims:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_report_claims_missing",
                "message": "Confirmed project claims are required before drafting a report.",
            },
        )

    published_report = _get_published_report(db, project_id)
    if published_report is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_report_already_published",
                "message": "A published report already exists for this project.",
            },
        )

    existing_report = _get_latest_report(db, project_id)
    claims_by_id = {str(row["id"]): row for row in confirmed_claims}
    claim_judgments = judgment_skeleton.get("claim_judgments") or []
    question_judgments = judgment_skeleton.get("question_judgments") or []

    body = _build_draft_body(
        project,
        session_id,
        claim_judgments,
        question_judgments,
        claims_by_id,
        len(evidence_items),
        allowed_evidence_ids,
    )

    report = _upsert_report(db, project_id, existing_report, body)
    report_id = str(report["id"])

    report_claim_rows = [
        {
            "id": str(uuid4()),
            "report_id": report_id,
            "claim_id": judgment.get("claim_id"),
            "tier": judgment.get("status"),
            "inconsistency_noted": False,
            "evidence_item_ids": [
                str(eid)
                for eid in (judgment.get("evidence_item_ids") or [])
                if str(eid) in allowed_evidence_ids
            ],
            "created_at": _now(),
        }
        for judgment in claim_judgments
    ]
    _replace_report_claims(db, report_id, report_claim_rows)

    _advance_project_status(db, project, "report_drafted")

    logger.info(
        "[VBR] Report draft generated for session %s (report=%s, claims=%d, evidence=%d)",
        session_id,
        report_id,
        len(claim_judgments),
        len(evidence_items),
    )

    return {
        "session_id": session_id,
        "report_id": report_id,
        "status": report.get("status") or "draft",
        "claim_count": len(claim_judgments),
        "evidence_count": len(evidence_items),
        "message": "Private report draft generated from confirmed claims and deterministic judgment. Report requires review before publishing.",
    }
