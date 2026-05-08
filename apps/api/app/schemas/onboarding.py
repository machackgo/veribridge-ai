"""Schemas for universal student onboarding and Career Graph heatmaps."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


SalaryPeriod = Literal["hourly", "monthly", "yearly"]


class StudentSkillInput(BaseModel):
    skill_name: str = Field(..., min_length=1, max_length=120)
    skill_category: str | None = Field(default=None, max_length=120)
    proficiency_level: str | None = Field(default=None, max_length=80)
    evidence: list[dict] = Field(default_factory=list)
    verification_status: str = Field(default="self_reported", max_length=40)


class StudentOnboardingUpsert(BaseModel):
    university_country: str | None = Field(default=None, max_length=120)
    degree_level: str | None = Field(default=None, max_length=120)
    major: str | None = Field(default=None, max_length=255)
    graduation_year: int | None = Field(default=None, ge=1900, le=2100)

    career_fields: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    target_industries: list[str] = Field(default_factory=list)
    target_locations: list[str] = Field(default_factory=list)
    preferred_work_modes: list[str] = Field(default_factory=list)
    open_to_relocate: bool = False
    global_search_open: bool = False
    job_search_timeline: str | None = Field(default=None, max_length=120)
    urgency_level: str | None = Field(default=None, max_length=80)

    work_authorization_countries: list[str] = Field(default_factory=list)
    sponsorship_needed: bool = False
    visa_status: str | None = Field(default=None, max_length=120)
    work_authorization_notes: str | None = Field(default=None, max_length=1000)

    skills: list[StudentSkillInput] = Field(default_factory=list)

    expected_salary_min: float | None = Field(default=None, ge=0)
    expected_salary_max: float | None = Field(default=None, ge=0)
    minimum_acceptable_salary: float | None = Field(default=None, ge=0)
    salary_currency: str = Field(default="USD", min_length=3, max_length=3)
    salary_period: SalaryPeriod = "yearly"
    open_to_negotiation: bool = True

    @field_validator(
        "career_fields",
        "target_roles",
        "target_industries",
        "target_locations",
        "preferred_work_modes",
        "work_authorization_countries",
        mode="before",
    )
    @classmethod
    def _coerce_string_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    @field_validator("salary_currency", mode="before")
    @classmethod
    def _normalize_currency(cls, value: object) -> str:
        if not value:
            return "USD"
        return str(value).strip().upper()


class StudentOnboardingResponse(StudentOnboardingUpsert):
    user_id: str
    completed_at: str | None = None


class OnboardingCompleteResponse(BaseModel):
    user_id: str
    completed: bool
    completed_at: str


class OpportunityHeatmapLocation(BaseModel):
    location_name: str
    country: str
    estimated_open_roles: int
    salary_min: int
    salary_max: int
    currency: str
    competition_level: Literal["Low", "Medium", "High"]
    remote_availability: Literal["Low", "Medium", "High"]
    work_authorization_fit: Literal["Low", "Medium", "High"]
    salary_fit: Literal["Below target", "Aligned", "Strong"]
    recommendation_score: int = Field(..., ge=0, le=100)
    reasons: list[str]


class OpportunityHeatmapResponse(BaseModel):
    user_id: str
    feature_name: str = "Opportunity & Salary Heatmap"
    career_graph_name: str = "VeriBridge Career Graph"
    compensation_fit_name: str = "Compensation Fit"
    selected_locations: list[str]
    recommended_locations: list[OpportunityHeatmapLocation]
    guidance_message: str
    data_provider: str = "mock"
    market_data_warning: str = (
        "MVP market data is sample/mock data until Adzuna, JSearch, or BLS providers are connected."
    )
