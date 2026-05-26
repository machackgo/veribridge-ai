-- VeriBridge AI - Migration 023: Recruiter / Organization Identity Backend
--
-- Stores requester identity profiles for recruiters, faculty, mentors,
-- company reviewers, and domain experts who request access to protected
-- Public Work Passport evidence.

create table if not exists public.recruiter_requester_profiles (
  id uuid primary key default gen_random_uuid(),
  email text unique not null,
  full_name text,
  organization_name text,
  organization_domain text,
  requester_role text,
  requester_type text not null default 'recruiter'
    check (
      requester_type in (
        'recruiter',
        'hiring_manager',
        'faculty',
        'mentor',
        'company_reviewer',
        'domain_expert',
        'other'
      )
    ),
  email_verified boolean not null default false,
  domain_verified boolean not null default false,
  verification_status text not null default 'unverified'
    check (
      verification_status in (
        'unverified',
        'email_pending',
        'email_verified',
        'domain_verified',
        'trusted',
        'suspicious',
        'blocked'
      )
    ),
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  total_access_requests int not null default 0,
  approved_access_requests int not null default 0,
  denied_access_requests int not null default 0,
  risk_score int not null default 0,
  risk_flags jsonb not null default '[]'::jsonb,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists recruiter_requester_profiles_email_idx
  on public.recruiter_requester_profiles (email);

create index if not exists recruiter_requester_profiles_domain_idx
  on public.recruiter_requester_profiles (organization_domain);

create index if not exists recruiter_requester_profiles_verification_status_idx
  on public.recruiter_requester_profiles (verification_status);

create index if not exists recruiter_requester_profiles_last_seen_idx
  on public.recruiter_requester_profiles (last_seen_at);

create or replace trigger set_recruiter_requester_profiles_updated_at
  before update on public.recruiter_requester_profiles
  for each row execute function public.set_updated_at();

alter table public.recruiter_requester_profiles enable row level security;

drop policy if exists "recruiter_requester_profiles: service role all"
  on public.recruiter_requester_profiles;
create policy "recruiter_requester_profiles: service role all"
  on public.recruiter_requester_profiles for all
  to service_role
  using (true)
  with check (true);

alter table public.evidence_access_requests
  add column if not exists requester_profile_id uuid
  references public.recruiter_requester_profiles (id);

create index if not exists evidence_access_requests_requester_profile_idx
  on public.evidence_access_requests (requester_profile_id);
