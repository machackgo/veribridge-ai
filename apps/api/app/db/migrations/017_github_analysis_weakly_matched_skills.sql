-- ============================================================
-- VeriBridge AI — Migration 017: Add weakly_matched_claimed_skills
--
-- Adds a column to extension_proof_github_analysis to store skills
-- that have partial or contextual evidence (README text, live URL,
-- page title, deployment context) rather than direct dependency-file
-- confirmation.
--
-- Idempotent:
--   • ALTER TABLE … ADD COLUMN IF NOT EXISTS
-- ============================================================

alter table public.extension_proof_github_analysis
  add column if not exists weakly_matched_claimed_skills jsonb not null default '[]'::jsonb;
