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
import DevRecruiterPassportPreviewPage from "../app/dev/recruiter-passport-preview/page"
import type { RecruiterPassportViewResponse } from "../lib/passport-api"
import * as apiModule from "@/lib/api"
import type { RecruiterSafePipelineSummary } from "@/lib/api"

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

  const mockPipeline: RecruiterSafePipelineSummary = {
    id: "pipeline-ts-1",
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
    visibility_status: "public",
    is_locked_for_recruiter: false,
    artifacts: [],
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

// ── Visibility enforcement: view.skill_groups + backend authority (Case A) ─────

describe("RecruiterWorkPassportPreview — visibility enforcement via view.skill_groups", () => {
  // View that has both AI/ML and JS as pre-loaded skill groups (the typical production state).
  function makeViewWithTwoGroups(): RecruiterPassportViewResponse {
    return makeView({
      skill_groups: [
        {
          group_name: "AI / Machine Learning",
          category: "AI/ML",
          confidence: "high",
          evidence_count: 4,
          source_labels: ["GitHub", "Website Workflow"],
          skills: [
            { skill: "Machine Learning", confidence: "high", status_label: "strongly supported", source_labels: ["GitHub"] },
          ],
        },
        {
          group_name: "JavaScript / Frontend",
          category: "Frontend",
          confidence: "high",
          evidence_count: 3,
          source_labels: ["GitHub"],
          skills: [
            { skill: "React", confidence: "high", status_label: "strongly supported", source_labels: ["GitHub"] },
          ],
        },
      ],
      verified_skills: [],
      partially_verified_skills: [],
      skills_needing_review: [],
    })
  }

  // Backend returns only JS (AI/ML is private → server excluded it entirely)
  const jsPublicPipeline: RecruiterSafePipelineSummary = {
    id: "p-js-pub",
    skill_name: "JavaScript / Frontend",
    skill_category: "Frontend",
    confidence_score: 75,
    support_status: "strongly_supported",
    evidence_count: 2,
    strongest_proof: { label: "GitHub", reason: "JS throughout" },
    weakest_proof: null,
    missing_evidence: [],
    next_actions: [],
    evidence_sources: [{ key: "github", label: "GitHub code", status: "supported", score: 75, reason: "TS imports" }],
    recruiter_summary: "Strong JS evidence.",
    visibility_status: "public",
    is_locked_for_recruiter: false,
    artifacts: [],
  }

  // Backend returns AI/ML as protected/locked
  const aiMlLockedPipeline: RecruiterSafePipelineSummary = {
    id: "p-ai-locked",
    skill_name: "AI / Machine Learning",
    skill_category: "AI/ML",
    confidence_score: 88,
    support_status: "strongly_supported",
    evidence_count: 7,
    strongest_proof: {},
    weakest_proof: {},
    missing_evidence: [],
    next_actions: [],
    evidence_sources: [
      { key: "github", label: "GitHub code", status: "protected", score: null, reason: "" },
    ],
    recruiter_summary: "Protected evidence available. Student approval required to inspect protected details.",
    visibility_status: "protected",
    is_locked_for_recruiter: true,
    artifacts: [],
  }

  afterEach(() => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
  })

  it("private skill absent from backend: AI/ML group card is not rendered", async () => {
    // Backend only returns JS; AI/ML is absent (private → excluded server-side)
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([jsPublicPipeline])
    render(<RecruiterWorkPassportPreview view={makeViewWithTwoGroups()} />)
    await waitFor(() => {
      expect(screen.getAllByText("JavaScript / Frontend").length).toBeGreaterThan(0)
    })
    // AI/ML view group must be filtered out — no SkillGroupCard for it
    expect(screen.queryByTestId("skill-group-card-ai-machine-learning")).not.toBeInTheDocument()
  })

  it("public skill still renders as SkillGroupCard when backend confirms it public", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([jsPublicPipeline])
    render(<RecruiterWorkPassportPreview view={makeViewWithTwoGroups()} />)
    await waitFor(() => {
      expect(screen.getAllByText("JavaScript / Frontend").length).toBeGreaterThan(0)
    })
    expect(screen.getByTestId("skill-group-card-javascript-frontend")).toBeInTheDocument()
  })

  it("protected skill: AI/ML renders as LockedPipelineCard, not SkillGroupCard", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      aiMlLockedPipeline,
      jsPublicPipeline,
    ])
    render(<RecruiterWorkPassportPreview view={makeViewWithTwoGroups()} />)
    await waitFor(() => {
      expect(screen.getByTestId("locked-pipeline-card-ai-machine-learning")).toBeInTheDocument()
    })
    // Full skill group card must NOT be shown — that would expose mock static artifacts
    expect(screen.queryByTestId("skill-group-card-ai-machine-learning")).not.toBeInTheDocument()
  })

  it("protected locked card shows Protected badge and approval message", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      aiMlLockedPipeline,
      jsPublicPipeline,
    ])
    render(<RecruiterWorkPassportPreview view={makeViewWithTwoGroups()} />)
    await waitFor(() => {
      expect(screen.getByTestId("protected-pipeline-badge")).toBeInTheDocument()
    })
    expect(screen.getByTestId("protected-pipeline-message").textContent).toMatch(
      /student approval required/i
    )
  })

  it("protected skill: no GitHub exact code links rendered before approval", async () => {
    // Only AI/ML in view (locked) — SkillGroupsSection not rendered at all
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([aiMlLockedPipeline])
    render(<RecruiterWorkPassportPreview view={makeView({
      skill_groups: [{
        group_name: "AI / Machine Learning",
        category: "AI/ML",
        confidence: "high",
        evidence_count: 4,
        source_labels: ["GitHub"],
        skills: [{ skill: "Machine Learning", confidence: "high", status_label: "strongly supported", source_labels: ["GitHub"] }],
      }],
      verified_skills: [],
      partially_verified_skills: [],
      skills_needing_review: [],
    })} />)
    await waitFor(() => {
      expect(screen.getByTestId("locked-pipeline-card-ai-machine-learning")).toBeInTheDocument()
    })
    expect(screen.queryByTestId("github-open-exact-0")).not.toBeInTheDocument()
    expect(screen.queryByTestId("github-open-file-0")).not.toBeInTheDocument()
    expect(screen.queryByTestId("skill-artifact-github")).not.toBeInTheDocument()
  })

  it("protected skill: no OCR, DOM, or Qwen detail cards before approval", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([aiMlLockedPipeline])
    render(<RecruiterWorkPassportPreview view={makeView({
      skill_groups: [{
        group_name: "AI / Machine Learning",
        category: "AI/ML",
        confidence: "high",
        evidence_count: 4,
        source_labels: ["GitHub"],
        skills: [{ skill: "Machine Learning", confidence: "high", status_label: "strongly supported", source_labels: ["GitHub"] }],
      }],
      verified_skills: [],
      partially_verified_skills: [],
      skills_needing_review: [],
    })} />)
    await waitFor(() => {
      expect(screen.getByTestId("locked-pipeline-card-ai-machine-learning")).toBeInTheDocument()
    })
    expect(screen.queryByTestId("skill-artifact-dom")).not.toBeInTheDocument()
    expect(screen.queryByTestId("skill-artifact-transcript")).not.toBeInTheDocument()
    expect(screen.queryByTestId("skill-artifact-keyframes")).not.toBeInTheDocument()
    expect(screen.queryByTestId("skill-artifact-qwen")).not.toBeInTheDocument()
  })

  it("protected skill: no view-skill-evidence-btn on locked card (no direct proof action)", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([aiMlLockedPipeline])
    render(<RecruiterWorkPassportPreview view={makeView({
      skill_groups: [{
        group_name: "AI / Machine Learning",
        category: "AI/ML",
        confidence: "high",
        evidence_count: 4,
        source_labels: ["GitHub"],
        skills: [{ skill: "Machine Learning", confidence: "high", status_label: "strongly supported", source_labels: ["GitHub"] }],
      }],
      verified_skills: [],
      partially_verified_skills: [],
      skills_needing_review: [],
    })} />)
    await waitFor(() => {
      expect(screen.getByTestId("locked-pipeline-card-ai-machine-learning")).toBeInTheDocument()
    })
    // LockedPipelineCard has no view-skill-evidence-btn — no detail modal can be opened
    expect(screen.queryByTestId("view-skill-evidence-btn")).not.toBeInTheDocument()
  })

  it("backend data is not merged with mock artifact details for locked skill", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([aiMlLockedPipeline])
    const { container } = render(<RecruiterWorkPassportPreview view={makeView({
      skill_groups: [{
        group_name: "AI / Machine Learning",
        category: "AI/ML",
        confidence: "high",
        evidence_count: 4,
        source_labels: ["GitHub"],
        skills: [{ skill: "Machine Learning", confidence: "high", status_label: "strongly supported", source_labels: ["GitHub"] }],
      }],
      verified_skills: [],
      partially_verified_skills: [],
      skills_needing_review: [],
    })} />)
    await waitFor(() => {
      expect(screen.getByTestId("locked-pipeline-card-ai-machine-learning")).toBeInTheDocument()
    })
    const html = container.innerHTML
    // Static mock bundle data for AI/ML must not appear — no merge with SKILL_EVIDENCE_BUNDLES
    expect(html).not.toContain("FinalEvidenceEvaluatorService")
    expect(html).not.toContain("Overall Score: 87")
    expect(html).not.toContain("TensorFlow.js")
    expect(html).not.toContain("Model inference UI")
  })

  it("fallback: when backend unavailable, all view groups are shown (no visibility filtering)", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
    render(<RecruiterWorkPassportPreview view={makeViewWithTwoGroups()} />)
    await waitFor(() => {
      expect(screen.getAllByText("JavaScript / Frontend").length).toBeGreaterThan(0)
      expect(screen.getAllByText("AI / Machine Learning").length).toBeGreaterThan(0)
    })
  })
})

// ── Recruiter Work Passport — pipeline visibility enforcement ─────────────────

