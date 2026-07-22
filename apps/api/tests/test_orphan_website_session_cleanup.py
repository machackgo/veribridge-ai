"""Regression tests: abandoned ("orphan") website proof sessions.

Website Proof creation writes its project edge (session ``metadata.project_id``
plus a ``proof_project_relationships`` row, both ``directly_linked``) BEFORE any
recording exists.  A session abandoned mid-recording therefore used to stay
project-linked forever, and its creation-time ``skill_evidence`` stub kept
surfacing as an evidence profile.

Covers (all dict-mode, no network):
  ✓ canonical_website_session_ids admits ONLY usable (completed) sessions —
    an abandoned recording session on the same project is excluded, no
    duplicates, deterministic single id
  ✓ a relationship-edge whose session row is visibly non-usable is excluded;
    an edge whose session row no longer exists keeps legacy behavior
  ✓ report _canonical_website_proofs_for_project surfaces exactly one website
    proof (the completed one) even if the orphan somehow has an analysis row
  ✓ defense merge_group_metadata_with_canonical attaches exactly one website
    proof summary
  ✓ ProofSessionCleanupService dry_run/backup cover proof_project_relationships
    and the session's skill_evidence stub, without mutating the db
  ✓ archive_session detaches: session expired + metadata edge moved to
    detached_project_id + relationship rows downgraded to vault_only with a
    provenance trail; nothing deleted; resolver no longer returns the session
  ✓ delete removes relationship rows and the skill_evidence stub — no dangling
    rows — and the resolver output for the project is unchanged
  ✓ SkillEvidenceProfileService does not surface the orphan's pending stub
    (abandoned or archived), while completed / in-flight sessions keep theirs
"""

from __future__ import annotations

import copy
from typing import Any

from app.services.canonical_project_evidence import (
    USABLE_WEBSITE_SESSION_STATUSES,
    canonical_website_session_ids,
)
from app.services.proof_session_cleanup_service import (
    ProofSessionCleanupService,
    _T_RELATIONSHIPS,
    _T_SESSIONS,
    _T_SKILL_EVIDENCE,
)
from app.services.skill_evidence_profile_service import SkillEvidenceProfileService
from app.services.vbr_project_defense import merge_group_metadata_with_canonical
from app.services.vbr_student_report import _canonical_website_proofs_for_project

USER = "user-148"
PROJECT = "11111111-1111-1111-1111-111111111111"
COMPLETED = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ORPHAN = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
SEV_COMPLETED = "sev-completed"
SEV_ORPHAN = "sev-orphan"


def _make_db() -> dict[str, Any]:
    """One project, one completed+analyzed session, one abandoned session.

    Mirrors the production orphan shape: both sessions were created with an
    explicit project_id, so both carry directly_linked metadata AND a
    directly_linked proof_project_relationships row from create time.
    """
    return {
        "vbr_projects": {
            PROJECT: {
                "id": PROJECT,
                "user_id": USER,
                "title": "WEB-ANALYTICS",
                "status": "questions_ready",
                "metadata": {
                    "claimed_skills": ["Web Analytics", "Data Visualization"],
                    "attached_proofs": {},
                },
            },
        },
        _T_SESSIONS: {
            ORPHAN: {
                "id": ORPHAN,
                "user_id": USER,
                "status": "recording",
                "skill_evidence_id": SEV_ORPHAN,
                "website_url": "https://demo.umami.is",
                "created_at": "2026-07-21T15:20:00+00:00",
                "metadata": {
                    "project_id": PROJECT,
                    "project_relationship_state": "directly_linked",
                    "project_link_source": "proof_creation",
                },
                "proof_data": {},
            },
            COMPLETED: {
                "id": COMPLETED,
                "user_id": USER,
                "status": "completed",
                "skill_evidence_id": SEV_COMPLETED,
                "website_url": "https://plausible.io/plausible.io",
                "created_at": "2026-07-21T15:36:00+00:00",
                "metadata": {
                    "project_id": PROJECT,
                    "project_relationship_state": "directly_linked",
                    "project_link_source": "user_confirmation",
                },
            },
        },
        _T_RELATIONSHIPS: {
            "rel-orphan": {
                "id": "rel-orphan",
                "owner_user_id": USER,
                "proof_type": "website",
                "proof_id": ORPHAN,
                "project_id": PROJECT,
                "relationship_state": "directly_linked",
                "match_method": "explicit_project_id",
                "confirmed_by_user": True,
                "provenance": {"source": "extension_proof_session_create"},
                "created_at": "2026-07-21T15:20:01+00:00",
            },
            "rel-completed": {
                "id": "rel-completed",
                "owner_user_id": USER,
                "proof_type": "website",
                "proof_id": COMPLETED,
                "project_id": PROJECT,
                "relationship_state": "directly_linked",
                "match_method": "user_confirmation",
                "confirmed_by_user": True,
                "provenance": {"source": "extension_proof_session_create"},
                "created_at": "2026-07-21T15:36:01+00:00",
            },
        },
        "workflow_analysis_results": {
            "wf-completed": {
                "id": "wf-completed",
                "user_id": USER,
                "proof_session_id": COMPLETED,
                "target_website": "https://plausible.io/plausible.io",
                "evidence_strength_score": 57,
                "workflow_confidence": "moderate",
                "supported_skills": ["Web Analytics"],
                "created_at": "2026-07-21T17:53:00+00:00",
            },
        },
        _T_SKILL_EVIDENCE: {
            SEV_ORPHAN: {
                "id": SEV_ORPHAN,
                "user_id": USER,
                "evidence_type": "private website (extension proof)",
                "evidence_url": "https://demo.umami.is",
                "skill_name": "Web Analytics",
                "verification_status": "pending_review",
                "metadata": {"proof_kind": "extension_proof"},
                "created_at": "2026-07-21T15:20:00+00:00",
            },
            SEV_COMPLETED: {
                "id": SEV_COMPLETED,
                "user_id": USER,
                "evidence_type": "private website (extension proof)",
                "evidence_url": "https://plausible.io/plausible.io",
                "skill_name": "Web Analytics",
                "verification_status": "pending_review",
                "metadata": {"proof_kind": "extension_proof", "session_id": COMPLETED},
                "created_at": "2026-07-21T15:36:00+00:00",
            },
        },
    }


