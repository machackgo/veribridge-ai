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
    // Outbound links are public routes only: the published report path and the
    // public skill report on the same slug — never an internal id.
    expect(ref.querySelector("a")).toHaveAttribute("href", "/vbr/report/tok-abc")
    expect(detail.querySelector('[data-testid="public-skill-report-link"]')).toHaveAttribute(
      "href",
      "/p/slug123/skills/python",
    )
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
    // The only buttons allowed on the public passport are read-only
    // expand/collapse disclosure toggles — never any mutating edit control.
    const readOnlyToggles = new Set([
      "public-skill-expand-toggle",
      "public-project-detail-toggle",
      "public-passport-methodology-toggle",
      "public-skills-show-all",
    ])
    for (const btn of screen.queryAllByRole("button")) {
      expect(readOnlyToggles.has(btn.getAttribute("data-testid") ?? "")).toBe(true)
    }
  })

  it("renders featured projects before the skills section (projects-first)", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    const projectsHeading = screen.getByRole("heading", { name: "Featured projects" })
    const skillsSection = screen.getByRole("heading", { name: "Top evidence-backed skills" })
    expect(
      projectsHeading.compareDocumentPosition(skillsSection) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  it("shows a safe proof-chain on featured projects, derived from evidence sources", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    // Proof-chain completeness is progressive disclosure: opened explicitly.
    fireEvent.click(screen.getByTestId("public-project-detail-toggle"))

    expect(screen.getByTestId("public-project-proof-chain")).toBeInTheDocument()
    const items = screen.getAllByTestId("public-proof-chain-item")
    expect(items).toHaveLength(5)
    const bySource = Object.fromEntries(items.map((el) => [el.getAttribute("data-source"), el.getAttribute("data-present")]))
    // evidence_sources: GitHub Proof + Project Defense (+ VBR Report, not a chain step).
    expect(bySource["GitHub Proof"]).toBe("true")
    expect(bySource["Project Defense"]).toBe("true")
    expect(bySource["Website Proof"]).toBe("false")
    // Missing sources are stated honestly, with labels only.
    expect(screen.getByTestId("public-project-gaps")).toHaveTextContent("Website")
  })

  it("renders the compact evidence coverage summary chips", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    const overview = screen.getByTestId("public-passport-overview")
    expect(overview).toHaveTextContent("GitHub · 1")
    expect(overview).toHaveTextContent("Project Defense · 1")
    expect(screen.getAllByTestId("public-evidence-source-count").length).toBeGreaterThan(0)
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
    // The relationship note renders (progressive disclosure) with safe labels only.
    fireEvent.click(screen.getByTestId("public-project-detail-toggle"))
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
    expect(strongest).toHaveTextContent("Strongest in Skill Evidence Tracker")
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

    // Qualitative tiers render instead ("Demonstrated" / "Supported").
    expect(screen.getAllByText("Demonstrated").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Supported").length).toBeGreaterThan(0)
    // The exact backend label stays available inside the expanded detail —
    // the tier is presentation grouping, never an upgrade.
    fireEvent.click(screen.getAllByTestId("public-skill-expand-toggle")[1])
    expect(screen.getByText("Partially demonstrated")).toBeInTheDocument()
  })
})

// ── Candidate identity hero (consented Passport Profile) ─────────────────────

