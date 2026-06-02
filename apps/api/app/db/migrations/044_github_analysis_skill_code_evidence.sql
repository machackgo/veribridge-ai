-- ============================================================
-- VeriBridge AI — Migration 044: Add skill_code_evidence to
-- extension_proof_github_analysis
--
-- Stores per-skill deep code evidence (file paths, line ranges,
-- code snippets, exact GitHub blob URLs) discovered by the
-- extended GitHub analyzer.
--
-- Idempotent:
--   • ALTER TABLE … ADD COLUMN IF NOT EXISTS
-- ============================================================

alter table public.extension_proof_github_analysis
  add column if not exists skill_code_evidence jsonb not null default '[]'::jsonb;
