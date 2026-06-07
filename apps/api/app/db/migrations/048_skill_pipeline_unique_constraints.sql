-- ============================================================
-- VeriBridge AI — Migration 048: Skill Pipeline Unique Constraints
--
-- Root cause: Migration 047 created a PARTIAL unique index on
-- (student_id, skill_name) WHERE student_id IS NOT NULL.
-- The service calls upsert with on_conflict="student_id,skill_name"
-- which PostgREST translates to:
--   ON CONFLICT (student_id, skill_name) DO UPDATE ...
-- Postgres error 42P10: cannot match a plain ON CONFLICT target to a
-- partial index — the WHERE predicate must be included in the ON CONFLICT
-- clause, which PostgREST/supabase-py does not support.
--
-- Fix: replace the partial index with a non-partial unique CONSTRAINT on
-- (student_id, skill_name).  NULL behavior is safe under standard SQL:
-- two NULL student_ids are not considered equal by the constraint, so
-- rows with student_id = NULL never collide with each other.
--
-- Idempotent: DROP INDEX IF EXISTS + pg_constraint existence check.
-- ============================================================

-- 1. Remove the partial unique index created by migration 047.
--    IF EXISTS makes this safe to re-run after the index is already gone.
drop index if exists skill_evidence_pipelines_student_skill_uidx;

-- 2. Add the non-partial unique constraint that ON CONFLICT can match.
do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'skill_evidence_pipelines_student_skill_key'
      and conrelid = 'public.skill_evidence_pipelines'::regclass
  ) then
    alter table public.skill_evidence_pipelines
      add constraint skill_evidence_pipelines_student_skill_key
      unique (student_id, skill_name);
  end if;
end $$;
