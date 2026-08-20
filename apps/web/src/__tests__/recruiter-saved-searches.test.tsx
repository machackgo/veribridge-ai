/**
 * Saved Searches UI — list + detail.
 *
 * Covers: list rows (new/updated badges, paused state, tracking-disabled
 * honesty line, delete confirm copy, empty state) and the detail view
 * (exact vs close sections, New / Updated-evidence badges from the API
 * annotations, mark-reviewed, paused banner, inline rename).
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/recruiter-saved-searches-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/recruiter-saved-searches-api")>()),
  listSavedSearches: vi.fn(),
  getSavedSearchResults: vi.fn(),
  updateSavedSearch: vi.fn(),
  markSavedSearchReviewed: vi.fn(),
  deleteSavedSearch: vi.fn(),
}))

vi.mock("@/lib/recruiter-connections-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/recruiter-connections-api")>()),
  saveCandidate: vi.fn(),
}))

vi.mock("@/lib/recruiter-pools-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/recruiter-pools-api")>()),
  listPools: vi.fn(),
  addPoolCandidates: vi.fn(),
  createPool: vi.fn(),
}))

vi.mock("@/lib/recruiter-briefs-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/recruiter-briefs-api")>()),
  listBriefs: vi.fn(),
  addBriefCandidates: vi.fn(),
}))

import { addPoolCandidates, listPools, type TalentPool } from "@/lib/recruiter-pools-api"
import {
  deleteSavedSearch,
  getSavedSearchResults,
  listSavedSearches,
  markSavedSearchReviewed,
  updateSavedSearch,
  type SavedSearchListItem,
  type SavedSearchResults,
} from "@/lib/recruiter-saved-searches-api"
import type {
  QueryInterpretation,
  RequirementMatch,
  SearchResultCandidate,
} from "@/lib/recruiter-search-api"
import { SavedSearchesListView } from "../app/recruiters/saved-searches/SavedSearchesListView"
import { SavedSearchDetailView } from "../app/recruiters/saved-searches/[searchId]/SavedSearchDetailView"

const mockList = vi.mocked(listSavedSearches)
const mockResults = vi.mocked(getSavedSearchResults)
const mockUpdate = vi.mocked(updateSavedSearch)
const mockReview = vi.mocked(markSavedSearchReviewed)
const mockDelete = vi.mocked(deleteSavedSearch)
const mockListPools = vi.mocked(listPools)
const mockAddPoolCandidates = vi.mocked(addPoolCandidates)

const REQUIREMENTS = {
  required: [
    { display: "Python", concepts: ["python"] },
    { display: "FastAPI", concepts: ["fastapi"] },
  ],
  preferred: [],
  excluded: [],
  evidence: [],
  preferred_evidence: [],
  role: null,
  seniority: null,
  location: null,
  remote: false,
  unrecognized_terms: [],
}

const ITEM: SavedSearchListItem = {
  id: "ss-1",
  name: "Python, FastAPI",
  query_text: "Python and FastAPI are required.",
  status: "active",
  requirements: REQUIREMENTS,
  tracking: true,
  new_count: 2,
  updated_count: 1,
  match_count: 4,
  last_evaluated_at: new Date().toISOString(),
  last_reviewed_at: "2026-08-18T00:00:00+00:00",
  created_at: "2026-08-10T00:00:00+00:00",
  updated_at: "2026-08-18T00:00:00+00:00",
}

const PAUSED_ITEM: SavedSearchListItem = {
  ...ITEM,
  id: "ss-2",
  name: "Paused search",
  status: "paused",
  new_count: null,
  updated_count: null,
  match_count: null,
}

const UNTRACKED_ITEM: SavedSearchListItem = {
  ...ITEM,
  id: "ss-3",
  name: "creative generalist",
  requirements: { ...REQUIREMENTS, required: [] },
  tracking: false,
  new_count: 0,
  updated_count: 0,
  match_count: 0,
}

function requirementRow(display: string, satisfied = true): RequirementMatch {
  return {
    kind: "concept",
    requirement: display.toLowerCase(),
    display,
    required: true,
    satisfied,
    via: satisfied ? "skill" : null,
    matched_label: satisfied ? display : null,
    skill_status: satisfied ? "Demonstrated" : null,
    evidence_sources: satisfied ? ["GitHub Proof"] : [],
    project_titles: [],
    note: satisfied ? null : `No published ${display} evidence`,
  }
}

function candidate(
  slug: string,
  name: string,
  matchType: "exact" | "close",
): SearchResultCandidate {
  return {
    match_type: matchType,
    requirements: [
      requirementRow("Python"),
      requirementRow("FastAPI", matchType === "exact"),
    ],
    missing_requirements: matchType === "close" ? ["FastAPI"] : [],
    public_slug: slug,
    display_name: name,
    headline: "Student engineer",
    location: null,
    availability_label: null,
    institution: null,
    degree: null,
    graduation_year: null,
    role_areas: [],
    skills: [],
    skill_count: 2,
    project_count: 1,
    projects: [],
    evidence_flags: {},
    matched_reasons: [],
    passport_published_at: null,
    in_brief: false,
    brief_status: null,
  }
}

const INTERPRETATION: QueryInterpretation = {
  mode: "structured",
  intent: "candidate_search",
  required: REQUIREMENTS.required,
  preferred: [],
  excluded: [],
  evidence: [],
  preferred_evidence: [],
  role: null,
  seniority: null,
  location: null,
  remote: false,
  residual_terms: ["rockstar"],
}

const RESULTS: SavedSearchResults = {
  saved_search: ITEM,
  results: [
    candidate("delta", "Delta Candidate", "exact"),
    candidate("alpha", "Alpha Candidate", "exact"),
    candidate("bravo", "Bravo Candidate", "close"),
  ],
  total: 3,
  exact_total: 2,
  close_total: 1,
  page: 1,
  page_size: 10,
  has_more: false,
  interpretation: INTERPRETATION,
  annotations: {
    delta: {
      is_new: true,
      evidence_updated: false,
      changed_requirements: [],
      first_matched_at: "2026-08-19T00:00:00+00:00",
    },
    alpha: {
      is_new: false,
      evidence_updated: true,
      changed_requirements: ["FastAPI"],
      first_matched_at: "2026-08-10T00:00:00+00:00",
    },
  },
  truncated: false,
}

beforeEach(() => {
  vi.clearAllMocks()
  mockList.mockResolvedValue([ITEM, PAUSED_ITEM, UNTRACKED_ITEM])
  mockResults.mockResolvedValue(RESULTS)
})

describe("SavedSearchesListView", () => {
  it("renders rows with query, chips, badges and checked line", async () => {
    render(<SavedSearchesListView />)
    const cards = await screen.findAllByTestId("savedsearch-card")
    const active = cards[0]
    expect(within(active).getByTestId("savedsearch-card-name")).toHaveTextContent(
      "Python, FastAPI",
    )
    expect(within(active).getByText("“Python and FastAPI are required.”")).toBeInTheDocument()
    expect(within(active).getByTestId("savedsearch-new-count")).toHaveTextContent("2 new")
    expect(within(active).getByTestId("savedsearch-updated-count")).toHaveTextContent(
      "1 updated evidence",
    )
    expect(within(active).getByText(/Checked/)).toBeInTheDocument()
    expect(within(active).getByTestId("savedsearch-open")).toHaveAttribute(
      "href",
      "/recruiters/saved-searches/ss-1",
    )
  })

  it("paused rows omit counts and offer Resume", async () => {
    mockUpdate.mockResolvedValue({ ...PAUSED_ITEM, status: "active", new_count: 0, updated_count: 0, match_count: 4 })
    render(<SavedSearchesListView />)
    const cards = await screen.findAllByTestId("savedsearch-card")
    const paused = cards[1]
    expect(within(paused).getByText("Paused")).toBeInTheDocument()
    expect(within(paused).queryByTestId("savedsearch-new-count")).not.toBeInTheDocument()
    fireEvent.click(within(paused).getByTestId("savedsearch-resume"))
    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith("ss-2", { status: "active" }),
    )
  })

  it("pauses an active search", async () => {
    mockUpdate.mockResolvedValue({ ...ITEM, status: "paused", new_count: null, updated_count: null, match_count: null })
    render(<SavedSearchesListView />)
    const cards = await screen.findAllByTestId("savedsearch-card")
    fireEvent.click(within(cards[0]).getByTestId("savedsearch-pause"))
    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith("ss-1", { status: "paused" }),
    )
  })

  it("says honestly when a search tracks nothing", async () => {
    render(<SavedSearchesListView />)
    const cards = await screen.findAllByTestId("savedsearch-card")
    expect(within(cards[2]).getByTestId("savedsearch-untracked")).toHaveTextContent(
      "Add a required skill or evidence type to track new candidates.",
    )
  })

  it("delete requires confirmation with the never-removes copy", async () => {
    mockDelete.mockResolvedValue(undefined)
    render(<SavedSearchesListView />)
    const cards = await screen.findAllByTestId("savedsearch-card")
    fireEvent.click(within(cards[0]).getByTestId("savedsearch-delete"))
    expect(screen.getByTestId("savedsearch-delete-confirm")).toHaveTextContent(
      "Deleting this saved search never removes candidates, Talent Pools, or Hiring Briefs.",
    )
    expect(mockDelete).not.toHaveBeenCalled()
    fireEvent.click(within(cards[0]).getByTestId("savedsearch-delete"))
    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith("ss-1"))
  })

  it("shows the empty state", async () => {
    mockList.mockResolvedValue([])
    render(<SavedSearchesListView />)
    expect(await screen.findByTestId("savedsearches-empty")).toHaveTextContent(
      "Save a recruiter search to be notified when new published evidence satisfies your requirements.",
    )
  })
})

describe("SavedSearchDetailView", () => {
  it("renders exact and close sections with honest annotations", async () => {
    render(<SavedSearchDetailView searchId="ss-1" />)
    expect(await screen.findByTestId("savedsearch-title")).toHaveTextContent("Python, FastAPI")
    expect(screen.getByTestId("savedsearch-section-exact")).toHaveTextContent("Exact matches (2)")
    expect(screen.getByTestId("savedsearch-section-close")).toHaveTextContent(
      "Close matches — missing requirements shown",
    )
    const cards = screen.getAllByTestId("savedsearch-result-card")
    expect(cards).toHaveLength(3)
    // Delta is NEW; Alpha has updated evidence naming the requirement.
    expect(within(cards[0]).getByTestId("savedsearch-badge-new")).toHaveTextContent("New")
    expect(within(cards[0]).getByTestId("savedsearch-result-counts")).toHaveTextContent(
      "Satisfies all 2 required requirements",
    )
    expect(within(cards[1]).getByTestId("savedsearch-badge-updated")).toHaveTextContent(
      "Updated evidence: FastAPI",
    )
    // Close card: no tracking badges, missing requirement stated.
    expect(within(cards[2]).queryByTestId("savedsearch-badge-new")).not.toBeInTheDocument()
    expect(within(cards[2]).getByTestId("savedsearch-result-missing")).toHaveTextContent(
      "Missing: FastAPI",
    )
    // Residual honesty line.
    expect(screen.getByTestId("savedsearch-residual-terms")).toHaveTextContent(
      "Not understood (never silently used): rockstar",
    )
  })

  it("marks reviewed through the API and clears badges", async () => {
    mockReview.mockResolvedValue({ ...ITEM, new_count: 0, updated_count: 0 })
    render(<SavedSearchDetailView searchId="ss-1" />)
    await screen.findByTestId("savedsearch-title")
    fireEvent.click(screen.getByTestId("savedsearch-mark-reviewed"))
    await waitFor(() => expect(mockReview).toHaveBeenCalledWith("ss-1"))
    await waitFor(() =>
      expect(screen.queryByTestId("savedsearch-badge-new")).not.toBeInTheDocument(),
    )
  })

  it("shows the paused banner and no annotations while paused", async () => {
    mockResults.mockResolvedValue({
      ...RESULTS,
      saved_search: { ...ITEM, status: "paused", new_count: null, updated_count: null, match_count: null },
      annotations: {},
    })
    render(<SavedSearchDetailView searchId="ss-1" />)
    expect(await screen.findByTestId("savedsearch-paused-banner")).toHaveTextContent(
      "Paused — not tracking new candidates",
    )
    expect(screen.queryByTestId("savedsearch-badge-new")).not.toBeInTheDocument()
    expect(screen.queryByTestId("savedsearch-mark-reviewed")).not.toBeInTheDocument()
  })

  it("renames inline", async () => {
    mockUpdate.mockResolvedValue({ ...ITEM, name: "Platform watch" })
    render(<SavedSearchDetailView searchId="ss-1" />)
    await screen.findByTestId("savedsearch-title")
    fireEvent.click(screen.getByTestId("savedsearch-rename"))
    fireEvent.change(screen.getByTestId("savedsearch-rename-input"), {
      target: { value: "Platform watch" },
    })
    fireEvent.click(screen.getByTestId("savedsearch-rename-save"))
    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith("ss-1", { name: "Platform watch" }),
    )
    expect(await screen.findByTestId("savedsearch-title")).toHaveTextContent("Platform watch")
  })

  it("shows the honest empty state when nothing satisfies the search", async () => {
    mockResults.mockResolvedValue({
      ...RESULTS,
      results: [],
      total: 0,
      exact_total: 0,
      close_total: 0,
      annotations: {},
    })
    render(<SavedSearchDetailView searchId="ss-1" />)
    expect(await screen.findByTestId("savedsearch-results-empty")).toHaveTextContent(
      "No published evidence-backed candidates satisfy this search yet.",
    )
  })

  it("adds an exact match to a pool with source saved_search", async () => {
    const pool: TalentPool = {
      id: "pool-1",
      name: "AI / ML Early Talent",
      description: null,
      status: "active",
      candidate_count: 0,
      created_at: null,
      updated_at: null,
    }
    mockListPools.mockResolvedValue([pool])
    mockAddPoolCandidates.mockResolvedValue({ added: 1, already_in_pool: 0, candidates: [] })
    render(<SavedSearchDetailView searchId="ss-1" />)
    await screen.findByTestId("savedsearch-title")
    const first = screen.getAllByTestId("savedsearch-result-card")[0]
    fireEvent.click(within(first).getByTestId("add-to-pool"))
    fireEvent.click(await within(first).findByTestId("add-to-pool-option"))
    await waitFor(() =>
      expect(mockAddPoolCandidates).toHaveBeenCalledWith("pool-1", {
        candidate_slugs: ["delta"],
        source: "saved_search",
      }),
    )
    expect(await within(first).findByText("Added ✓")).toBeInTheDocument()
  })
})
