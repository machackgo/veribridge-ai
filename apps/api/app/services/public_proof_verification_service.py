"""Rule-based public proof verification for stored and inspected public evidence."""

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
from app.services.github_public_inspection_service import (
    GITHUB_PUBLIC_INSPECTOR_VERSION,
    GitHubInspectionResult,
    GitHubPublicInspectionService,
)
from app.services.skill_evidence_service import SkillEvidenceNotFoundError
from app.services.website_public_inspection_service import (
    WEBSITE_PUBLIC_INSPECTOR_VERSION,
    WebsiteInspectionResult,
    WebsitePublicInspectionService,
)

_EVIDENCE_TABLE = "skill_evidence"
_VERIFICATION_TABLE = "skill_evidence_verifications"
_VERIFIER_VERSION = "public-proof-v2"


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
    github_inspection: GitHubInspectionResult | None = None
    website_inspection: WebsiteInspectionResult | None = None


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

        github_inspection = _inspect_github_proof(score_input)
        if github_inspection is not None:
            score_input = _build_score_input(row, github_inspection)
        else:
            website_inspection = _inspect_website_proof(score_input)
            if website_inspection is not None:
                score_input = _build_score_input(row, website_inspection=website_inspection)

        result = _score_public_proof(score_input)
        data = {
            **result,
            "user_id": user_id,
            "skill_evidence_id": evidence_id,
            "verification_type": "public_proof",
            "verifier_version": _VERIFIER_VERSION,
            "input_snapshot": _input_snapshot(row, score_input),
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
    github_inspection = score_input.github_inspection
    website_inspection = score_input.website_inspection

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

    if github_inspection is not None:
        if github_inspection.inspection_used:
            score += 0.18
            matched.extend(github_inspection.matched_signals)
        else:
            missing.extend(github_inspection.missing_signals)

    if website_inspection is not None:
        if website_inspection.inspection_used:
            score += 0.18
            matched.extend(website_inspection.matched_signals)
        else:
            missing.extend(website_inspection.missing_signals)

    keyword_hits = _skill_keyword_hits(skill, score_input.text)
    if keyword_hits:
        score += min(0.25, 0.08 * len(keyword_hits))
        if github_inspection and github_inspection.inspection_used:
            matched.append(f"GitHub inspection and stored metadata mention skill-relevant terms: {', '.join(keyword_hits[:5])}.")
        elif website_inspection and website_inspection.inspection_used:
            matched.append(f"Website inspection and stored metadata mention skill-relevant terms: {', '.join(keyword_hits[:5])}.")
        else:
            matched.append(f"Stored metadata mentions skill-relevant terms: {', '.join(keyword_hits[:5])}.")
    else:
        missing.append("Stored metadata and inspected public proof signals do not mention skill-relevant terms.")

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

    if github_inspection and github_inspection.inspection_used:
        score += _github_skill_signal_bonus(skill, github_inspection, matched, missing)

    if website_inspection and website_inspection.inspection_used:
        score += _website_skill_signal_bonus(skill, website_inspection, matched, missing)

    confidence = max(0.0, min(1.0, round(score, 2)))
    status = _status_for_score(confidence, score_input.proof_kind, skill)
    needs_human_review = status in {"pending", "weak_match", "rejected"} or confidence < 0.75

    return {
        "verification_status": status,
        "confidence_score": confidence,
        "evidence_summary": _summary(
            status,
            skill,
            score_input.proof_kind,
            confidence,
            bool(github_inspection and github_inspection.inspection_used),
            bool(website_inspection and website_inspection.inspection_used),
        ),
        "matched_signals": matched,
        "missing_signals": missing,
        "verifier_notes": (
            _verifier_notes(github_inspection, website_inspection)
        ),
        "needs_human_review": needs_human_review,
    }


def _build_score_input(
    row: dict[str, Any],
    github_inspection: GitHubInspectionResult | None = None,
    website_inspection: WebsiteInspectionResult | None = None,
) -> _ScoreInput:
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
            github_inspection.text if github_inspection and github_inspection.inspection_used else "",
            website_inspection.text if website_inspection and website_inspection.inspection_used else "",
        ]
    ).lower()
    return _ScoreInput(
        row=row,
        proof_url=proof_url,
        proof_kind=proof_kind,
        text=text,
        github_inspection=github_inspection,
        website_inspection=website_inspection,
    )


