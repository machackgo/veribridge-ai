/**
 * Private Verified Work Passport — frontend rendering tests.
 *
 * Covers: evidence-source groups/badges, grouped skills, per-project report
 * actions, and the publish / copy / unpublish controls.
 */

import { render, screen, waitFor, fireEvent, within } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { PrivatePassportView } from "../app/student/vbr/passport/PrivatePassportView"
import { buildPassportGraph } from "../app/student/vbr/passport/passport-graph"
import { ProofVaultView } from "../app/student/vbr/passport/vault/ProofVaultView"
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

    const header = await screen.findByTestId("passport-header")
    // Scoped: the name also appears in the Verified Passport Card preview above.
    expect(within(header).getByText("Jordan Rivera")).toBeInTheDocument()
    expect(screen.getByTestId("evidence-source-counts")).toBeInTheDocument()
    expect(screen.getAllByTestId("evidence-source-count").length).toBeGreaterThan(0)
    // The old redundant "Evidence-Backed Skills" / "Grouped by skill" section is gone.
    // Case-sensitive exact match: the new Verified Passport Card preview has an
    // "Evidence-backed skills" (lowercase) label that must NOT trip this guard.
    expect(screen.queryByText("Evidence-Backed Skills")).not.toBeInTheDocument()
    expect(screen.queryByTestId("passport-skill")).not.toBeInTheDocument()
    expect(screen.queryByTestId("skill-expand-toggle")).not.toBeInTheDocument()
  })

  it("shows program + status on the compact card and education in the candidate summary", async () => {
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

    // Identity now lives on the compact card (no duplicate identity-header block).
    const card = await screen.findByTestId("passport-card-private")
    expect(within(card).getByTestId("passport-card-program")).toHaveTextContent("Computer Science")
    expect(within(card).getByTestId("passport-card-status")).toHaveTextContent("Private only")
    // The slimmed candidate-summary detail carries the full education line.
    expect(screen.getByTestId("passport-education")).toHaveTextContent("Computer Science · Masters · Class of 2026")
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
    const card = await screen.findByTestId("passport-card-private")
    expect(within(card).getByTestId("passport-card-name")).toHaveTextContent("Verified candidate profile")
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

  it("renders the Evidence Graph Overview summary chips without maintenance stats", async () => {
    render(<PrivatePassportView />)

    expect(await screen.findByTestId("evidence-graph-overview")).toBeInTheDocument()
    const stats = screen.getAllByTestId("overview-stat")
    const byStat = Object.fromEntries(stats.map((el) => [el.getAttribute("data-stat"), el.textContent]))
    expect(byStat["projects"]).toContain("1")
    expect(byStat["published-reports"]).toContain("0")
    expect(byStat["skills-with-evidence"]).toContain("2")
    expect(byStat["attached-proofs"]).toContain("2")
    // Proof-maintenance stats and next actions moved to the Proof Vault page.
    expect(byStat["unattached-proofs"]).toBeUndefined()
    expect(byStat["suggested-proofs"]).toBeUndefined()
    expect(screen.queryByTestId("overview-next-actions")).not.toBeInTheDocument()
    expect(
      screen.getByText("Your Passport connects projects to skills through evidence-backed proof."),
    ).toBeInTheDocument()
  })

  it("derives an overview from base fields when the payload has none (older payloads)", async () => {
    const p = makeGraphPassport({ evidence_graph_overview: undefined })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)

    render(<PrivatePassportView />)

    expect(await screen.findByTestId("evidence-graph-overview")).toBeInTheDocument()
    const stats = screen.getAllByTestId("overview-stat")
    const byStat = Object.fromEntries(stats.map((el) => [el.getAttribute("data-stat"), el.textContent]))
    expect(byStat["projects"]).toContain("1")
    expect(byStat["attached-proofs"]).toContain("2")
  })

  it("renders a skill-first Skills Evidence Map with projects as a secondary lens", async () => {
    render(<PrivatePassportView />)

    expect(await screen.findByTestId("passport-graph-explorer")).toBeInTheDocument()
    // The map is skill-first: heading + subtitle name the skill→project→evidence model.
    expect(screen.getByText("Skills Evidence Map")).toBeInTheDocument()
    const projectsPanel = screen.getByTestId("passport-projects-panel")
    const skillsPanel = screen.getByTestId("passport-skills-panel")
    expect(projectsPanel).toBeInTheDocument()
    expect(skillsPanel).toBeInTheDocument()
    // Skills come FIRST (primary); the project lens is stacked below (secondary).
    expect(
      skillsPanel.compareDocumentPosition(projectsPanel) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    // The old side-by-side two-column framing ("Projects ↔ Skills") is gone.
    expect(screen.queryByText("Projects ↔ Skills")).not.toBeInTheDocument()
    expect(screen.getAllByTestId("passport-project-card").length).toBeGreaterThan(0)
    expect(screen.getAllByTestId("passport-skill-card").length).toBeGreaterThan(0)
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
    // Long "attach these next" maintenance copy moved to the Proof Vault page.
    expect(screen.queryByTestId("project-gaps")).not.toBeInTheDocument()
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

  it("selects the project from its 'View connected skills' action", async () => {
    render(<PrivatePassportView />)

    const button = await screen.findByTestId("view-connected-skills-button")
    fireEvent.click(button)
    expect(screen.getByTestId("passport-project-card")).toHaveAttribute("data-selected", "true")
    expect(screen.getByTestId("clear-filters-button")).toBeInTheDocument()
  })

  it("shows the strongest related project on the skill card", async () => {
    render(<PrivatePassportView />)

    const cards = await screen.findAllByTestId("passport-skill-card")
    const python = cards.find((c) => c.getAttribute("data-skill") === "Python")!
    const strongest = python.querySelector('[data-testid="skill-top-project"]')
    expect(strongest).toHaveTextContent("Skill Evidence Tracker")
    expect(strongest).toHaveTextContent("Demonstrated")
  })

  it("does not render the Evidence Vault maintenance section on the main Passport", async () => {
    render(<PrivatePassportView />)

    await screen.findByTestId("passport-graph-explorer")
    expect(screen.queryByTestId("evidence-vault-section")).not.toBeInTheDocument()
    expect(screen.queryByTestId("vault-unattached-action")).not.toBeInTheDocument()
    expect(screen.queryByTestId("vault-skill-dashboard")).not.toBeInTheDocument()
  })

  it("keeps the Skill Report link working from the skill card", async () => {
    render(<PrivatePassportView />)

    const cards = await screen.findAllByTestId("passport-skill-card")
    const python = cards.find((c) => c.getAttribute("data-skill") === "Python")!
    expect(python.querySelector('[data-testid="view-skill-report"]')).toHaveAttribute(
      "href",
      "/student/vbr/passport/skills/python",
    )
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
    // Project-card skill CTA is contextual to THIS project (requirement #5).
    expect(screen.getAllByTestId("project-skill-evidence-label")[0]).toHaveTextContent(
      "View Python evidence in this project →",
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

    const cards = await screen.findAllByTestId("passport-skill-card")
    const python = cards.find((c) => c.getAttribute("data-skill") === "Python")!
    expect(python.querySelector('[data-testid="skill-top-project"]')).toHaveTextContent(
      "Strongest in Skill Evidence Tracker",
    )
    expect(python.querySelector('[data-testid="skill-project-evidence-link"]')).toHaveAttribute(
      "href",
      "/student/vbr/projects/proj-1/report",
    )
  })

  it("renders per-project proof chips scoped to the skill→project row (no context-free skill chips)", async () => {
    render(<PrivatePassportView />)

    const cards = await screen.findAllByTestId("passport-skill-card")
    const python = cards.find((c) => c.getAttribute("data-skill") === "Python")!
    // Proof is shown per project row (with context), not as a context-free
    // skill-level chip strip.
    expect(python.querySelector('[data-testid="skill-proof-chips"]')).toBeNull()
    const rowChips = [...python.querySelectorAll('[data-testid="skill-project-proof-chip"]')]
    const sources = rowChips.map((el) => el.getAttribute("data-source"))
    // Python's Skill Evidence Tracker row: GitHub Proof only (no Website).
    expect(sources).toContain("GitHub Proof")
    expect(sources).not.toContain("Website Proof")
  })
})

// ── Contextual proof → project → skill navigation ─────────────────────────────
//
// Every evidence CTA on a skill card must express which project a proof supports
// and route into THAT project's report; Website Proof states its (generic, at
// passport level) source context; and vault-only evidence is labelled unattached
// and routes to the Proof Vault, never to a project report.

function makeContextualPassport(overrides: Partial<PrivateWorkPassport> = {}): PrivateWorkPassport {
  const base = makePassport().projects[0]
  return makePassport({
    skills: [
      {
        skill: "JavaScript",
        status: "Demonstrated",
        evidence_chip_count: 2,
        project_count: 1,
        evidence_sources: ["Website Proof", "GitHub Proof"],
        projects: [
          {
            project_title: "Teachable Machine Image Classification Demo",
            project_id: "proj-tm",
            skill_status: "Demonstrated",
            evidence_sources: ["Website Proof", "GitHub Proof"],
            report_is_public: false,
            public_report_path: null,
          },
        ],
        evidence_chips: [],
        notes: "",
        limitations: [],
      },
      {
        skill: "FastAPI",
        status: "Evidence observed",
        evidence_chip_count: 2,
        project_count: 2,
        evidence_sources: ["Website Proof", "GitHub Proof"],
        projects: [
          {
            project_title: "Boston Smart Accident Risk Rerouting",
            project_id: "proj-boston",
            skill_status: "Evidence observed",
            evidence_sources: ["Website Proof"],
            report_is_public: false,
            public_report_path: null,
          },
          {
            project_title: "Second API Project",
            project_id: "proj-api2",
            skill_status: "Supporting evidence",
            evidence_sources: ["GitHub Proof"],
            report_is_public: false,
            public_report_path: null,
          },
        ],
        evidence_chips: [],
        notes: "",
        limitations: [],
      },
      {
        // Evidence exists but is not attached to any project → vault-only.
        skill: "Rust",
        status: "Evidence observed",
        evidence_chip_count: 1,
        project_count: 0,
        evidence_sources: ["Website Proof"],
        projects: [],
        evidence_chips: [],
        notes: "",
        limitations: [],
      },
    ],
    projects: [
      {
        ...base,
        project_id: "proj-tm",
        project_title: "Teachable Machine Image Classification Demo",
        claimed_skills: ["JavaScript"],
        top_skills: [{ skill: "JavaScript", status: "Demonstrated", skill_slug: "javascript" }],
      },
      {
        ...base,
        project_id: "proj-boston",
        project_title: "Boston Smart Accident Risk Rerouting",
        claimed_skills: ["FastAPI"],
        top_skills: [{ skill: "FastAPI", status: "Evidence observed", skill_slug: "fastapi" }],
      },
      {
        ...base,
        project_id: "proj-api2",
        project_title: "Second API Project",
        claimed_skills: ["FastAPI"],
        top_skills: [{ skill: "FastAPI", status: "Supporting evidence", skill_slug: "fastapi" }],
      },
    ],
    project_count: 3,
    ...overrides,
  })
}

const contextualSkillCard = (name: string) =>
  screen.getAllByTestId("passport-skill-card").find((c) => c.getAttribute("data-skill") === name)!

describe("PrivatePassportView — contextual proof → project → skill navigation", () => {
  beforeEach(() => {
    const p = makeContextualPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
  })

  it("skill evidence rows include project context and route into that project's report", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const js = contextualSkillCard("JavaScript")
    const cta = js.querySelector('[data-testid="skill-project-evidence-link"]')!
    // Exactly one attached project → one primary contextual CTA.
    expect(within(js).getAllByTestId("skill-project-evidence-link")).toHaveLength(1)
    expect(cta).toHaveAttribute("href", "/student/vbr/projects/proj-tm/report")
    expect(cta).toHaveAttribute("data-project-id", "proj-tm")
    // The old vague "View Skill Report / View project evidence" wording is gone.
    expect(js).not.toHaveTextContent("View Skill Report")
    expect(js).not.toHaveTextContent("View project evidence")
  })

  it("attached Website Proof CTA is contextual: 'View [skill] evidence in [project] report'", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const js = contextualSkillCard("JavaScript")
    expect(js.querySelector('[data-testid="skill-project-evidence-link"]')).toHaveTextContent(
      "View JavaScript evidence in Teachable Machine Image Classification Demo report →",
    )
  })

  it("Website Proof under a skill states which project it supports (generic source at passport level)", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const js = contextualSkillCard("JavaScript")
    const note = js.querySelector('[data-testid="skill-website-evidence-note"]')!
    expect(note).toHaveAttribute("data-project", "Teachable Machine Image Classification Demo")
    expect(note).toHaveAttribute("data-skill", "JavaScript")
    expect(note).toHaveTextContent("Website evidence")
    // Passport payload carries no classified DOM/OCR/visual sub-source — honest generic label.
    expect(note).toHaveAttribute("data-source-classified", "false")
  })

  it("a skill in multiple projects shows a per-project list, each routing to its own report", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const fastapi = contextualSkillCard("FastAPI")
    expect(fastapi.querySelector('[data-testid="skill-multi-project-heading"]')).toHaveTextContent(
      "This skill appears in 2 project reports",
    )
    const rows = within(fastapi).getAllByTestId("skill-project-evidence-row")
    expect(rows).toHaveLength(2)
    const links = within(fastapi).getAllByTestId("skill-project-evidence-link")
    const hrefs = links.map((l) => l.getAttribute("href"))
    expect(hrefs).toContain("/student/vbr/projects/proj-boston/report")
    expect(hrefs).toContain("/student/vbr/projects/proj-api2/report")
    // Each CTA names its own project.
    expect(
      links.find((l) => l.getAttribute("data-project-id") === "proj-boston"),
    ).toHaveTextContent("View FastAPI evidence in Boston Smart Accident Risk Rerouting report →")
  })

  it("unattached/vault-only proof is labelled not-attached and never links to a project report", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const rust = contextualSkillCard("Rust")
    const vault = rust.querySelector('[data-testid="skill-vault-only"]')!
    expect(vault).toHaveTextContent("Vault-only evidence — not attached to any project here")
    // Routes to the Proof Vault, NOT to any project report.
    expect(rust.querySelector('[data-testid="skill-open-proof-vault"]')).toHaveAttribute(
      "href",
      "/student/vbr/passport/vault",
    )
    expect(rust.querySelector('[data-testid="skill-project-evidence-link"]')).toBeNull()
    expect(rust.querySelector('[data-testid="skill-evidence-nav"]')).toBeNull()
  })

  it("project-card skill CTA is contextual to this project ('View [skill] evidence in this project')", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const labels = screen.getAllByTestId("project-skill-evidence-label").map((el) => el.textContent)
    expect(labels).toContain("View JavaScript evidence in this project →")
    expect(labels).toContain("View FastAPI evidence in this project →")
    // The bare, project-less wording is gone.
    expect(labels).not.toContain("View skill evidence →")
  })

  it("still filters projects when a contextual skill is selected (unrelated projects removed)", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    // Selecting JavaScript (proven only by proj-tm) filters the Projects panel.
    fireEvent.click(contextualSkillCard("JavaScript"))
    const visible = screen.getAllByTestId("passport-project-card").map((c) => c.getAttribute("data-project-id"))
    expect(visible).toEqual(["proj-tm"])
    // The unrelated project CARD is removed (its title may still appear as a
    // secondary filter chip, so assert on the card, not raw text).
    expect(
      screen.queryAllByTestId("passport-project-card").find((c) => c.getAttribute("data-project-id") === "proj-boston"),
    ).toBeUndefined()
  })
})

