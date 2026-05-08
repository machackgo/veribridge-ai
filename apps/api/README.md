# VeriBridge AI — Backend API

FastAPI backend for the VeriBridge AI student MVP.

---

## Prerequisites

- Python 3.11+
- A Supabase project (free tier is sufficient for development)

---

## Local Setup

### 1. Create a virtual environment

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in your Supabase credentials.
**Never commit `.env` to version control.**

Required variables:

| Variable | Description |
|---|---|
| `SUPABASE_URL` | Project URL — Supabase dashboard → Settings → API |
| `SUPABASE_ANON_KEY` | Public anon key (safe for client-side) |
| `SUPABASE_SERVICE_ROLE_KEY` | Service-role key — **server only, never expose to browser** |
| `DATABASE_URL` | Direct Postgres connection string (optional for MVP) |

Find your keys at: **Supabase dashboard → Project Settings → API**.

---

## Supabase Setup

### 1. Run the initial schema migration

Open the Supabase SQL editor (**SQL Editor → New query**) and paste the
contents of:

```
apps/api/app/db/migrations/001_initial_schema.sql
```

Run the entire file. This creates all 12 MVP tables with RLS enabled.

### 2. Create the resumes storage bucket

See [`docs/storage/resumes_bucket.md`](docs/storage/resumes_bucket.md)
for step-by-step instructions and the Storage RLS policy SQL.

### 3. Verify the setup

After running the migration, check:

- **Table Editor** — all 12 tables visible.
- **Authentication → Policies** — RLS policies on every table.
- **Storage** — `resumes` bucket exists and is private.

---

## Running Locally

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/api/v1/health
```

Expected:

```json
{
  "status": "ok",
  "service": "careerproof-api",
  "version": "0.1.0"
}
```

---

## Demo User Setup (first-time development)

Before the Student Profile API will work, you need a real Supabase Auth user
whose UUID is placed in `DEMO_USER_ID` in `.env`, and a matching row in
`public.users`.

### Step 1 — Create the Supabase Auth user

If the Supabase dashboard Authentication page is broken, use this script:

```bash
# Run from the project root
python apps/api/scripts/create_demo_auth_user.py
```

The script:
- Reads `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` from `apps/api/.env`
- Prompts you for a temporary password (not echoed, not stored)
- Creates `mohammedmubashir@wpi.edu` with `email_confirm = true`
- Prints only the user **ID** and **email** — never prints any key
- Handles "already exists" gracefully and shows the existing ID

**Never run this in production.**

### Step 2 — Update DEMO_USER_ID

Copy the user ID printed by the script, then edit `apps/api/.env`:

```
DEMO_USER_ID=<paste-the-uuid-here>
```

### Step 3 — Restart the backend

```bash
uvicorn app.main:app --reload --port 8000
```

### Step 4 — Bootstrap the public.users row

The `student_profiles` table has a FK to `public.users`. Run this once:

```bash
curl -s -X POST http://localhost:8000/api/v1/debug/bootstrap-demo-user \
  | python3 -m json.tool
```

Expected: `"created": true` on first run, `"created": false` if already done.

### Step 5 — Check config

```bash
curl -s http://localhost:8000/api/v1/debug/config | python3 -m json.tool
```

---

## Authentication

Routes use `Authorization: Bearer <token>` with Supabase Auth JWTs (HS256).

**Development (no token):** Set `DEMO_USER_ID` in `.env` and omit the header. The
server falls back to that UUID automatically when `ENVIRONMENT != production`.

**Development (with real token):** Sign in from the frontend (or use Supabase's
REST auth endpoint) and pass the access token:

```bash
# Sign in and capture the access token
TOKEN=$(curl -s -X POST \
  "https://your-ref.supabase.co/auth/v1/token?grant_type=password" \
  -H "apikey: <SUPABASE_ANON_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"email":"mohammedmubashir@wpi.edu","password":"<your-password>"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Use it in subsequent requests
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/student/profile
```

**Error responses** when a token is present but invalid:

| Situation | HTTP | `code` |
|---|---|---|
| Token expired | 401 | `token_expired` |
| Bad signature / malformed | 401 | `invalid_token` |
| No token in production | 401 | `unauthorized` |

---

## Student Profile API

### GET /api/v1/student/profile

Returns the current student's profile.

```bash
curl http://localhost:8000/api/v1/student/profile
```

Returns `404` if no profile has been created yet.

### PUT /api/v1/student/profile

Creates or updates the current student's profile (upsert).

```bash
curl -X PUT http://localhost:8000/api/v1/student/profile \
  -H "Content-Type: application/json" \
  -d '{
    "full_name": "Maya Reyes",
    "university": "WPI",
    "degree": "B.S.",
    "major": "Computer Science",
    "graduation_year": 2026,
    "visa_status": "F-1",
    "target_roles": ["Backend Engineer", "SWE Intern"],
    "target_locations": ["NYC", "Remote"],
    "github_url": "https://github.com/maya",
    "linkedin_url": "https://linkedin.com/in/maya"
  }'
```

Required fields: `full_name`, `university`, `degree`, `major`.
All other fields are optional.

### Demo user setup

Set `DEMO_USER_ID` in `.env` to the UUID of a row in your Supabase
`auth.users` table.  You also need a matching row in `public.users`
(the application-side user table).

To create one quickly in the Supabase SQL editor:

```sql
-- Replace the UUID with your actual DEMO_USER_ID value
insert into public.users (id, email, role, status)
values (
  '00000000-0000-0000-0000-000000000001',
  'demo@example.com',
  'student',
  'active'
)
on conflict (id) do nothing;
```

### Interactive docs

With the server running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc:       http://localhost:8000/redoc

---

## Running Tests

```bash
pytest
```

| File | Scope |
|---|---|
| `tests/test_health.py` | Health endpoint response shape |
| `tests/test_config.py` | Settings loading; SecretStr types; Supabase config detection |
| `tests/test_auth.py` | JWT verification — valid, expired, wrong secret, wrong audience, malformed |
| `tests/test_student_profile.py` | Student profile API; field mapping; DB error handling |
| `tests/test_create_demo_auth_user.py` | CLI script — env loading, URL validation, user creation |

Tests make no real network calls to Supabase.

---

## Project Structure

```
apps/api/
├── app/
│   ├── main.py                       FastAPI app factory
│   ├── api/v1/
│   │   ├── router.py
│   │   └── endpoints/health.py       GET /api/v1/health
│   ├── core/config.py                Pydantic settings (env-backed)
│   └── db/
│       ├── supabase.py               Supabase client factory
│       └── migrations/
│           └── 001_initial_schema.sql  MVP tables + RLS
├── docs/storage/resumes_bucket.md    Bucket setup + Storage RLS
├── tests/
│   ├── test_health.py
│   └── test_config.py
├── requirements.txt
└── .env.example
```

---

## Environment Variable Reference

```bash
# App identity
APP_NAME=careerproof-api
APP_VERSION=0.1.0
API_V1_PREFIX=/api/v1
ENVIRONMENT=development

# CORS — comma-separated allowed origins
CORS_ORIGINS=http://localhost:3000

# Supabase — from Project Settings → API
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_ANON_KEY=<anon-key>
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>

# Direct Postgres (optional for MVP)
DATABASE_URL=postgresql+asyncpg://<user>:<pass>@<host>:5432/<db>
```

---

## Security Notes

- `SUPABASE_SERVICE_ROLE_KEY` bypasses all RLS. Keep it server-side only.
- Never log, return, or expose secret values in API responses.
- All student data routes must verify the requesting user owns the resource.
- Auth is not yet implemented — do not deploy to production until it is.
