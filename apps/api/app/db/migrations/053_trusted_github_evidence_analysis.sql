-- ============================================================
-- VeriBridge AI — Migration 053: Trusted GitHub evidence analysis
--
-- Security hardening for GitHub skill-evidence quality grading.
--
-- BACKGROUND
-- The GitHub Portfolio & Proof scanner computes, FROM REAL SOURCE at
-- scan time, a deterministic ``evidence_quality_grade`` (e.g.
-- ``implementation_body`` / ``supporting_logic``) plus a focused,
-- secret-redacted source excerpt for each precise ``skill_evidence``
-- row. Read-time services (the Verified Work Passport / VBR report /
-- proof vault) trust that grade so a genuine implementation body can
-- outrank import / docstring / config / bare-route-decorator windows.
--
-- THREAT
-- That trusted provenance used to live inside ``skill_evidence.metadata``
-- (a JSONB column). But ``skill_evidence`` carries an "own row ALL" RLS
-- policy (migration 001): an authenticated student can UPDATE their own
-- rows directly via Supabase, bypassing the FastAPI schema that strips
-- client-supplied provenance. A hostile owner could therefore inject the
-- analyzer marker + ``evidence_quality_grade="implementation_body"`` into
-- their own metadata and FORGE a strong, recruiter-facing grade with no
-- real source behind it. FastAPI-layer stripping alone is not enough.
--
-- FIX
-- Trusted provenance moves OUT of user-editable metadata into this
-- dedicated, service-role-only table. Authenticated users have NO insert
-- / update / delete / select policy here, so a student can neither write
-- (forge) nor read these rows directly. Only the backend service role
-- (the offline scanner / import path) writes provenance, and only the
-- backend service role reads it back at render time to decide whether a
-- persisted strong grade may be trusted. ``skill_evidence.metadata`` is
-- never again sufficient to establish implementation quality.
--
-- No existing tables are modified. Idempotent: safe to re-run.
-- ============================================================

create extension if not exists pgcrypto;

create table if not exists public.trusted_github_evidence_analysis (
  id                      uuid        primary key default gen_random_uuid(),
  -- One trusted provenance record per canonical skill_evidence row. ON DELETE
  -- CASCADE keeps provenance from outliving the evidence it describes.
  skill_evidence_id       uuid        not null unique
                            references public.skill_evidence (id) on delete cascade,
  -- Denormalized owner so the backend can fetch a user's whole provenance set in
  -- one service-role query at render time without a join.
  user_id                 uuid        references public.users (id) on delete cascade,
  -- Controlled analyzer identity. Read-time trust requires BOTH a recognized
  -- analyzer_name AND a recognized analyzer_version; a stale version fails closed.
  analyzer_name           text        not null,
  analyzer_version        text        not null,
  -- The grade the analyzer computed FROM REAL SOURCE at scan time.
  evidence_quality_grade  text,
  evidence_quality_reason text,
  -- Focused 1-indexed line range inside the parsed source.
  focused_start_line      int,
  focused_end_line        int,
  -- A focused, ALREADY-REDACTED source excerpt (secrets scrubbed before storage)
  -- + a hash of it. Never the raw file; never exposed in any public payload.
  safe_excerpt            text,
  snippet_hash            text,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

create index if not exists trusted_github_evidence_analysis_user_idx
  on public.trusted_github_evidence_analysis (user_id);

create or replace trigger set_trusted_github_evidence_analysis_updated_at
  before update on public.trusted_github_evidence_analysis
  for each row execute function public.set_updated_at();

-- ------------------------------------------------------------
-- Row Level Security
--
-- This is a SERVER-OWNED provenance table. There is intentionally NO
-- authenticated policy of any kind: authenticated students can neither
-- write (so they cannot forge a trusted grade / analyzer marker) nor
-- read (provenance internals / excerpts never reach a public surface
-- directly). Only the backend service role writes and reads these rows,
-- and the public/report services consume them exclusively through that
-- service-role backend path, returning only sanitized, public-safe data.
-- ------------------------------------------------------------
alter table public.trusted_github_evidence_analysis enable row level security;

drop policy if exists "trusted_github_evidence_analysis: service role all"
  on public.trusted_github_evidence_analysis;
create policy "trusted_github_evidence_analysis: service role all"
  on public.trusted_github_evidence_analysis
  for all
  to service_role
  using (true)
  with check (true);
