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

// ── Website AI Analyzer (Phase J4D / J4E / J4F / J4G) ───────────────────────

export type WebsiteEvidenceSource = "website" | "github_repo" | "combined" | "functional"

export type WebsiteAnalysisCandidate = {
  candidate_id: string
  skill_name: string
  skill_category: string
  confidence: "high" | "medium" | "low"
  evidence_title: string
  evidence_summary: string
  source_url: string
  route_path: string
  evidence_snippet: string
  evidence_type: "deployed_website" | "api_docs" | "api_endpoint" | "website_content" | "github_repo" | "combined"
  action_label: string
  suggested_status: "suggested" | "needs_review"
  evidence_source: "website" | "github_repo" | "combined"
  is_combined: boolean
  related_source_url?: string | null
}

// ── J4I: Browser workflow interfaces (future Playwright implementation) ─────────

/**
 * A single step in a browser workflow verification plan.
 * TODO(J4J): implement a Playwright runner that executes these steps,
 * captures screenshots, and attaches them to evidence.
 */
export type BrowserWorkflowStep = {
  /** The browser action to perform. */
  action: "open" | "fill" | "click" | "wait_for_text" | "screenshot"
  /** CSS/XPath selector for the target element (if applicable). */
  selector?: string | null
  /** Value to fill or text to wait for. */
  value?: string | null
  /** Human-readable label for this step. */
  label?: string | null
}

/**
 * Full browser workflow test plan submitted by the user.
 * Used by the future Playwright agent to open the site, run steps, and
 * capture a screenshot proving the input→output workflow.
 */
export type BrowserWorkflowTestPlan = {
  url: string
  steps: BrowserWorkflowStep[]
  expected_output?: string | null
  screenshot_required: boolean
  screenshot_url?: string | null
}

/** User-provided optional functional test plan. */
export type FunctionalTestPlan = {
  what_to_test?: string | null
  test_input?: string | null          // JSON or "key=value; key=value" pairs
  expected_output?: string | null
  test_mode?: "auto" | "api_endpoint" | "browser_ui" | "plan_only"  // kept for backward compat
  /** J4I: browser UI workflow screenshot fields */
  frontend_url?: string | null        // Frontend URL with interactive UI
  browser_workflow_instructions?: string | null
  /** J4J: explicit verification flags — both can be True simultaneously */
  run_api_verification?: boolean
  run_browser_verification?: boolean
}

/** One API metric matched (or not) against visible browser page text. */
export type MatchedVisualMetric = {
  metric_key: string
  api_value: string
  visible_match: string | null
  match_type: "exact" | "rounded" | "keyword" | "related" | "not_found"
  note: string
}

/** J4I: Result of a Playwright-based browser UI workflow screenshot capture. */
export type BrowserWorkflowVerificationResult = {
  success: boolean
  frontend_url: string
  steps_run: string[]
  expected_output_found: boolean
  screenshot_data_url?: string | null    // "data:image/jpeg;base64,..."
  screenshot_caption?: string | null
  error_message?: string | null
  no_ui_detected: boolean
  output_text_found?: string | null
  screenshot_status: "captured" | "not_captured" | "no_ui" | "error"
  /** J4J: richer result fields */
  output_terms_found?: string[]
  browser_workflow_status?: "passed" | "partial" | "failed"
  proof_summary?: string
  /** API metric → visual evidence matching */
  frontend_visible_output_text?: string | null
  matched_visual_metrics?: MatchedVisualMetric[]
}

/** J4F: Result of a live functional verification test on a safe endpoint. */
export type FunctionalVerificationCandidate = {
  candidate_id: string
  skill_name: string
  skill_category: string
  confidence: "high" | "medium" | "low"
  evidence_title: string
  evidence_summary: string
  endpoint_url: string
  method: string
  request_summary: string
  response_fields_found: string[]
  status_code: number | null
  verified: boolean
  verification_message: string
  evidence_type: "verified_workflow"
  action_label: string
  suggested_status: "suggested" | "needs_review"
  /** J4H transparency fields */
  test_input_source: "auto_generated" | "user_provided" | "schema_example"
  is_user_guided: boolean
  verification_label: string
  request_body_summary: string
  what_to_test?: string | null
  expected_output_description?: string | null
  /** Actual response captured from the live endpoint */
  response_preview?: Record<string, unknown> | null
  response_summary?: string
  raw_response_json?: string | null
  response_truncated?: boolean
  /** J4I: screenshot / browser workflow proof */
  screenshot_url?: string | null
  screenshot_caption?: string | null
  screenshot_status?: "unavailable" | "manual" | "auto_captured"
  browser_workflow_status?: "not_started" | "pending" | "completed" | "failed"
  browser_workflow_notes?: string | null
}

/** J4G: High-level grouped skill card combining website, GitHub, and functional evidence. */
export type GroupedWebsiteSkill = {
  group_id: string
  skill_name: string
  category: string
  confidence: "high" | "medium" | "low"
  sources: WebsiteEvidenceSource[]
  subskills: string[]
  evidence_count: number
  website_count: number
  repo_count: number
  functional_count: number
  combined_count: number
  candidate_ids: string[]
  functional_candidate_ids: string[]
  system_graph_nodes: string[]
  system_graph_edges: [string, string][]
  suggested_status: "suggested" | "needs_review"
  /** Partial-proof honesty fields */
  is_partial: boolean
  partial_proof_message?: string | null
  missing_proof_suggestions: string[]
  inferred_cloud_platform?: string | null
}

export type WebsiteAnalyzeResponse = {
  base_url: string
  candidates: WebsiteAnalysisCandidate[]
  functional_candidates: FunctionalVerificationCandidate[]
  grouped_skills: GroupedWebsiteSkill[]
  checked_urls: string[]
  warnings: string[]
  candidate_count: number
  website_candidate_count: number
  repo_candidate_count: number
  combined_candidate_count: number
  functional_candidate_count: number
  functional_verification_available: boolean
  github_repo_url?: string | null
  /** J4I: browser UI workflow screenshot result */
  browser_workflow_result?: BrowserWorkflowVerificationResult | null
}

