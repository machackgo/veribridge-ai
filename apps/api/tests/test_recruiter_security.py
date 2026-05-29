"""Security tests for recruiter endpoints and evidence access token hardening.

These tests verify the three critical/high security findings from the audit:

Critical 1 — Saved-passport endpoints require a valid recruiter session token.
Critical 2 — Candidate-comparison endpoints require a valid recruiter session token.
High 3     — Evidence access tokens are stored as SHA-256 hashes; plaintext is
             returned only once on grant creation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.recruiter_shortlist_service import RecruiterShortlistService
from app.schemas.recruiter_shortlist import RecruiterSavedPassportCreate

USER_ID = "00000000-0000-0000-0000-000000000042"
OWNER_EMAIL = "owner@example.com"
VICTIM_EMAIL = "victim@corp.com"
ATTACKER_EMAIL = "attacker@evil.com"


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    """No recruiter session override — tests exercise the real token flow."""
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── helpers ───────────────────────────────────────────────────────────────────

def _seed_passport(mem_store: dict, slug: str = "test-passport") -> dict[str, str]:
    session_id = str(uuid4())
    passport_id = str(uuid4())
    evidence_id = str(uuid4())
    mem_store.setdefault("users", {})[USER_ID] = {"id": USER_ID, "email": "student@example.edu"}
    mem_store.setdefault("student_profiles", {})[f"p-{USER_ID}"] = {
        "id": f"p-{USER_ID}", "user_id": USER_ID, "full_name": "Test Student",
    }
    mem_store.setdefault("skill_evidence", {})[evidence_id] = {
        "id": evidence_id, "user_id": USER_ID, "skill_name": "Python",
        "evidence_url": "https://example.edu/project",
    }
    mem_store.setdefault("extension_proof_sessions", {})[session_id] = {
        "id": session_id, "user_id": USER_ID,
        "skill_evidence_id": evidence_id, "status": "completed",
    }
    mem_store.setdefault("public_work_passports", {})[passport_id] = {
        "id": passport_id, "user_id": USER_ID, "proof_session_id": session_id,
        "public_slug": slug, "is_public": True,
        "public_title": "Test Passport", "public_summary": "Summary.",
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    return {"session_id": session_id, "passport_id": passport_id, "slug": slug}


def _seed_candidate_data(mem_store: dict, user_id: str, suffix: str) -> str:
    """Seed enough data for comparison service to build a snapshot. Returns public slug."""
    session_id = str(uuid4())
    evidence_id = str(uuid4())
    passport_id = str(uuid4())
    slug = f"candidate-{suffix}"
    mem_store.setdefault("users", {})[user_id] = {"id": user_id, "email": f"{suffix}@example.edu"}
    mem_store.setdefault("student_profiles", {})[f"p-{user_id}"] = {
        "id": f"p-{user_id}", "user_id": user_id, "full_name": suffix.title(),
    }
    mem_store.setdefault("skill_evidence", {})[evidence_id] = {
        "id": evidence_id, "user_id": user_id, "skill_name": "Python",
        "claimed_skills": ["Python"],
    }
    mem_store.setdefault("extension_proof_sessions", {})[session_id] = {
        "id": session_id, "user_id": user_id,
        "skill_evidence_id": evidence_id, "status": "completed",
    }
    mem_store.setdefault("workflow_analysis_results", {})[f"w-{session_id}"] = {
        "id": f"w-{session_id}", "user_id": user_id, "proof_session_id": session_id,
        "supported_skills": ["Python"],
    }
    mem_store.setdefault("workflow_privacy_scan_results", {})[f"priv-{session_id}"] = {
        "id": f"priv-{session_id}", "user_id": user_id, "proof_session_id": session_id,
        "status": "clean",
    }
    mem_store.setdefault("ai_domain_review_results", {})[f"ai-{session_id}"] = {
        "id": f"ai-{session_id}", "user_id": user_id, "proof_session_id": session_id,
        "verified_skills": ["Python"], "domain_review_score": 80,
    }
    mem_store.setdefault("public_work_passports", {})[passport_id] = {
        "id": passport_id, "user_id": user_id, "proof_session_id": session_id,
        "public_slug": slug, "is_public": True,
        "public_title": f"{suffix.title()} Passport",
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    return slug


def _create_recruiter_session(client: TestClient, email: str) -> str:
    """Call the session endpoint and return the plaintext token."""
    resp = client.post("/api/v1/public/recruiter/sessions", json={"requester_email": email})
    assert resp.status_code == 201, resp.text
    return resp.json()["session_token"]


def _save_passport_for(mem_store: dict, slug: str, requester_email: str) -> dict:
    return RecruiterShortlistService(mem_store).save_passport(
        slug,
        RecruiterSavedPassportCreate(
            requester_email=requester_email,
            requester_name="Test Recruiter",
            organization_name="Test Org",
            status="saved",
        ),
    ).model_dump(mode="json")


# ═══════════════════════════════════════════════════════════════════════════
# CRITICAL 1 — Saved-passport endpoints require a valid recruiter session
# ═══════════════════════════════════════════════════════════════════════════

class TestSavedPassportSessionRequired:
    """Verify that list/update/delete saved-passport endpoints reject requests
    without a valid recruiter session token."""

    def test_list_saved_passports_requires_session(self, client: TestClient, mem_store: dict) -> None:
        """GET /recruiter/saved-passports must return 401 without session token."""
        resp = client.get("/api/v1/public/recruiter/saved-passports")
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "recruiter_session_required"

    def test_update_saved_passport_requires_session(self, client: TestClient, mem_store: dict) -> None:
        """PATCH /recruiter/saved-passports/{id} must return 401 without session token."""
        resp = client.patch(
            "/api/v1/public/recruiter/saved-passports/some-id",
            json={"status": "shortlisted"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "recruiter_session_required"

    def test_delete_saved_passport_requires_session(self, client: TestClient, mem_store: dict) -> None:
        """DELETE /recruiter/saved-passports/{id} must return 401 without session token."""
        resp = client.delete("/api/v1/public/recruiter/saved-passports/some-id")
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "recruiter_session_required"

    def test_attacker_cannot_list_victim_saved_passports_with_victim_email(
        self,
        client: TestClient,
        mem_store: dict,
    ) -> None:
        """An attacker who knows VICTIM_EMAIL cannot list their saved passports
        by passing the email as a query parameter — the endpoint now ignores query
        params and requires a session token."""
        _seed_passport(mem_store)
        _save_passport_for(mem_store, "test-passport", VICTIM_EMAIL)

        # Attacker has no session for VICTIM_EMAIL; passes it as a query param (old API)
        resp = client.get(
            "/api/v1/public/recruiter/saved-passports",
            params={"requester_email": VICTIM_EMAIL},
        )
        assert resp.status_code == 401  # Rejected — session required

    def test_attacker_cannot_update_victim_saved_passport_with_victim_email_in_body(
        self,
        client: TestClient,
        mem_store: dict,
    ) -> None:
        """An attacker who knows VICTIM_EMAIL cannot update their saved passport
        by embedding the email in the request body."""
        _seed_passport(mem_store)
        saved = _save_passport_for(mem_store, "test-passport", VICTIM_EMAIL)

        resp = client.patch(
            f"/api/v1/public/recruiter/saved-passports/{saved['id']}",
            json={"requester_email": VICTIM_EMAIL, "status": "shortlisted"},
        )
        assert resp.status_code == 401  # No session token → rejected

    def test_attacker_cannot_delete_victim_saved_passport_with_victim_email(
        self,
        client: TestClient,
        mem_store: dict,
    ) -> None:
        """An attacker who knows VICTIM_EMAIL cannot delete their saved passport."""
        _seed_passport(mem_store)
        saved = _save_passport_for(mem_store, "test-passport", VICTIM_EMAIL)

        resp = client.delete(
            f"/api/v1/public/recruiter/saved-passports/{saved['id']}",
            params={"requester_email": VICTIM_EMAIL},
        )
        assert resp.status_code == 401  # No session token → rejected

    def test_valid_session_can_list_own_saved_passports(
        self,
        client: TestClient,
        mem_store: dict,
    ) -> None:
        """A recruiter with a valid session can list their own saved passports."""
        _seed_passport(mem_store)
        _save_passport_for(mem_store, "test-passport", OWNER_EMAIL)

        token = _create_recruiter_session(client, OWNER_EMAIL)
        resp = client.get(
            "/api/v1/public/recruiter/saved-passports",
            headers={"X-Recruiter-Token": token},
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["requester_email"] == OWNER_EMAIL

    def test_valid_session_can_update_own_saved_passport(
        self,
        client: TestClient,
        mem_store: dict,
    ) -> None:
        """A recruiter with a valid session can update their own saved passport."""
        _seed_passport(mem_store)
        saved = _save_passport_for(mem_store, "test-passport", OWNER_EMAIL)

        token = _create_recruiter_session(client, OWNER_EMAIL)
        resp = client.patch(
            f"/api/v1/public/recruiter/saved-passports/{saved['id']}",
            json={"status": "shortlisted", "private_notes": "Great candidate."},
            headers={"X-Recruiter-Token": token},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "shortlisted"
        assert resp.json()["private_notes"] == "Great candidate."

    def test_valid_session_can_delete_own_saved_passport(
        self,
        client: TestClient,
        mem_store: dict,
    ) -> None:
        """A recruiter with a valid session can delete their own saved passport."""
        _seed_passport(mem_store)
        saved = _save_passport_for(mem_store, "test-passport", OWNER_EMAIL)

        token = _create_recruiter_session(client, OWNER_EMAIL)
        resp = client.delete(
            f"/api/v1/public/recruiter/saved-passports/{saved['id']}",
            headers={"X-Recruiter-Token": token},
        )
        assert resp.status_code == 204
        assert mem_store.get("recruiter_saved_passports", {}) == {}

    def test_session_owner_cannot_update_another_recruiters_saved_passport(
        self,
        client: TestClient,
        mem_store: dict,
    ) -> None:
        """A valid session for ATTACKER_EMAIL cannot update VICTIM_EMAIL's saved passport."""
        _seed_passport(mem_store)
        saved = _save_passport_for(mem_store, "test-passport", VICTIM_EMAIL)

        # Attacker creates a legitimate session for their own email
        attacker_token = _create_recruiter_session(client, ATTACKER_EMAIL)
        resp = client.patch(
            f"/api/v1/public/recruiter/saved-passports/{saved['id']}",
            json={"status": "shortlisted"},
            headers={"X-Recruiter-Token": attacker_token},
        )
        assert resp.status_code == 404  # Ownership check: attacker email ≠ record email


