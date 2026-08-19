# V3 RECONCILIATION AUDIT — Recruiter Hiring Briefs

Date: 2026-08-18 · Orchestrator session · Three independent read-only audits (V2 salvage, V3 quarantine, frontend/integration) reached consistent verdicts on every overlapping question.

## WORKTREE

`/Users/mohammedmubashiruddinfaraz/veribridge-v3-hiring-briefs`

Note: the expected worktree did not exist at session start — the quarantine branch was checked
out directly in `~/veribridge-ai`. This worktree was created fresh at the quarantine tip.
`~/veribridge-ai` and `~/veribridge-landing` were not modified.

## BRANCH

`feat/recruiter-hiring-briefs-v3-reconcile` (new, based at the quarantine tip; git forbids
checking out `quarantine/v3-hiring-briefs-unverified` in a second worktree since it is held
by `~/veribridge-ai`). The quarantine branch itself remains untouched as the preservation record.

## QUARANTINE TIP

`e5f7f965` — preservation-only snapshot of the interrupted V3 session (7 files, +1641/−10).
Parents/context: base `72055b44` (deployed V1.6 tip); V2 preserved at
`wip/recruiter-v2-comparison-draft` = `c57464ad` (bulk) + `d64cbd97` (tip, 181/181 tests green).
Nothing from either branch deployed; **no 068 migration ever applied to any environment.**

## V2 COMPONENTS TO SALVAGE

1. **Matrix evaluation engine** — requirement×candidate matrix, closed cell states
   `proven / claimed / none / unavailable`, proof provenance (`/p/{slug}/skills/{slug}` deep
   links, project refs, trace previews), related-but-NOT-proof hints, transparent counts,
   deterministic summaries, **no scores/percentages**, fail-closed triple re-check
   (exclusions + `is_published` + `disclosure_version`) on every load, unavailable-column
   identity fallback from the recruiter's own connection projection. *Already present
   line-for-line in V3's `recruiter_comparison_service.py` — reconcile onto V3's copy, do not
   re-port from V2.*
2. **satisfies()/verification reuse** — engine imports `_candidate_evidence_map`,
   `_verify_concept`, `_evidence_requirement_met`, `_excluded_user_ids`,
   `_live_publication_map`, `_live_disclosure_versions`, `_read_with_transient_retry` from
   `recruiter_search_service`; taxonomy contract (ML≠NLP, child⇒parent only, related proves
   nothing) inherited, never reimplemented. Preserved.
3. **Test corpus** — fixture corpus (`_skill`/`_row`/`_seed`) and ~15 engine tests from
   `d64cbd97:apps/api/tests/test_recruiter_comparison_shortlisting.py` (matrix states,
   provenance, no-fake-scores sweep, related-not-proof, claimed-not-verified, fail-closed
   unpublish/disclosure/exclusion, excluded-flag-keeps-column). Port with brief-shaped entry
   points. Persistence-half tests re-expressed against briefs (patterns: foreign==missing 404,
   recruiter-isolation matrix, idempotency, fail-closed reload).
4. **Matrix schema models** — `MatrixCell/MatrixColumn/RequirementCoverage/…` from V2's
   `schemas/recruiter_comparisons.py`: architecture-neutral payload shapes; reuse under the
   brief-comparison response. Session CRUD models dropped.
5. **API craft patterns** — foreign==missing 404; `model_fields_set` partial update with `...`
   sentinel + `clear_note` flag; idempotent create/add with unique-violation race recovery;
   privacy-safe analytics via `recruiter_search_events` (counts + recruiter-authored text only).
6. **Migration apply-script pattern** — `apply_068_comparison_shortlisting.py` recipe
   (URL-decoded password, pooler fallbacks) retargeted at the hiring-briefs migration.

## V3 COMPONENTS TO KEEP