export async function analyzeWebsite(params: {
  url: string
  skill_focus?: string | null
  github_repo_url?: string | null
  run_safe_tests?: boolean
  functional_test_plan?: FunctionalTestPlan | null
}): Promise<WebsiteAnalyzeResponse> {
  const body = {
    url: params.url,
    skill_focus: params.skill_focus ?? null,
    github_repo_url: params.github_repo_url ?? null,
    run_safe_tests: params.run_safe_tests ?? true,
    functional_test_plan: params.functional_test_plan ?? null,
  }
  const res = await fetchAPI("/api/v1/student/website-analysis/analyze", {
    method: "POST",
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const rawBody = await res.text()
    let userMessage = `Analysis failed (HTTP ${res.status}).`
    try {
      const parsed = JSON.parse(rawBody) as { detail?: { message?: string } | string }
      const detail = parsed.detail
      if (detail && typeof detail === "object" && typeof detail.message === "string") {
        userMessage = detail.message
      } else if (typeof detail === "string") {
        userMessage = detail
      }
    } catch { /* not JSON */ }
    throw new Error(userMessage)
  }
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
  /** Repos returned by GitHub API after fork/archived filter (accurate total). */
  repos_available_count: number
  /** Repos actually scanned after smart_scan ranking + max_repos cap. */
  repos_selected_count: number
  /** Repos that produced ≥1 evidence candidate (may be lower than repos_selected_count). */
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
  if (!res.ok) {
    const body = await res.text()
    // Parse structured error from FastAPI detail field — show clean message, not raw JSON
    let userMessage = `Scan failed (HTTP ${res.status}).`
    try {
      const parsed = JSON.parse(body) as { detail?: { message?: string; code?: string } | string }
      const detail = parsed.detail
      if (detail && typeof detail === "object" && typeof detail.message === "string") {
        userMessage = detail.message
      } else if (typeof detail === "string") {
        userMessage = detail
      }
    } catch { /* body was not JSON — use generic message */ }
    throw new Error(userMessage)
  }
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
  screenshot_url?: string | null
  screenshot_caption?: string | null
  api_verified?: boolean
  api_output_summary?: string | null
  website_app_type_label?: string | null
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

// ── Controlled browser proof sessions (Manual Login Handoff) ─────────────────

export type WebsiteProofSessionStatus =
  | "created" | "running" | "waiting_for_manual_login" | "authenticated_ready"
  | "resumed" | "completed" | "partial" | "failed" | "expired"

export type WebsiteProofSessionResponse = {
  session_id: string
  status: WebsiteProofSessionStatus
  auth_mode: string
  login_url?: string | null
  login_screenshot?: string | null
  final_screenshot?: string | null
  final_page_text?: string | null
  steps_run: string[]
  proof_summary?: string | null
  error_message?: string | null
  expires_at: string
  created_at: string
}

export async function createWebsiteProofSession(params: {
  website_url: string
  frontend_url?: string | null
  auth_mode?: string
  test_input?: string | null
  expected_output?: string | null
  workflow_instructions?: string | null
}): Promise<WebsiteProofSessionResponse> {
  const res = await fetchAPI("/api/v1/student/website-proof/sessions", {
    method: "POST",
    body: JSON.stringify({
      website_url: params.website_url,
      frontend_url: params.frontend_url ?? null,
      auth_mode: params.auth_mode ?? "manual_login_handoff",
      test_input: params.test_input ?? null,
      expected_output: params.expected_output ?? null,
      workflow_instructions: params.workflow_instructions ?? null,
    }),
  })
  if (!res.ok) {
    const raw = await res.text()
    let msg = `Session create failed (HTTP ${res.status}).`
    try { msg = (JSON.parse(raw) as { detail?: { message?: string } }).detail?.message ?? msg } catch { /* */ }
    throw new Error(msg)
  }
  return res.json()
}

export async function resumeWebsiteProofSession(
  sessionId: string
): Promise<WebsiteProofSessionResponse> {
  const res = await fetchAPI(
    `/api/v1/student/website-proof/sessions/${encodeURIComponent(sessionId)}/resume`,
    { method: "POST" }
  )
  if (res.status === 404) throw new Error("Proof session not found or expired.")
  if (res.status === 410) throw new Error("Proof session expired. Please start a new session.")
  if (!res.ok) throw new Error(`Resume failed (HTTP ${res.status}).`)
  return res.json()
}

export async function closeWebsiteProofSession(sessionId: string): Promise<void> {
  await fetchAPI(
    `/api/v1/student/website-proof/sessions/${encodeURIComponent(sessionId)}/close`,
    { method: "POST" }
  )
}

export async function getWebsiteProofSession(
  sessionId: string
): Promise<WebsiteProofSessionResponse> {
  const res = await fetchAPI(
    `/api/v1/student/website-proof/sessions/${encodeURIComponent(sessionId)}`
  )
  if (res.status === 404) throw new Error("Proof session not found or expired.")
  if (!res.ok) throw new Error(`Get session failed (HTTP ${res.status}).`)
  return res.json()
}

// ── Extension Proof Sessions ──────────────────────────────────────────────────

export type ExtensionProofSessionStatus =
  | "created"
  | "waiting_for_extension"
  | "recording"
  | "uploaded_pending_analysis"
  | "analyzing"
  | "completed"
  | "expired"

export type ExtensionProofSessionResponse = {
  id: string
  user_id: string
  skill_evidence_id: string
  status: ExtensionProofSessionStatus
  started_at: string | null
  proof_upload_id: string | null
  created_at: string
  updated_at: string
  // Privacy Guard fields — present in upload responses, absent in session-only responses
  privacy_scan_status?: WorkflowPrivacyScanStatus | null
  privacy_scan_summary?: string | null
}

export async function createExtensionProofSession(
  skillEvidenceId: string,
  opts?: {
    parent_proof_session_id?: string
    followup_target_skill?: string
    followup_objective?: string
    proof_attempt_type?: "original" | "followup"
    website_url?: string
    github_url?: string
    claimed_skills?: string[]
    proof_objective?: string
  }
): Promise<ExtensionProofSessionResponse> {
  const body: Record<string, unknown> = { skill_evidence_id: skillEvidenceId }
  if (opts?.parent_proof_session_id) body.parent_proof_session_id = opts.parent_proof_session_id
  if (opts?.followup_target_skill) body.followup_target_skill = opts.followup_target_skill
  if (opts?.followup_objective) body.followup_objective = opts.followup_objective
  if (opts?.proof_attempt_type) body.proof_attempt_type = opts.proof_attempt_type
  if (opts?.website_url) body.website_url = opts.website_url
  if (opts?.github_url) body.github_url = opts.github_url
  if (opts?.claimed_skills?.length) body.claimed_skills = opts.claimed_skills
  if (opts?.proof_objective) body.proof_objective = opts.proof_objective
  const res = await fetchAPI("/api/v1/student/extension-proof/sessions", {
    method: "POST",
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const raw = await res.text()
    let msg = `Session create failed (HTTP ${res.status}).`
    try { msg = (JSON.parse(raw) as { detail?: { message?: string } }).detail?.message ?? msg } catch { /* */ }
    throw new Error(msg)
  }
  return res.json()
}

export async function getExtensionProofSession(
  sessionId: string
): Promise<ExtensionProofSessionResponse> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}`
  )
  if (res.status === 404) throw new Error("Extension proof session not found.")
  if (!res.ok) throw new Error(`Get session failed (HTTP ${res.status}).`)
  return res.json()
}

export async function startExtensionProofSession(
  sessionId: string
): Promise<ExtensionProofSessionResponse> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/start`,
    { method: "POST" }
  )
  if (res.status === 404) throw new Error("Extension proof session not found.")
  if (res.status === 409) {
    const raw = await res.text()
    let msg = "Session is not in a startable state."
    try { msg = (JSON.parse(raw) as { detail?: { message?: string } }).detail?.message ?? msg } catch { /* */ }
    throw new Error(msg)
  }
  if (!res.ok) throw new Error(`Start session failed (HTTP ${res.status}).`)
  return res.json()
}

// ── Extension Proof GitHub Analysis ──────────────────────────────────────────

export type ExtensionProofGitHubAnalysisStatus =
  | "success"
  | "failed"
  | "private_or_unavailable"

export type ExtensionProofGitHubAnalysisResponse = {
  id: string
  proof_session_id: string
  repo_url: string
  status: ExtensionProofGitHubAnalysisStatus
  detected_stack: string[]
  detected_features: string[]
  matched_claimed_skills: string[]
  weakly_matched_claimed_skills: string[]
  missing_claimed_skills: string[]
  evidence_files: string[]
  confidence_score: number
  warnings: string[]
  recruiter_summary: string
  created_at: string
  updated_at: string | null
}

export type AnalyzeGitHubOptions = {
  liveWebsiteUrl?: string
  livePageTitle?: string
  proofObjective?: string
}

export async function analyzeExtensionProofGitHub(
  sessionId: string,
  githubUrl: string,
  claimedSkills: string[],
  options: AnalyzeGitHubOptions = {}
): Promise<ExtensionProofGitHubAnalysisResponse> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/analyze/github`,
    {
      method: "POST",
      body: JSON.stringify({
        github_url: githubUrl,
        claimed_skills: claimedSkills,
        live_website_url: options.liveWebsiteUrl ?? "",
        live_page_title: options.livePageTitle ?? "",
        proof_objective: options.proofObjective ?? "",
      }),
    }
  )
  if (!res.ok) {
    const raw = await res.text()
    let msg = `GitHub analysis failed (HTTP ${res.status}).`
    try { msg = (JSON.parse(raw) as { detail?: { message?: string } }).detail?.message ?? msg } catch { /* */ }
    throw new Error(msg)
  }
  return res.json()
}

export async function getExtensionProofGitHubAnalysis(
  sessionId: string
): Promise<ExtensionProofGitHubAnalysisResponse | null> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/analysis/github`
  )
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Get GitHub analysis failed (HTTP ${res.status}).`)
  return res.json()
}

// ── Final Evidence Evaluator ──────────────────────────────────────────────────

export type FinalEvidenceStatus = "pass" | "partial" | "missing" | "not_run" | "not_available" | "not_applicable"

export type NextBestActionType =
  | "run_github_analysis"
  | "add_github_url"
  | "run_live_website_check"
  | "upload_document"
  | "record_followup_proof"
  | "add_linkedin_proof"
  | "record_camera_proof"
  | "record_cad_proof"
  | "record_presentation"

export type NextBestAction = {
  action_type: NextBestActionType
  target_skill: string
  reason: string
  objective: string
  button_label: string
  priority: "high" | "medium" | "low"
  is_recording: boolean
  recommended_duration: string | null
}

export type FinalRecommendationAction = {
  title: string
  reason: string
  action: string
  skill_learned: string
  evidence_to_record: string
  difficulty: "beginner" | "intermediate" | "advanced"
  estimated_time: "30 min" | "1–2 hr" | "1 day" | "1 week"
  priority: "high" | "medium" | "low"
  source_reason: string
  action_type: string
}

export type FinalRecommendations = {
  mode: "proof_repair" | "project_growth"
  proof_actions: FinalRecommendationAction[]
  learning_actions: FinalRecommendationAction[]
}

export type EvidenceSourceBreakdown = {
  key: string
  status: FinalEvidenceStatus
  score: number | null
  weight: number
  notes: string
}

export type EvidenceObject = {
  evidence_type: "recording_keyframe" | "ocr_text" | "dom_text" | "qwen_visual" | "github_file" | "live_check" | "transcript" | "transcript_quote" | "document" | "document_snippet" | "profile_snippet" | "certificate_or_transcript_snippet"
  source_name: string
  confidence: "high" | "medium" | "low"
  short_summary: string
  timestamp_seconds?: number | null
  keyframe_url?: string | null
  text_snippet?: string | null
  file_path?: string | null
  repo_name?: string | null
  source_type?: string | null
  page_number?: number | null
  profile_url?: string | null
  section_label?: string | null
  issuer?: string | null
  title?: string | null
  date?: string | null
  line_range?: string | null
  line_start?: number | null
  line_end?: number | null
  github_url?: string | null
  code_snippet?: string | null
  matched_keywords?: string[]
  provenance?: string
  evidence_kind?: "direct_workflow" | "contextual_page" | "embedded_video" | "unrelated" | "deployment_only" | ""
  skill_support_level?: "strong" | "partial" | "weak" | "none" | ""
  trace_action?: "open_github" | "view_keyframe" | "view_ocr" | "view_qwen" | "view_workflow_event" | "view_live_check" | "view_document" | "view_transcript" | ""
  action_available?: boolean
  route_url?: string | null
  source_url?: string | null
  source_host?: string | null
  target_match?: boolean
  exclusion_reason?: string | null
  evidence_source_type?: "target_website" | "github_repo" | "document" | "transcript" | "non_target_activity" | string
  recruiter_safe: boolean
}

export type DetectedSkillEntry = {
  skill: string
  confidence: "high" | "medium" | "low"
  evidence_support: string
  sources: string[]
  is_inferred: boolean
  status_label?: string
  keyframe_evidence?: string[]
  github_evidence?: string[]
  category?: string
  source_labels?: string[]
  evidence_count?: number
  sources_count?: number
  evidence_objects?: EvidenceObject[]
}

export type GroupedSkillEvidence = {
  group_name: string
  category: string
  confidence: "high" | "medium" | "low"
  evidence_count: number
  sources_count: number
  source_labels: string[]
  skills: DetectedSkillEntry[]
}

export type DetectedCapability = {
  role_title: string
  confidence: "high" | "medium" | "low"
  why_detected: string[]
  supporting_skills: DetectedSkillEntry[]
}

export type FinalEvaluationResult = {
  proof_session_id: string
  final_score: number
  confidence: "high" | "medium" | "low"
  evidence_sources_used: string[]
  evidence_sources_missing: string[]
  per_skill_scores: Record<string, number>
  evidence_source_breakdown: EvidenceSourceBreakdown[]
  final_recruiter_summary: string
  final_student_summary: string
  next_best_actions: NextBestAction[]
  recommendations?: FinalRecommendations
  strong_proof: boolean
  detected_capability?: DetectedCapability | null
  detected_additional_skills?: DetectedSkillEntry[]
  grouped_skill_evidence?: GroupedSkillEvidence[]
}

export async function runFinalEvaluation(
  sessionId: string,
  claimedSkills: string[],
  githubUrl?: string | null,
): Promise<FinalEvaluationResult> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/evaluate/final`,
    {
      method: "POST",
      body: JSON.stringify({
        claimed_skills: claimedSkills,
        github_url: githubUrl ?? null,
      }),
    },
  )
  if (!res.ok) throw new Error(`Final evaluation failed (HTTP ${res.status}).`)
  return res.json() as Promise<FinalEvaluationResult>
}

