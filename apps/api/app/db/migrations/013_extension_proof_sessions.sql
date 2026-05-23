-- ============================================================
-- VeriBridge AI — Migration 013: Extension Proof Sessions
--
-- Persists the Chrome-extension recording sessions created by the
-- student proof flow and the raw upload payloads delivered by the
-- extension after a recording.
--
-- This migration is fully idempotent:
--   • CREATE TABLE IF NOT EXISTS — safe to re-run on a fresh schema
--   • ADD COLUMN IF NOT EXISTS   — adds only columns absent from a
--     manually-patched table (the tested production scenario)
--   • CREATE INDEX IF NOT EXISTS — no-op when index already exists
--   • CREATE OR REPLACE TRIGGER  — always replaces the definition
--   • ALTER TABLE … ENABLE RLS   — idempotent in PostgreSQL
--   • DROP POLICY IF EXISTS      — clears stale policy before recreate
-- ============================================================

-- ── Table: extension_proof_sessions ───────────────────────────────────────────

create table if not exists public.extension_proof_sessions (
  id                      uuid        primary key default gen_random_uuid(),

  -- ownership
  user_id                 uuid        not null references public.users (id) on delete cascade,
  student_id              uuid                 references public.users (id) on delete set null,

  -- linked skill evidence record (anchor for this proof session)
  skill_evidence_id       uuid        not null references public.skill_evidence (id) on delete cascade,

  -- session metadata captured at creation time
  session_id              text,                        -- optional short/human token
  website_url             text,
  github_url              text,
  claimed_skills          jsonb       not null default '[]'::jsonb,
  student_note            text,
  title                   text,
  description             text,
  proof_objective         text,

  -- lifecycle status
  status                  text        not null default 'created'
                                        check (status in (
                                          'created',
                                          'waiting_for_extension',
                                          'recording',
                                          'uploaded_pending_analysis',
                                          'analyzing',
                                          'completed',
                                          'expired'
                                        )),

  -- extension handshake / redirect
  extension_launch_token  text,
  redirect_url            text,
  redirect_back_url       text,

  -- proof payload (stored inline for fast access by the analysis pipeline)
  proof_data              jsonb,
  proof_upload_id         uuid,
  proof_uploaded_at       timestamptz,

  -- convenience fields mirrored from the upload payload
  uploaded_at             timestamptz,
  final_note              text,
  upload_status           text        check (upload_status in (
                                        'pending',
                                        'processing',
                                        'completed',
                                        'failed'
                                      )),

  -- analysis output
  metadata                jsonb       not null default '{}'::jsonb,
  analysis_progress       jsonb       not null default '{}'::jsonb,
  error_message           text,

  -- recording window timestamps
  started_at              timestamptz,
  stopped_at              timestamptz,
  completed_at            timestamptz,

  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

-- Add any columns absent from a manually-patched table
alter table public.extension_proof_sessions
  add column if not exists student_id              uuid references public.users (id) on delete set null,
  add column if not exists session_id              text,
  add column if not exists website_url             text,
  add column if not exists github_url              text,
  add column if not exists claimed_skills          jsonb not null default '[]'::jsonb,
  add column if not exists student_note            text,
  add column if not exists title                   text,
  add column if not exists description             text,
  add column if not exists proof_objective         text,
  add column if not exists extension_launch_token  text,
  add column if not exists redirect_url            text,
  add column if not exists redirect_back_url       text,
  add column if not exists proof_data              jsonb,
  add column if not exists proof_upload_id         uuid,
  add column if not exists proof_uploaded_at       timestamptz,
  add column if not exists uploaded_at             timestamptz,
  add column if not exists final_note              text,
  add column if not exists upload_status           text,
  add column if not exists metadata                jsonb not null default '{}'::jsonb,
  add column if not exists analysis_progress       jsonb not null default '{}'::jsonb,
  add column if not exists error_message           text,
  add column if not exists started_at              timestamptz,
  add column if not exists stopped_at              timestamptz,
  add column if not exists completed_at            timestamptz;

-- Indexes
create index if not exists ext_proof_sessions_user_id_idx
  on public.extension_proof_sessions (user_id);

create index if not exists ext_proof_sessions_student_id_idx
  on public.extension_proof_sessions (student_id);

create index if not exists ext_proof_sessions_skill_evidence_idx
  on public.extension_proof_sessions (skill_evidence_id);

create index if not exists ext_proof_sessions_status_idx
  on public.extension_proof_sessions (status);

create index if not exists ext_proof_sessions_proof_upload_id_idx
  on public.extension_proof_sessions (proof_upload_id);

create index if not exists ext_proof_sessions_created_at_idx
  on public.extension_proof_sessions (created_at);

-- updated_at trigger
create or replace trigger set_ext_proof_sessions_updated_at
  before update on public.extension_proof_sessions
  for each row execute function public.set_updated_at();

-- Row-level security
alter table public.extension_proof_sessions enable row level security;

drop policy if exists "ext_proof_sessions: own row select"
  on public.extension_proof_sessions;
create policy "ext_proof_sessions: own row select"
  on public.extension_proof_sessions for select
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "ext_proof_sessions: own row insert"
  on public.extension_proof_sessions;
create policy "ext_proof_sessions: own row insert"
  on public.extension_proof_sessions for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

drop policy if exists "ext_proof_sessions: own row update"
  on public.extension_proof_sessions;
create policy "ext_proof_sessions: own row update"
  on public.extension_proof_sessions for update
  to authenticated
  using  ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

-- ── Table: extension_proof_uploads ────────────────────────────────────────────
-- Stores the raw extension upload payloads separately from the session row.
-- The current service writes proof_data inline into extension_proof_sessions;
-- this table is the target for a future upload-record split or replay.

create table if not exists public.extension_proof_uploads (
  id                  uuid        primary key default gen_random_uuid(),

  -- owning session and user
  session_id          uuid        not null references public.extension_proof_sessions (id) on delete cascade,
  user_id             uuid        not null references public.users (id) on delete cascade,
  student_id          uuid                 references public.users (id) on delete set null,

  -- raw proof payload (already masked by the extension + API layer)
  workflow_events     jsonb       not null default '[]'::jsonb,
  screenshots         jsonb,
  browser_metadata    jsonb,
  extension_version   text,

  -- recording window
  started_at          timestamptz,
  stopped_at          timestamptz,

  -- student annotation
  final_note          text,

  -- processing lifecycle
  upload_status       text        not null default 'pending'
                                    check (upload_status in (
                                      'pending',
                                      'processing',
                                      'completed',
                                      'failed'
                                    )),
  uploaded_at         timestamptz,
  metadata            jsonb       not null default '{}'::jsonb,
  analysis_progress   jsonb       not null default '{}'::jsonb,
  error_message       text,

  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

-- Add any columns absent from a manually-patched table
alter table public.extension_proof_uploads
  add column if not exists student_id          uuid references public.users (id) on delete set null,
  add column if not exists screenshots         jsonb,
  add column if not exists browser_metadata    jsonb,
  add column if not exists extension_version   text,
  add column if not exists started_at          timestamptz,
  add column if not exists stopped_at          timestamptz,
  add column if not exists final_note          text,
  add column if not exists uploaded_at         timestamptz,
  add column if not exists metadata            jsonb not null default '{}'::jsonb,
  add column if not exists analysis_progress   jsonb not null default '{}'::jsonb,
  add column if not exists error_message       text;

-- Indexes
create index if not exists ext_proof_uploads_session_id_idx
  on public.extension_proof_uploads (session_id);

create index if not exists ext_proof_uploads_user_id_idx
  on public.extension_proof_uploads (user_id);

create index if not exists ext_proof_uploads_student_id_idx
  on public.extension_proof_uploads (student_id);

create index if not exists ext_proof_uploads_upload_status_idx
  on public.extension_proof_uploads (upload_status);

create index if not exists ext_proof_uploads_created_at_idx
  on public.extension_proof_uploads (created_at);

-- updated_at trigger
create or replace trigger set_ext_proof_uploads_updated_at
  before update on public.extension_proof_uploads
  for each row execute function public.set_updated_at();

-- Row-level security
alter table public.extension_proof_uploads enable row level security;

drop policy if exists "ext_proof_uploads: own row select"
  on public.extension_proof_uploads;
create policy "ext_proof_uploads: own row select"
  on public.extension_proof_uploads for select
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "ext_proof_uploads: own row insert"
  on public.extension_proof_uploads;
create policy "ext_proof_uploads: own row insert"
  on public.extension_proof_uploads for insert
  to authenticated
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1
      from public.extension_proof_sessions eps
      where eps.id = session_id
        and eps.user_id = (select auth.uid())
    )
  );

drop policy if exists "ext_proof_uploads: own row update"
  on public.extension_proof_uploads;
create policy "ext_proof_uploads: own row update"
  on public.extension_proof_uploads for update
  to authenticated
  using  ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
