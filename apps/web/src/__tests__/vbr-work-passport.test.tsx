/**
 * Private Verified Work Passport — frontend rendering tests.
 *
 * Covers: evidence-source groups/badges, grouped skills, per-project report
 * actions, and the publish / copy / unpublish controls.
 */

import { render, screen, waitFor, fireEvent, within } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { PrivatePassportView } from "../app/student/vbr/passport/PrivatePassportView"
import { buildPassportGraph } from "../app/student/vbr/passport/passport-graph"
import { CAPABILITY_AREAS } from "@/lib/passport-capabilities"
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
  confirmWebsiteProofProjectRelationship: vi.fn(),
  confirmProofProjectRelationship: vi.fn(),
}))

import {
  getPrivateWorkPassport,
  getWorkPassportStatus,
  publishWorkPassport,
  unpublishWorkPassport,
  publishVBRProjectReport,
  confirmWebsiteProofProjectRelationship,
  confirmProofProjectRelationship,
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
  vi.mocked(confirmWebsiteProofProjectRelationship).mockReset()
  vi.mocked(confirmProofProjectRelationship).mockReset()
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
            supporting_proof_types: ["Website Proof", "GitHub Proof"],
            website_evidence_summary:
              "The recorded interactive UI behaviour is itself the subject of JavaScript, so this is direct evidence of working JavaScript product behaviour (authorship is corroborated by GitHub/Defense evidence, not by the UI alone).",
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

  it("Website Proof under a skill shows the precise, safe behaviour summary for that skill+project", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const js = contextualSkillCard("JavaScript")
    const note = js.querySelector('[data-testid="skill-website-evidence-note"]')!
    expect(note).toHaveAttribute("data-project", "Teachable Machine Image Classification Demo")
    expect(note).toHaveAttribute("data-skill", "JavaScript")
    // The generic placeholder is replaced by the safe, skill-specific behaviour
    // sentence derived from the website pipeline summaries (never raw DOM/OCR).
    expect(note).not.toHaveTextContent("Website evidence — shows observed runtime/product behavior")
    expect(note).toHaveTextContent("direct evidence of working JavaScript product behaviour")
    expect(note).toHaveAttribute("data-source-classified", "true")
  })

  it("Website Proof row without a derived summary falls back to the honest limited-detail note", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    // FastAPI's Boston project carries Website Proof but no `website_evidence_summary`.
    const fastapi = contextualSkillCard("FastAPI")
    const note = fastapi.querySelector('[data-testid="skill-website-evidence-note"]')!
    expect(note).toHaveTextContent(
      "Website Proof supports runtime/product behavior for this skill, but detailed website evidence is limited.",
    )
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

  it("labels every skill→project row 'Direct skill evidence in this project:' (skill-specific, not project-wide)", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const ml = breakdownSkillCard("Machine Learning")
    const headings = within(ml).getAllByTestId("skill-project-evidence-heading")
    expect(headings).toHaveLength(2)
    for (const h of headings) {
      expect(h).toHaveTextContent("Direct skill evidence in this project:")
    }
    // The vague, project-wide wording is gone.
    expect(ml).not.toHaveTextContent("Supports this skill with")
  })

  it("a skill with project-level proof but no skill mapping says 'No direct skill evidence yet.' and lists that proof in the separate project-level tier", async () => {
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
    // followed by the explicit "no direct evidence" statement — never a bare gap.
    expect(within(row).getByTestId("skill-project-evidence-heading")).toBeInTheDocument()
    expect(within(row).getByTestId("skill-project-no-direct")).toHaveTextContent(
      "No direct skill evidence yet.",
    )
    // The project's real attached proof renders in the SEPARATE project-level
    // tier — clearly labelled as not counted for this skill, never as skill chips.
    const tier = within(row).getByTestId("skill-project-level-tier")
    expect(tier).toHaveAttribute("data-tier", "project")
    expect(within(tier).getByTestId("skill-project-proof-unmapped")).toHaveTextContent(
      "Project-level proof — attached to this project, not mapped to this skill yet:",
    )
    expect(
      within(tier).getAllByTestId("skill-project-level-chip").map((c) => c.getAttribute("data-source")),
    ).toEqual(["GitHub Proof", "Document Proof", "Project Defense", "Video Evidence"])
    expect(within(row).queryByTestId("skill-project-proof-chip")).toBeNull()
    // A "Not assessed" row never overclaims — the per-project status is shown as-is.
    expect(within(row).getByTestId("skill-project-status")).toHaveTextContent("Not assessed")
  })

  it("a skill in a project with no attached proof at all reads 'This project has no attached proof yet.'", async () => {
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
    // The direct tier states the gap; with NO attached proof at all there is no
    // project-level tier to show either — only the honest no-proof line.
    expect(within(row).getByTestId("skill-project-no-direct")).toHaveTextContent(
      "No direct skill evidence yet.",
    )
    expect(within(row).getByTestId("skill-project-proof-unclassified")).toHaveTextContent(
      "This project has no attached proof yet.",
    )
    expect(within(row).queryByTestId("skill-project-level-tier")).toBeNull()
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
    // The standalone section routes to the Proof Vault, never a project report —
    // and never duplicates the card footer's "Open full skill report" link.
    expect(within(standalone).getByTestId("skill-standalone-open-vault")).toHaveAttribute(
      "href",
      "/student/vbr/passport/vault",
    )
    expect(within(ml).getAllByText(/Open full Machine Learning skill report/)).toHaveLength(1)
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

  it("requires explicit owned-project selection and confirmation before attaching one exact Website Proof", async () => {
    const initial = makeIntelligencePassport()
    initial.unattached_proof_summary!.suggestions[0] = {
      ...initial.unattached_proof_summary!.suggestions[0],
      proof_id: "fe658e5c-f8c5-47b8-8ff5-2c3a135b09b5",
      likely_project_id: "proj-1",
      relationship_state: "vault_only",
    }
    const refreshed = makeIntelligencePassport({
      unattached_proof_summary: {
        unattached_count: 2,
        suggestion_count: 0,
        unmatched_count: 2,
        suggestions: [],
      },
    })
    vi.mocked(getPrivateWorkPassport)
      .mockResolvedValueOnce(initial)
      .mockResolvedValue(refreshed)
    vi.mocked(confirmWebsiteProofProjectRelationship).mockResolvedValue({
      state: "directly_linked",
      project_id: "proj-1",
      project_title: "Skill Evidence Tracker",
      match_method: "user_confirmation",
      counted: true,
      confirmed_by_user: true,
      reasons: ["The student confirmed this Website Proof belongs to the selected project."],
      action_label: null,
    })

    render(<ProofVaultView />)

    const control = await screen.findByTestId("website-attachment-control")
    expect(within(control).getByTestId("confirm-website-attachment")).toBeDisabled()
    fireEvent.change(within(control).getByTestId("website-attachment-project-select"), {
      target: { value: "proj-1" },
    })
    expect(within(control).getByTestId("confirm-website-attachment")).toBeDisabled()
    fireEvent.click(within(control).getByTestId("website-attachment-confirmation"))
    fireEvent.click(within(control).getByTestId("confirm-website-attachment"))

    await waitFor(() =>
      expect(confirmWebsiteProofProjectRelationship).toHaveBeenCalledWith({
        proof_id: "fe658e5c-f8c5-47b8-8ff5-2c3a135b09b5",
        project_id: "proj-1",
      }),
    )
    expect(await screen.findByTestId("website-attachment-success")).toHaveTextContent(
      "Website Proof attached to Skill Evidence Tracker.",
    )
    expect(getPrivateWorkPassport).toHaveBeenCalledTimes(2)
  })

  it("attaches one exact Document Proof through the shared finalization endpoint", async () => {
    const initial = makeIntelligencePassport()
    initial.unattached_proof_summary!.suggestions[0] = {
      ...initial.unattached_proof_summary!.suggestions[0],
      proof_type: "Document Proof",
      proof_title: "VeriBridge Rich Document Proof Test",
      proof_id: "cb738b3e-73db-4e40-b359-f907106bb997",
      likely_project_title: "Skill Evidence Tracker",
      relationship_state: "vault_only",
    }
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(initial)
    vi.mocked(confirmProofProjectRelationship).mockResolvedValue({
      state: "directly_linked",
      project_id: "proj-1",
      project_title: "Skill Evidence Tracker",
      match_method: "user_confirmation",
      counted: true,
      confirmed_by_user: true,
      reasons: ["The student confirmed this document belongs to the selected project."],
      action_label: null,
    })

    render(<ProofVaultView />)

    const control = await screen.findByTestId("website-attachment-control")
    fireEvent.change(within(control).getByTestId("website-attachment-project-select"), {
      target: { value: "proj-1" },
    })
    // Document-specific honest consent copy: only exactly-cited evidence counts.
    expect(within(control).getByText(/only its exactly-cited evidence/i)).toBeInTheDocument()
    fireEvent.click(within(control).getByTestId("website-attachment-confirmation"))
    fireEvent.click(within(control).getByTestId("confirm-website-attachment"))

    await waitFor(() =>
      expect(confirmProofProjectRelationship).toHaveBeenCalledWith({
        proof_type: "document",
        proof_id: "cb738b3e-73db-4e40-b359-f907106bb997",
        project_id: "proj-1",
      }),
    )
    expect(await screen.findByTestId("website-attachment-success")).toHaveTextContent(
      "Document Proof attached to Skill Evidence Tracker.",
    )
    expect(confirmWebsiteProofProjectRelationship).not.toHaveBeenCalled()
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
    expect(screen.getByText("Filter by role area, skill, project, or proof type.")).toBeInTheDocument()
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
    expect(screen.getByTestId("summary-proof")).toHaveTextContent("Showing direct skill evidence with: Video Evidence")
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

    // FastAPI has no Website row → combining the two yields no matches. The copy
    // makes the honest distinction that project-level/vault-only Website Proof is
    // kept separate until attached to a specific project skill.
    selectSkill("fastapi")
    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "Website Proof" } })
    expect(screen.getByTestId("skills-panel-proof-empty")).toHaveTextContent(
      "No exact skill-project evidence matches Website Proof. Project-level or vault-only Website Proof is kept separate until it is attached to a specific project skill.",
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

// ── High-level Role Area (capability) filter + evidence summary ────────────────
//
// The Role Area filter aggregates the detailed skills into recruiter-facing role
// capabilities (Computer Vision, MLOps, Backend APIs, …). It is evidence-grounded:
// a role area only surfaces skill→project rows that genuinely support it, a
// contextual skill (ML under Computer Vision) shows only its role-relevant project
// rows, and unrelated projects (Boston ML) never leak into Computer Vision.

/** A capability-rich passport covering each required role area. */
function makeRoleAreaPassport(): PrivateWorkPassport {
  const base = makePassport().projects[0]
  const ref = (
    project_title: string,
    project_id: string,
    skill_status: string,
    supporting_proof_types: string[],
  ) => ({
    project_title,
    project_id,
    skill_status,
    evidence_sources: supporting_proof_types,
    supporting_proof_types,
    report_is_public: false,
    public_report_path: null,
  })
  const skill = (
    name: string,
    status: string,
    projects: ReturnType<typeof ref>[],
  ) => ({
    skill: name,
    status,
    evidence_chip_count: projects.length,
    project_count: projects.length,
    evidence_sources: [...new Set(projects.flatMap((p) => p.supporting_proof_types))],
    projects,
    evidence_chips: [],
    notes: "",
    limitations: [],
  })
  const top = (name: string, status: string, slug: string, proofs: string[]) => ({
    skill: name,
    status,
    skill_slug: slug,
    supporting_proof_types: proofs,
  })
  return makePassport({
    skills: [
      skill("Machine Learning", "Demonstrated", [
        ref("Boston Smart Accident Risk Rerouting", "proj-boston", "Demonstrated", ["GitHub Proof", "Document Proof"]),
        ref("Teachable Machine Image Classification Demo", "proj-tm", "Demonstrated", ["Website Proof", "Document Proof", "Project Defense", "Video Evidence"]),
      ]),
      skill("Image Classification", "Demonstrated", [
        ref("Teachable Machine Image Classification Demo", "proj-tm", "Demonstrated", ["Website Proof", "Project Defense"]),
      ]),
      skill("FastAPI", "Evidence observed", [
        ref("Boston Smart Accident Risk Rerouting", "proj-boston", "Evidence observed", ["GitHub Proof", "Document Proof"]),
      ]),
      skill("Docker", "Demonstrated", [
        ref("ML Model Cloud Run Deployment", "proj-cloud", "Demonstrated", ["GitHub Proof", "Project Defense"]),
      ]),
      skill("Data Visualization", "Evidence observed", [
        ref("Interactive Analytics Dashboard", "proj-dash", "Evidence observed", ["Website Proof", "Document Proof"]),
      ]),
      skill("React", "Partially demonstrated", [
        ref("Interactive Analytics Dashboard", "proj-dash", "Partially demonstrated", ["GitHub Proof", "Website Proof"]),
      ]),
    ],
    projects: [
      { ...base, project_id: "proj-boston", project_title: "Boston Smart Accident Risk Rerouting", claimed_skills: ["Machine Learning", "FastAPI"], top_skills: [top("Machine Learning", "Demonstrated", "machine-learning", ["GitHub Proof", "Document Proof"]), top("FastAPI", "Evidence observed", "fastapi", ["GitHub Proof", "Document Proof"])] },
      { ...base, project_id: "proj-tm", project_title: "Teachable Machine Image Classification Demo", claimed_skills: ["Machine Learning", "Image Classification"], top_skills: [top("Machine Learning", "Demonstrated", "machine-learning", ["Website Proof", "Document Proof", "Video Evidence"]), top("Image Classification", "Demonstrated", "image-classification", ["Website Proof", "Project Defense"])] },
      { ...base, project_id: "proj-cloud", project_title: "ML Model Cloud Run Deployment", claimed_skills: ["Docker"], top_skills: [top("Docker", "Demonstrated", "docker", ["GitHub Proof", "Project Defense"])] },
      { ...base, project_id: "proj-dash", project_title: "Interactive Analytics Dashboard", claimed_skills: ["Data Visualization", "React"], top_skills: [top("Data Visualization", "Evidence observed", "data-visualization", ["Website Proof", "Document Proof"]), top("React", "Partially demonstrated", "react", ["GitHub Proof", "Website Proof"])] },
    ],
    project_count: 4,
  })
}

const roleSkillCard = (name: string) =>
  screen.queryAllByTestId("passport-skill-card").find((c) => c.getAttribute("data-skill") === name)
const selectRole = (id: string) =>
  fireEvent.change(screen.getByTestId("passport-role-area-filter"), { target: { value: id } })
const capabilityProjectIds = () =>
  screen.queryAllByTestId("capability-project").map((c) => c.getAttribute("data-project-id"))

describe("PrivatePassportView — high-level Role Area capability filter", () => {
  beforeEach(() => {
    // Clear any Passport Card role-area selection persisted by an earlier test
    // file (localStorage leaks across files) so the card face shows the default
    // top role areas (incl. Computer Vision) these tests click.
    try {
      window.localStorage.clear()
    } catch {
      /* jsdom localStorage always available; guard just in case */
    }
    const p = makeRoleAreaPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
  })

  it("renders the Role Area filter with an 'All role areas' default and only evidenced areas", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    const roleSelect = screen.getByTestId("passport-role-area-filter")
    expect(roleSelect).toHaveValue("")
    expect(within(roleSelect).getByRole("option", { name: /^All role areas$/ })).toBeInTheDocument()
    // Present role areas become options; unevidenced ones (NLP / LLM) do not.
    expect(within(roleSelect).getByRole("option", { name: /^Computer Vision/ })).toBeInTheDocument()
    expect(within(roleSelect).getByRole("option", { name: /^Cloud \/ MLOps/ })).toBeInTheDocument()
    expect(within(roleSelect).getByRole("option", { name: /^Backend APIs/ })).toBeInTheDocument()
    expect(within(roleSelect).queryByRole("option", { name: /^NLP \/ LLM/ })).not.toBeInTheDocument()
  })

  it("selecting Computer Vision shows the capability evidence summary", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("computer-vision")
    const summary = screen.getByTestId("capability-summary")
    expect(summary).toHaveAttribute("data-capability", "Computer Vision")
    // Header framing + qualitative status chip (never a numeric score).
    expect(within(summary).getByTestId("capability-header")).toHaveTextContent("High-level capability selected (1)")
    expect(within(summary).getByTestId("capability-status")).toBeInTheDocument()
    // Counts-based headline + qualitative "why" (role-relevant evidence language).
    expect(within(summary).getByTestId("capability-summary-text")).toHaveTextContent(
      /Computer Vision is supported by \d+ connected skill.* across \d+ project.* and \d+ proof source/i,
    )
    // The "why" is now a richer, fact-grounded narrative (not the old one-liner):
    // it states the role area's purpose and names the connected project + skills.
    const why = within(summary).getByTestId("capability-why")
    expect(why).toHaveTextContent(/Computer Vision is about using image and visual workflows/i)
    expect(why).toHaveTextContent(/Teachable Machine Image Classification Demo/)
    expect(why).toHaveTextContent(/Image Classification/)
    expect(within(why).getAllByTestId("capability-why-paragraph").length).toBeGreaterThanOrEqual(2)
    // Not the old generic single-sentence summary.
    expect(why.textContent).not.toMatch(
      /is supported by role-relevant evidence from connected skills such as/i,
    )
    // Never a readiness/score guarantee (the disclaimer may say "score or rank").
    expect(summary.textContent).not.toMatch(/hire-ready|guaranteed|ready for (the )?role/i)
    expect(summary.textContent).not.toMatch(/\d+\s*\/\s*100|\d+\s*%|confidence:\s*\d/i)
    // Selected-filter summary line names the role area + its coverage.
    expect(screen.getByTestId("summary-role")).toHaveTextContent("Showing role-relevant evidence for: Computer Vision")
  })

  it("Computer Vision aggregates Teachable image-classification evidence (underlying skills + proof)", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("computer-vision")
    // Supported by the Teachable project only.
    expect(capabilityProjectIds()).toEqual(["proj-tm"])
    const proj = screen.getByTestId("capability-project")
    expect(proj).toHaveTextContent("Teachable Machine Image Classification Demo")
    // Underlying skills include the primary CV skill and the contextual ML skill.
    expect(proj.textContent).toMatch(/Image Classification/)
    expect(proj.textContent).toMatch(/Machine Learning/)
    // Proof chips reflect the Teachable evidence (Website + Project Defense).
    const proofs = within(proj).getAllByTestId("capability-project-proof-chip").map((c) => c.getAttribute("data-source"))
    expect(proofs).toContain("Website Proof")
    expect(proofs).toContain("Project Defense")
    // The skill blocks below narrow to CV's underlying skills only.
    const skills = screen.getAllByTestId("passport-skill-card").map((c) => c.getAttribute("data-skill"))
    expect(skills).toEqual(expect.arrayContaining(["Image Classification", "Machine Learning"]))
    expect(skills).not.toContain("FastAPI")
    expect(skills).not.toContain("Docker")
  })

  it("Computer Vision does NOT include unrelated Boston ML (no CV context there)", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("computer-vision")
    // Boston never appears under Computer Vision.
    expect(capabilityProjectIds()).not.toContain("proj-boston")
    // The Machine Learning block shows ONLY its Teachable row, not the Boston row.
    const ml = roleSkillCard("Machine Learning")!
    const rows = within(ml).getAllByTestId("skill-project-evidence-row")
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveAttribute("data-project-id", "proj-tm")
  })

  it("renders a visual connecting evidence chain (skills → project → proofs)", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("computer-vision")
    const chain = screen.getByTestId("capability-evidence-chain")
    const nodes = within(chain).getAllByTestId("capability-chain-node").map((n) => n.textContent)
    // The chain connects lower-level skills, the project, and proof sources.
    expect(nodes.length).toBeGreaterThanOrEqual(3)
    expect(nodes).toEqual(expect.arrayContaining([expect.stringMatching(/Image Classification|Machine Learning/)]))
    expect(nodes).toContain("Teachable Machine Image Classification Demo")
    expect(nodes).toEqual(expect.arrayContaining([expect.stringMatching(/Website Proof|Project Defense/)]))
  })

  it("lists connected lower-level skills with proof and a skill-report link", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("computer-vision")
    const connected = screen.getByTestId("capability-connected-skills")
    const skillNames = within(connected).getAllByTestId("capability-skill").map((s) => s.getAttribute("data-skill"))
    expect(skillNames).toEqual(expect.arrayContaining(["Image Classification", "Machine Learning"]))
    // Each connected skill exposes an owner-only skill-report link + proof chips.
    const reportLinks = within(connected).getAllByTestId("capability-skill-report-link")
    expect(reportLinks.length).toBeGreaterThan(0)
    expect(reportLinks[0].getAttribute("href")).toMatch(/\/student\/vbr\/passport\/skills\//)
    expect(within(connected).getAllByTestId("capability-skill-proof-chip").length).toBeGreaterThan(0)
  })

  it("connected projects show a reason and links to the project + skill reports", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("computer-vision")
    const proj = screen.getByTestId("capability-project")
    // Plain-language reason (honest, evidence-grounded, no numbers).
    expect(within(proj).getByTestId("capability-project-reason")).toHaveTextContent(
      /This project supports Computer Vision through/i,
    )
    // Links back to the owner-only project report and relevant skill reports.
    expect(within(proj).getByTestId("capability-open-report").getAttribute("href")).toMatch(
      /\/student\/vbr\/projects\/.*\/report/,
    )
    expect(within(proj).getAllByTestId("capability-open-skill-report").length).toBeGreaterThan(0)
  })

  it("shows a qualitative role-level status label (never a numeric score)", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("computer-vision")
    const status = screen.getByTestId("capability-status")
    expect(status.getAttribute("data-status")).toMatch(
      /Evidence observed|Supporting evidence|Partially demonstrated|Insufficient evidence|Not assessed/,
    )
    // Counts line, not a score.
    expect(screen.getByTestId("capability-skill-count")).toHaveTextContent(/Connected skills: \d+/)
    expect(screen.getByTestId("capability-project-count")).toHaveTextContent(/Connected projects: \d+/)
  })

  it("Machine Learning role area DOES include both Boston and Teachable (broad ML)", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("machine-learning")
    const ids = capabilityProjectIds()
    expect(ids).toContain("proj-boston")
    expect(ids).toContain("proj-tm")
    const ml = roleSkillCard("Machine Learning")!
    expect(within(ml).getAllByTestId("skill-project-evidence-row")).toHaveLength(2)
  })

  it("Cloud / MLOps aggregates deployment evidence and does not dominate Computer Vision", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("cloud-mlops")
    expect(screen.getByTestId("capability-summary")).toHaveAttribute("data-capability", "Cloud / MLOps")
    // Cloud / MLOps aggregates the deployment project (Docker) and, per the
    // expanded mapping, the FastAPI/backend project too — but NOT the pure CV/data
    // projects (Teachable / dashboard).
    expect(capabilityProjectIds()).toContain("proj-cloud")
    expect(capabilityProjectIds()).not.toContain("proj-tm")
    expect(screen.getByTestId("capability-summary").textContent).toMatch(/Docker/)

    // Pivoting back to Computer Vision must NOT drag in the Docker/cloud project.
    selectRole("computer-vision")
    expect(capabilityProjectIds()).toEqual(["proj-tm"])
    expect(screen.getByTestId("capability-summary").textContent).not.toMatch(/Docker/)
  })

  it("Data Science / Applied AI aggregates the analytics/visualization project", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("data-science-applied-ai")
    expect(screen.getByTestId("capability-summary")).toHaveAttribute("data-capability", "Data Science / Applied AI")
    expect(capabilityProjectIds()).toEqual(["proj-dash"])
    expect(screen.getByTestId("capability-summary").textContent).toMatch(/Data Visualization/)
  })

  it("Backend APIs aggregates the FastAPI project only", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("backend-apis")
    expect(capabilityProjectIds()).toEqual(["proj-boston"])
    const proj = screen.getByTestId("capability-project")
    expect(proj.textContent).toMatch(/FastAPI/)
    expect(proj.textContent).not.toMatch(/Docker|React/)
  })

  it("Full-Stack / Frontend AI aggregates the React dashboard project", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("full-stack-frontend-ai")
    expect(capabilityProjectIds()).toEqual(["proj-dash"])
    expect(screen.getByTestId("capability-summary").textContent).toMatch(/React/)
  })

  it("AI Product Engineering requires multi-layer evidence and aggregates across layers", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // Present because evidence spans AI/ML + backend + deployment + frontend.
    const roleSelect = screen.getByTestId("passport-role-area-filter")
    expect(within(roleSelect).getByRole("option", { name: /^AI Product Engineering/ })).toBeInTheDocument()

    selectRole("ai-product-engineering")
    const summary = screen.getByTestId("capability-summary")
    expect(summary).toHaveAttribute("data-capability", "AI Product Engineering")
    expect(within(summary).getByTestId("capability-composite-note")).toBeInTheDocument()
    expect(summary.textContent).toMatch(/multi-layer evidence/i)
    // It spans multiple projects/layers (ML, FastAPI, Docker, React).
    const ids = capabilityProjectIds()
    expect(ids.length).toBeGreaterThan(1)
  })

  it("Role Area + Proof Type filters compose (Computer Vision + Website Proof)", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("computer-vision")
    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "Website Proof" } })
    // Teachable CV rows carry Website Proof → they survive.
    const ml = roleSkillCard("Machine Learning")!
    const rows = within(ml).getAllByTestId("skill-project-evidence-row")
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveAttribute("data-project-id", "proj-tm")
    expect(screen.getByTestId("summary-proof")).toHaveTextContent("Showing direct skill evidence with: Website Proof")
  })

  it("Role Area + a proof type its evidence lacks shows an honest empty state (GitHub)", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // Teachable CV evidence has NO GitHub Proof → CV + GitHub yields nothing.
    selectRole("computer-vision")
    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "GitHub Proof" } })
    expect(screen.getByTestId("skills-panel-role-proof-empty")).toHaveTextContent(/No Computer Vision evidence uses GitHub Proof/i)
    expect(screen.queryAllByTestId("passport-skill-card")).toHaveLength(0)
  })

  it("Clear filters resets the Role Area filter too", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("computer-vision")
    expect(screen.getByTestId("passport-role-area-filter")).toHaveValue("computer-vision")
    fireEvent.click(screen.getByTestId("clear-filters-button"))
    expect(screen.getByTestId("passport-role-area-filter")).toHaveValue("")
    expect(screen.queryByTestId("capability-summary")).not.toBeInTheDocument()
    expect(screen.getAllByTestId("passport-skill-card").length).toBeGreaterThan(1)
  })

  it("the capability summary leaks no raw ids, file paths, or numeric scores", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("computer-vision")
    const text = screen.getByTestId("capability-summary").textContent ?? ""
    expect(text).not.toMatch(/octocat\/Hello-World/)
    expect(text).not.toMatch(/\/100|%|confidence:\s*\d/i)
  })

  // ── Passport Card role chip → high-level Role Area filter (integration) ───────
  //
  // The Passport Card preview at the top of the page drives the SAME Role Area
  // filter as the dropdown. A card role chip is a high-level role area — clicking
  // it must set the Role Area filter by the chip's canonical id and reset the
  // low-level Skill filter, never select an arbitrary underlying skill.

  /** The Computer Vision role chip on the top card preview. */
  const cardCvChip = () =>
    within(screen.getByTestId("passport-card-private"))
      .getAllByTestId("passport-card-capability")
      .find((c) => (c.textContent ?? "").trim() === "Computer Vision")!

  it("clicking a Passport Card role chip sets the Role Area filter and resets the Skill filter", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // Pre-select a low-level skill in the dropdown to prove the chip resets it.
    fireEvent.change(screen.getByTestId("passport-skill-filter"), { target: { value: "docker" } })
    expect(screen.getByTestId("passport-skill-filter")).toHaveValue("docker")

    fireEvent.click(cardCvChip())
    // Role Area dropdown reflects the clicked chip; Skill drops back to "all".
    expect(screen.getByTestId("passport-role-area-filter")).toHaveValue("computer-vision")
    expect(screen.getByTestId("passport-skill-filter")).toHaveValue("")
    // High-level capability card appears for that role area.
    expect(screen.getByTestId("capability-summary")).toHaveAttribute("data-capability", "Computer Vision")
  })

  it("card role chip ids line up with the Role Area filter option ids", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // Every option value in the Role Area dropdown is a canonical role-area id.
    const roleSelect = screen.getByTestId("passport-role-area-filter")
    const optionIds = within(roleSelect)
      .getAllByRole("option")
      .map((o) => (o as HTMLOptionElement).value)
      .filter(Boolean)
    const canonicalIds = new Set(CAPABILITY_AREAS.map((a) => a.id))
    for (const id of optionIds) expect(canonicalIds.has(id)).toBe(true)

    // Clicking the Computer Vision card chip selects an id that IS a real option.
    fireEvent.click(cardCvChip())
    expect(optionIds).toContain("computer-vision")
    expect(screen.getByTestId("passport-role-area-filter")).toHaveValue("computer-vision")
  })

  // ── Richer role-area narrative (A–H) ───────────────────────────────────────

  it("A/B: Cloud / MLOps 'why' names its connected projects, lower-level skills, and proof sources", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("cloud-mlops")
    const why = within(screen.getByTestId("capability-summary")).getByTestId("capability-why")
    // Purpose of the role area is stated (not just a keyword list).
    expect(why).toHaveTextContent(/Cloud \/ MLOps is about connecting models and products to deployment/i)
    // Names the exact connected project(s) and lower-level skill(s).
    expect(why).toHaveTextContent(/ML Model Cloud Run Deployment/)
    expect(why).toHaveTextContent(/Docker/)
    // Names concrete proof source(s) backing the connection.
    expect(why.textContent).toMatch(/GitHub Proof|Project Defense|Document Proof/)
    // Rendered as 1–2 readable paragraphs.
    const paras = within(why).getAllByTestId("capability-why-paragraph")
    expect(paras.length).toBeGreaterThanOrEqual(1)
    expect(paras.length).toBeLessThanOrEqual(2)
  })

  it("C: Backend APIs 'why' is a rich narrative, not the old generic sentence", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("backend-apis")
    const why = within(screen.getByTestId("capability-summary")).getByTestId("capability-why")
    expect(why).toHaveTextContent(/Backend APIs is about building service and API layers/i)
    expect(why).toHaveTextContent(/Boston Smart Accident Risk Rerouting/)
    expect(why).toHaveTextContent(/FastAPI/)
    // The old one-sentence "role-relevant evidence from connected skills such as …" is gone.
    expect(why.textContent).not.toMatch(/is supported by role-relevant evidence from connected skills such as/i)
    // Explains WHY the links support the area (capability pattern / traceable proof).
    expect(why.textContent).toMatch(/capability pattern|traceable/i)
  })

  it("D: connected lower-level skill cards show a reason tying the skill to the role area", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("cloud-mlops")
    const reasons = screen.getAllByTestId("capability-skill-reason")
    expect(reasons.length).toBeGreaterThan(0)
    // Every reason ties the skill back to Cloud / MLOps and stays conservative.
    for (const r of reasons) {
      expect(r.textContent).toMatch(/Connected to Cloud \/ MLOps/i)
    }
    // The Docker reason names the deployment project + its proof (fact-grounded).
    const docker = reasons.find((r) => r.getAttribute("data-skill") === "Docker")
    expect(docker).toBeTruthy()
    expect(docker!.textContent).toMatch(/ML Model Cloud Run Deployment/)
  })

  it("E: connected project cards explain why the project supports the role area", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("backend-apis")
    const proj = screen.getByTestId("capability-project")
    const reason = within(proj).getByTestId("capability-project-reason")
    expect(reason).toHaveTextContent(/This project supports Backend APIs through/i)
    expect(reason.textContent).toMatch(/FastAPI/)
    expect(reason.textContent).toMatch(/GitHub Proof|Document Proof/)
  })

  it("F: the narrative never exposes raw transcript/OCR/DOM, storage paths, signed URLs, ids, scores, or private routes", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    for (const id of ["cloud-mlops", "backend-apis", "computer-vision"]) {
      selectRole(id)
      const text = screen.getByTestId("capability-summary").textContent ?? ""
      // No raw evidence payloads.
      expect(text).not.toMatch(/transcript|transcript_segments|raw_text|ocr_text|<html|<div|dom_snapshot/i)
      // No storage paths / signed URLs / provider JSON.
      expect(text).not.toMatch(/https?:\/\/|storage\/|supabase\.co|X-Amz-|signature=|\.mp4|\.png|\.pdf/i)
      // No internal ids.
      expect(text).not.toMatch(/proj-boston|proj-tm|proj-cloud|proj-dash|[0-9a-f]{8}-[0-9a-f]{4}/)
      // No numeric confidence / trust scores.
      expect(text).not.toMatch(/\/100|\bconfidence:\s*\d|\btrust\s*score|\d+\s*%/i)
    }
  })

  it("G: the detailed underlying-skill filter still works within a role area", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("computer-vision")
    // Both CV underlying skills visible before narrowing.
    expect(roleSkillCard("Machine Learning")).toBeTruthy()
    expect(roleSkillCard("Image Classification")).toBeTruthy()
    // Narrow to a single underlying skill via the detailed skill filter
    // (option value is the skill key = the lowercased skill name).
    fireEvent.change(screen.getByTestId("passport-skill-filter"), { target: { value: "image classification" } })
    const cards = screen.getAllByTestId("passport-skill-card").map((c) => c.getAttribute("data-skill"))
    expect(cards).toEqual(["Image Classification"])
  })

  it("H: Clear filters clears the role area AND removes the capability narrative", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    selectRole("cloud-mlops")
    expect(screen.getByTestId("capability-why")).toBeInTheDocument()
    fireEvent.click(screen.getByTestId("clear-filters-button"))
    expect(screen.getByTestId("passport-role-area-filter")).toHaveValue("")
    expect(screen.queryByTestId("capability-summary")).not.toBeInTheDocument()
    expect(screen.queryByTestId("capability-why")).not.toBeInTheDocument()
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
    // The honest copy makes the project-level/vault-only distinction explicit.
    expect(screen.queryAllByTestId("passport-skill-card")).toHaveLength(0)
    expect(screen.getByTestId("skills-panel-proof-empty")).toHaveTextContent(
      "No exact skill-project evidence matches Website Proof. Project-level or vault-only Website Proof is kept separate until it is attached to a specific project skill.",
    )
  })

  it("Website Proof filter DOES show the project when a Website Proof is exactly attached to that skill+project", async () => {
    // Fail-closed must not become over-filtering: an exactly-attached Website
    // Proof that maps a skill in a project MUST still appear under the filter,
    // while a *different* project whose website union does not support that skill
    // stays hidden. proj-tm supports ML via Website Proof; proj-boston's website
    // is project-level union only (supports ML via GitHub, not website).
    const base = makePassport().projects[0]
    const p = makePassport({
      skills: [
        {
          skill: "Machine Learning",
          status: "Demonstrated",
          evidence_chip_count: 2,
          project_count: 2,
          evidence_sources: ["Website Proof", "GitHub Proof", "Project Defense"],
          projects: [
            {
              project_title: "Teachable Machine Image Classification Demo",
              project_id: "proj-tm",
              skill_status: "Demonstrated",
              evidence_sources: ["Website Proof", "Project Defense"],
              supporting_proof_types: ["Website Proof", "Project Defense"],
              report_is_public: false,
              public_report_path: null,
            },
            {
              project_title: "Boston Smart Accident Risk Rerouting",
              project_id: "proj-boston",
              skill_status: "Demonstrated",
              evidence_sources: ["GitHub Proof", "Website Proof"],
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
        { ...base, project_id: "proj-tm", project_title: "Teachable Machine Image Classification Demo", evidence_sources: ["Website Proof", "Project Defense"], claimed_skills: ["Machine Learning"], top_skills: [{ skill: "Machine Learning", status: "Demonstrated", skill_slug: "machine-learning", supporting_proof_types: ["Website Proof", "Project Defense"] }] },
        { ...base, project_id: "proj-boston", project_title: "Boston Smart Accident Risk Rerouting", evidence_sources: ["GitHub Proof", "Website Proof"], claimed_skills: ["Machine Learning"], top_skills: [{ skill: "Machine Learning", status: "Demonstrated", skill_slug: "machine-learning", supporting_proof_types: ["GitHub Proof"] }] },
      ],
      evidence_source_counts: { "Website Proof": 1, "GitHub Proof": 1, "Project Defense": 1 },
      project_count: 2,
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "Website Proof" } })

    // (6) The exactly-attached Website Proof still shows — NOT the empty state.
    expect(screen.queryByTestId("skills-panel-proof-empty")).not.toBeInTheDocument()
    const skills = screen.getAllByTestId("passport-skill-card").map((c) => c.getAttribute("data-skill"))
    expect(skills).toEqual(["Machine Learning"])
    // …and only proj-tm (the project the website actually supports for ML) survives.
    const ml = mapSkillCard("Machine Learning")
    const rows = within(ml).getAllByTestId("skill-project-evidence-row")
    expect(rows.map((r) => r.getAttribute("data-project-id"))).toEqual(["proj-tm"])
  })

  it("renders legacy project-level Website Proof context in the real-unmapped panel (fallback for older payloads)", async () => {
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

    // The honest with-context empty copy replaces the generic copy, and the
    // standing real-unmapped panel carries the entry.
    expect(screen.queryByTestId("skills-panel-proof-empty")).not.toBeInTheDocument()
    expect(screen.getByTestId("skills-panel-proof-empty-with-context")).toBeInTheDocument()
    const panel = screen.getByTestId("real-unmapped-proof-section")
    expect(within(panel).getByTestId("real-unmapped-proof-heading")).toHaveTextContent(
      "Attached proof not yet skill-mapped",
    )

    // The context card names the project, reason, and safe routes.
    const card = within(panel).getByTestId("real-unmapped-proof-card")
    expect(card).toHaveAttribute("data-proof-type", "Website Proof")
    expect(card).toHaveTextContent("Boston Smart Accident Risk Rerouting")
    expect(card).toHaveTextContent("Real proof · not skill-mapped yet")
    expect(card).toHaveTextContent("Navigation/layout evidence only")
    expect(within(card).getByTestId("real-unmapped-open-report")).toHaveAttribute(
      "href",
      "/student/vbr/projects/proj-boston/report#website-proof",
    )
    expect(within(card).getByTestId("real-unmapped-open-vault")).toHaveAttribute(
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

/** Passport carrying exact skill rows AND real-unmapped proof context. */
function makeRealUnmappedPassport(overrides: Partial<PrivateWorkPassport> = {}): PrivateWorkPassport {
  return makeWebsiteGlobalOnlyPassport({
    real_unmapped_proof_context: [
      {
        proof_type: "Website Proof",
        project_id: "proj-boston",
        project_title: "Boston Smart Accident Risk Rerouting",
        report_url: "/student/vbr/projects/proj-boston/report",
        reason: "Runtime proof exists, but it is not mapped to a specific skill yet.",
        safe_summary: "A recorded website runtime proof is attached to this project.",
        evidence_label: "Navigation / page layout",
        inspection_anchor: "website-proof",
      },
      {
        proof_type: "Project Defense",
        project_id: "proj-boston",
        project_title: "Boston Smart Accident Risk Rerouting",
        report_url: "/student/vbr/projects/proj-boston/report",
        reason: "Defense evidence exists, but it is not mapped to a specific skill yet.",
        safe_summary: "An answered and analyzed Project Defense session is attached to this project.",
        evidence_label: "Analyzed defense evidence",
        inspection_anchor: "project-defense",
      },
    ],
    ...overrides,
  })
}

describe("PrivatePassportView — real-unmapped proof panel (Attached proof not yet skill-mapped)", () => {
  it("renders the panel alongside exact skill rows — it is a standing section, not only an empty state", async () => {
    const p = makeRealUnmappedPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // Exact skill rows are visible (no filter) …
    expect(screen.getAllByTestId("passport-skill-card").map((c) => c.getAttribute("data-skill"))).toEqual([
      "Machine Learning",
    ])
    // … AND the real-unmapped panel renders at the same time.
    const panel = screen.getByTestId("real-unmapped-proof-section")
    expect(within(panel).getByTestId("real-unmapped-proof-heading")).toHaveTextContent(
      "Attached proof not yet skill-mapped",
    )
    expect(panel).toHaveTextContent(
      "These proof sources are attached to this project but are not yet mapped to a specific skill claim",
    )
    const cards = within(panel).getAllByTestId("real-unmapped-proof-card")
    expect(cards.map((c) => c.getAttribute("data-proof-type"))).toEqual(["Website Proof", "Project Defense"])
    // Entries link to the project report (with the proof-section anchor).
    expect(within(cards[0]).getByTestId("real-unmapped-open-report")).toHaveAttribute(
      "href",
      "/student/vbr/projects/proj-boston/report#website-proof",
    )
  })

  it("does not change skill/project counts, proof filter options, or exact evidence rows", async () => {
    const p = makeRealUnmappedPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // Skill / project counts stay exactly what the exact evidence map holds.
    expect(screen.getByText("Skills (1)")).toBeInTheDocument()
    expect(screen.getByText("Projects (1)")).toBeInTheDocument()
    // "Project Defense" exists ONLY as real-unmapped context here — it must NOT
    // become a proof filter option (real-unmapped context never feeds counts).
    const options = proofFilterOptionNames()
    expect(options).not.toContain("Project Defense")
    // The exact ML row still cites only its skill-specific proof (GitHub).
    const ml = mapSkillCard("Machine Learning")
    const row = within(ml).getAllByTestId("skill-project-evidence-row")[0]
    expect(rowChipSources(row)).toEqual(["GitHub Proof"])
  })

  it("narrows to the active proof type: only matching real-unmapped entries render under a filter", async () => {
    const p = makeRealUnmappedPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // Website Proof filter → no exact row maps website, so the honest
    // with-context copy shows, and ONLY the Website entry renders (not Defense).
    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "Website Proof" } })
    expect(screen.getByTestId("skills-panel-proof-empty-with-context")).toBeInTheDocument()
    const cards = screen.getAllByTestId("real-unmapped-proof-card")
    expect(cards.map((c) => c.getAttribute("data-proof-type"))).toEqual(["Website Proof"])

    // GitHub Proof filter → exact GitHub rows still render; no GitHub entry
    // exists in the real-unmapped context, so the panel disappears entirely.
    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "GitHub Proof" } })
    expect(screen.getAllByTestId("passport-skill-card")).toHaveLength(1)
    expect(screen.queryByTestId("real-unmapped-proof-section")).not.toBeInTheDocument()
  })

  it("renders nothing for URL-only metadata: an empty context list never fakes a proof card", async () => {
    // The project carries a repo_full_name AND a Website Proof source badge, but
    // the backend qualified NO real-unmapped proof (repo URL / website URL alone
    // are not proof) → the panel must not render at all.
    const p = makeRealUnmappedPassport({ real_unmapped_proof_context: [] })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    expect(screen.queryByTestId("real-unmapped-proof-section")).not.toBeInTheDocument()
    expect(screen.queryByText("Attached proof not yet skill-mapped")).not.toBeInTheDocument()

    // Under the Website Proof filter the generic honest empty copy returns —
    // never the with-context copy and never a fake proof card.
    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "Website Proof" } })
    expect(screen.getByTestId("skills-panel-proof-empty")).toBeInTheDocument()
    expect(screen.queryByTestId("skills-panel-proof-empty-with-context")).not.toBeInTheDocument()
    expect(screen.queryByTestId("real-unmapped-proof-card")).not.toBeInTheDocument()
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

  it("the 'Skills (N)' heading uses the FILTERED visible count under a proof filter, not the graph total", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // No filter active → heading reflects the full skill total (ML + FastAPI = 2).
    expect(screen.getByText("Skills (2)")).toBeInTheDocument()

    // Website Proof maps ONLY Machine Learning → the heading must read "Skills (1)",
    // never the full graph total (regression: Proof Type = Website Proof once showed
    // the whole "Skills (N)" count, e.g. "Skills (55)", even when few rows survived).
    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "Website Proof" } })
    expect(screen.getByText("Skills (1)")).toBeInTheDocument()
    expect(screen.queryByText("Skills (2)")).not.toBeInTheDocument()
    expect(screen.getAllByTestId("passport-skill-card")).toHaveLength(1)

    // Clearing the filter restores the full count.
    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "" } })
    expect(screen.getByText("Skills (2)")).toBeInTheDocument()
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

