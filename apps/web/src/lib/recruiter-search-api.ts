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

export type MatchType = "exact" | "close" | "match"

export interface RequirementMatch {
  kind: "concept" | "evidence" | "context"
  requirement: string
  display: string
  required: boolean
  satisfied: boolean
  via: "skill" | "technology" | null
  matched_label: string | null
  skill_status: string | null
  evidence_sources: string[]
  project_titles: string[]
  note: string | null
}

export interface InterpretationChip {
  display: string
  concepts: string[]
}

export interface EvidenceExpectation {
  key: string
  display: string
}

export type SearchIntent =
  | "candidate_search"
  | "evidence_search"
  | "project_search"

export interface QueryInterpretation {
  mode: "browse" | "lexical" | "structured"
  intent: SearchIntent
  required: InterpretationChip[]
  preferred: InterpretationChip[]
  excluded: InterpretationChip[]
  evidence: EvidenceExpectation[]
  preferred_evidence: EvidenceExpectation[]
  role: string | null
  seniority: string | null
  location: string | null
  residual_terms: string[]
}

export interface SearchResultCandidate {
  match_type: MatchType
  requirements: RequirementMatch[]
  missing_requirements: string[]
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

/**
 * Evidence Discovery (V1.6). Every field is a projection of PUBLIC Work
 * Passport data — titles, published report paths, closed proof-type labels,
 * qualitative statuses, sanitized public trace previews. Never private
 * artifacts.
 */
export interface EvidenceProjectRef {
  title: string | null
  public_report_path: string | null
  skill_status: string | null
  proof_types: string[]
}

export interface EvidenceTracePreview {
  source_type: string | null
  source_title: string | null
  summary: string | null
  public_url: string | null
}

export interface EvidenceItem {
  /** "skill" = published verified evidence; "claimed" = a project technology
   * claim, explicitly labeled and never presented as verified proof. */
  tier: "skill" | "claimed"
  requirement: string | null
  requirement_display: string | null
  related_to: string | null
  skill: string
  skill_slug: string
  status: string
  direct: boolean
  note: string | null
  evidence_sources: string[]
  proof_path: string | null
  projects: EvidenceProjectRef[]
  traces: EvidenceTracePreview[]
}

export interface EvidenceCandidateGroup {
  public_slug: string
  display_name: string | null
  headline: string | null
  passport_path: string
  items: EvidenceItem[]
}

export interface UnmatchedEvidenceRequirement {
  requirement: string
  display: string
  note: string
}

export interface RelatedEvidenceHint {
  requirement_display: string
  related_display: string
  candidate_names: string[]
  note: string
}

export interface EvidenceCandidateFilter {
  terms: string[]
  matched_candidates: string[]
  ambiguous: boolean
}

export interface EvidenceResults {
  total_items: number
  groups: EvidenceCandidateGroup[]
  unmatched: UnmatchedEvidenceRequirement[]
  related: RelatedEvidenceHint[]
  evidence_types: EvidenceExpectation[]
  candidate_filter: EvidenceCandidateFilter | null
  notes: string[]
}

export interface RecruiterSearchResponse {
  results: SearchResultCandidate[]
  total: number
  exact_total: number
  close_total: number
  page: number
  page_size: number
  has_more: boolean
  interpretation: QueryInterpretation
  evidence?: EvidenceResults | null
  query: SearchQueryEcho
}

export interface RecruiterEvidenceResponse {
  evidence: EvidenceResults
  skill: string | null
  candidate: string | null
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

/**
 * Structured View-proof drilldown: open the published evidence behind a
 * skill for one candidate (stable identifiers, no natural-language parsing).
 */
export async function viewEvidence(params: {
  skill?: string
  candidate?: string
  evidence?: EvidenceFilter[]
}): Promise<RecruiterEvidenceResponse> {
  const query = new URLSearchParams()
  if (params.skill?.trim()) query.set("skill", params.skill.trim())
  if (params.candidate?.trim()) query.set("candidate", params.candidate.trim())
  if (params.evidence?.length) query.set("evidence", params.evidence.join(","))
  const suffix = query.toString()
  const res = await fetchAPI(
    `/api/v1/recruiter/search/evidence${suffix ? `?${suffix}` : ""}`,
  )
  if (res.status === 401) throw new AuthRequiredError()
  if (!res.ok) {
    throw new Error(
      await parseErrorMessage(res, `Could not load proof (HTTP ${res.status}).`),
    )
  }
  return res.json()
}
