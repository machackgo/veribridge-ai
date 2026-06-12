"""Proof Session Cleanup Service.

Provides a safe dry-run + delete path for a single proof session and all
its dependent data.  Designed for dev/admin use only — never exposed on a
public or student route.

Table coverage
--------------
  extension_proof_sessions          id = proof_session_id (UUID)
  workflow_analysis_results         proof_session_id UUID FK → cascades on session delete
  workflow_visual_frame_evidence    proof_session_id TEXT   → must be deleted explicitly
  workflow_visible_evidence_events  proof_session_id TEXT   → must be deleted explicitly
  optional_evidence_submissions     proof_session_id UUID FK → cascades
  live_website_check_results        proof_session_id UUID FK → cascades
  skill_evidence_artifacts          artifact_data->>'proof_session_id' = session_id
                                    (proof_session_id FK column is NULL for synced website
                                    proof artifacts — must query via JSONB path)
  evidence_access_audit_events      proof_session_id UUID FK → cascades (audit only, reported)

Archive vs delete
-----------------
  • extension_proof_sessions has a status column — setting status='expired' is the
    soft-archive path.  It does NOT remove the text-column tables or synced artifacts.
  • Full delete removes everything, including text-column tables and synced artifacts.
  • Default mode is always dry_run=True.  Destructive delete requires confirm=True.

Pipeline evidence_count refresh
--------------------------------
  After artifacts are deleted the affected skill_evidence_pipelines may have stale
  evidence_count.  dry_run() and delete() both report affected_pipeline_ids so the
  caller can trigger a recalculate.

Dict-mode (tests)
-----------------
  When db is a plain dict the service uses in-memory dict operations.
  Table structure: db[table_name][row_id] = row_dict
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Table names ────────────────────────────────────────────────────────────────

_T_SESSIONS   = "extension_proof_sessions"
_T_ANALYSIS   = "workflow_analysis_results"
_T_FRAMES     = "workflow_visual_frame_evidence"
_T_EVENTS     = "workflow_visible_evidence_events"
_T_OPTIONAL   = "optional_evidence_submissions"
_T_LIVE       = "live_website_check_results"
_T_ARTIFACTS  = "skill_evidence_artifacts"
_T_AUDIT      = "evidence_access_audit_events"


# ── Result dataclasses ─────────────────────────────────────────────────────────

@dataclass
class DryRunReport:
    proof_session_id: str
    counts: dict[str, int] = field(default_factory=dict)
    affected_pipeline_ids: list[str] = field(default_factory=list)
    audit_event_count: int = 0
    session_exists: bool = False
    warnings: list[str] = field(default_factory=list)

    def total_rows(self) -> int:
        return sum(self.counts.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "proof_session_id": self.proof_session_id,
            "session_exists": self.session_exists,
            "counts_per_table": self.counts,
            "total_rows": self.total_rows(),
            "audit_event_count": self.audit_event_count,
            "affected_pipeline_ids": self.affected_pipeline_ids,
            "warnings": self.warnings,
        }


@dataclass
class DeleteReport:
    proof_session_id: str
    deleted_counts: dict[str, int] = field(default_factory=dict)
    affected_pipeline_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proof_session_id": self.proof_session_id,
            "deleted_counts": self.deleted_counts,
            "total_deleted": sum(self.deleted_counts.values()),
            "affected_pipeline_ids": self.affected_pipeline_ids,
            "errors": self.errors,
        }


# ── Service ────────────────────────────────────────────────────────────────────

class ProofSessionCleanupService:
    """Safe dry-run + delete utility for a single proof session.

    Usage (dry-run, always safe):
        svc = ProofSessionCleanupService(db)
        report = svc.dry_run(session_id)
        print(report.to_dict())

    Usage (backup then delete):
        backup = svc.backup(session_id)
        # write backup JSON somewhere safe
        result = svc.delete(session_id, confirm=True)

    Usage (soft archive only — sets status='expired' on the session row):
        svc.archive_session(session_id)
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    # ── Dict-mode helpers ──────────────────────────────────────────────────────

    def _is_dict_mode(self) -> bool:
        return isinstance(self._db, dict)

    def _dict_table(self, table: str) -> dict[str, dict[str, Any]]:
        return self._db.setdefault(table, {})

    def _dict_rows_matching(self, table: str, session_id: str) -> list[dict[str, Any]]:
        """Return rows from a text proof_session_id column (frames, events)."""
        return [
            row for row in self._dict_table(table).values()
            if str(row.get("proof_session_id", "")) == session_id
        ]

    def _dict_rows_uuid_matching(self, table: str, session_id: str) -> list[dict[str, Any]]:
        """Return rows from a UUID proof_session_id column (analysis, optional, live, audit)."""
        return [
            row for row in self._dict_table(table).values()
            if str(row.get("proof_session_id", "")) == session_id
        ]

    def _dict_artifacts_matching(self, session_id: str) -> list[dict[str, Any]]:
        """Return skill_evidence_artifacts where artifact_data->>'proof_session_id' == session_id."""
        return [
            row for row in self._dict_table(_T_ARTIFACTS).values()
            if (row.get("artifact_data") or {}).get("proof_session_id") == session_id
        ]

    # ── Count helpers ──────────────────────────────────────────────────────────

    def _count_session(self, session_id: str) -> int:
        if self._is_dict_mode():
            return 1 if session_id in self._dict_table(_T_SESSIONS) else 0
        try:
            resp = (
                self._db.table(_T_SESSIONS)
                .select("id", count="exact")
                .eq("id", session_id)
                .execute()
            )
            return getattr(resp, "count", 0) or 0
        except Exception:
            logger.warning("cleanup: count %s failed", _T_SESSIONS, exc_info=True)
            return 0

    def _count_text_table(self, table: str, session_id: str) -> int:
        """Count rows where proof_session_id (TEXT) = session_id."""
        if self._is_dict_mode():
            return len(self._dict_rows_matching(table, session_id))
        try:
            resp = (
                self._db.table(table)
                .select("id", count="exact")
                .eq("proof_session_id", session_id)
                .execute()
            )
            return getattr(resp, "count", 0) or 0
        except Exception:
            logger.warning("cleanup: count %s failed", table, exc_info=True)
            return 0

    def _count_uuid_table(self, table: str, session_id: str) -> int:
        """Count rows where proof_session_id (UUID FK) = session_id."""
        if self._is_dict_mode():
            return len(self._dict_rows_uuid_matching(table, session_id))
        try:
            resp = (
                self._db.table(table)
                .select("id", count="exact")
                .eq("proof_session_id", session_id)
                .execute()
            )
            return getattr(resp, "count", 0) or 0
        except Exception:
            logger.warning("cleanup: count %s failed", table, exc_info=True)
            return 0

    def _count_artifacts(self, session_id: str) -> int:
        """Count skill_evidence_artifacts via artifact_data->>'proof_session_id'."""
        if self._is_dict_mode():
            return len(self._dict_artifacts_matching(session_id))
        try:
            resp = (
                self._db.table(_T_ARTIFACTS)
                .select("id", count="exact")
                .filter("artifact_data->>proof_session_id", "eq", session_id)
                .execute()
            )
            return getattr(resp, "count", 0) or 0
        except Exception:
            logger.warning("cleanup: count %s (jsonb path) failed", _T_ARTIFACTS, exc_info=True)
            return 0

    def _list_affected_pipeline_ids(self, session_id: str) -> list[str]:
        """Return pipeline_ids of artifacts that would be deleted."""
        if self._is_dict_mode():
            return list({
                str(row["pipeline_id"])
                for row in self._dict_artifacts_matching(session_id)
                if row.get("pipeline_id")
            })
        try:
            resp = (
                self._db.table(_T_ARTIFACTS)
                .select("pipeline_id")
                .filter("artifact_data->>proof_session_id", "eq", session_id)
                .execute()
            )
            rows = getattr(resp, "data", []) or []
            return list({str(r["pipeline_id"]) for r in rows if r.get("pipeline_id")})
        except Exception:
            logger.warning("cleanup: list pipeline_ids failed", exc_info=True)
            return []

    # ── Dry-run ────────────────────────────────────────────────────────────────

    def dry_run(self, session_id: str) -> DryRunReport:
        """Count all rows that would be affected — makes no DB mutations."""
        report = DryRunReport(proof_session_id=session_id)

        session_count = self._count_session(session_id)
        report.session_exists = session_count > 0
        report.counts[_T_SESSIONS] = session_count

        if not report.session_exists:
            report.warnings.append(
                f"No row in {_T_SESSIONS} for id={session_id!r}. "
                "Text-column tables and artifacts may still have orphan rows."
            )

        report.counts[_T_ANALYSIS]  = self._count_uuid_table(_T_ANALYSIS, session_id)
        report.counts[_T_FRAMES]    = self._count_text_table(_T_FRAMES, session_id)
        report.counts[_T_EVENTS]    = self._count_text_table(_T_EVENTS, session_id)
        report.counts[_T_OPTIONAL]  = self._count_uuid_table(_T_OPTIONAL, session_id)
        report.counts[_T_LIVE]      = self._count_uuid_table(_T_LIVE, session_id)
        report.counts[_T_ARTIFACTS] = self._count_artifacts(session_id)

        report.audit_event_count    = self._count_uuid_table(_T_AUDIT, session_id)
        report.affected_pipeline_ids = self._list_affected_pipeline_ids(session_id)

        if report.audit_event_count > 0:
            report.warnings.append(
                f"{report.audit_event_count} evidence_access_audit_events row(s) reference "
                "this session. They will cascade-delete with the session row."
            )

        return report

    # ── Backup ─────────────────────────────────────────────────────────────────

    def backup(self, session_id: str) -> dict[str, Any]:
        """Return a JSON-serialisable dict of all rows that would be deleted.

        Call this and persist the result before running delete().
        """
        return {
            "proof_session_id": session_id,
            _T_SESSIONS:   self._fetch_session_rows(session_id),
            _T_ANALYSIS:   self._fetch_uuid_rows(_T_ANALYSIS, session_id),
            _T_FRAMES:     self._fetch_text_rows(_T_FRAMES, session_id),
            _T_EVENTS:     self._fetch_text_rows(_T_EVENTS, session_id),
            _T_OPTIONAL:   self._fetch_uuid_rows(_T_OPTIONAL, session_id),
            _T_LIVE:       self._fetch_uuid_rows(_T_LIVE, session_id),
            _T_ARTIFACTS:  self._fetch_artifact_rows(session_id),
            _T_AUDIT:      self._fetch_uuid_rows(_T_AUDIT, session_id),
        }

    def _fetch_session_rows(self, session_id: str) -> list[dict[str, Any]]:
        if self._is_dict_mode():
            row = self._dict_table(_T_SESSIONS).get(session_id)
            return [row] if row else []
        try:
            resp = self._db.table(_T_SESSIONS).select("*").eq("id", session_id).execute()
            return getattr(resp, "data", []) or []
        except Exception:
            return []

    def _fetch_text_rows(self, table: str, session_id: str) -> list[dict[str, Any]]:
        if self._is_dict_mode():
            return self._dict_rows_matching(table, session_id)
        try:
            resp = self._db.table(table).select("*").eq("proof_session_id", session_id).execute()
            return getattr(resp, "data", []) or []
        except Exception:
            return []

    def _fetch_uuid_rows(self, table: str, session_id: str) -> list[dict[str, Any]]:
        if self._is_dict_mode():
            return self._dict_rows_uuid_matching(table, session_id)
        try:
            resp = self._db.table(table).select("*").eq("proof_session_id", session_id).execute()
            return getattr(resp, "data", []) or []
        except Exception:
            return []

    def _fetch_artifact_rows(self, session_id: str) -> list[dict[str, Any]]:
        if self._is_dict_mode():
            return self._dict_artifacts_matching(session_id)
        try:
            resp = (
                self._db.table(_T_ARTIFACTS)
                .select("*")
                .filter("artifact_data->>proof_session_id", "eq", session_id)
                .execute()
            )
            return getattr(resp, "data", []) or []
        except Exception:
            return []

    # ── Soft archive ───────────────────────────────────────────────────────────

    def archive_session(self, session_id: str) -> bool:
        """Set extension_proof_sessions.status = 'expired' (soft archive only).

        Does NOT delete any rows or touch text-column tables.
        Returns True if a row was found and updated, False otherwise.
        """
        if self._is_dict_mode():
            table = self._dict_table(_T_SESSIONS)
            if session_id not in table:
                return False
            table[session_id]["status"] = "expired"
            return True
        try:
            resp = (
                self._db.table(_T_SESSIONS)
                .update({"status": "expired"})
                .eq("id", session_id)
                .execute()
            )
            rows = getattr(resp, "data", []) or []
            return len(rows) > 0
        except Exception:
            logger.warning("cleanup: archive_session failed", exc_info=True)
            return False

    # ── Delete ─────────────────────────────────────────────────────────────────

    def delete(self, session_id: str, confirm: bool = False) -> DeleteReport:
        """Delete all rows for the given proof session.

        Requires confirm=True to proceed — raises ValueError otherwise.

        Deletion order:
          1. skill_evidence_artifacts (JSONB path, must go first)
          2. workflow_visual_frame_evidence (TEXT column, must go explicitly)
          3. workflow_visible_evidence_events (TEXT column, must go explicitly)
          4. extension_proof_sessions (UUID PK — cascades analysis, optional,
             live_website_check_results, evidence_access_audit_events)

        After deletion, affected_pipeline_ids are reported so the caller can
        trigger an evidence_count refresh on those pipelines.
        """
        if not confirm:
            raise ValueError(
                "delete() requires confirm=True. This is a destructive operation. "
                "Call dry_run() first and write a backup with backup() before confirming."
            )

        report = DeleteReport(proof_session_id=session_id)
        report.affected_pipeline_ids = self._list_affected_pipeline_ids(session_id)

        # Step 1: skill_evidence_artifacts (JSONB path — no cascade)
        report.deleted_counts[_T_ARTIFACTS] = self._delete_artifacts(session_id, report)

        # Step 2: workflow_visual_frame_evidence (TEXT column — no cascade)
        report.deleted_counts[_T_FRAMES] = self._delete_text_table(_T_FRAMES, session_id, report)

        # Step 3: workflow_visible_evidence_events (TEXT column — no cascade)
        report.deleted_counts[_T_EVENTS] = self._delete_text_table(_T_EVENTS, session_id, report)

        # Step 4: extension_proof_sessions — cascades the UUID FK tables
        report.deleted_counts[_T_SESSIONS] = self._delete_session(session_id, report)

        return report

    def _delete_artifacts(self, session_id: str, report: DeleteReport) -> int:
        if self._is_dict_mode():
            to_delete = [
                row_id for row_id, row in self._dict_table(_T_ARTIFACTS).items()
                if (row.get("artifact_data") or {}).get("proof_session_id") == session_id
            ]
            for row_id in to_delete:
                del self._dict_table(_T_ARTIFACTS)[row_id]
            return len(to_delete)
        try:
            resp = (
                self._db.table(_T_ARTIFACTS)
                .delete()
                .filter("artifact_data->>proof_session_id", "eq", session_id)
                .execute()
            )
            rows = getattr(resp, "data", []) or []
            return len(rows)
        except Exception as exc:
            report.errors.append(f"delete {_T_ARTIFACTS} failed: {exc}")
            logger.warning("cleanup: delete %s failed", _T_ARTIFACTS, exc_info=True)
            return 0

    def _delete_text_table(self, table: str, session_id: str, report: DeleteReport) -> int:
        if self._is_dict_mode():
            to_delete = [
                row_id for row_id, row in self._dict_table(table).items()
                if str(row.get("proof_session_id", "")) == session_id
            ]
            for row_id in to_delete:
                del self._dict_table(table)[row_id]
            return len(to_delete)
        try:
            resp = (
                self._db.table(table)
                .delete()
                .eq("proof_session_id", session_id)
                .execute()
            )
            rows = getattr(resp, "data", []) or []
            return len(rows)
        except Exception as exc:
            report.errors.append(f"delete {table} failed: {exc}")
            logger.warning("cleanup: delete %s failed", table, exc_info=True)
            return 0

    def _delete_session(self, session_id: str, report: DeleteReport) -> int:
        if self._is_dict_mode():
            table = self._dict_table(_T_SESSIONS)
            if session_id in table:
                del table[session_id]
                # Also cascade-delete UUID FK tables in dict mode
                for t in (_T_ANALYSIS, _T_OPTIONAL, _T_LIVE, _T_AUDIT):
                    to_del = [
                        rid for rid, row in self._dict_table(t).items()
                        if str(row.get("proof_session_id", "")) == session_id
                    ]
                    for rid in to_del:
                        del self._dict_table(t)[rid]
                return 1
            return 0
        try:
            resp = (
                self._db.table(_T_SESSIONS)
                .delete()
                .eq("id", session_id)
                .execute()
            )
            rows = getattr(resp, "data", []) or []
            return len(rows)
        except Exception as exc:
            report.errors.append(f"delete {_T_SESSIONS} failed: {exc}")
            logger.warning("cleanup: delete %s failed", _T_SESSIONS, exc_info=True)
            return 0