# ── Shared resolver gate ───────────────────────────────────────────────────────

class TestResolverUsabilityGate:
    def test_only_completed_session_admitted(self) -> None:
        db = _make_db()
        ids = canonical_website_session_ids(db, user_id=USER, project_ids=[PROJECT])
        assert ids == [COMPLETED]

    def test_no_duplicate_ids_from_metadata_and_edge(self) -> None:
        db = _make_db()
        ids = canonical_website_session_ids(db, user_id=USER, project_ids=[PROJECT])
        assert len(ids) == len(set(ids)) == 1

    def test_edge_only_orphan_excluded_when_session_not_usable(self) -> None:
        """A relationship edge cannot resurrect a visibly non-usable session."""
        db = _make_db()
        # Remove the orphan's metadata edge — only the relationship row remains.
        db[_T_SESSIONS][ORPHAN]["metadata"] = {}
        ids = canonical_website_session_ids(db, user_id=USER, project_ids=[PROJECT])
        assert ORPHAN not in ids
        assert ids == [COMPLETED]

    def test_edge_with_missing_session_row_keeps_legacy_behavior(self) -> None:
        """Legacy retained-artifact edges (session row gone) are still admitted."""
        db = _make_db()
        del db[_T_SESSIONS][ORPHAN]
        ids = canonical_website_session_ids(db, user_id=USER, project_ids=[PROJECT])
        assert COMPLETED in ids
        assert ORPHAN in ids  # unknown session rows are not silently dropped

    def test_expired_session_excluded(self) -> None:
        db = _make_db()
        db[_T_SESSIONS][ORPHAN]["status"] = "expired"
        ids = canonical_website_session_ids(db, user_id=USER, project_ids=[PROJECT])
        assert ids == [COMPLETED]

    def test_usable_statuses_is_completed_only(self) -> None:
        assert USABLE_WEBSITE_SESSION_STATUSES == frozenset({"completed"})


# ── Report + defense consumers ─────────────────────────────────────────────────

class TestConsumersSurfaceExactlyOneWebsiteProof:
    def test_report_surfaces_only_completed_session(self) -> None:
        db = _make_db()
        proofs = _canonical_website_proofs_for_project(
            db, user_id=USER, project_ids=[PROJECT]
        )
        assert [p["proof_session_id"] for p in proofs] == [COMPLETED]

    def test_report_excludes_orphan_even_with_stray_analysis_row(self) -> None:
        """Resolver-level gating protects the report even if an analysis row
        somehow exists for a session that never completed."""
        db = _make_db()
        db["workflow_analysis_results"]["wf-orphan"] = {
            "id": "wf-orphan",
            "user_id": USER,
            "proof_session_id": ORPHAN,
            "target_website": "https://demo.umami.is",
            "evidence_strength_score": 10,
            "workflow_confidence": "insufficient",
            "supported_skills": [],
            "created_at": "2026-07-21T15:30:00+00:00",
        }
        proofs = _canonical_website_proofs_for_project(
            db, user_id=USER, project_ids=[PROJECT]
        )
        assert [p["proof_session_id"] for p in proofs] == [COMPLETED]

    def test_defense_merge_attaches_exactly_one_website_proof(self) -> None:
        db = _make_db()
        group = [db["vbr_projects"][PROJECT]]
        merged = merge_group_metadata_with_canonical(db, group)
        website_proofs = (merged.get("attached_proofs") or {}).get("website_proofs") or []
        session_ids = [str(w.get("proof_session_id") or "") for w in website_proofs]
        assert session_ids == [COMPLETED]


