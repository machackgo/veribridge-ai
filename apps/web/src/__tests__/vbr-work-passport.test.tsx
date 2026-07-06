/**
 * Private Verified Work Passport — frontend rendering tests.
 *
 * Covers: evidence-source groups/badges, grouped skills, per-project report
 * actions, and the publish / copy / unpublish controls.
 */

import { render, screen, waitFor, fireEvent } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { PrivatePassportView } from "../app/student/vbr/passport/PrivatePassportView"
import type {
  PrivateWorkPassport,
  VaultSkillPreview,
  VaultSkillSummary,
  WorkPassportStatus,
} from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/vbr-api")>()),
  getPrivateWorkPassport: vi.fn(),
  getWorkPassportStatus: vi.fn(),
  publishWorkPassport: vi.fn(),
  unpublishWorkPassport: vi.fn(),
  publishVBRProjectReport: vi.fn(),
}))

import {
  getPrivateWorkPassport,
  getWorkPassportStatus,
  publishWorkPassport,
  unpublishWorkPassport,
  publishVBRProjectReport,
} from "@/lib/vbr-api"

function makePassport(overrides: Partial<PrivateWorkPassport> = {}): PrivateWorkPassport {
  return {
    candidate_display_name: "Jordan Rivera",
    headline: "Full-stack builder",
    summary: "I ship and defend real projects.",
    is_published: false,
    public_slug: null,
    public_path: null,
    published_at: null,
    skills: [
      { skill: "Python", status: "Demonstrated", evidence_chip_count: 2, project_count: 1, evidence_sources: ["GitHub Proof"], projects: [], evidence_chips: [], notes: "", limitations: [] },
      { skill: "React", status: "Partially demonstrated", evidence_chip_count: 1, project_count: 1, evidence_sources: [], projects: [], evidence_chips: [], notes: "", limitations: [] },
    ],
    projects: [
      {
        project_id: "proj-1",
        project_title: "Skill Evidence Tracker",
        project_summary: "Tracks student skill evidence.",
        repo_full_name: "octocat/Hello-World",
        claimed_skills: ["Python", "React"],
        evidence_sources: ["GitHub Proof", "Document Proof", "Project Defense", "Video Evidence"],
        evidence_package: {
          github_proof_attached: true,
          documents_count: 1,
          website_proofs_count: 0,
          project_defense_completed: true,
          video_defense_recorded: true,
          video_evidence_chip_count: 1,
        },
        attempt_count: 1,
        report: { is_public: false, public_token: null, public_path: null, published_at: null },
      },
    ],
    evidence_source_counts: { "GitHub Proof": 1, "Document Proof": 1, "Project Defense": 1, "Video Evidence": 1 },
    project_count: 1,
    published_report_count: 0,
    limitations: ["Skills and evidence are shown with qualitative labels only — never numeric trust scores."],
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

beforeEach(() => {
  vi.mocked(getPrivateWorkPassport).mockReset()
  vi.mocked(getWorkPassportStatus).mockReset()
  vi.mocked(publishWorkPassport).mockReset()
  vi.mocked(unpublishWorkPassport).mockReset()
  vi.mocked(publishVBRProjectReport).mockReset()
})

describe("PrivatePassportView", () => {
  it("renders evidence source groups/badges (no old 'Evidence-Backed Skills' section)", async () => {
    const p = makePassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    expect(await screen.findByTestId("passport-header")).toBeInTheDocument()
    expect(screen.getByText("Jordan Rivera")).toBeInTheDocument()
    expect(screen.getByTestId("evidence-source-counts")).toBeInTheDocument()
    expect(screen.getAllByTestId("evidence-source-count").length).toBeGreaterThan(0)
    // The old redundant "Evidence-Backed Skills" / "Grouped by skill" section is gone.
    expect(screen.queryByText(/Evidence-Backed Skills/i)).not.toBeInTheDocument()
    expect(screen.queryByTestId("passport-skill")).not.toBeInTheDocument()
    expect(screen.queryByTestId("skill-expand-toggle")).not.toBeInTheDocument()
  })

  it("renders the passport identity header with education, status and evidence summary", async () => {
    const p = makePassport({
      identity: {
        display_name: "Jordan Rivera",
        headline: "Full-stack builder",
        program: "Computer Science",
        degree_level: "Masters",
        graduation_year: 2026,
        region: "United States",
        education_summary: "Computer Science · Masters · Class of 2026 · United States",
        public_status: "Private only",
        public_path: null,
        last_updated: "2026-01-02T00:00:00Z",
        evidence_source_summary: ["GitHub Proof · 1", "Document Proof · 1"],
        verification_label: "Verified Work Passport",
      },
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    expect(await screen.findByTestId("passport-identity-header")).toBeInTheDocument()
    expect(screen.getByTestId("passport-identity-name")).toHaveTextContent("Jordan Rivera")
    expect(screen.getByTestId("passport-identity-education")).toHaveTextContent("Computer Science")
    expect(screen.getByTestId("passport-identity-status")).toHaveTextContent("Private only")
    expect(screen.getByTestId("passport-identity-evidence-summary")).toHaveTextContent("GitHub Proof · 1")
  })

  it("falls back to a safe placeholder name when identity has no display name", async () => {
    const p = makePassport({
      candidate_display_name: null,
      identity: {
        display_name: null,
        headline: "Verified Work Passport",
        program: null,
        degree_level: null,
        graduation_year: null,
        region: null,
        education_summary: "",
        public_status: "Private only",
        public_path: null,
        last_updated: null,
        evidence_source_summary: [],
        verification_label: "Verified Work Passport",
      },
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    expect(await screen.findByTestId("passport-identity-name")).toHaveTextContent("Verified candidate profile")
  })

  it("shows a merged-attempts badge when duplicate evidence is grouped into one card", async () => {
    const base = makePassport()
    const p = makePassport({
      projects: [{ ...base.projects[0], attempt_count: 9 }],
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-project-card")
    // One card, not nine, with a badge surfacing the merged attempt count.
    expect(screen.getAllByTestId("passport-project-card")).toHaveLength(1)
    expect(screen.getByTestId("attempt-count-badge")).toHaveTextContent("9 attempts merged")
  })

  it("renders project report actions including publish when no report exists", async () => {
    const p = makePassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    expect(await screen.findByTestId("passport-project-card")).toBeInTheDocument()
    expect(screen.getByTestId("project-report-actions")).toBeInTheDocument()
    expect(screen.getByTestId("view-report-preview-link")).toHaveAttribute(
      "href",
      "/student/vbr/projects/proj-1/report",
    )
    expect(screen.getByTestId("publish-report-button")).toBeInTheDocument()
  })

  it("shows copy report link when a project report is already public", async () => {
    const p = makePassport({
      published_report_count: 1,
      projects: [
        {
          ...makePassport().projects[0],
          report: { is_public: true, public_token: "tok-abc", public_path: "/vbr/report/tok-abc", published_at: "2026-01-02T00:00:00Z" },
        },
      ],
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-project-card")

    expect(screen.getByTestId("copy-report-link-button")).toBeInTheDocument()
    expect(screen.queryByTestId("publish-report-button")).not.toBeInTheDocument()
  })

  it("renders publish control, then copy/unpublish after publishing", async () => {
    const p = makePassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
    vi.mocked(publishWorkPassport).mockResolvedValue({
      is_published: true,
      public_slug: "slug123",
      public_path: "/p/slug123",
      published_at: "2026-01-02T00:00:00Z",
      headline: p.headline,
      summary: p.summary,
    })

    render(<PrivatePassportView />)

    const publishBtn = await screen.findByTestId("publish-passport-button")
    fireEvent.click(publishBtn)

    await waitFor(() => expect(screen.getByTestId("passport-public-link")).toBeInTheDocument())
    expect(screen.getByTestId("passport-public-link").textContent).toContain("/p/slug123")
    expect(screen.getByTestId("copy-passport-link-button")).toBeInTheDocument()
    expect(screen.getByTestId("unpublish-passport-button")).toBeInTheDocument()
  })

  it("renders safe empty states with no projects or skills", async () => {
    const p = makePassport({
      skills: [],
      projects: [],
      evidence_source_counts: {},
      project_count: 0,
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    expect(await screen.findByTestId("passport-no-projects")).toBeInTheDocument()
    expect(screen.getByTestId("passport-no-evidence")).toBeInTheDocument()
    // The old "Evidence-Backed Skills" empty state no longer renders.
    expect(screen.queryByTestId("passport-no-skills")).not.toBeInTheDocument()
  })
})

// ── Evidence graph redesign (Phase 1) ─────────────────────────────────────────

function makeVaultSummary(overrides: Partial<VaultSkillSummary> = {}): VaultSkillSummary {
  return {
    skill: "Python",
    skill_slug: "python",
    category: "Programming Language",
    status: "Demonstrated",
    source_labels: ["GitHub Proof"],
    project_ids: ["proj-1"],
    project_titles: ["Skill Evidence Tracker"],
    project_count: 1,
    proof_source_counts: { "GitHub Proof": 2 },
    proof_count: 2,
    attached_count: 1,
    unattached_count: 1,
    has_unattached: true,
    summary: "",
    previews: [],
    more_count: 0,
    limitations: [],
    ...overrides,
  }
}

function makeGraphPassport(overrides: Partial<PrivateWorkPassport> = {}): PrivateWorkPassport {
  return makePassport({
    evidence_graph_overview: {
      project_count: 1,
      published_report_count: 0,
      skills_with_evidence: 2,
      proof_count: 3,
      attached_proof_count: 2,
      unattached_proof_count: 1,
      next_actions: ["Publish a recruiter-safe report for your strongest project."],
    },
    skills: [
      {
        skill: "Python",
        status: "Demonstrated",
        evidence_chip_count: 2,
        project_count: 1,
        evidence_sources: ["GitHub Proof"],
        projects: [],
        evidence_chips: [],
        strongest_project_title: "Skill Evidence Tracker",
        strongest_project_status: "Demonstrated",
        notes: "",
        limitations: [],
      },
    ],
    projects: [
      {
        ...makePassport().projects[0],
        proof_chain: {
          github: true,
          website: false,
          document: true,
          project_defense: true,
          video: true,
          attached_count: 4,
          total_count: 5,
          missing: ["Website Proof"],
        },
        top_skills: [
          { skill: "Python", status: "Demonstrated" },
          { skill: "React", status: "Partially demonstrated" },
        ],
      },
    ],
    vault_skill_summaries: [makeVaultSummary()],
    vault_proof_count: 3,
    vault_unattached_count: 1,
    ...overrides,
  })
}

describe("PrivatePassportView — evidence graph (Phase 1)", () => {
  beforeEach(() => {
    const p = makeGraphPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
  })

  it("renders the Evidence Graph Overview with stats and next actions", async () => {
    render(<PrivatePassportView />)

    expect(await screen.findByTestId("evidence-graph-overview")).toBeInTheDocument()
    const stats = screen.getAllByTestId("overview-stat")
    const byStat = Object.fromEntries(stats.map((el) => [el.getAttribute("data-stat"), el.textContent]))
    expect(byStat["projects"]).toContain("1")
    expect(byStat["published-reports"]).toContain("0")
    expect(byStat["skills-with-evidence"]).toContain("2")
    expect(byStat["attached-proofs"]).toContain("2")
    expect(byStat["unattached-proofs"]).toContain("1")
    expect(screen.getByTestId("overview-next-actions")).toHaveTextContent(
      "Publish a recruiter-safe report",
    )
  })

  it("derives an overview from base fields when the payload has none (older payloads)", async () => {
    const p = makeGraphPassport({ evidence_graph_overview: undefined })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)

    render(<PrivatePassportView />)

    expect(await screen.findByTestId("evidence-graph-overview")).toBeInTheDocument()
    const stats = screen.getAllByTestId("overview-stat")
    const byStat = Object.fromEntries(stats.map((el) => [el.getAttribute("data-stat"), el.textContent]))
    expect(byStat["projects"]).toContain("1")
    expect(byStat["unattached-proofs"]).toContain("1")
  })

  it("renders the Project Portfolio before Skill Intelligence", async () => {
    render(<PrivatePassportView />)

    const portfolio = await screen.findByRole("heading", { name: "Project Portfolio" })
    const skillIntelligence = screen.getByText("Skill Intelligence")
    expect(
      portfolio.compareDocumentPosition(skillIntelligence) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  it("shows proof-chain completeness with present and missing sources on the project card", async () => {
    render(<PrivatePassportView />)

    expect(await screen.findByTestId("project-proof-chain")).toBeInTheDocument()
    const items = screen.getAllByTestId("proof-chain-item")
    expect(items).toHaveLength(5)
    const bySource = Object.fromEntries(items.map((el) => [el.getAttribute("data-source"), el.getAttribute("data-present")]))
    expect(bySource["GitHub Proof"]).toBe("true")
    expect(bySource["Website Proof"]).toBe("false")
    expect(bySource["Project Defense"]).toBe("true")
    // Gaps are stated honestly.
    expect(screen.getByTestId("project-gaps")).toHaveTextContent("Website Proof")
  })

  it("derives the proof chain from evidence sources when the payload has none", async () => {
    const base = makeGraphPassport()
    const p = makeGraphPassport({
      projects: [{ ...base.projects[0], proof_chain: undefined }],
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)

    render(<PrivatePassportView />)

    expect(await screen.findByTestId("project-proof-chain")).toBeInTheDocument()
    const items = screen.getAllByTestId("proof-chain-item")
    const bySource = Object.fromEntries(items.map((el) => [el.getAttribute("data-source"), el.getAttribute("data-present")]))
    // evidence_sources: GitHub, Document, Project Defense, Video — no Website.
    expect(bySource["GitHub Proof"]).toBe("true")
    expect(bySource["Website Proof"]).toBe("false")
  })

  it("shows the project's top demonstrated skills with qualitative labels", async () => {
    render(<PrivatePassportView />)

    const topSkills = await screen.findByTestId("project-top-skills")
    expect(topSkills).toHaveTextContent("Python · Demonstrated")
    expect(topSkills).toHaveTextContent("React · Partially demonstrated")
  })

  it("links the project card to its connected skills section", async () => {
    render(<PrivatePassportView />)

    const link = await screen.findByTestId("view-connected-skills-link")
    expect(link).toHaveAttribute("href", "#skill-intelligence")
  })

  it("shows the strongest related project on the skill card", async () => {
    render(<PrivatePassportView />)

    const strongest = await screen.findByTestId("vault-summary-strongest-project")
    expect(strongest).toHaveTextContent("Skill Evidence Tracker")
    expect(strongest).toHaveTextContent("Demonstrated")
  })

  it("renders the Evidence Vault section with an unattached-proof next action", async () => {
    render(<PrivatePassportView />)

    expect(await screen.findByTestId("evidence-vault-section")).toBeInTheDocument()
    expect(screen.getByTestId("vault-unattached-action")).toHaveTextContent("1 unattached proof item")
  })

  it("confirms all proofs attached when nothing is unattached", async () => {
    const p = makeGraphPassport({ vault_unattached_count: 0 })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)

    render(<PrivatePassportView />)

    expect(await screen.findByTestId("evidence-vault-section")).toBeInTheDocument()
    expect(screen.getByTestId("vault-all-attached")).toBeInTheDocument()
    expect(screen.queryByTestId("vault-unattached-action")).not.toBeInTheDocument()
  })

  it("keeps the Skill Report link working from the skill card", async () => {
    render(<PrivatePassportView />)

    const link = await screen.findByTestId("view-skill-report")
    expect(link).toHaveAttribute("href", "/student/vbr/passport/skills/python")
  })
})

// ── Project ↔ Skill cross-linking (Phase 2) ───────────────────────────────────

function makeCrossLinkedPassport(overrides: Partial<PrivateWorkPassport> = {}): PrivateWorkPassport {
  const base = makeGraphPassport()
  return makeGraphPassport({
    skills: [
      {
        ...base.skills[0],
        strongest_project: {
          project_title: "Skill Evidence Tracker",
          skill_status: "Demonstrated",
          evidence_sources: ["GitHub Proof"],
          report_is_public: false,
          public_report_path: null,
          project_id: "proj-1",
          project_report_path: "/student/vbr/projects/proj-1/report",
        },
      },
    ],
    projects: [
      {
        ...base.projects[0],
        top_skills: [
          {
            skill: "Python",
            status: "Demonstrated",
            skill_slug: "python",
            skill_report_path: "/student/vbr/passport/skills/python",
          },
          // No path/slug from the backend — the view derives a fallback slug.
          { skill: "React", status: "Partially demonstrated" },
        ],
        evidence_relationship_note:
          "This project demonstrates Python and React through GitHub code and Project Defense explanation.",
      },
    ],
    ...overrides,
  })
}

describe("PrivatePassportView — project ↔ skill cross-linking (Phase 2)", () => {
  beforeEach(() => {
    const p = makeCrossLinkedPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
  })

  it("renders project top skills as links into their Skill Reports", async () => {
    render(<PrivatePassportView />)

    const chips = await screen.findAllByTestId("project-top-skill")
    expect(chips).toHaveLength(2)
    expect(chips[0]).toHaveAttribute("href", "/student/vbr/passport/skills/python")
    // Backend path missing → fallback slug still lands on the Skill Report route.
    expect(chips[1]).toHaveAttribute("href", "/student/vbr/passport/skills/react")
    expect(screen.getAllByTestId("project-skill-evidence-label")[0]).toHaveTextContent(
      "View skill evidence →",
    )
  })

  it("renders the project's evidence relationship note", async () => {
    render(<PrivatePassportView />)

    expect(await screen.findByTestId("project-relationship-note")).toHaveTextContent(
      "This project demonstrates Python and React through GitHub code and Project Defense explanation.",
    )
  })

  it("links the skill card's strongest project to its project report preview", async () => {
    render(<PrivatePassportView />)

    const strongest = await screen.findByTestId("vault-summary-strongest-project")
    expect(strongest).toHaveTextContent("This skill is strongest in Skill Evidence Tracker")
    expect(screen.getByTestId("strongest-project-evidence-link")).toHaveAttribute(
      "href",
      "/student/vbr/projects/proj-1/report",
    )
  })

  it("renders a compact proof-chain preview on the skill card", async () => {
    render(<PrivatePassportView />)

    expect(await screen.findByTestId("skill-proof-chain-preview")).toBeInTheDocument()
    const items = screen.getAllByTestId("skill-chain-item")
    expect(items).toHaveLength(5)
    const bySource = Object.fromEntries(
      items.map((el) => [el.getAttribute("data-source"), el.getAttribute("data-present")]),
    )
    // proof_source_counts: GitHub Proof only.
    expect(bySource["GitHub Proof"]).toBe("true")
    expect(bySource["Website Proof"]).toBe("false")
  })

  it("keeps unattached vault evidence honest on the skill card", async () => {
    const p = makeCrossLinkedPassport({
      vault_skill_summaries: [
        makeVaultSummary({ attached_count: 0, unattached_count: 2, has_unattached: true }),
      ],
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)

    render(<PrivatePassportView />)

    expect(await screen.findByTestId("vault-summary-unattached-note")).toHaveTextContent(
      "Additional vault evidence exists but is not attached to a project report.",
    )
  })

  it("does not show the unattached note when attached proof dominates", async () => {
    const p = makeCrossLinkedPassport({
      vault_skill_summaries: [
        makeVaultSummary({ attached_count: 3, unattached_count: 1, has_unattached: true }),
      ],
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)

    render(<PrivatePassportView />)
    await screen.findByTestId("vault-skill-dashboard")

    expect(screen.queryByTestId("vault-summary-unattached-note")).not.toBeInTheDocument()
  })
})

// ── Proof Attachment Intelligence (Phase 3) ───────────────────────────────────

function makeIntelligencePassport(overrides: Partial<PrivateWorkPassport> = {}): PrivateWorkPassport {
  const base = makeGraphPassport()
  return makeGraphPassport({
    projects: [
      {
        ...base.projects[0],
        chain_label: "Missing runtime proof",
        proof_chain_gaps: [
          {
            source: "Website Proof",
            gap_label: "Missing runtime proof",
            action: "Attach Website Proof to complete runtime behavior evidence.",
          },
        ],
        suggested_attachments: [
          {
            suggestion_id_safe: "attach-abc123",
            proof_type: "Website Proof",
            proof_title: "https://skill-evidence-tracker.vercel.app",
            confidence_label: "Likely match",
            suggestion_reason:
              "Website Proof may belong to “Skill Evidence Tracker” because the website domain matches the project title.",
            action_label: "Review and attach proof",
          },
        ],
        next_best_action:
          "Review and attach the suggested Website Proof “https://skill-evidence-tracker.vercel.app” (likely match).",
      },
    ],
    unattached_proof_summary: {
      unattached_count: 3,
      suggestion_count: 1,
      unmatched_count: 2,
      suggestions: [
        {
          suggestion_id_safe: "attach-abc123",
          proof_type: "Website Proof",
          proof_title: "https://skill-evidence-tracker.vercel.app",
          proof_count: 1,
          likely_project_title: "Skill Evidence Tracker",
          likely_project_ref_safe: "/student/vbr/projects/proj-1/report",
          likely_skill_names: ["React"],
          suggestion_reason:
            "Website Proof may belong to “Skill Evidence Tracker” because the website domain matches the project title and the proof and the project share claimed skills (React).",
          evidence_basis_chips: ["Matching website domain", "Matching skill"],
          confidence_label: "Likely match",
          attachment_status: "Not attached to a VBR project",
          limitation:
            "Suggested match only — based on matching safe metadata (titles, repository, domain, skills), not verified evidence. Review before attaching; nothing is attached automatically.",
          action_label: "Review and attach proof",
        },
      ],
    },
    vault_skill_summaries: [
      makeVaultSummary({
        strengthening_actions: [
          "Python has evidence, but 1 proof item(s) are not attached to a project — review and attach them to strengthen a project's proof chain.",
        ],
      }),
    ],
    ...overrides,
  })
}

describe("PrivatePassportView — Proof Attachment Intelligence (Phase 3)", () => {
  beforeEach(() => {
    const p = makeIntelligencePassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
  })

  it("renders the Proof Attachment Intelligence section with a suggestion card", async () => {
    render(<PrivatePassportView />)

    expect(await screen.findByTestId("proof-attachment-intelligence")).toBeInTheDocument()
    const suggestion = screen.getByTestId("attachment-suggestion")
    expect(suggestion).toHaveAttribute("data-proof-type", "Website Proof")
    expect(screen.getByTestId("suggestion-confidence")).toHaveTextContent("Likely match")
    expect(screen.getByTestId("suggestion-project")).toHaveTextContent("Skill Evidence Tracker")
    expect(screen.getByTestId("suggestion-action-label")).toHaveTextContent("Review and attach proof")
    expect(screen.getByTestId("suggestion-open-project")).toHaveAttribute(
      "href",
      "/student/vbr/projects/proj-1/report",
    )
  })

  it("renders the suggestion reason, evidence basis chips and honest limitation", async () => {
    render(<PrivatePassportView />)

    expect(await screen.findByTestId("suggestion-reason")).toHaveTextContent("may belong to")
    const chips = screen.getAllByTestId("suggestion-basis-chip")
    expect(chips.map((c) => c.textContent)).toEqual(["Matching website domain", "Matching skill"])
    expect(screen.getByTestId("suggestion-limitation")).toHaveTextContent(
      "nothing is attached automatically",
    )
  })

  it("lists projects to strengthen and skills with unattached evidence", async () => {
    render(<PrivatePassportView />)

    const projectRow = await screen.findByTestId("project-to-strengthen")
    expect(projectRow).toHaveTextContent("Skill Evidence Tracker")
    expect(projectRow).toHaveTextContent("Missing runtime proof")
    const skillChip = screen.getByTestId("skill-with-unattached")
    expect(skillChip).toHaveTextContent("Python · 1 unattached")
    expect(skillChip).toHaveAttribute("href", "/student/vbr/passport/skills/python")
    // Unmatched proofs are stated honestly — never guessed onto a project.
    expect(screen.getByTestId("suggestions-unmatched-note")).toHaveTextContent(
      "2 unattached proof item(s) had no safe project match",
    )
  })

  it("renders chain label, gap actions and next best action on the project card", async () => {
    render(<PrivatePassportView />)

    expect(await screen.findByTestId("project-chain-label")).toHaveTextContent("Missing runtime proof")
    const gap = screen.getByTestId("project-chain-gap")
    expect(gap).toHaveAttribute("data-source", "Website Proof")
    expect(gap).toHaveTextContent("Attach Website Proof to complete runtime behavior evidence.")
    expect(screen.getByTestId("project-next-action")).toHaveTextContent("Suggested next action:")
    const row = screen.getByTestId("project-suggested-attachment")
    expect(row).toHaveTextContent("Likely match")
    expect(row).toHaveTextContent("https://skill-evidence-tracker.vercel.app")
  })

  it("renders strengthening actions on the skill card", async () => {
    render(<PrivatePassportView />)

    const action = await screen.findByTestId("skill-strengthening-action")
    expect(action).toHaveTextContent("review and attach them to strengthen")
  })

  it("hides the section entirely when nothing is unattached and nothing is suggested", async () => {
    const p = makeIntelligencePassport({
      unattached_proof_summary: {
        unattached_count: 0,
        suggestion_count: 0,
        unmatched_count: 0,
        suggestions: [],
      },
      vault_unattached_count: 0,
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)

    render(<PrivatePassportView />)
    await screen.findByTestId("evidence-graph-overview")

    expect(screen.queryByTestId("proof-attachment-intelligence")).not.toBeInTheDocument()
  })

  it("keeps Phase 2 cross-links working alongside Phase 3 (skill report + project report links)", async () => {
    render(<PrivatePassportView />)

    // Project → Skill Report links still render.
    const chips = await screen.findAllByTestId("project-top-skill")
    expect(chips[0]).toHaveAttribute("href", "/student/vbr/passport/skills/python")
    // Skill card → Skill Report link still works.
    expect(screen.getByTestId("view-skill-report")).toHaveAttribute(
      "href",
      "/student/vbr/passport/skills/python",
    )
    // Project report preview link still works.
    expect(screen.getByTestId("view-report-preview-link")).toHaveAttribute(
      "href",
      "/student/vbr/projects/proj-1/report",
    )
  })
})

// ── Attachment Intelligence Cleanup (Step 4) ──────────────────────────────────

import type { ProofAttachmentEntry, ProofAttachmentOverview } from "@/lib/vbr-api"

function makeEntry(overrides: Partial<ProofAttachmentEntry> = {}): ProofAttachmentEntry {
  return {
    entry_id_safe: `att-${Math.random().toString(16).slice(2, 14)}`,
    proof_type: "Document Proof",
    display_title: "Final Year Project Report",
    source_label: "Document Proof",
    attachment_state: "attached",
    relation_reason: "exact_document_attachment",
    relation_strength: "deterministic",
    reason_label: "Document attached to the project",
    status_label: "Attached",
    project_titles: ["Skill Evidence Tracker"],
    project_refs_safe: ["/student/vbr/projects/proj-1/report"],
    skill_names: ["Python"],
    duplicate_count: 1,
    ...overrides,
  }
}

function makeOverview(overrides: Partial<ProofAttachmentOverview> = {}): ProofAttachmentOverview {
  const attached = [makeEntry({ entry_id_safe: "att-a1" })]
  const suggested = [
    makeEntry({
      entry_id_safe: "att-s1",
      attachment_state: "suggested",
      relation_reason: "title_similarity_suggestion",
      relation_strength: "likely",
      reason_label: "Titles look similar — review before attaching",
      status_label: "Suggested — not counted until attached",
      display_title: "Tracker Design Notes",
    }),
  ]
  const unattached = [
    makeEntry({
      entry_id_safe: "att-u1",
      attachment_state: "unattached",
      relation_reason: "no_match",
      relation_strength: "none",
      reason_label: "No matching project found",
      status_label: "Not attached to a project",
      display_title: "Old Elsewhere Notes",
      project_titles: [],
      project_refs_safe: [],
      duplicate_count: 2,
    }),
  ]
  return {
    attached,
    suggested,
    unattached,
    attached_count: attached.length,
    suggested_count: suggested.length,
    unattached_count: unattached.length,
    note: "Suggested — not counted until attached",
    ...overrides,
  }
}

describe("PrivatePassportView — Attachment Intelligence Cleanup (Step 4)", () => {
  it("renders Attached / Suggested / Unattached as separated, labelled sections", async () => {
    const p = makePassport({
      vault_proof_count: 3,
      vault_unattached_count: 2,
      attachment_overview: makeOverview(),
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    expect(await screen.findByTestId("attachment-overview")).toBeInTheDocument()
    expect(screen.getByTestId("attachment-attached-section")).toBeInTheDocument()
    expect(screen.getByTestId("attachment-suggested-section")).toBeInTheDocument()
    expect(screen.getByTestId("attachment-unattached-section")).toBeInTheDocument()

    // Suggested evidence is explicitly "not counted until attached".
    const suggestedSection = screen.getByTestId("attachment-suggested-section")
    expect(suggestedSection).toHaveTextContent("Suggested — not counted until attached")

    // The suggested entry links to its likely project; the attached entry to its project.
    expect(screen.getAllByTestId("attachment-entry-project-link").length).toBeGreaterThan(0)

    // The deduped unattached entry shows an honest duplicate note, once.
    expect(screen.getByTestId("attachment-entry-duplicates")).toHaveTextContent("2 duplicate rows collapsed")
  })

  it("renders each deduplicated proof exactly once (no duplicate cards, no duplicate keys)", async () => {
    const p = makePassport({
      vault_proof_count: 3,
      vault_unattached_count: 2,
      attachment_overview: makeOverview(),
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {})
    render(<PrivatePassportView />)

    await screen.findByTestId("attachment-overview")
    const entries = screen.getAllByTestId("attachment-entry")
    // One card per deduplicated entry: 1 attached + 1 suggested + 1 unattached.
    expect(entries).toHaveLength(3)
    // React duplicate-key warnings must not happen.
    const keyWarnings = consoleError.mock.calls.filter((args) =>
      String(args[0]).includes("same key"),
    )
    expect(keyWarnings).toHaveLength(0)
    consoleError.mockRestore()
  })

  it("shows the suggested count as its own overview stat — never merged into attached", async () => {
    const p = makePassport({
      evidence_graph_overview: {
        project_count: 1,
        published_report_count: 0,
        skills_with_evidence: 2,
        proof_count: 3,
        attached_proof_count: 1,
        suggested_proof_count: 1,
        unattached_proof_count: 1,
        next_actions: [],
      },
      attachment_overview: makeOverview(),
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    await screen.findByTestId("evidence-graph-overview")
    const stat = (name: string) => document.querySelector(`[data-testid="overview-stat"][data-stat="${name}"]`)
    expect(stat("attached-proofs")).toHaveTextContent("1")
    const suggestedStat = stat("suggested-proofs")
    expect(suggestedStat).toHaveTextContent("1")
    expect(suggestedStat).toHaveTextContent("Suggested — not counted until attached")
    expect(stat("unattached-proofs")).toHaveTextContent("1")
  })

  it("renders no attachment overview when the payload omits it (older backend)", async () => {
    const p = makePassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    expect(await screen.findByTestId("passport-header")).toBeInTheDocument()
    expect(screen.queryByTestId("attachment-overview")).not.toBeInTheDocument()
  })
})

// ── Attachment Intelligence Cleanup — browser polish ──────────────────────────

function makeVaultPreview(overrides: Partial<VaultSkillPreview> = {}): VaultSkillPreview {
  return {
    proof_type: "Document Proof",
    title: "Design Doc",
    safe_location: "page 2",
    safe_summary: "Overview of the design.",
    is_attached_to_project: false,
    public_safe: true,
    ...overrides,
  }
}

describe("PrivatePassportView — browser polish (dedupe + clean counts)", () => {
  it("shows the clean deduplicated attachment_overview count in prominent copy, not the raw vault count", async () => {
    const p = makeGraphPassport({
      // Raw vault rows (with duplicates) is large; the clean deduped count is small.
      vault_unattached_count: 519,
      attachment_overview: makeOverview({ unattached_count: 32 }),
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    // Skill Intelligence headline copy uses the clean count …
    const summaryCopy = await screen.findByTestId("vault-unattached-summary")
    expect(summaryCopy).toHaveTextContent("32 unattached proof item")
    expect(summaryCopy).not.toHaveTextContent("519")
    // … and so does the Evidence Vault next-action copy.
    const action = screen.getByTestId("vault-unattached-action")
    expect(action).toHaveTextContent("32 unattached proof item")
    expect(action).not.toHaveTextContent("519")
  })

  it("collapses duplicate-looking suggestions into one card with a grouped proof count", async () => {
    const dupSuggestion = {
      suggestion_id_safe: "attach-dup",
      proof_type: "Document Proof",
      proof_title: "Skill Evidence Tracker Report",
      proof_count: 1,
      likely_project_title: "Skill Evidence Tracker",
      likely_project_ref_safe: "/student/vbr/projects/proj-1/report",
      likely_skill_names: ["Python"],
      suggestion_reason: "Document Proof may belong to “Skill Evidence Tracker”.",
      evidence_basis_chips: ["Matching document title"],
      confidence_label: "Likely match",
      attachment_status: "Not attached to a VBR project",
      limitation: "Suggested match only — nothing is attached automatically.",
      action_label: "Review and attach proof",
    }
    const p = makeGraphPassport({
      unattached_proof_summary: {
        unattached_count: 2,
        suggestion_count: 2,
        unmatched_count: 0,
        suggestions: [
          { ...dupSuggestion, suggestion_id_safe: "attach-dup-a" },
          { ...dupSuggestion, suggestion_id_safe: "attach-dup-b" },
        ],
      },
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    await screen.findByTestId("proof-attachment-intelligence")
    const cards = screen.getAllByTestId("attachment-suggestion")
    expect(cards).toHaveLength(1)
    // The single card sums the grouped proof count of the collapsed rows.
    expect(cards[0]).toHaveTextContent("2 proof items grouped")
  })

  it("collapses identical skill preview rows but keeps distinct GitHub locations separate", async () => {
    const dupPreview = makeVaultPreview()
    const p = makeGraphPassport({
      vault_skill_summaries: [
        makeVaultSummary({
          previews: [dupPreview, { ...dupPreview }, { ...dupPreview }],
          more_count: 2,
        }),
      ],
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    // Three identical-looking preview rows collapse to one.
    const previews = await screen.findAllByTestId("vault-skill-preview")
    expect(previews).toHaveLength(1)
  })

  it("keeps distinct GitHub file/line preview rows separate", async () => {
    const p = makeGraphPassport({
      vault_skill_summaries: [
        makeVaultSummary({
          previews: [
            makeVaultPreview({
              proof_type: "GitHub Proof",
              title: "octocat/Hello-World",
              safe_location: "src/main.py:10",
              safe_summary: "implementation body",
            }),
            makeVaultPreview({
              proof_type: "GitHub Proof",
              title: "octocat/Hello-World",
              safe_location: "src/utils.py:22",
              safe_summary: "implementation body",
            }),
          ],
        }),
      ],
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    const previews = await screen.findAllByTestId("vault-skill-preview")
    expect(previews).toHaveLength(2)
  })

  it("collapses preview rows with the same visible title/location but a different hidden safe_summary", async () => {
    // PreviewRow renders `title || safe_summary` + safe_location. Two rows with
    // the same visible title and location but a differing hidden safe_summary
    // render identically, so they must collapse to a single row.
    const p = makeGraphPassport({
      vault_skill_summaries: [
        makeVaultSummary({
          previews: [
            makeVaultPreview({
              proof_type: "Document Proof",
              title: "Design Doc",
              safe_location: "page 2",
              safe_summary: "Overview of the design.",
            }),
            makeVaultPreview({
              proof_type: "Document Proof",
              title: "Design Doc",
              safe_location: "page 2",
              safe_summary: "A different hidden summary that never renders.",
            }),
          ],
        }),
      ],
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    const previews = await screen.findAllByTestId("vault-skill-preview")
    expect(previews).toHaveLength(1)
    expect(previews[0]).toHaveTextContent("Design Doc")
  })

  it("shows the clean attachment_overview count (not the raw vault row count) in the unmatched-proof note", async () => {
    // Regression: the unmatched-proof note used to render unmatched_count, which
    // is derived from the raw vault_unattached_count (519-style row count) and
    // contradicts the clean, deduplicated Evidence Graph Overview. It must use
    // the clean attachment_overview.unattached_count (32) instead.
    const p = makeIntelligencePassport({
      vault_unattached_count: 519,
      unattached_proof_summary: {
        unattached_count: 519,
        suggestion_count: 0,
        unmatched_count: 519,
        suggestions: [],
      },
      attachment_overview: makeOverview({ unattached_count: 32 }),
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    const { container } = render(<PrivatePassportView />)

    const note = await screen.findByTestId("suggestions-unmatched-note")
    expect(note).toHaveTextContent("32 unattached proof item(s) had no safe project match")
    expect(note).not.toHaveTextContent("519")
    // The raw 519-style row count appears nowhere on the rendered page.
    expect(container).not.toHaveTextContent("519")
  })
})

describe("PrivatePassportView — Step 5 recruiter-ready publishing", () => {
  it("shows 'Report private' with a not-on-public-passport note and a publish CTA", async () => {
    const p = makePassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-project-card")

    const state = screen.getByTestId("project-report-state")
    expect(state).toHaveAttribute("data-state", "private")
    expect(state).toHaveTextContent("Report private")
    expect(screen.getByTestId("publish-report-button")).toBeInTheDocument()
    expect(screen.getByTestId("report-visibility-note")).toHaveTextContent(
      "will not appear on your public Passport until you publish",
    )
    expect(screen.queryByTestId("open-public-report-link")).not.toBeInTheDocument()
  })

  // Report publishing and Passport publishing are independent (Step 5): a report
  // can be publicly live by direct link while the public Passport is unpublished.
  // The visibility note must stay correct in both Passport states.
  function makePublishedReportPassport(overrides: Partial<PrivateWorkPassport> = {}): PrivateWorkPassport {
    return makePassport({
      published_report_count: 1,
      projects: [
        {
          ...makePassport().projects[0],
          report: {
            is_public: true,
            public_token: "tok-abc",
            public_path: "/vbr/report/tok-abc",
            published_at: "2026-01-02T00:00:00Z",
          },
        },
      ],
      ...overrides,
    })
  }

  // The published-report visibility note now uses state-independent wording so it
  // can never go stale when the Passport is published/unpublished without a reload.
  // ("featured whenever your public Passport is published" is true in every state.)
  const PUBLISHED_NOTE = "featured whenever your public Passport is published"
  // Phrasing that would be false/stale if it depended on a possibly-stale Passport state.
  const STALE_PHRASE = "appears on your public Passport"

  it("published report + published Passport: note uses correct state-independent wording", async () => {
    const p = makePublishedReportPassport({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-project-card")

    const state = screen.getByTestId("project-report-state")
    expect(state).toHaveAttribute("data-state", "published")
    expect(state).toHaveTextContent("Report published")
    expect(screen.getByTestId("copy-report-link-button")).toBeInTheDocument()
    expect(screen.getByTestId("open-public-report-link")).toHaveAttribute(
      "href",
      expect.stringContaining("/vbr/report/tok-abc"),
    )
    const note = screen.getByTestId("report-visibility-note")
    expect(note).toHaveTextContent("public link is live")
    expect(note).toHaveTextContent(PUBLISHED_NOTE)
    // Never uses the state-dependent phrasing that could go stale.
    expect(note).not.toHaveTextContent(STALE_PHRASE)
    expect(screen.queryByTestId("publish-report-button")).not.toBeInTheDocument()
  })

  it("published report + unpublished Passport: note uses correct state-independent wording", async () => {
    // Default makePassport() is is_published:false, so the Passport is unpublished.
    const p = makePublishedReportPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-project-card")

    const state = screen.getByTestId("project-report-state")
    expect(state).toHaveAttribute("data-state", "published")
    // The direct public report link is still live independent of the Passport.
    expect(screen.getByTestId("open-public-report-link")).toHaveAttribute(
      "href",
      expect.stringContaining("/vbr/report/tok-abc"),
    )
    const note = screen.getByTestId("report-visibility-note")
    // Must NOT claim it appears on the public Passport while the Passport is unpublished.
    expect(note).not.toHaveTextContent(STALE_PHRASE)
    // Same wording regardless of Passport state — always correct.
    expect(note).toHaveTextContent("public link is live")
    expect(note).toHaveTextContent(PUBLISHED_NOTE)
  })

  it("does not render the stale project-card phrase anywhere for a published report", async () => {
    const p = makePublishedReportPassport({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    const { container } = render(<PrivatePassportView />)
    await screen.findByTestId("passport-project-card")

    expect(container).not.toHaveTextContent(STALE_PHRASE)
  })

  it("publish transition without reload keeps correct (non-stale) project-card wording", async () => {
    // Start: report published, Passport unpublished. Then publish the Passport in
    // PassportPublishControls (local state only — ProjectCard receives the static
    // initial passport.is_published, so its wording must not depend on it).
    const p = makePublishedReportPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
    vi.mocked(publishWorkPassport).mockResolvedValue({
      is_published: true,
      public_slug: "slug123",
      public_path: "/p/slug123",
      published_at: "2026-01-03T00:00:00Z",
      headline: p.headline,
      summary: p.summary,
    })

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-project-card")

    const noteBefore = screen.getByTestId("report-visibility-note").textContent
    fireEvent.click(screen.getByTestId("publish-passport-button"))

    // Passport controls flip to the published state...
    await screen.findByTestId("passport-public-badge")

    // ...but the project-card note is unchanged and never shows the stale phrase.
    const note = screen.getByTestId("report-visibility-note")
    expect(note).not.toHaveTextContent(STALE_PHRASE)
    expect(note).toHaveTextContent(PUBLISHED_NOTE)
    expect(note.textContent).toBe(noteBefore)
  })

  it("unpublish transition without reload keeps correct (non-stale) project-card wording", async () => {
    // Start: report published, Passport published. Then unpublish the Passport in
    // PassportPublishControls. The project-card wording must stay correct.
    const p = makePublishedReportPassport({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
    vi.mocked(unpublishWorkPassport).mockResolvedValue({
      is_published: false,
      public_slug: null,
      public_path: null,
      published_at: null,
      headline: p.headline,
      summary: p.summary,
    })

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-project-card")

    const noteBefore = screen.getByTestId("report-visibility-note").textContent
    fireEvent.click(screen.getByTestId("unpublish-passport-button"))

    // Passport controls flip to the private state...
    await screen.findByTestId("passport-private-badge")

    // ...and the project-card note is unchanged — still correct, never overclaims.
    const note = screen.getByTestId("report-visibility-note")
    expect(note).not.toHaveTextContent(STALE_PHRASE)
    expect(note).toHaveTextContent(PUBLISHED_NOTE)
    expect(note.textContent).toBe(noteBefore)
  })

  it("publishing a report flips the card to the published state with correct wording", async () => {
    const p = makePassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
    vi.mocked(publishVBRProjectReport).mockResolvedValue({
      project_id: "proj-1",
      is_public: true,
      public_token: "tok-new",
      public_path: "/vbr/report/tok-new",
      published_at: "2026-01-03T00:00:00Z",
    })

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-project-card")
    fireEvent.click(screen.getByTestId("publish-report-button"))

    await waitFor(() =>
      expect(screen.getByTestId("project-report-state")).toHaveAttribute("data-state", "published"),
    )
    expect(screen.getByTestId("open-public-report-link")).toHaveAttribute(
      "href",
      expect.stringContaining("/vbr/report/tok-new"),
    )
    // Passport is unpublished (default), so the note must not overclaim public-Passport visibility.
    const note = screen.getByTestId("report-visibility-note")
    expect(note).not.toHaveTextContent(STALE_PHRASE)
    expect(note).toHaveTextContent("public link is live")
    expect(note).toHaveTextContent(PUBLISHED_NOTE)
  })

  it("shows 'Needs report' and no publish CTA when the project has no attached proof", async () => {
    const base = makePassport().projects[0]
    const p = makePassport({
      projects: [
        {
          ...base,
          evidence_sources: [],
          evidence_package: {
            github_proof_attached: false,
            documents_count: 0,
            website_proofs_count: 0,
            project_defense_completed: false,
            video_defense_recorded: false,
            video_evidence_chip_count: 0,
          },
        },
      ],
      evidence_source_counts: {},
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-project-card")

    const state = screen.getByTestId("project-report-state")
    expect(state).toHaveAttribute("data-state", "needs-report")
    expect(state).toHaveTextContent("Needs report")
    expect(screen.queryByTestId("publish-report-button")).not.toBeInTheDocument()
    expect(screen.getByTestId("report-visibility-note")).toHaveTextContent(
      "no attached proof yet",
    )
    // The student can always open the (empty) preview to see what is missing.
    expect(screen.getByTestId("view-report-preview-link")).toBeInTheDocument()
  })
})
