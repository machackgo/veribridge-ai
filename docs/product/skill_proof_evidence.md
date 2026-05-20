# Skill Proof Evidence

Skill Proof Evidence lets a student attach exact proof to a claimed skill. A proof record can point to a GitHub repository or file, portfolio link, certificate, report, design artifact, presentation, or other artifact, with optional file path and line range.

## Phase 1: Persistence + Mock Verification

Phase 1 stores Skill Proof Evidence in Supabase and runs a backend mock verifier. It does not fetch GitHub files, inspect private files, or call an AI model.

Saved fields:

- `id`
- `user_id`
- `skill_name`
- `evidence_type`
- `evidence_url`
- `repository_url`
- `file_path`
- `line_start`
- `line_end`
- `evidence_description`
- `verification_status`
- `verification_summary`
- `verifier_version`
- `created_at`
- `updated_at`

## Phase 2: Public GitHub File Reader

Phase 2 verifies public GitHub file evidence without requiring a GitHub API token. When a proof record has a GitHub `repository_url` or GitHub `evidence_url` plus `file_path`, the backend builds a `raw.githubusercontent.com` URL, fetches the file, optionally narrows inspection to the submitted line range, and checks for skill-specific code indicators.

Supported URL formats:

- `https://github.com/user/repo`
- `https://github.com/user/repo/`
- `https://github.com/user/repo/tree/main`
- `https://github.com/user/repo/blob/main/app/main.py`
- `https://raw.githubusercontent.com/user/repo/main/app/main.py`

Branch behavior:

- If the GitHub URL includes a branch, VeriBridge tries that branch first.
- Otherwise VeriBridge tries `main`, then `master`.
- GitHub API tokens are not used in Phase 2.

Line range behavior:

- If `line_start` and `line_end` are provided, VeriBridge inspects that selected range first.
- If no line range is provided, VeriBridge inspects the full file.
- If `line_start` is beyond the file length, verification returns `needs_review`.
- If `line_end` is beyond the file length, VeriBridge clamps the range to the last available line and notes the inspected range in the summary.

Limits:

- Public GitHub files only.
- Private repositories are not supported yet.
- Maximum fetched file size is 1 MB.
- Phase 2 checks deterministic code/content indicators only; it is not a semantic AI verifier.

## API Endpoints

All endpoints are under `/api/v1` and are scoped to the authenticated user.

- `GET /student/skill-evidence` lists the current user's evidence.
- `POST /student/skill-evidence` creates evidence and runs GitHub file verification when possible, otherwise mock verification.
- `GET /student/skill-evidence/{evidence_id}` returns one evidence record for the current user.
- `PUT /student/skill-evidence/{evidence_id}` updates one evidence record and reruns verification when relevant fields change.
- `DELETE /student/skill-evidence/{evidence_id}` deletes one evidence record.
- `POST /student/skill-evidence/{evidence_id}/verify` reruns GitHub file verification when possible, otherwise mock verification.

## GitHub File Verification Rules

The Phase 2 GitHub verifier returns `verifier_version = github-file-v1`.

- Python: verifies `.py` or `.ipynb` files, or content with Python indicators such as imports, functions/classes, pandas, NumPy, scikit-learn, Torch, TensorFlow, or FastAPI.
- Machine Learning / AI / Data Science: verifies ML code indicators such as scikit-learn, DecisionTree, RandomForest, regressions, `train_test_split`, `fit(`, `predict(`, models, TensorFlow, Keras, Torch, XGBoost, or LightGBM.
- RAG / LLM / GenAI: verifies OpenAI, Anthropic, LangChain, LlamaIndex, embeddings, vector stores, retrieval, prompts, Chroma, Pinecone, or FAISS.
- MLOps / FastAPI / Docker / Cloud: verifies FastAPI, Uvicorn, Docker, GitHub Actions, Cloud Run, deployment, Prometheus, Grafana, monitoring, or API indicators.
- SQL: verifies `.sql` files or SQL query/table keywords.
- JavaScript / TypeScript: verifies `.js`, `.jsx`, `.ts`, or `.tsx` files, or common JS/TS indicators such as imports, exports, functions, `const`, `let`, React, or Next.js.

If the public GitHub file is fetched and evidence is found, status is `verified` and the summary mentions the inspected lines or full file. If the file is fetched but the selected lines do not demonstrate the skill, status is `skill_usage_not_found`. If the file cannot be fetched or exceeds the size limit, status is `needs_review`.

## Mock Verification Rules

The Phase 1 verifier returns `verifier_version = mock-v1`.

