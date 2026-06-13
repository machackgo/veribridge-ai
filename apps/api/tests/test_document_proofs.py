"""Tests for standalone Document Proof / supporting evidence.

Covers:
  ✓ standalone document text save creates optional_evidence_submissions row
    with proof_session_id=null and a usable id
  ✓ upload of a supported file persists a row and returns an id
  ✓ unsupported file upload is rejected
  ✓ wrong user cannot sync another user's document evidence (404)
  ✓ unsupported/failed/no-skill document does not sync as saved (400)
  ✓ analyzed document creates protected document artifacts
  ✓ idempotency prevents duplicate artifacts
  ✓ artifact_data excludes raw text / storage paths / signed URLs / tokens
  ✓ existing Website/GitHub pipeline is not downgraded or overwritten
  ✓ document-only pipeline support_status is partially_supported (never
    strongly_supported)

All storage is in-memory (dict mode). No real network calls.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.schemas.skill_evidence_pipeline import SkillEvidencePipelineCreate
from app.services.document_proof_artifact_sync_service import (
    DocumentProofArtifactSyncService,
    DocumentProofNotFoundError,
    DocumentProofSyncStatusError,
)
from app.services.optional_evidence_service import OptionalEvidenceService
from app.services.skill_evidence_pipeline_service import SkillEvidencePipelineService

STUDENT_A = "aaaaaaaa-1111-0000-0000-000000000001"
STUDENT_B = "bbbbbbbb-2222-0000-0000-000000000002"

FASTAPI_TEXT = "For this project I implemented FastAPI to serve the application."


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def proof_db() -> dict:
    """In-memory store for optional_evidence_submissions."""
    return {}


@pytest.fixture()
def pipeline_db() -> dict:
    """In-memory store for skill_evidence_pipelines / artifacts tables."""
    return {}


@pytest.fixture()
def svc(proof_db: dict, pipeline_db: dict) -> DocumentProofArtifactSyncService:
    return DocumentProofArtifactSyncService(db=proof_db, pipeline_db=pipeline_db)


@pytest.fixture()
def client(proof_db: dict, pipeline_db: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: STUDENT_A
    app.dependency_overrides[get_db] = lambda: proof_db
    app.dependency_overrides[get_pipeline_db] = lambda: pipeline_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _seed_document_proof(
    proof_db: dict,
    user_id: str = STUDENT_A,
    *,
    raw_text: str = FASTAPI_TEXT,
    source_type: str = "document",
    title: str | None = "My Project Report",
) -> dict:
    return OptionalEvidenceService(proof_db).submit_text(
        user_id=user_id,
        proof_session_id=None,
        source_type=source_type,
        raw_text=raw_text,
        section_label=title,
        extra_metadata={"title": title, "claimed_skills": [], "description": None},
    )


def _seed_pipeline(pipeline_db: dict, user_id: str, **overrides) -> str:
    """Seed an existing skill_evidence_pipeline directly (e.g. from Website Proof)."""
    payload = SkillEvidencePipelineCreate(
        skill_name="FastAPI",
        skill_category="Backend",
        confidence_score=85,
        support_status="strongly_supported",
        evidence_count=1,
        evidence_sources=[
            {"key": "workflow", "label": "Workflow Recording", "status": "supported", "score": 85, "reason": "Live workflow demonstrated FastAPI"},
        ],
        recruiter_summary="Strong website proof evidence for FastAPI.",
        student_summary="Your FastAPI evidence is strong from Website Proof.",
        visibility_status="public",
    )
    data = payload.model_dump()
    data.update(overrides)
    payload = SkillEvidencePipelineCreate(**data)
    pipeline = SkillEvidencePipelineService(pipeline_db).upsert_pipeline(user_id, payload)
    return pipeline.id


# ── Tests: submit / upload / list ───────────────────────────────────────────

def test_submit_document_proof_text_creates_standalone_row(client: TestClient, proof_db: dict) -> None:
    response = client.post(
        "/api/v1/student/document-proofs",
        json={"source_type": "document", "raw_text": FASTAPI_TEXT, "title": "My Project Report"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"]
    assert body["status"] == "analyzed"
    assert body["source_type"] == "document"
    assert "raw_text" not in body

    rows = proof_db["optional_evidence_submissions"]
    assert len(rows) == 1
    row = next(iter(rows.values()))
    assert row["id"] == body["id"]
    assert row["proof_session_id"] is None
    assert row["user_id"] == STUDENT_A


def test_upload_document_proof_persists_and_returns_id(client: TestClient, proof_db: dict) -> None:
    files = {"file": ("report.txt", FASTAPI_TEXT.encode("utf-8"), "text/plain")}
    response = client.post("/api/v1/student/document-proofs/upload", files=files, data={"title": "Report"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"]
    assert body["status"] == "analyzed"
    assert body["filename"] == "report.txt"

    rows = proof_db["optional_evidence_submissions"]
    assert len(rows) == 1
    row = next(iter(rows.values()))
    assert row["id"] == body["id"]
    assert row["proof_session_id"] is None


def test_upload_unsupported_file_is_rejected(client: TestClient, proof_db: dict) -> None:
    files = {"file": ("malware.exe", b"binary-content", "application/octet-stream")}
    response = client.post("/api/v1/student/document-proofs/upload", files=files)
    assert response.status_code == 422
    assert proof_db.get("optional_evidence_submissions", {}) == {}


def test_upload_certificate_transcript_persists_source_type(client: TestClient, proof_db: dict) -> None:
    files = {"file": ("certificate.txt", FASTAPI_TEXT.encode("utf-8"), "text/plain")}
    response = client.post(
        "/api/v1/student/document-proofs/upload",
        files=files,
        data={"title": "Certificate", "source_type": "certificate_transcript"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source_type"] == "certificate_transcript"

    rows = proof_db["optional_evidence_submissions"]
    row = next(iter(rows.values()))
    assert row["source_type"] == "certificate_transcript"
    assert row["evidence_objects"][0]["source_type"] == "certificate_transcript"


def test_upload_invalid_source_type_is_rejected(client: TestClient, proof_db: dict) -> None:
    files = {"file": ("report.txt", FASTAPI_TEXT.encode("utf-8"), "text/plain")}
    response = client.post(
        "/api/v1/student/document-proofs/upload",
        files=files,
        data={"source_type": "linkedin_profile"},
    )
    assert response.status_code == 422
    assert proof_db.get("optional_evidence_submissions", {}) == {}


def test_list_document_proofs_returns_standalone_rows(client: TestClient, proof_db: dict) -> None:
    _seed_document_proof(proof_db)
    response = client.get("/api/v1/student/document-proofs")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == "analyzed"


# ── Tests: sync status gating ───────────────────────────────────────────────

def test_wrong_user_cannot_sync_another_users_document(svc: DocumentProofArtifactSyncService, proof_db: dict) -> None:
    row = _seed_document_proof(proof_db, user_id=STUDENT_A)
    with pytest.raises(DocumentProofNotFoundError):
        svc.sync(user_id=STUDENT_B, document_evidence_id=row["id"])


def test_nonexistent_document_raises_not_found(svc: DocumentProofArtifactSyncService) -> None:
    with pytest.raises(DocumentProofNotFoundError):
        svc.sync(user_id=STUDENT_A, document_evidence_id="does-not-exist")


def test_session_scoped_optional_evidence_cannot_sync_via_document_proof(
    svc: DocumentProofArtifactSyncService, proof_db: dict
) -> None:
    # A Website Proof optional evidence row (proof_session_id is set) must not
    # be syncable through the standalone document proof endpoint/service.
    row = OptionalEvidenceService(proof_db).submit_text(
        user_id=STUDENT_A,
        proof_session_id="session-123",
        source_type="document",
        raw_text=FASTAPI_TEXT,
        section_label="Website Proof optional evidence",
    )
    with pytest.raises(DocumentProofNotFoundError):
        svc.sync(user_id=STUDENT_A, document_evidence_id=row["id"])


def test_linkedin_profile_evidence_cannot_sync_via_document_proof(
    svc: DocumentProofArtifactSyncService, proof_db: dict
) -> None:
    # A linkedin_profile optional evidence row must not be syncable through
    # the standalone document proof endpoint/service.
    row = OptionalEvidenceService(proof_db).submit_text(
        user_id=STUDENT_A,
        proof_session_id=None,
        source_type="linkedin_profile",
        raw_text=FASTAPI_TEXT,
        section_label="LinkedIn profile",
    )
    with pytest.raises(DocumentProofNotFoundError):
        svc.sync(user_id=STUDENT_A, document_evidence_id=row["id"])


def test_no_skill_document_does_not_sync(svc: DocumentProofArtifactSyncService, proof_db: dict) -> None:
    # Too short to extract any skills -> status "needs_review"
    row = _seed_document_proof(proof_db, raw_text="too short")
    assert row["status"] == "needs_review"
    with pytest.raises(DocumentProofSyncStatusError):
        svc.sync(user_id=STUDENT_A, document_evidence_id=row["id"])


def test_wrong_user_returns_404_via_endpoint(client: TestClient, proof_db: dict) -> None:
    row = _seed_document_proof(proof_db, user_id=STUDENT_B)
    response = client.post(f"/api/v1/student/skill-pipelines/from-document-proof/{row['id']}")
    assert response.status_code == 404


def test_unready_status_returns_400_via_endpoint(client: TestClient, proof_db: dict) -> None:
    row = _seed_document_proof(proof_db, raw_text="too short")
    response = client.post(f"/api/v1/student/skill-pipelines/from-document-proof/{row['id']}")
    assert response.status_code == 400


# ── Tests: analyzed document sync ───────────────────────────────────────────

def test_analyzed_document_creates_protected_artifacts(svc: DocumentProofArtifactSyncService, proof_db: dict, pipeline_db: dict) -> None:
    row = _seed_document_proof(proof_db)

    result = svc.sync(user_id=STUDENT_A, document_evidence_id=row["id"])

    assert result.already_synced is False
    assert result.skills_synced == ["FastAPI"]
    assert result.pipelines_upserted == 1
    assert result.artifacts_created == 1
    assert result.errors == []

    pipelines = SkillEvidencePipelineService(pipeline_db).list_pipelines_for_student(STUDENT_A)
    assert len(pipelines) == 1
    artifacts = SkillEvidencePipelineService(pipeline_db).list_artifacts_for_pipeline(pipelines[0].id, STUDENT_A)
    doc_artifact = next(a for a in artifacts if a.source_type == "document")
    assert doc_artifact.visibility == "protected"
    assert doc_artifact.project_name == "Document Proof"
    assert doc_artifact.source_title.startswith("Document — ")


def test_analyzed_document_via_endpoint(client: TestClient, proof_db: dict) -> None:
    row = _seed_document_proof(proof_db)
    response = client.post(f"/api/v1/student/skill-pipelines/from-document-proof/{row['id']}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["already_synced"] is False
    assert body["skills_synced"] == ["FastAPI"]
    assert body["pipelines_upserted"] == 1
    assert body["artifacts_created"] == 1


# ── Tests: idempotency ───────────────────────────────────────────────────────

def test_second_sync_is_idempotent(svc: DocumentProofArtifactSyncService, proof_db: dict, pipeline_db: dict) -> None:
    row = _seed_document_proof(proof_db)

    first = svc.sync(user_id=STUDENT_A, document_evidence_id=row["id"])
    assert first.already_synced is False
    assert first.artifacts_created == 1

    second = svc.sync(user_id=STUDENT_A, document_evidence_id=row["id"])
    assert second.already_synced is True
    assert second.artifacts_created == 0

    pipelines = SkillEvidencePipelineService(pipeline_db).list_pipelines_for_student(STUDENT_A)
    assert len(pipelines) == 1
    artifacts = SkillEvidencePipelineService(pipeline_db).list_artifacts_for_pipeline(pipelines[0].id, STUDENT_A)
    document_artifacts = [a for a in artifacts if a.source_type == "document"]
    assert len(document_artifacts) == 1


# ── Tests: artifact safety ───────────────────────────────────────────────────

def test_artifact_data_excludes_unsafe_fields(svc: DocumentProofArtifactSyncService, proof_db: dict, pipeline_db: dict) -> None:
    row = _seed_document_proof(proof_db)
    # Simulate accidental unsafe metadata being present on the row.
    row["analysis_json"]["storage_path"] = "private/bucket/secret.pdf"
    row["analysis_json"]["signed_url"] = "https://storage.example/secret?token=abc123"
    row["analysis_json"]["access_token"] = "super-secret-token"
    row["raw_text"] = FASTAPI_TEXT

    svc.sync(user_id=STUDENT_A, document_evidence_id=row["id"])

    pipelines = SkillEvidencePipelineService(pipeline_db).list_pipelines_for_student(STUDENT_A)
    artifacts = SkillEvidencePipelineService(pipeline_db).list_artifacts_for_pipeline(pipelines[0].id, STUDENT_A)
    doc_artifact = next(a for a in artifacts if a.source_type == "document")

    serialized = str(doc_artifact.artifact_data)
    assert "raw_text" not in doc_artifact.artifact_data
    assert "extracted_text_preview" not in doc_artifact.artifact_data
    assert "storage_path" not in doc_artifact.artifact_data
    assert "signed_url" not in doc_artifact.artifact_data
    assert "access_token" not in doc_artifact.artifact_data
    assert "super-secret-token" not in serialized
    assert "private/bucket/secret.pdf" not in serialized

    # Safe fields are present
    assert doc_artifact.artifact_data["document_evidence_id"] == row["id"]
    assert doc_artifact.artifact_data["matched_skills"] == ["FastAPI"]
    assert doc_artifact.artifact_data["extraction_status"] == "analyzed"


# ── Tests: existing pipeline preservation ───────────────────────────────────

def test_existing_website_pipeline_not_overwritten_or_downgraded(svc: DocumentProofArtifactSyncService, proof_db: dict, pipeline_db: dict) -> None:
    _seed_pipeline(
        pipeline_db,
        STUDENT_A,
        skill_name="FastAPI",
        confidence_score=85,
        support_status="strongly_supported",
        recruiter_summary="Strong website proof evidence for FastAPI.",
        student_summary="Your FastAPI evidence is strong from Website Proof.",
        visibility_status="public",
        evidence_sources=[
            {"key": "workflow", "label": "Workflow Recording", "status": "supported", "score": 85, "reason": "Live workflow demonstrated FastAPI"},
        ],
    )
    row = _seed_document_proof(proof_db)

    svc.sync(user_id=STUDENT_A, document_evidence_id=row["id"])

    pipelines = SkillEvidencePipelineService(pipeline_db).list_pipelines_for_student(STUDENT_A)
    assert len(pipelines) == 1
    fastapi_pipeline = pipelines[0]

    # Never downgraded
    assert fastapi_pipeline.confidence_score == 85
    assert fastapi_pipeline.support_status == "strongly_supported"
    assert fastapi_pipeline.visibility_status == "public"
    assert fastapi_pipeline.recruiter_summary == "Strong website proof evidence for FastAPI."
    assert fastapi_pipeline.student_summary == "Your FastAPI evidence is strong from Website Proof."

    # Document evidence merged in, existing source preserved
    keys = {s["key"] for s in fastapi_pipeline.evidence_sources}
    assert keys == {"workflow", "document"}
    assert fastapi_pipeline.evidence_count == 2


# ── Tests: no overclaiming from document-only evidence ─────────────────────

def test_document_only_pipeline_is_never_strongly_supported(svc: DocumentProofArtifactSyncService, proof_db: dict, pipeline_db: dict) -> None:
    row = _seed_document_proof(proof_db)

    svc.sync(user_id=STUDENT_A, document_evidence_id=row["id"])

    pipelines = SkillEvidencePipelineService(pipeline_db).list_pipelines_for_student(STUDENT_A)
    fastapi_pipeline = pipelines[0]

    assert fastapi_pipeline.support_status in {"partially_supported", "needs_review"}
    assert fastapi_pipeline.support_status != "strongly_supported"
    assert fastapi_pipeline.visibility_status == "protected"
    assert fastapi_pipeline.confidence_score < 70