// ── Skill → project report → supporting proof-type breakdown ───────────────────
// Each skill→project row must surface the proof types that support THIS skill in
// THIS project (from the closed, skill-specific `supporting_proof_types`), never
// the project-wide source union — and it must fail closed (a proof type shows
// only where the mapping recorded it).

function makeProofBreakdownPassport(): PrivateWorkPassport {
  const base = makePassport().projects[0]
  return makePassport({
    skills: [
      {
        skill: "Machine Learning",
        status: "Demonstrated",
        evidence_chip_count: 4,
        project_count: 2,
        // Passport-level union is deliberately broad; the per-project rows must
        // NOT inherit it — they use each project's skill-specific breakdown.
        evidence_sources: ["GitHub Proof", "Website Proof", "Document Proof", "Project Defense", "Video Evidence"],
        projects: [
          {
            project_title: "Boston Smart Accident Risk Rerouting",
            project_id: "proj-boston",
            skill_status: "Demonstrated",
            // Whole-project union (superset) — must be ignored in favour of the
            // skill-specific breakdown below.
            evidence_sources: ["GitHub Proof", "Website Proof", "Document Proof", "Project Defense", "Video Evidence"],
            supporting_proof_types: ["GitHub Proof", "Website Proof", "Document Proof", "Project Defense"],
            report_is_public: false,
            public_report_path: null,
          },
          {
            project_title: "Teachable Machine Image Classification Demo",
            project_id: "proj-tm",
            skill_status: "Demonstrated",
            evidence_sources: ["GitHub Proof", "Website Proof", "Document Proof", "Project Defense", "Video Evidence"],
            supporting_proof_types: ["Website Proof", "Document Proof", "Project Defense", "Video Evidence"],
            report_is_public: false,
            public_report_path: null,
          },
        ],
        evidence_chips: [],
        notes: "",
        limitations: [],
      },
      {
        // FastAPI: supported by GitHub + Document only in Boston — NO Website,
        // even though the project has website evidence for other skills.
        skill: "FastAPI",
        status: "Evidence observed",
        evidence_chip_count: 1,
        project_count: 1,
        evidence_sources: ["GitHub Proof", "Website Proof", "Document Proof"],
        projects: [
          {
            project_title: "Boston Smart Accident Risk Rerouting",
            project_id: "proj-boston",
            skill_status: "Evidence observed",
            evidence_sources: ["GitHub Proof", "Website Proof", "Document Proof", "Project Defense"],
            supporting_proof_types: ["GitHub Proof", "Document Proof"],
            report_is_public: false,
            public_report_path: null,
          },
        ],
        evidence_chips: [],
        notes: "",
        limitations: [],
      },
    ],
    projects: [
      {
        ...base,
        project_id: "proj-boston",
        project_title: "Boston Smart Accident Risk Rerouting",
        claimed_skills: ["Machine Learning", "FastAPI"],
        top_skills: [
          { skill: "Machine Learning", status: "Demonstrated", skill_slug: "machine-learning", supporting_proof_types: ["GitHub Proof", "Website Proof", "Document Proof"] },
          { skill: "FastAPI", status: "Evidence observed", skill_slug: "fastapi", supporting_proof_types: ["GitHub Proof", "Document Proof"] },
        ],
      },
      {
        ...base,
        project_id: "proj-tm",
        project_title: "Teachable Machine Image Classification Demo",
        claimed_skills: ["Machine Learning"],
        top_skills: [
          { skill: "Machine Learning", status: "Demonstrated", skill_slug: "machine-learning", supporting_proof_types: ["Website Proof", "Document Proof", "Video Evidence"] },
        ],
      },
    ],
    project_count: 2,
  })
}

