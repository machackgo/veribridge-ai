# CareerProof AI Backend API Plan

## Scope

This document defines the planned FastAPI backend architecture for the CareerProof AI student MVP. It is a planning artifact only; backend implementation should happen in later tasks.

The MVP backend should support:

- Student profile management
- Resume upload and parsing
- Job description capture
- Job matching
- Skill gap analysis
- Tailored resume generation
- Cover letter generation
- Application tracking

## 1. Backend Folder Structure

Planned location: `apps/api`

```text
apps/api/
  app/
    __init__.py
    main.py
    api/
      __init__.py
      deps.py
      v1/
        __init__.py
        router.py
        endpoints/
          __init__.py
          health.py
          profiles.py
          resumes.py
          jobs.py
          matching.py
          skill_gaps.py
          documents.py
          applications.py
    core/
      __init__.py
      config.py
      security.py
      logging.py
      errors.py
    db/
      __init__.py
      session.py
      base.py
      migrations/
    models/
      __init__.py
      student.py
      resume.py
      job.py
      match.py
      skill_gap.py
      generated_document.py
      application.py
    schemas/
      __init__.py
      common.py
      student.py
      resume.py
      job.py
      match.py
      skill_gap.py
      generated_document.py
      application.py
    services/
      __init__.py
      storage_service.py
      resume_parser_service.py
      matching_service.py
      skill_gap_service.py
      generation_service.py
      application_service.py
    integrations/
      __init__.py
      llm_client.py
      object_storage.py
    workers/
      __init__.py
      tasks.py
    tests/
      __init__.py
      test_health.py
      test_profiles.py
      test_resumes.py
      test_jobs.py
      test_matching.py
      test_skill_gaps.py
      test_documents.py
      test_applications.py
  alembic.ini
  pyproject.toml
  README.md
```

## 2. Core FastAPI Modules

### `app/main.py`

Creates the FastAPI application, configures CORS, mounts API routers, registers exception handlers, and exposes the OpenAPI schema.

### `app/api/deps.py`

Holds shared route dependencies:

- Current authenticated user
- Database session
- Pagination parameters
- File upload validation
- Request ID extraction

### `app/api/v1/router.py`

Combines all versioned endpoint routers under `/api/v1`.

### `app/core/config.py`

Loads environment-backed settings using Pydantic settings. This module should be the only place that reads raw environment variables directly.

### `app/core/security.py`

Handles authentication helpers, JWT validation, password hashing if needed later, authorization checks, and ownership validation utilities.

### `app/db/session.py`

Creates the database engine and request-scoped sessions.

### `app/models`

SQLAlchemy or SQLModel database models.

### `app/schemas`

Pydantic request and response schemas. Route handlers should return schema objects rather than raw ORM models.

### `app/services`

Business logic layer. API routes should stay thin and delegate resume parsing, matching, skill analysis, document generation, and tracker updates here.

### `app/integrations`

External service adapters for LLM APIs, object storage, email providers, or future ATS integrations.

### `app/workers`

Background task definitions for long-running operations such as resume parsing, matching, and document generation.

## 3. API Endpoints

Base path: `/api/v1`

### Health Check

```http
GET /health
```

Purpose: Confirm API and dependency readiness.

Response:

```json
{
  "status": "ok",
  "service": "careerproof-api",
  "version": "0.1.0",
  "checks": {
    "database": "ok",
    "storage": "ok"
  }
}
```

### Student Profile

```http
GET /students/me
PUT /students/me
```

Purpose: Read and update the authenticated student's profile.

Update request:

```json
{
  "first_name": "Aisha",
  "last_name": "Patel",
  "school": "State University",
  "major": "Computer Science",
  "graduation_year": 2027,
  "location": "Austin, TX",
  "target_roles": ["Software Engineer Intern", "Data Analyst Intern"],
  "target_industries": ["Technology", "Healthcare"],
  "skills": ["Python", "React", "SQL", "Git"],
  "portfolio_url": "https://example.com/aisha",
  "linkedin_url": "https://linkedin.com/in/aishapatel"
}
```

Response:

