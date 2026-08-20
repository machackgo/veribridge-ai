-- ============================================================
-- VeriBridge AI — Migration 070: Recruiter Talent Pools + Saved Searches
-- ============================================================
--
-- Recruiter V5: recruiters gain two reusable, role-independent
-- organizing primitives on top of the V3/V4 Hiring Brief stack, plus
-- evidence-aware discovery over time.
--
-- Four additive tables:
--
--   1. recruiter_talent_pools — recruiter-owned, reusable candidate
--      collections independent of any Hiring Brief ("AI / ML Early
--      Talent", "Fall 2026 Career Fair Prospects"). A pool is an
--      organizing label, NOT a copied candidate record: membership is
--      keyed by the stable public.users id, so one human remains one
--      canonical VeriBridge candidate identity across pools, briefs,
--      and searches. Pools never duplicate public evidence — candidate
--      identity and evidence context are always resolved live through
--      the existing consented projections (fail-closed).
--
--   2. recruiter_talent_pool_candidates — pool membership. Composite
--      PK (pool_id, student_user_id) makes membership idempotent by
--      construction; a candidate may belong to many pools. ``source``
--      reuses the acquisition vocabulary of
--      recruiter_candidate_connections (065) plus 'saved_search'
--      (mirror constant: recruiter_talent_pool_service
--      .POOL_CANDIDATE_SOURCES — keep the two in sync). ``note`` is a
--      recruiter-private annotation (<= 4000 app-side, 068 pattern).
--
--   3. recruiter_saved_searches — a recruiter search persisted as a
--      structured object. ``plan`` jsonb is THE canonical requirement
--      representation (recruiter_requirement_plan.PLAN_SCHEMA_VERSION,
--      same shape briefs persist) — UNTRUSTED on load, always passed
--      through sanitize_plan. ``query_text`` keeps the recruiter's
--      original words for honest display. ``filters`` is a small
--      closed shape (skills / evidence / availability — the explicit
--      chips search_candidates already accepts), sanitized on every
--      load. active|paused lifecycle; last_evaluated_at drives lazy
--      re-evaluation; last_reviewed_at drives "new since last review".
--
--   4. recruiter_saved_search_matches — evidence-aware discovery
--      state: ONE row per (saved_search, candidate) — one human, one
--      match, no matter how many projects satisfied the requirements.
--      Rows exist ONLY for candidates whose PUBLISHED evidence
--      deterministically satisfies EVERY hard requirement of the plan
--      (the engine's existing "exact" semantics — no scores, no
--      thresholds, no semantic-similarity qualification). The row
--      stores per-requirement content fingerprints of the
--      deterministic evaluation output (hashes, keys, timestamps
--      ONLY — never prose, never identity, never evidence content),
--      so "new candidate" and "updated published evidence" are
--      detected by diffing and every explanation is reconstructed
--      live from the plan + current published evidence. Candidates
--      who unpublish, change disclosure, get excluded, or stop
--      satisfying the plan have their row DELETED (fail-closed
--      removal — stale matches never survive).
--
-- Privacy contract: everything in this migration is recruiter-private
-- workflow data. Pools/saved searches carry owner RLS
-- (recruiter_user_id = auth.uid()); membership/match rows carry
-- owner-via-parent RLS; service_role has full access; STUDENTS GET NO
-- POLICY. Nothing here is ever written into recruiter_search_index,
-- any public projection, or any candidate-facing surface. The backend
-- runs with the service role, so app-level ownership filtering is the
-- real boundary; these policies are defense-in-depth.
--
-- Right-to-delete alignment: student_user_id FKs cascade from
-- public.users; membership cascades from its pool; match rows cascade
-- from their saved search — deleting any side removes every V5
-- artifact about that pair. Deleting a pool or saved search never
-- touches candidates, connections, briefs, or public evidence.
--
-- No existing tables are modified. Idempotent: safe to re-run.
-- ============================================================

create extension if not exists pgcrypto;

-- ------------------------------------------------------------
-- 1. recruiter_talent_pools (reusable recruiter-owned collections)
-- ------------------------------------------------------------

create table if not exists public.recruiter_talent_pools (
  id                uuid primary key default gen_random_uuid(),
  recruiter_user_id uuid not null references public.users (id) on delete cascade,
  -- Length caps (name <= 120, description <= 600) are enforced
  -- app-side, matching the 068 brief pattern.
  name              text not null,
  description       text,
  -- archived = parked, hidden from active lists, restorable. Mirror
  -- constant: recruiter_talent_pool_service.POOL_STATUSES.
  status            text not null default 'active'
    check (status in ('active', 'archived')),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists recruiter_talent_pools_recruiter_idx
  on public.recruiter_talent_pools (recruiter_user_id, updated_at desc);

create or replace trigger set_recruiter_talent_pools_updated_at
  before update on public.recruiter_talent_pools
  for each row execute function public.set_updated_at();

alter table public.recruiter_talent_pools enable row level security;

-- Pools are recruiter-private organizing labels. Students get NO
-- policy: pool existence and membership are recruiter-relationship
-- metadata, never public candidate data.
drop policy if exists "recruiter_talent_pools: own rows all"
  on public.recruiter_talent_pools;
create policy "recruiter_talent_pools: own rows all"
  on public.recruiter_talent_pools for all to authenticated
  using (recruiter_user_id::text = (select auth.uid())::text)
  with check (recruiter_user_id::text = (select auth.uid())::text);

drop policy if exists "recruiter_talent_pools: service role all"
  on public.recruiter_talent_pools;
create policy "recruiter_talent_pools: service role all"
  on public.recruiter_talent_pools for all to service_role
  using (true) with check (true);

-- ------------------------------------------------------------
-- 2. recruiter_talent_pool_candidates (idempotent membership)
-- ------------------------------------------------------------

create table if not exists public.recruiter_talent_pool_candidates (
  pool_id         uuid not null
    references public.recruiter_talent_pools (id) on delete cascade,
  student_user_id uuid not null references public.users (id) on delete cascade,
  -- How the candidate entered THIS pool. Superset of the 065
  -- connection vocabulary plus 'saved_search'. Mirror constant:
  -- recruiter_talent_pool_service.POOL_CANDIDATE_SOURCES.
  source          text not null default 'direct'
    check (source in ('qr_scan', 'shared_link', 'search', 'role_match',
                      'direct', 'saved_search')),
  -- Recruiter-private annotation (<= 4000 app-side, 068 note pattern).
  note            text,
  added_at        timestamptz not null default now(),
  primary key (pool_id, student_user_id)
);

create index if not exists recruiter_talent_pool_candidates_student_idx
  on public.recruiter_talent_pool_candidates (student_user_id);

alter table public.recruiter_talent_pool_candidates enable row level security;

-- Membership is visible/editable only through pools the recruiter
-- owns. Students get NO policy: pool membership is recruiter-private.
drop policy if exists "recruiter_talent_pool_candidates: own pool all"
  on public.recruiter_talent_pool_candidates;
create policy "recruiter_talent_pool_candidates: own pool all"
  on public.recruiter_talent_pool_candidates for all to authenticated
  using (exists (
    select 1 from public.recruiter_talent_pools p
    where p.id = pool_id
      and p.recruiter_user_id::text = (select auth.uid())::text))
  with check (exists (
    select 1 from public.recruiter_talent_pools p
    where p.id = pool_id
      and p.recruiter_user_id::text = (select auth.uid())::text));

drop policy if exists "recruiter_talent_pool_candidates: service role all"
  on public.recruiter_talent_pool_candidates;
create policy "recruiter_talent_pool_candidates: service role all"
  on public.recruiter_talent_pool_candidates for all to service_role
  using (true) with check (true);

-- ------------------------------------------------------------
-- 3. recruiter_saved_searches (a search persisted as structure)
-- ------------------------------------------------------------

create table if not exists public.recruiter_saved_searches (
  id                uuid primary key default gen_random_uuid(),
  recruiter_user_id uuid not null references public.users (id) on delete cascade,
  -- Recruiter-friendly name (<= 120 app-side).
  name              text not null,
  -- The recruiter's original words, for honest display
  -- (<= 320 app-side = recruiter_search_service.MAX_QUERY_LENGTH).
  query_text        text,
  -- THE canonical structured requirement representation
  -- (recruiter_requirement_plan, PLAN_SCHEMA_VERSION) — the exact
  -- shape recruiter_hiring_briefs.plan persists. UNTRUSTED on load:
  -- every read passes through sanitize_plan.
  plan              jsonb not null default '{}'::jsonb,
  -- Closed explicit-filter shape ({skills:[], evidence:[],
  -- availability}) matching search_candidates' chip kwargs.
  -- UNTRUSTED on load: sanitized against the closed vocabularies.
  filters           jsonb not null default '{}'::jsonb,
  -- paused = kept but not tracking. Mirror constant:
  -- recruiter_saved_search_service.SAVED_SEARCH_STATUSES.
  status            text not null default 'active'
    check (status in ('active', 'paused')),
  -- Lazy re-evaluation bookkeeping (never user-visible authority —
  -- results are always recomputed live, fail-closed).
  last_evaluated_at timestamptz,
  -- "New since last review" boundary; set at creation (baseline) and
  -- by the explicit mark-reviewed action.
  last_reviewed_at  timestamptz,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists recruiter_saved_searches_recruiter_idx
  on public.recruiter_saved_searches (recruiter_user_id, updated_at desc);

create or replace trigger set_recruiter_saved_searches_updated_at
  before update on public.recruiter_saved_searches
  for each row execute function public.set_updated_at();

alter table public.recruiter_saved_searches enable row level security;

-- Saved searches are recruiter-private intent. Students get NO policy.
drop policy if exists "recruiter_saved_searches: own rows all"
  on public.recruiter_saved_searches;
create policy "recruiter_saved_searches: own rows all"
  on public.recruiter_saved_searches for all to authenticated
  using (recruiter_user_id::text = (select auth.uid())::text)
  with check (recruiter_user_id::text = (select auth.uid())::text);

drop policy if exists "recruiter_saved_searches: service role all"
  on public.recruiter_saved_searches;
create policy "recruiter_saved_searches: service role all"
  on public.recruiter_saved_searches for all to service_role
  using (true) with check (true);

-- ------------------------------------------------------------
-- 4. recruiter_saved_search_matches (discovery state — hashes only)
-- ------------------------------------------------------------

create table if not exists public.recruiter_saved_search_matches (
  saved_search_id  uuid not null
    references public.recruiter_saved_searches (id) on delete cascade,
  student_user_id  uuid not null references public.users (id) on delete cascade,
  -- {requirement_axis_key -> 16-hex content hash of that requirement's
  -- deterministic evaluation row}. Axis keys are the comparison
  -- engine's stable ids ("concept:a|b", "evidence:github"). Hashes
  -- and keys ONLY — never prose, never identity, never evidence
  -- content; explanations are reconstructed live.
  requirement_fingerprints jsonb not null default '{}'::jsonb,
  -- Overall content hash across the requirement fingerprints.
  evidence_fingerprint     text not null default '',
  -- What the most recent change was. Mirror constant:
  -- recruiter_saved_search_service.MATCH_EVENTS.
  last_event               text not null default 'new_match'
    check (last_event in ('new_match', 'evidence_updated')),
  -- Axis keys whose evaluation changed at the last change (closed
  -- small shape — keys only, for "now satisfies FastAPI" display
  -- resolved against the live plan).
  changed_requirement_keys jsonb not null default '[]'::jsonb,
  first_matched_at         timestamptz not null default now(),
  -- Bumped ONLY when something actually changed (new match /
  -- fingerprint diff) — drives "new since last review".
  last_change_at           timestamptz not null default now(),
  last_evaluated_at        timestamptz not null default now(),
  primary key (saved_search_id, student_user_id)
);

create index if not exists recruiter_saved_search_matches_search_idx
  on public.recruiter_saved_search_matches
  (saved_search_id, last_change_at desc);

create index if not exists recruiter_saved_search_matches_student_idx
  on public.recruiter_saved_search_matches (student_user_id);

alter table public.recruiter_saved_search_matches enable row level security;

-- Discovery state is visible only through saved searches the
-- recruiter owns. Students get NO policy: who is being tracked by
-- whose saved search is recruiter-private metadata.
drop policy if exists "recruiter_saved_search_matches: own search all"
  on public.recruiter_saved_search_matches;
create policy "recruiter_saved_search_matches: own search all"
  on public.recruiter_saved_search_matches for all to authenticated
  using (exists (
    select 1 from public.recruiter_saved_searches s
    where s.id = saved_search_id
      and s.recruiter_user_id::text = (select auth.uid())::text))
  with check (exists (
    select 1 from public.recruiter_saved_searches s
    where s.id = saved_search_id
      and s.recruiter_user_id::text = (select auth.uid())::text));

drop policy if exists "recruiter_saved_search_matches: service role all"
  on public.recruiter_saved_search_matches;
create policy "recruiter_saved_search_matches: service role all"
  on public.recruiter_saved_search_matches for all to service_role
  using (true) with check (true);

notify pgrst, 'reload schema';

-- ------------------------------------------------------------
-- Rollback (manual):
--   drop table if exists public.recruiter_saved_search_matches;
--   drop table if exists public.recruiter_saved_searches;
--   drop table if exists public.recruiter_talent_pool_candidates;
--   drop table if exists public.recruiter_talent_pools;
-- ------------------------------------------------------------
