"""Schemas for the Recruiter Candidate Search (Phase J1)."""

from __future__ import annotations

from pydantic import BaseModel


class CandidateSearchResult(BaseModel):
    user_id: str
    display_name: str
    school_name: str | None = None
    degree: str | None = None
    major: str | None = None
    matched_skill_names: list[str]
    evidence_count: int
    accepted_evidence_count: int
    has_github_proof: bool
    has_website_proof: bool
    strongest_project_title: str | None = None
    proof_status_label: str | None = None


class CandidateSearchResponse(BaseModel):
    query: str
    results: list[CandidateSearchResult]
    result_count: int