```json
{
  "id": "stu_01hx7z2q7n6k9yr2p3tn8r4m6f",
  "email": "aisha@example.com",
  "first_name": "Aisha",
  "last_name": "Patel",
  "school": "State University",
  "major": "Computer Science",
  "graduation_year": 2027,
  "location": "Austin, TX",
  "target_roles": ["Software Engineer Intern", "Data Analyst Intern"],
  "target_industries": ["Technology", "Healthcare"],
  "skills": ["Python", "React", "SQL", "Git"],
  "portfolio_url": "https://example.com/aisha",
  "linkedin_url": "https://linkedin.com/in/aishapatel",
  "created_at": "2026-05-07T15:00:00Z",
  "updated_at": "2026-05-07T15:10:00Z"
}
```

### Resume Upload

```http
POST /resumes
GET /resumes
GET /resumes/{resume_id}
DELETE /resumes/{resume_id}
```

Purpose: Upload and manage student resumes. Upload should accept `multipart/form-data`.

Upload form fields:

- `file`: PDF or DOCX file
- `label`: Optional display label
- `is_primary`: Optional boolean

Upload response:

```json
{
  "id": "res_01hx8019sj0gf99ht2gxyjwj6v",
  "student_id": "stu_01hx7z2q7n6k9yr2p3tn8r4m6f",
  "label": "Software Engineering Resume",
  "file_name": "aisha_resume.pdf",
  "content_type": "application/pdf",
  "file_size_bytes": 184220,
  "storage_key": "students/stu_01hx7z2q7n6k9yr2p3tn8r4m6f/resumes/res_01hx8019sj0gf99ht2gxyjwj6v.pdf",
  "status": "uploaded",
  "is_primary": true,
  "created_at": "2026-05-07T15:15:00Z"
}
```

### Resume Parsing

```http
POST /resumes/{resume_id}/parse
GET /resumes/{resume_id}/parse-result
```

Purpose: Extract structured profile, education, experience, project, and skill data from a resume.

Parse request:

```json
{
  "force_reparse": false
}
```

Parse response:

```json
{
  "resume_id": "res_01hx8019sj0gf99ht2gxyjwj6v",
  "status": "processing",
  "job_id": "job_01hx8044c0ngq4q4mpe8q3nd7f"
}
```

Parse result response:

```json
{
  "resume_id": "res_01hx8019sj0gf99ht2gxyjwj6v",
  "status": "completed",
  "parsed_at": "2026-05-07T15:16:20Z",
  "candidate_name": "Aisha Patel",
  "email": "aisha@example.com",
  "phone": "+1-555-0100",
  "summary": "Computer science student focused on full-stack development.",
  "skills": ["Python", "React", "SQL", "FastAPI", "Git"],
  "education": [
    {
      "school": "State University",
      "degree": "B.S. Computer Science",
      "start_year": 2023,
      "end_year": 2027
    }
  ],
  "experience": [
    {
      "company": "Campus IT",
      "title": "Student Developer",
      "start_date": "2025-01",
      "end_date": "2025-12",
      "bullets": [
        "Built internal support dashboard using React and Python.",
        "Reduced manual ticket triage time by 30%."
      ]
    }
  ],
  "projects": [
    {
      "name": "Course Planner",
      "description": "Web app for planning degree requirements.",
      "skills": ["React", "SQL"]
    }
  ]
}
```

### Job Description Input

```http
POST /jobs
GET /jobs
GET /jobs/{job_id}
PUT /jobs/{job_id}
DELETE /jobs/{job_id}
```

Purpose: Store target job descriptions for matching and document generation.

Create request:

```json
{
  "title": "Software Engineer Intern",
  "company": "Northstar Labs",
  "location": "Remote",
  "employment_type": "internship",
  "source_url": "https://example.com/jobs/software-engineer-intern",
  "description": "We are looking for an intern with Python, React, SQL, and cloud experience.",
  "required_skills": ["Python", "React", "SQL"],
  "preferred_skills": ["AWS", "Docker"]
}
```

Response:

