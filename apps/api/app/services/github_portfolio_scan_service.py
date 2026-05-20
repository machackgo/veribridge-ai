"""Service wrapper around the J3A GitHub Portfolio Scanner for the student-facing API.

Imports the scanner from scripts/ using the same sys.path approach used in the J3A tests.
Wraps the GitHubAPIClient so fork/archived filtering can be applied before scanning.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

# Add apps/api/ to sys.path so `from scripts.github_portfolio_scanner import ...` works
_API_ROOT = Path(__file__).resolve().parents[2]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from scripts.github_portfolio_scanner import (  # noqa: E402
    EvidenceCandidate,
    GitHubAPIClient,
    MockGitHubAPIClient,
    PortfolioScanner,
    check_duplicate,
    make_import_key,
)

from app.schemas.github_portfolio import (
    GitHubPortfolioScanCandidate,
    GitHubPortfolioScanResponse,
)
from app.schemas.skill_evidence import SkillEvidenceCreate
from app.services.evidence_access_link_service import EvidenceAccessLinkService
from app.services.github_claim_code_semantic_verification_service import (
    GitHubSemanticVerificationService,
)
from app.services.github_recruiter_proof_report_service import (
    GitHubRecruiterProofReportService,
)
from app.services.skill_evidence_service import SkillEvidenceService

# Expose for use in tests / import endpoint
__all__ = [
    "run_portfolio_scan",
    "import_selected_candidates",
    "MockGitHubAPIClient",
    "PortfolioScanner",
]

# Detection reasons that warrant "high" confidence
_HIGH_CONFIDENCE_REASONS = frozenset(
    [
        "ML training call",
        "ML prediction/inference",
        "ML model instantiation",
        "ML evaluation metrics",
        "API endpoint decorator",
        "Dockerfile instruction",
        "CI/CD workflow step",
        "RAG/LLM logic",
        "NLP processing",
    ]
)


class _FilteredGitHubAPIClient:
    """Thin wrapper that strips forks and/or archived repos before scanning."""

    def __init__(
        self,
        real_client: GitHubAPIClient,
        include_forks: bool = False,
        include_archived: bool = False,
    ) -> None:
        self._real = real_client
        self._include_forks = include_forks
        self._include_archived = include_archived

    def list_repos(self, username: str) -> list[dict[str, Any]]:
        repos = self._real.list_repos(username)
        if not self._include_forks:
            repos = [r for r in repos if not r.get("fork")]
        if not self._include_archived:
            repos = [r for r in repos if not r.get("archived")]
        return repos

    def get_file_tree(self, owner: str, repo: str, branch: str) -> list[dict[str, Any]]:
        return self._real.get_file_tree(owner, repo, branch)

    def get_raw_file(self, owner: str, repo: str, branch: str, path: str) -> str | None:
        return self._real.get_raw_file(owner, repo, branch, path)


def _candidate_id(import_key_no_user: str) -> str:
    """Deterministic 16-char hex ID derived from the user-agnostic import key."""
    return hashlib.sha256(import_key_no_user.encode()).hexdigest()[:16]


def _confidence_label(detection_reason: str) -> str:
    return "high" if detection_reason in _HIGH_CONFIDENCE_REASONS else "medium"


def _suggested_status(detection_reason: str) -> str:
    return "suggested" if detection_reason in _HIGH_CONFIDENCE_REASONS else "needs_review"


def run_portfolio_scan(
    github_username: str,
    max_repos: int = 10,
    include_forks: bool = False,
    include_archived: bool = False,
    github_token: str | None = None,
    _override_client: Any = None,
) -> GitHubPortfolioScanResponse:
    """
    Run a dry-run portfolio scan for `github_username`.

    Returns structured proof candidates without writing anything to the database.

    Parameters
    ----------
    _override_client:
        Inject a MockGitHubAPIClient in tests instead of making real HTTP calls.
    """
    if _override_client is not None:
        client: Any = _override_client
    else:
        real_client = GitHubAPIClient(token=github_token)
        client = _FilteredGitHubAPIClient(real_client, include_forks, include_archived)

    scanner = PortfolioScanner(client)
    raw_candidates = scanner.scan(github_username, max_repos=max_repos)

    repo_names_scanned: set[str] = {c.repo_name for c in raw_candidates}
    skill_labels: set[str] = {c.skill_name for c in raw_candidates}

    proof_candidates: list[GitHubPortfolioScanCandidate] = []
    for candidate in raw_candidates:
        # Build a user-agnostic import key (user_id="" — stamped with real user_id at import time)
        base_key = make_import_key(
            "",
            candidate.repo_url,
            candidate.file_path,
            candidate.line_start,
            candidate.line_end,
            candidate.skill_name,
        )
        proof_candidates.append(
            GitHubPortfolioScanCandidate(
                candidate_id=_candidate_id(base_key),
                repo_name=candidate.repo_name,
                repo_url=candidate.repo_url,
                project_title=candidate.project_title,
                skill_label=candidate.skill_name,
                evidence_description=candidate.evidence_description,
                student_claim=candidate.student_claim,
                file_path=candidate.file_path,
                line_start=candidate.line_start,
                line_end=candidate.line_end,
                github_highlight_url=candidate.github_highlight_url,
                confidence_label=_confidence_label(candidate.detection_reason),
                selection_reason=candidate.detection_reason,
                website_url=candidate.website_url,
                suggested_status=_suggested_status(candidate.detection_reason),
                warnings=[],
                import_key=base_key,
            )
        )

    return GitHubPortfolioScanResponse(
        github_username=github_username,
        repo_count_scanned=len(repo_names_scanned),
        candidate_count=len(proof_candidates),
        detected_skill_count=len(skill_labels),
        proof_candidates=proof_candidates,
    )


def import_selected_candidates(
    db: Any,
    user_id: str,
    candidates: list[GitHubPortfolioScanCandidate],
) -> list[dict[str, Any]]:
    """
    Save approved proof candidates for `user_id`.

    For each candidate:
    1. Skip if a duplicate already exists.
    2. Create a SkillEvidenceService record (same path as manual UI submission).
    3. Run GitHub semantic verification (best effort).
    4. Run recruiter proof report generation (best effort).
    5. Generate evidence access links (best effort).

    Returns a list of per-candidate result dicts.
    """
    results: list[dict[str, Any]] = []

    for candidate in candidates:
        real_import_key = make_import_key(
            user_id,
            candidate.repo_url,
            candidate.file_path,
            candidate.line_start,
            candidate.line_end,
            candidate.skill_label,
        )

        # Build an EvidenceCandidate for duplicate check
        dummy = EvidenceCandidate(
            skill_name=candidate.skill_label,
            project_title=candidate.project_title,
            repo_url=candidate.repo_url,
            repo_name=candidate.repo_name,
            file_path=candidate.file_path,
            line_start=candidate.line_start,
            line_end=candidate.line_end,
            evidence_description=candidate.evidence_description,
            student_claim=candidate.student_claim,
            evidence_type="github repository",
            website_url=candidate.website_url,
            detection_reason=candidate.selection_reason,
            github_highlight_url=candidate.github_highlight_url,
            import_key=real_import_key,
        )

        if check_duplicate(db, user_id, dummy):
            results.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "skill_label": candidate.skill_label,
                    "repo_name": candidate.repo_name,
                    "status": "skipped_duplicate",
                    "evidence_id": None,
                    "message": "Duplicate evidence already exists for this user.",
                }
            )
            continue

        # Create the proof evidence record
        try:
            evidence = SkillEvidenceService(db).create_skill_evidence(
                user_id,
                SkillEvidenceCreate(
                    skill_name=candidate.skill_label,
                    evidence_type="github repository",
                    repository_url=candidate.repo_url,
                    file_path=candidate.file_path,
                    line_start=candidate.line_start,
                    line_end=candidate.line_end,
                    evidence_description=candidate.evidence_description,
                    proof_visibility="public",
                    metadata={
                        "evidence_title": candidate.project_title,
                        "submission_source": "github_portfolio_scan",
                        "import_source": "github_portfolio_scan_ui",
                        "import_key": real_import_key,
                        "branch_ref": "main",
                        "student_claim": candidate.student_claim,
                        "github_highlight_url": candidate.github_highlight_url,
                        "selection_reason": candidate.selection_reason,
                    },
                ),
            )
        except Exception as exc:
            results.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "skill_label": candidate.skill_label,
                    "repo_name": candidate.repo_name,
                    "status": "failed",
                    "evidence_id": None,
                    "message": f"Failed to create evidence record: {exc}",
                }
            )
            continue

        evidence_id = evidence.id

        # Best-effort pipeline steps — failures don't block the import
        try:
            GitHubSemanticVerificationService(db).evaluate_github_semantic_verification(
                user_id, evidence_id
            )
        except Exception:
            pass

        try:
            GitHubRecruiterProofReportService(db).generate_github_recruiter_proof_report(
                user_id=user_id,
                evidence_id=evidence_id,
            )
        except Exception:
            pass

        try:
            EvidenceAccessLinkService(db).generate_evidence_access_links(user_id, evidence_id)
        except Exception:
            pass

        results.append(
            {
                "candidate_id": candidate.candidate_id,
                "skill_label": candidate.skill_label,
                "repo_name": candidate.repo_name,
                "status": "imported",
                "evidence_id": evidence_id,
                "message": f"Imported successfully (verification_status={evidence.verification_status}).",
            }
        )

    return results
