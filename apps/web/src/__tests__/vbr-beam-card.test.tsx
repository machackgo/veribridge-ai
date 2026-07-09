/**
 * Premium Beam Card (`/beam`, Phase 1) — frontend tests.
 *
 * Covers the full-screen in-person handoff surface:
 *  - the card renders the candidate's REAL identity (name / headline / program),
 *    with the safe initials fallback when there is no photo and the honest
 *    fallback copy when there is no real name;
 *  - proof-source chips render ONLY the proof types that actually back the
 *    passport (present sources, canonical order);
 *  - the QR encodes EXACTLY the public Passport URL (`/p/{slug}`) — Phase 1
 *    payload — never a card/private/owner route;
 *  - Share Passport uses `navigator.share` when available and falls back to
 *    copying the link when not; Copy link shows the "Link copied" toast;
 *  - the honest publish-first state (no QR, no fabricated link) when the
 *    passport is unpublished;
 *  - the last-card offline fallback (cached public-safe model, visible offline
 *    note) when the network load fails;
 *  - safety guardrails: no fake wallet/NFC buttons, no raw evidence, internal
 *    ids, private routes, or numeric scores anywhere on the surface.
 */

import { render, screen, fireEvent, waitFor, within } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"

import { BeamView } from "../app/beam/BeamView"
import {
  BEAM_CARD_CACHE_KEY,
  buildBeamCardModel,
  loadBeamCardCache,
} from "@/lib/beam-card"
import { publicPassportUrl } from "@/lib/app-url"
import type {
  PassportIdentity,
  PassportSkillSummary,
  PrivateWorkPassport,
  WorkPassportStatus,
} from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", async (importActual) => ({
  // Keep the real pure helpers; only the network calls are mocked.
  ...(await importActual<typeof import("@/lib/vbr-api")>()),
  getPrivateWorkPassport: vi.fn(),
  getWorkPassportStatus: vi.fn(),
}))

import { getPrivateWorkPassport, getWorkPassportStatus } from "@/lib/vbr-api"

// ── Factories ────────────────────────────────────────────────────────────────

function skill(overrides: Partial<PassportSkillSummary> & { skill: string }): PassportSkillSummary {
  return {
    status: "Demonstrated",
    evidence_chip_count: 1,
    project_count: 1,
    evidence_sources: ["GitHub Proof"],
    projects: [],
    evidence_chips: [],
    notes: "",
    limitations: [],
    ...overrides,
  }
}

function identity(overrides: Partial<PassportIdentity> = {}): PassportIdentity {
  return {
    display_name: "Jordan Rivera",
    headline: "Full-stack builder",
    program: "B.Sc. Computer Science",
    degree_level: "Bachelor",
    graduation_year: 2026,
    region: "India",
    education_summary: "B.Sc. Computer Science · 2026",
    public_status: "Public passport live",
    public_path: "/p/slug123",
    last_updated: "2026-01-02T00:00:00Z",
    evidence_source_summary: ["GitHub Proof"],
    verification_label: "Verified Work Passport",
    ...overrides,
  }
}

function makePassport(overrides: Partial<PrivateWorkPassport> = {}): PrivateWorkPassport {
  return {
    candidate_display_name: "Jordan Rivera",
    headline: "Full-stack builder",
    summary: "I ship and defend real projects.",
    identity: identity(),
    is_published: true,
    public_slug: "slug123",
    public_path: "/p/slug123",
    published_at: "2026-01-02T00:00:00Z",
    skills: [
      skill({
        skill: "Python",
        status: "Demonstrated",
        evidence_sources: ["GitHub Proof", "Project Defense"],
        projects: [
          {
            project_title: "Skill Evidence Tracker",
            project_id: "proj-1",
            skill_status: "Demonstrated",
            evidence_sources: ["GitHub Proof"],
            supporting_proof_types: ["GitHub Proof"],
            report_is_public: true,
            public_report_path: "/r/tok123",
          },
        ],
      }),
      skill({
        skill: "React",
        status: "Partially demonstrated",
        evidence_sources: ["GitHub Proof"],
        projects: [
          {
            project_title: "Skill Evidence Tracker",
            project_id: "proj-1",
            skill_status: "Partially demonstrated",
            evidence_sources: ["GitHub Proof"],
            supporting_proof_types: ["GitHub Proof"],
            report_is_public: true,
            public_report_path: "/r/tok123",
          },
        ],
      }),
      skill({ skill: "Unassessed Skill", status: "Not assessed", evidence_sources: [] }),
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
        report: { is_public: true, public_token: "tok123", public_path: "/r/tok123", published_at: "2026-01-02T00:00:00Z" },
      },
      {
        project_id: "proj-2",
        project_title: "Unpublished Side Project",
        project_summary: "Not shared yet.",
        repo_full_name: null,
        claimed_skills: ["Python"],
        evidence_sources: ["GitHub Proof"],
        evidence_package: {
          github_proof_attached: true,
          documents_count: 0,
          website_proofs_count: 0,
          project_defense_completed: false,
          video_defense_recorded: false,
          video_evidence_chip_count: 0,
        },
        attempt_count: 1,
        report: { is_public: false, public_token: null, public_path: null, published_at: null },
      },
    ],
    evidence_source_counts: { "GitHub Proof": 2, "Document Proof": 1, "Project Defense": 1, "Video Evidence": 1 },
    project_count: 2,
    published_report_count: 1,
    limitations: [],
    generated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  }
}

