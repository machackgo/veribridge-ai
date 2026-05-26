-- VeriBridge AI - Migration 030: Recruiter Candidate Comparison Backend
--
-- Stores recruiter-side private comparison snapshots for saved Work Passports.
-- These rows are backend-managed only and are not publicly selectable.

create table if not exists public.recruiter_candidate_comparisons (
  id uuid primary key default gen_random_uuid(),
  requester_profile_id uuid references public.recruiter_requester_profiles (id) on delete cascade,
  requester_email text not null,
  comparison_name text,
  role_title text,
  role_requirements jsonb not null default '{}'::jsonb,
  candidate_passport_ids jsonb not null default '[]'::jsonb,
  comparison_snapshot jsonb not null default '{}'::jsonb,
  status text not null default 'draft'
    check (status in ('draft', 'generated', 'archived')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists recruiter_candidate_comparisons_requester_profile_idx
  on public.recruiter_candidate_comparisons (requester_profile_id);

create index if not exists recruiter_candidate_comparisons_requester_email_idx
  on public.recruiter_candidate_comparisons (requester_email);

create index if not exists recruiter_candidate_comparisons_status_idx
  on public.recruiter_candidate_comparisons (status);

create index if not exists recruiter_candidate_comparisons_created_at_idx
  on public.recruiter_candidate_comparisons (created_at);

create or replace trigger set_recruiter_candidate_comparisons_updated_at
  before update on public.recruiter_candidate_comparisons
  for each row execute function public.set_updated_at();

alter table public.recruiter_candidate_comparisons enable row level security;

drop policy if exists "recruiter_candidate_comparisons: service role all"
  on public.recruiter_candidate_comparisons;
create policy "recruiter_candidate_comparisons: service role all"
  on public.recruiter_candidate_comparisons for all
  to service_role
  using (true)
  with check (true);

do $$
begin
  if exists (
    select 1
    from pg_constraint
    where conname = 'evidence_access_audit_events_event_type_check'
      and conrelid = 'public.evidence_access_audit_events'::regclass
  ) then
    alter table public.evidence_access_audit_events
      drop constraint evidence_access_audit_events_event_type_check;
  end if;

  alter table public.evidence_access_audit_events
    add constraint evidence_access_audit_events_event_type_check
    check (
      event_type in (
        'passport_created',
        'access_requested',
        'access_approved',
        'access_denied',
        'access_granted',
        'access_revoked',
        'protected_evidence_viewed',
        'access_expired',
        'suspicious_request_flagged',
        'passport_saved',
        'candidate_shortlisted',
        'recruiter_note_updated',
        'saved_passport_archived',
        'candidate_comparison_created',
        'candidate_comparison_viewed',
        'candidate_comparison_archived'
      )
    );
end $$;

