-- ============================================================
-- VeriBridge AI — Migration 066: Recruiter Search & Discovery index
-- ============================================================
--
-- Adds the searchable candidate projection behind Recruiter Search V1
-- (the second candidate-acquisition path, alongside QR / shared link).
--
-- PRIVACY MODEL (the load-bearing design decision):
--   A row in recruiter_search_index is DERIVED FROM THE OUTPUT of
--   build_public_passport() — the one disclosure-enforced, scrubbed,
--   fail-closed projection already served publicly at /p/{slug}.
--   The index therefore can never contain anything a recruiter could
--   not already see on the candidate's public Work Passport:
--     * unpublished passports have NO row (refresh deletes it),
--     * hidden projects / skills / sources never reach the projection,
--     * the API re-checks vbr_work_passports.is_published AND the
--       current disclosure_version live at query time — a stale row
--       is excluded (fail closed), never served.
--
-- Design notes:
--   * one row per candidate (user_id primary key); rebuildable at any
--     time from source-of-truth data (services/recruiter_search_service
--     .rebuild_search_index) — the index is a cache, never a source.
--   * skills / projects are compact jsonb summaries (names, qualitative
--     statuses, evidence-source labels, public report paths) — never
--     evidence blobs, media, tokens, or private ids.
--   * text_* columns split the searchable document by weight class so
--     search_tsv can rank skills above profile text above project prose.
--   * search_text is the flat concatenation used for trigram/ilike
--     prefiltering; ranking itself is deterministic in the service.
--   * RLS: service-role ONLY. Recruiters search exclusively through the
--     authenticated API; there is no anon or authenticated table access.
--
-- Also adds recruiter_search_events: coarse, privacy-conscious search
-- observability (query text is recruiter-authored input, truncated;
-- never candidate evidence). Mirrors the 060/065 events-table style.
--
-- No existing tables are modified. Idempotent: safe to re-run.
-- ============================================================

create extension if not exists pgcrypto;
create extension if not exists pg_trgm;

-- ------------------------------------------------------------
-- recruiter_search_index — public-projection-derived candidate index
-- ------------------------------------------------------------

create table if not exists public.recruiter_search_index (
  user_id               uuid primary key references public.users (id) on delete cascade,
  passport_id           uuid not null references public.vbr_work_passports (id) on delete cascade,
  public_slug           text not null,

  -- Consented public identity (visibility-filtered upstream).
  display_name          text,
  headline              text,
  location              text,
  availability          text,
  availability_label    text,
  institution           text,
  degree                text,
  graduation_year       integer,
  role_areas            text[] not null default '{}',

  -- Compact public summaries (labels/statuses/paths only — no blobs).
  skills                jsonb not null default '[]'::jsonb,
  projects              jsonb not null default '[]'::jsonb,
  -- {github, live_site, documents, project_defense, video} booleans.
  evidence_flags        jsonb not null default '{}'::jsonb,
  skill_count           integer not null default 0,
  project_count         integer not null default 0,

  -- Weighted searchable document components (built by the projection).
  text_skills           text not null default '',
  text_profile          text not null default '',
  text_projects         text not null default '',
  text_meta             text not null default '',
  -- Flat concatenation for trigram/ilike prefiltering.
  search_text           text not null default '',
  search_tsv            tsvector generated always as (
                          setweight(to_tsvector('english', coalesce(text_skills, '')), 'A')
                          || setweight(to_tsvector('english', coalesce(text_profile, '')), 'B')
                          || setweight(to_tsvector('english', coalesce(text_projects, '')), 'C')
                          || setweight(to_tsvector('english', coalesce(text_meta, '')), 'D')
                        ) stored,

  -- Staleness guards: the API excludes rows whose recorded version is
  -- behind the candidate's live disclosure_version (fail closed).
  disclosure_version    integer not null default 1,
  passport_published_at timestamptz,
  projected_at          timestamptz not null default now()
);

create index if not exists recruiter_search_index_tsv_idx
  on public.recruiter_search_index using gin (search_tsv);
create index if not exists recruiter_search_index_trgm_idx
  on public.recruiter_search_index using gin (search_text gin_trgm_ops);
create index if not exists recruiter_search_index_published_idx
  on public.recruiter_search_index (passport_published_at);
create unique index if not exists recruiter_search_index_slug_idx
  on public.recruiter_search_index (public_slug);

alter table public.recruiter_search_index enable row level security;

-- Service-role ONLY: recruiter search is served exclusively by the
-- authenticated API. No anon policy, no authenticated policy — not even
-- the owner reads this table directly.
drop policy if exists "recruiter_search_index: service role all"
  on public.recruiter_search_index;
create policy "recruiter_search_index: service role all"
  on public.recruiter_search_index for all to service_role
  using (true) with check (true);

-- ------------------------------------------------------------
-- recruiter_search_events — coarse search observability (mirrors 060/065)
-- ------------------------------------------------------------

create table if not exists public.recruiter_search_events (
  id                uuid primary key default gen_random_uuid(),
  recruiter_user_id uuid references public.users (id) on delete set null,
  -- Recruiter-authored query input only, truncated upstream — never
  -- candidate evidence, snippets, or result content.
  query_text        text,
  filters           jsonb not null default '{}'::jsonb,
  result_count      integer not null default 0,
  zero_results      boolean not null default false,
  created_at        timestamptz not null default now()
);

create index if not exists recruiter_search_events_created_idx
  on public.recruiter_search_events (created_at);
create index if not exists recruiter_search_events_recruiter_idx
  on public.recruiter_search_events (recruiter_user_id);

alter table public.recruiter_search_events enable row level security;

drop policy if exists "recruiter_search_events: service role all"
  on public.recruiter_search_events;
create policy "recruiter_search_events: service role all"
  on public.recruiter_search_events for all to service_role
  using (true) with check (true);

notify pgrst, 'reload schema';

-- ------------------------------------------------------------
-- Rollback (manual):
--   drop table if exists public.recruiter_search_events;
--   drop table if exists public.recruiter_search_index;
-- ------------------------------------------------------------
