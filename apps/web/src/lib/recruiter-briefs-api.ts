/**
 * Typed client for the Recruiter Hiring Briefs API
 * (`/api/v1/recruiter/briefs`, migration 068).
 *
 * A Hiring Brief is the recruiter-owned source of truth for one hiring
 * need: role text + structured requirements + a ROLE-SCOPED candidate pool
 * (a candidate can be Shortlisted for one brief and merely Saved for
 * another — there is no global shortlist). Comparison and every candidate
 * evaluation are live views re-run against published public evidence on
 * every load; nothing is snapshotted.
 *
 * Requires a Supabase session, same policy as the connections/search APIs.
 */

import { fetchAPI } from "@/lib/api"
import { AuthRequiredError } from "@/lib/recruiter-connections-api"
import type {
  AvailabilityFilter,
  RecruiterSearchResponse,
} from "@/lib/recruiter-search-api"

export type BriefStatus = "draft" | "active" | "paused" | "closed"

/**
 * The role-scoped pipeline vocabulary, in pipeline order (V4).
 * `passed` = considered and declined for THIS role; `archived` = parked
 * without a decision. Any→any transitions are allowed — the activity trail
 * is the audit, not a state machine.
 */
export const CANDIDATE_STAGE_ORDER = [
  "saved",
  "reviewing",
  "shortlisted",
  "contacted",
  "interview",
  "decision",
  "hired",
  "passed",
  "archived",
] as const

export type BriefCandidateStatus = (typeof CANDIDATE_STAGE_ORDER)[number]

export interface RequirementsInput {
  required?: (string | string[])[]
  preferred?: string[]
  excluded?: string[]
  evidence?: string[]
  preferred_evidence?: string[]
  role?: string | null
  seniority?: string | null
  location?: string | null
  remote?: boolean
}

export interface RequirementChip {
  display: string
  concepts: string[]
}

export interface EvidenceChip {
  key: string
  display: string
}

export interface RequirementsView {
  required: RequirementChip[]
  preferred: RequirementChip[]
  excluded: RequirementChip[]
  evidence: EvidenceChip[]
  preferred_evidence: EvidenceChip[]
  role: string | null
  seniority: string | null
  location: string | null
  remote: boolean
  unrecognized_terms: string[]
}

export interface BriefStatusCounts {
  saved: number
  reviewing: number
  shortlisted: number
  contacted: number
  interview: number
  decision: number
  hired: number
  passed: number
  archived: number
}

export interface HiringBrief {
  id: string
  title: string
  role_text: string | null
  status: BriefStatus
  requirements_view: RequirementsView
  candidate_count: number
  status_counts: BriefStatusCounts
  created_at: string | null
  updated_at: string | null
}

export interface HiringBriefListItem {
  id: string
  title: string
  role: string | null
  status: BriefStatus
  candidate_count: number
  shortlisted_count: number
  created_at: string | null
  updated_at: string | null
}

export interface BriefCandidateIdentity {
  display_name: string | null
  headline: string | null
  summary: string | null
  availability_label: string | null
  location: string | null
  role_areas: string[]
  public_slug: string | null
  is_published: boolean
}

export interface BriefColumnCounts {
  required_proven: number
  required_claimed: number
  required_total: number
  preferred_proven: number
  preferred_claimed: number
  preferred_total: number
}

export interface BriefCandidateEvaluation {
  available: boolean
  counts: BriefColumnCounts
  missing_required: string[]
  missing_preferred: string[]
  excluded_hits: string[]
}

export interface BriefCandidate {
  student_user_id: string
  status: BriefCandidateStatus
  note: string | null
  connection_id: string | null
  candidate: BriefCandidateIdentity
  evaluation: BriefCandidateEvaluation | null
  added_at: string | null
  updated_at: string | null
}

export interface BriefCandidatesResponse {
  candidates: BriefCandidate[]
  total: number
  status_counts: BriefStatusCounts
}

export interface AddBriefCandidatesResult {
  added: number
  already_in_brief: number
  candidates: BriefCandidate[]
}

/** Matrix payloads — closed cell states, transparent counts, never a score. */
export interface MatrixCellProjectRef {
  title: string | null
  public_report_path: string | null
  skill_status: string | null
  proof_types: string[]
}

