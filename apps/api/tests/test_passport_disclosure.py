"""Granular hierarchical Passport disclosure (migration 063) — product matrix.

The student controls, per resource, exactly what an anonymous recruiter may
see. The canonical resolver (``app.services.passport_disclosure``) is the ONE
policy authority consulted by every public serializer and media gate:

* ``vbr_work_passports.is_published`` stays the master switch ABOVE everything
  here — Private fails every public surface closed, even explicit grants.
* ``recruiter_safe`` mode (the default) reproduces the pre-063 public behavior;
  stored overrides are kept but IGNORED.
* ``custom`` mode applies overrides hierarchically (passport → project →
  report → aspect; skill_group → skill → project_skill) and is authoritative
  for anonymous media access — it can both grant (open an owner-only document
  the student opted in) and revoke (hide a previously public-safe replay).

Covered here, per the product test matrix: global mode semantics + tenant
isolation, project/report hiding, the skills tree, GitHub summary/viewable/
lines states, website URL/frames/video aspects, per-document view & download
grants, defense transcript/video grants, report section omission + honest
counts, disclosure_version revocation semantics, audit rows, and leak scans.

All storage is in-memory (dict mode). No network / LLM calls.
"""

from __future__ import annotations

import json

from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import (
    get_current_user_id,
    get_db,
    get_optional_user_id,
    get_pipeline_db,
)
from app.main import app
from app.services import proof_artifact_service as artifacts
from app.services import passport_disclosure as disclosure_service
from app.services.passport_disclosure import (
    FULL_ACCESS_DEFAULTS,
    HIDDEN,
    MODE_CUSTOM,
    MODE_FULL_ACCESS,
    MODE_RECRUITER_SAFE,
    PROJECT_ASPECTS,
    RECRUITER_SAFE_DEFAULTS,
    RESOURCE_TYPES,
    SUMMARY,
    VIEWABLE,
    VISIBLE,
    EffectiveDisclosure,
    apply_disclosure_overrides,
    load_effective_disclosure,
)

from tests.conftest import seed_published_passport
from tests.test_vbr_project_defense import (
    OTHER_USER_ID,
    USER_ID,
    VIDEO_TRANSCRIPT_SEGMENTS,
    _create_project_defense,
    _generate_questions,
    _seed_auto_video_transcript,
    _seed_document_evidence,
    _seed_github_proof,
    _seed_workflow_analysis,
    _submit_defense,
)
from tests.test_vbr_student_report import _seed_github_proof_with_code_evidence
from tests.test_vbr_work_passport import _SUBSTANTIVE_DEFENSE_TRANSCRIPT

_REPO_URL = "https://github.com/octocat/Hello-World"
_BLOB_PREFIX = f"{_REPO_URL}/blob/main"
_WEBSITE_URL = "http://demo.example.com"
_DOC_TITLE = "Final Year Project Report"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def pipeline_db() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict, pipeline_db: dict) -> TestClient:
    """TestClient whose caller identity is switchable per request.

    ``required`` = the authenticated identity (owner routes); setting it to
    None makes authenticated routes fail 401, proving public reads need no
    auth. ``optional`` = the media-route caller (None = anonymous recruiter).
    """
    caller: dict = {"required": USER_ID, "optional": USER_ID}

    def _required_identity() -> str:
        if caller["required"] is None:
            raise HTTPException(status_code=401, detail="unauthenticated")
        return caller["required"]

    app.dependency_overrides[get_current_user_id] = _required_identity
    app.dependency_overrides[get_optional_user_id] = lambda: caller["optional"]
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: pipeline_db
    test_client = TestClient(app)
    test_client.caller = caller  # type: ignore[attr-defined]
    yield test_client
    app.dependency_overrides.clear()


def _as_user(client: TestClient, user_id: str) -> None:
    client.caller["required"] = user_id
    client.caller["optional"] = user_id


def _as_anon(client: TestClient) -> None:
    client.caller["required"] = None
    client.caller["optional"] = None


# ── Owner / public request helpers ───────────────────────────────────────────


def _publish_passport(client: TestClient):
    return client.post("/api/v1/student/vbr/passport/publish", json={})


def _unpublish_passport(client: TestClient):
    return client.post("/api/v1/student/vbr/passport/unpublish")


def _publish_report(client: TestClient, project_id: str):
    return client.post(f"/api/v1/student/vbr/projects/{project_id}/public-report")


def _public_passport(client: TestClient, slug: str):
    return client.get(f"/api/v1/public/p/{slug}")


def _public_skill_report(client: TestClient, slug: str, skill: str):
    return client.get(f"/api/v1/public/p/{slug}/skills/{skill}")


def _public_report(client: TestClient, token: str):
    return client.get(f"/api/v1/public/vbr/reports/{token}")


def _get_disclosure(client: TestClient):
    return client.get("/api/v1/student/vbr/passport/disclosure")


def _set_mode(client: TestClient, mode: str):
    return client.put("/api/v1/student/vbr/passport/disclosure/mode", json={"mode": mode})


def _ov(rtype: str, key: str, visibility: str | None) -> dict:
    return {"resource_type": rtype, "resource_key": key, "visibility": visibility}


def _apply(client: TestClient, *changes: dict):
    return client.put(
        "/api/v1/student/vbr/passport/disclosure/overrides",
        json={"changes": list(changes)},
    )


def _register_artifact(
    mem_store: dict,
    *,
    artifact_type: str,
    proof_type: str,
    proof_id: str,
    project_id: str,
    policy: str = "owner_only",
    owner: str = USER_ID,
    data: bytes = b"artifact-bytes",
    mime: str = "application/octet-stream",
    file_name: str = "artifact.bin",
) -> dict:
    row = artifacts.register_artifact_with_bytes(
        mem_store,
        owner_user_id=owner,
        proof_type=proof_type,
        artifact_type=artifact_type,
        data=data,
        file_name=file_name,
        mime_type=mime,
        proof_id=proof_id,
        project_id=project_id,
        access_policy=policy,
    )
    assert row is not None
    return row


# ── Scenario builders ─────────────────────────────────────────────────────────


