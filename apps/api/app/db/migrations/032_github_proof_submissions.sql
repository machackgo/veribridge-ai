-- VeriBridge AI - Migration 032: Standalone GitHub Proof Backend
--
-- Stores student-submitted GitHub proof items as first-class evidence records
-- so repositories can be analyzed independently from website proofs.

create table if not exists public.github_proof_submissions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users (id) on delete cascade,
  proof_session_id uuid references public.extension_proof_sessions (id) on delete cascade,
  repo_url text not null,
  repo_owner text,
  repo_name text,
  default_branch text,
  visibility text,
  status text not null default 'submitted'
    check (status in ('submitted', 'analyzing', 'analyzed', 'needs_more_evidence', 'failed', 'archived')),
  submitted_skill_claims jsonb not null default '[]'::jsonb,
  detected_skills jsonb not null default '[]'::jsonb,
  repo_metadata jsonb not null default '{}'::jsonb,
  analysis_summary text,
  evidence_strength text
    check (evidence_strength in ('strong', 'partial', 'weak', 'insufficient') or evidence_strength is null),
  confidence_score int check (confidence_score is null or (confidence_score >= 0 and confidence_score <= 100)),
  risk_flags jsonb not null default '[]'::jsonb,
  missing_evidence jsonb not null default '[]'::jsonb,
  public_safe_summary text,
  analysis_snapshot jsonb not null default '{}'::jsonb,
  last_analyzed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists github_proof_submissions_user_idx
  on public.github_proof_submissions (user_id);

create index if not exists github_proof_submissions_session_idx
  on public.github_proof_submissions (proof_session_id);

create index if not exists github_proof_submissions_repo_url_idx
  on public.github_proof_submissions (repo_url);

create index if not exists github_proof_submissions_status_idx
  on public.github_proof_submissions (status);

create index if not exists github_proof_submissions_created_at_idx
  on public.github_proof_submissions (created_at);

create index if not exists github_proof_submissions_last_analyzed_at_idx
  on public.github_proof_submissions (last_analyzed_at);

create or replace trigger set_github_proof_submissions_updated_at
  before update on public.github_proof_submissions
  for each row execute function public.set_updated_at();

alter table public.github_proof_submissions enable row level security;

drop policy if exists "github_proof_submissions: own select"
  on public.github_proof_submissions;
create policy "github_proof_submissions: own select"
  on public.github_proof_submissions for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "github_proof_submissions: own insert"
  on public.github_proof_submissions;
create policy "github_proof_submissions: own insert"
  on public.github_proof_submissions for insert
  to authenticated
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "github_proof_submissions: own update"
  on public.github_proof_submissions;
create policy "github_proof_submissions: own update"
  on public.github_proof_submissions for update
  to authenticated
  using (user_id::text = (select auth.uid())::text)
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "github_proof_submissions: service role all"
  on public.github_proof_submissions;
create policy "github_proof_submissions: service role all"
  on public.github_proof_submissions for all
  to service_role
  using (true)
  with check (true);
