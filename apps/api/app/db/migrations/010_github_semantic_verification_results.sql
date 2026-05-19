-- ============================================================
-- VeriBridge AI — Migration 010: GitHub Semantic Verification Results
--
-- Phase G2 stores semantic claim-to-code judgments for GitHub proof
-- evidence, including the strongest matching line range and compact
-- matched-segment metadata.
-- ============================================================

create table if not exists public.github_semantic_verification_results (
  id                              uuid        primary key default gen_random_uuid(),
  evidence_id                     uuid        not null references public.skill_evidence (id) on delete cascade,
  user_id                         uuid        not null references public.users (id) on delete cascade,
  semantic_status                 text        not null
                                            check (semantic_status in (
                                              'verified',
                                              'partially_verified',
                                              'not_verified',
                                              'needs_human_review',
                                              'insufficient_evidence',
                                              'evaluation_error'
                                            )),
  confidence_score                numeric(5,4)
                                            check (confidence_score is null or confidence_score between 0.0000 and 1.0000),
  evaluator_version               text        not null default 'github-claim-code-semantic-v1',
  evaluator_provider              text        not null default 'local_deterministic_embedding',
  recruiter_facing_summary         text,
  evidence_summary                text,
  limitations                     text,
  recommended_next_action         text,
  strongest_matching_segment_start integer,
  strongest_matching_segment_end   integer,
  strongest_matching_segment_summary text,
  source_snapshot                 jsonb       not null default '{}'::jsonb,
  created_at                      timestamptz not null default now(),
  updated_at                      timestamptz not null default now()
);

create index if not exists github_semantic_verification_results_evidence_idx
  on public.github_semantic_verification_results (evidence_id);

create index if not exists github_semantic_verification_results_user_idx
  on public.github_semantic_verification_results (user_id);

create index if not exists github_semantic_verification_results_status_idx
  on public.github_semantic_verification_results (semantic_status);

create index if not exists github_semantic_verification_results_created_idx
  on public.github_semantic_verification_results (created_at);

create or replace trigger set_github_semantic_verification_results_updated_at
  before update on public.github_semantic_verification_results
  for each row execute function public.set_updated_at();

alter table public.github_semantic_verification_results enable row level security;

create policy "github_semantic_verification_results: own row select"
  on public.github_semantic_verification_results for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "github_semantic_verification_results: own row insert"
  on public.github_semantic_verification_results for insert
  to authenticated
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1
      from public.skill_evidence se
      where se.id = evidence_id
        and se.user_id = (select auth.uid())
    )
  );
