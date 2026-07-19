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
from tests.test_vbr_project_defense import USER_ID


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


def test_public_skill_report_unlinked_bucket_is_capped_and_safe(
    client: TestClient, mem_store: dict
) -> None:
    slug, skill = _published_passport_with_skill(client, mem_store)
    body = _get_public_skill_report(client, slug, skill).json()

    bucket = body["unlinked_supporting_evidence"]
    assert set(bucket.keys()) == {"items", "count", "more_count"}
    for item in bucket["items"]:
        # Compact safe card shape only — no ids, no snippets, no locators
        # beyond the safe display location.
        assert set(item.keys()) <= {
            "proof_type",
            "title",
            "safe_summary",
            "safe_location",
            "corroborates",
            "limitation",
        }
