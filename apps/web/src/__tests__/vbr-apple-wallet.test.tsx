/**
 * Apple Wallet Passport Pass — /beam frontend gating tests.
 *
 * The "Add to Apple Wallet" button is HONEST or absent:
 *  - hidden when the backend readiness says disabled (default), when the
 *    readiness check fails (fail-closed), and on the unpublished state;
 *  - shown ONLY when the backend confirms it can issue a REAL signed pass,
 *    and its click fetches the gated `.pkpass` endpoint (owner-auth blob
 *    download — never a fabricated file);
 *  - a wallet-readiness failure never takes the Beam Card down: the card, its
 *    revocable `/b/{code}` QR, and the share/copy actions render regardless;
 *  - no fake Google Wallet / NFC surfaces are ever rendered.
 */

import { render, screen, fireEvent, waitFor, within } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"

import { BeamView } from "../app/beam/BeamView"
import { beamShortUrl } from "@/lib/app-url"
import type {
  AppleWalletAvailability,
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
  getAppleWalletAvailability: vi.fn(),
  downloadAppleWalletPass: vi.fn(),
}))

import {
  downloadAppleWalletPass,
  getAppleWalletAvailability,
  getOrCreateBeamLink,
  getPrivateWorkPassport,
  getWorkPassportStatus,
} from "@/lib/vbr-api"

// ── Factories (published passport, matching the Beam Card test shapes) ───────

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
    skills: [skill({ skill: "Python" })],
    projects: [
      {
        project_id: "proj-1",
        project_title: "Skill Evidence Tracker",
        project_summary: "Tracks student skill evidence.",
        repo_full_name: "octocat/Hello-World",
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
        report: { is_public: true, public_token: "tok123", public_path: "/r/tok123", published_at: "2026-01-02T00:00:00Z" },
      },
    ],
    evidence_source_counts: { "GitHub Proof": 1 },
    project_count: 1,
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

function availability(overrides: Partial<AppleWalletAvailability> = {}): AppleWalletAvailability {
  return {
    enabled: false,
    feature_flag: false,
    identifiers_configured: false,
    signing_ready: false,
    ...overrides,
  }
}

const ENABLED = availability({
  enabled: true,
  feature_flag: true,
  identifiers_configured: true,
  signing_ready: true,
})

// ── Setup ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  window.localStorage.clear()
  vi.mocked(getPrivateWorkPassport).mockResolvedValue(makePassport())
  vi.mocked(getWorkPassportStatus).mockResolvedValue(publishedStatus)
  vi.mocked(getOrCreateBeamLink).mockResolvedValue(makeBeamLink())
  vi.mocked(getAppleWalletAvailability).mockResolvedValue(availability())
  vi.mocked(downloadAppleWalletPass).mockResolvedValue(
    new Blob(["pkpass-bytes"], { type: "application/vnd.apple.pkpass" }),
  )
})

afterEach(() => {
  vi.clearAllMocks()
})

async function renderBeam() {
  render(<BeamView />)
  return await screen.findByTestId("beam-card")
}

// ── Hidden by default / fail-closed ───────────────────────────────────────────

describe("Apple Wallet button gating on /beam", () => {
  it("shows NO wallet button when the backend reports disabled (default)", async () => {
    const card = await renderBeam()

    expect(screen.queryByTestId("beam-add-to-apple-wallet")).not.toBeInTheDocument()
    // The Beam Card itself is untouched: QR still the revocable short link.
    expect(within(card).getByTestId("beam-card-qr").getAttribute("data-qr-value")).toBe(
      beamShortUrl(BEAM_CODE),
    )
  })

  it("shows NO wallet button when the readiness check itself fails (fail-closed)", async () => {
    vi.mocked(getAppleWalletAvailability).mockRejectedValue(new Error("network down"))
    const card = await renderBeam()

    expect(screen.queryByTestId("beam-add-to-apple-wallet")).not.toBeInTheDocument()
    // A wallet problem never takes the handoff surface down.
    expect(card).toBeInTheDocument()
    expect(screen.getByTestId("beam-share")).toBeInTheDocument()
  })

  it("shows NO wallet button when partially configured but not enabled", async () => {
    vi.mocked(getAppleWalletAvailability).mockResolvedValue(
      availability({ feature_flag: true, identifiers_configured: true, signing_ready: false }),
    )
    await renderBeam()
    expect(screen.queryByTestId("beam-add-to-apple-wallet")).not.toBeInTheDocument()
  })

  it("never checks wallet readiness (and shows no button) for an unpublished passport", async () => {
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(
      makePassport({ is_published: false, public_slug: null, public_path: null, published_at: null }),
    )
    vi.mocked(getWorkPassportStatus).mockResolvedValue(unpublishedStatus)
    vi.mocked(getAppleWalletAvailability).mockResolvedValue(ENABLED)

    render(<BeamView />)
    await screen.findByTestId("beam-publish-first")

    expect(screen.queryByTestId("beam-add-to-apple-wallet")).not.toBeInTheDocument()
    expect(getAppleWalletAvailability).not.toHaveBeenCalled()
  })

  it("renders no fake Google Wallet or NFC surfaces", async () => {
    vi.mocked(getAppleWalletAvailability).mockResolvedValue(ENABLED)
    await renderBeam()

    expect(screen.queryByText(/google wallet/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/nfc/i)).not.toBeInTheDocument()
  })
})

// ── Enabled path ──────────────────────────────────────────────────────────────

describe("Apple Wallet button when the backend is fully configured", () => {
  beforeEach(() => {
    vi.mocked(getAppleWalletAvailability).mockResolvedValue(ENABLED)
  })

  it("renders the Add to Apple Wallet action alongside the untouched Beam actions", async () => {
    const card = await renderBeam()

    const button = screen.getByTestId("beam-add-to-apple-wallet")
    expect(button).toHaveTextContent("Add to Apple Wallet")
    // Existing Beam surface is unchanged around it.
    expect(screen.getByTestId("beam-share")).toBeInTheDocument()
    expect(screen.getByTestId("beam-copy")).toBeInTheDocument()
    expect(screen.getByTestId("beam-open-public")).toBeInTheDocument()
    expect(within(card).getByTestId("beam-card-qr").getAttribute("data-qr-value")).toBe(
      beamShortUrl(BEAM_CODE),
    )
  })

  it("clicking the button downloads the pass from the gated .pkpass endpoint", async () => {
    const createObjectURL = vi.fn(() => "blob:pass")
    const revokeObjectURL = vi.fn()
    vi.stubGlobal("URL", Object.assign(Object.create(URL), { createObjectURL, revokeObjectURL }))

    try {
      await renderBeam()
      fireEvent.click(screen.getByTestId("beam-add-to-apple-wallet"))

      await waitFor(() => expect(downloadAppleWalletPass).toHaveBeenCalledTimes(1))
      await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1))
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:pass")
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it("surfaces an honest note when the pass download fails (no fake success)", async () => {
    vi.mocked(downloadAppleWalletPass).mockRejectedValue(
      new Error("Apple Wallet pass is unavailable right now."),
    )
    await renderBeam()
    fireEvent.click(screen.getByTestId("beam-add-to-apple-wallet"))

    const note = await screen.findByTestId("beam-share-note")
    expect(note).toHaveTextContent("Apple Wallet pass is unavailable right now.")
  })
})
