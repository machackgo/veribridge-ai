"""Skill evidence timeline and multi-proof aggregation service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.schemas.skill_evidence_timeline import (
    SkillEvidenceItem,
    SkillEvidenceRecord,
    SkillEvidenceTimelineResponse,
)
from app.services.extension_proof_service import ExtensionProofSessionNotFoundError
from app.services.public_work_passport_service import EvidenceAccessDeniedError, PublicWorkPassportNotFoundError
from app.services.verification_readiness_service import compute_readiness_report

_SESSIONS = "extension_proof_sessions"
_SKILL_EVIDENCE = "skill_evidence"
_WORKFLOW = "workflow_analysis_results"
_GITHUB = "extension_proof_github_analysis"
_LIVE = "live_website_check_results"
_PRIVACY = "workflow_privacy_scan_results"
_DEFENSE = "project_defense_analysis_results"
_AI_DOMAIN = "ai_domain_review_results"
_VERSIONS = "proof_evidence_versions"
_PASSPORTS = "public_work_passports"
_GRANTS = "evidence_access_grants"

_SECTION_TO_TYPES = {
    "workflow_analysis": {"workflow"},
    "github_analysis": {"github"},
    "live_website_check": {"live_website"},
    "project_defense_summary": {"project_defense"},
    "project_defense_transcript": {"project_defense"},
    "ai_domain_review": {"ai_domain_review"},
    "readiness_report": {"readiness_report"},
    "privacy_scan_summary": {"privacy_scan"},
}


class SkillEvidenceTimelineService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def get_skill_evidence_timeline(self, user_id: str, proof_session_id: str) -> SkillEvidenceTimelineResponse:
        return self._build_timeline(user_id, proof_session_id)

    def build_skill_evidence_items(self, user_id: str, proof_session_id: str) -> list[SkillEvidenceRecord]:
        return self.get_skill_evidence_timeline(user_id, proof_session_id).skills

    def calculate_skill_support_level(self, skill_name: str, evidence_items: list[SkillEvidenceItem]) -> str:
        _ = skill_name
        strong_count = len([item for item in evidence_items if item.support_strength == "strong"])
        meaningful_count = len([item for item in evidence_items if item.confidence_score >= 45])
        score = _confidence_score(evidence_items)
        if strong_count >= 2 or any(item.evidence_type == "ai_domain_review" and item.confidence_score >= 85 for item in evidence_items):
            return "strong"
        if meaningful_count >= 1 or score >= 45:
            return "partial"
        if evidence_items:
            return "weak"
        return "missing"

    def get_public_skill_evidence_timeline(self, public_slug: str) -> SkillEvidenceTimelineResponse:
        passport = self._passport_by_slug(public_slug)
        if not passport or not passport.get("is_public", True):
            raise PublicWorkPassportNotFoundError(public_slug)
        timeline = self._build_timeline(str(passport["user_id"]), str(passport["proof_session_id"]))
        return _public_timeline(timeline)

    def get_protected_skill_evidence_timeline(self, access_token: str) -> SkillEvidenceTimelineResponse:
        grant = self._grant_by_token(access_token)
        if not grant or grant.get("revoked_at"):
            raise EvidenceAccessDeniedError("Access token is invalid or revoked.")
        expires_at = _parse_dt(grant.get("expires_at"))
        if expires_at and expires_at <= _now():
            raise EvidenceAccessDeniedError("Access token is expired.")
        allowed_types = _allowed_evidence_types(list(grant.get("granted_sections") or []))
        timeline = self._build_timeline(str(grant["user_id"]), str(grant["proof_session_id"]))
        return _protected_timeline(timeline, allowed_types)

    def _build_timeline(self, user_id: str, proof_session_id: str) -> SkillEvidenceTimelineResponse:
        session = self._get_session(user_id, proof_session_id)
        skill_row = self._skill_evidence(user_id, str(session.get("skill_evidence_id") or ""))
        workflow = self._row_by_session(_WORKFLOW, user_id, proof_session_id)
        github = self._row_by_session(_GITHUB, user_id, proof_session_id)
        live = self._row_by_session(_LIVE, user_id, proof_session_id)
        privacy = self._row_by_session(_PRIVACY, user_id, proof_session_id)
        defense = self._row_by_session(_DEFENSE, user_id, proof_session_id)
        ai_domain = self._row_by_session(_AI_DOMAIN, user_id, proof_session_id)
        active_version = self._active_version(user_id, proof_session_id)
        readiness = compute_readiness_report(
            proof_session_id=proof_session_id,
            session_status=str(session.get("status") or ""),
            website_url=str(session.get("website_url") or (skill_row or {}).get("evidence_url") or ""),
            claimed_skills=_claimed_skills(session, skill_row, workflow, github, defense, ai_domain),
            workflow_analysis=workflow,
            live_check=live,
            github_analysis=github,
            privacy_scan=privacy,
            defense_analysis=defense,
        )
        skills = _claimed_skills(session, skill_row, workflow, github, defense, ai_domain)
        records = [
            self._skill_record(
                skill,
                workflow=workflow,
                github=github,
                live=live,
                privacy=privacy,
                defense=defense,
                ai_domain=ai_domain,
                active_version=active_version,
                readiness=readiness,
                skill_row=skill_row,
            )
            for skill in skills
        ]
        records.sort(key=lambda row: ({"strong": 0, "partial": 1, "weak": 2, "missing": 3}[row.support_level], row.skill_name.lower()))
        return SkillEvidenceTimelineResponse(proof_session_id=proof_session_id, skills=records, generated_at=_now())

    def _skill_record(
        self,
        skill_name: str,
        *,
        workflow: dict[str, Any] | None,
        github: dict[str, Any] | None,
        live: dict[str, Any] | None,
        privacy: dict[str, Any] | None,
        defense: dict[str, Any] | None,
        ai_domain: dict[str, Any] | None,
        active_version: dict[str, Any] | None,
        readiness: Any,
        skill_row: dict[str, Any] | None,
    ) -> SkillEvidenceRecord:
        items: list[SkillEvidenceItem] = []
        items.extend(_workflow_items(skill_name, workflow))
        items.extend(_github_items(skill_name, github))
        items.extend(_live_items(skill_name, live, skill_row))
        items.extend(_defense_items(skill_name, defense))
        items.extend(_ai_domain_items(skill_name, ai_domain))
        items.extend(_readiness_items(skill_name, readiness))
        items.extend(_privacy_items(skill_name, privacy))
        items.extend(_version_items(skill_name, active_version))
        score = _confidence_score(items)
        support_level = self.calculate_skill_support_level(skill_name, items)
        gaps = _gaps(skill_name, support_level, items)
        recommendations = _recommended_next_steps(support_level, items, gaps)
        sources = list(dict.fromkeys(item.evidence_type for item in items))
        return SkillEvidenceRecord(
            skill_name=skill_name,
            normalized_skill_name=_normalize_skill(skill_name),
            support_level=support_level,
            confidence_score=score,
            evidence_count=len(items),
            evidence_sources=sources,
            public_safe=all(item.public_safe for item in items) if items else True,
            recruiter_visible=any(item.public_safe or item.protected for item in items),
            evidence_items=items,
            gaps=gaps,
            recommended_next_steps=recommendations,
            last_updated_at=_latest_date([item.created_at for item in items]),
        )

    def _get_session(self, user_id: str, proof_session_id: str) -> dict[str, Any]:
        row = self._by_id(_SESSIONS, proof_session_id)
        if not row or str(row.get("user_id")) != user_id:
            raise ExtensionProofSessionNotFoundError(proof_session_id)
        return row

    def _skill_evidence(self, user_id: str, evidence_id: str) -> dict[str, Any] | None:
        if not evidence_id:
            return None
        row = self._by_id(_SKILL_EVIDENCE, evidence_id)
        return row if row and str(row.get("user_id")) == user_id else None

    def _row_by_session(self, table: str, user_id: str, proof_session_id: str) -> dict[str, Any] | None:
        rows = self._rows_by_session(table, user_id, proof_session_id)
        rows.sort(key=lambda row: str(row.get("created_at") or row.get("updated_at") or ""), reverse=True)
        return rows[0] if rows else None

    def _rows_by_session(self, table: str, user_id: str, proof_session_id: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            return [
                row for row in self._client.get(table, {}).values()
                if str(row.get("user_id")) == user_id and str(row.get("proof_session_id")) == proof_session_id
            ]
        result = self._client.table(table).select("*").eq("user_id", user_id).eq("proof_session_id", proof_session_id).execute()
        return getattr(result, "data", []) or []

    def _active_version(self, user_id: str, proof_session_id: str) -> dict[str, Any] | None:
        for row in self._rows_by_session(_VERSIONS, user_id, proof_session_id):
            if row.get("is_active"):
                return row
        return None

    def _passport_by_slug(self, public_slug: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            for row in self._client.get(_PASSPORTS, {}).values():
                if str(row.get("public_slug")) == public_slug:
                    return row
            return None
        result = self._client.table(_PASSPORTS).select("*").eq("public_slug", public_slug).limit(1).execute()
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _grant_by_token(self, token: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            for row in self._client.get(_GRANTS, {}).values():
                if str(row.get("access_token")) == token:
                    return row
            return None
        result = self._client.table(_GRANTS).select("*").eq("access_token", token).limit(1).execute()
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _by_id(self, table: str, row_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            return self._client.get(table, {}).get(row_id)
        result = self._client.table(table).select("*").eq("id", row_id).limit(1).execute()
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None


def _workflow_items(skill: str, row: dict[str, Any] | None) -> list[SkillEvidenceItem]:
    if not row:
        return []
    if _contains_skill(row.get("supported_skills") or row.get("verified_skills") or row.get("matched_claimed_skills"), skill):
        return [_item("workflow", "Workflow analysis", f"Workflow evidence supports {skill}.", "strong", 75, row, public_safe=True, protected=False)]
    if _contains_skill(row.get("claimed_skills") or row.get("partially_supported_skills"), skill):
        return [_item("workflow", "Workflow analysis", f"Workflow evidence mentions {skill}, but support is partial.", "partial", 55, row, public_safe=True, protected=False)]
    return []


def _github_items(skill: str, row: dict[str, Any] | None) -> list[SkillEvidenceItem]:
    if not row:
        return []
    if _contains_skill(row.get("matched_claimed_skills") or row.get("verified_skills") or row.get("supported_skills"), skill):
        return [_item("github", "GitHub analysis", f"Repository analysis found source evidence for {skill}.", "strong", 85, row, public_safe=True, protected=False, evidence_url=_public_url(row))]
    if _contains_skill(row.get("weakly_matched_claimed_skills") or row.get("partially_verified_skills"), skill):
        return [_item("github", "GitHub analysis", f"Repository analysis found partial evidence for {skill}.", "partial", 55, row, public_safe=True, protected=False, evidence_url=_public_url(row), limitations=["Source evidence is partial."])]
    return []


def _live_items(skill: str, row: dict[str, Any] | None, skill_row: dict[str, Any] | None) -> list[SkillEvidenceItem]:
    if not row or row.get("is_reachable") is not True:
        return []
    return [_item("live_website", "Live website check", f"A live project URL was reachable while evaluating {skill}.", "partial", 45, row, public_safe=True, protected=False, evidence_url=_public_url(row) or _public_url(skill_row or {}))]


def _defense_items(skill: str, row: dict[str, Any] | None) -> list[SkillEvidenceItem]:
    if not row:
        return []
    if _contains_skill(row.get("skills_explained_well"), skill):
        return [_item("project_defense", "Project defense", f"Project defense summary explains ownership and decisions for {skill}.", "strong", 85, row, public_safe=False, protected=True)]
    if _contains_skill(row.get("skills_mentioned"), skill):
        return [_item("project_defense", "Project defense", f"Project defense mentions {skill}.", "partial", 60, row, public_safe=False, protected=True)]
    if row.get("transcript_summary"):
        return [_item("project_defense", "Project defense", f"Project defense summary is available for additional context on {skill}.", "weak", 30, row, public_safe=False, protected=True)]
    return []


def _ai_domain_items(skill: str, row: dict[str, Any] | None) -> list[SkillEvidenceItem]:
    if not row:
        return []
    if _contains_skill(row.get("verified_skills") or row.get("strongly_supported_skills"), skill):
        return [_item("ai_domain_review", "AI Domain Review", f"AI Domain Review verified {skill}.", "strong", 90, row, public_safe=True, protected=False)]
    if _contains_skill(row.get("partially_verified_skills") or row.get("partially_supported_skills"), skill):
        return [_item("ai_domain_review", "AI Domain Review", f"AI Domain Review found partial support for {skill}.", "partial", 65, row, public_safe=True, protected=False)]
    if _contains_skill(row.get("skills_needing_more_evidence") or row.get("needs_more_evidence"), skill):
        return [_item("ai_domain_review", "AI Domain Review", f"AI Domain Review says {skill} needs stronger evidence.", "weak", 30, row, public_safe=True, protected=False, limitations=["Needs stronger evidence."])]
    if int(row.get("domain_review_score") or row.get("overall_score") or 0) >= 85:
        return [_item("ai_domain_review", "AI Domain Review", f"AI Domain Review reports high confidence for the evidence package including {skill}.", "strong", 85, row, public_safe=True, protected=False)]
    return []


def _readiness_items(skill: str, readiness: Any) -> list[SkillEvidenceItem]:
    if _contains_skill(getattr(readiness, "strongly_supported_skills", []), skill):
        return [_computed_item("readiness_report", "Readiness report", f"Readiness report marks {skill} as strongly supported.", "strong", 80)]
    if _contains_skill(getattr(readiness, "partially_supported_skills", []), skill):
        return [_computed_item("readiness_report", "Readiness report", f"Readiness report marks {skill} as partially supported.", "partial", 60)]
    needs = [_need_skill(value) for value in getattr(readiness, "needs_more_evidence", [])]
    if _contains_skill(needs, skill):
        return [_computed_item("readiness_report", "Readiness report", f"Readiness report needs more evidence for {skill}.", "weak", 25, limitations=["More evidence needed."])]
    return []


def _privacy_items(skill: str, row: dict[str, Any] | None) -> list[SkillEvidenceItem]:
    if not row:
        return []
    status = row.get("status") or row.get("privacy_scan_status")
    summary = f"Privacy scan status for evidence involving {skill}: {status or 'available'}."
    return [_item("privacy_scan", "Privacy scan", summary, "weak", 15, row, public_safe=True, protected=False)]


def _version_items(skill: str, row: dict[str, Any] | None) -> list[SkillEvidenceItem]:
    if not row:
        return []
    label = row.get("version_label") or f"Version {row.get('version_number')}"
    return [_item("version_snapshot", "Evidence version", f"{label} is the active evidence version for {skill}.", "weak", 20, row, public_safe=True, protected=False)]


def _item(
    evidence_type: str,
    source_label: str,
    summary: str,
    support_strength: str,
    confidence_score: int,
    row: dict[str, Any],
    *,
    public_safe: bool,
    protected: bool,
    evidence_url: str | None = None,
    limitations: list[str] | None = None,
) -> SkillEvidenceItem:
    return SkillEvidenceItem(
        evidence_type=evidence_type,
        source_label=source_label,
        summary=summary,
        support_strength=support_strength,
        confidence_score=max(0, min(100, int(confidence_score))),
        created_at=row.get("created_at") or row.get("updated_at") or row.get("submitted_at"),
        public_safe=public_safe,
        protected=protected,
        reference_id=str(row.get("id")) if row.get("id") else None,
        evidence_url=evidence_url if public_safe else None,
        limitations=limitations or [],
    )


def _computed_item(
    evidence_type: str,
    source_label: str,
    summary: str,
    support_strength: str,
    confidence_score: int,
    limitations: list[str] | None = None,
) -> SkillEvidenceItem:
    return SkillEvidenceItem(
        evidence_type=evidence_type,
        source_label=source_label,
        summary=summary,
        support_strength=support_strength,
        confidence_score=confidence_score,
        created_at=None,
        public_safe=True,
        protected=False,
        reference_id=None,
        evidence_url=None,
        limitations=limitations or [],
    )


def _public_timeline(timeline: SkillEvidenceTimelineResponse) -> SkillEvidenceTimelineResponse:
    return SkillEvidenceTimelineResponse(
        proof_session_id=timeline.proof_session_id,
        skills=[_filtered_record(record, allowed_types=None, public_only=True) for record in timeline.skills],
        generated_at=timeline.generated_at,
    )


def _protected_timeline(timeline: SkillEvidenceTimelineResponse, allowed_types: set[str]) -> SkillEvidenceTimelineResponse:
    return SkillEvidenceTimelineResponse(
        proof_session_id=timeline.proof_session_id,
        skills=[_filtered_record(record, allowed_types=allowed_types, public_only=False) for record in timeline.skills],
        generated_at=timeline.generated_at,
    )


def _filtered_record(record: SkillEvidenceRecord, *, allowed_types: set[str] | None, public_only: bool) -> SkillEvidenceRecord:
    if public_only:
        visible = [item for item in record.evidence_items if item.public_safe and not item.protected]
        hidden_count = len(record.evidence_items) - len(visible)
    else:
        visible = [
            item for item in record.evidence_items
            if item.evidence_type in (allowed_types or set())
        ]
        hidden_count = len(record.evidence_items) - len(visible)
    if hidden_count:
        visible.append(_protected_placeholder(hidden_count))
    score = _confidence_score(visible)
    support_level = _support_level_from_items(visible)
    return record.model_copy(
        update={
            "support_level": support_level,
            "confidence_score": score,
            "evidence_count": len(visible),
            "evidence_sources": list(dict.fromkeys(item.evidence_type for item in visible)),
            "public_safe": public_only,
            "recruiter_visible": bool(visible),
            "evidence_items": visible,
            "last_updated_at": _latest_date([item.created_at for item in visible]),
        }
    )


def _protected_placeholder(hidden_count: int) -> SkillEvidenceItem:
    noun = "source" if hidden_count == 1 else "sources"
    return SkillEvidenceItem(
        evidence_type="future_upload",
        source_label="Protected evidence",
        summary=f"Protected evidence available by request ({hidden_count} {noun}).",
        support_strength="weak",
        confidence_score=0,
        created_at=None,
        public_safe=True,
        protected=True,
        reference_id=None,
        evidence_url=None,
        limitations=["Private details require approved access."],
    )


def _claimed_skills(*rows: dict[str, Any] | None) -> list[str]:
    values: list[str] = []
    for row in rows:
        if not row:
            continue
        if row.get("skill_name"):
            values.append(str(row["skill_name"]))
        for key in (
            "claimed_skills",
            "supported_skills",
            "verified_skills",
            "strongly_supported_skills",
            "partially_verified_skills",
            "partially_supported_skills",
            "matched_claimed_skills",
            "weakly_matched_claimed_skills",
            "skills_mentioned",
            "skills_explained_well",
        ):
            raw = row.get(key)
            if isinstance(raw, list):
                values.extend(_need_skill(value) for value in raw if str(_need_skill(value)).strip())
    return list(dict.fromkeys(value for value in values if value))


def _contains_skill(values: Any, skill: str) -> bool:
    if not isinstance(values, list):
        return False
    target = _normalize_skill(skill)
    return any(_normalize_skill(_need_skill(value)) == target for value in values)


def _need_skill(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("skill", "skill_name", "name"):
            if value.get(key):
                return str(value[key])
        return ""
    return str(value)


def _normalize_skill(value: str) -> str:
    return " ".join(value.lower().replace("_", " ").replace("-", " ").split())


def _confidence_score(items: list[SkillEvidenceItem]) -> int:
    total = 0
    seen: set[str] = set()
    for item in items:
        if item.evidence_type in seen and item.support_strength != "strong":
            total += min(item.confidence_score, 10)
        else:
            total += item.confidence_score
        seen.add(item.evidence_type)
    return max(0, min(100, total))


def _support_level_from_items(items: list[SkillEvidenceItem]) -> str:
    strong_count = len([item for item in items if item.support_strength == "strong"])
    meaningful_count = len([item for item in items if item.confidence_score >= 45])
    score = _confidence_score(items)
    if strong_count >= 2 or score >= 80:
        return "strong"
    if meaningful_count >= 1 or score >= 45:
        return "partial"
    if items:
        return "weak"
    return "missing"


def _gaps(skill: str, support_level: str, items: list[SkillEvidenceItem]) -> list[str]:
    sources = {item.evidence_type for item in items}
    gaps: list[str] = []
    if support_level in {"missing", "weak"}:
        gaps.append(f"Add direct evidence that demonstrates {skill}.")
    if "github" not in sources:
        gaps.append("Add source or repository evidence where applicable.")
    if "project_defense" not in sources:
        gaps.append("Explain this skill in a project defense summary.")
    if "workflow" not in sources:
        gaps.append("Show the skill in a recorded workflow.")
    return gaps[:3]


def _recommended_next_steps(support_level: str, items: list[SkillEvidenceItem], gaps: list[str]) -> list[str]:
    if support_level == "strong":
        return ["Keep evidence current and review access requests carefully."]
    if gaps:
        return gaps[:2]
    if any(item.limitations for item in items):
        return ["Address the evidence limitations noted for this skill."]
    return ["Add another independent evidence source for this skill."]


def _public_url(row: dict[str, Any]) -> str | None:
    for key in ("repository_url", "github_url", "website_url", "url", "evidence_url", "live_url"):
        value = row.get(key)
        if value and not _blocked_private_key(key):
            return str(value)
    return None


def _blocked_private_key(key: str) -> bool:
    normalized = key.lower()
    blocked_exact = {"media_storage_path", "media_url", "video_url", "transcript_text", "proof_data", "access_token"}
    blocked_fragments = ("private", "internal", "debug", "raw_risk", "raw_metadata")
    return normalized in blocked_exact or any(fragment in normalized for fragment in blocked_fragments)


def _allowed_evidence_types(sections: list[str]) -> set[str]:
    out: set[str] = set()
    for section in sections:
        out.update(_SECTION_TO_TYPES.get(str(section), set()))
    return out


def _latest_date(values: list[Any]) -> Any:
    present = [value for value in values if value]
    return max(present, default=None)


def _parse_dt(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _now() -> datetime:
    return datetime.now(UTC)
