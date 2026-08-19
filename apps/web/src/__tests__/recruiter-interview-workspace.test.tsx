/**
 * Interview Workspace UI — evidence-grounded prep for one (brief,
 * candidate) pair.
 *
 * Covers: the live verification checklist (grouped rows, exact
 * absence-of-evidence language, proof deep links, the shared evidence
 * drawer, fail-closed unavailable state), recruiter-private checklist
 * marks (toggle / clear / revert-on-failure), evidence-grounded question
 * generation (deterministic + LLM provenance, gap framing, stale-evidence
 * honesty), debounced autosaving notes with clear_* semantics, the
 * role-stage decision strip (role-scoped, optimistic with revert), and
 * the activity trail. Sweeps the workspace for "%" — transparent counts
 * only, never a score.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock("@/lib/recruiter-briefs-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/recruiter-briefs-api")>()),
  getInterviewWorkspace: vi.fn(),
  updateInterview: vi.fn(),
  generateInterviewQuestions: vi.fn(),
  setChecklistMark: vi.fn(),
  updateBriefCandidate: vi.fn(),
}))

vi.mock("@/lib/recruiter-search-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/recruiter-search-api")>()),
  viewEvidence: vi.fn(),
}))

import {
  generateInterviewQuestions,
  getInterviewWorkspace,
  setChecklistMark,
  updateBriefCandidate,
  updateInterview,
  type BriefCandidate,
  type HiringBriefListItem,
  type InterviewQuestions,
  type InterviewWorkspace,
  type MatrixCell,
} from "@/lib/recruiter-briefs-api"
import { viewEvidence } from "@/lib/recruiter-search-api"
import { InterviewWorkspaceView } from "../app/recruiters/briefs/[briefId]/interview/[studentId]/InterviewWorkspaceView"

const mockGetWorkspace = vi.mocked(getInterviewWorkspace)
const mockUpdateInterview = vi.mocked(updateInterview)
const mockGenerateQuestions = vi.mocked(generateInterviewQuestions)
const mockSetMark = vi.mocked(setChecklistMark)
const mockUpdateCandidate = vi.mocked(updateBriefCandidate)
const mockViewEvidence = vi.mocked(viewEvidence)

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

const PROVEN_CELL: MatrixCell = {
  state: "proven",
  matched_label: "Python",
  skill_status: "Demonstrated",
  direct: true,
  evidence_sources: ["GitHub Proof"],
  project_titles: ["Capstone"],
  note: null,
  proof_path: "/p/alpha/skills/python",
  projects: [],
  traces: [],
  related: [],
}

const NONE_CELL: MatrixCell = {
  state: "none",
  matched_label: null,
  skill_status: null,
  direct: true,
  evidence_sources: [],
  project_titles: [],
  note: null,
  proof_path: null,
  projects: [],
  traces: [],
  related: [],
}

const WORKSPACE: InterviewWorkspace = {
  brief: LIST_ITEM,
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
  pool_status: "shortlisted",
  checklist: {
    requirements: [
      { key: "concept:python", kind: "concept", display: "Python", required: true, concepts: ["python"] },
      { key: "evidence:github", kind: "evidence", display: "GitHub-verified project", required: true, concepts: [] },
      { key: "concept:nlp", kind: "concept", display: "Natural Language Processing", required: false, concepts: ["natural-language-processing"] },
    ],
    cells: {
      "concept:python": PROVEN_CELL,
      "evidence:github": NONE_CELL,
      "concept:nlp": NONE_CELL,
    },
    counts: {
      required_proven: 1,
      required_claimed: 0,
      required_total: 2,
      preferred_proven: 0,
      preferred_claimed: 0,
      preferred_total: 1,
    },
    available: true,
    unavailable_note: null,
    summary:
      "Alpha Candidate: published evidence for 1 of 2 required requirements.",
  },
  marks: [
    { requirement_key: "concept:python", state: "discussed", marked_at: "2026-08-19T00:00:00+00:00" },
  ],
  interview: null,
  questions: null,
  activity: [
    { event_type: "stage_changed", detail: { from: "saved", to: "shortlisted" }, created_at: "2026-08-19T01:00:00+00:00" },
    { event_type: "added", detail: {}, created_at: "2026-08-18T00:00:00+00:00" },
  ],
}

const QUESTIONS: InterviewQuestions = {
  items: [
    {
      id: "q1",
      requirement_key: "concept:python",
      kind: "evidence",
      question:
        "In Capstone, you published Python evidence. Walk me through how you used Python there — key decisions and trade-offs.",
      grounding: {
        requirement_display: "Python",
        state: "proven",
        matched_label: "Python",
        evidence_sources: ["GitHub Proof"],
        project_titles: ["Capstone"],
        proof_path: "/p/alpha/skills/python",
      },
      evidence_available: true,
    },
    {
      id: "q2",
      requirement_key: "evidence:github",
      kind: "gap",
      question:
        "No published GitHub-verified project was found. If this matters to the role, verify it during the interview.",
      grounding: {
        requirement_display: "GitHub-verified project",
        state: "none",
        matched_label: null,
        evidence_sources: [],
        project_titles: [],
        proof_path: null,
      },
      evidence_available: false,
    },
  ],
  source: "deterministic",
  generated_at: "2026-08-19T02:00:00+00:00",
  fallback_reason: null,
}

const SAVED_RECORD = {
  scheduled_at: null,
  interviewer_name: null,
  prep_notes: "Focus on FastAPI internals.",
  notes: null,
  decision_notes: null,
  updated_at: "2026-08-19T03:00:00+00:00",
}

function renderWorkspace() {
  return render(
    <InterviewWorkspaceView briefId="brief-1" studentUserId="u-alpha" />,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockGetWorkspace.mockResolvedValue(structuredClone(WORKSPACE))
  mockUpdateInterview.mockResolvedValue(SAVED_RECORD)
  mockGenerateQuestions.mockResolvedValue(structuredClone(QUESTIONS))
  mockSetMark.mockResolvedValue([
    { requirement_key: "concept:python", state: "discussed", marked_at: "2026-08-19T00:00:00+00:00" },
    { requirement_key: "concept:nlp", state: "follow_up", marked_at: "2026-08-19T04:00:00+00:00" },
  ])
  mockUpdateCandidate.mockResolvedValue({ status: "hired" } as unknown as BriefCandidate)
})

afterEach(() => {
  vi.useRealTimers()
})

describe("InterviewWorkspaceView", () => {
  it("renders the header, live checklist groups and exact evidence language — never a score", async () => {
    renderWorkspace()

    expect(await screen.findByTestId("interview-workspace")).toBeInTheDocument()
    expect(mockGetWorkspace).toHaveBeenCalledWith("brief-1", "u-alpha")

    // Header: candidate + role + pool stage + transparent coverage line.
    expect(screen.getByText("Alpha Candidate")).toBeInTheDocument()
    expect(screen.getByTestId("interview-open-passport")).toHaveAttribute("href", "/p/alpha")
    expect(screen.getByTestId("interview-summary")).toHaveTextContent(
      "published evidence for 1 of 2 required requirements",
    )
    expect(screen.getByTestId("interview-coverage")).toHaveTextContent(
      "Required evidence supported: 1 of 2",
    )

    // Checklist grouped Required / Required evidence / Preferred.
    const checklist = screen.getByTestId("interview-checklist")
    expect(within(checklist).getByText("Required")).toBeInTheDocument()
    expect(within(checklist).getByText("Required evidence")).toBeInTheDocument()
    expect(within(checklist).getByText("Preferred")).toBeInTheDocument()

    const rows = screen.getAllByTestId("interview-checklist-row")
    expect(rows).toHaveLength(3)
    // Proven: published-evidence affirmation + proof deep link.
    expect(rows[0]).toHaveTextContent("Python")
    expect(rows[0]).toHaveTextContent("✓ Published evidence")
    expect(within(rows[0]).getByTestId("interview-proof-link")).toHaveAttribute(
      "href",
      "/p/alpha/skills/python",
    )
    // Absence language contract: never "doesn't know" — always this exact framing.
    expect(rows[1]).toHaveTextContent("? No published evidence — verify during interview")

    // Transparent counts only — the workspace never renders a percentage.
    expect(screen.getByTestId("interview-workspace").textContent).not.toContain("%")
  })

  it("expands the shared evidence drawer behind a proven concept requirement", async () => {
    mockViewEvidence.mockResolvedValue({
      evidence: {
        groups: [
          {
            items: [
              {
                tier: "skill",
                requirement: "python",
                requirement_display: "Python",
                related_to: null,
                skill: "Python",
                skill_slug: "python",
                status: "Demonstrated",
                direct: true,
                note: null,
                evidence_sources: ["GitHub Proof"],
                proof_path: "/p/alpha/skills/python",
                projects: [],
                traces: [],
              },
            ],
          },
        ],
      },
    } as unknown as Awaited<ReturnType<typeof viewEvidence>>)
    renderWorkspace()
    await screen.findByTestId("interview-workspace")

    // Only the proven concept row offers the drawer (1 of 3 rows).
    const toggles = screen.getAllByTestId("requirement-view-proof")
    expect(toggles).toHaveLength(1)
    fireEvent.click(toggles[0])

    const drawer = await screen.findByTestId("requirement-proof-drawer")
    await waitFor(() =>
      expect(within(drawer).getByTestId("evidence-item")).toBeInTheDocument(),
    )
    expect(mockViewEvidence).toHaveBeenCalledWith({ skill: "python", candidate: "alpha" })
    expect(within(drawer).getByTestId("evidence-view-full")).toHaveAttribute(
      "href",
      "/p/alpha/skills/python",
    )
  })

  it("fails closed when the candidate's evidence is unavailable", async () => {
    mockGetWorkspace.mockResolvedValue({
      ...structuredClone(WORKSPACE),
      candidate: { ...WORKSPACE.candidate, public_slug: null, is_published: false },
      checklist: {
        requirements: [],
        cells: {},
        counts: {
          required_proven: 0,
          required_claimed: 0,
          required_total: 0,
          preferred_proven: 0,
          preferred_claimed: 0,
          preferred_total: 0,
        },
        available: false,
        unavailable_note: "This candidate's evidence is no longer publicly available.",
        summary: "Alpha Candidate: evidence is no longer publicly available.",
      },
    })
    renderWorkspace()
    await screen.findByTestId("interview-workspace")

    expect(screen.getByTestId("interview-checklist-unavailable")).toHaveTextContent(
      "unpublished or restricted",
    )
    expect(screen.getByText("Passport currently private")).toBeInTheDocument()
    expect(screen.queryByTestId("interview-checklist-row")).not.toBeInTheDocument()
    expect(screen.queryByTestId("interview-coverage")).not.toBeInTheDocument()
  })

  it("sets, clears and reverts recruiter-private checklist marks", async () => {
    renderWorkspace()
    await screen.findByTestId("interview-workspace")
    const rows = screen.getAllByTestId("interview-checklist-row")

    // Existing mark hydrates as pressed.
    expect(within(rows[0]).getByTestId("interview-mark-discussed")).toHaveAttribute(
      "aria-pressed",
      "true",
    )

    // Marking another requirement posts the axis key + state in the body.
    fireEvent.click(within(rows[2]).getByTestId("interview-mark-follow_up"))
    await waitFor(() =>
      expect(mockSetMark).toHaveBeenCalledWith("brief-1", "u-alpha", {
        requirement_key: "concept:nlp",
        state: "follow_up",
      }),
    )
    await waitFor(() =>
      expect(within(rows[2]).getByTestId("interview-mark-follow_up")).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    )

    // Clicking the active mark clears it (state null).
    mockSetMark.mockResolvedValue([
      { requirement_key: "concept:nlp", state: "follow_up", marked_at: "2026-08-19T04:00:00+00:00" },
    ])
    fireEvent.click(within(rows[0]).getByTestId("interview-mark-discussed"))
    await waitFor(() =>
      expect(mockSetMark).toHaveBeenCalledWith("brief-1", "u-alpha", {
        requirement_key: "concept:python",
        state: null,
      }),
    )

    // A failed mark reverts optimistic state and explains why.
    mockSetMark.mockRejectedValue(new Error("mark failed"))
    fireEvent.click(within(rows[1]).getByTestId("interview-mark-verified"))
    await waitFor(() => expect(screen.getByText("mark failed")).toBeInTheDocument())
    expect(within(rows[1]).getByTestId("interview-mark-verified")).toHaveAttribute(
      "aria-pressed",
      "false",
    )
  })

  it("generates grounded questions with honest provenance and gap framing", async () => {
    renderWorkspace()
    await screen.findByTestId("interview-workspace")

    // Empty state invites generation.
    expect(screen.getByText("No questions generated yet")).toBeInTheDocument()
    fireEvent.click(screen.getByText("Generate questions"))
    await waitFor(() =>
      expect(mockGenerateQuestions).toHaveBeenCalledWith("brief-1", "u-alpha", {}),
    )

    const cards = await screen.findAllByTestId("interview-question-card")
    expect(cards).toHaveLength(2)
    expect(screen.getByTestId("interview-questions-provenance")).toHaveTextContent(
      "Generated deterministically from published evidence — advisory only.",
    )

    // Evidence-backed question: kind badge + proof deep link, no stale note.
    expect(cards[0]).toHaveTextContent("Evidence-backed")
    expect(within(cards[0]).getByTestId("interview-question-proof")).toHaveAttribute(
      "href",
      "/p/alpha/skills/python",
    )
    expect(within(cards[0]).queryByTestId("interview-question-stale")).not.toBeInTheDocument()

    // Gap question: honest gap-to-verify framing — a gap is not
    // "stale evidence", and absence is never framed as a candidate deficit.
    expect(cards[1]).toHaveTextContent("Gap to verify")
    expect(cards[1]).toHaveTextContent("No published GitHub-verified project was found.")
    expect(within(cards[1]).queryByTestId("interview-question-stale")).not.toBeInTheDocument()

    // Regenerate goes back to the API with regenerate: true.
    fireEvent.click(screen.getByTestId("interview-regenerate-questions"))
    await waitFor(() =>
      expect(mockGenerateQuestions).toHaveBeenCalledWith("brief-1", "u-alpha", {
        regenerate: true,
      }),
    )
  })

  it("flags a stored evidence question whose proof has since been unpublished", async () => {
    const stale = structuredClone(QUESTIONS)
    stale.source = "llm"
    stale.items = [
      {
        ...stale.items[0],
        grounding: {
          ...stale.items[0].grounding,
          state: "none",
          proof_path: null,
        },
        evidence_available: false,
      },
    ]
    mockGetWorkspace.mockResolvedValue({
      ...structuredClone(WORKSPACE),
      questions: stale,
    })
    renderWorkspace()
    await screen.findByTestId("interview-workspace")

    const card = screen.getByTestId("interview-question-card")
    expect(within(card).getByTestId("interview-question-stale")).toHaveTextContent(
      "Previously referenced evidence is no longer published.",
    )
    expect(within(card).queryByTestId("interview-question-proof")).not.toBeInTheDocument()
    expect(screen.getByTestId("interview-questions-provenance")).toHaveTextContent(
      "AI-suggested from published evidence — advisory only.",
    )
  })

  it("autosaves notes with a debounce and diffs to a minimal patch", async () => {
    renderWorkspace()
    await screen.findByTestId("interview-workspace")

    vi.useFakeTimers()
    fireEvent.change(screen.getByTestId("interview-prep-notes"), {
      target: { value: "Focus on FastAPI internals." },
    })
    // Debounced: nothing is sent while typing settles.
    expect(mockUpdateInterview).not.toHaveBeenCalled()
    vi.advanceTimersByTime(801)
    vi.useRealTimers()

    await waitFor(() =>
      expect(mockUpdateInterview).toHaveBeenCalledWith("brief-1", "u-alpha", {
        prep_notes: "Focus on FastAPI internals.",
      }),
    )
    await waitFor(() =>
      expect(screen.getByTestId("interview-notes-status")).toHaveTextContent("Saved ✓"),
    )
  })

  it("saves on blur and sends clear_* when a saved field is emptied", async () => {
    mockGetWorkspace.mockResolvedValue({
      ...structuredClone(WORKSPACE),
      interview: structuredClone(SAVED_RECORD),
    })
    renderWorkspace()
    await screen.findByTestId("interview-workspace")

    const prep = screen.getByTestId("interview-prep-notes")
    expect(prep).toHaveValue("Focus on FastAPI internals.")

    fireEvent.change(prep, { target: { value: "" } })
    fireEvent.blur(prep)

    await waitFor(() =>
      expect(mockUpdateInterview).toHaveBeenCalledWith("brief-1", "u-alpha", {
        clear_prep_notes: true,
      }),
    )
  })

  it("surfaces a failed autosave with a retry", async () => {
    mockUpdateInterview.mockRejectedValue(new Error("offline"))
    renderWorkspace()
    await screen.findByTestId("interview-workspace")

    const notes = screen.getByTestId("interview-notes-input")
    fireEvent.change(notes, { target: { value: "Great systems answers." } })
    fireEvent.blur(notes)

    await waitFor(() =>
      expect(screen.getByTestId("interview-notes-status")).toHaveTextContent("Couldn't save"),
    )

    // Retry re-sends the same still-unsaved diff.
    mockUpdateInterview.mockResolvedValue(SAVED_RECORD)
    fireEvent.click(screen.getByTestId("interview-notes-retry"))
    await waitFor(() =>
      expect(mockUpdateInterview).toHaveBeenLastCalledWith("brief-1", "u-alpha", {
        notes: "Great systems answers.",
      }),
    )
    await waitFor(() =>
      expect(screen.getByTestId("interview-notes-status")).toHaveTextContent("Saved ✓"),
    )
  })

  it("moves the ROLE-SCOPED stage from the decision strip", async () => {
    renderWorkspace()
    await screen.findByTestId("interview-workspace")

    fireEvent.click(screen.getByTestId("interview-stage-hired"))
    await waitFor(() =>
      expect(mockUpdateCandidate).toHaveBeenCalledWith("brief-1", "u-alpha", {
        status: "hired",
      }),
    )
    // Optimistic badge + button state; the strip reminds this is role-scoped.
    expect(screen.getByTestId("interview-stage-hired")).toBeDisabled()
    expect(
      screen.getByText("Stage changes apply to this role only — never to other briefs."),
    ).toBeInTheDocument()

    // The any-stage select carries the full 9-stage vocabulary.
    const select = screen.getByTestId("interview-stage-select")
    expect(
      within(select).getAllByRole("option").map((o) => (o as HTMLOptionElement).value),
    ).toEqual([
      "saved", "reviewing", "shortlisted", "contacted", "interview",
      "decision", "hired", "passed", "archived",
    ])
  })

  it("reverts a failed stage move and explains why", async () => {
    mockUpdateCandidate.mockRejectedValue(new Error("stage move failed"))
    renderWorkspace()
    await screen.findByTestId("interview-workspace")

    fireEvent.click(screen.getByTestId("interview-stage-passed"))
    await waitFor(() =>
      expect(screen.getByText("stage move failed")).toBeInTheDocument(),
    )
    expect(screen.getByTestId("interview-stage-select")).toHaveValue("shortlisted")
  })

  it("shows the recruiter-private activity trail on demand", async () => {
    renderWorkspace()
    await screen.findByTestId("interview-workspace")

    expect(screen.queryAllByTestId("interview-activity-event")).toHaveLength(0)
    fireEvent.click(screen.getByTestId("interview-activity-toggle"))

    const events = screen.getAllByTestId("interview-activity-event")
    expect(events).toHaveLength(2)
    expect(events[0]).toHaveTextContent("Moved to Shortlisted")
    expect(events[1]).toHaveTextContent("Added to role")
  })

  it("shows a retryable error when the workspace fails to load", async () => {
    mockGetWorkspace.mockRejectedValueOnce(new Error("Failed to load the interview workspace."))
    renderWorkspace()

    expect(
      await screen.findByText("Failed to load the interview workspace."),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByText("Try again"))
    await waitFor(() => expect(screen.getByTestId("interview-workspace")).toBeInTheDocument())
  })
})
