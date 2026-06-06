-- ============================================================
-- VeriBridge AI — Migration 047: Skill Evidence Pipelines
--
-- Persists per-student skill evidence pipelines and their
-- constituent evidence artifacts.
--
-- Tables created (in dependency order):
--   1. skill_evidence_pipelines   — aggregated per-skill view
--   2. skill_evidence_artifacts   — individual evidence items
--
-- All tables are idempotent (CREATE TABLE IF NOT EXISTS,
-- ADD COLUMN IF NOT EXISTS, CREATE INDEX IF NOT EXISTS).
-- RLS is enabled; service-role writes, students read own rows.
-- Recruiters read via the sanitized public API (no RLS override).
-- ============================================================


-- ============================================================
-- 1. skill_evidence_pipelines
-- ============================================================

create table if not exists public.skill_evidence_pipelines (
  id                  uuid        primary key default gen_random_uuid(),

  -- ownership
  student_id          uuid        references public.users (id) on delete cascade,
  profile_id          uuid        references public.student_profiles (id) on delete set null,

  -- skill identity
  skill_name          text        not null,
  skill_category      text        not null default 'technical',

  -- evidence aggregate
  confidence_score    integer     not null default 0
                        check (confidence_score between 0 and 100),
  support_status      text        not null default 'needs_review'
                        check (support_status in (
                          'strongly_supported',
                          'partially_supported',
                          'needs_review'
                        )),
  evidence_count      integer     not null default 0,

  -- evidence quality detail (stored as jsonb to allow evolution)
  strongest_proof     jsonb       not null default '{}'::jsonb,
  weakest_proof       jsonb       not null default '{}'::jsonb,
  missing_evidence    jsonb       not null default '[]'::jsonb,
  next_actions        jsonb       not null default '[]'::jsonb,
  evidence_sources    jsonb       not null default '[]'::jsonb,

  -- summaries
  recruiter_summary   text        not null default '',
  student_summary     text        not null default '',

  -- visibility (student controls, frontend-authoritative for MVP)
  visibility_status   text        not null default 'public'
                        check (visibility_status in ('public', 'protected', 'private')),

  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

-- Idempotent column additions (for manually-patched tables)
alter table public.skill_evidence_pipelines
  add column if not exists student_id       uuid references public.users (id) on delete cascade,
  add column if not exists profile_id       uuid references public.student_profiles (id) on delete set null,
  add column if not exists skill_category   text not null default 'technical',
  add column if not exists confidence_score integer not null default 0,
  add column if not exists support_status   text not null default 'needs_review',
  add column if not exists evidence_count   integer not null default 0,
  add column if not exists strongest_proof  jsonb not null default '{}'::jsonb,
  add column if not exists weakest_proof    jsonb not null default '{}'::jsonb,
  add column if not exists missing_evidence jsonb not null default '[]'::jsonb,
  add column if not exists next_actions     jsonb not null default '[]'::jsonb,
  add column if not exists evidence_sources jsonb not null default '[]'::jsonb,
  add column if not exists recruiter_summary text not null default '',
  add column if not exists student_summary   text not null default '',
  add column if not exists visibility_status text not null default 'public';

-- One pipeline per student per skill (upsert target)
create unique index if not exists skill_evidence_pipelines_student_skill_uidx
  on public.skill_evidence_pipelines (student_id, skill_name)
  where student_id is not null;

create index if not exists skill_evidence_pipelines_student_idx
  on public.skill_evidence_pipelines (student_id);

create index if not exists skill_evidence_pipelines_profile_idx
  on public.skill_evidence_pipelines (profile_id);

create index if not exists skill_evidence_pipelines_skill_name_idx
  on public.skill_evidence_pipelines (skill_name);

create index if not exists skill_evidence_pipelines_visibility_idx
  on public.skill_evidence_pipelines (visibility_status);

create index if not exists skill_evidence_pipelines_confidence_idx
  on public.skill_evidence_pipelines (confidence_score desc);

create or replace trigger set_skill_evidence_pipelines_updated_at
  before update on public.skill_evidence_pipelines
  for each row execute function public.set_updated_at();

alter table public.skill_evidence_pipelines enable row level security;

drop policy if exists "skill_evidence_pipelines: own row select"
  on public.skill_evidence_pipelines;
create policy "skill_evidence_pipelines: own row select"
  on public.skill_evidence_pipelines for select
  to authenticated
  using (student_id = (select auth.uid()));

drop policy if exists "skill_evidence_pipelines: own row insert"
  on public.skill_evidence_pipelines;
create policy "skill_evidence_pipelines: own row insert"
  on public.skill_evidence_pipelines for insert
  to authenticated
  with check (student_id = (select auth.uid()));

drop policy if exists "skill_evidence_pipelines: own row update"
  on public.skill_evidence_pipelines;
create policy "skill_evidence_pipelines: own row update"
  on public.skill_evidence_pipelines for update
  to authenticated
  using  (student_id = (select auth.uid()))
  with check (student_id = (select auth.uid()));

drop policy if exists "skill_evidence_pipelines: service role all"
  on public.skill_evidence_pipelines;
create policy "skill_evidence_pipelines: service role all"
  on public.skill_evidence_pipelines for all
  to service_role
  using (true)
  with check (true);


-- ============================================================
-- 2. skill_evidence_artifacts
-- ============================================================

create table if not exists public.skill_evidence_artifacts (
  id                  uuid        primary key default gen_random_uuid(),

  -- parent pipeline
  pipeline_id         uuid        not null references public.skill_evidence_pipelines (id) on delete cascade,

  -- optional source session link
  proof_session_id    uuid        references public.extension_proof_sessions (id) on delete set null,

  -- artifact identity
  source_type         text        not null
                        check (source_type in (
                          'github',
                          'workflow',
                          'keyframe',
                          'ocr',
                          'dom',
                          'qwen',
                          'transcript',
                          'document',
                          'review',
                          'certificate',
                          'coursework'
                        )),
  source_title        text        not null,
  project_name        text        not null default '',

  -- visibility (mirrors pipeline; can override per artifact)
  visibility          text        not null default 'public'
                        check (visibility in (
                          'public',
                          'protected',
                          'private',
                          'approved',
                          'locked',
                          'unavailable'
                        )),

  -- evidence quality
  confidence_score    integer     not null default 0
                        check (confidence_score between 0 and 100),
  relevance_to_skill  text        not null default '',
  proof_reason        text        not null default '',

  -- type-specific data (GitHub line refs, transcript segments, etc.)
  -- Security: never store raw tokens, signed URLs, service-role keys, or
  -- private storage paths in this column.
  artifact_data       jsonb       not null default '{}'::jsonb,

  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

-- Idempotent column additions
alter table public.skill_evidence_artifacts
  add column if not exists proof_session_id   uuid references public.extension_proof_sessions (id) on delete set null,
  add column if not exists project_name       text not null default '',
  add column if not exists confidence_score   integer not null default 0,
  add column if not exists relevance_to_skill text not null default '',
  add column if not exists proof_reason       text not null default '';

create index if not exists skill_evidence_artifacts_pipeline_idx
  on public.skill_evidence_artifacts (pipeline_id);

create index if not exists skill_evidence_artifacts_session_idx
  on public.skill_evidence_artifacts (proof_session_id);

create index if not exists skill_evidence_artifacts_source_type_idx
  on public.skill_evidence_artifacts (source_type);

create index if not exists skill_evidence_artifacts_visibility_idx
  on public.skill_evidence_artifacts (visibility);

create or replace trigger set_skill_evidence_artifacts_updated_at
  before update on public.skill_evidence_artifacts
  for each row execute function public.set_updated_at();

alter table public.skill_evidence_artifacts enable row level security;

drop policy if exists "skill_evidence_artifacts: pipeline owner select"
  on public.skill_evidence_artifacts;
create policy "skill_evidence_artifacts: pipeline owner select"
  on public.skill_evidence_artifacts for select
  to authenticated
  using (
    exists (
      select 1 from public.skill_evidence_pipelines sep
      where sep.id = pipeline_id
        and sep.student_id = (select auth.uid())
    )
  );

drop policy if exists "skill_evidence_artifacts: pipeline owner insert"
  on public.skill_evidence_artifacts;
create policy "skill_evidence_artifacts: pipeline owner insert"
  on public.skill_evidence_artifacts for insert
  to authenticated
  with check (
    exists (
      select 1 from public.skill_evidence_pipelines sep
      where sep.id = pipeline_id
        and sep.student_id = (select auth.uid())
    )
  );

drop policy if exists "skill_evidence_artifacts: pipeline owner update"
  on public.skill_evidence_artifacts;
create policy "skill_evidence_artifacts: pipeline owner update"
  on public.skill_evidence_artifacts for update
  to authenticated
  using (
    exists (
      select 1 from public.skill_evidence_pipelines sep
      where sep.id = pipeline_id
        and sep.student_id = (select auth.uid())
    )
  )
  with check (
    exists (
      select 1 from public.skill_evidence_pipelines sep
      where sep.id = pipeline_id
        and sep.student_id = (select auth.uid())
    )
  );

drop policy if exists "skill_evidence_artifacts: service role all"
  on public.skill_evidence_artifacts;
create policy "skill_evidence_artifacts: service role all"
  on public.skill_evidence_artifacts for all
  to service_role
  using (true)
  with check (true);
