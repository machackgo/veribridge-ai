-- ============================================================
-- VeriBridge AI — Migration 002: Student Onboarding + Career Graph
--
-- Flexible MVP schema for universal student onboarding across majors,
-- career fields, locations, work authorization, and compensation.
-- ============================================================

create table if not exists public.student_onboarding_profiles (
  id                         uuid        primary key default gen_random_uuid(),
  user_id                    uuid        not null references public.users (id) on delete cascade,
  university_country         text,
  degree_level               text,
  major                      text,
  graduation_year            integer,
  job_search_timeline        text,
  urgency_level              text,
  work_authorization_countries jsonb     not null default '[]',
  sponsorship_needed         boolean     not null default false,
  visa_status                text,
  work_authorization_notes   text,
  completed_at               timestamptz,
  created_at                 timestamptz not null default now(),
  updated_at                 timestamptz not null default now()
);

create unique index if not exists student_onboarding_profiles_user_uidx
  on public.student_onboarding_profiles (user_id);
create index if not exists student_onboarding_profiles_major_idx
  on public.student_onboarding_profiles (major);
create index if not exists student_onboarding_profiles_auth_countries_gin
  on public.student_onboarding_profiles using gin (work_authorization_countries);

create or replace trigger set_student_onboarding_profiles_updated_at
  before update on public.student_onboarding_profiles
  for each row execute function public.set_updated_at();

alter table public.student_onboarding_profiles enable row level security;

create policy "student_onboarding_profiles: own row select"
  on public.student_onboarding_profiles for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "student_onboarding_profiles: own row insert"
  on public.student_onboarding_profiles for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

create policy "student_onboarding_profiles: own row update"
  on public.student_onboarding_profiles for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);


create table if not exists public.student_career_preferences (
  id                   uuid        primary key default gen_random_uuid(),
  user_id              uuid        not null references public.users (id) on delete cascade,
  career_fields        jsonb       not null default '[]',
  target_roles         jsonb       not null default '[]',
  target_industries    jsonb       not null default '[]',
  target_locations     jsonb       not null default '[]',
  preferred_work_modes jsonb       not null default '[]',
  open_to_relocate     boolean     not null default false,
  global_search_open   boolean     not null default false,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

create unique index if not exists student_career_preferences_user_uidx
  on public.student_career_preferences (user_id);
create index if not exists student_career_preferences_fields_gin
  on public.student_career_preferences using gin (career_fields);
create index if not exists student_career_preferences_roles_gin
  on public.student_career_preferences using gin (target_roles);
create index if not exists student_career_preferences_locations_gin
  on public.student_career_preferences using gin (target_locations);

create or replace trigger set_student_career_preferences_updated_at
  before update on public.student_career_preferences
  for each row execute function public.set_updated_at();

alter table public.student_career_preferences enable row level security;

create policy "student_career_preferences: own row select"
  on public.student_career_preferences for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "student_career_preferences: own row insert"
  on public.student_career_preferences for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

create policy "student_career_preferences: own row update"
  on public.student_career_preferences for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);


create table if not exists public.student_skills (
  id                  uuid        primary key default gen_random_uuid(),
  user_id             uuid        not null references public.users (id) on delete cascade,
  skill_name          text        not null,
  skill_category      text,
  proficiency_level   text,
  evidence            jsonb       not null default '[]',
  verification_status text        not null default 'self_reported'
                        check (verification_status in ('self_reported','pending','verified','rejected')),
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create index if not exists student_skills_user_idx
  on public.student_skills (user_id);
create index if not exists student_skills_name_idx
  on public.student_skills (skill_name);
create index if not exists student_skills_evidence_gin
  on public.student_skills using gin (evidence);

create or replace trigger set_student_skills_updated_at
  before update on public.student_skills
  for each row execute function public.set_updated_at();

alter table public.student_skills enable row level security;

create policy "student_skills: own rows select"
  on public.student_skills for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "student_skills: own rows insert"
  on public.student_skills for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

create policy "student_skills: own rows update"
  on public.student_skills for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);


create table if not exists public.student_compensation_preferences (
  id                         uuid        primary key default gen_random_uuid(),
  user_id                    uuid        not null references public.users (id) on delete cascade,
  expected_salary_min        numeric(14,2),
  expected_salary_max        numeric(14,2),
  minimum_acceptable_salary  numeric(14,2),
  salary_currency            text        not null default 'USD',
  salary_period              text        not null default 'yearly'
                               check (salary_period in ('hourly','monthly','yearly')),
  open_to_negotiation        boolean     not null default true,
  created_at                 timestamptz not null default now(),
  updated_at                 timestamptz not null default now()
);

create unique index if not exists student_compensation_preferences_user_uidx
  on public.student_compensation_preferences (user_id);

create or replace trigger set_student_compensation_preferences_updated_at
  before update on public.student_compensation_preferences
  for each row execute function public.set_updated_at();

alter table public.student_compensation_preferences enable row level security;

create policy "student_compensation_preferences: own row select"
  on public.student_compensation_preferences for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "student_compensation_preferences: own row insert"
  on public.student_compensation_preferences for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

create policy "student_compensation_preferences: own row update"
  on public.student_compensation_preferences for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);


create table if not exists public.opportunity_heatmap_snapshots (
  id                uuid        primary key default gen_random_uuid(),
  user_id           uuid        not null references public.users (id) on delete cascade,
  input_preferences jsonb       not null default '{}',
  recommendations   jsonb       not null default '[]',
  provider          text        not null default 'mock',
  created_at        timestamptz not null default now()
);

create index if not exists opportunity_heatmap_snapshots_user_created_idx
  on public.opportunity_heatmap_snapshots (user_id, created_at desc);
create index if not exists opportunity_heatmap_snapshots_recommendations_gin
  on public.opportunity_heatmap_snapshots using gin (recommendations);

alter table public.opportunity_heatmap_snapshots enable row level security;

create policy "opportunity_heatmap_snapshots: own rows select"
  on public.opportunity_heatmap_snapshots for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "opportunity_heatmap_snapshots: own rows insert"
  on public.opportunity_heatmap_snapshots for insert
  to authenticated
  with check ((select auth.uid()) = user_id);
