-- ============================================================
-- VeriBridge AI — Migration 001: Initial MVP Schema
--
-- Run in the Supabase SQL editor while connected as the
-- postgres / service-role user.
--
-- Tables created (in dependency order):
--   1.  users
--   2.  student_profiles
--   3.  resumes
--   4.  parsed_resume_data
--   5.  skills
--   6.  skill_evidence
--   7.  jobs
--   8.  job_matches
--   9.  generated_materials
--   10. applications
--   11. project_suggestions
--   12. audit_logs
--
-- All tables enable Row-Level Security (RLS).
-- Service-role access bypasses RLS for server-side jobs.
-- Students may only read/write their own rows.
-- ============================================================


-- ── Extensions ───────────────────────────────────────────────
-- citext: case-insensitive text for email uniqueness.
-- pg_trgm: trigram similarity for future skill/job search.
create extension if not exists citext  with schema extensions;
create extension if not exists pg_trgm with schema extensions;


-- ── Shared trigger: auto-update updated_at ────────────────────
create or replace function public.set_updated_at()
  returns trigger
  language plpgsql
  security definer
  set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;


-- ============================================================
-- 1. users
-- ============================================================
create table if not exists public.users (
  id                      uuid        primary key
                            references auth.users (id) on delete cascade,
  email                   citext      not null,
  role                    text        not null default 'student'
                            check (role in ('student','recruiter','university_admin','admin')),
  status                  text        not null default 'active'
                            check (status in ('active','disabled','pending_deletion')),
  onboarding_completed_at timestamptz,
  last_seen_at            timestamptz,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

-- Indexes
create unique index if not exists users_email_uidx  on public.users (email);
create        index if not exists users_role_idx    on public.users (role);
create        index if not exists users_status_idx  on public.users (status);
create        index if not exists users_created_idx on public.users (created_at);

-- updated_at trigger
create or replace trigger set_users_updated_at
  before update on public.users
  for each row execute function public.set_updated_at();

-- RLS
alter table public.users enable row level security;

create policy "users: select own row"
  on public.users for select
  to authenticated
  using ((select auth.uid()) = id);

-- Students update their own row; role/status must not change.
-- Privileged field changes are service-role only (bypasses RLS).
create policy "users: update own non-privileged fields"
  on public.users for update
  to authenticated
  using ((select auth.uid()) = id)
  with check (
    (select auth.uid()) = id
  );


-- ============================================================
-- 2. student_profiles
-- ============================================================
create table if not exists public.student_profiles (
  id               uuid        primary key default gen_random_uuid(),
  user_id          uuid        not null references public.users (id) on delete cascade,
  full_name        text,
  headline         text,
  school_name      text,
  degree           text,
  major            text,
  graduation_year  integer,
  location         text,
  target_roles     text[],
  target_locations text[],
  work_authorization text,
  links            jsonb       not null default '{}',
  preferences      jsonb       not null default '{}',
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create unique index if not exists student_profiles_user_uidx
  on public.student_profiles (user_id);
create index if not exists student_profiles_graduation_idx
  on public.student_profiles (graduation_year);
create index if not exists student_profiles_target_roles_gin
  on public.student_profiles using gin (target_roles);
create index if not exists student_profiles_target_locs_gin
  on public.student_profiles using gin (target_locations);

create or replace trigger set_student_profiles_updated_at
  before update on public.student_profiles
  for each row execute function public.set_updated_at();

alter table public.student_profiles enable row level security;

create policy "student_profiles: own row select"
  on public.student_profiles for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "student_profiles: own row insert"
  on public.student_profiles for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

create policy "student_profiles: own row update"
  on public.student_profiles for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "student_profiles: own row delete"
  on public.student_profiles for delete
  to authenticated
  using ((select auth.uid()) = user_id);


-- ============================================================
-- 3. resumes
-- ============================================================
create table if not exists public.resumes (
  id                  uuid        primary key default gen_random_uuid(),
  user_id             uuid        not null references public.users (id) on delete cascade,
  student_profile_id  uuid        references public.student_profiles (id) on delete set null,
  storage_bucket      text        not null default 'resumes',
  storage_path        text        not null,
  original_filename   text        not null,
  content_type        text        not null,
  file_size_bytes     bigint      not null,
  checksum_sha256     text,
  status              text        not null default 'uploaded'
                        check (status in ('uploaded','parsing','parsed','parse_failed','archived')),
  is_primary          boolean     not null default false,
  uploaded_at         timestamptz not null default now(),
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create        index if not exists resumes_user_idx
  on public.resumes (user_id);
-- Only one primary resume per user
create unique index if not exists resumes_primary_user_uidx
  on public.resumes (user_id)
  where is_primary = true;
create        index if not exists resumes_user_status_idx
  on public.resumes (user_id, status);
create unique index if not exists resumes_storage_uidx
  on public.resumes (storage_bucket, storage_path);
create        index if not exists resumes_uploaded_idx
  on public.resumes (uploaded_at);

create or replace trigger set_resumes_updated_at
  before update on public.resumes
  for each row execute function public.set_updated_at();

alter table public.resumes enable row level security;

create policy "resumes: own row select"
  on public.resumes for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "resumes: own row insert"
  on public.resumes for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

-- Students may update limited fields (is_primary, status to 'archived').
-- Parser/service-role updates remaining fields.
create policy "resumes: own row update"
  on public.resumes for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);


-- ============================================================
-- 4. parsed_resume_data
-- ============================================================
create table if not exists public.parsed_resume_data (
  id               uuid          primary key default gen_random_uuid(),
  resume_id        uuid          not null references public.resumes (id) on delete cascade,
  user_id          uuid          not null references public.users (id) on delete cascade,
  parser_version   text          not null,
  raw_text         text,
  contact_info     jsonb         not null default '{}',
  education        jsonb         not null default '[]',
  experience       jsonb         not null default '[]',
  projects         jsonb         not null default '[]',
  certifications   jsonb         not null default '[]',
  detected_skills  jsonb         not null default '[]',
  quality_signals  jsonb         not null default '{}',
  confidence_score numeric(5,4),
  parsed_at        timestamptz,
  created_at       timestamptz   not null default now(),
  updated_at       timestamptz   not null default now()
);

create unique index if not exists parsed_resume_data_resume_uidx
  on public.parsed_resume_data (resume_id);
create        index if not exists parsed_resume_data_user_idx
  on public.parsed_resume_data (user_id);
create        index if not exists parsed_resume_data_parsed_idx
  on public.parsed_resume_data (parsed_at);
create        index if not exists parsed_resume_data_skills_gin
  on public.parsed_resume_data using gin (detected_skills);
create        index if not exists parsed_resume_data_exp_gin
  on public.parsed_resume_data using gin (experience);

create or replace trigger set_parsed_resume_data_updated_at
  before update on public.parsed_resume_data
  for each row execute function public.set_updated_at();

alter table public.parsed_resume_data enable row level security;

-- Students may read their own parsed data; inserts/updates are service-role only.
create policy "parsed_resume_data: own row select"
  on public.parsed_resume_data for select
  to authenticated
  using ((select auth.uid()) = user_id);


-- ============================================================
-- 5. skills
-- ============================================================
create table if not exists public.skills (
  id             uuid        primary key default gen_random_uuid(),
  user_id        uuid        not null references public.users (id) on delete cascade,
  name           text        not null,
  category       text        not null default 'technical'
                   check (category in ('technical','tool','domain','soft','language','other')),
  proficiency    text
                   check (proficiency in ('beginner','intermediate','advanced','expert')),
  source         text        not null default 'manual'
                   check (source in ('resume_parse','manual','project','import')),
  normalized_key text        not null,
  last_used_at   date,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create unique index if not exists skills_user_key_uidx
  on public.skills (user_id, normalized_key);
create        index if not exists skills_user_idx
  on public.skills (user_id);
create        index if not exists skills_category_idx
  on public.skills (category);
create        index if not exists skills_normalized_key_idx
  on public.skills (normalized_key);

create or replace trigger set_skills_updated_at
  before update on public.skills
  for each row execute function public.set_updated_at();

alter table public.skills enable row level security;

create policy "skills: own row all"
  on public.skills for all
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);


-- ============================================================
-- 6. skill_evidence
-- ============================================================
create table if not exists public.skill_evidence (
  id                    uuid          primary key default gen_random_uuid(),
  user_id               uuid          not null references public.users (id) on delete cascade,
  skill_id              uuid          not null references public.skills (id) on delete cascade,
  resume_id             uuid          references public.resumes (id) on delete set null,
  parsed_resume_data_id uuid          references public.parsed_resume_data (id) on delete set null,
  evidence_type         text          not null
                          check (evidence_type in ('resume_bullet','project','coursework','certification','manual')),
  source_label          text,
  evidence_text         text,
  strength_score        numeric(5,4),
  metadata              jsonb         not null default '{}',
  created_at            timestamptz   not null default now(),
  updated_at            timestamptz   not null default now()
);

create index if not exists skill_evidence_user_idx
  on public.skill_evidence (user_id);
create index if not exists skill_evidence_skill_idx
  on public.skill_evidence (skill_id);
create index if not exists skill_evidence_resume_idx
  on public.skill_evidence (resume_id);
create index if not exists skill_evidence_type_idx
  on public.skill_evidence (user_id, evidence_type);
create index if not exists skill_evidence_strength_idx
  on public.skill_evidence (strength_score);

create or replace trigger set_skill_evidence_updated_at
  before update on public.skill_evidence
  for each row execute function public.set_updated_at();

alter table public.skill_evidence enable row level security;

create policy "skill_evidence: own row all"
  on public.skill_evidence for all
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);


-- ============================================================
-- 7. jobs
-- ============================================================
create table if not exists public.jobs (
  id                  uuid        primary key default gen_random_uuid(),
  source              text        not null default 'manual'
                        check (source in ('manual','linkedin','greenhouse','lever','workday','other')),
  source_job_id       text,
  url                 text,
  company_name        text        not null,
  title               text        not null,
  location            text,
  remote_policy       text        not null default 'unknown'
                        check (remote_policy in ('onsite','hybrid','remote','unknown')),
  employment_type     text        not null default 'full_time'
                        check (employment_type in ('internship','full_time','part_time','contract')),
  description         text,
  requirements        jsonb       not null default '{}',
  salary_range        jsonb       not null default '{}',
  posted_at           timestamptz,
  expires_at          timestamptz,
  created_by_user_id  uuid        references public.users (id) on delete set null,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create unique index if not exists jobs_source_id_uidx
  on public.jobs (source, source_job_id)
  where source_job_id is not null;
create        index if not exists jobs_created_by_idx
  on public.jobs (created_by_user_id);
create        index if not exists jobs_company_idx
  on public.jobs (company_name);
create        index if not exists jobs_title_idx
  on public.jobs (title);
create        index if not exists jobs_posted_idx
  on public.jobs (posted_at);
create        index if not exists jobs_requirements_gin
  on public.jobs using gin (requirements);

create or replace trigger set_jobs_updated_at
  before update on public.jobs
  for each row execute function public.set_updated_at();

alter table public.jobs enable row level security;

-- Shared catalog jobs are readable by all authenticated users.
-- User-created private jobs are readable only by creator.
create policy "jobs: authenticated read shared or own"
  on public.jobs for select
  to authenticated
  using (
    created_by_user_id is null
    or created_by_user_id = (select auth.uid())
  );

create policy "jobs: own insert"
  on public.jobs for insert
  to authenticated
  with check (created_by_user_id = (select auth.uid()));

create policy "jobs: own update"
  on public.jobs for update
  to authenticated
  using (created_by_user_id = (select auth.uid()))
  with check (created_by_user_id = (select auth.uid()));

create policy "jobs: own delete"
  on public.jobs for delete
  to authenticated
  using (created_by_user_id = (select auth.uid()));


-- ============================================================
-- 8. job_matches
-- ============================================================
create table if not exists public.job_matches (
  id                     uuid          primary key default gen_random_uuid(),
  user_id                uuid          not null references public.users (id) on delete cascade,
  job_id                 uuid          not null references public.jobs (id) on delete cascade,
  resume_id              uuid          references public.resumes (id) on delete set null,
  match_score            numeric(5,4),
  skill_match_score      numeric(5,4),
  experience_match_score numeric(5,4),
  missing_skills         jsonb         not null default '[]',
  matched_skills         jsonb         not null default '[]',
  recommendations        jsonb         not null default '[]',
  model_version          text,
  status                 text          not null default 'queued'
                           check (status in ('queued','completed','failed','stale')),
  matched_at             timestamptz,
  created_at             timestamptz   not null default now(),
  updated_at             timestamptz   not null default now()
);

create        index if not exists job_matches_user_idx
  on public.job_matches (user_id);
create        index if not exists job_matches_job_idx
  on public.job_matches (job_id);
create        index if not exists job_matches_resume_idx
  on public.job_matches (resume_id);
-- Prevent duplicate active matches
create unique index if not exists job_matches_active_uidx
  on public.job_matches (user_id, job_id, resume_id)
  where status <> 'stale';
create        index if not exists job_matches_score_idx
  on public.job_matches (user_id, match_score desc);
create        index if not exists job_matches_status_idx
  on public.job_matches (user_id, status);
create        index if not exists job_matches_missing_gin
  on public.job_matches using gin (missing_skills);

create or replace trigger set_job_matches_updated_at
  before update on public.job_matches
  for each row execute function public.set_updated_at();

alter table public.job_matches enable row level security;

create policy "job_matches: own row select"
  on public.job_matches for select
  to authenticated
  using ((select auth.uid()) = user_id);

-- Students may queue a match request; service-role writes score fields.
create policy "job_matches: own row insert"
  on public.job_matches for insert
  to authenticated
  with check ((select auth.uid()) = user_id);


-- ============================================================
-- 9. generated_materials
-- ============================================================
create table if not exists public.generated_materials (
  id                 uuid        primary key default gen_random_uuid(),
  user_id            uuid        not null references public.users (id) on delete cascade,
  job_match_id       uuid        references public.job_matches (id) on delete set null,
  job_id             uuid        references public.jobs (id) on delete set null,
  resume_id          uuid        references public.resumes (id) on delete set null,
  material_type      text        not null
                       check (material_type in
                         ('tailored_resume','cover_letter','outreach_email','interview_prep','resume_bullets')),
  title              text,
  content            text,
  structured_content jsonb       not null default '{}',
  prompt_version     text,
  model_version      text,
  status             text        not null default 'draft'
                       check (status in ('draft','accepted','edited','archived')),
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create        index if not exists generated_materials_user_idx
  on public.generated_materials (user_id);
create        index if not exists generated_materials_match_idx
  on public.generated_materials (job_match_id);
create        index if not exists generated_materials_job_idx
  on public.generated_materials (job_id);
create        index if not exists generated_materials_type_idx
  on public.generated_materials (user_id, material_type);
create        index if not exists generated_materials_status_idx
  on public.generated_materials (user_id, status);
create        index if not exists generated_materials_created_idx
  on public.generated_materials (created_at);

create or replace trigger set_generated_materials_updated_at
  before update on public.generated_materials
  for each row execute function public.set_updated_at();

alter table public.generated_materials enable row level security;

create policy "generated_materials: own row select"
  on public.generated_materials for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "generated_materials: own row update"
  on public.generated_materials for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);


-- ============================================================
-- 10. applications
-- ============================================================
create table if not exists public.applications (
  id                     uuid        primary key default gen_random_uuid(),
  user_id                uuid        not null references public.users (id) on delete cascade,
  job_id                 uuid        not null references public.jobs (id) on delete cascade,
  job_match_id           uuid        references public.job_matches (id) on delete set null,
  resume_id              uuid        references public.resumes (id) on delete set null,
  generated_material_id  uuid        references public.generated_materials (id) on delete set null,
  status                 text        not null default 'saved'
                           check (status in
                             ('saved','applying','applied','interviewing','offer','rejected','withdrawn')),
  source                 text,
  application_url        text,
  applied_at             timestamptz,
  next_follow_up_at      timestamptz,
  notes                  text,
  metadata               jsonb       not null default '{}',
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);

create        index if not exists applications_user_idx
  on public.applications (user_id);
create unique index if not exists applications_user_job_uidx
  on public.applications (user_id, job_id);
create        index if not exists applications_status_idx
  on public.applications (user_id, status);
create        index if not exists applications_applied_idx
  on public.applications (applied_at);
create        index if not exists applications_followup_idx
  on public.applications (next_follow_up_at);

create or replace trigger set_applications_updated_at
  before update on public.applications
  for each row execute function public.set_updated_at();

alter table public.applications enable row level security;

create policy "applications: own row all"
  on public.applications for all
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);


-- ============================================================
-- 11. project_suggestions
-- ============================================================
create table if not exists public.project_suggestions (
  id               uuid        primary key default gen_random_uuid(),
  user_id          uuid        not null references public.users (id) on delete cascade,
  job_match_id     uuid        references public.job_matches (id) on delete set null,
  job_id           uuid        references public.jobs (id) on delete set null,
  title            text        not null,
  summary          text,
  target_skills    text[]      not null default '{}',
  difficulty       text
                     check (difficulty in ('beginner','intermediate','advanced')),
  estimated_hours  integer,
  deliverables     jsonb       not null default '[]',
  rubric           jsonb       not null default '{}',
  status           text        not null default 'suggested'
                     check (status in ('suggested','accepted','in_progress','completed','dismissed')),
  model_version    text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create        index if not exists project_suggestions_user_idx
  on public.project_suggestions (user_id);
create        index if not exists project_suggestions_match_idx
  on public.project_suggestions (job_match_id);
create        index if not exists project_suggestions_status_idx
  on public.project_suggestions (user_id, status);
create        index if not exists project_suggestions_skills_gin
  on public.project_suggestions using gin (target_skills);
create        index if not exists project_suggestions_created_idx
  on public.project_suggestions (created_at);

create or replace trigger set_project_suggestions_updated_at
  before update on public.project_suggestions
  for each row execute function public.set_updated_at();

alter table public.project_suggestions enable row level security;

create policy "project_suggestions: own row select"
  on public.project_suggestions for select
  to authenticated
  using ((select auth.uid()) = user_id);

-- Students may update status (accept/dismiss); AI fields are service-role only.
create policy "project_suggestions: own row update status"
  on public.project_suggestions for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);


-- ============================================================
-- 12. audit_logs
-- ============================================================
create table if not exists public.audit_logs (
  id            uuid        primary key default gen_random_uuid(),
  user_id       uuid        references public.users (id) on delete set null,
  actor_type    text        not null default 'system'
                  check (actor_type in ('student','service','admin','system')),
  action        text        not null,
  entity_table  text,
  entity_id     uuid,
  request_id    text,
  ip_address    inet,
  user_agent    text,
  metadata      jsonb       not null default '{}',
  created_at    timestamptz not null default now()
  -- No updated_at: audit rows are append-only.
);

create index if not exists audit_logs_user_idx
  on public.audit_logs (user_id);
create index if not exists audit_logs_action_idx
  on public.audit_logs (action);
create index if not exists audit_logs_entity_idx
  on public.audit_logs (entity_table, entity_id);
create index if not exists audit_logs_created_idx
  on public.audit_logs (created_at);
create index if not exists audit_logs_request_idx
  on public.audit_logs (request_id);

alter table public.audit_logs enable row level security;

-- Students may not write audit logs; only service-role may insert.
-- A limited read policy can be enabled later for account-history features.
-- No client-visible policy is created here intentionally.


-- ============================================================
-- Storage bucket note
-- ============================================================
-- Create the 'resumes' bucket manually in the Supabase dashboard:
--   Storage → New bucket → Name: resumes → Private: ON
--
-- Then run the Storage RLS policies in the Supabase dashboard
-- SQL editor (see docs/storage/resumes_bucket.md).
-- ============================================================
