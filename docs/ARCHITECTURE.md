# VeriBridge AI architecture

This document describes the system as it exists in this repository. For features, status and setup,
see the [README](../README.md).

## System overview

```mermaid
flowchart LR
  subgraph Clients
    B["Browser<br/>(student / recruiter / anonymous)"]
    X["Chrome MV3 extension<br/>apps/extension"]
  end

  subgraph Vercel
    W["Next.js 16 web app<br/>apps/web"]
  end

  subgraph Render
    A["FastAPI service<br/>apps/api"]
    PW["Playwright (Chromium)<br/>website verification"]
    ST["sentence-transformers<br/>semantic similarity"]
  end

  subgraph Supabase
    AUTH["Auth<br/>(email OTP, Google OAuth)"]
    DB[("Postgres<br/>73 SQL migrations, RLS on every migrated table")]
    S3[("Storage<br/>vbr-media, proof-artifacts")]
  end

  subgraph External["External / optional"]
    GH["GitHub REST API"]
    LLM["Optional LLM providers<br/>Anthropic or OpenAI-compatible"]
    TR["Optional transcription<br/>OpenAI Whisper or local faster-whisper"]
  end

  B -->|pages| W
  B -->|sign-in| AUTH
  W -->|"fetch + Bearer JWT"| A
  X -->|"session config, recording upload<br/>(Bearer JWT)"| A
  W <-->|"postMessage bridge"| X
  A -->|"verify JWT (HS256 secret or JWKS)"| AUTH
  A -->|"service-role client"| DB
  A -->|"service-role client"| S3
  A --> PW
  A --> ST
  A --> GH
  A -.->|"only when enabled"| LLM
  A -.->|"only when configured"| TR
```

- **Web (`apps/web`).** Next.js App Router, React 19, TypeScript, Tailwind. Every data call goes to
  the API through `src/lib/api.ts`, which attaches the Supabase access token. The browser uses the
  Supabase client only for authentication (`src/lib/supabase/`).
  `src/proxy.ts` redirects unauthenticated users away from `/student/**`, `/dashboard/**` and
  `/onboarding`. That redirect is a UX gate; the security boundary is the API.
- **API (`apps/api`).** FastAPI app with 72 router registrations under `/api/v1`
  (`app/api/v1/router.py`). Business logic lives in `app/services/`. Unit tests run against an
  in-memory dict store, so they never touch Supabase.
- **Extension (`apps/extension`).** Chrome Manifest V3, the "VeriBridge Website Proof Recorder".
  It records a student-started website demonstration (screen capture plus on-page evidence) and
  uploads it to the API for the session the web app configured. The extension and the web app talk
  through a content-script `window.postMessage` bridge. The recorder contract lives in
  `packages/shared/websiteProofRecorderContract.ts`; the extension imports it, and web tests check
  against it.