1. **`recruiter_requirement_plan.py` (whole module, verbatim)** — canonical plan abstraction:
   `plan_from_role_text` / `plan_from_requirements` / `requirements_view` / `sanitize_plan`
   (hardened for untrusted jsonb/client input, forced closed vocab + `candidate_search`
   intent) / `merge_refinement` / `required_concept_set`, `PLAN_SCHEMA_VERSION = 1`.
2. **Query-understanding delta (verbatim)** — strict functional superset of V2's +43
   (trailing-marker rewrite extended; sentence-boundary mode resets; `MAX_BRIEF_LENGTH=600`;
   senior/mid-level; closed `_KNOWN_PLACES` vocabulary; `remote` flag; intent-noise words).
   Nothing from V2's parser delta needs salvaging.
3. **Migration `068_recruiter_hiring_briefs.sql` design** — brief-as-pool model wins the 068
   slot (see MIGRATION STRATEGY).
4. **V3 comparison-service structure** — plan helpers extracted out; `live_valid_index_rows`
   public helper; `resolve_candidate_user_ids` with `candidate_user_ids` + `allowed_user_ids`
   whitelist (brief pool compared without trusting raw client ids); `evaluate_candidate_summary`
   (per-candidate counts for a brief's candidates tab); no leaked `plan` key in responses.
5. **Search hooks** — `search_candidates(plan=…)` structured entry (bypasses NL parse for a
   sanitized stored plan) and `SearchResultCandidate.in_brief`/`brief_status` +
   `QueryInterpretation.remote` schema fields; currently dangling, to be wired by the new
   brief service/endpoints.

## CONFLICTS

1. **068 slot collision** — two incompatible migrations both numbered 068:
   V2 `068_recruiter_comparison_shortlisting.sql` (209 ln: global status on connections +
   `recruiter_comparisons` sessions + talent pools) vs V3 `068_recruiter_hiring_briefs.sql`
   (155 ln: briefs + brief candidates). Mutually exclusive designs; V3 wins (see below).
2. **Cross-contamination from the shared-checkout collision** (byte-identical blobs, so no
   textual conflicts — only ownership decisions):
   - V3's `068_recruiter_hiring_briefs.sql` was swept into V2's tip commit `d64cbd97`
     (its tree carries BOTH 068 files). Ignore it there.
   - V2's `schemas/recruiter_comparisons.py` (session CRUD contracts, docstring "v2,
     migration 068") was swept into the V3 quarantine. It contradicts V3's no-sessions
     service and has a latent landmine: `requirements_view()` emits `remote` but the
     `extra:"forbid"` schemas lack the field — instant Pydantic failure the moment an
     endpoint exists. **Rewrite around briefs.**
3. **Shortlist semantics** — V2: global per-connection status. V3: role-scoped per
   `(brief_id, student)`. Incompatible; role-scoped wins per product model.
4. **Session vs live-view comparison** — V2 persists comparison sessions with their own
   `candidate_user_ids`; V3 makes comparison a live view over a brief's pool. V3 wins;
   sessions would duplicate the pool.
5. **Query-understanding double edit** — only file both sessions touched; V3 strictly
   supersedes. No merge needed.
6. **Naming hazard** — pre-existing legacy `/public/recruiter/candidate-comparisons`
   (migration 027/030, unverified-email + `X-Recruiter-Token` identity) already owns
   "comparison" and a status vocabulary. Do NOT extend it; new surface lives under
   `/recruiter/briefs`, authenticated via Supabase JWT.
7. **V3 is an engine with no chassis** — no brief service, no endpoints, no router wiring,
   no schemas for briefs, no tests, no apply script. That is the implementation gap, not a
   design conflict.

## MIGRATION STRATEGY

- **V3's `068_recruiter_hiring_briefs.sql` keeps the 068 slot.** Rationale: role-scoped
  status (incl. `reviewing`) with real FK pool rows is the required product semantics; it
  collapses V2's three-table design (sessions + pools + connection ALTER) into two tables;
  `recruiter_candidate_connections` stays untouched as the workspace substrate; neither
  migration was ever applied anywhere, so there is no rollback debt.
- **V2's `068_recruiter_comparison_shortlisting.sql` is discarded** (and its apply script).
  Deferred product question (documented, not blocking): a workspace-level `archived` flag on
  connections — V2's only piece with no V3 counterpart. Not needed for V3 scope; DELETE
  connection already covers removal; revisit only if product asks.
- Migration remains **additive and idempotent**; no evidence snapshots by design (live
  fail-closed re-evaluation is the privacy contract).
- A new `apply_068_hiring_briefs.py` script is written but **NOT executed**. Gate order:
  reconciled architecture → full local test suite green → migration review → RLS/privacy
  review → local rig verification → only then production apply (separate, explicit step).
- RLS in 068 is defense-in-depth only: backend is service-role for all requests, so every
  brief query MUST filter `recruiter_user_id` (and pool ops resolve through the owning brief)
  in application code.

## FINAL DOMAIN MODEL

- `recruiter_hiring_briefs` — id, recruiter_user_id (FK users, cascade), title, role_text
  (raw NL), `plan` jsonb (canonical requirement plan, `PLAN_SCHEMA_VERSION` stamped,
  **always re-sanitized on load, never trusted raw**), status `draft|active|paused|closed`,
  timestamps. The brief IS the role: requirements + pool + comparison scope.
- `recruiter_hiring_brief_candidates` — PK `(brief_id, student_user_id)` (stable user id,
  slug-rotation-proof), role-scoped status `saved|reviewing|shortlisted|archived`,
  recruiter-private `note`, added_at/updated_at. The brief-candidates table IS the role
  candidate pool; no separate talent-pool or session tables.
- `recruiter_candidate_connections` (065) — unchanged: global workspace membership.
  Brief-driven saves may stamp `source="role_match"`, `source_context={"brief_id":…}`
  (already-reserved enum value; no schema change).
- Comparison — **not a table**: a live view computed per request by `evaluate_matrix` over a
  brief's pool (whitelisted via `resolve_candidate_user_ids(allowed_user_ids=pool)`), with the
  full fail-closed privacy triple on every load.
- Privacy invariants: candidate axis = indexed public projection only; brief titles/plans/notes
  are recruiter-private and never reach the index, events beyond coarse counts, or any
  candidate-facing surface; unavailable candidates fall back to the recruiter's own connection
  projection, never a stale index row; foreign == missing (404) everywhere.

## FINAL ROLE-SCOPED WORKFLOW

HIRING BRIEF (title + NL role text and/or edited requirement chips → sanitized plan)
→ ROLE REQUIREMENTS (plan ⇄ editable chips via `requirements_view`/`plan_from_requirements`)
→ SEARCH / DISCOVERY (brief-scoped search: stored plan drives `search_candidates(plan=…)`,
  optional per-search refinement via `merge_refinement` without mutating the brief; results
  annotated `in_brief`/`brief_status`)
→ EVIDENCE VERIFICATION (same `satisfies()`/`_verify_concept` path as V1.5/V1.6; exact/close;
  proof drawer / View Proof unchanged)
→ ROLE CANDIDATE POOL (add by connection or published slug → `recruiter_hiring_brief_candidates`,
  status `saved`; workspace connection optionally ensured via idempotent `save_candidate`)
→ COMPARISON (live matrix over 2–5 pool candidates; proven/claimed/none/unavailable;
  transparent counts; NO opaque scores)
→ ROLE-SPECIFIC SHORTLIST (PATCH status per (brief, candidate): saved → reviewing →
  shortlisted / archived; per-brief private note)
→ DECISION WORKFLOW (brief status draft/active/paused/closed; shortlist view per brief).

A candidate can simultaneously be Shortlisted for "AI Engineer" and merely Saved for
"Backend Engineer" — status is per (brief, candidate) by construction; no global status.

## TEST STRATEGY

- **API unit (hermetic, dict-mode)** — house pattern: FastAPI `TestClient` +
  `dependency_overrides[get_current_user_id/get_db]`, in-memory dict store, no network.
  New `test_recruiter_hiring_briefs.py`:
  1. Ported V2 engine tests (matrix cell states, child⇒parent indirect proof, provenance,
     related-not-proof, claimed-not-verified, no-fake-scores sweep, zero-coverage note,
     excluded-flag-keeps-column) re-expressed through brief endpoints.
  2. Brief CRUD: create from role_text, create from chips (chips win), sanitize round-trip,
     list/get/patch/delete, status transitions, limits, `remote` field round-trip (the V2
     schema landmine gets an explicit regression test).
  3. Pool: add by connection / by published slug, idempotency, remove, per-brief status+note
     PATCH (sentinel partial update, clear_note), invalid status 422, role-scoped independence
     (same candidate different statuses in two briefs).
  4. Isolation: recruiter-B cannot see/touch recruiter-A briefs/pool on every verb
     (foreign==missing 404).
  5. Fail-closed: unpublish / disclosure bump / exclusion degrade comparison columns and
     brief-scoped search on reload.
  6. Brief-scoped search: stored plan drives results; refinement merges without mutating brief;
     `in_brief`/`brief_status` annotations.
  7. Analytics: one privacy-safe event, no notes/titles leaked.
  8. Existing suites (`test_recruiter_search*`, `test_recruiter_connections`,
     `test_recruiter_security`, evidence discovery) must stay green — the quarantined parser
     changes run on every search.
- **Web unit (Vitest)** — extend TS client types (`remote`, `in_brief`, `brief_status`) and
  fixtures; new tests for brief list/detail/pool/comparison components following existing
  `recruiter-*.test.tsx` mock-the-api-client pattern.
- **E2E** — local rig spec (`e2e-local/`) for the brief workflow once UI exists; production
  suite only post-deploy. Never run in parallel with other suites; one rig at a time.

## IMPLEMENTATION PLAN

Backend first, then frontend; migration apply and deploy explicitly out of scope until all
gates pass.

1. **Schemas** — new `schemas/recruiter_hiring_briefs.py`: brief CRUD models, pool/candidate
   models, brief-comparison response reusing V2's matrix models (with `remote` added to
   requirement views/inputs). Delete stale `schemas/recruiter_comparisons.py` session models
   (file rewritten/replaced).
