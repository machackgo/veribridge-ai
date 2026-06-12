-- ============================================================
-- VeriBridge AI — Migration 050: Add session_id to vbr_reports
--
-- T7D scope: associate each vbr_reports row with the exact
-- vbr_verification_sessions attempt it was drafted from, so a
-- second verification attempt on the same project cannot
-- overwrite or publish another attempt's report.
--
-- Backfills session_id from the existing body->summary->session_id
-- for any pre-existing report rows where that value is a valid uuid.
--
-- Idempotent: safe to re-run.
-- ============================================================

with report_session_backfill as (
  select
    r.id,
    (r.body #>> '{summary,session_id}')::uuid as session_id
  from public.vbr_reports r
  where r.session_id is null
    and r.body #>> '{summary,session_id}' ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
)
update public.vbr_reports r
set session_id = b.session_id
from report_session_backfill b
join public.vbr_verification_sessions s on s.id = b.session_id
where r.id = b.id;


alter table public.vbr_reports
  add column if not exists session_id uuid
    references public.vbr_verification_sessions (id) on delete set null;

update public.vbr_reports
set session_id = (body #>> '{summary,session_id}')::uuid
where session_id is null
  and body #>> '{summary,session_id}' ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';

-- One report row per verification session. Multiple NULLs are allowed by
-- Postgres unique indexes, so pre-existing rows that could not be backfilled
-- remain valid.
create unique index if not exists vbr_reports_session_id_unique_idx
  on public.vbr_reports (session_id);
