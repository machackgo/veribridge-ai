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
-- Idempotent: safe to re-run (ENABLE on a table that already has RLS is a
-- no-op). Runs as one transaction; `if exists` lets the tables that are present
-- get RLS even where a table was never created (feature not deployed).
-- lock_timeout bounds the brief ACCESS EXCLUSIVE lock each ALTER needs: if a
-- long-running query holds the table, the migration fails fast and can be
-- retried instead of queueing every other query behind it.
-- ============================================================

begin;
set local lock_timeout = '5s';
alter table if exists public.proof_artifacts enable row level security;
alter table if exists public.video_proofs enable row level security;
alter table if exists public.video_proof_transcript_segments enable row level security;
alter table if exists public.video_proof_frames enable row level security;
commit;
