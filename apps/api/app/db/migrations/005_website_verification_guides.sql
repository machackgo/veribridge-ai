-- ============================================================
-- VeriBridge AI — Migration 005: Website Verification Guides
--
-- Phase 5A stores structured student-authored instructions for
-- future browser-agent verification of deployed website proof.
-- One current guide is stored per skill_evidence record.
-- ============================================================

create table if not exists public.website_verification_guides (
  id                  uuid        primary key default gen_random_uuid(),
  user_id             uuid        not null references public.users (id) on delete cascade,
  skill_evidence_id   uuid        not null references public.skill_evidence (id) on delete cascade,
  project_overview    text,
  feature_to_verify   text        not null,
  verification_steps  jsonb       not null default '[]',
  sample_inputs       jsonb,
  expected_output     text        not null,
  login_required      boolean     not null default false,
  login_notes         text,
  access_notes        text,
  known_limitations   text,
  additional_notes    text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  constraint website_verification_guides_steps_array_check
    check (jsonb_typeof(verification_steps) = 'array' and jsonb_array_length(verification_steps) > 0),
  constraint website_verification_guides_feature_not_blank_check
    check (length(btrim(feature_to_verify)) > 0),
  constraint website_verification_guides_expected_not_blank_check
    check (length(btrim(expected_output)) > 0)
);

create unique index if not exists website_verification_guides_evidence_uidx
  on public.website_verification_guides (skill_evidence_id);

create index if not exists website_verification_guides_user_idx
  on public.website_verification_guides (user_id);

create or replace trigger set_website_verification_guides_updated_at
  before update on public.website_verification_guides
  for each row execute function public.set_updated_at();

alter table public.website_verification_guides enable row level security;

create policy "website_verification_guides: own row select"
  on public.website_verification_guides for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "website_verification_guides: own row insert"
  on public.website_verification_guides for insert
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

create policy "website_verification_guides: own row update"
  on public.website_verification_guides for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1
      from public.skill_evidence se
      where se.id = skill_evidence_id
        and se.user_id = (select auth.uid())
    )
  );
