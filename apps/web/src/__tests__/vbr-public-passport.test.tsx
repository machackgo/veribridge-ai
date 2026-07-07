/**
 * Public Verified Work Passport page — frontend rendering tests.
 *
 * Covers: candidate header / skills / featured projects, links to
 * /vbr/report/[token], the safe not-found empty state, the absence of any
 * edit controls, and the guardrails against raw/private fields, numeric
 * scores, /100 bars, score wording, percentages, and "fully verified".
 */

import { readFileSync } from "node:fs"
import { join } from "node:path"
import { render, screen, fireEvent } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { PublicPassportView } from "../app/p/[slug]/PublicPassportView"
import LegacyPublicPassportPage from "../app/passport/[slug]/page"
import type { PublicWorkPassport } from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/vbr-api")>()),
  getPublicWorkPassportBySlug: vi.fn(),
}))

vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
}))

import { redirect } from "next/navigation"

import { getPublicWorkPassportBySlug } from "@/lib/vbr-api"

function makePublicPassport(overrides: Partial<PublicWorkPassport> = {}): PublicWorkPassport {
  return {
    candidate_display_name: "Jordan Rivera",
    headline: "Full-stack builder",
    summary: "I ship and defend real projects.",
    top_skills: [
      { skill: "Python", status: "Demonstrated", evidence_sources: ["GitHub Proof"], projects: [], evidence_chips: [], limitations: [] },
      { skill: "React", status: "Partially demonstrated", evidence_sources: [], projects: [], evidence_chips: [], limitations: [] },
    ],
    featured_projects: [
      {
        project_title: "Skill Evidence Tracker",
        project_summary: "Tracks student skill evidence.",
        claimed_skills: ["Python", "React"],
        evidence_sources: ["GitHub Proof", "Project Defense", "VBR Report"],
        public_report_path: "/vbr/report/tok-abc",
        published_at: "2026-01-02T00:00:00Z",
      },
    ],
    evidence_source_counts: { "GitHub Proof": 1, "Project Defense": 1, "VBR Report": 1 },
    featured_project_count: 1,
    limitations: ["This passport links only to reports the candidate has chosen to make public."],
    published_at: "2026-01-02T00:00:00Z",
    generated_at: "2026-01-02T00:00:00Z",
    verification_note:
      "Evidence is described qualitatively — never as a number, percentage, or ranking.",
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(getPublicWorkPassportBySlug).mockReset()
})

