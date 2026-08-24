-- ============================================================
-- VeriBridge AI — Migration 072: Recruiter pool workflow metadata
-- ============================================================
--
-- Recruiter V6 turns a Talent Pool from a collection into a workspace.
-- Two additive pieces of RECRUITER-PRIVATE JUDGEMENT, kept strictly
-- separate from VeriBridge EVIDENCE:
--
--   1. ``recruiter_talent_pool_candidates.status`` — a pool-scoped
--      workflow stage (review / shortlisted / interview / hold / pass).
--      Deliberately mirrors the role-scoped
--      ``recruiter_hiring_brief_candidates.status`` pattern from 068:
--      the stage a candidate is at is a property of THIS recruiter's
--      process in THIS pool, not of the human. Marking someone "pass"
--      in "Fall 2026 — AI / ML" says nothing about them in any other
--      pool, in any Hiring Brief, or anywhere on their Passport.
--
--   2. ``recruiter_candidate_tags`` — the recruiter's own private
--      vocabulary about a candidate ("Backend", "Career Fair",
--      "Follow up"). Scoped to (recruiter, candidate) rather than to a
--      pool, because a tag describes the person as this recruiter sees
--      them and should travel with them across every pool. Tags are
--      recruiter-authored free text, never inferred, never derived from
--      evidence.
--
-- THE INVARIANT THIS MIGRATION MUST NOT BREAK: nothing here is
-- evidence. A recruiter writing "Excellent backend candidate" or
-- tagging someone "ML" changes NO skill state, NO proof, NO Verified
-- Build Report, NO public projection, NO Work Passport, and is never
-- written into recruiter_search_index or any embedding. It is not
-- visible to the candidate and not visible to any other recruiter.
-- Existing surfaces are untouched: no student-facing table is modified.
--
-- RLS: status rides the existing owner-via-pool policies already on
-- recruiter_talent_pool_candidates (a column addition inherits them).
-- Tags carry owner RLS (recruiter_user_id = auth.uid()); service_role
-- full access; STUDENTS GET NO POLICY. The backend runs as the service
-- role, so app-level ownership filtering is the real boundary and these
-- policies are defense-in-depth.
--
-- Right-to-delete alignment: tags cascade from BOTH users — deleting
-- either the recruiter or the candidate removes the row.
--
-- Additive and idempotent: safe to re-run.
-- ============================================================

create extension if not exists pgcrypto;

-- ------------------------------------------------------------
-- 1. Pool-scoped workflow status
-- ------------------------------------------------------------

-- Mirror constant: recruiter_talent_pool_service.POOL_CANDIDATE_STATUSES.
-- 'review' is the honest default: a candidate lands in a pool to be
-- looked at, not pre-judged.
alter table public.recruiter_talent_pool_candidates
  add column if not exists status text not null default 'review';

alter table public.recruiter_talent_pool_candidates
  drop constraint if exists recruiter_talent_pool_candidates_status_check;
alter table public.recruiter_talent_pool_candidates
  add constraint recruiter_talent_pool_candidates_status_check
  check (status in ('review', 'shortlisted', 'interview', 'hold', 'pass'));

-- Membership only had ``added_at``; workflow metadata now mutates, so it
-- needs the standard updated_at + trigger (068 pattern).
alter table public.recruiter_talent_pool_candidates
  add column if not exists updated_at timestamptz not null default now();

create or replace trigger set_recruiter_talent_pool_candidates_updated_at
  before update on public.recruiter_talent_pool_candidates
  for each row execute function public.set_updated_at();

-- Pool workspace filtering ("show me the shortlist") stays a single
-- index scan as pools grow.
create index if not exists recruiter_talent_pool_candidates_pool_status_idx
  on public.recruiter_talent_pool_candidates (pool_id, status);

-- ------------------------------------------------------------
-- 2. recruiter_candidate_tags (recruiter-private vocabulary)
-- ------------------------------------------------------------

create table if not exists public.recruiter_candidate_tags (
  recruiter_user_id uuid not null references public.users (id) on delete cascade,
  student_user_id   uuid not null references public.users (id) on delete cascade,
  -- Recruiter-authored label, normalized app-side (trimmed, collapsed
  -- whitespace, <= 40 chars, compared case-insensitively via tag_key so
  -- "Backend" and "backend" are one tag). ``tag`` keeps the recruiter's
  -- own casing for display; ``tag_key`` is the identity.
  tag               text not null,
  tag_key           text not null,
  created_at        timestamptz not null default now(),
  primary key (recruiter_user_id, student_user_id, tag_key)
);

create index if not exists recruiter_candidate_tags_recruiter_idx
  on public.recruiter_candidate_tags (recruiter_user_id, tag_key);

alter table public.recruiter_candidate_tags enable row level security;

-- Recruiter-private judgement. Students get NO policy: a recruiter's
-- tags about a candidate are never candidate-visible.
drop policy if exists "recruiter_candidate_tags: own rows all"
  on public.recruiter_candidate_tags;
create policy "recruiter_candidate_tags: own rows all"
  on public.recruiter_candidate_tags for all to authenticated
  using (recruiter_user_id::text = (select auth.uid())::text)
  with check (recruiter_user_id::text = (select auth.uid())::text);

drop policy if exists "recruiter_candidate_tags: service role all"
  on public.recruiter_candidate_tags;
create policy "recruiter_candidate_tags: service role all"
  on public.recruiter_candidate_tags for all to service_role
  using (true) with check (true);

notify pgrst, 'reload schema';

-- ------------------------------------------------------------
-- Rollback (manual):
--   drop table if exists public.recruiter_candidate_tags;
--   drop index if exists public.recruiter_talent_pool_candidates_pool_status_idx;
--   alter table public.recruiter_talent_pool_candidates
--     drop constraint if exists recruiter_talent_pool_candidates_status_check;
--   alter table public.recruiter_talent_pool_candidates
--     drop column if exists status,
--     drop column if exists updated_at;
-- ------------------------------------------------------------
