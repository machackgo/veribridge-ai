-- ============================================================
-- VeriBridge AI — Migration 065: Recruiter ↔ Candidate connections
-- ============================================================
--
-- Foundation of the recruiter-side product: a recruiter (an authenticated
-- Supabase user) opens a student's public Work Passport (/p/{public_slug},
-- via QR scan or shared link), clicks "Save Candidate", and the candidate
-- appears in that recruiter's workspace for later review.
--
-- Why a NEW table instead of reusing recruiter_saved_passports (027):
--   * 027 keys the recruiter by an UNVERIFIED requester_email plus an
--     opaque X-Recruiter-Token session (036). Anyone can claim any email,
--     so that identity model cannot guarantee recruiter isolation.
--   * This table keys the recruiter by public.users(id) — a real verified
--     Supabase identity — which is the canonical model every future
--     acquisition channel (QR, shared link, search, role match) converges
--     into. 027 remains untouched for the legacy email-token surface.
--
-- Design notes:
--   * unique (recruiter_user_id, student_user_id) makes saves idempotent at
--     the database level — one connection per recruiter/candidate pair no
--     matter how many passports, links, or repeat clicks are involved.
--   * source is a closed, extensible vocabulary; must stay in sync with
--     services/recruiter_connection_service.py CONNECTION_SOURCES.
--   * source_context is a small jsonb bag for attribution details the
--     source enum cannot carry (e.g. the passport slug that was scanned).
--   * passport_id records which passport row the connection was made
--     through; the durable relationship itself is user-to-user, so slug
--     rotation or passport re-publishing never orphans a saved candidate.
--
-- Also adds vbr_passport_views: privacy-conscious view events for the
-- public passport page, mirroring vbr_project_report_views (060) exactly —
-- coarse categories only, NO raw referrer URL, NO IP, NO user-agent string.
--
-- No existing tables are modified. Idempotent: safe to re-run.
-- ============================================================

create extension if not exists pgcrypto;

-- ------------------------------------------------------------
-- recruiter_candidate_connections — canonical saved-candidate model
-- ------------------------------------------------------------

create table if not exists public.recruiter_candidate_connections (
  id                uuid primary key default gen_random_uuid(),
  recruiter_user_id uuid not null references public.users (id) on delete cascade,
  student_user_id   uuid not null references public.users (id) on delete cascade,
  passport_id       uuid not null references public.vbr_work_passports (id) on delete cascade,
  -- Acquisition channel. Closed vocabulary, designed for future channels;
  -- must stay in sync with services/recruiter_connection_service.py.
  source            text not null default 'shared_link'
                    check (source in ('qr_scan', 'shared_link', 'search', 'role_match', 'direct')),
  source_context    jsonb not null default '{}'::jsonb,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (recruiter_user_id, student_user_id)
);

create index if not exists recruiter_candidate_connections_recruiter_idx
  on public.recruiter_candidate_connections (recruiter_user_id);
create index if not exists recruiter_candidate_connections_student_idx
  on public.recruiter_candidate_connections (student_user_id);
create index if not exists recruiter_candidate_connections_created_idx
  on public.recruiter_candidate_connections (created_at);

create or replace trigger set_recruiter_candidate_connections_updated_at
  before update on public.recruiter_candidate_connections
  for each row execute function public.set_updated_at();

-- RLS: the API always uses the service role with app-level filters; these
-- policies are defense-in-depth for the anon-key path. The recruiter may
-- read/delete only their own connections. Students intentionally get NO
-- policy here — who saved them is recruiter-relationship metadata, not
-- public candidate data. No anon access of any kind.
alter table public.recruiter_candidate_connections enable row level security;

drop policy if exists "recruiter_candidate_connections: own rows select"
  on public.recruiter_candidate_connections;
create policy "recruiter_candidate_connections: own rows select"
  on public.recruiter_candidate_connections for select to authenticated
  using (recruiter_user_id::text = (select auth.uid())::text);

drop policy if exists "recruiter_candidate_connections: own rows delete"
  on public.recruiter_candidate_connections;
create policy "recruiter_candidate_connections: own rows delete"
  on public.recruiter_candidate_connections for delete to authenticated
  using (recruiter_user_id::text = (select auth.uid())::text);

drop policy if exists "recruiter_candidate_connections: service role all"
  on public.recruiter_candidate_connections;
create policy "recruiter_candidate_connections: service role all"
  on public.recruiter_candidate_connections for all to service_role
  using (true) with check (true);

-- ------------------------------------------------------------
-- vbr_passport_views — public passport view/scan events (mirrors 060)
-- ------------------------------------------------------------

create table if not exists public.vbr_passport_views (
  id                uuid primary key default gen_random_uuid(),
  passport_id       uuid not null references public.vbr_work_passports (id) on delete cascade,
  -- How the viewer arrived. QR scans are attributed because student QR
  -- surfaces encode /p/{slug}?src=qr; camera-app scans of older codes
  -- without the marker fall back to 'direct'.
  source            text not null default 'unknown'
                    check (source in ('direct', 'qr_scan', 'shared_link', 'unknown')),
  -- Coarse category only, never the referrer URL itself.
  referrer_category text not null default 'none'
                    check (referrer_category in ('internal', 'external', 'none')),
  -- Coarse device class only, never the raw user-agent string.
  ua_class          text not null default 'unknown'
                    check (ua_class in ('desktop', 'mobile', 'bot', 'unknown')),
  -- Set only when the viewer presented a valid Supabase session; anonymous
  -- views stay anonymous. No fingerprinting of any kind.
  recruiter_user_id uuid references public.users (id) on delete set null,
  -- Client-generated opaque per-session key; unique per passport so
  -- same-page rerenders / tab refreshes don't create duplicate rows.
  dedupe_key        text,
  viewed_at         timestamptz not null default now()
);

create index if not exists vbr_passport_views_passport_idx
  on public.vbr_passport_views (passport_id);
create index if not exists vbr_passport_views_viewed_idx
  on public.vbr_passport_views (viewed_at);
create unique index if not exists vbr_passport_views_dedupe_idx
  on public.vbr_passport_views (passport_id, dedupe_key)
  where dedupe_key is not null;

alter table public.vbr_passport_views enable row level security;

drop policy if exists "vbr_passport_views: service role all"
  on public.vbr_passport_views;
create policy "vbr_passport_views: service role all"
  on public.vbr_passport_views for all to service_role
  using (true) with check (true);

notify pgrst, 'reload schema';

-- ------------------------------------------------------------
-- Rollback (manual):
--   drop table if exists public.vbr_passport_views;
--   drop table if exists public.recruiter_candidate_connections;
-- ------------------------------------------------------------
