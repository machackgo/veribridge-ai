# VeriBridge AI

VeriBridge AI helps verified students turn projects, coursework, resumes, and applications into evidence-backed career profiles recruiters and universities can trust.

This repository is the initial monorepo for the VeriBridge AI SaaS product. The frontend is scaffolded with Next.js, while the backend, shared package, infrastructure, and deeper product features are still intentionally lightweight.

## Tech Stack

- Frontend: Next.js, TypeScript, Tailwind CSS, shadcn/ui
- Backend: FastAPI, Python
- Database: Supabase PostgreSQL
- AI integrations: Claude and OpenAI APIs
- Future deployment: Vercel for frontend, Cloud Run or Render for backend
- Future CI/CD: GitHub Actions

## Repository Structure

```text
careerproof-ai/
  apps/
    web/                 # Next.js frontend app
    api/                 # FastAPI backend app
  packages/
    shared/              # Shared types, schemas, and utilities
  docs/
    architecture/        # Architecture notes and design decisions
    roadmap/             # Product and delivery roadmap documents
  infra/
    docker/              # Docker and local service configuration
    github-actions/      # CI/CD workflow references before moving to .github
  scripts/               # Project automation scripts
```

## Getting Started

1. Review `.env.example` and create local environment files when app integrations begin.
2. Place the roadmap file at `docs/roadmap/CareerProof_AI_12_Month_Roadmap.html`.
3. Run the frontend locally from `apps/web`.
4. Scaffold `apps/api` with FastAPI when backend work starts.
5. Define the first Supabase schema migrations before implementing data-backed features.

## Frontend Setup

The frontend app lives in `apps/web` and uses Next.js with TypeScript, Tailwind CSS, and the App Router.

```bash
cd apps/web
npm install
npm run dev
```

Open `http://localhost:3000` to view the landing page.

Useful frontend commands:

```bash
npm run lint
npm run build
```

## Development Principles

- Keep secrets out of Git.
- Keep frontend and backend boundaries clear.
- Prefer typed contracts between apps.
- Document meaningful architecture decisions.
- Build small, testable milestones before adding deployment automation.

## Current Status

Initial project structure and frontend scaffold are in place. Authentication, backend APIs, database schema, and AI features have not been implemented yet.
