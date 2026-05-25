-- VeriBridge AI - Migration 020: AI Domain Reviewer Agents
--
-- Trust boundary:
--   These rows represent AI Domain Reviewed output only. They do not mark a
--   proof session as human_verified or final verification complete.

create table if not exists public.ai_domain_reviewers (
  id uuid primary key default gen_random_uuid(),
  reviewer_name text not null unique,
  reviewer_role text not null,
  domain text not null unique,
  rubric_version text not null default '1.0.0',
  rubric_json jsonb not null default '{}'::jsonb,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists ai_domain_reviewers_domain_idx
  on public.ai_domain_reviewers (domain);

create index if not exists ai_domain_reviewers_is_active_idx
  on public.ai_domain_reviewers (is_active);

create or replace trigger set_ai_domain_reviewers_updated_at
  before update on public.ai_domain_reviewers
  for each row execute function public.set_updated_at();

alter table public.ai_domain_reviewers enable row level security;

drop policy if exists "ai_domain_reviewers: authenticated read"
  on public.ai_domain_reviewers;
create policy "ai_domain_reviewers: authenticated read"
  on public.ai_domain_reviewers for select
  to authenticated
  using (true);

drop policy if exists "ai_domain_reviewers: service role all"
  on public.ai_domain_reviewers;
create policy "ai_domain_reviewers: service role all"
  on public.ai_domain_reviewers for all
  to service_role
  using (true)
  with check (true);

create table if not exists public.ai_domain_review_results (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users (id) on delete cascade,
  proof_session_id uuid not null references public.extension_proof_sessions (id) on delete cascade,
  reviewer_name text not null,
  reviewer_role text not null,
  domain text not null,
  ai_domain_review_status text not null
    check (ai_domain_review_status in (
      'ai_domain_reviewed',
      'needs_more_evidence',
      'human_review_recommended',
      'privacy_blocked'
    )),
  domain_review_score integer not null check (domain_review_score between 0 and 100),
  confidence_level text not null check (confidence_level in ('high', 'medium', 'low')),
  verified_skills jsonb not null default '[]'::jsonb,
  partially_verified_skills jsonb not null default '[]'::jsonb,
  skills_needing_more_evidence jsonb not null default '[]'::jsonb,
  domain_specific_strengths jsonb not null default '[]'::jsonb,
  domain_specific_concerns jsonb not null default '[]'::jsonb,
  criterion_scores jsonb not null default '[]'::jsonb,
  evidence_sources_reviewed jsonb not null default '[]'::jsonb,
  human_review_recommended boolean not null default false,
  human_review_reason text,
  recruiter_summary text not null default '',
  student_next_steps jsonb not null default '[]'::jsonb,
  review_limitations text not null default '',
  disclosure_note text not null default
    'This proof has been AI-reviewed using a field-specific rubric by a VeriBridge AI Domain Reviewer. Human/faculty/company review has not been completed unless explicitly shown.',
  llm_used boolean not null default false,
  fallback_reason text,
  human_ai_agreement_score numeric(4,3),
  calibration_status text,
  reviewed_against_human_baseline boolean,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.ai_domain_review_results
  add column if not exists reviewer_role text not null default '',
  add column if not exists domain text not null default '',
  add column if not exists ai_domain_review_status text not null default 'needs_more_evidence',
  add column if not exists domain_review_score integer not null default 0,
  add column if not exists confidence_level text not null default 'low',
  add column if not exists verified_skills jsonb not null default '[]'::jsonb,
  add column if not exists partially_verified_skills jsonb not null default '[]'::jsonb,
  add column if not exists skills_needing_more_evidence jsonb not null default '[]'::jsonb,
  add column if not exists domain_specific_strengths jsonb not null default '[]'::jsonb,
  add column if not exists domain_specific_concerns jsonb not null default '[]'::jsonb,
  add column if not exists criterion_scores jsonb not null default '[]'::jsonb,
  add column if not exists evidence_sources_reviewed jsonb not null default '[]'::jsonb,
  add column if not exists human_review_recommended boolean not null default false,
  add column if not exists human_review_reason text,
  add column if not exists recruiter_summary text not null default '',
  add column if not exists student_next_steps jsonb not null default '[]'::jsonb,
  add column if not exists review_limitations text not null default '',
  add column if not exists disclosure_note text not null default
    'This proof has been AI-reviewed using a field-specific rubric by a VeriBridge AI Domain Reviewer. Human/faculty/company review has not been completed unless explicitly shown.',
  add column if not exists llm_used boolean not null default false,
  add column if not exists fallback_reason text,
  add column if not exists human_ai_agreement_score numeric(4,3),
  add column if not exists calibration_status text,
  add column if not exists reviewed_against_human_baseline boolean,
  add column if not exists updated_at timestamptz not null default now();

create unique index if not exists ai_domain_review_results_session_idx
  on public.ai_domain_review_results (proof_session_id);

create index if not exists ai_domain_review_results_user_id_idx
  on public.ai_domain_review_results (user_id);

create index if not exists ai_domain_review_results_status_idx
  on public.ai_domain_review_results (ai_domain_review_status);

create index if not exists ai_domain_review_results_domain_idx
  on public.ai_domain_review_results (domain);

create or replace trigger set_ai_domain_review_results_updated_at
  before update on public.ai_domain_review_results
  for each row execute function public.set_updated_at();

alter table public.ai_domain_review_results enable row level security;

drop policy if exists "ai_domain_review_results: own row select"
  on public.ai_domain_review_results;
create policy "ai_domain_review_results: own row select"
  on public.ai_domain_review_results for select
  to authenticated
  using (user_id::text = (select auth.uid())::text);

drop policy if exists "ai_domain_review_results: service role all"
  on public.ai_domain_review_results;
create policy "ai_domain_review_results: service role all"
  on public.ai_domain_review_results for all
  to service_role
  using (true)
  with check (true);

insert into public.ai_domain_reviewers
  (reviewer_name, reviewer_role, domain, rubric_version, rubric_json, is_active)
values
  ('Astra', 'CS / AI / Data Science AI Reviewer', 'cs_ai', '1.0.0', '{}'::jsonb, true),
  ('Atlas', 'Civil / Mechanical Engineering AI Reviewer', 'civil_mech_eng', '1.0.0', '{}'::jsonb, true),
  ('Nova', 'Business / Finance / Analytics AI Reviewer', 'business_finance', '1.0.0', '{}'::jsonb, true),
  ('Sage', 'Research / Academic AI Reviewer', 'research', '1.0.0', '{}'::jsonb, true),
  ('General', 'General AI Domain Reviewer', 'general', '1.0.0', '{}'::jsonb, true)
on conflict (domain) do update set
  reviewer_name = excluded.reviewer_name,
  reviewer_role = excluded.reviewer_role,
  rubric_version = excluded.rubric_version,
  is_active = true,
  updated_at = now();
