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

## Privacy And Security

Users own their evidence. All API reads, writes, updates, deletes, and verification actions are scoped by `user_id`. Future recruiter access must respect student approval and privacy settings, especially for private uploads and non-public project artifacts.
