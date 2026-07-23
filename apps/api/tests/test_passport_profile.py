"""Tests for the Passport Profile (consented candidate identity, migration 062).

Owner-only:
  ``GET /api/v1/student/vbr/passport/profile``
  ``PUT /api/v1/student/vbr/passport/profile``

Covers:
  - create / update round-trip with PATCH semantics (omitted unchanged,
    explicit empty clears)
  - field validation: text caps, https-only host-pinned links, graduation
    year range, availability vocabulary, role-area cap
  - owner scoping: each user reads/writes only their own profile
  - public passport identity: profile fields serialized when published,
    visibility toggles honored, empty fields omitted (never placeholdered),
    work authorization opt-in only
  - scrubbing: emails / private ids in student text never reach the public
    surface
  - prefill comes from student_profiles but is never auto-published
  - cross-user isolation: A's profile never appears on B's passport

All storage is in-memory (dict mode). No network / LLM calls.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app

from tests.test_vbr_project_defense import OTHER_USER_ID, USER_ID

_PROFILE_PATH = "/api/v1/student/vbr/passport/profile"


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


def _as_user(user_id: str) -> None:
    app.dependency_overrides[get_current_user_id] = lambda: user_id


def _get(client: TestClient):
    return client.get(_PROFILE_PATH)


def _put(client: TestClient, **body):
    return client.put(_PROFILE_PATH, json=body)


def _publish(client: TestClient):
    return client.post("/api/v1/student/vbr/passport/publish", json=None)


def _get_public(client: TestClient, slug: str):
    return client.get(f"/api/v1/public/p/{slug}")


_FULL_PROFILE = {
    "full_name": "Ada Lovelace",
    "headline": "AI Engineer | M.S. in Artificial Intelligence",
    "bio": "I build evidence-backed ML systems and full-stack products.",
    "institution": "Worcester Polytechnic Institute",
    "degree": "M.S. in Artificial Intelligence",
    "graduation_year": 2027,
    "location": "Worcester, Massachusetts",
    "github_url": "https://github.com/ada",
    "linkedin_url": "https://www.linkedin.com/in/ada",
    "portfolio_url": "https://ada.dev",
    "role_areas": ["AI/ML", "Backend"],
    "availability": "seeking_internship",
}


# ── Owner CRUD ────────────────────────────────────────────────────────────────

def test_get_profile_defaults_when_absent(client: TestClient) -> None:
    res = _get(client)
    assert res.status_code == 200
    body = res.json()
    assert body["has_profile"] is False
    assert body["profile"]["full_name"] is None
    assert body["profile"]["show_work_authorization"] is False
    assert body["profile"]["show_links"] is True


def test_create_and_roundtrip(client: TestClient) -> None:
    res = _put(client, **_FULL_PROFILE)
    assert res.status_code == 200
    body = res.json()
    assert body["has_profile"] is True
    for key, value in _FULL_PROFILE.items():
        assert body["profile"][key] == value
    # GET returns the same stored profile.
    again = _get(client).json()
    assert again["profile"]["full_name"] == "Ada Lovelace"
    assert again["has_profile"] is True


def test_patch_semantics_omitted_unchanged_empty_clears(client: TestClient) -> None:
    _put(client, **_FULL_PROFILE)
    res = _put(client, headline="", location=None)
    assert res.status_code == 200
    profile = res.json()["profile"]
    assert profile["headline"] is None  # cleared
    assert profile["location"] is None  # cleared
    assert profile["full_name"] == "Ada Lovelace"  # untouched
    assert profile["github_url"] == "https://github.com/ada"  # untouched


def test_text_normalization_and_caps(client: TestClient) -> None:
    res = _put(client, full_name="  Ada\n  Lovelace  ")
    assert res.json()["profile"]["full_name"] == "Ada Lovelace"
    too_long = "x" * 200
    res = _put(client, headline=too_long)
    assert res.status_code == 422
    assert res.json()["detail"]["field"] == "headline"


@pytest.mark.parametrize(
    "field,value",
    [
        ("github_url", "http://github.com/ada"),  # not https
        ("github_url", "https://gitlab.com/ada"),  # wrong host
        ("linkedin_url", "https://evil.com/in/ada"),  # wrong host
        ("portfolio_url", "javascript:alert(1)"),  # not a URL
        ("portfolio_url", "https://ada.dev/?token=abc123"),  # tokenized
        ("portfolio_url", "https://user:pass@ada.dev/"),  # credentials
    ],
)
def test_url_validation_rejects(client: TestClient, field: str, value: str) -> None:
    res = _put(client, **{field: value})
    assert res.status_code == 422
    assert res.json()["detail"]["field"] == field


def test_url_validation_accepts_subdomain_hosts(client: TestClient) -> None:
    res = _put(client, linkedin_url="https://www.linkedin.com/in/ada")
    assert res.status_code == 200


def test_graduation_year_range(client: TestClient) -> None:
    assert _put(client, graduation_year=1900).status_code == 422
    assert _put(client, graduation_year=2150).status_code == 422
    assert _put(client, graduation_year=2027).status_code == 200


def test_availability_vocabulary(client: TestClient) -> None:
    assert _put(client, availability="hire-me-now").status_code == 422
    assert _put(client, availability="open_to_opportunities").status_code == 200
    # Empty clears.
    assert _put(client, availability="").json()["profile"]["availability"] is None


def test_role_areas_cap_and_dedupe(client: TestClient) -> None:
    res = _put(client, role_areas=["AI", "AI", " Backend "])
    assert res.json()["profile"]["role_areas"] == ["AI", "Backend"]
    res = _put(client, role_areas=[f"Area {i}" for i in range(9)])
    assert res.status_code == 422


def test_owner_scoping_two_users(client: TestClient) -> None:
    _put(client, full_name="Ada Lovelace")
    _as_user(OTHER_USER_ID)
    other = _get(client).json()
    assert other["has_profile"] is False
    assert other["profile"]["full_name"] is None
    _put(client, full_name="Grace Hopper")
    _as_user(USER_ID)
    assert _get(client).json()["profile"]["full_name"] == "Ada Lovelace"


def test_prefill_from_student_profile_not_auto_published(
    client: TestClient, mem_store: dict
) -> None:
    mem_store.setdefault("student_profiles", {})["sp1"] = {
        "user_id": USER_ID,
        "full_name": "Ada Lovelace",
        "school_name": "WPI",
        "degree": "M.S.",
        "major": "Artificial Intelligence",
        "graduation_year": 2027,
        "links": {"github_url": "https://github.com/ada"},
    }
    body = _get(client).json()
    assert body["prefill"]["full_name"] == "Ada Lovelace"
    assert body["prefill"]["institution"] == "WPI"
    assert body["prefill"]["degree"] == "M.S. in Artificial Intelligence"
    assert body["has_profile"] is False
    # Prefill is editor-only: with no saved profile, the public passport must
    # not surface the prefill link.
    slug = _publish(client).json()["public_slug"]
    public = _get_public(client, slug).json()
    assert public["identity"]["github_url"] is None


# ── Public serialization ─────────────────────────────────────────────────────

def test_public_identity_serves_profile_fields(client: TestClient) -> None:
    _put(client, **_FULL_PROFILE)
    slug = _publish(client).json()["public_slug"]
    public = _get_public(client, slug).json()
    identity = public["identity"]
    assert public["candidate_display_name"] == "Ada Lovelace"
    assert identity["display_name"] == "Ada Lovelace"
    assert identity["headline"] == _FULL_PROFILE["headline"]
    assert identity["institution"] == "Worcester Polytechnic Institute"
    assert identity["degree"] == "M.S. in Artificial Intelligence"
    assert identity["graduation_year"] == 2027
    assert identity["location"] == "Worcester, Massachusetts"
    assert identity["github_url"] == "https://github.com/ada"
    assert identity["linkedin_url"] == "https://www.linkedin.com/in/ada"
    assert identity["portfolio_url"] == "https://ada.dev"
    assert identity["availability_label"] == "Seeking internship"
    assert identity["bio"] == _FULL_PROFILE["bio"]
    assert identity["has_custom_profile"] is True


def test_public_identity_omits_empty_fields(client: TestClient) -> None:
    _put(client, full_name="Ada Lovelace")  # nothing else
    slug = _publish(client).json()["public_slug"]
    identity = _get_public(client, slug).json()["identity"]
    assert identity["display_name"] == "Ada Lovelace"
    for field in ("institution", "degree", "location", "bio", "github_url",
                  "linkedin_url", "portfolio_url", "availability_label",
                  "work_authorization_note"):
        assert identity[field] is None, field


def test_visibility_toggles_hide_fields(client: TestClient) -> None:
    _put(client, **_FULL_PROFILE)
    _put(client, show_links=False, show_location=False, show_availability=False)
    slug = _publish(client).json()["public_slug"]
    identity = _get_public(client, slug).json()["identity"]
    assert identity["github_url"] is None
    assert identity["linkedin_url"] is None
    assert identity["portfolio_url"] is None
    assert identity["location"] is None
    assert identity["availability_label"] is None
    # Still identified — toggles hide only their own fields.
    assert identity["display_name"] == "Ada Lovelace"


def test_work_authorization_opt_in_only(client: TestClient) -> None:
    _put(client, **_FULL_PROFILE, work_authorization_note="Authorized to work in the US")
    slug = _publish(client).json()["public_slug"]
    identity = _get_public(client, slug).json()["identity"]
    # Default show_work_authorization=False → never public without opt-in.
    assert identity["work_authorization_note"] is None
    _put(client, show_work_authorization=True)
    identity = _get_public(client, slug).json()["identity"]
    assert identity["work_authorization_note"] == "Authorized to work in the US"


def test_public_surface_never_leaks_email_in_bio(client: TestClient) -> None:
    _put(
        client,
        full_name="Ada Lovelace",
        bio="Contact me at ada@example.com for details.",
    )
    slug = _publish(client).json()["public_slug"]
    public = _get_public(client, slug)
    assert public.status_code == 200
    assert "ada@example.com" not in public.text


def test_unpublished_passport_hides_profile(client: TestClient) -> None:
    _put(client, **_FULL_PROFILE)
    slug = _publish(client).json()["public_slug"]
    client.post("/api/v1/student/vbr/passport/unpublish")
    assert _get_public(client, slug).status_code == 404


def test_cross_user_profile_never_leaks(client: TestClient) -> None:
    _put(client, full_name="Ada Lovelace", github_url="https://github.com/ada")
    _as_user(OTHER_USER_ID)
    _put(client, full_name="Grace Hopper")
    slug_b = _publish(client).json()["public_slug"]
    public_b = _get_public(client, slug_b).json()
    assert public_b["candidate_display_name"] == "Grace Hopper"
    assert "Ada" not in str(public_b)
    assert public_b["identity"]["github_url"] is None


def test_private_passport_identity_previews_profile(client: TestClient) -> None:
    _put(client, **_FULL_PROFILE)
    private = client.get("/api/v1/student/vbr/passport").json()
    identity = private["identity"]
    assert identity["display_name"] == "Ada Lovelace"
    assert identity["institution"] == "Worcester Polytechnic Institute"
    assert identity["has_custom_profile"] is True
