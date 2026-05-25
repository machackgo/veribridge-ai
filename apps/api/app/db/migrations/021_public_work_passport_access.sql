-- VeriBridge AI - Migration 021: Public Work Passport + Recruiter Access
--
-- Public passports expose only safe summary metadata. Private media,
-- transcripts, hidden files, and sensitive evidence remain behind explicit
-- access grants created from approved access requests.

create table if not exists public.public_work_passports (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users (id) on delete cascade,
  proof_session_id uuid not null references public.extension_proof_sessions (id) on delete cascade,
  public_slug text unique not null,
  is_public boolean not null default true,
  public_title text,
  public_summary text,
  field text,
  visible_sections jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists public_work_passports_session_uidx
  on public.public_work_passports (proof_session_id);

create index if not exists public_work_passports_user_id_idx
  on public.public_work_passports (user_id);

create index if not exists public_work_passports_public_slug_idx
  on public.public_work_passports (public_slug);

create index if not exists public_work_passports_is_public_idx
  on public.public_work_passports (is_public);

create or replace trigger set_public_work_passports_updated_at
  before update on public.public_work_passports
  for each row execute function public.set_updated_at();

alter table public.public_work_passports enable row level security;

drop policy if exists "public_work_passports: own row select"
  on public.public_work_passports;
create policy "public_work_passports: own row select"
  on public.public_work_passports for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "public_work_passports: own row insert"
  on public.public_work_passports;
create policy "public_work_passports: own row insert"
  on public.public_work_passports for insert
  to authenticated
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "public_work_passports: own row update"
  on public.public_work_passports;
create policy "public_work_passports: own row update"
  on public.public_work_passports for update
  to authenticated
  using (user_id::text = (select auth.uid())::text)
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "public_work_passports: anon public read"
  on public.public_work_passports;
create policy "public_work_passports: anon public read"
  on public.public_work_passports for select
  to anon, authenticated
  using (is_public = true);

drop policy if exists "public_work_passports: service role all"
  on public.public_work_passports;
create policy "public_work_passports: service role all"
  on public.public_work_passports for all
  to service_role
  using (true)
  with check (true);

create table if not exists public.evidence_access_requests (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users (id) on delete cascade,
  proof_session_id uuid not null references public.extension_proof_sessions (id) on delete cascade,
  passport_id uuid not null references public.public_work_passports (id) on delete cascade,
  requester_name text not null,
  requester_email text not null,
  requester_organization text,
  requester_role text,
  request_reason text,
  status text not null default 'pending'
    check (status in ('pending', 'approved', 'denied', 'revoked')),
  requested_sections jsonb not null default '[]'::jsonb,
  decision_notes text,
  decided_at timestamptz,
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists evidence_access_requests_user_id_idx
  on public.evidence_access_requests (user_id);

create index if not exists evidence_access_requests_session_idx
  on public.evidence_access_requests (proof_session_id);

create index if not exists evidence_access_requests_passport_idx
  on public.evidence_access_requests (passport_id);

create index if not exists evidence_access_requests_status_idx
  on public.evidence_access_requests (status);

create index if not exists evidence_access_requests_email_idx
  on public.evidence_access_requests (requester_email);

create or replace trigger set_evidence_access_requests_updated_at
  before update on public.evidence_access_requests
  for each row execute function public.set_updated_at();

alter table public.evidence_access_requests enable row level security;

drop policy if exists "evidence_access_requests: own row select"
  on public.evidence_access_requests;
create policy "evidence_access_requests: own row select"
  on public.evidence_access_requests for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "evidence_access_requests: own row update"
  on public.evidence_access_requests;
create policy "evidence_access_requests: own row update"
  on public.evidence_access_requests for update
  to authenticated
  using (user_id::text = (select auth.uid())::text)
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "evidence_access_requests: service role all"
  on public.evidence_access_requests;
create policy "evidence_access_requests: service role all"
  on public.evidence_access_requests for all
  to service_role
  using (true)
  with check (true);

create table if not exists public.evidence_access_grants (
  id uuid primary key default gen_random_uuid(),
  access_request_id uuid not null references public.evidence_access_requests (id) on delete cascade,
  user_id uuid not null references public.users (id) on delete cascade,
  proof_session_id uuid not null references public.extension_proof_sessions (id) on delete cascade,
  requester_email text not null,
  granted_sections jsonb not null default '[]'::jsonb,
  access_token text unique not null,
  expires_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists evidence_access_grants_request_idx
  on public.evidence_access_grants (access_request_id);

create index if not exists evidence_access_grants_user_id_idx
  on public.evidence_access_grants (user_id);

create index if not exists evidence_access_grants_session_idx
  on public.evidence_access_grants (proof_session_id);

create index if not exists evidence_access_grants_token_idx
  on public.evidence_access_grants (access_token);

create index if not exists evidence_access_grants_email_idx
  on public.evidence_access_grants (requester_email);

create or replace trigger set_evidence_access_grants_updated_at
  before update on public.evidence_access_grants
  for each row execute function public.set_updated_at();

alter table public.evidence_access_grants enable row level security;

drop policy if exists "evidence_access_grants: own row select"
  on public.evidence_access_grants;
create policy "evidence_access_grants: own row select"
  on public.evidence_access_grants for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "evidence_access_grants: own row update"
  on public.evidence_access_grants;
create policy "evidence_access_grants: own row update"
  on public.evidence_access_grants for update
  to authenticated
  using (user_id::text = (select auth.uid())::text)
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "evidence_access_grants: service role all"
  on public.evidence_access_grants;
create policy "evidence_access_grants: service role all"
  on public.evidence_access_grants for all
  to service_role
  using (true)
  with check (true);
