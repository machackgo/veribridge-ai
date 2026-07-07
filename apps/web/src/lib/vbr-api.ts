"use client"

import { fetchAPI } from "@/lib/api"

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"

/**
 * Client for the Verified Build Report (VBR) session recording endpoints.
 * Chunks are uploaded via a short-lived signed URL (chunk-upload-url), then
 * their metadata (storage_path, bytes, sha256) is saved via /chunk.
 */

export type VBRSessionStatus = "created" | "recording" | "uploaded" | string

export type VBRSessionQuestionResponse = {
  id: string
  session_id: string
  sort_order: number
  question_text: string
  target_ref: Record<string, unknown>
  claim_ids: string[]
  asked_at_s: number | null
  answered: boolean
  created_at: string
}

/**
 * A safe, timestamped reference into a Project Defense video transcript.
 * Never includes storage paths, signed URLs, access tokens, or full
 * transcript text — `short_summary` is a short snippet of a single
 * transcript segment.
 */
export type VideoEvidenceChip = {
  label: string
  timestamp_start_s: number
  timestamp_end_s: number
  short_summary: string
  related_skill?: string | null
  question_id?: string | null
  source: string
  source_type: string
}

export type VBRSessionResponse = {
  id: string
  project_id: string
  attempt_no: number
  status: VBRSessionStatus
  started_at: string | null
  ended_at: string | null
  duration_s: number | null
  webcam_present: boolean
  chunk_count: number
  created_at: string
  updated_at: string
  transcript_status?: string | null
  video_evidence_chips: VideoEvidenceChip[]
}

export type VBRSessionDetailResponse = VBRSessionResponse & {
  questions: VBRSessionQuestionResponse[]
}

export type VBRProjectResponse = {
  id: string
  title: string
  repo_url: string
  repo_full_name?: string | null
  deployed_url?: string | null
  head_sha?: string | null
  status: string
  created_at: string
  updated_at: string
  metadata?: Record<string, unknown>
}

export type VBRConsentResponse = {
  id: string
  user_id: string
  kind: string
  granted: boolean
  text_version: string
  created_at: string
}

export type VBRChunkUploadRequest = {
  chunk_index: number
  storage_path: string
  bytes: number
  sha256: string
}

export type VBRChunkResponse = {
  id: string
  session_id: string
  chunk_index: number
  bytes: number | null
  sha256: string | null
  received_at: string
}

export type VBRChunkUploadUrlRequest = {
  chunk_index: number
  bytes: number
  sha256: string
}

export type VBRChunkUploadUrlResponse = {
  upload_url: string
  storage_path: string
  chunk_index: number
  expires_in: number | null
}

export type VBRTelemetryResponse = {
  session_id: string
  telemetry: Record<string, unknown>
}

export type VBRRecordingReadinessResponse = {
  ready: boolean
  code: string | null
  message: string
}

export type VBRPublicReportClaim = {
  claim_text: string | null
  judgment: string | null
  rationale: string | null
  evidence_count: number
}

export type VBRPublicReportResponse = {
  project_title: string | null
  repo_full_name: string | null
  status: string
  published_at: string | null
  claim_count: number
  evidence_count: number | null
  claims: VBRPublicReportClaim[]
  methodology: string[]
  verification_note: string
}

async function parseErrorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: { message?: string } | string }
    const detail = body?.detail
    if (detail && typeof detail === "object" && typeof detail.message === "string") {
      return detail.message
    }
    if (typeof detail === "string") return detail
  } catch {
    // response body was not JSON — fall back to generic message
  }
  return fallback
}

export async function getVBRSession(sessionId: string): Promise<VBRSessionDetailResponse | null> {
  const res = await fetchAPI(`/api/v1/student/vbr/sessions/${encodeURIComponent(sessionId)}`)
  if (res.status === 404) return null
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to load session (HTTP ${res.status}).`))
  return res.json()
}

export async function getVBRProject(projectId: string): Promise<VBRProjectResponse | null> {
  const res = await fetchAPI(`/api/v1/student/vbr/projects/${encodeURIComponent(projectId)}`)
  if (res.status === 404) return null
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to load project (HTTP ${res.status}).`))
  return res.json()
}

/** List the current user's Verified Build Report projects. */
export async function listVBRProjects(): Promise<VBRProjectResponse[]> {
  const res = await fetchAPI("/api/v1/student/vbr/projects")
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to load projects (HTTP ${res.status}).`))
  return res.json()
}

export type VBRProjectQuestionsResponse = {
  project_id: string
  session_id: string | null
  questions: VBRSessionQuestionResponse[]
}

/** Get the latest verification session (if any) for a VBR project. */
export async function getVBRProjectQuestions(projectId: string): Promise<VBRProjectQuestionsResponse> {
  const res = await fetchAPI(`/api/v1/student/vbr/projects/${encodeURIComponent(projectId)}/questions`)
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to load project session (HTTP ${res.status}).`))
  return res.json()
}

export async function createVBRSessionConsent(
  sessionId: string,
  textVersion: string = "recording_v1"
): Promise<VBRConsentResponse> {
  const res = await fetchAPI(`/api/v1/student/vbr/sessions/${encodeURIComponent(sessionId)}/consent`, {
    method: "POST",
    body: JSON.stringify({ text_version: textVersion }),
  })
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to record consent (HTTP ${res.status}).`))
  return res.json()
}

export async function startVBRSession(sessionId: string): Promise<VBRSessionResponse> {
  const res = await fetchAPI(`/api/v1/student/vbr/sessions/${encodeURIComponent(sessionId)}/start`, {
    method: "POST",
  })
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to start session (HTTP ${res.status}).`))
  return res.json()
}

/** Check whether recording upload storage is ready before requesting media permissions. */
export async function getVBRSessionRecordingReadiness(sessionId: string): Promise<VBRRecordingReadinessResponse> {
  const res = await fetchAPI(`/api/v1/student/vbr/sessions/${encodeURIComponent(sessionId)}/recording-readiness`)
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to check recording readiness (HTTP ${res.status}).`))
  return res.json()
}

/** Reset a stuck, zero-chunk "recording" session back to a retryable state. */
export async function cancelVBRSessionRecording(sessionId: string): Promise<VBRSessionResponse> {
  const res = await fetchAPI(`/api/v1/student/vbr/sessions/${encodeURIComponent(sessionId)}/cancel-recording`, {
    method: "POST",
  })
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to reset the recording session (HTTP ${res.status}).`))
  return res.json()
}

export async function requestVBRChunkUploadUrl(
  sessionId: string,
  payload: VBRChunkUploadUrlRequest
): Promise<VBRChunkUploadUrlResponse> {
  const res = await fetchAPI(`/api/v1/student/vbr/sessions/${encodeURIComponent(sessionId)}/chunk-upload-url`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to request an upload URL (HTTP ${res.status}).`))
  return res.json()
}

export async function uploadVBRChunkBytes(uploadUrl: string, blob: Blob): Promise<void> {
  const res = await fetch(uploadUrl, {
    method: "PUT",
    headers: {
      "Content-Type": blob.type || "video/webm",
      "x-upsert": "true",
      apikey: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "",
    },
    body: blob,
  })
  if (!res.ok) throw new Error(`Failed to upload chunk bytes (HTTP ${res.status}).`)
}

export async function uploadVBRSessionChunk(
  sessionId: string,
  payload: VBRChunkUploadRequest
): Promise<VBRChunkResponse> {
  const res = await fetchAPI(`/api/v1/student/vbr/sessions/${encodeURIComponent(sessionId)}/chunk`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to save chunk metadata (HTTP ${res.status}).`))
  return res.json()
}

export async function updateVBRSessionTelemetry(
  sessionId: string,
  telemetry: Record<string, unknown>,
  merge: boolean = true
): Promise<VBRTelemetryResponse> {
  const res = await fetchAPI(`/api/v1/student/vbr/sessions/${encodeURIComponent(sessionId)}/telemetry`, {
    method: "POST",
    body: JSON.stringify({ telemetry, merge }),
  })
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to record telemetry (HTTP ${res.status}).`))
  return res.json()
}

export async function finalizeVBRSession(
  sessionId: string,
  durationS?: number | null
): Promise<VBRSessionResponse> {
  const res = await fetchAPI(`/api/v1/student/vbr/sessions/${encodeURIComponent(sessionId)}/finalize`, {
    method: "POST",
    body: JSON.stringify({ duration_s: durationS ?? null }),
  })
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to finalize session (HTTP ${res.status}).`))
  return res.json()
}

export type VBRMediaProcessingResponse = {
  session_id: string
  status: string
  chunk_count: number
  total_bytes: number
  full_video_bytes: number
  full_video_sha256: string
  next_steps: string[]
  message: string
}

/** Run media processing (concatenation) for a finalized ("uploaded") session. */
export async function processVBRSession(sessionId: string): Promise<VBRMediaProcessingResponse> {
  const res = await fetchAPI(`/api/v1/student/vbr/sessions/${encodeURIComponent(sessionId)}/process`, {
    method: "POST",
  })
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to process recording (HTTP ${res.status}).`))
  return res.json()
}

export type VBRTranscriptionResponse = {
  session_id: string
  status: string
  transcript_id: string | null
  segment_count: number
  duration_s: number | null
  provider: string | null
  configured: boolean
  message: string
}

/** Generate a timestamped transcript for a processed session. */
export async function transcribeVBRSession(sessionId: string): Promise<VBRTranscriptionResponse> {
  const res = await fetchAPI(`/api/v1/student/vbr/sessions/${encodeURIComponent(sessionId)}/transcribe`, {
    method: "POST",
  })
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to generate transcript (HTTP ${res.status}).`))
  return res.json()
}

export type VBRTranscriptSegment = {
  start_s: number
  end_s: number
  text: string
}

