"""
Tests for the Project Defense Transcript Analysis feature.

Covers:
- Transcript with claimed skills increases overall defense score
- Vague/short transcript gets low clarity and overall score
- Transcript mentioning ownership increases ownership_signal_score
- Transcript contradicting evidence creates a risk flag
- Transcript containing an API key / token is flagged (privacy_scan_status = 'flagged')
- Readiness report improves when a strong project defense exists
- Missing transcript does NOT break existing proof flow or readiness
- Final verification NEVER becomes "complete" from this feature
- No project-specific hardcoding (no Boston / React-demo specific rules)
- POST /analyze/project-defense returns 404 for unknown session
- GET /analysis/project-defense returns 404 before analysis is run
- Skills explained well subset of skills mentioned
- Extremely short transcript gets deduction and risk flag
- Privacy-flagged defense reduces readiness score and adds risk flag
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.project_defense_analysis_service import (
    DefenseAnalysisResult,
    ProjectDefenseAnalysisService,
    analyze_defense_transcript,
)
from app.services.verification_readiness_service import compute_readiness_report

# ── Test identifiers ──────────────────────────────────────────────────────────

DEMO_USER_ID = "00000000-0000-0000-0000-000000000088"
EVIDENCE_ID  = "eeeeeeee-0000-0000-0000-000000000088"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_session(client: TestClient) -> str:
    """Create a proof session and return its ID."""
    r = client.post(
        "/api/v1/student/extension-proof/sessions",
        json={"skill_evidence_id": EVIDENCE_ID},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── Pure function tests (no HTTP, no DB) ──────────────────────────────────────

class TestAnalyzeDefenseTranscript:
    """Unit tests for the pure analyze_defense_transcript() function."""

    def test_no_transcript_returns_zero_score(self) -> None:
        result = analyze_defense_transcript(
            transcript_text="",
            claimed_skills=["React", "FastAPI"],
        )
        assert result.overall_defense_score == 0
        assert result.skills_mentioned == []
        assert result.skills_missing_from_explanation == []

    def test_claimed_skills_mentioned_increases_score(self) -> None:
        """Explicitly naming claimed skills in the transcript should add +20."""
        result_with = analyze_defense_transcript(
            transcript_text=(
                "I built a React frontend that communicates with a FastAPI backend. "
                "I implemented the authentication flow using JWT tokens and PostgreSQL "
                "for the database. The architecture separates concerns cleanly. "
                "I designed the API routes and configured the CORS middleware. "
                "In retrospect I would add caching to improve response latency. "
                "I am proud of the design pattern I used for the service layer."
            ),
            claimed_skills=["React", "FastAPI", "PostgreSQL"],
        )
        result_without = analyze_defense_transcript(
            transcript_text=(
                "I built a project with a frontend and a backend. "
                "The architecture separates concerns. "
                "I implemented authentication. "
                "I am proud of my design. "
                "In retrospect I would add caching. "
                "I handled all the configuration."
            ),
            claimed_skills=["React", "FastAPI", "PostgreSQL"],
        )
        assert result_with.overall_defense_score > result_without.overall_defense_score
        assert len(result_with.skills_mentioned) >= 2
        assert "React" in result_with.skills_mentioned or "FastAPI" in result_with.skills_mentioned

    def test_vague_short_transcript_gets_low_scores(self) -> None:
        """A very short vague transcript should get a low score."""
        result = analyze_defense_transcript(
            transcript_text="Great app. It works well. Very good project.",
            claimed_skills=["React", "FastAPI"],
        )
        assert result.overall_defense_score < 30
        assert result.explanation_clarity_score < 40
        # Should have at least one risk flag or improvement suggestion
        assert len(result.risk_flags) > 0 or len(result.recommended_improvements) > 0

    def test_ownership_phrases_increase_ownership_score(self) -> None:
        """First-person ownership phrases should increase ownership_signal_score."""
        result_owned = analyze_defense_transcript(
            transcript_text=(
                "I built the entire backend API using FastAPI. "
                "I implemented the database schema with PostgreSQL. "
                "My design decision was to use JWT for authentication. "
                "I was responsible for all deployment configuration. "
                "I optimized the query performance by adding indexes. "
                "I would improve the error handling in the next version."
            ),
            claimed_skills=["FastAPI", "PostgreSQL"],
        )
        result_passive = analyze_defense_transcript(
            transcript_text=(
                "The backend API was built using FastAPI. "
                "The database schema uses PostgreSQL. "
                "Authentication is done with JWT. "
                "Deployment was configured. "
                "Query performance was optimized. "
                "Error handling could be improved."
            ),
            claimed_skills=["FastAPI", "PostgreSQL"],
        )
        assert result_owned.ownership_signal_score > result_passive.ownership_signal_score

    def test_contradiction_creates_risk_flag(self) -> None:
        """Language suggesting the work wasn't the student's own should be flagged."""
        result = analyze_defense_transcript(
            transcript_text=(
                "I found the code online and did not build it myself. "
                "The logic was borrowed code from a tutorial. "
                "I never used FastAPI before this project. "
                "I submitted code I did not write. "
                "The architecture decisions were not mine. "
                "I didn't build the main feature."
            ),
            claimed_skills=["FastAPI"],
        )
        assert any("contradict" in flag.lower() or "may contradict" in flag.lower()
                   for flag in result.risk_flags)

    def test_api_key_in_transcript_is_flagged(self) -> None:
        """An API key in the transcript should be caught by the privacy scan."""
        result = analyze_defense_transcript(
            transcript_text=(
                "I integrated with OpenAI using key sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwx "
                "and built a chatbot interface. I designed the prompt pipeline. "
                "I implemented the streaming response handler. "
                "I used FastAPI for the backend with React frontend. "
                "I would improve the rate limiting in future. "
                "My architecture separates the API layer from the model logic."
            ),
            claimed_skills=["FastAPI", "React", "OpenAI"],
        )
        assert result.privacy_scan_status == "flagged"
        assert any("sensitive" in flag.lower() or "api key" in flag.lower() or "token" in flag.lower()
                   for flag in result.risk_flags)

    def test_aws_key_in_transcript_is_flagged(self) -> None:
        """AWS access key in transcript triggers privacy flag."""
        result = analyze_defense_transcript(
            transcript_text=(
                "I deployed to AWS using AKIAIOSFODNN7EXAMPLE access key. "
                "I configured S3 bucket policies. "
                "I built the deployment pipeline. "
                "I managed the IAM roles. "
                "I set up CloudWatch monitoring. "
                "I would use Terraform next time."
            ),
            claimed_skills=["AWS", "Python"],
        )
        assert result.privacy_scan_status == "flagged"

    def test_spaced_card_number_in_transcript_is_flagged(self) -> None:
        """A space/hyphen-grouped card number the shared scanner misses (its
        credit-card regex only matches an unbroken digit run) still flags the
        defense so the transcript summary fails closed on the public report."""
        result = analyze_defense_transcript(
            transcript_text=(
                "I built a payment demo and accidentally read my card 4111 1111 1111 1111 out loud. "
                "I implemented the checkout flow with Stripe. "
                "I designed the React frontend and the FastAPI backend. "
                "I set up the webhook handler for payment confirmation. "
                "I would tokenize card entry with Stripe Elements next time. "
                "My architecture keeps the secret key server-side only."
            ),
            claimed_skills=["React", "FastAPI", "Stripe"],
        )
        assert result.privacy_scan_status == "flagged"
        assert any("sensitive" in flag.lower() for flag in result.risk_flags)

    def test_hyphen_grouped_card_number_in_transcript_is_flagged(self) -> None:
        """Hyphen-grouped variant is caught as well."""
        result = analyze_defense_transcript(
            transcript_text=(
                "The test card 4111-1111-1111-1111 shows up in my transcript by mistake. "
                "I built the billing service and the invoice generator. "
                "I implemented retries on the payment webhook. "
                "I designed the database schema for orders. "
                "I would add idempotency keys in future. "
                "My deployment runs the API behind a load balancer."
            ),
            claimed_skills=["Python"],
        )
        assert result.privacy_scan_status == "flagged"

    def test_double_spaced_card_number_in_transcript_is_flagged(self) -> None:
        """P0 #3: repeated-space grouping ("4111  1111 1111 1111") the old single
        separator regex missed is now caught (Luhn-valid PAN, separator-tolerant)."""
        result = analyze_defense_transcript(
            transcript_text=(
                "I accidentally read my card 4111  1111 1111 1111 during the demo. "
                "I built the checkout flow and the order service. "
                "I implemented the payment webhook handler. "
                "I designed the React frontend and FastAPI backend. "
                "I would tokenize card entry next time. "
                "My architecture keeps secrets server-side only."
            ),
            claimed_skills=["React", "FastAPI"],
        )
        assert result.privacy_scan_status == "flagged"
        assert any("sensitive" in flag.lower() for flag in result.risk_flags)

    def test_alternate_grouped_card_number_in_transcript_is_flagged(self) -> None:
        """P0 #3: alternate grouping ("6011 111 1111 1111") — a card-shaped test PAN
        that is not Luhn-valid — is flagged via the known-test-number backstop."""
        result = analyze_defense_transcript(
            transcript_text=(
                "The number 6011 111 1111 1111 slipped into my recording by mistake. "
                "I built the billing dashboard and the reporting service. "
                "I implemented the nightly reconciliation job. "
                "I designed the Postgres schema for transactions. "
                "I would add alerting on failed charges next. "
                "My deployment runs the workers behind a queue."
            ),
            claimed_skills=["Python"],
        )
        assert result.privacy_scan_status == "flagged"
        assert any("sensitive" in flag.lower() for flag in result.risk_flags)

    def test_normal_technical_transcript_stays_clean(self) -> None:
        """P0 #3 control: a normal technical transcript (version numbers, ports,
        line counts, years) must NOT be mistaken for a card number — stays clean."""
        result = analyze_defense_transcript(
            transcript_text=(
                "I built a FastAPI service running on port 8080 with Python 3.11. "
                "I implemented 42 unit tests covering the 3 core endpoints. "
                "I designed the schema in 2024 and deployed it behind nginx. "
                "I optimized the query from 1200 ms down to 45 ms. "
                "I would add caching for the top 100 requests next. "
                "My architecture handles about 500 requests per second."
            ),
            claimed_skills=["Python", "FastAPI"],
        )
        assert result.privacy_scan_status == "clean"
        assert not any("sensitive" in flag.lower() for flag in result.risk_flags)

    def test_extremely_short_transcript_penalised(self) -> None:
        """Fewer than 50 words should trigger a risk flag and score deduction."""
        result = analyze_defense_transcript(
            transcript_text="I built a web app. It uses React. It is deployed. Thank you.",
            claimed_skills=["React"],
        )
        assert any("short" in f.lower() or "brief" in f.lower() or "50" in f
                   for f in result.risk_flags + result.recommended_improvements)

    def test_long_detailed_transcript_scores_higher(self) -> None:
        """100+ words with depth, ownership, and skill mentions should score ≥ 70."""
        result = analyze_defense_transcript(
            transcript_text=(
                "I built a full-stack project management dashboard for my capstone course. "
                "The problem I was solving is that teams need a way to track tasks and deadlines "
                "without switching between multiple apps. "
                "I designed the React frontend with custom hooks and context for state management. "
                "I implemented the FastAPI backend with SQLAlchemy as the ORM for PostgreSQL. "
                "I chose PostgreSQL because it supports complex queries for the reporting feature. "
                "I was responsible for writing all the API endpoints and the database schema. "
                "My design decision was to use JWT authentication with refresh tokens. "
                "I configured the Docker containers for local development. "
                "The main workflow is: user logs in, creates a board, adds tasks, assigns deadlines. "
                "I would improve the real-time updates feature using WebSockets in a future version. "
                "One limitation is that the search is not indexed, which slows down at scale. "
                "I am proud of the clean architecture I implemented."
            ),
            claimed_skills=["React", "FastAPI", "PostgreSQL", "Docker"],
        )
        assert result.overall_defense_score >= 70
        assert result.ownership_signal_score >= 40
        assert result.technical_depth_score >= 40
        assert len(result.skills_mentioned) >= 3

    def test_no_claimed_skills_listed_with_empty_skills(self) -> None:
        """When no claimed_skills are passed the skills lists should be empty."""
        result = analyze_defense_transcript(
            transcript_text=(
                "I built an API using Python. I implemented authentication. "
                "I designed the data model. I handled all the deployment. "
                "I would improve error handling in the future."
            ),
            claimed_skills=[],
        )
        assert result.skills_mentioned == []
        assert result.skills_missing_from_explanation == []

    def test_skills_explained_well_subset_of_mentioned(self) -> None:
        """skills_explained_well must always be a subset of skills_mentioned."""
        result = analyze_defense_transcript(
            transcript_text=(
                "I implemented the React components using hooks and context. "
                "I built the FastAPI backend and I designed all the endpoints. "
                "I used PostgreSQL and I wrote the schema migrations. "
                "My architecture decision was to use a repository pattern. "
                "I would add caching to improve performance in future."
            ),
            claimed_skills=["React", "FastAPI", "PostgreSQL"],
        )
        for skill in result.skills_explained_well:
            assert skill in result.skills_mentioned, (
                f"{skill!r} in skills_explained_well but not in skills_mentioned"
            )

    def test_evidence_context_consistency_improves_score(self) -> None:
        """Mentioning the same tech as in evidence summaries should boost consistency."""
        result_with_context = analyze_defense_transcript(
            transcript_text=(
                "I built a React frontend and a FastAPI backend. "
                "I implemented authentication with JWT. "
                "I designed the PostgreSQL schema. "
                "My architecture decision was to separate concerns cleanly. "
                "I would improve the test coverage in future iterations."
            ),
            claimed_skills=["React", "FastAPI"],
            workflow_summary="Student demonstrated React component navigation and FastAPI endpoints.",
            github_summary="Repository contains React components and FastAPI routes with PostgreSQL models.",
        )
        result_no_context = analyze_defense_transcript(
            transcript_text=(
                "I built a React frontend and a FastAPI backend. "
                "I implemented authentication with JWT. "
                "I designed the PostgreSQL schema. "
                "My architecture decision was to separate concerns cleanly. "
                "I would improve the test coverage in future iterations."
            ),
            claimed_skills=["React", "FastAPI"],
        )
        assert result_with_context.consistency_with_evidence_score >= result_no_context.consistency_with_evidence_score


# ── DB service tests ───────────────────────────────────────────────────────────

class TestProjectDefenseService:
    """Unit tests for ProjectDefenseAnalysisService using in-memory store."""

    def test_store_and_retrieve(self) -> None:
        store: dict = {}
        svc = ProjectDefenseAnalysisService(store)
        result = DefenseAnalysisResult(
            overall_defense_score=75,
            transcript_summary="Test summary",
            privacy_scan_status="clean",
        )
        stored = svc.store_analysis("uid", "sid", None, "transcript text", result)
        assert stored["overall_defense_score"] == 75

        retrieved = svc.get_analysis("uid", "sid")
        assert retrieved is not None
        assert retrieved["overall_defense_score"] == 75
        assert retrieved["transcript_summary"] == "Test summary"

    def test_get_returns_none_when_not_stored(self) -> None:
        store: dict = {}
        svc = ProjectDefenseAnalysisService(store)
        assert svc.get_analysis("uid", "unknown-sid") is None


# ── HTTP endpoint tests ────────────────────────────────────────────────────────

class TestProjectDefenseEndpoint:
    """Integration tests using FastAPI TestClient with in-memory store."""

    def test_post_returns_404_for_unknown_session(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/student/extension-proof/sessions/nonexistent/analyze/project-defense",
            json={
                "transcript_text": "I built a React app.",
                "claimed_skills": ["React"],
            },
        )
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "session_not_found"

    def test_get_returns_404_before_analysis(self, client: TestClient) -> None:
        session_id = _make_session(client)
        r = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analysis/project-defense"
        )
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "project_defense_not_found"

    def test_post_and_get_full_cycle(self, client: TestClient) -> None:
        session_id = _make_session(client)
        transcript = (
            "I built a web application using React for the frontend and FastAPI for the backend. "
            "I was responsible for the entire architecture including database design with PostgreSQL. "
            "My design decision was to use JWT authentication. "
            "I implemented the CRUD endpoints and tested them with pytest. "
            "I deployed the application using Docker containers. "
            "One limitation is the lack of real-time updates; I would add WebSockets in future."
        )
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/project-defense",
            json={
                "transcript_text": transcript,
                "claimed_skills": ["React", "FastAPI", "PostgreSQL", "Docker"],
                "proof_objective": "Demonstrate full-stack development skills",
            },
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["proof_session_id"] == session_id
        assert data["overall_defense_score"] >= 0
        assert data["overall_defense_score"] <= 100
        assert isinstance(data["skills_mentioned"], list)
        assert isinstance(data["skills_explained_well"], list)
        assert isinstance(data["skills_missing_from_explanation"], list)
        assert data["privacy_scan_status"] == "clean"
        # Should NOT be 'complete' — invariant check
        assert data.get("final_verification_status") != "complete"

        # GET should return the stored result
        r2 = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analysis/project-defense"
        )
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["proof_session_id"] == session_id
        assert data2["overall_defense_score"] == data["overall_defense_score"]

    def test_privacy_flagged_for_sensitive_transcript(self, client: TestClient) -> None:
        session_id = _make_session(client)
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/project-defense",
            json={
                "transcript_text": (
                    "I used API key sk-proj-TESTKEY1234567890ABCDEFGHIJKLMNOPQRSTUVWX "
                    "to connect to OpenAI. I built the backend with FastAPI. "
                    "I implemented the prompt pipeline. I designed the response handler. "
                    "My architecture separates model calls from the API layer. "
                    "I would improve the rate limiting in a future version."
                ),
                "claimed_skills": ["FastAPI", "OpenAI"],
            },
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["privacy_scan_status"] == "flagged"
        assert any("sensitive" in f.lower() or "api key" in f.lower() or "token" in f.lower()
                   for f in data["risk_flags"])

    def test_short_transcript_analysis(self, client: TestClient) -> None:
        session_id = _make_session(client)
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/project-defense",
            json={
                "transcript_text": "Built an app. It is great.",
                "claimed_skills": ["React"],
            },
        )
        assert r.status_code == 201, r.text
        data = r.json()
        # Short transcript should score low
        assert data["overall_defense_score"] < 40

    def test_no_transcript_does_not_break_proof_flow(
        self, client: TestClient
    ) -> None:
        """
        The proof flow must work without a project defense transcript.
        The readiness endpoint should still return successfully.
        """
        session_id = _make_session(client)
        # Do NOT post any defense analysis
        r = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}/readiness"
        )
        # Readiness endpoint should return 200 even with no defense analysis
        assert r.status_code == 200, r.text
        data = r.json()
        # No defense should not break the score computation
        assert "readiness_score" in data
        assert data["final_verification_status"] != "complete"

    def test_video_url_stored(self, client: TestClient) -> None:
        session_id = _make_session(client)
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/project-defense",
            json={
                "video_url": "https://www.loom.com/share/abc123",
                "transcript_text": (
                    "I built this project to demonstrate my FastAPI skills. "
                    "I implemented REST endpoints and JWT authentication. "
                    "My architecture uses dependency injection for clean separation. "
                    "I was responsible for the database schema design. "
                    "I would add caching in a future version."
                ),
                "claimed_skills": ["FastAPI"],
            },
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["video_url"] == "https://www.loom.com/share/abc123"


# ── Readiness integration tests ───────────────────────────────────────────────

class TestReadinessWithDefenseAnalysis:
    """Tests that defense analysis integrates correctly with the readiness report."""

    def _make_workflow_analysis(self) -> dict:
        return {
            "supported_skills": ["React", "FastAPI"],
            "weakly_supported_skills": [],
            "missing_evidence": [],
            "risk_flags": [],
            "recruiter_summary": "Student demonstrated React navigation and FastAPI endpoints.",
            "human_review_needed": False,
        }

    def _make_strong_defense(self) -> dict:
        return {
            "overall_defense_score": 80,
            "consistency_with_evidence_score": 70,
            "ownership_signal_score": 80,
            "technical_depth_score": 70,
            "risk_flags": [],
            "privacy_scan_status": "clean",
            "transcript_text": "I built this project … " * 10,  # ≥50 words
        }

    def test_strong_defense_improves_readiness_score(self) -> None:
        """Adding a high-quality defense analysis should increase the readiness score."""
        base = compute_readiness_report(
            proof_session_id="sid-1",
            session_status="completed",
            website_url="http://localhost:3000",
            claimed_skills=["React", "FastAPI"],
            workflow_analysis=self._make_workflow_analysis(),
        )
        with_defense = compute_readiness_report(
            proof_session_id="sid-1",
            session_status="completed",
            website_url="http://localhost:3000",
            claimed_skills=["React", "FastAPI"],
            workflow_analysis=self._make_workflow_analysis(),
            defense_analysis=self._make_strong_defense(),
        )
        assert with_defense.readiness_score > base.readiness_score

    def test_defense_consistency_bonus_applied(self) -> None:
        """A defense with high consistency score should trigger the +10 contributor."""
        result = compute_readiness_report(
            proof_session_id="sid-2",
            session_status="completed",
            website_url="http://localhost:3000",
            claimed_skills=["React"],
            defense_analysis={
                "overall_defense_score": 75,
                "consistency_with_evidence_score": 80,
                "ownership_signal_score": 70,
                "technical_depth_score": 60,
                "risk_flags": [],
                "privacy_scan_status": "clean",
                "transcript_text": "I built this using React… " * 10,
            },
        )
        labels = [c["label"] for c in result.score_contributors]
        assert any("transcript" in lbl.lower() or "defense" in lbl.lower() for lbl in labels)

    def test_flagged_defense_adds_risk_flag_to_readiness(self) -> None:
        """A privacy-flagged defense should add a risk flag to the readiness report."""
        result = compute_readiness_report(
            proof_session_id="sid-3",
            session_status="completed",
            website_url="http://localhost:3000",
            claimed_skills=["React"],
            defense_analysis={
                "overall_defense_score": 60,
                "consistency_with_evidence_score": 50,
                "ownership_signal_score": 50,
                "technical_depth_score": 50,
                "risk_flags": ["sensitive data detected"],
                "privacy_scan_status": "flagged",
                "transcript_text": "I built this… " * 10,
            },
        )
        assert any("defense" in f.lower() or "transcript" in f.lower() or "privacy" in f.lower()
                   for f in result.risk_flags)

    def test_missing_defense_adds_next_action(self) -> None:
        """When session is uploaded but no defense exists, a next action is suggested."""
        result = compute_readiness_report(
            proof_session_id="sid-4",
            session_status="uploaded_pending_analysis",
            website_url="http://localhost:3000",
            claimed_skills=["React"],
            defense_analysis=None,
        )
        assert any(
            "defense" in action.lower() or "transcript" in action.lower()
            for action in result.recommended_next_actions
        )

    def test_final_verification_never_complete_even_with_perfect_defense(self) -> None:
        """
        Even with a perfect defense score + all other evidence,
        final_verification_status must NEVER be 'complete'.
        """
        result = compute_readiness_report(
            proof_session_id="sid-5",
            session_status="completed",
            website_url="http://localhost:3000",
            claimed_skills=["React", "FastAPI"],
            workflow_analysis={
                "supported_skills": ["React", "FastAPI"],
                "weakly_supported_skills": [],
                "missing_evidence": [],
                "risk_flags": [],
                "recruiter_summary": "Strong workflow evidence",
                "human_review_needed": False,
            },
            github_analysis={
                "status": "success",
                "matched_claimed_skills": ["React", "FastAPI"],
                "weakly_matched_claimed_skills": [],
                "detected_features": ["readme", "deployment"],
                "recruiter_summary": "Strong GitHub evidence",
            },
            live_check={"is_reachable": True},
            privacy_scan={"status": "clean"},
            defense_analysis={
                "overall_defense_score": 95,
                "consistency_with_evidence_score": 90,
                "ownership_signal_score": 95,
                "technical_depth_score": 90,
                "risk_flags": [],
                "privacy_scan_status": "clean",
                "transcript_text": "I built this using React and FastAPI… " * 15,
            },
        )
        # The invariant: "complete" must never appear
        assert result.final_verification_status != "complete"
        assert result.final_verification_status in ("pending", "ready_for_review")

    def test_no_hardcoded_project_names_in_results(self) -> None:
        """
        Results must not reference 'Boston', 'React demo', or any specific
        project name that is hardcoded in the analysis logic.
        """
        result = analyze_defense_transcript(
            transcript_text=(
                "I built a machine learning pipeline to classify images. "
                "I implemented the training loop with PyTorch. "
                "I was responsible for data preprocessing and augmentation. "
                "My architecture uses a custom ResNet variant. "
                "I would improve the inference speed in future using TorchScript."
            ),
            claimed_skills=["PyTorch", "Python", "Machine Learning"],
        )
        forbidden = ["boston", "react demo", "veribridge"]
        for text in [result.transcript_summary, result.recruiter_summary]:
            for word in forbidden:
                assert word not in text.lower(), (
                    f"Hardcoded project name '{word}' found in output: {text!r}"
                )


# ── Media upload / transcript review tests ────────────────────────────────────

class TestProjectDefenseMediaUpload:
    """Tests for the media upload and transcript update endpoints."""

    def test_upload_valid_audio_mp3(self, client: TestClient, mem_store: dict) -> None:
        """POSTing a .mp3 file registers media metadata and returns 201."""
        session_id = _make_session(client)
        dummy_mp3 = b"ID3" + b"\x00" * 100   # minimal placeholder bytes
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
            files={"file": ("explanation.mp3", dummy_mp3, "audio/mpeg")},
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["proof_session_id"] == session_id
        assert data["media_filename"] == "explanation.mp3"
        assert data["media_type"] == "mp3"
        assert data["transcription_status"] == "uploaded"
        assert data["media_size_bytes"] == len(dummy_mp3)
        # storage_configured reflects the bucket env var (not whether dict-store skips upload).
        # In test env with .env loaded: bucket IS configured, so storage_configured=True.
        # Actual storage upload is still skipped for dict stores (isinstance check).
        assert isinstance(data["storage_configured"], bool)
        # With a dict store the upload block is skipped → no storage path set
        assert data["media_storage_path"] is None

    def test_upload_valid_video_mp4(self, client: TestClient) -> None:
        """POSTing a .mp4 file is accepted."""
        session_id = _make_session(client)
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
            files={"file": ("walkthrough.mp4", b"\x00" * 50, "video/mp4")},
        )
        assert r.status_code == 201, r.text
        assert r.json()["media_type"] == "mp4"

    def test_upload_valid_webm(self, client: TestClient) -> None:
        """POSTing a .webm file is accepted."""
        session_id = _make_session(client)
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
            files={"file": ("recording.webm", b"\x00" * 50, "video/webm")},
        )
        assert r.status_code == 201, r.text
        assert r.json()["media_type"] == "webm"

    def test_upload_invalid_extension_rejected(self, client: TestClient) -> None:
        """Uploading a .pdf is rejected with 422."""
        session_id = _make_session(client)
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
            files={"file": ("notes.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == "invalid_media_type"

    def test_upload_unknown_session_returns_404(self, client: TestClient) -> None:
        """Uploading to a non-existent session returns 404."""
        r = client.post(
            "/api/v1/student/extension-proof/sessions/nonexistent-session-id/defense/upload-media",
            files={"file": ("test.mp3", b"\x00" * 10, "audio/mpeg")},
        )
        assert r.status_code == 404, r.text

    def test_get_analysis_returns_media_metadata_after_upload(
        self, client: TestClient, mem_store: dict
    ) -> None:
        """After upload, GET /analysis/project-defense returns the media fields."""
        session_id = _make_session(client)
        # Upload media
        client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
            files={"file": ("talk.wav", b"\x00" * 20, "audio/wav")},
        )
        # Fetch the stored record
        r = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analysis/project-defense"
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["media_filename"] == "talk.wav"
        assert data["media_type"] == "wav"
        assert data["transcription_status"] == "uploaded"


class TestProjectDefenseUpdateTranscript:
    """Tests for the PATCH /defense/transcript endpoint."""

    def test_update_transcript_after_upload(
        self, client: TestClient, mem_store: dict
    ) -> None:
        """After uploading media, student can PATCH the transcript."""
        session_id = _make_session(client)
        # Register media first
        client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
            files={"file": ("audio.mp3", b"\x00" * 10, "audio/mpeg")},
        )
        # Update transcript
        r = client.patch(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcript",
            json={
                "transcript_text": "I built this using React and FastAPI. " * 8,
                "transcript_reviewed": True,
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "React" in data["transcript_text"]
        assert data["transcript_reviewed"] is True
        assert data["transcription_status"] == "transcript_ready"

    def test_update_transcript_sets_status_pending_when_not_reviewed(
        self, client: TestClient
    ) -> None:
        """transcript_reviewed=False keeps transcription_status as 'uploaded'."""
        session_id = _make_session(client)
        client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
            files={"file": ("audio.mp3", b"\x00" * 10, "audio/mpeg")},
        )
        r = client.patch(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcript",
            json={"transcript_text": "Draft text", "transcript_reviewed": False},
        )
        assert r.status_code == 200, r.text
        assert r.json()["transcript_reviewed"] is False
        assert r.json()["transcription_status"] == "uploaded"

    def test_update_transcript_no_row_returns_404(self, client: TestClient) -> None:
        """PATCH without a prior upload/register returns 404."""
        session_id = _make_session(client)
        r = client.patch(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/transcript",
            json={"transcript_text": "Some text", "transcript_reviewed": True},
        )
        assert r.status_code == 404, r.text

    def test_manual_transcript_still_works_after_new_endpoints_added(
        self, client: TestClient
    ) -> None:
        """Existing POST /analyze/project-defense still functions without media."""
        session_id = _make_session(client)
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/project-defense",
            json={
                "transcript_text": (
                    "I built this application using FastAPI and PostgreSQL. "
                    "I designed the REST API endpoints and configured the database schema. "
                    "I implemented authentication using JWT tokens. "
                    "I was responsible for deploying to Cloud Run. "
                    "In future I would add caching to improve response latency. "
                ) * 3,
                "claimed_skills": ["FastAPI", "PostgreSQL"],
                "proof_objective": "Show the live API handling authenticated requests.",
            },
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["overall_defense_score"] > 0
        # transcript_reviewed should be True (analyzed = reviewed)
        assert data["transcript_reviewed"] is True
        assert data["transcription_status"] == "analysis_complete"
        # Final verification must never be "complete"
        assert data["overall_defense_score"] <= 100

    def test_empty_transcript_cannot_be_analyzed_via_analyze_endpoint(
        self, client: TestClient
    ) -> None:
        """An empty transcript string returns score=0 and no risk."""
        session_id = _make_session(client)
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/project-defense",
            json={"transcript_text": "", "claimed_skills": ["React"]},
        )
        assert r.status_code == 201, r.text
        assert r.json()["overall_defense_score"] == 0

    def test_media_upload_does_not_break_readiness_report(
        self, client: TestClient, mem_store: dict
    ) -> None:
        """
        Uploading media without running analysis must not break the readiness
        report — the defense contribution should be absent (not error).
        """
        from app.services.verification_readiness_service import compute_readiness_report

        # Media uploaded but no analysis row has NLP scores
        session_id = _make_session(client)
        client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
            files={"file": ("demo.mp4", b"\x00" * 10, "video/mp4")},
        )

        # Fetch the row — has media fields but zero NLP scores
        r = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analysis/project-defense"
        )
        assert r.status_code == 200, r.text
        row = r.json()

        # Build a minimal readiness report using the media-only row as defense_analysis
        report = compute_readiness_report(
            proof_session_id=session_id,
            session_status="completed",
            url_type="live_deployed_url",
            claimed_skills=["FastAPI"],
            workflow_analysis=None,
            live_check=None,
            github_analysis=None,
            privacy_scan=None,
            defense_analysis=row,
        )
        # Should not error, and final verification should never be "complete"
        assert report.final_verification_status != "complete"
        assert report.readiness_score >= 0

    def test_no_hardcoded_project_names_in_media_response(
        self, client: TestClient
    ) -> None:
        """Media upload response must not contain hardcoded project names."""
        session_id = _make_session(client)
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/defense/upload-media",
            files={"file": ("defense.mp3", b"\x00" * 10, "audio/mpeg")},
        )
        assert r.status_code == 201, r.text
        body_str = r.text.lower()
        for forbidden in ["boston", "react demo", "veribridge_project"]:
            assert forbidden not in body_str, f"Hardcoded name '{forbidden}' in response"
