-- ============================================================
-- VeriBridge AI — Migration 011: GitHub Recruiter Proof Reports
--
-- Phase G5 stores recruiter-friendly GitHub proof reports that
-- synthesize the claim, semantic verification result, capability
-- match metadata, and line-level supporting evidence.
-- ============================================================

create table if not exists public.github_recruiter_proof_reports (
  id                          uuid        primary key default gen_random_uuid(),
  evidence_id                 uuid        not null references public.skill_evidence (id) on delete cascade,
  github_semantic_result_id   uuid        not null references public.github_semantic_verification_results (id) on delete cascade,
  user_id                     uuid        not null references public.users (id) on delete cascade,
  report_status               text        not null
                                          check (report_status in (
                                            'verified',
                                            'partially_verified',
                                            'not_verified',
                                            'needs_human_review',
                                            'insufficient_evidence',
                                            'report_error'
                                          )),
  confidence_score            numeric(5,4)
                                          check (confidence_score is null or confidence_score between 0.0000 and 1.0000),
  report_version              text        not null default 'github-recruiter-proof-report-v1',
  student_claim               text,
  headline                    text,
  recruiter_summary           text,
  evidence_summary            text,
  limitations                 text,
  recommended_next_action     text,
  confirmed_capabilities      jsonb       not null default '[]'::jsonb,
  missing_capabilities        jsonb       not null default '[]'::jsonb,
  supporting_line_ranges      jsonb       not null default '[]'::jsonb,
  report_snapshot             jsonb       not null default '{}'::jsonb,
  created_at                  timestamptz not null default now(),
  updated_at                  timestamptz not null default now()
);

create index if not exists github_recruiter_proof_reports_evidence_idx
  on public.github_recruiter_proof_reports (evidence_id);

create index if not exists github_recruiter_proof_reports_semantic_result_idx
  on public.github_recruiter_proof_reports (github_semantic_result_id);

create index if not exists github_recruiter_proof_reports_user_idx
  on public.github_recruiter_proof_reports (user_id);

create index if not exists github_recruiter_proof_reports_status_idx
  on public.github_recruiter_proof_reports (report_status);

create index if not exists github_recruiter_proof_reports_created_idx
  on public.github_recruiter_proof_reports (created_at);

create or replace trigger set_github_recruiter_proof_reports_updated_at
  before update on public.github_recruiter_proof_reports
  for each row execute function public.set_updated_at();

alter table public.github_recruiter_proof_reports enable row level security;

create policy "github_recruiter_proof_reports: own row select"
  on public.github_recruiter_proof_reports for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "github_recruiter_proof_reports: own row insert"
  on public.github_recruiter_proof_reports for insert
  to authenticated
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1
      from public.skill_evidence se
      where se.id = evidence_id
        and se.user_id = (select auth.uid())
    )
    and exists (
      select 1
      from public.github_semantic_verification_results gsvr
      where gsvr.id = github_semantic_result_id
        and gsvr.evidence_id = evidence_id
        and gsvr.user_id = (select auth.uid())
    )
  );