const publishedStatus: WorkPassportStatus = {
  is_published: true,
  public_slug: "slug123",
  public_path: "/p/slug123",
  published_at: "2026-01-02T00:00:00Z",
  headline: "Full-stack builder",
  summary: "",
}

const unpublishedStatus: WorkPassportStatus = {
  is_published: false,
  public_slug: null,
  public_path: null,
  published_at: null,
  headline: "Full-stack builder",
  summary: "",
}

async function renderBeam(
  passport: PrivateWorkPassport = makePassport(),
  status: WorkPassportStatus = publishedStatus,
) {
  vi.mocked(getPrivateWorkPassport).mockResolvedValue(passport)
  vi.mocked(getWorkPassportStatus).mockResolvedValue(status)
  render(<BeamView />)
  return await screen.findByTestId("beam-card")
}

beforeEach(() => {
  vi.mocked(getPrivateWorkPassport).mockReset()
  vi.mocked(getWorkPassportStatus).mockReset()
  window.localStorage.clear()
  delete (navigator as { share?: unknown }).share
})

// ── Identity ─────────────────────────────────────────────────────────────────

describe("Beam Card identity", () => {
  it("renders the candidate's real name, headline, and program", async () => {
    const card = await renderBeam()
    expect(within(card).getByTestId("beam-card-name")).toHaveTextContent("Jordan Rivera")
    expect(within(card).getByTestId("beam-card-headline")).toHaveTextContent("Full-stack builder")
    expect(within(card).getByTestId("beam-card-program")).toHaveTextContent(/B\.Sc\. Computer Science/)
    expect(within(card).getByTestId("beam-card-program")).toHaveTextContent(/India/)
  })

  it("falls back to real-name initials when there is no profile photo", async () => {
    const card = await renderBeam()
    expect(within(card).queryByTestId("beam-card-profile-image")).not.toBeInTheDocument()
    expect(within(card).getByTestId("beam-card-avatar")).toHaveTextContent("JR")
  })

  it("renders a public-safe profile photo when one exists", async () => {
    const card = await renderBeam(
      makePassport({ identity: identity({ avatar_url: "https://cdn.example.com/photo.jpg" }) }),
    )
    expect(within(card).getByTestId("beam-card-profile-image")).toHaveAttribute(
      "src",
      "https://cdn.example.com/photo.jpg",
    )
    expect(within(card).queryByTestId("beam-card-avatar")).not.toBeInTheDocument()
  })

  it("never fabricates initials from the backend placeholder name", async () => {
    const card = await renderBeam(
      makePassport({
        candidate_display_name: "Verified candidate profile",
        identity: identity({ display_name: "Verified candidate profile" }),
      }),
    )
    expect(within(card).getByTestId("beam-card-name")).toHaveTextContent("Verified candidate profile")
    // Fallback star, never fake "VP" initials.
    expect(within(card).getByTestId("beam-card-avatar")).not.toHaveTextContent("VP")
  })
})

// ── Proof chips / skills / projects ──────────────────────────────────────────

describe("Beam Card proof summary", () => {
  it("renders proof chips ONLY for proof sources that actually exist", async () => {
    const card = await renderBeam()
    const chips = within(card).getAllByTestId("beam-card-proof-chip")
    const labels = chips.map((c) => c.getAttribute("data-label"))
    expect(labels).toEqual(["GitHub Proof", "Document Proof", "Project Defense", "Video Evidence"])
    // Website Proof has zero evidence in the fixture — it must not appear.
    expect(labels).not.toContain("Website Proof")
  })

  it("shows top proof-backed skills and excludes 'Not assessed'", async () => {
    const card = await renderBeam()
    const skills = within(card).getAllByTestId("beam-card-skill")
    const names = skills.map((s) => s.getAttribute("data-label"))
    expect(names).toContain("Python")
    expect(names).toContain("React")
    expect(names).not.toContain("Unassessed Skill")
  })

  it("lists ONLY projects with a published public report as verified projects", async () => {
    const card = await renderBeam()
    const projects = within(card).getAllByTestId("beam-card-project")
    expect(projects.map((p) => p.textContent)).toEqual(["✓Skill Evidence Tracker"])
    expect(card.textContent).not.toContain("Unpublished Side Project")
  })

  it("shows the honest empty state when no project report is published", async () => {
    const passport = makePassport()
    passport.projects = passport.projects.map((p) => ({
      ...p,
      report: { is_public: false, public_token: null, public_path: null, published_at: null },
    }))
    const card = await renderBeam(passport)
    expect(within(card).getByTestId("beam-card-projects-empty")).toHaveTextContent(
      "Verified projects coming soon",
    )
  })
})

