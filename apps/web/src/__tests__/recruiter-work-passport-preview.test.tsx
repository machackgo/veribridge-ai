import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import {
  RecruiterWorkPassportPreview,
  SkillEvidenceDetailModal,
} from "../../components/recruiter-passport/RecruiterWorkPassportPreview"
import { EvidenceAccessRequestModal } from "../../components/recruiter-passport/EvidenceAccessRequestModal"
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

// ── EvidenceAccessRequestModal tests ─────────────────────────────────────────

describe("EvidenceAccessRequestModal", () => {
  it("renders modal with title", () => {
    render(<EvidenceAccessRequestModal onClose={vi.fn()} />)
    expect(screen.getByTestId("access-request-modal")).toBeInTheDocument()
    expect(screen.getByText(/Request access to protected evidence/i)).toBeInTheDocument()
  })

  it("renders privacy and consent copy", () => {
    render(<EvidenceAccessRequestModal onClose={vi.fn()} />)
    const copy = screen.getByTestId("privacy-consent-copy")
    expect(copy).toBeInTheDocument()
    expect(copy.textContent).toMatch(/Students stay in control/i)
    expect(copy.textContent).toMatch(/VeriBridge will notify the student/i)
    expect(copy.textContent).toMatch(/Public skill summaries remain visible/i)
  })

  it("renders required name and email fields", () => {
    render(<EvidenceAccessRequestModal onClose={vi.fn()} />)
    expect(screen.getByPlaceholderText("Jane Smith")).toBeInTheDocument()
    expect(screen.getByPlaceholderText("jane@company.com")).toBeInTheDocument()
  })

  it("renders evidence section checkboxes", () => {
    render(<EvidenceAccessRequestModal onClose={vi.fn()} />)
    const checkboxGroup = screen.getByTestId("evidence-checkboxes")
    expect(checkboxGroup).toBeInTheDocument()
    expect(checkboxGroup.textContent).toMatch(/Workflow recordings/i)
    expect(checkboxGroup.textContent).toMatch(/Project defense/i)
    expect(checkboxGroup.textContent).toMatch(/Uploaded documents/i)
    expect(checkboxGroup.textContent).toMatch(/Detailed skill evidence/i)
  })

  it("submit button is disabled until name and email are filled", () => {
    render(<EvidenceAccessRequestModal onClose={vi.fn()} />)
    const submitBtn = screen.getByText("Submit request")
    expect(submitBtn).toBeDisabled()
  })

  it("submit button enables when name and email are provided", () => {
    render(<EvidenceAccessRequestModal onClose={vi.fn()} />)
    fireEvent.change(screen.getByPlaceholderText("Jane Smith"), { target: { value: "Jane" } })
    fireEvent.change(screen.getByPlaceholderText("jane@company.com"), { target: { value: "jane@co.com" } })
    expect(screen.getByText("Submit request")).not.toBeDisabled()
  })

  it("shows success/pending state after mock submission", async () => {
    render(
      <EvidenceAccessRequestModal onClose={vi.fn()} />,
    )
    fireEvent.change(screen.getByPlaceholderText("Jane Smith"), { target: { value: "Jane" } })
    fireEvent.change(screen.getByPlaceholderText("jane@company.com"), { target: { value: "jane@co.com" } })
    fireEvent.click(screen.getByText("Submit request"))
    await waitFor(() =>
      expect(screen.getByTestId("access-request-success")).toBeInTheDocument(),
      { timeout: 2000 },
    )
    expect(screen.getByText(/Access request submitted for demo review/i)).toBeInTheDocument()
    expect(screen.getByText(/Pending student approval/i)).toBeInTheDocument()
  })

  it("pre-fills fields from defaultRequester prop", () => {
    render(
      <EvidenceAccessRequestModal
        onClose={vi.fn()}
        defaultRequester={{
          requester_name: "Stripe Early Talent",
          requester_email: "recruiter@stripe.com",
          company: "Stripe",
          role: "Early Talent / AI Intern Hiring",
        }}
      />,
    )
    expect(screen.getByDisplayValue("Stripe Early Talent")).toBeInTheDocument()
    expect(screen.getByDisplayValue("recruiter@stripe.com")).toBeInTheDocument()
  })

  it("shows candidate name in subtitle", () => {
    render(<EvidenceAccessRequestModal onClose={vi.fn()} candidateName="Maya Reyes" />)
    expect(screen.getByText(/Maya Reyes/i)).toBeInTheDocument()
  })

  it("cancel button calls onClose", () => {
    const onClose = vi.fn()
    render(<EvidenceAccessRequestModal onClose={onClose} />)
    fireEvent.click(screen.getByText("Cancel"))
    expect(onClose).toHaveBeenCalled()
  })

  it("does not render private field names in UI", () => {
    const { container } = render(<EvidenceAccessRequestModal onClose={vi.fn()} />)
    const html = container.innerHTML
    expect(html).not.toContain("media_storage_path")
    expect(html).not.toContain("access_token")
    expect(html).not.toContain("transcript_text")
    expect(html).not.toContain("raw_risk")
    expect(html).not.toContain("debug_metadata")
    expect(html).not.toContain("admin_notes")
  })
})

