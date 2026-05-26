-- VeriBridge AI - Migration 025: Proof Evidence Versioning / Resubmission
--
-- Preserves proof package snapshots across student resubmissions while keeping
-- a single active version per proof session.

create table if not exists public.proof_evidence_versions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users (id) on delete cascade,
  proof_session_id uuid not null references public.extension_proof_sessions (id) on delete cascade,
  version_number int not null,
  version_label text,
  status text not null default 'draft'
    check (
      status in (
        'draft',
        'submitted',
        'analyzed',
        'needs_more_evidence',
        'ai_domain_reviewed',
        'approved_for_sharing',
        'archived'
      )
    ),
  change_summary text,
  resubmission_reason text,
  evidence_snapshot jsonb not null default '{}'::jsonb,
  analysis_snapshot jsonb not null default '{}'::jsonb,
  readiness_score int,
  ai_domain_review_score int,
  project_defense_score int,
  privacy_status text,
  created_from_version_id uuid references public.proof_evidence_versions (id) on delete set null,
  is_active boolean not null default false,
  submitted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (proof_session_id, version_number)
);

create unique index if not exists proof_evidence_versions_one_active_per_session_idx
  on public.proof_evidence_versions (proof_session_id)
  where is_active = true;

create index if not exists proof_evidence_versions_user_id_idx
  on public.proof_evidence_versions (user_id);

create index if not exists proof_evidence_versions_session_idx
  on public.proof_evidence_versions (proof_session_id);

create index if not exists proof_evidence_versions_status_idx
  on public.proof_evidence_versions (status);

create index if not exists proof_evidence_versions_created_at_idx
  on public.proof_evidence_versions (created_at);

create or replace trigger set_proof_evidence_versions_updated_at
  before update on public.proof_evidence_versions
  for each row execute function public.set_updated_at();

alter table public.proof_evidence_versions enable row level security;

drop policy if exists "proof_evidence_versions: own row select"
  on public.proof_evidence_versions;
create policy "proof_evidence_versions: own row select"
  on public.proof_evidence_versions for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "proof_evidence_versions: own row insert"
  on public.proof_evidence_versions;
create policy "proof_evidence_versions: own row insert"
  on public.proof_evidence_versions for insert
  to authenticated
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "proof_evidence_versions: own row update"
  on public.proof_evidence_versions;
create policy "proof_evidence_versions: own row update"
  on public.proof_evidence_versions for update
  to authenticated
  using (user_id::text = (select auth.uid())::text)
  with check (user_id::text = (select auth.uid())::text);

drop policy if exists "proof_evidence_versions: service role all"
  on public.proof_evidence_versions;
create policy "proof_evidence_versions: service role all"
  on public.proof_evidence_versions for all
  to service_role
  using (true)
  with check (true);