# ── Cleanup service: post-058 dependent coverage ───────────────────────────────

class TestCleanupCoversPost058Dependents:
    def test_dry_run_counts_relationships_and_skill_evidence(self) -> None:
        db = _make_db()
        report = ProofSessionCleanupService(db).dry_run(ORPHAN)
        assert report.counts[_T_RELATIONSHIPS] == 1
        assert report.counts[_T_SKILL_EVIDENCE] == 1

    def test_dry_run_does_not_mutate_db(self) -> None:
        db = _make_db()
        before = copy.deepcopy(db)
        ProofSessionCleanupService(db).dry_run(ORPHAN)
        assert db == before

    def test_dry_run_safe_when_new_tables_absent(self) -> None:
        """Pre-058 dict db (no relationships/skill_evidence tables): counts are
        0 and the read does not create the missing tables."""
        db = _make_db()
        del db[_T_RELATIONSHIPS]
        del db[_T_SKILL_EVIDENCE]
        before = copy.deepcopy(db)
        report = ProofSessionCleanupService(db).dry_run(ORPHAN)
        assert report.counts[_T_RELATIONSHIPS] == 0
        assert report.counts[_T_SKILL_EVIDENCE] == 0
        assert db == before

    def test_backup_includes_relationships_and_skill_evidence(self) -> None:
        db = _make_db()
        data = ProofSessionCleanupService(db).backup(ORPHAN)
        assert [r["id"] for r in data[_T_RELATIONSHIPS]] == ["rel-orphan"]
        assert [r["id"] for r in data[_T_SKILL_EVIDENCE]] == [SEV_ORPHAN]

    def test_backup_does_not_include_other_sessions_rows(self) -> None:
        db = _make_db()
        data = ProofSessionCleanupService(db).backup(ORPHAN)
        assert all(r["proof_id"] == ORPHAN for r in data[_T_RELATIONSHIPS])
        assert all(r["id"] != SEV_COMPLETED for r in data[_T_SKILL_EVIDENCE])


# ── Archive = expire + detach ──────────────────────────────────────────────────

class TestArchiveDetachesLinkage:
    def test_archive_expires_and_detaches_metadata(self) -> None:
        db = _make_db()
        assert ProofSessionCleanupService(db).archive_session(ORPHAN) is True
        row = db[_T_SESSIONS][ORPHAN]
        assert row["status"] == "expired"
        assert "project_id" not in row["metadata"]
        assert row["metadata"]["detached_project_id"] == PROJECT
        assert row["metadata"]["project_relationship_state"] == "vault_only"
        assert row["metadata"]["project_detach_source"].endswith("archive_session")

    def test_archive_downgrades_relationship_row_with_provenance(self) -> None:
        db = _make_db()
        ProofSessionCleanupService(db).archive_session(ORPHAN)
        rel = db[_T_RELATIONSHIPS]["rel-orphan"]
        assert rel["relationship_state"] == "vault_only"
        assert rel["project_id"] is None
        assert rel["provenance"]["detached_from_project_id"] == PROJECT
        assert rel["provenance"]["previous_relationship_state"] == "directly_linked"

    def test_archive_deletes_nothing(self) -> None:
        db = _make_db()
        ProofSessionCleanupService(db).archive_session(ORPHAN)
        assert ORPHAN in db[_T_SESSIONS]
        assert "rel-orphan" in db[_T_RELATIONSHIPS]
        assert SEV_ORPHAN in db[_T_SKILL_EVIDENCE]

    def test_archive_leaves_completed_session_untouched(self) -> None:
        db = _make_db()
        before_completed = copy.deepcopy(db[_T_SESSIONS][COMPLETED])
        before_rel = copy.deepcopy(db[_T_RELATIONSHIPS]["rel-completed"])
        ProofSessionCleanupService(db).archive_session(ORPHAN)
        assert db[_T_SESSIONS][COMPLETED] == before_completed
        assert db[_T_RELATIONSHIPS]["rel-completed"] == before_rel

    def test_resolver_excludes_archived_session_via_all_edges(self) -> None:
        db = _make_db()
        ProofSessionCleanupService(db).archive_session(ORPHAN)
        ids = canonical_website_session_ids(db, user_id=USER, project_ids=[PROJECT])
        assert ids == [COMPLETED]

    def test_archive_without_project_linkage_stays_plain_expire(self) -> None:
        db = _make_db()
        db[_T_SESSIONS][ORPHAN]["metadata"] = {"other_key": "kept"}
        del db[_T_RELATIONSHIPS]["rel-orphan"]
        ProofSessionCleanupService(db).archive_session(ORPHAN)
        row = db[_T_SESSIONS][ORPHAN]
        assert row["status"] == "expired"
        assert row["metadata"] == {"other_key": "kept"}
        assert "detached_project_id" not in row["metadata"]