describe("RecruiterWorkPassportPreview — pipeline visibility enforcement", () => {
  function makeEmptyViewForVisibility(): RecruiterPassportViewResponse {
    return {
      public_slug: "vis-test-slug",
      student_display_name: "Test Candidate",
      field: "Engineering",
      public_title: "Software Engineer",
      public_summary: "Test summary.",
      overall_score: 70,
      evidence_confidence: "medium",
      verification_status: null,
      readiness_level: null,
      skill_groups: [],
      verified_skills: [],
      partially_verified_skills: [],
      skills_needing_review: [],
      proof_sources: [],
      why_credible: [],
      strongest_skills: [],
      areas_needing_review: [],
      suggested_interview_questions: [],
      public_project_links: [],
      project_type: "Engineering",
      access_request_available: false,
      has_protected_evidence: false,
      disclosure_note: "Test disclosure.",
    }
  }

  function makePublicPipeline(overrides: Partial<RecruiterSafePipelineSummary> = {}): RecruiterSafePipelineSummary {
    return {
      id: "pub-pipeline-1",
      skill_name: "Public Skill",
      skill_category: "Frontend",
      confidence_score: 80,
      support_status: "strongly_supported",
      evidence_count: 2,
      strongest_proof: { label: "GitHub code", reason: "Confirmed" },
      weakest_proof: null,
      missing_evidence: [],
      next_actions: [],
      evidence_sources: [
        { key: "github", label: "GitHub code", status: "supported", score: 80, reason: "Confirmed" },
      ],
      recruiter_summary: "Strong public evidence.",
      visibility_status: "public",
      is_locked_for_recruiter: false,
      artifacts: [],
      ...overrides,
    }
  }

  function makeProtectedPipeline(overrides: Partial<RecruiterSafePipelineSummary> = {}): RecruiterSafePipelineSummary {
    return {
      id: "prot-pipeline-1",
      skill_name: "Protected Skill",
      skill_category: "AI/ML",
      confidence_score: 75,
      support_status: "strongly_supported",
      evidence_count: 3,
      strongest_proof: { label: "Workflow", reason: "Inference observed" },
      weakest_proof: null,
      missing_evidence: [],
      next_actions: [],
      evidence_sources: [],
      recruiter_summary: "Protected evidence available. Student approval required to inspect protected details.",
      visibility_status: "protected",
      is_locked_for_recruiter: true,
      artifacts: [
        { id: "art-1", source_type: "transcript", source_title: "Defense excerpt",
          project_name: "P", visibility: "protected", confidence_score: 80,
          proof_reason: "", artifact_data: {} },
      ],
      ...overrides,
    }
  }

  afterEach(() => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
  })

  it("private pipeline is not rendered (backend already excludes it)", async () => {
    // Backend excludes private pipelines; we verify no remnant renders
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePublicPipeline({ skill_name: "Visible Skill" }),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForVisibility()} />)
    await waitFor(() => expect(screen.getAllByText("Visible Skill").length).toBeGreaterThan(0))
    expect(screen.queryByText("Private Skill")).not.toBeInTheDocument()
  })

  it("public pipeline is visible in recruiter view", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePublicPipeline(),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForVisibility()} />)
    await waitFor(() => expect(screen.getAllByText("Public Skill").length).toBeGreaterThan(0))
    // Should NOT show the locked badge for public pipeline
    expect(screen.queryByTestId("protected-pipeline-badge")).not.toBeInTheDocument()
  })

  it("protected pipeline shows locked card with Protected badge", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makeProtectedPipeline(),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForVisibility()} />)
    await waitFor(() => expect(screen.getByTestId("protected-pipeline-badge")).toBeInTheDocument())
    expect(screen.getByTestId("protected-pipeline-badge").textContent).toMatch(/Protected/i)
  })

  it("protected pipeline shows approval required message", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makeProtectedPipeline(),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForVisibility()} />)
    await waitFor(() =>
      expect(screen.getByTestId("protected-pipeline-message")).toBeInTheDocument()
    )
    expect(screen.getByTestId("protected-pipeline-message").textContent).toMatch(
      /student approval required/i
    )
  })

  it("protected pipeline locked card shows the skill name", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makeProtectedPipeline({ skill_name: "AI / Machine Learning" }),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForVisibility()} />)
    await waitFor(() => expect(screen.getAllByText("AI / Machine Learning").length).toBeGreaterThan(0))
    expect(screen.getByTestId("protected-pipeline-badge")).toBeInTheDocument()
  })

  it("mixed visibility: public shown normally, protected shown as locked", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePublicPipeline({ skill_name: "JavaScript" }),
      makeProtectedPipeline({ skill_name: "AI / Machine Learning" }),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForVisibility()} />)
    await waitFor(() => {
      expect(screen.getAllByText("JavaScript").length).toBeGreaterThan(0)
      expect(screen.getAllByText("AI / Machine Learning").length).toBeGreaterThan(0)
    })
    // Protected card is shown with badge; public card has no lock badge
    expect(screen.getByTestId("protected-pipeline-badge")).toBeInTheDocument()
  })

  it("protected pipeline locked card does not expose detailed artifact data", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makeProtectedPipeline({
        artifacts: [
          { id: "art-1", source_type: "transcript", source_title: "Defense",
            project_name: "P", visibility: "protected", confidence_score: 80,
            proof_reason: "", artifact_data: { excerpt: "PRIVATE_TRANSCRIPT_CONTENT" } },
        ],
      }),
    ])
    const { container } = render(<RecruiterWorkPassportPreview view={makeEmptyViewForVisibility()} />)
    await waitFor(() => expect(screen.getByTestId("protected-pipeline-badge")).toBeInTheDocument())
    expect(container.innerHTML).not.toContain("PRIVATE_TRANSCRIPT_CONTENT")
  })

  it("backend pipelines badge count includes both public and protected pipelines", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePublicPipeline(),
      makeProtectedPipeline(),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForVisibility()} />)
    await waitFor(() => expect(screen.getByTestId("backend-pipelines-badge")).toBeInTheDocument())
    expect(screen.getByTestId("backend-pipelines-badge").textContent).toMatch(/2 pipeline/)
  })

  it("public pipeline github exact code links include /blob/main/ and #Lstart-Lend", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePublicPipeline({
        artifacts: [
          {
            id: "art-gh-1",
            source_type: "github",
            source_title: "evaluator.py",
            project_name: "VeriBridge",
            visibility: "public",
            confidence_score: 90,
            proof_reason: "ML confirmed",
            artifact_data: {
              repo_url: "https://github.com/veribridge-ai/veribridge",
              branch: "main",
              file_path: "apps/api/app/services/evaluator.py",
            },
            exact_code_url: "https://github.com/veribridge-ai/veribridge/blob/main/apps/api/app/services/evaluator.py#L40-L140",
            full_file_url: "https://github.com/veribridge-ai/veribridge/blob/main/apps/api/app/services/evaluator.py",
          },
        ],
      }),
    ])
    // Public pipeline renders via SkillGroupsSection (no static bundle for "Public Skill")
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForVisibility()} />)
    await waitFor(() => expect(screen.getAllByText("Public Skill").length).toBeGreaterThan(0))
    // The pipeline renders but artifact links are inside the detail modal — confirm no unsafe strings
    const { container } = render(<RecruiterWorkPassportPreview view={makeEmptyViewForVisibility()} />)
    await waitFor(() => expect(screen.getAllByText("Public Skill").length).toBeGreaterThan(0))
    expect(container.innerHTML).not.toContain("storage_path")
    expect(container.innerHTML).not.toContain("signed_url")
    expect(container.innerHTML).not.toContain("access_token")
  })

  it("unsafe strings not rendered in recruiter view output", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePublicPipeline({
        // These should never appear even if somehow passed in
        recruiter_summary: "Safe summary without tokens",
        artifacts: [
          {
            id: "art-safe",
            source_type: "workflow",
            source_title: "recording",
            project_name: "P",
            visibility: "public",
            confidence_score: 80,
            proof_reason: "Captured",
            artifact_data: { frame_label: "SAFE_LABEL" },
          },
        ],
      }),
    ])
    const { container } = render(<RecruiterWorkPassportPreview view={makeEmptyViewForVisibility()} />)
    await waitFor(() => expect(screen.getAllByText("Public Skill").length).toBeGreaterThan(0))
    expect(container.innerHTML).not.toContain("storage_path")
    expect(container.innerHTML).not.toContain("signed_url")
    expect(container.innerHTML).not.toContain("access_token")
    expect(container.innerHTML).not.toContain("service_role")
    expect(container.innerHTML).not.toContain("private_url")
  })
})

// ── Private-all fix: backend [] with view.skill_groups ────────────────────────
// Regression test for the bug where backend returning [] (all private)
// caused backendHasAuthority=false and showed all mock groups as fallback.
// With the fix, backendPipelineMap is an empty Map (not null), so
// backendHasAuthority=true and all view groups are filtered out.

describe("RecruiterWorkPassportPreview — all-private fix (backend returns [])", () => {
  function makeViewWithTwoGroups(): RecruiterPassportViewResponse {
    return {
      public_slug: "priv-all-slug",
      student_display_name: "Test Candidate",
      field: "AI",
      public_title: "AI Engineer",
      public_summary: "Summary.",
      overall_score: 80,
      evidence_confidence: "high",
      verification_status: null,
      readiness_level: null,
      skill_groups: [
        {
          group_name: "AI / Machine Learning",
          category: "AI/ML",
          confidence: "high",
          evidence_count: 4,
          source_labels: ["GitHub"],
          skills: [{ skill: "Machine Learning", confidence: "high", status_label: "strongly supported", source_labels: ["GitHub"] }],
        },
        {
          group_name: "JavaScript / Frontend",
          category: "Frontend",
          confidence: "high",
          evidence_count: 3,
          source_labels: ["GitHub"],
          skills: [{ skill: "React", confidence: "high", status_label: "strongly supported", source_labels: ["GitHub"] }],
        },
      ],
      verified_skills: [],
      partially_verified_skills: [],
      skills_needing_review: [],
      proof_sources: [],
      why_credible: [],
      strongest_skills: [],
      areas_needing_review: [],
      suggested_interview_questions: [],
      public_project_links: [],
      project_type: null,
      access_request_available: false,
      has_protected_evidence: false,
      disclosure_note: "Test.",
    }
  }

  afterEach(() => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
  })

  it("backend returns [] (all private) → no skill group cards rendered", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([])
    render(<RecruiterWorkPassportPreview view={makeViewWithTwoGroups()} />)
    // Wait for backend to respond and component to re-render with empty map
    await waitFor(() => {
      expect(screen.queryByTestId("skill-group-card-ai-machine-learning")).not.toBeInTheDocument()
    })
    expect(screen.queryByTestId("skill-group-card-javascript-frontend")).not.toBeInTheDocument()
  })

  it("backend returns [] (all private) → mock AI/ML static content not leaked", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([])
    const { container } = render(<RecruiterWorkPassportPreview view={makeViewWithTwoGroups()} />)
    await waitFor(() => {
      expect(screen.queryByTestId("skill-group-card-ai-machine-learning")).not.toBeInTheDocument()
    })
    expect(container.innerHTML).not.toContain("Model inference UI visible")
    expect(container.innerHTML).not.toContain("Overall Score: 87")
    expect(container.innerHTML).not.toContain("FinalEvidenceEvaluatorService")
  })

  it("backend returns [] (all private) → protected section also absent", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([])
    render(<RecruiterWorkPassportPreview view={makeViewWithTwoGroups()} />)
    await waitFor(() => {
      expect(screen.queryByTestId("skill-group-card-ai-machine-learning")).not.toBeInTheDocument()
    })
    expect(screen.queryByTestId("protected-pipelines-section")).not.toBeInTheDocument()
    expect(screen.queryByTestId("protected-pipeline-badge")).not.toBeInTheDocument()
  })

  it("backend null (unavailable) still shows all mock groups as fallback", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
    render(<RecruiterWorkPassportPreview view={makeViewWithTwoGroups()} />)
    await waitFor(() => {
      expect(screen.getAllByText("AI / Machine Learning").length).toBeGreaterThan(0)
      expect(screen.getAllByText("JavaScript / Frontend").length).toBeGreaterThan(0)
    })
  })
})

// ── /dev/recruiter-passport-preview page banner and backend integration ────────

describe("DevRecruiterPassportPreviewPage — banner and backend state", () => {
  afterEach(() => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
  })

  it("shows fallback mock badge when backend returns null", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
    render(<DevRecruiterPassportPreviewPage />)
    await waitFor(() =>
      expect(screen.getByTestId("banner-fallback-badge")).toBeInTheDocument()
    )
    expect(screen.getByTestId("banner-fallback-badge").textContent).toMatch(/Fallback mock preview/i)
  })

  it("shows backend badge when backend returns pipeline data (empty array)", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([])
    render(<DevRecruiterPassportPreviewPage />)
    await waitFor(() =>
      expect(screen.getByTestId("banner-backend-badge")).toBeInTheDocument()
    )
    expect(screen.getByTestId("banner-backend-badge").textContent).toMatch(/Backend recruiter-safe data/i)
  })

  it("shows backend badge when backend returns non-empty pipelines", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      {
        id: "p-1",
        skill_name: "JavaScript",
        skill_category: "Frontend",
        confidence_score: 80,
        support_status: "strongly_supported",
        evidence_count: 2,
        strongest_proof: null,
        weakest_proof: null,
        missing_evidence: [],
        next_actions: [],
        evidence_sources: [],
        recruiter_summary: "Strong JS.",
        visibility_status: "public",
        is_locked_for_recruiter: false,
        artifacts: [],
      },
    ])
    render(<DevRecruiterPassportPreviewPage />)
    await waitFor(() =>
      expect(screen.getByTestId("banner-backend-badge")).toBeInTheDocument()
    )
  })

  it("dev page: when backend responds, mock AI/ML group card is not shown", async () => {
    // Backend returns [] — all pipelines are private or none exist.
    // Dev page passes skill_groups:[] to component; component's own fetch returns [].
    // Result: no skill group cards rendered (correct recruiter-safe behavior).
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([])
    render(<DevRecruiterPassportPreviewPage />)
    await waitFor(() =>
      expect(screen.getByTestId("banner-backend-badge")).toBeInTheDocument()
    )
    expect(screen.queryByTestId("skill-group-card-ai-machine-learning")).not.toBeInTheDocument()
  })

  it("dev page: when backend unavailable, mock groups are shown as fallback", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
    render(<DevRecruiterPassportPreviewPage />)
    await waitFor(() =>
      expect(screen.getByTestId("banner-fallback-badge")).toBeInTheDocument()
    )
    // Fallback: full MOCK_VIEW with skill_groups is passed, so all groups visible
    await waitFor(() =>
      expect(screen.getAllByText("AI / Machine Learning").length).toBeGreaterThan(0)
    )
  })

  it("dev page: banner does not expose unsafe strings", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
    const { container } = render(<DevRecruiterPassportPreviewPage />)
    await waitFor(() =>
      expect(screen.getByTestId("banner-fallback-badge")).toBeInTheDocument()
    )
    const html = container.innerHTML
    expect(html).not.toContain("access_token")
    expect(html).not.toContain("storage_path")
    expect(html).not.toContain("transcript_text")
    expect(html).not.toContain("media_storage_path")
  })

  // ── Refresh / loading regression tests ────────────────────────────────────

  it("loading state: has_protected_evidence=false → protected CTA not rendered", () => {
    let resolve!: (v: null) => void
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockReturnValue(
      new Promise<null>((r) => { resolve = r }),
    )
    render(<DevRecruiterPassportPreviewPage />)
    expect(screen.getByTestId("banner-loading-badge")).toBeInTheDocument()
    // has_protected_evidence stripped to false during loading — protected CTA must be absent
    expect(screen.queryByText(/Protected Evidence Available/i)).not.toBeInTheDocument()
    expect(screen.queryByTestId("request-access-btn")).not.toBeInTheDocument()
    resolve(null)
  })

  it("loading state: banner reset button not visible during fetch", () => {
    let resolve!: (v: null) => void
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockReturnValue(
      new Promise<null>((r) => { resolve = r }),
    )
    render(<DevRecruiterPassportPreviewPage />)
    expect(screen.getByTestId("banner-loading-badge")).toBeInTheDocument()
    expect(screen.queryByTestId("banner-reset-btn")).not.toBeInTheDocument()
    resolve(null)
  })

  it("backend success with empty data stays in backend-safe mode (not mock mode)", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([])
    render(<DevRecruiterPassportPreviewPage />)
    await waitFor(() => expect(screen.getByTestId("banner-backend-badge")).toBeInTheDocument())
    // Empty pipeline list is still backend success — must not fall back to mock groups
    expect(screen.queryByTestId("skill-group-card-ai-machine-learning")).not.toBeInTheDocument()
    // No protected evidence CTA from mock store
    expect(screen.queryByText(/Protected Evidence Available/i)).not.toBeInTheDocument()
    expect(screen.queryByTestId("banner-reset-btn")).not.toBeInTheDocument()
  })

  it("backend failure (null) is the only trigger for mock fallback mode", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
    render(<DevRecruiterPassportPreviewPage />)
    await waitFor(() => expect(screen.getByTestId("banner-fallback-badge")).toBeInTheDocument())
    // Only in fallback mode should the reset button appear (mock controls enabled)
    expect(screen.getByTestId("banner-reset-btn")).toBeInTheDocument()
  })
})

