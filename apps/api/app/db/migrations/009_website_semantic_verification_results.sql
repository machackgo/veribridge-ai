-- ============================================================
-- VeriBridge AI — Migration 009: Website Semantic Verification Results
--
-- Phase 5F stores final semantic judgments over website proof evidence,
-- combining the guide/plan, static run, and safe browser run into a
-- recruiter-friendly verification result.
-- ============================================================

create table if not exists public.website_semantic_verification_results (
  id                         uuid        primary key default gen_random_uuid(),
  evidence_id                uuid        not null references public.skill_evidence (id) on delete cascade,
  plan_id                    uuid        not null references public.website_verification_plans (id) on delete cascade,
  static_run_id              uuid        references public.website_verification_runs (id) on delete set null,
  browser_run_id             uuid        references public.website_browser_verification_runs (id) on delete set null,
  user_id                    uuid        not null references public.users (id) on delete cascade,
  semantic_status            text        not null
                                      check (semantic_status in (
                                        'verified',
                                        'partially_verified',
                                        'not_verified',
                                        'needs_human_review',
                                        'insufficient_evidence',
                                        'evaluation_error'
                                      )),
  confidence_score           numeric(5,4)
                                      check (confidence_score is null or confidence_score between 0.0000 and 1.0000),
  evaluator_version          text        not null default 'website-semantic-evaluator-mock-v1',
  evaluator_provider         text        not null default 'deterministic_mock',
  internal_reasoning_summary text,
  recruiter_facing_summary   text,
  evidence_summary           text,
  limitations                text,
  recommended_next_action    text,
  source_snapshot            jsonb       not null default '{}'::jsonb,
  created_at                 timestamptz not null default now(),
  updated_at                 timestamptz not null default now()
);

create index if not exists website_semantic_verification_results_evidence_idx
  on public.website_semantic_verification_results (evidence_id);

create index if not exists website_semantic_verification_results_user_idx
  on public.website_semantic_verification_results (user_id);

create index if not exists website_semantic_verification_results_status_idx
  on public.website_semantic_verification_results (semantic_status);

create index if not exists website_semantic_verification_results_plan_idx
  on public.website_semantic_verification_results (plan_id);

create index if not exists website_semantic_verification_results_static_run_idx
  on public.website_semantic_verification_results (static_run_id);

create index if not exists website_semantic_verification_results_browser_run_idx
  on public.website_semantic_verification_results (browser_run_id);

create index if not exists website_semantic_verification_results_created_idx
  on public.website_semantic_verification_results (created_at);

create or replace trigger set_website_semantic_verification_results_updated_at
  before update on public.website_semantic_verification_results
  for each row execute function public.set_updated_at();

alter table public.website_semantic_verification_results enable row level security;

create policy "website_semantic_verification_results: own row select"
  on public.website_semantic_verification_results for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "website_semantic_verification_results: own row insert"
  on public.website_semantic_verification_results for insert
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
    and (
      static_run_id is null
      or exists (
        select 1
        from public.website_verification_runs r
        where r.id = static_run_id
          and r.user_id = (select auth.uid())
          and r.evidence_id = evidence_id
          and r.plan_id = plan_id
      )
    )
    and (
      browser_run_id is null
      or exists (
        select 1
        from public.website_browser_verification_runs br
        where br.id = browser_run_id
          and br.user_id = (select auth.uid())
          and br.evidence_id = evidence_id
          and br.plan_id = plan_id
      )
    )
  );
