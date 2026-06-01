-- ============================================================
-- VeriBridge AI — Migration 043: Follow-up proof session linkage
--
-- Adds nullable columns to extension_proof_sessions so a follow-up
-- recording can reference its parent session and capture the specific
-- skill/objective it is targeting.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, CREATE INDEX IF NOT EXISTS.
-- ============================================================

alter table public.extension_proof_sessions
  add column if not exists parent_proof_session_id uuid
    references public.extension_proof_sessions (id) on delete set null,
  add column if not exists followup_target_skill   text,
  add column if not exists followup_objective      text,
  add column if not exists proof_attempt_type      text not null default 'original'
    check (proof_attempt_type in ('original', 'followup'));

create index if not exists ext_proof_sessions_parent_proof_idx
  on public.extension_proof_sessions (parent_proof_session_id)
  where parent_proof_session_id is not null;
