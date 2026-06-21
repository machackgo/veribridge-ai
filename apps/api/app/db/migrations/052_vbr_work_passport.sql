-- ============================================================
-- VeriBridge AI — Migration 052: Verified Work Passport (v1)
--
-- Adds the dedicated public Work Passport surface for the VBR
-- (Verified Build Report) flow. This is the student's public,
-- recruiter-safe profile / index that links out to the
-- already-tokenized public VBR project reports
-- (vbr_projects.public_report_token, see migration 051).
--
-- This is intentionally SEPARATE from the older session-based
-- public_work_passport_access surface (migration 021): that one
-- is keyed by extension-proof session and serves a different
-- product. The VBR Work Passport aggregates a student's
-- vbr_projects and their published public reports under a single
-- stable public slug.
--
-- Design notes:
--   * one passport per user (user_id unique)
--   * public_slug is minted once at first publish and kept stable
--     so a re-publish resolves to the same recruiter link
--   * is_published gates public visibility; unpublishing 404s the
--     public passport WITHOUT touching any underlying evidence or
--     individual VBR report tokens
--   * headline / summary are optional, student-editable, public-safe
--     text (safe defaults are derived in the service when empty)
--
-- No existing tables are modified. Idempotent: safe to re-run.
-- ============================================================

create extension if not exists pgcrypto;

create table if not exists public.vbr_work_passports (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null unique references public.users (id) on delete cascade,
  public_slug   text,
  headline      text,
  summary       text,
  is_published  boolean not null default false,
  published_at  timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

-- One passport per public slug. Multiple NULLs are allowed by Postgres
-- partial unique indexes, so passports without a minted slug never collide.
create unique index if not exists vbr_work_passports_public_slug_unique_idx
  on public.vbr_work_passports (public_slug)
  where public_slug is not null;

-- ------------------------------------------------------------
-- Row Level Security
--
-- vbr_work_passports is a user-owned table: each authenticated
-- student can read and manage only their own passport row. The
-- service role retains full access for API-side reads/writes.
--
-- NOTE: there is intentionally NO anonymous / public select
-- policy. Public, recruiter-facing access to a published passport
-- is served exclusively through the API public endpoint, which
-- resolves the slug with the service role and returns a
-- sanitized, public-safe serialization. Recruiters never read
-- this table directly via Supabase anon.
--
-- Mirrors the vbr_projects RLS style from migration 049.
-- ------------------------------------------------------------
alter table public.vbr_work_passports enable row level security;

drop policy if exists "vbr_work_passports: own row select"
  on public.vbr_work_passports;
create policy "vbr_work_passports: own row select"
  on public.vbr_work_passports
  for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "vbr_work_passports: own row insert"
  on public.vbr_work_passports;
create policy "vbr_work_passports: own row insert"
  on public.vbr_work_passports
  for insert
  to authenticated
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "vbr_work_passports: own row update"
  on public.vbr_work_passports;
create policy "vbr_work_passports: own row update"
  on public.vbr_work_passports
  for update
  to authenticated
  using (user_id::text = (select auth.uid())::text)
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "vbr_work_passports: service role all"
  on public.vbr_work_passports;
create policy "vbr_work_passports: service role all"
  on public.vbr_work_passports
  for all
  to service_role
  using (true)
  with check (true);
