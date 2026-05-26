"""Work Passport analytics service."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from app.schemas.work_passport_analytics import (
    AccessRequestSummary,
    RequestedSectionSummary,
    RequesterOrganizationSummary,
    WorkPassportActivityItem,
    WorkPassportAnalyticsResponse,
)

_PASSPORTS = "public_work_passports"
_REQUESTS = "evidence_access_requests"
_GRANTS = "evidence_access_grants"
_AUDIT_EVENTS = "evidence_access_audit_events"
_VIEW_EVENTS = "public_passport_view_events"
_REQUESTER_PROFILES = "recruiter_requester_profiles"
_NOTIFICATIONS = "notification_events"


class WorkPassportAnalyticsService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def get_student_passport_analytics(
        self,
        user_id: str,
        proof_session_id: str | None = None,
    ) -> WorkPassportAnalyticsResponse:
        passports = self._passports(user_id, proof_session_id)
        passport_ids = {str(row["id"]) for row in passports}
        session_ids = {str(row["proof_session_id"]) for row in passports}
        requests = self._scoped_requests(user_id, proof_session_id, passport_ids, session_ids)
        grants = self._scoped_grants(user_id, proof_session_id, requests)
        audit_events = self._scoped_audit_events(user_id, proof_session_id, passport_ids, session_ids)
        view_events = self._view_events(passport_ids)
        requester_profiles = self._requester_profiles(requests)
        access_summary = self.get_access_request_summary(user_id, proof_session_id)
        return WorkPassportAnalyticsResponse(
            total_passports=len(passports),
            total_public_views=len(view_events),
            total_access_requests=access_summary.total_access_requests,
            pending_access_requests=access_summary.pending_access_requests,
            approved_access_requests=access_summary.approved_access_requests,
            denied_access_requests=access_summary.denied_access_requests,
            revoked_access_grants=access_summary.revoked_access_grants,
            active_access_grants=access_summary.active_access_grants,
            protected_evidence_views=len([
                row for row in audit_events
                if row.get("event_type") == "protected_evidence_viewed"
            ]),
            unique_requester_emails=len({
                str(row.get("requester_email")).lower()
                for row in requests
                if row.get("requester_email")
            }),
            unique_requester_organizations=len(_organization_keys(requests, requester_profiles)),
            top_requested_sections=self._top_requested_sections(requests),
            recent_activity=self.get_passport_activity_timeline(user_id, proof_session_id, limit=10),
            requester_organizations=self.get_requester_organization_summary(user_id, proof_session_id),
            unread_notifications=self._unread_notification_count(user_id),
            generated_at=_now(),
        )

    def get_passport_activity_timeline(
        self,
        user_id: str,
        proof_session_id: str | None = None,
        limit: int = 50,
    ) -> list[WorkPassportActivityItem]:
        passports = self._passports(user_id, proof_session_id)
        passport_ids = {str(row["id"]) for row in passports}
        session_ids = {str(row["proof_session_id"]) for row in passports}
        profiles = self._requester_profiles(self._scoped_requests(user_id, proof_session_id, passport_ids, session_ids))
        events = self._scoped_audit_events(user_id, proof_session_id, passport_ids, session_ids)
        events.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return [
            _activity_item(row, profiles)
            for row in events[:limit]
        ]

    def get_access_request_summary(
        self,
        user_id: str,
        proof_session_id: str | None = None,
    ) -> AccessRequestSummary:
        passports = self._passports(user_id, proof_session_id)
        passport_ids = {str(row["id"]) for row in passports}
        session_ids = {str(row["proof_session_id"]) for row in passports}
        requests = self._scoped_requests(user_id, proof_session_id, passport_ids, session_ids)
        grants = self._scoped_grants(user_id, proof_session_id, requests)
        return AccessRequestSummary(
            total_access_requests=len(requests),
            pending_access_requests=len([row for row in requests if row.get("status") == "pending"]),
            approved_access_requests=len([row for row in requests if row.get("status") == "approved"]),
            denied_access_requests=len([row for row in requests if row.get("status") == "denied"]),
            revoked_access_grants=len([row for row in grants if row.get("revoked_at")]),
            active_access_grants=len([row for row in grants if not row.get("revoked_at")]),
        )

    def get_requester_organization_summary(
        self,
        user_id: str,
        proof_session_id: str | None = None,
    ) -> list[RequesterOrganizationSummary]:
        passports = self._passports(user_id, proof_session_id)
        passport_ids = {str(row["id"]) for row in passports}
        session_ids = {str(row["proof_session_id"]) for row in passports}
        requests = self._scoped_requests(user_id, proof_session_id, passport_ids, session_ids)
        profiles = self._requester_profiles(requests)
        grouped: dict[tuple[str | None, str | None], dict[str, Any]] = defaultdict(
            lambda: {"request_count": 0, "emails": set()}
        )
        for row in requests:
            profile = profiles.get(str(row.get("requester_profile_id") or ""))
            organization_name = row.get("requester_organization") or (profile or {}).get("organization_name")
            organization_domain = (profile or {}).get("organization_domain")
            key = (organization_name, organization_domain)
            grouped[key]["request_count"] += 1
            if row.get("requester_email"):
                grouped[key]["emails"].add(str(row["requester_email"]).lower())
        summaries = [
            RequesterOrganizationSummary(
                organization_name=name,
                organization_domain=domain,
                request_count=value["request_count"],
                unique_requester_emails=len(value["emails"]),
            )
            for (name, domain), value in grouped.items()
        ]
        summaries.sort(key=lambda row: (-row.request_count, row.organization_name or row.organization_domain or ""))
        return summaries

    def _passports(self, user_id: str, proof_session_id: str | None = None) -> list[dict[str, Any]]:
        rows = self._rows_for_user(_PASSPORTS, user_id)
        if proof_session_id:
            rows = [row for row in rows if str(row.get("proof_session_id")) == proof_session_id]
        return rows

    def _scoped_requests(
        self,
        user_id: str,
        proof_session_id: str | None,
        passport_ids: set[str],
        session_ids: set[str],
    ) -> list[dict[str, Any]]:
        rows = self._rows_for_user(_REQUESTS, user_id)
        if proof_session_id:
            rows = [row for row in rows if str(row.get("proof_session_id")) == proof_session_id]
        return [
            row for row in rows
            if str(row.get("passport_id")) in passport_ids
            or str(row.get("proof_session_id")) in session_ids
        ]

    def _scoped_grants(
        self,
        user_id: str,
        proof_session_id: str | None,
        requests: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        request_ids = {str(row["id"]) for row in requests}
        rows = self._rows_for_user(_GRANTS, user_id)
        if proof_session_id:
            rows = [row for row in rows if str(row.get("proof_session_id")) == proof_session_id]
        return [row for row in rows if str(row.get("access_request_id")) in request_ids]

    def _scoped_audit_events(
        self,
        user_id: str,
        proof_session_id: str | None,
        passport_ids: set[str],
        session_ids: set[str],
    ) -> list[dict[str, Any]]:
        rows = self._rows_for_user(_AUDIT_EVENTS, user_id)
        if proof_session_id:
            rows = [row for row in rows if str(row.get("proof_session_id")) == proof_session_id]
        return [
            row for row in rows
            if str(row.get("passport_id")) in passport_ids
            or str(row.get("proof_session_id")) in session_ids
        ]

    def _view_events(self, passport_ids: set[str]) -> list[dict[str, Any]]:
        if not passport_ids:
            return []
        if isinstance(self._client, dict):
            return [
                row for row in self._client.get(_VIEW_EVENTS, {}).values()
                if str(row.get("passport_id")) in passport_ids
            ]
        result = self._client.table(_VIEW_EVENTS).select("*").in_("passport_id", list(passport_ids)).execute()
        return getattr(result, "data", []) or []

    def _requester_profiles(self, requests: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        profile_ids = {
            str(row.get("requester_profile_id"))
            for row in requests
            if row.get("requester_profile_id")
        }
        if not profile_ids:
            return {}
        if isinstance(self._client, dict):
            return {
                profile_id: row
                for profile_id, row in self._client.get(_REQUESTER_PROFILES, {}).items()
                if profile_id in profile_ids
            }
        result = self._client.table(_REQUESTER_PROFILES).select("*").in_("id", list(profile_ids)).execute()
        rows = getattr(result, "data", []) or []
        return {str(row["id"]): row for row in rows}

    def _top_requested_sections(self, requests: list[dict[str, Any]]) -> list[RequestedSectionSummary]:
        counts: Counter[str] = Counter()
        for row in requests:
            for section in row.get("requested_sections") or []:
                counts[str(section)] += 1
        return [
            RequestedSectionSummary(section=section, count=count)
            for section, count in counts.most_common()
        ]

    def _unread_notification_count(self, user_id: str) -> int:
        return len([
            row for row in self._rows_for_user(_NOTIFICATIONS, user_id)
            if row.get("read_at") is None and row.get("archived_at") is None
        ])

    def _rows_for_user(self, table: str, user_id: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            return [
                row for row in self._client.get(table, {}).values()
                if str(row.get("user_id")) == user_id
            ]
        result = self._client.table(table).select("*").eq("user_id", user_id).execute()
        return getattr(result, "data", []) or []


def _activity_item(
    row: dict[str, Any],
    profiles: dict[str, dict[str, Any]],
) -> WorkPassportActivityItem:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    profile_id = metadata.get("requester_profile_id")
    profile = profiles.get(str(profile_id)) if profile_id else None
    return WorkPassportActivityItem(
        event_type=str(row["event_type"]),
        event_summary=row.get("event_summary"),
        actor_type=row.get("actor_type"),
        actor_email=row.get("actor_email"),
        requester_organization=metadata.get("requester_organization") or (profile or {}).get("organization_name"),
        proof_session_id=str(row["proof_session_id"]) if row.get("proof_session_id") else None,
        passport_id=str(row["passport_id"]) if row.get("passport_id") else None,
        created_at=row["created_at"],
    )


def _organization_keys(
    requests: list[dict[str, Any]],
    profiles: dict[str, dict[str, Any]],
) -> set[tuple[str | None, str | None]]:
    keys: set[tuple[str | None, str | None]] = set()
    for row in requests:
        profile = profiles.get(str(row.get("requester_profile_id") or ""))
        organization_name = row.get("requester_organization") or (profile or {}).get("organization_name")
        organization_domain = (profile or {}).get("organization_domain")
        if organization_name or organization_domain:
            keys.add((organization_name, organization_domain))
    return keys


def _now() -> datetime:
    return datetime.now(UTC)
