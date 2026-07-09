"""Tests for standalone GitHub proof backend."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.github_proof_service import GitHubProofService


USER_ID = "00000000-0000-0000-0000-000000000042"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000099"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_session(mem_store: dict, *, user_id: str = USER_ID, slug: str = "github-passport") -> dict[str, str]:
    session_id = str(uuid4())
    passport_id = str(uuid4())
    mem_store.setdefault("extension_proof_sessions", {})[session_id] = {
        "id": session_id,
        "user_id": user_id,
        "status": "completed",
        "website_url": "https://example.edu/project",
        "created_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("public_work_passports", {})[passport_id] = {
        "id": passport_id,
        "user_id": user_id,
        "proof_session_id": session_id,
        "public_slug": slug,
        "is_public": True,
        "public_title": "Public Work Passport",
        "public_summary": "Public-safe summary.",
        "field": "Computer Science",
        "visible_sections": ["summary", "skills"],
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
        "access_token": "passport-secret-token",
    }
    return {"session_id": session_id, "passport_id": passport_id}


def _seed_grant(
    mem_store: dict,
    *,
    user_id: str = USER_ID,
    session_id: str,
    passport_id: str,
    access_token: str = "grant-token",
    granted_sections: list[str] | None = None,
    revoked_at: str | None = None,
    expires_at: datetime | None = None,
) -> str:
    request_id = str(uuid4())
    grant_id = str(uuid4())
    mem_store.setdefault("evidence_access_requests", {})[request_id] = {
        "id": request_id,
        "user_id": user_id,
        "proof_session_id": session_id,
        "passport_id": passport_id,
        "requester_profile_id": None,
        "requester_name": "Recruiter Person",
        "requester_email": "recruiter@example.org",
        "requester_organization": "Example Org",
        "requester_role": "recruiter",
        "request_reason": "Review candidate",
        "status": "approved",
        "requested_sections": granted_sections or ["github_analysis"],
        "decision_notes": None,
        "decided_at": datetime.now(UTC).isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("evidence_access_grants", {})[grant_id] = {
        "id": grant_id,
        "access_request_id": request_id,
        "user_id": user_id,
        "proof_session_id": session_id,
        "passport_id": passport_id,
        "requester_email": "recruiter@example.org",
        "granted_sections": granted_sections or ["github_analysis"],
        "access_token": access_token,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "revoked_at": revoked_at,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    return access_token


def _seed_analysis_result() -> dict[str, object]:
    return {
        "status": "success",
        "detected_stack": ["Python", "FastAPI", "React", "Docker"],
        "detected_features": ["readme", "testing", "deployment", "api_framework"],
        "matched_claimed_skills": ["FastAPI"],
        "weakly_matched_claimed_skills": ["React"],
        "missing_claimed_skills": [],
        "evidence_files": ["README.md", "requirements.txt", "Dockerfile"],
        "confidence_score": 72.0,
        "warnings": [],
        "recruiter_summary": "Standalone GitHub proof supports backend and frontend work.",
        "created_at": datetime.now(UTC).isoformat(),
    }


def _submit(client: TestClient, repo_url: str = "https://github.com/example/project", **overrides: object) -> dict:
    payload = {
        "repo_url": repo_url,
        "proof_session_id": overrides.pop("proof_session_id", None),
        "submitted_skill_claims": overrides.pop("submitted_skill_claims", ["FastAPI", "React"]),
        **overrides,
    }
    response = client.post("/api/v1/student/github-proofs", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _analyze(monkeypatch: pytest.MonkeyPatch, response: dict[str, object] | None = None, *, raises: Exception | None = None) -> None:
    if raises is not None:
        def _raise(*args: object, **kwargs: object) -> dict[str, object]:
            raise raises
        monkeypatch.setattr("app.services.github_proof_service.analyze_github_repo", _raise)
    else:
        monkeypatch.setattr("app.services.github_proof_service.analyze_github_repo", lambda *args, **kwargs: response or _seed_analysis_result())


def test_student_can_submit_github_proof(client: TestClient, mem_store: dict) -> None:
    ids = _seed_session(mem_store)

    saved = _submit(client, proof_session_id=ids["session_id"])

    assert saved["repo_owner"] == "example"
    assert saved["repo_name"] == "project"
    assert saved["status"] == "submitted"
    assert saved["proof_session_id"] == ids["session_id"]
    assert len(mem_store["github_proof_submissions"]) == 1


def test_github_url_parser_extracts_owner_and_repo() -> None:
    service = GitHubProofService({})

    repo_ref = service.parse_github_repo_url("https://github.com/example/project/blob/main/app.py")

    assert repo_ref is not None
    assert repo_ref.owner == "example"
    assert repo_ref.repo == "project"
    assert repo_ref.branch == "main"
    assert repo_ref.file_path == "app.py"


def test_invalid_github_url_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/student/github-proofs",
        json={"repo_url": "https://example.com/not-github", "submitted_skill_claims": []},
    )

    assert response.status_code == 422


def test_student_can_list_own_github_proofs(client: TestClient, mem_store: dict) -> None:
    ids = _seed_session(mem_store)
    _submit(client, proof_session_id=ids["session_id"], repo_url="https://github.com/example/own-project")
    other_session = _seed_session(mem_store, user_id=OTHER_USER_ID, slug="other-passport")
    other_proof_id = str(uuid4())
    mem_store.setdefault("github_proof_submissions", {})[other_proof_id] = {
        "id": other_proof_id,
        "user_id": OTHER_USER_ID,
        "proof_session_id": other_session["session_id"],
        "repo_url": "https://github.com/example/other-project",
        "repo_owner": "example",
        "repo_name": "other-project",
        "default_branch": "main",
        "visibility": "public",
        "status": "submitted",
        "submitted_skill_claims": [],
        "detected_skills": [],
        "repo_metadata": {},
        "analysis_summary": None,
        "evidence_strength": None,
        "confidence_score": None,
        "risk_flags": [],
        "missing_evidence": [],
        "public_safe_summary": None,
        "analysis_snapshot": {},
        "last_analyzed_at": None,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }

    response = client.get("/api/v1/student/github-proofs")

    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["repo_name"] == "own-project"


def test_student_cannot_access_another_students_github_proof(client: TestClient, mem_store: dict) -> None:
    other_ids = _seed_session(mem_store, user_id=OTHER_USER_ID, slug="other-passport")
    other_proof_id = str(uuid4())
    mem_store.setdefault("github_proof_submissions", {})[other_proof_id] = {
        "id": other_proof_id,
        "user_id": OTHER_USER_ID,
        "proof_session_id": other_ids["session_id"],
        "repo_url": "https://github.com/example/private-project",
        "repo_owner": "example",
        "repo_name": "private-project",
        "default_branch": "main",
        "visibility": "public",
        "status": "submitted",
        "submitted_skill_claims": [],
        "detected_skills": [],
        "repo_metadata": {},
        "analysis_summary": None,
        "evidence_strength": None,
        "confidence_score": None,
        "risk_flags": [],
        "missing_evidence": [],
        "public_safe_summary": None,
        "analysis_snapshot": {},
        "last_analyzed_at": None,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }

    response = client.get(f"/api/v1/student/github-proofs/{other_proof_id}")

    assert response.status_code == 404


def test_analyze_github_proof_updates_status_and_signals(
    client: TestClient,
    mem_store: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = _seed_session(mem_store)
    saved = _submit(client, proof_session_id=ids["session_id"])
    _analyze(monkeypatch)

    response = client.post(f"/api/v1/student/github-proofs/{saved['id']}/analyze")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "analyzed"
    assert payload["evidence_strength"] in {"strong", "partial", "weak"}
    assert payload["confidence_score"] is not None
    assert "FastAPI" in payload["detected_skills"]
    assert "React" in payload["detected_skills"]
    assert len(mem_store.get("notification_events", {})) == 1


def test_github_api_unavailable_returns_controlled_fallback(
    client: TestClient,
    mem_store: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = _seed_session(mem_store)
    saved = _submit(client, proof_session_id=ids["session_id"])
    _analyze(monkeypatch, raises=RuntimeError("network down"))

    response = client.post(f"/api/v1/student/github-proofs/{saved['id']}/analyze")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] in {"failed", "needs_more_evidence"}
    assert "GitHub analysis is limited because GitHub API is not configured." in json.dumps(payload)


def test_public_github_proofs_endpoint_excludes_internal_data(
    client: TestClient,
    mem_store: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = _seed_session(mem_store)
    saved = _submit(client, proof_session_id=ids["session_id"])
    _analyze(monkeypatch)
    client.post(f"/api/v1/student/github-proofs/{saved['id']}/analyze")

    response = client.get("/api/v1/public/passports/github-passport/github-proofs")

    assert response.status_code == 200, response.text
    serialized = json.dumps(response.json()).lower()
    assert "repo_metadata" not in serialized
    assert "analysis_snapshot" not in serialized
    assert "access_token" not in serialized
    assert "private transcript" not in serialized


def test_protected_github_proofs_endpoint_respects_granted_sections(
    client: TestClient,
    mem_store: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = _seed_session(mem_store)
    saved = _submit(client, proof_session_id=ids["session_id"])
    _analyze(monkeypatch)
    client.post(f"/api/v1/student/github-proofs/{saved['id']}/analyze")
    allowed_token = _seed_grant(mem_store, session_id=ids["session_id"], passport_id=ids["passport_id"], access_token="allowed-token", granted_sections=["github_analysis"])
    denied_token = _seed_grant(mem_store, session_id=ids["session_id"], passport_id=ids["passport_id"], access_token="denied-token", granted_sections=["project_defense_summary"])

    allowed = client.get(f"/api/v1/public/access/{allowed_token}/github-proofs")
    denied = client.get(f"/api/v1/public/access/{denied_token}/github-proofs")

    assert allowed.status_code == 200, allowed.text
    assert len(allowed.json()) == 1
    assert denied.status_code == 403


def test_github_proof_contributes_to_skill_evidence_timeline(
    client: TestClient,
    mem_store: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = _seed_session(mem_store)
    saved = _submit(client, proof_session_id=ids["session_id"])
    _analyze(monkeypatch)
    client.post(f"/api/v1/student/github-proofs/{saved['id']}/analyze")

    response = client.get(f"/api/v1/student/extension-proof/sessions/{ids['session_id']}/skill-evidence-timeline")

    assert response.status_code == 200, response.text
    payload = response.json()
    fastapi_skill = next(skill for skill in payload["skills"] if skill["skill_name"] == "FastAPI")
    assert "github" in fastapi_skill["evidence_sources"]
    assert any(item["evidence_type"] == "github" for item in fastapi_skill["evidence_items"])


def test_work_passport_status_includes_github_proof_steps(
    client: TestClient,
    mem_store: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = _seed_session(mem_store)
    saved = _submit(client, proof_session_id=ids["session_id"])
    _analyze(monkeypatch)
    client.post(f"/api/v1/student/github-proofs/{saved['id']}/analyze")

    response = client.get(f"/api/v1/student/extension-proof/sessions/{ids['session_id']}/work-passport-status")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "github_proof_added" in payload["completed_steps"]
    assert "github_proof_analyzed" in payload["completed_steps"]
    assert "add_github_proof" not in payload["missing_steps"]


def test_submit_github_proof_sends_json_safe_payload_to_supabase() -> None:
    mock_client = MagicMock()
    select_result = MagicMock()
    select_result.data = []
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = select_result

    upsert_result = MagicMock()
    upsert_result.data = [
        {
            "id": str(uuid4()),
            "user_id": USER_ID,
            "proof_session_id": None,
            "repo_url": "https://github.com/example/project",
            "repo_owner": "example",
            "repo_name": "project",
            "default_branch": "main",
            "visibility": "public",
            "status": "submitted",
            "submitted_skill_claims": [],
            "detected_skills": [],
            "repo_metadata": {},
            "analysis_summary": None,
            "evidence_strength": None,
            "confidence_score": None,
            "risk_flags": [],
            "missing_evidence": [],
            "public_safe_summary": None,
            "analysis_snapshot": {},
            "last_analyzed_at": None,
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
    ]
    mock_client.table.return_value.upsert.return_value.execute.return_value = upsert_result

    GitHubProofService(mock_client).submit_github_proof(USER_ID, "https://github.com/example/project")

    payload = mock_client.table.return_value.upsert.call_args[0][0]
    json.dumps(payload)
    assert isinstance(payload["created_at"], str)
    assert isinstance(payload["updated_at"], str)
    assert payload["last_analyzed_at"] is None


def test_no_project_specific_hardcoding() -> None:
    source = inspect.getsource(GitHubProofService).lower()

    assert "boston" not in source
    assert "react demo" not in source
    assert "repo name" not in source


# ── Fresh-user provisioning & safe errors ─────────────────────────────────────


FRESH_USER_ID = "00000000-0000-0000-0000-0000000000aa"


def test_fresh_user_can_submit_standalone_github_proof(client: TestClient, mem_store: dict) -> None:
    """A brand-new user with no session and no public.users row can submit."""
    saved = _submit(
        client,
        repo_url="https://github.com/machackgo/boston-smart-accident-risk-rerouting-google-cloud",
        submitted_skill_claims=["Python", "Machine Learning", "FastAPI", "Google Cloud"],
    )

    assert saved["status"] == "submitted"
    assert saved["repo_owner"] == "machackgo"
    assert saved["proof_session_id"] is None
    # The submission owns exactly one proof, attributed to the caller.
    proofs = list(mem_store["github_proof_submissions"].values())
    assert len(proofs) == 1
    assert proofs[0]["user_id"] == USER_ID


def test_submit_provisions_the_callers_own_user_row(client: TestClient, mem_store: dict) -> None:
    """The FK-parent public.users row is created for the authenticated caller."""
    assert "users" not in mem_store or USER_ID not in mem_store.get("users", {})

    _submit(client, repo_url="https://github.com/example/fresh-repo", submitted_skill_claims=[])

    users = mem_store["users"]
    assert USER_ID in users
    assert users[USER_ID]["id"] == USER_ID
    assert users[USER_ID]["role"] == "student"
    # Only the caller's own row is provisioned — no other tenant is touched.
    assert list(users.keys()) == [USER_ID]


def test_submit_provisioning_uses_verified_email_claim() -> None:
    """When the JWT email claim is known, it seeds the provisioned users row."""
    store: dict = {}
    GitHubProofService(store).submit_github_proof(
        FRESH_USER_ID,
        "https://github.com/example/fresh-repo",
        email="fresh.user@example.com",
    )

    assert store["users"][FRESH_USER_ID]["email"] == "fresh.user@example.com"


def test_fresh_user_proof_is_isolated_from_other_users(mem_store: dict) -> None:
    """User B's submitted proof is invisible to User A and vice versa."""
    # User A submits.
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    with TestClient(app) as a_client:
        _submit(a_client, repo_url="https://github.com/example/user-a-repo", submitted_skill_claims=[])

    # User B submits a different repo.
    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    with TestClient(app) as b_client:
        _submit(b_client, repo_url="https://github.com/example/user-b-repo", submitted_skill_claims=[])
        b_rows = b_client.get("/api/v1/student/github-proofs").json()

    # User A lists again.
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    with TestClient(app) as a_client:
        a_rows = a_client.get("/api/v1/student/github-proofs").json()

    app.dependency_overrides.clear()

    assert [row["repo_name"] for row in b_rows] == ["user-b-repo"]
    assert [row["repo_name"] for row in a_rows] == ["user-a-repo"]


