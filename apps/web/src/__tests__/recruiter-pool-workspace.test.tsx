/**
 * Talent Pool WORKSPACE UI (V6) — filtering, selection, comparison, and the
 * recruiter-private workflow layer.
 *
 * The behavioural contract these tests defend:
 *   * filter/selection state is URL-derived, so reload and back/forward
 *     reproduce the view;
 *   * an empty filter result reads as "no evidence matched", never as a
 *     judgement about anyone;
 *   * a candidate who unpublished is reported as unavailable, not silently
 *     dropped;
 *   * comparison shows evidence states with their qualitative wording and a
 *     walkable trail to the proof, and never a score or ranking;
 *   * recruiter status/notes/tags are visibly separate from evidence.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const routerPush = vi.fn()
let searchParams = new URLSearchParams()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
  useSearchParams: () => searchParams,
}))

vi.mock("@/lib/recruiter-pools-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/recruiter-pools-api")>()),
  filterPoolCandidates: vi.fn(),
  comparePoolCandidates: vi.fn(),
  updatePool: vi.fn(),
  deletePool: vi.fn(),
  updatePoolCandidate: vi.fn(),
  removePoolCandidate: vi.fn(),
}))

vi.mock("@/lib/recruiter-briefs-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/recruiter-briefs-api")>()),
  listBriefs: vi.fn(async () => []),
  addBriefCandidates: vi.fn(),
}))

import {
  comparePoolCandidates,
  filterPoolCandidates,
  updatePoolCandidate,
  type FilteredPoolCandidate,
  type PoolComparisonResult,
  type PoolFilterResult,
  type TalentPool,
} from "@/lib/recruiter-pools-api"
import { PoolDetailView } from "../app/recruiters/pools/[poolId]/PoolDetailView"
import { PoolComparisonView } from "../app/recruiters/pools/[poolId]/compare/PoolComparisonView"

const mockFilter = vi.mocked(filterPoolCandidates)
const mockCompare = vi.mocked(comparePoolCandidates)
const mockUpdateCandidate = vi.mocked(updatePoolCandidate)

const POOL: TalentPool = {
  id: "pool-1",
  name: "Fall 2026 — AI / ML",
  description: "Career fair prospects",
  status: "active",
  candidate_count: 3,
  created_at: "2026-08-20T00:00:00+00:00",
  updated_at: "2026-08-24T00:00:00+00:00",
}

function candidate(
  id: string,
  name: string,
  slug: string | null,
  overrides: Partial<FilteredPoolCandidate> = {},
): FilteredPoolCandidate {
  return {
    student_user_id: id,
    source: "search",
    status: "review",
    note: null,
    tags: [],
    added_at: "2026-08-20T00:00:00+00:00",
    updated_at: null,
    candidate: {
      display_name: name,
      headline: "Student engineer",
      summary: null,
      availability_label: null,
      location: null,
      role_areas: ["Backend"],
      public_slug: slug,
      is_published: slug !== null,
    },
    evidence:
      slug === null
        ? null
        : {
            skill_count: 2,
            project_count: 1,
            evidence_flags: { github: true, live_site: true },
            top_skills: ["Python", "FastAPI"],
            public_slug: slug,
          },
    match: null,
    ...overrides,
  }
}

const ALPHA = candidate("u-alpha", "Alpha Candidate", "alpha")
const BRAVO = candidate("u-bravo", "Bravo Candidate", "bravo")
const CHARLIE = candidate("u-charlie", "Charlie Candidate", "charlie")

function filterResult(overrides: Partial<PoolFilterResult> = {}): PoolFilterResult {
  return {
    pool: POOL,
    candidates: [ALPHA, BRAVO, CHARLIE],
    total: 3,
    pool_total: 3,
    status_counts: { review: 3, shortlisted: 0, interview: 0, hold: 0, pass: 0 },
    tag_vocabulary: [],
    filters: { q: "", evidence: [], status: null, tags: [] },
    interpretation: null,
    unavailable_excluded: 0,
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  searchParams = new URLSearchParams()
  mockFilter.mockResolvedValue(filterResult())
})

// ── Filtering ────────────────────────────────────────────────────────────────

describe("Talent Pool filtering", () => {
  it("loads the whole pool when nothing is filtered", async () => {
    render(<PoolDetailView poolId="pool-1" />)
    await screen.findByText("Alpha Candidate")
    expect(screen.getAllByTestId("pool-candidate-card")).toHaveLength(3)
    expect(screen.queryByTestId("pool-filter-summary")).not.toBeInTheDocument()
    expect(mockFilter).toHaveBeenCalledWith("pool-1", {
      q: "",
      evidence: [],
      status: null,
      tags: [],
    })
  })

  it("pushes the typed query into the URL rather than local state", async () => {
    render(<PoolDetailView poolId="pool-1" />)
    await screen.findByText("Alpha Candidate")
    fireEvent.change(screen.getByTestId("pool-filter-input"), {
      target: { value: "FastAPI with deployed website evidence" },
    })
    fireEvent.click(screen.getByTestId("pool-filter-submit"))
    expect(routerPush).toHaveBeenCalledWith(
      "/recruiters/pools/pool-1?q=FastAPI+with+deployed+website+evidence",
    )
  })

  it("runs the filter from the URL, so a reload reproduces it", async () => {
    searchParams = new URLSearchParams({ q: "FastAPI", evidence: "live_site" })
    mockFilter.mockResolvedValue(
      filterResult({
        candidates: [ALPHA],
        total: 1,
        filters: { q: "FastAPI", evidence: ["live_site"], status: null, tags: [] },
      }),
    )
    render(<PoolDetailView poolId="pool-1" />)
    await screen.findByText("Alpha Candidate")
    expect(mockFilter).toHaveBeenCalledWith("pool-1", {
      q: "FastAPI",
      evidence: ["live_site"],
      status: null,
      tags: [],
    })
    expect(screen.getByTestId("pool-filter-summary")).toHaveTextContent(
      "Showing 1 of 3 candidates in this pool.",
    )
  })

  it("shows WHY a candidate matched, with a link into the proof", async () => {
    searchParams = new URLSearchParams({ q: "FastAPI" })
    mockFilter.mockResolvedValue(
      filterResult({
        candidates: [
          {
            ...ALPHA,
            match: {
              match_type: "exact",
              requirements: [
                { requirement: "fastapi", display: "FastAPI", satisfied: true },
              ],
              missing_requirements: [],
              matched_reasons: [],
              skills: [],
              projects: [],
            },
          },
        ],
        total: 1,
      }),
    )
    render(<PoolDetailView poolId="pool-1" />)
    const match = await screen.findByTestId("pool-candidate-match")
    expect(match).toHaveTextContent("Matched on published evidence")
    expect(within(match).getByTestId("pool-match-proof-link")).toHaveAttribute(
      "href",
      "/p/alpha/skills/fastapi",
    )
  })

  it("names what is missing on a close match instead of scoring it", async () => {
    searchParams = new URLSearchParams({ q: "FastAPI and Kubernetes" })
    mockFilter.mockResolvedValue(
      filterResult({
        candidates: [
          {
            ...ALPHA,
            match: {
              match_type: "close",
              requirements: [
                { requirement: "fastapi", display: "FastAPI", satisfied: true },
              ],
              missing_requirements: ["Kubernetes"],
              matched_reasons: [],
              skills: [],
              projects: [],
            },
          },
        ],
        total: 1,
      }),
    )
    render(<PoolDetailView poolId="pool-1" />)
    const match = await screen.findByTestId("pool-candidate-match")
    expect(match).toHaveTextContent("Close match — some evidence missing")
    expect(match).toHaveTextContent("Kubernetes: not demonstrated")
  })

  it("states an empty result as absent evidence, never as a verdict", async () => {
    searchParams = new URLSearchParams({ q: "Rust" })
    mockFilter.mockResolvedValue(filterResult({ candidates: [], total: 0 }))
    render(<PoolDetailView poolId="pool-1" />)
    const empty = await screen.findByTestId("pool-filter-empty")
    expect(empty).toHaveTextContent("No candidates in this pool match that evidence")
    expect(empty).toHaveTextContent("Nothing here is a judgement about anyone")
    const text = empty.textContent ?? ""
    expect(text.toLowerCase()).not.toContain("weak")
    expect(text.toLowerCase()).not.toContain("unqualified")
  })

  it("says so when members were excluded for being unpublished", async () => {
    searchParams = new URLSearchParams({ q: "Python" })
    mockFilter.mockResolvedValue(
      filterResult({ candidates: [ALPHA], total: 1, unavailable_excluded: 2 }),
    )
    render(<PoolDetailView poolId="pool-1" />)
    expect(await screen.findByTestId("pool-filter-unavailable")).toHaveTextContent(
      "2 candidates are not shown because their evidence is no longer published",
    )
  })

  it("surfaces terms it could not turn into a requirement", async () => {
    searchParams = new URLSearchParams({ q: "python wizardry" })
    mockFilter.mockResolvedValue(
      filterResult({
        candidates: [ALPHA],
        total: 1,
        interpretation: { unrecognized_terms: ["wizardry"] },
      }),
    )
    render(<PoolDetailView poolId="pool-1" />)
    expect(await screen.findByTestId("pool-filter-unrecognized")).toHaveTextContent(
      "Not understood as a requirement, so not used to match: wizardry.",
    )
  })

  it("toggles a proof-source chip through the URL", async () => {
    render(<PoolDetailView poolId="pool-1" />)
    await screen.findByText("Alpha Candidate")
    const chips = screen.getAllByTestId("pool-filter-evidence")
    fireEvent.click(chips[0])
    expect(routerPush).toHaveBeenCalledWith("/recruiters/pools/pool-1?evidence=github")
  })

  it("offers a real next action from the empty pool", async () => {
    mockFilter.mockResolvedValue(filterResult({ candidates: [], total: 0, pool_total: 0 }))
    render(<PoolDetailView poolId="pool-1" />)
    const empty = await screen.findByTestId("pool-candidates-empty")
    expect(within(empty).getByTestId("pool-empty-saved")).toHaveAttribute(
      "href",
      "/recruiters/workspace",
    )
    expect(within(empty).getByTestId("pool-empty-search")).toHaveAttribute(
      "href",
      "/recruiters/search",
    )
  })
})

// ── Selection + compare hand-off ─────────────────────────────────────────────

describe("Talent Pool selection", () => {
  it("keeps Compare disabled below two candidates", async () => {
    render(<PoolDetailView poolId="pool-1" />)
    await screen.findByText("Alpha Candidate")
    expect(screen.getByTestId("pool-compare")).toBeDisabled()
    fireEvent.click(screen.getAllByTestId("pool-candidate-select")[0])
    expect(routerPush).toHaveBeenCalledWith("/recruiters/pools/pool-1?selected=u-alpha")
  })

  it("enables Compare at two and deep-links the selection", async () => {
    searchParams = new URLSearchParams({ selected: "u-alpha,u-bravo" })
    render(<PoolDetailView poolId="pool-1" />)
    await screen.findByText("Alpha Candidate")
    const compare = screen.getByTestId("pool-compare")
    expect(compare).not.toBeDisabled()
    fireEvent.click(compare)
    expect(routerPush).toHaveBeenCalledWith(
      "/recruiters/pools/pool-1/compare?ids=u-alpha%2Cu-bravo",
    )
  })

  it("caps selection at five and disables the rest", async () => {
    const many = ["a", "b", "c", "d", "e", "f"].map((k) =>
      candidate(`u-${k}`, `Candidate ${k}`, k),
    )
    searchParams = new URLSearchParams({ selected: "u-a,u-b,u-c,u-d,u-e" })
    mockFilter.mockResolvedValue(filterResult({ candidates: many, total: 6, pool_total: 6 }))
    render(<PoolDetailView poolId="pool-1" />)
    await screen.findByText("Candidate f")
    const boxes = screen.getAllByTestId("pool-candidate-select") as HTMLInputElement[]
    expect(boxes.filter((b) => b.checked)).toHaveLength(5)
    expect(boxes[5].disabled).toBe(true)
    expect(screen.getByTestId("pool-compare-bar")).toHaveTextContent("5 selected (maximum)")
  })

  it("ignores a stale selection for a candidate no longer on screen", async () => {
    searchParams = new URLSearchParams({ selected: "u-alpha,u-removed" })
    mockFilter.mockResolvedValue(filterResult({ candidates: [ALPHA], total: 1 }))
    render(<PoolDetailView poolId="pool-1" />)
    await screen.findByText("Alpha Candidate")
    expect(screen.getByTestId("pool-compare")).toBeDisabled()
    expect(screen.getByTestId("pool-compare-bar")).toHaveTextContent("1 selected")
  })
})

// ── Recruiter-private workflow layer ─────────────────────────────────────────

describe("Recruiter workflow metadata", () => {
  it("changes a workflow status", async () => {
    mockUpdateCandidate.mockResolvedValue({ ...ALPHA, status: "shortlisted" })
    render(<PoolDetailView poolId="pool-1" />)
    await screen.findByText("Alpha Candidate")
    fireEvent.change(screen.getAllByTestId("pool-candidate-status-select")[0], {
      target: { value: "shortlisted" },
    })
    await waitFor(() =>
      expect(mockUpdateCandidate).toHaveBeenCalledWith("pool-1", "u-alpha", {
        status: "shortlisted",
      }),
    )
    await waitFor(() =>
      expect(screen.getAllByTestId("pool-candidate-status")[0]).toHaveTextContent(
        "Shortlisted",
      ),
    )
  })

  it("adds a tag and says who can see it", async () => {
    mockUpdateCandidate.mockResolvedValue({ ...ALPHA, tags: ["Career Fair"] })
    render(<PoolDetailView poolId="pool-1" />)
    await screen.findByText("Alpha Candidate")
    fireEvent.click(screen.getAllByTestId("pool-candidate-tags-toggle")[0])
    fireEvent.change(screen.getByTestId("pool-candidate-tag-input"), {
      target: { value: "Career Fair" },
    })
    fireEvent.click(screen.getByTestId("pool-candidate-tag-add"))
    await waitFor(() =>
      expect(mockUpdateCandidate).toHaveBeenCalledWith("pool-1", "u-alpha", {
        tags: ["Career Fair"],
      }),
    )
    expect(
      screen.getByText(/Tags are yours alone/, { exact: false }),
    ).toBeInTheDocument()
  })

  it("does not re-add a tag that already exists", async () => {
    mockFilter.mockResolvedValue(
      filterResult({ candidates: [{ ...ALPHA, tags: ["Backend"] }], total: 1 }),
    )
    render(<PoolDetailView poolId="pool-1" />)
    await screen.findByText("Alpha Candidate")
    fireEvent.click(screen.getByTestId("pool-candidate-tags-toggle"))
    fireEvent.change(screen.getByTestId("pool-candidate-tag-input"), {
      target: { value: "backend" },
    })
    fireEvent.click(screen.getByTestId("pool-candidate-tag-add"))
    expect(mockUpdateCandidate).not.toHaveBeenCalled()
  })

  it("saves a private note and labels it as private", async () => {
    mockUpdateCandidate.mockResolvedValue({ ...ALPHA, note: "Strong walkthrough" })
    render(<PoolDetailView poolId="pool-1" />)
    await screen.findByText("Alpha Candidate")
    fireEvent.click(screen.getAllByTestId("pool-candidate-note-toggle")[0])
    const input = screen.getByTestId("pool-candidate-note-input")
    expect(input).toHaveAttribute(
      "placeholder",
      expect.stringContaining("the candidate never sees it"),
    )
    fireEvent.change(input, { target: { value: "Strong walkthrough" } })
    fireEvent.click(screen.getByTestId("pool-candidate-note-save"))
    await waitFor(() =>
      expect(mockUpdateCandidate).toHaveBeenCalledWith("pool-1", "u-alpha", {
        note: "Strong walkthrough",
      }),
    )
  })

  it("filters by a recruiter status chip", async () => {
    render(<PoolDetailView poolId="pool-1" />)
    await screen.findByText("Alpha Candidate")
    const statusChips = screen.getAllByTestId("pool-filter-status")
    fireEvent.click(statusChips[1]) // "Shortlisted"
    expect(routerPush).toHaveBeenCalledWith("/recruiters/pools/pool-1?status=shortlisted")
  })
})

// ── Comparison ───────────────────────────────────────────────────────────────

function comparisonResult(
  overrides: Partial<PoolComparisonResult["matrix"]> = {},
): PoolComparisonResult {
  const counts = {
    required_proven: 0,
    required_claimed: 0,
    required_total: 0,
    preferred_proven: 0,
    preferred_claimed: 0,
    preferred_total: 0,
    observed_proven: 1,
    observed_claimed: 0,
    observed_total: 2,
  }
  return {
    pool: POOL,
    query: null,
    requirements_view: {
      required: [],
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
    matrix: {
      requirements: [
        {
          key: "concept:fastapi",
          kind: "concept",
          display: "FastAPI",
          required: false,
          origin: "observed",
          concepts: ["fastapi"],
        },
        {
          key: "concept:docker",
          kind: "concept",
          display: "Docker",
          required: false,
          origin: "observed",
          concepts: ["docker"],
        },
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
            "concept:fastapi": {
              state: "proven",
              matched_label: "FastAPI",
              skill_status: "Demonstrated",
              direct: true,
              evidence_sources: ["GitHub Proof"],
              project_titles: ["Boston Rerouting"],
              note: null,
              proof_path: "/p/alpha/skills/fastapi",
              projects: [
                {
                  title: "Boston Rerouting",
                  public_report_path: "/r/alpha",
                  skill_status: "Demonstrated",
                  proof_types: ["GitHub Proof", "Website Proof"],
                },
              ],
              traces: [
                {
                  source_type: "GitHub Proof",
                  source_title: "router.py",
                  summary: "Routing service",
                  public_url: "/r/alpha#github",
                },
              ],
              related: [],
            },
            "concept:docker": {
              state: "none",
              matched_label: null,
              skill_status: null,
              direct: true,
              evidence_sources: [],
              project_titles: [],
              note: "No published Docker evidence",
              proof_path: null,
              projects: [],
              traces: [],
              related: ["Kubernetes"],
            },
          },
          counts,
          missing_required: [],
          missing_preferred: [],
          missing_observed: ["Docker"],
          excluded_hits: [],
          unavailable_note: null,
          connection: null,
          brief_status: null,
          pool_status: "shortlisted",
          pool_note: "Strong walkthrough",
          tags: ["Backend"],
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
          counts: { ...counts, observed_proven: 0, observed_total: 0 },
          missing_required: [],
          missing_preferred: [],
          missing_observed: [],
          excluded_hits: [],
          unavailable_note:
            "This candidate's evidence is no longer publicly available.",
          connection: null,
          brief_status: null,
          pool_status: "review",
          pool_note: null,
          tags: [],
        },
      ],
      coverage: [],
      summaries: [
        "Alpha Candidate: published evidence for 1 of 2 compared skills.",
        "Bravo Candidate: evidence no longer publicly available.",
      ],
      notes: [
        "No requirements given — comparing the skills these candidates have published evidence for.",
      ],
      requirements_view: {
        required: [],
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
      ...overrides,
    },
  }
}

describe("Talent Pool comparison", () => {
  beforeEach(() => {
    searchParams = new URLSearchParams({ ids: "u-alpha,u-bravo" })
    mockCompare.mockResolvedValue(comparisonResult())
  })

  it("asks for a selection when fewer than two are deep-linked", async () => {
    searchParams = new URLSearchParams({ ids: "u-alpha" })
    render(<PoolComparisonView poolId="pool-1" />)
    expect(await screen.findByTestId("comparison-too-few")).toHaveTextContent(
      "Select between 2 and 5 candidates",
    )
    expect(mockCompare).not.toHaveBeenCalled()
  })

  it("renders the matrix and says where the axis came from", async () => {
    render(<PoolComparisonView poolId="pool-1" />)
    await screen.findByTestId("comparison-matrix")
    expect(mockCompare).toHaveBeenCalledWith("pool-1", {
      student_user_ids: ["u-alpha", "u-bravo"],
      q: null,
    })
    expect(screen.getByTestId("comparison-section-heading")).toHaveTextContent(
      "Published evidence across the selected candidates",
    )
    expect(screen.getByTestId("comparison-note")).toHaveTextContent(
      "No requirements given",
    )
  })

  it("keeps qualitative verification wording instead of a checkmark", async () => {
    render(<PoolComparisonView poolId="pool-1" />)
    await screen.findByTestId("comparison-matrix")
    expect(screen.getByTestId("matrix-cell-proven")).toHaveTextContent("Proven")
    expect(screen.getByTestId("matrix-cell-skill-status")).toHaveTextContent(
      "Demonstrated",
    )
  })

  it("states absent evidence as absence, and related skills as not proof", async () => {
    render(<PoolComparisonView poolId="pool-1" />)
    await screen.findByTestId("comparison-matrix")
    const none = screen.getByTestId("matrix-cell-none")
    expect(none).toHaveTextContent("No published Docker evidence")
    expect(none).toHaveTextContent("Related (not proof): Kubernetes")
  })

  it("exposes the whole proof trail: skill → project → report → proof", async () => {
    render(<PoolComparisonView poolId="pool-1" />)
    await screen.findByTestId("comparison-matrix")
    expect(screen.getByTestId("matrix-cell-proof-link")).toHaveAttribute(
      "href",
      "/p/alpha/skills/fastapi",
    )
    fireEvent.click(screen.getByTestId("matrix-cell-trace-toggle"))
    const trail = screen.getByTestId("matrix-cell-trace")
    expect(within(trail).getByTestId("matrix-cell-project-link")).toHaveAttribute(
      "href",
      "/r/alpha",
    )
    expect(within(trail).getByTestId("matrix-cell-trace-link")).toHaveAttribute(
      "href",
      "/r/alpha#github",
    )
    expect(trail).toHaveTextContent("GitHub Proof")
  })

  it("shows an unavailable candidate rather than dropping them", async () => {
    render(<PoolComparisonView poolId="pool-1" />)
    await screen.findByTestId("comparison-matrix")
    const table = screen.getByTestId("comparison-matrix")
    expect(within(table).getByText("Bravo Candidate")).toBeInTheDocument()
    expect(screen.getAllByTestId("matrix-cell-unavailable").length).toBeGreaterThan(0)
    expect(screen.getByText("Unavailable")).toBeInTheDocument()
  })

  it("keeps recruiter judgement out of the evidence cells", async () => {
    render(<PoolComparisonView poolId="pool-1" />)
    await screen.findByTestId("comparison-matrix")
    expect(screen.getAllByTestId("comparison-column-status")[0]).toHaveTextContent(
      "Shortlisted",
    )
    expect(screen.getByTestId("comparison-column-note")).toHaveTextContent(
      "Strong walkthrough",
    )
    // The note lives outside the matrix table entirely.
    const table = screen.getByTestId("comparison-matrix")
    expect(table.textContent).not.toContain("Strong walkthrough")
  })

  it("shows no score, percentage or ranking", async () => {
    render(<PoolComparisonView poolId="pool-1" />)
    const table = await screen.findByTestId("comparison-matrix")
    // The evidence matrix itself must be free of any composite judgement.
    const text = (table.textContent ?? "").toLowerCase()
    expect(text).not.toMatch(/\d+\s*%/)
    expect(text).not.toContain("score")
    expect(text).not.toContain("best")
    expect(text).not.toContain("rank")
    expect(text).not.toContain("top candidate")
    // …and the page states the contract outright.
    const view = screen.getByTestId("recruiter-pool-comparison")
    expect(view.textContent?.toLowerCase()).toContain(
      "it is not a ranking and produces no score",
    )
  })

  it("re-runs the comparison against typed requirements", async () => {
    render(<PoolComparisonView poolId="pool-1" />)
    await screen.findByTestId("comparison-matrix")
    fireEvent.change(screen.getByTestId("comparison-query-input"), {
      target: { value: "FastAPI and Docker" },
    })
    fireEvent.click(screen.getByTestId("comparison-query-submit"))
    expect(routerPush).toHaveBeenCalledWith(
      "/recruiters/pools/pool-1/compare?ids=u-alpha%2Cu-bravo&q=FastAPI+and+Docker",
    )
  })

  it("shortlists from inside the comparison", async () => {
    mockUpdateCandidate.mockResolvedValue({ ...ALPHA, status: "interview" })
    render(<PoolComparisonView poolId="pool-1" />)
    await screen.findByTestId("comparison-matrix")
    fireEvent.change(screen.getAllByTestId("comparison-status-select")[0], {
      target: { value: "interview" },
    })
    await waitFor(() =>
      expect(mockUpdateCandidate).toHaveBeenCalledWith("pool-1", "u-alpha", {
        status: "interview",
      }),
    )
  })

  it("links back to the pool with the selection intact", async () => {
    render(<PoolComparisonView poolId="pool-1" />)
    await screen.findByTestId("comparison-matrix")
    expect(screen.getByTestId("comparison-back")).toHaveAttribute(
      "href",
      "/recruiters/pools/pool-1?selected=u-alpha%2Cu-bravo",
    )
  })
})
