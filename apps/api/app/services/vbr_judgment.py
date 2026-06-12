"""VBR claim/question judgment skeleton (T6B).

T6B scope: build a deterministic claim/question judgment skeleton from
confirmed project claims, session questions, and ``vbr_evidence_items``
(built in T6A). This module does NOT call any LLM, generate a final report,
or create public report rows.

Migration 049 has no dedicated claim-judgment table (``vbr_report_claims``
requires a ``vbr_reports`` row, which T6B intentionally does not create), so
the judgment skeleton is stored under
``vbr_verification_sessions.telemetry["judgment_skeleton"]``.

Idempotent: re-running replaces only the ``judgment_skeleton`` telemetry key
for this session, preserving other telemetry keys (media processing,
transcript, keyframes, etc.).
"""

from __future__ import annotations

import logging

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status

from app.services.vbr_question_generation import list_claims, list_session_questions
from app.services.vbr_session_recording import get_owned_vbr_session_or_404, update_session_telemetry

logger = logging.getLogger(__name__)

_EVIDENCE_TABLE = "vbr_evidence_items"
_QUESTION_EVIDENCE_SOURCE = "vbr_session_questions"

_CLAIM_RATIONALE = "Skeleton judgment based on available transcript/question evidence. No LLM assessment yet."
_QUESTION_RATIONALE = "Skeleton judgment based on available transcript evidence. No LLM assessment yet."

__all__ = ["judge_session_skeleton"]


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ── Evidence lookup ──────────────────────────────────────────────────────────


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


# ── Claim judgment ───────────────────────────────────────────────────────────


def _question_ids_for_claim(questions: list[dict[str, Any]], claim_id: str) -> set[str]:
    return {
        str(question["id"])
        for question in questions
        if claim_id in [str(ref) for ref in (question.get("claim_ids") or [])]
    }


def _evidence_categories(
    evidence_items: list[dict[str, Any]],
    *,
    question_ids: set[str] | None = None,
    claim_id: str | None = None,
) -> tuple[list[str], list[str]]:
    """Return (transcript_segment_ids, question_evidence_ids) for the given filters.

    If ``question_ids``/``claim_id`` are ``None``, matches all evidence of each
    category (used for the session-level fallback).
    """
    transcript_ids: list[str] = []
    question_evidence_ids: list[str] = []

    for item in evidence_items:
        pointer = item.get("pointer") or {}
        item_id = str(item["id"])
        evidence_type = item.get("evidence_type")

        if evidence_type == "transcript_segment":
            if question_ids is None or str(pointer.get("question_id")) in question_ids:
                transcript_ids.append(item_id)
        elif evidence_type == "session_telemetry" and item.get("source") == _QUESTION_EVIDENCE_SOURCE:
            if claim_id is None:
                question_evidence_ids.append(item_id)
            elif claim_id in [str(ref) for ref in (pointer.get("claim_ids") or [])]:
                question_evidence_ids.append(item_id)

    return transcript_ids, question_evidence_ids


def _build_claim_judgment(
    claim: dict[str, Any], evidence_items: list[dict[str, Any]], questions: list[dict[str, Any]]
) -> dict[str, Any]:
    claim_id = str(claim["id"])
    question_ids = _question_ids_for_claim(questions, claim_id)

    transcript_ids, question_evidence_ids = _evidence_categories(
        evidence_items, question_ids=question_ids, claim_id=claim_id
    )
    if not transcript_ids and not question_evidence_ids:
        # No claim-specific evidence link found; fall back to session-level evidence.
        transcript_ids, question_evidence_ids = _evidence_categories(evidence_items)

    has_transcript = bool(transcript_ids)
    has_question = bool(question_evidence_ids)

    if has_transcript and has_question:
        judgment_status = "demonstrated"
    elif has_transcript or has_question:
        judgment_status = "partially_demonstrated"
    else:
        judgment_status = "not_assessed"

    return {
        "claim_id": claim_id,
        "status": judgment_status,
        "rationale": _CLAIM_RATIONALE,
        "evidence_item_ids": transcript_ids + question_evidence_ids,
    }


