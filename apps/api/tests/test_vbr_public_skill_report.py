"""Tests for the public recruiter-safe Skill Report.

Public (no auth):
  ``GET /api/v1/public/p/{public_slug}/skills/{skill}``

Covers:
  - resolves only for an actively PUBLISHED passport (unknown / unpublished 404)
  - a skill with no proof for the candidate 404s (no page enumeration)
  - accepts both the canonical skill name and the URL slug
  - the payload is the centralized public projection: no private ids, storage
    paths, owner routes, snippets/excerpts, or numeric scores
  - every served linked chain / evidence member / synthesis result is
    explicitly ``public_safe``

All storage is in-memory (dict mode). No network / LLM calls — the public
route builds the report with the deterministic-only synthesis pass.
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app

from tests.test_vbr_work_passport import (
    _make_full_project,
    _publish,
    _publish_project_report,
    _unpublish,
)
from tests.test_vbr_project_defense import USER_ID, _seed_github_proof


# ── Fixtures ──────────────────────────────────────────────────────────────────

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


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_public_skill_report(client: TestClient, slug: str, skill: str):
    return client.get(f"/api/v1/public/p/{slug}/skills/{skill}")


def _published_passport_with_skill(client: TestClient, mem_store: dict) -> tuple[str, str]:
    """Create a full project, publish its report + the passport.

    Returns ``(public_slug, first_public_skill_name)`` — the skill is taken from
    the public passport itself so the test never assumes a specific label.
    """
    project_id = _make_full_project(client, mem_store)
    assert _publish_project_report(client, project_id).status_code in (200, 201)
    slug = _publish(client).json()["public_slug"]

    passport = client.get(f"/api/v1/public/p/{slug}").json()
    skills = [s["skill"] for s in passport["top_skills"]]
    assert skills, "expected at least one public skill on the published passport"
    return slug, skills[0]


def _slugify(skill: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", skill.lower()).strip("-")


# ── Resolution / fail-closed 404s ─────────────────────────────────────────────

def test_public_skill_report_resolves_for_published_passport(
    client: TestClient, mem_store: dict
) -> None:
    slug, skill = _published_passport_with_skill(client, mem_store)

    res = _get_public_skill_report(client, slug, skill)
    assert res.status_code == 200
    body = res.json()

    assert body["skill"]
    assert body["skill_slug"] == _slugify(body["skill"])
    # Closed qualitative label — never a numeric score.
    assert body["status"] in {
        "Demonstrated",
        "Partially demonstrated",
        "Evidence observed",
        "Supporting evidence",
        "Needs review",
        "Not assessed",
    }
    # Boolean coverage only.
    assert all(isinstance(v, bool) for v in body["source_coverage"].values())
    assert isinstance(body["linked_proof_chains"], list)
    assert isinstance(body["synthesis"], list)
    assert isinstance(body["limitations"], list)


def test_public_skill_report_accepts_slug_and_name(client: TestClient, mem_store: dict) -> None:
    slug, skill = _published_passport_with_skill(client, mem_store)

    by_name = _get_public_skill_report(client, slug, skill)
    by_slug = _get_public_skill_report(client, slug, _slugify(skill))
    assert by_name.status_code == 200
    assert by_slug.status_code == 200
    assert by_name.json()["skill"] == by_slug.json()["skill"]


def test_public_skill_report_404_unknown_slug(client: TestClient) -> None:
    res = _get_public_skill_report(client, "nope-nope", "python")
    assert res.status_code == 404
    # Generic fail-closed error — no holder data, no reason detail.
    assert res.json()["detail"]["code"] == "vbr_work_passport_not_found"


def test_public_skill_report_404_when_passport_unpublished(
    client: TestClient, mem_store: dict
) -> None:
    slug, skill = _published_passport_with_skill(client, mem_store)
    assert _get_public_skill_report(client, slug, skill).status_code == 200

    _unpublish(client)
    res = _get_public_skill_report(client, slug, skill)
    assert res.status_code == 404


def test_public_skill_report_404_for_skill_with_no_proof(
    client: TestClient, mem_store: dict
) -> None:
    slug, _ = _published_passport_with_skill(client, mem_store)
    res = _get_public_skill_report(client, slug, "quantum-basket-weaving")
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "vbr_work_passport_not_found"


# ── Public-safety guarantees ──────────────────────────────────────────────────

def test_public_skill_report_contains_no_private_fields(
    client: TestClient, mem_store: dict
) -> None:
    slug, skill = _published_passport_with_skill(client, mem_store)
    body = _get_public_skill_report(client, slug, skill).json()
    raw = json.dumps(body)

    # The owner's auth user id (and any internal id) never rides out.
    assert USER_ID not in raw

    # No private KEY may exist anywhere in the payload (keys, not prose — a safe
    # sentence may legitimately contain a word like "metadata").
    def _keys(value, out):
        if isinstance(value, dict):
            for k, v in value.items():
                out.add(str(k))
                _keys(v, out)
        elif isinstance(value, list):
            for v in value:
                _keys(v, out)
        return out

    keys = _keys(body, set())
    for unsafe_key in (
        "source_id",
        "storage_path",
        "signed_url",
        "artifact_data",
        "metadata",
        "answer_excerpt",
        "safe_snippet",
        "code_snippet",
        "raw_payload",
    ):
        assert unsafe_key not in keys, f"public skill report leaked key {unsafe_key!r}"

    # No path-like / token-like fragment in any string value.
    for unsafe in ("uploads/", "/student/vbr", "/Users/", "access_token", "?token="):
        assert unsafe not in raw, f"public skill report leaked {unsafe!r}"

    # No numeric-score wording anywhere in the public payload.
    assert not re.search(r"\b\d{1,3}\s*/\s*100\b", raw)
    assert not re.search(r"\btrust score\b", raw, re.IGNORECASE)
    assert not re.search(r"\bfully verified\b", raw, re.IGNORECASE)


def test_public_skill_report_serves_only_public_safe_members(
    client: TestClient, mem_store: dict
) -> None:
    slug, skill = _published_passport_with_skill(client, mem_store)
    body = _get_public_skill_report(client, slug, skill).json()

    for chain in body["linked_proof_chains"]:
        assert chain["public_safe"] is True
        for member in chain.get("evidence", []):
            assert member["public_safe"] is True
            # Any outbound link must be a plain public http(s) URL.
            url = member.get("public_url")
            assert url is None or url.startswith("https://") or url.startswith("http://")
    for result in body["synthesis"]:
        assert result["public_safe"] is True
        for claim in result.get("claims", []):
            # A public claim always keeps at least one opaque, traceable citation.
            assert claim["supporting_evidence_ids"], "uncited public claim served"
            assert all(
                ev.startswith("ev_") for ev in claim["supporting_evidence_ids"]
            )


def test_public_skill_report_unlinked_bucket_is_always_empty(
    client: TestClient, mem_store: dict
) -> None:
    """Unattached private vault evidence never surfaces publicly: the unlinked
    bucket keeps its shape for clients but is ALWAYS empty (no items, no
    counts) — public skill reports show only evidence chained to published
    projects."""
    slug, skill = _published_passport_with_skill(client, mem_store)
    body = _get_public_skill_report(client, slug, skill).json()

    assert body["unlinked_supporting_evidence"] == {
        "items": [],
        "count": 0,
        "more_count": 0,
    }


def _set_disclosure_mode(client: TestClient, mode: str) -> None:
    res = client.put(
        "/api/v1/student/vbr/passport/disclosure/mode", json={"mode": mode}
    )
    assert res.status_code == 200, res.text


def test_public_skill_report_never_names_unpublished_projects(
    client: TestClient, mem_store: dict
) -> None:
    """G1 regression: ``collect_skill_report`` scans the student's ENTIRE
    vault, so a chain anchored to a project whose report was never published
    must be dropped by the passport-membership gate — in the default
    recruiter-safe mode AND in custom mode (full access is covered by the
    disclosure suite). The never-published project's title must not appear
    anywhere in the public payload."""
    from tests.test_passport_disclosure import _make_project

    slug, _ = _published_passport_with_skill(client, mem_store)
    _make_project(
        client,
        mem_store,
        title="Stealth Draft Rewrite",
        repo_owner="ghostorg",
        repo_name="ghost-draft-repo",
        claimed_skills=["Python"],
    )

    for mode in ("recruiter_safe", "custom"):
        _set_disclosure_mode(client, mode)
        res = _get_public_skill_report(client, slug, "python")
        assert res.status_code == 200, mode
        assert "Stealth Draft Rewrite" not in res.text, mode
        assert "ghost-draft-repo" not in res.text, mode


def test_public_skill_report_never_shows_unattached_vault_evidence(
    client: TestClient, mem_store: dict
) -> None:
    """G1 regression: vault evidence the student never attached to ANY project
    (no project_id → no disclosure node governs it) must never surface on the
    public skill report — neither as a project-less chain nor as an unlinked
    supporting-evidence card."""
    slug, _ = _published_passport_with_skill(client, mem_store)
    _seed_github_proof(
        mem_store,
        repo_url="https://github.com/ghostorg/vault-only-repo",
        repo_owner="ghostorg",
        repo_name="vault-only-repo",
        detected_skills=["Python"],
        submitted_skill_claims=["Python"],
        analysis_summary="Private vault-only repository analysis.",
        public_safe_summary="GitHub proof for ghostorg/vault-only-repo.",
    )

    res = _get_public_skill_report(client, slug, "python")
    assert res.status_code == 200
    assert "vault-only-repo" not in res.text
    assert "ghostorg" not in res.text
    body = res.json()
    assert body["unlinked_supporting_evidence"]["items"] == []
    assert body["unlinked_supporting_evidence"]["count"] == 0
    # Owner views are untouched: the private (authenticated) skill report
    # still unions the whole vault, including the unattached proof.
    private = client.get(
        "/api/v1/student/vbr/passport/skill-report", params={"skill": "Python"}
    )
    assert private.status_code == 200, private.text
    assert "vault-only-repo" in private.text


def test_public_skill_report_drops_chains_without_a_project_anchor(
    client: TestClient, mem_store: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G1 regression for the chain path specifically: a linked proof chain with
    NO ``project_id`` (built from unattached vault evidence) has no disclosure
    node governing it and must be dropped from the PUBLIC projection, while a
    chain anchored to the published project survives."""
    from app.services import vbr_work_passport_service as svc

    slug, _ = _published_passport_with_skill(client, mem_store)
    published_project_id = next(
        str(row["id"])
        for row in mem_store.get("vbr_projects", {}).values()
        if row.get("public_report_token")
    )

    def _chain(chain_id: str, project_id: str | None, title: str) -> dict:
        return {
            "chain_id": chain_id,
            "project_id": project_id,
            "project_title": title,
            "canonical_skill_name": "Python",
            "chain_label": title,
            "linked_evidence_ids": ["ev_github_deadbeefcafe01"],
            "source_types_present": ["github"],
            "primary_source_type": "github",
            "connection_reasons": [],
            "proof_strength_summary": {},
            "limitations": [],
            "public_safe": True,
            "evidence": [
                {
                    "evidence_id": "ev_github_deadbeefcafe01",
                    "source_type": "github",
                    "public_safe": True,
                }
            ],
        }

    def _fake_synthesize(report: dict, *, use_llm: bool = True) -> dict:
        return {
            "synthesis_summary": "ok",
            "source_coverage": {"GitHub": True},
            "proof_chains": [],
            "unlinked_supporting_evidence": {"items": [], "count": 0, "more_count": 0},
            "linked_proof_chains": [
                _chain("chain_deadbeefcafe01", published_project_id, "Anchored Chain"),
                _chain("chain_cafebabe000002", None, "Vault Only Standalone Chain"),
            ],
            "llm_synthesis": [],
        }

    monkeypatch.setattr(svc, "synthesize_skill_report", _fake_synthesize)

    res = _get_public_skill_report(client, slug, "python")
    assert res.status_code == 200, res.text
    assert "Vault Only Standalone Chain" not in res.text
    titles = [c.get("project_title") for c in res.json()["linked_proof_chains"]]
    assert titles == ["Anchored Chain"]
