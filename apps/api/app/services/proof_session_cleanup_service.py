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
  proof_project_relationships       proof_type='website' AND proof_id = session_id (TEXT —
                                    migration 058; written at session CREATE time, so an
                                    abandoned session still carries a directly_linked edge)
  skill_evidence                    id = extension_proof_sessions.skill_evidence_id (the
                                    creation-time evidence stub; resolved from the session
                                    row BEFORE the session itself is deleted)

Archive vs delete
-----------------
  • extension_proof_sessions has a status column — setting status='expired' is the
    soft-archive path.  Archiving also DETACHES the session's project linkage:
    proof_project_relationships rows are downgraded to ``vault_only`` (project id
    preserved in provenance) and the session metadata's project edge is moved to
    ``detached_project_id``, so no surface keeps presenting the session as
    project-linked.  Nothing is deleted — the skill_evidence stub, text-column
    tables, and synced artifacts all remain.
  • Full delete removes everything, including text-column tables, synced artifacts,
    relationship rows, and the session's skill_evidence stub.
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
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# ── Table names ────────────────────────────────────────────────────────────────

_T_SESSIONS      = "extension_proof_sessions"
_T_ANALYSIS      = "workflow_analysis_results"
_T_FRAMES        = "workflow_visual_frame_evidence"
_T_EVENTS        = "workflow_visible_evidence_events"
_T_OPTIONAL      = "optional_evidence_submissions"
_T_LIVE          = "live_website_check_results"
_T_ARTIFACTS     = "skill_evidence_artifacts"
_T_AUDIT         = "evidence_access_audit_events"
_T_RELATIONSHIPS = "proof_project_relationships"
_T_SKILL_EVIDENCE = "skill_evidence"

_ARCHIVE_SOURCE = "proof_session_cleanup_service.archive_session"