def _make_project(
    client: TestClient,
    mem_store: dict,
    *,
    title: str = "Skill Evidence Tracker",
    repo_owner: str = "octocat",
    repo_name: str = "Hello-World",
    claimed_skills: list[str] | None = None,
    detected_skills: list[str] | None = None,
    github_code_evidence: bool = False,
    github_visibility: str = "public",
    document: bool = False,
    website: bool = False,
    defense: bool = False,
    **create_overrides: object,
) -> dict:
    """Create one Project Defense project with the requested proofs attached.

    Returns the ids needed by the disclosure tests: project / session /
    github proof / document (the per-document disclosure key) / website
    session (the frames+replay artifact key) / repo URL.
    """
    claimed = claimed_skills or ["Python", "React"]
    detected = detected_skills or claimed
    repo_url = f"https://github.com/{repo_owner}/{repo_name}"
    seed_kwargs = {
        "repo_url": repo_url,
        "repo_owner": repo_owner,
        "repo_name": repo_name,
        "visibility": github_visibility,
        "detected_skills": detected,
        "submitted_skill_claims": detected,
        "public_safe_summary": "Repository evidence observed for this project.",
    }
    if github_code_evidence:
        github_proof_id = _seed_github_proof_with_code_evidence(mem_store, **seed_kwargs)
    else:
        github_proof_id = _seed_github_proof(mem_store, **seed_kwargs)

    attached: dict = {"github_proof_id": github_proof_id}
    document_id = None
    if document:
        document_id = _seed_document_evidence(mem_store)
        attached["document_evidence_ids"] = [document_id]
    website_session_id = None
    if website:
        website_session_id = _seed_workflow_analysis(mem_store)
        attached["website_proof_session_ids"] = [website_session_id]

    created = _create_project_defense(
        client,
        title=title,
        repo_url=repo_url,
        claimed_skills=claimed,
        attached_proofs=attached,
        **create_overrides,
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["project"]["id"]

    session_id = None
    if defense:
        session_id = _generate_questions(client, project_id).json()["session_id"]
        chunk_id = str(uuid4())
        mem_store.setdefault("vbr_video_chunks", {})[chunk_id] = {
            "id": chunk_id,
            "session_id": session_id,
            "chunk_index": 0,
            "bytes": 1024,
            "sha256": "deadbeef",
        }
        _seed_auto_video_transcript(mem_store, session_id, VIDEO_TRANSCRIPT_SEGMENTS)
        submitted = _submit_defense(
            client, session_id, combined_text=_SUBSTANTIVE_DEFENSE_TRANSCRIPT
        )
        assert submitted.status_code == 200, submitted.text

    return {
        "project_id": project_id,
        "session_id": session_id,
        "github_proof_id": github_proof_id,
        "document_id": document_id,
        "website_session_id": website_session_id,
        "repo_url": repo_url,
    }


def _publish_setup(client: TestClient, mem_store: dict, **project_kwargs) -> dict:
    """One published project + published passport → ctx incl. slug + token."""
    ctx = _make_project(client, mem_store, **project_kwargs)
    published = _publish_report(client, ctx["project_id"])
    assert published.status_code in (200, 201), published.text
    ctx["token"] = published.json()["public_token"]
    slug_res = _publish_passport(client)
    assert slug_res.status_code == 200, slug_res.text
    ctx["slug"] = slug_res.json()["public_slug"]
    return ctx


def _featured_by_token(passport_body: dict, token: str) -> dict | None:
    for card in passport_body.get("featured_projects") or []:
        if card.get("public_report_path") == f"/vbr/report/{token}":
            return card
    return None


def _top_skill_names(passport_body: dict) -> set[str]:
    return {s["skill"] for s in passport_body.get("top_skills") or []}


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL — master switch, modes, tenant isolation
# ═══════════════════════════════════════════════════════════════════════════════


def test_private_passport_blocks_public_surfaces_even_with_viewable_grants(
    client: TestClient, mem_store: dict
) -> None:
    """(1) Private is absolute: even explicit custom-mode viewable grants never
    open the public passport, skill report, report token, beam link, or a
    retained media artifact while ``is_published`` is false."""
    ctx = _publish_setup(client, mem_store, document=True, website=True)
    replay = _register_artifact(
        mem_store,
        artifact_type="website_replay_video",
        proof_type="website",
        proof_id=ctx["website_session_id"],
        project_id=ctx["project_id"],
        policy="public_safe",
    )
    doc_artifact = _register_artifact(
        mem_store,
        artifact_type="document_original",
        proof_type="document",
        proof_id=ctx["document_id"],
        project_id=ctx["project_id"],
    )
    beam_code = client.post("/api/v1/student/vbr/beam/links", json=None).json()["code"]

    # Grant everything the custom policy can grant…
    _set_mode(client, MODE_CUSTOM)
    _apply(
        client,
        _ov("website_video", ctx["project_id"], "viewable"),
        _ov("website_frames", ctx["project_id"], "viewable"),
        _ov("document", ctx["document_id"], "viewable"),
        _ov("document_download", ctx["document_id"], "downloadable"),
    )
    # …then flip the master switch to Private.
    _unpublish_passport(client)

    _as_anon(client)
    assert _public_passport(client, ctx["slug"]).status_code == 404
    assert _public_skill_report(client, ctx["slug"], "python").status_code == 404
    assert _public_report(client, ctx["token"]).status_code == 404
    assert client.get(f"/api/v1/public/beam/{beam_code}").status_code == 404
    assert client.get(f"/api/v1/proofs/artifacts/{replay['id']}/view").status_code == 404
    assert client.get(f"/api/v1/proofs/artifacts/{doc_artifact['id']}/view").status_code == 404
    assert (
        client.get(f"/api/v1/proofs/website/{ctx['website_session_id']}/replay").status_code
        == 404
    )


def test_recruiter_safe_mode_stores_but_ignores_overrides(
    client: TestClient, mem_store: dict
) -> None:
    """(2) In recruiter-safe mode summaries are public but overrides are inert:
    no shared_view / replay / transcript descriptors appear and downloads stay
    denied to non-owners, even though grants are stored."""
    ctx = _publish_setup(client, mem_store, document=True, website=True, defense=True)
    _register_artifact(
        mem_store,
        artifact_type="website_replay_video",
        proof_type="website",
        proof_id=ctx["website_session_id"],
        project_id=ctx["project_id"],
    )
    doc_artifact = _register_artifact(
        mem_store,
        artifact_type="document_original",
        proof_type="document",
        proof_id=ctx["document_id"],
        project_id=ctx["project_id"],
    )
    _register_artifact(
        mem_store,
        artifact_type="defense_transcript",
        proof_type="project_defense",
        proof_id=ctx["session_id"],
        project_id=ctx["project_id"],
        mime="text/plain",
    )

    # Grants are written while the mode REMAINS recruiter_safe (the default).
    res = _apply(
        client,
        _ov("website_video", ctx["project_id"], "viewable"),
        _ov("website_frames", ctx["project_id"], "viewable"),
        _ov("defense_transcript", ctx["project_id"], "viewable"),
        _ov("document", ctx["document_id"], "viewable"),
        _ov("document_download", ctx["document_id"], "downloadable"),
    )
    assert res.status_code == 200
    assert res.json()["passport"]["mode"] == MODE_RECRUITER_SAFE

    _as_anon(client)
    body = _public_report(client, ctx["token"]).json()
    # Summaries are public…
    assert body["github_proof"] is not None
    assert body["website_proofs"]
    assert body["project_defense_analysis"] is not None
    # …but no artifact descriptors materialize (grants ignored in this mode).
    assert body["defense_transcript_view"] is None
    assert body["defense_video_view"] is None
    for proof in body["website_proofs"]:
        assert proof["frame_views"] == []
        assert proof["replay_path"] is None
    for doc in body["documents"]:
        assert doc["disclosure"] == "summary"
        assert doc["shared_view"] is None
    # Owner-only media stays closed; download denied regardless of the grant.
    assert client.get(f"/api/v1/proofs/artifacts/{doc_artifact['id']}/view").status_code == 404
    assert (
        client.get(f"/api/v1/proofs/artifacts/{doc_artifact['id']}/download").status_code == 404
    )


def test_recruiter_safe_download_of_public_safe_artifact_stays_denied(
    client: TestClient, mem_store: dict
) -> None:
    """(2b) recruiter-safe = legacy public_safe VIEW behavior; the download
    action is never granted to a non-owner without an explicit custom grant."""
    ctx = _publish_setup(client, mem_store, website=True)
    replay = _register_artifact(
        mem_store,
        artifact_type="website_replay_video",
        proof_type="website",
        proof_id=ctx["website_session_id"],
        project_id=ctx["project_id"],
        policy="public_safe",
    )
    _as_anon(client)
    assert client.get(f"/api/v1/proofs/artifacts/{replay['id']}/view").status_code == 200
    assert client.get(f"/api/v1/proofs/artifacts/{replay['id']}/download").status_code == 404


def test_custom_mode_honors_overrides_end_to_end(client: TestClient, mem_store: dict) -> None:
    """(3) Custom mode applies stored overrides: granted frames/replay/document
    descriptors appear in the public report and their media routes serve the
    anonymous recruiter."""
    ctx = _publish_setup(client, mem_store, document=True, website=True)
    frame = _register_artifact(
        mem_store,
        artifact_type="website_frame",
        proof_type="website",
        proof_id=ctx["website_session_id"],
        project_id=ctx["project_id"],
        mime="image/jpeg",
        data=b"jpeg-bytes",
    )
    _register_artifact(
        mem_store,
        artifact_type="website_replay_video",
        proof_type="website",
        proof_id=ctx["website_session_id"],
        project_id=ctx["project_id"],
        mime="video/webm",
        data=b"webm-bytes",
    )
    doc_artifact = _register_artifact(
        mem_store,
        artifact_type="document_original",
        proof_type="document",
        proof_id=ctx["document_id"],
        project_id=ctx["project_id"],
        mime="application/pdf",
        data=b"pdf-bytes",
    )

    _set_mode(client, MODE_CUSTOM)
    _apply(
        client,
        _ov("website_frames", ctx["project_id"], "viewable"),
        _ov("website_video", ctx["project_id"], "viewable"),
        _ov("document", ctx["document_id"], "viewable"),
    )

    _as_anon(client)
    body = _public_report(client, ctx["token"]).json()
    proof = body["website_proofs"][0]
    assert proof["frame_views"] == [
        {"view_path": f"/api/v1/proofs/artifacts/{frame['id']}/view", "mime_type": "image/jpeg"}
    ]
    assert proof["replay_path"] == f"/api/v1/proofs/website/{ctx['website_session_id']}/replay"
    doc = body["documents"][0]
    assert doc["disclosure"] == "viewable"
    assert doc["shared_view"]["open_path"] == f"/api/v1/proofs/artifacts/{doc_artifact['id']}/view"

    # Every advertised descriptor genuinely serves anonymously.
    assert client.get(proof["frame_views"][0]["view_path"]).content == b"jpeg-bytes"
    assert client.get(proof["replay_path"]).content == b"webm-bytes"
    assert client.get(doc["shared_view"]["open_path"]).content == b"pdf-bytes"


def test_owner_keeps_full_access_while_private(client: TestClient, mem_store: dict) -> None:
    """(4) Privacy settings never lock the student out: while Private the owner
    still reads the disclosure editor, the private passport, the private
    report preview, and their own retained artifacts."""
    ctx = _publish_setup(client, mem_store, document=True)
    doc_artifact = _register_artifact(
        mem_store,
        artifact_type="document_original",
        proof_type="document",
        proof_id=ctx["document_id"],
        project_id=ctx["project_id"],
    )
    _unpublish_passport(client)

    editor = _get_disclosure(client)
    assert editor.status_code == 200
    body = editor.json()
    assert body["passport"]["is_published"] is False
    assert [p["project_id"] for p in body["projects"]] == [ctx["project_id"]]
    # Effective states are computed AS IF public so the student can prepare a
    # policy while Private (the UI overlays the master Private banner).
    assert body["projects"][0]["project"]["effective"] == "visible"

    assert client.get("/api/v1/student/vbr/passport").status_code == 200
    assert (
        client.get(f"/api/v1/student/vbr/projects/{ctx['project_id']}/report").status_code == 200
    )
    assert client.get(f"/api/v1/proofs/artifacts/{doc_artifact['id']}/view").status_code == 200
    assert (
        client.get(f"/api/v1/proofs/artifacts/{doc_artifact['id']}/download").status_code == 200
    )


def test_tenant_isolation_overrides_never_cross_users(
    client: TestClient, mem_store: dict
) -> None:
    """(5) One user's disclosure writes only ever affect their own surfaces —
    identity comes from the auth token, so writing an override that NAMES
    another tenant's project id is a harmless self-scoped row."""
    ctx_a = _publish_setup(client, mem_store)

    _as_user(client, OTHER_USER_ID)
    gid_b = _seed_github_proof(
        mem_store,
        user_id=OTHER_USER_ID,
        repo_url="https://github.com/otherorg/other-repo",
        repo_owner="otherorg",
        repo_name="other-repo",
    )
    created = _create_project_defense(
        client,
        title="Other Tenant Project",
        repo_url="https://github.com/otherorg/other-repo",
        attached_proofs={"github_proof_id": gid_b},
    )
    project_b = created.json()["project"]["id"]
    token_b = _publish_report(client, project_b).json()["public_token"]
    slug_b = _publish_passport(client).json()["public_slug"]

    # A goes fully custom, hides their OWN project, and even writes an override
    # naming B's project id.
    _as_user(client, USER_ID)
    _set_mode(client, MODE_CUSTOM)
    _apply(
        client,
        _ov("project", ctx_a["project_id"], "hidden"),
        _ov("project", project_b, "hidden"),  # names B's project — self-scoped
        _ov("skill", "python", "hidden"),
    )

    _as_anon(client)
    # A's surfaces honor A's policy…
    assert _public_report(client, ctx_a["token"]).status_code == 404
    # …while B's surfaces are completely unaffected.
    assert _public_report(client, token_b).status_code == 200
    passport_b = _public_passport(client, slug_b).json()
    assert _featured_by_token(passport_b, token_b) is not None

    # B's own policy row is untouched (still the recruiter-safe default).
    _as_user(client, OTHER_USER_ID)
    body = _get_disclosure(client).json()
    assert body["passport"]["mode"] == MODE_RECRUITER_SAFE
    assert body["passport"]["override_count"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# PROJECTS
# ═══════════════════════════════════════════════════════════════════════════════


def test_visible_project_appears_on_public_passport(client: TestClient, mem_store: dict) -> None:
    """(6) The default-visible published project renders a featured card that
    links its public report."""
    ctx = _publish_setup(client, mem_store)
    _as_anon(client)
    body = _public_passport(client, ctx["slug"]).json()
    card = _featured_by_token(body, ctx["token"])
    assert card is not None
    assert card["project_title"] == "Skill Evidence Tracker"
    assert body["featured_project_count"] == 1


def test_hidden_project_absent_from_featured_projects(
    client: TestClient, mem_store: dict
) -> None:
    """(7) A hidden project's card disappears from featured_projects and its
    report token 404s."""
    ctx = _publish_setup(client, mem_store)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("project", ctx["project_id"], "hidden"))

    _as_anon(client)
    body = _public_passport(client, ctx["slug"]).json()
    assert body["featured_projects"] == []
    assert body["featured_project_count"] == 0
    assert _public_report(client, ctx["token"]).status_code == 404


def test_hidden_project_never_leaks_through_skills_or_counts(
    client: TestClient, mem_store: dict
) -> None:
    """(8) A skill evidenced ONLY by a hidden project disappears from
    top_skills, and evidence_source_counts drop the hidden project's sources."""
    ctx_a = _publish_setup(client, mem_store)  # Python + React
    ctx_b = _make_project(
        client,
        mem_store,
        title="Go Microservice",
        repo_owner="betaorg",
        repo_name="beta-repo",
        claimed_skills=["Go"],
    )
    token_b = _publish_report(client, ctx_b["project_id"]).json()["public_token"]

    _as_anon(client)
    before = _public_passport(client, ctx_a["slug"]).json()
    assert "Go" in _top_skill_names(before)
    github_count_before = before["evidence_source_counts"]["GitHub Proof"]
    assert github_count_before == 2

    _as_user(client, USER_ID)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("project", ctx_b["project_id"], "hidden"))

    _as_anon(client)
    after = _public_passport(client, ctx_a["slug"]).json()
    assert "Go" not in _top_skill_names(after)  # only evidenced by the hidden project
    assert "Python" in _top_skill_names(after)  # other project unaffected
    assert after["evidence_source_counts"]["GitHub Proof"] == 1
    assert _featured_by_token(after, token_b) is None


