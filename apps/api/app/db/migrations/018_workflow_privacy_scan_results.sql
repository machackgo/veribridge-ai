-- ============================================================
-- VeriBridge AI — Migration 018: Workflow Privacy Scan Results
--
-- Stores the result of an automated privacy scan run against
-- every uploaded workflow proof session.  One row per session
-- (upserted on proof_session_id).
--
-- Status values:
--   clean    — no sensitive data detected
--   redacted — extension/backend already masked sensitive fields
--   flagged  — unredacted sensitive patterns were found; proof
--              is hidden from recruiter/public view pending review
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

create table if not exists public.workflow_privacy_scan_results (
  id                      uuid        primary key default gen_random_uuid(),

  -- ownership
  user_id                 uuid        not null references public.users (id) on delete cascade,
  proof_session_id        uuid        not null references public.extension_proof_sessions (id) on delete cascade,

  -- scan outcome
  status                  text        not null default 'clean'
                                        check (status in ('clean', 'redacted', 'flagged')),
  risk_flags              jsonb       not null default '[]'::jsonb,
  redacted_fields_count   integer     not null default 0,
  redacted_urls_count     integer     not null default 0,
  contains_sensitive_data boolean     not null default false,
  scan_summary            text        not null default '',

  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

-- Add any columns absent from a manually-patched table
alter table public.workflow_privacy_scan_results
  add column if not exists risk_flags              jsonb   not null default '[]'::jsonb,
  add column if not exists redacted_fields_count   integer not null default 0,
  add column if not exists redacted_urls_count     integer not null default 0,
  add column if not exists contains_sensitive_data boolean not null default false,
  add column if not exists scan_summary            text    not null default '';

-- One scan result per session (upsert target)
create unique index if not exists workflow_privacy_scan_results_session_idx
  on public.workflow_privacy_scan_results (proof_session_id);

create index if not exists workflow_privacy_scan_results_user_id_idx
  on public.workflow_privacy_scan_results (user_id);

create index if not exists workflow_privacy_scan_results_status_idx
  on public.workflow_privacy_scan_results (status);

create index if not exists workflow_privacy_scan_results_created_at_idx
  on public.workflow_privacy_scan_results (created_at);

-- updated_at trigger
create or replace trigger set_workflow_privacy_scan_results_updated_at
  before update on public.workflow_privacy_scan_results
  for each row execute function public.set_updated_at();

-- Row-level security
alter table public.workflow_privacy_scan_results enable row level security;

drop policy if exists "workflow_privacy_scan_results: own row select"
  on public.workflow_privacy_scan_results;
create policy "workflow_privacy_scan_results: own row select"
  on public.workflow_privacy_scan_results for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "workflow_privacy_scan_results: own row insert"
  on public.workflow_privacy_scan_results;
create policy "workflow_privacy_scan_results: own row insert"
  on public.workflow_privacy_scan_results for insert
  to authenticated
  with check (
    user_id::text = (select auth.uid())::text
    and exists (
      select 1
      from public.extension_proof_sessions eps
      where eps.id = proof_session_id
        and eps.user_id::text = (select auth.uid())::text
    )
  );

drop policy if exists "workflow_privacy_scan_results: own row update"
  on public.workflow_privacy_scan_results;
create policy "workflow_privacy_scan_results: own row update"
  on public.workflow_privacy_scan_results for update
  to authenticated
  using  (user_id::text = (select auth.uid())::text)
  with check (user_id::text = (select auth.uid())::text);