- Python: verifies when the skill contains Python and the file path ends in `.py` or `.ipynb`.
- Machine Learning / AI / Data Science: verifies when the skill is ML-related and the file path is Python/notebook, or the description contains ML keywords such as model, decision tree, random forest, regression, classification, neural network, training, prediction, sklearn, PyTorch, TensorFlow, XGBoost, or LightGBM.
- JavaScript / TypeScript: verifies `.js`, `.jsx`, `.ts`, and `.tsx` files.
- SQL: verifies `.sql` files.
- RAG / LLM / GenAI: verifies when RAG/LLM skills include file path or description keywords such as rag, llm, prompt, embedding, vector, LangChain, LlamaIndex, OpenAI, Anthropic, or retrieval.
- MLOps / Docker / FastAPI / Cloud / CI/CD: verifies when deployment, API, cloud, Docker, FastAPI, GitHub Actions, CI/CD, or monitoring keywords are present.
- Design / CAD: verifies Figma, CAD, DWG, SLDPRT, Revit/RVT, portfolio, prototype, or design evidence.
- Obvious mismatch: Python evidence using document or deck file paths without useful Python/ML/API context returns `skill_usage_not_found`.
- Insufficient data returns `pending_review`.

## Future Phase 3: AI Verification + Highlighted Lines

Phase 3 should use AI verification to evaluate whether the evidence actually supports the selected skill. The recruiter viewer should show highlighted lines, confidence, and a concise explanation of why the evidence supports or does not support the skill.

## Future Phase 4: Recruiter Evidence Viewer

The intended recruiter flow is:

1. Recruiter clicks a verified skill.
2. VeriBridge opens the exact evidence file or link.
3. Relevant lines or regions are highlighted.
4. AI explains why the evidence supports the skill.

## Phase 5D: Website Verification Executor Foundation

Phase 5D adds stored website verification runs for deployed website proof. A run takes a saved website verification plan, safely inspects the public HTML page, performs static checks, stores the run, and stores child check records for traceability.

The current executor is static/public-page only. It can:

- Load the latest or selected website verification plan.
- Fetch and inspect the public website HTML through the existing safe website inspection service.
- Record page title, meta description, headings, and a visible text excerpt.
- Check whether meaningful terms from the plan feature and expected output appear in static page content.
- Mark checks that require clicking, typing, selecting, form submission, or login as browser-required.
- Persist run status, summary, counts, page snapshot fields, raw executor notes, and per-check results.

The current executor cannot:

- Execute JavaScript-driven browser flows.
- Click buttons, type into forms, select dropdowns, or submit data.
- Use private login credentials.
- Capture screenshots.
- Make AI semantic judgments about behavior.
- Verify hidden, authenticated, or post-interaction states.

Run statuses:

- `static_verified`: static public-page content strongly matches the plan and no browser-only actions are required.
- `partial_verification`: static public-page content partially matches the plan.
- `failed_static_checks`: the site loaded but static checks did not find enough matching evidence.
- `needs_browser_execution`: the plan or page requires interactions such as clicking, typing, selecting, form submission, or login.
- `needs_review`: the plan is vague, unsupported, or needs human judgment before execution.
- `execution_error`: the public website could not be safely inspected.

Future roadmap:

- Phase 5E: Browser executor for safe public flows.
- Phase 5F: AI semantic evaluator over browser execution results.
- Phase 5G: Recruiter-readable website proof reports.

## Phase 5E: Safe Browser Verification Executor Foundation

Phase 5E adds a separate browser-run layer for deployed website proof. Browser runs build on saved website verification plans and attempt only bounded, public, non-destructive interactions that can be derived from structured plan fields.

The browser executor can:

- Open the submitted public website URL in a controlled Playwright browser context.
- Translate clear plan steps into safe actions such as navigate, fill, select, click, wait for text, and assert text present.
- Use only sample inputs supplied by the student in the verification guide/plan.
- Click only benign action targets such as analyze, generate, calculate, search, run, check, view result, next, or verify.
- Inspect the final page URL, title, and visible text snapshot.
- Store browser runs and per-step outcomes for traceability.

The browser executor has strict safety limits:

- Login-required flows are blocked and recorded as `blocked_by_login`.
- Localhost, private IPs, file URLs, and unsupported schemes are rejected before browser execution.
- Passwords, payment fields, tokens, OTPs, card data, or other sensitive values are not filled.
- Destructive or real-world action buttons such as delete, purchase, pay, buy, subscribe, send message, send email, confirm order, transfer, or submit application are not clicked.
- It does not bypass authentication, CAPTCHAs, paywalls, or bot protections.
- It does not run arbitrary page JavaScript.
- Screenshots and HTML snapshot storage fields exist for future use, but this phase stores a safe text snapshot only.

Browser execution statuses:

- `browser_verified`: navigation and safe required steps passed, and expected output appeared clearly.
- `browser_partially_verified`: some browser evidence appeared, but confidence remains partial.
- `browser_failed`: executable steps ran, but expected output was not found.
- `needs_human_review`: plan/page state is ambiguous or not detailed enough for safe execution.
- `blocked_by_login`: the plan or page requires authentication.
- `unsupported_plan`: the plan cannot be translated into safe browser actions.
- `execution_timeout`: execution exceeded bounded timeouts.
- `execution_error`: browser execution failed safely before enough page state was collected.