def _inspect_github_proof(score_input: _ScoreInput) -> GitHubInspectionResult | None:
    if score_input.proof_url is None or parse_github_repo_url(score_input.proof_url) is None:
        return None
    return GitHubPublicInspectionService().inspect_url(score_input.proof_url)


def _inspect_website_proof(score_input: _ScoreInput) -> WebsiteInspectionResult | None:
    if score_input.proof_url is None or score_input.proof_kind not in {"deployed_project", "portfolio_documentation"}:
        return None
    return WebsitePublicInspectionService().inspect_url(score_input.proof_url)


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


def _summary(
    status: str,
    skill: str,
    proof_kind: str | None,
    score: float,
    github_inspection_used: bool,
    website_inspection_used: bool,
) -> str:
    if github_inspection_used:
        basis = "inspected public GitHub proof"
    elif website_inspection_used:
        basis = "inspected public website proof"
    else:
        basis = "stored public proof metadata"
    if status == "strong_match":
        return f"{basis} strongly supports the claimed skill '{skill}' with confidence {score:.2f}."
    if status == "plausible_match":
        return f"{basis} plausibly supports the claimed skill '{skill}' with confidence {score:.2f}."
    if status == "weak_match":
        return f"{basis} weakly supports the claimed skill '{skill}' with confidence {score:.2f}."
    return f"{basis} does not provide enough public, skill-relevant signal for '{skill}'."


def _github_skill_signal_bonus(
    skill: str,
    github_inspection: GitHubInspectionResult,
    matched: list[str],
    missing: list[str],
) -> float:
    bonus = 0.0
    normalized_skill = skill.lower()
    language = (github_inspection.primary_language or "").lower()
    if language and language in _keywords_for_skill(skill):
        bonus += 0.08
        matched.append(f"GitHub primary language directly supports the claimed skill: {github_inspection.primary_language}.")
    elif language and _language_supports_skill(normalized_skill, language):
        bonus += 0.08
        matched.append(f"GitHub primary language supports the claimed skill: {github_inspection.primary_language}.")
    elif github_inspection.primary_language:
        missing.append(f"GitHub primary language does not directly match the claimed skill: {github_inspection.primary_language}.")

    readme_hits = _skill_keyword_hits(skill, github_inspection.readme_text or "")
    if readme_hits:
        bonus += 0.10
        matched.append(f"GitHub README includes skill-relevant terms: {', '.join(readme_hits[:5])}.")
    elif github_inspection.readme_text:
        missing.append("GitHub README was inspected but did not include skill-relevant terms.")

    file_text = " ".join([github_inspection.file_name or "", github_inspection.file_path or "", github_inspection.file_text or ""])
    file_hits = _skill_keyword_hits(skill, file_text)
    if file_hits:
        bonus += 0.10
        matched.append(f"GitHub file proof includes skill-relevant terms: {', '.join(file_hits[:5])}.")
    elif github_inspection.file_path:
        missing.append("GitHub file proof was inspected but did not include skill-relevant terms.")

    return bonus


def _website_skill_signal_bonus(
    skill: str,
    website_inspection: WebsiteInspectionResult,
    matched: list[str],
    missing: list[str],
) -> float:
    bonus = 0.0
    title_hits = _skill_keyword_hits(skill, website_inspection.page_title or "")
    if title_hits:
        bonus += 0.06
        matched.append(f"Website title includes skill-relevant terms: {', '.join(title_hits[:5])}.")
    elif website_inspection.page_title:
        missing.append("Website title was inspected but did not include skill-relevant terms.")

    meta_hits = _skill_keyword_hits(skill, website_inspection.meta_description or "")
    if meta_hits:
        bonus += 0.06
        matched.append(f"Website meta description includes skill-relevant terms: {', '.join(meta_hits[:5])}.")
    elif website_inspection.meta_description:
        missing.append("Website meta description was inspected but did not include skill-relevant terms.")

    heading_hits = _skill_keyword_hits(skill, " ".join(website_inspection.headings))
    if heading_hits:
        bonus += 0.08
        matched.append(f"Website headings include skill-relevant terms: {', '.join(heading_hits[:5])}.")
    elif website_inspection.headings:
        missing.append("Website headings were inspected but did not include skill-relevant terms.")

    body_hits = _skill_keyword_hits(skill, website_inspection.visible_text or "")
    if body_hits:
        bonus += 0.10
        matched.append(f"Website visible text includes skill-relevant terms: {', '.join(body_hits[:5])}.")
    elif website_inspection.visible_text:
        missing.append("Website visible text was inspected but did not include skill-relevant terms.")

    if website_inspection.public_markers:
        bonus += 0.03
        matched.append(f"Website public interaction markers found: {', '.join(website_inspection.public_markers[:5])}.")

    return bonus


