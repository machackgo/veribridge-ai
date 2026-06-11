"""Placeholder claim + question generation for VBR projects (T3 skeleton).

MVP scope only: deterministic, non-LLM placeholder logic that derives
project claims from ``vbr_repo_analyses.facts`` and derives repo-specific
verification questions from confirmed claims.

TODO (future milestones):
  - Replace placeholder claim/question text with real Claude/OpenAI
    extraction + generation, gated through the AI safety checks in
    SECURITY_SPEC.md (banned wording, citation coverage, schema validation).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

_REPO_ANALYSES_TABLE = "vbr_repo_analyses"
_CLAIMS_TABLE = "vbr_project_claims"
_SESSIONS_TABLE = "vbr_verification_sessions"
_ACTIVE_SESSION_STATUSES = {"created", "recording", "uploaded"}
_QUESTIONS_TABLE = "vbr_session_questions"

_QUESTION_TEMPLATE_FILE_NAV = "Open the key file or folder related to this claim and explain how it works: {claim_text}"
_QUESTION_TEMPLATE_TRADEOFF = "Show where this behavior exists in the repository and explain the tradeoff you made."
_QUESTION_TEMPLATE_DEPLOYED_DEMO = "Demonstrate this in the deployed app if applicable and connect it back to code."

_MIN_QUESTIONS = 6
_MAX_QUESTIONS = 10

__all__ = [
    "build_placeholder_claims",
    "build_placeholder_questions",
    "generate_claims",
    "generate_questions",
    "get_repo_analysis",
    "list_claims",
    "get_claim",
    "update_claim",
    "get_latest_session",
    "list_session_questions",
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ── Repo analysis lookup ─────────────────────────────────────────────────────


def get_repo_analysis(db: Any, project_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        rows = [row for row in db.setdefault(_REPO_ANALYSES_TABLE, {}).values() if row.get("project_id") == project_id]
        return rows[0] if rows else None

    result = (
        db.table(_REPO_ANALYSES_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


# ── Claim generation ─────────────────────────────────────────────────────────


def build_placeholder_claims(project: dict[str, Any], facts: dict[str, Any]) -> list[dict[str, Any]]:
    """Build 4-6 deterministic placeholder claim specs from repo facts.

    Each spec has ``claim_text`` and ``anchors`` (a list of anchor dicts
    pointing back to repo/source info for evidence linking later).
    """
    repo_full_name = facts.get("repo_full_name") or project.get("repo_full_name") or ""
    repo_name = facts.get("repo") or (repo_full_name.split("/")[-1] if repo_full_name else "this project")
    repo_url = project.get("repo_url") or ""
    languages = facts.get("languages")

    if isinstance(languages, dict) and languages:
        language_summary = ", ".join(sorted(languages.keys()))
    elif isinstance(languages, list) and languages:
        language_summary = ", ".join(str(lang) for lang in languages)
    else:
        language_summary = "this project's primary languages"

    base_anchor = {
        "repo_url": repo_url,
        "repo_full_name": repo_full_name or None,
        "languages": languages or None,
    }

    claims: list[dict[str, Any]] = [
        {
            "claim_text": f"Explained the architecture and purpose of the {repo_name} repository.",
            "anchors": [{**base_anchor, "type": "repo_overview"}],
        },
        {
            "claim_text": f"Demonstrated understanding of the primary language stack: {language_summary}.",
            "anchors": [{**base_anchor, "type": "language_stack"}],
        },
        {
            "claim_text": "Walked through the repository structure and key implementation files.",
            "anchors": [{**base_anchor, "type": "repo_structure"}],
        },
        {
            "claim_text": "Explained development history using commit and repository evidence.",
            "anchors": [{**base_anchor, "type": "commit_history", "commit_count": facts.get("commit_count")}],
        },
    ]

    deployed_url = (project.get("deployed_url") or "").strip()
    if deployed_url:
        claims.append(
            {
                "claim_text": "Demonstrated the deployed application and connected it to repository functionality.",
                "anchors": [{**base_anchor, "type": "deployed_url", "deployed_url": deployed_url}],
            }
        )

    return claims


def _delete_proposed_llm_claims(db: Any, project_id: str) -> None:
    """Delete previously auto-proposed (untouched) claims for a project.

    Confirmed/dropped/student-edited claims are left intact so a refresh
    is idempotent with respect to student progress.
    """
    if isinstance(db, dict):
        store = db.setdefault(_CLAIMS_TABLE, {})
        for key in [
            claim_id
            for claim_id, row in store.items()
            if row.get("project_id") == project_id
            and row.get("source") == "llm_proposed"
            and row.get("status") == "proposed"
        ]:
            del store[key]
        return

    (
        db.table(_CLAIMS_TABLE)
        .delete()
        .eq("project_id", project_id)
        .eq("source", "llm_proposed")
        .eq("status", "proposed")
        .execute()
    )


def _insert_claims(db: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        store = db.setdefault(_CLAIMS_TABLE, {})
        for row in rows:
            store[row["id"]] = row
        return rows

    result = db.table(_CLAIMS_TABLE).insert(rows).execute()
    return getattr(result, "data", []) or []


def list_claims(db: Any, project_id: str) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        rows = [row for row in db.setdefault(_CLAIMS_TABLE, {}).values() if row.get("project_id") == project_id]
        rows.sort(key=lambda row: row.get("sort_order", 0))
        return rows

    result = (
        db.table(_CLAIMS_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .order("sort_order")
        .execute()
    )
    return getattr(result, "data", []) or []


def get_claim(db: Any, project_id: str, claim_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        row = db.setdefault(_CLAIMS_TABLE, {}).get(claim_id)
        if not row or row.get("project_id") != project_id:
            return None
        return row

    result = (
        db.table(_CLAIMS_TABLE)
        .select("*")
        .eq("id", claim_id)
        .eq("project_id", project_id)
        .maybe_single()
        .execute()
    )
    return getattr(result, "data", None) if result is not None else None


def update_claim(db: Any, project_id: str, claim_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    payload = {**updates, "updated_at": _now()}

    if isinstance(db, dict):
        row = db.setdefault(_CLAIMS_TABLE, {}).get(claim_id)
        if not row or row.get("project_id") != project_id:
            return None
        row.update(payload)
        return row

    result = (
        db.table(_CLAIMS_TABLE)
        .update(payload)
        .eq("id", claim_id)
        .eq("project_id", project_id)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def generate_claims(db: Any, project: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Generate/refresh placeholder claims for a project.

    Returns ``None`` if the project has no repo analysis yet.
    """
    repo_analysis = get_repo_analysis(db, project["id"])
    if repo_analysis is None:
        return None

    facts = repo_analysis.get("facts") or {}
    claim_specs = build_placeholder_claims(project, facts)

    _delete_proposed_llm_claims(db, project["id"])

    now = _now()
    rows = [
        {
            "id": str(uuid4()),
            "project_id": project["id"],
            "claim_text": spec["claim_text"],
            "source": "llm_proposed",
            "status": "proposed",
            "anchors": spec["anchors"],
            "skill_refs": [],
            "sort_order": sort_order,
            "created_at": now,
            "updated_at": now,
        }
        for sort_order, spec in enumerate(claim_specs)
    ]

    return _insert_claims(db, rows)


