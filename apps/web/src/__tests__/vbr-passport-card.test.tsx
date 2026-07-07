/**
 * Verified Passport Card — frontend tests.
 *
 * Covers the compact recruiter/career-fair credential in both surfaces:
 *  - Private preview embedded at the top of the owner's Passport
 *    (Verified Passport Card Preview): identity, high-level ROLE-AREA chips
 *    (grouped from detailed skills), the integrated profile/QR scan area, the
 *    merged sharing controls, and the same-page role-chip deep-link into the
 *    Skills Evidence Map.
 *  - Public /card/[slug]: recruiter-safe compact card, integrated profile QR to
 *    the full Passport, slug-anchored role-chip links, and the safe not-found
 *    state.
 *
 * Safety guardrails asserted throughout: the compact card lists NO featured
 * projects and never leaks raw evidence, internal ids, file paths, private
 * routes, or numeric scores on either surface.
 */

import { render, screen, fireEvent, within } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { PrivatePassportView } from "../app/student/vbr/passport/PrivatePassportView"
import { PublicPassportCardView } from "../app/card/[slug]/PublicPassportCardView"
import type { PassportIdentity, PrivateWorkPassport, PublicWorkPassport, WorkPassportStatus } from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", async (importActual) => ({
  // Keep the real pure helpers (publicSafeAvatarUrl, …); only the network calls
  // are mocked.
  ...(await importActual<typeof import("@/lib/vbr-api")>()),
  getPrivateWorkPassport: vi.fn(),
  getWorkPassportStatus: vi.fn(),
  publishWorkPassport: vi.fn(),
  unpublishWorkPassport: vi.fn(),
  publishVBRProjectReport: vi.fn(),
  getPublicWorkPassportBySlug: vi.fn(),
}))

import {
  getPrivateWorkPassport,
  getWorkPassportStatus,
  getPublicWorkPassportBySlug,
} from "@/lib/vbr-api"

// ── Factories ────────────────────────────────────────────────────────────────

