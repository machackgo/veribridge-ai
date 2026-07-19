"""Regressions for project-scoped Website Proof selection.

Reproduces the observed manual-browser failure: a freshly finalized Website
Proof (Todo app) appeared on the Work Passport, but the passport's grouped
project card still linked to an OLDER duplicate-attempt project whose report
rendered only an unrelated older Website Proof (ReactPlay, 0:11 replay).

Canonical contract under test:
  * a proof finalized against project A appears in A's report — and never in
    project B's report;
  * a project's several attached Website Proofs render in a deterministic
    order regardless of storage iteration order;
  * the passport's grouped-card representative follows the newest canonical
    proof attachment, so the card's report link always lands on the report
    that actually contains the newly attached proof (passport and report
    resolve the same canonical proof/session);
  * each report's replay descriptor references only that project's own
    attached sessions (the replay/video can never come from another project).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.services.canonical_evidence_service import finalize_proof_evidence
from app.services.vbr_student_report import build_student_vbr_report
from app.services.vbr_work_passport_service import build_private_passport
from tests.test_vbr_project_defense import USER_ID

TODO_SESSION_ID = "edd33708-350b-4458-b94d-613d3c8e700a"
REACTPLAY_SESSION_ID = "1a68aac8-19ab-4c84-927c-fdfbdf06241f"

TODO_SITE = "https://no2ehi.github.io/simple-todo-app-react/"
REACTPLAY_SITE = "https://reactplay.io/"


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
    created_at: str = "2026-07-17T12:00:00+00:00",
    updated_at: str | None = None,
) -> dict:
    pid = str(uuid4())
    row = {
        "id": pid,
        "user_id": USER_ID,
        "title": title,
        "repo_url": f"https://github.com/{repo}",
        "repo_full_name": repo,
        "deployed_url": None,
        "status": "report_drafted",
        "metadata": {
            "claimed_skills": ["React"],
            "description": f"{title} project",
            "attached_proofs": {},
        },
        "created_at": created_at,
        "updated_at": updated_at or created_at,
    }
    store.setdefault("vbr_projects", {})[pid] = row
    return row


def _website_session(
    store: dict,
    *,
    session_id: str,
    site: str,
    created_at: str = "2026-07-17T12:00:00+00:00",
    analysis_created_at: str = "2026-07-17T12:10:00+00:00",
    duration_seconds: float = 58.0,
) -> None:
    """A completed, analyzed, retained (vault-only) Website Proof session."""
    store.setdefault("extension_proof_sessions", {})[session_id] = {
        "id": session_id,
        "user_id": USER_ID,
        "student_id": USER_ID,
        "skill_evidence_id": str(uuid4()),
        "status": "completed",
        "website_url": site,
        "github_url": None,
        "claimed_skills": ["React"],
        "proof_objective": f"Demonstrate the workflow on {site}",
        "metadata": {},
        "created_at": created_at,
        "updated_at": created_at,
    }
    workflow_id = str(uuid4())
    store.setdefault("workflow_analysis_results", {})[workflow_id] = {
        "id": workflow_id,
        "user_id": USER_ID,
        "proof_session_id": session_id,
        "target_website": site,
        "workflow_summary": f"The user exercised the app at {site}.",
        "recruiter_summary": "Interactive React workflow was observed.",
        "demonstrated_actions": ["Opened the app", "Used the main workflow"],
        "observed_demonstration": {"steps": [{"timestamp_s": 5, "label": "Used the app"}]},
        "supported_skills": ["React"],
        "weakly_supported_skills": [],
        "workflow_confidence": "high",
        "evidence_strength_score": 75,
        "created_at": analysis_created_at,
    }
    artifact_id = str(uuid4())
    store.setdefault("proof_artifacts", {})[artifact_id] = {
        "id": artifact_id,
        "owner_user_id": USER_ID,
        "proof_type": "website",
        "artifact_type": "website_replay_video",
        "proof_id": session_id,
        "project_id": None,
        "retained": True,
        "access_policy": "owner_only",
        "mime_type": "video/webm",
        "duration_seconds": duration_seconds,
        "storage_path": f"private/{session_id}.webm",
    }


def _finalize(store: dict, pipeline_db: dict, *, session_id: str, project_id: str) -> dict:
    return finalize_proof_evidence(
        store,
        user_id=USER_ID,
        proof_type="website",
        proof_id=session_id,
        project_id=project_id,
        pipeline_db=pipeline_db,
    )


def _report_targets(report: dict[str, Any]) -> list[str]:
    return [wp["target_website"] for wp in report.get("website_proofs") or []]


def _report_replay_paths(report: dict[str, Any]) -> list[str]:
    return [
        str(entry.get("website_replay_path") or "")
        for entry in report.get("website_skill_evidence") or []
        if entry.get("website_replay_available")
    ]


def test_finalized_proof_appears_only_in_its_own_project_report(
    mem_store: dict, pipeline_db: dict
) -> None:
    project_a = _project(mem_store, title="Todo Website Test", repo="no2ehi/simple-todo-app-react")
    project_b = _project(mem_store, title="SW Restart Recovery", repo="reactplay/react-play")
    _website_session(mem_store, session_id=REACTPLAY_SESSION_ID, site=REACTPLAY_SITE)
    _website_session(
        mem_store,
        session_id=TODO_SESSION_ID,
        site=TODO_SITE,
        created_at="2026-07-18T08:22:00+00:00",
        analysis_created_at="2026-07-18T08:26:00+00:00",
    )
    _finalize(mem_store, pipeline_db, session_id=REACTPLAY_SESSION_ID, project_id=project_b["id"])
    _finalize(mem_store, pipeline_db, session_id=TODO_SESSION_ID, project_id=project_a["id"])

    report_a = build_student_vbr_report(mem_store, pipeline_db, project_a, USER_ID)
    report_b = build_student_vbr_report(mem_store, pipeline_db, project_b, USER_ID)

    assert _report_targets(report_a) == [TODO_SITE]
    assert _report_targets(report_b) == [REACTPLAY_SITE]

    # The replay/video descriptor must belong to the project's OWN session —
    # never another project's recording.
    assert any(TODO_SESSION_ID in path for path in _report_replay_paths(report_a))
    assert all(REACTPLAY_SESSION_ID not in path for path in _report_replay_paths(report_a))
    assert any(REACTPLAY_SESSION_ID in path for path in _report_replay_paths(report_b))
    assert all(TODO_SESSION_ID not in path for path in _report_replay_paths(report_b))


def test_multiple_attached_proofs_render_deterministically(pipeline_db: dict) -> None:
    """Attachment order (analysis recency) decides rendering order — not the
    storage backend's iteration order."""
    orders = ([REACTPLAY_SESSION_ID, TODO_SESSION_ID], [TODO_SESSION_ID, REACTPLAY_SESSION_ID])
    rendered: list[list[str]] = []
    for insertion_order in orders:
        store: dict = {}
        project = _project(store, title="Multi Proof Project", repo="demo/multi")
        for sid in insertion_order:
            if sid == TODO_SESSION_ID:
                _website_session(
                    store,
                    session_id=sid,
                    site=TODO_SITE,
                    created_at="2026-07-18T08:22:00+00:00",
                    analysis_created_at="2026-07-18T08:26:00+00:00",
                )
            else:
                _website_session(store, session_id=sid, site=REACTPLAY_SITE)
        for sid in insertion_order:
            _finalize(store, pipeline_db, session_id=sid, project_id=project["id"])
        rendered.append(_report_targets(build_student_vbr_report(store, pipeline_db, project, USER_ID)))

    assert rendered[0] == rendered[1] == [REACTPLAY_SITE, TODO_SITE]


