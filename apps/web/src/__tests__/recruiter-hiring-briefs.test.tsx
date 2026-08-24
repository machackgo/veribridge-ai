/**
 * Hiring Briefs UI — list + role detail.
 *
 * Covers: brief cards and creation flow, the role's requirement chips,
 * the ROLE-SCOPED candidate pool (status pills, private note, remove,
 * add-from-saved), the live comparison matrix (closed cell states,
 * transparent counts — never a score), and brief-scoped search with
 * in-role annotation and add-to-role.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const routerPush = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
}))

vi.mock("@/lib/recruiter-briefs-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/recruiter-briefs-api")>()),
  listBriefs: vi.fn(),
  createBrief: vi.fn(),
  getBrief: vi.fn(),
  updateBrief: vi.fn(),
  deleteBrief: vi.fn(),
  listBriefCandidates: vi.fn(),
  addBriefCandidates: vi.fn(),
  updateBriefCandidate: vi.fn(),
  removeBriefCandidate: vi.fn(),
  getBriefComparison: vi.fn(),
  briefSearch: vi.fn(),
}))

vi.mock("@/lib/recruiter-connections-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/recruiter-connections-api")>()),
  listConnections: vi.fn(),
}))

import {
  addBriefCandidates,
  briefSearch,
  createBrief,
  deleteBrief,
  getBrief,
  getBriefComparison,
  listBriefCandidates,
  listBriefs,
  removeBriefCandidate,
  updateBrief,
  updateBriefCandidate,
  type BriefCandidate,
  type BriefCandidatesResponse,
  type BriefComparisonResponse,
  type BriefStatusCounts,
  type HiringBrief,
  type HiringBriefListItem,
  type RequirementsView,
} from "@/lib/recruiter-briefs-api"
import {
  listConnections,
  type RecruiterConnection,
} from "@/lib/recruiter-connections-api"
import type { RecruiterSearchResponse } from "@/lib/recruiter-search-api"
import { BriefsListView } from "../app/recruiters/briefs/BriefsListView"
import { BriefDetailView } from "../app/recruiters/briefs/[briefId]/BriefDetailView"

const mockListBriefs = vi.mocked(listBriefs)
const mockCreateBrief = vi.mocked(createBrief)
const mockGetBrief = vi.mocked(getBrief)
const mockUpdateBrief = vi.mocked(updateBrief)
const mockDeleteBrief = vi.mocked(deleteBrief)
const mockListCandidates = vi.mocked(listBriefCandidates)
const mockAddCandidates = vi.mocked(addBriefCandidates)
const mockUpdateCandidate = vi.mocked(updateBriefCandidate)
const mockRemoveCandidate = vi.mocked(removeBriefCandidate)
const mockComparison = vi.mocked(getBriefComparison)
const mockBriefSearch = vi.mocked(briefSearch)
const mockListConnections = vi.mocked(listConnections)

const REQUIREMENTS_VIEW: RequirementsView = {
  required: [
    { display: "Python", concepts: ["python"] },
    { display: "FastAPI", concepts: ["fastapi"] },
  ],
  preferred: [{ display: "Natural Language Processing", concepts: ["natural-language-processing"] }],
  excluded: [],
  evidence: [],
  preferred_evidence: [{ key: "live_site", display: "Live deployed project" }],
  role: "AI Engineer",
  seniority: "Entry level",
  location: null,
  remote: false,
  unrecognized_terms: [],
}

/** All-zero 9-stage role-scoped counts (V4 pipeline vocabulary). */
const ZERO_COUNTS: BriefStatusCounts = {
  saved: 0,
  reviewing: 0,
  shortlisted: 0,
  contacted: 0,
  interview: 0,
  decision: 0,
  hired: 0,
  passed: 0,
  archived: 0,
}

const BRIEF: HiringBrief = {
  id: "brief-1",
  title: "AI Engineer — Fall 2026",
  role_text: "Entry-level AI Engineer. Python and FastAPI are required.",
  status: "active",
  requirements_view: REQUIREMENTS_VIEW,
  candidate_count: 2,
  status_counts: { ...ZERO_COUNTS, saved: 1, shortlisted: 1 },
  created_at: "2026-08-18T00:00:00+00:00",
  updated_at: "2026-08-18T00:00:00+00:00",
}

