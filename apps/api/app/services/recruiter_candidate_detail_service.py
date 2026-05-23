"""Recruiter candidate detail service (Phase J2).

Aggregates full proof-backed candidate detail for a specific user_id.
Uses the service-role client (bypasses RLS) — same pattern as the J1 search service.
"""

from __future__ import annotations

from typing import Any

from app.schemas.recruiter_candidate_detail import (
    EvidenceAccessLinkItem,
    ProofOverview,
    ProofProjectSummary,
    RecruiterCandidateDetailResponse,
    VerifiedSkillSummary,
)

_SKILL_EVIDENCE_TABLE = "skill_evidence"
_STUDENT_PROFILES_TABLE = "student_profiles"
_EVIDENCE_ACCESS_LINKS_TABLE = "evidence_access_links"

_ACCEPTED_STATUSES = frozenset({"verified"})


class CandidateNotFoundError(LookupError):
    """No student profile was found for the given candidate_user_id."""


def _normalize_title(value: str) -> str:
    return value.strip().lower()


def _get_evidence_title(row: dict[str, Any]) -> str:
    meta = row.get("metadata")
    if isinstance(meta, dict):
        title = meta.get("evidence_title")
        if isinstance(title, str) and title.strip():
            return title.strip()
    skill = str(row.get("skill_name") or "").strip()
    return skill or "Project Evidence"


def _status_label(status: str) -> str:
    if status == "verified":
        return "Evidence Accepted"
    if status == "needs_review":
        return "Needs Review"
    if status == "skill_usage_not_found":
        return "Not Verified"
    return "Pending Analysis"