export interface MatrixCellTrace {
  source_type: string | null
  source_title: string | null
  summary: string | null
  public_url: string | null
}

export type MatrixCellState = "proven" | "claimed" | "none" | "unavailable"

export interface MatrixCell {
  state: MatrixCellState
  matched_label: string | null
  skill_status: string | null
  direct: boolean
  evidence_sources: string[]
  project_titles: string[]
  note: string | null
  proof_path: string | null
  projects: MatrixCellProjectRef[]
  traces: MatrixCellTrace[]
  related: string[]
}

export interface MatrixRequirement {
  key: string
  kind: "concept" | "evidence"
  display: string
  required: boolean
  concepts: string[]
}

export interface MatrixColumn {
  user_id: string
  available: boolean
  public_slug: string | null
  display_name: string | null
  headline: string | null
  availability_label: string | null
  passport_path: string | null
  cells: Record<string, MatrixCell>
  counts: BriefColumnCounts
  missing_required: string[]
  missing_preferred: string[]
  excluded_hits: string[]
  unavailable_note: string | null
  connection: { id: string } | null
  brief_status: BriefCandidateStatus | null
}

export interface RequirementCoverage {
  key: string
  display: string
  required: boolean
  proven_count: number
  claimed_count: number
  candidate_total: number
}

export interface ComparisonMatrix {
  requirements: MatrixRequirement[]
  columns: MatrixColumn[]
  coverage: RequirementCoverage[]
  summaries: string[]
  notes: string[]
  requirements_view: RequirementsView
}

export interface BriefComparisonResponse {
  brief: HiringBriefListItem
  matrix: ComparisonMatrix
}

/**
 * A non-OK Hiring Briefs API response, carrying the machine-readable
 * `detail.code` (e.g. "too_few_candidates") alongside the human message so
 * views can branch on WHY a request failed instead of pattern-matching
 * error prose. `code` is null when the API sent no structured code.
 */
export class BriefApiError extends Error {
  code: string | null

  constructor(message: string, code: string | null = null) {
    super(message)
    this.name = "BriefApiError"
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
    throw new BriefApiError(message, code)
  }
  return res.json() as Promise<T>
}

/** The recruiter's Hiring Briefs, most recently updated first. */
export async function listBriefs(): Promise<HiringBriefListItem[]> {
  const body = await request<{ briefs?: HiringBriefListItem[] }>(
    "/api/v1/recruiter/briefs",
    undefined,
    "Failed to load hiring briefs.",
  )
  return body.briefs ?? []
}

/** Create a brief from role text and/or edited requirement chips. */
export async function createBrief(params: {
  title?: string | null
  role_text?: string | null
  requirements?: RequirementsInput | null
  status?: BriefStatus
}): Promise<HiringBrief> {
  const body = await request<{ brief: HiringBrief }>(
    "/api/v1/recruiter/briefs",
    { method: "POST", body: JSON.stringify(params) },
    "Failed to create the hiring brief.",
  )
  return body.brief
}

export async function getBrief(briefId: string): Promise<HiringBrief> {
  const body = await request<{ brief: HiringBrief }>(
    `/api/v1/recruiter/briefs/${encodeURIComponent(briefId)}`,
    undefined,
    "Failed to load the hiring brief.",
  )
  return body.brief
}

/** Partial update: title / role text / requirements / lifecycle status. */
export async function updateBrief(
  briefId: string,
  params: {
    title?: string | null
    role_text?: string | null
    requirements?: RequirementsInput | null
    status?: BriefStatus
  },
): Promise<HiringBrief> {
  const body = await request<{ brief: HiringBrief }>(
    `/api/v1/recruiter/briefs/${encodeURIComponent(briefId)}`,
    { method: "PATCH", body: JSON.stringify(params) },
    "Failed to update the hiring brief.",
  )
  return body.brief
}

export async function deleteBrief(briefId: string): Promise<void> {
  await request<{ deleted: boolean }>(
    `/api/v1/recruiter/briefs/${encodeURIComponent(briefId)}`,
    { method: "DELETE" },
    "Failed to delete the hiring brief.",
  )
}

