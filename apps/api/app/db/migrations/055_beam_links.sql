-- ============================================================
-- VeriBridge AI — Migration 055: Beam Links (dynamic revocable short QR)
--
-- The Beam Card QR (Phase 2) no longer encodes the public Passport
-- URL directly. It encodes a short link — `{app}/b/{code}` — whose
-- target is decided at scan time by the backend resolver
-- (`GET /api/v1/public/beam/{code}`). This makes every QR the
-- student ever hands out *revocable and rotatable after the fact*:
-- revoking/rotating the link kills every printed/screenshotted copy
-- of the old code without touching the Passport itself.
--
-- This table is the security spine for every future handoff surface
-- (Apple/Google Wallet passes, NFC cards, career-fair event links):
-- they all encode a `beam_links.code`, never a raw destination.
--
-- Design notes:
--   * `code` is a cryptographically random, URL-safe, unguessable
--     token (>= 12 chars, ~72 bits) minted server-side — never a
--     sequential or internal id.
--   * `passport_id` is the authoritative target: the resolver looks
--     up the passport row LIVE at scan time and only redirects when
--     it is still published. `passport_slug` is a creation-time
--     snapshot kept for observability; the resolver never trusts it.
--   * No stored `target_url`: the redirect target is always derived
--     server-side from the live passport row, so a row can never be
--     tampered into an open redirect.
--   * `status`: active | revoked | expired. Expiry is enforced at
--     resolve time from `expires_at` (lazily stamped to `expired`).
--   * `beam_link_events` is a coarse, privacy-safe audit trail:
--     user-agent CLASS and referrer HOST only — never raw IPs,
--     never full user agents, never evidence.
--
-- No existing tables are modified. Idempotent: safe to re-run.
-- ============================================================

create extension if not exists pgcrypto;

create table if not exists public.beam_links (
  id             uuid primary key default gen_random_uuid(),
  code           text not null unique,
  user_id        uuid not null references public.users (id) on delete cascade,
  passport_id    uuid not null references public.vbr_work_passports (id) on delete cascade,
  passport_slug  text not null,
  status         text not null default 'active'
                   check (status in ('active', 'revoked', 'expired')),
  event_tag      text,
  expires_at     timestamptz,
  revoked_at     timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists beam_links_user_id_idx
  on public.beam_links (user_id);

create index if not exists beam_links_status_idx
  on public.beam_links (status);

-- Fast "does this user already have an active link" reuse lookup.
create index if not exists beam_links_user_active_idx
  on public.beam_links (user_id, status)
  where status = 'active';

create table if not exists public.beam_link_events (
  id             uuid primary key default gen_random_uuid(),
  beam_link_id   uuid not null references public.beam_links (id) on delete cascade,
  event_type     text not null
                   check (event_type in ('created', 'opened', 'rotated', 'revoked', 'expired_hit')),
  -- Coarse, privacy-safe metadata only. NEVER raw IPs, full user-agent
  -- strings, query strings, or anything derived from evidence.
  user_agent_class text,
  referrer_host    text,
  created_at     timestamptz not null default now()
);

create index if not exists beam_link_events_link_idx
  on public.beam_link_events (beam_link_id, created_at desc);

-- ------------------------------------------------------------
-- Row Level Security
--
-- Deny by default. The owner may READ their own links/events
-- (management UI); all writes go through the API with the service
-- role so status transitions and event logging stay server-owned.
--
-- There is intentionally NO anonymous policy on either table:
-- public scan-time access happens EXCLUSIVELY through the backend
-- resolver endpoint, which validates the code with the service role
-- and returns only { status, public passport path }. Anonymous
-- clients can never enumerate or read codes from the table.
--
-- Mirrors the vbr_work_passports RLS style from migration 052.
-- ------------------------------------------------------------
alter table public.beam_links enable row level security;

drop policy if exists "beam_links: own row select"
  on public.beam_links;
create policy "beam_links: own row select"
  on public.beam_links
  for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "beam_links: service role all"
  on public.beam_links;
create policy "beam_links: service role all"
  on public.beam_links
  for all
  to service_role
  using (true)
  with check (true);

alter table public.beam_link_events enable row level security;

drop policy if exists "beam_link_events: own link select"
  on public.beam_link_events;
create policy "beam_link_events: own link select"
  on public.beam_link_events
  for select
  to authenticated
  using (
    exists (
      select 1
      from public.beam_links bl
      where bl.id = beam_link_events.beam_link_id
        and bl.user_id::text = (select auth.uid())::text
    )
  );

drop policy if exists "beam_link_events: service role all"
  on public.beam_link_events;
create policy "beam_link_events: service role all"
  on public.beam_link_events
  for all
  to service_role
  using (true)
  with check (true);
