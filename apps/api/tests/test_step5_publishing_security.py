"""Step 5 — Final Report + Passport publishing security tests.

Hostile-content posture for the two anonymous recruiter surfaces:

  ``GET /api/v1/public/p/{public_slug}``       (public Work Passport)
  ``GET /api/v1/public/vbr/reports/{public_token}``   (public VBR project report)

Hostile private-looking values are injected into the student-controlled free
text that feeds both surfaces (project title / description metadata) and each
surface must respond fail-safe: either the served payload no longer contains
the hostile value (scrubbed) or the surface refuses to serve at all (404,
fail-closed). Additionally, the public JSON must never carry private key names
(raw_transcript, storage_path, signed_url, source_id, user_id, …) or private
suggestion/unattached bookkeeping.

All storage is in-memory (dict mode). No network / LLM calls.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app

from tests.test_vbr_project_defense import USER_ID
from tests.test_vbr_work_passport import _make_full_project


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

def _publish_report_and_passport(client: TestClient, project_id: str) -> tuple[str, str]:
    """Publish the project report + the passport; return (slug, report_token)."""
    resp = client.post(f"/api/v1/student/vbr/projects/{project_id}/public-report")
    assert resp.status_code == 200
    token = resp.json()["public_token"]

    resp = client.post("/api/v1/student/vbr/passport/publish")
    assert resp.status_code == 200
    slug = resp.json()["public_slug"]
    return slug, token


def _inject_hostile_text(mem_store: dict, project_id: str, hostile: str) -> None:
    """Plant ``hostile`` in the student-controlled free text the public
    surfaces are built from (project title + description metadata)."""
    row = mem_store["vbr_projects"][project_id]
    row["title"] = f"Skill Tracker {hostile}"
    metadata = dict(row.get("metadata") or {})
    metadata["description"] = f"A project that uses {hostile} internally."
    row["metadata"] = metadata


def _get_public_surfaces(client: TestClient, slug: str, token: str) -> list:
    return [
        client.get(f"/api/v1/public/p/{slug}"),
        client.get(f"/api/v1/public/vbr/reports/{token}"),
    ]


def _all_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            keys.add(str(key).lower())
            keys |= _all_keys(nested)
    elif isinstance(value, list):
        for item in value:
            keys |= _all_keys(item)
    return keys


# ── Hostile free-text values must never be served publicly ───────────────────

# Each entry is (test id, hostile value planted in free text, sentinel that must
# not appear in any public response body). The sentinel is the distinctive
# secret part so the assertion cannot pass by accident.
_HOSTILE_CASES = [
    ("github-pat", "ghp_hostileToken1234567890abcd", "ghp_hostileToken1234567890abcd"),
    ("github-fine-grained-pat", "github_pat_hostile1234567890_ABCdef", "github_pat_hostile"),
    ("api-key", "api_key=sk-hostile-abc123", "sk-hostile-abc123"),
    ("client-secret", "client_secret=hostile-secret-999", "hostile-secret-999"),
    ("bearer-token", "Bearer hostiletoken123456", "hostiletoken123456"),
    ("local-user-path", "/Users/alice/private/report.pdf", "/Users/alice/private/report.pdf"),
    ("relative-storage-path", "uploads/user-123/report.pdf", "uploads/user-123/report.pdf"),
    ("raw-email", "alice.hostile@example.com", "alice.hostile@example.com"),
    ("numeric-score", "scored 91/100 on the rubric", "91/100"),
    ("percent-confidence", "95% confidence in the result", "95%"),
    ("trust-score", "trust score 88 overall", "trust score"),
    (
        "signed-storage-url",
        "https://abc.supabase.co/storage/v1/object/sign/vbr/sessions/x.webm?token=sekret",
        "supabase.co/storage",
    ),
    ("tmp-path", "/tmp/vbr-scratch/movie.webm", "/tmp/vbr-scratch"),
]


@pytest.mark.parametrize(
    ("hostile", "sentinel"),
    [(hostile, sentinel) for _, hostile, sentinel in _HOSTILE_CASES],
    ids=[case_id for case_id, _, _ in _HOSTILE_CASES],
)
def test_hostile_free_text_never_reaches_public_surfaces(
    client: TestClient, mem_store: dict, hostile: str, sentinel: str
) -> None:
    project_id = _make_full_project(client, mem_store)
    slug, token = _publish_report_and_passport(client, project_id)
    _inject_hostile_text(mem_store, project_id, hostile)

    for resp in _get_public_surfaces(client, slug, token):
        # Scrubbed (200 without the value) or fail-closed (404) — never served raw.
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            assert sentinel.lower() not in resp.text.lower()


def test_public_surfaces_still_serve_safe_projects(client: TestClient, mem_store: dict) -> None:
    """Sanity guard for the cases above: a clean project serves 200 publicly,
    so a 404 in the hostile tests really is the fail-closed path, not a broken
    fixture."""
    project_id = _make_full_project(client, mem_store)
    slug, token = _publish_report_and_passport(client, project_id)

    for resp in _get_public_surfaces(client, slug, token):
        assert resp.status_code == 200


# ── Private key names must never appear in public JSON ───────────────────────

_FORBIDDEN_PUBLIC_KEYS = {
    "raw_transcript",
    "transcript_segments",
    "raw_document_text",
    "storage_path",
    "media_storage_path",
    "signed_url",
    "source_id",
    "provider_id",
    "private_id",
    "user_id",
    "auth_user_id",
    "email",
    "confidence",
    "score",
    "confidence_score",
    "trust_score",
    "api_key",
    "client_secret",
    "access_token",
    "artifact_data",
    "raw_metadata",
    "public_report_token",
    "project_id",
    "session_id",
    "question_id",
    "suggestions",
    "suggested_attachments",
    "unattached_proof_summary",
    "attachment_overview",
}


def test_public_json_never_carries_private_key_names(client: TestClient, mem_store: dict) -> None:
    project_id = _make_full_project(client, mem_store)
    slug, token = _publish_report_and_passport(client, project_id)

    for resp in _get_public_surfaces(client, slug, token):
        assert resp.status_code == 200
        leaked = _all_keys(resp.json()) & _FORBIDDEN_PUBLIC_KEYS
        assert not leaked, f"private key names leaked publicly: {sorted(leaked)}"


def test_public_passport_carries_no_suggestion_objects(client: TestClient, mem_store: dict) -> None:
    """Suggested / unattached Proof Attachment Intelligence is owner-only: the
    public passport may carry at most the count-free limitation sentence."""
    project_id = _make_full_project(client, mem_store)
    slug, _token = _publish_report_and_passport(client, project_id)

    resp = client.get(f"/api/v1/public/p/{slug}")
    assert resp.status_code == 200
    body = resp.text.lower()
    assert "suggestion_reason" not in body
    assert "likely_project" not in body
    assert "unattached_count" not in body
    assert "suggested_proof_count" not in body


# ── Publish-state lifecycle on the public surfaces ────────────────────────────

def test_unpublishing_report_removes_it_and_its_link_from_public_passport(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _make_full_project(client, mem_store)
    slug, token = _publish_report_and_passport(client, project_id)

    resp = client.get(f"/api/v1/public/p/{slug}")
    assert resp.status_code == 200
    assert any(
        p["public_report_path"] == f"/vbr/report/{token}"
        for p in resp.json()["featured_projects"]
    )

    assert client.delete(f"/api/v1/student/vbr/projects/{project_id}/public-report").status_code == 200

    # The passport stays live but stops featuring / linking the report…
    resp = client.get(f"/api/v1/public/p/{slug}")
    assert resp.status_code == 200
    assert resp.json()["featured_projects"] == []
    assert token not in resp.text
    # …and the old report link itself stops resolving.
    assert client.get(f"/api/v1/public/vbr/reports/{token}").status_code == 404


def test_unpublishing_passport_fails_closed_but_keeps_report_link_and_private_data(
    client: TestClient, mem_store: dict
) -> None:
    project_id = _make_full_project(client, mem_store)
    slug, token = _publish_report_and_passport(client, project_id)

    assert client.post("/api/v1/student/vbr/passport/unpublish").status_code == 200

    # Public passport fails closed.
    assert client.get(f"/api/v1/public/p/{slug}").status_code == 404
    # The individually-published report link is untouched by design…
    assert client.get(f"/api/v1/public/vbr/reports/{token}").status_code == 200
    # …and no private data was deleted: the private passport still has the project.
    private = client.get("/api/v1/student/vbr/passport")
    assert private.status_code == 200
    assert private.json()["project_count"] == 1
    assert private.json()["projects"][0]["report"]["is_public"] is True
