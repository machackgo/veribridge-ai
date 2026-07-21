-- 060: Public VBR project report view events (recruiter report opens).
--
-- Minimal privacy-conscious view tracking for the canonical public project
-- report (`/vbr/report/{public_report_token}` → vbr_projects, migration 051).
-- The legacy `vbr_report_views` table (049) is keyed to `vbr_reports` rows and
-- cannot represent the current project-token report, which has no report row.
--
-- Deliberately stored: NO raw referrer URL, NO IP (raw or hashed), NO user
-- agent string — only coarse categories plus an optional client-generated
-- dedupe key so same-session rerenders don't inflate counts.

create table if not exists public.vbr_project_report_views (
  id                uuid primary key default gen_random_uuid(),
  project_id        uuid not null references public.vbr_projects (id) on delete cascade,
  -- How the recruiter arrived. QR scans through an external camera app open
  -- the canonical URL directly and are indistinguishable from 'direct'.
  source            text not null default 'direct'
                    check (source in ('direct', 'recruiter_open', 'recruiter_scan', 'unknown')),
  -- Coarse category only, never the referrer URL itself.
  referrer_category text not null default 'none'
                    check (referrer_category in ('internal', 'external', 'none')),
  -- Coarse device class only, never the raw user-agent string.
  ua_class          text not null default 'unknown'
                    check (ua_class in ('desktop', 'mobile', 'bot', 'unknown')),
  -- Client-generated opaque per-session key; unique per project so obvious
  -- same-page rerenders / tab refreshes don't create duplicate rows.
  dedupe_key        text,
  viewed_at         timestamptz not null default now()
);

create index if not exists vbr_project_report_views_project_idx
  on public.vbr_project_report_views (project_id);
create index if not exists vbr_project_report_views_viewed_idx
  on public.vbr_project_report_views (viewed_at);
create unique index if not exists vbr_project_report_views_dedupe_idx
  on public.vbr_project_report_views (project_id, dedupe_key)
  where dedupe_key is not null;

alter table public.vbr_project_report_views enable row level security;

drop policy if exists "vbr_project_report_views: service role all"
  on public.vbr_project_report_views;
create policy "vbr_project_report_views: service role all"
  on public.vbr_project_report_views
  for all
  to service_role
  using (true)
  with check (true);
