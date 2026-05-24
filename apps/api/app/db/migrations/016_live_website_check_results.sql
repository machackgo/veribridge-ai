-- ============================================================
-- VeriBridge AI — Migration 016: Live Website Check Results
--
-- Stores the result of HTTP reachability checks run against a
-- student's submitted live website URL. One row per session
-- (upserted on proof_session_id). Checks status code, response
-- time, page title, confidence, and risk flags.
--
-- NOTE: If this migration has not been applied, the service falls
-- back to storing the result in extension_proof_sessions.proof_data
-- so checks still persist after page refresh.
--
-- Idempotent:
--   • CREATE TABLE IF NOT EXISTS
--   • CREATE UNIQUE INDEX IF NOT EXISTS
--   • CREATE OR REPLACE TRIGGER
--   • ALTER TABLE … ENABLE RLS
--   • DROP POLICY IF EXISTS + CREATE POLICY
-- ============================================================

create table if not exists public.live_website_check_results (
  id                uuid        primary key default gen_random_uuid(),

  -- ownership
  user_id           uuid        not null references public.users (id) on delete cascade,
  proof_session_id  uuid        not null references public.extension_proof_sessions (id) on delete cascade,

  -- check inputs
  website_url       text        not null,
  checker_version   text        not null default 'live-check-v1',

  -- check outputs
  final_url         text,
  status_code       int,
  response_time_ms  int,
  content_type      text,
  page_title        text,
  is_reachable      boolean     not null default false,
  confidence        text        not null default 'failed'
                                  check (confidence in ('high', 'medium', 'low', 'failed')),
  risk_flags        jsonb       not null default '[]'::jsonb,
  recruiter_summary text        not null default '',
  error_message     text,

  checked_at        timestamptz not null default now(),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

-- One check result per session (latest wins on upsert)
create unique index if not exists live_website_check_results_session_idx
  on public.live_website_check_results (proof_session_id);

create index if not exists live_website_check_results_user_idx
  on public.live_website_check_results (user_id);

-- Auto-update updated_at
create or replace trigger set_live_website_check_results_updated_at
  before update on public.live_website_check_results
  for each row execute function public.set_updated_at();

-- Row-level security
alter table public.live_website_check_results enable row level security;

drop policy if exists "Users can view their own live website check results" on public.live_website_check_results;
create policy "Users can view their own live website check results"
  on public.live_website_check_results for select
  using (auth.uid() = user_id);

drop policy if exists "Users can insert their own live website check results" on public.live_website_check_results;
create policy "Users can insert their own live website check results"
  on public.live_website_check_results for insert
  with check (auth.uid() = user_id);

drop policy if exists "Users can update their own live website check results" on public.live_website_check_results;
create policy "Users can update their own live website check results"
  on public.live_website_check_results for update
  using (auth.uid() = user_id);
