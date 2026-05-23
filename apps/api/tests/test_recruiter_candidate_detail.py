"""Tests for the Recruiter Candidate Detail endpoint and service (Phase J2)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.recruiter_candidate_detail_service import (
    CandidateNotFoundError,
    RecruiterCandidateDetailService,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_db(
    profiles: list[dict] | None = None,
    evidence: list[dict] | None = None,
    access_links: list[dict] | None = None,
) -> dict:
    db: dict = {
        "student_profiles": {},
        "skill_evidence": {},
        "evidence_access_links": {},
    }
    for p in profiles or []:
        db["student_profiles"][p["id"]] = p
    for e in evidence or []:
        db["skill_evidence"][e["id"]] = e
    for link in access_links or []:
        db["evidence_access_links"][link["id"]] = link
    return db


def _make_profile(
    id: str = "prof-1",
    user_id: str = "user-1",
    full_name: str = "Mohammed Mubashir",
    school_name: str = "WPI",
    degree: str = "MS",
    major: str = "Artificial Intelligence",
) -> dict:
    return {
        "id": id,
        "user_id": user_id,
        "full_name": full_name,
        "school_name": school_name,
        "degree": degree,
        "major": major,
        "graduation_year": 2026,
        "created_at": "2026-05-01T00:00:00Z",
        "updated_at": "2026-05-01T00:00:00Z",
    }


def _make_evidence(
    id: str = "ev-1",
    user_id: str = "user-1",
    skill_name: str = "Machine Learning",
    evidence_type: str = "github repository",
    verification_status: str = "verified",
    verification_summary: str = "Code detected.",
    metadata: dict | None = None,
) -> dict:
    return {
        "id": id,
        "user_id": user_id,
        "skill_name": skill_name,
        "evidence_type": evidence_type,
        "verification_status": verification_status,
        "verification_summary": verification_summary,
        "metadata": metadata or {"evidence_title": "Boston Accident Risk System"},
        "created_at": "2026-05-19T00:00:00Z",
        "updated_at": "2026-05-19T00:00:00Z",
    }


def _make_access_link(
    id: str = "link-1",
    evidence_id: str = "ev-1",
    user_id: str = "user-1",
    access_type: str = "github_exact_lines",
    url: str = "https://github.com/user/repo/blob/main/api.py#L19-L23",
    source_type: str = "github",
    file_path: str = "api.py",
    line_start: int | None = 19,
    line_end: int | None = 23,
    availability_status: str = "available",
    generation_id: str = "gen-1",
) -> dict:
    return {
        "id": id,
        "evidence_id": evidence_id,
        "user_id": user_id,
        "access_type": access_type,
        "label": "View Exact Code Lines" if access_type == "github_exact_lines" else "Open Live Website",
        "url": url,
        "source_type": source_type,
        "file_path": file_path,
        "line_start": line_start,
        "line_end": line_end,
        "availability_status": availability_status,
        "notes": None,
        "access_snapshot": {"generation_id": generation_id},
        "created_at": "2026-05-19T00:00:00Z",
        "updated_at": "2026-05-19T00:00:00Z",
    }


# ── RecruiterCandidateDetailService ───────────────────────────────────────────

class TestRecruiterCandidateDetailService:
    def test_returns_candidate_profile_basics(self):
        db = _make_db(
            profiles=[_make_profile(user_id="u1", full_name="Mohammed Mubashir", school_name="WPI", degree="MS", major="AI")],
        )
        result = RecruiterCandidateDetailService(db).get_candidate_detail("u1")
        assert result.candidate_id == "u1"
        assert result.display_name == "Mohammed Mubashir"
        assert result.school_name == "WPI"
        assert result.degree == "MS"
        assert result.major == "AI"

    def test_proof_overview_counts_are_correct(self):
        db = _make_db(
            profiles=[_make_profile(user_id="u1")],
            evidence=[
                _make_evidence(id="ev-1", user_id="u1", evidence_type="github repository", verification_status="verified"),
                _make_evidence(id="ev-2", user_id="u1", evidence_type="deployed website", verification_status="pending_review"),
                _make_evidence(id="ev-3", user_id="u1", evidence_type="github repository", verification_status="verified"),
            ],
        )
        result = RecruiterCandidateDetailService(db).get_candidate_detail("u1")
        assert result.proof_overview.total_evidence_count == 3
        assert result.proof_overview.accepted_evidence_count == 2
        assert result.proof_overview.github_proof_count == 2
        assert result.proof_overview.website_proof_count == 1
        assert result.proof_overview.strongest_display_status == "Evidence Accepted"

    def test_github_only_project_grouping(self):
        db = _make_db(
            profiles=[_make_profile(user_id="u1")],
            evidence=[
                _make_evidence(
                    id="ev-1",
                    user_id="u1",
                    evidence_type="github repository",
                    metadata={"evidence_title": "GitHub Only Project"},
                ),
            ],
            access_links=[
                _make_access_link(
                    id="link-1",
                    evidence_id="ev-1",
                    user_id="u1",
                    access_type="github_exact_lines",
                    source_type="github",
                ),
            ],
        )
        result = RecruiterCandidateDetailService(db).get_candidate_detail("u1")
        assert len(result.proof_projects) == 1
        project = result.proof_projects[0]
        assert project.project_title == "GitHub Only Project"
        assert project.has_github_proof is True
        assert project.has_website_proof is False
        assert len(project.evidence_access_links) == 1
        assert project.evidence_access_links[0].access_type == "github_exact_lines"

    def test_website_only_project_grouping(self):
        db = _make_db(
            profiles=[_make_profile(user_id="u1")],
            evidence=[
                _make_evidence(
                    id="ev-1",
                    user_id="u1",
                    evidence_type="deployed website",
                    metadata={"evidence_title": "Website Only Project"},
                ),
            ],
            access_links=[
                _make_access_link(
                    id="link-1",
                    evidence_id="ev-1",
                    user_id="u1",
                    access_type="live_website",
                    url="https://example.com",
                    source_type="website",
                    file_path=None,
                    line_start=None,
                    line_end=None,
                ),
            ],
        )
        result = RecruiterCandidateDetailService(db).get_candidate_detail("u1")
        assert len(result.proof_projects) == 1
        project = result.proof_projects[0]
        assert project.project_title == "Website Only Project"
        assert project.has_github_proof is False
        assert project.has_website_proof is True
        assert len(project.evidence_access_links) == 1
        assert project.evidence_access_links[0].access_type == "live_website"

    def test_github_and_website_same_title_produces_combined_bundle(self):
        title = "Boston Smart Accident Risk and Rerouting System"
        db = _make_db(
            profiles=[_make_profile(user_id="u1")],
            evidence=[
                _make_evidence(
                    id="ev-github",
                    user_id="u1",
                    evidence_type="github repository",
                    metadata={"evidence_title": title},
                ),
                _make_evidence(
                    id="ev-website",
                    user_id="u1",
                    evidence_type="deployed website",
                    metadata={"evidence_title": title},
                ),
            ],
            access_links=[
                _make_access_link(
                    id="link-github",
                    evidence_id="ev-github",
                    user_id="u1",
                    access_type="github_exact_lines",
                    source_type="github",
                ),
                _make_access_link(
                    id="link-website",
                    evidence_id="ev-website",
                    user_id="u1",
                    access_type="live_website",
                    url="https://example.com/boston",
                    source_type="website",
                    file_path=None,
                    line_start=None,
                    line_end=None,
                    generation_id="gen-website-1",
                ),
            ],
        )
        result = RecruiterCandidateDetailService(db).get_candidate_detail("u1")
        # Same title → combined into one project bundle
        assert len(result.proof_projects) == 1
        project = result.proof_projects[0]
        assert project.project_title == title
        assert project.has_github_proof is True
        assert project.has_website_proof is True
        access_types = {link.access_type for link in project.evidence_access_links}
        assert "github_exact_lines" in access_types
        assert "live_website" in access_types

    def test_evidence_access_links_included(self):
        db = _make_db(
            profiles=[_make_profile(user_id="u1")],
            evidence=[_make_evidence(id="ev-1", user_id="u1")],
            access_links=[
                _make_access_link(
                    id="link-1",
                    evidence_id="ev-1",
                    user_id="u1",
                    url="https://github.com/user/repo/blob/main/api.py#L19-L23",
                ),
            ],
        )
        result = RecruiterCandidateDetailService(db).get_candidate_detail("u1")
        assert len(result.proof_projects) == 1
        links = result.proof_projects[0].evidence_access_links
        assert len(links) == 1
        assert "github.com" in links[0].url

    def test_github_exact_line_data_preserved(self):
        db = _make_db(
            profiles=[_make_profile(user_id="u1")],
            evidence=[_make_evidence(id="ev-1", user_id="u1")],
            access_links=[
                _make_access_link(
                    id="link-1",
                    evidence_id="ev-1",
                    user_id="u1",
                    access_type="github_exact_lines",
                    url="https://github.com/user/repo/blob/main/api.py#L19-L23",
                    source_type="github",
                    file_path="api.py",
                    line_start=19,
                    line_end=23,
                ),
            ],
        )
        result = RecruiterCandidateDetailService(db).get_candidate_detail("u1")
        link = result.proof_projects[0].evidence_access_links[0]
        assert link.access_type == "github_exact_lines"
        assert link.line_start == 19
        assert link.line_end == 23
        assert link.file_path == "api.py"
        assert "#L19-L23" in link.url

    def test_live_website_link_data_preserved(self):
        db = _make_db(
            profiles=[_make_profile(user_id="u1")],
            evidence=[_make_evidence(id="ev-1", user_id="u1", evidence_type="deployed website")],
            access_links=[
                _make_access_link(
                    id="link-1",
                    evidence_id="ev-1",
                    user_id="u1",
                    access_type="live_website",
                    url="https://boston-app.example.com",
                    source_type="website",
                    file_path=None,
                    line_start=None,
                    line_end=None,
                ),
            ],
        )
        result = RecruiterCandidateDetailService(db).get_candidate_detail("u1")
        link = result.proof_projects[0].evidence_access_links[0]
        assert link.access_type == "live_website"
        assert link.url == "https://boston-app.example.com"
        assert link.line_start is None
        assert link.line_end is None

    def test_recruiter_safe_summary_included(self):
        db = _make_db(
            profiles=[_make_profile(user_id="u1")],
            evidence=[
                _make_evidence(
                    id="ev-1",
                    user_id="u1",
                    verification_summary="Model training and evaluation logic detected.",
                )
            ],
        )
        result = RecruiterCandidateDetailService(db).get_candidate_detail("u1")
        assert result.proof_projects[0].recruiter_summary == "Model training and evaluation logic detected."

    def test_unknown_candidate_raises_not_found(self):
        db = _make_db()
        with pytest.raises(CandidateNotFoundError):
            RecruiterCandidateDetailService(db).get_candidate_detail("user-who-does-not-exist")

    def test_no_proof_data_returns_sparse_valid_response(self):
        db = _make_db(
            profiles=[_make_profile(user_id="u1")],
        )
        result = RecruiterCandidateDetailService(db).get_candidate_detail("u1")
        assert result.candidate_id == "u1"
        assert result.proof_overview.total_evidence_count == 0
        assert result.proof_overview.accepted_evidence_count == 0
        assert result.proof_projects == []
        assert result.verified_or_supported_skills == []

    def test_unavailable_links_are_excluded(self):
        db = _make_db(
            profiles=[_make_profile(user_id="u1")],
            evidence=[_make_evidence(id="ev-1", user_id="u1")],
            access_links=[
                _make_access_link(
                    id="link-unavailable",
                    evidence_id="ev-1",
                    user_id="u1",
                    availability_status="insufficient_data",
                    url="",
                ),
            ],
        )
        result = RecruiterCandidateDetailService(db).get_candidate_detail("u1")
        assert result.proof_projects[0].evidence_access_links == []

    def test_response_does_not_expose_raw_snapshots_or_secrets(self):
        db = _make_db(
            profiles=[_make_profile(user_id="u1")],
            evidence=[_make_evidence(id="ev-1", user_id="u1")],
            access_links=[
                _make_access_link(
                    id="link-1", evidence_id="ev-1", user_id="u1"
                )
            ],
        )
        result = RecruiterCandidateDetailService(db).get_candidate_detail("u1")
        data = result.model_dump()
        # No raw snapshot, no secret fields in the response
        assert "access_snapshot" not in str(data)
        assert "source_report_id" not in str(data)
        assert "source_report_type" not in str(data)

    def test_only_evidence_for_requested_user_is_returned(self):
        db = _make_db(
            profiles=[
                _make_profile(id="p1", user_id="u1", full_name="Alice"),
                _make_profile(id="p2", user_id="u2", full_name="Bob"),
            ],
            evidence=[
                _make_evidence(id="ev-1", user_id="u1", skill_name="Python"),
                _make_evidence(id="ev-2", user_id="u2", skill_name="Machine Learning"),
            ],
        )
        result = RecruiterCandidateDetailService(db).get_candidate_detail("u1")
        assert result.display_name == "Alice"
        assert result.proof_overview.total_evidence_count == 1
        skill_names = [s.skill_name for s in result.verified_or_supported_skills]
        assert "Python" in skill_names
        assert "Machine Learning" not in skill_names


# ── HTTP endpoint ──────────────────────────────────────────────────────────────

def _make_client_with_db(db: dict) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user_id] = lambda: "recruiter-user-1"
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.clear()


def test_detail_endpoint_returns_candidate_basics():
    db = _make_db(
        profiles=[_make_profile(user_id="u1", full_name="Mohammed Mubashir", school_name="WPI")],
        evidence=[_make_evidence(id="ev-1", user_id="u1")],
    )
    client = _make_client_with_db(db)
    res = client.get("/api/v1/recruiter/candidates/u1/detail")
    assert res.status_code == 200
    body = res.json()
    assert body["candidate_id"] == "u1"
    assert body["display_name"] == "Mohammed Mubashir"
    assert body["school_name"] == "WPI"


def test_detail_endpoint_returns_404_for_unknown_candidate():
    db = _make_db()
    client = _make_client_with_db(db)
    res = client.get("/api/v1/recruiter/candidates/does-not-exist/detail")
    assert res.status_code == 404


def test_detail_endpoint_includes_proof_overview():
    db = _make_db(
        profiles=[_make_profile(user_id="u1")],
        evidence=[
            _make_evidence(id="ev-1", user_id="u1", evidence_type="github repository", verification_status="verified"),
            _make_evidence(id="ev-2", user_id="u1", evidence_type="deployed website", verification_status="pending_review"),
        ],
    )
    client = _make_client_with_db(db)
    res = client.get("/api/v1/recruiter/candidates/u1/detail")
    assert res.status_code == 200
    overview = res.json()["proof_overview"]
    assert overview["total_evidence_count"] == 2
    assert overview["accepted_evidence_count"] == 1
    assert overview["github_proof_count"] == 1
    assert overview["website_proof_count"] == 1


def test_detail_endpoint_includes_projects_with_access_links():
    db = _make_db(
        profiles=[_make_profile(user_id="u1")],
        evidence=[_make_evidence(id="ev-1", user_id="u1")],
        access_links=[
            _make_access_link(
                id="link-1",
                evidence_id="ev-1",
                user_id="u1",
                url="https://github.com/user/repo/blob/main/api.py#L19-L23",
            )
        ],
    )
    client = _make_client_with_db(db)
    res = client.get("/api/v1/recruiter/candidates/u1/detail")
    assert res.status_code == 200
    projects = res.json()["proof_projects"]
    assert len(projects) == 1
    assert len(projects[0]["evidence_access_links"]) == 1
    assert "github.com" in projects[0]["evidence_access_links"][0]["url"]


def test_detail_endpoint_does_not_conflict_with_search():
    db = _make_db()
    client = _make_client_with_db(db)
    res = client.get("/api/v1/recruiter/candidates/search?query=")
    assert res.status_code == 200
    assert "results" in res.json()


# ── Proof metadata persistence tests ─────────────────────────────────────────

_FAKE_SCREENSHOT = "data:image/jpeg;base64,/9j/fakeimagedata=="


def test_proof_project_includes_screenshot_url_from_metadata():
    """ProofProjectSummary.screenshot_url is populated from evidence metadata."""
    db = _make_db(
        profiles=[_make_profile(user_id="u1")],
        evidence=[
            _make_evidence(
                id="ev-bw",
                user_id="u1",
                skill_name="ML Engineering",
                evidence_type="deployed website",
                metadata={
                    "evidence_title": "Browser UI Workflow — boston-app.run.app",
                    "proof_kind": "browser_workflow_verification",
                    "screenshot_url": _FAKE_SCREENSHOT,
                    "screenshot_caption": "Final UI output after workflow execution",
                    "browser_workflow_status": "passed",
                },
            )
        ],
    )
    result = RecruiterCandidateDetailService(db).get_candidate_detail("u1")
    assert len(result.proof_projects) == 1
    proj = result.proof_projects[0]
    assert proj.screenshot_url == _FAKE_SCREENSHOT
    assert proj.screenshot_caption == "Final UI output after workflow execution"


def test_proof_project_includes_browser_screenshot_url_fallback():
    """browser_screenshot_url in metadata (functional candidates) is surfaced."""
    db = _make_db(
        profiles=[_make_profile(user_id="u1")],
        evidence=[
            _make_evidence(
                id="ev-fc",
                user_id="u1",
                skill_name="Backend API",
                evidence_type="deployed website",
                metadata={
                    "evidence_title": "FastAPI prediction endpoint",
                    "proof_kind": "functional_verification",
                    "verified": True,
                    "browser_screenshot_url": _FAKE_SCREENSHOT,
                    "browser_screenshot_caption": "Browser UI workflow screenshot",
                    "response_summary": "Risk class: High, Confidence: 0.82",
                },
            )
        ],
    )
    result = RecruiterCandidateDetailService(db).get_candidate_detail("u1")
    proj = result.proof_projects[0]
    assert proj.screenshot_url == _FAKE_SCREENSHOT
    assert proj.api_verified is True


def test_proof_project_api_verified_true_when_functional_verified():
    """api_verified is True when any evidence row has proof_kind=functional_verification + verified=True."""
    db = _make_db(
        profiles=[_make_profile(user_id="u1")],
        evidence=[
            _make_evidence(
                id="ev-1",
                user_id="u1",
                evidence_type="deployed website",
                metadata={
                    "evidence_title": "Prediction endpoint test",
                    "proof_kind": "functional_verification",
                    "verified": True,
                    "response_summary": "Returned risk_class=High",
                },
            )
        ],
    )
    result = RecruiterCandidateDetailService(db).get_candidate_detail("u1")
    proj = result.proof_projects[0]
    assert proj.api_verified is True
    assert proj.api_output_summary is not None
    assert "risk_class" in (proj.api_output_summary or "").lower() or "returned" in (proj.api_output_summary or "").lower()


def test_proof_project_api_verified_false_when_not_verified():
    """api_verified stays False when verified field is absent or False."""
    db = _make_db(
        profiles=[_make_profile(user_id="u1")],
        evidence=[
            _make_evidence(
                id="ev-1",
                user_id="u1",
                evidence_type="deployed website",
                metadata={"proof_kind": "functional_verification", "verified": False},
            )
        ],
    )
    result = RecruiterCandidateDetailService(db).get_candidate_detail("u1")
    assert result.proof_projects[0].api_verified is False


def test_proof_project_screenshot_url_omitted_when_oversized():
    """Screenshots exceeding the 2MB size limit are not forwarded to recruiter."""
    oversized = "data:image/jpeg;base64," + ("A" * (3 * 1024 * 1024))
    db = _make_db(
        profiles=[_make_profile(user_id="u1")],
        evidence=[
            _make_evidence(
                id="ev-1",
                user_id="u1",
                evidence_type="deployed website",
                metadata={"proof_kind": "browser_workflow_verification", "screenshot_url": oversized},
            )
        ],
    )
    result = RecruiterCandidateDetailService(db).get_candidate_detail("u1")
    assert result.proof_projects[0].screenshot_url is None


def test_proof_project_screenshot_url_none_when_no_metadata():
    """Fields default to None when evidence has no proof metadata."""
    db = _make_db(
        profiles=[_make_profile(user_id="u1")],
        evidence=[_make_evidence(id="ev-1", user_id="u1")],
    )
    result = RecruiterCandidateDetailService(db).get_candidate_detail("u1")
    proj = result.proof_projects[0]
    assert proj.screenshot_url is None
    assert proj.api_verified is False
    assert proj.api_output_summary is None
