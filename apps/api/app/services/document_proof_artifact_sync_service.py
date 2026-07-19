"""Document Proof → Skill Evidence Artifact Sync Service.

Converts an analyzed standalone document/certificate submission
(optional_evidence_submissions, proof_session_id IS NULL) into structured
skill_evidence_artifacts linked to skill_evidence_pipelines.

Security invariants:
  - Never store raw_text, extracted text previews, file bytes, storage paths,
    signed URLs, or tokens in artifact_data.
  - artifact_data stores a safe projection only (see _build_artifact_data).
  - Default artifact visibility: protected.
  - Default pipeline visibility (new pipelines only): protected. Existing
    pipeline visibility is always preserved.
  - Document evidence is supporting evidence only: confidence_score is
    capped and support_status is never "strongly_supported" purely from a
    document/certificate submission — only "partially_supported" or
    "needs_review".
  - Existing (e.g. Website/GitHub Proof) pipeline data is never overwritten
    or downgraded — confidence_score and support_status can only increase,
    and evidence_sources are merged rather than replaced.
  - Idempotent: safe to call multiple times for the same document_evidence_id.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.schemas.skill_evidence_pipeline import (
    SkillEvidenceArtifactCreate,
    SkillEvidencePipelineCreate,
    SkillEvidencePipelineResponse,
)
from app.services.optional_evidence_service import OptionalEvidenceService
from app.services.skill_evidence_pipeline_service import SkillEvidencePipelineService
from app.services.website_proof_artifact_sync_service import _infer_category, _truncate

logger = logging.getLogger(__name__)

# Only fully-analyzed documents (with at least one detected skill) are synced.
_ALLOWED_STATUSES = frozenset({"analyzed"})

# support_status ranking — used to avoid downgrading an existing pipeline.
_SUPPORT_RANK = {"needs_review": 0, "partially_supported": 1, "strongly_supported": 2}

# Confidence ceiling applied to document-derived evidence: a document is
# supporting evidence, not fully demonstrated proof, so it can never push a
# skill into "strongly_supported" territory on its own.
_CONFIDENCE_BY_LEVEL = {"high": 65, "medium": 55, "low": 45}
_DEFAULT_CONFIDENCE = 45

# Keys that must never appear in artifact_data (defensive — _build_artifact_data
# only constructs a safe allowlist, but this guards against accidental leaks).
_UNSAFE_KEYS = frozenset({
    "raw_text", "extracted_text_preview",
    "storage_path", "storage_bucket", "signed_url", "signedUrl",
    "access_token", "service_role_key", "private_url", "download_url",
})


class DocumentProofNotFoundError(LookupError):
    """Document proof evidence was not found for the scoped student."""


class DocumentProofSyncStatusError(ValueError):
    """Document proof status does not allow syncing to the Skill Graph yet."""


def _strip_unsafe(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k not in _UNSAFE_KEYS}


def _document_title(row: dict[str, Any]) -> str:
    analysis_json = row.get("analysis_json") or {}
    title = analysis_json.get("title") or row.get("file_path") or "Document"
    return _truncate(str(title), 120)


def _extract_skills(row: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in row.get("evidence_objects") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("skill_name") or "").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


def _matched_evidence(row: dict[str, Any], skill: str) -> list[dict[str, Any]]:
    skill_lower = skill.strip().lower()
    return [
        e for e in (row.get("evidence_objects") or [])
        if isinstance(e, dict) and str(e.get("skill_name") or "").strip().lower() == skill_lower
    ]


def _confidence_for_matched(matched: list[dict[str, Any]]) -> int:
    levels = {str(e.get("confidence") or "").lower() for e in matched}
    for level in ("high", "medium", "low"):
        if level in levels:
            return _CONFIDENCE_BY_LEVEL[level]
    return _DEFAULT_CONFIDENCE


def _evidence_quality(matched: list[dict[str, Any]]) -> str:
    levels = {str(e.get("confidence") or "").lower() for e in matched}
    for level in ("high", "medium", "low"):
        if level in levels:
            return level
    return "low"


def _build_artifact_data(row: dict[str, Any], skill: str, matched: list[dict[str, Any]], source_type_label: str) -> dict[str, Any]:
    analysis_json = row.get("analysis_json") or {}
    sections = [_truncate(str(e.get("snippet") or ""), 200) for e in matched[:3]]
    page_numbers = sorted({
        int(e["page_number"]) for e in matched
        if e.get("page_number") is not None
    })
    line_refs = [
        {"line_start": e.get("line_start"), "line_end": e.get("line_end")}
        for e in matched
        if e.get("line_start") is not None
    ][:5]

    data: dict[str, Any] = {
        "document_evidence_id": str(row.get("id") or ""),
        "source_type": source_type_label,
        "document_title": _document_title(row),
        "document_type": analysis_json.get("file_type") or ("text" if not row.get("file_path") else ""),
        "extracted_sections_summary": sections,
        "matched_skills": [skill],
        "page_numbers": page_numbers,
        "line_refs": line_refs,
        "extraction_status": str(row.get("status") or ""),
        "evidence_quality": _evidence_quality(matched),
    }
    if row.get("source_type") == "certificate_transcript":
        data["issuer"] = analysis_json.get("issuer")
        data["title"] = analysis_json.get("title")
        data["date"] = analysis_json.get("date")
    return _strip_unsafe(data)


def _build_document_evidence_source(row: dict[str, Any], skill: str, confidence: int) -> dict[str, Any]:
    title = _document_title(row)
    return {
        "key": "document",
        "label": "Document",
        "status": "partial",
        "score": confidence,
        "reason": _truncate(f"Document '{title}' provides supporting evidence for {skill}.", 200),
    }


def _merge_evidence_sources(existing_sources: list[Any], document_source: dict[str, Any]) -> list[Any]:
    merged = [
        s for s in (existing_sources or [])
        if not (isinstance(s, dict) and s.get("key") == "document")
    ]
    merged.append(document_source)
    return merged


def _merged_support_status(existing: SkillEvidencePipelineResponse | None, new_status: str) -> str:
    if existing is None:
        return new_status
    existing_rank = _SUPPORT_RANK.get(existing.support_status, 0)
    new_rank = _SUPPORT_RANK.get(new_status, 0)
    return existing.support_status if existing_rank >= new_rank else new_status


def _build_recruiter_summary(skill: str, row: dict[str, Any]) -> str:
    title = _document_title(row)
    return _truncate(
        f"A submitted document ({title}) provides supporting evidence for {skill}.", 400
    )


def _build_student_summary(skill: str, row: dict[str, Any]) -> str:
    return _truncate(
        f"Your {skill} evidence now includes a supporting document. Add a live demo, "
        "GitHub repository, or recorded workflow for stronger proof.",
        400,
    )


def _build_pipeline_payload(
    skill: str,
    row: dict[str, Any],
    existing: SkillEvidencePipelineResponse | None,
    document_source: dict[str, Any],
    confidence: int,
) -> SkillEvidencePipelineCreate:
    new_support = "partially_supported"

    if existing is not None:
        skill_name = existing.skill_name
        confidence_score = max(existing.confidence_score, confidence)
        support_status = _merged_support_status(existing, new_support)
        evidence_sources = _merge_evidence_sources(existing.evidence_sources, document_source)
        evidence_count = max(existing.evidence_count + 1, len(evidence_sources))
        skill_category = existing.skill_category or _infer_category(skill)
        strongest_proof = existing.strongest_proof
        weakest_proof = existing.weakest_proof
        missing_evidence = existing.missing_evidence
        next_actions = existing.next_actions
        recruiter_summary = existing.recruiter_summary or _build_recruiter_summary(skill, row)
        student_summary = existing.student_summary or _build_student_summary(skill, row)
        visibility_status = existing.visibility_status
    else:
        skill_name = skill
        confidence_score = confidence
        support_status = new_support
        evidence_sources = [document_source]
        evidence_count = len(evidence_sources)
        skill_category = _infer_category(skill)
        strongest_proof = {}
        weakest_proof = {}
        missing_evidence = []
        next_actions = []
        recruiter_summary = _build_recruiter_summary(skill, row)
        student_summary = _build_student_summary(skill, row)
        visibility_status = "protected"

    return SkillEvidencePipelineCreate(
        skill_name=skill_name,
        skill_category=skill_category,
        confidence_score=confidence_score,
        support_status=support_status,
        evidence_count=evidence_count,
        strongest_proof=strongest_proof,
        weakest_proof=weakest_proof,
        missing_evidence=missing_evidence,
        next_actions=next_actions,
        evidence_sources=evidence_sources,
        recruiter_summary=recruiter_summary,
        student_summary=student_summary,
        visibility_status=visibility_status,
    )


@dataclass
class DocumentProofSyncResult:
    document_evidence_id: str
    user_id: str
    skills_synced: list[str] = field(default_factory=list)
    artifacts_created: int = 0
    pipelines_upserted: int = 0
    already_synced: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_evidence_id": self.document_evidence_id,
            "user_id": self.user_id,
            "skills_synced": self.skills_synced,
            "artifacts_created": self.artifacts_created,
            "pipelines_upserted": self.pipelines_upserted,
            "already_synced": self.already_synced,
            "errors": self.errors,
        }


class DocumentProofArtifactSyncService:
    """Converts an analyzed standalone document proof into skill_evidence_artifacts.

    Reads from optional_evidence_submissions using ``db``.
    Writes to skill_evidence_pipelines / skill_evidence_artifacts using ``pipeline_db``.
    """

    def __init__(self, db: Any, pipeline_db: Any) -> None:
        self._db = db
        self._pipeline_svc = SkillEvidencePipelineService(pipeline_db)

    # ── Existing pipeline lookup ─────────────────────────────────────────────

    def _existing_pipeline(self, user_id: str, skill_name: str) -> SkillEvidencePipelineResponse | None:
        try:
            # Rows only — pulling every pipeline's artifacts per skill made this
            # an N×M query storm on real databases.
            for p in self._pipeline_svc.list_pipeline_rows_for_student(user_id):
                if p.skill_name.strip().lower() == skill_name.strip().lower():
                    return p
        except Exception:
            pass
        return None

    # ── Idempotency check ─────────────────────────────────────────────────────

    def _artifact_exists_for_evidence(self, user_id: str, document_evidence_id: str) -> bool:
        try:
            return self._pipeline_svc.has_artifact_matching(
                user_id, document_evidence_id=document_evidence_id
            )
        except Exception:
            pass
        return False

    # ── Main sync ─────────────────────────────────────────────────────────────

    def sync(self, user_id: str, document_evidence_id: str) -> DocumentProofSyncResult:
        """Convert an analyzed document proof into skill_evidence_artifacts.

        Raises:
            DocumentProofNotFoundError: evidence missing or owned by another user.
            DocumentProofSyncStatusError: status does not allow syncing yet.

        Idempotent: returns early with already_synced=True if an artifact for
        this document_evidence_id already exists.
        """
        row = OptionalEvidenceService(self._db).get_by_id(user_id=user_id, evidence_id=document_evidence_id)
        if row is None:
            raise DocumentProofNotFoundError(document_evidence_id)

        if row.get("proof_session_id") is not None:
            raise DocumentProofNotFoundError(document_evidence_id)

        if row.get("source_type") not in {"document", "certificate_transcript"}:
            raise DocumentProofNotFoundError(document_evidence_id)

        proof_status = str(row.get("status") or "")
        if proof_status not in _ALLOWED_STATUSES:
            raise DocumentProofSyncStatusError(proof_status)

        result = DocumentProofSyncResult(document_evidence_id=document_evidence_id, user_id=user_id)

        if self._artifact_exists_for_evidence(user_id, document_evidence_id):
            result.already_synced = True
            return result

        skills = _extract_skills(row)
        if not skills:
            result.errors.append("No skills detected from document evidence — nothing to sync.")
            return result

        source_type_label = "certificate" if row.get("source_type") == "certificate_transcript" else "document"
        doc_title = _document_title(row)

        for skill in skills:
            try:
                matched = _matched_evidence(row, skill)
                confidence = _confidence_for_matched(matched)
                existing = self._existing_pipeline(user_id, skill)
                document_source = _build_document_evidence_source(row, skill, confidence)
                payload = _build_pipeline_payload(skill, row, existing, document_source, confidence)
                pipeline = self._pipeline_svc.upsert_pipeline(user_id, payload)
                result.pipelines_upserted += 1

                artifact_data = _build_artifact_data(row, skill, matched, source_type_label)
                self._pipeline_svc.add_artifact(
                    user_id,
                    SkillEvidenceArtifactCreate(
                        pipeline_id=pipeline.id,
                        proof_session_id=None,
                        source_type=source_type_label,
                        source_title=f"Document — {doc_title}",
                        project_name="Document Proof",
                        visibility="protected",
                        confidence_score=confidence,
                        relevance_to_skill=f"Document evidence supports {skill}",
                        proof_reason=_truncate("; ".join(artifact_data["extracted_sections_summary"]), 200),
                        artifact_data=artifact_data,
                    ),
                )
                result.artifacts_created += 1
                result.skills_synced.append(payload.skill_name)
            except Exception as exc:
                logger.warning("document proof sync: failed for skill %r: %s", skill, exc)
                result.errors.append(f"sync failed for {skill!r}: {exc}")

        return result