def test_two_projects_partial_hiding_and_hidden_report_override(
    client: TestClient, mem_store: dict
) -> None:
    """(9) With two projects, hiding one leaves the other fully served; a
    ``report`` override 404s that project's token while the passport stays up."""
    ctx_a = _publish_setup(client, mem_store)
    ctx_b = _make_project(
        client,
        mem_store,
        title="Beta Project",
        repo_owner="betaorg",
        repo_name="beta-repo",
        claimed_skills=["Go"],
    )
    token_b = _publish_report(client, ctx_b["project_id"]).json()["public_token"]

    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("report", ctx_b["project_id"], "hidden"))

    _as_anon(client)
    assert _public_report(client, token_b).status_code == 404
    assert _public_report(client, ctx_a["token"]).status_code == 200
    passport = _public_passport(client, ctx_a["slug"])
    assert passport.status_code == 200  # the passport itself stays public
    # A hidden report never renders a dead featured card either.
    assert _featured_by_token(passport.json(), token_b) is None
    assert _featured_by_token(passport.json(), ctx_a["token"]) is not None


# ═══════════════════════════════════════════════════════════════════════════════
# SKILLS — group → skill → project_skill
# ═══════════════════════════════════════════════════════════════════════════════


def test_visible_skill_appears_publicly(client: TestClient, mem_store: dict) -> None:
    """(10) A default-visible evidenced skill appears in top_skills and serves
    its public skill report."""
    ctx = _publish_setup(client, mem_store)
    _as_anon(client)
    body = _public_passport(client, ctx["slug"]).json()
    assert "Python" in _top_skill_names(body)
    assert _public_skill_report(client, ctx["slug"], "python").status_code == 200


def test_hidden_skill_absent_and_skill_report_404s(client: TestClient, mem_store: dict) -> None:
    """(11) A hidden skill vanishes from top_skills AND its public skill report
    404s exactly like an unknown skill (no probing oracle)."""
    ctx = _publish_setup(client, mem_store)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("skill", "python", "hidden"))

    _as_anon(client)
    body = _public_passport(client, ctx["slug"]).json()
    assert "Python" not in _top_skill_names(body)
    assert "React" in _top_skill_names(body)
    res = _public_skill_report(client, ctx["slug"], "python")
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "vbr_work_passport_not_found"


def test_hidden_project_skill_scoped_to_one_project(client: TestClient, mem_store: dict) -> None:
    """(12) Hiding one project's claim of a skill removes it from THAT card's
    chips and THAT report's skill_evidence while the skill survives via the
    other project."""
    ctx_a = _publish_setup(client, mem_store)  # octocat: Python + React
    ctx_b = _make_project(
        client,
        mem_store,
        title="Beta Python Service",
        repo_owner="betaorg",
        repo_name="beta-repo",
        claimed_skills=["Python"],
    )
    token_b = _publish_report(client, ctx_b["project_id"]).json()["public_token"]

    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("project_skill", f"{ctx_a['project_id']}:python", "hidden"))

    _as_anon(client)
    passport = _public_passport(client, ctx_a["slug"]).json()
    card_a = _featured_by_token(passport, ctx_a["token"])
    card_b = _featured_by_token(passport, token_b)
    assert card_a is not None and card_b is not None
    assert "Python" not in {s["skill"] for s in card_a["top_skills"]}
    assert "Python" not in card_a["claimed_skills"]
    assert "Python" in {s["skill"] for s in card_b["top_skills"]}
    # The skill itself survives via project B.
    assert "Python" in _top_skill_names(passport)

    report_a = _public_report(client, ctx_a["token"]).json()
    assert "Python" not in {row["skill"] for row in report_a["skill_evidence"]}
    report_b = _public_report(client, token_b).json()
    assert "Python" in {row["skill"] for row in report_b["skill_evidence"]}


def test_hidden_skill_group_hides_all_member_skills(client: TestClient, mem_store: dict) -> None:
    """(13) Hiding a taxonomy group hides every skill in it (group → skill
    inheritance); other groups stay untouched."""
    ctx = _publish_setup(client, mem_store)  # Python (Programming Language), React (Frontend)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("skill_group", "Frontend", "hidden"))

    _as_anon(client)
    body = _public_passport(client, ctx["slug"]).json()
    assert "React" not in _top_skill_names(body)
    assert "Python" in _top_skill_names(body)
    assert _public_skill_report(client, ctx["slug"], "react").status_code == 404
    assert _public_skill_report(client, ctx["slug"], "python").status_code == 200


def test_skill_counts_exclude_hidden_skills(client: TestClient, mem_store: dict) -> None:
    """(14) Counts are effective-visibility-true: the public top_skills list
    shrinks and the owner summary's skills_public reflects the hidden skill."""
    ctx = _publish_setup(client, mem_store)
    _as_anon(client)
    before = len(_public_passport(client, ctx["slug"]).json()["top_skills"])
    assert before >= 2

    _as_user(client, USER_ID)
    _set_mode(client, MODE_CUSTOM)
    res = _apply(client, _ov("skill", "python", "hidden"))
    summary = res.json()["summary"]
    _as_anon(client)
    after = len(_public_passport(client, ctx["slug"]).json()["top_skills"])
    assert after == before - 1
    assert summary["skills_public"] == after


def test_skill_report_chains_honor_project_skill_overrides(
    client: TestClient, mem_store: dict
) -> None:
    """(15) Public skill-report proof chains drop chains from hidden
    project-skill claims while keeping chains from the still-visible project."""
    ctx_a = _publish_setup(client, mem_store)
    ctx_b = _make_project(
        client,
        mem_store,
        title="Beta Python Service",
        repo_owner="betaorg",
        repo_name="beta-repo",
        claimed_skills=["Python"],
    )
    _publish_report(client, ctx_b["project_id"])

    _as_anon(client)
    before = _public_skill_report(client, ctx_a["slug"], "python")
    assert before.status_code == 200
    assert "Skill Evidence Tracker" in before.text
    assert "Beta Python Service" in before.text

    _as_user(client, USER_ID)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("project_skill", f"{ctx_a['project_id']}:python", "hidden"))

    _as_anon(client)
    after = _public_skill_report(client, ctx_a["slug"], "python")
    assert after.status_code == 200
    assert "Skill Evidence Tracker" not in after.text  # hidden claim's chain dropped
    assert "Beta Python Service" in after.text  # surviving claim intact


# ═══════════════════════════════════════════════════════════════════════════════
# GITHUB — hidden / summary / viewable / lines
# ═══════════════════════════════════════════════════════════════════════════════


def test_github_summary_withholds_repo_identity_and_link(
    client: TestClient, mem_store: dict
) -> None:
    """(16) Summary state: the raw repository URL appears NOWHERE in the public
    report; the verified summary survives with repo link fields nulled."""
    ctx = _publish_setup(client, mem_store, github_code_evidence=True)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("github_repo", ctx["project_id"], "summary"))

    _as_anon(client)
    res = _public_report(client, ctx["token"])
    assert res.status_code == 200
    assert _REPO_URL not in res.text  # raw repo URL string absent everywhere
    body = res.json()
    gh = body["github_proof"]
    assert gh["disclosure"] == "summary"
    assert gh["repo_url"] is None
    assert gh["repo_owner"] is None
    assert gh["repo_name"] is None
    assert gh["public_safe_summary"]
    assert body["repo_full_name"] is None


def test_github_viewable_public_repo_keeps_repo_url(client: TestClient, mem_store: dict) -> None:
    """(17) Viewable + genuinely public repo → the repo link renders (this is
    the recruiter-safe default, i.e. the pre-063 behavior)."""
    ctx = _publish_setup(client, mem_store)
    _as_anon(client)
    body = _public_report(client, ctx["token"]).json()
    assert body["github_proof"]["repo_url"] == _REPO_URL
    assert body["github_proof"]["repo_is_public"] is True
    assert body["github_proof"]["disclosure"] == "viewable"
    assert body["repo_full_name"] == "octocat/Hello-World"


def test_github_trace_keeps_exact_line_link_format(client: TestClient, mem_store: dict) -> None:
    """(18) With repo + lines viewable, the code trace keeps the exact-line
    ``…#L`` blob link format end-to-end through every public scrubber."""
    ctx = _publish_setup(client, mem_store, github_code_evidence=True)
    _as_anon(client)
    body = _public_report(client, ctx["token"]).json()
    code = next(
        t
        for t in body["evidence_traces"]
        if t["source_type"] == "GitHub Proof" and t.get("file_path") == "src/main.py"
    )
    assert code["public_url"] == f"{_BLOB_PREFIX}/src/main.py#L24-L38"
    assert "#L" in code["public_url"]
    assert code["line_start"] == 24 and code["line_end"] == 38


def test_private_repo_never_yields_repo_url_even_when_viewable(
    client: TestClient, mem_store: dict
) -> None:
    """(19) A private repository (repo_is_public false) never exposes its URL
    on the public report — not even in the most permissive viewable state."""
    ctx = _publish_setup(client, mem_store, github_code_evidence=True, github_visibility="private")
    _set_mode(client, MODE_CUSTOM)
    _apply(
        client,
        _ov("github_repo", ctx["project_id"], "viewable"),
        _ov("github_lines", ctx["project_id"], "viewable"),
    )
    _as_anon(client)
    body = _public_report(client, ctx["token"]).json()
    assert body["github_proof"] is not None
    assert body["github_proof"]["repo_url"] is None
    assert body["github_proof"]["repo_is_public"] is False


def test_github_hidden_removes_section_traces_and_flag(
    client: TestClient, mem_store: dict
) -> None:
    """(20) Hidden GitHub: no github_proof object, no GitHub Proof traces, and
    the evidence package honestly reports github_proof_attached false."""
    ctx = _publish_setup(client, mem_store, github_code_evidence=True)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("github_repo", ctx["project_id"], "hidden"))

    _as_anon(client)
    res = _public_report(client, ctx["token"])
    body = res.json()
    assert body["github_proof"] is None
    assert not [t for t in body["evidence_traces"] if t["source_type"] == "GitHub Proof"]
    assert body["evidence_package"]["github_proof_attached"] is False
    assert _REPO_URL not in res.text


def test_github_lines_hidden_keeps_repo_link_but_strips_locators(
    client: TestClient, mem_store: dict
) -> None:
    """(21) Lines hidden with the repo still viewable: the repo link renders
    but code traces lose file paths, line ranges, commits, and #L links."""
    ctx = _publish_setup(client, mem_store, github_code_evidence=True)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("github_lines", ctx["project_id"], "hidden"))

    _as_anon(client)
    body = _public_report(client, ctx["token"]).json()
    assert body["github_proof"]["repo_url"] == _REPO_URL
    github_traces = [t for t in body["evidence_traces"] if t["source_type"] == "GitHub Proof"]
    assert github_traces
    for trace in github_traces:
        assert trace["file_path"] is None
        assert trace["public_url"] is None
        assert trace["line_start"] is None
        assert trace["commit_sha"] is None
    assert "#L" not in json.dumps(body["evidence_traces"])


# ═══════════════════════════════════════════════════════════════════════════════
# WEBSITE — summary / url / frames / video
# ═══════════════════════════════════════════════════════════════════════════════


def test_website_url_visible_shows_targets(client: TestClient, mem_store: dict) -> None:
    """(22) With the website URL aspect visible (the default), the live target
    and deployed URL render on the public report and passport card."""
    ctx = _publish_setup(client, mem_store, website=True)
    mem_store["vbr_projects"][ctx["project_id"]]["deployed_url"] = "https://demo.example.com"

    _as_anon(client)
    body = _public_report(client, ctx["token"]).json()
    assert body["website_proofs"][0]["target_website"] == _WEBSITE_URL
    assert body["deployed_url"] == "https://demo.example.com"
    card = _featured_by_token(_public_passport(client, ctx["slug"]).json(), ctx["token"])
    assert card["live_url"] == "https://demo.example.com"


