-- ============================================================
-- VeriBridge AI — Migration 061: Extension Proof Sessions RLS repair
--
-- Root cause (Gate 13 / Gate 14):
--   public.extension_proof_sessions and public.extension_proof_uploads
--   had RLS ENABLED but their only policy was
--     "Allow service role full access to extension proof …"
--       cmd=ALL  roles={public}  using(true)  with check(true)
--   Because the policy targets the PostgreSQL `public` role (every role,
--   incl. `anon`) with USING(true), the anon key could read AND write
--   every row across all users — a cross-tenant exposure of launch tokens,
--   proof payloads, and session metadata.
--
--   Migration 013 defined owner-only policies, but the production tables
--   pre-date it (user_id is `text`, and extension_proof_uploads has no
--   user_id column at all), so 013's uuid-typed policies were never the
--   live state. This migration repairs the LIVE schema in place.
--
-- Fix (matches the proven, isolated pattern used by public.vbr_projects
-- and public.github_proof_submissions):
--   • Drop the permissive `public`/USING(true) policy.
--   • extension_proof_sessions: explicit service_role policy + owner-only
--     authenticated select/insert/update keyed on
--       (user_id)::text = ((select auth.uid()))::text
--     (the ::text cast tolerates the `text` user_id column).
--   • extension_proof_uploads: legacy, empty, backend-only table with no
--     user_id column and no application writer. Lock it to service_role
--     only (no anon/authenticated policy -> RLS default-deny). The backend
--     uses the service-role key, which BYPASSes RLS, so server access is
--     unaffected.
--
-- Access preserved:
--   • Backend (service_role key) — unaffected (bypasses RLS; explicit policy
--     added for clarity).
--   • Legitimate owner (authenticated JWT) — own rows only on sessions.
--   • Anonymous — default-deny (no anon/public policy remains).
--   • Public Verified Build Report / Passport tokens are served by separate
--     endpoints and tables; they are untouched by this migration.
--
-- Idempotent: ENABLE RLS is a no-op when already on; every policy is
-- DROP POLICY IF EXISTS before CREATE.
-- ============================================================

-- ── extension_proof_sessions ──────────────────────────────────────────────────

alter table public.extension_proof_sessions enable row level security;

-- Remove the over-permissive policy that granted every role (incl. anon)
-- full access to all rows.
drop policy if exists "Allow service role full access to extension proof sessions"
  on public.extension_proof_sessions;

-- Explicit service-role full access (service_role also bypasses RLS; this
-- documents intent and matches the vbr_projects convention).
drop policy if exists "ext_proof_sessions: service role all"
  on public.extension_proof_sessions;
create policy "ext_proof_sessions: service role all"
  on public.extension_proof_sessions for all
  to service_role
  using (true)
  with check (true);

-- Owner-only access for authenticated end users.
drop policy if exists "ext_proof_sessions: own row select"
  on public.extension_proof_sessions;
create policy "ext_proof_sessions: own row select"
  on public.extension_proof_sessions for select
  to authenticated
  using ((user_id)::text = ((select auth.uid()))::text);

drop policy if exists "ext_proof_sessions: own row insert"
  on public.extension_proof_sessions;
create policy "ext_proof_sessions: own row insert"
  on public.extension_proof_sessions for insert
  to authenticated
  with check ((user_id)::text = ((select auth.uid()))::text);

drop policy if exists "ext_proof_sessions: own row update"
  on public.extension_proof_sessions;
create policy "ext_proof_sessions: own row update"
  on public.extension_proof_sessions for update
  to authenticated
  using ((user_id)::text = ((select auth.uid()))::text)
  with check ((user_id)::text = ((select auth.uid()))::text);

-- ── extension_proof_uploads ───────────────────────────────────────────────────
-- Legacy, empty, backend-only (no user_id column, no application writer).
-- Lock to service_role only; anon/authenticated fall through to default-deny.

alter table public.extension_proof_uploads enable row level security;

drop policy if exists "Allow service role full access to extension proof uploads"
  on public.extension_proof_uploads;

drop policy if exists "ext_proof_uploads: service role all"
  on public.extension_proof_uploads;
create policy "ext_proof_uploads: service role all"
  on public.extension_proof_uploads for all
  to service_role
  using (true)
  with check (true);

-- Ask PostgREST to reload its schema/policy cache.
notify pgrst, 'reload schema';
