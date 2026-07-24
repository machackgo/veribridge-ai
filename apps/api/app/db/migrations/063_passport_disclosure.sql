-- ============================================================
-- VeriBridge AI — Migration 063: Granular Passport Disclosure
--
-- Adds the hierarchical, student-controlled evidence-disclosure model
-- behind the public Work Passport. Before this migration the public
-- surface had exactly one switch (vbr_work_passports.is_published) and
-- everything else was implicit: a project was public iff it had a
-- public_report_token, and every artifact was summary-only.
--
-- Three-mode model (the passport master switch stays authoritative):
--   * Private            — is_published = false (rows here are dormant)
--   * Public recruiter-safe — is_published = true, mode = 'recruiter_safe':
--       fixed safe defaults, overrides stored but NOT applied
--   * Public custom      — is_published = true, mode = 'custom':
--       per-resource overrides apply, resolved hierarchically
--
-- Design notes:
--   * one policy row per user (user_id unique), like the passport row
--   * overrides are (resource_type, resource_key) → visibility, one row
--     per node; the CANONICAL resolver (services/passport_disclosure.py)
--     is the only reader — endpoints never interpret rows directly
--   * resource_key shapes (documented here, enforced in the resolver):
--       project / report / per-project proof aspects → the project UUID
--       skill_group → the canonical taxonomy category label
--       skill       → the canonical skill slug
--       project_skill → "<project_uuid>:<skill_slug>"
--       document / document_download → the document proof id
--   * a closed visibility vocabulary; the per-resource-type allowed
--     subset is enforced by the resolver and the write endpoint, NOT by
--     CHECK, so new aspects never need a migration to tighten rules
--   * disclosure_version increments on EVERY policy/override write —
--     public caches and snapshots key off it for immediate revocation
--   * the audit table is append-only and owner/service-only — it is
--     never exposed publicly
--
-- No existing tables are modified. Idempotent: safe to re-run.
-- ============================================================

create extension if not exists pgcrypto;

create table if not exists public.passport_disclosure_policies (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null unique references public.users (id) on delete cascade,

  -- 'recruiter_safe' (recommended default) | 'custom'
  mode               text not null default 'recruiter_safe'
                     check (mode in ('recruiter_safe', 'custom')),

  -- Monotonic version for cache/snapshot invalidation. Bumped on every
  -- mode or override change so previously served representations can be
  -- recognized as stale immediately.
  disclosure_version integer not null default 1,

  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create table if not exists public.passport_disclosure_overrides (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.users (id) on delete cascade,

  -- Closed node vocabulary — must stay in sync with
  -- services/passport_disclosure.py RESOURCE_TYPES.
  resource_type text not null check (resource_type in (
    'project',            -- whole project card (key: project uuid)
    'report',             -- the project's Verified Build Report (key: project uuid)
    'skill_group',        -- high-level taxonomy category (key: category label)
    'skill',              -- individual canonical skill (key: skill slug)
    'project_skill',      -- one skill claim inside one project (key: "<project>:<slug>")
    'github_repo',        -- repository identity + link (key: project uuid)
    'github_lines',       -- exact file/line code references (key: project uuid)
    'website_summary',    -- Website Proof verified summary/presence (key: project uuid)
    'website_url',        -- live website link (key: project uuid)
    'website_frames',     -- captured screenshots/frames (key: project uuid)
    'website_video',      -- workflow recording/replay video (key: project uuid)
    'document',           -- one document: summary/preview (key: document proof id)
    'document_download',  -- one document: download action (key: document proof id)
    'defense_summary',    -- Project Defense verified summary (key: project uuid)
    'defense_transcript', -- Project Defense transcript (key: project uuid)
    'defense_video',      -- Project Defense recording (key: project uuid)
    'video_summary',      -- video evidence chips/summary (key: project uuid)
    'video_full'          -- full video evidence playback (key: project uuid)
  )),
  resource_key  text not null,

  -- Closed visibility vocabulary (per-resource-type subsets are enforced
  -- by the canonical resolver):
  --   hidden       — the node does not exist publicly
  --   summary      — verified summary only, no artifact access
  --   viewable     — original/approved representation opens in browser
  --   downloadable — original artifact may be downloaded
  --   visible      — structural nodes (project/report/skill…) that only
  --                  toggle presence, not artifact depth
  visibility    text not null check (visibility in (
    'hidden', 'summary', 'viewable', 'downloadable', 'visible'
  )),

  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),

  unique (user_id, resource_type, resource_key)
);