const LIST_ITEM: HiringBriefListItem = {
  id: "brief-1",
  title: "AI Engineer — Fall 2026",
  role: "AI Engineer",
  status: "active",
  candidate_count: 2,
  shortlisted_count: 1,
  created_at: "2026-08-18T00:00:00+00:00",
  updated_at: "2026-08-18T00:00:00+00:00",
}

const ALPHA: BriefCandidate = {
  student_user_id: "u-alpha",
  status: "shortlisted",
  note: "Strong FastAPI + ML.",
  connection_id: "conn-alpha",
  candidate: {
    display_name: "Alpha Candidate",
    headline: "Builds verified APIs",
    summary: null,
    availability_label: null,
    location: null,
    role_areas: [],
    public_slug: "alpha",
    is_published: true,
  },
  evaluation: {
    available: true,
    counts: {
      required_proven: 2,
      required_claimed: 0,
      required_total: 2,
      preferred_proven: 0,
      preferred_claimed: 0,
      preferred_total: 2,
    observed_proven: 0,
    observed_claimed: 0,
    observed_total: 0,
    },
    missing_required: [],
    missing_preferred: ["Natural Language Processing"],
    excluded_hits: [],
  },
  added_at: "2026-08-18T00:00:00+00:00",
  updated_at: "2026-08-18T00:00:00+00:00",
}

const BRAVO: BriefCandidate = {
  student_user_id: "u-bravo",
  status: "saved",
  note: null,
  connection_id: "conn-bravo",
  candidate: {
    display_name: "Bravo Candidate",
    headline: null,
    summary: null,
    availability_label: null,
    location: null,
    role_areas: [],
    public_slug: "bravo",
    is_published: true,
  },
  evaluation: {
    available: false,
    counts: {
      required_proven: 0,
      required_claimed: 0,
      required_total: 0,
      preferred_proven: 0,
      preferred_claimed: 0,
      preferred_total: 0,
    observed_proven: 0,
    observed_claimed: 0,
    observed_total: 0,
    },
    missing_required: [],
    missing_preferred: [],
    excluded_hits: [],
  },
  added_at: "2026-08-17T00:00:00+00:00",
  updated_at: "2026-08-17T00:00:00+00:00",
}

const POOL: BriefCandidatesResponse = {
  candidates: [ALPHA, BRAVO],
  total: 2,
  status_counts: { ...ZERO_COUNTS, saved: 1, shortlisted: 1 },
}

const CONNECTION_OUTSIDE_POOL: RecruiterConnection = {
  id: "conn-charlie",
  source: "search",
  created_at: "2026-08-10T12:00:00+00:00",
  candidate: {
    display_name: "Charlie Candidate",
    headline: "CV specialist",
    summary: null,
    availability_label: null,
    location: null,
    role_areas: [],
    public_slug: "charlie",
    is_published: true,
  },
}

const COMPARISON: BriefComparisonResponse = {
  brief: LIST_ITEM,
  matrix: {
    requirements: [
      { key: "concept:python", kind: "concept", display: "Python", required: true, origin: "plan" as const, concepts: ["python"] },
      { key: "concept:docker", kind: "concept", display: "Docker", required: true, origin: "plan" as const, concepts: ["docker"] },
      { key: "concept:nlp", kind: "concept", display: "Natural Language Processing", required: false, origin: "plan" as const, concepts: ["natural-language-processing"] },
    ],
    columns: [
      {
        user_id: "u-alpha",
        available: true,
        public_slug: "alpha",
        display_name: "Alpha Candidate",
        headline: null,
        availability_label: null,
        passport_path: "/p/alpha",
        cells: {
          "concept:python": {
            state: "proven",
            matched_label: "Python",
            skill_status: "Demonstrated",
            direct: true,
            evidence_sources: ["GitHub Proof"],
            project_titles: [],
            note: null,
            proof_path: "/p/alpha/skills/python",
            projects: [],
            traces: [],
            related: [],
          },
          "concept:docker": {
            state: "claimed",
            matched_label: "Docker",
            skill_status: null,
            direct: true,
            evidence_sources: [],
            project_titles: ["Capstone"],
            note: "Claimed in Capstone — not verified evidence",
            proof_path: null,
            projects: [],
            traces: [],
            related: [],
          },
          "concept:nlp": {
            state: "none",
            matched_label: null,
            skill_status: null,
            direct: true,
            evidence_sources: [],
            project_titles: [],
            note: "No published Natural Language Processing evidence",
            proof_path: null,
            projects: [],
            traces: [],
            related: ["Machine Learning"],
          },
        },
        counts: {
          required_proven: 1,
          required_claimed: 1,
          required_total: 2,
          preferred_proven: 0,
          preferred_claimed: 0,
          preferred_total: 1,
    observed_proven: 0,
    observed_claimed: 0,
    observed_total: 0,
        },
        missing_required: ["Docker"],
        missing_preferred: ["Natural Language Processing"],
        excluded_hits: [],
        unavailable_note: null,
        connection: { id: "conn-alpha" },
        brief_status: "shortlisted",
        missing_observed: [],
        pool_status: null,
        pool_note: null,
        tags: [],
      },
      {
        user_id: "u-bravo",
        available: false,
        public_slug: null,
        display_name: "Bravo Candidate",
        headline: null,
        availability_label: null,
        passport_path: null,
        cells: {},
        counts: {
          required_proven: 0,
          required_claimed: 0,
          required_total: 0,
          preferred_proven: 0,
          preferred_claimed: 0,
          preferred_total: 0,
    observed_proven: 0,
    observed_claimed: 0,
    observed_total: 0,
        },
        missing_required: [],
        missing_preferred: [],
        excluded_hits: [],
        unavailable_note: "This candidate's evidence is no longer publicly available.",
        connection: { id: "conn-bravo" },
        brief_status: "saved",
        missing_observed: [],
        pool_status: null,
        pool_note: null,
        tags: [],
      },
    ],
    coverage: [],
    summaries: [
      "Alpha Candidate: published evidence for 1 of 2 required requirements (plus 1 claimed — not verified).",
    ],
    notes: ["1 selected candidate is no longer publicly available."],
    requirements_view: REQUIREMENTS_VIEW,
  },
}