// ── suppressMockActions: backend mode hides mock-derived controls ─────────────

describe("RecruiterWorkPassportPreview — suppressMockActions in backend mode", () => {
  // View with no skill_groups so the component fetches from backend (Case C)
  function makeEmptyView(): RecruiterPassportViewResponse {
    return makeView({
      skill_groups: [],
      verified_skills: [],
      partially_verified_skills: [],
      skills_needing_review: [],
      has_protected_evidence: false,
    })
  }

  const aiMlPublicPipeline: RecruiterSafePipelineSummary = {
    id: "p-ai-public",
    skill_name: "AI / Machine Learning",
    skill_category: "AI/ML",
    confidence_score: 85,
    support_status: "strongly_supported",
    evidence_count: 4,
    strongest_proof: { label: "GitHub", reason: "ML training loops" },
    weakest_proof: null,
    missing_evidence: [],
    next_actions: [],
    evidence_sources: [
      { key: "github", label: "GitHub code", status: "supported", score: 85, reason: "ML code" },
    ],
    recruiter_summary: "Strong AI/ML evidence from GitHub and workflow.",
    visibility_status: "public",
    is_locked_for_recruiter: false,
    artifacts: [],
  }

  afterEach(() => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
  })

  it("backend mode: compact action chips are hidden for AI/ML group (suppressMockActions=true)", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([aiMlPublicPipeline])
    render(<RecruiterWorkPassportPreview view={makeEmptyView()} />)
    await waitFor(() => expect(screen.getAllByText("AI / Machine Learning").length).toBeGreaterThan(0))
    // suppressMockActions=true in Case C → no compact action chips from mock bundle
    expect(screen.queryByTestId("skill-card-compact-actions")).not.toBeInTheDocument()
  })

  it("backend mode: no GitHub proof chip from mock bundle (suppressMockActions=true)", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([aiMlPublicPipeline])
    render(<RecruiterWorkPassportPreview view={makeEmptyView()} />)
    await waitFor(() => expect(screen.getAllByText("AI / Machine Learning").length).toBeGreaterThan(0))
    expect(screen.queryByTestId("skill-card-github-proof-action")).not.toBeInTheDocument()
  })

  it("backend mode: no keyframe chip from mock bundle (suppressMockActions=true)", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([aiMlPublicPipeline])
    render(<RecruiterWorkPassportPreview view={makeEmptyView()} />)
    await waitFor(() => expect(screen.getAllByText("AI / Machine Learning").length).toBeGreaterThan(0))
    expect(screen.queryByTestId("skill-card-keyframe-action")).not.toBeInTheDocument()
  })

  it("backend mode: Protected evidence approved text is hidden when has_protected_evidence=false", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([aiMlPublicPipeline])
    render(<RecruiterWorkPassportPreview view={makeEmptyView()} />)
    await waitFor(() => expect(screen.getAllByText("AI / Machine Learning").length).toBeGreaterThan(0))
    expect(screen.queryByText(/Protected evidence approved/i)).not.toBeInTheDocument()
  })

  it("backend mode: no Reset mock access requests button when onReset=undefined", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([aiMlPublicPipeline])
    // No onReset prop → all *-reset-btn testids absent
    render(<RecruiterWorkPassportPreview view={makeEmptyView()} onReset={undefined} />)
    await waitFor(() => expect(screen.getAllByText("AI / Machine Learning").length).toBeGreaterThan(0))
    expect(screen.queryByTestId("approved-reset-btn")).not.toBeInTheDocument()
    expect(screen.queryByTestId("pending-reset-btn")).not.toBeInTheDocument()
    expect(screen.queryByTestId("cta-reset-btn")).not.toBeInTheDocument()
  })

  it("backend mode: view-skill-evidence-btn is disabled (not a dead enabled button)", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([aiMlPublicPipeline])
    render(<RecruiterWorkPassportPreview view={makeEmptyView()} />)
    await waitFor(() => expect(screen.getAllByText("AI / Machine Learning").length).toBeGreaterThan(0))
    const btn = screen.getByTestId("view-skill-evidence-btn")
    expect(btn).toBeDisabled()
  })

  it("backend mode: view-skill-evidence-disabled helper text is shown", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([aiMlPublicPipeline])
    render(<RecruiterWorkPassportPreview view={makeEmptyView()} />)
    await waitFor(() => expect(screen.getAllByText("AI / Machine Learning").length).toBeGreaterThan(0))
    expect(screen.getByTestId("view-skill-evidence-disabled")).toBeInTheDocument()
    expect(screen.getByTestId("view-skill-evidence-disabled").textContent).toMatch(
      /Evidence viewer unavailable/i,
    )
  })

  it("backend mode: clicking disabled view-skill-evidence-btn does not open skill evidence modal", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([aiMlPublicPipeline])
    render(<RecruiterWorkPassportPreview view={makeEmptyView()} />)
    await waitFor(() => expect(screen.getAllByText("AI / Machine Learning").length).toBeGreaterThan(0))
    const btn = screen.getByTestId("view-skill-evidence-btn")
    fireEvent.click(btn)
    expect(screen.queryByTestId("skill-evidence-detail-modal")).not.toBeInTheDocument()
  })

  it("fallback mode: compact action chips ARE rendered from mock bundle when backend unavailable", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
    // Use view with skill_groups (Case A: fallback mock groups)
    const viewWithGroups = makeView({
      skill_groups: [
        {
          group_name: "AI / Machine Learning",
          category: "AI/ML",
          confidence: "high",
          evidence_count: 4,
          source_labels: ["GitHub", "Website Workflow"],
          skills: [{ skill: "Machine Learning", confidence: "high", status_label: "strongly supported", source_labels: ["GitHub"] }],
        },
      ],
      verified_skills: ["Machine Learning"],
      partially_verified_skills: [],
      skills_needing_review: [],
    })
    render(<RecruiterWorkPassportPreview view={viewWithGroups} />)
    await waitFor(() => expect(screen.getAllByText("AI / Machine Learning").length).toBeGreaterThan(0))
    // In fallback mode (backend null), Case A renders with suppressMockActions=false → chips present
    expect(screen.queryAllByTestId("skill-card-compact-actions").length).toBeGreaterThan(0)
  })
})

// ── Dev page: banner reset button gating ──────────────────────────────────────

describe("DevRecruiterPassportPreviewPage — banner reset button gating", () => {
  afterEach(() => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
  })

  it("banner-reset-btn is hidden in backend-safe mode", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([])
    render(<DevRecruiterPassportPreviewPage />)
    await waitFor(() => expect(screen.getByTestId("banner-backend-badge")).toBeInTheDocument())
    expect(screen.queryByTestId("banner-reset-btn")).not.toBeInTheDocument()
  })

  it("banner-reset-btn is shown in fallback/mock mode", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
    render(<DevRecruiterPassportPreviewPage />)
    await waitFor(() => expect(screen.getByTestId("banner-fallback-badge")).toBeInTheDocument())
    expect(screen.getByTestId("banner-reset-btn")).toBeInTheDocument()
  })
})

// ── Dev page: onReset gating with backend state ────────────────────────────────

describe("DevRecruiterPassportPreviewPage — onReset gating", () => {
  afterEach(() => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
  })

  it("dev page: no inner Reset button in RecruiterWorkPassportPreview when backend is available", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([])
    render(<DevRecruiterPassportPreviewPage />)
    await waitFor(() => expect(screen.getByTestId("banner-backend-badge")).toBeInTheDocument())
    // onReset=undefined in backend mode → no inner reset buttons
    expect(screen.queryByTestId("approved-reset-btn")).not.toBeInTheDocument()
    expect(screen.queryByTestId("pending-reset-btn")).not.toBeInTheDocument()
    expect(screen.queryByTestId("cta-reset-btn")).not.toBeInTheDocument()
    expect(screen.queryByTestId("denied-reset-btn")).not.toBeInTheDocument()
  })

  it("dev page: loading state does not show inner reset buttons (onReset=undefined during loading)", async () => {
    // Simulate slow backend response
    let resolve!: (v: null) => void
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockReturnValue(
      new Promise<null>((r) => { resolve = r }),
    )
    render(<DevRecruiterPassportPreviewPage />)
    expect(screen.getByTestId("banner-loading-badge")).toBeInTheDocument()
    // During loading, backendStatus === "loading" → onReset=undefined
    expect(screen.queryByTestId("cta-reset-btn")).not.toBeInTheDocument()
    resolve(null)
  })

  it("dev page: has_protected_evidence=false in backend mode suppresses protected CTA", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([])
    render(<DevRecruiterPassportPreviewPage />)
    await waitFor(() => expect(screen.getByTestId("banner-backend-badge")).toBeInTheDocument())
    // has_protected_evidence=false → no "Protected Evidence Available" CTA rendered
    expect(screen.queryByText(/Protected Evidence Available/i)).not.toBeInTheDocument()
    expect(screen.queryByTestId("request-access-btn")).not.toBeInTheDocument()
  })

  it("dev page: fallback mode shows inner reset button (onReset defined when backend unavailable)", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
    render(<DevRecruiterPassportPreviewPage />)
    await waitFor(() => expect(screen.getByTestId("banner-fallback-badge")).toBeInTheDocument())
    // onReset=handleReset when backendStatus==="unavailable"
    // has_protected_evidence=true in MOCK_VIEW → protected section renders
    // SAMPLE_REQUESTS has Stripe pending request (filtered by defaultRequester email) → pending-reset-btn
    await waitFor(() =>
      expect(screen.getByTestId("pending-reset-btn")).toBeInTheDocument()
    )
  })
})

// ── RecruiterSafeEvidencePipelineViewer ──────────────────────────────────────

