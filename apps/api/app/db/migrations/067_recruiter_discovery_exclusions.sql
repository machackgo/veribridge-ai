-- ============================================================
-- VeriBridge AI — Migration 067: Recruiter discovery exclusions
-- ============================================================
--
-- Durable guard that keeps POSITIVELY IDENTIFIED non-candidate accounts
-- (QA fixtures, demo/dev accounts, isolation-test users) out of recruiter
-- discovery — even if their Work Passport is ever (re-)published.
--
-- Why this exists: manual production testing on 2026-08-18 found the
-- recruiter search corpus polluted by three of Mohammed's own QA/legacy
-- accounts ("QA Student One-Forty-Eight", the null-name proof-to-beam
-- fixture, and the legacy demo/WPI duplicate). The primary remediation is
-- unpublishing those passports (reversible, no data deleted); this table is
-- the defense-in-depth layer so a future automated QA run that publishes a
-- passport on one of these accounts can never re-pollute discovery.
--
-- Semantics (enforced in recruiter_search_service):
--   * refresh_search_projection deletes (and never writes) index rows for
--     excluded users;
--   * rebuild_search_index sweeps them;
--   * search re-checks exclusions live per request (fail closed).
--
-- Rows are inserted ONLY after positive, evidence-grounded identification
-- of the account — never by naming heuristics. The reason column records
-- that evidence. Exclusion never touches the account's own data, auth, or
-- the owner's private passport views — it removes ONE thing: presence in
-- recruiter bulk discovery.
--
-- RLS: service-role only (like recruiter_search_index).
-- Additive only; idempotent; no existing tables modified.
-- ============================================================

create table if not exists public.recruiter_discovery_exclusions (
  user_id    uuid primary key references public.users (id) on delete cascade,
  reason     text not null,
  created_at timestamptz not null default now()
);

alter table public.recruiter_discovery_exclusions enable row level security;

drop policy if exists "recruiter_discovery_exclusions: service role all"
  on public.recruiter_discovery_exclusions;
create policy "recruiter_discovery_exclusions: service role all"
  on public.recruiter_discovery_exclusions for all to service_role
  using (true) with check (true);

notify pgrst, 'reload schema';

-- ------------------------------------------------------------
-- Rollback (manual):
--   drop table if exists public.recruiter_discovery_exclusions;
-- ------------------------------------------------------------
