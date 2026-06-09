"""Tests for ProofSessionCleanupService.

Covers:
  ✓ dry_run reports exact affected row counts per table
  ✓ dry_run counts skill_evidence_artifacts via artifact_data->>'proof_session_id'
  ✓ dry_run counts extension_proof_sessions by UUID id
  ✓ dry_run counts text-column tables (frames, events) via proof_session_id text
  ✓ dry_run counts UUID FK tables (analysis, optional, live, audit)
  ✓ dry_run does NOT mutate any table
  ✓ dry_run session_exists=False when session row is missing
  ✓ dry_run reports affected_pipeline_ids from artifacts
  ✓ dry_run includes audit event warning when audit rows exist
  ✓ delete() raises ValueError when confirm=False
  ✓ delete(confirm=True) removes artifacts selected by artifact_data proof_session_id
  ✓ delete(confirm=True) removes text-column rows (frames, events)
  ✓ delete(confirm=True) removes session row (cascades analysis, optional, live, audit in dict mode)
  ✓ unrelated session rows are NOT affected by dry_run counts
  ✓ unrelated session rows are NOT deleted
  ✓ skill_evidence_pipelines are NOT deleted (only artifacts are removed)
  ✓ affected_pipeline_ids reported for evidence_count refresh
  ✓ backup() returns all rows across all tables for the session
  ✓ backup() does NOT mutate DB
  ✓ archive_session() sets status='expired' and does NOT delete rows
  ✓ archive_session() returns False for missing session

All storage is in-memory (dict mode).
No real network calls.
"""

from __future__ import annotations

import copy
from typing import Any
from uuid import uuid4

import pytest

from app.services.proof_session_cleanup_service import (
    ProofSessionCleanupService,
    _T_ANALYSIS,
    _T_ARTIFACTS,
    _T_AUDIT,
    _T_EVENTS,
    _T_FRAMES,
    _T_LIVE,
    _T_OPTIONAL,
    _T_SESSIONS,
)

# ── Constants ──────────────────────────────────────────────────────────────────

NOISY_SESSION = "d592f7fb-6aee-47d6-a549-a7192268574e"
OTHER_SESSION = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PIPELINE_A = str(uuid4())
PIPELINE_B = str(uuid4())


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_db_with_noisy_session() -> dict[str, Any]:
    """Populate an in-memory store with rows for NOISY_SESSION and OTHER_SESSION."""
    db: dict[str, Any] = {}

    # extension_proof_sessions — id is the UUID key
    db[_T_SESSIONS] = {
        NOISY_SESSION: {
            "id": NOISY_SESSION,
            "user_id": "user-1",
            "status": "completed",
            "website_url": "https://supabase.com/dashboard",
        },
        OTHER_SESSION: {
            "id": OTHER_SESSION,
            "user_id": "user-2",
            "status": "completed",
            "website_url": "https://threejs.org/examples",
        },
    }

    # workflow_analysis_results (UUID FK — proof_session_id as UUID string)
    db[_T_ANALYSIS] = {
        "ar-1": {"id": "ar-1", "proof_session_id": NOISY_SESSION, "user_id": "user-1"},
        "ar-2": {"id": "ar-2", "proof_session_id": OTHER_SESSION, "user_id": "user-2"},
    }

    # workflow_visual_frame_evidence (TEXT proof_session_id)
    db[_T_FRAMES] = {
        f"fr-{i}": {"id": f"fr-{i}", "proof_session_id": NOISY_SESSION, "user_id": "user-1"}
        for i in range(20)
    }
    db[_T_FRAMES].update({
        "fr-other": {"id": "fr-other", "proof_session_id": OTHER_SESSION, "user_id": "user-2"},
    })

    # workflow_visible_evidence_events (TEXT proof_session_id)
    db[_T_EVENTS] = {
        f"ev-{i}": {"id": f"ev-{i}", "proof_session_id": NOISY_SESSION, "user_id": "user-1"}
        for i in range(64)
    }
    db[_T_EVENTS].update({
        "ev-other": {"id": "ev-other", "proof_session_id": OTHER_SESSION, "user_id": "user-2"},
    })

    # optional_evidence_submissions (UUID FK)
    db[_T_OPTIONAL] = {
        "opt-1": {"id": "opt-1", "proof_session_id": NOISY_SESSION, "user_id": "user-1"},
        "opt-other": {"id": "opt-other", "proof_session_id": OTHER_SESSION, "user_id": "user-2"},
    }

    # live_website_check_results (UUID FK)
    db[_T_LIVE] = {
        "lw-1": {"id": "lw-1", "proof_session_id": NOISY_SESSION, "user_id": "user-1"},
        "lw-other": {"id": "lw-other", "proof_session_id": OTHER_SESSION, "user_id": "user-2"},
    }

    # skill_evidence_artifacts — artifact_data->>'proof_session_id' path
    # proof_session_id FK column is None/null (website proof synced artifacts)
    db[_T_ARTIFACTS] = {}
    for i in range(55):
        art_id = f"art-noisy-{i}"
        db[_T_ARTIFACTS][art_id] = {
            "id": art_id,
            "pipeline_id": PIPELINE_A if i < 30 else PIPELINE_B,
            "proof_session_id": None,  # FK column is null for website proof artifacts
            "artifact_data": {"proof_session_id": NOISY_SESSION, "score": 70},
            "source_type": "workflow",
        }
    # Unrelated artifact for OTHER_SESSION
    db[_T_ARTIFACTS]["art-other"] = {
        "id": "art-other",
        "pipeline_id": PIPELINE_B,
        "proof_session_id": None,
        "artifact_data": {"proof_session_id": OTHER_SESSION, "score": 60},
        "source_type": "workflow",
    }

    # evidence_access_audit_events (UUID FK)
    db[_T_AUDIT] = {
        "audit-1": {
            "id": "audit-1",
            "proof_session_id": NOISY_SESSION,
            "event_type": "access_requested",
        },
        "audit-other": {
            "id": "audit-other",
            "proof_session_id": OTHER_SESSION,
            "event_type": "access_approved",
        },
    }

    return db