# ── Question judgment ────────────────────────────────────────────────────────


def _build_question_judgment(question: dict[str, Any], evidence_items: list[dict[str, Any]]) -> dict[str, Any]:
    question_id = str(question["id"])

    related_ids: list[str] = []
    has_transcript = False

    for item in evidence_items:
        pointer = item.get("pointer") or {}
        item_id = str(item["id"])
        evidence_type = item.get("evidence_type")

        if evidence_type == "transcript_segment" and str(pointer.get("question_id")) == question_id:
            related_ids.append(item_id)
            has_transcript = True
        elif (
            evidence_type == "session_telemetry"
            and item.get("source") == _QUESTION_EVIDENCE_SOURCE
            and str(pointer.get("question_id")) == question_id
        ):
            related_ids.append(item_id)

    judgment_status = "answered_with_evidence" if has_transcript else "needs_review"

    return {
        "question_id": question_id,
        "status": judgment_status,
        "rationale": _QUESTION_RATIONALE,
        "evidence_item_ids": related_ids,
    }


# ── Orchestration ────────────────────────────────────────────────────────────


def judge_session_skeleton(db: Any, session_id: str, user_id: str) -> dict[str, Any]:
    """Build a deterministic claim/question judgment skeleton for a session.

    Validates ownership, that the session is ``processed``, and that evidence
    items, confirmed project claims, and session questions all exist. Stores
    the skeleton under ``session.telemetry["judgment_skeleton"]``. Idempotent:
    re-running replaces only that telemetry key.

    No LLM call happens here, no report rows are created, and the response
    never includes storage paths, signed URLs, local temp paths, full
    transcript text, or evidence metadata.
    """
    session, project = get_owned_vbr_session_or_404(db, session_id, user_id)

    if session.get("status") != "processed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_session_not_processed",
                "message": "Session must be in 'processed' status to run judgment.",
            },
        )

    project_id = str(project["id"])

    evidence_items = _list_session_evidence(db, project_id, session_id)
    if not evidence_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_judgment_evidence_missing",
                "message": "Evidence items are required before judgment can run.",
            },
        )

    has_transcript_evidence = any(
        item.get("evidence_type") == "transcript_segment"
        for item in evidence_items
    )
    has_question_evidence = any(
        item.get("evidence_type") == "session_telemetry"
        and item.get("source") == _QUESTION_EVIDENCE_SOURCE
        for item in evidence_items
    )

    if not has_transcript_evidence and not has_question_evidence:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_judgment_supporting_evidence_missing",
                "message": "Transcript or question evidence is required before judgment can run.",
            },
        )

    confirmed_claims = [row for row in list_claims(db, project_id) if row.get("status") == "confirmed"]
    if not confirmed_claims:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_judgment_claims_missing",
                "message": "Confirmed project claims are required before judgment can run.",
            },
        )

    questions = list_session_questions(db, session_id)
    if not questions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_judgment_questions_missing",
                "message": "Session questions are required before judgment can run.",
            },
        )

    claim_judgments = [_build_claim_judgment(claim, evidence_items, questions) for claim in confirmed_claims]
    question_judgments = [_build_question_judgment(question, evidence_items) for question in questions]

    judgment_skeleton = {
        "claim_judgments": claim_judgments,
        "question_judgments": question_judgments,
        "created_at": _now(),
        "method": "deterministic_skeleton_no_llm",
    }

    updated_session = update_session_telemetry(db, session, {"judgment_skeleton": judgment_skeleton}, merge=True)

    logger.info(
        "[VBR] Judgment skeleton built for session %s (claims=%d, questions=%d)",
        session_id,
        len(claim_judgments),
        len(question_judgments),
    )

    return {
        "session_id": session_id,
        "judged_claim_count": len(claim_judgments),
        "judged_question_count": len(question_judgments),
        "status": updated_session.get("status") or session.get("status") or "processed",
        "message": "Deterministic judgment skeleton created from available evidence. No LLM assessment yet.",
    }
