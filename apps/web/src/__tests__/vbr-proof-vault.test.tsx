/**
 * Student Proof Vault — frontend rendering tests.
 *
 * Covers: the Private Work Passport's "Proof Vault" section (every owned proof
 * grouped by skill, attached AND unattached, with unattached proofs clearly
 * labelled), the per-project report's "Other student proofs for related skills"
 * section, the VaultProofList component's safe metadata rendering, and the
 * absence of any private vault structure on the recruiter-facing public passport.
 */

import { render, screen, fireEvent } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"

import { PrivatePassportView } from "../app/student/vbr/passport/PrivatePassportView"
import { ProjectReportView } from "../app/student/vbr/projects/[projectId]/report/ProjectReportView"
import { PublicPassportView } from "../app/p/[slug]/PublicPassportView"
import { SkillReportPageView } from "../app/student/vbr/passport/skills/[skillSlug]/SkillReportView"
import { SkillReportView, VaultProofList } from "../../components/passport/VaultProofs"
import type {
  PrivateWorkPassport,
  PublicWorkPassport,
  SkillReport,
  SkillReportProjectChain,
  VaultSkillGroup,
  VaultSkillSummary,
  VBRStudentProjectReportResponse,
  WorkPassportStatus,
} from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/vbr-api")>()),
  getPrivateWorkPassport: vi.fn(),
  getWorkPassportStatus: vi.fn(),
  getSkillReport: vi.fn(),
  getVBRProjectReport: vi.fn(),
  getVBRProjectReportPublishStatus: vi.fn(),
  getPublicWorkPassportBySlug: vi.fn(),
}))

vi.mock("next/navigation", () => ({ redirect: vi.fn() }))

import {
  getPrivateWorkPassport,
  getWorkPassportStatus,
  getSkillReport,
  getVBRProjectReport,
  getVBRProjectReportPublishStatus,
  getPublicWorkPassportBySlug,
} from "@/lib/vbr-api"

// ── Fixtures ──────────────────────────────────────────────────────────────────

function vaultSummary(overrides: Partial<VaultSkillSummary> = {}): VaultSkillSummary {
  return {
    skill: "Python",
    skill_slug: "python",
    category: "Programming Language",
    status: "Evidence observed",
    source_labels: ["Python"],
    project_ids: [],
    project_titles: [],
    project_count: 0,
    proof_source_counts: { "Website Proof": 1 },
    proof_count: 1,
    attached_count: 0,
    unattached_count: 1,
    has_unattached: true,
    summary: "1 proof source(s) across 1 type(s) support this skill.",
    previews: [
      {
        proof_type: "Website Proof",
        title: "https://demo.example.com",
        safe_location: "demo.example.com",
        safe_summary: "A working deployment was inspected.",
        is_attached_to_project: false,
        public_safe: true,
      },
    ],
    more_count: 0,
    limitations: ["1 proof(s) not attached to a VBR project."],
    ...overrides,
  }
}

const GITHUB_ITEM: SkillReport["github"][number] = {
  proof_type: "GitHub Proof",
  source_id: "gh-1",
  title: "octocat/Hello-World",
  safe_summary: "Repository analyzed.",
  safe_location: "src/model/train.py · train_model()",
  safe_snippet: "def train_model(): ...",
  public_safe: true,
  is_attached_to_project: false,
  attached_project_ids: [],
  project_titles: [],
  limitation: "Repo evidence is not proof of authorship.",
  file_path: "src/model/train.py",
  line_start: 10,
  line_end: 24,
  function_name: "train_model",
  commit_sha: "abc1234",
  public_url: "https://github.com/octocat/Hello-World/blob/main/src/model/train.py#L10-L24",
  workflow_steps: [],
}

function emptyStandalone(): SkillReport["standalone_evidence"] {
  return { github: [], website: [], documents: [], document_more_count: 0, defense: [], video: [], skill_graph: [] }
}

function skillReport(overrides: Partial<SkillReport> = {}): SkillReport {
  return {
    skill: "Python",
    skill_slug: "python",
    requested_skill: "python",
    category: "Programming Language",
    status: "Demonstrated",
    summary: "1 safe proof source(s) across 1 type(s) support Python.",
    source_counts: { "GitHub Proof": 1 },
    overview: {
      skill: "Python",
      category: "Programming Language",
      status: "Demonstrated",
      proof_source_counts: { "GitHub Proof": 1 },
      proof_count: 1,
      attached_count: 0,
      unattached_count: 1,
      project_count: 0,
      why_supported: "1 safe proof source(s) across 1 type(s) support Python.",
      gaps: ["No Website Proof maps to this skill."],
    },
    projects: [],
    standalone_evidence: { ...emptyStandalone(), github: [{ ...GITHUB_ITEM }] },
    github: [{ ...GITHUB_ITEM }],
    website: [],
    documents: [],
    defense: [],
    video: [],
    skill_graph: [],
    gaps: ["No Website Proof maps to this skill."],
    generated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  }
}

function vaultGroup(overrides: Partial<VaultSkillGroup> = {}): VaultSkillGroup {
  return {
    skill: "Python",
    proof_types: ["Website Proof"],
    attached_count: 0,
    unattached_count: 1,
    has_unattached: true,
    proofs: [
      {
        skill_name: "Python",
        proof_type: "Website Proof",
        source_id: "sess-9",
        source_table: "workflow_analysis_results",
        project_id: null,
        attached_project_ids: [],
        title: "https://demo.example.com",
        source_label: "Website Proof",
        safe_summary: "A working deployment was inspected for the supported skills.",
        safe_snippet: null,
        safe_location: "demo.example.com",
        public_safe: true,
        visibility: "public",
        limitation: "Confirms observed behaviour at inspection time. Not attached to a VBR project.",
        is_attached_to_project: false,
      },
    ],
    ...overrides,
  }
}

function makePassport(overrides: Partial<PrivateWorkPassport> = {}): PrivateWorkPassport {
  return {
    candidate_display_name: "Jordan Rivera",
    headline: "Full-stack builder",
    summary: "I ship and defend real projects.",
    is_published: false,
    public_slug: null,
    public_path: null,
    published_at: null,
    skills: [],
    projects: [],
    evidence_source_counts: {},
    vault_skill_summaries: [vaultSummary()],
    vault_proof_count: 1,
    vault_unattached_count: 1,
    project_count: 0,
    published_report_count: 0,
    limitations: ["1 proof item(s) are not attached to any VBR project."],
    generated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  }
}

function statusFrom(p: PrivateWorkPassport): WorkPassportStatus {
  return {
    is_published: p.is_published,
    public_slug: p.public_slug,
    public_path: p.public_path,
    published_at: p.published_at,
    headline: p.headline,
    summary: p.summary,
  }
}

function makeReport(overrides: Partial<VBRStudentProjectReportResponse> = {}): VBRStudentProjectReportResponse {
  return {
    project_id: "proj-1",
    project_title: "Skill Evidence Tracker",
    project_description: "Tracks skill evidence.",
    repo_url: "https://github.com/octocat/Hello-World",
    repo_full_name: "octocat/Hello-World",
    student_role: "I built it.",
    claimed_skills: ["Python"],
    project_status: "questions_ready",
    session_id: "sess-1",
    generated_at: "2026-01-01T00:00:00Z",
    evidence_package: {
      github_proof_attached: false,
      documents_count: 0,
      website_proofs_count: 0,
      project_defense_completed: false,
      video_defense_recorded: false,
      video_evidence_chip_count: 0,
    },
    github_proof: null,
    documents: [],
    website_proofs: [],
    project_defense_analysis: null,
    defense_questions: [],
    video_evidence_chips: [],
    skill_evidence: [],
    evidence_traces: [],
    other_student_proofs: [vaultGroup()],
    limitations: ["Website proof not attached."],
    next_actions: [],
    preview_only: true,
    public_recruiter_sharing_enabled: false,
    note: "Student preview.",
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(getPrivateWorkPassport).mockReset()
  vi.mocked(getWorkPassportStatus).mockReset()
  vi.mocked(getSkillReport).mockReset()
  vi.mocked(getVBRProjectReport).mockReset()
  vi.mocked(getVBRProjectReportPublishStatus).mockReset()
  vi.mocked(getVBRProjectReportPublishStatus).mockResolvedValue({
    project_id: "proj-1",
    is_public: false,
    public_token: null,
    public_path: null,
    published_at: null,
  })
})