def _now() -> str:
    return datetime.now(UTC).isoformat()


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
            row for row in self._dict_table_readonly(table).values()
            if str(row.get("proof_session_id", "")) == session_id
        ]

    def _dict_rows_uuid_matching(self, table: str, session_id: str) -> list[dict[str, Any]]:
        """Return rows from a UUID proof_session_id column (analysis, optional, live, audit)."""
        return [
            row for row in self._dict_table_readonly(table).values()
            if str(row.get("proof_session_id", "")) == session_id
        ]

    def _dict_artifacts_matching(self, session_id: str) -> list[dict[str, Any]]:
        """Return skill_evidence_artifacts where artifact_data->>'proof_session_id' == session_id."""
        return [
            row for row in self._dict_table_readonly(_T_ARTIFACTS).values()
            if (row.get("artifact_data") or {}).get("proof_session_id") == session_id
        ]

    def _dict_table_readonly(self, table: str) -> dict[str, dict[str, Any]]:
        """Read a dict-mode table WITHOUT creating it — dry_run/backup must not mutate."""
        rows = self._db.get(table)
        return rows if isinstance(rows, dict) else {}

    # ── Post-058 dependents: relationship rows + creation-time skill_evidence ──

    def _fetch_relationship_rows(self, session_id: str) -> list[dict[str, Any]]:
        """proof_project_relationships rows for this website session (proof_id TEXT)."""
        if self._is_dict_mode():
            return [
                row for row in self._dict_table_readonly(_T_RELATIONSHIPS).values()
                if str(row.get("proof_type") or "") == "website"
                and str(row.get("proof_id") or "") == session_id
            ]
        try:
            resp = (
                self._db.table(_T_RELATIONSHIPS)
                .select("*")
                .eq("proof_type", "website")
                .eq("proof_id", session_id)
                .execute()
            )
            return getattr(resp, "data", []) or []
        except Exception:
            # Pre-058 database — the table may not exist.
            logger.info("cleanup: %s unavailable (pre-058 database?)", _T_RELATIONSHIPS)
            return []

    def _session_skill_evidence_id(self, session_id: str) -> str:
        """The session's creation-time skill_evidence stub id, or ''.

        Must be resolved from the session row BEFORE the session is deleted.
        """
        if self._is_dict_mode():
            row = self._dict_table_readonly(_T_SESSIONS).get(session_id) or {}
            return str(row.get("skill_evidence_id") or "")
        try:
            resp = (
                self._db.table(_T_SESSIONS)
                .select("skill_evidence_id")
                .eq("id", session_id)
                .execute()
            )
            rows = getattr(resp, "data", []) or []
            return str((rows[0] if rows else {}).get("skill_evidence_id") or "")
        except Exception:
            logger.warning("cleanup: read skill_evidence_id failed", exc_info=True)
            return ""

    def _fetch_skill_evidence_rows(self, session_id: str) -> list[dict[str, Any]]:
        """The skill_evidence stub row referenced by the session, if any."""
        evidence_id = self._session_skill_evidence_id(session_id)
        if not evidence_id:
            return []
        if self._is_dict_mode():
            row = self._dict_table_readonly(_T_SKILL_EVIDENCE).get(evidence_id)
            return [row] if isinstance(row, dict) else []
        try:
            resp = (
                self._db.table(_T_SKILL_EVIDENCE)
                .select("*")
                .eq("id", evidence_id)
                .execute()
            )
            return getattr(resp, "data", []) or []
        except Exception:
            logger.warning("cleanup: fetch %s failed", _T_SKILL_EVIDENCE, exc_info=True)
            return []

    # ── Count helpers ──────────────────────────────────────────────────────────

    def _count_session(self, session_id: str) -> int:
        if self._is_dict_mode():
            return 1 if session_id in self._dict_table_readonly(_T_SESSIONS) else 0
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
        report.counts[_T_RELATIONSHIPS] = len(self._fetch_relationship_rows(session_id))
        report.counts[_T_SKILL_EVIDENCE] = len(self._fetch_skill_evidence_rows(session_id))

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
            _T_RELATIONSHIPS: self._fetch_relationship_rows(session_id),
            _T_SKILL_EVIDENCE: self._fetch_skill_evidence_rows(session_id),
        }

    def _fetch_session_rows(self, session_id: str) -> list[dict[str, Any]]:
        if self._is_dict_mode():
            row = self._dict_table_readonly(_T_SESSIONS).get(session_id)
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
        """Soft-archive: set status='expired' AND detach the project linkage.

        Website Proof creation writes its project edge (session
        ``metadata.project_id`` + a ``proof_project_relationships`` row) before
        any recording exists, so merely expiring an abandoned session would
        leave it presented as project-linked forever. Archiving therefore also:

          • moves the session metadata's ``project_id`` to
            ``detached_project_id`` and sets
            ``project_relationship_state='vault_only'`` (with an explicit
            detach provenance trail), and
          • downgrades the session's relationship rows to ``vault_only``,
            clearing ``project_id`` while preserving the original edge in
            ``provenance`` (``detached_from_project_id`` /
            ``previous_relationship_state``).

        Nothing is deleted — not the session, the skill_evidence stub, the
        text-column tables, nor synced artifacts. Returns True if a session row
        was found and updated, False otherwise.
        """
        now = _now()
        if self._is_dict_mode():
            table = self._dict_table(_T_SESSIONS)
            if session_id not in table:
                return False
            row = table[session_id]
            row["status"] = "expired"
            row["updated_at"] = now
            metadata = row.get("metadata")
            detached = self._detached_session_metadata(metadata, now)
            if detached != (metadata if isinstance(metadata, dict) else {}):
                row["metadata"] = detached
            self._detach_relationship_rows(session_id, now)
            return True
        try:
            session_rows = self._fetch_session_rows(session_id)
            if not session_rows:
                return False
            updates: dict[str, Any] = {"status": "expired", "updated_at": now}
            metadata = session_rows[0].get("metadata")
            detached = self._detached_session_metadata(metadata, now)
            if detached != (metadata if isinstance(metadata, dict) else {}):
                updates["metadata"] = detached
            resp = (
                self._db.table(_T_SESSIONS)
                .update(updates)
                .eq("id", session_id)
                .execute()
            )
            rows = getattr(resp, "data", []) or []
            if not rows:
                return False
            self._detach_relationship_rows(session_id, now)
            return True
        except Exception:
            logger.warning("cleanup: archive_session failed", exc_info=True)
            return False

    @staticmethod
    def _detached_session_metadata(metadata: Any, now: str) -> dict[str, Any]:
        """Session metadata with the project edge moved into a detach trail."""
        md = dict(metadata) if isinstance(metadata, dict) else {}
        project_id = str(md.get("project_id") or "")
        was_linked = bool(project_id) or (
            str(md.get("project_relationship_state") or "") == "directly_linked"
        )
        if not was_linked:
            return md
        md.pop("project_id", None)
        if project_id:
            md["detached_project_id"] = project_id
        md["project_relationship_state"] = "vault_only"
        md["project_detached_at"] = now
        md["project_detach_source"] = _ARCHIVE_SOURCE
        return md

    def _detach_relationship_rows(self, session_id: str, now: str) -> int:
        """Downgrade this session's relationship rows to detached ``vault_only``.

        The original edge is preserved in ``provenance`` so a deliberate
        re-attach (or audit) can always reconstruct what was detached.
        """
        detached = 0
        if self._is_dict_mode():
            for row in self._dict_table_readonly(_T_RELATIONSHIPS).values():
                if (
                    str(row.get("proof_type") or "") != "website"
                    or str(row.get("proof_id") or "") != session_id
                ):
                    continue
                if str(row.get("relationship_state") or "") == "vault_only" and not row.get("project_id"):
                    continue
                provenance = dict(row.get("provenance") or {})
                provenance.update(
                    {
                        "detached_from_project_id": str(row.get("project_id") or ""),
                        "previous_relationship_state": str(row.get("relationship_state") or ""),
                        "detached_by": _ARCHIVE_SOURCE,
                        "detached_at": now,
                    }
                )
                row.update(
                    {
                        "relationship_state": "vault_only",
                        "project_id": None,
                        "confirmed_by_user": False,
                        "provenance": provenance,
                        "updated_at": now,
                    }
                )
                detached += 1
            return detached
        for row in self._fetch_relationship_rows(session_id):
            if str(row.get("relationship_state") or "") == "vault_only" and not row.get("project_id"):
                continue
            provenance = dict(row.get("provenance") or {})
            provenance.update(
                {
                    "detached_from_project_id": str(row.get("project_id") or ""),
                    "previous_relationship_state": str(row.get("relationship_state") or ""),
                    "detached_by": _ARCHIVE_SOURCE,
                    "detached_at": now,
                }
            )
            try:
                (
                    self._db.table(_T_RELATIONSHIPS)
                    .update(
                        {
                            "relationship_state": "vault_only",
                            "project_id": None,
                            "confirmed_by_user": False,
                            "provenance": provenance,
                            "updated_at": now,
                        }
                    )
                    .eq("id", row.get("id"))
                    .execute()
                )
                detached += 1
            except Exception:
                logger.warning(
                    "cleanup: detach relationship row %s failed", row.get("id"), exc_info=True
                )
        return detached

    # ── Delete ─────────────────────────────────────────────────────────────────

    def delete(self, session_id: str, confirm: bool = False) -> DeleteReport:
        """Delete all rows for the given proof session.

        Requires confirm=True to proceed — raises ValueError otherwise.

        Deletion order:
          1. skill_evidence_artifacts (JSONB path, must go first)
          2. workflow_visual_frame_evidence (TEXT column, must go explicitly)
          3. workflow_visible_evidence_events (TEXT column, must go explicitly)
          4. proof_project_relationships (TEXT proof_id — no cascade)
          5. extension_proof_sessions (UUID PK — cascades analysis, optional,
             live_website_check_results, evidence_access_audit_events)
          6. skill_evidence stub (id captured from the session row in step 0 —
             deleted last so a session FK on skill_evidence_id can never block)

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

        # Step 0: capture the creation-time skill_evidence stub id BEFORE the
        # session row (its only pointer) is deleted.
        skill_evidence_id = self._session_skill_evidence_id(session_id)

        # Step 1: skill_evidence_artifacts (JSONB path — no cascade)
        report.deleted_counts[_T_ARTIFACTS] = self._delete_artifacts(session_id, report)

        # Step 2: workflow_visual_frame_evidence (TEXT column — no cascade)
        report.deleted_counts[_T_FRAMES] = self._delete_text_table(_T_FRAMES, session_id, report)

        # Step 3: workflow_visible_evidence_events (TEXT column — no cascade)
        report.deleted_counts[_T_EVENTS] = self._delete_text_table(_T_EVENTS, session_id, report)

        # Step 4: proof_project_relationships (TEXT proof_id — no cascade)
        report.deleted_counts[_T_RELATIONSHIPS] = self._delete_relationship_rows(
            session_id, report
        )

        # Step 5: extension_proof_sessions — cascades the UUID FK tables
        report.deleted_counts[_T_SESSIONS] = self._delete_session(session_id, report)

        # Step 6: the session's creation-time skill_evidence stub (after the
        # session so the skill_evidence_id FK cannot block the delete)
        report.deleted_counts[_T_SKILL_EVIDENCE] = self._delete_skill_evidence(
            skill_evidence_id, report
        )

        return report

    def _delete_relationship_rows(self, session_id: str, report: DeleteReport) -> int:
        if self._is_dict_mode():
            table = self._dict_table_readonly(_T_RELATIONSHIPS)
            to_delete = [
                row_id for row_id, row in table.items()
                if str(row.get("proof_type") or "") == "website"
                and str(row.get("proof_id") or "") == session_id
            ]
            for row_id in to_delete:
                del table[row_id]
            return len(to_delete)
        try:
            resp = (
                self._db.table(_T_RELATIONSHIPS)
                .delete()
                .eq("proof_type", "website")
                .eq("proof_id", session_id)
                .execute()
            )
            rows = getattr(resp, "data", []) or []
            return len(rows)
        except Exception as exc:
            # Pre-058 database: nothing to delete is not an error.
            logger.info("cleanup: delete %s skipped: %s", _T_RELATIONSHIPS, type(exc).__name__)
            return 0

    def _delete_skill_evidence(self, skill_evidence_id: str, report: DeleteReport) -> int:
        if not skill_evidence_id:
            return 0
        if self._is_dict_mode():
            table = self._dict_table_readonly(_T_SKILL_EVIDENCE)
            if skill_evidence_id in table:
                del table[skill_evidence_id]
                return 1
            return 0
        try:
            resp = (
                self._db.table(_T_SKILL_EVIDENCE)
                .delete()
                .eq("id", skill_evidence_id)
                .execute()
            )
            rows = getattr(resp, "data", []) or []
            return len(rows)
        except Exception as exc:
            report.errors.append(f"delete {_T_SKILL_EVIDENCE} failed: {exc}")
            logger.warning("cleanup: delete %s failed", _T_SKILL_EVIDENCE, exc_info=True)
            return 0

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