const SEARCH_RESPONSE: RecruiterSearchResponse = {
  results: [
    {
      match_type: "exact",
      requirements: [],
      missing_requirements: [],
      public_slug: "alpha",
      display_name: "Alpha Candidate",
      headline: null,
      location: null,
      availability_label: null,
      institution: null,
      degree: null,
      graduation_year: null,
      role_areas: [],
      skills: [],
      skill_count: 3,
      project_count: 1,
      projects: [],
      evidence_flags: {},
      matched_reasons: [],
      passport_published_at: null,
      in_brief: true,
      brief_status: "shortlisted",
    },
    {
      match_type: "close",
      requirements: [],
      missing_requirements: ["Machine Learning"],
      public_slug: "delta",
      display_name: "Delta Candidate",
      headline: null,
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
    },
  ],
  total: 2,
  exact_total: 1,
  close_total: 1,
  page: 1,
  page_size: 10,
  has_more: false,
  interpretation: {
    mode: "structured",
    intent: "candidate_search",
    required: [{ display: "Python", concepts: ["python"] }],
    preferred: [],
    excluded: [],
    evidence: [],
    preferred_evidence: [],
    role: "AI Engineer",
    seniority: null,
    location: null,
    remote: false,
    residual_terms: [],
  },
  query: { q: "", terms: [], skills: [], evidence: [], availability: null },
}

beforeEach(() => {
  vi.clearAllMocks()
  mockListBriefs.mockResolvedValue([LIST_ITEM])
  mockCreateBrief.mockResolvedValue(BRIEF)
  mockGetBrief.mockResolvedValue(BRIEF)
  mockUpdateBrief.mockResolvedValue(BRIEF)
  mockDeleteBrief.mockResolvedValue(undefined)
  mockListCandidates.mockResolvedValue(POOL)
  mockAddCandidates.mockResolvedValue({ added: 1, already_in_brief: 0, candidates: [] })
  mockUpdateCandidate.mockResolvedValue({ ...ALPHA, status: "reviewing" })
  mockRemoveCandidate.mockResolvedValue(undefined)
  mockComparison.mockResolvedValue(COMPARISON)
  mockBriefSearch.mockResolvedValue(SEARCH_RESPONSE)
  mockListConnections.mockResolvedValue([CONNECTION_OUTSIDE_POOL])
})

