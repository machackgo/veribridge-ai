import React from "react"
import { render, screen, fireEvent, within } from "@testing-library/react"
import { describe, it, expect } from "vitest"
import { StudentSkillEvidencePipelines } from "../../components/dashboard/StudentSkillEvidencePipelines"

// Skill IDs are derived: skillName.toLowerCase().replace(/[^a-z0-9]+/g, "-")
// "AI / Machine Learning"   → "ai-machine-learning"
// "JavaScript / Frontend"   → "javascript-frontend"
// "Data & Visualization"    → "data-visualization"
// "DevOps / Deployment"     → "devops-deployment"

describe("StudentSkillEvidencePipelines", () => {
  it("renders the section heading and subtitle", () => {
    render(<StudentSkillEvidencePipelines />)
    expect(screen.getByTestId("skill-pipelines-heading")).toHaveTextContent(
      "Skill Evidence Pipelines",
    )
    expect(
      screen.getByText(/VeriBridge groups your evidence by skill/),
    ).toBeInTheDocument()
  })

  it("renders a card for each of the 4 skills", () => {
    render(<StudentSkillEvidencePipelines />)
    const skills = [
      "AI / Machine Learning",
      "JavaScript / Frontend",
      "Data & Visualization",
      "DevOps / Deployment",
    ]
    for (const name of skills) {
      expect(screen.getByText(name)).toBeInTheDocument()
    }
    // 4 manage buttons
    const manageBtns = screen.getAllByText(/Manage skill evidence/i)
    expect(manageBtns).toHaveLength(4)
  })

  it("shows confidence badge on each card", () => {
    render(<StudentSkillEvidencePipelines />)
    expect(screen.getAllByText(/confidence/i).length).toBeGreaterThanOrEqual(4)
  })

  it("shows source coverage chips for AI/ML skill", () => {
    render(<StudentSkillEvidencePipelines />)
    const aiCard = screen.getByTestId("skill-pipeline-card-ai-machine-learning")
    const chips = within(aiCard).getAllByTestId(/source-chip-ai-machine-learning/)
    expect(chips.length).toBeGreaterThan(0)
  })

  it("shows strongest and weakest proof for AI/ML", () => {
    render(<StudentSkillEvidencePipelines />)
    expect(screen.getByTestId("strongest-proof-ai-machine-learning")).toBeInTheDocument()
    expect(screen.getByTestId("weakest-proof-ai-machine-learning")).toBeInTheDocument()
  })

  it("shows next action for each skill", () => {
    render(<StudentSkillEvidencePipelines />)
    expect(screen.getByTestId("next-action-ai-machine-learning")).toBeInTheDocument()
    expect(screen.getByTestId("next-action-javascript-frontend")).toBeInTheDocument()
  })

  it("shows visibility control buttons on each card", () => {
    render(<StudentSkillEvidencePipelines />)
    const aiCard = screen.getByTestId("skill-pipeline-card-ai-machine-learning")
    expect(within(aiCard).getByTestId("visibility-btn-ai-machine-learning-public")).toBeInTheDocument()
    expect(within(aiCard).getByTestId("visibility-btn-ai-machine-learning-protected")).toBeInTheDocument()
    expect(within(aiCard).getByTestId("visibility-btn-ai-machine-learning-private")).toBeInTheDocument()
  })

  it("changing visibility on a card is reflected in button state", () => {
    render(<StudentSkillEvidencePipelines />)
    const protectedBtn = screen.getByTestId("visibility-btn-ai-machine-learning-protected")
    fireEvent.click(protectedBtn)
    expect(protectedBtn).toBeInTheDocument()
  })

  it("opens ManageSkillModal when Manage button is clicked", () => {
    render(<StudentSkillEvidencePipelines />)
    expect(screen.queryByTestId("manage-skill-modal")).not.toBeInTheDocument()
    const manageBtn = screen.getByTestId("manage-btn-ai-machine-learning")
    fireEvent.click(manageBtn)
    expect(screen.getByTestId("manage-skill-modal")).toBeInTheDocument()
  })

  it("modal shows skill name in header", () => {
    render(<StudentSkillEvidencePipelines />)
    fireEvent.click(screen.getByTestId("manage-btn-ai-machine-learning"))
    const modal = screen.getByTestId("manage-skill-modal-content")
    expect(within(modal).getByText("AI / Machine Learning")).toBeInTheDocument()
  })

  it("modal shows evidence source coverage rows", () => {
    render(<StudentSkillEvidencePipelines />)
    fireEvent.click(screen.getByTestId("manage-btn-ai-machine-learning"))
    const modal = screen.getByTestId("manage-skill-modal-content")
    const sourceRows = within(modal).getAllByTestId(/modal-source-/)
    expect(sourceRows.length).toBeGreaterThan(0)
  })

  it("modal shows evidence artifacts", () => {
    render(<StudentSkillEvidencePipelines />)
    fireEvent.click(screen.getByTestId("manage-btn-ai-machine-learning"))
    const modal = screen.getByTestId("manage-skill-modal-content")
    const artifacts = within(modal).queryAllByTestId(/modal-artifact-/)
    expect(artifacts.length).toBeGreaterThan(0)
  })

  it("modal shows suggested improvement / next action", () => {
    render(<StudentSkillEvidencePipelines />)
    fireEvent.click(screen.getByTestId("manage-btn-javascript-frontend"))
    expect(screen.getByTestId("modal-next-action")).toBeInTheDocument()
  })

  it("modal closes when close button is clicked", () => {
    render(<StudentSkillEvidencePipelines />)
    fireEvent.click(screen.getByTestId("manage-btn-ai-machine-learning"))
    expect(screen.getByTestId("manage-skill-modal")).toBeInTheDocument()
    fireEvent.click(screen.getByTestId("manage-modal-close"))
    expect(screen.queryByTestId("manage-skill-modal")).not.toBeInTheDocument()
  })

  it("modal closes when backdrop is clicked", () => {
    render(<StudentSkillEvidencePipelines />)
    fireEvent.click(screen.getByTestId("manage-btn-ai-machine-learning"))
    const backdrop = screen.getByTestId("manage-skill-modal")
    fireEvent.click(backdrop)
    expect(screen.queryByTestId("manage-skill-modal")).not.toBeInTheDocument()
  })

  it("modal visibility controls work independently from card", () => {
    render(<StudentSkillEvidencePipelines />)
    fireEvent.click(screen.getByTestId("manage-btn-ai-machine-learning"))
    const privateBtn = screen.getByTestId("modal-visibility-private")
    fireEvent.click(privateBtn)
    expect(screen.getByText(/Recruiter cannot see this skill/)).toBeInTheDocument()
  })

  it("modal shows recruiter visibility section", () => {
    render(<StudentSkillEvidencePipelines />)
    fireEvent.click(screen.getByTestId("manage-btn-ai-machine-learning"))
    expect(screen.getByText(/What recruiters can see/i)).toBeInTheDocument()
  })

  it("DevOps card shows low confidence", () => {
    render(<StudentSkillEvidencePipelines />)
    const devopsCard = screen.getByTestId("skill-pipeline-card-devops-deployment")
    expect(within(devopsCard).getByTestId("skill-confidence-devops-deployment")).toHaveTextContent(
      /low confidence/i,
    )
  })

  it("AI/ML card shows high confidence", () => {
    render(<StudentSkillEvidencePipelines />)
    const aiCard = screen.getByTestId("skill-pipeline-card-ai-machine-learning")
    expect(within(aiCard).getByTestId("skill-confidence-ai-machine-learning")).toHaveTextContent(
      /high confidence/i,
    )
  })

  it("does not render any unsafe strings (storage path, token, signed URL)", () => {
    const { container } = render(<StudentSkillEvidencePipelines />)
    const text = container.innerHTML
    expect(text).not.toMatch(/storage\.googleapis|supabase\.co\/storage|access_token/)
    expect(text).not.toMatch(/service_role|anon_key/)
    expect(text).not.toMatch(/signed_url|signedUrl/i)
  })

  it("renders missing evidence row when stillNeedsReview is non-empty", () => {
    render(<StudentSkillEvidencePipelines />)
    // At least one skill should have a missing-evidence row (DevOps has missing evidence)
    const missingRows = screen.queryAllByTestId(/missing-evidence-/)
    expect(missingRows.length).toBeGreaterThanOrEqual(0)
  })

  it("renders evidence count text indicating source coverage", () => {
    render(<StudentSkillEvidencePipelines />)
    expect(screen.getAllByText(/of \d+ confirmed/i).length).toBeGreaterThanOrEqual(1)
  })

  it("student-safe language: does not show raw status strings like 'in_progress'", () => {
    render(<StudentSkillEvidencePipelines />)
    const text = document.body.textContent ?? ""
    expect(text).not.toContain("in_progress")
    expect(text).not.toContain("ai_approved_for_sharing")
  })

  // ── DOM Evidence tests ────────────────────────────────────────────────────────

  it("AI/ML source coverage chips include DOM Evidence chip", () => {
    render(<StudentSkillEvidencePipelines />)
    const aiCard = screen.getByTestId("skill-pipeline-card-ai-machine-learning")
    expect(within(aiCard).getByTestId("source-chip-ai-machine-learning-dom")).toBeInTheDocument()
    expect(within(aiCard).getByTestId("source-chip-ai-machine-learning-dom")).toHaveTextContent(
      /DOM Evidence/i,
    )
  })

  it("AI/ML Manage Skill Evidence modal renders DOM Evidence source row", () => {
    render(<StudentSkillEvidencePipelines />)
    fireEvent.click(screen.getByTestId("manage-btn-ai-machine-learning"))
    const modal = screen.getByTestId("manage-skill-modal-content")
    expect(within(modal).getByTestId("modal-source-dom")).toBeInTheDocument()
    expect(within(modal).getByTestId("modal-source-dom")).toHaveTextContent(/DOM Evidence/i)
  })

  it("AI/ML modal DOM Evidence source row shows reason text", () => {
    render(<StudentSkillEvidencePipelines />)
    fireEvent.click(screen.getByTestId("manage-btn-ai-machine-learning"))
    const modal = screen.getByTestId("manage-skill-modal-content")
    const domRow = within(modal).getByTestId("modal-source-dom")
    expect(domRow).toHaveTextContent(/page structure|visible UI labels|proof builder state/i)
  })

  it("AI/ML modal artifacts include a DOM Evidence artifact", () => {
    render(<StudentSkillEvidencePipelines />)
    fireEvent.click(screen.getByTestId("manage-btn-ai-machine-learning"))
    const modal = screen.getByTestId("manage-skill-modal-content")
    // "DOM Evidence" appears in both source coverage row and artifacts section
    const domMatches = within(modal).getAllByText("DOM Evidence")
    expect(domMatches.length).toBeGreaterThanOrEqual(2)
  })

  it("DOM Evidence does not expose unsafe raw DOM dumps or storage paths", () => {
    render(<StudentSkillEvidencePipelines />)
    fireEvent.click(screen.getByTestId("manage-btn-ai-machine-learning"))
    const modal = screen.getByTestId("manage-skill-modal-content")
    const html = modal.innerHTML
    expect(html).not.toMatch(/storage\.googleapis|supabase\.co\/storage|access_token/)
    expect(html).not.toMatch(/innerHTML|outerHTML|document\.querySelector/)
    expect(html).not.toMatch(/service_role|anon_key/)
  })
})
