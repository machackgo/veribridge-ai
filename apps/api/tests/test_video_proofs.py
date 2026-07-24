"""Tests for first-class Video Proof (migration 057).

Covers:

  * upload validation (extension / MIME / source_kind)
  * honest pipeline statuses — transcription not configured / no speech,
    frame extraction unavailable — never faked results
  * transcript + frame persistence when the (mocked) providers succeed
  * deterministic analysis epistemics: skills stay unverified claims, the
    demo-video limitations are always present, needs_review stays true
  * access gating: owner-only until shared; sharing propagates to artifacts
  * transcript/frames endpoints expose safe descriptors only (no paths)
  * Skill Report integration: the video proof card appears for its claimed
    skill with honest availability flags

All storage is in-memory (dict mode). No network / LLM calls — transcription
and frame extraction are monkeypatched at the video_proof_service seam.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_optional_user_id, get_pipeline_db
from app.main import app
from app.services import video_proof_service
from app.services.transcription_service import (
    TranscriptionResult,
    TranscriptionUnavailableError,
    TranscriptSegment,
)
from app.services.video_keyframe_extractor_service import VideoKeyframeResult

from tests.conftest import seed_published_passport

OWNER = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict):
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


@pytest.fixture()
def transcription_unavailable(monkeypatch):
    def _unavailable(*_args, **_kwargs):
        raise TranscriptionUnavailableError("not configured")

    monkeypatch.setattr(video_proof_service, "transcribe_audio", _unavailable)


@pytest.fixture()
def transcription_ok(monkeypatch):
    def _ok(*_args, **_kwargs):
        return TranscriptionResult(
            transcript_text="This is our Machine Learning crash predictor demo.",
            provider_used="test",
            language="en",
            transcript_segments=[
                TranscriptSegment(0.0, 6.5, "This is our Machine Learning crash predictor demo."),
                TranscriptSegment(7.0, 14.0, "Uploading a dataset produces a risk prediction."),
            ],
        )

    monkeypatch.setattr(video_proof_service, "transcribe_audio", _ok)


@pytest.fixture()
def frames_unavailable(monkeypatch):
    class _NoBackend:
        def extract_keyframes(self, *_args, **_kwargs):
            return VideoKeyframeResult(
                video_analysis_status="not_available",
                keyframe_count=0,
                selected_frame_timestamps_ms=[],
                extraction_method="none",
                duration_ms=None,
                frame_width=None,
                frame_height=None,
                limitations=["No extraction backend installed."],
            )

    monkeypatch.setattr(video_proof_service, "VideoKeyframeExtractorService", _NoBackend)


@pytest.fixture()
def frames_ok(monkeypatch):
    class _FakeExtractor:
        def extract_keyframes(self, *_args, **_kwargs):
            return VideoKeyframeResult(
                video_analysis_status="analyzed",
                keyframe_count=2,
                selected_frame_timestamps_ms=[3000, 9000],
                extraction_method="cv2_interval",
                duration_ms=192_000,
                frame_width=1280,
                frame_height=720,
                limitations=[],
                _extracted_frames=[(3000, b"jpeg-frame-1"), (9000, b"jpeg-frame-2")],
            )

    monkeypatch.setattr(video_proof_service, "VideoKeyframeExtractorService", _FakeExtractor)


def _upload(client, **data):
    payload = {
        "title": "ML classifier demo",
        "source_kind": "hackathon_demo",
        "claimed_skills": "Machine Learning,React",
        **data,
    }
    return client.post(
        "/api/v1/proofs/video",
        files={"file": ("demo.mp4", b"fake-mp4-bytes", "video/mp4")},
        data=payload,
    )


# ── Upload validation ─────────────────────────────────────────────────────────

def test_upload_rejects_non_video_extension(client):
    response = client.post(
        "/api/v1/proofs/video",
        files={"file": ("notes.pdf", b"%PDF", "application/pdf")},
        data={"title": "x"},
    )
    assert response.status_code == 422


def test_upload_rejects_unknown_source_kind(client, transcription_unavailable, frames_unavailable):
    response = _upload(client, source_kind="tiktok_edit")
    assert response.status_code == 422


# ── Honest pipeline statuses ──────────────────────────────────────────────────

def test_upload_records_honest_unavailable_stages(client, transcription_unavailable, frames_unavailable):
    response = _upload(client)
    assert response.status_code == 201
    proof = response.json()
    assert proof["status"] == "analyzed"
    assert proof["transcript_status"] == "not_configured"
    assert proof["frames_status"] == "not_available"
    assert proof["segment_count"] == 0
    assert proof["frame_count"] == 0
    analysis = proof["analysis"]
    # Every heavy CV capability is explicitly not implemented — never faked.
    assert analysis["capabilities"]["ocr"] == "not_implemented"
    assert analysis["capabilities"]["object_detection"] == "not_implemented"
    assert analysis["observed_workflow"] == []
    assert analysis["project_features_shown"] == []
    assert "not configured" in analysis["demo_summary"]


def test_analysis_epistemics_never_overclaim(client, transcription_ok, frames_ok):
    proof = _upload(client).json()
    analysis = proof["analysis"]
    # A claimed skill mentioned in narration is still only a mention.
    by_skill = {s["skill"]: s for s in analysis["skills_supported"]}
    assert by_skill["Machine Learning"]["basis"] == "mentioned_in_narration"
    assert by_skill["Machine Learning"]["verified"] is False
    assert by_skill["React"]["basis"] == "claimed_only"
    assert by_skill["React"]["verified"] is False
    # The demo-video limitations are always present, verbatim honesty.
    assert any("authorship" in limitation for limitation in analysis["limitations"])
    assert proof["needs_review"] is True
    assert analysis["proof_strength"] == "demo_evidence"
    assert set(analysis["corroborates_with"]) == {"github", "website", "document", "project_defense"}


def test_transcript_and_frames_are_persisted_and_safe(client, mem_store, transcription_ok, frames_ok):
    proof = _upload(client).json()
    proof_id = proof["id"]
    assert proof["transcript_status"] == "completed"
    assert proof["frames_status"] == "completed"
    assert proof["duration_seconds"] == pytest.approx(192.0)

    transcript = client.get(f"/api/v1/proofs/video/{proof_id}/transcript")
    assert transcript.status_code == 200
    segments = transcript.json()["segments"]
    assert len(segments) == 2
    assert segments[0]["text"].startswith("This is our Machine Learning")
    assert "storage_path" not in transcript.text

    frames = client.get(f"/api/v1/proofs/video/{proof_id}/frames")
    assert frames.status_code == 200
    listing = frames.json()
    assert listing["frame_count"] == 2
    for frame in listing["frames"]:
        assert frame["frame_artifact_id"]
        assert frame["timestamp_label"]
        # Future-CV fields are honest nulls, not placeholder text.
        assert frame["ocr_text"] is None
        assert frame["activity_summary"] is None
    assert "storage_path" not in frames.text
    assert "proof-artifacts/" not in frames.text

    # Frame bytes stream through the gated artifact route for the owner.
    frame_artifact_id = listing["frames"][0]["frame_artifact_id"]
    view = client.get(f"/api/v1/proofs/artifacts/{frame_artifact_id}/view")
    assert view.status_code == 200
    assert view.content == b"jpeg-frame-1"


# ── Access gating ─────────────────────────────────────────────────────────────

def test_video_proof_is_owner_only_until_shared(client, transcription_ok, frames_ok, mem_store):
    # Non-owner access additionally requires the owner's Passport to be Public
    # (the migration-063 master-switch extension to media routes).
    seed_published_passport(mem_store, OWNER)
    proof = _upload(client).json()
    proof_id, artifact_id = proof["id"], proof["original_artifact_id"]

    _as(client, None)
    assert client.get(f"/api/v1/proofs/video/{proof_id}").status_code == 404
    assert client.get(f"/api/v1/proofs/video/{proof_id}/transcript").status_code == 404
    assert client.get(f"/api/v1/proofs/video/{proof_id}/frames").status_code == 404
    assert client.get(f"/api/v1/proofs/artifacts/{artifact_id}/view").status_code == 404

    _as(client, OWNER)
    shared = client.post(f"/api/v1/proofs/video/{proof_id}/visibility", json={"public_safe": True})
    assert shared.status_code == 200 and shared.json()["public_safe"] is True

    _as(client, None)
    assert client.get(f"/api/v1/proofs/video/{proof_id}").status_code == 200
    assert client.get(f"/api/v1/proofs/video/{proof_id}/transcript").status_code == 200
    assert client.get(f"/api/v1/proofs/video/{proof_id}/frames").status_code == 200
    # Sharing propagated to the retained artifacts (original + frames).
    assert client.get(f"/api/v1/proofs/artifacts/{artifact_id}/view").status_code == 200


def test_non_owner_cannot_toggle_visibility(client, transcription_unavailable, frames_unavailable):
    proof = _upload(client).json()
    _as(client, OTHER)
    client.caller["required"] = OTHER
    response = client.post(f"/api/v1/proofs/video/{proof['id']}/visibility", json={"public_safe": True})
    assert response.status_code == 404


# ── Skill Report integration ──────────────────────────────────────────────────

def test_skill_report_carries_video_proof_card(client, transcription_ok, frames_ok):
    _upload(client)
    report = client.get(
        "/api/v1/student/vbr/passport/skill-report", params={"skill": "machine-learning"}
    )
    assert report.status_code == 200
    payload = report.json()
    cards = payload["standalone_evidence"]["video_proofs"]
    assert len(cards) == 1
    card = cards[0]
    assert card["title"] == "ML classifier demo"
    assert card["replay_available"] is True
    assert card["transcript_available"] is True
    assert card["frames_available"] is True
    assert card["needs_review"] is True
    assert card["skills_supported"][0]["verified"] is False
    # The vault-bucket chain mirrors the standalone cards for the chains UI.
    vault_chains = [c for c in payload["projects"] if c["project_id"] is None]
    assert vault_chains and vault_chains[0]["video_proofs"] == cards
    assert "storage_path" not in report.text
    assert "proof-artifacts/" not in report.text


def test_skill_report_omits_video_proofs_for_other_skills(client, transcription_unavailable, frames_unavailable):
    _upload(client, claimed_skills="Machine Learning")
    report = client.get("/api/v1/student/vbr/passport/skill-report", params={"skill": "devops"})
    assert report.status_code == 200
    assert report.json()["standalone_evidence"]["video_proofs"] == []
