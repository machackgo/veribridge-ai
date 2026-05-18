"""Semantic website verification result service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.schemas.website_semantic_verification_result import WebsiteSemanticVerificationResultResponse
from app.services.skill_evidence_service import SkillEvidenceNotFoundError
from app.services.website_browser_verification_executor_service import WebsiteBrowserVerificationRunNotFoundError
from app.services.website_expected_output_match_service import (
    evaluate_expected_output_match,
    expected_output_match_to_snapshot,
)
from app.services.website_semantic_evaluator_provider import (
    DeterministicMockWebsiteSemanticEvaluator,
    WebsiteSemanticEvaluationResult,
    WebsiteSemanticEvaluatorProvider,
    build_evidence_summary,
    build_limitations,
    build_recommended_next_action,
    build_recruiter_facing_summary,
    calculate_confidence_score,
    determine_semantic_status,
)
from app.services.website_semantic_similarity_service import (
    SentenceEmbeddingProvider,
    evaluate_semantic_similarity,
    semantic_similarity_to_snapshot,
)
from app.services.website_verification_executor_service import WebsiteVerificationRunNotFoundError
from app.services.website_verification_guide_service import WebsiteVerificationGuideNotAllowedError, _validate_website_evidence
from app.services.website_verification_plan_service import WebsiteVerificationPlanNotFoundError

_EVIDENCE_TABLE = "skill_evidence"
_PLAN_TABLE = "website_verification_plans"
_STATIC_RUN_TABLE = "website_verification_runs"
_STATIC_CHECK_TABLE = "website_verification_run_checks"
_BROWSER_RUN_TABLE = "website_browser_verification_runs"
_BROWSER_STEP_TABLE = "website_browser_verification_steps"
_RESULT_TABLE = "website_semantic_verification_results"


class WebsiteSemanticVerificationResultNotFoundError(LookupError):
    """No semantic website verification result exists for the scoped evidence row."""


class WebsiteSemanticVerificationService:
    def __init__(
        self,
        client: Any,
        evaluator: WebsiteSemanticEvaluatorProvider | None = None,
        embedding_provider: SentenceEmbeddingProvider | None = None,
    ) -> None:
        self._client = client
        self._evaluator = evaluator or DeterministicMockWebsiteSemanticEvaluator()
        self._embedding_provider = embedding_provider

    def evaluate_latest_website_semantic_verification(self, user_id: str, evidence_id: str) -> WebsiteSemanticVerificationResultResponse:
        return self.evaluate_website_semantic_verification(user_id, evidence_id)

    def evaluate_website_semantic_verification(
        self,
        user_id: str,
        evidence_id: str,
        plan_id: str | None = None,
        static_run_id: str | None = None,
        browser_run_id: str | None = None,
    ) -> WebsiteSemanticVerificationResultResponse:
        context = self.load_evaluation_context(user_id, evidence_id, plan_id, static_run_id, browser_run_id)
        evaluation_input = self.build_semantic_evaluation_input(context)
        similarity = evaluate_semantic_similarity(evaluation_input, self._embedding_provider)
        context["semantic_similarity"] = semantic_similarity_to_snapshot(similarity)
        evaluation_input["semantic_similarity"] = semantic_similarity_to_snapshot(similarity)
        output_match = evaluate_expected_output_match(evaluation_input, self._embedding_provider)
        context["expected_output_match"] = expected_output_match_to_snapshot(output_match)
        evaluation_input["expected_output_match"] = expected_output_match_to_snapshot(output_match)
        try:
            evaluation = self.evaluate_semantically(evaluation_input)
        except Exception:
            evaluation = WebsiteSemanticEvaluationResult(
                semantic_status="evaluation_error",
                confidence_score=0.0,
                recruiter_facing_summary="VeriBridge could not complete semantic evaluation because of an internal evaluation error.",
                evidence_summary=build_evidence_summary(evaluation_input),
                limitations=build_limitations(evaluation_input, "evaluation_error"),
                recommended_next_action="Retry semantic evaluation after checking service health.",
                internal_reasoning_summary="Semantic evaluator raised an internal runtime error.",
                evaluator_provider=getattr(self._evaluator, "evaluator_provider", "unknown"),
                evaluator_version=getattr(self._evaluator, "evaluator_version", "unknown"),
            )
        return self.persist_semantic_verification_result(user_id, evidence_id, context, evaluation)

    def load_evaluation_context(
        self,
        user_id: str,
        evidence_id: str,
        plan_id: str | None = None,
        static_run_id: str | None = None,
        browser_run_id: str | None = None,
    ) -> dict[str, Any]:
        evidence = self._get_evidence_row(user_id, evidence_id)
        _validate_website_evidence(evidence)
        plan = self._get_plan_row(user_id, evidence_id, plan_id) if plan_id else self._get_latest_plan_row(user_id, evidence_id)
        static_run = self._get_static_run_row(user_id, evidence_id, str(plan["id"]), static_run_id) if static_run_id else self._get_latest_static_run_row(user_id, evidence_id, str(plan["id"]))
        browser_run = (
            self._get_browser_run_row(user_id, evidence_id, str(plan["id"]), browser_run_id)
            if browser_run_id
            else self._get_latest_browser_run_row(user_id, evidence_id, str(plan["id"]))
        )
        return {
            "evidence": evidence,
            "plan": plan,
            "static_run": static_run,
            "static_checks": self._get_static_checks(str(static_run["id"])) if static_run else [],
            "browser_run": browser_run,
            "browser_steps": self._get_browser_steps(str(browser_run["id"])) if browser_run else [],
        }

    def build_semantic_evaluation_input(self, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "evidence": _compact_evidence(context.get("evidence") or {}),
            "plan": _compact_plan(context.get("plan") or {}),
            "static_run": _compact_static_run(context.get("static_run")),
            "static_checks": [_compact_static_check(check) for check in (context.get("static_checks") or [])[:20]],
            "browser_run": _compact_browser_run(context.get("browser_run")),
            "browser_steps": [_compact_browser_step(step) for step in (context.get("browser_steps") or [])[:20]],
            "semantic_similarity": context.get("semantic_similarity"),
            "expected_output_match": context.get("expected_output_match"),
        }

    def evaluate_semantically(self, context: dict[str, Any]) -> WebsiteSemanticEvaluationResult:
        return self._evaluator.evaluate(context)

    def determine_semantic_status(self, context: dict[str, Any]) -> str:
        return determine_semantic_status(context)

    def calculate_confidence_score(self, context: dict[str, Any]) -> float:
        return calculate_confidence_score(context)

    def build_recruiter_facing_summary(self, context: dict[str, Any], status: str) -> str:
        return build_recruiter_facing_summary(context, status)

    def build_evidence_summary(self, context: dict[str, Any]) -> str:
        return build_evidence_summary(context)

    def build_limitations(self, context: dict[str, Any], status: str) -> str:
        return build_limitations(context, status)

    def build_recommended_next_action(self, context: dict[str, Any], status: str) -> str:
        return build_recommended_next_action(context, status)

    def persist_semantic_verification_result(
        self,
        user_id: str,
        evidence_id: str,
        context: dict[str, Any],
        evaluation: WebsiteSemanticEvaluationResult,
    ) -> WebsiteSemanticVerificationResultResponse:
        plan = context["plan"]
        static_run = context.get("static_run")
        browser_run = context.get("browser_run")
        data = {
            "evidence_id": evidence_id,
            "plan_id": str(plan["id"]),
            "static_run_id": str(static_run["id"]) if static_run else None,
            "browser_run_id": str(browser_run["id"]) if browser_run else None,
            "user_id": user_id,
            "semantic_status": evaluation.semantic_status,
            "confidence_score": evaluation.confidence_score,
            "evaluator_version": evaluation.evaluator_version,
            "evaluator_provider": evaluation.evaluator_provider,
            "internal_reasoning_summary": evaluation.internal_reasoning_summary,
            "recruiter_facing_summary": evaluation.recruiter_facing_summary,
            "evidence_summary": evaluation.evidence_summary,
            "limitations": evaluation.limitations,
            "recommended_next_action": evaluation.recommended_next_action,
            "source_snapshot": self._source_snapshot(context),
        }

        if isinstance(self._client, dict):
            now = _now()
            row = {"id": str(uuid4()), "created_at": now, "updated_at": now, **data}
            self._client.setdefault(_RESULT_TABLE, {})[row["id"]] = row
            return _to_response(row)

        result = self._client.table(_RESULT_TABLE).insert(data).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError("Website semantic verification result insert returned no data.")
        return _to_response(rows[0])

    def get_latest_result(self, user_id: str, evidence_id: str) -> WebsiteSemanticVerificationResultResponse:
        self._get_evidence_row(user_id, evidence_id)
        results = self.list_results(user_id, evidence_id)
        if not results:
            raise WebsiteSemanticVerificationResultNotFoundError(evidence_id)
        return results[0]

    def list_results(self, user_id: str, evidence_id: str) -> list[WebsiteSemanticVerificationResultResponse]:
        self._get_evidence_row(user_id, evidence_id)
        if isinstance(self._client, dict):
            rows = [
                row
                for row in self._client.setdefault(_RESULT_TABLE, {}).values()
                if row.get("user_id") == user_id and row.get("evidence_id") == evidence_id
            ]
            rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
            return [_to_response(row) for row in rows]

        result = (
            self._client.table(_RESULT_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("evidence_id", evidence_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [_to_response(row) for row in (getattr(result, "data", []) or [])]

    def get_result(self, user_id: str, evidence_id: str, result_id: str) -> WebsiteSemanticVerificationResultResponse:
        self._get_evidence_row(user_id, evidence_id)
        if isinstance(self._client, dict):
            row = self._client.setdefault(_RESULT_TABLE, {}).get(result_id)
            if not row or row.get("user_id") != user_id or row.get("evidence_id") != evidence_id:
                raise WebsiteSemanticVerificationResultNotFoundError(result_id)
            return _to_response(row)

        result = (
            self._client.table(_RESULT_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("evidence_id", evidence_id)
            .eq("id", result_id)
            .maybe_single()
            .execute()
        )
        if result is None or not result.data:
            raise WebsiteSemanticVerificationResultNotFoundError(result_id)
        return _to_response(result.data)

    def _source_snapshot(self, context: dict[str, Any]) -> dict[str, Any]:
        compact = self.build_semantic_evaluation_input(context)
        static_run = compact.get("static_run") or {}
        browser_run = compact.get("browser_run") or {}
        similarity = semantic_similarity_to_snapshot(compact.get("semantic_similarity"))
        output_match = expected_output_match_to_snapshot(compact.get("expected_output_match"))
        return {
            "plan": {
                "id": compact["plan"].get("id"),
                "plan_status": compact["plan"].get("plan_status"),
                "requires_login": compact["plan"].get("requires_login"),
                "can_attempt_automated_execution": compact["plan"].get("can_attempt_automated_execution"),
                "validation_warnings": compact["plan"].get("validation_warnings"),
            },
            "static_run": {
                "id": static_run.get("id"),
                "execution_status": static_run.get("execution_status"),
                "checks_attempted": static_run.get("checks_attempted"),
                "checks_passed": static_run.get("checks_passed"),
                "checks_failed": static_run.get("checks_failed"),
                "checks_needing_review": static_run.get("checks_needing_review"),
            },
            "browser_run": {
                "id": browser_run.get("id"),
                "browser_execution_status": browser_run.get("browser_execution_status"),
                "steps_attempted": browser_run.get("steps_attempted"),
                "steps_passed": browser_run.get("steps_passed"),
                "steps_failed": browser_run.get("steps_failed"),
                "steps_needing_review": browser_run.get("steps_needing_review"),
                "final_url": browser_run.get("final_url"),
                "page_title": browser_run.get("page_title"),
                "safe_text_snapshot_excerpt": _excerpt(browser_run.get("safe_text_snapshot"), 500),
            },
            "key_outputs": {
                "static_check_summaries": [check.get("check_summary") for check in compact.get("static_checks", [])[:6]],
                "browser_step_summaries": [step.get("step_summary") for step in compact.get("browser_steps", [])[:8]],
            },
            "semantic_similarity": similarity,
            "semantic_similarity_claim_bundle_preview": similarity.get("claim_bundle_preview"),
            "semantic_similarity_observed_bundle_preview": similarity.get("observed_bundle_preview"),
            "semantic_similarity_claim_bundle_source_fields": similarity.get("claim_bundle_source_fields") or [],
            "semantic_similarity_observed_bundle_source_fields": similarity.get("observed_bundle_source_fields") or [],
            "semantic_similarity_score": similarity.get("score"),
            "semantic_similarity_label": similarity.get("label"),
            "semantic_similarity_model": similarity.get("model"),
            "semantic_similarity_method": similarity.get("method"),
            "semantic_similarity_available": similarity.get("available"),
            "expected_output_match": output_match,
        }

    def _get_evidence_row(self, user_id: str, evidence_id: str) -> dict[str, Any]:
        if isinstance(self._client, dict):
            row = self._client.setdefault(_EVIDENCE_TABLE, {}).get(evidence_id)
            if not row or row.get("user_id") != user_id:
                raise SkillEvidenceNotFoundError(evidence_id)
            return row
        result = self._client.table(_EVIDENCE_TABLE).select("*").eq("user_id", user_id).eq("id", evidence_id).maybe_single().execute()
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

    def _get_static_run_row(self, user_id: str, evidence_id: str, plan_id: str, run_id: str) -> dict[str, Any]:
        if isinstance(self._client, dict):
            row = self._client.setdefault(_STATIC_RUN_TABLE, {}).get(run_id)
            if not row or row.get("user_id") != user_id or row.get("evidence_id") != evidence_id or row.get("plan_id") != plan_id:
                raise WebsiteVerificationRunNotFoundError(run_id)
            return row
        result = (
            self._client.table(_STATIC_RUN_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("evidence_id", evidence_id)
            .eq("plan_id", plan_id)
            .eq("id", run_id)
            .maybe_single()
            .execute()
        )
        if result is None or not result.data:
            raise WebsiteVerificationRunNotFoundError(run_id)
        return result.data

    def _get_latest_static_run_row(self, user_id: str, evidence_id: str, plan_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            rows = [
                row
                for row in self._client.setdefault(_STATIC_RUN_TABLE, {}).values()
                if row.get("user_id") == user_id and row.get("evidence_id") == evidence_id and row.get("plan_id") == plan_id
            ]
            rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
            return rows[0] if rows else None
        result = (
            self._client.table(_STATIC_RUN_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("evidence_id", evidence_id)
            .eq("plan_id", plan_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _get_browser_run_row(self, user_id: str, evidence_id: str, plan_id: str, run_id: str) -> dict[str, Any]:
        if isinstance(self._client, dict):
            row = self._client.setdefault(_BROWSER_RUN_TABLE, {}).get(run_id)
            if not row or row.get("user_id") != user_id or row.get("evidence_id") != evidence_id or row.get("plan_id") != plan_id:
                raise WebsiteBrowserVerificationRunNotFoundError(run_id)
            return row
        result = (
            self._client.table(_BROWSER_RUN_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("evidence_id", evidence_id)
            .eq("plan_id", plan_id)
            .eq("id", run_id)
            .maybe_single()
            .execute()
        )
        if result is None or not result.data:
            raise WebsiteBrowserVerificationRunNotFoundError(run_id)
        return result.data

    def _get_latest_browser_run_row(self, user_id: str, evidence_id: str, plan_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            rows = [
                row
                for row in self._client.setdefault(_BROWSER_RUN_TABLE, {}).values()
                if row.get("user_id") == user_id and row.get("evidence_id") == evidence_id and row.get("plan_id") == plan_id
            ]
            rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
            return rows[0] if rows else None
        result = (
            self._client.table(_BROWSER_RUN_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("evidence_id", evidence_id)
            .eq("plan_id", plan_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _get_static_checks(self, run_id: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            rows = [row for row in self._client.setdefault(_STATIC_CHECK_TABLE, {}).values() if row.get("run_id") == run_id]
            rows.sort(key=lambda row: row.get("created_at", ""))
            return rows
        result = self._client.table(_STATIC_CHECK_TABLE).select("*").eq("run_id", run_id).order("created_at", desc=False).execute()
        return getattr(result, "data", []) or []

    def _get_browser_steps(self, run_id: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            rows = [row for row in self._client.setdefault(_BROWSER_STEP_TABLE, {}).values() if row.get("run_id") == run_id]
            rows.sort(key=lambda row: int(row.get("step_index") or 0))
            return rows
        result = self._client.table(_BROWSER_STEP_TABLE).select("*").eq("run_id", run_id).order("step_index", desc=False).execute()
        return getattr(result, "data", []) or []


def _compact_evidence(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id")),
        "skill_name": row.get("skill_name"),
        "evidence_type": row.get("evidence_type"),
        "evidence_url": row.get("evidence_url"),
        "evidence_description": row.get("evidence_description"),
    }


def _compact_plan(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id")),
        "website_url": row.get("website_url"),
        "feature_to_verify": row.get("feature_to_verify"),
        "plan_status": row.get("plan_status"),
        "normalized_test_steps": list(row.get("normalized_test_steps") or []),
        "expected_output": row.get("expected_output"),
        "sample_inputs": row.get("sample_inputs"),
        "validation_warnings": list(row.get("validation_warnings") or []),
        "requires_login": bool(row.get("requires_login")),
        "can_attempt_automated_execution": bool(row.get("can_attempt_automated_execution")),
    }


def _compact_static_run(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": str(row.get("id")),
        "execution_status": row.get("execution_status"),
        "execution_summary": row.get("execution_summary"),
        "checks_attempted": int(row.get("checks_attempted") or 0),
        "checks_passed": int(row.get("checks_passed") or 0),
        "checks_failed": int(row.get("checks_failed") or 0),
        "checks_needing_review": int(row.get("checks_needing_review") or 0),
    }


def _compact_static_check(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "check_key": row.get("check_key"),
        "check_status": row.get("check_status"),
        "observed_value": _excerpt(row.get("observed_value"), 300),
        "check_summary": _excerpt(row.get("check_summary"), 300),
    }


def _compact_browser_run(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": str(row.get("id")),
        "browser_execution_status": row.get("browser_execution_status"),
        "execution_summary": row.get("execution_summary"),
        "steps_attempted": int(row.get("steps_attempted") or 0),
        "steps_passed": int(row.get("steps_passed") or 0),
        "steps_failed": int(row.get("steps_failed") or 0),
        "steps_skipped": int(row.get("steps_skipped") or 0),
        "steps_needing_review": int(row.get("steps_needing_review") or 0),
        "final_url": row.get("final_url"),
        "page_title": row.get("page_title"),
        "safe_text_snapshot": _excerpt(row.get("safe_text_snapshot"), 1200),
    }


def _compact_browser_step(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "step_index": int(row.get("step_index") or 0),
        "plan_step_key": row.get("plan_step_key"),
        "action_type": row.get("action_type"),
        "expected_result": _excerpt(row.get("expected_result"), 300),
        "observed_result": _excerpt(row.get("observed_result"), 300),
        "step_status": row.get("step_status"),
        "step_summary": _excerpt(row.get("step_summary"), 300),
    }


def _to_response(row: dict[str, Any]) -> WebsiteSemanticVerificationResultResponse:
    return WebsiteSemanticVerificationResultResponse(
        id=str(row["id"]),
        evidence_id=str(row["evidence_id"]),
        plan_id=str(row["plan_id"]),
        static_run_id=str(row["static_run_id"]) if row.get("static_run_id") else None,
        browser_run_id=str(row["browser_run_id"]) if row.get("browser_run_id") else None,
        user_id=str(row["user_id"]),
        semantic_status=row["semantic_status"],
        confidence_score=float(row["confidence_score"]) if row.get("confidence_score") is not None else None,
        evaluator_version=row.get("evaluator_version") or "website-semantic-evaluator-mock-v1",
        evaluator_provider=row.get("evaluator_provider") or "deterministic_mock",
        recruiter_facing_summary=row.get("recruiter_facing_summary"),
        evidence_summary=row.get("evidence_summary"),
        limitations=row.get("limitations"),
        recommended_next_action=row.get("recommended_next_action"),
        semantic_similarity=semantic_similarity_to_snapshot((row.get("source_snapshot") or {}).get("semantic_similarity")),
        source_snapshot=row.get("source_snapshot") or {},
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


def _excerpt(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:limit]


def _now() -> str:
    return datetime.now(UTC).isoformat()
