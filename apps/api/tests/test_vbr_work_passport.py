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


# A substantive, project-specific defense transcript that genuinely explains
# Python and React under the tightened transcript-only fallback: each skill is
# named in a sentence carrying multiple distinct *non-generic* technical-depth
# signals (authentication/middleware/schema/validation, state management/caching/
# optimization), not merely generic "API endpoint database" vocabulary.
_SUBSTANTIVE_DEFENSE_TRANSCRIPT = (
    "In Python I implemented the authentication middleware and the request schema "
    "validation, and I refactored the asynchronous job queue to cut latency. "
    "In React I built the dashboard state management with a caching layer and "
    "optimized the data flow between the components. One limitation is that it "
    "does not yet support real-time updates, which I would improve next."
)


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
    _submit_defense(client, session_id, combined_text=_SUBSTANTIVE_DEFENSE_TRANSCRIPT)
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


_KNOWN_PROOF_TYPES = {
    "GitHub Proof",
    "Website Proof",
    "Document Proof",
    "Project Defense",
    "Video Evidence",
}


def _norm_skill(name: str) -> str:
    return str(name or "").strip().lower()


def test_skill_project_ref_proof_types_are_skill_and_project_specific(
    client: TestClient, mem_store: dict
) -> None:
    """Each skill→project ref must carry the proof types that support THAT skill
    in THAT project — the closed, fail-closed breakdown from the report row's
    ``supporting_sources`` — never the project-wide source union blindly."""
    project_id = _make_full_project(client, mem_store)
    body = _get_private(client).json()

    # The project report's per-skill supporting_sources are the source of truth.
    report = client.get(f"/api/v1/student/vbr/projects/{project_id}/report").json()
    report_sources_by_skill = {
        _norm_skill(row["skill"]): set(row.get("supporting_sources") or [])
        for row in report["skill_evidence"]
    }

    saw_ref = False
    saw_strict_subset = False
    for skill in body["skills"]:
        for ref in skill["projects"]:
            saw_ref = True
            assert "supporting_proof_types" in ref
            spt = set(ref["supporting_proof_types"])
            # 1. Closed vocabulary only — never an invented proof type.
            assert spt <= _KNOWN_PROOF_TYPES
            # 2. A proof type is never claimed unless the project actually has it.
            assert spt <= set(ref["evidence_sources"])
            # 3. It equals the report's SKILL-SPECIFIC breakdown for this skill,
            #    proving it is not the project-wide union.
            expected = report_sources_by_skill.get(_norm_skill(skill["skill"]), set())
            assert spt == expected
            # 4. Vault-only / unattached proof never appears as project support:
            #    every listed type is one the attached report row recorded.
            if spt < set(ref["evidence_sources"]):
                saw_strict_subset = True

    assert saw_ref, "expected at least one skill→project ref to check"
    # At least one skill is NOT supported by every proof type the project carries,
    # proving the breakdown is skill-specific rather than a blind project dump.
    assert saw_strict_subset


def test_skill_project_ref_website_proof_only_when_website_supports_skill(
    client: TestClient, mem_store: dict
) -> None:
    """Website Proof appears on a skill→project ref only when the website
    evidence actually supported THAT skill — never dumped onto every skill just
    because the project has a Website Proof attached."""
    project_id = _make_full_project(client, mem_store)
    body = _get_private(client).json()
    report = client.get(f"/api/v1/student/vbr/projects/{project_id}/report").json()

    website_skills = {
        _norm_skill(row["skill"])
        for row in report["skill_evidence"]
        if "Website Proof" in (row.get("supporting_sources") or [])
    }
    for skill in body["skills"]:
        for ref in skill["projects"]:
            has_website = "Website Proof" in ref["supporting_proof_types"]
            assert has_website == (_norm_skill(skill["skill"]) in website_skills)


def test_passport_supporting_proof_types_include_derived_website_proof(
    client: TestClient, mem_store: dict
) -> None:
    """A Website Proof with EMPTY ``supported_skills`` but a safe prediction-result
    narrative maps (derived) to the claimed ML skill, so the passport skill→project
    ref lists Website Proof in ``supporting_proof_types`` — the Website Proof filter
    now has a row to show."""
    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=[],
        workflow_summary="Entered input values and the model displayed a prediction result.",
    )
    _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    )
    body = _get_private(client).json()

    ml = next(s for s in body["skills"] if _norm_skill(s["skill"]) == "machine learning")
    assert ml["projects"], "expected a project ref for the ML skill"
    assert any(
        "Website Proof" in (ref.get("supporting_proof_types") or [])
        for ref in ml["projects"]
    )


def test_passport_mapped_website_proof_carries_safe_skill_behaviour_summary(
    client: TestClient, mem_store: dict
) -> None:
    """When a Website Proof maps to a skill, its skill→project ref carries a safe,
    closed-vocabulary ``website_evidence_summary`` describing the observed runtime
    behaviour for THAT skill — not the generic placeholder, and never raw
    DOM/OCR/workflow text."""
    raw_workflow = "Entered input values and the model displayed a prediction result."
    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=[],
        workflow_summary=raw_workflow,
    )
    _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    )
    body = _get_private(client).json()

    ml = next(s for s in body["skills"] if _norm_skill(s["skill"]) == "machine learning")
    website_refs = [
        ref
        for ref in ml["projects"]
        if "Website Proof" in (ref.get("supporting_proof_types") or [])
    ]
    assert website_refs, "expected a Website-Proof-backed ML project ref"
    for ref in website_refs:
        summary = ref.get("website_evidence_summary")
        assert isinstance(summary, str) and summary.strip()
        # A real behaviour sentence, not the honest limited-detail fallback.
        assert "detailed website evidence is limited" not in summary
        # Recruiter-safe: never echoes the raw pipeline workflow text.
        assert raw_workflow not in summary
        # The strongest-project link mirrors the same safe summary.
    strongest = ml.get("strongest_project") or {}
    if "Website Proof" in (strongest.get("supporting_proof_types") or []):
        assert (strongest.get("website_evidence_summary") or "").strip()


def test_passport_website_evidence_summary_absent_when_website_maps_no_skill(
    client: TestClient, mem_store: dict
) -> None:
    """A generic Website Proof maps no skill, so no skill→project ref carries a
    ``website_evidence_summary`` (the field only accompanies real Website Proof
    support)."""
    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=[],
        workflow_summary="A landing page describing the product and its features was shown.",
    )
    _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    )
    body = _get_private(client).json()

    for skill in body["skills"]:
        for ref in skill["projects"]:
            if "Website Proof" not in (ref.get("supporting_proof_types") or []):
                assert not ref.get("website_evidence_summary")


def test_passport_generic_website_adds_no_website_proof_to_skill(
    client: TestClient, mem_store: dict
) -> None:
    """A generic Website Proof (landing page, empty ``supported_skills``) maps to no
    skill, so no passport skill→project ref lists Website Proof — the filter stays
    truthfully empty rather than showing a spurious row."""
    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=[],
        workflow_summary="A landing page describing the product and its features was shown.",
    )
    _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    )
    body = _get_private(client).json()

    for skill in body["skills"]:
        for ref in skill["projects"]:
            assert "Website Proof" not in (ref.get("supporting_proof_types") or [])


# ── Collapsed-attempt navigation consistency (Website Proof leak fix) ─────────
#
# Repeated attempts of the SAME project (same repo) collapse into ONE passport
# card that links to exactly ONE report — the representative's. Evidence shown on
# the card / skill refs must therefore come from the representative report ONLY,
# never unioned across the other collapsed attempts. Otherwise a Website Proof
# attached to a *different* attempt rides onto the card while the report it links
# to shows "Website proof not attached" — the observed Teachable-Machine leak.


