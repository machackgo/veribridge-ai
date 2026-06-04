# Individual Proof Architecture (Phase 3 Proposal — Design Only)

Status: **Proposed**. Not yet implemented. This document describes the target
architecture for individual proof sources and the evidence aggregator. It builds
on the code that already exists today and proposes the smallest set of additions
to make every proof type pluggable and consistent.

> Scope note: This is a design proposal per the Phase 3 request. The only code
> shipped alongside it is the source-card consistency fix (all final-evaluator
> loaders are now dict-store-aware) and expanded test coverage. The normalized
> evidence object and aggregator interface below are a forward plan, not a
> rewrite of the working pipeline.

---

## 1. Goals

1. Each proof source produces the **same normalized evidence object shape**, so
   the aggregator and UI never special-case a source.
2. The Final Evidence Score and Detected Skill Profile are derived from one
   aggregation pass over normalized evidence — never from per-section ad-hoc state.
3. A source that produced analyzed evidence is **never reported as `not_run`**.
4. Scoring is **project-type aware through source applicability**, not through
   per-project magic numbers (see §5).
5. New proof types (API, dataset, deployment, notebook, demo video) plug in by
   implementing one interface — no aggregator changes.

---

## 2. What already exists (do not rebuild)

| Concern | Current home |
|---|---|
| Website/workflow timeline analysis | `extension_proof_workflow_analysis_service.py` |
| GitHub code evidence + file/line traceback | `extension_proof_github_analysis_service.py` |
| Qwen visual reasoning (per-frame JSON) | `visual_reasoning_service.py` |
| OCR / keyframe evidence | `workflow_visual_analysis_service.py` |
| Project Defense transcript/NLP | `project_defense_analysis_service.py` |
| Document / PDF / report evidence | `optional_evidence_service.py` |
| Live website check | `live_website_check_service.py` |
| Aggregation → score, skills, recommendations | `final_evidence_evaluator_service.py` |
| Normalized evidence object (partial) | `EvidenceObject` dataclass in the evaluator |

The evaluator **already aggregates** all sources into `grouped_skill_evidence`,
`evidence_source_breakdown`, `detected_capability`, and recommendations. The
proposal below formalizes the contract these services fulfill rather than
introducing a parallel system.

---

## 3. Normalized evidence object (target contract)

Every proof source emits a list of these. `EvidenceObject` in
`final_evidence_evaluator_service.py` is already ~90% of this shape; the plan is
to make it the **input** contract each source returns, not just an evaluator-internal
type.

```python
NormalizedEvidence = {
    "source_type":          str,   # website | github | project_defense | document | live_check | api | dataset | deployment | notebook | demo_video
    "evidence_type":        str,   # recording_keyframe | ocr_text | dom_text | qwen_visual | github_file | transcript_quote | document_snippet | live_response | api_response | ...
    "skill_name":           str,   # the claimed/detected skill this supports
    "snippet_or_observation": str, # recruiter-safe text (PII-masked)
    "file_path":            str | None,
    "line_start":           int | None,
    "line_end":             int | None,
    "timestamp":            float | None,   # seconds into recording, if applicable
    "page_number":          int | None,     # for documents
    "source_url":           str | None,
    "confidence":           "high" | "medium" | "low",
    "reason":               str,   # why this is evidence for the skill
    "recruiter_safe":       bool,  # false → never surfaced to recruiters
}
```

Privacy invariant: no raw frame paths, storage URLs, access tokens, or unmasked
PII ever appear in a normalized object. Each source is responsible for masking
before it returns (the OCR/Qwen services already do this).

---

## 4. Proof source interface (target)

```python
class ProofSource(Protocol):
    source_type: str

    def is_applicable(self, project_type: str, claimed_skills: list[str]) -> bool:
        """True when this source can meaningfully contribute for this project."""

    def collect(self, user_id: str, session_id: str) -> SourceResult:
        """Return analyzed evidence + a source-level status/score.
        MUST distinguish: not_run | not_available | analyzed(partial|pass) | failed.
        MUST NOT raise — return a failed/not_run result instead."""
```