def test_website_url_hidden_removes_url_string(client: TestClient, mem_store: dict) -> None:
    """(23) URL hidden: the raw target string is absent from the entire report
    AND passport response text — the workflow summary itself stays public."""
    ctx = _publish_setup(client, mem_store, website=True)
    mem_store["vbr_projects"][ctx["project_id"]]["deployed_url"] = "https://demo.example.com"
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("website_url", ctx["project_id"], "hidden"))

    _as_anon(client)
    report = _public_report(client, ctx["token"])
    assert report.status_code == 200
    assert "demo.example.com" not in report.text
    body = report.json()
    assert body["deployed_url"] is None
    assert body["website_proofs"][0]["target_website"] == ""

    passport = _public_passport(client, ctx["slug"])
    assert "demo.example.com" not in passport.text
    assert _featured_by_token(passport.json(), ctx["token"])["live_url"] is None


def test_website_frames_grant_independent_of_hidden_video(
    client: TestClient, mem_store: dict
) -> None:
    """(24) Frames viewable (with a genuinely retained frame) → frame_views
    populate and serve anonymously, while the still-hidden replay stays a null
    descriptor and its route 404s."""
    ctx = _publish_setup(client, mem_store, website=True)
    frame = _register_artifact(
        mem_store,
        artifact_type="website_frame",
        proof_type="website",
        proof_id=ctx["website_session_id"],
        project_id=ctx["project_id"],
        mime="image/jpeg",
        data=b"frame-bytes",
    )
    _register_artifact(
        mem_store,
        artifact_type="website_replay_video",
        proof_type="website",
        proof_id=ctx["website_session_id"],
        project_id=ctx["project_id"],
        mime="video/webm",
    )
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("website_frames", ctx["project_id"], "viewable"))
    # website_video stays at its hidden default.

    _as_anon(client)
    proof = _public_report(client, ctx["token"]).json()["website_proofs"][0]
    assert proof["frame_views"] == [
        {"view_path": f"/api/v1/proofs/artifacts/{frame['id']}/view", "mime_type": "image/jpeg"}
    ]
    assert proof["replay_path"] is None
    assert client.get(proof["frame_views"][0]["view_path"]).status_code == 200
    assert (
        client.get(f"/api/v1/proofs/website/{ctx['website_session_id']}/replay").status_code
        == 404
    )


def test_custom_mode_revokes_public_safe_replay_when_video_hidden(
    client: TestClient, mem_store: dict
) -> None:
    """(25) Revocation beats retention policy: a replay stored ``public_safe``
    is still denied anonymously in custom mode while website_video is hidden."""
    ctx = _publish_setup(client, mem_store, website=True)
    replay = _register_artifact(
        mem_store,
        artifact_type="website_replay_video",
        proof_type="website",
        proof_id=ctx["website_session_id"],
        project_id=ctx["project_id"],
        policy="public_safe",
    )
    # Sanity: legacy recruiter-safe behavior serves the public_safe replay.
    _as_anon(client)
    assert client.get(f"/api/v1/proofs/artifacts/{replay['id']}/view").status_code == 200

    _as_user(client, USER_ID)
    _set_mode(client, MODE_CUSTOM)  # website_video defaults to hidden

    _as_anon(client)
    assert client.get(f"/api/v1/proofs/artifacts/{replay['id']}/view").status_code == 404
    assert (
        client.get(f"/api/v1/proofs/website/{ctx['website_session_id']}/replay").status_code
        == 404
    )


# ═══════════════════════════════════════════════════════════════════════════════
# DOCUMENTS — summary / viewable / download as a separate grant
# ═══════════════════════════════════════════════════════════════════════════════


def _document_setup(client: TestClient, mem_store: dict) -> tuple[dict, dict]:
    """Published project with a document whose original IS retained."""
    ctx = _publish_setup(client, mem_store, document=True)
    doc_artifact = _register_artifact(
        mem_store,
        artifact_type="document_original",
        proof_type="document",
        proof_id=ctx["document_id"],
        project_id=ctx["project_id"],
        mime="application/pdf",
        data=b"original-doc-bytes",
        file_name="report.pdf",
    )
    return ctx, doc_artifact


def test_document_summary_has_no_view_paths(client: TestClient, mem_store: dict) -> None:
    """(26) Summary state (the default): title only — no shared_view and no
    open/download path strings anywhere in the response."""
    ctx, doc_artifact = _document_setup(client, mem_store)
    _as_anon(client)
    res = _public_report(client, ctx["token"])
    doc = res.json()["documents"][0]
    assert doc["title"] == _DOC_TITLE
    assert doc["disclosure"] == "summary"
    assert doc["shared_view"] is None
    assert f"/api/v1/proofs/artifacts/{doc_artifact['id']}" not in res.text
    assert "download_path" not in json.dumps(res.json()["documents"])


def test_document_viewable_opens_via_artifact_route(client: TestClient, mem_store: dict) -> None:
    """(27) Viewable + retained original → shared_view.open_path renders and
    serves the anonymous recruiter through the gated artifact route."""
    ctx, doc_artifact = _document_setup(client, mem_store)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("document", ctx["document_id"], "viewable"))

    _as_anon(client)
    doc = _public_report(client, ctx["token"]).json()["documents"][0]
    assert doc["disclosure"] == "viewable"
    view = doc["shared_view"]
    assert view["open_path"] == f"/api/v1/proofs/artifacts/{doc_artifact['id']}/view"
    assert view["can_download"] is False
    opened = client.get(view["open_path"])
    assert opened.status_code == 200
    assert opened.content == b"original-doc-bytes"


def test_document_view_does_not_imply_download(client: TestClient, mem_store: dict) -> None:
    """(28) View and download are separate grants: with only ``document:
    viewable`` the view route 200s while the download route 404s."""
    ctx, doc_artifact = _document_setup(client, mem_store)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("document", ctx["document_id"], "viewable"))

    _as_anon(client)
    assert client.get(f"/api/v1/proofs/artifacts/{doc_artifact['id']}/view").status_code == 200
    assert (
        client.get(f"/api/v1/proofs/artifacts/{doc_artifact['id']}/download").status_code == 404
    )
    doc = _public_report(client, ctx["token"]).json()["documents"][0]
    assert doc["shared_view"]["download_path"] is None


def test_document_download_grant_opens_download_route(
    client: TestClient, mem_store: dict
) -> None:
    """(29) The explicit ``document_download: downloadable`` grant (on top of
    viewable) opens the download route and advertises download_path."""
    ctx, doc_artifact = _document_setup(client, mem_store)
    _set_mode(client, MODE_CUSTOM)
    _apply(
        client,
        _ov("document", ctx["document_id"], "viewable"),
        _ov("document_download", ctx["document_id"], "downloadable"),
    )

    _as_anon(client)
    doc = _public_report(client, ctx["token"]).json()["documents"][0]
    assert doc["shared_view"]["can_download"] is True
    assert (
        doc["shared_view"]["download_path"]
        == f"/api/v1/proofs/artifacts/{doc_artifact['id']}/download"
    )
    download = client.get(doc["shared_view"]["download_path"])
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]


def test_document_signed_url_respects_gate_and_ttl(client: TestClient, mem_store: dict) -> None:
    """(30) The signed-url route rides the same gate: mints (TTL ≤ 300 s, no
    storage path) for a viewable document, 404s once the document is hidden."""
    ctx, doc_artifact = _document_setup(client, mem_store)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("document", ctx["document_id"], "viewable"))

    _as_anon(client)
    minted = client.get(f"/api/v1/proofs/artifacts/{doc_artifact['id']}/signed-url")
    assert minted.status_code == 200
    payload = minted.json()
    assert payload["expires_in_seconds"] <= 300
    assert doc_artifact["storage_path"] not in payload["signed_url"]

    _as_user(client, USER_ID)
    _apply(client, _ov("document", ctx["document_id"], "hidden"))
    _as_anon(client)
    assert (
        client.get(f"/api/v1/proofs/artifacts/{doc_artifact['id']}/signed-url").status_code
        == 404
    )


def test_document_rehidden_revokes_view_url_immediately(
    client: TestClient, mem_store: dict
) -> None:
    """(31) Flipping a viewable document to hidden 404s its previously working
    view URL on the very next request — no grace, no cache."""
    ctx, doc_artifact = _document_setup(client, mem_store)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("document", ctx["document_id"], "viewable"))
    view_path = f"/api/v1/proofs/artifacts/{doc_artifact['id']}/view"

    _as_anon(client)
    assert client.get(view_path).status_code == 200

    _as_user(client, USER_ID)
    _apply(client, _ov("document", ctx["document_id"], "hidden"))
    _as_anon(client)
    assert client.get(view_path).status_code == 404
    res = _public_report(client, ctx["token"])
    assert _DOC_TITLE not in res.text  # hidden document absent from the report too


def test_document_download_without_viewable_is_not_downloadable(
    client: TestClient, mem_store: dict
) -> None:
    """(extra) ``document_download`` without a viewable document is inert: the
    editor reports effective_downloadable false and the route stays closed."""
    ctx, doc_artifact = _document_setup(client, mem_store)
    _set_mode(client, MODE_CUSTOM)
    res = _apply(client, _ov("document_download", ctx["document_id"], "downloadable"))
    doc_entry = res.json()["projects"][0]["documents"][0]
    assert doc_entry["effective"] == "summary"  # never elevated by the download grant
    assert doc_entry["effective_downloadable"] is False

    _as_anon(client)
    assert (
        client.get(f"/api/v1/proofs/artifacts/{doc_artifact['id']}/download").status_code == 404
    )
    assert client.get(f"/api/v1/proofs/artifacts/{doc_artifact['id']}/view").status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# DEFENSE / VIDEO
# ═══════════════════════════════════════════════════════════════════════════════


def _defense_setup(client: TestClient, mem_store: dict) -> tuple[dict, dict, dict]:
    """Published defended project with retained transcript + video artifacts."""
    ctx = _publish_setup(client, mem_store, defense=True)
    transcript = _register_artifact(
        mem_store,
        artifact_type="defense_transcript",
        proof_type="project_defense",
        proof_id=ctx["session_id"],
        project_id=ctx["project_id"],
        mime="text/plain",
        data=b"transcript-bytes",
    )
    video = _register_artifact(
        mem_store,
        artifact_type="defense_video",
        proof_type="project_defense",
        proof_id=ctx["session_id"],
        project_id=ctx["project_id"],
        mime="video/webm",
        data=b"defense-video-bytes",
    )
    return ctx, transcript, video


def test_defense_summary_public_but_media_absent_by_default(
    client: TestClient, mem_store: dict
) -> None:
    """(32) Recruiter-safe default: the defense summary is public while the
    transcript/recording descriptors stay null and their artifacts closed."""
    ctx, transcript, video = _defense_setup(client, mem_store)
    _as_anon(client)
    body = _public_report(client, ctx["token"]).json()
    assert body["project_defense_analysis"] is not None
    assert body["evidence_package"]["project_defense_completed"] is True
    assert body["defense_transcript_view"] is None
    assert body["defense_video_view"] is None
    assert client.get(f"/api/v1/proofs/artifacts/{transcript['id']}/view").status_code == 404
    assert client.get(f"/api/v1/proofs/artifacts/{video['id']}/view").status_code == 404


