"""Tests for local website semantic similarity."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.website_semantic_similarity_service import (
    SemanticSimilarityResult,
    build_claim_semantic_bundle,
    build_claim_text,
    build_observed_semantic_bundle,
    build_observed_text,
    claim_bundle_source_fields,
    compact_semantic_fragments,
    compute_embedding_similarity,
    evaluate_semantic_similarity,
    observed_bundle_source_fields,
    normalize_semantic_text,
    semantic_similarity_label,
)

USER_ID = "00000000-0000-0000-0000-000000000001"


class _FakeEmbeddingProvider:
    model_name = "fake-local-embedding-model"

    def __init__(self, vectors: list[list[float]]) -> None:
        self._vectors = vectors

    def encode(self, texts: list[str]) -> list[list[float]]:
        assert len(texts) == 2
        return self._vectors


class _UnavailableEmbeddingProvider:
    model_name = "unavailable-model"

    def encode(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("model unavailable")


class _RecordingEmbeddingProvider:
    model_name = "recording-provider"

    def __init__(self) -> None:
        self.texts: list[str] = []

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.texts = texts
        return [[1.0, 0.0], [0.9, 0.1]]


def _context(observed: str = "Alternative low-risk path available.") -> dict:
    return {
        "evidence": {
            "skill_name": "FastAPI",
            "evidence_description": "This public website predicts accident risk after route inputs are entered and recommends a safer route.",
        },
        "plan": {
            "feature_to_verify": "analyzes route accident risk after a user enters source and destination locations, then recommends a safer alternative route",
            "expected_output": "A route risk score and safer route recommendation appear.",
            "normalized_test_steps": ["Open website", "Analyze route", "Confirm safer route recommendation"],
            "sample_inputs": {"source": "Boston", "destination": "Cambridge"},
            "validation_warnings": [],
        },
        "static_run": {
            "execution_status": "partial_verification",
            "execution_summary": "Static checks found route risk language.",
            "checks_attempted": 4,
            "checks_passed": 2,
        },
        "static_checks": [
            {
                "check_status": "passed",
                "observed_value": "route risk",
                "check_summary": "Matched route risk language.",
            }
        ],
        "browser_run": {
            "browser_execution_status": "browser_partially_verified",
            "execution_summary": "Browser run reached route result page.",
            "page_title": "Route Analyzer",
            "safe_text_snapshot": observed,
            "steps_attempted": 4,
            "steps_passed": 2,
        },
        "browser_steps": [
            {
                "step_status": "passed",
                "observed_result": observed,
                "step_summary": "Observed route recommendation text.",
            }
        ],
    }


def _context_with_status(browser_status: str, observed: str = "Alternative low-risk path available.") -> dict:
    context = _context(observed)
    context["browser_run"]["browser_execution_status"] = browser_status
    if browser_status == "browser_failed":
        context["browser_run"]["execution_summary"] = "Browser run could not reach the route result page."
        context["browser_run"]["safe_text_snapshot"] = "Welcome page and contact links."
        context["browser_steps"] = [
            {
                "step_status": "failed",
                "observed_result": "No route recommendation appeared.",
                "step_summary": "The route analysis action did not produce the expected output.",
            }
        ]
    if browser_status == "blocked_by_login":
        context["browser_run"]["execution_summary"] = "Browser run stopped at a login screen."
        context["browser_run"]["safe_text_snapshot"] = "Sign in to continue."
        context["browser_steps"] = [
            {
                "step_status": "needs_human_review",
                "observed_result": "Login was required before route analysis could run.",
                "step_summary": "The verification flow was blocked by authentication.",
            }
        ]
    return context


def _client(store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: store
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _seed_semantic_endpoint_context(store: dict, browser_status: str = "browser_partially_verified", static_status: str = "partial_verification") -> dict:
    evidence = {
        "id": str(uuid4()),
        "user_id": USER_ID,
        "skill_name": "FastAPI",
        "evidence_type": "Deployed website URL",
        "evidence_url": "https://student-demo.example.com",
        "proof_visibility": "public",
        "evidence_description": "This website recommends a safer route.",
        "metadata": {},
        "created_at": _now(),
        "updated_at": _now(),
    }
    plan = {
        "id": str(uuid4()),
        "user_id": USER_ID,
        "skill_evidence_id": evidence["id"],
        "website_url": evidence["evidence_url"],
        "feature_to_verify": "Safer route recommendation",
        "plan_status": "ready",
        "normalized_test_steps": ["Open the website.", "Analyze a route.", "Confirm safer route output."],
        "expected_output": "This website recommends a safer route.",
        "sample_inputs": {},
        "inferred_action_candidates": [],
        "validation_warnings": [],
        "requires_login": False,
        "can_attempt_automated_execution": True,
        "planner_version": "website-plan-v1",
        "guide_snapshot": {},
        "created_at": _now(),
    }
    static_run = {
        "id": str(uuid4()),
        "evidence_id": evidence["id"],
        "plan_id": plan["id"],
        "user_id": USER_ID,
        "execution_status": static_status,
        "executor_version": "website-executor-static-v1",
        "execution_summary": "Static checks found some route language.",
        "checks_attempted": 4,
        "checks_passed": 2 if static_status != "failed_static_checks" else 0,
        "checks_failed": 2 if static_status == "failed_static_checks" else 1,
        "checks_needing_review": 1,
        "created_at": _now(),
        "updated_at": _now(),
    }
    browser_run = {
        "id": str(uuid4()),
        "evidence_id": evidence["id"],
        "plan_id": plan["id"],
        "user_id": USER_ID,
        "browser_execution_status": browser_status,
        "executor_version": "website-browser-executor-v1",
        "execution_summary": "Browser run reached the route output page.",
        "inspected_url": evidence["evidence_url"],
        "final_url": evidence["evidence_url"],
        "page_title": "Route Analyzer",
        "safe_text_snapshot": "Alternative low-risk path available." if browser_status != "browser_failed" else "Portfolio and contact links.",
        "steps_attempted": 4,
        "steps_passed": 2 if browser_status != "browser_failed" else 1,
        "steps_failed": 1 if browser_status == "browser_failed" else 0,
        "steps_skipped": 0,
        "steps_needing_review": 1 if browser_status == "needs_human_review" else 0,
        "browser_metadata": {},
        "created_at": _now(),
        "updated_at": _now(),
    }
    store.setdefault("skill_evidence", {})[evidence["id"]] = evidence
    store.setdefault("website_verification_plans", {})[plan["id"]] = plan
    store.setdefault("website_verification_runs", {})[static_run["id"]] = static_run
    store.setdefault("website_browser_verification_runs", {})[browser_run["id"]] = browser_run
    return evidence


def test_normalize_text_works() -> None:
    assert normalize_semantic_text("  This   website\n\nrecommends\t a route.  ") == "This website recommends a route."


def test_claim_text_builder_creates_useful_text() -> None:
    claim = build_claim_text(_context())

    assert "predicts accident risk" in claim
    assert "recommends a safer route" in claim


def test_claim_semantic_bundle_includes_feature_expected_output_and_steps() -> None:
    claim = build_claim_semantic_bundle(_context())

    assert "The student claims" in claim
    assert "source and destination" in claim
    assert "expected visible outcome" in claim
    assert "risk score" in claim
    assert "intended verification flow" in claim
    assert "Open website" in claim


def test_observed_text_builder_creates_useful_text() -> None:
    observed = build_observed_text(_context())

    assert "Alternative low-risk path available" in observed
    assert "route result page" in observed


def test_observed_semantic_bundle_includes_summary_status_and_visible_output() -> None:
    observed = build_observed_semantic_bundle(_context())

    assert "completed part of the browser flow" in observed
    assert "Browser execution summary" in observed
    assert "Alternative low-risk path available" in observed
    assert "Static verification status was partial_verification" in observed


def test_failed_browser_bundle_does_not_use_success_wording() -> None:
    observed = build_observed_semantic_bundle(_context_with_status("browser_failed"))

    assert "attempted the browser flow but did not observe the expected result" in observed
    assert "successfully completed the browser flow" not in observed


def test_blocked_by_login_bundle_reflects_blocked_state() -> None:
    observed = build_observed_semantic_bundle(_context_with_status("blocked_by_login"))

    assert "required login" in observed
    assert "Sign in to continue" in observed


def test_missing_browser_bundle_falls_back_to_static_evidence() -> None:
    context = _context()
    context["browser_run"] = None
    context["browser_steps"] = []

    observed = build_observed_semantic_bundle(context)

    assert "No browser execution result was available" in observed
    assert "Static verification status was partial_verification" in observed
    assert "route risk language" in observed


def test_semantic_bundles_are_compact_and_length_capped() -> None:
    text = compact_semantic_fragments(["same text", "same text", "x" * 2000], max_chars=120)

    assert len(text) <= 120
    assert text.count("same text") == 1


def test_source_field_provenance_is_reported() -> None:
    context = _context()

    assert claim_bundle_source_fields(context) == [
        "skill_evidence.description",
        "plan.feature_to_verify",
        "plan.expected_output",
        "plan.normalized_test_steps",
        "plan.sample_inputs",
    ]
    observed_fields = observed_bundle_source_fields(context)
    assert "browser_run.execution_summary" in observed_fields
    assert "browser_run.safe_text_snapshot" in observed_fields
    assert "static_run.execution_summary" in observed_fields


def test_similarity_evaluation_uses_richer_bundles() -> None:
    provider = _RecordingEmbeddingProvider()
    result = evaluate_semantic_similarity(_context(), provider)

    assert result.available is True
    assert len(provider.texts) == 2
    assert "The student claims" in provider.texts[0]
    assert "The expected visible outcome" in provider.texts[0]
    assert "VeriBridge completed part of the browser flow" in provider.texts[1]
    assert "The observed page/output included" in provider.texts[1]
    assert result.claim_bundle_source_fields
    assert result.observed_bundle_source_fields


def test_mocked_embedding_provider_returns_high_similarity_for_paraphrase() -> None:
    score = compute_embedding_similarity(
        "This website recommends a safer route.",
        "Alternative low-risk path available.",
        _FakeEmbeddingProvider([[1.0, 0.0, 0.0], [0.9, 0.1, 0.0]]),
    )

    assert score is not None
    assert score >= 0.82


def test_mocked_embedding_provider_returns_low_similarity_for_unrelated_texts() -> None:
    score = compute_embedding_similarity(
        "This website recommends a safer route.",
        "The page contains a biography and contact form.",
        _FakeEmbeddingProvider([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
    )

    assert score == 0.0


def test_score_thresholds_map_to_labels() -> None:
    assert semantic_similarity_label(0.90) == "strong_semantic_match"
    assert semantic_similarity_label(0.75) == "moderate_semantic_match"
    assert semantic_similarity_label(0.60) == "weak_semantic_match"
    assert semantic_similarity_label(0.30) == "low_semantic_match"


def test_provider_unavailable_returns_graceful_fallback_result() -> None:
    result = evaluate_semantic_similarity(_context(), _UnavailableEmbeddingProvider())

    assert result.available is False
    assert result.score is None
    assert result.interpretation == "unavailable"
    assert "RuntimeError" in (result.notes or "")


def test_similarity_result_can_be_inserted_into_semantic_evaluation_context() -> None:
    result = evaluate_semantic_similarity(_context(), _FakeEmbeddingProvider([[1.0, 0.0], [0.9, 0.1]]))
    context = {**_context(), "semantic_similarity": result.__dict__}

    assert context["semantic_similarity"]["available"] is True
    assert context["semantic_similarity"]["interpretation"] == "strong_semantic_match"


def test_semantic_verification_source_snapshot_stores_similarity_metadata(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    similarity = SemanticSimilarityResult(
        available=True,
        score=0.87,
        model_name="fake-local-embedding-model",
        method="sentence_transformers_cosine_similarity",
        claim_text="The student claims that this website recommends a safer route.",
        observed_text="VeriBridge observed alternative low-risk path available.",
        interpretation="strong_semantic_match",
        supports_verification=True,
        claim_bundle_source_fields=["plan.feature_to_verify"],
        observed_bundle_source_fields=["browser_run.safe_text_snapshot"],
    )
    monkeypatch.setattr("app.services.website_semantic_verification_service.evaluate_semantic_similarity", lambda context, provider=None: similarity)
    try:
        evidence = _seed_semantic_endpoint_context(store)
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-semantic-verification-results", json={})

        assert response.status_code == 200
        data = response.json()
        assert data["semantic_similarity"]["available"] is True
        assert data["semantic_similarity"]["score"] == 0.87
        assert data["semantic_similarity"]["label"] == "strong_semantic_match"
        assert data["source_snapshot"]["semantic_similarity"]["model"] == "fake-local-embedding-model"
        assert data["source_snapshot"]["semantic_similarity_claim_bundle_preview"].startswith("The student claims")
        assert data["source_snapshot"]["semantic_similarity_claim_bundle_source_fields"] == ["plan.feature_to_verify"]
        assert data["source_snapshot"]["semantic_similarity_observed_bundle_source_fields"] == ["browser_run.safe_text_snapshot"]
    finally:
        _clear_overrides()


def test_high_similarity_modestly_increases_confidence_in_partial_case(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    monkeypatch.setattr(
        "app.services.website_semantic_verification_service.evaluate_semantic_similarity",
        lambda context, provider=None: SemanticSimilarityResult(
            available=True,
            score=0.90,
            model_name="fake-local-embedding-model",
            method="sentence_transformers_cosine_similarity",
            claim_text="This website recommends a safer route.",
            observed_text="Alternative low-risk path available.",
            interpretation="strong_semantic_match",
            supports_verification=True,
        ),
    )
    try:
        evidence = _seed_semantic_endpoint_context(store)
        data = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-semantic-verification-results", json={}).json()

        assert data["semantic_status"] == "partially_verified"
        assert data["confidence_score"] >= 0.74
        assert "semantic similarity was strong" in store["website_semantic_verification_results"][data["id"]]["internal_reasoning_summary"]
    finally:
        _clear_overrides()


def test_low_similarity_does_not_incorrectly_verify_failed_browser_evidence(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    monkeypatch.setattr(
        "app.services.website_semantic_verification_service.evaluate_semantic_similarity",
        lambda context, provider=None: SemanticSimilarityResult(
            available=True,
            score=0.21,
            model_name="fake-local-embedding-model",
            method="sentence_transformers_cosine_similarity",
            claim_text="This website recommends a safer route.",
            observed_text="Portfolio and contact links.",
            interpretation="low_semantic_match",
            supports_verification=False,
        ),
    )
    try:
        evidence = _seed_semantic_endpoint_context(store, browser_status="browser_failed", static_status="failed_static_checks")
        data = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-semantic-verification-results", json={}).json()

        assert data["semantic_status"] == "not_verified"
        assert data["semantic_similarity"]["label"] == "low_semantic_match"
    finally:
        _clear_overrides()
