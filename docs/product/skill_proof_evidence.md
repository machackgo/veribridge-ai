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

## API Endpoints

All endpoints are under `/api/v1` and are scoped to the authenticated user.

- `GET /student/skill-evidence` lists the current user's evidence.
- `POST /student/skill-evidence` creates evidence and runs mock verification.
- `GET /student/skill-evidence/{evidence_id}` returns one evidence record for the current user.
- `PUT /student/skill-evidence/{evidence_id}` updates one evidence record and reruns mock verification when relevant fields change.
- `DELETE /student/skill-evidence/{evidence_id}` deletes one evidence record.
- `POST /student/skill-evidence/{evidence_id}/verify` reruns mock verification.

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

## Future Phase 2: GitHub/File Fetching

Phase 2 should fetch public GitHub files and supported linked artifacts, normalize file content, and store enough metadata to verify exact evidence locations. Private files must require explicit student permission before recruiter access.

## Future Phase 3: AI Verification + Highlighted Lines

Phase 3 should use AI verification to evaluate whether the evidence actually supports the selected skill. The recruiter viewer should show highlighted lines, confidence, and a concise explanation of why the evidence supports or does not support the skill.

## Future Recruiter Flow

The intended recruiter flow is:

1. Recruiter clicks a verified skill.
2. VeriBridge opens the exact evidence file or link.
3. Relevant lines or regions are highlighted.
4. AI explains why the evidence supports the skill.

## Privacy And Security

Users own their evidence. All API reads, writes, updates, deletes, and verification actions are scoped by `user_id`. Future recruiter access must respect student approval and privacy settings, especially for private uploads and non-public project artifacts.
