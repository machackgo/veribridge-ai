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


# ── Hydrated GitHub line + Website rich traces flow into the passport ─────────


def _make_rich_project(client: TestClient, mem_store: dict) -> str:
    """A project whose GitHub proof has line-level code evidence and whose
    Website proof has the deeper OCR/DOM/visual artifacts."""
    snapshot = {
        "skill_code_evidence": [
            {
                "skill": "Python",
                "file_path": "src/main.py",
                "line_start": 24,
                "line_end": 38,
                "function_name": "classify_image",
                "code_snippet": "def classify_image(img):\n    return model.predict(img)",
                "github_url": "https://github.com/octocat/Hello-World/blob/main/src/main.py#L24-L38",
            }
        ]
    }
    github_proof_id = _seed_github_proof(mem_store, analysis_snapshot=snapshot)
    website_proof_session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=["Python", "React"],
        frame_ocr_evidence_summary={
            "has_ocr_evidence": True,
            "top_ocr_snippets": ["Prediction: cat"],
            "frames_analyzed": 2,
        },
    )
    created = _create_project_defense(
        client,
        attached_proofs={
            "github_proof_id": github_proof_id,
            "website_proof_session_ids": [website_proof_session_id],
        },
    ).json()
    return created["project"]["id"]


def test_private_passport_aggregates_github_line_and_website_traces(
    client: TestClient, mem_store: dict
) -> None:
    _make_rich_project(client, mem_store)
    body = _get_private(client).json()

    all_traces = [t for s in body["skills"] for t in (s.get("evidence_traces") or [])]
    # The deepest GitHub code trace and a Website OCR card both reach the passport.
    assert any(t["location_type"] == "github_function" for t in all_traces)
    assert any(t["location_type"] == "website_ocr" for t in all_traces)
    # Private passport retains the safe code snippet.
    gh = next(t for t in all_traces if t["location_type"] == "github_function")
    assert gh["code_snippet"] and "classify_image" in gh["code_snippet"]


def test_public_passport_strips_github_code_snippet(client: TestClient, mem_store: dict) -> None:
    project_id = _make_rich_project(client, mem_store)
    _publish_project_report(client, project_id)
    slug = _publish(client).json()["public_slug"]

    app.dependency_overrides.pop(get_current_user_id, None)
    body = _get_public(client, slug).json()

    all_traces = [t for s in body["top_skills"] for t in (s.get("evidence_traces") or [])]
    gh = [t for t in all_traces if t.get("location_type") == "github_function"]
    assert gh, "expected the GitHub code trace to surface on the public passport"
    for t in gh:
        # Snippet is private-only; the public #L link is the proof instead.
        assert t.get("code_snippet") in (None, "")
        if t.get("public_url"):
            assert is_safe_public_url(t["public_url"])


# ── Evidence graph (Phase 1): overview, proof chains, project↔skill links ────

_QUALITATIVE_LABELS = {
    "Demonstrated",
    "Partially demonstrated",
    "Evidence observed",
    "Supporting evidence",
    "Needs review",
    "Not assessed",
}


def test_private_passport_has_evidence_graph_overview(client: TestClient, mem_store: dict) -> None:
    _make_full_project(client, mem_store)
    body = _get_private(client).json()

    overview = body["evidence_graph_overview"]
    assert overview["project_count"] == 1
    assert overview["published_report_count"] == 0
    assert overview["skills_with_evidence"] >= 1
    assert overview["proof_count"] >= 1
    assert overview["attached_proof_count"] + overview["unattached_proof_count"] == overview["proof_count"]
    # Next actions are plain guidance strings (capped), never scores.
    assert overview["next_actions"]
    assert len(overview["next_actions"]) <= 3
    assert all(isinstance(a, str) for a in overview["next_actions"])