const breakdownSkillCard = (name: string) =>
  screen.getAllByTestId("passport-skill-card").find((c) => c.getAttribute("data-skill") === name)!

const rowChipSources = (row: HTMLElement) =>
  within(row)
    .queryAllByTestId("skill-project-proof-chip")
    .map((c) => c.getAttribute("data-source"))

describe("PrivatePassportView — skill → project → proof-type breakdown", () => {
  beforeEach(() => {
    const p = makeProofBreakdownPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
  })

  it("shows per-project proof-type chips on each skill→project row", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const ml = breakdownSkillCard("Machine Learning")
    const rows = within(ml).getAllByTestId("skill-project-evidence-row")
    expect(rows).toHaveLength(2)
    for (const row of rows) {
      expect(within(row).getByTestId("skill-project-proof-chips")).toBeInTheDocument()
    }
  })

  it("Machine Learning shows different proof chips for Boston vs Teachable", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const ml = breakdownSkillCard("Machine Learning")
    const boston = within(ml).getAllByTestId("skill-project-evidence-row").find((r) => r.getAttribute("data-project-id") === "proj-boston")!
    const teachable = within(ml).getAllByTestId("skill-project-evidence-row").find((r) => r.getAttribute("data-project-id") === "proj-tm")!

    // Boston: GitHub + Document + Website + Project Defense (no Video), canonical order.
    expect(rowChipSources(boston)).toEqual(["GitHub Proof", "Website Proof", "Document Proof", "Project Defense"])
    // Teachable: Website + Document + Project Defense + Video (no GitHub).
    expect(rowChipSources(teachable)).toEqual(["Website Proof", "Document Proof", "Project Defense", "Video Evidence"])
    // Boston has no Video chip; Teachable has no GitHub chip — proof of skill+project specificity.
    expect(rowChipSources(boston)).not.toContain("Video Evidence")
    expect(rowChipSources(teachable)).not.toContain("GitHub Proof")
  })

  it("Website Proof chip appears only where website evidence supports that skill/project", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    // ML in Boston: Website supports it → Website chip present.
    const ml = breakdownSkillCard("Machine Learning")
    const mlBoston = within(ml).getAllByTestId("skill-project-evidence-row").find((r) => r.getAttribute("data-project-id") === "proj-boston")!
    expect(rowChipSources(mlBoston)).toContain("Website Proof")

    // FastAPI in Boston: same project HAS website evidence, but it does NOT
    // support FastAPI → no Website chip (the project-wide union is not dumped in).
    const fastapi = breakdownSkillCard("FastAPI")
    const faBoston = within(fastapi).getAllByTestId("skill-project-evidence-row")[0]
    expect(rowChipSources(faBoston)).toEqual(["GitHub Proof", "Document Proof"])
    expect(rowChipSources(faBoston)).not.toContain("Website Proof")
  })

  it("uses supporting_proof_types (skill-specific), not the project-wide evidence_sources union", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    // Teachable's ref carries a broad evidence_sources union that INCLUDES GitHub
    // Proof, but its skill-specific supporting_proof_types excludes it — so no
    // GitHub chip may appear for ML in Teachable.
    const ml = breakdownSkillCard("Machine Learning")
    const teachable = within(ml).getAllByTestId("skill-project-evidence-row").find((r) => r.getAttribute("data-project-id") === "proj-tm")!
    expect(rowChipSources(teachable)).not.toContain("GitHub Proof")
  })

  it("project card shows per-skill proof chips supporting that skill in this project", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const bostonCard = screen.getAllByTestId("passport-project-card").find((c) => c.getAttribute("data-project-id") === "proj-boston")!
    const mlChipRow = within(bostonCard).getAllByTestId("project-skill-proof-chips").find((r) => r.getAttribute("data-skill") === "Machine Learning")!
    const sources = within(mlChipRow).getAllByTestId("project-skill-proof-chip").map((c) => c.getAttribute("data-source"))
    // GitHub · Website · Document — the ML breakdown for THIS project (canonical order).
    expect(sources).toEqual(["GitHub Proof", "Website Proof", "Document Proof"])
  })

  it("vault-only evidence stays separate and never renders a project-report proof chip", async () => {
    // A skill whose evidence is unattached: no project rows, no proof chips.
    const p = makeProofBreakdownPassport()
    p.skills.push({
      skill: "Rust",
      status: "Evidence observed",
      evidence_chip_count: 1,
      project_count: 0,
      evidence_sources: ["GitHub Proof"],
      projects: [],
      evidence_chips: [],
      notes: "",
      limitations: [],
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const rust = breakdownSkillCard("Rust")
    expect(rust.querySelector('[data-testid="skill-vault-only"]')).toBeInTheDocument()
    expect(rust.querySelector('[data-testid="skill-project-proof-chip"]')).toBeNull()
    expect(rust.querySelector('[data-testid="skill-project-evidence-link"]')).toBeNull()
  })

  it("skill→project CTAs stay project-specific and keyboard-operable with the chips added", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const ml = breakdownSkillCard("Machine Learning")
    const links = within(ml).getAllByTestId("skill-project-evidence-link")
    expect(links.map((l) => l.getAttribute("href"))).toEqual(
      expect.arrayContaining(["/student/vbr/projects/proj-boston/report", "/student/vbr/projects/proj-tm/report"]),
    )
    // The card is still a keyboard-operable selection control.
    expect(ml).toHaveAttribute("tabindex", "0")
    expect(ml).toHaveAttribute("role", "button")
    fireEvent.keyDown(ml, { key: "Enter" })
    expect(ml).toHaveAttribute("data-selected", "true")
  })

  it("labels every skill→project row 'Evidence for this skill in this project:' (skill-specific, not project-wide)", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const ml = breakdownSkillCard("Machine Learning")
    const headings = within(ml).getAllByTestId("skill-project-evidence-heading")
    expect(headings).toHaveLength(2)
    for (const h of headings) {
      expect(h).toHaveTextContent("Evidence for this skill in this project:")
    }
    // The vague, project-wide wording is gone.
    expect(ml).not.toHaveTextContent("Supports this skill with")
  })

  it("a skill with project-level proof but no skill mapping reads 'Project-level proof exists, but is not mapped to this skill yet'", async () => {
    // Browser APIs is proven-in-project (an attached row exists) but the mapping
    // recorded NO proof type for it in that project → empty supporting_proof_types.
    // The project itself DOES carry project-level proof, so the row must say the
    // proof exists but is not yet mapped to this skill (never overclaim it as
    // skill-specific evidence).
    const p = makeProofBreakdownPassport()
    p.skills.push({
      skill: "Browser APIs",
      status: "Not assessed",
      evidence_chip_count: 0,
      project_count: 1,
      evidence_sources: [],
      projects: [
        {
          project_title: "Boston Smart Accident Risk Rerouting",
          project_id: "proj-boston",
          skill_status: "Not assessed",
          evidence_sources: ["GitHub Proof", "Document Proof"],
          supporting_proof_types: [],
          report_is_public: false,
          public_report_path: null,
        },
      ],
      evidence_chips: [],
      notes: "",
      limitations: [],
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const browser = breakdownSkillCard("Browser APIs")
    const row = within(browser).getByTestId("skill-project-evidence-row")
    // Heading is still present (so the reader knows what the empty state means),
    // followed by the project-level-proof distinction and NO skill proof chips.
    expect(within(row).getByTestId("skill-project-evidence-heading")).toBeInTheDocument()
    expect(within(row).getByTestId("skill-project-proof-unmapped")).toHaveTextContent(
      "Project-level proof exists, but is not mapped to this skill yet.",
    )
    expect(within(row).queryByTestId("skill-project-proof-chip")).toBeNull()
    // A "Not assessed" row never overclaims — the per-project status is shown as-is.
    expect(within(row).getByTestId("skill-project-status")).toHaveTextContent("Not assessed")
  })

  it("a skill in a project with no attached proof at all reads 'No skill-specific evidence attached for this project yet.'", async () => {
    // The project row exists but the project carries NO project-level proof, so
    // the honest empty state is "none attached for this project yet".
    const p = makeProofBreakdownPassport()
    p.projects.push({
      ...makePassport().projects[0],
      project_id: "proj-empty",
      project_title: "Bare Claim Project",
      evidence_sources: [],
      top_skills: [],
    })
    p.skills.push({
      skill: "Browser APIs",
      status: "Not assessed",
      evidence_chip_count: 0,
      project_count: 1,
      evidence_sources: [],
      projects: [
        {
          project_title: "Bare Claim Project",
          project_id: "proj-empty",
          skill_status: "Not assessed",
          evidence_sources: [],
          supporting_proof_types: [],
          report_is_public: false,
          public_report_path: null,
        },
      ],
      evidence_chips: [],
      notes: "",
      limitations: [],
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const browser = breakdownSkillCard("Browser APIs")
    const row = within(browser).getByTestId("skill-project-evidence-row")
    expect(within(row).getByTestId("skill-project-proof-unclassified")).toHaveTextContent(
      "No skill-specific evidence attached for this project yet.",
    )
    expect(within(row).queryByTestId("skill-project-proof-unmapped")).toBeNull()
    expect(within(row).queryByTestId("skill-project-proof-chip")).toBeNull()
  })
})

// ── Skills Evidence Map: Skill → Project → Evidence + vault-only separation ────
//
// The primary Passport body is a skill-first evidence map. Each skill block lists
// the projects that demonstrate it (with the proof scoped to that skill+project)
// and keeps vault-only / standalone evidence in a clearly-labelled SEPARATE
// section that is never counted as project-attached proof.

function makeVaultSeparationPassport(overrides: Partial<PrivateWorkPassport> = {}): PrivateWorkPassport {
  const base = makePassport().projects[0]
  return makePassport({
    skills: [
      {
        skill: "Machine Learning",
        status: "Partially demonstrated",
        evidence_chip_count: 3,
        project_count: 1,
        evidence_sources: ["GitHub Proof", "Website Proof"],
        // Two proof types exist for ML in the vault, attached to NO project.
        vault_only_sources: ["GitHub Proof", "Project Defense"],
        projects: [
          {
            project_title: "Boston Smart Accident Risk Rerouting",
            project_id: "proj-boston",
            skill_status: "Partially demonstrated",
            evidence_sources: ["GitHub Proof", "Website Proof"],
            supporting_proof_types: ["GitHub Proof", "Website Proof"],
            report_is_public: false,
            public_report_path: null,
          },
        ],
        evidence_chips: [],
        notes: "",
        limitations: [],
      },
      {
        // A skill whose ONLY evidence is vault-only (no attached project).
        skill: "Rust",
        status: "Supporting evidence",
        evidence_chip_count: 1,
        project_count: 0,
        evidence_sources: ["Document Proof"],
        vault_only_sources: ["Document Proof"],
        projects: [],
        evidence_chips: [],
        notes: "",
        limitations: [],
      },
    ],
    projects: [
      {
        ...base,
        project_id: "proj-boston",
        project_title: "Boston Smart Accident Risk Rerouting",
        claimed_skills: ["Machine Learning"],
        top_skills: [
          { skill: "Machine Learning", status: "Partially demonstrated", skill_slug: "machine-learning", supporting_proof_types: ["GitHub Proof", "Website Proof"] },
        ],
      },
    ],
    project_count: 1,
    ...overrides,
  })
}

const mapSkillCard = (name: string) =>
  screen.getAllByTestId("passport-skill-card").find((c) => c.getAttribute("data-skill") === name)!

describe("PrivatePassportView — Skills Evidence Map (skill → project → evidence)", () => {
  beforeEach(() => {
    const p = makeVaultSeparationPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
  })

  it("renders the skill-first Skills Evidence Map section with its subtitle", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    expect(screen.getByText("Skills Evidence Map")).toBeInTheDocument()
    expect(
      screen.getByText(/Each skill shows the projects that support it/i),
    ).toBeInTheDocument()
    // Every skill block names its projects and its overall status.
    const ml = mapSkillCard("Machine Learning")
    expect(within(ml).getByTestId("skill-projects-heading")).toHaveTextContent(
      "Projects demonstrating this skill",
    )
    expect(within(ml).getByTestId("skill-project-count")).toHaveTextContent("Connected projects: 1")
  })

  it("shows each project row's status and proof scoped to that skill+project", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const ml = mapSkillCard("Machine Learning")
    const row = within(ml).getByTestId("skill-project-evidence-row")
    expect(row).toHaveAttribute("data-project-id", "proj-boston")
    expect(within(row).getByTestId("skill-project-status")).toHaveTextContent("Partially demonstrated")
    const chips = within(row)
      .getAllByTestId("skill-project-proof-chip")
      .map((c) => c.getAttribute("data-source"))
    expect(chips).toEqual(["GitHub Proof", "Website Proof"])
    // Contextual CTAs into the project's report.
    expect(within(row).getByTestId("skill-project-evidence-link")).toHaveAttribute(
      "href",
      "/student/vbr/projects/proj-boston/report",
    )
    expect(within(row).getByTestId("skill-open-project-report")).toHaveAttribute(
      "href",
      "/student/vbr/projects/proj-boston/report",
    )
  })

  it("keeps vault-only evidence SEPARATE from the project rows and labels it not-attached", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const ml = mapSkillCard("Machine Learning")
    // The skill has BOTH an attached project row and a standalone vault section.
    expect(within(ml).getByTestId("skill-project-evidence-row")).toBeInTheDocument()
    const standalone = within(ml).getByTestId("skill-standalone-evidence")
    expect(standalone).toHaveTextContent("Vault-only evidence — not attached to a project report.")
    // Vault-only chips are the unattached sources (GitHub · Project Defense),
    // distinct from the project row's own sources.
    const vaultChips = within(standalone)
      .getAllByTestId("skill-standalone-proof-chip")
      .map((c) => c.getAttribute("data-source"))
    expect(vaultChips).toEqual(["GitHub Proof", "Project Defense"])
    // The standalone section routes to the full skill report, never a project report.
    expect(within(standalone).getByTestId("skill-standalone-skill-report")).toHaveAttribute(
      "href",
      "/student/vbr/passport/skills/machine-learning",
    )
    // The vault-only chips live only inside the standalone section — they are NOT
    // rendered as project-attached proof chips.
    expect(within(standalone).queryByTestId("skill-project-proof-chip")).toBeNull()
  })

  it("a purely vault-only skill shows only the vault-only block with its chips (no project CTA)", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const rust = mapSkillCard("Rust")
    const vault = within(rust).getByTestId("skill-vault-only")
    expect(vault).toHaveTextContent("Vault-only evidence — not attached to any project here")
    expect(
      within(vault).getAllByTestId("skill-vault-only-chip").map((c) => c.getAttribute("data-source")),
    ).toEqual(["Document Proof"])
    // Never fronts a project-report CTA; routes to the Proof Vault instead.
    expect(within(rust).queryByTestId("skill-project-evidence-link")).toBeNull()
    expect(within(rust).getByTestId("skill-open-proof-vault")).toHaveAttribute(
      "href",
      "/student/vbr/passport/vault",
    )
  })

  it("hides the vault-only section when a project filter is focused on that project", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    fireEvent.change(screen.getByTestId("passport-project-filter"), { target: { value: "proj-boston" } })

    const ml = mapSkillCard("Machine Learning")
    // In project-filter mode the row stays, but the vault-only section (not tied
    // to this project) is hidden so it is never read as this project's evidence.
    expect(within(ml).getByTestId("skill-project-evidence-row")).toBeInTheDocument()
    expect(within(ml).queryByTestId("skill-standalone-evidence")).toBeNull()
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

describe("PrivatePassportView — Proof Attachment Intelligence moved to Proof Vault", () => {
  beforeEach(() => {
    const p = makeIntelligencePassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
  })

  it("does not render 'Proof Attachment Intelligence' in the main Passport body", async () => {
    render(<PrivatePassportView />)

    await screen.findByTestId("passport-graph-explorer")
    expect(screen.queryByTestId("proof-attachment-intelligence")).not.toBeInTheDocument()
    expect(screen.queryByText(/Proof Attachment Intelligence/i)).not.toBeInTheDocument()
  })

  it("does not render 'What to attach next' in the main Passport body", async () => {
    render(<PrivatePassportView />)

    await screen.findByTestId("passport-graph-explorer")
    expect(screen.queryByText(/What to attach next/i)).not.toBeInTheDocument()
  })

  it("does not render suggested attachments as a main Passport section", async () => {
    render(<PrivatePassportView />)

    await screen.findByTestId("passport-graph-explorer")
    expect(screen.queryByTestId("suggested-attachments")).not.toBeInTheDocument()
    expect(screen.queryByTestId("attachment-suggestion")).not.toBeInTheDocument()
    expect(screen.queryByTestId("project-suggested-attachment")).not.toBeInTheDocument()
    expect(screen.queryByTestId("skills-with-unattached")).not.toBeInTheDocument()
    expect(screen.queryByText(/Skills with unattached evidence/i)).not.toBeInTheDocument()
  })

  it("renders the Improve Passport card with the Proof Vault CTA instead", async () => {
    render(<PrivatePassportView />)

    const card = await screen.findByTestId("improve-passport-card")
    expect(card).toHaveTextContent("Review suggested attachments and unattached evidence in Proof Vault.")
    expect(screen.getByTestId("open-proof-vault-link")).toHaveAttribute(
      "href",
      "/student/vbr/passport/vault",
    )
  })

  it("keeps the project card free of per-project maintenance rows", async () => {
    render(<PrivatePassportView />)

    const card = await screen.findByTestId("passport-project-card")
    // Chain-quality label stays (qualitative identity), maintenance rows move.
    expect(screen.getByTestId("project-chain-label")).toHaveTextContent("Missing runtime proof")
    expect(card.querySelector('[data-testid="project-next-action"]')).toBeNull()
    expect(card.querySelector('[data-testid="project-chain-gap"]')).toBeNull()
    expect(card.querySelector('[data-testid="project-suggested-attachments"]')).toBeNull()
  })

  it("keeps cross-links working (skill report + project report links)", async () => {
    render(<PrivatePassportView />)

    // Project → Skill Report links still render.
    const chips = await screen.findAllByTestId("project-top-skill")
    expect(chips[0]).toHaveAttribute("href", "/student/vbr/passport/skills/python")
    // Skill card → Skill Report link still works.
    const skillCards = screen.getAllByTestId("passport-skill-card")
    const python = skillCards.find((c) => c.getAttribute("data-skill") === "Python")!
    expect(python.querySelector('[data-testid="view-skill-report"]')).toHaveAttribute(
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

describe("PrivatePassportView — Attachment Intelligence Cleanup (Step 4, moved to Proof Vault)", () => {
  it("never renders the attachment overview sections in the main Passport body", async () => {
    const p = makePassport({
      vault_proof_count: 3,
      vault_unattached_count: 2,
      attachment_overview: makeOverview(),
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    await screen.findByTestId("passport-graph-explorer")
    expect(screen.queryByTestId("attachment-overview")).not.toBeInTheDocument()
    expect(screen.queryByTestId("attachment-attached-section")).not.toBeInTheDocument()
    expect(screen.queryByTestId("attachment-suggested-section")).not.toBeInTheDocument()
    expect(screen.queryByTestId("attachment-unattached-section")).not.toBeInTheDocument()
  })

  it("surfaces the clean suggested/unattached counts on the Improve Passport card", async () => {
    const p = makePassport({
      vault_proof_count: 3,
      vault_unattached_count: 2,
      attachment_overview: makeOverview(),
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    const card = await screen.findByTestId("improve-passport-card")
    expect(card).toBeInTheDocument()
    expect(screen.getByTestId("improve-passport-suggested-count")).toHaveTextContent("1 suggested")
    expect(screen.getByTestId("improve-passport-unattached-count")).toHaveTextContent("1 unattached")
    expect(screen.getByTestId("open-proof-vault-link")).toHaveAttribute(
      "href",
      "/student/vbr/passport/vault",
    )
  })

  it("still renders the Improve Passport CTA when the payload omits the overview (older backend)", async () => {
    const p = makePassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    expect(await screen.findByTestId("passport-header")).toBeInTheDocument()
    expect(screen.queryByTestId("attachment-overview")).not.toBeInTheDocument()
    expect(screen.getByTestId("open-proof-vault-link")).toBeInTheDocument()
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

// These dedupe/clean-count behaviours live on the Proof Vault page now — the
// Proof Attachment Intelligence, Skill Intelligence previews, and vault count
// copy all moved out of the main Passport into ProofVaultView.
describe("ProofVaultView — browser polish (dedupe + clean counts)", () => {
  it("shows the clean deduplicated attachment_overview count in prominent copy, not the raw vault count", async () => {
    const p = makeGraphPassport({
      // Raw vault rows (with duplicates) is large; the clean deduped count is small.
      vault_unattached_count: 519,
      attachment_overview: makeOverview({ unattached_count: 32 }),
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<ProofVaultView />)

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

    render(<ProofVaultView />)

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

    render(<ProofVaultView />)

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

    render(<ProofVaultView />)

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

    render(<ProofVaultView />)

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

    const { container } = render(<ProofVaultView />)

    const note = await screen.findByTestId("suggestions-unmatched-note")
    expect(note).toHaveTextContent("32 unattached proof item(s) had no safe project match")
    expect(note).not.toHaveTextContent("519")
    // The raw 519-style row count appears nowhere on the rendered page.
    expect(container).not.toHaveTextContent("519")
  })
})

// ── Projects ↔ Skills interactive explorer (true filtering + a11y + fail-closed)
//
// Two projects, each with one evidence-backed top_skill, so selecting one side
// filters the OTHER panel down to exactly the connected item — unrelated cards
// are removed from the DOM entirely, never rendered faded in the background.
function makeInteractivePassport(overrides: Partial<PrivateWorkPassport> = {}): PrivateWorkPassport {
  const base = makePassport().projects[0]
  return makePassport({
    skills: [
      { skill: "Python", status: "Demonstrated", evidence_chip_count: 1, project_count: 1, evidence_sources: ["GitHub Proof"], projects: [], evidence_chips: [], notes: "", limitations: [] },
      { skill: "Rust", status: "Demonstrated", evidence_chip_count: 1, project_count: 1, evidence_sources: ["GitHub Proof"], projects: [], evidence_chips: [], notes: "", limitations: [] },
    ],
    projects: [
      { ...base, project_id: "proj-alpha", project_title: "Alpha Service", claimed_skills: ["Python"], top_skills: [{ skill: "Python", status: "Demonstrated", skill_slug: "python" }] },
      { ...base, project_id: "proj-beta", project_title: "Beta Service", claimed_skills: ["Rust"], top_skills: [{ skill: "Rust", status: "Demonstrated", skill_slug: "rust" }] },
    ],
    project_count: 2,
    ...overrides,
  })
}

// Query (not get) helpers: they must return undefined — not throw — when a card
// has been filtered out of the DOM, so absence can be asserted directly.
const querySkillCard = (name: string) =>
  screen.queryAllByTestId("passport-skill-card").find((c) => c.getAttribute("data-skill") === name)
const queryProjectCard = (id: string) =>
  screen.queryAllByTestId("passport-project-card").find((c) => c.getAttribute("data-project-id") === id)
const skillCard = (name: string) => querySkillCard(name)!
const projectCard = (id: string) => queryProjectCard(id)!

// The project filter is now an evaluator dropdown (scales to 20–30 projects),
// not a horizontal pill strip. Selecting "" is the "All projects" option.
const selectProject = (id: string) =>
  fireEvent.change(screen.getByTestId("passport-project-filter"), { target: { value: id } })
const selectSkill = (key: string) =>
  fireEvent.change(screen.getByTestId("passport-skill-filter"), { target: { value: key } })

describe("PrivatePassportView — skill-first map filtering (skill focus + project filter)", () => {
  beforeEach(() => {
    const p = makeInteractivePassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
  })

  it("no selection renders all skill blocks and all projects", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    expect(screen.getAllByTestId("passport-project-card")).toHaveLength(2)
    expect(screen.getAllByTestId("passport-skill-card")).toHaveLength(2)
    expect(querySkillCard("Python")).toBeDefined()
    expect(querySkillCard("Rust")).toBeDefined()
    expect(queryProjectCard("proj-alpha")).toBeDefined()
    expect(queryProjectCard("proj-beta")).toBeDefined()
    // No selection → default panel headers with the full counts.
    expect(screen.getByText("Projects (2)")).toBeInTheDocument()
    expect(screen.getByText("Skills (2)")).toBeInTheDocument()
    // The evaluator controls default to "All skills" (skill-first), and the
    // project filter is a compact dropdown, NOT a horizontal pill strip.
    expect(screen.getByText("Explore evidence")).toBeInTheDocument()
    expect(screen.getByTestId("passport-skill-filter")).toHaveValue("")
    expect(screen.getByTestId("passport-project-filter")).toHaveValue("")
    const skillSelect = screen.getByTestId("passport-skill-filter")
    expect(within(skillSelect).getByRole("option", { name: /^All skills$/ })).toBeInTheDocument()
    expect(screen.queryAllByTestId("passport-project-filter-chip")).toHaveLength(0)
    // No active filter yet → no Clear filters control.
    expect(screen.queryByTestId("clear-filters-button")).not.toBeInTheDocument()
  })

  it("selecting a project narrows the map to that project's skill blocks AND that project row only", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    selectProject("proj-alpha")

    expect(screen.getByTestId("passport-project-filter")).toHaveValue("proj-alpha")
    // Alpha proves Python only → Python is the ONLY skill block left; Rust is gone.
    expect(querySkillCard("Python")).toBeDefined()
    expect(querySkillCard("Rust")).toBeUndefined()
    expect(screen.getAllByTestId("passport-skill-card")).toHaveLength(1)
    // Inside the Python block, only the selected project's row shows.
    const python = skillCard("Python")
    const rows = within(python).getAllByTestId("skill-project-evidence-row")
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveAttribute("data-project-id", "proj-alpha")
    // The secondary project lens is narrowed to just that project.
    expect(screen.getAllByTestId("passport-project-card")).toHaveLength(1)
    expect(queryProjectCard("proj-alpha")).toBeDefined()
    expect(queryProjectCard("proj-beta")).toBeUndefined()
    expect(screen.getByText("Skills for selected project (1)")).toBeInTheDocument()
  })

  it("selecting another project updates the visible skill blocks to that project's skills", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    selectProject("proj-alpha")
    expect(querySkillCard("Python")).toBeDefined()
    expect(querySkillCard("Rust")).toBeUndefined()

    // Pivot to Beta via the project dropdown.
    selectProject("proj-beta")

    expect(screen.getByTestId("passport-project-filter")).toHaveValue("proj-beta")
    // Previous project's skill disappears; the new project's skill appears.
    expect(querySkillCard("Python")).toBeUndefined()
    expect(querySkillCard("Rust")).toBeDefined()
    expect(screen.getAllByTestId("passport-skill-card")).toHaveLength(1)
    expect(queryProjectCard("proj-alpha")).toBeUndefined()
  })

  it("the 'All projects' option clears the project filter and restores all skills", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    selectProject("proj-alpha")
    expect(querySkillCard("Rust")).toBeUndefined()

    // Selecting the empty "All projects" option clears the project filter.
    selectProject("")

    expect(querySkillCard("Python")).toBeDefined()
    expect(querySkillCard("Rust")).toBeDefined()
    expect(screen.getAllByTestId("passport-skill-card")).toHaveLength(2)
    expect(screen.getByText("Skills (2)")).toBeInTheDocument()
  })

  it("focusing a skill block shows only that block and only its projects", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    fireEvent.click(skillCard("Python"))

    expect(skillCard("Python")).toHaveAttribute("data-selected", "true")
    // Skill focus narrows the map to that single skill block (req 9 — no confusing
    // separate skill/project column).
    expect(querySkillCard("Python")).toBeDefined()
    expect(querySkillCard("Rust")).toBeUndefined()
    expect(screen.getAllByTestId("passport-skill-card")).toHaveLength(1)
    // Python is proven by Alpha only → Alpha is the ONLY project card left; Beta is gone.
    expect(queryProjectCard("proj-alpha")).toBeDefined()
    expect(queryProjectCard("proj-beta")).toBeUndefined()
    expect(screen.getAllByTestId("passport-project-card")).toHaveLength(1)
    expect(screen.getByText("Projects for selected skill (1)")).toBeInTheDocument()
  })

  it("clearing the skill focus restores all skills and projects", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    fireEvent.click(skillCard("Python"))
    expect(queryProjectCard("proj-beta")).toBeUndefined()

    fireEvent.click(screen.getByTestId("clear-filters-button"))

    expect(screen.queryByTestId("clear-filters-button")).not.toBeInTheDocument()
    expect(querySkillCard("Python")).toBeDefined()
    expect(querySkillCard("Rust")).toBeDefined()
    expect(queryProjectCard("proj-alpha")).toBeDefined()
    expect(queryProjectCard("proj-beta")).toBeDefined()
    expect(screen.getByText("Skills (2)")).toBeInTheDocument()
  })

  it("skill focus is keyboard accessible (real button semantics + Enter/Space)", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const card = skillCard("Python")
    // Exposed as an operable, focusable selection control.
    expect(card).toHaveAttribute("role", "button")
    expect(card).toHaveAttribute("tabindex", "0")
    expect(card).toHaveAttribute("aria-pressed", "false")

    fireEvent.keyDown(card, { key: "Enter" })
    expect(skillCard("Python")).toHaveAttribute("data-selected", "true")
    expect(skillCard("Python")).toHaveAttribute("aria-pressed", "true")
    // Enter focuses the block and narrows the project lens to Python's project.
    expect(queryProjectCard("proj-alpha")).toBeDefined()
    expect(queryProjectCard("proj-beta")).toBeUndefined()

    // Space toggles it back off — same affordance as a native button.
    fireEvent.keyDown(skillCard("Python"), { key: " " })
    expect(skillCard("Python")).toHaveAttribute("data-selected", "false")
    // Toggling off restores all projects and all skills.
    expect(queryProjectCard("proj-beta")).toBeDefined()
    expect(screen.getAllByTestId("passport-skill-card")).toHaveLength(2)

    // A keypress on an inner link must not hijack the card's toggle.
    fireEvent.keyDown(within(skillCard("Python")).getByTestId("view-skill-report"), { key: "Enter" })
    expect(skillCard("Python")).toHaveAttribute("data-selected", "false")
  })
})

// ── Evaluator-grade "Explore evidence" controls ───────────────────────────────
//
// Designed for a recruiter/evaluator, not a student project list: skill-first
// default ("All skills"), compact skill/project/proof-type dropdowns (no long
// project-pill strip), informative option labels + selected summaries, a
// proof-type filter scoped to skill→project rows, and many-project scalability.

describe("PrivatePassportView — evaluator Explore-evidence controls", () => {
  beforeEach(() => {
    const p = makeProofBreakdownPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
  })

  it("renders the 'Explore evidence' controls with a skill-first 'All skills' default", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    expect(screen.getByText("Explore evidence")).toBeInTheDocument()
    expect(screen.getByText("Filter by skill, project, or proof type.")).toBeInTheDocument()
    // Skill-first default control text is "All skills", never "All projects".
    const skillSelect = screen.getByTestId("passport-skill-filter")
    expect(skillSelect).toHaveValue("")
    expect(within(skillSelect).getByRole("option", { name: /^All skills$/ })).toBeInTheDocument()
    expect(screen.getByTestId("passport-project-filter")).toHaveValue("")
    expect(screen.getByTestId("passport-proof-filter")).toHaveValue("")
    // The old horizontal project-pill strip is gone (does not scale to 20–30 projects).
    expect(screen.queryAllByTestId("passport-project-filter-chip")).toHaveLength(0)
    expect(screen.queryByTestId("passport-project-filter-all")).not.toBeInTheDocument()
  })

  it("skill dropdown options carry project + proof context, not bare skill names", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    const skillSelect = screen.getByTestId("passport-skill-filter")
    const ml = within(skillSelect).getByRole("option", { name: /^Machine Learning/ })
    // "Machine Learning — 2 projects · GitHub · …" — recruiter-informative.
    expect(ml.textContent).toContain("2 projects")
    expect(ml.textContent).toContain("GitHub")
    expect(ml.textContent).not.toBe("Machine Learning")
  })

  it("project dropdown options carry skill context, not bare project names", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    const projectSelect = screen.getByTestId("passport-project-filter")
    const boston = within(projectSelect).getByRole("option", { name: /^Boston Smart Accident Risk Rerouting/ })
    // Boston proves Machine Learning + FastAPI → "— 2 skills".
    expect(boston.textContent).toContain("2 skills")
    expect(boston.textContent).not.toBe("Boston Smart Accident Risk Rerouting")
  })

  it("the skill dropdown narrows the map to a single skill block", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectSkill("machine learning")
    expect(screen.getByTestId("passport-skill-filter")).toHaveValue("machine learning")
    const cards = screen.getAllByTestId("passport-skill-card")
    expect(cards).toHaveLength(1)
    expect(cards[0]).toHaveAttribute("data-skill", "Machine Learning")
    // Selected-skill summary carries context (project count), not just the name.
    const summary = screen.getByTestId("summary-skill")
    expect(summary).toHaveTextContent("Showing evidence for: Machine Learning")
    expect(summary).toHaveTextContent("2 projects")
  })

  it("the project dropdown narrows to that project's skills and shows a proof summary", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectProject("proj-boston")
    // Boston proves ML + FastAPI → both skill blocks, each showing only Boston's row.
    const cards = screen.getAllByTestId("passport-skill-card").map((c) => c.getAttribute("data-skill"))
    expect(cards).toEqual(expect.arrayContaining(["Machine Learning", "FastAPI"]))
    const ml = screen.getAllByTestId("passport-skill-card").find((c) => c.getAttribute("data-skill") === "Machine Learning")!
    const rows = within(ml).getAllByTestId("skill-project-evidence-row")
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveAttribute("data-project-id", "proj-boston")
    // Selected-project summary names the project and its attached proof.
    expect(screen.getByTestId("summary-project")).toHaveTextContent(
      "Showing skills from: Boston Smart Accident Risk Rerouting",
    )
    expect(screen.getByTestId("summary-project-proof")).toHaveTextContent("Project proof attached:")
  })

  it("the proof-type filter shows only skill→project rows that have that proof for that skill", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // Video Evidence supports ML only in Teachable — and no FastAPI row at all.
    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "Video Evidence" } })
    const skills = screen.getAllByTestId("passport-skill-card").map((c) => c.getAttribute("data-skill"))
    expect(skills).toEqual(["Machine Learning"])
    const ml = mapSkillCard("Machine Learning")
    const rows = within(ml).getAllByTestId("skill-project-evidence-row")
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveAttribute("data-project-id", "proj-tm")
    expect(screen.getByTestId("summary-proof")).toHaveTextContent("Showing evidence with: Video Evidence")
  })

  it("proof-type filter does NOT surface a skill just because the project has that proof generally", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // Boston HAS Website evidence, but it does not support FastAPI. Filtering by
    // Website Proof must therefore hide FastAPI (only ML survives).
    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "Website Proof" } })
    const skills = screen.getAllByTestId("passport-skill-card").map((c) => c.getAttribute("data-skill"))
    expect(skills).toContain("Machine Learning")
    expect(skills).not.toContain("FastAPI")
  })

  it("shows a helpful empty state when no skill→project row matches the proof-type filter", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // FastAPI has no Website row → combining the two yields no matches.
    selectSkill("fastapi")
    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "Website Proof" } })
    expect(screen.getByTestId("skills-panel-proof-empty")).toHaveTextContent(
      "No skill-project evidence found for Website Proof. Try all proof types or attach website evidence.",
    )
    expect(screen.queryAllByTestId("passport-skill-card")).toHaveLength(0)
  })

  it("Clear filters resets skill, project and proof-type filters back to all skills", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectSkill("machine learning")
    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "Website Proof" } })
    expect(screen.getByTestId("clear-filters-button")).toBeInTheDocument()

    fireEvent.click(screen.getByTestId("clear-filters-button"))
    expect(screen.getByTestId("passport-skill-filter")).toHaveValue("")
    expect(screen.getByTestId("passport-proof-filter")).toHaveValue("")
    expect(screen.queryByTestId("graph-filter-summary")).not.toBeInTheDocument()
    expect(screen.getAllByTestId("passport-skill-card").length).toBeGreaterThan(1)
  })
})

