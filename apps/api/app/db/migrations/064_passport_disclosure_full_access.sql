-- ============================================================
-- VeriBridge AI — Migration 064: Full-access Passport disclosure mode
--
-- Migration 063 shipped a two-value mode vocabulary:
--
--   check (mode in ('recruiter_safe', 'custom'))
--
-- This migration widens that closed vocabulary by exactly ONE value,
-- 'full_access' — the deliberate "everything supported is public"
-- disclosure mode a student may opt into from the Privacy Center.
--
-- Scope is intentionally minimal:
--   * NO new tables, columns, indexes or policies. The disclosure
--     spine, the override vocabulary, the audit table and every RLS
--     policy from migration 063 are untouched and NOT duplicated.
--   * NO data is rewritten. Every existing row keeps its current mode;
--     the column default stays 'recruiter_safe', so no passport can be
--     moved into full access except by an explicit, confirmed owner
--     action through PUT /api/v1/student/passport/disclosure/mode.
--   * full_access is resolved entirely in the canonical resolver
--     (services/passport_disclosure.py FULL_ACCESS_DEFAULTS) — it
--     never writes override rows, so a student's granular policy
--     survives intact and is reapplied verbatim on a later switch
--     back to 'custom'.
--
-- Deploy ordering: apply this migration BEFORE the API deploy. The API
-- fails closed on an unknown mode value (get_policy downgrades to
-- 'recruiter_safe'), so an API running ahead of the migration would
-- reject every full-access write with a 23514 check violation.
--
-- Idempotent: safe to re-run.
-- ============================================================

-- The constraint created by 063 is unnamed, so Postgres auto-named it
-- <table>_<column>_check. Drop by that canonical name if present, then
-- drop the explicitly named form this migration installs, so re-running
-- is a no-op either way.
alter table public.passport_disclosure_policies
  drop constraint if exists passport_disclosure_policies_mode_check;

alter table public.passport_disclosure_policies
  drop constraint if exists passport_disclosure_policies_mode_allowed;

alter table public.passport_disclosure_policies
  add constraint passport_disclosure_policies_mode_allowed
  check (mode in ('recruiter_safe', 'full_access', 'custom'));

-- ------------------------------------------------------------
-- Rollback (manual, no data loss — run BEFORE reverting the API):
--
--   update public.passport_disclosure_policies
--      set mode = 'recruiter_safe', disclosure_version = disclosure_version + 1
--    where mode = 'full_access';
--
--   alter table public.passport_disclosure_policies
--     drop constraint if exists passport_disclosure_policies_mode_allowed;
--   alter table public.passport_disclosure_policies
--     add constraint passport_disclosure_policies_mode_check
--     check (mode in ('recruiter_safe', 'custom'));
--
-- Reverting NARROWS public exposure (full access → recruiter-safe) and
-- bumps disclosure_version so any cached public representation is
-- immediately recognized as stale. Stored override rows are untouched.
-- ------------------------------------------------------------