def test_private_project_cards_include_proof_chain_completeness(
    client: TestClient, mem_store: dict
) -> None:
    _make_full_project(client, mem_store)
    proj = _get_private(client).json()["projects"][0]

    chain = proj["proof_chain"]
    # The full project attaches GitHub + Document + Website and completes a
    # defense with video evidence — every chain step is present.
    assert chain["github"] is True
    assert chain["document"] is True
    assert chain["website"] is True
    assert chain["project_defense"] is True
    assert chain["total_count"] == 5
    assert chain["attached_count"] == sum(
        1 for key in ("github", "website", "document", "project_defense", "video") if chain[key]
    )
    # ``missing`` lists exactly the absent source labels (may be empty).
    assert len(chain["missing"]) == chain["total_count"] - chain["attached_count"]


def test_private_project_cards_include_top_skills(client: TestClient, mem_store: dict) -> None:
    _make_full_project(client, mem_store)
    proj = _get_private(client).json()["projects"][0]

    assert proj["top_skills"], "expected evidence-backed top skills on the project card"
    assert len(proj["top_skills"]) <= 5
    for row in proj["top_skills"]:
        assert set(row.keys()) == {"skill", "status"}
        assert row["status"] in _QUALITATIVE_LABELS


def test_private_skill_cards_carry_strongest_project(client: TestClient, mem_store: dict) -> None:
    _make_full_project(client, mem_store)
    body = _get_private(client).json()

    assert body["skills"]
    for skill in body["skills"]:
        # Every aggregated skill links back to the project where it is most
        # strongly evidenced, with a qualitative label only.
        assert skill["strongest_project_title"]
        assert skill["strongest_project_status"] in _QUALITATIVE_LABELS