// ── Private Work Passport vault section ────────────────────────────────────────

describe("PrivatePassportView — Skill Intelligence (compact dashboard)", () => {
  it("renders compact skill summary cards under category headings, not raw proof cards", async () => {
    const p = makePassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    expect(await screen.findByTestId("vault-skill-dashboard")).toBeInTheDocument()
    const card = screen.getByTestId("vault-skill-summary")
    expect(card).toHaveAttribute("data-skill", "Python")
    expect(screen.getByTestId("vault-category")).toHaveAttribute("data-category", "Programming Language")
    // The main page shows source counts, NOT every raw proof card.
    expect(screen.getByTestId("vault-summary-source-counts")).toHaveTextContent("Website Proof: 1")
    expect(screen.queryByTestId("vault-proof")).not.toBeInTheDocument()
    expect(screen.queryByTestId("skill-evidence-item")).not.toBeInTheDocument()
  })

  it("labels unattached proofs clearly", async () => {
    const p = makePassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    expect(await screen.findByTestId("vault-summary-unattached")).toHaveTextContent("not attached")
    expect(screen.getByTestId("vault-unattached-summary")).toHaveTextContent("1 unattached proof item")
  })

  it("links 'View Skill Report' to the SEPARATE skill report route — never inline", async () => {
    const p = makePassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    await screen.findByTestId("vault-skill-dashboard")
    const link = screen.getByTestId("view-skill-report")
    // It is a navigation link to the separate page, not an inline toggle.
    expect(link).toHaveAttribute("href", "/student/vbr/passport/skills/python")
    // The expensive Skill Report is NEVER fetched from the Passport page.
    expect(getSkillReport).not.toHaveBeenCalled()
    // Clicking does not expand a report inline on the Passport.
    fireEvent.click(link)
    expect(screen.queryByTestId("skill-report")).not.toBeInTheDocument()
  })

  it("omits the vault section when there are no skill summaries", async () => {
    const p = makePassport({ vault_skill_summaries: [], vault_proof_count: 0, vault_unattached_count: 0 })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-header")
    expect(screen.queryByTestId("vault-skill-dashboard")).not.toBeInTheDocument()
  })
})

describe("Skill Report page (separate route)", () => {
  it("fetches and renders ACTUAL GitHub evidence for the slug, with gaps", async () => {
    vi.mocked(getSkillReport).mockResolvedValue(skillReport())

    render(<SkillReportPageView skillSlug="python" />)

    expect(await screen.findByTestId("skill-report")).toBeInTheDocument()
    expect(getSkillReport).toHaveBeenCalledWith("python")
    expect(screen.getByTestId("skill-report-github")).toBeInTheDocument()
    expect(screen.getByTestId("github-location")).toHaveTextContent("src/model/train.py")
    expect(screen.getByTestId("github-snippet")).toHaveTextContent("def train_model")
    expect(screen.getByTestId("evidence-public-link")).toHaveAttribute(
      "href",
      expect.stringContaining("#L10-L24"),
    )
    expect(screen.getByTestId("skill-report-gaps")).toBeInTheDocument()
  })

  it("renders hydrated website workflow / OCR / DOM / visual summaries", async () => {
    vi.mocked(getSkillReport).mockResolvedValue(
      skillReport({
        github: [],
        standalone_evidence: {
          ...emptyStandalone(),
          website: [
            {
              proof_type: "Website Proof",
              source_id: "sess-1",
              title: "https://demo.example.com",
              safe_summary: "",
              safe_location: "demo.example.com",
              public_safe: true,
              is_attached_to_project: false,
              attached_project_ids: [],
              project_titles: [],
              limitation: "Confirms observed behaviour at inspection time.",
              workflow_summary: "User logged in and ran a prediction.",
              workflow_steps: ["Log in", "Run prediction"],
              ocr_summary: "Prediction: 0.92",
              dom_summary: "Dashboard rendered with a results panel.",
              visual_summary: "A working ML dashboard.",
              live_check: { is_reachable: true },
            },
          ],
        },
      }),
    )

    render(<SkillReportPageView skillSlug="python" />)

    expect(await screen.findByTestId("skill-report-website")).toBeInTheDocument()
    expect(screen.getByTestId("website-workflow")).toHaveTextContent("ran a prediction")
    expect(screen.getByTestId("website-ocr")).toHaveTextContent("Prediction: 0.92")
    expect(screen.getByTestId("website-dom")).toHaveTextContent("Dashboard rendered")
    expect(screen.getByTestId("website-visual")).toHaveTextContent("working ML dashboard")
  })
})

describe("SkillReportView — connected proof chains & document corroboration", () => {
  function chainReport(): SkillReport {
    return skillReport({
      github: [],
      standalone_evidence: emptyStandalone(),
      projects: [
        {
          project_id: "proj-1",
          project_title: "Boston Smart Accident Risk Rerouting",
          attached: true,
          attached_status: "Attached to a VBR project",
          sources: ["GitHub Proof", "Document Proof"],
          evidence_chain_summary:
            "In Boston, Python is supported by GitHub code and document corroboration — these sources corroborate the same skill claim.",
          github_evidence: [{ ...GITHUB_ITEM, is_attached_to_project: true, attached_project_ids: ["proj-1"] }],
          website_evidence: [],
          document_correlations: [
            {
              source_id: "doc-1",
              document_title: "Boston — Final Report",
              page_number: 5,
              section_label: "Methodology",
              citation: "Methodology",
              safe_snippet: "The model endpoint serves predictions.",
              corroborates: "GitHub implementation",
              reason: "Describes the same ML model endpoint.",
              limitation: "Document supports the claim but does not independently prove implementation.",
            },
            {
              source_id: "doc-2",
              document_title: "Boston — Appendix",
              page_number: 9,
              section_label: null,
              citation: null,
              safe_snippet: "Pipeline overview.",
              corroborates: "GitHub implementation",
              reason: "Pipeline overview.",
              limitation: "Document supports the claim but does not independently prove implementation.",
            },
            {
              source_id: "doc-3",
              document_title: "Boston — Notes",
              page_number: 11,
              section_label: null,
              citation: null,
              safe_snippet: "Training loop notes.",
              corroborates: "GitHub implementation",
              reason: "Training loop notes.",
              limitation: "Document supports the claim but does not independently prove implementation.",
            },
          ],
          document_more_count: 2,
          defense_evidence: [],
          video_evidence: [],
          limitations: [],
        },
      ],
    })
  }

  it("renders a connected proof chain with documents as corroboration, not a dump", () => {
    render(<SkillReportView report={chainReport()} />)

    // The chain ties GitHub code and the corroborating document together.
    const chain = screen.getByTestId("skill-report-chain")
    expect(chain).toHaveAttribute("data-project", "proj-1")
    expect(screen.getByTestId("chain-summary")).toHaveTextContent("corroborate the same skill claim")
    expect(screen.getByTestId("chain-github")).toBeInTheDocument()

    // Documents appear as connected corroboration cards, capped, with a +N more.
    const corr = screen.getAllByTestId("document-correlation")
    expect(corr).toHaveLength(3)
    expect(screen.getAllByTestId("document-corroborates")[0]).toHaveTextContent("GitHub implementation")
    expect(screen.getByTestId("document-more")).toHaveTextContent("+2 more supporting document citation")
  })

  it("does not repeat duplicate document snippets beyond what the API returns", () => {
    // The API already de-dupes; the component renders exactly what it is given.
    render(<SkillReportView report={chainReport()} />)
    const snippets = screen.getAllByTestId("document-snippet").map((n) => n.textContent)
    expect(new Set(snippets).size).toBe(snippets.length)
  })

  it("shows skill-specific document context (figure, why) and gates full download", () => {
    const report = chainReport()
    const chain = (report.proof_chains ?? report.projects)![0]
    chain.document_correlations = [
      {
        source_id: "doc-1",
        document_title: "Stroke — Final Report",
        page_number: 7,
        section_label: "Model Evaluation",
        citation: "Model Evaluation",
        figure_reference: "Figure 4",
        safe_snippet: "Reported F1 and confusion matrix.",
        corroborates: "GitHub implementation",
        reason: "Documents the evaluation metrics.",
        why_supported: "Documents the evaluation metrics used to assess the model.",
        full_document_available: false,
        document_access_note: "Full document available only with candidate permission.",
        limitation: "Document supports the claim but does not independently prove implementation.",
      },
    ]
    chain.document_more_count = 0
    render(<SkillReportView report={report} />)
    expect(screen.getByTestId("document-citation")).toHaveTextContent("Figure 4")
    expect(screen.getByTestId("document-why")).toHaveTextContent("evaluation metrics")
    expect(screen.getByTestId("document-access-note")).toHaveTextContent(
      "Full document available only with candidate permission.",
    )
  })
})

