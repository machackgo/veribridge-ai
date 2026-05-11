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
