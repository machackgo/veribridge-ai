/**
 * Public Skill Report page (`/p/{slug}/skills/{skillSlug}`) — rendering tests.
 *
 * Covers: the recruiter-safe evidence argument (header / coverage / linked
 * proof chains / cited synthesis / unlinked bucket / limitations), honest
 * "not public" access labels, the safe not-found state, the recruiter
 * checklist + CTA, and the guardrails: no owner controls, no private routes,
 * no raw/private field text, no numeric scores.
 */

import { render, screen } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"

import { PublicSkillReportView } from "../app/p/[slug]/skills/[skillSlug]/PublicSkillReportView"
import type { PublicSkillReport } from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/vbr-api")>()),
  getPublicSkillReport: vi.fn(),
}))

import { getPublicSkillReport } from "@/lib/vbr-api"

function makeReport(overrides: Partial<PublicSkillReport> = {}): PublicSkillReport {
  return {
    skill: "Python",
    skill_slug: "python",
    status: "Demonstrated",
    category: "Programming Languages",
    synthesis_summary:
      "Python is supported by connected GitHub, website, and project defense evidence.",
    source_coverage: { github: true, website: true, document: false, defense: true, video: false },
    linked_proof_chains: [
      {
        chain_id: "chain_ab12cd34ef",
        project_title: "Skill Evidence Tracker",
        canonical_skill_name: "Python",
        chain_label: "Skill Evidence Tracker — connected proof",
        linked_evidence_ids: ["ev_github_a1b2c3d4e5f6"],
        source_types_present: ["github", "defense"],
        primary_source_type: "github",
        connection_reasons: ["Same project"],
        proof_strength_summary: { label: "Precise code plus self-explanation" },
        limitations: ["Not sole-authorship proof."],
        public_safe: true,
        evidence: [
          {
            evidence_id: "ev_github_a1b2c3d4e5f6",
            source_type: "github",
            source_label: "GitHub Proof",
            canonical_skill_name: "Python",
            project_title: "Skill Evidence Tracker",
            exact_location: "tracker/api.py · lines 10-42",
            safe_summary: "Implemented the evidence-collection endpoint in Python.",
            proof_strength: "precise_code",
            public_safe: true,
            limitations: [],
            public_url: "https://github.com/octocat/Hello-World/blob/main/api.py#L10-L42",
          },
          {
            evidence_id: "ev_defense_ff00aa11bb22",
            source_type: "defense",
            source_label: "Project Defense",
            canonical_skill_name: "Python",
            project_title: "Skill Evidence Tracker",
            exact_location: null,
            safe_summary: "The candidate explained the Python implementation in their own words.",
            proof_strength: "self_explanation",
            public_safe: true,
            limitations: ["Self-explanation evidence; strongest when combined with artifacts."],
            public_url: null,
          },
        ],
      },
    ],
    synthesis: [
      {
        chain_id: "chain_ab12cd34ef",
        canonical_skill_name: "Python",
        project_title: "Skill Evidence Tracker",
        claims: [
          {
            claim_id: "claim_0011aabbcc",
            claim: "The candidate implemented and explained Python API logic in this project.",
            supporting_evidence_ids: ["ev_github_a1b2c3d4e5f6"],
            why_connected: "The code lines and the defense answer describe the same endpoint.",
            limitations: [],
            qualitative_tier: "Corroborated",
            public_safe: true,
          },
        ],
        overall_summary: "Connected evidence corroborates the Python claim.",
        limitations: [],
        public_safe: true,
        source: "deterministic",
      },
    ],
    unlinked_supporting_evidence: {
      items: [
        {
          proof_type: "Document Proof",
          title: "Final report",
          safe_summary: "A supporting document matched to Python.",
          safe_location: "Page 4",
          corroborates: "GitHub implementation",
          limitation: "Documents support but do not independently prove implementation.",
        },
      ],
      count: 1,
      more_count: 2,
    },
    limitations: ["Evidence is shown with qualitative labels only."],
    generated_at: "2026-07-01T00:00:00Z",
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(getPublicSkillReport).mockReset()
})

