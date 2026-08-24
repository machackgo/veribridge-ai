"""Live-JWT RLS probes for migration 072 (pool workflow metadata + tags).

Usage (against the local docker e2e-supabase rig by default):
    cd apps/api
    python scripts/probe_072_rls.py

Environment (defaults are the standard local supabase dev keys):
    PROBE_SUPABASE_URL          default http://127.0.0.1:54321
    PROBE_SUPABASE_ANON_KEY     default local demo anon JWT
    PROBE_SUPABASE_SERVICE_KEY  default local demo service_role JWT

072 adds RECRUITER JUDGEMENT to the schema — a pool-scoped workflow status
and a private tag vocabulary. Judgement is exactly the kind of data that must
never leak, so these probes assert, with REAL tokens rather than mocked app
permissions, that:

  1. recruiter A sees their own tags; recruiter B, the tagged student, and an
     anonymous caller all see ZERO tag rows;
  2. recruiter B cannot INSERT a tag attributed to recruiter A (WITH CHECK),
     and cannot UPDATE or DELETE A's tags;
  3. recruiter B cannot flip the workflow status of a candidate inside A's
     pool (owner-via-parent policy on the membership row);
  4. THE STUDENT BEING JUDGED cannot read the status or the note recorded
     about them, and cannot read any tag applied to them — the row is
     recruiter-private in both directions;
  5. the status CHECK constraint rejects a value outside the closed
     vocabulary even when written with the service role.

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
        "rec_a": f"probe072.rec.a.{run}@example.com",
        "rec_b": f"probe072.rec.b.{run}@example.com",
        "student": f"probe072.student.{run}@example.com",
    }
    print(f"Probe run {run} against {BASE}")

    ids: dict[str, str] = {}
    try:
        for key, email in users.items():
            ids[key] = admin_create_user(email, password)
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

        # Recruiter A's pool, with the student in it, judged and tagged.
        pool_id = str(uuid.uuid4())
        for table, row in (
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
                    "status": "shortlisted",
                    "note": "A's private assessment",
                },
            ),
            (
                "recruiter_candidate_tags",
                {
                    "recruiter_user_id": ids["rec_a"],
                    "student_user_id": ids["student"],
                    "tag": "Backend",
                    "tag_key": "backend",
                },
            ),
        ):
            status, body = _req(
                "POST", f"/rest/v1/{table}", token=SERVICE, body=row,
                prefer="return=minimal",
            )
            if status not in (200, 201):
                sys.exit(f"seed failed for {table}: {status} {body}")

        tok_a = sign_in(users["rec_a"], password)
        tok_b = sign_in(users["rec_b"], password)
        tok_s = sign_in(users["student"], password)

        # ── 1. Tag visibility ────────────────────────────────────────
        tags_path = "/rest/v1/recruiter_candidate_tags?select=*"
        status, rows = _req("GET", tags_path, token=tok_a)
        check(
            "tags: owner A sees own tag",
            status == 200 and isinstance(rows, list) and len(rows) == 1,
            f"status={status} rows={rows}",
        )
        for label, tok in (
            ("recruiter B", tok_b),
            ("the tagged student", tok_s),
            ("anon", ANON),
        ):
            status, rows = _req("GET", tags_path, token=tok)
            check(
                f"tags: {label} sees zero rows",
                status == 200 and rows == [],
                f"status={status} rows={rows}",
            )

        # ── 2. Tag writes by another recruiter ───────────────────────
        status, body = _req(
            "POST",
            "/rest/v1/recruiter_candidate_tags",
            token=tok_b,
            body={
                "recruiter_user_id": ids["rec_a"],
                "student_user_id": ids["student"],
                "tag": "Injected",
                "tag_key": "injected",
            },
            prefer="return=minimal",
        )
        check(
            "tags: B cannot insert a tag attributed to A",
            status in (401, 403),
            f"status={status} body={body}",
        )
        status, body = _req(
            "PATCH",
            f"/rest/v1/recruiter_candidate_tags?student_user_id=eq.{ids['student']}",
            token=tok_b,
            body={"tag": "hijacked"},
            prefer="return=representation",
        )
        check(
            "tags: B update of A's tag affects zero rows",
            status in (401, 403) or (status == 200 and body == []),
            f"status={status} body={body}",
        )
        status, body = _req(
            "DELETE",
            f"/rest/v1/recruiter_candidate_tags?student_user_id=eq.{ids['student']}",
            token=tok_b,
            prefer="return=representation",
        )
        check(
            "tags: B delete of A's tag affects zero rows",
            status in (401, 403) or (status in (200, 204) and body in ([], None)),
            f"status={status} body={body}",
        )

        # ── 3. Workflow status inside A's pool ───────────────────────
        status, body = _req(
            "PATCH",
            f"/rest/v1/recruiter_talent_pool_candidates?pool_id=eq.{pool_id}",
            token=tok_b,
            body={"status": "pass"},
            prefer="return=representation",
        )
        check(
            "status: B cannot change a candidate's stage in A's pool",
            status in (401, 403) or (status == 200 and body == []),
            f"status={status} body={body}",
        )

        # ── 4. The judged student cannot read the judgement ──────────
        status, rows = _req(
            "GET",
            "/rest/v1/recruiter_talent_pool_candidates?select=status,note",
            token=tok_s,
        )
        check(
            "judgement: the student cannot read their own status or note",
            status == 200 and rows == [],
            f"status={status} rows={rows}",
        )

        # ── 5. Closed status vocabulary is enforced in the DB ────────
        status, body = _req(
            "PATCH",
            f"/rest/v1/recruiter_talent_pool_candidates?pool_id=eq.{pool_id}",
            token=SERVICE,
            body={"status": "hired"},
            prefer="return=representation",
        )
        check(
            "status: CHECK rejects a value outside the closed vocabulary",
            status >= 400,
            f"status={status} body={body}",
        )

        # ── A's data survived every attempt ──────────────────────────
        status, rows = _req(
            "GET",
            f"/rest/v1/recruiter_talent_pool_candidates?pool_id=eq.{pool_id}&select=status,note",
            token=tok_a,
        )
        check(
            "judgement: A's status and note intact after B's attempts",
            status == 200
            and isinstance(rows, list)
            and len(rows) == 1
            and rows[0]["status"] == "shortlisted"
            and rows[0]["note"] == "A's private assessment",
            f"status={status} rows={rows}",
        )
        status, rows = _req(tags_path and "GET", tags_path, token=tok_a)
        check(
            "tags: A's tag intact after B's attempts",
            status == 200
            and isinstance(rows, list)
            and len(rows) == 1
            and rows[0]["tag"] == "Backend",
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
