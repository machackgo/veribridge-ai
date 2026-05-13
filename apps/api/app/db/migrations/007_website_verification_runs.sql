-- ============================================================
-- VeriBridge AI — Migration 007: Website Verification Runs
--
-- Phase 5D stores static public-page execution runs generated
-- from website verification plans. Runs and child checks are
-- historical so future browser/AI execution phases can build on
-- the same audit trail.
-- ============================================================

create table if not exists public.website_verification_runs (
  id                            uuid        primary key default gen_random_uuid(),
  evidence_id                   uuid        not null references public.skill_evidence (id) on delete cascade,
  plan_id                       uuid        not null references public.website_verification_plans (id) on delete cascade,
  user_id                       uuid        not null references public.users (id) on delete cascade,
  execution_status              text        not null
                                  check (execution_status in (
                                    'pending',
                                    'partial_verification',
                                    'static_verified',
                                    'failed_static_checks',
                                    'needs_browser_execution',
                                    'needs_review',
                                    'execution_error'
                                  )),
  executor_version              text        not null default 'website-executor-static-v1',
  execution_summary             text,
  checks_attempted              integer     not null default 0,
  checks_passed                 integer     not null default 0,
  checks_failed                 integer     not null default 0,
  checks_needing_review         integer     not null default 0,
  inspected_url                 text,
  inspected_title               text,
  inspected_meta_description    text,
  inspected_headings            jsonb       not null default '[]'::jsonb,
  inspected_visible_text_excerpt text,
  raw_executor_notes            jsonb       not null default '{}'::jsonb,
  created_at                    timestamptz not null default now(),
  updated_at                    timestamptz not null default now()
);

create index if not exists website_verification_runs_evidence_idx
  on public.website_verification_runs (evidence_id);

create index if not exists website_verification_runs_plan_idx
  on public.website_verification_runs (plan_id);

create index if not exists website_verification_runs_user_idx
  on public.website_verification_runs (user_id);

create index if not exists website_verification_runs_status_idx
  on public.website_verification_runs (execution_status);

create index if not exists website_verification_runs_created_idx
  on public.website_verification_runs (created_at);

create or replace trigger set_website_verification_runs_updated_at
  before update on public.website_verification_runs
  for each row execute function public.set_updated_at();

alter table public.website_verification_runs enable row level security;

create policy "website_verification_runs: own row select"
  on public.website_verification_runs for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "website_verification_runs: own row insert"
  on public.website_verification_runs for insert
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

create table if not exists public.website_verification_run_checks (
  id              uuid        primary key default gen_random_uuid(),
  run_id          uuid        not null references public.website_verification_runs (id) on delete cascade,
  check_key       text        not null,
  check_label     text        not null,
  check_type      text        not null
                            check (check_type in (
                              'static_text_presence',
                              'static_title_presence',
                              'static_heading_presence',
                              'expected_output_keyword_check',
                              'manual/browser_required'
                            )),
  expected_value  text,
  observed_value  text,
  check_status    text        not null
                            check (check_status in ('passed','failed','needs_review','browser_required')),
  check_summary   text,
  created_at      timestamptz not null default now()
);

create index if not exists website_verification_run_checks_run_idx
  on public.website_verification_run_checks (run_id);

create index if not exists website_verification_run_checks_status_idx
  on public.website_verification_run_checks (check_status);

create index if not exists website_verification_run_checks_type_idx
  on public.website_verification_run_checks (check_type);

alter table public.website_verification_run_checks enable row level security;

create policy "website_verification_run_checks: own row select"
  on public.website_verification_run_checks for select
  to authenticated
  using (
    exists (
      select 1
      from public.website_verification_runs r
      where r.id = run_id
        and r.user_id = (select auth.uid())
    )
  );

create policy "website_verification_run_checks: own row insert"
  on public.website_verification_run_checks for insert
  to authenticated
  with check (
    exists (
      select 1
      from public.website_verification_runs r
      where r.id = run_id
        and r.user_id = (select auth.uid())
    )
  );