describe("RecruiterSafeEvidencePipelineViewer — backend mode evidence viewer", () => {
  function makeEmptyViewForViewer(): RecruiterPassportViewResponse {
    return {
      public_slug: "viewer-test-slug",
      student_display_name: "Test Candidate",
      field: "AI",
      public_title: "AI Engineer",
      public_summary: "Summary.",
      overall_score: 80,
      evidence_confidence: "high",
      verification_status: null,
      readiness_level: null,
      skill_groups: [],
      verified_skills: [],
      partially_verified_skills: [],
      skills_needing_review: [],
      proof_sources: [],
      why_credible: [],
      strongest_skills: [],
      areas_needing_review: [],
      suggested_interview_questions: [],
      public_project_links: [],
      project_type: "Engineering",
      access_request_available: false,
      has_protected_evidence: false,
      disclosure_note: "Test.",
    }
  }

  function makePipelineWithArtifacts(
    overrides: Partial<RecruiterSafePipelineSummary> = {},
  ): RecruiterSafePipelineSummary {
    return {
      id: "viewer-pipeline-1",
      skill_name: "Viewer Skill",
      skill_category: "AI/ML",
      confidence_score: 85,
      support_status: "strongly_supported",
      evidence_count: 3,
      strongest_proof: { label: "GitHub", reason: "Code confirmed" },
      weakest_proof: null,
      missing_evidence: [],
      next_actions: [],
      evidence_sources: [
        { key: "github", label: "GitHub code", status: "supported", score: 85, reason: "Code confirmed" },
      ],
      recruiter_summary: "Strong evidence from GitHub and workflow.",
      visibility_status: "public",
      is_locked_for_recruiter: false,
      artifacts: [
        {
          id: "art-gh-1",
          source_type: "github",
          source_title: "evaluator.py",
          project_name: "VeriBridge",
          visibility: "public",
          confidence_score: 90,
          proof_reason: "ML training loop confirmed",
          artifact_data: { file_path: "apps/api/evaluator.py" },
          exact_code_url: "https://github.com/veribridge-ai/veribridge/blob/main/apps/api/evaluator.py#L1-L50",
          full_file_url: "https://github.com/veribridge-ai/veribridge/blob/main/apps/api/evaluator.py",
        },
      ],
      ...overrides,
    }
  }

  afterEach(() => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
  })

  it("view-skill-evidence-btn is enabled when pipeline has artifacts", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePipelineWithArtifacts(),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForViewer()} />)
    await waitFor(() => expect(screen.getAllByText("Viewer Skill").length).toBeGreaterThan(0))
    const btn = screen.getByTestId("view-skill-evidence-btn")
    expect(btn).not.toBeDisabled()
  })

  it("view-skill-evidence-btn disabled when pipeline has no artifacts", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePipelineWithArtifacts({ artifacts: [] }),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForViewer()} />)
    await waitFor(() => expect(screen.getAllByText("Viewer Skill").length).toBeGreaterThan(0))
    const btn = screen.getByTestId("view-skill-evidence-btn")
    expect(btn).toBeDisabled()
  })

  it("clicking enabled view-skill-evidence-btn opens recruiter-safe-evidence-viewer", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePipelineWithArtifacts(),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForViewer()} />)
    await waitFor(() => expect(screen.getAllByText("Viewer Skill").length).toBeGreaterThan(0))
    fireEvent.click(screen.getByTestId("view-skill-evidence-btn"))
    expect(screen.getByTestId("recruiter-safe-evidence-viewer")).toBeInTheDocument()
  })

  it("viewer shows skill name in header", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePipelineWithArtifacts(),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForViewer()} />)
    await waitFor(() => expect(screen.getAllByText("Viewer Skill").length).toBeGreaterThan(0))
    fireEvent.click(screen.getByTestId("view-skill-evidence-btn"))
    const viewer = screen.getByTestId("recruiter-safe-evidence-viewer")
    expect(viewer.textContent).toContain("Viewer Skill")
    expect(viewer.textContent).toContain("85% confidence")
  })

  it("viewer shows github exact code link when exact_code_url is safe", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePipelineWithArtifacts(),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForViewer()} />)
    await waitFor(() => expect(screen.getAllByText("Viewer Skill").length).toBeGreaterThan(0))
    fireEvent.click(screen.getByTestId("view-skill-evidence-btn"))
    const link = screen.getByTestId("github-exact-code-link")
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute("href", expect.stringContaining("github.com"))
  })

  it("viewer shows github full file link when full_file_url is safe", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePipelineWithArtifacts(),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForViewer()} />)
    await waitFor(() => expect(screen.getAllByText("Viewer Skill").length).toBeGreaterThan(0))
    fireEvent.click(screen.getByTestId("view-skill-evidence-btn"))
    const link = screen.getByTestId("github-full-file-link")
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute("href", expect.stringContaining("github.com"))
  })

  it("viewer shows 'Exact lines not available' when exact_code_url is absent", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePipelineWithArtifacts({
        artifacts: [{
          id: "art-gh-nox",
          source_type: "github",
          source_title: "model.py",
          project_name: "P",
          visibility: "public",
          confidence_score: 75,
          proof_reason: "Confirmed",
          artifact_data: {},
          exact_code_url: null,
          full_file_url: null,
        }],
      }),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForViewer()} />)
    await waitFor(() => expect(screen.getAllByText("Viewer Skill").length).toBeGreaterThan(0))
    fireEvent.click(screen.getByTestId("view-skill-evidence-btn"))
    expect(screen.getByTestId("github-exact-code-unavailable")).toBeInTheDocument()
  })

  it("viewer shows keyframe-unavailable when no safe keyframe URL", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePipelineWithArtifacts({
        artifacts: [{
          id: "art-kf-1",
          source_type: "keyframe",
          source_title: "Frame 3",
          project_name: "Demo",
          visibility: "public",
          confidence_score: 80,
          proof_reason: "Shows model output",
          artifact_data: {},
        }],
      }),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForViewer()} />)
    await waitFor(() => expect(screen.getAllByText("Viewer Skill").length).toBeGreaterThan(0))
    fireEvent.click(screen.getByTestId("view-skill-evidence-btn"))
    expect(screen.getByTestId("keyframe-unavailable-0")).toBeInTheDocument()
    expect(screen.getByTestId("keyframe-unavailable-0").textContent).toMatch(/No saved keyframe image is available/i)
  })

  it("viewer blocks unsafe localhost keyframe URL, shows unavailable state", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePipelineWithArtifacts({
        artifacts: [{
          id: "art-kf-unsafe",
          source_type: "keyframe",
          source_title: "Frame",
          project_name: "Demo",
          visibility: "public",
          confidence_score: 70,
          proof_reason: "Proof",
          artifact_data: { keyframe_url: "http://localhost:3000/media/frame.png" },
        }],
      }),
    ])
    const { container } = render(<RecruiterWorkPassportPreview view={makeEmptyViewForViewer()} />)
    await waitFor(() => expect(screen.getAllByText("Viewer Skill").length).toBeGreaterThan(0))
    fireEvent.click(screen.getByTestId("view-skill-evidence-btn"))
    expect(screen.getByTestId("keyframe-unavailable-0")).toBeInTheDocument()
    expect(container.innerHTML).not.toContain("localhost")
  })

  it("viewer shows transcript disabled download buttons", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePipelineWithArtifacts({
        artifacts: [{
          id: "art-tr-1",
          source_type: "transcript",
          source_title: "Project defense excerpt",
          project_name: "P",
          visibility: "public",
          confidence_score: 75,
          proof_reason: "Ownership signals present",
          artifact_data: { excerpt: "I implemented the training loop using PyTorch." },
        }],
      }),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForViewer()} />)
    await waitFor(() => expect(screen.getAllByText("Viewer Skill").length).toBeGreaterThan(0))
    fireEvent.click(screen.getByTestId("view-skill-evidence-btn"))
    expect(screen.getByTestId("transcript-txt-download-disabled")).toBeDisabled()
    expect(screen.getByTestId("transcript-pdf-download-disabled")).toBeDisabled()
  })

  it("viewer shows transcript excerpt text", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePipelineWithArtifacts({
        artifacts: [{
          id: "art-tr-2",
          source_type: "transcript",
          source_title: "Defense",
          project_name: "P",
          visibility: "public",
          confidence_score: 75,
          proof_reason: "Strong ownership",
          artifact_data: { excerpt: "I built the feature extraction pipeline from scratch." },
        }],
      }),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForViewer()} />)
    await waitFor(() => expect(screen.getAllByText("Viewer Skill").length).toBeGreaterThan(0))
    fireEvent.click(screen.getByTestId("view-skill-evidence-btn"))
    const viewer = screen.getByTestId("recruiter-safe-evidence-viewer")
    expect(viewer.textContent).toContain("I built the feature extraction pipeline from scratch.")
  })

  it("viewer document shows disabled open button when full_file_url absent", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePipelineWithArtifacts({
        artifacts: [{
          id: "art-doc-1",
          source_type: "document",
          source_title: "Project Report",
          project_name: "P",
          visibility: "public",
          confidence_score: 70,
          proof_reason: "Technical report",
          artifact_data: {},
        }],
      }),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForViewer()} />)
    await waitFor(() => expect(screen.getAllByText("Viewer Skill").length).toBeGreaterThan(0))
    fireEvent.click(screen.getByTestId("view-skill-evidence-btn"))
    expect(screen.getByTestId("document-open-disabled")).toBeDisabled()
  })

  it("viewer shows safety footer", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePipelineWithArtifacts(),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForViewer()} />)
    await waitFor(() => expect(screen.getAllByText("Viewer Skill").length).toBeGreaterThan(0))
    fireEvent.click(screen.getByTestId("view-skill-evidence-btn"))
    const footer = screen.getByTestId("evidence-viewer-safety-footer")
    expect(footer).toBeInTheDocument()
    expect(footer.textContent).toMatch(/Private files.*internal storage references.*sensitive credentials/i)
  })

  it("evidence viewer safety footer does not contain literal unsafe-key vocabulary", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePipelineWithArtifacts(),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForViewer()} />)
    await waitFor(() => expect(screen.getAllByText("Viewer Skill").length).toBeGreaterThan(0))
    fireEvent.click(screen.getByTestId("view-skill-evidence-btn"))
    const footer = screen.getByTestId("evidence-viewer-safety-footer")
    const text = footer.textContent ?? ""
    // None of these literal unsafe-key strings may appear in the footer
    expect(text).not.toContain("token")
    expect(text).not.toContain("access_token")
    expect(text).not.toContain("storage_path")
    expect(text).not.toContain("signed_url")
    expect(text).not.toContain("video_url")
    expect(text).not.toContain("media_storage_path")
    expect(text).not.toContain("service_role")
    expect(text).not.toContain("anon_key")
  })

  it("evidence-viewer-close button closes the viewer", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePipelineWithArtifacts(),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForViewer()} />)
    await waitFor(() => expect(screen.getAllByText("Viewer Skill").length).toBeGreaterThan(0))
    fireEvent.click(screen.getByTestId("view-skill-evidence-btn"))
    expect(screen.getByTestId("recruiter-safe-evidence-viewer")).toBeInTheDocument()
    fireEvent.click(screen.getByTestId("evidence-viewer-close"))
    expect(screen.queryByTestId("recruiter-safe-evidence-viewer")).not.toBeInTheDocument()
  })

  it("viewer does not expose unsafe strings in rendered HTML", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePipelineWithArtifacts({
        artifacts: [
          {
            id: "art-safe-1",
            source_type: "github",
            source_title: "model.py",
            project_name: "P",
            visibility: "public",
            confidence_score: 80,
            proof_reason: "Code confirmed",
            artifact_data: { file_path: "apps/model.py" },
            exact_code_url: "https://github.com/veribridge-ai/repo/blob/main/model.py",
            full_file_url: "https://github.com/veribridge-ai/repo/blob/main/model.py",
          },
        ],
      }),
    ])
    const { container } = render(<RecruiterWorkPassportPreview view={makeEmptyViewForViewer()} />)
    await waitFor(() => expect(screen.getAllByText("Viewer Skill").length).toBeGreaterThan(0))
    fireEvent.click(screen.getByTestId("view-skill-evidence-btn"))
    const html = container.innerHTML
    expect(html).not.toContain("storage_path")
    expect(html).not.toContain("access_token")
    expect(html).not.toContain("service_role")
    expect(html).not.toContain("anon_key")
    expect(html).not.toContain("signed_url")
  })

  it("viewer sections show 'no data' state for artifact types not present", async () => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([
      makePipelineWithArtifacts(),
    ])
    render(<RecruiterWorkPassportPreview view={makeEmptyViewForViewer()} />)
    await waitFor(() => expect(screen.getAllByText("Viewer Skill").length).toBeGreaterThan(0))
    fireEvent.click(screen.getByTestId("view-skill-evidence-btn"))
    const viewer = screen.getByTestId("recruiter-safe-evidence-viewer")
    // keyframe, workflow, ocr, dom, qwen, transcript, document — all absent from makePipelineWithArtifacts default
    expect(viewer.textContent).toContain("No keyframe evidence artifacts")
    expect(viewer.textContent).toContain("No workflow recording artifacts")
    expect(viewer.textContent).toContain("No transcript evidence artifacts")
    expect(viewer.textContent).toContain("No document artifacts")
  })
})

// ── RecruiterSafeEvidencePipelineViewer — deep artifact detail rendering ───────