export async function getFinalEvaluation(
  sessionId: string,
): Promise<FinalEvaluationResult | null> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/evaluate/final`,
  )
  if (res.status === 404) return null
  if (!res.ok) return null
  return res.json() as Promise<FinalEvaluationResult>
}

export type OptionalEvidenceSourceType = "document" | "linkedin_profile" | "certificate_transcript"

export type OptionalEvidenceResponse = {
  user_id: string
  proof_session_id?: string | null
  source_type: OptionalEvidenceSourceType
  status: string
  file_path?: string | null
  profile_url?: string | null
  analysis_json: Record<string, unknown>
  evidence_objects: Array<Record<string, unknown>>
}

export async function submitOptionalEvidence(
  sessionId: string,
  payload: {
    source_type: OptionalEvidenceSourceType
    raw_text?: string
    profile_url?: string | null
    section_label?: string | null
    file_path?: string | null
  },
): Promise<OptionalEvidenceResponse> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/optional-evidence`,
    { method: "POST", body: JSON.stringify(payload) },
  )
  if (!res.ok) throw new Error(`Optional evidence analysis failed (HTTP ${res.status}).`)
  return res.json() as Promise<OptionalEvidenceResponse>
}

export async function listOptionalEvidence(sessionId: string): Promise<OptionalEvidenceResponse[]> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/optional-evidence`,
  )
  if (!res.ok) return []
  return res.json() as Promise<OptionalEvidenceResponse[]>
}

export async function uploadOptionalEvidenceFile(
  sessionId: string,
  file: File,
): Promise<OptionalEvidenceResponse> {
  const supabase = (await import("@/lib/supabase/client")).createSupabaseBrowserClient()
  const { data: { session } } = await supabase.auth.getSession()
  const headers: Record<string, string> = {}
  if (session?.access_token) headers["Authorization"] = `Bearer ${session.access_token}`

  const form = new FormData()
  form.append("file", file)
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/optional-evidence/upload`,
    { method: "POST", body: form, headers },
  )
  if (!res.ok) {
    let msg = `File upload failed (HTTP ${res.status}).`
    try { const j = await res.json(); msg = j?.detail?.message ?? msg } catch { /* ignore */ }
    throw new Error(msg)
  }
  return res.json() as Promise<OptionalEvidenceResponse>
}

// ── Extension Proof Workflow Analysis ────────────────────────────────────────

export type WorkflowAnalysisType =
  | "timeline_only"
  | "video_frame_analysis"
  | "full_multimodal_analysis"

export type WorkflowConfidence = "high" | "medium" | "low" | "insufficient"

export type WorkflowAnalysisStageStatus =
  | "pending"
  | "in_progress"
  | "complete"
  | "failed"
  | "coming_soon"

export type WorkflowAnalysisStage = {
  key: string
  label: string
  status: WorkflowAnalysisStageStatus
  note?: string | null  // optional warning/context for this stage
}

// ── Observed Demonstration types (v3/v4) ─────────────────────────────────────

export type VisualAnalysisStatus =
  // v5 provider-agnostic values (current)
  | "analyzed"       // provider ran and frames were analyzed
  | "pending"        // frames stored, analysis queued
  | "skipped"        // frames stored but skipped (no bytes)
  | "failed"         // provider error
  | "not_configured" // no VISUAL_ANALYSIS_PROVIDER set (safe default)
  // legacy values (pre-v5, kept for backward compatibility)
  | "available"
  | "partial"
  | "not_available"
  | "not_captured"

/** DOM text capture status from the browser extension (distinct from OCR/frame analysis). */
export type VisibleEvidenceStatus = "available" | "partial" | "not_captured"

export type ResultValueSource = "ocr" | "dom" | "event" | "model_output_text"

/** Evidence provenance per demonstration step (v4). */
export type EvidenceSource = "dom_snapshot" | "event_metadata" | "inferred_from_click"

export type DetectedResultValue = {
  label: string
  value: string
  confidence: number | null
  source: ResultValueSource
}

export type DemonstrationSkillEvidence = {
  skill: string
  support_level: "strong" | "partial" | "weak" | "missing"
  reasoning: string
}

export type DemonstrationStep = {
  step_number: number
  timestamp_ms: number | null
  user_action: string
  observed_input: string | null
  observed_output: string | null
  visible_text_evidence: string[]
  detected_result_values: DetectedResultValue[]
  demonstrated_feature: string
  skill_evidence: DemonstrationSkillEvidence[]
  confidence: "high" | "medium" | "low"
  needs_review: boolean
  /** v4: where this step's evidence came from */
  evidence_source?: EvidenceSource
}

export type ObservedDemonstration = {
  target_app: string
  // OCR/frame analysis — always "not_available" until implemented
  visual_analysis_status: VisualAnalysisStatus
  // DOM text capture status — "available" | "partial" | "not_captured"
  dom_evidence_status?: VisibleEvidenceStatus
  /** v4: DOM text capture status from the browser extension (alias for dom_evidence_status) */
  visible_evidence_status?: VisibleEvidenceStatus
  // OCR status — always "not_available" until implemented
  ocr_status?: string
  // Graphical rendering (canvas/SVG detected)
  has_graphical_rendering?: boolean
  // Top result-like text snippets captured from DOM
  top_result_snippets?: string[]
  steps: DemonstrationStep[]
  summary: string
  limitations: string[]
}

// ── Sequence Analysis types (v6 — Week 3) ─────────────────────────────────────

/** One workflow stage captured during sequence analysis. */
export type WorkflowStageSummary = {
  stage: string
  description: string
  frame_index?: number | null
  confidence?: string | null
}

/** Input→Action→Output chain captured by sequence analysis. */
export type InputActionOutputChain = {
  inputs?: string[]
  actions?: string[]
  outputs?: string[]
  [key: string]: unknown
}

/**
 * Result of multi-frame sequence analysis (backend Week 3).
 * Returned via WorkflowAnalysisResponse.sequence_analysis.
 * All fields use to_public_dict() — no raw paths or private metadata.
 */
