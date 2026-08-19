-- ============================================================
-- VeriBridge AI — Migration 069: Recruiter Interview Workspace + Pipeline
-- ============================================================
--
-- Recruiter V4: the Hiring Brief's candidate pool (migration 068) grows
-- into a full role pipeline, and every (brief, candidate) pair gains a
-- recruiter-private interview workspace grounded in the candidate's
-- LIVE published evidence.
--
-- Four additive changes:
--
--   1. The pool's role-scoped status CHECK widens from the V3 vocabulary
--      (saved | reviewing | shortlisted | archived) to the 9-stage
--      pipeline (saved | reviewing | shortlisted | contacted | interview
--      | decision | hired | passed | archived). Strict superset — every
--      existing row remains valid; no data rewrite of any kind.
--
--   2. recruiter_brief_candidate_interviews — ONE interview workspace
--      per (brief, candidate): schedule, interviewer, prep / interview /
--      decision notes, and the stored generated-questions payload
--      (jsonb; UNTRUSTED on load, always re-validated and re-graded
--      against the CURRENT live checklist exactly like the brief plan).
--      Deliberately NOT FK'd to the pool row: removing a candidate from
--      the role must not destroy interview notes; re-adding the
--      candidate restores the workspace.
--
--   3. recruiter_interview_checklist_marks — recruiter-private
--      per-requirement interview marks (discussed | verified |
--      follow_up), keyed by the deterministic requirement axis key
--      ("concept:a|b" / "evidence:github"). These marks are recruiter
--      hiring context ONLY — they are never public proof, never
--      candidate-visible, and never written to any index, projection,
--      or student-owned table.
--
--   4. recruiter_brief_candidate_events — compact recruiter-private
--      activity trail (added / stage_changed / note_updated /
--      interview_updated / checklist_marked / questions_generated /
--      removed). ``detail`` is a closed small shape (e.g.
--      {"from":"reviewing","to":"contacted"}) — NEVER note text, NEVER
--      candidate content. This is an audit convenience, not event
--      sourcing.
--
-- Privacy contract: everything in this migration is recruiter-private
-- workflow data. All three new tables carry owner-via-brief RLS for
-- authenticated users (recruiter_user_id = auth.uid() on the owning
-- brief), service_role has full access, and STUDENTS GET NO POLICY.
-- Nothing here is ever written into recruiter_search_index, any public
-- projection, any embedding, or any candidate-facing surface. The
-- backend runs with the service role, so app-level ownership filtering
-- (every query resolves through the owning brief) is the real boundary;
-- these policies are defense-in-depth.
--
-- Right-to-delete alignment: student_user_id FKs cascade from
-- public.users, brief_id FKs cascade from the owning brief — deleting
-- either side removes every interview artifact about that pair.
--
-- No destructive changes. Idempotent: safe to re-run.
-- ============================================================

create extension if not exists pgcrypto;

-- ------------------------------------------------------------
-- 1. Widen the role-scoped pool status vocabulary (superset)
-- ------------------------------------------------------------

alter table public.recruiter_hiring_brief_candidates
  drop constraint if exists recruiter_hiring_brief_candidates_status_check;
alter table public.recruiter_hiring_brief_candidates
  add constraint recruiter_hiring_brief_candidates_status_check
  check (status in ('saved', 'reviewing', 'shortlisted', 'contacted',
                    'interview', 'decision', 'hired', 'passed', 'archived'));

-- ------------------------------------------------------------
-- 2. recruiter_brief_candidate_interviews (one workspace per pair)
-- ------------------------------------------------------------

create table if not exists public.recruiter_brief_candidate_interviews (
  brief_id         uuid not null
    references public.recruiter_hiring_briefs (id) on delete cascade,
  student_user_id  uuid not null references public.users (id) on delete cascade,
  -- All recruiter-private. Length caps (interviewer_name <= 120, note
  -- fields <= 4000) are enforced app-side, matching the 068 note pattern.
  scheduled_at     timestamptz,
  interviewer_name text,
  prep_notes       text,
  notes            text,
  decision_notes   text,
  -- Stored generated interview questions + provenance
  -- ({items, source, generated_at, model, fallback_reason}). UNTRUSTED
  -- on load: always re-validated (closed shape) and re-graded against
  -- the CURRENT live checklist, exactly like the brief's plan jsonb.
  questions        jsonb not null default '{}'::jsonb,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  primary key (brief_id, student_user_id)
);

create or replace trigger set_recruiter_brief_candidate_interviews_updated_at
  before update on public.recruiter_brief_candidate_interviews
  for each row execute function public.set_updated_at();

alter table public.recruiter_brief_candidate_interviews enable row level security;

-- Rows are visible/editable only through briefs the recruiter owns.
-- Students get NO policy: interview workspaces are recruiter-private.
drop policy if exists "recruiter_brief_candidate_interviews: own brief all"
  on public.recruiter_brief_candidate_interviews;