// ── GitHub weak/repo-level evidence is shown as a limitation, never a code card ─

describe("SkillReportView — weak / repo-level GitHub evidence", () => {
  const REPO_LEVEL_ITEM: SkillReport["github"][number] = {
    proof_type: "GitHub Proof",
    source_id: "gh-weak",
    title: "octocat/Hello-World",
    safe_summary: "Repository analyzed.",
    safe_location: "github.com",
    safe_snippet: null, // backend never sends a weak snippet
    public_safe: true,
    is_attached_to_project: false,
    attached_project_ids: [],
    project_titles: [],
    limitation:
      "Repository-level evidence only: the stored GitHub line evidence for this skill is imports, setup/metadata or notebook narrative — not strong line-level proof.",
    file_path: null,
    line_start: null,
    line_end: null,
    function_name: null,
    commit_sha: null,
    public_url: "https://github.com/octocat/Hello-World",
    workflow_steps: [],
  }

  it("renders the repo-level limitation and NO import/sys.path code-line card", () => {
    render(
      <SkillReportView
        report={skillReport({
          github: [],
          standalone_evidence: { ...emptyStandalone(), github: [{ ...REPO_LEVEL_ITEM }] },
        })}
      />,
    )
    // No fake code-line card: no GitHub location and no snippet are rendered.
    expect(screen.queryByTestId("github-location")).not.toBeInTheDocument()
    expect(screen.queryByTestId("github-snippet")).not.toBeInTheDocument()
    // The honest repo-level limitation IS shown.
    expect(screen.getByText(/Repository-level evidence only/i)).toBeInTheDocument()
    // No import/sys.path text leaks into the rendered card.
    expect(screen.queryByText(/import sys/)).not.toBeInTheDocument()
    expect(screen.queryByText(/sys\.path/)).not.toBeInTheDocument()
  })

  it("renders strong GitHub evidence with file/line/link/snippet", () => {
    render(
      <SkillReportView
        report={skillReport({
          github: [],
          standalone_evidence: { ...emptyStandalone(), github: [{ ...GITHUB_ITEM }] },
        })}
      />,
    )
    expect(screen.getByTestId("github-location")).toHaveTextContent("src/model/train.py")
    expect(screen.getByTestId("github-snippet")).toHaveTextContent("def train_model")
    expect(screen.getByTestId("evidence-public-link")).toHaveAttribute(
      "href",
      expect.stringContaining("#L10-L24"),
    )
  })
})

// ── Explicit GitHub display_mode rendering (code_line vs repo_level) ───────────

describe("SkillReportView — explicit GitHub display_mode", () => {
  const PRECISE_ITEM: SkillReport["github"][number] = {
    ...GITHUB_ITEM,
    source_id: "gh-precise",
    safe_location: "api.py · predict()",
    safe_snippet: "def predict(req):\n    return model.predict(req)",
    file_path: "api.py",
    line_start: 252,
    line_end: 255,
    function_name: "predict",
    display_mode: "code_line",
    has_precise_line_evidence: true,
    evidence_strength: "strong",
    evidence_kind: "function",
    github_line_url: "https://github.com/octocat/Hello-World/blob/abc1234/api.py#L252-L255",
    repo_url: "https://github.com/octocat/Hello-World",
    public_url: "https://github.com/octocat/Hello-World/blob/abc1234/api.py#L252-L255",
  }

  const REPO_LEVEL_MODE_ITEM: SkillReport["github"][number] = {
    proof_type: "GitHub Proof",
    source_id: "gh-repo",
    title: "octocat/Hello-World",
    safe_summary: "Repository analyzed.",
    safe_location: "github.com",
    safe_snippet: null,
    public_safe: true,
    is_attached_to_project: false,
    attached_project_ids: [],
    project_titles: [],
    limitation:
      "Repository-level evidence only: the stored GitHub line evidence for this skill is imports, setup/metadata or notebook narrative — not strong line-level proof.",
    file_path: null,
    line_start: null,
    line_end: null,
    function_name: null,
    commit_sha: null,
    display_mode: "repo_level",
    has_precise_line_evidence: false,
    evidence_strength: "weak",
    evidence_kind: "repo_level_summary",
    github_line_url: null,
    repo_url: "https://github.com/octocat/Hello-World",
    public_url: "https://github.com/octocat/Hello-World",
    workflow_steps: [],
  }

  it("renders precise evidence with a 'Precise code evidence' badge and 'View code lines' link", () => {
    render(
      <SkillReportView
        report={skillReport({
          github: [],
          standalone_evidence: { ...emptyStandalone(), github: [{ ...PRECISE_ITEM }] },
        })}
      />,
    )
    expect(screen.getByTestId("github-precise-badge")).toHaveTextContent("Precise code evidence")
    expect(screen.getByTestId("github-location")).toHaveTextContent("api.py · predict()")
    expect(screen.getByTestId("github-snippet")).toHaveTextContent("def predict")
    const link = screen.getByTestId("evidence-public-link")
    expect(link).toHaveTextContent("View code lines →")
    expect(link).toHaveAttribute("href", expect.stringContaining("#L252-L255"))
  })

  it("renders weak/repo-level evidence with a 'Repo-level support only' badge and 'View repository' link", () => {
    render(
      <SkillReportView
        report={skillReport({
          github: [],
          standalone_evidence: { ...emptyStandalone(), github: [{ ...REPO_LEVEL_MODE_ITEM }] },
        })}
      />,
    )
    expect(screen.getByTestId("github-repo-level-badge")).toHaveTextContent("Repo-level support only")
    // No precise-proof affordances: no location, no snippet, no code-line link.
    expect(screen.queryByTestId("github-location")).not.toBeInTheDocument()
    expect(screen.queryByTestId("github-snippet")).not.toBeInTheDocument()
    expect(screen.queryByTestId("github-precise-badge")).not.toBeInTheDocument()
    const link = screen.getByTestId("evidence-public-link")
    expect(link).toHaveTextContent("View repository →")
    expect(link).toHaveAttribute("href", "https://github.com/octocat/Hello-World")
    // The honest repo-level limitation is shown.
    expect(screen.getByText(/Repository-level evidence only/i)).toBeInTheDocument()
  })
})