def test_defense_transcript_grant_is_independent_of_video(
    client: TestClient, mem_store: dict
) -> None:
    """(33)+(34) Granting the transcript alone attaches its descriptor and
    opens its artifact, while the (still hidden) defense video stays a null
    descriptor with a closed artifact route."""
    ctx, transcript, video = _defense_setup(client, mem_store)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("defense_transcript", ctx["project_id"], "viewable"))

    _as_anon(client)
    body = _public_report(client, ctx["token"]).json()
    assert body["defense_transcript_view"] == {
        "view_path": f"/api/v1/proofs/artifacts/{transcript['id']}/view",
        "mime_type": "text/plain",
    }
    assert body["defense_video_view"] is None
    opened = client.get(body["defense_transcript_view"]["view_path"])
    assert opened.status_code == 200
    assert opened.content == b"transcript-bytes"
    assert client.get(f"/api/v1/proofs/artifacts/{video['id']}/view").status_code == 404


def test_defense_transcript_rehide_revokes_route_immediately(
    client: TestClient, mem_store: dict
) -> None:
    """(35) Flipping the transcript back to hidden revokes the artifact route
    on the very next request and removes the descriptor."""
    ctx, transcript, _video = _defense_setup(client, mem_store)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("defense_transcript", ctx["project_id"], "viewable"))
    view_path = f"/api/v1/proofs/artifacts/{transcript['id']}/view"

    _as_anon(client)
    assert client.get(view_path).status_code == 200

    _as_user(client, USER_ID)
    _apply(client, _ov("defense_transcript", ctx["project_id"], "hidden"))
    _as_anon(client)
    assert client.get(view_path).status_code == 404
    assert _public_report(client, ctx["token"]).json()["defense_transcript_view"] is None


def test_video_proof_routes_follow_video_full_aspect(
    client: TestClient, mem_store: dict
) -> None:
    """(extra) First-class Video Proof rows ride the same policy: recruiter-safe
    keeps the legacy public_safe flag; custom mode requires video_full
    viewable; the owner always passes."""
    ctx = _publish_setup(client, mem_store)
    proof_id = str(uuid4())
    mem_store.setdefault("video_proofs", {})[proof_id] = {
        "id": proof_id,
        "user_id": USER_ID,
        "project_id": ctx["project_id"],
        "title": "Demo video",
        "public_safe": True,
        "status": "uploaded",
        "source_kind": "uploaded_demo",
        "transcript_status": "pending",
        "frames_status": "pending",
        "analysis_status": "pending",
    }

    _as_anon(client)
    assert client.get(f"/api/v1/proofs/video/{proof_id}").status_code == 200  # legacy flag

    _as_user(client, USER_ID)
    _set_mode(client, MODE_CUSTOM)  # video_full defaults hidden → revoked
    _as_anon(client)
    assert client.get(f"/api/v1/proofs/video/{proof_id}").status_code == 404

    _as_user(client, USER_ID)
    _apply(client, _ov("video_full", ctx["project_id"], "viewable"))
    _as_anon(client)
    assert client.get(f"/api/v1/proofs/video/{proof_id}").status_code == 200

    # Owner access never depends on the public policy.
    _as_user(client, USER_ID)
    _apply(client, _ov("video_full", ctx["project_id"], "hidden"))
    assert client.get(f"/api/v1/proofs/video/{proof_id}").status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# REPORTS — hidden tokens, section omission, honest counts
# ═══════════════════════════════════════════════════════════════════════════════


def _seed_legacy_report(mem_store: dict, project_id: str, token: str = "legacy-token-063") -> None:
    mem_store.setdefault("vbr_reports", {})["legacy-report-063"] = {
        "id": "legacy-report-063",
        "project_id": project_id,
        "status": "published",
        "public_token": token,
        "published_at": "2026-01-01T00:00:00+00:00",
        "body": {"summary": {"project_title": "Legacy"}, "claims": []},
    }


def test_hidden_report_404s_canonical_and_legacy_tokens(
    client: TestClient, mem_store: dict
) -> None:
    """(36) A ``report: hidden`` override 404s both the canonical token and a
    legacy token pointing at the same project; clearing it restores both."""
    ctx = _publish_setup(client, mem_store)
    _seed_legacy_report(mem_store, ctx["project_id"])
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("report", ctx["project_id"], "hidden"))

    _as_anon(client)
    assert _public_report(client, ctx["token"]).status_code == 404
    assert client.get("/api/v1/public/vbr/legacy-reports/legacy-token-063").status_code == 404

    # Clearing the override (visibility: null) restores both tokens unchanged.
    _as_user(client, USER_ID)
    _apply(client, _ov("report", ctx["project_id"], None))
    _as_anon(client)
    assert _public_report(client, ctx["token"]).status_code == 200
    assert client.get("/api/v1/public/vbr/legacy-reports/legacy-token-063").status_code == 200


def test_partial_disclosure_omits_sections_not_placeholders(
    client: TestClient, mem_store: dict
) -> None:
    """(37) A partially disclosed report OMITS hidden sections (github null,
    defense null, no cards) instead of rendering empty shells that still leak
    that the evidence exists."""
    ctx = _publish_setup(client, mem_store, defense=True, github_code_evidence=True)
    _set_mode(client, MODE_CUSTOM)
    _apply(
        client,
        _ov("github_repo", ctx["project_id"], "hidden"),
        _ov("defense_summary", ctx["project_id"], "hidden"),
    )

    _as_anon(client)
    body = _public_report(client, ctx["token"]).json()
    assert body["github_proof"] is None
    assert body["project_defense_analysis"] is None
    assert body["defense_answer_evidence"] == []
    assert body["project_defense_inspection"] == []
    assert body["evidence_package"]["github_proof_attached"] is False
    assert body["evidence_package"]["project_defense_completed"] is False
    assert body["evidence_package"]["video_defense_recorded"] is False
    source_types = {t["source_type"] for t in body["evidence_traces"]}
    assert "GitHub Proof" not in source_types
    assert "Project Defense" not in source_types
    # Hidden sources are stripped from skill-row source badges too.
    for row in body["skill_evidence"]:
        assert "GitHub Proof" not in row["supporting_sources"]
        assert "Project Defense" not in row["supporting_sources"]


def test_evidence_package_counts_match_effective_visibility(
    client: TestClient, mem_store: dict
) -> None:
    """(38) evidence_package counts reflect ONLY what the projection renders:
    a hidden document leaves documents_count, hidden website zeroes the
    website counts."""
    ctx = _publish_setup(client, mem_store, document=True, website=True)
    _as_anon(client)
    before = _public_report(client, ctx["token"]).json()["evidence_package"]
    assert before["documents_count"] == 1
    assert before["website_proofs_count"] == 1

    _as_user(client, USER_ID)
    _set_mode(client, MODE_CUSTOM)
    _apply(
        client,
        _ov("document", ctx["document_id"], "hidden"),
        _ov("website_summary", ctx["project_id"], "hidden"),
    )
    _as_anon(client)
    body = _public_report(client, ctx["token"]).json()
    assert body["documents"] == []
    assert body["website_proofs"] == []
    after = body["evidence_package"]
    assert after["documents_count"] == 0
    assert after["website_proofs_count"] == 0
    assert after["website_proofs_excluded_count"] == 0


def test_video_chips_empty_when_video_summary_hidden(
    client: TestClient, mem_store: dict
) -> None:
    """(39) ``video_summary: hidden`` empties the timestamped chips and their
    count while the defense summary itself stays public."""
    ctx = _publish_setup(client, mem_store, defense=True)
    _as_anon(client)
    before = _public_report(client, ctx["token"]).json()
    assert before["video_evidence_chips"]
    assert before["evidence_package"]["video_evidence_chip_count"] > 0

    _as_user(client, USER_ID)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("video_summary", ctx["project_id"], "hidden"))
    _as_anon(client)
    body = _public_report(client, ctx["token"]).json()
    assert body["video_evidence_chips"] == []
    assert body["evidence_package"]["video_evidence_chip_count"] == 0
    assert body["project_defense_analysis"] is not None  # defense summary unaffected


def test_legacy_token_honors_hidden_project(client: TestClient, mem_store: dict) -> None:
    """(40) A hidden PROJECT darkens its legacy report token too (project →
    report inheritance applies to every token generation)."""
    ctx = _publish_setup(client, mem_store)
    _seed_legacy_report(mem_store, ctx["project_id"])
    _as_anon(client)
    assert client.get("/api/v1/public/vbr/legacy-reports/legacy-token-063").status_code == 200

    _as_user(client, USER_ID)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("project", ctx["project_id"], "hidden"))
    _as_anon(client)
    assert client.get("/api/v1/public/vbr/legacy-reports/legacy-token-063").status_code == 404
    # Nothing was deleted — the token row is intact for when the student unhides.
    assert mem_store["vbr_reports"]["legacy-report-063"]["public_token"] == "legacy-token-063"


# ═══════════════════════════════════════════════════════════════════════════════
# CACHING / REVOCATION / VERSIONING
# ═══════════════════════════════════════════════════════════════════════════════


def test_disclosure_version_increments_and_surfaces_publicly(
    client: TestClient, mem_store: dict
) -> None:
    """(41) Every mode/override/reset write bumps disclosure_version exactly
    once, and public payloads carry the current version for cache keying."""
    ctx = _publish_setup(client, mem_store)
    _as_anon(client)
    v0 = _public_passport(client, ctx["slug"]).json()["disclosure_version"]
    assert _public_report(client, ctx["token"]).json()["disclosure_version"] == v0

    _as_user(client, USER_ID)
    v1 = _set_mode(client, MODE_CUSTOM).json()["passport"]["disclosure_version"]
    assert v1 == v0 + 1
    v2 = _apply(
        client,
        _ov("skill", "python", "hidden"),
        _ov("website_url", ctx["project_id"], "hidden"),
    ).json()["passport"]["disclosure_version"]
    assert v2 == v1 + 1  # ONE bump per batch
    v3 = client.post("/api/v1/student/vbr/passport/disclosure/reset").json()["passport"][
        "disclosure_version"
    ]
    assert v3 == v2 + 1

    _as_anon(client)
    assert _public_passport(client, ctx["slug"]).json()["disclosure_version"] == v3
    assert _public_report(client, ctx["token"]).json()["disclosure_version"] == v3


def test_disclosure_change_reflected_on_next_public_get(
    client: TestClient, mem_store: dict
) -> None:
    """(42) No server-side caching: a hide is live on the very next GET, and
    the un-hide equally so."""
    ctx = _publish_setup(client, mem_store)
    _as_anon(client)
    assert "Python" in _top_skill_names(_public_passport(client, ctx["slug"]).json())

    _as_user(client, USER_ID)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("skill", "python", "hidden"))
    _as_anon(client)
    assert "Python" not in _top_skill_names(_public_passport(client, ctx["slug"]).json())

    _as_user(client, USER_ID)
    _apply(client, _ov("skill", "python", None))
    _as_anon(client)
    assert "Python" in _top_skill_names(_public_passport(client, ctx["slug"]).json())


def test_rehide_revokes_media_on_fresh_request(client: TestClient, mem_store: dict) -> None:
    """(43) Media routes re-evaluate the policy per request: grant → 200,
    re-hide → immediate 404, re-grant → 200 again."""
    ctx = _publish_setup(client, mem_store, website=True)
    frame = _register_artifact(
        mem_store,
        artifact_type="website_frame",
        proof_type="website",
        proof_id=ctx["website_session_id"],
        project_id=ctx["project_id"],
        mime="image/jpeg",
    )
    view_path = f"/api/v1/proofs/artifacts/{frame['id']}/view"
    _set_mode(client, MODE_CUSTOM)

    _apply(client, _ov("website_frames", ctx["project_id"], "viewable"))
    _as_anon(client)
    assert client.get(view_path).status_code == 200

    _as_user(client, USER_ID)
    _apply(client, _ov("website_frames", ctx["project_id"], "hidden"))
    _as_anon(client)
    assert client.get(view_path).status_code == 404

    _as_user(client, USER_ID)
    _apply(client, _ov("website_frames", ctx["project_id"], "viewable"))
    _as_anon(client)
    assert client.get(view_path).status_code == 200