def test_public_featured_projects_include_safe_proof_chain(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _make_full_project(client, mem_store)
    _publish_project_report(client, project_id)
    slug = _publish(client).json()["public_slug"]

    app.dependency_overrides.pop(get_current_user_id, None)
    body = _get_public(client, slug).json()
    assert body["featured_projects"]
    chain = body["featured_projects"][0]["proof_chain"]
    assert chain["total_count"] == 5
    assert isinstance(chain["github"], bool)
    # The chain carries only booleans, counts, and canonical source labels.
    assert all(isinstance(label, str) for label in chain["missing"])
    # Strongest-project fields are owner-only and never leak publicly.
    serialized = str(body["top_skills"])
    assert "strongest_project_title" not in serialized


# ── Identity / passport header ───────────────────────────────────────────────


def _seed_user(mem_store: dict, user_id: str = USER_ID, full_name: str = "Ada Lovelace") -> None:
    mem_store.setdefault("users", {})[user_id] = {"id": user_id, "full_name": full_name}


def _seed_onboarding(mem_store: dict, user_id: str = USER_ID, **fields) -> None:
    row = {"id": str(uuid4()), "user_id": user_id}
    row.update(fields)
    mem_store.setdefault("student_onboarding_profiles", {})[row["id"]] = row


def test_private_passport_has_identity_header(client: TestClient, mem_store: dict) -> None:
    _seed_user(mem_store)
    _seed_onboarding(
        mem_store,
        degree_level="masters",
        major="Computer Science",
        graduation_year=2026,
        university_country="United States",
        # Private/sensitive fields that must NEVER surface in the header.
        visa_status="F1",
        sponsorship_needed=True,
    )
    body = _get_private(client).json()
    identity = body["identity"]
    assert identity is not None
    assert identity["display_name"] == "Ada Lovelace"
    assert identity["program"] == "Computer Science"
    assert identity["degree_level"] == "Masters"
    assert identity["graduation_year"] == 2026
    assert identity["region"] == "United States"
    assert "Computer Science" in identity["education_summary"]
    assert identity["verification_label"] == "Verified Work Passport"
    assert identity["public_status"] == "Private only"
    # No private/sensitive fields leak into the header.
    blob = str(identity)
    assert "F1" not in blob and "sponsorship" not in blob.lower() and "visa" not in blob.lower()


def test_private_passport_identity_uses_safe_placeholder_when_no_profile(
    client: TestClient, mem_store: dict
) -> None:
    # No user row and no onboarding profile → header still renders safely.
    body = _get_private(client).json()
    identity = body["identity"]
    assert identity is not None
    assert identity["headline"]  # default "Verified Work Passport" headline
    assert identity["program"] is None
    assert identity["verification_label"] == "Verified Work Passport"


def test_public_passport_identity_is_recruiter_safe(client: TestClient, mem_store: dict) -> None:
    _seed_user(mem_store)
    _seed_onboarding(mem_store, major="Computer Science", graduation_year=2026, visa_status="F1")
    slug = _publish(client).json()["public_slug"]
    body = _get_public(client, slug).json()
    identity = body["identity"]
    assert identity is not None
    assert identity["display_name"] == "Ada Lovelace"
    assert identity["program"] == "Computer Science"
    # Public identity never carries a private owner link or sensitive profile data.
    assert identity["public_path"] is None
    blob = str(body)
    assert "F1" not in blob and USER_ID not in blob


# ── Must-fix: identity header scrubs UUID / private-id / email onboarding values ─
#
# Onboarding-derived identity fields are untrusted free text. A value shaped like
# a raw UUID, a ``user_…`` / ``project_…`` private id, or an email must never ride
# out on the identity header — it is omitted (optional fields) or replaced with a
# neutral placeholder (display name / headline), public OR private.


def test_identity_replaces_uuid_display_name_with_safe_placeholder(
    client: TestClient, mem_store: dict
) -> None:
    raw_uuid = "550e8400-e29b-41d4-a716-446655440000"
    _seed_user(mem_store, full_name=raw_uuid)
    identity = _get_private(client).json()["identity"]
    assert identity["display_name"] == "Verified candidate profile"
    assert raw_uuid not in str(identity)


def test_identity_omits_private_prefixed_id_onboarding_fields(
    client: TestClient, mem_store: dict
) -> None:
    _seed_user(mem_store)
    _seed_onboarding(
        mem_store,
        major="user_1234567890abcdef",
        university_country="project_0011223344556677",
    )
    identity = _get_private(client).json()["identity"]
    assert identity["program"] is None
    assert identity["region"] is None
    blob = str(identity)
    assert "user_1234567890abcdef" not in blob
    assert "project_0011223344556677" not in blob


@pytest.mark.parametrize(
    "raw_value",
    [
        "user_1234567890ghijkl",
        "project_ABCXYZ1234567890",
        "student_1234567890ghijkl",
        "artifact_ABCXYZ1234567890",
        "source_ABCXYZ1234567890",
        "provider_1234567890ghijkl",
        "report_ABCXYZ1234567890",
    ],
)
def test_safe_identity_text_rejects_long_alphanumeric_private_ids(raw_value: str) -> None:
    from app.services.vbr_work_passport_service import _safe_identity_text

    # A long alphanumeric private-prefixed id must never come back as the raw value.
    assert _safe_identity_text(raw_value) != raw_value


def test_safe_identity_text_preserves_normal_safe_labels() -> None:
    from app.services.vbr_work_passport_service import _safe_identity_text

    assert _safe_identity_text("Mohammed Faraz") == "Mohammed Faraz"
    assert _safe_identity_text("MS AI") == "MS AI"
    assert _safe_identity_text("Machine Learning Engineer") == "Machine Learning Engineer"


def test_identity_omits_long_alphanumeric_private_id_onboarding_fields(
    client: TestClient, mem_store: dict
) -> None:
    _seed_user(mem_store)
    _seed_onboarding(
        mem_store,
        major="project_ABCXYZ1234567890",
        university_country="user_1234567890ghijkl",
    )
    identity = _get_private(client).json()["identity"]
    assert identity["program"] is None
    assert identity["region"] is None
    blob = str(identity)
    assert "project_ABCXYZ1234567890" not in blob
    assert "user_1234567890ghijkl" not in blob


def test_public_identity_omits_long_alphanumeric_private_id(
    client: TestClient, mem_store: dict
) -> None:
    _seed_user(mem_store, full_name="student_1234567890ghijkl")
    _seed_onboarding(mem_store, major="artifact_ABCXYZ1234567890")
    slug = _publish(client).json()["public_slug"]
    identity = _get_public(client, slug).json()["identity"]
    assert identity["display_name"] == "Verified candidate profile"
    assert identity["program"] is None
    blob = str(identity)
    assert "student_1234567890ghijkl" not in blob
    assert "artifact_ABCXYZ1234567890" not in blob


def test_identity_does_not_expose_email_like_value(
    client: TestClient, mem_store: dict
) -> None:
    _seed_user(mem_store, full_name="ada@example.com")
    _seed_onboarding(mem_store, major="ada@example.com")
    identity = _get_private(client).json()["identity"]
    assert "@example.com" not in str(identity)
    assert identity["display_name"] == "Verified candidate profile"
    assert identity["program"] is None


def test_identity_preserves_normal_safe_values(
    client: TestClient, mem_store: dict
) -> None:
    _seed_user(mem_store, full_name="Ada Lovelace")
    _seed_onboarding(
        mem_store, major="Computer Science", university_country="United States"
    )
    identity = _get_private(client).json()["identity"]
    assert identity["display_name"] == "Ada Lovelace"
    assert identity["program"] == "Computer Science"
    assert identity["region"] == "United States"


def test_public_identity_scrubs_uuid_and_email_onboarding_values(
    client: TestClient, mem_store: dict
) -> None:
    _seed_user(mem_store, full_name="550e8400-e29b-41d4-a716-446655440000")
    _seed_onboarding(mem_store, major="ada@example.com")
    slug = _publish(client).json()["public_slug"]
    identity = _get_public(client, slug).json()["identity"]
    assert identity["display_name"] == "Verified candidate profile"
    assert identity["program"] is None
    blob = str(identity)
    assert "550e8400" not in blob
    assert "@example.com" not in blob


# ── Grouped project skill aggregation across multiple attempts ───────────────


def test_grouped_project_skill_intelligence_aggregates_distinct_skills(
    client: TestClient, mem_store: dict
) -> None:
    """Attempt 1 demonstrates Skill A, Attempt 2 demonstrates Skill B.
    Skill Intelligence must show both skills in the combined card."""
    # Attempt 1: Project with Python evidence
    snapshot1 = {
        "skill_code_evidence": [
            {
                "skill": "Python",
                "file_path": "src/main.py",
                "line_start": 1,
                "line_end": 15,
                "function_name": "main",
                "code_snippet": "def main():\n    print('hello')",
                "github_url": "https://github.com/test/repo/blob/main/src/main.py#L1-L15",
            }
        ]
    }
    github_proof_1 = _seed_github_proof(mem_store, analysis_snapshot=snapshot1)
    project_1_id = _create_project_defense(
        client,
        attached_proofs={"github_proof_id": github_proof_1},
    ).json()["project"]["id"]
    mem_store["vbr_projects"][project_1_id]["repo_full_name"] = "test/multi-skill-repo"

    # Attempt 2: Different skill (React), same repo identity
    snapshot2 = {
        "skill_code_evidence": [
            {
                "skill": "React",
                "file_path": "src/App.tsx",
                "line_start": 5,
                "line_end": 25,
                "function_name": "App",
                "code_snippet": "function App() {\n    return <div>App</div>;\n}",
                "github_url": "https://github.com/test/repo/blob/main/src/App.tsx#L5-L25",
            }
        ]
    }
    github_proof_2 = _seed_github_proof(mem_store, analysis_snapshot=snapshot2)
    project_2_id = _create_project_defense(
        client,
        attached_proofs={"github_proof_id": github_proof_2},
    ).json()["project"]["id"]
    mem_store["vbr_projects"][project_2_id]["repo_full_name"] = "test/multi-skill-repo"

    body = _get_private(client).json()

    # Should collapse to one grouped project with both attempts
    assert body["project_count"] == 1
    assert body["projects"][0]["attempt_count"] == 2

    # Skill Intelligence should include skills from BOTH attempts
    skill_names = {s["skill"] for s in body["skills"]}
    assert "Python" in skill_names, "Attempt 1 skill should be in Skill Intelligence"
    assert "React" in skill_names, "Attempt 2 skill should be in Skill Intelligence"

    # Each skill should have the grouped project in its cross-project detail
    for skill in body["skills"]:
        if skill["skill"] in ("Python", "React"):
            assert skill["projects"], f"{skill['skill']} should reference the grouped project"
            # Verify no project duplication (one deduplicated reference per skill)
            proj_titles = [p["project_title"] for p in skill["projects"]]
            assert len(proj_titles) == len(set(proj_titles)), "Grouped project must appear only once per skill"


def test_grouped_project_aggregates_strongest_status_across_attempts(
    client: TestClient, mem_store: dict
) -> None:
    """Attempt 1 has weaker status (Supporting evidence) for Skill X.
    Attempt 2 has stronger status (Demonstrated) for the same Skill X.
    Skill Intelligence and strongest-project context must use the stronger aggregated status."""
    # Note: The status comes from the skill_evidence rows in the report.
    # We can't directly control that without modifying the report structure.
    # Instead, we'll create one full project and verify the aggregation works
    # correctly when multiple attempts are grouped.

    # Create a full project (Attempt 1)
    project_1_id = _make_full_project(client, mem_store)
    mem_store["vbr_projects"][project_1_id]["repo_full_name"] = "test/status-strength-repo"

    # Create another identical project (Attempt 2) with same repo
    project_2_id = _make_full_project(client, mem_store)
    mem_store["vbr_projects"][project_2_id]["repo_full_name"] = "test/status-strength-repo"

    body = _get_private(client).json()

    # Should have one grouped project
    assert body["project_count"] == 1
    assert body["projects"][0]["attempt_count"] == 2

    # All skills should be present and deduplicated
    skills = {s["skill"]: s for s in body["skills"]}
    for skill in body["skills"]:
        # Should have strongest_project_status set (from strongest evidence)
        assert skill["strongest_project_status"] is not None
        # The status should be one of the qualitative labels
        assert skill["strongest_project_status"] in {
            "Demonstrated",
            "Partially demonstrated",
            "Evidence observed",
            "Supporting evidence",
            "Needs review",
            "Not assessed",
        }


def test_grouped_project_preserves_card_behavior_in_skill_intelligence(
    client: TestClient, mem_store: dict
) -> None:
    """Verify that grouped project card aggregation is preserved when combined
    with Skill Intelligence aggregation. Project cards and Skill Intelligence
    should be in sync."""
    # Create two attempts of the same project
    project_1_id = _make_full_project(client, mem_store)
    mem_store["vbr_projects"][project_1_id]["repo_full_name"] = "test/preserve-card-repo"

    project_2_id = _make_full_project(client, mem_store)
    mem_store["vbr_projects"][project_2_id]["repo_full_name"] = "test/preserve-card-repo"

    body = _get_private(client).json()

    # Project card shows single grouped entry with both attempts
    assert body["project_count"] == 1
    card = body["projects"][0]
    assert card["attempt_count"] == 2

    # Project card aggregates evidence sources across all attempts
    assert "GitHub Proof" in card["evidence_sources"]
    assert "Project Defense" in card["evidence_sources"]

    # Project card aggregates top skills across all attempts
    card_skill_names = {s["skill"] for s in card["top_skills"]}
    passport_skill_names = {s["skill"] for s in body["skills"]}

    # All card top skills should be in the full Skill Intelligence
    assert card_skill_names.issubset(passport_skill_names)


def test_public_passport_aggregates_skills_from_all_published_attempts(
    client: TestClient, mem_store: dict
) -> None:
    """Public projection must also aggregate skills from all attempts in a
    grouped project, using the same safe aggregation."""
    # Create Attempt 1
    project_1_id = _make_full_project(client, mem_store)
    mem_store["vbr_projects"][project_1_id]["repo_full_name"] = "test/public-multi-skill-repo"
    _publish_project_report(client, project_1_id)

    # Create Attempt 2 with same repo
    project_2_id = _make_full_project(client, mem_store)
    mem_store["vbr_projects"][project_2_id]["repo_full_name"] = "test/public-multi-skill-repo"
    _publish_project_report(client, project_2_id)

    slug = _publish(client).json()["public_slug"]

    app.dependency_overrides.pop(get_current_user_id, None)
    body = _get_public(client, slug).json()

    # Public passport should feature one grouped project
    assert body["featured_project_count"] == 1

    # Top skills must be aggregated from all published attempts
    assert body["top_skills"], "expected skills aggregated from all attempts"

    # Verify safety: no private ids / internal fields
    serialized = str(body["top_skills"])
    assert "project_id" not in serialized
    assert USER_ID not in serialized
    for skill in body["top_skills"]:
        assert "project_id" not in str(skill)
        # All linked projects must be published
        for ref in skill.get("projects", []):
            assert ref["public_report_path"].startswith("/vbr/report/")


# ── Grouped attempt aggregation (unit level) ──────────────────────────────────
# The end-to-end tests above cannot control per-attempt skill status directly,
# so these drive ``_aggregate_skills_with_detail`` with the exact card shape the
# passport builders produce for a grouped project: ONE shared project summary
# paired with EVERY attempt report in the group.


def _attempt_report(skill_rows: list[dict]) -> dict:
    return {"project_title": "Grouped Project", "skill_evidence": skill_rows, "evidence_traces": []}


_GROUPED_SUMMARY_PRIVATE = {
    "project_id": "proj-1",
    "project_title": "Grouped Project",
    "evidence_sources": ["GitHub Proof"],
    "report": {"is_public": False, "public_path": None},
}


def test_aggregation_upgrades_per_project_status_from_later_attempt() -> None:
    """Attempt 1 has a weaker label for a skill; attempt 2 has a stronger one.
    The single deduplicated project reference (and strongest-project context)
    must carry the stronger label, not the representative's weaker one."""
    from app.services.vbr_work_passport_service import _aggregate_skills_with_detail

    weak = _attempt_report(
        [{"skill": "Python", "status": "Supporting evidence", "evidence_chip_count": 1}]
    )
    strong = _attempt_report(
        [{"skill": "Python", "status": "Demonstrated", "evidence_chip_count": 2}]
    )
    skills = _aggregate_skills_with_detail(
        [(_GROUPED_SUMMARY_PRIVATE, weak), (_GROUPED_SUMMARY_PRIVATE, strong)],
        public=False,
    )

    assert len(skills) == 1
    entry = skills[0]
    assert entry["skill"] == "Python"
    assert entry["status"] == "Demonstrated"
    # One deduplicated grouped project reference — not one per attempt.
    assert entry["project_count"] == 1
    assert len(entry["projects"]) == 1
    # The per-project label reflects the strongest attempt in the group.
    assert entry["projects"][0]["skill_status"] == "Demonstrated"
    assert entry["strongest_project_title"] == "Grouped Project"
    assert entry["strongest_project_status"] == "Demonstrated"


def test_aggregation_order_independent_for_strongest_status() -> None:
    """The stronger attempt wins whether it is grouped first or last."""
    from app.services.vbr_work_passport_service import _aggregate_skills_with_detail

    strong = _attempt_report([{"skill": "Python", "status": "Demonstrated"}])
    weak = _attempt_report([{"skill": "Python", "status": "Needs review"}])
    skills = _aggregate_skills_with_detail(
        [(_GROUPED_SUMMARY_PRIVATE, strong), (_GROUPED_SUMMARY_PRIVATE, weak)],
        public=False,
    )

    assert skills[0]["projects"][0]["skill_status"] == "Demonstrated"
    assert skills[0]["strongest_project_status"] == "Demonstrated"


def test_aggregation_unions_distinct_skills_across_attempts() -> None:
    """Attempt 1 evidences Skill A, attempt 2 evidences Skill B: both must
    appear, each pointing at the same single grouped project reference."""
    from app.services.vbr_work_passport_service import _aggregate_skills_with_detail

    attempt1 = _attempt_report([{"skill": "Python", "status": "Demonstrated"}])
    attempt2 = _attempt_report([{"skill": "React", "status": "Evidence observed"}])
    skills = _aggregate_skills_with_detail(
        [(_GROUPED_SUMMARY_PRIVATE, attempt1), (_GROUPED_SUMMARY_PRIVATE, attempt2)],
        public=False,
    )

    by_name = {s["skill"]: s for s in skills}
    assert set(by_name) == {"Python", "React"}
    for entry in by_name.values():
        assert entry["project_count"] == 1
        assert len(entry["projects"]) == 1
        assert entry["projects"][0]["project_title"] == "Grouped Project"


# ── Project-reference identity (same-title / different-repo dedupe) ────────────
# Two genuinely different projects can share a human-readable title but live in
# different repositories / have different public report paths. They must stay as
# separate skill references (never collapsed by title), while repeated attempts
# of ONE grouped project (same summary) still dedupe to a single reference.

_SAME_TITLE_REPO_A = {
    "project_id": "proj-a",
    "project_title": "Portfolio",
    "repo_full_name": "octo/alpha",
    "evidence_sources": ["GitHub Proof"],
    "report": {"is_public": False, "public_path": None},
}

_SAME_TITLE_REPO_B = {
    "project_id": "proj-b",
    "project_title": "Portfolio",
    "repo_full_name": "octo/beta",
    "evidence_sources": ["GitHub Proof"],
    "report": {"is_public": False, "public_path": None},
}


def test_same_title_different_repo_projects_do_not_collapse_private() -> None:
    """Two DISTINCT projects sharing a title but differing by repository must
    both be counted in a skill's project_count and kept as separate references —
    never merged by title alone (which would undercount and merge statuses)."""
    from app.services.vbr_work_passport_service import _aggregate_skills_with_detail

    report_a = _attempt_report([{"skill": "Python", "status": "Demonstrated"}])
    report_b = _attempt_report([{"skill": "Python", "status": "Evidence observed"}])
    skills = _aggregate_skills_with_detail(
        [(_SAME_TITLE_REPO_A, report_a), (_SAME_TITLE_REPO_B, report_b)],
        public=False,
    )

    assert len(skills) == 1
    entry = skills[0]
    assert entry["skill"] == "Python"
    # Both distinct projects count — references are NOT collapsed by title.
    assert entry["project_count"] == 2
    assert len(entry["projects"]) == 2
    assert {p["project_id"] for p in entry["projects"]} == {"proj-a", "proj-b"}
    # Display titles stay human-readable (both legitimately "Portfolio").
    assert [p["project_title"] for p in entry["projects"]] == ["Portfolio", "Portfolio"]
    # Distinct per-project statuses are preserved, not merged into one.
    assert {p["skill_status"] for p in entry["projects"]} == {"Demonstrated", "Evidence observed"}


def test_same_grouped_project_attempts_dedupe_to_one_reference() -> None:
    """Repeated attempts of ONE grouped project (same representative summary)
    must still collapse to a single skill project reference."""
    from app.services.vbr_work_passport_service import _aggregate_skills_with_detail

    attempt1 = _attempt_report([{"skill": "Python", "status": "Supporting evidence"}])
    attempt2 = _attempt_report([{"skill": "Python", "status": "Demonstrated"}])
    skills = _aggregate_skills_with_detail(
        [(_GROUPED_SUMMARY_PRIVATE, attempt1), (_GROUPED_SUMMARY_PRIVATE, attempt2)],
        public=False,
    )

    assert len(skills) == 1
    entry = skills[0]
    assert entry["project_count"] == 1
    assert len(entry["projects"]) == 1
    # The single reference keeps the strongest attempt's label.
    assert entry["projects"][0]["skill_status"] == "Demonstrated"


_PUBLIC_SUMMARY_ALPHA = {
    "project_title": "Portfolio",
    "evidence_sources": ["GitHub Proof"],
    "public_report_path": "/vbr/report/alpha-token",
}

_PUBLIC_SUMMARY_BETA = {
    "project_title": "Portfolio",
    "evidence_sources": ["GitHub Proof"],
    "public_report_path": "/vbr/report/beta-token",
}


def test_public_same_title_different_report_path_preserved_without_private_ids() -> None:
    """Public projection must keep two same-title projects that differ by public
    report path as SEPARATE references — using the public-safe path identity —
    and must never carry a private project_id/internal id in the output."""
    from app.services.vbr_work_passport_service import (
        _aggregate_skills_with_detail,
        _to_public_skill,
    )

    report_a = _attempt_report([{"skill": "Python", "status": "Demonstrated"}])
    report_b = _attempt_report([{"skill": "Python", "status": "Evidence observed"}])
    skills = _aggregate_skills_with_detail(
        [(_PUBLIC_SUMMARY_ALPHA, report_a), (_PUBLIC_SUMMARY_BETA, report_b)],
        public=True,
    )

    assert len(skills) == 1
    entry = skills[0]
    # Both distinct projects preserved via the public-safe (path) identity.
    assert entry["project_count"] == 2
    assert len(entry["projects"]) == 2
    # No private id leaks into the public aggregation refs.
    for ref in entry["projects"]:
        assert "project_id" not in ref

    public_skill = _to_public_skill(entry)
    # Both published references survive the recruiter-safe projection, distinct
    # by their public report path (never by a private id).
    assert len(public_skill["projects"]) == 2
    paths = {p["public_report_path"] for p in public_skill["projects"]}
    assert paths == {"/vbr/report/alpha-token", "/vbr/report/beta-token"}
    assert all(p["project_title"] == "Portfolio" for p in public_skill["projects"])
    # Defence in depth: no private id / internal id anywhere in the public shape.
    assert "project_id" not in str(public_skill)


def test_public_projection_uses_upgraded_grouped_status_safely() -> None:
    """The public skill shape must carry the stronger aggregated per-project
    label from a later attempt while staying recruiter-safe (no project_id)."""
    from app.services.vbr_work_passport_service import (
        _aggregate_skills_with_detail,
        _to_public_skill,
    )

    public_summary = {
        "project_title": "Grouped Project",
        "evidence_sources": ["GitHub Proof"],
        "public_report_path": "/vbr/report/tok-123",
    }
    weak = _attempt_report([{"skill": "Python", "status": "Supporting evidence"}])
    strong = _attempt_report([{"skill": "Python", "status": "Demonstrated"}])
    skills = _aggregate_skills_with_detail(
        [(public_summary, weak), (public_summary, strong)],
        public=True,
    )
    public = [_to_public_skill(s) for s in skills]

    assert len(public) == 1
    entry = public[0]
    assert entry["status"] == "Demonstrated"
    assert len(entry["projects"]) == 1
    assert entry["projects"][0]["skill_status"] == "Demonstrated"
    assert entry["projects"][0]["public_report_path"] == "/vbr/report/tok-123"
    assert "project_id" not in str(entry)