create index if not exists idx_passport_disclosure_overrides_user
  on public.passport_disclosure_overrides (user_id);

-- Append-only audit of every disclosure change (who/what/old/new/when).
-- Never exposed publicly; read paths are owner/service only.
create table if not exists public.passport_disclosure_audit (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid not null references public.users (id) on delete cascade,
  changed_by_user_id  uuid,
  resource_type       text not null,
  resource_key        text not null,
  previous_visibility text,
  new_visibility      text,
  disclosure_version  integer,
  changed_at          timestamptz not null default now()
);

create index if not exists idx_passport_disclosure_audit_user
  on public.passport_disclosure_audit (user_id, changed_at desc);

-- ------------------------------------------------------------
-- Row Level Security — mirrors passport_profiles (migration 062):
-- owner-only select/insert/update, service role full access, and
-- intentionally NO anonymous/public policy. Public surfaces read
-- disclosure exclusively through the API resolver after projection.
-- ------------------------------------------------------------
alter table public.passport_disclosure_policies enable row level security;
alter table public.passport_disclosure_overrides enable row level security;
alter table public.passport_disclosure_audit enable row level security;

drop policy if exists "passport_disclosure_policies: own row select"
  on public.passport_disclosure_policies;
create policy "passport_disclosure_policies: own row select"
  on public.passport_disclosure_policies
  for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "passport_disclosure_policies: own row insert"
  on public.passport_disclosure_policies;
create policy "passport_disclosure_policies: own row insert"
  on public.passport_disclosure_policies
  for insert
  to authenticated
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "passport_disclosure_policies: own row update"
  on public.passport_disclosure_policies;
create policy "passport_disclosure_policies: own row update"
  on public.passport_disclosure_policies
  for update
  to authenticated
  using (user_id::text = (select auth.uid())::text)
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "passport_disclosure_policies: service role all"
  on public.passport_disclosure_policies;
create policy "passport_disclosure_policies: service role all"
  on public.passport_disclosure_policies
  for all
  to service_role
  using (true)
  with check (true);

drop policy if exists "passport_disclosure_overrides: own rows select"
  on public.passport_disclosure_overrides;
create policy "passport_disclosure_overrides: own rows select"
  on public.passport_disclosure_overrides
  for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "passport_disclosure_overrides: own rows insert"
  on public.passport_disclosure_overrides;
create policy "passport_disclosure_overrides: own rows insert"
  on public.passport_disclosure_overrides
  for insert
  to authenticated
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "passport_disclosure_overrides: own rows update"
  on public.passport_disclosure_overrides;
create policy "passport_disclosure_overrides: own rows update"
  on public.passport_disclosure_overrides
  for update
  to authenticated
  using (user_id::text = (select auth.uid())::text)
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "passport_disclosure_overrides: own rows delete"
  on public.passport_disclosure_overrides;
create policy "passport_disclosure_overrides: own rows delete"
  on public.passport_disclosure_overrides
  for delete
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "passport_disclosure_overrides: service role all"
  on public.passport_disclosure_overrides;
create policy "passport_disclosure_overrides: service role all"
  on public.passport_disclosure_overrides
  for all
  to service_role
  using (true)
  with check (true);

drop policy if exists "passport_disclosure_audit: own rows select"
  on public.passport_disclosure_audit;
create policy "passport_disclosure_audit: own rows select"
  on public.passport_disclosure_audit
  for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "passport_disclosure_audit: service role all"
  on public.passport_disclosure_audit;
create policy "passport_disclosure_audit: service role all"
  on public.passport_disclosure_audit
  for all
  to service_role
  using (true)
  with check (true);