// ── Canonical GitHub skill evidence (old Profile & Proof engine) ────────────────

describe("SkillReportView — canonical skill_evidence GitHub fields", () => {
  const CANONICAL_ITEM: SkillReport["github"][number] = {
    ...GITHUB_ITEM,
    source_id: "se-1",
    safe_location: "app/api/routes.py · lines 12-30",
    safe_snippet: null, // canonical rows store no raw snippet
    file_path: "app/api/routes.py",
    line_start: 12,
    line_end: 30,
    function_name: null,
    display_mode: "code_line",
    has_precise_line_evidence: true,
    evidence_strength: "strong",
    evidence_kind: "portfolio_skill_evidence",
    selection_reason: "API endpoint decorator",
    subskill_name: "API Route",
    github_line_url: "https://github.com/octocat/Hello-World/blob/main/app/api/routes.py#L12-L30",
    repo_url: "https://github.com/octocat/Hello-World",
    public_url: "https://github.com/octocat/Hello-World/blob/main/app/api/routes.py#L12-L30",
  }

  it("renders precise file/line, the selection reason, subskill, and a 'View code lines' link", () => {
    render(
      <SkillReportView
        report={skillReport({
          github: [],
          standalone_evidence: { ...emptyStandalone(), github: [{ ...CANONICAL_ITEM }] },
        })}
      />,
    )
    expect(screen.getByTestId("github-precise-badge")).toHaveTextContent("Precise code evidence")
    expect(screen.getByTestId("github-location")).toHaveTextContent("app/api/routes.py · lines 12-30")
    expect(screen.getByTestId("github-selection-reason")).toHaveTextContent("API endpoint decorator")
    expect(screen.getByTestId("github-subskill")).toHaveTextContent("API Route")
    const link = screen.getByTestId("evidence-public-link")
    expect(link).toHaveTextContent("View code lines →")
    expect(link).toHaveAttribute("href", expect.stringContaining("#L12-L30"))
  })

  it("keeps document corroboration BELOW the canonical GitHub evidence in a chain", () => {
    const report = skillReport({
      github: [],
      standalone_evidence: emptyStandalone(),
      projects: [
        {
          project_id: "proj-1",
          project_title: "Boston Smart Rerouting",
          attached: true,
          attached_status: "Attached to a VBR project",
          sources: ["GitHub Proof", "Document Proof"],
          evidence_chain_summary: "GitHub code and a corroborating document.",
          github_evidence: [{ ...CANONICAL_ITEM, is_attached_to_project: true, attached_project_ids: ["proj-1"] }],
          website_evidence: [],
          document_correlations: [
            {
              source_id: "doc-1",
              document_title: "Boston Report",
              page_number: 2,
              section_label: null,
              citation: null,
              safe_snippet: "API design notes.",
              corroborates: "GitHub implementation",
              correlation_confidence: "direct attachment",
              support_label: "Supporting evidence",
              reason: "Describes the API design.",
              limitation: "Document supports the claim but does not independently prove implementation.",
            },
          ],
          document_more_count: 0,
          defense_evidence: [],
          video_evidence: [],
          limitations: [],
        },
      ],
    })
    const { container } = render(<SkillReportView report={report} />)
    const html = container.innerHTML
    // The precise GitHub badge appears before the Document corroboration block.
    expect(html.indexOf("Precise code evidence")).toBeLessThan(html.indexOf("Document corroboration"))
    expect(screen.getByTestId("document-corroborates")).toHaveTextContent("GitHub implementation")
  })
})

// ── Grouped same-title project attempts show a small note ───────────────────────

describe("SkillReportView — grouped same-title project attempts", () => {
  it("renders a 'related project attempts grouped' note when the backend grouped attempts", () => {
    const report = skillReport({
      github: [],
      standalone_evidence: emptyStandalone(),
      projects: [
        {
          project_id: "proj-1",
          project_title: "Boston Smart Accident Risk Rerouting",
          attached: true,
          attached_status: "Attached to a VBR project",
          sources: ["GitHub Proof", "Document Proof"],
          evidence_chain_summary: "Boston is supported by GitHub code and document corroboration.",
          github_evidence: [{ ...GITHUB_ITEM, is_attached_to_project: true, attached_project_ids: ["proj-1"] }],
          website_evidence: [],
          document_correlations: [
            {
              source_id: "doc-1",
              document_title: "Boston Report",
              page_number: 2,
              section_label: null,
              citation: null,
              safe_snippet: "ML pipeline.",
              corroborates: "GitHub implementation",
              correlation_confidence: "direct attachment",
              support_label: "Supporting evidence",
              reason: "Describes the ML pipeline.",
              limitation: "Document supports the claim but does not independently prove implementation.",
            },
          ],
          document_more_count: 0,
          defense_evidence: [],
          video_evidence: [],
          limitations: ["3 related project attempts grouped."],
          grouped_attempt_count: 3,
          grouped_project_ids: ["proj-1", "proj-2", "proj-3"],
        },
      ],
    })
    render(<SkillReportView report={report} />)
    expect(screen.getByTestId("chain-grouped-note")).toHaveTextContent("3 related project attempts grouped")
    // Document corroboration is shown once, not repeated per grouped attempt.
    expect(screen.getAllByTestId("document-correlation")).toHaveLength(1)
  })
})

// ── Collapsed duplicate project chains show a small note ────────────────────────

describe("SkillReportView — collapsed duplicate project chains", () => {
  it("renders a collapsed-attempts note when the backend collapsed duplicates", () => {
    const report = skillReport({
      github: [],
      standalone_evidence: emptyStandalone(),
      projects: [
        {
          project_id: "proj-1",
          project_title: "Boston Smart Accident Risk Rerouting",
          attached: true,
          attached_status: "Attached to a VBR project",
          sources: ["GitHub Proof", "Document Proof"],
          evidence_chain_summary: "Boston is supported by GitHub code and document corroboration.",
          github_evidence: [{ ...GITHUB_ITEM, is_attached_to_project: true, attached_project_ids: ["proj-1"] }],
          website_evidence: [],
          document_correlations: [
            {
              source_id: "doc-1",
              document_title: "Boston Report",
              page_number: 2,
              section_label: null,
              citation: null,
              safe_snippet: "ML pipeline.",
              corroborates: "GitHub implementation",
              correlation_confidence: "direct attachment",
              support_label: "Supporting evidence",
              reason: "Describes the ML pipeline.",
              limitation: "Document supports the claim but does not independently prove implementation.",
            },
          ],
          document_more_count: 0,
          defense_evidence: [],
          video_evidence: [],
          limitations: ["Repeated project attempts collapsed: 3 VBR project rows share this same proof package."],
          collapsed_project_count: 3,
          collapsed_project_ids: ["proj-1", "proj-2", "proj-3"],
        },
      ],
    })
    render(<SkillReportView report={report} />)
    expect(screen.getByTestId("chain-collapsed-note")).toHaveTextContent("3 repeated attempts collapsed")
    // The document corroboration shows its supporting label + confidence.
    expect(screen.getByTestId("document-confidence")).toHaveTextContent("direct attachment")
    // Exactly one document corroboration card — not repeated per duplicate row.
    expect(screen.getAllByTestId("document-correlation")).toHaveLength(1)
  })
})

// ── Proof Synthesis Agent: connected chains, tiers, unlinked support ───────────

