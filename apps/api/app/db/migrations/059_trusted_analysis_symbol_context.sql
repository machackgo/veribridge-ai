-- ============================================================
-- VeriBridge AI — Migration 059: Trusted analysis symbol context
--
-- Strengthens the GitHub code-purpose classification pipeline.
--
-- BACKGROUND
-- ``trusted_github_evidence_analysis`` (migration 053) stores the scanner's
-- grade + redacted focused excerpt per canonical ``skill_evidence`` row. Some
-- historical rows persisted MID-STATEMENT fragments (e.g. the continuation
-- lines of a multi-line ``from x import (…)``) whose bare metric names read as
-- implementation signals, producing "purpose unknown" rows that still counted
-- as implementation evidence.
--
-- THIS MIGRATION
-- * ``symbol_name`` / ``symbol_type`` — the AST-derived containing
--   function/method/class of the cited target lines.
-- * ``context_start_line`` / ``context_end_line`` — the ANALYZED context
--   window when it is wider than the cited target lines (the citation itself
--   is never rewritten; reports render this as "Analyzed context").
-- * ``analysis_history`` — append-only JSONB history of prior analyses, so
--   reclassification preserves provenance instead of overwriting it silently.
--
-- Additive only; no existing columns/tables are modified. Idempotent.
-- ============================================================

alter table public.trusted_github_evidence_analysis
  add column if not exists symbol_name        text,
  add column if not exists symbol_type        text,
  add column if not exists context_start_line int,
  add column if not exists context_end_line   int,
  add column if not exists analysis_history   jsonb not null default '[]'::jsonb;

-- RLS from migration 053 is unchanged: service-role only, no authenticated
-- policies of any kind — students can neither read nor forge these columns.