export type SequenceAnalysisResult = {
  /** Status: completed | not_available | failed | insufficient_frames | skipped */
  sequence_analysis_status: string
  analyzed_frame_count: number
  workflow_stage_summaries: WorkflowStageSummary[]
  input_action_output_chain: InputActionOutputChain
  before_after_changes: string[]
  observed_outputs: string[]
  /** Skills the sequence evidence supports */
  supported_skills: string[]
  /** Claims made but not confirmed by frames */
  unsupported_claims: string[]
  /** Qualitative strength: strong | moderate | weak | insufficient */
  evidence_strength: string
  /** 0–100 confidence score */
  confidence_score: number
  /** Safe for public/recruiter view — no private metadata */
  public_safe_summary: string
  /** Recruiter-oriented safe summary */
  recruiter_safe_summary: string
  limitations: string[]
}

// ── Video keyframe evidence types (v6 — Week 2) ────────────────────────────────

export type VideoKeyframeEvidenceStatus =
  | "not_captured"
  | "pending"
  | "extracted"
  | "failed"
  | "skipped"
  | "not_available"

export type WorkflowAnalysisResponse = {
  id: string
  proof_session_id: string
  analysis_type: WorkflowAnalysisType
  analyzer_version: string
  workflow_summary: string
  demonstrated_actions: string[]
  supported_skills: string[]
  weakly_supported_skills: string[]
  unsupported_skills: string[]
  evidence_strength_score: number
  workflow_confidence: WorkflowConfidence
  missing_evidence: string[]
  risk_flags: string[]
  recruiter_summary: string
  student_improvement_suggestions: string[]
  human_review_needed: boolean
  // v2 metadata
  target_website?: string
  target_site_pages_count?: number
  supporting_evidence_count?: number
  noise_filtered_count?: number
  filtered_unrelated_activity?: {
    count: number
    hosts: string[]
  }
  // v3/v4 precise visual evidence
  observed_demonstration?: ObservedDemonstration | null
  // Visual frame analysis (v5): provider-agnostic screenshot evidence
  visual_analysis_status?: VisualAnalysisStatus
  /** Provider used for visual analysis (none | local_ocr | local_vision | openai | veribridge_future) */
  visual_analysis_provider?: string
  /** Number of analyzed (OCR/vision-processed) visual frames */
  visual_frame_count?: number
  /** Total stored frames including not_configured (frames captured regardless of provider) */
  visual_frames_stored?: number
  // DOM text capture status from the browser extension
  dom_evidence_status?: VisibleEvidenceStatus
  /** v4: alias for dom_evidence_status (backward compat) */
  visible_evidence_status?: VisibleEvidenceStatus
  // OCR status
  ocr_status?: string
  // Graphical rendering (canvas/SVG)
  has_graphical_rendering?: boolean
  graphical_rendering_note?: string | null
  top_result_snippets?: string[]
  page_context_summary?: string | null
  // ── Video keyframe evidence (Phase 0 — unified MediaRecorder) ───────────────
  /** "extracted" when keyframes extracted from uploaded video; null when no video. */
  video_keyframe_status?: VideoKeyframeEvidenceStatus | null
  /** Number of keyframes extracted from the uploaded video. */
  video_keyframe_count?: number | null
  /** Timestamps (ms from start) of each extracted keyframe. Empty when no video. */
  video_keyframe_timestamps_ms?: number[]
  /** Duration of the uploaded video in milliseconds (approximate, from last keyframe). */
  video_duration_ms?: number | null
  /** Exact error reason from the backend when video_keyframe_status is "failed". */
  video_upload_error?: string | null
  /**
   * High-level video upload status derived from keyframe status:
   * 'uploaded' = video uploaded and keyframes extracted;
   * 'failed'   = video uploaded but keyframe extraction failed;
   * 'none'     = no video recorded for this session.
   */
  video_upload_status?: string | null
  // ── OCR / frame evidence (v5 — local_ocr provider) ───────────────────────────
  /** Detected label:value pairs from OCR (e.g. [{label:"dog",value:"0.89",source:"ocr"}]) */
  visual_result_values?: Array<{ label: string; value: string; confidence?: number; source?: string }>
  /** Condensed summary of OCR text from analyzed keyframes (pipe-separated lines) */
  visual_summary?: string | null
  // ── Sequence analysis (v6 — Week 3) ──────────────────────────────────────────
  /** Full sequence analysis result. Public-safe — no raw paths or private metadata. */
  sequence_analysis?: SequenceAnalysisResult | null
  // ── Frame OCR evidence summary (v6) ──────────────────────────────────────────
  /**
   * Structured summary of what OCR/visual analysis found in video keyframes.
   * Includes page context (homepage vs training UI vs prediction output),
   * top OCR text snippets, what was/wasn't observed, and per-skill OCR signals.
   */
  frame_ocr_evidence_summary?: {
    has_ocr_evidence: boolean
    ocr_provider: string
    frames_analyzed: number
    top_ocr_snippets: string[]
    detected_page_context: "homepage_marketing" | "training_ui" | "prediction_output" | "demo_content" | "unknown" | "filtered_non_target_frame"
    observed_summary: string
    what_was_not_observed: string[]
    skill_signals: Array<{
      skill: string
      ocr_support: "partial" | "insufficient"
      reasoning: string
      ocr_terms_found: string[]
    }>
  } | null
  // ── Advanced Visual Reasoning (v7 — Qwen2.5-VL / Qwen3-VL) ──────────────────
  /**
   * Structured skill-evidence reasoning from open-weight vision models.
   * null when VISUAL_REASONING_ENABLED=false (the default).
   */
  visual_reasoning_summary?: {
    status: "analyzed" | "failed" | "disabled" | "missing_dependency" | "not_configured" | "rejected_inconsistent" | "rejected_stale" | "skipped" | "pending" | "filtered_non_target_frame"
    provider: string
    frames_analyzed: number
    summary: string
    observations: Array<{
      frame_index: number | null
      timestamp_ms: number | null
      model_provider: string
      visual_summary: string
      visible_ui_elements: string[]
      visible_objects: string[]
      visible_objects_or_diagrams: string[]
      detected_workflow_stage: string
      detected_user_action: string
      detected_actions: string[]
      detected_outputs: string[]
      skill_evidence: Record<string, { items_visible: string[]; verdict: string }>
      supported_skills: string[]
      detected_skills_supported: string[]
      missing_or_unclear_evidence: string[]
      confidence_score: number
      limitations: string[]
      status: string
    }>
    supported_signals: string[]
    missing_claims: string[]
    limitations: string[]
    skill_timeline?: Array<{
      timestamp_ms: number | null
      timestamp_label: string
      detected_skill: string
      evidence_source: "Qwen" | "OCR" | "DOM" | "fusion"
      evidence_text: string
      confidence: number
      support_level: "supported" | "partial" | "missing" | "unclear"
      reason: string
    }>
  } | null
  // progress tracking
  progress: number
  current_stage: string
  stages: WorkflowAnalysisStage[]
  analysis_stage?: string
  progress_percent?: number
  created_at: string
  updated_at: string | null
}

export type WorkflowAnalyzeRequest = {
  claimed_skills: string[]
  proof_objective: string
  original_url: string
  url_type: string
  github_url?: string | null
}

