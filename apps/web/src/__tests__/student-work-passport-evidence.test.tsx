import React from "react"
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { StudentProfileProof } from "../../components/dashboard/StudentViews"
import type { BackendSkillPipeline, BackendEvidenceSource } from "@/lib/api"

// ── Mock child components that make their own API calls ─────────────────────────

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

vi.mock("../../data/mock", () => ({
  student: { score: 82, verifiedSkills: 8, publicProof: 6 },
  skillGaps: [],
  applications: [],
  jobs: [],
  visaSignals: [],
}))

vi.mock("@/lib/api", () => ({
  listSkillEvidencePipelines: vi.fn(),
}))

import { listSkillEvidencePipelines } from "@/lib/api"

// ── Fixtures ─────────────────────────────────────────────────────────────────────

function makeEvidenceSource(overrides: Partial<BackendEvidenceSource> = {}): BackendEvidenceSource {
  return {
    key: "github",
    label: "GitHub",
    status: "supported",
    score: 85,
    reason: "Commits reviewed",
    ...overrides,
  }
}

function makeBackendPipeline(overrides: Partial<BackendSkillPipeline> = {}): BackendSkillPipeline {
  return {
    id: "pipeline-uuid-1",
    student_id: "student-1",
    profile_id: "profile-1",
    skill_name: "AI / Machine Learning",
    skill_category: "Core ML",
    confidence_score: 82,
    support_status: "strongly_supported",
    evidence_count: 1,
    strongest_proof: null,
    weakest_proof: null,
    missing_evidence: [],
    next_actions: [],
    evidence_sources: [makeEvidenceSource()],
    recruiter_summary: "Strong ML foundation.",
    student_summary: "You have strong ML evidence.",
    visibility_status: "public",
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    ...overrides,
  }
}

async function openWorkPassportTab() {
  render(<StudentProfileProof />)
  fireEvent.click(screen.getByRole("tab", { name: "Work Passport" }))
  await waitFor(() => expect(screen.queryByText(/Loading synced evidence/i)).not.toBeInTheDocument())
}