describe("PublicPassportView — candidate identity hero", () => {
  const FULL_IDENTITY = {
    display_name: "Ada Lovelace",
    headline: "AI Engineer | M.S. in Artificial Intelligence",
    program: null,
    degree_level: null,
    graduation_year: 2027,
    region: null,
    education_summary: "",
    public_status: "Verified Work Passport",
    public_path: null,
    last_updated: "2026-01-02T00:00:00Z",
    evidence_source_summary: [],
    verification_label: "Verified Work Passport",
    avatar_url: "https://cdn.example.com/avatars/ada.png",
    bio: "I build evidence-backed AI products.",
    institution: "Worcester Polytechnic Institute",
    degree: "M.S. in Artificial Intelligence",
    location: "Worcester, Massachusetts",
    availability_label: "Seeking internship",
    github_url: "https://github.com/ada",
    linkedin_url: "https://www.linkedin.com/in/ada",
    portfolio_url: "https://ada.dev",
    role_areas: ["AI/ML"],
    work_authorization_note: null,
    has_custom_profile: true,
  }

  it("renders the full identity hero: photo, name, headline, education, links, availability", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(
      makePublicPassport({ identity: FULL_IDENTITY }),
    )

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    const hero = screen.getByTestId("public-passport-hero")
    expect(screen.getByTestId("passport-identity-name")).toHaveTextContent("Ada Lovelace")
    expect(screen.getByTestId("public-hero-headline")).toHaveTextContent(
      "AI Engineer | M.S. in Artificial Intelligence",
    )
    expect(screen.getByTestId("public-hero-education")).toHaveTextContent(
      "M.S. in Artificial Intelligence · Worcester Polytechnic Institute",
    )
    expect(hero).toHaveTextContent("Expected 2027 · Worcester, Massachusetts")
    expect(screen.getByTestId("public-hero-availability")).toHaveTextContent("Seeking internship")
    expect(hero.querySelector("img")).toHaveAttribute(
      "src",
      "https://cdn.example.com/avatars/ada.png",
    )
    const links = screen.getByTestId("public-hero-links")
    const hrefs = Array.from(links.querySelectorAll("a")).map((a) => a.getAttribute("href"))
    expect(hrefs).toEqual([
      "https://github.com/ada",
      "https://www.linkedin.com/in/ada",
      "https://ada.dev",
    ])
    // The candidate summary uses the student's own bio.
    expect(screen.getByTestId("public-passport-summary")).toHaveTextContent(
      "I build evidence-backed AI products.",
    )
  })

  it("omits empty identity fields cleanly — no fake placeholders, no 'Not provided'", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(
      makePublicPassport({
        identity: {
          ...FULL_IDENTITY,
          avatar_url: null,
          bio: null,
          institution: null,
          degree: null,
          graduation_year: null,
          location: null,
          availability_label: null,
          github_url: null,
          linkedin_url: null,
          portfolio_url: null,
          work_authorization_note: null,
        },
      }),
    )

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    expect(screen.queryByTestId("public-hero-education")).not.toBeInTheDocument()
    expect(screen.queryByTestId("public-hero-links")).not.toBeInTheDocument()
    expect(screen.queryByTestId("public-hero-availability")).not.toBeInTheDocument()
    expect(screen.queryByTestId("public-hero-work-auth")).not.toBeInTheDocument()
    const raw = document.body.textContent ?? ""
    expect(raw).not.toMatch(/not provided/i)
    expect(raw).not.toMatch(/unknown/i)
    // Name still renders; photo falls back to initials (no broken <img>).
    expect(screen.getByTestId("passport-identity-name")).toHaveTextContent("Ada Lovelace")
    expect(screen.getByTestId("public-passport-hero").querySelector("img")).toBeNull()
  })

  it("shows the work-authorization badge only when the note is present (opt-in)", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(
      makePublicPassport({
        identity: { ...FULL_IDENTITY, work_authorization_note: "Authorized to work in the US" },
      }),
    )

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    expect(screen.getByTestId("public-hero-work-auth")).toHaveTextContent(
      "Authorized to work in the US",
    )
  })

  it("never renders an unsafe avatar URL (signed/tokenized) — falls back to initials", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(
      makePublicPassport({
        identity: {
          ...FULL_IDENTITY,
          avatar_url: "https://cdn.example.com/avatars/ada.png?token=secret123",
        },
      }),
    )

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    expect(screen.getByTestId("public-passport-hero").querySelector("img")).toBeNull()
    expect(document.body.innerHTML).not.toContain("token=secret123")
  })

  it("falls back to the placeholder identity when no profile exists (legacy payloads)", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(
      makePublicPassport({ candidate_display_name: null, identity: undefined }),
    )

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    expect(screen.getByTestId("passport-identity-name")).toHaveTextContent(
      "Verified candidate profile",
    )
  })
})

// ── Recruiter link-review MVP ─────────────────────────────────────────────────

describe("PublicPassportView — recruiter link-review MVP", () => {
  it("renders the recruiter trust framing with the honest non-certification line", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    // The full trust framing sits behind "Learn how verification works" —
    // available, never dominating the primary view.
    fireEvent.click(screen.getByTestId("public-passport-methodology-toggle"))
    const framing = screen.getByTestId("recruiter-trust-framing")
    expect(framing).toHaveTextContent(
      "This Passport summarizes public-safe proof submitted by the candidate.",
    )
    expect(framing).toHaveTextContent("not an employment certification or background check")
    expect(framing).toHaveTextContent(
      "Inspect the linked evidence before making hiring decisions.",
    )
  })

  it("renders the recruiter review checklist", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    fireEvent.click(screen.getByTestId("public-passport-methodology-toggle"))
    const checklist = screen.getByTestId("recruiter-review-checklist")
    expect(checklist).toHaveTextContent("GitHub / code evidence")
    expect(checklist).toHaveTextContent("website / runtime evidence")
    expect(checklist).toHaveTextContent("project defense explanation")
    expect(checklist).toHaveTextContent("Review the limitations")
  })

  it("links top skills to their public skill report on the same slug", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    // Each skill row's expanded detail links to its public skill report.
    for (const toggle of screen.getAllByTestId("public-skill-expand-toggle")) {
      fireEvent.click(toggle)
    }
    const links = await screen.findAllByTestId("public-skill-report-link")
    const hrefs = links.map((a) => a.getAttribute("href"))
    expect(hrefs).toContain("/p/slug123/skills/python")
    expect(hrefs).toContain("/p/slug123/skills/react")
  })

  it("shows the recruiter CTA with the exact copy and request-vbr link", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())

    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")

    const cta = screen.getByTestId("recruiter-cta")
    expect(cta).toHaveTextContent("Want candidates to send proof-backed reports?")
    expect(cta).toHaveTextContent(
      "Ask applicants to generate a VeriBridge Verified Build Report for one project.",
    )
    expect(screen.getByTestId("recruiter-cta-request-vbr")).toHaveAttribute(
      "href",
      "/recruiters/request-vbr",
    )
    expect(screen.getByTestId("recruiter-cta-request-vbr")).toHaveTextContent(
      "Request a VBR from your candidates",
    )
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

    // Limitations live inside the collapsed verification-details section.
    fireEvent.click(screen.getByTestId("public-passport-methodology-toggle"))
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

