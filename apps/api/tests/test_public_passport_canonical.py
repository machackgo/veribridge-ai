"""Canonical public Work Passport data-integrity tests (production-correction pass).

Covers the recruiter-trust requirements:

  1. The public passport returns EVERY published project (no hidden drops).
  2. Featured projects are ranked deterministically (proof coverage → skill
     strength → recency → title), never randomly.
  3. The public skill list is uncapped — every evidence-backed skill survives.
  4. Skill aliases are normalized (canonical name) WITHOUT losing evidence:
     the merged entry unions projects/sources and records its aliases.
  5. Every public skill carries a stable slug + high-level taxonomy category.
  6. Featured-project GitHub links are truth-gated: present only when a GitHub
     Proof is attached AND the repo is recorded public AND the URL is safe.
  7. The public report never surfaces a repository identity that no GitHub
     Proof backs (the "report says GitHub but nothing opens" trust failure).

All storage is in-memory (dict mode). No network / LLM calls.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.services.vbr_work_passport_service import (
    _aggregate_skills_with_detail,
    _public_project_links,
    _rank_public_projects,
    _to_public_skill,
)

from tests.test_vbr_project_defense import (
    USER_ID,
    _create_project_defense,
    _seed_github_proof,
)
from tests.test_vbr_work_passport import (  # reuse the shared fixtures/helpers
    _get_public,
    _publish,
    _publish_project_report,
)


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def pipeline_db() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict, pipeline_db: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: pipeline_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_simple_project(client: TestClient, title: str, repo: str) -> str:
    created = _create_project_defense(
        client,
        title=title,
        repo_url=repo,
        claimed_skills=["Python"],
    ).json()
    return created["project"]["id"]


# ── 1. Every published project appears ───────────────────────────────────────


def test_public_passport_returns_all_published_projects(client: TestClient, mem_store: dict) -> None:
    ids = [
        _make_simple_project(client, f"Distinct Project {i}", f"https://github.com/octocat/repo-{i}")
        for i in range(4)
    ]
    for pid in ids:
        _publish_project_report(client, pid)
    slug = _publish(client).json()["public_slug"]

    app.dependency_overrides.pop(get_current_user_id, None)
    body = _get_public(client, slug).json()
    assert body["featured_project_count"] == 4
    titles = {p["project_title"] for p in body["featured_projects"]}
    assert titles == {f"Distinct Project {i}" for i in range(4)}
    # Every card links to a live public report path.
    for proj in body["featured_projects"]:
        assert proj["public_report_path"].startswith("/vbr/report/")


# ── 2. Deterministic ranking ─────────────────────────────────────────────────


def _summary(title: str, attached: int, statuses: list[str], published_at: str) -> dict:
    return {
        "project_title": title,
        "proof_chain": {"attached_count": attached},
        "top_skills": [{"status": s} for s in statuses],
        "published_at": published_at,
    }


def test_rank_public_projects_is_deterministic_and_evidence_first() -> None:
    weak = _summary("Weak", 1, ["Supporting evidence"], "2026-01-03T00:00:00Z")
    strong = _summary("Strong", 5, ["Demonstrated", "Demonstrated"], "2026-01-01T00:00:00Z")
    mid_newer = _summary("Mid Newer", 3, ["Partially demonstrated"], "2026-02-01T00:00:00Z")
    mid_older = _summary("Mid Older", 3, ["Partially demonstrated"], "2026-01-01T00:00:00Z")

    ordered = [weak, mid_older, strong, mid_newer]
    _rank_public_projects(ordered)
    assert [s["project_title"] for s in ordered] == ["Strong", "Mid Newer", "Mid Older", "Weak"]

    # Same input, any starting order → identical result (determinism).
    reordered = [strong, mid_newer, weak, mid_older]
    _rank_public_projects(reordered)
    assert [s["project_title"] for s in reordered] == ["Strong", "Mid Newer", "Mid Older", "Weak"]


# ── 3–5. Uncapped, alias-normalized, categorized skills ──────────────────────


def _skill_row(skill: str, status: str = "Supporting evidence") -> dict:
    return {"skill": skill, "status": status, "evidence_chip_count": 0, "supporting_sources": []}


def _card(title: str, path: str, skills: list[dict]) -> tuple[dict, dict]:
    summary = {
        "project_title": title,
        "evidence_sources": ["Document Proof"],
        "public_report_path": path,
    }
    report = {"project_title": title, "skill_evidence": skills, "evidence_traces": []}
    return summary, report


def test_public_skills_are_uncapped_alias_merged_and_categorized() -> None:
    many = [_skill_row(f"Skill Number {i}") for i in range(18)]
    card_a = _card("Alpha", "/vbr/report/tok-a", [*many, _skill_row("APIs", "Partially demonstrated")])
    card_b = _card("Beta", "/vbr/report/tok-b", [_skill_row("API Development"), _skill_row("apis")])

    aggregated = _aggregate_skills_with_detail([card_a, card_b], public=True)
    public = [_to_public_skill(s) for s in aggregated]

    # Uncapped: 18 distinct + 1 merged canonical "API Development" = 19 (> the old 16 cap).
    names = [s["skill"] for s in public]
    assert len(names) == 19
    assert names.count("API Development") == 1
    assert "APIs" not in names and "apis" not in names

    merged = next(s for s in public if s["skill"] == "API Development")
    # Evidence UNIONED across aliases: both projects support the merged skill.
    assert {p["project_title"] for p in merged["projects"]} == {"Alpha", "Beta"}
    # Best qualitative label across aliases survives the merge.
    assert merged["status"] == "Partially demonstrated"
    # Aliases recorded for traceability; slug + category are stable/canonical.
    assert "APIs" in merged["aliases"]
    assert merged["skill_slug"] == "api-development"
    assert merged["category"] == "Backend / APIs"

    for skill in public:
        assert skill["skill_slug"]
        assert skill["category"]


# ── 6. Truth-gated featured-project links ────────────────────────────────────


def test_public_project_links_truth_gate() -> None:
    public_repo = {
        "github_proof": {
            "repo_url": "https://github.com/octocat/Hello-World",
            "repo_owner": "octocat",
            "repo_name": "Hello-World",
            "repo_is_public": True,
        },
        "deployed_url": "https://demo.example.com",
        "website_proofs": [],
    }
    links = _public_project_links(public_repo)
    assert links["github_repo_url"] == "https://github.com/octocat/Hello-World"
    assert links["github_repo_label"] == "octocat/Hello-World"
    assert links["live_url"] == "https://demo.example.com"

    # Private repo → no GitHub link, even though a proof is attached.
    private_repo = {
        "github_proof": {
            "repo_url": "https://github.com/octocat/secret",
            "repo_is_public": False,
        },
        "website_proofs": [],
    }
    assert _public_project_links(private_repo)["github_repo_url"] is None

    # Unsafe URL → no GitHub link even when flagged public.
    unsafe = {
        "github_proof": {"repo_url": "http://localhost:3000/repo", "repo_is_public": True},
        "website_proofs": [],
    }
    assert _public_project_links(unsafe)["github_repo_url"] is None

    # No GitHub Proof at all → no GitHub link (never inferred from repo_url).
    none_attached = {"github_proof": None, "website_proofs": []}
    assert _public_project_links(none_attached)["github_repo_url"] is None

    # Live URL falls back to the first SAFE website-proof target.
    website_fallback = {
        "github_proof": None,
        "deployed_url": None,
        "website_proofs": [
            {"target_website": "http://192.168.1.5/internal"},
            {"target_website": "https://app.example.com"},
        ],
    }
    assert _public_project_links(website_fallback)["live_url"] == "https://app.example.com"


def test_public_passport_card_github_link_matches_report_truth(
    client: TestClient, mem_store: dict
) -> None:
    # Project WITH an attached public GitHub proof → card carries the repo link.
    github_proof_id = _seed_github_proof(mem_store)
    with_gh = _create_project_defense(
        client,
        title="With GitHub",
        repo_url="https://github.com/octocat/Hello-World",
        attached_proofs={"github_proof_id": github_proof_id},
    ).json()["project"]["id"]
    # Project WITHOUT any GitHub proof → no GitHub link, ever.
    without_gh = _make_simple_project(
        client, "Without GitHub", "https://github.com/octocat/other-repo"
    )
    _publish_project_report(client, with_gh)
    _publish_project_report(client, without_gh)
    slug = _publish(client).json()["public_slug"]

    app.dependency_overrides.pop(get_current_user_id, None)
    body = _get_public(client, slug).json()
    by_title = {p["project_title"]: p for p in body["featured_projects"]}

    gh_card = by_title["With GitHub"]
    assert gh_card["github_repo_url"] == "https://github.com/octocat/Hello-World"
    assert "GitHub Proof" in gh_card["evidence_sources"]

    plain_card = by_title["Without GitHub"]
    assert plain_card["github_repo_url"] is None
    assert "GitHub Proof" not in plain_card["evidence_sources"]


# ── 7. Public report never implies an unbacked repository ────────────────────


def test_public_report_hides_repo_identity_without_github_proof(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _make_simple_project(
        client, "No GitHub Here", "https://github.com/octocat/private-thing"
    )
    token = _publish_project_report(client, project_id).json()["public_token"]
    _publish(client)  # report links resolve only while the Passport is Public

    app.dependency_overrides.pop(get_current_user_id, None)
    res = client.get(f"/api/v1/public/vbr/reports/{token}")
    assert res.status_code == 200
    body = res.json()
    # No GitHub Proof → no repository identity anywhere in the public report.
    assert body["github_proof"] is None
    assert body["repo_full_name"] is None
    assert body["evidence_package"]["github_proof_attached"] is False


def test_public_report_keeps_repo_identity_with_github_proof(
    client: TestClient, mem_store: dict
) -> None:
    github_proof_id = _seed_github_proof(mem_store)
    project_id = _create_project_defense(
        client,
        title="GitHub Backed",
        repo_url="https://github.com/octocat/Hello-World",
        attached_proofs={"github_proof_id": github_proof_id},
    ).json()["project"]["id"]
    token = _publish_project_report(client, project_id).json()["public_token"]
    _publish(client)  # report links resolve only while the Passport is Public

    app.dependency_overrides.pop(get_current_user_id, None)
    res = client.get(f"/api/v1/public/vbr/reports/{token}")
    assert res.status_code == 200
    body = res.json()
    assert body["github_proof"] is not None
    assert body["github_proof"]["repo_url"] == "https://github.com/octocat/Hello-World"
    assert body["repo_full_name"]
