"""Rule-based public proof verification for stored skill evidence metadata."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from app.schemas.skill_evidence import PublicProofVerificationResponse
from app.services.github_evidence_service import parse_github_repo_url
from app.services.skill_evidence_service import SkillEvidenceNotFoundError

_EVIDENCE_TABLE = "skill_evidence"
_VERIFICATION_TABLE = "skill_evidence_verifications"
_VERIFIER_VERSION = "public-metadata-v1"


class PublicProofVerificationNotFoundError(LookupError):
    """No public verification result exists for the evidence row."""


class PublicProofNotVerifiableError(ValueError):
    """Evidence is not eligible for the public proof verifier."""


@dataclass(frozen=True)
class _ScoreInput:
    row: dict[str, Any]
    proof_url: str | None
    proof_kind: str | None
    text: str


class PublicProofVerificationService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def verify_public_proof(self, user_id: str, evidence_id: str) -> PublicProofVerificationResponse:
        row = self._get_evidence_row(user_id, evidence_id)
        score_input = _build_score_input(row)
        if not _is_public(row):
            raise PublicProofNotVerifiableError("Only public proof evidence can use the public verifier.")
        if score_input.proof_url is None:
            raise PublicProofNotVerifiableError("Public proof verification requires a public URL.")

        result = _score_public_proof(score_input)
        data = {
            **result,
            "user_id": user_id,
            "skill_evidence_id": evidence_id,
            "verification_type": "public_metadata",
            "verifier_version": _VERIFIER_VERSION,
            "input_snapshot": _input_snapshot(row, score_input.proof_kind),
        }

        if isinstance(self._client, dict):
            now = _now()
            stored = {
                "id": str(uuid4()),
                "created_at": now,
                **data,
            }
            self._client.setdefault(_VERIFICATION_TABLE, {})[stored["id"]] = stored
            return _to_response(stored)

        insert_result = self._client.table(_VERIFICATION_TABLE).insert(data).execute()
        rows = getattr(insert_result, "data", []) or []
        if not rows:
            raise RuntimeError("Public proof verification insert returned no data.")
        return _to_response(rows[0])

    def get_latest_public_verification(self, user_id: str, evidence_id: str) -> PublicProofVerificationResponse:
        self._get_evidence_row(user_id, evidence_id)

        if isinstance(self._client, dict):
            rows = [
                row
                for row in self._client.setdefault(_VERIFICATION_TABLE, {}).values()
                if row.get("user_id") == user_id and row.get("skill_evidence_id") == evidence_id
            ]
            if not rows:
                raise PublicProofVerificationNotFoundError(evidence_id)
            rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
            return _to_response(rows[0])

        result = (
            self._client.table(_VERIFICATION_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("skill_evidence_id", evidence_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        if not rows:
            raise PublicProofVerificationNotFoundError(evidence_id)
        return _to_response(rows[0])

    def _get_evidence_row(self, user_id: str, evidence_id: str) -> dict[str, Any]:
        if isinstance(self._client, dict):
            row = self._client.setdefault(_EVIDENCE_TABLE, {}).get(evidence_id)
            if not row or row.get("user_id") != user_id:
                raise SkillEvidenceNotFoundError(evidence_id)
            return row

        result = (
            self._client.table(_EVIDENCE_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", evidence_id)
            .maybe_single()
            .execute()
        )
        if result is None or not result.data:
            raise SkillEvidenceNotFoundError(evidence_id)
        return result.data


def _score_public_proof(score_input: _ScoreInput) -> dict[str, Any]:
    row = score_input.row
    skill = _clean(row.get("skill_name"))
    title = _title(row)
    description = _clean(row.get("evidence_description"))
    matched: list[str] = []
    missing: list[str] = []
    score = 0.0

    if skill:
        score += 0.10
        matched.append("Claimed skill is present on the proof record.")
    else:
        missing.append("Claimed skill is missing.")

    if score_input.proof_url:
        score += 0.20
        matched.append("A public proof URL is present.")

    if score_input.proof_kind:
        score += 0.15
        matched.append(f"Proof URL matches supported public proof type: {score_input.proof_kind}.")
    else:
        missing.append("Proof URL does not clearly match GitHub, deployed project, portfolio, or documentation proof.")

    if title:
        score += 0.08
        matched.append("Proof title or source label is present.")
    else:
        missing.append("Proof title or source label is missing.")

    if len(description) >= 40:
        score += 0.12
        matched.append("Description gives enough context to evaluate the proof.")
    else:
        missing.append("Description is missing or too short to explain the student's contribution.")

    keyword_hits = _skill_keyword_hits(skill, score_input.text)
    if keyword_hits:
        score += min(0.25, 0.08 * len(keyword_hits))
        matched.append(f"Stored metadata mentions skill-relevant terms: {', '.join(keyword_hits[:5])}.")
    else:
        missing.append("Stored title, description, URL, and metadata do not mention skill-relevant terms.")

    contribution_hits = _keyword_hits(
        score_input.text,
        (
            "built",
            "implemented",
            "designed",
            "developed",
            "created",
            "deployed",
            "trained",
            "integrated",
            "authored",
        ),
    )
    if contribution_hits:
        score += 0.10
        matched.append("Description includes action-oriented contribution language.")
    else:
        missing.append("Student contribution is not explicit in the stored metadata.")

    if _has_repo_detail(row):
        score += 0.05
        matched.append("Repository/file detail is available for future deeper analysis.")
    elif score_input.proof_kind == "github_repository":
        missing.append("Repository proof does not include file or path details for deeper analysis.")

    confidence = max(0.0, min(1.0, round(score, 2)))
    status = _status_for_score(confidence, score_input.proof_kind, skill)
    needs_human_review = status in {"pending", "weak_match", "rejected"} or confidence < 0.75

    return {
        "verification_status": status,
        "confidence_score": confidence,
        "evidence_summary": _summary(status, skill, score_input.proof_kind, confidence),
        "matched_signals": matched,
        "missing_signals": missing,
        "verifier_notes": (
            "Rule-based MVP only. This result uses stored metadata and URL structure; "
            "it does not fetch GitHub, scrape webpages, or call an LLM."
        ),
        "needs_human_review": needs_human_review,
    }


def _build_score_input(row: dict[str, Any]) -> _ScoreInput:
    metadata = _metadata(row)
    proof_url = _clean(row.get("repository_url")) or _clean(row.get("evidence_url")) or _clean(metadata.get("url"))
    proof_kind = _proof_kind(row, proof_url)
    text = " ".join(
        [
            _clean(row.get("evidence_type")),
            _title(row),
            _clean(row.get("evidence_description")),
            _clean(row.get("file_path")),
            proof_url or "",
            _metadata_text(metadata),
        ]
    ).lower()
    return _ScoreInput(row=row, proof_url=proof_url, proof_kind=proof_kind, text=text)


def _is_public(row: dict[str, Any]) -> bool:
    metadata = _metadata(row)
    if row.get("proof_visibility") == "private":
        return False
    if metadata.get("visibility") == "private" or metadata.get("proof_visibility") == "private":
        return False
    if metadata.get("is_public") is False:
        return False
    return True


def _proof_kind(row: dict[str, Any], proof_url: str | None) -> str | None:
    if not proof_url or not _is_public_http_url(proof_url):
        return None

    parsed = urlparse(proof_url)
    host = parsed.netloc.lower()
    evidence_type = _clean(row.get("evidence_type")).lower()

    if parse_github_repo_url(proof_url) is not None:
        return "github_repository"
    if _contains_any(evidence_type, ("deployed", "live", "demo", "project")):
        return "deployed_project"
    if _contains_any(evidence_type, ("portfolio", "documentation", "docs")):
        return "portfolio_documentation"
    if _contains_any(host, ("readthedocs", "gitbook", "notion.site", "medium.com", "dev.to")):
        return "portfolio_documentation"
    if _contains_any(parsed.path.lower(), ("/docs", "/documentation", "/portfolio")):
        return "portfolio_documentation"
    if host and "github" not in host:
        return "deployed_project"
    return None


def _is_public_http_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = parsed.hostname or ""
    return host not in {"localhost", "127.0.0.1", "0.0.0.0"} and not host.endswith(".local")


def _status_for_score(score: float, proof_kind: str | None, skill: str) -> str:
    if not proof_kind or not skill:
        return "rejected"
    if score >= 0.82:
        return "strong_match"
    if score >= 0.62:
        return "plausible_match"
    if score >= 0.35:
        return "weak_match"
    return "rejected"


def _summary(status: str, skill: str, proof_kind: str | None, score: float) -> str:
    if status == "strong_match":
        return f"Stored public {proof_kind} metadata strongly supports the claimed skill '{skill}' with confidence {score:.2f}."
    if status == "plausible_match":
        return f"Stored public {proof_kind} metadata plausibly supports the claimed skill '{skill}' with confidence {score:.2f}."
    if status == "weak_match":
        return f"Stored public proof metadata weakly supports the claimed skill '{skill}' with confidence {score:.2f}."
    return f"Stored proof metadata does not provide enough public, skill-relevant signal for '{skill}'."


def _skill_keyword_hits(skill: str, text: str) -> list[str]:
    keywords = _keywords_for_skill(skill)
    return _keyword_hits(text, keywords)


def _keywords_for_skill(skill: str) -> tuple[str, ...]:
    normalized = skill.lower()
    base = tuple(token for token in re.split(r"[^a-z0-9+#.]+", normalized) if len(token) > 1)
    aliases: list[str] = list(base)

    if "python" in normalized:
        aliases.extend(["python", "fastapi", "django", "flask", "pandas", "numpy", "pytest"])
    if _contains_any(normalized, ("machine learning", "ml", "data science", "ai", "artificial intelligence")):
        aliases.extend(["machine learning", "model", "training", "prediction", "sklearn", "tensorflow", "pytorch"])
    if _contains_any(normalized, ("rag", "llm", "genai", "generative ai", "prompt")):
        aliases.extend(["rag", "llm", "openai", "embedding", "vector", "retrieval", "prompt"])
    if _contains_any(normalized, ("javascript", "typescript", "react", "next")):
        aliases.extend(["javascript", "typescript", "react", "next.js", "frontend"])
    if "sql" in normalized:
        aliases.extend(["sql", "postgres", "database", "query", "schema"])
    if _contains_any(normalized, ("docker", "cloud", "deployment", "devops", "mlops")):
        aliases.extend(["docker", "deploy", "deployment", "cloud", "ci", "github actions"])

    deduped: list[str] = []
    for alias in aliases:
        if alias and alias not in deduped:
            deduped.append(alias)
    return tuple(deduped)


def _keyword_hits(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [keyword for keyword in keywords if keyword.lower() in text]


def _has_repo_detail(row: dict[str, Any]) -> bool:
    return bool(_clean(row.get("file_path")) or _metadata(row).get("repository_name") or _metadata(row).get("branch"))


def _title(row: dict[str, Any]) -> str:
    metadata = _metadata(row)
    return _clean(row.get("title")) or _clean(row.get("source_label")) or _clean(metadata.get("title"))


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") or {}
    return metadata if isinstance(metadata, dict) else {}


def _metadata_text(metadata: dict[str, Any]) -> str:
    try:
        return json.dumps(metadata, sort_keys=True)
    except TypeError:
        return str(metadata)


def _input_snapshot(row: dict[str, Any], proof_kind: str | None) -> dict[str, Any]:
    return {
        "skill_name": row.get("skill_name"),
        "evidence_type": row.get("evidence_type"),
        "evidence_url": row.get("evidence_url"),
        "repository_url": row.get("repository_url"),
        "file_path": row.get("file_path"),
        "evidence_description": row.get("evidence_description"),
        "proof_visibility": row.get("proof_visibility"),
        "metadata": _metadata(row),
        "proof_kind": proof_kind,
    }


def _to_response(row: dict[str, Any]) -> PublicProofVerificationResponse:
    return PublicProofVerificationResponse(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        skill_evidence_id=str(row["skill_evidence_id"]),
        verification_status=row["verification_status"],
        confidence_score=float(row["confidence_score"]),
        evidence_summary=row["evidence_summary"],
        matched_signals=list(row.get("matched_signals") or []),
        missing_signals=list(row.get("missing_signals") or []),
        verifier_notes=row.get("verifier_notes") or "",
        needs_human_review=bool(row.get("needs_human_review")),
        verifier_version=row.get("verifier_version") or _VERIFIER_VERSION,
        created_at=str(row.get("created_at") or ""),
    )


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _now() -> str:
    return datetime.now(UTC).isoformat()
