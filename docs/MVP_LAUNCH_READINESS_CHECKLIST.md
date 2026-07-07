# MVP Launch Readiness Checklist — veribridgeai.com

Production domain integration for:

- Web app: `https://veribridgeai.com` and `https://www.veribridgeai.com`
- API: `https://api.veribridgeai.com`

Stack: **Vercel** (Next.js web app) · **Render** (FastAPI backend) · **Supabase** (Postgres + Auth + Storage).

> DNS values below are **placeholders**. Read the real records from each provider's
> dashboard (Vercel → Domains, Render → Custom Domain) and substitute them. Do not
> invent record values.

---

## 0. Pre-flight

- [ ] All target tests green locally (see `docs/PROJECT_CHECKLIST.md` and the API/web test suites).
- [ ] `main` (or the release branch) builds clean: `apps/web` `npx tsc --noEmit` + `next build`, and the API imports without error.
- [ ] No secrets committed. `.env.example` files contain placeholders only. Frontend env exposes **no** service-role key.
- [ ] Confirm domain ownership of `veribridgeai.com` in your registrar; you can edit DNS records.

---

## 1. Vercel (web app — Next.js)

- [ ] Import the repo into Vercel; set the project root to `apps/web` (monorepo).
- [ ] Framework preset: **Next.js**. Build: `next build`. Install: `npm install` (or repo package manager).
- [ ] **Environment variables** (Production scope):
  - [ ] `NEXT_PUBLIC_API_URL=https://api.veribridgeai.com`
  - [ ] `NEXT_PUBLIC_API_BASE_URL=https://api.veribridgeai.com` (legacy fallback — keep in sync)
  - [ ] `NEXT_PUBLIC_APP_URL=https://veribridgeai.com`
  - [ ] `NEXT_PUBLIC_APP_NAME=VeriBridge AI`
  - [ ] `NEXT_PUBLIC_SUPABASE_URL=https://<project-ref>.supabase.co`
  - [ ] `NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon key>`
  - [ ] **Do NOT** set `SUPABASE_SERVICE_ROLE_KEY` (or any server secret) in Vercel envs consumed by the browser.
- [ ] Add domains under **Project → Settings → Domains**:
  - [ ] `veribridgeai.com` (apex)
  - [ ] `www.veribridgeai.com`
  - [ ] Choose one canonical host and set the other to redirect (recommended: `www` → apex, or apex → `www`).
- [ ] Deploy and confirm the Production build succeeds.

## 2. Render (API — FastAPI)

- [ ] Create a Web Service from the repo; root `apps/api`.
- [ ] Start command (adjust to repo): `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- [ ] **Environment variables** (Production):
  - [ ] `ENVIRONMENT=production`
  - [ ] `CORS_ALLOWED_ORIGINS=https://veribridgeai.com,https://www.veribridgeai.com,http://localhost:3000,http://127.0.0.1:3000`
        (⚠ a literal `*` is rejected at startup when `ENVIRONMENT=production`)
  - [ ] `FRONTEND_URL=https://veribridgeai.com`
  - [ ] `PUBLIC_APP_URL=https://veribridgeai.com`
  - [ ] `BACKEND_PUBLIC_URL=https://api.veribridgeai.com`
  - [ ] `SUPABASE_URL=https://<project-ref>.supabase.co`
  - [ ] `SUPABASE_ANON_KEY=<anon key>`
  - [ ] `SUPABASE_SERVICE_ROLE_KEY=<service role key>` (server-side only)
  - [ ] `SUPABASE_JWT_SECRET=<jwt secret>` (required for token verification in production)
  - [ ] `DATABASE_URL=<supabase session-pooler URL, URL-encoded password>`
  - [ ] Storage buckets as needed: `SUPABASE_VBR_MEDIA_BUCKET`, etc.
  - [ ] Provider keys as needed: `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` (optional; deterministic fallbacks exist).
- [ ] Add custom domain `api.veribridgeai.com` under **Settings → Custom Domains**.
- [ ] Confirm the service boots (no wildcard-CORS ValueError, no missing-JWT-secret warnings).

