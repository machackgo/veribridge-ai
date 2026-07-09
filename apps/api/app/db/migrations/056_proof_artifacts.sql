-- ============================================================
-- VeriBridge AI — Migration 056: Proof Artifact Retention
--
-- One additive registry for RETAINED original proof artifacts
-- (`proof_artifacts`). Until now several proof types analyzed an
-- original and then dropped it (document uploads) or never had a
-- retainable original at all (local/private website runtimes). A
-- recruiter could READ that proof exists but could not INSPECT the
-- original evidence. This table is the safe retention spine:
--
--   * `storage_path` / `storage_bucket` are PRIVATE server-side
--     locators. They are NEVER returned by any API response. All
--     access flows through gated backend routes
--     (`/api/v1/proofs/artifacts/{id}/view|download|signed-url`)
--     that stream bytes or mint short-lived signed URLs.
--   * `access_policy` is the closed access vocabulary:
--       owner_only     — only the owning student (default)
--       recruiter_safe — owner + any AUTHENTICATED non-owner
--       public_safe    — anyone the report surface admits
--       expired        — retained but no longer served to non-owners
--   * `public_safe` mirrors (access_policy = 'public_safe') for fast
--     filtering; the policy column is authoritative.
--   * `retained = false` rows are honest tombstones: metadata about
--     an artifact that was analyzed but whose bytes were not (or are
--     no longer) kept. Endpoints answer 404 — never a fake artifact.
--   * `redacted` marks a public-safe COPY derived from a private
--     original (e.g. a redacted document) — reserved for the future
--     redaction pipeline; no code fakes redacted copies today.
--
-- No existing tables are modified. Idempotent: safe to re-run.
-- ============================================================

create extension if not exists pgcrypto;

create table if not exists public.proof_artifacts (
  id                uuid primary key default gen_random_uuid(),
  owner_user_id     uuid not null references public.users (id) on delete cascade,

  -- Which proof surface this artifact belongs to.
  proof_type        text not null
                      check (proof_type in ('website', 'document', 'project_defense', 'video')),
  -- What the artifact IS. Closed set — additive only.
  artifact_type     text not null
                      check (artifact_type in (
                        'website_replay_video',
                        'website_frame',
                        'document_original',
                        'document_redacted',
                        'defense_transcript',
                        'defense_video',
                        'defense_audio',
                        'video_proof_original',
                        'video_proof_frame',
                        'video_proof_transcript'
                      )),

  -- Source linkage. `proof_id` is the id of the owning proof row in its
  -- own table (optional_evidence_submissions id, website proof session id,
  -- vbr_verification_sessions id, video_proofs id, …) — kept as text
  -- because source id shapes vary across proof engines.
  proof_id          text,
  report_id         uuid,
  project_id        uuid,

  -- PRIVATE storage locator — never exposed via API.
  storage_bucket    text,
  storage_path      text,

  retained          boolean not null default true,
  public_safe       boolean not null default false,
  redacted          boolean not null default false,
  access_policy     text not null default 'owner_only'
                      check (access_policy in ('owner_only', 'public_safe', 'recruiter_safe', 'expired')),

  mime_type         text,
  file_name         text,
  size_bytes        bigint,
  duration_seconds  double precision,
  page_count        integer,

  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists proof_artifacts_owner_idx
  on public.proof_artifacts (owner_user_id);

-- "Which retained artifacts exist for this proof" — the hot lookup used by
-- report builders and the replay/frames endpoints.
create index if not exists proof_artifacts_proof_idx
  on public.proof_artifacts (proof_type, proof_id);

create index if not exists proof_artifacts_project_idx
  on public.proof_artifacts (project_id)
  where project_id is not null;
