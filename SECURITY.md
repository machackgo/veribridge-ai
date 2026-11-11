# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability** (GitHub private vulnerability reporting). This opens a draft
   Security Advisory that only the maintainer can see.

Do not open a public issue, pull request or discussion for a suspected vulnerability.

A useful report includes:

- the affected component (`apps/api`, `apps/web`, `apps/extension`, or a migration) and the
  commit you tested;
- steps to reproduce, or a proof of concept against a **local** setup;
- the impact you expect (for example data exposure, privilege escalation, denial of service).

This is a solo project, so there is no guaranteed response time. Reports are acknowledged on a
best-effort basis, and fixes are published through the Security Advisory once they land.

## Supported versions

Only the `main` branch is supported. Other branches, tags and older Chrome extension builds do not
receive security fixes.

| Version | Supported |
|---|---|
| `main` | Yes |
| Anything else | No |

## Scope

In scope:

- the FastAPI service in `apps/api`, including authentication, authorization and the public
  passport/report surfaces;
- the Next.js web app in `apps/web`;
- the Chrome extension in `apps/extension`;
- the SQL migrations in `apps/api/app/db/migrations` (Row Level Security, storage policies).

Out of scope:

- third-party services the project uses (Supabase, Vercel, Render, GitHub, the Chrome Web Store).
  Report those to the vendor;
- vulnerabilities in dependencies with no demonstrated impact on this project. Please report
  them upstream;
- the prototypes and design exports under `docs/design`, which are not deployed;
- denial-of-service through volume alone, social engineering, and physical attacks.

Test only against your own local instance (see [Local setup](README.md#local-setup)). Do not
probe the hosted deployment, and do not access, change or delete data that is not yours.

## Secrets

Never commit secrets: API keys, service-role keys, JWT secrets, database URLs with passwords,
signing certificates, or real `.env` files. Configuration goes in untracked `.env` / `.env.local`
files created from the `.env.example` templates, which contain placeholders only. If a secret is
committed by mistake, treat it as exposed: rotate it first, then remove it from history.

## Security model

How authentication, authorization, Row Level Security, the public surfaces and the deployment
guards work is described in the [Security model](README.md#security-model) section of the README.
These controls have not been independently audited.