// ── QR + link (Phase 1 payload) ──────────────────────────────────────────────

describe("Beam Card QR", () => {
  it("encodes EXACTLY the public Passport URL — never a card/private route", async () => {
    const card = await renderBeam()
    const qr = within(card).getByTestId("beam-card-qr")
    const encoded = qr.getAttribute("data-qr-value") ?? ""
    expect(encoded).toBe(publicPassportUrl("slug123"))
    expect(encoded).toContain("/p/slug123")
    expect(encoded).not.toContain("/card/")
    expect(encoded).not.toContain("/student/")
    expect(encoded).not.toContain("/beam")
  })

  it("shows the scan caption, visible link, no-login note, and trust line", async () => {
    const card = await renderBeam()
    expect(within(card).getByTestId("beam-card-qr-caption")).toHaveTextContent(
      "Scan to open the live public Passport",
    )
    expect(within(card).getByTestId("beam-card-link")).toHaveTextContent("/p/slug123")
    expect(within(card).getByTestId("beam-card-no-login")).toHaveTextContent("No login required")
    expect(within(card).getByTestId("beam-card-trust-line")).toHaveTextContent(
      "Public-safe proof summary — private evidence protected",
    )
  })
})

// ── Actions ──────────────────────────────────────────────────────────────────

describe("Beam actions", () => {
  it("copies the public link and shows the 'Link copied' toast", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    await renderBeam()
    fireEvent.click(screen.getByTestId("beam-copy"))
    await waitFor(() => expect(writeText).toHaveBeenCalled())
    expect(writeText.mock.calls[0][0]).toBe(publicPassportUrl("slug123"))
    expect(await screen.findByTestId("beam-copy-toast")).toHaveTextContent("Link copied")
  })

  it("Share Passport uses navigator.share when available — with the public URL only", async () => {
    const share = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { share })
    await renderBeam()
    fireEvent.click(screen.getByTestId("beam-share"))
    await waitFor(() => expect(share).toHaveBeenCalled())
    expect(share.mock.calls[0][0].url).toBe(publicPassportUrl("slug123"))
    expect(share.mock.calls[0][0].url).not.toContain("/student/")
  })

  it("Share Passport falls back to copying when navigator.share is unavailable", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    await renderBeam()
    fireEvent.click(screen.getByTestId("beam-share"))
    await waitFor(() => expect(writeText).toHaveBeenCalled())
    expect(await screen.findByTestId("beam-share-note")).toHaveTextContent(/link copied instead/i)
  })

  it("Open public Passport links to the public URL in a new tab", async () => {
    await renderBeam()
    const open = screen.getByTestId("beam-open-public")
    expect(open.getAttribute("href")).toBe(publicPassportUrl("slug123"))
    expect(open.getAttribute("target")).toBe("_blank")
  })
})

// ── Publish-first state ──────────────────────────────────────────────────────

describe("Beam publish-first state", () => {
  it("shows an honest publish-first state with NO QR and NO fabricated link", async () => {
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(
      makePassport({ is_published: false, public_slug: null, public_path: null }),
    )
    vi.mocked(getWorkPassportStatus).mockResolvedValue(unpublishedStatus)
    render(<BeamView />)
    const state = await screen.findByTestId("beam-publish-first")
    expect(state).toHaveTextContent(/Publish your Passport/i)
    expect(screen.queryByTestId("beam-card")).not.toBeInTheDocument()
    expect(screen.queryByTestId("beam-card-qr")).not.toBeInTheDocument()
    expect(screen.queryByTestId("beam-share")).not.toBeInTheDocument()
    expect(screen.getByTestId("beam-open-passport").getAttribute("href")).toBe("/student/vbr/passport")
  })
})

// ── Offline / last-card fallback ─────────────────────────────────────────────