describe("BriefsListView", () => {
  it("renders brief cards with role-scoped counts and status", async () => {
    render(<BriefsListView />)

    const card = await screen.findByTestId("brief-card")
    expect(card).toBeInTheDocument()
    expect(screen.getByTestId("brief-card-title")).toHaveTextContent("AI Engineer — Fall 2026")
    expect(screen.getByText("2 candidates")).toBeInTheDocument()
    expect(screen.getByText("1 shortlisted")).toBeInTheDocument()
    expect(screen.getByTestId("brief-card-open")).toHaveAttribute(
      "href",
      "/recruiters/briefs/brief-1",
    )
  })

  it("shows the empty state when there are no briefs", async () => {
    mockListBriefs.mockResolvedValue([])
    render(<BriefsListView />)
    expect(await screen.findByTestId("briefs-empty")).toBeInTheDocument()
  })

  it("creates a brief from role text and navigates to it", async () => {
    render(<BriefsListView />)
    await screen.findByTestId("brief-card")

    fireEvent.change(screen.getByTestId("brief-create-role-text"), {
      target: { value: "Python and FastAPI required." },
    })
    fireEvent.click(screen.getByTestId("brief-create-submit"))

    await waitFor(() =>
      expect(mockCreateBrief).toHaveBeenCalledWith({
        title: null,
        role_text: "Python and FastAPI required.",
      }),
    )
    await waitFor(() =>
      expect(routerPush).toHaveBeenCalledWith("/recruiters/briefs/brief-1"),
    )
  })

  it("deletes a brief from its card", async () => {
    render(<BriefsListView />)
    await screen.findByTestId("brief-card")
    fireEvent.click(screen.getByTestId("brief-card-delete"))
    await waitFor(() => expect(mockDeleteBrief).toHaveBeenCalledWith("brief-1"))
    await waitFor(() =>
      expect(screen.queryByTestId("brief-card")).not.toBeInTheDocument(),
    )
  })
})

