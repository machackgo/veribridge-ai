-- VeriBridge AI — Migration 038: Workflow Analysis Results v4 columns
--
-- Adds all columns used by analysis versions v2–v6 that are absent from the
-- original migration 015 schema.  All ALTER TABLE … ADD COLUMN IF NOT EXISTS,
-- so re-running on an already-migrated database is safe (idempotent).
--
-- Missing columns surfaced by WORKFLOW_ANALYSIS_DB_INSERT_FAILED error:
--   "Could not find the 'has_graphical_rendering' column of
--    'workflow_analysis_results' in the schema cache"
--
-- Root cause: the service inserts many new fields added during v2–v6
-- development, but the Supabase schema was never refreshed with these columns.
--
-- Columns added here (grouped by feature version):
--   v2  target-site filtering metadata
--   v3  precise visual workflow evidence (observed_demonstration)
--   v4  DOM visible evidence enrichment
--   v5  visual frame analysis (provider-agnostic)
--   v6  sequence analysis (multi-frame temporal chain)

-- ---------------------------------------------------------------------------
-- v2: target-site filtering metadata
-- ---------------------------------------------------------------------------

alter table public.workflow_analysis_results
  add column if not exists target_website              text        not null default '',
  add column if not exists target_site_pages_count     integer     not null default 0,
  add column if not exists supporting_evidence_count   integer     not null default 0,
  add column if not exists noise_filtered_count        integer     not null default 0;

-- ---------------------------------------------------------------------------
-- v3: precise visual workflow evidence
-- ---------------------------------------------------------------------------

alter table public.workflow_analysis_results
  -- Full observed demonstration JSON (target_app, steps, summary, limitations)
  add column if not exists observed_demonstration      jsonb       default null;

-- ---------------------------------------------------------------------------
-- v4: DOM visible evidence enrichment
-- ---------------------------------------------------------------------------

alter table public.workflow_analysis_results
  -- Whether DOM-text evidence was captured by the extension
  add column if not exists visible_evidence_status     text        not null default 'not_captured'
    check (visible_evidence_status in ('available', 'partial', 'not_captured'))  ,
  -- Explicit alias used in UI (same values as visible_evidence_status)
  add column if not exists dom_evidence_status         text        not null default 'not_captured',
  -- Whether graphical elements (canvas/SVG) were detected on the result page
  add column if not exists has_graphical_rendering     boolean     not null default false,
  -- Human-readable note about graphical rendering limitation (null when not detected)
  add column if not exists graphical_rendering_note    text        default null,
  -- Top result-like text snippets for UI surface (up to 5)
  add column if not exists top_result_snippets         jsonb       not null default '[]'::jsonb,
  -- DOM-derived context summary of visited pages
  add column if not exists page_context_summary        text        default null;

-- ---------------------------------------------------------------------------
-- v5: visual frame analysis (provider-agnostic local-first)
-- ---------------------------------------------------------------------------

alter table public.workflow_analysis_results
  -- Overall status of visual frame / OCR analysis
  add column if not exists visual_analysis_status      text        not null default 'not_configured',
  -- Which provider ran (none | local_ocr | local_vision | openai | veribridge_future)
  add column if not exists visual_analysis_provider    text        not null default 'none',
  -- How many frames were analyzed by the visual provider
  add column if not exists visual_frame_count          integer     not null default 0,
  -- How many frames are stored (includes not_configured frames)
  add column if not exists visual_frames_stored        integer     not null default 0,
  -- OCR sub-component status
  add column if not exists ocr_status                  text        not null default 'not_configured',
  -- Result values extracted from frame analysis [{label, value, confidence, source}]
  add column if not exists visual_result_values        jsonb       not null default '[]'::jsonb,
  -- Free-form visual summary from the provider
  add column if not exists visual_summary              text        not null default '';

-- ---------------------------------------------------------------------------
-- v6: sequence analysis (multi-frame temporal chain)
-- ---------------------------------------------------------------------------

alter table public.workflow_analysis_results
  -- Full sequence analysis result (to_public_dict() output — no raw paths)
  add column if not exists sequence_analysis           jsonb       default null;

-- ---------------------------------------------------------------------------
-- Helpful indexes on new queryable fields
-- ---------------------------------------------------------------------------

create index if not exists workflow_analysis_results_visible_evidence_status_idx
  on public.workflow_analysis_results (visible_evidence_status);

create index if not exists workflow_analysis_results_visual_analysis_status_idx
  on public.workflow_analysis_results (visual_analysis_status);