// ── Broad Website Proof does not leak across many skills ──────────────────────
//
// Regression for the "Skills (55)" leak: a project whose stored Website Proof
// carried a broad/dirty ``supported_skills`` list must NOT paint every claimed
// skill with a Website Proof chip. The backend canonical mapping now validates
// each skill/project pair, so only the genuinely-supported skills carry a
// per-project ``Website Proof`` in ``supporting_proof_types`` — and the Proof
// Type = Website Proof filter (plus its heading count) must reflect only those.

function makeBroadWebsiteSupportedPassport(): PrivateWorkPassport {
  const base = makePassport().projects[0]
  // Eight claimed skills on one project; the stored Website Proof named many of
  // them, but only two are actually validated as website-supported.
  const skillNames = [
    "Machine Learning",
    "Image Classification",
    "React",
    "Docker",
    "AWS",
    "SQL",
    "NLP",
    "Security",
  ]
  const websiteSupported = new Set(["Machine Learning", "Image Classification"])
  return makePassport({
    evidence_source_counts: { "GitHub Proof": 8, "Website Proof": 1 },
    skills: skillNames.map((skill) => {
      const proofTypes = websiteSupported.has(skill)
        ? ["GitHub Proof", "Website Proof"]
        : ["GitHub Proof"]
      return {
        skill,
        status: "Demonstrated",
        evidence_chip_count: 1,
        project_count: 1,
        // Passport-level union is deliberately broad; the per-project row is the
        // source of truth for whether Website Proof supports THIS skill.
        evidence_sources: proofTypes,
        projects: [
          {
            project_title: "Teachable Machine Image Classification Demo",
            project_id: "proj-tm",
            skill_status: "Demonstrated",
            evidence_sources: proofTypes,
            supporting_proof_types: proofTypes,
            report_is_public: false,
            public_report_path: null,
          },
        ],
        evidence_chips: [],
        notes: "",
        limitations: [],
      }
    }),
    projects: [
      {
        ...base,
        project_id: "proj-tm",
        project_title: "Teachable Machine Image Classification Demo",
        claimed_skills: skillNames,
        top_skills: skillNames.map((skill) => ({
          skill,
          status: "Demonstrated",
          skill_slug: skill.toLowerCase().replace(/\s+/g, "-"),
          supporting_proof_types: websiteSupported.has(skill)
            ? ["GitHub Proof", "Website Proof"]
            : ["GitHub Proof"],
        })),
      },
    ],
    project_count: 1,
  })
}