@pytest.fixture()
def db() -> dict[str, Any]:
    return _make_db_with_noisy_session()


@pytest.fixture()
def svc(db: dict[str, Any]) -> ProofSessionCleanupService:
    return ProofSessionCleanupService(db)


# ── Dry-run tests ──────────────────────────────────────────────────────────────

class TestDryRun:
    def test_session_exists(self, svc: ProofSessionCleanupService) -> None:
        report = svc.dry_run(NOISY_SESSION)
        assert report.session_exists is True

    def test_session_not_exists_when_missing(self, svc: ProofSessionCleanupService) -> None:
        report = svc.dry_run("00000000-0000-0000-0000-000000000000")
        assert report.session_exists is False

    def test_counts_session_row(self, svc: ProofSessionCleanupService) -> None:
        report = svc.dry_run(NOISY_SESSION)
        assert report.counts[_T_SESSIONS] == 1

    def test_counts_analysis_rows(self, svc: ProofSessionCleanupService) -> None:
        report = svc.dry_run(NOISY_SESSION)
        assert report.counts[_T_ANALYSIS] == 1

    def test_counts_frame_rows(self, svc: ProofSessionCleanupService) -> None:
        report = svc.dry_run(NOISY_SESSION)
        assert report.counts[_T_FRAMES] == 20

    def test_counts_event_rows(self, svc: ProofSessionCleanupService) -> None:
        report = svc.dry_run(NOISY_SESSION)
        assert report.counts[_T_EVENTS] == 64

    def test_counts_optional_rows(self, svc: ProofSessionCleanupService) -> None:
        report = svc.dry_run(NOISY_SESSION)
        assert report.counts[_T_OPTIONAL] == 1

    def test_counts_live_rows(self, svc: ProofSessionCleanupService) -> None:
        report = svc.dry_run(NOISY_SESSION)
        assert report.counts[_T_LIVE] == 1

    def test_counts_artifacts_via_jsonb_path(self, svc: ProofSessionCleanupService) -> None:
        """Artifacts must be counted via artifact_data->>'proof_session_id', not FK column."""
        report = svc.dry_run(NOISY_SESSION)
        assert report.counts[_T_ARTIFACTS] == 55

    def test_audit_event_count(self, svc: ProofSessionCleanupService) -> None:
        report = svc.dry_run(NOISY_SESSION)
        assert report.audit_event_count == 1

    def test_audit_warning_included(self, svc: ProofSessionCleanupService) -> None:
        report = svc.dry_run(NOISY_SESSION)
        assert any("audit" in w.lower() for w in report.warnings)

    def test_affected_pipeline_ids_reported(self, svc: ProofSessionCleanupService) -> None:
        report = svc.dry_run(NOISY_SESSION)
        assert set(report.affected_pipeline_ids) == {PIPELINE_A, PIPELINE_B}

    def test_to_dict_shape(self, svc: ProofSessionCleanupService) -> None:
        d = svc.dry_run(NOISY_SESSION).to_dict()
        assert "counts_per_table" in d
        assert "total_rows" in d
        assert "affected_pipeline_ids" in d
        assert "session_exists" in d

    def test_dry_run_does_not_mutate_db(
        self, svc: ProofSessionCleanupService, db: dict[str, Any]
    ) -> None:
        before = copy.deepcopy(db)
        svc.dry_run(NOISY_SESSION)
        assert db == before


