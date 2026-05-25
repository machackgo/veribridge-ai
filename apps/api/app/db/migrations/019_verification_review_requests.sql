-- ============================================================
-- VeriBridge AI — Migration 019: Verification Review Requests
--
-- Two tables:
--
--   verification_review_requests
--     One row per proof session review lifecycle.
--     Tracks both the AI-review track (Track A) and the
--     human/faculty/expert review track (Track B).
--
--   human_review_assignments
--     One row per reviewer assigned to a review request.
--     Supports future faculty, company, and domain-expert
--     reviewer programs.  MVP: table exists but is empty.
--
-- AI review status values (Track A):
--   not_submitted              — student has not yet requested review
--   submitted_for_ai_review    — student clicked "Submit for AI Review"
--   ai_review_in_progress      — 5-minute review timer is running
--   ai_approved_for_sharing    — passed readiness + privacy checks
--   needs_more_evidence        — score too low, not yet approvable
--   manual_review_recommended  — borderline; suggest human escalation
--   privacy_flagged            — privacy scan blocked AI approval
--
-- Human review status values (Track B):
--   human_review_not_requested   — default
--   human_review_requested       — student requested human review
--   faculty_review_pending       — assigned to faculty queue
--   company_review_pending       — assigned to company/mentor queue
--   domain_expert_review_pending — assigned to expert queue
--   faculty_reviewed             — faculty reviewer completed review
--   company_reviewed             — company reviewer completed review
--   domain_expert_reviewed       — domain expert completed review
--   human_verified               — manually set by admin/reviewer
--   human_review_rejected        — reviewer rejected the evidence
--
-- Reviewer roles:
--   veribridge_admin, faculty_reviewer, company_reviewer,
--   domain_expert, recruiter_reviewer
--
-- Idempotent:
--   CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS /
--   CREATE UNIQUE INDEX IF NOT EXISTS / CREATE INDEX IF NOT EXISTS /
--   CREATE OR REPLACE TRIGGER / ALTER TABLE ENABLE RLS /
--   DROP POLICY IF EXISTS + CREATE POLICY
-- ============================================================

-- ── Table: verification_review_requests ──────────────────────────────────────

create table if not exists public.verification_review_requests (
  id                          uuid        primary key default gen_random_uuid(),

  -- ownership
  user_id                     uuid        not null references public.users (id) on delete cascade,
  proof_session_id            uuid        not null references public.extension_proof_sessions (id) on delete cascade,

  -- Track A — AI review
  ai_review_status            text        not null default 'not_submitted'
                                            check (ai_review_status in (
                                              'not_submitted',
                                              'submitted_for_ai_review',
                                              'ai_review_in_progress',
                                              'ai_approved_for_sharing',
                                              'needs_more_evidence',
                                              'manual_review_recommended',
                                              'privacy_flagged'
                                            )),
  ai_review_started_at        timestamptz,
  ai_review_completed_at      timestamptz,
  ai_decision_summary         text        not null default '',

  -- Track B — Human review
  human_review_status         text        not null default 'human_review_not_requested'
                                            check (human_review_status in (
                                              'human_review_not_requested',
                                              'human_review_requested',
                                              'faculty_review_pending',
                                              'company_review_pending',
                                              'domain_expert_review_pending',
                                              'faculty_reviewed',
                                              'company_reviewed',
                                              'domain_expert_reviewed',
                                              'human_verified',
                                              'human_review_rejected'
                                            )),
  human_review_requested_at   timestamptz,

  -- Snapshot of readiness at submission time
  readiness_score             integer     not null default 0 check (readiness_score between 0 and 100),
  readiness_level             text        not null default 'insufficient'
                                            check (readiness_level in ('strong', 'moderate', 'weak', 'insufficient')),

  -- Audit timestamps
  submitted_at                timestamptz,
  created_at                  timestamptz not null default now(),
  updated_at                  timestamptz not null default now()
);

-- Idempotent column additions for manually-patched databases
alter table public.verification_review_requests
  add column if not exists ai_review_started_at      timestamptz,
  add column if not exists ai_review_completed_at    timestamptz,
  add column if not exists ai_decision_summary       text not null default '',
  add column if not exists human_review_requested_at timestamptz,
  add column if not exists submitted_at              timestamptz;

-- One active review lifecycle per session
create unique index if not exists verification_review_requests_session_idx
  on public.verification_review_requests (proof_session_id);