describe("SkillReportView — Proof Synthesis Agent", () => {
  function synthesisReport(): SkillReport {
    const chain: SkillReport["projects"][number] = {
      project_id: "proj-1",
      project_title: "Boston Smart Accident Risk Rerouting",
      attached: true,
      attached_status: "Attached to a VBR project",
      sources: ["GitHub Proof", "Website Proof", "Document Proof", "Project Defense"],
      evidence_chain_summary: "Boston is supported by GitHub code, a live workflow, defense and a document.",
      confidence_tier: "Strongly corroborated",
      synthesis_result:
        "In Boston Smart Accident Risk Rerouting, GitHub Proof, Website Proof and Project Defense independently corroborate Python (strongly corroborated).",
      why_linked: "These sources are connected because they belong to the same project, “Boston”.",
      subskills: ["API Route"],
      synthesis_statements: [
        { text: "GitHub code at api.py shows the prediction endpoint.", source: "GitHub Proof", evidence_ids: ["gh-1"] },
      ],
      github_evidence: [{ ...GITHUB_ITEM, is_attached_to_project: true, attached_project_ids: ["proj-1"] }],
      website_evidence: [
        {
          proof_type: "Website Proof",
          source_id: "ws-1",
          title: "https://demo.example.com",
          safe_summary: "",
          safe_location: "demo.example.com",
          public_safe: true,
          is_attached_to_project: true,
          attached_project_ids: ["proj-1"],
          project_titles: [],
          limitation: "Confirms observed behaviour at inspection time.",
          workflow_summary: "User submitted route data and received a risk prediction.",
          workflow_steps: ["Submit route", "Receive prediction"],
        },
      ],
      document_correlations: [
        {
          source_id: "doc-1",
          document_title: "Boston — Final Report",
          page_number: 5,
          section_label: "Methodology",
          citation: "Methodology",
          safe_snippet: "The model endpoint serves predictions.",
          corroborates: "GitHub implementation",
          correlation_confidence: "direct attachment",
          support_label: "Supporting evidence",
          reason: "Describes the same ML model endpoint.",
          limitation: "Document supports the claim but does not independently prove implementation.",
        },
      ],
      document_more_count: 0,
      defense_evidence: [
        {
          proof_type: "Project Defense",
          source_id: "dfn-1",
          title: "Project Defense",
          safe_summary: "The candidate explained the prediction route.",
          safe_location: "overall explanation",
          public_safe: false,
          is_attached_to_project: true,
          attached_project_ids: ["proj-1"],
          project_titles: [],
          limitation: "Self-explanation evidence.",
          workflow_steps: [],
        },
      ],
      video_evidence: [],
      limitations: [],
    }
    return skillReport({
      github: [],
      standalone_evidence: emptyStandalone(),
      projects: [chain],
      proof_chains: [chain],
      synthesis_summary: "Python is supported by 1 connected proof chain; the strongest is strongly corroborated.",
      source_coverage: { GitHub: true, Website: true, Document: true, Defense: true, Video: false },
      unlinked_supporting_evidence: {
        count: 3,
        more_count: 1,
        items: [
          { proof_type: "Document Proof", source_id: "u1", title: "Loose Memo", safe_summary: "Unrelated note.", safe_location: "Page 2", corroborates: "Project architecture", limitation: "" },
          { proof_type: "Website Proof", source_id: "u2", title: "https://other.example.com", safe_summary: "A separate deployment.", safe_location: "other.example.com", corroborates: "", limitation: "" },
        ],
      },
    })
  }

  it("renders a connected chain with confidence tier, synthesis result and grouped evidence", () => {
    render(<SkillReportView report={synthesisReport()} />)
    expect(screen.getByTestId("skill-report-synthesis-summary")).toHaveTextContent("strongly corroborated")
    expect(screen.getByTestId("chain-confidence-tier")).toHaveTextContent("Strongly corroborated")
    expect(screen.getByTestId("chain-synthesis-result")).toHaveTextContent("independently corroborate")
    expect(screen.getByTestId("chain-why-linked")).toHaveTextContent("same project")
    // Code implementation + runtime behavior + defense explanation + document corroboration.
    expect(screen.getByTestId("chain-github")).toHaveTextContent("Code implementation")
    expect(screen.getByTestId("chain-website")).toHaveTextContent("Runtime / website behavior")
    expect(screen.getByTestId("website-workflow")).toHaveTextContent("risk prediction")
    expect(screen.getByTestId("chain-defense")).toHaveTextContent("Defense / video explanation")
    expect(screen.getByTestId("document-corroborates")).toHaveTextContent("GitHub implementation")
    expect(screen.getByTestId("chain-subskill")).toHaveTextContent("API Route")
  })

  it("collapses repeated Project Defense evidence into one grouped section", () => {
    const report = synthesisReport()
    const chain = (report.proof_chains ?? report.projects)![0]
    chain.defense_group = {
      explanation: "The candidate explained the model training and prediction route.",
      grouped_count: 3,
      limitation: "Self-explanation evidence; should be combined with artifact evidence.",
      source_ids: ["dfn-1", "vid-1", "vid-2"],
      moments: [
        { label: "Explains training loop", timestamp_label: "01:20", question_text: null, short_summary: "Walks through model.fit.", source_id: "vid-1" },
        { label: "Explains prediction", timestamp_label: "02:05", question_text: null, short_summary: "Shows the predict endpoint.", source_id: "vid-2" },
      ],
    }
    render(<SkillReportView report={report} />)
    const defense = screen.getByTestId("chain-defense")
    expect(defense).toHaveTextContent("Defense / video explanation")
    expect(screen.getByTestId("defense-grouped-count")).toHaveTextContent("3 defense moments grouped")
    expect(screen.getByTestId("defense-explanation")).toHaveTextContent("training and prediction route")
    // Only ONE grouped section — never repeated near-identical cards.
    expect(screen.getAllByTestId("chain-defense")).toHaveLength(1)
    expect(screen.getAllByTestId("defense-moment")).toHaveLength(2)
    expect(defense).toHaveTextContent("01:20")
  })

  it("renders source-coverage badges across the five surfaces", () => {
    render(<SkillReportView report={synthesisReport()} />)
    const coverage = screen.getByTestId("skill-report-coverage")
    expect(coverage).toHaveTextContent("GitHub: ✓")
    expect(coverage).toHaveTextContent("Video: —")
  })

  it("renders unlinked supporting evidence separately, capped with a +N more note", () => {
    render(<SkillReportView report={synthesisReport()} />)
    const unlinked = screen.getByTestId("skill-report-unlinked")
    expect(unlinked).toHaveTextContent("Unlinked supporting evidence")
    expect(screen.getAllByTestId("unlinked-evidence")).toHaveLength(2)
    expect(screen.getByTestId("unlinked-more")).toHaveTextContent("+1 more supporting proof")
    // The unrelated proofs are NOT inside the strong chain.
    const chain = screen.getByTestId("skill-report-chain")
    expect(chain).not.toHaveTextContent("Loose Memo")
  })

  it("never renders a raw proof dump (no forbidden raw fields)", () => {
    const { container } = render(<SkillReportView report={synthesisReport()} />)
    const html = container.innerHTML
    expect(html).not.toContain("analysis_snapshot")
    expect(html).not.toContain("raw_dump")
    expect(html).not.toContain("/storage/v1/object")
  })

  it("renders chain synthesis statements with audit citation chips (never raw ids)", () => {
    const { container } = render(<SkillReportView report={synthesisReport()} />)
    // The chain's evidence-cited statement renders with its citation chips.
    expect(screen.getByTestId("chain-synthesis-statement")).toHaveTextContent("prediction endpoint")
    const chips = screen.getAllByTestId("evidence-citation-chip")
    expect(chips.length).toBeGreaterThan(0)
    // The "gh-1" statement resolves to the chain's GitHub item location, not a raw id.
    expect(chips[0]).toHaveAttribute("data-source-type", "github")
    expect(container.innerHTML).not.toContain(">gh-1<")
  })
})

