"""Passport visibility master-switch contract (Private 🔒 / Public 🌍).

The canonical server-side visibility state is ``vbr_work_passports.is_published``.
These tests pin the product contract for the student-facing visibility control:

- The student toggles their OWN passport Private ⇄ Public via the existing
  publish/unpublish endpoints; the state persists and is idempotent.
- Private is enforced SERVER-SIDE on every public surface: public passport,
  public skill report, beam short links, canonical project report links, the
  report view tracker, legacy report tokens, and the legacy session passport
  surface. All fail closed with a generic 404 and no candidate data.
- Toggling visibility never deletes anything: slugs, beam links, and report
  tokens are preserved, so Public restores exactly the prior selections.
- Tenant isolation: one user's toggle can never affect another user.

All storage is in-memory (dict mode). No network, no LLM calls.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.services.passport_visibility import (
    owner_has_canonical_passport,
    owner_passport_blocks_public_access,
    owner_passport_is_public,
)

from tests.conftest import seed_published_passport
from tests.test_vbr_project_defense import (
    OTHER_USER_ID,
    USER_ID,
    _create_project_defense,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def pipeline_db() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict, pipeline_db: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: pipeline_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _as_user(user_id: str) -> None:
    app.dependency_overrides[get_current_user_id] = lambda: user_id


def _publish(client: TestClient):
    return client.post("/api/v1/student/vbr/passport/publish", json={})


def _unpublish(client: TestClient):
    return client.post("/api/v1/student/vbr/passport/unpublish")


def _status(client: TestClient):
    return client.get("/api/v1/student/vbr/passport/status")


def _public_passport(client: TestClient, slug: str):
    return client.get(f"/api/v1/public/p/{slug}")


def _public_skill_report(client: TestClient, slug: str, skill: str):
    return client.get(f"/api/v1/public/p/{slug}/skills/{skill}")


def _publish_project_report(client: TestClient, project_id: str):
    return client.post(f"/api/v1/student/vbr/projects/{project_id}/public-report")


def _public_report(client: TestClient, token: str):
    return client.get(f"/api/v1/public/vbr/reports/{token}")


def _record_view(client: TestClient, token: str):
    return client.post(f"/api/v1/public/vbr/reports/{token}/view", json={"source": "direct"})


def _create_beam_link(client: TestClient):
    return client.post("/api/v1/student/vbr/beam/links", json=None)


def _resolve_beam(client: TestClient, code: str):
    return client.get(f"/api/v1/public/beam/{code}")


def _published_setup(client: TestClient) -> tuple[str, str, str]:
    """Publish a project report + passport + beam link. → (slug, token, beam_code)."""
    project_id = _create_project_defense(client).json()["project"]["id"]
    token = _publish_project_report(client, project_id).json()["public_token"]
    slug = _publish(client).json()["public_slug"]
    beam_code = _create_beam_link(client).json()["code"]
    assert slug and token and beam_code
    return slug, token, beam_code


# ── Own-passport toggling + persistence ──────────────────────────────────────


def test_student_can_toggle_private_to_public_and_back(client: TestClient) -> None:
    assert _status(client).json()["is_published"] is False

    published = _publish(client).json()
    assert published["is_published"] is True
    assert published["public_slug"]
    assert _status(client).json()["is_published"] is True

    unpublished = _unpublish(client).json()
    assert unpublished["is_published"] is False
    assert unpublished["public_slug"] is None
    assert _status(client).json()["is_published"] is False


def test_visibility_persists_and_slug_is_stable_across_toggles(client: TestClient, mem_store: dict) -> None:
    slug = _publish(client).json()["public_slug"]
    _unpublish(client)

    row = next(iter(mem_store["vbr_work_passports"].values()))
    assert row["is_published"] is False
    assert row["public_slug"] == slug  # never cleared → link restored on republish

    assert _publish(client).json()["public_slug"] == slug


def test_status_exposes_preview_path_while_private(client: TestClient) -> None:
    slug = _publish(client).json()["public_slug"]
    _unpublish(client)

    body = _status(client).json()
    assert body["is_published"] is False
    assert body["public_path"] is None
    # Owner-only preview path lets the student open/verify the private-state page.
    assert body["preview_public_path"] == f"/p/{slug}"


# ── Private state: every public surface fails closed ─────────────────────────


def test_private_passport_blocks_public_passport_and_skill_report(client: TestClient) -> None:
    slug, _token, _code = _published_setup(client)
    _unpublish(client)
    app.dependency_overrides.pop(get_current_user_id, None)

    res = _public_passport(client, slug)
    assert res.status_code == 404
    # Generic non-disclosing 404: no identity, project, or skill data.
    assert "candidate_name" not in res.text
    assert res.json()["detail"]["code"] == "vbr_work_passport_not_found"

    assert _public_skill_report(client, slug, "python").status_code == 404


def test_private_passport_blocks_beam_resolution(client: TestClient) -> None:
    _slug, _token, code = _published_setup(client)
    _unpublish(client)
    app.dependency_overrides.pop(get_current_user_id, None)

    res = _resolve_beam(client, code)
    assert res.status_code == 404
    assert "public_passport_path" not in res.text


def test_private_passport_blocks_published_report_and_view_tracker(
    client: TestClient, mem_store: dict
) -> None:
    _slug, token, _code = _published_setup(client)
    _unpublish(client)
    app.dependency_overrides.pop(get_current_user_id, None)

    assert _public_report(client, token).status_code == 404
    # The view tracker is a deliberate content-free 200 (never a token oracle);
    # while Private it must record nothing.
    res = _record_view(client, token)
    assert res.status_code == 200
    assert res.json() == {"recorded": False}
    assert not mem_store.get("vbr_project_report_views")


def test_draft_reports_stay_private_in_every_mode(client: TestClient) -> None:
    project_id = _create_project_defense(client).json()["project"]["id"]
    _publish(client)  # passport Public, but the report was never published
    app.dependency_overrides.pop(get_current_user_id, None)

    # No token was ever minted for this project; nothing to fetch by design —
    # probing an arbitrary token still 404s.
    assert _public_report(client, "not-a-real-token-aaaaaaaaaaaaaaaa").status_code == 404
    assert project_id  # the draft project itself is untouched


def test_report_selections_survive_visibility_toggles(client: TestClient, mem_store: dict) -> None:
    _slug, token, code = _published_setup(client)

    _unpublish(client)
    project = next(iter(mem_store["vbr_projects"].values()))
    assert project["public_report_token"] == token  # selection preserved
    beam_row = next(iter(mem_store["beam_links"].values()))
    assert beam_row["status"] == "active"  # beam link dormant, not revoked

    _publish(client)
    app.dependency_overrides.pop(get_current_user_id, None)

    # Re-publication restores the exact same surfaces without re-selection.
    assert _public_report(client, token).status_code == 200
    resolved = _resolve_beam(client, code)
    assert resolved.status_code == 200
    assert resolved.json()["public_passport_path"]


def test_legacy_report_token_respects_visibility(client: TestClient, mem_store: dict) -> None:
    project_id = _create_project_defense(client).json()["project"]["id"]
    mem_store.setdefault("vbr_reports", {})["legacy-report-1"] = {
        "id": "legacy-report-1",
        "project_id": project_id,
        "status": "published",
        "public_token": "legacy-token-123",
        "published_at": "2026-01-01T00:00:00+00:00",
        "body": {"summary": {"project_title": "Legacy"}, "claims": []},
    }
    app.dependency_overrides.pop(get_current_user_id, None)

    # Owner has no published passport → legacy link dark.
    assert client.get("/api/v1/public/vbr/legacy-reports/legacy-token-123").status_code == 404

    # Passport Public → legacy link resolves again.
    seed_published_passport(mem_store, USER_ID)
    assert client.get("/api/v1/public/vbr/legacy-reports/legacy-token-123").status_code == 200

    # Passport Private again → dark again (reversible, nothing deleted).
    seed_published_passport(mem_store, USER_ID, is_published=False)
    assert client.get("/api/v1/public/vbr/legacy-reports/legacy-token-123").status_code == 404
    assert mem_store["vbr_reports"]["legacy-report-1"]["public_token"] == "legacy-token-123"


def test_legacy_session_passport_surface_respects_canonical_visibility(
    client: TestClient, mem_store: dict
) -> None:
    # Legacy surface row is is_public=true, but the owner's canonical Passport
    # is Private → every legacy public route must 404 without candidate data.
    mem_store.setdefault("public_work_passports", {})["legacy-pass-1"] = {
        "id": "legacy-pass-1",
        "user_id": USER_ID,
        "proof_session_id": "session-1",
        "public_slug": "legacy-slug-1",
        "is_public": True,
    }
    seed_published_passport(mem_store, USER_ID, is_published=False)
    app.dependency_overrides.pop(get_current_user_id, None)

    for path in (
        "/api/v1/public/passports/legacy-slug-1",
        "/api/v1/public/passports/legacy-slug-1/recruiter-view",
        "/api/v1/public/passports/legacy-slug-1/status",
        "/api/v1/public/passports/legacy-slug-1/skill-evidence-timeline",
        "/api/v1/public/passports/legacy-slug-1/export",
        "/api/v1/public/passports/legacy-slug-1/github-proofs",
    ):
        res = client.get(path)
        assert res.status_code == 404, path
        assert "Ada" not in res.text, path  # no identity leak in the 404 body


def test_legacy_session_passport_surface_is_retired_for_canonical_owners(
    client: TestClient, mem_store: dict
) -> None:
    """G3: the legacy session-passport surface predates the disclosure system
    entirely, so ANY canonical Passport row — even a PUBLIC one — retires it:
    every legacy public route 404s indistinguishably. The owner's only public
    surface is the canonical, disclosure-enforced one."""
    mem_store.setdefault("public_work_passports", {})["legacy-pass-2"] = {
        "id": "legacy-pass-2",
        "user_id": USER_ID,
        "proof_session_id": "session-2",
        "public_slug": "legacy-slug-2",
        "is_public": True,
    }
    seed_published_passport(mem_store, USER_ID, is_published=True)  # PUBLIC canonical row
    app.dependency_overrides.pop(get_current_user_id, None)

    for path in (
        "/api/v1/public/passports/legacy-slug-2",
        "/api/v1/public/passports/legacy-slug-2/recruiter-view",
        "/api/v1/public/passports/legacy-slug-2/status",
        "/api/v1/public/passports/legacy-slug-2/skill-evidence-timeline",
        "/api/v1/public/passports/legacy-slug-2/export",
        "/api/v1/public/passports/legacy-slug-2/github-proofs",
    ):
        res = client.get(path)
        assert res.status_code == 404, path
        assert "Ada" not in res.text, path  # no identity leak in the 404 body

    # The write-style legacy routes are retired too (request-access / save).
    res = client.post(
        "/api/v1/public/passports/legacy-slug-2/request-access",
        json={
            "requester_name": "Recruiter Person",
            "requester_email": "recruiter@example.com",
            "requested_sections": ["github_analysis"],
        },
    )
    assert res.status_code == 404


def test_public_responses_are_never_cacheable(client: TestClient) -> None:
    """Every /public/ response carries Cache-Control: no-store so browsers and
    CDNs re-check visibility on each open — Public → Private revokes instantly."""
    slug, token, code = _published_setup(client)
    app.dependency_overrides.pop(get_current_user_id, None)

    for res in (
        _public_passport(client, slug),
        _public_report(client, token),
        _resolve_beam(client, code),
        _public_passport(client, "unknown-slug"),  # 404s must be no-store too
    ):
        assert res.headers.get("Cache-Control") == "no-store"


# ── Tenant isolation ─────────────────────────────────────────────────────────


def test_toggling_visibility_never_touches_another_tenant(client: TestClient, mem_store: dict) -> None:
    slug_a, token_a, _code_a = _published_setup(client)

    # Another tenant flips their own passport around; A is untouched.
    _as_user(OTHER_USER_ID)
    _publish(client)
    _unpublish(client)

    app.dependency_overrides.pop(get_current_user_id, None)
    assert _public_passport(client, slug_a).status_code == 200
    assert _public_report(client, token_a).status_code == 200

    rows = {r["user_id"]: r for r in mem_store["vbr_work_passports"].values()}
    assert rows[USER_ID]["is_published"] is True
    assert rows[OTHER_USER_ID]["is_published"] is False


def test_unpublish_only_affects_callers_own_passport(client: TestClient, mem_store: dict) -> None:
    slug_a, _token_a, _code_a = _published_setup(client)

    _as_user(OTHER_USER_ID)
    # OTHER user unpublishes while owning nothing: a no-op — never a cross-tenant write.
    res = _unpublish(client)
    assert res.status_code == 200
    assert res.json()["is_published"] is False

    app.dependency_overrides.pop(get_current_user_id, None)
    assert _public_passport(client, slug_a).status_code == 200


# ── Helper-level fail-closed semantics ───────────────────────────────────────


def test_visibility_helpers_fail_closed() -> None:
    store: dict = {}
    assert owner_passport_is_public(store, None) is False
    assert owner_passport_is_public(store, "no-row-user") is False
    assert owner_passport_blocks_public_access(store, "no-row-user") is False  # legacy keeps own gate
    assert owner_has_canonical_passport(store, None) is False
    assert owner_has_canonical_passport(store, "no-row-user") is False

    row = seed_published_passport(store, "u1")
    assert owner_passport_is_public(store, "u1") is True
    assert owner_passport_blocks_public_access(store, "u1") is False
    # The retirement gate trips on ANY canonical row — public or private.
    assert owner_has_canonical_passport(store, "u1") is True

    row["is_published"] = False
    assert owner_passport_is_public(store, "u1") is False
    assert owner_passport_blocks_public_access(store, "u1") is True
    assert owner_has_canonical_passport(store, "u1") is True
