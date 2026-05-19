"""Skill Proof Evidence persistence and mock verification service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.schemas.skill_evidence import (
    SkillEvidenceCreate,
    SkillEvidenceResponse,
    SkillEvidenceUpdate,
)
from app.services.github_evidence_service import verify_github_file_evidence

_TABLE = "skill_evidence"
_MOCK_VERIFIER_VERSION = "mock-v1"


class SkillEvidenceNotFoundError(LookupError):
    """Evidence row was not found for the scoped user."""


class SkillEvidenceService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def list_skill_evidence(self, user_id: str) -> list[SkillEvidenceResponse]:
        if isinstance(self._client, dict):
            rows = [
                row
                for row in self._client.setdefault(_TABLE, {}).values()
                if row["user_id"] == user_id
            ]
            rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
            return [_to_response(row) for row in rows]

        result = (
            self._client.table(_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [_to_response(row) for row in (getattr(result, "data", []) or [])]

    def create_skill_evidence(self, user_id: str, payload: SkillEvidenceCreate) -> SkillEvidenceResponse:
        verification = verify_evidence(payload)
        payload_data = payload.model_dump()
        payload_data["metadata"] = _merge_verification_metadata(payload_data.get("metadata"), verification)
        payload_data["proof_visibility"] = payload_data.get("proof_visibility") or "public"
        data = {
            **payload_data,
            "user_id": user_id,
            "verification_status": verification["status"],
            "verification_summary": verification["summary"],
            "verifier_version": verification["verifier_version"],
        }

        if isinstance(self._client, dict):
            now = _now()
            row = {
                "id": str(uuid4()),
                "created_at": now,
                "updated_at": now,
                **data,
            }
            self._client.setdefault(_TABLE, {})[row["id"]] = row
            return _to_response(row)

        result = self._client.table(_TABLE).insert(data).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError("Skill evidence insert returned no data.")
        return _to_response(rows[0])

    def get_skill_evidence(self, user_id: str, evidence_id: str) -> SkillEvidenceResponse:
        row = self._get_row(user_id, evidence_id)
        return _to_response(row)

    def update_skill_evidence(
        self,
        user_id: str,
        evidence_id: str,
        payload: SkillEvidenceUpdate,
    ) -> SkillEvidenceResponse:
        current = self._get_row(user_id, evidence_id)
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return _to_response(current)
        if updates.get("metadata") is None:
            updates["metadata"] = {}
        if updates.get("proof_visibility") is None:
            updates["proof_visibility"] = "public"

        relevant = {
            "skill_name",
            "evidence_type",
            "evidence_url",
            "repository_url",
            "file_path",
            "line_start",
            "line_end",
            "evidence_description",
            "proof_visibility",
            "metadata",
        }
        if relevant.intersection(updates):
            merged = {**current, **updates}
            verification = verify_evidence(merged)
            updates["metadata"] = _merge_verification_metadata(updates.get("metadata") or current.get("metadata"), verification)
            updates.update(
                {
                    "verification_status": verification["status"],
                    "verification_summary": verification["summary"],
                    "verifier_version": verification["verifier_version"],
                }
            )

        if isinstance(self._client, dict):
            row = {
                **current,
                **updates,
                "updated_at": _now(),
            }
            self._client.setdefault(_TABLE, {})[evidence_id] = row
            return _to_response(row)

        result = (
            self._client.table(_TABLE)
            .update(updates)
            .eq("user_id", user_id)
            .eq("id", evidence_id)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        if not rows:
            raise SkillEvidenceNotFoundError(evidence_id)
        return _to_response(rows[0])

    def delete_skill_evidence(self, user_id: str, evidence_id: str) -> None:
        self._get_row(user_id, evidence_id)

        if isinstance(self._client, dict):
            self._client.setdefault(_TABLE, {}).pop(evidence_id, None)
            return

        self._client.table(_TABLE).delete().eq("user_id", user_id).eq("id", evidence_id).execute()

    def verify_skill_evidence(self, user_id: str, evidence_id: str) -> SkillEvidenceResponse:
        current = self._get_row(user_id, evidence_id)
        verification = verify_evidence(current)
        updates = {
            "verification_status": verification["status"],
            "verification_summary": verification["summary"],
            "verifier_version": verification["verifier_version"],
            "metadata": _merge_verification_metadata(current.get("metadata"), verification),
        }

        if isinstance(self._client, dict):
            row = {
                **current,
                **updates,
                "updated_at": _now(),
            }
            self._client.setdefault(_TABLE, {})[evidence_id] = row
            return _to_response(row)

        result = (
            self._client.table(_TABLE)
            .update(updates)
            .eq("user_id", user_id)
            .eq("id", evidence_id)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        if not rows:
            raise SkillEvidenceNotFoundError(evidence_id)
        return _to_response(rows[0])

    def _get_row(self, user_id: str, evidence_id: str) -> dict[str, Any]:
        if isinstance(self._client, dict):
            row = self._client.setdefault(_TABLE, {}).get(evidence_id)
            if not row or row.get("user_id") != user_id:
                raise SkillEvidenceNotFoundError(evidence_id)
            return row

        result = (
            self._client.table(_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", evidence_id)
            .maybe_single()
            .execute()
        )
        if result is None:
            raise SkillEvidenceNotFoundError(evidence_id)
        return result.data


def verify_evidence(payload_or_record: Any) -> dict[str, str]:
    github_verification = verify_github_file_evidence(payload_or_record)
    if github_verification is not None:
        return github_verification
    return verify_evidence_mock(payload_or_record)


def verify_evidence_mock(payload_or_record: Any) -> dict[str, str]:
    data = _as_dict(payload_or_record)
    skill = str(data.get("skill_name") or "").strip().lower()
    path = str(data.get("file_path") or "").strip().lower()
    description = str(data.get("evidence_description") or "").strip().lower()
    evidence_url = str(data.get("evidence_url") or "").strip().lower()
    repository_url = str(data.get("repository_url") or "").strip().lower()
    combined = f"{path} {description} {evidence_url} {repository_url}"

    def verified(summary: str) -> dict[str, str]:
        return {
            "status": "verified",
            "summary": summary,
            "verifier_version": _MOCK_VERIFIER_VERSION,
        }

    if "python" in skill and path.endswith((".py", ".ipynb")):
        return verified("Python usage likely found from Python/Notebook file path.")

    ml_skill = _contains_any(
        skill,
        ("machine learning", "ml", "deep learning", "data science", "artificial intelligence", "ai"),
    )
    ml_keywords = (
        "model",
        "decision tree",
        "random forest",
        "regression",
        "classification",
        "neural network",
        "training",
        "prediction",
        "sklearn",
        "scikit-learn",
        "pytorch",
        "tensorflow",
        "xgboost",
        "lightgbm",
    )
    if ml_skill and (path.endswith((".py", ".ipynb")) or _contains_any(description, ml_keywords)):
        return verified("Machine learning evidence likely found from file path or ML keywords.")

    if _contains_any(skill, ("javascript", "typescript")) and path.endswith((".js", ".jsx", ".ts", ".tsx")):
        return verified("JavaScript/TypeScript usage likely found.")

    if "sql" in skill and path.endswith(".sql"):
        return verified("SQL usage likely found.")

    ai_llm_skill = _contains_any(
        skill,
        ("rag", "llm", "genai", "generative ai", "prompt engineering", "vector databases"),
    )
    ai_llm_keywords = (
        "rag",
        "llm",
        "prompt",
        "embedding",
        "vector",
        "langchain",
        "llamaindex",
        "openai",
        "anthropic",
        "retrieval",
    )
    if ai_llm_skill and _contains_any(combined, ai_llm_keywords):
        return verified("AI/LLM evidence likely found from RAG/LLM keywords.")

    mlops_skill = _contains_any(
        skill,
        ("mlops", "docker", "fastapi", "cloud", "ci/cd", "github actions", "deployment"),
    )
    mlops_keywords = (
        "dockerfile",
        "docker",
        "fastapi",
        "github actions",
        "ci",
        "cd",
        "deploy",
        "cloud",
        "api",
        "monitoring",
    )
    if mlops_skill and _contains_any(combined, mlops_keywords):
        return verified("MLOps/cloud evidence likely found from deployment keywords.")

    design_skill = _contains_any(skill, ("cad", "autocad", "solidworks", "revit", "figma", "ux", "design"))
    design_keywords = ("figma", "cad", "dwg", "sldprt", "revit", "rvt", "portfolio", "prototype", "design")
    if design_skill and _contains_any(combined, design_keywords):
        return verified("Design/CAD evidence likely found.")

    doc_path = path.endswith((".pdf", ".ppt", ".pptx", ".doc", ".docx"))
    useful_python_keywords = ("python", "fastapi", "api", "model", "prediction", "training", "notebook", "script")
    if "python" in skill and doc_path and not _contains_any(description, useful_python_keywords):
        return {
            "status": "skill_usage_not_found",
            "summary": "Skill usage not found in the provided file path. Please provide a file or link that clearly demonstrates this skill.",
            "verifier_version": _MOCK_VERIFIER_VERSION,
        }

    return {
        "status": "pending_review",
        "summary": "Pending review: VeriBridge needs GitHub/file/AI integration to inspect this evidence.",
        "verifier_version": _MOCK_VERIFIER_VERSION,
    }


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


def _as_dict(payload_or_record: Any) -> dict[str, Any]:
    if isinstance(payload_or_record, dict):
        return payload_or_record
    if hasattr(payload_or_record, "model_dump"):
        return payload_or_record.model_dump()
    return dict(payload_or_record)


def _to_response(row: dict[str, Any]) -> SkillEvidenceResponse:
    return SkillEvidenceResponse(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        skill_name=row["skill_name"],
        evidence_type=row["evidence_type"],
        evidence_url=row.get("evidence_url"),
        repository_url=row.get("repository_url"),
        file_path=row.get("file_path"),
        line_start=row.get("line_start"),
        line_end=row.get("line_end"),
        evidence_description=row.get("evidence_description"),
        proof_visibility=row.get("proof_visibility") or "public",
        metadata=row.get("metadata") or {},
        verification_status=row.get("verification_status") or "pending_review",
        verification_summary=row.get("verification_summary"),
        verifier_version=row.get("verifier_version"),
        github_code_evidence_summary=_github_code_evidence_summary_from_row(row),
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


def _merge_verification_metadata(metadata: Any, verification: dict[str, Any]) -> dict[str, Any]:
    merged = dict(metadata or {})
    github_summary = verification.get("github_code_evidence_summary")
    if github_summary:
        merged["github_code_evidence_summary"] = github_summary
    return merged


def _github_code_evidence_summary_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    metadata = row.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("github_code_evidence_summary"):
        return metadata.get("github_code_evidence_summary")
    value = row.get("github_code_evidence_summary")
    return value if isinstance(value, dict) else None


def _now() -> str:
    return datetime.now(UTC).isoformat()
