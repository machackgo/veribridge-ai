# CareerProof AI

CareerProof AI is a production-oriented SaaS platform for helping students plan, prepare, and improve their career outcomes with AI-assisted workflows.

This repository is the initial monorepo scaffold. It is intentionally lightweight: the frontend, backend, shared package, infrastructure, and documentation folders are present, but application code has not been implemented yet.

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

1. Review `.env.example` and create local environment files when app scaffolding begins.
2. Place the roadmap file at `docs/roadmap/CareerProof_AI_12_Month_Roadmap.html`.
3. Scaffold `apps/web` with Next.js when frontend work starts.
4. Scaffold `apps/api` with FastAPI when backend work starts.
5. Define the first Supabase schema migrations before implementing data-backed features.

## Development Principles

- Keep secrets out of Git.
- Keep frontend and backend boundaries clear.
- Prefer typed contracts between apps.
- Document meaningful architecture decisions.
- Build small, testable milestones before adding deployment automation.

## Current Status

Initial project structure and documentation scaffold only. No production application code has been added yet.