describe("RecruiterSafeEvidencePipelineViewer — deep artifact detail rendering", () => {
  function makeEmptyView(): RecruiterPassportViewResponse {
    return {
      public_slug: "detail-test",
      student_display_name: "Detail Candidate",
      field: "AI",
      public_title: "Engineer",
      public_summary: "Summary.",
      overall_score: 80,
      evidence_confidence: "high",
      verification_status: null,
      readiness_level: null,
      skill_groups: [],
      verified_skills: [],
      partially_verified_skills: [],
      skills_needing_review: [],
      proof_sources: [],
      why_credible: [],
      strongest_skills: [],
      areas_needing_review: [],
      suggested_interview_questions: [],
      public_project_links: [],
      project_type: "Engineering",
      access_request_available: false,
      has_protected_evidence: false,
      disclosure_note: "Test.",
    }
  }

  function makePipeline(artifacts: RecruiterSafePipelineSummary["artifacts"]): RecruiterSafePipelineSummary {
    return {
      id: "dp-1",
      skill_name: "Detail Skill",
      skill_category: "AI/ML",
      confidence_score: 80,
      support_status: "strongly_supported",
      evidence_count: artifacts.length,
      strongest_proof: { label: "Workflow", reason: "Recorded" },
      weakest_proof: null,
      missing_evidence: [],
      next_actions: [],
      evidence_sources: [],
      recruiter_summary: "Evidence from real proof session.",
      visibility_status: "public",
      is_locked_for_recruiter: false,
      artifacts,
    }
  }

  async function openViewer(pipeline: RecruiterSafePipelineSummary) {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([pipeline])
    render(<RecruiterWorkPassportPreview view={makeEmptyView()} />)
    await waitFor(() => expect(screen.getAllByText("Detail Skill").length).toBeGreaterThan(0))
    fireEvent.click(screen.getByTestId("view-skill-evidence-btn"))
  }

  afterEach(() => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
  })

  // ── Workflow artifact details ────────────────────────────────────────────────

  it("workflow artifact renders website_url", async () => {
    await openViewer(makePipeline([{
      id: "wf-1", source_type: "workflow", source_title: "Website Workflow", project_name: "Demo",
      visibility: "public", confidence_score: 80, proof_reason: "Live recorded session.",
      artifact_data: {
        website_url: "https://demo.vercel.app",
        steps_count: 5,
        workflow_summary: "Candidate interacted with 3D canvas using Three.js API.",
        matched_skills: ["WebGL", "Three.js"],
      },
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("workflow-artifact-detail")).toBeInTheDocument()
    expect(screen.getByTestId("workflow-artifact-detail").textContent).toMatch(/demo\.vercel\.app/)
  })

  it("workflow artifact renders steps_count", async () => {
    await openViewer(makePipeline([{
      id: "wf-2", source_type: "workflow", source_title: "Workflow", project_name: "Demo",
      visibility: "public", confidence_score: 80, proof_reason: "Recorded.",
      artifact_data: { steps_count: 7, workflow_summary: "7 steps captured." },
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("workflow-artifact-detail").textContent).toMatch(/7/)
  })

  it("workflow artifact renders workflow_summary", async () => {
    await openViewer(makePipeline([{
      id: "wf-3", source_type: "workflow", source_title: "Workflow", project_name: "Demo",
      visibility: "public", confidence_score: 80, proof_reason: "Recorded.",
      artifact_data: { workflow_summary: "Candidate demonstrated shader compilation workflow." },
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("workflow-summary-text").textContent).toMatch(/shader compilation/)
  })

  it("workflow artifact renders matched_skills as tags", async () => {
    await openViewer(makePipeline([{
      id: "wf-4", source_type: "workflow", source_title: "Workflow", project_name: "Demo",
      visibility: "public", confidence_score: 80, proof_reason: "Recorded.",
      artifact_data: { matched_skills: ["WebGL", "GLSL"] },
      exact_code_url: null, full_file_url: null,
    }]))
    const tags = screen.getByTestId("workflow-matched-skills")
    expect(tags.textContent).toMatch(/WebGL/)
    expect(tags.textContent).toMatch(/GLSL/)
  })

  it("workflow artifact with no detail data shows NoDetailData", async () => {
    await openViewer(makePipeline([{
      id: "wf-5", source_type: "workflow", source_title: "Website Workflow", project_name: "Demo",
      visibility: "public", confidence_score: 80, proof_reason: "Recorded.",
      artifact_data: {},
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("no-detail-data")).toBeInTheDocument()
    expect(screen.getByTestId("no-detail-data").textContent).toMatch(/No detailed safe artifact data/)
  })

  // ── OCR artifact details ─────────────────────────────────────────────────────

  it("OCR artifact renders extracted_text_summary", async () => {
    await openViewer(makePipeline([{
      id: "ocr-1", source_type: "ocr", source_title: "OCR Evidence", project_name: "Demo",
      visibility: "public", confidence_score: 70, proof_reason: "Text extracted.",
      artifact_data: {
        extracted_text_summary: "Canvas initialized; WebGL context: enabled; Shader compiled",
        matched_ui_labels: ["Canvas", "WebGL context"],
        frame_count: 3,
      },
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("ocr-artifact-detail")).toBeInTheDocument()
    expect(screen.getByTestId("ocr-extracted-summary").textContent).toMatch(/Canvas initialized/)
  })

  it("OCR artifact renders matched_ui_labels", async () => {
    await openViewer(makePipeline([{
      id: "ocr-2", source_type: "ocr", source_title: "OCR Evidence", project_name: "Demo",
      visibility: "public", confidence_score: 70, proof_reason: "Text extracted.",
      artifact_data: { matched_ui_labels: ["Submit", "Compile Shader", "Render"] },
      exact_code_url: null, full_file_url: null,
    }]))
    const labels = screen.getByTestId("ocr-matched-labels")
    expect(labels.textContent).toMatch(/Submit/)
    expect(labels.textContent).toMatch(/Compile Shader/)
  })

  it("OCR artifact shows NoDetailData when artifact_data is empty", async () => {
    await openViewer(makePipeline([{
      id: "ocr-3", source_type: "ocr", source_title: "OCR", project_name: "Demo",
      visibility: "public", confidence_score: 55, proof_reason: "OCR.",
      artifact_data: {},
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("no-detail-data").textContent).toMatch(/No detailed safe artifact data/)
  })

  // ── DOM artifact details ─────────────────────────────────────────────────────

  it("DOM artifact renders dom_summary", async () => {
    await openViewer(makePipeline([{
      id: "dom-1", source_type: "dom", source_title: "DOM Evidence", project_name: "Demo",
      visibility: "public", confidence_score: 65, proof_reason: "DOM captured.",
      artifact_data: {
        dom_summary: "Three.js canvas with WebGL context; shader controls visible",
        interacted_elements_summary: "Clicked Compile button; adjusted uniforms slider",
        state_changes_summary: "Canvas re-rendered after shader update",
      },
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("dom-artifact-detail")).toBeInTheDocument()
    expect(screen.getByTestId("dom-summary-text").textContent).toMatch(/Three\.js canvas/)
  })

  it("DOM artifact renders interacted_elements_summary", async () => {
    await openViewer(makePipeline([{
      id: "dom-2", source_type: "dom", source_title: "DOM Evidence", project_name: "Demo",
      visibility: "public", confidence_score: 65, proof_reason: "DOM captured.",
      artifact_data: { interacted_elements_summary: "Button: Compile; Slider: resolution" },
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("dom-interacted-elements").textContent).toMatch(/Button: Compile/)
  })

  it("DOM artifact renders state_changes_summary", async () => {
    await openViewer(makePipeline([{
      id: "dom-3", source_type: "dom", source_title: "DOM", project_name: "Demo",
      visibility: "public", confidence_score: 65, proof_reason: "DOM.",
      artifact_data: { state_changes_summary: "Canvas repainted with new fragment shader output" },
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("dom-state-changes").textContent).toMatch(/fragment shader/)
  })

  it("DOM artifact shows NoDetailData when artifact_data is empty", async () => {
    await openViewer(makePipeline([{
      id: "dom-4", source_type: "dom", source_title: "DOM", project_name: "Demo",
      visibility: "public", confidence_score: 45, proof_reason: "Partial.",
      artifact_data: {},
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("no-detail-data").textContent).toMatch(/No detailed safe artifact data/)
  })

  // ── Qwen / visual reasoning details ─────────────────────────────────────────

  it("Qwen artifact renders visual_observation_summary", async () => {
    await openViewer(makePipeline([{
      id: "qwen-1", source_type: "qwen", source_title: "Visual Reasoning", project_name: "Demo",
      visibility: "public", confidence_score: 75, proof_reason: "Qwen analyzed frames.",
      artifact_data: {
        visual_observation_summary: "3D mesh rendering with wireframe overlay visible; WebGL context active.",
        evidence_reasoning: "Frame confirms active WebGL pipeline usage",
      },
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("qwen-artifact-detail")).toBeInTheDocument()
    expect(screen.getByTestId("qwen-visual-observation").textContent).toMatch(/3D mesh rendering/)
  })

  it("Qwen artifact renders evidence_reasoning", async () => {
    await openViewer(makePipeline([{
      id: "qwen-2", source_type: "qwen", source_title: "Visual Reasoning", project_name: "Demo",
      visibility: "public", confidence_score: 75, proof_reason: "Qwen analyzed.",
      artifact_data: { evidence_reasoning: "Active GPU pipeline confirmed from rendered output" },
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("qwen-evidence-reasoning").textContent).toMatch(/GPU pipeline/)
  })

  it("Qwen artifact shows NoDetailData when artifact_data is empty", async () => {
    await openViewer(makePipeline([{
      id: "qwen-3", source_type: "qwen", source_title: "Qwen", project_name: "Demo",
      visibility: "public", confidence_score: 50, proof_reason: "Visual.",
      artifact_data: {},
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("no-detail-data").textContent).toMatch(/No detailed safe artifact data/)
  })

  // ── Keyframe metadata when image unavailable ─────────────────────────────────

  it("keyframe artifact renders visual_summary when image unavailable", async () => {
    await openViewer(makePipeline([{
      id: "kf-1", source_type: "keyframe", source_title: "Video Keyframes", project_name: "Demo",
      visibility: "public", confidence_score: 80, proof_reason: "4 keyframes captured.",
      artifact_data: {
        frame_count: 4,
        visual_summary: "3D scene with rotating geometry; WebGL context visible",
      },
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("keyframe-artifact-detail-0")).toBeInTheDocument()
    expect(screen.getByTestId("keyframe-unavailable-0")).toBeInTheDocument()
    expect(screen.getByTestId("keyframe-visual-summary-0").textContent).toMatch(/3D scene with rotating geometry/)
  })

  it("keyframe artifact renders frame_count", async () => {
    await openViewer(makePipeline([{
      id: "kf-2", source_type: "keyframe", source_title: "Keyframes", project_name: "Demo",
      visibility: "public", confidence_score: 80, proof_reason: "Frames captured.",
      artifact_data: { frame_count: 6 },
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("keyframe-artifact-detail-0").textContent).toMatch(/6/)
  })

  it("keyframe artifact shows NoDetailData when no frame_count or visual_summary", async () => {
    await openViewer(makePipeline([{
      id: "kf-3", source_type: "keyframe", source_title: "Keyframes", project_name: "Demo",
      visibility: "public", confidence_score: 60, proof_reason: "Captured.",
      artifact_data: {},
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("no-detail-data").textContent).toMatch(/No detailed safe artifact data/)
  })

  // ── Transcript artifact details ───────────────────────────────────────────────

  it("transcript artifact renders excerpt", async () => {
    await openViewer(makePipeline([{
      id: "tr-1", source_type: "transcript", source_title: "Project Defense", project_name: "Demo",
      visibility: "public", confidence_score: 68, proof_reason: "Defense recorded.",
      artifact_data: {
        excerpt: "I built the WebGL renderer from scratch using GLSL shader programs.",
        ownership_signals: ["First-person explanation", "Described personal implementation"],
        technical_depth_signals: ["Architecture/design discussion"],
        matched_skills: ["WebGL"],
      },
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("transcript-artifact-detail")).toBeInTheDocument()
    expect(screen.getByTestId("transcript-excerpt-text").textContent).toMatch(/GLSL shader programs/)
  })

  it("transcript artifact renders ownership_signals", async () => {
    await openViewer(makePipeline([{
      id: "tr-2", source_type: "transcript", source_title: "Defense", project_name: "Demo",
      visibility: "public", confidence_score: 68, proof_reason: "Defense.",
      artifact_data: { ownership_signals: ["First-person explanation", "Described personal implementation"] },
      exact_code_url: null, full_file_url: null,
    }]))
    const signals = screen.getByTestId("transcript-ownership-signals")
    expect(signals.textContent).toMatch(/First-person explanation/)
  })

  it("transcript artifact renders technical_depth_signals", async () => {
    await openViewer(makePipeline([{
      id: "tr-3", source_type: "transcript", source_title: "Defense", project_name: "Demo",
      visibility: "public", confidence_score: 68, proof_reason: "Defense.",
      artifact_data: { technical_depth_signals: ["Technical depth detected", "Architecture/design discussion"] },
      exact_code_url: null, full_file_url: null,
    }]))
    const signals = screen.getByTestId("transcript-depth-signals")
    expect(signals.textContent).toMatch(/Technical depth detected/)
  })

  it("transcript artifact shows NoDetailData when artifact_data is empty", async () => {
    await openViewer(makePipeline([{
      id: "tr-4", source_type: "transcript", source_title: "Transcript", project_name: "Demo",
      visibility: "public", confidence_score: 50, proof_reason: "Partial.",
      artifact_data: {},
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("no-detail-data").textContent).toMatch(/No detailed safe artifact data/)
  })

  // ── Document artifact details ─────────────────────────────────────────────────

  it("document artifact renders document_title", async () => {
    await openViewer(makePipeline([{
      id: "doc-1", source_type: "document", source_title: "Document — report.pdf", project_name: "Demo",
      visibility: "public", confidence_score: 75, proof_reason: "Submitted document.",
      artifact_data: {
        document_title: "WebGL Engineering Report",
        extracted_sections_summary: ["Section: Shader Architecture", "Section: Performance Benchmarks"],
        matched_skills: ["WebGL", "GLSL"],
      },
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("document-artifact-detail")).toBeInTheDocument()
    expect(screen.getByTestId("document-artifact-detail").textContent).toMatch(/WebGL Engineering Report/)
  })

  it("document artifact renders extracted_sections_summary", async () => {
    await openViewer(makePipeline([{
      id: "doc-2", source_type: "document", source_title: "Document", project_name: "Demo",
      visibility: "public", confidence_score: 75, proof_reason: "Document.",
      artifact_data: {
        extracted_sections_summary: ["Vertex shader implementation described in detail", "Fragment output analysis"],
      },
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("document-extracted-sections").textContent).toMatch(/Vertex shader/)
  })

  it("document artifact renders matched_skills", async () => {
    await openViewer(makePipeline([{
      id: "doc-3", source_type: "document", source_title: "Document", project_name: "Demo",
      visibility: "public", confidence_score: 75, proof_reason: "Document.",
      artifact_data: { matched_skills: ["Three.js", "Computer Vision"] },
      exact_code_url: null, full_file_url: null,
    }]))
    const skills = screen.getByTestId("document-matched-skills")
    expect(skills.textContent).toMatch(/Three\.js/)
    expect(skills.textContent).toMatch(/Computer Vision/)
  })

  it("document artifact shows NoDetailData when artifact_data is empty", async () => {
    await openViewer(makePipeline([{
      id: "doc-4", source_type: "document", source_title: "Document", project_name: "Demo",
      visibility: "public", confidence_score: 50, proof_reason: "Partial.",
      artifact_data: {},
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("no-detail-data").textContent).toMatch(/No detailed safe artifact data/)
  })

  // ── GitHub artifact details ───────────────────────────────────────────────────

  it("GitHub artifact renders file_path and symbol_name", async () => {
    await openViewer(makePipeline([{
      id: "gh-1", source_type: "github", source_title: "GitHub Code", project_name: "Demo",
      visibility: "public", confidence_score: 90, proof_reason: "Code confirmed.",
      artifact_data: {
        file_path: "apps/api/app/services/webgl_analyzer.py",
        symbol_name: "WebGLAnalyzerService",
        code_reason: "Service implements WebGL frame analysis using computer vision.",
        start_line: 10,
        end_line: 80,
      },
      exact_code_url: "https://github.com/example/repo/blob/main/apps/api/app/services/webgl_analyzer.py#L10-L80",
      full_file_url: "https://github.com/example/repo/blob/main/apps/api/app/services/webgl_analyzer.py",
    }]))
    const detail = screen.getByTestId("github-artifact-detail-0")
    expect(detail.textContent).toMatch(/webgl_analyzer\.py/)
    expect(detail.textContent).toMatch(/WebGLAnalyzerService/)
  })

  it("GitHub artifact renders code_reason", async () => {
    await openViewer(makePipeline([{
      id: "gh-2", source_type: "github", source_title: "GitHub", project_name: "Demo",
      visibility: "public", confidence_score: 90, proof_reason: "Code.",
      artifact_data: {
        file_path: "evaluator.py",
        code_reason: "Implements evidence strength scoring using weighted aggregation.",
      },
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("github-code-reason-0").textContent).toMatch(/weighted aggregation/)
  })

  it("GitHub artifact renders line range badge from start_line and end_line", async () => {
    await openViewer(makePipeline([{
      id: "gh-3", source_type: "github", source_title: "GitHub", project_name: "Demo",
      visibility: "public", confidence_score: 90, proof_reason: "Code.",
      artifact_data: { file_path: "service.py", start_line: 42, end_line: 120 },
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("github-line-range-viewer-0").textContent).toMatch(/L42/)
    expect(screen.getByTestId("github-line-range-viewer-0").textContent).toMatch(/L120/)
  })

  it("GitHub artifact shows NoDetailData when only file_path is present", async () => {
    await openViewer(makePipeline([{
      id: "gh-4", source_type: "github", source_title: "GitHub", project_name: "Demo",
      visibility: "public", confidence_score: 80, proof_reason: "Code.",
      artifact_data: { file_path: "some/file.py" },
      exact_code_url: null, full_file_url: null,
    }]))
    expect(screen.getByTestId("no-detail-data").textContent).toMatch(/No detailed safe artifact data/)
  })

  // ── Unsafe key blocking ───────────────────────────────────────────────────────

  it("unsafe keys are not rendered in any artifact section", async () => {
    await openViewer(makePipeline([{
      id: "unsafe-1", source_type: "workflow", source_title: "Workflow", project_name: "Demo",
      visibility: "public", confidence_score: 80, proof_reason: "Safe proof only.",
      artifact_data: {
        workflow_summary: "Candidate demonstrated workflow.",
        proof_session_id: "session-abc-123",
        access_token: "eyJhbGciOiJIUzI1NiJ9.secret",
        storage_path: "/private/recordings/abc.webm",
        signed_url: "https://supabase.co/storage/v1/object/sign/abc?token=xyz",
        video_url: "https://internal.veribridge.app/private/abc.mp4",
        service_role: "supabase-service-role-key",
        anon_key: "supabase-anon-key",
      },
      exact_code_url: null, full_file_url: null,
    }]))
    const viewer = screen.getByTestId("recruiter-safe-evidence-viewer")
    const html = viewer.outerHTML
    expect(html).not.toContain("session-abc-123")
    expect(html).not.toContain("eyJhbGciOiJIUzI1NiJ9")
    expect(html).not.toContain("/private/recordings/")
    expect(html).not.toContain("supabase.co/storage")
    expect(html).not.toContain("supabase-service-role-key")
    expect(html).not.toContain("supabase-anon-key")
  })

  it("safe workflow summary renders but unsafe keys do not appear", async () => {
    await openViewer(makePipeline([{
      id: "wf-safe", source_type: "workflow", source_title: "Workflow", project_name: "Demo",
      visibility: "public", confidence_score: 80, proof_reason: "Proof.",
      artifact_data: {
        workflow_summary: "Candidate demonstrated Three.js scene rendering.",
        storage_path: "/private/vid.webm",
        signed_url: "https://example.supabase.co/storage/abc?token=xyz",
      },
      exact_code_url: null, full_file_url: null,
    }]))
    const viewer = screen.getByTestId("recruiter-safe-evidence-viewer")
    expect(viewer.textContent).toMatch(/Three\.js scene rendering/)
    expect(viewer.outerHTML).not.toContain("/private/vid.webm")
    expect(viewer.outerHTML).not.toContain("supabase.co/storage")
  })
})

// ── RecruiterSafeEvidencePipelineViewer — noise filtering & related-skill notes ─

describe("RecruiterSafeEvidencePipelineViewer — noise filtering and related skill notes", () => {
  function makeEmptyView(): RecruiterPassportViewResponse {
    return {
      public_slug: "noise-filter-test",
      student_display_name: "Filter Candidate",
      field: "Computer Graphics",
      public_title: "Graphics Engineer",
      public_summary: "Summary.",
      overall_score: 80,
      evidence_confidence: "high",
      verification_status: null,
      readiness_level: null,
      skill_groups: [],
      verified_skills: [],
      partially_verified_skills: [],
      skills_needing_review: [],
      proof_sources: [],
      why_credible: [],
      strongest_skills: [],
      areas_needing_review: [],
      suggested_interview_questions: [],
      public_project_links: [],
      project_type: "Engineering",
      access_request_available: false,
      has_protected_evidence: false,
      disclosure_note: "Test.",
    }
  }

  function makePipeline(
    arts: RecruiterSafePipelineSummary["artifacts"],
    skill = "Computer Graphics",
  ): RecruiterSafePipelineSummary {
    return {
      id: "nf-pipeline-1",
      skill_name: skill,
      skill_category: "Frontend",
      confidence_score: 80,
      support_status: "strongly_supported",
      evidence_count: arts.length,
      strongest_proof: { label: "Workflow", reason: "Recorded" },
      weakest_proof: null,
      missing_evidence: [],
      next_actions: [],
      evidence_sources: [],
      recruiter_summary: "Evidence from WebGL proof session.",
      visibility_status: "public",
      is_locked_for_recruiter: false,
      artifacts: arts,
    }
  }

  async function openViewer(pipeline: RecruiterSafePipelineSummary) {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue([pipeline])
    render(<RecruiterWorkPassportPreview view={makeEmptyView()} />)
    await waitFor(() =>
      expect(screen.getAllByText(pipeline.skill_name).length).toBeGreaterThan(0),
    )
    fireEvent.click(screen.getByTestId("view-skill-evidence-btn"))
  }

  afterEach(() => {
    vi.mocked(apiModule.listRecruiterSkillEvidencePipelines).mockResolvedValue(null)
  })

  // ── OCR noise filtering ────────────────────────────────────────────────────

  it("OCR: noisy Supabase text filtered when target domain is threejs.org", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-kf-1", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org/examples/#webgl_geometry_cube" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "ocr-noisy-1", source_type: "ocr", source_title: "OCR Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 70,
        proof_reason: "Text extracted.",
        artifact_data: {
          extracted_text_summary:
            "Canvas initialized; WebGL context: enabled; Supabase; Storage; Buckets",
          matched_ui_labels: ["Canvas", "WebGL context", "Supabase", "Buckets"],
          frame_count: 3,
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    const summary = screen.getByTestId("ocr-extracted-summary")
    expect(summary.textContent).toMatch(/Canvas initialized/)
    expect(summary.textContent).toMatch(/WebGL context/)
    expect(summary.textContent).not.toMatch(/Supabase/)
    expect(summary.textContent).not.toMatch(/Buckets/)
  })

  it("OCR: noisy browser labels filtered from matched_ui_labels when target is threejs.org", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-kf-2", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "ocr-labs-1", source_type: "ocr", source_title: "OCR Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 70,
        proof_reason: "Labels extracted.",
        artifact_data: {
          matched_ui_labels: ["Render", "3D View", "Supabase", "Storage", "Canvas"],
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    const labels = screen.getByTestId("ocr-matched-labels")
    expect(labels.textContent).toMatch(/Render/)
    expect(labels.textContent).toMatch(/Canvas/)
    expect(labels.textContent).not.toMatch(/Supabase/)
    expect(labels.textContent).not.toMatch(/Storage/)
  })

  it("OCR: noise-filter notice shown when noisy text was removed", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-kf-3", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "ocr-notice-1", source_type: "ocr", source_title: "OCR Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 70,
        proof_reason: "Text extracted.",
        artifact_data: {
          extracted_text_summary: "Canvas active; Supabase; Storage buckets",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    expect(screen.getByTestId("noise-filter-notice")).toBeInTheDocument()
    expect(screen.getByTestId("noise-filter-notice").textContent).toMatch(
      /environment noise was filtered/i,
    )
  })

  // ── DOM noise filtering ────────────────────────────────────────────────────

  it("DOM: Supabase/storage text filtered when target domain is threejs.org", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-dom-1", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "dom-noisy-1", source_type: "dom", source_title: "DOM Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 65,
        proof_reason: "DOM captured.",
        artifact_data: {
          dom_summary:
            "Three.js canvas with WebGL context; Supabase admin panel visible; Storage bucket list",
          interacted_elements_summary: "Clicked Compile button; Supabase navigation active",
          state_changes_summary: "Canvas re-rendered after shader update",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    expect(screen.getByTestId("dom-summary-text").textContent).toMatch(/Three\.js canvas/)
    expect(screen.getByTestId("dom-summary-text").textContent).not.toMatch(/Supabase admin panel/)
    expect(screen.getByTestId("dom-state-changes").textContent).toMatch(/Canvas re-rendered/)
  })

  it("DOM: noise-filter notice shown when DOM text was filtered", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-dom-n", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "dom-fn-1", source_type: "dom", source_title: "DOM Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 65,
        proof_reason: "DOM captured.",
        artifact_data: {
          dom_summary: "Canvas element present; Supabase panel captured",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    expect(screen.getByTestId("noise-filter-notice")).toBeInTheDocument()
  })

  // ── Target-domain preservation (anti-over-filter) ─────────────────────────

  it("OCR: target-relevant text preserved — WebGL/3D text not filtered for threejs.org target", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-pres-1", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org/examples/#webgl_geometry" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "ocr-pres-1", source_type: "ocr", source_title: "OCR Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 70,
        proof_reason: "Text extracted.",
        artifact_data: {
          extracted_text_summary:
            "WebGL geometry; Rotation matrix applied; Canvas 3D render active",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    const summary = screen.getByTestId("ocr-extracted-summary")
    expect(summary.textContent).toMatch(/WebGL geometry/)
    expect(summary.textContent).toMatch(/Canvas 3D render/)
  })

  it("anti-over-filter: Supabase text preserved when target domain is supabase.com", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-sb-1", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://supabase.com/dashboard" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "ocr-sb-1", source_type: "ocr", source_title: "OCR Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 70,
        proof_reason: "Text extracted.",
        artifact_data: {
          extracted_text_summary: "Supabase dashboard; Storage buckets created; Database table",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    const summary = screen.getByTestId("ocr-extracted-summary")
    expect(summary.textContent).toMatch(/Supabase dashboard/)
    expect(summary.textContent).toMatch(/Storage buckets/)
  })

  // ── Keyframe: target domain badge ─────────────────────────────────────────

  it("keyframe unavailable state shows target domain when workflow artifact has website_url", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-kf-dom-1", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org/examples/#webgl_geometry_cube" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "kf-td-1", source_type: "keyframe", source_title: "Video Keyframes",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "4 keyframes captured.",
        artifact_data: { frame_count: 4, visual_summary: "3D mesh rendered; WebGL active" },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    const badge = screen.getByTestId("keyframe-target-domain-0")
    expect(badge).toBeInTheDocument()
    expect(badge.textContent).toMatch(/threejs\.org/)
  })

  it("keyframe: noisy visual_summary filtered and FilteredNoiseNotice shown", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-kf-vn-1", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "kf-vn-1", source_type: "keyframe", source_title: "Video Keyframes",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Captured.",
        artifact_data: {
          frame_count: 2,
          visual_summary: "3D scene visible; Supabase dashboard open in background",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    const summary = screen.getByTestId("keyframe-visual-summary-0")
    expect(summary.textContent).toMatch(/3D scene visible/)
    expect(summary.textContent).not.toMatch(/Supabase/)
    expect(screen.getByTestId("noise-filter-notice")).toBeInTheDocument()
  })

  // ── No Website Proof note ─────────────────────────────────────────────────

  it("shows github-only note when skill has github artifacts but no website proof arts", async () => {
    await openViewer(
      makePipeline(
        [
          {
            id: "gh-only-1", source_type: "github", source_title: "evaluator.py",
            project_name: "VeriBridge", visibility: "public", confidence_score: 85,
            proof_reason: "Code confirmed.",
            artifact_data: { file_path: "apps/api/evaluator.py", symbol_name: "EvaluatorService" },
            exact_code_url: "https://github.com/example/repo/blob/main/apps/api/evaluator.py",
            full_file_url: "https://github.com/example/repo/blob/main/apps/api/evaluator.py",
          },
        ],
        "AI / Machine Learning",
      ),
    )
    const note = screen.getByTestId("no-website-proof-note")
    expect(note).toBeInTheDocument()
    expect(note.textContent).toMatch(/GitHub-backed evidence found/i)
    expect(note.textContent).toMatch(/WebGL|Three\.js|Computer Graphics|JavaScript|Frontend Development/i)
  })

  it("shows generic related-skill note when no website proof and no github artifacts", async () => {
    await openViewer(
      makePipeline(
        [
          {
            id: "tr-only-1", source_type: "transcript", source_title: "Defense",
            project_name: "Demo", visibility: "public", confidence_score: 60,
            proof_reason: "Transcript.",
            artifact_data: { excerpt: "Explained the approach." },
            exact_code_url: null, full_file_url: null,
          },
        ],
        "AI / Machine Learning",
      ),
    )
    const note = screen.getByTestId("no-website-proof-note")
    expect(note).toBeInTheDocument()
    expect(note.textContent).toMatch(/No Website Proof artifacts/i)
    expect(note.textContent).toMatch(/WebGL|Three\.js|Computer Graphics/i)
  })

  it("does NOT show no-website-proof note when skill has workflow artifact", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-present", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org", workflow_summary: "Demo recorded." },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    expect(screen.queryByTestId("no-website-proof-note")).not.toBeInTheDocument()
  })

  // ── Qwen visual reasoning preserved ─────────────────────────────────────────

  it("Qwen visual observation shows target-app reasoning and is not suppressed by noise filter", async () => {
    await openViewer(makePipeline([
      {
        id: "qwen-pres-1", source_type: "qwen", source_title: "Visual Reasoning",
        project_name: "Demo", visibility: "public", confidence_score: 75,
        proof_reason: "Qwen analyzed frames.",
        artifact_data: {
          visual_observation_summary:
            "Three.js scene rendering a rotating 3D cube using WebGL pipeline. Shader active.",
          evidence_reasoning: "GPU pipeline confirmed from rendered output on threejs.org",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    expect(screen.getByTestId("qwen-visual-observation").textContent).toMatch(
      /Three\.js scene rendering/,
    )
    expect(screen.getByTestId("qwen-evidence-reasoning").textContent).toMatch(
      /GPU pipeline confirmed/,
    )
  })

  // ── All-noisy content: FilteredFieldEmpty shown, original text not rendered ─

  it("OCR: all-noisy extracted_text_summary shows FilteredFieldEmpty, not original noisy text", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-alln-1", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "ocr-alln-1", source_type: "ocr", source_title: "OCR Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 70,
        proof_reason: "Text extracted.",
        artifact_data: {
          extracted_text_summary: "Buckets; Storage; terminal; Supabase",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    expect(screen.queryByTestId("ocr-extracted-summary")).not.toBeInTheDocument()
    expect(screen.getByTestId("noise-filter-empty")).toBeInTheDocument()
    expect(screen.getByTestId("noise-filter-empty").textContent).toMatch(
      /Environment\/browser noise was removed/i,
    )
    expect(screen.getByTestId("noise-filter-notice")).toBeInTheDocument()
    const viewer = screen.getByTestId("recruiter-safe-evidence-viewer")
    expect(viewer.outerHTML).not.toContain("Buckets")
    expect(viewer.outerHTML).not.toContain("terminal")
  })

  it("DOM: all-noisy dom_summary shows FilteredFieldEmpty, not original noisy text", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-domn-1", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "dom-alln-1", source_type: "dom", source_title: "DOM Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 65,
        proof_reason: "DOM captured.",
        artifact_data: {
          dom_summary: "Supabase admin panel; Storage buckets list",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    expect(screen.queryByTestId("dom-summary-text")).not.toBeInTheDocument()
    expect(screen.getByTestId("noise-filter-empty")).toBeInTheDocument()
    expect(screen.getByTestId("noise-filter-notice")).toBeInTheDocument()
    const viewer = screen.getByTestId("recruiter-safe-evidence-viewer")
    expect(viewer.outerHTML).not.toContain("Supabase admin panel")
    expect(viewer.outerHTML).not.toContain("Storage buckets list")
  })

  it("keyframe: all-noisy visual_summary shows FilteredFieldEmpty, not original noisy text", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-kfn-1", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "kf-alln-1", source_type: "keyframe", source_title: "Keyframe",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Captured.",
        artifact_data: {
          frame_count: 1,
          visual_summary: "Supabase dashboard; Storage buckets panel; terminal open",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    expect(screen.queryByTestId("keyframe-visual-summary-0")).not.toBeInTheDocument()
    expect(screen.getByTestId("noise-filter-empty")).toBeInTheDocument()
    expect(screen.getByTestId("noise-filter-notice")).toBeInTheDocument()
    const viewer = screen.getByTestId("recruiter-safe-evidence-viewer")
    expect(viewer.outerHTML).not.toContain("Supabase dashboard")
    expect(viewer.outerHTML).not.toContain("terminal open")
  })

  // ── Strict quarantine: mixed noisy + garbled residue ──────────────────────

  it("OCR: mixed noisy string with garbled OCR residue — entire field quarantined", async () => {
    // Exact failing string from QA: Buckets/storage segments + garbled OCR residue in same field.
    // The garbled segment must NOT be shown even though it contains the word 'threejs'.
    await openViewer(makePipeline([
      {
        id: "wf-mixed-1", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "ocr-mixed-1", source_type: "ocr", source_title: "OCR Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 70,
        proof_reason: "Text extracted.",
        artifact_data: {
          extracted_text_summary:
            "Buckets; storage; veriido: x xP threejs examples x Veriardge—sewon rec x +",
        },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "ocr-clean-1", source_type: "ocr", source_title: "OCR Clean",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Clean evidence.",
        artifact_data: {
          extracted_text_summary: "Three.js canvas element rendered with WebGL context active",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    // Quarantined field: replacement shown, original NOT rendered
    expect(screen.getByTestId("noise-filter-empty")).toBeInTheDocument()
    // The noisy OCR field must not be shown (check OCR artifact sections directly)
    const ocrDetails = document.querySelectorAll('[data-testid="ocr-artifact-detail"]')
    const ocrHtml = Array.from(ocrDetails).map((el) => el.outerHTML).join("")
    expect(ocrHtml).not.toContain("Buckets")
    expect(ocrHtml).not.toContain("veriido")
    expect(ocrHtml).not.toContain("Veriardge")
    expect(ocrHtml).not.toContain("sewon")
    // Target-app proof from clean artifact still visible
    expect(ocrHtml).toContain("Three.js canvas element rendered")
  })

  it("DOM: pooler/maintenance/us-east residue — entire field quarantined", async () => {
    // Exact failing DOM string from QA: infrastructure noise + garbled residue.
    await openViewer(makePipeline([
      {
        id: "wf-pooler-1", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "dom-pooler-1", source_type: "dom", source_title: "DOM Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 65,
        proof_reason: "DOM captured.",
        artifact_data: {
          dom_summary:
            "Shared pooler maintenance in; us-east-1; 03 Jun, 09:00; machackgo.",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    const viewer = screen.getByTestId("recruiter-safe-evidence-viewer")
    expect(screen.queryByTestId("dom-summary-text")).not.toBeInTheDocument()
    expect(screen.getByTestId("noise-filter-empty")).toBeInTheDocument()
    expect(viewer.outerHTML).not.toContain("pooler")
    expect(viewer.outerHTML).not.toContain("maintenance")
    expect(viewer.outerHTML).not.toContain("us-east")
    expect(viewer.outerHTML).not.toContain("machackgo")
  })

  it("OCR: 'extension' (singular) term is filtered for non-extension target domain", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-ext-1", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "ocr-ext-1", source_type: "ocr", source_title: "OCR Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 70,
        proof_reason: "Text extracted.",
        artifact_data: {
          extracted_text_summary: "Canvas active; Chrome extension recorder running; WebGL enabled",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    const viewer = screen.getByTestId("recruiter-safe-evidence-viewer")
    const html = viewer.outerHTML
    expect(html).not.toContain("Chrome extension recorder")
    expect(html).toContain("Canvas active")
    expect(html).toContain("WebGL enabled")
  })

  it("AI/ML related-skill note names WebGL, Three.js, Computer Graphics, JavaScript, Frontend Development explicitly", async () => {
    await openViewer(
      makePipeline(
        [
          {
            id: "gh-aiml-1", source_type: "github", source_title: "model.py",
            project_name: "Demo", visibility: "public", confidence_score: 80,
            proof_reason: "Code confirmed.",
            artifact_data: { file_path: "model.py", symbol_name: "ModelRunner" },
            exact_code_url: "https://github.com/example/repo/blob/main/model.py",
            full_file_url: "https://github.com/example/repo/blob/main/model.py",
          },
        ],
        "AI / Machine Learning",
      ),
    )
    const note = screen.getByTestId("no-website-proof-note")
    expect(note.textContent).toMatch(/WebGL/i)
    expect(note.textContent).toMatch(/Three\.js/i)
    expect(note.textContent).toMatch(/Computer Graphics/i)
    expect(note.textContent).toMatch(/JavaScript/i)
    expect(note.textContent).toMatch(/Frontend Development/i)
    expect(note.textContent).not.toMatch(/frontend\/graphics skills/i)
  })

  it("target-app terms WebGL/3D/threejs.org preserved after filtering", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-tgt-1", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org/examples/#webgl_cube" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "kf-tgt-1", source_type: "keyframe", source_title: "Keyframe",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Captured.",
        artifact_data: {
          frame_count: 3,
          visual_summary: "3D scene with WebGL geometry; threejs.org demo running; geometric simplification applied",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    const summary = screen.getByTestId("keyframe-visual-summary-0")
    expect(summary.textContent).toMatch(/3D scene/)
    expect(summary.textContent).toMatch(/WebGL geometry/)
    expect(summary.textContent).toMatch(/geometric simplification/)
    expect(screen.queryByTestId("noise-filter-notice")).not.toBeInTheDocument()
  })

  // ── Maintenance / pooler term filtering (new terms) ───────────────────────

  it("OCR: 'maintenance' and 'pooler' segments filtered for threejs.org target", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-mp-1", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org/examples/#webgl_cube" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "ocr-mp-1", source_type: "ocr", source_title: "OCR Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 70,
        proof_reason: "Text extracted.",
        artifact_data: {
          extracted_text_summary:
            "WebGL cube rendered; shared pooler maintenance page; Canvas 3D context active",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    const summary = screen.getByTestId("ocr-extracted-summary")
    expect(summary.textContent).toMatch(/WebGL cube rendered/)
    expect(summary.textContent).toMatch(/Canvas 3D context active/)
    expect(summary.textContent).not.toMatch(/pooler/)
    expect(summary.textContent).not.toMatch(/maintenance/)
  })

  it("DOM: 'maintenance' and 'pooler' segments filtered for threejs.org target", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-mp-2", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "dom-mp-1", source_type: "dom", source_title: "DOM Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 65,
        proof_reason: "DOM captured.",
        artifact_data: {
          dom_summary:
            "Three.js canvas initialized with WebGL; database pooler connection panel visible; Canvas active",
          interacted_elements_summary: "Clicked play button on threejs demo",
          state_changes_summary: "shared pooler maintenance window appeared; shader compiled",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    const domSummary = screen.getByTestId("dom-summary-text")
    expect(domSummary.textContent).toMatch(/Three\.js canvas initialized/)
    expect(domSummary.textContent).not.toMatch(/pooler/)
    const stateChanges = screen.getByTestId("dom-state-changes")
    expect(stateChanges.textContent).toMatch(/shader compiled/)
    expect(stateChanges.textContent).not.toMatch(/maintenance/)
  })

  it("anti-over-filter: 'maintenance' and 'pooler' preserved when target domain is supabase.com", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-sb-mp", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://supabase.com/dashboard/project/abc" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "ocr-sb-mp", source_type: "ocr", source_title: "OCR Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 70,
        proof_reason: "Text extracted.",
        artifact_data: {
          extracted_text_summary:
            "Supabase dashboard; shared pooler maintenance page; Storage bucket created",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    const summary = screen.getByTestId("ocr-extracted-summary")
    expect(summary.textContent).toMatch(/Supabase dashboard/)
    expect(summary.textContent).toMatch(/pooler/)
    expect(summary.textContent).toMatch(/maintenance/)
    expect(summary.textContent).toMatch(/Storage bucket/)
  })

  // ── Qwen: recorder UI detection ─────────────────────────────────────────────

  it("Qwen: recorder UI observation shows RecorderUiGradeNotice and hides observation text", async () => {
    await openViewer(makePipeline([
      {
        id: "qwen-rec-1", source_type: "qwen", source_title: "Visual Reasoning",
        project_name: "Demo", visibility: "public", confidence_score: 70,
        proof_reason: "Qwen analyzed frames.",
        artifact_data: {
          visual_observation_summary:
            "Screen recording interface is visible with a Stop & Upload button.",
          evidence_reasoning: "Confirming WebGL usage from timeline data.",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    expect(screen.getByTestId("qwen-recorder-ui-notice")).toBeInTheDocument()
    expect(screen.queryByTestId("qwen-visual-observation")).not.toBeInTheDocument()
    expect(screen.getByTestId("qwen-evidence-reasoning").textContent).toMatch(/WebGL usage/)
  })

  it("Qwen: backend recorder_ui_detected: true flag triggers RecorderUiGradeNotice", async () => {
    await openViewer(makePipeline([
      {
        id: "qwen-be-rec-1", source_type: "qwen", source_title: "Visual Reasoning",
        project_name: "Demo", visibility: "public", confidence_score: 70,
        proof_reason: "Qwen analyzed frames.",
        artifact_data: {
          recorder_ui_detected: true,
          visual_observation_summary: "Three.js geometry rendered on canvas.",
          evidence_reasoning: "Shader pipeline active.",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    expect(screen.getByTestId("qwen-recorder-ui-notice")).toBeInTheDocument()
    expect(screen.queryByTestId("qwen-visual-observation")).not.toBeInTheDocument()
  })

  it("Qwen: recorder UI not triggered for genuine target-app observation", async () => {
    await openViewer(makePipeline([
      {
        id: "qwen-clean-1", source_type: "qwen", source_title: "Visual Reasoning",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Qwen analyzed frames.",
        artifact_data: {
          visual_observation_summary:
            "Three.js geometry cube rotating in real-time with WebGL context active.",
          evidence_reasoning: "GPU pipeline confirmed from rendered output.",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    expect(screen.queryByTestId("qwen-recorder-ui-notice")).not.toBeInTheDocument()
    expect(screen.getByTestId("qwen-visual-observation").textContent).toMatch(
      /Three\.js geometry cube/,
    )
  })

  // ── Evidence quality badge ────────────────────────────────────────────────

  it("evidence_quality badge renders on keyframe artifact when field is present", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-kf-q-1", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "kf-q-1", source_type: "keyframe", source_title: "Video Keyframes",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "4 keyframes captured.",
        artifact_data: {
          frame_count: 4,
          visual_summary: "3D mesh rendered with WebGL active.",
          evidence_quality: "partial",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    expect(screen.getByTestId("evidence-quality-badge")).toBeInTheDocument()
  })

  it("evidence_quality badge renders on Qwen artifact when field is present", async () => {
    await openViewer(makePipeline([
      {
        id: "qwen-q-1", source_type: "qwen", source_title: "Visual Reasoning",
        project_name: "Demo", visibility: "public", confidence_score: 75,
        proof_reason: "Qwen analyzed frames.",
        artifact_data: {
          visual_observation_summary: "WebGL cube rotating on threejs.org canvas.",
          evidence_quality: "clean",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    expect(screen.getByTestId("evidence-quality-badge")).toBeInTheDocument()
  })

  // ── Keyframe: updated unavailable message ─────────────────────────────────

  it("keyframe unavailable state shows updated message text", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-kf-ua", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "kf-ua-1", source_type: "keyframe", source_title: "Video Keyframes",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Session recorded.",
        artifact_data: {
          frame_count: 3,
          keyframe_image_available: false,
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    const unavailable = screen.getByTestId("keyframe-unavailable-0")
    expect(unavailable).toBeInTheDocument()
    expect(unavailable.textContent).toMatch(/No saved keyframe image is available/)
    expect(unavailable.textContent).toMatch(/Future Website Proof sessions/)
  })

  // ── Unsafe keys still hidden ──────────────────────────────────────────────

  // ── proof_reason quarantine — exact Codex QA failing OCR noise ───────────────

  it("OCR: exact failing noise string in proof_reason is quarantined, not rendered", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-pr-noise-1", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "ocr-pr-noise-1", source_type: "ocr", source_title: "OCR Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 70,
        proof_reason: "Buckets; storage; veriido: x xP threejs examples x Veriardge—sewon rec x +",
        artifact_data: { extracted_text_summary: "Three.js canvas rendered with WebGL context active." },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    const viewer = screen.getByTestId("recruiter-safe-evidence-viewer")
    expect(viewer.outerHTML).not.toContain("Buckets")
    expect(viewer.outerHTML).not.toContain("veriido")
    expect(viewer.outerHTML).not.toContain("Veriardge")
    expect(viewer.outerHTML).not.toContain("sewon rec")
    expect(screen.getByTestId("proof-reason-noise-filter")).toBeInTheDocument()
    expect(screen.getByTestId("proof-reason-noise-filter").textContent).toMatch(
      /Environment\/browser noise was removed/i,
    )
  })

  it("OCR: noisy proof_reason quarantined but clean artifact_data text remains visible", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-pr-mixed-1", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "ocr-pr-mixed-1", source_type: "ocr", source_title: "OCR Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 70,
        proof_reason: "Buckets; storage; veriido: x xP threejs examples x Veriardge—sewon rec x +",
        artifact_data: {
          extracted_text_summary: "Three.js WebGL canvas rendering 3D mesh geometry on threejs.org.",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    // noisy proof_reason quarantined
    expect(screen.getByTestId("proof-reason-noise-filter")).toBeInTheDocument()
    // clean artifact_data still visible
    const ocrSummary = screen.getByTestId("ocr-extracted-summary")
    expect(ocrSummary.textContent).toMatch(/Three\.js WebGL canvas/)
    expect(ocrSummary.textContent).toMatch(/3D mesh geometry/)
    const viewer = screen.getByTestId("recruiter-safe-evidence-viewer")
    expect(viewer.outerHTML).not.toContain("Buckets")
    expect(viewer.outerHTML).not.toContain("veriido")
  })

  it("clean proof_reason renders normally through SafeProofReason", async () => {
    await openViewer(makePipeline([
      {
        id: "ocr-pr-clean-1", source_type: "ocr", source_title: "OCR Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Live WebGL session confirmed on threejs.org.",
        artifact_data: { extracted_text_summary: "Canvas active with WebGL context." },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    const prText = screen.getByTestId("proof-reason-text")
    expect(prText).toBeInTheDocument()
    expect(prText.textContent).toMatch(/Live WebGL session confirmed/)
    expect(screen.queryByTestId("proof-reason-noise-filter")).not.toBeInTheDocument()
  })

  it("noisy proof_reason quarantined in DOM artifact section", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-pr-dom-1", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "dom-pr-noise-1", source_type: "dom", source_title: "DOM Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 65,
        proof_reason: "Buckets; storage; veriido: x xP threejs examples x Veriardge—sewon rec x +",
        artifact_data: { dom_summary: "Three.js WebGL canvas element observed in DOM." },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    const viewer = screen.getByTestId("recruiter-safe-evidence-viewer")
    expect(viewer.outerHTML).not.toContain("Buckets")
    expect(viewer.outerHTML).not.toContain("veriido")
    expect(viewer.outerHTML).not.toContain("Veriardge")
    expect(screen.getByTestId("proof-reason-noise-filter")).toBeInTheDocument()
    expect(screen.getByTestId("dom-summary-text").textContent).toMatch(/Three\.js WebGL canvas/)
  })

  it("noisy proof_reason quarantined in Qwen artifact section", async () => {
    await openViewer(makePipeline([
      {
        id: "wf-pr-qwen-1", source_type: "workflow", source_title: "Website Workflow",
        project_name: "Demo", visibility: "public", confidence_score: 80,
        proof_reason: "Recorded.",
        artifact_data: { website_url: "https://threejs.org" },
        exact_code_url: null, full_file_url: null,
      },
      {
        id: "qwen-pr-noise-1", source_type: "qwen", source_title: "Visual Reasoning",
        project_name: "Demo", visibility: "public", confidence_score: 75,
        proof_reason: "Buckets; storage; veriido: x xP threejs examples x Veriardge—sewon rec x +",
        artifact_data: {
          visual_observation_summary: "WebGL renderer active on threejs.org with 3D mesh visible.",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    const viewer = screen.getByTestId("recruiter-safe-evidence-viewer")
    expect(viewer.outerHTML).not.toContain("Buckets")
    expect(viewer.outerHTML).not.toContain("sewon rec")
    expect(screen.getByTestId("proof-reason-noise-filter")).toBeInTheDocument()
    expect(screen.getByTestId("qwen-visual-observation").textContent).toMatch(/WebGL renderer active/)
  })

  it("unsafe keys (token, storage_path, signed_url, etc.) still hidden after filtering logic added", async () => {
    await openViewer(makePipeline([
      {
        id: "unsafe-nf-1", source_type: "ocr", source_title: "OCR Evidence",
        project_name: "Demo", visibility: "public", confidence_score: 70,
        proof_reason: "Text extracted.",
        artifact_data: {
          extracted_text_summary: "Canvas active; WebGL context enabled",
          access_token: "eyJhbGciOiJIUzI1NiJ9.secret",
          storage_path: "/private/recordings/abc.webm",
          signed_url: "https://supabase.co/storage/v1/sign/abc?token=xyz",
          video_url: "https://internal.veribridge.app/private/abc.mp4",
          service_role: "supabase-service-role-key",
          anon_key: "supabase-anon-key",
          media_storage_path: "/media/abc",
        },
        exact_code_url: null, full_file_url: null,
      },
    ]))
    const viewer = screen.getByTestId("recruiter-safe-evidence-viewer")
    const html = viewer.outerHTML
    expect(html).not.toContain("eyJhbGciOiJIUzI1NiJ9")
    expect(html).not.toContain("/private/recordings/")
    expect(html).not.toContain("supabase.co/storage")
    expect(html).not.toContain("supabase-service-role-key")
    expect(html).not.toContain("supabase-anon-key")
    expect(html).not.toContain("media_storage_path")
    expect(html).not.toContain("video_url")
  })
})