```json
{
  "id": "job_01hx80bcjmb1f24d0khvxzd94x",
  "student_id": "stu_01hx7z2q7n6k9yr2p3tn8r4m6f",
  "title": "Software Engineer Intern",
  "company": "Northstar Labs",
  "location": "Remote",
  "employment_type": "internship",
  "source_url": "https://example.com/jobs/software-engineer-intern",
  "description": "We are looking for an intern with Python, React, SQL, and cloud experience.",
  "required_skills": ["Python", "React", "SQL"],
  "preferred_skills": ["AWS", "Docker"],
  "created_at": "2026-05-07T15:20:00Z",
  "updated_at": "2026-05-07T15:20:00Z"
}
```

### Job Matching

```http
POST /jobs/{job_id}/match
GET /matches/{match_id}
GET /jobs/{job_id}/matches
```

Purpose: Compare a resume or student profile against a job description.

Match request:

```json
{
  "resume_id": "res_01hx8019sj0gf99ht2gxyjwj6v"
}
```

Response:

```json
{
  "id": "mat_01hx80j9w9xm66x2w8ajsz7gzp",
  "job_id": "job_01hx80bcjmb1f24d0khvxzd94x",
  "resume_id": "res_01hx8019sj0gf99ht2gxyjwj6v",
  "student_id": "stu_01hx7z2q7n6k9yr2p3tn8r4m6f",
  "overall_score": 82,
  "skill_score": 86,
  "experience_score": 75,
  "education_score": 90,
  "matched_skills": ["Python", "React", "SQL"],
  "missing_skills": ["AWS", "Docker"],
  "strengths": [
    "Strong alignment with required programming skills.",
    "Relevant full-stack project experience."
  ],
  "risks": [
    "Limited cloud deployment experience."
  ],
  "recommendation": "good_match",
  "created_at": "2026-05-07T15:25:00Z"
}
```

### Skill Gap Analysis

```http
POST /jobs/{job_id}/skill-gap-analysis
GET /skill-gap-analyses/{analysis_id}
```

Purpose: Identify missing skills and recommend student-friendly next actions.

Request:

```json
{
  "resume_id": "res_01hx8019sj0gf99ht2gxyjwj6v",
  "include_learning_plan": true
}
```

Response:

```json
{
  "id": "gap_01hx80n5hp5d6d6g8x6w5je9d1",
  "job_id": "job_01hx80bcjmb1f24d0khvxzd94x",
  "resume_id": "res_01hx8019sj0gf99ht2gxyjwj6v",
  "critical_gaps": [
    {
      "skill": "AWS",
      "reason": "Listed as preferred and useful for cloud deployment work.",
      "priority": "medium",
      "recommended_action": "Complete a small deployment project and mention it in the projects section."
    }
  ],
  "minor_gaps": [
    {
      "skill": "Docker",
      "reason": "Useful for backend development workflows.",
      "priority": "low",
      "recommended_action": "Containerize an existing class or portfolio project."
    }
  ],
  "learning_plan": [
    {
      "week": 1,
      "focus": "AWS basics",
      "outcome": "Deploy a simple FastAPI or React app."
    },
    {
      "week": 2,
      "focus": "Docker basics",
      "outcome": "Add Dockerfile and local run instructions to a project."
    }
  ],
  "created_at": "2026-05-07T15:30:00Z"
}
```

### Tailored Resume Generation

```http
POST /jobs/{job_id}/tailored-resumes
GET /generated-documents/{document_id}
```

Purpose: Generate a job-targeted resume draft from the uploaded resume and job description.

Request:

```json
{
  "resume_id": "res_01hx8019sj0gf99ht2gxyjwj6v",
  "tone": "professional",
  "format": "markdown",
  "preserve_truthfulness": true
}
```

Response:

```json
{
  "id": "doc_01hx80w2e0tkm3428vryrgtb64",
  "type": "tailored_resume",
  "status": "completed",
  "job_id": "job_01hx80bcjmb1f24d0khvxzd94x",
  "resume_id": "res_01hx8019sj0gf99ht2gxyjwj6v",
  "content": "# Aisha Patel\n\n## Summary\nComputer science student with Python, React, and SQL experience...",
  "warnings": [
    "Cloud experience was not added because it was not found in the source resume."
  ],
  "created_at": "2026-05-07T15:35:00Z"
}
```