describe("PublicPassportView", () => {
  it("renders candidate header, skills, featured projects, and report links", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())

    render(<PublicPassportView slug="slug123" />)

    expect(await screen.findByTestId("public-passport")).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Jordan Rivera" })).toBeInTheDocument()
    expect(screen.getByText("Full-stack builder")).toBeInTheDocument()
    expect(screen.getAllByTestId("public-passport-skill")).toHaveLength(2)
    expect(screen.getByTestId("public-passport-project")).toBeInTheDocument()

    const reportLink = screen.getByTestId("public-passport-report-link")
    expect(reportLink).toHaveAttribute("href", "/vbr/report/tok-abc")

    // CTA present and points at the recruiters page.
    expect(screen.getByTestId("public-passport-cta")).toBeInTheDocument()
  })

  it("expands a public skill to show only published-report drilldown detail", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(
      makePublicPassport({
        top_skills: [
          {
            skill: "Python",
            status: "Demonstrated",
            evidence_sources: ["GitHub Proof", "Project Defense"],
            projects: [
              {
                project_title: "Skill Evidence Tracker",
                evidence_sources: ["GitHub Proof"],
                public_report_path: "/vbr/report/tok-abc",
              },
            ],
            evidence_chips: [],
            limitations: [],
          },
        ],
      }),
    )

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    expect(screen.queryByTestId("public-skill-detail")).not.toBeInTheDocument()
    fireEvent.click(screen.getByTestId("public-skill-expand-toggle"))

    const detail = await screen.findByTestId("public-skill-detail")
    const ref = screen.getByTestId("public-skill-project-ref")
    expect(ref).toHaveTextContent("Skill Evidence Tracker")
    // The only outbound link is the public report path — never an internal id.
    expect(detail.querySelector("a")).toHaveAttribute("href", "/vbr/report/tok-abc")
    expect(detail.textContent).not.toContain("project_id")
  })

  it("shows published-report-backed evidence traces in the skill drilldown", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(
      makePublicPassport({
        top_skills: [
          {
            skill: "Python",
            status: "Demonstrated",
            evidence_sources: ["GitHub Proof"],
            projects: [
              { project_title: "Skill Evidence Tracker", evidence_sources: ["GitHub Proof"], public_report_path: "/vbr/report/tok-abc" },
            ],
            evidence_chips: [],
            limitations: [],
            evidence_traces: [
              {
                trace_id: "github-proof",
                source_type: "GitHub Proof",
                source_title: "octocat/Hello-World",
                skill_names: ["Python"],
                qualitative_status: "Supporting evidence",
                safe_summary: "Repository analyzed.",
                safe_detail: "Static analysis.",
                evidence_anchor: "github-proof",
                public_url: "https://github.com/octocat/Hello-World",
                public_url_label: "View public repository",
                timestamp: null,
                limitation: "Not sole authorship.",
                is_publicly_openable: true,
                private_evidence_note: null,
              },
            ],
          },
        ],
      }),
    )

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")
    fireEvent.click(screen.getByTestId("public-skill-expand-toggle"))

    const detail = await screen.findByTestId("public-skill-detail")
    expect(detail.querySelector('[data-testid="evidence-traceability"]')).toBeTruthy()
    expect(screen.getByTestId("evidence-trace-link")).toHaveAttribute("href", "https://github.com/octocat/Hello-World")
    expect(detail.textContent).not.toContain("project_id")
  })

  it("renders the not-found empty state safely", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(null)

    render(<PublicPassportView slug="bad-slug" />)

    expect(await screen.findByTestId("public-passport-not-found")).toBeInTheDocument()
    expect(screen.queryByTestId("public-passport")).not.toBeInTheDocument()
  })

  it("renders safe empty states when nothing is published", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(
      makePublicPassport({
        top_skills: [],
        featured_projects: [],
        evidence_source_counts: {},
        featured_project_count: 0,
        limitations: ["No public reports published yet.", "No featured projects yet."],
      }),
    )

    render(<PublicPassportView slug="slug123" />)

    expect(await screen.findByTestId("public-passport-no-projects")).toBeInTheDocument()
    expect(screen.getByTestId("public-passport-no-skills")).toBeInTheDocument()
  })

  it("renders no edit controls", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    expect(screen.queryByTestId("publish-passport-button")).not.toBeInTheDocument()
    expect(screen.queryByTestId("unpublish-passport-button")).not.toBeInTheDocument()
    expect(screen.queryByTestId("publish-report-button")).not.toBeInTheDocument()
    expect(screen.queryByTestId("copy-passport-link-button")).not.toBeInTheDocument()
    // The only buttons allowed on the public passport are read-only skill
    // expand/collapse toggles — never any mutating edit control.
    for (const btn of screen.queryAllByRole("button")) {
      expect(btn).toHaveAttribute("data-testid", "public-skill-expand-toggle")
    }
  })

  it("renders featured projects before the skills section (projects-first)", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    const projectsHeading = screen.getByRole("heading", { name: "Featured Verified Build Reports" })
    const skillsSection = screen.getByText("Top Evidence-Backed Skills")
    expect(
      projectsHeading.compareDocumentPosition(skillsSection) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  it("shows a safe proof-chain on featured projects, derived from evidence sources", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    expect(screen.getByTestId("public-project-proof-chain")).toBeInTheDocument()
    const items = screen.getAllByTestId("public-proof-chain-item")
    expect(items).toHaveLength(5)
    const bySource = Object.fromEntries(items.map((el) => [el.getAttribute("data-source"), el.getAttribute("data-present")]))
    // evidence_sources: GitHub Proof + Project Defense (+ VBR Report, not a chain step).
    expect(bySource["GitHub Proof"]).toBe("true")
    expect(bySource["Project Defense"]).toBe("true")
    expect(bySource["Website Proof"]).toBe("false")
    // Missing sources are stated honestly, with labels only.
    expect(screen.getByTestId("public-project-gaps")).toHaveTextContent("Website Proof")
  })

  it("renders the compact evidence-graph overview line", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    const overview = screen.getByTestId("public-passport-overview")
    expect(overview).toHaveTextContent("1 verified project")
    expect(overview).toHaveTextContent("2 evidence-backed skills")
  })

  it("links featured-project skill chips to the matching public skill section (Phase 2)", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(
      makePublicPassport({
        featured_projects: [
          {
            ...makePublicPassport().featured_projects[0],
            top_skills: [
              { skill: "Python", status: "Demonstrated", skill_slug: "python" },
              // Not in top_skills below → renders as a plain, unlinked chip.
              { skill: "GraphQL", status: "Supporting evidence", skill_slug: "graphql" },
            ],
            evidence_relationship_note:
              "This project demonstrates Python through GitHub code and Project Defense explanation.",
          },
        ],
      }),
    )

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    // Python exists in the Top Skills section → in-page anchor link.
    const links = screen.getAllByTestId("public-project-skill-link")
    expect(links).toHaveLength(1)
    expect(links[0]).toHaveAttribute("href", "#public-skill-python")
    // The anchor target exists on the skill row.
    expect(document.getElementById("public-skill-python")).toBeTruthy()
    // The relationship note renders with safe labels only.
    expect(screen.getByTestId("public-project-relationship-note")).toHaveTextContent(
      "This project demonstrates Python",
    )
  })

  it("shows the strongest project with a public report link in the skill drilldown (Phase 2)", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(
      makePublicPassport({
        top_skills: [
          {
            skill: "Python",
            status: "Demonstrated",
            evidence_sources: ["GitHub Proof"],
            projects: [
              {
                project_title: "Skill Evidence Tracker",
                evidence_sources: ["GitHub Proof"],
                public_report_path: "/vbr/report/tok-abc",
              },
            ],
            evidence_chips: [],
            strongest_project: {
              project_title: "Skill Evidence Tracker",
              skill_status: "Demonstrated",
              evidence_sources: ["GitHub Proof"],
              public_report_path: "/vbr/report/tok-abc",
            },
            limitations: [],
          },
        ],
      }),
    )

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")
    fireEvent.click(screen.getByTestId("public-skill-expand-toggle"))

    const strongest = await screen.findByTestId("public-skill-strongest-project")
    expect(strongest).toHaveTextContent("This skill is strongest in Skill Evidence Tracker")
    expect(screen.getByTestId("public-strongest-project-link")).toHaveAttribute(
      "href",
      "/vbr/report/tok-abc",
    )
  })

  it("public cross-links never point at private student routes (Phase 2)", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(
      makePublicPassport({
        featured_projects: [
          {
            ...makePublicPassport().featured_projects[0],
            top_skills: [{ skill: "Python", status: "Demonstrated", skill_slug: "python" }],
          },
        ],
      }),
    )

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    for (const a of Array.from(document.querySelectorAll("a"))) {
      expect(a.getAttribute("href") ?? "").not.toMatch(/^\/student\//)
    }
  })

  it("never renders raw/private fields, numeric scores, /100, percentages, or 'fully verified'", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    const raw = document.body.textContent ?? ""
    for (const unsafe of [
      "storage_path",
      "signed_url",
      "access_token",
      "public_token",
      "user_id",
      "vbr/sessions",
      "full_text",
      ".webm",
    ]) {
      expect(raw).not.toContain(unsafe)
    }
    expect(raw).not.toMatch(/\/100/)
    expect(raw).not.toMatch(/\bscore\b/i)
    expect(raw).not.toMatch(/trust score/i)
    expect(raw).not.toMatch(/fully verified/i)
    expect(raw).not.toMatch(/\b\d{1,3}%/)

    // Qualitative labels render instead.
    expect(screen.getByText("Demonstrated")).toBeInTheDocument()
    expect(screen.getByText("Partially demonstrated")).toBeInTheDocument()
  })
})

