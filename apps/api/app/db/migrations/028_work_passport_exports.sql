-- VeriBridge AI - Migration 028: Work Passport Export Backend
--
-- Stores generated JSON export payloads for student, public, protected recruiter,
-- and admin export workflows. The MVP uses structured JSON payloads only.

create table if not exists public.work_passport_exports (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.users (id) on delete cascade,
  proof_session_id uuid references public.extension_proof_sessions (id) on delete cascade,
  passport_id uuid references public.public_work_passports (id) on delete set null,
  access_grant_id uuid references public.evidence_access_grants (id) on delete set null,
  export_type text not null default 'student'
    check (export_type in ('student', 'public', 'protected_recruiter', 'admin')),
  export_format text not null default 'json'
    check (export_format in ('json', 'pdf_future', 'html_future')),
  status text not null default 'generated'
    check (status in ('generated', 'failed', 'expired', 'revoked')),
  public_slug text,
  access_token_hash text,
  export_payload jsonb not null default '{}'::jsonb,
  file_storage_path text,
  generated_by_type text not null default 'student'
    check (generated_by_type in ('student', 'public', 'recruiter', 'admin')),
  generated_by_email text,
  created_at timestamptz not null default now(),
  expires_at timestamptz
);

create index if not exists work_passport_exports_user_idx
  on public.work_passport_exports (user_id);

create index if not exists work_passport_exports_session_idx
  on public.work_passport_exports (proof_session_id);

create index if not exists work_passport_exports_passport_idx
  on public.work_passport_exports (passport_id);

create index if not exists work_passport_exports_grant_idx
  on public.work_passport_exports (access_grant_id);

create index if not exists work_passport_exports_type_idx
  on public.work_passport_exports (export_type);

create index if not exists work_passport_exports_status_idx
  on public.work_passport_exports (status);

create index if not exists work_passport_exports_created_at_idx
  on public.work_passport_exports (created_at);

create index if not exists work_passport_exports_public_slug_idx
  on public.work_passport_exports (public_slug);

create index if not exists work_passport_exports_access_token_hash_idx
  on public.work_passport_exports (access_token_hash);

alter table public.work_passport_exports enable row level security;

drop policy if exists "work_passport_exports: own row select"
  on public.work_passport_exports;
create policy "work_passport_exports: own row select"
  on public.work_passport_exports for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "work_passport_exports: service role all"
  on public.work_passport_exports;
create policy "work_passport_exports: service role all"
  on public.work_passport_exports for all
  to service_role
  using (true)
  with check (true);
