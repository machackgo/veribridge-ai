"""AI Domain Reviewer Agent backend service.

The service is deterministic first. It never requires Anthropic credentials for
local development or tests; when the reviewer LLM is not configured, the saved
row includes a fallback reason and rubric-based result.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from app.core.config import settings
from app.schemas.ai_domain_review import AiDomainReviewResultResponse
from app.services.ai_domain_reviewer_rubrics import COMMON_LIMITATION, get_rubric
from app.services.extension_proof_service import ExtensionProofSessionNotFoundError
from app.services.verification_readiness_service import compute_readiness_report

logger = logging.getLogger(__name__)

_TABLE = "ai_domain_review_results"
_SESSION_TABLE = "extension_proof_sessions"
_SKILL_TABLE = "skill_evidence"
_WORKFLOW_TABLE = "workflow_analysis_results"
_GITHUB_TABLE = "extension_proof_github_analysis"
_LIVE_TABLE = "live_website_check_results"
_PRIVACY_TABLE = "workflow_privacy_scan_results"
_DEFENSE_TABLE = "project_defense_analysis_results"

_FALLBACK_REASON = "LLM reviewer not configured; using rubric-based deterministic review."
_DISCLOSURE = (
    "This proof has been AI-reviewed using a field-specific rubric by a "
    "VeriBridge AI Domain Reviewer. Human/faculty/company review has not been "
    "completed unless explicitly shown."
)


class AiDomainReviewNotFoundError(LookupError):
    """No AI domain review result exists for this proof session."""


class AiDomainReviewService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def run_or_fetch_review(
        self,
        user_id: str,
        session_id: str,
        *,
        force: bool = False,
    ) -> AiDomainReviewResultResponse:
        self._get_session(user_id, session_id)
        if not force:
            existing = self._get_existing(user_id, session_id)
            if existing is not None:
                return _to_response(existing)

        evidence = self._gather_evidence(user_id, session_id)
        row = self._build_deterministic_result(user_id, session_id, evidence)
        saved = self._upsert(row)
        return _to_response(saved)

    def get_review(self, user_id: str, session_id: str) -> AiDomainReviewResultResponse:
        self._get_session(user_id, session_id)
        row = self._get_existing(user_id, session_id)
        if row is None:
            raise AiDomainReviewNotFoundError(session_id)
        return _to_response(row)

    def _gather_evidence(self, user_id: str, session_id: str) -> dict[str, Any]:
        session = self._get_session(user_id, session_id)
        skill = self._get_skill_evidence(user_id, str(session.get("skill_evidence_id") or ""))
        workflow = self._get_by_session(_WORKFLOW_TABLE, user_id, session_id)
        github = self._get_by_session(_GITHUB_TABLE, user_id, session_id)
        live = self._get_by_session(_LIVE_TABLE, user_id, session_id)
        privacy = self._get_by_session(_PRIVACY_TABLE, user_id, session_id)
        defense = self._get_by_session(_DEFENSE_TABLE, user_id, session_id)

        claimed_skills = _claimed_skills(session, skill, workflow, github)
        readiness = compute_readiness_report(
            proof_session_id=session_id,
            session_status=str(session.get("status") or ""),
            website_url=_website_url(session, skill),
            claimed_skills=claimed_skills,
            workflow_analysis=workflow,
            live_check=live,
            github_analysis=github,
            privacy_scan=privacy,
            defense_analysis=defense,
        )

        return {
            "session": session,
            "skill_evidence": skill,
            "claimed_skills": claimed_skills,
            "workflow_analysis": workflow,
            "github_analysis": github,
            "live_website_check": live,
            "privacy_scan": privacy,
            "project_defense_analysis": defense,
            "readiness_report": readiness,
        }

    def _build_deterministic_result(
        self,
        user_id: str,
        session_id: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        now = _now()
        domain = choose_domain(evidence)
        rubric = get_rubric(domain)
        readiness = evidence["readiness_report"]
        sources = _available_sources(evidence)
        privacy_flagged = _privacy_flagged(evidence)
        high_risk_reason = _high_risk_reason(evidence, domain)
        contradiction_reason = _contradiction_reason(evidence)

        criterion_scores = [
            _score_criterion(c, evidence, sources, readiness.readiness_score)
            for c in rubric["criteria"]
        ]
        max_total = sum(int(c["max_score"]) for c in criterion_scores) or 1
        raw_total = sum(int(c["score"]) for c in criterion_scores)
        rubric_score = round(raw_total / max_total * 100)
        score = round((rubric_score * 0.55) + (readiness.readiness_score * 0.45))

        if privacy_flagged:
            score = min(score, 50)
        if high_risk_reason:
            score = min(score, 79)
        if contradiction_reason:
            score = min(score, 59)
        score = max(0, min(100, score))

        confidence = _confidence_level(score, len(sources), readiness.risk_flags)
        human_reason = _human_review_reason(
            privacy_flagged=privacy_flagged,
            high_risk_reason=high_risk_reason,
            contradiction_reason=contradiction_reason,
            confidence=confidence,
            readiness=readiness,
        )
        human_review_recommended = human_reason is not None
        status = _status(score, privacy_flagged, human_review_recommended, confidence)

        verified = list(readiness.strongly_supported_skills)
        partial = list(readiness.partially_supported_skills)
        needing = [_clean_need_more(s) for s in readiness.needs_more_evidence]
        if not verified and evidence["claimed_skills"] and score >= 70:
            verified = list(evidence["claimed_skills"][:2])
        if not needing:
            needing = [
                s for s in evidence["claimed_skills"]
                if s not in verified and s not in partial
            ]

        concerns = list(readiness.risk_flags)
        if privacy_flagged:
            concerns.append("Privacy scan flagged sensitive or unredacted evidence.")
        if high_risk_reason:
            concerns.append(high_risk_reason)
        if contradiction_reason:
            concerns.append(contradiction_reason)

        next_steps = _student_next_steps(status, needing, concerns)
        recruiter_summary = _recruiter_summary(
            reviewer_name=str(rubric["reviewer_name"]),
            reviewer_role=str(rubric["reviewer_role"]),
            status=status,
            score=score,
            confidence=confidence,
            verified=verified,
            partial=partial,
            human_review_recommended=human_review_recommended,
        )

        llm_used = False
        fallback_reason = None if settings.anthropic_configured else _FALLBACK_REASON

        return {
            "id": str(uuid4()),
            "user_id": user_id,
            "proof_session_id": session_id,
            "reviewer_name": rubric["reviewer_name"],
            "reviewer_role": rubric["reviewer_role"],
            "domain": rubric["domain"],
            "ai_domain_review_status": status,
            "domain_review_score": score,
            "confidence_level": confidence,
            "verified_skills": verified,
            "partially_verified_skills": partial,
            "skills_needing_more_evidence": needing,
            "domain_specific_strengths": _strengths(verified, sources, evidence),
            "domain_specific_concerns": _dedupe(concerns),
            "criterion_scores": criterion_scores,
            "evidence_sources_reviewed": sources,
            "human_review_recommended": human_review_recommended,
            "human_review_reason": human_reason,
            "recruiter_summary": recruiter_summary,
            "student_next_steps": next_steps,
            "review_limitations": COMMON_LIMITATION,
            "disclosure_note": _DISCLOSURE,
            "llm_used": llm_used,
            "fallback_reason": fallback_reason,
            "human_ai_agreement_score": None,
            "calibration_status": None,
            "reviewed_against_human_baseline": None,
            "created_at": now,
            "updated_at": now,
            "evidence_hash": _evidence_hash(evidence),
        }

    def _get_session(self, user_id: str, session_id: str) -> dict[str, Any]:
        if isinstance(self._client, dict):
            row = self._client.setdefault(_SESSION_TABLE, {}).get(session_id)
            if not row or str(row.get("user_id")) != user_id:
                raise ExtensionProofSessionNotFoundError(session_id)
            return row

        result = (
            self._client.table(_SESSION_TABLE)
            .select("*")
            .eq("id", session_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if result is None or not getattr(result, "data", None):
            raise ExtensionProofSessionNotFoundError(session_id)
        return result.data

    def _get_skill_evidence(self, user_id: str, evidence_id: str) -> dict[str, Any] | None:
        if not evidence_id:
            return None
        if isinstance(self._client, dict):
            row = self._client.setdefault(_SKILL_TABLE, {}).get(evidence_id)
            if row and str(row.get("user_id")) == user_id:
                return row
            return None

        result = (
            self._client.table(_SKILL_TABLE)
            .select("*")
            .eq("id", evidence_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return getattr(result, "data", None) if result is not None else None

    def _get_by_session(self, table: str, user_id: str, session_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            for row in self._client.get(table, {}).values():
                if (
                    str(row.get("proof_session_id")) == session_id
                    and str(row.get("user_id")) == user_id
                ):
                    return row
            return None

        result = (
            self._client.table(table)
            .select("*")
            .eq("proof_session_id", session_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _get_existing(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            for row in self._client.get(_TABLE, {}).values():
                if (
                    str(row.get("proof_session_id")) == session_id
                    and str(row.get("user_id")) == user_id
                ):
                    return row
            return None

        result = (
            self._client.table(_TABLE)
            .select("*")
            .eq("proof_session_id", session_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _upsert(self, row: dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        data.pop("evidence_hash", None)
        if isinstance(self._client, dict):
            store = self._client.setdefault(_TABLE, {})
            for existing_id, existing in store.items():
                if str(existing.get("proof_session_id")) == row["proof_session_id"]:
                    updated = {**existing, **data, "id": existing_id, "updated_at": _now()}
                    store[existing_id] = updated
                    return updated
            store[data["id"]] = data
            return data

        result = (
            self._client.table(_TABLE)
            .upsert(make_json_safe(data), on_conflict="proof_session_id")
            .execute()
        )
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError("AI domain review upsert returned no data.")
        return rows[0]


def choose_domain(evidence: dict[str, Any]) -> str:
    text = _domain_text(evidence)
    if _has_any(text, ["civil", "mechanical", "structural", "cad", "solidworks", "ansys", "load", "stress", "beam", "hvac"]):
        return "civil_mech_eng"
    if _has_any(text, ["business", "finance", "analytics", "accounting", "market", "revenue", "valuation", "dashboard", "kpi", "excel", "power bi", "tableau"]):
        return "business_finance"
    if _has_any(text, ["research", "academic", "paper", "study", "hypothesis", "literature", "citation", "methodology", "experiment"]):
        return "research"
    if _has_any(text, ["computer science", "software", "python", "javascript", "typescript", "react", "backend", "frontend", "machine learning", "data science", "ai", "llm", "github", "api"]):
        return "cs_ai"
    return "general"


def _score_criterion(
    criterion: dict[str, Any],
    evidence: dict[str, Any],
    sources: list[str],
    readiness_score: int,
) -> dict[str, Any]:
    expected_sources = list(criterion["evidence_sources_to_check"])
    used = [s for s in expected_sources if s in sources or s == "claimed_skills"]
    missing = [s for s in expected_sources if s not in used and s != "uploaded_files"]
    source_score = min(5, len([s for s in used if s != "claimed_skills"]))
    if "readiness_report" in expected_sources:
        source_score = max(source_score, round(readiness_score / 20))
    if _privacy_flagged(evidence) and "privacy_scan" in expected_sources:
        source_score = 0
    if _contradiction_reason(evidence) and "project_defense_analysis" in expected_sources:
        source_score = min(source_score, 2)

    score = max(0, min(5, source_score))
    level = "strong" if score >= 4 else "moderate" if score >= 3 else "weak" if score else "absent"
    snippets = _snippets_for_sources(evidence, used)
    return {
        "criterion_name": criterion["criterion_name"],
        "score": score,
        "max_score": int(criterion["max_score"]),
        "justification": (
            f"{criterion['criterion_name']} scored {score}/{criterion['max_score']} "
            f"based on {', '.join(used) if used else 'no available matching evidence sources'}. "
            "Scoring uses technical substance and evidence consistency, not grammar, accent, or non-native English phrasing."
        ),
        "evidence_sources_used": used,
        "evidence_snippets_or_references": snippets,
        "missing_evidence": missing,
        "level": level,
    }


def _available_sources(evidence: dict[str, Any]) -> list[str]:
    sources = ["claimed_skills", "readiness_report"]
    for key in [
        "workflow_analysis",
        "github_analysis",
        "live_website_check",
        "privacy_scan",
        "project_defense_analysis",
    ]:
        if evidence.get(key):
            sources.append(key)
    return sources


def _claimed_skills(
    session: dict[str, Any],
    skill: dict[str, Any] | None,
    workflow: dict[str, Any] | None,
    github: dict[str, Any] | None,
) -> list[str]:
    values: list[str] = []
    if skill and skill.get("skill_name"):
        values.append(str(skill["skill_name"]))
    for source in [session.get("proof_data") or {}, skill or {}, workflow or {}, github or {}]:
        for key in ["claimed_skills", "supported_skills", "matched_claimed_skills"]:
            raw = source.get(key)
            if isinstance(raw, list):
                values.extend(str(v) for v in raw if str(v).strip())
        meta = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
        raw_meta = meta.get("claimed_skills") or meta.get("skills")
        if isinstance(raw_meta, list):
            values.extend(str(v) for v in raw_meta if str(v).strip())
    return _dedupe([v.strip() for v in values if v.strip()])


def _website_url(session: dict[str, Any], skill: dict[str, Any] | None) -> str:
    proof_data = session.get("proof_data") if isinstance(session.get("proof_data"), dict) else {}
    return str(
        proof_data.get("website_url")
        or proof_data.get("url")
        or (skill or {}).get("evidence_url")
        or ""
    )


def _domain_text(evidence: dict[str, Any]) -> str:
    pieces: list[str] = []
    for key in ["session", "skill_evidence", "workflow_analysis", "github_analysis", "project_defense_analysis"]:
        row = evidence.get(key) or {}
        pieces.extend(str(row.get(field) or "") for field in ["skill_name", "evidence_type", "evidence_description", "recruiter_summary", "summary"])
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        pieces.extend(str(metadata.get(field) or "") for field in ["field", "discipline", "domain", "project_type", "major"])
    pieces.extend(evidence.get("claimed_skills") or [])
    return " ".join(pieces).lower()


def _privacy_flagged(evidence: dict[str, Any]) -> bool:
    privacy = evidence.get("privacy_scan") or {}
    defense = evidence.get("project_defense_analysis") or {}
    return str(privacy.get("status") or "").lower() == "flagged" or str(defense.get("privacy_scan_status") or "").lower() == "flagged"


def _high_risk_reason(evidence: dict[str, Any], domain: str) -> str | None:
    text = _domain_text(evidence)
    risk_terms = [
        "healthcare", "clinical", "patient", "medical", "diagnostic", "legal",
        "compliance", "safety-critical", "safety critical", "structural",
        "load-bearing", "load bearing", "financial advice", "investment advice",
    ]
    if _has_any(text, risk_terms):
        return "High-stakes domain claims are present; human/faculty/company review is recommended."
    if domain == "civil_mech_eng" and _has_any(text, ["load", "stress", "structural", "safety", "beam", "bridge"]):
        return "Civil/mechanical safety or structural evidence should be reviewed by a qualified human expert."
    return None


def _contradiction_reason(evidence: dict[str, Any]) -> str | None:
    readiness = evidence.get("readiness_report")
    flags = list(getattr(readiness, "risk_flags", []) or [])
    defense = evidence.get("project_defense_analysis") or {}
    flags.extend(str(f) for f in defense.get("risk_flags", []) or [])
    if any("contradict" in f.lower() or "inconsistent" in f.lower() for f in flags):
        return "Transcript or evidence signals may contradict other submitted artifacts."
    return None


def _human_review_reason(**kwargs: Any) -> str | None:
    if kwargs["privacy_flagged"]:
        return "Privacy scan flagged sensitive or unredacted evidence."
    if kwargs["high_risk_reason"]:
        return str(kwargs["high_risk_reason"])
    if kwargs["contradiction_reason"]:
        return str(kwargs["contradiction_reason"])
    readiness = kwargs["readiness"]
    if kwargs["confidence"] == "low":
        return "Low confidence due to limited or inconsistent evidence."
    if len(readiness.partially_supported_skills) > len(readiness.strongly_supported_skills) and readiness.partially_supported_skills:
        return "Major claimed skills are only partially supported by available evidence."
    return None


def _status(score: int, privacy_flagged: bool, human_review_recommended: bool, confidence: str) -> str:
    if privacy_flagged:
        return "privacy_blocked"
    if human_review_recommended and score >= 60:
        return "human_review_recommended"
    if score >= 80 and confidence != "low":
        return "ai_domain_reviewed"
    return "needs_more_evidence"


def _confidence_level(score: int, source_count: int, risk_flags: list[str]) -> str:
    if source_count >= 5 and score >= 80 and not risk_flags:
        return "high"
    if source_count >= 3 and score >= 60:
        return "medium"
    return "low"


def _strengths(verified: list[str], sources: list[str], evidence: dict[str, Any]) -> list[str]:
    strengths: list[str] = []
    if verified:
        strengths.append(f"Strong evidence supports: {', '.join(verified[:5])}.")
    if "project_defense_analysis" in sources:
        strengths.append("Project defense evidence was available for ownership and understanding review.")
    if "github_analysis" in sources:
        strengths.append("Repository evidence was available for technical artifact review.")
    if "live_website_check" in sources:
        strengths.append("Runtime or live project evidence was available.")
    return strengths or ["Available evidence was reviewed against a field-specific rubric."]


def _student_next_steps(status: str, needing: list[str], concerns: list[str]) -> list[str]:
    steps: list[str] = []
    if needing:
        steps.append(f"Add stronger evidence for: {', '.join(needing[:5])}.")
    if concerns:
        steps.append("Address risk flags or request human review before relying on this result.")
    if status == "privacy_blocked":
        steps.append("Remove or redact sensitive data, rerun the privacy scan, and submit a fresh review.")
    if not steps:
        steps.append("Keep evidence artifacts available and consider human review for higher-trust use cases.")
    return steps


def _recruiter_summary(
    *,
    reviewer_name: str,
    reviewer_role: str,
    status: str,
    score: int,
    confidence: str,
    verified: list[str],
    partial: list[str],
    human_review_recommended: bool,
) -> str:
    skill_text = ", ".join(verified[:5]) if verified else "the submitted claimed skills"
    summary = (
        f"Reviewed by VeriBridge AI Domain Reviewer {reviewer_name} "
        f"({reviewer_role}) using a field-specific rubric. The evidence scored "
        f"{score}/100 with {confidence} confidence and status '{status}'. "
        f"Supported evidence is strongest for {skill_text}."
    )
    if partial:
        summary += f" Partial support remains for: {', '.join(partial[:5])}."
    if human_review_recommended:
        summary += " Human/faculty/company review is recommended before treating this as a high-trust credential."
    else:
        summary += " Human/faculty/company review has not been completed unless explicitly shown."
    return summary


def _snippets_for_sources(evidence: dict[str, Any], sources: list[str]) -> list[str]:
    snippets: list[str] = []
    readiness = evidence.get("readiness_report")
    for source in sources:
        if source == "readiness_report" and readiness is not None:
            snippets.append(f"Readiness report: {readiness.readiness_score}/100 ({readiness.readiness_level}).")
        elif source == "claimed_skills":
            skills = evidence.get("claimed_skills") or []
            snippets.append(f"Claimed skills: {', '.join(skills[:6]) or 'none listed'}.")
        elif source == "github_analysis":
            row = evidence.get(source) or {}
            snippets.append(f"GitHub analysis status: {row.get('status', 'available')}.")
        elif source == "live_website_check":
            row = evidence.get(source) or {}
            snippets.append(f"Live check reachable: {row.get('is_reachable', 'unknown')}.")
        elif source == "privacy_scan":
            row = evidence.get(source) or {}
            snippets.append(f"Privacy scan status: {row.get('status', 'available')}.")
        elif source == "project_defense_analysis":
            row = evidence.get(source) or {}
            snippets.append(f"Project defense score: {row.get('overall_defense_score', 'available')}.")
        elif source == "workflow_analysis":
            row = evidence.get(source) or {}
            snippets.append(f"Workflow supported skills: {', '.join((row.get('supported_skills') or [])[:5])}.")
    return snippets


def _clean_need_more(value: str) -> str:
    return value.split(" — ", 1)[0].strip()


def _has_any(text: str, needles: list[str]) -> bool:
    return any(n in text for n in needles)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _evidence_hash(evidence: dict[str, Any]) -> str:
    payload = json.dumps(evidence, default=str, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _to_response(row: dict[str, Any]) -> AiDomainReviewResultResponse:
    return AiDomainReviewResultResponse(**row)


def _now() -> str:
    """Return current UTC time as an ISO 8601 string (httpx/Supabase-compatible).

    httpx does not have a datetime JSON encoder, so raw datetime objects in
    insert/update payloads raise TypeError.  All timestamps stored in the DB
    must be ISO strings.
    """
    return datetime.now(UTC).isoformat()


def make_json_safe(value: Any) -> Any:
    """Recursively convert non-JSON-serializable values to safe primitives.

    Handles: datetime / date → isoformat string, UUID → str,
    dict → sanitised dict, list/tuple → sanitised list.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: make_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [make_json_safe(item) for item in value]
    return value
