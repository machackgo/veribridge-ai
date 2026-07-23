-- ============================================================
-- VeriBridge AI — Migration 062: Passport Profiles (candidate identity)
--
-- Adds the dedicated, consented candidate-identity model behind the
-- public Verified Work Passport (resolves the TODO(profile-model) in
-- vbr_work_passport_service._build_identity).
--
-- Before this migration the public passport identity was assembled
-- from scattered onboarding fields and a users.full_name lookup that
-- could never succeed (public.users has no full_name column), so
-- nearly every published passport rendered the neutral
-- "Verified candidate profile" placeholder instead of the student.
--
-- Design notes:
--   * one profile per user (user_id unique)
--   * every field is student-authored and OPTIONAL — the public
--     surface omits empty fields, it never invents or placeholders
--   * publish-sensitive fields carry explicit visibility toggles;
--     work authorization is OFF by default (opt-in only)
--   * the profile photo intentionally stays on the existing
--     migration-054 path (student_onboarding_profiles.avatar_url +
--     public passport-avatars bucket) — no second photo store
--   * identity is served LIVE at read time: editing the profile
--     updates an already-published passport without a re-publish
--     (evidence/report content remains publication-versioned)
--
-- No existing tables are modified. Idempotent: safe to re-run.
-- ============================================================

create extension if not exists pgcrypto;

create table if not exists public.passport_profiles (
  id                      uuid primary key default gen_random_uuid(),
  user_id                 uuid not null unique references public.users (id) on delete cascade,

  -- Identity
  full_name               text,
  preferred_name          text,
  pronunciation           text,
  headline                text,
  bio                     text,

  -- Education
  institution             text,
  degree                  text,
  graduation_year         integer,

  -- Broad location only (city/state) — never a street address.
  location                text,

  -- Public links (validated https URLs).
  github_url              text,
  linkedin_url            text,
  portfolio_url           text,

  -- Preferences
  role_areas              text[] not null default '{}',
  -- Closed vocabulary: seeking_internship | seeking_full_time | open_to_opportunities
  availability            text,
  -- Opt-in ONLY (show_work_authorization defaults false).
  work_authorization_note text,

  -- Per-field public visibility toggles.
  show_location           boolean not null default true,
  show_availability       boolean not null default true,
  show_links              boolean not null default true,
  show_work_authorization boolean not null default false,

  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

-- ------------------------------------------------------------
-- Row Level Security — mirrors vbr_work_passports (migration 052):
-- owner-only select/insert/update, service role full access, and
-- intentionally NO anonymous/public select policy. The public
-- passport identity is served exclusively through the API public
-- endpoint after whitelist projection + scrubbing.
-- ------------------------------------------------------------
alter table public.passport_profiles enable row level security;

drop policy if exists "passport_profiles: own row select"
  on public.passport_profiles;
create policy "passport_profiles: own row select"
  on public.passport_profiles
  for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "passport_profiles: own row insert"
  on public.passport_profiles;
create policy "passport_profiles: own row insert"
  on public.passport_profiles
  for insert
  to authenticated
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "passport_profiles: own row update"
  on public.passport_profiles;
create policy "passport_profiles: own row update"
  on public.passport_profiles
  for update
  to authenticated
  using (user_id::text = (select auth.uid())::text)
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "passport_profiles: service role all"
  on public.passport_profiles;
create policy "passport_profiles: service role all"
  on public.passport_profiles
  for all
  to service_role
  using (true)
  with check (true);