/** The brief's role-scoped pool, with live per-candidate evaluation. */
export async function listBriefCandidates(
  briefId: string,
): Promise<BriefCandidatesResponse> {
  return request<BriefCandidatesResponse>(
    `/api/v1/recruiter/briefs/${encodeURIComponent(briefId)}/candidates`,
    undefined,
    "Failed to load the role's candidates.",
  )
}

/** Idempotently add workspace connections and/or published slugs. */
export async function addBriefCandidates(
  briefId: string,
  params: { connection_ids?: string[]; candidate_slugs?: string[] },
): Promise<AddBriefCandidatesResult> {
  return request<AddBriefCandidatesResult>(
    `/api/v1/recruiter/briefs/${encodeURIComponent(briefId)}/candidates`,
    { method: "POST", body: JSON.stringify(params) },
    "Failed to add candidates to the role.",
  )
}

/** Update one candidate's ROLE-SCOPED status / private note. */
export async function updateBriefCandidate(
  briefId: string,
  studentUserId: string,
  params: { status?: BriefCandidateStatus; note?: string; clear_note?: boolean },
): Promise<BriefCandidate> {
  const body = await request<{ candidate: BriefCandidate }>(
    `/api/v1/recruiter/briefs/${encodeURIComponent(briefId)}/candidates/${encodeURIComponent(studentUserId)}`,
    { method: "PATCH", body: JSON.stringify(params) },
    "Failed to update the candidate.",
  )
  return body.candidate
}

export async function removeBriefCandidate(
  briefId: string,
  studentUserId: string,
): Promise<void> {
  await request<{ removed: boolean }>(
    `/api/v1/recruiter/briefs/${encodeURIComponent(briefId)}/candidates/${encodeURIComponent(studentUserId)}`,
    { method: "DELETE" },
    "Failed to remove the candidate from the role.",
  )
}

/**
 * The brief's live evidence matrix. `candidateUserIds` selects 2–5 pool
 * members; omitted, the pool's non-archived candidates are compared.
 */
export async function getBriefComparison(
  briefId: string,
  candidateUserIds?: string[],
): Promise<BriefComparisonResponse> {
  const query = candidateUserIds?.length
    ? `?candidates=${encodeURIComponent(candidateUserIds.join(","))}`
    : ""
  return request<BriefComparisonResponse>(
    `/api/v1/recruiter/briefs/${encodeURIComponent(briefId)}/comparison${query}`,
    undefined,
    "Failed to load the comparison.",
  )
}

// ── Interview workspace (V4) ─────────────────────────────────────────────
//
// Everything below is RECRUITER-PRIVATE hiring context: prep/interview/
// decision notes, per-requirement interview marks, generated questions and
// the activity trail are never candidate-visible and never become public
// evidence. The checklist itself is recomputed live from PUBLISHED evidence
// on every load (fail-closed) — nothing is snapshotted.

export type InterviewMarkState = "discussed" | "verified" | "follow_up"

export interface InterviewMark {
  requirement_key: string
  state: InterviewMarkState
  marked_at: string | null
}

/** The live, deterministic verification checklist for one (brief, candidate). */
export interface InterviewChecklist {
  requirements: MatrixRequirement[]
  cells: Record<string, MatrixCell>
  counts: BriefColumnCounts
  available: boolean
  unavailable_note: string | null
  summary: string
}

export interface InterviewRecord {
  scheduled_at: string | null
  interviewer_name: string | null
  prep_notes: string | null
  notes: string | null
  decision_notes: string | null
  updated_at: string | null
}

export interface InterviewQuestionGrounding {
  requirement_display: string
  state: MatrixCellState
  matched_label: string | null
  evidence_sources: string[]
  project_titles: string[]
  proof_path: string | null
}

export interface InterviewQuestion {
  id: string
  requirement_key: string
  /** "evidence" = grounded in published proof; "gap" = verify in interview. */
  kind: "evidence" | "gap"
  question: string
  grounding: InterviewQuestionGrounding
  /** False when the cited evidence is no longer published (re-graded on load). */
  evidence_available: boolean
}

export interface InterviewQuestions {
  items: InterviewQuestion[]
  source: "llm" | "deterministic"
  generated_at: string | null
  fallback_reason: string | null
}