/**
 * Owner-only private transcript preview. Served to the student who owns the
 * session so the recorder/workspace page can render their generated transcript.
 * Never exposed on the public recruiter report (sanitized separately).
 */
export type VBRSessionTranscriptResponse = {
  session_id: string
  status: string
  transcript_id: string | null
  provider: string | null
  language: string | null
  segment_count: number
  duration_s: number | null
  preview_text: string
  truncated: boolean
  segments: VBRTranscriptSegment[]
}

/** Fetch the owner's private transcript preview for a session. */
export async function getVBRSessionTranscript(
  sessionId: string
): Promise<VBRSessionTranscriptResponse> {
  const res = await fetchAPI(`/api/v1/student/vbr/sessions/${encodeURIComponent(sessionId)}/transcript`)
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to load transcript (HTTP ${res.status}).`))
  return res.json()
}

// ─── Project Defense (Phase 1 — individual project defense) ────────────────

export type ProjectDefenseAttachedProofsRequest = {
  github_proof_id?: string | null
  website_proof_session_ids?: string[]
  document_evidence_ids?: string[]
  skill_pipeline_ids?: string[]
  repo_url?: string | null
}

export type ProjectDefenseCreateRequest = {
  title: string
  description?: string
  claimed_skills?: string[]
  student_role?: string
  repo_url?: string | null
  attached_proofs?: ProjectDefenseAttachedProofsRequest
}

export type ProjectDefenseMetadataResponse = {
  description: string
  claimed_skills: string[]
  student_role: string
  individual_project_only: boolean
  attached_proofs: Record<string, unknown>
  phase: string
}

export type ProjectDefenseCreateResponse = {
  project: VBRProjectResponse
  metadata: ProjectDefenseMetadataResponse
}

export type GenerateDefenseQuestionsResponse = {
  project_id: string
  session_id: string
  status: string
  questions: VBRSessionQuestionResponse[]
}

export type DefenseAnswerItem = {
  question_id?: string | null
  answer_text?: string
}

export type SubmitDefenseAnswersRequest = {
  answers?: DefenseAnswerItem[]
  combined_text?: string | null
}

export type DefenseAnalysisResponse = {
  transcript_summary: string
  skills_mentioned: string[]
  skills_explained_well: string[]
  skills_missing_from_explanation: string[]
  consistency_with_evidence_score: number
  explanation_clarity_score: number
  ownership_signal_score: number
  technical_depth_score: number
  overall_defense_score: number
  risk_flags: string[]
  recruiter_summary: string
  recommended_improvements: string[]
  privacy_scan_status: string
}

export type SubmitDefenseAnswersResponse = {
  project_id: string
  session_id: string
  transcript_id: string
  segment_count: number
  answered_question_count: number
  analysis: DefenseAnalysisResponse
  video_evidence_chips: VideoEvidenceChip[]
}

/**
 * Result of syncing analyzed Project Defense evidence into the student's
 * Skill Graph (skill_evidence_pipelines / skill_evidence_artifacts).
 */
export type ProjectDefenseSyncResult = {
  ok: boolean
  already_synced: boolean
  skills_synced: string[]
  pipelines_upserted: number
  artifacts_created: number
  errors: string[]
}

// ─── Project-first defense flow (defend an existing project) ────────────────
//
// Project Defense is a defense layer on top of an existing project, not a
// fourth standalone proof form. These responses expose only safe, already-
// derived summaries — never raw proof payloads, storage paths, or scores.

export type DefenseStatus = "not_started" | "in_progress" | "completed"

export type DefenseEvidenceTypeSummary = {
  attached: boolean
  count: number
  /** Safe display label only (repo full name / doc titles / website URLs). */
  label: string
}

export type ProjectDefenseEvidenceSummary = {
  github_proof: DefenseEvidenceTypeSummary
  documents: DefenseEvidenceTypeSummary
  website_proof: DefenseEvidenceTypeSummary
  project_defense: DefenseEvidenceTypeSummary
}

export type EligibleProjectResponse = {
  id: string
  title: string
  description: string
  claimed_skills: string[]
  repo_full_name: string | null
  defense_status: DefenseStatus
  report_ready: boolean
  evidence: ProjectDefenseEvidenceSummary
  created_at: string
  updated_at: string
}

export type EligibleProjectsResponse = {
  projects: EligibleProjectResponse[]
}

export type ProjectDefenseContextResponse = {
  project: VBRProjectResponse
  metadata: ProjectDefenseMetadataResponse
  evidence: ProjectDefenseEvidenceSummary
  defense_status: DefenseStatus
  report_ready: boolean
  session_id: string | null
  questions: VBRSessionQuestionResponse[]
}

export type AttachProofsResponse = {
  project: VBRProjectResponse
  metadata: ProjectDefenseMetadataResponse
  evidence: ProjectDefenseEvidenceSummary
}

/** List the current user's projects that can be defended. */
export async function listEligibleDefenseProjects(): Promise<EligibleProjectResponse[]> {
  const res = await fetchAPI("/api/v1/student/vbr/project-defense/eligible-projects")
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to load projects (HTTP ${res.status}).`))
  const data: EligibleProjectsResponse = await res.json()
  return data.projects
}

/** Fetch the defense context (evidence + status + any in-progress session) for a project. */
export async function getProjectDefenseContext(projectId: string): Promise<ProjectDefenseContextResponse> {
  const res = await fetchAPI(
    `/api/v1/student/vbr/project-defense/projects/${encodeURIComponent(projectId)}/context`
  )
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to load project defense context (HTTP ${res.status}).`))
  return res.json()
}

/** Attach existing owned proofs to a selected project. */
export async function attachProjectDefenseProofs(
  projectId: string,
  body: ProjectDefenseAttachedProofsRequest
): Promise<AttachProofsResponse> {
  const res = await fetchAPI(
    `/api/v1/student/vbr/project-defense/projects/${encodeURIComponent(projectId)}/attach-proofs`,
    { method: "POST", body: JSON.stringify(body) }
  )
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to attach proofs (HTTP ${res.status}).`))
  return res.json()
}

/** Create an individual Project Defense identity and attach existing proof sources. */
export async function createProjectDefense(
  body: ProjectDefenseCreateRequest
): Promise<ProjectDefenseCreateResponse> {
  const res = await fetchAPI("/api/v1/student/vbr/project-defense", {
    method: "POST",
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to create project defense (HTTP ${res.status}).`))
  return res.json()
}

/** Generate deterministic defense questions for a Project Defense project. */
export async function generateDefenseQuestions(projectId: string): Promise<GenerateDefenseQuestionsResponse> {
  const res = await fetchAPI(
    `/api/v1/student/vbr/projects/${encodeURIComponent(projectId)}/generate-defense-questions`,
    { method: "POST" }
  )
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to generate defense questions (HTTP ${res.status}).`))
  return res.json()
}

/**
 * Create a *fresh* Project Defense recording session (new attempt) for a project.
 * Used by "Record another defense" — a completed/processed session is
 * non-retryable, so this always returns a brand-new session id to record into.
 */
export async function createNewDefenseSession(projectId: string): Promise<GenerateDefenseQuestionsResponse> {
  const res = await fetchAPI(
    `/api/v1/student/vbr/projects/${encodeURIComponent(projectId)}/defense-sessions`,
    { method: "POST" }
  )
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to start a new defense session (HTTP ${res.status}).`))
  return res.json()
}

/** Submit pasted/manual defense answers and run deterministic analysis. */
export async function submitDefenseAnswers(
  sessionId: string,
  body: SubmitDefenseAnswersRequest
): Promise<SubmitDefenseAnswersResponse> {
  const res = await fetchAPI(`/api/v1/student/vbr/sessions/${encodeURIComponent(sessionId)}/submit-defense`, {
    method: "POST",
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to submit defense answers (HTTP ${res.status}).`))
  return res.json()
}

/**
 * Sync analyzed Project Defense evidence into the student's Skill Graph.
 * Idempotent on the backend — safe to call multiple times for the same session.
 */
