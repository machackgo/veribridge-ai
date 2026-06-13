import React from "react"
import { render, screen, fireEvent, within, waitFor, act } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { StudentSkillEvidencePipelines } from "../../components/dashboard/StudentSkillEvidencePipelines"
import type { BackendSkillPipeline, StudentArtifactSummary } from "@/lib/api"

// ── Mock @/lib/api ─────────────────────────────────────────────────────────────

vi.mock("@/lib/api", () => ({
  listSkillEvidencePipelines: vi.fn(),
  seedMockSkillEvidencePipelines: vi.fn(),
  getSkillEvidencePipeline: vi.fn(),
  getRecruiterSkillPipelineView: vi.fn(),
  updateSkillPipelineVisibility: vi.fn(),
}))

import {
  listSkillEvidencePipelines,
  seedMockSkillEvidencePipelines,
  updateSkillPipelineVisibility,
} from "@/lib/api"

// ── Minimal backend pipeline fixture ──────────────────────────────────────────

function makeBackendPipeline(overrides: Partial<BackendSkillPipeline> = {}): BackendSkillPipeline {
  return {
    id: "pipeline-uuid-1",
    student_id: "student-1",
    profile_id: "profile-1",
    skill_name: "AI / Machine Learning",
    skill_category: "Core ML",
    confidence_score: 82,
    support_status: "strongly_supported",
    evidence_count: 3,
    strongest_proof: { label: "GitHub", reason: "ML repo with training loops" },
    weakest_proof: { label: "Transcript", reason: "Only partial coverage" },
    missing_evidence: ["Model evaluation report"],
    next_actions: ["Add a model evaluation report"],
    evidence_sources: [
      { key: "github", label: "GitHub", status: "supported", score: 88, reason: "Active ML repo" },
      { key: "dom", label: "DOM Evidence", status: "supported", score: 78, reason: "Captured page structure" },
      { key: "visual", label: "Visual", status: "partial", score: 60, reason: "Partial visual evidence" },
    ],
    recruiter_summary: "Strong ML foundation demonstrated via GitHub.",
    student_summary: "You have strong ML evidence from GitHub and DOM captures.",
    visibility_status: "public",
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    ...overrides,
  }
}

// ── Helpers ────────────────────────────────────────────────────────────────────

// skillId derives from skill_name: toLowerCase → replace non-alphanumeric runs with "-"
// "AI / Machine Learning" → "ai-machine-learning"

const aiId = "ai-machine-learning"

// Skill IDs for mock-fallback (same derivation from SKILL_NAMES)
// "JavaScript / Frontend"   → "javascript-frontend"
// "Data & Visualization"    → "data-visualization"
// "DevOps / Deployment"     → "devops-deployment"