2. **Service** — new `services/recruiter_hiring_brief_service.py` (dict/Supabase dual-mode):
   brief CRUD with `sanitize_plan` on every load, pool ops (idempotent add w/ race recovery,
   remove, status/note partial update), comparison assembly via `evaluate_matrix` +
   `resolve_candidate_user_ids(allowed_user_ids=pool)`, `evaluate_candidate_summary` for the
   pool view, brief-scoped search via `merge_refinement` + `search_candidates(plan=…)` with
   `in_brief`/`brief_status` annotation, privacy-safe analytics. App-level
   `recruiter_user_id` filters on every query.
3. **Endpoints + wiring** — `endpoints/recruiter_hiring_briefs.py` under `/recruiter/briefs`;
   register in `router.py`. Connection-status vestige in matrix columns resolved (drop or
   populate from brief status).
4. **Apply script** — `scripts/apply_068_hiring_briefs.py` (written, not run).
5. **Tests** — suite per TEST STRATEGY; run `pytest` for recruiter tests (single run, no
   watch mode) until green, plus full API suite once.
6. **Frontend** — TS client additions; `/recruiters/briefs` list + detail (requirements chips
   editor seeded from `InterpretationPanel`, pool grid reusing workspace cards with status
   pills, comparison tab, brief-scoped search mode of `RecruiterSearchView`); workspace nav
   gains Briefs; web unit tests.
7. **Verification gates (in order, before any deploy/migration)** — API suite green → web
   unit green → local rig e2e → migration review + RLS/privacy review → then (separate
   explicit step, not this session's default) production migration + deploy.
