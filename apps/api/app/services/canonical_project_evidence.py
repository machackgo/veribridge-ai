"""Canonical project-evidence resolution — the ONE shared read-path contract.

Given an authenticated ``user_id`` and the ``vbr_projects`` row ids that make up
ONE logical project (the selected row plus its duplicate rows), these helpers
resolve exactly the evidence explicitly and validly attached to that project:

  * GitHub proofs      — ``proof_project_relationships`` (``directly_linked``)
                         and retained ``proof_artifacts`` project stamps
  * Document proofs    — same two tables
  * Website sessions   — ``extension_proof_sessions.project_id`` (or its
                         ``metadata.project_id``), plus the same two tables

Both Project Defense (context / eligible cards / question generation) and the
Project Report / Work Passport resolve through these helpers, so every surface
presents the SAME evidence package for a project.

The resolver contract:
  1. Evidence is admitted only through explicit, owner-confirmed project edges —
     never through skill sharing, URL similarity, account-latest fallbacks, or
     another user's rows.
  2. Every read is scoped by BOTH ``user_id`` and the exact project ids.
  3. Ordering is deterministic — edges sort by ``(created_at, id)`` — so
     "first" can never silently vary between requests.
  4. A GitHub proof whose repository identity contradicts the project's own
     declared repository identity is EXCLUDED at read time (a legacy wrong
     attachment must not leak an unrelated repository into a project) and is
     rejected at write time by the canonical finalization boundary.
  5. When several valid GitHub proofs are attached, selection is explicit:
     analysis-complete proofs first, then the most recently attached edge,
     with the proof id as the final tie-break.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from app.services.github_evidence_service import parse_github_repo_url

# GitHub proof statuses whose analysis is complete enough to prefer when
# several valid proofs are attached to the same project.
_ANALYZED_GITHUB_STATUSES = ("analyzed", "needs_more_evidence")

# Website session statuses whose recording lifecycle actually finished. Only
# these sessions are usable as project evidence. A session that was created or
# started but never uploaded/completed (an abandoned recording), or that was
# soft-archived as ``expired``, must never be admitted as project evidence —
# the gate lives HERE, in the shared resolver, so every consumer (defense
# context, Project Report, Work Passport) excludes such sessions centrally
# instead of each re-implementing the filter.
USABLE_WEBSITE_SESSION_STATUSES = frozenset({"completed"})


def _website_session_status_usable(session: dict[str, Any]) -> bool:
    return (
        str(session.get("status") or "").strip().lower()
        in USABLE_WEBSITE_SESSION_STATUSES
    )


def owned_rows(
    db: Any, table: str, user_id: str, *, user_key: str = "user_id"
) -> list[dict[str, Any]]:
    """Best-effort owner-scoped bulk read for canonical relationship hydration."""
    try:
        if isinstance(db, dict):
            return [
                row
                for row in db.get(table, {}).values()
                if isinstance(row, dict) and str(row.get(user_key) or "") == str(user_id)
            ]
        response = db.table(table).select("*").eq(user_key, user_id).execute()
        return [row for row in (getattr(response, "data", []) or []) if isinstance(row, dict)]
    except Exception:  # pragma: no cover - migration/table availability is additive
        return []


def project_repo_identity(project: dict[str, Any]) -> str:
    """Canonical ``owner/repo`` (lowercased) for a project row, or ``""``.

    Prefers the stored ``repo_full_name``; falls back to parsing ``repo_url``.
    """
    full_name = str(project.get("repo_full_name") or "").strip().lower()
    if full_name:
        return full_name.strip("/")
    ref = parse_github_repo_url(str(project.get("repo_url") or "").strip())
    if ref is not None:
        return f"{ref.owner}/{ref.repo}".lower()
    return ""


def github_identity_conflict(project_identity: str, repo_url: Any) -> bool:
    """True when a GitHub proof's repository provably contradicts the project.

    Conservative on purpose: a conflict exists only when BOTH the project's
    declared repository identity and the proof's ``repo_url`` parse to a
    canonical ``owner/repo`` and those identities differ. Anything unparseable
    is NOT treated as a conflict (the safe display layers already handle it).
    This is an integrity gate against contradictions — it never selects
    evidence by URL similarity.
    """
    if not project_identity:
        return False
    ref = parse_github_repo_url(str(repo_url or "").strip())
    if ref is None:
        return False
    return f"{ref.owner}/{ref.repo}".lower() != project_identity


def _edge_sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("created_at") or ""), str(row.get("id") or ""))


def canonical_proof_ids_for_projects(
    db: Any,
    *,
    user_id: str,
    project_ids: Iterable[str],
    proof_type: str,
    newest_first: bool = False,
) -> list[str]:
    """Proof ids of ``proof_type`` with an explicit direct edge to this project.

    Reads only explicit finalization writes: ``proof_project_relationships``
    rows in state ``directly_linked`` and retained ``proof_artifacts`` project
    stamps — both written exclusively by the shared canonical finalization
    boundary from an owner-confirmed attachment. Nothing is inferred from
    titles, repos, filenames, or skill text. Edges are ordered by
    ``(created_at, id)`` so the result is deterministic.
    """
    wanted = {str(pid) for pid in project_ids if str(pid)}
    if not wanted:
        return []
    edges: list[tuple[tuple[str, str], str]] = []
    for relation in sorted(
        owned_rows(db, "proof_project_relationships", user_id, user_key="owner_user_id"),
        key=_edge_sort_key,
    ):
        if (
            relation.get("proof_type") == proof_type
            and relation.get("relationship_state") == "directly_linked"
            and str(relation.get("project_id") or "") in wanted
            and relation.get("proof_id")
        ):
            edges.append((_edge_sort_key(relation), str(relation["proof_id"])))
    for artifact in sorted(
        owned_rows(db, "proof_artifacts", user_id, user_key="owner_user_id"),
        key=_edge_sort_key,
    ):
        if (
            artifact.get("proof_type") == proof_type
            and str(artifact.get("project_id") or "") in wanted
            and artifact.get("proof_id")
        ):
            edges.append((_edge_sort_key(artifact), str(artifact["proof_id"])))
    edges.sort(key=lambda item: item[0], reverse=newest_first)
    ids: list[str] = []
    seen: set[str] = set()
    for _, proof_id in edges:
        if proof_id not in seen:
            seen.add(proof_id)
            ids.append(proof_id)
    return ids


def canonical_website_session_ids(
    db: Any, *, user_id: str, project_ids: Iterable[str]
) -> list[str]:
    """Website session ids with an explicit direct edge to this project.

    Sources (all owner + project scoped): ``extension_proof_sessions`` rows
    whose ``project_id`` (or ``metadata.project_id``) matches, plus the shared
    relationship/artifact edges. Deterministic order: session-create edges by
    ``(created_at, id)`` first, then relationship/artifact edges.

    Usability gate: only sessions whose status is in
    ``USABLE_WEBSITE_SESSION_STATUSES`` are admitted. Website Proof creation
    writes its project edge (session metadata + relationship row) BEFORE any
    recording exists, so an abandoned recording would otherwise stay
    project-linked forever. A relationship/artifact edge whose session row is
    visibly non-usable is excluded for the same reason; an edge whose session
    row no longer exists is kept (legacy retained-artifact edges predate the
    session lifecycle and are already summary-gated downstream).
    """
    wanted = {str(pid) for pid in project_ids if str(pid)}
    if not wanted:
        return []
    sessions = sorted(
        owned_rows(db, "extension_proof_sessions", user_id), key=_edge_sort_key
    )
    usable_by_id = {
        str(session.get("id") or ""): _website_session_status_usable(session)
        for session in sessions
        if session.get("id")
    }
    ids: list[str] = []
    seen: set[str] = set()
    for session in sessions:
        metadata = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
        pid = str(session.get("project_id") or metadata.get("project_id") or "")
        sid = str(session.get("id") or "")
        if (
            pid in wanted
            and sid
            and sid not in seen
            and _website_session_status_usable(session)
        ):
            seen.add(sid)
            ids.append(sid)
    for sid in canonical_proof_ids_for_projects(
        db, user_id=user_id, project_ids=wanted, proof_type="website"
    ):
        if sid in seen:
            continue
        if usable_by_id.get(sid, True):  # unknown session rows keep legacy behavior
            seen.add(sid)
            ids.append(sid)
    return ids


def resolve_canonical_github_summary(
    db: Any,
    *,
    user_id: str,
    project_ids: Iterable[str],
    project_identity: str,
    build_summary: Callable[[Any, str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    """Deterministically choose THE canonical GitHub proof for a project.

    Candidates are the explicitly attached proofs (newest edge first). A
    candidate contradicting the project's repository identity is skipped (rule
    4). Among the valid remainder, the first analysis-complete proof wins;
    otherwise the newest valid attachment (rule 5). ``build_summary`` is the
    same safe summary builder the attach flow uses; a candidate whose summary
    cannot be built is skipped rather than failing the whole resolution.
    """
    fallback: dict[str, Any] | None = None
    for proof_id in canonical_proof_ids_for_projects(
        db, user_id=user_id, project_ids=project_ids, proof_type="github", newest_first=True
    ):
        try:
            summary = build_summary(db, user_id, proof_id)
        except Exception:
            continue
        if github_identity_conflict(project_identity, summary.get("repo_url")):
            continue
        summary["relationship_source"] = "canonical_direct"
        if str(summary.get("status") or "") in _ANALYZED_GITHUB_STATUSES:
            return summary
        if fallback is None:
            fallback = summary
    return fallback
