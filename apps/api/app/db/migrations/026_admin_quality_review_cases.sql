-- VeriBridge AI - Migration 026: Admin Quality Review / Moderation Backend
--
-- Internal VeriBridge quality/moderation cases for privacy, evidence risk,
-- recruiter risk, access abuse, and other operational review signals.

create table if not exists public.admin_quality_review_cases (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.users (id) on delete cascade,
  proof_session_id uuid references public.extension_proof_sessions (id) on delete cascade,
  passport_id uuid references public.public_work_passports (id) on delete set null,
  access_request_id uuid references public.evidence_access_requests (id) on delete set null,
  requester_profile_id uuid references public.recruiter_requester_profiles (id) on delete set null,
  case_type text not null
    check (
      case_type in (
        'privacy_flag',
        'suspicious_evidence',
        'low_confidence_ai_review',
        'recruiter_risk',
        'access_abuse',
        'student_report',
        'system_flag',
        'manual_review',
        'other'
      )
    ),
  status text not null default 'open'
    check (
      status in (
        'open',
        'under_review',
        'needs_student_action',
        'resolved',
        'dismissed',
        'escalated'
      )
    ),
  priority text not null default 'normal'
    check (priority in ('low', 'normal', 'high', 'urgent')),
  risk_score int not null default 0,
  risk_flags jsonb not null default '[]'::jsonb,
  source text not null default 'system',
  title text,
  summary text,
  assigned_admin_id uuid references public.users (id) on delete set null,
  admin_notes text,
  decision text
    check (
      decision is null or decision in (
        'safe_for_sharing',
        'needs_more_evidence',
        'privacy_blocked',
        'suspicious',
        'dismissed',
        'escalated_to_human_review',
        'no_action_needed'
      )
    ),
  decision_reason text,
  requested_student_actions jsonb not null default '[]'::jsonb,
  resolved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists admin_quality_review_cases_user_id_idx
  on public.admin_quality_review_cases (user_id);

create index if not exists admin_quality_review_cases_session_idx
  on public.admin_quality_review_cases (proof_session_id);

create index if not exists admin_quality_review_cases_status_idx
  on public.admin_quality_review_cases (status);

create index if not exists admin_quality_review_cases_type_idx
  on public.admin_quality_review_cases (case_type);

create index if not exists admin_quality_review_cases_priority_idx
  on public.admin_quality_review_cases (priority);

create index if not exists admin_quality_review_cases_requester_idx
  on public.admin_quality_review_cases (requester_profile_id);

create unique index if not exists admin_quality_review_open_case_signal_idx
  on public.admin_quality_review_cases (
    proof_session_id,
    case_type,
    coalesce(requester_profile_id, '00000000-0000-0000-0000-000000000000'::uuid),
    coalesce(access_request_id, '00000000-0000-0000-0000-000000000000'::uuid)
  )
  where status in ('open', 'under_review', 'needs_student_action', 'escalated');

create or replace trigger set_admin_quality_review_cases_updated_at
  before update on public.admin_quality_review_cases
  for each row execute function public.set_updated_at();

alter table public.admin_quality_review_cases enable row level security;

drop policy if exists "admin_quality_review_cases: service role all"
  on public.admin_quality_review_cases;
create policy "admin_quality_review_cases: service role all"
  on public.admin_quality_review_cases for all
  to service_role
  using (true)
  with check (true);

create table if not exists public.admin_quality_review_events (
  id uuid primary key default gen_random_uuid(),
  case_id uuid references public.admin_quality_review_cases (id) on delete cascade,
  event_type text not null
    check (
      event_type in (
        'case_created',
        'case_assigned',
        'case_status_changed',
        'admin_note_added',
        'decision_recorded',
        'student_action_requested',
        'case_resolved',
        'case_dismissed',
        'case_escalated'
      )
    ),
  actor_user_id uuid references public.users (id) on delete set null,
  actor_type text not null default 'system',
  event_summary text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists admin_quality_review_events_case_idx
  on public.admin_quality_review_events (case_id);

create index if not exists admin_quality_review_events_type_idx
  on public.admin_quality_review_events (event_type);

create index if not exists admin_quality_review_events_created_at_idx
  on public.admin_quality_review_events (created_at);

alter table public.admin_quality_review_events enable row level security;

drop policy if exists "admin_quality_review_events: service role all"
  on public.admin_quality_review_events;
create policy "admin_quality_review_events: service role all"
  on public.admin_quality_review_events for all
  to service_role
  using (true)
  with check (true);
