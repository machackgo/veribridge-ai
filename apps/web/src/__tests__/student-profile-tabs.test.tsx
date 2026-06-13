import React from "react"
import { render, screen, fireEvent } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { StudentProfileProof } from "../../components/dashboard/StudentViews"

// ── Mock child components that make API calls ──────────────────────────────────

vi.mock("../../components/dashboard/StudentSkillEvidencePipelines", () => ({
  StudentSkillEvidencePipelines: () => (
    <div data-testid="mock-skill-pipelines">Skill Evidence Pipelines</div>
  ),
}))

vi.mock("../../components/dashboard/EvidenceFlowVisual", () => ({
  EvidenceFlowVisual: () => (
    <div data-testid="evidence-flow-visual">Evidence Flow Visual</div>
  ),
}))

vi.mock("../../components/skill-proof/student-proof-submission-panel", () => ({
  StudentProofSubmissionPanel: () => (
    <div data-testid="mock-proof-panel">Proof Submission Panel</div>
  ),
}))

vi.mock("../../components/ui/DemoToast", () => ({
  DemoToast: () => null,
  useDemoToast: () => ({ show: vi.fn(), msg: "" }),
}))

vi.mock("@/lib/api", () => ({
  listSkillEvidencePipelines: vi.fn().mockResolvedValue(null),
}))