// ── Proof-type dropdown reflects the WHOLE passport, not just visible rows ─────
//
// Regression: the Proof Type dropdown was derived only from mapped skill→project
// rows, so a proof type the candidate genuinely has (e.g. Website Proof, shown in
// the Evidence Graph Overview) went missing whenever no visible skill block mapped
// it. The dropdown must offer every proof type present anywhere in the passport
// evidence — while selection still fails closed to the exact skill→project rows.

// Website Proof exists globally (overview counts + project-level attached source),
// but it is NOT mapped to the skill's supporting_proof_types → no skill→project
// row carries it. The dropdown must still offer it; selecting it must show the
// clear empty state, never overclaim the project-level Website Proof as skill-
// specific evidence.
function makeWebsiteGlobalOnlyPassport(overrides: Partial<PrivateWorkPassport> = {}): PrivateWorkPassport {
  const base = makePassport().projects[0]
  return makePassport({
    skills: [
      {
        skill: "Machine Learning",
        status: "Demonstrated",
        evidence_chip_count: 2,
        project_count: 1,
        evidence_sources: ["GitHub Proof"],
        projects: [
          {
            project_title: "Boston Smart Accident Risk Rerouting",
            project_id: "proj-boston",
            skill_status: "Demonstrated",
            // Project-wide union HAS website evidence …
            evidence_sources: ["GitHub Proof", "Website Proof"],
            // … but it does NOT support Machine Learning (fail-closed mapping).
            supporting_proof_types: ["GitHub Proof"],
            report_is_public: false,
            public_report_path: null,
          },
        ],
        evidence_chips: [],
        notes: "",
        limitations: [],
      },
    ],
    projects: [
      {
        ...base,
        project_id: "proj-boston",
        project_title: "Boston Smart Accident Risk Rerouting",
        evidence_sources: ["GitHub Proof", "Website Proof"],
        claimed_skills: ["Machine Learning"],
        top_skills: [
          { skill: "Machine Learning", status: "Demonstrated", skill_slug: "machine-learning", supporting_proof_types: ["GitHub Proof"] },
        ],
      },
    ],
    // The Evidence Graph Overview counts Website Proof — so must the dropdown.
    evidence_source_counts: { "GitHub Proof": 2, "Website Proof": 1 },
    project_count: 1,
    ...overrides,
  })
}

