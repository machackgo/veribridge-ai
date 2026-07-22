-- ============================================================
-- VeriBridge AI — Migration 058: workflow_analysis_results.filtered_unrelated_activity
--
-- The workflow analyzer (extension_proof_workflow_analysis_service._analyze_workflow)
-- emits a `filtered_unrelated_activity` object describing navigation the analyzer
-- classified as noise (unrelated hosts) and excluded from the workflow evidence:
--
--   "filtered_unrelated_activity": { "count": <int>, "hosts": [ ... ] }
--
-- The result dict is persisted to workflow_analysis_results via `**result`, but
-- migration 038 (which back-filled every other v2–v6 field) never added this
-- column. Every analysis write therefore logs:
--
--   Could not find the 'filtered_unrelated_activity' column of
--   'workflow_analysis_results' in the schema cache
--
-- and the field silently drops — the honest "we ignored this off-target
-- activity" evidence is lost, and reports fall back to an in-memory value that
-- never survives a reload. This migration adds the column so the value persists.
--
-- Additive only. ADD COLUMN IF NOT EXISTS → idempotent, safe to re-run.
-- ============================================================

alter table public.workflow_analysis_results
  -- { "count": <int>, "hosts": [ { "host": ..., "count": ... }, ... ] }
  -- Off-target navigation the analyzer filtered out of the workflow evidence.
  add column if not exists filtered_unrelated_activity jsonb default null;
