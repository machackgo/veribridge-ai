# Contributing

This project is in its initial setup phase. Keep changes small, clear, and aligned with the monorepo structure.

## Branch Rules

- Use `main` for production-ready code only.
- Create feature branches from `main`.
- Use descriptive branch names:
  - `feature/student-profile`
  - `fix/api-health-check`
  - `docs/architecture-overview`
  - `chore/repo-config`

## Commit Rules

Use concise, conventional commit messages:

```text
type(scope): short description
```

Examples:

```text
feat(web): add onboarding layout
fix(api): validate profile payload
docs(roadmap): add milestone checklist
chore(repo): add gitignore and env template
```

Recommended commit types:

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation
- `chore`: Project maintenance
- `refactor`: Code change without behavior change
- `test`: Test changes
- `ci`: CI/CD changes

## Pull Request Expectations

- Keep pull requests focused.
- Include a short summary of what changed.
- Mention any environment variables, migrations, or deployment steps.
- Do not include secrets, API keys, production credentials, or private tokens.
- Add or update documentation when behavior or architecture changes.

## Local Environment

- Use `.env.example` as the source for required environment variables.
- Keep real `.env` files local.
- Never commit generated dependency folders, build outputs, or local cache files.