create policy "recruiter_brief_candidate_interviews: own brief all"
  on public.recruiter_brief_candidate_interviews for all to authenticated
  using (exists (
    select 1 from public.recruiter_hiring_briefs b
    where b.id = brief_id
      and b.recruiter_user_id::text = (select auth.uid())::text))
  with check (exists (
    select 1 from public.recruiter_hiring_briefs b
    where b.id = brief_id
      and b.recruiter_user_id::text = (select auth.uid())::text));

drop policy if exists "recruiter_brief_candidate_interviews: service role all"
  on public.recruiter_brief_candidate_interviews;
create policy "recruiter_brief_candidate_interviews: service role all"
  on public.recruiter_brief_candidate_interviews for all to service_role
  using (true) with check (true);

-- ------------------------------------------------------------
-- 3. recruiter_interview_checklist_marks (per-requirement marks)
-- ------------------------------------------------------------

create table if not exists public.recruiter_interview_checklist_marks (
  brief_id        uuid not null
    references public.recruiter_hiring_briefs (id) on delete cascade,
  student_user_id uuid not null references public.users (id) on delete cascade,
  -- The deterministic requirement axis key ("concept:a|b",
  -- "evidence:github"); validated app-side against the CURRENT axis.
  requirement_key text not null,
  state           text not null
    check (state in ('discussed', 'verified', 'follow_up')),
  marked_at       timestamptz not null default now(),
  primary key (brief_id, student_user_id, requirement_key)
);

alter table public.recruiter_interview_checklist_marks enable row level security;

-- Recruiter hiring context ONLY — never public proof, never
-- candidate-visible. Students get NO policy.
drop policy if exists "recruiter_interview_checklist_marks: own brief all"
  on public.recruiter_interview_checklist_marks;
create policy "recruiter_interview_checklist_marks: own brief all"
  on public.recruiter_interview_checklist_marks for all to authenticated
  using (exists (
    select 1 from public.recruiter_hiring_briefs b
    where b.id = brief_id
      and b.recruiter_user_id::text = (select auth.uid())::text))
  with check (exists (
    select 1 from public.recruiter_hiring_briefs b
    where b.id = brief_id
      and b.recruiter_user_id::text = (select auth.uid())::text));

drop policy if exists "recruiter_interview_checklist_marks: service role all"
  on public.recruiter_interview_checklist_marks;
create policy "recruiter_interview_checklist_marks: service role all"
  on public.recruiter_interview_checklist_marks for all to service_role
  using (true) with check (true);

-- ------------------------------------------------------------
-- 4. recruiter_brief_candidate_events (compact activity trail)
-- ------------------------------------------------------------

create table if not exists public.recruiter_brief_candidate_events (
  id              uuid primary key default gen_random_uuid(),
  brief_id        uuid not null
    references public.recruiter_hiring_briefs (id) on delete cascade,
  student_user_id uuid not null references public.users (id) on delete cascade,
  event_type      text not null
    check (event_type in ('added', 'stage_changed', 'note_updated',
                          'interview_updated', 'checklist_marked',
                          'questions_generated', 'removed')),
  -- Closed small shape (e.g. {"from":"reviewing","to":"contacted"}) —
  -- NEVER note text, NEVER candidate content.
  detail          jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now()
);

create index if not exists recruiter_brief_candidate_events_pair_idx
  on public.recruiter_brief_candidate_events
  (brief_id, student_user_id, created_at desc);

alter table public.recruiter_brief_candidate_events enable row level security;

drop policy if exists "recruiter_brief_candidate_events: own brief all"
  on public.recruiter_brief_candidate_events;
create policy "recruiter_brief_candidate_events: own brief all"
  on public.recruiter_brief_candidate_events for all to authenticated
  using (exists (
    select 1 from public.recruiter_hiring_briefs b
    where b.id = brief_id
      and b.recruiter_user_id::text = (select auth.uid())::text))
  with check (exists (
    select 1 from public.recruiter_hiring_briefs b
    where b.id = brief_id
      and b.recruiter_user_id::text = (select auth.uid())::text));

drop policy if exists "recruiter_brief_candidate_events: service role all"
  on public.recruiter_brief_candidate_events;
create policy "recruiter_brief_candidate_events: service role all"
  on public.recruiter_brief_candidate_events for all to service_role
  using (true) with check (true);

notify pgrst, 'reload schema';

-- ------------------------------------------------------------
-- Rollback (manual):
--   drop table if exists public.recruiter_brief_candidate_events;
--   drop table if exists public.recruiter_interview_checklist_marks;
--   drop table if exists public.recruiter_brief_candidate_interviews;
--   alter table public.recruiter_hiring_brief_candidates
--     drop constraint if exists recruiter_hiring_brief_candidates_status_check;
--   alter table public.recruiter_hiring_brief_candidates
--     add constraint recruiter_hiring_brief_candidates_status_check
--     check (status in ('saved', 'reviewing', 'shortlisted', 'archived'));
--   -- NOTE: the narrow re-add above fails if any row already uses a
--   -- V4 stage; map those rows back first (e.g. hired/passed/decision/
--   -- interview/contacted -> shortlisted) before restoring the V3 CHECK.
-- ------------------------------------------------------------
