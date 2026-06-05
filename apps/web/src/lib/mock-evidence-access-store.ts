/**
 * Development/mock store only — replace with backend API calls before production.
 *
 * Provides a localStorage-backed store so that:
 *  - A recruiter submitting a request in /dev/recruiter-passport-preview
 *    persists the request locally.
 *  - The student dev page (/dev/student-access-requests) and the dashboard
 *    access page (/dashboard/passport/access) read the same localStorage key
 *    and show the pending request.
 *
 * Key: "vb_dev_access_requests"
 *
 * Privacy: never stores media_storage_path, private storage URLs, access
 * tokens, raw transcripts, admin notes, or debug metadata.
 */

import type { EvidenceAccessRequest, EvidenceAccessStatus, EvidenceAccessFormInput } from "../types/evidence-access"

// ── Canonical demo passport slug ──────────────────────────────────────────────
// All dev/mock pages must use this constant so recruiter, student dev, and
// student dashboard all operate on the same requests.

export const DEMO_PASSPORT_SLUG = "maya-reyes-ai-wpi-preview"

// ── Default sample requests (shown when store is empty) ───────────────────────

const SAMPLE_REQUESTS: EvidenceAccessRequest[] = [
  {
    id: "sample-stripe-001",
    passportSlug: DEMO_PASSPORT_SLUG,
    requesterName: "Stripe Early Talent",
    requesterEmail: "recruiter@stripe.com",
    company: "Stripe",
    role: "Early Talent / AI Intern Hiring",
    reason: "Reviewing your profile for an AI internship role on our applied ML team.",
    message: "Hi! We're excited about your browser ML project and would love to see the full evidence.",
    requestedEvidenceTypes: ["workflow_recordings", "project_defense_media", "detailed_skill_evidence"],
    status: "pending",
    requestedAt: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(),
  },
  {
    id: "sample-wpi-002",
    passportSlug: DEMO_PASSPORT_SLUG,
    requesterName: "WPI Faculty Reviewer",
    requesterEmail: "faculty@wpi.edu",
    company: "Worcester Polytechnic Institute",
    role: "Faculty / Academic Reviewer",
    reason: "Portfolio review for graduate program research credit assessment.",
    requestedEvidenceTypes: ["uploaded_documents", "detailed_skill_evidence"],
    approvedEvidenceTypes: ["uploaded_documents", "detailed_skill_evidence"],
    status: "approved",
    requestedAt: new Date(Date.now() - 8 * 24 * 60 * 60 * 1000).toISOString(),
    decidedAt: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
  },
]

const STORE_KEY = "vb_dev_access_requests"

// ── Persistence helpers ───────────────────────────────────────────────────────

function load(): EvidenceAccessRequest[] {
  if (typeof window === "undefined") return [...SAMPLE_REQUESTS]
  try {
    const raw = window.localStorage.getItem(STORE_KEY)
    if (!raw) return [...SAMPLE_REQUESTS]
    const parsed = JSON.parse(raw) as EvidenceAccessRequest[]
    return Array.isArray(parsed) ? parsed : [...SAMPLE_REQUESTS]
  } catch {
    return [...SAMPLE_REQUESTS]
  }
}

function save(requests: EvidenceAccessRequest[]): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(STORE_KEY, JSON.stringify(requests))
  } catch {
    // localStorage unavailable (private browsing / quota) — silently continue
  }
}

// ── Public API ────────────────────────────────────────────────────────────────

/** Return all requests from the store (falls back to sample data). */
export function listStudentAccessRequests(): EvidenceAccessRequest[] {
  return load()
}

/**
 * Create or update an access request (upsert by requesterEmail + passportSlug).
 *
 * If a request from the same recruiter email for the same passport already
 * exists, it is updated to a fresh pending state rather than creating a
 * duplicate entry.  This prevents stale duplicate pending requests accumulating
 * in the store across multiple test submissions.
 */
export function createAccessRequest(
  input: EvidenceAccessFormInput,
  passportSlug?: string,
): EvidenceAccessRequest {
  const requests = load()
  const slug = passportSlug ?? null
  const now = new Date().toISOString()

  // Upsert: find existing request from same recruiter for same passport
  const existingIdx =
    slug && input.requesterEmail
      ? requests.findIndex(
          (r) => r.passportSlug === slug && r.requesterEmail === input.requesterEmail,
        )
      : -1

  if (existingIdx !== -1) {
    const existing = requests[existingIdx]
    // Never silently override an approved grant — recruiter must reset explicitly.
    if (existing.status === "approved") {
      return existing
    }
    // For pending / denied / revoked: update to fresh pending.
    const updated: EvidenceAccessRequest = {
      id: existing.id,
      passportSlug: slug,
      requesterName: input.requesterName,
      requesterEmail: input.requesterEmail,
      company: input.company || null,
      role: input.role || null,
      reason: input.reason || null,
      message: input.messageToStudent || null,
      requestedEvidenceTypes: input.requestedEvidenceTypes,
      status: "pending",
      requestedAt: now,
      decidedAt: null,
    }
    const rest = requests.filter((_, i) => i !== existingIdx)
    save([updated, ...rest])
    return updated
  }

  const request: EvidenceAccessRequest = {
    id: `req-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    passportSlug: slug,
    requesterName: input.requesterName,
    requesterEmail: input.requesterEmail,
    company: input.company || null,
    role: input.role || null,
    reason: input.reason || null,
    message: input.messageToStudent || null,
    requestedEvidenceTypes: input.requestedEvidenceTypes,
    status: "pending",
    requestedAt: now,
  }
  save([request, ...requests])
  return request
}

/** Approve a request and record the approved evidence types. */
export function approveAccessRequest(
  id: string,
  approvedSections: string[],
): EvidenceAccessRequest | null {
  const requests = load()
  const idx = requests.findIndex((r) => r.id === id)
  if (idx === -1) return null
  requests[idx] = {
    ...requests[idx],
    status: "approved",
    approvedEvidenceTypes: approvedSections,
    decidedAt: new Date().toISOString(),
  }
  save(requests)
  return requests[idx]
}

/** Deny a request. */
export function denyAccessRequest(id: string): EvidenceAccessRequest | null {
  const requests = load()
  const idx = requests.findIndex((r) => r.id === id)
  if (idx === -1) return null
  requests[idx] = {
    ...requests[idx],
    status: "denied",
    decidedAt: new Date().toISOString(),
  }
  save(requests)
  return requests[idx]
}

/** Revoke a previously-approved grant. */
export function revokeAccessRequest(id: string): EvidenceAccessRequest | null {
  const requests = load()
  const idx = requests.findIndex((r) => r.id === id)
  if (idx === -1) return null
  requests[idx] = {
    ...requests[idx],
    status: "revoked",
    decidedAt: new Date().toISOString(),
  }
  save(requests)
  return requests[idx]
}

/** Reset the store to sample data (useful for dev testing). */
export function resetAccessRequestStore(): void {
  save([...SAMPLE_REQUESTS])
}

/** Clear the store entirely. */
export function clearAccessRequestStore(): void {
  if (typeof window === "undefined") return
  try { window.localStorage.removeItem(STORE_KEY) } catch { /* ignore */ }
}

/**
 * Clear all mock evidence access requests from the canonical localStorage key.
 * Named alias for clearAccessRequestStore — use in dev UX reset controls and tests.
 * After clearing, listStudentAccessRequests() falls back to sample data.
 */
export function clearMockEvidenceAccessRequests(): void {
  clearAccessRequestStore()
}