describe("Beam offline fallback", () => {
  it("caches the published card on a successful load", async () => {
    await renderBeam()
    await waitFor(() => expect(window.localStorage.getItem(BEAM_CARD_CACHE_KEY)).toBeTruthy())
    const cached = loadBeamCardCache()
    expect(cached?.name).toBe("Jordan Rivera")
    expect(cached?.publicPassportUrl).toBe(publicPassportUrl("slug123"))
  })

  it("renders the last saved card with an offline note when the load fails", async () => {
    // Seed the cache exactly as a previous successful visit would have.
    const model = buildBeamCardModel(makePassport(), publishedStatus)
    window.localStorage.setItem(BEAM_CARD_CACHE_KEY, JSON.stringify(model))

    vi.mocked(getPrivateWorkPassport).mockRejectedValue(new Error("network down"))
    vi.mocked(getWorkPassportStatus).mockRejectedValue(new Error("network down"))
    render(<BeamView />)

    const card = await screen.findByTestId("beam-card")
    expect(screen.getByTestId("beam-offline-note")).toHaveTextContent(/offline copy/i)
    expect(within(card).getByTestId("beam-card-name")).toHaveTextContent("Jordan Rivera")
    expect(within(card).getByTestId("beam-card-qr").getAttribute("data-qr-value")).toBe(
      publicPassportUrl("slug123"),
    )
  })

  it("shows the error state (not a fabricated card) when the load fails with no cache", async () => {
    vi.mocked(getPrivateWorkPassport).mockRejectedValue(new Error("network down"))
    vi.mocked(getWorkPassportStatus).mockRejectedValue(new Error("network down"))
    render(<BeamView />)
    expect(await screen.findByTestId("beam-error")).toBeInTheDocument()
    expect(screen.queryByTestId("beam-card")).not.toBeInTheDocument()
  })

  it("rejects a tampered cache instead of rendering unsafe values", () => {
    window.localStorage.setItem(
      BEAM_CARD_CACHE_KEY,
      JSON.stringify({
        name: "Jordan Rivera",
        slug: "slug123",
        publicPassportUrl: "https://app.example.com/p/slug123",
        profileImageUrl: "https://cdn.example.com/photo.jpg?token=SECRET",
        proofSources: ["GitHub Proof", "Fake Proof"],
        isPublished: true,
      }),
    )
    const cached = loadBeamCardCache()
    // Signed/tokenized URL re-sanitized away; unknown proof labels dropped.
    expect(cached?.profileImageUrl).toBeNull()
    expect(cached?.proofSources).toEqual(["GitHub Proof"])
  })

  it("returns null for a cache without a real public Passport URL", () => {
    window.localStorage.setItem(
      BEAM_CARD_CACHE_KEY,
      JSON.stringify({ slug: "slug123", publicPassportUrl: "https://evil.example.com/steal" }),
    )
    expect(loadBeamCardCache()).toBeNull()
  })
})

// ── Safety guardrails ────────────────────────────────────────────────────────

describe("Beam safety", () => {
  it("renders NO fake wallet / NFC / proximity features", async () => {
    await renderBeam()
    const text = document.body.textContent ?? ""
    expect(text).not.toMatch(/apple wallet|google wallet|add to wallet|wallet pass/i)
    expect(text).not.toMatch(/NFC|tap[- ]to[- ]phone|AirDrop|Bluetooth|nearby (device|share)/i)
    expect(screen.queryByTestId("beam-wallet-button")).not.toBeInTheDocument()
  })

  it("never leaks raw evidence, internal ids, private routes, or scores", async () => {
    const card = await renderBeam()
    const text = card.textContent ?? ""
    expect(text).not.toMatch(/proj-1|proj-2/) // internal project ids
    expect(text).not.toMatch(/octocat\/Hello-World/) // repo identifiers
    expect(text).not.toMatch(/\/student\//) // owner-only routes
    expect(text).not.toMatch(/tok123/) // report tokens
    expect(text).not.toMatch(/\/100|%|confidence|score/i) // numeric scoring
    expect(text).not.toMatch(/transcript|signed|storage/i) // raw evidence fields
  })

  it("shows exactly ONE trust mark on the card face", async () => {
    const card = await renderBeam()
    expect(within(card).getAllByTestId("beam-card-verified-pill")).toHaveLength(1)
    // No invented certification / expert language anywhere on the card.
    expect(card.textContent).not.toMatch(/certified|expert badge|top 1%/i)
  })
})

// ── Model unit behaviour ─────────────────────────────────────────────────────

describe("buildBeamCardModel", () => {
  it("keeps unpublished passports link-free", () => {
    const model = buildBeamCardModel(
      makePassport({ is_published: false, public_slug: null, public_path: null }),
      unpublishedStatus,
    )
    expect(model.isPublished).toBe(false)
    expect(model.publicPassportUrl).toBeNull()
    expect(model.slug).toBeNull()
  })

  it("orders top skills strongest-first with qualitative labels only", () => {
    const model = buildBeamCardModel(makePassport(), publishedStatus)
    expect(model.topSkills[0]).toEqual({ name: "Python", status: "Demonstrated" })
    expect(model.topSkills.map((s) => s.name)).not.toContain("Unassessed Skill")
  })
})