const proofFilterOptionNames = () =>
  within(screen.getByTestId("passport-proof-filter"))
    .getAllByRole("option")
    .map((o) => o.textContent)

describe("PrivatePassportView — Proof Type dropdown reflects the whole passport", () => {
  it("includes Website Proof when it exists in the passport, even if no visible skill row maps it", async () => {
    const p = makeWebsiteGlobalOnlyPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // Overview shows Website Proof …
    expect(screen.getByTestId("evidence-source-counts")).toHaveTextContent("Website Proof")
    // … so the Proof Type dropdown must offer it (recruiter-useful), in canonical
    // order after GitHub Proof.
    const options = proofFilterOptionNames()
    expect(options).toContain("Website Proof")
    expect(options).toEqual(["All proof types", "GitHub Proof", "Website Proof"])
  })

  it("does not overclaim project-level Website Proof as skill-specific: selecting it shows the clear empty state", async () => {
    const p = makeWebsiteGlobalOnlyPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // The ML row must NOT show a Website chip — its skill-specific proof is GitHub only.
    const mlBefore = mapSkillCard("Machine Learning")
    expect(
      within(mlBefore).getAllByTestId("skill-project-proof-chip").map((c) => c.getAttribute("data-source")),
    ).toEqual(["GitHub Proof"])

    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "Website Proof" } })

    // No skill→project row maps Website → clear empty state, no fabricated rows.
    expect(screen.queryAllByTestId("passport-skill-card")).toHaveLength(0)
    expect(screen.getByTestId("skills-panel-proof-empty")).toHaveTextContent(
      "No skill-project evidence found for Website Proof. Try all proof types or attach website evidence.",
    )
  })

  it("explains the project-level-only Website Proof and lists context cards when the passport carries it", async () => {
    const p = makeWebsiteGlobalOnlyPassport({
      website_proof_project_context: [
        {
          project_id: "proj-boston",
          project_title: "Boston Smart Accident Risk Rerouting",
          focus_key: "navigation_layout",
          focus_label: "Navigation / page layout",
          explanation: "The recorded session shows the app's page layout and navigation between views.",
          reason: "Navigation/layout evidence only",
          action_guidance:
            "Record a stronger Website Proof showing runtime behavior such as a model prediction, API response, dashboard interaction, route recommendation, or workflow completion.",
          mapped_to_skills: false,
          report_path: "/student/vbr/projects/proj-boston/report",
        },
      ],
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "Website Proof" } })

    // The honest explanatory empty state replaces the generic copy.
    expect(screen.queryByTestId("skills-panel-proof-empty")).not.toBeInTheDocument()
    const panel = screen.getByTestId("website-proof-project-level-empty")
    expect(within(panel).getByTestId("website-proof-empty-headline")).toHaveTextContent(
      "Website Proof exists, but it has not been mapped to specific skills yet.",
    )
    expect(panel).toHaveTextContent(
      "Current website evidence was classified as navigation/layout",
    )

    // A project-level context card names the project, reason, action and safe routes.
    const card = within(panel).getByTestId("website-proof-project-context-card")
    expect(card).toHaveTextContent("Boston Smart Accident Risk Rerouting")
    expect(card).toHaveTextContent("Website Proof: Project-level only")
    expect(card).toHaveTextContent("Navigation/layout evidence only")
    expect(within(card).getByTestId("website-proof-context-open-report")).toHaveAttribute(
      "href",
      "/student/vbr/projects/proj-boston/report",
    )
    expect(within(card).getByTestId("website-proof-context-open-vault")).toHaveAttribute(
      "href",
      "/student/vbr/passport/vault",
    )

    // Project-level Website Proof is NEVER rendered as a skill card / skill evidence.
    expect(screen.queryAllByTestId("passport-skill-card")).toHaveLength(0)
  })

  it("normalizes non-canonical Website Proof spellings to a single 'Website Proof' option", async () => {
    // Overview carries a snake_case variant; the dropdown must still read "Website
    // Proof" (once, not duplicated).
    const p = makeWebsiteGlobalOnlyPassport({
      evidence_source_counts: { "GitHub Proof": 2, website_proof: 1 },
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    const options = proofFilterOptionNames()
    expect(options.filter((o) => o === "Website Proof")).toHaveLength(1)
    expect(options).toContain("Website Proof")
  })
})