// ── Legacy unlinked/standalone dedupe without source_id ────────────────────────

describe("SkillReportView — legacy unlinked/standalone dedupe", () => {
  function legacyReport(): SkillReport {
    // A legacy GitHub proof with NO stable source_id, present in BOTH the
    // standalone section and the derived unlinked bucket.
    const legacyGithub: SkillReport["github"][number] = {
      proof_type: "GitHub Proof",
      source_id: "",
      title: "legacy/repo",
      safe_summary: "Legacy repository analyzed.",
      safe_location: "old.py · lines 1-9",
      public_safe: true,
      is_attached_to_project: false,
      attached_project_ids: [],
      project_titles: [],
      limitation: "",
      file_path: "old.py",
      line_start: 1,
      line_end: 9,
      workflow_steps: [],
    }
    return skillReport({
      github: [],
      projects: [],
      proof_chains: [],
      standalone_evidence: {
        ...emptyStandalone(),
        github: [legacyGithub],
        github_groups: [
          {
            repo_label: "legacy/repo",
            repo_url: null,
            repo_is_public: false,
            rows: [{ source_id: "", label: "old.py · lines 1-9", file_path: "old.py", line_start: 1, line_end: 9 }],
            row_more_count: 0,
          },
        ],
      },
      unlinked_supporting_evidence: {
        count: 2,
        more_count: 0,
        items: [
          // Same proof as the standalone GitHub item (no source_id) — must dedupe.
          { proof_type: "GitHub Proof", source_id: "", title: "legacy/repo", safe_summary: "Legacy repository analyzed.", safe_location: "old.py · lines 1-9", corroborates: "", limitation: "" },
          // A genuinely distinct legacy proof (no source_id) — must stay visible.
          { proof_type: "Website Proof", source_id: "", title: "https://distinct.example.com", safe_summary: "A genuinely distinct deployment.", safe_location: "distinct.example.com", corroborates: "", limitation: "" },
        ],
      },
    })
  }

  it("renders legacy evidence once (standalone), not duplicated in the unlinked bucket", () => {
    render(<SkillReportView report={legacyReport()} />)
    // Shown once — in the canonical standalone section.
    const standalone = screen.getByTestId("skill-report-standalone")
    expect(standalone).toHaveTextContent("old.py")
    // Excluded from the unlinked bucket (deduped by normalized fallback identity).
    const unlinked = screen.getByTestId("skill-report-unlinked")
    expect(unlinked).not.toHaveTextContent("legacy/repo")
    // The genuinely distinct legacy proof remains visible.
    expect(screen.getAllByTestId("unlinked-evidence")).toHaveLength(1)
    expect(unlinked).toHaveTextContent("distinct.example.com")
  })
})

// ── VeriBridge synthesis claims (Step 4) + empty states ────────────────────────

describe("SkillReportView — VeriBridge synthesis claims", () => {
  function reportWithSynthesis(): SkillReport {
    return skillReport({
      github: [],
      standalone_evidence: emptyStandalone(),
      linked_proof_chains: [
        {
          chain_id: "c1",
          project_title: "Boston Smart Accident Risk Rerouting",
          canonical_skill_name: "Python",
          chain_label: "Python in Boston",
          linked_evidence_ids: ["ev_a", "ev_b"],
          source_types_present: ["github", "website"],
          primary_source_type: "github",
          connection_reasons: ["Same project"],
          proof_strength_summary: {
            label: "Implementation proven by precise code",
            strengths_present: ["precise_code", "runtime_behavior"],
            has_precise_code: true,
            has_runtime_behavior: true,
            has_self_explanation: false,
            has_supporting_moment: false,
            repo_level_only: false,
            corroborating_document_count: 0,
          },
          limitations: [],
          public_safe: true,
          evidence: [
            { evidence_id: "ev_a", source_type: "github", source_label: "GitHub", exact_location: "api.py · predict()", safe_summary: "", proof_strength: "precise_code" },
            { evidence_id: "ev_b", source_type: "website", source_label: "Website", exact_location: "demo.example.com", safe_summary: "", proof_strength: "runtime_behavior" },
          ],
        },
      ],
      llm_synthesis: [
        {
          chain_id: "c1",
          skill_name: "Python",
          canonical_skill_name: "Python",
          project_title: "Boston Smart Accident Risk Rerouting",
          overall_summary: "GitHub code and a live workflow corroborate Python.",
          limitations: ["Workflow confirmed only at inspection time."],
          public_safe: true,
          source: "deterministic",
          claims: [
            {
              claim_id: "cl1",
              claim: "The candidate implemented the prediction endpoint and demonstrated it live.",
              supporting_evidence_ids: ["ev_a", "ev_b"],
              why_connected: "Both reference the same prediction route.",
              limitations: [],
              qualitative_tier: "Strongly corroborated",
              public_safe: true,
            },
          ],
        },
      ],
    })
  }

  it("collapses the big 'synthesis says' wall into ONE compact agent summary (no repeated claim cards)", () => {
    render(<SkillReportView report={reportWithSynthesis()} />)
    const section = screen.getByTestId("skill-report-synthesis")
    // The large "What VeriBridge synthesis says" claim-card section is gone — it
    // is now a short, recruiter-facing agent summary block.
    expect(section).toHaveTextContent("VeriBridge agent summary")
    expect(screen.getByTestId("skill-report-agent-summary")).toHaveTextContent(
      "GitHub code and a live workflow corroborate Python.",
    )
    // The duplicate per-claim cards (and their repeated limitations / GitHub
    // citation chips) are no longer rendered in this section.
    expect(screen.queryByTestId("synthesis-claim")).not.toBeInTheDocument()
    expect(screen.queryByTestId("synthesis-claim-tier")).not.toBeInTheDocument()
  })

  it("never exposes the raw ev_ ids or any score-like language", () => {
    const { container } = render(<SkillReportView report={reportWithSynthesis()} />)
    const html = container.innerHTML
    expect(html).not.toContain("ev_a")
    expect(html).not.toContain("ev_b")
    expect(html).not.toMatch(/\d+%/)
    expect(html).not.toMatch(/trust score|fully verified|ranked/i)
  })

  it("withholds the agent summary in public-safe mode when no result is public-safe", () => {
    const report = reportWithSynthesis()
    report.llm_synthesis![0].public_safe = false
    report.llm_synthesis![0].claims[0].public_safe = false
    render(<SkillReportView report={report} publicSafe />)
    expect(screen.queryByTestId("skill-report-agent-summary")).not.toBeInTheDocument()
    // Honest withheld state — the synthesis exists but isn't public-safe.
    expect(screen.getByTestId("skill-report-synthesis-withheld")).toHaveTextContent("not public-safe")
  })

  it("hides the synthesis section entirely when there is no chain or synthesis", () => {
    render(<SkillReportView report={skillReport({ projects: [], proof_chains: [], standalone_evidence: emptyStandalone(), github: [], llm_synthesis: [] })} />)
    expect(screen.getByTestId("skill-report-chains-empty")).toHaveTextContent("No linked proof chain yet")
    // No synthesis ⇒ the compact agent-summary section is omitted (not an empty card).
    expect(screen.queryByTestId("skill-report-synthesis")).not.toBeInTheDocument()
  })
})

// ── Standalone GitHub evidence grouped by repository (no repeated cards) ────────