# ── Verification sessions ────────────────────────────────────────────────────


def get_active_session(db: Any, project_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        rows = [
            row
            for row in db.setdefault(_SESSIONS_TABLE, {}).values()
            if row.get("project_id") == project_id and row.get("status") in _ACTIVE_SESSION_STATUSES
        ]
        rows.sort(key=lambda row: row.get("attempt_no", 0), reverse=True)
        return rows[0] if rows else None

    result = (
        db.table(_SESSIONS_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .in_("status", list(_ACTIVE_SESSION_STATUSES))
        .order("attempt_no", desc=True)
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def get_latest_session(db: Any, project_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        rows = [row for row in db.setdefault(_SESSIONS_TABLE, {}).values() if row.get("project_id") == project_id]
        rows.sort(key=lambda row: row.get("attempt_no", 0), reverse=True)
        return rows[0] if rows else None

    result = (
        db.table(_SESSIONS_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .order("attempt_no", desc=True)
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _next_attempt_no(db: Any, project_id: str) -> int:
    if isinstance(db, dict):
        rows = [row for row in db.setdefault(_SESSIONS_TABLE, {}).values() if row.get("project_id") == project_id]
        return max((row.get("attempt_no", 0) for row in rows), default=0) + 1

    result = (
        db.table(_SESSIONS_TABLE)
        .select("attempt_no")
        .eq("project_id", project_id)
        .order("attempt_no", desc=True)
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return (rows[0]["attempt_no"] if rows else 0) + 1


def _create_session(db: Any, project_id: str) -> dict[str, Any]:
    now = _now()
    row = {
        "id": str(uuid4()),
        "project_id": project_id,
        "attempt_no": _next_attempt_no(db, project_id),
        "status": "created",
        "started_at": None,
        "ended_at": None,
        "duration_s": None,
        "video_path": None,
        "webcam_present": False,
        "telemetry": {},
        "created_at": now,
        "updated_at": now,
    }

    if isinstance(db, dict):
        db.setdefault(_SESSIONS_TABLE, {})[row["id"]] = row
        return row

    result = db.table(_SESSIONS_TABLE).insert(row).execute()
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else row


# ── Question generation ──────────────────────────────────────────────────────


def build_placeholder_questions(confirmed_claims: list[dict[str, Any]], deployed_url: str | None) -> list[dict[str, Any]]:
    """Build 6-10 deterministic, navigation-forcing placeholder questions.

    For each confirmed claim, one question is generated per template. The
    resulting list is clamped to ``[_MIN_QUESTIONS, _MAX_QUESTIONS]`` by
    trimming or cycling through the generated questions.
    """
    questions: list[dict[str, Any]] = []

    for claim in confirmed_claims:
        claim_id = str(claim["id"])
        questions.append(
            {
                "question_text": _QUESTION_TEMPLATE_FILE_NAV.format(claim_text=claim["claim_text"]),
                "target_ref": {"type": "claim_navigation", "claim_id": claim_id},
                "claim_ids": [claim_id],
            }
        )

    for claim in confirmed_claims:
        claim_id = str(claim["id"])
        questions.append(
            {
                "question_text": _QUESTION_TEMPLATE_TRADEOFF,
                "target_ref": {"type": "repo_tradeoff", "claim_id": claim_id},
                "claim_ids": [claim_id],
            }
        )

    for claim in confirmed_claims:
        claim_id = str(claim["id"])
        questions.append(
            {
                "question_text": _QUESTION_TEMPLATE_DEPLOYED_DEMO,
                "target_ref": {"type": "deployed_demo", "claim_id": claim_id, "deployed_url": deployed_url},
                "claim_ids": [claim_id],
            }
        )

    if len(questions) > _MAX_QUESTIONS:
        questions = questions[:_MAX_QUESTIONS]
    elif len(questions) < _MIN_QUESTIONS and questions:
        base = list(questions)
        index = 0
        while len(questions) < _MIN_QUESTIONS:
            questions.append(base[index % len(base)])
            index += 1

    for sort_order, question in enumerate(questions):
        question["sort_order"] = sort_order

    return questions


def _delete_session_questions(db: Any, session_id: str) -> None:
    if isinstance(db, dict):
        store = db.setdefault(_QUESTIONS_TABLE, {})
        for key in [qid for qid, row in store.items() if row.get("session_id") == session_id]:
            del store[key]
        return

    db.table(_QUESTIONS_TABLE).delete().eq("session_id", session_id).execute()


def _insert_questions(db: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        store = db.setdefault(_QUESTIONS_TABLE, {})
        for row in rows:
            store[row["id"]] = row
        return rows

    result = db.table(_QUESTIONS_TABLE).insert(rows).execute()
    return getattr(result, "data", []) or []


def list_session_questions(db: Any, session_id: str) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        rows = [row for row in db.setdefault(_QUESTIONS_TABLE, {}).values() if row.get("session_id") == session_id]
        rows.sort(key=lambda row: row.get("sort_order", 0))
        return rows

    result = (
        db.table(_QUESTIONS_TABLE)
        .select("*")
        .eq("session_id", session_id)
        .order("sort_order")
        .execute()
    )
    return getattr(result, "data", []) or []


def generate_questions(db: Any, project: dict[str, Any]) -> tuple[str, list[dict[str, Any]]] | None:
    """Generate/refresh placeholder questions from confirmed claims.

    Returns ``None`` if the project has no confirmed claims. Otherwise
    returns ``(session_id, question_rows)``.
    """
    confirmed_claims = [row for row in list_claims(db, project["id"]) if row.get("status") == "confirmed"]
    if not confirmed_claims:
        return None

    session = get_active_session(db, project["id"])
    if session is not None and session.get("status") != "created":
        raise ValueError("active_session_already_started")
    if session is None:
        session = _create_session(db, project["id"])

    _delete_session_questions(db, session["id"])

    question_specs = build_placeholder_questions(confirmed_claims, project.get("deployed_url"))

    now = _now()
    rows = [
        {
            "id": str(uuid4()),
            "session_id": session["id"],
            "sort_order": spec["sort_order"],
            "question_text": spec["question_text"],
            "target_ref": spec["target_ref"],
            "claim_ids": spec["claim_ids"],
            "asked_at_s": None,
            "answered": False,
            "created_at": now,
        }
        for spec in question_specs
    ]

    inserted = _insert_questions(db, rows)
    return str(session["id"]), inserted