describe("PrivatePassportView — Proof Type dropdown filtering (mapped + existing types)", () => {
  beforeEach(() => {
    const p = makeProofBreakdownPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
  })

  it("offers every proof type the candidate has, in canonical order", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // makeProofBreakdownPassport maps all five proof types across its skill rows.
    expect(proofFilterOptionNames()).toEqual([
      "All proof types",
      "GitHub Proof",
      "Website Proof",
      "Document Proof",
      "Project Defense",
      "Video Evidence",
    ])
  })

  it("selecting Website Proof keeps only skill→project rows where website maps to that skill", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "Website Proof" } })

    // ML maps Website (Boston + Teachable rows) → ML survives; FastAPI does not.
    const skills = screen.getAllByTestId("passport-skill-card").map((c) => c.getAttribute("data-skill"))
    expect(skills).toEqual(["Machine Learning"])
    const ml = mapSkillCard("Machine Learning")
    const rows = within(ml).getAllByTestId("skill-project-evidence-row").map((r) => r.getAttribute("data-project-id"))
    expect(rows).toEqual(expect.arrayContaining(["proj-boston", "proj-tm"]))
    // Every surviving row genuinely carries a Website chip.
    for (const row of within(ml).getAllByTestId("skill-project-evidence-row")) {
      expect(rowChipSources(row)).toContain("Website Proof")
    }
  })

  it("existing GitHub / Document / Project Defense / Video filters still work", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    const proofFilter = screen.getByTestId("passport-proof-filter")
    const skillsAfter = () => screen.queryAllByTestId("passport-skill-card").map((c) => c.getAttribute("data-skill"))

    // GitHub Proof supports ML (Boston) and FastAPI (Boston).
    fireEvent.change(proofFilter, { target: { value: "GitHub Proof" } })
    expect(skillsAfter()).toEqual(expect.arrayContaining(["Machine Learning", "FastAPI"]))

    // Document Proof supports both ML and FastAPI too.
    fireEvent.change(proofFilter, { target: { value: "Document Proof" } })
    expect(skillsAfter()).toEqual(expect.arrayContaining(["Machine Learning", "FastAPI"]))

    // Project Defense supports ML only (in both projects); FastAPI has no defense chip.
    fireEvent.change(proofFilter, { target: { value: "Project Defense" } })
    expect(skillsAfter()).toEqual(["Machine Learning"])

    // Video Evidence supports ML only, in Teachable.
    fireEvent.change(proofFilter, { target: { value: "Video Evidence" } })
    expect(skillsAfter()).toEqual(["Machine Learning"])
    const ml = mapSkillCard("Machine Learning")
    expect(
      within(ml).getAllByTestId("skill-project-evidence-row").map((r) => r.getAttribute("data-project-id")),
    ).toEqual(["proj-tm"])
  })
})