describe("SkillReportView — standalone GitHub grouped by repository", () => {
  function groupedStandalone(): SkillReport["standalone_evidence"] {
    return {
      ...emptyStandalone(),
      // Back-compat flat list still present, but the UI must render the grouped
      // projection so multiple lines from one repo are not repeated full cards.
      github: [],
      github_groups: [
        {
          repo_label: "Stroke Prediction Model",
          repo_url: "https://github.com/alice/stroke-prediction",
          repo_is_public: true,
          row_more_count: 0,
          rows: [
            { source_id: "g1", label: "Tree.py · lines 13-72", file_path: "Tree.py", line_start: 13, line_end: 72, selection_reason: "ML training call", github_line_url: "https://github.com/alice/stroke-prediction/blob/main/Tree.py#L13-L72" },
            { source_id: "g2", label: "retrain_tree.py · lines 87-105", file_path: "retrain_tree.py", line_start: 87, line_end: 105, selection_reason: "model instantiation", github_line_url: "https://github.com/alice/stroke-prediction/blob/main/retrain_tree.py#L87-L105" },
          ],
        },
      ],
    }
  }

  it("renders ONE compact repository group with code-line rows, not one full card per line", () => {
    render(<SkillReportView report={skillReport({ projects: [], proof_chains: [], github: [], standalone_evidence: groupedStandalone() })} />)
    const groups = screen.getAllByTestId("standalone-github-group")
    expect(groups).toHaveLength(1)
    expect(groups[0]).toHaveAttribute("data-repo", "Stroke Prediction Model")
    // Compact rows, never full SkillEvidenceItem cards for the grouped lines.
    const rows = screen.getAllByTestId("standalone-github-row")
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent("Tree.py · lines 13-72")
    expect(rows[0]).toHaveTextContent("ML training call")
    expect(screen.queryByTestId("skill-evidence-item")).not.toBeInTheDocument()
  })

  it("expands and collapses '+N more code locations' inline (rows present in payload)", () => {
    const standalone: SkillReport["standalone_evidence"] = {
      ...emptyStandalone(),
      github: [],
      github_groups: [
        {
          repo_label: "Stroke Prediction Model",
          repo_url: "https://github.com/alice/stroke-prediction",
          repo_is_public: true,
          // Two collapsed rows beyond the visible window, still carried in `rows`.
          row_more_count: 2,
          rows: [
            { source_id: "v1", label: "train.py · train_model()", file_path: "train.py", function_name: "train_model", selection_reason: "ML training call", github_line_url: "https://github.com/alice/stroke-prediction/blob/main/train.py#L1-L9" },
            { source_id: "h1", label: "extra1.py · lines 1-5", file_path: "extra1.py", line_start: 1, line_end: 5, selection_reason: "model instantiation", github_line_url: "https://github.com/alice/stroke-prediction/blob/main/extra1.py#L1-L5" },
            { source_id: "h2", label: "extra2.py · lines 1-5", file_path: "extra2.py", line_start: 1, line_end: 5, selection_reason: "evaluation metrics", github_line_url: "https://github.com/alice/stroke-prediction/blob/main/extra2.py#L1-L5" },
          ],
        },
      ],
    }
    render(<SkillReportView report={skillReport({ projects: [], proof_chains: [], github: [], standalone_evidence: standalone })} />)
    // Collapsed: only the first (visible) row shows; overflow rows are hidden.
    expect(screen.getAllByTestId("standalone-github-row")).toHaveLength(1)
    expect(screen.queryByText("extra2.py · lines 1-5")).not.toBeInTheDocument()
    const toggle = screen.getByTestId("standalone-github-more")
    expect(toggle).toHaveTextContent("+2 more code locations")
    expect(toggle).toHaveAttribute("aria-expanded", "false")
    // Expand → all rows + their safe "View code lines" links appear.
    fireEvent.click(toggle)
    expect(screen.getAllByTestId("standalone-github-row")).toHaveLength(3)
    expect(screen.getByText("extra2.py · lines 1-5")).toBeInTheDocument()
    expect(toggle).toHaveAttribute("aria-expanded", "true")
    expect(toggle).toHaveTextContent("Show fewer code locations")
    const revealedLink = screen
      .getAllByTestId("evidence-public-link")
      .find((a) => a.getAttribute("href")?.includes("extra2.py"))
    expect(revealedLink).toBeTruthy()
    // Collapse again → back to a single visible row.
    fireEvent.click(toggle)
    expect(screen.getAllByTestId("standalone-github-row")).toHaveLength(1)
  })

  it("does not render an interactive '+N more' control when no rows are collapsed", () => {
    render(<SkillReportView report={skillReport({ projects: [], proof_chains: [], github: [], standalone_evidence: groupedStandalone() })} />)
    expect(screen.queryByTestId("standalone-github-more")).not.toBeInTheDocument()
  })

  it("links a public standalone repo once and never duplicates the rows as cards", () => {
    render(<SkillReportView report={skillReport({ projects: [], proof_chains: [], github: [], standalone_evidence: groupedStandalone() })} />)
    const repoLink = screen
      .getAllByTestId("evidence-public-link")
      .find((a) => a.getAttribute("href") === "https://github.com/alice/stroke-prediction")
    expect(repoLink).toBeTruthy()
  })

  it("does NOT render the same standalone evidence twice (unlinked excludes standalone)", () => {
    // The unlinked bucket is derived from the SAME standalone proofs; the same
    // GitHub evidence (source_id g1) must appear ONCE — in the canonical
    // standalone section, never also in "Unlinked supporting evidence".
    const report = skillReport({
      projects: [],
      proof_chains: [],
      github: [],
      standalone_evidence: groupedStandalone(),
      unlinked_supporting_evidence: {
        count: 1,
        more_count: 0,
        items: [
          { proof_type: "GitHub Proof", source_id: "g1", title: "Stroke Prediction Model", safe_summary: "Tree.py training.", safe_location: "Tree.py · lines 13-72", corroborates: "", limitation: "" },
        ],
      },
    })
    render(<SkillReportView report={report} />)
    // Standalone group still renders the grouped GitHub rows.
    expect(screen.getByTestId("standalone-github-group")).toHaveAttribute("data-repo", "Stroke Prediction Model")
    // The duplicate unlinked card (same source_id) is dropped → section absent.
    expect(screen.queryByTestId("skill-report-unlinked")).not.toBeInTheDocument()
    expect(screen.queryByTestId("unlinked-evidence")).not.toBeInTheDocument()
  })

  it("keeps truly unlinked non-standalone evidence in the unlinked section", () => {
    const report = skillReport({
      projects: [],
      proof_chains: [],
      github: [],
      standalone_evidence: groupedStandalone(),
      unlinked_supporting_evidence: {
        count: 1,
        more_count: 0,
        // A different source_id that is NOT in the standalone groups.
        items: [
          { proof_type: "Document Proof", source_id: "loose-1", title: "Loose Memo", safe_summary: "Unrelated note.", safe_location: "Page 2", corroborates: "Project architecture", limitation: "" },
        ],
      },
    })
    render(<SkillReportView report={report} />)
    expect(screen.getByTestId("skill-report-unlinked")).toHaveTextContent("Loose Memo")
  })
})

// ── Connected proof-chain GitHub uses the grouped repository model ──────────────