describe("Canonical public passport route", () => {
  it("legacy /passport/[slug] redirects to the canonical /p/[slug] route", async () => {
    vi.mocked(redirect).mockClear()

    await LegacyPublicPassportPage({ params: Promise.resolve({ slug: "abc123" }) })

    expect(redirect).toHaveBeenCalledWith("/p/abc123")
  })

  it("MVP surfaces link to /p/[slug], never the legacy /passport/[slug] route", () => {
    const surfaces = [
      "src/app/dashboard/passport/page.tsx",
      "components/passport/WorkPassportStatus.tsx",
      "components/recruiter-passport/SavedCandidates.tsx",
    ]

    for (const rel of surfaces) {
      const src = readFileSync(join(process.cwd(), rel), "utf8")
      // Links to the public passport now point at the canonical /p/<slug> route…
      expect(src).toMatch(/\/p\/\$\{/)
      // …and no longer build a legacy /passport/<slug> public link.
      expect(src).not.toMatch(/\/passport\/\$\{/)
    }
  })
})

// ── Proof Attachment Intelligence (Phase 3) — public safety ──────────────────

describe("PublicPassportView — Phase 3 public safety", () => {
  it("never renders private attachment suggestions or management UI", async () => {
    // Even if a malformed payload carried suggestion-shaped extras, the public
    // view has no code path that renders them.
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    expect(screen.queryByTestId("proof-attachment-intelligence")).not.toBeInTheDocument()
    expect(screen.queryByTestId("attachment-suggestion")).not.toBeInTheDocument()
    expect(screen.queryByTestId("suggested-attachments")).not.toBeInTheDocument()
    expect(screen.queryByTestId("project-suggested-attachments")).not.toBeInTheDocument()
    expect(screen.queryByTestId("project-next-action")).not.toBeInTheDocument()
    expect(screen.queryByTestId("skill-strengthening-action")).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain("Review and attach proof")
    expect(document.body.textContent).not.toContain("Likely match")
  })

  it("renders the safe unattached-evidence limitation when present", async () => {
    const limitation =
      "Additional proof evidence exists in the candidate's private vault that is not attached to the featured projects, so it is not shown here."
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(
      makePublicPassport({
        limitations: [
          "This passport links only to reports the candidate has chosen to make public.",
          limitation,
        ],
      }),
    )

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    expect(screen.getByText(limitation)).toBeInTheDocument()
    // No private ids, owner-only routes, or suggestion logic ride along.
    expect(document.body.innerHTML).not.toContain("/student/vbr/projects/")
    expect(document.body.textContent).not.toContain("suggestion")
  })
})

describe("PublicPassportView — Step 5 recruiter-ready publishing", () => {
  it("shows the exact safe empty state when no project reports are published", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(
      makePublicPassport({
        top_skills: [],
        featured_projects: [],
        evidence_source_counts: {},
        featured_project_count: 0,
      }),
    )

    render(<PublicPassportView slug="slug123" />)

    const empty = await screen.findByTestId("public-passport-no-projects")
    expect(empty).toHaveTextContent("No published project reports yet.")
    // No publish/report CTAs leak into the recruiter-facing empty state.
    expect(screen.queryByTestId("publish-report-button")).not.toBeInTheDocument()
    expect(screen.queryByTestId("view-report-preview-link")).not.toBeInTheDocument()
  })

  it("never renders unattached-proof counts or suggested-evidence cards", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    expect(screen.queryByTestId("attachment-suggestion")).not.toBeInTheDocument()
    expect(screen.queryByTestId("suggested-attachments")).not.toBeInTheDocument()
    expect(screen.queryByTestId("evidence-vault-section")).not.toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/unattached proof item/i)
    expect(document.body.textContent).not.toMatch(/suggested attachments/i)
  })
})