export async function syncProjectDefenseToSkillGraph(sessionId: string): Promise<ProjectDefenseSyncResult> {
  const res = await fetchAPI(`/api/v1/student/skill-pipelines/from-project-defense/${encodeURIComponent(sessionId)}`, {
    method: "POST",
  })
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to save to Skill Graph (HTTP ${res.status}).`))
  return res.json()
}

// ─── Final VBR Report v1 (student preview) ──────────────────────────────────

export type VBRReportGitHubProofSummary = {
  repo_url: string | null
  repo_owner: string | null
  repo_name: string | null
  status: string | null
  detected_skills: string[]
  public_safe_summary: string
  /** True only when the repo is a known public GitHub repo (safe to link). */
  repo_is_public?: boolean
}

export type VBRReportDocumentSummary = {
  title: string
  source_type: string | null
  status: string | null
}

export type VBRReportWebsiteProofSummary = {
  target_website: string
  evidence_strength: string
  workflow_confidence: string
  supported_skills: string[]
}

/**
 * How one attached Website Proof's observed behaviour relates to ONE of the
 * project's claimed skills. Every field is a closed backend vocabulary label —
 * never a numeric score, never proof strength. `is_direct_evidence` is true only
 * for the families allowed to read as DIRECT skill evidence (interactive
 * frontend UI, rendered data-visualisation); ML / GenAI / DevOps skills always
 * read as product-behaviour / availability context, never implementation proof.
 */
export type WebsiteProofSkillRelevance = {
  skill_name: string
  relevance_key: string
  relevance_label: string
  relevance_summary: string
  limitation: string
  is_direct_evidence: boolean
}

/**
 * Skill-specific Website Behavior Evidence for ONE attached Website Proof —
 * owner/private project report only (never on the public projection). Empty
 * `skills` with `skill_mapping_available === false` means the proof is captured
 * but not yet mapped to a specific skill; the gap is stated, never faked.
 */
export type WebsiteProofSkillEvidence = {
  target_website: string
  behavior_claim: string
  website_purpose_key: string
  website_purpose_label: string
  website_purpose_summary: string
  skills: WebsiteProofSkillRelevance[]
  skill_mapping_available: boolean
}

export type VBRReportEvidencePackageSummary = {
  github_proof_attached: boolean
  documents_count: number
  website_proofs_count: number
  project_defense_completed: boolean
  video_defense_recorded: boolean
  video_evidence_chip_count: number
}

export type VBRReportQuestionSummary = {
  id: string
  question_text: string
  kind: string | null
  skill: string | null
  answered: boolean
}

/**
 * A single recruiter-safe claim→evidence trace. Ties one concrete evidence
 * source (repo, document, website proof, defense answer, video chip) to the
 * skills it supports, with a safe explanation, an in-page anchor, and — only
 * when the target is genuinely public — a directly-openable link. Never carries
 * raw evidence, storage paths, signed URLs, media URLs, tokens, or scores.
 */
export type EvidenceTrace = {
  trace_id: string
  source_type: "GitHub Proof" | "Document Proof" | "Website Proof" | "Project Defense" | "Video Evidence" | string
  source_title: string
  skill_names: string[]
  qualitative_status: string
  safe_summary: string
  safe_detail: string
  evidence_anchor: string
  /** Coarse machine label for where inside the source this trace points. */
  location_type?: string | null
  /** Short human label for the location (e.g. "repo-level", "Q3", "Live URL", "Video 02:14"). */
  location_label?: string | null
  /** Slightly longer safe locator detail; redacted for documents on public surfaces. */
  location_detail?: string | null
  /** Deterministic Project Defense question text (never the answer transcript). */
  question_text?: string | null
  /** Short safe excerpt of the candidate's own answer; absent on public surfaces. */
  answer_excerpt?: string | null
  /** Document page locator, when one was recorded. */
  page_number?: number | null
  /** Short safe document snippet; absent on public surfaces. */
  snippet?: string | null
  /** Safe document citation (matched section heading); kept on public surfaces. */
  citation?: string | null
  /** Safe repository-relative file path, for file-level GitHub traces. */
  file_path?: string | null
  /** Start line for line-level GitHub code evidence, when recorded. */
  line_start?: number | null
  /** End line for line-level GitHub code evidence, when recorded. */
  line_end?: number | null
  /** Matched function name for GitHub code evidence, when recorded. */
  function_name?: string | null
  /** Commit SHA the analyzer pinned GitHub evidence to; safe on public surfaces. */
  commit_sha?: string | null
  /** Safe code snippet from a public GitHub file; absent on public surfaces. */
  code_snippet?: string | null
  public_url?: string | null
  public_url_label?: string | null
  timestamp?: string | null
  /** Human timestamp label for video traces (e.g. "02:14"). */
  timestamp_label?: string | null
  limitation: string
  is_publicly_openable: boolean
  private_evidence_note?: string | null
}

/**
 * A precise, recruiter-readable label for a skill-matrix trace link, derived
 * from the trace's proof-native location (e.g. "GitHub: repo-level",
 * "Defense Q3", "Video 02:14", "Website: Live URL"). Falls back to the bare
 * source type when no location label is present. Keeps the short matrix-link
 * style ("matrixTraceLabel") while using the recovered location fields.
 */
export function matrixTraceLabel(trace: EvidenceTrace): string {
  const loc = (trace.location_label ?? "").trim()
  switch (trace.source_type) {
    case "GitHub Proof":
      // "GitHub: lines 24-38" / "GitHub: function classify_image" / "GitHub:
      // src/main.py" / "GitHub: repo-level" — whatever the deepest recorded
      // locator was, falling back to the bare source type.
      return loc ? `GitHub: ${loc}` : "GitHub Proof"
    case "Document Proof":
      // "Doc: Page 2" / "Doc: Citation" / "Doc: Snippet" when a precise locator
      // exists; otherwise a plain "Document".
      if (typeof trace.page_number === "number") return `Doc: Page ${trace.page_number}`
      if (loc === "matched skill" || loc === "project context" || loc === "") return "Document"
      return `Doc: ${loc}`
    case "Website Proof":
      return loc ? `Website: ${loc}` : "Website Proof"
    case "Project Defense":
      // Q-located answers read "Defense Q3"; the overview reads "Defense".
      return /^Q\d+$/.test(loc) ? `Defense ${loc}` : "Defense"
    case "Video Evidence":
      return trace.timestamp_label ? `Video ${trace.timestamp_label}` : loc || "Video Evidence"
    default:
      return loc || trace.source_type
  }
}

/**
 * One safe, student-owned proof from the Student Proof Vault. Normalized from
 * any proof source (GitHub / Document / Website / Project Defense / Video /
 * Skill Graph), attached to a VBR project or standalone. Never carries raw
 * transcripts/docs/snapshots, storage paths, signed URLs, or numeric scores.
 */
export type VaultProofItem = {
  /** Null when the proof is project-level context not mapped to a single skill. */
  skill_name: string | null
  proof_type: "GitHub Proof" | "Document Proof" | "Website Proof" | "Project Defense" | "Video Evidence" | "Skill Graph" | string
  source_id: string
  source_table: string
  /** Owner-only: the primary VBR project this proof is attached to, if any. */
  project_id: string | null
  attached_project_ids: string[]
  title: string
  source_label: string
  safe_summary: string
  safe_snippet?: string | null
  safe_location?: string | null
  public_safe: boolean
  visibility: string
  limitation: string
  is_attached_to_project: boolean
  // Safe structured locators (populated cheaply at collection — no hydration).
  file_path?: string | null
  line_start?: number | null
  line_end?: number | null
  function_name?: string | null
  commit_sha?: string | null
  public_url?: string | null
  // Explicit GitHub display-mode fields (only set for GitHub proofs).
  display_mode?: "code_line" | "repo_level" | "limitation" | string | null
  evidence_strength?: string | null
  evidence_kind?: string | null
  has_precise_line_evidence?: boolean | null
  github_line_url?: string | null
  repo_url?: string | null
  page_number?: number | null
  section_label?: string | null
  citation?: string | null
  question_text?: string | null
  answer_excerpt?: string | null
  timestamp_label?: string | null
}

/** Student-vault proofs grouped under one skill (attached + unattached). */
export type VaultSkillGroup = {
  skill: string
  proofs: VaultProofItem[]
  proof_types: string[]
  attached_count: number
  unattached_count: number
  has_unattached: boolean
}

// ── Student Proof Vault — Layer 1 (compact skill summary) ───────────────────

/** A compact, safe preview of one vault proof, for the main Passport card. */
export type VaultSkillPreview = {
  proof_type: string
  title: string
  safe_location?: string | null
  safe_summary: string
  is_attached_to_project: boolean
  public_safe: boolean
}

/**
 * Layer 1 — one compact skill card for the main Work Passport dashboard.
 * Carries counts + a few representative previews only — NOT every proof. The
 * full evidence is loaded lazily via the Skill Report endpoint.
 */
export type VaultSkillSummary = {
  skill: string
  /** Stable, URL-safe slug — the Skill Report route key. */
  skill_slug?: string
  category: string
  status: string
  source_labels: string[]
  project_ids: string[]
  project_titles: string[]
  project_count: number
  proof_source_counts: Record<string, number>
  proof_count: number
  attached_count: number
  unattached_count: number
  has_unattached: boolean
  summary: string
  previews: VaultSkillPreview[]
  more_count: number
  limitations: string[]
  /** Owner-only "strengthen this skill" sentences (Proof Attachment
   *  Intelligence). Qualitative only; may be absent on older payloads. */
  strengthening_actions?: string[]
}

// ── Student Proof Vault — Layer 2 (full Skill Report) ───────────────────────

/** One rich, recruiter-verifiable evidence item inside a Skill Report section. */
export type SkillReportEvidenceItem = {
  proof_type: string
  source_id: string
  title: string
  safe_summary: string
  safe_location?: string | null
  safe_snippet?: string | null
  public_safe: boolean
  is_attached_to_project: boolean
  attached_project_ids: string[]
  project_titles: string[]
  limitation: string
  file_path?: string | null
  line_start?: number | null
  line_end?: number | null
  function_name?: string | null
  commit_sha?: string | null
  public_url?: string | null
  // Explicit GitHub display-mode fields. ``display_mode`` drives whether a card
  // renders as precise "View code lines" or honest repo-level "View repository".
  display_mode?: "code_line" | "repo_level" | "limitation" | string | null
  evidence_strength?: string | null
  evidence_kind?: string | null
  /**
   * Deterministic quality band (implementation_body / supporting_logic /
   * config_or_constant / comment_or_docstring / import_only / route_decorator_only
   * / repo_level_fallback). Only implementation_body / supporting_logic are strong;
   * everything else is a weak repository-level signal and must never render as
   * precise "Precise code evidence".
   */
  evidence_quality_grade?: string | null
  /**
   * Conservative DESCRIPTIVE code role, resolved server-side against the
   * validated grade: key ("documentation_header" / "imports_setup" /
   * "model_training" / …) + recruiter-readable label ("Documentation / usage
   * header"). Says what the block appears to be — never proof strength.
   */
  code_role_key?: string | null
  code_role_label?: string | null
  /**
   * Block-level PURPOSE (finer than the role): what THIS exact block appears to
   * do, from a closed safe vocabulary ("Documentation describing retraining
   * pipeline", "Imports / dependency setup"), plus one short helper sentence.
   * Descriptive only — never proof strength; weak rows stay under Needs review.
   */
  code_block_purpose_key?: string | null
  code_block_purpose_label?: string | null
  code_block_purpose_summary?: string | null
  /**
   * SKILL RELEVANCE: how this block relates to the report's selected skill
   * ("Direct Machine Learning implementation evidence", "Product UI context,
   * not Machine Learning implementation"), from a closed template vocabulary.
   * Descriptive only — never proof strength; weak rows stay under Needs review.
   */
  skill_relevance_key?: string | null
  skill_relevance_label?: string | null
  skill_relevance_summary?: string | null
  has_precise_line_evidence?: boolean | null
  github_line_url?: string | null
  repo_url?: string | null
  // Canonical (old GitHub Profile & Proof engine) fields — precise
  // selection_reason ("API endpoint decorator") + optional subskill / graph node.
  selection_reason?: string | null
  subskill_name?: string | null
  skill_graph_node?: string | null
  page_number?: number | null
  section_label?: string | null
  citation?: string | null
  question_text?: string | null
  answer_excerpt?: string | null
  timestamp_label?: string | null
  workflow_summary?: string | null
  workflow_steps: string[]
  dom_summary?: string | null
  ocr_summary?: string | null
  visual_summary?: string | null
  live_check?: Record<string, unknown> | null
  /**
   * Website PURPOSE: what the recorded page/app demonstrably showed
   * ("Chat / prompt interface", "Prediction / result display", "Interactive
   * form flow", …), from a closed backend vocabulary derived only from
   * already-safe summaries — never raw DOM/OCR/provider text.
   */
  website_purpose_key?: string | null
  website_purpose_label?: string | null
  website_purpose_summary?: string | null
  /**
   * Website SKILL RELEVANCE: how the observed behaviour relates to the report's
   * selected skill, recomputed server-side per report ("Direct React evidence",
   * "Machine Learning product behaviour context — not implementation proof",
   * "Deployed application availability evidence"). Closed template vocabulary;
   * descriptive only — never proof strength.
   */
  website_skill_relevance_key?: string | null
  website_skill_relevance_label?: string | null
  website_skill_relevance_summary?: string | null
  /**
   * ONE structured, recruiter-inspectable Website Evidence Card — the Website
   * counterpart of GitHub's "View code lines" row. Built server-side from
   * closed vocabularies + already-safe summaries; never raw DOM/OCR/frame/
   * provider payloads, storage paths, or signed URLs.
   */
  website_evidence_card?: WebsiteEvidenceCard | null
}

/**
 * A recruiter-verifiable Website Proof evidence card. Every field is a closed
 * backend vocabulary label, an already-sanitized summary, or a revalidated safe
 * public URL. OCR/DOM/visual evidence appears only as derived closed-template
 * sentences. `screenshot_preview_url` is always null in the MVP — keyframes
 * stay in private storage behind the candidate-permission thumbnail proxy, so
 * the UI renders `screenshot_access_label` instead.
 */
export type WebsiteEvidenceCard = {
  card_key: string
  route_or_page: string
  page_title?: string | null
  /** Date-only (YYYY-MM-DD) observation date. */
  observed_at?: string | null
  /**
   * Recruiter-first behaviour claim (closed backend vocabulary keyed by
   * purpose) — the first line the card renders: what live behaviour was
   * demonstrably shown, phrased as a checkable statement.
   */
  behavior_claim?: string | null
  website_purpose_key: string
  website_purpose_label: string
  website_purpose_summary: string
  skill_relevance_key: string
  skill_relevance_label: string
  skill_relevance_summary: string
  observed_behavior_summary?: string | null
  visual_evidence_summary?: string | null
  ocr_evidence_summary_safe?: string | null
  dom_evidence_summary_safe?: string | null
  evidence_basis_chips: string[]
  limitation: string
  open_website_url?: string | null
  screenshot_available: boolean
  /** "private_candidate_permission_required" | "unavailable" (closed enum). */
  screenshot_access_label: string
  screenshot_preview_url?: string | null
  /**
   * Cross-proof corroboration — set server-side ONLY when this website proof
   * sits inside a confirmed VBR project chain holding the companion source.
   * `corroboration_note` is a closed-fragment sentence naming those companions;
   * `connected_project_title` is the already-safe project title.
   */
  corroborates_github?: boolean
  corroborates_defense?: boolean
  corroborates_document?: boolean
  corroboration_note?: string | null
  connected_project_title?: string | null
}

export type SkillReportProjectUsage = {
  project_id: string | null
  project_title: string
  attached: boolean
  sources: string[]
}

/**
 * A document shown as connected *corroboration* — never a standalone dump. It
 * answers "what does this document corroborate?" with one safe citation.
 */
export type SkillReportDocumentCorrelation = {
  source_id: string
  document_title: string
  page_number?: number | null
  section_label?: string | null
  citation?: string | null
  /** Safe figure/diagram/table reference label (e.g. "Figure 3") — never the raw figure. */
  figure_reference?: string | null
  safe_snippet?: string | null
  /** "GitHub implementation" / "Website workflow behavior" / "Skill explanation" / "Project architecture". */
  corroborates: string
  /** "direct attachment" / "title/project match" / "skill-only match" / "weak/standalone". */
  correlation_confidence?: string
  /** Always "Supporting evidence" — a document corroborates, it is never primary proof. */
  support_label?: string
  reason: string
  /** Why this page/section supports the skill (safe analyzer reason, with a deterministic fallback). */
  why_supported?: string
  /** True only when the student explicitly allowed full-document recruiter download. */
  full_document_available?: boolean
  /** Safe download gating message — never a storage path or signed URL. */
  document_access_note?: string
  limitation: string
}

/** One evidence-cited synthesis statement (Proof Synthesis Agent). */
export type SkillProofSynthesisStatement = {
  text: string
  source: string
  /** The real evidence ids this statement was built from (never fabricated). */
  evidence_ids: string[]
}

/** One project's connected proof chain for a skill — artifacts + corroboration. */
export type SkillReportProjectChain = {
  project_id: string | null
  project_title: string
  attached: boolean
  attached_status: string
  sources: string[]
  evidence_chain_summary: string
  github_evidence: SkillReportEvidenceItem[]
  /**
   * This chain's GitHub implementation evidence grouped by canonical owner/repo —
   * the same compact grouped projection used for standalone GitHub. May be absent
   * on older payloads; fall back to `github_evidence`.
   */
  github_groups?: SkillReportStandaloneGitHubGroup[]
  website_evidence: SkillReportEvidenceItem[]
  document_correlations: SkillReportDocumentCorrelation[]
  document_more_count: number
  defense_evidence: SkillReportEvidenceItem[]
  video_evidence: SkillReportEvidenceItem[]
  /**
   * One safe sentence explaining how this chain's Website Proof corroborates its
   * other sources ("the website demonstrates the behaviour, GitHub code shows the
   * implementation, …"). Null when the chain has no website evidence or nothing
   * to connect it to.
   */
  website_connection_note?: string | null
  /** Project Defense + Video evidence collapsed into ONE grouped section (no repeated cards). */
  defense_group?: SkillReportDefenseGroup | null
  limitations: string[]
  /** >1 when duplicate VBR project rows sharing the same proof package were collapsed. */
  collapsed_project_count?: number
  collapsed_project_ids?: string[]
  /** >1 when several same-title VBR attempts (different proof combos) were grouped into one chain. */
  grouped_attempt_count?: number
  grouped_project_ids?: string[]
  // ── Proof Synthesis Agent fields (qualitative — never a numeric score) ──────
  /** "Strongly corroborated" / "Corroborated" / "Supporting evidence" / "Needs review" / "Insufficient evidence". */
  confidence_tier?: string
  synthesis_result?: string
  why_linked?: string
  subskills?: string[]
  synthesis_statements?: SkillProofSynthesisStatement[]
  /** Step 2: this chain's evidence collapsed into the uniform normalized model. */
  normalized_evidence?: SkillReportNormalizedArtifact[]
}

/** One cited Project Defense / video moment inside the grouped defense section. */
export type SkillReportDefenseMoment = {
  label: string
  timestamp_label?: string | null
  question_text?: string | null
  short_summary: string
  source_id: string
}

/** All Project Defense + Video evidence for one chain, grouped into one section. */
export type SkillReportDefenseGroup = {
  explanation: string
  moments: SkillReportDefenseMoment[]
  grouped_count: number
  limitation: string
  source_ids: string[]
}

/** A standalone proof that links to no chain — shown under unlinked support. */
export type SkillProofSynthesisUnlinkedItem = {
  proof_type: string
  source_id: string
  title: string
  safe_summary: string
  safe_location?: string | null
  corroborates: string
  limitation: string
}

/** Capped bucket of proofs that support the skill but join no proof chain. */
export type SkillProofSynthesisUnlinked = {
  items: SkillProofSynthesisUnlinkedItem[]
  count: number
  more_count: number
}

/**
 * One proof normalized into the Evidence Normalization Engine's uniform shape
 * (Step 2). Only the already-safe fields are surfaced — never raw payloads,
 * storage paths, signed URLs or the internal ``metadata`` bag.
 */
export type SkillReportNormalizedArtifact = {
  /** Safe ``ev_…`` evidence id a synthesis claim can cite. */
  evidence_id: string
  source_type: string
  source_label?: string
  /** Public-safe location (e.g. "file.py · lines 10-20", "demo.example.com"). */
  exact_location?: string | null
  safe_summary?: string
  /** Qualitative — never a numeric score. */
  proof_strength?: string
  subskill_name?: string | null
  skill_name?: string | null
  canonical_skill_name?: string | null
  project_title?: string | null
}

/**
 * Qualitative (never numeric) summary of a linked chain's proof strengths, as
 * emitted by the backend's ``_strength_summary``. Mixed value types: a label
 * string, the sorted list of strengths present, boolean capability flags, and a
 * single corroborating-document count. Never a score or ranking.
 */
export type SkillReportProofStrengthSummary = {
  /** Qualitative label, e.g. "Implementation proven by precise code". */
  label?: string
  /** Sorted qualitative strength tokens present across the chain. */
  strengths_present?: string[]
  has_precise_code?: boolean
  has_runtime_behavior?: boolean
  has_self_explanation?: boolean
  has_supporting_moment?: boolean
  repo_level_only?: boolean
  /** Count of corroborating documents — never a primary-proof score. */
  corroborating_document_count?: number
}

/**
 * One deterministically linked proof chain across normalized evidence (Step 3):
 * the safe ``ev_…`` ids, the source types present, why the sources connect, and
 * the safe member artifacts a synthesis claim cites.
 */
export type SkillReportLinkedChain = {
  chain_id: string
  project_title?: string
  canonical_skill_name?: string | null
  chain_label?: string
  linked_evidence_ids: string[]
  source_types_present: string[]
  primary_source_type?: string
  connection_reasons: string[]
  proof_strength_summary?: SkillReportProofStrengthSummary
  limitations: string[]
  public_safe: boolean
  evidence: SkillReportNormalizedArtifact[]
}

/**
 * One recruiter-readable synthesis claim (Step 4 — LLM Synthesis Layer). Every
 * claim cites real ``ev_…`` ids (never invented); its ``qualitative_tier`` is a
 * label, never a numeric score.
 */
export type SkillSynthesisClaim = {
  claim_id: string
  claim: string
  supporting_evidence_ids: string[]
  why_connected: string
  limitations: string[]
  qualitative_tier: string
  public_safe: boolean
}

/** The synthesis for ONE linked proof chain (Step 4). */
export type SkillSynthesisResult = {
  chain_id: string
  skill_name?: string | null
  canonical_skill_name?: string | null
  project_title?: string | null
  claims: SkillSynthesisClaim[]
  overall_summary: string
  limitations: string[]
  public_safe: boolean
  /** Provenance only: "llm" | "deterministic" — never a score. */
  source?: string
}

/** Proofs supporting a skill that are not attached to any VBR project. */
/** One compact code-location row inside a standalone GitHub repository group. */
export type SkillReportStandaloneGitHubRow = {
  source_id: string
  /** Compact "file · lines / function()" label (e.g. "Tree.py · lines 13-72"). */
  label: string
  file_path?: string | null
  line_start?: number | null
  line_end?: number | null
  function_name?: string | null
  display_mode?: string | null
  /**
   * Deterministic quality band (implementation_body / supporting_logic /
   * config_or_constant / comment_or_docstring / import_only / route_decorator_only
   * / repo_level_fallback). The backend already ranks strong rows first and pushes
   * weak rows past `row_more_count`; this is exposed so the UI can label/skip weak
   * rows rather than render them like real implementation code.
   */
  evidence_quality_grade?: string | null
  /**
   * Conservative DESCRIPTIVE code role for this block, resolved server-side
   * against the validated grade: key ("documentation_header" / "imports_setup" /
   * "model_training" / …) + recruiter-readable label ("Documentation / usage
   * header"). Weak rows render this instead of the raw `selection_reason`; it is
   * a label only and never promotes a row out of Needs review.
   */
  code_role_key?: string | null
  code_role_label?: string | null
  /**
   * Block-level PURPOSE for this exact row (closed safe vocabulary + one short
   * helper sentence). Preferred over `code_role_label` on weak rows; it is a
   * label only and never promotes a row out of Needs review.
   */
  code_block_purpose_key?: string | null
  code_block_purpose_label?: string | null
  code_block_purpose_summary?: string | null
  /**
   * SKILL RELEVANCE for this row relative to the report's skill (closed template
   * vocabulary + one short helper sentence). Descriptive only; it never promotes
   * a weak row out of Needs review.
   */
  skill_relevance_key?: string | null
  skill_relevance_label?: string | null
  skill_relevance_summary?: string | null
  /** Precise "why selected" reason ("ML training call"), when the analyzer set it. */
  selection_reason?: string | null
  github_line_url?: string | null
  public_url?: string | null
}

/** Standalone GitHub evidence grouped by repository — compact rows, not cards. */
export type SkillReportStandaloneGitHubGroup = {
  repo_label: string
  /** Only set when the repository is public-safe. */
  repo_url?: string | null
  repo_is_public: boolean
  rows: SkillReportStandaloneGitHubRow[]
  row_more_count: number
}

export type SkillReportStandaloneEvidence = {
  github: SkillReportEvidenceItem[]
  /**
   * Repository-grouped, de-duplicated projection of `github` — compact rows per
   * repo so multiple lines from one repo never render as repeated full cards.
   * May be absent on older payloads — fall back to `github`.
   */
  github_groups?: SkillReportStandaloneGitHubGroup[]
  website: SkillReportEvidenceItem[]
  documents: SkillReportDocumentCorrelation[]
  document_more_count: number
  defense: SkillReportEvidenceItem[]
  video: SkillReportEvidenceItem[]
  skill_graph: SkillReportEvidenceItem[]
}

export type SkillReportOverview = {
  skill: string
  category: string
  status: string
  proof_source_counts: Record<string, number>
  proof_count: number
  attached_count: number
  unattached_count: number
  project_count: number
  why_supported: string
  gaps: string[]
}

/** Layer 2 — the full, recruiter-verifiable evidence for one selected skill. */
export type SkillReport = {
  skill: string
  skill_slug: string
  requested_skill: string
  category: string
  status: string
  summary: string
  source_counts: Record<string, number>
  overview: SkillReportOverview
  /** Connected proof chains, one per project (plus a standalone-vault bucket). */
  projects: SkillReportProjectChain[]
  /** Proofs not attached to any VBR project, grouped by source. */
  standalone_evidence: SkillReportStandaloneEvidence
  // ── Proof Synthesis Agent output ──────────────────────────────────────────
  /** Recruiter-facing summary of the whole synthesis (qualitative, no scores). */
  synthesis_summary?: string
  /** Boolean coverage across GitHub / Website / Document / Defense / Video. */
  source_coverage?: Record<string, boolean>
  /** Project-anchored connected proof chains (strongest tier first). */
  proof_chains?: SkillReportProjectChain[]
  /** Capped supporting proofs that join no chain. */
  unlinked_supporting_evidence?: SkillProofSynthesisUnlinked
  /**
   * Deterministically linked proof chains across normalized evidence (Step 3).
   * Carries the safe ``ev_…`` ids the synthesis claims cite. May be absent on
   * older payloads — treat as `[]`.
   */
  linked_proof_chains?: SkillReportLinkedChain[]
  /**
   * Recruiter-readable synthesis claims over the linked proof chains (Step 4).
   * Every claim cites real ``ev_…`` ids and carries a qualitative tier (never a
   * numeric score). May be absent on older payloads — treat as `[]`.
   */
  llm_synthesis?: SkillSynthesisResult[]
  // Flat per-source lists (back-compat; the connected chains above are primary).
  github: SkillReportEvidenceItem[]
  website: SkillReportEvidenceItem[]
  documents: SkillReportEvidenceItem[]
  defense: SkillReportEvidenceItem[]
  video: SkillReportEvidenceItem[]
  skill_graph: SkillReportEvidenceItem[]
  gaps: string[]
  generated_at: string
}

/**
 * A single row in the skill evidence table. ``status`` is always a
 * qualitative label — never a numeric trust/confidence score.
 */
export type VBRReportSkillEvidenceRow = {
  skill: string
  status: "Demonstrated" | "Partially demonstrated" | "Supporting evidence" | "Needs review" | "Not assessed" | string
  evidence_chip_count: number
  notes: string
  /**
   * Canonical recruiter-facing evidence-source labels that support this skill
   * (e.g. "GitHub Proof", "Website Proof", "Project Defense", "Video Evidence").
   * May be absent on older payloads — treat as `[]`.
   */
  supporting_sources?: string[]
  /** Honest per-skill caveats (e.g. a weakly-evidenced claim). */
  limitations?: string[]
  /** Plain-language justification for the qualitative status. */
  why_this_status?: string
  /** What a recruiter can safely inspect to verify this skill claim. */
  recruiter_can_verify?: string
  /** IDs of the evidence traces (see EvidenceTrace) that support this skill. */
  evidence_traces?: string[]
}

/**
 * Report-safe summary of the Project Defense analysis. Numeric analysis
 * scores (overall/clarity/ownership/depth/consistency) are never included —
 * each is mapped to a qualitative label
 * ("Demonstrated" / "Partially demonstrated" / "Supporting evidence" /
 * "Needs review" / "Not assessed").
 */
export type VBRReportProjectDefenseAnalysis = {
  transcript_summary: string
  skills_mentioned: string[]
  skills_explained_well: string[]
  skills_missing_from_explanation: string[]
  overall_assessment: string
  explanation_clarity: string
  ownership_signal: string
  technical_depth: string
  consistency_with_evidence: string
  risk_flags: string[]
  recruiter_summary: string
  recommended_improvements: string[]
  privacy_scan_status: string
}

/**
 * Private, student-owned preview of the Final VBR Report (v1) evidence
 * package for a Project Defense project. This is NOT the public tokenized
 * recruiter report — `public_recruiter_sharing_enabled` is always `false`.
 */
export type VBRStudentProjectReportResponse = {
  project_id: string
  project_title: string
  project_description: string
  repo_url: string
  repo_full_name: string | null
  student_role: string
  claimed_skills: string[]
  project_status: string
  session_id: string | null
  generated_at: string
  deployed_url?: string | null

  evidence_package: VBRReportEvidencePackageSummary

  github_proof: VBRReportGitHubProofSummary | null
  documents: VBRReportDocumentSummary[]
  website_proofs: VBRReportWebsiteProofSummary[]
  /**
   * Skill-specific Website Behavior Evidence (owner/private view only): what each
   * attached Website Proof demonstrably showed + an honest per-skill relevance,
   * projected only for the claimed skills the proof's extracted supported-skills
   * actually name. Never present on the public projection.
   */
  website_skill_evidence?: WebsiteProofSkillEvidence[]

  project_defense_analysis: VBRReportProjectDefenseAnalysis | null
  defense_questions: VBRReportQuestionSummary[]
  video_evidence_chips: VideoEvidenceChip[]

  skill_evidence: VBRReportSkillEvidenceRow[]
  evidence_traces?: EvidenceTrace[]

  /**
   * "Other student proofs for related skills" — safe student-vault proofs that
   * match this report's claimed skills but are NOT attached to this project.
   * Cross-proof / vault evidence, kept separate from the attached skill matrix
   * above so the report stays project-honest. May be absent on older payloads.
   */
  other_student_proofs?: VaultSkillGroup[]

  /**
   * "Suggested evidence to attach" (owner-only): unattached vault proofs whose
   * safe metadata points at this project. Clearly labelled "not counted until
   * attached" — never part of the attached evidence package, never on the
   * public report. May be absent on older payloads.
   */
  suggested_evidence?: ProofAttachmentEntry[]

  limitations: string[]
  next_actions: string[]

  preview_only: boolean
  public_recruiter_sharing_enabled: boolean
  note: string
}

/** Get the private, student-owned Final VBR Report preview for a project. */
export async function getVBRProjectReport(projectId: string): Promise<VBRStudentProjectReportResponse | null> {
  const res = await fetchAPI(`/api/v1/student/vbr/projects/${encodeURIComponent(projectId)}/report`)
  if (res.status === 404) return null
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to load report (HTTP ${res.status}).`))
  return res.json()
}