// ── RecruiterWorkPassportPreview + modal integration ──────────────────────────

describe("RecruiterWorkPassportPreview — access request modal", () => {
  it("renders Request Evidence Access button when has_protected_evidence", () => {
    render(<RecruiterWorkPassportPreview view={makeView({ has_protected_evidence: true })} />)
    expect(screen.getByTestId("request-access-btn")).toBeInTheDocument()
    expect(screen.getByText(/Request Evidence Access/i)).toBeInTheDocument()
  })

  it("opens modal when button is clicked", () => {
    render(<RecruiterWorkPassportPreview view={makeView({ has_protected_evidence: true })} />)
    fireEvent.click(screen.getByTestId("request-access-btn"))
    expect(screen.getByTestId("access-request-modal")).toBeInTheDocument()
  })

  it("shows pending status card after mock submission", async () => {
    render(<RecruiterWorkPassportPreview view={makeView({ has_protected_evidence: true })} />)
    fireEvent.click(screen.getByTestId("request-access-btn"))
    fireEvent.change(screen.getByPlaceholderText("Jane Smith"), { target: { value: "Jane" } })
    fireEvent.change(screen.getByPlaceholderText("jane@company.com"), { target: { value: "jane@co.com" } })
    fireEvent.click(screen.getByText("Submit request"))
    await waitFor(() =>
      expect(screen.getByTestId("access-request-success")).toBeInTheDocument(),
      { timeout: 2000 },
    )
    // Close modal
    fireEvent.click(screen.getByText("Close"))
    // Parent should show pending card
    await waitFor(() =>
      expect(screen.getByTestId("access-pending-card")).toBeInTheDocument(),
    )
    expect(screen.getByText(/Request pending/i)).toBeInTheDocument()
    expect(screen.getByText(/Student approval required/i)).toBeInTheDocument()
  })
})

// ── Skill-first evidence: SkillGroupCard "View skill evidence" button ─────────

