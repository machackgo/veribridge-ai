-- ============================================================
-- VeriBridge AI — Migration 057: Video Proof (first-class proof type)
--
-- Students can upload or record a project demonstration video (class
-- demo, walkthrough, live presentation, screen demo, prototype demo,
-- hackathon demo). This makes that a FIRST-CLASS proof input with its
-- own retention + analysis model instead of piggybacking on Project
-- Defense recordings.
--
--   * The original bytes live in Supabase Storage and are registered
--     in `proof_artifacts` (artifact_type = 'video_proof_original');
--     `video_proofs.original_artifact_id` points at that row. Frames
--     are 'video_proof_frame' artifacts referenced per-row below.
--   * `analysis` is the structured video_analysis object
--     (demo_summary / observed_workflow / observed_inputs /
--     observed_outputs / project_features_shown / skills_supported /
--     proof_strength / limitations / corroborates_with /
--     needs_review). Statuses are HONEST: when transcription or
--     frame extraction is not configured the status says so — no
--     stage ever fakes results.
--   * Epistemics by design: a demo video can show runtime behaviour,
--     UI workflow, and the candidate's explanation. It cannot prove
--     authorship, implementation, model training, security
--     correctness, or production readiness — the analysis carries
--     those limitations verbatim and `needs_review` defaults true.
--
-- No existing tables are modified. Idempotent: safe to re-run.
-- ============================================================

create extension if not exists pgcrypto;

create table if not exists public.video_proofs (
  id                    uuid primary key default gen_random_uuid(),
  user_id               uuid not null references public.users (id) on delete cascade,
  project_id            uuid,

  title                 text not null default '',
  description           text,
  -- What kind of demonstration the student says this is. Closed set.
  source_kind           text not null default 'uploaded_demo'
                          check (source_kind in (
                            'uploaded_demo',
                            'class_demo',
                            'project_walkthrough',
                            'live_presentation',
                            'screen_demo',
                            'prototype_demo',
                            'hackathon_demo'
                          )),

  status                text not null default 'uploaded'
                          check (status in ('uploaded', 'processing', 'analyzed', 'failed')),

  -- Student-claimed skills this video is meant to support (JSON array of
  -- strings). Claims — the analysis never upgrades them to verified.
  claimed_skills        jsonb not null default '[]'::jsonb,

  -- Retained original (proof_artifacts row, artifact_type='video_proof_original').
  original_artifact_id  uuid references public.proof_artifacts (id) on delete set null,

  mime_type             text,
  file_name             text,
  size_bytes            bigint,
  duration_seconds      double precision,

  -- Honest per-stage statuses — 'not_configured' / 'not_available' mean the
  -- capability is absent in this deployment, never silently skipped.
  transcript_status     text not null default 'pending'
                          check (transcript_status in
                            ('pending', 'completed', 'no_speech', 'not_configured', 'failed')),
  frames_status         text not null default 'pending'
                          check (frames_status in
                            ('pending', 'completed', 'not_available', 'failed')),
  analysis_status       text not null default 'pending'
                          check (analysis_status in ('pending', 'completed', 'failed')),

  -- Structured video_analysis object (see video_proof_service.py).
  analysis              jsonb,
  needs_review          boolean not null default true,

  -- Sharing gate: false → owner-only. True propagates recruiter_safe access
  -- to the retained artifacts via the service (never bypassing proof_artifacts
  -- access_policy checks).
  public_safe           boolean not null default false,

  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create index if not exists video_proofs_user_idx
  on public.video_proofs (user_id);

create index if not exists video_proofs_project_idx
  on public.video_proofs (project_id)
  where project_id is not null;

-- Time-aligned narration transcript segments extracted from the audio track.
create table if not exists public.video_proof_transcript_segments (
  id              uuid primary key default gen_random_uuid(),
  video_proof_id  uuid not null references public.video_proofs (id) on delete cascade,
  seq             integer not null default 0,
  start_s         double precision not null default 0,
  end_s           double precision not null default 0,
  text            text not null default '',
  speaker         text,
  created_at      timestamptz not null default now()
);

create index if not exists video_proof_transcript_segments_proof_idx
  on public.video_proof_transcript_segments (video_proof_id, seq);

-- Extracted visual frames. OCR / object / UI-element detection columns are
-- part of the schema now but are populated ONLY when a real CV pipeline runs
-- (future work) — they stay null until then, never placeholder text.
create table if not exists public.video_proof_frames (
  id                    uuid primary key default gen_random_uuid(),
  video_proof_id        uuid not null references public.video_proofs (id) on delete cascade,
  timestamp_s           double precision,
  frame_artifact_id     uuid references public.proof_artifacts (id) on delete set null,
  ocr_text              text,
  detected_objects      jsonb,
  detected_ui_elements  jsonb,
  activity_summary      text,
  relevance_to_skill    text,
  created_at            timestamptz not null default now()
);

create index if not exists video_proof_frames_proof_idx
  on public.video_proof_frames (video_proof_id, timestamp_s);
