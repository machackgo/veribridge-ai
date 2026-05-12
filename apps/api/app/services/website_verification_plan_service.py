"""Planning layer for future browser-agent website verification."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.schemas.skill_evidence import WebsiteVerificationPlanResponse
from app.services.skill_evidence_service import SkillEvidenceNotFoundError
from app.services.website_verification_guide_service import (
    WebsiteVerificationGuideNotAllowedError,
    WebsiteVerificationGuideNotFoundError,
    _validate_website_evidence,
)

_EVIDENCE_TABLE = "skill_evidence"
_GUIDE_TABLE = "website_verification_guides"
_PLAN_TABLE = "website_verification_plans"
_PLANNER_VERSION = "website-plan-v1"

_VAGUE_STEP_PHRASES = (
    "test the app",
    "test app",
    "check the website",
    "verify it works",
    "try it",
    "use the site",
    "open and test",
)
_UNSUPPORTED_TERMS = (
    "upload",
    "download",
    "camera",
    "microphone",
    "payment",
    "stripe",
    "oauth",
    "email verification",
    "captcha",
    "2fa",
    "two-factor",
    "admin approval",
)


class WebsiteVerificationPlanNotFoundError(LookupError):
    """No generated website verification plan exists for the evidence row."""


class WebsiteVerificationPlanService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def generate_plan(self, user_id: str, evidence_id: str) -> WebsiteVerificationPlanResponse:
        evidence = self._get_evidence_row(user_id, evidence_id)
        _validate_website_evidence(evidence)
        guide = self._get_guide_row(user_id, evidence_id)
        if not guide:
            raise WebsiteVerificationGuideNotFoundError(evidence_id)

        plan = _build_plan(evidence, guide)
        data = {
            **plan,
            "user_id": user_id,
            "skill_evidence_id": evidence_id,
            "website_verification_guide_id": guide.get("id"),
            "planner_version": _PLANNER_VERSION,
            "guide_snapshot": _guide_snapshot(guide),
        }

        if isinstance(self._client, dict):
            row = {
                "id": str(uuid4()),
                "created_at": _now(),
                **data,
            }
            self._client.setdefault(_PLAN_TABLE, {})[row["id"]] = row
            return _to_response(row)

        result = self._client.table(_PLAN_TABLE).insert(data).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError("Website verification plan insert returned no data.")
        return _to_response(rows[0])

    def get_latest_plan(self, user_id: str, evidence_id: str) -> WebsiteVerificationPlanResponse:
        self._get_evidence_row(user_id, evidence_id)
        if isinstance(self._client, dict):
            rows = [
                row
                for row in self._client.setdefault(_PLAN_TABLE, {}).values()
                if row.get("user_id") == user_id and row.get("skill_evidence_id") == evidence_id
            ]
            if not rows:
                raise WebsiteVerificationPlanNotFoundError(evidence_id)
            rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
            return _to_response(rows[0])

        result = (
            self._client.table(_PLAN_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("skill_evidence_id", evidence_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        if not rows:
            raise WebsiteVerificationPlanNotFoundError(evidence_id)
        return _to_response(rows[0])

    def _get_evidence_row(self, user_id: str, evidence_id: str) -> dict[str, Any]:
        if isinstance(self._client, dict):
            row = self._client.setdefault(_EVIDENCE_TABLE, {}).get(evidence_id)
            if not row or row.get("user_id") != user_id:
                raise SkillEvidenceNotFoundError(evidence_id)
            return row

        result = (
            self._client.table(_EVIDENCE_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", evidence_id)
            .maybe_single()
            .execute()
        )
        if result is None or not result.data:
            raise SkillEvidenceNotFoundError(evidence_id)
        return result.data

    def _get_guide_row(self, user_id: str, evidence_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            for row in self._client.setdefault(_GUIDE_TABLE, {}).values():
                if row.get("user_id") == user_id and row.get("skill_evidence_id") == evidence_id:
                    return row
            return None

        result = (
            self._client.table(_GUIDE_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("skill_evidence_id", evidence_id)
            .maybe_single()
            .execute()
        )
        if result is None:
            return None
        return result.data


def _build_plan(evidence: dict[str, Any], guide: dict[str, Any]) -> dict[str, Any]:
    normalized_steps = _normalize_steps(guide.get("verification_steps") or [])
    expected_output = _clean(guide.get("expected_output"))
    feature = _clean(guide.get("feature_to_verify"))
    sample_inputs = guide.get("sample_inputs")
    validation_warnings: list[str] = []

    if not normalized_steps:
        validation_warnings.append("vague_verification_steps")
    elif _has_vague_steps(normalized_steps):
        validation_warnings.append("vague_verification_steps")

    if _needs_sample_inputs(normalized_steps) and not sample_inputs:
        validation_warnings.append("missing_sample_inputs")

    if _expected_output_too_generic(expected_output):
        validation_warnings.append("expected_output_too_generic")

    if guide.get("login_required") and not _safe_access_notes_present(guide):
        validation_warnings.append("login_required_without_safe_access_notes")

    unsupported_hits = _unsupported_hits(normalized_steps, guide)
    if unsupported_hits:
        validation_warnings.append("unsupported_instruction_detected")

    plan_status = _plan_status(validation_warnings, normalized_steps, expected_output)
    requires_login = bool(guide.get("login_required"))
    can_attempt = plan_status == "ready" and not (
        requires_login and "login_required_without_safe_access_notes" in validation_warnings
    )

    return {
        "website_url": _clean(evidence.get("evidence_url")),
        "feature_to_verify": feature,
        "plan_status": plan_status,
        "normalized_test_steps": normalized_steps,
        "expected_output": expected_output,
        "sample_inputs": sample_inputs,
        "inferred_action_candidates": _infer_action_candidates(normalized_steps),
        "validation_warnings": validation_warnings,
        "agent_notes": _agent_notes(plan_status, validation_warnings, unsupported_hits),
        "requires_login": requires_login,
        "can_attempt_automated_execution": can_attempt,
    }


def _normalize_steps(steps: list[Any]) -> list[str]:
    normalized = []
    for step in steps:
        text = _clean(step)
        if text:
            normalized.append(text)
    return normalized


def _has_vague_steps(steps: list[str]) -> bool:
    if len(steps) < 2:
        return True
    combined = " ".join(steps).lower()
    return any(phrase in combined for phrase in _VAGUE_STEP_PHRASES)


def _needs_sample_inputs(steps: list[str]) -> bool:
    combined = " ".join(steps).lower()
    return any(term in combined for term in ("enter", "type", "input", "fill", "select", "choose", "search", "submit"))


def _expected_output_too_generic(expected_output: str) -> bool:
    normalized = expected_output.lower()
    if len(normalized) < 20:
        return True
    return normalized in {"it works", "works", "success", "shows result", "the app works"}


def _safe_access_notes_present(guide: dict[str, Any]) -> bool:
    notes = f"{_clean(guide.get('login_notes'))} {_clean(guide.get('access_notes'))}".strip().lower()
    if not notes:
        return False
    unsafe_markers = ("password:", "secret", "private key", "personal account")
    return not any(marker in notes for marker in unsafe_markers)


def _unsupported_hits(steps: list[str], guide: dict[str, Any]) -> list[str]:
    combined = " ".join(
        [
            " ".join(steps),
            _clean(guide.get("project_overview")),
            _clean(guide.get("expected_output")),
            _clean(guide.get("additional_notes")),
            _clean(guide.get("known_limitations")),
        ]
    ).lower()
    return [term for term in _UNSUPPORTED_TERMS if term in combined]


def _plan_status(warnings: list[str], steps: list[str], expected_output: str) -> str:
    if "unsupported_instruction_detected" in warnings:
        return "unsupported"
    if not steps or not expected_output:
        return "needs_more_detail"
    blocking = {
        "vague_verification_steps",
        "missing_sample_inputs",
        "expected_output_too_generic",
        "login_required_without_safe_access_notes",
    }
    if any(warning in blocking for warning in warnings):
        return "needs_more_detail"
    return "ready"


def _infer_action_candidates(steps: list[str]) -> list[dict[str, Any]]:
    candidates = []
    for index, step in enumerate(steps, start=1):
        lower = step.lower()
        action_type = "observe"
        if any(term in lower for term in ("open", "navigate", "go to", "visit")):
            action_type = "navigate"
        elif any(term in lower for term in ("enter", "type", "fill", "input")):
            action_type = "input"
        elif any(term in lower for term in ("select", "choose")):
            action_type = "select"
        elif any(term in lower for term in ("click", "submit", "press")):
            action_type = "click"
        elif any(term in lower for term in ("confirm", "verify", "check", "compare", "see")):
            action_type = "assert"
        candidates.append(
            {
                "step_number": index,
                "action_type": action_type,
                "instruction": step,
            }
        )
    return candidates


def _agent_notes(plan_status: str, warnings: list[str], unsupported_hits: list[str]) -> str:
    if plan_status == "ready":
        return "Plan is structured enough for a future browser executor. No browser actions are executed in this phase."
    if plan_status == "unsupported":
        return (
            "Plan includes instructions outside the current future browser-agent scope: "
            f"{', '.join(unsupported_hits)}. No browser actions are executed in this phase."
        )
    return (
        "Plan needs more detail before automated execution. Warnings: "
        f"{', '.join(warnings) if warnings else 'missing detail'}. No browser actions are executed in this phase."
    )


def _guide_snapshot(guide: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": guide.get("id"),
        "project_overview": guide.get("project_overview"),
        "feature_to_verify": guide.get("feature_to_verify"),
        "verification_steps": guide.get("verification_steps") or [],
        "sample_inputs": guide.get("sample_inputs"),
        "expected_output": guide.get("expected_output"),
        "login_required": guide.get("login_required"),
        "login_notes": guide.get("login_notes"),
        "access_notes": guide.get("access_notes"),
        "known_limitations": guide.get("known_limitations"),
        "additional_notes": guide.get("additional_notes"),
    }


def _to_response(row: dict[str, Any]) -> WebsiteVerificationPlanResponse:
    return WebsiteVerificationPlanResponse(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        skill_evidence_id=str(row["skill_evidence_id"]),
        website_url=row["website_url"],
        feature_to_verify=row["feature_to_verify"],
        plan_status=row["plan_status"],
        normalized_test_steps=list(row.get("normalized_test_steps") or []),
        expected_output=row["expected_output"],
        sample_inputs=row.get("sample_inputs"),
        inferred_action_candidates=list(row.get("inferred_action_candidates") or []),
        validation_warnings=list(row.get("validation_warnings") or []),
        agent_notes=row.get("agent_notes") or "",
        requires_login=bool(row.get("requires_login")),
        can_attempt_automated_execution=bool(row.get("can_attempt_automated_execution")),
        planner_version=row.get("planner_version") or _PLANNER_VERSION,
        created_at=str(row.get("created_at") or ""),
    )


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _now() -> str:
    return datetime.now(UTC).isoformat()