describe("PrivatePassportView — broad Website Proof supported_skills does not inflate the count", () => {
  beforeEach(() => {
    const p = makeBroadWebsiteSupportedPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
  })

  it("Proof Type = Website Proof shows only the validated skills, and the heading count matches (never 'Skills (8)')", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // All eight claimed skills are visible with no filter.
    expect(screen.getByText("Skills (8)")).toBeInTheDocument()
    expect(screen.getAllByTestId("passport-skill-card")).toHaveLength(8)

    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "Website Proof" } })

    // Only the two genuinely website-supported skills survive — the broad stored
    // list never leaks Website Proof onto Docker / AWS / SQL / NLP / Security.
    const skills = screen.getAllByTestId("passport-skill-card").map((c) => c.getAttribute("data-skill"))
    expect(skills.sort()).toEqual(["Image Classification", "Machine Learning"])
    // Heading reflects the FILTERED count, not the full graph total of 8.
    expect(screen.getByText("Skills (2)")).toBeInTheDocument()
    expect(screen.queryByText("Skills (8)")).not.toBeInTheDocument()

    // No generic fallback note leaks onto an unrelated, filtered-out skill.
    for (const card of screen.getAllByTestId("passport-skill-card")) {
      expect(["Machine Learning", "Image Classification"]).toContain(card.getAttribute("data-skill"))
    }
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

  // (I/J) Wider-vault isolation: a Website Proof that exists only in the skill's
  // WIDER PROOF VAULT (attached to a DIFFERENT project, or standalone) must never
  // ride onto the skill's ATTACHED proof-type set or add an attached project edge.
  it("wider-vault Website Proof never becomes attached proof-type or project edge", () => {
    const base = makePassport().projects[0]
    const p = makePassport({
      skills: [
        {
          // Machine Learning is attached only in proj-doc, via Document Proof.
          skill: "Machine Learning",
          status: "Demonstrated",
          evidence_chip_count: 1,
          project_count: 1,
          evidence_sources: ["Document Proof"],
          projects: [
            {
              project_title: "Teachable Machine Image Classification Demo",
              project_id: "proj-doc",
              skill_status: "Demonstrated",
              evidence_sources: ["Document Proof"],
              supporting_proof_types: ["Document Proof"],
              report_is_public: false,
              public_report_path: null,
            },
          ],
          evidence_chips: [],
          notes: "",
          limitations: [],
          // Wider vault carries an UNATTACHED Website Proof for ML.
          vault_only_sources: ["Website Proof"],
        },
      ],
      projects: [
        { ...base, project_id: "proj-doc", project_title: "Teachable Machine Image Classification Demo", claimed_skills: ["Machine Learning"], top_skills: [{ skill: "Machine Learning", status: "Demonstrated", skill_slug: "machine-learning", supporting_proof_types: ["Document Proof"] }] },
      ],
      // The wider vault summary spans the whole vault: it reports a Website Proof
      // for ML and even lists a different attached project. None of this may leak
      // into the ATTACHED graph.
      vault_skill_summaries: [
        makeVaultSummary({
          skill: "Machine Learning",
          skill_slug: "machine-learning",
          proof_source_counts: { "Document Proof": 1, "Website Proof": 1 },
          project_ids: ["proj-other"],
          project_titles: ["Some Other Project"],
          project_count: 1,
        }),
      ],
    })

    const graph = buildPassportGraph(p)
    const ml = graph.skills.find((s) => s.name === "Machine Learning")!

    // Attached proof types are Document only — the vault's Website Proof is excluded.
    expect(ml.proofTypes).toEqual(["Document Proof"])
    // Website Proof surfaces ONLY as a wider-vault (unattached) source, kept separate.
    expect(ml.vaultOnlySources).toEqual(["Website Proof"])
    // Only the truly-attached project edge exists; the vault's "proj-other" is not added.
    expect(ml.projectIds).toEqual(["proj-doc"])
    // No skill→project row advertises Website Proof, and none routes to proj-other.
    for (const row of ml.projectEvidence) {
      expect(row.hasWebsiteProof).toBe(false)
      expect(row.evidenceSources).not.toContain("Website Proof")
      expect(row.projectId).not.toBe("proj-other")
    }
  })

  // (K) Selecting the Website Proof filter over such a skill fails closed: the
  // only evidence rows are Document-backed, so no row survives the filter.
  it("Website Proof filter yields no attached row for a vault-only-Website skill", () => {
    const p = makePassport({
      skills: [
        {
          skill: "Machine Learning",
          status: "Demonstrated",
          evidence_chip_count: 1,
          project_count: 1,
          evidence_sources: ["Document Proof"],
          projects: [
            {
              project_title: "Teachable Machine Image Classification Demo",
              project_id: "proj-doc",
              skill_status: "Demonstrated",
              evidence_sources: ["Document Proof"],
              supporting_proof_types: ["Document Proof"],
              report_is_public: false,
              public_report_path: null,
            },
          ],
          evidence_chips: [],
          notes: "",
          limitations: [],
          vault_only_sources: ["Website Proof"],
        },
      ],
      projects: [
        { ...makePassport().projects[0], project_id: "proj-doc", project_title: "Teachable Machine Image Classification Demo", claimed_skills: ["Machine Learning"], top_skills: [{ skill: "Machine Learning", status: "Demonstrated", skill_slug: "machine-learning", supporting_proof_types: ["Document Proof"] }] },
      ],
      vault_skill_summaries: [
        makeVaultSummary({ skill: "Machine Learning", skill_slug: "machine-learning", proof_source_counts: { "Website Proof": 1 }, project_ids: [], project_titles: [], project_count: 0 }),
      ],
    })

    const graph = buildPassportGraph(p)
    const ml = graph.skills.find((s) => s.name === "Machine Learning")!
    // No skill→project row includes Website Proof → the filter has nothing to show.
    const websiteRows = ml.projectEvidence.filter((r) => r.evidenceSources.includes("Website Proof"))
    expect(websiteRows).toEqual([])
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

// Domain integration: copied/shared public Passport links must stay on the
// canonical app origin (NEXT_PUBLIC_APP_URL) rather than a preview origin.
describe("PrivatePassportView — canonical public link origin", () => {
  afterEach(() => vi.unstubAllEnvs())

  function renderPublishedPassport() {
    const p = makePassport({
      is_published: true,
      public_slug: "slug123",
      public_path: "/p/slug123",
      published_at: "2026-01-02T00:00:00Z",
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
    render(<PrivatePassportView />)
  }

  it("uses NEXT_PUBLIC_APP_URL for the public Passport link when it is set", async () => {
    vi.stubEnv("NEXT_PUBLIC_APP_URL", "https://veribridgeai.com")
    renderPublishedPassport()

    const link = await screen.findByTestId("passport-public-link")
    expect(link.textContent).toContain("https://veribridgeai.com/p/slug123")
    // In production the canonical origin must win — never a localhost link.
    expect(link.textContent).not.toContain("localhost")
  })

  it("normalizes a trailing slash on NEXT_PUBLIC_APP_URL (no double slash)", async () => {
    vi.stubEnv("NEXT_PUBLIC_APP_URL", "https://veribridgeai.com/")
    renderPublishedPassport()

    const link = await screen.findByTestId("passport-public-link")
    expect(link.textContent).toContain("https://veribridgeai.com/p/slug123")
    expect(link.textContent).not.toContain("veribridgeai.com//p/")
  })

  it("falls back to window.location.origin when NEXT_PUBLIC_APP_URL is unset", async () => {
    vi.stubEnv("NEXT_PUBLIC_APP_URL", "")
    renderPublishedPassport()

    const link = await screen.findByTestId("passport-public-link")
    expect(link.textContent).toContain(`${window.location.origin}/p/slug123`)
  })
})

// ── Proof-filter heading/count consistency (Codex PASS-WITH-FIXES regression) ──
//
// When a Proof Type filter (or any other evidence filter) is active, the Projects
// heading count must never contradict the filtered list below it. Previously the
// heading used the total passport.projects.length, so a Website/GitHub Proof
// filter with zero matching skill-project rows showed the contradictory pair
// "Skills (0)" + "Projects (2)". The heading must now track visibleProjects, the
// empty copy must honestly explain that project-level/vault-only proof is kept
// separate, and the capability summary must respect the active proof type.

// A passport where Website + GitHub Proof are OFFERED as proof-type options (they
// exist at project level / in the source counts) but NO skill→project row maps
// them — the only mapped evidence is Document Proof. Filtering by Website or
// GitHub therefore yields zero matching skill-project rows.
function makeProofOptionOnlyPassport(overrides: Partial<PrivateWorkPassport> = {}): PrivateWorkPassport {
  const base = makePassport().projects[0]
  return makePassport({
    skills: [
      {
        skill: "Machine Learning",
        status: "Demonstrated",
        evidence_chip_count: 1,
        project_count: 1,
        evidence_sources: ["Document Proof"],
        projects: [
          {
            project_title: "Doc-Only ML Project",
            project_id: "proj-doc",
            skill_status: "Demonstrated",
            evidence_sources: ["Document Proof"],
            supporting_proof_types: ["Document Proof"],
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
        project_id: "proj-doc",
        project_title: "Doc-Only ML Project",
        claimed_skills: ["Machine Learning"],
        // Project-level Website + GitHub proof exists (so both are offered as
        // proof-type options) but neither is mapped to the skill row above.
        evidence_sources: ["Document Proof", "Website Proof", "GitHub Proof"],
        top_skills: [
          { skill: "Machine Learning", status: "Demonstrated", skill_slug: "machine-learning", supporting_proof_types: ["Document Proof"] },
        ],
      },
      {
        ...base,
        project_id: "proj-extra",
        project_title: "Second Project",
        claimed_skills: [],
        evidence_sources: ["Website Proof", "GitHub Proof"],
        top_skills: [],
      },
    ],
    evidence_source_counts: { "Document Proof": 1, "Website Proof": 1, "GitHub Proof": 1 },
    project_count: 2,
    ...overrides,
  })
}

// A passport with exactly one Website-attached skill row and one GitHub-attached
// skill row, in different projects — so a proof filter narrows the map to a real
// subset (never the total, never zero).
function makeProofMixPassport(overrides: Partial<PrivateWorkPassport> = {}): PrivateWorkPassport {
  const base = makePassport().projects[0]
  const skillRow = (title: string, id: string, proofs: string[]) => ({
    project_title: title,
    project_id: id,
    skill_status: "Demonstrated",
    evidence_sources: proofs,
    supporting_proof_types: proofs,
    report_is_public: false,
    public_report_path: null,
  })
  return makePassport({
    skills: [
      {
        skill: "React",
        status: "Demonstrated",
        evidence_chip_count: 1,
        project_count: 1,
        evidence_sources: ["Website Proof"],
        projects: [skillRow("Web Product Demo", "proj-web", ["Website Proof"])],
        evidence_chips: [],
        notes: "",
        limitations: [],
      },
      {
        skill: "Python",
        status: "Demonstrated",
        evidence_chip_count: 1,
        project_count: 1,
        evidence_sources: ["GitHub Proof"],
        projects: [skillRow("Backend Service", "proj-git", ["GitHub Proof"])],
        evidence_chips: [],
        notes: "",
        limitations: [],
      },
    ],
    projects: [
      {
        ...base,
        project_id: "proj-web",
        project_title: "Web Product Demo",
        claimed_skills: ["React"],
        evidence_sources: ["Website Proof"],
        top_skills: [{ skill: "React", status: "Demonstrated", skill_slug: "react", supporting_proof_types: ["Website Proof"] }],
      },
      {
        ...base,
        project_id: "proj-git",
        project_title: "Backend Service",
        claimed_skills: ["Python"],
        evidence_sources: ["GitHub Proof"],
        top_skills: [{ skill: "Python", status: "Demonstrated", skill_slug: "python", supporting_proof_types: ["GitHub Proof"] }],
      },
    ],
    evidence_source_counts: { "Website Proof": 1, "GitHub Proof": 1 },
    project_count: 2,
    ...overrides,
  })
}

const setProof = (label: string) =>
  fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: label } })
const proofFilterSkillCard = (name: string) =>
  screen.queryAllByTestId("passport-skill-card").find((c) => c.getAttribute("data-skill") === name)
const proofFilterProjectCard = (id: string) =>
  screen.queryAllByTestId("passport-project-card").find((c) => c.getAttribute("data-project-id") === id)

describe("PrivatePassportView — proof-filter heading/count consistency", () => {
  // A — Website Proof with zero matching rows: Skills (0) + Projects (0), never
  // the contradictory Projects (2).
  it("Website Proof filter with no matching skill-project row shows Skills (0) and Projects (0)", async () => {
    const p = makeProofOptionOnlyPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // Baseline (no filter) shows the full project total.
    expect(screen.getByText("Projects (2)")).toBeInTheDocument()

    setProof("Website Proof")

    expect(screen.getByText("Skills (0)")).toBeInTheDocument()
    expect(screen.getByText("Projects (0)")).toBeInTheDocument()
    // The old contradictory "Projects (2)" heading is gone.
    expect(screen.queryByText("Projects (2)")).not.toBeInTheDocument()
    expect(proofFilterSkillCard("Machine Learning")).toBeUndefined()
    // Honest copy: project-level/vault-only Website Proof is kept separate.
    expect(screen.getByTestId("skills-panel-proof-empty")).toHaveTextContent(
      "No exact skill-project evidence matches Website Proof. Project-level or vault-only Website Proof is kept separate until it is attached to a specific project skill.",
    )
  })

  // B — GitHub Proof with zero matching rows: Skills (0) + Projects (0).
  it("GitHub Proof filter with no matching skill-project row shows Skills (0) and Projects (0)", async () => {
    const p = makeProofOptionOnlyPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    setProof("GitHub Proof")

    expect(screen.getByText("Skills (0)")).toBeInTheDocument()
    expect(screen.getByText("Projects (0)")).toBeInTheDocument()
    expect(screen.queryByText("Projects (2)")).not.toBeInTheDocument()
    expect(screen.getByTestId("skills-panel-proof-empty")).toHaveTextContent(
      "No exact skill-project evidence matches GitHub Proof. Repository references or vault-only GitHub evidence are kept separate until attached to a specific project skill.",
    )
  })

  // C — an active proof filter uses visibleProjects.length (a subset), not total.
  it("Projects heading uses the filtered count (not the total) when a proof filter is active", async () => {
    const p = makeProofMixPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // Two projects total; only the Website-attached one matches the filter.
    expect(screen.getByText("Projects (2)")).toBeInTheDocument()
    setProof("Website Proof")
    expect(screen.getByText("Projects (1)")).toBeInTheDocument()
    expect(screen.queryByText("Projects (2)")).not.toBeInTheDocument()
    expect(proofFilterProjectCard("proj-web")).toBeDefined()
    expect(proofFilterProjectCard("proj-git")).toBeUndefined()
  })

  // D — with no filters active the Projects heading shows the full total.
  it("Projects heading uses the total passport.projects.length when no filters are active", async () => {
    const p = makeProofMixPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    expect(screen.getByText("Projects (2)")).toBeInTheDocument()
    expect(screen.getByText("Skills (2)")).toBeInTheDocument()
    expect(screen.queryByTestId("clear-filters-button")).not.toBeInTheDocument()
  })

  // E — Role Area + Proof Type compose with AND semantics: a proof that exists in
  // the passport but NOT within the selected role area's evidence yields nothing.
  it("Role Area + Proof Type filters use AND semantics (proof must match within the role area)", async () => {
    const p = makeRoleAreaPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // GitHub Proof exists in the passport (Boston/backend), so it is a valid option.
    selectRole("computer-vision")
    setProof("GitHub Proof")
    // But the Computer Vision role area's own evidence (Teachable) has NO GitHub
    // Proof → AND semantics remove every skill; it is not treated as OR.
    expect(screen.queryAllByTestId("passport-skill-card")).toHaveLength(0)
    expect(screen.getByTestId("skills-panel-role-proof-empty")).toBeInTheDocument()
    // The capability summary is scoped away too (no unfiltered/overall summary).
    expect(screen.queryByTestId("capability-summary")).not.toBeInTheDocument()
    expect(screen.getByTestId("capability-proof-empty")).toHaveTextContent(
      "No exact evidence for this role area matches the selected proof type",
    )
  })

  // F — the capability summary must not show a Document Proof chain while the
  // active Proof Type filter is Website Proof.
  it("capability summary does not show a Document Proof chain while Proof Type = Website Proof", async () => {
    const p = makeRoleAreaPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // Computer Vision's evidence includes Document Proof (Teachable ML), but under a
    // Website Proof filter the summary must be scoped to Website Proof only.
    selectRole("computer-vision")
    setProof("Website Proof")
    const summary = screen.getByTestId("capability-summary")
    expect(summary).toHaveAttribute("data-capability", "Computer Vision")

    const coverage = within(summary).queryAllByTestId("capability-proof-chip").map((c) => c.getAttribute("data-source"))
    expect(coverage).toContain("Website Proof")
    expect(coverage).not.toContain("Document Proof")
    // No proof chip anywhere in the summary (coverage, skills, projects) is Document.
    const allProofSources = within(summary)
      .queryAllByTestId(/proof-chip$/)
      .map((c) => c.getAttribute("data-source"))
    expect(allProofSources).not.toContain("Document Proof")
    // The evidence-chain connector must not carry a Document Proof node either.
    const chainNodes = within(summary).getAllByTestId("capability-chain-node").map((n) => n.textContent)
    expect(chainNodes).not.toContain("Document Proof")
  })

  // G — a valid attached Website Proof skill-project row still appears and counts.
  it("keeps a genuinely attached Website Proof skill-project row visible with a correct count", async () => {
    const p = makeProofMixPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    setProof("Website Proof")
    expect(screen.getByText("Skills (1)")).toBeInTheDocument()
    expect(screen.getByText("Projects (1)")).toBeInTheDocument()
    expect(proofFilterSkillCard("React")).toBeDefined()
    expect(proofFilterSkillCard("Python")).toBeUndefined()
    expect(proofFilterProjectCard("proj-web")).toBeDefined()
    // No contradictory empty state when a real match exists.
    expect(screen.queryByTestId("skills-panel-proof-empty")).not.toBeInTheDocument()
  })

  // H — a valid attached GitHub Proof skill-project row still appears and counts.
  it("keeps a genuinely attached GitHub Proof skill-project row visible with a correct count", async () => {
    const p = makeProofMixPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    setProof("GitHub Proof")
    expect(screen.getByText("Skills (1)")).toBeInTheDocument()
    expect(screen.getByText("Projects (1)")).toBeInTheDocument()
    expect(proofFilterSkillCard("Python")).toBeDefined()
    expect(proofFilterSkillCard("React")).toBeUndefined()
    expect(proofFilterProjectCard("proj-git")).toBeDefined()
    expect(screen.queryByTestId("skills-panel-proof-empty")).not.toBeInTheDocument()
  })
})

// ── Proof Relationship UX — legend, relationship labels, honest separation ─────
// The guide + relationship labels are pure presentation: they explain how proof
// relates to the Passport (direct skill evidence / project-level / attached-not-
// skill-mapped / vault-only) without changing a single count, filter, or row.

describe("PrivatePassportView — Proof Relationship UX", () => {
  it("renders the compact proof relationship guide with all four relationship tiers", async () => {
    const p = makeProofBreakdownPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const guide = screen.getByTestId("proof-relationship-guide")
    expect(guide).toHaveTextContent("Proof relationship guide")
    const items = within(guide).getAllByTestId("proof-relationship-guide-item")
    expect(items.map((i) => i.getAttribute("data-kind"))).toEqual(["skill", "project", "unmapped", "vault"])
    expect(guide).toHaveTextContent("Direct skill evidence")
    expect(guide).toHaveTextContent("Project-level proof")
    expect(guide).toHaveTextContent("Attached, not skill-mapped")
    expect(guide).toHaveTextContent("Vault-only / suggested")
    // The guide never overclaims: counted-ness is stated honestly.
    expect(guide).toHaveTextContent("the only proof counted in the map and proof filters")
    expect(guide).toHaveTextContent("never counted as skill evidence")
  })

  it("labels skill→project rows as direct skill evidence (heading + project-card chips label)", async () => {
    const p = makeProofBreakdownPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    // Every skill→project row heading names the relationship explicitly.
    for (const h of screen.getAllByTestId("skill-project-evidence-heading")) {
      expect(h).toHaveTextContent("Direct skill evidence in this project:")
    }
    // Project-card per-skill chip rows carry the same label.
    const bostonCard = screen
      .getAllByTestId("passport-project-card")
      .find((c) => c.getAttribute("data-project-id") === "proj-boston")!
    const mlChips = within(bostonCard)
      .getAllByTestId("project-skill-proof-chips")
      .find((r) => r.getAttribute("data-skill") === "Machine Learning")!
    expect(mlChips).toHaveTextContent("Direct skill evidence:")
  })

  it("project card separates direct skill evidence from project-level-only proof (never mixed)", async () => {
    // proj-boston (from makeWebsiteGlobalOnlyPassport): attached GitHub + Website,
    // but only GitHub maps to a skill → Website must appear ONLY as project-level.
    const p = makeWebsiteGlobalOnlyPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const strip = screen.getByTestId("project-proof-relationships")
    const skillChips = within(strip)
      .getAllByTestId("project-relationship-skill-chip")
      .map((c) => c.getAttribute("data-source"))
    expect(skillChips).toEqual(["GitHub Proof"])
    const projectChips = within(strip)
      .getAllByTestId("project-relationship-project-chip")
      .map((c) => c.getAttribute("data-source"))
    expect(projectChips).toEqual(["Website Proof"])
    // Website Proof is NOT claimed as direct skill evidence anywhere in the strip.
    expect(skillChips).not.toContain("Website Proof")
    expect(strip).toHaveTextContent("Project-level proof (not skill-specific):")
    // The exact skill row in the map still cites only GitHub for ML.
    const ml = mapSkillCard("Machine Learning")
    const row = within(ml).getAllByTestId("skill-project-evidence-row")[0]
    expect(rowChipSources(row)).toEqual(["GitHub Proof"])
  })

  it("fails closed: legacy payloads without supporting_proof_types render no relationship strip", async () => {
    // Skill rows exist but carry NO skill-specific breakdown — the skill-vs-
    // project split is unknowable, so nothing may be inferred or faked.
    const p = makeWebsiteGlobalOnlyPassport()
    p.projects = p.projects.map((proj) => ({
      ...proj,
      top_skills: (proj.top_skills ?? []).map((t) => {
        const legacy = { ...t }
        delete legacy.supporting_proof_types
        return legacy
      }),
    }))
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    expect(screen.queryByTestId("project-proof-relationships")).not.toBeInTheDocument()
  })

  it("the real-unmapped panel carries the 'Attached, not skill-mapped' relationship badge", async () => {
    const p = makeRealUnmappedPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    const panel = screen.getByTestId("real-unmapped-proof-section")
    expect(within(panel).getByTestId("real-unmapped-proof-heading")).toHaveTextContent(
      "Attached proof not yet skill-mapped",
    )
    const badge = within(panel).getByTestId("evidence-relationship-badge")
    expect(badge).toHaveAttribute("data-kind", "unmapped")
    expect(badge).toHaveTextContent("Attached, not skill-mapped")
  })

  it("vault-only sections carry the 'Vault-only / suggested' relationship badge", async () => {
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
    const vault = within(rust).getByTestId("skill-vault-only")
    const badge = within(vault).getByTestId("evidence-relationship-badge")
    expect(badge).toHaveAttribute("data-kind", "vault")
    expect(badge).toHaveTextContent("Vault-only / suggested")
  })

  it("an active proof filter states it shows direct skill evidence, with separation noted", async () => {
    const p = makeProofBreakdownPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "Website Proof" } })
    expect(screen.getByTestId("summary-proof")).toHaveTextContent(
      "Showing direct skill evidence with: Website Proof",
    )
    expect(screen.getByTestId("summary-proof-separation-note")).toHaveTextContent(
      "Project-level, attached-but-not-skill-mapped, and vault-only evidence is listed separately and never counted here.",
    )
  })

  it("the proof-filter empty state explains where related proof may live and points at the vault when pending proof exists", async () => {
    const p = makeWebsiteGlobalOnlyPassport({
      vault_unattached_count: 2,
      attachment_overview: {
        attached_count: 1,
        suggested_count: 1,
        unattached_count: 2,
        attached: [],
        suggested: [],
        unattached: [],
        note: "",
      },
      // Video exists in the vault only → offered as a filter option, matches no row.
      evidence_source_counts: { "GitHub Proof": 2, "Website Proof": 1, "Video Evidence": 1 },
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "Video Evidence" } })
    expect(screen.getByTestId("skills-panel-proof-empty")).toHaveTextContent(
      "No exact skill evidence matches Video Evidence. Related proof may be project-level, attached but not skill-mapped, or still in your Proof Vault — those are listed separately and never counted as skill evidence.",
    )
    // 1 suggested + 2 unattached → 3 pending, pointed at Improve Passport.
    expect(screen.getByTestId("skills-panel-vault-hint")).toHaveTextContent(
      "3 proofs are suggested or unattached in your Proof Vault",
    )
  })

  it("Improve Passport explains that suggested/unattached proof is not counted until attached", async () => {
    const p = makeProofBreakdownPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("improve-passport-card")

    const explainer = screen.getByTestId("improve-passport-explainer")
    expect(explainer).toHaveTextContent("Suggested or unattached proof is not counted as skill evidence yet.")
    expect(explainer).toHaveTextContent("Attach proof to a project report to make it eligible as skill evidence.")
    expect(explainer).toHaveTextContent("Vault-only proof never appears as skill evidence until it is attached.")
  })

  it("the relationship guide changes no counts, filter options, or evidence rows", async () => {
    const p = makeRealUnmappedPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    // Guide present…
    expect(screen.getByTestId("proof-relationship-guide")).toBeInTheDocument()
    // …with the same counts and options the pre-guide tests assert.
    expect(screen.getByText("Skills (1)")).toBeInTheDocument()
    expect(screen.getByText("Projects (1)")).toBeInTheDocument()
    expect(proofFilterOptionNames()).toEqual(["All proof types", "GitHub Proof", "Website Proof"])
    const ml = mapSkillCard("Machine Learning")
    const row = within(ml).getAllByTestId("skill-project-evidence-row")[0]
    expect(rowChipSources(row)).toEqual(["GitHub Proof"])
  })

  it("never renders overclaiming language anywhere on the passport", async () => {
    const p = makeRealUnmappedPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    expect(screen.queryByText(/certified/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/guaranteed/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/verified expert/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/proof found nearby/i)).not.toBeInTheDocument()
  })
})

