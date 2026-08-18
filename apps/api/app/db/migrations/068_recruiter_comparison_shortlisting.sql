-- ============================================================
-- VeriBridge AI — Migration 068: Recruiter comparison + shortlisting
-- ============================================================
--
-- Recruiter V2: after discovering and saving candidates, the recruiter
-- organizes them (shortlist / archive, private note), compares them
-- against role requirements in an evidence matrix, and can group them
-- into lightweight talent pools.
--
-- Three additive pieces:
--
--   1. recruiter_candidate_connections gains a review status
--      (saved | shortlisted | archived), a recruiter-PRIVATE note, and
--      status_updated_at. The connection row remains the single canonical
--      recruiter↔candidate relationship — no parallel shortlist table.
--
--   2. recruiter_comparisons — persisted comparison sessions. Stores the
--      recruiter's role brief (raw text + the structured requirement plan)
--      and the selected candidates BY user id (stable identity; slugs can
--      rotate). It stores NO evidence snapshot: the matrix is re-evaluated
--      from the live search index + live publication/disclosure checks on
--      every load, so unpublished evidence can never be served stale.
--      The plan jsonb is the forward-compatible Hiring Brief primitive.
--
--   3. recruiter_talent_pools (+ members) — minimal recruiter-isolated
--      grouping foundation. Members reference the student user id, so
--      pool membership survives passport re-publishing. Candidates are
--      never told about pool membership.
--
-- Privacy: recruiter notes, statuses, comparisons and pools are
-- recruiter-private workflow data. They are NEVER written into
-- recruiter_search_index, any public projection, or any embedding.
--
-- No destructive changes. Idempotent: safe to re-run.
-- ============================================================

create extension if not exists pgcrypto;

-- ------------------------------------------------------------
-- 1. Connection review status + private note (additive columns)
-- ------------------------------------------------------------

alter table public.recruiter_candidate_connections
  add column if not exists status text not null default 'saved'
    check (status in ('saved', 'shortlisted', 'archived'));

alter table public.recruiter_candidate_connections
  add column if not exists recruiter_note text;

alter table public.recruiter_candidate_connections
  add column if not exists status_updated_at timestamptz;

create index if not exists recruiter_candidate_connections_status_idx
  on public.recruiter_candidate_connections (recruiter_user_id, status);

-- The recruiter may update only their own rows (defense-in-depth; the API
-- uses the service role with app-level filters). with check keeps a
-- recruiter from re-pointing a row at another recruiter.
drop policy if exists "recruiter_candidate_connections: own rows update"
  on public.recruiter_candidate_connections;
create policy "recruiter_candidate_connections: own rows update"
  on public.recruiter_candidate_connections for update to authenticated
  using (recruiter_user_id::text = (select auth.uid())::text)
  with check (recruiter_user_id::text = (select auth.uid())::text);

-- ------------------------------------------------------------
-- 2. recruiter_comparisons — persisted comparison sessions
-- ------------------------------------------------------------