/** Fetch a published VBR report by its public token. No auth required. */
export async function getPublicVBRReport(
  publicToken: string,
): Promise<VBRPublicReportResponse | null> {
  const response = await fetch(
    `${API_BASE}/api/v1/public/vbr/legacy-reports/${encodeURIComponent(publicToken)}`,
    {
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
    },
  )

  if (response.status === 404) {
    return null
  }

  if (!response.ok) {
    throw new Error(`Failed to load report (HTTP ${response.status}).`)
  }

  return response.json()
}

// ─── Public recruiter-safe VBR project report link (v1) ─────────────────────

/**
 * Owner-only publish status for a project's recruiter-safe public link.
 * `public_token` is the owner's own token (used to build the shareable link)
 * and is only ever returned to the authenticated owner.
 */
export type ProjectReportPublishStatus = {
  project_id: string
  is_public: boolean
  public_token: string | null
  public_path: string | null
  published_at: string | null
}

/** A sanitized, timestamped public video evidence chip (no internal ids). */
export type PublicVideoEvidenceChip = {
  label: string
  timestamp_start_s: number
  timestamp_end_s: number
  short_summary: string
  related_skill?: string | null
  source: string
  source_type: string
}

/**
 * Defence-in-depth gate for direct verification links in public views.
 *
 * Mirrors the backend `is_safe_public_url` helper: a link is only safe to
 * render to an anonymous recruiter when it is a plain http(s) URL pointing at a
 * publicly resolvable host. Rejects localhost, private/internal hosts, private
 * IPs (RFC1918 + link-local), bare intranet hostnames, file/data/blob/javascript
 * schemes, and storage/signed/tokenized URLs. The backend already filters these
 * out; this is a second line of defence so an unsafe URL is never linked even if
 * one somehow reaches the client.
 */
