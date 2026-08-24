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
import type {
  BriefCandidateIdentity,
  ComparisonMatrix,
  RequirementsView,
} from "@/lib/recruiter-briefs-api"
import { AuthRequiredError } from "@/lib/recruiter-connections-api"

export type { BriefCandidateIdentity, ComparisonMatrix, RequirementsView }
export { AuthRequiredError }

export type PoolStatus = "active" | "archived"

/**
 * RECRUITER-PRIVATE workflow stage, scoped to ONE pool.
 *
 * This is the recruiter's own process, never a judgement recorded against
 * the candidate: it changes no evidence, is invisible to the candidate, and
 * does not travel to another pool, a Hiring Brief, or any public surface.
 */
export type PoolCandidateStatus =
  | "review"
  | "shortlisted"
  | "interview"
  | "hold"
  | "pass"

export const POOL_CANDIDATE_STATUSES: PoolCandidateStatus[] = [
  "review",
  "shortlisted",
  "interview",
  "hold",
  "pass",
]

export const POOL_STATUS_LABEL: Record<PoolCandidateStatus, string> = {
  review: "Review",
  shortlisted: "Shortlisted",
  interview: "Interview",
  hold: "Hold",
  pass: "Pass",
}

/** Evidence-type gates the engine accepts (recruiter_search_service). */
export const EVIDENCE_FILTER_KEYS = [
  "github",
  "live_site",
  "documents",
  "project_defense",
  "video",
] as const
export type EvidenceFilterKey = (typeof EVIDENCE_FILTER_KEYS)[number]

export const EVIDENCE_FILTER_LABEL: Record<EvidenceFilterKey, string> = {
  github: "GitHub Proof",
  live_site: "Website Proof",
  documents: "Document Proof",
  project_defense: "Project Defense",
  video: "Video Evidence",
}

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
  /** ── recruiter-private judgement (never evidence, never candidate-visible) */
  status: PoolCandidateStatus
  note: string | null
  tags: string[]
  added_at: string | null
  updated_at: string | null
  /** ── VeriBridge evidence domain (consented, live, fail-closed) */
  candidate: BriefCandidateIdentity
  evidence: PoolCandidateEvidence | null
}

/** One entry in the recruiter's private tag vocabulary. */
export interface RecruiterTag {
  tag: string
  tag_key: string
  candidate_count: number
}

export interface TalentPoolDetail {
  pool: TalentPool
  candidates: PoolCandidate[]
  total: number
  status_counts: Record<string, number>
  tag_vocabulary: RecruiterTag[]
}

/**
 * WHY a candidate survived an evidence filter — reconstructed from the
 * deterministic evaluation, never a score and never generated prose.
 * `match_type` is the engine's classification: "exact" (every requirement
 * evidenced) vs "close" (at least one named in `missing_requirements`).
 */
export interface PoolCandidateMatch {
  match_type: string
  requirements: Array<Record<string, unknown>>
  missing_requirements: string[]
  matched_reasons: Array<Record<string, unknown>>
  skills: Array<Record<string, unknown>>
  projects: Array<Record<string, unknown>>
}

export interface FilteredPoolCandidate extends PoolCandidate {
  match: PoolCandidateMatch | null
}

export interface PoolFilterEcho {
  q: string
  evidence: string[]
  status: string | null
  tags: string[]
}

export interface PoolFilterResult {
  pool: TalentPool
  candidates: FilteredPoolCandidate[]
  total: number
  pool_total: number
  status_counts: Record<string, number>
  tag_vocabulary: RecruiterTag[]
  filters: PoolFilterEcho
  /** "Understood as …" — what the engine actually executed, including terms
   * it could NOT turn into a requirement. Null when no query was given. */
  interpretation: Record<string, unknown> | null
  /** Members who could not be evidence-matched because their evidence is no
   * longer publicly live. Surfaced so the UI says so rather than silently
   * shrinking the pool. */
  unavailable_excluded: number
}

export interface PoolComparisonResult {
  pool: TalentPool
  matrix: ComparisonMatrix
  query: string | null
  requirements_view: RequirementsView
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

/**
 * Update one member's RECRUITER-PRIVATE workflow metadata — pool-scoped note
 * and status, plus the recruiter's tags for that candidate. Omitted fields
 * stay unchanged; `tags` REPLACES the set.
 *
 * None of this can alter evidence, verification state, a Work Passport, a
 * Verified Build Report, or any public surface.
 */
export async function updatePoolCandidate(
  poolId: string,
  studentUserId: string,
  params: {
    note?: string
    clear_note?: boolean
    status?: PoolCandidateStatus
    tags?: string[]
  },
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

/**
 * Filter ONE pool's members by published evidence and/or the recruiter's own
 * workflow metadata. Evidence predicates run through the SAME engine global
 * recruiter search runs, restricted to this pool — so every returned
 * candidate is explainable from stored evidence, and a fuzzy near-miss is
 * never silently promoted into a match.
 */
export async function filterPoolCandidates(
  poolId: string,
  params: {
    q?: string
    evidence?: string[]
    status?: PoolCandidateStatus | null
    tags?: string[]
  },
): Promise<PoolFilterResult> {
  const search = new URLSearchParams()
  if (params.q?.trim()) search.set("q", params.q.trim())
  if (params.evidence?.length) search.set("evidence", params.evidence.join(","))
  if (params.status) search.set("candidate_status", params.status)
  if (params.tags?.length) search.set("tags", params.tags.join(","))
  const qs = search.toString()
  return request<PoolFilterResult>(
    `/api/v1/recruiter/pools/${encodeURIComponent(poolId)}/filter${qs ? `?${qs}` : ""}`,
    undefined,
    "Failed to filter the Talent Pool.",
  )
}

/**
 * The requirement × candidate evidence matrix for 2–5 pool members.
 * With `q`, the axis is the recruiter's stated requirements; without it, the
 * axis is derived from the selected candidates' OWN published evidence.
 * Never a ranking and never a score.
 */
export async function comparePoolCandidates(
  poolId: string,
  params: { student_user_ids: string[]; q?: string | null },
): Promise<PoolComparisonResult> {
  return request<PoolComparisonResult>(
    `/api/v1/recruiter/pools/${encodeURIComponent(poolId)}/comparison`,
    { method: "POST", body: JSON.stringify(params) },
    "Failed to build the comparison.",
  )
}

/** The caller's private candidate-tag vocabulary (autocomplete + chips). */
export async function listRecruiterTags(): Promise<RecruiterTag[]> {
  const body = await request<{ tags?: RecruiterTag[] }>(
    "/api/v1/recruiter/pools/tags",
    undefined,
    "Failed to load your tags.",
  )
  return body.tags ?? []
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
