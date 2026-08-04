"""Tests for Proof Artifact Retention (migration 056).

Covers the security spine of retained original proof artifacts:

  * metadata registration is safe (allowlist DTO, no storage paths)
  * owner can access owner-only retained artifacts
  * an authenticated non-owner can access ONLY recruiter_safe / public_safe
  * anonymous callers can access ONLY public_safe
  * expired / not-retained / unknown → the SAME indistinct 404
  * signed URLs are short-lived (≤ 300 s) and never expose the storage path
  * website replay serves ONLY a genuinely retained replay artifact
  * document upload retains the original; gated download honours consent
  * no raw storage path appears in ANY API response

All storage is in-memory (dict mode). No network / LLM calls.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_optional_user_id, get_pipeline_db
from app.main import app
from app.services import proof_artifact_service as artifacts

from tests.conftest import seed_published_passport

OWNER = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict):
    """TestClient whose caller identity is switchable per request."""
    caller: dict = {"required": OWNER, "optional": OWNER}
    app.dependency_overrides[get_current_user_id] = lambda: caller["required"]
    app.dependency_overrides[get_optional_user_id] = lambda: caller["optional"]
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: {}
    test_client = TestClient(app)
    test_client.caller = caller  # type: ignore[attr-defined]
    yield test_client
    app.dependency_overrides.clear()


def _as(client, user_id):
    client.caller["required"] = user_id or OWNER
    client.caller["optional"] = user_id


def _register(db, *, policy="owner_only", data=b"original-bytes", artifact_type="document_original",
              proof_type="document", proof_id="doc-1", **kwargs):
    row = artifacts.register_artifact_with_bytes(
        db,
        owner_user_id=OWNER,
        proof_type=proof_type,
        artifact_type=artifact_type,
        data=data,
        file_name="report.pdf",
        mime_type="application/pdf",
        proof_id=proof_id,
        access_policy=policy,
        **kwargs,
    )
    assert row is not None
    return row


# ── Registration + safe DTO ───────────────────────────────────────────────────

def test_registration_creates_safe_metadata(mem_store):
    row = _register(mem_store)
    assert row["retained"] is True
    assert row["access_policy"] == "owner_only"
    assert row["size_bytes"] == len(b"original-bytes")
    assert row["mime_type"] == "application/pdf"
    # The row itself stores the private path…
    assert row["storage_path"]
    # …but the ONLY serialization allowed in responses never carries it.
    dto = artifacts.safe_artifact_dto(row)
    assert "storage_path" not in dto
    assert "storage_bucket" not in dto
    assert "owner_user_id" not in dto


def test_registration_rejects_unknown_types(mem_store):
    assert (
        artifacts.register_artifact_with_bytes(
            mem_store,
            owner_user_id=OWNER,
            proof_type="document",
            artifact_type="not_a_real_type",
            data=b"x",
            file_name="a.pdf",
            mime_type="application/pdf",
        )
        is None
    )


def test_unsafe_filenames_are_collapsed(mem_store):
    row = artifacts.register_artifact_with_bytes(
        mem_store,
        owner_user_id=OWNER,
        proof_type="document",
        artifact_type="document_original",
        data=b"x",
        file_name="../../etc/passwd my report?.pdf",
        mime_type="application/pdf",
    )
    assert row is not None
    assert "/" not in row["file_name"]
    assert ".." not in row["file_name"]


# ── Access model ──────────────────────────────────────────────────────────────

def test_owner_can_view_and_download_owner_only_artifact(client, mem_store):
    row = _register(mem_store)
    view = client.get(f"/api/v1/proofs/artifacts/{row['id']}/view")
    assert view.status_code == 200
    assert view.content == b"original-bytes"
    assert view.headers["content-type"].startswith("application/pdf")

    download = client.get(f"/api/v1/proofs/artifacts/{row['id']}/download")
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]


def test_non_owner_cannot_access_owner_only_artifact(client, mem_store):
    row = _register(mem_store)
    _as(client, OTHER)
    assert client.get(f"/api/v1/proofs/artifacts/{row['id']}/view").status_code == 404
    _as(client, None)  # anonymous
    assert client.get(f"/api/v1/proofs/artifacts/{row['id']}/view").status_code == 404


def _grant_role(db, user_id, role):
    db.setdefault("user_roles", {})[f"{user_id}:{role}"] = {
        "id": f"{user_id}:{role}",
        "user_id": user_id,
        "role": role,
        "scope": "global",
        "scope_id": None,
        "is_active": True,
        "created_at": "2026-01-01T00:00:00Z",
    }


def test_recruiter_safe_denies_plain_student_admits_privileged(client, mem_store):
    # F3 hardening: recruiter_safe is for the owner + privileged viewers only.
    row = _register(mem_store, policy="recruiter_safe")

    # A plain authenticated non-owner (another student, no roles) is denied —
    # they can never pull a peer's recruiter-safe media by guessing its id.
    _as(client, OTHER)
    assert client.get(f"/api/v1/proofs/artifacts/{row['id']}/view").status_code == 404

    # Anonymous is denied too.
    _as(client, None)
    assert client.get(f"/api/v1/proofs/artifacts/{row['id']}/view").status_code == 404

    # A privileged non-owner (recruiter / admin / reviewer) IS admitted.
    for role in ("recruiter", "admin", "reviewer"):
        privileged = f"33333333-3333-3333-3333-33333333333{('recruiter','admin','reviewer').index(role)}"
        _grant_role(mem_store, privileged, role)
        _as(client, privileged)
        assert (
            client.get(f"/api/v1/proofs/artifacts/{row['id']}/view").status_code == 200
        ), f"{role} should access recruiter_safe"


def test_recruiter_safe_access_unit_policy():
    # Direct unit coverage of the closed-policy decision.
    art = {"retained": True, "owner_user_id": OWNER, "access_policy": "recruiter_safe"}
    assert artifacts.can_access_artifact(art, OWNER) is True  # owner
    assert artifacts.can_access_artifact(art, OTHER) is False  # plain student
    assert artifacts.can_access_artifact(art, None) is False  # anonymous
    assert (
        artifacts.can_access_artifact(art, OTHER, caller_is_privileged=True) is True
    )  # recruiter/admin


def test_public_safe_admits_anonymous(client, mem_store):
    # Anonymous access additionally requires the owner's Passport to be Public
    # (the migration-063 master-switch extension to media routes).
    seed_published_passport(mem_store, OWNER)
    row = _register(mem_store, policy="public_safe")
    _as(client, None)
    assert client.get(f"/api/v1/proofs/artifacts/{row['id']}/view").status_code == 200


def test_public_safe_denied_anonymous_while_passport_private(client, mem_store):
    """A Private Passport blacks out even ``public_safe`` artifacts publicly."""
    seed_published_passport(mem_store, OWNER, is_published=False)
    row = _register(mem_store, policy="public_safe")
    _as(client, None)
    assert client.get(f"/api/v1/proofs/artifacts/{row['id']}/view").status_code == 404
    # The owner keeps full access regardless of the public switch.
    _as(client, OWNER)
    assert client.get(f"/api/v1/proofs/artifacts/{row['id']}/view").status_code == 200


def test_expired_artifact_serves_owner_only(client, mem_store):
    row = _register(mem_store, policy="expired")
    assert client.get(f"/api/v1/proofs/artifacts/{row['id']}/view").status_code == 200
    _as(client, OTHER)
    assert client.get(f"/api/v1/proofs/artifacts/{row['id']}/view").status_code == 404


def test_not_retained_artifact_is_indistinct_404_even_for_owner(client, mem_store):
    row = _register(mem_store)
    artifacts.update_artifact(mem_store, row["id"], {"retained": False})
    assert client.get(f"/api/v1/proofs/artifacts/{row['id']}/view").status_code == 404


def test_unknown_artifact_is_indistinct_404(client):
    response = client.get("/api/v1/proofs/artifacts/00000000-0000-0000-0000-000000000000/view")
    assert response.status_code == 404
    assert "storage" not in response.text.lower()


# ── Signed URLs ───────────────────────────────────────────────────────────────

def test_signed_url_is_short_lived_and_pathless(client, mem_store):
    row = _register(mem_store)
    response = client.get(f"/api/v1/proofs/artifacts/{row['id']}/signed-url")
    assert response.status_code == 200
    payload = response.json()
    assert payload["expires_in_seconds"] <= artifacts.SIGNED_URL_MAX_TTL_S
    assert row["storage_path"] not in payload["signed_url"]
    assert "storage_path" not in response.text

    # TTL beyond the cap is rejected at the validation layer.
    too_long = client.get(f"/api/v1/proofs/artifacts/{row['id']}/signed-url", params={"expires_in": 3600})
    assert too_long.status_code == 422


def test_signed_url_is_gated_like_view(client, mem_store):
    row = _register(mem_store)
    _as(client, OTHER)
    assert client.get(f"/api/v1/proofs/artifacts/{row['id']}/signed-url").status_code == 404


# ── Website replay ────────────────────────────────────────────────────────────

def test_website_replay_404_when_nothing_retained(client):
    assert client.get("/api/v1/proofs/website/sess-1/replay").status_code == 404


def test_website_replay_serves_only_genuinely_retained_replay(client, mem_store):
    _register(
        mem_store,
        proof_type="website",
        proof_id="sess-1",
        artifact_type="website_replay_video",
        data=b"webm-bytes",
        policy="owner_only",
    )
    response = client.get("/api/v1/proofs/website/sess-1/replay")
    assert response.status_code == 200
    assert response.content == b"webm-bytes"
    # A non-owner cannot reach an owner-only replay.
    _as(client, OTHER)
    assert client.get("/api/v1/proofs/website/sess-1/replay").status_code == 404


def test_website_replay_ignores_other_artifact_types(client, mem_store):
    # A retained FRAME must not satisfy the replay route.
    _register(
        mem_store,
        proof_type="website",
        proof_id="sess-2",
        artifact_type="website_frame",
        data=b"jpeg-bytes",
    )
    assert client.get("/api/v1/proofs/website/sess-2/replay").status_code == 404


# ── Document upload retention ─────────────────────────────────────────────────

def _upload_document(client, share: bool):
    return client.post(
        "/api/v1/student/document-proofs/upload",
        files={
            "file": (
                "report.md",
                b"# Report\nWe trained a Machine Learning model with scikit-learn "
                b"pipelines and cross-validation.",
                "text/markdown",
            )
        },
        data={"title": "Report", "claimed_skills": "Machine Learning",
              "share_with_recruiters": "true" if share else "false"},
    )


def test_document_upload_retains_original_privately_by_default(client, mem_store):
    response = _upload_document(client, share=False)
    assert response.status_code == 201
    payload = response.json()
    assert payload["original_retained"] is True
    assert payload["original_artifact_id"]
    assert "storage_path" not in response.text

    artifact_id = payload["original_artifact_id"]
    # Owner can open it; nobody else can.
    assert client.get(f"/api/v1/proofs/artifacts/{artifact_id}/download").status_code == 200
    _as(client, OTHER)
    assert client.get(f"/api/v1/proofs/artifacts/{artifact_id}/download").status_code == 404


def test_document_share_consent_opens_recruiter_gated_access(client, mem_store):
    # G1: "share with recruiters" consents to RECRUITERS — the retained
    # original goes recruiter_safe, never public_safe, so anonymous callers
    # (and plain student peers) get the indistinct 404 while an authenticated
    # recruiter streams the bytes.
    seed_published_passport(mem_store, OWNER)
    response = _upload_document(client, share=True)
    artifact_id = response.json()["original_artifact_id"]

    stored = artifacts.get_artifact(mem_store, artifact_id)
    assert stored is not None and stored["access_policy"] == "recruiter_safe"

    _as(client, None)  # anonymous — sharing with recruiters is NOT public
    assert client.get(f"/api/v1/proofs/artifacts/{artifact_id}/view").status_code == 404
    _as(client, OTHER)  # plain student peer — denied too
    assert client.get(f"/api/v1/proofs/artifacts/{artifact_id}/view").status_code == 404

    recruiter = "44444444-4444-4444-4444-444444444444"
    _grant_role(mem_store, recruiter, "recruiter")
    _as(client, recruiter)
    view = client.get(f"/api/v1/proofs/artifacts/{artifact_id}/view")
    assert view.status_code == 200
    assert view.content.startswith(b"# Report")


def test_skill_report_reflects_document_retention_without_paths(client, mem_store):
    _upload_document(client, share=True)
    report = client.get(
        "/api/v1/student/vbr/passport/skill-report", params={"skill": "machine-learning"}
    )
    assert report.status_code == 200
    assert "storage_path" not in report.text
    assert "proof-artifacts/" not in report.text

    correlations = [
        corr
        for chain in report.json().get("projects") or []
        for corr in chain.get("document_correlations") or []
    ]
    assert correlations, "expected the uploaded document to appear as a correlation"
    for corr in correlations:
        assert corr["document_retained"] is True
        card = corr["inspection_card"]
        assert card["document_retained"] is True
        assert card["document_artifact_id"]
        assert card["can_download_document"] is True
        assert card["document_open_url"].startswith("/api/v1/proofs/artifacts/")


# ── Website Proof replay storage config (Gate 14 blocker C) ───────────────────
#
# Gate 13 found Website Proof replay uploads failing in production with
# WPR-UPLOAD-REJECTED / replay_storage_unavailable, because the Render service
# had no SUPABASE_PROOF_ARTIFACT_BUCKET set (settings default ""), so
# storage_available() returned False and register_artifact_with_bytes() refused
# to retain the replay. The bucket `proof-artifacts` existed all along.
#
# These tests pin the config contract: retention is gated purely on the bucket
# setting for a real (non-dict) Supabase client. The fix is operational (set the
# env var on Render), not a code change — so we assert the exact env alias and
# the enable/disable behaviour rather than hardcoding a bucket in source.

class TestReplayStorageConfig:
    def test_env_var_alias_is_exact(self):
        # The deploy runbook / Render env change depends on this exact name.
        field = type(artifacts.settings).model_fields["supabase_proof_artifact_bucket"]
        assert field.alias == "SUPABASE_PROOF_ARTIFACT_BUCKET"

    def test_default_bucket_is_empty_not_hardcoded(self):
        # Source must NOT hardcode a production bucket; it stays configurable.
        field = type(artifacts.settings).model_fields["supabase_proof_artifact_bucket"]
        assert field.default == ""

    def test_retention_disabled_when_bucket_unset(self, monkeypatch):
        # Real (non-dict) client + no bucket → honest disable (Gate 13 prod state).
        monkeypatch.setattr(artifacts.settings, "supabase_proof_artifact_bucket", "")
        real_client = object()  # anything that is not a dict
        assert artifacts.storage_available(real_client) is False

    def test_retention_enabled_when_bucket_configured(self, monkeypatch):
        # Setting the bucket (as the Render fix does) enables retention.
        monkeypatch.setattr(
            artifacts.settings, "supabase_proof_artifact_bucket", "proof-artifacts"
        )
        real_client = object()
        assert artifacts.storage_available(real_client) is True
        assert artifacts._bucket() == "proof-artifacts"
