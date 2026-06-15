-- ============================================================
-- VeriBridge AI — Migration 051: Public recruiter-safe VBR
-- report link for a Project Defense project (v1)
--
-- Adds the minimal token columns needed to publish the
-- student-owned Final VBR Report (built from vbr_projects +
-- Project Defense evidence) as a read-only, tokenized public
-- recruiter link.
--
-- Mirrors the existing vbr_reports.public_token pattern:
--   * a single nullable, unique token minted at publish time
--   * cleared on unpublish so old links stop resolving
--   * published_at records when the link was last minted
--
-- No new table is introduced — the public report is derived
-- on the fly from the project's already-sanitized evidence
-- summaries, so only the token + timestamp need to persist.
--
-- Idempotent: safe to re-run.
-- ============================================================

alter table public.vbr_projects
  add column if not exists public_report_token text,
  add column if not exists public_report_published_at timestamptz;

-- One project per public token. Multiple NULLs are allowed by Postgres
-- unique indexes, so unpublished projects (token NULL) never collide.
create unique index if not exists vbr_projects_public_report_token_unique_idx
  on public.vbr_projects (public_report_token)
  where public_report_token is not null;
