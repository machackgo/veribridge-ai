"""Project Defense → Skill Evidence Artifact Sync Service (Phase 1).

Converts a deterministically-analyzed individual Project Defense session
(vbr_verification_sessions.telemetry.project_defense_analysis) into
structured skill_evidence_artifacts linked to skill_evidence_pipelines.

Security invariants:
  - Never store the full transcript, video paths, signed URLs, storage
    paths, raw VBR telemetry, raw document text, raw GitHub analysis
    snapshots, file bytes, tokens, or full metadata blobs in artifact_data.
  - artifact_data stores a safe projection only (see ``sync``).
  - Default artifact visibility: protected.
  - Default pipeline visibility (new pipelines only): protected. Existing
    pipeline visibility is always preserved.
  - Project Defense evidence is explanation/ownership evidence only:
    confidence_score is capped conservatively and support_status is never
    "strongly_supported" purely from a project defense — only
    "partially_supported" or "needs_review".
  - Existing (e.g. Website/GitHub Proof) pipeline data is never overwritten
    or downgraded — confidence_score and support_status can only increase,
    and evidence_sources are merged rather than replaced.
  - Idempotent: safe to call multiple times for the same session_id.
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
from app.services.skill_evidence_pipeline_service import SkillEvidencePipelineService
from app.services.vbr_project_defense import effective_claimed_skills, merge_owned_project
from app.services.vbr_session_recording import get_session
from app.services.website_proof_artifact_sync_service import _infer_category, _truncate

logger = logging.getLogger(__name__)

_PROJECTS_TABLE = "vbr_projects"
_TRANSCRIPTS_TABLE = "vbr_transcripts"
_QUESTIONS_TABLE = "vbr_session_questions"

# support_status ranking — used to avoid downgrading an existing pipeline.
_SUPPORT_RANK = {"needs_review": 0, "partially_supported": 1, "strongly_supported": 2}

# Confidence ceiling applied to project-defense-derived evidence: an
# explanation is supporting/ownership evidence, not fully demonstrated proof,
# so it can never push a skill into "strongly_supported" territory on its own.
_CONFIDENCE_CAP = 50

# Max safe video evidence chip references included per skill in artifact_data.
_MAX_VIDEO_CHIPS_PER_SKILL = 3

# Keys that must never appear in artifact_data (defensive — the artifact_data
# below only constructs a safe allowlist, but this guards against accidental leaks).
_UNSAFE_KEYS = frozenset({
    "full_transcript", "transcript_text", "refined_transcript",
    "video_path", "storage_path", "storage_bucket", "signed_url", "signedUrl",
    "access_token", "service_role_key", "private_url", "download_url",
    "telemetry", "metadata", "analysis_snapshot",
})


class ProjectDefenseNotFoundError(LookupError):
    """Project defense session was not found for the scoped student."""


class ProjectDefenseNotAnalyzedError(ValueError):
    """The session has no project defense analysis to sync yet."""


def _strip_unsafe(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k not in _UNSAFE_KEYS}


def _clean_list(values: Any) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if text:
            out.append(text)
    return list(dict.fromkeys(out))


def _get_project_row(db: Any, project_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return db.get(_PROJECTS_TABLE, {}).get(project_id)

    result = db.table(_PROJECTS_TABLE).select("*").eq("id", project_id).maybe_single().execute()
    return getattr(result, "data", None) if result is not None else None


def _transcript_excerpt(db: Any, session_id: str, max_len: int = 300) -> str:
    if isinstance(db, dict):
        row = next(
            (r for r in db.get(_TRANSCRIPTS_TABLE, {}).values() if str(r.get("session_id")) == session_id),
            None,
        )
    else:
        result = (
            db.table(_TRANSCRIPTS_TABLE)
            .select("full_text")
            .eq("session_id", session_id)
            .maybe_single()
            .execute()
        )
        row = getattr(result, "data", None) if result is not None else None

    text = str((row or {}).get("full_text") or "")
    return _truncate(text, max_len)


def _video_evidence_chip_refs_for_skill(all_chips: list[Any], skill: str) -> list[dict[str, Any]]:
    """Return safe video evidence chip references related to ``skill``.

    Each chip is already a safe projection (label, timestamps, short
    snippet, source) built by ``project_defense_evidence_chips`` — never the
    full transcript, storage paths, or signed URLs.
    """
    matched = [
        chip for chip in (all_chips or [])
        if isinstance(chip, dict) and chip.get("related_skill") == skill
    ]
    return matched[:_MAX_VIDEO_CHIPS_PER_SKILL]


def _answered_question_count(db: Any, session_id: str) -> int:
    if isinstance(db, dict):
        rows = [r for r in db.get(_QUESTIONS_TABLE, {}).values() if str(r.get("session_id")) == session_id]
    else:
        result = db.table(_QUESTIONS_TABLE).select("answered").eq("session_id", session_id).execute()
        rows = getattr(result, "data", []) or []
    return sum(1 for r in rows if r.get("answered"))


def _safe_attached_proof_refs(attached: dict[str, Any]) -> dict[str, Any]:
    refs: dict[str, Any] = {}

    github_proof = attached.get("github_proof")
    if isinstance(github_proof, dict) and github_proof.get("github_proof_id"):
        refs["github_proof_id"] = github_proof["github_proof_id"]
    elif attached.get("github_proof_id"):
        refs["github_proof_id"] = attached["github_proof_id"]

    website_proofs = attached.get("website_proofs")
    if isinstance(website_proofs, list) and website_proofs:
        proof_ids = [
            p.get("proof_session_id") for p in website_proofs if isinstance(p, dict) and p.get("proof_session_id")
        ]
        if proof_ids:
            refs["website_proof_session_ids"] = proof_ids

    documents = attached.get("documents")
    if isinstance(documents, list) and documents:
        doc_ids = [d.get("document_evidence_id") for d in documents if isinstance(d, dict) and d.get("document_evidence_id")]
        if doc_ids:
            refs["document_evidence_ids"] = doc_ids

    if attached.get("skill_pipeline_ids"):
        refs["skill_pipeline_ids"] = attached["skill_pipeline_ids"]

    return refs


def _confidence_for_skill(analysis: dict[str, Any]) -> int:
    overall = int(analysis.get("overall_defense_score") or 0)
    return max(0, min(_CONFIDENCE_CAP, overall // 2))


def _ownership_signals(analysis: dict[str, Any]) -> list[str]:
    score = int(analysis.get("ownership_signal_score") or 0)
    if score >= 60:
        return ["First-person explanation", "Described personal implementation"]
    return []


def _technical_depth_signals(analysis: dict[str, Any]) -> list[str]:
    score = int(analysis.get("technical_depth_score") or 0)
    if score >= 60:
        return ["Technical depth detected", "Architecture/design discussion"]
    return []


def _merged_support_status(existing: SkillEvidencePipelineResponse | None, new_status: str) -> str:
    if existing is None:
        return new_status
    existing_rank = _SUPPORT_RANK.get(existing.support_status, 0)
    new_rank = _SUPPORT_RANK.get(new_status, 0)
    return existing.support_status if existing_rank >= new_rank else new_status


def _build_project_defense_evidence_source(skill: str, project_title: str, confidence: int, support_status: str) -> dict[str, Any]:
    status = "partial" if support_status == "partially_supported" else "missing"
    return {
        "key": "project_defense",
        "label": "Project Defense",
        "status": status,
        "score": confidence,
        "reason": _truncate(f"Project defense explanation for '{project_title}' provides supporting evidence for {skill}.", 200),
    }


def _merge_evidence_sources(existing_sources: list[Any], project_defense_source: dict[str, Any]) -> list[Any]:
    merged = [
        s for s in (existing_sources or [])
        if not (isinstance(s, dict) and s.get("key") == "project_defense")
    ]
    merged.append(project_defense_source)
    return merged


def _build_recruiter_summary(skill: str, project_title: str) -> str:
    return _truncate(
        f"The student provided a project defense explanation for '{project_title}' "
        f"that provides supporting evidence for {skill}.",
        400,
    )


def _build_student_summary(skill: str) -> str:
    return _truncate(
        f"Your {skill} evidence now includes a project defense explanation. Add GitHub, "
        "website, or document proof for stronger evidence.",
        400,
    )


def _build_pipeline_payload(
    skill: str,
    project_title: str,
    existing: SkillEvidencePipelineResponse | None,
    project_defense_source: dict[str, Any],
    confidence: int,
    new_support: str,
) -> SkillEvidencePipelineCreate:
    if existing is not None:
        skill_name = existing.skill_name
        confidence_score = max(existing.confidence_score, confidence)
        support_status = _merged_support_status(existing, new_support)
        evidence_sources = _merge_evidence_sources(existing.evidence_sources, project_defense_source)
        evidence_count = max(existing.evidence_count + 1, len(evidence_sources))
        skill_category = existing.skill_category or _infer_category(skill)
        strongest_proof = existing.strongest_proof
        weakest_proof = existing.weakest_proof
        missing_evidence = existing.missing_evidence
        next_actions = existing.next_actions
        recruiter_summary = existing.recruiter_summary or _build_recruiter_summary(skill, project_title)
        student_summary = existing.student_summary or _build_student_summary(skill)
        visibility_status = existing.visibility_status
    else:
        skill_name = skill
        confidence_score = confidence
        support_status = new_support
        evidence_sources = [project_defense_source]
        evidence_count = len(evidence_sources)
        skill_category = _infer_category(skill)
        strongest_proof = {}
        weakest_proof = {}
        missing_evidence = []
        next_actions = []
        recruiter_summary = _build_recruiter_summary(skill, project_title)
        student_summary = _build_student_summary(skill)
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
class ProjectDefenseSyncResult:
    project_id: str
    session_id: str
    user_id: str
    skills_synced: list[str] = field(default_factory=list)
    artifacts_created: int = 0
    pipelines_upserted: int = 0
    already_synced: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "skills_synced": self.skills_synced,
            "artifacts_created": self.artifacts_created,
            "pipelines_upserted": self.pipelines_upserted,
            "already_synced": self.already_synced,
            "errors": self.errors,
        }


class ProjectDefenseArtifactSyncService:
    """Converts an analyzed Project Defense session into skill_evidence_artifacts.

    Reads from vbr_projects / vbr_verification_sessions / vbr_transcripts /
    vbr_session_questions using ``db``. Writes to skill_evidence_pipelines /
    skill_evidence_artifacts using ``pipeline_db``.
    """

    def __init__(self, db: Any, pipeline_db: Any) -> None:
        self._db = db
        self._pipeline_svc = SkillEvidencePipelineService(pipeline_db)

    # ── Ownership lookup ──────────────────────────────────────────────────────

    def _get_owned_session_and_project(self, user_id: str, session_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        session = get_session(self._db, session_id)
        if session is None:
            raise ProjectDefenseNotFoundError(session_id)

        project = _get_project_row(self._db, str(session.get("project_id") or ""))
        if project is None or str(project.get("user_id")) != str(user_id):
            raise ProjectDefenseNotFoundError(session_id)

        # Sync reads the SAME merged canonical evidence package (claimed skills
        # + attached proofs across the project's duplicate group) that the
        # workspace, question generation, and analysis use — never only the
        # session's own row, which may be a near-empty duplicate.
        return session, merge_owned_project(self._db, user_id, project)

    # ── Existing pipeline lookup ─────────────────────────────────────────────

    def _pipelines_by_skill(self, user_id: str) -> dict[str, SkillEvidencePipelineResponse]:
        """One bulk read of the student's pipeline rows, keyed by lowercased skill.

        The per-skill loop in ``sync`` used to re-list EVERY pipeline (and each
        pipeline's artifacts) for EVERY claimed skill — an N×M query storm that
        made the save hang for minutes against a real database.
        """
        try:
            return {
                p.skill_name.strip().lower(): p
                for p in self._pipeline_svc.list_pipeline_rows_for_student(user_id)
            }
        except Exception:
            return {}

    # ── Idempotency check ─────────────────────────────────────────────────────

    def _artifact_exists_for_session(self, user_id: str, session_id: str) -> bool:
        try:
            return self._pipeline_svc.has_artifact_for_session(
                user_id, kind="project_defense", vbr_session_id=session_id
            )
        except Exception:
            return False

    def artifact_exists_for_session(self, user_id: str, session_id: str) -> bool:
        """True when this session's defense evidence is already on the Skill Graph.

        Used by the workspace context endpoint so a reloaded workspace reports
        the honest saved/not-saved Skill Graph state.
        """
        return self._artifact_exists_for_session(user_id, session_id)

    # ── Main sync ─────────────────────────────────────────────────────────────

    def sync(self, user_id: str, session_id: str) -> ProjectDefenseSyncResult:
        """Convert an analyzed Project Defense session into skill_evidence_artifacts.

        Raises:
            ProjectDefenseNotFoundError: session missing or owned by another user.
            ProjectDefenseNotAnalyzedError: session has not been analyzed yet.

        Idempotent: returns early with already_synced=True if an artifact for
        this session_id already exists.
        """
        session, project = self._get_owned_session_and_project(user_id, session_id)
        project_id = str(project["id"])

        telemetry = session.get("telemetry") or {}
        analysis = telemetry.get("project_defense_analysis")
        if not analysis:
            raise ProjectDefenseNotAnalyzedError(session_id)

        result = ProjectDefenseSyncResult(project_id=project_id, session_id=session_id, user_id=user_id)

        if self._artifact_exists_for_session(user_id, session_id):
            result.already_synced = True
            return result

        metadata = project.get("metadata") or {}
        # Explicit claimed skills, or the deterministic evidence-derived list
        # (GitHub detected_skills / document skills / website supported_skills)
        # when the student never typed one — the project-first flow collects no
        # claimed-skills input, so requiring the explicit list here made every
        # project-first defense fail with "Couldn't save to Skill Graph".
        claimed_skills = effective_claimed_skills(metadata)
        if not claimed_skills:
            result.errors.append(
                "No skills to save yet — attach GitHub, website, or document proof "
                "with detected skills (or add claimed skills) and try again."
            )
            return result

        project_title = _truncate(project.get("title") or "this project", 200)
        transcript_excerpt = _transcript_excerpt(self._db, session_id)
        answered_question_count = _answered_question_count(self._db, session_id)
        all_video_chips = telemetry.get("video_evidence_chips") or []
        attached_proof_refs = _safe_attached_proof_refs(metadata.get("attached_proofs") or {})
        ownership_signals = _ownership_signals(analysis)
        technical_depth_signals = _technical_depth_signals(analysis)
        skills_explained_well = set(_clean_list(analysis.get("skills_explained_well") or []))
        confidence = _confidence_for_skill(analysis)

        existing_by_skill = self._pipelines_by_skill(user_id)

        for skill in claimed_skills:
            try:
                new_support = "partially_supported" if skill in skills_explained_well else "needs_review"
                existing = existing_by_skill.get(skill.strip().lower())
                source = _build_project_defense_evidence_source(skill, project_title, confidence, new_support)
                payload = _build_pipeline_payload(skill, project_title, existing, source, confidence, new_support)
                pipeline = self._pipeline_svc.upsert_pipeline(user_id, payload)
                result.pipelines_upserted += 1

                artifact_data = _strip_unsafe({
                    "kind": "project_defense",
                    "vbr_project_id": project_id,
                    "vbr_session_id": session_id,
                    "project_title": project_title,
                    "claimed_skills": claimed_skills,
                    "student_role_summary": _truncate(metadata.get("student_role") or "", 200),
                    "capped_transcript_excerpt": transcript_excerpt,
                    "ownership_signals": ownership_signals,
                    "technical_depth_signals": technical_depth_signals,
                    "attached_proof_refs": attached_proof_refs,
                    "answered_question_count": answered_question_count,
                    "matched_skills": [skill],
                    "video_evidence_chips": _video_evidence_chip_refs_for_skill(all_video_chips, skill),
                })

                self._pipeline_svc.add_artifact(
                    user_id,
                    SkillEvidenceArtifactCreate(
                        pipeline_id=pipeline.id,
                        proof_session_id=None,
                        source_type="transcript",
                        source_title=f"Project Defense — {skill}",
                        project_name=project_title,
                        visibility="protected",
                        confidence_score=confidence,
                        relevance_to_skill=f"Project defense explanation supports {skill}",
                        proof_reason=_truncate(str(analysis.get("recruiter_summary") or ""), 200),
                        artifact_data=artifact_data,
                    ),
                )
                result.artifacts_created += 1
                result.skills_synced.append(payload.skill_name)
            except Exception as exc:
                logger.warning("project defense sync: failed for skill %r: %s", skill, exc)
                result.errors.append(f"sync failed for {skill!r}: {exc}")

        return result
