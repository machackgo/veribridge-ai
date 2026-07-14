/**
 * VeriBridge Work Passport API client.
 * Covers all new backend modules from the MVP build phase.
 */

"use client"

import { fetchAPI } from "./api"
import { PUBLIC_API_BASE } from "./api-base"
import {
  withRecruiterTokenHeader,
  clearRecruiterSession,
} from "./recruiter-session"

const API = "/api/v1"

/** Base URL for direct fetch calls (recruiter public endpoints don't use Supabase auth). */
// Prefer NEXT_PUBLIC_API_URL (production domain, e.g. https://api.veribridgeai.com);
// fall back to the legacy NEXT_PUBLIC_API_BASE_URL, then to local dev.
const API_BASE_URL = PUBLIC_API_BASE

// ─── Shared helpers ────────────────────────────────────────────────────────

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetchAPI(path, init)
  if (!res.ok) {
    const text = await res.text().catch(() => "")
    throw new Error(`API ${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

/**
 * Fetch helper for private recruiter endpoints.
 *
 * Adds X-Recruiter-Token from sessionStorage.  On 401 the session is cleared
 * and a user-facing error is thrown prompting re-authentication.
 * Token is NEVER logged.
 */
async function recruiterApiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = withRecruiterTokenHeader({
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) ?? {}),
  })
  const res = await fetch(`${API_BASE_URL}${path}`, { ...init, headers })

  if (res.status === 401) {
    clearRecruiterSession()
    const raw = await res.text().catch(() => "")
    let msg = "Recruiter session expired. Please re-enter your email to continue."
    try {
      const parsed = JSON.parse(raw) as { detail?: { message?: string } | string }
      const d = parsed.detail
      if (d && typeof d === "object" && typeof d.message === "string") msg = d.message
      else if (typeof d === "string") msg = d
    } catch { /* not JSON */ }
    throw new Error(msg)
  }

  if (res.status === 204) return undefined as unknown as T

  if (!res.ok) {
    const text = await res.text().catch(() => "")
    throw new Error(`API ${res.status}: ${text}`)
  }

  return res.json() as Promise<T>
}

// ─── Types ─────────────────────────────────────────────────────────────────

export type WorkPassportIssue = {
  code: string
  label: string
  description: string
  source: string
  severity: "info" | "low" | "normal" | "high" | "urgent"
  recommended_fix?: string | null
}

export type SkillEvidenceSummary = {
  strong_skill_count: number
  partial_skill_count: number
  missing_skill_count: number
}

export type WorkPassportStatusResponse = {
  proof_session_id: string
  overall_status: string
  status_label: string
  status_description: string
  readiness_score?: number | null
  readiness_level?: string | null
  ai_review_status?: string | null
  ai_domain_review_status?: string | null
  ai_domain_reviewer_name?: string | null
  ai_domain_review_score?: number | null
  project_defense_status?: string | null
  project_defense_score?: number | null
  privacy_status?: string | null
  public_passport_status?: string | null
  public_slug?: string | null
  active_version_id?: string | null
  active_version_number?: number | null
  admin_review_status?: string | null
  open_admin_case_count: number
  pending_access_request_count: number
  active_access_grant_count: number
  unread_notification_count: number
  skill_evidence_summary?: SkillEvidenceSummary | null
  blocking_issues: WorkPassportIssue[]
  warnings: WorkPassportIssue[]
  completed_steps: string[]
  missing_steps: string[]
  recommended_next_action?: string | null
  recruiter_safe_summary: string
  student_next_steps: string[]
  generated_at: string
}

export type PublicWorkPassportStatusResponse = {
  overall_status: string
  status_label: string
  readiness_level?: string | null
  ai_review_status?: string | null
  ai_domain_review_status?: string | null
  privacy_status?: string | null
  public_passport_status?: string | null
  recruiter_safe_summary: string
  generated_at: string
}

export type SkillEvidenceItem = {
  evidence_type: string
  source_label: string
  summary: string
  support_strength: "strong" | "partial" | "weak"
  confidence_score: number
  created_at?: string | null
  public_safe: boolean
  protected: boolean
  reference_id?: string | null
  evidence_url?: string | null
  limitations: string[]
}

export type SkillEvidenceRecord = {
  skill_name: string
  normalized_skill_name: string
  support_level: "strong" | "partial" | "weak" | "missing"
  confidence_score: number
  evidence_count: number
  evidence_sources: string[]
  public_safe: boolean
  recruiter_visible: boolean
  evidence_items: SkillEvidenceItem[]
  gaps: string[]
  recommended_next_steps: string[]
  last_updated_at?: string | null
}

export type SkillEvidenceTimelineResponse = {
  proof_session_id: string
  skills: SkillEvidenceRecord[]
  generated_at: string
}

export type GitHubProofResponse = {
  id: string
  user_id?: string
  proof_session_id?: string | null
  repo_url: string
  repo_owner?: string | null
  repo_name?: string | null
  default_branch?: string | null
  visibility?: string | null
  status: string
  submitted_skill_claims: string[]
  detected_skills: string[]
  analysis_summary?: string | null
  evidence_strength?: string | null
  confidence_score?: number | null
  risk_flags?: string[]
  missing_evidence: string[]
  public_safe_summary?: string | null
  analysis_snapshot?: Record<string, unknown>
  last_analyzed_at?: string | null
  created_at: string
  updated_at: string
  /** Canonical project relationship — the SAME rows the Passport/report read. */
  project_id?: string | null
  project_title?: string | null
  project_relationship_state?: string
}

/**
 * Result of syncing an analyzed GitHub proof into the student's
 * Skill Graph (skill_evidence_pipelines / skill_evidence_artifacts).
 */
export type GitHubProofSyncResult = {
  ok: boolean
  already_synced: boolean
  skills_synced: string[]
  pipelines_upserted: number
  artifacts_created: number
  errors: string[]
}

export type GitHubProofPublicResponse = {
  id: string
  proof_session_id?: string | null
  repo_url: string
  repo_owner?: string | null
  repo_name?: string | null
  default_branch?: string | null
  visibility?: string | null
  status: string
  submitted_skill_claims: string[]
  detected_skills: string[]
  analysis_summary?: string | null
  evidence_strength?: string | null
  confidence_score?: number | null
  public_safe_summary?: string | null
  missing_evidence: string[]
  last_analyzed_at?: string | null
  created_at: string
  updated_at: string
}

export type NotificationResponse = {
  id: string
  event_type: string
  category: string
  priority: "low" | "normal" | "high" | "urgent"
  title?: string | null
  message?: string | null
  action_url?: string | null
  action_label?: string | null
  status: string
  read_at?: string | null
  archived_at?: string | null
  dismissed_at?: string | null
  delivery_status?: string | null
  metadata: Record<string, unknown>
  created_at: string
}

export type NotificationUnreadCountResponse = { unread_count: number }

export type EvidenceAccessRequestResponse = {
  id: string
  user_id: string
  proof_session_id: string
  passport_id: string
  requester_profile_id?: string | null
  requester_name: string
  requester_email: string
  requester_organization?: string | null
  requester_role?: string | null
  request_reason?: string | null
  status: "pending" | "approved" | "denied" | "revoked"
  requested_sections: string[]
  decision_notes?: string | null
  decided_at?: string | null
  expires_at?: string | null
  created_at: string
  updated_at: string
}

export type EvidenceAccessGrantResponse = {
  id: string
  user_id: string
  access_request_id?: string | null
  passport_id?: string | null
  access_token: string
  requester_email?: string | null
  granted_sections: string[]
  expires_at?: string | null
  revoked_at?: string | null
  created_at: string
}

export type RecruiterRequesterProfileResponse = {
  id: string
  email: string
  name?: string | null
  organization?: string | null
  domain?: string | null
  role?: string | null
  requester_type?: string | null
  verification_status: string
  email_verified: boolean
  domain_verified: boolean
  risk_flags: string[]
  notes?: string | null
  last_seen_at?: string | null
  created_at: string
}

export type AccessRequestDecision = {
  notes?: string | null
  expires_at?: string | null
}

export type AccessRequestCreate = {
  requester_name: string
  requester_email: string
  requester_organization?: string | null
  requester_role?: string | null
  request_reason?: string | null
  requested_sections?: string[]
}

export type AccessRequestPublicResponse = {
  id: string
  passport_id: string
  public_slug: string
  requester_name: string
  requester_email: string
  requester_organization?: string | null
  status: string
  requested_sections: string[]
  created_at: string
}

export type PublicPassportSafeResponse = {
  id: string
  public_slug: string
  proof_session_id: string
  student_display_name?: string | null
  field?: string | null
  public_title?: string | null
  public_summary?: string | null
  visible_sections: string[]
  ai_reviewed_status?: string | null
  ai_domain_review_summary?: string | null
  ai_domain_reviewer_name?: string | null
  ai_domain_review_status?: string | null
  verified_skills: string[]
  partially_verified_skills: string[]
  skills_needing_more_evidence: string[]
  readiness_score?: number | null
  readiness_level?: string | null
  public_project_links: { label: string; url: string }[]
  disclosure_note: string
  access_request_available: boolean
}

export type PublicWorkPassportStudentResponse = {
  id: string
  user_id: string
  proof_session_id: string
  public_slug: string
  is_public: boolean
  public_title?: string | null
  public_summary?: string | null
  field?: string | null
  visible_sections: string[]
  public_url_path: string
  created_at: string
  updated_at: string
}

export type RecruiterSavedPassportResponse = {
  id: string
  requester_profile_id: string
  passport_id: string
  proof_session_id: string
  student_user_id: string
  requester_email: string
  organization_name?: string | null
  status: string
  tags: string[]
  private_notes?: string | null
  reviewed_sections: string[]
  fit_score?: number | null
  fit_reason?: string | null
  last_viewed_at?: string | null
  public_slug?: string | null
  public_title?: string | null
  public_summary?: string | null
  field?: string | null
  created_at: string
  updated_at: string
}

export type RecruiterSavedPassportCreate = {
  requester_email: string
  requester_name?: string | null
  organization_name?: string | null
  status?: string
  tags?: string[]
  private_notes?: string | null
}

export type RecruiterSavedPassportUpdate = {
  /** Retained for backward compatibility; ignored by the backend (identity comes from X-Recruiter-Token). */
  requester_email?: string | null
  status?: string | null
  tags?: string[] | null
  private_notes?: string | null
  fit_score?: number | null
  fit_reason?: string | null
}

export type RecruiterCandidateComparisonRequest = {
  requester_email: string
  saved_passport_ids: string[]
  role_title?: string | null
  required_skills?: string[]
  preferred_skills?: string[]
}

export type RecruiterCandidateComparisonResponse = {
  id: string
  requester_email: string
  role_title?: string | null
  required_skills: string[]
  preferred_skills: string[]
  candidate_count: number
  comparison_results: RecruiterCandidateResult[]
  overall_disclaimer: string
  generated_at: string
}

export type RecruiterCandidateResult = {
  saved_passport_id: string
  passport_id?: string | null
  public_slug?: string | null
  student_display_name?: string | null
  field?: string | null
  match_signal_score?: number | null
  match_signal_label?: string | null
  strong_skill_matches: string[]
  partial_skill_matches: string[]
  missing_required_skills: string[]
  missing_preferred_skills: string[]
  evidence_strength_summary?: string | null
  recommended_follow_up?: string | null
  disclaimer: string
}

// Analytics sub-types (mirror backend schemas exactly)
export type RequestedSectionSummary = {
  section: string
  count: number
}

export type RequesterOrganizationSummary = {
  organization_name: string | null
  organization_domain: string | null
  request_count: number
  unique_requester_emails: number
}

export type WorkPassportActivityItem = {
  event_type: string
  event_summary: string | null
  actor_type: string | null
  actor_email: string | null
  requester_organization: string | null
  proof_session_id: string | null
  passport_id: string | null
  created_at: string
}

export type WorkPassportAnalyticsResponse = {
  total_passports: number
  total_public_views: number
  total_access_requests: number
  pending_access_requests: number
  approved_access_requests: number
  denied_access_requests: number
  revoked_access_grants: number
  active_access_grants: number
  protected_evidence_views: number
  unique_requester_emails: number
  unique_requester_organizations: number
  top_requested_sections: RequestedSectionSummary[]
  recent_activity: WorkPassportActivityItem[]
  requester_organizations: RequesterOrganizationSummary[]
  unread_notifications: number
  generated_at: string
}

export type ProofVersionResponse = {
  id: string
  user_id: string
  proof_session_id: string
  version_number: number
  status: string
  version_label?: string | null
  snapshot_summary?: Record<string, unknown> | null
  change_reason?: string | null
  submitted_skills: string[]
  created_at: string
  updated_at: string
}

export type AdminQualityReviewCaseResponse = {
  id: string
  user_id: string
  proof_session_id: string
  case_type: string
  status: string
  priority: string
  title: string
  description?: string | null
  admin_notes?: string | null
  decision?: string | null
  decision_notes?: string | null
  requested_student_actions: string[]
  resolved_at?: string | null
  created_at: string
  updated_at: string
}

export type AdminQualityReviewEventResponse = {
  id: string
  case_id: string
  event_type: string
  actor_type: string
  actor_user_id?: string | null
  summary: string
  notes?: string | null
  metadata?: Record<string, unknown> | null
  created_at: string
}

export type CurrentUserPermissionsResponse = {
  user_id: string
  roles: string[]
  permissions: string[]
  is_admin: boolean
  is_student: boolean
  is_recruiter: boolean
  is_reviewer: boolean
  dashboard_access: {
    student: boolean
    recruiter: boolean
    admin: boolean
    reviewer: boolean
  }
}

// ─── Work Passport Status ──────────────────────────────────────────────────

export function getWorkPassportStatus(sessionId: string): Promise<WorkPassportStatusResponse> {
  return apiJson(`${API}/student/extension-proof/sessions/${sessionId}/work-passport-status`)
}

export function getPublicWorkPassportStatus(publicSlug: string): Promise<PublicWorkPassportStatusResponse> {
  return apiJson(`${API}/public/passports/${publicSlug}/status`)
}

// ─── Skill Evidence Timeline ───────────────────────────────────────────────

export function getSkillEvidenceTimeline(sessionId: string): Promise<SkillEvidenceTimelineResponse> {
  return apiJson(`${API}/student/extension-proof/sessions/${sessionId}/skill-evidence-timeline`)
}

export function getPublicSkillEvidenceTimeline(publicSlug: string): Promise<SkillEvidenceTimelineResponse> {
  return apiJson(`${API}/public/passports/${publicSlug}/skill-evidence-timeline`)
}

// ─── GitHub Proofs ─────────────────────────────────────────────────────────

export function listGitHubProofs(sessionId?: string): Promise<GitHubProofResponse[]> {
  const qs = sessionId ? `?proof_session_id=${encodeURIComponent(sessionId)}` : ""
  return apiJson(`${API}/student/github-proofs${qs}`)
}

export function getGitHubProof(proofId: string): Promise<GitHubProofResponse> {
  return apiJson(`${API}/student/github-proofs/${proofId}`)
}

export function submitGitHubProof(body: {
  repo_url: string
  proof_session_id?: string | null
  submitted_skill_claims?: string[]
}): Promise<GitHubProofResponse> {
  return apiJson(`${API}/student/github-proofs`, {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export function analyzeGitHubProof(proofId: string): Promise<GitHubProofResponse> {
  return apiJson(`${API}/student/github-proofs/${proofId}/analyze`, { method: "POST" })
}

export function archiveGitHubProof(proofId: string): Promise<GitHubProofResponse> {
  return apiJson(`${API}/student/github-proofs/${proofId}/archive`, { method: "POST" })
}

/**
 * Sync an analyzed GitHub proof into the student's Skill Graph.
 * Idempotent on the backend — safe to call multiple times for the same proof.
 * Throws an Error with the backend message on failure so callers can show it.
 */
export function syncGitHubProofToSkillGraph(githubProofId: string): Promise<GitHubProofSyncResult> {
  return apiJson(`${API}/student/skill-pipelines/from-github-proof/${githubProofId}`, { method: "POST" })
}

export function getPublicGitHubProofs(publicSlug: string): Promise<GitHubProofPublicResponse[]> {
  return apiJson(`${API}/public/passports/${publicSlug}/github-proofs`)
}

// ─── Document Proofs ───────────────────────────────────────────────────────

export type DocumentProofSourceType = "document" | "certificate_transcript"

export type DocumentProofResponse = {
  id: string
  user_id?: string
  source_type: DocumentProofSourceType
  status: string
  filename?: string | null
  title?: string | null
  claimed_skills: string[]
  description?: string | null
  analysis_json: Record<string, unknown>
  evidence_objects: Array<Record<string, unknown>>
  created_at?: string | null
  /** Original-file retention (migration 056): opaque artifact id only. */
  original_retained?: boolean
  original_artifact_id?: string | null
  /**
   * Canonical project relationship — the SAME rows the Passport and reports
   * read. Attachment status must render from these fields only, never from a
   * display title, so "shown under a project" can't diverge from "attached".
   */
  project_id?: string | null
  project_title?: string | null
  project_relationship_state?: string
}

/**
 * Result of syncing an analyzed Document Proof into the student's
 * Skill Graph (skill_evidence_pipelines / skill_evidence_artifacts).
 */
export type DocumentProofSyncResult = {
  ok: boolean
  already_synced: boolean
  skills_synced: string[]
  pipelines_upserted: number
  artifacts_created: number
  errors: string[]
}

export function listDocumentProofs(): Promise<DocumentProofResponse[]> {
  return apiJson(`${API}/student/document-proofs`)
}

/**
 * Deterministic, additive block re-extraction (tables / charts / diagrams /
 * code blocks / metrics with section+block locators) from the retained
 * original file. Idempotent; the original analysis is preserved.
 */
export function reextractDocumentBlocks(evidenceId: string): Promise<DocumentProofResponse> {
  return apiJson(`${API}/student/document-proofs/${encodeURIComponent(evidenceId)}/reextract-blocks`, {
    method: "POST",
  })
}

export function submitDocumentProof(body: {
  source_type?: DocumentProofSourceType
  raw_text: string
  title?: string | null
  claimed_skills?: string[]
  description?: string | null
}): Promise<DocumentProofResponse> {
  return apiJson(`${API}/student/document-proofs`, {
    method: "POST",
    body: JSON.stringify(body),
  })
}

/**
 * Upload a document file (PDF/DOCX/TXT/MD) as standalone supporting evidence.
 * Throws an Error with the backend message on failure.
 */
export async function uploadDocumentProof(
  file: File,
  meta?: {
    title?: string
    claimed_skills?: string[]
    description?: string
    source_type?: DocumentProofSourceType
  },
): Promise<DocumentProofResponse> {
  const form = new FormData()
  form.append("file", file)
  if (meta?.title) form.append("title", meta.title)
  if (meta?.claimed_skills?.length) form.append("claimed_skills", meta.claimed_skills.join(","))
  if (meta?.description) form.append("description", meta.description)
  if (meta?.source_type) form.append("source_type", meta.source_type)

  // fetchAPI attaches the Supabase Bearer token, never sends this private
  // student call anonymously (signed out → local 401 with a clear message),
  // and leaves Content-Type to the browser for FormData bodies.
  const res = await fetchAPI(`${API}/student/document-proofs/upload`, {
    method: "POST",
    body: form,
  })
  if (!res.ok) {
    let message = `Upload failed (HTTP ${res.status}).`
    try {
      const body = await res.json()
      message = body?.detail?.message ?? message
    } catch {
      // ignore — use default message
    }
    throw new Error(message)
  }
  return res.json() as Promise<DocumentProofResponse>
}

/**
 * Sync an analyzed Document Proof into the student's Skill Graph.
 * Idempotent on the backend — safe to call multiple times for the same document.
 * Throws an Error with the backend message on failure so callers can show it.
 */
export function syncDocumentProofToSkillGraph(documentEvidenceId: string): Promise<DocumentProofSyncResult> {
  return apiJson(`${API}/student/skill-pipelines/from-document-proof/${documentEvidenceId}`, { method: "POST" })
}

// ─── Website Proofs ────────────────────────────────────────────────────────

/**
 * Safe summary of a completed Website Proof session — never includes
 * screenshots, storage paths, signed URLs, tokens, or raw artifact data.
 */
export type WebsiteProofSummaryResponse = {
  proof_session_id: string
  target_website: string
  evidence_strength_score: number
  workflow_confidence: string
  supported_skills: string[]
  created_at: string
}

export function listWebsiteProofs(): Promise<WebsiteProofSummaryResponse[]> {
  return apiJson(`${API}/student/website-proof/proofs`)
}

/** Safe project context used to rank saved Website Proofs deterministically. */
export type WebsiteProofRecommendationRequest = {
  project_title?: string
  project_description?: string
  repo_url?: string
  claimed_skills?: string[]
}

/** A safe Website Proof summary plus its deterministic match grouping. */
export type RecommendedWebsiteProofResponse = WebsiteProofSummaryResponse & {
  match_label: "recommended" | "possible" | "other"
  match_reason: string
}

export type WebsiteProofRecommendationResponse = {
  recommended_website_proofs: RecommendedWebsiteProofResponse[]
  possible_website_proofs: RecommendedWebsiteProofResponse[]
  other_website_proofs: RecommendedWebsiteProofResponse[]
  has_strong_match: boolean
}

/**
 * Backend-supported, deterministic Website Proof recommendations for a Project
 * Defense. Owner-scoped; returns only safe summary + match fields.
 */
export function recommendWebsiteProofs(
  body: WebsiteProofRecommendationRequest,
): Promise<WebsiteProofRecommendationResponse> {
  return apiJson(`${API}/student/website-proof/recommendations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

// ─── Notifications ─────────────────────────────────────────────────────────

export function listNotifications(params?: {
  unread_only?: boolean
  category?: string
  include_archived?: boolean
  limit?: number
  offset?: number
}): Promise<NotificationResponse[]> {
  const qs = new URLSearchParams()
  if (params?.unread_only) qs.set("unread_only", "true")
  if (params?.category) qs.set("category", params.category)
  if (params?.include_archived) qs.set("include_archived", "true")
  if (params?.limit != null) qs.set("limit", String(params.limit))
  if (params?.offset != null) qs.set("offset", String(params.offset))
  return apiJson(`${API}/student/notifications${qs.size ? `?${qs}` : ""}`)
}

export function getUnreadNotificationCount(): Promise<NotificationUnreadCountResponse> {
  return apiJson(`${API}/student/notifications/unread-count`)
}

export function markNotificationRead(id: string): Promise<NotificationResponse> {
  return apiJson(`${API}/student/notifications/${id}/read`, { method: "POST" })
}

export function markNotificationUnread(id: string): Promise<NotificationResponse> {
  return apiJson(`${API}/student/notifications/${id}/unread`, { method: "POST" })
}

export function archiveNotification(id: string): Promise<NotificationResponse> {
  return apiJson(`${API}/student/notifications/${id}/archive`, { method: "POST" })
}

export function dismissNotification(id: string): Promise<NotificationResponse> {
  return apiJson(`${API}/student/notifications/${id}/dismiss`, { method: "POST" })
}

export function markAllNotificationsRead(notificationIds?: string[]): Promise<NotificationResponse[]> {
  return apiJson(`${API}/student/notifications/mark-all-read`, {
    method: "POST",
    body: notificationIds ? JSON.stringify({ notification_ids: notificationIds }) : undefined,
  })
}

// ─── Access Requests ───────────────────────────────────────────────────────

export function listAccessRequests(sessionId: string): Promise<EvidenceAccessRequestResponse[]> {
  return apiJson(`${API}/student/extension-proof/sessions/${sessionId}/access-requests`)
}

export function listAccessRequesters(): Promise<RecruiterRequesterProfileResponse[]> {
  return apiJson(`${API}/student/access-requesters`)
}

export function approveAccessRequest(
  requestId: string,
  body?: AccessRequestDecision,
): Promise<EvidenceAccessGrantResponse> {
  return apiJson(`${API}/student/access-requests/${requestId}/approve`, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  })
}

export function denyAccessRequest(
  requestId: string,
  body?: AccessRequestDecision,
): Promise<EvidenceAccessRequestResponse> {
  return apiJson(`${API}/student/access-requests/${requestId}/deny`, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  })
}

