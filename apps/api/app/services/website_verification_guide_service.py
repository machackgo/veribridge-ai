"""Website verification guide persistence for deployed website proof evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from app.schemas.skill_evidence import (
    WebsiteVerificationGuideCreate,
    WebsiteVerificationGuideResponse,
)
from app.services.skill_evidence_service import SkillEvidenceNotFoundError

_EVIDENCE_TABLE = "skill_evidence"
_GUIDE_TABLE = "website_verification_guides"


class WebsiteVerificationGuideNotFoundError(LookupError):
    """No guide exists for the scoped evidence row."""


class WebsiteVerificationGuideNotAllowedError(ValueError):
    """The evidence row is not eligible for a website verification guide."""


class WebsiteVerificationGuideService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def save_guide(
        self,
        user_id: str,
        evidence_id: str,
        payload: WebsiteVerificationGuideCreate,
    ) -> WebsiteVerificationGuideResponse:
        evidence = self._get_evidence_row(user_id, evidence_id)
        _validate_website_evidence(evidence)
        data = {
            **payload.model_dump(),
            "user_id": user_id,
            "skill_evidence_id": evidence_id,
        }

        if isinstance(self._client, dict):
            existing = self._get_existing_guide_row(user_id, evidence_id)
            now = _now()
            if existing:
                row = {
                    **existing,
                    **data,
                    "updated_at": now,
                }
            else:
                row = {
                    "id": str(uuid4()),
                    "created_at": now,
                    "updated_at": now,
                    **data,
                }
            self._client.setdefault(_GUIDE_TABLE, {})[row["id"]] = row
            return _to_response(row)

        existing = self._get_existing_guide_row(user_id, evidence_id)
        if existing:
            result = (
                self._client.table(_GUIDE_TABLE)
                .update(data)
                .eq("user_id", user_id)
                .eq("skill_evidence_id", evidence_id)
                .execute()
            )
        else:
            result = self._client.table(_GUIDE_TABLE).insert(data).execute()

        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError("Website verification guide save returned no data.")
        return _to_response(rows[0])

    def get_guide(self, user_id: str, evidence_id: str) -> WebsiteVerificationGuideResponse:
        self._get_evidence_row(user_id, evidence_id)
        row = self._get_existing_guide_row(user_id, evidence_id)
        if not row:
            raise WebsiteVerificationGuideNotFoundError(evidence_id)
        return _to_response(row)

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

    def _get_existing_guide_row(self, user_id: str, evidence_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            for row in self._client.setdefault(_GUIDE_TABLE, {}).values():
                if row.get("user_id") == user_id and row.get("skill_evidence_id") == evidence_id:
                    return row
            return None

        result = (
            self._client.table(_GUIDE_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("skill_evidence_id", evidence_id)
            .maybe_single()
            .execute()
        )
        if result is None:
            return None
        return result.data


def _validate_website_evidence(row: dict[str, Any]) -> None:
    if (row.get("proof_visibility") or "public") != "public":
        raise WebsiteVerificationGuideNotAllowedError("Website verification guides require public proof evidence.")

    evidence_url = _clean(row.get("evidence_url"))
    if not _is_public_http_url(evidence_url):
        raise WebsiteVerificationGuideNotAllowedError("Website verification guides require a public live website URL.")

    host = (urlparse(evidence_url).hostname or "").lower()
    if host == "github.com" or host.endswith(".github.com") or host == "raw.githubusercontent.com":
        raise WebsiteVerificationGuideNotAllowedError("GitHub proof should use GitHub verification, not a website guide.")

    evidence_type = _clean(row.get("evidence_type")).lower()
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    proof_kind = _clean(metadata.get("proof_kind")).lower()
    combined = f"{evidence_type} {proof_kind}"
    if not _contains_any(
        combined,
        (
            "deployed",
            "website",
            "web",
            "live",
            "demo",
            "app",
            "application",
            "portfolio",
            "documentation",
            "docs",
            "project",
        ),
    ):
        raise WebsiteVerificationGuideNotAllowedError(
            "Evidence type must indicate a deployed website, live app, portfolio, documentation, or web project."
        )


def _is_public_http_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = parsed.hostname or ""
    return host not in {"localhost", "127.0.0.1", "0.0.0.0"} and not host.endswith(".local")


def _to_response(row: dict[str, Any]) -> WebsiteVerificationGuideResponse:
    return WebsiteVerificationGuideResponse(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        skill_evidence_id=str(row["skill_evidence_id"]),
        project_overview=row.get("project_overview"),
        feature_to_verify=row["feature_to_verify"],
        verification_steps=list(row.get("verification_steps") or []),
        sample_inputs=row.get("sample_inputs"),
        expected_output=row["expected_output"],
        login_required=bool(row.get("login_required")),
        login_notes=row.get("login_notes"),
        access_notes=row.get("access_notes"),
        known_limitations=row.get("known_limitations"),
        additional_notes=row.get("additional_notes"),
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _now() -> str:
    return datetime.now(UTC).isoformat()