describe("RecruiterWorkPassportPreview — skill-first evidence", () => {
  function makeGroupedView(overrides: Partial<RecruiterPassportViewResponse> = {}): RecruiterPassportViewResponse {
    return makeView({
      skill_groups: [
        {
          group_name: "AI / Machine Learning",
          category: "AI/ML",
          confidence: "high",
          evidence_count: 4,
          source_labels: ["GitHub", "Website Workflow", "Documents"],
          skills: [
            { skill: "Machine Learning", confidence: "high", status_label: "strongly supported", source_labels: ["GitHub"] },
            { skill: "TensorFlow.js",    confidence: "high", status_label: "strongly supported", source_labels: ["GitHub", "Website Workflow"] },
          ],
        },
        {
          group_name: "JavaScript / Frontend",
          category: "Frontend",
          confidence: "high",
          evidence_count: 3,
          source_labels: ["GitHub", "Website Workflow"],
          skills: [
            { skill: "React", confidence: "high", status_label: "strongly supported", source_labels: ["GitHub"] },
          ],
        },
        {
          group_name: "DevOps / Deployment",
          category: "DevOps",
          confidence: "low",
          evidence_count: 1,
          source_labels: ["Documents"],
          skills: [
            { skill: "CI/CD", confidence: "low", status_label: "needs review", source_labels: ["Documents"] },
          ],
        },
      ],
      verified_skills: [],
      partially_verified_skills: [],
      skills_needing_review: [],
      ...overrides,
    })
  }

  it("evidence-backed skill card has View skill evidence action", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    const btns = screen.getAllByTestId("view-skill-evidence-btn")
    expect(btns.length).toBeGreaterThan(0)
    expect(btns[0]).toHaveTextContent("View skill evidence")
  })

  it("clicking AI / Machine Learning opens skill evidence detail modal", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    const btns = screen.getAllByTestId("view-skill-evidence-btn")
    fireEvent.click(btns[0])
    expect(screen.getByTestId("skill-evidence-detail-modal")).toBeInTheDocument()
    expect(screen.getAllByText(/AI \/ Machine Learning/i).length).toBeGreaterThan(0)
  })

  it("skill modal shows source coverage summary", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    fireEvent.click(screen.getAllByTestId("view-skill-evidence-btn")[0])
    expect(screen.getByTestId("skill-evidence-source-coverage")).toBeInTheDocument()
  })

  it("skill modal aggregates workflow, visual, GitHub, transcript, and document proof sections", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    fireEvent.click(screen.getAllByTestId("view-skill-evidence-btn")[0])
    expect(screen.getByTestId("skill-evidence-visual-proof")).toBeInTheDocument()
    expect(screen.getByTestId("skill-evidence-github")).toBeInTheDocument()
    expect(screen.getByTestId("skill-evidence-transcript")).toBeInTheDocument()
    expect(screen.getByTestId("skill-evidence-interview-questions")).toBeInTheDocument()
  })

  it("GitHub code evidence shows safe file paths and reasons", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    fireEvent.click(screen.getAllByTestId("view-skill-evidence-btn")[0])
    const github = screen.getByTestId("skill-evidence-github")
    expect(github.textContent).toMatch(/final_evidence_evaluator_service\.py/i)
    expect(github.textContent).toMatch(/combines workflow.*GitHub.*signals/i)
  })

  it("visual evidence cards are skill-specific not generic for AI/ML", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    fireEvent.click(screen.getAllByTestId("view-skill-evidence-btn")[0])
    const visual = screen.getByTestId("skill-evidence-visual-proof")
    expect(visual.textContent).toMatch(/Model inference UI visible/i)
  })

  it("without approval, protected frames in AI/ML show locked request-access state", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView({ has_protected_evidence: true })} />)
    fireEvent.click(screen.getAllByTestId("view-skill-evidence-btn")[0])
    const locks = screen.getAllByTestId("skill-evidence-protected-lock")
    expect(locks.length).toBeGreaterThan(0)
    expect(locks[0].textContent).toMatch(/Protected evidence available/i)
  })

  it("public-safe proof visible without approval", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView({ has_protected_evidence: true })} />)
    fireEvent.click(screen.getAllByTestId("view-skill-evidence-btn")[0])
    const visual = screen.getByTestId("skill-evidence-visual-proof")
    expect(visual.textContent).toMatch(/Model inference UI visible/i)
  })

  it("interview questions render per skill", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    fireEvent.click(screen.getAllByTestId("view-skill-evidence-btn")[0])
    const questions = screen.getByTestId("skill-evidence-interview-questions")
    expect(questions.textContent).toMatch(/evidence scoring model/i)
  })

  it("JavaScript/Frontend skill opens different evidence than AI/ML", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    const btns = screen.getAllByTestId("view-skill-evidence-btn")
    fireEvent.click(btns[1])
    expect(screen.getByTestId("skill-evidence-detail-modal")).toBeInTheDocument()
    const visual = screen.getByTestId("skill-evidence-visual-proof")
    expect(visual.textContent).toMatch(/React UI interaction/i)
    expect(visual.textContent).not.toMatch(/Model inference UI visible/i)
  })

  it("DevOps/Deployment shows needs-review state with document-only coverage", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    const btns = screen.getAllByTestId("view-skill-evidence-btn")
    fireEvent.click(btns[2])
    expect(screen.getByTestId("skill-evidence-detail-modal")).toBeInTheDocument()
    expect(screen.getAllByText(/needs review/i).length).toBeGreaterThan(0)
    const visual = screen.getByTestId("skill-evidence-visual-proof")
    expect(visual.textContent).toMatch(/No visual\/keyframe evidence/i)
    const github = screen.getByTestId("skill-evidence-github")
    expect(github.textContent).toMatch(/No GitHub code evidence/i)
  })
})

