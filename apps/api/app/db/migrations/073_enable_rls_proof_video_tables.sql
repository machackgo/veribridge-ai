-- ============================================================
-- VeriBridge AI — Migration 073: Enable RLS on proof/video tables
-- ============================================================
--
-- Migrations 056 (proof_artifacts) and 057 (video_proofs,
-- video_proof_transcript_segments, video_proof_frames) created their tables
-- without enabling Row Level Security. Under Supabase's default grants the
-- anon / authenticated roles could therefore reach these tables directly
-- through PostgREST with the public anon key.
--
-- All access to these tables is API-mediated: the FastAPI service uses the
-- service-role client (which bypasses RLS) and enforces ownership and the
-- access_policy vocabulary in application code. Neither the web app nor the
-- extension queries these tables directly.
--
-- Enabling RLS with NO policies denies anon/authenticated direct access and
-- leaves service-role access unchanged.
--
-- Idempotent: safe to re-run.
-- ============================================================

alter table public.proof_artifacts enable row level security;
alter table public.video_proofs enable row level security;
alter table public.video_proof_transcript_segments enable row level security;
alter table public.video_proof_frames enable row level security;