export function isSafePublicUrl(url: string | null | undefined): boolean {
  if (!url || typeof url !== "string") return false
  let parsed: URL
  try {
    parsed = new URL(url.trim())
  } catch {
    return false
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return false

  // URL normalises IPv6 hosts to bracketed lowercase; strip the brackets.
  const host = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, "")
  if (!host) return false

  const disallowedHosts = new Set(["localhost", "0.0.0.0", "127.0.0.1", "::1", "ip6-localhost", "ip6-loopback"])
  if (disallowedHosts.has(host)) return false

  const disallowedSuffixes = [".local", ".localhost", ".internal", ".intranet", ".lan", ".corp", ".home", ".test", ".example", ".invalid"]
  if (disallowedSuffixes.some((suffix) => host.endsWith(suffix))) return false

  // IPv4 literal → reject loopback / private / link-local ranges.
  const ipv4 = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/)
  if (ipv4) {
    const [a, b] = ipv4.slice(1).map(Number)
    if ([a, b, Number(ipv4[3]), Number(ipv4[4])].some((n) => n > 255)) return false
    if (a === 10 || a === 127 || a === 0) return false
    if (a === 192 && b === 168) return false
    if (a === 172 && b >= 16 && b <= 31) return false
    if (a === 169 && b === 254) return false
    return true
  }
  // Any other IP-literal-ish / no public suffix → reject.
  if (host.includes(":")) return false // bare IPv6 literal
  if (!host.includes(".")) return false // bare intranet hostname
  const tld = host.slice(host.lastIndexOf(".") + 1)
  if (tld.length < 2 || !/^[a-z]+$/.test(tld)) return false

  // Storage / signed-object paths and obvious token/signature query params.
  const path = parsed.pathname.toLowerCase()
  if (path.includes("/storage/v1/object") || path.includes("/object/sign")) return false
  for (const key of parsed.searchParams.keys()) {
    const k = key.toLowerCase()
    if (["token", "access_token", "signature", "sig", "expires", "x-goog-signature"].includes(k) || k.startsWith("x-amz-")) {
      return false
    }
  }
  return true
}