// ── SkillEvidenceDetailModal direct tests ─────────────────────────────────────

describe("SkillEvidenceDetailModal", () => {
  it("renders skill name, confidence badge, and support status in header", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="AI / Machine Learning"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getByTestId("skill-evidence-detail-modal")).toBeInTheDocument()
    expect(screen.getByText("AI / Machine Learning")).toBeInTheDocument()
    expect(screen.getByText(/strongly supported/i)).toBeInTheDocument()
    expect(screen.getAllByText(/high confidence/i).length).toBeGreaterThan(0)
  })

  it("shows source coverage with all 6 sources for AI/ML", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="AI / Machine Learning"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    const coverage = screen.getByTestId("skill-evidence-source-coverage")
    expect(coverage.textContent).toMatch(/Workflow recording/i)
    expect(coverage.textContent).toMatch(/GitHub code/i)
    expect(coverage.textContent).toMatch(/Documents/i)
    expect(coverage.textContent).toMatch(/Project defense/i)
  })

  it("shows skill-specific visual evidence label for AI/ML without approval", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="AI / Machine Learning"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    const visual = screen.getByTestId("skill-evidence-visual-proof")
    expect(visual.textContent).toMatch(/Model inference UI visible/i)
  })

  it("shows protected locks for AI/ML protected frames when not approved", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="AI / Machine Learning"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    const locks = screen.getAllByTestId("skill-evidence-protected-lock")
    expect(locks.length).toBeGreaterThan(0)
    expect(locks[0].textContent).toMatch(/Protected evidence available/i)
  })

  it("shows all protected visual frames when access is approved", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="AI / Machine Learning"
        accessApproved={true}
        onClose={vi.fn()}
      />,
    )
    const visual = screen.getByTestId("skill-evidence-visual-proof")
    expect(visual.textContent).toMatch(/Prediction\/demo workflow observed/i)
    expect(visual.textContent).toMatch(/AI proof builder/i)
  })

  it("transcript is locked when not approved", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="AI / Machine Learning"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    const transcript = screen.getByTestId("skill-evidence-transcript")
    const lock = transcript.querySelector('[data-testid="skill-evidence-protected-lock"]')
    expect(lock).not.toBeNull()
  })

  it("transcript excerpt visible when approved", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="AI / Machine Learning"
        accessApproved={true}
        onClose={vi.fn()}
      />,
    )
    const transcript = screen.getByTestId("skill-evidence-transcript")
    expect(transcript.textContent).toMatch(/TensorFlow\.js/i)
    expect(transcript.textContent).toMatch(/inference/i)
  })

  it("GitHub code evidence shows safe file paths and reasons", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="AI / Machine Learning"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    const github = screen.getByTestId("skill-evidence-github")
    expect(github.textContent).toMatch(/final_evidence_evaluator_service\.py/i)
    expect(github.textContent).toMatch(/extension_proof_workflow_analysis_service\.py/i)
  })

  it("interview questions render for AI/ML", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="AI / Machine Learning"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    const qs = screen.getByTestId("skill-evidence-interview-questions")
    expect(qs.textContent).toMatch(/evidence scoring model/i)
    expect(qs.textContent).toMatch(/rule-based versus model-based/i)
  })

  it("JavaScript/Frontend shows different visual evidence than AI/ML", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="JavaScript / Frontend"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    const visual = screen.getByTestId("skill-evidence-visual-proof")
    expect(visual.textContent).toMatch(/React UI interaction/i)
    expect(visual.textContent).not.toMatch(/Model inference UI visible/i)
  })

  it("JavaScript/Frontend GitHub files differ from AI/ML", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="JavaScript / Frontend"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    const github = screen.getByTestId("skill-evidence-github")
    expect(github.textContent).toMatch(/RecruiterWorkPassportPreview\.tsx/i)
    expect(github.textContent).not.toMatch(/final_evidence_evaluator_service\.py/i)
  })

  it("DevOps/Deployment shows needs-review with no visual or GitHub evidence", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="DevOps / Deployment"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getAllByText(/needs review/i).length).toBeGreaterThan(0)
    const visual = screen.getByTestId("skill-evidence-visual-proof")
    expect(visual.textContent).toMatch(/No visual\/keyframe evidence/i)
    const github = screen.getByTestId("skill-evidence-github")
    expect(github.textContent).toMatch(/No GitHub code evidence/i)
  })

  it("DevOps/Deployment document-only evidence visible without approval", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="DevOps / Deployment"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    const transcript = screen.getByTestId("skill-evidence-transcript")
    expect(transcript.textContent).toMatch(/containerizing/i)
  })

  it("skill evidence modal does not render unsafe strings", () => {
    const { container } = render(
      <SkillEvidenceDetailModal
        skillName="AI / Machine Learning"
        accessApproved={true}
        onClose={vi.fn()}
      />,
    )
    const html = container.innerHTML
    expect(html).not.toContain("localhost")
    expect(html).not.toContain("127.0.0.1")
    expect(html).not.toContain("access_token")
    expect(html).not.toContain("session_id")
    expect(html).not.toContain("storage_path")
    expect(html).not.toContain("raw_url")
    expect(html).not.toContain("supabase")
  })

  it("close button calls onClose", () => {
    const onClose = vi.fn()
    render(
      <SkillEvidenceDetailModal
        skillName="AI / Machine Learning"
        accessApproved={false}
        onClose={onClose}
      />,
    )
    fireEvent.click(screen.getByTestId("close-skill-evidence-modal-btn"))
    expect(onClose).toHaveBeenCalled()
  })
})