def _bump_created_at(mem_store: dict, project_id: str, iso: str) -> None:
    row = mem_store.setdefault("vbr_projects", {}).get(project_id)
    assert row is not None, f"project {project_id} not in store"
    row["created_at"] = iso
    row["updated_at"] = iso


def test_collapsed_attempt_website_proof_does_not_leak_onto_representative(
    client: TestClient, mem_store: dict
) -> None:
    """Scenarios C/E/F/G: two collapsed attempts of the same repo — the OLDER one
    carries a Website Proof mapping ML; the NEWER (representative) one has NO
    Website Proof. The single card links to the representative report (no website),
    so neither the card's evidence badges nor any ML skill→project ref may claim
    Website Proof — it would contradict the report the card opens."""
    # Attempt A (older): same repo, WITH a Website Proof that maps ML.
    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=[],
        workflow_summary="Entered input values and the model displayed a prediction result.",
    )
    created_a = _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    ).json()
    proj_a = created_a["project"]["id"]
    # Attempt B (newer → representative): same repo, only Document/Defense proof.
    doc_id = _seed_document_evidence(mem_store)
    created_b = _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"document_evidence_ids": [doc_id]},
    ).json()
    proj_b = created_b["project"]["id"]

    # Force B to be the representative (newest wins, no published token on either).
    _bump_created_at(mem_store, proj_a, "2020-01-01T00:00:00+00:00")
    _bump_created_at(mem_store, proj_b, "2020-06-01T00:00:00+00:00")

    body = _get_private(client).json()
    # Same repo → collapsed into ONE card.
    assert body["project_count"] == 1
    card = body["projects"][0]
    rep_id = card["project_id"]
    assert rep_id == proj_b  # newest attempt is the representative the card links to

    # The report the card links to is the source of truth for what is attached.
    report = client.get(f"/api/v1/student/vbr/projects/{rep_id}/report").json()
    website_attached = (
        int((report.get("evidence_package") or {}).get("website_proofs_count") or 0) > 0
    )
    assert website_attached is False  # representative attempt has no Website Proof

    # (F) The card must not advertise Website Proof its linked report denies.
    assert "Website Proof" not in card["evidence_sources"]
    # (C/G) No ML skill→project ref may claim Website Proof for this collapsed card.
    for skill in body["skills"]:
        for ref in skill["projects"]:
            if str(ref.get("project_id")) == rep_id:
                assert "Website Proof" not in (ref.get("supporting_proof_types") or [])
            # (F) Global invariant: a ref claiming Website Proof must resolve to a
            # project whose own report has Website Proof attached.
            if "Website Proof" in (ref.get("supporting_proof_types") or []):
                ref_report = client.get(
                    f"/api/v1/student/vbr/projects/{ref['project_id']}/report"
                ).json()
                assert int(
                    (ref_report.get("evidence_package") or {}).get("website_proofs_count") or 0
                ) > 0


def test_collapsed_attempt_website_proof_kept_when_representative_has_it(
    client: TestClient, mem_store: dict
) -> None:
    """Scenario E (positive): when the REPRESENTATIVE attempt is the one carrying
    the mapping Website Proof, the ML ref legitimately keeps its Website Proof chip
    and its exact project_id — collapsing never drops a truly-attached proof."""
    # Attempt A (older): no website. Attempt B (newer → representative): website→ML.
    doc_id = _seed_document_evidence(mem_store)
    created_a = _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"document_evidence_ids": [doc_id]},
    ).json()
    proj_a = created_a["project"]["id"]
    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=[],
        workflow_summary="Entered input values and the model displayed a prediction result.",
    )
    created_b = _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    ).json()
    proj_b = created_b["project"]["id"]

    _bump_created_at(mem_store, proj_a, "2020-01-01T00:00:00+00:00")
    _bump_created_at(mem_store, proj_b, "2020-06-01T00:00:00+00:00")

    body = _get_private(client).json()
    assert body["project_count"] == 1
    card = body["projects"][0]
    assert card["project_id"] == proj_b
    assert "Website Proof" in card["evidence_sources"]

    ml = next(s for s in body["skills"] if _norm_skill(s["skill"]) == "machine learning")
    website_refs = [
        ref for ref in ml["projects"] if "Website Proof" in (ref.get("supporting_proof_types") or [])
    ]
    assert website_refs, "representative-attached Website Proof must survive collapse"
    # (E) The ref preserves the exact representative project_id it routes to.
    for ref in website_refs:
        assert str(ref.get("project_id")) == proj_b


def test_website_proof_does_not_cross_between_distinct_projects_same_skill(
    client: TestClient, mem_store: dict
) -> None:
    """Scenario A: two DISTINCT projects (different repos) both claim ML, but only
    Project A has a Website Proof mapping ML. The ML skill→project ref for Project
    B must NOT list Website Proof — website evidence never crosses project
    boundaries just because both share the skill."""
    # Project A (repo alpha): website→ML.
    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=[],
        workflow_summary="Entered input values and the model displayed a prediction result.",
    )
    created_a = _create_project_defense(
        client,
        title="Alpha ML Demo",
        repo_url="https://github.com/octocat/alpha-repo",
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    ).json()
    proj_a = created_a["project"]["id"]
    # Project B (repo beta): only Document Proof, no website.
    doc_id = _seed_document_evidence(mem_store)
    created_b = _create_project_defense(
        client,
        title="Beta ML Demo",
        repo_url="https://github.com/octocat/beta-repo",
        claimed_skills=["Machine Learning"],
        attached_proofs={"document_evidence_ids": [doc_id]},
    ).json()
    proj_b = created_b["project"]["id"]

    body = _get_private(client).json()
    assert body["project_count"] == 2  # distinct repos → not collapsed

    ml = next(s for s in body["skills"] if _norm_skill(s["skill"]) == "machine learning")
    refs = {str(r.get("project_id")): r for r in ml["projects"]}
    assert "Website Proof" in (refs[proj_a].get("supporting_proof_types") or [])
    assert "Website Proof" not in (refs[proj_b].get("supporting_proof_types") or [])
    # And Project B's card must not advertise Website Proof at the project level.
    card_b = next(p for p in body["projects"] if p["project_id"] == proj_b)
    assert "Website Proof" not in card_b["evidence_sources"]


def test_standalone_vault_website_proof_never_attaches_to_a_project_card(
    client: TestClient, mem_store: dict
) -> None:
    """Scenario B: a standalone Website Proof living in the wider vault (attached to
    NO project) must never make a project card — or a skill→project ref — show
    Website Proof. The card's evidence is the attached report only."""
    # One project with Document Proof only (no website attached).
    doc_id = _seed_document_evidence(mem_store)
    created = _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"document_evidence_ids": [doc_id]},
    ).json()
    project_id = created["project"]["id"]
    # A standalone Website Proof exists in the vault, attached to nothing.
    _seed_workflow_analysis(
        mem_store,
        supported_skills=["Machine Learning"],
        workflow_summary="Entered input values and the model displayed a prediction result.",
    )

    body = _get_private(client).json()
    card = next(p for p in body["projects"] if p["project_id"] == project_id)
    # The standalone website proof is counted as unattached vault evidence …
    assert body["vault_unattached_count"] >= 1
    # … but never rides onto the project card or a skill→project ref.
    assert "Website Proof" not in card["evidence_sources"]
    for skill in body["skills"]:
        for ref in skill["projects"]:
            assert "Website Proof" not in (ref.get("supporting_proof_types") or [])


# ── Project-level-only Website Proof context (Diagnosis-C explainer) ──────────
#
# A Website Proof can be attached to a project yet map to NO skill because the
# observed behaviour was too generic (navigation/layout). It must stay
# project-level: never a skill→project Website Proof chip, but the passport DOES
# expose a safe explanation so the Skills Evidence Map can say WHY it is absent
# from the skill map — never a faked mapping, never a raw field.


def _website_context(body: dict) -> list[dict]:
    return body.get("website_proof_project_context") or []


