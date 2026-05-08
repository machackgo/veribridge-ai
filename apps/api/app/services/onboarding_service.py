"""Student onboarding persistence and Career Graph heatmap services."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.schemas.onboarding import (
    OpportunityHeatmapLocation,
    OpportunityHeatmapResponse,
    StudentOnboardingResponse,
    StudentOnboardingUpsert,
)
from app.services.market_data import MarketDataProvider, MockMarketDataProvider

_PROFILE_TABLE = "student_onboarding_profiles"
_CAREER_TABLE = "student_career_preferences"
_SKILLS_TABLE = "student_skills"
_COMP_TABLE = "student_compensation_preferences"


class StudentOnboardingService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def get_onboarding(self, user_id: str) -> StudentOnboardingResponse:
        if isinstance(self._client, dict):
            return _memory_get(self._client, user_id)

        profile = self._maybe_single(_PROFILE_TABLE, user_id) or {}
        career = self._maybe_single(_CAREER_TABLE, user_id) or {}
        comp = self._maybe_single(_COMP_TABLE, user_id) or {}
        skills_result = (
            self._client.table(_SKILLS_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
        skills = getattr(skills_result, "data", []) or []
        return _to_response(user_id, profile, career, comp, skills)

    def upsert_onboarding(
        self,
        user_id: str,
        data: StudentOnboardingUpsert,
    ) -> StudentOnboardingResponse:
        if isinstance(self._client, dict):
            self._client.setdefault("onboarding", {})[user_id] = data.model_dump()
            return _memory_get(self._client, user_id)

        self._upsert(
            _PROFILE_TABLE,
            {
                "user_id": user_id,
                "university_country": data.university_country,
                "degree_level": data.degree_level,
                "major": data.major,
                "graduation_year": data.graduation_year,
                "job_search_timeline": data.job_search_timeline,
                "urgency_level": data.urgency_level,
                "work_authorization_countries": data.work_authorization_countries,
                "sponsorship_needed": data.sponsorship_needed,
                "visa_status": data.visa_status,
                "work_authorization_notes": data.work_authorization_notes,
            },
        )
        self._upsert(
            _CAREER_TABLE,
            {
                "user_id": user_id,
                "career_fields": data.career_fields,
                "target_roles": data.target_roles,
                "target_industries": data.target_industries,
                "target_locations": data.target_locations,
                "preferred_work_modes": data.preferred_work_modes,
                "open_to_relocate": data.open_to_relocate,
                "global_search_open": data.global_search_open,
            },
        )
        self._upsert(
            _COMP_TABLE,
            {
                "user_id": user_id,
                "expected_salary_min": data.expected_salary_min,
                "expected_salary_max": data.expected_salary_max,
                "minimum_acceptable_salary": data.minimum_acceptable_salary,
                "salary_currency": data.salary_currency,
                "salary_period": data.salary_period,
                "open_to_negotiation": data.open_to_negotiation,
            },
        )

        for skill in data.skills:
            self._client.table(_SKILLS_TABLE).insert(
                {"user_id": user_id, **skill.model_dump()}
            ).execute()

        return self.get_onboarding(user_id)

    def mark_complete(self, user_id: str) -> str:
        completed_at = datetime.now(UTC).isoformat()
        if isinstance(self._client, dict):
            record = self._client.setdefault("onboarding", {}).setdefault(user_id, {})
            record["completed_at"] = completed_at
            return completed_at

        self._client.table(_PROFILE_TABLE).update(
            {"completed_at": completed_at}
        ).eq("user_id", user_id).execute()
        return completed_at

    def _maybe_single(self, table: str, user_id: str) -> dict[str, Any] | None:
        result = (
            self._client.table(table)
            .select("*")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return None if result is None else result.data

    def _upsert(self, table: str, payload: dict[str, Any]) -> None:
        self._client.table(table).upsert(payload, on_conflict="user_id").execute()


class OpportunityHeatmapService:
    def __init__(
        self,
        onboarding_service: StudentOnboardingService,
        provider: MarketDataProvider | None = None,
    ) -> None:
        self._onboarding_service = onboarding_service
        self._provider = provider or MockMarketDataProvider()

    def get_heatmap(self, user_id: str) -> OpportunityHeatmapResponse:
        onboarding = self._onboarding_service.get_onboarding(user_id)
        selected = onboarding.target_locations
        market = self._provider.get_location_market_data(
            onboarding.career_fields,
            onboarding.target_roles,
            selected,
        )
        recs = [
            self._score_location(row, onboarding)
            for row in market
        ]
        recs.sort(key=lambda item: item.recommendation_score, reverse=True)

        top_names = [item.location_name for item in recs[:3]]
        selected_name = selected[0] if selected else "your selected location"
        return OpportunityHeatmapResponse(
            user_id=user_id,
            selected_locations=selected,
            recommended_locations=recs,
            guidance_message=(
                f"You selected {selected_name}, but {', '.join(top_names)} currently "
                "show stronger market signals for your selected roles. Would you like to expand your search?"
            ),
            data_provider=self._provider.name,
        )

    @staticmethod
    def _score_location(row: Any, onboarding: StudentOnboardingResponse) -> OpportunityHeatmapLocation:
        selected_match = row.location_name in onboarding.target_locations
        field_match = any(field in row.field_strengths for field in onboarding.career_fields)
        auth_fit = _work_authorization_fit(row.country, onboarding)
        salary_fit = _salary_fit(row.salary_min, row.salary_max, onboarding)

        score = 45
        score += min(25, row.estimated_open_roles // 700)
        score += 12 if field_match else 0
        score += 8 if row.remote_availability == "High" else 4
        score += {"High": 12, "Medium": 6, "Low": -4}[auth_fit]
        score += {"Strong": 8, "Aligned": 4, "Below target": -8}[salary_fit]
        score += 5 if selected_match else 0
        score = max(0, min(100, score))

        reasons = [
            f"{row.estimated_open_roles:,} estimated open roles across compatible fields.",
            f"{row.remote_availability} remote availability for flexible search strategy.",
            f"{auth_fit} work authorization fit based on student-controlled inputs.",
        ]
        if field_match:
            reasons.append("Strong signal for at least one selected career field.")
        if salary_fit != "Below target":
            reasons.append("Compensation Fit aligns with stated salary expectations.")

        return OpportunityHeatmapLocation(
            location_name=row.location_name,
            country=row.country,
            estimated_open_roles=row.estimated_open_roles,
            salary_min=row.salary_min,
            salary_max=row.salary_max,
            currency=row.currency,
            competition_level=row.competition_level,
            remote_availability=row.remote_availability,
            work_authorization_fit=auth_fit,
            salary_fit=salary_fit,
            recommendation_score=score,
            reasons=reasons,
        )


def _memory_get(store: dict[str, Any], user_id: str) -> StudentOnboardingResponse:
    payload = store.setdefault("onboarding", {}).get(user_id, {})
    return StudentOnboardingResponse(user_id=user_id, **payload)


def _to_response(
    user_id: str,
    profile: dict[str, Any],
    career: dict[str, Any],
    comp: dict[str, Any],
    skills: list[dict[str, Any]],
) -> StudentOnboardingResponse:
    return StudentOnboardingResponse(
        user_id=user_id,
        university_country=profile.get("university_country"),
        degree_level=profile.get("degree_level"),
        major=profile.get("major"),
        graduation_year=profile.get("graduation_year"),
        job_search_timeline=profile.get("job_search_timeline"),
        urgency_level=profile.get("urgency_level"),
        work_authorization_countries=profile.get("work_authorization_countries") or [],
        sponsorship_needed=profile.get("sponsorship_needed") or False,
        visa_status=profile.get("visa_status"),
        work_authorization_notes=profile.get("work_authorization_notes"),
        completed_at=str(profile.get("completed_at")) if profile.get("completed_at") else None,
        career_fields=career.get("career_fields") or [],
        target_roles=career.get("target_roles") or [],
        target_industries=career.get("target_industries") or [],
        target_locations=career.get("target_locations") or [],
        preferred_work_modes=career.get("preferred_work_modes") or [],
        open_to_relocate=career.get("open_to_relocate") or False,
        global_search_open=career.get("global_search_open") or False,
        skills=skills,
        expected_salary_min=comp.get("expected_salary_min"),
        expected_salary_max=comp.get("expected_salary_max"),
        minimum_acceptable_salary=comp.get("minimum_acceptable_salary"),
        salary_currency=comp.get("salary_currency") or "USD",
        salary_period=comp.get("salary_period") or "yearly",
        open_to_negotiation=True if comp.get("open_to_negotiation") is None else comp.get("open_to_negotiation"),
    )


def _work_authorization_fit(country: str, onboarding: StudentOnboardingResponse) -> str:
    countries = {item.lower() for item in onboarding.work_authorization_countries}
    if country.lower() in countries or "global" in countries:
        return "High"
    if country == "Global" and onboarding.global_search_open:
        return "High"
    if onboarding.sponsorship_needed:
        return "Medium"
    return "Medium" if onboarding.global_search_open else "Low"


def _salary_fit(salary_min: int, salary_max: int, onboarding: StudentOnboardingResponse) -> str:
    minimum = onboarding.minimum_acceptable_salary
    expected_min = onboarding.expected_salary_min
    if minimum is not None and salary_max < minimum:
        return "Below target"
    if expected_min is not None and salary_max >= expected_min:
        return "Strong"
    return "Aligned"