Future roadmap:

- Phase 5F: AI semantic evaluator over static and browser execution results.
- Phase 5G: Student-facing and recruiter-facing website proof verification UI.
- Phase 5H: Richer screenshot/report artifacts when storage and privacy rules are defined.

## Phase 5F: AI Semantic Website Verification Foundation

Phase 5F adds the semantic judgment layer for deployed website proof. A semantic result combines the student's claimed skill or feature, the website verification guide, the structured verification plan, the latest or selected static run, and the latest or selected safe browser run into a final verification judgment.

The semantic evaluator stores:

- `semantic_status`
- `confidence_score`
- `evaluator_provider`
- `evaluator_version`
- recruiter-facing summary
- evidence summary
- limitations
- recommended next action
- compact source snapshot

Semantic statuses:

- `verified`: browser execution completed, expected output signals were observed, and no major blocking warnings are present.
- `partially_verified`: supporting evidence exists, but not every expected step or signal was confirmed.
- `not_verified`: collected static and browser evidence did not demonstrate the claimed behavior.
- `needs_human_review`: signals are mixed, ambiguous, login-blocked, unsupported, or require judgment beyond safe automation.
- `insufficient_evidence`: a plan exists but static/browser evidence is missing or too sparse.
- `evaluation_error`: semantic evaluation failed due to an internal runtime issue.

The confidence score is a bounded `0.0000` to `1.0000` value. It reflects how strongly the structured evidence supports the semantic status, not a guarantee of product correctness. Verified results should generally be high confidence, partial results medium confidence, human-review and insufficient-evidence results lower confidence, and not-verified results confidence in the negative judgment.

The recruiter summary is intentionally concise and professional. It explains what VeriBridge observed without exposing internal implementation details or overstating what was proven. The source snapshot stores compact references to plan status, static run counts/status, browser run counts/status, final URL/title, a safe text excerpt, and selected step/check summaries. It does not store hidden chain-of-thought or large raw page content.

Current evaluator architecture:

- The service uses a `WebsiteSemanticEvaluatorProvider` interface.
- Phase 5F ships with `DeterministicMockWebsiteSemanticEvaluator`.
- No external Claude, OpenAI, Gemini, or other live LLM API is called.
- No API keys or model secrets are required.
- A future model-backed provider can replace the deterministic provider while preserving the same persisted result contract.

Limitations and ethical caution:

- Visible website behavior is not the same as full product correctness.
- Hidden backend logic, model accuracy, business correctness, production reliability, and data quality are not independently proven.
- Login-required or ambiguous flows should remain reviewable by a human.
- Semantic verification is currently based on structured evidence and deterministic logic, not live external model reasoning.

Future roadmap:

- Phase 5G: Student-facing website proof verification result UI.
- Phase 5H: Recruiter-facing proof report UI.
- Future: real LLM evaluator provider with auditable prompt/version controls.

## Phase 5F.1: Local Semantic Similarity Engine

Phase 5F.1 adds local NLP semantic similarity to the website proof verifier. It compares what the student claims or expects against what the static and browser verification layers actually observed.

Example:

- Claim: `This website recommends a safer route.`
- Observed output: `Alternative low-risk path available.`

Exact keyword matching may miss this because the wording is different. An embedding model converts each sentence into a meaning-vector: a list of numbers that represents the sentence's semantic content. Cosine similarity compares the angle between those vectors. If two vectors point in a similar direction, the texts likely mean similar things even when they use different words.

The current local engine uses Sentence Transformers with the CPU-friendly `sentence-transformers/all-MiniLM-L6-v2` model when it is available locally. It does not call Claude, OpenAI, Gemini, or any paid external LLM API. Model loading is lazy, and if the local model is not available, semantic verification falls back to the existing deterministic evaluator and records semantic similarity as unavailable.

Similarity labels:

- `strong_semantic_match`: score is `0.82` or higher.
- `moderate_semantic_match`: score is `0.68` to below `0.82`.
- `weak_semantic_match`: score is `0.50` to below `0.68`.
- `low_semantic_match`: score is below `0.50`.

Semantic similarity supports verification, but it does not decide the result alone. A strong similarity score can modestly raise confidence, and in some ambiguous but supportive cases it can help move evidence toward `partially_verified`. It should not override strong contradictory evidence, such as both browser execution and static checks failing.

VeriBridge stores only compact similarity metadata in `website_semantic_verification_results.source_snapshot`: availability, score, label, model name, and method. Embedding vectors are not stored in Postgres in this phase because they are bulky, model-specific, and not needed for the recruiter-facing audit trail.

## GitHub Proof Semantic Track - Phase G4: False-Positive Reduction Evaluation

Phase G4 evaluates whether GitHub capability matching actually improves trust. The guardrail from G3 is useful only if it blocks related-but-not-equivalent code without throwing away obvious true positives.

