"""Standalone GitHub proof submission and analysis service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.schemas.github_proof_submission import (
    GitHubProofPublicResponse,
    GitHubProofSubmissionResponse,
)
from app.services.extension_proof_github_analysis_service import analyze_github_repo
from app.services.extension_proof_service import ExtensionProofSessionNotFoundError
from app.services.notification_service import NotificationService
from app.services.public_work_passport_service import (
    EvidenceAccessDeniedError,
    PublicWorkPassportNotFoundError,
)
from app.services.github_evidence_service import GitHubRepoRef, parse_github_repo_url

_GITHUB_PROOFS = "github_proof_submissions"
_SESSIONS = "extension_proof_sessions"
_PASSPORTS = "public_work_passports"
_GRANTS = "evidence_access_grants"
_PROJECT_DEFENSE = "project_defense_analysis_results"
_AI_DOMAIN = "ai_domain_review_results"

_PROTECTED_SECTION_NAMES = {"github", "evidence/github", "github_analysis"}


class GitHubProofNotFoundError(LookupError):
    """GitHub proof was not found for the scoped student."""


class GitHubProofAccessDeniedError(PermissionError):
    """GitHub proof access token or grant is invalid."""


class GitHubProofValidationError(ValueError):
    """GitHub proof submission is invalid."""


class GitHubProofService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def submit_github_proof(
        self,
        user_id: str,
        repo_url: str,
        proof_session_id: str | None = None,
        submitted_skill_claims: list[str] | None = None,
    ) -> GitHubProofSubmissionResponse:
        repo_ref = self.parse_github_repo_url(repo_url)
        if repo_ref is None:
            raise GitHubProofValidationError("Unsupported GitHub repository URL.")
        if proof_session_id:
            self._session_for_user(user_id, proof_session_id)
        normalized_repo_url = _repo_root_url(repo_ref)
        existing = self._proof_by_repo(user_id, normalized_repo_url, proof_session_id)
        now = _now()
        row = dict(existing or {})
        row.update({
            "id": str(existing.get("id") if existing else uuid4()),
            "user_id": user_id,
            "proof_session_id": proof_session_id,
            "repo_url": normalized_repo_url,
            "repo_owner": repo_ref.owner,
            "repo_name": repo_ref.repo,
            "default_branch": repo_ref.branch or (existing or {}).get("default_branch") or "main",
            "visibility": existing.get("visibility") if existing else "public",
            "status": "submitted",
            "submitted_skill_claims": _clean_list(submitted_skill_claims),
            "detected_skills": [],
            "repo_metadata": {
                "repo_ref": _repo_ref_snapshot(repo_ref),
                "submitted_skill_claims": _clean_list(submitted_skill_claims),
            },
            "analysis_summary": None,
            "evidence_strength": None,
            "confidence_score": None,
            "risk_flags": [],
            "missing_evidence": [],
            "public_safe_summary": "GitHub proof submitted and awaiting analysis.",
            "analysis_snapshot": {},
            "last_analyzed_at": None,
            "created_at": existing.get("created_at") if existing else now,
            "updated_at": now,
        })
        saved = self._save(row)
        return _student_response(saved)

    def analyze_github_proof(self, user_id: str, github_proof_id: str) -> GitHubProofSubmissionResponse:
        row = self._proof_for_user(user_id, github_proof_id)
        if row.get("status") == "archived":
            raise GitHubProofValidationError("Archived GitHub proofs cannot be analyzed.")

        now = _now()
        row["status"] = "analyzing"
        row["updated_at"] = now
        self._save(row)

        claims = _clean_list(row.get("submitted_skill_claims"))
        try:
            analysis = analyze_github_repo(
                str(row.get("repo_url") or ""),
                claims,
                live_website_url="",
                live_page_title="",
                proof_objective="Standalone GitHub proof analysis",
            )
        except Exception:
            analysis = _fallback_analysis_result(str(row.get("repo_url") or ""), claims)

        session_id = str(row.get("proof_session_id") or "")
        project_defense = self._row_by_session(_PROJECT_DEFENSE, user_id, session_id) if session_id else None
        ai_domain = self._row_by_session(_AI_DOMAIN, user_id, session_id) if session_id else None
        detected_skills = _detected_skills_from_analysis(analysis, claims)
        confidence_score = calculate_github_evidence_strength(analysis, row, detected_skills, project_defense, ai_domain)
        evidence_strength = _evidence_strength_label(confidence_score, analysis)
        status = _analysis_status(analysis, confidence_score)
        missing_evidence = _missing_evidence(analysis, confidence_score)
        risk_flags = _risk_flags(analysis, confidence_score, evidence_strength)
        public_safe_summary = build_public_safe_github_summary(row, analysis, detected_skills, evidence_strength, confidence_score, missing_evidence)
        row.update({
            "status": status,
            "repo_metadata": {
                "repo_ref": _repo_ref_snapshot(parse_github_repo_url(str(row.get("repo_url") or ""))),
                "detected_stack": analysis.get("detected_stack") or [],
                "detected_features": analysis.get("detected_features") or [],
                "evidence_files": analysis.get("evidence_files") or [],
                "warnings": analysis.get("warnings") or [],
                "submitted_skill_claims": claims,
                "detected_skills": detected_skills,
            },
            "analysis_summary": str(analysis.get("recruiter_summary") or public_safe_summary),
            "evidence_strength": evidence_strength,
            "confidence_score": confidence_score,
            "risk_flags": risk_flags,
            "missing_evidence": missing_evidence,
            "public_safe_summary": public_safe_summary,
            "analysis_snapshot": {
                **analysis,
                "repo_ref": _repo_ref_snapshot(parse_github_repo_url(str(row.get("repo_url") or ""))),
                "detected_skills": detected_skills,
            },
            "detected_skills": detected_skills,
            "last_analyzed_at": now,
            "updated_at": now,
        })
        saved = self._save(row)
        self._notify_analysis_complete(user_id, saved)
        return _student_response(saved)

    def get_github_proof(self, user_id: str, github_proof_id: str) -> GitHubProofSubmissionResponse:
        return _student_response(self._proof_for_user(user_id, github_proof_id))

    def list_github_proofs(self, user_id: str, proof_session_id: str | None = None) -> list[GitHubProofSubmissionResponse]:
        rows = self._rows_for_user(user_id)
        if proof_session_id:
            rows = [row for row in rows if str(row.get("proof_session_id") or "") == proof_session_id]
        rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return [_student_response(row) for row in rows]

    def archive_github_proof(self, user_id: str, github_proof_id: str) -> GitHubProofSubmissionResponse:
        row = self._proof_for_user(user_id, github_proof_id)
        row["status"] = "archived"
        row["updated_at"] = _now()
        return _student_response(self._save(row))

    def get_public_github_proofs(self, public_slug: str) -> list[GitHubProofPublicResponse]:
        passport = self._passport_by_slug(public_slug)
        if not passport or not passport.get("is_public", True):
            raise PublicWorkPassportNotFoundError(public_slug)
        return [
            _public_response(row)
            for row in self._rows_for_session(str(passport["user_id"]), str(passport["proof_session_id"]))
            if row.get("status") != "archived"
        ]

    def get_protected_github_proofs(self, access_token: str) -> list[GitHubProofPublicResponse]:
        grant = self._grant_by_token(access_token)
        if not grant or grant.get("revoked_at"):
            raise EvidenceAccessDeniedError("Access token is invalid or revoked.")
        expires_at = _parse_dt(grant.get("expires_at"))
        if expires_at and expires_at <= _now():
            raise EvidenceAccessDeniedError("Access token is expired.")
        granted_sections = _normalized_sections(list(grant.get("granted_sections") or []))
        if not (_PROTECTED_SECTION_NAMES & granted_sections):
            raise EvidenceAccessDeniedError("Access grant does not include GitHub proof access.")
        return [
            _public_response(row)
            for row in self._rows_for_session(str(grant["user_id"]), str(grant["proof_session_id"]))
            if row.get("status") != "archived"
        ]

    def parse_github_repo_url(self, repo_url: str | None) -> GitHubRepoRef | None:
        return parse_github_repo_url(repo_url)

    def build_public_safe_github_summary(
        self,
        row: dict[str, Any],
        analysis: dict[str, Any],
        detected_skills: list[str],
        evidence_strength: str,
        confidence_score: int,
        missing_evidence: list[str] | None = None,
    ) -> str:
        return build_public_safe_github_summary(row, analysis, detected_skills, evidence_strength, confidence_score, missing_evidence)

    def calculate_github_evidence_strength(
        self,
        analysis: dict[str, Any],
        row: dict[str, Any] | None = None,
        detected_skills: list[str] | None = None,
        project_defense: dict[str, Any] | None = None,
        ai_domain: dict[str, Any] | None = None,
    ) -> int:
        return calculate_github_evidence_strength(analysis, row, detected_skills, project_defense, ai_domain)

    def _notify_analysis_complete(self, user_id: str, row: dict[str, Any]) -> None:
        try:
            NotificationService(self._client).create_notification_event(
                user_id=user_id,
                event_type="verification_needs_more_evidence",
                recipient_email=self._user_email(user_id),
                title="GitHub proof analyzed",
                message="Your GitHub proof has been analyzed and added to your Work Passport evidence.",
                category="verification",
                priority="normal",
                metadata={
                    "github_proof_id": str(row["id"]),
                    "proof_session_id": row.get("proof_session_id"),
                    "repo_url": row.get("repo_url"),
                    "status": row.get("status"),
                    "evidence_strength": row.get("evidence_strength"),
                },
            )
        except Exception:
            return

    def _session_for_user(self, user_id: str, proof_session_id: str) -> dict[str, Any]:
        row = self._by_id(_SESSIONS, proof_session_id)
        if not row or str(row.get("user_id")) != user_id:
            raise ExtensionProofSessionNotFoundError(proof_session_id)
        return row

    def _proof_for_user(self, user_id: str, github_proof_id: str) -> dict[str, Any]:
        row = self._by_id(_GITHUB_PROOFS, github_proof_id)
        if not row or str(row.get("user_id")) != user_id:
            raise GitHubProofNotFoundError(github_proof_id)
        return row

    def _proof_by_repo(self, user_id: str, repo_url: str, proof_session_id: str | None) -> dict[str, Any] | None:
        rows = self._rows_for_user(user_id)
        for row in rows:
            if row.get("status") == "archived":
                continue
            if str(row.get("repo_url") or "") != repo_url:
                continue
            if proof_session_id and str(row.get("proof_session_id") or "") != proof_session_id:
                continue
            return row
        return None

    def _rows_for_user(self, user_id: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            return [
                row for row in self._client.get(_GITHUB_PROOFS, {}).values()
                if str(row.get("user_id")) == user_id
            ]
        result = self._client.table(_GITHUB_PROOFS).select("*").eq("user_id", user_id).execute()
        return getattr(result, "data", []) or []

    def _rows_for_session(self, user_id: str, proof_session_id: str) -> list[dict[str, Any]]:
        rows = [
            row for row in self._rows_for_user(user_id)
            if str(row.get("proof_session_id") or "") == proof_session_id
        ]
        rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return rows

    def _row_by_session(self, table: str, user_id: str, proof_session_id: str) -> dict[str, Any] | None:
        if not proof_session_id:
            return None
        if isinstance(self._client, dict):
            rows = [
                row for row in self._client.get(table, {}).values()
                if str(row.get("user_id")) == user_id and str(row.get("proof_session_id")) == proof_session_id
            ]
            rows.sort(key=lambda row: str(row.get("created_at") or row.get("updated_at") or ""), reverse=True)
            return rows[0] if rows else None
        result = (
            self._client.table(table)
            .select("*")
            .eq("user_id", user_id)
            .eq("proof_session_id", proof_session_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _passport_by_slug(self, public_slug: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            for row in self._client.get(_PASSPORTS, {}).values():
                if str(row.get("public_slug")) == public_slug:
                    return row
            return None
        result = self._client.table(_PASSPORTS).select("*").eq("public_slug", public_slug).limit(1).execute()
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _grant_by_token(self, token: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            for row in self._client.get(_GRANTS, {}).values():
                if str(row.get("access_token")) == token:
                    return row
            return None
        result = self._client.table(_GRANTS).select("*").eq("access_token", token).limit(1).execute()
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _by_id(self, table: str, row_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            return self._client.get(table, {}).get(row_id)
        result = self._client.table(table).select("*").eq("id", row_id).limit(1).execute()
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _save(self, row: dict[str, Any]) -> dict[str, Any]:
        if isinstance(self._client, dict):
            self._client.setdefault(_GITHUB_PROOFS, {})[str(row["id"])] = row
            return row
        result = self._client.table(_GITHUB_PROOFS).upsert(row).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError("github_proof_submissions upsert returned no data.")
        return rows[0]

    def _user_email(self, user_id: str) -> str:
        if isinstance(self._client, dict):
            user = self._client.get("users", {}).get(user_id) or {}
            return str(user.get("email") or "")
        result = self._client.table("users").select("email").eq("id", user_id).limit(1).execute()
        rows = getattr(result, "data", []) or []
        return str((rows[0] if rows else {}).get("email") or "")


def submit_github_proof(
    user_id: str,
    repo_url: str,
    client: Any,
    proof_session_id: str | None = None,
    submitted_skill_claims: list[str] | None = None,
) -> GitHubProofSubmissionResponse:
    return GitHubProofService(client).submit_github_proof(user_id, repo_url, proof_session_id, submitted_skill_claims)


def analyze_github_proof(user_id: str, github_proof_id: str, client: Any) -> GitHubProofSubmissionResponse:
    return GitHubProofService(client).analyze_github_proof(user_id, github_proof_id)


def build_public_safe_github_summary(
    row: dict[str, Any],
    analysis: dict[str, Any],
    detected_skills: list[str],
    evidence_strength: str,
    confidence_score: int,
    missing_evidence: list[str] | None = None,
) -> str:
    repo_ref = parse_github_repo_url(str(row.get("repo_url") or ""))
    if analysis.get("status") in {"failed", "private_or_unavailable"} and not analysis.get("evidence_files"):
        return "GitHub analysis is limited because GitHub API is not configured."
    repo_name = f"{repo_ref.owner}/{repo_ref.repo}" if repo_ref else str(row.get("repo_url") or "GitHub repository")
    parts = [f"GitHub proof for {repo_name} is {evidence_strength} evidence with {confidence_score}/100 confidence."]
    if detected_skills:
        parts.append(f"Detected skills: {', '.join(detected_skills[:6])}.")
    if missing_evidence:
        parts.append(f"Missing evidence: {', '.join(missing_evidence[:3])}.")
    return " ".join(parts)


def calculate_github_evidence_strength(
    analysis: dict[str, Any],
    row: dict[str, Any] | None = None,
    detected_skills: list[str] | None = None,
    project_defense: dict[str, Any] | None = None,
    ai_domain: dict[str, Any] | None = None,
) -> int:
    score = int(analysis.get("confidence_score") or 0)
    features = {str(item).lower() for item in analysis.get("detected_features") or []}
    evidence_files = [str(item) for item in analysis.get("evidence_files") or []]
    warnings = [str(item).lower() for item in analysis.get("warnings") or []]

    if "readme" in features:
        score += 15
    if len(evidence_files) >= 2:
        score += 25
    elif evidence_files:
        score += 10
    if "testing" in features:
        score += 15
    if "deployment" in features:
        score += 10
    if "database" in features or "api_framework" in features:
        score += 10
    if detected_skills:
        score += min(10, len(detected_skills) * 2)
    if project_defense:
        score += 10
    if ai_domain:
        score += 10
    if row and str(row.get("status") or "").lower() in {"failed", "needs_more_evidence"}:
        score -= 10
    if any("private" in warning or "unavailable" in warning or "rate" in warning for warning in warnings):
        score -= 10
    return max(0, min(100, score))


def _analysis_status(analysis: dict[str, Any], confidence_score: int) -> str:
    status = str(analysis.get("status") or "").lower()
    if status == "success" and confidence_score >= 55:
        return "analyzed"
    if status in {"private_or_unavailable", "failed"}:
        if confidence_score >= 30:
            return "needs_more_evidence"
        return "failed"
    if confidence_score >= 45:
        return "analyzed"
    return "needs_more_evidence"


def _evidence_strength_label(confidence_score: int, analysis: dict[str, Any]) -> str:
    if str(analysis.get("status") or "").lower() in {"private_or_unavailable", "failed"} and confidence_score < 30:
        return "insufficient"
    if confidence_score >= 80:
        return "strong"
    if confidence_score >= 55:
        return "partial"
    if confidence_score >= 30:
        return "weak"
    return "insufficient"


def _missing_evidence(analysis: dict[str, Any], confidence_score: int) -> list[str]:
    missing: list[str] = []
    features = {str(item).lower() for item in analysis.get("detected_features") or []}
    if "readme" not in features:
        missing.append("README or project documentation")
    if "testing" not in features:
        missing.append("tests or CI")
    if "deployment" not in features:
        missing.append("deployment evidence")
    if confidence_score < 45:
        missing.append("clearer source structure or stronger skill matches")
    return _clean_list(missing)[:4]


def _risk_flags(analysis: dict[str, Any], confidence_score: int, evidence_strength: str) -> list[str]:
    flags: list[str] = []
    status = str(analysis.get("status") or "").lower()
    if status in {"private_or_unavailable", "failed"}:
        flags.append("repository_unavailable")
    warnings = [str(item).lower() for item in analysis.get("warnings") or []]
    if any("private" in warning for warning in warnings):
        flags.append("private_or_restricted_repository")
    if confidence_score < 45:
        flags.append("low_confidence")
    if evidence_strength == "insufficient":
        flags.append("insufficient_proof")
    return _clean_list(flags)


def _detected_skills_from_analysis(analysis: dict[str, Any], submitted_skill_claims: list[str]) -> list[str]:
    skills: list[str] = []
    skills.extend(_clean_list(analysis.get("matched_claimed_skills") or []))
    skills.extend(_clean_list(analysis.get("weakly_matched_claimed_skills") or []))
    skills.extend(_skills_from_stack(analysis.get("detected_stack") or []))
    skills.extend(_skills_from_features(analysis.get("detected_features") or []))
    skills.extend(_clean_list(submitted_skill_claims))
    if not skills:
        skills.extend(_clean_list(analysis.get("missing_claimed_skills") or []))
    return _clean_list(skills)


def _skills_from_stack(stack: list[Any]) -> list[str]:
    map_stack = {
        "python": "Python",
        "javascript": "JavaScript",
        "typescript": "TypeScript",
        "react": "React",
        "next.js": "React",
        "nextjs": "React",
        "vue": "Vue",
        "angular": "Angular",
        "svelte": "Svelte",
        "fastapi": "FastAPI",
        "flask": "Flask",
        "django": "Django",
        "express": "API Development",
        "nest": "API Development",
        "nestjs": "API Development",
        "pytorch": "Machine Learning",
        "tensorflow": "Deep Learning",
        "keras": "Deep Learning",
        "scikit-learn": "Machine Learning",
        "sklearn": "Machine Learning",
        "xgboost": "Machine Learning",
        "lightgbm": "Machine Learning",
        "pandas": "Data Analysis",
        "numpy": "Data Analysis",
        "matplotlib": "Data Analysis",
        "seaborn": "Data Analysis",
        "sqlalchemy": "SQL/PostgreSQL",
        "prisma": "SQL/PostgreSQL",
        "supabase": "SQL/PostgreSQL",
        "mongodb": "Database",
        "redis": "Database",
        "docker": "Docker",
        "github actions": "CI/CD",
        "gitlab ci": "CI/CD",
        "cloud": "Cloud Deployment",
    }
    out: list[str] = []
    for value in stack:
        key = str(value).lower()
        for needle, skill in map_stack.items():
            if needle in key:
                out.append(skill)
    return out


def _skills_from_features(features: list[Any]) -> list[str]:
    out: list[str] = []
    for value in features:
        key = str(value).lower()
        if key in {"api_framework", "html_frontend"}:
            out.append("API Development" if key == "api_framework" else "Frontend Development")
        elif key == "machine_learning":
            out.append("Machine Learning")
        elif key == "ai_llm":
            out.append("NLP")
        elif key == "deployment":
            out.append("Cloud Deployment")
        elif key == "testing":
            out.append("CI/CD")
        elif key == "database":
            out.append("SQL/PostgreSQL")
        elif key == "data_visualization":
            out.append("Data Analysis")
    return out


def _repo_ref_snapshot(repo_ref: GitHubRepoRef | None) -> dict[str, Any]:
    if repo_ref is None:
        return {}
    return {
        "owner": repo_ref.owner,
        "repo": repo_ref.repo,
        "branch": repo_ref.branch,
        "file_path": repo_ref.file_path,
    }


def _repo_root_url(repo_ref: GitHubRepoRef) -> str:
    return f"https://github.com/{repo_ref.owner}/{repo_ref.repo}"


def _clean_list(values: list[Any] | tuple[Any, ...] | None) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if text:
            out.append(text)
    return list(dict.fromkeys(out))


def _normalized_sections(sections: list[str]) -> set[str]:
    return {str(section).strip().lower() for section in sections if str(section).strip()}


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_dt(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _fallback_analysis_result(repo_url: str, claims: list[str]) -> dict[str, Any]:
    now = _now().isoformat()
    return {
        "repo_url": repo_url,
        "status": "failed",
        "detected_stack": [],
        "detected_features": [],
        "matched_claimed_skills": [],
        "weakly_matched_claimed_skills": [],
        "missing_claimed_skills": claims,
        "evidence_files": [],
        "confidence_score": 0.0,
        "warnings": ["GitHub analysis is limited because GitHub API is not configured."],
        "recruiter_summary": "GitHub analysis is limited because GitHub API is not configured.",
        "created_at": now,
    }


def _student_response(row: dict[str, Any]) -> GitHubProofSubmissionResponse:
    return GitHubProofSubmissionResponse(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        proof_session_id=str(row["proof_session_id"]) if row.get("proof_session_id") else None,
        repo_url=str(row["repo_url"]),
        repo_owner=row.get("repo_owner"),
        repo_name=row.get("repo_name"),
        default_branch=row.get("default_branch"),
        visibility=row.get("visibility"),
        status=str(row.get("status") or "submitted"),
        submitted_skill_claims=_clean_list(row.get("submitted_skill_claims") or []),
        detected_skills=_clean_list(row.get("detected_skills") or []),
        repo_metadata=row.get("repo_metadata") if isinstance(row.get("repo_metadata"), dict) else {},
        analysis_summary=row.get("analysis_summary"),
        evidence_strength=row.get("evidence_strength"),
        confidence_score=int(row["confidence_score"]) if row.get("confidence_score") is not None else None,
        risk_flags=_clean_list(row.get("risk_flags") or []),
        missing_evidence=_clean_list(row.get("missing_evidence") or []),
        public_safe_summary=row.get("public_safe_summary"),
        analysis_snapshot=row.get("analysis_snapshot") if isinstance(row.get("analysis_snapshot"), dict) else {},
        last_analyzed_at=row.get("last_analyzed_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _public_response(row: dict[str, Any]) -> GitHubProofPublicResponse:
    return GitHubProofPublicResponse(
        id=str(row["id"]),
        proof_session_id=str(row["proof_session_id"]) if row.get("proof_session_id") else None,
        repo_url=str(row["repo_url"]),
        repo_owner=row.get("repo_owner"),
        repo_name=row.get("repo_name"),
        default_branch=row.get("default_branch"),
        visibility=row.get("visibility"),
        status=str(row.get("status") or "submitted"),
        submitted_skill_claims=_clean_list(row.get("submitted_skill_claims") or []),
        detected_skills=_clean_list(row.get("detected_skills") or []),
        analysis_summary=row.get("analysis_summary"),
        evidence_strength=row.get("evidence_strength"),
        confidence_score=int(row["confidence_score"]) if row.get("confidence_score") is not None else None,
        public_safe_summary=row.get("public_safe_summary"),
        missing_evidence=_clean_list(row.get("missing_evidence") or []),
        last_analyzed_at=row.get("last_analyzed_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
