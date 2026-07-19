"""Project Defense canonical evidence resolution regressions.

Reproduces the observed manual-browser failure on a fresh project: the
student attached a GitHub Proof, a Website Proof, and a Document Proof, yet
Project Defense displayed a GitHub proof from an UNRELATED repository
(attached to the project by a wrong finalization), reported the Website Proof
as missing (its canonical edge lived only in ``proof_project_relationships``
on a duplicate project row, which the defense read path never consulted), and
generated a stale "You have not attached a live/website demo" question.

Canonical contract under test (see ``canonical_project_evidence``):
  * Project Defense resolves ONLY evidence explicitly attached to the exact
    user + logical project (including its duplicate rows) — never another
    project's proof, never a skill-shared or account-latest proof.
  * A GitHub proof whose repository contradicts the project's own declared
    repository is rejected at the write boundary and excluded at read time.
  * Website Proof edges written at session create/finalize (relationship
    rows) surface in the defense context and question generation.
  * Stored questions regenerate while the session is unstarted whenever the
    canonical evidence package changes; started sessions keep their history.
  * Selection among several valid proofs is deterministic (never dependent on
    storage iteration order).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.services.canonical_evidence_service import (
    CanonicalEvidenceNotFoundError,
    CanonicalEvidencePreconditionError,
    finalize_proof_evidence,
)
from app.services.vbr_project_defense import (
    attach_proofs_to_project,
    build_defense_question_specs,
    build_project_defense_context,
    generate_defense_questions,
    merge_owned_project,
)
from app.services.vbr_student_report import build_student_vbr_report
from app.services.vbr_work_passport_service import build_private_passport
from tests.test_vbr_project_defense import USER_ID

OTHER_USER_ID = "00000000-0000-4000-8000-00000000beef"

STICKY_REPO = "dennisivy/Sticky-Notes-React"
STICKY_SITE = "https://sticky-fcc.vercel.app/"
WIKITOK_REPO = "IsaacGemal/wikitok"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def pipeline_db() -> dict:
    return {}


def _now(offset_minutes: int = 0) -> str:
    return f"2026-07-18T10:{offset_minutes:02d}:00+00:00"


def _project(
    store: dict,
    *,
    title: str,
    repo: str,
    user_id: str = USER_ID,
    created_at: str = "2026-07-18T09:56:04+00:00",
    metadata: dict | None = None,
) -> dict:
    pid = str(uuid4())
    row = {
        "id": pid,
        "user_id": user_id,
        "title": title,
        "repo_url": f"https://github.com/{repo}",
        "repo_full_name": repo,
        "deployed_url": None,
        "head_sha": None,
        "status": "draft",
        "metadata": metadata
        if metadata is not None
        else {"description": f"{title} project", "claimed_skills": [], "attached_proofs": {}},
        "created_at": created_at,
        "updated_at": created_at,
    }
    store.setdefault("vbr_projects", {})[pid] = row
    return row


def _github_proof(
    store: dict,
    *,
    repo: str,
    user_id: str = USER_ID,
    status: str = "analyzed",
    created_at: str = "2026-07-18T09:54:00+00:00",
) -> str:
    proof_id = str(uuid4())
    owner, name = repo.split("/", 1)
    store.setdefault("github_proof_submissions", {})[proof_id] = {
        "id": proof_id,
        "user_id": user_id,
        "proof_session_id": None,
        "repo_url": f"https://github.com/{repo}",
        "repo_owner": owner,
        "repo_name": name,
        "default_branch": "main",
        "visibility": "public",
        "status": status,
        "submitted_skill_claims": ["React"],
        "detected_skills": ["React"],
        "repo_metadata": {},
        "analysis_summary": f"Repo {repo} demonstrates frontend work.",
        "evidence_strength": "partial",
        "confidence_score": 60,
        "risk_flags": [],
        "missing_evidence": [],
        "public_safe_summary": f"GitHub proof for {repo}.",
        "analysis_snapshot": {},
        "last_analyzed_at": created_at,
        "created_at": created_at,
        "updated_at": created_at,
    }
    return proof_id


def _website_session(
    store: dict,
    *,
    site: str,
    user_id: str = USER_ID,
    session_id: str | None = None,
    status: str = "completed",
    analyzed: bool = True,
    created_at: str = "2026-07-18T09:58:32+00:00",
    analysis_created_at: str = "2026-07-18T10:03:51+00:00",
) -> str:
    sid = session_id or str(uuid4())
    store.setdefault("extension_proof_sessions", {})[sid] = {
        "id": sid,
        "user_id": user_id,
        "student_id": user_id,
        "skill_evidence_id": str(uuid4()),
        "status": status,
        "website_url": site,
        "github_url": None,
        "claimed_skills": ["React"],
        "proof_objective": f"Demonstrate the workflow on {site}",
        "metadata": {},
        "created_at": created_at,
        "updated_at": created_at,
    }
    if analyzed:
        workflow_id = str(uuid4())
        store.setdefault("workflow_analysis_results", {})[workflow_id] = {
            "id": workflow_id,
            "user_id": user_id,
            "proof_session_id": sid,
            "target_website": site,
            "workflow_summary": f"The user exercised the app at {site}.",
            "recruiter_summary": "Interactive workflow was observed.",
            "demonstrated_actions": ["Opened the app"],
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
        "owner_user_id": user_id,
        "proof_type": "website",
        "artifact_type": "website_replay_video",
        "proof_id": sid,
        "project_id": None,
        "retained": True,
        "access_policy": "owner_only",
        "mime_type": "video/webm",
        "duration_seconds": 58.0,
        "storage_path": f"private/{sid}.webm",
        "created_at": created_at,
    }
    return sid


def _document(store: dict, *, title: str, user_id: str = USER_ID) -> str:
    doc_id = str(uuid4())
    now = _now()
    store.setdefault("optional_evidence_submissions", {})[doc_id] = {
        "id": doc_id,
        "user_id": user_id,
        "proof_session_id": None,
        "source_type": "document",
        "status": "analyzed",
        "analysis_json": {"title": title},
        "evidence_objects": [],
        "file_path": None,
        "created_at": now,
        "updated_at": now,
    }
    return doc_id


def _relationship(
    store: dict,
    *,
    proof_type: str,
    proof_id: str,
    project_id: str,
    user_id: str = USER_ID,
    created_at: str = "2026-07-18T09:58:32+00:00",
) -> None:
    """The canonical edge exactly as the session-create/finalize write paths persist it."""
    rel_id = str(uuid4())
    store.setdefault("proof_project_relationships", {})[rel_id] = {
        "id": rel_id,
        "owner_user_id": user_id,
        "proof_type": proof_type,
        "proof_id": proof_id,
        "project_id": project_id,
        "relationship_state": "directly_linked",
        "match_method": "user_confirmation",
        "confirmed_by_user": True,
        "provenance": {"source": "extension_proof_session_create"},
        "created_at": created_at,
        "updated_at": created_at,
    }


def _evidence(store: dict, project: dict) -> dict:
    return build_project_defense_context(store, project, USER_ID)["evidence"]


def _question_texts(store: dict, project: dict) -> list[str]:
    context = build_project_defense_context(store, project, USER_ID)
    return [str(q.get("question_text") or "") for q in context["questions"]]


class _GitHubAttach:
    website_proof_session_ids: list[str] = []
    skill_pipeline_ids: list[str] = []
    document_evidence_ids: list[str] = []

    def __init__(self, github_proof_id: str) -> None:
        self.github_proof_id = github_proof_id


# ── 1–3. Project- and user-scoped resolution ────────────────────────────────


def test_website_proof_resolves_only_for_its_own_project(
    mem_store: dict, pipeline_db: dict
) -> None:
    project_a = _project(mem_store, title="Sticky Notes", repo=STICKY_REPO)
    project_b = _project(mem_store, title="Todo App", repo="no2ehi/simple-todo-app-react")
    session_a = _website_session(mem_store, site=STICKY_SITE)
    session_b = _website_session(
        mem_store,
        site="https://no2ehi.github.io/simple-todo-app-react/",
        created_at="2026-07-18T09:02:00+00:00",
        analysis_created_at="2026-07-18T09:06:00+00:00",
    )
    finalize_proof_evidence(
        mem_store, user_id=USER_ID, proof_type="website", proof_id=session_a,
        project_id=project_a["id"], pipeline_db=pipeline_db,
    )
    finalize_proof_evidence(
        mem_store, user_id=USER_ID, proof_type="website", proof_id=session_b,
        project_id=project_b["id"], pipeline_db=pipeline_db,
    )

    evidence_a = _evidence(mem_store, project_a)
    evidence_b = _evidence(mem_store, project_b)
    assert evidence_a["website_proof"]["attached"] is True
    assert evidence_a["website_proof"]["label"] == "https://sticky-fcc.vercel.app"
    assert "todo" not in evidence_a["website_proof"]["label"]
    assert evidence_b["website_proof"]["label"] == "https://no2ehi.github.io"


def test_github_proof_never_leaks_across_projects(mem_store: dict, pipeline_db: dict) -> None:
    project_a = _project(mem_store, title="Sticky Notes", repo=STICKY_REPO)
    project_b = _project(mem_store, title="Wikitok", repo=WIKITOK_REPO)
    proof_a = _github_proof(mem_store, repo=STICKY_REPO)
    proof_b = _github_proof(mem_store, repo=WIKITOK_REPO)
    finalize_proof_evidence(
        mem_store, user_id=USER_ID, proof_type="github", proof_id=proof_a,
        project_id=project_a["id"], pipeline_db=pipeline_db,
    )
    finalize_proof_evidence(
        mem_store, user_id=USER_ID, proof_type="github", proof_id=proof_b,
        project_id=project_b["id"], pipeline_db=pipeline_db,
    )

    assert _evidence(mem_store, project_a)["github_proof"]["label"] == STICKY_REPO
    assert _evidence(mem_store, project_b)["github_proof"]["label"] == WIKITOK_REPO


def test_user_cannot_resolve_or_attach_another_users_proof(
    mem_store: dict, pipeline_db: dict
) -> None:
    my_project = _project(mem_store, title="Mine", repo=STICKY_REPO)
    their_project = _project(mem_store, title="Theirs", repo=STICKY_REPO, user_id=OTHER_USER_ID)
    their_session = _website_session(mem_store, site=STICKY_SITE, user_id=OTHER_USER_ID)
    # Their canonical edge to THEIR project must never surface for me, even
    # though repo/title/site all coincide.
    _relationship(
        mem_store, proof_type="website", proof_id=their_session,
        project_id=their_project["id"], user_id=OTHER_USER_ID,
    )
    assert _evidence(mem_store, my_project)["website_proof"]["attached"] is False

    # Finalizing THEIR proof against MY project fails ownership, and vice versa.
    with pytest.raises(CanonicalEvidenceNotFoundError):
        finalize_proof_evidence(
            mem_store, user_id=USER_ID, proof_type="website", proof_id=their_session,
            project_id=my_project["id"], pipeline_db=pipeline_db,
        )
    with pytest.raises(CanonicalEvidenceNotFoundError):
        finalize_proof_evidence(
            mem_store, user_id=OTHER_USER_ID, proof_type="website", proof_id=their_session,
            project_id=my_project["id"], pipeline_db=pipeline_db,
        )


# ── 5. Stale-question invalidation ──────────────────────────────────────────


def test_website_attached_after_questions_regenerates_missing_evidence_question(
    mem_store: dict, pipeline_db: dict
) -> None:
    project = _project(mem_store, title="Sticky Notes", repo=STICKY_REPO)
    generate_defense_questions(mem_store, merge_owned_project(mem_store, USER_ID, project))
    assert any("live/website demo" in q for q in _question_texts(mem_store, project))

    session = _website_session(mem_store, site=STICKY_SITE)
    finalize_proof_evidence(
        mem_store, user_id=USER_ID, proof_type="website", proof_id=session,
        project_id=project["id"], pipeline_db=pipeline_db,
    )

    questions = _question_texts(mem_store, project)
    assert questions, "questions must survive regeneration"
    assert not any("live/website demo" in q for q in questions)
    assert any("sticky-fcc.vercel.app" in q for q in questions)


def test_started_session_keeps_its_questions_as_history(
    mem_store: dict, pipeline_db: dict
) -> None:
    project = _project(mem_store, title="Sticky Notes", repo=STICKY_REPO)
    session_id, _ = generate_defense_questions(
        mem_store, merge_owned_project(mem_store, USER_ID, project)
    )
    mem_store["vbr_verification_sessions"][session_id]["status"] = "recording"

    web_session = _website_session(mem_store, site=STICKY_SITE)
    finalize_proof_evidence(
        mem_store, user_id=USER_ID, proof_type="website", proof_id=web_session,
        project_id=project["id"], pipeline_db=pipeline_db,
    )

    # A started recording is a historical record — its asked questions are
    # never rewritten (a fresh attempt gets fresh questions instead).
    assert any("live/website demo" in q for q in _question_texts(mem_store, project))


# ── 6. Incomplete / unanalyzed sessions ─────────────────────────────────────


def test_incomplete_website_session_is_not_treated_as_attached(mem_store: dict) -> None:
    project = _project(mem_store, title="Sticky Notes", repo=STICKY_REPO)
    session = _website_session(mem_store, site=STICKY_SITE, status="recording", analyzed=False)
    # The session-create write path records the canonical edge immediately —
    # an abandoned/in-flight recording must still not count as evidence.
    _relationship(mem_store, proof_type="website", proof_id=session, project_id=project["id"])

    evidence = _evidence(mem_store, project)
    assert evidence["website_proof"]["attached"] is False
    specs = build_defense_question_specs(merge_owned_project(mem_store, USER_ID, project))
    assert any("live/website demo" in s["question_text"] for s in specs)


def test_completed_session_without_analysis_surfaces_as_pending(mem_store: dict) -> None:
    project = _project(mem_store, title="Sticky Notes", repo=STICKY_REPO)
    session = _website_session(mem_store, site=STICKY_SITE, analyzed=False)
    _relationship(mem_store, proof_type="website", proof_id=session, project_id=project["id"])

    context = build_project_defense_context(mem_store, project, USER_ID)
    websites = context["safe_metadata"]["attached_proofs"]["website_proofs"]
    assert [w.get("status") for w in websites] == ["analysis_pending"]
    assert context["evidence"]["website_proof"]["attached"] is True


# ── 7 & 10. Deterministic selection ─────────────────────────────────────────


def test_multiple_website_attempts_render_deterministically(pipeline_db: dict) -> None:
    rendered: list[str] = []
    for flip in (False, True):
        store: dict = {}
        project = _project(store, title="Sticky Notes", repo=STICKY_REPO)
        sessions = [
            ("https://sticky-fcc.vercel.app/", "2026-07-18T09:00:00+00:00"),
            ("https://sticky-two.vercel.app/", "2026-07-18T09:30:00+00:00"),
        ]
        if flip:
            sessions.reverse()
        for site, created in sessions:
            sid = _website_session(
                store, site=site, created_at=created,
                analysis_created_at=created.replace("T09:", "T10:"),
            )
            finalize_proof_evidence(
                store, user_id=USER_ID, proof_type="website", proof_id=sid,
                project_id=project["id"], pipeline_db=pipeline_db,
            )
        rendered.append(_evidence(store, project)["website_proof"]["label"])
    assert rendered[0] == rendered[1]


def test_github_selection_prefers_analyzed_proof_deterministically(mem_store: dict) -> None:
    project = _project(mem_store, title="Sticky Notes", repo=STICKY_REPO)
    analyzed = _github_proof(mem_store, repo=STICKY_REPO, status="analyzed")
    submitted = _github_proof(mem_store, repo=STICKY_REPO, status="submitted")
    # Newest edge first would pick the submitted proof; the deterministic rule
    # prefers the analysis-complete one.
    _relationship(
        mem_store, proof_type="github", proof_id=analyzed,
        project_id=project["id"], created_at="2026-07-18T09:00:00+00:00",
    )
    _relationship(
        mem_store, proof_type="github", proof_id=submitted,
        project_id=project["id"], created_at="2026-07-18T09:30:00+00:00",
    )

    metadata = merge_owned_project(mem_store, USER_ID, project)["metadata"]
    assert metadata["attached_proofs"]["github_proof"]["status"] == "analyzed"


# ── 8. Documents stay linked via canonical rows ─────────────────────────────


def test_document_canonical_relationship_surfaces_in_context(mem_store: dict) -> None:
    project = _project(mem_store, title="Sticky Notes", repo=STICKY_REPO)
    doc = _document(mem_store, title="Sticky Notes Application Technical Overview")
    _relationship(mem_store, proof_type="document", proof_id=doc, project_id=project["id"])

    evidence = _evidence(mem_store, project)
    assert evidence["documents"]["attached"] is True
    assert "Sticky Notes Application Technical Overview" in evidence["documents"]["label"]


# ── Write-path guard ─────────────────────────────────────────────────────────


def test_finalize_rejects_github_proof_for_a_different_repository(
    mem_store: dict, pipeline_db: dict
) -> None:
    project = _project(mem_store, title="Sticky Notes", repo=STICKY_REPO)
    wikitok = _github_proof(mem_store, repo=WIKITOK_REPO)
    with pytest.raises(CanonicalEvidencePreconditionError):
        finalize_proof_evidence(
            mem_store, user_id=USER_ID, proof_type="github", proof_id=wikitok,
            project_id=project["id"], pipeline_db=pipeline_db,
        )
    # And the defense attach flow enforces the same rule.
    with pytest.raises(ValueError, match="github_proof_repo_mismatch"):
        attach_proofs_to_project(mem_store, pipeline_db, USER_ID, project, _GitHubAttach(wikitok))


# ── 9 & 12. The exact observed bug + report/passport parity ─────────────────


def _seed_observed_bug(store: dict) -> tuple[dict, dict, str, str]:
    """Two duplicate rows of one logical project, evidence split across them,
    plus a legacy contradictory GitHub attachment on the row being defended."""
    wikitok_proof = _github_proof(store, repo=WIKITOK_REPO, created_at="2026-07-14T04:04:00+00:00")
    defended = _project(
        store,
        title="Sticky Notes Full Proof Test 71826",
        repo=STICKY_REPO,
        metadata={
            "attached_proofs": {
                # Legacy wrong attachment: an unrelated repository's summary.
                "github_proof": {
                    "github_proof_id": wikitok_proof,
                    "repo_url": f"https://github.com/{WIKITOK_REPO}",
                    "repo_owner": "IsaacGemal",
                    "repo_name": "wikitok",
                    "status": "analyzed",
                    "detected_skills": ["React"],
                    "public_safe_summary": "GitHub proof for IsaacGemal/wikitok.",
                }
            }
        },
    )
    _relationship(
        store, proof_type="github", proof_id=wikitok_proof, project_id=defended["id"],
        created_at="2026-07-18T09:56:04+00:00",
    )
    duplicate = _project(
        store,
        title="Sticky Notes Full Proof Test 71826",
        repo=STICKY_REPO,
        created_at="2026-07-18T09:56:23+00:00",
    )
    session = _website_session(store, site=STICKY_SITE)
    _relationship(store, proof_type="website", proof_id=session, project_id=duplicate["id"])
    doc = _document(store, title="Sticky Notes Application Technical Overview")
    _relationship(
        store, proof_type="document", proof_id=doc, project_id=duplicate["id"],
        created_at="2026-07-18T10:05:32+00:00",
    )
    return defended, duplicate, session, doc


def test_observed_bug_defense_resolves_sticky_notes_never_wikitok(mem_store: dict) -> None:
    defended, _duplicate, _session, _doc = _seed_observed_bug(mem_store)

    context = build_project_defense_context(mem_store, defended, USER_ID)
    evidence = context["evidence"]

    # Website + document attached via canonical rows on the duplicate row.
    assert evidence["website_proof"]["attached"] is True
    assert evidence["website_proof"]["label"] == "https://sticky-fcc.vercel.app"
    assert evidence["documents"]["attached"] is True

    # The contradictory wikitok attachment must not leak anywhere.
    assert "wikitok" not in (evidence["github_proof"]["label"] or "")
    metadata_github = context["safe_metadata"]["attached_proofs"].get("github_proof")
    assert metadata_github is None or "wikitok" not in str(metadata_github.get("repo_url") or "")


def test_observed_bug_questions_ground_in_sticky_evidence(mem_store: dict) -> None:
    defended, _duplicate, _session, _doc = _seed_observed_bug(mem_store)
    _sid, questions = generate_defense_questions(
        mem_store, merge_owned_project(mem_store, USER_ID, defended)
    )
    texts = [str(q["question_text"]) for q in questions]
    assert not any("live/website demo" in t for t in texts)
    assert not any("wikitok" in t.lower() for t in texts)
    assert any("sticky-fcc.vercel.app" in t for t in texts)
    assert any("Sticky Notes Application Technical Overview" in t for t in texts)


def test_observed_bug_report_and_defense_resolve_same_package(
    mem_store: dict, pipeline_db: dict
) -> None:
    defended, _duplicate, session, _doc = _seed_observed_bug(mem_store)

    report = build_student_vbr_report(mem_store, pipeline_db, defended, USER_ID)
    report_sites = [wp["target_website"] for wp in report.get("website_proofs") or []]
    assert report_sites == [STICKY_SITE]
    assert session in str(report.get("website_skill_evidence") or "")
    github = report.get("github_proof")
    assert github is None or "wikitok" not in str(github.get("repo_url") or "")
    doc_titles = [d.get("title") for d in report.get("documents") or []]
    assert "Sticky Notes Application Technical Overview" in doc_titles

    # After the student attaches the CORRECT GitHub proof, every surface
    # resolves it — and still never wikitok.
    sticky_proof = _github_proof(mem_store, repo=STICKY_REPO)
    finalize_proof_evidence(
        mem_store, user_id=USER_ID, proof_type="github", proof_id=sticky_proof,
        project_id=defended["id"], pipeline_db=pipeline_db,
    )
    evidence = _evidence(mem_store, defended)
    assert evidence["github_proof"]["label"] == STICKY_REPO
    report_after = build_student_vbr_report(mem_store, pipeline_db, defended, USER_ID)
    assert str((report_after.get("github_proof") or {}).get("repo_url") or "").endswith(STICKY_REPO)


def test_observed_bug_passport_attachment_overview_excludes_contradictory_github(
    mem_store: dict, pipeline_db: dict
) -> None:
    """The vault attachment overview must not present the contradictory GitHub
    proof as 'Attached' to the Sticky Notes project (legacy wrong edge)."""
    _seed_observed_bug(mem_store)
    passport = build_private_passport(mem_store, pipeline_db, USER_ID)
    overview = passport.get("attachment_overview") or {}
    for entry in overview.get("attached") or []:
        if "wikitok" in str(entry.get("display_title") or "").lower():
            assert not any(
                "Sticky Notes" in title for title in entry.get("project_titles") or []
            ), "contradictory wikitok proof must not show as attached to Sticky Notes"
