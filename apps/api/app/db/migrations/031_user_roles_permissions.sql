-- VeriBridge AI - Migration 031: Role-Based Access Control / Admin Permission Backend
--
-- Stores backend-managed role assignments and permission audit events so the
-- API can distinguish student, recruiter, admin, reviewer, and future reviewer
-- scopes safely without frontend hardcoding.

create table if not exists public.user_roles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users (id) on delete cascade,
  role text not null
    check (role in ('student', 'recruiter', 'admin', 'reviewer', 'faculty_reviewer', 'company_reviewer', 'support')),
  scope text not null default 'global'
    check (scope in ('global', 'organization', 'proof_session', 'passport', 'quality_case')),
  scope_id uuid,
  granted_by uuid references public.users (id) on delete set null,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  revoked_at timestamptz,
  metadata jsonb not null default '{}'::jsonb
);

create unique index if not exists user_roles_active_unique_idx
  on public.user_roles (
    user_id,
    role,
    scope,
    coalesce(scope_id, '00000000-0000-0000-0000-000000000000'::uuid)
  )
  where is_active;

create index if not exists user_roles_user_id_idx
  on public.user_roles (user_id);

create index if not exists user_roles_role_idx
  on public.user_roles (role);

create index if not exists user_roles_scope_idx
  on public.user_roles (scope);

create index if not exists user_roles_is_active_idx
  on public.user_roles (is_active);

alter table public.user_roles enable row level security;

drop policy if exists "user_roles: own active select"
  on public.user_roles;
create policy "user_roles: own active select"
  on public.user_roles for select
  to authenticated
  using (is_active and user_id::text = (select auth.uid())::text);

drop policy if exists "user_roles: service role all"
  on public.user_roles;
create policy "user_roles: service role all"
  on public.user_roles for all
  to service_role
  using (true)
  with check (true);

create table if not exists public.role_permission_audit_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.users (id) on delete cascade,
  target_user_id uuid references public.users (id) on delete cascade,
  event_type text not null,
  role text,
  scope text,
  scope_id uuid,
  actor_user_id uuid references public.users (id) on delete set null,
  event_summary text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists role_permission_audit_events_user_id_idx
  on public.role_permission_audit_events (user_id);

create index if not exists role_permission_audit_events_target_user_id_idx
  on public.role_permission_audit_events (target_user_id);

create index if not exists role_permission_audit_events_event_type_idx
  on public.role_permission_audit_events (event_type);

create index if not exists role_permission_audit_events_created_at_idx
  on public.role_permission_audit_events (created_at);

alter table public.role_permission_audit_events enable row level security;

drop policy if exists "role_permission_audit_events: service role all"
  on public.role_permission_audit_events;
create policy "role_permission_audit_events: service role all"
  on public.role_permission_audit_events for all
  to service_role
  using (true)
  with check (true);

