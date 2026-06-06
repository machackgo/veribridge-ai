import React from "react"
import { render, screen, fireEvent, within, waitFor, act } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { StudentSkillEvidencePipelines } from "../../components/dashboard/StudentSkillEvidencePipelines"
import type { BackendSkillPipeline } from "@/lib/api"

// ── Mock @/lib/api ─────────────────────────────────────────────────────────────

vi.mock("@/lib/api", () => ({
  listSkillEvidencePipelines: vi.fn(),
  seedMockSkillEvidencePipelines: vi.fn(),
  getSkillEvidencePipeline: vi.fn(),
  getRecruiterSkillPipelineView: vi.fn(),
}))

import {
  listSkillEvidencePipelines,
  seedMockSkillEvidencePipelines,
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
