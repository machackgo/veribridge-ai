"""Tests for the Verified Work Passport (v1).

Owner-only:
  ``GET  /api/v1/student/vbr/passport``
  ``GET  /api/v1/student/vbr/passport/status``
  ``POST /api/v1/student/vbr/passport/publish``
  ``POST /api/v1/student/vbr/passport/unpublish``

Public (no auth):
  ``GET  /api/v1/public/p/{public_slug}``

Covers:
  - private passport is owner-scoped and groups evidence by skill / project
  - publish mints a stable slug; non-owner gets their own (separate) passport
  - public passport resolves only when published; invalid / unpublished 404
  - public passport features only projects with an active public report token
  - unpublishing a VBR report hides that project from the public passport
  - unpublishing the passport 404s the public surface but keeps the report
    tokens and the project rows (evidence) intact
  - public passport excludes raw/private fields, internal ids, numeric scores

All storage is in-memory (dict mode). No network / LLM calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.services.safe_public_url import is_safe_public_url

from tests.test_vbr_project_defense import (
    DEFENSE_TRANSCRIPT,
    OTHER_USER_ID,
    USER_ID,
    VIDEO_TRANSCRIPT_SEGMENTS,
    _create_project_defense,
    _generate_questions,
    _seed_auto_video_transcript,
    _seed_document_evidence,
    _seed_github_proof,
    _seed_workflow_analysis,
    _submit_defense,
)
from uuid import uuid4


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


def _get_private(client: TestClient):
    return client.get("/api/v1/student/vbr/passport")


def _get_status(client: TestClient):
    return client.get("/api/v1/student/vbr/passport/status")


def _publish(client: TestClient, **body):
    return client.post("/api/v1/student/vbr/passport/publish", json=body or None)


def _unpublish(client: TestClient):
    return client.post("/api/v1/student/vbr/passport/unpublish")


def _get_public(client: TestClient, slug: str):
    return client.get(f"/api/v1/public/p/{slug}")


def _publish_project_report(client: TestClient, project_id: str):
    return client.post(f"/api/v1/student/vbr/projects/{project_id}/public-report")


def _unpublish_project_report(client: TestClient, project_id: str):
    return client.delete(f"/api/v1/student/vbr/projects/{project_id}/public-report")


def _make_full_project(client: TestClient, mem_store: dict) -> str:
    github_proof_id = _seed_github_proof(mem_store)
    document_id = _seed_document_evidence(mem_store)
    website_proof_session_id = _seed_workflow_analysis(mem_store)
    created = _create_project_defense(
        client,
        attached_proofs={
            "github_proof_id": github_proof_id,
            "document_evidence_ids": [document_id],
            "website_proof_session_ids": [website_proof_session_id],
        },
    ).json()
    project_id = created["project"]["id"]
    session_id = _generate_questions(client, project_id).json()["session_id"]

    chunk_id = str(uuid4())
    mem_store.setdefault("vbr_video_chunks", {})[chunk_id] = {
        "id": chunk_id,
        "session_id": session_id,
        "chunk_index": 0,
        "bytes": 1024,
        "sha256": "deadbeef",
    }
    _seed_auto_video_transcript(mem_store, session_id, VIDEO_TRANSCRIPT_SEGMENTS)
    _submit_defense(client, session_id, combined_text=DEFENSE_TRANSCRIPT)
    return project_id


# ── Private passport ──────────────────────────────────────────────────────────

def test_private_passport_groups_skills_and_projects(client: TestClient, mem_store: dict) -> None:
    project_id = _make_full_project(client, mem_store)

    body = _get_private(client).json()
    assert body["project_count"] == 1
    assert len(body["projects"]) == 1
    proj = body["projects"][0]
    assert proj["project_id"] == project_id
    assert "GitHub Proof" in proj["evidence_sources"]
    assert "Project Defense" in proj["evidence_sources"]
    assert proj["report"]["is_public"] is False

    # Skills are grouped with qualitative labels only.
    assert body["skills"]
    for skill in body["skills"]:
        assert skill["status"] in {
            "Demonstrated",
            "Partially demonstrated",
            "Evidence observed",
            "Supporting evidence",
            "Needs review",
            "Not assessed",
        }


def test_private_passport_groups_duplicate_project_rows(client: TestClient, mem_store: dict) -> None:
    # Three Project Defense rows for the SAME repo (e.g. repeated attempts).
    # The passport must collapse them into ONE evidence card, not three.
    p1 = _make_full_project(client, mem_store)
    _make_full_project(client, mem_store)
    _make_full_project(client, mem_store)

    body = _get_private(client).json()
    assert body["project_count"] == 1
    assert len(body["projects"]) == 1
    card = body["projects"][0]
    assert card["attempt_count"] == 3
    # Evidence badges are unioned onto the single card (no duplicate cards).
    assert "GitHub Proof" in card["evidence_sources"]
    assert "Project Defense" in card["evidence_sources"]
    # Skills aggregate over distinct projects, so each appears once.
    skill_names = [s["skill"] for s in body["skills"]]
    assert len(skill_names) == len(set(skill_names))

    # Publishing one duplicate's report surfaces the published status on the card.
    _publish_project_report(client, p1)
    card = _get_private(client).json()["projects"][0]
    assert card["report"]["is_public"] is True


def test_public_passport_collapses_duplicate_published_reports(client: TestClient, mem_store: dict) -> None:
    # Two duplicate rows of the same project, both with published reports, must
    # appear as a SINGLE featured card on the public passport.
    p1 = _make_full_project(client, mem_store)
    p2 = _make_full_project(client, mem_store)
    _publish_project_report(client, p1)
    _publish_project_report(client, p2)
    slug = _publish(client).json()["public_slug"]

    app.dependency_overrides.pop(get_current_user_id, None)
    body = _get_public(client, slug).json()
    assert body["featured_project_count"] == 1


def test_private_passport_is_owner_scoped(client: TestClient) -> None:
    _create_project_defense(client)

    _as_user(OTHER_USER_ID)
    body = _get_private(client).json()
    assert body["project_count"] == 0
    assert body["projects"] == []


def test_private_passport_shows_published_report_action(client: TestClient, mem_store: dict) -> None:
    project_id = _make_full_project(client, mem_store)
    _publish_project_report(client, project_id)

    body = _get_private(client).json()
    assert body["published_report_count"] == 1
    proj = body["projects"][0]
    assert proj["report"]["is_public"] is True
    assert proj["report"]["public_path"].startswith("/vbr/report/")


def test_private_skill_drilldown_has_safe_detail(client: TestClient, mem_store: dict) -> None:
    project_id = _make_full_project(client, mem_store)
    body = _get_private(client).json()
    assert body["skills"]
    skill = body["skills"][0]
    # Drilldown detail is present and references the owner's project for linking.
    assert "evidence_sources" in skill
    assert skill["projects"]
    ref = skill["projects"][0]
    assert ref["project_id"] == project_id  # owner-only, used for the report preview link
    for chip in skill["evidence_chips"]:
        assert set(chip.keys()) == {"label", "short_summary", "source"}


def test_public_skill_drilldown_excludes_private_and_unpublished(client: TestClient, mem_store: dict) -> None:
    published = _make_full_project(client, mem_store)
    # A second project with NO published report — its evidence must not surface.
    _make_full_project(client, mem_store)
    _publish_project_report(client, published)
    slug = _publish(client).json()["public_slug"]

    app.dependency_overrides.pop(get_current_user_id, None)
    body = _get_public(client, slug).json()
    assert body["top_skills"]
    serialized = str(body["top_skills"])
    # No owner-only project ids leak into the public skill drilldown.
    assert "project_id" not in serialized
    assert USER_ID not in serialized
    for skill in body["top_skills"]:
        # Every linked project is a published public report path only.
        for ref in skill["projects"]:
            assert ref["public_report_path"].startswith("/vbr/report/")
            assert "project_id" not in ref


def test_public_skill_drilldown_document_traces_are_safe_and_consistent(
    client: TestClient, mem_store: dict
) -> None:
    """Published report-backed document traces appear in the public passport
    drilldown only for the skill they were matched to, and stay safe."""
    document_id = _seed_document_evidence(
        mem_store,
        evidence_objects=[{"skill_name": "Python", "confidence": "high", "snippet": "leak-me-not"}],
    )
    project_id = _create_project_defense(
        client, attached_proofs={"document_evidence_ids": [document_id]}
    ).json()["project"]["id"]
    _publish_project_report(client, project_id)
    slug = _publish(client).json()["public_slug"]

    app.dependency_overrides.pop(get_current_user_id, None)
    response = _get_public(client, slug)
    assert response.status_code == 200, response.text
    body = response.json()
    skills = {s["skill"]: s for s in body["top_skills"]}

    # Python carries a safe, conservative Document Proof trace for itself only.
    py_doc_traces = [
        t for t in skills["Python"]["evidence_traces"] if t["source_type"] == "Document Proof"
    ]
    assert py_doc_traces
    for trace in py_doc_traces:
        assert trace["is_publicly_openable"] is False
        assert trace["public_url"] is None
        assert trace["skill_names"] == ["Python"]

    # React was never matched by the document → no Document Proof trace claims it.
    react = skills.get("React")
    if react is not None:
        assert all(
            t["source_type"] != "Document Proof" for t in react["evidence_traces"]
        )

    assert "leak-me-not" not in response.text


# ── Publish / status ownership ────────────────────────────────────────────────

def test_status_unpublished_by_default(client: TestClient) -> None:
    body = _get_status(client).json()
    assert body["is_published"] is False
    assert body["public_slug"] is None
    assert body["public_path"] is None


def test_publish_mints_stable_slug(client: TestClient) -> None:
    first = _publish(client).json()
    assert first["is_published"] is True
    assert first["public_slug"]
    assert first["public_path"] == f"/p/{first['public_slug']}"

    second = _publish(client).json()
    assert second["public_slug"] == first["public_slug"]


def test_publish_accepts_safe_headline_summary(client: TestClient) -> None:
    body = _publish(client, headline="Full-stack builder", summary="I ship and defend my work.").json()
    assert body["headline"] == "Full-stack builder"
    assert body["summary"] == "I ship and defend my work."


def test_publish_is_per_user(client: TestClient) -> None:
    owner_slug = _publish(client).json()["public_slug"]

    _as_user(OTHER_USER_ID)
    other_slug = _publish(client).json()["public_slug"]
    assert other_slug != owner_slug


# ── Public passport (no auth) ─────────────────────────────────────────────────

def test_public_passport_requires_published(client: TestClient) -> None:
    # Minted but not yet published? Publishing is required; before publish there
    # is no slug at all, so any slug 404s.
    assert _get_public(client, "definitely-not-real").status_code == 404


def test_public_passport_resolves_when_published(client: TestClient, mem_store: dict) -> None:
    project_id = _make_full_project(client, mem_store)
    _publish_project_report(client, project_id)
    slug = _publish(client).json()["public_slug"]

    # Prove no auth required.
    app.dependency_overrides.pop(get_current_user_id, None)
    res = _get_public(client, slug)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["featured_project_count"] == 1
    assert body["featured_projects"][0]["public_report_path"].startswith("/vbr/report/")
    assert body["top_skills"]
    assert body["verification_note"]


def test_public_passport_features_only_projects_with_public_report(client: TestClient, mem_store: dict) -> None:
    # One project with a published report, one without.
    published = _make_full_project(client, mem_store)
    _make_full_project(client, mem_store)
    _publish_project_report(client, published)
    slug = _publish(client).json()["public_slug"]

    body = _get_public(client, slug).json()
    assert body["featured_project_count"] == 1


def test_unpublishing_report_hides_project_from_public_passport(client: TestClient, mem_store: dict) -> None:
    project_id = _make_full_project(client, mem_store)
    _publish_project_report(client, project_id)
    slug = _publish(client).json()["public_slug"]

    assert _get_public(client, slug).json()["featured_project_count"] == 1

    _unpublish_project_report(client, project_id)
    assert _get_public(client, slug).json()["featured_project_count"] == 0


def test_unpublishing_passport_404s_public_but_keeps_evidence(client: TestClient, mem_store: dict) -> None:
    project_id = _make_full_project(client, mem_store)
    report_token = _publish_project_report(client, project_id).json()["public_token"]
    slug = _publish(client).json()["public_slug"]

    assert _get_public(client, slug).status_code == 200

    _unpublish(client)
    assert _get_public(client, slug).status_code == 404

    # The individual VBR report token still resolves (passport unpublish does
    # not revoke report links), and the project row is intact.
    assert client.get(f"/api/v1/public/vbr/reports/{report_token}").status_code == 200
    assert project_id in mem_store.get("vbr_projects", {})

    # Re-publishing restores the same slug.
    assert _publish(client).json()["public_slug"] == slug


def test_invalid_slug_returns_404(client: TestClient) -> None:
    _publish(client)
    assert _get_public(client, "totally-wrong-slug").status_code == 404


# ── Public passport safety ────────────────────────────────────────────────────

_FORBIDDEN_SUBSTRINGS = (
    "/100",
    "trust score",
    "fully verified",
    "supabase.co/storage",
    "should-never-leak",
    "secret_token",
)


def test_public_passport_excludes_unsafe_content(client: TestClient, mem_store: dict) -> None:
    project_id = _make_full_project(client, mem_store)
    _publish_project_report(client, project_id)
    slug = _publish(client).json()["public_slug"]

    raw = _get_public(client, slug).text.lower()
    for needle in _FORBIDDEN_SUBSTRINGS:
        assert needle not in raw, f"public passport leaked {needle!r}"

    body = _get_public(client, slug).json()
    # No internal ids / private identifiers anywhere in the projection.
    serialized = str(body)
    assert USER_ID not in serialized
    assert "user_id" not in body
    assert "public_token" not in str(body["featured_projects"])
    # No percentages-as-scores survive.
    assert "%" not in raw or "confidence" in raw  # workflow_confidence is a word label, not a %


# ── Migration RLS guarantees ──────────────────────────────────────────────────
#
# vbr_work_passports is user-owned and underpins a public/recruiter-facing
# surface, so migration 052 MUST lock the table down with RLS. Public access is
# served only via the API public endpoint (service role), never anon direct
# read. These assertions guard that contract at the SQL level.

_MIGRATION_052 = (
    Path(__file__).resolve().parents[1]
    / "app" / "db" / "migrations" / "052_vbr_work_passport.sql"
)


@pytest.fixture(scope="module")
def migration_052_sql() -> str:
    return _MIGRATION_052.read_text(encoding="utf-8").lower()


def test_migration_enables_row_level_security(migration_052_sql: str) -> None:
    assert (
        "alter table public.vbr_work_passports enable row level security"
        in migration_052_sql
    )


def test_migration_has_owner_select_policy(migration_052_sql: str) -> None:
    assert '"vbr_work_passports: own row select"' in migration_052_sql
    assert "for select" in migration_052_sql
    assert "user_id::text = (select auth.uid())::text" in migration_052_sql


def test_migration_has_owner_insert_policy(migration_052_sql: str) -> None:
    assert '"vbr_work_passports: own row insert"' in migration_052_sql
    assert "for insert" in migration_052_sql


def test_migration_has_owner_update_policy(migration_052_sql: str) -> None:
    assert '"vbr_work_passports: own row update"' in migration_052_sql
    assert "for update" in migration_052_sql


def test_migration_has_no_anonymous_select_policy(migration_052_sql: str) -> None:
    # Public access must flow through the API serializer, not a Supabase anon
    # direct read. No policy may grant the anon role on this table.
    assert "to anon" not in migration_052_sql
    assert "to public" not in migration_052_sql


def test_migration_preserves_slug_unique_index(migration_052_sql: str) -> None:
    # RLS additions must not drop the existing public_slug uniqueness guard.
    assert "vbr_work_passports_public_slug_unique_idx" in migration_052_sql


# ── Evidence traceability aggregation ────────────────────────────────────────

def test_private_passport_skill_drilldown_includes_evidence_traces(client: TestClient, mem_store: dict) -> None:
    _make_full_project(client, mem_store)
    body = _get_private(client).json()

    assert body["skills"]
    traced = [s for s in body["skills"] if s.get("evidence_traces")]
    assert traced, "expected at least one skill with aggregated evidence traces"
    skill = traced[0]
    source_types = {t["source_type"] for t in skill["evidence_traces"]}
    assert source_types & {"GitHub Proof", "Document Proof", "Project Defense", "Video Evidence"}
    for trace in skill["evidence_traces"]:
        # Trace fields are safe — no raw evidence, storage paths, or media URLs.
        assert "trace_id" in trace and "source_type" in trace
        assert ".webm" not in str(trace) and "storage_path" not in str(trace)


def test_public_passport_skill_traces_are_published_only(client: TestClient, mem_store: dict) -> None:
    published = _make_full_project(client, mem_store)
    # A second project with NO published report — its evidence must never surface.
    _make_full_project(client, mem_store)
    _publish_project_report(client, published)
    slug = _publish(client).json()["public_slug"]

    app.dependency_overrides.pop(get_current_user_id, None)
    body = _get_public(client, slug).json()

    assert body["top_skills"]
    traced = [s for s in body["top_skills"] if s.get("evidence_traces")]
    assert traced, "expected published-report-backed evidence traces in public passport"
    serialized = str(body["top_skills"])
    # No owner-only ids / private fields leak into public traces.
    assert "project_id" not in serialized
    assert USER_ID not in serialized
    for skill in body["top_skills"]:
        for trace in skill.get("evidence_traces") or []:
            # Any direct link in a public trace must be a safe public URL.
            if trace.get("public_url"):
                assert is_safe_public_url(trace["public_url"])
            assert ".webm" not in str(trace)


def test_unpublished_project_traces_absent_from_public_passport(client: TestClient, mem_store: dict) -> None:
    # Only an unpublished project exists → the public passport features nothing,
    # and therefore exposes no evidence traces at all.
    _make_full_project(client, mem_store)
    slug = _publish(client).json()["public_slug"]

    app.dependency_overrides.pop(get_current_user_id, None)
    body = _get_public(client, slug).json()
    assert body["featured_project_count"] == 0
    assert all(not s.get("evidence_traces") for s in body["top_skills"])