// ── Proof Relationship UX — cross-skill consistency (second pass) ──────────────
// EVERY skill card and project row renders the SAME tier structure: direct skill
// evidence (primary) → project-level proof (secondary) → vault-only (tertiary),
// with no bare chip rows, no duplicate action links, and unchanged counts.

describe("PrivatePassportView — Proof Relationship UX consistency", () => {
  /** Breakdown fixture + Machine Learning vault-only sources, so one card has
   *  all three tiers at once (direct + project-level + vault-only). */
  function makeAllTiersPassport(): PrivateWorkPassport {
    const p = makeProofBreakdownPassport()
    p.skills[0].vault_only_sources = ["GitHub Proof", "Project Defense"]
    return p
  }

  beforeEach(() => {
    const p = makeAllTiersPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
  })

  it("every skill→project row renders the SAME primary direct-evidence tier (no bare chip rows)", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const rows = screen.getAllByTestId("skill-project-evidence-row")
    expect(rows.length).toBeGreaterThan(0)
    for (const row of rows) {
      // Consistent tier container + heading in every row, across every skill.
      const tier = within(row).getByTestId("skill-project-direct-tier")
      expect(tier).toHaveAttribute("data-tier", "skill")
      expect(within(tier).getByTestId("skill-project-evidence-heading")).toHaveTextContent(
        "Direct skill evidence in this project:",
      )
      // Never a silent gap: either scoped chips or the explicit no-direct line.
      const hasChips = within(row).queryAllByTestId("skill-project-proof-chip").length > 0
      const hasNoDirect = within(row).queryByTestId("skill-project-no-direct") !== null
      expect(hasChips || hasNoDirect).toBe(true)
    }
  })

  it("a row WITH direct evidence still separates the project's remaining proof into the project-level tier", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    // ML in Boston: direct = GitHub/Website/Document/Defense; the project also
    // carries Video Evidence, which is NOT mapped to ML → project-level tier.
    const ml = breakdownSkillCard("Machine Learning")
    const boston = within(ml)
      .getAllByTestId("skill-project-evidence-row")
      .find((r) => r.getAttribute("data-project-id") === "proj-boston")!
    expect(rowChipSources(boston)).toEqual(["GitHub Proof", "Website Proof", "Document Proof", "Project Defense"])
    const tier = within(boston).getByTestId("skill-project-level-tier")
    expect(
      within(tier).getAllByTestId("skill-project-level-chip").map((c) => c.getAttribute("data-source")),
    ).toEqual(["Video Evidence"])
    // The tiers never mix: project-level chips are not direct chips and vice versa.
    expect(rowChipSources(boston)).not.toContain("Video Evidence")
    expect(within(tier).queryByTestId("skill-project-proof-chip")).toBeNull()

    // FastAPI in the SAME project gets the SAME treatment (consistency across
    // skills): direct GitHub/Document; the project's other ATTACHED sources
    // (Defense/Video — Website is not attached at the project level here) land
    // in the project-level tier, never as FastAPI evidence.
    const fastapi = breakdownSkillCard("FastAPI")
    const faRow = within(fastapi).getAllByTestId("skill-project-evidence-row")[0]
    expect(rowChipSources(faRow)).toEqual(["GitHub Proof", "Document Proof"])
    expect(
      within(faRow).getAllByTestId("skill-project-level-chip").map((c) => c.getAttribute("data-source")),
    ).toEqual(["Project Defense", "Video Evidence"])
  })

  it("a skill card with exact + vault-only evidence renders them in separate tiers with one skill-report link", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const ml = breakdownSkillCard("Machine Learning")
    // Direct rows (primary) and the vault-only section (tertiary) coexist, apart.
    expect(within(ml).getAllByTestId("skill-project-direct-tier").length).toBeGreaterThan(0)
    const standalone = within(ml).getByTestId("skill-standalone-evidence")
    expect(within(standalone).getByTestId("evidence-relationship-badge")).toHaveAttribute("data-kind", "vault")
    expect(
      within(standalone).getAllByTestId("skill-standalone-proof-chip").map((c) => c.getAttribute("data-source")),
    ).toEqual(["GitHub Proof", "Project Defense"])
    // Vault-only chips never render as direct chips.
    expect(within(standalone).queryByTestId("skill-project-proof-chip")).toBeNull()
    // Deduped actions: exactly ONE "Open full … skill report" link per card
    // (the footer), and the vault section routes to the Proof Vault instead.
    expect(within(ml).getAllByText(/Open full Machine Learning skill report/)).toHaveLength(1)
    expect(within(standalone).getByTestId("skill-standalone-open-vault")).toHaveAttribute(
      "href",
      "/student/vbr/passport/vault",
    )
  })

  it("under the Website Proof filter every visible row keeps the direct-evidence label, naming the filter", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "Website Proof" } })

    const rows = screen.getAllByTestId("skill-project-evidence-row")
    expect(rows.length).toBeGreaterThan(0)
    for (const row of rows) {
      expect(within(row).getByTestId("skill-project-evidence-heading")).toHaveTextContent(
        "Direct skill evidence · Website Proof:",
      )
      expect(rowChipSources(row)).toContain("Website Proof")
      // The proof-filter lens shows counted direct evidence only — no secondary
      // project-level tier that could read as matching the filter.
      expect(within(row).queryByTestId("skill-project-level-tier")).toBeNull()
    }
  })

  it("under the Project Defense filter every visible row keeps the direct-evidence label, naming the filter", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-evidence-controls")

    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "Project Defense" } })

    const rows = screen.getAllByTestId("skill-project-evidence-row")
    expect(rows.length).toBeGreaterThan(0)
    for (const row of rows) {
      expect(within(row).getByTestId("skill-project-evidence-heading")).toHaveTextContent(
        "Direct skill evidence · Project Defense:",
      )
      expect(rowChipSources(row)).toContain("Project Defense")
    }
  })

  it("project-card skill rows state 'No direct skill evidence yet' instead of a silent chip gap", async () => {
    const p = makeAllTiersPassport()
    // A top-skill whose mapping recorded NO proof types for it in this project.
    p.projects[0].top_skills!.push({
      skill: "Browser APIs",
      status: "Not assessed",
      skill_slug: "browser-apis",
      supporting_proof_types: [],
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const bostonCard = screen
      .getAllByTestId("passport-project-card")
      .find((c) => c.getAttribute("data-project-id") === "proj-boston")!
    const row = within(bostonCard)
      .getAllByTestId("project-top-skill-row")
      .find((r) => r.getAttribute("data-skill") === "Browser APIs")!
    expect(within(row).getByTestId("project-skill-no-direct")).toHaveTextContent(
      "No direct skill evidence yet — this project's attached proof is project-level for this skill.",
    )
    expect(within(row).queryByTestId("project-skill-proof-chip")).toBeNull()
    // Rows with a recorded mapping keep their labelled direct chips.
    const mlRow = within(bostonCard)
      .getAllByTestId("project-top-skill-row")
      .find((r) => r.getAttribute("data-skill") === "Machine Learning")!
    expect(within(mlRow).getByTestId("project-skill-proof-chips")).toHaveTextContent("Direct skill evidence:")
  })

  it("the tier split changes no proof counts, filter options, or direct chips", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    // Same skill/project counts and direct chips the pre-split tests assert.
    expect(screen.getByText("Skills (2)")).toBeInTheDocument()
    expect(screen.getByText("Projects (2)")).toBeInTheDocument()
    const ml = breakdownSkillCard("Machine Learning")
    const teachable = within(ml)
      .getAllByTestId("skill-project-evidence-row")
      .find((r) => r.getAttribute("data-project-id") === "proj-tm")!
    expect(rowChipSources(teachable)).toEqual(["Website Proof", "Document Proof", "Project Defense", "Video Evidence"])
  })
})

