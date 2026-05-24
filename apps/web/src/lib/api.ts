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
  skillEvidenceId: string
): Promise<ExtensionProofSessionResponse> {
  const res = await fetchAPI("/api/v1/student/extension-proof/sessions", {
    method: "POST",
    body: JSON.stringify({ skill_evidence_id: skillEvidenceId }),
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
}

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
  progress: number
  current_stage: string
  stages: WorkflowAnalysisStage[]
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

// ── Live Website Check ────────────────────────────────────────────────────────

export type LiveWebsiteCheckConfidence = "high" | "medium" | "low" | "failed"

export type LiveCheckStageStatus = "pending" | "in_progress" | "complete" | "failed"

export type LiveWebsiteCheckStage = {
  key: string
  label: string
  status: LiveCheckStageStatus
}

export type LiveWebsiteCheckResponse = {
  id: string
  proof_session_id: string
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