class RecruiterCandidateDetailService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def get_candidate_detail(self, candidate_user_id: str) -> RecruiterCandidateDetailResponse:
        profile = self._get_profile(candidate_user_id)
        if profile is None:
            raise CandidateNotFoundError(candidate_user_id)

        evidence_rows = self._get_evidence(candidate_user_id)
        evidence_ids = [str(r["id"]) for r in evidence_rows if r.get("id")]
        access_links_by_evidence_id = self._get_latest_access_links_by_evidence(
            candidate_user_id, evidence_ids
        )
        return _build_detail(
            candidate_user_id, profile, evidence_rows, access_links_by_evidence_id
        )

    # ── private ────────────────────────────────────────────────────────────────

    def _get_profile(self, user_id: str) -> dict[str, Any] | None:
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

    def _get_evidence(self, user_id: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            return [
                row
                for row in self._client.get(_SKILL_EVIDENCE_TABLE, {}).values()
                if str(row.get("user_id")) == user_id
            ]

        result = (
            self._client.table(_SKILL_EVIDENCE_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
        return getattr(result, "data", []) or []

    def _get_latest_access_links_by_evidence(
        self, user_id: str, evidence_ids: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        if not evidence_ids:
            return {}

        if isinstance(self._client, dict):
            all_links = [
                row
                for row in self._client.get(_EVIDENCE_ACCESS_LINKS_TABLE, {}).values()
                if str(row.get("user_id")) == user_id
                and str(row.get("evidence_id")) in evidence_ids
            ]
        else:
            result = (
                self._client.table(_EVIDENCE_ACCESS_LINKS_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .in_("evidence_id", evidence_ids)
                .order("created_at", desc=True)
                .execute()
            )
            all_links = getattr(result, "data", []) or []

        # Group by evidence_id, pick the latest generation for each
        by_evidence: dict[str, list[dict[str, Any]]] = {}
        for link in all_links:
            eid = str(link.get("evidence_id", ""))
            by_evidence.setdefault(eid, []).append(link)

        result_map: dict[str, list[dict[str, Any]]] = {}
        for eid, links in by_evidence.items():
            links_sorted = sorted(
                links, key=lambda r: r.get("created_at", ""), reverse=True
            )
            latest_gen = (links_sorted[0].get("access_snapshot") or {}).get("generation_id")
            if latest_gen:
                links_sorted = [
                    r
                    for r in links_sorted
                    if (r.get("access_snapshot") or {}).get("generation_id") == latest_gen
                ]
            result_map[eid] = links_sorted

        return result_map


def _build_detail(
    candidate_user_id: str,
    profile: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    access_links_by_evidence_id: dict[str, list[dict[str, Any]]],
) -> RecruiterCandidateDetailResponse:
    p = profile or {}
    display_name = str(p.get("full_name") or "Unknown Candidate")
    school_name: str | None = p.get("school_name") or None
    degree: str | None = p.get("degree") or None
    major: str | None = p.get("major") or None

    # Proof overview
    total_count = len(evidence_rows)
    accepted_count = sum(
        1 for r in evidence_rows if r.get("verification_status") in _ACCEPTED_STATUSES
    )
    github_count = sum(
        1 for r in evidence_rows if r.get("evidence_type") == "github repository"
    )
    website_count = sum(
        1 for r in evidence_rows if r.get("evidence_type") == "deployed website"
    )
    strongest_status: str | None = (
        "Evidence Accepted"
        if accepted_count > 0
        else ("Pending Analysis" if total_count > 0 else None)
    )
    proof_overview = ProofOverview(
        total_evidence_count=total_count,
        accepted_evidence_count=accepted_count,
        github_proof_count=github_count,
        website_proof_count=website_count,
        strongest_display_status=strongest_status,
    )

    # Per-skill summaries
    skills_map: dict[str, dict[str, Any]] = {}
    for row in evidence_rows:
        skill = str(row.get("skill_name") or "").strip()
        if not skill:
            continue
        if skill not in skills_map:
            skills_map[skill] = {"count": 0, "has_accepted": False}
        skills_map[skill]["count"] += 1
        if row.get("verification_status") in _ACCEPTED_STATUSES:
            skills_map[skill]["has_accepted"] = True

    verified_or_supported_skills = [
        VerifiedSkillSummary(
            skill_name=skill,
            evidence_count=data["count"],
            strongest_status_label=(
                "Evidence Accepted" if data["has_accepted"] else "Pending Analysis"
            ),
        )
        for skill, data in sorted(
            skills_map.items(), key=lambda kv: kv[1]["count"], reverse=True
        )
    ]

    # Group evidence by normalized project title
    grouped: dict[str, dict[str, Any]] = {}
    for row in evidence_rows:
        title = _get_evidence_title(row)
        key = _normalize_title(title)
        if key not in grouped:
            grouped[key] = {
                "project_title": title,
                "evidence_rows": [],
                "skill_labels": set(),
            }
        grouped[key]["evidence_rows"].append(row)
        skill = str(row.get("skill_name") or "").strip()
        if skill:
            grouped[key]["skill_labels"].add(skill)

    proof_projects: list[ProofProjectSummary] = []
    for group in grouped.values():
        rows: list[dict[str, Any]] = group["evidence_rows"]
        skill_labels: list[str] = sorted(group["skill_labels"])

        latest_status: str | None = None
        for row in sorted(
            rows, key=lambda r: r.get("created_at", ""), reverse=True
        ):
            s = str(row.get("verification_status") or "").strip()
            if s:
                latest_status = s
                break

        has_github = any(r.get("evidence_type") == "github repository" for r in rows)
        has_website = any(r.get("evidence_type") == "deployed website" for r in rows)

        # Prefer non-empty verification_summary as recruiter summary
        recruiter_summary: str | None = None
        for row in rows:
            summ = str(row.get("verification_summary") or "").strip()
            if summ:
                recruiter_summary = summ
                break

        # Collect and deduplicate available access links for this project
        seen_dedupe: set[tuple[str, str, str, str]] = set()
        link_items: list[EvidenceAccessLinkItem] = []
        for row in rows:
            eid = str(row.get("id", ""))
            for link in access_links_by_evidence_id.get(eid, []):
                if link.get("availability_status") != "available":
                    continue
                url = str(link.get("url") or "")
                access_type = str(link.get("access_type") or "")
                line_start = str(link.get("line_start") or "")
                line_end = str(link.get("line_end") or "")
                dedupe_key = (access_type, url, line_start, line_end)
                if dedupe_key in seen_dedupe:
                    continue
                seen_dedupe.add(dedupe_key)
                link_items.append(
                    EvidenceAccessLinkItem(
                        id=str(link.get("id") or f"link-{len(link_items)}"),
                        label=str(link.get("label") or ""),
                        url=url,
                        access_type=access_type,
                        source_type=str(link.get("source_type") or ""),
                        file_path=link.get("file_path"),
                        line_start=link.get("line_start"),
                        line_end=link.get("line_end"),
                        availability_status=str(link.get("availability_status") or ""),
                    )
                )

        # Extract proof verification fields from metadata
        _MAX_SCREENSHOT_LEN = 2 * 1024 * 1024  # 2 MB generous limit for base64 images
        screenshot_url: str | None = None
        screenshot_caption: str | None = None
        api_verified = False
        api_output_parts: list[str] = []
        for row in rows:
            meta = row.get("metadata") or {}
            if not isinstance(meta, dict):
                continue
            # Screenshot: prefer browser_screenshot_url then screenshot_url
            for key in ("browser_screenshot_url", "screenshot_url"):
                su = meta.get(key)
                if (
                    isinstance(su, str)
                    and su.startswith("data:image/")
                    and len(su) <= _MAX_SCREENSHOT_LEN
                    and screenshot_url is None
                ):
                    screenshot_url = su
                    caption = meta.get("browser_screenshot_caption") or meta.get("screenshot_caption")
                    screenshot_caption = str(caption).strip() if isinstance(caption, str) else None
                    break
            # API verification
            if meta.get("proof_kind") == "functional_verification" and meta.get("verified") is True:
                api_verified = True
            # API output summary
            for key in ("response_summary", "proof_summary", "browser_proof_summary"):
                rs = meta.get(key)
                if isinstance(rs, str) and rs.strip() and rs not in api_output_parts:
                    api_output_parts.append(rs.strip())
                    break

        api_output_summary = "; ".join(api_output_parts[:2]) if api_output_parts else None

        proof_projects.append(
            ProofProjectSummary(
                project_title=group["project_title"],
                status_label=_status_label(latest_status or ""),
                status_code=latest_status,
                has_github_proof=has_github,
                has_website_proof=has_website,
                recruiter_summary=recruiter_summary,
                associated_skill_labels=skill_labels,
                evidence_access_links=link_items,
                screenshot_url=screenshot_url,
                screenshot_caption=screenshot_caption,
                api_verified=api_verified,
                api_output_summary=api_output_summary,
            )
        )

    # Sort projects: most access links first, then by github+website proof
    proof_projects.sort(
        key=lambda proj: (
            len(proj.evidence_access_links),
            proj.has_github_proof,
            proj.has_website_proof,
        ),
        reverse=True,
    )

    return RecruiterCandidateDetailResponse(
        candidate_id=candidate_user_id,
        display_name=display_name,
        school_name=school_name if isinstance(school_name, str) else None,
        degree=degree if isinstance(degree, str) else None,
        major=major if isinstance(major, str) else None,
        proof_overview=proof_overview,
        verified_or_supported_skills=verified_or_supported_skills,
        proof_projects=proof_projects,
    )
