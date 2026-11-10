"""Public VBR report token: revocation and lookup-hardening tests.

Complements ``test_vbr_public_project_report.py`` (unknown token, API
unpublish), ``test_passport_visibility.py`` (private passport) and
``test_passport_disclosure.py`` (hidden project / report). The cases here
cover what those files do not:

  - a token revoked by a direct database write (``public_report_token = NULL``,
    the SQL path in the owner's revocation runbook) 404s on the public read and
    records no view, and stays revoked when the project is re-published (a new
    token is minted; the old one never comes back);
  - revoking one project leaves the same owner's other published report and
    another user's report untouched;
  - near-miss tokens (prefix, suffix, case change, padded, implausible shapes)
    never resolve;
  - a disclosure-hidden report: the GET 404s (already covered) and the view
    tracker's behaviour is pinned.

All storage is in-memory (dict mode). Tokens are generated at test time.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.passport_disclosure import MODE_CUSTOM
from tests.test_passport_disclosure import (  # noqa: F401  (fixtures)
    _apply,
    _as_anon,
    _as_user,
    _make_project,
    _ov,
    _public_report,
    _publish_report,
    _publish_setup,
    _publish_passport,
    _set_mode,
    client,
    mem_store,
    pipeline_db,
)
from tests.test_vbr_project_defense import OTHER_USER_ID, _create_project_defense, _seed_github_proof


def _record_view(client: TestClient, token: str):
    return client.post(f"/api/v1/public/vbr/reports/{token}/view", json={})


def _project_row(mem_store: dict, project_id: str) -> dict:
    return mem_store["vbr_projects"][project_id]


def _sql_style_revoke(mem_store: dict, project_id: str) -> None:
    """Mirror runbook A2: token and published_at cleared directly in the DB."""
    row = _project_row(mem_store, project_id)
    row["public_report_token"] = None
    row["public_report_published_at"] = None


def test_db_level_revocation_404s_and_records_no_view(client: TestClient, mem_store: dict) -> None:
    ctx = _publish_setup(client, mem_store)
    token = ctx["token"]
    _as_anon(client)
    assert _public_report(client, token).status_code == 200

    _sql_style_revoke(mem_store, ctx["project_id"])
    views_before = len(mem_store.get("vbr_project_report_views") or {})

    res = _public_report(client, token)
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "vbr_public_report_not_found"
    view = _record_view(client, token)
    assert view.status_code == 200
    assert view.json() == {"recorded": False}
    assert len(mem_store.get("vbr_project_report_views") or {}) == views_before


def test_republish_after_revocation_mints_new_token_old_stays_dead(
    client: TestClient, mem_store: dict
) -> None:
    ctx = _publish_setup(client, mem_store)
    old = ctx["token"]
    _sql_style_revoke(mem_store, ctx["project_id"])

    new = _publish_report(client, ctx["project_id"]).json()["public_token"]
    assert new and new != old
    _as_anon(client)
    assert _public_report(client, old).status_code == 404
    assert _public_report(client, new).status_code == 200


def test_revocation_is_scoped_to_one_project(client: TestClient, mem_store: dict) -> None:
    ctx_a = _publish_setup(client, mem_store)
    ctx_a2 = _make_project(
        client, mem_store, title="Second Project", repo_owner="o2", repo_name="r2", claimed_skills=["Go"]
    )
    token_a2 = _publish_report(client, ctx_a2["project_id"]).json()["public_token"]

    _as_user(client, OTHER_USER_ID)
    gid_b = _seed_github_proof(
        mem_store,
        user_id=OTHER_USER_ID,
        repo_url="https://github.com/otherorg/other-repo",
        repo_owner="otherorg",
        repo_name="other-repo",
    )
    created_b = _create_project_defense(
        client,
        title="Other User Project",
        repo_url="https://github.com/otherorg/other-repo",
        attached_proofs={"github_proof_id": gid_b},
    )
    ctx_b = {"project_id": created_b.json()["project"]["id"]}
    token_b = _publish_report(client, ctx_b["project_id"]).json()["public_token"]
    assert _publish_passport(client).status_code == 200

    _sql_style_revoke(mem_store, ctx_a["project_id"])

    _as_anon(client)
    assert _public_report(client, ctx_a["token"]).status_code == 404
    assert _public_report(client, token_a2).status_code == 200
    assert _public_report(client, token_b).status_code == 200
    assert _project_row(mem_store, ctx_a2["project_id"])["public_report_token"] == token_a2
    assert _project_row(mem_store, ctx_b["project_id"])["public_report_token"] == token_b
    assert _project_row(mem_store, ctx_b["project_id"])["user_id"] == OTHER_USER_ID


def test_near_miss_tokens_never_resolve(client: TestClient, mem_store: dict) -> None:
    ctx = _publish_setup(client, mem_store)
    token = ctx["token"]
    _as_anon(client)
    near_misses = [
        token[:-1],
        token[1:],
        token + "A",
        token.swapcase() if token.swapcase() != token else token[:-1] + ("A" if token[-1] != "A" else "B"),
        token[:12],
        "None",
        "null",
        "a" * 7,
        "a" * 129,
    ]
    for candidate in near_misses:
        assert candidate != token
        assert _public_report(client, candidate).status_code == 404, candidate[:4]
        assert _record_view(client, candidate).json() == {"recorded": False}
    # sanity: the real token still works
    assert _public_report(client, token).status_code == 200


@pytest.mark.parametrize("bad", ["%20", "..", "a%2Fb", "tok en", "tok.en"])
def test_implausible_token_shapes_404(client: TestClient, mem_store: dict, bad: str) -> None:
    _publish_setup(client, mem_store)
    _as_anon(client)
    assert _public_report(client, bad).status_code in (404, 405)


def test_disclosure_hidden_report_view_tracker_behaviour(client: TestClient, mem_store: dict) -> None:
    """GET 404s for a disclosure-hidden report. The view tracker only checks the
    token and the passport master switch (``resolve_published_project_id``), not
    ``report_visible``; this test pins that behaviour so a change is deliberate.
    It is a minor oracle (``recorded: true`` vs ``false``), not a data leak."""
    ctx = _publish_setup(client, mem_store)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("report", ctx["project_id"], "hidden"))
    _as_anon(client)
    assert _public_report(client, ctx["token"]).status_code == 404
    view = _record_view(client, ctx["token"])
    assert view.status_code == 200
    assert view.json() == {"recorded": True}