describe("Work Passport — Skill Evidence from Proofs panel", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("shows empty state when no pipelines are synced", async () => {
    vi.mocked(listSkillEvidencePipelines).mockResolvedValue([])
    await openWorkPassportTab()

    expect(screen.getByTestId("evidence-from-proofs-panel")).toHaveTextContent(/No synced proof evidence yet/i)
  })

  it("shows empty state when backend is unavailable (null)", async () => {
    vi.mocked(listSkillEvidencePipelines).mockResolvedValue(null)
    await openWorkPassportTab()

    expect(screen.getByTestId("evidence-from-proofs-panel")).toHaveTextContent(/No synced proof evidence yet/i)
  })

  it("renders a GitHub evidence source as repo-supported", async () => {
    vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
      makeBackendPipeline({
        evidence_sources: [makeEvidenceSource({ key: "github" })],
      }),
    ])
    await openWorkPassportTab()

    const githubRow = screen.getByTestId("evidence-source-github")
    expect(githubRow).toHaveTextContent("GitHub")
    expect(screen.getByTestId("evidence-status-github")).toHaveTextContent(/repo-supported/i)
  })

  it("renders a document evidence source as document-supported and does not claim full verification", async () => {
    vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
      makeBackendPipeline({
        evidence_sources: [makeEvidenceSource({ key: "document", label: "Document", reason: "Uploaded report" })],
      }),
    ])
    await openWorkPassportTab()

    const docRow = screen.getByTestId("evidence-source-document")
    expect(screen.getByTestId("evidence-status-document")).toHaveTextContent(/document-supported/i)
    expect(docRow.textContent).toMatch(/not independently verified/i)
    expect(docRow.textContent).not.toMatch(/fully verified/i)
  })

  it("renders a certificate evidence source grouped under Documents & Certificates", async () => {
    vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
      makeBackendPipeline({
        evidence_sources: [makeEvidenceSource({ key: "certificate", label: "Certificate", reason: "Uploaded certificate" })],
      }),
    ])
    await openWorkPassportTab()

    const docRow = screen.getByTestId("evidence-source-document")
    expect(docRow).toHaveTextContent("Documents & Certificates")
    expect(screen.getByTestId("evidence-status-document")).toHaveTextContent(/document-supported/i)
  })

  it("renders a website/workflow evidence source as demonstrated workflow evidence", async () => {
    vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
      makeBackendPipeline({
        evidence_sources: [makeEvidenceSource({ key: "workflow", label: "Workflow recording", reason: "Recorded workflow session" })],
      }),
    ])
    await openWorkPassportTab()

    const webRow = screen.getByTestId("evidence-source-website")
    expect(webRow.textContent).toMatch(/demonstrated workflow evidence/i)
  })

  it("aggregates evidence sources across multiple pipelines into the same category", async () => {
    vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
      makeBackendPipeline({
        skill_name: "AI / Machine Learning",
        evidence_sources: [makeEvidenceSource({ key: "github" })],
      }),
      makeBackendPipeline({
        skill_name: "DevOps / Deployment",
        evidence_sources: [makeEvidenceSource({ key: "github" })],
        visibility_status: "public",
      }),
    ])
    await act(async () => {})
    await openWorkPassportTab()

    expect(screen.getByTestId("evidence-meta-github")).toHaveTextContent("2 items · 2 skills")
  })

  // ── Must-fix: student-owned pipeline endpoint, not recruiter-safe artifacts ──

  it("renders evidence from the student-owned pipeline endpoint, not recruiter-safe artifacts", async () => {
    vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
      makeBackendPipeline({
        evidence_sources: [makeEvidenceSource({ key: "github" })],
      }),
    ])
    await openWorkPassportTab()

    expect(vi.mocked(listSkillEvidencePipelines)).toHaveBeenCalled()
    expect(screen.getByTestId("evidence-source-github")).toBeInTheDocument()
  })

  it("protected document/certificate evidence appears in the student-facing panel even though recruiter-safe would hide it", async () => {
    vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
      makeBackendPipeline({
        visibility_status: "protected",
        evidence_sources: [makeEvidenceSource({ key: "certificate", label: "Certificate", reason: "Uploaded certificate" })],
      }),
    ])
    await openWorkPassportTab()

    const docRow = screen.getByTestId("evidence-source-document")
    expect(docRow).toBeInTheDocument()
    expect(screen.getByTestId("evidence-status-document")).toHaveTextContent(/document-supported/i)
    expect(screen.getByTestId("evidence-meta-document")).toHaveTextContent(/Protected/i)
  })

  it("private evidence is visible to the student even though recruiter-safe excludes private pipelines", async () => {
    vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
      makeBackendPipeline({
        visibility_status: "private",
        evidence_sources: [makeEvidenceSource({ key: "document", label: "Document", reason: "Uploaded report" })],
      }),
    ])
    await openWorkPassportTab()

    expect(screen.getByTestId("evidence-source-document")).toBeInTheDocument()
    expect(screen.getByTestId("evidence-meta-document")).toHaveTextContent(/Private/i)
  })

  // ── Must-fix: honest mixed-visibility labeling ──

  it("shows 'Mixed visibility' when a category has both public and protected evidence", async () => {
    vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
      makeBackendPipeline({
        skill_name: "AI / Machine Learning",
        visibility_status: "public",
        evidence_sources: [makeEvidenceSource({ key: "github" })],
      }),
      makeBackendPipeline({
        skill_name: "DevOps / Deployment",
        visibility_status: "protected",
        evidence_sources: [makeEvidenceSource({ key: "github" })],
      }),
    ])
    await openWorkPassportTab()

    expect(screen.getByTestId("evidence-meta-github")).toHaveTextContent(/Mixed visibility/i)
  })

  it("shows a single visibility state when all evidence in a category shares it", async () => {
    vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
      makeBackendPipeline({
        skill_name: "AI / Machine Learning",
        visibility_status: "protected",
        evidence_sources: [makeEvidenceSource({ key: "github" })],
      }),
      makeBackendPipeline({
        skill_name: "DevOps / Deployment",
        visibility_status: "protected",
        evidence_sources: [makeEvidenceSource({ key: "github" })],
      }),
    ])
    await openWorkPassportTab()

    expect(screen.getByTestId("evidence-meta-github")).toHaveTextContent("Protected")
    expect(screen.getByTestId("evidence-meta-github")).not.toHaveTextContent(/Mixed visibility/i)
  })

  // ── Must-fix: certificate evidence is included in document/certificate category ──

  it("counts certificate and document evidence sources together in the document category", async () => {
    vi.mocked(listSkillEvidencePipelines).mockResolvedValue([
      makeBackendPipeline({
        skill_name: "AI / Machine Learning",
        evidence_sources: [
          makeEvidenceSource({ key: "document", label: "Document", reason: "Uploaded report" }),
          makeEvidenceSource({ key: "certificate", label: "Certificate", reason: "Uploaded certificate" }),
        ],
      }),
    ])
    await openWorkPassportTab()

    expect(screen.getByTestId("evidence-meta-document")).toHaveTextContent("2 items · 1 skill")
  })
})