def test_passport_navigation_layout_website_stays_project_level_with_context(
    client: TestClient, mem_store: dict
) -> None:
    """A navigation/layout Website Proof (empty ``supported_skills``) maps no skill,
    yet the passport surfaces a safe project-level explanation: focus, reason,
    action, ``mapped_to_skills == False`` and an owner-only report route."""
    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=[],
        workflow_summary="Navigated between the app's pages using the sidebar menu.",
    )
    _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    )
    body = _get_private(client).json()

    # Stays project-level: no skill→project ref advertises Website Proof.
    for skill in body["skills"]:
        for ref in skill["projects"]:
            assert "Website Proof" not in (ref.get("supporting_proof_types") or [])

    # But the honest explanation is available.
    ctx = _website_context(body)
    assert len(ctx) == 1
    entry = ctx[0]
    assert entry["focus_key"] == "navigation_layout"
    assert entry["mapped_to_skills"] is False
    assert entry["reason"] == "Navigation/layout evidence only"
    assert entry["action_guidance"]
    assert entry["explanation"]
    assert entry["report_path"].endswith("/report")


def test_passport_website_context_ignores_weakly_supported_skills(
    client: TestClient, mem_store: dict
) -> None:
    """``weakly_supported_skills`` never become a supporting proof type: with empty
    ``supported_skills`` and a navigation page, the claimed skill stays unmapped and
    the proof only surfaces as project-level context — the weak skills are never
    promoted to skill evidence."""
    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=["Machine Learning"],
        workflow_summary="Navigated between the app's pages using the sidebar menu.",
    )
    _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    )
    body = _get_private(client).json()

    for skill in body["skills"]:
        for ref in skill["projects"]:
            assert "Website Proof" not in (ref.get("supporting_proof_types") or [])
    assert _website_context(body), "expected project-level Website Proof context"


def test_passport_mapped_website_proof_absent_from_project_context(
    client: TestClient, mem_store: dict
) -> None:
    """A Website Proof that DID map a skill (derived from a prediction result) is
    surfaced as skill evidence, NOT duplicated into the project-level context."""
    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=[],
        workflow_summary="Entered input values and the model displayed a prediction result.",
    )
    _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    )
    body = _get_private(client).json()

    assert _website_context(body) == []
    ml = next(s for s in body["skills"] if _norm_skill(s["skill"]) == "machine learning")
    assert any("Website Proof" in (ref.get("supporting_proof_types") or []) for ref in ml["projects"])


def test_passport_website_project_context_exposes_no_raw_fields(
    client: TestClient, mem_store: dict
) -> None:
    """The project-level Website Proof context never leaks raw DOM/OCR/visual text,
    screenshots, storage paths, signed URLs, ``proof_session_id`` or scores."""
    import json

    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=[],
        workflow_summary="Navigated between the app's pages using the sidebar menu.",
        dom_summary="Raw DOM should never appear here",
        screenshot_url="https://bucket.example/secret.png",
        storage_path="/private/bucket/raw.html",
        evidence_strength_score=91,
    )
    _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    )
    body = _get_private(client).json()

    ctx = _website_context(body)
    assert ctx, "expected project-level Website Proof context"
    blob = json.dumps(ctx)
    for unsafe in [
        "secret.png",
        "/private/bucket",
        "storage_path",
        "screenshot_url",
        "signed_url",
        str(session_id),
    ]:
        assert unsafe not in blob
    # Only the closed, safe key set is exposed — no score/confidence/raw fields.
    allowed_keys = {
        "project_id",
        "project_title",
        "focus_key",
        "focus_label",
        "explanation",
        "reason",
        "action_guidance",
        "mapped_to_skills",
        "report_path",
    }
    for entry in ctx:
        assert set(entry) <= allowed_keys
        assert "91" not in str(entry.get("explanation", ""))


def test_skill_vault_only_sources_are_separate_from_project_evidence(
    client: TestClient, mem_store: dict
) -> None:
    """A skill's ``vault_only_sources`` lists proof types that exist for it in
    the vault but are NOT attached to any project — kept strictly separate from
    the project-attached ``supporting_proof_types`` so vault-only proof is never
    counted as project evidence."""
    _make_full_project(client, mem_store)
    # An EXTRA Document Proof for Python that is NEVER attached to the project —
    # it stays vault-only (standalone) evidence.
    _seed_document_evidence(
        mem_store,
        evidence_objects=[
            {"skill_name": "Python", "confidence": "high", "snippet": "standalone notes", "page_number": 5},
        ],
    )
    body = _get_private(client).json()
    by_skill = {_norm_skill(s["skill"]): s for s in body["skills"]}

    python = by_skill.get("python")
    assert python is not None, "expected a Python skill on the passport"
    assert "vault_only_sources" in python
    # The unattached Document Proof for Python shows up as vault-only evidence …
    assert "Document Proof" in python["vault_only_sources"]
    # … using the closed proof-type vocabulary only (never a Skill Graph pipeline).
    assert set(python["vault_only_sources"]) <= _KNOWN_PROOF_TYPES
    # Every skill carries the field, and no vault-only chip is ever an invented type.
    for skill in body["skills"]:
        assert set(skill.get("vault_only_sources") or []) <= _KNOWN_PROOF_TYPES


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
        assert set(row.keys()) == {
            "skill",
            "status",
            "skill_slug",
            "skill_report_path",
            "supporting_proof_types",
        }
        assert row["status"] in _QUALITATIVE_LABELS
        assert set(row["supporting_proof_types"]) <= _KNOWN_PROOF_TYPES


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


# ── Phase 2: Project ↔ Skill cross-linking ────────────────────────────────────


def test_private_project_top_skills_link_to_skill_reports(
    client: TestClient, mem_store: dict
) -> None:
    _make_full_project(client, mem_store)
    proj = _get_private(client).json()["projects"][0]

    assert proj["top_skills"]
    for row in proj["top_skills"]:
        # Project → Skill link: stable slug + the owner-only Skill Report route.
        assert row["skill_slug"]
        assert row["skill_report_path"] == f"/student/vbr/passport/skills/{row['skill_slug']}"


def test_private_project_cards_carry_relationship_note(
    client: TestClient, mem_store: dict
) -> None:
    _make_full_project(client, mem_store)
    proj = _get_private(client).json()["projects"][0]

    note = proj["evidence_relationship_note"]
    # Project Defense is explanation evidence, so a defense-explained skill now
    # reads "partially demonstrates" — the note stays honest, never inflated.
    assert note and note.startswith("This project partially demonstrates ")
    # Composed from safe labels only — never a score-style fragment.
    assert "%" not in note and "score" not in note.lower()


def test_relationship_note_demonstrated_status_uses_demonstrates() -> None:
    """A purely "Demonstrated" skill reads as something the project
    "demonstrates" — the strongest, full-strength claim tier."""
    from app.services.vbr_work_passport_service import _project_relationship_note

    note = _project_relationship_note(
        [
            {"skill": "React", "status": "Demonstrated"},
            {"skill": "API Development", "status": "Demonstrated"},
        ],
        ["GitHub Proof"],
    )
    assert note is not None
    assert note.startswith("This project demonstrates React and API Development")
    # "demonstrates" here is the full-strength verb, not "partially demonstrates".
    assert "partially demonstrates" not in note
    assert "%" not in note and "score" not in note.lower()


def test_relationship_note_partial_status_is_not_promoted_to_demonstrates() -> None:
    """"Partially demonstrated" must keep its own weaker wording — it is never
    promoted into the full "This project demonstrates …" claim."""
    from app.services.vbr_work_passport_service import _project_relationship_note

    note = _project_relationship_note(
        [
            {"skill": "React", "status": "Partially demonstrated"},
            {"skill": "API Development", "status": "Partially demonstrated"},
        ],
        ["GitHub Proof"],
    )
    assert note is not None
    assert note.startswith(
        "This project partially demonstrates React and API Development"
    )
    # Must NOT be dressed up as a full demonstrated claim.
    assert not note.startswith("This project demonstrates ")
    assert "%" not in note and "score" not in note.lower()


