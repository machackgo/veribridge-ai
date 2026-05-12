-- ============================================================
-- VeriBridge AI — Migration 006: Website Verification Plans
--
-- Phase 5C stores machine-readable plans generated from a
-- Website Verification Guide. Plans are historical so future
-- browser execution attempts can reference the exact plan used.
-- ============================================================

create table if not exists public.website_verification_plans (
  id                              uuid        primary key default gen_random_uuid(),
  user_id                         uuid        not null references public.users (id) on delete cascade,
  skill_evidence_id               uuid        not null references public.skill_evidence (id) on delete cascade,
  website_verification_guide_id   uuid        references public.website_verification_guides (id) on delete set null,
  website_url                     text        not null,
  feature_to_verify               text        not null,
  plan_status                     text        not null
                                    check (plan_status in ('ready','needs_more_detail','unsupported')),
  normalized_test_steps           jsonb       not null default '[]',
  expected_output                 text        not null,
  sample_inputs                   jsonb,
  inferred_action_candidates      jsonb       not null default '[]',
  validation_warnings             jsonb       not null default '[]',
  agent_notes                     text        not null default '',
  requires_login                  boolean     not null default false,
  can_attempt_automated_execution boolean     not null default false,
  planner_version                 text        not null,
  guide_snapshot                  jsonb       not null default '{}',
  created_at                      timestamptz not null default now(),
  constraint website_verification_plans_steps_array_check
    check (jsonb_typeof(normalized_test_steps) = 'array'),
  constraint website_verification_plans_actions_array_check
    check (jsonb_typeof(inferred_action_candidates) = 'array'),
  constraint website_verification_plans_warnings_array_check
    check (jsonb_typeof(validation_warnings) = 'array')
);

create index if not exists website_verification_plans_evidence_created_idx
  on public.website_verification_plans (skill_evidence_id, created_at desc);

create index if not exists website_verification_plans_user_idx
  on public.website_verification_plans (user_id);

create index if not exists website_verification_plans_status_idx
  on public.website_verification_plans (plan_status);

alter table public.website_verification_plans enable row level security;

create policy "website_verification_plans: own row select"
  on public.website_verification_plans for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "website_verification_plans: own row insert"
  on public.website_verification_plans for insert
  to authenticated
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1
      from public.skill_evidence se
      where se.id = skill_evidence_id
        and se.user_id = (select auth.uid())
    )
  );
