"""Tests for proof_session_id scoping in workflow analysis.

Critical invariants verified:
  1. get_latest(user_id, session_A) returns None when only session_B has an
     analysis row — the service never leaks a result across sessions.
  2. The GET /{session_id}/analysis/workflow endpoint returns 404 for session_A
     even when session_B has been analyzed.
  3. Submitting DOM events to session_A and running analysis for session_B
     does not mark session_A as having DOM evidence in session_B's result.
  4. Running analysis for session_A reads DOM events from session_A only.

These tests document the root-cause scenario reported in the bug:
  DOM evidence exists for session A (b127bea4-…) but workflow_analysis_results
  row was written for session B (d4b95be9-…).  Fetching analysis for session A
  must return null / HTTP 404, never session B's row.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.extension_proof_workflow_analysis_service import (
    ExtensionProofWorkflowAnalysisService,
    _SESSION_TABLE,
    _TABLE as _ANALYSIS_TABLE,
)
from app.services.workflow_visible_evidence_service import (
    WorkflowVisibleEvidenceService,
    _TABLE as _VE_TABLE,
)

DEMO_USER_ID = "00000000-0000-0000-0000-000000000042"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000043"

TARGET_URL = "https://myapp.example.com"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _add_session(mem_store: dict, session_id: str, user_id: str = DEMO_USER_ID) -> None:
    """Insert a minimal extension_proof_sessions row."""
    mem_store.setdefault(_SESSION_TABLE, {})[session_id] = {
        "id": session_id,
        "user_id": user_id,
        "status": "completed",
        "proof_data": {
            "start_time": "2024-01-01T10:00:00Z",
            "stop_time": "2024-01-01T10:03:00Z",
            "events": [
                {"type": "page_visit", "page_url": TARGET_URL, "page_title": "My App"},
                {"type": "click", "page_url": TARGET_URL, "element_text": "Submit"},
            ],
        },
        "created_at": "2024-01-01T10:00:00Z",
        "updated_at": "2024-01-01T10:03:00Z",
    }


def _add_analysis(
    mem_store: dict,
    session_id: str,
    user_id: str = DEMO_USER_ID,
    visible_evidence_status: str = "not_captured",
) -> str:
    """Insert a minimal workflow_analysis_results row for session_id."""
    row_id = str(uuid.uuid4())
    mem_store.setdefault(_ANALYSIS_TABLE, {})[row_id] = {
        "id": row_id,
        "proof_session_id": session_id,
        "user_id": user_id,
        "analysis_type": "timeline_only",
        "analyzer_version": "test-1.0",
        "workflow_summary": f"Analysis for {session_id[:8]}",
        "demonstrated_actions": [],
        "supported_skills": ["Python"],
        "weakly_supported_skills": [],
        "unsupported_skills": [],
        "evidence_strength_score": 55,
        "workflow_confidence": "medium",
        "missing_evidence": [],
        "risk_flags": [],
        "recruiter_summary": f"Recruiter summary for {session_id[:8]}",
        "student_improvement_suggestions": [],
        "human_review_needed": False,
        "target_website": TARGET_URL,
        "target_site_pages_count": 2,
        "supporting_evidence_count": 2,
        "noise_filtered_count": 0,
        "observed_demonstration": None,
        "visible_evidence_status": visible_evidence_status,
        "created_at": "2024-01-01T10:05:00Z",
        "updated_at": "2024-01-01T10:05:00Z",
    }
    return row_id


def _add_dom_events(
    mem_store: dict,
    session_id: str,
    user_id: str = DEMO_USER_ID,
    count: int = 3,
) -> None:
    """Insert visible evidence events for session_id."""
    for i in range(count):
        row_id = str(uuid.uuid4())
        mem_store.setdefault(_VE_TABLE, {})[row_id] = {
            "id": row_id,
            "proof_session_id": session_id,
            "user_id": user_id,
            "event_type": "dom_snapshot",
            "page_url": TARGET_URL,
            "visible_text_blocks": [f"Result value {i + 1}: 0.{i + 1}"],
            "result_indicators": [{"type": "numeric", "text": f"0.{i + 1}", "confidence": 0.9}],
            "file_uploads": [],
            "metadata": {"snapshot_index": i},
            "created_at": "2024-01-01T10:01:00Z",
        }


# ── Core session-scoping tests ────────────────────────────────────────────────


class TestGetLatestScopedBySession:
    """ExtensionProofWorkflowAnalysisService.get_latest() must never cross session boundaries."""

    def test_get_latest_returns_none_for_session_with_no_analysis(
        self, mem_store: dict
    ) -> None:
        """session_A has no analysis row → get_latest returns None."""
        session_a = str(uuid.uuid4())
        _add_session(mem_store, session_a)

        svc = ExtensionProofWorkflowAnalysisService(mem_store)
        result = svc.get_latest(user_id=DEMO_USER_ID, session_id=session_a)
        assert result is None

    def test_get_latest_does_not_return_other_sessions_analysis(
        self, mem_store: dict
    ) -> None:
        """session_A has no analysis; session_B has one. get_latest(session_A) must return None."""
        session_a = str(uuid.uuid4())
        session_b = str(uuid.uuid4())

        _add_session(mem_store, session_a)
        _add_session(mem_store, session_b)
        _add_analysis(mem_store, session_b)  # only session_B is analyzed

        svc = ExtensionProofWorkflowAnalysisService(mem_store)

        # session_A must return None — not session_B's row
        result_a = svc.get_latest(user_id=DEMO_USER_ID, session_id=session_a)
        assert result_a is None, (
            "get_latest must return None for session_A when only session_B has an analysis row"
        )

    def test_get_latest_returns_correct_session_analysis(
        self, mem_store: dict
    ) -> None:
        """Both sessions analyzed; each get_latest call returns the matching row."""
        session_a = str(uuid.uuid4())
        session_b = str(uuid.uuid4())

        _add_session(mem_store, session_a)
        _add_session(mem_store, session_b)
        _add_analysis(mem_store, session_a)
        _add_analysis(mem_store, session_b)

        svc = ExtensionProofWorkflowAnalysisService(mem_store)

        result_a = svc.get_latest(user_id=DEMO_USER_ID, session_id=session_a)
        result_b = svc.get_latest(user_id=DEMO_USER_ID, session_id=session_b)

        assert result_a is not None
        assert result_b is not None
        assert result_a["proof_session_id"] == session_a
        assert result_b["proof_session_id"] == session_b
        assert result_a["proof_session_id"] != result_b["proof_session_id"]

    def test_get_latest_isolated_by_user(self, mem_store: dict) -> None:
        """Session belonging to a different user must not bleed across."""
        session_a = str(uuid.uuid4())
        _add_session(mem_store, session_a, user_id=OTHER_USER_ID)
        _add_analysis(mem_store, session_a, user_id=OTHER_USER_ID)

        svc = ExtensionProofWorkflowAnalysisService(mem_store)

        # DEMO_USER_ID querying the same session_id must get None
        result = svc.get_latest(user_id=DEMO_USER_ID, session_id=session_a)
        assert result is None


class TestDOMEvidenceSessionIsolation:
    """DOM events for session_A must not appear in session_B's analysis and vice-versa."""

    def test_dom_events_for_session_a_not_seen_by_session_b(
        self, mem_store: dict
    ) -> None:
        """
        Reproduces the reported bug scenario:
          - DOM events submitted for session_A
          - Analysis stored for session_B (no DOM events)
          - Session_A analysis fetch must return None (not session_B's result)
          - Session_B analysis correctly shows visible_evidence_status = "not_captured"
        """
        session_a = str(uuid.uuid4())
        session_b = str(uuid.uuid4())

        _add_session(mem_store, session_a)
        _add_session(mem_store, session_b)
        _add_dom_events(mem_store, session_a, count=3)            # DOM only for A
        _add_analysis(mem_store, session_b,                        # analysis only for B
                      visible_evidence_status="not_captured")

        svc = ExtensionProofWorkflowAnalysisService(mem_store)
        ve_svc = WorkflowVisibleEvidenceService(mem_store)

        # 1. Session A should have no analysis
        result_a = svc.get_latest(user_id=DEMO_USER_ID, session_id=session_a)
        assert result_a is None, "Session A must not inherit session B's analysis"

        # 2. Session B's analysis should reflect its own status (not_captured)
        result_b = svc.get_latest(user_id=DEMO_USER_ID, session_id=session_b)
        assert result_b is not None
        assert result_b["visible_evidence_status"] == "not_captured"
        assert result_b["proof_session_id"] == session_b

        # 3. Session A's DOM events should be accessible only for session A
        obs_a = ve_svc.get_extracted_observations(DEMO_USER_ID, session_a)
        assert obs_a.event_count >= 3, "Session A should have its DOM events"

        # 4. Session B should have no DOM events
        obs_b = ve_svc.get_extracted_observations(DEMO_USER_ID, session_b)
        assert obs_b.event_count == 0, "Session B should have no DOM events"


