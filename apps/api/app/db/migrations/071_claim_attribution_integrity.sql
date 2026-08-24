-- ============================================================
-- VeriBridge AI — Migration 071: Claim attribution integrity
-- ============================================================
--
-- Trust-model correction: PROJECT EVIDENCE != CANDIDATE OWNERSHIP.
--
-- The persisted skill-claim sentence in vbr_project_skill_claims.claim_text
-- was minted as "<skill> was implemented and demonstrated in <project>." —
-- subject-ambiguous language a recruiter can read as a claim about the
-- CANDIDATE ("the candidate implemented <skill>") even when no evidence
-- connects the candidate to the artifact (e.g. a public third-party project
-- like Excalidraw used to demonstrate the proof workflow, where the candidate
-- explicitly denied authorship).
--
-- The claim writer (canonical_evidence_service._upsert_skill_claims_and_links)
-- now mints the subject-explicit PROJECT-scoped sentence
--   "<skill> is demonstrated in the project <project>."
-- and candidate attribution is carried separately (claim synthesis layer,
-- candidate_attribution_service) with its own evidence bar.
--
-- This data migration rewrites the historical rows to the same subject-safe
-- template. Non-destructive: only the sentence template changes; skill_key,
-- skill_name, claim_state, evidence_status, and every evidence link row are
-- untouched. Rows already using the new template (or custom text) are left
-- as-is. Idempotent.

update public.vbr_project_skill_claims c
set
  claim_text = c.skill_name || ' is demonstrated in the project ' || p.title || '.',
  updated_at = now()
from public.vbr_projects p
where p.id = c.project_id
  and c.claim_text like '% was implemented and demonstrated in %';

-- Legacy rows whose project row is gone keep referential honesty without a title.
update public.vbr_project_skill_claims c
set
  claim_text = c.skill_name || ' is demonstrated in this project.',
  updated_at = now()
where c.claim_text like '% was implemented and demonstrated in %'
  and not exists (select 1 from public.vbr_projects p where p.id = c.project_id);
