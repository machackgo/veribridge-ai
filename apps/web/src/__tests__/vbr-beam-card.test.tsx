/**
 * Premium Beam Card (`/beam`, Phase 1 + Phase 2 short link) — frontend tests.
 *
 * Covers the full-screen in-person handoff surface:
 *  - the card renders the candidate's REAL identity (name / headline / program),
 *    with the safe initials fallback when there is no photo and the honest
 *    fallback copy when there is no real name;
 *  - proof-source chips render ONLY the proof types that actually back the
 *    passport (present sources, canonical order);
 *  - Phase 2 payload: the QR / copy / share carry EXACTLY the revocable short
 *    link (`{app}/b/{code}`) — never the direct public URL when a Beam link
 *    exists, and never a card/private/owner route;
 *  - honest fallback: when the Beam link service fails, the card falls back to
 *    the direct public Passport URL with a visible note and a retry action;
 *  - Share Passport uses `navigator.share` when available and falls back to
 *    copying the link when not; Copy link shows the "Link copied" toast;
 *  - the honest publish-first state (no QR, no fabricated link) when the
 *    passport is unpublished;
 *  - the last-card offline fallback (cached public-safe model + cached short
 *    link, visible offline note) when the network load fails;
 *  - safety guardrails: no fake wallet/NFC buttons, no raw evidence, internal
 *    ids, private routes, or numeric scores anywhere on the surface; no
 *    hardcoded localhost in production URL generation.
 */

import { render, screen, fireEvent, waitFor, within } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"

import { BeamView } from "../app/beam/BeamView"
import {
  BEAM_CARD_CACHE_KEY,
  BEAM_LINK_CACHE_KEY,
  buildBeamCardModel,
  loadBeamCardCache,
  loadBeamLinkCache,
} from "@/lib/beam-card"
import { beamShortUrl, publicPassportUrl } from "@/lib/app-url"
import type {
  BeamLink,
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
  getOrCreateBeamLink: vi.fn(),
}))

import {
  getOrCreateBeamLink,
  getPrivateWorkPassport,
  getWorkPassportStatus,
} from "@/lib/vbr-api"

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

/** The active revocable short link the Beam link service returns by default. */
const BEAM_CODE = "k7GhQ2mZ9pTw4Rx_"

function makeBeamLink(overrides: Partial<BeamLink> = {}): BeamLink {
  return {
    id: "link-1",
    code: BEAM_CODE,
    status: "active",
    short_path: `/b/${BEAM_CODE}`,
    public_passport_path: "/p/slug123",
    event_tag: null,
    expires_at: null,
    revoked_at: null,
    created_at: "2026-01-02T00:00:00Z",
    ...overrides,
  }
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
  vi.mocked(getOrCreateBeamLink).mockReset()
  vi.mocked(getOrCreateBeamLink).mockResolvedValue(makeBeamLink())
  window.localStorage.clear()
  delete (navigator as { share?: unknown }).share
})