describe("PublicSkillReportView", () => {
  it("renders the public-safe evidence argument for the skill", async () => {
    vi.mocked(getPublicSkillReport).mockResolvedValue(makeReport())

    render(<PublicSkillReportView slug="slug123" skillSlug="python" />)

    expect(await screen.findByTestId("public-skill-report")).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Python" })).toBeInTheDocument()
    expect(screen.getByText("Demonstrated")).toBeInTheDocument()
    expect(screen.getByTestId("public-skill-coverage")).toBeInTheDocument()
    expect(screen.getAllByTestId("public-skill-proof-chain")).toHaveLength(1)
    expect(screen.getAllByTestId("public-skill-evidence-item")).toHaveLength(2)
    expect(screen.getAllByTestId("public-skill-synthesis-claim")).toHaveLength(1)
    expect(screen.getAllByTestId("public-skill-unlinked-item")).toHaveLength(1)
    // The honest overflow note for the capped unlinked bucket.
    expect(screen.getByText(/\+2 more supporting proofs/)).toBeInTheDocument()
  })

  it("links public evidence and labels non-public evidence honestly", async () => {
    vi.mocked(getPublicSkillReport).mockResolvedValue(makeReport())

    render(<PublicSkillReportView slug="slug123" skillSlug="python" />)
    await screen.findByTestId("public-skill-report")

    const links = screen.getAllByTestId("public-skill-evidence-link")
    expect(links).toHaveLength(1)
    expect(links[0]).toHaveAttribute(
      "href",
      "https://github.com/octocat/Hello-World/blob/main/api.py#L10-L42",
    )
    // The defense evidence has no public artifact — honest label, no link.
    expect(screen.getByTestId("public-skill-evidence-private")).toHaveTextContent(
      "verified summary only",
    )
  })

  it("shows boolean coverage chips with present/missing state", async () => {
    vi.mocked(getPublicSkillReport).mockResolvedValue(makeReport())

    render(<PublicSkillReportView slug="slug123" skillSlug="python" />)
    await screen.findByTestId("public-skill-report")

    const items = screen.getAllByTestId("public-skill-coverage-item")
    const bySource = Object.fromEntries(
      items.map((el) => [el.getAttribute("data-source"), el.getAttribute("data-present")]),
    )
    expect(bySource["github"]).toBe("true")
    expect(bySource["document"]).toBe("false")
  })

  it("renders the recruiter checklist and CTA on the public report", async () => {
    vi.mocked(getPublicSkillReport).mockResolvedValue(makeReport())

    render(<PublicSkillReportView slug="slug123" skillSlug="python" />)
    await screen.findByTestId("public-skill-report")

    expect(screen.getByTestId("recruiter-review-checklist")).toBeInTheDocument()
    expect(screen.getByTestId("recruiter-cta")).toBeInTheDocument()
    expect(screen.getByTestId("recruiter-cta-request-vbr")).toHaveAttribute(
      "href",
      "/recruiters/request-vbr",
    )
    expect(
      screen.getByText("Want candidates to send proof-backed reports?"),
    ).toBeInTheDocument()
  })

  it("renders the safe not-found state for an unknown/unpublished report", async () => {
    vi.mocked(getPublicSkillReport).mockResolvedValue(null)

    render(<PublicSkillReportView slug="bad-slug" skillSlug="python" />)

    expect(await screen.findByTestId("public-skill-report-not-found")).toBeInTheDocument()
    expect(screen.queryByTestId("public-skill-report")).not.toBeInTheDocument()
    // The only escape hatch is the public passport route.
    const back = document.querySelector('a[href="/p/bad-slug"]')
    expect(back).toBeTruthy()
  })

  it("renders the honest empty state when nothing public-safe survived", async () => {
    vi.mocked(getPublicSkillReport).mockResolvedValue(
      makeReport({
        linked_proof_chains: [],
        synthesis: [],
        unlinked_supporting_evidence: { items: [], count: 0, more_count: 0 },
      }),
    )

    render(<PublicSkillReportView slug="slug123" skillSlug="python" />)
    await screen.findByTestId("public-skill-report")

    expect(screen.getByTestId("public-skill-no-chains")).toBeInTheDocument()
    expect(screen.getByTestId("public-skill-no-public-evidence")).toBeInTheDocument()
  })

  it("renders no owner controls and no private routes", async () => {
    vi.mocked(getPublicSkillReport).mockResolvedValue(makeReport())

    render(<PublicSkillReportView slug="slug123" skillSlug="python" />)
    await screen.findByTestId("public-skill-report")

    // No mutating owner controls of any kind on the public report.
    expect(screen.queryByTestId("publish-passport-button")).not.toBeInTheDocument()
    expect(screen.queryByTestId("unpublish-passport-button")).not.toBeInTheDocument()
    expect(screen.queryByTestId("reanalyze-button")).not.toBeInTheDocument()
    expect(screen.queryByTestId("attach-proof-button")).not.toBeInTheDocument()
    expect(screen.queryAllByRole("button")).toHaveLength(0)

    // Every link is public: never an owner/student route.
    for (const a of Array.from(document.querySelectorAll("a"))) {
      expect(a.getAttribute("href") ?? "").not.toMatch(/^\/student\//)
    }
  })

  it("never renders raw/private field text, storage paths, or numeric scores", async () => {
    vi.mocked(getPublicSkillReport).mockResolvedValue(makeReport())

    const { container } = render(<PublicSkillReportView slug="slug123" skillSlug="python" />)
    await screen.findByTestId("public-skill-report")

    const html = container.innerHTML
    for (const unsafe of [
      "storage_path",
      "signed_url",
      "access_token",
      "source_id",
      "uploads/",
      "?token=",
      ".webm",
      "transcript_segments",
    ]) {
      expect(html).not.toContain(unsafe)
    }
    const raw = document.body.textContent ?? ""
    expect(raw).not.toMatch(/\/100/)
    expect(raw).not.toMatch(/\btrust score\b/i)
    expect(raw).not.toMatch(/fully verified/i)
    expect(raw).not.toMatch(/\b\d{1,3}%/)
  })
})
