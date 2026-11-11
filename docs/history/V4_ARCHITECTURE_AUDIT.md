# RECRUITER V4 ARCHITECTURE AUDIT — Role Pipeline + Evidence-Grounded Interview Workspace

Date: 2026-08-19 · Branch `feat/recruiter-pipeline-v4` @ base `c19cf727` (= main incl. V3 Hiring Briefs, PR #86).
Produced from three independent read-only audits (API domain, web frontend, AI/query-understanding) before any implementation.
This document is also the **implementation contract** shared by the V4 work packages.

---

## CURRENT ROLE-CANDIDATE MODEL

`recruiter_hiring_brief_candidates` (migration 068, applied to prod): PK `(brief_id, student_user_id)`,
stable-user-id keyed (slug-rotation-proof), role-scoped `status`, recruiter-private `note`,
`added_at/updated_at`, `set_updated_at` trigger. The brief IS the pool; `recruiter_candidate_connections`
(065) stays the workspace-level substrate, untouched. 068's own comment reserves the V4 extension:
"Forward-compatible with a fuller pipeline later; deliberately minimal for V3."

## CURRENT STATUS MODEL

Role-scoped `status ∈ (saved, reviewing, shortlisted, archived)` — enforced in **three places that must
stay in sync**: SQL CHECK (068:108-109), `BRIEF_CANDIDATE_STATUSES` tuple
(`recruiter_hiring_brief_service.py:75`), Pydantic `BriefCandidateStatus` Literal + fixed-key
`BriefCandidateStatusCounts` (`schemas/recruiter_hiring_briefs.py:24,52-60`); mirrored on the web in the
TS union (`recruiter-briefs-api.ts:23-27`) and three UI maps (`BriefDetailView.tsx:52-71`).
`_status_counts` derives keys from the tuple (adapts automatically); the Pydantic counts model and TS
counts type are closed shapes and must grow explicitly. No transition state machine exists — any→any,
validated against the closed vocabulary. Same candidate in two briefs = two independent rows by
construction (covered by existing tests).

## CURRENT HIRING BRIEF MODEL

`recruiter_hiring_briefs`: title, raw `role_text` (≤600), sanitized `plan` jsonb
(`PLAN_SCHEMA_VERSION=1`; `sanitize_plan` on EVERY load — stored plans are UNTRUSTED), lifecycle
`draft|active|paused|closed`. Endpoints under `/api/v1/recruiter/briefs` (11 routes), foreign==missing
404, `model_fields_set` + `...` sentinel partial updates, `extra="forbid"` everywhere.
Backend is service-role for ALL requests → **app-level `recruiter_user_id` filtering is the tenancy
boundary**; 068 RLS is defense-in-depth.

## CURRENT COMPARISON MODEL

Not a table — a live view. `evaluate_matrix(db, recruiter_user_id, candidate_user_ids, plan)` over the
brief pool (whitelisted via `resolve_candidate_user_ids(allowed_user_ids=pool)`), min 2 / max 5.
Axis: `_requirement_axis(plan)` → ordered `{key, kind: concept|evidence, display, required, concepts[]}`
(keys `concept:a|b`, `evidence:github`; ≤16 rows). Cells: `proven|claimed|none|unavailable` with
provenance (`proof_path=/p/{slug}/skills/{skill_slug}`, ≤3 project refs, ≤2 sanitized traces,
related-but-NOT-proof hints). Transparent counts, deterministic summaries, **no scores** (enforced by
unit + e2e "%"-sweep tests).

## CURRENT EVIDENCE VERIFICATION MODEL

`_candidate_evidence_map` / `_verify_concept` / `_evidence_requirement_met` over the search-index public
projection; taxonomy `satisfies()` (child⇒parent only, ML≠NLP, related proves nothing).
**Fail-closed triple on every load** (`live_valid_index_rows`): discovery exclusions + live
`is_published` + live `disclosure_version`; unavailable candidates degrade to zeroed columns with
identity from the recruiter's own connection projection — never a stale index row.
Index rows carry per-skill `projects[]` (title, public_report_path, skill_status, proof_types) and
`traces[]` (source_type, source_title, ≤220-char sanitized summary, public_url) — the finest evidence
provenance available, exactly what grounded interview questions cite.

## CURRENT RLS MODEL

068 tables: owner-only `authenticated` policies (brief via `recruiter_user_id = auth.uid()`, pool via
EXISTS on owning brief), `service_role` all, **students no policy**. 26/26 live probes passed at V3
deploy. `recruiter_search_index` + `recruiter_search_events`: service-role only.

## REUSABLE COMPONENTS

- Backend: `_requirement_axis` + `_candidate_column` (deterministic checklist backbone, per-requirement
  proof provenance), `live_valid_index_rows`, `evaluate_candidate_summary`, `_column_summary`
  (deterministic prep header), `sanitize_plan`, `record_search_event` + `_record_brief_event`
  (privacy-safe analytics), dual-mode dict/Supabase storage helpers, `_read_with_transient_retry`,
  foreign==missing 404 + `...`-sentinel + race-recovery API craft, apply-script recipe.
- AI: `LlmFn` injectable seam + provider resolution (`llm_proof_synthesis_service.py:174,824`),
  `settings.anthropic_configured` gate (config.py:641), build-deterministic-fallback-FIRST + replace
  only on validated parse (`:918-940`), citation-allowlist JSON validation (`_parse_llm_synthesis`,
  `:637-738`), `_safe_text` scrubbing, `source: "llm"|"deterministic"` provenance, autouse hermetic
  test fixture (`tests/conftest.py:97-120`).
- Web: `components/passport/shared.tsx` kit (TOKEN, Card, Badge, Btn, EmptyState, ErrorState),
  `components/brand` (`ProofDiamond` claimed|attached|verified — the evidence-state visual),
  `recruiter-briefs-api.ts` request wrapper (`fetchAPI` w/ transient retry + `AuthRequiredError`),
  proof deep links (`MatrixCell.proof_path` free on every proven cell), evidence drawer
  (`viewEvidence({skill, candidate})` + `EvidenceItemBlock`/`RequirementRow` — to be extracted shared),
  `useSpeechRecognition` hook, mock-the-api-client vitest pattern, e2e hydration guards + chunked
  cookie session minting.

## MISSING PIPELINE COMPONENTS

- Stage vocabulary beyond `shortlisted` (contacted/interview/decision/hired/passed).
- Stage-grouped pipeline UI (Candidates tab shows a flat grid).
- Role-candidate activity timeline (no history of stage changes).
- Duplicate-add prevention exists (PK + race recovery) — nothing missing.

## MISSING INTERVIEW COMPONENTS

- No interview session/notes storage anywhere (drafts precedent is student-side sessionStorage only).
- No per-requirement recruiter marks ("discussed / verified in interview").
- No interview question generation grounded in the plan+evidence (only tone-baseline heuristics:
  `public_work_passport_service._suggested_interview_questions`, `vbr_question_generation.py` — whose
  TODO literally names this feature as its successor).
- No autosave pattern in the codebase (will introduce one: debounced + requestSeq + save-on-blur).

## PROPOSED DB CHANGES — MIGRATION 069 (`069_recruiter_interview_workspace.sql`)

Additive, idempotent, production-safe. All new tables: RLS enabled, owner-via-brief EXISTS policy for
`authenticated`, `service_role` all, **students no policy**, `set_updated_at` triggers where updated_at
exists, `notify pgrst, 'reload schema'` at end, manual rollback comment.

1. **Widen the pool status CHECK** (additive superset — existing rows all remain valid):
   ```sql
   alter table public.recruiter_hiring_brief_candidates
     drop constraint if exists recruiter_hiring_brief_candidates_status_check;
   alter table public.recruiter_hiring_brief_candidates
     add constraint recruiter_hiring_brief_candidates_status_check
     check (status in ('saved','reviewing','shortlisted','contacted','interview',
                       'decision','hired','passed','archived'));
   ```
2. **`recruiter_brief_candidate_interviews`** — one workspace per (brief, candidate).
   PK `(brief_id, student_user_id)`; `brief_id → recruiter_hiring_briefs(id) on delete cascade`;
   `student_user_id → users(id) on delete cascade` (right-to-delete alignment, same as 068 pool).
   Deliberately NOT FK'd to the pool row: removing a candidate from the role must not destroy
   interview notes; re-adding restores the workspace.
   Columns: `scheduled_at timestamptz`, `interviewer_name text` (≤120 app-side),
   `prep_notes text`, `notes text`, `decision_notes text` (all recruiter-private, ≤4000 app-side),
   `questions jsonb not null default '{}'` (stored generated questions + provenance — UNTRUSTED on
   load, always re-validated like `plan`), `created_at/updated_at` + trigger.
3. **`recruiter_interview_checklist_marks`** — recruiter-private per-requirement interview marks.
   PK `(brief_id, student_user_id, requirement_key)`; same FKs as above;
   `state text check (state in ('discussed','verified','follow_up'))`, `marked_at timestamptz default now()`.
   `requirement_key` = the deterministic axis key (`concept:a|b` / `evidence:github`), ≤160.
   These marks are recruiter hiring context ONLY — never public proof, never candidate-visible,
   never written to any index/projection.
4. **`recruiter_brief_candidate_events`** — compact recruiter-private activity trail (not event
   sourcing). `id uuid pk`, `brief_id → briefs cascade`, `student_user_id → users cascade`,
   `event_type text check in ('added','stage_changed','note_updated','interview_updated',
   'checklist_marked','questions_generated','removed')`, `detail jsonb not null default '{}'`
   (closed small shape: e.g. `{"from":"reviewing","to":"contacted"}` — NEVER note text, NEVER
   candidate content), `created_at`. Index `(brief_id, student_user_id, created_at desc)`.

**NEXT MIGRATION NUMBER: 069** (verified free repo-wide; 001–068 contiguous).

## PIPELINE STATES (final)

`saved → reviewing → shortlisted → contacted → interview → decision → hired | passed | archived`

- `passed` = considered and declined for THIS role; `archived` = parked without decision. Both
  reversible; no stage is mandatory; any→any transitions (validated against the closed vocabulary
  only — recruiters move candidates naturally; the activity trail is the audit, not a state machine).
- Role-scoped by construction (PK on `(brief_id, student_user_id)`); zero global status.
- 5-site sync edit: 069 CHECK · service tuple `:75` · schemas Literal+Counts · TS union+counts ·
  UI maps. `_status_counts` adapts automatically.
- Stage changes recorded as `stage_changed` activity events (service-level, from/to only).

## AI GROUNDING ARCHITECTURE (interview questions)

New `services/recruiter_interview_service.py` + question generation module:

```
sanitized plan (brief) + live checklist (axis + cells, fail-closed) 
  → grounding payload (ONLY: requirement display/kind/required, cell state,
     matched_label, evidence_sources, project titles, trace summaries [already ≤220-char
     sanitized public projections], proof_path)  — candidate text is UNTRUSTED DATA
  → deterministic question set built FIRST (always available; templates per cell state)
  → if settings.anthropic_configured: single LLM attempt (LlmFn seam, module-level fn so the
     hermetic conftest fixture + tests can patch; no retry; bounded timeout)
  → validation: strip fences → json.loads or discard → every item MUST cite a requirement_key
     from the axis allowlist (unknown → dropped); items citing `none`-state requirements are
     forced into gap-verification framing; per-item + total caps (≤2/req, ≤12 total);
     `_safe_text`-style scrub; empty survivors → deterministic set
  → stored on interviews.questions jsonb with {source: "llm"|"deterministic", generated_at,
     fallback_reason?}; re-validated + re-grounded against the CURRENT checklist on every load —
     a question whose evidence is no longer proven is flagged evidence_available=false and the UI
     says "Previously referenced evidence is no longer published."
```

LANGUAGE INVARIANTS (enforced in templates + validation + tests):
never "the candidate doesn't know X" — always "No published X evidence was found";
absence of evidence ≠ evidence of absence; AI advisory only; no scores, no suitability judgments,
no protected-characteristic/personality/honesty/intelligence inference. Prompt hard-rules follow
`llm_proof_synthesis_service._SYSTEM_PROMPT` shape; candidate-derived strings are data, never
instructions; unknown citations can only WEAKEN output (drop), never add.

## API CONTRACT (new/changed surface — all under `/api/v1/recruiter/briefs`)

Changed:
- `PATCH /{brief_id}/candidates/{uid}` — status now validated against the 9-stage vocabulary;
  records `stage_changed` activity event when status actually changes.
- `POST /{brief_id}/candidates` records `added`; `DELETE .../{uid}` records `removed`.
- `GET /{brief_id}/candidates` unchanged shape (evaluation already batched — no N+1); counts grow keys.

New (all `get_current_user_id`, foreign==missing 404 via `_not_found()`; `db=Depends(get_db)`):
- `GET  /{brief_id}/candidates/{uid}/interview` → `InterviewWorkspaceResponse`
  `{brief: HiringBriefListItem, candidate: BriefCandidateIdentity, pool_status: str,
    checklist: {requirements: [MatrixRequirement], cells: {key→MatrixCell}, counts: ColumnCounts,
    available: bool, unavailable_note: str|None, summary: str},
    marks: [{requirement_key, state, marked_at}],
    interview: {scheduled_at, interviewer_name, prep_notes, notes, decision_notes, updated_at} | null,
    questions: {items: [InterviewQuestion], source, generated_at, fallback_reason: str|null} | null,
    activity: [{event_type, detail, created_at}] (≤30 newest)}`
  `InterviewQuestion = {id, requirement_key, kind: "evidence"|"gap", question,
    grounding: {requirement_display, state, matched_label|null, evidence_sources[], project_titles[],
    proof_path|null}, evidence_available: bool}`
  Candidate must be in the pool (404 otherwise). Checklist computed live per request (fail-closed).
- `PATCH /{brief_id}/candidates/{uid}/interview` → upserts the interview row; `...`-sentinel partial
  update over `{scheduled_at, interviewer_name, prep_notes, notes, decision_notes}` (+ `clear_*`
  flags mirroring the note pattern); returns the interview object. Autosave-friendly: no analytics
  event; recruiter-private activity `interview_updated` recorded at most once per 15 min per pair.
- `POST /{brief_id}/candidates/{uid}/interview/questions` `{regenerate?: bool}` → generates (or
  returns stored unless regenerate), stores, returns the questions object. Analytics
  `questions_generated` (counts only). 503-never: LLM failure silently degrades to deterministic
  with `fallback_reason`.
- `POST /{brief_id}/candidates/{uid}/interview/checklist` `{requirement_key, state: 
  "discussed"|"verified"|"follow_up"|null}` (null clears) → returns updated marks list. Body not
  path param (keys contain `:`/`|`). Activity `checklist_marked`.

## PIPELINE UX

Inside the brief (the brief IS the role scope) — no new global nav. `BriefDetailView` tab type grows:
`candidates | compare | search` → the **Candidates tab becomes the pipeline** (one tab, not two — two
tabs over the same rows would create state-collision UI and ATS bloat):
- Stage summary bar: 9 stage pills with live counts (from `status_counts`), acting as filters
  (`aria-pressed`, keyboard reachable). Empty stages render as count-0 pills, not empty columns.
- Below: stage-grouped sections (only non-empty stages, in pipeline order), each `<h3>` + count +
  card grid (existing `auto-fill minmax(340px)` — intrinsically mobile-safe; NO horizontal kanban,
  NO drag-and-drop: explicit controls are more accessible and error-proof).
- `PoolCandidateCard` evolves: stage moves via an accessible `<select>` (9 options, labelled), keeps
  evidence context (`EvaluationLine`: required proven counts, missing displays, excluded hits — never
  a score), private note editor, `Interview prep →` link (always available) to the workspace route,
  Open Passport. Card testids: `brief-candidate-stage-select`, `brief-candidate-interview-link`.
- Compare tab fix (V3 defect): compute `comparableCount` (non-archived, mirroring server), guard the
  fetch, calm `EmptyState` ⚖️ for 0 ("Find candidates using this role's requirements" → switch to
  search tab) and 1 ("Add at least 2 candidates to compare evidence"); surface `detail.code` via a
  `BriefApiError` so `too_few_candidates` is never rendered as "Something went wrong".

## INTERVIEW UX

Full page `/recruiters/briefs/[briefId]/interview/[studentId]` (server-side auth gate like the brief
page; recruiter-private). Layout (desktop 2-col ~ 7/5, mobile stacked):
- Header: candidate identity + role title + pool stage + deterministic summary line + Open Passport.
- **Verification checklist** (the deterministic core, works with AI down): axis rows grouped
  Required / Required evidence / Preferred; each row: `ProofDiamond`-style state, display,
  `✓ published evidence` (+ `View proof →` deep link + expandable evidence drawer reusing the
  extracted `EvidenceProofDrawer`) or `? No published evidence — verify during interview`
  (exact language contract); recruiter mark control (Discussed / Verified in interview / Follow up —
  clearly labelled "recruiter-private; never becomes public evidence").
- **Interview questions**: Generate/Regenerate button; each question card shows the question +
  grounding footer (Requirement · Project · Evidence source · View proof) + kind badge
  (`Evidence-backed` / `Gap to verify`); stale grounding shows "Previously referenced evidence is no
  longer published."; provenance line "Generated from published evidence — advisory only"
  (+ deterministic fallback notice when `source=deterministic` and LLM configured-but-failed).
- **Notes panel**: prep notes + interview notes + decision notes textareas, debounced autosave
  (~800 ms, requestSeq stale-drop, save-on-blur, "Saved ✓ / Saving…" status, beforeunload guard) —
  "Private to you — never visible to the candidate."
- **Decision strip**: current stage + explicit outcome buttons (Move to Decision / Hired / Passed /
  Archived / keep reviewing) driving the same PATCH stage endpoint + decision notes. Transparent
  coverage line ("Required evidence supported: 3 of 4") — deterministic, explained, never a %.
- Activity timeline (compact, collapsible).
- Empty/edge states: candidate unpublished → checklist unavailable note + identity fallback; no
  questions yet → invite generation; AI unavailable → deterministic set with honest provenance.

## V3 UX DEFECTS TO FIX (in scope)

1. Compare-with-<2-candidates alarming `ErrorState` → calm empty states + error-code surfacing (above).
2. Search `InterpretationPanel` never renders `residual_terms` → add the brief view's honest
   "Not understood (never silently used): …" treatment.
3. Location normalization (scoped, not a geography project): `_PLACE_ALIASES` beside `_KNOWN_PLACES`
   (state abbreviations + `mass`, `nyc`, `sf`; **2-letter codes honored ONLY after a location starter
   or comma-adjacent to a known city — never bare**, so `or`/`in`/`ai`/`ok` stay operators/skills);
   handle `"Boston, MA"` (comma window special-case); normalize BOTH matcher sides
   (`_term_in` on location: canonicalize query + row through the same alias map) so
   `massachusetts` matches a stored `"Boston, MA"`. Guard regressions: OR-group parsing, gibberish
   fallback, shorthand tests.

## PRIVACY RISKS (and mitigations)

- Interview notes/marks/questions/activity are recruiter-private: new tables have owner-only RLS,
  students no policy; app-level ownership resolves through the owning brief on EVERY query (backend
  is service-role — app filters are the real boundary). Explicit tests: recruiter-B 404 on every new
  verb; student token sees nothing; public passport payloads unchanged (grep + test that passport/
  index/evidence builders never reference the new tables).
- Analytics: counts + recruiter-authored text only (existing `_record_brief_event` discipline);
  activity `detail` closed shape, never note text. Privacy-sweep test extended to new events.
- LLM payload: only already-public sanitized projections (same guarantee as proof synthesis);
  prompt-injection posture is architectural (citation allowlist, drop-unknown, weaken-only) + tested
  with malicious project titles/traces.
- Checklist marks must never contaminate the public evidence graph: no writes to any student-owned
  or public table from the interview surface (asserted by test).
- Evidence unpublish mid-flow: checklist recomputed live (fail-closed triple); stored questions
  re-graded on load; UI shows the "no longer published" state instead of stale proof.

## PERFORMANCE RISKS

- Workspace GET = ~8 bounded queries (brief, pool row, index row + triple, interview, marks, events)
  — no N+1. Pool list already batches `live_valid_index_rows` for the whole pool (100-cap).
- Pipeline tab reuses the existing single `GET /candidates` (evaluation batched server-side);
  grouping is client-side. 100-candidate pool = same payload as V3's flat grid.
- Autosave PATCHes are single-row upserts; activity writes rate-limited (15-min collapse) to avoid
  event spam; questions stored (no LLM call on every load).

## IMPLEMENTATION PLAN (3 work packages, orchestrator-owned integration)

- **WP1 backend**: migration 069 + apply script (NOT run); status vocabulary 3-site backend edit;
  `recruiter_interview_service.py` (dual-mode storage, workspace assembly, sentinel PATCH upsert,
  checklist marks, activity events incl. stage/add/remove hooks in brief service, question
  generation deterministic+LLM+validation); `schemas/recruiter_interviews.py`; endpoints + router;
  conftest hermetic extension; tests (isolation matrix on every new verb, role independence,
  fail-closed, deterministic checklist, AI grounding validation incl. injection corpus, fallback,
  activity, privacy sweeps).
- **WP2 frontend**: TS client (9-stage union, counts, interview API, `BriefApiError` w/ code);
  pipeline-ified Candidates tab + stage bar + accessible stage select; compare empty-state fix;
  interview workspace route + view (checklist, questions, autosave notes, decision strip);
  `EvidenceProofDrawer` extraction; search residual-terms honesty line; vitest suites.
- **WP3 parser/e2e**: `_PLACE_ALIASES` + comma-city handling + matcher-side normalization + parser
  tests; e2e-local V4 journey spec (create→search→add→stage walk→interview→notes→persistence,
  cross-role independence, zero console errors/5xx) + e2e-prod spec (post-deploy).
- Orchestrator: integration, full API+web suites, typecheck, build, local rig e2e, migration+RLS
  review, browser QA (desktop + iPhone 13), deploy gates, PR.

## GATES (unchanged from mission §38 — nothing deploys until all pass)