def test_submit_provisions_user_row_via_real_client_insert() -> None:
    """Against a real (non-dict) client, a missing users row is inserted once."""
    mock_client = MagicMock()
    empty = MagicMock()
    empty.data = []
    # users existence check: .select("id").eq("id", ...).limit(1).execute()
    mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = empty
    # _rows_for_user: .select("*").eq("user_id", ...).execute()
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = empty

    upsert_result = MagicMock()
    upsert_result.data = [{"id": str(uuid4()), "user_id": FRESH_USER_ID, "repo_url": "https://github.com/example/project", "status": "submitted", "created_at": datetime.now(UTC).isoformat(), "updated_at": datetime.now(UTC).isoformat()}]
    mock_client.table.return_value.upsert.return_value.execute.return_value = upsert_result

    GitHubProofService(mock_client).submit_github_proof(
        FRESH_USER_ID, "https://github.com/example/project", email="fresh@example.com"
    )

    insert_payload = mock_client.table.return_value.insert.call_args[0][0]
    assert insert_payload["id"] == FRESH_USER_ID
    assert insert_payload["email"] == "fresh@example.com"
    assert insert_payload["role"] == "student"


def test_submit_foreign_key_error_returns_safe_conflict(client: TestClient) -> None:
    """A residual FK violation surfaces a clean 409 — never a raw 500 traceback."""
    from app.db.supabase import SupabaseFKError

    def _boom(*args: object, **kwargs: object) -> None:
        raise SupabaseFKError("INSERT users failed: foreign-key constraint")

    original = GitHubProofService._ensure_user_row
    GitHubProofService._ensure_user_row = _boom  # type: ignore[assignment]
    try:
        response = client.post(
            "/api/v1/student/github-proofs",
            json={"repo_url": "https://github.com/example/project", "submitted_skill_claims": []},
        )
    finally:
        GitHubProofService._ensure_user_row = original  # type: ignore[assignment]

    assert response.status_code == 409
    body = response.json()
    assert body["detail"]["code"] == "github_proof_account_not_ready"
    assert "traceback" not in json.dumps(body).lower()


def test_submit_database_outage_returns_safe_503(client: TestClient) -> None:
    """A generic Supabase failure maps to a safe 503, not a leaky 500."""
    from app.db.supabase import SupabaseConnectionError

    def _boom(*args: object, **kwargs: object) -> None:
        raise SupabaseConnectionError("network error")

    original = GitHubProofService._ensure_user_row
    GitHubProofService._ensure_user_row = _boom  # type: ignore[assignment]
    try:
        response = client.post(
            "/api/v1/student/github-proofs",
            json={"repo_url": "https://github.com/example/project", "submitted_skill_claims": []},
        )
    finally:
        GitHubProofService._ensure_user_row = original  # type: ignore[assignment]

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "github_proof_unavailable"


def test_classify_db_error_detects_foreign_key_violation() -> None:
    from app.db.supabase import SupabaseAPIError, SupabaseFKError
    from app.services.github_proof_service import _classify_db_error

    fk = _classify_db_error(Exception('code 23503 violates foreign key constraint'), "INSERT", "users")
    assert isinstance(fk, SupabaseFKError)

    other = _classify_db_error(Exception("bad request 400"), "UPSERT", "github_proof_submissions")
    assert isinstance(other, SupabaseAPIError)
