"""Project-first Project Defense flow tests.

Project Defense is a defense layer on top of an existing project, not a fourth
standalone proof form. These tests cover the selection + workspace endpoints:

  - list the current user's projects eligible for defense
  - fetch a selected project's defense context (attached evidence summary)
  - ownership: a user cannot read another user's defense context
  - ownership: a user cannot attach another user's proof to their project
  - generate defense questions uses the selected project's context
  - missing evidence is represented safely (no raw payloads)
  - document title fallback never exposes a raw file_path
  - report-link readiness is conservative (analysis-complete only)

All storage is in-memory (dict mode). No real network calls, no LLM calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app

USER_ID = "00000000-0000-0000-0000-000000000042"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000099"

BASE = "/api/v1/student/vbr"


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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(UTC).isoformat()


def _seed_project(
    mem_store: dict,
    *,
    user_id: str = USER_ID,
    title: str = "Skill Evidence Tracker",
    metadata: dict | None = None,
) -> str:
    project_id = str(uuid4())
    now = _now()
    mem_store.setdefault("vbr_projects", {})[project_id] = {
        "id": project_id,
        "user_id": user_id,
        "title": title,
        "repo_url": "https://github.com/octocat/Hello-World",
        "repo_full_name": "octocat/Hello-World",
        "deployed_url": None,
        "head_sha": None,
        "status": "draft",
        "metadata": metadata
        if metadata is not None
        else {
            "description": "A platform that tracks student skill evidence.",
            "claimed_skills": ["Python", "React"],
            "student_role": "I built the backend API.",
            "individual_project_only": True,
            "attached_proofs": {},
            "phase": "project_defense_mvp_v1",
        },
        "created_at": now,
        "updated_at": now,
    }
    return project_id


def _seed_github_proof(mem_store: dict, user_id: str = USER_ID, **overrides) -> str:
    proof_id = str(uuid4())
    now = _now()
    row = {
        "id": proof_id,
        "user_id": user_id,
        "proof_session_id": None,
        "repo_url": "https://github.com/machackgo/boston-smart-accident-risk-rerouting-google-cloud",
        "repo_owner": "machackgo",
        "repo_name": "boston-smart-accident-risk-rerouting-google-cloud",
        "default_branch": "main",
        "visibility": "public",
        "status": "analyzed",
        "submitted_skill_claims": ["Python"],
        "detected_skills": ["Python", "Machine Learning"],
        "repo_metadata": {"secret_token": "should-never-leak"},
        "analysis_summary": "Repo demonstrates backend work.",
        "evidence_strength": "partial",
        "confidence_score": 72,
        "risk_flags": [],
        "missing_evidence": [],
        "public_safe_summary": "GitHub proof is partial evidence with 72/100 confidence.",
        "analysis_snapshot": {"raw_dump": "should-never-leak"},
        "last_analyzed_at": now,
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    mem_store.setdefault("github_proof_submissions", {})[proof_id] = row
    return proof_id


def _seed_document_evidence(mem_store: dict, user_id: str = USER_ID, **overrides) -> str:
    doc_id = str(uuid4())
    now = _now()
    row = {
        "id": doc_id,
        "user_id": user_id,
        "proof_session_id": None,
        "source_type": "document",
        "status": "analyzed",
        "analysis_json": {"title": "Final Year Project Report"},
        "file_path": None,
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    mem_store.setdefault("optional_evidence_submissions", {})[doc_id] = row
    return doc_id


# ── Eligible project listing ─────────────────────────────────────────────────

def test_lists_only_the_current_users_eligible_projects(client: TestClient, mem_store: dict) -> None:
    mine = _seed_project(mem_store, title="My Project")
    _seed_project(mem_store, user_id=OTHER_USER_ID, title="Someone Else's Project")

    res = client.get(f"{BASE}/project-defense/eligible-projects")
    assert res.status_code == 200
    projects = res.json()["projects"]

    ids = {p["id"] for p in projects}
    assert mine in ids
    titles = {p["title"] for p in projects}
    assert "My Project" in titles
    assert "Someone Else's Project" not in titles


def test_eligible_project_summary_reflects_attached_evidence_and_status(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _seed_project(
        mem_store,
        metadata={
            "description": "desc",
            "claimed_skills": ["Python"],
            "student_role": "",
            "individual_project_only": True,
            "attached_proofs": {
                "github_proof": {
                    "github_proof_id": "gh-1",
                    "repo_url": "https://github.com/octocat/Hello-World",
                    "repo_owner": "octocat",
                    "repo_name": "Hello-World",
                    "status": "analyzed",
                    "detected_skills": ["Python"],
                    "public_safe_summary": "safe summary",
                },
                "documents": [{"document_evidence_id": "doc-1", "title": "Report.pdf"}],
            },
            "phase": "project_defense_mvp_v1",
        },
    )

    res = client.get(f"{BASE}/project-defense/eligible-projects")
    assert res.status_code == 200
    project = next(p for p in res.json()["projects"] if p["id"] == project_id)

    assert project["evidence"]["github_proof"]["attached"] is True
    assert project["evidence"]["github_proof"]["label"] == "octocat/Hello-World"
    assert project["evidence"]["documents"]["attached"] is True
    assert project["evidence"]["documents"]["count"] == 1
    assert project["evidence"]["website_proof"]["attached"] is False
    assert project["defense_status"] == "not_started"
    assert project["report_ready"] is False


# ── Defense context (workspace) ──────────────────────────────────────────────

def test_context_includes_attached_evidence_summary(client: TestClient, mem_store: dict) -> None:
    project_id = _seed_project(
        mem_store,
        metadata={
            "description": "A platform.",
            "claimed_skills": ["Python", "React"],
            "student_role": "backend",
            "individual_project_only": True,
            "attached_proofs": {
                "website_proofs": [
                    {
                        "proof_session_id": "ws-1",
                        "target_website": "https://demo.example.com",
                        "workflow_confidence": "high",
                    }
                ]
            },
            "phase": "project_defense_mvp_v1",
        },
    )

    res = client.get(f"{BASE}/project-defense/projects/{project_id}/context")
    assert res.status_code == 200
    body = res.json()

    assert body["project"]["id"] == project_id
    assert body["metadata"]["claimed_skills"] == ["Python", "React"]
    assert body["evidence"]["website_proof"]["attached"] is True
    assert body["evidence"]["website_proof"]["label"] == "https://demo.example.com"
    assert body["evidence"]["github_proof"]["attached"] is False
    assert body["defense_status"] == "not_started"
    assert body["report_ready"] is False
    assert body["session_id"] is None
    assert body["questions"] == []


def test_context_missing_evidence_is_represented_safely(client: TestClient, mem_store: dict) -> None:
    project_id = _seed_project(
        mem_store,
        metadata={
            "description": "",
            "claimed_skills": [],
            "student_role": "",
            "individual_project_only": True,
            "attached_proofs": {},
            "phase": "project_defense_mvp_v1",
        },
    )

    res = client.get(f"{BASE}/project-defense/projects/{project_id}/context")
    assert res.status_code == 200
    evidence = res.json()["evidence"]

    for key in ("github_proof", "documents", "website_proof", "project_defense"):
        assert evidence[key]["attached"] is False
        assert evidence[key]["count"] == 0
        assert evidence[key]["label"] == ""


def test_context_excludes_unsafe_legacy_attached_proof_fields(
    client: TestClient, mem_store: dict
) -> None:
    """Legacy metadata.attached_proofs may carry unsafe fields — the context
    endpoint must allowlist them away and echo only safe display summaries."""
    project_id = _seed_project(
        mem_store,
        metadata={
            "description": "A platform.",
            "claimed_skills": ["Python"],
            "student_role": "",
            "individual_project_only": True,
            "attached_proofs": {
                # Unsafe top-level legacy keys.
                "skill_pipeline_ids": ["pipeline-secret-1"],
                "github_proof_id": "gh-private-id-123",
                "github_proof": {
                    "repo_url": "https://github.com/octocat/Hello-World",
                    "repo_owner": "octocat",
                    "repo_name": "Hello-World",
                    "status": "analyzed",
                    "detected_skills": ["Python"],
                    "public_safe_summary": "Safe public summary.",
                    # Unsafe legacy fields that must be dropped.
                    "github_proof_id": "gh-private-id-123",
                    "repo_metadata": {"secret_token": "LEAK_SECRET_TOKEN"},
                    "file_path": "vbr/uploads/private-file.json",
                    "signed_url": "https://storage.example.com/x?token=abc",
                    "provider_json": {"raw": "dump"},
                    "confidence_score": 72,
                },
                "documents": [
                    {
                        "document_evidence_id": "doc-private-id-999",
                        "title": "Report.pdf",
                        "source_type": "document",
                        "status": "analyzed",
                        "skills": ["Python"],
                        # Unsafe legacy fields.
                        "file_path": "vbr/uploads/secret-report.pdf",
                        "raw_text": "raw extracted document text that must not leak",
                        "analysis_score": 88,
                    }
                ],
                "website_proofs": [
                    {
                        "proof_session_id": "ws-private-id-555",
                        "target_website": "https://demo.example.com",
                        "workflow_confidence": "high",
                        "supported_skills": ["Python"],
                        # Unsafe legacy fields.
                        "evidence_strength_score": 75,
                        "storage_path": "buckets/screens/ws-555.png",
                        "signed_url": "https://storage.example.com/y?token=def",
                    }
                ],
            },
            "phase": "project_defense_mvp_v1",
        },
    )

    res = client.get(f"{BASE}/project-defense/projects/{project_id}/context")
    assert res.status_code == 200
    body = res.json()

    attached = body["metadata"]["attached_proofs"]

    # GitHub proof — only allowlisted safe fields survive.
    assert set(attached["github_proof"].keys()) == {
        "repo_url",
        "repo_owner",
        "repo_name",
        "status",
        "detected_skills",
        "public_safe_summary",
    }

    # Documents — only allowlisted safe fields survive.
    assert set(attached["documents"][0].keys()) == {"title", "source_type", "status", "skills"}

    # Website proofs — only allowlisted safe fields survive (no private id/score).
    assert set(attached["website_proofs"][0].keys()) == {
        "target_website",
        "workflow_confidence",
        "supported_skills",
    }

    # No unsafe legacy value or key anywhere in the serialized response.
    serialized = res.text
    for leaked in (
        "LEAK_SECRET_TOKEN",
        "secret_token",
        "repo_metadata",
        "provider_json",
        "raw_text",
        "signed_url",
        "storage_path",
        "confidence_score",
        "evidence_strength_score",
        "gh-private-id-123",
        "doc-private-id-999",
        "ws-private-id-555",
        "pipeline-secret-1",
        "vbr/uploads",
    ):
        assert leaked not in serialized, f"leaked unsafe field/value: {leaked}"


def test_context_owner_only_returns_404_for_other_users_project(
    client: TestClient, mem_store: dict
) -> None:
    other_project = _seed_project(mem_store, user_id=OTHER_USER_ID)

    res = client.get(f"{BASE}/project-defense/projects/{other_project}/context")
    assert res.status_code == 404


# ── Attach existing proofs to a selected project ─────────────────────────────

def test_attach_owned_proofs_to_project_updates_evidence(client: TestClient, mem_store: dict) -> None:
    project_id = _seed_project(mem_store)
    gh_proof = _seed_github_proof(mem_store)
    doc = _seed_document_evidence(mem_store)

    res = client.post(
        f"{BASE}/project-defense/projects/{project_id}/attach-proofs",
        json={"github_proof_id": gh_proof, "document_evidence_ids": [doc]},
    )
    assert res.status_code == 200
    evidence = res.json()["evidence"]

    assert evidence["github_proof"]["attached"] is True
    assert evidence["github_proof"]["label"] == "machackgo/boston-smart-accident-risk-rerouting-google-cloud"
    assert evidence["documents"]["attached"] is True
    assert evidence["documents"]["count"] == 1

    # Persisted onto the project metadata so a later context read reflects it.
    ctx = client.get(f"{BASE}/project-defense/projects/{project_id}/context").json()
    assert ctx["evidence"]["github_proof"]["attached"] is True


def test_cannot_attach_another_users_github_proof(client: TestClient, mem_store: dict) -> None:
    project_id = _seed_project(mem_store)
    foreign_proof = _seed_github_proof(mem_store, user_id=OTHER_USER_ID)

    res = client.post(
        f"{BASE}/project-defense/projects/{project_id}/attach-proofs",
        json={"github_proof_id": foreign_proof},
    )
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "vbr_github_proof_not_found"


def test_cannot_attach_another_users_document(client: TestClient, mem_store: dict) -> None:
    project_id = _seed_project(mem_store)
    foreign_doc = _seed_document_evidence(mem_store, user_id=OTHER_USER_ID)

    res = client.post(
        f"{BASE}/project-defense/projects/{project_id}/attach-proofs",
        json={"document_evidence_ids": [foreign_doc]},
    )
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "vbr_document_evidence_not_found"


def test_cannot_attach_to_another_users_project(client: TestClient, mem_store: dict) -> None:
    other_project = _seed_project(mem_store, user_id=OTHER_USER_ID)
    gh_proof = _seed_github_proof(mem_store)

    res = client.post(
        f"{BASE}/project-defense/projects/{other_project}/attach-proofs",
        json={"github_proof_id": gh_proof},
    )
    assert res.status_code == 404


def test_document_title_fallback_never_exposes_raw_file_path(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _seed_project(mem_store)
    # A document with no analyzer/student title and a raw storage-ish file_path.
    doc = _seed_document_evidence(
        mem_store,
        analysis_json={},
        title=None,
        file_path="vbr/uploads/secret-user-file-12345.pdf",
    )

    res = client.post(
        f"{BASE}/project-defense/projects/{project_id}/attach-proofs",
        json={"document_evidence_ids": [doc]},
    )
    assert res.status_code == 200

    label = res.json()["evidence"]["documents"]["label"]
    assert "secret-user-file" not in label
    assert "vbr/uploads" not in label
    assert label == "Document"


# ── Generate questions uses the selected project's context ───────────────────

def test_generate_questions_uses_selected_project_context(client: TestClient, mem_store: dict) -> None:
    project_id = _seed_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        metadata={
            "description": "Accident-risk-aware routing on Google Cloud.",
            "claimed_skills": ["Python", "Machine Learning"],
            "student_role": "I built the risk-scoring API.",
            "individual_project_only": True,
            "attached_proofs": {},
            "phase": "project_defense_mvp_v1",
        },
    )

    res = client.post(f"{BASE}/projects/{project_id}/generate-defense-questions")
    assert res.status_code == 200
    body = res.json()
    assert body["project_id"] == project_id

    texts = " ".join(q["question_text"] for q in body["questions"])
    # Project-specific: names the actual project title and a claimed skill.
    assert "Boston Smart Accident Risk Rerouting" in texts
    assert "Python" in texts
    assert "Machine Learning" in texts

    # After questions exist, the defense status advances to in_progress.
    ctx = client.get(f"{BASE}/project-defense/projects/{project_id}/context").json()
    assert ctx["defense_status"] == "in_progress"
    assert ctx["session_id"] == body["session_id"]
    assert len(ctx["questions"]) == len(body["questions"])
    # An in-progress (questions-only) defense is NOT yet report-ready.
    assert ctx["report_ready"] is False


def test_generated_questions_are_grounded_in_description_and_safe_proof_summaries(
    client: TestClient, mem_store: dict
) -> None:
    """Question generation must weave in the project's own description and the
    *safe* attached-proof summaries — never generic boilerplate, and never any
    unsafe legacy metadata field."""
    project_id = _seed_project(
        mem_store,
        title="Aurora Reef Monitor",
        metadata={
            "description": "Reef-health monitoring using tidal-drift sonar mapping.",
            "claimed_skills": ["Python"],
            "student_role": "I built the sonar ingestion pipeline.",
            "individual_project_only": True,
            "attached_proofs": {
                "github_proof": {
                    "repo_url": "https://github.com/octocat/Hello-World",
                    "repo_owner": "octocat",
                    "repo_name": "Hello-World",
                    "status": "analyzed",
                    "detected_skills": ["Python"],
                    "public_safe_summary": "Repo shows a bathymetric-sweep scheduler with 72/100 confidence.",
                    # Unsafe legacy fields that must never reach a question.
                    "repo_metadata": {"secret_token": "LEAK_SECRET_TOKEN"},
                    "file_path": "vbr/uploads/private-file.json",
                },
                "documents": [
                    {
                        "document_evidence_id": "doc-1",
                        "title": "Sonar Calibration Notes",
                        "skills": ["Python"],
                        "raw_text": "SECRET raw document text that must not leak",
                    }
                ],
            },
            "phase": "project_defense_mvp_v1",
        },
    )

    res = client.post(f"{BASE}/projects/{project_id}/generate-defense-questions")
    assert res.status_code == 200, res.text
    questions = res.json()["questions"]
    texts = " ".join(q["question_text"] for q in questions)

    # Grounded in the project's own description.
    assert "tidal-drift sonar mapping" in texts
    # Grounded in the safe GitHub public-safe summary.
    assert "bathymetric-sweep scheduler" in texts
    # Grounded in the safe document summary (title / linked skill).
    assert "Sonar Calibration Notes" in texts

    # A purely generic plan would not name any of the above — this asserts the
    # questions are specific, not boilerplate.
    assert "Aurora Reef Monitor" in texts

    # No unsafe legacy field or value ever surfaces inside a question.
    for leaked in (
        "LEAK_SECRET_TOKEN",
        "secret_token",
        "SECRET raw document text",
        "raw_text",
        "vbr/uploads",
        "file_path",
    ):
        assert leaked not in texts, f"leaked unsafe field/value in question: {leaked}"


# ── Hostile GitHub value sanitization (scrub values, not only keys) ───────────
#
# The safe projection must scrub GitHub *values*, not only keys: a signed /
# tokenized repo_url and numeric score/confidence language in
# public_safe_summary must never reach the context view, the attach response, or
# a generated question — while a normal github.com owner/repo still displays.


def _project_with_hostile_github(
    mem_store: dict, github_proof: dict, *, description: str = "A platform."
) -> str:
    return _seed_project(
        mem_store,
        metadata={
            "description": description,
            "claimed_skills": ["Python"],
            "student_role": "",
            "individual_project_only": True,
            "attached_proofs": {"github_proof": github_proof},
            "phase": "project_defense_mvp_v1",
        },
    )


def _defense_surfaces(
    client: TestClient, project_id: str, mem_store: dict
) -> tuple[str, str, str]:
    """Serialized (context, attach-response, generated-questions) text for a
    project, so a single hostile value can be checked across all three surfaces
    Codex called out."""
    context_text = client.get(
        f"{BASE}/project-defense/projects/{project_id}/context"
    ).text
    doc = _seed_document_evidence(mem_store)
    attach_text = client.post(
        f"{BASE}/project-defense/projects/{project_id}/attach-proofs",
        json={"document_evidence_ids": [doc]},
    ).text
    questions = client.post(
        f"{BASE}/projects/{project_id}/generate-defense-questions"
    ).json()["questions"]
    question_text = " ".join(q["question_text"] for q in questions)
    return context_text, attach_text, question_text


def test_signed_github_repo_url_is_never_echoed_but_owner_repo_survives(
    client: TestClient, mem_store: dict
) -> None:
    """A github.com repo_url smuggling a signed/token query: the raw signed URL
    must not appear in context, attach response, or generated questions, but the
    owner/repo safely parsed from the github.com path still displays."""
    project_id = _project_with_hostile_github(
        mem_store,
        {
            "repo_url": "https://github.com/octocat/Hello-World?token=SECRETTOKEN123&X-Amz-Signature=abcSIG",
            "status": "analyzed",
            "detected_skills": ["Python"],
            "public_safe_summary": "Repo implements a tide-drift scheduler.",
        },
        description="A tide-drift scheduling service.",
    )

    context_text, attach_text, question_text = _defense_surfaces(client, project_id, mem_store)

    for surface in (context_text, attach_text, question_text):
        assert "SECRETTOKEN123" not in surface
        assert "X-Amz-Signature" not in surface
        assert "abcSIG" not in surface
        assert "token=" not in surface

    # Safe owner/repo, parsed from the github.com path, still displays.
    assert "octocat/Hello-World" in context_text
    assert "octocat/Hello-World" in attach_text
    # Grounded questions still link the canonical, query-stripped repo URL.
    assert "https://github.com/octocat/Hello-World" in question_text


def test_github_summary_score_confidence_text_is_stripped_everywhere(
    client: TestClient, mem_store: dict
) -> None:
    """Numeric score/confidence language in public_safe_summary must not reach
    the context view, the attach response, or a generated question — while the
    safe descriptive prose survives."""
    project_id = _project_with_hostile_github(
        mem_store,
        {
            "repo_url": "https://github.com/octocat/Hello-World",
            "status": "analyzed",
            "detected_skills": ["Python"],
            "public_safe_summary": "Repo shows a bathymetric-sweep scheduler with 72/100 confidence.",
        },
    )

    context_text, attach_text, question_text = _defense_surfaces(client, project_id, mem_store)

    for surface in (context_text, attach_text, question_text):
        assert "72/100" not in surface
        assert "72/100 confidence" not in surface

    # Safe descriptive prose about the evidence type survives.
    assert "bathymetric-sweep scheduler" in context_text
    assert "bathymetric-sweep scheduler" in question_text


@pytest.mark.parametrize(
    "hostile_repo_url",
    [
        "/Users/alice/private/repo",
        "s3://bucket/repo",
        "https://signed-storage.example.com/repo?token=secret",
    ],
)
def test_non_github_unsafe_repo_url_never_leaks_and_falls_back(
    client: TestClient, mem_store: dict, hostile_repo_url: str
) -> None:
    """A non-github.com repo_url (file path, s3://, signed storage URL) is never
    echoed anywhere; the evidence label falls back to a safe neutral label."""
    project_id = _project_with_hostile_github(
        mem_store,
        {
            "repo_url": hostile_repo_url,
            "status": "analyzed",
            "detected_skills": ["Python"],
            "public_safe_summary": "Repo implements a routing service.",
        },
    )

    context_text, attach_text, question_text = _defense_surfaces(client, project_id, mem_store)

    for surface in (context_text, attach_text, question_text):
        assert "signed-storage.example.com" not in surface
        assert "s3://bucket" not in surface
        assert "/Users/alice/private" not in surface
        assert "token=secret" not in surface

    # The evidence label falls back to a safe neutral label, never the raw value.
    assert "GitHub proof" in context_text
    assert "GitHub proof" in attach_text


def test_github_summary_inline_secrets_are_scrubbed_everywhere(
    client: TestClient, mem_store: dict
) -> None:
    """A public_safe_summary carrying standalone credential assignments
    (``api_key=…`` / ``client_secret=…``) must never surface the secret values in
    the context view, the attach response, or a generated question."""
    project_id = _project_with_hostile_github(
        mem_store,
        {
            "repo_url": "https://github.com/octocat/Hello-World",
            "status": "analyzed",
            "detected_skills": ["Python"],
            "public_safe_summary": (
                "Uses routing API api_key=sk-private and client_secret=abc123"
            ),
        },
    )

    context_text, attach_text, question_text = _defense_surfaces(client, project_id, mem_store)

    for surface in (context_text, attach_text, question_text):
        assert "sk-private" not in surface
        assert "abc123" not in surface
        assert "client_secret" not in surface
        assert "api_key=" not in surface

    # Safe owner/repo, parsed from the github.com path, still displays.
    assert "octocat/Hello-World" in context_text
    assert "octocat/Hello-World" in attach_text


def test_github_summary_bearer_and_private_ids_are_scrubbed_everywhere(
    client: TestClient, mem_store: dict
) -> None:
    """A public_safe_summary carrying an ``Authorization: Bearer <ghp_…>`` token
    and a ``source_id=user_…`` private identifier must never surface the token or
    the private id in the context view, attach response, or a generated
    question."""
    project_id = _project_with_hostile_github(
        mem_store,
        {
            "repo_url": "https://github.com/octocat/Hello-World",
            "status": "analyzed",
            "detected_skills": ["Python"],
            "public_safe_summary": (
                "Authorization: Bearer ghp_abcd1234 source_id=user_123"
            ),
        },
    )

    context_text, attach_text, question_text = _defense_surfaces(client, project_id, mem_store)

    for surface in (context_text, attach_text, question_text):
        assert "Bearer" not in surface
        assert "ghp_abcd1234" not in surface
        assert "source_id=user_123" not in surface
        assert "user_123" not in surface


def test_normal_github_summary_remains_usable_and_owner_repo_survives(
    client: TestClient, mem_store: dict
) -> None:
    """A benign public_safe_summary of safe project prose is reflected as-is (the
    secret scrubber never over-redacts normal words), and owner/repo still
    displays."""
    project_id = _project_with_hostile_github(
        mem_store,
        {
            "repo_url": "https://github.com/octocat/Hello-World",
            "status": "analyzed",
            "detected_skills": ["Python"],
            "public_safe_summary": (
                "Repository includes FastAPI endpoints, route scoring files, "
                "and GitHub Actions workflow."
            ),
        },
    )

    context_text, attach_text, question_text = _defense_surfaces(client, project_id, mem_store)

    # Safe descriptive prose survives the secret scrubber untouched.
    assert "FastAPI endpoints" in context_text
    assert "GitHub Actions" in context_text
    assert "route scoring files" in context_text
    assert "[redacted]" not in context_text
    # The safe owner/repo label still works.
    assert "octocat/Hello-World" in context_text
    assert "octocat/Hello-World" in attach_text


# ── Duplicate-project dedupe / canonicalization / evidence merge ─────────────

BOSTON_REPO_FULL_NAME = "machackgo/boston-smart-accident-risk-rerouting-google-cloud"
BOSTON_REPO_URL = f"https://github.com/{BOSTON_REPO_FULL_NAME}"


def _seed_repo_project(
    mem_store: dict,
    *,
    user_id: str = USER_ID,
    title: str,
    repo_full_name: str,
    attached_proofs: dict | None = None,
    project_defense_status: str | None = None,
    description: str = "Accident-risk-aware routing on Google Cloud.",
    claimed_skills: list[str] | None = None,
    created_at: str | None = None,
) -> str:
    """Seed a project row with an explicit repo identity + attached proofs so
    duplicate/historical rows for the same logical project can be constructed."""
    project_id = str(uuid4())
    now = created_at or _now()
    metadata: dict = {
        "description": description,
        "claimed_skills": claimed_skills if claimed_skills is not None else ["Python"],
        "student_role": "",
        "individual_project_only": True,
        "attached_proofs": attached_proofs or {},
        "phase": "project_defense_mvp_v1",
    }
    if project_defense_status is not None:
        metadata["project_defense_status"] = project_defense_status
    mem_store.setdefault("vbr_projects", {})[project_id] = {
        "id": project_id,
        "user_id": user_id,
        "title": title,
        "repo_url": f"https://github.com/{repo_full_name}",
        "repo_full_name": repo_full_name,
        "deployed_url": None,
        "head_sha": None,
        "status": "draft",
        "metadata": metadata,
        "created_at": now,
        "updated_at": now,
    }
    return project_id


def _boston_github_proof_summary() -> dict:
    return {
        "github_proof": {
            "repo_url": BOSTON_REPO_URL,
            "repo_owner": "machackgo",
            "repo_name": "boston-smart-accident-risk-rerouting-google-cloud",
            "status": "analyzed",
            "detected_skills": ["Python"],
            "public_safe_summary": "Repo demonstrates accident-risk rerouting.",
        }
    }


def test_eligible_projects_dedupe_repeated_boston_rows_into_one(
    client: TestClient, mem_store: dict
) -> None:
    # Three historical rows for the SAME logical Boston project (same repo).
    _seed_repo_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name=BOSTON_REPO_FULL_NAME,
        attached_proofs=_boston_github_proof_summary(),
    )
    _seed_repo_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name=BOSTON_REPO_FULL_NAME,
        attached_proofs={"documents": [{"document_evidence_id": "doc-1", "title": "Report.pdf"}]},
    )
    _seed_repo_project(
        mem_store,
        title="  boston smart accident risk rerouting ",  # different case/spacing
        repo_full_name=BOSTON_REPO_FULL_NAME,
    )
    # A different logical project must remain its own card.
    _seed_repo_project(
        mem_store,
        title="Teachable Machine Image Classification Demo",
        repo_full_name="machackgo/teachable-machine-demo",
    )

    res = client.get(f"{BASE}/project-defense/eligible-projects")
    assert res.status_code == 200
    projects = res.json()["projects"]

    boston_cards = [p for p in projects if "boston" in p["title"].lower()]
    assert len(boston_cards) == 1
    teachable_cards = [p for p in projects if "teachable" in p["title"].lower()]
    assert len(teachable_cards) == 1
    # One canonical card per logical project total.
    assert len(projects) == 2


def test_deduped_boston_card_shows_github_attached_from_any_duplicate(
    client: TestClient, mem_store: dict
) -> None:
    # The row WITHOUT GitHub is more recent, but the merged card must still show
    # GitHub attached because a sibling duplicate carries the proof.
    _seed_repo_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name=BOSTON_REPO_FULL_NAME,
        attached_proofs=_boston_github_proof_summary(),
        created_at="2026-01-01T00:00:00Z",
    )
    _seed_repo_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name=BOSTON_REPO_FULL_NAME,
        attached_proofs={},  # GitHub "missing" on this row alone
        created_at="2026-02-01T00:00:00Z",
    )

    res = client.get(f"{BASE}/project-defense/eligible-projects")
    boston = next(p for p in res.json()["projects"] if "boston" in p["title"].lower())

    assert boston["evidence"]["github_proof"]["attached"] is True
    assert boston["evidence"]["github_proof"]["label"] == BOSTON_REPO_FULL_NAME


def test_deduped_card_combines_unique_document_titles_and_count(
    client: TestClient, mem_store: dict
) -> None:
    _seed_repo_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name=BOSTON_REPO_FULL_NAME,
        attached_proofs={"documents": [{"document_evidence_id": "doc-1", "title": "Design Doc.pdf"}]},
    )
    _seed_repo_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name=BOSTON_REPO_FULL_NAME,
        attached_proofs={
            "documents": [
                {"document_evidence_id": "doc-2", "title": "Final Report.pdf"},
                # Duplicate id — must be de-duped, not double-counted.
                {"document_evidence_id": "doc-1", "title": "Design Doc.pdf"},
            ]
        },
    )

    res = client.get(f"{BASE}/project-defense/eligible-projects")
    boston = next(p for p in res.json()["projects"] if "boston" in p["title"].lower())

    docs = boston["evidence"]["documents"]
    assert docs["attached"] is True
    assert docs["count"] == 2
    assert "Design Doc.pdf" in docs["label"]
    assert "Final Report.pdf" in docs["label"]


def test_deduped_card_combines_website_proof_from_any_duplicate(
    client: TestClient, mem_store: dict
) -> None:
    _seed_repo_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name=BOSTON_REPO_FULL_NAME,
        attached_proofs=_boston_github_proof_summary(),
    )
    _seed_repo_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name=BOSTON_REPO_FULL_NAME,
        attached_proofs={
            "website_proofs": [
                {"proof_session_id": "ws-1", "target_website": "https://boston.vercel.app"}
            ]
        },
    )

    res = client.get(f"{BASE}/project-defense/eligible-projects")
    boston = next(p for p in res.json()["projects"] if "boston" in p["title"].lower())

    assert boston["evidence"]["website_proof"]["attached"] is True
    assert boston["evidence"]["website_proof"]["label"] == "https://boston.vercel.app"


def test_deduped_status_chooses_strongest_across_duplicates(
    client: TestClient, mem_store: dict
) -> None:
    # not_started + completed(analyzed) → the merged card is completed.
    _seed_repo_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name=BOSTON_REPO_FULL_NAME,
    )
    _seed_repo_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name=BOSTON_REPO_FULL_NAME,
        attached_proofs=_boston_github_proof_summary(),
        project_defense_status="analyzed",
    )

    res = client.get(f"{BASE}/project-defense/eligible-projects")
    boston = next(p for p in res.json()["projects"] if "boston" in p["title"].lower())

    assert boston["defense_status"] == "completed"
    assert boston["report_ready"] is True
    assert boston["evidence"]["project_defense"]["attached"] is True


def test_deduped_card_does_not_leak_unsafe_duplicate_metadata(
    client: TestClient, mem_store: dict
) -> None:
    _seed_repo_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name=BOSTON_REPO_FULL_NAME,
        attached_proofs={
            "github_proof": {
                **_boston_github_proof_summary()["github_proof"],
                # Unsafe legacy fields on a duplicate row.
                "repo_metadata": {"secret_token": "LEAK_SECRET_TOKEN"},
                "signed_url": "https://storage.example.com/x?token=abc",
                "confidence_score": 72,
            },
            "skill_pipeline_ids": ["pipeline-secret-1"],
        },
    )
    _seed_repo_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name=BOSTON_REPO_FULL_NAME,
    )

    res = client.get(f"{BASE}/project-defense/eligible-projects")
    for leaked in (
        "LEAK_SECRET_TOKEN",
        "secret_token",
        "repo_metadata",
        "signed_url",
        "confidence_score",
        "pipeline-secret-1",
    ):
        assert leaked not in res.text, f"leaked unsafe duplicate field/value: {leaked}"


def test_selected_context_uses_merged_evidence_across_duplicates(
    client: TestClient, mem_store: dict
) -> None:
    """Opening the canonical card's workspace shows the merged evidence package
    — it must not regress to a weaker duplicate that is missing GitHub."""
    # Canonical (strongest / has GitHub) vs a weaker duplicate with a document.
    canonical_id = _seed_repo_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name=BOSTON_REPO_FULL_NAME,
        attached_proofs=_boston_github_proof_summary(),
    )
    _seed_repo_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name=BOSTON_REPO_FULL_NAME,
        attached_proofs={"documents": [{"document_evidence_id": "doc-1", "title": "Report.pdf"}]},
    )

    res = client.get(f"{BASE}/project-defense/projects/{canonical_id}/context")
    assert res.status_code == 200
    body = res.json()

    # Merged: GitHub (from canonical) AND the document (from the duplicate).
    assert body["evidence"]["github_proof"]["attached"] is True
    assert body["evidence"]["github_proof"]["label"] == BOSTON_REPO_FULL_NAME
    assert body["evidence"]["documents"]["attached"] is True
    assert body["evidence"]["documents"]["count"] == 1


def test_generated_questions_use_merged_github_from_duplicate(
    client: TestClient, mem_store: dict
) -> None:
    """Question generation on the canonical (GitHub-missing) row must still weave
    in the repository, because a sibling duplicate carries the GitHub proof."""
    # Canonical row (most recent) lacks GitHub; older duplicate has it.
    canonical_id = _seed_repo_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name=BOSTON_REPO_FULL_NAME,
        claimed_skills=["Python"],
        attached_proofs={},
        created_at="2026-03-01T00:00:00Z",
    )
    _seed_repo_project(
        mem_store,
        title="Boston Smart Accident Risk Rerouting",
        repo_full_name=BOSTON_REPO_FULL_NAME,
        claimed_skills=["Python"],
        attached_proofs=_boston_github_proof_summary(),
        created_at="2026-01-01T00:00:00Z",
    )

    res = client.post(f"{BASE}/projects/{canonical_id}/generate-defense-questions")
    assert res.status_code == 200, res.text
    texts = " ".join(q["question_text"] for q in res.json()["questions"])

    # The merged GitHub repo URL is woven into the skill-linkage question.
    assert BOSTON_REPO_URL in texts
    assert "Python" in texts


# ── Same repo, DIFFERENT projects must NOT merge (must-fix 1) ─────────────────
#
# A single monorepo can hold many distinct projects. Repository identity may
# strengthen a match but must never collapse two different project titles.

ACME_MONO_REPO = "acme/mono"


def _seed_billing_and_analytics(mem_store: dict) -> tuple[str, str]:
    """Two DIFFERENT logical projects that happen to share one monorepo."""
    billing = _seed_repo_project(
        mem_store,
        title="Billing Service",
        repo_full_name=ACME_MONO_REPO,
        description="Handles invoicing and payments.",
        claimed_skills=["Python"],
        attached_proofs={
            "documents": [{"document_evidence_id": "bill-doc", "title": "Billing Spec.pdf"}]
        },
    )
    analytics = _seed_repo_project(
        mem_store,
        title="Analytics Dashboard",
        repo_full_name=ACME_MONO_REPO,
        description="Charts and metrics dashboard.",
        claimed_skills=["React"],
        attached_proofs={
            "website_proofs": [
                {"proof_session_id": "an-ws", "target_website": "https://analytics.example.com"}
            ]
        },
    )
    return billing, analytics


def test_same_repo_different_titles_render_as_two_cards(client: TestClient, mem_store: dict) -> None:
    _seed_billing_and_analytics(mem_store)

    res = client.get(f"{BASE}/project-defense/eligible-projects")
    assert res.status_code == 200
    projects = res.json()["projects"]

    titles = {p["title"] for p in projects}
    assert "Billing Service" in titles
    assert "Analytics Dashboard" in titles
    # Two distinct cards — the shared repo did NOT collapse them.
    assert len(projects) == 2

    billing = next(p for p in projects if p["title"] == "Billing Service")
    analytics = next(p for p in projects if p["title"] == "Analytics Dashboard")

    # Evidence must not cross-contaminate across the two projects.
    assert billing["evidence"]["documents"]["attached"] is True
    assert billing["evidence"]["website_proof"]["attached"] is False
    assert analytics["evidence"]["website_proof"]["attached"] is True
    assert analytics["evidence"]["documents"]["attached"] is False


def test_same_repo_different_titles_workspaces_are_isolated(
    client: TestClient, mem_store: dict
) -> None:
    billing, analytics = _seed_billing_and_analytics(mem_store)

    billing_ctx = client.get(f"{BASE}/project-defense/projects/{billing}/context").json()
    assert billing_ctx["evidence"]["documents"]["attached"] is True
    assert billing_ctx["evidence"]["documents"]["label"] == "Billing Spec.pdf"
    # The Billing workspace must NOT show the Analytics website/defense evidence.
    assert billing_ctx["evidence"]["website_proof"]["attached"] is False

    analytics_res = client.get(f"{BASE}/project-defense/projects/{analytics}/context")
    analytics_ctx = analytics_res.json()
    assert analytics_ctx["evidence"]["website_proof"]["attached"] is True
    assert analytics_ctx["evidence"]["website_proof"]["label"] == "https://analytics.example.com"
    # The Analytics workspace must NOT show the Billing document evidence.
    assert analytics_ctx["evidence"]["documents"]["attached"] is False
    assert "Billing Spec.pdf" not in analytics_res.text


# ── Unsafe display VALUES are scrubbed, not only unsafe keys (must-fix 2) ─────


def test_hostile_document_title_and_signed_website_are_scrubbed_everywhere(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _seed_repo_project(
        mem_store,
        title="Hostile Evidence Project",
        repo_full_name="acme/hostile",
        claimed_skills=["Python"],
        attached_proofs={
            "documents": [
                {"document_evidence_id": "d1", "title": "/Users/alice/private/report.pdf"}
            ],
            "website_proofs": [
                {
                    "proof_session_id": "w1",
                    "target_website": "https://storage.example.com/dl?token=SECRET_TOKEN&X-Amz-Signature=abc",
                }
            ],
        },
    )

    listed = client.get(f"{BASE}/project-defense/eligible-projects").text
    ctx = client.get(f"{BASE}/project-defense/projects/{project_id}/context")
    questions = client.post(f"{BASE}/projects/{project_id}/generate-defense-questions")
    assert questions.status_code == 200, questions.text

    # The hostile file path and signed-URL token never appear on ANY surface.
    for surface in (listed, ctx.text, questions.text):
        for leaked in ("/Users/alice", "SECRET_TOKEN", "X-Amz-Signature", "token="):
            assert leaked not in surface, f"leaked unsafe value: {leaked}"

    body = ctx.json()
    # Only the safe hostname survives for the website (query/token dropped).
    assert body["evidence"]["website_proof"]["label"] == "https://storage.example.com"
    assert (
        body["metadata"]["attached_proofs"]["website_proofs"][0]["target_website"]
        == "https://storage.example.com"
    )
    # The hostile document title is replaced with a safe fallback.
    assert body["evidence"]["documents"]["label"] == "Document proof"
    assert body["metadata"]["attached_proofs"]["documents"][0]["title"] == "Document proof"


# ── Attach endpoint returns the safe DTO / projection (must-fix 3) ────────────


def test_attach_response_returns_safe_dto_scrubbing_legacy_metadata(
    client: TestClient, mem_store: dict
) -> None:
    """The attach endpoint must apply the same allowlisted/sanitized projection
    even when the project already carries hostile legacy metadata — the response
    exposes a safe DTO, never raw ``metadata.attached_proofs``."""
    project_id = _seed_repo_project(
        mem_store,
        title="Legacy Hostile Project",
        repo_full_name="acme/legacy",
        claimed_skills=["Python"],
        attached_proofs={
            # Unsafe top-level legacy keys.
            "github_proof_id": "gh-private-id-123",
            "skill_pipeline_ids": ["pipeline-secret-1"],
            "documents": [
                {
                    "document_evidence_id": "doc-private-999",
                    "title": "/Users/alice/private/report.pdf",
                    "file_path": "vbr/uploads/secret.pdf",
                    "raw_text": "SECRET RAW TEXT that must not leak",
                    "analysis_score": 88,
                }
            ],
            "website_proofs": [
                {
                    "proof_session_id": "ws-private-555",
                    "target_website": "https://storage.example.com/x?token=SIGNED_TOKEN",
                    "signed_url": "https://storage.example.com/y?token=abc",
                    "evidence_strength_score": 75,
                }
            ],
        },
    )
    # Attach a new, safe document by id.
    new_doc = _seed_document_evidence(mem_store)

    res = client.post(
        f"{BASE}/project-defense/projects/{project_id}/attach-proofs",
        json={"document_evidence_ids": [new_doc]},
    )
    assert res.status_code == 200
    body = res.json()

    attached = body["metadata"]["attached_proofs"]
    # Only allowlisted safe keys survive on each document / website summary.
    for doc in attached["documents"]:
        assert set(doc.keys()) == {"title", "source_type", "status", "skills"}
    for web in attached["website_proofs"]:
        assert set(web.keys()) == {"target_website", "workflow_confidence", "supported_skills"}
        assert web["target_website"] == "https://storage.example.com"

    # The hostile legacy document title is scrubbed to the safe fallback.
    doc_titles = [d["title"] for d in attached["documents"]]
    assert "/Users/alice/private/report.pdf" not in doc_titles
    assert "Document proof" in doc_titles

    # Safe attached counts / labels are still present.
    assert body["evidence"]["documents"]["attached"] is True
    assert body["evidence"]["documents"]["count"] == 2

    # No raw metadata.attached_proofs, private id, path, signed URL, provider
    # blob, raw text, or numeric score appears anywhere in the response.
    serialized = res.text
    for leaked in (
        "gh-private-id-123",
        "pipeline-secret-1",
        "doc-private-999",
        "ws-private-555",
        "/Users/alice",
        "vbr/uploads",
        "SECRET RAW TEXT",
        "raw_text",
        "file_path",
        "signed_url",
        "analysis_score",
        "evidence_strength_score",
        "SIGNED_TOKEN",
        "token=",
    ):
        assert leaked not in serialized, f"leaked unsafe field/value: {leaked}"
