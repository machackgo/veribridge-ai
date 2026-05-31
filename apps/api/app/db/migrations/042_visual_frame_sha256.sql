-- VeriBridge AI — Migration 042: Add frame_sha256 traceability column
--
-- Adds frame_sha256 to workflow_visual_frame_evidence so each keyframe
-- can be integrity-verified without exposing raw bytes.
--
-- The hash is a SHA-256 of the raw JPEG/PNG bytes, computed at upload
-- time and stored as a 64-char hex string.  It lets a dev-only endpoint
-- confirm "did Qwen see this exact frame?" without storing the bytes.
--
-- Idempotent: safe to re-run.

alter table public.workflow_visual_frame_evidence
  add column if not exists frame_sha256 text default null;

comment on column public.workflow_visual_frame_evidence.frame_sha256 is
  'SHA-256 hex digest of the raw frame bytes, computed at upload time (migration 042). '
  'Used by the dev-only debug endpoint to confirm frame identity without exposing bytes. '
  'null for frames uploaded before this migration.';

create index if not exists workflow_visual_frame_evidence_sha256_idx
  on public.workflow_visual_frame_evidence (proof_session_id, frame_sha256)
  where frame_sha256 is not null;