# ── Delete = no dangling rows ──────────────────────────────────────────────────

class TestDeleteLeavesNoDanglingRows:
    def test_delete_removes_relationship_and_skill_evidence(self) -> None:
        db = _make_db()
        result = ProofSessionCleanupService(db).delete(ORPHAN, confirm=True)
        assert result.deleted_counts[_T_RELATIONSHIPS] == 1
        assert result.deleted_counts[_T_SKILL_EVIDENCE] == 1
        assert "rel-orphan" not in db[_T_RELATIONSHIPS]
        assert SEV_ORPHAN not in db[_T_SKILL_EVIDENCE]
        assert ORPHAN not in db[_T_SESSIONS]

    def test_no_dangling_relationship_rows_after_delete(self) -> None:
        db = _make_db()
        ProofSessionCleanupService(db).delete(ORPHAN, confirm=True)
        dangling = [
            r for r in db[_T_RELATIONSHIPS].values()
            if str(r.get("proof_id") or "") == ORPHAN
        ]
        assert dangling == []

    def test_resolver_output_unchanged_after_delete(self) -> None:
        db = _make_db()
        before = canonical_website_session_ids(db, user_id=USER, project_ids=[PROJECT])
        ProofSessionCleanupService(db).delete(ORPHAN, confirm=True)
        after = canonical_website_session_ids(db, user_id=USER, project_ids=[PROJECT])
        assert before == after == [COMPLETED]

    def test_delete_does_not_touch_completed_sessions_rows(self) -> None:
        db = _make_db()
        ProofSessionCleanupService(db).delete(ORPHAN, confirm=True)
        assert COMPLETED in db[_T_SESSIONS]
        assert "rel-completed" in db[_T_RELATIONSHIPS]
        assert SEV_COMPLETED in db[_T_SKILL_EVIDENCE]

    def test_delete_idempotent_for_new_tables(self) -> None:
        db = _make_db()
        svc = ProofSessionCleanupService(db)
        svc.delete(ORPHAN, confirm=True)
        result2 = svc.delete(ORPHAN, confirm=True)
        assert result2.deleted_counts.get(_T_RELATIONSHIPS, 0) == 0
        assert result2.deleted_counts.get(_T_SKILL_EVIDENCE, 0) == 0


# ── Skill evidence profile honesty gate ────────────────────────────────────────

class TestProfileServiceGate:
    def _profiles(self, db: dict[str, Any]):
        return SkillEvidenceProfileService(db).compute_skill_evidence_profiles(USER)

    def test_orphan_stub_not_surfaced_while_abandoned(self) -> None:
        db = _make_db()
        urls = [p.evidence_url for p in self._profiles(db)]
        assert "https://demo.umami.is" not in urls
        assert "https://plausible.io/plausible.io" in urls

    def test_orphan_stub_not_surfaced_after_archive(self) -> None:
        db = _make_db()
        ProofSessionCleanupService(db).archive_session(ORPHAN)
        urls = [p.evidence_url for p in self._profiles(db)]
        assert "https://demo.umami.is" not in urls

    def test_in_flight_uploaded_session_keeps_its_stub(self) -> None:
        db = _make_db()
        db[_T_SESSIONS][ORPHAN]["status"] = "uploaded_pending_analysis"
        urls = [p.evidence_url for p in self._profiles(db)]
        assert "https://demo.umami.is" in urls

    def test_verified_row_never_gated(self) -> None:
        """The gate only applies to still-pending stubs."""
        db = _make_db()
        db[_T_SKILL_EVIDENCE][SEV_ORPHAN]["verification_status"] = "verified"
        urls = [p.evidence_url for p in self._profiles(db)]
        assert "https://demo.umami.is" in urls

    def test_legacy_row_without_session_kept(self) -> None:
        db = _make_db()
        db[_T_SKILL_EVIDENCE]["sev-legacy"] = {
            "id": "sev-legacy",
            "user_id": USER,
            "evidence_type": "private website (extension proof)",
            "evidence_url": "https://legacy.example.com",
            "skill_name": "React",
            "verification_status": "pending_review",
            "metadata": {},
            "created_at": "2026-07-01T00:00:00+00:00",
        }
        urls = [p.evidence_url for p in self._profiles(db)]
        assert "https://legacy.example.com" in urls