describe("PublicPassportView — Project Defense inspection (fail-closed)", () => {
  function withInspection(cardOverrides = {}) {
    const base = makePublicPassport()
    return makePublicPassport({
      featured_projects: [
        {
          ...base.featured_projects[0],
          project_defense_inspection: [
            {
              evidence_id_safe: "defense-inspection-1",
              question_text: null,
              question_kind: "skill_explanation",
              project_title: "Skill Evidence Tracker",
              mapped_skill: null,
              claim_type: "project_architecture",
              answer_purpose: "unknown_or_generic",
              evidence_role: "insufficient_or_generic",
              qualitative_status: "Withheld for privacy",
              safe_answer_summary: "Defense answer details are withheld because this session is not public-safe.",
              evidence_basis_chips: [],
              timestamp_label: null,
              clip_start_seconds: null,
              clip_end_seconds: null,
              clip_available: false,
              corroborates_github: false,
              corroborates_website: false,
              corroborates_document: false,
              corroboration_summary: "",
              what_this_demonstrates: "",
              limitation: "Project Defense is explanation evidence.",
              public_safe: false,
              withheld_reason: "Defense answer details are withheld because this session is not public-safe.",
              ...cardOverrides,
            },
          ],
        },
      ],
    })
  }

  it("renders a withheld placeholder for a not-public-safe defense card", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(withInspection())
    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    expect(screen.getByTestId("public-passport-project-defense-inspection")).toBeInTheDocument()
    expect(screen.getByTestId("pdi-withheld")).toHaveTextContent("withheld because this session is not public-safe")
    // No answer text / question / timestamp exposed in the withheld state.
    expect(screen.queryByTestId("pdi-question")).toBeNull()
    expect(screen.queryByTestId("pdi-answer-summary")).toBeNull()
    expect(screen.queryByTestId("pdi-timestamp")).toBeNull()
  })

  it("never exposes raw transcript, segments, or internal ids on the public passport", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(withInspection())
    const { container } = render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")
    const html = container.innerHTML
    for (const unsafe of ["transcript", "transcript_segments", "question_id", "storage_path", "signed_url", "vbr/sessions", "evidence_id_safe"]) {
      expect(html).not.toContain(unsafe)
    }
  })

  it("shows nothing extra when a featured project has no inspection cards", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())
    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")
    expect(screen.queryByTestId("public-passport-project-defense-inspection")).toBeNull()
  })
})