// ── Many-project scalability (top rows + expander) ────────────────────────────

function makeManyProjectPassport(): PrivateWorkPassport {
  const base = makePassport().projects[0]
  const titles = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
  return makePassport({
    skills: [
      {
        skill: "Scaling",
        status: "Demonstrated",
        evidence_chip_count: 5,
        project_count: 5,
        evidence_sources: ["GitHub Proof"],
        strongest_project_title: "Alpha Project",
        strongest_project_status: "Demonstrated",
        projects: titles.map((t, i) => ({
          project_title: `${t} Project`,
          project_id: `proj-${i}`,
          skill_status: "Demonstrated",
          evidence_sources: ["GitHub Proof"],
          supporting_proof_types: ["GitHub Proof"],
          report_is_public: false,
          public_report_path: null,
        })),
        evidence_chips: [],
        notes: "",
        limitations: [],
      },
    ],
    projects: titles.map((t, i) => ({
      ...base,
      project_id: `proj-${i}`,
      project_title: `${t} Project`,
      claimed_skills: ["Scaling"],
      top_skills: [
        { skill: "Scaling", status: "Demonstrated", skill_slug: "scaling", supporting_proof_types: ["GitHub Proof"] },
      ],
    })),
    project_count: 5,
  })
}

describe("PrivatePassportView — many-project skill scalability", () => {
  beforeEach(() => {
    const p = makeManyProjectPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
  })

  it("caps a many-project skill to its top rows by default with a 'Show N more projects' expander", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const scaling = mapSkillCard("Scaling")
    // 5 connected projects → only the top 3 rows render by default (no flood).
    expect(within(scaling).getAllByTestId("skill-project-evidence-row")).toHaveLength(3)
    const showMore = within(scaling).getByTestId("skill-show-more-projects")
    expect(showMore).toHaveTextContent("Show 2 more projects")

    // Expanding reveals all rows and offers a way to collapse again.
    fireEvent.click(showMore)
    expect(within(scaling).getAllByTestId("skill-project-evidence-row")).toHaveLength(5)
    expect(within(scaling).queryByTestId("skill-show-more-projects")).toBeNull()
    fireEvent.click(within(scaling).getByTestId("skill-show-fewer-projects"))
    expect(within(scaling).getAllByTestId("skill-project-evidence-row")).toHaveLength(3)
  })

  it("a project filter collapses a many-project skill to just that project's row", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    selectProject("proj-2")
    const scaling = mapSkillCard("Scaling")
    const rows = within(scaling).getAllByTestId("skill-project-evidence-row")
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveAttribute("data-project-id", "proj-2")
    // No expander in single-project mode — there is nothing more to reveal.
    expect(within(scaling).queryByTestId("skill-show-more-projects")).toBeNull()
  })
})