describe("PublicPassportView — Document Proof trace safety", () => {
  function documentTracePassport(): PublicWorkPassport {
    return makePublicPassport({
      top_skills: [
        {
          skill: "Machine Learning",
          status: "Demonstrated",
          evidence_sources: ["Document Proof"],
          projects: [
            { project_title: "Housing Price Predictor", evidence_sources: ["Document Proof"], public_report_path: "/vbr/report/tok-abc" },
          ],
          evidence_chips: [],
          limitations: [],
          evidence_traces: [
            {
              trace_id: "document-1-machine-learning",
              source_type: "Document Proof",
              source_title: "Final Year Project Report",
              skill_names: ["Machine Learning"],
              qualitative_status: "Supporting evidence",
              safe_summary: "A supporting document the analyzer matched to Machine Learning on page 4.",
              safe_detail: "A safe excerpt/page is shown for recruiters rather than the raw file.",
              evidence_anchor: "",
              location_type: "document_page",
              location_label: "Page 4",
              location_detail: "Page 4 · Model Architecture",
              page_number: 4,
              citation: "Model Architecture",
              // Public projection strips the raw excerpt — no snippet on a public trace.
              snippet: null,
              public_url: null,
              public_url_label: null,
              timestamp: null,
              limitation: "Document evidence supports but does not independently prove implementation or authorship.",
              is_publicly_openable: false,
              private_evidence_note: "Private document; only a safe citation is shown.",
            },
          ],
        },
      ],
    })
  }

  it("S. public document trace exposes no raw snippet, storage path, or internal id", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(documentTracePassport())
    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")
    fireEvent.click(screen.getByTestId("public-skill-expand-toggle"))
    const detail = await screen.findByTestId("public-skill-detail")

    // No raw excerpt is rendered for a public document trace.
    expect(detail.querySelector('[data-testid="evidence-trace-snippet"]')).toBeNull()
    const html = detail.innerHTML
    expect(html).not.toContain("uploads/")
    expect(html).not.toContain("?token=")
    expect(html).not.toContain("document_id")
    expect(html).not.toContain("source_id")
    expect(html).not.toContain("optional_evidence_submissions")
  })

  it("T. public document trace shows the safe locator and limitation", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(documentTracePassport())
    render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")
    fireEvent.click(screen.getByTestId("public-skill-expand-toggle"))
    const detail = await screen.findByTestId("public-skill-detail")

    expect(detail.querySelector('[data-testid="evidence-trace-page"]')?.textContent).toContain("Page 4")
    expect(detail.querySelector('[data-testid="evidence-trace-citation"]')?.textContent).toContain("Model Architecture")
    expect(detail.textContent).toContain("does not independently prove implementation")
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

    // Defense inspection cards live inside the project's evidence detail.
    fireEvent.click(screen.getByTestId("public-project-detail-toggle"))
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

  it("a public-safe card fails closed: no recording link and no verbatim excerpt", async () => {
    // The backend public projection sends the playback URL and the verbatim
    // excerpt as null even on a public-safe card — the recruiter sees only the
    // derived summary + the "private" notes.
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(
      withInspection({
        question_text: "How does your model make predictions?",
        mapped_skill: "Python",
        qualitative_status: "Explained with evidence",
        safe_answer_summary: "The candidate explained this Python claim.",
        public_safe: true,
        withheld_reason: null,
        video_available: false,
        video_playback_url: null,
        clip_playback_url: null,
        transcript_excerpt_available: false,
        safe_transcript_excerpt: null,
        transcript_access_note: "Defense recording and transcript are private. Recruiters see only verified summary and timestamp labels.",
        recording_access_note: "Defense recording and transcript are private. Recruiters see only verified summary and timestamp labels.",
      }),
    )
    const { container } = render(<PublicPassportView slug="slug123" />)
    await screen.findByTestId("public-passport")
    fireEvent.click(screen.getByTestId("public-project-detail-toggle"))

    // No <video> element and no verbatim transcript excerpt on the recruiter view.
    expect(screen.queryByTestId("pdi-video")).toBeNull()
    expect(screen.queryByTestId("pdi-transcript-excerpt")).toBeNull()
    // Both fall back to the fixed "private" note.
    expect(screen.getByTestId("pdi-recording-note")).toHaveTextContent(/private/i)
    expect(screen.getByTestId("pdi-transcript-note")).toHaveTextContent(/private/i)
    // No storage path / signed URL / segments leak.
    const html = container.innerHTML
    for (const unsafe of ["transcript_segments", "storage_path", "signed_url", "vbr/sessions"]) {
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
