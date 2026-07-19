"""Website Proof → Skill Evidence Artifact Sync Service.

Converts completed Website Proof analysis outputs into structured
skill_evidence_artifacts linked to skill_evidence_pipelines.

Security invariants:
  - Never store signed URLs, storage paths, tokens, raw private media,
    or full DOM/transcript dumps.
  - artifact_data stores summaries and safe metadata only.
  - Default pipeline visibility: protected (respects existing student choice).
  - Default artifact visibility: protected.
  - proof_session_id is stored in artifact_data only (not as the FK column,
    because website proof sessions are not in extension_proof_sessions).
  - Idempotent: safe to call multiple times for the same session.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.schemas.skill_evidence_pipeline import (
    SkillEvidenceArtifactCreate,
    SkillEvidencePipelineCreate,
)
from app.services.skill_evidence_pipeline_service import SkillEvidencePipelineService

logger = logging.getLogger(__name__)

_WF_TABLE     = "workflow_analysis_results"
_PD_TABLE     = "project_defense_analysis_results"
_OPT_TABLE    = "optional_evidence_submissions"
_VF_TABLE     = "workflow_visual_frame_evidence"
_REVIEW_TABLE = "ai_domain_review_results"

# Keys that must never appear in artifact_data
_UNSAFE_KEYS = frozenset({
    "storage_path", "storage_bucket", "signed_url", "signedUrl",
    "access_token", "service_role_key", "private_url", "download_url",
    "raw_frame_url", "keyframe_url", "screenshot_url", "user_data_dir",
    "video_url", "media_url", "media_storage_path",
    "login_screenshot", "final_screenshot",
})

_CATEGORY_MAP: list[tuple[list[str], str]] = [
    (["machine learning", "deep learning", "ai", "nlp", "computer vision", "tensorflow", "pytorch", "llm", "inference", "model"], "AI/ML"),
    (["react", "frontend", "javascript", "typescript", "vue", "html", "css", "web", "ui", "three.js", "webgl"], "Frontend"),
    (["python", "fastapi", "django", "flask", "backend", "api", "node", "express", "rest"], "Backend"),
    (["data", "visualization", "d3", "chart", "pandas", "sql", "database", "analytics"], "Data"),
    (["docker", "devops", "deployment", "kubernetes", "ci", "cloud", "aws", "gcp"], "DevOps"),
]

# Terms that signal browser/platform environment noise (not target-app content)
# Note: "shared pooler" is intentionally omitted — "pooler" already catches it.
_BACKEND_NOISE_TERMS: frozenset[str] = frozenset({
    "supabase", "storage", "buckets", "new bucket",
    "pooler", "maintenance",
    "us-east", "us-east-1", "eu-west", "eu-west-1",
    "devtools", "developer tools", "chrome extension",
    "new tab", "bookmarks", "downloads", "notifications",
    "terminal",
})

# Group definitions: if target domain contains any member, all group members are exempt
_BACKEND_NOISE_GROUPS: list[list[str]] = [
    ["supabase", "storage", "buckets", "pooler", "maintenance"],
    ["devtools", "developer tools", "chrome extension", "extensions"],
    ["new tab", "bookmarks", "downloads", "notifications"],
]

# Phrases that indicate Qwen analyzed the recorder/browser UI instead of the target app
_RECORDER_UI_PHRASES: frozenset[str] = frozenset({
    "screen recording interface",
    "veribridge ai is open",
    "recorder tab",
    "veribridge recorder",
    "stop & upload",
    "start screen recording",
    "recording interface",
    "proof builder is open",
    # Exact phrases from the failing Teachable Machine session (added 2026-06-09)
    "live video recording",
    "stop or send the recording",
    "recording controls",
    "recorder controls",
    "veribridge screen recorder",
    "veribridge recording interface",
    "recording active",
    "stop recording",
    "send proof",
    "send recording",
    "screen recorder overlay",
    "browser recorder",
    "extension recorder",
    "start and stop recording",
    "showing options to start and stop recording",
})


def _strip_unsafe(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k not in _UNSAFE_KEYS}


def _truncate(text: str | None, max_len: int = 400) -> str:
    if not text:
        return ""
    return str(text)[:max_len]


def _extract_domain(url: str) -> str:
    """Extract hostname from a URL string for noise-filtering context."""
    if not url:
        return ""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url if "://" in url else f"https://{url}")
        return (parsed.netloc or parsed.path).lower()
    except Exception:
        return url.split("/")[0].lower()


def _term_exempt_for_domain(term: str, domain_lower: str) -> bool:
    """True if term should be preserved because the target domain is in the same group."""
    if term in domain_lower:
        return True
    for group in _BACKEND_NOISE_GROUPS:
        if term in group and any(t in domain_lower for t in group):
            return True
    return False


def _segment_is_noisy(segment: str, domain_lower: str) -> bool:
    """True if segment is dominated by browser/platform environment noise."""
    sl = segment.strip().lower()
    for term in _BACKEND_NOISE_TERMS:
        if _term_exempt_for_domain(term, domain_lower):
            continue
        if term in sl:
            return True
    return False


def _sanitize_text_segments(text: str, target_domain: str) -> tuple[str, str]:
    """Filter noise segments from semicolon/newline-separated text.

    Returns (sanitized_text, evidence_quality) where quality is
    'clean', 'partial', or 'noisy'.
    """
    if not text or not text.strip():
        return "", "clean"
    domain_lower = target_domain.lower()
    segments = [s.strip() for s in text.replace("\n", ";").split(";") if s.strip()]
    if not segments:
        return "", "clean"
    kept: list[str] = []
    dropped = 0
    for seg in segments:
        if _segment_is_noisy(seg, domain_lower):
            dropped += 1
        else:
            kept.append(seg)
    if dropped == 0:
        quality = "clean"
    elif kept:
        quality = "partial"
    else:
        quality = "noisy"
    return "; ".join(kept), quality


def _is_recorder_ui_text(text: str) -> bool:
    """True if text shows Qwen analyzed the recorder/browser UI, not the target app."""
    lower = text.lower()
    return any(phrase in lower for phrase in _RECORDER_UI_PHRASES)


def _infer_category(skill: str) -> str:
    lower = skill.lower()
    for keywords, cat in _CATEGORY_MAP:
        if any(k in lower for k in keywords):
            return cat
    return "technical"


def _skill_confidence(skill: str, wf: dict[str, Any] | None, pd: dict[str, Any] | None) -> int:
    base = 50
    if wf:
        supported = [str(s).strip().lower() for s in (wf.get("supported_skills") or [])]
        if skill.strip().lower() in supported:
            base = max(base, int(wf.get("evidence_strength_score") or 60))
    if pd:
        well = [str(s).strip().lower() for s in (pd.get("skills_explained_well") or [])]
        if skill.strip().lower() in well:
            base = min(base + 10, 100)
    return min(base, 100)


def _skill_support_status(skill: str, wf: dict[str, Any] | None) -> str:
    if not wf:
        return "needs_review"
    supported = [str(s).strip().lower() for s in (wf.get("supported_skills") or [])]
    weak = [str(s).strip().lower() for s in (wf.get("weakly_supported_skills") or [])]
    sl = skill.strip().lower()
    if sl in supported:
        score = int(wf.get("evidence_strength_score") or 0)
        return "strongly_supported" if score >= 70 else "partially_supported"
    if sl in weak:
        return "partially_supported"
    return "needs_review"


def _build_evidence_sources(
    wf: dict[str, Any] | None,
    pd: dict[str, Any] | None,
    opt_rows: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    review: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    if wf:
        score = int(wf.get("evidence_strength_score") or 0)
        sources.append({
            "key": "workflow",
            "label": "Workflow Recording",
            "status": "supported" if score >= 60 else "partial",
            "score": score,
            "reason": _truncate(str(wf.get("recruiter_summary") or ""), 150),
        })
    kf_frames = [f for f in frames if f.get("frame_type") == "video_keyframe"]
    if kf_frames:
        kf_count = len(kf_frames)
        sources.append({
            "key": "keyframes",
            "label": "Keyframes",
            "status": "supported",
            "score": min(90, 60 + kf_count * 10),
            "reason": f"{kf_count} keyframe(s) captured during proof session",
        })
    if wf and wf.get("frame_ocr_evidence_summary"):
        ocr = wf["frame_ocr_evidence_summary"]
        if isinstance(ocr, dict) and ocr.get("has_ocr_evidence"):
            sources.append({
                "key": "ocr",
                "label": "OCR / Text Extraction",
                "status": "partial",
                "score": 55,
                "reason": "Text extracted from recorded frames",
            })
    if wf:
        dom_status = wf.get("dom_evidence_status") or wf.get("visible_evidence_status") or "not_captured"
        if dom_status != "not_captured":
            sources.append({
                "key": "dom",
                "label": "DOM Evidence",
                "status": "supported" if dom_status == "available" else "partial",
                "score": 65 if dom_status == "available" else 45,
                "reason": f"DOM evidence status: {dom_status}",
            })
    if pd and pd.get("transcript_text"):
        score = int(pd.get("overall_defense_score") or pd.get("overall_score") or 50)
        sources.append({
            "key": "defense",
            "label": "Project Defense",
            "status": "supported" if score >= 60 else "partial",
            "score": score,
            "reason": _truncate(str(pd.get("recruiter_summary") or ""), 150),
        })
    if opt_rows:
        doc_rows = [r for r in opt_rows if r.get("source_type") == "document"]
        if doc_rows:
            sources.append({
                "key": "documents",
                "label": "Documents",
                "status": "supported",
                "score": 65,
                "reason": f"{len(doc_rows)} document(s) submitted",
            })
    if review:
        score = int(review.get("domain_review_score") or 0)
        sources.append({
            "key": "review",
            "label": "VeriBridge AI Review",
            "status": "supported" if score >= 60 else "partial",
            "score": score,
            "reason": _truncate(str(review.get("recruiter_summary") or ""), 150),
        })
    return sources


def _build_recruiter_summary(skill: str, wf: dict[str, Any] | None, pd: dict[str, Any] | None) -> str:
    parts: list[str] = []
    if wf and wf.get("recruiter_summary"):
        parts.append(_truncate(str(wf["recruiter_summary"]), 200))
    if pd and pd.get("recruiter_summary"):
        parts.append(_truncate(str(pd["recruiter_summary"]), 200))
    return " ".join(parts) if parts else f"Evidence from Website Proof supports {skill}."


def _build_student_summary(skill: str, wf: dict[str, Any] | None, pd: dict[str, Any] | None) -> str:
    if pd and pd.get("recommended_improvements"):
        improvements = pd["recommended_improvements"]
        if isinstance(improvements, list) and improvements:
            return _truncate(str(improvements[0]), 200)
    if wf:
        score = int(wf.get("evidence_strength_score") or 0)
        if score < 70:
            return f"Your {skill} evidence is building. Add more recordings to strengthen it."
    return f"Your {skill} evidence from Website Proof has been recorded."


def _most_relevant_skill(row: dict[str, Any], skills: list[str]) -> str | None:
    if not skills:
        return None
    ev_objects = row.get("evidence_objects") or []
    counts: dict[str, int] = {}
    for ev in ev_objects:
        if isinstance(ev, dict) and ev.get("skill_name"):
            name = str(ev["skill_name"]).strip().lower()
            for s in skills:
                if s.strip().lower() == name:
                    counts[s] = counts.get(s, 0) + 1
    return max(counts, key=lambda x: counts[x]) if counts else skills[0]


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class SyncResult:
    proof_session_id: str
    user_id: str
    skills_synced: list[str] = field(default_factory=list)
    artifacts_created: int = 0
    pipelines_upserted: int = 0
    artifact_types_created: list[str] = field(default_factory=list)
    already_synced: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proof_session_id": self.proof_session_id,
            "user_id": self.user_id,
            "skills_synced": self.skills_synced,
            "artifacts_created": self.artifacts_created,
            "pipelines_upserted": self.pipelines_upserted,
            "artifact_types_created": self.artifact_types_created,
            "already_synced": self.already_synced,
            "errors": self.errors,
        }


# ── Service ───────────────────────────────────────────────────────────────────

class WebsiteProofArtifactSyncService:
    """Converts Website Proof analysis data into skill_evidence_artifacts.

    Reads from proof analysis tables using ``db``.
    Writes to skill_evidence_pipelines / skill_evidence_artifacts using ``pipeline_db``.
    """

    def __init__(self, db: Any, pipeline_db: Any) -> None:
        self._db = db
        self._pipeline_svc = SkillEvidencePipelineService(pipeline_db)

    # ── Data loaders ──────────────────────────────────────────────────────────

    def _load_workflow(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        if isinstance(self._db, dict):
            for row in self._db.get(_WF_TABLE, {}).values():
                if (
                    str(row.get("proof_session_id")) == session_id
                    and str(row.get("user_id")) == user_id
                ):
                    return row
            return None
        try:
            resp = (
                self._db.table(_WF_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .eq("proof_session_id", session_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            return rows[0] if rows else None
        except Exception:
            logger.warning("sync: workflow load failed", exc_info=True)
            return None

    def _load_project_defense(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        if isinstance(self._db, dict):
            direct = self._db.get(_PD_TABLE, {}).get(session_id)
            if direct:
                return direct
            for row in self._db.get(_PD_TABLE, {}).values():
                if (
                    str(row.get("proof_session_id")) == session_id
                    and str(row.get("user_id")) == user_id
                ):
                    return row
            return None
        try:
            resp = (
                self._db.table(_PD_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .eq("proof_session_id", session_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            return rows[0] if rows else None
        except Exception:
            logger.warning("sync: project defense load failed", exc_info=True)
            return None

    def _load_optional_evidence(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        if isinstance(self._db, dict):
            return [
                row for row in self._db.get(_OPT_TABLE, {}).values()
                if (
                    str(row.get("proof_session_id")) == session_id
                    and str(row.get("user_id")) == user_id
                )
            ]
        try:
            resp = (
                self._db.table(_OPT_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .eq("proof_session_id", session_id)
                .order("created_at", desc=True)
                .execute()
            )
            return resp.data or []
        except Exception:
            logger.warning("sync: optional evidence load failed", exc_info=True)
            return []

    def _load_frame_evidence(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        if isinstance(self._db, dict):
            return [
                row for row in self._db.get(_VF_TABLE, {}).values()
                if (
                    str(row.get("proof_session_id")) == session_id
                    and str(row.get("user_id")) == user_id
                )
            ]
        try:
            resp = (
                self._db.table(_VF_TABLE)
                .select("timestamp_ms,frame_type,visual_summary,ocr_text,extracted_result_values,visual_reasoning_json,confidence_score")
                .eq("user_id", user_id)
                .eq("proof_session_id", session_id)
                .order("timestamp_ms", desc=False)
                .limit(20)
                .execute()
            )
            return resp.data or []
        except Exception:
            logger.warning("sync: frame evidence load failed", exc_info=True)
            return []

    def _load_review(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        if isinstance(self._db, dict):
            for row in self._db.get(_REVIEW_TABLE, {}).values():
                if (
                    str(row.get("proof_session_id")) == session_id
                    and str(row.get("user_id")) == user_id
                ):
                    return row
            return None
        try:
            resp = (
                self._db.table(_REVIEW_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .eq("proof_session_id", session_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            return rows[0] if rows else None
        except Exception:
            logger.warning("sync: review load failed", exc_info=True)
            return None

    # ── Skill extraction ──────────────────────────────────────────────────────

    def _extract_skills(
        self,
        wf: dict[str, Any] | None,
        pd: dict[str, Any] | None,
        opt_rows: list[dict[str, Any]],
    ) -> list[str]:
        """Collect unique skill names from all analysis outputs."""
        skills: list[str] = []
        seen: set[str] = set()

        def _add(name: str) -> None:
            key = name.strip().lower()
            if key and key not in seen:
                seen.add(key)
                skills.append(name.strip())

        if wf:
            for s in (wf.get("supported_skills") or []):
                _add(str(s))
            for s in (wf.get("weakly_supported_skills") or []):
                _add(str(s))

        if pd:
            for s in (pd.get("skills_mentioned") or []):
                _add(str(s))
            for s in (pd.get("skills_explained_well") or []):
                _add(str(s))

        for row in opt_rows:
            for ev in (row.get("evidence_objects") or []):
                if isinstance(ev, dict) and ev.get("skill_name"):
                    _add(str(ev["skill_name"]))

        return skills

    # ── Visibility guard ──────────────────────────────────────────────────────

    def _existing_pipeline_visibility(self, user_id: str, skill_name: str) -> str | None:
        """Return the current visibility for (user, skill_name) or None if not found."""
        try:
            # Rows only — pulling every pipeline's artifacts per skill made this
            # an N×M query storm on real databases.
            for p in self._pipeline_svc.list_pipeline_rows_for_student(user_id):
                if p.skill_name.strip().lower() == skill_name.strip().lower():
                    return p.visibility_status
        except Exception:
            pass
        return None

    # ── Idempotency check ─────────────────────────────────────────────────────

    def _artifacts_exist_for_session(self, user_id: str, session_id: str) -> bool:
        """True if any artifact already stores proof_session_id == session_id."""
        try:
            return self._pipeline_svc.has_artifact_matching(
                user_id, proof_session_id=session_id
            )
        except Exception:
            pass
        return False

    # ── Main sync ─────────────────────────────────────────────────────────────

    def sync(self, user_id: str, proof_session_id: str) -> SyncResult:
        """Convert Website Proof analysis outputs into skill_evidence_artifacts.

        Idempotent: returns early with already_synced=True if artifacts for
        this session already exist.
        """
        result = SyncResult(proof_session_id=proof_session_id, user_id=user_id)

        if self._artifacts_exist_for_session(user_id, proof_session_id):
            result.already_synced = True
            return result

        wf        = self._load_workflow(user_id, proof_session_id)
        pd        = self._load_project_defense(user_id, proof_session_id)
        opt_rows  = self._load_optional_evidence(user_id, proof_session_id)
        frames    = self._load_frame_evidence(user_id, proof_session_id)
        review    = self._load_review(user_id, proof_session_id)

        skills = self._extract_skills(wf, pd, opt_rows)
        if not skills:
            result.errors.append("No skills detected from proof analysis — nothing to sync.")
            return result

        result.skills_synced = skills

        pipeline_ids: dict[str, str] = {}
        ev_sources = _build_evidence_sources(wf, pd, opt_rows, frames, review)
        ev_count = len(ev_sources)

        for skill in skills:
            try:
                existing_vis = self._existing_pipeline_visibility(user_id, skill)
                visibility = existing_vis if existing_vis else "protected"

                pipeline_payload = SkillEvidencePipelineCreate(
                    skill_name=skill,
                    skill_category=_infer_category(skill),
                    confidence_score=_skill_confidence(skill, wf, pd),
                    support_status=_skill_support_status(skill, wf),
                    evidence_count=ev_count,
                    evidence_sources=ev_sources,
                    recruiter_summary=_build_recruiter_summary(skill, wf, pd),
                    student_summary=_build_student_summary(skill, wf, pd),
                    visibility_status=visibility,
                )
                pipeline = self._pipeline_svc.upsert_pipeline(user_id, pipeline_payload)
                pipeline_ids[skill] = pipeline.id
                result.pipelines_upserted += 1
            except Exception as exc:
                logger.warning("sync: pipeline upsert failed for skill %r: %s", skill, exc)
                result.errors.append(f"pipeline upsert failed for {skill!r}: {exc}")

        for skill in skills:
            pid = pipeline_ids.get(skill)
            if not pid:
                continue
            try:
                self._create_workflow_artifact(user_id, skill, pid, proof_session_id, wf, result)
                self._create_ocr_artifact(user_id, skill, pid, proof_session_id, wf, result)
                self._create_dom_artifact(user_id, skill, pid, proof_session_id, wf, result)
                self._create_qwen_artifact(user_id, skill, pid, proof_session_id, wf, result)
                self._create_keyframe_artifact(user_id, skill, pid, proof_session_id, frames, result)
                self._create_transcript_artifact(user_id, skill, pid, proof_session_id, pd, result)
                self._create_review_artifact(user_id, skill, pid, proof_session_id, review, result)
            except Exception as exc:
                logger.warning("sync: artifact creation failed for skill %r: %s", skill, exc)
                result.errors.append(f"artifact error for {skill!r}: {exc}")

        doc_rows = [r for r in opt_rows if r.get("source_type") == "document"]
        for row in doc_rows:
            skill = _most_relevant_skill(row, skills)
            pid = pipeline_ids.get(skill) if skill else None
            if pid and skill:
                try:
                    self._create_document_artifact(user_id, skill, pid, proof_session_id, row, result)
                except Exception as exc:
                    logger.warning("sync: document artifact failed: %s", exc)
                    result.errors.append(f"document artifact error: {exc}")

        return result

    # ── Artifact helpers ──────────────────────────────────────────────────────

    def _add_artifact(
        self,
        user_id: str,
        payload: SkillEvidenceArtifactCreate,
        result: SyncResult,
        source_type: str,
    ) -> None:
        self._pipeline_svc.add_artifact(user_id, payload)
        result.artifacts_created += 1
        if source_type not in result.artifact_types_created:
            result.artifact_types_created.append(source_type)

    def _create_workflow_artifact(
        self,
        user_id: str,
        skill: str,
        pipeline_id: str,
        session_id: str,
        wf: dict[str, Any] | None,
        result: SyncResult,
    ) -> None:
        if not wf:
            return
        score = int(wf.get("evidence_strength_score") or 0)
        observed = wf.get("observed_demonstration") or {}
        steps_count = len(observed.get("steps") or []) if isinstance(observed, dict) else 0
        matched = [
            s for s in (wf.get("supported_skills") or [])
            if str(s).strip().lower() == skill.strip().lower()
        ]
        artifact_data = _strip_unsafe({
            "proof_session_id": session_id,
            "website_url": _truncate(str(wf.get("target_website") or ""), 200),
            "objective": _truncate(str(wf.get("workflow_confidence") or ""), 100),
            "steps_count": steps_count,
            "workflow_summary": _truncate(str(wf.get("workflow_summary") or ""), 400),
            "score": score,
            "matched_skills": matched[:10],
        })
        self._add_artifact(
            user_id,
            SkillEvidenceArtifactCreate(
                pipeline_id=pipeline_id,
                proof_session_id=None,
                source_type="workflow",
                source_title=f"Website Workflow — {_truncate(str(wf.get('target_website') or 'Proof Session'), 60)}",
                project_name="Website Proof",
                visibility="protected",
                confidence_score=min(score, 100),
                relevance_to_skill=f"Live workflow demonstrated {skill}",
                proof_reason=_truncate(str(wf.get("recruiter_summary") or ""), 300),
                artifact_data=artifact_data,
            ),
            result,
            "workflow",
        )

    def _create_ocr_artifact(
        self,
        user_id: str,
        skill: str,
        pipeline_id: str,
        session_id: str,
        wf: dict[str, Any] | None,
        result: SyncResult,
    ) -> None:
        if not wf:
            return
        ocr = wf.get("frame_ocr_evidence_summary") or {}
        if not (isinstance(ocr, dict) and ocr.get("has_ocr_evidence")):
            return
        snippets = ocr.get("top_ocr_snippets") or []
        snippet_summary = "; ".join(str(s)[:100] for s in snippets[:3])
        skill_signals = [
            sig for sig in (ocr.get("skill_signals") or [])
            if isinstance(sig, dict)
            and str(sig.get("skill", "")).strip().lower() == skill.strip().lower()
        ]
        ocr_score = 70 if skill_signals else 50
        target_domain = _extract_domain(str(wf.get("target_website") or ""))
        sanitized_summary, ocr_quality = _sanitize_text_segments(snippet_summary, target_domain)
        artifact_data = _strip_unsafe({
            "proof_session_id": session_id,
            "extracted_text_summary": _truncate(sanitized_summary, 400),
            "matched_ui_labels": (ocr.get("matched_ui_labels") or [])[:10],
            "frame_count": int(ocr.get("frames_analyzed") or 0),
            "score": ocr_score,
            "evidence_quality": ocr_quality,
            "target_domain": target_domain or None,
        })
        self._add_artifact(
            user_id,
            SkillEvidenceArtifactCreate(
                pipeline_id=pipeline_id,
                proof_session_id=None,
                source_type="ocr",
                source_title=f"OCR Evidence — {skill}",
                project_name="Website Proof",
                visibility="protected",
                confidence_score=ocr_score,
                relevance_to_skill=f"OCR-extracted text supports {skill}",
                proof_reason=_truncate(snippet_summary, 200),
                artifact_data=artifact_data,
            ),
            result,
            "ocr",
        )

    def _create_dom_artifact(
        self,
        user_id: str,
        skill: str,
        pipeline_id: str,
        session_id: str,
        wf: dict[str, Any] | None,
        result: SyncResult,
    ) -> None:
        if not wf:
            return
        dom_status = (
            wf.get("dom_evidence_status")
            or wf.get("visible_evidence_status")
            or "not_captured"
        )
        if dom_status == "not_captured":
            return
        observed = wf.get("observed_demonstration") or {}
        target_domain = _extract_domain(str(wf.get("target_website") or ""))
        dom_summary = ""
        interacted = ""
        state_changes = ""
        dom_quality = "clean"
        if isinstance(observed, dict):
            raw_dom = str(observed.get("dom_summary") or "")
            raw_interacted = str(observed.get("demonstrated_actions") or "")
            raw_state = str(observed.get("state_changes") or "")
            dom_summary, dom_q = _sanitize_text_segments(raw_dom, target_domain)
            interacted, int_q = _sanitize_text_segments(raw_interacted, target_domain)
            state_changes, sc_q = _sanitize_text_segments(raw_state, target_domain)
            dom_summary = _truncate(dom_summary, 400)
            interacted = _truncate(interacted, 300)
            state_changes = _truncate(state_changes, 200)
            qualities = [q for q in (dom_q, int_q, sc_q) if q != "clean"]
            if not qualities:
                dom_quality = "clean"
            elif all(q == "noisy" for q in qualities):
                dom_quality = "noisy"
            else:
                dom_quality = "partial"
        dom_score = 65 if dom_status == "available" else 45
        artifact_data = _strip_unsafe({
            "proof_session_id": session_id,
            "dom_summary": dom_summary or _truncate(str(wf.get("page_context_summary") or ""), 400),
            "interacted_elements_summary": interacted,
            "state_changes_summary": state_changes,
            "score": dom_score,
            "evidence_quality": dom_quality,
            "target_domain": target_domain or None,
        })
        self._add_artifact(
            user_id,
            SkillEvidenceArtifactCreate(
                pipeline_id=pipeline_id,
                proof_session_id=None,
                source_type="dom",
                source_title=f"DOM Evidence — {skill}",
                project_name="Website Proof",
                visibility="protected",
                confidence_score=dom_score,
                relevance_to_skill=f"DOM capture supports {skill}",
                proof_reason=_truncate(str(wf.get("recruiter_summary") or ""), 200),
                artifact_data=artifact_data,
            ),
            result,
            "dom",
        )

    def _create_qwen_artifact(
        self,
        user_id: str,
        skill: str,
        pipeline_id: str,
        session_id: str,
        wf: dict[str, Any] | None,
        result: SyncResult,
    ) -> None:
        if not wf:
            return
        vrs = wf.get("visual_reasoning_summary") or {}
        if isinstance(vrs, str):
            try:
                import json as _json
                vrs = _json.loads(vrs)
            except Exception:
                vrs = {}
        if not isinstance(vrs, dict) or vrs.get("status") != "analyzed":
            return
        frames_analyzed = int(vrs.get("frames_analyzed") or 0)
        if frames_analyzed == 0:
            return
        summary = _truncate(str(vrs.get("summary") or ""), 400)
        confidence = min(90, 50 + frames_analyzed * 15)
        recorder_ui_detected = _is_recorder_ui_text(summary)
        target_domain = _extract_domain(str(wf.get("target_website") or ""))
        qwen_quality = "noisy" if recorder_ui_detected else "clean"
        # Compute sanitized target-only summary by dropping recorder-contaminated segments
        if recorder_ui_detected:
            raw_segs = [s.strip() for s in summary.replace(" | ", ";").replace("\n", ";").split(";") if s.strip()]
            clean_segs = [s for s in raw_segs if not _is_recorder_ui_text(s)]
            sanitized_visual_summary = _truncate("; ".join(clean_segs), 400) if clean_segs else ""
        else:
            sanitized_visual_summary = ""
        artifact_data = _strip_unsafe({
            "proof_session_id": session_id,
            "visual_observation_summary": summary,
            "sanitized_visual_summary": sanitized_visual_summary or None,
            "evidence_reasoning": _truncate(str(vrs.get("missing_claims") or ""), 200),
            "confidence": round(confidence / 100.0, 2),
            "recorder_ui_detected": recorder_ui_detected,
            "evidence_quality": qwen_quality,
            "target_domain": target_domain or None,
        })
        # Never expose raw contaminated Qwen output as proof_reason
        safe_proof_reason = "" if recorder_ui_detected else _truncate(summary, 200)
        self._add_artifact(
            user_id,
            SkillEvidenceArtifactCreate(
                pipeline_id=pipeline_id,
                proof_session_id=None,
                source_type="qwen",
                source_title=f"Visual Reasoning — {skill}",
                project_name="Website Proof",
                visibility="protected",
                confidence_score=confidence,
                relevance_to_skill=f"Qwen visual analysis supports {skill}",
                proof_reason=safe_proof_reason,
                artifact_data=artifact_data,
            ),
            result,
            "qwen",
        )

    def _create_keyframe_artifact(
        self,
        user_id: str,
        skill: str,
        pipeline_id: str,
        session_id: str,
        frames: list[dict[str, Any]],
        result: SyncResult,
    ) -> None:
        kf = [f for f in frames if f.get("frame_type") == "video_keyframe"]
        if not kf:
            return
        count = len(kf)
        summaries = [str(f["visual_summary"]) for f in kf if f.get("visual_summary")]
        combined = "; ".join(summaries[:3])
        score = min(90, 60 + count * 10)
        artifact_data = _strip_unsafe({
            "proof_session_id": session_id,
            "frame_count": count,
            "visual_summary": _truncate(combined, 400),
            "score": score,
            "keyframe_image_available": False,
            "evidence_quality": "partial",
        })
        self._add_artifact(
            user_id,
            SkillEvidenceArtifactCreate(
                pipeline_id=pipeline_id,
                proof_session_id=None,
                source_type="keyframe",
                source_title=f"Video Keyframes — {skill}",
                project_name="Website Proof",
                visibility="protected",
                confidence_score=score,
                relevance_to_skill=f"Video keyframes captured during {skill} demonstration",
                proof_reason=f"{count} keyframe(s) captured",
                artifact_data=artifact_data,
            ),
            result,
            "keyframe",
        )

    def _create_transcript_artifact(
        self,
        user_id: str,
        skill: str,
        pipeline_id: str,
        session_id: str,
        pd: dict[str, Any] | None,
        result: SyncResult,
    ) -> None:
        if not pd:
            return
        transcript = str(pd.get("refined_transcript") or pd.get("transcript_text") or "")
        if len(transcript.strip()) < 20:
            return
        skills_mentioned = pd.get("skills_mentioned") or []
        ownership_score = pd.get("ownership_signal_score")
        depth_score     = pd.get("technical_depth_score")
        ownership_signals: list[str] = (
            ["First-person explanation", "Described personal implementation"]
            if ownership_score and int(ownership_score) >= 60
            else []
        )
        depth_signals: list[str] = (
            ["Technical depth detected", "Architecture/design discussion"]
            if depth_score and int(depth_score) >= 60
            else []
        )
        # Store only a safe excerpt — never the full raw transcript
        excerpt = _truncate(transcript, 300)
        defense_score = int(pd.get("overall_defense_score") or pd.get("overall_score") or 0)
        artifact_data = _strip_unsafe({
            "proof_session_id": session_id,
            "excerpt": excerpt,
            "ownership_signals": ownership_signals,
            "technical_depth_signals": depth_signals,
            "matched_skills": [
                s for s in skills_mentioned
                if str(s).strip().lower() == skill.strip().lower()
            ],
        })
        self._add_artifact(
            user_id,
            SkillEvidenceArtifactCreate(
                pipeline_id=pipeline_id,
                proof_session_id=None,
                source_type="transcript",
                source_title=f"Project Defense — {skill}",
                project_name="Website Proof",
                visibility="protected",
                confidence_score=min(defense_score, 100) if defense_score else 50,
                relevance_to_skill=f"Defense transcript demonstrates {skill}",
                proof_reason=_truncate(str(pd.get("recruiter_summary") or ""), 200),
                artifact_data=artifact_data,
            ),
            result,
            "transcript",
        )

    def _create_document_artifact(
        self,
        user_id: str,
        skill: str,
        pipeline_id: str,
        session_id: str,
        row: dict[str, Any],
        result: SyncResult,
    ) -> None:
        ev_objects = row.get("evidence_objects") or []
        file_path = str(row.get("file_path") or row.get("section_label") or "Uploaded Document")
        doc_title = file_path.split("/")[-1][:80]
        skill_evs = [
            e for e in ev_objects
            if isinstance(e, dict)
            and str(e.get("skill_name", "")).strip().lower() == skill.strip().lower()
        ]
        sections = [_truncate(str(e.get("snippet") or ""), 200) for e in skill_evs[:3]]
        matched  = [str(e.get("skill_name")) for e in skill_evs]
        score = 75 if any(e.get("confidence") == "high" for e in skill_evs) else (60 if skill_evs else 50)
        artifact_data = _strip_unsafe({
            "proof_session_id": session_id,
            "document_title": doc_title,
            "extracted_sections_summary": sections,
            "matched_skills": matched[:10],
        })
        self._add_artifact(
            user_id,
            SkillEvidenceArtifactCreate(
                pipeline_id=pipeline_id,
                proof_session_id=None,
                source_type="document",
                source_title=f"Document — {doc_title}",
                project_name="Website Proof",
                visibility="protected",
                confidence_score=score,
                relevance_to_skill=f"Document evidence for {skill}",
                proof_reason=_truncate("; ".join(sections), 200),
                artifact_data=artifact_data,
            ),
            result,
            "document",
        )

    def _create_review_artifact(
        self,
        user_id: str,
        skill: str,
        pipeline_id: str,
        session_id: str,
        review: dict[str, Any] | None,
        result: SyncResult,
    ) -> None:
        if not review:
            return
        status    = str(review.get("ai_domain_review_status") or "pending")
        score     = int(review.get("domain_review_score") or 0)
        approved_at = str(review.get("updated_at") or review.get("created_at") or "")
        snapshot  = _truncate(str(review.get("recruiter_summary") or ""), 400)
        artifact_data = _strip_unsafe({
            "proof_session_id": session_id,
            "final_score": score,
            "approval_status": status,
            "review_snapshot_summary": snapshot,
            "approved_at": approved_at,
        })
        self._add_artifact(
            user_id,
            SkillEvidenceArtifactCreate(
                pipeline_id=pipeline_id,
                proof_session_id=None,
                source_type="review",
                source_title=f"VeriBridge AI Review — {skill}",
                project_name="Website Proof",
                visibility="protected",
                confidence_score=min(score, 100),
                relevance_to_skill=f"AI review result for {skill}",
                proof_reason=_truncate(snapshot, 200),
                artifact_data=artifact_data,
            ),
            result,
            "review",
        )