describe("buildPassportGraph — evidence-only edges (fail closed)", () => {
  it("does not create proven project↔skill links from evidence-less claimed_skills", () => {
    const base = makePassport().projects[0]
    const p = makePassport({
      skills: [],
      projects: [
        // A claim with no top_skills and no skill/vault evidence must not link.
        { ...base, project_id: "proj-x", project_title: "Claim Only", claimed_skills: ["Kubernetes"], top_skills: [] },
      ],
    })

    const graph = buildPassportGraph(p)

    // No skill node at all — a bare claim never becomes a graph node…
    expect(graph.skills.find((s) => s.name === "Kubernetes")).toBeUndefined()
    // …and the project surfaces no "proven" skills.
    expect(graph.projectSkills.get("proj-x")).toEqual([])
    expect(graph.skillProjects.get("kubernetes")).toBeUndefined()
  })

  it("fails closed on ambiguous same-title matches but keeps unique-title matches", () => {
    const base = makePassport().projects[0]
    const p = makePassport({
      skills: [
        // Title-only ref (no project_id) to an ambiguous, duplicated title.
        { skill: "Go", status: "Demonstrated", evidence_chip_count: 1, project_count: 1, evidence_sources: [], projects: [{ project_title: "Dup Project", project_id: null, evidence_sources: [], report_is_public: false, public_report_path: null }], evidence_chips: [], notes: "", limitations: [] },
        // Title-only ref to a unique title — this one may safely resolve.
        { skill: "Rust", status: "Demonstrated", evidence_chip_count: 1, project_count: 1, evidence_sources: [], projects: [{ project_title: "Solo Project", project_id: null, evidence_sources: [], report_is_public: false, public_report_path: null }], evidence_chips: [], notes: "", limitations: [] },
      ],
      projects: [
        { ...base, project_id: "dup-1", project_title: "Dup Project", claimed_skills: [], top_skills: [] },
        { ...base, project_id: "dup-2", project_title: "Dup Project", claimed_skills: [], top_skills: [] },
        { ...base, project_id: "solo-1", project_title: "Solo Project", claimed_skills: [], top_skills: [] },
      ],
    })

    const graph = buildPassportGraph(p)

    // Ambiguous title → no edge to either duplicate.
    expect(graph.skills.find((s) => s.name === "Go")!.projectIds).toEqual([])
    expect(graph.projectSkills.get("dup-1")).toEqual([])
    expect(graph.projectSkills.get("dup-2")).toEqual([])
    // Unique title → the title-only fallback still resolves safely.
    expect(graph.skills.find((s) => s.name === "Rust")!.projectIds).toEqual(["solo-1"])
    expect(graph.projectSkills.get("solo-1")).toEqual(["rust"])
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
