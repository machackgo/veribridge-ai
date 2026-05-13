"""Static website verification executor foundation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.schemas.website_verification_run import (
    WebsiteVerificationRunCheckResponse,
    WebsiteVerificationRunResponse,
)
from app.services.skill_evidence_service import SkillEvidenceNotFoundError
from app.services.website_public_inspection_service import (
    WebsiteInspectionResult,
    WebsitePublicInspectionService,
)
from app.services.website_verification_guide_service import (
    WebsiteVerificationGuideNotAllowedError,
    _validate_website_evidence,
)
from app.services.website_verification_plan_service import WebsiteVerificationPlanNotFoundError

_EVIDENCE_TABLE = "skill_evidence"
_PLAN_TABLE = "website_verification_plans"
_RUN_TABLE = "website_verification_runs"
_CHECK_TABLE = "website_verification_run_checks"
_EXECUTOR_VERSION = "website-executor-static-v1"
_TEXT_EXCERPT_CHARS = 2000


class WebsiteVerificationRunNotFoundError(LookupError):
    """No website verification run exists for the scoped evidence row."""


@dataclass(frozen=True)
class _CheckResult:
    check_key: str
    check_label: str
    check_type: str
    expected_value: str | None
    observed_value: str | None
    check_status: str
    check_summary: str


class WebsiteVerificationExecutorService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def execute_latest_website_verification_plan(self, user_id: str, evidence_id: str) -> WebsiteVerificationRunResponse:
        evidence = self._get_evidence_row(user_id, evidence_id)
        _validate_website_evidence(evidence)
        plan = self._get_latest_plan_row(user_id, evidence_id)
        return self.execute_website_verification_plan(user_id, evidence_id, str(plan["id"]))

    def execute_website_verification_plan(
        self,
        user_id: str,
        evidence_id: str,
        plan_id: str,
    ) -> WebsiteVerificationRunResponse:
        evidence = self._get_evidence_row(user_id, evidence_id)
        _validate_website_evidence(evidence)
        plan = self._get_plan_row(user_id, evidence_id, plan_id)
        inspection = WebsitePublicInspectionService().inspect_url(plan.get("website_url"))
        checks = build_static_checks_from_plan(plan, inspection)
        status = determine_execution_status(checks, plan, inspection)
        summary = summarize_execution(checks, status, plan, inspection)
        return self._persist_verification_run(user_id, evidence_id, plan, inspection, checks, status, summary)

    def list_runs(self, user_id: str, evidence_id: str) -> list[WebsiteVerificationRunResponse]:
        self._get_evidence_row(user_id, evidence_id)
        if isinstance(self._client, dict):
            rows = [
                row
                for row in self._client.setdefault(_RUN_TABLE, {}).values()
                if row.get("user_id") == user_id and row.get("evidence_id") == evidence_id
            ]
            rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
            return [self._run_response_with_checks(row) for row in rows]

        result = (
            self._client.table(_RUN_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("evidence_id", evidence_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [self._run_response_with_checks(row) for row in (getattr(result, "data", []) or [])]

    def get_latest_run(self, user_id: str, evidence_id: str) -> WebsiteVerificationRunResponse:
        self._get_evidence_row(user_id, evidence_id)
        runs = self.list_runs(user_id, evidence_id)
        if not runs:
            raise WebsiteVerificationRunNotFoundError(evidence_id)
        return runs[0]

    def get_run(self, user_id: str, evidence_id: str, run_id: str) -> WebsiteVerificationRunResponse:
        self._get_evidence_row(user_id, evidence_id)
        if isinstance(self._client, dict):
            row = self._client.setdefault(_RUN_TABLE, {}).get(run_id)
            if not row or row.get("user_id") != user_id or row.get("evidence_id") != evidence_id:
                raise WebsiteVerificationRunNotFoundError(run_id)
            return self._run_response_with_checks(row)

        result = (
            self._client.table(_RUN_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("evidence_id", evidence_id)
            .eq("id", run_id)
            .maybe_single()
            .execute()
        )
        if result is None or not result.data:
            raise WebsiteVerificationRunNotFoundError(run_id)
        return self._run_response_with_checks(result.data)

    def _persist_verification_run(
        self,
        user_id: str,
        evidence_id: str,
        plan: dict[str, Any],
        inspection: WebsiteInspectionResult,
        checks: list[_CheckResult],
        status: str,
        summary: str,
    ) -> WebsiteVerificationRunResponse:
        counts = _check_counts(checks)
        run_data = {
            "evidence_id": evidence_id,
            "plan_id": str(plan["id"]),
            "user_id": user_id,
            "execution_status": status,
            "executor_version": _EXECUTOR_VERSION,
            "execution_summary": summary,
            "checks_attempted": len(checks),
            "checks_passed": counts["passed"],
            "checks_failed": counts["failed"],
            "checks_needing_review": counts["needs_review"],
            "inspected_url": inspection.final_url,
            "inspected_title": inspection.page_title,
            "inspected_meta_description": inspection.meta_description,
            "inspected_headings": inspection.headings,
            "inspected_visible_text_excerpt": _excerpt(inspection.visible_text),
            "raw_executor_notes": {
                "inspection_used": inspection.inspection_used,
                "inspection_error": inspection.error,
                "plan_status": plan.get("plan_status"),
                "plan_can_attempt_automated_execution": plan.get("can_attempt_automated_execution"),
                "phase": "static_public_page_only",
            },
        }

        if isinstance(self._client, dict):
            now = _now()
            run_row = {"id": str(uuid4()), "created_at": now, "updated_at": now, **run_data}
            self._client.setdefault(_RUN_TABLE, {})[run_row["id"]] = run_row
            check_rows = self._persist_run_checks(str(run_row["id"]), checks)
            return _to_run_response(run_row, check_rows)

        result = self._client.table(_RUN_TABLE).insert(run_data).execute()
        run_rows = getattr(result, "data", []) or []
        if not run_rows:
            raise RuntimeError("Website verification run insert returned no data.")
        run_row = run_rows[0]
        check_rows = self._persist_run_checks(str(run_row["id"]), checks)
        return _to_run_response(run_row, check_rows)

    def _persist_run_checks(self, run_id: str, checks: list[_CheckResult]) -> list[dict[str, Any]]:
        check_data = [
            {
                "run_id": run_id,
                "check_key": check.check_key,
                "check_label": check.check_label,
                "check_type": check.check_type,
                "expected_value": check.expected_value,
                "observed_value": check.observed_value,
                "check_status": check.check_status,
                "check_summary": check.check_summary,
            }
            for check in checks
        ]
        if isinstance(self._client, dict):
            rows = []
            now = _now()
            for item in check_data:
                row = {"id": str(uuid4()), "created_at": now, **item}
                self._client.setdefault(_CHECK_TABLE, {})[row["id"]] = row
                rows.append(row)
            return rows

        result = self._client.table(_CHECK_TABLE).insert(check_data).execute()
        return getattr(result, "data", []) or []

    def _run_response_with_checks(self, row: dict[str, Any]) -> WebsiteVerificationRunResponse:
        if isinstance(self._client, dict):
            checks = [
                check
                for check in self._client.setdefault(_CHECK_TABLE, {}).values()
                if check.get("run_id") == row.get("id")
            ]
            checks.sort(key=lambda check: check.get("created_at", ""))
            return _to_run_response(row, checks)

        result = (
            self._client.table(_CHECK_TABLE)
            .select("*")
            .eq("run_id", row["id"])
            .order("created_at", desc=False)
            .execute()
        )
        return _to_run_response(row, getattr(result, "data", []) or [])

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

    def _get_plan_row(self, user_id: str, evidence_id: str, plan_id: str) -> dict[str, Any]:
        if isinstance(self._client, dict):
            row = self._client.setdefault(_PLAN_TABLE, {}).get(plan_id)
            if not row or row.get("user_id") != user_id or row.get("skill_evidence_id") != evidence_id:
                raise WebsiteVerificationPlanNotFoundError(plan_id)
            return row

        result = (
            self._client.table(_PLAN_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("skill_evidence_id", evidence_id)
            .eq("id", plan_id)
            .maybe_single()
            .execute()
        )
        if result is None or not result.data:
            raise WebsiteVerificationPlanNotFoundError(plan_id)
        return result.data

    def _get_latest_plan_row(self, user_id: str, evidence_id: str) -> dict[str, Any]:
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
            return rows[0]

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
        return rows[0]


def build_static_checks_from_plan(plan: dict[str, Any], inspection: WebsiteInspectionResult) -> list[_CheckResult]:
    checks: list[_CheckResult] = [
        _public_page_presence_check(inspection),
        _keyword_check(
            key="expected_output_keywords",
            label="Expected output keyword check",
            check_type="expected_output_keyword_check",
            source_text=plan.get("expected_output") or "",
            inspected_text=_inspection_text(inspection),
        ),
        _keyword_check(
            key="feature_keywords",
            label="Feature phrase check",
            check_type="static_text_presence",
            source_text=plan.get("feature_to_verify") or "",
            inspected_text=_inspection_text(inspection),
        ),
        _title_presence_check(plan, inspection),
        _heading_presence_check(plan, inspection),
    ]
    checks.extend(_browser_required_checks(plan, inspection))
    return checks


def run_static_checks(plan: dict[str, Any], website_inspection_result: WebsiteInspectionResult) -> list[_CheckResult]:
    return build_static_checks_from_plan(plan, website_inspection_result)


def determine_execution_status(
    check_results: list[_CheckResult],
    plan: dict[str, Any],
    inspection_result: WebsiteInspectionResult,
) -> str:
    if not inspection_result.inspection_used:
        return "execution_error" if inspection_result.error else "needs_review"
    if plan.get("plan_status") in {"needs_more_detail", "unsupported"}:
        return "needs_review"

    browser_required = any(check.check_status == "browser_required" for check in check_results)
    static_passes = sum(1 for check in check_results if check.check_status == "passed")
    static_failures = sum(1 for check in check_results if check.check_status == "failed")

    if browser_required:
        return "needs_browser_execution"
    if static_passes >= 4 and static_failures == 0:
        return "static_verified"
    if static_passes >= 2:
        return "partial_verification"
    if static_failures > 0:
        return "failed_static_checks"
    return "needs_review"


def summarize_execution(
    check_results: list[_CheckResult],
    status: str,
    plan: dict[str, Any],
    inspection_result: WebsiteInspectionResult,
) -> str:
    if status == "execution_error":
        return f"Static website inspection could not run safely: {inspection_result.error or 'unknown error'}."
    if status == "needs_browser_execution":
        return "Static checks found limited public-page signals, but this plan requires browser interaction or login to verify fully."
    if status == "static_verified":
        return "Static public-page checks strongly matched the website verification plan."
    if status == "partial_verification":
        return "Static public-page checks partially matched the website verification plan."
    if status == "failed_static_checks":
        return "Static public-page checks did not find enough matching evidence for the plan."
    return f"Run needs review before automated execution. Plan status: {plan.get('plan_status')}."


def _public_page_presence_check(inspection: WebsiteInspectionResult) -> _CheckResult:
    passed = inspection.inspection_used and (inspection.status_code or 0) < 400
    return _CheckResult(
        check_key="public_page_loaded",
        check_label="Public page loaded",
        check_type="static_text_presence",
        expected_value="Public HTML page loads successfully",
        observed_value=f"status={inspection.status_code}, url={inspection.final_url}",
        check_status="passed" if passed else "needs_review",
        check_summary="Website public HTML was inspected." if passed else f"Website inspection unavailable: {inspection.error or 'unknown error'}.",
    )


def _keyword_check(
    key: str,
    label: str,
    check_type: str,
    source_text: str,
    inspected_text: str,
) -> _CheckResult:
    keywords = _meaningful_keywords(source_text)
    hits = [keyword for keyword in keywords if keyword in inspected_text.lower()]
    if not keywords:
        status = "needs_review"
        summary = "No meaningful keywords could be derived for this check."
    elif hits:
        status = "passed"
        summary = f"Matched keywords: {', '.join(hits[:8])}."
    else:
        status = "failed"
        summary = "No derived keywords were found in static page content."
    return _CheckResult(
        check_key=key,
        check_label=label,
        check_type=check_type,
        expected_value=", ".join(keywords[:12]) if keywords else None,
        observed_value=", ".join(hits[:12]) if hits else None,
        check_status=status,
        check_summary=summary,
    )


def _title_presence_check(plan: dict[str, Any], inspection: WebsiteInspectionResult) -> _CheckResult:
    keywords = _meaningful_keywords(plan.get("feature_to_verify") or plan.get("expected_output") or "")
    title = (inspection.page_title or "").lower()
    hits = [keyword for keyword in keywords if keyword in title]
    return _CheckResult(
        check_key="title_presence",
        check_label="Static title presence",
        check_type="static_title_presence",
        expected_value=", ".join(keywords[:12]) if keywords else None,
        observed_value=inspection.page_title,
        check_status="passed" if hits else "failed",
        check_summary=f"Title matched keywords: {', '.join(hits[:8])}." if hits else "Page title did not match derived plan keywords.",
    )


def _heading_presence_check(plan: dict[str, Any], inspection: WebsiteInspectionResult) -> _CheckResult:
    keywords = _meaningful_keywords(plan.get("feature_to_verify") or plan.get("expected_output") or "")
    heading_text = " ".join(inspection.headings).lower()
    hits = [keyword for keyword in keywords if keyword in heading_text]
    return _CheckResult(
        check_key="heading_presence",
        check_label="Static heading presence",
        check_type="static_heading_presence",
        expected_value=", ".join(keywords[:12]) if keywords else None,
        observed_value=" | ".join(inspection.headings[:8]) if inspection.headings else None,
        check_status="passed" if hits else "failed",
        check_summary=f"Headings matched keywords: {', '.join(hits[:8])}." if hits else "Page headings did not match derived plan keywords.",
    )


def _browser_required_checks(plan: dict[str, Any], inspection: WebsiteInspectionResult) -> list[_CheckResult]:
    checks: list[_CheckResult] = []
    candidates = plan.get("inferred_action_candidates") or []
    dynamic_actions = [
        candidate.get("action_type")
        for candidate in candidates
        if candidate.get("action_type") in {"click", "input", "select"}
    ]
    if plan.get("requires_login"):
        checks.append(
            _CheckResult(
                check_key="login_required",
                check_label="Login required",
                check_type="manual/browser_required",
                expected_value="No private credentials used by static executor",
                observed_value="Plan requires login",
                check_status="browser_required",
                check_summary="Login-required flows need a future browser executor and safe demo access policy.",
            )
        )
    if dynamic_actions:
        checks.append(
            _CheckResult(
                check_key="dynamic_interaction_required",
                check_label="Dynamic browser interaction required",
                check_type="manual/browser_required",
                expected_value="Static executor does not click, type, select, or submit forms",
                observed_value=", ".join(sorted(set(dynamic_actions))),
                check_status="browser_required",
                check_summary="Plan includes actions that require browser automation in a later phase.",
            )
        )
    if "form" in inspection.public_markers or "interactive_controls" in inspection.public_markers:
        checks.append(
            _CheckResult(
                check_key="public_interactive_controls_present",
                check_label="Public interactive controls present",
                check_type="manual/browser_required",
                expected_value="Future browser executor can interact with public controls",
                observed_value=", ".join(inspection.public_markers),
                check_status="browser_required",
                check_summary="The static page exposes controls, but this phase does not interact with them.",
            )
        )
    return checks


def _check_counts(checks: list[_CheckResult]) -> dict[str, int]:
    return {
        "passed": sum(1 for check in checks if check.check_status == "passed"),
        "failed": sum(1 for check in checks if check.check_status == "failed"),
        "needs_review": sum(1 for check in checks if check.check_status in {"needs_review", "browser_required"}),
    }


def _inspection_text(inspection: WebsiteInspectionResult) -> str:
    return " ".join(
        [
            inspection.page_title or "",
            inspection.meta_description or "",
            " ".join(inspection.headings),
            inspection.visible_text or "",
        ]
    ).lower()


def _meaningful_keywords(value: str) -> list[str]:
    stopwords = {
        "after",
        "with",
        "that",
        "this",
        "from",
        "into",
        "appears",
        "shows",
        "show",
        "display",
        "displays",
        "page",
        "website",
        "user",
        "users",
        "input",
        "output",
        "card",
        "result",
        "results",
        "selecting",
        "selected",
    }
    tokens = re.findall(r"[a-z0-9]+", (value or "").lower())
    deduped: list[str] = []
    for token in tokens:
        if len(token) < 4 or token in stopwords:
            continue
        if token.endswith("ing") and len(token) > 6:
            token = token[:-3]
        if token.endswith("ed") and len(token) > 5:
            token = token[:-2]
        if token not in deduped:
            deduped.append(token)
    return deduped[:20]


def _excerpt(value: str | None) -> str | None:
    if not value:
        return None
    return value[:_TEXT_EXCERPT_CHARS]


def _to_run_response(row: dict[str, Any], checks: list[dict[str, Any]]) -> WebsiteVerificationRunResponse:
    return WebsiteVerificationRunResponse(
        id=str(row["id"]),
        evidence_id=str(row["evidence_id"]),
        plan_id=str(row["plan_id"]),
        user_id=str(row["user_id"]),
        execution_status=row["execution_status"],
        executor_version=row.get("executor_version") or _EXECUTOR_VERSION,
        execution_summary=row.get("execution_summary"),
        checks_attempted=int(row.get("checks_attempted") or 0),
        checks_passed=int(row.get("checks_passed") or 0),
        checks_failed=int(row.get("checks_failed") or 0),
        checks_needing_review=int(row.get("checks_needing_review") or 0),
        inspected_url=row.get("inspected_url"),
        inspected_title=row.get("inspected_title"),
        inspected_meta_description=row.get("inspected_meta_description"),
        inspected_headings=list(row.get("inspected_headings") or []),
        inspected_visible_text_excerpt=row.get("inspected_visible_text_excerpt"),
        raw_executor_notes=row.get("raw_executor_notes") or {},
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
        checks=[_to_check_response(check) for check in checks],
    )


def _to_check_response(row: dict[str, Any]) -> WebsiteVerificationRunCheckResponse:
    return WebsiteVerificationRunCheckResponse(
        id=str(row["id"]),
        run_id=str(row["run_id"]),
        check_key=row["check_key"],
        check_label=row["check_label"],
        check_type=row["check_type"],
        expected_value=row.get("expected_value"),
        observed_value=row.get("observed_value"),
        check_status=row["check_status"],
        check_summary=row.get("check_summary"),
        created_at=str(row.get("created_at") or ""),
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
