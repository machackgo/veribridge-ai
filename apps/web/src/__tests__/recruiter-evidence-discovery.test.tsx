/**
 * RecruiterSearchView — Evidence Discovery (V1.6).
 *
 * Covers: evidence-intent result rendering (proof cards, artifact links,
 * project links, trace previews), explicit zero-proof + labeled related
 * evidence, Save Candidate from a proof card, and the View-proof drawer on
 * verified requirement rows of candidate results.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/recruiter-search-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/recruiter-search-api")>()),
  searchCandidates: vi.fn(),
  viewEvidence: vi.fn(),
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
  viewEvidence,
  type EvidenceItem,
  type EvidenceResults,
  type RecruiterSearchResponse,
  type SearchResultCandidate,
} from "@/lib/recruiter-search-api"
import { RecruiterSearchView } from "../app/recruiters/search/RecruiterSearchView"

const mockSearch = vi.mocked(searchCandidates)
const mockView = vi.mocked(viewEvidence)
const mockList = vi.mocked(listConnections)
const mockSave = vi.mocked(saveCandidate)

const ML_ITEM: EvidenceItem = {
  tier: "skill",
  requirement: "machine-learning",
  requirement_display: "Machine Learning",
  related_to: null,
  skill: "Machine Learning",
  skill_slug: "machine-learning",
  status: "Demonstrated",
  direct: true,
  note: null,
  evidence_sources: ["GitHub Proof", "Document Proof"],
  proof_path: "/p/alpha/skills/machine-learning",
  projects: [
    {
      title: "Boston Risk Rerouting",
      public_report_path: "/vbr/report/tok1",
      skill_status: "Demonstrated",
      proof_types: ["GitHub Proof", "Document Proof"],
    },
  ],
  traces: [
    {
      source_type: "GitHub Proof",
      source_title: "model.py",
      summary: "Trains a gradient-boosted risk model",
      public_url: "https://github.com/x/y/blob/main/model.py",
    },
  ],
}

function evidenceResults(overrides: Partial<EvidenceResults> = {}): EvidenceResults {
  return {
    total_items: 1,
    groups: [
      {
        public_slug: "alpha",
        display_name: "Alpha Candidate",
        headline: "AI Engineer",
        passport_path: "/p/alpha",
        items: [ML_ITEM],
      },
    ],
    unmatched: [],
    related: [],
    evidence_types: [],
    candidate_filter: null,
    notes: [],
    ...overrides,
  }
}

function response(
  overrides: Partial<RecruiterSearchResponse> = {},
): RecruiterSearchResponse {
  return {
    results: [],
    total: 0,
    exact_total: 0,
    close_total: 0,
    page: 1,
    page_size: 10,
    has_more: false,
    interpretation: {
      mode: "structured",
      intent: "evidence_search",
      required: [{ display: "Machine Learning", concepts: ["machine-learning"] }],
      preferred: [],
      excluded: [],
      evidence: [],
      preferred_evidence: [],
      role: null,
      seniority: null,
      location: null,
      remote: false,
      residual_terms: [],
    },
    evidence: evidenceResults(),
    query: { q: "", terms: [], skills: [], evidence: [], availability: null },
    ...overrides,
  }
}

const BROWSE: RecruiterSearchResponse = {
  results: [],
  total: 0,
  exact_total: 0,
  close_total: 0,
  page: 1,
  page_size: 10,
  has_more: false,
  interpretation: {
    mode: "browse",
    intent: "candidate_search",
    required: [],
    preferred: [],
    excluded: [],
    evidence: [],
    preferred_evidence: [],
    role: null,
    seniority: null,
    location: null,
    remote: false,
      residual_terms: [],
  },
  query: { q: "", terms: [], skills: [], evidence: [], availability: null },
}

async function searchFor(query: string) {
  fireEvent.change(screen.getByTestId("search-input"), {
    target: { value: query },
  })
  fireEvent.click(screen.getByTestId("search-submit"))
}

beforeEach(() => {
  vi.clearAllMocks()
  mockList.mockResolvedValue([])
  mockSearch.mockResolvedValue(BROWSE)
})

describe("RecruiterSearchView — evidence discovery", () => {
  it("renders proof cards with artifact links for an evidence-intent query", async () => {
    render(<RecruiterSearchView />)
    await waitFor(() => expect(mockSearch).toHaveBeenCalled())

    mockSearch.mockResolvedValue(response())
    await searchFor("show me proof of machine learning")

    await waitFor(() =>
      expect(screen.getByTestId("evidence-results")).toBeInTheDocument(),
    )
    expect(screen.getByTestId("interpretation-intent")).toHaveTextContent(
      "Evidence search",
    )
    expect(screen.getByTestId("evidence-group-name")).toHaveTextContent(
      "Alpha Candidate",
    )
    expect(screen.getByTestId("evidence-result-count")).toHaveTextContent(
      "1 proof item",
    )
    const item = screen.getByTestId("evidence-item")
    expect(item).toHaveTextContent("Machine Learning")
    expect(item).toHaveTextContent("Demonstrated")
    expect(item).toHaveTextContent("Boston Risk Rerouting")
    expect(item).toHaveTextContent("Trains a gradient-boosted risk model")
    expect(screen.getByTestId("evidence-view-full")).toHaveAttribute(
      "href",
      "/p/alpha/skills/machine-learning",
    )
    expect(screen.getByTestId("evidence-open-project")).toHaveAttribute(
      "href",
      "/vbr/report/tok1",
    )
    expect(screen.getByTestId("evidence-open-passport")).toHaveAttribute(
      "href",
      "/p/alpha",
    )
  })

  it("saves a candidate straight from a proof card", async () => {
    render(<RecruiterSearchView />)
    await waitFor(() => expect(mockSearch).toHaveBeenCalled())
    mockSearch.mockResolvedValue(response())
    await searchFor("show me proof of machine learning")
    await waitFor(() =>
      expect(screen.getByTestId("evidence-results")).toBeInTheDocument(),
    )
    mockSave.mockResolvedValue({} as never)
    fireEvent.click(screen.getByTestId("search-result-save"))
    await waitFor(() =>
      expect(screen.getByTestId("search-result-saved")).toBeInTheDocument(),
    )
    expect(mockSave).toHaveBeenCalledWith(
      "alpha",
      "search",
      expect.objectContaining({ passport_slug: "alpha" }),
    )
  })

  it("states zero proof explicitly and labels related evidence as NOT proof", async () => {
    render(<RecruiterSearchView />)
    await waitFor(() => expect(mockSearch).toHaveBeenCalled())
    mockSearch.mockResolvedValue(
      response({
        evidence: evidenceResults({
          total_items: 0,
          groups: [],
          unmatched: [
            {
              requirement: "natural-language-processing",
              display: "Natural Language Processing",
              note: "No published Natural Language Processing evidence exists yet.",
            },
          ],
          related: [
            {
              requirement_display: "Natural Language Processing",
              related_display: "Machine Learning",
              candidate_names: ["Alpha Candidate"],
              note: "Related Machine Learning evidence is published — it is NOT Natural Language Processing proof.",
            },
          ],
        }),
      }),
    )
    await searchFor("show me NLP proof")
    await waitFor(() =>
      expect(screen.getByTestId("evidence-unmatched")).toBeInTheDocument(),
    )
    expect(screen.getByTestId("evidence-unmatched")).toHaveTextContent(
      "no published proof",
    )
    expect(screen.getByTestId("evidence-related")).toHaveTextContent(
      "NOT Natural Language Processing proof",
    )
    expect(screen.queryByTestId("evidence-item")).not.toBeInTheDocument()
  })

  it("opens the View-proof drawer on a verified requirement row", async () => {
    const candidate: SearchResultCandidate = {
      match_type: "exact",
      requirements: [
        {
          kind: "concept",
          requirement: "machine-learning",
          display: "Machine Learning",
          required: true,
          satisfied: true,
          via: "skill",
          matched_label: "Machine Learning",
          skill_status: "Demonstrated",
          evidence_sources: ["GitHub Proof"],
          project_titles: ["Boston Risk Rerouting"],
          note: null,
        },
      ],
      missing_requirements: [],
      public_slug: "alpha",
      display_name: "Alpha Candidate",
      headline: "AI Engineer",
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
      evidence_flags: {},
      matched_reasons: [],
      passport_published_at: null,
      in_brief: false,
      brief_status: null,
    }
    render(<RecruiterSearchView />)
    await waitFor(() => expect(mockSearch).toHaveBeenCalled())
    mockSearch.mockResolvedValue(
      response({
        results: [candidate],
        total: 1,
        exact_total: 1,
        evidence: null,
        interpretation: {
          mode: "structured",
          intent: "candidate_search",
          required: [
            { display: "Machine Learning", concepts: ["machine-learning"] },
          ],
          preferred: [],
          excluded: [],
          evidence: [],
          preferred_evidence: [],
          role: null,
          seniority: null,
          location: null,
          remote: false,
      residual_terms: [],
        },
      }),
    )
    await searchFor("machine learning engineer")
    await waitFor(() =>
      expect(screen.getByTestId("requirement-view-proof")).toBeInTheDocument(),
    )

    mockView.mockResolvedValue({
      evidence: evidenceResults(),
      skill: "machine-learning",
      candidate: "alpha",
    })
    fireEvent.click(screen.getByTestId("requirement-view-proof"))
    await waitFor(() =>
      expect(screen.getByTestId("requirement-proof-drawer")).toBeInTheDocument(),
    )
    expect(mockView).toHaveBeenCalledWith({
      skill: "machine-learning",
      candidate: "alpha",
    })
    expect(screen.getByTestId("evidence-item")).toHaveTextContent(
      "Machine Learning",
    )
    expect(screen.getByTestId("evidence-view-full")).toHaveAttribute(
      "href",
      "/p/alpha/skills/machine-learning",
    )

    // Toggle closed.
    fireEvent.click(screen.getByTestId("requirement-view-proof"))
    expect(
      screen.queryByTestId("requirement-proof-drawer"),
    ).not.toBeInTheDocument()
  })
})
