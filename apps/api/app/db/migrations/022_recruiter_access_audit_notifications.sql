-- VeriBridge AI - Migration 022: Recruiter Access Audit + Notification Backend
--
-- Adds audit history, notification placeholders, and public passport view
-- analytics for Public Work Passport recruiter access flows. Notification rows
-- are queued only; no email is sent by this migration or backend stage.

create table if not exists public.evidence_access_audit_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.users (id) on delete cascade,
  proof_session_id uuid references public.extension_proof_sessions (id) on delete cascade,
  passport_id uuid references public.public_work_passports (id) on delete cascade,
  access_request_id uuid references public.evidence_access_requests (id) on delete set null,
  access_grant_id uuid references public.evidence_access_grants (id) on delete set null,
  event_type text not null check (
    event_type in (
      'passport_created',
      'access_requested',
      'access_approved',
      'access_denied',
      'access_granted',
      'access_revoked',
      'protected_evidence_viewed',
      'access_expired',
      'suspicious_request_flagged'
    )
  ),
  actor_type text not null,
  actor_email text,
  actor_user_id uuid references public.users (id),
  event_summary text,
  metadata jsonb default '{}'::jsonb,
  created_at timestamptz default now()
);

create index if not exists evidence_access_audit_events_user_id_idx
  on public.evidence_access_audit_events (user_id);

create index if not exists evidence_access_audit_events_session_idx
  on public.evidence_access_audit_events (proof_session_id);

create index if not exists evidence_access_audit_events_passport_idx
  on public.evidence_access_audit_events (passport_id);

create index if not exists evidence_access_audit_events_request_idx
  on public.evidence_access_audit_events (access_request_id);

create index if not exists evidence_access_audit_events_grant_idx
  on public.evidence_access_audit_events (access_grant_id);

create index if not exists evidence_access_audit_events_type_idx
  on public.evidence_access_audit_events (event_type);

alter table public.evidence_access_audit_events enable row level security;

drop policy if exists "evidence_access_audit_events: own row select"
  on public.evidence_access_audit_events;
create policy "evidence_access_audit_events: own row select"
  on public.evidence_access_audit_events for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "evidence_access_audit_events: service role all"
  on public.evidence_access_audit_events;
create policy "evidence_access_audit_events: service role all"
  on public.evidence_access_audit_events for all
  to service_role
  using (true)
  with check (true);

create table if not exists public.notification_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.users (id) on delete cascade,
  event_type text not null,
  channel text not null default 'email',
  recipient_email text not null,
  subject text,
  body text,
  status text not null default 'pending',
  metadata jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  sent_at timestamptz,
  failure_reason text
);

create index if not exists notification_events_user_id_idx
  on public.notification_events (user_id);

create index if not exists notification_events_event_type_idx
  on public.notification_events (event_type);

create index if not exists notification_events_status_idx
  on public.notification_events (status);

create index if not exists notification_events_recipient_email_idx
  on public.notification_events (recipient_email);

alter table public.notification_events enable row level security;

drop policy if exists "notification_events: own row select"
  on public.notification_events;
create policy "notification_events: own row select"
  on public.notification_events for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "notification_events: service role all"
  on public.notification_events;
create policy "notification_events: service role all"
  on public.notification_events for all
  to service_role
  using (true)
  with check (true);

create table if not exists public.public_passport_view_events (
  id uuid primary key default gen_random_uuid(),
  passport_id uuid references public.public_work_passports (id) on delete cascade,
  public_slug text not null,
  viewer_type text default 'anonymous',
  viewer_email text,
  viewer_organization text,
  ip_hash text,
  user_agent_hash text,
  viewed_sections jsonb default '[]'::jsonb,
  created_at timestamptz default now()
);

create index if not exists public_passport_view_events_passport_idx
  on public.public_passport_view_events (passport_id);

create index if not exists public_passport_view_events_public_slug_idx
  on public.public_passport_view_events (public_slug);

create index if not exists public_passport_view_events_created_at_idx
  on public.public_passport_view_events (created_at);

alter table public.public_passport_view_events enable row level security;

drop policy if exists "public_passport_view_events: passport owner select"
  on public.public_passport_view_events;
create policy "public_passport_view_events: passport owner select"
  on public.public_passport_view_events for select
  to authenticated
  using (
    exists (
      select 1
      from public.public_work_passports p
      where p.id = public_passport_view_events.passport_id
        and p.user_id::text = (select auth.uid())::text
    )
  );

drop policy if exists "public_passport_view_events: service role all"
  on public.public_passport_view_events;
create policy "public_passport_view_events: service role all"
  on public.public_passport_view_events for all
  to service_role
  using (true)
  with check (true);