def test_relationship_note_evidence_observed_uses_its_own_wording() -> None:
    """"Evidence observed" must read as "Evidence was observed for …", never as
    something the project "demonstrates"."""
    from app.services.vbr_work_passport_service import _project_relationship_note

    note = _project_relationship_note(
        [
            {"skill": "React", "status": "Evidence observed"},
            {"skill": "API Development", "status": "Evidence observed"},
        ],
        ["GitHub Proof"],
    )
    assert note is not None
    assert note.startswith(
        "Evidence was observed for React and API Development in this project"
    )
    # Never promoted into a "demonstrates" claim.
    assert "demonstrates" not in note.lower()
    assert "%" not in note and "score" not in note.lower()


def test_relationship_note_mixed_statuses_preserve_each_wording_tier() -> None:
    """When several tiers co-exist, each keeps its own distinct wording — the
    full "demonstrates" claim only covers "Demonstrated" skills; "Partially
    demonstrated" and "Evidence observed" keep their own weaker phrasing; weak
    statuses stay under review."""
    from app.services.vbr_work_passport_service import _project_relationship_note

    note = _project_relationship_note(
        [
            {"skill": "React", "status": "Demonstrated"},
            {"skill": "API Development", "status": "Partially demonstrated"},
            {"skill": "Machine Learning", "status": "Evidence observed"},
        ],
        ["GitHub Proof"],
    )
    assert note is not None
    # Each tier keeps its own verb clause — none collapsed into another.
    assert "demonstrates React" in note
    assert "partially demonstrates API Development" in note
    assert "has observed evidence for Machine Learning" in note
    # The full "demonstrates" claim covers ONLY the Demonstrated skill.
    demonstrates_clause = note.split("demonstrates ", 1)[1]
    assert demonstrates_clause.startswith("React")
    assert "API Development" not in demonstrates_clause.split(",")[0]
    assert "Machine Learning" not in demonstrates_clause.split(",")[0]
    assert "%" not in note and "score" not in note.lower()


def test_relationship_note_weak_statuses_stay_under_review_alongside_positive() -> None:
    """Weak statuses (Needs review / Not assessed / Insufficient evidence) never
    appear as demonstrated even beside positive tiers — they get a separate,
    under-review sentence."""
    from app.services.vbr_work_passport_service import _project_relationship_note

    top_skills = [
        {"skill": "React", "status": "Demonstrated"},
        {"skill": "API Development", "status": "Evidence observed"},
        {"skill": "Kubernetes", "status": "Needs review"},
    ]
    note = _project_relationship_note(top_skills, ["GitHub Proof"])
    assert note is not None
    assert note.startswith("This project demonstrates React")
    assert "has observed evidence for API Development" in note
    # The weak skill is described under review, never as demonstrated.
    assert "Additional evidence is under review for Kubernetes." in note
    positive_part = note.split(" Additional evidence is under review for")[0]
    assert "Kubernetes" not in positive_part
    assert "%" not in note and "score" not in note.lower()


def test_relationship_note_supporting_evidence_gets_its_own_tier() -> None:
    """"Supporting evidence" skills are never called demonstrated — they read
    as "has supporting evidence for", both alongside supported skills and when
    they lead the note."""
    from app.services.vbr_work_passport_service import _project_relationship_note

    # Mixed: supported + supporting + weak, each in its own clause.
    note = _project_relationship_note(
        [
            {"skill": "React", "status": "Demonstrated"},
            {"skill": "Docker", "status": "Supporting evidence"},
            {"skill": "Kubernetes", "status": "Not assessed"},
        ],
        ["GitHub Proof"],
    )
    assert note is not None
    assert note.startswith("This project demonstrates React")
    assert "has supporting evidence for Docker" in note
    assert "Docker" not in note.split("has supporting evidence for")[0]
    assert "Additional evidence is under review for Kubernetes." in note

    # Supporting-only: leads with the supporting phrasing, never "demonstrates".
    note = _project_relationship_note(
        [{"skill": "Docker", "status": "Supporting evidence"}], ["GitHub Proof"]
    )
    assert note is not None
    assert "demonstrates" not in note.lower()
    assert note.startswith("This project has supporting evidence for Docker")
    assert "%" not in note and "score" not in note.lower()


def test_relationship_note_never_demonstrates_weak_only_skills() -> None:
    """When a project's top skills are ALL weak (Needs review / Not assessed /
    Insufficient evidence), the note must not use "demonstrates" at all — only
    preliminary / under-review wording."""
    from app.services.vbr_work_passport_service import _project_relationship_note

    for status in ("Needs review", "Not assessed", "Insufficient evidence"):
        top_skills = [
            {"skill": "Machine Learning", "status": status},
            {"skill": "Kubernetes", "status": "Not assessed"},
        ]
        note = _project_relationship_note(top_skills, ["GitHub Proof"])
        assert note is not None
        assert "demonstrates" not in note.lower(), status
        assert note.startswith("This project has preliminary or under-review evidence for")
        assert "Machine Learning" in note and "Kubernetes" in note
        assert "%" not in note and "score" not in note.lower()


