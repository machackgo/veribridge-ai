-- ============================================================
-- VeriBridge AI — Migration 008: Website Browser Verification Runs
--
-- Phase 5E stores safe browser-based website verification runs.
-- Browser runs are intentionally separate from static runs so each
-- execution layer has a clear audit trail and independent status model.
-- ============================================================

create table if not exists public.website_browser_verification_runs (
  id                        uuid        primary key default gen_random_uuid(),
  evidence_id               uuid        not null references public.skill_evidence (id) on delete cascade,
  plan_id                   uuid        not null references public.website_verification_plans (id) on delete cascade,
  user_id                   uuid        not null references public.users (id) on delete cascade,
  browser_execution_status  text        not null
                                      check (browser_execution_status in (
                                        'pending',
                                        'browser_verified',
                                        'browser_partially_verified',
                                        'browser_failed',
                                        'needs_human_review',
                                        'blocked_by_login',
                                        'unsupported_plan',
                                        'execution_timeout',
                                        'execution_error'
                                      )),
  executor_version          text        not null default 'website-browser-executor-v1',
  execution_summary         text,
  inspected_url             text,
  final_url                 text,
  page_title                text,
  screenshot_storage_path   text,
  html_snapshot_storage_path text,
  safe_text_snapshot        text,
  steps_attempted           integer     not null default 0,
  steps_passed              integer     not null default 0,
  steps_failed              integer     not null default 0,
  steps_skipped             integer     not null default 0,
  steps_needing_review      integer     not null default 0,
  browser_metadata          jsonb       not null default '{}'::jsonb,
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now()
);

create index if not exists website_browser_verification_runs_evidence_idx
  on public.website_browser_verification_runs (evidence_id);

create index if not exists website_browser_verification_runs_plan_idx
  on public.website_browser_verification_runs (plan_id);

create index if not exists website_browser_verification_runs_user_idx
  on public.website_browser_verification_runs (user_id);

create index if not exists website_browser_verification_runs_status_idx
  on public.website_browser_verification_runs (browser_execution_status);

create index if not exists website_browser_verification_runs_created_idx
  on public.website_browser_verification_runs (created_at);

create or replace trigger set_website_browser_verification_runs_updated_at
  before update on public.website_browser_verification_runs
  for each row execute function public.set_updated_at();

alter table public.website_browser_verification_runs enable row level security;

create policy "website_browser_verification_runs: own row select"
  on public.website_browser_verification_runs for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "website_browser_verification_runs: own row insert"
  on public.website_browser_verification_runs for insert
  to authenticated
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1
      from public.skill_evidence se
      where se.id = evidence_id
        and se.user_id = (select auth.uid())
    )
    and exists (
      select 1
      from public.website_verification_plans p
      where p.id = plan_id
        and p.user_id = (select auth.uid())
        and p.skill_evidence_id = evidence_id
    )
  );

create table if not exists public.website_browser_verification_steps (
  id                      uuid        primary key default gen_random_uuid(),
  run_id                  uuid        not null references public.website_browser_verification_runs (id) on delete cascade,
  step_index              integer     not null,
  plan_step_key           text,
  action_type             text        not null
                                      check (action_type in (
                                        'navigate',
                                        'wait_for_selector',
                                        'click',
                                        'fill',
                                        'select',
                                        'wait_for_text',
                                        'assert_text_present',
                                        'assert_selector_present',
                                        'screenshot',
                                        'unsupported',
                                        'skipped'
                                      )),
  action_target           text,
  action_value            text,
  expected_result         text,
  observed_result         text,
  step_status             text        not null
                                      check (step_status in (
                                        'passed',
                                        'failed',
                                        'skipped',
                                        'unsupported',
                                        'needs_review',
                                        'blocked_by_login',
                                        'timeout'
                                      )),
  step_summary            text,
  screenshot_storage_path text,
  created_at              timestamptz not null default now()
);

create index if not exists website_browser_verification_steps_run_idx
  on public.website_browser_verification_steps (run_id);

create index if not exists website_browser_verification_steps_status_idx
  on public.website_browser_verification_steps (step_status);

create index if not exists website_browser_verification_steps_type_idx
  on public.website_browser_verification_steps (action_type);

create index if not exists website_browser_verification_steps_index_idx
  on public.website_browser_verification_steps (step_index);

alter table public.website_browser_verification_steps enable row level security;

create policy "website_browser_verification_steps: own row select"
  on public.website_browser_verification_steps for select
  to authenticated
  using (
    exists (
      select 1
      from public.website_browser_verification_runs r
      where r.id = run_id
        and r.user_id = (select auth.uid())
    )
  );

create policy "website_browser_verification_steps: own row insert"
  on public.website_browser_verification_steps for insert
  to authenticated
  with check (
    exists (
      select 1
      from public.website_browser_verification_runs r
      where r.id = run_id
        and r.user_id = (select auth.uid())
    )
  );
