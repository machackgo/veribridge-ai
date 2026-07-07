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

import { ProofVaultView } from "../app/student/vbr/passport/vault/ProofVaultView"
import { ProjectReportView } from "../app/student/vbr/projects/[projectId]/report/ProjectReportView"
import { PublicPassportView } from "../app/p/[slug]/PublicPassportView"
import { SkillReportPageView } from "../app/student/vbr/passport/skills/[skillSlug]/SkillReportView"
import { SkillReportView, VaultProofList } from "../../components/passport/VaultProofs"
import type {
  PrivateWorkPassport,
  PublicWorkPassport,
  SkillReport,
  SkillReportProjectChain,
  SkillReportStandaloneGitHubRow,
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
  PROOF_SOURCE_RELATIONSHIP,
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

// The Skill Intelligence dashboard moved OUT of the main Passport into the
// private Proof Vault page, so it is exercised against ProofVaultView now.
describe("ProofVaultView — Skill Intelligence (compact dashboard)", () => {
  it("renders compact skill summary cards under category headings, not raw proof cards", async () => {
    const p = makePassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<ProofVaultView />)

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

    render(<ProofVaultView />)

    expect(await screen.findByTestId("vault-summary-unattached")).toHaveTextContent("not attached")
    expect(screen.getByTestId("vault-unattached-summary")).toHaveTextContent("1 unattached proof item")
  })

  it("links 'View Skill Report' to the SEPARATE skill report route — never inline", async () => {
    const p = makePassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<ProofVaultView />)

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

    render(<ProofVaultView />)
    await screen.findByTestId("vault-overview")
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

  function websiteSemanticItem(overrides: Record<string, unknown> = {}) {
    return {
      proof_type: "Website Proof",
      source_id: "sess-sem-1",
      title: "https://demo.example.com",
      safe_summary: "",
      safe_location: "demo.example.com",
      public_safe: true,
      is_attached_to_project: false,
      attached_project_ids: [],
      project_titles: [],
      limitation:
        "Website prediction/output demonstrates product behaviour at inspection time; it does not, by itself, prove model training or ML implementation.",
      workflow_summary: "Accident details were entered and a crash-risk prediction was displayed.",
      workflow_steps: [],
      public_url: "https://demo.example.com",
      website_purpose_key: "prediction_result_display",
      website_purpose_label: "Prediction / result display",
      website_purpose_summary:
        "The recorded session shows an input → prediction/result flow: values were entered and a computed result was displayed.",
      website_skill_relevance_key: "ml_product_context",
      website_skill_relevance_label:
        "Machine Learning product behaviour context — not Machine Learning implementation proof",
      website_skill_relevance_summary:
        "The website shows model-powered product behaviour; it does not, by itself, prove model training.",
      ...overrides,
    }
  }

  it("renders website purpose / skill-relevance labels and honest ML limitation", async () => {
    vi.mocked(getSkillReport).mockResolvedValue(
      skillReport({
        github: [],
        standalone_evidence: { ...emptyStandalone(), website: [websiteSemanticItem()] },
      }),
    )

    render(<SkillReportPageView skillSlug="machine-learning" />)

    expect(await screen.findByTestId("skill-report-website")).toBeInTheDocument()
    expect(screen.getByTestId("website-purpose-label")).toHaveTextContent("Prediction / result display")
    expect(screen.getByTestId("website-purpose-summary")).toHaveTextContent("prediction/result flow")
    // ML report: the relevance says product behaviour context — never implementation proof.
    expect(screen.getByTestId("website-skill-relevance")).toHaveTextContent(
      "not Machine Learning implementation proof",
    )
    expect(screen.getByText(/does not, by itself, prove model training/)).toBeInTheDocument()
    // The open-website link renders only the safe public URL.
    expect(screen.getByTestId("evidence-public-link")).toHaveAttribute("href", "https://demo.example.com")
  })

  it("renders direct Frontend relevance for a React report's website proof", async () => {
    vi.mocked(getSkillReport).mockResolvedValue(
      skillReport({
        github: [],
        standalone_evidence: {
          ...emptyStandalone(),
          website: [
            websiteSemanticItem({
              limitation:
                "Confirms observed behaviour at inspection time, not source-code authorship or ongoing uptime.",
              website_skill_relevance_key: "direct_frontend_evidence",
              website_skill_relevance_label: "Direct React evidence — interactive product UI demonstrated",
              website_skill_relevance_summary:
                "The recorded interactive UI behaviour is itself the subject of React.",
            }),
          ],
        },
      }),
    )

    render(<SkillReportPageView skillSlug="react" />)

    expect(await screen.findByTestId("skill-report-website")).toBeInTheDocument()
    expect(screen.getByTestId("website-skill-relevance")).toHaveTextContent("Direct React evidence")
  })

  function websiteEvidenceCard(overrides: Record<string, unknown> = {}) {
    return {
      card_key: "web-abc123def456",
      route_or_page: "demo.example.com/dashboard",
      page_title: "Risk Dashboard",
      observed_at: "2026-06-30",
      behavior_claim: "User input produces a prediction/result display.",
      website_purpose_key: "prediction_result_display",
      website_purpose_label: "Prediction / result display",
      website_purpose_summary:
        "The recorded session shows an input → prediction/result flow: values were entered and a computed result was displayed.",
      skill_relevance_key: "ml_product_context",
      skill_relevance_label:
        "Machine Learning product behaviour context — not Machine Learning implementation proof",
      skill_relevance_summary:
        "The website shows model-powered product behaviour; it does not, by itself, prove model training.",
      observed_behavior_summary: "Accident details were entered and a crash-risk prediction was displayed.",
      visual_evidence_summary:
        "Visual frame analysis of the recorded session is consistent with: Prediction / result display.",
      ocr_evidence_summary_safe: null,
      dom_evidence_summary_safe: null,
      evidence_basis_chips: ["Route observed", "Visual frame", "Workflow navigation", "Output / result visible"],
      limitation:
        "Website prediction/output demonstrates product behaviour at inspection time; it does not, by itself, prove model training or ML implementation.",
      verification_mode: "directly_verifiable_live",
      verification_mode_label: "Directly verifiable live",
      verification_note:
        "A public live URL is available, so a recruiter can open the site and inspect the current runtime/product behaviour directly. The recorded evidence below shows what VeriBridge observed during the proof session.",
      deployment_recommended: false,
      open_website_url: "https://demo.example.com",
      screenshot_available: true,
      screenshot_access_label: "private_candidate_permission_required",
      screenshot_preview_url: null,
      corroborates_github: false,
      corroborates_defense: false,
      corroborates_document: false,
      corroboration_note: null,
      connected_project_title: null,
      ...overrides,
    }
  }

  it("renders the Website Evidence Card: route, chips, permission-gated frame, safe link", async () => {
    vi.mocked(getSkillReport).mockResolvedValue(
      skillReport({
        github: [],
        standalone_evidence: {
          ...emptyStandalone(),
          website: [
            websiteSemanticItem({
              // Raw-ish hydrated summaries present on the item — the card view
              // must suppress them in favour of the structured card.
              ocr_summary: "RAW-OCR-TEXT",
              dom_summary: "RAW-DOM-TEXT",
              visual_summary: "RAW-VISUAL-TEXT",
              website_evidence_card: websiteEvidenceCard(),
            }),
          ],
        },
      }),
    )

    render(<SkillReportPageView skillSlug="machine-learning" />)

    expect(await screen.findByTestId("website-evidence-card")).toBeInTheDocument()
    expect(screen.getByTestId("website-card-route")).toHaveTextContent(
      "Website Behavior Evidence · demo.example.com/dashboard",
    )
    expect(screen.getByTestId("website-card-observed-at")).toHaveTextContent("observed 2026-06-30")
    // Claim-first: the recruiter reads WHAT behaviour was demonstrated first.
    expect(screen.getByTestId("website-behavior-claim")).toHaveTextContent(
      "Claim: User input produces a prediction/result display.",
    )
    expect(screen.getByTestId("website-purpose-label")).toHaveTextContent("Prediction / result display")
    // ML report: product behaviour context, never implementation proof.
    expect(screen.getByTestId("website-skill-relevance")).toHaveTextContent(
      "not Machine Learning implementation proof",
    )
    expect(screen.getByTestId("website-skill-relevance")).toHaveTextContent(/^Supports:/)
    // Standalone card: no corroboration line is invented.
    expect(screen.queryByTestId("website-corroboration")).not.toBeInTheDocument()
    // Evidence basis chips render from the closed vocabulary.
    const chips = screen.getAllByTestId("website-evidence-chip").map((c) => c.textContent)
    expect(chips).toEqual(["Route observed", "Visual frame", "Workflow navigation", "Output / result visible"])
    // Frames exist but are private → permission-gated status, never a link.
    expect(screen.getByTestId("website-screenshot-status")).toHaveTextContent(
      "available with candidate permission",
    )
    // The open-website link renders only the safe public URL.
    expect(screen.getByTestId("evidence-public-link")).toHaveAttribute("href", "https://demo.example.com")
    expect(screen.getByTestId("evidence-public-link")).toHaveTextContent("Open live website →")
    // GitHub-style inspection header: a public URL → directly verifiable live.
    expect(screen.getByTestId("website-inspection-title")).toHaveTextContent("Website Proof inspection")
    expect(screen.getByTestId("website-verification-mode")).toHaveTextContent("Directly verifiable live")
    expect(screen.getByTestId("website-verification-mode")).toHaveAttribute("data-mode", "live")
    expect(screen.getByTestId("website-open-live")).toBeInTheDocument()
    // Live-verifiable proof does not nag for a deployment.
    expect(screen.queryByTestId("website-deployment-recommended")).not.toBeInTheDocument()
    // Limitation renders via the item row.
    expect(screen.getByText(/does not, by itself, prove model training/)).toBeInTheDocument()
    // Raw hydrated payloads never render when the card is present.
    expect(screen.queryByTestId("website-ocr")).not.toBeInTheDocument()
    expect(screen.queryByTestId("website-dom")).not.toBeInTheDocument()
    expect(screen.queryByTestId("website-visual")).not.toBeInTheDocument()
    expect(screen.queryByText(/RAW-OCR-TEXT|RAW-DOM-TEXT|RAW-VISUAL-TEXT/)).not.toBeInTheDocument()
  })

  it("marks a local-only Website Proof as recorded replay only with no open-live CTA", async () => {
    vi.mocked(getSkillReport).mockResolvedValue(
      skillReport({
        github: [],
        standalone_evidence: {
          ...emptyStandalone(),
          website: [
            websiteSemanticItem({
              // Local/private capture — the backend already stripped the URL,
              // so no safe open URL survives and the card is replay-only.
              public_url: null,
              website_evidence_card: websiteEvidenceCard({
                verification_mode: "recorded_replay_only",
                verification_mode_label: "Recorded replay only",
                verification_note:
                  "This proof was captured from a local or non-public website, so a recruiter cannot open the original runtime URL directly. VeriBridge shows a recruiter-safe replay of the recorded website behaviour instead. Deploying the site to a public URL would allow direct recruiter verification.",
                deployment_recommended: true,
                open_website_url: null,
              }),
            }),
          ],
        },
      }),
    )

    render(<SkillReportPageView skillSlug="machine-learning" />)

    expect(await screen.findByTestId("website-evidence-card")).toBeInTheDocument()
    expect(screen.getByTestId("website-verification-mode")).toHaveTextContent("Recorded replay only")
    expect(screen.getByTestId("website-verification-mode")).toHaveAttribute("data-mode", "recorded")
    expect(screen.getByTestId("website-verification-note")).toHaveTextContent(/local or non-public website/)
    // No live URL → the recruiter cannot open localhost; no open-live CTA.
    expect(screen.queryByTestId("website-open-live")).not.toBeInTheDocument()
    // Deployment is recommended so a recruiter could verify directly.
    expect(screen.getByTestId("website-deployment-recommended")).toHaveTextContent(
      "Deployment recommended for direct recruiter verification",
    )
    // Frames still exist → permission-gated replay status is honest.
    expect(screen.getByTestId("website-screenshot-status")).toHaveTextContent(
      "available with candidate permission",
    )
  })

  it("groups safe visual/OCR/DOM findings under a Visual and page analysis heading", async () => {
    vi.mocked(getSkillReport).mockResolvedValue(
      skillReport({
        github: [],
        standalone_evidence: {
          ...emptyStandalone(),
          website: [
            websiteSemanticItem({
              website_evidence_card: websiteEvidenceCard({
                visual_evidence_summary:
                  "Visual frame analysis of the recorded session is consistent with: Prediction / result display.",
                ocr_evidence_summary_safe:
                  "Safe OCR summary indicates on-screen text consistent with: Prediction / result display.",
                dom_evidence_summary_safe:
                  "Safe DOM summary indicates page structure consistent with: Prediction / result display.",
              }),
            }),
          ],
        },
      }),
    )

    render(<SkillReportPageView skillSlug="machine-learning" />)

    const analysis = await screen.findByTestId("website-visual-page-analysis")
    expect(analysis).toHaveTextContent("Visual and page analysis")
    expect(screen.getByTestId("website-card-visual")).toHaveTextContent("Visual frame analysis")
    expect(screen.getByTestId("website-card-ocr")).toHaveTextContent("on-screen text consistent with")
    expect(screen.getByTestId("website-card-dom")).toHaveTextContent("page structure consistent with")
  })

  it("renders the evidence-frame link ONLY for a safe preview URL", async () => {
    vi.mocked(getSkillReport).mockResolvedValue(
      skillReport({
        github: [],
        standalone_evidence: {
          ...emptyStandalone(),
          website: [
            websiteSemanticItem({
              website_evidence_card: websiteEvidenceCard({
                screenshot_preview_url: "https://cdn.veribridge.app/frames/safe-frame.jpg",
                open_website_url: null,
              }),
            }),
          ],
        },
      }),
    )

    render(<SkillReportPageView skillSlug="machine-learning" />)

    expect(await screen.findByTestId("website-evidence-card")).toBeInTheDocument()
    // A safe preview URL upgrades the permission status to a real link.
    expect(screen.queryByTestId("website-screenshot-status")).not.toBeInTheDocument()
    expect(screen.getByText("View evidence frame →")).toHaveAttribute(
      "href",
      "https://cdn.veribridge.app/frames/safe-frame.jpg",
    )
  })

  it("never renders unsafe card URLs (frame or website)", async () => {
    vi.mocked(getSkillReport).mockResolvedValue(
      skillReport({
        github: [],
        standalone_evidence: {
          ...emptyStandalone(),
          website: [
            websiteSemanticItem({
              public_url: null,
              website_evidence_card: websiteEvidenceCard({
                screenshot_preview_url: "https://storage.internal/frame.jpg?sig=SECRET",
                open_website_url: "javascript:alert(1)",
              }),
            }),
          ],
        },
      }),
    )

    render(<SkillReportPageView skillSlug="machine-learning" />)

    expect(await screen.findByTestId("website-evidence-card")).toBeInTheDocument()
    // Unsafe preview URL → falls back to the permission-gated status; unsafe
    // open URL → no link at all.
    expect(screen.getByTestId("website-screenshot-status")).toBeInTheDocument()
    expect(screen.queryByText("View evidence frame →")).not.toBeInTheDocument()
    expect(screen.queryByTestId("evidence-public-link")).not.toBeInTheDocument()
  })

  it("shows direct Frontend evidence on the card for a React report", async () => {
    vi.mocked(getSkillReport).mockResolvedValue(
      skillReport({
        github: [],
        standalone_evidence: {
          ...emptyStandalone(),
          website: [
            websiteSemanticItem({
              website_evidence_card: websiteEvidenceCard({
                skill_relevance_key: "direct_frontend_evidence",
                skill_relevance_label: "Direct React evidence — interactive product UI demonstrated",
                screenshot_available: false,
                screenshot_access_label: "unavailable",
              }),
            }),
          ],
        },
      }),
    )

    render(<SkillReportPageView skillSlug="react" />)

    expect(await screen.findByTestId("website-evidence-card")).toBeInTheDocument()
    expect(screen.getByTestId("website-skill-relevance")).toHaveTextContent("Direct React evidence")
    // No frames → no status line and no frame link (fails safe, renders nothing).
    expect(screen.queryByTestId("website-screenshot-status")).not.toBeInTheDocument()
    expect(screen.queryByText("View evidence frame →")).not.toBeInTheDocument()
  })

  it("renders the cross-proof corroboration line and chips on a connected card", async () => {
    vi.mocked(getSkillReport).mockResolvedValue(
      skillReport({
        github: [],
        standalone_evidence: {
          ...emptyStandalone(),
          website: [
            websiteSemanticItem({
              website_evidence_card: websiteEvidenceCard({
                evidence_basis_chips: [
                  "Route observed",
                  "Output / result visible",
                  "Attached project",
                  "Corroborates GitHub",
                  "Corroborates Defense",
                ],
                corroborates_github: true,
                corroborates_defense: true,
                corroboration_note:
                  "GitHub provides implementation evidence for the same project; the candidate explained this behaviour in the Project Defense.",
                connected_project_title: "Boston Smart Accident Risk Rerouting",
              }),
            }),
          ],
        },
      }),
    )

    render(<SkillReportPageView skillSlug="machine-learning" />)

    expect(await screen.findByTestId("website-evidence-card")).toBeInTheDocument()
    expect(screen.getByTestId("website-corroboration")).toHaveTextContent(
      "Corroborates: GitHub provides implementation evidence for the same project",
    )
    expect(screen.getByTestId("website-corroboration")).toHaveTextContent("Project Defense")
    expect(screen.getByTestId("website-connected-project")).toHaveTextContent(
      "Boston Smart Accident Risk Rerouting",
    )
    const chips = screen.getAllByTestId("website-evidence-chip").map((c) => c.textContent)
    expect(chips).toContain("Corroborates GitHub")
    expect(chips).toContain("Corroborates Defense")
    expect(chips).toContain("Attached project")
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

// ── Project Defense inspection cards inside a proof chain ──────────────────────

describe("SkillReportView — Project Defense inspection", () => {
  function inspectionChainReport(inspectionOverrides = {}): SkillReport {
    return skillReport({
      github: [],
      standalone_evidence: emptyStandalone(),
      projects: [
        {
          project_id: "proj-1",
          project_title: "Boston Housing",
          attached: true,
          attached_status: "Attached to a VBR project",
          sources: ["Project Defense"],
          evidence_chain_summary: "Python is supported by the candidate's own defense explanation.",
          github_evidence: [],
          website_evidence: [],
          document_correlations: [],
          document_more_count: 0,
          defense_evidence: [],
          video_evidence: [],
          project_defense_inspection: [
            {
              evidence_id_safe: "defense-inspection-1",
              question_text: "How does your model make predictions?",
              question_kind: "skill_explanation",
              project_title: "Boston Housing",
              mapped_skill: "Python",
              claim_type: "skill_understanding",
              answer_purpose: "skill_explanation",
              evidence_role: "candidate_explanation",
              qualitative_status: "Explained with evidence",
              safe_answer_summary: "I trained a regression model and use it for inference on features.",
              evidence_basis_chips: ["Targeted question", "Candidate answer", "Privacy-safe summary"],
              timestamp_label: "Video 03:12",
              clip_start_seconds: 192.0,
              clip_end_seconds: 205.0,
              clip_available: true,
              corroborates_github: true,
              corroborates_website: false,
              corroborates_document: false,
              corroboration_summary: "Corroborating defense evidence: GitHub Proof (implementation) for the same project.",
              what_this_demonstrates: "The student explained this Python claim in their own words.",
              limitation: "Project Defense is explanation evidence. It should be read with GitHub Proof for implementation.",
              public_safe: true,
              withheld_reason: null,
              ...inspectionOverrides,
            },
          ],
          limitations: [],
        },
      ],
    })
  }

  it("renders the private inspection card with question, answer, skill, chips, timestamp, limitation", () => {
    render(<SkillReportView report={inspectionChainReport()} />)

    const card = screen.getByTestId("project-defense-inspection-card")
    expect(card).toBeInTheDocument()
    expect(screen.getByTestId("pdi-question")).toHaveTextContent("How does your model make predictions?")
    expect(screen.getByTestId("pdi-answer-summary")).toHaveTextContent("regression model")
    expect(screen.getByTestId("pdi-skill")).toHaveTextContent("Python")
    expect(screen.getByTestId("pdi-basis-chips")).toHaveTextContent("Targeted question")
    // The timestamp/clip locator renders only its safe label.
    expect(screen.getByTestId("pdi-timestamp")).toHaveTextContent("Video 03:12")
    // Corroboration chips + honest limitation framing.
    expect(screen.getByTestId("pdi-corroborates")).toHaveTextContent("GitHub")
    expect(screen.getByTestId("pdi-limitation")).toHaveTextContent("explanation evidence")
  })

  it("never renders raw transcript segments, storage paths, signed URLs, or internal ids", () => {
    // A safe, bounded transcript excerpt is allowed; the raw segments array,
    // storage paths, signed URLs, and internal ids are not.
    const { container } = render(
      <SkillReportView
        report={inspectionChainReport({
          transcript_excerpt_available: true,
          safe_transcript_excerpt: "I trained a regression model and validated features first.",
        })}
      />,
    )
    const html = container.innerHTML
    for (const unsafe of [
      "transcript_segments",
      "storage_path",
      "signed_url",
      "vbr/sessions",
      "question_id",
      "evidence_id_safe",
    ]) {
      expect(html).not.toContain(unsafe)
    }
    // Clip seconds are a locator, not raw media — no media path/URL is emitted.
    expect(html).not.toContain("https://storage")
  })

  it("renders the Recording / clip section with a video element only for a safe playback URL", () => {
    const { rerender } = render(
      <SkillReportView
        report={inspectionChainReport({
          video_available: true,
          video_playback_url: "https://signed.example/full.webm?token=xyz",
          recording_access_note: "Your defense recording is available to play here.",
        })}
      />,
    )
    // The Recording / clip section is present with a real <video> player.
    expect(screen.getByTestId("pdi-recording")).toBeInTheDocument()
    const video = screen.getByTestId("pdi-video") as HTMLVideoElement
    expect(video.tagName).toBe("VIDEO")
    expect(video).toHaveAttribute("src", "https://signed.example/full.webm?token=xyz")
    expect(screen.queryByTestId("pdi-recording-note")).toBeNull()

    // No safe playback URL → no <video>, just the access note.
    rerender(
      <SkillReportView
        report={inspectionChainReport({
          video_available: true,
          video_playback_url: null,
          recording_access_note: "A defense recording exists, but a safe playback link is not available from this view yet.",
        })}
      />,
    )
    expect(screen.queryByTestId("pdi-video")).toBeNull()
    expect(screen.getByTestId("pdi-recording-note")).toHaveTextContent("not available from this view yet")
  })

  it("renders a bounded transcript excerpt when provided, else the access note", () => {
    const { rerender } = render(
      <SkillReportView
        report={inspectionChainReport({
          transcript_excerpt_available: true,
          safe_transcript_excerpt: "I trained a regression model and validated the features before inference.",
          transcript_excerpt_start_label: "03:10",
          transcript_excerpt_end_label: "03:25",
        })}
      />,
    )
    expect(screen.getByTestId("pdi-transcript-excerpt")).toHaveTextContent("regression model")
    expect(screen.getByTestId("pdi-transcript")).toHaveTextContent("03:10 – 03:25")

    // No excerpt → the safe access note is shown instead.
    rerender(
      <SkillReportView
        report={inspectionChainReport({
          transcript_excerpt_available: false,
          safe_transcript_excerpt: null,
          transcript_access_note: "No transcript excerpt is available for this answer.",
        })}
      />,
    )
    expect(screen.queryByTestId("pdi-transcript-excerpt")).toBeNull()
    expect(screen.getByTestId("pdi-transcript-note")).toHaveTextContent("No transcript excerpt is available")
  })

  it("never injects a non-http playback URL into the video element", () => {
    render(
      <SkillReportView
        report={inspectionChainReport({
          video_available: true,
          // A bare storage key / unsafe scheme must never become a media src.
          video_playback_url: "vbr/sessions/s1/processed/full.webm",
          recording_access_note: "A defense recording exists, but a safe playback link is not available from this view yet.",
        })}
      />,
    )
    expect(screen.queryByTestId("pdi-video")).toBeNull()
    expect(screen.getByTestId("pdi-recording-note")).toBeInTheDocument()
  })

  it("shows a withheld placeholder and no answer content for a not-public-safe card", () => {
    const report = inspectionChainReport({
      question_text: null,
      safe_answer_summary: "Defense answer details are withheld because this session is not public-safe.",
      what_this_demonstrates: "",
      corroboration_summary: "",
      corroborates_github: false,
      clip_available: false,
      timestamp_label: null,
      public_safe: false,
      withheld_reason: "Defense answer details are withheld because this session is not public-safe.",
    })
    render(<SkillReportView report={report} />)

    expect(screen.getByTestId("pdi-withheld")).toHaveTextContent("withheld because this session is not public-safe")
    // No answer summary / question / timestamp when withheld.
    expect(screen.queryByTestId("pdi-question")).toBeNull()
    expect(screen.queryByTestId("pdi-answer-summary")).toBeNull()
    expect(screen.queryByTestId("pdi-timestamp")).toBeNull()
    // The honest limitation framing is still shown.
    expect(screen.getByTestId("pdi-limitation")).toBeInTheDocument()
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
    evidence_quality_grade: "implementation_body",
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

// ── Flat legacy weak code_line rows: role-aware, inspectable, still Needs review ─
//
// A weak-graded flat ``code_line`` row must NOT collapse into a bare "Repo-level
// support only" card: it keeps the safe file/line location, the descriptive
// ``code_role_label`` (grade-derived fallback when absent) and the "View code
// lines" link — while staying clearly a Needs-review repository-level signal,
// never primary implementation proof.
describe("SkillReportView — flat legacy weak GitHub code_line rows", () => {
  const WEAK_FLAT_ITEM: SkillReport["github"][number] = {
    ...GITHUB_ITEM,
    source_id: "gh-weak-flat",
    safe_location: "scripts/pipeline_retrain.py · lines 2-20",
    safe_snippet: null,
    file_path: "scripts/pipeline_retrain.py",
    line_start: 2,
    line_end: 20,
    function_name: null,
    display_mode: "code_line",
    has_precise_line_evidence: true,
    evidence_strength: "weak",
    evidence_quality_grade: "comment_or_docstring",
    code_role_label: "Documentation / usage header",
    // Stale overclaiming reason — a weak row must NEVER echo it.
    selection_reason: "ML training call",
    github_line_url: "https://github.com/octocat/Hello-World/blob/main/scripts/pipeline_retrain.py#L2-L20",
    repo_url: "https://github.com/octocat/Hello-World",
    public_url: "https://github.com/octocat/Hello-World/blob/main/scripts/pipeline_retrain.py#L2-L20",
  }

  function renderWeakFlat(overrides: Partial<SkillReport["github"][number]> = {}) {
    render(
      <SkillReportView
        report={skillReport({
          github: [],
          standalone_evidence: { ...emptyStandalone(), github: [{ ...WEAK_FLAT_ITEM, ...overrides }] },
        })}
      />,
    )
  }

  it("renders the backend code_role_label for a weak flat row", () => {
    renderWeakFlat()
    expect(screen.getByTestId("github-code-role-label")).toHaveTextContent("Documentation / usage header")
  })

  it("renders the exact file/line location for a weak flat row", () => {
    renderWeakFlat()
    expect(screen.getByTestId("github-location")).toHaveTextContent("scripts/pipeline_retrain.py · lines 2-20")
  })

  it("renders the function-based location when a function name is present", () => {
    renderWeakFlat({
      file_path: "api.py",
      function_name: "predict",
      evidence_quality_grade: "route_decorator_only",
      code_role_label: "API route shell",
    })
    expect(screen.getByTestId("github-location")).toHaveTextContent("api.py · predict()")
    expect(screen.getByTestId("github-code-role-label")).toHaveTextContent("API route shell")
  })

  it("renders a 'View code lines' link to the exact line URL", () => {
    renderWeakFlat()
    const link = screen.getByTestId("evidence-public-link")
    expect(link).toHaveTextContent("View code lines →")
    expect(link).toHaveAttribute("href", expect.stringContaining("#L2-L20"))
  })

  it("does NOT render 'Repo-level support only' as the row label — it stays Needs review", () => {
    renderWeakFlat()
    expect(screen.queryByText("Repo-level support only")).not.toBeInTheDocument()
    expect(screen.getByTestId("github-needs-review-badge")).toHaveTextContent(
      "Needs review — repository-level signal",
    )
    expect(screen.getByTestId("github-needs-review-note")).toHaveTextContent(
      "not been validated as primary implementation proof",
    )
  })

  it("never shows 'Precise code evidence' for a weak flat row", () => {
    renderWeakFlat()
    expect(screen.queryByTestId("github-precise-badge")).not.toBeInTheDocument()
    expect(screen.queryByText("Precise code evidence")).not.toBeInTheDocument()
  })

  it("never shows 'Code implementation' or 'Primary implementation' for a weak flat row", () => {
    renderWeakFlat()
    expect(screen.queryByText(/Code implementation/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Primary implementation/)).not.toBeInTheDocument()
  })

  it("never echoes the stale overclaiming selection_reason on a weak flat row", () => {
    renderWeakFlat()
    expect(screen.queryByText(/ML training call/)).not.toBeInTheDocument()
    expect(screen.queryByTestId("github-selection-reason")).not.toBeInTheDocument()
  })

  it("falls back to a conservative grade-derived role label when code_role_label is missing", () => {
    renderWeakFlat({ code_role_label: null, evidence_quality_grade: "import_only", selection_reason: null })
    expect(screen.getByTestId("github-code-role-label")).toHaveTextContent("Imports / setup context")
  })

  it("falls back to 'Repository-level context' when both role label and grade are missing", () => {
    renderWeakFlat({ code_role_label: null, evidence_quality_grade: null, selection_reason: null })
    expect(screen.getByTestId("github-code-role-label")).toHaveTextContent("Repository-level context")
    expect(screen.getByTestId("github-needs-review-badge")).toBeInTheDocument()
  })

  // ── Block-level purpose labels (preferred over the broader role label) ──────

  it("prefers code_block_purpose_label over code_role_label on a weak flat row", () => {
    renderWeakFlat({
      code_block_purpose_key: "retraining_documentation",
      code_block_purpose_label: "Documentation describing retraining pipeline",
      code_block_purpose_summary:
        "This header describes the planned retraining workflow and artifacts, but it is not executable training code.",
    })
    expect(screen.getByTestId("github-code-role-label")).toHaveTextContent(
      "Documentation describing retraining pipeline",
    )
    // The short safe purpose summary renders as helper text — never raw code.
    const summary = screen.getByTestId("github-purpose-summary")
    expect(summary).toHaveTextContent("not executable training code")
    expect(summary.textContent).not.toMatch(/import |def |\.fit\(/)
    // Still a Needs-review signal with the code-line link — never promoted.
    expect(screen.getByTestId("github-needs-review-badge")).toBeInTheDocument()
    expect(screen.queryByTestId("github-precise-badge")).not.toBeInTheDocument()
    expect(screen.getByTestId("evidence-public-link")).toHaveTextContent("View code lines →")
  })

  it("falls back to code_role_label when the purpose label is missing, without a summary line", () => {
    renderWeakFlat({ code_block_purpose_label: null, code_block_purpose_summary: null })
    expect(screen.getByTestId("github-code-role-label")).toHaveTextContent("Documentation / usage header")
    expect(screen.queryByTestId("github-purpose-summary")).not.toBeInTheDocument()
  })
})

// ── Missing evidence_quality_grade fails closed (never "Precise code evidence") ─
describe("SkillReportView — ungraded GitHub code_line fails closed", () => {
  const MISSING_GRADE_ITEM: SkillReport["github"][number] = {
    ...GITHUB_ITEM,
    source_id: "gh-ungraded",
    safe_location: "api.py · predict()",
    safe_snippet: "def predict(req):\n    return model.predict(req)",
    file_path: "api.py",
    line_start: 252,
    line_end: 255,
    function_name: "predict",
    display_mode: "code_line",
    has_precise_line_evidence: true,
    evidence_strength: "strong",
    // NO evidence_quality_grade — this must fail closed.
    github_line_url: "https://github.com/octocat/Hello-World/blob/abc1234/api.py#L252-L255",
    repo_url: "https://github.com/octocat/Hello-World",
    public_url: "https://github.com/octocat/Hello-World/blob/abc1234/api.py#L252-L255",
  }

  it("does NOT show 'Precise code evidence' for a missing grade", () => {
    render(
      <SkillReportView
        report={skillReport({
          github: [],
          standalone_evidence: { ...emptyStandalone(), github: [{ ...MISSING_GRADE_ITEM }] },
        })}
      />,
    )
    expect(screen.queryByTestId("github-precise-badge")).not.toBeInTheDocument()
    expect(screen.queryByText("Precise code evidence")).not.toBeInTheDocument()
  })

  it("renders a Needs review / repository-level signal for a missing grade, keeping the code link", () => {
    render(
      <SkillReportView
        report={skillReport({
          github: [],
          standalone_evidence: { ...emptyStandalone(), github: [{ ...MISSING_GRADE_ITEM }] },
        })}
      />,
    )
    expect(screen.getByTestId("github-needs-review-badge")).toHaveTextContent(
      "Needs review — repository-level signal",
    )
    expect(screen.getByTestId("github-needs-review-note")).toHaveTextContent(
      "not been validated as primary implementation proof",
    )
    // The "View code lines" link may remain (rule 4).
    const link = screen.getByTestId("evidence-public-link")
    expect(link).toHaveTextContent("View code lines →")
    expect(link).toHaveAttribute("href", expect.stringContaining("#L252-L255"))
  })

  it("still renders implementation_body as precise implementation", () => {
    render(
      <SkillReportView
        report={skillReport({
          github: [],
          standalone_evidence: {
            ...emptyStandalone(),
            github: [{ ...MISSING_GRADE_ITEM, evidence_quality_grade: "implementation_body" }],
          },
        })}
      />,
    )
    expect(screen.getByTestId("github-precise-badge")).toHaveTextContent("Precise code evidence")
    expect(screen.queryByTestId("github-needs-review-badge")).not.toBeInTheDocument()
  })
})

// ── Connected chain FLAT fallback (no github_groups) fails closed for ungraded ──
describe("SkillReportView — connected flat GitHub fallback fails closed", () => {
  function flatChainReport(grade?: string): SkillReport {
    const chain: SkillReport["projects"][number] = {
      project_id: "proj-1",
      project_title: "Boston Smart Rerouting",
      attached: true,
      attached_status: "Attached to a VBR project",
      sources: ["GitHub Proof"],
      evidence_chain_summary: "GitHub code.",
      // No github_groups on the chain → the flat fallback path is exercised.
      github_evidence: [
        {
          ...GITHUB_ITEM,
          source_id: "gh-flat",
          is_attached_to_project: true,
          attached_project_ids: ["proj-1"],
          display_mode: "code_line",
          has_precise_line_evidence: true,
          ...(grade ? { evidence_quality_grade: grade } : {}),
        },
      ],
      website_evidence: [],
      document_correlations: [],
      document_more_count: 0,
      defense_evidence: [],
      video_evidence: [],
      limitations: [],
    }
    return skillReport({
      github: [],
      standalone_evidence: emptyStandalone(),
      projects: [chain],
      proof_chains: [chain],
    })
  }

  it("renders 'GitHub code signals' (not 'Code implementation') for ungraded flat rows", () => {
    render(<SkillReportView report={flatChainReport()} />)
    const section = screen.getByTestId("chain-github")
    expect(section).toHaveTextContent("GitHub code signals")
    expect(section).not.toHaveTextContent("Code implementation")
    expect(screen.getByTestId("chain-github-flat-no-primary")).toHaveTextContent(
      "not been validated as primary implementation proof",
    )
  })

  it("renders 'Code implementation' when a flat row is a graded implementation_body", () => {
    render(<SkillReportView report={flatChainReport("implementation_body")} />)
    const section = screen.getByTestId("chain-github")
    expect(section).toHaveTextContent("Code implementation")
    expect(screen.queryByTestId("chain-github-flat-no-primary")).not.toBeInTheDocument()
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
    evidence_quality_grade: "implementation_body",
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
      github_evidence: [
        {
          ...GITHUB_ITEM,
          is_attached_to_project: true,
          attached_project_ids: ["proj-1"],
          display_mode: "code_line",
          has_precise_line_evidence: true,
          evidence_quality_grade: "implementation_body",
        },
      ],
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
      website_connection_note:
        "The website demonstrates the working product behaviour; GitHub code shows the implementation; the Project Defense shows the candidate's own understanding.",
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
    // The chain explains how Website Proof connects to the other sources.
    expect(screen.getByTestId("chain-website-note")).toHaveTextContent(
      "GitHub code shows the implementation",
    )
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
    // A fully-ungraded (legacy) group fails closed: the section is titled "GitHub
    // code signals" (never "Code implementation") and the rows sit under a
    // conservative "Needs review / repository-level signals" heading.
    expect(section).toHaveTextContent("GitHub code signals")
    expect(section).not.toHaveTextContent("Code implementation")
    expect(screen.getByTestId("github-ungraded-heading")).toHaveTextContent(
      "not validated primary implementation proof",
    )
    // Grouped block (attached) — not the standalone "not attached" variant.
    const group = screen.getByTestId("chain-github-group")
    expect(group).toHaveAttribute("data-repo", "octocat/Hello-World")
    expect(group).toHaveTextContent("Attached")
    // "View code lines" rows remain, but never as "Primary implementation".
    const rows = screen.getAllByTestId("standalone-github-row")
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveTextContent("api.py · predict()")
    expect(screen.queryByTestId("github-primary-band")).not.toBeInTheDocument()
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
    // The flat fallback fails closed: the ungraded rows are repository-level signals,
    // so the honest "GitHub code signals" title is used (never "Code implementation").
    expect(section).toHaveTextContent("GitHub code signals")
    expect(section).not.toHaveTextContent("Code implementation")
    // Older payload → flat SkillEvidenceItem card, not a grouped block.
    expect(screen.getByTestId("skill-evidence-item")).toBeInTheDocument()
    expect(screen.queryByTestId("chain-github-group")).not.toBeInTheDocument()
  })

  it("titles the section 'GitHub code signals' and shows the no-primary note when graded rows have no implementation body", () => {
    const chain = connectedChain()
    chain.github_groups = [
      {
        repo_label: "octocat/Hello-World",
        repo_url: "https://github.com/octocat/Hello-World",
        repo_is_public: true,
        row_more_count: 0,
        rows: [
          { source_id: "w1", label: "scripts/pipeline_retrain.py · lines 2-20", file_path: "scripts/pipeline_retrain.py", line_start: 2, line_end: 20, evidence_quality_grade: "comment_or_docstring", selection_reason: "module docstring or header comment", github_line_url: "https://github.com/octocat/Hello-World/blob/main/scripts/pipeline_retrain.py#L2-L20" },
          { source_id: "w2", label: "scripts/pipeline_retrain.py · lines 29-47", file_path: "scripts/pipeline_retrain.py", line_start: 29, line_end: 47, evidence_quality_grade: "import_only", selection_reason: "import statements", github_line_url: "https://github.com/octocat/Hello-World/blob/main/scripts/pipeline_retrain.py#L29-L47" },
        ],
      },
    ]
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    const section = screen.getByTestId("chain-github")
    expect(section).toHaveTextContent("GitHub code signals")
    expect(section).not.toHaveTextContent("Code implementation")
    expect(screen.getByTestId("chain-github-no-primary")).toBeInTheDocument()
    // Weak rows collapse into a "Needs review" summary, not precise code rows.
    expect(screen.getByTestId("github-weak-signals")).toBeInTheDocument()
    expect(screen.queryByTestId("standalone-github-row")).not.toBeInTheDocument()
  })

  it("keeps 'Code implementation' and renders primary rows when an implementation body exists", () => {
    const chain = connectedChain()
    chain.github_groups = [
      {
        repo_label: "octocat/Hello-World",
        repo_url: "https://github.com/octocat/Hello-World",
        repo_is_public: true,
        row_more_count: 0,
        rows: [
          { source_id: "p1", label: "src/model/train.py · train_model()", file_path: "src/model/train.py", function_name: "train_model", evidence_quality_grade: "implementation_body", selection_reason: "ML training call", github_line_url: "https://github.com/octocat/Hello-World/blob/main/src/model/train.py#L16-L26" },
          { source_id: "w1", label: "a.py · lines 1-3", file_path: "a.py", line_start: 1, line_end: 3, evidence_quality_grade: "import_only", selection_reason: "import statements", github_line_url: "https://github.com/octocat/Hello-World/blob/main/a.py#L1-L3" },
        ],
      },
    ]
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    const section = screen.getByTestId("chain-github")
    expect(section).toHaveTextContent("Code implementation")
    expect(screen.getByTestId("github-primary-band")).toBeInTheDocument()
    expect(screen.getByTestId("github-primary-band")).toHaveTextContent("train_model()")
    // The weak import row is still demoted to the "Needs review" summary.
    expect(screen.getByTestId("github-weak-signals")).toBeInTheDocument()
  })

  // ── Fix #3: legacy ungraded rows fail closed (only when mixed) ────────────────

  function ghRow(over: Partial<SkillReportStandaloneGitHubRow> & { source_id: string; label: string }) {
    return {
      file_path: "x.py",
      line_start: 1,
      line_end: 5,
      github_line_url: `https://github.com/octocat/Hello-World/blob/main/${over.file_path ?? "x.py"}#L1-L5`,
      ...over,
    } as SkillReportStandaloneGitHubRow
  }

  function groupedChain(rows: SkillReportStandaloneGitHubRow[], rowMore = 0): SkillReportProjectChain {
    const chain = connectedChain()
    chain.github_groups = [
      { repo_label: "octocat/Hello-World", repo_url: "https://github.com/octocat/Hello-World", repo_is_public: true, row_more_count: rowMore, rows },
    ]
    return chain
  }

  it("demotes an UNGRADED code_line into Needs review when the group also has a graded row", () => {
    const chain = groupedChain([
      ghRow({ source_id: "p1", label: "src/train.py · train_model()", file_path: "src/train.py", function_name: "train_model", evidence_quality_grade: "implementation_body" }),
      ghRow({ source_id: "u1", label: "legacy_helper.py · lines 1-5", file_path: "legacy_helper.py", selection_reason: "prior heuristic" }),
    ])
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    // The ungraded row is inside the Needs-review band, never a precise primary row,
    // and never carries the "Precise code evidence" badge.
    expect(screen.getByTestId("github-weak-signals")).toBeInTheDocument()
    expect(screen.queryByTestId("github-precise-badge")).not.toBeInTheDocument()
    // The ungraded row is inspectable by default (visible without any interaction),
    // surfaced as a muted weak row — never as a primary implementation row.
    expect(screen.getByText("legacy_helper.py · lines 1-5")).toBeInTheDocument()
    expect(screen.getAllByTestId("standalone-github-weak-row").length).toBeGreaterThanOrEqual(1)
  })

  it("a weak-GRADED-only group titles the section 'GitHub code signals', never 'Code implementation'", () => {
    const chain = groupedChain([
      ghRow({ source_id: "w1", label: "a.py · lines 1-5", evidence_quality_grade: "import_only", selection_reason: "import statements" }),
      ghRow({ source_id: "w2", label: "b.py · lines 1-5", file_path: "b.py", evidence_quality_grade: "comment_or_docstring", selection_reason: "module docstring or header comment" }),
    ])
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    const section = screen.getByTestId("chain-github")
    expect(section).toHaveTextContent("GitHub code signals")
    expect(section).not.toHaveTextContent("Code implementation")
    expect(screen.getByTestId("github-weak-signals")).toBeInTheDocument()
    expect(screen.queryByTestId("standalone-github-row")).not.toBeInTheDocument()
  })

  // ── Weak-only group: weak code signals stay conservative but inspectable ──────

  it("keeps a weak-only group inspectable: safe file/line rows + 'View code lines' visible by default", () => {
    const chain = groupedChain([
      ghRow({ source_id: "w1", label: "a.py · lines 1-5", evidence_quality_grade: "import_only", selection_reason: "ML training call" }),
      ghRow({ source_id: "w2", label: "b.py · lines 8-12", file_path: "b.py", evidence_quality_grade: "comment_or_docstring", selection_reason: "Cloud deployment command" }),
    ])
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    const section = screen.getByTestId("chain-github")
    // Conservative framing.
    expect(section).toHaveTextContent("GitHub code signals")
    expect(section).not.toHaveTextContent("Code implementation")
    expect(section).not.toHaveTextContent("Primary implementation")
    expect(screen.queryByTestId("github-precise-badge")).not.toBeInTheDocument()
    expect(section).not.toHaveTextContent("Precise code evidence")
    // Needs-review heading names the weak signal count.
    expect(screen.getByTestId("github-weak-heading")).toHaveTextContent("Needs review — 2 weak/repository-level signals")
    // BUT the weak rows are inspectable WITHOUT any interaction (works in a PDF):
    // safe file/line labels + a "View code lines" link on each row.
    const weakRows = screen.getAllByTestId("standalone-github-weak-row")
    expect(weakRows).toHaveLength(2)
    expect(weakRows[0]).toHaveTextContent("a.py · lines 1-5")
    expect(weakRows[1]).toHaveTextContent("b.py · lines 8-12")
    expect(screen.getAllByText("View code lines →").length).toBeGreaterThanOrEqual(2)
    // Overclaiming raw selection_reason is replaced by a conservative grade-derived
    // role label describing what the block appears to be.
    expect(section).not.toHaveTextContent("ML training call")
    expect(section).not.toHaveTextContent("Cloud deployment command")
    expect(weakRows[0]).toHaveTextContent("Imports / setup context")
    expect(weakRows[1]).toHaveTextContent("Documentation / usage header")
  })

  // ── Code role labels: role-aware weak rows (never proof-strength promotion) ───

  it("renders the backend code_role_label on weak rows (docstring / imports / route shell)", () => {
    const chain = groupedChain([
      ghRow({
        source_id: "r1",
        label: "scripts/pipeline_retrain.py · lines 2-20",
        file_path: "scripts/pipeline_retrain.py",
        evidence_quality_grade: "comment_or_docstring",
        code_role_key: "documentation_header",
        code_role_label: "Documentation / usage header",
        selection_reason: "ML training call",
      }),
      ghRow({
        source_id: "r2",
        label: "scripts/pipeline_retrain.py · lines 29-47",
        file_path: "scripts/pipeline_retrain.py",
        evidence_quality_grade: "import_only",
        code_role_key: "imports_setup",
        code_role_label: "Imports / setup context",
      }),
      ghRow({
        source_id: "r3",
        label: "api.py · predict()",
        file_path: "api.py",
        function_name: "predict",
        evidence_quality_grade: "route_decorator_only",
        code_role_key: "api_route_shell",
        code_role_label: "API route shell",
      }),
    ])
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    // All three stay in the Needs-review band — role labels never promote a row.
    const weak = screen.getByTestId("github-weak-signals")
    const weakRows = screen.getAllByTestId("standalone-github-weak-row")
    expect(weakRows).toHaveLength(3)
    expect(weakRows[0]).toHaveTextContent("Documentation / usage header")
    expect(weakRows[1]).toHaveTextContent("Imports / setup context")
    expect(weakRows[2]).toHaveTextContent("API route shell")
    // The stale overclaiming reason never renders as the row label.
    expect(weak).not.toHaveTextContent("ML training call")
    // No implementation framing, no precise-evidence badge for weak-only groups.
    const section = screen.getByTestId("chain-github")
    expect(section).not.toHaveTextContent("Code implementation")
    expect(section).not.toHaveTextContent("Precise code evidence")
    expect(screen.queryByTestId("github-precise-badge")).not.toBeInTheDocument()
    // Rows keep their safe location label + "View code lines" link.
    expect(weakRows[0]).toHaveTextContent("scripts/pipeline_retrain.py · lines 2-20")
    expect(screen.getAllByText("View code lines →").length).toBeGreaterThanOrEqual(3)
  })

  it("renders semantic context roles (evaluation / deployment) on weak rows without promoting them", () => {
    const chain = groupedChain([
      ghRow({
        source_id: "m1",
        label: "src/model/train.py · lines 19-37",
        file_path: "src/model/train.py",
        evidence_quality_grade: "repo_level_fallback",
        code_role_key: "evaluation_metrics",
        code_role_label: "Evaluation / metrics context",
      }),
      ghRow({
        source_id: "d1",
        label: "serving/main.py · lines 8-26",
        file_path: "serving/main.py",
        evidence_quality_grade: "repo_level_fallback",
        code_role_key: "deployment_serving",
        code_role_label: "Deployment / serving context",
      }),
    ])
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    const weakRows = screen.getAllByTestId("standalone-github-weak-row")
    expect(weakRows[0]).toHaveTextContent("Evaluation / metrics context")
    expect(weakRows[1]).toHaveTextContent("Deployment / serving context")
    // Still under Needs review — a context role never becomes primary ML proof.
    expect(screen.getByTestId("github-weak-heading")).toHaveTextContent("Needs review")
    expect(screen.queryByTestId("github-primary-band")).not.toBeInTheDocument()
    const section = screen.getByTestId("chain-github")
    expect(section).not.toHaveTextContent("Code implementation")
  })

  it("derives a conservative role label from the grade when code_role_label is missing (stale payload)", () => {
    const chain = groupedChain([
      ghRow({ source_id: "s1", label: "cfg.py · lines 1-4", file_path: "cfg.py", evidence_quality_grade: "config_or_constant", selection_reason: "ML model configuration" }),
      ghRow({ source_id: "s2", label: "legacy.py · lines 1-9", file_path: "legacy.py", evidence_quality_grade: "repo_level_fallback", selection_reason: "Model serving inference handler" }),
    ])
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    const weakRows = screen.getAllByTestId("standalone-github-weak-row")
    expect(weakRows[0]).toHaveTextContent("Config / constants")
    expect(weakRows[1]).toHaveTextContent("Repository-level context")
    // Stale overclaiming reasons never surface as the main label.
    const weak = screen.getByTestId("github-weak-signals")
    expect(weak).not.toHaveTextContent("ML model configuration")
    expect(weak).not.toHaveTextContent("Model serving inference handler")
  })

  // ── Block-level purpose labels on grouped rows (preferred, never promoting) ───

  it("renders the code_block_purpose_label on weak grouped rows, preferred over the role label", () => {
    const chain = groupedChain([
      ghRow({
        source_id: "p1",
        label: "scripts/pipeline_retrain.py · lines 2-20",
        file_path: "scripts/pipeline_retrain.py",
        evidence_quality_grade: "comment_or_docstring",
        code_role_key: "documentation_header",
        code_role_label: "Documentation / usage header",
        code_block_purpose_key: "retraining_documentation",
        code_block_purpose_label: "Documentation describing retraining pipeline",
        code_block_purpose_summary:
          "This header describes the planned retraining workflow and artifacts, but it is not executable training code.",
        selection_reason: "ML training call",
      }),
      ghRow({
        source_id: "p2",
        label: "scripts/pipeline_retrain.py · lines 29-47",
        file_path: "scripts/pipeline_retrain.py",
        evidence_quality_grade: "import_only",
        code_role_key: "imports_setup",
        code_role_label: "Imports / setup context",
        code_block_purpose_key: "imports_dependencies",
        code_block_purpose_label: "Imports / dependency setup",
        code_block_purpose_summary:
          "This block imports libraries used elsewhere; it is not implementation proof by itself.",
      }),
    ])
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    const weakRows = screen.getAllByTestId("standalone-github-weak-row")
    expect(weakRows).toHaveLength(2)
    // The purpose label wins over the broader role label.
    expect(weakRows[0]).toHaveTextContent("Documentation describing retraining pipeline")
    expect(weakRows[0]).not.toHaveTextContent("Documentation / usage header")
    expect(weakRows[1]).toHaveTextContent("Imports / dependency setup")
    // The short safe purpose summary rides as a hover tooltip (kept compact).
    const purposes = screen.getAllByTestId("github-row-purpose")
    expect(purposes[0]).toHaveAttribute("title", expect.stringContaining("not executable training code"))
    // Still Needs review, never precise/primary, stale reason never surfaces.
    expect(screen.getByTestId("github-weak-heading")).toHaveTextContent("Needs review")
    const section = screen.getByTestId("chain-github")
    expect(section).toHaveTextContent("GitHub code signals")
    expect(section).not.toHaveTextContent("Code implementation")
    expect(section).not.toHaveTextContent("Precise code evidence")
    expect(section).not.toHaveTextContent("ML training call")
    // Rows keep their safe location + "View code lines" links.
    expect(weakRows[0]).toHaveTextContent("scripts/pipeline_retrain.py · lines 2-20")
    expect(screen.getAllByText("View code lines →").length).toBeGreaterThanOrEqual(2)
  })

  it("weak grouped rows fall back to role label then grade label when the purpose is missing", () => {
    const chain = groupedChain([
      ghRow({
        source_id: "f1",
        label: "a.py · lines 1-5",
        evidence_quality_grade: "comment_or_docstring",
        code_role_label: "Documentation / usage header",
      }),
      ghRow({
        source_id: "f2",
        label: "b.py · lines 1-5",
        file_path: "b.py",
        evidence_quality_grade: "import_only",
      }),
    ])
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    const weakRows = screen.getAllByTestId("standalone-github-weak-row")
    expect(weakRows[0]).toHaveTextContent("Documentation / usage header")
    expect(weakRows[1]).toHaveTextContent("Imports / setup context")
  })

  it("primary and supporting rows still render their bands when purpose fields are present", () => {
    const chain = groupedChain([
      ghRow({
        source_id: "pr1",
        label: "src/model/train.py · lines 19-37",
        file_path: "src/model/train.py",
        evidence_quality_grade: "implementation_body",
        code_block_purpose_key: "model_training",
        code_block_purpose_label: "Model training",
        selection_reason: "ML training call",
      }),
      ghRow({
        source_id: "su1",
        label: "src/model/eval.py · lines 10-22",
        file_path: "src/model/eval.py",
        evidence_quality_grade: "supporting_logic",
        code_block_purpose_key: "model_evaluation",
        code_block_purpose_label: "Evaluation / metrics",
      }),
      ghRow({
        source_id: "wk1",
        label: "scripts/pipeline_retrain.py · lines 29-47",
        file_path: "scripts/pipeline_retrain.py",
        evidence_quality_grade: "import_only",
        code_block_purpose_label: "Imports / dependency setup",
      }),
    ])
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    // Strong rows render in their bands; the strong row keeps its validated reason,
    // and the supporting row falls back to its purpose label.
    expect(screen.getByTestId("github-primary-band")).toHaveTextContent("ML training call")
    expect(screen.getByTestId("github-supporting-band")).toHaveTextContent("Evaluation / metrics")
    // The weak import row stays under Needs review with its purpose label.
    expect(screen.getByTestId("github-weak-signals")).toHaveTextContent("Imports / dependency setup")
    // A group WITH a primary body still titles as Code implementation.
    expect(screen.getByTestId("chain-github")).toHaveTextContent("Code implementation")
  })

  it("collapses extra weak purpose-labelled rows behind '+N more weak code locations'", () => {
    const rows = Array.from({ length: 5 }, (_, i) =>
      ghRow({
        source_id: `pw${i}`,
        label: `w${i}.py · lines 1-5`,
        file_path: `w${i}.py`,
        evidence_quality_grade: "import_only",
        code_block_purpose_label: "Imports / dependency setup",
      }),
    )
    const chain = groupedChain(rows)
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    // First 3 visible, the rest behind the toggle.
    expect(screen.getAllByTestId("standalone-github-weak-row")).toHaveLength(3)
    const toggle = screen.getByTestId("github-weak-more")
    expect(toggle).toHaveTextContent("+2 more weak code locations")
    fireEvent.click(toggle)
    expect(screen.getAllByTestId("standalone-github-weak-row")).toHaveLength(5)
  })

  it("shows the first weak rows and collapses the rest behind '+N more weak code locations'", () => {
    const rows = Array.from({ length: 6 }, (_, i) =>
      ghRow({ source_id: `w${i}`, label: `w${i}.py · lines 1-5`, file_path: `w${i}.py`, evidence_quality_grade: "import_only" }),
    )
    const chain = groupedChain(rows)
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    // First 3 weak rows visible by default; a "+3 more weak code locations" toggle.
    expect(screen.getAllByTestId("standalone-github-weak-row")).toHaveLength(3)
    const more = screen.getByTestId("github-weak-more")
    expect(more).toHaveTextContent("+3 more weak code locations")
    fireEvent.click(more)
    expect(screen.getAllByTestId("standalone-github-weak-row")).toHaveLength(6)
    expect(more).toHaveTextContent("Show fewer weak code locations")
  })

  it("orders a mixed graded group primary → supporting → needs-review, all inspectable", () => {
    const chain = groupedChain([
      ghRow({ source_id: "p1", label: "src/train.py · train_model()", file_path: "src/train.py", function_name: "train_model", evidence_quality_grade: "implementation_body" }),
      ghRow({ source_id: "s1", label: "src/util.py · helper()", file_path: "src/util.py", function_name: "helper", evidence_quality_grade: "supporting_logic" }),
      ghRow({ source_id: "w1", label: "imp.py · lines 1-3", file_path: "imp.py", evidence_quality_grade: "import_only" }),
    ])
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    const section = screen.getByTestId("chain-github")
    // A real implementation body → "Code implementation" title + primary band.
    expect(section).toHaveTextContent("Code implementation")
    expect(screen.getByTestId("github-primary-band")).toHaveTextContent("train_model()")
    expect(screen.getByTestId("github-supporting-band")).toHaveTextContent("helper()")
    // The weak row is demoted to the Needs-review band, but still inspectable.
    const weak = screen.getByTestId("github-weak-signals")
    expect(weak).toHaveTextContent("imp.py · lines 1-3")
    // DOM order: primary band appears before the needs-review band.
    const primary = screen.getByTestId("github-primary-band")
    expect(primary.compareDocumentPosition(weak) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  // ── Fix #4: each band caps visible rows with a "+N more" control ──────────────

  it("caps the primary band and reveals hidden primary rows via '+N more'", () => {
    const rows = Array.from({ length: 5 }, (_, i) =>
      ghRow({ source_id: `p${i}`, label: `src/m${i}.py · f${i}()`, file_path: `src/m${i}.py`, function_name: `f${i}`, evidence_quality_grade: "implementation_body" }),
    )
    const chain = groupedChain(rows)
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    // Only the first 3 primary rows are visible; a "+2 more" control caps the band.
    expect(screen.getByTestId("github-primary-band")).toHaveTextContent("f0()")
    expect(screen.queryByText("src/m4.py · f4()")).not.toBeInTheDocument()
    const more = screen.getByTestId("github-primary-band-more")
    expect(more).toHaveTextContent("+2 more code locations")
    fireEvent.click(more)
    expect(screen.getByText("src/m4.py · f4()")).toBeInTheDocument()
    expect(more).toHaveTextContent("Show fewer code locations")
  })

  it("caps the Needs-review band with its own '+N more' when expanded", () => {
    const rows = Array.from({ length: 5 }, (_, i) =>
      ghRow({ source_id: `w${i}`, label: `w${i}.py · lines 1-5`, file_path: `w${i}.py`, evidence_quality_grade: "import_only", selection_reason: "import statements" }),
    )
    const chain = groupedChain(rows)
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    // The first 3 weak rows are visible by default (inspectable in a static/PDF
    // render); the rest collapse behind a "+2 more weak code locations" toggle.
    expect(screen.getAllByTestId("standalone-github-weak-row")).toHaveLength(3)
    const more = screen.getByTestId("github-weak-more")
    expect(more).toHaveTextContent("+2 more weak code locations")
    fireEvent.click(more)
    expect(screen.getAllByTestId("standalone-github-weak-row")).toHaveLength(5)
  })

  it("preserves the legacy '+N more' flat behavior for a fully-ungraded group", () => {
    const chain = groupedChain(
      [
        ghRow({ source_id: "l1", label: "train.py · train_model()", file_path: "train.py", function_name: "train_model", selection_reason: "training body" }),
        ghRow({ source_id: "l2", label: "extra1.py · lines 1-5", file_path: "extra1.py", selection_reason: "helper" }),
        ghRow({ source_id: "l3", label: "extra2.py · lines 1-5", file_path: "extra2.py", selection_reason: "helper" }),
      ],
      2,
    )
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    // Fully ungraded → legacy flat list: 1 visible + a "+2 more code locations".
    expect(screen.getAllByTestId("standalone-github-row")).toHaveLength(1)
    const toggle = screen.getByTestId("standalone-github-more")
    expect(toggle).toHaveTextContent("+2 more code locations")
    fireEvent.click(toggle)
    expect(screen.getAllByTestId("standalone-github-row")).toHaveLength(3)
  })

  it("fails closed for a fully-ungraded legacy group (no implementation overclaim)", () => {
    const chain = groupedChain([
      ghRow({ source_id: "l1", label: "train.py · train_model()", file_path: "train.py", function_name: "train_model", selection_reason: "training body" }),
      ghRow({ source_id: "l2", label: "extra1.py · lines 1-5", file_path: "extra1.py", selection_reason: "helper" }),
    ])
    render(<SkillReportView report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })} />)
    const section = screen.getByTestId("chain-github")
    // Section title is "GitHub code signals", never "Code implementation".
    expect(section).toHaveTextContent("GitHub code signals")
    expect(section).not.toHaveTextContent("Code implementation")
    // Rows render under the conservative Needs-review / repository-level heading.
    expect(screen.getByTestId("github-ungraded-heading")).toHaveTextContent(
      "Needs review / repository-level signals — not validated primary implementation proof",
    )
    // No primary-implementation band and no "Precise code evidence" badge.
    expect(screen.queryByTestId("github-primary-band")).not.toBeInTheDocument()
    expect(section).not.toHaveTextContent("Primary implementation")
    expect(screen.queryByTestId("github-precise-badge")).not.toBeInTheDocument()
    // "View code lines" links may remain on the ungraded rows.
    expect(screen.getAllByText("View code lines →").length).toBeGreaterThanOrEqual(1)
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

  it("never renders the attachment overview or suggestion sections (Step 4)", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())
    render(<PublicPassportView slug="abc" />)
    expect(await screen.findByText("Jordan Rivera")).toBeInTheDocument()
    // Suggested evidence is owner-only — it must never read as public proof.
    expect(screen.queryByTestId("attachment-overview")).not.toBeInTheDocument()
    expect(screen.queryByTestId("attachment-entry")).not.toBeInTheDocument()
    expect(screen.queryByTestId("attachment-suggested-section")).not.toBeInTheDocument()
    expect(screen.queryByText(/Suggested — not counted until attached/)).not.toBeInTheDocument()
  })
})

// ── Skill relevance helpers (closed backend templates, never proof strength) ───
//
// ``skill_relevance_label`` explains how a block relates to the report's skill
// ("Product UI context, not Machine Learning implementation"). Weak rows render
// it as a compact helper; it never promotes a row out of Needs review.
describe("SkillReportView — skill relevance helpers on GitHub rows", () => {
  const WEAK_RELEVANCE_ITEM: SkillReport["github"][number] = {
    ...GITHUB_ITEM,
    source_id: "gh-weak-rel",
    safe_location: "stroke-risk-prediction-app/page.tsx · lines 31-58",
    safe_snippet: null,
    file_path: "stroke-risk-prediction-app/page.tsx",
    line_start: 31,
    line_end: 58,
    function_name: null,
    display_mode: "code_line",
    has_precise_line_evidence: true,
    evidence_strength: "weak",
    evidence_quality_grade: "repo_level_fallback",
    code_role_label: "Repository-level context",
    code_block_purpose_key: "frontend_ui_component",
    code_block_purpose_label: "Frontend UI component",
    code_block_purpose_summary: "This block is frontend UI code supporting the application.",
    skill_relevance_key: "product_ui_context",
    skill_relevance_label: "Product UI context, not Machine Learning implementation",
    skill_relevance_summary:
      "This is frontend/product UI around the application — context for Machine Learning, not implementation proof.",
    selection_reason: "ML training call",
    github_line_url:
      "https://github.com/octocat/Hello-World/blob/main/stroke-risk-prediction-app/page.tsx#L31-L58",
    repo_url: "https://github.com/octocat/Hello-World",
    public_url:
      "https://github.com/octocat/Hello-World/blob/main/stroke-risk-prediction-app/page.tsx#L31-L58",
  }

  function renderWeakItem(overrides: Partial<SkillReport["github"][number]> = {}) {
    render(
      <SkillReportView
        report={skillReport({
          github: [],
          standalone_evidence: {
            ...emptyStandalone(),
            github: [{ ...WEAK_RELEVANCE_ITEM, ...overrides }],
          },
        })}
      />,
    )
  }

  it("renders the skill relevance helper on a weak UI-context row (UI ≠ ML implementation)", () => {
    renderWeakItem()
    const relevance = screen.getByTestId("github-skill-relevance")
    expect(relevance).toHaveTextContent("Product UI context, not Machine Learning implementation")
    expect(relevance).toHaveAttribute("title", expect.stringContaining("not implementation proof"))
    // The purpose label still renders as the descriptive label.
    expect(screen.getByTestId("github-code-role-label")).toHaveTextContent("Frontend UI component")
    // Still Needs review — the relevance helper never promotes the row.
    expect(screen.getByTestId("github-needs-review-badge")).toBeInTheDocument()
    expect(screen.queryByTestId("github-precise-badge")).not.toBeInTheDocument()
    // The stale overclaiming reason never surfaces.
    expect(screen.queryByText(/ML training call/)).not.toBeInTheDocument()
  })

  it("omits the relevance helper when the backend did not provide one", () => {
    renderWeakItem({ skill_relevance_key: null, skill_relevance_label: null, skill_relevance_summary: null })
    expect(screen.queryByTestId("github-skill-relevance")).not.toBeInTheDocument()
    expect(screen.getByTestId("github-needs-review-badge")).toBeInTheDocument()
  })

  // The frontend is fully generic: any purpose label from the backend's closed
  // vocabulary renders as-is — new skill families (React sub-purposes, Docker
  // instructions, geospatial purposes) need NO per-skill rendering changes.
  it.each([
    ["frontend_form_component", "Input form and form state handling"],
    ["container_dependency_install", "Container dependency installation"],
    ["geospatial_distance_calculation", "Distance / proximity calculation"],
  ])("renders the specific %s purpose label instead of a generic one", (key, label) => {
    renderWeakItem({
      code_block_purpose_key: key,
      code_block_purpose_label: label,
      code_role_label: null,
    })
    expect(screen.getByTestId("github-code-role-label")).toHaveTextContent(label)
    // Proof strength is untouched by the richer label.
    expect(screen.getByTestId("github-needs-review-badge")).toBeInTheDocument()
  })

  function relChain(rows: SkillReportStandaloneGitHubRow[], rowMore = 0): SkillReportProjectChain {
    return {
      project_id: "proj-rel",
      project_title: "Stroke Risk Prediction",
      attached: true,
      attached_status: "Attached to a VBR project",
      sources: ["GitHub Proof"],
      evidence_chain_summary: "ML is supported by GitHub implementation.",
      github_evidence: [{ ...GITHUB_ITEM, source_id: rows[0]?.source_id ?? "gh-rel" }],
      github_groups: [
        {
          repo_label: "octocat/Hello-World",
          repo_url: "https://github.com/octocat/Hello-World",
          repo_is_public: true,
          row_more_count: rowMore,
          rows,
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

  it("weak grouped rows show the compact relevance suffix; strong rows do not", () => {
    const chain = relChain([
      {
        source_id: "s1",
        label: "Tree.py · lines 13-72",
        file_path: "Tree.py",
        line_start: 13,
        line_end: 72,
        evidence_quality_grade: "implementation_body",
        code_block_purpose_key: "model_training",
        code_block_purpose_label: "Model training",
        skill_relevance_key: "direct_implementation",
        skill_relevance_label: "Direct Machine Learning implementation evidence",
        selection_reason: "Decision tree training / splitting logic",
        github_line_url: "https://github.com/octocat/Hello-World/blob/main/Tree.py#L13-L72",
      } as SkillReportStandaloneGitHubRow,
      {
        source_id: "w1",
        label: "stroke-risk-prediction-app/page.tsx · lines 31-58",
        file_path: "stroke-risk-prediction-app/page.tsx",
        line_start: 31,
        line_end: 58,
        evidence_quality_grade: "repo_level_fallback",
        code_block_purpose_key: "frontend_ui_component",
        code_block_purpose_label: "Frontend UI component",
        skill_relevance_key: "product_ui_context",
        skill_relevance_label: "Product UI context, not Machine Learning implementation",
        skill_relevance_summary:
          "This is frontend/product UI around the application — context for Machine Learning, not implementation proof.",
        github_line_url:
          "https://github.com/octocat/Hello-World/blob/main/stroke-risk-prediction-app/page.tsx#L31-L58",
      } as SkillReportStandaloneGitHubRow,
    ])
    render(
      <SkillReportView
        report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })}
      />,
    )
    // The weak UI row carries the compact italic relevance suffix + tooltip.
    const suffixes = screen.getAllByTestId("github-row-skill-relevance")
    expect(suffixes).toHaveLength(1)
    expect(suffixes[0]).toHaveTextContent("Product UI context, not Machine Learning implementation")
    expect(suffixes[0]).toHaveAttribute("title", expect.stringContaining("not implementation proof"))
    // The strong Tree.py row keeps its validated precise reason — no suffix.
    const strongRow = screen.getAllByTestId("standalone-github-row")[0]
    expect(strongRow).toHaveTextContent("Decision tree training / splitting logic")
    expect(strongRow).not.toHaveTextContent("Direct Machine Learning implementation evidence")
    // The weak row stays under Needs review with its "View code lines" link.
    expect(screen.getByTestId("github-weak-heading")).toHaveTextContent("Needs review")
    expect(screen.getAllByText("View code lines →").length).toBeGreaterThanOrEqual(2)
  })

  it("keeps '+N more weak code locations' collapse behaviour when weak rows carry relevance helpers", () => {
    // 4 weak rows against the GITHUB_BAND_CAP of 3 -> one collapses behind the toggle.
    const weakRows = [1, 2, 3, 4].map(
      (n) =>
        ({
          source_id: `w${n}`,
          label: `mod_${n}.py · lines 1-5`,
          file_path: `mod_${n}.py`,
          evidence_quality_grade: "import_only",
          code_block_purpose_label: "Imports / dependency setup",
          skill_relevance_key: "setup_context",
          skill_relevance_label: "Setup context, not Machine Learning implementation proof",
          github_line_url: `https://github.com/octocat/Hello-World/blob/main/mod_${n}.py#L1-L5`,
        }) as SkillReportStandaloneGitHubRow,
    )
    const chain = relChain(weakRows)
    render(
      <SkillReportView
        report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })}
      />,
    )
    // Visible weak rows carry the relevance helper; the remainder still collapses.
    expect(screen.getAllByTestId("github-row-skill-relevance")).toHaveLength(3)
    expect(
      screen.getAllByTestId("github-row-skill-relevance")[0],
    ).toHaveTextContent("Setup context, not Machine Learning implementation proof")
    expect(screen.getByTestId("github-weak-more")).toHaveTextContent("+1 more weak code location")
  })

  it("demotes a cross-skill implementation_body row out of Primary implementation", () => {
    // Codex must-fix regression: an implementation body whose skill relevance says
    // "another skill's code" (cross_skill_context) must render under Needs review,
    // never inside the Primary implementation band; the direct ML body stays primary.
    const chain = relChain([
      {
        source_id: "s1",
        label: "Tree.py · lines 13-72",
        file_path: "Tree.py",
        line_start: 13,
        line_end: 72,
        evidence_quality_grade: "implementation_body",
        code_block_purpose_key: "model_training",
        code_block_purpose_label: "Model training",
        skill_relevance_key: "direct_implementation",
        skill_relevance_label: "Direct Machine Learning implementation evidence",
        selection_reason: "Decision tree training / splitting logic",
        github_line_url: "https://github.com/octocat/Hello-World/blob/main/Tree.py#L13-L72",
      } as SkillReportStandaloneGitHubRow,
      {
        source_id: "x1",
        label: "app/page.tsx · lines 31-58",
        file_path: "app/page.tsx",
        line_start: 31,
        line_end: 58,
        evidence_quality_grade: "implementation_body",
        code_block_purpose_key: "frontend_ui_component",
        code_block_purpose_label: "Frontend UI component",
        skill_relevance_key: "cross_skill_context",
        skill_relevance_label: "Adjacent code context, not direct Machine Learning evidence",
        github_line_url: "https://github.com/octocat/Hello-World/blob/main/app/page.tsx#L31-L58",
      } as SkillReportStandaloneGitHubRow,
    ])
    render(
      <SkillReportView
        report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })}
      />,
    )
    const primary = screen.getByTestId("github-primary-band")
    expect(primary).toHaveTextContent("Tree.py · lines 13-72")
    expect(primary).not.toHaveTextContent("app/page.tsx")
    // The demoted row sits under Needs review, with its honest purpose + relevance.
    const weakBand = screen.getByTestId("github-weak-signals")
    expect(weakBand).toHaveTextContent("app/page.tsx · lines 31-58")
    expect(weakBand).toHaveTextContent("Frontend UI component")
    expect(weakBand).toHaveTextContent("Adjacent code context, not direct Machine Learning evidence")
  })

  it("demotes a product-UI implementation_body group entirely and keeps supporting rows honest", () => {
    // A group whose ONLY strong rows are another skill's code renders no Primary
    // band at all; a cross-skill supporting_logic row is also kept out of the
    // Supporting band.
    const chain = relChain([
      {
        source_id: "x1",
        label: "app/page.tsx · lines 31-58",
        file_path: "app/page.tsx",
        evidence_quality_grade: "implementation_body",
        code_block_purpose_label: "Frontend UI component",
        skill_relevance_key: "product_ui_context",
        skill_relevance_label: "Product UI context, not Machine Learning implementation",
        github_line_url: "https://github.com/octocat/Hello-World/blob/main/app/page.tsx#L31-L58",
      } as SkillReportStandaloneGitHubRow,
      {
        source_id: "x2",
        label: "app/api-client.ts · lines 5-40",
        file_path: "app/api-client.ts",
        evidence_quality_grade: "supporting_logic",
        code_block_purpose_label: "Frontend UI component",
        skill_relevance_key: "cross_skill_context",
        skill_relevance_label: "Adjacent code context, not direct Machine Learning evidence",
        github_line_url: "https://github.com/octocat/Hello-World/blob/main/app/api-client.ts#L5-L40",
      } as SkillReportStandaloneGitHubRow,
    ])
    render(
      <SkillReportView
        report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })}
      />,
    )
    expect(screen.queryByTestId("github-primary-band")).not.toBeInTheDocument()
    expect(screen.queryByTestId("github-supporting-band")).not.toBeInTheDocument()
    const weakBand = screen.getByTestId("github-weak-signals")
    expect(weakBand).toHaveTextContent("app/page.tsx · lines 31-58")
    expect(weakBand).toHaveTextContent("app/api-client.ts · lines 5-40")
  })

  it("keeps grade-based placement for strong rows without a relevance key (legacy payloads)", () => {
    const chain = relChain([
      {
        source_id: "s1",
        label: "train.py · lines 1-40",
        file_path: "train.py",
        evidence_quality_grade: "implementation_body",
        selection_reason: "model training loop",
        github_line_url: "https://github.com/octocat/Hello-World/blob/main/train.py#L1-L40",
      } as SkillReportStandaloneGitHubRow,
    ])
    render(
      <SkillReportView
        report={skillReport({ projects: [chain], proof_chains: [chain], github: [], standalone_evidence: emptyStandalone() })}
      />,
    )
    expect(screen.getByTestId("github-primary-band")).toHaveTextContent("train.py · lines 1-40")
  })
})

// ── Proof-source relationship labels ─────────────────────────────────────────
// The safe, recruiter-facing vocabulary that describes how each attached proof
// source relates to a claim. It must NEVER infer evidence strength (authorship,
// implementation, or time-based proof) from a source's mere presence.
describe("PROOF_SOURCE_RELATIONSHIP — neutral, evidence-strength-safe labels", () => {
  it("does not describe repo-level GitHub as implementation proof", () => {
    const label = PROOF_SOURCE_RELATIONSHIP["GitHub Proof"]
    // Weak/repo-level GitHub presence must not read as authorship/implementation.
    expect(label).not.toMatch(/explains the implementation/i)
    expect(label).not.toMatch(/\bimplement/i)
    // Safe default: attached for code/repository review.
    expect(label).toBe("GitHub evidence is attached for code/repository review")
  })

  it("does not describe timestamp/video evidence as showing work over time", () => {
    const label = PROOF_SOURCE_RELATIONSHIP["Video Evidence"]
    // Transcript/timestamp-only chips must not claim time-based proof of work.
    expect(label).not.toMatch(/shows the work over time/i)
    expect(label).not.toMatch(/over time/i)
    // Safe default: recorded explanation moments.
    expect(label).toBe("Video/timestamp evidence provides recorded explanation moments")
  })

  it("renders neutral, safe descriptions for every source", () => {
    expect(PROOF_SOURCE_RELATIONSHIP).toEqual({
      "GitHub Proof": "GitHub evidence is attached for code/repository review",
      "Website Proof": "Website evidence shows observed runtime/product behavior",
      "Document Proof": "Document evidence corroborates the project claim",
      "Project Defense": "Project Defense provides candidate explanation",
      "Video Evidence": "Video/timestamp evidence provides recorded explanation moments",
    })
    // No numeric scores leak through any label.
    for (const label of Object.values(PROOF_SOURCE_RELATIONSHIP)) {
      expect(label).not.toMatch(/%|\bscore\b/i)
    }
  })
})
