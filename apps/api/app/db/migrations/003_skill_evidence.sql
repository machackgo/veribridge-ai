-- ============================================================
-- VeriBridge AI — Migration 003: Skill Proof Evidence
--
-- Phase 1 backend persistence for onboarding Step 3 proof evidence.
-- Upgrades the existing MVP skill_evidence table so it can store exact
-- proof locations and mock verification results without requiring a
-- linked normalized skill row yet.
-- ============================================================

alter table public.skill_evidence
  alter column skill_id drop not null;

alter table public.skill_evidence
  drop constraint if exists skill_evidence_evidence_type_check;

alter table public.skill_evidence
  add column if not exists skill_name text,
  add column if not exists evidence_url text,
  add column if not exists repository_url text,
  add column if not exists file_path text,
  add column if not exists line_start integer,
  add column if not exists line_end integer,
  add column if not exists evidence_description text,
  add column if not exists verification_status text not null default 'pending_review',
  add column if not exists verification_summary text,
  add column if not exists verifier_version text;

update public.skill_evidence se
set skill_name = coalesce(se.skill_name, s.name, se.source_label, 'Unknown skill')
from public.skills s
where se.skill_id = s.id
  and se.skill_name is null;

update public.skill_evidence
set skill_name = coalesce(skill_name, source_label, 'Unknown skill')
where skill_name is null;

alter table public.skill_evidence
  alter column skill_name set not null;

alter table public.skill_evidence
  drop constraint if exists skill_evidence_verification_status_check;

alter table public.skill_evidence
  add constraint skill_evidence_verification_status_check
  check (
    verification_status in (
      'pending_review',
      'verified',
      'skill_usage_not_found',
      'needs_review'
    )
  );

alter table public.skill_evidence
  drop constraint if exists skill_evidence_line_start_positive_check,
  drop constraint if exists skill_evidence_line_end_positive_check,
  drop constraint if exists skill_evidence_line_range_check;

alter table public.skill_evidence
  add constraint skill_evidence_line_start_positive_check
  check (line_start is null or line_start > 0),
  add constraint skill_evidence_line_end_positive_check
  check (line_end is null or line_end > 0),
  add constraint skill_evidence_line_range_check
  check (line_start is null or line_end is null or line_end >= line_start);

create index if not exists skill_evidence_skill_name_idx
  on public.skill_evidence (skill_name);

create index if not exists skill_evidence_user_id_idx
  on public.skill_evidence (user_id);

create index if not exists skill_evidence_verification_status_idx
  on public.skill_evidence (verification_status);
