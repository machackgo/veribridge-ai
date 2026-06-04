/**
 * Shared evidence access request types — used by both the recruiter-side
 * EvidenceAccessRequestModal and the student-side StudentAccessRequestsPanel.
 *
 * When the backend is connected these map directly to the response shapes
 * returned by:
 *   POST /api/v1/public/passports/{slug}/request-access  (recruiter creates)
 *   GET  /api/v1/student/extension-proof/sessions/{id}/access-requests  (student lists)
 *   POST /api/v1/student/access-requests/{id}/approve   (student approves)
 *   POST /api/v1/student/access-requests/{id}/deny      (student denies)
 *   POST /api/v1/student/access-grants/{id}/revoke      (student revokes)
 *
 * Privacy rules: never include media_storage_path, private storage URLs,
 * access tokens, raw transcripts, admin notes, or debug metadata.
 */

// ── Evidence type keys ────────────────────────────────────────────────────────

export const EVIDENCE_TYPE_KEYS = [
  "workflow_recordings",
  "project_defense_media",
  "uploaded_documents",
  "detailed_skill_evidence",
] as const

export type EvidenceTypeKey = typeof EVIDENCE_TYPE_KEYS[number]

export const EVIDENCE_TYPE_LABELS: Record<EvidenceTypeKey, string> = {
  workflow_recordings:    "Workflow recordings",
  project_defense_media:  "Project defense media / transcript",
  uploaded_documents:     "Uploaded documents / reports",
  detailed_skill_evidence: "Detailed skill evidence",
}

/** Normalise legacy section keys (from backend) to canonical EvidenceTypeKey. */
export function normaliseEvidenceKey(raw: string): EvidenceTypeKey | string {
  const MAP: Record<string, EvidenceTypeKey> = {
    workflow_recordings:     "workflow_recordings",
    workflow:                "workflow_recordings",
    workflow_analysis:       "workflow_recordings",
    project_defense:         "project_defense_media",
    project_defense_media:   "project_defense_media",
    documents:               "uploaded_documents",
    uploaded_documents:      "uploaded_documents",
    detailed_skill_evidence: "detailed_skill_evidence",
    evidence:                "detailed_skill_evidence",
  }
  return MAP[raw] ?? raw
}

export function evidenceLabel(key: string): string {
  const normalised = normaliseEvidenceKey(key) as EvidenceTypeKey
  return EVIDENCE_TYPE_LABELS[normalised] ?? key.replace(/_/g, " ")
}

// ── Status ────────────────────────────────────────────────────────────────────

export type EvidenceAccessStatus = "pending" | "approved" | "denied" | "revoked"

// ── Core shared type ──────────────────────────────────────────────────────────

export type EvidenceAccessRequest = {
  /** Stable request ID — matches backend `id` field. */
  id: string
  /** Public slug of the student's Work Passport. */
  passportSlug?: string | null
  /** Backend session ID — present when loaded from the student's dashboard. */
  sessionId?: string | null
  requesterName: string
  requesterEmail: string
  company?: string | null
  role?: string | null
  reason?: string | null
  message?: string | null
  /** Evidence categories the recruiter is requesting access to. */
  requestedEvidenceTypes: string[]
  /** Evidence categories the student has approved (subset of requestedEvidenceTypes). */
  approvedEvidenceTypes?: string[]
  status: EvidenceAccessStatus
  requestedAt: string   // ISO-8601
  decidedAt?: string | null
  expiresAt?: string | null
}

// ── Recruiter form input type ─────────────────────────────────────────────────

export type EvidenceAccessFormInput = {
  requesterName: string
  requesterEmail: string
  company: string
  role: string
  reason: string
  requestedEvidenceTypes: string[]
  messageToStudent: string
}

// ── Mapper helpers ─────────────────────────────────────────────────────────────

/**
 * Convert a backend EvidenceAccessRequestResponse (from passport-api.ts) to
 * the shared EvidenceAccessRequest shape.  Safe to call even when optional
 * fields are absent.
 */
export function fromBackendRequest(r: {
  id: string
  requester_name: string
  requester_email: string
  requester_organization?: string | null
  requester_role?: string | null
  request_reason?: string | null
  requested_sections: string[]
  status: string
  created_at?: string
  decided_at?: string | null
  expires_at?: string | null
}): EvidenceAccessRequest {
  return {
    id: r.id,
    requesterName: r.requester_name,
    requesterEmail: r.requester_email,
    company: r.requester_organization ?? null,
    role: r.requester_role ?? null,
    reason: r.request_reason ?? null,
    requestedEvidenceTypes: r.requested_sections,
    status: (r.status as EvidenceAccessStatus) ?? "pending",
    requestedAt: r.created_at ?? new Date().toISOString(),
    decidedAt: r.decided_at ?? null,
    expiresAt: r.expires_at ?? null,
  }
}
