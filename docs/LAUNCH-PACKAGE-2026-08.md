# VeriBridge AI — MVP Launch Package (2026-08)

**Status: READY FOR LAUNCH** · Deployed commit `acb845746f9f46f0b4235e5ef8f312d7ab8bc912` (PR #82 → `main`) · Verified in production 2026-08-05 00:45 UTC

VeriBridge AI turns student work into verified, recruiter-ready evidence. Students
prove skills through five proof types — GitHub repositories, website walkthrough
recordings, documents, video defenses, and project defenses — and publish a
privacy-controlled Work Passport that recruiters can inspect down to individual
evidence chains.

---

## 1. Production architecture

```
Browser ──► veribridgeai.com (Vercel, Next.js — apps/web)
   │              │  server routes proxy /api → backend
   │              ▼
   ├──► veribridge-api.onrender.com (Render, FastAPI — apps/api)
   │              │  service-role Supabase client; ALL authorization is
   │              │  app-level (owner filters, disclosure resolver, RLS bypassed)
   │              ▼
   └──► Supabase (us-east-1)
            ├─ Postgres 17 — schema migrations 001–064
            ├─ Auth — ES256 JWTs verified via JWKS (no shared secret)
            └─ Storage — proof artifacts, VBR media, defense media, avatars

Email:   Auth emails → Resend SMTP (smtp.resend.com:465, auth@veribridgeai.com,
         domain DKIM/SPF-verified) · Inbound support@ → ImprovMX forwarding
DNS:     GoDaddy (ns73/ns74.domaincontrol.com); root = ImprovMX, send.* = Resend
Capture: Chrome MV3 recorder extension v1.0.0 (store-ready, unpublished)
```

Key invariants:

- Every public surface routes through the canonical visibility master switch
  (`vbr_work_passports.is_published`) and the hierarchical disclosure resolver
  (migrations 052–064).
- All denials are indistinguishable 404s (non-disclosure).
- Artifact access policies are `owner_only` / `recruiter_safe`; recruiter
  consent never maps to anonymous access.
- The backend uses a service-role database client for all requests; row-level
  security is bypassed by design and authorization is enforced in the
  application layer.

## 2. MVP capabilities

- **Five proof types** with a shared canonical claim→evidence map: GitHub
  repositories (countable-purpose tier contract, analyzer v3), website
  walkthrough recordings (MV3 recorder with durable finalize + recovery),
  document originals, video proofs, and project defenses.
- **Canonical Work Passport**: Private/Public master switch, granular
  per-section disclosure, Privacy & Sharing center, Full-access mode.
- **Recruiter-first public passport**: `/p/{slug}` with per-skill evidence
  drilldowns, source-coverage attribution, credibility rationale, and
  suggested interview questions; QR/Beam sharing with scan-safe codes and
  view tracking.
- **Auth & identity**: Supabase Auth with ES256/JWKS verification, email
  confirmation via custom SMTP, fresh-user self-provisioning, fail-closed
  session handling (no demo-user fallback).
- **Multi-user isolation**: audited (2026-07-21/22) with app-level owner
  filtering on every student surface.

## 3. Deployment summary

| Tier | Where | How | State |
|---|---|---|---|
| Backend | Render service `veribridge-api` (`srv-d9fgdnrrjlhs73aa8dq0`) | Auto-deploy **off**; trigger via `POST /v1/services/<id>/deploys` with `commitId` | Deploy `dep-d9p737vqj5pc73djrta0` live 2026-08-04 23:16 UTC |
| Frontend | Vercel project `veribridge-web` (root `apps/web`) | `npx vercel deploy --prod --archive=tgz --yes` from repo root | `dpl_G5aNduCsNgF3dXTjQr6ahfUg7NSS` aliased to veribridgeai.com |
| Database | Supabase Postgres | Numbered migrations `apps/api/app/db/migrations/` (runner needs URL-decoded password) | Schema at 064; 2026-08 access-policy repair verified no-op |
| Auth email | Resend custom SMTP | Supabase Auth → SMTP settings | Domain verified; end-to-end delivery confirmed |

Operational notes: health check is `GET /api/v1/health`; `/docs` and
`/openapi.json` are disabled in production; Vercel uploads occasionally fail
transiently ("fetch failed") — retry; verify GoDaddy DNS via public resolvers
(`dig @8.8.8.8`), as GoDaddy's own nameservers refuse direct queries.

## 4. Production verification results (2026-08-04/05)

Smoke suite — **8/8 PASS**:

1. Account creation (auth layer) ✅
2. Login — password grant, ES256 token accepted by API ✅
3. Proofs — `/student/vbr/projects` and `/student/extension-proof/sessions`
   both 200 with fresh-user provisioning ✅
4. Private passport — `/student/vbr/passport` + `/passport/status` 200 ✅
5. Public passport — `/api/v1/public/p/{slug}` 200 on published slugs;
   unknown slug → non-disclosure 404 ✅
6. Recruiter surface — public skill-report drilldown 200, recruiter-safe
   payload ✅
7. Logout — 204 ✅
8. Cleanup — smoke user deleted ✅

Additional verification:

- **Signup email flow (end-to-end, real email)**: public signup 200 →
  confirmation email from `auth@veribridgeai.com` delivered to Gmail **inbox**
  in ~1 second → confirmation consumed (`email_confirmed_at` set) → login 200
  → API session 200 → logout 204.
- **Privacy fail-closed**: anonymous requests to an `owner_only` artifact's
  `view` / `download` / `signed-url` endpoints all return 404.
- **Data audit**: `proof_artifacts` contains only `owner_only` rows — zero
  `public_safe` rows ever existed, so the 2026-08 recruiter-share repair is a
  verified no-op (see `docs/data-repairs/2026-08-recruiter-share-access-policy.md`).
- **Production hardening**: `/docs` and `/openapi.json` return 404 in
  production.

## 5. Launch readiness status

| Dimension | Status |
|---|---|
| Core MVP software | ✅ Ready — deployed and verified |
| Public self-service signup | ✅ Ready — email delivery verified end-to-end |
| Chrome extension publication | ⏸ Waiting on Google Trader verification (external) |
| Supabase plan upgrade | ⏳ Operational requirement (owner action, dated) |

**Verdict: the MVP is launch-ready.** All remaining items are operational,
not software.

## 6. Remaining operational requirements

1. **Supabase Pro upgrade** — before **19 Aug 2026** (dashboard-announced
   restriction date for the over-quota organization). Handled separately by
   the owner. Also eliminates the free-plan inactivity auto-pause.
2. **Chrome Web Store publication** — gated on Google Trader verification
   (~10–12 days); checklist in §8.
3. *(Optional)* Execute the no-op repair SQL for the record
   (`docs/data-repairs/2026-08-recruiter-share-access-policy.md`).
4. *(Optional)* ImprovMX alias for `auth@veribridgeai.com` so replies to auth
   emails reach the team.
5. *(Optional, post-launch)* Configure a production transcription provider to
   retire video-proof degraded mode.

## 7. Known limitations

- Production video transcription is `not_configured`; video proofs run in a
  degraded mode that reports its status honestly.
- Replay `duration_seconds` is a display-only cv2 estimate and can be wrong.
- Long MediaRecorder sessions can lose chunks at ffmpeg concat boundaries,
  truncating transcripts (known, unfixed).
- Legacy VBR report tokens (`vbr_reports`) are unused in production; the
  recruiter surface is the canonical passport and skill reports.
- Render backend does not auto-deploy on merge; deploys are explicit.

## 8. Chrome Web Store publication checklist

Everything on our side is frozen and verified; full detail in
`docs/chrome-web-store/PUBLICATION-RUNBOOK.md`.

**Gate (external):** Google Trader verification of the publisher address.

Then (~40–50 min at the dashboard):

- [ ] **A.** Account tab: Trader verified; publisher name "VeriBridge";
  contact email confirmed
- [ ] **B.** New item → upload
  `apps/extension/release/veribridge-recorder-v1.0.0.zip`
  (sha256 `4702db28bfc5b6ad34c0f68eb00b670b65b758f09e1651b1f1557102e2aaea32`);
  record the item ID; confirm v1.0.0 / MV3 / no manifest errors
- [ ] **C.** Store listing from `LISTING.md` §1 + assets from
  `apps/extension/store-assets/`
- [ ] **D.** Privacy tab from `LISTING.md` §2 (single purpose, permission
  justifications, data-use checkboxes, attestations, privacy URL)
- [ ] **E.** Distribution (Public, or Unlisted for soft launch) + reviewer
  test account from `LISTING.md` §3
- [ ] **F.** **STOP** — compile pre-submission review; publisher explicitly
  approves
- [ ] **G.** Submit; record timestamp, item ID, listing URL; status is
  "pending review", not "published"

After Google approves (~15 min):

- [ ] Set `NEXT_PUBLIC_RECORDER_EXTENSION_STORE_URL=<listing URL>` in the
  Vercel production environment and redeploy the web app

## 9. Future roadmap

Aligned with the 12-month enterprise plan
(`docs/roadmap/CareerProof_AI_12_Month_Roadmap.html`, ARC-002): evolve from
the launched student MVP into a three-sided platform on one verified profile
graph.

- **Near term (post-launch hardening)**: production transcription provider;
  transcript-truncation fix; Chrome extension GA + install-flow polish;
  Apple Wallet passport card (signing done; Apple Developer certs remain).
- **Side B — recruiter marketplace**: recruiter accounts and search over
  verified candidates (readiness, evidence, visa compatibility), invitations,
  company profiles, subscription billing.
- **Side C — university analytics**: aggregate, anonymized career-center
  analytics — readiness by major, skill gaps, employer engagement, outcome
  reports.
- **Platform**: verified .edu identity tiering, evidence-graph intelligence
  and skill-gap guidance, outcome tracking, interview preparation loops.

---

*Compiled at MVP launch from the 2026-08-04/05 launch-readiness verification.
All production claims in this document were verified against the deployed
commit listed above.*