describe("Recruiter shortlist page — demo preview card", () => {
  const src = readFileSync(
    join(process.cwd(), "src/app/recruiter/passport/page.tsx"),
    "utf8",
  )

  it("renders a link to /dev/recruiter-passport-preview", () => {
    expect(src).toContain("/dev/recruiter-passport-preview")
  })

  it("renders the 'Preview sample Work Passport' card title", () => {
    expect(src).toContain("Preview sample Work Passport")
  })

  it("renders the 'Open preview' button label", () => {
    expect(src).toContain("Open preview")
  })

  it("communicates demo/mock status", () => {
    expect(src).toContain("Demo preview")
    expect(src).toContain("mock recruiter-safe data")
  })

  it("does not remove existing tab functionality", () => {
    expect(src).toContain("Saved Candidates")
    expect(src).toContain("Compare Candidates")
    expect(src).toContain("RecruiterSavedCandidatesPanel")
    expect(src).toContain("CandidateComparisonPanel")
  })
})

// ── Inline skill evidence cards ───────────────────────────────────────────────

describe("RecruiterWorkPassportPreview — inline skill evidence cards", () => {
  function makeGroupedView(overrides: Partial<RecruiterPassportViewResponse> = {}): RecruiterPassportViewResponse {
    return makeView({
      skill_groups: [
        {
          group_name: "AI / Machine Learning",
          category: "AI/ML",
          confidence: "high",
          evidence_count: 4,
          source_labels: ["GitHub", "Website Workflow", "Documents"],
          skills: [
            { skill: "Machine Learning", confidence: "high", status_label: "strongly supported", source_labels: ["GitHub"] },
            { skill: "TensorFlow.js",    confidence: "high", status_label: "strongly supported", source_labels: ["GitHub", "Website Workflow"] },
          ],
        },
        {
          group_name: "JavaScript / Frontend",
          category: "Frontend",
          confidence: "high",
          evidence_count: 3,
          source_labels: ["GitHub", "Website Workflow"],
          skills: [
            { skill: "React", confidence: "high", status_label: "strongly supported", source_labels: ["GitHub"] },
          ],
        },
        {
          group_name: "DevOps / Deployment",
          category: "DevOps",
          confidence: "low",
          evidence_count: 1,
          source_labels: ["Documents"],
          skills: [
            { skill: "CI/CD", confidence: "low", status_label: "needs review", source_labels: ["Documents"] },
          ],
        },
      ],
      verified_skills: [],
      partially_verified_skills: [],
      skills_needing_review: [],
      ...overrides,
    })
  }

  it("Evidence-Backed Skills renders expanded inline evidence summaries without opening modal", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    expect(screen.getAllByTestId("skill-group-source-coverage").length).toBeGreaterThan(0)
    expect(screen.getAllByTestId("skill-group-inline-snippets").length).toBeGreaterThan(0)
  })

  it("AI/ML card shows source coverage inline: workflow, visual/OCR, GitHub, defense, documents", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    const coverage = screen.getAllByTestId("skill-group-source-coverage")[0]
    expect(coverage.textContent).toMatch(/Workflow recording/i)
    expect(coverage.textContent).toMatch(/GitHub code/i)
    expect(coverage.textContent).toMatch(/Documents/i)
    expect(coverage.textContent).toMatch(/Project defense/i)
    expect(coverage.textContent).toMatch(/OCR/i)
  })

  it("AI/ML card shows skill-specific inline snippets, not generic fallback text", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    const snippets = screen.getAllByTestId("skill-group-inline-snippets")[0]
    expect(snippets.textContent).toMatch(/Model inference UI visible/i)
    expect(snippets.textContent).not.toMatch(/Workflow evidence reviewed/i)
  })

  it("JavaScript/Frontend card shows different inline evidence than AI/ML", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    const allSnippets = screen.getAllByTestId("skill-group-inline-snippets")
    expect(allSnippets[0].textContent).toMatch(/Model inference UI visible/i)
    expect(allSnippets[1].textContent).toMatch(/React UI interaction/i)
    expect(allSnippets[1].textContent).not.toMatch(/Model inference UI visible/i)
  })

  it("DevOps/Deployment card shows needs-review explanation inline", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    expect(screen.getByText(/limited evidence of deployment skills/i)).toBeInTheDocument()
  })

  it("DevOps/Deployment source coverage shows Missing for workflow and GitHub sources", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    const coverage = screen.getAllByTestId("skill-group-source-coverage")[2]
    expect(coverage.textContent).toMatch(/Missing/i)
    expect(coverage.textContent).not.toMatch(/Supported/i)
  })

  it("public-safe evidence is visible on card before approval", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView({ has_protected_evidence: true })} />)
    const snippets = screen.getAllByTestId("skill-group-inline-snippets")[0]
    expect(snippets.textContent).toMatch(/Model inference UI visible/i)
  })

  it("protected evidence shows inline lock on card before approval", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView({ has_protected_evidence: true })} />)
    const locks = screen.getAllByTestId("skill-group-protected-lock")
    expect(locks.length).toBeGreaterThan(0)
    expect(locks[0].textContent).toMatch(/Protected evidence available/i)
  })

  it("View skill evidence button still opens the skill evidence detail modal", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    fireEvent.click(screen.getAllByTestId("view-skill-evidence-btn")[0])
    expect(screen.getByTestId("skill-evidence-detail-modal")).toBeInTheDocument()
  })

  it("each card shows support status (strongly supported / partially supported / needs review)", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    expect(screen.getAllByText(/strongly supported/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/needs review/i).length).toBeGreaterThan(0)
  })

  it("inline rendered html does not contain unsafe private strings", () => {
    const { container } = render(
      <RecruiterWorkPassportPreview view={makeGroupedView({ has_protected_evidence: true })} />,
    )
    const html = container.innerHTML
    expect(html).not.toContain("localhost")
    expect(html).not.toContain("127.0.0.1")
    expect(html).not.toContain("access_token")
    expect(html).not.toContain("session_id")
    expect(html).not.toContain("storage_path")
    expect(html).not.toContain("raw_url")
    expect(html).not.toContain("supabase")
    expect(html).not.toContain("token=")
  })
})

