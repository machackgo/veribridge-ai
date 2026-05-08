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

## Running Tests

```bash
pytest
```

| File | Scope |
|---|---|
| `tests/test_health.py` | Health endpoint response shape |
| `tests/test_config.py` | Settings loading; SecretStr types; Supabase config detection |

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