def test_public_payloads_never_leak_hidden_content_or_storage_fields(
    client: TestClient, mem_store: dict
) -> None:
    """(44) Leak scan across the public passport, report, and skill report:
    hidden project title, hidden skill name, hidden document title, storage
    internals, and hidden raw URLs never appear in any response text.

    The policy governs skill LABELS, lists, chips, and traces — not the
    student's own free-text prose — so the fixture keeps its prose neutral to
    pin the label contract exactly."""
    ctx_a = _publish_setup(
        client,
        mem_store,
        document=True,
        website=True,
        description="A platform that tracks student skill evidence across proof sources.",
        student_role="I built the backend API and the dashboard.",
    )
    ctx_b = _make_project(
        client,
        mem_store,
        title="Hidden Project Beta",
        repo_owner="betaorg",
        repo_name="beta-repo",
        claimed_skills=["Go"],
    )
    _publish_report(client, ctx_b["project_id"])
    _register_artifact(
        mem_store,
        artifact_type="document_original",
        proof_type="document",
        proof_id=ctx_a["document_id"],
        project_id=ctx_a["project_id"],
    )

    _set_mode(client, MODE_CUSTOM)
    _apply(
        client,
        _ov("project", ctx_b["project_id"], "hidden"),
        _ov("skill", "react", "hidden"),
        _ov("document", ctx_a["document_id"], "hidden"),
        _ov("website_url", ctx_a["project_id"], "hidden"),
    )

    _as_anon(client)
    responses = [
        _public_passport(client, ctx_a["slug"]),
        _public_report(client, ctx_a["token"]),
        _public_skill_report(client, ctx_a["slug"], "python"),
    ]
    forbidden = [
        "Hidden Project Beta",  # hidden project title
        "beta-repo",  # hidden project's repo identity
        "React",  # hidden skill name
        _DOC_TITLE,  # hidden document title
        "demo.example.com",  # hidden website URL
        "storage_path",
        "/storage/v1/object",
        "signed_url",
    ]
    for res in responses:
        assert res.status_code == 200, res.text
        for needle in forbidden:
            assert needle not in res.text, f"{needle!r} leaked in {res.request.url.path}"


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT, PERSISTENCE, VALIDATION, PRESETS, RESOLVER UNITS
# ═══════════════════════════════════════════════════════════════════════════════


def test_audit_rows_written_per_change(client: TestClient, mem_store: dict) -> None:
    """Every mode switch and override change writes one audit row carrying the
    previous and new values."""
    ctx = _publish_setup(client, mem_store)
    assert not mem_store.get("passport_disclosure_audit")

    _set_mode(client, MODE_CUSTOM)
    audits = list(mem_store["passport_disclosure_audit"].values())
    assert len(audits) == 1
    assert audits[0]["resource_type"] == "passport_mode"
    assert audits[0]["previous_visibility"] == MODE_RECRUITER_SAFE
    assert audits[0]["new_visibility"] == MODE_CUSTOM

    _apply(
        client,
        _ov("skill", "python", "hidden"),
        _ov("project", ctx["project_id"], "hidden"),
    )
    audits = list(mem_store["passport_disclosure_audit"].values())
    assert len(audits) == 3
    skill_audit = next(a for a in audits if a["resource_type"] == "skill")
    assert skill_audit["previous_visibility"] is None
    assert skill_audit["new_visibility"] == "hidden"
    assert skill_audit["user_id"] == USER_ID

    # Changing an existing override records its previous value.
    _apply(client, _ov("skill", "python", "visible"))
    audits = list(mem_store["passport_disclosure_audit"].values())
    assert len(audits) == 4
    latest = max(audits, key=lambda a: a["changed_at"])
    assert latest["previous_visibility"] == "hidden"
    assert latest["new_visibility"] == "visible"


def test_granular_settings_survive_private_public_round_trip(
    client: TestClient, mem_store: dict
) -> None:
    """Custom overrides survive the master Private → Public round trip intact:
    nothing is deleted while Private, and republishing restores the exact same
    custom behavior without re-configuration."""
    ctx = _publish_setup(client, mem_store)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("skill", "python", "hidden"))
    override_rows = dict(mem_store["passport_disclosure_overrides"])

    _unpublish_passport(client)
    assert mem_store["passport_disclosure_overrides"] == override_rows  # nothing deleted
    body = _get_disclosure(client).json()
    assert body["passport"]["mode"] == MODE_CUSTOM
    assert body["passport"]["override_count"] == 1

    _publish_passport(client)
    _as_anon(client)
    passport = _public_passport(client, ctx["slug"]).json()
    assert "Python" not in _top_skill_names(passport)  # custom behavior restored
    assert "React" in _top_skill_names(passport)


def test_invalid_disclosure_writes_are_422(client: TestClient, mem_store: dict) -> None:
    """Unknown resource types, out-of-vocabulary visibility values, unknown
    modes, and unknown presets are all rejected 422 before any write."""
    ctx = _publish_setup(client, mem_store)

    res = _apply(client, _ov("not_a_type", ctx["project_id"], "hidden"))
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "disclosure_invalid"

    res = _apply(client, _ov("project", ctx["project_id"], "downloadable"))
    assert res.status_code == 422
    assert res.json()["detail"]["field"] == "visibility"

    # A batch with one bad change writes NOTHING (validated before any write).
    version_before = _get_disclosure(client).json()["passport"]["disclosure_version"]
    res = _apply(
        client,
        _ov("skill", "python", "hidden"),
        _ov("skill", "react", "bogus-state"),
    )
    assert res.status_code == 422
    body = _get_disclosure(client).json()
    assert body["passport"]["override_count"] == 0
    assert body["passport"]["disclosure_version"] == version_before

    assert _set_mode(client, "wide_open").status_code == 422
    preset = client.post(
        "/api/v1/student/vbr/passport/disclosure/preset", json={"preset": "everything"}
    )
    assert preset.status_code == 422


def test_presets_apply_safe_override_sets(client: TestClient, mem_store: dict) -> None:
    """Presets configure the CURRENT projects: maximum_privacy withholds repo
    identity + live URL, portfolio_open opens repos/frames/documents while
    keeping recordings hidden, and recruiter_safe returns to the default mode."""
    ctx = _publish_setup(client, mem_store, document=True, website=True)

    res = client.post(
        "/api/v1/student/vbr/passport/disclosure/preset", json={"preset": "maximum_privacy"}
    )
    assert res.status_code == 200
    assert res.json()["passport"]["mode"] == MODE_CUSTOM
    _as_anon(client)
    body = _public_report(client, ctx["token"]).json()
    assert body["github_proof"]["repo_url"] is None
    assert body["github_proof"]["disclosure"] == "summary"
    assert body["website_proofs"][0]["target_website"] == ""

    _as_user(client, USER_ID)
    res = client.post(
        "/api/v1/student/vbr/passport/disclosure/preset", json={"preset": "portfolio_open"}
    )
    assert res.status_code == 200
    _as_anon(client)
    body = _public_report(client, ctx["token"]).json()
    assert body["github_proof"]["repo_url"] == _REPO_URL
    assert body["website_proofs"][0]["replay_path"] is None  # recordings stay hidden

    _as_user(client, USER_ID)
    res = client.post(
        "/api/v1/student/vbr/passport/disclosure/preset", json={"preset": "recruiter_safe"}
    )
    assert res.json()["passport"]["mode"] == MODE_RECRUITER_SAFE


def test_resolver_fails_closed_on_unknown_inputs(mem_store: dict) -> None:
    """Unit: the resolver's fail-closed edges — unknown resource types resolve
    Hidden, unknown stored modes degrade to recruiter_safe, stored overrides
    with invalid values are dropped on read, and dependent aspects require
    their parents."""
    seed_published_passport(mem_store, USER_ID)
    project_id = str(uuid4())

    disclosure = EffectiveDisclosure(
        user_id=USER_ID,
        passport_public=True,
        mode="future_mode",  # unknown → degrades to recruiter_safe
        disclosure_version=1,
        overrides={},
    )
    assert disclosure.mode == MODE_RECRUITER_SAFE
    assert disclosure.aspect(project_id, "not_an_aspect") == HIDDEN

    # Invalid stored rows (bad type / bad value) are dropped on read.
    mem_store.setdefault("passport_disclosure_overrides", {})["bad-1"] = {
        "id": "bad-1",
        "user_id": USER_ID,
        "resource_type": "project",
        "resource_key": project_id,
        "visibility": "downloadable",  # not valid for project
    }
    mem_store["passport_disclosure_overrides"]["bad-2"] = {
        "id": "bad-2",
        "user_id": USER_ID,
        "resource_type": "mystery",
        "resource_key": project_id,
        "visibility": "hidden",
    }
    loaded = load_effective_disclosure(mem_store, USER_ID)
    assert loaded.configured("project", project_id) is None
    assert loaded.project_visible(project_id) is True

    # Dependent aspects: exact lines require a VIEWABLE repo; transcript/video
    # require the defense summary; url/frames/video require the website proof.
    custom = EffectiveDisclosure(
        user_id=USER_ID,
        passport_public=True,
        mode=MODE_CUSTOM,
        disclosure_version=1,
        overrides={
            ("github_repo", project_id): "summary",
            ("github_lines", project_id): "viewable",
            ("defense_summary", project_id): "hidden",
            ("defense_transcript", project_id): "viewable",
            ("website_summary", project_id): "hidden",
            ("website_url", project_id): "visible",
        },
    )
    assert custom.aspect(project_id, "github_lines") == HIDDEN
    assert custom.aspect(project_id, "defense_transcript") == HIDDEN
    assert custom.aspect(project_id, "website_url") == HIDDEN

    # Recruiter-safe defaults must stay in lockstep with the closed vocabulary.
    assert set(RECRUITER_SAFE_DEFAULTS) == set(RESOURCE_TYPES)
    for rtype, default in RECRUITER_SAFE_DEFAULTS.items():
        assert default in RESOURCE_TYPES[rtype], rtype


def test_artifact_gate_units_owner_unmapped_and_download(mem_store: dict) -> None:
    """Unit: ``artifact_action_allowed`` — not-retained always denied; owner
    always allowed; unmapped artifact types fall back to the retention policy;
    custom-mode download requires the explicit download grant."""
    seed_published_passport(mem_store, USER_ID)
    project_id = str(uuid4())
    document_key = str(uuid4())
    base = {
        "retained": True,
        "owner_user_id": USER_ID,
        "artifact_type": "document_original",
        "proof_id": document_key,
        "project_id": project_id,
        "access_policy": "owner_only",
    }

    assert not disclosure_service.artifact_action_allowed(
        mem_store, {**base, "retained": False}, USER_ID
    )
    assert disclosure_service.artifact_action_allowed(mem_store, base, USER_ID, action="download")
    # Anonymous, recruiter-safe: owner_only stays closed.
    assert not disclosure_service.artifact_action_allowed(mem_store, base, None)

    # Custom grant: view opens, download still requires its own grant.
    apply_disclosure_overrides(mem_store, USER_ID, [_ov("document", document_key, "viewable")])
    disclosure_service.set_disclosure_mode(mem_store, USER_ID, MODE_CUSTOM)
    assert disclosure_service.artifact_action_allowed(mem_store, base, None, action="view")
    assert not disclosure_service.artifact_action_allowed(mem_store, base, None, action="download")
    apply_disclosure_overrides(
        mem_store, USER_ID, [_ov("document_download", document_key, "downloadable")]
    )
    assert disclosure_service.artifact_action_allowed(mem_store, base, None, action="download")

    # An unmapped artifact type keeps the pre-063 retention policy authority.
    unmapped = {**base, "artifact_type": "mystery_type", "access_policy": "public_safe"}
    assert disclosure_service.artifact_action_allowed(mem_store, unmapped, None)