def test_private_skill_cards_include_strongest_project_link(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _make_full_project(client, mem_store)
    body = _get_private(client).json()

    assert body["skills"]
    for skill in body["skills"]:
        link = skill["strongest_project"]
        assert link is not None
        assert link["project_title"] == skill["strongest_project_title"]
        assert link["skill_status"] in _QUALITATIVE_LABELS
        # Owner-only project report route for "View project evidence →".
        assert link["project_id"] == project_id
        assert link["project_report_path"] == f"/student/vbr/projects/{project_id}/report"
        # Unpublished project → no public path yet.
        assert link["report_is_public"] is False
        assert link["public_report_path"] is None


def test_public_skill_strongest_project_is_safe_and_published_only(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _make_full_project(client, mem_store)
    _publish_project_report(client, project_id)
    slug = _publish(client).json()["public_slug"]

    app.dependency_overrides.pop(get_current_user_id, None)
    body = _get_public(client, slug).json()

    assert body["top_skills"]
    for skill in body["top_skills"]:
        link = skill["strongest_project"]
        assert link is not None
        # Public shape: title / per-skill label / published path ONLY.
        assert set(link.keys()) == {
            "project_title",
            "skill_status",
            "evidence_sources",
            "supporting_proof_types",
            "public_report_path",
        }
        assert set(link["supporting_proof_types"]) <= _KNOWN_PROOF_TYPES
        assert link["public_report_path"].startswith("/vbr/report/")
        assert project_id not in str(link)


def test_public_projection_never_carries_private_routes(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _make_full_project(client, mem_store)
    _publish_project_report(client, project_id)
    slug = _publish(client).json()["public_slug"]

    app.dependency_overrides.pop(get_current_user_id, None)
    body = _get_public(client, slug).json()

    serialized = str(body)
    # Owner-only app routes and internal ids never ride on the public surface.
    assert "/student/vbr/" not in serialized
    assert "skill_report_path" not in serialized
    assert "project_report_path" not in serialized
    assert project_id not in serialized


def test_public_featured_projects_carry_safe_skill_chips_and_note(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _make_full_project(client, mem_store)
    _publish_project_report(client, project_id)
    slug = _publish(client).json()["public_slug"]

    app.dependency_overrides.pop(get_current_user_id, None)
    proj = _get_public(client, slug).json()["featured_projects"][0]

    assert proj["top_skills"]
    for row in proj["top_skills"]:
        # Skill + qualitative label + stable slug + safe proof-type breakdown
        # only — no private route, no score, no proof type outside the closed set.
        assert set(row.keys()) == {"skill", "status", "skill_slug", "supporting_proof_types"}
        assert row["skill_slug"]
        assert set(row["supporting_proof_types"]) <= _KNOWN_PROOF_TYPES
    note = proj["evidence_relationship_note"]
    # Defense-explained skills are conservative ("partially demonstrates") —
    # the public note must never promote explanation evidence to a full claim.
    assert note and note.startswith("This project partially demonstrates ")


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


# ── Phase 3: Proof Attachment Intelligence ─────────────────────────────────────
#
# Unattached proof becomes actionable: deterministic safe-metadata matching
# (repository / website domain / document & project titles / shared skills)
# produces owner-only suggestions with qualitative labels. Nothing is ever
# attached automatically, and none of it reaches the public projection.

_QUALITATIVE_CONFIDENCE_LABELS = {"Likely match", "Possible match", "Needs review"}


def _suggestions_of(body: dict) -> list[dict]:
    summary = body.get("unattached_proof_summary") or {}
    return summary.get("suggestions") or []


def test_private_passport_includes_attachment_suggestions(client: TestClient, mem_store: dict) -> None:
    """The private payload carries unattached_proof_summary with deterministic,
    qualitative suggestions for unattached proof."""
    _make_full_project(client, mem_store)
    # An UNATTACHED website proof whose domain names the project title.
    _seed_workflow_analysis(
        mem_store,
        target_website="https://skill-evidence-tracker.vercel.app",
        supported_skills=["React"],
    )

    body = _get_private(client).json()
    summary = body["unattached_proof_summary"]
    assert summary is not None
    assert summary["unattached_count"] >= 1
    assert summary["suggestion_count"] == len(summary["suggestions"]) >= 1
    for suggestion in summary["suggestions"]:
        # Qualitative closed-set labels only — never numeric confidence.
        assert suggestion["confidence_label"] in _QUALITATIVE_CONFIDENCE_LABELS
        assert suggestion["suggestion_reason"]
        assert suggestion["evidence_basis_chips"]
        assert suggestion["limitation"]
        assert suggestion["action_label"] == "Review and attach proof"
        assert suggestion["attachment_status"] == "Not attached to a VBR project"
        # The safe suggestion id never embeds a raw source id (it is a digest).
        assert suggestion["suggestion_id_safe"].startswith("attach-")


def test_website_proof_with_matching_domain_suggests_correct_project(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _make_full_project(client, mem_store)
    _seed_workflow_analysis(
        mem_store,
        target_website="https://skill-evidence-tracker.vercel.app",
        supported_skills=["React"],
    )

    body = _get_private(client).json()
    website = [s for s in _suggestions_of(body) if s["proof_type"] == "Website Proof"]
    assert website, "expected a Website Proof suggestion"
    suggestion = website[0]
    assert suggestion["likely_project_title"] == "Skill Evidence Tracker"
    assert suggestion["likely_project_ref_safe"] == f"/student/vbr/projects/{project_id}/report"
    assert "Matching website domain" in suggestion["evidence_basis_chips"]
    assert "Matching skill" in suggestion["evidence_basis_chips"]
    assert suggestion["confidence_label"] == "Likely match"
    # Honest hedged phrasing — never a guaranteed-link claim.
    assert "may belong to" in suggestion["suggestion_reason"]


def test_document_proof_with_matching_title_suggests_correct_project(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _make_full_project(client, mem_store)
    _seed_document_evidence(
        mem_store,
        analysis_json={"title": "Skill Evidence Tracker — Final Report"},
        evidence_objects=[{"skill_name": "Python", "page_number": 2, "snippet": "built the API"}],
    )

    body = _get_private(client).json()
    docs = [s for s in _suggestions_of(body) if s["proof_type"] == "Document Proof"]
    assert docs, "expected a Document Proof suggestion"
    suggestion = docs[0]
    assert suggestion["likely_project_title"] == "Skill Evidence Tracker"
    assert suggestion["likely_project_ref_safe"] == f"/student/vbr/projects/{project_id}/report"
    assert "Matching document title" in suggestion["evidence_basis_chips"]
    assert suggestion["confidence_label"] == "Likely match"


def test_github_proof_with_matching_repo_suggests_correct_project(
    client: TestClient, mem_store: dict
) -> None:
    # Project WITHOUT an attached GitHub proof, pointing at octocat/Hello-World.
    created = _create_project_defense(client).json()
    project_id = created["project"]["id"]
    # An unattached GitHub proof for the SAME repository.
    _seed_github_proof(mem_store)

    body = _get_private(client).json()
    github = [s for s in _suggestions_of(body) if s["proof_type"] == "GitHub Proof"]
    assert github, "expected a GitHub Proof suggestion"
    suggestion = github[0]
    assert suggestion["likely_project_title"] == "Skill Evidence Tracker"
    assert suggestion["likely_project_ref_safe"] == f"/student/vbr/projects/{project_id}/report"
    assert "Matching repository" in suggestion["evidence_basis_chips"]
    assert suggestion["confidence_label"] == "Likely match"


def test_suggestions_group_duplicate_rows_of_one_proof_source(
    client: TestClient, mem_store: dict
) -> None:
    """Many vault rows from ONE unattached proof source (a repo's per-skill
    rows) collapse into a single suggestion — never a suggestion per row."""
    _create_project_defense(client)
    _seed_github_proof(mem_store)  # detected_skills Python + React → 2+ vault rows

    body = _get_private(client).json()
    github = [s for s in _suggestions_of(body) if s["proof_type"] == "GitHub Proof"]
    assert len(github) == 1
    assert github[0]["proof_count"] >= 2


def test_skill_only_overlap_never_reads_as_likely_match(
    client: TestClient, mem_store: dict
) -> None:
    """A proof whose ONLY signal is one shared skill must stay conservative
    (Needs review) — a skill name alone is not a project match."""
    _create_project_defense(client)
    # Unattached website proof: unrelated domain, one overlapping skill (React).
    _seed_workflow_analysis(
        mem_store,
        target_website="https://unrelated-domain-zzz.example.com",
        supported_skills=["React"],
    )

    body = _get_private(client).json()
    website = [s for s in _suggestions_of(body) if s["proof_type"] == "Website Proof"]
    assert website
    assert website[0]["evidence_basis_chips"] == ["Matching skill"]
    assert website[0]["confidence_label"] == "Needs review"


def test_skill_only_tie_across_projects_stays_unmatched(
    client: TestClient, mem_store: dict
) -> None:
    """When an unattached proof's ONLY signal is a shared skill and several
    projects tie, no project is suggested — never a guess at the first one."""
    from app.services.passport_attachment_intelligence import SKILL_TIE_REVIEW_REASON

    _create_project_defense(
        client,
        title="Alpha Inventory Platform",
        repo_url="https://github.com/student/alpha-inventory",
    )
    _create_project_defense(
        client,
        title="Beta Payments Engine",
        repo_url="https://github.com/student/beta-payments",
    )
    # Unattached website proof: unrelated domain, one skill both projects claim.
    _seed_workflow_analysis(
        mem_store,
        target_website="https://unrelated-domain-zzz.example.com",
        supported_skills=["React"],
    )

    body = _get_private(client).json()
    website = [s for s in _suggestions_of(body) if s["proof_type"] == "Website Proof"]
    assert website, "the tied proof must still surface as a review row"
    suggestion = website[0]
    # No project is picked — not the first one, not any one.
    assert suggestion["likely_project_title"] == ""
    assert suggestion["likely_project_ref_safe"] is None
    assert suggestion["confidence_label"] == "Needs review"
    assert suggestion["suggestion_reason"] == SKILL_TIE_REVIEW_REASON
    assert "Alpha" not in suggestion["suggestion_reason"]
    assert "Beta" not in suggestion["suggestion_reason"]
    # The tie row never lands on any project card either.
    for project in body["projects"]:
        assert all(
            row["proof_type"] != "Website Proof" for row in project["suggested_attachments"]
        )


def test_ownerless_github_rows_do_not_merge_by_title() -> None:
    """GitHub rows WITHOUT a stable repo identity (no repo URL, no owner/name)
    never merge just because their titles match."""
    from app.services.passport_attachment_intelligence import build_attachment_suggestions

    def gh_row(source_id: str, skill: str) -> dict:
        return {
            "proof_type": "GitHub Proof",
            "source_table": "skill_evidence",
            "source_id": source_id,
            "title": "Portfolio Website",
            "skill_name": skill,
            "repo_url": None,
            "public_url": None,
            "is_attached_to_project": False,
        }

    project = {
        "project_id": "proj-1",
        "project_title": "Portfolio Website",
        "repo_full_name": None,
        "claimed_skills": ["Python", "React"],
    }
    suggestions = build_attachment_suggestions(
        [gh_row("ev-1", "Python"), gh_row("ev-2", "React")], [project]
    )
    assert len(suggestions) == 2, "ownerless rows must stay separate suggestions"
    assert all(s["proof_count"] == 1 for s in suggestions)
    assert len({s["suggestion_id_safe"] for s in suggestions}) == 2


def test_github_rows_with_stable_repo_identity_still_group() -> None:
    """Rows that DO share a stable ``owner/name`` identity keep collapsing
    into one suggestion (the ownerless fix must not break real grouping)."""
    from app.services.passport_attachment_intelligence import build_attachment_suggestions

    def gh_row(source_id: str, skill: str) -> dict:
        return {
            "proof_type": "GitHub Proof",
            "source_table": "skill_evidence",
            "source_id": source_id,
            "title": "octocat/Hello-World",
            "skill_name": skill,
            "repo_url": None,
            "public_url": None,
            "is_attached_to_project": False,
        }

    project = {
        "project_id": "proj-1",
        "project_title": "Skill Evidence Tracker",
        "repo_full_name": "octocat/Hello-World",
        "claimed_skills": ["Python", "React"],
    }
    suggestions = build_attachment_suggestions(
        [gh_row("ev-1", "Python"), gh_row("ev-2", "React")], [project]
    )
    assert len(suggestions) == 1
    assert suggestions[0]["proof_count"] == 2
    assert "Matching repository" in suggestions[0]["evidence_basis_chips"]


def test_same_title_document_suggestions_collapse_per_project() -> None:
    """Two duplicate-looking document proofs (same safe title) suggested to the
    SAME project collapse into ONE card with the grouped proof count summed —
    the passport no longer renders a near-identical row per source."""
    from app.services.passport_attachment_intelligence import build_attachment_suggestions

    def doc_row(source_id: str) -> dict:
        return {
            "proof_type": "Document Proof",
            "source_table": "optional_evidence_submissions",
            "source_id": source_id,
            "title": "Skill Evidence Tracker Report",
            "skill_name": "Python",
            "safe_summary": "",
            "safe_snippet": "",
            "is_attached_to_project": False,
        }

    project = {
        "project_id": "proj-1",
        "project_title": "Skill Evidence Tracker",
        "repo_full_name": None,
        "claimed_skills": ["Python"],
    }
    suggestions = build_attachment_suggestions([doc_row("doc-1"), doc_row("doc-2")], [project])
    assert len(suggestions) == 1, "same-title documents to one project collapse into one card"
    assert suggestions[0]["proof_count"] == 2, "the honest grouped proof count is preserved"
    # The safe suggestion id is still a one-way digest — never a raw source id.
    sid = suggestions[0]["suggestion_id_safe"]
    assert sid.startswith("attach-")
    assert "doc-1" not in sid and "doc-2" not in sid


def test_same_domain_website_suggestions_collapse_per_project() -> None:
    """Repeated unattached website proofs on the SAME domain (per-skill rows)
    collapse into one suggestion card for the project, not one card per row."""
    from app.services.passport_attachment_intelligence import build_attachment_suggestions

    def site_row(source_id: str, skill: str) -> dict:
        url = "https://stroke-prediction-app.vercel.app"
        return {
            "proof_type": "Website Proof",
            "source_table": "workflow_analysis",
            "source_id": source_id,
            "title": url,
            "public_url": url,
            "skill_name": skill,
            "is_attached_to_project": False,
        }

    project = {
        "project_id": "proj-1",
        "project_title": "Stroke Prediction App",
        "repo_full_name": None,
        "claimed_skills": ["Python", "React"],
    }
    suggestions = build_attachment_suggestions(
        [site_row("w1", "Python"), site_row("w2", "React")], [project]
    )
    assert len(suggestions) == 1, "same-domain website suggestions collapse into one card"
    assert suggestions[0]["proof_type"] == "Website Proof"
    assert suggestions[0]["proof_count"] == 2
    assert suggestions[0]["likely_project_title"] == "Stroke Prediction App"


def test_distinct_suggestions_to_different_projects_stay_separate() -> None:
    """Dedupe collapses only duplicate-looking rows — distinct proofs that belong
    to DIFFERENT projects must never be merged into one card."""
    from app.services.passport_attachment_intelligence import build_attachment_suggestions

    alpha = {
        "project_id": "a",
        "project_title": "Alpha Inventory",
        "repo_full_name": None,
        "claimed_skills": ["React"],
    }
    beta = {
        "project_id": "b",
        "project_title": "Beta Payments",
        "repo_full_name": None,
        "claimed_skills": ["Python"],
    }

    def site_row(domain: str, source_id: str, skill: str) -> dict:
        url = f"https://{domain}"
        return {
            "proof_type": "Website Proof",
            "source_table": "workflow_analysis",
            "source_id": source_id,
            "title": url,
            "public_url": url,
            "skill_name": skill,
            "is_attached_to_project": False,
        }

    suggestions = build_attachment_suggestions(
        [
            site_row("alpha-inventory.vercel.app", "w1", "React"),
            site_row("beta-payments.vercel.app", "w2", "Python"),
        ],
        [alpha, beta],
    )
    assert len(suggestions) == 2, "proofs for different projects stay separate cards"
    assert {s["likely_project_title"] for s in suggestions} == {"Alpha Inventory", "Beta Payments"}
    assert all(s["proof_count"] == 1 for s in suggestions)


def test_duplicate_same_domain_website_suggestions_collapse_in_passport(
    client: TestClient, mem_store: dict
) -> None:
    """End-to-end: repeated same-domain website proofs surface as ONE suggestion
    with the grouped count, and the clean deduplicated unattached count stays
    available on the passport for headline copy (never regressed)."""
    _make_full_project(client, mem_store)
    for _ in range(2):
        _seed_workflow_analysis(
            mem_store,
            target_website="https://skill-evidence-tracker.vercel.app",
            supported_skills=["React"],
        )

    body = _get_private(client).json()
    website = [s for s in _suggestions_of(body) if s["proof_type"] == "Website Proof"]
    assert len(website) == 1, "same-domain website suggestions collapse into one card"
    assert website[0]["proof_count"] >= 2
    # The clean deduplicated unattached count remains available (Step 4 overview).
    assert isinstance(body["attachment_overview"]["unattached_count"], int)


def test_project_cards_show_proof_chain_gaps_and_next_action(
    client: TestClient, mem_store: dict
) -> None:
    _create_project_defense(client)

    proj = _get_private(client).json()["projects"][0]
    # Qualitative chain label + concrete gaps (labels/actions only, no scores).
    assert proj["chain_label"]
    assert not any(ch.isdigit() for ch in proj["chain_label"])
    assert proj["proof_chain_gaps"]
    gap_sources = {g["source"] for g in proj["proof_chain_gaps"]}
    assert gap_sources == set(proj["proof_chain"]["missing"])
    for gap in proj["proof_chain_gaps"]:
        assert gap["gap_label"]
        assert gap["action"]
    # The next best action is the first gap's action when nothing is suggested.
    assert proj["next_best_action"] == proj["proof_chain_gaps"][0]["action"]


def test_complete_chain_has_no_gaps_and_strong_label(client: TestClient, mem_store: dict) -> None:
    _make_full_project(client, mem_store)

    proj = _get_private(client).json()["projects"][0]
    assert proj["proof_chain"]["missing"] == []
    assert proj["chain_label"] == "Strong chain"
    assert proj["proof_chain_gaps"] == []
    assert proj["next_best_action"] is None


def _proof_chain_with(**present: bool) -> dict:
    """A proof_chain dict in the passport-service shape, from source flags."""
    keys = ("github", "website", "document", "project_defense", "video")
    chain: dict = {key: bool(present.get(key)) for key in keys}
    chain["attached_count"] = sum(1 for key in keys if chain[key])
    chain["total_count"] = len(keys)
    chain["missing"] = [key for key in keys if not chain[key]]
    return chain


def test_four_source_chain_without_github_is_not_strong() -> None:
    """Source count alone never makes a Strong chain — implementation proof
    (GitHub) is core evidence."""
    from app.services.passport_attachment_intelligence import chain_label

    chain = _proof_chain_with(website=True, document=True, project_defense=True, video=True)
    assert chain["attached_count"] == 4
    assert chain_label(chain) == "Needs implementation proof"


def test_four_source_chain_without_runtime_proof_is_not_strong() -> None:
    """Four sources missing runtime/product behavior evidence (Website) must
    not read as Strong chain."""
    from app.services.passport_attachment_intelligence import chain_label

    chain = _proof_chain_with(github=True, document=True, project_defense=True, video=True)
    assert chain["attached_count"] == 4
    assert chain_label(chain) == "Needs runtime proof"


def test_document_and_defense_alone_never_read_strong() -> None:
    from app.services.passport_attachment_intelligence import chain_label

    chain = _proof_chain_with(document=True, project_defense=True)
    label = chain_label(chain)
    assert label != "Strong chain"
    assert label == "Needs implementation proof"


def test_core_evidence_with_three_sources_reads_good_supporting_chain() -> None:
    from app.services.passport_attachment_intelligence import chain_label

    chain = _proof_chain_with(github=True, website=True, project_defense=True)
    assert chain_label(chain) == "Good supporting chain"
    # Core evidence + four sources is where Strong begins.
    strong = _proof_chain_with(github=True, website=True, document=True, project_defense=True)
    assert chain_label(strong) == "Strong chain"


def test_project_card_lists_suggested_attachments_for_it(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _create_project_defense(client).json()["project"]["id"]
    _seed_github_proof(mem_store)

    proj = next(
        p for p in _get_private(client).json()["projects"] if p["project_id"] == project_id
    )
    assert proj["suggested_attachments"], "expected the repo-matched suggestion on the card"
    row = proj["suggested_attachments"][0]
    assert row["proof_type"] == "GitHub Proof"
    assert row["confidence_label"] in _QUALITATIVE_CONFIDENCE_LABELS
    assert row["suggestion_reason"]
    # The card's next action points at reviewing the suggestion (review-only).
    assert proj["next_best_action"].startswith("Review and attach")


def test_suggestions_never_mutate_projects_or_attach_proof(
    client: TestClient, mem_store: dict
) -> None:
    """Building the passport (with suggestions present) is read-only: no
    project metadata changes, and the proof stays unattached on re-read."""
    import copy

    _create_project_defense(client)
    _seed_github_proof(mem_store)
    before = copy.deepcopy(mem_store.get("vbr_projects", {}))

    first = _get_private(client).json()
    second = _get_private(client).json()

    assert mem_store.get("vbr_projects", {}) == before
    assert first["vault_unattached_count"] == second["vault_unattached_count"] > 0
    assert len(_suggestions_of(first)) == len(_suggestions_of(second)) > 0


def test_public_passport_strips_attachment_suggestions_and_private_ids(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _make_full_project(client, mem_store)
    _seed_workflow_analysis(
        mem_store,
        target_website="https://skill-evidence-tracker.vercel.app",
        supported_skills=["React"],
    )
    _publish_project_report(client, project_id)
    slug = _publish(client).json()["public_slug"]

    app.dependency_overrides.pop(get_current_user_id, None)
    body = _get_public(client, slug).json()
    dump = str(body)

    # No suggestion objects, owner-only routes, matching chips, or private ids.
    assert "unattached_proof_summary" not in body
    assert "suggestion" not in dump.lower()
    assert "Likely match" not in dump
    assert "/student/vbr/projects/" not in dump
    assert project_id not in dump
    for project in body["featured_projects"]:
        assert "suggested_attachments" not in project
        assert "next_best_action" not in project
        assert "proof_chain_gaps" not in project
        assert "chain_label" not in project


def test_public_passport_keeps_safe_unattached_limitation_only(
    client: TestClient, mem_store: dict
) -> None:
    from app.services.passport_attachment_intelligence import PUBLIC_UNATTACHED_LIMITATION

    project_id = _make_full_project(client, mem_store)
    _seed_workflow_analysis(
        mem_store,
        target_website="https://skill-evidence-tracker.vercel.app",
        supported_skills=["React"],
    )
    _publish_project_report(client, project_id)
    slug = _publish(client).json()["public_slug"]

    app.dependency_overrides.pop(get_current_user_id, None)
    body = _get_public(client, slug).json()
    assert PUBLIC_UNATTACHED_LIMITATION in body["limitations"]
    # The limitation is count-free and id-free (an honest sentence only).
    assert not any(ch.isdigit() for ch in PUBLIC_UNATTACHED_LIMITATION)


# ── Attachment Intelligence Cleanup (Step 4): attached / suggested / unattached ─


def test_private_passport_carries_attachment_overview(client: TestClient, mem_store: dict) -> None:
    """The private passport exposes disjoint, deduplicated attached / suggested /
    unattached sections whose counts drive the evidence-graph overview."""
    _make_full_project(client, mem_store)
    # One unattached document naming the project → a suggestion, never attached.
    _seed_document_evidence(
        mem_store, analysis_json={"title": "Skill Evidence Tracker — Design Report"}
    )

    body = _get_private(client).json()
    overview = body["attachment_overview"]
    assert overview is not None

    assert overview["attached_count"] == len(overview["attached"]) > 0
    assert overview["suggested_count"] == len(overview["suggested"]) >= 1
    assert overview["unattached_count"] == len(overview["unattached"])
    assert overview["note"] == "Suggested — not counted until attached"

    for entry in overview["attached"]:
        assert entry["attachment_state"] == "attached"
        assert entry["relation_strength"] == "deterministic"
    for entry in overview["suggested"]:
        assert entry["attachment_state"] == "suggested"
        assert entry["relation_strength"] in ("likely", "weak")
        assert entry["status_label"] == "Suggested — not counted until attached"

    # Entry ids are unique across all three sections (stable React keys).
    ids = [
        e["entry_id_safe"]
        for e in overview["attached"] + overview["suggested"] + overview["unattached"]
    ]
    assert len(ids) == len(set(ids))

    graph = body["evidence_graph_overview"]
    assert graph["attached_proof_count"] == overview["attached_count"]
    assert graph["suggested_proof_count"] == overview["suggested_count"]
    assert graph["unattached_proof_count"] == overview["unattached_count"]
    assert graph["proof_count"] == (
        overview["attached_count"] + overview["suggested_count"] + overview["unattached_count"]
    )


def test_passport_counts_do_not_inflate_from_duplicate_document_rows(
    client: TestClient, mem_store: dict
) -> None:
    """Two vault rows for the same document (same safe title) collapse into ONE
    display entry — duplicate rows never inflate the passport counts."""
    _make_full_project(client, mem_store)
    for _ in range(2):
        _seed_document_evidence(
            mem_store, analysis_json={"title": "Completely Unrelated Elsewhere Notes"}
        )

    body = _get_private(client).json()
    overview = body["attachment_overview"]
    matching = [
        e
        for e in overview["suggested"] + overview["unattached"]
        if e["display_title"] == "Completely Unrelated Elsewhere Notes"
    ]
    assert len(matching) == 1
    assert matching[0]["duplicate_count"] == 2


def test_public_passport_never_carries_attachment_overview_or_suggestions(
    client: TestClient, mem_store: dict
) -> None:
    """The public passport must not expose the attachment overview, suggestion
    labels, reason codes, or relation-strength labels."""
    project_id = _make_full_project(client, mem_store)
    _seed_document_evidence(
        mem_store, analysis_json={"title": "Skill Evidence Tracker — Design Report"}
    )
    assert _publish_project_report(client, project_id).status_code == 200
    slug = _publish(client).json()["public_slug"]

    public = _get_public(client, slug)
    assert public.status_code == 200
    body = public.json()
    assert "attachment_overview" not in body
    assert "unattached_proof_summary" not in body
    text = public.text
    assert "Suggested — not counted until attached" not in text
    assert "relation_reason" not in text
    assert "relation_strength" not in text
    assert "suggestion_reason" not in text


# ── Project-level-only proof context (GitHub + Website, not skill-mapped) ──────
#
# GitHub/Website proof can be ATTACHED to a project yet map to NO skill (the
# detected skills / observed behaviour do not match a claimed skill). It must
# stay PROJECT-LEVEL: never a skill→project GitHub/Website chip, never counted
# under Skills — but the passport exposes a safe, honest "needs skill mapping"
# context so the Skills Evidence Map can show it under the GitHub / Website
# proof filter (linking to the report to inspect / improve the mapping).


def _project_level_context(body: dict) -> list[dict]:
    return body.get("project_level_proof_context") or []


def _github_contexts(body: dict) -> list[dict]:
    return [c for c in _project_level_context(body) if c["proof_type"] == "GitHub Proof"]


def _website_contexts(body: dict) -> list[dict]:
    return [c for c in _project_level_context(body) if c["proof_type"] == "Website Proof"]


def test_passport_emits_project_level_github_context_when_attached_but_unmapped(
    client: TestClient, mem_store: dict
) -> None:
    """(A) A GitHub Proof attached to a project whose detected skills match no
    claimed skill maps no skill row, yet the passport surfaces a safe project-level
    GitHub context: 'Needs skill mapping', an owner-only report route, a safe repo
    label, ``has_exact_skill_mapping == False`` and ``safe_inspection_available``."""
    gh = _seed_github_proof(mem_store, detected_skills=["Python", "React"])
    _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"github_proof_id": gh},
    )
    body = _get_private(client).json()

    ctxs = _github_contexts(body)
    assert len(ctxs) == 1
    ctx = ctxs[0]
    assert ctx["status"] == "Needs skill mapping"
    assert ctx["has_exact_skill_mapping"] is False
    assert ctx["safe_inspection_available"] is True
    assert ctx["safe_source_label"] == "octocat/Hello-World"
    assert ctx["report_url"].endswith("/report")
    assert ctx["reason_not_skill_mapped"]
    # Summary is already score-scrubbed by the report builder — never a raw score.
    assert "confidence" not in ctx["summary"].lower()
    assert "/100" not in ctx["summary"]


def test_passport_emits_project_level_website_context_when_attached_but_unmapped(
    client: TestClient, mem_store: dict
) -> None:
    """(B) A navigation/layout Website Proof (maps no skill) surfaces a Website
    project-level context in the generalized ``project_level_proof_context``."""
    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=[],
        workflow_summary="Navigated between the app's pages using the sidebar menu.",
    )
    _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"website_proof_session_ids": [session_id]},
    )
    body = _get_private(client).json()

    ctxs = _website_contexts(body)
    assert len(ctxs) >= 1
    ctx = ctxs[0]
    assert ctx["proof_type"] == "Website Proof"
    assert ctx["status"] == "Needs skill mapping"
    assert ctx["has_exact_skill_mapping"] is False
    assert ctx["report_url"].endswith("/report")


def test_project_level_context_adds_no_supporting_proof_types_to_skills(
    client: TestClient, mem_store: dict
) -> None:
    """(C) Project-level GitHub/Website proof never becomes a skill's supporting
    proof type — no skill→project ref advertises it."""
    gh = _seed_github_proof(mem_store, detected_skills=["Python", "React"])
    session_id = _seed_workflow_analysis(
        mem_store,
        supported_skills=[],
        weakly_supported_skills=[],
        workflow_summary="Navigated between the app's pages using the sidebar menu.",
    )
    _create_project_defense(
        client,
        claimed_skills=["Machine Learning"],
        attached_proofs={"github_proof_id": gh, "website_proof_session_ids": [session_id]},
    )
    body = _get_private(client).json()

    assert _github_contexts(body), "expected a project-level GitHub context"
    assert _website_contexts(body), "expected a project-level Website context"
    for skill in body["skills"]:
        for ref in skill["projects"]:
            proof_types = ref.get("supporting_proof_types") or []
            assert "GitHub Proof" not in proof_types
            assert "Website Proof" not in proof_types


def test_exact_mapped_github_row_appears_and_no_project_level_github_context(
    client: TestClient, mem_store: dict
) -> None:
    """(D) When the GitHub Proof's detected skills DO match claimed skills, the
    exact skill→project GitHub row appears normally and NO project-level GitHub
    context is emitted for that project (it mapped a skill)."""
    gh = _seed_github_proof(mem_store, detected_skills=["Python", "React"])
    _create_project_defense(
        client,
        claimed_skills=["Python", "React"],
        attached_proofs={"github_proof_id": gh},
    )
    body = _get_private(client).json()

    # Exact GitHub rows exist.
    assert any(
        "GitHub Proof" in (ref.get("supporting_proof_types") or [])
        for skill in body["skills"]
        for ref in skill["projects"]
    )
    # …and no project-level GitHub "needs skill mapping" context for this project.
    assert _github_contexts(body) == []


def test_unattached_vault_github_proof_is_not_project_level_attached_context(
    client: TestClient, mem_store: dict
) -> None:
    """(E) A GitHub Proof that lives only in the vault (never attached to a
    project) is never surfaced as ATTACHED project-level context — no GitHub
    context claims analyzed evidence is inspectable for it."""
    # Seed a standalone (unattached) GitHub Proof, then a project that does NOT
    # attach it.
    _seed_github_proof(mem_store, detected_skills=["Python", "React"])
    _create_project_defense(client, claimed_skills=["Machine Learning"], attached_proofs={})
    body = _get_private(client).json()

    # The vault has the standalone proof …
    assert body["vault_proof_count"] >= 1
    # … but no GitHub context presents it as attached/analyzed project evidence.
    for ctx in _github_contexts(body):
        assert ctx["safe_inspection_available"] is False


def test_project_level_github_proof_does_not_spray_across_claimed_skills(
    client: TestClient, mem_store: dict
) -> None:
    """(F) A single project's unmapped GitHub Proof produces exactly ONE project-
    level context (per project), never one per claimed skill, and never marks any
    of the claimed skills as GitHub-supported."""
    gh = _seed_github_proof(mem_store, detected_skills=["Python", "React"])
    _create_project_defense(
        client,
        claimed_skills=["Machine Learning", "Data Engineering", "MLOps"],
        attached_proofs={"github_proof_id": gh},
    )
    body = _get_private(client).json()

    ctxs = _github_contexts(body)
    assert len(ctxs) == 1  # one per project, not per skill
    for skill in body["skills"]:
        for ref in skill["projects"]:
            assert "GitHub Proof" not in (ref.get("supporting_proof_types") or [])
