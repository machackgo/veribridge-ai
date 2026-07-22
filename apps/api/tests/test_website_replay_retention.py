"""Website Proof replay retention (migrations 056 + 058).

Covers the retention foundation that turns a completed Website Proof into a
durable, replayable artifact:

  * uploading a workflow recording retains the raw bytes PRIVATELY as a
    ``website_replay_video`` proof artifact, and reports a canonical
    ``recording_state`` of ``ready`` — never the old "processing / no video"
    contradiction
  * the gated ``/proofs/website/{session}/replay`` route then streams it
  * ``/workflow/video/replay`` returns state + a short-lived signed URL, and is
    owner-gated (a non-owner sees the SAME ``not_retained`` as an empty session
    — no existence leak)
  * a re-upload REPLACES the prior recording (idempotent, no duplicate retained
    artifact)
  * when artifact storage is not configured, retention degrades honestly to
    ``not_retained`` (no fake artifact row)
  * storage paths / buckets never leak into any response
  * the workflow analyzer's ``filtered_unrelated_activity`` field survives
    persistence (migration 058)

All storage is in-memory (dict mode). No network / LLM calls.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_optional_user_id
from app.main import app
from app.services import proof_artifact_service as artifacts

OWNER = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
SESSION = "sess-replay-1"

_VIDEO_BASE = "/api/v1/student/extension-proof/sessions"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict):
    caller: dict = {"required": OWNER, "optional": OWNER}
    app.dependency_overrides[get_current_user_id] = lambda: caller["required"]
    app.dependency_overrides[get_optional_user_id] = lambda: caller["optional"]
    app.dependency_overrides[get_db] = lambda: mem_store
    test_client = TestClient(app)
    test_client.caller = caller  # type: ignore[attr-defined]
    yield test_client
    app.dependency_overrides.clear()


def _as(client, user_id):
    client.caller["required"] = user_id or OWNER
    client.caller["optional"] = user_id


def _upload(client, session_id=SESSION, data=b"webm-recording-bytes", name="recording.webm"):
    return client.post(
        f"{_VIDEO_BASE}/{session_id}/workflow/video",
        files={"video": (name, io.BytesIO(data), "video/webm")},
    )


# ── Upload retains the recording ────────────────────────────────────────────────

def test_upload_retains_replay_privately_and_reports_ready(client, mem_store):
    resp = _upload(client)
    assert resp.status_code == 202
    body = resp.json()
    assert body["replay_retained"] is True
    assert body["recording_state"] == "ready"
    assert body["replay_artifact_id"]
    # No storage internals leak.
    assert "storage_path" not in resp.text
    assert "proof-artifacts/" not in resp.text

    # Exactly one retained replay artifact exists for this session.
    retained = artifacts.list_artifacts_for_proof(
        mem_store, proof_type="website", proof_id=SESSION,
        artifact_type="website_replay_video",
    )
    assert len(retained) == 1
    assert retained[0]["access_policy"] == "owner_only"  # private by default


def test_gated_replay_route_streams_the_retained_recording(client):
    _upload(client, data=b"the-real-bytes")
    resp = client.get(f"/api/v1/proofs/website/{SESSION}/replay")
    assert resp.status_code == 200
    assert resp.content == b"the-real-bytes"


# ── Replay-status endpoint ──────────────────────────────────────────────────────

def test_replay_status_ready_with_short_lived_signed_url(client):
    _upload(client)
    resp = client.get(f"{_VIDEO_BASE}/{SESSION}/workflow/video/replay")
    assert resp.status_code == 200
    body = resp.json()
    assert body["recording_state"] == "ready"
    assert body["replay_available"] is True
    assert body["signed_url"]
    assert body["expires_at"]
    assert 0 < body["expires_in_seconds"] <= artifacts.SIGNED_URL_MAX_TTL_S
    # The signed URL never carries the private storage path.
    assert "proof-artifacts/" not in body["signed_url"]
    assert "storage_path" not in resp.text


def test_replay_status_not_retained_for_unknown_session(client):
    resp = client.get(f"{_VIDEO_BASE}/never-recorded/workflow/video/replay")
    assert resp.status_code == 200
    body = resp.json()
    assert body["recording_state"] == "not_retained"
    assert body["replay_available"] is False
    assert body["signed_url"] is None


def test_replay_status_is_owner_gated_no_existence_leak(client):
    _upload(client)
    _as(client, OTHER)
    resp = client.get(f"{_VIDEO_BASE}/{SESSION}/workflow/video/replay")
    assert resp.status_code == 200
    body = resp.json()
    # A non-owner sees the SAME shape as an empty session — no leak.
    assert body["recording_state"] == "not_retained"
    assert body["replay_available"] is False
    # And the gated stream route also refuses the non-owner.
    assert client.get(f"/api/v1/proofs/website/{SESSION}/replay").status_code == 404


# ── Idempotent re-upload ────────────────────────────────────────────────────────

def test_reupload_replaces_recording_without_duplicating(client, mem_store):
    _upload(client, data=b"first-take")
    second = _upload(client, data=b"second-take")
    assert second.status_code == 202

    # Only ONE retained replay artifact remains for the session.
    retained = artifacts.list_artifacts_for_proof(
        mem_store, proof_type="website", proof_id=SESSION,
        artifact_type="website_replay_video",
    )
    assert len(retained) == 1

    # And the replay serves the NEWEST recording.
    resp = client.get(f"/api/v1/proofs/website/{SESSION}/replay")
    assert resp.status_code == 200
    assert resp.content == b"second-take"


# ── Honest degradation when storage is not configured ───────────────────────────

def test_retention_degrades_honestly_without_storage(monkeypatch):
    # Simulate artifact bucket not configured — retention must refuse rather than
    # write a dangling/fake artifact row.
    monkeypatch.setattr(artifacts, "storage_available", lambda db: False)
    row = artifacts.retain_website_replay_video(
        {},
        owner_user_id=OWNER,
        session_id=SESSION,
        data=b"bytes",
        mime_type="video/webm",
        file_name="recording.webm",
    )
    assert row is None


# ── Migration 058: filtered_unrelated_activity persists ─────────────────────────

def test_migration_058_adds_filtered_unrelated_activity_column():
    sql = (
        Path(__file__).resolve().parents[1]
        / "app" / "db" / "migrations"
        / "058_workflow_filtered_unrelated_activity.sql"
    ).read_text()
    assert "add column if not exists filtered_unrelated_activity" in sql.lower()
    assert "workflow_analysis_results" in sql


def test_workflow_analysis_persistence_carries_filtered_unrelated_activity():
    from app.services.extension_proof_workflow_analysis_service import (
        ExtensionProofWorkflowAnalysisService,
    )

    db: dict = {}
    svc = ExtensionProofWorkflowAnalysisService(db)
    payload = {
        "workflow_summary": "did a thing",
        "filtered_unrelated_activity": {"count": 2, "hosts": [{"host": "ads.example", "count": 2}]},
    }
    svc._upsert_result(OWNER, SESSION, payload)
    stored = svc.get_latest(OWNER, SESSION)
    assert stored is not None
    assert stored["filtered_unrelated_activity"] == payload["filtered_unrelated_activity"]
