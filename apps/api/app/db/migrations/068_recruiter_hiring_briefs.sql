-- ============================================================
-- VeriBridge AI — Migration 068: Recruiter Hiring Briefs + Role Workspace
-- ============================================================
--
-- Recruiter V3: the Hiring Brief is the persistent, recruiter-owned
-- source of truth for one hiring need. The recruiter defines the role
-- ONCE — role, seniority, location, required / preferred / excluded
-- requirements, evidence expectations — and the same brief then powers
-- search, evidence review, candidate association, comparison and
-- role-scoped shortlisting.
--
-- Two additive tables:
--
--   1. recruiter_hiring_briefs — the brief itself. Stores the raw
--      natural-language role text exactly as the recruiter typed it AND
--      the structured requirement plan (the SAME jsonb shape
--      recruiter_query_understanding produces, after recruiter edits).
--      It stores NO candidate evidence snapshot of any kind: every
--      evaluation (search, candidates tab, comparison) re-runs against
--      the live search index + live publication / disclosure /
--      exclusion checks, so unpublished evidence can never be served
--      stale and requirement changes take effect immediately.
--
--   2. recruiter_hiring_brief_candidates — the role's candidate pool.
--      One row per (brief, student), keyed by the student's STABLE user
--      id (slug rotation or passport re-publishing never orphans the
--      association). Carries the ROLE-SCOPED review status
--      (saved | reviewing | shortlisted | archived) and a
--      recruiter-PRIVATE, role-specific note. A candidate shortlisted
--      for one brief is deliberately NOT shortlisted anywhere else —
--      there is no global shortlist state.
--
-- Design notes:
--   * The brief subsumes what an earlier draft modeled as separate
--     "comparison sessions" and "talent pools": the brief IS the pool,
--     and comparison is a live view over the brief's plan. Neither of
--     those draft tables was ever applied to any environment.
--   * recruiter_candidate_connections is untouched — it remains the
--     single canonical workspace-level "saved candidate" relationship.
--
-- Privacy: briefs, their requirements, candidate statuses and notes are
-- recruiter-private workflow data. They are NEVER written into
-- recruiter_search_index, any public projection, any embedding, or any
-- candidate-facing surface. Students get NO policy on either table.
--
-- No destructive changes. Idempotent: safe to re-run.
-- ============================================================

create extension if not exists pgcrypto;

-- ------------------------------------------------------------
-- 1. recruiter_hiring_briefs
-- ------------------------------------------------------------

create table if not exists public.recruiter_hiring_briefs (
  id                 uuid primary key default gen_random_uuid(),
  recruiter_user_id  uuid not null references public.users (id) on delete cascade,
  -- Short recruiter-facing name, e.g. "AI Engineer Intern — Fall 2026".
  title              text not null,
  -- The raw natural-language brief exactly as the recruiter typed
  -- (or spoke) it. Kept for transparency and re-interpretation.
  role_text          text,
  -- Structured requirement plan (required_groups, preferred, excluded,
  -- evidence, preferred_evidence, role, seniority, location) — the same
  -- closed-vocabulary shape recruiter_query_understanding produces,
  -- after recruiter edits. Always re-sanitized on load; never trusted
  -- raw from a client or an LLM.
  plan               jsonb not null default '{}'::jsonb,
  -- Lightweight lifecycle. No enterprise requisition workflow.
  status             text not null default 'active'
    check (status in ('draft', 'active', 'paused', 'closed')),
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create index if not exists recruiter_hiring_briefs_recruiter_idx
  on public.recruiter_hiring_briefs (recruiter_user_id, updated_at desc);

create or replace trigger set_recruiter_hiring_briefs_updated_at
  before update on public.recruiter_hiring_briefs
  for each row execute function public.set_updated_at();

alter table public.recruiter_hiring_briefs enable row level security;

drop policy if exists "recruiter_hiring_briefs: own rows all"
  on public.recruiter_hiring_briefs;
create policy "recruiter_hiring_briefs: own rows all"
  on public.recruiter_hiring_briefs for all to authenticated
  using (recruiter_user_id::text = (select auth.uid())::text)
  with check (recruiter_user_id::text = (select auth.uid())::text);

drop policy if exists "recruiter_hiring_briefs: service role all"
  on public.recruiter_hiring_briefs;
create policy "recruiter_hiring_briefs: service role all"
  on public.recruiter_hiring_briefs for all to service_role
  using (true) with check (true);

-- ------------------------------------------------------------
-- 2. recruiter_hiring_brief_candidates (role-scoped pool + status)
-- ------------------------------------------------------------

create table if not exists public.recruiter_hiring_brief_candidates (
  brief_id        uuid not null
    references public.recruiter_hiring_briefs (id) on delete cascade,
  student_user_id uuid not null references public.users (id) on delete cascade,
  -- ROLE-SCOPED review status. Forward-compatible with a fuller
  -- pipeline later; deliberately minimal for V3.
  status          text not null default 'saved'
    check (status in ('saved', 'reviewing', 'shortlisted', 'archived')),
  -- Recruiter-PRIVATE, role-specific note ("Strong for AI Engineer,
  -- lacks published deployment evidence"). Never exposed to the
  -- candidate, any public surface, any index, or any embedding.
  note            text,
  added_at        timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  primary key (brief_id, student_user_id)
);

create index if not exists recruiter_hiring_brief_candidates_student_idx
  on public.recruiter_hiring_brief_candidates (student_user_id);

create or replace trigger set_recruiter_hiring_brief_candidates_updated_at
  before update on public.recruiter_hiring_brief_candidates
  for each row execute function public.set_updated_at();

alter table public.recruiter_hiring_brief_candidates enable row level security;

-- Rows are visible/editable only through briefs the recruiter owns.
-- Students get NO policy: brief membership is recruiter-private.
drop policy if exists "recruiter_hiring_brief_candidates: own brief all"
  on public.recruiter_hiring_brief_candidates;
create policy "recruiter_hiring_brief_candidates: own brief all"
  on public.recruiter_hiring_brief_candidates for all to authenticated
  using (exists (
    select 1 from public.recruiter_hiring_briefs b
    where b.id = brief_id
      and b.recruiter_user_id::text = (select auth.uid())::text))
  with check (exists (
    select 1 from public.recruiter_hiring_briefs b
    where b.id = brief_id
      and b.recruiter_user_id::text = (select auth.uid())::text));

drop policy if exists "recruiter_hiring_brief_candidates: service role all"
  on public.recruiter_hiring_brief_candidates;
create policy "recruiter_hiring_brief_candidates: service role all"
  on public.recruiter_hiring_brief_candidates for all to service_role
  using (true) with check (true);

notify pgrst, 'reload schema';

-- ------------------------------------------------------------
-- Rollback (manual):
--   drop table if exists public.recruiter_hiring_brief_candidates;
--   drop table if exists public.recruiter_hiring_briefs;
-- ------------------------------------------------------------