function makePrivatePassport(overrides: Partial<PrivateWorkPassport> = {}): PrivateWorkPassport {
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
        // top_skills link Python to the project so the role-area aggregation has
        // real skill→project evidence (the Data Science / Applied AI chip becomes
        // an evidence-backed role area, not just a card label).
        top_skills: [
          { skill: "Python", status: "Demonstrated", skill_slug: "python", supporting_proof_types: ["GitHub Proof"] },
        ],
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

/** A recruiter-safe identity payload (public by construction) for photo tests. */
function makeIdentity(overrides: Partial<PassportIdentity> = {}): PassportIdentity {
  return {
    display_name: "Jordan Rivera",
    headline: "Full-stack builder",
    program: "Computer Science",
    degree_level: "Masters",
    graduation_year: 2026,
    region: "US",
    education_summary: "Computer Science · Masters · Class of 2026",
    public_status: "Verified public passport",
    public_path: "/p/slug123",
    last_updated: null,
    evidence_source_summary: [],
    verification_label: "Verified",
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
    verification_note: "Evidence is described qualitatively — never as a number, percentage, or ranking.",
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(getPrivateWorkPassport).mockReset()
  vi.mocked(getWorkPassportStatus).mockReset()
  vi.mocked(getPublicWorkPassportBySlug).mockReset()
})

// ── Private preview ──────────────────────────────────────────────────────────

describe("Verified Passport Card preview (private)", () => {
  async function renderPrivate(overrides: Partial<PrivateWorkPassport> = {}) {
    const p = makePrivatePassport(overrides)
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
    render(<PrivatePassportView />)
    return screen.findByTestId("verified-passport-card-preview")
  }

  it("renders the compact card with identity and high-level role areas (no projects)", async () => {
    const preview = await renderPrivate()
    const card = within(preview).getByTestId("passport-card-private")
    expect(within(card).getByTestId("passport-card-name")).toHaveTextContent("Jordan Rivera")
    expect(within(card).getByTestId("passport-card-headline")).toHaveTextContent("Full-stack builder")

    // Detailed skills are grouped into recruiter-friendly ROLE areas, not dumped
    // as raw skills. Python (Demonstrated) → Data Science / Applied AI leads.
    const chips = within(card).getAllByTestId("passport-card-capability")
    expect(chips.length).toBeGreaterThan(0)
    expect(chips[0]).toHaveTextContent("Data Science / Applied AI")

    // The compact card never lists featured projects (they live below in the map).
    expect(within(card).queryByTestId("passport-card-project")).not.toBeInTheDocument()
    // Compact evidence line rather than a project list.
    expect(within(card).getByTestId("passport-card-evidence-line")).toHaveTextContent(/recruiter-safe/i)
  })

  it("clicking a role-area chip sets the ROLE AREA filter (aggregation), not just a raw skill", async () => {
    const preview = await renderPrivate()
    const chip = within(preview).getAllByTestId("passport-card-capability")[0]
    expect(chip).toHaveAttribute("data-label", "Data Science / Applied AI")
    fireEvent.click(chip)

    // The evidence map opens the role-level CAPABILITY view (aggregation across
    // the area's underlying skills/projects), never a single raw skill filter.
    const summary = screen.getByTestId("capability-summary")
    expect(summary).toHaveAttribute("data-capability", "Data Science / Applied AI")
    // The Role Area filter is what got selected — not the raw skill dropdown.
    expect(screen.getByTestId("passport-role-area-filter")).toHaveValue("data-science-applied-ai")
    expect(screen.getByTestId("passport-skill-filter")).toHaveValue("")
    // It aggregates the underlying evidence (Python → Data Science, via proj-1):
    // counts-based headline + qualitative "why".
    expect(within(summary).getByTestId("capability-summary-text")).toHaveTextContent(
      /Data Science \/ Applied AI is supported by \d+ connected skill/i,
    )
    // The "why" is the richer, fact-grounded narrative: purpose + the connected
    // project + role-relevant framing.
    const why = within(summary).getByTestId("capability-why")
    expect(why).toHaveTextContent(/Data Science \/ Applied AI is about using analysis/i)
    expect(why).toHaveTextContent(/role-relevant work/i)
  })

  it("shows the avatar-only profile (no scan QR) and a publish action while private", async () => {
    const preview = await renderPrivate({ is_published: false, public_slug: null })
    expect(within(preview).getByTestId("passport-card-avatar-only")).toBeInTheDocument()
    expect(within(preview).queryByTestId("passport-card-qr")).not.toBeInTheDocument()
    expect(within(preview).getByTestId("passport-card-preview-publish-hint")).toBeInTheDocument()
    expect(within(preview).getByTestId("publish-passport-button")).toBeInTheDocument()
    // No public copy/open links while private.
    expect(within(preview).queryByTestId("copy-passport-link-button")).not.toBeInTheDocument()
    expect(within(preview).queryByTestId("passport-card-open-card")).not.toBeInTheDocument()
  })

  it("integrates the scan QR into the profile area and shows share CTAs once published", async () => {
    const preview = await renderPrivate({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    // QR is layered into the profile area (initials overlay), not a standalone box.
    expect(within(preview).getByTestId("passport-card-qr")).toBeInTheDocument()
    expect(within(preview).getByTestId("passport-card-qr-overlay")).toBeInTheDocument()

    expect(within(preview).getByTestId("copy-passport-link-button")).toBeInTheDocument()
    const openPublic = within(preview).getByTestId("open-passport-link")
    expect(openPublic.getAttribute("href")).toContain("/p/slug123")
    const openCard = within(preview).getByTestId("passport-card-open-card")
    expect(openCard.getAttribute("href")).toContain("/card/slug123")
  })

  it("never leaks raw evidence, file paths, or numeric scores in the card", async () => {
    const preview = await renderPrivate()
    const card = within(preview).getByTestId("passport-card-private")
    const text = card.textContent ?? ""
    expect(text).not.toMatch(/octocat\/Hello-World/) // repo/internal identifiers
    expect(text).not.toMatch(/proj-1/) // internal project id
    expect(text).not.toMatch(/\/100|%|confidence|score/i) // numeric scoring
  })

  it("keeps high-level ROLE-AREA chips (not a raw skill dump)", async () => {
    const preview = await renderPrivate()
    const card = within(preview).getByTestId("passport-card-private")
    const labels = within(card).getAllByTestId("passport-card-capability").map((c) => c.textContent)
    // Grouped role areas, never the raw detailed skills ("Python" / "React").
    expect(labels.join(" ")).toMatch(/Data Science|Full-Stack|Software Engineering/)
    expect(labels.join(" ")).not.toMatch(/^Python$|^React$/)
  })

  it("falls back to safe initials when no profile image exists", async () => {
    const preview = await renderPrivate({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    // No avatar_url on the payload → initials, never a broken/empty <img>.
    expect(within(preview).getByTestId("passport-card-avatar")).toHaveTextContent("JR")
    expect(within(preview).queryByTestId("passport-card-profile-image")).not.toBeInTheDocument()
  })

  it("renders the profile photo at the centre of the scan area when a safe URL exists", async () => {
    const preview = await renderPrivate({
      is_published: true,
      public_slug: "slug123",
      public_path: "/p/slug123",
      identity: makeIdentity({ avatar_url: "https://cdn.example.com/u/jordan.jpg" }),
    })
    const img = within(preview).getByTestId("passport-card-profile-image") as HTMLImageElement
    expect(img.getAttribute("src")).toBe("https://cdn.example.com/u/jordan.jpg")
    // Photo replaces the initials overlay, and the scan QR still wraps it.
    expect(within(preview).queryByTestId("passport-card-avatar")).not.toBeInTheDocument()
    expect(within(preview).getByTestId("passport-card-qr")).toBeInTheDocument()
  })

  it("the scan QR encodes the public full Passport URL (never /card or a private route)", async () => {
    const preview = await renderPrivate({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    const qr = within(preview).getByTestId("passport-card-qr")
    const encoded = qr.getAttribute("data-qr-value") ?? ""
    expect(encoded).toContain("/p/slug123")
    expect(encoded).not.toContain("/card/")
    expect(encoded).not.toContain("/student/")
  })

  it("shows no profile-photo upload control in this branch (upload lives in the Passport Card branch)", async () => {
    // This Website Proof branch renders the safe avatar/initials only — never a
    // profile-photo upload/remove control or hidden file input.
    const preview = await renderPrivate()
    expect(within(preview).queryByTestId("passport-card-photo-control")).not.toBeInTheDocument()
    expect(within(preview).queryByTestId("passport-card-add-photo")).not.toBeInTheDocument()
    expect(within(preview).queryByTestId("passport-card-remove-photo")).not.toBeInTheDocument()
    expect(within(preview).queryByTestId("passport-card-photo-input")).not.toBeInTheDocument()
  })

  it("does not resurrect a duplicate Public Work Passport identity block", async () => {
    const preview = await renderPrivate({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    // Identity + sharing live once, on the card preview — no legacy second block.
    expect(screen.queryByTestId("passport-identity-header")).not.toBeInTheDocument()
    expect(within(preview).getAllByTestId("passport-sharing-controls")).toHaveLength(1)
  })
})

// ── Public card ──────────────────────────────────────────────────────────────

describe("Public Verified Passport Card (/card/[slug])", () => {
  it("renders a recruiter-safe compact card with identity and role areas (no projects)", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())
    render(<PublicPassportCardView slug="slug123" />)

    expect(await screen.findByTestId("public-passport-card")).toBeInTheDocument()
    const card = screen.getByTestId("passport-card-public")
    expect(within(card).getByTestId("passport-card-name")).toHaveTextContent("Jordan Rivera")
    expect(within(card).getAllByTestId("passport-card-capability").length).toBeGreaterThan(0)
    // No featured-project list on the compact card.
    expect(within(card).queryByTestId("passport-card-project")).not.toBeInTheDocument()

    // Safe footer note + full-passport CTA.
    expect(screen.getByTestId("public-card-footer-note")).toHaveTextContent(/Recruiter-safe summaries only/i)
    expect(screen.getByTestId("public-card-full-passport-cta")).toHaveAttribute("href", "/p/slug123")
  })

  it("integrates a QR into the profile area that opens the full Passport", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())
    render(<PublicPassportCardView slug="slug123" />)
    await screen.findByTestId("public-passport-card")
    expect(screen.getByTestId("passport-card-qr")).toBeInTheDocument()
  })

  it("role-area chips deep-link into the full public Passport by slug anchor", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())
    render(<PublicPassportCardView slug="slug123" />)
    await screen.findByTestId("public-passport-card")
    const chip = screen.getAllByTestId("passport-card-capability")[0]
    expect(chip.getAttribute("href")).toContain("/p/slug123#public-skill-")
  })

  it("never exposes a private/owner route or a raw report link on the compact card", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())
    render(<PublicPassportCardView slug="slug123" />)
    await screen.findByTestId("public-passport-card")
    const card = screen.getByTestId("passport-card-public")
    const text = card.textContent ?? ""
    // The compact card lists no projects, so it never fronts a report/owner route.
    expect(text).not.toMatch(/\/student\/vbr\/projects\//)
    expect(card.querySelector('a[href*="/vbr/report/"]')).toBeNull()
  })

  it("renders a public-safe profile photo when the public payload exposes one", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(
      makePublicPassport({ identity: makeIdentity({ avatar_url: "https://cdn.example.com/u/jordan.jpg" }) }),
    )
    render(<PublicPassportCardView slug="slug123" />)
    await screen.findByTestId("public-passport-card")
    const img = screen.getByTestId("passport-card-profile-image") as HTMLImageElement
    expect(img.getAttribute("src")).toBe("https://cdn.example.com/u/jordan.jpg")
  })

  it("never renders a signed/private storage URL — it falls back to initials", async () => {
    const signed =
      "https://proj.supabase.co/storage/v1/object/sign/private/avatars/jordan.jpg?token=eyJhbGciOiJI&X-Amz-Signature=abc"
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(
      makePublicPassport({ identity: makeIdentity({ avatar_url: signed }) }),
    )
    render(<PublicPassportCardView slug="slug123" />)
    const root = await screen.findByTestId("public-passport-card")
    // The unsafe URL is dropped: no <img>, safe initials instead, and the signed
    // token/signature never reaches the DOM (attributes included).
    expect(screen.queryByTestId("passport-card-profile-image")).not.toBeInTheDocument()
    expect(screen.getByTestId("passport-card-avatar")).toBeInTheDocument()
    expect(root.innerHTML).not.toContain("X-Amz-Signature")
    expect(root.innerHTML).not.toContain("/object/sign/")
    expect(root.innerHTML).not.toContain("token=")
  })

  it("never shows profile-photo upload controls on the public card", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(
      makePublicPassport({ identity: makeIdentity({ avatar_url: "https://cdn.example.com/u/jordan.jpg" }) }),
    )
    render(<PublicPassportCardView slug="slug123" />)
    await screen.findByTestId("public-passport-card")
    // The public surface renders the photo but exposes NO upload/remove/file input.
    expect(screen.queryByTestId("passport-card-add-photo")).not.toBeInTheDocument()
    expect(screen.queryByTestId("passport-card-remove-photo")).not.toBeInTheDocument()
    expect(screen.queryByTestId("passport-card-photo-input")).not.toBeInTheDocument()
    expect(screen.queryByTestId("passport-card-photo-control")).not.toBeInTheDocument()
  })

  it("renders a safe not-found state for an unpublished/unknown slug", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(null)
    render(<PublicPassportCardView slug="missing" />)
    expect(await screen.findByTestId("public-card-not-found")).toBeInTheDocument()
  })

  it("never leaks numeric scores or private routes on the public card", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())
    render(<PublicPassportCardView slug="slug123" />)
    const root = await screen.findByTestId("public-passport-card")
    const text = root.textContent ?? ""
    // Numeric-score patterns (a real leak) — the safe "no numeric scores"
    // disclaimer is fine, so match digits, not the word.
    expect(text).not.toMatch(/\d+\s*\/\s*100|\d+\s*%|confidence:\s*\d/i)
    expect(text).not.toMatch(/\/student\/vbr\//)
  })
})