### Cover Letter Generation

```http
POST /jobs/{job_id}/cover-letters
GET /generated-documents/{document_id}
```

Purpose: Generate a cover letter draft grounded in the student's profile, resume, and target job.

Request:

```json
{
  "resume_id": "res_01hx8019sj0gf99ht2gxyjwj6v",
  "tone": "confident",
  "length": "short",
  "additional_context": "I met the company at a university career fair."
}
```

Response:

```json
{
  "id": "doc_01hx812g35c2xm9mvst3v2wj4e",
  "type": "cover_letter",
  "status": "completed",
  "job_id": "job_01hx80bcjmb1f24d0khvxzd94x",
  "resume_id": "res_01hx8019sj0gf99ht2gxyjwj6v",
  "content": "Dear Hiring Team,\n\nI am excited to apply for the Software Engineer Intern role at Northstar Labs...",
  "warnings": [],
  "created_at": "2026-05-07T15:40:00Z"
}
```

### Application Tracker

```http
POST /applications
GET /applications
GET /applications/{application_id}
PUT /applications/{application_id}
DELETE /applications/{application_id}
```

Purpose: Track internship and entry-level job applications.

Create request:

```json
{
  "job_id": "job_01hx80bcjmb1f24d0khvxzd94x",
  "status": "planned",
  "deadline": "2026-06-01",
  "notes": "Apply after tailoring resume.",
  "contact_name": "Jordan Lee",
  "contact_email": "jordan@example.com"
}
```

Update request:

```json
{
  "status": "applied",
  "applied_at": "2026-05-08T14:00:00Z",
  "notes": "Submitted through company careers page."
}
```

Response:

```json
{
  "id": "app_01hx818t5sxwz1jv0vjncfez4d",
  "student_id": "stu_01hx7z2q7n6k9yr2p3tn8r4m6f",
  "job_id": "job_01hx80bcjmb1f24d0khvxzd94x",
  "company": "Northstar Labs",
  "title": "Software Engineer Intern",
  "status": "applied",
  "deadline": "2026-06-01",
  "applied_at": "2026-05-08T14:00:00Z",
  "notes": "Submitted through company careers page.",
  "contact_name": "Jordan Lee",
  "contact_email": "jordan@example.com",
  "created_at": "2026-05-07T15:45:00Z",
  "updated_at": "2026-05-08T14:00:00Z"
}
```

## 4. Common API Patterns

### Error Response

```json
{
  "error": {
    "code": "resume_not_found",
    "message": "Resume was not found or does not belong to the current student.",
    "request_id": "req_01hx81azhfz0g37c909m33p56s"
  }
}
```

### Pagination Response

```json
{
  "items": [],
  "page": 1,
  "page_size": 20,
  "total": 0
}
```

### Status Values

Resume status:

- `uploaded`
- `parsing`
- `parsed`
- `parse_failed`

Generated document status:

- `processing`
- `completed`
- `failed`

Application status:

- `planned`
- `applied`
- `interviewing`
- `offer`
- `rejected`
- `withdrawn`

## 5. Database Tables Needed

### `students`

Stores the authenticated student profile.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID/string | Primary key |
| `auth_user_id` | string | External auth provider user ID |
| `email` | string | Unique |
| `first_name` | string | Required after onboarding |
| `last_name` | string | Required after onboarding |
| `school` | string | Nullable |
| `major` | string | Nullable |
| `graduation_year` | integer | Nullable |
| `location` | string | Nullable |
| `target_roles` | JSON/array | Student goals |
| `target_industries` | JSON/array | Student goals |
| `skills` | JSON/array | Profile-level skills |
| `portfolio_url` | string | Nullable |
| `linkedin_url` | string | Nullable |
| `created_at` | timestamp | Required |
| `updated_at` | timestamp | Required |

### `resumes`