export interface InterviewActivityEvent {
  event_type: string
  detail: Record<string, unknown>
  created_at: string | null
}

export interface InterviewWorkspace {
  brief: HiringBriefListItem
  candidate: BriefCandidateIdentity
  pool_status: BriefCandidateStatus
  checklist: InterviewChecklist
  marks: InterviewMark[]
  interview: InterviewRecord | null
  questions: InterviewQuestions | null
  activity: InterviewActivityEvent[]
}

/** Partial update over the interview row; `clear_*` empties a field. */
export interface InterviewPatch {
  scheduled_at?: string
  interviewer_name?: string
  prep_notes?: string
  notes?: string
  decision_notes?: string
  clear_scheduled_at?: boolean
  clear_interviewer_name?: boolean
  clear_prep_notes?: boolean
  clear_notes?: boolean
  clear_decision_notes?: boolean
}

function interviewPath(briefId: string, studentUserId: string, suffix = ""): string {
  return `/api/v1/recruiter/briefs/${encodeURIComponent(briefId)}/candidates/${encodeURIComponent(studentUserId)}/interview${suffix}`
}

/** The full interview workspace: live checklist, marks, notes, questions, activity. */
export async function getInterviewWorkspace(
  briefId: string,
  studentUserId: string,
): Promise<InterviewWorkspace> {
  return request<InterviewWorkspace>(
    interviewPath(briefId, studentUserId),
    undefined,
    "Failed to load the interview workspace.",
  )
}

/** Autosave-friendly partial upsert of the recruiter-private interview row. */
export async function updateInterview(
  briefId: string,
  studentUserId: string,
  patch: InterviewPatch,
): Promise<InterviewRecord> {
  const body = await request<{ interview: InterviewRecord } | InterviewRecord>(
    interviewPath(briefId, studentUserId),
    { method: "PATCH", body: JSON.stringify(patch) },
    "Failed to save interview notes.",
  )
  return "interview" in body ? body.interview : body
}

/**
 * Generate (or return stored, unless `regenerate`) evidence-grounded
 * interview questions. LLM failure degrades silently to the deterministic
 * set with an honest `fallback_reason` — never an error.
 */
export async function generateInterviewQuestions(
  briefId: string,
  studentUserId: string,
  params: { regenerate?: boolean } = {},
): Promise<InterviewQuestions> {
  const body = await request<{ questions: InterviewQuestions } | InterviewQuestions>(
    interviewPath(briefId, studentUserId, "/questions"),
    { method: "POST", body: JSON.stringify(params) },
    "Failed to generate interview questions.",
  )
  return "questions" in body ? body.questions : body
}

/**
 * Set (or clear, with state null) one recruiter-private checklist mark.
 * Body, not path param — requirement keys contain `:` and `|`.
 * Returns the updated marks list.
 */
export async function setChecklistMark(
  briefId: string,
  studentUserId: string,
  params: { requirement_key: string; state: InterviewMarkState | null },
): Promise<InterviewMark[]> {
  const body = await request<{ marks: InterviewMark[] } | InterviewMark[]>(
    interviewPath(briefId, studentUserId, "/checklist"),
    { method: "POST", body: JSON.stringify(params) },
    "Failed to save the checklist mark.",
  )
  return Array.isArray(body) ? body : (body.marks ?? [])
}

/**
 * Search candidates with the brief's stored requirement plan. `q` is a
 * TEMPORARY refinement overlay — it never modifies the stored brief.
 */
export async function briefSearch(
  briefId: string,
  params: {
    q?: string
    availability?: AvailabilityFilter | null
    page?: number
    pageSize?: number
  } = {},
): Promise<RecruiterSearchResponse> {
  const query = new URLSearchParams()
  if (params.q?.trim()) query.set("q", params.q.trim())
  if (params.availability) query.set("availability", params.availability)
  if (params.page && params.page > 1) query.set("page", String(params.page))
  if (params.pageSize) query.set("page_size", String(params.pageSize))
  const suffix = query.toString()
  return request<RecruiterSearchResponse>(
    `/api/v1/recruiter/briefs/${encodeURIComponent(briefId)}/search${suffix ? `?${suffix}` : ""}`,
    undefined,
    "Search failed.",
  )
}
