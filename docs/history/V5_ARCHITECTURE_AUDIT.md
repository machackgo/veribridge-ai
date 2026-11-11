# RECRUITER V5 ARCHITECTURE AUDIT — Talent Pools + Saved Searches + Evidence-Aware Discovery

Date: 2026-08-19 · Branch `feat/recruiter-talent-pools-saved-searches-v5` @ base `63ad9ace`
(= origin/main incl. V4 pipeline, PR #87). Produced from three independent read-only audits
(API domain, web frontend, migrations/RLS/e2e) before any implementation.
This document is the **implementation contract** shared by the V5 work packages.

---

## AUDIT RESULTS (confirmed against the tree)

- Worktree `~/veribridge-recruiter-v5`, clean, branch tip = origin/main = `63ad9ace`. V4 merged.
- Migrations 001–069 contiguous; **NEXT MIGRATION NUMBER: 070** (verified free repo-wide).
- ONE canonical structured requirement representation exists and V5 reuses it verbatim:
  `app/services/recruiter_requirement_plan.py` (module docstring: "the ONE structured
  representation"; `PLAN_SCHEMA_VERSION=1`; `sanitize_plan` on EVERY load — stored plans are
  UNTRUSTED). Briefs persist it in `recruiter_hiring_briefs.plan`; search executes it
  (`search_candidates(db, plan=…)`); comparison/interview derive the requirement axis from it.
  **Saved Searches persist exactly this plan. No third requirement system.**
- `recruiter_search_index` (066): one row per human (`user_id` PK), refreshed **synchronously on
  publication-shaped events only** (passport publish/unpublish, disclosure mode/overrides/preset/
  reset, profile update, project report publish/unpublish — 9 caller sites in
  `vbr_work_passport.py` + `vbr_project_defense.py`). No cron, no queue, no revision column;
  staleness guards are `disclosure_version` + `passport_published_at` + `projected_at`.
- Fail-closed triple on every recruiter read: exclusions (067) + live `is_published` + live
  `disclosure_version` (`live_valid_index_rows`, and inline in search/evidence services).
- Acquisition-source convention: `recruiter_candidate_connections.source ∈
  (qr_scan, shared_link, search, role_match, direct)` mirrored at
  `recruiter_connection_service.py:46`. V5 extends this vocabulary (pools) with `saved_search`.
- Backend is service-role for ALL requests → app-level `recruiter_user_id` filtering is the
  tenancy boundary; RLS is defense-in-depth. Foreign==missing 404 everywhere.
- No background/notification runner exists (`notification_*` services are pull-triggered,
  admin-poked; Resend/SendGrid optional). **V5 does not add one** — discovery is evaluated
  lazily on recruiter reads (correctness > premature scale; V5 scope is in-product status only).
- Web: no shared recruiter nav (3-item pill nav hand-duplicated in Workspace/Search/Briefs
  views); no add-to-brief on global search; `EvidenceProofDrawer`/`RequirementRow` extracted and
  reusable; `recruiter-briefs-api.ts` `request<T>` + `BriefApiError` is the client pattern;
  `AUTH_REQUIRED_PATH_PREFIXES` in `src/lib/api.ts` must grow for new recruiter prefixes.
- Local rig: docker `e2e-supabase` (:54321) is UP with schema through 069. API :8000, web :3000.

## DESIGN DECISIONS (the "why" summary)

1. **Saved Search = named, persisted plan** — same `sanitize_plan` discipline as briefs.
   Plus a small closed `filters` jsonb (`skills[]`, `evidence[]`, `availability`) mirroring the
   explicit chips `search_candidates` already accepts as kwargs. No new requirement semantics.
2. **Results are ALWAYS computed live** (same engine, fail-closed). Persistence exists ONLY to
   answer "what is new/changed since I last reviewed" — a match row per (saved_search,
   candidate), created/updated/deleted by a deterministic reconciliation pass.
3. **Discovery = lazy re-evaluation on recruiter read.** No new infra. Evaluations run: on
   create (baseline), on saved-search detail open (always), on list open (only when stale,
   ≥5 min TTL, active searches only). Index freshness remains publication-driven — this is the
   trust model: discovery is over PUBLISHED evidence; a raw analysis change surfaces when the
   student (re)publishes. Document as known limitation, not a defect.
4. **Match rows persist EXACT matches only** (every hard requirement satisfied). Close/partial
   matches render live in a separate section (existing search semantics) but are never tracked —
   no thresholds, no scores. A plan with zero hard requirements (pure lexical/browse) is savable
   but untracked; UI says so honestly.
5. **No opaque scores anywhere.** Change events are per-requirement fingerprint diffs of the
   deterministic evaluation rows. Reason text is reconstructed live from plan + evaluation,
   never persisted prose.
6. **Talent Pools = recruiter-owned candidate collections keyed by stable `student_user_id`.**
   No copied candidate data; identity is resolved live via `_candidate_summary` (consented,
   unpublish-goes-dark) + `live_valid_index_rows` for evidence context. Pools never auto-link
   to briefs; both directions are explicit recruiter actions.

---

## MIGRATION 070 — `070_recruiter_talent_pools_saved_searches.sql`

Additive, idempotent, house style (069 as template). All new tables: RLS enabled, owner policies
for `authenticated` (`::text = (select auth.uid())::text` pattern), `service_role` all, students
NO policy, `set_updated_at` triggers where `updated_at` exists, `notify pgrst, 'reload schema'`,
manual rollback footer. Length caps app-side only.

1. **`recruiter_talent_pools`** — `id uuid pk gen_random_uuid()`, `recruiter_user_id uuid not
   null → users cascade`, `name text not null`, `description text`, `status text not null
   default 'active' check in ('active','archived')`, `created_at/updated_at` + trigger.
   Index `(recruiter_user_id, updated_at desc)`. RLS: own rows all + service_role.
2. **`recruiter_talent_pool_candidates`** — `pool_id → recruiter_talent_pools cascade`,
   `student_user_id → users cascade`, `source text not null default 'direct' check in
   ('qr_scan','shared_link','search','role_match','direct','saved_search')` (065 vocabulary +
   `saved_search`), `note text` (recruiter-private, ≤4000 app-side), `added_at`.
   PK `(pool_id, student_user_id)` (idempotent membership by construction).
   Index `_student_idx (student_user_id)`. RLS: own-pool EXISTS all + service_role.
3. **`recruiter_saved_searches`** — `id uuid pk`, `recruiter_user_id → users cascade`,
   `name text not null` (≤120 app-side), `query_text text` (original NL query, ≤320 app-side =
   MAX_QUERY_LENGTH), `plan jsonb not null default '{}'` (THE canonical plan, UNTRUSTED on
   load), `filters jsonb not null default '{}'` (closed shape: skills[]≤10 / evidence[] ⊂
   EVIDENCE_FILTERS / availability ∈ closed vocab — sanitized on every load),
   `status text not null default 'active' check in ('active','paused')`,
   `last_evaluated_at timestamptz`, `last_reviewed_at timestamptz`, `created_at/updated_at` +
   trigger. Index `(recruiter_user_id, updated_at desc)`. RLS: own rows all + service_role.
4. **`recruiter_saved_search_matches`** — `saved_search_id → recruiter_saved_searches cascade`,
   `student_user_id → users cascade`, PK `(saved_search_id, student_user_id)` — ONE HUMAN → ONE
   MATCH ROW by construction. `requirement_fingerprints jsonb not null default '{}'`
   ({axis_key → 16-hex content hash of that requirement's deterministic evaluation row}),
   `evidence_fingerprint text not null default ''` (overall hash), `last_event text not null
   default 'new_match' check in ('new_match','evidence_updated')`, `changed_requirement_keys
   jsonb not null default '[]'`, `first_matched_at timestamptz not null default now()`,
   `last_change_at timestamptz not null default now()`, `last_evaluated_at timestamptz not null
   default now()`. Index `(saved_search_id, last_change_at desc)`, `_student_idx`.
   RLS: own-saved-search EXISTS all + service_role. NEVER stores prose, identity, or evidence
   content — hashes, keys, timestamps only (privacy: even a leaked row reveals nothing public).

Apply script `apps/api/scripts/apply_070_talent_pools_saved_searches.py` — copy of 069's
(URL-decoded password, pooler ladder, per-file commit, NOTIFY) with fresh docstring/prints.
**Written but NOT run against prod in this phase.** Applied to the LOCAL rig only, after review.

## BACKEND — new modules

### `app/services/recruiter_talent_pool_service.py`
Dual-mode (dict | Supabase service-role). Constants: `MAX_TALENT_POOLS = 40`,
`MAX_POOL_CANDIDATES = 200`, `MAX_POOL_NAME = 120`, `MAX_POOL_DESCRIPTION = 600`,
`MAX_NOTE_LENGTH = 4000`, `POOL_STATUSES = ("active","archived")`,
`POOL_CANDIDATE_SOURCES = {"qr_scan","shared_link","search","role_match","direct","saved_search"}`
(comment: superset of 065's CONNECTION_SOURCES + saved_search; keep in sync with 070 CHECK).
Errors: `PoolError(code, message)` / `PoolNotFound` mirroring `BriefError` exactly.
Functions (mirror brief service craft: `_now_iso`, ownership filter on EVERY query,
unique-violation race recovery, `make_json_safe`):
- `create_pool(db, recruiter_user_id, *, name, description=None)` → pool view; cap check
  `too_many_pools`; name required (`invalid_name`).
- `list_pools(db, recruiter_user_id)` → `{pools:[pool view + candidate_count], total}` newest
  updated first. candidate_count via one batched membership read (no N+1).
- `get_pool(db, recruiter_user_id, pool_id)` → pool view (404 pattern: foreign==missing).
- `update_pool(db, …, *, name=…, description=…, clear_description=False, status=…)` —
  `...`-sentinel partials; status validated.
- `delete_pool(db, …)` — deletes pool (membership cascades). Never touches connections/briefs.
- `add_pool_candidates(db, …, pool_id, *, candidate_slugs=None, connection_ids=None,
  student_user_ids=None, source="direct")` — resolution mirrors `add_brief_candidates`:
  slugs → actively published passports; connection_ids → recruiter's OWN connections;
  student_user_ids → accepted ONLY when that id is already visible to this recruiter (own
  connection OR member of one of the recruiter's own pools/briefs) — used by saved-search flow;
  otherwise `candidate_not_found`. Idempotent (`already_in_pool` skip), cap check, race
  recovery. Records analytics.
- `update_pool_candidate(db, …, *, note=…, clear_note=False)` — private note.
- `remove_pool_candidate(db, …)` — 404 when absent.
- `list_pool_candidates(db, …)` → `{pool, candidates:[…], total}` where each candidate =
  `{student_user_id, source, note, added_at, candidate: _candidate_summary(db, uid),
  evidence: <light index context> | None}`; evidence from ONE batched
  `live_valid_index_rows(db, uids)` call: `{skill_count, project_count, evidence_flags,
  top_skills: [≤6 display names], public_slug}` — None when not live (fail-closed; identity
  card then shows the connection-service "no longer published" treatment).
- `pool_memberships(db, recruiter_user_id, student_user_ids)` → {uid: [pool ids]} for pickers.
Reuses: `_candidate_summary` (connection service), `live_valid_index_rows` (comparison
service), `_read_with_transient_retry`, `record_search_event` for analytics.

### `app/services/recruiter_saved_search_service.py`
Constants: `MAX_SAVED_SEARCHES = 20`, `MAX_SAVED_SEARCH_NAME = 120`,
`EVALUATION_TTL_MINUTES = 5`, `MAX_MATCH_ROWS = 200`, `SAVED_SEARCH_STATUSES =
("active","paused")`. Errors `SavedSearchError`/`SavedSearchNotFound` (same craft).
- `sanitize_filters(filters)` → closed shape (skills ≤10 strings, evidence ⊂ EVIDENCE_FILTERS,
  availability ∈ AVAILABILITY vocab or None). UNTRUSTED on every load, like the plan.
- `create_saved_search(db, recruiter_user_id, *, q, name=None, filters=None)` —
  `plan = parse_recruiter_query(q, MAX_QUERY_LENGTH)` then `sanitize_plan`; default name derived
  like `default_brief_title` (role display / required displays / truncated q). Cap
  `too_many_saved_searches`. Then **initial evaluation** seeds match rows and sets
  `last_reviewed_at = now` (baseline: the recruiter is looking at these results right now —
  nothing is "new" at creation). Returns detail view.
- `list_saved_searches(db, recruiter_user_id)` → `{saved_searches:[list item], total}`.
  For each ACTIVE search with `last_evaluated_at` older than TTL (or null): run
  `evaluate_saved_search` first (bounded: ≤ MAX_SAVED_SEARCHES per recruiter). List item =
  `{id, name, query_text, status, requirements: requirements_view(plan), tracking: bool
  (hard requirements exist), new_count, updated_count, match_count, last_evaluated_at,
  last_reviewed_at, created_at, updated_at}`. Paused → counts omitted (null) + status shown.
- `get_saved_search_results(db, recruiter_user_id, saved_search_id, *, page=1)` — always
  evaluates first when active (paused: NO match reconciliation, live results still shown).
  Returns `{saved_search: list item, results, total, exact_total, close_total, page, page_size,
  has_more, interpretation, annotations: {public_slug → {is_new, evidence_updated,
  changed_requirements: [display names], first_matched_at}}}` — results verbatim from
  `search_candidates(db, plan=plan, skills=…, evidence=…, availability=…, page=…)`;
  annotations computed by joining match rows (slug↔user_id via one index read) against
  `last_reviewed_at`: `is_new` = new_match AND last_change_at > last_reviewed_at;
  `evidence_updated` analogous.
- `update_saved_search(db, …, *, name=…, status=…, q=…, filters=…)` — editing `q`/`filters`
  re-parses/re-sanitizes, **wipes match rows**, re-evaluates, resets `last_reviewed_at = now`
  (a changed search must not fake "new" candidates). Pause/resume via status; resume triggers
  evaluation.
- `mark_reviewed(db, …)` → sets `last_reviewed_at = now`; returns refreshed list item.
- `delete_saved_search(db, …)` — match rows cascade. Never deletes candidates/pools/briefs.
- **`evaluate_saved_search(db, recruiter_user_id, saved_search_row)`** — the deterministic
  reconciliation core (pure Python over engine output; identical dict/Supabase):
  1. `plan = sanitize_plan(row["plan"])`; if no hard requirements → delete any match rows,
     stamp `last_evaluated_at`, return (untracked).
  2. `res = search_candidates(db, plan=plan, skills/evidence/availability from sanitized
     filters, page=1, page_size=MAX_MATCH_ROWS)`; keep `match_type == "exact"` cards only.
     If `exact_total > MAX_MATCH_ROWS` log + expose `truncated: true` (no silent caps).
  3. Map result slugs → user_ids via one index read (slug unique). Cards whose slug no longer
     resolves are skipped (fail-closed).
  4. Per candidate: `requirement_fingerprints = {axis_key(kind, requirement):
     sha256(canonical_json(requirement_row))[:16]}` over the card's `requirements` rows
     (kind/requirement/satisfied/via/matched_label/skill_status/evidence_sources/
     project_titles — the deterministic evidence-relevant projection);
     `evidence_fingerprint = sha256(canonical_json(sorted fingerprints))`.
  5. Diff vs stored rows: absent → insert (`new_match`, first_matched_at=last_change_at=now);
     present + fingerprint changed → update (`evidence_updated`,
     `changed_requirement_keys = keys whose hash changed or appeared`, last_change_at=now);
     present + unchanged → touch `last_evaluated_at` only (NO last_change_at bump).
     Stored rows not in the live exact set → DELETE (no longer satisfies / unpublished /
     excluded / non-discoverable — fail-closed removal; re-appearing later = honestly new).
  6. Stamp `last_evaluated_at` on the saved search.
  Axis key format matches comparison: `"concept:" + "|".join(group)` / `f"evidence:{key}"`.
- Analytics via `record_search_event(db, recruiter_user_id, q=query_text[:320],
  filters={"saved_search": action}, result_count=n)` — actions: created / opened / paused /
  resumed / reviewed / deleted / evaluated(zero_results flag). Counts + recruiter-authored text
  only; NEVER candidate identity/evidence content (existing discipline).

### Schemas + routers
`app/schemas/recruiter_talent_pools.py`, `app/schemas/recruiter_saved_searches.py` —
`extra="forbid"` everywhere, closed Literals, `...`-sentinel partial-update models mirroring
`recruiter_hiring_briefs.py` (use `model_fields_set`).
`app/api/v1/endpoints/recruiter_talent_pools.py` mounted at **`/recruiter/pools`**;
`app/api/v1/endpoints/recruiter_saved_searches.py` at **`/recruiter/saved-searches`**
(router.py, after recruiter_interviews). All routes `Depends(get_current_user_id)`
(+ `get_provisioned_user_id` on the two POST creates, like brief create), `db=Depends(get_db)`,
`_not_found()` 404 for foreign==missing, error mapping `PoolError/SavedSearchError.code` →
`{"detail": {"code", "message"}}` exactly like briefs (web `BriefApiError` pattern relies on it).

Routes:
```
POST   /recruiter/pools                                  create
GET    /recruiter/pools                                  list (+candidate_count)
GET    /recruiter/pools/{pool_id}                        detail + candidates
PATCH  /recruiter/pools/{pool_id}                        name/description/status
DELETE /recruiter/pools/{pool_id}
POST   /recruiter/pools/{pool_id}/candidates             add (slugs|connection_ids|student_user_ids, source)
PATCH  /recruiter/pools/{pool_id}/candidates/{uid}       note
DELETE /recruiter/pools/{pool_id}/candidates/{uid}
GET    /recruiter/pools/memberships?student_user_ids=…   picker support (define BEFORE /{pool_id})
POST   /recruiter/saved-searches                         create {q, name?, filters?}
GET    /recruiter/saved-searches                         list (lazy evaluation)
GET    /recruiter/saved-searches/{id}                    detail + live results + annotations
PATCH  /recruiter/saved-searches/{id}                    name/status/q/filters
POST   /recruiter/saved-searches/{id}/review             mark reviewed
DELETE /recruiter/saved-searches/{id}
```
(Route-order note: static segments `memberships` must be declared before `/{pool_id}`.)

## FRONTEND — new/changed surface

### Shared first
- **Extract `components/recruiter/RecruiterNav.tsx`**: items Saved candidates(/recruiters/
  workspace) · Search(/recruiters/search) · Hiring Briefs(/recruiters/briefs) · Talent Pools
  (/recruiters/pools) · Saved Searches(/recruiters/saved-searches). Props `{active, testidPrefix}`
  → testids `${prefix}-nav-${key}` preserving EVERY existing testid
  (`workspace-nav-search`, `search-nav-briefs`, `briefs-nav-workspace`, …; active item stays a
  `<span aria-current="page">`). Replace the three hand-rolled navs; add to new pages
  (prefixes `pools`, `savedsearches`). Existing unit/e2e assertions must stay green.
- **API clients**: `src/lib/recruiter-pools-api.ts`, `src/lib/recruiter-saved-searches-api.ts`
  — follow `recruiter-briefs-api.ts` exactly (`request<T>` on `fetchAPI`, 401→`AuthRequiredError`
  (re-export from connections client), non-OK→code-carrying error class; reuse/subclass
  `BriefApiError`-style `PoolApiError`/`SavedSearchApiError`). Add `/api/v1/recruiter/pools`
  and `/api/v1/recruiter/saved-searches` to `AUTH_REQUIRED_PATH_PREFIXES` in `src/lib/api.ts`.
- **`components/recruiter/AddToListButtons.tsx`**: `AddToPoolButton` + `AddToBriefButton`
  (lazy-load pickers on open; pool picker shows existing membership ✓s via memberships endpoint
  or listing payload, offers inline "New pool…" name input; brief picker lists briefs →
  `addBriefCandidates(briefId, {candidate_slugs:[slug]})`). Explicit recruiter action only —
  never auto-add. Used on saved-search result cards, pool detail (brief button), and the global
  search `ResultCard` action row.

### Pages (server-side auth gate = existing 5-line pattern)
- `/recruiters/pools` → `PoolsListView`: create form (name ≤120 + optional description),
  pool cards (name, description, candidate count, updated, archived badge), archived section
  collapsed/labelled. Empty state: 🗂 "Create a Talent Pool to organize candidates across
  roles." Testids `pools-*` (`pools-create-name`, `pools-create-submit`, `pool-card`, …).
- `/recruiters/pools/[poolId]` → `PoolDetailView`: header (name, inline edit, description,
  status archive/restore, delete w/ confirm), candidate grid (auto-fill minmax(min(100%,340px)))
  — each card: consented identity, source label (reuse SOURCE_LABEL map + "Saved search"),
  evidence context line (skill/project counts + top skills + evidence flags) when live,
  "No longer published" treatment otherwise, private note editor (brief-note pattern),
  Open Passport (only when published), `AddToBriefButton`, remove. Testids `pool-*`.
- `/recruiters/saved-searches` → `SavedSearchesListView`: rows/cards with name, original query
  (`query_text`), structured chips (reuse the interpretation-chip rendering over
  `requirements`), status pause/resume toggle, "Checked <relative>" line, **new/updated counts
  as badges** ("2 new", "1 updated evidence"), tracking-disabled note when no hard requirements
  ("Add a required skill or evidence type to track new candidates"), open → detail, delete
  (confirm; copy: deleting never removes candidates/pools/briefs). Empty state: 🔔 "Save a
  recruiter search to be notified when new published evidence satisfies your requirements."
  Testids `savedsearches-*`.
- `/recruiters/saved-searches/[searchId]` → `SavedSearchDetailView`: header (name inline-edit,
  original query, InterpretationPanel-style chips incl. residual-terms honesty line, status,
  last checked, **"Mark reviewed"** button, paused banner) + live results: EXACT section cards
  with **"New" / "Updated evidence: <requirement displays>" badges** from `annotations`
  (never a score; language: "New candidate satisfies all N required requirements" via counts
  line), full `RequirementRow` per-requirement rows + View Proof (reuse EvidenceProofDrawer
  kit), actions: Open Passport · Save candidate (ResultSaveButton pattern) · AddToPoolButton ·
  AddToBriefButton. CLOSE section separate, labelled "Close matches — missing requirements
  shown" (live only, no tracking badges). Empty states: no matches yet → "No published
  evidence-backed candidates satisfy this search yet."; zero new → "No new evidence-backed
  candidates since your last review." Testids `savedsearch-*`.
- **Search page**: "Save search" `Btn` beside the interpretation panel once a query has run
  (`search-save-search`); opens inline card: name input (prefilled from role/required
  displays), the structured interpretation summary ("This saved search will track: …" +
  residual-terms honesty + "not tracked" note when no hard requirements), Save →
  `createSavedSearch({q, name, filters})` (filters = current explicit chips: evidence/
  availability UI state) → success line + link "View saved search →". Also add
  `AddToPoolButton`/`AddToBriefButton` to `ResultCard` action row (compact).

### Language invariants (enforced in components + tests)
"Published evidence supports X" / "No published X evidence found" / counts like "Satisfies all
4 required requirements". NEVER "knows/weak/fit/score/%". Semantic similarity never claimed as
proof. Absence of evidence ≠ absence of skill.

## PRIVACY / RLS (hard gate)

- All 4 new tables: RLS owner/owner-via-parent + service_role, students NO policy (070).
- App layer: every service function takes `recruiter_user_id` and filters on it (or resolves
  ownership via the parent pool/saved-search row) on EVERY query — same boundary as briefs.
- Tests: recruiter-B 404/absence on every verb for every new resource; student token cannot
  read/write recruiter V5 data through any surface; anonymous 401 (both new prefixes are in
  AUTH_REQUIRED_PATH_PREFIXES client-side AND `get_current_user_id` server-side);
  public passport payload builders never reference the new tables (grep + test);
  match rows store hashes/keys/timestamps only — no candidate prose (asserted).
- Live-JWT RLS probes (local rig): new script `apps/api/scripts/probe_070_rls.py` (mint real
  tokens via `POST /auth/v1/token?grant_type=password` with anon key; PostgREST asserts:
  recruiter A sees own rows, recruiter B sees zero, student sees zero, anon sees zero, on all
  4 tables). Run against the local rig as part of the RLS gate.

## PERFORMANCE

- List pools: 2 reads (pools + batched membership counts). Pool detail: pool + memberships +
  ONE `live_valid_index_rows` batch + per-uid `_candidate_summary` (bounded by
  MAX_POOL_CANDIDATES=200; acceptable at current scale — same pattern as connections listing).
- Saved-search evaluation: one `search_candidates` (trigram-prefiltered, `_MAX_CANDIDATE_POOL`
  bounded) + one slug→uid read + one match-rows read + bounded writes-on-change. List view:
  ≤20 evaluations only when stale (5-min TTL), typically 0. Detail: exactly 1.
- Index reuse: no pgvector, no new index infrastructure; 070 adds only btree indexes for the
  new access paths.

## WORK PACKAGES

- **WP1 backend agent**: services + schemas + routers + router mounts + tests (pools CRUD/
  membership/idempotency/isolation/multi-pool; saved-search CRUD/pause/resume/parse-reuse/
  match lifecycle: new candidate appears → new_match, index row evidence change → evidence_
  updated with changed keys, unpublication/disclosure bump/exclusion → row deleted, delete
  search keeps candidates; no-hard-requirements untracked; adversarial: prompt-injection
  strings in project titles/traces stay data; "%"-sweep on new payloads; analytics privacy
  sweep). Touches ONLY `apps/api/**` (migration 070 + apply script are pre-written by
  orchestrator; do not edit).
- **WP2 frontend agent**: nav extraction + clients + api.ts prefixes + 4 new views + search-page
  save/add actions + vitest suites (list/detail/empty/paused/badges/save-flow/pickers/
  accessibility roles/labels). Touches ONLY `apps/web/**` (not e2e specs).
- **Orchestrator**: migration 070 + apply script + local apply, integration, full suites,
  typecheck/build, RLS probes, e2e-local V5 spec, browser QA desktop + iPhone 13, gates,
  report. Production untouched until explicit authorization.

## REGRESSION GUARDS

V1–V4 surfaces untouched except: search view (additive Save/Add controls), the three nav
replacements (testids preserved), api.ts prefix list (additive), router.py mounts (additive).
Full `pytest` + `npm test` + typecheck + build + existing e2e-local suites are the gate.

## KNOWN LIMITATIONS (honest, by design)

- Discovery latency = when the recruiter next loads a V5 surface (no background runner) AND
  index freshness remains publication-driven (raw evidence analysis changes surface on next
  publish/disclosure/profile touch). Email/push alerts: future work (delivery service exists,
  pull-triggered).
- Close matches are never tracked as events (no thresholds by design).
- `filters` are saved-search-local; the brief plan remains filter-free (unchanged).