`SourceResult` carries `status`, `score`, `weight`, `notes`, and
`list[NormalizedEvidence]`. This is exactly the information the evaluator already
computes per source today; the change is to **co-locate evidence collection with
status/score** so the two can never disagree (the root cause of the "section shows
evidence but card says not_run" bug class).

### Concrete sources (priority order)

1. **Website / Live App Proof** — workflow timeline + DOM + OCR + Qwen + keyframes.
2. **GitHub Repository Proof** — file/line code evidence (traceback preserved as-is).
3. **Project Defense Proof** — transcript NLP + ownership/clarity/depth dimensions.
4. **Document / PDF / Report Proof** — additive booster, never lowers score.
5. **Later:** API proof, dataset proof, deployment proof, notebook proof, demo-video proof.

---

## 5. Project-type-aware scoring (clarified model)

The system is project-type aware **through source applicability and source-level
adjustment**, not through per-project weight tables. This is intentional: it keeps
scores explainable and avoids "every project becomes high score."

```
final_score = weighted_avg( score(s) * weight(s)
                            for s in sources
                            if s.status not in {not_run, not_available} )
            + small breadth bonus
            + additive optional-booster bonus (never subtractive)
```

Project type changes **which sources are applicable / how a source scores**, not
the global weights:

| Project type | Carries the proof | Naturally `not_run` (excluded) |
|---|---|---|
| 3D / WebGL | Qwen visual, GitHub code, live site | OCR (canvas is unreadable) |
| D3 / data-viz | DOM labels, OCR axis/legend, GitHub, document | — |
| Chatbot / NLP / LLM | chat UI + input/prompt/response, Qwen, transcript, GitHub | heavy graphics OCR |
| ML demo | input→prediction/training/inference, GitHub, transcript | — |
| Backend / API | endpoint response, repo API code, docs, transcript | visual/Qwen |

Because excluded sources drop out of the weighted average (rather than scoring 0),
a WebGL project is **not penalized** for unreadable OCR, and a backend project is
not penalized for absent visual evidence. Partial evidence yields partial scores;
nothing is auto-elevated. (Already implemented: `_adjust_chatbot_workflow_score`,
`_is_visual_graphics_skill` OCR exemption, Qwen chatbot partial scoring,
`not_run`/`not_available` exclusion in `_combine_scores`.)

---

## 6. Aggregator flow (target)

```
sources = [WebsiteProof, GitHubProof, ProjectDefenseProof, DocumentProof, LiveCheckProof, ...]
results = [s.collect(user, session) for s in sources if s.is_applicable(project_type, skills)]

evidence       = flatten(r.normalized_evidence for r in results)
grouped_skills = group_by_skill_then_category(evidence)          # single source of truth
final_score    = combine(results)                                # §5
confidence     = confidence_label(final_score, len(run_results))
recommendations = proof_repair(results) if final_score < 80
                  else project_growth(project_type)
→ Detected Skill Profile (now)
→ Student Profile (later)
→ Work Passport (later)
```

UI contract: individual modules show **evidence details + that source's
score/status only**. The grouped skill evidence is the **single** skill summary.
Per-section skill lists are removed (done for Workflow + Qwen sections).

---

## 7. Migration path (incremental, low-risk)

1. **Done now:** all evaluator loaders read the dict store consistently; endpoint
   integration tests pin source-card ↔ section parity.
2. **Next:** extract a thin `ProofSource` adapter around each existing service
   (no behavior change) that returns `SourceResult` with normalized evidence.
3. **Then:** the evaluator consumes `SourceResult`s instead of re-deriving status
   from raw rows — eliminating the status/evidence disagreement class entirely.
4. **Later:** add API / dataset / deployment / notebook / demo-video sources by
   implementing the interface; aggregator untouched.

No step requires re-enabling Live Tutor, Scan Website, or Guided Overlay, and none
touches GitHub traceback, document upload, or Project Defense transcript logic.