The evaluation compares four groups:

- Strong true positives: code that really shows the claimed capability.
- False-positive traps: code that is related, but does not prove the exact claim.
- Generic or incomplete code: imports, schemas, helper names, or setup without the proof step.
- Borderline cases: partially supportive code that should stay cautious.

In the curated evaluation harness, VeriBridge checked whether the guardrail preserved strong GitHub proof cases and blocked misleading ones. The strong cases stayed supported, and the traps stayed blocked. That is the behavior we want before we trust recruiter-facing proof reports.

Example:

- Claim: `I built and evaluated a machine learning classification model.`
- Code found: CSV loading, preprocessing, train/test split.
- Missing: model training, prediction, evaluation.
- Result: full verification should be blocked.

This phase does not change the product claim. It measures whether the capability matcher is reducing false positives while keeping legitimate proof visible and explainable.

## GitHub Proof Semantic Track: Phase G5 - Recruiter-Friendly GitHub Proof Report Foundation

Phase G5 turns the GitHub proof intelligence from the earlier phases into a clean recruiter-readable report object. The verifier already knows the claim, the semantic match result, the strongest supporting line ranges, the confirmed capabilities, the missing capabilities, and the confidence level. G5 packages that information into a report that the recruiter UI can render later without recomputing the underlying proof.

The report includes:

- the student claim
- the verification result
- the confidence level
- a concise recruiter-facing explanation
- the strongest supporting code line ranges
- confirmed capabilities
- missing capabilities, when applicable
- limitations and a recommended next action

Example:

- Claim: `I built and evaluated a Decision Tree classifier.`
- Lines 20-32: model training
- Lines 34-50: prediction
- Lines 52-61: evaluation
- Result: the selected code supports the claim

G5 does not add the recruiter UI yet. It creates the backend report foundation that future recruiter screens can show as summary cards, expandable evidence blocks, and exact line-level support views.

## GitHub Proof Semantic Track: Phase H1 - Direct Evidence Access And Recruiter Redirect Foundation

Phase H1 adds backend access links so a recruiter can inspect the original proof directly. VeriBridge already knows which code lines or website result are supporting the claim. H1 turns that into recruiter-safe links that future UI buttons can open.

Two direct access types are supported:

- GitHub exact line ranges for selected code evidence
- public live website URLs for deployed website proof

Example:

- Supporting range: `Lines 20-32: Model training`
- Generated action: `View Exact Code Lines`
- Direct URL: `https://github.com/user/project/blob/main/app/model.py#L20-L32`

For website proof:

- Generated action: `Open Live Website`
- Direct URL: the student’s public deployed app URL

H1 does not build the final recruiter buttons yet. It creates the backend link layer, persists it, and makes it easy for the future recruiter UI to open the original evidence in one click.

Future roadmap:

- Phase G6: recruiter evidence redirect and open-exact-lines support.
- Phase G7: recruiter-facing GitHub proof UI.

## Phase H2: Recruiter Evidence Access Buttons

Phase H2 surfaces the backend evidence links as recruiter-facing UI actions. The recruiter view does not rebuild GitHub URLs or website URLs in the browser. It consumes the backend-generated access link response and renders safe buttons that open the original proof in a new tab.

GitHub proof shows buttons such as:

- `View Exact Code Lines`
- `View Code Lines 20-32`

Website proof shows a button such as:

- `Open Live Website`

Example:

- GitHub supporting range: `Lines 20-32: Model training`
- Recruiter action: `View Exact Code Lines`
- Direct URL: `https://github.com/user/project/blob/main/app/model.py#L20-L32`

Website example:

- Recruiter action: `Open Live Website`
- Direct URL: the student’s public deployed app URL

This completes the first visible recruiter-access layer for direct proof inspection. Future UI work can reuse the same backend links to build richer proof report cards and redirect flows without duplicating URL logic in the frontend.

## Phase H3: Combined Project Evidence Actions UI

Phase H3 groups related GitHub and website proof actions into one recruiter-friendly project evidence area. H2 showed direct buttons on individual proof cards. H3 makes the recruiter experience cleaner by presenting the actions together when a project has both a code proof and a live deployed proof.

The combined UI supports three cases:

- GitHub + live website
- GitHub only
- website only

The website deployment is optional. VeriBridge does not assume every project has a live app, and the UI stays clean when only GitHub proof exists.

Example:

- Project: `Boston Accident Risk Rerouting`
- Actions: `View Code Lines 1653–1779` and `Open Live Website`

This helps a recruiter inspect both:

- the implementation evidence
- the deployed product experience

It also keeps the earlier H2 behavior intact on individual proof cards, so direct links remain available wherever a proof card is shown.

## Phase I1: Student Proof Submission UI Foundation

Before Phase I1, the student-facing `Add proof evidence` button was still a placeholder. The backend proof systems existed, but students could not create GitHub or website proof from the real Profile & Proof page.

