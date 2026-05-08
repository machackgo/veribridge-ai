# VeriBridge AI Web

Next.js 16 frontend for VeriBridge AI — the verified .edu talent platform.

## Stack

- **Next.js 16** (App Router, Turbopack)
- **React 19**, TypeScript 5
- **Tailwind CSS 4** + CSS custom properties
- **Supabase Auth** — email OTP for .edu students
- **Playwright** for E2E tests

---

## Local Development

### 1. Install dependencies

```bash
cd apps/web
npm install
```

### 2. Configure environment

```bash
cp .env.example .env.local
```

Fill in your Supabase credentials. Find them at:
**Supabase dashboard → Project Settings → API**

| Variable | Description |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Project REST URL — `https://your-ref.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Public anon key (safe for browser) |
| `NEXT_PUBLIC_API_BASE_URL` | VeriBridge backend URL (default: `http://localhost:8000`) |

**Never commit `.env.local`.**

### 3. Enable Supabase Auth email OTP

In the Supabase dashboard:

1. **Authentication → Providers → Email** — ensure Email provider is enabled.
2. **Authentication → Email Templates** — the default OTP template works.
3. **Authentication → Settings**:
   - Disable "Confirm email" (OTP handles verification)
   - Set "OTP expiry" to 600 seconds (10 minutes)
4. *(Production)* Set an SMTP provider so emails are delivered.

### 4. Run locally

```bash
npm run dev
```

Open `http://localhost:3000`.

---

## Authentication Flow

VeriBridge uses Supabase Auth **email OTP** (no passwords):

```
Student enters .edu email
  │
  ▼
Supabase sends a 6-digit OTP to the email address
  │
  ▼
Student enters code on /login
  │
  ▼
Supabase verifies → issues access_token + refresh_token (stored in cookies)
  │
  ▼
Middleware reads session from cookie → allows /dashboard/**
  │
  ▼
Frontend sends Authorization: Bearer <access_token> to backend API
  │
  ▼
Backend verifies HS256 JWT with SUPABASE_JWT_SECRET → returns data
```

### Routes

| Route | Protection |
|---|---|
| `/` | Public |
| `/login` | Public |
| `/dashboard/**` | Auth required (redirect to `/login?next=<path>`) |
| `/recruiter/**` | Public (prototype/demo) |
| `/university/**` | Public (prototype/demo) |

### Development bypass

Set `NEXT_PUBLIC_DEMO_MODE=true` to skip the dashboard auth proxy guard while
local SMTP/domain verification is not ready. This variable must be present at
build/start time because Next.js bakes it into the Edge Runtime bundle.

```bash
NEXT_PUBLIC_DEMO_MODE=true npm run dev
```

For the current Resend/Supabase SMTP status and local auth workflow, see:

- `../../docs/auth/smtp_domain_setup_status.md`
- `../../docs/auth/local_auth_testing.md`

### Calling the backend

Use the `fetchAPI` helper in `src/lib/api.ts`:

```typescript
import { fetchAPI, getStudentProfile } from "@/lib/api"

// Reads the Supabase session, injects Authorization: Bearer <token>
const profile = await getStudentProfile()

// Or make arbitrary authenticated requests:
const res = await fetchAPI("/api/v1/student/profile", { method: "GET" })
```

### Getting a token for curl testing

```bash
# Sign in via Supabase REST
TOKEN=$(curl -s -X POST \
  "${NEXT_PUBLIC_SUPABASE_URL}/auth/v1/token?grant_type=password" \
  -H "apikey: ${NEXT_PUBLIC_SUPABASE_ANON_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"email":"you@university.edu","password":""}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Use it
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/student/profile
```

> **Note:** OTP logins don't use passwords. Use the Supabase JS client in-browser
> or the `signInWithOtp` + `verifyOtp` flow for non-password sessions.

---

## Checks

```bash
npm run lint
npm run build
```

---

## E2E Tests

```bash
npm run test:e2e
```

| File | Scope |
|---|---|
| `e2e/navigation.spec.ts` | Landing page nav, hero CTAs, platform links |
| `e2e/dashboards.spec.ts` | All 3 dashboards + 9 pages, toggles, toasts |
| `e2e/proof-section.spec.ts` | Interactive skill tabs and evidence cards |
| `e2e/auth.spec.ts` | Login page renders, .edu validation, OTP flow (mocked) |

The Playwright suite runs with `NEXT_PUBLIC_DEMO_MODE=true` so dashboard tests do not
require a real Supabase session.

---

## Project Structure

```
apps/web/
├── src/
│   ├── app/
│   │   ├── page.tsx            Landing page
│   │   ├── login/page.tsx      .edu OTP auth flow  ← new
│   │   ├── dashboard/          Student dashboard (auth-protected)
│   │   ├── recruiter/          Recruiter dashboard (prototype)
│   │   └── university/         University dashboard (prototype)
│   ├── lib/
│   │   ├── supabase/
│   │   │   ├── client.ts       Browser Supabase client  ← new
│   │   │   └── server.ts       Server Supabase client  ← new
│   │   └── api.ts              Authenticated backend fetch helper  ← new
│   └── middleware.ts           Dashboard auth guard  ← new
├── components/
│   ├── dashboard/
│   │   ├── DashboardShell.tsx
│   │   ├── StudentViews.tsx
│   │   ├── RecruiterViews.tsx
│   │   └── UniversityViews.tsx
│   ├── prototype/ClaudeLanding.tsx
│   └── ui/
├── e2e/                        Playwright tests
├── .env.example                Required env vars template  ← new
└── playwright.config.ts
```
