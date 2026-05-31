-- VeriBridge AI — Migration 040: Add frame_ocr_evidence_summary column
--
-- Adds the frame_ocr_evidence_summary jsonb column to workflow_analysis_results.
-- This column stores the structured OCR evidence summary built by
-- _build_frame_ocr_evidence_summary() during workflow analysis (v6).
--
-- Contains:
--   has_ocr_evidence      bool
--   ocr_provider          str  (local_ocr | none | ...)
--   frames_analyzed       int
--   top_ocr_snippets      list[str]  — public-safe, max 8, max 120 chars each
--   detected_page_context str        — homepage_marketing | training_ui | prediction_output | unknown
--   observed_summary      str        — what was visually/textually observed
--   what_was_not_observed list[str]  — specific things not observed
--   skill_signals         list[dict] — per-skill OCR support signals
--
-- Privacy guarantee:
--   This column NEVER stores raw frame paths, storage URLs, access tokens,
--   raw DOM, debug metadata, or admin notes.
--   _safe_frame_ocr_summary() in the API endpoint additionally strips any
--   private fields before exposing to clients.
--
-- Idempotent: safe to re-run on an already-migrated database.

alter table public.workflow_analysis_results
  add column if not exists frame_ocr_evidence_summary jsonb default null;

comment on column public.workflow_analysis_results.frame_ocr_evidence_summary is
  'Structured OCR/visual evidence summary from video keyframes (v6). '
  'Public-safe: no raw paths, storage URLs, or tokens. '
  'null for sessions analysed before this migration or when no video was uploaded.';