Phase I1 replaces that placeholder with a working submission modal.

Students can now submit:

- GitHub code proof
- Website/live demo proof

Website proof remains optional. A student can submit GitHub only, website only, or both separately.

The GitHub form captures:

- skill name
- project or evidence title
- claim or evidence description
- GitHub repository URL
- file path
- start line
- end line

The website form captures:

- skill name
- project or evidence title
- live website URL
- feature to verify
- expected output
- verification steps

The modal submits through the existing backend API pipeline. After submission, VeriBridge refreshes the profile proof list so the new evidence is visible immediately.

This unlocks a real end-to-end project test through the app UI, including the Boston Accident Risk project flow.

## Phase I2: Recruiter View Real Proof Data Wiring

Phase I2 connects the recruiter proof panel to the real proof data created by the student submission flow. Before this phase, the recruiter page still showed demo-style proof links even though the backend was already storing real GitHub and website evidence.

That created a gap in end-to-end testing: the student profile showed the real Boston evidence cards, but the recruiter view still pointed at placeholder links such as `student-app.example.com` and demo GitHub URLs.

Phase I2 fixes that by reading persisted proof evidence and direct evidence access links from the backend, then grouping them into recruiter-friendly project bundles.

Example:

- Project: `Boston Smart Accident Risk and Rerouting System`
- Actions:
  - `View Code Lines 19–23`
  - `Open Live Website`

The buttons are now rendered from stored backend proof data instead of being hardcoded in the frontend. Prototype grouping uses exact normalized project title matching, which is enough for local validation. A future production model may use an explicit `project_id` or `evidence_bundle_id`.

## Phase I3: Verification Usability Calibration And Status Reconciliation

Phase I3 improves how proof verification statuses are presented to students and recruiters. The Boston end-to-end test showed that the verification pipeline was trustworthy, but the UI could be too review-heavy and sometimes mixed raw technical statuses with product-facing outcomes.

Those technical layers are still useful internally, but students and recruiters should see a cleaner product-facing status such as:

- Verified
- Supported with review
- Partially supported
- Not verified
- Pending analysis

Phase I3 adds a reconciliation layer that converts lower-level technical signals into a clearer product label and message. It keeps false-positive guardrails intact, but it reduces unnecessary discouragement when the evidence is materially supportive.

Example:

- Strong support: a complete GitHub machine learning workflow can be shown as `Verified`.
- Supportive but review-worthy: a real Boston proof can be shown as `Supported with review` when the evidence is meaningful but one deeper layer remains cautious.
- Weak or mismatched evidence: import-only or unrelated code still stays `Not verified`.

The student-facing proof cards now use clearer labels such as `Evidence accepted` or `Supported with review`, while recruiter-facing surfaces use similarly reconciled labels and messages. The backend also stores compact reconciliation metadata so future UI layers can render the same status consistently.

Future roadmap:

- Phase 5F.2: stronger local rerankers, classifiers, or self-hosted model providers for better semantic decisions.
- Future: versioned model/prompt evaluation records if a model-backed evaluator is introduced.

## Phase 5F.2: Semantic Similarity Smoke Test And Calibration

Phase 5F.2 adds a developer smoke-test script for the real local semantic similarity model. The script runs curated VeriBridge examples through `sentence-transformers/all-MiniLM-L6-v2`, prints cosine similarity scores, applies the current labels, and summarizes whether the examples look aligned with human expectations.

Semantic models output similarity scores, not final truth. Thresholds decide how those numeric scores become product signals such as `strong_semantic_match`, `moderate_semantic_match`, `weak_semantic_match`, or `low_semantic_match`. Calibration means testing realistic examples to see whether those thresholds behave sensibly before relying on them in product decisions.

The calibration set intentionally includes:

- Positive examples where different wording should still score high, such as safer route language versus low-risk path language.
- Medium examples that are related but less direct, such as visa-compatible jobs versus work authorization filters.
- Negative controls where the text should not support the claim.
- Tricky borderline examples that are close but not equivalent, such as accident risk prediction versus historical accident counts.

This makes the verifier more trustworthy because it checks both false negatives and false positives. A useful threshold should recognize real paraphrases without treating every topically related sentence as proof.

The smoke test is developer tooling only. It does not call external LLM APIs, does not store embeddings, and does not automatically change production thresholds. Future improvements may use larger calibration datasets, human-labeled examples, threshold tuning by evidence type, classifier/reranker models, or self-hosted model providers.

## Phase 5F.3: Minimum Detail Requirement For Semantic Verification

Phase 5F.3 adds input-quality guardrails for website verification guides. Short descriptions reduce semantic signal quality because the local embedding model has too little context to compare meaning reliably. Richer descriptions help VeriBridge understand the intended workflow and the visible result it should verify.

Website guide requirements:

- `feature_to_verify` must contain at least 20 words.
- `expected_output` must contain at least 8 words.