// ── SkillEvidenceDetailModal — direct proof links ─────────────────────────────

describe("SkillEvidenceDetailModal — direct proof links", () => {
  function renderModal(skillName: string, accessApproved: boolean) {
    render(
      <SkillEvidenceDetailModal
        skillName={skillName}
        accessApproved={accessApproved}
        onClose={() => {}}
      />,
    )
  }

  it("renders direct proof links section in the modal", () => {
    renderModal("AI / Machine Learning", false)
    expect(screen.getByTestId("skill-direct-proof-links")).toBeInTheDocument()
    expect(screen.getByText(/direct proof links/i)).toBeInTheDocument()
  })

  it("GitHub section renders locked state for private repos before approval", () => {
    renderModal("AI / Machine Learning", false)
    expect(screen.getByTestId("skill-direct-github")).toBeInTheDocument()
    // AI/ML github files are all private → locked banners not open-source-file links
    expect(screen.getByTestId("locked-github-file-0")).toBeInTheDocument()
    expect(screen.queryByTestId("open-source-file-0")).not.toBeInTheDocument()
  })

  it("GitHub section renders locked state for private repo files (all bundles use private repos)", () => {
    renderModal("JavaScript / Frontend", false)
    // All github evidence is private in mock data — all should show locked banners
    expect(screen.getByTestId("locked-github-file-0")).toBeInTheDocument()
    expect(screen.queryByTestId("open-source-file-0")).not.toBeInTheDocument()
  })

  it("keyframe section shows view-keyframe-btn for public frames and locked for protected frames", () => {
    renderModal("AI / Machine Learning", false)
    expect(screen.getByTestId("skill-direct-keyframes")).toBeInTheDocument()
    // Frame 0 is public → view-keyframe-btn visible
    expect(screen.getAllByTestId("view-keyframe-btn").length).toBeGreaterThan(0)
    // Frames 1 and 2 are protected and not approved → locked banners
    expect(screen.getAllByTestId("locked-keyframe-btn").length).toBeGreaterThan(0)
  })

  it("keyframe section shows all frames openable after approval", () => {
    renderModal("AI / Machine Learning", true)
    // All frames should have view-keyframe-btn (no locked banners)
    expect(screen.getAllByTestId("view-keyframe-btn").length).toBeGreaterThan(0)
    expect(screen.queryByTestId("locked-keyframe-btn")).not.toBeInTheDocument()
    // At least one frame has OCR → ocr details btn visible
    expect(screen.getAllByTestId("view-ocr-details-btn").length).toBeGreaterThan(0)
    // All frames approved → open-recording-segment-btn visible
    expect(screen.getAllByTestId("open-recording-segment-btn").length).toBeGreaterThan(0)
  })

  it("transcript section shows locked state before approval", () => {
    renderModal("AI / Machine Learning", false)
    expect(screen.getByTestId("skill-direct-transcript")).toBeInTheDocument()
    expect(screen.getByTestId("locked-transcript-btn")).toBeInTheDocument()
    expect(screen.queryByTestId("view-transcript-excerpt-btn")).not.toBeInTheDocument()
  })

  it("transcript section shows view + full transcript after approval", () => {
    renderModal("AI / Machine Learning", true)
    expect(screen.getByTestId("view-transcript-excerpt-btn")).toBeInTheDocument()
    expect(screen.getByTestId("view-full-transcript-btn")).toBeInTheDocument()
  })

  it("document section shows locked state before approval for protected docs", () => {
    renderModal("AI / Machine Learning", false)
    expect(screen.getByTestId("skill-direct-documents")).toBeInTheDocument()
    expect(screen.getByTestId("locked-document-btn")).toBeInTheDocument()
  })

  it("document section shows open-approved-document-btn after approval", () => {
    renderModal("AI / Machine Learning", true)
    expect(screen.getByTestId("view-document-summary-btn")).toBeInTheDocument()
    expect(screen.getByTestId("open-approved-document-btn")).toBeInTheDocument()
  })

  it("live app section shows open-live-app-btn for public app (JS/Frontend)", () => {
    renderModal("JavaScript / Frontend", false)
    expect(screen.getByTestId("skill-direct-live-app")).toBeInTheDocument()
    expect(screen.getByTestId("open-live-app-btn")).toBeInTheDocument()
    expect(screen.queryByTestId("local-private-app-notice")).not.toBeInTheDocument()
  })

  it("live app section shows local-private-app-notice for private/local apps", () => {
    renderModal("AI / Machine Learning", false)
    expect(screen.getByTestId("skill-direct-live-app")).toBeInTheDocument()
    expect(screen.getByTestId("local-private-app-notice")).toBeInTheDocument()
    expect(screen.queryByTestId("open-live-app-btn")).not.toBeInTheDocument()
  })

  it("keyframe expand/collapse panel works (frame 0 is public)", async () => {
    // Frame 0 is public — can expand without approval
    renderModal("AI / Machine Learning", false)
    const btns = screen.getAllByTestId("view-keyframe-btn")
    fireEvent.click(btns[0])
    await waitFor(() => expect(screen.getByTestId("keyframe-detail-panel-0")).toBeInTheDocument())
    fireEvent.click(screen.getAllByTestId("view-keyframe-btn")[0])
    await waitFor(() => expect(screen.queryByTestId("keyframe-detail-panel-0")).not.toBeInTheDocument())
  })

  it("transcript expand/collapse panel works after approval", async () => {
    renderModal("AI / Machine Learning", true)
    fireEvent.click(screen.getByTestId("view-transcript-excerpt-btn"))
    await waitFor(() => expect(screen.getByTestId("transcript-detail-panel-0")).toBeInTheDocument())
  })

  it("document expand/collapse panel works after approval", async () => {
    renderModal("AI / Machine Learning", true)
    fireEvent.click(screen.getByTestId("view-document-summary-btn"))
    await waitFor(() => expect(screen.getByTestId("document-detail-panel-0")).toBeInTheDocument())
  })

  it("direct proof links modal html contains no private unsafe strings", () => {
    const { container } = render(
      <SkillEvidenceDetailModal skillName="AI / Machine Learning" accessApproved={true} onClose={() => {}} />,
    )
    const html = container.innerHTML
    expect(html).not.toContain("localhost")
    expect(html).not.toContain("127.0.0.1")
    expect(html).not.toContain("access_token")
    expect(html).not.toContain("session_id")
    expect(html).not.toContain("storage_path")
    expect(html).not.toContain("raw_url")
    expect(html).not.toContain("supabase")
    expect(html).not.toContain("token=")
  })
})

