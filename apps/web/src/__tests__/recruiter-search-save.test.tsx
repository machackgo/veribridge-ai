/**
 * Search page — Save search flow + add-to-list actions.
 *
 * Covers: the Save search button appearing once a query-backed search has
 * completed, the panel's prefilled name and tracked-requirements summary,
 * the create payload (q + name + current filter chips), the success link
 * to the new saved search, the no-hard-requirements honesty note, and the
 * Add-to-pool action on a result card.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/recruiter-search-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/recruiter-search-api")>()),
  searchCandidates: vi.fn(),
}))

vi.mock("@/lib/recruiter-connections-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/recruiter-connections-api")>()),
  listConnections: vi.fn(),
  saveCandidate: vi.fn(),
}))

vi.mock("@/lib/recruiter-saved-searches-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/recruiter-saved-searches-api")>()),
  createSavedSearch: vi.fn(),
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

import { listConnections } from "@/lib/recruiter-connections-api"
import { addPoolCandidates, listPools, type TalentPool } from "@/lib/recruiter-pools-api"
import {
  createSavedSearch,
  type SavedSearchListItem,
} from "@/lib/recruiter-saved-searches-api"
import {
  searchCandidates,
  type QueryInterpretation,
  type RecruiterSearchResponse,
  type SearchResultCandidate,
} from "@/lib/recruiter-search-api"
import { RecruiterSearchView } from "../app/recruiters/search/RecruiterSearchView"

const mockSearch = vi.mocked(searchCandidates)
const mockListConnections = vi.mocked(listConnections)
const mockCreateSavedSearch = vi.mocked(createSavedSearch)
const mockListPools = vi.mocked(listPools)
const mockAddPoolCandidates = vi.mocked(addPoolCandidates)

const CANDIDATE: SearchResultCandidate = {
  match_type: "exact",
  requirements: [
    {
      kind: "concept",
      requirement: "python",
      display: "Python",
      required: true,
      satisfied: true,
      via: "skill",
      matched_label: "Python",
      skill_status: "Demonstrated",
      evidence_sources: ["GitHub Proof"],
      project_titles: [],
      note: null,
    },
  ],
  missing_requirements: [],
  public_slug: "ada-slug",
  display_name: "Ada Lovelace",
  headline: "Backend Engineer",
  location: null,
  availability_label: null,
  institution: null,
  degree: null,
  graduation_year: null,
  role_areas: [],
  skills: [],
  skill_count: 1,
  project_count: 1,
  projects: [],
  evidence_flags: { github: true },
  matched_reasons: [],
  passport_published_at: null,
  in_brief: false,
  brief_status: null,
}

function interpretation(
  overrides: Partial<QueryInterpretation> = {},
): QueryInterpretation {
  return {
    mode: "structured",
    intent: "candidate_search",
    required: [{ display: "Python", concepts: ["python"] }],
    preferred: [],
    excluded: [],
    evidence: [],
    preferred_evidence: [],
    role: null,
    seniority: null,
    location: null,
    remote: false,
    residual_terms: [],
    ...overrides,
  }
}

function response(
  results: SearchResultCandidate[],
  interp: QueryInterpretation,
): RecruiterSearchResponse {
  return {
    results,
    total: results.length,
    exact_total: results.filter((r) => r.match_type === "exact").length,
    close_total: results.filter((r) => r.match_type === "close").length,
    page: 1,
    page_size: 10,
    has_more: false,
    interpretation: interp,
    query: { q: "", terms: [], skills: [], evidence: [], availability: null },
  }
}

const SAVED_ITEM: SavedSearchListItem = {
  id: "ss-new",
  name: "Python",
  query_text: "Python is required.",
  status: "active",
  requirements: {
    required: [{ display: "Python", concepts: ["python"] }],
    preferred: [],
    excluded: [],
    evidence: [],
    preferred_evidence: [],
    role: null,
    seniority: null,
    location: null,
    remote: false,
    unrecognized_terms: [],
  },
  tracking: true,
  new_count: 0,
  updated_count: 0,
  match_count: 1,
  last_evaluated_at: null,
  last_reviewed_at: null,
  created_at: null,
  updated_at: null,
}

async function runQuery(query: string) {
  fireEvent.change(screen.getByTestId("search-input"), { target: { value: query } })
  fireEvent.click(screen.getByTestId("search-submit"))
  await waitFor(() => expect(screen.getByTestId("search-save-search")).toBeInTheDocument())
}

beforeEach(() => {
  vi.clearAllMocks()
  mockListConnections.mockResolvedValue([])
  // Initial browse (empty q) then the typed query.
  mockSearch.mockResolvedValue(response([CANDIDATE], interpretation()))
})

describe("Save search flow", () => {
  it("does not offer Save search on the initial browse listing", async () => {
    mockSearch.mockResolvedValue(response([CANDIDATE], interpretation({ mode: "browse", required: [] })))
    render(<RecruiterSearchView />)
    await screen.findAllByTestId("search-result-card")
    expect(screen.queryByTestId("search-save-search")).not.toBeInTheDocument()
  })

  it("opens the panel prefilled and submits q + name + filters", async () => {
    mockCreateSavedSearch.mockResolvedValue(SAVED_ITEM)
    render(<RecruiterSearchView />)
    await screen.findAllByTestId("search-result-card")
    await runQuery("Python is required.")

    fireEvent.click(screen.getByTestId("search-save-search"))
    const panel = screen.getByTestId("search-save-panel")
    // Prefilled from the interpretation's required displays.
    expect(screen.getByTestId("search-save-name")).toHaveValue("Python")
    expect(within(panel).getByText("This saved search will track:")).toBeInTheDocument()
    expect(within(panel).getByText("Python")).toBeInTheDocument()

    fireEvent.change(screen.getByTestId("search-save-name"), {
      target: { value: "Python watch" },
    })
    fireEvent.click(screen.getByTestId("search-save-submit"))
    await waitFor(() =>
      expect(mockCreateSavedSearch).toHaveBeenCalledWith({
        q: "Python is required.",
        name: "Python watch",
        filters: { evidence: [], availability: null },
      }),
    )
    const success = await screen.findByTestId("search-save-success")
    expect(success).toHaveTextContent("View saved search →")
    expect(within(success).getByRole("link")).toHaveAttribute(
      "href",
      "/recruiters/saved-searches/ss-new",
    )
  })

  it("says honestly when the search has no hard requirements", async () => {
    mockSearch.mockResolvedValue(
      response(
        [CANDIDATE],
        interpretation({ mode: "lexical", required: [], residual_terms: ["creative"] }),
      ),
    )
    render(<RecruiterSearchView />)
    await screen.findAllByTestId("search-result-card")
    await runQuery("creative")
    fireEvent.click(screen.getByTestId("search-save-search"))
    expect(screen.getByTestId("search-save-untracked-note")).toHaveTextContent(
      "This search has no required skills or evidence, so it will not track new candidates.",
    )
  })

  it("offers Add-to-pool on a result card and adds with source search", async () => {
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
    render(<RecruiterSearchView />)
    const card = (await screen.findAllByTestId("search-result-card"))[0]
    fireEvent.click(within(card).getByTestId("add-to-pool"))
    fireEvent.click(await within(card).findByTestId("add-to-pool-option"))
    await waitFor(() =>
      expect(mockAddPoolCandidates).toHaveBeenCalledWith("pool-1", {
        candidate_slugs: ["ada-slug"],
        source: "search",
      }),
    )
    expect(await within(card).findByText("Added ✓")).toBeInTheDocument()
    expect(within(card).getByTestId("add-to-brief")).toBeInTheDocument()
  })

  it("creates a new pool inline from the picker and adds to it", async () => {
    const { createPool: mockedCreatePool } = await import("@/lib/recruiter-pools-api")
    mockListPools.mockResolvedValue([])
    vi.mocked(mockedCreatePool).mockResolvedValue({
      id: "pool-new",
      name: "Fresh pool",
      description: null,
      status: "active",
      candidate_count: 0,
      created_at: null,
      updated_at: null,
    })
    mockAddPoolCandidates.mockResolvedValue({ added: 1, already_in_pool: 0, candidates: [] })
    render(<RecruiterSearchView />)
    const card = (await screen.findAllByTestId("search-result-card"))[0]
    fireEvent.click(within(card).getByTestId("add-to-pool"))
    fireEvent.change(await within(card).findByTestId("add-to-pool-new-name"), {
      target: { value: "Fresh pool" },
    })
    fireEvent.click(within(card).getByTestId("add-to-pool-create"))
    await waitFor(() =>
      expect(mockAddPoolCandidates).toHaveBeenCalledWith("pool-new", {
        candidate_slugs: ["ada-slug"],
        source: "search",
      }),
    )
    expect(await within(card).findByText("Added ✓")).toBeInTheDocument()
  })
})