def _language_supports_skill(normalized_skill: str, language: str) -> bool:
    return (
        ("python" in normalized_skill and language == "python")
        or (_contains_any(normalized_skill, ("javascript", "typescript", "react", "next")) and language in {"javascript", "typescript"})
        or ("sql" in normalized_skill and language in {"sql", "plpgsql"})
    )


def _verifier_notes(
    github_inspection: GitHubInspectionResult | None,
    website_inspection: WebsiteInspectionResult | None,
) -> str:
    base = "Rule-based MVP only. This result does not scrape webpages or call an LLM."
    if github_inspection and github_inspection.inspection_used:
        return (
            f"{base} Real GitHub inspection was used via {GITHUB_PUBLIC_INSPECTOR_VERSION}; "
            "stored metadata remains part of the score."
        )
    if github_inspection is not None:
        return (
            f"{base} Real GitHub inspection was attempted but unavailable "
            f"({github_inspection.error or 'unknown_error'}); used stored metadata fallback."
        )
    if website_inspection and website_inspection.inspection_used:
        return (
            f"{base} Real website inspection was used via {WEBSITE_PUBLIC_INSPECTOR_VERSION}; "
            "no forms were submitted, no links were clicked, and stored metadata remains part of the score."
        )
    if website_inspection is not None:
        return (
            f"{base} Real website inspection was attempted but unavailable "
            f"({website_inspection.error or 'unknown_error'}); used stored metadata fallback."
        )
    return f"{base} Live public inspection was not applicable; used stored metadata only."


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
    normalized_text = text.lower()
    return [keyword for keyword in keywords if keyword.lower() in normalized_text]


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


def _input_snapshot(row: dict[str, Any], score_input: _ScoreInput) -> dict[str, Any]:
    github_inspection = score_input.github_inspection
    website_inspection = score_input.website_inspection
    snapshot = {
        "skill_name": row.get("skill_name"),
        "evidence_type": row.get("evidence_type"),
        "evidence_url": row.get("evidence_url"),
        "repository_url": row.get("repository_url"),
        "file_path": row.get("file_path"),
        "evidence_description": row.get("evidence_description"),
        "proof_visibility": row.get("proof_visibility"),
        "metadata": _metadata(row),
        "proof_kind": score_input.proof_kind,
        "github_inspection_used": bool(github_inspection and github_inspection.inspection_used),
        "website_inspection_used": bool(website_inspection and website_inspection.inspection_used),
    }
    if github_inspection is not None:
        snapshot["github_inspection"] = {
            "owner": github_inspection.owner,
            "repo": github_inspection.repo,
            "primary_language": github_inspection.primary_language,
            "default_branch": github_inspection.default_branch,
            "file_path": github_inspection.file_path,
            "error": github_inspection.error,
            "status_code": github_inspection.status_code,
        }
    if website_inspection is not None:
        snapshot["website_inspection"] = {
            "final_url": website_inspection.final_url,
            "status_code": website_inspection.status_code,
            "page_title": website_inspection.page_title,
            "headings": website_inspection.headings,
            "public_markers": website_inspection.public_markers,
            "error": website_inspection.error,
        }
    return snapshot


def _to_response(row: dict[str, Any]) -> PublicProofVerificationResponse:
    input_snapshot = row.get("input_snapshot") if isinstance(row.get("input_snapshot"), dict) else {}
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
        github_inspection_used=bool(row.get("github_inspection_used") or input_snapshot.get("github_inspection_used")),
        website_inspection_used=bool(row.get("website_inspection_used") or input_snapshot.get("website_inspection_used")),
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