- **Supabase.**
  - Auth issues the JWTs.
  - Postgres holds all application data. The schema is `apps/api/app/db/migrations/` (`001` to `073`),
    applied in order. A fresh database currently needs the workarounds listed under
    [Local setup](../README.md#1-database-supabase) in the README.
  - Storage holds recorded media and retained proof artifacts. Buckets are private; the API streams
    the bytes. Proof-artifact signed URLs last at most 5 minutes; defense-recording playback URLs last 30 minutes.

## Evidence pipeline

```mermaid
flowchart TD
  P["Student creates a project<br/>(vbr_projects)"] --> E1 & E2 & E3 & E4
  E1["GitHub proof<br/>repo analysis via GitHub API"]
  E2["Website proof<br/>extension recording + live-site check<br/>+ Playwright browser run"]
  E3["Document proof<br/>PDF / DOCX parsing"]
  E4["Project Defense<br/>recorded Q&A about the project"]
  E1 & E2 & E3 & E4 --> C["Canonical evidence + claim synthesis<br/>(deterministic; optional LLM synthesis)"]
  C --> AT["Candidate attribution<br/>(project evidence is not candidate ownership)"]
  AT --> R["Verified Build Report<br/>(private student preview)"]
  R -->|"owner publishes"| PR["Public report<br/>/vbr/report/{token}"]
  R --> WP["Work Passport<br/>/p/{slug} + disclosure policy"]
  WP --> RS["Recruiter search index<br/>+ recruiter workspace"]
```

The design rules below are enforced in code:

- **Qualitative evidence labels, not numeric trust scores, on public surfaces.** See
  `vbr_public_project_report.py` and `public_report_safety_service.py`.
- **Project evidence is never presented as proof of personal authorship.** Attribution has its own
  states (`unknown`, `claimed_contributor`, `verified_contributor`, `denied_by_candidate`, `conflicted`, `verified_author`).
  See `candidate_attribution_service.py` and migration 071.
- **The deterministic path works with no model access.** LLM synthesis is off by default
  (`LLM_SYNTHESIS_ENABLED=false`, `LLM_SYNTHESIS_PROVIDER=disabled`). Transcription and
  visual/OCR analysis default to `none` and degrade to "not configured".

## Authentication and authorization

```mermaid
sequenceDiagram
  participant U as Browser
  participant SA as Supabase Auth
  participant API as FastAPI
  participant DB as Postgres (service role)
  U->>SA: email OTP / Google OAuth
  SA-->>U: access token (JWT)
  U->>API: request + Authorization: Bearer JWT
  API->>API: verify signature, exp, aud (app/core/auth.py)
  API->>DB: query with service-role client
  API->>API: ownership / role checks in service code
  API-->>U: response (or uniform 404/401/403)
```

- **JWT verification** (`app/core/auth.py`).
  - HS256 tokens are checked only against `SUPABASE_JWT_SECRET`.
  - ES256/RS256 tokens are checked only against the project's JWKS.
  - The header `alg` picks the key material, which prevents algorithm-confusion attacks.
  - Anything unverifiable fails closed.
- **Authorization is enforced in the application layer.** `get_db` returns a service-role client,
  which bypasses RLS, so every owner-scoped operation checks ownership explicitly (for example
  `get_owned_vbr_project_or_404`). Roles (student, recruiter, admin, reviewer) are resolved by
  `permission_service.py`.
- **RLS is defence in depth.** RLS is enabled on every table the migrations create, including the four proof/video tables
  added in migration 073; access is API-mediated with the service role. RLS limits what an anon or
  authenticated Supabase key could reach directly. It does **not** constrain the API itself,
  because the API uses the service-role key.
- **Public surfaces need no session.** These are the public passport `/p/{slug}`, report links
  `/vbr/report/{token}`, and Beam/QR links.
  - Report tokens come from `secrets.token_urlsafe(24)` and are stored in
    `vbr_projects.public_report_token`. They have no expiry; unpublishing clears the token.
  - A report resolves only while the owner's Work Passport is public and the disclosure policy
    allows it.
  - Unknown, revoked and hidden reports all return the same 404.
- **Demo user fallback.** It works only outside `ENVIRONMENT=production` and only when
  `ENABLE_DEMO_USER_FALLBACK=true`.

## Deployment

| Component | Host | Notes |
|---|---|---|
| Web app and landing page | Vercel | `https://veribridgeai.com` |
| API | Render (`veribridge-api.onrender.com`) | **Currently suspended.** The service answers `503 Service Suspended`. |
| Database, Auth, Storage | Supabase | Migrations are applied manually (SQL editor or the `scripts/apply_*.py` helpers). |
| Extension | Chrome Web Store | Release build via `npm run build:release` / `npm run package:release` |

Infrastructure is configured in each provider's dashboard. The repository has no deployment
manifests (no `render.yaml`, `vercel.json` or Dockerfile) and no CI workflow. `infra/docker` and
`infra/github-actions` are empty placeholders.