// ── Skills Evidence Map wiring regressions (skill-evidence-map-fix) ────────────
//
// Root cause proved against the real dev user (836d5bc3): the Proof Vault summary
// carries a `project_count` that counts duplicate-attempt `vbr_projects` rows
// (e.g. 24 rows for 2 real projects), and the map used to fold it into the
// connected-project count — so a skill with ZERO resolvable project edges rendered
// "Connected projects: 24" while showing no project rows. At the same time, a
// skill whose evidence lived only in the vault (GitHub / Document proof, no
// VBR-report skill_evidence row) rendered an EMPTY "vault-only" tier, hiding the
// real proof source. These lock both defects closed.
describe("buildPassportGraph — vault project-count honesty + vault proof visibility", () => {
  it("never inflates connected projects from the vault summary's raw project_count", () => {
    // Docker lives only in the Proof Vault: no report skill_evidence row and no
    // project top_skill. Its vault summary claims 24 projects (duplicate rows).
    const p = makeGraphPassport({
      skills: [],
      vault_skill_summaries: [
        makeVaultSummary({
          skill: "Docker",
          skill_slug: "docker",
          project_count: 24,
          project_ids: [],
          project_titles: [],
          proof_source_counts: { "GitHub Proof": 14, "Document Proof": 1, "Skill Graph": 1 },
          proof_count: 16,
          attached_count: 3,
          unattached_count: 13,
        }),
      ],
    })

    const graph = buildPassportGraph(p)
    const docker = graph.skills.find((s) => s.name === "Docker")!

    // Honest: no resolvable project edge → zero connected projects (never 24).
    expect(docker.projectIds).toEqual([])
    expect(docker.projectCount).toBe(0)
    // …but its real proof source is NOT invisible — the vault's GitHub + Document
    // proof surfaces as vault-only chips (the non-proof "Skill Graph" is dropped).
    expect(docker.vaultOnlySources).toEqual(["GitHub Proof", "Document Proof"])
    expect(docker.proofSourceCount).toBe(2)
  })

  it("keeps the honest grouped project_count for a skill with real project edges", () => {
    // A report skill with one resolvable edge whose vault summary over-reports 21
    // duplicate-attempt rows must still read one connected project.
    const base = makePassport().projects[0]
    const p = makePassport({
      skills: [
        {
          skill: "FastAPI",
          status: "Partially demonstrated",
          evidence_chip_count: 1,
          project_count: 1,
          evidence_sources: ["GitHub Proof", "Document Proof"],
          projects: [
            {
              project_title: "Boston Smart Accident Risk Rerouting",
              project_id: "proj-boston",
              skill_status: "Partially demonstrated",
              evidence_sources: ["GitHub Proof", "Document Proof"],
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
        { ...base, project_id: "proj-boston", project_title: "Boston Smart Accident Risk Rerouting", claimed_skills: ["FastAPI"], top_skills: [{ skill: "FastAPI", status: "Partially demonstrated", skill_slug: "fastapi", supporting_proof_types: ["GitHub Proof", "Document Proof"] }] },
      ],
      vault_skill_summaries: [
        makeVaultSummary({ skill: "FastAPI", skill_slug: "fastapi", project_count: 21, project_ids: [], proof_source_counts: { "GitHub Proof": 2 } }),
      ],
    })

    const graph = buildPassportGraph(p)
    const fastapi = graph.skills.find((s) => s.name === "FastAPI")!

    expect(fastapi.projectIds).toEqual(["proj-boston"])
    expect(fastapi.projectCount).toBe(1) // never the vault's 21
  })

  it("does not synthesize vault-only chips for a skill that already has an attached project edge", () => {
    // A skill with a real project edge shows its proof on the project row; the
    // vault summary's proof types must NOT be re-labelled vault-only for it.
    const base = makePassport().projects[0]
    const p = makePassport({
      skills: [
        {
          skill: "Python",
          status: "Demonstrated",
          evidence_chip_count: 1,
          project_count: 1,
          evidence_sources: ["GitHub Proof"],
          projects: [
            {
              project_title: "Boston Smart Accident Risk Rerouting",
              project_id: "proj-boston",
              skill_status: "Demonstrated",
              evidence_sources: ["GitHub Proof"],
              supporting_proof_types: ["GitHub Proof"],
              report_is_public: false,
              public_report_path: null,
            },
          ],
          evidence_chips: [],
          notes: "",
          limitations: [],
          // No backend-computed unattached vault sources for this skill.
        },
      ],
      projects: [
        { ...base, project_id: "proj-boston", project_title: "Boston Smart Accident Risk Rerouting", claimed_skills: ["Python"], top_skills: [{ skill: "Python", status: "Demonstrated", skill_slug: "python", supporting_proof_types: ["GitHub Proof"] }] },
      ],
      vault_skill_summaries: [
        makeVaultSummary({ skill: "Python", skill_slug: "python", project_count: 24, project_ids: [], proof_source_counts: { "GitHub Proof": 5, "Website Proof": 1 } }),
      ],
    })

    const graph = buildPassportGraph(p)
    const python = graph.skills.find((s) => s.name === "Python")!

    // Proof shows on the attached project row, not as a synthesized vault tier.
    expect(python.vaultOnlySources).toEqual([])
    expect(python.projectCount).toBe(1)
  })

  it("offers a proof type in the Proof Type dropdown when only a vault-only skill has it", () => {
    // Regression: a candidate with GitHub/Document proof that lives only in the
    // vault must still be able to filter by those proof types.
    const p = makeGraphPassport({
      skills: [],
      evidence_source_counts: {},
      projects: [],
      vault_skill_summaries: [
        makeVaultSummary({
          skill: "Technical Documentation",
          skill_slug: "technical-documentation",
          project_count: 24,
          project_ids: [],
          proof_source_counts: { "Document Proof": 14, "Skill Graph": 1 },
        }),
      ],
    })

    const graph = buildPassportGraph(p)
    expect(graph.proofTypeOptions).toContain("Document Proof")
  })

  it("renders a purely-vault skill with 0 connected projects AND its real proof chips", async () => {
    const p = makeGraphPassport({
      skills: [],
      projects: [],
      evidence_source_counts: {},
      vault_skill_summaries: [
        makeVaultSummary({
          skill: "Docker",
          skill_slug: "docker",
          project_count: 24,
          project_ids: [],
          project_titles: [],
          proof_source_counts: { "GitHub Proof": 14, "Document Proof": 1, "Skill Graph": 1 },
        }),
      ],
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const docker = mapSkillCard("Docker")
    // Honest count — never the vault summary's inflated 24.
    expect(within(docker).getByTestId("skill-project-count")).toHaveTextContent("Connected projects: 0")
    // The real GitHub + Document proof is visible (previously an empty row).
    const vault = within(docker).getByTestId("skill-vault-only")
    const chips = within(vault)
      .getAllByTestId("skill-vault-only-chip")
      .map((c) => c.getAttribute("data-source"))
    expect(chips).toEqual(["GitHub Proof", "Document Proof"])
  })
})

describe("canonical Website Proof project suggestions", () => {
  it("Website Proof filter shows the suggested VeriBridge project and isolates Boston", async () => {
    const base = makePassport().projects[0]
    const p = makeGraphPassport({
      skills: [],
      projects: [
        { ...base, project_id: "proj-veribridge", project_title: "VeriBridge", repo_full_name: "veribridge/veribridge", claimed_skills: ["React"], evidence_sources: [] },
        { ...base, project_id: "proj-boston", project_title: "Boston Smart Accident Risk Routing", repo_full_name: "demo/boston", claimed_skills: ["React"], evidence_sources: [] },
      ],
      evidence_source_counts: { "Website Proof": 1 },
      vault_skill_summaries: [
        makeVaultSummary({
          skill: "React",
          skill_slug: "react",
          project_ids: [],
          project_titles: [],
          project_count: 0,
          connected_project_ids: [],
          has_retained_proof: true,
          proof_source_counts: { "Website Proof": 1 },
        }),
      ],
      unattached_proof_summary: {
        unattached_count: 1,
        suggestion_count: 1,
        unmatched_count: 0,
        suggestions: [{
          suggestion_id_safe: "suggest-veribridge",
          proof_type: "Website Proof",
          proof_title: "Website Proof",
          proof_count: 1,
          likely_project_title: "VeriBridge",
          likely_project_ref_safe: "/student/vbr/projects/proj-veribridge/report",
          likely_skill_names: ["React"],
          suggestion_reason: "The proof objective names the VeriBridge project.",
          evidence_basis_chips: ["Matching project title"],
          confidence_label: "Likely match",
          attachment_status: "Not attached to a VBR project",
          limitation: "Suggested match only — review before attaching.",
          action_label: "Review and attach proof",
        }],
      },
    })
    const graph = buildPassportGraph(p)
    const react = graph.skills.find((skill) => skill.name === "React")!
    expect(react.projectIds).toEqual([])
    expect(react.projectCount).toBe(0)
    expect(react.suggestedProjects).toEqual([
      expect.objectContaining({ projectId: "proj-veribridge", proofType: "Website Proof" }),
    ])

    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
    render(<PrivatePassportView />)
    await screen.findAllByTestId("passport-project-card")
    fireEvent.change(screen.getByTestId("passport-proof-filter"), { target: { value: "Website Proof" } })
    const cards = screen.getAllByTestId("passport-project-card")
    expect(cards).toHaveLength(1)
    expect(cards[0]).toHaveTextContent("VeriBridge")
    expect(cards[0]).not.toHaveTextContent("Boston Smart Accident Risk Routing")
    expect(screen.getByTestId("skill-suggested-projects")).toHaveTextContent("not counted")
  })
})

// ── Canonical relationship model + suggested skills + evidence filters ─────────
describe("buildPassportGraph — canonical relationship model", () => {
  it("classifies a vault skill attached to a real project as 'attached' (not vault-only)", () => {
    const p = makeGraphPassport({
      skills: [],
      vault_skill_summaries: [
        makeVaultSummary({
          skill: "Docker",
          skill_slug: "docker",
          project_count: 24,
          project_ids: ["raw-a", "raw-b"],
          connected_project_ids: ["proj-1"],
          connected_project_titles: ["Skill Evidence Tracker"],
          has_retained_proof: true,
          proof_source_counts: { "GitHub Proof": 14, "Document Proof": 1 },
        }),
      ],
    })

    const graph = buildPassportGraph(p)
    const docker = graph.skills.find((s) => s.name === "Docker")!

    expect(docker.relationship).toBe("attached")
    expect(docker.attachedProjects).toEqual([{ projectId: "proj-1", projectTitle: "Skill Evidence Tracker" }])
    // Counted as ONE connected project (the grouped representative), never 24.
    expect(docker.projectCount).toBe(1)
    expect(docker.hasRetainedProof).toBe(true)
  })

  it("classifies a Skill-Graph-only skill as 'suggested' with no retained proof", () => {
    const p = makeGraphPassport({
      skills: [],
      projects: [],
      vault_skill_summaries: [
        makeVaultSummary({
          skill: "AI / Machine Learning",
          skill_slug: "ai-machine-learning",
          project_count: 0,
          project_ids: [],
          connected_project_ids: [],
          has_retained_proof: false,
          proof_source_counts: { "Skill Graph": 1 },
        }),
      ],
    })

    const graph = buildPassportGraph(p)
    const s = graph.skills.find((x) => x.name === "AI / Machine Learning")!

    expect(s.relationship).toBe("suggested")
    expect(s.hasRetainedProof).toBe(false)
    expect(s.proofSourceCount).toBe(0)
    expect(s.projectCount).toBe(0)
  })

  it("keeps a direct report skill as 'direct' even when a vault summary also lists it", () => {
    const p = makeGraphPassport({
      vault_skill_summaries: [
        makeVaultSummary({ skill: "Python", skill_slug: "python", connected_project_ids: ["proj-1"], has_retained_proof: true }),
      ],
    })
    const graph = buildPassportGraph(p)
    const python = graph.skills.find((s) => s.name === "Python")!
    expect(python.relationship).toBe("direct")
    expect(python.attachedProjects).toEqual([])
  })
})

// Mixed passport: one DIRECT (Python), one ATTACHED-not-mapped (Docker), one
// SUGGESTED (AI / ML). Drives the suggested-hiding + relationship/status/source
// filters + active chips.
function makeMixedRelationshipPassport(overrides: Partial<PrivateWorkPassport> = {}): PrivateWorkPassport {
  return makeGraphPassport({
    vault_skill_summaries: [
      makeVaultSummary({ skill: "Python", skill_slug: "python", connected_project_ids: ["proj-1"], has_retained_proof: true, proof_source_counts: { "GitHub Proof": 2 } }),
      makeVaultSummary({
        skill: "Docker",
        skill_slug: "docker",
        status: "Evidence observed",
        project_count: 24,
        project_ids: ["raw-a"],
        connected_project_ids: ["proj-1"],
        connected_project_titles: ["Skill Evidence Tracker"],
        has_retained_proof: true,
        proof_source_counts: { "Document Proof": 3 },
      }),
      makeVaultSummary({
        skill: "AI / Machine Learning",
        skill_slug: "ai-machine-learning",
        status: "Supporting evidence",
        project_count: 0,
        project_ids: [],
        connected_project_ids: [],
        has_retained_proof: false,
        proof_source_counts: { "Skill Graph": 1 },
      }),
    ],
    ...overrides,
  })
}

const selectFilter = (testid: string, value: string) =>
  fireEvent.change(screen.getByTestId(testid), { target: { value } })

describe("PrivatePassportView — suggested-skill hiding + evidence filters", () => {
  beforeEach(() => {
    const p = makeMixedRelationshipPassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
  })

  it("hides suggested skills by default and reveals them on demand", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    // Direct + attached shown; the bare suggestion is hidden.
    expect(querySkillCard("Python")).toBeDefined()
    expect(querySkillCard("Docker")).toBeDefined()
    expect(querySkillCard("AI / Machine Learning")).toBeUndefined()

    // An honest note offers to review the hidden suggestion.
    const note = screen.getByTestId("suggested-skills-note")
    expect(note).toHaveTextContent("1 AI-suggested skill is hidden")
    fireEvent.click(screen.getByTestId("show-suggested-skills"))

    // Now only the suggestion shows, and it is NOT dressed up as observed evidence.
    expect(querySkillCard("AI / Machine Learning")).toBeDefined()
    const s = skillCard("AI / Machine Learning")
    expect(within(s).getByTestId("skill-overall-status")).toHaveTextContent("Suggested — no retained proof")
    expect(within(s).getByTestId("skill-overall-status")).not.toHaveTextContent("Evidence observed")
    expect(within(s).getByTestId("skill-suggested")).toBeInTheDocument()
  })

  it("renders the attached-not-skill-mapped tier with a real project link", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    const docker = skillCard("Docker")
    expect(within(docker).getByTestId("skill-relationship-badge")).toHaveAttribute("data-relationship", "attached")
    expect(within(docker).getByTestId("skill-project-count")).toHaveTextContent("Connected projects: 1")
    const tier = within(docker).getByTestId("skill-attached-not-mapped")
    expect(within(tier).getByTestId("skill-attached-project-link")).toHaveAttribute(
      "href",
      "/student/vbr/projects/proj-1/report",
    )
    // Its proof is visible but never presented as direct skill evidence.
    expect(within(docker).queryByTestId("skill-project-evidence-row")).not.toBeInTheDocument()
  })

  it("filters by relationship type", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    selectFilter("passport-relationship-filter", "attached")
    expect(querySkillCard("Docker")).toBeDefined()
    expect(querySkillCard("Python")).toBeUndefined()
    expect(screen.getByTestId("filter-result-count")).toHaveTextContent("1 of")
  })

  it("filters by evidence status", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    selectFilter("passport-status-filter", "Evidence observed")
    expect(querySkillCard("Docker")).toBeDefined() // Docker is "Evidence observed"
    expect(querySkillCard("Python")).toBeUndefined() // Python is "Demonstrated"
  })

  it("filters by evidence source", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    selectFilter("passport-source-filter", "Document Proof")
    expect(querySkillCard("Docker")).toBeDefined() // Docker proof is Document
    expect(querySkillCard("Python")).toBeUndefined() // Python proof is GitHub
  })

  it("shows removable active-filter chips and clears them", async () => {
    render(<PrivatePassportView />)
    await screen.findByTestId("passport-graph-explorer")

    selectFilter("passport-relationship-filter", "attached")
    const chip = screen.getByTestId("active-filter-chips")
    expect(within(chip).getByText(/Relationship: Attached/)).toBeInTheDocument()
    // Removing the chip restores the unfiltered map.
    fireEvent.click(within(chip).getAllByTestId("active-filter-chip").find((c) => c.getAttribute("data-filter") === "relationship")!)
    expect(querySkillCard("Python")).toBeDefined()
  })
})
