"""Direct evidence access link generation for recruiter redirect foundations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from app.schemas.evidence_access_link import EvidenceAccessLinkResponse
from app.services.github_evidence_service import parse_github_repo_url
from app.services.github_recruiter_proof_report_service import (
    GitHubRecruiterProofReportNotFoundError,
    GitHubRecruiterProofReportService,
)
from app.services.skill_evidence_service import SkillEvidenceNotFoundError, SkillEvidenceService
from app.services.website_public_inspection_service import _validate_public_url
from app.services.website_semantic_verification_service import (
    WebsiteSemanticVerificationResultNotFoundError,
    WebsiteSemanticVerificationService,
)

_TABLE = "evidence_access_links"


class EvidenceAccessLinkNotFoundError(LookupError):
    """No access link was found for the scoped evidence row."""


class EvidenceAccessLinkNotAllowedError(ValueError):
    """The evidence cannot be converted into a recruiter-safe access link."""


@dataclass(frozen=True)
class EvidenceAccessLink:
    access_type: str
    label: str
    url: str
    source_type: str
    line_start: int | None = None
    line_end: int | None = None
    file_path: str | None = None
    availability_status: str = "available"
    notes: str | None = None
    source_report_type: str = "none"
    source_report_id: str | None = None
    access_snapshot: dict[str, Any] | None = None


@dataclass(frozen=True)
class _GitHubAccessContext:
    repository_url: str
    file_path: str
    owner: str
    repo: str
    branch: str


class EvidenceAccessLinkService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def generate_latest_evidence_access_links(self, user_id: str, evidence_id: str) -> list[EvidenceAccessLinkResponse]:
        return self.generate_evidence_access_links(user_id, evidence_id)

    def generate_evidence_access_links(self, user_id: str, evidence_id: str) -> list[EvidenceAccessLinkResponse]:
        evidence = self._get_evidence_row(user_id, evidence_id)
        links = self._build_access_links(user_id, evidence_id, evidence)
        return self.persist_evidence_access_links(user_id, evidence_id, links)

    def build_github_exact_line_links(self, user_id: str, evidence_id: str, evidence: dict[str, Any]) -> list[EvidenceAccessLink]:
        repo_context = parse_github_blob_or_repo_context(evidence)
        if repo_context is None:
            return [
                EvidenceAccessLink(
                    access_type="github_exact_lines",
                    label="View Exact Code Lines",
                    url="",
                    source_type="github",
                    file_path=str(evidence.get("file_path") or "") or None,
                    availability_status="insufficient_data",
                    notes="GitHub repository URL or file path is missing.",
                    source_report_type="none",
                    source_report_id=None,
                    access_snapshot={
                        "generated_from": "direct_skill_evidence",
                        "source_evidence_type": str(evidence.get("evidence_type") or ""),
                        "validated_url": False,
                    },
                )
            ]

        report_service = GitHubRecruiterProofReportService(self._client)
        report = _latest_report_or_none(report_service, user_id, evidence_id)
        source_report_type = "github_recruiter_proof_report" if report else "direct_skill_evidence"
        source_report_id = report.id if report else None
        ranges = list((getattr(report, "supporting_line_ranges", []) if report else []) or [])
        if not ranges and evidence.get("line_start") and evidence.get("line_end"):
            ranges = [
                {
                    "line_start": evidence["line_start"],
                    "line_end": evidence["line_end"],
                    "segment_type": "generic_logic",
                    "summary": str(evidence.get("evidence_description") or "Selected GitHub evidence."),
                    "detected_signals": [],
                    "supports_claim": True,
                    "semantic_score": None,
                }
            ]

        if not ranges:
            return [
                EvidenceAccessLink(
                    access_type="github_exact_lines",
                    label="View Exact Code Lines",
                    url="",
                    source_type="github",
                    file_path=repo_context.file_path,
                    availability_status="insufficient_data",
                    notes="No supporting line ranges were available yet.",
                    source_report_type=source_report_type,
                    source_report_id=source_report_id,
                    access_snapshot={
                        "generated_from": source_report_type,
                        "supporting_line_range_count": 0,
                        "source_evidence_type": str(evidence.get("evidence_type") or ""),
                        "validated_url": True,
                        "branch": repo_context.branch,
                        "file_path": repo_context.file_path,
                    },
                )
            ]

        links: list[EvidenceAccessLink] = []
        seen: set[tuple[int, int]] = set()
        for item in ranges:
            start = _to_int(_range_value(item, "line_start"))
            end = _to_int(_range_value(item, "line_end"))
            if start is None or end is None or start <= 0 or end <= 0:
                continue
            key = (start, end)
            if key in seen:
                continue
            seen.add(key)
            links.append(
                EvidenceAccessLink(
                    access_type="github_exact_lines",
                    label="View Exact Code Lines",
                    url=build_github_highlight_url(repo_context, start, end),
                    source_type="github",
                    line_start=start,
                    line_end=end,
                    file_path=repo_context.file_path,
                    availability_status="available",
                    notes=str(_range_value(item, "summary") or "").strip() or None,
                    source_report_type=source_report_type,
                    source_report_id=source_report_id,
                    access_snapshot={
                        "generated_from": source_report_type,
                        "supporting_line_range_count": len(ranges),
                        "source_evidence_type": str(evidence.get("evidence_type") or ""),
                        "validated_url": True,
                        "branch": repo_context.branch,
                        "file_path": repo_context.file_path,
                        "supporting_line_range": {
                            "line_start": start,
                            "line_end": end,
                        },
                    },
                )
            )
        return links or [
            EvidenceAccessLink(
                access_type="github_exact_lines",
                label="View Exact Code Lines",
                url="",
                source_type="github",
                file_path=repo_context.file_path,
                availability_status="insufficient_data",
                notes="No valid supporting line ranges were available.",
                source_report_type=source_report_type,
                source_report_id=source_report_id,
                access_snapshot={
                    "generated_from": source_report_type,
                    "supporting_line_range_count": 0,
                    "source_evidence_type": str(evidence.get("evidence_type") or ""),
                    "validated_url": True,
                    "branch": repo_context.branch,
                    "file_path": repo_context.file_path,
                },
            )
        ]

    def build_live_website_link(self, user_id: str, evidence_id: str, evidence: dict[str, Any]) -> EvidenceAccessLink:
        raw_url = str(evidence.get("evidence_url") or evidence.get("website_url") or "").strip()
        normalized_url, error = validate_public_website_url_for_access(raw_url)
        semantic_result = _latest_website_semantic_result_or_none(self._client, user_id, evidence_id)
        source_report_type = "website_semantic_verification_result" if semantic_result else "direct_skill_evidence"
        source_report_id = semantic_result.id if semantic_result else None

        if error:
            return EvidenceAccessLink(
                access_type="live_website",
                label="Open Live Website",
                url="",
                source_type="website",
                availability_status="invalid_source",
                notes="Website URL is not public or uses an unsupported scheme.",
                source_report_type=source_report_type,
                source_report_id=source_report_id,
                access_snapshot={
                    "generated_from": source_report_type,
                    "validated_url": False,
                    "source_evidence_type": str(evidence.get("evidence_type") or ""),
                    "website_url_error": error,
                },
            )

        if not normalized_url:
            return EvidenceAccessLink(
                access_type="live_website",
                label="Open Live Website",
                url="",
                source_type="website",
                availability_status="insufficient_data",
                notes="No public website URL was available.",
                source_report_type=source_report_type,
                source_report_id=source_report_id,
                access_snapshot={
                    "generated_from": source_report_type,
                    "validated_url": False,
                    "source_evidence_type": str(evidence.get("evidence_type") or ""),
                },
            )

        return EvidenceAccessLink(
            access_type="live_website",
            label="Open Live Website",
            url=normalized_url,
            source_type="website",
            availability_status="available",
            notes=None,
            source_report_type=source_report_type,
            source_report_id=source_report_id,
            access_snapshot={
                "generated_from": source_report_type,
                "validated_url": True,
                "source_evidence_type": str(evidence.get("evidence_type") or ""),
            },
        )

    def parse_github_blob_or_repo_context(self, evidence: dict[str, Any]) -> _GitHubAccessContext | None:
        return parse_github_blob_or_repo_context(evidence)

    def build_github_highlight_url(self, context: _GitHubAccessContext, line_start: int, line_end: int) -> str:
        return build_github_highlight_url(context, line_start, line_end)

    def validate_public_website_url_for_access(self, url: str | None) -> tuple[str | None, str | None]:
        return validate_public_website_url_for_access(url)

    def persist_evidence_access_links(
        self,
        user_id: str,
        evidence_id: str,
        links: list[EvidenceAccessLink],
    ) -> list[EvidenceAccessLinkResponse]:
        if not links:
            return []

        generation_id = str(uuid4())
        rows = []
        for link in links:
            snapshot = dict(link.access_snapshot or {})
            snapshot.setdefault("generation_id", generation_id)
            snapshot.setdefault("generated_from", link.source_report_type)
            row = {
                "id": str(uuid4()),
                "evidence_id": evidence_id,
                "user_id": user_id,
                "source_report_type": link.source_report_type,
                "source_report_id": link.source_report_id,
                "access_type": link.access_type,
                "label": link.label,
                "url": link.url,
                "source_type": link.source_type,
                "file_path": link.file_path,
                "line_start": link.line_start,
                "line_end": link.line_end,
                "availability_status": link.availability_status,
                "notes": link.notes,
                "access_snapshot": snapshot,
                "created_at": _now(),
                "updated_at": _now(),
            }
            rows.append(row)

        if isinstance(self._client, dict):
            table = self._client.setdefault(_TABLE, {})
            for row in rows:
                table[row["id"]] = row
            return [_to_response(row) for row in rows]

        inserted = []
        for row in rows:
            result = self._client.table(_TABLE).insert(row).execute()
            returned = getattr(result, "data", []) or []
            if not returned:
                raise RuntimeError("Evidence access link insert returned no data.")
            inserted.append(returned[0])
        return [_to_response(row) for row in inserted]

    def list_latest_evidence_access_links(self, user_id: str, evidence_id: str) -> list[EvidenceAccessLinkResponse]:
        self._get_evidence_row(user_id, evidence_id)
        latest_generation_id = None
        if isinstance(self._client, dict):
            rows = [
                row
                for row in self._client.setdefault(_TABLE, {}).values()
                if row.get("user_id") == user_id and row.get("evidence_id") == evidence_id
            ]
            rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
            if not rows:
                return []
            latest_generation_id = (rows[0].get("access_snapshot") or {}).get("generation_id")
            if latest_generation_id:
                rows = [row for row in rows if (row.get("access_snapshot") or {}).get("generation_id") == latest_generation_id]
            return [_to_response(row) for row in rows]

        result = (
            self._client.table(_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("evidence_id", evidence_id)
            .order("created_at", desc=True)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        if not rows:
            return []
        latest_generation_id = (rows[0].get("access_snapshot") or {}).get("generation_id")
        if latest_generation_id:
            rows = [row for row in rows if (row.get("access_snapshot") or {}).get("generation_id") == latest_generation_id]
        return [_to_response(row) for row in rows]

    def list_evidence_access_links(self, user_id: str, evidence_id: str) -> list[EvidenceAccessLinkResponse]:
        self._get_evidence_row(user_id, evidence_id)
        if isinstance(self._client, dict):
            rows = [
                row
                for row in self._client.setdefault(_TABLE, {}).values()
                if row.get("user_id") == user_id and row.get("evidence_id") == evidence_id
            ]
            rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
            return [_to_response(row) for row in rows]

        result = (
            self._client.table(_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("evidence_id", evidence_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [_to_response(row) for row in (getattr(result, "data", []) or [])]

    def get_evidence_access_link(self, user_id: str, evidence_id: str, link_id: str) -> EvidenceAccessLinkResponse:
        self._get_evidence_row(user_id, evidence_id)
        if isinstance(self._client, dict):
            row = self._client.setdefault(_TABLE, {}).get(link_id)
            if not row or row.get("user_id") != user_id or row.get("evidence_id") != evidence_id:
                raise EvidenceAccessLinkNotFoundError(link_id)
            return _to_response(row)

        result = (
            self._client.table(_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("evidence_id", evidence_id)
            .eq("id", link_id)
            .maybe_single()
            .execute()
        )
        if result is None or not result.data:
            raise EvidenceAccessLinkNotFoundError(link_id)
        return _to_response(result.data)

    def _build_access_links(self, user_id: str, evidence_id: str, evidence: dict[str, Any]) -> list[EvidenceAccessLink]:
        source_type = _detect_source_type(evidence)
        if source_type == "github":
            return self.build_github_exact_line_links(user_id, evidence_id, evidence)
        if source_type == "website":
            return [self.build_live_website_link(user_id, evidence_id, evidence)]
        raise EvidenceAccessLinkNotAllowedError("Evidence type is not compatible with direct access links.")

    def _get_evidence_row(self, user_id: str, evidence_id: str) -> dict[str, Any]:
        row = SkillEvidenceService(self._client).get_skill_evidence(user_id, evidence_id)
        return row.model_dump()


def generate_latest_evidence_access_links(user_id: str, evidence_id: str, client: Any) -> list[EvidenceAccessLinkResponse]:
    return EvidenceAccessLinkService(client).generate_latest_evidence_access_links(user_id, evidence_id)


def generate_evidence_access_links(user_id: str, evidence_id: str, client: Any) -> list[EvidenceAccessLinkResponse]:
    return EvidenceAccessLinkService(client).generate_evidence_access_links(user_id, evidence_id)


def parse_github_blob_or_repo_context(evidence: dict[str, Any]) -> _GitHubAccessContext | None:
    repository_url = str(evidence.get("repository_url") or evidence.get("evidence_url") or "").strip()
    file_path = str(evidence.get("file_path") or "").strip()
    repo_ref = parse_github_repo_url(repository_url)
    if repo_ref is None:
        return None
    normalized_file_path = (file_path or repo_ref.file_path or "").strip().lstrip("/")
    if not normalized_file_path:
        return None
    owner = str(repo_ref.owner or "").strip()
    repo = str(repo_ref.repo or "").strip()
    if not owner or not repo:
        return None
    branch = str(repo_ref.branch or "main").strip() or "main"
    return _GitHubAccessContext(
        repository_url=repository_url,
        file_path=normalized_file_path,
        owner=owner,
        repo=repo,
        branch=branch,
    )


def build_github_highlight_url(context: _GitHubAccessContext, line_start: int, line_end: int) -> str:
    fragment = f"#L{line_start}" if line_start == line_end else f"#L{line_start}-L{line_end}"
    encoded_path = "/".join(quote(part) for part in context.file_path.split("/"))
    return f"https://github.com/{context.owner}/{context.repo}/blob/{context.branch}/{encoded_path}{fragment}"


def validate_public_website_url_for_access(url: str | None) -> tuple[str | None, str | None]:
    return _validate_public_url(url)


def persist_evidence_access_links(
    user_id: str,
    evidence_id: str,
    client: Any,
    links: list[EvidenceAccessLink],
) -> list[EvidenceAccessLinkResponse]:
    return EvidenceAccessLinkService(client).persist_evidence_access_links(user_id, evidence_id, links)


def list_latest_evidence_access_links(user_id: str, evidence_id: str, client: Any) -> list[EvidenceAccessLinkResponse]:
    return EvidenceAccessLinkService(client).list_latest_evidence_access_links(user_id, evidence_id)


def list_evidence_access_links(user_id: str, evidence_id: str, client: Any) -> list[EvidenceAccessLinkResponse]:
    return EvidenceAccessLinkService(client).list_evidence_access_links(user_id, evidence_id)


def get_evidence_access_link(user_id: str, evidence_id: str, link_id: str, client: Any) -> EvidenceAccessLinkResponse:
    return EvidenceAccessLinkService(client).get_evidence_access_link(user_id, evidence_id, link_id)


def _detect_source_type(evidence: dict[str, Any]) -> str:
    repository_url = str(evidence.get("repository_url") or evidence.get("evidence_url") or "").strip()
    if parse_github_repo_url(repository_url) is not None:
        return "github"
    if str(evidence.get("evidence_url") or evidence.get("website_url") or "").strip():
        return "website"
    website_hint = " ".join(
        [
            str(evidence.get("evidence_type") or ""),
            str((evidence.get("metadata") or {}).get("proof_kind") if isinstance(evidence.get("metadata"), dict) else ""),
        ]
    ).lower()
    if any(keyword in website_hint for keyword in ("website", "web", "live", "deployed", "app", "application", "portfolio", "demo", "project")):
        return "website"
    raise EvidenceAccessLinkNotAllowedError("Evidence type is not compatible with direct access links.")


def _latest_report_or_none(service: GitHubRecruiterProofReportService, user_id: str, evidence_id: str):
    try:
        return service.get_latest_report(user_id, evidence_id)
    except GitHubRecruiterProofReportNotFoundError:
        return None


def _latest_website_semantic_result_or_none(client: Any, user_id: str, evidence_id: str):
    service = WebsiteSemanticVerificationService(client)
    try:
        return service.get_latest_result(user_id, evidence_id)
    except WebsiteSemanticVerificationResultNotFoundError:
        return None


def _to_response(row: dict[str, Any]) -> EvidenceAccessLinkResponse:
    return EvidenceAccessLinkResponse(
        id=str(row["id"]),
        evidence_id=str(row["evidence_id"]),
        source_report_type=row.get("source_report_type") or "none",
        source_report_id=str(row["source_report_id"]) if row.get("source_report_id") else None,
        access_type=row.get("access_type") or "github_exact_lines",
        label=row.get("label") or "",
        url=row.get("url") or "",
        source_type=row.get("source_type") or "github",
        file_path=row.get("file_path"),
        line_start=row.get("line_start"),
        line_end=row.get("line_end"),
        availability_status=row.get("availability_status") or "unavailable",
        notes=row.get("notes"),
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _range_value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _now() -> str:
    return datetime.now(UTC).isoformat()