describe("BriefDetailView", () => {
  it("renders the brief with requirement chips", async () => {
    render(<BriefDetailView briefId="brief-1" />)

    expect(await screen.findByTestId("brief-title")).toHaveTextContent(
      "AI Engineer — Fall 2026",
    )
    const chips = screen.getAllByTestId("requirement-chip").map((el) => el.textContent)
    expect(chips).toContain("Python")
    expect(chips).toContain("FastAPI")
    expect(chips).toContain("Natural Language Processing")
    expect(chips).toContain("Live deployed project")
  })

  it("shows the pipeline: stage-grouped candidates with live evaluation", async () => {
    render(<BriefDetailView briefId="brief-1" />)

    const cards = await screen.findAllByTestId("brief-candidate-card")
    expect(cards).toHaveLength(2)

    // Candidates are grouped into stage sections, in pipeline order
    // (saved before shortlisted) — only non-empty stages render sections.
    const savedSection = screen.getByTestId("brief-stage-section-saved")
    const shortlistedSection = screen.getByTestId("brief-stage-section-shortlisted")
    expect(within(savedSection).getByText("Bravo Candidate")).toBeInTheDocument()
    expect(within(shortlistedSection).getByText("Alpha Candidate")).toBeInTheDocument()
    expect(screen.queryByTestId("brief-stage-section-hired")).not.toBeInTheDocument()

    expect(screen.getByTestId("brief-candidate-evaluation")).toHaveTextContent(
      "2 of 2 required proven",
    )
    // Unavailable candidates evaluate honestly, never with stale evidence.
    expect(screen.getByTestId("brief-candidate-unavailable")).toBeInTheDocument()
    expect(screen.getByTestId("brief-candidate-note")).toHaveTextContent(
      "Strong FastAPI + ML.",
    )
    // Every card links to its interview workspace.
    expect(
      within(shortlistedSection).getByTestId("brief-candidate-interview-link"),
    ).toHaveAttribute("href", "/recruiters/briefs/brief-1/interview/u-alpha")
  })

  it("renders the 9-stage summary bar with live counts and filters by stage", async () => {
    render(<BriefDetailView briefId="brief-1" />)
    await screen.findAllByTestId("brief-candidate-card")

    // All 9 stages render as count pills — empty stages included.
    const bar = screen.getByTestId("brief-stage-bar")
    expect(within(bar).getByTestId("brief-stage-pill-all")).toHaveTextContent("All · 2")
    expect(within(bar).getByTestId("brief-stage-pill-saved")).toHaveTextContent("Saved · 1")
    expect(within(bar).getByTestId("brief-stage-pill-shortlisted")).toHaveTextContent(
      "Shortlisted · 1",
    )
    for (const stage of [
      "reviewing", "contacted", "interview", "decision", "hired", "passed", "archived",
    ]) {
      expect(within(bar).getByTestId(`brief-stage-pill-${stage}`)).toHaveTextContent("· 0")
    }

    // Filtering to one stage hides the other sections.
    const savedPill = within(bar).getByTestId("brief-stage-pill-saved")
    fireEvent.click(savedPill)
    expect(savedPill).toHaveAttribute("aria-pressed", "true")
    expect(screen.getByTestId("brief-stage-section-saved")).toBeInTheDocument()
    expect(screen.queryByTestId("brief-stage-section-shortlisted")).not.toBeInTheDocument()

    // An empty stage filter shows a calm empty line, not a blank page.
    fireEvent.click(within(bar).getByTestId("brief-stage-pill-hired"))
    expect(screen.getByTestId("brief-stage-filter-empty")).toHaveTextContent("Hired")

    // Clicking the active pill returns to All.
    fireEvent.click(within(bar).getByTestId("brief-stage-pill-hired"))
    expect(screen.getAllByTestId("brief-candidate-card")).toHaveLength(2)
  })

  it("updates a candidate's ROLE-SCOPED stage through the accessible select", async () => {
    mockUpdateCandidate.mockResolvedValue({ ...ALPHA, status: "contacted" })
    render(<BriefDetailView briefId="brief-1" />)
    await screen.findAllByTestId("brief-candidate-card")

    const alphaCard = within(
      screen.getByTestId("brief-stage-section-shortlisted"),
    ).getByTestId("brief-candidate-card")
    const select = within(alphaCard).getByTestId("brief-candidate-stage-select")
    // The select carries the full 9-stage vocabulary.
    expect(within(select).getAllByRole("option").map((o) => (o as HTMLOptionElement).value)).toEqual([
      "saved", "reviewing", "shortlisted", "contacted", "interview",
      "decision", "hired", "passed", "archived",
    ])

    fireEvent.change(select, { target: { value: "contacted" } })
    await waitFor(() =>
      expect(mockUpdateCandidate).toHaveBeenCalledWith("brief-1", "u-alpha", {
        status: "contacted",
      }),
    )
    // The card moves to its new stage section; counts follow.
    await waitFor(() =>
      expect(screen.getByTestId("brief-stage-section-contacted")).toBeInTheDocument(),
    )
    expect(screen.getByTestId("brief-stage-pill-contacted")).toHaveTextContent(
      "Contacted · 1",
    )
    expect(screen.queryByTestId("brief-stage-section-shortlisted")).not.toBeInTheDocument()
  })

  it("reverts an optimistic stage move when the update fails", async () => {
    mockUpdateCandidate.mockRejectedValue(new Error("network down"))
    render(<BriefDetailView briefId="brief-1" />)
    await screen.findAllByTestId("brief-candidate-card")

    const alphaCard = within(
      screen.getByTestId("brief-stage-section-shortlisted"),
    ).getByTestId("brief-candidate-card")
    fireEvent.change(within(alphaCard).getByTestId("brief-candidate-stage-select"), {
      target: { value: "hired" },
    })

    // The failed request restores the original stage and explains why.
    await waitFor(() =>
      expect(screen.getByTestId("brief-stage-section-shortlisted")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("brief-stage-section-hired")).not.toBeInTheDocument()
    expect(screen.getByText("network down")).toBeInTheDocument()
  })

  it("removes a candidate from the role only", async () => {
    render(<BriefDetailView briefId="brief-1" />)
    await screen.findAllByTestId("brief-candidate-card")

    const alphaCard = within(
      screen.getByTestId("brief-stage-section-shortlisted"),
    ).getByTestId("brief-candidate-card")
    fireEvent.click(within(alphaCard).getByTestId("brief-candidate-remove"))
    await waitFor(() =>
      expect(mockRemoveCandidate).toHaveBeenCalledWith("brief-1", "u-alpha"),
    )
  })

  it("offers saved candidates not yet in the pool", async () => {
    render(<BriefDetailView briefId="brief-1" />)
    await screen.findByTestId("brief-add-saved")

    expect(screen.getByText("Charlie Candidate")).toBeInTheDocument()
    fireEvent.click(screen.getByTestId("brief-add-connection"))
    await waitFor(() =>
      expect(mockAddCandidates).toHaveBeenCalledWith("brief-1", {
        connection_ids: ["conn-charlie"],
      }),
    )
  })

  it("renders the live comparison matrix with closed cell states and no scores", async () => {
    render(<BriefDetailView briefId="brief-1" />)
    await screen.findByTestId("brief-title")

    fireEvent.click(screen.getByTestId("brief-tab-compare"))
    const matrix = await screen.findByTestId("comparison-matrix")

    expect(mockComparison).toHaveBeenCalledWith("brief-1")
    expect(screen.getByTestId("matrix-cell-proven")).toBeInTheDocument()
    expect(screen.getByTestId("matrix-cell-proof-link")).toHaveAttribute(
      "href",
      "/p/alpha/skills/python",
    )
    expect(screen.getByTestId("matrix-cell-claimed")).toHaveTextContent(
      "not verified",
    )
    expect(screen.getByTestId("matrix-cell-none")).toHaveTextContent(
      "Related (not proof): Machine Learning",
    )
    // Role-scoped status travels into the matrix header.
    const columnNames = screen.getAllByTestId("comparison-column-name")
    expect(columnNames[0]).toHaveTextContent("Alpha Candidate")
    expect(screen.getByText("Unavailable")).toBeInTheDocument()
    // Transparent counts, never a percentage.
    expect(matrix.textContent).not.toContain("%")
    expect(screen.getByTestId("comparison-note")).toHaveTextContent(
      "no longer publicly available",
    )
  })

  it("shows a calm compare empty state for a small pool without calling the API", async () => {
    // One comparable candidate (Bravo archived): compare is an invitation,
    // never an alarming error — and the comparison endpoint is never hit.
    mockListCandidates.mockResolvedValue({
      candidates: [ALPHA, { ...BRAVO, status: "archived" }],
      total: 2,
      status_counts: { ...ZERO_COUNTS, shortlisted: 1, archived: 1 },
    })
    render(<BriefDetailView briefId="brief-1" />)
    await screen.findByTestId("brief-title")

    fireEvent.click(screen.getByTestId("brief-tab-compare"))
    const empty = await screen.findByTestId("brief-comparison-empty")
    expect(empty).toHaveTextContent("Only one candidate in this role")
    expect(empty).toHaveTextContent("Add at least 2 candidates to compare evidence.")
    expect(mockComparison).not.toHaveBeenCalled()
    expect(screen.queryByTestId("brief-comparison-error")).not.toBeInTheDocument()
  })

  it("treats a server-side too_few_candidates code as an empty state, not an error", async () => {
    const { BriefApiError } = await import("@/lib/recruiter-briefs-api")
    mockComparison.mockRejectedValue(
      new BriefApiError("At least 2 candidates are required.", "too_few_candidates"),
    )
    render(<BriefDetailView briefId="brief-1" />)
    await screen.findByTestId("brief-title")

    fireEvent.click(screen.getByTestId("brief-tab-compare"))
    expect(await screen.findByTestId("brief-comparison-empty")).toBeInTheDocument()
    expect(screen.queryByTestId("brief-comparison-error")).not.toBeInTheDocument()
  })

  it("runs brief-scoped search and adds a result to the role", async () => {
    render(<BriefDetailView briefId="brief-1" />)
    await screen.findByTestId("brief-title")

    fireEvent.click(screen.getByTestId("brief-tab-search"))
    fireEvent.click(screen.getByTestId("brief-search-submit"))

    const results = await screen.findAllByTestId("brief-search-result")
    expect(results).toHaveLength(2)
    expect(mockBriefSearch).toHaveBeenCalledWith("brief-1", { q: "" })

    // Pool members are annotated with their role-scoped status.
    expect(screen.getByTestId("brief-search-in-brief")).toHaveTextContent(
      "In role · Shortlisted",
    )

    // Non-members can be added by published slug.
    fireEvent.click(screen.getByTestId("brief-search-add"))
    await waitFor(() =>
      expect(mockAddCandidates).toHaveBeenCalledWith("brief-1", {
        candidate_slugs: ["delta"],
      }),
    )
  })

  it("re-parses the role description on update", async () => {
    render(<BriefDetailView briefId="brief-1" />)
    await screen.findByTestId("brief-title")

    fireEvent.click(screen.getByTestId("brief-edit-requirements"))
    fireEvent.change(screen.getByTestId("brief-role-text-input"), {
      target: { value: "Senior NLP engineer. Python required." },
    })
    fireEvent.click(screen.getByTestId("brief-role-text-save"))

    await waitFor(() =>
      expect(mockUpdateBrief).toHaveBeenCalledWith("brief-1", {
        role_text: "Senior NLP engineer. Python required.",
      }),
    )
  })
})
