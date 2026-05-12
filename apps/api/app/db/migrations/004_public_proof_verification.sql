-- ============================================================
-- VeriBridge AI — Migration 004: Public Proof Verification
--
-- Phase 3 stores structured verification attempts for public
-- proof evidence. Results are historical; the API reads the latest
-- row for a proof record when it needs current verifier output.
-- ============================================================

alter table public.skill_evidence
  add column if not exists proof_visibility text not null default 'public',
  add column if not exists metadata jsonb not null default '{}';

alter table public.skill_evidence
  drop constraint if exists skill_evidence_proof_visibility_check;

alter table public.skill_evidence
  add constraint skill_evidence_proof_visibility_check
  check (proof_visibility in ('public', 'private'));

create table if not exists public.skill_evidence_verifications (
  id                    uuid          primary key default gen_random_uuid(),
  user_id               uuid          not null references public.users (id) on delete cascade,
  skill_evidence_id     uuid          not null references public.skill_evidence (id) on delete cascade,
  verification_type     text          not null default 'public_metadata',
  verification_status   text          not null
                            check (verification_status in (
                              'pending',
                              'weak_match',
                              'plausible_match',
                              'strong_match',
                              'rejected'
                            )),
  confidence_score      numeric(5,4)  not null
                            check (confidence_score >= 0 and confidence_score <= 1),
  evidence_summary      text          not null,
  matched_signals       jsonb         not null default '[]',
  missing_signals       jsonb         not null default '[]',
  verifier_notes        text          not null default '',
  needs_human_review    boolean       not null default true,
  verifier_version      text          not null,
  input_snapshot        jsonb         not null default '{}',
  created_at            timestamptz   not null default now()
);

create index if not exists skill_evidence_verifications_evidence_created_idx
  on public.skill_evidence_verifications (skill_evidence_id, created_at desc);

create index if not exists skill_evidence_verifications_user_idx
  on public.skill_evidence_verifications (user_id);

create index if not exists skill_evidence_verifications_status_idx
  on public.skill_evidence_verifications (verification_status);

alter table public.skill_evidence_verifications enable row level security;

create policy "skill_evidence_verifications: own row select"
  on public.skill_evidence_verifications for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "skill_evidence_verifications: own row insert"
  on public.skill_evidence_verifications for insert
  to authenticated
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1
      from public.skill_evidence se
      where se.id = skill_evidence_id
        and se.user_id = (select auth.uid())
    )
  );