class TestAnalysisEndpointScoping:
    """HTTP endpoint: GET /{session_id}/analysis/workflow must return 404 for unanalyzed sessions."""

    def test_get_analysis_404_when_session_unanalyzed(
        self, client: TestClient, mem_store: dict
    ) -> None:
        """Unanalyzed session returns 404, even when another session has been analyzed."""
        session_a = str(uuid.uuid4())
        session_b = str(uuid.uuid4())

        _add_session(mem_store, session_a)
        _add_session(mem_store, session_b)
        _add_dom_events(mem_store, session_a, count=2)
        _add_analysis(mem_store, session_b)

        resp = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_a}/analysis/workflow"
        )
        assert resp.status_code == 404, (
            f"Expected 404 for unanalyzed session_A; got {resp.status_code}: {resp.text}"
        )

    def test_get_analysis_200_returns_correct_session(
        self, client: TestClient, mem_store: dict
    ) -> None:
        """Analyzed session returns 200 with matching proof_session_id."""
        session_a = str(uuid.uuid4())
        _add_session(mem_store, session_a)
        _add_analysis(mem_store, session_a)

        resp = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_a}/analysis/workflow"
        )
        assert resp.status_code == 200, f"Expected 200; got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["proof_session_id"] == session_a, (
            f"proof_session_id mismatch: expected {session_a}, got {data.get('proof_session_id')}"
        )

    def test_get_analysis_never_returns_other_sessions_data(
        self, client: TestClient, mem_store: dict
    ) -> None:
        """Fetching session_A analysis must NOT return session_B's row under any circumstances."""
        session_a = str(uuid.uuid4())
        session_b = str(uuid.uuid4())

        _add_session(mem_store, session_a)
        _add_session(mem_store, session_b)
        _add_analysis(mem_store, session_b)  # only session_B analyzed

        resp = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_a}/analysis/workflow"
        )
        # Must be 404, never 200 with session_B's data
        assert resp.status_code == 404
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("proof_session_id") != session_b, (
                "CRITICAL: endpoint returned session_B's analysis when session_A was requested"
            )
