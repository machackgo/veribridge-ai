"""Safe browser website verification executor foundation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.schemas.website_browser_verification_run import (
    WebsiteBrowserVerificationRunResponse,
    WebsiteBrowserVerificationStepResponse,
)
from app.services.skill_evidence_service import SkillEvidenceNotFoundError
from app.services.website_public_inspection_service import _validate_public_url
from app.services.website_verification_guide_service import (
    WebsiteVerificationGuideNotAllowedError,
    _validate_website_evidence,
)
from app.services.website_verification_plan_service import WebsiteVerificationPlanNotFoundError

_EVIDENCE_TABLE = "skill_evidence"
_PLAN_TABLE = "website_verification_plans"
_RUN_TABLE = "website_browser_verification_runs"
_STEP_TABLE = "website_browser_verification_steps"
_EXECUTOR_VERSION = "website-browser-executor-v1"
_TEXT_SNAPSHOT_CHARS = 4000
_ACTION_TIMEOUT_MS = 5000
_NAVIGATION_TIMEOUT_MS = 15000
_TOTAL_STEP_LIMIT = 12

_LOGIN_TERMS = ("login", "log in", "sign in", "password", "auth", "otp", "2fa", "two-factor")
_SAFE_CLICK_TERMS = ("analyze", "generate", "calculate", "search", "run", "check", "view result", "view results", "next", "verify")
_UNSAFE_CLICK_TERMS = (
    "delete",
    "remove account",
    "purchase",
    "pay",
    "buy",
    "subscribe",
    "send message",
    "send email",
    "message recruiter",
    "confirm order",
    "confirm payment",
    "transfer",
    "submit application",
    "apply",
)
_SENSITIVE_FIELD_TERMS = (
    "password",
    "card",
    "credit",
    "cvv",
    "ssn",
    "social security",
    "secret",
    "token",
    "api key",
    "otp",
)


class WebsiteBrowserVerificationRunNotFoundError(LookupError):
    """No browser verification run exists for the scoped evidence row."""


class WebsiteBrowserExecutionTimeoutError(TimeoutError):
    """Browser execution exceeded a bounded timeout."""


class WebsiteBrowserExecutionError(RuntimeError):
    """Browser execution failed safely."""


@dataclass(frozen=True)
class _BrowserStep:
    step_index: int
    plan_step_key: str | None
    action_type: str
    action_target: str | None = None
    action_value: str | None = None
    expected_result: str | None = None


@dataclass(frozen=True)
class _ExecutedStep:
    step_index: int
    plan_step_key: str | None
    action_type: str
    action_target: str | None
    action_value: str | None
    expected_result: str | None
    observed_result: str | None
    step_status: str
    step_summary: str
    screenshot_storage_path: str | None = None


@dataclass(frozen=True)
class _BrowserPageState:
    inspected_url: str | None
    final_url: str | None
    page_title: str | None
    safe_text_snapshot: str | None
    browser_metadata: dict[str, Any]


@dataclass(frozen=True)
class _BrowserRunResult:
    steps: list[_ExecutedStep]
    page_state: _BrowserPageState
    error: str | None = None


class WebsiteBrowserAutomationAdapter:
    """Small Playwright boundary so tests can mock browser execution."""

    def run(self, website_url: str, steps: list[_BrowserStep]) -> _BrowserRunResult:
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise WebsiteBrowserExecutionError("python_playwright_not_installed") from exc

        executed: list[_ExecutedStep] = []
        final_url = website_url
        page_title: str | None = None
        safe_text_snapshot: str | None = None
        metadata: dict[str, Any] = {
            "adapter": "playwright_sync",
            "screenshots_persisted": False,
            "html_snapshots_persisted": False,
        }

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    context = browser.new_context(ignore_https_errors=False)
                    page = context.new_page()
                    page.set_default_timeout(_ACTION_TIMEOUT_MS)
                    page.set_default_navigation_timeout(_NAVIGATION_TIMEOUT_MS)
                    for step in steps:
                        executed.append(_execute_playwright_step(page, step))
                    final_url = page.url
                    page_title = page.title()
                    safe_text_snapshot = _excerpt(page.locator("body").inner_text(timeout=_ACTION_TIMEOUT_MS))
                    metadata["browser_closed_cleanly"] = True
                finally:
                    browser.close()
        except PlaywrightTimeoutError as exc:
            raise WebsiteBrowserExecutionTimeoutError("browser_execution_timeout") from exc
        except WebsiteBrowserExecutionTimeoutError:
            raise
        except Exception as exc:  # pragma: no cover - exercised through service fallback
            raise WebsiteBrowserExecutionError("browser_execution_error") from exc

        return _BrowserRunResult(
            steps=executed,
            page_state=_BrowserPageState(
                inspected_url=website_url,
                final_url=final_url,
                page_title=page_title,
                safe_text_snapshot=safe_text_snapshot,
                browser_metadata=metadata,
            ),
        )


class WebsiteBrowserVerificationExecutorService:
    def __init__(self, client: Any, browser_adapter: WebsiteBrowserAutomationAdapter | None = None) -> None:
        self._client = client
        self._browser_adapter = browser_adapter or WebsiteBrowserAutomationAdapter()

    def execute_latest_browser_verification_plan(self, user_id: str, evidence_id: str) -> WebsiteBrowserVerificationRunResponse:
        evidence = self._get_evidence_row(user_id, evidence_id)
        _validate_website_evidence(evidence)
        plan = self._get_latest_plan_row(user_id, evidence_id)
        return self.execute_browser_verification_plan(user_id, evidence_id, str(plan["id"]))

    def execute_browser_verification_plan(
        self,
        user_id: str,
        evidence_id: str,
        plan_id: str,
    ) -> WebsiteBrowserVerificationRunResponse:
        evidence = self._get_evidence_row(user_id, evidence_id)
        _validate_website_evidence(evidence)
        plan = self._get_plan_row(user_id, evidence_id, plan_id)
        status, reason = validate_plan_is_browser_executable(plan)
        if status:
            steps = _blocked_steps_for_plan(plan, status, reason)
            page_state = _empty_page_state(plan.get("website_url"), {"blocked_reason": reason})
            summary = summarize_browser_execution(steps, status, plan, page_state)
            return self._persist_browser_verification_run(user_id, evidence_id, plan, page_state, steps, status, summary)

        website_url, url_error = _validate_public_url(plan.get("website_url"))
        if url_error or not website_url:
            steps = [
                _ExecutedStep(
                    step_index=1,
                    plan_step_key="navigate",
                    action_type="navigate",
                    action_target=plan.get("website_url"),
                    action_value=None,
                    expected_result="Public website URL can be opened safely.",
                    observed_result=url_error,
                    step_status="failed",
                    step_summary=f"Website URL was rejected by public URL safety checks: {url_error}.",
                )
            ]
            page_state = _empty_page_state(plan.get("website_url"), {"url_error": url_error})
            summary = summarize_browser_execution(steps, "execution_error", plan, page_state)
            return self._persist_browser_verification_run(user_id, evidence_id, plan, page_state, steps, "execution_error", summary)

        safe_steps = translate_plan_to_safe_browser_steps(plan)
        if not safe_steps:
            steps = _blocked_steps_for_plan(plan, "unsupported_plan", "No safely executable browser steps could be derived from the plan.")
            page_state = _empty_page_state(website_url, {"blocked_reason": "no_safe_steps"})
            summary = summarize_browser_execution(steps, "unsupported_plan", plan, page_state)
            return self._persist_browser_verification_run(user_id, evidence_id, plan, page_state, steps, "unsupported_plan", summary)

        try:
            result = self._browser_adapter.run(website_url, safe_steps)
            steps = evaluate_browser_result(plan, result.steps, result.page_state)
            status = determine_browser_execution_status(steps, plan, result.page_state)
            summary = summarize_browser_execution(steps, status, plan, result.page_state)
            return self._persist_browser_verification_run(user_id, evidence_id, plan, result.page_state, steps, status, summary)
        except WebsiteBrowserExecutionTimeoutError:
            steps = _timeout_steps(safe_steps)
            page_state = _empty_page_state(website_url, {"browser_error": "browser_execution_timeout"})
            summary = summarize_browser_execution(steps, "execution_timeout", plan, page_state)
            return self._persist_browser_verification_run(user_id, evidence_id, plan, page_state, steps, "execution_timeout", summary)
        except WebsiteBrowserExecutionError as exc:
            steps = _error_steps(safe_steps, str(exc) or "browser_execution_error")
            page_state = _empty_page_state(website_url, {"browser_error": str(exc) or "browser_execution_error"})
            summary = summarize_browser_execution(steps, "execution_error", plan, page_state)
            return self._persist_browser_verification_run(user_id, evidence_id, plan, page_state, steps, "execution_error", summary)

    def list_runs(self, user_id: str, evidence_id: str) -> list[WebsiteBrowserVerificationRunResponse]:
        self._get_evidence_row(user_id, evidence_id)
        if isinstance(self._client, dict):
            rows = [
                row
                for row in self._client.setdefault(_RUN_TABLE, {}).values()
                if row.get("user_id") == user_id and row.get("evidence_id") == evidence_id
            ]
            rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
            return [self._run_response_with_steps(row) for row in rows]

        result = (
            self._client.table(_RUN_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("evidence_id", evidence_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [self._run_response_with_steps(row) for row in (getattr(result, "data", []) or [])]

    def get_latest_run(self, user_id: str, evidence_id: str) -> WebsiteBrowserVerificationRunResponse:
        self._get_evidence_row(user_id, evidence_id)
        runs = self.list_runs(user_id, evidence_id)
        if not runs:
            raise WebsiteBrowserVerificationRunNotFoundError(evidence_id)
        return runs[0]

    def get_run(self, user_id: str, evidence_id: str, run_id: str) -> WebsiteBrowserVerificationRunResponse:
        self._get_evidence_row(user_id, evidence_id)
        if isinstance(self._client, dict):
            row = self._client.setdefault(_RUN_TABLE, {}).get(run_id)
            if not row or row.get("user_id") != user_id or row.get("evidence_id") != evidence_id:
                raise WebsiteBrowserVerificationRunNotFoundError(run_id)
            return self._run_response_with_steps(row)

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
            raise WebsiteBrowserVerificationRunNotFoundError(run_id)
        return self._run_response_with_steps(result.data)

    def _persist_browser_verification_run(
        self,
        user_id: str,
        evidence_id: str,
        plan: dict[str, Any],
        page_state: _BrowserPageState,
        steps: list[_ExecutedStep],
        status: str,
        summary: str,
    ) -> WebsiteBrowserVerificationRunResponse:
        counts = _step_counts(steps)
        run_data = {
            "evidence_id": evidence_id,
            "plan_id": str(plan["id"]),
            "user_id": user_id,
            "browser_execution_status": status,
            "executor_version": _EXECUTOR_VERSION,
            "execution_summary": summary,
            "inspected_url": page_state.inspected_url,
            "final_url": page_state.final_url,
            "page_title": page_state.page_title,
            "screenshot_storage_path": None,
            "html_snapshot_storage_path": None,
            "safe_text_snapshot": page_state.safe_text_snapshot,
            "steps_attempted": len([step for step in steps if step.step_status not in {"skipped", "unsupported"}]),
            "steps_passed": counts["passed"],
            "steps_failed": counts["failed"],
            "steps_skipped": counts["skipped"],
            "steps_needing_review": counts["needs_review"],
            "browser_metadata": {
                **page_state.browser_metadata,
                "plan_status": plan.get("plan_status"),
                "requires_login": plan.get("requires_login"),
                "can_attempt_automated_execution": plan.get("can_attempt_automated_execution"),
                "executor_phase": "safe_browser_foundation",
            },
        }

        if isinstance(self._client, dict):
            now = _now()
            run_row = {"id": str(uuid4()), "created_at": now, "updated_at": now, **run_data}
            self._client.setdefault(_RUN_TABLE, {})[run_row["id"]] = run_row
            step_rows = self._persist_browser_verification_steps(str(run_row["id"]), steps)
            return _to_run_response(run_row, step_rows)

        result = self._client.table(_RUN_TABLE).insert(run_data).execute()
        run_rows = getattr(result, "data", []) or []
        if not run_rows:
            raise RuntimeError("Website browser verification run insert returned no data.")
        run_row = run_rows[0]
        step_rows = self._persist_browser_verification_steps(str(run_row["id"]), steps)
        return _to_run_response(run_row, step_rows)

    def _persist_browser_verification_steps(self, run_id: str, steps: list[_ExecutedStep]) -> list[dict[str, Any]]:
        step_data = [
            {
                "run_id": run_id,
                "step_index": step.step_index,
                "plan_step_key": step.plan_step_key,
                "action_type": step.action_type,
                "action_target": step.action_target,
                "action_value": step.action_value,
                "expected_result": step.expected_result,
                "observed_result": step.observed_result,
                "step_status": step.step_status,
                "step_summary": step.step_summary,
                "screenshot_storage_path": step.screenshot_storage_path,
            }
            for step in steps
        ]
        if isinstance(self._client, dict):
            rows = []
            now = _now()
            for item in step_data:
                row = {"id": str(uuid4()), "created_at": now, **item}
                self._client.setdefault(_STEP_TABLE, {})[row["id"]] = row
                rows.append(row)
            return rows

        result = self._client.table(_STEP_TABLE).insert(step_data).execute()
        return getattr(result, "data", []) or []

    def _run_response_with_steps(self, row: dict[str, Any]) -> WebsiteBrowserVerificationRunResponse:
        if isinstance(self._client, dict):
            steps = [
                step
                for step in self._client.setdefault(_STEP_TABLE, {}).values()
                if step.get("run_id") == row.get("id")
            ]
            steps.sort(key=lambda step: int(step.get("step_index") or 0))
            return _to_run_response(row, steps)

        result = (
            self._client.table(_STEP_TABLE)
            .select("*")
            .eq("run_id", row["id"])
            .order("step_index", desc=False)
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


def validate_plan_is_browser_executable(plan: dict[str, Any]) -> tuple[str | None, str | None]:
    combined = _combined_plan_text(plan)
    if plan.get("requires_login") or _contains_any(combined, _LOGIN_TERMS):
        return "blocked_by_login", "Plan or instructions require login/authentication, which Phase 5E does not support."
    if plan.get("plan_status") == "unsupported":
        return "unsupported_plan", "Plan contains unsupported instructions from the planning layer."
    if plan.get("plan_status") == "needs_more_detail" or not plan.get("can_attempt_automated_execution"):
        return "needs_human_review", "Plan is not detailed enough for safe automated browser execution."
    return None, None


def translate_plan_to_safe_browser_steps(plan: dict[str, Any]) -> list[_BrowserStep]:
    steps: list[_BrowserStep] = [
        _BrowserStep(
            step_index=1,
            plan_step_key="navigate",
            action_type="navigate",
            action_target=plan.get("website_url"),
            expected_result="Public website opens in a browser.",
        )
    ]
    candidates = plan.get("inferred_action_candidates") or []
    sample_inputs = _sample_input_map(plan.get("sample_inputs"))
    fill_index = 0

    for candidate in candidates:
        if len(steps) >= _TOTAL_STEP_LIMIT - 1:
            break
        action_type = candidate.get("action_type")
        instruction = str(candidate.get("instruction") or "")
        step_number = candidate.get("step_number")
        plan_step_key = f"plan_step_{step_number}" if step_number else None
        lower = instruction.lower()
        if action_type == "navigate":
            continue
        if action_type == "input":
            key, value = _input_for_instruction(instruction, sample_inputs, fill_index)
            fill_index += 1
            if not value or _contains_any(f"{key} {instruction}", _SENSITIVE_FIELD_TERMS):
                steps.append(_unsupported_browser_step(len(steps) + 1, plan_step_key, instruction, "Input step lacks a safe non-sensitive sample value."))
                continue
            steps.append(
                _BrowserStep(
                    step_index=len(steps) + 1,
                    plan_step_key=plan_step_key,
                    action_type="fill",
                    action_target=key or _field_hint_from_instruction(instruction),
                    action_value=value,
                    expected_result=instruction,
                )
            )
        elif action_type == "select":
            key, value = _input_for_instruction(instruction, sample_inputs, fill_index)
            fill_index += 1
            if not value or _contains_any(f"{key} {instruction}", _SENSITIVE_FIELD_TERMS):
                steps.append(_unsupported_browser_step(len(steps) + 1, plan_step_key, instruction, "Select step lacks a safe explicit sample value."))
                continue
            steps.append(
                _BrowserStep(
                    step_index=len(steps) + 1,
                    plan_step_key=plan_step_key,
                    action_type="select",
                    action_target=key or _field_hint_from_instruction(instruction),
                    action_value=value,
                    expected_result=instruction,
                )
            )
        elif action_type == "click":
            target = _click_target_from_instruction(instruction)
            if not is_safe_click_target(target or instruction):
                steps.append(_unsupported_browser_step(len(steps) + 1, plan_step_key, instruction, "Click target is unsafe or too ambiguous for Phase 5E."))
                continue
            steps.append(
                _BrowserStep(
                    step_index=len(steps) + 1,
                    plan_step_key=plan_step_key,
                    action_type="click",
                    action_target=target or instruction,
                    expected_result=instruction,
                )
            )
        elif action_type == "assert":
            steps.append(
                _BrowserStep(
                    step_index=len(steps) + 1,
                    plan_step_key=plan_step_key,
                    action_type="assert_text_present",
                    action_target=None,
                    expected_result=instruction,
                )
            )
        elif any(term in lower for term in ("wait for", "appears", "visible")):
            steps.append(
                _BrowserStep(
                    step_index=len(steps) + 1,
                    plan_step_key=plan_step_key,
                    action_type="wait_for_text",
                    expected_result=instruction,
                )
            )

    expected_output = str(plan.get("expected_output") or "").strip()
    if expected_output:
        steps.append(
            _BrowserStep(
                step_index=len(steps) + 1,
                plan_step_key="expected_output",
                action_type="assert_text_present",
                expected_result=expected_output,
            )
        )
    return steps


def run_browser_steps(browser_context: WebsiteBrowserAutomationAdapter, safe_steps: list[_BrowserStep], website_url: str) -> _BrowserRunResult:
    return browser_context.run(website_url, safe_steps)


def evaluate_browser_result(
    plan: dict[str, Any],
    executed_steps: list[_ExecutedStep],
    final_page_state: _BrowserPageState,
) -> list[_ExecutedStep]:
    text = f"{final_page_state.page_title or ''} {final_page_state.safe_text_snapshot or ''}".lower()
    expected_keywords = _meaningful_keywords(plan.get("expected_output") or "")
    expected_hits = [keyword for keyword in expected_keywords if keyword in text]
    evaluated = list(executed_steps)
    if expected_keywords and not any(step.plan_step_key == "expected_output" for step in evaluated):
        evaluated.append(
            _ExecutedStep(
                step_index=len(evaluated) + 1,
                plan_step_key="expected_output",
                action_type="assert_text_present",
                action_target=None,
                action_value=None,
                expected_result=", ".join(expected_keywords),
                observed_result=", ".join(expected_hits) if expected_hits else None,
                step_status="passed" if expected_hits else "failed",
                step_summary=(
                    f"Expected output keywords appeared on the final page: {', '.join(expected_hits[:8])}."
                    if expected_hits
                    else "Expected output keywords were not found in the final browser page state."
                ),
            )
        )
    return evaluated


def determine_browser_execution_status(
    executed_steps: list[_ExecutedStep],
    plan: dict[str, Any],
    final_page_state: _BrowserPageState,
) -> str:
    statuses = [step.step_status for step in executed_steps]
    if "blocked_by_login" in statuses:
        return "blocked_by_login"
    if "timeout" in statuses:
        return "execution_timeout"
    if all(status == "unsupported" for status in statuses):
        return "unsupported_plan"
    if not final_page_state.final_url:
        return "execution_error"

    passed = statuses.count("passed")
    failed = statuses.count("failed")
    review = sum(1 for status in statuses if status in {"needs_review", "unsupported", "skipped"})
    expected_step = next((step for step in executed_steps if step.plan_step_key == "expected_output"), None)

    if expected_step and expected_step.step_status == "passed" and failed == 0 and review == 0:
        return "browser_verified"
    if expected_step and expected_step.step_status == "passed" and passed >= 2:
        return "browser_partially_verified"
    if failed > 0 and passed >= 1:
        return "browser_failed"
    if review > 0:
        return "needs_human_review"
    return "browser_failed"


def summarize_browser_execution(
    executed_steps: list[_ExecutedStep],
    status: str,
    plan: dict[str, Any],
    final_page_state: _BrowserPageState,
) -> str:
    if status == "blocked_by_login":
        return "Browser verification was blocked because the plan or page requires login/authentication."
    if status == "unsupported_plan":
        return "Browser verification could not run because the plan cannot be translated into safe bounded browser actions."
    if status == "execution_timeout":
        return "Browser verification timed out within the bounded Phase 5E execution limits."
    if status == "execution_error":
        return "Browser verification failed safely before enough page state could be collected."
    if status == "browser_verified":
        return "Safe browser verification completed and expected output appeared on the final page."
    if status == "browser_partially_verified":
        return "Safe browser verification found some expected output, but the result remains partial."
    if status == "browser_failed":
        return "Safe browser steps ran, but expected output was not found in the final page state."
    warnings = ", ".join(plan.get("validation_warnings") or [])
    return f"Browser verification needs human review. Warnings: {warnings or 'inconclusive browser state'}."


def is_safe_click_target(text: str | None) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    if any(term in normalized for term in _UNSAFE_CLICK_TERMS):
        return False
    return any(term in normalized for term in _SAFE_CLICK_TERMS)


def _execute_playwright_step(page: Any, step: _BrowserStep) -> _ExecutedStep:
    try:
        if step.action_type == "navigate":
            page.goto(step.action_target, wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT_MS)
            return _passed_step(step, page.url, "Browser navigated to the public website.")
        if step.action_type == "fill":
            locator = _input_locator(page, step.action_target)
            locator.fill(step.action_value or "", timeout=_ACTION_TIMEOUT_MS)
            return _passed_step(step, step.action_target, "Safe sample value was entered into a public text input.")
        if step.action_type == "select":
            locator = _input_locator(page, step.action_target)
            locator.select_option(label=step.action_value, timeout=_ACTION_TIMEOUT_MS)
            return _passed_step(step, step.action_target, "Safe sample option was selected.")
        if step.action_type == "click":
            if not is_safe_click_target(step.action_target):
                return _unsupported_executed_step(step, "Click target failed safety review.")
            locator = page.get_by_role("button", name=re.compile(re.escape(step.action_target or ""), re.I)).first
            locator.click(timeout=_ACTION_TIMEOUT_MS)
            return _passed_step(step, step.action_target, "Safe button click completed.")
        if step.action_type in {"wait_for_text", "assert_text_present"}:
            keywords = _meaningful_keywords(step.expected_result or "")
            body = page.locator("body").inner_text(timeout=_ACTION_TIMEOUT_MS).lower()
            hits = [keyword for keyword in keywords if keyword in body]
            return _ExecutedStep(
                **_step_base(step),
                observed_result=", ".join(hits) if hits else None,
                step_status="passed" if hits else "failed",
                step_summary=(
                    f"Matched expected browser text keywords: {', '.join(hits[:8])}."
                    if hits
                    else "Expected browser text keywords were not visible."
                ),
            )
        return _unsupported_executed_step(step, f"Action type {step.action_type} is not implemented in Phase 5E.")
    except Exception as exc:
        return _ExecutedStep(
            **_step_base(step),
            observed_result=str(exc)[:300],
            step_status="failed",
            step_summary=f"Browser step failed safely: {type(exc).__name__}.",
        )


def _input_locator(page: Any, target: str | None) -> Any:
    if target:
        return page.get_by_label(re.compile(re.escape(target), re.I)).or_(page.get_by_placeholder(re.compile(re.escape(target), re.I))).first
    return page.locator("input:not([type=password]), textarea").first


def _blocked_steps_for_plan(plan: dict[str, Any], status: str, reason: str | None) -> list[_ExecutedStep]:
    step_status = "blocked_by_login" if status == "blocked_by_login" else "unsupported" if status == "unsupported_plan" else "needs_review"
    return [
        _ExecutedStep(
            step_index=1,
            plan_step_key="plan_validation",
            action_type="unsupported",
            action_target=None,
            action_value=None,
            expected_result="Plan can be translated into safe browser actions.",
            observed_result=reason,
            step_status=step_status,
            step_summary=reason or "Plan could not be executed safely.",
        )
    ]


def _timeout_steps(safe_steps: list[_BrowserStep]) -> list[_ExecutedStep]:
    if not safe_steps:
        safe_steps = [_BrowserStep(step_index=1, plan_step_key="browser_timeout", action_type="navigate")]
    return [
        _ExecutedStep(
            **_step_base(safe_steps[0]),
            observed_result="browser_execution_timeout",
            step_status="timeout",
            step_summary="Browser execution timed out and was stopped safely.",
        )
    ]


def _error_steps(safe_steps: list[_BrowserStep], error: str) -> list[_ExecutedStep]:
    if not safe_steps:
        safe_steps = [_BrowserStep(step_index=1, plan_step_key="browser_error", action_type="navigate")]
    return [
        _ExecutedStep(
            **_step_base(safe_steps[0]),
            observed_result=error,
            step_status="failed",
            step_summary="Browser execution failed safely.",
        )
    ]


def _unsupported_browser_step(step_index: int, plan_step_key: str | None, instruction: str, summary: str) -> _BrowserStep:
    return _BrowserStep(
        step_index=step_index,
        plan_step_key=plan_step_key,
        action_type="unsupported",
        action_target=instruction,
        expected_result=summary,
    )


def _unsupported_executed_step(step: _BrowserStep, summary: str) -> _ExecutedStep:
    return _ExecutedStep(
        **_step_base(step),
        observed_result=None,
        step_status="unsupported",
        step_summary=summary,
    )


def _passed_step(step: _BrowserStep, observed: str | None, summary: str) -> _ExecutedStep:
    return _ExecutedStep(
        **_step_base(step),
        observed_result=observed,
        step_status="passed",
        step_summary=summary,
    )


def _step_base(step: _BrowserStep) -> dict[str, Any]:
    return {
        "step_index": step.step_index,
        "plan_step_key": step.plan_step_key,
        "action_type": step.action_type,
        "action_target": step.action_target,
        "action_value": step.action_value,
        "expected_result": step.expected_result,
    }


def _empty_page_state(url: str | None, metadata: dict[str, Any] | None = None) -> _BrowserPageState:
    return _BrowserPageState(
        inspected_url=url,
        final_url=None,
        page_title=None,
        safe_text_snapshot=None,
        browser_metadata=metadata or {},
    )


def _sample_input_map(sample_inputs: Any) -> dict[str, str]:
    if isinstance(sample_inputs, dict):
        return {str(key).strip().lower(): str(value).strip() for key, value in sample_inputs.items() if str(value).strip()}
    if isinstance(sample_inputs, list):
        mapped: dict[str, str] = {}
        for index, item in enumerate(sample_inputs):
            if isinstance(item, dict):
                key = str(item.get("field") or item.get("name") or item.get("label") or f"input_{index}").strip().lower()
                value = str(item.get("value") or item.get("sample") or item.get("input") or "").strip()
                if value:
                    mapped[key] = value
        return mapped
    return {}


def _input_for_instruction(instruction: str, sample_inputs: dict[str, str], fallback_index: int) -> tuple[str | None, str | None]:
    lower = instruction.lower()
    for key, value in sample_inputs.items():
        if key in lower:
            return key, value
    items = list(sample_inputs.items())
    if fallback_index < len(items):
        return items[fallback_index]
    return _field_hint_from_instruction(instruction), _quoted_value(instruction)


def _field_hint_from_instruction(instruction: str) -> str | None:
    lower = instruction.lower()
    for phrase in ("source", "origin", "destination", "city", "route", "query", "search", "input"):
        if phrase in lower:
            return phrase
    match = re.search(r"(?:enter|type|fill|select|choose)\s+([a-z0-9 _-]{2,40})\s+(?:as|with|to)", lower)
    return match.group(1).strip() if match else None


def _quoted_value(instruction: str) -> str | None:
    match = re.search(r"['\"]([^'\"]{1,120})['\"]", instruction)
    if match:
        return match.group(1).strip()
    match = re.search(r"\bas\s+([^.,;]+)", instruction, flags=re.I)
    return match.group(1).strip() if match else None


def _click_target_from_instruction(instruction: str) -> str | None:
    match = re.search(r"(?:click|press|submit)\s+['\"]?([^'\".]+)['\"]?", instruction, flags=re.I)
    if not match:
        return None
    target = match.group(1).strip()
    target = re.sub(r"^(the|a|an)\s+", "", target, flags=re.I)
    return target[:80]


def _combined_plan_text(plan: dict[str, Any]) -> str:
    return " ".join(
        [
            str(plan.get("feature_to_verify") or ""),
            " ".join(str(step) for step in (plan.get("normalized_test_steps") or [])),
            str(plan.get("expected_output") or ""),
            str(plan.get("agent_notes") or ""),
        ]
    ).lower()


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    lower = value.lower()
    return any(needle in lower for needle in needles)


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
        "click",
        "enter",
        "type",
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


def _step_counts(steps: list[_ExecutedStep]) -> dict[str, int]:
    return {
        "passed": sum(1 for step in steps if step.step_status == "passed"),
        "failed": sum(1 for step in steps if step.step_status == "failed"),
        "skipped": sum(1 for step in steps if step.step_status in {"skipped", "unsupported"}),
        "needs_review": sum(1 for step in steps if step.step_status in {"needs_review", "blocked_by_login", "timeout"}),
    }


def _to_run_response(row: dict[str, Any], steps: list[dict[str, Any]]) -> WebsiteBrowserVerificationRunResponse:
    return WebsiteBrowserVerificationRunResponse(
        id=str(row["id"]),
        evidence_id=str(row["evidence_id"]),
        plan_id=str(row["plan_id"]),
        user_id=str(row["user_id"]),
        browser_execution_status=row["browser_execution_status"],
        executor_version=row.get("executor_version") or _EXECUTOR_VERSION,
        execution_summary=row.get("execution_summary"),
        inspected_url=row.get("inspected_url"),
        final_url=row.get("final_url"),
        page_title=row.get("page_title"),
        screenshot_storage_path=row.get("screenshot_storage_path"),
        html_snapshot_storage_path=row.get("html_snapshot_storage_path"),
        safe_text_snapshot=row.get("safe_text_snapshot"),
        steps_attempted=int(row.get("steps_attempted") or 0),
        steps_passed=int(row.get("steps_passed") or 0),
        steps_failed=int(row.get("steps_failed") or 0),
        steps_skipped=int(row.get("steps_skipped") or 0),
        steps_needing_review=int(row.get("steps_needing_review") or 0),
        browser_metadata=row.get("browser_metadata") or {},
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
        steps=[_to_step_response(step) for step in steps],
    )


def _to_step_response(row: dict[str, Any]) -> WebsiteBrowserVerificationStepResponse:
    return WebsiteBrowserVerificationStepResponse(
        id=str(row["id"]),
        run_id=str(row["run_id"]),
        step_index=int(row["step_index"]),
        plan_step_key=row.get("plan_step_key"),
        action_type=row["action_type"],
        action_target=row.get("action_target"),
        action_value=row.get("action_value"),
        expected_result=row.get("expected_result"),
        observed_result=row.get("observed_result"),
        step_status=row["step_status"],
        step_summary=row.get("step_summary"),
        screenshot_storage_path=row.get("screenshot_storage_path"),
        created_at=str(row.get("created_at") or ""),
    )


def _excerpt(value: str | None) -> str | None:
    if not value:
        return None
    return value[:_TEXT_SNAPSHOT_CHARS]


def _now() -> str:
    return datetime.now(UTC).isoformat()