Stores uploaded resume metadata.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID/string | Primary key |
| `student_id` | UUID/string | Foreign key to `students.id` |
| `label` | string | Nullable |
| `file_name` | string | Required |
| `content_type` | string | PDF/DOCX only for MVP |
| `file_size_bytes` | integer | Required |
| `storage_key` | string | Object storage path |
| `status` | string | Upload/parse status |
| `is_primary` | boolean | Default false |
| `created_at` | timestamp | Required |
| `updated_at` | timestamp | Required |

### `resume_parse_results`

Stores structured extraction output.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID/string | Primary key |
| `resume_id` | UUID/string | Foreign key to `resumes.id` |
| `student_id` | UUID/string | Foreign key to `students.id` |
| `status` | string | `processing`, `completed`, `failed` |
| `raw_text` | text | Extracted text |
| `parsed_json` | JSON | Structured resume data |
| `parser_version` | string | Enables future reparse |
| `error_message` | text | Nullable |
| `created_at` | timestamp | Required |
| `updated_at` | timestamp | Required |

### `jobs`

Stores student-entered job descriptions.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID/string | Primary key |
| `student_id` | UUID/string | Foreign key to `students.id` |
| `title` | string | Required |
| `company` | string | Required |
| `location` | string | Nullable |
| `employment_type` | string | Nullable |
| `source_url` | string | Nullable |
| `description` | text | Required |
| `required_skills` | JSON/array | Parsed or user-provided |
| `preferred_skills` | JSON/array | Parsed or user-provided |
| `created_at` | timestamp | Required |
| `updated_at` | timestamp | Required |

### `job_matches`

Stores match scores and rationale.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID/string | Primary key |
| `student_id` | UUID/string | Foreign key to `students.id` |
| `job_id` | UUID/string | Foreign key to `jobs.id` |
| `resume_id` | UUID/string | Foreign key to `resumes.id` |
| `overall_score` | integer | 0 to 100 |
| `skill_score` | integer | 0 to 100 |
| `experience_score` | integer | 0 to 100 |
| `education_score` | integer | 0 to 100 |
| `matched_skills` | JSON/array | Required |
| `missing_skills` | JSON/array | Required |
| `strengths` | JSON/array | Required |
| `risks` | JSON/array | Required |
| `recommendation` | string | Example: `good_match` |
| `created_at` | timestamp | Required |

### `skill_gap_analyses`

Stores skill gap findings and learning plans.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID/string | Primary key |
| `student_id` | UUID/string | Foreign key to `students.id` |
| `job_id` | UUID/string | Foreign key to `jobs.id` |
| `resume_id` | UUID/string | Foreign key to `resumes.id` |
| `critical_gaps` | JSON | Required |
| `minor_gaps` | JSON | Required |
| `learning_plan` | JSON | Nullable |
| `created_at` | timestamp | Required |

### `generated_documents`

Stores generated resume and cover letter drafts.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID/string | Primary key |
| `student_id` | UUID/string | Foreign key to `students.id` |
| `job_id` | UUID/string | Foreign key to `jobs.id` |
| `resume_id` | UUID/string | Foreign key to `resumes.id` |
| `type` | string | `tailored_resume` or `cover_letter` |
| `status` | string | `processing`, `completed`, `failed` |
| `content` | text | Generated markdown/plain text |
| `warnings` | JSON/array | Truthfulness or quality warnings |
| `model_name` | string | LLM model used |
| `prompt_version` | string | Enables repeatability |
| `created_at` | timestamp | Required |
| `updated_at` | timestamp | Required |

### `applications`

Stores application tracker records.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID/string | Primary key |
| `student_id` | UUID/string | Foreign key to `students.id` |
| `job_id` | UUID/string | Foreign key to `jobs.id`, nullable for manual entries |
| `company` | string | Denormalized for quick display |
| `title` | string | Denormalized for quick display |
| `status` | string | Tracker status |
| `deadline` | date | Nullable |
| `applied_at` | timestamp | Nullable |
| `notes` | text | Nullable |
| `contact_name` | string | Nullable |
| `contact_email` | string | Nullable |
| `created_at` | timestamp | Required |
| `updated_at` | timestamp | Required |

## 6. Environment Variables Needed