def test_newest_attachment_promotes_grouped_passport_representative(
    mem_store: dict, pipeline_db: dict
) -> None:
    """The observed bug: duplicate-attempt projects (same repo) collapse into one
    passport card; the card advertised the freshly attached proof (evidence
    union) while its report link stayed on the most-recently-UPDATED row — an
    older attempt whose report only contained an old unrelated proof."""
    older_attempt = _project(
        mem_store,
        title="ReactPlay Acceptance run2",
        repo="reactplay/react-play",
        created_at="2026-07-17T12:23:00+00:00",
    )
    newer_row = _project(
        mem_store,
        title="SW Restart Recovery",
        repo="reactplay/react-play",
        created_at="2026-07-18T05:32:00+00:00",
    )
    _website_session(mem_store, session_id=REACTPLAY_SESSION_ID, site=REACTPLAY_SITE)
    # The old proof is attached to the newer-updated row (mirrors production).
    _finalize(mem_store, pipeline_db, session_id=REACTPLAY_SESSION_ID, project_id=newer_row["id"])
    # Freeze the old attachment's stamps in the past so only project-row recency
    # would (wrongly) still elect ``newer_row`` as representative.
    for relation in mem_store["proof_project_relationships"].values():
        relation["created_at"] = "2026-07-18T05:33:00+00:00"
        relation["updated_at"] = "2026-07-18T05:33:00+00:00"

    # The fresh Todo proof is finalized against the OLDER project row.
    _website_session(
        mem_store,
        session_id=TODO_SESSION_ID,
        site=TODO_SITE,
        created_at="2026-07-18T08:22:00+00:00",
        analysis_created_at="2026-07-18T08:26:00+00:00",
    )
    _finalize(mem_store, pipeline_db, session_id=TODO_SESSION_ID, project_id=older_attempt["id"])

    passport = build_private_passport(mem_store, pipeline_db, USER_ID)
    grouped_cards = [
        card for card in passport["projects"] if card.get("repo_full_name") == "reactplay/react-play"
    ]
    assert len(grouped_cards) == 1
    card = grouped_cards[0]
    assert card["attempt_count"] == 2
    assert "Website Proof" in card["evidence_sources"]

    # The card (and therefore every report link on it) must resolve to the
    # attempt that carries the NEWEST canonical attachment.
    assert card["project_id"] == older_attempt["id"]

    # Passport → report consistency: the linked report contains the exact
    # freshly attached proof/session the card advertises.
    linked_report = build_student_vbr_report(
        mem_store, pipeline_db, mem_store["vbr_projects"][card["project_id"]], USER_ID
    )
    assert TODO_SITE in _report_targets(linked_report)
    assert any(TODO_SESSION_ID in path for path in _report_replay_paths(linked_report))

    # The unrelated older proof stays in ITS project's report only.
    other_report = build_student_vbr_report(mem_store, pipeline_db, newer_row, USER_ID)
    assert _report_targets(other_report) == [REACTPLAY_SITE]
    assert all(TODO_SESSION_ID not in path for path in _report_replay_paths(other_report))


def test_grouping_still_prefers_published_representative(
    mem_store: dict, pipeline_db: dict
) -> None:
    """A published (token-holding) attempt stays the grouped representative even
    when a sibling attempt received newer evidence — publishing is an explicit
    owner act and the card must keep advertising the published report."""
    published = _project(
        mem_store,
        title="Published attempt",
        repo="demo/grouped",
        created_at="2026-07-16T00:00:00+00:00",
    )
    published["public_report_token"] = "tok-published"
    sibling = _project(
        mem_store,
        title="Sibling attempt",
        repo="demo/grouped",
        created_at="2026-07-17T00:00:00+00:00",
    )
    _website_session(
        mem_store,
        session_id=TODO_SESSION_ID,
        site=TODO_SITE,
        created_at="2026-07-18T08:22:00+00:00",
        analysis_created_at="2026-07-18T08:26:00+00:00",
    )
    _finalize(mem_store, pipeline_db, session_id=TODO_SESSION_ID, project_id=sibling["id"])

    passport = build_private_passport(mem_store, pipeline_db, USER_ID)
    card = next(c for c in passport["projects"] if c.get("repo_full_name") == "demo/grouped")
    assert card["project_id"] == published["id"]