## 3. Supabase (Postgres + Auth + Storage)

- [ ] All migrations applied to the production project (check the migrations directory / runner).
- [ ] **Auth → URL Configuration**: Site URL = `https://veribridgeai.com`; add redirect URLs for
      `https://veribridgeai.com/**` and `https://www.veribridgeai.com/**`.
- [ ] **RLS** enabled on all user-data tables; policies verified (owner-scoped reads/writes; public-report tables fail closed).
- [ ] **Storage** buckets exist and are **private** (e.g. `vbr-media`); signed-URL access only.
- [ ] Service-role key rotated if it was ever exposed during development.
- [ ] `DATABASE_URL` uses the session-mode pooler and a URL-encoded password.

## 4. DNS records

Set at your registrar / DNS provider. **Replace placeholders with the exact values shown in the Vercel and Render dashboards.**

| Host | Type | Value (placeholder) | Source |
|------|------|---------------------|--------|
| `veribridgeai.com` (apex) | A (or ALIAS/ANAME) | `<VERCEL_APEX_RECORD>` | Vercel → Domains |
| `www.veribridgeai.com` | CNAME | `<VERCEL_WWW_CNAME>` | Vercel → Domains |
| `api.veribridgeai.com` | CNAME | `<RENDER_API_CNAME>` | Render → Custom Domain |

- [ ] Apex record added (Vercel usually provides an A record or an ALIAS/ANAME target).
- [ ] `www` CNAME added.
- [ ] `api` CNAME added (points at the Render service target).
- [ ] Wait for propagation; verify with `dig +short veribridgeai.com`, `dig +short www.veribridgeai.com`, `dig +short api.veribridgeai.com`.

## 5. SSL / TLS

- [ ] Vercel issued certs for `veribridgeai.com` and `www.veribridgeai.com` (auto after DNS validates).
- [ ] Render issued a cert for `api.veribridgeai.com`.
- [ ] HTTPS loads with no certificate warnings on all three hosts.
- [ ] HTTP → HTTPS redirect works on all three.

## 6. Production smoke tests

Run after DNS + SSL are live:

- [ ] `curl -I https://veribridgeai.com` → 200/redirect to canonical host.
- [ ] `curl -I https://www.veribridgeai.com` → resolves to canonical per redirect choice.
- [ ] `curl -i https://api.veribridgeai.com/docs` (or health/openapi) → 200.
- [ ] **CORS preflight** succeeds from the real origin:
      ```
      curl -i -X OPTIONS https://api.veribridgeai.com/api/v1/health \
        -H "Origin: https://veribridgeai.com" \
        -H "Access-Control-Request-Method: GET"
      ```
      Expect `Access-Control-Allow-Origin: https://veribridgeai.com` (echoed, not `*`).
- [ ] Sign in on `https://veribridgeai.com`; confirm the browser calls `https://api.veribridgeai.com` (Network tab) with a Bearer token, no CORS errors, no `localhost` calls.
- [ ] Load a public report / passport link end-to-end (unauthenticated).
- [ ] Confirm no mixed-content or blocked-request console errors.

## 7. Rollback plan

- [ ] **Web (Vercel):** Deployments → previous good deployment → **Promote to Production** (instant). Or `git revert` and redeploy.
- [ ] **API (Render):** Deploys → **Rollback** to the last healthy deploy. Or set the branch back and redeploy.
- [ ] **DNS:** keep a note of the pre-cutover records so they can be restored; TTL kept low (e.g. 300s) during cutover for fast revert.
- [ ] **Env:** capture the previous env-var values before changing them so they can be restored.
- [ ] **DB:** migrations are forward-only — verify a backup/snapshot exists before cutover; do not auto-run destructive down-migrations.

---

### Manual steps that are NOT automated here

1. Reading the real DNS record values from Vercel/Render and entering them at the registrar.
2. Setting production env vars in the Vercel and Render dashboards.
3. Applying migrations to the production Supabase project and verifying RLS.
4. Rotating any secrets exposed during development.
5. The actual DNS change, deploy, and DNS/SSL propagation wait.