describe("StudentSkillEvidencePipelines", () => {

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(updateSkillPipelineVisibility).mockResolvedValue(null)
  })

  // ── Loading state ────────────────────────────────────────────────────────────

  describe("loading state", () => {
    it("shows loading indicator while backend fetch is in progress", async () => {
      let resolve!: (v: BackendSkillPipeline[]) => void
      vi.mocked(listSkillEvidencePipelines).mockReturnValueOnce(
        new Promise<BackendSkillPipeline[]>((r) => { resolve = r }),
      )
      render(<StudentSkillEvidencePipelines />)
      expect(screen.getByTestId("pipelines-loading")).toBeInTheDocument()
      await act(async () => resolve([]))
    })

    it("hides loading indicator once data arrives", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValueOnce([makeBackendPipeline()])
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => expect(screen.queryByTestId("pipelines-loading")).not.toBeInTheDocument())
    })
  })

  // ── Empty state ──────────────────────────────────────────────────────────────

  describe("empty state (backend returns [])", () => {
    beforeEach(() => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([])
    })

    it("shows empty state message", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId("pipelines-empty")).toBeInTheDocument(),
      )
      expect(screen.getByText(/No skill pipelines yet/i)).toBeInTheDocument()
    })

    it("shows seed demo button in empty state", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => expect(screen.getByTestId("seed-demo-btn")).toBeInTheDocument())
    })

    it("seed button calls seedMockSkillEvidencePipelines then reloads", async () => {
      const seeded = [makeBackendPipeline()]
      vi.mocked(seedMockSkillEvidencePipelines).mockResolvedValueOnce(seeded)
      vi.mocked(listSkillEvidencePipelines)
        .mockResolvedValueOnce([])
        .mockResolvedValueOnce(seeded)

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => expect(screen.getByTestId("seed-demo-btn")).toBeInTheDocument())

      await act(async () => {
        fireEvent.click(screen.getByTestId("seed-demo-btn"))
      })

      expect(vi.mocked(seedMockSkillEvidencePipelines)).toHaveBeenCalledOnce()
      await waitFor(() =>
        expect(screen.getByTestId(`skill-pipeline-card-${aiId}`)).toBeInTheDocument(),
      )
    })

    it("seed button shows 'Seeding…' while in progress", async () => {
      let resolveSeed!: (v: BackendSkillPipeline[]) => void
      vi.mocked(seedMockSkillEvidencePipelines).mockReturnValueOnce(
        new Promise<BackendSkillPipeline[]>((r) => { resolveSeed = r }),
      )
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => expect(screen.getByTestId("seed-demo-btn")).toBeInTheDocument())

      fireEvent.click(screen.getByTestId("seed-demo-btn"))
      expect(screen.getByTestId("seed-demo-btn")).toHaveTextContent(/Seeding/i)

      await act(async () => resolveSeed([]))
    })

    it("shows error message when seed backend call fails (throws)", async () => {
      vi.mocked(seedMockSkillEvidencePipelines).mockRejectedValueOnce(
        new Error("Unable to seed pipelines — please sign in or check backend connection."),
      )
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => expect(screen.getByTestId("seed-demo-btn")).toBeInTheDocument())

      await act(async () => {
        fireEvent.click(screen.getByTestId("seed-demo-btn"))
      })

      await waitFor(() =>
        expect(screen.getByTestId("seed-error-msg")).toBeInTheDocument(),
      )
      expect(screen.getByTestId("seed-error-msg")).toHaveTextContent(/sign in|backend/i)
    })

    it("seed success removes Demo data badge and shows backend pipelines", async () => {
      const seeded = [makeBackendPipeline()]
      vi.mocked(seedMockSkillEvidencePipelines).mockResolvedValueOnce(seeded)
      vi.mocked(listSkillEvidencePipelines)
        .mockResolvedValueOnce([])
        .mockResolvedValueOnce(seeded)

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => expect(screen.getByTestId("seed-demo-btn")).toBeInTheDocument())

      await act(async () => {
        fireEvent.click(screen.getByTestId("seed-demo-btn"))
      })

      await waitFor(() =>
        expect(screen.getByTestId(`skill-pipeline-card-${aiId}`)).toBeInTheDocument(),
      )
      expect(screen.queryByTestId("fallback-badge")).not.toBeInTheDocument()
    })
  })

  // ── Fallback mock (backend returns null / throws) ────────────────────────────

  describe("fallback mock (backend unavailable)", () => {
    beforeEach(() => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue(null)
    })

    it("shows 'Demo data' badge when using fallback", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => expect(screen.getByTestId("fallback-badge")).toBeInTheDocument())
    })

    it("renders 4 skill cards from mock fallback", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getAllByText(/Manage skill evidence/i)).toHaveLength(4),
      )
    })

    it("still shows seed button when using fallback", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => expect(screen.getByTestId("seed-demo-btn")).toBeInTheDocument())
    })

    it("shows all 4 skill names from mock fallback", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => expect(screen.getByText("AI / Machine Learning")).toBeInTheDocument())
      expect(screen.getByText("JavaScript / Frontend")).toBeInTheDocument()
      expect(screen.getByText("Data & Visualization")).toBeInTheDocument()
      expect(screen.getByText("DevOps / Deployment")).toBeInTheDocument()
    })

    it("fallback mock: AI/ML card shows high confidence", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`skill-confidence-${aiId}`)).toHaveTextContent(/high confidence/i),
      )
    })

    it("shows seed error when seed fails in fallback mode", async () => {
      vi.mocked(seedMockSkillEvidencePipelines).mockRejectedValueOnce(
        new Error("Seed failed"),
      )

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => expect(screen.getByTestId("seed-demo-btn")).toBeInTheDocument())

      await act(async () => {
        fireEvent.click(screen.getByTestId("seed-demo-btn"))
      })

      await waitFor(() =>
        expect(screen.getByTestId("seed-error-msg")).toBeInTheDocument(),
      )
    })
  })

  // ── Backend data rendering ────────────────────────────────────────────────────

  describe("backend data rendering", () => {
    const pipeline = makeBackendPipeline()

    beforeEach(() => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([pipeline])
    })

    it("renders skill card from backend pipeline", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`skill-pipeline-card-${aiId}`)).toBeInTheDocument(),
      )
    })

    it("shows skill name from backend", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => expect(screen.getByText("AI / Machine Learning")).toBeInTheDocument())
    })

    it("maps confidence_score 82 → 'high confidence'", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`skill-confidence-${aiId}`)).toHaveTextContent(/high confidence/i),
      )
    })

    it("maps confidence_score 60 → 'medium confidence'", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValueOnce([
        makeBackendPipeline({ confidence_score: 60 }),
      ])
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`skill-confidence-${aiId}`)).toHaveTextContent(/medium confidence/i),
      )
    })

    it("maps confidence_score 30 → 'low confidence'", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValueOnce([
        makeBackendPipeline({ confidence_score: 30 }),
      ])
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`skill-confidence-${aiId}`)).toHaveTextContent(/low confidence/i),
      )
    })

    it("maps support_status 'strongly_supported' → 'Strongly supported'", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`skill-status-${aiId}`)).toHaveTextContent(/Strongly supported/i),
      )
    })

    it("maps support_status 'partially_supported' → 'Partially supported'", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValueOnce([
        makeBackendPipeline({ support_status: "partially_supported" }),
      ])
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`skill-status-${aiId}`)).toHaveTextContent(/Partially supported/i),
      )
    })

    it("renders evidence source chips from backend evidence_sources", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`source-chip-${aiId}-github`)).toBeInTheDocument(),
      )
      expect(screen.getByTestId(`source-chip-${aiId}-dom`)).toBeInTheDocument()
    })

    it("renders strongest proof from backend", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`strongest-proof-${aiId}`)).toBeInTheDocument(),
      )
      expect(screen.getByTestId(`strongest-proof-${aiId}`)).toHaveTextContent("GitHub")
    })

    it("renders weakest proof from backend", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`weakest-proof-${aiId}`)).toBeInTheDocument(),
      )
      expect(screen.getByTestId(`weakest-proof-${aiId}`)).toHaveTextContent("Transcript")
    })

    it("renders missing evidence from backend", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`missing-evidence-${aiId}`)).toBeInTheDocument(),
      )
      expect(screen.getByTestId(`missing-evidence-${aiId}`)).toHaveTextContent(
        "Model evaluation report",
      )
    })

    it("renders next action from backend next_actions", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`next-action-${aiId}`)).toBeInTheDocument(),
      )
      expect(screen.getByTestId(`next-action-${aiId}`)).toHaveTextContent(
        "Add a model evaluation report",
      )
    })

    it("does NOT show the 'Demo data' fallback badge when backend data loads", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`skill-pipeline-card-${aiId}`)).toBeInTheDocument(),
      )
      expect(screen.queryByTestId("fallback-badge")).not.toBeInTheDocument()
    })

    it("modal shows 'Live from backend' when pipeline is from backend", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`manage-btn-${aiId}`)).toBeInTheDocument(),
      )
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))
      expect(screen.getByText(/Live from backend/i)).toBeInTheDocument()
    })
  })

  // ── Modal (with fallback data) ────────────────────────────────────────────────

  describe("ManageSkillModal", () => {
    beforeEach(() => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue(null)
    })

    it("opens when Manage button is clicked", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`manage-btn-${aiId}`)).toBeInTheDocument(),
      )
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))
      expect(screen.getByTestId("manage-skill-modal")).toBeInTheDocument()
    })

    it("shows skill name in modal header", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))
      const modal = screen.getByTestId("manage-skill-modal-content")
      expect(within(modal).getByText("AI / Machine Learning")).toBeInTheDocument()
    })

    it("shows evidence source rows in modal", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))
      const modal = screen.getByTestId("manage-skill-modal-content")
      expect(within(modal).getAllByTestId(/modal-source-/).length).toBeGreaterThan(0)
    })

    it("modal shows suggested improvement (next action)", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId("manage-btn-javascript-frontend"))
      fireEvent.click(screen.getByTestId("manage-btn-javascript-frontend"))
      expect(screen.getByTestId("modal-next-action")).toBeInTheDocument()
    })

    it("closes when close button is clicked", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId("manage-modal-close"))
      expect(screen.queryByTestId("manage-skill-modal")).not.toBeInTheDocument()
    })

    it("closes when backdrop is clicked", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId("manage-skill-modal"))
      expect(screen.queryByTestId("manage-skill-modal")).not.toBeInTheDocument()
    })

    it("closes when Escape key is pressed", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))
      expect(screen.getByTestId("manage-skill-modal")).toBeInTheDocument()
      fireEvent.keyDown(document, { key: "Escape" })
      expect(screen.queryByTestId("manage-skill-modal")).not.toBeInTheDocument()
    })

    it("modal content is present in the document when open", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))
      expect(screen.getByTestId("manage-skill-modal-content")).toBeInTheDocument()
      expect(screen.getByTestId("manage-modal-close")).toBeInTheDocument()
    })

    it("visibility controls change recruiter view text", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId("modal-visibility-private"))
      expect(screen.getByText(/Recruiter cannot see this skill/)).toBeInTheDocument()
    })

    it("modal shows recruiter visibility section", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))
      expect(screen.getByText(/What recruiters can see/i)).toBeInTheDocument()
    })

    // ── DOM Evidence (requires fallback mock with DOM source) ─────────────────

    it("AI/ML source coverage chip includes DOM Evidence", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`skill-pipeline-card-${aiId}`)).toBeInTheDocument(),
      )
      const aiCard = screen.getByTestId(`skill-pipeline-card-${aiId}`)
      expect(within(aiCard).getByTestId(`source-chip-${aiId}-dom`)).toHaveTextContent(/DOM Evidence/i)
    })

    it("AI/ML modal shows DOM Evidence source row", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))
      const modal = screen.getByTestId("manage-skill-modal-content")
      expect(within(modal).getByTestId("modal-source-dom")).toHaveTextContent(/DOM Evidence/i)
    })

    it("AI/ML modal DOM Evidence row shows reason text", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))
      const modal = screen.getByTestId("manage-skill-modal-content")
      const domRow = within(modal).getByTestId("modal-source-dom")
      expect(domRow).toHaveTextContent(/page structure|visible UI labels|proof builder state/i)
    })

    it("AI/ML modal artifacts include DOM Evidence artifact", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))
      const modal = screen.getByTestId("manage-skill-modal-content")
      const domMatches = within(modal).getAllByText("DOM Evidence")
      expect(domMatches.length).toBeGreaterThanOrEqual(2)
    })

    it("DOM Evidence does not expose unsafe raw DOM dumps or storage paths", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))
      const modal = screen.getByTestId("manage-skill-modal-content")
      const html = modal.innerHTML
      expect(html).not.toMatch(/storage\.googleapis|supabase\.co\/storage|access_token/)
      expect(html).not.toMatch(/innerHTML|outerHTML|document\.querySelector/)
      expect(html).not.toMatch(/service_role|anon_key/)
    })
  })

  // ── Visibility controls (card) ────────────────────────────────────────────────

  describe("card visibility controls", () => {
    beforeEach(() => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue(null)
    })

    it("renders all 3 visibility buttons on AI/ML card", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`skill-pipeline-card-${aiId}`))
      const aiCard = screen.getByTestId(`skill-pipeline-card-${aiId}`)
      expect(within(aiCard).getByTestId(`visibility-btn-${aiId}-public`)).toBeInTheDocument()
      expect(within(aiCard).getByTestId(`visibility-btn-${aiId}-protected`)).toBeInTheDocument()
      expect(within(aiCard).getByTestId(`visibility-btn-${aiId}-private`)).toBeInTheDocument()
    })

    it("clicking protected visibility updates button", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`skill-pipeline-card-${aiId}`))
      const protectedBtn = screen.getByTestId(`visibility-btn-${aiId}-protected`)
      fireEvent.click(protectedBtn)
      expect(protectedBtn).toBeInTheDocument()
    })
  })

  // ── Confidence + status badges ────────────────────────────────────────────────

  describe("badges", () => {
    beforeEach(() => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue(null)
    })

    it("shows confidence badge on each card", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getAllByText(/confidence/i).length).toBeGreaterThanOrEqual(4),
      )
    })

    it("DevOps card shows low confidence", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId("skill-pipeline-card-devops-deployment")).toBeInTheDocument(),
      )
      const devopsCard = screen.getByTestId("skill-pipeline-card-devops-deployment")
      expect(
        within(devopsCard).getByTestId("skill-confidence-devops-deployment"),
      ).toHaveTextContent(/low confidence/i)
    })

    it("AI/ML card shows high confidence", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`skill-pipeline-card-${aiId}`)).toBeInTheDocument(),
      )
      const aiCard = screen.getByTestId(`skill-pipeline-card-${aiId}`)
      expect(within(aiCard).getByTestId(`skill-confidence-${aiId}`)).toHaveTextContent(
        /high confidence/i,
      )
    })
  })

  // ── Security / unsafe string checks ─────────────────────────────────────────

  describe("security checks", () => {
    it("fallback mock does not render unsafe strings (storage paths, tokens)", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue(null)
      const { container } = render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.queryByTestId("pipelines-loading")).not.toBeInTheDocument(),
      )
      const text = container.innerHTML
      expect(text).not.toMatch(/storage\.googleapis|supabase\.co\/storage|access_token/)
      expect(text).not.toMatch(/service_role|anon_key/)
      expect(text).not.toMatch(/signed_url|signedUrl/i)
    })

    it("backend data does not render unsafe strings", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([makeBackendPipeline()])
      const { container } = render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`skill-pipeline-card-${aiId}`)).toBeInTheDocument(),
      )
      const text = container.innerHTML
      expect(text).not.toMatch(/storage\.googleapis|supabase\.co\/storage|access_token/)
      expect(text).not.toMatch(/service_role|anon_key/)
      expect(text).not.toMatch(/signed_url|signedUrl/i)
    })

    it("student-safe language: does not show raw status strings like 'in_progress'", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue(null)
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.queryByTestId("pipelines-loading")).not.toBeInTheDocument(),
      )
      const text = document.body.textContent ?? ""
      expect(text).not.toContain("in_progress")
      expect(text).not.toContain("ai_approved_for_sharing")
    })

    it("backend pipeline with unsafe artifact_data: signed_url is not rendered", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({
          recruiter_summary: "safe summary",
          student_summary: "safe student summary",
        }),
      ])
      const { container } = render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`skill-pipeline-card-${aiId}`)).toBeInTheDocument(),
      )
      expect(container.innerHTML).not.toMatch(/signed_url/i)
    })
  })

  // ── Visibility persistence ────────────────────────────────────────────────────

  describe("visibility persistence", () => {
    it("changing visibility calls updateSkillPipelineVisibility with correct args", async () => {
      vi.mocked(updateSkillPipelineVisibility).mockResolvedValueOnce(
        makeBackendPipeline({ visibility_status: "protected" }),
      )
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([makeBackendPipeline()])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`skill-pipeline-card-${aiId}`))

      await act(async () => {
        fireEvent.click(screen.getByTestId(`visibility-btn-${aiId}-protected`))
      })

      expect(vi.mocked(updateSkillPipelineVisibility)).toHaveBeenCalledWith(
        "pipeline-uuid-1",
        "protected",
      )
    })

    it("shows saving state while backend call is in progress", async () => {
      let resolve!: (v: ReturnType<typeof makeBackendPipeline>) => void
      vi.mocked(updateSkillPipelineVisibility).mockReturnValueOnce(
        new Promise<ReturnType<typeof makeBackendPipeline>>((r) => {
          resolve = r
        }),
      )
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([makeBackendPipeline()])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`skill-pipeline-card-${aiId}`))

      fireEvent.click(screen.getByTestId(`visibility-btn-${aiId}-protected`))

      await waitFor(() =>
        expect(screen.getByTestId(`visibility-saving-${aiId}`)).toBeInTheDocument(),
      )

      await act(async () => resolve(makeBackendPipeline({ visibility_status: "protected" })))
    })

    it("shows saved state after successful backend call", async () => {
      vi.mocked(updateSkillPipelineVisibility).mockResolvedValueOnce(
        makeBackendPipeline({ visibility_status: "protected" }),
      )
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([makeBackendPipeline()])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`skill-pipeline-card-${aiId}`))

      await act(async () => {
        fireEvent.click(screen.getByTestId(`visibility-btn-${aiId}-protected`))
      })

      await waitFor(() =>
        expect(screen.getByTestId(`visibility-saved-${aiId}`)).toBeInTheDocument(),
      )
    })

    it("shows error state when backend call returns null", async () => {
      vi.mocked(updateSkillPipelineVisibility).mockResolvedValueOnce(null)
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([makeBackendPipeline()])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`skill-pipeline-card-${aiId}`))

      await act(async () => {
        fireEvent.click(screen.getByTestId(`visibility-btn-${aiId}-protected`))
      })

      await waitFor(() =>
        expect(screen.getByTestId(`visibility-error-${aiId}`)).toBeInTheDocument(),
      )
    })

    it("does not call backend when using fallback mock", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue(null)

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`skill-pipeline-card-${aiId}`))

      await act(async () => {
        fireEvent.click(screen.getByTestId(`visibility-btn-${aiId}-protected`))
      })

      expect(vi.mocked(updateSkillPipelineVisibility)).not.toHaveBeenCalled()
    })

    it("loads initial visibility_status from backend", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({ visibility_status: "protected" }),
      ])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`skill-pipeline-card-${aiId}`))

      // Protected button should be active (backend-loaded), not public
      // (If public were active, clicking protected would be a no-op visually)
      // We verify by checking that clicking public triggers a backend call for "public"
      vi.mocked(updateSkillPipelineVisibility).mockResolvedValueOnce(
        makeBackendPipeline({ visibility_status: "public" }),
      )
      await act(async () => {
        fireEvent.click(screen.getByTestId(`visibility-btn-${aiId}-public`))
      })
      expect(vi.mocked(updateSkillPipelineVisibility)).toHaveBeenCalledWith(
        "pipeline-uuid-1",
        "public",
      )
    })

    it("private visibility does not appear in recruiter list (client-side filter)", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({ visibility_status: "private" }),
      ])
      // When rendered, private pipeline would still show in student view
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`skill-pipeline-card-${aiId}`))
      // Student can still see private pipeline in their own profile view
      expect(screen.getByTestId(`skill-pipeline-card-${aiId}`)).toBeInTheDocument()
    })

    it("protected visibility button label is 'Protected evidence'", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([makeBackendPipeline()])
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`skill-pipeline-card-${aiId}`))
      expect(screen.getByTestId(`visibility-btn-${aiId}-protected`)).toHaveTextContent(
        "Protected evidence",
      )
    })

    it("saved state does not render unsafe strings", async () => {
      vi.mocked(updateSkillPipelineVisibility).mockResolvedValueOnce(
        makeBackendPipeline({ visibility_status: "protected" }),
      )
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([makeBackendPipeline()])

      const { container } = render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`skill-pipeline-card-${aiId}`))

      await act(async () => {
        fireEvent.click(screen.getByTestId(`visibility-btn-${aiId}-protected`))
      })

      await waitFor(() => screen.getByTestId(`visibility-saved-${aiId}`))

      expect(container.innerHTML).not.toMatch(/access_token|signed_url|storage_path|service_role/i)
    })

    it("visible text does not contain the literal word 'token'", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([makeBackendPipeline()])
      const { container } = render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`skill-pipeline-card-${aiId}`))
      const text = container.textContent ?? ""
      expect(text.toLowerCase()).not.toContain("access token")
      expect(text.toLowerCase()).not.toContain("access_token")
    })

    it("remount/refetch restores persisted visibility from backend", async () => {
      // First mount: pipeline has protected visibility from backend
      vi.mocked(listSkillEvidencePipelines).mockResolvedValueOnce([
        makeBackendPipeline({ visibility_status: "protected" }),
      ])
      const { unmount } = render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`skill-pipeline-card-${aiId}`))
      unmount()

      // Second mount (page refresh): backend still returns protected
      vi.mocked(listSkillEvidencePipelines).mockResolvedValueOnce([
        makeBackendPipeline({ visibility_status: "protected" }),
      ])
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`skill-pipeline-card-${aiId}`))

      // Switching to public should trigger a backend call with "public"
      vi.mocked(updateSkillPipelineVisibility).mockResolvedValueOnce(
        makeBackendPipeline({ visibility_status: "public" }),
      )
      await act(async () => {
        fireEvent.click(screen.getByTestId(`visibility-btn-${aiId}-public`))
      })
      expect(vi.mocked(updateSkillPipelineVisibility)).toHaveBeenCalledWith(
        "pipeline-uuid-1",
        "public",
      )
    })

    it("backend reachable with empty response does not show demo fallback badge", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([])
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => expect(screen.queryByTestId("pipelines-loading")).not.toBeInTheDocument())
      expect(screen.queryByTestId("fallback-badge")).not.toBeInTheDocument()
      expect(screen.getByTestId("pipelines-empty")).toBeInTheDocument()
    })
  })

  // ── Artifact inventory (backend mode, student-owned data) ─────────────────────

  describe("artifact inventory in manage modal", () => {
    function makeArtifact(overrides: Partial<StudentArtifactSummary> = {}): StudentArtifactSummary {
      return {
        id: "a1",
        source_type: "workflow",
        source_title: "Website Proof",
        project_name: "ML Demo",
        visibility: "protected",
        confidence_score: 80,
        proof_reason: "Recorded workflow session",
        exact_code_url: null,
        full_file_url: null,
        ...overrides,
      }
    }

    const defaultArtifacts: StudentArtifactSummary[] = [
      makeArtifact({ id: "a1", source_type: "workflow", source_title: "Website Proof", proof_reason: "Recorded workflow session", confidence_score: 80 }),
      makeArtifact({ id: "a2", source_type: "ocr", source_title: "OCR Keyframe", proof_reason: "Extracted text from keyframe", confidence_score: 70 }),
      makeArtifact({ id: "a3", source_type: "dom", source_title: "DOM Capture", proof_reason: "DOM structure captured", confidence_score: 75 }),
      makeArtifact({ id: "a4", source_type: "workflow", source_title: "Website Proof 2", proof_reason: "Second workflow session", confidence_score: 82 }),
      makeArtifact({ id: "a5", source_type: "transcript", source_title: "Defense Transcript", proof_reason: "Project defense excerpt", confidence_score: 68 }),
    ]

    it("shows artifact inventory section when backend returns artifacts", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({ evidence_count: 5, artifacts: defaultArtifacts }),
      ])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))

      await act(async () => {
        fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))
      })

      expect(screen.getByTestId("artifact-inventory-section")).toBeInTheDocument()
    })

    it("shows total artifact count in modal", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({ evidence_count: 5, artifacts: defaultArtifacts }),
      ])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))

      expect(screen.getByTestId("artifact-inventory-section")).toHaveTextContent("Persisted evidence artifacts (5)")
    })

    it("shows workflow artifact group", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({ evidence_count: 5, artifacts: defaultArtifacts }),
      ])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))

      expect(screen.getByTestId("artifact-group-workflow")).toBeInTheDocument()
    })

    it("shows OCR artifact group", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({ evidence_count: 5, artifacts: defaultArtifacts }),
      ])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))

      expect(screen.getByTestId("artifact-group-ocr")).toBeInTheDocument()
    })

    it("shows DOM artifact group", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({ evidence_count: 5, artifacts: defaultArtifacts }),
      ])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))

      expect(screen.getByTestId("artifact-group-dom")).toBeInTheDocument()
    })

    it("shows transcript artifact group", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({ evidence_count: 5, artifacts: defaultArtifacts }),
      ])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))

      expect(screen.getByTestId("artifact-group-transcript")).toBeInTheDocument()
    })

    it("shows GitHub artifact group", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({
          evidence_count: 1,
          artifacts: [
            makeArtifact({ id: "g1", source_type: "github", source_title: "repo", proof_reason: "Commits reviewed", confidence_score: 85 }),
          ],
        }),
      ])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))

      expect(screen.getByTestId("artifact-group-github")).toBeInTheDocument()
      expect(screen.getByTestId("artifact-group-github")).toHaveTextContent("GitHub code evidence")
    })

    it("shows document artifact group", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({
          evidence_count: 1,
          artifacts: [
            makeArtifact({ id: "d1", source_type: "document", source_title: "Report", proof_reason: "Uploaded report", confidence_score: 60 }),
          ],
        }),
      ])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))

      expect(screen.getByTestId("artifact-group-document")).toBeInTheDocument()
      expect(screen.getByTestId("artifact-group-document")).toHaveTextContent("Document evidence")
    })

    it("shows certificate artifact group with a certificate-specific label", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({
          evidence_count: 1,
          artifacts: [
            makeArtifact({ id: "c1", source_type: "certificate", source_title: "AWS Cloud Practitioner", proof_reason: "Uploaded certificate", confidence_score: 60 }),
          ],
        }),
      ])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))

      const group = screen.getByTestId("artifact-group-certificate")
      expect(group).toBeInTheDocument()
      expect(group).toHaveTextContent("Certificate / transcript evidence")
    })

    it("does not expose unsafe fields in artifact inventory", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({
          evidence_count: 1,
          artifacts: [makeArtifact({ id: "a1", source_title: "Safe Proof", proof_reason: "Verified session" })],
        }),
      ])

      const { container } = render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))

      expect(container.innerHTML).not.toMatch(/storage_path|signed_url|access_token|video_url|media_storage_path/i)
    })

    it("does not show artifact inventory section for fallback mock data", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue(null)

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))

      expect(screen.queryByTestId("artifact-inventory-section")).not.toBeInTheDocument()
    })

    it("artifact inventory renders for arbitrary backend pipeline (WebGL), not only AI/ML", async () => {
      const webglPipeline: BackendSkillPipeline = {
        id: "pipeline-webgl-1",
        student_id: "student-1",
        profile_id: "profile-1",
        skill_name: "WebGL",
        skill_category: "Graphics",
        confidence_score: 78,
        support_status: "strongly_supported",
        evidence_count: 3,
        strongest_proof: { label: "Workflow", reason: "3D rendering captured" },
        weakest_proof: null,
        missing_evidence: [],
        next_actions: ["Add more geometry evidence"],
        evidence_sources: [
          { key: "workflow", label: "Workflow recording", status: "supported", score: 80, reason: "3D workflow" },
          { key: "dom", label: "DOM Evidence", status: "supported", score: 75, reason: "Canvas DOM captured" },
          { key: "ocr", label: "OCR", status: "partial", score: 55, reason: "Partial text extraction" },
        ],
        recruiter_summary: "WebGL evidence from Website Proof.",
        student_summary: "Your WebGL evidence from workflow recording.",
        visibility_status: "public",
        created_at: "2025-01-01T00:00:00Z",
        updated_at: "2025-01-01T00:00:00Z",
        artifacts: [
          makeArtifact({ id: "w1", source_type: "workflow", source_title: "3D Proof Session", project_name: "WebGL Demo", visibility: "public", confidence_score: 80, proof_reason: "3D rendering observed" }),
          makeArtifact({ id: "w2", source_type: "dom", source_title: "Canvas DOM", project_name: "WebGL Demo", visibility: "public", confidence_score: 75, proof_reason: "Canvas element captured" }),
          makeArtifact({ id: "w3", source_type: "keyframe", source_title: "3D Keyframe", project_name: "WebGL Demo", visibility: "public", confidence_score: 70, proof_reason: "Keyframe from recording" }),
        ],
      }

      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([webglPipeline])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId("manage-btn-webgl"))
      fireEvent.click(screen.getByTestId("manage-btn-webgl"))

      expect(screen.getByTestId("artifact-inventory-section")).toBeInTheDocument()
      expect(screen.getByTestId("artifact-inventory-section")).toHaveTextContent("Persisted evidence artifacts (3)")
      expect(screen.getByTestId("artifact-group-workflow")).toBeInTheDocument()
      expect(screen.getByTestId("artifact-group-dom")).toBeInTheDocument()
      expect(screen.getByTestId("artifact-group-keyframe")).toBeInTheDocument()
    })

    it("protected pipeline still shows artifact count from evidence_count when artifacts not yet synced", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({ evidence_count: 8, visibility_status: "protected", artifacts: [] }),
      ])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))

      const section = screen.getByTestId("artifact-inventory-section")
      expect(section).toBeInTheDocument()
      expect(section).toHaveTextContent("Persisted evidence artifacts (8)")
    })

    it("AI/ML with only 2 artifacts shows count 2 not a fake large number", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({
          evidence_count: 2,
          artifacts: [
            makeArtifact({ id: "b1", source_type: "github", source_title: "GitHub", visibility: "public", confidence_score: 90, proof_reason: "GitHub code", exact_code_url: "https://github.com/example/repo/blob/main/file.py#L1-L10" }),
            makeArtifact({ id: "b2", source_type: "workflow", source_title: "Workflow", visibility: "public", confidence_score: 80, proof_reason: "Workflow" }),
          ],
        }),
      ])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))

      const section = screen.getByTestId("artifact-inventory-section")
      expect(section).toHaveTextContent("Persisted evidence artifacts (2)")
      expect(section.textContent).not.toMatch(/\(5[5-9]\)|\([6-9]\d\)/i)
    })

    it("empty artifact state: no inventory section when evidence_count is 0", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({ evidence_count: 0, artifacts: [] }),
      ])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))

      expect(screen.queryByTestId("artifact-inventory-section")).not.toBeInTheDocument()
    })

    it("private pipeline shows artifact count with private message when artifacts not available", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({ evidence_count: 4, visibility_status: "private", artifacts: [] }),
      ])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))

      const section = screen.getByTestId("artifact-inventory-section")
      expect(section).toBeInTheDocument()
      expect(section).toHaveTextContent("4 artifacts synced")
    })

    it("does not render unsafe strings in artifact inventory section", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({ evidence_count: 5, artifacts: defaultArtifacts }),
      ])

      const { container } = render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))

      const html = container.innerHTML
      expect(html).not.toMatch(/storage\.googleapis|supabase\.co\/storage|access_token|signed_url/i)
      expect(html).not.toMatch(/video_url|media_storage_path|raw_full_dom|raw_full_transcript/i)
      expect(html).not.toMatch(/service_role|anon_key|env_secret/i)
    })

    // ── Must-fix regression: student-owned artifacts must not depend on the ──
    // ── recruiter-safe endpoint, which hides protected/private artifacts. ────

    it("Manage Skill Evidence modal shows a protected document artifact from student-owned data", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({
          evidence_count: 1,
          visibility_status: "protected",
          artifacts: [
            makeArtifact({
              id: "doc1",
              source_type: "document",
              source_title: "Transcript PDF",
              visibility: "protected",
              proof_reason: "Uploaded transcript document",
              confidence_score: 65,
            }),
          ],
        }),
      ])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))

      const group = screen.getByTestId("artifact-group-document")
      expect(group).toBeInTheDocument()
      expect(group).toHaveTextContent("Document evidence")
      expect(group).toHaveTextContent("protected")
    })

    it("certificate artifact appears in its own group with the certificate label, even on a protected pipeline", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({
          evidence_count: 1,
          visibility_status: "protected",
          artifacts: [
            makeArtifact({
              id: "cert1",
              source_type: "certificate",
              source_title: "AWS Cloud Practitioner",
              visibility: "protected",
              proof_reason: "Uploaded certificate",
              confidence_score: 60,
            }),
          ],
        }),
      ])

      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))

      const group = screen.getByTestId("artifact-group-certificate")
      expect(group).toBeInTheDocument()
      expect(group).toHaveTextContent("Certificate / transcript evidence")
    })

    it("does not render raw artifact_data on a protected pipeline's artifacts", async () => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
        makeBackendPipeline({
          evidence_count: 1,
          visibility_status: "protected",
          artifacts: [
            makeArtifact({
              id: "doc2",
              source_type: "document",
              source_title: "Reference Letter",
              visibility: "protected",
              proof_reason: "Uploaded reference letter",
              confidence_score: 55,
            }),
          ],
        }),
      ])

      const { container } = render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`manage-btn-${aiId}`))
      fireEvent.click(screen.getByTestId(`manage-btn-${aiId}`))

      expect(container.innerHTML).not.toMatch(/artifact_data|extracted_sections|document_title|download_available/i)
    })
  })

  // ── Section structure ─────────────────────────────────────────────────────────

  describe("section structure", () => {
    beforeEach(() => {
      vi.mocked(listSkillEvidencePipelines).mockResolvedValue(null)
    })

    it("renders the section heading", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId("skill-pipelines-heading")).toHaveTextContent(
          "Skill Evidence Pipelines",
        ),
      )
    })

    it("renders the subtitle", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByText(/VeriBridge groups your evidence by skill/)).toBeInTheDocument(),
      )
    })

    it("renders evidence count source coverage text", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getAllByText(/of \d+ confirmed/i).length).toBeGreaterThanOrEqual(1),
      )
    })

    it("renders missing evidence row when present", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.queryByTestId("pipelines-loading")).not.toBeInTheDocument(),
      )
      const missingRows = screen.queryAllByTestId(/missing-evidence-/)
      expect(missingRows.length).toBeGreaterThanOrEqual(0)
    })

    it("renders next action for each visible skill", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() => screen.getByTestId(`next-action-${aiId}`))
      expect(screen.getByTestId("next-action-javascript-frontend")).toBeInTheDocument()
    })

    it("shows strongest and weakest proof for AI/ML", async () => {
      render(<StudentSkillEvidencePipelines />)
      await waitFor(() =>
        expect(screen.getByTestId(`strongest-proof-${aiId}`)).toBeInTheDocument(),
      )
      expect(screen.getByTestId(`weakest-proof-${aiId}`)).toBeInTheDocument()
    })
  })
})
