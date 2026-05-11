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

## Privacy And Security

Users own their evidence. All API reads, writes, updates, deletes, and verification actions are scoped by `user_id`. Future recruiter access must respect student approval and privacy settings, especially for private uploads and non-public project artifacts.