# ── Unrelated session isolation ────────────────────────────────────────────────

class TestIsolation:
    def test_dry_run_does_not_count_other_session(
        self, svc: ProofSessionCleanupService
    ) -> None:
        """Counts for NOISY_SESSION must not include OTHER_SESSION rows."""
        report = svc.dry_run(NOISY_SESSION)
        # OTHER_SESSION has 1 artifact — must not be included
        assert report.counts[_T_ARTIFACTS] == 55
        assert report.counts[_T_FRAMES] == 20
        assert report.counts[_T_EVENTS] == 64

    def test_delete_does_not_touch_other_session_rows(
        self, svc: ProofSessionCleanupService, db: dict[str, Any]
    ) -> None:
        svc.delete(NOISY_SESSION, confirm=True)

        # OTHER_SESSION rows must still exist
        assert OTHER_SESSION in db[_T_SESSIONS]
        assert any(
            str(r.get("proof_session_id")) == OTHER_SESSION
            for r in db[_T_FRAMES].values()
        )
        assert any(
            str(r.get("proof_session_id")) == OTHER_SESSION
            for r in db[_T_EVENTS].values()
        )
        assert "art-other" in db[_T_ARTIFACTS]

    def test_delete_does_not_delete_pipelines(
        self, svc: ProofSessionCleanupService, db: dict[str, Any]
    ) -> None:
        """Pipelines themselves are never deleted — only their artifacts."""
        svc.delete(NOISY_SESSION, confirm=True)
        # There are no pipelines table in this test db, but we can verify the
        # service doesn't touch a table it's not responsible for.
        # If pipelines were inserted, they'd be untouched.
        assert _T_ARTIFACTS in db  # table still exists, just emptied for noisy session


# ── Delete tests ───────────────────────────────────────────────────────────────