# ═══════════════════════════════════════════════════════════════════════════
# CRITICAL 2 — Candidate-comparison endpoints require a valid recruiter session
# ═══════════════════════════════════════════════════════════════════════════

class TestCandidateComparisonSessionRequired:
    """Verify that list/get/archive comparison endpoints reject unauthenticated requests."""

    def test_list_comparisons_requires_session(self, client: TestClient, mem_store: dict) -> None:
        resp = client.get("/api/v1/public/recruiter/candidate-comparisons")
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "recruiter_session_required"

    def test_get_comparison_requires_session(self, client: TestClient, mem_store: dict) -> None:
        resp = client.get("/api/v1/public/recruiter/candidate-comparisons/some-id")
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "recruiter_session_required"

    def test_archive_comparison_requires_session(self, client: TestClient, mem_store: dict) -> None:
        resp = client.post("/api/v1/public/recruiter/candidate-comparisons/some-id/archive")
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "recruiter_session_required"

    def test_attacker_cannot_list_victim_comparisons_with_email_query_param(
        self,
        client: TestClient,
        mem_store: dict,
    ) -> None:
        """Old API accepted requester_email as query param — now ignored without session."""
        resp = client.get(
            "/api/v1/public/recruiter/candidate-comparisons",
            params={"requester_email": VICTIM_EMAIL},
        )
        assert resp.status_code == 401

    def test_attacker_cannot_archive_victim_comparison(
        self,
        client: TestClient,
        mem_store: dict,
    ) -> None:
        """Archive with only email query param (old API) must fail."""
        resp = client.post(
            "/api/v1/public/recruiter/candidate-comparisons/some-id/archive",
            params={"requester_email": VICTIM_EMAIL},
        )
        assert resp.status_code == 401

    def test_valid_session_can_access_own_comparisons(
        self,
        client: TestClient,
        mem_store: dict,
    ) -> None:
        """A recruiter with a valid session can list their own comparisons."""
        user_b = "00000000-0000-0000-0000-000000000099"
        slug = _seed_candidate_data(mem_store, user_b, "cand-b")
        # Save the candidate for OWNER_EMAIL
        _save_passport_for(mem_store, slug, OWNER_EMAIL)

        # Create comparison using the create endpoint (no session required for create)
        create_resp = client.post(
            "/api/v1/public/recruiter/candidate-comparisons",
            json={
                "requester_email": OWNER_EMAIL,
                "comparison_name": "Test Comparison",
                "role_requirements": {"required_skills": ["Python"], "preferred_skills": []},
                "saved_passport_ids": [],
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        comparison_id = create_resp.json()["id"]

        # List with valid session
        owner_token = _create_recruiter_session(client, OWNER_EMAIL)
        list_resp = client.get(
            "/api/v1/public/recruiter/candidate-comparisons",
            headers={"X-Recruiter-Token": owner_token},
        )
        assert list_resp.status_code == 200
        comparison_ids = [c["id"] for c in list_resp.json()]
        assert comparison_id in comparison_ids

    def test_attacker_session_cannot_see_victim_comparisons(
        self,
        client: TestClient,
        mem_store: dict,
    ) -> None:
        """A session for ATTACKER_EMAIL cannot retrieve VICTIM_EMAIL's comparisons."""
        # Create a comparison for VICTIM_EMAIL
        client.post(
            "/api/v1/public/recruiter/candidate-comparisons",
            json={
                "requester_email": VICTIM_EMAIL,
                "comparison_name": "Victim Comparison",
                "role_requirements": {"required_skills": ["Python"], "preferred_skills": []},
                "saved_passport_ids": [],
            },
        )

        attacker_token = _create_recruiter_session(client, ATTACKER_EMAIL)
        resp = client.get(
            "/api/v1/public/recruiter/candidate-comparisons",
            headers={"X-Recruiter-Token": attacker_token},
        )
        assert resp.status_code == 200
        # Attacker's list is empty — victim's comparison is not returned
        assert all(c["requester_email"] != VICTIM_EMAIL for c in resp.json())


# ═══════════════════════════════════════════════════════════════════════════
# HIGH 3 — Evidence access tokens hashed at rest
# ═══════════════════════════════════════════════════════════════════════════

class TestEvidenceAccessTokenHashing:
    """Verify that evidence access tokens are stored as hashes and plaintext
    is returned only once on grant creation."""

    def _setup_passport_and_request(self, client: TestClient, mem_store: dict) -> tuple[str, str, str]:
        """Return (session_id, passport_slug, access_request_id)."""
        from app.services.public_work_passport_service import PublicWorkPassportService
        evidence_id = str(uuid4())
        mem_store.setdefault("users", {})[USER_ID] = {
            "id": USER_ID, "email": "student@example.edu",
        }
        mem_store.setdefault("student_profiles", {})[f"p-{USER_ID}"] = {
            "id": f"p-{USER_ID}", "user_id": USER_ID, "full_name": "Test Student",
            "preferences": {"show_public_name": True},
        }
        mem_store.setdefault("skill_evidence", {})[evidence_id] = {
            "id": evidence_id, "user_id": USER_ID, "skill_name": "Python",
            "evidence_url": "https://example.edu/project",
            "metadata": {"evidence_title": "Python Project"},
        }
        # Create session
        sess_resp = client.post(
            "/api/v1/student/extension-proof/sessions",
            json={"skill_evidence_id": evidence_id},
        )
        assert sess_resp.status_code == 201, sess_resp.text
        session_id = sess_resp.json()["id"]
        mem_store["extension_proof_sessions"][session_id]["status"] = "uploaded_pending_analysis"

        # Seed minimal evidence for passport creation
        mem_store.setdefault("workflow_analysis_results", {})[f"w-{session_id}"] = {
            "id": f"w-{session_id}", "user_id": USER_ID, "proof_session_id": session_id,
            "supported_skills": ["Python"],
        }
        mem_store.setdefault("workflow_privacy_scan_results", {})[f"priv-{session_id}"] = {
            "id": f"priv-{session_id}", "user_id": USER_ID, "proof_session_id": session_id,
            "status": "clean",
        }
        mem_store.setdefault("ai_domain_review_results", {})[f"ai-{session_id}"] = {
            "id": f"ai-{session_id}", "user_id": USER_ID, "proof_session_id": session_id,
            "verified_skills": ["Python"], "domain_review_score": 80,
            "recruiter_summary": "Good Python skills.",
        }

        # Create passport
        passport_resp = client.post(f"/api/v1/student/extension-proof/sessions/{session_id}/passport")
        assert passport_resp.status_code == 200, passport_resp.text
        slug = passport_resp.json()["public_slug"]

        # Create access request
        req_resp = client.post(
            f"/api/v1/public/passports/{slug}/request-access",
            json={
                "requester_name": "Recruiter",
                "requester_email": "recruiter@corp.com",
                "requester_organization": "Corp",
                "request_reason": "Interview",
                "requested_sections": ["github_analysis"],
            },
        )
        assert req_resp.status_code == 201, req_resp.text
        return session_id, slug, req_resp.json()["id"]

    def test_evidence_access_grant_stores_token_hash_not_plaintext(
        self,
        client: TestClient,
        mem_store: dict,
    ) -> None:
        """The DB row for a new grant stores access_token_hash and NOT a plaintext access_token."""
        session_id, slug, request_id = self._setup_passport_and_request(client, mem_store)

        grant_resp = client.post(f"/api/v1/student/access-requests/{request_id}/approve")
        assert grant_resp.status_code == 200, grant_resp.text

        # Inspect DB row directly
        grants = list(mem_store.get("evidence_access_grants", {}).values())
        assert len(grants) == 1
        row = grants[0]
        # New grants: hash is set, plaintext is None
        assert row.get("access_token_hash") is not None, "access_token_hash must be stored"
        assert row.get("access_token") is None, "plaintext access_token must NOT be stored for new grants"

    def test_plaintext_access_token_returned_only_once_on_grant_creation(
        self,
        client: TestClient,
        mem_store: dict,
    ) -> None:
        """approve_request returns the plaintext token; subsequent revoke does not re-emit it."""
        session_id, slug, request_id = self._setup_passport_and_request(client, mem_store)

        approve_resp = client.post(f"/api/v1/student/access-requests/{request_id}/approve")
        assert approve_resp.status_code == 200, approve_resp.text
        grant = approve_resp.json()

        # Plaintext must be present in the approve response
        assert grant["access_token"] is not None
        assert grant["access_token"].startswith("vbpa_")

        # Revoke — should NOT re-expose the plaintext token
        revoke_resp = client.post(f"/api/v1/student/access-grants/{grant['id']}/revoke")
        assert revoke_resp.status_code == 200, revoke_resp.text
        assert revoke_resp.json()["access_token"] is None, (
            "Plaintext token must not be returned on revoke or subsequent reads"
        )

    def test_protected_evidence_accessible_with_plaintext_token(
        self,
        client: TestClient,
        mem_store: dict,
    ) -> None:
        """Recruiter can access evidence using the plaintext token returned on approval."""
        session_id, slug, request_id = self._setup_passport_and_request(client, mem_store)

        approve_resp = client.post(f"/api/v1/student/access-requests/{request_id}/approve")
        plaintext = approve_resp.json()["access_token"]
        assert plaintext is not None

        evidence_resp = client.get(f"/api/v1/public/access/{plaintext}/evidence")
        assert evidence_resp.status_code == 200, evidence_resp.text

    def test_hash_in_db_matches_sha256_of_plaintext(
        self,
        client: TestClient,
        mem_store: dict,
    ) -> None:
        """The stored hash equals sha256(plaintext_token)."""
        session_id, slug, request_id = self._setup_passport_and_request(client, mem_store)

        approve_resp = client.post(f"/api/v1/student/access-requests/{request_id}/approve")
        plaintext = approve_resp.json()["access_token"]

        row = next(iter(mem_store.get("evidence_access_grants", {}).values()))
        expected_hash = sha256(plaintext.encode()).hexdigest()
        assert row["access_token_hash"] == expected_hash

    def test_revoked_grant_still_blocks_access(
        self,
        client: TestClient,
        mem_store: dict,
    ) -> None:
        """After revocation, the plaintext token is rejected even though it was valid."""
        session_id, slug, request_id = self._setup_passport_and_request(client, mem_store)

        grant = client.post(f"/api/v1/student/access-requests/{request_id}/approve").json()
        plaintext = grant["access_token"]
        client.post(f"/api/v1/student/access-grants/{grant['id']}/revoke")

        resp = client.get(f"/api/v1/public/access/{plaintext}/evidence")
        assert resp.status_code == 403

    def test_protected_evidence_response_does_not_contain_access_token(
        self,
        client: TestClient,
        mem_store: dict,
    ) -> None:
        """The protected evidence response body must never contain an access_token field."""
        session_id, slug, request_id = self._setup_passport_and_request(client, mem_store)

        plaintext = client.post(
            f"/api/v1/student/access-requests/{request_id}/approve"
        ).json()["access_token"]

        evidence_resp = client.get(f"/api/v1/public/access/{plaintext}/evidence")
        assert evidence_resp.status_code == 200, evidence_resp.text
        assert "access_token" not in json.dumps(evidence_resp.json())


# ═══════════════════════════════════════════════════════════════════════════
# Session token mechanics
# ═══════════════════════════════════════════════════════════════════════════

class TestRecruiterSessionMechanics:
    """Test the session token creation and validation flow."""

    def test_create_session_returns_vrec_token(self, client: TestClient, mem_store: dict) -> None:
        resp = client.post(
            "/api/v1/public/recruiter/sessions",
            json={"requester_email": OWNER_EMAIL},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["session_token"].startswith("vrec_")
        assert body["requester_email"] == OWNER_EMAIL
        assert body["expires_in_days"] == 30

    def test_session_token_is_stored_as_hash_not_plaintext(
        self, client: TestClient, mem_store: dict
    ) -> None:
        resp = client.post(
            "/api/v1/public/recruiter/sessions",
            json={"requester_email": OWNER_EMAIL},
        )
        plaintext = resp.json()["session_token"]
        tokens = list(mem_store.get("recruiter_session_tokens", {}).values())
        assert len(tokens) == 1
        # Hash is stored
        expected_hash = sha256(plaintext.encode()).hexdigest()
        assert tokens[0]["token_hash"] == expected_hash
        # Plaintext is NOT stored
        assert "token_plaintext" not in tokens[0]
        assert tokens[0].get("token") != plaintext

    def test_invalid_token_returns_401(self, client: TestClient, mem_store: dict) -> None:
        resp = client.get(
            "/api/v1/public/recruiter/saved-passports",
            headers={"X-Recruiter-Token": "vrec_invalid_garbage"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "recruiter_session_invalid"

    def test_email_normalization_in_session(self, client: TestClient, mem_store: dict) -> None:
        """Session email is lowercased and trimmed."""
        resp = client.post(
            "/api/v1/public/recruiter/sessions",
            json={"requester_email": "  OWNER@Example.COM  "},
        )
        assert resp.status_code == 201
        assert resp.json()["requester_email"] == "owner@example.com"
