"""GitHub Proof → Skill Evidence Artifact Sync Service.

Converts an analyzed (or partially analyzed) standalone GitHub proof
submission into structured skill_evidence_artifacts linked to
skill_evidence_pipelines.

Security invariants:
  - Never store the raw analysis_snapshot, repo_metadata blob, tokens,
    signed URLs, or other unsafe metadata in artifact_data.
  - artifact_data stores a safe projection only (see _build_artifact_data).
  - Default artifact visibility: protected.
  - Default pipeline visibility (new pipelines only): protected. Existing
    pipeline visibility is always preserved.
  - GitHub evidence is treated as repo-supported evidence, not fully
    demonstrated proof: confidence_score is capped and support_status is
    never set to "strongly_supported" purely from GitHub evidence.
  - Existing (e.g. Website Proof) pipeline data is never overwritten or
    downgraded — confidence_score and support_status can only increase,
    and evidence_sources are merged rather than replaced.
  - Idempotent: safe to call multiple times for the same github_proof_id.

TODO(canonical-evidence): this sync derives Skill Graph artifacts from a
standalone ``github_proof_submissions`` snapshot only. The older GitHub
Portfolio & Proof engine also persists *precise* code-line rows in the
canonical ``skill_evidence`` table (exact file/line + ``github_highlight_url`` +
``selection_reason``), which the Work Passport Skill Report now reads first via
``github_canonical_skill_evidence_adapter.collect_canonical_github_skill_evidence``.
A future, safe enhancement is to also fold any matching canonical
``skill_evidence`` rows (by repo identity + skill) into the synced artifacts so
the Skill Graph reflects the strongest available code evidence — without ever
calling the live scanner here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.schemas.skill_evidence_pipeline import (
    SkillEvidenceArtifactCreate,
    SkillEvidencePipelineCreate,
    SkillEvidencePipelineResponse,
)
from app.services.skill_evidence_pipeline_service import SkillEvidencePipelineService
from app.services.website_proof_artifact_sync_service import _infer_category, _truncate

logger = logging.getLogger(__name__)

_GITHUB_PROOFS_TABLE = "github_proof_submissions"

# Statuses that are never synced — too early, in progress, or no longer usable.
_REJECTED_STATUSES = frozenset({"submitted", "analyzing", "failed", "archived"})

# "needs_more_evidence" is allowed as partial / needs-review evidence.
_PARTIAL_STATUSES = frozenset({"needs_more_evidence"})

_ALLOWED_STATUSES = frozenset({"analyzed"}) | _PARTIAL_STATUSES

# support_status ranking — used to avoid downgrading an existing pipeline.
_SUPPORT_RANK = {"needs_review": 0, "partially_supported": 1, "strongly_supported": 2}

# Confidence ceiling applied to GitHub-derived evidence: GitHub repo evidence
# is repo-supported, not fully demonstrated, so it can never push a skill into
# "strongly_supported" territory on its own.
_ANALYZED_CONFIDENCE_CAP = 75
_PARTIAL_CONFIDENCE_CAP = 50

# Keys that must never appear in artifact_data (defensive — _build_artifact_data
# only constructs a safe allowlist, but this guards against accidental leaks).
_UNSAFE_KEYS = frozenset({
    "analysis_snapshot", "repo_metadata",
    "storage_path", "storage_bucket", "signed_url", "signedUrl",
    "access_token", "service_role_key", "private_url", "download_url",
    "raw_frame_url", "keyframe_url", "screenshot_url", "video_url",
    "media_storage_path",
})


class GitHubProofNotFoundError(LookupError):
    """GitHub proof was not found for the scoped student."""


class GitHubProofSyncStatusError(ValueError):
    """GitHub proof status does not allow syncing to the Skill Graph yet."""


def _strip_unsafe(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k not in _UNSAFE_KEYS}


def _clean_list(values: Any) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if text:
            out.append(text)
    return list(dict.fromkeys(out))


def _iso(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _repo_display_name(row: dict[str, Any]) -> str:
    owner = row.get("repo_owner")
    name = row.get("repo_name")
    if owner and name:
        return f"{owner}/{name}"
    return str(row.get("repo_url") or "GitHub repository")


def _extract_skills(row: dict[str, Any], is_partial: bool) -> list[str]:
    """Detected skills are the primary source; submitted claims are only used
    as a fallback for partial / needs-review evidence."""
    detected = _clean_list(row.get("detected_skills") or [])
    if detected:
        return detected
    if is_partial:
        return _clean_list(row.get("submitted_skill_claims") or [])
    return []


def _build_artifact_data(row: dict[str, Any]) -> dict[str, Any]:
    repo_metadata = row.get("repo_metadata") if isinstance(row.get("repo_metadata"), dict) else {}
    evidence_files = [
        f for f in _clean_list(repo_metadata.get("evidence_files") or [])
        if "://" not in f
    ][:20]

    confidence_score = row.get("confidence_score")
    data = {
        "github_proof_id": str(row.get("id") or ""),
        "proof_session_id": str(row["proof_session_id"]) if row.get("proof_session_id") else None,
        "repo_url": str(row.get("repo_url") or ""),
        "repo_owner": row.get("repo_owner"),
        "repo_name": row.get("repo_name"),
        "default_branch": row.get("default_branch") or "main",
        "submitted_skill_claims": _clean_list(row.get("submitted_skill_claims") or []),
        "detected_skills": _clean_list(row.get("detected_skills") or []),
        "evidence_strength": row.get("evidence_strength"),
        "confidence_score": int(confidence_score) if confidence_score is not None else None,
        "public_safe_summary": _truncate(str(row.get("public_safe_summary") or ""), 400),
        "detected_stack": _clean_list(repo_metadata.get("detected_stack") or [])[:20],
        "detected_features": _clean_list(repo_metadata.get("detected_features") or [])[:20],
        "evidence_files": evidence_files,
        "risk_flags": _clean_list(row.get("risk_flags") or []),
        "missing_evidence": _clean_list(row.get("missing_evidence") or []),
        "last_analyzed_at": _iso(row.get("last_analyzed_at")),
    }
    return _strip_unsafe(data)


def _build_github_evidence_source(row: dict[str, Any]) -> dict[str, Any]:
    confidence = int(row.get("confidence_score") or 0)
    status = str(row.get("status") or "")
    return {
        "key": "github",
        "label": "GitHub Repository",
        "status": "supported" if (status == "analyzed" and confidence >= 60) else "partial",
        "score": confidence,
        "reason": _truncate(str(row.get("public_safe_summary") or ""), 150),
    }


def _merge_evidence_sources(existing_sources: list[Any], github_source: dict[str, Any]) -> list[Any]:
    merged = [
        s for s in (existing_sources or [])
        if not (isinstance(s, dict) and s.get("key") == "github")
    ]
    merged.append(github_source)
    return merged


def _merged_support_status(existing: SkillEvidencePipelineResponse | None, new_status: str) -> str:
    if existing is None:
        return new_status
    existing_rank = _SUPPORT_RANK.get(existing.support_status, 0)
    new_rank = _SUPPORT_RANK.get(new_status, 0)
    return existing.support_status if existing_rank >= new_rank else new_status


def _skill_confidence_for_github(row: dict[str, Any], is_partial: bool) -> int:
    score = int(row.get("confidence_score") or 0)
    cap = _PARTIAL_CONFIDENCE_CAP if is_partial else _ANALYZED_CONFIDENCE_CAP
    return max(0, min(score, cap))


def _support_status_for_github(is_partial: bool) -> str:
    return "needs_review" if is_partial else "partially_supported"


def _build_recruiter_summary(skill: str, row: dict[str, Any]) -> str:
    repo_name = _repo_display_name(row)
    summary = f"GitHub repository ({repo_name}) provides repo-supported evidence for {skill}."
    public_safe = str(row.get("public_safe_summary") or "")
    if public_safe:
        summary += f" {_truncate(public_safe, 200)}"
    return _truncate(summary, 400)


def _build_student_summary(skill: str, row: dict[str, Any]) -> str:
    repo_name = _repo_display_name(row)
    return _truncate(
        f"Your {skill} evidence now includes the GitHub repository {repo_name}. "
        "This is repo-supported evidence — add a live demo or workflow recording "
        "for stronger proof.",
        400,
    )


def _build_pipeline_payload(
    skill: str,
    row: dict[str, Any],
    existing: SkillEvidencePipelineResponse | None,
    github_source: dict[str, Any],
    is_partial: bool,
) -> SkillEvidencePipelineCreate:
    new_confidence = _skill_confidence_for_github(row, is_partial)
    new_support = _support_status_for_github(is_partial)

    if existing is not None:
        skill_name = existing.skill_name
        confidence_score = max(existing.confidence_score, new_confidence)
        support_status = _merged_support_status(existing, new_support)
        evidence_sources = _merge_evidence_sources(existing.evidence_sources, github_source)
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
        confidence_score = new_confidence
        support_status = new_support
        evidence_sources = [github_source]
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
class GitHubProofSyncResult:
    github_proof_id: str
    user_id: str
    skills_synced: list[str] = field(default_factory=list)
    artifacts_created: int = 0
    pipelines_upserted: int = 0
    already_synced: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "github_proof_id": self.github_proof_id,
            "user_id": self.user_id,
            "skills_synced": self.skills_synced,
            "artifacts_created": self.artifacts_created,
            "pipelines_upserted": self.pipelines_upserted,
            "already_synced": self.already_synced,
            "errors": self.errors,
        }


class GitHubProofArtifactSyncService:
    """Converts an analyzed GitHub proof into skill_evidence_artifacts.

    Reads from github_proof_submissions using ``db``.
    Writes to skill_evidence_pipelines / skill_evidence_artifacts using ``pipeline_db``.
    """

    def __init__(self, db: Any, pipeline_db: Any) -> None:
        self._db = db
        self._pipeline_svc = SkillEvidencePipelineService(pipeline_db)

    # ── Data loaders ──────────────────────────────────────────────────────────

    def _load_proof(self, user_id: str, github_proof_id: str) -> dict[str, Any] | None:
        if isinstance(self._db, dict):
            row = self._db.get(_GITHUB_PROOFS_TABLE, {}).get(github_proof_id)
            if not row or str(row.get("user_id")) != user_id:
                return None
            return row
        try:
            resp = (
                self._db.table(_GITHUB_PROOFS_TABLE)
                .select("*")
                .eq("id", github_proof_id)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            return rows[0] if rows else None
        except Exception:
            logger.warning("github sync: proof load failed", exc_info=True)
            return None

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

    def _artifact_exists_for_proof(self, user_id: str, github_proof_id: str) -> bool:
        try:
            return self._pipeline_svc.has_artifact_matching(
                user_id, github_proof_id=github_proof_id
            )
        except Exception:
            pass
        return False

    # ── Main sync ─────────────────────────────────────────────────────────────

    def sync(self, user_id: str, github_proof_id: str) -> GitHubProofSyncResult:
        """Convert an analyzed GitHub proof into skill_evidence_artifacts.

        Raises:
            GitHubProofNotFoundError: proof missing or owned by another user.
            GitHubProofSyncStatusError: proof status does not allow syncing yet.

        Idempotent: returns early with already_synced=True if an artifact for
        this github_proof_id already exists.
        """
        row = self._load_proof(user_id, github_proof_id)
        if row is None:
            raise GitHubProofNotFoundError(github_proof_id)

        status = str(row.get("status") or "")
        if status not in _ALLOWED_STATUSES:
            raise GitHubProofSyncStatusError(status)

        result = GitHubProofSyncResult(github_proof_id=github_proof_id, user_id=user_id)

        if self._artifact_exists_for_proof(user_id, github_proof_id):
            result.already_synced = True
            return result

        is_partial = status in _PARTIAL_STATUSES
        skills = _extract_skills(row, is_partial)
        if not skills:
            result.errors.append("No skills detected from GitHub analysis — nothing to sync.")
            return result

        artifact_data = _build_artifact_data(row)
        github_source = _build_github_evidence_source(row)
        artifact_confidence = _skill_confidence_for_github(row, is_partial)
        repo_name = _repo_display_name(row)

        for skill in skills:
            try:
                existing = self._existing_pipeline(user_id, skill)
                payload = _build_pipeline_payload(skill, row, existing, github_source, is_partial)
                pipeline = self._pipeline_svc.upsert_pipeline(user_id, payload)
                result.pipelines_upserted += 1

                self._pipeline_svc.add_artifact(
                    user_id,
                    SkillEvidenceArtifactCreate(
                        pipeline_id=pipeline.id,
                        proof_session_id=None,
                        source_type="github",
                        source_title=f"GitHub Repository — {repo_name}",
                        project_name=repo_name,
                        visibility="protected",
                        confidence_score=artifact_confidence,
                        relevance_to_skill=f"GitHub repository evidence supports {skill}",
                        proof_reason=_truncate(str(row.get("public_safe_summary") or ""), 200),
                        artifact_data=artifact_data,
                    ),
                )
                result.artifacts_created += 1
                result.skills_synced.append(payload.skill_name)
            except Exception as exc:
                logger.warning("github sync: failed for skill %r: %s", skill, exc)
                result.errors.append(f"sync failed for {skill!r}: {exc}")

        return result
