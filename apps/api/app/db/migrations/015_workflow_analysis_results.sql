-- ============================================================
-- VeriBridge AI — Migration 015: Extension Proof Workflow Analysis
--
-- Stores the results of AI-driven workflow timeline analysis for
-- extension proof sessions. One row per session (upserted on
-- proof_session_id). Analysis covers demonstrated actions, skill
-- support, confidence, risk flags, and recruiter-facing summaries.
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

create table if not exists public.workflow_analysis_results (
  id                              uuid        primary key default gen_random_uuid(),

  -- ownership
  user_id                         uuid        not null references public.users (id) on delete cascade,
  proof_session_id                uuid        not null references public.extension_proof_sessions (id) on delete cascade,

  -- analysis meta
  analysis_type                   text        not null default 'timeline_only'
                                                check (analysis_type in (
                                                  'timeline_only',
                                                  'video_frame_analysis',
                                                  'full_multimodal_analysis'
                                                )),
  analyzer_version                text        not null default 'workflow-analysis-v1',

  -- narrative outputs
  workflow_summary                text        not null default '',
  recruiter_summary               text        not null default '',

  -- skill assessment (stored as jsonb string arrays)
  demonstrated_actions            jsonb       not null default '[]'::jsonb,
  supported_skills                jsonb       not null default '[]'::jsonb,
  weakly_supported_skills         jsonb       not null default '[]'::jsonb,
  unsupported_skills              jsonb       not null default '[]'::jsonb,

  -- scoring
  evidence_strength_score         integer     not null default 0
                                                check (evidence_strength_score between 0 and 100),
  workflow_confidence             text        not null default 'insufficient'
                                                check (workflow_confidence in (
                                                  'high',
                                                  'medium',
                                                  'low',
                                                  'insufficient'
                                                )),

  -- gaps and flags
  missing_evidence                jsonb       not null default '[]'::jsonb,
  risk_flags                      jsonb       not null default '[]'::jsonb,
  student_improvement_suggestions jsonb       not null default '[]'::jsonb,

  -- review flag
  human_review_needed             boolean     not null default false,

  created_at                      timestamptz not null default now(),
  updated_at                      timestamptz not null default now()
);

-- Add any columns absent from a manually-patched table
alter table public.workflow_analysis_results
  add column if not exists analysis_type                   text        not null default 'timeline_only',
  add column if not exists analyzer_version                text        not null default 'workflow-analysis-v1',
  add column if not exists workflow_summary                text        not null default '',
  add column if not exists recruiter_summary               text        not null default '',
  add column if not exists demonstrated_actions            jsonb       not null default '[]'::jsonb,
  add column if not exists supported_skills                jsonb       not null default '[]'::jsonb,
  add column if not exists weakly_supported_skills         jsonb       not null default '[]'::jsonb,
  add column if not exists unsupported_skills              jsonb       not null default '[]'::jsonb,
  add column if not exists evidence_strength_score         integer     not null default 0,
  add column if not exists workflow_confidence             text        not null default 'insufficient',
  add column if not exists missing_evidence                jsonb       not null default '[]'::jsonb,
  add column if not exists risk_flags                      jsonb       not null default '[]'::jsonb,
  add column if not exists student_improvement_suggestions jsonb       not null default '[]'::jsonb,
  add column if not exists human_review_needed             boolean     not null default false;

-- Unique: one analysis result per session (upsert target)
create unique index if not exists workflow_analysis_results_session_idx
  on public.workflow_analysis_results (proof_session_id);

create index if not exists workflow_analysis_results_user_id_idx
  on public.workflow_analysis_results (user_id);

create index if not exists workflow_analysis_results_confidence_idx
  on public.workflow_analysis_results (workflow_confidence);

create index if not exists workflow_analysis_results_created_at_idx
  on public.workflow_analysis_results (created_at);

-- updated_at trigger
create or replace trigger set_workflow_analysis_results_updated_at
  before update on public.workflow_analysis_results
  for each row execute function public.set_updated_at();

-- Row-level security
alter table public.workflow_analysis_results enable row level security;

drop policy if exists "workflow_analysis_results: own row select"
  on public.workflow_analysis_results;
create policy "workflow_analysis_results: own row select"
  on public.workflow_analysis_results for select
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "workflow_analysis_results: own row insert"
  on public.workflow_analysis_results;
create policy "workflow_analysis_results: own row insert"
  on public.workflow_analysis_results for insert
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

drop policy if exists "workflow_analysis_results: own row update"
  on public.workflow_analysis_results;
create policy "workflow_analysis_results: own row update"
  on public.workflow_analysis_results for update
  to authenticated
  using  ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