Do not commit real secrets. Use `.env.example` later with placeholder values only.

```text
APP_ENV=development
APP_NAME=careerproof-api
APP_VERSION=0.1.0
API_V1_PREFIX=/api/v1

DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/careerproof

AUTH_PROVIDER=local_or_external
JWT_ISSUER=https://auth.example.com
JWT_AUDIENCE=careerproof-api
JWT_PUBLIC_KEY=replace_with_public_key_or_jwks_url
JWKS_URL=https://auth.example.com/.well-known/jwks.json

CORS_ORIGINS=http://localhost:3000

OBJECT_STORAGE_PROVIDER=s3_or_supabase
OBJECT_STORAGE_BUCKET=careerproof-resumes
OBJECT_STORAGE_REGION=us-east-1
OBJECT_STORAGE_ENDPOINT_URL=
OBJECT_STORAGE_ACCESS_KEY_ID=replace_in_real_env_only
OBJECT_STORAGE_SECRET_ACCESS_KEY=replace_in_real_env_only

LLM_PROVIDER=openai
LLM_MODEL=replace_with_selected_model
LLM_API_KEY=replace_in_real_env_only

MAX_UPLOAD_SIZE_MB=10
ALLOWED_RESUME_CONTENT_TYPES=application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document

BACKGROUND_WORKER_ENABLED=false
REDIS_URL=redis://localhost:6379/0

LOG_LEVEL=INFO
SENTRY_DSN=
```

## 7. Security Considerations

- Require authentication for all student data routes. Only `/health` should be public.
- Validate that every requested resource belongs to the authenticated student before returning, updating, or deleting it.
- Store uploaded resumes in private object storage. Do not expose raw storage keys as public download URLs.
- Enforce upload size limits and allow only PDF/DOCX content types for the MVP.
- Scan or validate uploaded files before parsing when infrastructure supports it.
- Avoid logging resume text, generated document content, access tokens, API keys, or full request bodies.
- Use request IDs in logs and error responses for debugging without exposing sensitive data.
- Keep LLM prompts grounded in user-provided data. The tailored resume generator must not invent credentials, employers, degrees, metrics, or skills.
- Include generated document warnings when source evidence is weak or missing.
- Rate limit expensive endpoints such as parsing, matching, skill analysis, and generation.
- Add background job idempotency so repeated requests do not create uncontrolled duplicate work.
- Use HTTPS in deployed environments.
- Use database migrations for all schema changes.
- Apply least-privilege credentials for database, object storage, and LLM providers.
- Set CORS to explicit frontend origins rather than wildcard origins.
- Define retention policies for uploaded resumes, parsed text, and generated documents.

## 8. Backend Implementation Build Order

1. Scaffold `apps/api` FastAPI project structure, dependency management, settings, logging, and `/api/v1/health`.
2. Add database connection, migration tooling, base models, and test database setup.
3. Implement authentication dependency and student ownership checks.
4. Implement student profile read/update endpoints.
5. Implement resume upload metadata, private object storage adapter, and file validation.
6. Implement resume parsing flow with initial synchronous parsing for development and a background-job-ready service boundary.
7. Implement job description CRUD endpoints.
8. Implement job matching service and persistence.
9. Implement skill gap analysis service and persistence.
10. Implement generated document service for tailored resumes and cover letters with truthfulness guardrails.
11. Implement application tracker CRUD endpoints.
12. Add rate limiting, structured error responses, and request ID middleware.
13. Add integration tests for core student workflows:
    - Create/update profile
    - Upload and parse resume
    - Create job
    - Match job to resume
    - Generate skill gap analysis
    - Generate tailored resume and cover letter
    - Track application status
14. Add deployment configuration, health dependency checks, and production environment documentation.

## MVP Workflow

The intended end-to-end student flow is:

1. Student signs in and completes their profile.
2. Student uploads a resume.
3. Backend parses the resume into structured data.
4. Student enters a job description.
5. Backend scores the match between the resume/profile and the job.
6. Backend identifies skill gaps and recommends next actions.
7. Student generates a tailored resume and cover letter.
8. Student saves the job in the application tracker and updates status over time.