# ═══════════════════════════════════════════════════════════════════════════════
# FULL ACCESS (migration 064) — the deliberate "everything supported is public"
# mode. Matrix: maximum resolution, superset guarantee, private/owner/cross-
# tenant boundaries, per-route reachability, persistence, and leak scans.
# ═══════════════════════════════════════════════════════════════════════════════


def _full_setup(client: TestClient, mem_store: dict) -> dict:
    """Published passport + project carrying every artifact family at once."""
    ctx = _publish_setup(
        client, mem_store, document=True, website=True, github_code_evidence=True
    )
    ctx["frame"] = _register_artifact(
        mem_store,
        artifact_type="website_frame",
        proof_type="website",
        proof_id=ctx["website_session_id"],
        project_id=ctx["project_id"],
        mime="image/jpeg",
        data=b"frame-bytes",
    )
    ctx["replay"] = _register_artifact(
        mem_store,
        artifact_type="website_replay_video",
        proof_type="website",
        proof_id=ctx["website_session_id"],
        project_id=ctx["project_id"],
        mime="video/webm",
        data=b"replay-bytes",
    )
    ctx["doc_artifact"] = _register_artifact(
        mem_store,
        artifact_type="document_original",
        proof_type="document",
        proof_id=ctx["document_id"],
        project_id=ctx["project_id"],
        mime="application/pdf",
        data=b"original-doc-bytes",
        file_name="report.pdf",
    )
    return ctx


def _seed_video_proof(
    mem_store: dict,
    *,
    owner: str = USER_ID,
    project_id: str | None = None,
    public_safe: bool = False,
) -> dict:
    """Minimal first-class Video Proof row with one transcript segment + frame."""
    proof_id = str(uuid4())
    row = {
        "id": proof_id,
        "user_id": owner,
        "project_id": project_id,
        "title": "Demo walkthrough",
        "source_kind": "uploaded_demo",
        "status": "analyzed",
        "transcript_status": "ready",
        "frames_status": "ready",
        "analysis_status": "ready",
        "public_safe": public_safe,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    mem_store.setdefault("video_proofs", {})[proof_id] = row
    seg_id = str(uuid4())
    mem_store.setdefault("video_proof_transcript_segments", {})[seg_id] = {
        "id": seg_id,
        "video_proof_id": proof_id,
        "seq": 0,
        "start_s": 0.0,
        "end_s": 4.0,
        "text": "Here I walk through the deployment pipeline.",
    }
    frame_id = str(uuid4())
    mem_store.setdefault("video_proof_frames", {})[frame_id] = {
        "id": frame_id,
        "video_proof_id": proof_id,
        "timestamp_s": 2.0,
        "activity_summary": "Terminal showing a successful deploy.",
    }
    return row


# ── Resolution: maximum, closed-vocabulary-legal, and a strict superset ───────


def test_full_access_resolves_every_node_to_its_maximum(mem_store: dict) -> None:
    """(F1) Every resource type resolves to ``FULL_ACCESS_DEFAULTS``, every one
    of those values is legal for its type, and the map covers the whole closed
    vocabulary — no node can silently fall through to Hidden."""
    project_id = str(uuid4())
    full = EffectiveDisclosure(
        user_id=USER_ID,
        passport_public=True,
        mode=MODE_FULL_ACCESS,
        disclosure_version=1,
        overrides={},
    )

    assert set(FULL_ACCESS_DEFAULTS) == set(RESOURCE_TYPES)
    for rtype, value in FULL_ACCESS_DEFAULTS.items():
        assert value in RESOURCE_TYPES[rtype], rtype

    for rtype in PROJECT_ASPECTS:
        assert full.aspect(project_id, rtype) == FULL_ACCESS_DEFAULTS[rtype], rtype
    assert full.project_visible(project_id)
    assert full.report_visible(project_id)
    assert full.project_card_visible(project_id)
    assert full.skill_group_visible("Backend")
    assert full.skill_visible("Backend", "python")
    assert full.project_skill_visible(project_id, "Backend", "python")

    document_key = str(uuid4())
    assert full.document_state(project_id, document_key) == VIEWABLE
    assert full.document_downloadable(project_id, document_key) is True

    # Unknown resource types still fail closed.
    assert full.aspect(project_id, "not_an_aspect") == HIDDEN


def test_full_access_is_a_superset_of_recruiter_safe(mem_store: dict) -> None:
    """(F2) For every node, full access is at least as open as recruiter-safe —
    the mode can never narrow what the legacy default already exposed."""
    rank = {HIDDEN: 0, SUMMARY: 1, VISIBLE: 1, VIEWABLE: 2, "downloadable": 3}
    for rtype, safe_value in RECRUITER_SAFE_DEFAULTS.items():
        assert rank[FULL_ACCESS_DEFAULTS[rtype]] >= rank[safe_value], rtype


def test_full_access_ignores_overrides_and_restores_them_on_custom(
    client: TestClient, mem_store: dict
) -> None:
    """(F3) Stored overrides stay dormant under full access and are reapplied
    verbatim on the way back to custom — the student's granular policy is never
    destroyed by opting into openness."""
    ctx = _full_setup(client, mem_store)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("project", ctx["project_id"], "hidden"))
    assert _get_disclosure(client).json()["passport"]["override_count"] == 1

    _as_anon(client)
    assert _featured_by_token(_public_passport(client, ctx["slug"]).json(), ctx["token"]) is None

    _as_user(client, USER_ID)
    assert _set_mode(client, MODE_FULL_ACCESS).status_code == 200
    body = _get_disclosure(client).json()["passport"]
    assert body["mode"] == MODE_FULL_ACCESS
    assert body["custom_overrides_active"] is False
    assert body["override_count"] == 1  # kept, not deleted

    _as_anon(client)
    assert _featured_by_token(_public_passport(client, ctx["slug"]).json(), ctx["token"])

    _as_user(client, USER_ID)
    _set_mode(client, MODE_CUSTOM)
    _as_anon(client)
    assert _featured_by_token(_public_passport(client, ctx["slug"]).json(), ctx["token"]) is None


# ── Public reachability of every supported evidence family ───────────────────


def test_full_access_opens_frames_replay_document_view_and_download(
    client: TestClient, mem_store: dict
) -> None:
    """(F4) Anonymous visitor gets every website + document capability at once:
    frame descriptors serve, the replay route streams, the document is viewable
    AND downloadable, and each direct route agrees with the page payload."""
    ctx = _full_setup(client, mem_store)
    _set_mode(client, MODE_FULL_ACCESS)

    _as_anon(client)
    report = _public_report(client, ctx["token"]).json()

    proof = report["website_proofs"][0]
    assert proof["frame_views"] == [
        {
            "view_path": f"/api/v1/proofs/artifacts/{ctx['frame']['id']}/view",
            "mime_type": "image/jpeg",
        }
    ]
    assert proof["replay_path"] == f"/api/v1/proofs/website/{ctx['website_session_id']}/replay"
    assert client.get(proof["frame_views"][0]["view_path"]).status_code == 200
    replay_res = client.get(proof["replay_path"])
    assert replay_res.status_code == 200
    assert replay_res.content == b"replay-bytes"

    doc = report["documents"][0]
    assert doc["disclosure"] == VIEWABLE
    view = doc["shared_view"]
    assert view["can_download"] is True
    assert view["open_path"] == f"/api/v1/proofs/artifacts/{ctx['doc_artifact']['id']}/view"
    assert view["download_path"] == f"/api/v1/proofs/artifacts/{ctx['doc_artifact']['id']}/download"

    opened = client.get(view["open_path"])
    assert opened.status_code == 200
    assert opened.content == b"original-doc-bytes"
    downloaded = client.get(view["download_path"])
    assert downloaded.status_code == 200
    assert downloaded.content == b"original-doc-bytes"
    assert 'attachment; filename="report.pdf"' in downloaded.headers["content-disposition"]


def test_full_access_opens_code_evidence_and_exact_lines(
    client: TestClient, mem_store: dict
) -> None:
    """(F5) Repository identity and exact file/line references both resolve to
    Viewable, so code evidence renders with its blob links intact."""
    ctx = _full_setup(client, mem_store)
    _set_mode(client, MODE_FULL_ACCESS)

    _as_anon(client)
    report = _public_report(client, ctx["token"])
    assert report.status_code == 200
    assert _REPO_URL in report.text
    assert _BLOB_PREFIX in report.text


def test_full_access_opens_video_proof_detail_transcript_and_frames(
    client: TestClient, mem_store: dict
) -> None:
    """(F6) The first-class Video Proof routes (detail / transcript / frames)
    all open for an anonymous visitor when the proof belongs to a project."""
    ctx = _full_setup(client, mem_store)
    proof = _seed_video_proof(mem_store, project_id=ctx["project_id"])
    _set_mode(client, MODE_FULL_ACCESS)

    _as_anon(client)
    detail = client.get(f"/api/v1/proofs/video/{proof['id']}")
    assert detail.status_code == 200
    transcript = client.get(f"/api/v1/proofs/video/{proof['id']}/transcript")
    assert transcript.status_code == 200
    assert transcript.json()["segment_count"] == 1
    frames = client.get(f"/api/v1/proofs/video/{proof['id']}/frames")
    assert frames.status_code == 200
    assert frames.json()["frame_count"] == 1


def test_full_access_video_playback_artifacts_open_but_never_download(
    client: TestClient, mem_store: dict
) -> None:
    """(F7) Download is modeled for documents ONLY. A video/replay artifact
    streams inline under full access but its download route stays 404 — the
    closed vocabulary has no download state for recordings."""
    ctx = _full_setup(client, mem_store)
    original = _register_artifact(
        mem_store,
        artifact_type="video_proof_original",
        proof_type="video",
        proof_id=str(uuid4()),
        project_id=ctx["project_id"],
        mime="video/mp4",
        data=b"video-bytes",
    )
    _set_mode(client, MODE_FULL_ACCESS)

    _as_anon(client)
    assert client.get(f"/api/v1/proofs/artifacts/{original['id']}/view").status_code == 200
    assert client.get(f"/api/v1/proofs/artifacts/{original['id']}/download").status_code == 404
    assert client.get(f"/api/v1/proofs/artifacts/{ctx['replay']['id']}/view").status_code == 200
    assert client.get(f"/api/v1/proofs/artifacts/{ctx['replay']['id']}/download").status_code == 404


# ── Boundaries that full access must NEVER cross ─────────────────────────────


