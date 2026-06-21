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
import { render, screen } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { PublicPassportView } from "../app/p/[slug]/PublicPassportView"
import LegacyPublicPassportPage from "../app/passport/[slug]/page"
import type { PublicWorkPassport } from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", () => ({
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
      { skill: "Python", status: "Demonstrated" },
      { skill: "React", status: "Partially demonstrated" },
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
    expect(screen.queryByRole("button")).not.toBeInTheDocument()
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
