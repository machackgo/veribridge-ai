# 075 (note, not a migration): `public.project_defense_analysis_results`

This file is documentation only. There is deliberately no `075_*.sql` yet.

## The gap

Migrations 033 (`project_defense_transcript_refinement`) and 046
(`project_defense_transcript_segments`) `ALTER` the table
`public.project_defense_analysis_results`, but no migration creates it. The
table was created outside the repository in production. As a result:

- a fresh database cannot be built from `001`–`074b` alone (033 fails), and
- the repository says nothing about the table's real columns, constraints or
  whether Row Level Security is enabled on it.

## Where the real DDL must come from

Do not write the `CREATE TABLE` from the code or from guesses. Run
`VERIBRIDGE_PROD_VERIFY_ONE.sql` against production and use its
`catalog.project_defense_analysis_results` section, which returns the table's
real column list (name, type, not-null, default, identity, generated),
constraints, indexes, triggers, RLS flags and policies. A bootstrap migration
(numbered before 033, or as a `create table if not exists` that runs ahead of
it) must reproduce exactly that schema, with the columns 033 and 046 add left to
those migrations.

## If the verification output shows `rls_enabled: false`

The table holds Project Defense transcripts. All access is API-mediated through
the service-role client (which bypasses RLS), so enabling RLS with no policies
denies anon/authenticated PostgREST access and leaves the API unchanged. Run
this on staging first, then production:

```sql
begin;
set local lock_timeout = '5s';
alter table if exists public.project_defense_analysis_results enable row level security;
commit;
```

It is idempotent. `lock_timeout` makes it fail fast without changing anything if
a long-running query holds the table, so it can just be retried. Verify
afterwards that `catalog.project_defense_analysis_results.rls_enabled` is `true`
and that anon `GET /rest/v1/project_defense_analysis_results?select=id` returns
`[]`.

Rollback (re-opens the exposure):
`alter table public.project_defense_analysis_results disable row level security;`
