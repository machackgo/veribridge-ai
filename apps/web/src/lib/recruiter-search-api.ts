/**
 * Typed client for the Recruiter Search & Discovery API
 * (`/api/v1/recruiter/search`, migration 066).
 *
 * Requires a Supabase session (same policy as the connections API):
 * candidate discovery is a recruiter-product surface. Every result is
 * derived from the candidate's PUBLIC Work Passport projection — the same
 * data served at `/p/{slug}` — with structured, evidence-traceable match
 * explanations instead of scores.
 */

import { fetchAPI } from "@/lib/api"
import { AuthRequiredError } from "@/lib/recruiter-connections-api"

export type EvidenceFilter =
  | "github"
  | "live_site"
  | "documents"
  | "project_defense"
  | "video"

export type AvailabilityFilter =
  | "seeking_internship"
  | "seeking_full_time"
  | "open_to_opportunities"

export interface SearchSkill {
  skill: string
  status: string
  evidence_sources: string[]
  matched: boolean
}

export interface SearchProject {
  title: string | null
  public_report_path: string | null
  evidence_sources: string[]
  has_live_url: boolean
}

export interface MatchedReason {
  type:
    | "skill"
    | "name"
    | "technology"
    | "headline"
    | "role_area"
    | "project"
    | "education"
    | "location"
  label: string
  term?: string | null
  skill_status?: string | null
  evidence_sources?: string[] | null
  project_title?: string | null
}

export interface SearchResultCandidate {
  public_slug: string
  display_name: string | null
  headline: string | null
  location: string | null
  availability_label: string | null
  institution: string | null
  degree: string | null
  graduation_year: number | null
  role_areas: string[]
  skills: SearchSkill[]
  skill_count: number
  project_count: number
  projects: SearchProject[]
  evidence_flags: Partial<Record<EvidenceFilter, boolean>>
  matched_reasons: MatchedReason[]
  passport_published_at: string | null
}

export interface SearchQueryEcho {
  q: string
  terms: string[]
  skills: string[]
  evidence: string[]
  availability: string | null
}

export interface RecruiterSearchResponse {
  results: SearchResultCandidate[]
  total: number
  page: number
  page_size: number
  has_more: boolean
  query: SearchQueryEcho
}

export interface SearchParams {
  q?: string
  evidence?: EvidenceFilter[]
  availability?: AvailabilityFilter | null
  page?: number
  pageSize?: number
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

/** Search the discoverable candidate population (published passports only). */
export async function searchCandidates(
  params: SearchParams,
): Promise<RecruiterSearchResponse> {
  const query = new URLSearchParams()
  if (params.q?.trim()) query.set("q", params.q.trim())
  if (params.evidence?.length) query.set("evidence", params.evidence.join(","))
  if (params.availability) query.set("availability", params.availability)
  if (params.page && params.page > 1) query.set("page", String(params.page))
  if (params.pageSize) query.set("page_size", String(params.pageSize))
  const suffix = query.toString()
  const res = await fetchAPI(`/api/v1/recruiter/search${suffix ? `?${suffix}` : ""}`)
  if (res.status === 401) throw new AuthRequiredError()
  if (!res.ok) {
    throw new Error(
      await parseErrorMessage(res, `Search failed (HTTP ${res.status}).`),
    )
  }
  return res.json()
}
