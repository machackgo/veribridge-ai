-- ============================================================
-- VeriBridge AI — Migration 046: Project Defense transcript segments
--
-- Adds timestamped transcript fields used by local_whisper/faster-whisper
-- Project Defense transcription and final evidence evaluation.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS
-- ============================================================

alter table public.project_defense_analysis_results
  add column if not exists transcript_segments jsonb not null default '[]'::jsonb,
  add column if not exists transcript_language text,
  add column if not exists transcript_provider text,
  add column if not exists transcript_status text not null default 'not_configured',
  add column if not exists transcript_error text;

create index if not exists project_defense_transcript_status_idx
  on public.project_defense_analysis_results (transcript_status);