export function revokeAccessGrant(grantId: string): Promise<EvidenceAccessGrantResponse> {
  return apiJson(`${API}/student/access-grants/${grantId}/revoke`, { method: "POST" })
}

// ─── Public Passport ───────────────────────────────────────────────────────

export function getPublicPassport(publicSlug: string): Promise<PublicPassportSafeResponse> {
  return apiJson(`${API}/public/passports/${publicSlug}`)
}

export function requestPassportAccess(
  publicSlug: string,
  body: AccessRequestCreate,
): Promise<AccessRequestPublicResponse> {
  return apiJson(`${API}/public/passports/${publicSlug}/request-access`, {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export function savePublicPassport(
  publicSlug: string,
  body: RecruiterSavedPassportCreate,
): Promise<RecruiterSavedPassportResponse> {
  return apiJson(`${API}/public/passports/${publicSlug}/save`, {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export function getPublicPassportExport(publicSlug: string): Promise<Record<string, unknown>> {
  return apiJson(`${API}/public/passports/${publicSlug}/export`)
}

// ─── Student Passport Management ──────────────────────────────────────────

export function createOrUpdateStudentPassport(
  sessionId: string,
  body?: {
    is_public?: boolean
    public_title?: string | null
    public_summary?: string | null
    field?: string | null
    visible_sections?: string[]
  },
): Promise<PublicWorkPassportStudentResponse> {
  return apiJson(`${API}/student/extension-proof/sessions/${sessionId}/passport`, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  })
}

export function getStudentPassport(sessionId: string): Promise<PublicWorkPassportStudentResponse> {
  return apiJson(`${API}/student/extension-proof/sessions/${sessionId}/passport`)
}

// ─── Export ────────────────────────────────────────────────────────────────

export function createStudentExport(sessionId: string): Promise<Record<string, unknown>> {
  return apiJson(`${API}/student/extension-proof/sessions/${sessionId}/export`, { method: "POST" })
}

export function getLatestStudentExport(sessionId: string): Promise<Record<string, unknown>> {
  return apiJson(`${API}/student/extension-proof/sessions/${sessionId}/export/latest`)
}

// ─── Analytics ─────────────────────────────────────────────────────────────

export function getWorkPassportAnalytics(): Promise<WorkPassportAnalyticsResponse> {
  return apiJson(`${API}/student/work-passport/analytics`)
}

export function getWorkPassportAnalyticsActivity(
  params?: { proof_session_id?: string; limit?: number },
): Promise<WorkPassportActivityItem[]> {
  const qs = new URLSearchParams()
  if (params?.proof_session_id) qs.set("proof_session_id", params.proof_session_id)
  if (params?.limit != null) qs.set("limit", String(params.limit))
  return apiJson(`${API}/student/work-passport/analytics/activity${qs.size ? `?${qs}` : ""}`)
}

// ─── Proof Versioning ──────────────────────────────────────────────────────

export function listProofVersions(sessionId: string): Promise<ProofVersionResponse[]> {
  return apiJson(`${API}/student/extension-proof/sessions/${sessionId}/versions`)
}

export function getActiveProofVersion(sessionId: string): Promise<ProofVersionResponse | null> {
  return apiJson<ProofVersionResponse>(`${API}/student/extension-proof/sessions/${sessionId}/versions/active`).catch(() => null)
}

export function createProofVersion(
  sessionId: string,
  body?: { change_reason?: string; version_label?: string },
): Promise<ProofVersionResponse> {
  return apiJson(`${API}/student/extension-proof/sessions/${sessionId}/versions`, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  })
}

export function activateProofVersion(sessionId: string, versionId: string): Promise<ProofVersionResponse> {
  return apiJson(`${API}/student/extension-proof/sessions/${sessionId}/versions/${versionId}/activate`, {
    method: "POST",
  })
}

export function archiveProofVersion(sessionId: string, versionId: string): Promise<ProofVersionResponse> {
  return apiJson(`${API}/student/extension-proof/sessions/${sessionId}/versions/${versionId}/archive`, {
    method: "POST",
  })
}

// ─── Recruiter Saved Passports ─────────────────────────────────────────────
// All endpoints below require X-Recruiter-Token (injected by recruiterApiJson).

/**
 * List saved passports for the authenticated recruiter session.
 * Requires a valid session token stored via createRecruiterSession().
 */
export function listRecruiterSavedPassports(): Promise<RecruiterSavedPassportResponse[]> {
  return recruiterApiJson(`${API}/public/recruiter/saved-passports`)
}

/**
 * Update a saved passport.
 * Requires a valid session token — requester_email in body is ignored by the backend.
 */
export function updateRecruiterSavedPassport(
  savedId: string,
  body: RecruiterSavedPassportUpdate,
): Promise<RecruiterSavedPassportResponse> {
  return recruiterApiJson(`${API}/public/recruiter/saved-passports/${savedId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  })
}

/**
 * Delete a saved passport.
 * Requires a valid session token — no requester_email query param needed.
 */
export function deleteRecruiterSavedPassport(savedId: string): Promise<void> {
  return recruiterApiJson<void>(`${API}/public/recruiter/saved-passports/${savedId}`, {
    method: "DELETE",
  }).catch(() => undefined)
}

// ─── Candidate Comparison ──────────────────────────────────────────────────

/**
 * Create a new candidate comparison.
 * This endpoint is open (no session token required); requester_email in body
 * is used for scoping the comparison record.
 */
export function createCandidateComparison(
  body: RecruiterCandidateComparisonRequest,
): Promise<RecruiterCandidateComparisonResponse> {
  return apiJson(`${API}/public/recruiter/candidate-comparisons`, {
    method: "POST",
    body: JSON.stringify(body),
  })
}

/**
 * List past comparisons for the authenticated recruiter session.
 * Requires a valid session token stored via createRecruiterSession().
 */
export function listCandidateComparisons(): Promise<RecruiterCandidateComparisonResponse[]> {
  return recruiterApiJson(`${API}/public/recruiter/candidate-comparisons`)
}

// ─── RBAC / Permissions ────────────────────────────────────────────────────

export function getCurrentUserPermissions(): Promise<CurrentUserPermissionsResponse> {
  return apiJson(`${API}/me/permissions`)
}

// ─── Admin – Quality Review ────────────────────────────────────────────────

export function listAdminQualityReviewCases(params?: {
  status?: string
  priority?: string
  case_type?: string
  user_id?: string
  proof_session_id?: string
  limit?: number
  offset?: number
}): Promise<AdminQualityReviewCaseResponse[]> {
  const qs = new URLSearchParams()
  if (params?.status) qs.set("status", params.status)
  if (params?.priority) qs.set("priority", params.priority)
  if (params?.case_type) qs.set("case_type", params.case_type)
  if (params?.user_id) qs.set("user_id", params.user_id)
  if (params?.proof_session_id) qs.set("proof_session_id", params.proof_session_id)
  if (params?.limit != null) qs.set("limit", String(params.limit))
  if (params?.offset != null) qs.set("offset", String(params.offset))
  return apiJson(`${API}/admin/quality-review/cases${qs.size ? `?${qs}` : ""}`)
}

export function getAdminQualityReviewCase(caseId: string): Promise<AdminQualityReviewCaseResponse> {
  return apiJson(`${API}/admin/quality-review/cases/${caseId}`)
}

export function updateAdminQualityReviewCase(
  caseId: string,
  body: Partial<{
    status: string
    priority: string
    admin_notes: string
    decision: string
    decision_notes: string
    requested_student_actions: string[]
  }>,
): Promise<AdminQualityReviewCaseResponse> {
  return apiJson(`${API}/admin/quality-review/cases/${caseId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  })
}

export function listAdminQualityReviewEvents(caseId: string): Promise<AdminQualityReviewEventResponse[]> {
  return apiJson(`${API}/admin/quality-review/cases/${caseId}/events`)
}

export function runAdminQualityReviewScan(
  body?: { session_ids?: string[]; dry_run?: boolean },
): Promise<unknown> {
  return apiJson(`${API}/admin/quality-review/scan`, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  })
}

// ─── Admin – Requester Verification ───────────────────────────────────────

export function listAdminRequesterProfiles(params?: {
  limit?: number
  offset?: number
}): Promise<RecruiterRequesterProfileResponse[]> {
  const qs = new URLSearchParams()
  if (params?.limit != null) qs.set("limit", String(params.limit))
  if (params?.offset != null) qs.set("offset", String(params.offset))
  return apiJson(`${API}/admin/recruiter-requesters${qs.size ? `?${qs}` : ""}`)
}

export function updateAdminRequesterVerification(
  profileId: string,
  body: {
    verification_status: string
    email_verified?: boolean
    domain_verified?: boolean
    notes?: string | null
  },
): Promise<RecruiterRequesterProfileResponse> {
  return apiJson(`${API}/admin/recruiter-requesters/${profileId}/verification-status`, {
    method: "POST",
    body: JSON.stringify(body),
  })
}

// ── Recruiter Work Passport View ──────────────────────────────────────────────

export type RecruiterSkillResponse = {
  skill: string
  confidence: "high" | "medium" | "low"
  status_label: string
  source_labels: string[]
}

export type RecruiterSkillGroupResponse = {
  group_name: string
  category: string
  confidence: "high" | "medium" | "low"
  evidence_count: number
  source_labels: string[]
  skills: RecruiterSkillResponse[]
}

export type RecruiterProofSourceResponse = {
  key: string
  label: string
  status: string
  score: number
  is_run: boolean
}

export type RecruiterPassportViewResponse = {
  public_slug: string
  student_display_name?: string | null
  field?: string | null
  public_title?: string | null
  public_summary?: string | null
  overall_score: number
  evidence_confidence: "high" | "medium" | "low"
  verification_status?: string | null
  readiness_level?: string | null
  skill_groups: RecruiterSkillGroupResponse[]
  verified_skills: string[]
  partially_verified_skills: string[]
  skills_needing_review: string[]
  proof_sources: RecruiterProofSourceResponse[]
  why_credible: string[]
  strongest_skills: string[]
  areas_needing_review: string[]
  suggested_interview_questions: string[]
  public_project_links: { label: string; url: string }[]
  project_type?: string | null
  access_request_available: boolean
  has_protected_evidence: boolean
  disclosure_note: string
}

/** Fetch the recruiter-enriched Work Passport view for a public slug. */
export function getRecruiterPassportView(
  publicSlug: string,
): Promise<RecruiterPassportViewResponse> {
  return apiJson(`${API}/public/passports/${encodeURIComponent(publicSlug)}/recruiter-view`)
}
