# Data repair: recruiter-share consent stored as `public_safe`

**Date:** 2026-08 · **Fix:** G1 (MVP release-gap audit) · **Table:** `proof_artifacts`

## What happened

Two flows mapped the student's "share with recruiters" consent toggle to
`access_policy = 'public_safe'`, which admits **anyone including anonymous
callers** (`proof_artifact_service.can_access_artifact`). The consented scope
is recruiters, so both flows now write `recruiter_safe` (owner + authenticated
privileged recruiter/admin/reviewer callers only):

- `apps/api/app/api/v1/endpoints/document_proofs.py` — retained document
  original on upload (`artifact_type = 'document_original'`).
- `apps/api/app/services/video_proof_service.py`
  (`set_video_proof_visibility`) — sharing toggle propagated to every retained
  video-proof artifact (`artifact_type IN ('video_proof_original',
  'video_proof_frame', 'video_proof_transcript')`).

No other code path ever writes `public_safe` into `proof_artifacts`
(`workflow_visual_frames.py` registers `owner_only`; the service default is
`owner_only`), so every existing `public_safe` row with the artifact types
below was created by these two consent flows and carries the wrong scope.

## Repair (run once against production)

```sql
-- Narrow recruiter-consented artifacts from anonymous to recruiter scope.
-- `public_safe` is the denormalized mirror of (access_policy = 'public_safe')
-- (migration 056), so it must be cleared in the same statement.
UPDATE proof_artifacts
SET access_policy = 'recruiter_safe',
    public_safe   = false,
    updated_at    = now()
WHERE access_policy = 'public_safe'
  AND artifact_type IN (
    'document_original',
    'video_proof_original',
    'video_proof_frame',
    'video_proof_transcript'
  );
```

Verification:

```sql
SELECT artifact_type, access_policy, count(*)
FROM proof_artifacts
GROUP BY 1, 2
ORDER BY 1, 2;
-- Expect ZERO rows with access_policy = 'public_safe' for the four
-- artifact types above.
```

Not shipped as a numbered migration: the `apps/api/app/db/migrations/`
series contains schema migrations (backfills only alongside a schema change,
e.g. 037), and this is a pure data repair with no schema delta.
