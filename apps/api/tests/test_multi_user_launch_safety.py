"""Step 6A — multi-user launch safety regression tests.

Covers the two ownership/auth gaps found in the pre-launch audit plus
cross-user isolation for the Project Defense analysis surface:

1. ``/admin/verification-reviews`` (list / decision / invite-reviewer) was
   completely unauthenticated. It is now gated by ``require_admin_user_id``:
   a plain authenticated student must get 403 and must never be able to list
   other students' review requests or override decisions.

2. ``/recruiter/candidates`` (search / detail) let ANY authenticated user
   enumerate other students and dump their private skill evidence (including
   pending/unverified rows, screenshots, and access links). It is now gated
   by ``require_admin_user_id``.

3. Project Defense analysis routes under
   ``/student/extension-proof/sessions/{session_id}/...`` are keyed by
   ``(user_id, session_id)``: User B must get a generic 404 on User A's
   session and must never read or overwrite A's transcript or analysis.

All storage is in-memory (get_db → {}). No real network calls.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app

USER_A = "aaaaaaaa-0000-0000-0000-000000000001"
USER_B = "bbbbbbbb-0000-0000-0000-000000000002"
ADMIN_ID = "cccccccc-0000-0000-0000-000000000003"
EVIDENCE_ID = "eeeeeeee-0000-0000-0000-000000000042"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.clear()


def _client_as(user_id: str, mem_store: dict) -> TestClient:
    """Authenticated client for ``user_id``; admin gating is NOT bypassed."""
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    app.dependency_overrides[get_db] = lambda: mem_store
    return TestClient(app)


def _grant_admin(mem_store: dict, user_id: str) -> None:
    mem_store.setdefault("users", {})[user_id] = {"id": user_id, "role": "admin"}


def _set_user_role(mem_store: dict, user_id: str, role: str) -> None:
    """Set the primary ``users.role`` column (admin / university_admin / etc.)."""
    mem_store.setdefault("users", {})[user_id] = {"id": user_id, "role": role}


def _grant_user_roles_grant(mem_store: dict, user_id: str, role: str) -> None:
    """Grant a role via the ``user_roles`` table (how support/reviewer are granted).

    These grants satisfy ``require_admin_user_id`` (admin/support/reviewer) but
    must NOT satisfy the stricter candidate-discovery gate.
    """
    row_id = f"grant:{user_id}:{role}"
    mem_store.setdefault("user_roles", {})[row_id] = {
        "id": row_id,
        "user_id": user_id,
        "role": role,
        "scope": "global",
        "scope_id": None,
        "granted_by": None,
        "is_active": True,
        "created_at": "2026-07-01T00:00:00Z",
        "revoked_at": None,
        "metadata": {},
    }


# ── 1. Admin verification-review routes require an admin ─────────────────────


class TestAdminVerificationReviewGating:
    def test_student_cannot_list_all_review_requests(self, mem_store: dict) -> None:
        client = _client_as(USER_B, mem_store)
        r = client.get("/api/v1/admin/verification-reviews")
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "admin_required"

    def test_student_cannot_override_review_decision(self, mem_store: dict) -> None:
        client = _client_as(USER_B, mem_store)
        r = client.post(
            "/api/v1/admin/verification-reviews/some-review-id/decision",
            json={"ai_review_status": "ai_approved_for_sharing"},
        )
        assert r.status_code == 403

    def test_student_cannot_invite_reviewer(self, mem_store: dict) -> None:
        client = _client_as(USER_B, mem_store)
        r = client.post(
            "/api/v1/admin/verification-reviews/some-review-id/invite-reviewer",
            params={
                "reviewer_email": "reviewer@example.com",
                "reviewer_name": "Reviewer",
                "reviewer_role": "faculty_reviewer",
            },
        )
        assert r.status_code == 403

    def test_admin_role_can_list_review_requests(self, mem_store: dict) -> None:
        _grant_admin(mem_store, ADMIN_ID)
        client = _client_as(ADMIN_ID, mem_store)
        r = client.get("/api/v1/admin/verification-reviews")
        assert r.status_code == 200
        assert r.json() == []


# ── 2. Recruiter candidate discovery is no longer student-browsable ──────────


class TestRecruiterCandidateDiscoveryGating:
    def _seed_private_evidence(self, mem_store: dict) -> None:
        mem_store.setdefault("skill_evidence", {})["ev-a-1"] = {
            "id": "ev-a-1",
            "user_id": USER_A,
            "skill_name": "Python",
            "evidence_type": "github repository",
            "evidence_description": "Private pending evidence for user A.",
            "verification_status": "pending",
            "metadata": {},
            "created_at": "2026-07-01T00:00:00Z",
            "updated_at": "2026-07-01T00:00:00Z",
        }
        mem_store.setdefault("student_profiles", {})["prof-a"] = {
            "id": "prof-a",
            "user_id": USER_A,
            "full_name": "Student A",
            "school_name": "Some University",
        }

    def test_student_cannot_search_other_students_evidence(self, mem_store: dict) -> None:
        self._seed_private_evidence(mem_store)
        client = _client_as(USER_B, mem_store)
        r = client.get("/api/v1/recruiter/candidates/search", params={"query": "Python"})
        assert r.status_code == 403
        body = r.text
        assert USER_A not in body
        assert "Student A" not in body

    def test_student_cannot_dump_another_students_candidate_detail(
        self, mem_store: dict
    ) -> None:
        self._seed_private_evidence(mem_store)
        client = _client_as(USER_B, mem_store)
        r = client.get(f"/api/v1/recruiter/candidates/{USER_A}/detail")
        assert r.status_code == 403
        body = r.text
        assert "Student A" not in body
        assert "Private pending evidence" not in body

    def test_admin_role_can_still_use_candidate_search(self, mem_store: dict) -> None:
        self._seed_private_evidence(mem_store)
        _grant_admin(mem_store, ADMIN_ID)
        client = _client_as(ADMIN_ID, mem_store)
        r = client.get("/api/v1/recruiter/candidates/search", params={"query": "Python"})
        assert r.status_code == 200
        assert r.json()["result_count"] == 1

    # ── Full role matrix: only admin / university_admin may discover candidates ──
    #
    # ``require_admin_user_id`` also admits ``support`` and ``reviewer`` grants,
    # which is too broad for candidate discovery. These endpoints must use the
    # stricter ``require_admin_or_university_admin_user_id`` gate.

    @pytest.mark.parametrize(
        "role, via_user_roles",
        [
            ("student", False),
            ("recruiter", False),
            ("reviewer", True),
            ("support", True),
        ],
    )
    def test_non_admin_roles_denied_candidate_search(
        self, mem_store: dict, role: str, via_user_roles: bool
    ) -> None:
        self._seed_private_evidence(mem_store)
        if via_user_roles:
            _grant_user_roles_grant(mem_store, USER_B, role)
        else:
            _set_user_role(mem_store, USER_B, role)
        client = _client_as(USER_B, mem_store)
        r = client.get("/api/v1/recruiter/candidates/search", params={"query": "Python"})
        assert r.status_code == 403, f"{role} should be denied candidate search"
        body = r.text
        assert USER_A not in body
        assert "Student A" not in body

    @pytest.mark.parametrize(
        "role, via_user_roles",
        [
            ("student", False),
            ("recruiter", False),
            ("reviewer", True),
            ("support", True),
        ],
    )
    def test_non_admin_roles_denied_candidate_detail(
        self, mem_store: dict, role: str, via_user_roles: bool
    ) -> None:
        self._seed_private_evidence(mem_store)
        if via_user_roles:
            _grant_user_roles_grant(mem_store, USER_B, role)
        else:
            _set_user_role(mem_store, USER_B, role)
        client = _client_as(USER_B, mem_store)
        r = client.get(f"/api/v1/recruiter/candidates/{USER_A}/detail")
        assert r.status_code == 403, f"{role} should be denied candidate detail"
        body = r.text
        assert "Student A" not in body
        assert "Private pending evidence" not in body

    @pytest.mark.parametrize("role", ["admin", "university_admin"])
    def test_privileged_roles_allowed_candidate_search(
        self, mem_store: dict, role: str
    ) -> None:
        self._seed_private_evidence(mem_store)
        _set_user_role(mem_store, ADMIN_ID, role)
        client = _client_as(ADMIN_ID, mem_store)
        r = client.get("/api/v1/recruiter/candidates/search", params={"query": "Python"})
        assert r.status_code == 200, f"{role} should be allowed candidate search"
        assert r.json()["result_count"] == 1

    @pytest.mark.parametrize("role", ["admin", "university_admin"])
    def test_privileged_roles_allowed_candidate_detail(
        self, mem_store: dict, role: str
    ) -> None:
        self._seed_private_evidence(mem_store)
        _set_user_role(mem_store, ADMIN_ID, role)
        client = _client_as(ADMIN_ID, mem_store)
        r = client.get(f"/api/v1/recruiter/candidates/{USER_A}/detail")
        assert r.status_code == 200, f"{role} should be allowed candidate detail"
        assert r.json()["candidate_id"] == USER_A


# ── 3. Project Defense analysis session isolation ────────────────────────────


class TestProjectDefenseAnalysisCrossUserIsolation:
    def _create_session_and_analysis_as_a(self, mem_store: dict) -> str:
        client_a = _client_as(USER_A, mem_store)
        r = client_a.post(
            "/api/v1/student/extension-proof/sessions",
            json={"skill_evidence_id": EVIDENCE_ID},
        )
        assert r.status_code == 201, r.text
        session_id = r.json()["id"]

        r = client_a.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/project-defense",
            json={
                "transcript_text": "I built the ingestion pipeline in Python myself.",
                "claimed_skills": ["Python"],
            },
        )
        assert r.status_code == 201, r.text
        return session_id

    def test_user_b_cannot_read_user_a_defense_analysis(self, mem_store: dict) -> None:
        session_id = self._create_session_and_analysis_as_a(mem_store)
        client_b = _client_as(USER_B, mem_store)
        r = client_b.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analysis/project-defense"
        )
        assert r.status_code == 404
        assert "ingestion pipeline" not in r.text

    def test_user_b_cannot_overwrite_user_a_transcript(self, mem_store: dict) -> None:
        session_id = self._create_session_and_analysis_as_a(mem_store)
        client_b = _client_as(USER_B, mem_store)
        r = client_b.patch(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcript",
            json={"transcript_text": "attacker text", "transcript_reviewed": True},
        )
        assert r.status_code == 404

        # A's stored transcript is untouched.
        client_a = _client_as(USER_A, mem_store)
        r = client_a.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analysis/project-defense"
        )
        assert r.status_code == 200
        assert "attacker text" not in r.text

    def test_user_b_cannot_run_analysis_on_user_a_session(self, mem_store: dict) -> None:
        session_id = self._create_session_and_analysis_as_a(mem_store)
        client_b = _client_as(USER_B, mem_store)
        r = client_b.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/project-defense",
            json={"transcript_text": "attacker transcript", "claimed_skills": ["Python"]},
        )
        assert r.status_code == 404

    def test_user_b_cannot_transcribe_user_a_media(self, mem_store: dict) -> None:
        session_id = self._create_session_and_analysis_as_a(mem_store)
        client_b = _client_as(USER_B, mem_store)
        r = client_b.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcribe"
        )
        assert r.status_code == 404
