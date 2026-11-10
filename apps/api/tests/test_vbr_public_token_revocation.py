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
  - the view tracker applies the SAME gate as the public GET (finding R8):
    a disclosure-hidden report, a hidden project, a private passport and a
    disclosure-loader failure all answer ``recorded: false`` and insert no row;
  - unauthenticated view inserts are capped per project per UTC day.

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
    _unpublish_passport,
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


# Finding R8: the view tracker used to check only the token and the passport
# master switch, not ``disclosure.report_visible``, so ``/view`` answered
# ``recorded: true`` for a report the GET 404s (a token-liveness oracle). Both
# routes now share ``_resolve_visible_project``.


def _view_count(mem_store: dict) -> int:
    return len(mem_store.get("vbr_project_report_views") or {})


def _assert_view_not_recorded(client: TestClient, mem_store: dict, token: str) -> None:
    before = _view_count(mem_store)
    view = _record_view(client, token)
    assert view.status_code == 200
    assert view.json() == {"recorded": False}
    assert _view_count(mem_store) == before


def test_view_tracker_records_visible_report(client: TestClient, mem_store: dict) -> None:
    """Control: the gate still lets a visible report record exactly one row."""
    ctx = _publish_setup(client, mem_store)
    _as_anon(client)
    before = _view_count(mem_store)
    assert _record_view(client, ctx["token"]).json() == {"recorded": True}
    assert _view_count(mem_store) == before + 1


def test_disclosure_hidden_report_view_tracker_records_nothing(client: TestClient, mem_store: dict) -> None:
    """A disclosure-hidden report 404s on GET and must not record a view."""
    ctx = _publish_setup(client, mem_store)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("report", ctx["project_id"], "hidden"))
    _as_anon(client)
    assert _public_report(client, ctx["token"]).status_code == 404
    _assert_view_not_recorded(client, mem_store, ctx["token"])


def test_hidden_project_view_tracker_records_nothing(client: TestClient, mem_store: dict) -> None:
    ctx = _publish_setup(client, mem_store)
    _set_mode(client, MODE_CUSTOM)
    _apply(client, _ov("project", ctx["project_id"], "hidden"))
    _as_anon(client)
    assert _public_report(client, ctx["token"]).status_code == 404
    _assert_view_not_recorded(client, mem_store, ctx["token"])


def test_private_passport_view_tracker_records_nothing(client: TestClient, mem_store: dict) -> None:
    ctx = _publish_setup(client, mem_store)
    assert _unpublish_passport(client).status_code == 200
    _as_anon(client)
    assert _public_report(client, ctx["token"]).status_code == 404
    _assert_view_not_recorded(client, mem_store, ctx["token"])


def test_disclosure_loader_failure_view_tracker_fails_closed(
    client: TestClient, mem_store: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _publish_setup(client, mem_store)
    _as_anon(client)

    import app.services.vbr_public_project_report as report_module

    def _boom(*args, **kwargs):
        raise RuntimeError("disclosure tables unavailable")

    monkeypatch.setattr(report_module, "load_effective_disclosure", _boom)
    _assert_view_not_recorded(client, mem_store, ctx["token"])


def test_view_tracker_daily_cap(
    client: TestClient, mem_store: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Past the per-project daily cap, /view answers recorded:false and writes nothing,
    even with fresh dedupe keys; yesterday's rows do not count against today."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "public_report_view_daily_cap", 3)
    ctx = _publish_setup(client, mem_store)
    other = _make_project(
        client, mem_store, title="Capped Sibling", repo_owner="o3", repo_name="r3", claimed_skills=["Go"]
    )
    other_token = _publish_report(client, other["project_id"]).json()["public_token"]
    _as_anon(client)

    table = mem_store.setdefault("vbr_project_report_views", {})
    table["old-row"] = {
        "id": "old-row",
        "project_id": ctx["project_id"],
        "dedupe_key": None,
        "viewed_at": "2000-01-01T12:00:00+00:00",
    }

    def _post(token: str, n: int):
        return client.post(
            f"/api/v1/public/vbr/reports/{token}/view", json={"dedupe_key": f"cap-key-{n:04d}"}
        )

    assert [_post(ctx["token"], n).json()["recorded"] for n in range(3)] == [True] * 3
    before = _view_count(mem_store)
    for n in range(3, 8):
        assert _post(ctx["token"], n).json() == {"recorded": False}
    assert _view_count(mem_store) == before

    # The cap is per project: a sibling report still records.
    assert _post(other_token, 99).json() == {"recorded": True}
    # The report itself stays readable while views are capped.
    assert _public_report(client, ctx["token"]).status_code == 200


def test_view_tracker_cap_zero_disables_recording(
    client: TestClient, mem_store: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "public_report_view_daily_cap", 0)
    ctx = _publish_setup(client, mem_store)
    _as_anon(client)
    _assert_view_not_recorded(client, mem_store, ctx["token"])


class _FakeQuery:
    def __init__(self, client: "_FakeSupabase", table: str) -> None:
        self.client, self.table, self.filters, self.count_mode = client, table, [], None

    def select(self, _cols: str, count: str | None = None) -> "_FakeQuery":
        self.count_mode = count
        return self

    def eq(self, col: str, val) -> "_FakeQuery":
        self.filters.append(("eq", col, val))
        return self

    def gte(self, col: str, val) -> "_FakeQuery":
        self.filters.append(("gte", col, val))
        return self

    def limit(self, _n: int) -> "_FakeQuery":
        return self

    def insert(self, row: dict) -> "_FakeQuery":
        self.client.inserted.append(row)
        return self

    def execute(self):
        self.client.queries.append((self.count_mode, list(self.filters)))

        class _Res:
            data: list = []
            count = self.client.count if self.count_mode == "exact" else None

        return _Res()


class _FakeSupabase:
    def __init__(self, count) -> None:
        self.count, self.inserted, self.queries = count, [], []

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self, name)


def test_daily_cap_supabase_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Supabase mode: exact count since UTC midnight gates the insert; an
    unknown count fails closed (raises, which the endpoint maps to recorded:false)."""
    from app.core.config import settings
    from app.services.vbr_report_view_service import record_public_report_view

    monkeypatch.setattr(settings, "public_report_view_daily_cap", 5)

    under = _FakeSupabase(count=4)
    assert record_public_report_view(under, "proj-1") is True
    assert len(under.inserted) == 1
    count_mode, filters = under.queries[0]
    assert count_mode == "exact"
    assert ("eq", "project_id", "proj-1") in filters
    gte = [f for f in filters if f[0] == "gte"]
    assert gte and gte[0][1] == "viewed_at" and gte[0][2].endswith("T00:00:00+00:00")

    at_cap = _FakeSupabase(count=5)
    assert record_public_report_view(at_cap, "proj-1") is False
    assert at_cap.inserted == []

    unknown = _FakeSupabase(count=None)
    with pytest.raises(RuntimeError):
        record_public_report_view(unknown, "proj-1")
    assert unknown.inserted == []
