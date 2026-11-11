-- ============================================================
-- VeriBridge AI — Migration 074d: evidence_access_grants credential lifecycle
-- ============================================================
--
-- Why
--   1. Migration 021 created "evidence_access_grants: own row update", an
--      UPDATE policy TO authenticated USING/WITH CHECK (user_id = auth.uid()).
--      Through PostgREST a signed-in candidate could therefore rewrite their
--      own grant rows directly — clear revoked_at (re-activating a revoked
--      bearer token), extend expires_at, widen granted_sections, or set a
--      token value of their choosing — bypassing the API's audit trail and
--      the credential rotation that approve_request() now performs. The
--      application never needs the policy: every read and write of this table
--      goes through the service-role client (app.api.deps.get_db), and
--      candidates revoke and re-approve via /api/v1/student/access-grants/
--      {id}/revoke and /access-requests/{id}/approve. apps/web and
--      apps/extension never query the table.
--   2. Migration 021 declares access_token NOT NULL, but since migration 037
--      the API stores only access_token_hash and inserts access_token = NULL
--      (and approve_request() now sets it NULL when it rotates a legacy
--      credential). A database built from the migrations would reject every
--      new grant. Dropping NOT NULL makes the schema match the API. The
--      UNIQUE constraint on access_token is kept (NULLs do not collide).
--
-- What stays
--   "evidence_access_grants: own row select" (candidates can still read their
--   own grants) and "evidence_access_grants: service role all".
--
-- Preconditions
--   Migrations 021 and 037 applied. Production may differ from the repo
--   (see 074c); this migration only drops the policy by its exact 021 name
--   and is a no-op where it is absent. Use VERIBRIDGE_PROD_FIX_GRANTS_LIFECYCLE.sql
--   (guarded, fail-closed) for production instead of this file.
--
-- Properties
--   One transaction; lock_timeout bounds the ACCESS EXCLUSIVE locks so the
--   migration fails fast instead of queueing behind long queries. Idempotent
--   (re-running is a no-op) and tolerant of the table being absent.
--
-- Verification
--   select policyname, cmd, roles from pg_policies
--    where schemaname = 'public' and tablename = 'evidence_access_grants';
--     -> exactly "own row select" (SELECT, {authenticated}) and
--        "service role all" (ALL, {service_role}); no UPDATE policy.
--   select is_nullable from information_schema.columns
--    where table_schema = 'public' and table_name = 'evidence_access_grants'
--      and column_name = 'access_token';                      -> YES
--
-- Rollback (re-opens direct candidate writes; only if a proven flow breaks)
--   begin; set local lock_timeout = '5s';
--   create policy "evidence_access_grants: own row update"
--     on public.evidence_access_grants for update to authenticated
--     using (user_id::text = (select auth.uid())::text)
--     with check (user_id::text = (select auth.uid())::text);
--   -- NOT NULL can only be restored once no hash-only row exists:
--   -- alter table public.evidence_access_grants alter column access_token set not null;
--   commit;
-- ============================================================

begin;
set local lock_timeout = '5s';

do $$
begin
  if pg_catalog.to_regclass('public.evidence_access_grants') is null then
    raise notice '074d: public.evidence_access_grants not present; nothing to do';
    return;
  end if;
  execute 'drop policy if exists "evidence_access_grants: own row update" on public.evidence_access_grants';
  execute 'alter table public.evidence_access_grants alter column access_token drop not null';
end $$;

commit;
