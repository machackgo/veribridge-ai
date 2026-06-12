-- ============================================================
-- VeriBridge AI — Migration 049: Verified Build Report Core
--
-- Adds the Mythos MVP core schema for the Verified Build Report flow.
-- This migration intentionally does NOT modify:
--   - public.users
--   - public.audit_logs
--   - old passport / extension / marketplace tables
--
-- MVP scope:
--   repo evidence -> browser defense session -> transcript/keyframes
--   -> evidence items -> report claims -> tokenized public report
-- ============================================================

create extension if not exists pgcrypto;

-- ------------------------------------------------------------
-- Consent records
-- ------------------------------------------------------------
create table if not exists public.consent_records (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references public.users (id) on delete cascade,
  kind         text not null check (
    kind in (
      'recording',
      'publish_report',
      'publish_passport',
      'program_link',
      'outcomes'
    )
  ),
  granted      boolean not null default true,
  text_version text not null,
  metadata     jsonb not null default '{}',
  created_at   timestamptz not null default now()
);

create index if not exists consent_records_user_idx
  on public.consent_records (user_id);
create index if not exists consent_records_kind_idx
  on public.consent_records (kind);
create index if not exists consent_records_created_idx
  on public.consent_records (created_at);

alter table public.consent_records enable row level security;

drop policy if exists "consent_records: own row select"
  on public.consent_records;
create policy "consent_records: own row select"
  on public.consent_records
  for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "consent_records: service role all"
  on public.consent_records;
create policy "consent_records: service role all"
  on public.consent_records
  for all
  to service_role
  using (true)
  with check (true);

-- ------------------------------------------------------------
-- Data deletion requests
-- ------------------------------------------------------------
create table if not exists public.data_deletion_requests (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references public.users (id) on delete cascade,
  scope          text not null check (scope in ('project', 'account')),
  object_id      uuid,
  status         text not null default 'requested'
                 check (status in ('requested', 'processing', 'completed', 'failed')),
  manifest       jsonb not null default '{}',
  error_message  text,
  requested_at   timestamptz not null default now(),
  completed_at   timestamptz
);

create index if not exists data_deletion_requests_user_idx
  on public.data_deletion_requests (user_id);
create index if not exists data_deletion_requests_status_idx
  on public.data_deletion_requests (status);
create index if not exists data_deletion_requests_requested_idx
  on public.data_deletion_requests (requested_at);

alter table public.data_deletion_requests enable row level security;

drop policy if exists "data_deletion_requests: own row select"
  on public.data_deletion_requests;
create policy "data_deletion_requests: own row select"
  on public.data_deletion_requests
  for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "data_deletion_requests: own row insert"
  on public.data_deletion_requests;
create policy "data_deletion_requests: own row insert"
  on public.data_deletion_requests
  for insert
  to authenticated
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "data_deletion_requests: service role all"
  on public.data_deletion_requests;
create policy "data_deletion_requests: service role all"
  on public.data_deletion_requests
  for all
  to service_role
  using (true)
  with check (true);

