import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { RecruiterWorkPassportPreview } from "../../components/recruiter-passport/RecruiterWorkPassportPreview"
import type { RecruiterPassportViewResponse } from "../lib/passport-api"

// ── Fixture builder ───────────────────────────────────────────────────────────

function makeView(overrides: Partial<RecruiterPassportViewResponse> = {}): RecruiterPassportViewResponse {
  return {
    public_slug: "test-slug-abc",
    student_display_name: "Alex Candidate",
    field: "AI / Machine Learning",
    public_title: "AI Chatbot Developer",
    public_summary: "Full-stack engineer with NLP and chatbot experience.",
    overall_score: 65,
    evidence_confidence: "medium",
    verification_status: null,
    readiness_level: "Partially Ready",
    skill_groups: [],
    verified_skills: ["Chatbot UI", "React"],
    partially_verified_skills: ["Natural Language Processing"],
    skills_needing_review: ["Large Language Models"],
    proof_sources: [
      { key: "website_workflow", label: "Website Workflow", status: "partial", score: 60, is_run: true },
      { key: "github", label: "GitHub", status: "pass", score: 75, is_run: true },
      { key: "ocr", label: "OCR", status: "not_run", score: 0, is_run: false },
    ],
    why_credible: ["GitHub evidence confirms React and chatbot skills."],
    strongest_skills: ["Chatbot UI", "React"],
    areas_needing_review: ["Large Language Models"],
    suggested_interview_questions: [
      "Tell me about a challenge you faced with Natural Language Processing.",
      "Walk me through your chatbot architecture decisions.",
    ],
    public_project_links: [{ label: "GitHub Repo", url: "https://github.com/alex/chatbot" }],
    project_type: "AI / Data Visualization Engineer",
    access_request_available: true,
    has_protected_evidence: true,
    disclosure_note: "This is a safe summary. Protected evidence requires approval.",
    ...overrides,
  }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("RecruiterWorkPassportPreview", () => {
  it("renders candidate summary fields", () => {
    render(<RecruiterWorkPassportPreview view={makeView()} />)
    // Score rendered
    expect(screen.getByText("65")).toBeInTheDocument()
    // At least one confidence label element rendered (badge and section header both say "Partial evidence")
    expect(screen.getAllByText(/partial evidence/i).length).toBeGreaterThan(0)
    // Source count
    expect(screen.getByText(/2 of 3 evidence sources analyzed/i)).toBeInTheDocument()
  })

  it("renders proof sources with status", () => {
    render(<RecruiterWorkPassportPreview view={makeView()} />)
    expect(screen.getByText("Website Workflow")).toBeInTheDocument()
    expect(screen.getByText("GitHub")).toBeInTheDocument()
    expect(screen.getByText("OCR")).toBeInTheDocument()
    // Scores for run sources
    expect(screen.getByText("60/100")).toBeInTheDocument()
    expect(screen.getByText("75/100")).toBeInTheDocument()
    // Not-run label for OCR
    expect(screen.getByText("Not run")).toBeInTheDocument()
  })

  it("renders evidence-backed skills from flat lists when no groups", () => {
    render(<RecruiterWorkPassportPreview view={makeView()} />)
    expect(screen.getAllByText("Chatbot UI").length).toBeGreaterThan(0)
    expect(screen.getAllByText("React").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Natural Language Processing").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Large Language Models").length).toBeGreaterThan(0)
  })

  it("renders skill groups when provided", () => {
    const view = makeView({
      skill_groups: [{
        group_name: "AI / Machine Learning",
        category: "AI/ML",
        confidence: "high",
        evidence_count: 3,
        source_labels: ["GitHub", "Website Workflow"],
        skills: [{
          skill: "Chatbot UI",
          confidence: "high",
          status_label: "claimed — strongly supported",
          source_labels: ["GitHub"],
        }],
      }],
      verified_skills: [],
      partially_verified_skills: [],
      skills_needing_review: [],
    })
    render(<RecruiterWorkPassportPreview view={view} />)
    expect(screen.getByText("AI / Machine Learning")).toBeInTheDocument()
    expect(screen.getByText("Chatbot UI")).toBeInTheDocument()
    expect(screen.getAllByText(/GitHub/).length).toBeGreaterThan(0)
    expect(screen.getByText(/high confidence/i)).toBeInTheDocument()
  })

  it("renders why-credible section", () => {
    render(<RecruiterWorkPassportPreview view={makeView()} />)
    expect(screen.getByText(/Why this candidate is credible/i)).toBeInTheDocument()
    expect(screen.getByText(/GitHub evidence confirms React/i)).toBeInTheDocument()
  })

  it("renders suggested interview questions", () => {
    render(<RecruiterWorkPassportPreview view={makeView()} />)
    expect(screen.getByText(/Suggested interview questions/i)).toBeInTheDocument()
    // interview question text containing these phrases must exist (may be inside question element)
    expect(screen.getAllByText(/Natural Language Processing/).length).toBeGreaterThan(0)
    expect(screen.getByText(/chatbot architecture/i)).toBeInTheDocument()
  })

  it("renders request access CTA when has_protected_evidence", () => {
    const onRequestAccess = vi.fn()
    render(
      <RecruiterWorkPassportPreview
        view={makeView({ has_protected_evidence: true })}
        onRequestAccess={onRequestAccess}
      />,
    )
    expect(screen.getByText(/Protected Evidence Available/i)).toBeInTheDocument()
    expect(screen.getByText(/Request Evidence Access/i)).toBeInTheDocument()
  })

  it("omits request access CTA when has_protected_evidence is false", () => {
    render(
      <RecruiterWorkPassportPreview
        view={makeView({ has_protected_evidence: false })}
      />,
    )
    expect(screen.queryByText(/Protected Evidence Available/i)).not.toBeInTheDocument()
  })

  it("renders project link", () => {
    render(<RecruiterWorkPassportPreview view={makeView()} />)
    const link = screen.getByText("GitHub Repo")
    expect(link.tagName).toBe("SPAN")
    // Parent anchor
    expect(link.closest("a")).toHaveAttribute("href", "https://github.com/alex/chatbot")
  })

  it("renders disclosure note", () => {
    render(<RecruiterWorkPassportPreview view={makeView()} />)
    expect(screen.getByText(/Protected evidence requires approval/i)).toBeInTheDocument()
  })

  it("works with empty optional fields gracefully", () => {
    const view = makeView({
      why_credible: [],
      areas_needing_review: [],
      suggested_interview_questions: [],
      public_project_links: [],
      skill_groups: [],
      verified_skills: [],
      partially_verified_skills: [],
      skills_needing_review: [],
      proof_sources: [],
    })
    // Must not throw
    render(<RecruiterWorkPassportPreview view={view} />)
    // Score still renders
    expect(screen.getByText("65")).toBeInTheDocument()
  })

  it("does not use student-only labels", () => {
    render(<RecruiterWorkPassportPreview view={makeView()} />)
    expect(screen.queryByText(/Save selected skills/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Send Proof/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Start Recording/i)).not.toBeInTheDocument()
  })

  it("does not expose debug or private field labels in UI", () => {
    const { container } = render(<RecruiterWorkPassportPreview view={makeView()} />)
    const html = container.innerHTML
    expect(html).not.toContain("media_storage_path")
    expect(html).not.toContain("access_token")
    expect(html).not.toContain("proof_data")
    expect(html).not.toContain("transcript_text")
    expect(html).not.toContain("raw_risk")
  })
})