// ── Skill card compact actions ────────────────────────────────────────────────

describe("RecruiterWorkPassportPreview — skill card compact actions", () => {
  function makeGroupedView(overrides: Partial<RecruiterPassportViewResponse> = {}): RecruiterPassportViewResponse {
    return makeView({
      skill_groups: [
        {
          group_name: "AI / Machine Learning",
          category: "AI/ML",
          confidence: "high",
          evidence_count: 4,
          source_labels: ["GitHub", "Website Workflow", "Documents"],
          skills: [
            { skill: "Machine Learning", confidence: "high", status_label: "Verified", source_labels: ["GitHub"] },
            { skill: "TensorFlow.js", confidence: "high", status_label: "Verified", source_labels: ["GitHub"] },
          ],
        },
        {
          group_name: "JavaScript / Frontend",
          category: "Frontend",
          confidence: "high",
          evidence_count: 3,
          source_labels: ["GitHub", "Website Workflow"],
          skills: [
            { skill: "React", confidence: "high", status_label: "Verified", source_labels: ["GitHub"] },
          ],
        },
      ],
      verified_skills: ["Machine Learning", "React"],
      partially_verified_skills: ["TensorFlow.js"],
      skills_needing_review: [],
      ...overrides,
    })
  }

  it("compact action row is rendered on each skill card", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    const rows = screen.getAllByTestId("skill-card-compact-actions")
    expect(rows.length).toBeGreaterThanOrEqual(2)
  })

  it("GitHub proof chip is rendered when bundle has github evidence", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    const chips = screen.getAllByTestId("skill-card-github-proof-action")
    expect(chips.length).toBeGreaterThan(0)
  })

  it("keyframe chip visible for skill with public keyframe", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    // AI/ML visual evidence frame 0 is public — keyframe chip should appear on that card
    expect(screen.getAllByTestId("skill-card-keyframe-action").length).toBeGreaterThan(0)
  })

  it("live app chip visible for JS/Frontend (public app)", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    expect(screen.getByTestId("skill-card-live-app-action")).toBeInTheDocument()
  })
})