create index if not exists verification_review_requests_user_id_idx
  on public.verification_review_requests (user_id);

create index if not exists verification_review_requests_ai_status_idx
  on public.verification_review_requests (ai_review_status);

create index if not exists verification_review_requests_human_status_idx
  on public.verification_review_requests (human_review_status);

create index if not exists verification_review_requests_created_at_idx
  on public.verification_review_requests (created_at);

-- updated_at trigger
create or replace trigger set_verification_review_requests_updated_at
  before update on public.verification_review_requests
  for each row execute function public.set_updated_at();

-- Row-level security
alter table public.verification_review_requests enable row level security;

-- Students can see their own review requests
drop policy if exists "verification_review_requests: own row select"
  on public.verification_review_requests;
create policy "verification_review_requests: own row select"
  on public.verification_review_requests for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

-- Students can insert for their own sessions
drop policy if exists "verification_review_requests: own row insert"
  on public.verification_review_requests;
create policy "verification_review_requests: own row insert"
  on public.verification_review_requests for insert
  to authenticated
  with check (
    user_id::text = (select auth.uid())::text
    and exists (
      select 1
      from public.extension_proof_sessions eps
      where eps.id = proof_session_id
        and eps.user_id::text = (select auth.uid())::text
    )
  );

-- Students can update their own rows (e.g., request human review)
drop policy if exists "verification_review_requests: own row update"
  on public.verification_review_requests;
create policy "verification_review_requests: own row update"
  on public.verification_review_requests for update
  to authenticated
  using  (user_id::text = (select auth.uid())::text)
  with check (user_id::text = (select auth.uid())::text);

-- ── Table: human_review_assignments ──────────────────────────────────────────

create table if not exists public.human_review_assignments (
  id                      uuid        primary key default gen_random_uuid(),

  -- FK to the review request
  review_request_id       uuid        not null references public.verification_review_requests (id) on delete cascade,

  -- Reviewer identity
  reviewer_id             uuid        references public.users (id) on delete set null,
  reviewer_email          text        not null default '',
  reviewer_name           text        not null default '',
  reviewer_role           text        not null default 'faculty_reviewer'
                                        check (reviewer_role in (
                                          'veribridge_admin',
                                          'faculty_reviewer',
                                          'company_reviewer',
                                          'domain_expert',
                                          'recruiter_reviewer'
                                        )),
  reviewer_field          text        not null default '',   -- e.g. "Machine Learning", "Backend Engineering"

  -- Assignment lifecycle
  status                  text        not null default 'pending'
                                        check (status in (
                                          'pending',
                                          'accepted',
                                          'declined',
                                          'completed',
                                          'withdrawn'
                                        )),
  assigned_at             timestamptz not null default now(),
  completed_at            timestamptz,

  -- Review outcome (populated when status = completed)
  reviewer_notes          text        not null default '',
  reviewer_decision       text        check (reviewer_decision in (
                                        'approved',
                                        'rejected',
                                        'needs_revision',
                                        'escalate'
                                      )),
  verified_skills         jsonb       not null default '[]'::jsonb,
  requested_improvements  jsonb       not null default '[]'::jsonb,

  -- Timestamps
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

-- Idempotent column additions
alter table public.human_review_assignments
  add column if not exists reviewer_field         text not null default '',
  add column if not exists completed_at           timestamptz,
  add column if not exists reviewer_notes         text not null default '',
  add column if not exists reviewer_decision      text,
  add column if not exists verified_skills        jsonb not null default '[]'::jsonb,
  add column if not exists requested_improvements jsonb not null default '[]'::jsonb;

create index if not exists human_review_assignments_review_request_id_idx
  on public.human_review_assignments (review_request_id);

create index if not exists human_review_assignments_reviewer_id_idx
  on public.human_review_assignments (reviewer_id);

create index if not exists human_review_assignments_status_idx
  on public.human_review_assignments (status);

create index if not exists human_review_assignments_created_at_idx
  on public.human_review_assignments (created_at);

-- updated_at trigger
create or replace trigger set_human_review_assignments_updated_at
  before update on public.human_review_assignments
  for each row execute function public.set_updated_at();

-- Row-level security
alter table public.human_review_assignments enable row level security;

-- Only admin/service role can read all assignments; students cannot directly access
drop policy if exists "human_review_assignments: service role all"
  on public.human_review_assignments;
create policy "human_review_assignments: service role all"
  on public.human_review_assignments for all
  to service_role
  using (true)
  with check (true);
