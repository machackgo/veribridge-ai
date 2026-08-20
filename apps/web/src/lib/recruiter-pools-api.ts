/**
 * Typed client for the Recruiter Talent Pools API
 * (`/api/v1/recruiter/pools`, migration 070).
 *
 * A Talent Pool is a recruiter-owned, role-independent candidate collection
 * ("AI / ML Early Talent"). Membership is keyed by the candidate's stable
 * user id; identity and evidence context are resolved live and fail-closed
 * on every load — a candidate who unpublishes goes dark in every pool.
 *
 * Requires a Supabase session, same policy as the connections/briefs APIs.
 */

import { fetchAPI } from "@/lib/api"
import type { BriefCandidateIdentity } from "@/lib/recruiter-briefs-api"
import { AuthRequiredError } from "@/lib/recruiter-connections-api"

export type { BriefCandidateIdentity }
export { AuthRequiredError }

export type PoolStatus = "active" | "archived"

/** 065 connection vocabulary + saved_search — how a candidate entered a pool. */
export type PoolCandidateSource =
  | "qr_scan"
  | "shared_link"
  | "search"
  | "role_match"
  | "direct"
  | "saved_search"

export interface TalentPool {
  id: string
  name: string
  description: string | null
  status: PoolStatus
  candidate_count: number
  created_at: string | null
  updated_at: string | null
}

/** Light LIVE evidence context — transparent counts, never a score. */
export interface PoolCandidateEvidence {
  skill_count: number
  project_count: number
  evidence_flags: Record<string, boolean>
  top_skills: string[]
  public_slug: string | null
}

/** One pool member. `evidence` is null once the candidate is no longer
 * publicly live — the identity card then shows the no-longer-published
 * treatment. */
export interface PoolCandidate {
  student_user_id: string
  source: PoolCandidateSource
  note: string | null
  added_at: string | null
  candidate: BriefCandidateIdentity
  evidence: PoolCandidateEvidence | null
}

export interface TalentPoolDetail {
  pool: TalentPool
  candidates: PoolCandidate[]
  total: number
}

export interface AddPoolCandidatesResult {
  added: number
  already_in_pool: number
  candidates: PoolCandidate[]
}

/**
 * A non-OK Talent Pools API response, carrying the machine-readable
 * `detail.code` (e.g. "pool_full") alongside the human message.
 */
export class PoolApiError extends Error {
  code: string | null

  constructor(message: string, code: string | null = null) {
    super(message)
    this.name = "PoolApiError"
    this.code = code
  }
}

async function parseErrorDetail(
  res: Response,
  fallback: string,
): Promise<{ message: string; code: string | null }> {
  try {
    const body = (await res.json()) as {
      detail?: { message?: string; code?: string } | string
    }
    const detail = body?.detail
    if (detail && typeof detail === "object") {
      return {
        message: typeof detail.message === "string" ? detail.message : fallback,
        code: typeof detail.code === "string" ? detail.code : null,
      }
    }
    if (typeof detail === "string") return { message: detail, code: null }
  } catch {
    // response body was not JSON — fall back to generic message
  }
  return { message: fallback, code: null }
}

async function request<T>(path: string, init: RequestInit | undefined, fallback: string): Promise<T> {
  const res = await fetchAPI(path, init)
  if (res.status === 401) throw new AuthRequiredError()
  if (!res.ok) {
    const { message, code } = await parseErrorDetail(res, fallback)
    throw new PoolApiError(message, code)
  }
  return res.json() as Promise<T>
}

/** The recruiter's Talent Pools, most recently updated first. */
export async function listPools(): Promise<TalentPool[]> {
  const body = await request<{ pools?: TalentPool[] }>(
    "/api/v1/recruiter/pools",
    undefined,
    "Failed to load Talent Pools.",
  )
  return body.pools ?? []
}

export async function createPool(params: {
  name: string
  description?: string | null
}): Promise<TalentPool> {
  const body = await request<{ pool: TalentPool }>(
    "/api/v1/recruiter/pools",
    { method: "POST", body: JSON.stringify(params) },
    "Failed to create the Talent Pool.",
  )
  return body.pool
}

/** One pool plus its live candidate cards. */
export async function getPool(poolId: string): Promise<TalentPoolDetail> {
  return request<TalentPoolDetail>(
    `/api/v1/recruiter/pools/${encodeURIComponent(poolId)}`,
    undefined,
    "Failed to load the Talent Pool.",
  )
}

/** Partial update: name / description / archived status. */
export async function updatePool(
  poolId: string,
  params: {
    name?: string
    description?: string | null
    clear_description?: boolean
    status?: PoolStatus
  },
): Promise<TalentPool> {
  const body = await request<{ pool: TalentPool }>(
    `/api/v1/recruiter/pools/${encodeURIComponent(poolId)}`,
    { method: "PATCH", body: JSON.stringify(params) },
    "Failed to update the Talent Pool.",
  )
  return body.pool
}

export async function deletePool(poolId: string): Promise<void> {
  await request<{ deleted: boolean }>(
    `/api/v1/recruiter/pools/${encodeURIComponent(poolId)}`,
    { method: "DELETE" },
    "Failed to delete the Talent Pool.",
  )
}

/** Idempotently add candidates (published slugs / own connections / already
 * visible student ids). */
export async function addPoolCandidates(
  poolId: string,
  params: {
    candidate_slugs?: string[]
    connection_ids?: string[]
    student_user_ids?: string[]
    source?: PoolCandidateSource
  },
): Promise<AddPoolCandidatesResult> {
  return request<AddPoolCandidatesResult>(
    `/api/v1/recruiter/pools/${encodeURIComponent(poolId)}/candidates`,
    { method: "POST", body: JSON.stringify(params) },
    "Failed to add candidates to the Talent Pool.",
  )
}

/** Update one member's recruiter-private note. */
export async function updatePoolCandidate(
  poolId: string,
  studentUserId: string,
  params: { note?: string; clear_note?: boolean },
): Promise<PoolCandidate> {
  const body = await request<{ candidate: PoolCandidate }>(
    `/api/v1/recruiter/pools/${encodeURIComponent(poolId)}/candidates/${encodeURIComponent(studentUserId)}`,
    { method: "PATCH", body: JSON.stringify(params) },
    "Failed to save the note.",
  )
  return body.candidate
}

export async function removePoolCandidate(
  poolId: string,
  studentUserId: string,
): Promise<void> {
  await request<{ removed: boolean }>(
    `/api/v1/recruiter/pools/${encodeURIComponent(poolId)}/candidates/${encodeURIComponent(studentUserId)}`,
    { method: "DELETE" },
    "Failed to remove the candidate from the Talent Pool.",
  )
}

/** {student_user_id → [pool ids]} across the caller's OWN pools. */
export async function getPoolMemberships(
  studentUserIds: string[],
): Promise<Record<string, string[]>> {
  if (studentUserIds.length === 0) return {}
  const body = await request<{ memberships?: Record<string, string[]> }>(
    `/api/v1/recruiter/pools/memberships?student_user_ids=${encodeURIComponent(studentUserIds.join(","))}`,
    undefined,
    "Failed to load pool memberships.",
  )
  return body.memberships ?? {}
}