vi.mock("../../data/mock", () => ({
  student: { score: 82, verifiedSkills: 8, publicProof: 6 },
  skillGaps: [
    { skill: "Kubernetes", impact: 68, readiness: 32, plan: "Build minikube project" },
    { skill: "Terraform", impact: 45, readiness: 20, plan: "Write infra-as-code scripts" },
    { skill: "GraphQL", impact: 38, readiness: 55, plan: "Add GraphQL API layer" },
  ],
  applications: [],
  jobs: [],
  visaSignals: [],
}))

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("StudentProfileProof – tab accessibility", () => {

  beforeEach(() => {
    render(<StudentProfileProof />)
  })

  // ── Tablist / tab roles ────────────────────────────────────────────────────

  it("tablist role exists on the tab container", () => {
    expect(screen.getByRole("tablist")).toBeInTheDocument()
  })

  it("each tab has role=tab", () => {
    const tabs = screen.getAllByRole("tab")
    expect(tabs).toHaveLength(5)
  })

  it("tab labels are Overview, Proof Center, Skill Graph, Work Passport, Improvement Plan", () => {
    const tabs = screen.getAllByRole("tab")
    const labels = tabs.map(t => t.textContent)
    expect(labels).toEqual(["Overview", "Proof Center", "Skill Graph", "Work Passport", "Improvement Plan"])
  })

  // ── Initial aria-selected state ───────────────────────────────────────────

  it("Overview tab has aria-selected=true by default", () => {
    const overviewTab = screen.getByRole("tab", { name: "Overview" })
    expect(overviewTab).toHaveAttribute("aria-selected", "true")
  })

  it("inactive tabs have aria-selected=false by default", () => {
    const inactiveTabs = ["Proof Center", "Skill Graph", "Work Passport", "Improvement Plan"]
    for (const name of inactiveTabs) {
      expect(screen.getByRole("tab", { name })).toHaveAttribute("aria-selected", "false")
    }
  })

  // ── Tabpanel ──────────────────────────────────────────────────────────────

  it("active tabpanel exists with role=tabpanel", () => {
    expect(screen.getByRole("tabpanel")).toBeInTheDocument()
  })

  it("active tabpanel is labelled by the Overview tab", () => {
    const panel = screen.getByRole("tabpanel")
    expect(panel).toHaveAttribute("aria-labelledby", "tab-overview")
  })

  it("Overview tab has aria-controls pointing to its panel", () => {
    const overviewTab = screen.getByRole("tab", { name: "Overview" })
    expect(overviewTab).toHaveAttribute("aria-controls", "panel-overview")
  })

  // ── Clicking tabs updates aria-selected ───────────────────────────────────

  it("clicking Skill Graph tab sets aria-selected=true on Skill Graph and false on others", () => {
    fireEvent.click(screen.getByRole("tab", { name: "Skill Graph" }))
    expect(screen.getByRole("tab", { name: "Skill Graph" })).toHaveAttribute("aria-selected", "true")
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "false")
    expect(screen.getByRole("tab", { name: "Proof Center" })).toHaveAttribute("aria-selected", "false")
    expect(screen.getByRole("tab", { name: "Work Passport" })).toHaveAttribute("aria-selected", "false")
    expect(screen.getByRole("tab", { name: "Improvement Plan" })).toHaveAttribute("aria-selected", "false")
  })

  it("clicking Proof Center tab sets aria-selected=true on Proof Center and false on others", () => {
    fireEvent.click(screen.getByRole("tab", { name: "Proof Center" }))
    expect(screen.getByRole("tab", { name: "Proof Center" })).toHaveAttribute("aria-selected", "true")
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "false")
    expect(screen.getByRole("tab", { name: "Skill Graph" })).toHaveAttribute("aria-selected", "false")
    expect(screen.getByRole("tab", { name: "Work Passport" })).toHaveAttribute("aria-selected", "false")
    expect(screen.getByRole("tab", { name: "Improvement Plan" })).toHaveAttribute("aria-selected", "false")
  })

  it("clicking Work Passport tab sets aria-selected=true on Work Passport", () => {
    fireEvent.click(screen.getByRole("tab", { name: "Work Passport" }))
    expect(screen.getByRole("tab", { name: "Work Passport" })).toHaveAttribute("aria-selected", "true")
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "false")
    expect(screen.getByRole("tab", { name: "Proof Center" })).toHaveAttribute("aria-selected", "false")
    expect(screen.getByRole("tab", { name: "Skill Graph" })).toHaveAttribute("aria-selected", "false")
    expect(screen.getByRole("tab", { name: "Improvement Plan" })).toHaveAttribute("aria-selected", "false")
  })

  it("clicking Improvement Plan tab sets aria-selected=true on Improvement Plan", () => {
    fireEvent.click(screen.getByRole("tab", { name: "Improvement Plan" }))
    expect(screen.getByRole("tab", { name: "Improvement Plan" })).toHaveAttribute("aria-selected", "true")
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "false")
    expect(screen.getByRole("tab", { name: "Proof Center" })).toHaveAttribute("aria-selected", "false")
    expect(screen.getByRole("tab", { name: "Skill Graph" })).toHaveAttribute("aria-selected", "false")
    expect(screen.getByRole("tab", { name: "Work Passport" })).toHaveAttribute("aria-selected", "false")
  })

  // ── Panel aria-controls / aria-labelledby wiring ──────────────────────────

  it("Skill Graph tabpanel is labelled by tab-skill-graph after clicking Skill Graph", () => {
    fireEvent.click(screen.getByRole("tab", { name: "Skill Graph" }))
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "tab-skill-graph")
  })

  it("Proof Center tabpanel is labelled by tab-proof-center after clicking Proof Center", () => {
    fireEvent.click(screen.getByRole("tab", { name: "Proof Center" }))
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "tab-proof-center")
  })

  it("Work Passport tabpanel is labelled by tab-work-passport after clicking Work Passport", () => {
    fireEvent.click(screen.getByRole("tab", { name: "Work Passport" }))
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "tab-work-passport")
  })

  it("Improvement Plan tabpanel is labelled by tab-improvement after clicking", () => {
    fireEvent.click(screen.getByRole("tab", { name: "Improvement Plan" }))
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "tab-improvement")
  })

  // ── Panel content renders correctly ───────────────────────────────────────

  it("Skill Graph tab renders skill evidence pipelines content", () => {
    fireEvent.click(screen.getByRole("tab", { name: "Skill Graph" }))
    expect(screen.getByTestId("mock-skill-pipelines")).toBeInTheDocument()
  })

  it("Proof Center tab renders proof submission panel content", () => {
    fireEvent.click(screen.getByRole("tab", { name: "Proof Center" }))
    expect(screen.getByTestId("mock-proof-panel")).toBeInTheDocument()
  })

  // ── Keyboard navigation ───────────────────────────────────────────────────

  it("ArrowRight on Overview tab activates Proof Center tab", () => {
    const tablist = screen.getByRole("tablist")
    fireEvent.keyDown(tablist, { key: "ArrowRight" })
    expect(screen.getByRole("tab", { name: "Proof Center" })).toHaveAttribute("aria-selected", "true")
  })

  it("ArrowLeft on Overview tab wraps to Improvement Plan tab", () => {
    const tablist = screen.getByRole("tablist")
    fireEvent.keyDown(tablist, { key: "ArrowLeft" })
    expect(screen.getByRole("tab", { name: "Improvement Plan" })).toHaveAttribute("aria-selected", "true")
  })

  it("ArrowRight wraps from Improvement Plan to Overview", () => {
    fireEvent.click(screen.getByRole("tab", { name: "Improvement Plan" }))
    const tablist = screen.getByRole("tablist")
    fireEvent.keyDown(tablist, { key: "ArrowRight" })
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true")
  })

  // ── Copy / label assertions ───────────────────────────────────────────────

  it("Overview tab contains 'Preview as recruiter' button", () => {
    expect(screen.getByText("Preview as recruiter")).toBeInTheDocument()
  })

  it("Proof Center tab shows 'AI Session' card", () => {
    fireEvent.click(screen.getByRole("tab", { name: "Proof Center" }))
    expect(screen.getByText("AI Session")).toBeInTheDocument()
  })

  it("Proof Center tab shows 'Website Proof' card", () => {
    fireEvent.click(screen.getByRole("tab", { name: "Proof Center" }))
    expect(screen.getByText("Website Proof")).toBeInTheDocument()
  })

  it("Proof Center tab shows 'GitHub Proof' card", () => {
    fireEvent.click(screen.getByRole("tab", { name: "Proof Center" }))
    expect(screen.getByText("GitHub Proof")).toBeInTheDocument()
  })

  // ── Focus / tabIndex (roving tabindex) ────────────────────────────────────

  it("active tab has tabIndex=0", () => {
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("tabindex", "0")
  })

  it("inactive tabs have tabIndex=-1", () => {
    const inactiveTabs = ["Proof Center", "Skill Graph", "Work Passport", "Improvement Plan"]
    for (const name of inactiveTabs) {
      expect(screen.getByRole("tab", { name })).toHaveAttribute("tabindex", "-1")
    }
  })

  // ── Motion polish ─────────────────────────────────────────────────────────

  it("Overview panel has vb-tab-panel animation class", () => {
    expect(screen.getByRole("tabpanel")).toHaveClass("vb-tab-panel")
  })

  it("Overview tab renders the EvidenceFlowVisual component", () => {
    expect(screen.getByTestId("evidence-flow-visual")).toBeInTheDocument()
  })

  it("switching to Proof Center panel still has vb-tab-panel class", () => {
    fireEvent.click(screen.getByRole("tab", { name: "Proof Center" }))
    expect(screen.getByRole("tabpanel")).toHaveClass("vb-tab-panel")
  })

  it("switching to Work Passport panel still has vb-tab-panel class", () => {
    fireEvent.click(screen.getByRole("tab", { name: "Work Passport" }))
    expect(screen.getByRole("tabpanel")).toHaveClass("vb-tab-panel")
  })
})
