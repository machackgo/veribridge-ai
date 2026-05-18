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

## Privacy And Security

Users own their evidence. All API reads, writes, updates, deletes, and verification actions are scoped by `user_id`. Future recruiter access must respect student approval and privacy settings, especially for private uploads and non-public project artifacts.