export async function analyzeWorkflowEvidence(
  sessionId: string,
  request: WorkflowAnalyzeRequest
): Promise<WorkflowAnalysisResponse> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/analyze/workflow`,
    {
      method: "POST",
      body: JSON.stringify(request),
    }
  )
  if (res.status === 404) throw new Error("Extension proof session not found.")
  if (res.status === 409) {
    const raw = await res.text()
    let msg = "Session is not in an analyzable state."
    try { msg = (JSON.parse(raw) as { detail?: { message?: string } }).detail?.message ?? msg } catch { /* */ }
    throw new Error(msg)
  }
  if (!res.ok) {
    const raw = await res.text()
    let msg = `Workflow analysis failed (HTTP ${res.status}).`
    try { msg = (JSON.parse(raw) as { detail?: { message?: string } }).detail?.message ?? msg } catch { /* */ }
    throw new Error(msg)
  }
  return res.json()
}

export async function getWorkflowAnalysis(
  sessionId: string
): Promise<WorkflowAnalysisResponse | null> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/analysis/workflow`
  )
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Get workflow analysis failed (HTTP ${res.status}).`)
  return res.json()
}

// ── Visible Evidence Capture (v4) ─────────────────────────────────────────────

/** One DOM-snapshot event captured by the browser extension. */
export type VisibleEvidenceEventInput = {
  event_type:
    | "page_load"
    | "click"
    | "input_change"
    | "file_upload"
    | "form_submit"
    | "dom_snapshot"
    | "result_detected"
    | "recording_end"
  timestamp_ms?: number | null
  event_id?: string | null
  url?: string
  page_title?: string
  /** Sanitized visible text blocks. Must not include passwords, tokens, or local paths. */
  visible_text_blocks?: string[]
  /** Text blocks near result/output keywords. */
  result_like_blocks?: string[]
  /** Sanitized form inputs (exclude password fields). */
  input_snapshot?: Record<string, unknown>
  /** Clicked element metadata. */
  action_snapshot?: Record<string, unknown>
  file_upload_meta?: {
    file_category: string
    file_extension: string
    file_name_masked?: string | null
  } | null
}

export type VisibleEvidenceBatchRequest = {
  events: VisibleEvidenceEventInput[]
}

export type VisibleEvidenceIngestResponse = {
  session_id: string
  events_received: number
  events_stored: number
  privacy_flags_raised: number
  status: "accepted"
}

export type VisibleEvidenceExtractedResultValue = {
  label: string
  value: string
  unit: string
  raw_text: string
  source: string
}

export type VisibleEvidenceExtractedObservations = {
  observed_inputs: string[]
  observed_actions: string[]
  observed_outputs: string[]
  detected_result_values: VisibleEvidenceExtractedResultValue[]
  demonstrated_features: string[]
  skill_support_reasoning: string[]
  visible_evidence_status: VisibleEvidenceStatus
  event_count: number
  result_event_count: number
  file_upload_count: number
  form_submit_count: number
}

export type VisibleEvidenceSummaryEvent = {
  event_type: string
  timestamp_ms: number | null
  page_title: string
  result_block_count: number
  visible_block_count: number
  has_file_upload: boolean
  privacy_flags: string[]
}

export type VisibleEvidenceSummaryResponse = {
  proof_session_id: string
  event_count: number
  result_event_count: number
  file_upload_count: number
  visible_evidence_status: VisibleEvidenceStatus
  events_summary: VisibleEvidenceSummaryEvent[]
  extracted_observations: VisibleEvidenceExtractedObservations
  privacy_note: string
}

/**
 * Submit a batch of visible evidence events captured by the browser extension.
 * Call this at end of recording before calling analyzeWorkflowEvidence.
 *
 * The extension should sanitize events client-side before calling this:
 * - Remove passwords, API keys, local file paths, Supabase/internal URLs.
 * - Only include text from the target website (not other tabs).
 */
export async function submitVisibleEvidence(
  sessionId: string,
  request: VisibleEvidenceBatchRequest
): Promise<VisibleEvidenceIngestResponse> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/workflow/visible-evidence`,
    {
      method: "POST",
      body: JSON.stringify(request),
    }
  )
  if (!res.ok) {
    const raw = await res.text()
    let msg = `Visible evidence submission failed (HTTP ${res.status}).`
    try { msg = (JSON.parse(raw) as { detail?: { message?: string } }).detail?.message ?? msg } catch { /* */ }
    throw new Error(msg)
  }
  return res.json()
}

/**
 * Get visible evidence summary for debugging.
 * Student/admin only — NOT recruiter-facing.
 */
export async function getVisibleEvidenceSummary(
  sessionId: string
): Promise<VisibleEvidenceSummaryResponse | null> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/workflow/visible-evidence/summary`
  )
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Get visible evidence summary failed (HTTP ${res.status}).`)
  return res.json()
}

// ── Live Website Check ────────────────────────────────────────────────────────

export type LiveWebsiteCheckConfidence = "high" | "medium" | "low" | "failed" | "not_applicable"

export type LiveWebsiteCheckStatus = "complete" | "failed" | "not_applicable"

export type LiveCheckStageStatus = "pending" | "in_progress" | "complete" | "failed"

export type LiveWebsiteCheckStage = {
  key: string
  label: string
  status: LiveCheckStageStatus
}

export type LiveWebsiteCheckResponse = {
  id: string
  proof_session_id: string
  status: LiveWebsiteCheckStatus
  website_url: string
  final_url: string | null
  status_code: number | null
  response_time_ms: number | null
  content_type: string | null
  page_title: string | null
  is_reachable: boolean
  confidence: LiveWebsiteCheckConfidence
  risk_flags: string[]
  recruiter_summary: string
  error_message: string | null
  checked_at: string
  progress: number
  current_stage: string
  stages: LiveWebsiteCheckStage[]
}

export async function runLiveWebsiteCheck(
  sessionId: string,
  websiteUrl: string
): Promise<LiveWebsiteCheckResponse> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/check/live-website`,
    {
      method: "POST",
      body: JSON.stringify({ website_url: websiteUrl }),
    }
  )
  if (!res.ok) {
    const raw = await res.text()
    let msg = `Live website check failed (HTTP ${res.status}).`
    try { msg = (JSON.parse(raw) as { detail?: { message?: string } }).detail?.message ?? msg } catch { /* */ }
    throw new Error(msg)
  }
  return res.json()
}

export async function getLiveWebsiteCheck(
  sessionId: string
): Promise<LiveWebsiteCheckResponse | null> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/check/live-website`
  )
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Get live website check failed (HTTP ${res.status}).`)
  return res.json()
}

// ── Workflow Privacy Scan ─────────────────────────────────────────────────────

export type WorkflowPrivacyScanStatus = "clean" | "redacted" | "flagged"

export type WorkflowPrivacyScanResponse = {
  id: string | null
  user_id: string
  proof_session_id: string
  status: WorkflowPrivacyScanStatus
  risk_flags: string[]
  redacted_fields_count: number
  redacted_urls_count: number
  contains_sensitive_data: boolean
  scan_summary: string
  created_at: string | null
  updated_at: string | null
}

export async function runWorkflowPrivacyScan(
  sessionId: string
): Promise<WorkflowPrivacyScanResponse> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/privacy-scan`,
    { method: "POST" }
  )
  if (res.status === 404) throw new Error("Extension proof session not found.")
  if (!res.ok) {
    const raw = await res.text()
    let msg = `Privacy scan failed (HTTP ${res.status}).`
    try { msg = (JSON.parse(raw) as { detail?: { message?: string } }).detail?.message ?? msg } catch { /* */ }
    throw new Error(msg)
  }
  return res.json()
}

export async function getWorkflowPrivacyScan(
  sessionId: string
): Promise<WorkflowPrivacyScanResponse | null> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/privacy-scan`
  )
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Get privacy scan failed (HTTP ${res.status}).`)
  return res.json()
}

// ── Skill Evidence Profiles ───────────────────────────────────────────────────

export type EvidenceLevel =
  | "self_claimed"
  | "workflow_evidence_complete"
  | "workflow_analysis_ai_reviewed"
  | "multi_source_ai_reviewed"
  | "final_verification_ready"

export type EvidenceSourceStatus = {
  key: string
  label: string
  status: "complete" | "pending" | "unavailable"
}

export type EvidenceAttemptSummary = {
  evidence_id: string
  session_id: string | null
  session_status: string | null
  has_analysis: boolean
  skill_name: string
  submitted_at: string
}

export type SkillEvidenceProfile = {
  profile_id: string
  primary_skill_name: string
  all_skill_names: string[]
  proof_objective: string | null
  evidence_url: string | null
  github_url: string | null
  url_type: string
  evidence_level: EvidenceLevel
  evidence_level_label: string
  has_workflow_proof: boolean
  has_workflow_analysis: boolean
  has_github_evidence: boolean
  confidence: string
  evidence_strength_score: number | null
  workflow_analysis_summary: string | null
  latest_session_id: string | null
  latest_session_status: string | null
  evidence_sources: EvidenceSourceStatus[]
  missing_evidence: string[]
  submission_count: number
  first_submitted_at: string
  last_updated_at: string
  history: EvidenceAttemptSummary[]
}

export async function getSkillEvidenceProfiles(): Promise<SkillEvidenceProfile[]> {
  const res = await fetchAPI("/api/v1/student/skill-evidence-profiles")
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

// ── Verification Readiness Report ─────────────────────────────────────────────

export type ReadinessLevel = "strong" | "moderate" | "weak" | "insufficient"

/**
 * Computed readiness report from GET /student/extension-proof/sessions/:id/readiness
 *
 * IMPORTANT: final_verification_status is NEVER "complete" — it is only
 * "pending" or "ready_for_review".  Final Verification completion is a
 * separate VeriBridge reviewer step.
 */
export type ScoreContributor = {
  label: string
  points: number            // positive = earned, negative = deducted
  type: "positive" | "negative" | "info"  // info = not yet earned
}

export type SkillImprovementTip = {
  skill: string
  status: "partial" | "missing"
  category: string
  tip: string
}

export type VerificationReadinessReport = {
  proof_session_id: string
  readiness_score: number          // 0–100
  readiness_level: ReadinessLevel
  final_verification_status: "pending" | "ready_for_review"
  strongly_supported_skills: string[]
  partially_supported_skills: string[]
  needs_more_evidence: string[]
  risk_flags: string[]
  recommended_next_actions: string[]
  recruiter_summary: string
  is_local_only: boolean
  has_github_evidence: boolean
  computed_at: string
  // ── Personalized recommendations ───────────────────────────────────────
  score_contributors: ScoreContributor[]
  score_explanation: string[]
  skill_improvement_tips: SkillImprovementTip[]
}

export async function getVerificationReadiness(
  sessionId: string
): Promise<VerificationReadinessReport | null> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/readiness`
  )
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Get readiness report failed (HTTP ${res.status}).`)
  return res.json()
}

// ── Project Defense Transcript Analysis ──────────────────────────────────────

export type ProjectDefensePrivacyScanStatus = "clean" | "redacted" | "flagged"

