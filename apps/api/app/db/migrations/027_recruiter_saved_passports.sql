-- VeriBridge AI - Migration 027: Recruiter Saved Passports / Shortlist Backend
--
-- Stores recruiter/requester private workflow metadata for saved and
-- shortlisted public Work Passports. These rows are recruiter-side only and
-- are not exposed to students through student routes.

create table if not exists public.recruiter_saved_passports (
  id uuid primary key default gen_random_uuid(),
  requester_profile_id uuid references public.recruiter_requester_profiles (id) on delete cascade,
  passport_id uuid references public.public_work_passports (id) on delete cascade,
  proof_session_id uuid references public.extension_proof_sessions (id) on delete cascade,
  student_user_id uuid references public.users (id) on delete cascade,
  requester_email text not null,
  organization_name text,
  status text not null default 'saved'
    check (status in ('saved', 'shortlisted', 'reviewing', 'contacted', 'rejected', 'archived')),
  tags jsonb not null default '[]'::jsonb,
  private_notes text,
  reviewed_sections jsonb not null default '[]'::jsonb,
  fit_score int check (fit_score is null or (fit_score >= 0 and fit_score <= 100)),
  fit_reason text,
  last_viewed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (requester_profile_id, passport_id)
);

create index if not exists recruiter_saved_passports_requester_idx
  on public.recruiter_saved_passports (requester_profile_id);

create index if not exists recruiter_saved_passports_passport_idx
  on public.recruiter_saved_passports (passport_id);

create index if not exists recruiter_saved_passports_session_idx
  on public.recruiter_saved_passports (proof_session_id);

create index if not exists recruiter_saved_passports_student_idx
  on public.recruiter_saved_passports (student_user_id);

create index if not exists recruiter_saved_passports_email_idx
  on public.recruiter_saved_passports (requester_email);

create index if not exists recruiter_saved_passports_status_idx
  on public.recruiter_saved_passports (status);

create index if not exists recruiter_saved_passports_last_viewed_idx
  on public.recruiter_saved_passports (last_viewed_at);

create or replace trigger set_recruiter_saved_passports_updated_at
  before update on public.recruiter_saved_passports
  for each row execute function public.set_updated_at();

alter table public.recruiter_saved_passports enable row level security;

drop policy if exists "recruiter_saved_passports: service role all"
  on public.recruiter_saved_passports;
create policy "recruiter_saved_passports: service role all"
  on public.recruiter_saved_passports for all
  to service_role
  using (true)
  with check (true);

-- Extend audit event types for recruiter saved-candidate workflow.
alter table public.evidence_access_audit_events
  drop constraint if exists evidence_access_audit_events_event_type_check;

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
      'saved_passport_archived'
    )
  );
