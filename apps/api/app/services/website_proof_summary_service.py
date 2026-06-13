"""Website Proof summary service — safe, student-owned Website Proof listings.

Reads ``workflow_analysis_results`` (one row per completed Website Proof
session, linked via ``proof_session_id`` -> ``extension_proof_sessions.id``)
and returns only safe summary fields for use elsewhere (e.g. Project
Defense attachment).

Security invariants:
  - Never returns screenshots, storage paths, signed URLs, tokens, raw
    transcripts, or full artifact_data — summary fields only.
  - Ownership is always scoped to ``user_id``.
"""

from __future__ import annotations

from typing import Any

_WF_TABLE = "workflow_analysis_results"

_SUMMARY_COLUMNS = (
    "proof_session_id,target_website,evidence_strength_score,"
    "workflow_confidence,supported_skills,created_at,user_id"
)


def _clean_skill_list(values: Any, limit: int = 10) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out[:limit]


def _to_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "proof_session_id": str(row.get("proof_session_id")),
        "target_website": str(row.get("target_website") or "")[:200],
        "evidence_strength_score": int(row.get("evidence_strength_score") or 0),
        "workflow_confidence": str(row.get("workflow_confidence") or "insufficient"),
        "supported_skills": _clean_skill_list(row.get("supported_skills")),
        "created_at": str(row.get("created_at") or ""),
    }


def list_website_proof_summaries(db: Any, user_id: str) -> list[dict[str, Any]]:
    """Return safe summaries of ``user_id``'s completed Website Proof sessions."""
    if isinstance(db, dict):
        rows = [r for r in db.get(_WF_TABLE, {}).values() if str(r.get("user_id")) == user_id]
        rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
        return [_to_summary(r) for r in rows]

    resp = (
        db.table(_WF_TABLE)
        .select(_SUMMARY_COLUMNS)
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    rows = getattr(resp, "data", []) or []
    return [_to_summary(r) for r in rows]


def get_website_proof_summary(db: Any, user_id: str, proof_session_id: str) -> dict[str, Any] | None:
    """Return a safe summary for one Website Proof session owned by ``user_id``, or ``None``."""
    if isinstance(db, dict):
        for row in db.get(_WF_TABLE, {}).values():
            if str(row.get("user_id")) == user_id and str(row.get("proof_session_id")) == proof_session_id:
                return _to_summary(row)
        return None

    resp = (
        db.table(_WF_TABLE)
        .select(_SUMMARY_COLUMNS)
        .eq("user_id", user_id)
        .eq("proof_session_id", proof_session_id)
        .limit(1)
        .execute()
    )
    rows = getattr(resp, "data", []) or []
    return _to_summary(rows[0]) if rows else None