describe("SkillReportView — connected chain GitHub grouped by repository", () => {
  function connectedChain(): SkillReportProjectChain {
    return {
      project_id: "proj-1",
      project_title: "Boston Smart Accident Risk Rerouting",
      attached: true,
      attached_status: "Attached to a VBR project",
      sources: ["GitHub Proof"],
      evidence_chain_summary: "ML is supported by GitHub implementation.",
      github_evidence: [{ ...GITHUB_ITEM, source_id: "gh-boston", file_path: "api.py", function_name: "predict" }],
      github_groups: [
        {
          repo_label: "octocat/Hello-World",
          repo_url: "https://github.com/octocat/Hello-World",
          repo_is_public: true,
          row_more_count: 0,
          rows: [
            { source_id: "gh-boston", label: "api.py · predict()", file_path: "api.py", function_name: "predict", selection_reason: "prediction endpoint", github_line_url: "https://github.com/octocat/Hello-World/blob/main/api.py#L252-L255" },
          ],
        },
      ],
      website_evidence: [],
      document_correlations: [],
      document_more_count: 0,
      defense_evidence: [],
      video_evidence: [],
      limitations: [],
    }
  }

  it("renders connected GitHub through the grouped model (one repo block, compact rows)", () => {
    const chain = connectedChain()
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    const section = screen.getByTestId("chain-github")
    expect(section).toHaveTextContent("Code implementation")
    // Grouped block (attached) — not the standalone "not attached" variant.
    const group = screen.getByTestId("chain-github-group")
    expect(group).toHaveAttribute("data-repo", "octocat/Hello-World")
    expect(group).toHaveTextContent("Attached")
    const rows = screen.getAllByTestId("standalone-github-row")
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveTextContent("api.py · predict()")
    // No "not attached" badge on a connected chain group.
    expect(group).not.toHaveTextContent("Not attached to a VBR project")
  })

  it("renders ONE grouped block with MULTIPLE code rows (each with location, reason, link)", () => {
    const chain = connectedChain()
    chain.github_groups = [
      {
        repo_label: "octocat/Hello-World",
        repo_url: "https://github.com/octocat/Hello-World",
        repo_is_public: true,
        row_more_count: 0,
        rows: [
          { source_id: "g-train", label: "src/train.py · train_model()", file_path: "src/train.py", function_name: "train_model", selection_reason: "Analyzer located function evidence for Machine Learning in src/train.py (lines 10-14).", github_line_url: "https://github.com/octocat/Hello-World/blob/main/src/train.py#L10-L14" },
          { source_id: "g-prep", label: "src/preprocess.py · prepare_features()", file_path: "src/preprocess.py", function_name: "prepare_features", selection_reason: "Analyzer located function evidence for Machine Learning in src/preprocess.py (lines 20-24).", github_line_url: "https://github.com/octocat/Hello-World/blob/main/src/preprocess.py#L20-L24" },
          { source_id: "g-pred", label: "api.py · predict()", file_path: "api.py", function_name: "predict", selection_reason: "Analyzer located function evidence for Machine Learning in api.py (lines 40-44).", github_line_url: "https://github.com/octocat/Hello-World/blob/main/api.py#L40-L44" },
        ],
      },
    ]
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    // ONE repository group...
    expect(screen.getAllByTestId("chain-github-group")).toHaveLength(1)
    // ...with MULTIPLE code rows (not a single weak one-row card).
    const rows = screen.getAllByTestId("standalone-github-row")
    expect(rows).toHaveLength(3)
    expect(rows[0]).toHaveTextContent("src/train.py · train_model()")
    expect(rows[1]).toHaveTextContent("src/preprocess.py · prepare_features()")
    expect(rows[2]).toHaveTextContent("api.py · predict()")
    // Each row shows its selection reason and a safe "View code lines" link.
    expect(rows[0]).toHaveTextContent("Analyzer located function evidence")
    const links = screen.getAllByText("View code lines →")
    expect(links.length).toBeGreaterThanOrEqual(3)
  })

  it("never shows a contradictory 'No GitHub code evidence' note when github_groups exists", () => {
    const chain = connectedChain()
    // A stale derived limitation that the backend should have dropped post-merge;
    // even if present, it must not contradict the rendered GitHub groups.
    chain.limitations = ["3 related project attempts grouped."]
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    expect(screen.getByTestId("chain-github-group")).toBeInTheDocument()
    expect(screen.queryByText(/No GitHub code evidence/i)).not.toBeInTheDocument()
  })

  it("falls back to the flat per-item list when a chain has no github_groups", () => {
    const chain = { ...connectedChain(), github_groups: undefined }
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    const section = screen.getByTestId("chain-github")
    expect(section).toHaveTextContent("Code implementation")
    // Older payload → flat SkillEvidenceItem card, not a grouped block.
    expect(screen.getByTestId("skill-evidence-item")).toBeInTheDocument()
    expect(screen.queryByTestId("chain-github-group")).not.toBeInTheDocument()
  })
})

// ── Project report "Other student proofs" section ──────────────────────────────

describe("ProjectReportView — Other student proofs", () => {
  it("renders a COMPACT other-student-proofs list that links to the separate Skill Report", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(makeReport())

    render(<ProjectReportView projectId="proj-1" />)

    expect(await screen.findByTestId("other-student-proofs")).toBeInTheDocument()
    expect(screen.getByText(/Other Student Proofs for Related Skills/i)).toBeInTheDocument()
    // Compact: a skill row labelled not-attached, with a link to the Skill Report.
    expect(screen.getByTestId("vault-skill-link-list")).toBeInTheDocument()
    expect(screen.getByTestId("vault-unattached-badge")).toBeInTheDocument()
    expect(screen.getByTestId("other-proof-skill-report-link")).toHaveAttribute(
      "href",
      "/student/vbr/passport/skills/python",
    )
    // It does NOT dump the full per-proof evidence cards inline.
    expect(screen.queryByTestId("vault-proof")).not.toBeInTheDocument()
  })

  it("omits the section when there are no cross-proof matches", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(makeReport({ other_student_proofs: [] }))

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skill Evidence Tracker")
    expect(screen.queryByTestId("other-student-proofs")).not.toBeInTheDocument()
  })
})

// ── VaultProofList component (safe metadata rendering) ──────────────────────────

describe("VaultProofList", () => {
  it("renders proof metadata safely and never raw evidence", () => {
    render(<VaultProofList groups={[vaultGroup()]} />)
    expect(screen.getByTestId("vault-proof-location")).toHaveTextContent("demo.example.com")
    expect(screen.getByText(/A working deployment was inspected/)).toBeInTheDocument()
    // No raw snippet rendered when none is present.
    expect(screen.queryByTestId("vault-proof-snippet")).not.toBeInTheDocument()
  })

  it("renders nothing for empty groups", () => {
    const { container } = render(<VaultProofList groups={[]} />)
    expect(container).toBeEmptyDOMElement()
  })
})

// ── Public passport stays free of private vault structure ───────────────────────

function makePublicPassport(overrides: Partial<PublicWorkPassport> = {}): PublicWorkPassport {
  return {
    candidate_display_name: "Jordan Rivera",
    headline: "Full-stack builder",
    summary: "I ship and defend real projects.",
    top_skills: [
      { skill: "Python", status: "Demonstrated", evidence_sources: ["GitHub Proof"], projects: [], evidence_chips: [], limitations: [] },
    ],
    featured_projects: [],
    evidence_source_counts: {},
    featured_project_count: 0,
    limitations: [],
    published_at: "2026-01-02T00:00:00Z",
    generated_at: "2026-01-02T00:00:00Z",
    verification_note: "Candidate-published.",
    ...overrides,
  }
}

describe("PublicPassportView — no private vault", () => {
  it("never renders the private proof-vault structure", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())
    render(<PublicPassportView slug="abc" />)
    // Wait for the candidate header to confirm the passport rendered.
    expect(await screen.findByText("Jordan Rivera")).toBeInTheDocument()
    expect(screen.queryByTestId("vault-proof-list")).not.toBeInTheDocument()
    expect(screen.queryByTestId("vault-proof")).not.toBeInTheDocument()
    expect(screen.queryByTestId("vault-unattached-badge")).not.toBeInTheDocument()
  })
})
