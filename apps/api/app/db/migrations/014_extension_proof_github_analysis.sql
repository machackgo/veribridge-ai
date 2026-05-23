-- ============================================================
-- VeriBridge AI — Migration 014: Extension Proof GitHub Analysis
--
-- Stores the results of GitHub repository analysis for extension
-- proof sessions. One row per session (upserted on proof_session_id).
--
-- Idempotent:
--   • CREATE TABLE IF NOT EXISTS
--   • ADD COLUMN IF NOT EXISTS
--   • CREATE UNIQUE INDEX IF NOT EXISTS
--   • CREATE INDEX IF NOT EXISTS
--   • CREATE OR REPLACE TRIGGER
--   • ALTER TABLE … ENABLE RLS
--   • DROP POLICY IF EXISTS + CREATE POLICY
-- ============================================================

create table if not exists public.extension_proof_github_analysis (
  id                      uuid        primary key default gen_random_uuid(),

  -- ownership
  user_id                 uuid        not null references public.users (id) on delete cascade,
  proof_session_id        uuid        not null references public.extension_proof_sessions (id) on delete cascade,

  -- input
  repo_url                text        not null,

  -- analysis outcome
  status                  text        not null default 'failed'
                                        check (status in (
                                          'success',
                                          'failed',
                                          'private_or_unavailable'
                                        )),

  -- detected results (stored as jsonb arrays)
  detected_stack          jsonb       not null default '[]'::jsonb,
  detected_features       jsonb       not null default '[]'::jsonb,
  matched_claimed_skills  jsonb       not null default '[]'::jsonb,
  missing_claimed_skills  jsonb       not null default '[]'::jsonb,
  evidence_files          jsonb       not null default '[]'::jsonb,

  -- scoring
  confidence_score        double precision not null default 0.0,

  -- narrative
  warnings                jsonb       not null default '[]'::jsonb,
  recruiter_summary       text        not null default '',

  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

-- Add any columns absent from a manually-patched table
alter table public.extension_proof_github_analysis
  add column if not exists detected_stack          jsonb       not null default '[]'::jsonb,
  add column if not exists detected_features       jsonb       not null default '[]'::jsonb,
  add column if not exists matched_claimed_skills  jsonb       not null default '[]'::jsonb,
  add column if not exists missing_claimed_skills  jsonb       not null default '[]'::jsonb,
  add column if not exists evidence_files          jsonb       not null default '[]'::jsonb,
  add column if not exists confidence_score        double precision not null default 0.0,
  add column if not exists warnings                jsonb       not null default '[]'::jsonb,
  add column if not exists recruiter_summary       text        not null default '';

-- Unique: one analysis result per session (upsert target)
create unique index if not exists ext_proof_github_analysis_session_idx
  on public.extension_proof_github_analysis (proof_session_id);

-- Supporting indexes
create index if not exists ext_proof_github_analysis_user_id_idx
  on public.extension_proof_github_analysis (user_id);

create index if not exists ext_proof_github_analysis_status_idx
  on public.extension_proof_github_analysis (status);

create index if not exists ext_proof_github_analysis_created_at_idx
  on public.extension_proof_github_analysis (created_at);

-- updated_at trigger
create or replace trigger set_ext_proof_github_analysis_updated_at
  before update on public.extension_proof_github_analysis
  for each row execute function public.set_updated_at();

-- Row-level security
alter table public.extension_proof_github_analysis enable row level security;

drop policy if exists "ext_proof_github_analysis: own row select"
  on public.extension_proof_github_analysis;
create policy "ext_proof_github_analysis: own row select"
  on public.extension_proof_github_analysis for select
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "ext_proof_github_analysis: own row insert"
  on public.extension_proof_github_analysis;
create policy "ext_proof_github_analysis: own row insert"
  on public.extension_proof_github_analysis for insert
  to authenticated
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1
      from public.extension_proof_sessions eps
      where eps.id = proof_session_id
        and eps.user_id = (select auth.uid())
    )
  );

drop policy if exists "ext_proof_github_analysis: own row update"
  on public.extension_proof_github_analysis;
create policy "ext_proof_github_analysis: own row update"
  on public.extension_proof_github_analysis for update
  to authenticated
  using  ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
