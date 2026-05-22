"use client"

import { createSupabaseBrowserClient } from "@/lib/supabase/client"

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"

/**
 * Authenticated fetch wrapper for the VeriBridge backend API.
 * Reads the current Supabase session and injects the access token
 * as an Authorization: Bearer header when present.
 */
export async function fetchAPI(
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  const supabase = createSupabaseBrowserClient()
  const {
    data: { session },
  } = await supabase.auth.getSession()

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string> | undefined) ?? {}),
  }

  if (session?.access_token) {
    headers["Authorization"] = `Bearer ${session.access_token}`
  }

  return fetch(`${API_BASE}${path}`, { ...options, headers })
}

export async function getStudentProfile(): Promise<unknown | null> {
  const res = await fetchAPI("/api/v1/student/profile")
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

export type SkillEvidencePayload = {
  skill_name: string
  evidence_type: string
  evidence_url?: string | null
  repository_url?: string | null
  file_path?: string | null
  line_start?: number | null
  line_end?: number | null
  evidence_description?: string | null
  proof_visibility?: "public" | "private" | null
  metadata?: Record<string, unknown> | null
}

export type SkillEvidenceResponse = SkillEvidencePayload & {
  id: string
  user_id: string
  verification_status: "pending_review" | "verified" | "skill_usage_not_found" | "needs_review"
  verification_summary?: string | null
  verifier_version?: string | null
  created_at: string
  updated_at: string
}

export type EvidenceAccessLink = {
  id: string
  evidence_id: string
  source_report_type: "github_recruiter_proof_report" | "website_semantic_verification_result" | "direct_skill_evidence" | "none"
  source_report_id?: string | null
  access_type: "github_exact_lines" | "live_website"
  label: string
  url: string
  source_type: "github" | "website"
  file_path?: string | null
  line_start?: number | null
  line_end?: number | null
  availability_status: "available" | "unavailable" | "invalid_source" | "insufficient_data"
  notes?: string | null
  created_at: string
  updated_at: string
}

export type EvidenceAccessLinkListResponse = {
  results: EvidenceAccessLink[]
}

export type EvidenceAccessLinkCreateResponse = EvidenceAccessLinkListResponse

export type WebsiteVerificationGuidePayload = {
  project_overview?: string | null
  feature_to_verify: string
  verification_steps: string[]
  sample_inputs?: unknown[] | Record<string, unknown> | null
  expected_output: string
  login_required?: boolean
  login_notes?: string | null
  access_notes?: string | null
  known_limitations?: string | null
  additional_notes?: string | null
}

export type WebsiteVerificationGuideResponse = WebsiteVerificationGuidePayload & {
  id: string
  user_id: string
  skill_evidence_id: string
  created_at: string
  updated_at: string
}

export type WebsiteVerificationPlanResponse = {
  id: string
  user_id: string
  skill_evidence_id: string
  website_url: string
  feature_to_verify: string
  plan_status: string
  normalized_test_steps: string[]
  expected_output: string
  sample_inputs?: unknown[] | Record<string, unknown> | null
  inferred_action_candidates: Array<Record<string, unknown>>
  validation_warnings: string[]
  agent_notes: string
  requires_login: boolean
  can_attempt_automated_execution: boolean
  planner_version: string
  created_at: string
}

export type WebsiteVerificationRunResponse = {
  id: string
  evidence_id: string
  plan_id: string
  user_id: string
  execution_status: string
  executor_version: string
  execution_summary?: string | null
  checks_attempted: number
  checks_passed: number
  checks_failed: number
  checks_needing_review: number
  inspected_url?: string | null
  inspected_title?: string | null
  inspected_meta_description?: string | null
  inspected_headings: string[]
  inspected_visible_text_excerpt?: string | null
  raw_executor_notes: Record<string, unknown>
  created_at: string
  updated_at: string
  checks: Array<Record<string, unknown>>
}

export type WebsiteBrowserVerificationRunResponse = {
  id: string
  evidence_id: string
  plan_id: string
  user_id: string
  browser_execution_status: string
  executor_version: string
  execution_summary?: string | null
  inspected_url?: string | null
  final_url?: string | null
  page_title?: string | null
  screenshot_storage_path?: string | null
  html_snapshot_storage_path?: string | null
  safe_text_snapshot?: string | null
  steps_attempted: number
  steps_passed: number
  steps_failed: number
  steps_skipped: number
  steps_needing_review: number
  browser_metadata: Record<string, unknown>
  created_at: string
  updated_at: string
  steps: Array<Record<string, unknown>>
}

export type WebsiteSemanticVerificationResultResponse = {
  id: string
  evidence_id: string
  plan_id: string
  static_run_id?: string | null
  browser_run_id?: string | null
  user_id: string
  semantic_status: string
  confidence_score?: number | null
  evaluator_version: string
  evaluator_provider: string
  recruiter_facing_summary?: string | null
  evidence_summary?: string | null
  limitations?: string | null
  recommended_next_action?: string | null
  semantic_similarity?: {
    available: boolean
    score?: number | null
    label: string
    model?: string | null
    method: string
  } | null
  source_snapshot: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type GitHubSemanticVerificationResultResponse = {
  id: string
  evidence_id: string
  user_id: string
  semantic_status: string
  confidence_score?: number | null
  evaluator_version: string
  evaluator_provider: string
  recruiter_facing_summary?: string | null
  evidence_summary?: string | null
  limitations?: string | null
  recommended_next_action?: string | null
  strongest_matching_segment_start?: number | null
  strongest_matching_segment_end?: number | null
  strongest_matching_segment_summary?: string | null
  matched_segments: Array<Record<string, unknown>>
  source_snapshot: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type GitHubRecruiterProofReportResponse = {
  id: string
  evidence_id: string
  github_semantic_result_id: string
  user_id: string
  report_status: string
  confidence_score?: number | null
  report_version: string
  student_claim?: string | null
  headline?: string | null
  recruiter_summary?: string | null
  evidence_summary?: string | null
  limitations?: string | null
  recommended_next_action?: string | null
  confirmed_capabilities: Array<Record<string, unknown>>
  missing_capabilities: Array<Record<string, unknown>>
  supporting_line_ranges: Array<Record<string, unknown>>
  report_snapshot: Record<string, unknown>
  created_at: string
  updated_at: string
}

export async function listSkillEvidence(): Promise<SkillEvidenceResponse[]> {
  const res = await fetchAPI("/api/v1/student/skill-evidence")
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

export async function createSkillEvidence(payload: SkillEvidencePayload): Promise<SkillEvidenceResponse> {
  const res = await fetchAPI("/api/v1/student/skill-evidence", {
    method: "POST",
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

export async function updateSkillEvidence(id: string, payload: Partial<SkillEvidencePayload>): Promise<SkillEvidenceResponse> {
  const res = await fetchAPI(`/api/v1/student/skill-evidence/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

export async function deleteSkillEvidence(id: string): Promise<{ success: boolean; message: string }> {
  const res = await fetchAPI(`/api/v1/student/skill-evidence/${id}`, {
    method: "DELETE",
  })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

export async function verifySkillEvidence(id: string): Promise<{
  id: string
  verification_status: SkillEvidenceResponse["verification_status"]
  verification_summary: string
  verifier_version: string
  evidence: SkillEvidenceResponse
}> {
  const res = await fetchAPI(`/api/v1/student/skill-evidence/${id}/verify`, {
    method: "POST",
  })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

export async function getLatestEvidenceAccessLinks(evidenceId: string): Promise<EvidenceAccessLink[]> {
  const res = await fetchAPI(`/api/v1/student/skill-evidence/${evidenceId}/evidence-access-links/latest`)
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  const data = (await res.json()) as EvidenceAccessLinkListResponse
  return data.results ?? []
}

export async function listEvidenceAccessLinks(evidenceId: string): Promise<EvidenceAccessLink[]> {
  const res = await fetchAPI(`/api/v1/student/skill-evidence/${evidenceId}/evidence-access-links`)
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  const data = (await res.json()) as EvidenceAccessLinkListResponse
  return data.results ?? []
}

export async function generateEvidenceAccessLinks(evidenceId: string): Promise<EvidenceAccessLink[]> {
  const res = await fetchAPI(`/api/v1/student/skill-evidence/${evidenceId}/evidence-access-links`, {
    method: "POST",
  })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  const data = (await res.json()) as EvidenceAccessLinkCreateResponse
  return data.results ?? []
}

export async function createWebsiteVerificationGuide(
  evidenceId: string,
  payload: WebsiteVerificationGuidePayload
): Promise<WebsiteVerificationGuideResponse> {
  const res = await fetchAPI(`/api/v1/student/skill-evidence/${evidenceId}/website-verification-guide`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

export async function generateWebsiteVerificationPlan(evidenceId: string): Promise<WebsiteVerificationPlanResponse> {
  const res = await fetchAPI(`/api/v1/student/skill-evidence/${evidenceId}/website-verification-plan`, {
    method: "POST",
  })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

export async function executeWebsiteVerificationRun(
  evidenceId: string,
  planId?: string | null
): Promise<WebsiteVerificationRunResponse> {
  const res = await fetchAPI(`/api/v1/student/skill-evidence/${evidenceId}/website-verification-runs`, {
    method: "POST",
    body: JSON.stringify(planId ? { plan_id: planId } : {}),
  })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

export async function executeWebsiteBrowserVerificationRun(
  evidenceId: string,
  planId?: string | null
): Promise<WebsiteBrowserVerificationRunResponse> {
  const res = await fetchAPI(`/api/v1/student/skill-evidence/${evidenceId}/website-browser-verification-runs`, {
    method: "POST",
    body: JSON.stringify(planId ? { plan_id: planId } : {}),
  })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

export async function createWebsiteSemanticVerificationResult(
  evidenceId: string,
  payload: { plan_id?: string | null; static_run_id?: string | null; browser_run_id?: string | null } = {}
): Promise<WebsiteSemanticVerificationResultResponse> {
  const res = await fetchAPI(`/api/v1/student/skill-evidence/${evidenceId}/website-semantic-verification-results`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

export async function createGithubSemanticVerificationResult(
  evidenceId: string
): Promise<GitHubSemanticVerificationResultResponse> {
  const res = await fetchAPI(`/api/v1/student/skill-evidence/${evidenceId}/github-semantic-verification-results`, {
    method: "POST",
  })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

export async function createGithubRecruiterProofReport(
  evidenceId: string,
  semanticResultId?: string | null
): Promise<GitHubRecruiterProofReportResponse> {
  const res = await fetchAPI(`/api/v1/student/skill-evidence/${evidenceId}/github-recruiter-proof-reports`, {
    method: "POST",
    body: JSON.stringify(semanticResultId ? { semantic_result_id: semanticResultId } : {}),
  })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

// ── Recruiter Candidate Search (Phase J1) ─────────────────────────────────────

export type CandidateSearchResult = {
  user_id: string
  display_name: string
  school_name?: string | null
  degree?: string | null
  major?: string | null
  matched_skill_names: string[]
  evidence_count: number
  accepted_evidence_count: number
  has_github_proof: boolean
  has_website_proof: boolean
  strongest_project_title?: string | null
  proof_status_label?: string | null
}

export type CandidateSearchResponse = {
  query: string
  results: CandidateSearchResult[]
  result_count: number
}

export async function searchRecruiterCandidates(query: string): Promise<CandidateSearchResponse> {
  const res = await fetchAPI(
    `/api/v1/recruiter/candidates/search?query=${encodeURIComponent(query)}`
  )
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

// ── GitHub Portfolio Scan (Phase J3B) ────────────────────────────────────────

export type GitHubPortfolioSuggestedStatus = "suggested" | "needs_review" | "skipped"
export type GitHubPortfolioConfidenceLabel = "high" | "medium" | "low"

export type GitHubPortfolioScanCandidate = {
  candidate_id: string
  repo_name: string
  repo_url: string
  project_title: string
  skill_label: string
  evidence_description: string
  student_claim: string
  file_path: string
  line_start: number
  line_end: number
  github_highlight_url: string
  confidence_label: GitHubPortfolioConfidenceLabel
  selection_reason: string
  website_url?: string | null
  suggested_status: GitHubPortfolioSuggestedStatus
  warnings: string[]
  import_key: string
}

export type GitHubPortfolioScanResponse = {
  github_username: string
  repo_count_scanned: number
  candidate_count: number
  detected_skill_count: number
  proof_candidates: GitHubPortfolioScanCandidate[]
}

export type GitHubPortfolioCandidateResult = {
  candidate_id: string
  skill_label: string
  repo_name: string
  status: "imported" | "skipped_duplicate" | "failed"
  evidence_id?: string | null
  message: string
}

export type GitHubPortfolioImportResponse = {
  imported_count: number
  skipped_duplicate_count: number
  failed_count: number
  imported_evidence_ids: string[]
  per_candidate_results: GitHubPortfolioCandidateResult[]
}

export async function scanGitHubPortfolio(params: {
  github_profile_url?: string | null
  github_username?: string | null
  max_repos?: number
  include_forks?: boolean
  include_archived?: boolean
  smart_scan?: boolean
}): Promise<GitHubPortfolioScanResponse> {
  const res = await fetchAPI("/api/v1/student/github-portfolio/scan", {
    method: "POST",
    body: JSON.stringify(params),
  })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

export async function importSelectedGitHubPortfolioProofs(
  proof_candidates: GitHubPortfolioScanCandidate[]
): Promise<GitHubPortfolioImportResponse> {
  const res = await fetchAPI("/api/v1/student/github-portfolio/import-selected", {
    method: "POST",
    body: JSON.stringify({ proof_candidates }),
  })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

// ── Recruiter Candidate Detail (Phase J2) ─────────────────────────────────────

export type EvidenceAccessLinkItem = {
  id: string
  label: string
  url: string
  access_type: string
  source_type: string
  file_path?: string | null
  line_start?: number | null
  line_end?: number | null
  availability_status: string
}

export type ProofProjectSummary = {
  project_title: string
  status_label?: string | null
  status_code?: string | null
  has_github_proof: boolean
  has_website_proof: boolean
  recruiter_summary?: string | null
  associated_skill_labels: string[]
  evidence_access_links: EvidenceAccessLinkItem[]
}

export type VerifiedSkillSummary = {
  skill_name: string
  evidence_count: number
  strongest_status_label?: string | null
}

export type ProofOverview = {
  total_evidence_count: number
  accepted_evidence_count: number
  github_proof_count: number
  website_proof_count: number
  strongest_display_status?: string | null
}

export type RecruiterCandidateDetailResponse = {
  candidate_id: string
  display_name: string
  school_name?: string | null
  degree?: string | null
  major?: string | null
  proof_overview: ProofOverview
  verified_or_supported_skills: VerifiedSkillSummary[]
  proof_projects: ProofProjectSummary[]
}

export async function fetchRecruiterCandidateDetail(
  candidateId: string
): Promise<RecruiterCandidateDetailResponse> {
  const res = await fetchAPI(
    `/api/v1/recruiter/candidates/${encodeURIComponent(candidateId)}/detail`
  )
  if (res.status === 404) throw new Error(`Candidate not found: ${candidateId}`)
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}
