"""Skill Evidence Pipeline Service.

Persists per-student skill evidence pipelines and artifacts to
skill_evidence_pipelines / skill_evidence_artifacts.

Security invariants (enforced in sanitize_recruiter_payload):
  - Never expose: student_id in recruiter payload, raw storage paths,
    signed URLs, private media URLs, access_token, service-role keys.
  - artifact_data for recruiter view strips any key matching a blocklist.
  - Private/locked artifacts are excluded from recruiter payload entirely.

Dict-mode (tests):
  The service detects ``isinstance(self._client, dict)`` and uses the
  in-memory store as a plain dict of table-name → {row_id: row_dict}.
  This avoids any network calls in unit tests.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.schemas.skill_evidence_pipeline import (
    RecruiterPipelineSummary,
    SkillEvidenceArtifactCreate,
    SkillEvidenceArtifactResponse,
    SkillEvidencePipelineCreate,
    SkillEvidencePipelineResponse,
    StudentArtifactSummary,
)

logger = logging.getLogger(__name__)

_PIPELINES_TABLE = "skill_evidence_pipelines"
_ARTIFACTS_TABLE = "skill_evidence_artifacts"

# Keys that must never appear in recruiter-facing artifact_data payloads.
_UNSAFE_ARTIFACT_KEYS = frozenset({
    "storage_path", "storage_bucket", "signed_url", "signedUrl",
    "access_token", "service_role_key", "private_url", "download_url",
    "raw_frame_url", "keyframe_url", "screenshot_url",
    "video_url", "media_storage_path",
})

# Visibility states that are never shown to recruiters.
_RECRUITER_HIDDEN_VISIBILITIES = frozenset({"private", "locked", "unavailable"})

# Pipeline visibility values that mean "hidden from recruiter entirely".
# Includes "private_only" as a defensive alias in case old data uses that string.
_PRIVATE_VISIBILITY_VALUES = frozenset({"private", "private_only"})

# ── MVP mock pipeline definitions ─────────────────────────────────────────────

_MVP_PIPELINES: list[dict[str, Any]] = [
    {
        "skill_name": "AI / Machine Learning",
        "skill_category": "AI/ML",
        "confidence_score": 88,
        "support_status": "strongly_supported",
        "evidence_count": 7,
        "strongest_proof": {
            "label": "Workflow recording",
            "reason": "Live model inference workflow observed in 3 recordings",
        },
        "weakest_proof": {
            "label": "Keyframes / screenshots",
            "reason": "AI-related UI visible in 2 of 3 keyframe sets — raw frames protected",
        },
        "missing_evidence": ["Deployment evidence or live app URL"],
        "next_actions": [
            "Add a model evaluation report or demo showing input/output and accuracy metrics."
        ],
        "evidence_sources": [
            {"key": "workflow",  "label": "Workflow recording",    "status": "supported", "score": 88, "reason": "Live model inference workflow observed"},
            {"key": "github",   "label": "GitHub code",            "status": "supported", "score": 91, "reason": "ML pipeline and evaluator service files confirmed"},
            {"key": "defense",  "label": "Project defense",        "status": "supported", "score": 84, "reason": "Candidate explained model selection, training, and evaluation"},
            {"key": "documents","label": "Documents",              "status": "supported", "score": 79, "reason": "Project report covers ML methodology"},
            {"key": "ocr",      "label": "OCR / visual reasoning", "status": "partial",   "score": 65, "reason": "Inference output text extracted; some frames inconclusive"},
            {"key": "keyframes","label": "Keyframes / screenshots","status": "partial",   "score": 72, "reason": "AI-related UI visible in 2 of 3 keyframe sets"},
            {"key": "dom",      "label": "DOM Evidence",           "status": "supported", "score": 78, "reason": "Captured page structure, visible UI labels, and proof builder state changes support this skill."},
        ],
        "recruiter_summary": (
            "Evidence suggests strong AI/ML proficiency: workflow recordings confirm live "
            "model inference, GitHub code shows ML pipeline implementation, and a project "
            "defense transcript demonstrates technical depth."
        ),
        "student_summary": (
            "Your AI/ML evidence is strong. Add a deployment demo or live app URL to "
            "reach maximum confidence."
        ),
        "visibility_status": "public",
    },
    {
        "skill_name": "JavaScript / Frontend",
        "skill_category": "Frontend",
        "confidence_score": 74,
        "support_status": "partially_supported",
        "evidence_count": 4,
        "strongest_proof": {
            "label": "GitHub code",
            "reason": "React dashboard with modal state, tab navigation, and conditional rendering confirmed",
        },
        "weakest_proof": {
            "label": "OCR / visual reasoning",
            "reason": "UI elements captured but limited component test coverage observed",
        },
        "missing_evidence": ["UI test recording or accessibility coverage documentation"],
        "next_actions": [
            "Add a UI test recording or show component state handling and accessibility coverage."
        ],
        "evidence_sources": [
            {"key": "github",   "label": "GitHub code",            "status": "supported", "score": 85, "reason": "React components and DOM interaction confirmed"},
            {"key": "workflow", "label": "Workflow recording",     "status": "supported", "score": 78, "reason": "Frontend interaction workflow observed"},
            {"key": "ocr",      "label": "OCR / visual reasoning", "status": "partial",   "score": 61, "reason": "UI elements captured; limited test coverage observed"},
            {"key": "dom",      "label": "DOM Evidence",           "status": "partial",   "score": 68, "reason": "React component tree captured; modal and tab state confirmed"},
        ],
        "recruiter_summary": (
            "Evidence suggests solid JavaScript/Frontend skills: GitHub confirms a React "
            "dashboard with state management; workflow recordings show live UI interaction."
        ),
        "student_summary": (
            "Add UI test recordings or accessibility coverage to strengthen this pipeline."
        ),
        "visibility_status": "public",
    },
    {
        "skill_name": "Data & Visualization",
        "skill_category": "Data",
        "confidence_score": 65,
        "support_status": "partially_supported",
        "evidence_count": 3,
        "strongest_proof": {
            "label": "Workflow recording",
            "reason": "Chart and dashboard interaction observed; D3 SVG elements confirmed in DOM capture",
        },
        "weakest_proof": {
            "label": "Documents",
            "reason": "Project report present but limited data pipeline depth documented",
        },
        "missing_evidence": ["Data source, transformation step, and chart output together"],
        "next_actions": [
            "Show data source, transformation step, and chart output together in one recording or document."
        ],
        "evidence_sources": [
            {"key": "workflow", "label": "Workflow recording",    "status": "supported", "score": 79, "reason": "Chart interaction and D3 SVG elements observed"},
            {"key": "ocr",      "label": "OCR / visual reasoning","status": "partial",   "score": 62, "reason": "Chart labels extracted; data pipeline not fully visible"},
            {"key": "documents","label": "Documents",             "status": "supported", "score": 71, "reason": "Project report covers data visualization approach"},
        ],
        "recruiter_summary": (
            "Evidence partially supports Data & Visualization: workflow shows interactive "
            "charting, but data pipeline depth is limited."
        ),
        "student_summary": (
            "Show a data source and transformation step alongside the chart to improve confidence."
        ),
        "visibility_status": "public",
    },
    {
        "skill_name": "DevOps / Deployment",
        "skill_category": "DevOps",
        "confidence_score": 38,
        "support_status": "needs_review",
        "evidence_count": 1,
        "strongest_proof": {
            "label": "GitHub code",
            "reason": "Basic project structure present; no deployment config found",
        },
        "weakest_proof": {
            "label": "Workflow recording",
            "reason": "No deployment workflow captured in current recordings",
        },
        "missing_evidence": [
            "Dockerfile, CI config, or deployment guide",
            "Live deployed app URL",
        ],
        "next_actions": [
            "Deploy the app and upload documentation such as a Dockerfile, CI config, or deployment guide."
        ],
        "evidence_sources": [
            {"key": "github", "label": "GitHub code", "status": "partial", "score": 38, "reason": "Project structure present; no deployment config found"},
        ],
        "recruiter_summary": (
            "Insufficient deployment evidence at this time. Candidate has a GitHub repo "
            "but no deployment artifacts have been submitted."
        ),
        "student_summary": (
            "Deploy your app and add a Dockerfile or CI config to unlock this skill pipeline."
        ),
        "visibility_status": "public",
    },
]

_MVP_GITHUB_ARTIFACTS: dict[str, list[dict[str, Any]]] = {
    "AI / Machine Learning": [
        {
            "source_type": "github",
            "source_title": "final_evidence_evaluator_service.py",
            "project_name": "VeriBridge AI Proof System",
            "visibility": "public",
            "confidence_score": 88,
            "relevance_to_skill": "Combines workflow, GitHub, OCR, transcript, and document signals into final skill confidence",
            "proof_reason": "ML pipeline and evaluator service implementation confirmed",
            "artifact_data": {
                "repo_url": "https://github.com/veribridge-ai/veribridge",
                "branch": "main",
                "file_path": "apps/api/app/services/final_evidence_evaluator_service.py",
                "start_line": 40,
                "end_line": 140,
                "symbol_name": "FinalEvidenceEvaluatorService",
                "code_reason": "Combines multi-source skill signals into weighted confidence score",
            },
        },
        {
            "source_type": "github",
            "source_title": "extension_proof_workflow_analysis_service.py",
            "project_name": "VeriBridge AI Proof System",
            "visibility": "public",
            "confidence_score": 85,
            "relevance_to_skill": "Analyzes browser workflow signals to extract skill evidence",
            "proof_reason": "Core ML signal processing layer confirmed",
            "artifact_data": {
                "repo_url": "https://github.com/veribridge-ai/veribridge",
                "branch": "main",
                "file_path": "apps/api/app/services/extension_proof_workflow_analysis_service.py",
                "start_line": 80,
                "end_line": 180,
                "symbol_name": "WorkflowAnalysisService",
                "code_reason": "Analyzes browser workflow events and maps to claimed skills",
            },
        },
    ],
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return str(uuid4())


def _strip_unsafe_artifact_data(data: dict[str, Any]) -> dict[str, Any]:
    """Remove keys that must never appear in recruiter-facing payloads."""
    return {k: v for k, v in data.items() if k not in _UNSAFE_ARTIFACT_KEYS}


def _compute_github_urls(artifact_data: dict[str, Any]) -> tuple[str, str]:
    """Compute exact_code_url and full_file_url from artifact_data for GitHub artifacts."""
    repo_url = artifact_data.get("repo_url", "")
    branch = artifact_data.get("branch", "main")
    file_path = artifact_data.get("file_path", "")
    start_line = artifact_data.get("start_line")
    end_line = artifact_data.get("end_line")

    if not repo_url or not file_path:
        return "", ""

    full_file = f"{repo_url}/blob/{branch}/{file_path}"
    if start_line is not None and end_line is not None:
        exact = f"{full_file}#L{start_line}-L{end_line}"
    else:
        exact = full_file

    return exact, full_file


def _artifact_row_to_response(row: dict[str, Any]) -> SkillEvidenceArtifactResponse:
    artifact_data = row.get("artifact_data") or {}
    exact_url, full_url = ("", "")
    if row.get("source_type") == "github":
        exact_url, full_url = _compute_github_urls(artifact_data)

    return SkillEvidenceArtifactResponse(
        id=str(row["id"]),
        pipeline_id=str(row["pipeline_id"]),
        proof_session_id=str(row["proof_session_id"]) if row.get("proof_session_id") else None,
        source_type=str(row["source_type"]),
        source_title=str(row["source_title"]),
        project_name=str(row.get("project_name") or ""),
        visibility=str(row["visibility"]),
        confidence_score=int(row.get("confidence_score") or 0),
        relevance_to_skill=str(row.get("relevance_to_skill") or ""),
        proof_reason=str(row.get("proof_reason") or ""),
        artifact_data=artifact_data,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        exact_code_url=exact_url or None,
        full_file_url=full_url or None,
    )


def _artifact_response_to_student_summary(art: SkillEvidenceArtifactResponse) -> StudentArtifactSummary:
    """Build a safe, student-facing artifact summary.

    Excludes artifact_data entirely (no raw document text, storage paths,
    signed URLs, or tokens) — only the fields needed to group and label
    artifacts in the student's own Manage Skill Evidence UI.
    """
    return StudentArtifactSummary(
        id=art.id,
        source_type=art.source_type,
        source_title=art.source_title,
        project_name=art.project_name,
        visibility=art.visibility,
        confidence_score=art.confidence_score,
        proof_reason=art.proof_reason,
        exact_code_url=art.exact_code_url,
        full_file_url=art.full_file_url,
    )


def _pipeline_row_to_response(row: dict[str, Any]) -> SkillEvidencePipelineResponse:
    return SkillEvidencePipelineResponse(
        id=str(row["id"]),
        student_id=str(row["student_id"]) if row.get("student_id") else None,
        profile_id=str(row["profile_id"]) if row.get("profile_id") else None,
        skill_name=str(row["skill_name"]),
        skill_category=str(row.get("skill_category") or "technical"),
        confidence_score=int(row.get("confidence_score") or 0),
        support_status=str(row.get("support_status") or "needs_review"),
        evidence_count=int(row.get("evidence_count") or 0),
        strongest_proof=row.get("strongest_proof") or {},
        weakest_proof=row.get("weakest_proof") or {},
        missing_evidence=row.get("missing_evidence") or [],
        next_actions=row.get("next_actions") or [],
        evidence_sources=row.get("evidence_sources") or [],
        recruiter_summary=str(row.get("recruiter_summary") or ""),
        student_summary=str(row.get("student_summary") or ""),
        visibility_status=str(row.get("visibility_status") or "public"),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


# ── Custom exceptions ─────────────────────────────────────────────────────────


class PipelineNotFoundError(LookupError):
    """No pipeline found for the given ID / user."""


class ArtifactNotFoundError(LookupError):
    """No artifact found for the given ID / pipeline."""


# ── Service ───────────────────────────────────────────────────────────────────


class SkillEvidencePipelineService:
    """CRUD + sanitization for skill evidence pipelines and artifacts.

    Supports both a real Supabase client (production) and an in-memory
    dict store (unit tests).
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    # ── Private dict-mode helpers ─────────────────────────────────────────────

    def _dict_table(self, table: str) -> dict[str, dict[str, Any]]:
        assert isinstance(self._client, dict)
        return self._client.setdefault(table, {})

    def _dict_insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        store = self._dict_table(table)
        store[row["id"]] = row
        return row

    def _dict_update(self, table: str, row_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        store = self._dict_table(table)
        store[row_id] = {**store[row_id], **patch, "updated_at": _now()}
        return store[row_id]

    def _dict_find_pipeline(self, pipeline_id: str) -> dict[str, Any] | None:
        return self._dict_table(_PIPELINES_TABLE).get(pipeline_id)

    def _dict_list_pipelines_for_user(self, student_id: str) -> list[dict[str, Any]]:
        return [
            r for r in self._dict_table(_PIPELINES_TABLE).values()
            if str(r.get("student_id")) == student_id
        ]

    def _dict_list_artifacts_for_pipeline(self, pipeline_id: str) -> list[dict[str, Any]]:
        return [
            r for r in self._dict_table(_ARTIFACTS_TABLE).values()
            if str(r.get("pipeline_id")) == pipeline_id
        ]

    # ── Pipeline operations ───────────────────────────────────────────────────

    def list_pipelines_for_student(self, student_id: str) -> list[SkillEvidencePipelineResponse]:
        """Return all pipelines owned by the student, including a safe
        summary of each pipeline's own evidence artifacts."""
        if isinstance(self._client, dict):
            rows = self._dict_list_pipelines_for_user(student_id)
        else:
            result = (
                self._client.table(_PIPELINES_TABLE)
                .select("*")
                .eq("student_id", student_id)
                .order("confidence_score", desc=True)
                .execute()
            )
            rows = getattr(result, "data", []) or []

        pipelines = [_pipeline_row_to_response(r) for r in rows]
        for pipeline in pipelines:
            artifacts = self._list_artifacts_for_pipeline_by_id(pipeline.id)
            pipeline.artifacts = [_artifact_response_to_student_summary(a) for a in artifacts]
        return pipelines

    def has_artifact_matching(self, student_id: str, **artifact_data_filters: str) -> bool:
        """True when any of the student's pipelines carries an artifact whose
        ``artifact_data`` matches every given (field, value) pair.

        Two queries on Supabase (pipeline ids + one filtered artifact lookup)
        instead of scanning every artifact of every pipeline — the sync
        services' idempotency checks call this on every save.
        """
        if isinstance(self._client, dict):
            pipeline_ids = {
                str(r.get("id")) for r in self._dict_list_pipelines_for_user(student_id)
            }
            return any(
                str(r.get("pipeline_id")) in pipeline_ids
                and all(
                    (r.get("artifact_data") or {}).get(field) == value
                    for field, value in artifact_data_filters.items()
                )
                for r in self._dict_table(_ARTIFACTS_TABLE).values()
            )
        rows_result = (
            self._client.table(_PIPELINES_TABLE).select("id").eq("student_id", student_id).execute()
        )
        pipeline_ids = [str(r["id"]) for r in (getattr(rows_result, "data", []) or [])]
        if not pipeline_ids:
            return False
        query = (
            self._client.table(_ARTIFACTS_TABLE)
            .select("id")
            .in_("pipeline_id", pipeline_ids)
        )
        for field, value in artifact_data_filters.items():
            query = query.eq(f"artifact_data->>{field}", value)
        result = query.limit(1).execute()
        return bool(getattr(result, "data", []) or [])

    def has_artifact_for_session(
        self, student_id: str, *, kind: str, vbr_session_id: str
    ) -> bool:
        """True when any of the student's pipelines carries an artifact whose
        ``artifact_data`` matches (kind, vbr_session_id)."""
        return self.has_artifact_matching(student_id, kind=kind, vbr_session_id=vbr_session_id)

    def list_pipeline_rows_for_student(self, student_id: str) -> list[SkillEvidencePipelineResponse]:
        """Pipelines owned by the student WITHOUT their artifact summaries.

        One query instead of 1+N — for callers (e.g. sync services) that only
        need the pipeline rows themselves and would otherwise trigger an
        artifact fetch per pipeline.
        """
        if isinstance(self._client, dict):
            rows = self._dict_list_pipelines_for_user(student_id)
        else:
            result = (
                self._client.table(_PIPELINES_TABLE)
                .select("*")
                .eq("student_id", student_id)
                .order("confidence_score", desc=True)
                .execute()
            )
            rows = getattr(result, "data", []) or []
        return [_pipeline_row_to_response(r) for r in rows]

    def get_pipeline(self, pipeline_id: str, student_id: str) -> SkillEvidencePipelineResponse:
        """Fetch a single pipeline (with its own artifact summaries);
        raises PipelineNotFoundError if absent."""
        if isinstance(self._client, dict):
            row = self._dict_find_pipeline(pipeline_id)
            if not row or str(row.get("student_id")) != student_id:
                raise PipelineNotFoundError(f"Pipeline {pipeline_id} not found")
        else:
            result = (
                self._client.table(_PIPELINES_TABLE)
                .select("*")
                .eq("id", pipeline_id)
                .eq("student_id", student_id)
                .limit(1)
                .execute()
            )
            rows = getattr(result, "data", []) or []
            if not rows:
                raise PipelineNotFoundError(f"Pipeline {pipeline_id} not found")
            row = rows[0]

        pipeline = _pipeline_row_to_response(row)
        artifacts = self._list_artifacts_for_pipeline_by_id(pipeline.id)
        pipeline.artifacts = [_artifact_response_to_student_summary(a) for a in artifacts]
        return pipeline

    def upsert_pipeline(
        self,
        student_id: str,
        payload: SkillEvidencePipelineCreate,
        profile_id: str | None = None,
    ) -> SkillEvidencePipelineResponse:
        """Create or update (by student_id + skill_name) a skill pipeline."""
        now = _now()

        if isinstance(self._client, dict):
            # Find existing by student_id + skill_name
            existing = next(
                (
                    r for r in self._dict_table(_PIPELINES_TABLE).values()
                    if str(r.get("student_id")) == student_id
                    and r.get("skill_name") == payload.skill_name
                ),
                None,
            )
            if existing:
                patch = {
                    **payload.model_dump(),
                    "updated_at": now,
                }
                return _pipeline_row_to_response(
                    self._dict_update(_PIPELINES_TABLE, existing["id"], patch)
                )
            row = {
                "id": _new_id(),
                "student_id": student_id,
                "profile_id": profile_id,
                **payload.model_dump(),
                "created_at": now,
                "updated_at": now,
            }
            return _pipeline_row_to_response(self._dict_insert(_PIPELINES_TABLE, row))

        # Supabase upsert (unique index on student_id + skill_name)
        data = {
            "student_id": student_id,
            "profile_id": profile_id,
            **payload.model_dump(),
            "updated_at": now,
        }
        result = (
            self._client.table(_PIPELINES_TABLE)
            .upsert(data, on_conflict="student_id,skill_name")
            .execute()
        )
        rows = getattr(result, "data", []) or []
        return _pipeline_row_to_response(rows[0])

    # ── Artifact operations ───────────────────────────────────────────────────

    def add_artifact(
        self,
        student_id: str,
        payload: SkillEvidenceArtifactCreate,
    ) -> SkillEvidenceArtifactResponse:
        """Add an evidence artifact to a pipeline owned by student_id."""
        # Verify pipeline ownership
        pipeline = self.get_pipeline(payload.pipeline_id, student_id)
        now = _now()

        row: dict[str, Any] = {
            "id": _new_id(),
            "pipeline_id": pipeline.id,
            "proof_session_id": payload.proof_session_id,
            "source_type": payload.source_type,
            "source_title": payload.source_title,
            "project_name": payload.project_name,
            "visibility": payload.visibility,
            "confidence_score": payload.confidence_score,
            "relevance_to_skill": payload.relevance_to_skill,
            "proof_reason": payload.proof_reason,
            "artifact_data": payload.artifact_data,
            "created_at": now,
            "updated_at": now,
        }

        if isinstance(self._client, dict):
            return _artifact_row_to_response(self._dict_insert(_ARTIFACTS_TABLE, row))

        result = self._client.table(_ARTIFACTS_TABLE).insert(row).execute()
        rows = getattr(result, "data", []) or []
        return _artifact_row_to_response(rows[0])

    def list_artifacts_for_pipeline(
        self,
        pipeline_id: str,
        student_id: str,
    ) -> list[SkillEvidenceArtifactResponse]:
        """Return all artifacts for a pipeline owned by student_id."""
        # Verify ownership
        self.get_pipeline(pipeline_id, student_id)

        if isinstance(self._client, dict):
            rows = self._dict_list_artifacts_for_pipeline(pipeline_id)
        else:
            result = (
                self._client.table(_ARTIFACTS_TABLE)
                .select("*")
                .eq("pipeline_id", pipeline_id)
                .order("created_at", desc=False)
                .execute()
            )
            rows = getattr(result, "data", []) or []

        return [_artifact_row_to_response(r) for r in rows]

    # ── MVP mock pipeline builder ─────────────────────────────────────────────

    def build_mock_pipelines_for_student(
        self,
        student_id: str,
        profile_id: str | None = None,
    ) -> list[SkillEvidencePipelineResponse]:
        """Create or refresh deterministic MVP pipelines for a student.

        Designed for WPI career fair testing: seeds the database with
        realistic pipelines based on the standard skill bundle.  Real
        evidence aggregation can replace this later without schema changes.
        """
        results = []
        for defn in _MVP_PIPELINES:
            payload = SkillEvidencePipelineCreate(**defn)
            pipeline = self.upsert_pipeline(student_id, payload, profile_id)
            results.append(pipeline)

            # Seed GitHub artifacts for AI/ML
            if defn["skill_name"] in _MVP_GITHUB_ARTIFACTS:
                existing_artifacts = self._existing_artifact_count(pipeline.id)
                if existing_artifacts == 0:
                    for art_defn in _MVP_GITHUB_ARTIFACTS[defn["skill_name"]]:
                        artifact_payload = SkillEvidenceArtifactCreate(
                            pipeline_id=pipeline.id,
                            **art_defn,
                        )
                        self.add_artifact(student_id, artifact_payload)

        return results

    def _existing_artifact_count(self, pipeline_id: str) -> int:
        if isinstance(self._client, dict):
            return len(self._dict_list_artifacts_for_pipeline(pipeline_id))
        try:
            result = (
                self._client.table(_ARTIFACTS_TABLE)
                .select("id", count="exact")
                .eq("pipeline_id", pipeline_id)
                .execute()
            )
            return getattr(result, "count", 0) or 0
        except Exception:
            return 0

    # ── Visibility updates ────────────────────────────────────────────────────

    def update_pipeline_visibility(
        self,
        pipeline_id: str,
        student_id: str,
        visibility: str,
    ) -> SkillEvidencePipelineResponse:
        """Update visibility_status for a pipeline owned by student_id."""
        # Ownership check (raises PipelineNotFoundError if not found or wrong user)
        self.get_pipeline(pipeline_id, student_id)
        now = _now()

        if isinstance(self._client, dict):
            row = self._dict_update(_PIPELINES_TABLE, pipeline_id, {"visibility_status": visibility})
            return _pipeline_row_to_response(row)

        result = (
            self._client.table(_PIPELINES_TABLE)
            .update({"visibility_status": visibility, "updated_at": now})
            .eq("id", pipeline_id)
            .eq("student_id", student_id)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        return _pipeline_row_to_response(rows[0])

    def update_artifact_visibility(
        self,
        artifact_id: str,
        student_id: str,
        visibility: str,
    ) -> SkillEvidenceArtifactResponse:
        """Update visibility for an artifact whose pipeline is owned by student_id."""
        if isinstance(self._client, dict):
            artifact_row = self._dict_table(_ARTIFACTS_TABLE).get(artifact_id)
            if not artifact_row:
                raise ArtifactNotFoundError(f"Artifact {artifact_id} not found")
            # Verify pipeline ownership
            pipeline_id = str(artifact_row["pipeline_id"])
            self.get_pipeline(pipeline_id, student_id)
            updated = self._dict_update(_ARTIFACTS_TABLE, artifact_id, {"visibility": visibility})
            return _artifact_row_to_response(updated)

        # Supabase path: fetch artifact, verify pipeline ownership, then update
        art_result = (
            self._client.table(_ARTIFACTS_TABLE)
            .select("*")
            .eq("id", artifact_id)
            .limit(1)
            .execute()
        )
        art_rows = getattr(art_result, "data", []) or []
        if not art_rows:
            raise ArtifactNotFoundError(f"Artifact {artifact_id} not found")

        pipeline_id = str(art_rows[0]["pipeline_id"])
        self.get_pipeline(pipeline_id, student_id)

        now = _now()
        result = (
            self._client.table(_ARTIFACTS_TABLE)
            .update({"visibility": visibility, "updated_at": now})
            .eq("id", artifact_id)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        return _artifact_row_to_response(rows[0])

    # ── Recruiter sanitization ────────────────────────────────────────────────

    def _list_artifacts_for_pipeline_by_id(
        self,
        pipeline_id: str,
    ) -> list[SkillEvidenceArtifactResponse]:
        """Fetch artifacts without an ownership check.

        Caller must already have confirmed pipeline ownership.
        """
        if isinstance(self._client, dict):
            rows = self._dict_list_artifacts_for_pipeline(pipeline_id)
        else:
            result = (
                self._client.table(_ARTIFACTS_TABLE)
                .select("*")
                .eq("pipeline_id", pipeline_id)
                .order("created_at", desc=False)
                .execute()
            )
            rows = getattr(result, "data", []) or []
        return [_artifact_row_to_response(r) for r in rows]

    def sanitize_recruiter_payload(
        self,
        pipeline: SkillEvidencePipelineResponse,
        artifacts: list[SkillEvidenceArtifactResponse],
        access_approved: bool = False,
    ) -> RecruiterPipelineSummary:
        """Build a recruiter-safe view of a pipeline.

        Visibility rules applied here:
        - Private pipeline: caller should exclude; if passed, returns empty artifacts.
        - Protected pipeline without approval:
            is_locked_for_recruiter=True, generic recruiter_summary,
            no detailed artifact_data exposed.
        - Public (or approved protected) pipeline: full safe payload; private artifacts
            excluded; public and protected artifacts both show their sanitized data.
            Artifact-level protected visibility is preserved as a label so the recruiter
            knows the student controls sharing, but the safe stored data is shown.

        Unsafe fields are always stripped: storage_path, signed_url,
        access_token, and similar keys defined in _UNSAFE_ARTIFACT_KEYS.
        Data stored by the sync service is already sanitized before storage, so it is
        safe to surface here once the pipeline-level gate (is_locked) allows access.
        """
        is_locked = (
            pipeline.visibility_status == "protected" and not access_approved
        )

        safe_artifacts: list[dict[str, Any]] = []
        for art in artifacts:
            if art.visibility in _RECRUITER_HIDDEN_VISIBILITIES:
                continue  # always hide private/locked/unavailable

            if is_locked:
                # Locked pipeline: minimal card with no detail — pipeline gate blocks all data
                entry: dict[str, Any] = {
                    "id": art.id,
                    "source_type": art.source_type,
                    "source_title": art.source_title,
                    "project_name": art.project_name,
                    "visibility": "protected",
                    "confidence_score": art.confidence_score,
                    "proof_reason": "",
                    "artifact_data": {},
                }
            else:
                # Public or approved pipeline: show sanitized data for all visible artifacts
                safe_data = _strip_unsafe_artifact_data(art.artifact_data)
                entry = {
                    "id": art.id,
                    "source_type": art.source_type,
                    "source_title": art.source_title,
                    "project_name": art.project_name,
                    "visibility": art.visibility,
                    "confidence_score": art.confidence_score,
                    "proof_reason": art.proof_reason,
                    "artifact_data": safe_data,
                }
                if art.exact_code_url:
                    entry["exact_code_url"] = art.exact_code_url
                if art.full_file_url:
                    entry["full_file_url"] = art.full_file_url
            safe_artifacts.append(entry)

        if is_locked:
            # Protected pipeline: return minimal locked summary.
            # Strip proof details (reasons, missing evidence, next actions) to prevent
            # evidence detail leakage before the recruiter receives student approval.
            # Source coverage keys/labels/status are kept so the locked card can show
            # which evidence types exist, but reasons and scores are stripped.
            locked_sources = [
                {
                    "key": s.get("key", "") if isinstance(s, dict) else getattr(s, "key", ""),
                    "label": s.get("label", "") if isinstance(s, dict) else getattr(s, "label", ""),
                    "status": "protected",
                    "score": None,
                    "reason": "",
                }
                for s in (pipeline.evidence_sources or [])
            ]
            return RecruiterPipelineSummary(
                id=pipeline.id,
                skill_name=pipeline.skill_name,
                skill_category=pipeline.skill_category,
                confidence_score=pipeline.confidence_score,
                support_status=pipeline.support_status,
                evidence_count=pipeline.evidence_count,
                strongest_proof={},
                weakest_proof={},
                missing_evidence=[],
                next_actions=[],
                evidence_sources=locked_sources,
                recruiter_summary="Protected evidence available. Student approval required to inspect protected details.",
                visibility_status=pipeline.visibility_status,
                is_locked_for_recruiter=True,
                artifacts=[],
            )

        return RecruiterPipelineSummary(
            id=pipeline.id,
            skill_name=pipeline.skill_name,
            skill_category=pipeline.skill_category,
            confidence_score=pipeline.confidence_score,
            support_status=pipeline.support_status,
            evidence_count=pipeline.evidence_count,
            strongest_proof=pipeline.strongest_proof,
            weakest_proof=pipeline.weakest_proof,
            missing_evidence=pipeline.missing_evidence,
            next_actions=pipeline.next_actions,
            evidence_sources=pipeline.evidence_sources,
            recruiter_summary=pipeline.recruiter_summary,
            visibility_status=pipeline.visibility_status,
            is_locked_for_recruiter=False,
            artifacts=safe_artifacts,
        )

    def list_recruiter_safe_pipelines(
        self,
        student_id: str,
        access_approved: bool = False,
    ) -> list[RecruiterPipelineSummary]:
        """List all non-private pipelines for a student in recruiter-safe format.

        Enforces student visibility choices server-side:
        - private pipelines are excluded entirely
        - protected pipelines are returned as locked summaries
        - public pipelines are returned with full safe payload
        """
        all_pipelines = self.list_pipelines_for_student(student_id)
        result: list[RecruiterPipelineSummary] = []
        for pipeline in all_pipelines:
            # Exclude private pipelines — handle any "private*" variant defensively.
            if pipeline.visibility_status in _PRIVATE_VISIBILITY_VALUES:
                continue
            artifacts = self._list_artifacts_for_pipeline_by_id(pipeline.id)
            summary = self.sanitize_recruiter_payload(
                pipeline, artifacts, access_approved=access_approved
            )
            result.append(summary)
        return result
