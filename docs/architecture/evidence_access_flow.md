# Evidence Access Flow — Architecture Plan

Status: **Backend endpoints exist. Frontend integration plan documented here.**

---

## Current state (as of 2026-06-04)

### Backend (already implemented)
All endpoints exist in `apps/api/app/api/v1/endpoints/public_work_passport.py`
and `apps/api/app/services/public_work_passport_service.py`:

| Method | Route | Purpose |
|--------|-------|---------|
| `POST` | `/api/v1/public/passports/{slug}/request-access` | Recruiter creates access request |
| `GET`  | `/api/v1/student/extension-proof/sessions/{id}/access-requests` | Student lists requests |
| `POST` | `/api/v1/student/access-requests/{id}/approve` | Student approves with sections |
| `POST` | `/api/v1/student/access-requests/{id}/deny` | Student denies |
| `POST` | `/api/v1/student/access-grants/{id}/revoke` | Student revokes a grant |
| `GET`  | `/api/v1/public/access/{token}/evidence` | Recruiter reads protected evidence |

Frontend API wrappers exist in `apps/web/src/lib/passport-api.ts`:
`listAccessRequests`, `approveAccessRequest`, `denyAccessRequest`, `revokeAccessGrant`,
`requestPassportAccess`.

### Frontend (mock/dev — as of this task)
- Shared types: `apps/web/src/types/evidence-access.ts`
- Mock dev store: `apps/web/src/lib/mock-evidence-access-store.ts` (localStorage)
- Recruiter modal: `components/recruiter-passport/EvidenceAccessRequestModal.tsx`
- Student panel: `components/passport/StudentAccessRequestsPanel.tsx`

---

## Full flow (target)

```
Recruiter                            VeriBridge                        Student
─────────                            ──────────                        ───────
1. Visits /passport/{slug}
2. Clicks "Request Evidence Access"
3. Fills form (name, email, company,
   role, reason, evidence types)
4. Submits
                                     POST /public/passports/{slug}/request-access
                                     → creates evidence_access_requests row
                                     → notifies student (email/notification)
                                                                        5. Student sees new pending request
                                                                           in /dashboard/passport/access
                                                                        6. Reviews requester + reason
                                                                        7. Selects evidence categories
                                                                        8. Clicks "Approve selected access"
                                     POST /student/access-requests/{id}/approve
                                     → creates evidence_access_grants row
                                     → generates access_token (hashed, one-time)
                                     → returns access_token to student (shown once)
                                     → notifies recruiter (email)
9. Recruiter receives email with
   access link
10. GET /public/access/{token}/evidence
                                     → validates token (not expired, not revoked)
                                     → returns approved evidence sections (safe dict)
                                     → logs audit event
11. Recruiter views protected evidence
    (no raw transcripts, no private
    storage paths, no admin notes)

                                                                       12. Student can revoke any time:
                                     POST /student/access-grants/{id}/revoke
                                     → marks grant as revoked
                                     → future token requests return 403
```

---

## Privacy invariants

1. `access_token` is generated as `vrec_<32-byte-urlsafe>`, hashed (SHA-256) before DB storage.
   The plaintext is returned **once** in the approve response — never again.
2. `media_storage_path`, `video_url`, `transcript_text`, `proof_data`, and `admin_notes`
   are blocked by `_blocked_private_key()` in `_safe_dict()` before any evidence is serialised.
3. `project_defense_transcript` section is only included if explicitly in `granted_sections`.
4. All access events are written to `evidence_access_audit_events` for the audit trail.
5. Requester identity (email, org) is stored in `recruiter_requester_profiles` and linked
   to all requests — enabling the student to block or flag suspicious requesters.

---

## Next integration steps

### To connect recruiter modal to real backend

In `EvidenceAccessRequestModal`, the `onSubmit` prop receives `EvidenceAccessFormData`.
Wire it to `requestPassportAccess(publicSlug, { requester_name, requester_email, ... })` from
`passport-api.ts`.  The `publicSlug` must be threaded down from the passport page.

```ts
// In /passport/[slug]/page.tsx — already done for the public passport page.
// For the recruiter dashboard, thread the slug from the saved passport record.
```

### To connect student panel to real backend

In `StudentAccessRequestsPanel`, replace the mock store callbacks with the real API:

```ts
// Load:
const requests = await listAccessRequests(sessionId)

// Approve:
await approveAccessRequest(requestId, { sections: approvedSections })

// Deny:
await denyAccessRequest(requestId)

// Revoke (requires the grant ID, not the request ID):
await revokeAccessGrant(grantId)
```

Note: the current `approveAccessRequest` in `passport-api.ts` takes `requestId` +
`AccessRequestDecision`.  Map `approvedSections` → `decision.sections`.

### Audit trail

`evidence_access_audit_events` is already populated by the backend service.
An admin/student audit log UI can read it via a future endpoint if needed.

---

## Dev preview store

`apps/web/src/lib/mock-evidence-access-store.ts` is a **localStorage-backed** mock store
for development only.  It is imported only by:
- `src/app/dev/recruiter-passport-preview/page.tsx` (write on submit)
- `src/app/dev/student-access-requests/page.tsx` (read + update)

It must **never** be imported by production routes or components.
