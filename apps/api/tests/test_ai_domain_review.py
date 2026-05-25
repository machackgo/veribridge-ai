"""Tests for AI Domain Reviewer Agents backend foundation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.ai_domain_review_service import AiDomainReviewService, choose_domain


DEMO_USER_ID = "00000000-0000-0000-0000-000000000042"
EVIDENCE_ID = "eeeeeeee-0000-0000-0000-000000000042"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_session(client: TestClient, mem_store: dict, *, skill: str, metadata: dict | None = None) -> str:
    mem_store.setdefault("skill_evidence", {})[EVIDENCE_ID] = {
        "id": EVIDENCE_ID,
        "user_id": DEMO_USER_ID,
        "skill_name": skill,
        "evidence_type": "project",
        "evidence_description": skill,
        "metadata": metadata or {},
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    response = client.post(
        "/api/v1/student/extension-proof/sessions",
        json={"skill_evidence_id": EVIDENCE_ID},
    )
    assert response.status_code == 201, response.text
    session_id = response.json()["id"]
    mem_store["extension_proof_sessions"][session_id]["status"] = "uploaded_pending_analysis"
    return session_id


def _seed_strong_clean_evidence(mem_store: dict, session_id: str, *, skills: list[str]) -> None:
    mem_store.setdefault("workflow_analysis_results", {})["wf"] = {
        "id": "wf",
        "user_id": DEMO_USER_ID,
        "proof_session_id": session_id,
        "supported_skills": skills,
        "weakly_supported_skills": [],
        "risk_flags": [],
        "recruiter_summary": "Workflow evidence shows meaningful project work and skill usage.",
    }
    mem_store.setdefault("extension_proof_github_analysis", {})["gh"] = {
        "id": "gh",
        "user_id": DEMO_USER_ID,
        "proof_session_id": session_id,
        "status": "success",
        "matched_claimed_skills": skills,
        "weakly_matched_claimed_skills": [],
        "recruiter_summary": "Repository analysis supports the claimed technical skills.",
    }
    mem_store.setdefault("live_website_check_results", {})["live"] = {
        "id": "live",
        "user_id": DEMO_USER_ID,
        "proof_session_id": session_id,
        "is_reachable": True,
        "status_code": 200,
    }
    mem_store.setdefault("workflow_privacy_scan_results", {})["privacy"] = {
        "id": "privacy",
        "user_id": DEMO_USER_ID,
        "proof_session_id": session_id,
        "status": "clean",
    }
    mem_store.setdefault("project_defense_analysis_results", {})["defense"] = {
        "id": "defense",
        "user_id": DEMO_USER_ID,
        "proof_session_id": session_id,
        "overall_defense_score": 90,
        "ownership_signal_score": 90,
        "technical_depth_score": 88,
        "consistency_with_evidence_score": 90,
        "privacy_scan_status": "clean",
        "risk_flags": [],
        "transcript_text": (
            "I built this project and can explain the architecture, data flow, "
            "tradeoffs, testing approach, and limitations with technical detail."
        ),
    }


def _run_review(client: TestClient, session_id: str) -> dict:
    response = client.post(
        f"/api/v1/student/extension-proof/sessions/{session_id}/ai-domain-review"
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_cs_ai_proof_selects_astra(client: TestClient, mem_store: dict) -> None:
    sid = _make_session(client, mem_store, skill="Machine Learning API", metadata={"field": "Computer Science"})
    _seed_strong_clean_evidence(mem_store, sid, skills=["Machine Learning API"])
    body = _run_review(client, sid)
    assert body["reviewer_name"] == "Astra"
    assert body["domain"] == "cs_ai"


def test_civil_mechanical_proof_selects_atlas(client: TestClient, mem_store: dict) -> None:
    sid = _make_session(client, mem_store, skill="Mechanical stress analysis", metadata={"discipline": "Mechanical Engineering"})
    _seed_strong_clean_evidence(mem_store, sid, skills=["Mechanical stress analysis"])
    body = _run_review(client, sid)
    assert body["reviewer_name"] == "Atlas"
    assert body["domain"] == "civil_mech_eng"


def test_business_finance_proof_selects_nova(client: TestClient, mem_store: dict) -> None:
    sid = _make_session(client, mem_store, skill="Finance analytics dashboard", metadata={"field": "Business Analytics"})
    _seed_strong_clean_evidence(mem_store, sid, skills=["Finance analytics dashboard"])
    body = _run_review(client, sid)
    assert body["reviewer_name"] == "Nova"
    assert body["domain"] == "business_finance"


def test_unknown_field_selects_general(client: TestClient, mem_store: dict) -> None:
    sid = _make_session(client, mem_store, skill="Specialized craft documentation", metadata={"field": "Interdisciplinary"})
    body = _run_review(client, sid)
    assert body["reviewer_name"] == "General"
    assert body["domain"] == "general"


def test_missing_anthropic_config_falls_back_deterministic(client: TestClient, mem_store: dict) -> None:
    sid = _make_session(client, mem_store, skill="Python")
    body = _run_review(client, sid)
    assert body["llm_used"] is False
    assert body["fallback_reason"] == "LLM reviewer not configured; using rubric-based deterministic review."


def test_every_criterion_includes_evidence_sources_used(client: TestClient, mem_store: dict) -> None:
    sid = _make_session(client, mem_store, skill="Python")
    body = _run_review(client, sid)
    assert body["criterion_scores"]
    assert all("evidence_sources_used" in criterion for criterion in body["criterion_scores"])


def test_disclosure_and_limitations_always_present(client: TestClient, mem_store: dict) -> None:
    sid = _make_session(client, mem_store, skill="Python")
    body = _run_review(client, sid)
    assert body["disclosure_note"]
    assert "Human/faculty/company review has not been completed" in body["disclosure_note"]
    assert body["review_limitations"]


def test_ai_review_never_sets_human_verified(client: TestClient, mem_store: dict) -> None:
    sid = _make_session(client, mem_store, skill="Python")
    body = _run_review(client, sid)
    assert "human_verified" not in body
    assert body["ai_domain_review_status"] != "human_verified"
    assert body["recruiter_summary"].lower().find("human verified") == -1


def test_privacy_flagged_blocks_or_recommends_human_review(client: TestClient, mem_store: dict) -> None:
    sid = _make_session(client, mem_store, skill="Python")
    mem_store.setdefault("workflow_privacy_scan_results", {})["privacy"] = {
        "id": "privacy",
        "user_id": DEMO_USER_ID,
        "proof_session_id": sid,
        "status": "flagged",
    }
    body = _run_review(client, sid)
    assert body["ai_domain_review_status"] == "privacy_blocked"
    assert body["human_review_recommended"] is True


def test_low_support_becomes_needs_more_evidence(client: TestClient, mem_store: dict) -> None:
    sid = _make_session(client, mem_store, skill="Python")
    body = _run_review(client, sid)
    assert body["ai_domain_review_status"] == "needs_more_evidence"


def test_high_readiness_clean_proof_can_become_ai_domain_reviewed(client: TestClient, mem_store: dict) -> None:
    sid = _make_session(client, mem_store, skill="Python API", metadata={"field": "Computer Science"})
    _seed_strong_clean_evidence(mem_store, sid, skills=["Python API"])
    body = _run_review(client, sid)
    assert body["ai_domain_review_status"] == "ai_domain_reviewed"
    assert body["domain_review_score"] >= 80


def test_high_risk_domain_triggers_human_review_recommended(client: TestClient, mem_store: dict) -> None:
    sid = _make_session(client, mem_store, skill="Structural load calculation", metadata={"discipline": "Civil Engineering"})
    _seed_strong_clean_evidence(mem_store, sid, skills=["Structural load calculation"])
    body = _run_review(client, sid)
    assert body["human_review_recommended"] is True
    assert body["ai_domain_review_status"] == "human_review_recommended"


def test_non_native_grammar_does_not_automatically_reduce_strong_technical_score(client: TestClient, mem_store: dict) -> None:
    sid = _make_session(client, mem_store, skill="Machine Learning", metadata={"field": "Computer Science"})
    _seed_strong_clean_evidence(mem_store, sid, skills=["Machine Learning"])
    mem_store["project_defense_analysis_results"]["defense"]["transcript_text"] = (
        "I build model myself. Grammar not perfect, but I explain data split, "
        "feature engineering, validation metric, error analysis, tradeoffs, and why model chosen."
    )
    body = _run_review(client, sid)
    assert body["domain_review_score"] >= 80
    assert body["ai_domain_review_status"] == "ai_domain_reviewed"


def test_no_project_specific_hardcoding() -> None:
    import inspect

    joined = inspect.getsource(AiDomainReviewService).lower()
    assert "boston" not in joined
    assert "react demo" not in joined
    assert "route risk" not in joined
    assert "veribridge-ai" not in joined
    assert choose_domain({"claimed_skills": ["unclassified field"], "session": {}, "skill_evidence": {}}) == "general"
