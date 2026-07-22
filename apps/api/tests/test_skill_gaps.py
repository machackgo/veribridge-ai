"""
Evidence-derived Skill Gaps — rule table, fallback, isolation and DTO tests.

Covers every row of the deterministic rule table in
``app/services/skill_gap_service.py``:

  1. demonstrated (counted+primary / ladder demonstrated)  → NOT a gap
  2. partially_demonstrated (counted supporting)           → Partially demonstrated
  3. links exist but none counted (excluded/pending)       → Insufficient evidence
  4. website supported/weakly-supported, nothing counted   → Insufficient evidence
  5. website unsupported (attempted, not demonstrated)     → Missing evidence
  6. claimed / link-less claim, no mention anywhere        → Not assessed
  7. no claimed skills and no claim rows (website-only     → project fallback,
     outcomes can never form items)                          zero fabricated items

Plus:
  - the e5e74ace-shaped fixture reproducing the production worked example
  - incomplete (recording) website sessions are never used as evidence
  - tenant isolation: cross-user project id → 404, list excludes other users
  - endpoint DTO shape
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.skill_gap_service import (
    build_project_skill_gap_report,
    build_user_skill_gaps,
)

USER_ID = "00000000-0000-0000-0000-0000000000aa"
OTHER_USER_ID = "00000000-0000-0000-0000-0000000000bb"
PROJECT_ID = "pppppppp-0000-0000-0000-000000000001"
OTHER_PROJECT_ID = "pppppppp-0000-0000-0000-000000000002"
SESSION_ID = "ssssssss-0000-0000-0000-000000000001"


# ── Fixture helpers ───────────────────────────────────────────────────────────


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _add_project(
    db: dict,
    *,
    project_id: str = PROJECT_ID,
    user_id: str = USER_ID,
    title: str = "Analytics Project",
    claimed_skills: list[str] | None = None,
) -> dict:
    row = {
        "id": project_id,
        "user_id": user_id,
        "title": title,
        "metadata": {"claimed_skills": claimed_skills or []},
        "created_at": "2026-07-20T00:00:00+00:00",
    }
    db.setdefault("vbr_projects", {})[project_id] = row
    return row


def _add_claim(
    db: dict,
    *,
    skill: str,
    evidence_status: str = "not_assessed",
    project_id: str = PROJECT_ID,
) -> str:
    claim_id = f"claim:{project_id}:{skill.lower()}"
    db.setdefault("vbr_project_skill_claims", {})[claim_id] = {
        "id": claim_id,
        "project_id": project_id,
        "skill_key": skill.lower(),
        "skill_name": skill,
        "claim_state": "claimed",
        "evidence_status": evidence_status,
    }
    return claim_id


def _add_link(
    db: dict,
    *,
    claim_id: str,
    link_status: str,
    quality: str,
    proof_type: str = "document",
    citation_type: str = "document_block",
    reason: str = "The document cites this skill at an exact page/section/block locator.",
    limitations: list[str] | None = None,
) -> str:
    link_id = f"link:{claim_id}:{link_status}:{quality}:{proof_type}"
    db.setdefault("vbr_claim_evidence_links", {})[link_id] = {
        "id": link_id,
        "project_skill_claim_id": claim_id,
        "proof_type": proof_type,
        "proof_id": f"proof:{proof_type}",
        "citation_type": citation_type,
        "link_status": link_status,
        "evidence_quality": quality,
        "link_reason": reason,
        "limitations": limitations or [],
    }
    return link_id


def _add_website_session(
    db: dict,
    *,
    session_id: str = SESSION_ID,
    user_id: str = USER_ID,
    project_id: str = PROJECT_ID,
    status: str = "completed",
    supported: list[str] | None = None,
    weakly: list[str] | None = None,
    unsupported: list[str] | None = None,
) -> None:
    db.setdefault("extension_proof_sessions", {})[session_id] = {
        "id": session_id,
        "user_id": user_id,
        "status": status,
        "metadata": {"project_id": project_id},
        "created_at": "2026-07-20T01:00:00+00:00",
    }
    db.setdefault("workflow_analysis_results", {})[f"analysis:{session_id}"] = {
        "id": f"analysis:{session_id}",
        "proof_session_id": session_id,
        "analysis_type": "timeline_only",
        "supported_skills": supported or [],
        "weakly_supported_skills": weakly or [],
        "unsupported_skills": unsupported or [],
        "created_at": "2026-07-20T02:00:00+00:00",
    }


def _report(db: dict, project_id: str = PROJECT_ID, user_id: str = USER_ID) -> dict:
    return build_project_skill_gap_report(
        db, user_id=user_id, project=db["vbr_projects"][project_id]
    )


def _item(report: dict, skill: str) -> dict:
    matches = [i for i in report["gap_items"] if i["skill_name"] == skill]
    assert matches, f"no gap item for {skill!r}: {[i['skill_name'] for i in report['gap_items']]}"
    return matches[0]


# ── Rule table ────────────────────────────────────────────────────────────────


class TestRuleTable:
    def test_rule1_demonstrated_is_not_a_gap(self, mem_store: dict) -> None:
        _add_project(mem_store, claimed_skills=["React"])
        claim_id = _add_claim(mem_store, skill="React", evidence_status="demonstrated")
        _add_link(mem_store, claim_id=claim_id, link_status="counted", quality="primary")
        report = _report(mem_store)
        assert report["demonstrated_skills"] == ["React"]
        assert report["gap_items"] == []
        assert report["summary"]["demonstrated"] == 1

    def test_rule1_counted_primary_link_wins_even_if_ladder_lags(self, mem_store: dict) -> None:
        _add_project(mem_store, claimed_skills=["React"])
        claim_id = _add_claim(mem_store, skill="React", evidence_status="not_assessed")
        _add_link(mem_store, claim_id=claim_id, link_status="counted", quality="primary")
        report = _report(mem_store)
        assert report["demonstrated_skills"] == ["React"]

    def test_rule2_counted_supporting_is_partially_demonstrated(self, mem_store: dict) -> None:
        _add_project(mem_store, claimed_skills=["Data Visualization"])
        claim_id = _add_claim(
            mem_store, skill="Data Visualization", evidence_status="partially_demonstrated"
        )
        link_id = _add_link(mem_store, claim_id=claim_id, link_status="counted", quality="supporting")
        item = _item(_report(mem_store), "Data Visualization")
        assert item["status"] == "partially_demonstrated"
        assert item["status_label"] == "Partially demonstrated"
        assert item["claim_id"] == claim_id
        assert "no primary" in item["why"].lower()
        # Exact evidence basis: the counted link with its stored reason.
        basis_ids = [b["reference_id"] for b in item["evidence_basis"]]
        assert link_id in basis_ids
        assert any("exact page/section/block" in b["detail"] for b in item["evidence_basis"])
        assert "primary citation" in item["recommended_action"]

    def test_rule3_excluded_context_links_are_insufficient(self, mem_store: dict) -> None:
        _add_project(mem_store, claimed_skills=[])
        claim_id = _add_claim(mem_store, skill="CI/CD", evidence_status="not_assessed")
        _add_link(
            mem_store,
            claim_id=claim_id,
            link_status="excluded",
            quality="context",
            proof_type="github",
            citation_type="github_code_lines",
            reason="Detected at repository level only — context, not implementation proof.",
        )
        item = _item(_report(mem_store), "CI/CD")
        assert item["status"] == "insufficient_evidence"
        assert "Detected at repository level only" in item["why"]
        assert "github" in item["recommended_action"].lower() or "citation" in item["recommended_action"].lower()

    def test_rule3_pending_links_are_insufficient(self, mem_store: dict) -> None:
        _add_project(mem_store, claimed_skills=["SQL"])
        claim_id = _add_claim(mem_store, skill="SQL", evidence_status="not_assessed")
        _add_link(
            mem_store,
            claim_id=claim_id,
            link_status="pending",
            quality="insufficient",
            reason="Skill detected without a specific citation.",
        )
        item = _item(_report(mem_store), "SQL")
        assert item["status"] == "insufficient_evidence"
        assert "Skill detected without a specific citation." in item["why"]

    def test_rule4_website_supported_but_unlinked_is_insufficient(self, mem_store: dict) -> None:
        _add_project(mem_store, claimed_skills=["React"])
        _add_website_session(mem_store, supported=["React"])
        item = _item(_report(mem_store), "React")
        assert item["status"] == "insufficient_evidence"
        assert "no counted evidence links it" in item["why"]
        assert any(b["kind"] == "website_analysis" for b in item["evidence_basis"])

    def test_rule4_website_weak_support_is_insufficient(self, mem_store: dict) -> None:
        _add_project(mem_store, claimed_skills=["React"])
        _add_website_session(mem_store, weakly=["React"])
        item = _item(_report(mem_store), "React")
        assert item["status"] == "insufficient_evidence"

    def test_rule5_website_unsupported_is_missing_evidence(self, mem_store: dict) -> None:
        _add_project(mem_store, claimed_skills=["Web Analytics"])
        _add_website_session(mem_store, unsupported=["Web Analytics"])
        item = _item(_report(mem_store), "Web Analytics")
        assert item["status"] == "missing_evidence"
        assert item["status_label"] == "Missing evidence"
        assert "attempted this skill at runtime" in item["why"]
        basis = [b for b in item["evidence_basis"] if b["kind"] == "website_analysis"]
        assert basis and basis[0]["proof_id"] == SESSION_ID
        assert "workflow" in item["recommended_action"].lower()

    def test_rule5_case_insensitive_skill_match(self, mem_store: dict) -> None:
        # Prod reality: claimed "Dashboard UX" vs analysis "Dashboard Ux".
        _add_project(mem_store, claimed_skills=["Dashboard UX"])
        _add_website_session(mem_store, unsupported=["Dashboard Ux"])
        item = _item(_report(mem_store), "Dashboard UX")
        assert item["status"] == "missing_evidence"

    def test_rule6_claimed_with_no_evidence_anywhere_is_not_assessed(self, mem_store: dict) -> None:
        _add_project(mem_store, claimed_skills=["Kubernetes"])
        item = _item(_report(mem_store), "Kubernetes")
        assert item["status"] == "not_assessed"
        assert "no attached proof has been assessed" in item["why"]
        assert any(b["kind"] == "claimed_skill" for b in item["evidence_basis"])

    def test_rule6_linkless_claim_row_is_not_assessed(self, mem_store: dict) -> None:
        _add_project(mem_store, claimed_skills=[])
        _add_claim(mem_store, skill="GraphQL", evidence_status="not_assessed")
        # Another skill's evidence keeps the project assessable.
        _add_website_session(mem_store, unsupported=["Something Else"])
        item = _item(_report(mem_store), "GraphQL")
        assert item["status"] == "not_assessed"
        assert "no evidence has been linked" in item["why"]

    def test_rule7_project_without_evidence_falls_back_honestly(self, mem_store: dict) -> None:
        _add_project(mem_store, claimed_skills=[])
        report = _report(mem_store)
        assert report["assessment_state"] == "insufficient_evidence"
        assert "Not enough evidence to assess" in report["insufficient_evidence_note"]
        assert report["gap_items"] == []
        assert report["summary"]["total_claimed"] == 0

    def test_rule7_website_outcomes_alone_are_not_assessable(self, mem_store: dict) -> None:
        # A completed analysis with nothing claimed and no claim rows must NOT
        # yield an "assessed / no gaps" verdict — nothing claims any skill, so
        # the honest state is the explicit insufficient-evidence fallback.
        _add_project(mem_store, claimed_skills=[])
        _add_website_session(
            mem_store, supported=["React"], unsupported=["Machine Learning"]
        )
        report = _report(mem_store)
        assert report["assessment_state"] == "insufficient_evidence"
        assert report["gap_items"] == []
        assert report["demonstrated_skills"] == []

    def test_case_variant_claimed_duplicates_yield_one_item(self, mem_store: dict) -> None:
        _add_project(mem_store, claimed_skills=["React", "react "])
        report = _report(mem_store)
        names = [i["skill_name"] for i in report["gap_items"]]
        assert names == ["React"]
        assert report["claimed_skills"] == ["React"]
        assert report["summary"]["total_claimed"] == 1
        assert report["summary"]["not_assessed"] == 1

    def test_claim_ladder_beats_website_unsupported(self, mem_store: dict) -> None:
        # Canonical demonstrated axis wins; the runtime outcome stays in basis.
        _add_project(mem_store, claimed_skills=["Data Visualization"])
        claim_id = _add_claim(
            mem_store, skill="Data Visualization", evidence_status="partially_demonstrated"
        )
        _add_link(mem_store, claim_id=claim_id, link_status="counted", quality="supporting")
        _add_website_session(mem_store, unsupported=["Data Visualization"])
        item = _item(_report(mem_store), "Data Visualization")
        assert item["status"] == "partially_demonstrated"
        assert any(b["kind"] == "website_analysis" for b in item["evidence_basis"])

    def test_incomplete_recording_session_is_never_evidence(self, mem_store: dict) -> None:
        _add_project(mem_store, claimed_skills=["Web Analytics"])
        _add_website_session(
            mem_store, status="recording", unsupported=["Web Analytics"]
        )
        item = _item(_report(mem_store), "Web Analytics")
        # Without a COMPLETED analysis the honest state is Not assessed,
        # not a fabricated Missing-evidence verdict.
        assert item["status"] == "not_assessed"

    def test_website_only_skills_are_never_invented_as_gaps(self, mem_store: dict) -> None:
        _add_project(mem_store, claimed_skills=["React"])
        _add_website_session(
            mem_store, supported=["React"], unsupported=["Machine Learning"]
        )
        report = _report(mem_store)
        names = [i["skill_name"] for i in report["gap_items"]]
        assert "Machine Learning" not in names


# ── Production worked example (project e5e74ace, account 148) ────────────────


class TestWorkedExample:
    def _build(self, db: dict) -> dict:
        _add_project(
            db,
            title="MULTIUSER-148-WEB-ANALYTICS",
            claimed_skills=["Web Analytics", "Data Visualization", "Dashboard UX"],
        )
        # Data Visualization: counted/supporting document link → partially.
        dv = _add_claim(db, skill="Data Visualization", evidence_status="partially_demonstrated")
        _add_link(db, claim_id=dv, link_status="counted", quality="supporting")
        # CI/CD, Cloud Deployment, JavaScript, SQL/PostgreSQL: excluded/context
        # github links only (evidence_status still not_assessed in prod).
        for skill in ("CI/CD", "Cloud Deployment", "JavaScript", "SQL/PostgreSQL"):
            claim_id = _add_claim(db, skill=skill, evidence_status="not_assessed")
            _add_link(
                db,
                claim_id=claim_id,
                link_status="excluded",
                quality="context",
                proof_type="github",
                citation_type="github_code_lines",
                reason="Detected at repository level only — context, not implementation proof.",
            )
        # Other partially demonstrated claims (counted supporting doc links).
        for skill in ("React", "Next.js", "PostgreSQL"):
            claim_id = _add_claim(db, skill=skill, evidence_status="partially_demonstrated")
            _add_link(db, claim_id=claim_id, link_status="counted", quality="supporting")
        # Completed website session: all three claimed skills unsupported
        # (note prod's "Dashboard Ux" casing) + one still-recording session
        # that must be ignored.
        _add_website_session(
            db,
            unsupported=["Web Analytics", "Data Visualization", "Dashboard Ux"],
        )
        _add_website_session(
            db,
            session_id="ssssssss-0000-0000-0000-000000000099",
            status="recording",
        )
        return _report(db)

    def test_statuses_match_production_reality(self, mem_store: dict) -> None:
        report = self._build(mem_store)
        by_skill = {i["skill_name"]: i["status"] for i in report["gap_items"]}
        # Claimed at runtime but never demonstrated, no claim rows → Missing.
        assert by_skill["Web Analytics"] == "missing_evidence"
        assert by_skill["Dashboard UX"] == "missing_evidence"
        # Counted supporting document citation → Partially demonstrated
        # (canonical axis wins over the runtime unsupported outcome).
        assert by_skill["Data Visualization"] == "partially_demonstrated"
        # Excluded/context github links only → Insufficient evidence.
        for skill in ("CI/CD", "Cloud Deployment", "JavaScript", "SQL/PostgreSQL"):
            assert by_skill[skill] == "insufficient_evidence"
        assert by_skill["React"] == "partially_demonstrated"
        # Nothing on the project is demonstrated (no primary link anywhere).
        assert report["demonstrated_skills"] == []
        assert report["summary"]["demonstrated"] == 0
        assert report["assessment_state"] == "assessed"

    def test_every_item_carries_basis_why_and_action(self, mem_store: dict) -> None:
        report = self._build(mem_store)
        for item in report["gap_items"]:
            assert item["why"].strip()
            assert item["recommended_action"].strip()
            assert item["evidence_basis"], f"{item['skill_name']} has no evidence basis"


# ── Tenant isolation ──────────────────────────────────────────────────────────


class TestIsolation:
    def test_cross_user_project_is_404(self, client: TestClient, mem_store: dict) -> None:
        _add_project(
            mem_store,
            project_id=OTHER_PROJECT_ID,
            user_id=OTHER_USER_ID,
            claimed_skills=["React"],
        )
        response = client.get(f"/api/v1/student/skill-gaps/projects/{OTHER_PROJECT_ID}")
        assert response.status_code == 404
        assert "React" not in response.text

    def test_unknown_project_is_404(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/student/skill-gaps/projects/00000000-0000-0000-0000-00000000dead"
        )
        assert response.status_code == 404

    def test_overview_excludes_other_users_projects(
        self, client: TestClient, mem_store: dict
    ) -> None:
        _add_project(mem_store, claimed_skills=["React"])
        _add_project(
            mem_store,
            project_id=OTHER_PROJECT_ID,
            user_id=OTHER_USER_ID,
            title="Someone Else's Project",
            claimed_skills=["Secret Skill"],
        )
        response = client.get("/api/v1/student/skill-gaps")
        assert response.status_code == 200
        body = response.json()
        titles = [p["project_title"] for p in body["projects"]]
        assert titles == ["Analytics Project"]
        assert "Secret Skill" not in response.text

    def test_service_never_uses_other_users_sessions(self, mem_store: dict) -> None:
        _add_project(mem_store, claimed_skills=["Web Analytics"])
        # Another user's completed session pointing at MY project id must not count.
        _add_website_session(
            mem_store,
            user_id=OTHER_USER_ID,
            unsupported=["Web Analytics"],
        )
        item = _item(_report(mem_store), "Web Analytics")
        assert item["status"] == "not_assessed"


# ── Endpoint DTO ──────────────────────────────────────────────────────────────


class TestEndpointDTO:
    def test_overview_shape(self, client: TestClient, mem_store: dict) -> None:
        _add_project(mem_store, claimed_skills=["Web Analytics"])
        _add_website_session(mem_store, unsupported=["Web Analytics"])
        body = client.get("/api/v1/student/skill-gaps").json()
        assert body["total_gap_count"] == 1
        assert body["generated_at"]
        project = body["projects"][0]
        assert project["project_id"] == PROJECT_ID
        assert project["assessment_state"] == "assessed"
        item = project["gap_items"][0]
        assert set(item) >= {
            "skill_name",
            "skill_key",
            "status",
            "status_label",
            "why",
            "evidence_basis",
            "recommended_action",
            "claim_id",
        }
        basis = item["evidence_basis"][0]
        assert set(basis) >= {
            "kind",
            "reference_id",
            "proof_type",
            "proof_id",
            "citation_type",
            "link_status",
            "evidence_quality",
            "detail",
            "limitations",
        }

    def test_per_project_shape_matches_overview(
        self, client: TestClient, mem_store: dict
    ) -> None:
        _add_project(mem_store, claimed_skills=["Web Analytics"])
        _add_website_session(mem_store, unsupported=["Web Analytics"])
        single = client.get(f"/api/v1/student/skill-gaps/projects/{PROJECT_ID}").json()
        overview = client.get("/api/v1/student/skill-gaps").json()["projects"][0]
        assert single == overview

    def test_insufficient_evidence_project_in_overview(
        self, client: TestClient, mem_store: dict
    ) -> None:
        _add_project(mem_store, claimed_skills=[])
        body = client.get("/api/v1/student/skill-gaps").json()
        project = body["projects"][0]
        assert project["assessment_state"] == "insufficient_evidence"
        assert "Not enough evidence to assess" in project["insufficient_evidence_note"]
        assert body["total_gap_count"] == 0


# ── User-level aggregation ────────────────────────────────────────────────────


class TestUserAggregation:
    def test_projects_ordered_newest_first_and_counted(self, mem_store: dict) -> None:
        first = _add_project(mem_store, claimed_skills=["Web Analytics"])
        first["created_at"] = "2026-07-19T00:00:00+00:00"
        second = _add_project(
            mem_store,
            project_id=OTHER_PROJECT_ID,
            title="Newer Project",
            claimed_skills=["React"],
        )
        second["created_at"] = "2026-07-21T00:00:00+00:00"
        result = build_user_skill_gaps(mem_store, user_id=USER_ID)
        assert [p["project_title"] for p in result["projects"]] == [
            "Newer Project",
            "Analytics Project",
        ]
        assert result["total_gap_count"] == 2  # both Not assessed