This is a product-quality guardrail, not an arbitrary form restriction. The feature description should mention what the user enters or clicks, what the website does, and what outcome should appear. The expected output should describe the visible result VeriBridge should look for after the flow succeeds.

Too short:

- `It shows safer route.`

Better:

- `After the user enters a source and destination, the website analyzes accident risk for the route and displays a safer rerouting recommendation.`

Valid expected output example:

- `A risk score card and safer route recommendation appear on the results section.`

Invalid expected output example:

- `Risk appears.`

## Phase 5F.4: Better Semantic Evidence Construction

Phase 5F.4 improves the text representation sent to the local semantic similarity engine. Embeddings compare the text we feed them. If that text is too short, incomplete, or missing execution context, the score can be weaker or misleading even when the underlying evidence is useful.

This phase creates richer semantic bundles:

- Claim bundle: combines the student's evidence description, `feature_to_verify`, `expected_output`, a compact version of normalized test steps, and sample inputs when they clarify the intended interaction.
- Observed evidence bundle: combines browser execution status, browser execution summary, browser step evidence, safe visible page text, static execution status, static summary, and passed static check signals.

Short pair:

- Claim: `This website recommends a safer route.`
- Observed: `Alternative low-risk path available.`

Enriched pair:

- Claim bundle: `The student claims this website analyzes route accident risk after a user enters source and destination locations, then recommends a safer alternative route.`
- Observed bundle: `During browser verification, VeriBridge entered source and destination inputs, clicked the analysis action, and observed a displayed risk score plus a safer route recommendation.`

This is an example of input representation in NLP. The embedding model has the same architecture and thresholds, but it receives a more complete description of the claim and the collected evidence. The observed bundle is result-aware: verified runs use success wording, failed runs say the expected result was not observed, login-blocked runs say the flow was blocked, and missing browser runs fall back to static evidence.

VeriBridge stores compact bundle previews and source-field provenance in `website_semantic_verification_results.source_snapshot`. It does not store large page dumps or embedding vectors.

## Phase 5F.5: Recalibration With Enriched Semantic Bundles

Phase 5F.5 recalibrates local semantic similarity after changing the input representation. When the verifier moves from short raw text pairs to richer claim and observed-evidence bundles, the model's score behavior can change. Calibration compares both versions side by side before making any production threshold decision.

The smoke-test workflow now evaluates each curated example twice:

- Raw score: original short claim text compared with original short observed text.
- Enriched score: claim and observed evidence bundles built with the same semantic construction logic used by production verification.

Safer-route example:

- Raw score: `0.4728`
- Enriched score: `0.6196`

This shows that better text representation can improve model signals without changing the embedding model. It also shows why thresholds should not be lowered casually: verification false positives are more damaging than missed automation, because they could overstate what a student actually demonstrated.

The calibration report groups expected high, medium, low, and tricky borderline examples. It checks whether enriched bundles improve true-positive alignment, whether they inflate low or borderline examples, and whether current thresholds still look trustworthy. The current production thresholds remain conservative unless a larger calibration set strongly justifies changing them.

## Phase 5F.6: Expected Output Matching And False-Positive Reduction

Phase 5F.6 adds a dedicated expected-output match guardrail. A website producing some output after a browser flow is not enough to verify the student's claim. VeriBridge now compares what the student said should appear against what static and browser verification actually observed.

Good match:

- Expected: `A risk score and safer route recommendation should appear.`
- Observed: `Risk Score: High. Safer route available.`

Bad match:

- Expected: `A risk prediction should appear.`
- Observed: `Historical accident counts displayed.`

These examples are topically related, but they do not prove the same capability. Prediction is not the same as historical display. Verification is not the same as upload. A generated result is not the same as successful input upload.

The expected-output matcher combines two signals:

- local semantic similarity between the expected output and observed output
- exact required output signals, such as `risk score`, `safer route`, `verification result`, `predicted label`, or `customized resume`

The result is stored compactly in `website_semantic_verification_results.source_snapshot` under `expected_output_match`. It includes the score, label, signal hits, missing signals, whether the match supports verification, and whether it blocks full verification. Large raw text and embedding vectors are not stored.

This layer reduces false positives by preventing `verified` when the browser flow completed but the output did not demonstrate the exact expected capability. In those cases, VeriBridge returns a more cautious semantic status such as `needs_human_review` and uses recruiter-facing wording that explains the observed output did not clearly match the claimed result.

## GitHub Proof Semantic Track - Phase G1

Phase G1 starts the GitHub proof semantic track with line-level code evidence segmentation. When a student submits a GitHub file and selected line range, VeriBridge now breaks that code into meaningful line ranges and adds a plain-English explanation for each segment.

Example:

- Lines 20-32: Decision Tree classifier creation and training
- Lines 34-50: Prediction and evaluation