/**
 * Public recruiter-safe Verified Build Report for one project. Read-only, no
 * login required, and never includes numeric trust scores, internal IDs, the
 * student's email, or raw/private evidence.
 */
export type PublicVBRProjectReport = {
  report_title: string
  project_title: string
  candidate_display_name: string | null
  project_summary: string
  student_role: string
  repo_full_name: string | null
  deployed_url?: string | null
  claimed_skills: string[]

  evidence_package: VBRReportEvidencePackageSummary

  github_proof: VBRReportGitHubProofSummary | null
  documents: VBRReportDocumentSummary[]
  website_proofs: VBRReportWebsiteProofSummary[]

  project_defense_analysis: VBRReportProjectDefenseAnalysis | null
  skill_evidence: VBRReportSkillEvidenceRow[]
  evidence_traces?: EvidenceTrace[]
  video_evidence_chips: PublicVideoEvidenceChip[]

  limitations: string[]

  published_at: string | null
  generated_at: string
  /**
   * Recruiter-safe link back to the candidate's published Work Passport
   * (`/p/{slug}`), or null when the passport is private/unpublished.
   */
  public_passport_path?: string | null
  verification_note: string
}

/** Get the publish status of a project's recruiter-safe public link. */
export async function getVBRProjectReportPublishStatus(
  projectId: string,
): Promise<ProjectReportPublishStatus> {
  const res = await fetchAPI(`/api/v1/student/vbr/projects/${encodeURIComponent(projectId)}/public-report/status`)
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to load publish status (HTTP ${res.status}).`))
  return res.json()
}

/** Publish (or re-fetch) the recruiter-safe public link for a project's report. */
export async function publishVBRProjectReport(projectId: string): Promise<ProjectReportPublishStatus> {
  const res = await fetchAPI(`/api/v1/student/vbr/projects/${encodeURIComponent(projectId)}/public-report`, {
    method: "POST",
  })
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to publish link (HTTP ${res.status}).`))
  return res.json()
}