export type TranscriptionStatus =
  | "not_started"
  | "uploaded"
  | "transcription_pending"
  | "transcript_ready"
  | "analysis_complete"

export type TranscriptCorrectionEntry = {
  original: string
  corrected: string
  reason: string
}

export type TranscriptRefinementStatus =
  | "not_started"
  | "in_progress"
  | "complete"
  | "failed"

export type ProjectDefenseAnalysisResponse = {
  id: string | null
  user_id: string
  proof_session_id: string
  // ── Media metadata ──────────────────────────────────────────────────────────
  video_url: string | null
  media_url: string | null
  media_type: string | null
  media_filename: string | null
  media_storage_path: string | null
  transcription_status: TranscriptionStatus
  transcript_reviewed: boolean
  // ── Transcript + refinement fields ─────────────────────────────────────────
  transcript_text: string
  raw_transcript: string | null
  refined_transcript: string | null
  transcript_correction_summary: TranscriptCorrectionEntry[]
  transcript_glossary_matches: string[]
  transcript_refinement_status: TranscriptRefinementStatus
  transcript_needs_review: boolean
  // ── NLP outputs ─────────────────────────────────────────────────────────────
  transcript_summary: string
  skills_mentioned: string[]
  skills_explained_well: string[]
  skills_missing_from_explanation: string[]
  consistency_with_evidence_score: number   // 0–100
  explanation_clarity_score: number         // 0–100
  ownership_signal_score: number            // 0–100
  technical_depth_score: number             // 0–100
  overall_defense_score: number             // 0–100
  risk_flags: string[]
  recruiter_summary: string
  recommended_improvements: string[]
  privacy_scan_status: ProjectDefensePrivacyScanStatus
  created_at: string | null
  updated_at: string | null
}

export type ProjectDefenseMediaUploadResponse = {
  proof_session_id: string
  media_filename: string
  media_type: string
  media_size_bytes: number
  media_url: string | null
  media_storage_path: string | null
  transcription_status: TranscriptionStatus
  storage_configured: boolean
  message: string
}

export type ProjectDefenseUpdateTranscriptRequest = {
  transcript_text: string
  transcript_reviewed: boolean
}

export type ProjectDefenseAnalyzeRequest = {
  video_url?: string | null
  transcript_text: string
  claimed_skills: string[]
  proof_objective?: string
  workflow_summary?: string
  github_summary?: string
  live_check_summary?: string
}

/**
 * Submit and analyse a project defense transcript for a proof session.
 *
 * Transcript is scanned for sensitive data before storage.  If flagged the
 * response will have privacy_scan_status = 'flagged' and the result is hidden
 * from recruiter view until reviewed.
 */
export async function analyzeProjectDefense(
  sessionId: string,
  request: ProjectDefenseAnalyzeRequest
): Promise<ProjectDefenseAnalysisResponse> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/analyze/project-defense`,
    {
      method: "POST",
      body: JSON.stringify({
        video_url: request.video_url ?? null,
        transcript_text: request.transcript_text,
        claimed_skills: request.claimed_skills,
        proof_objective: request.proof_objective ?? "",
        workflow_summary: request.workflow_summary ?? "",
        github_summary: request.github_summary ?? "",
        live_check_summary: request.live_check_summary ?? "",
      }),
    }
  )
  if (res.status === 404) throw new Error("Extension proof session not found.")
  if (!res.ok) {
    const raw = await res.text()
    let msg = `Project defense analysis failed (HTTP ${res.status}).`
    try { msg = (JSON.parse(raw) as { detail?: { message?: string } }).detail?.message ?? msg } catch { /* */ }
    throw new Error(msg)
  }
  return res.json()
}

/**
 * Get the stored project defense analysis for a proof session.
 * Returns null if no analysis has been submitted yet.
 */
export async function getProjectDefenseAnalysis(
  sessionId: string
): Promise<ProjectDefenseAnalysisResponse | null> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/analysis/project-defense`
  )
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Get project defense analysis failed (HTTP ${res.status}).`)
  return res.json()
}

/**
 * Upload a defense media file (mp4/mov/webm/mp3/wav/m4a, max 200 MB).
 * Uses XHR so upload progress events can be reported.
 * Media is stored privately; automatic transcription is not connected in the MVP.
 */
export async function uploadProjectDefenseMedia(
  sessionId: string,
  file: File,
  onProgress?: (pct: number) => void,
): Promise<ProjectDefenseMediaUploadResponse> {
  const supabase = createSupabaseBrowserClient()
  const { data: { session } } = await supabase.auth.getSession()

  return new Promise((resolve, reject) => {
    const formData = new FormData()
    formData.append("file", file)

    const xhr = new XMLHttpRequest()

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100))
      }
    })

    xhr.addEventListener("load", () => {
      if (xhr.status === 201) {
        try {
          const data = JSON.parse(xhr.responseText) as ProjectDefenseMediaUploadResponse
          // Debug: log the upload response shape to help diagnose storage config issues.
          // Safe — media_storage_path is a path string, not a secret.
          console.debug("[VeriBridge] upload-media response:", {
            status: xhr.status,
            media_filename: data.media_filename,
            media_storage_path: data.media_storage_path,
            storage_configured: data.storage_configured,
            message: data.message,
          })
          resolve(data)
        } catch {
          reject(new Error("Invalid response from server."))
        }
      } else {
        let msg = `Media upload failed (HTTP ${xhr.status}).`
        try {
          const errData = JSON.parse(xhr.responseText) as { detail?: { message?: string } | string }
          if (typeof errData.detail === "string") msg = errData.detail
          else msg = errData.detail?.message ?? msg
        } catch { /* */ }
        console.debug("[VeriBridge] upload-media error:", { status: xhr.status, body: xhr.responseText })
        reject(new Error(msg))
      }
    })

    xhr.addEventListener("error", () => reject(new Error("Media upload failed — network error.")))
    xhr.addEventListener("abort", () => reject(new Error("Media upload was cancelled.")))

    xhr.open(
      "POST",
      `${API_BASE}/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/defense/upload-media`,
    )
    if (session?.access_token) {
      xhr.setRequestHeader("Authorization", `Bearer ${session.access_token}`)
    }
    xhr.send(formData)
  })
}

/**
 * Save an edited transcript (and reviewed flag) before running analysis.
 * Sets transcription_status to 'transcript_ready' when transcript_reviewed=true.
 */
export async function updateDefenseTranscript(
  sessionId: string,
  request: ProjectDefenseUpdateTranscriptRequest,
): Promise<ProjectDefenseAnalysisResponse> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/defense/transcript`,
    {
      method: "PATCH",
      body: JSON.stringify(request),
    },
  )
  if (res.status === 404) throw new Error("No defense record found. Upload a media file first.")
  if (!res.ok) {
    const raw = await res.text()
    let msg = `Transcript update failed (HTTP ${res.status}).`
    try { msg = (JSON.parse(raw) as { detail?: { message?: string } }).detail?.message ?? msg } catch { /* */ }
    throw new Error(msg)
  }
  return res.json()
}

// ── Project Defense Transcription ─────────────────────────────────────────────

/**
 * Response from POST /defense/transcribe.
 *
 * When configured=false the backend has no transcription provider set up.
 * The frontend shows the manual-paste fallback instead of throwing an error.
 */
export interface TranscriptSegment {
  start_time: number
  end_time: number
  text: string
}

export interface ProjectDefenseTranscribeResponse {
  proof_session_id: string
  transcript_text: string
  transcription_status: string
  transcript_reviewed: boolean
  provider_used: string
  configured: boolean
  message: string
  // Timestamped segments (present when local_whisper/faster-whisper was used)
  transcript_segments?: TranscriptSegment[]
  // Refinement fields (present when auto-refinement ran after transcription)
  raw_transcript?: string | null
  refined_transcript?: string | null
  transcript_correction_summary?: TranscriptCorrectionEntry[]
  transcript_glossary_matches?: string[]
  transcript_refinement_status?: TranscriptRefinementStatus
  transcript_needs_review?: boolean
  refinement_display_summary?: string
}

export interface ProjectDefenseRefineTranscriptRequest {
  claimed_skills?: string[]
  project_context?: string
  website_url?: string | null
  github_url?: string | null
}

export interface ProjectDefenseRefineTranscriptResponse {
  proof_session_id: string
  raw_transcript: string
  refined_transcript: string
  transcript_correction_summary: TranscriptCorrectionEntry[]
  transcript_glossary_matches: string[]
  transcript_refinement_status: TranscriptRefinementStatus
  transcript_needs_review: boolean
  confidence: number
  refinement_display_summary: string
  message: string
}

/**
 * Ask the backend to transcribe the registered defense media file.
 *
 * Always resolves (never throws) when the provider is not configured —
 * check response.configured to know whether transcript_text was populated.
 * Only throws on HTTP errors unrelated to provider availability (4xx / 5xx).
 */