This is the foundation for later GitHub semantic work. The system is not yet trying to decide whether the student's written claim fully matches the code. Instead, it is preparing the evidence into smaller, recruiter-friendly pieces that can be inspected directly. That makes it easier to build future semantic claim matching, code proof reports, and line-range redirect buttons.

Each segment is intentionally conservative. VeriBridge looks for signals such as model initialization, training, prediction, evaluation metrics, preprocessing, API routes, database logic, UI components, file I/O, and authentication logic. If the code is generic or the signals are weak, the segment summary stays cautious instead of overclaiming.

The GitHub verifier now attaches a compact `github_code_evidence_summary` to successful file-based evidence responses. That summary includes the overall code explanation and the detected line-level segments, preserving the absolute line numbers so recruiters can inspect the exact proof location later.

## GitHub Proof Semantic Track - Phase G2: Claim-to-Code Semantic Matching

Phase G2 compares the student's GitHub proof claim with the line-level code evidence summaries produced in Phase G1. The system does not read raw code only. It first turns the selected code into plain-English segment summaries, then compares those summaries with what the student said they built.

Example:

- Student claim: `I built and evaluated a Decision Tree classification model for stroke prediction.`
- Matched evidence:
  - Lines 20-32: classifier setup and training
  - Lines 34-50: prediction logic
  - Lines 52-61: evaluation metrics

If the claim and code summaries align, VeriBridge stores a semantic result that explains why the code supports the claim, which line ranges are strongest, and what the recruiter should inspect. This creates the foundation for recruiter-facing GitHub proof reports without jumping straight to a final UI redirect layer.

The claim-to-code match is intentionally conservative. It uses the student claim, the overall code summary, and the segment summaries plus detected signals. If the selected lines are generic or the claim is too broad, the result stays cautious instead of overclaiming verification.

## GitHub Proof Semantic Track - Phase G3: False-Positive Reduction Through Capability Matching

Phase G3 adds a capability guardrail on top of the G2 semantic match. Similar code is not always enough. VeriBridge now checks whether the selected code actually proves the exact capabilities the student claimed, not just whether it is topically related.

Example:

- Claim: `I built and evaluated a Decision Tree classifier.`
- Code found:
  - preprocessing
  - train/test split

That evidence is related to machine learning, but it does not clearly prove model training or model evaluation. In that case, VeriBridge keeps the result cautious instead of returning a full verification.

The capability matcher extracts requirement types from the claim, such as:

- model training
- model evaluation
- prediction inference
- data preprocessing
- API endpoint logic
- database writes
- authentication
- visualization

Then it compares those requirements against the segmented code evidence from Phase G1. If critical requirements are missing, the semantic result is downgraded or blocked from becoming fully verified. This reduces recruiter-facing false positives like:

- preprocessing without model training
- route definition without authentication
- API routes without database writes when database storage was claimed

The result remains line-level and explainable. VeriBridge stores which requirements were satisfied, which were missing, and which segment ranges provided support. That lets recruiters see both the positive evidence and the missing capability gaps in one place.

## Phase 5F.7: False-Positive Reduction Evaluation

Phase 5F.7 adds a repeatable developer evaluation for the expected-output guardrail introduced in Phase 5F.6. The goal is to check whether the guardrail actually reduces false-positive risk while still preserving strong true-positive cases.

False positives are dangerous in proof verification because they can mislead recruiters into believing a student demonstrated a capability that the website did not actually show. The evaluation compares strong true positives against misleading trap cases, generic-output cases, and borderline cases.

Example:

- Claim: `This app predicts accident risk.`
- Expected: `A risk prediction score should appear.`
- Observed: `Historical accident counts by city are displayed.`

These outputs are related to accidents, but they do not prove the same capability. Displaying historical counts is not the same as predicting risk. The Phase 5F.7 harness reports how semantic similarity alone might view the text as related, then shows how expected-output matching blocks or downgrades full verification when required output signals are missing.

The evaluation script prints per-scenario diagnostics, including semantic similarity score, expected-output match score, exact signal hits, missing signals, whether full verification should be blocked, and the final recommended interpretation. It also summarizes whether true-positive cases were preserved, false-positive traps were blocked or downgraded, generic outputs were blocked, and borderline cases stayed cautious.

This phase does not redesign production verification logic. It is a trust and measurement layer. Production logic should only change if the evaluation exposes a clear implementation bug or a larger calibration set justifies a conservative adjustment.

## Phase J1 — Recruiter Verified Skill Search Foundation

Phase J1 begins the candidate discovery engine. Recruiters can now search for proof-backed student candidates by skill name or keyword. The search is powered by real Skill Proof Evidence data — not hardcoded placeholder cards.

### What recruiters can do

A recruiter who searches "Machine Learning" sees candidate result cards backed by actual submitted proof evidence. Each card shows:

- candidate name and school/program
- matched skill names
- evidence source count (total and accepted)
- whether GitHub proof and live website proof are available
- the strongest matched project title
- a proof status label (Evidence Accepted / Pending Analysis)

