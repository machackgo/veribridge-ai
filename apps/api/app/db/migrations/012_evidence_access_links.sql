-- ============================================================
-- VeriBridge AI — Migration 012: Evidence Access Links
--
-- Phase H1 stores recruiter-safe access links that open the original
-- GitHub code lines or public website proof directly.
-- ============================================================

create table if not exists public.evidence_access_links (
  id                    uuid        primary key default gen_random_uuid(),
  evidence_id           uuid        not null references public.skill_evidence (id) on delete cascade,
  user_id               uuid        not null references public.users (id) on delete cascade,
  source_report_type    text        not null
                                        check (source_report_type in (
                                          'github_recruiter_proof_report',
                                          'website_semantic_verification_result',
                                          'direct_skill_evidence',
                                          'none'
                                        )),
  source_report_id      uuid,
  access_type           text        not null
                                        check (access_type in (
                                          'github_exact_lines',
                                          'live_website'
                                        )),
  label                 text        not null,
  url                   text        not null,
  source_type           text        not null
                                        check (source_type in (
                                          'github',
                                          'website'
                                        )),
  file_path             text,
  line_start            integer,
  line_end              integer,
  availability_status   text        not null
                                        check (availability_status in (
                                          'available',
                                          'unavailable',
                                          'invalid_source',
                                          'insufficient_data'
                                        )),
  notes                 text,
  access_snapshot       jsonb       not null default '{}'::jsonb,
  created_at            timestamptz  not null default now(),
  updated_at            timestamptz  not null default now()
);

create index if not exists evidence_access_links_evidence_idx
  on public.evidence_access_links (evidence_id);

create index if not exists evidence_access_links_user_idx
  on public.evidence_access_links (user_id);

create index if not exists evidence_access_links_access_type_idx
  on public.evidence_access_links (access_type);

create index if not exists evidence_access_links_source_type_idx
  on public.evidence_access_links (source_type);

create index if not exists evidence_access_links_source_report_type_idx
  on public.evidence_access_links (source_report_type);

create index if not exists evidence_access_links_created_idx
  on public.evidence_access_links (created_at);

create or replace trigger set_evidence_access_links_updated_at
  before update on public.evidence_access_links
  for each row execute function public.set_updated_at();

alter table public.evidence_access_links enable row level security;

create policy "evidence_access_links: own row select"
  on public.evidence_access_links for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "evidence_access_links: own row insert"
  on public.evidence_access_links for insert
  to authenticated
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1
      from public.skill_evidence se
      where se.id = evidence_id
        and se.user_id = (select auth.uid())
    )
    and (
      source_report_type in ('direct_skill_evidence', 'none')
      or (
        source_report_type = 'github_recruiter_proof_report'
        and exists (
          select 1
          from public.github_recruiter_proof_reports gpr
          where gpr.id = source_report_id
            and gpr.evidence_id = evidence_id
            and gpr.user_id = (select auth.uid())
        )
      )
      or (
        source_report_type = 'website_semantic_verification_result'
        and exists (
          select 1
          from public.website_semantic_verification_results wsr
          where wsr.id = source_report_id
            and wsr.evidence_id = evidence_id
            and wsr.user_id = (select auth.uid())
        )
      )
    )
  );
