-- VeriBridge AI - Migration 033: Project Defense Transcript Refinement
--
-- Adds refinement fields to project_defense_analysis_results so we can store
-- both the raw ASR transcript and the AI-corrected version side by side.
--
-- Fields added:
--   raw_transcript                  — verbatim ASR output (never overwritten)
--   refined_transcript              — context-aware corrected transcript
--   transcript_correction_summary   — JSONB list of individual corrections made
--   transcript_glossary_matches     — JSONB list of terms matched from glossary
--   transcript_refinement_status    — lifecycle flag: not_started | in_progress | complete | failed
--   transcript_needs_review         — true when confidence is low or many corrections
--
-- Design:
--   transcript_text remains the "working" transcript that analysis runs on
--   (either the original or the student-approved refined version).
--   raw_transcript is append-only for audit purposes.
--   refined_transcript is the AI-suggested correction.
--   transcript_needs_review signals the UI to prompt the student to verify.

alter table if exists public.project_defense_analysis_results
  add column if not exists raw_transcript text,
  add column if not exists refined_transcript text,
  add column if not exists transcript_correction_summary jsonb not null default '[]'::jsonb,
  add column if not exists transcript_glossary_matches jsonb not null default '[]'::jsonb,
  add column if not exists transcript_refinement_status text not null default 'not_started'
    check (transcript_refinement_status in ('not_started', 'in_progress', 'complete', 'failed')),
  add column if not exists transcript_needs_review boolean not null default false;

-- Index on refinement status for admin queries
create index if not exists idx_project_defense_refinement_status
  on public.project_defense_analysis_results (transcript_refinement_status)
  where transcript_refinement_status != 'not_started';
