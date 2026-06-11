"use client"

import { fetchAPI } from "@/lib/api"

/**
 * Client for the Verified Build Report (VBR) session recording endpoints
 * (T4A backend). MVP metadata-only — no real signed upload URLs yet.
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
  sha256?: string | null
}

export type VBRChunkResponse = {
  id: string
  session_id: string
  chunk_index: number
  bytes: number | null
  sha256: string | null
  received_at: string
}

export type VBRTelemetryResponse = {
  session_id: string
  telemetry: Record<string, unknown>
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