export async function transcribeDefenseMedia(
  sessionId: string,
): Promise<ProjectDefenseTranscribeResponse> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/defense/transcribe`,
    { method: "POST" },
  )
  // 404 = no media registered yet
  if (res.status === 404) throw new Error("No media file registered. Upload or record first.")
  if (!res.ok) {
    const raw = await res.text()
    let msg = `Transcription failed (HTTP ${res.status}).`
    try { msg = (JSON.parse(raw) as { detail?: { message?: string } }).detail?.message ?? msg } catch { /* */ }
    throw new Error(msg)
  }
  // 200 with configured=false is a valid, non-error response
  return res.json() as Promise<ProjectDefenseTranscribeResponse>
}

/**
 * (Re-)run ASR transcript correction on the stored raw transcript.
 * Corrects spelling and term recognition mistakes only — does not rewrite.
 * Use when transcription already ran but auto-correction failed, or when
 * the student updates their context (skills, project description).
 * Returns 404 if no raw transcript exists for this session yet.
 */
export async function refineDefenseTranscript(
  sessionId: string,
  request: ProjectDefenseRefineTranscriptRequest = {},
): Promise<ProjectDefenseRefineTranscriptResponse> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/defense/refine-transcript`,
    {
      method: "POST",
      body: JSON.stringify({
        claimed_skills: request.claimed_skills ?? [],
        project_context: request.project_context ?? "",
        website_url: request.website_url ?? null,
        github_url: request.github_url ?? null,
      }),
    },
  )
  if (res.status === 404) throw new Error("No raw transcript found. Transcribe first.")
  if (!res.ok) {
    const raw = await res.text()
    let msg = `Transcript correction failed (HTTP ${res.status}).`
    try { msg = (JSON.parse(raw) as { detail?: { message?: string } }).detail?.message ?? msg } catch { /* */ }
    throw new Error(msg)
  }
  return res.json() as Promise<ProjectDefenseRefineTranscriptResponse>
}

// ── Verification Review ───────────────────────────────────────────────────────

/**
 * AI review status values (Track A).
 * "human_verified" is intentionally absent — AI review can never produce it.
 */
export type AiReviewStatus =
  | "not_submitted"
  | "submitted_for_ai_review"
  | "ai_review_in_progress"
  | "ai_approved_for_sharing"
  | "needs_more_evidence"
  | "manual_review_recommended"
  | "privacy_flagged"

/** Human / faculty / expert review status values (Track B). */
export type HumanReviewStatus =
  | "human_review_not_requested"
  | "human_review_requested"
  | "faculty_review_pending"
  | "company_review_pending"
  | "domain_expert_review_pending"
  | "faculty_reviewed"
  | "company_reviewed"
  | "domain_expert_reviewed"
  | "human_verified"
  | "human_review_rejected"

export type ReviewerRole =
  | "veribridge_admin"
  | "faculty_reviewer"
  | "company_reviewer"
  | "domain_expert"
  | "recruiter_reviewer"

export type AssignmentStatus =
  | "pending"
  | "accepted"
  | "declined"
  | "completed"
  | "withdrawn"

export interface HumanReviewAssignment {
  id: string
  review_request_id: string
  reviewer_name: string
  reviewer_role: ReviewerRole
  reviewer_field: string
  status: AssignmentStatus
  assigned_at: string
  completed_at: string | null
  reviewer_decision: "approved" | "rejected" | "needs_revision" | "escalate" | null
  verified_skills: string[]
  requested_improvements: string[]
}

export interface VerificationReviewResponse {
  id: string
  proof_session_id: string
  user_id: string

  // Track A — AI review
  ai_review_status: AiReviewStatus
  ai_review_started_at: string | null
  ai_review_completed_at: string | null
  ai_decision_summary: string

  // Track B — Human review
  human_review_status: HumanReviewStatus
  human_review_requested_at: string | null

  // Readiness snapshot
  readiness_score: number
  readiness_level: "strong" | "moderate" | "weak" | "insufficient"

  // Lifecycle
  submitted_at: string | null
  created_at: string
  updated_at: string

  // Human assignments (empty in MVP)
  assignments: HumanReviewAssignment[]
}

export interface AdminReviewListItem {
  id: string
  proof_session_id: string
  user_id: string
  ai_review_status: AiReviewStatus
  human_review_status: HumanReviewStatus
  readiness_score: number
  readiness_level: "strong" | "moderate" | "weak" | "insufficient"
  submitted_at: string | null
  ai_review_completed_at: string | null
  ai_decision_summary: string
  created_at: string
  updated_at: string
}

/**
 * Submit a proof session for VeriBridge AI review.
 *
 * Reads the current readiness score + level from the already-computed report
 * and sends them as query params.  The backend reads the privacy scan result
 * and applies decision rules.
 *
 * Wording: "ai_approved_for_sharing" ≠ "Human Verified".
 * human_verified is NEVER returned by this call.
 */
export async function submitForAiReview(
  sessionId: string,
  readinessScore: number,
  readinessLevel: string,
): Promise<VerificationReviewResponse> {
  const params = new URLSearchParams({
    readiness_score: String(readinessScore),
    readiness_level: readinessLevel,
  })
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/submit-ai-review?${params}`,
    { method: "POST" },
  )
  if (res.status === 409) {
    const data = (await res.json()) as { detail?: { message?: string; code?: string } }
    const msg = data.detail?.message ?? "Review already submitted."
    throw new Error(msg)
  }
  if (!res.ok) {
    const raw = await res.text()
    let msg = `AI review submission failed (HTTP ${res.status}).`
    try { msg = (JSON.parse(raw) as { detail?: { message?: string } }).detail?.message ?? msg } catch { /* */ }
    throw new Error(msg)
  }
  return res.json() as Promise<VerificationReviewResponse>
}

/**
 * Get the current AI + human review status for a proof session.
 * Returns null if the student has not yet submitted for review (404).
 */
export async function getReviewStatus(
  sessionId: string,
): Promise<VerificationReviewResponse | null> {
  const res = await fetchAPI(
    `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/review-status`,
  )
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Failed to fetch review status (HTTP ${res.status}).`)
  return res.json() as Promise<VerificationReviewResponse>
}

/**
 * Admin: list all verification review requests.
 */
export async function adminListReviews(
  limit = 100,
  offset = 0,
): Promise<AdminReviewListItem[]> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  const res = await fetchAPI(`/api/v1/admin/verification-reviews?${params}`)
  if (!res.ok) throw new Error(`Failed to fetch review list (HTTP ${res.status}).`)
  return res.json() as Promise<AdminReviewListItem[]>
}

// ── Website Evidence Discovery ─────────────────────────────────────────────

export type DiscoveredEvidenceType =
  | "github_repository"
  | "video_demo"
  | "pdf_report"
  | "google_doc"
  | "google_drive"
  | "linkedin"
  | "deployed_app"
  | "api_docs"
  | "image_or_screenshot"
  | "unknown"

export type DiscoveredEvidenceItem = {
  evidence_type: DiscoveredEvidenceType
  url: string
  domain: string
  title: string | null
  confidence: number
  reason: string
  suggested_action: string
  raw_text: string | null
}

export type WebsiteEvidenceDiscoveryResponse = {
  source_url: string
  final_url: string | null
  status_code: number | null
  page_title: string | null
  items: DiscoveredEvidenceItem[]
  total_discovered: number
  js_heavy_warning: boolean
  limitation: string | null
  error: string | null
  version: string
}

export async function discoverWebsiteEvidence(
  websiteUrl: string,
  proofSessionId?: string | null,
): Promise<WebsiteEvidenceDiscoveryResponse> {
  const res = await fetchAPI("/api/v1/student/website-analysis/discover", {
    method: "POST",
    body: JSON.stringify({
      website_url: websiteUrl,
      proof_session_id: proofSessionId ?? null,
    }),
  })
  if (!res.ok) {
    const raw = await res.text()
    let msg = `Evidence discovery failed (HTTP ${res.status}).`
    try { msg = (JSON.parse(raw) as { detail?: string }).detail ?? msg } catch { /* */ }
    throw new Error(msg)
  }
  return res.json() as Promise<WebsiteEvidenceDiscoveryResponse>
}

/**
 * Admin: manually override the AI review decision.
 * Does NOT set human_verified — that requires a human reviewer action.
 */
export async function adminSetDecision(
  reviewId: string,
  aiReviewStatus: AiReviewStatus,
  aiDecisionSummary: string,
): Promise<VerificationReviewResponse> {
  const res = await fetchAPI(`/api/v1/admin/verification-reviews/${encodeURIComponent(reviewId)}/decision`, {
    method: "POST",
    body: JSON.stringify({ ai_review_status: aiReviewStatus, ai_decision_summary: aiDecisionSummary }),
  })
  if (!res.ok) {
    const raw = await res.text()
    let msg = `Admin decision failed (HTTP ${res.status}).`
    try { msg = (JSON.parse(raw) as { detail?: { message?: string } }).detail?.message ?? msg } catch { /* */ }
    throw new Error(msg)
  }
  return res.json() as Promise<VerificationReviewResponse>
}

// ── Live Proof Feedback ───────────────────────────────────────────────────────

