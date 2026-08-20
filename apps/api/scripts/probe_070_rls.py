"""Live-JWT RLS probes for migration 070 (Talent Pools + Saved Searches).

Usage (against the local docker e2e-supabase rig by default):
    cd apps/api
    python scripts/probe_070_rls.py

Environment (defaults are the standard local supabase dev keys):
    PROBE_SUPABASE_URL          default http://127.0.0.1:54321
    PROBE_SUPABASE_ANON_KEY     default local demo anon JWT
    PROBE_SUPABASE_SERVICE_KEY  default local demo service_role JWT

What it does — with REAL tokens, not mocked app permissions:
  1. Creates three throwaway auth users (recruiter A, recruiter B, student)
     via the GoTrue admin API, plus their public.users rows (service role).
  2. Seeds one row in each 070 table owned by recruiter A (service role).
  3. Signs each user in (password grant) and probes PostgREST directly:
       - recruiter A sees exactly their own rows on all four tables;
       - recruiter B sees ZERO rows on all four tables;
       - the student sees ZERO rows on all four tables;
       - anonymous sees ZERO rows on all four tables;
       - recruiter B cannot INSERT membership/match rows into A's
         pool/saved search (WITH CHECK), and cannot UPDATE or DELETE
         A's pool (0 rows affected).
  4. Deletes the throwaway auth users (public.users FK cascade removes
     every seeded row).

Exit code 0 with "ALL PROBES PASSED (n/n)" on success; non-zero otherwise.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("PROBE_SUPABASE_URL", "http://127.0.0.1:54321").rstrip("/")
ANON = os.environ.get(
    "PROBE_SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9."
    "CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0",
)
SERVICE = os.environ.get(
    "PROBE_SUPABASE_SERVICE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0."
    "EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU",
)

TABLES = (
    "recruiter_talent_pools",
    "recruiter_talent_pool_candidates",
    "recruiter_saved_searches",
    "recruiter_saved_search_matches",
)

passed = 0
failed: list[str] = []


def _req(
    method: str,
    path: str,
    *,
    token: str,
    body: dict | list | None = None,
    prefer: str | None = None,
) -> tuple[int, object]:
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", ANON)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    if prefer:
        req.add_header("Prefer", prefer)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode() or "null"
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode() or "null"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        return exc.code, parsed


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed.append(name)
        print(f"  FAIL  {name}  {detail}")


def admin_create_user(email: str, password: str) -> str:
    status, body = _req(
        "POST",
        "/auth/v1/admin/users",
        token=SERVICE,
        body={"email": email, "password": password, "email_confirm": True},
    )
    if status not in (200, 201):
        sys.exit(f"admin user create failed for {email}: {status} {body}")
    return body["id"]  # type: ignore[index]


def admin_delete_user(user_id: str) -> None:
    _req("DELETE", f"/auth/v1/admin/users/{user_id}", token=SERVICE)


def sign_in(email: str, password: str) -> str:
    status, body = _req(
        "POST",
        "/auth/v1/token?grant_type=password",
        token=ANON,
        body={"email": email, "password": password},
    )
    if status != 200:
        sys.exit(f"sign-in failed for {email}: {status} {body}")
    return body["access_token"]  # type: ignore[index]


def main() -> None:
    run = uuid.uuid4().hex[:8]
    password = f"Probe-{uuid.uuid4().hex}!"
    users = {
        "rec_a": f"probe070.rec.a.{run}@example.com",
        "rec_b": f"probe070.rec.b.{run}@example.com",
        "student": f"probe070.student.{run}@example.com",
    }
    print(f"Probe run {run} against {BASE}")

    ids: dict[str, str] = {}
    try:
        for key, email in users.items():
            ids[key] = admin_create_user(email, password)
        # public.users rows (FK anchor; cascade cleans everything up).
        status, body = _req(
            "POST",
            "/rest/v1/users",
            token=SERVICE,
            body=[
                {"id": ids["rec_a"], "email": users["rec_a"], "role": "recruiter"},
                {"id": ids["rec_b"], "email": users["rec_b"], "role": "recruiter"},
                {"id": ids["student"], "email": users["student"], "role": "student"},
            ],
            prefer="return=minimal",
        )
        if status not in (200, 201):
            sys.exit(f"public.users seed failed: {status} {body}")

        # Seed one row per 070 table, all owned by recruiter A.
        pool_id = str(uuid.uuid4())
        search_id = str(uuid.uuid4())
        seeds = [
            (
                "recruiter_talent_pools",
                {
                    "id": pool_id,
                    "recruiter_user_id": ids["rec_a"],
                    "name": f"Probe pool {run}",
                },
            ),
            (
                "recruiter_talent_pool_candidates",
                {
                    "pool_id": pool_id,
                    "student_user_id": ids["student"],
                    "source": "direct",
                },
            ),
            (
                "recruiter_saved_searches",
                {
                    "id": search_id,
                    "recruiter_user_id": ids["rec_a"],
                    "name": f"Probe search {run}",
                    "query_text": "python and fastapi",
                },
            ),
            (
                "recruiter_saved_search_matches",
                {
                    "saved_search_id": search_id,
                    "student_user_id": ids["student"],
                    "evidence_fingerprint": "deadbeef",
                },
            ),
        ]
        for table, row in seeds:
            status, body = _req(
                "POST", f"/rest/v1/{table}", token=SERVICE, body=row,
                prefer="return=minimal",
            )
            if status not in (200, 201):
                sys.exit(f"seed failed for {table}: {status} {body}")

        tok_a = sign_in(users["rec_a"], password)
        tok_b = sign_in(users["rec_b"], password)
        tok_s = sign_in(users["student"], password)

        # ── Visibility probes ────────────────────────────────────────
        for table in TABLES:
            path = f"/rest/v1/{table}?select=*"
            status, rows = _req("GET", path, token=tok_a)
            check(
                f"{table}: owner A sees own row",
                status == 200 and isinstance(rows, list) and len(rows) == 1,
                f"status={status} rows={rows if not isinstance(rows, list) else len(rows)}",
            )
            for label, tok in (("recruiter B", tok_b), ("student", tok_s), ("anon", ANON)):
                status, rows = _req("GET", path, token=tok)
                check(
                    f"{table}: {label} sees zero rows",
                    status == 200 and rows == [],
                    f"status={status} rows={rows}",
                )

        # ── Write probes (recruiter B against A's data) ──────────────
        status, body = _req(
            "POST",
            "/rest/v1/recruiter_talent_pool_candidates",
            token=tok_b,
            body={"pool_id": pool_id, "student_user_id": ids["rec_b"], "source": "direct"},
            prefer="return=minimal",
        )
        check(
            "membership: B cannot insert into A's pool",
            status in (401, 403),
            f"status={status} body={body}",
        )
        status, body = _req(
            "POST",
            "/rest/v1/recruiter_saved_search_matches",
            token=tok_b,
            body={"saved_search_id": search_id, "student_user_id": ids["rec_b"]},
            prefer="return=minimal",
        )
        check(
            "matches: B cannot insert into A's saved search",
            status in (401, 403),
            f"status={status} body={body}",
        )
        status, body = _req(
            "PATCH",
            f"/rest/v1/recruiter_talent_pools?id=eq.{pool_id}",
            token=tok_b,
            body={"name": "hijacked"},
            prefer="return=representation",
        )
        check(
            "pools: B update of A's pool affects zero rows",
            status in (401, 403) or (status == 200 and body == []),
            f"status={status} body={body}",
        )
        status, body = _req(
            "DELETE",
            f"/rest/v1/recruiter_talent_pools?id=eq.{pool_id}",
            token=tok_b,
            prefer="return=representation",
        )
        check(
            "pools: B delete of A's pool affects zero rows",
            status in (401, 403) or (status in (200, 204) and body in ([], None)),
            f"status={status} body={body}",
        )
        status, rows = _req(
            "GET",
            f"/rest/v1/recruiter_talent_pools?id=eq.{pool_id}&select=id,name",
            token=tok_a,
        )
        check(
            "pools: A's pool intact after B's attempts",
            status == 200
            and isinstance(rows, list)
            and len(rows) == 1
            and rows[0]["name"] == f"Probe pool {run}",
            f"status={status} rows={rows}",
        )
    finally:
        for uid in ids.values():
            admin_delete_user(uid)
        print("Cleanup: throwaway auth users deleted (rows cascade).")

    total = passed + len(failed)
    if failed:
        print(f"\n{len(failed)}/{total} PROBES FAILED: {failed}")
        sys.exit(1)
    print(f"\nALL PROBES PASSED ({passed}/{total})")


if __name__ == "__main__":
    main()
