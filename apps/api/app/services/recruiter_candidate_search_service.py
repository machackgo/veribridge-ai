"""Recruiter candidate search service (Phase J1).

Searches skill_evidence across all students using the service-role client
(which bypasses RLS).  Per-user evidence APIs remain user-scoped; this
service is intentionally cross-user for recruiter discovery.
"""

from __future__ import annotations

import re
from typing import Any

from app.schemas.recruiter_candidate_search import CandidateSearchResult

_SKILL_EVIDENCE_TABLE = "skill_evidence"
_STUDENT_PROFILES_TABLE = "student_profiles"

_ACCEPTED_STATUSES = frozenset({"verified"})


def _sanitize_query(query: str) -> str:
    """Strip SQL wildcard characters so they aren't injected into ilike patterns."""
    return re.sub(r"[%_]", "", query).strip()


class RecruiterCandidateSearchService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def search(self, raw_query: str) -> list[CandidateSearchResult]:
        query = _sanitize_query(raw_query)
        if not query:
            return []

        evidence_rows = self._search_evidence(query)
        if not evidence_rows:
            return []

        by_user: dict[str, list[dict[str, Any]]] = {}
        for row in evidence_rows:
            uid = str(row["user_id"])
            by_user.setdefault(uid, []).append(row)

        results: list[CandidateSearchResult] = []
        for uid, rows in by_user.items():
            profile = self._get_student_profile(uid)
            results.append(_build_result(uid, rows, profile))

        results.sort(
            key=lambda r: (r.accepted_evidence_count, r.evidence_count),
            reverse=True,
        )
        return results

    # ── private ────────────────────────────────────────────────────────────

    def _search_evidence(self, query: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            q = query.lower()
            return [
                row
                for row in self._client.get(_SKILL_EVIDENCE_TABLE, {}).values()
                if q in (row.get("skill_name") or "").lower()
                or q in (row.get("evidence_description") or "").lower()
            ]

        result = (
            self._client.table(_SKILL_EVIDENCE_TABLE)
            .select("*")
            .or_(
                f"skill_name.ilike.%{query}%,"
                f"evidence_description.ilike.%{query}%"
            )
            .execute()
        )
        return getattr(result, "data", []) or []

    def _get_student_profile(self, user_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            for p in self._client.get(_STUDENT_PROFILES_TABLE, {}).values():
                if str(p.get("user_id")) == user_id:
                    return p
            return None

        result = (
            self._client.table(_STUDENT_PROFILES_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if result is None:
            return None
        return result.data


def _build_result(
    user_id: str,
    evidence_rows: list[dict[str, Any]],
    profile: dict[str, Any] | None,
) -> CandidateSearchResult:
    p = profile or {}
    display_name: str = p.get("full_name") or "Unknown Candidate"
    school_name: str | None = p.get("school_name") or None
    degree: str | None = p.get("degree") or None
    major: str | None = p.get("major") or None

    seen_skills: dict[str, None] = {}
    for row in evidence_rows:
        sn = (row.get("skill_name") or "").strip()
        if sn:
            seen_skills[sn] = None
    matched_skill_names = list(seen_skills)

    accepted_count = sum(
        1 for r in evidence_rows
        if r.get("verification_status") in _ACCEPTED_STATUSES
    )

    has_github = any(
        r.get("evidence_type") == "github repository" for r in evidence_rows
    )
    has_website = any(
        r.get("evidence_type") == "deployed website" for r in evidence_rows
    )

    strongest_project_title: str | None = None
    for row in sorted(evidence_rows, key=lambda r: r.get("created_at", ""), reverse=True):
        meta = row.get("metadata")
        title = (meta or {}).get("evidence_title") if isinstance(meta, dict) else None
        if title:
            strongest_project_title = str(title)
            break

    proof_status_label = "Evidence Accepted" if accepted_count > 0 else "Pending Analysis"

    return CandidateSearchResult(
        user_id=user_id,
        display_name=display_name,
        school_name=school_name,
        degree=degree,
        major=major,
        matched_skill_names=matched_skill_names,
        evidence_count=len(evidence_rows),
        accepted_evidence_count=accepted_count,
        has_github_proof=has_github,
        has_website_proof=has_website,
        strongest_project_title=strongest_project_title,
        proof_status_label=proof_status_label,
    )