create table if not exists public.recruiter_comparisons (
  id                 uuid primary key default gen_random_uuid(),
  recruiter_user_id  uuid not null references public.users (id) on delete cascade,
  -- Short recruiter-facing name, e.g. "AI Engineer — Fall 2026".
  title              text,
  -- The raw natural-language role brief exactly as the recruiter typed it.
  role_text          text,
  -- Structured requirement plan (required_groups, preferred, excluded,
  -- evidence, preferred_evidence, role, seniority, location) — the same
  -- shape recruiter_query_understanding produces, after recruiter edits.
  -- This is the seed of the future Hiring Brief.
  plan               jsonb not null default '{}'::jsonb,
  -- Selected candidates as an ordered jsonb array of student user-id
  -- strings. Identity is user-level: slug rotation or re-publishing never
  -- orphans a comparison, and unpublished candidates degrade at load time.
  candidate_user_ids jsonb not null default '[]'::jsonb,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create index if not exists recruiter_comparisons_recruiter_idx
  on public.recruiter_comparisons (recruiter_user_id, updated_at desc);

create or replace trigger set_recruiter_comparisons_updated_at
  before update on public.recruiter_comparisons
  for each row execute function public.set_updated_at();

alter table public.recruiter_comparisons enable row level security;

drop policy if exists "recruiter_comparisons: own rows select"
  on public.recruiter_comparisons;
create policy "recruiter_comparisons: own rows select"
  on public.recruiter_comparisons for select to authenticated
  using (recruiter_user_id::text = (select auth.uid())::text);

drop policy if exists "recruiter_comparisons: own rows insert"
  on public.recruiter_comparisons;
create policy "recruiter_comparisons: own rows insert"
  on public.recruiter_comparisons for insert to authenticated
  with check (recruiter_user_id::text = (select auth.uid())::text);

drop policy if exists "recruiter_comparisons: own rows update"
  on public.recruiter_comparisons;
create policy "recruiter_comparisons: own rows update"
  on public.recruiter_comparisons for update to authenticated
  using (recruiter_user_id::text = (select auth.uid())::text)
  with check (recruiter_user_id::text = (select auth.uid())::text);

drop policy if exists "recruiter_comparisons: own rows delete"
  on public.recruiter_comparisons;
create policy "recruiter_comparisons: own rows delete"
  on public.recruiter_comparisons for delete to authenticated
  using (recruiter_user_id::text = (select auth.uid())::text);

drop policy if exists "recruiter_comparisons: service role all"
  on public.recruiter_comparisons;
create policy "recruiter_comparisons: service role all"
  on public.recruiter_comparisons for all to service_role
  using (true) with check (true);

-- ------------------------------------------------------------
-- 3. Talent pools (minimal recruiter-isolated foundation)
-- ------------------------------------------------------------

create table if not exists public.recruiter_talent_pools (
  id                uuid primary key default gen_random_uuid(),
  recruiter_user_id uuid not null references public.users (id) on delete cascade,
  name              text not null,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (recruiter_user_id, name)
);

create index if not exists recruiter_talent_pools_recruiter_idx
  on public.recruiter_talent_pools (recruiter_user_id);

create or replace trigger set_recruiter_talent_pools_updated_at
  before update on public.recruiter_talent_pools
  for each row execute function public.set_updated_at();

alter table public.recruiter_talent_pools enable row level security;

drop policy if exists "recruiter_talent_pools: own rows all"
  on public.recruiter_talent_pools;
create policy "recruiter_talent_pools: own rows all"
  on public.recruiter_talent_pools for all to authenticated
  using (recruiter_user_id::text = (select auth.uid())::text)
  with check (recruiter_user_id::text = (select auth.uid())::text);

drop policy if exists "recruiter_talent_pools: service role all"
  on public.recruiter_talent_pools;
create policy "recruiter_talent_pools: service role all"
  on public.recruiter_talent_pools for all to service_role
  using (true) with check (true);

create table if not exists public.recruiter_talent_pool_members (
  pool_id         uuid not null references public.recruiter_talent_pools (id) on delete cascade,
  student_user_id uuid not null references public.users (id) on delete cascade,
  added_at        timestamptz not null default now(),
  primary key (pool_id, student_user_id)
);

create index if not exists recruiter_talent_pool_members_student_idx
  on public.recruiter_talent_pool_members (student_user_id);

alter table public.recruiter_talent_pool_members enable row level security;

-- Membership rows are visible/editable only through pools the recruiter
-- owns. Students get NO policy: pool membership is recruiter-private.
drop policy if exists "recruiter_talent_pool_members: own pool all"
  on public.recruiter_talent_pool_members;
create policy "recruiter_talent_pool_members: own pool all"
  on public.recruiter_talent_pool_members for all to authenticated
  using (exists (
    select 1 from public.recruiter_talent_pools p
    where p.id = pool_id
      and p.recruiter_user_id::text = (select auth.uid())::text))
  with check (exists (
    select 1 from public.recruiter_talent_pools p
    where p.id = pool_id
      and p.recruiter_user_id::text = (select auth.uid())::text));

drop policy if exists "recruiter_talent_pool_members: service role all"
  on public.recruiter_talent_pool_members;
create policy "recruiter_talent_pool_members: service role all"
  on public.recruiter_talent_pool_members for all to service_role
  using (true) with check (true);

notify pgrst, 'reload schema';

-- ------------------------------------------------------------
-- Rollback (manual):
--   drop table if exists public.recruiter_talent_pool_members;
--   drop table if exists public.recruiter_talent_pools;
--   drop table if exists public.recruiter_comparisons;
--   alter table public.recruiter_candidate_connections
--     drop column if exists status,
--     drop column if exists recruiter_note,
--     drop column if exists status_updated_at;
-- ------------------------------------------------------------
