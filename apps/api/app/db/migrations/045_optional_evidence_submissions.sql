-- VeriBridge AI - Migration 045: Optional Evidence Boosters
--
-- Reusable storage for document/report, LinkedIn/profile, and
-- certificate/transcript proof submitted as optional Work Passport boosters.

create table if not exists public.optional_evidence_submissions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users (id) on delete cascade,
  proof_session_id uuid references public.extension_proof_sessions (id) on delete cascade,
  source_type text not null
    check (source_type in ('document', 'linkedin_profile', 'certificate_transcript')),
  status text not null default 'not_added'
    check (status in ('not_added', 'processing', 'analyzed', 'failed', 'unsupported_file', 'needs_review', 'url_added', 'text_analyzed')),
  file_path text,
  profile_url text,
  raw_text text,
  analysis_json jsonb not null default '{}'::jsonb,
  evidence_objects jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists optional_evidence_user_idx
  on public.optional_evidence_submissions (user_id);

create index if not exists optional_evidence_session_idx
  on public.optional_evidence_submissions (proof_session_id);

create index if not exists optional_evidence_source_idx
  on public.optional_evidence_submissions (source_type);

create index if not exists optional_evidence_status_idx
  on public.optional_evidence_submissions (status);

create or replace trigger set_optional_evidence_submissions_updated_at
  before update on public.optional_evidence_submissions
  for each row execute function public.set_updated_at();

alter table public.optional_evidence_submissions enable row level security;

drop policy if exists "optional_evidence_submissions: own select"
  on public.optional_evidence_submissions;
create policy "optional_evidence_submissions: own select"
  on public.optional_evidence_submissions for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "optional_evidence_submissions: own insert"
  on public.optional_evidence_submissions;
create policy "optional_evidence_submissions: own insert"
  on public.optional_evidence_submissions for insert
  to authenticated
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "optional_evidence_submissions: own update"
  on public.optional_evidence_submissions;
create policy "optional_evidence_submissions: own update"
  on public.optional_evidence_submissions for update
  to authenticated
  using (user_id::text = (select auth.uid())::text)
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "optional_evidence_submissions: service role all"
  on public.optional_evidence_submissions;
create policy "optional_evidence_submissions: service role all"
  on public.optional_evidence_submissions for all
  to service_role
  using (true)
  with check (true);
