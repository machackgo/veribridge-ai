"""Acceptance regressions for the canonical project/claim/evidence spine."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.services.canonical_evidence_service import (
    CanonicalEvidenceConflictError,
    CanonicalEvidenceNotFoundError,
    CanonicalEvidencePreconditionError,
    confirm_project_relationship,
    finalize_proof_evidence,
)
from app.services.claim_evidence_synthesis_service import build_skill_claim_evidence_map
from app.services.vbr_student_report import build_student_vbr_report
from app.services.vbr_work_passport_service import build_private_passport
from app.services.student_proof_vault_service import collect_skill_report, collect_vault_items
from tests.test_vbr_project_defense import USER_ID

REAL_SESSION_ID = "fe658e5c-f8c5-47b8-8ff5-2c3a135b09b5"
MIGRATION_058 = (
    Path(__file__).parents[1]
    / "app/db/migrations/058_canonical_evidence_relationships.sql"
)


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def pipeline_db() -> dict:
    return {}


def _project(
    store: dict,
    *,
    title: str,
    repo: str,
    claimed_skills: list[str] | None = None,
    website_session_ids: list[str] | None = None,
) -> dict:
    pid = str(uuid4())
    website_proofs = [
        {
            "proof_session_id": sid,
            "target_website": "http://localhost:3000",
            "evidence_strength_score": 75,
            "workflow_confidence": "high",
            "supported_skills": ["React"],
        }
        for sid in (website_session_ids or [])
    ]
    row = {
        "id": pid,
        "user_id": USER_ID,
        "title": title,
        "repo_url": f"https://github.com/{repo}",
        "repo_full_name": repo,
        "deployed_url": None,
        "status": "report_drafted",
        "metadata": {
            "claimed_skills": claimed_skills or ["React"],
            "description": f"{title} project",
            "attached_proofs": {"website_proofs": website_proofs},
        },
        "created_at": "2026-07-12T00:00:00+00:00",
        "updated_at": "2026-07-12T00:00:00+00:00",
    }
    store.setdefault("vbr_projects", {})[pid] = row
    return row


def _website_fixture(
    store: dict,
    *,
    project_id: str | None,
    objective: str,
    retained: bool = True,
    session_id: str = REAL_SESSION_ID,
) -> None:
    metadata = {}
    if project_id:
        metadata = {
            "project_id": project_id,
            "project_relationship_state": "directly_linked",
            "project_link_source": "proof_creation",
        }
    store.setdefault("extension_proof_sessions", {})[session_id] = {
        "id": session_id,
        "user_id": USER_ID,
        "student_id": USER_ID,
        "skill_evidence_id": str(uuid4()),
        "status": "completed",
        "website_url": "http://localhost:3000",
        "github_url": "https://github.com/veribridge/veribridge",
        "claimed_skills": ["React"],
        "proof_objective": objective,
        "metadata": metadata,
        "created_at": "2026-07-12T00:00:00+00:00",
        "updated_at": "2026-07-12T00:00:00+00:00",
    }
    workflow_id = str(uuid4())
    store.setdefault("workflow_analysis_results", {})[workflow_id] = {
        "id": workflow_id,
        "user_id": USER_ID,
        "proof_session_id": session_id,
        "target_website": "http://localhost:3000",
        "workflow_summary": "The user opened the interface, submitted a form, and a result appeared.",
        "recruiter_summary": "Interactive React workflow was observed.",
        "demonstrated_actions": ["Opened the form", "Submitted the form", "Viewed the result"],
        "observed_demonstration": {
            "steps": [
                {"timestamp_s": 24, "label": "Submitted the form"},
                {"timestamp_s": 31, "label": "Viewed the result"},
            ]
        },
        "supported_skills": ["React"],
        "weakly_supported_skills": [],
        "workflow_confidence": "high",
        "evidence_strength_score": 75,
        "created_at": "2026-07-12T00:10:00+00:00",
    }
    if retained:
        artifact_id = str(uuid4())
        store.setdefault("proof_artifacts", {})[artifact_id] = {
            "id": artifact_id,
            "owner_user_id": USER_ID,
            "proof_type": "website",
            "artifact_type": "website_replay_video",
            "proof_id": session_id,
            "project_id": project_id,
            "retained": True,
            "access_policy": "owner_only",
            "mime_type": "video/webm",
            "duration_seconds": 58.0,
            "storage_path": "private/not-serialized.webm",
        }


def test_real_session_directly_linked_to_veribridge_and_isolated_from_boston(
    mem_store: dict, pipeline_db: dict
) -> None:
    veribridge = _project(mem_store, title="VeriBridge", repo="veribridge/veribridge")
    boston = _project(mem_store, title="Boston Smart Accident Risk Routing", repo="demo/boston")
    _website_fixture(
        mem_store,
        project_id=veribridge["id"],
        objective="Demonstrate the VeriBridge Work Passport workflow",
    )

    veri_report = build_student_vbr_report(mem_store, pipeline_db, veribridge, USER_ID)
    boston_report = build_student_vbr_report(mem_store, pipeline_db, boston, USER_ID)
    assert veri_report["evidence_package"]["website_proofs_count"] == 1
    assert boston_report["evidence_package"]["website_proofs_count"] == 0
    assert not any(t["source_type"] == "Website Proof" for t in boston_report["evidence_traces"])

    passport = build_private_passport(mem_store, pipeline_db, USER_ID)
    by_title = {p["project_title"]: p for p in passport["projects"]}
    assert "Website Proof" in by_title["VeriBridge"]["evidence_sources"]
    assert "Website Proof" not in by_title["Boston Smart Accident Risk Routing"]["evidence_sources"]


def test_real_session_report_has_retained_replay_timestamp_and_analysis_actions(
    mem_store: dict, pipeline_db: dict
) -> None:
    project = _project(mem_store, title="VeriBridge", repo="veribridge/veribridge")
    _website_fixture(
        mem_store,
        project_id=project["id"],
        objective="Demonstrate the VeriBridge Work Passport workflow",
    )
    report = build_student_vbr_report(mem_store, pipeline_db, project, USER_ID)
    web = [c for c in report["claim_evidence_map"]["citations"] if c["proof_type"] == "Website Proof"]
    assert web
    assert any(c["video"] and c["video"]["recording_available"] for c in web)
    cited = next(c for c in web if c["video"] and c["video"]["recording_available"])
    assert cited["timestamp_start_label"] == "00:24"
    action_kinds = {a["kind"] for a in cited["actions"]}
    assert {"recorded_replay", "website_analysis"} <= action_kinds
    assert "localhost" in " ".join(cited["video"]["limitations"]).lower()
    assert "storage_path" not in str(report)
    assert "private/not-serialized" not in str(report)


def test_unlinked_real_session_is_suggested_to_veribridge_and_never_counted(
    mem_store: dict, pipeline_db: dict
) -> None:
    veribridge = _project(mem_store, title="VeriBridge", repo="veribridge/veribridge")
    boston = _project(mem_store, title="Boston Smart Accident Risk Routing", repo="demo/boston")
    _website_fixture(
        mem_store,
        project_id=None,
        objective="Demonstrate the VeriBridge Work Passport workflow",
    )
    passport = build_private_passport(mem_store, pipeline_db, USER_ID)
    suggestions = passport["unattached_proof_summary"]["suggestions"]
    website = next(s for s in suggestions if s["proof_type"] == "Website Proof")
    assert website["likely_project_title"] == "VeriBridge"
    assert website["proof_id"] == REAL_SESSION_ID
    assert website["likely_project_id"] == veribridge["id"]
    assert website["relationship_state"] == "vault_only"
    assert website["attachment_status"] == "Not attached to a VBR project"
    assert website["likely_project_ref_safe"].endswith(f"/{veribridge['id']}/report")
    assert not website["likely_project_ref_safe"].endswith(f"/{boston['id']}/report")
    for project in (veribridge, boston):
        report = build_student_vbr_report(mem_store, pipeline_db, project, USER_ID)
        assert report["evidence_package"]["website_proofs_count"] == 0


def test_cross_project_identity_conflict_excludes_boston_and_suggests_veribridge(
    mem_store: dict, pipeline_db: dict
) -> None:
    veribridge = _project(mem_store, title="VeriBridge", repo="veribridge/veribridge")
    boston = _project(
        mem_store,
        title="Boston Smart Accident Risk Routing",
        repo="demo/boston",
        website_session_ids=[REAL_SESSION_ID],
    )
    _website_fixture(
        mem_store,
        project_id=boston["id"],
        objective="Demonstrate the VeriBridge Work Passport workflow",
    )
    boston_report = build_student_vbr_report(mem_store, pipeline_db, boston, USER_ID)
    assert boston_report["evidence_package"]["website_proofs_count"] == 0
    assert boston_report["evidence_package"]["website_proofs_excluded_count"] == 1
    [identity] = boston_report["website_skill_evidence"]
    assert identity["project_identity_state"] == "mismatched"
    assert identity["counted_for_project"] is False

    passport = build_private_passport(mem_store, pipeline_db, USER_ID)
    suggestions = passport["unattached_proof_summary"]["suggestions"]
    assert any(s["likely_project_title"] == "VeriBridge" for s in suggestions)
    by_title = {p["project_title"]: p for p in passport["projects"]}
    assert "Website Proof" not in by_title["Boston Smart Accident Risk Routing"]["evidence_sources"]
    assert veribridge["id"] != boston["id"]


def test_student_confirmation_makes_vault_only_session_countable(
    mem_store: dict, pipeline_db: dict
) -> None:
    project = _project(mem_store, title="VeriBridge", repo="veribridge/veribridge")
    _website_fixture(mem_store, project_id=None, objective="Local application workflow")
    before = build_student_vbr_report(mem_store, pipeline_db, project, USER_ID)
    assert before["evidence_package"]["website_proofs_count"] == 0

    relationship = confirm_project_relationship(
        mem_store,
        user_id=USER_ID,
        proof_type="website",
        proof_id=REAL_SESSION_ID,
        project_id=project["id"],
    )
    assert relationship["state"] == "directly_linked"
    assert relationship["confirmed_by_user"] is True
    after = build_student_vbr_report(mem_store, pipeline_db, project, USER_ID)
    assert after["evidence_package"]["website_proofs_count"] == 1


def test_website_finalization_is_shared_idempotent_and_propagates_everywhere(
    mem_store: dict, pipeline_db: dict
) -> None:
    project = _project(
        mem_store,
        title="WikiTok Open-Source Pipeline Test",
        repo="demo/wikitok",
        claimed_skills=["React"],
    )
    _website_fixture(mem_store, project_id=None, objective="Demonstrate the WikiTok feed workflow")

    first = finalize_proof_evidence(
        mem_store,
        user_id=USER_ID,
        proof_type="website",
        proof_id=REAL_SESSION_ID,
        project_id=project["id"],
        pipeline_db=pipeline_db,
    )
    second = finalize_proof_evidence(
        mem_store,
        user_id=USER_ID,
        proof_type="website",
        proof_id=REAL_SESSION_ID,
        project_id=project["id"],
        pipeline_db=pipeline_db,
    )

    assert first["already_finalized"] is False
    assert second["already_finalized"] is True
    assert first["finalized_at"] == second["finalized_at"]
    assert first["claim_link_count"] == second["claim_link_count"] == 1
    assert len(mem_store["proof_project_relationships"]) == 1
    assert len(mem_store["vbr_claim_evidence_links"]) == 1
    session = mem_store["extension_proof_sessions"][REAL_SESSION_ID]
    assert session["metadata"]["canonical_finalization_service"] == "finalize_proof_evidence"
    assert session["metadata"]["canonical_finalized_project_id"] == project["id"]

    project_report = build_student_vbr_report(mem_store, pipeline_db, project, USER_ID)
    assert project_report["evidence_package"]["website_proofs_count"] == 1
    passport = build_private_passport(mem_store, pipeline_db, USER_ID)
    passport_project = next(row for row in passport["projects"] if row["project_id"] == project["id"])
    assert "Website Proof" in passport_project["evidence_sources"]
    skill_report = collect_skill_report(mem_store, pipeline_db, USER_ID, "React", synthesize=False)
    assert any(
        str(item.get("source_id")) == REAL_SESSION_ID
        for row in skill_report["projects"]
        for item in row["website_evidence"]
    )
    vault_items = collect_vault_items(mem_store, pipeline_db, USER_ID)
    website_items = [item for item in vault_items if item["proof_type"] == "Website Proof"]
    assert website_items
    assert all(project["id"] in item["attached_project_ids"] for item in website_items)


def test_website_finalization_rejects_foreign_session_and_project_without_leakage(
    mem_store: dict, pipeline_db: dict
) -> None:
    owned = _project(mem_store, title="Owned", repo="demo/owned")
    foreign_project = _project(mem_store, title="Foreign", repo="demo/foreign")
    foreign_project["user_id"] = "00000000-0000-0000-0000-000000000099"
    _website_fixture(mem_store, project_id=None, objective="Owned workflow")

    with pytest.raises(CanonicalEvidenceNotFoundError):
        finalize_proof_evidence(
            mem_store,
            user_id=USER_ID,
            proof_type="website",
            proof_id=REAL_SESSION_ID,
            project_id=foreign_project["id"],
            pipeline_db=pipeline_db,
        )
    with pytest.raises(CanonicalEvidenceNotFoundError):
        finalize_proof_evidence(
            mem_store,
            user_id="00000000-0000-0000-0000-000000000099",
            proof_type="website",
            proof_id=REAL_SESSION_ID,
            project_id=owned["id"],
            pipeline_db=pipeline_db,
        )
    assert not mem_store.get("proof_project_relationships")
    assert not mem_store.get("vbr_claim_evidence_links")


def test_confirmation_requires_a_retained_replay_without_partial_write(
    mem_store: dict,
) -> None:
    project = _project(mem_store, title="VeriBridge", repo="machackgo/veribridge-ai")
    _website_fixture(
        mem_store,
        project_id=None,
        objective="Demonstrate the VeriBridge workflow",
        retained=False,
    )

    with pytest.raises(CanonicalEvidencePreconditionError, match="retained"):
        confirm_project_relationship(
            mem_store,
            user_id=USER_ID,
            proof_type="website",
            proof_id=REAL_SESSION_ID,
            project_id=project["id"],
        )

    session = mem_store["extension_proof_sessions"][REAL_SESSION_ID]
    assert session["metadata"] == {}
    assert mem_store.get("proof_project_relationships", {}) == {}


def test_confirmation_requires_a_completed_session(mem_store: dict) -> None:
    project = _project(mem_store, title="VeriBridge", repo="machackgo/veribridge-ai")
    _website_fixture(
        mem_store,
        project_id=None,
        objective="Demonstrate the VeriBridge workflow",
    )
    mem_store["extension_proof_sessions"][REAL_SESSION_ID]["status"] = "processing"

    with pytest.raises(CanonicalEvidencePreconditionError, match="completed"):
        confirm_project_relationship(
            mem_store,
            user_id=USER_ID,
            proof_type="website",
            proof_id=REAL_SESSION_ID,
            project_id=project["id"],
        )


def test_confirmation_rejects_conflicting_direct_project(mem_store: dict) -> None:
    veribridge = _project(mem_store, title="VeriBridge", repo="machackgo/veribridge-ai")
    boston = _project(mem_store, title="Boston", repo="machackgo/boston")
    _website_fixture(
        mem_store,
        project_id=None,
        objective="Demonstrate the VeriBridge workflow",
    )
    mem_store["proof_project_relationships"] = {
        "existing": {
            "id": "existing",
            "owner_user_id": USER_ID,
            "proof_type": "website",
            "proof_id": REAL_SESSION_ID,
            "project_id": boston["id"],
            "relationship_state": "directly_linked",
        }
    }

    with pytest.raises(CanonicalEvidenceConflictError, match="another project"):
        confirm_project_relationship(
            mem_store,
            user_id=USER_ID,
            proof_type="website",
            proof_id=REAL_SESSION_ID,
            project_id=veribridge["id"],
        )

    assert mem_store["extension_proof_sessions"][REAL_SESSION_ID]["metadata"] == {}


def test_vault_row_transitions_in_place_and_repeat_is_idempotent(mem_store: dict) -> None:
    project = _project(mem_store, title="VeriBridge", repo="machackgo/veribridge-ai")
    _website_fixture(
        mem_store,
        project_id=None,
        objective="Demonstrate the VeriBridge workflow",
    )
    mem_store["proof_project_relationships"] = {
        "vault-row": {
            "id": "vault-row",
            "owner_user_id": USER_ID,
            "proof_type": "website",
            "proof_id": REAL_SESSION_ID,
            "project_id": None,
            "relationship_state": "vault_only",
            "match_method": "legacy",
            "confirmed_by_user": False,
        }
    }

    result = confirm_project_relationship(
        mem_store,
        user_id=USER_ID,
        proof_type="website",
        proof_id=REAL_SESSION_ID,
        project_id=project["id"],
    )
    assert result["state"] == "directly_linked"
    first_confirmed_at = mem_store["extension_proof_sessions"][REAL_SESSION_ID][
        "metadata"
    ]["project_link_confirmed_at"]
    first_provenance = dict(
        mem_store["proof_project_relationships"]["vault-row"]["provenance"]
    )

    repeated = confirm_project_relationship(
        mem_store,
        user_id=USER_ID,
        proof_type="website",
        proof_id=REAL_SESSION_ID,
        project_id=project["id"],
    )
    assert repeated["state"] == "directly_linked"

    [relationship] = list(mem_store["proof_project_relationships"].values())
    assert relationship["id"] == "vault-row"
    assert relationship["project_id"] == project["id"]
    assert relationship["relationship_state"] == "directly_linked"
    assert relationship["confirmed_by_user"] is True
    assert relationship["provenance"] == first_provenance
    assert relationship["provenance"]["previous_relationship_state"] == "vault_only"
    assert (
        mem_store["extension_proof_sessions"][REAL_SESSION_ID]["metadata"][
            "project_link_confirmed_at"
        ]
        == first_confirmed_at
    )


def test_migration_058_is_additive_idempotent_and_owner_safe() -> None:
    sql = MIGRATION_058.read_text().lower()
    assert "create table if not exists public.vbr_project_skill_claims" in sql
    assert "create table if not exists public.proof_project_relationships" in sql
    assert "create table if not exists public.vbr_claim_evidence_links" in sql
    assert "create index if not exists" in sql
    assert "drop table" not in sql
    assert "truncate " not in sql
    assert "delete from" not in sql
    assert "update public." not in sql
    assert "foreign key (project_id, owner_user_id)" in sql
    assert "references public.vbr_projects (id, user_id)" in sql
    assert "proof_project_relationships_one_direct_idx" in sql
    assert "where relationship_state = 'directly_linked'" in sql
    assert "relationship_state = 'vault_only' and project_id is null" in sql
    assert "enforce_vbr_claim_evidence_project_identity" in sql
    assert "not valid" in sql
    assert "to authenticated" in sql
    assert "for select" in sql
    assert "to service_role" in sql


def test_document_blocks_preserve_table_and_uncertain_visual_contracts() -> None:
    chain = {
        "project_id": "p1",
        "project_title": "VeriBridge",
        "attached": True,
        "github_evidence": [],
        "website_evidence": [],
        "defense_evidence": [],
        "video_evidence": [],
        "project_defense_inspection": [],
        "document_correlations": [
            {
                "source_id": "doc-1",
                "document_title": "Architecture report",
                "page_number": 7,
                "section_label": "Results",
                "figure_reference": "Table 2",
                "safe_snippet": "Latency | 120 ms",
                "table_cells": [["Metric", "Value"], ["Latency", "120 ms"]],
                "why_supported": "Reports the measured workflow result.",
                "corroborates": "Runtime behaviour",
                "document_retained": False,
            },
            {
                "source_id": "doc-2",
                "document_title": "Design appendix",
                "page_number": 9,
                "figure_reference": "Figure 4",
                "why_supported": "A visual region was cited.",
                "document_retained": False,
            },
        ],
    }
    report = {
        "skill": "React",
        "skill_slug": "react",
        "projects": [chain],
        "gaps": [],
    }
    evidence_map = build_skill_claim_evidence_map(report)
    blocks = [c["document_block"] for c in evidence_map["citations"]]
    table = next(b for b in blocks if b["block_type"] == "table")
    assert table["table_cells"][1] == ["Latency", "120 ms"]
    visual = next(b for b in blocks if b["block_type"] == "unknown_visual_region")
    assert "no chart/table values are inferred" in visual["model_limitation"]


def test_canonical_relationship_confirmation_is_owner_scoped(mem_store: dict) -> None:
    project = _project(mem_store, title="VeriBridge", repo="veribridge/veribridge")
    _website_fixture(mem_store, project_id=None, objective="Local application workflow")
    foreign = "00000000-0000-0000-0000-000000000099"
    try:
        confirm_project_relationship(
            mem_store,
            user_id=foreign,
            proof_type="website",
            proof_id=REAL_SESSION_ID,
            project_id=project["id"],
        )
    except LookupError:
        pass
    else:  # pragma: no cover - explicit assertion branch
        raise AssertionError("foreign user must not confirm another student's proof")
