-- VeriBridge AI — Migration 041: Advanced Visual Reasoning columns
--
-- Adds two columns to support Level 3 visual reasoning (Qwen2.5-VL / Qwen3-VL):
--
--   workflow_visual_frame_evidence.visual_reasoning_json
--     Per-frame structured reasoning output from the vision model.
--     Stored at video upload time if VISUAL_REASONING_ENABLED=true.
--     Contains: visual_summary, visible_ui_elements, visible_objects,
--     detected_workflow_stage, detected_actions, detected_outputs,
--     detected_skills_supported, missing_or_unclear_evidence,
--     confidence_score, limitations, status, model_provider.
--
--   workflow_analysis_results.visual_reasoning_summary
--     Session-level aggregated reasoning summary built during workflow analysis.
--     Contains: status, provider, frames_analyzed, summary,
--     observations (list[dict]), supported_signals, missing_claims, limitations.
--
-- Privacy guarantees:
--   These columns NEVER store raw frame paths, storage URLs, access tokens,
--   raw DOM, debug metadata, or frame pixel bytes.
--   _safe_visual_reasoning_summary() in the API endpoint strips any private
--   fields before exposing to clients.
--
-- Idempotent: safe to re-run on an already-migrated database.

-- 1. Per-frame reasoning storage
alter table public.workflow_visual_frame_evidence
  add column if not exists visual_reasoning_json jsonb default null;

comment on column public.workflow_visual_frame_evidence.visual_reasoning_json is
  'Per-frame structured reasoning from Qwen2.5-VL / Qwen3-VL (v7, migration 041). '
  'Populated when VISUAL_REASONING_ENABLED=true. '
  'null when reasoning is disabled or model not installed. '
  'Public-safe: no raw paths, storage URLs, or tokens.';

-- 2. Session-level reasoning summary
alter table public.workflow_analysis_results
  add column if not exists visual_reasoning_summary jsonb default null;

comment on column public.workflow_analysis_results.visual_reasoning_summary is
  'Aggregated advanced visual reasoning summary for a recording session (v7, migration 041). '
  'Populated during workflow analysis when visual_reasoning_json frames exist. '
  'null for sessions analysed before this migration or when reasoning is disabled. '
  'Public-safe: no raw paths, storage URLs, or tokens.';