def test_private_passport_denies_everything_even_in_full_access(
    client: TestClient, mem_store: dict
) -> None:
    """(F8) The master switch stays above the mode: unpublishing while in full
    access closes the passport, the report, every artifact route, and the video
    proof routes."""
    ctx = _full_setup(client, mem_store)
    proof = _seed_video_proof(
        mem_store, project_id=ctx["project_id"], public_safe=True
    )
    _set_mode(client, MODE_FULL_ACCESS)

    _as_anon(client)
    assert client.get(f"/api/v1/proofs/artifacts/{ctx['doc_artifact']['id']}/view").status_code == 200

    _as_user(client, USER_ID)
    assert _unpublish_passport(client).status_code == 200

    _as_anon(client)
    assert _public_passport(client, ctx["slug"]).status_code == 404
    assert _public_report(client, ctx["token"]).status_code == 404
    assert client.get(f"/api/v1/proofs/artifacts/{ctx['doc_artifact']['id']}/view").status_code == 404
    assert (
        client.get(f"/api/v1/proofs/artifacts/{ctx['doc_artifact']['id']}/download").status_code
        == 404
    )
    assert client.get(f"/api/v1/proofs/artifacts/{ctx['frame']['id']}/view").status_code == 404
    assert (
        client.get(f"/api/v1/proofs/website/{ctx['website_session_id']}/replay").status_code == 404
    )
    assert client.get(f"/api/v1/proofs/video/{proof['id']}").status_code == 404
    assert client.get(f"/api/v1/proofs/video/{proof['id']}/transcript").status_code == 404
    assert client.get(f"/api/v1/proofs/video/{proof['id']}/frames").status_code == 404


def test_full_access_never_reaches_another_tenant(
    client: TestClient, mem_store: dict
) -> None:
    """(F9) Full access is scoped to its own owner: another student's artifacts
    and video proofs stay 404, and their still-recruiter-safe passport keeps its
    own narrower policy."""
    ctx = _full_setup(client, mem_store)
    _set_mode(client, MODE_FULL_ACCESS)

    seed_published_passport(mem_store, OTHER_USER_ID)
    other_doc = _register_artifact(
        mem_store,
        artifact_type="document_original",
        proof_type="document",
        proof_id=str(uuid4()),
        project_id=str(uuid4()),
        owner=OTHER_USER_ID,
        mime="application/pdf",
        data=b"other-student-doc",
    )
    other_video = _seed_video_proof(mem_store, owner=OTHER_USER_ID, project_id=str(uuid4()))

    _as_anon(client)
    # The full-access student's own document is open …
    assert client.get(f"/api/v1/proofs/artifacts/{ctx['doc_artifact']['id']}/view").status_code == 200
    # … and reveals nothing about the other student's.
    assert client.get(f"/api/v1/proofs/artifacts/{other_doc['id']}/view").status_code == 404
    assert client.get(f"/api/v1/proofs/artifacts/{other_doc['id']}/download").status_code == 404
    assert client.get(f"/api/v1/proofs/video/{other_video['id']}").status_code == 404


def test_full_access_denies_unknown_deleted_and_malformed_ids(
    client: TestClient, mem_store: dict
) -> None:
    """(F10) Missing, removed, and malformed identifiers all fail with the same
    indistinct 404 — full access never turns id guessing into an oracle."""
    ctx = _full_setup(client, mem_store)
    _set_mode(client, MODE_FULL_ACCESS)

    _as_anon(client)
    assert client.get(f"/api/v1/proofs/artifacts/{uuid4()}/view").status_code == 404
    assert client.get("/api/v1/proofs/artifacts/not-a-uuid/view").status_code == 404
    assert client.get("/api/v1/proofs/artifacts/..%2F..%2Fetc%2Fpasswd/view").status_code == 404
    assert client.get(f"/api/v1/proofs/video/{uuid4()}").status_code == 404
    assert client.get(f"/api/v1/proofs/website/{uuid4()}/replay").status_code == 404

    # A deleted (tombstoned) artifact stays closed even though its aspect is open.
    mem_store["proof_artifacts"][ctx["doc_artifact"]["id"]]["retained"] = False
    assert client.get(f"/api/v1/proofs/artifacts/{ctx['doc_artifact']['id']}/view").status_code == 404


def test_full_access_does_not_expose_unshared_unlinked_evidence(
    client: TestClient, mem_store: dict
) -> None:
    """(F11) The superset floor is a FLOOR, not a blanket grant: an artifact or
    video proof the hierarchy cannot resolve (no project linkage) is served only
    when the owner had already shared it. Unshared drafts stay private."""
    ctx = _full_setup(client, mem_store)
    unlinked_shared = _register_artifact(
        mem_store,
        artifact_type="website_frame",
        proof_type="website",
        proof_id=str(uuid4()),
        project_id=None,  # type: ignore[arg-type]
        policy="public_safe",
        mime="image/jpeg",
    )
    unlinked_private = _register_artifact(
        mem_store,
        artifact_type="website_frame",
        proof_type="website",
        proof_id=str(uuid4()),
        project_id=None,  # type: ignore[arg-type]
        policy="owner_only",
        mime="image/jpeg",
    )
    draft_video = _seed_video_proof(mem_store, project_id=None, public_safe=False)
    shared_video = _seed_video_proof(mem_store, project_id=None, public_safe=True)

    # Baseline: this is exactly what recruiter-safe already served.
    _as_anon(client)
    assert client.get(f"/api/v1/proofs/artifacts/{unlinked_shared['id']}/view").status_code == 200
    assert client.get(f"/api/v1/proofs/artifacts/{unlinked_private['id']}/view").status_code == 404

    _as_user(client, USER_ID)
    _set_mode(client, MODE_FULL_ACCESS)

    _as_anon(client)
    # Superset: previously shared evidence must NOT disappear …
    assert client.get(f"/api/v1/proofs/artifacts/{unlinked_shared['id']}/view").status_code == 200
    assert client.get(f"/api/v1/proofs/video/{shared_video['id']}").status_code == 200
    # … and unshared drafts must NOT appear.
    assert client.get(f"/api/v1/proofs/artifacts/{unlinked_private['id']}/view").status_code == 404
    assert client.get(f"/api/v1/proofs/video/{draft_video['id']}").status_code == 404
    # The floor never upgrades a view into a download.
    assert (
        client.get(f"/api/v1/proofs/artifacts/{unlinked_shared['id']}/download").status_code == 404
    )


def test_full_access_public_payloads_carry_no_owner_or_storage_internals(
    client: TestClient, mem_store: dict
) -> None:
    """(F12) Leak scan at maximum exposure — the most open mode is exactly where
    private locators, owner-only descriptors, and disclosure keys must not
    appear in any public payload."""
    ctx = _full_setup(client, mem_store)
    _set_mode(client, MODE_FULL_ACCESS)

    _as_anon(client)
    passport_text = _public_passport(client, ctx["slug"]).text
    report_res = _public_report(client, ctx["token"])
    report_text = report_res.text

    for blob in (passport_text, report_text):
        for forbidden in (
            "storage_path",
            "storage_bucket",
            "owner_user_id",
            "access_policy",
            "signed_url",
            "website_key",
            USER_ID,
        ):
            assert forbidden not in blob, forbidden

    # These survive as DECLARED fields on the shared owner/public schema; their
    # VALUES — the per-document disclosure key, the candidate's spoken answer,
    # and the owner-only retained-original descriptor — must never be populated
    # on a public surface, in any mode.
    def _assert_stripped_values(node: object) -> None:
        if isinstance(node, dict):
            for field in ("document_key", "answer_excerpt", "original_document"):
                assert node.get(field) is None, (field, node)
            for value in node.values():
                _assert_stripped_values(value)
        elif isinstance(node, list):
            for value in node:
                _assert_stripped_values(value)

    _assert_stripped_values(report_res.json())
    _assert_stripped_values(_public_passport(client, ctx["slug"]).json())
    assert ctx["document_id"] not in report_text
    assert ctx["document_id"] not in passport_text

    # The document descriptor exposes only the gated route pair.
    view = report_res.json()["documents"][0]["shared_view"]
    assert set(view) == {"open_path", "mime_type", "page_count", "can_download", "download_path"}


def test_full_access_leaves_owner_access_untouched(
    client: TestClient, mem_store: dict
) -> None:
    """(F13) Disclosure never locks the student out of their own evidence, and
    owner-only surfaces stay authenticated in every mode."""
    ctx = _full_setup(client, mem_store)
    _set_mode(client, MODE_FULL_ACCESS)

    _as_user(client, USER_ID)
    assert client.get(f"/api/v1/proofs/artifacts/{ctx['doc_artifact']['id']}/view").status_code == 200
    assert (
        client.get(f"/api/v1/proofs/artifacts/{ctx['doc_artifact']['id']}/download").status_code
        == 200
    )
    assert _get_disclosure(client).status_code == 200

    # The owner-only editor context is never reachable without auth.
    _as_anon(client)
    assert _get_disclosure(client).status_code == 401
    assert _set_mode(client, MODE_CUSTOM).status_code == 401


# ── Persistence and mode transitions ─────────────────────────────────────────


def test_full_access_is_never_a_default_and_survives_reload(
    client: TestClient, mem_store: dict
) -> None:
    """(F14) No passport lands in full access implicitly: the default stays
    recruiter-safe and an unknown/legacy mode value fails closed to it. Once
    chosen explicitly, full access persists across reloads and bumps the
    version so cached public representations are recognized as stale."""
    ctx = _full_setup(client, mem_store)
    assert _get_disclosure(client).json()["passport"]["mode"] == MODE_RECRUITER_SAFE

    before = _get_disclosure(client).json()["passport"]["disclosure_version"]
    assert _set_mode(client, MODE_FULL_ACCESS).status_code == 200
    after = _get_disclosure(client).json()["passport"]
    assert after["mode"] == MODE_FULL_ACCESS
    assert after["disclosure_version"] > before

    # Reload from storage — the persisted row still resolves to full access.
    assert load_effective_disclosure(mem_store, USER_ID).mode == MODE_FULL_ACCESS
    assert _get_disclosure(client).json()["passport"]["mode"] == MODE_FULL_ACCESS

    # Migration drift / a hand-edited row fails closed, never open.
    policy = next(iter(mem_store["passport_disclosure_policies"].values()))
    policy["mode"] = "wide_open"
    assert load_effective_disclosure(mem_store, USER_ID).mode == MODE_RECRUITER_SAFE

    # And the write path refuses anything outside the closed vocabulary.
    policy["mode"] = MODE_FULL_ACCESS
    assert _set_mode(client, "wide_open").status_code == 422
    assert load_effective_disclosure(mem_store, USER_ID).mode == MODE_FULL_ACCESS
    assert ctx["slug"]


def test_narrowing_from_full_access_revokes_immediately(
    client: TestClient, mem_store: dict
) -> None:
    """(F15) Switching away from full access contracts access on the very next
    request — no stale grant survives on either the payload or the routes."""
    ctx = _full_setup(client, mem_store)
    _set_mode(client, MODE_FULL_ACCESS)

    _as_anon(client)
    assert (
        client.get(f"/api/v1/proofs/artifacts/{ctx['doc_artifact']['id']}/download").status_code
        == 200
    )

    _as_user(client, USER_ID)
    _set_mode(client, MODE_RECRUITER_SAFE)

    _as_anon(client)
    report = _public_report(client, ctx["token"]).json()
    assert report["documents"][0]["disclosure"] == SUMMARY
    assert report["documents"][0]["shared_view"] is None
    assert report["website_proofs"][0]["replay_path"] is None
    assert report["website_proofs"][0]["frame_views"] == []
    assert (
        client.get(f"/api/v1/proofs/artifacts/{ctx['doc_artifact']['id']}/download").status_code
        == 404
    )
    assert client.get(f"/api/v1/proofs/artifacts/{ctx['doc_artifact']['id']}/view").status_code == 404
    assert client.get(f"/api/v1/proofs/artifacts/{ctx['frame']['id']}/view").status_code == 404

    # Custom mode then narrows independently of the recruiter-safe defaults.
    _as_user(client, USER_ID)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("report", ctx["project_id"], "hidden"))
    _as_anon(client)
    assert _public_report(client, ctx["token"]).status_code == 404