Selecting a card opens a summary detail panel with skill list, proof stats, and project title.

### Example

Recruiter searches "Machine Learning":

→ Candidate result: Mohammed Mubashir Uddin Faraz · MS AI · WPI

- Matched skill: Machine Learning
- Evidence Accepted · 2 sources
- GitHub proof: yes (Boston Smart Accident Risk and Rerouting System)
- Live site proof: yes

### What is real in Phase J1

- The search bar is wired to the backend API `GET /api/v1/recruiter/candidates/search?query=...`.
- The backend queries the `skill_evidence` table across all students using the service-role client (which bypasses RLS).
- Results include real proof metadata: skill names, evidence counts, accepted/pending statuses, GitHub and website proof flags, and project titles from submission metadata.
- Student profiles are joined to add display name, school, degree, and major when available.
- Results are ordered by accepted evidence count (higher quality first).

### What remains demo/static in Phase J1

- The default dashboard state (before a search is submitted) still shows demo candidate cards (Maya Reyes, Jordan Kim, Arjun Singh, Leila Pham) and the demo CandidatePreview panel for illustration.
- The metric cards (2,847 active candidates, etc.) remain demo values.
- The pipeline board uses demo counts.

### Future phases

- Phase J3: richer candidate profile cards with proof depth scoring, company challenge signals, and talent pool filters.
- Phase J4: ranking, scoring, and filtering by proof confidence, school, graduation year, and visa status.

---

## Phase J2 — Recruiter Candidate Detail and Proof Drill-Down

Phase J1 made recruiter search real: typing a skill returns real proof-backed candidate cards from the live database. Phase J2 makes the selected candidate panel real: clicking a candidate loads a full backend proof payload so the recruiter can inspect their evidence.

### What was added

**Backend**

- `GET /api/v1/recruiter/candidates/{candidate_user_id}/detail` — new endpoint returning a `RecruiterCandidateDetailResponse`
- `RecruiterCandidateDetailService` — loads the student profile, all skill evidence, and persisted evidence access links for the candidate using the service-role client (same cross-user pattern as J1 search)
- Evidence is grouped by normalized project title. GitHub and website evidence for the same project title are combined into one project bundle.
- Access links are filtered to the latest generation and only `available` links are surfaced
- Recruiter-safe response: no raw snapshots, no internal debug fields

**Response schema (`RecruiterCandidateDetailResponse`)**

```
RecruiterCandidateDetailResponse
  candidate_id
  display_name
  school_name / degree / major
  proof_overview
    total_evidence_count
    accepted_evidence_count
    github_proof_count
    website_proof_count
    strongest_display_status
  verified_or_supported_skills[]
    skill_name, evidence_count, strongest_status_label
  proof_projects[]
    project_title
    status_label / status_code
    has_github_proof / has_website_proof
    recruiter_summary
    associated_skill_labels[]
    evidence_access_links[]
      id, label, url, access_type, source_type
      file_path, line_start, line_end, availability_status
```

**Frontend**

- `fetchRecruiterCandidateDetail(candidateId)` added to `api.ts`
- `RecruiterCandidateDetailResponse` and nested types added to `api.ts`
- `RecruiterOverview` now fetches candidate detail whenever `selectedResult` changes (auto-select or explicit click)
- Detail panel shows a loading indicator while fetching
- Detail panel shows a clean error message if the fetch fails
- After detail loads, the panel renders:
  - Candidate header (name, school/degree, proof status badge)
  - Proof overview stats (evidence counts, GitHub count, website count)
  - Verified skills list with evidence count per skill
  - Project evidence section with one card per grouped project
  - Direct evidence action links (exact GitHub lines, live website) from the real backend payload

### Example flow

```
Recruiter searches "Machine Learning"
→ Mohammed Mubashir Uddin Faraz card appears (real proof data)
→ Recruiter clicks the card
→ Detail panel fetches /api/v1/recruiter/candidates/{user_id}/detail
→ Boston Smart Accident Risk and Rerouting System project appears
→ "View Exact Code Lines" link → github.com/…/api.py#L19-L23
→ "Open Live Website" link → boston-accident-risk-api-qzr2qvsfqa-uc.a.run.app
```

### What remains demo/static

- The pre-search recruiter landing state (metric cards, demo pipeline board, demo CandidatePreview) remains demo/static. This is intentional — the real experience begins after a search.
- After a real search result is selected, the detail panel is fully powered by the new real backend endpoint.

### What comes next

- Phase J3: richer candidate profile cards with proof depth scoring and talent pool filters
- Phase J4: ranking, scoring engine, and marketplace-scale seeded datasets

## Privacy And Security

Users own their evidence. All API reads, writes, updates, deletes, and verification actions are scoped by `user_id`. Future recruiter access must respect student approval and privacy settings, especially for private uploads and non-public project artifacts.
