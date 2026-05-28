-- VeriBridge AI - Migration 034: Workflow Visible Evidence Events
--
-- Adds a table to store DOM-visible evidence snapshots captured by the browser
-- extension during website proof recordings.  Each row is one "capture moment":
-- page_load, click, file_upload, form_submit, dom_snapshot, result_detected, etc.
--
-- Privacy design:
--   • Raw visible text is stored ONLY for the student's own session (private).
--   • Recruiters never see raw visible_text_blocks or result_like_blocks directly.
--   • Recruiter-facing surfaces only use aggregated / summarised public-safe fields
--     produced by the workflow analysis service.
--   • sanitized = true means the service has already removed sensitive tokens;
--     every row should have sanitized = true before storage.
--
-- Backward compatibility:
--   • Old sessions without visible evidence show visible_evidence_status = 'not_captured'
--     in the workflow analysis result.  All existing analysis still works.

-- ---------------------------------------------------------------------------
-- Table
-- ---------------------------------------------------------------------------

create table if not exists public.workflow_visible_evidence_events (
  id                    uuid        primary key default gen_random_uuid(),
  user_id               text        not null,
  proof_session_id      text        not null,
  event_id              text,                           -- correlates with workflow_events.id if available
  timestamp_ms          integer,
  event_type            text        not null
    check (event_type in (
      'page_load',
      'click',
      'input_change',
      'file_upload',
      'form_submit',
      'dom_snapshot',
      'result_detected',
      'recording_end'
    )),
  url                   text,
  target_domain         text,
  page_title            text,
  -- Captured visible text (sanitized, student-private)
  visible_text_blocks   jsonb       not null default '[]',
  -- Text blocks that scored high on result/output keyword proximity
  result_like_blocks    jsonb       not null default '[]',
  -- Form inputs snapshot (sanitized – no passwords)
  input_snapshot        jsonb       not null default '{}',
  -- Clicked element or triggered action metadata
  action_snapshot       jsonb       not null default '{}',
  -- Privacy flags raised during sanitization
  sanitized             boolean     not null default true,
  privacy_flags         jsonb       not null default '[]',
  created_at            timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

create index if not exists workflow_visible_evidence_events_session_idx
  on public.workflow_visible_evidence_events (proof_session_id);

create index if not exists workflow_visible_evidence_events_user_session_idx
  on public.workflow_visible_evidence_events (user_id, proof_session_id);

create index if not exists workflow_visible_evidence_events_type_idx
  on public.workflow_visible_evidence_events (proof_session_id, event_type);

-- ---------------------------------------------------------------------------
-- Row-Level Security
-- ---------------------------------------------------------------------------

alter table public.workflow_visible_evidence_events enable row level security;

-- Students can read / insert their own events only
create policy "student_own_visible_evidence_events"
  on public.workflow_visible_evidence_events
  for all
  using (auth.uid()::text = user_id)
  with check (auth.uid()::text = user_id);

-- Service role (backend) has full access
create policy "service_role_visible_evidence_events"
  on public.workflow_visible_evidence_events
  for all
  to service_role
  using (true)
  with check (true);

-- Recruiters: NO access — they use workflow_analysis_results (the processed summary)
-- There is intentionally no recruiter policy here.