/** Revoke the recruiter-safe public link for a project's report. */
export async function unpublishVBRProjectReport(projectId: string): Promise<ProjectReportPublishStatus> {
  const res = await fetchAPI(`/api/v1/student/vbr/projects/${encodeURIComponent(projectId)}/public-report`, {
    method: "DELETE",
  })
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to unpublish link (HTTP ${res.status}).`))
  return res.json()
}

/** Fetch a published recruiter-safe VBR project report by its public token. No auth required. */
export async function getPublicVBRProjectReport(
  publicToken: string,
): Promise<PublicVBRProjectReport | null> {
  const response = await fetch(
    `${API_BASE}/api/v1/public/vbr/reports/${encodeURIComponent(publicToken)}`,
    {
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
    },
  )

  if (response.status === 404) {
    return null
  }

  if (!response.ok) {
    throw new Error(`Failed to load report (HTTP ${response.status}).`)
  }

  return response.json()
}

// ─── Verified Work Passport v1 ──────────────────────────────────────────────

/**
 * Owner-only publish status for the student's public Work Passport.
 * `public_slug` / `public_path` are only ever returned to the owner, and only
 * while the passport is published.
 */
export type WorkPassportStatus = {
  is_published: boolean
  public_slug: string | null
  public_path: string | null
  published_at: string | null
  headline: string
  summary: string
}

/** A sanitized skill-evidence snippet shown in the skill drilldown. */
export type PassportSkillEvidenceChip = {
  label: string
  short_summary: string
  source: string
}

/** A project supporting a skill (private drilldown — owner-only project_id). */
export type PassportSkillProjectRef = {
  project_title: string
  project_id?: string | null
  /** This project's qualitative status FOR THIS SKILL (not the cross-project best). */
  skill_status?: string
  evidence_sources: string[]
  /** The proof types supporting THIS skill in THIS project only — a closed,
   *  skill-specific subset. Distinct from `evidence_sources` (the whole
   *  project's union); a type appears here only where the mapping recorded it
   *  for this exact skill, so it fails closed. */
  supporting_proof_types?: string[]
  report_is_public: boolean
  public_report_path: string | null
  /** Proof-native trace cards this project contributes for this skill. */
  evidence_traces?: EvidenceTrace[]
}

/**
 * Skill → Project cross-link: the project where a skill is most strongly
 * evidenced, as a linkable reference. `project_id` / `project_report_path`
 * are owner-only and never present on the public projection.
 */
export type PassportStrongestProjectLink = {
  project_title: string
  /** This project's qualitative label FOR THIS SKILL (never a score). */
  skill_status?: string
  evidence_sources: string[]
  /** Skill-specific proof-type breakdown for this project (see PassportSkillProjectRef). */
  supporting_proof_types?: string[]
  report_is_public?: boolean
  public_report_path?: string | null
  project_id?: string | null
  project_report_path?: string | null
}

/** A grouped, evidence-backed skill. `status` is always a qualitative label. */
export type PassportSkillSummary = {
  skill: string
  status: string
  evidence_chip_count: number
  project_count: number
  evidence_sources: string[]
  projects: PassportSkillProjectRef[]
  evidence_chips: PassportSkillEvidenceChip[]
  /** Aggregated claim→evidence traces across this candidate's projects. */
  evidence_traces?: EvidenceTrace[]
  /** The project where this skill is most strongly evidenced (owner-only). */
  strongest_project_title?: string | null
  strongest_project_status?: string | null
  /** The same strongest project as a linkable reference (owner-only routes). */
  strongest_project?: PassportStrongestProjectLink | null
  /** Proof-type sources that exist for this skill in the vault but are NOT
   *  attached to any project (vault-only / standalone evidence). Kept separate
   *  from `projects` so vault-only proof is never counted as project evidence. */
  vault_only_sources?: string[]
  notes: string
  limitations: string[]
}

/**
 * Proof-chain completeness for one project card. Derived from the already-safe
 * evidence source badges — booleans + missing labels only, never a score.
 */
export type PassportProofChain = {
  github: boolean
  website: boolean
  document: boolean
  project_defense: boolean
  video: boolean
  attached_count: number
  total_count: number
  missing: string[]
}

/**
 * One of the strongest skills a project demonstrates — qualitative label only.
 * `skill_slug` is the stable slug; `skill_report_path` is the owner-only Skill
 * Report route (absent on public payloads).
 */
export type PassportProjectTopSkill = {
  skill: string
  status: string
  skill_slug?: string | null
  skill_report_path?: string | null
  /** Proof types supporting THIS skill in THIS project (closed, skill-specific
   *  label set) — lets the project card show a per-skill proof breakdown. */
  supporting_proof_types?: string[]
}

/**
 * How each proof source relates to a project/skill claim — the safe,
 * recruiter-facing relationship vocabulary (labels only, never scores).
 *
 * Intentionally neutral: these labels describe only that a source is *attached*
 * for review. They never infer evidence strength from source presence alone —
 * e.g. GitHub is "attached for code/repository review" rather than "explains the
 * implementation", and video is "recorded explanation moments" rather than
 * "shows the work over time" — so a weak/repo-level source is never overclaimed
 * as authorship, implementation, or time-based proof.
 */
export const PROOF_SOURCE_RELATIONSHIP: Record<string, string> = {
  "GitHub Proof": "GitHub evidence is attached for code/repository review",
  "Website Proof": "Website evidence shows observed runtime/product behavior",
  "Document Proof": "Document evidence corroborates the project claim",
  "Project Defense": "Project Defense provides candidate explanation",
  "Video Evidence": "Video/timestamp evidence provides recorded explanation moments",
}

/** The five attachable proof-chain steps, in canonical render order. */
export const PROOF_CHAIN_STEPS: ReadonlyArray<{
  key: "github" | "website" | "document" | "project_defense" | "video"
  label: string
}> = [
  { key: "github", label: "GitHub Proof" },
  { key: "website", label: "Website Proof" },
  { key: "document", label: "Document Proof" },
  { key: "project_defense", label: "Project Defense" },
  { key: "video", label: "Video Evidence" },
]

/**
 * Derive proof-chain completeness from evidence source badges — the client-side
 * fallback for payloads that don't carry `proof_chain` yet.
 */
export function proofChainFromSources(sources: string[]): PassportProofChain {
  const present = new Set(sources)
  const chain = {
    github: present.has("GitHub Proof"),
    website: present.has("Website Proof"),
    document: present.has("Document Proof"),
    project_defense: present.has("Project Defense"),
    video: present.has("Video Evidence"),
  }
  const attached = PROOF_CHAIN_STEPS.filter((s) => chain[s.key]).length
  return {
    ...chain,
    attached_count: attached,
    total_count: PROOF_CHAIN_STEPS.length,
    missing: PROOF_CHAIN_STEPS.filter((s) => !chain[s.key]).map((s) => s.label),
  }
}

/**
 * Compact top-of-passport summary of the evidence graph
 * (projects ↔ skills ↔ proofs). Counts and next actions only — no scores.
 */
export type EvidenceGraphOverview = {
  project_count: number
  published_report_count: number
  skills_with_evidence: number
  proof_count: number
  attached_proof_count: number
  /** Suggested evidence — an improvement opportunity, never part of the
   *  attached count. May be absent on older payloads. */
  suggested_proof_count?: number
  unattached_proof_count: number
  next_actions: string[]
}

// ── Attachment Intelligence Cleanup (Step 4) ─────────────────────────────────

/** How a proof relates to the student's projects — a closed three-way state. */
export type AttachmentState = "attached" | "suggested" | "unattached"

/** Closed relation-strength labels — never a numeric confidence. Only
 *  `deterministic` (or user-attached) evidence ever counts as attached. */
export type RelationStrength = "deterministic" | "likely" | "weak" | "none"

/** Closed reason codes explaining an entry's attachment state. */
export type RelationReason =
  | "user_attached"
  | "exact_project_id_match"
  | "exact_repo_match"
  | "exact_document_attachment"
  | "exact_website_attachment"
  | "project_defense_session"
  | "title_similarity_suggestion"
  | "skill_overlap_suggestion"
  | "repo_owner_repo_suggestion"
  | "no_match"

/**
 * One deduplicated proof entry in the attachment overview (owner-only).
 * Safe display fields only — no source ids/tables, storage paths, signed
 * URLs, raw text, or provider payloads. `entry_id_safe` is a one-way digest
 * (also the stable React key).
 */
export type ProofAttachmentEntry = {
  entry_id_safe: string
  proof_type: string
  display_title: string
  source_label: string
  attachment_state: AttachmentState
  relation_reason: RelationReason
  relation_strength: RelationStrength
  reason_label: string
  status_label: string
  project_titles: string[]
  /** Owner-only project-report routes (never on the public projection). */
  project_refs_safe: string[]
  skill_names: string[]
  /** How many duplicate vault rows collapsed into this one entry (≥1). */
  duplicate_count: number
}

/**
 * Owner-only attached / suggested / unattached proof sections. The buckets are
 * disjoint and deduplicated: each real-world proof appears exactly once,
 * suggested evidence never counts as attached, and duplicate rows never
 * inflate a count.
 */
export type ProofAttachmentOverview = {
  attached: ProofAttachmentEntry[]
  suggested: ProofAttachmentEntry[]
  unattached: ProofAttachmentEntry[]
  attached_count: number
  suggested_count: number
  unattached_count: number
  note: string
}

/** One missing proof-chain source on a project card — qualitative gap + safe
 *  action copy (owner-only, never numeric). */
export type PassportProofChainGap = {
  source: string
  gap_label: string
  action: string
}

/** A compact per-project attachment suggestion (owner-only, non-destructive —
 *  it only describes a next action; nothing is attached automatically). */
export type PassportSuggestedAttachment = {
  suggestion_id_safe: string
  proof_type: string
  proof_title: string
  /** Closed qualitative label: "Likely match" / "Possible match" / "Needs review". */
  confidence_label: string
  suggestion_reason: string
  action_label: string
}

/**
 * One owner-only Proof Attachment Intelligence suggestion: which unattached
 * proof likely belongs to which project, the deterministic evidence-basis
 * chips behind the match, an honest hedged reason and limitation, and a closed
 * qualitative confidence label — never a numeric score, never on the public
 * passport.
 */
export type ProofAttachmentSuggestion = {
  suggestion_id_safe: string
  proof_type: string
  proof_title: string
  /** How many underlying vault rows grouped into this one suggestion. */
  proof_count: number
  likely_project_title: string
  /** Owner-only project-report route (absent when the project id is unknown). */
  likely_project_ref_safe?: string | null
  likely_skill_names: string[]
  suggestion_reason: string
  evidence_basis_chips: string[]
  confidence_label: string
  attachment_status: string
  limitation: string
  action_label: string
}

/** Owner-only summary of unattached vault evidence + attachment suggestions. */
export type UnattachedProofSummary = {
  unattached_count: number
  suggestion_count: number
  /** Unattached proofs no suggestion could safely match (never guessed). */
  unmatched_count: number
  suggestions: ProofAttachmentSuggestion[]
}

/** Owner-only publish status for one project's recruiter link. */
export type PassportProjectReportStatus = {
  is_public: boolean
  public_token: string | null
  public_path: string | null
  published_at: string | null
}

/** Owner-only project evidence card in the private passport. */
export type PassportProjectSummary = {
  project_id: string
  project_title: string
  project_summary: string
  repo_full_name: string | null
  claimed_skills: string[]
  evidence_sources: string[]
  evidence_package: VBRReportEvidencePackageSummary
  /** Proof-chain completeness across the five attachable evidence sources.
   *  May be absent on older payloads — derive from `evidence_sources`. */
  proof_chain?: PassportProofChain
  /** Qualitative proof-chain label ("Strong chain", "Missing runtime proof", …). */
  chain_label?: string
  /** Missing proof-chain sources as qualitative gaps with safe action copy. */
  proof_chain_gaps?: PassportProofChainGap[]
  /** Suggested proof attachments targeting THIS project (owner-only, capped). */
  suggested_attachments?: PassportSuggestedAttachment[]
  /** One safe "do this next" sentence for this project, when anything is left. */
  next_best_action?: string | null
  /** Strongest evidence-backed skills this project demonstrates (capped).
   *  Each entry links to its owner-only Skill Report route (Project → Skill). */
  top_skills?: PassportProjectTopSkill[]
  /** One safe sentence relating this project's skills to its proof sources. */
  evidence_relationship_note?: string | null
  /** How many duplicate evidence attempts merged into this card (≥1). */
  attempt_count: number
  report: PassportProjectReportStatus
}

/**
 * Owner-only, project-level-only Website Proof context. Surfaced when a project
 * has an attached Website Proof that did NOT map to any specific skill — it stays
 * project-level evidence (the site exists / can be inspected) but the observed
 * behaviour was too generic to demonstrate a skill. Every field is a closed label
 * / safe sentence — never raw evidence, ids, scores, or a faked skill mapping.
 */
export type PassportWebsiteProofContext = {
  project_id: string
  project_title: string
  /** Observed-behaviour classification key (e.g. "navigation_layout"). */
  focus_key: string
  /** Human label for the classification (e.g. "Navigation / page layout"). */
  focus_label: string
  /** One safe sentence describing what the recorded page demonstrably showed. */
  explanation: string
  /** Short reason it did not map a skill ("Navigation/layout evidence only", …). */
  reason: string
  /** The concrete runtime behaviour to record to make it skill-specific. */
  action_guidance: string
  /** Always false — this is explicitly the NOT-skill-mapped case. */
  mapped_to_skills: boolean
  /** Owner-only private route to this project's report. */
  report_path: string
}

/** The owner-only private Work Passport (full evidence wallet). */
/**
 * Recruiter-safe candidate identity header for the Verified Work Passport.
 * Non-PII identity context only — never the student's email, auth id, private
 * profile fields, or a raw institution name beyond the safe `region` (country).
 */
export type PassportIdentity = {
  display_name: string | null
  headline: string
  program: string | null
  degree_level: string | null
  graduation_year: number | null
  region: string | null
  education_summary: string
  public_status: string
  public_path: string | null
  last_updated: string | null
  evidence_source_summary: string[]
  verification_label: string
  /**
   * Optional recruiter-safe profile photo URL for the Passport Card. It is part
   * of the already-public identity payload, so it must only ever be a
   * public-safe image URL — never a signed/tokenized storage URL, a private
   * storage path, or a raw storage key. The card additionally sanitizes it
   * (see `publicSafeAvatarUrl`) and falls back to safe initials when absent or
   * unsafe. May be absent on older payloads.
   */
  avatar_url?: string | null
}

export type PrivateWorkPassport = {
  candidate_display_name: string | null
  headline: string
  summary: string
  identity?: PassportIdentity | null
  is_published: boolean
  public_slug: string | null
  public_path: string | null
  published_at: string | null
  /**
   * Compact evidence-graph summary rendered at the top of the passport. May be
   * absent on older payloads — the view derives a fallback from other fields.
   */
  evidence_graph_overview?: EvidenceGraphOverview | null
  skills: PassportSkillSummary[]
  projects: PassportProjectSummary[]
  evidence_source_counts: Record<string, number>
  /**
   * Project-level-only Website Proof context: attached Website Proofs that did
   * NOT map to any skill (too-generic observed behaviour). Powers the Skills
   * Evidence Map's honest "Website Proof exists but isn't skill-mapped" empty
   * state. Never counted as skill evidence; may be absent on older payloads.
   */
  website_proof_project_context?: PassportWebsiteProofContext[]
  /**
   * Student Proof Vault — Layer 1: COMPACT per-skill summaries (the main
   * dashboard). Each card carries category, qualitative status, counts, and a
   * few representative previews — never every proof card. The full evidence for
   * one skill is loaded lazily via `getSkillReport`. May be absent on older
   * payloads — treat as `[]`.
   */
  vault_skill_summaries?: VaultSkillSummary[]
  vault_proof_count?: number
  vault_unattached_count?: number
  /**
   * Proof Attachment Intelligence (owner-only): unattached vault evidence with
   * deterministic, qualitative attachment suggestions. Never present on the
   * public passport; may be absent on older payloads.
   */
  unattached_proof_summary?: UnattachedProofSummary | null
  /**
   * Attachment Intelligence Cleanup (Step 4): deduplicated attached /
   * suggested / unattached sections. Owner-only — never on the public
   * passport; may be absent on older payloads.
   */
  attachment_overview?: ProofAttachmentOverview | null
  project_count: number
  published_report_count: number
  limitations: string[]
  generated_at: string
}

/** A published project supporting a public skill — no internal ids. */
export type PublicPassportSkillProjectRef = {
  project_title: string
  /** Per-project qualitative status for this skill (label only). */
  skill_status?: string
  evidence_sources: string[]
  /** Proof types supporting this skill in this published project only. */
  supporting_proof_types?: string[]
  public_report_path: string
  /** Per-project trace cards (published, recruiter-safe) for this skill. */
  evidence_traces?: EvidenceTrace[]
}

/**
 * Public strongest-project reference — title, per-skill qualitative label and
 * the published report path only. Never an internal id or private route.
 */
export type PublicPassportStrongestProject = {
  project_title: string
  skill_status?: string
  evidence_sources: string[]
  /** Skill-specific proof-type breakdown for this published project. */
  supporting_proof_types?: string[]
  public_report_path: string
}

/** A public top-skill row — qualitative label only, with a safe drilldown. */
export type PublicPassportSkill = {
  skill: string
  status: string
  evidence_sources: string[]
  projects: PublicPassportSkillProjectRef[]
  evidence_chips: PassportSkillEvidenceChip[]
  /** Claim→evidence traces sourced ONLY from published public reports. */
  evidence_traces?: EvidenceTrace[]
  /** Where this skill is most strongly evidenced — published projects only. */
  strongest_project?: PublicPassportStrongestProject | null
  limitations: string[]
}

/** Public Project → Skill chip: skill + qualitative status + stable slug only. */
export type PublicPassportProjectTopSkill = {
  skill: string
  status: string
  skill_slug?: string | null
  /** Skill-specific proof-type breakdown for this published project (safe labels). */
  supporting_proof_types?: string[]
}

/** A public featured project — links to its public VBR report. */
export type PublicPassportProject = {
  project_title: string
  project_summary: string
  claimed_skills: string[]
  evidence_sources: string[]
  /** Safe proof-chain completeness (booleans + source labels; no ids/scores). */
  proof_chain?: PassportProofChain
  /** Safe Project → Skill chips (anchor to the public skills section). */
  top_skills?: PublicPassportProjectTopSkill[]
  /** Safe relationship sentence (qualitative labels only). */
  evidence_relationship_note?: string | null
  public_report_path: string
  published_at: string | null
}

/**
 * The recruiter-safe public Work Passport. Never includes the candidate's
 * email, auth id, internal project/session ids, raw evidence, or numeric
 * trust scores.
 */
export type PublicWorkPassport = {
  candidate_display_name: string | null
  headline: string
  summary: string
  identity?: PassportIdentity | null
  top_skills: PublicPassportSkill[]
  featured_projects: PublicPassportProject[]
  evidence_source_counts: Record<string, number>
  featured_project_count: number
  limitations: string[]
  published_at: string | null
  generated_at: string
  verification_note: string
}

/** Get the current user's private Verified Work Passport. */
export async function getPrivateWorkPassport(): Promise<PrivateWorkPassport> {
  const res = await fetchAPI("/api/v1/student/vbr/passport")
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to load passport (HTTP ${res.status}).`))
  return res.json()
}

