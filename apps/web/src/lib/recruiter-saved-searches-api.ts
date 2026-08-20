/**
 * Typed client for the Recruiter Saved Searches API
 * (`/api/v1/recruiter/saved-searches`, migration 070).
 *
 * A Saved Search persists the parsed requirement plan of a recruiter
 * search. Results are ALWAYS recomputed live by the same engine as the
 * search page; the API's stored match state only powers the honest
 * "new candidate" / "updated published evidence" annotations — hashes and
 * timestamps server-side, never copied candidate data.
 *
 * Requires a Supabase session, same policy as the connections/briefs APIs.
 */

import { fetchAPI } from "@/lib/api"
import type { RequirementsView } from "@/lib/recruiter-briefs-api"
import { AuthRequiredError } from "@/lib/recruiter-connections-api"
import type {
  AvailabilityFilter,
  EvidenceFilter,
  QueryInterpretation,
  SearchResultCandidate,
} from "@/lib/recruiter-search-api"

export type { RequirementsView }
export { AuthRequiredError }

export type SavedSearchStatus = "active" | "paused"

/** The explicit filter chips a saved search re-applies on every run. */
export interface SavedSearchFilters {
  skills?: string[]
  evidence?: EvidenceFilter[]
  availability?: AvailabilityFilter | null
}

/** One saved search. `tracking` is false when the plan has no hard
 * requirements (savable, honestly untracked). Counts are null while
 * paused — a paused search is not reconciled, so counts would be stale. */
export interface SavedSearchListItem {
  id: string
  name: string
  query_text: string | null
  status: SavedSearchStatus
  requirements: RequirementsView
  tracking: boolean
  new_count: number | null
  updated_count: number | null
  match_count: number | null
  last_evaluated_at: string | null
  last_reviewed_at: string | null
  created_at: string | null
  updated_at: string | null
}

/** Per-candidate discovery state, keyed by public slug in the results. */
export interface SavedSearchAnnotation {
  is_new: boolean
  evidence_updated: boolean
  changed_requirements: string[]
  first_matched_at: string | null
}

export interface SavedSearchResults {
  saved_search: SavedSearchListItem
  results: SearchResultCandidate[]
  total: number
  exact_total: number
  close_total: number
  page: number
  page_size: number
  has_more: boolean
  interpretation: QueryInterpretation
  annotations: Record<string, SavedSearchAnnotation>
  /** True when the exact-match set exceeded the tracking bound — stated,
   * never silent. */
  truncated: boolean
}

/**
 * A non-OK Saved Searches API response, carrying the machine-readable
 * `detail.code` (e.g. "too_many_saved_searches") alongside the message.
 */
export class SavedSearchApiError extends Error {
  code: string | null

  constructor(message: string, code: string | null = null) {
    super(message)
    this.name = "SavedSearchApiError"
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
    throw new SavedSearchApiError(message, code)
  }
  return res.json() as Promise<T>
}

/** The recruiter's saved searches, most recently updated first. */
export async function listSavedSearches(): Promise<SavedSearchListItem[]> {
  const body = await request<{ saved_searches?: SavedSearchListItem[] }>(
    "/api/v1/recruiter/saved-searches",
    undefined,
    "Failed to load saved searches.",
  )
  return body.saved_searches ?? []
}

/** Save a search. The API parses `q` with the real search grammar and
 * baselines the results — nothing is "new" at the moment of saving. */
export async function createSavedSearch(params: {
  q: string
  name?: string | null
  filters?: SavedSearchFilters | null
}): Promise<SavedSearchListItem> {
  const body = await request<{ saved_search: SavedSearchListItem }>(
    "/api/v1/recruiter/saved-searches",
    { method: "POST", body: JSON.stringify(params) },
    "Failed to save the search.",
  )
  return body.saved_search
}

/** Live results + new/updated-evidence annotations for one saved search. */
export async function getSavedSearchResults(
  savedSearchId: string,
  params: { page?: number } = {},
): Promise<SavedSearchResults> {
  const query = params.page && params.page > 1 ? `?page=${params.page}` : ""
  return request<SavedSearchResults>(
    `/api/v1/recruiter/saved-searches/${encodeURIComponent(savedSearchId)}${query}`,
    undefined,
    "Failed to load the saved search.",
  )
}

/** Partial update: rename / pause / resume / edit the query or filters. */
export async function updateSavedSearch(
  savedSearchId: string,
  params: {
    name?: string
    status?: SavedSearchStatus
    q?: string
    filters?: SavedSearchFilters
  },
): Promise<SavedSearchListItem> {
  const body = await request<{ saved_search: SavedSearchListItem }>(
    `/api/v1/recruiter/saved-searches/${encodeURIComponent(savedSearchId)}`,
    { method: "PATCH", body: JSON.stringify(params) },
    "Failed to update the saved search.",
  )
  return body.saved_search
}

/** Mark reviewed — moves the "new since" boundary to now. */
export async function markSavedSearchReviewed(
  savedSearchId: string,
): Promise<SavedSearchListItem> {
  const body = await request<{ saved_search: SavedSearchListItem }>(
    `/api/v1/recruiter/saved-searches/${encodeURIComponent(savedSearchId)}/review`,
    { method: "POST", body: JSON.stringify({}) },
    "Failed to mark the saved search reviewed.",
  )
  return body.saved_search
}

/** Deleting a saved search never removes candidates, pools, or briefs. */
export async function deleteSavedSearch(savedSearchId: string): Promise<void> {
  await request<{ deleted: boolean }>(
    `/api/v1/recruiter/saved-searches/${encodeURIComponent(savedSearchId)}`,
    { method: "DELETE" },
    "Failed to delete the saved search.",
  )
}
