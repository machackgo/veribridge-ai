# Canonical report routes (MVP)

Decided 2026-07-10 as part of the Passport + Verified Build Report MVP integration.

## Canonical recruiter-facing report — Verified Build Report (per project)

| Surface | Route | Backend |
|---|---|---|
| Owner preview | `/student/vbr/projects/{projectId}/report` | `GET /api/v1/student/vbr/projects/{id}/report` → `build_student_vbr_report` |
| Public (recruiter, no login) | `/vbr/report/{token}` | `GET /api/v1/public/vbr/reports/{token}` → `build_public_project_report` (scrubbed, no LLM) |

Publish/unpublish: `POST`/`DELETE /api/v1/student/vbr/projects/{id}/public-report`
(token = `vbr_projects.public_report_token`, revocation clears it; old links 404).

The report is proof-native: GitHub proof summary, Website Proof workflow evidence,
Project Defense inspection (transcript timestamps), Document proof, deployed-URL
check, skill-evidence matrix, evidence traces, and limitations. Every section
renders from persisted evidence; missing proof types read "Not assessed", never a
zero score.

## Work Passport (private evidence map vs public)

- Private map: `/student/vbr/passport` (skills evidence map: 4-tier relationship
  model `direct / attached / vault / suggested`, honest connected-project counts,
  suggested-only skills hidden by default).
- Public passport: `/p/{slug}` (published projects only, links to published
  Verified Build Reports). `/passport/{slug}` permanently redirects to `/p/{slug}`.
- Skill report: `/student/vbr/passport/skills/{skillSlug}` (owner) and
  `/p/{slug}/skills/{skillSlug}` (public, fail-closed).
- Beam short links `/b/{code}` resolve onto `/p/{slug}` (revocable/rotatable).

## Legacy / demoted (kept only for already-shared links)

- `/r/{token}` + `GET /api/v1/public/vbr/legacy-reports/{token}` — the old
  session-scoped generic report (`vbr_reports`). No UI links into it; the
  session report-generation endpoints in `vbr_sessions.py` have no callers in the
  web app. Guarded by `apps/web/src/__tests__/legacy-report-demotion.test.ts`.
- The extension-proof-era passport stack (`/dashboard/passport/*`, `/recruiter/*`,
  `public_work_passport.py` export/access-grant endpoints) is a parallel legacy
  universe; it is not linked from the VBR student flow and is out of MVP scope.

Do not add new recruiter report surfaces; extend the Verified Build Report.