-- ------------------------------------------------------------
-- Projects for Verified Build Reports
-- ------------------------------------------------------------
create table if not exists public.vbr_projects (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references public.users (id) on delete cascade,
  title           text not null,
  repo_url        text not null,
  repo_full_name  text,
  deployed_url    text,
  head_sha        text,
  status          text not null default 'draft'
                  check (
                    status in (
                      'draft',
                      'repo_ingested',
                      'url_checked',
                      'claims_ready',
                      'claims_confirmed',
                      'questions_ready',
                      'session_recording',
                      'session_uploaded',
                      'media_processed',
                      'judged',
                      'report_drafted',
                      'in_review',
                      'published',
                      'unpublished',
                      'failed'
                    )
                  ),
  metadata        jsonb not null default '{}',
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index if not exists vbr_projects_user_idx
  on public.vbr_projects (user_id);
create index if not exists vbr_projects_status_idx
  on public.vbr_projects (status);
create index if not exists vbr_projects_repo_idx
  on public.vbr_projects (repo_full_name);

alter table public.vbr_projects enable row level security;

drop policy if exists "vbr_projects: own row select"
  on public.vbr_projects;
create policy "vbr_projects: own row select"
  on public.vbr_projects
  for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "vbr_projects: own row insert"
  on public.vbr_projects;
create policy "vbr_projects: own row insert"
  on public.vbr_projects
  for insert
  to authenticated
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "vbr_projects: service role all"
  on public.vbr_projects;
create policy "vbr_projects: service role all"
  on public.vbr_projects
  for all
  to service_role
  using (true)
  with check (true);

-- ------------------------------------------------------------
-- GitHub / URL analysis
-- ------------------------------------------------------------
create table if not exists public.vbr_repo_analyses (
  id                     uuid primary key default gen_random_uuid(),
  project_id             uuid not null references public.vbr_projects (id) on delete cascade,
  head_sha               text,
  facts                  jsonb not null default '{}',
  fork                   boolean,
  authorship_match_pct   numeric,
  computed_at            timestamptz not null default now()
);

create index if not exists vbr_repo_analyses_project_idx
  on public.vbr_repo_analyses (project_id);
create index if not exists vbr_repo_analyses_head_sha_idx
  on public.vbr_repo_analyses (head_sha);

alter table public.vbr_repo_analyses enable row level security;

drop policy if exists "vbr_repo_analyses: own row select"
  on public.vbr_repo_analyses;
create policy "vbr_repo_analyses: own row select"
  on public.vbr_repo_analyses
  for select
  to authenticated
  using (
    exists (
      select 1
      from public.vbr_projects p
      where p.id = project_id
        and p.user_id::text = (select auth.uid())::text
    )
  );

drop policy if exists "vbr_repo_analyses: service role all"
  on public.vbr_repo_analyses;
create policy "vbr_repo_analyses: service role all"
  on public.vbr_repo_analyses
  for all
  to service_role
  using (true)
  with check (true);

create table if not exists public.vbr_deployed_url_checks (
  id              uuid primary key default gen_random_uuid(),
  project_id      uuid not null references public.vbr_projects (id) on delete cascade,
  url             text not null,
  status_code     integer,
  title           text,
  screenshot_path text,
  phash           text,
  result          text not null default 'unknown'
                  check (result in ('pass', 'note', 'unable', 'unknown')),
  detail          text,
  checked_at      timestamptz not null default now()
);

create index if not exists vbr_deployed_url_checks_project_idx
  on public.vbr_deployed_url_checks (project_id);
create index if not exists vbr_deployed_url_checks_checked_idx
  on public.vbr_deployed_url_checks (checked_at);

alter table public.vbr_deployed_url_checks enable row level security;

drop policy if exists "vbr_deployed_url_checks: own row select"
  on public.vbr_deployed_url_checks;
create policy "vbr_deployed_url_checks: own row select"
  on public.vbr_deployed_url_checks
  for select
  to authenticated
  using (
    exists (
      select 1
      from public.vbr_projects p
      where p.id = project_id
        and p.user_id::text = (select auth.uid())::text
    )
  );

drop policy if exists "vbr_deployed_url_checks: service role all"
  on public.vbr_deployed_url_checks;
create policy "vbr_deployed_url_checks: service role all"
  on public.vbr_deployed_url_checks
  for all
  to service_role
  using (true)
  with check (true);

-- ------------------------------------------------------------
-- Claims and sessions
-- ------------------------------------------------------------
create table if not exists public.vbr_project_claims (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid not null references public.vbr_projects (id) on delete cascade,
  claim_text  text not null,
  source      text not null default 'llm_proposed'
              check (source in ('llm_proposed', 'student_edited', 'student_added')),
  status      text not null default 'proposed'
              check (status in ('proposed', 'confirmed', 'dropped')),
  anchors     jsonb not null default '[]',
  skill_refs  jsonb not null default '[]',
  sort_order  integer not null default 0,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists vbr_project_claims_project_idx
  on public.vbr_project_claims (project_id);
create index if not exists vbr_project_claims_status_idx
  on public.vbr_project_claims (status);

alter table public.vbr_project_claims enable row level security;

drop policy if exists "vbr_project_claims: own row select"
  on public.vbr_project_claims;
create policy "vbr_project_claims: own row select"
  on public.vbr_project_claims
  for select
  to authenticated
  using (
    exists (
      select 1
      from public.vbr_projects p
      where p.id = project_id
        and p.user_id::text = (select auth.uid())::text
    )
  );

drop policy if exists "vbr_project_claims: own row update"
  on public.vbr_project_claims;
create policy "vbr_project_claims: own row update"
  on public.vbr_project_claims
  for update
  to authenticated
  using (
    exists (
      select 1
      from public.vbr_projects p
      where p.id = project_id
        and p.user_id::text = (select auth.uid())::text
    )
  )
  with check (
    exists (
      select 1
      from public.vbr_projects p
      where p.id = project_id
        and p.user_id::text = (select auth.uid())::text
    )
  );

drop policy if exists "vbr_project_claims: service role all"
  on public.vbr_project_claims;
create policy "vbr_project_claims: service role all"
  on public.vbr_project_claims
  for all
  to service_role
  using (true)
  with check (true);

create table if not exists public.vbr_verification_sessions (
  id             uuid primary key default gen_random_uuid(),
  project_id     uuid not null references public.vbr_projects (id) on delete cascade,
  attempt_no     integer not null default 1,
  status         text not null default 'created'
                 check (status in ('created', 'recording', 'uploaded', 'processed', 'discarded', 'failed')),
  started_at     timestamptz,
  ended_at       timestamptz,
  duration_s     integer,
  video_path     text,
  webcam_present boolean not null default false,
  telemetry      jsonb not null default '{}',
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  unique (project_id, attempt_no)
);

create index if not exists vbr_verification_sessions_project_idx
  on public.vbr_verification_sessions (project_id);
create index if not exists vbr_verification_sessions_status_idx
  on public.vbr_verification_sessions (status);

alter table public.vbr_verification_sessions enable row level security;

drop policy if exists "vbr_verification_sessions: own row select"
  on public.vbr_verification_sessions;
create policy "vbr_verification_sessions: own row select"
  on public.vbr_verification_sessions
  for select
  to authenticated
  using (
    exists (
      select 1
      from public.vbr_projects p
      where p.id = project_id
        and p.user_id::text = (select auth.uid())::text
    )
  );

drop policy if exists "vbr_verification_sessions: service role all"
  on public.vbr_verification_sessions;
create policy "vbr_verification_sessions: service role all"
  on public.vbr_verification_sessions
  for all
  to service_role
  using (true)
  with check (true);

create table if not exists public.vbr_session_questions (
  id            uuid primary key default gen_random_uuid(),
  session_id    uuid not null references public.vbr_verification_sessions (id) on delete cascade,
  sort_order    integer not null default 0,
  question_text text not null,
  target_ref    jsonb not null default '{}',
  claim_ids     jsonb not null default '[]',
  asked_at_s    numeric,
  answered      boolean not null default false,
  created_at    timestamptz not null default now()
);

create index if not exists vbr_session_questions_session_idx
  on public.vbr_session_questions (session_id);
create index if not exists vbr_session_questions_order_idx
  on public.vbr_session_questions (session_id, sort_order);

alter table public.vbr_session_questions enable row level security;

drop policy if exists "vbr_session_questions: own row select"
  on public.vbr_session_questions;
create policy "vbr_session_questions: own row select"
  on public.vbr_session_questions
  for select
  to authenticated
  using (
    exists (
      select 1
      from public.vbr_verification_sessions s
      join public.vbr_projects p on p.id = s.project_id
      where s.id = session_id
        and p.user_id::text = (select auth.uid())::text
    )
  );

drop policy if exists "vbr_session_questions: service role all"
  on public.vbr_session_questions;
create policy "vbr_session_questions: service role all"
  on public.vbr_session_questions
  for all
  to service_role
  using (true)
  with check (true);

create table if not exists public.vbr_video_chunks (
  id           uuid primary key default gen_random_uuid(),
  session_id   uuid not null references public.vbr_verification_sessions (id) on delete cascade,
  chunk_index  integer not null,
  storage_path text not null,
  bytes        integer,
  sha256       text,
  received_at  timestamptz not null default now(),
  unique (session_id, chunk_index)
);

create index if not exists vbr_video_chunks_session_idx
  on public.vbr_video_chunks (session_id);

alter table public.vbr_video_chunks enable row level security;

drop policy if exists "vbr_video_chunks: service role all"
  on public.vbr_video_chunks;
create policy "vbr_video_chunks: service role all"
  on public.vbr_video_chunks
  for all
  to service_role
  using (true)
  with check (true);

-- ------------------------------------------------------------
-- Transcript and keyframes
-- ------------------------------------------------------------
create table if not exists public.vbr_transcripts (
  id          uuid primary key default gen_random_uuid(),
  session_id  uuid not null unique references public.vbr_verification_sessions (id) on delete cascade,
  provider    text,
  language    text,
  full_text   text,
  raw         jsonb not null default '{}',
  created_at  timestamptz not null default now()
);

create index if not exists vbr_transcripts_session_idx
  on public.vbr_transcripts (session_id);

alter table public.vbr_transcripts enable row level security;

drop policy if exists "vbr_transcripts: own row select"
  on public.vbr_transcripts;
create policy "vbr_transcripts: own row select"
  on public.vbr_transcripts
  for select
  to authenticated
  using (
    exists (
      select 1
      from public.vbr_verification_sessions s
      join public.vbr_projects p on p.id = s.project_id
      where s.id = session_id
        and p.user_id::text = (select auth.uid())::text
    )
  );

drop policy if exists "vbr_transcripts: service role all"
  on public.vbr_transcripts;
create policy "vbr_transcripts: service role all"
  on public.vbr_transcripts
  for all
  to service_role
  using (true)
  with check (true);

create table if not exists public.vbr_transcript_segments (
  id             uuid primary key default gen_random_uuid(),
  transcript_id  uuid not null references public.vbr_transcripts (id) on delete cascade,
  question_id    uuid references public.vbr_session_questions (id) on delete set null,
  start_s        numeric not null,
  end_s          numeric not null,
  text           text not null,
  created_at     timestamptz not null default now()
);

create index if not exists vbr_transcript_segments_transcript_idx
  on public.vbr_transcript_segments (transcript_id);
create index if not exists vbr_transcript_segments_question_idx
  on public.vbr_transcript_segments (question_id);
create index if not exists vbr_transcript_segments_time_idx
  on public.vbr_transcript_segments (transcript_id, start_s);

alter table public.vbr_transcript_segments enable row level security;

drop policy if exists "vbr_transcript_segments: own row select"
  on public.vbr_transcript_segments;
create policy "vbr_transcript_segments: own row select"
  on public.vbr_transcript_segments
  for select
  to authenticated
  using (
    exists (
      select 1
      from public.vbr_transcripts t
      join public.vbr_verification_sessions s on s.id = t.session_id
      join public.vbr_projects p on p.id = s.project_id
      where t.id = transcript_id
        and p.user_id::text = (select auth.uid())::text
    )
  );

drop policy if exists "vbr_transcript_segments: service role all"
  on public.vbr_transcript_segments;
create policy "vbr_transcript_segments: service role all"
  on public.vbr_transcript_segments
  for all
  to service_role
  using (true)
  with check (true);

create table if not exists public.vbr_keyframes (
  id               uuid primary key default gen_random_uuid(),
  session_id       uuid not null references public.vbr_verification_sessions (id) on delete cascade,
  ts_s             numeric not null,
  storage_path     text not null,
  phash            text,
  near_question_id uuid references public.vbr_session_questions (id) on delete set null,
  vision_summary   jsonb,
  created_at       timestamptz not null default now()
);

create index if not exists vbr_keyframes_session_idx
  on public.vbr_keyframes (session_id);
create index if not exists vbr_keyframes_time_idx
  on public.vbr_keyframes (session_id, ts_s);
create index if not exists vbr_keyframes_question_idx
  on public.vbr_keyframes (near_question_id);

alter table public.vbr_keyframes enable row level security;

drop policy if exists "vbr_keyframes: own row select"
  on public.vbr_keyframes;
create policy "vbr_keyframes: own row select"
  on public.vbr_keyframes
  for select
  to authenticated
  using (
    exists (
      select 1
      from public.vbr_verification_sessions s
      join public.vbr_projects p on p.id = s.project_id
      where s.id = session_id
        and p.user_id::text = (select auth.uid())::text
    )
  );

drop policy if exists "vbr_keyframes: service role all"
  on public.vbr_keyframes;
create policy "vbr_keyframes: service role all"
  on public.vbr_keyframes
  for all
  to service_role
  using (true)
  with check (true);

-- ------------------------------------------------------------
-- Evidence, judgments, checks, reports
-- ------------------------------------------------------------
create table if not exists public.vbr_evidence_items (
  id             uuid primary key default gen_random_uuid(),
  project_id     uuid not null references public.vbr_projects (id) on delete cascade,
  evidence_type  text not null check (
    evidence_type in (
      'commit',
      'diff',
      'file',
      'repo_stat',
      'url_check',
      'video_segment',
      'transcript_segment',
      'keyframe',
      'session_telemetry',
      'dom_event'
    )
  ),
  source         text not null,
  evidence_class text not null check (evidence_class in ('artifact', 'process')),
  interpretation text not null check (interpretation in ('deterministic', 'ai')),
  visibility     text not null default 'internal' check (visibility in ('public', 'internal')),
  sensitivity    text not null default 'normal' check (sensitivity in ('normal', 'sensitive')),
  pointer        jsonb not null default '{}',
  summary        text,
  created_at     timestamptz not null default now()
);

create index if not exists vbr_evidence_items_project_idx
  on public.vbr_evidence_items (project_id);
create index if not exists vbr_evidence_items_type_idx
  on public.vbr_evidence_items (evidence_type);
create index if not exists vbr_evidence_items_visibility_idx
  on public.vbr_evidence_items (visibility);

alter table public.vbr_evidence_items enable row level security;

drop policy if exists "vbr_evidence_items: own row select"
  on public.vbr_evidence_items;
create policy "vbr_evidence_items: own row select"
  on public.vbr_evidence_items
  for select
  to authenticated
  using (
    exists (
      select 1
      from public.vbr_projects p
      where p.id = project_id
        and p.user_id::text = (select auth.uid())::text
    )
  );

drop policy if exists "vbr_evidence_items: service role all"
  on public.vbr_evidence_items;
create policy "vbr_evidence_items: service role all"
  on public.vbr_evidence_items
  for all
  to service_role
  using (true)
  with check (true);

create table if not exists public.vbr_per_question_judgments (
  id                 uuid primary key default gen_random_uuid(),
  question_id         uuid not null references public.vbr_session_questions (id) on delete cascade,
  quality             text not null check (quality in ('demonstrated', 'partial', 'not_demonstrated', 'unable')),
  rationale           text,
  evidence_item_ids   jsonb not null default '[]',
  notable_quote       text,
  inconsistencies     jsonb not null default '[]',
  model               text,
  prompt_version      text,
  raw                 jsonb not null default '{}',
  created_at          timestamptz not null default now()
);

create index if not exists vbr_per_question_judgments_question_idx
  on public.vbr_per_question_judgments (question_id);

alter table public.vbr_per_question_judgments enable row level security;

drop policy if exists "vbr_per_question_judgments: own row select"
  on public.vbr_per_question_judgments;
create policy "vbr_per_question_judgments: own row select"
  on public.vbr_per_question_judgments
  for select
  to authenticated
  using (
    exists (
      select 1
      from public.vbr_session_questions q
      join public.vbr_verification_sessions s on s.id = q.session_id
      join public.vbr_projects p on p.id = s.project_id
      where q.id = question_id
        and p.user_id::text = (select auth.uid())::text
    )
  );

drop policy if exists "vbr_per_question_judgments: service role all"
  on public.vbr_per_question_judgments;
create policy "vbr_per_question_judgments: service role all"
  on public.vbr_per_question_judgments
  for all
  to service_role
  using (true)
  with check (true);

create table if not exists public.vbr_authenticity_checks (
  id                uuid primary key default gen_random_uuid(),
  project_id         uuid not null references public.vbr_projects (id) on delete cascade,
  check_key          text not null,
  result             text not null check (result in ('pass', 'note', 'unable')),
  detail             text,
  evidence_item_ids  jsonb not null default '[]',
  created_at         timestamptz not null default now()
);

create index if not exists vbr_authenticity_checks_project_idx
  on public.vbr_authenticity_checks (project_id);
create index if not exists vbr_authenticity_checks_key_idx
  on public.vbr_authenticity_checks (check_key);

alter table public.vbr_authenticity_checks enable row level security;

drop policy if exists "vbr_authenticity_checks: own row select"
  on public.vbr_authenticity_checks;
create policy "vbr_authenticity_checks: own row select"
  on public.vbr_authenticity_checks
  for select
  to authenticated
  using (
    exists (
      select 1
      from public.vbr_projects p
      where p.id = project_id
        and p.user_id::text = (select auth.uid())::text
    )
  );

drop policy if exists "vbr_authenticity_checks: service role all"
  on public.vbr_authenticity_checks;
create policy "vbr_authenticity_checks: service role all"
  on public.vbr_authenticity_checks
  for all
  to service_role
  using (true)
  with check (true);

create table if not exists public.vbr_reports (
  id              uuid primary key default gen_random_uuid(),
  project_id      uuid not null references public.vbr_projects (id) on delete cascade,
  version         integer not null default 1,
  body            jsonb not null default '{}',
  public_token    text unique,
  status          text not null default 'draft'
                  check (status in ('draft', 'in_review', 'published', 'unpublished', 'failed')),
  human_reviewed  boolean not null default false,
  rerecord_count  integer not null default 0,
  view_count      integer not null default 0,
  published_at    timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (project_id, version)
);

create index if not exists vbr_reports_project_idx
  on public.vbr_reports (project_id);
create index if not exists vbr_reports_status_idx
  on public.vbr_reports (status);
create index if not exists vbr_reports_public_token_idx
  on public.vbr_reports (public_token);

alter table public.vbr_reports enable row level security;

drop policy if exists "vbr_reports: own row select"
  on public.vbr_reports;
create policy "vbr_reports: own row select"
  on public.vbr_reports
  for select
  to authenticated
  using (
    exists (
      select 1
      from public.vbr_projects p
      where p.id = project_id
        and p.user_id::text = (select auth.uid())::text
    )
  );

drop policy if exists "vbr_reports: service role all"
  on public.vbr_reports;
create policy "vbr_reports: service role all"
  on public.vbr_reports
  for all
  to service_role
  using (true)
  with check (true);

create table if not exists public.vbr_report_claims (
  id                 uuid primary key default gen_random_uuid(),
  report_id           uuid not null references public.vbr_reports (id) on delete cascade,
  claim_id            uuid not null references public.vbr_project_claims (id) on delete cascade,
  tier                text not null check (
    tier in (
      'demonstrated',
      'partially_demonstrated',
      'not_assessed',
      'insufficient_evidence'
    )
  ),
  inconsistency_noted boolean not null default false,
  evidence_item_ids   jsonb not null default '[]',
  created_at          timestamptz not null default now(),
  unique (report_id, claim_id)
);

create index if not exists vbr_report_claims_report_idx
  on public.vbr_report_claims (report_id);
create index if not exists vbr_report_claims_claim_idx
  on public.vbr_report_claims (claim_id);
create index if not exists vbr_report_claims_tier_idx
  on public.vbr_report_claims (tier);

alter table public.vbr_report_claims enable row level security;

drop policy if exists "vbr_report_claims: own row select"
  on public.vbr_report_claims;
create policy "vbr_report_claims: own row select"
  on public.vbr_report_claims
  for select
  to authenticated
  using (
    exists (
      select 1
      from public.vbr_reports r
      join public.vbr_projects p on p.id = r.project_id
      where r.id = report_id
        and p.user_id::text = (select auth.uid())::text
    )
  );

drop policy if exists "vbr_report_claims: service role all"
  on public.vbr_report_claims;
create policy "vbr_report_claims: service role all"
  on public.vbr_report_claims
  for all
  to service_role
  using (true)
  with check (true);

create table if not exists public.vbr_report_views (
  id          uuid primary key default gen_random_uuid(),
  report_id   uuid not null references public.vbr_reports (id) on delete cascade,
  referrer    text,
  ip_hash     text,
  ua_class    text,
  dwell_s     integer,
  viewed_at   timestamptz not null default now()
);

create index if not exists vbr_report_views_report_idx
  on public.vbr_report_views (report_id);
create index if not exists vbr_report_views_viewed_idx
  on public.vbr_report_views (viewed_at);

alter table public.vbr_report_views enable row level security;

drop policy if exists "vbr_report_views: service role all"
  on public.vbr_report_views;
create policy "vbr_report_views: service role all"
  on public.vbr_report_views
  for all
  to service_role
  using (true)
  with check (true);

create table if not exists public.vbr_recruiter_leads (
  id               uuid primary key default gen_random_uuid(),
  source_report_id uuid references public.vbr_reports (id) on delete set null,
  email            text not null,
  company          text,
  message          text,
  wants            text not null default 'updates'
                   check (wants in ('updates', 'verify_candidates', 'other')),
  metadata         jsonb not null default '{}',
  created_at       timestamptz not null default now()
);

create index if not exists vbr_recruiter_leads_email_idx
  on public.vbr_recruiter_leads (email);
create index if not exists vbr_recruiter_leads_report_idx
  on public.vbr_recruiter_leads (source_report_id);
create index if not exists vbr_recruiter_leads_created_idx
  on public.vbr_recruiter_leads (created_at);

alter table public.vbr_recruiter_leads enable row level security;

drop policy if exists "vbr_recruiter_leads: service role all"
  on public.vbr_recruiter_leads;
create policy "vbr_recruiter_leads: service role all"
  on public.vbr_recruiter_leads
  for all
  to service_role
  using (true)
  with check (true);

drop trigger if exists set_vbr_projects_updated_at on public.vbr_projects;
create trigger set_vbr_projects_updated_at
before update on public.vbr_projects
for each row execute function public.set_updated_at();

drop trigger if exists set_vbr_project_claims_updated_at on public.vbr_project_claims;
create trigger set_vbr_project_claims_updated_at
before update on public.vbr_project_claims
for each row execute function public.set_updated_at();

drop trigger if exists set_vbr_verification_sessions_updated_at on public.vbr_verification_sessions;
create trigger set_vbr_verification_sessions_updated_at
before update on public.vbr_verification_sessions
for each row execute function public.set_updated_at();

drop trigger if exists set_vbr_reports_updated_at on public.vbr_reports;
create trigger set_vbr_reports_updated_at
before update on public.vbr_reports
for each row execute function public.set_updated_at();