/** The private Skill Report route for a skill slug (a separate page, not inline). */
export function skillReportPath(skillSlug: string): string {
  return `/student/vbr/passport/skills/${encodeURIComponent(skillSlug)}`
}

/**
 * Client-side skill-name slugify, used ONLY when a payload omits `skill_slug`.
 * The Skill Report endpoint resolves both canonical names and slugs, so a
 * display-name slug still lands on the right skill.
 */
export function fallbackSkillSlug(skill: string): string {
  return skill.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "skill"
}

/**
 * Layer 2 — load the FULL Student Proof Vault evidence for ONE selected skill.
 * Accepts either a canonical skill name or a URL slug (the backend resolves both
 * to the same skill). This is the expensive call (it hydrates website detail for
 * the skill); it is only made on the separate Skill Report page.
 */
export async function getSkillReport(skill: string): Promise<SkillReport> {
  const res = await fetchAPI(
    `/api/v1/student/vbr/passport/skill-report?skill=${encodeURIComponent(skill)}`,
  )
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to load skill report (HTTP ${res.status}).`))
  return res.json()
}

/** Get the publish status of the current user's Work Passport. */
export async function getWorkPassportStatus(): Promise<WorkPassportStatus> {
  const res = await fetchAPI("/api/v1/student/vbr/passport/status")
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to load passport status (HTTP ${res.status}).`))
  return res.json()
}

/** Publish (or re-publish) the current user's public Work Passport. */
export async function publishWorkPassport(
  body?: { headline?: string; summary?: string },
): Promise<WorkPassportStatus> {
  const res = await fetchAPI("/api/v1/student/vbr/passport/publish", {
    method: "POST",
    body: JSON.stringify(body ?? {}),
  })
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to publish passport (HTTP ${res.status}).`))
  return res.json()
}

/** Hide the current user's public Work Passport. */
export async function unpublishWorkPassport(): Promise<WorkPassportStatus> {
  const res = await fetchAPI("/api/v1/student/vbr/passport/unpublish", { method: "POST" })
  if (!res.ok) throw new Error(await parseErrorMessage(res, `Failed to unpublish passport (HTTP ${res.status}).`))
  return res.json()
}

/** Fetch a published recruiter-safe public Work Passport by its slug. No auth required. */
export async function getPublicWorkPassportBySlug(
  slug: string,
): Promise<PublicWorkPassport | null> {
  const response = await fetch(`${API_BASE}/api/v1/public/p/${encodeURIComponent(slug)}`, {
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
  })

  if (response.status === 404) {
    return null
  }

  if (!response.ok) {
    throw new Error(`Failed to load passport (HTTP ${response.status}).`)
  }

  return response.json()
}
