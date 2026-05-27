"""Admin quality review / moderation service."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.schemas.admin_quality_review import (
    AdminQualityReviewCaseCreate,
    AdminQualityReviewCaseResponse,
    AdminQualityReviewCaseUpdate,
    AdminQualityReviewEventCreate,
    AdminQualityReviewEventResponse,
    AdminQualityReviewScanResponse,
)
from app.services.notification_service import NotificationService

_CASES = "admin_quality_review_cases"
_EVENTS = "admin_quality_review_events"
_USERS = "users"
_PRIVACY = "workflow_privacy_scan_results"
_AI_DOMAIN = "ai_domain_review_results"
_REQUESTER_PROFILES = "recruiter_requester_profiles"
_REQUESTS = "evidence_access_requests"
_GRANTS = "evidence_access_grants"
_PASSPORTS = "public_work_passports"

_OPEN_STATUSES = {"open", "under_review", "needs_student_action", "escalated"}


class AdminQualityReviewCaseNotFoundError(LookupError):
    """Admin quality review case not found."""


class AdminQualityReviewService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def create_quality_review_case(
        self,
        payload: AdminQualityReviewCaseCreate,
        actor_user_id: str | None = None,
    ) -> AdminQualityReviewCaseResponse:
        existing = self._matching_open_case(
            payload.proof_session_id,
            payload.case_type,
            payload.requester_profile_id,
            payload.access_request_id,
        )
        if existing:
            return self._case_response(existing)
        now = _now()
        row = {
            "id": str(uuid4()),
            "user_id": payload.user_id,
            "proof_session_id": payload.proof_session_id,
            "passport_id": payload.passport_id,
            "access_request_id": payload.access_request_id,
            "requester_profile_id": payload.requester_profile_id,
            "case_type": payload.case_type,
            "status": payload.status,
            "priority": payload.priority,
            "risk_score": payload.risk_score,
            "risk_flags": list(payload.risk_flags or []),
            "source": payload.source,
            "title": payload.title,
            "summary": payload.summary,
            "assigned_admin_id": payload.assigned_admin_id,
            "admin_notes": payload.admin_notes,
            "decision": None,
            "decision_reason": None,
            "requested_student_actions": list(payload.requested_student_actions or []),
            "resolved_at": None,
            "created_at": now,
            "updated_at": now,
        }
        saved = self._insert(_CASES, row)
        self.add_quality_review_event(
            str(saved["id"]),
            AdminQualityReviewEventCreate(
                event_type="case_created",
                event_summary=saved.get("summary") or saved.get("title") or "Quality review case created.",
                metadata={"case_type": saved["case_type"], "source": saved["source"], "risk_flags": saved["risk_flags"]},
            ),
            actor_user_id=actor_user_id,
            actor_type="admin" if actor_user_id else "system",
        )
        return self._case_response(saved)

    def list_quality_review_cases(
        self,
        *,
        status: str | None = None,
        priority: str | None = None,
        case_type: str | None = None,
        user_id: str | None = None,
        proof_session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AdminQualityReviewCaseResponse]:
        rows = list(self._table_rows(_CASES))
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if priority:
            rows = [row for row in rows if row.get("priority") == priority]
        if case_type:
            rows = [row for row in rows if row.get("case_type") == case_type]
        if user_id:
            rows = [row for row in rows if str(row.get("user_id")) == user_id]
        if proof_session_id:
            rows = [row for row in rows if str(row.get("proof_session_id")) == proof_session_id]
        rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return [self._case_response(row) for row in rows[offset:offset + limit]]

    def get_quality_review_case(self, case_id: str) -> AdminQualityReviewCaseResponse:
        row = self._by_id(_CASES, case_id)
        if not row:
            raise AdminQualityReviewCaseNotFoundError(case_id)
        return self._case_response(row, include_events=True)

    def update_quality_review_case(
        self,
        case_id: str,
        payload: AdminQualityReviewCaseUpdate,
        actor_user_id: str | None = None,
    ) -> AdminQualityReviewCaseResponse:
        row = self._by_id(_CASES, case_id)
        if not row:
            raise AdminQualityReviewCaseNotFoundError(case_id)
        old_status = row.get("status")
        updates = payload.model_dump(exclude_unset=True)
        for key, value in updates.items():
            row[key] = value
        if row.get("status") in {"resolved", "dismissed"} and not row.get("resolved_at"):
            row["resolved_at"] = _now()
        row["updated_at"] = _now()
        saved = self._save(_CASES, row)
        if payload.status and payload.status != old_status:
            self.add_quality_review_event(
                case_id,
                AdminQualityReviewEventCreate(
                    event_type=_event_type_for_status(payload.status),
                    event_summary=f"Case status changed to {payload.status}.",
                    metadata={"old_status": old_status, "new_status": payload.status},
                ),
                actor_user_id=actor_user_id,
                actor_type="admin",
            )
        if payload.admin_notes:
            self.add_quality_review_event(
                case_id,
                AdminQualityReviewEventCreate(event_type="admin_note_added", event_summary=payload.admin_notes),
                actor_user_id=actor_user_id,
                actor_type="admin",
            )
        if payload.decision:
            self.add_quality_review_event(
                case_id,
                AdminQualityReviewEventCreate(
                    event_type="decision_recorded",
                    event_summary=f"Decision recorded: {payload.decision}.",
                    metadata={"decision": payload.decision, "decision_reason": payload.decision_reason},
                ),
                actor_user_id=actor_user_id,
                actor_type="admin",
            )
            if payload.decision in {"needs_more_evidence", "privacy_blocked"}:
                self._notify_student_attention(saved)
        if payload.requested_student_actions:
            self.add_quality_review_event(
                case_id,
                AdminQualityReviewEventCreate(
                    event_type="student_action_requested",
                    event_summary="Student action requested.",
                    metadata={"requested_student_actions": payload.requested_student_actions},
                ),
                actor_user_id=actor_user_id,
                actor_type="admin",
            )
        return self.get_quality_review_case(case_id)

    def add_quality_review_event(
        self,
        case_id: str,
        payload: AdminQualityReviewEventCreate,
        actor_user_id: str | None = None,
        actor_type: str = "system",
    ) -> AdminQualityReviewEventResponse:
        if not self._by_id(_CASES, case_id):
            raise AdminQualityReviewCaseNotFoundError(case_id)
        row = {
            "id": str(uuid4()),
            "case_id": case_id,
            "event_type": payload.event_type,
            "actor_user_id": actor_user_id,
            "actor_type": actor_type,
            "event_summary": payload.event_summary,
            "metadata": payload.metadata or {},
            "created_at": _now(),
        }
        return _event_response(self._insert(_EVENTS, row))

    def create_cases_from_existing_signals(
        self,
        user_id: str | None = None,
        proof_session_id: str | None = None,
    ) -> AdminQualityReviewScanResponse:
        candidates = []
        candidates.extend(self._privacy_candidates(user_id, proof_session_id))
        candidates.extend(self._ai_review_candidates(user_id, proof_session_id))
        candidates.extend(self._requester_risk_candidates(user_id, proof_session_id))
        candidates.extend(self._access_abuse_candidates(user_id, proof_session_id))
        created = 0
        existing = 0
        cases: list[AdminQualityReviewCaseResponse] = []
        for payload in candidates:
            before = len(list(self._table_rows(_CASES)))
            case = self.create_quality_review_case(payload)
            after = len(list(self._table_rows(_CASES)))
            created += int(after > before)
            existing += int(after == before)
            cases.append(case)
        return AdminQualityReviewScanResponse(created_count=created, existing_count=existing, cases=cases)

    def _privacy_candidates(self, user_id: str | None, proof_session_id: str | None) -> list[AdminQualityReviewCaseCreate]:
        out = []
        for row in self._filtered_rows(_PRIVACY, user_id, proof_session_id):
            status = str(row.get("status") or row.get("privacy_scan_status") or "").lower()
            if status in {"flagged", "warning", "unsafe"}:
                out.append(AdminQualityReviewCaseCreate(
                    user_id=str(row.get("user_id")) if row.get("user_id") else None,
                    proof_session_id=str(row.get("proof_session_id")) if row.get("proof_session_id") else None,
                    passport_id=self._passport_id(row.get("user_id"), row.get("proof_session_id")),
                    case_type="privacy_flag",
                    priority="high" if status != "warning" else "normal",
                    risk_score=80 if status in {"flagged", "unsafe"} else 50,
                    risk_flags=_list(row.get("risk_flags")) or [f"privacy_status:{status}"],
                    source="privacy_scan",
                    title="Privacy issue detected",
                    summary=str(row.get("scan_summary") or "Privacy scan requires admin review."),
                ))
        return out

    def _ai_review_candidates(self, user_id: str | None, proof_session_id: str | None) -> list[AdminQualityReviewCaseCreate]:
        out = []
        for row in self._filtered_rows(_AI_DOMAIN, user_id, proof_session_id):
            confidence = str(row.get("confidence_level") or "").lower()
            human_review = bool(row.get("human_review_recommended")) or row.get("ai_domain_review_status") == "human_review_recommended"
            if confidence == "low" or human_review:
                flags = ["low_confidence_ai_review"] if confidence == "low" else []
                if human_review:
                    flags.append("human_review_recommended")
                out.append(AdminQualityReviewCaseCreate(
                    user_id=str(row.get("user_id")) if row.get("user_id") else None,
                    proof_session_id=str(row.get("proof_session_id")) if row.get("proof_session_id") else None,
                    passport_id=self._passport_id(row.get("user_id"), row.get("proof_session_id")),
                    case_type="low_confidence_ai_review",
                    priority="normal" if confidence == "low" else "high",
                    risk_score=40 if confidence == "low" else 60,
                    risk_flags=flags,
                    source="ai_domain_review",
                    title="AI domain review needs moderation",
                    summary=str(row.get("recruiter_summary") or "AI domain review requires admin review."),
                ))
        return out

    def _requester_risk_candidates(self, user_id: str | None, proof_session_id: str | None) -> list[AdminQualityReviewCaseCreate]:
        out = []
        requests = self._filtered_rows(_REQUESTS, user_id, proof_session_id)
        profile_ids = {str(row.get("requester_profile_id")) for row in requests if row.get("requester_profile_id")}
        for profile_id in profile_ids:
            profile = self._by_id(_REQUESTER_PROFILES, profile_id)
            if not profile:
                continue
            risk_score = int(profile.get("risk_score") or 0)
            status = str(profile.get("verification_status") or "")
            if risk_score >= 30 or status in {"suspicious", "blocked"}:
                linked = next((row for row in requests if str(row.get("requester_profile_id")) == profile_id), {})
                out.append(AdminQualityReviewCaseCreate(
                    user_id=str(linked.get("user_id")) if linked.get("user_id") else None,
                    proof_session_id=str(linked.get("proof_session_id")) if linked.get("proof_session_id") else None,
                    passport_id=str(linked.get("passport_id")) if linked.get("passport_id") else None,
                    access_request_id=str(linked.get("id")) if linked.get("id") else None,
                    requester_profile_id=profile_id,
                    case_type="recruiter_risk",
                    priority="high" if status == "blocked" else "normal",
                    risk_score=risk_score,
                    risk_flags=_list(profile.get("risk_flags")) or [f"verification_status:{status}"],
                    source="requester_profile",
                    title="Requester risk requires review",
                    summary="Requester profile risk signals require moderation review.",
                ))
        return out

    def _access_abuse_candidates(self, user_id: str | None, proof_session_id: str | None) -> list[AdminQualityReviewCaseCreate]:
        grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"denied": 0, "revoked": 0, "row": None})
        requests = self._filtered_rows(_REQUESTS, user_id, proof_session_id)
        for row in requests:
            key = (str(row.get("user_id")), str(row.get("proof_session_id")))
            grouped[key]["row"] = grouped[key]["row"] or row
            if row.get("status") == "denied":
                grouped[key]["denied"] += 1
            if not row.get("request_reason"):
                grouped[key]["missing_reason"] = True
        grants = self._filtered_rows(_GRANTS, user_id, proof_session_id)
        for grant in grants:
            key = (str(grant.get("user_id")), str(grant.get("proof_session_id")))
            grouped[key]["row"] = grouped[key]["row"] or grant
            if grant.get("revoked_at"):
                grouped[key]["revoked"] += 1
        out = []
        for (_, session_id), data in grouped.items():
            if data["denied"] + data["revoked"] >= 3 or data.get("missing_reason"):
                row = data["row"] or {}
                flags = []
                if data["denied"]:
                    flags.append("repeated_denials")
                if data["revoked"]:
                    flags.append("repeated_revocations")
                if data.get("missing_reason"):
                    flags.append("missing_reason")
                out.append(AdminQualityReviewCaseCreate(
                    user_id=str(row.get("user_id")) if row.get("user_id") else None,
                    proof_session_id=session_id,
                    passport_id=self._passport_id(row.get("user_id"), session_id),
                    case_type="access_abuse",
                    priority="normal",
                    risk_score=30 + 10 * (data["denied"] + data["revoked"]),
                    risk_flags=flags,
                    source="access_request_monitor",
                    title="Access request pattern needs review",
                    summary="Access request or grant pattern requires moderation review.",
                ))
        return out

    def _notify_student_attention(self, case: dict[str, Any]) -> None:
        if not case.get("user_id"):
            return
        decision = case.get("decision")
        NotificationService(self._client).create_notification_event(
            user_id=str(case["user_id"]),
            event_type="privacy_issue_detected" if decision == "privacy_blocked" else "verification_needs_more_evidence",
            recipient_email=self._user_email(str(case["user_id"])),
            title="Evidence review needs attention",
            message="A VeriBridge review found an issue that needs your attention.",
            category="privacy" if decision == "privacy_blocked" else "verification",
            priority="high",
            metadata={"case_id": str(case["id"]), "proof_session_id": case.get("proof_session_id"), "decision": decision},
        )

    def _case_response(self, row: dict[str, Any], include_events: bool = False) -> AdminQualityReviewCaseResponse:
        events = []
        if include_events:
            events = [
                _event_response(event) for event in self._table_rows(_EVENTS)
                if str(event.get("case_id")) == str(row["id"])
            ]
            events.sort(key=lambda event: str(event.created_at))
        return _case_response(row, events)

    def _matching_open_case(
        self,
        proof_session_id: str | None,
        case_type: str,
        requester_profile_id: str | None = None,
        access_request_id: str | None = None,
    ) -> dict[str, Any] | None:
        if not proof_session_id and not requester_profile_id and not access_request_id:
            return None
        for row in self._table_rows(_CASES):
            if row.get("status") not in _OPEN_STATUSES:
                continue
            if str(row.get("proof_session_id") or "") != str(proof_session_id or ""):
                continue
            if row.get("case_type") != case_type:
                continue
            if str(row.get("requester_profile_id") or "") != str(requester_profile_id or ""):
                continue
            if str(row.get("access_request_id") or "") != str(access_request_id or ""):
                continue
            return row
        return None

    def _filtered_rows(self, table: str, user_id: str | None, proof_session_id: str | None) -> list[dict[str, Any]]:
        rows = list(self._table_rows(table))
        if user_id:
            rows = [row for row in rows if str(row.get("user_id")) == user_id]
        if proof_session_id:
            rows = [row for row in rows if str(row.get("proof_session_id")) == proof_session_id]
        return rows

    def _passport_id(self, user_id: Any, proof_session_id: Any) -> str | None:
        for row in self._filtered_rows(_PASSPORTS, str(user_id) if user_id else None, str(proof_session_id) if proof_session_id else None):
            return str(row["id"])
        return None

    def _user_email(self, user_id: str) -> str:
        row = self._by_id(_USERS, user_id)
        return str((row or {}).get("email") or "")

    def _table_rows(self, table: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            return list(self._client.get(table, {}).values())
        result = self._client.table(table).select("*").execute()
        return getattr(result, "data", []) or []

    def _by_id(self, table: str, row_id: str) -> dict[str, Any] | None:
        if isinstance(self._client, dict):
            return self._client.get(table, {}).get(row_id)
        result = self._client.table(table).select("*").eq("id", row_id).limit(1).execute()
        rows = getattr(result, "data", []) or []
        return rows[0] if rows else None

    def _insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        if isinstance(self._client, dict):
            self._client.setdefault(table, {})[str(row["id"])] = row
            return row
        result = self._client.table(table).insert(row).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError(f"{table} insert returned no data.")
        return rows[0]

    def _save(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        if isinstance(self._client, dict):
            self._client.setdefault(table, {})[str(row["id"])] = row
            return row
        result = self._client.table(table).upsert(row).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError(f"{table} upsert returned no data.")
        return rows[0]


def _case_response(row: dict[str, Any], events: list[AdminQualityReviewEventResponse] | None = None) -> AdminQualityReviewCaseResponse:
    return AdminQualityReviewCaseResponse(
        id=str(row["id"]),
        user_id=str(row["user_id"]) if row.get("user_id") else None,
        proof_session_id=str(row["proof_session_id"]) if row.get("proof_session_id") else None,
        passport_id=str(row["passport_id"]) if row.get("passport_id") else None,
        access_request_id=str(row["access_request_id"]) if row.get("access_request_id") else None,
        requester_profile_id=str(row["requester_profile_id"]) if row.get("requester_profile_id") else None,
        case_type=row["case_type"],
        status=row.get("status") or "open",
        priority=row.get("priority") or "normal",
        risk_score=int(row.get("risk_score") or 0),
        risk_flags=_list(row.get("risk_flags")),
        source=row.get("source") or "system",
        title=row.get("title"),
        summary=row.get("summary"),
        assigned_admin_id=str(row["assigned_admin_id"]) if row.get("assigned_admin_id") else None,
        admin_notes=row.get("admin_notes"),
        decision=row.get("decision"),
        decision_reason=row.get("decision_reason"),
        requested_student_actions=_list(row.get("requested_student_actions")),
        resolved_at=row.get("resolved_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        events=events or [],
    )


def _event_response(row: dict[str, Any]) -> AdminQualityReviewEventResponse:
    return AdminQualityReviewEventResponse(
        id=str(row["id"]),
        case_id=str(row["case_id"]),
        event_type=row["event_type"],
        actor_user_id=str(row["actor_user_id"]) if row.get("actor_user_id") else None,
        actor_type=row.get("actor_type") or "system",
        event_summary=row.get("event_summary"),
        metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
        created_at=row["created_at"],
    )


def _event_type_for_status(status: str) -> str:
    return {
        "resolved": "case_resolved",
        "dismissed": "case_dismissed",
        "escalated": "case_escalated",
    }.get(status, "case_status_changed")


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _now() -> datetime:
    return datetime.now(UTC)