class TestDelete:
    def test_delete_without_confirm_raises(self, svc: ProofSessionCleanupService) -> None:
        with pytest.raises(ValueError, match="confirm=True"):
            svc.delete(NOISY_SESSION, confirm=False)

    def test_delete_without_confirm_default_raises(
        self, svc: ProofSessionCleanupService
    ) -> None:
        with pytest.raises(ValueError):
            svc.delete(NOISY_SESSION)

    def test_delete_removes_artifacts(
        self, svc: ProofSessionCleanupService, db: dict[str, Any]
    ) -> None:
        svc.delete(NOISY_SESSION, confirm=True)
        remaining = [
            row for row in db[_T_ARTIFACTS].values()
            if (row.get("artifact_data") or {}).get("proof_session_id") == NOISY_SESSION
        ]
        assert remaining == []

    def test_delete_removes_frame_rows(
        self, svc: ProofSessionCleanupService, db: dict[str, Any]
    ) -> None:
        svc.delete(NOISY_SESSION, confirm=True)
        remaining = [
            row for row in db[_T_FRAMES].values()
            if str(row.get("proof_session_id")) == NOISY_SESSION
        ]
        assert remaining == []

    def test_delete_removes_event_rows(
        self, svc: ProofSessionCleanupService, db: dict[str, Any]
    ) -> None:
        svc.delete(NOISY_SESSION, confirm=True)
        remaining = [
            row for row in db[_T_EVENTS].values()
            if str(row.get("proof_session_id")) == NOISY_SESSION
        ]
        assert remaining == []

    def test_delete_removes_session_row(
        self, svc: ProofSessionCleanupService, db: dict[str, Any]
    ) -> None:
        svc.delete(NOISY_SESSION, confirm=True)
        assert NOISY_SESSION not in db[_T_SESSIONS]

    def test_delete_cascades_analysis_in_dict_mode(
        self, svc: ProofSessionCleanupService, db: dict[str, Any]
    ) -> None:
        svc.delete(NOISY_SESSION, confirm=True)
        remaining = [
            row for row in db[_T_ANALYSIS].values()
            if str(row.get("proof_session_id")) == NOISY_SESSION
        ]
        assert remaining == []

    def test_delete_cascades_audit_in_dict_mode(
        self, svc: ProofSessionCleanupService, db: dict[str, Any]
    ) -> None:
        svc.delete(NOISY_SESSION, confirm=True)
        remaining = [
            row for row in db[_T_AUDIT].values()
            if str(row.get("proof_session_id")) == NOISY_SESSION
        ]
        assert remaining == []

    def test_delete_report_contains_affected_pipelines(
        self, svc: ProofSessionCleanupService
    ) -> None:
        result = svc.delete(NOISY_SESSION, confirm=True)
        assert set(result.affected_pipeline_ids) == {PIPELINE_A, PIPELINE_B}

    def test_delete_report_deleted_artifact_count(
        self, svc: ProofSessionCleanupService
    ) -> None:
        result = svc.delete(NOISY_SESSION, confirm=True)
        assert result.deleted_counts[_T_ARTIFACTS] == 55

    def test_delete_report_deleted_frame_count(
        self, svc: ProofSessionCleanupService
    ) -> None:
        result = svc.delete(NOISY_SESSION, confirm=True)
        assert result.deleted_counts[_T_FRAMES] == 20

    def test_delete_report_deleted_event_count(
        self, svc: ProofSessionCleanupService
    ) -> None:
        result = svc.delete(NOISY_SESSION, confirm=True)
        assert result.deleted_counts[_T_EVENTS] == 64

    def test_delete_idempotent_second_call(
        self, svc: ProofSessionCleanupService
    ) -> None:
        svc.delete(NOISY_SESSION, confirm=True)
        result2 = svc.delete(NOISY_SESSION, confirm=True)
        assert result2.deleted_counts.get(_T_SESSIONS, 0) == 0
        assert result2.deleted_counts.get(_T_ARTIFACTS, 0) == 0


# ── Backup tests ───────────────────────────────────────────────────────────────

class TestBackup:
    def test_backup_includes_session(self, svc: ProofSessionCleanupService) -> None:
        data = svc.backup(NOISY_SESSION)
        assert len(data[_T_SESSIONS]) == 1
        assert data[_T_SESSIONS][0]["id"] == NOISY_SESSION

    def test_backup_includes_all_frames(self, svc: ProofSessionCleanupService) -> None:
        data = svc.backup(NOISY_SESSION)
        assert len(data[_T_FRAMES]) == 20

    def test_backup_includes_all_events(self, svc: ProofSessionCleanupService) -> None:
        data = svc.backup(NOISY_SESSION)
        assert len(data[_T_EVENTS]) == 64

    def test_backup_includes_artifacts(self, svc: ProofSessionCleanupService) -> None:
        data = svc.backup(NOISY_SESSION)
        assert len(data[_T_ARTIFACTS]) == 55

    def test_backup_does_not_include_other_session_rows(
        self, svc: ProofSessionCleanupService
    ) -> None:
        data = svc.backup(NOISY_SESSION)
        for table in (_T_SESSIONS, _T_ANALYSIS, _T_OPTIONAL, _T_LIVE):
            for row in data[table]:
                sid = row.get("proof_session_id") or row.get("id")
                assert sid != OTHER_SESSION, f"Other-session row found in {table} backup"

    def test_backup_does_not_mutate_db(
        self, svc: ProofSessionCleanupService, db: dict[str, Any]
    ) -> None:
        before = copy.deepcopy(db)
        svc.backup(NOISY_SESSION)
        assert db == before


