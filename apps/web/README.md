# VeriBridge AI — web app (`apps/web`)

Next.js 16 (App Router), React 19, TypeScript and Tailwind CSS, deployed on Vercel at
<https://veribridgeai.com>. The product overview, architecture, feature status and full setup guide
are in the [root README](../../README.md) and [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md);
this file only covers working inside `apps/web`.

## Run locally

```bash
cd apps/web
cp .env.example .env.local   # then fill in the values below
npm ci
npm run dev                  # http://localhost:3000
```

Environment variables (see `.env.example`):

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_API_URL` | FastAPI origin, e.g. `http://localhost:8000` (`NEXT_PUBLIC_API_BASE_URL` is the legacy fallback) |
| `NEXT_PUBLIC_APP_URL` | This app's origin |
| `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase Auth (email OTP and Google) — public values only |
| `NEXT_PUBLIC_OTP_CODE_LENGTH` | Length of the emailed sign-in code |
| `NEXT_PUBLIC_RECORDER_EXTENSION_STORE_URL` | Chrome Web Store link for the recorder extension |
| `NEXT_PUBLIC_SERVICE_STATUS` | `paused` shows the site-wide "backend paused" banner; empty otherwise |
| `NEXT_PUBLIC_DEMO_MODE` | `true` skips auth redirects for local development only; ignored in production builds |

## Layout

| Path | Contents |
|---|---|
| `src/app/` | Routes. `src/proxy.ts` is the auth proxy (Next.js 16's replacement for `middleware.ts`) and lists the public routes |
| `src/lib/` | API clients (`api.ts`, `vbr-api.ts`, `passport-api.ts`), Supabase clients, service status |
| `components/` | Shared UI: `landing-v2/` (home page and its sample-data product demonstration), `dashboard/`, `passport/`, `vbr/`, `recruiter-passport/` |
| `data/` | Sample data for the prototype dashboards (labelled as sample data in the UI) |
| `src/__tests__/` | Vitest unit tests |
| `e2e/`, `e2e-local/`, `e2e-prod/` | Playwright suites: mocked, local stack, and live site (needs QA sessions) |

## Checks

```bash
npx vitest run      # unit tests
npx tsc --noEmit    # types
npm run lint
npm run build       # production build
```