export type LiveEvidenceChecklist = {
  website_loaded: boolean
  dom_text_seen: boolean
  interaction_seen: boolean
  form_input_seen: boolean
  output_or_result_seen: boolean
  chart_or_visual_seen: boolean
  code_or_repo_seen: boolean
  github_seen: boolean
  sensitive_warning: boolean
}

export type LiveSkillSupport = {
  skill: string
  support_level: "missing" | "partial" | "likely"
  evidence_source: string
  short_reason: string
}

export type LiveFeedbackResponse = {
  session_id: string
  recording_status: "recording" | "stopped" | "analyzing"
  checklist: LiveEvidenceChecklist
  live_score: number
  claimed_skill_support: LiveSkillSupport[]
  suggestions: string[]
  sensitive_warning: boolean
  last_updated_at: string
}

/**
 * Poll current live feedback state for a session.
 * Returns null on any error so the frontend can silently ignore failures.
 */
export async function getLiveFeedback(sessionId: string): Promise<LiveFeedbackResponse | null> {
  try {
    const res = await fetchAPI(
      `/api/v1/student/extension-proof/sessions/${encodeURIComponent(sessionId)}/live-feedback`,
    )
    if (!res.ok) return null
    return res.json() as Promise<LiveFeedbackResponse>
  } catch {
    return null
  }
}

// ── Skill Evidence Pipelines ──────────────────────────────────────────────────

export type BackendEvidenceSource = {
  key: string
  label: string
  status: "supported" | "partial" | "missing" | "protected"
  score?: number | null
  reason: string
}

export type BackendSkillPipeline = {
  id: string
  student_id: string | null
  profile_id: string | null
  skill_name: string
  skill_category: string
  confidence_score: number
  support_status: "strongly_supported" | "partially_supported" | "needs_review"
  evidence_count: number
  strongest_proof: { label?: string; reason?: string } | null
  weakest_proof: { label?: string; reason?: string } | null
  missing_evidence: string[]
  next_actions: string[]
  evidence_sources: BackendEvidenceSource[]
  recruiter_summary: string
  student_summary: string
  visibility_status: "public" | "protected" | "private"
  created_at: string
  updated_at: string
}

export type BackendSkillArtifact = {
  id: string
  pipeline_id: string
  proof_session_id: string | null
  source_type: string
  source_title: string
  project_name: string
  visibility: string
  confidence_score: number
  relevance_to_skill: string
  proof_reason: string
  artifact_data: Record<string, unknown>
  exact_code_url?: string | null
  full_file_url?: string | null
  created_at: string
  updated_at: string
}

/**
 * List all skill evidence pipelines for the current student.
 * Returns null on any error (backend unavailable).
 */
export async function listSkillEvidencePipelines(): Promise<BackendSkillPipeline[] | null> {
  try {
    const res = await fetchAPI("/api/v1/student/skill-pipelines")
    if (!res.ok) return null
    return res.json() as Promise<BackendSkillPipeline[]>
  } catch {
    return null
  }
}

/**
 * Get a single skill evidence pipeline by ID.
 * Returns null on 404 or any error.
 */
export async function getSkillEvidencePipeline(
  pipelineId: string,
): Promise<BackendSkillPipeline | null> {
  try {
    const res = await fetchAPI(
      `/api/v1/student/skill-pipelines/${encodeURIComponent(pipelineId)}`,
    )
    if (!res.ok) return null
    return res.json() as Promise<BackendSkillPipeline>
  } catch {
    return null
  }
}

/**
 * Seed the deterministic MVP skill pipelines for the current student.
 * Throws an Error with the backend message on failure so callers can
 * display the real reason (table missing, auth error, etc.) instead of
 * a generic message.
 */
export async function seedMockSkillEvidencePipelines(): Promise<BackendSkillPipeline[]> {
  const res = await fetchAPI("/api/v1/student/skill-pipelines/seed-mock", {
    method: "POST",
  })
  if (!res.ok) {
    let message = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail?.message) message = body.detail.message
      else if (typeof body?.detail === "string") message = body.detail
      else if (body?.message) message = body.message
    } catch {
      // body not JSON — use status text
    }
    throw new Error(message)
  }
  return res.json() as Promise<BackendSkillPipeline[]>
}

/**
 * Recruiter-safe pipeline summary as returned by the backend /recruiter-safe endpoint.
 * Visibility rules are enforced server-side:
 * - private pipelines excluded
 * - protected pipelines returned with is_locked_for_recruiter=true and no detailed artifact content
 * - public pipelines returned with full safe payload
 */
export type RecruiterSafePipelineSummary = {
  id: string
  skill_name: string
  skill_category: string
  confidence_score: number
  support_status: "strongly_supported" | "partially_supported" | "needs_review"
  evidence_count: number
  strongest_proof: { label?: string; reason?: string } | null
  weakest_proof: { label?: string; reason?: string } | null
  missing_evidence: string[]
  next_actions: string[]
  evidence_sources: BackendEvidenceSource[]
  recruiter_summary: string
  visibility_status: "public" | "protected" | "private"
  /** True when the pipeline is protected and the recruiter has not yet received approval. */
  is_locked_for_recruiter: boolean
  artifacts: Array<{
    id: string
    source_type: string
    source_title: string
    project_name: string
    visibility: string
    confidence_score: number
    proof_reason: string
    artifact_data: Record<string, unknown>
    exact_code_url?: string | null
    full_file_url?: string | null
  }>
}

/**
 * List skill evidence pipelines that are safe for recruiter viewing.
 * Calls the backend /recruiter-safe endpoint which enforces visibility server-side:
 * private pipelines excluded, protected shown as locked, public shown in full.
 * Returns null if backend unavailable.
 */
export async function listRecruiterSkillEvidencePipelines(): Promise<RecruiterSafePipelineSummary[] | null> {
  try {
    const res = await fetchAPI("/api/v1/student/skill-pipelines/recruiter-safe")
    if (!res.ok) return null
    return res.json() as Promise<RecruiterSafePipelineSummary[]>
  } catch {
    return null
  }
}

/**
 * Persist a pipeline's visibility_status to the backend.
 * Returns the updated pipeline, or null on any error (non-throwing; UI handles gracefully).
 */
export async function updateSkillPipelineVisibility(
  pipelineId: string,
  visibility: "public" | "protected" | "private",
): Promise<BackendSkillPipeline | null> {
  try {
    const res = await fetchAPI(
      `/api/v1/student/skill-pipelines/${encodeURIComponent(pipelineId)}/visibility`,
      { method: "PATCH", body: JSON.stringify({ visibility }) },
    )
    if (!res.ok) return null
    return res.json() as Promise<BackendSkillPipeline>
  } catch {
    return null
  }
}


/**
 * Persist an artifact's visibility to the backend.
 * Returns the updated artifact, or null on any error.
 */
export async function updateSkillArtifactVisibility(
  artifactId: string,
  visibility: "public" | "protected" | "private" | "approved" | "locked" | "unavailable",
): Promise<BackendSkillArtifact | null> {
  try {
    const res = await fetchAPI(
      `/api/v1/student/skill-pipelines/artifacts/${encodeURIComponent(artifactId)}/visibility`,
      { method: "PATCH", body: JSON.stringify({ visibility }) },
    )
    if (!res.ok) return null
    return res.json() as Promise<BackendSkillArtifact>
  } catch {
    return null
  }
}

/**
 * Fetch a recruiter-safe pipeline view.
 * Strips student_id, student_summary, private artifacts, and unsafe artifact_data keys.
 * Returns null on any error.
 */
export async function getRecruiterSkillPipelineView(
  pipelineId: string,
): Promise<Record<string, unknown> | null> {
  try {
    const res = await fetchAPI(
      `/api/v1/student/skill-pipelines/${encodeURIComponent(pipelineId)}/recruiter-view`,
    )
    if (!res.ok) return null
    return res.json() as Promise<Record<string, unknown>>
  } catch {
    return null
  }
}

/**
 * Result of syncing a completed Website Proof session into the student's
 * Skill Graph (skill_evidence_pipelines / skill_evidence_artifacts).
 */
export type WebsiteProofSyncResult = {
  ok: boolean
  already_synced: boolean
  skills_synced: string[]
  pipelines_upserted: number
  artifacts_created: number
  artifact_types_created: string[]
  errors: string[]
}

/**
 * Sync a completed Website Proof session into the student's profile / Skill Graph.
 * Idempotent on the backend — safe to call multiple times for the same session.
 * Throws an Error with the backend message on failure so callers can show it.
 */
export async function syncWebsiteProofToSkillGraph(
  proofSessionId: string,
): Promise<WebsiteProofSyncResult> {
  const res = await fetchAPI(
    `/api/v1/student/skill-pipelines/from-website-proof/${encodeURIComponent(proofSessionId)}`,
    { method: "POST" },
  )
  if (!res.ok) {
    let message = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail?.message) message = body.detail.message
      else if (typeof body?.detail === "string") message = body.detail
      else if (body?.message) message = body.message
    } catch {
      // body not JSON — use status text
    }
    throw new Error(message)
  }
  return res.json() as Promise<WebsiteProofSyncResult>
}