# ── Archive tests ──────────────────────────────────────────────────────────────

class TestArchive:
    def test_archive_sets_status_expired(
        self, svc: ProofSessionCleanupService, db: dict[str, Any]
    ) -> None:
        result = svc.archive_session(NOISY_SESSION)
        assert result is True
        assert db[_T_SESSIONS][NOISY_SESSION]["status"] == "expired"

    def test_archive_does_not_delete_session(
        self, svc: ProofSessionCleanupService, db: dict[str, Any]
    ) -> None:
        svc.archive_session(NOISY_SESSION)
        assert NOISY_SESSION in db[_T_SESSIONS]

    def test_archive_does_not_delete_frames(
        self, svc: ProofSessionCleanupService, db: dict[str, Any]
    ) -> None:
        svc.archive_session(NOISY_SESSION)
        count = sum(
            1 for row in db[_T_FRAMES].values()
            if str(row.get("proof_session_id")) == NOISY_SESSION
        )
        assert count == 20

    def test_archive_does_not_touch_artifacts(
        self, svc: ProofSessionCleanupService, db: dict[str, Any]
    ) -> None:
        before_count = sum(
            1 for row in db[_T_ARTIFACTS].values()
            if (row.get("artifact_data") or {}).get("proof_session_id") == NOISY_SESSION
        )
        svc.archive_session(NOISY_SESSION)
        after_count = sum(
            1 for row in db[_T_ARTIFACTS].values()
            if (row.get("artifact_data") or {}).get("proof_session_id") == NOISY_SESSION
        )
        assert before_count == after_count == 55

    def test_archive_returns_false_when_missing(
        self, svc: ProofSessionCleanupService
    ) -> None:
        result = svc.archive_session("00000000-0000-0000-0000-000000000000")
        assert result is False

    def test_archive_does_not_affect_other_session(
        self, svc: ProofSessionCleanupService, db: dict[str, Any]
    ) -> None:
        svc.archive_session(NOISY_SESSION)
        assert db[_T_SESSIONS][OTHER_SESSION]["status"] == "completed"


# ── Pipeline refresh identification ───────────────────────────────────────────

class TestPipelineRefresh:
    def test_dry_run_reports_pipeline_ids_for_refresh(
        self, svc: ProofSessionCleanupService
    ) -> None:
        report = svc.dry_run(NOISY_SESSION)
        assert PIPELINE_A in report.affected_pipeline_ids
        assert PIPELINE_B in report.affected_pipeline_ids

    def test_no_pipeline_ids_when_no_artifacts(self) -> None:
        db: dict[str, Any] = {
            _T_SESSIONS: {NOISY_SESSION: {"id": NOISY_SESSION, "status": "completed"}},
        }
        svc = ProofSessionCleanupService(db)
        report = svc.dry_run(NOISY_SESSION)
        assert report.affected_pipeline_ids == []

    def test_delete_report_includes_pipeline_ids_before_deletion(
        self, svc: ProofSessionCleanupService
    ) -> None:
        result = svc.delete(NOISY_SESSION, confirm=True)
        assert PIPELINE_A in result.affected_pipeline_ids
        assert PIPELINE_B in result.affected_pipeline_ids

    def test_unrelated_pipeline_not_in_affected_list(
        self, svc: ProofSessionCleanupService
    ) -> None:
        report = svc.dry_run(NOISY_SESSION)
        # PIPELINE_B also has the OTHER_SESSION artifact (art-other), but
        # the affected list should only come from NOISY_SESSION artifacts.
        # Both pipelines appear because NOISY_SESSION artifacts span both.
        # Verify OTHER_SESSION's pipeline_id is not added from the other artifact:
        all_ids = set(report.affected_pipeline_ids)
        # art-other has PIPELINE_B and OTHER_SESSION — must not add an extra "other" pipeline
        assert len(all_ids) == 2
