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
 * A single row in the skill evidence table. ``status`` is always a
 * qualitative label — never a numeric trust/confidence score.
 */
export type VBRReportSkillEvidenceRow = {
  skill: string
  status: "Demonstrated" | "Partially demonstrated" | "Supporting evidence" | "Needs review" | "Not assessed" | string
  evidence_chip_count: number
  notes: string
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

  evidence_package: VBRReportEvidencePackageSummary

  github_proof: VBRReportGitHubProofSummary | null
  documents: VBRReportDocumentSummary[]
  website_proofs: VBRReportWebsiteProofSummary[]

  project_defense_analysis: VBRReportProjectDefenseAnalysis | null
  defense_questions: VBRReportQuestionSummary[]
  video_evidence_chips: VideoEvidenceChip[]

  skill_evidence: VBRReportSkillEvidenceRow[]

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
  claimed_skills: string[]

  evidence_package: VBRReportEvidencePackageSummary

  github_proof: VBRReportGitHubProofSummary | null
  documents: VBRReportDocumentSummary[]
  website_proofs: VBRReportWebsiteProofSummary[]

  project_defense_analysis: VBRReportProjectDefenseAnalysis | null
  skill_evidence: VBRReportSkillEvidenceRow[]
  video_evidence_chips: PublicVideoEvidenceChip[]

  limitations: string[]

  published_at: string | null
  generated_at: string
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