afterEach(() => {
  vi.unstubAllEnvs()
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

// ── QR + link (Phase 2 payload: revocable short link) ────────────────────────

describe("Beam Card QR", () => {
  it("encodes EXACTLY the revocable short link — not the direct public URL, never a private route", async () => {
    const card = await renderBeam()
    const qr = within(card).getByTestId("beam-card-qr")
    const encoded = qr.getAttribute("data-qr-value") ?? ""
    expect(encoded).toBe(beamShortUrl(BEAM_CODE))
    expect(encoded).toContain(`/b/${BEAM_CODE}`)
    expect(encoded).not.toContain("/p/")
    expect(encoded).not.toContain("/card/")
    expect(encoded).not.toContain("/student/")
    expect(encoded).not.toContain("/beam")
  })

  it("shows the scan caption, visible short link, no-login note, and trust line", async () => {
    const card = await renderBeam()
    expect(within(card).getByTestId("beam-card-qr-caption")).toHaveTextContent(
      "Scan to open the live public Passport",
    )
    expect(within(card).getByTestId("beam-card-link")).toHaveTextContent(`/b/${BEAM_CODE}`)
    expect(within(card).getByTestId("beam-card-no-login")).toHaveTextContent("No login required")
    expect(within(card).getByTestId("beam-card-trust-line")).toHaveTextContent(
      "Public-safe proof summary — private evidence protected",
    )
  })

  it("falls back to the direct public URL with a visible note + retry when the link service fails", async () => {
    vi.mocked(getOrCreateBeamLink).mockRejectedValue(new Error("beam service down"))
    const card = await renderBeam()
    const encoded = within(card).getByTestId("beam-card-qr").getAttribute("data-qr-value")
    expect(encoded).toBe(publicPassportUrl("slug123"))
    expect(screen.getByTestId("beam-link-fallback-note")).toHaveTextContent(
      /secure short link unavailable/i,
    )
    expect(screen.getByTestId("beam-link-retry")).toBeInTheDocument()
  })

  it("retry re-attempts the Beam link and swaps the QR to the short link", async () => {
    vi.mocked(getOrCreateBeamLink).mockRejectedValueOnce(new Error("beam service down"))
    await renderBeam()
    fireEvent.click(screen.getByTestId("beam-link-retry"))
    await waitFor(() =>
      expect(screen.getByTestId("beam-card-qr").getAttribute("data-qr-value")).toBe(
        beamShortUrl(BEAM_CODE),
      ),
    )
    expect(screen.queryByTestId("beam-link-fallback-note")).not.toBeInTheDocument()
  })

  it("reuses this device's last saved short link when the link service fails", async () => {
    window.localStorage.setItem(BEAM_LINK_CACHE_KEY, beamShortUrl("cachedCode123456"))
    vi.mocked(getOrCreateBeamLink).mockRejectedValue(new Error("beam service down"))
    const card = await renderBeam()
    expect(within(card).getByTestId("beam-card-qr").getAttribute("data-qr-value")).toBe(
      beamShortUrl("cachedCode123456"),
    )
    // A revocable link is still in play — no fallback warning needed.
    expect(screen.queryByTestId("beam-link-fallback-note")).not.toBeInTheDocument()
  })

  it("never asks for a Beam link while the passport is unpublished", async () => {
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(
      makePassport({ is_published: false, public_slug: null, public_path: null }),
    )
    vi.mocked(getWorkPassportStatus).mockResolvedValue(unpublishedStatus)
    render(<BeamView />)
    await screen.findByTestId("beam-publish-first")
    expect(getOrCreateBeamLink).not.toHaveBeenCalled()
  })

  it("uses the configured production origin — never a hardcoded localhost", async () => {
    vi.stubEnv("NEXT_PUBLIC_APP_URL", "https://veribridgeai.com")
    const card = await renderBeam()
    const encoded = within(card).getByTestId("beam-card-qr").getAttribute("data-qr-value") ?? ""
    expect(encoded).toBe(`https://veribridgeai.com/b/${BEAM_CODE}`)
    expect(encoded).not.toContain("localhost")
  })
})

// ── Actions ──────────────────────────────────────────────────────────────────

describe("Beam actions", () => {
  it("copies the revocable short link and shows the 'Link copied' toast", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    await renderBeam()
    fireEvent.click(screen.getByTestId("beam-copy"))
    await waitFor(() => expect(writeText).toHaveBeenCalled())
    expect(writeText.mock.calls[0][0]).toBe(beamShortUrl(BEAM_CODE))
    expect(await screen.findByTestId("beam-copy-toast")).toHaveTextContent("Link copied")
  })

  it("Share Passport uses navigator.share when available — with the short link only", async () => {
    const share = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { share })
    await renderBeam()
    fireEvent.click(screen.getByTestId("beam-share"))
    await waitFor(() => expect(share).toHaveBeenCalled())
    expect(share.mock.calls[0][0].url).toBe(beamShortUrl(BEAM_CODE))
    expect(share.mock.calls[0][0].url).not.toContain("/student/")
    expect(share.mock.calls[0][0].url).not.toContain("/p/")
  })

  it("Share Passport falls back to copying when navigator.share is unavailable", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    await renderBeam()
    fireEvent.click(screen.getByTestId("beam-share"))
    await waitFor(() => expect(writeText).toHaveBeenCalled())
    expect(await screen.findByTestId("beam-share-note")).toHaveTextContent(/link copied instead/i)
  })

  it("Open public Passport links straight to the public URL in a new tab", async () => {
    // The owner's own "open" action skips the short-link hop on purpose —
    // still a public-safe URL, just no pointless redirect for the holder.
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
  it("caches the published card AND the short link on a successful load", async () => {
    await renderBeam()
    await waitFor(() => expect(window.localStorage.getItem(BEAM_CARD_CACHE_KEY)).toBeTruthy())
    const cached = loadBeamCardCache()
    expect(cached?.name).toBe("Jordan Rivera")
    expect(cached?.publicPassportUrl).toBe(publicPassportUrl("slug123"))
    expect(loadBeamLinkCache()).toBe(beamShortUrl(BEAM_CODE))
  })

  it("renders the last saved card + cached short link with an offline note when the load fails", async () => {
    // Seed both caches exactly as a previous successful visit would have.
    const model = buildBeamCardModel(makePassport(), publishedStatus)
    window.localStorage.setItem(BEAM_CARD_CACHE_KEY, JSON.stringify(model))
    window.localStorage.setItem(BEAM_LINK_CACHE_KEY, beamShortUrl(BEAM_CODE))

    vi.mocked(getPrivateWorkPassport).mockRejectedValue(new Error("network down"))
    vi.mocked(getWorkPassportStatus).mockRejectedValue(new Error("network down"))
    render(<BeamView />)

    const card = await screen.findByTestId("beam-card")
    expect(screen.getByTestId("beam-offline-note")).toHaveTextContent(/offline copy/i)
    expect(within(card).getByTestId("beam-card-name")).toHaveTextContent("Jordan Rivera")
    // The offline QR still carries the SHORT link — a revoked code shows the
    // safe inactive page at scan time even from an offline-rendered card.
    expect(within(card).getByTestId("beam-card-qr").getAttribute("data-qr-value")).toBe(
      beamShortUrl(BEAM_CODE),
    )
  })

  it("falls back to the direct public URL offline when no short link was ever cached", async () => {
    const model = buildBeamCardModel(makePassport(), publishedStatus)
    window.localStorage.setItem(BEAM_CARD_CACHE_KEY, JSON.stringify(model))

    vi.mocked(getPrivateWorkPassport).mockRejectedValue(new Error("network down"))
    vi.mocked(getWorkPassportStatus).mockRejectedValue(new Error("network down"))
    render(<BeamView />)

    const card = await screen.findByTestId("beam-card")
    expect(within(card).getByTestId("beam-card-qr").getAttribute("data-qr-value")).toBe(
      publicPassportUrl("slug123"),
    )
  })

  it("rejects a tampered short-link cache instead of encoding it", () => {
    window.localStorage.setItem(BEAM_LINK_CACHE_KEY, "https://evil.example.com/steal")
    expect(loadBeamLinkCache()).toBeNull()
    window.localStorage.setItem(BEAM_LINK_CACHE_KEY, "javascript:alert(1)")
    expect(loadBeamLinkCache()).toBeNull()
    window.localStorage.setItem(BEAM_LINK_CACHE_KEY, "http://localhost:3000/b/short")
    expect(loadBeamLinkCache()).toBeNull() // code too short to be minted
    window.localStorage.setItem(BEAM_LINK_CACHE_KEY, "http://localhost:3000/p/slug123")
    expect(loadBeamLinkCache()).toBeNull() // not a /b/ short link
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
