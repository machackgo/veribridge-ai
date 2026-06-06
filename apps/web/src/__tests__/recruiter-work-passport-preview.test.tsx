import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import {
  RecruiterWorkPassportPreview,
  SkillEvidenceDetailModal,
  getSkillPipeline,
} from "../../components/recruiter-passport/RecruiterWorkPassportPreview"
import { EvidenceAccessRequestModal } from "../../components/recruiter-passport/EvidenceAccessRequestModal"
import type { RecruiterPassportViewResponse } from "../lib/passport-api"
import * as apiModule from "@/lib/api"
import type { BackendSkillPipeline } from "@/lib/api"

// Default: backend unavailable — safe fallback, existing tests unaffected.
vi.mock("@/lib/api", () => ({
  listRecruiterSkillEvidencePipelines: vi.fn().mockResolvedValue(null),
}))

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
    expect(screen.getByTestId("skill-artifact-workflow-recording")).toBeInTheDocument()
    expect(screen.getByTestId("skill-artifact-keyframes")).toBeInTheDocument()
    expect(screen.getByTestId("skill-artifact-github")).toBeInTheDocument()
    expect(screen.getByTestId("skill-artifact-transcript")).toBeInTheDocument()
    expect(screen.getByTestId("skill-artifact-documents")).toBeInTheDocument()
    expect(screen.getByTestId("skill-artifact-final-analysis")).toBeInTheDocument()
    expect(screen.getByTestId("skill-evidence-interview-questions")).toBeInTheDocument()
  })

  it("GitHub code evidence shows direct file links for public repo", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    fireEvent.click(screen.getAllByTestId("view-skill-evidence-btn")[0])
    const github = screen.getByTestId("skill-artifact-github")
    expect(github.textContent).toMatch(/final_evidence_evaluator_service\.py/i)
    expect(github.textContent).toMatch(/combines workflow.*GitHub.*signals/i)
    // Public repo — direct open file links should exist
    expect(screen.getByTestId("github-open-file-0")).toBeInTheDocument()
  })

  it("visual evidence cards are skill-specific not generic for AI/ML", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    fireEvent.click(screen.getAllByTestId("view-skill-evidence-btn")[0])
    const keyframes = screen.getByTestId("skill-artifact-keyframes")
    expect(keyframes.textContent).toMatch(/Model inference UI visible/i)
  })

  it("without approval, protected frames in AI/ML show locked message", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView({ has_protected_evidence: true })} />)
    fireEvent.click(screen.getAllByTestId("view-skill-evidence-btn")[0])
    const keyframes = screen.getByTestId("skill-artifact-keyframes")
    // Frames 1 and 2 are protected — should show locked state
    expect(keyframes.textContent).toMatch(/Protected keyframe/i)
  })

  it("public-safe proof visible without approval", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView({ has_protected_evidence: true })} />)
    fireEvent.click(screen.getAllByTestId("view-skill-evidence-btn")[0])
    const keyframes = screen.getByTestId("skill-artifact-keyframes")
    // Frame 0 is public — should be visible
    expect(keyframes.textContent).toMatch(/Model inference UI visible/i)
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
    const keyframes = screen.getByTestId("skill-artifact-keyframes")
    expect(keyframes.textContent).toMatch(/React UI interaction/i)
    expect(keyframes.textContent).not.toMatch(/Model inference UI visible/i)
  })

  it("DevOps/Deployment shows needs-review state with document-only coverage", () => {
    render(<RecruiterWorkPassportPreview view={makeGroupedView()} />)
    const btns = screen.getAllByTestId("view-skill-evidence-btn")
    fireEvent.click(btns[2])
    expect(screen.getByTestId("skill-evidence-detail-modal")).toBeInTheDocument()
    expect(screen.getAllByText(/needs review/i).length).toBeGreaterThan(0)
    // DevOps has no keyframes or github — both sections show empty state
    const keyframes = screen.getByTestId("skill-artifact-keyframes")
    expect(keyframes.textContent).toMatch(/No keyframe or visual artifacts/i)
    const github = screen.getByTestId("skill-artifact-github")
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
    expect(screen.getAllByText(/strongly supported/i).length).toBeGreaterThan(0)
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

  it("shows actual proof artifact sections for AI/ML", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="AI / Machine Learning"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getByTestId("skill-artifact-workflow-recording")).toBeInTheDocument()
    expect(screen.getByTestId("skill-artifact-keyframes")).toBeInTheDocument()
    expect(screen.getByTestId("skill-artifact-github")).toBeInTheDocument()
    expect(screen.getByTestId("skill-artifact-transcript")).toBeInTheDocument()
    expect(screen.getByTestId("skill-artifact-documents")).toBeInTheDocument()
    expect(screen.getByTestId("skill-artifact-final-analysis")).toBeInTheDocument()
  })

  it("shows skill-specific keyframe artifact for AI/ML — model inference label", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="AI / Machine Learning"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    const keyframes = screen.getByTestId("skill-artifact-keyframes")
    expect(keyframes.textContent).toMatch(/Model inference UI visible/i)
  })

  it("shows protected keyframe message for locked frames when not approved", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="AI / Machine Learning"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    // Frames 1 and 2 are protected — show locked message
    const keyframes = screen.getByTestId("skill-artifact-keyframes")
    expect(keyframes.textContent).toMatch(/Protected keyframe/i)
  })

  it("expands protected keyframe details when access is approved", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="AI / Machine Learning"
        accessApproved={true}
        onClose={vi.fn()}
      />,
    )
    const keyframes = screen.getByTestId("skill-artifact-keyframes")
    expect(keyframes.textContent).toMatch(/Prediction\/demo workflow observed/i)
    expect(keyframes.textContent).toMatch(/AI proof builder/i)
    // No locked message when approved
    expect(keyframes.textContent).not.toMatch(/Protected keyframe/i)
  })

  it("transcript shows locked message when not approved", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="AI / Machine Learning"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    const transcript = screen.getByTestId("skill-artifact-transcript")
    expect(transcript.textContent).toMatch(/Full transcript requires student approval/i)
  })

  it("transcript artifact shows excerpt and ownership signal when approved", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="AI / Machine Learning"
        accessApproved={true}
        onClose={vi.fn()}
      />,
    )
    const transcript = screen.getByTestId("skill-artifact-transcript")
    expect(transcript.textContent).toMatch(/TensorFlow\.js/i)
    expect(transcript.textContent).toMatch(/inference/i)
  })

  it("GitHub artifact shows direct open file link for public repo (AI/ML)", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="AI / Machine Learning"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    const github = screen.getByTestId("skill-artifact-github")
    expect(github.textContent).toMatch(/final_evidence_evaluator_service\.py/i)
    expect(github.textContent).toMatch(/extension_proof_workflow_analysis_service\.py/i)
    // Should have open file links (public repo)
    expect(screen.getByTestId("github-open-file-0")).toBeInTheDocument()
    expect(screen.getByTestId("github-open-repo-0")).toBeInTheDocument()
  })

  it("GitHub open file link points to /blob/main/ path", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="AI / Machine Learning"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    const link = screen.getByTestId("github-open-file-0") as HTMLAnchorElement
    expect(link.href).toMatch(/github\.com\/machackgo\/veribridge-ai\/blob\/main\//i)
    expect(link.href).toMatch(/final_evidence_evaluator_service\.py/i)
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

  it("JavaScript/Frontend keyframe artifact is different from AI/ML", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="JavaScript / Frontend"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    const keyframes = screen.getByTestId("skill-artifact-keyframes")
    expect(keyframes.textContent).toMatch(/React UI interaction/i)
    expect(keyframes.textContent).not.toMatch(/Model inference UI visible/i)
  })

  it("JavaScript/Frontend GitHub artifacts differ from AI/ML", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="JavaScript / Frontend"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    const github = screen.getByTestId("skill-artifact-github")
    expect(github.textContent).toMatch(/RecruiterWorkPassportPreview\.tsx/i)
    expect(github.textContent).not.toMatch(/final_evidence_evaluator_service\.py/i)
  })

  it("DevOps/Deployment shows needs-review with no keyframe or GitHub artifacts", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="DevOps / Deployment"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getAllByText(/needs review/i).length).toBeGreaterThan(0)
    const keyframes = screen.getByTestId("skill-artifact-keyframes")
    expect(keyframes.textContent).toMatch(/No keyframe or visual artifacts/i)
    const github = screen.getByTestId("skill-artifact-github")
    expect(github.textContent).toMatch(/No GitHub code evidence/i)
  })

  it("DevOps/Deployment document artifact visible without approval (not protected)", () => {
    render(
      <SkillEvidenceDetailModal
        skillName="DevOps / Deployment"
        accessApproved={false}
        onClose={vi.fn()}
      />,
    )
    const docs = screen.getByTestId("skill-artifact-documents")
    expect(docs.textContent).toMatch(/containerizing/i)
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

// ── SkillEvidenceDetailModal — artifact inspection ────────────────────────────

describe("SkillEvidenceDetailModal — artifact inspection", () => {
  function renderModal(skillName: string, accessApproved: boolean) {
    render(
      <SkillEvidenceDetailModal
        skillName={skillName}
        accessApproved={accessApproved}
        onClose={() => {}}
      />,
    )
  }

  it("artifact access summary is shown in the modal", () => {
    renderModal("AI / Machine Learning", false)
    expect(screen.getByTestId("skill-artifact-access-summary")).toBeInTheDocument()
  })

  it("workflow recording placeholder viewer is rendered", () => {
    renderModal("AI / Machine Learning", false)
    expect(screen.getByTestId("workflow-recording-viewer")).toBeInTheDocument()
  })

  it("workflow recording shows title, duration, and segments for AI/ML", () => {
    renderModal("AI / Machine Learning", false)
    const recording = screen.getByTestId("skill-artifact-workflow-recording")
    expect(recording.textContent).toMatch(/AI Proof Builder/i)
    expect(recording.textContent).toMatch(/4:12/i)
    expect(recording.textContent).toMatch(/Model inference UI opened/i)
  })

  it("workflow recording shows different skills for JS/Frontend", () => {
    renderModal("JavaScript / Frontend", false)
    const recording = screen.getByTestId("skill-artifact-workflow-recording")
    expect(recording.textContent).toMatch(/Recruiter Passport Dashboard/i)
    expect(recording.textContent).not.toMatch(/AI Proof Builder/i)
  })

  it("keyframe artifact shows per-frame card with public frame visible", () => {
    renderModal("AI / Machine Learning", false)
    expect(screen.getByTestId("keyframe-artifact-0")).toBeInTheDocument()
    expect(screen.getByTestId("keyframe-artifact-0").textContent).toMatch(/Model inference UI visible/i)
  })

  it("expanding public keyframe reveals OCR, DOM, and Qwen", async () => {
    renderModal("AI / Machine Learning", false)
    fireEvent.click(screen.getByTestId("expand-keyframe-0"))
    await waitFor(() => expect(screen.getByTestId("keyframe-detail-0")).toBeInTheDocument())
    expect(screen.getByTestId("keyframe-ocr-0")).toBeInTheDocument()
    expect(screen.getByTestId("keyframe-dom-0")).toBeInTheDocument()
    expect(screen.getByTestId("keyframe-qwen-0")).toBeInTheDocument()
  })

  it("OCR text is artifact-specific for AI/ML frame 0", async () => {
    renderModal("AI / Machine Learning", false)
    fireEvent.click(screen.getByTestId("expand-keyframe-0"))
    await waitFor(() => expect(screen.getByTestId("keyframe-ocr-0")).toBeInTheDocument())
    expect(screen.getByTestId("keyframe-ocr-0").textContent).toMatch(/Overall Score: 87/i)
  })

  it("DOM context is shown for AI/ML frame 0", async () => {
    renderModal("AI / Machine Learning", false)
    fireEvent.click(screen.getByTestId("expand-keyframe-0"))
    await waitFor(() => expect(screen.getByTestId("keyframe-dom-0")).toBeInTheDocument())
    expect(screen.getByTestId("keyframe-dom-0").textContent).toMatch(/Evidence-backed skills/i)
  })

  it("Qwen observation is shown for AI/ML frame 0", async () => {
    renderModal("AI / Machine Learning", false)
    fireEvent.click(screen.getByTestId("expand-keyframe-0"))
    await waitFor(() => expect(screen.getByTestId("keyframe-qwen-0")).toBeInTheDocument())
    // Qwen observation for frame 0 is about the proof builder dashboard
    expect(screen.getByTestId("keyframe-qwen-0").textContent).toMatch(/proof builder/i)
  })

  it("Qwen analysis summary section is shown for AI/ML", () => {
    renderModal("AI / Machine Learning", false)
    expect(screen.getByTestId("skill-artifact-qwen")).toBeInTheDocument()
    const qwen = screen.getByTestId("skill-artifact-qwen")
    expect(qwen.textContent).toMatch(/3 frames analyzed/i)
    expect(qwen.textContent).toMatch(/evidence confidence/i)
  })

  it("DOM evidence artifact is shown for AI/ML", () => {
    renderModal("AI / Machine Learning", false)
    expect(screen.getByTestId("skill-artifact-dom")).toBeInTheDocument()
    const dom = screen.getByTestId("skill-artifact-dom")
    expect(dom.textContent).toMatch(/AI Proof Builder/i)
    expect(dom.textContent).toMatch(/Evidence-backed skills/i)
  })

  it("DOM evidence says local/private URL hidden (not exposing raw URL)", () => {
    renderModal("AI / Machine Learning", false)
    const dom = screen.getByTestId("skill-artifact-dom")
    expect(dom.textContent).toMatch(/local\/private URL hidden/i)
  })

  it("GitHub artifact shows direct /blob/main/ links for public repo", () => {
    renderModal("AI / Machine Learning", false)
    const link = screen.getByTestId("github-open-file-0") as HTMLAnchorElement
    expect(link.href).toContain("github.com/machackgo/veribridge-ai/blob/main/")
    expect(link.href).toContain("final_evidence_evaluator_service.py")
  })

  it("GitHub artifact has open repo link alongside open file", () => {
    renderModal("AI / Machine Learning", false)
    expect(screen.getByTestId("github-open-repo-0")).toBeInTheDocument()
    const repoLink = screen.getByTestId("github-open-repo-0") as HTMLAnchorElement
    expect(repoLink.href).toContain("github.com/machackgo/veribridge-ai")
  })

  it("transcript artifact shows first excerpt (public) without approval for AI/ML", () => {
    renderModal("AI / Machine Learning", false)
    const transcript = screen.getByTestId("skill-artifact-transcript")
    // First excerpt is public
    expect(transcript.textContent).toMatch(/TensorFlow\.js/i)
  })

  it("expanding transcript shows full excerpt lines when approved", async () => {
    renderModal("AI / Machine Learning", true)
    // Second transcript is protected — but there should be an expand button for first (public)
    const expandBtns = screen.getAllByTestId("expand-transcript-0")
    fireEvent.click(expandBtns[0])
    await waitFor(() => expect(screen.getByTestId("transcript-full-0")).toBeInTheDocument())
    expect(screen.getByTestId("transcript-full-0").textContent).toMatch(/80\/20 train\/test split/i)
  })

  it("document artifact shows title, file type, and extracted sections for AI/ML (when approved)", async () => {
    renderModal("AI / Machine Learning", true)
    const docs = screen.getByTestId("skill-artifact-documents")
    expect(docs.textContent).toMatch(/AI Engineering Project Report/i)
    expect(docs.textContent).toMatch(/PDF/i)
    fireEvent.click(screen.getByTestId("expand-document-0"))
    await waitFor(() => expect(screen.getByTestId("document-sections-0")).toBeInTheDocument())
    expect(screen.getByTestId("document-sections-0").textContent).toMatch(/Model Selection/i)
  })

  it("document approved viewer placeholder shown when approved", () => {
    renderModal("AI / Machine Learning", true)
    expect(screen.getByTestId("document-approved-viewer-0")).toBeInTheDocument()
    expect(screen.getByTestId("document-approved-viewer-0").textContent).toMatch(/Approved document file viewer/i)
  })

  it("final analysis artifact shows evidence score and per-source scores", () => {
    renderModal("AI / Machine Learning", false)
    const analysis = screen.getByTestId("skill-artifact-final-analysis")
    expect(analysis.textContent).toMatch(/87/i)
    expect(analysis.textContent).toMatch(/91/i)
    expect(analysis.textContent).toMatch(/Strongly supported/i)
  })

  it("final analysis shows strongest and weakest proof", () => {
    renderModal("AI / Machine Learning", false)
    const analysis = screen.getByTestId("skill-artifact-final-analysis")
    expect(analysis.textContent).toMatch(/Strongest proof/i)
    expect(analysis.textContent).toMatch(/Weakest proof/i)
    expect(analysis.textContent).toMatch(/GitHub code.*3 production service files/i)
  })

  it("DevOps final analysis shows score of 22 and no workflow/GitHub", () => {
    renderModal("DevOps / Deployment", false)
    const analysis = screen.getByTestId("skill-artifact-final-analysis")
    expect(analysis.textContent).toMatch(/22/i)
    expect(analysis.textContent).toMatch(/Needs review/i)
  })

  it("JS/Frontend Qwen analysis shows different observations from AI/ML", () => {
    renderModal("JavaScript / Frontend", false)
    const qwen = screen.getByTestId("skill-artifact-qwen")
    expect(qwen.textContent).toMatch(/React-based recruiter dashboard/i)
    expect(qwen.textContent).not.toMatch(/TensorFlow/i)
  })

  it("modal artifact inspection html contains no unsafe private strings", () => {
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

// ── SkillEvidencePipeline model tests ─────────────────────────────────────────

describe("SkillEvidencePipeline — model structure", () => {
  it("AI/ML pipeline has skillId, skillName, and category", () => {
    const pipeline = getSkillPipeline("AI / Machine Learning")
    expect(pipeline.skillId).toBe("ai-machine-learning")
    expect(pipeline.skillName).toBe("AI / Machine Learning")
    expect(pipeline.category).toBe("AI/ML")
  })

  it("AI/ML pipeline aggregates workflow, GitHub, visual, OCR, DOM, Qwen, transcript, and document evidence", () => {
    const pipeline = getSkillPipeline("AI / Machine Learning")
    expect(pipeline.workflowEvidence.length).toBeGreaterThan(0)
    expect(pipeline.codeEvidence.length).toBeGreaterThan(0)
    expect(pipeline.visualEvidence.length).toBeGreaterThan(0)
    expect(pipeline.ocrEvidence.length).toBeGreaterThan(0)
    expect(pipeline.domEvidence.length).toBeGreaterThan(0)
    expect(pipeline.qwenEvidence.length).toBeGreaterThan(0)
    expect(pipeline.transcriptEvidence.length).toBeGreaterThan(0)
    expect(pipeline.documentEvidence.length).toBeGreaterThan(0)
  })

  it("AI/ML pipeline has multiple projects", () => {
    const pipeline = getSkillPipeline("AI / Machine Learning")
    expect(pipeline.projects.length).toBeGreaterThan(0)
    expect(pipeline.projects[0].name).toMatch(/VeriBridge/i)
  })

  it("AI/ML pipeline has directActions for each evidence type", () => {
    const pipeline = getSkillPipeline("AI / Machine Learning")
    const types = pipeline.directActions.map((a) => a.sourceType)
    expect(types).toContain("workflow")
    expect(types).toContain("github")
    expect(types).toContain("transcript")
    expect(types).toContain("document")
  })

  it("AI/ML pipeline ocrEvidence extracts text from visual frames", () => {
    const pipeline = getSkillPipeline("AI / Machine Learning")
    expect(pipeline.ocrEvidence[0].extractedText).toMatch(/Overall Score: 87/i)
  })

  it("JavaScript/Frontend pipeline has different codeEvidence from AI/ML", () => {
    const aiPipeline = getSkillPipeline("AI / Machine Learning")
    const jsPipeline = getSkillPipeline("JavaScript / Frontend")
    const aiPaths = aiPipeline.codeEvidence.map((f) => f.path)
    const jsPaths = jsPipeline.codeEvidence.map((f) => f.path)
    expect(jsPaths).not.toEqual(aiPaths)
    expect(jsPaths.some((p) => p.includes("RecruiterWorkPassportPreview"))).toBe(true)
    expect(aiPaths.some((p) => p.includes("final_evidence_evaluator_service"))).toBe(true)
  })

  it("JavaScript/Frontend pipeline has different workflowEvidence title from AI/ML", () => {
    const aiPipeline = getSkillPipeline("AI / Machine Learning")
    const jsPipeline = getSkillPipeline("JavaScript / Frontend")
    expect(jsPipeline.workflowEvidence[0].title).not.toBe(aiPipeline.workflowEvidence[0].title)
    expect(jsPipeline.workflowEvidence[0].title).toMatch(/Recruiter Passport/i)
  })

  it("JavaScript/Frontend pipeline category is Frontend", () => {
    const pipeline = getSkillPipeline("JavaScript / Frontend")
    expect(pipeline.category).toBe("Frontend")
  })

  it("Data & Visualization pipeline has partial support status", () => {
    const pipeline = getSkillPipeline("Data & Visualization")
    expect(pipeline.supportStatus).toBe("partially supported")
    expect(pipeline.confidence).toBe("medium")
  })

  it("Data & Visualization pipeline has partial evidenceSources", () => {
    const pipeline = getSkillPipeline("Data & Visualization")
    const partial = pipeline.evidenceSources.filter((s) => s.status === "partial")
    expect(partial.length).toBeGreaterThan(0)
  })

  it("DevOps/Deployment pipeline has needs-review status", () => {
    const pipeline = getSkillPipeline("DevOps / Deployment")
    expect(pipeline.supportStatus).toBe("needs review")
    expect(pipeline.confidence).toBe("low")
  })

  it("DevOps/Deployment pipeline has missing workflow and GitHub evidence", () => {
    const pipeline = getSkillPipeline("DevOps / Deployment")
    expect(pipeline.workflowEvidence.length).toBe(0)
    expect(pipeline.codeEvidence.length).toBe(0)
    const wfSource = pipeline.evidenceSources.find((s) => s.key === "workflow")
    expect(wfSource?.status).toBe("missing")
  })

  it("DevOps/Deployment pipeline has document-only coverage", () => {
    const pipeline = getSkillPipeline("DevOps / Deployment")
    expect(pipeline.documentEvidence.length).toBeGreaterThan(0)
    expect(pipeline.transcriptEvidence.length).toBe(0)
  })

  it("pipeline evidenceSources matches bundle sources", () => {
    const pipeline = getSkillPipeline("AI / Machine Learning")
    expect(pipeline.evidenceSources.length).toBe(7)
    expect(pipeline.evidenceSources.map((s) => s.key)).toContain("workflow")
    expect(pipeline.evidenceSources.map((s) => s.key)).toContain("github")
    expect(pipeline.evidenceSources.map((s) => s.key)).toContain("documents")
    expect(pipeline.evidenceSources.map((s) => s.key)).toContain("dom")
  })

  it("pipeline does not expose unsafe strings in any field", () => {
    const pipeline = getSkillPipeline("AI / Machine Learning")
    const serialized = JSON.stringify(pipeline)
    expect(serialized).not.toContain("localhost")
    expect(serialized).not.toContain("access_token")
    expect(serialized).not.toContain("storage_path")
    expect(serialized).not.toContain("token=")
    expect(serialized).not.toContain("supabase")
  })
})

// ── Document artifact action tests ────────────────────────────────────────────

describe("SkillEvidenceDetailModal — document artifact actions", () => {
  function renderModal(skillName: string, accessApproved: boolean) {
    render(
      <SkillEvidenceDetailModal
        skillName={skillName}
        accessApproved={accessApproved}
        onClose={() => {}}
      />,
    )
  }

  it("document section shows Open document and Download document actions when approved", () => {
    renderModal("AI / Machine Learning", true)
    expect(screen.getByTestId("open-document-btn-0")).toBeInTheDocument()
    expect(screen.getByTestId("download-document-btn-0")).toBeInTheDocument()
  })

  it("Open document and Download document buttons visible for public document without approval", () => {
    renderModal("Data & Visualization", false)
    // Data & Viz document is public (isProtected: false)
    expect(screen.getByTestId("open-document-btn-0")).toBeInTheDocument()
    expect(screen.getByTestId("download-document-btn-0")).toBeInTheDocument()
  })

  it("protected document download is locked before approval", () => {
    renderModal("AI / Machine Learning", false)
    // AI/ML document is protected — canView=false → shows locked state
    expect(screen.getByTestId("document-download-locked-0")).toBeInTheDocument()
    expect(screen.getByTestId("document-download-locked-0").textContent).toMatch(/student approval/i)
  })

  it("protected document download locked message says approval required", () => {
    renderModal("AI / Machine Learning", false)
    const locked = screen.getByTestId("document-download-locked-0")
    expect(locked.textContent).toMatch(/Document download requires student approval/i)
  })

  it("approved document download action buttons are visible after approval", () => {
    renderModal("AI / Machine Learning", true)
    // Protected AI/ML document — with approval, canView=true, buttons appear
    expect(screen.queryByTestId("document-download-locked-0")).not.toBeInTheDocument()
    expect(screen.getByTestId("open-document-btn-0")).toBeInTheDocument()
    expect(screen.getByTestId("download-document-btn-0")).toBeInTheDocument()
  })

  it("DevOps document is public — action buttons visible without approval", () => {
    renderModal("DevOps / Deployment", false)
    expect(screen.getByTestId("open-document-btn-0")).toBeInTheDocument()
    expect(screen.getByTestId("download-document-btn-0")).toBeInTheDocument()
  })

  it("document action buttons do not render raw storage_path or Supabase URL", () => {
    const { container } = render(
      <SkillEvidenceDetailModal skillName="AI / Machine Learning" accessApproved={true} onClose={() => {}} />,
    )
    const html = container.innerHTML
    expect(html).not.toContain("storage_path")
    expect(html).not.toContain("supabase")
    expect(html).not.toContain("access_token")
    expect(html).not.toContain("token=")
    expect(html).not.toContain("localhost")
  })
})

// ── Transcript artifact download tests ───────────────────────────────────────

describe("SkillEvidenceDetailModal — transcript download actions", () => {
  function renderModal(skillName: string, accessApproved: boolean) {
    render(
      <SkillEvidenceDetailModal
        skillName={skillName}
        accessApproved={accessApproved}
        onClose={() => {}}
      />,
    )
  }

  it("transcript section shows Download transcript TXT button for AI/ML", () => {
    renderModal("AI / Machine Learning", false)
    expect(screen.getByTestId("download-transcript-txt-btn")).toBeInTheDocument()
  })

  it("transcript TXT download button is enabled when transcript evidence exists", () => {
    renderModal("AI / Machine Learning", false)
    const btn = screen.getByTestId("download-transcript-txt-btn")
    expect(btn).not.toBeDisabled()
  })

  it("transcript PDF download action is visible but disabled (placeholder)", () => {
    renderModal("AI / Machine Learning", false)
    const pdfBtn = screen.getByTestId("download-transcript-pdf-btn")
    expect(pdfBtn).toBeInTheDocument()
    expect(pdfBtn).toBeDisabled()
  })

  it("transcript PDF placeholder button has tooltip about export service", () => {
    renderModal("AI / Machine Learning", false)
    const pdfBtn = screen.getByTestId("download-transcript-pdf-btn")
    expect(pdfBtn).toHaveAttribute("title")
    expect(pdfBtn.getAttribute("title")).toMatch(/transcript export service/i)
  })

  it("transcript download action row is visible even without approval (for public excerpts)", () => {
    renderModal("AI / Machine Learning", false)
    expect(screen.getByTestId("transcript-download-actions")).toBeInTheDocument()
  })

  it("transcript download actions do not render when skill has no transcript evidence", () => {
    renderModal("DevOps / Deployment", false)
    // DevOps has no transcript evidence — the entire section shows empty state, no download buttons
    expect(screen.queryByTestId("download-transcript-txt-btn")).not.toBeInTheDocument()
  })

  it("transcript export excludes unsafe strings from component HTML", () => {
    const { container } = render(
      <SkillEvidenceDetailModal skillName="AI / Machine Learning" accessApproved={true} onClose={() => {}} />,
    )
    const html = container.innerHTML
    expect(html).not.toContain("storage_path")
    expect(html).not.toContain("supabase")
    expect(html).not.toContain("access_token")
    expect(html).not.toContain("token=")
    expect(html).not.toContain("localhost")
    expect(html).not.toContain("raw_url")
  })

  it("skill-specific transcript includes skill name in download button section for AI/ML", () => {
    renderModal("AI / Machine Learning", false)
    // The section renders with the skill name available (passed via skillName prop)
    const transcript = screen.getByTestId("skill-artifact-transcript")
    expect(transcript).toBeInTheDocument()
    expect(screen.getByTestId("download-transcript-txt-btn")).toBeInTheDocument()
  })

  it("JS/Frontend transcript download button is present for that skill", () => {
    renderModal("JavaScript / Frontend", false)
    expect(screen.getByTestId("download-transcript-txt-btn")).toBeInTheDocument()
  })

  it("UI still renders skill evidence cards from pipeline data", () => {
    renderModal("AI / Machine Learning", false)
    expect(screen.getByTestId("skill-artifact-workflow-recording")).toBeInTheDocument()
    expect(screen.getByTestId("skill-artifact-keyframes")).toBeInTheDocument()
    expect(screen.getByTestId("skill-artifact-github")).toBeInTheDocument()
    expect(screen.getByTestId("skill-artifact-transcript")).toBeInTheDocument()
    expect(screen.getByTestId("skill-artifact-documents")).toBeInTheDocument()
    expect(screen.getByTestId("skill-artifact-final-analysis")).toBeInTheDocument()
  })
})

// ── GitHub line-level proof links ─────────────────────────────────────────────

describe("SkillEvidenceDetailModal — GitHub line-level proof links", () => {
  function renderModal(skillName: string, accessApproved = false) {
    render(
      <SkillEvidenceDetailModal
        skillName={skillName}
        accessApproved={accessApproved}
        onClose={() => {}}
      />,
    )
  }

  it("AI/ML GitHub evidence renders line range badge L40–L140 for first file", () => {
    renderModal("AI / Machine Learning")
    const badge = screen.getByTestId("github-line-range-0")
    expect(badge).toBeInTheDocument()
    expect(badge.textContent).toMatch(/L40/)
    expect(badge.textContent).toMatch(/L140/)
  })

  it("AI/ML GitHub evidence shows symbol name FinalEvidenceEvaluatorService", () => {
    renderModal("AI / Machine Learning")
    const github = screen.getByTestId("skill-artifact-github")
    expect(github.textContent).toMatch(/FinalEvidenceEvaluatorService/i)
  })

  it("AI/ML GitHub evidence shows code block summary for first file", () => {
    renderModal("AI / Machine Learning")
    const github = screen.getByTestId("skill-artifact-github")
    expect(github.textContent).toMatch(/weighted aggregation logic/i)
  })

  it("Open exact code block button is present for AI/ML first file", () => {
    renderModal("AI / Machine Learning")
    expect(screen.getByTestId("github-open-exact-0")).toBeInTheDocument()
  })

  it("Open exact code block href includes /blob/main/ for AI/ML", () => {
    renderModal("AI / Machine Learning")
    const link = screen.getByTestId("github-open-exact-0") as HTMLAnchorElement
    expect(link.href).toContain("github.com/machackgo/veribridge-ai/blob/main/")
  })

  it("Open exact code block href includes #L40-L140 anchor for AI/ML first file", () => {
    renderModal("AI / Machine Learning")
    const link = screen.getByTestId("github-open-exact-0") as HTMLAnchorElement
    expect(link.href).toContain("#L40-L140")
  })

  it("Open exact code block href includes file path for AI/ML first file", () => {
    renderModal("AI / Machine Learning")
    const link = screen.getByTestId("github-open-exact-0") as HTMLAnchorElement
    expect(link.href).toContain("final_evidence_evaluator_service.py")
  })

  it("Open full file href does not include line anchor for AI/ML", () => {
    renderModal("AI / Machine Learning")
    const link = screen.getByTestId("github-open-file-0") as HTMLAnchorElement
    expect(link.href).not.toContain("#L")
    expect(link.href).toContain("/blob/main/")
  })

  it("Open full file still points to /blob/main/ path for AI/ML", () => {
    renderModal("AI / Machine Learning")
    const link = screen.getByTestId("github-open-file-0") as HTMLAnchorElement
    expect(link.href).toContain("github.com/machackgo/veribridge-ai/blob/main/")
    expect(link.href).toContain("final_evidence_evaluator_service.py")
  })

  it("Open repository button still present for AI/ML", () => {
    renderModal("AI / Machine Learning")
    const link = screen.getByTestId("github-open-repo-0") as HTMLAnchorElement
    expect(link.href).toContain("github.com/machackgo/veribridge-ai")
    expect(link.href).not.toContain("/blob/")
  })

  it("AI/ML second file (extension_proof_workflow_analysis_service.py) has L80–L180 badge", () => {
    renderModal("AI / Machine Learning")
    const badge = screen.getByTestId("github-line-range-1")
    expect(badge.textContent).toMatch(/L80/)
    expect(badge.textContent).toMatch(/L180/)
  })

  it("AI/ML third file (verification_review_service.py) has L30–L120 badge", () => {
    renderModal("AI / Machine Learning")
    const badge = screen.getByTestId("github-line-range-2")
    expect(badge.textContent).toMatch(/L30/)
    expect(badge.textContent).toMatch(/L120/)
  })

  it("AI/ML exact code links are different from JavaScript/Frontend exact code links", () => {
    renderModal("AI / Machine Learning")
    const aiLink = screen.getByTestId("github-open-exact-0") as HTMLAnchorElement
    const aiHref = aiLink.href

    render(
      <SkillEvidenceDetailModal
        skillName="JavaScript / Frontend"
        accessApproved={false}
        onClose={() => {}}
      />,
    )
    const jsLink = screen.getAllByTestId("github-open-exact-0")[1] as HTMLAnchorElement
    expect(aiHref).not.toBe(jsLink.href)
    expect(aiHref).toContain("final_evidence_evaluator_service")
    expect(jsLink.href).toContain("RecruiterWorkPassportPreview")
  })

  it("JavaScript/Frontend first file has L300–L520 badge", () => {
    renderModal("JavaScript / Frontend")
    const badge = screen.getByTestId("github-line-range-0")
    expect(badge.textContent).toMatch(/L300/)
    expect(badge.textContent).toMatch(/L520/)
  })

  it("JavaScript/Frontend exact code link includes #L300-L520 anchor", () => {
    renderModal("JavaScript / Frontend")
    const link = screen.getByTestId("github-open-exact-0") as HTMLAnchorElement
    expect(link.href).toContain("#L300-L520")
    expect(link.href).toContain("RecruiterWorkPassportPreview.tsx")
  })

  it("JavaScript/Frontend second file (extension-proof-panel.tsx) has L120–L260 badge", () => {
    renderModal("JavaScript / Frontend")
    const badge = screen.getByTestId("github-line-range-1")
    expect(badge.textContent).toMatch(/L120/)
    expect(badge.textContent).toMatch(/L260/)
  })

  it("JavaScript/Frontend exact code link for extension-proof-panel includes #L120-L260", () => {
    renderModal("JavaScript / Frontend")
    const link = screen.getByTestId("github-open-exact-1") as HTMLAnchorElement
    expect(link.href).toContain("#L120-L260")
    expect(link.href).toContain("extension-proof-panel")
  })

  it("JavaScript/Frontend third file (recruiter/passport/page.tsx) has L20–L110 badge", () => {
    renderModal("JavaScript / Frontend")
    const badge = screen.getByTestId("github-line-range-2")
    expect(badge.textContent).toMatch(/L20/)
    expect(badge.textContent).toMatch(/L110/)
  })

  it("Data/Visualization first file has L520–L700 badge for EvidenceCoverageGrid", () => {
    renderModal("Data & Visualization")
    const badge = screen.getByTestId("github-line-range-0")
    expect(badge.textContent).toMatch(/L520/)
    expect(badge.textContent).toMatch(/L700/)
  })

  it("Data/Visualization shows EvidenceCoverageGrid symbol name", () => {
    renderModal("Data & Visualization")
    const github = screen.getByTestId("skill-artifact-github")
    expect(github.textContent).toMatch(/EvidenceCoverageGrid/i)
  })

  it("protected/private GitHub evidence shows locked state without exact code link", () => {
    renderModal("Data & Visualization")
    // Third file is private (isPublic: false) — should show locked state
    const locked = screen.getByTestId("github-locked-2")
    expect(locked).toBeInTheDocument()
    expect(locked.textContent).toMatch(/student approval/i)
    // Exact code link must not appear for private file
    expect(screen.queryByTestId("github-open-exact-2")).not.toBeInTheDocument()
  })

  it("private file does not render Open full file link", () => {
    renderModal("Data & Visualization")
    // index 2 is private — no full file link
    expect(screen.queryByTestId("github-open-file-2")).not.toBeInTheDocument()
  })

  it("GitHub artifact html does not contain unsafe private strings", () => {
    const { container } = render(
      <SkillEvidenceDetailModal skillName="AI / Machine Learning" accessApproved={true} onClose={() => {}} />,
    )
    const html = container.innerHTML
    expect(html).not.toContain("token")
    expect(html).not.toContain("access_token")
    expect(html).not.toContain("storage_path")
    expect(html).not.toContain("supabase")
    expect(html).not.toContain("localhost")
    expect(html).not.toContain("raw_url")
    expect(html).not.toContain("127.0.0.1")
  })

  it("GitHub artifact html does not contain candidate-repo fake placeholder URL", () => {
    const { container } = render(
      <SkillEvidenceDetailModal skillName="AI / Machine Learning" accessApproved={false} onClose={() => {}} />,
    )
    expect(container.innerHTML).not.toContain("candidate-repo")
  })
})

// ── Backend skill pipeline integration ────────────────────────────────────────

describe("RecruiterWorkPassportPreview — backend skill pipeline integration", () => {
  // View with no skills at all — forces the backend-pipeline code path.
  function makeEmptyView() {
    return makeView({
      skill_groups: [],
      verified_skills: [],
      partially_verified_skills: [],
      skills_needing_review: [],
    })
  }

  const mockPipeline: BackendSkillPipeline = {
    id: "pipeline-ts-1",
    student_id: "s-1",
    profile_id: "p-1",
    skill_name: "TypeScript",
    skill_category: "Frontend",
    confidence_score: 80,
    support_status: "strongly_supported",
    evidence_count: 2,
    strongest_proof: { label: "GitHub code", reason: "TypeScript throughout codebase" },
    weakest_proof: null,
    missing_evidence: [],
    next_actions: [],
    evidence_sources: [
      { key: "github", label: "GitHub code", status: "supported", score: 80, reason: "TS imports found" },
      { key: "project", label: "Project defense", status: "partial", score: 50, reason: "mentioned in defense" },
    ],
    recruiter_summary: "Strong TypeScript evidence from GitHub and project defense.",
    student_summary: "PRIVATE_student_summary_do_not_render",
    visibility_status: "public",
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
  }

  afterEach(() => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
  })

  it("shows loading placeholder while backend fetch is pending (no view skills)", () => {
    let settle!: () => void
    const pending = new Promise<null>((r) => { settle = () => r(null) })
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockReturnValue(pending)
    render(<RecruiterWorkPassportPreview view={makeEmptyView()} />)
    expect(screen.getByTestId("skill-pipelines-loading")).toBeInTheDocument()
    settle()
  })

  it("safe fallback: existing view skills still render when backend returns null", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
    render(<RecruiterWorkPassportPreview view={makeView()} />)
    await waitFor(() => {
      expect(screen.getAllByText("Chatbot UI").length).toBeGreaterThan(0)
      expect(screen.getAllByText("React").length).toBeGreaterThan(0)
    })
  })

  it("renders skill name from backend pipeline when view has no skills", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([mockPipeline])
    render(<RecruiterWorkPassportPreview view={makeEmptyView()} />)
    await waitFor(() => {
      expect(screen.getAllByText("TypeScript").length).toBeGreaterThan(0)
    })
  })

  it("shows backend pipelines badge when backend provides pipelines", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([mockPipeline])
    render(<RecruiterWorkPassportPreview view={makeEmptyView()} />)
    await waitFor(() => {
      expect(screen.getByTestId("backend-pipelines-badge")).toBeInTheDocument()
    })
    expect(screen.getByTestId("backend-pipelines-badge").textContent).toMatch(/pipeline/)
  })

  it("shows empty state when backend returns an empty list", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([])
    render(<RecruiterWorkPassportPreview view={makeEmptyView()} />)
    await waitFor(() => {
      expect(screen.getByTestId("skill-pipelines-empty")).toBeInTheDocument()
    })
  })

  it("backend pipeline evidence section renders Evidence-Backed Skills heading", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([mockPipeline])
    render(<RecruiterWorkPassportPreview view={makeEmptyView()} />)
    await waitFor(() => {
      expect(screen.getByTestId("evidence-backed-skills-section")).toBeInTheDocument()
    })
  })

  it("does not render student_summary from backend pipeline in recruiter HTML", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([mockPipeline])
    const { container } = render(<RecruiterWorkPassportPreview view={makeEmptyView()} />)
    await waitFor(() => expect(screen.getAllByText("TypeScript").length).toBeGreaterThan(0))
    expect(container.innerHTML).not.toContain("PRIVATE_student_summary_do_not_render")
  })

  it("does not render student_id from backend pipeline in recruiter HTML", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([mockPipeline])
    const { container } = render(<RecruiterWorkPassportPreview view={makeEmptyView()} />)
    await waitFor(() => expect(screen.getAllByText("TypeScript").length).toBeGreaterThan(0))
    expect(container.innerHTML).not.toContain('"s-1"')
  })

  it("AI/ML SkillEvidenceDetailModal still opens and shows evidence from static mock", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([mockPipeline])
    render(<SkillEvidenceDetailModal skillName="AI / Machine Learning" accessApproved={false} onClose={() => {}} />)
    expect(screen.getAllByText(/AI \/ Machine Learning/i).length).toBeGreaterThan(0)
    // Static GitHub evidence still present
    expect(screen.getAllByText(/FinalEvidenceEvaluatorService/i).length).toBeGreaterThan(0)
  })

  it("GitHub exact code links still include /blob/main/ and #Lstart-Lend after backend load", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([mockPipeline])
    render(<SkillEvidenceDetailModal skillName="AI / Machine Learning" accessApproved={true} onClose={() => {}} />)
    const exactLinks = screen.getAllByTestId(/github-open-exact-/)
    expect(exactLinks.length).toBeGreaterThan(0)
    const href = exactLinks[0].getAttribute("href") ?? ""
    expect(href).toContain("/blob/main/")
    expect(href).toMatch(/#L\d+-L\d+/)
  })
})
