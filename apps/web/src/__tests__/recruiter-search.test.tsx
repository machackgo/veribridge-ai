/**
 * RecruiterSearchView — Recruiter Search & Discovery.
 *
 * Covers: initial browse listing, query submit, evidence-explained result
 * cards (real data only — no scores), Save Candidate through the existing
 * connection API with source="search", saved-state marks, clear/zero-result/
 * error states, and load-more pagination.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react"
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

import {
  listConnections,
  saveCandidate,
} from "@/lib/recruiter-connections-api"
import {
  searchCandidates,
  type RecruiterSearchResponse,
  type SearchResultCandidate,
} from "@/lib/recruiter-search-api"
import { RecruiterSearchView } from "../app/recruiters/search/RecruiterSearchView"

const mockSearch = vi.mocked(searchCandidates)
const mockList = vi.mocked(listConnections)
const mockSave = vi.mocked(saveCandidate)

const CANDIDATE: SearchResultCandidate = {
  public_slug: "ada-slug",
  display_name: "Ada Lovelace",
  headline: "Backend Engineer",
  location: "London",
  availability_label: "Seeking internship",
  institution: "WPI",
  degree: "M.S. Computer Science",
  graduation_year: 2026,
  role_areas: ["Backend"],
  skills: [
    {
      skill: "Python",
      status: "Demonstrated",
      evidence_sources: ["GitHub Proof", "Website Proof"],
      matched: true,
    },
  ],
  skill_count: 1,
  project_count: 1,
  projects: [
    {
      title: "Deployment API",
      public_report_path: "/vbr/report/tok123",
      evidence_sources: ["GitHub Proof"],
      has_live_url: true,
    },
  ],
  evidence_flags: { github: true, live_site: true },
  matched_reasons: [],
  passport_published_at: "2026-06-01T00:00:00+00:00",
}

function response(
  results: SearchResultCandidate[],
  overrides: Partial<RecruiterSearchResponse> = {},
): RecruiterSearchResponse {
  return {
    results,
    total: results.length,
    page: 1,
    page_size: 10,
    has_more: false,
    query: { q: "", terms: [], skills: [], evidence: [], availability: null },
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockList.mockResolvedValue([])
  mockSearch.mockResolvedValue(response([CANDIDATE]))
  mockSave.mockResolvedValue({
    id: "conn-1",
    source: "search",
    created_at: "2026-08-16T00:00:00+00:00",
    saved: true,
    already_saved: false,
    candidate: {
      display_name: "Ada Lovelace",
      headline: null,
      summary: null,
      availability_label: null,
      location: null,
      role_areas: [],
      public_slug: "ada-slug",
      is_published: true,
    },
  })
})

describe("RecruiterSearchView", () => {
  it("loads the discoverable population on mount and renders evidence-backed cards", async () => {
    render(<RecruiterSearchView />)

    const card = await screen.findByTestId("search-result-card")
    expect(card).toBeInTheDocument()
    expect(mockSearch).toHaveBeenCalledWith(
      expect.objectContaining({ q: "", page: 1 }),
    )
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument()
    expect(screen.getByTestId("search-result-count")).toHaveTextContent(
      "1 candidate with a published Work Passport",
    )
    // Browse mode (no query): evidence-backed skills, qualitative only.
    expect(screen.getByTestId("search-result-skills")).toHaveTextContent(
      "✓ Python — Demonstrated",
    )
    expect(screen.getByTestId("search-result-open")).toHaveAttribute(
      "href",
      "/p/ada-slug",
    )
    // No scores or percentages anywhere.
    expect(document.body.textContent).not.toMatch(/\d+\s*%/)
  })

  it("submits a query and renders match explanations", async () => {
    render(<RecruiterSearchView />)
    await screen.findByTestId("search-result-card")

    mockSearch.mockResolvedValue(
      response(
        [
          {
            ...CANDIDATE,
            matched_reasons: [
              {
                type: "skill",
                label: "Python",
                term: "python",
                skill_status: "Demonstrated",
                evidence_sources: ["GitHub Proof"],
              },
              {
                type: "technology",
                label: "FastAPI",
                term: "fastapi",
                project_title: "Deployment API",
              },
            ],
          },
        ],
        { query: { q: "python fastapi", terms: ["python", "fastapi"], skills: [], evidence: [], availability: null } },
      ),
    )

    fireEvent.change(screen.getByTestId("search-input"), {
      target: { value: "python fastapi" },
    })
    fireEvent.click(screen.getByTestId("search-submit"))

    const reasons = await screen.findByTestId("search-result-reasons")
    expect(reasons).toHaveTextContent("Match evidence")
    expect(reasons).toHaveTextContent("✓ Python — Demonstrated · GitHub Proof")
    expect(reasons).toHaveTextContent("FastAPI — used in Deployment API (claimed)")
    expect(mockSearch).toHaveBeenLastCalledWith(
      expect.objectContaining({ q: "python fastapi" }),
    )
    expect(screen.getByTestId("search-result-count")).toHaveTextContent(
      "matching “python fastapi”",
    )
  })

  it("saves a result through the existing connection API with source=search", async () => {
    render(<RecruiterSearchView />)
    await screen.findByTestId("search-result-card")

    fireEvent.click(screen.getByTestId("search-result-save"))

    await screen.findByTestId("search-result-saved")
    expect(mockSave).toHaveBeenCalledWith("ada-slug", "search", {
      passport_slug: "ada-slug",
    })
  })

  it("marks already-saved candidates from the workspace listing", async () => {
    mockList.mockResolvedValue([
      {
        id: "conn-1",
        source: "qr_scan",
        created_at: null,
        candidate: {
          display_name: "Ada Lovelace",
          headline: null,
          summary: null,
          availability_label: null,
          location: null,
          role_areas: [],
          public_slug: "ada-slug",
          is_published: true,
        },
      },
    ])
    render(<RecruiterSearchView />)
    await screen.findByTestId("search-result-card")
    await screen.findByTestId("search-result-saved")
    expect(screen.queryByTestId("search-result-save")).not.toBeInTheDocument()
  })

  it("shows the save error state without losing the retry CTA", async () => {
    mockSave.mockRejectedValue(new Error("Network down"))
    render(<RecruiterSearchView />)
    await screen.findByTestId("search-result-card")

    fireEvent.click(screen.getByTestId("search-result-save"))
    await screen.findByTestId("search-result-save-error")
    expect(screen.getByTestId("search-result-save")).toBeInTheDocument()
  })

  it("renders the zero-result state with a clear action", async () => {
    render(<RecruiterSearchView />)
    await screen.findByTestId("search-result-card")

    mockSearch.mockResolvedValue(
      response([], {
        query: { q: "nope", terms: ["nope"], skills: [], evidence: [], availability: null },
      }),
    )
    fireEvent.change(screen.getByTestId("search-input"), { target: { value: "nope" } })
    fireEvent.click(screen.getByTestId("search-submit"))

    await screen.findByTestId("search-empty")
    expect(screen.getByText(/no candidates match this search/i)).toBeInTheDocument()

    // Clearing re-runs the browse listing.
    mockSearch.mockResolvedValue(response([CANDIDATE]))
    fireEvent.click(screen.getByTestId("search-clear"))
    await screen.findByTestId("search-result-card")
    expect(mockSearch).toHaveBeenLastCalledWith(expect.objectContaining({ q: "" }))
  })

  it("renders the empty discoverable population honestly", async () => {
    mockSearch.mockResolvedValue(response([]))
    render(<RecruiterSearchView />)
    await screen.findByTestId("search-empty")
    expect(
      screen.getByText(/no discoverable candidates yet/i),
    ).toBeInTheDocument()
  })

  it("shows the error state and recovers on retry", async () => {
    mockSearch.mockRejectedValueOnce(new Error("API unavailable"))
    render(<RecruiterSearchView />)
    await screen.findByText("API unavailable")

    mockSearch.mockResolvedValue(response([CANDIDATE]))
    fireEvent.click(screen.getByRole("button", { name: /try again|retry/i }))
    await screen.findByTestId("search-result-card")
  })

  it("toggles evidence filters and forwards them to the API", async () => {
    render(<RecruiterSearchView />)
    await screen.findByTestId("search-result-card")

    fireEvent.click(screen.getByTestId("search-filter-live_site"))
    await waitFor(() =>
      expect(mockSearch).toHaveBeenLastCalledWith(
        expect.objectContaining({ evidence: ["live_site"] }),
      ),
    )
    expect(screen.getByTestId("search-filter-live_site")).toHaveAttribute(
      "aria-pressed",
      "true",
    )
  })

  it("loads more results when has_more", async () => {
    mockSearch.mockResolvedValue(
      response([CANDIDATE], { has_more: true, total: 2 }),
    )
    render(<RecruiterSearchView />)
    await screen.findByTestId("search-load-more")

    const second: SearchResultCandidate = { ...CANDIDATE, public_slug: "ben-slug", display_name: "Ben Osei" }
    mockSearch.mockResolvedValue(
      response([second], { page: 2, total: 2, has_more: false }),
    )
    fireEvent.click(screen.getByTestId("search-load-more"))
    await screen.findByText("Ben Osei")
    expect(screen.getAllByTestId("search-result-card")).toHaveLength(2)
    expect(mockSearch).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 2 }),
    )
  })
})
