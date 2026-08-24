/**
 * Talent Pools UI — list + pool detail.
 *
 * Covers: pool cards + creation flow + empty state, archived grouping, the
 * detail view's live candidate cards (evidence context line, unpublished
 * fail-closed treatment, private note editor, remove, archive/restore) and
 * the add-to-brief picker on a pool candidate.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const routerPush = vi.fn()
// Pool detail derives its filter + selection state from the URL, so the
// search params have to be mockable per test.
let searchParams = new URLSearchParams()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
  useSearchParams: () => searchParams,
}))

vi.mock("@/lib/recruiter-pools-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/recruiter-pools-api")>()),
  listPools: vi.fn(),
  createPool: vi.fn(),
  getPool: vi.fn(),
  filterPoolCandidates: vi.fn(),
  comparePoolCandidates: vi.fn(),
  updatePool: vi.fn(),
  deletePool: vi.fn(),
  addPoolCandidates: vi.fn(),
  updatePoolCandidate: vi.fn(),
  removePoolCandidate: vi.fn(),
  getPoolMemberships: vi.fn(),
}))

vi.mock("@/lib/recruiter-briefs-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/recruiter-briefs-api")>()),
  listBriefs: vi.fn(),
  addBriefCandidates: vi.fn(),
}))

import {
  addBriefCandidates,
  listBriefs,
  type HiringBriefListItem,
} from "@/lib/recruiter-briefs-api"
import {
  createPool,
  deletePool,
  filterPoolCandidates,
  getPool,
  listPools,
  removePoolCandidate,
  updatePool,
  updatePoolCandidate,
  type PoolCandidate,
  type TalentPool,
  type TalentPoolDetail,
} from "@/lib/recruiter-pools-api"
import { PoolsListView } from "../app/recruiters/pools/PoolsListView"
import { PoolDetailView } from "../app/recruiters/pools/[poolId]/PoolDetailView"

const mockListPools = vi.mocked(listPools)
const mockCreatePool = vi.mocked(createPool)
const mockGetPool = vi.mocked(getPool)
const mockFilterPool = vi.mocked(filterPoolCandidates)
const mockUpdatePool = vi.mocked(updatePool)
const mockDeletePool = vi.mocked(deletePool)
const mockUpdateCandidate = vi.mocked(updatePoolCandidate)
const mockRemoveCandidate = vi.mocked(removePoolCandidate)
const mockListBriefs = vi.mocked(listBriefs)
const mockAddBriefCandidates = vi.mocked(addBriefCandidates)

const POOL: TalentPool = {
  id: "pool-1",
  name: "AI / ML Early Talent",
  description: "Prospects across roles",
  status: "active",
  candidate_count: 2,
  created_at: "2026-08-18T00:00:00+00:00",
  updated_at: "2026-08-18T00:00:00+00:00",
}

const ARCHIVED_POOL: TalentPool = {
  ...POOL,
  id: "pool-2",
  name: "Fall 2025 Prospects",
  status: "archived",
  candidate_count: 0,
}

const ALPHA: PoolCandidate = {
  student_user_id: "u-alpha",
  source: "search",
  status: "review" as const,
  tags: [],
  updated_at: null,
  note: null,
  added_at: "2026-08-18T00:00:00+00:00",
  candidate: {
    display_name: "Alpha Candidate",
    headline: "Student engineer",
    summary: null,
    availability_label: null,
    location: "Boston, MA",
    role_areas: [],
    public_slug: "alpha",
    is_published: true,
  },
  evidence: {
    skill_count: 3,
    project_count: 2,
    evidence_flags: { github: true, live_site: true },
    top_skills: ["Python", "FastAPI"],
    public_slug: "alpha",
  },
}

const BRAVO_UNPUBLISHED: PoolCandidate = {
  student_user_id: "u-bravo",
  source: "saved_search",
  status: "review" as const,
  tags: [],
  updated_at: null,
  note: "Met at the career fair",
  added_at: "2026-08-17T00:00:00+00:00",
  candidate: {
    display_name: "Bravo Candidate",
    headline: null,
    summary: null,
    availability_label: null,
    location: null,
    role_areas: [],
    public_slug: null,
    is_published: false,
  },
  evidence: null,
}

const DETAIL: TalentPoolDetail = {
  pool: POOL,
  candidates: [ALPHA, BRAVO_UNPUBLISHED],
  total: 2,
  status_counts: { review: 2, shortlisted: 0, interview: 0, hold: 0, pass: 0 },
  tag_vocabulary: [],
}

const BRIEF_ITEM: HiringBriefListItem = {
  id: "brief-1",
  title: "AI Engineer — Fall 2026",
  role: "AI Engineer",
  status: "active",
  candidate_count: 1,
  shortlisted_count: 0,
  created_at: "2026-08-18T00:00:00+00:00",
  updated_at: "2026-08-18T00:00:00+00:00",
}

beforeEach(() => {
  vi.clearAllMocks()
  mockListPools.mockResolvedValue([POOL, ARCHIVED_POOL])
  mockGetPool.mockResolvedValue(DETAIL)
  searchParams = new URLSearchParams()
  // The detail view loads through the filter endpoint (an unfiltered call
  // returns the whole pool), so the fixture is served from there.
  mockFilterPool.mockResolvedValue({
    pool: DETAIL.pool,
    candidates: DETAIL.candidates.map((c) => ({ ...c, match: null })),
    total: DETAIL.total,
    close_candidates: [],
    close_total: 0,
    pool_total: DETAIL.total,
    status_counts: DETAIL.status_counts,
    tag_vocabulary: DETAIL.tag_vocabulary,
    filters: { q: "", evidence: [], status: null, tags: [] },
    interpretation: null,
    unavailable_excluded: 0,
  })
  mockListBriefs.mockResolvedValue([BRIEF_ITEM])
})

describe("PoolsListView", () => {
  it("renders pool cards with counts and an archived group", async () => {
    render(<PoolsListView />)
    expect(await screen.findByText("AI / ML Early Talent")).toBeInTheDocument()
    expect(screen.getByText("2 candidates")).toBeInTheDocument()
    expect(screen.getByTestId("pools-archived-heading")).toHaveTextContent("Archived (1)")
    expect(screen.getByTestId("pool-card-archived")).toBeInTheDocument()
    // Shared nav present with the pools item active.
    expect(screen.getByTestId("pools-nav-pools")).toHaveAttribute("aria-current", "page")
    expect(screen.getByTestId("pools-nav-savedsearches")).toHaveAttribute(
      "href",
      "/recruiters/saved-searches",
    )
  })

  it("creates a pool and navigates to it", async () => {
    mockCreatePool.mockResolvedValue({ ...POOL, id: "pool-new", name: "Platform hires" })
    render(<PoolsListView />)
    await screen.findByText("AI / ML Early Talent")
    fireEvent.change(screen.getByTestId("pools-create-name"), {
      target: { value: "Platform hires" },
    })
    fireEvent.change(screen.getByTestId("pools-create-description"), {
      target: { value: "Backend + infra" },
    })
    fireEvent.click(screen.getByTestId("pools-create-submit"))
    await waitFor(() =>
      expect(mockCreatePool).toHaveBeenCalledWith({
        name: "Platform hires",
        description: "Backend + infra",
      }),
    )
    await waitFor(() =>
      expect(routerPush).toHaveBeenCalledWith("/recruiters/pools/pool-new"),
    )
  })

  it("requires a name before creating", async () => {
    render(<PoolsListView />)
    await screen.findByText("AI / ML Early Talent")
    fireEvent.click(screen.getByTestId("pools-create-submit"))
    expect(await screen.findByTestId("pools-create-error")).toHaveTextContent(
      "Give the Talent Pool a name first.",
    )
    expect(mockCreatePool).not.toHaveBeenCalled()
  })

  it("shows the empty state", async () => {
    mockListPools.mockResolvedValue([])
    render(<PoolsListView />)
    expect(await screen.findByTestId("pools-empty")).toHaveTextContent(
      "Create a Talent Pool to organize candidates across roles.",
    )
  })

  it("delete asks for confirmation and never claims to remove candidates", async () => {
    mockDeletePool.mockResolvedValue(undefined)
    render(<PoolsListView />)
    await screen.findByText("AI / ML Early Talent")
    const card = screen.getAllByTestId("pool-card")[0]
    fireEvent.click(within(card).getByTestId("pool-card-delete"))
    expect(screen.getByTestId("pool-delete-confirm")).toHaveTextContent(
      "never removes candidates",
    )
    expect(mockDeletePool).not.toHaveBeenCalled()
    fireEvent.click(within(card).getByTestId("pool-card-delete"))
    await waitFor(() => expect(mockDeletePool).toHaveBeenCalledWith("pool-1"))
  })
})

describe("PoolDetailView", () => {
  it("renders candidates with live evidence context and source labels", async () => {
    render(<PoolDetailView poolId="pool-1" />)
    expect(await screen.findByTestId("pool-title")).toHaveTextContent("AI / ML Early Talent")
    const cards = screen.getAllByTestId("pool-candidate-card")
    expect(cards).toHaveLength(2)
    const alpha = cards[0]
    expect(within(alpha).getByTestId("pool-candidate-evidence")).toHaveTextContent(
      "3 skills · 2 projects",
    )
    expect(within(alpha).getByText("Python")).toBeInTheDocument()
    expect(within(alpha).getByTestId("pool-candidate-source")).toHaveTextContent("Search")
    expect(within(alpha).getByTestId("pool-candidate-open")).toHaveAttribute("href", "/p/alpha")
  })

  it("treats an unpublished candidate fail-closed", async () => {
    render(<PoolDetailView poolId="pool-1" />)
    await screen.findByTestId("pool-title")
    const bravo = screen.getAllByTestId("pool-candidate-card")[1]
    expect(within(bravo).getByTestId("pool-candidate-unpublished")).toHaveTextContent(
      "No longer published",
    )
    expect(within(bravo).queryByTestId("pool-candidate-open")).not.toBeInTheDocument()
    expect(within(bravo).getByTestId("pool-candidate-source")).toHaveTextContent("Saved search")
    // Consented note still renders.
    expect(within(bravo).getByTestId("pool-candidate-note")).toHaveTextContent(
      "Met at the career fair",
    )
  })

  it("edits a private note", async () => {
    mockUpdateCandidate.mockResolvedValue({ ...ALPHA, note: "Strong evidence" })
    render(<PoolDetailView poolId="pool-1" />)
    await screen.findByTestId("pool-title")
    const alpha = screen.getAllByTestId("pool-candidate-card")[0]
    fireEvent.click(within(alpha).getByTestId("pool-candidate-note-toggle"))
    fireEvent.change(within(alpha).getByTestId("pool-candidate-note-input"), {
      target: { value: "Strong evidence" },
    })
    fireEvent.click(within(alpha).getByTestId("pool-candidate-note-save"))
    await waitFor(() =>
      expect(mockUpdateCandidate).toHaveBeenCalledWith("pool-1", "u-alpha", {
        note: "Strong evidence",
      }),
    )
    expect(await within(alpha).findByTestId("pool-candidate-note")).toHaveTextContent(
      "Strong evidence",
    )
  })

  it("removes a candidate", async () => {
    mockRemoveCandidate.mockResolvedValue(undefined)
    render(<PoolDetailView poolId="pool-1" />)
    await screen.findByTestId("pool-title")
    const alpha = screen.getAllByTestId("pool-candidate-card")[0]
    fireEvent.click(within(alpha).getByTestId("pool-candidate-remove"))
    await waitFor(() =>
      expect(mockRemoveCandidate).toHaveBeenCalledWith("pool-1", "u-alpha"),
    )
    await waitFor(() =>
      expect(screen.getAllByTestId("pool-candidate-card")).toHaveLength(1),
    )
  })

  it("archives and restores the pool", async () => {
    mockUpdatePool.mockResolvedValue({ ...POOL, status: "archived" })
    render(<PoolDetailView poolId="pool-1" />)
    await screen.findByTestId("pool-title")
    fireEvent.click(screen.getByTestId("pool-archive"))
    await waitFor(() =>
      expect(mockUpdatePool).toHaveBeenCalledWith("pool-1", { status: "archived" }),
    )
    expect(await screen.findByTestId("pool-restore")).toBeInTheDocument()
  })

  it("adds a pool candidate to a Hiring Brief through the picker", async () => {
    mockAddBriefCandidates.mockResolvedValue({
      added: 1,
      already_in_brief: 0,
      candidates: [],
    })
    render(<PoolDetailView poolId="pool-1" />)
    await screen.findByTestId("pool-title")
    const alpha = screen.getAllByTestId("pool-candidate-card")[0]
    fireEvent.click(within(alpha).getByTestId("add-to-brief"))
    const option = await within(alpha).findByTestId("add-to-brief-option")
    expect(option).toHaveTextContent("AI Engineer — Fall 2026")
    fireEvent.click(option)
    await waitFor(() =>
      expect(mockAddBriefCandidates).toHaveBeenCalledWith("brief-1", {
        candidate_slugs: ["alpha"],
      }),
    )
    expect(await within(alpha).findByText("Added ✓")).toBeInTheDocument()
  })

  it("renames the pool inline", async () => {
    mockUpdatePool.mockResolvedValue({ ...POOL, name: "Renamed pool" })
    render(<PoolDetailView poolId="pool-1" />)
    await screen.findByTestId("pool-title")
    fireEvent.click(screen.getByTestId("pool-rename"))
    fireEvent.change(screen.getByTestId("pool-rename-input"), {
      target: { value: "Renamed pool" },
    })
    fireEvent.click(screen.getByTestId("pool-rename-save"))
    await waitFor(() =>
      expect(mockUpdatePool).toHaveBeenCalledWith("pool-1", { name: "Renamed pool" }),
    )
    expect(await screen.findByTestId("pool-title")).toHaveTextContent("Renamed pool")
  })
})
