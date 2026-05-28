-- VeriBridge AI - Migration 035: Workflow Visual Frame Evidence
--
-- Adds a table to store visual frame screenshots captured by the browser
-- extension at key moments during website proof recordings.
--
-- Provider-agnostic design:
--   • visual_analysis_provider can be: none, local_ocr, local_vision, openai, veribridge_future
--   • If no provider is configured, rows are stored with visual_analysis_status='not_configured'
--   • DOM evidence continues to work regardless of visual provider status
--
-- Privacy design:
--   • frame_storage_path is NEVER exposed to recruiters or in public APIs.
--   • Only aggregated/summarised output fields are surfaced externally.
--   • ocr_text and visual_objects are student-private.
--   • privacy_flags records any PII detected and masked during analysis.
--
-- Backward compatibility:
--   • Old sessions without visual frames continue to show
--     visual_analysis_status='not_configured' in workflow analysis.
--   • All existing DOM/event evidence analysis continues unchanged.

-- ---------------------------------------------------------------------------
-- Table
-- ---------------------------------------------------------------------------

create table if not exists public.workflow_visual_frame_evidence (
  id                              uuid        primary key default gen_random_uuid(),

  -- Ownership
  user_id                         text        not null,
  proof_session_id                text        not null,

  -- Optional link back to a DOM visible evidence event (nullable)
  visible_evidence_event_id       uuid        references public.workflow_visible_evidence_events(id)
                                              on delete set null,

  -- When in the recording this frame was captured (ms from recording start)
  timestamp_ms                    integer,

  -- What triggered this capture
  frame_type                      text        not null default 'screenshot'
    check (frame_type in (
      'recording_start',
      'page_load',
      'after_click',
      'after_upload',
      'after_form_submit',
      'after_dom_mutation',
      'after_result_detected',
      'recording_end',
      'screenshot'
    )),

  -- Storage paths (private — never exposed publicly)
  frame_storage_path              text,
  frame_thumbnail_storage_path    text,

  -- Frame dimensions (pixels)
  frame_width                     integer,
  frame_height                    integer,

  -- Analysis provider that processed this frame
  visual_analysis_provider        text,

  -- Analysis lifecycle status
  visual_analysis_status          text        not null default 'pending'
    check (visual_analysis_status in (
      'pending',
      'analyzed',
      'skipped',
      'failed',
      'not_configured'
    )),

  -- OCR-extracted text blocks (array of {text, confidence, bbox})
  ocr_text                        jsonb       not null default '[]',

  -- Detected visual objects / UI elements (array of {label, confidence, bbox, source})
  visual_objects                  jsonb       not null default '[]',

  -- Free-form summary from vision model or OCR post-processing
  visual_summary                  text,

  -- Structured result values extracted from this frame
  -- Array of {label, value, confidence, source}
  extracted_result_values         jsonb       not null default '[]',

  -- Privacy flags raised during visual analysis (PII detection, etc.)
  privacy_flags                   jsonb       not null default '[]',

  -- Timestamps
  created_at                      timestamptz not null default now(),
  analyzed_at                     timestamptz
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

create index if not exists workflow_visual_frame_evidence_session_idx
  on public.workflow_visual_frame_evidence (proof_session_id);

create index if not exists workflow_visual_frame_evidence_user_session_idx
  on public.workflow_visual_frame_evidence (user_id, proof_session_id);

create index if not exists workflow_visual_frame_evidence_type_idx
  on public.workflow_visual_frame_evidence (proof_session_id, frame_type);

create index if not exists workflow_visual_frame_evidence_status_idx
  on public.workflow_visual_frame_evidence (visual_analysis_status);

-- ---------------------------------------------------------------------------
-- Row-Level Security
-- ---------------------------------------------------------------------------

alter table public.workflow_visual_frame_evidence enable row level security;

-- Students can read / insert their own frames only
create policy "student_own_visual_frame_evidence"
  on public.workflow_visual_frame_evidence
  for all
  using (auth.uid()::text = user_id)
  with check (auth.uid()::text = user_id);

-- Service role (backend) has full access
create policy "service_role_visual_frame_evidence"
  on public.workflow_visual_frame_evidence
  for all
  to service_role
  using (true)
  with check (true);

-- Recruiters: NO access — they use workflow_analysis_results (the processed summary)
-- There is intentionally no recruiter policy here.
