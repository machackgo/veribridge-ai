/**
 * Verified Passport Card — frontend tests.
 *
 * Covers the professional, QR-free recruiter/career-fair credential in both
 * surfaces:
 *  - Private preview embedded at the top of the owner's Passport
 *    (Verified Passport Card Preview): identity portrait, high-level ROLE-AREA
 *    chips (grouped from detailed skills), the profile-photo upload/update/remove
 *    flow, and the sharing controls (Copy link, Open Passport, Open Card, Download
 *    card, Web Share + fallback, optional "Show QR" modal).
 *  - Public /card/[slug]: recruiter-safe compact card, slug-anchored role-chip
 *    links, share/download/QR controls, and the safe not-found state.
 *
 * Safety guardrails asserted throughout: the compact card lists NO featured
 * projects and never leaks raw evidence, internal ids, file paths, private
 * routes, or numeric scores on either surface. The card face carries NO QR /
 * barcode — scanning is only available via the optional modal.
 */

import { render, screen, fireEvent, waitFor, within } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { PrivatePassportView } from "../app/student/vbr/passport/PrivatePassportView"
import { PublicPassportCardView } from "../app/card/[slug]/PublicPassportCardView"
import type { PassportIdentity, PrivateWorkPassport, PublicWorkPassport, WorkPassportStatus } from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", async (importActual) => ({
  // Keep the real pure helpers (validatePassportPhoto, publicSafeAvatarUrl, …);
  // only the network calls are mocked.
  ...(await importActual<typeof import("@/lib/vbr-api")>()),
  getPrivateWorkPassport: vi.fn(),
  getWorkPassportStatus: vi.fn(),
  publishWorkPassport: vi.fn(),
  unpublishWorkPassport: vi.fn(),
  publishVBRProjectReport: vi.fn(),
  getPublicWorkPassportBySlug: vi.fn(),
  uploadPassportPhoto: vi.fn(),
  removePassportPhoto: vi.fn(),
}))

import {
  getPrivateWorkPassport,
  getWorkPassportStatus,
  getPublicWorkPassportBySlug,
  uploadPassportPhoto,
  removePassportPhoto,
} from "@/lib/vbr-api"

// jsdom does not implement object URLs; the photo control creates one for its
// instant local preview, so stub them.
beforeEach(() => {
  globalThis.URL.createObjectURL = vi.fn(() => "blob:preview-mock")
  globalThis.URL.revokeObjectURL = vi.fn()
})

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
  vi.mocked(uploadPassportPhoto).mockReset()
  vi.mocked(removePassportPhoto).mockReset()
})

/** A valid in-memory image File of the given type/size for upload tests. */
function makeImageFile(type: string, name = "photo", sizeBytes = 1024): File {
  const file = new File(["x"], name, { type })
  Object.defineProperty(file, "size", { value: sizeBytes })
  return file
}

/** Assert no QR / barcode is painted on the card face. */
function expectNoQrOnCardFace(card: HTMLElement) {
  expect(within(card).queryByTestId("passport-card-qr")).not.toBeInTheDocument()
  expect(card.querySelector("[data-qr-value]")).toBeNull()
}

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

  it("never renders a QR/barcode on the card face (private, published or not)", async () => {
    const preview = await renderPrivate({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    const card = within(preview).getByTestId("passport-card-private")
    expectNoQrOnCardFace(card)
    // The identity area is a clean portrait, not a scan target.
    expect(within(card).getByTestId("passport-card-portrait")).toBeInTheDocument()
  })

  it("does not use old QR/scan copy on the card or photo control", async () => {
    const preview = await renderPrivate({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    const text = preview.textContent ?? ""
    expect(text).not.toMatch(/scan (the )?profile/i)
    expect(text).not.toMatch(/scan pattern/i)
    expect(text).not.toMatch(/scan code/i)
    // Professional replacement copy is present.
    expect(within(preview).getByTestId("passport-card-photo-control")).toHaveTextContent(
      /your profile photo appears on the passport card/i,
    )
  })

  it("clicking a role-area chip deep-links into the same-page Skills Evidence Map", async () => {
    const preview = await renderPrivate()
    const chip = within(preview).getAllByTestId("passport-card-capability")[0]
    fireEvent.click(chip)
    expect(screen.getByText(/Projects for selected skill/i)).toBeInTheDocument()
  })

  it("shows a publish action while private and no public share links yet", async () => {
    const preview = await renderPrivate({ is_published: false, public_slug: null })
    // Portrait present, no verified badge, no QR.
    expect(within(preview).getByTestId("passport-card-portrait")).toBeInTheDocument()
    expect(within(preview).queryByTestId("passport-card-verified-badge")).not.toBeInTheDocument()
    expect(within(preview).getByTestId("passport-card-preview-publish-hint")).toBeInTheDocument()
    expect(within(preview).getByTestId("publish-passport-button")).toBeInTheDocument()
    // No public copy/open/share links while private.
    expect(within(preview).queryByTestId("copy-passport-link-button")).not.toBeInTheDocument()
    expect(within(preview).queryByTestId("passport-card-open-card")).not.toBeInTheDocument()
    expect(within(preview).queryByTestId("share-passport-button")).not.toBeInTheDocument()
    expect(within(preview).queryByTestId("show-qr-button")).not.toBeInTheDocument()
  })

  it("exposes the full share controls once published (copy / open / open card / share / QR)", async () => {
    const preview = await renderPrivate({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    // Verified badge on the portrait once live.
    expect(within(preview).getByTestId("passport-card-verified-badge")).toBeInTheDocument()

    expect(within(preview).getByTestId("copy-passport-link-button")).toBeInTheDocument()
    const openPublic = within(preview).getByTestId("open-passport-link")
    expect(openPublic.getAttribute("href")).toContain("/p/slug123")
    const openCard = within(preview).getByTestId("passport-card-open-card")
    expect(openCard.getAttribute("href")).toContain("/card/slug123")
    expect(within(preview).getByTestId("share-passport-button")).toBeInTheDocument()
    expect(within(preview).getByTestId("show-qr-button")).toBeInTheDocument()
  })

  it("has a 'View full Work Passport' action below the card", async () => {
    const preview = await renderPrivate()
    expect(within(preview).getByTestId("passport-card-open-full")).toHaveTextContent(/full Work Passport/i)
  })

  it("offers a Download Passport Card action in any state", async () => {
    const preview = await renderPrivate({ is_published: false, public_slug: null })
    const download = within(preview).getByTestId("download-passport-card-button")
    expect(download).toHaveTextContent(/Download Passport Card/i)
    // Clicking must not throw (canvas is unsupported in jsdom → graceful fallback).
    expect(() => fireEvent.click(download)).not.toThrow()
  })

  it("shows the optional QR only inside a modal opened from the controls (never on the card face)", async () => {
    const preview = await renderPrivate({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    // No modal / no QR until explicitly requested.
    expect(screen.queryByTestId("passport-qr-modal")).not.toBeInTheDocument()
    fireEvent.click(within(preview).getByTestId("show-qr-button"))
    const modal = await screen.findByTestId("passport-qr-modal")
    const qr = within(modal).getByTestId("passport-modal-qr")
    // The modal QR encodes the public full Passport URL, never /card or a private route.
    const encoded = qr.getAttribute("data-qr-value") ?? ""
    expect(encoded).toContain("/p/slug123")
    expect(encoded).not.toContain("/card/")
    expect(encoded).not.toContain("/student/")
    // Dismissible.
    fireEvent.click(within(modal).getByTestId("passport-qr-modal-close"))
    await waitFor(() => expect(screen.queryByTestId("passport-qr-modal")).not.toBeInTheDocument())
  })

  it("Web Share falls back to copying the link when navigator.share is unavailable", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    // Ensure no share API is present.
    delete (navigator as { share?: unknown }).share
    const preview = await renderPrivate({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    fireEvent.click(within(preview).getByTestId("share-passport-button"))
    await waitFor(() => expect(writeText).toHaveBeenCalled())
    expect(writeText.mock.calls[0][0]).toContain("/p/slug123")
    expect(await within(preview).findByTestId("share-passport-note")).toHaveTextContent(/link copied/i)
  })

  it("uses the native share sheet when navigator.share exists", async () => {
    const share = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { share })
    const preview = await renderPrivate({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    fireEvent.click(within(preview).getByTestId("share-passport-button"))
    await waitFor(() => expect(share).toHaveBeenCalled())
    expect(share.mock.calls[0][0].url).toContain("/p/slug123")
    delete (navigator as { share?: unknown }).share
  })

  it("no longer surfaces the proximity-share / nearby-handoff feature", async () => {
    const preview = await renderPrivate({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    // The Proximity Share feature is fully removed from the MVP.
    expect(within(preview).queryByTestId("proximity-share-note")).not.toBeInTheDocument()
    expect(within(preview).queryByTestId("share-to-phone-button")).not.toBeInTheDocument()
    // No leftover nearby-device / NFC / Bluetooth / handoff-code copy.
    const text = preview.textContent ?? ""
    expect(text).not.toMatch(/proximity share/i)
    expect(text).not.toMatch(/nearby (device|share)/i)
    expect(text).not.toMatch(/handoff code/i)
    expect(text).not.toMatch(/NFC|Bluetooth|tap-to-phone/i)
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
    expect(labels.join(" ")).toMatch(/Data Science|Full-Stack|Software Engineering/)
    expect(labels.join(" ")).not.toMatch(/^Python$|^React$/)
  })

  it("falls back to safe initials when no profile image exists", async () => {
    const preview = await renderPrivate({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    expect(within(preview).getByTestId("passport-card-avatar")).toHaveTextContent("JR")
    expect(within(preview).queryByTestId("passport-card-profile-image")).not.toBeInTheDocument()
  })

  it("renders the profile photo portrait cleanly when a safe URL exists (no QR)", async () => {
    const preview = await renderPrivate({
      is_published: true,
      public_slug: "slug123",
      public_path: "/p/slug123",
      identity: makeIdentity({ avatar_url: "https://cdn.example.com/u/jordan.jpg" }),
    })
    const img = within(preview).getByTestId("passport-card-profile-image") as HTMLImageElement
    expect(img.getAttribute("src")).toBe("https://cdn.example.com/u/jordan.jpg")
    expect(img.style.objectFit).toBe("cover")
    expect(within(preview).queryByTestId("passport-card-avatar")).not.toBeInTheDocument()
    expectNoQrOnCardFace(within(preview).getByTestId("passport-card-private"))
  })

  it("renders a working Add profile photo control (no image yet, no Remove)", async () => {
    const preview = await renderPrivate()
    const addPhoto = within(preview).getByTestId("passport-card-add-photo")
    expect(addPhoto).toHaveTextContent(/add profile photo/i)
    expect(addPhoto).not.toBeDisabled()
    expect(within(preview).queryByTestId("passport-card-remove-photo")).not.toBeInTheDocument()
  })

  it("switches the control to Update / Remove when a photo exists", async () => {
    const preview = await renderPrivate({
      identity: makeIdentity({ avatar_url: "https://cdn.example.com/u/jordan.jpg" }),
    })
    expect(within(preview).getByTestId("passport-card-add-photo")).toHaveTextContent(/update profile photo/i)
    expect(within(preview).getByTestId("passport-card-remove-photo")).toBeInTheDocument()
  })

  it("rejects an unsupported file type before uploading", async () => {
    const preview = await renderPrivate()
    const input = within(preview).getByTestId("passport-card-photo-input")
    fireEvent.change(input, { target: { files: [makeImageFile("image/gif", "bad.gif")] } })
    expect(within(preview).getByTestId("passport-card-photo-error")).toHaveTextContent(
      /JPG, PNG, or WebP image under 5MB/i,
    )
    expect(uploadPassportPhoto).not.toHaveBeenCalled()
  })

  it("rejects an oversized file before uploading", async () => {
    const preview = await renderPrivate()
    const input = within(preview).getByTestId("passport-card-photo-input")
    const tooBig = makeImageFile("image/png", "big.png", 6 * 1024 * 1024)
    fireEvent.change(input, { target: { files: [tooBig] } })
    expect(within(preview).getByTestId("passport-card-photo-error")).toHaveTextContent(
      /JPG, PNG, or WebP image under 5MB/i,
    )
    expect(uploadPassportPhoto).not.toHaveBeenCalled()
  })

  it("uploads a valid image and shows the new portrait on the card", async () => {
    vi.mocked(uploadPassportPhoto).mockResolvedValue({
      avatar_url: "https://cdn.example.com/u/new-photo.png",
      persisted: true,
    })
    const preview = await renderPrivate({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    expect(within(preview).getByTestId("passport-card-avatar")).toBeInTheDocument()

    const input = within(preview).getByTestId("passport-card-photo-input")
    fireEvent.change(input, { target: { files: [makeImageFile("image/png", "me.png")] } })

    const img = (await within(preview).findByTestId("passport-card-profile-image")) as HTMLImageElement
    expect(img.getAttribute("src")).toBe("https://cdn.example.com/u/new-photo.png")
    expect(within(preview).queryByTestId("passport-card-avatar")).not.toBeInTheDocument()
    expect(within(preview).getByTestId("passport-card-photo-note")).toHaveTextContent(/profile photo updated/i)
    expect(uploadPassportPhoto).toHaveBeenCalledTimes(1)
  })

  it("removing the photo restores the safe initials fallback", async () => {
    vi.mocked(removePassportPhoto).mockResolvedValue({ avatar_url: null, persisted: true })
    const preview = await renderPrivate({
      is_published: true,
      public_slug: "slug123",
      public_path: "/p/slug123",
      identity: makeIdentity({ avatar_url: "https://cdn.example.com/u/jordan.jpg" }),
    })
    expect(within(preview).getByTestId("passport-card-profile-image")).toBeInTheDocument()

    fireEvent.click(within(preview).getByTestId("passport-card-remove-photo"))

    await waitFor(() =>
      expect(within(preview).queryByTestId("passport-card-profile-image")).not.toBeInTheDocument(),
    )
    expect(within(preview).getByTestId("passport-card-avatar")).toHaveTextContent("JR")
    expect(removePassportPhoto).toHaveBeenCalledTimes(1)
  })

  it("does not resurrect a duplicate Public Work Passport identity block", async () => {
    const preview = await renderPrivate({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    expect(screen.queryByTestId("passport-identity-header")).not.toBeInTheDocument()
    expect(within(preview).getAllByTestId("passport-sharing-controls")).toHaveLength(1)
  })

  // ── MVP sharing only — Proximity Share / nearby handoff removed ──────────────

  it("has no Proximity Share button or phone-share modal in the sharing controls", async () => {
    const preview = await renderPrivate({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    // The removed feature's button and modal must not mount in any state.
    expect(within(preview).queryByTestId("share-to-phone-button")).not.toBeInTheDocument()
    expect(screen.queryByTestId("phone-share-modal")).not.toBeInTheDocument()
    // The MVP share controls remain: Share Passport + Show QR.
    expect(within(preview).getByTestId("share-passport-button")).toBeInTheDocument()
    expect(within(preview).getByTestId("show-qr-button")).toBeInTheDocument()
  })

  it("has no handoff code or nearby-device copy anywhere in the preview", async () => {
    const preview = await renderPrivate({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    expect(within(preview).queryByTestId("phone-share-handoff-code")).not.toBeInTheDocument()
    expect(within(preview).queryByTestId("phone-share-receive-link")).not.toBeInTheDocument()
    const text = preview.textContent ?? ""
    expect(text).not.toMatch(/handoff code/i)
    expect(text).not.toMatch(/nearby (device|share)/i)
    expect(text).not.toMatch(/tap phones to transfer|tap-to-phone|AirDrop|NFC|Bluetooth/i)
  })

  it("never shares a private /student route through the MVP controls", async () => {
    const preview = await renderPrivate({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    const controls = within(preview).getByTestId("passport-sharing-controls")
    // Only public /p and /card links are exposed; no private owner route.
    expect(controls.innerHTML).not.toMatch(/\/student\//)
    expect(within(controls).getByTestId("open-passport-link").getAttribute("href")).toContain("/p/slug123")
    expect(within(controls).getByTestId("passport-card-open-card").getAttribute("href")).toContain("/card/slug123")
  })

  it("shows the localhost testing note when the public link is a localhost URL", async () => {
    // jsdom's window.origin is http://localhost, so the public link is localhost.
    const preview = await renderPrivate({ is_published: true, public_slug: "slug123", public_path: "/p/slug123" })
    expect(await within(preview).findByTestId("localhost-share-note")).toHaveTextContent(
      /localhost links only work on this computer.*network url|deploy to the production domain/i,
    )
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
    expect(within(card).queryByTestId("passport-card-project")).not.toBeInTheDocument()

    expect(screen.getByTestId("public-card-footer-note")).toHaveTextContent(/Recruiter-safe summaries only/i)
    expect(screen.getByTestId("public-card-full-passport-cta")).toHaveAttribute("href", "/p/slug123")
  })

  it("never renders a QR/barcode on the public card face", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())
    render(<PublicPassportCardView slug="slug123" />)
    await screen.findByTestId("public-passport-card")
    expectNoQrOnCardFace(screen.getByTestId("passport-card-public"))
    // And no leftover "scan the profile" copy.
    expect(screen.getByTestId("public-passport-card").textContent ?? "").not.toMatch(/scan the profile/i)
  })

  it("offers share / copy / download / QR controls below the card", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())
    render(<PublicPassportCardView slug="slug123" />)
    await screen.findByTestId("public-passport-card")
    expect(screen.getByTestId("public-card-copy-link")).toBeInTheDocument()
    expect(screen.getByTestId("public-card-share")).toBeInTheDocument()
    expect(screen.getByTestId("public-card-download")).toBeInTheDocument()
    expect(screen.getByTestId("public-card-show-qr")).toBeInTheDocument()
  })

  it("opens an optional QR modal encoding the full Passport URL", async () => {
    vi.mocked(getPublicWorkPassportBySlug).mockResolvedValue(makePublicPassport())
    render(<PublicPassportCardView slug="slug123" />)
    await screen.findByTestId("public-passport-card")
    expect(screen.queryByTestId("passport-qr-modal")).not.toBeInTheDocument()
    fireEvent.click(screen.getByTestId("public-card-show-qr"))
    const modal = await screen.findByTestId("passport-qr-modal")
    expect(within(modal).getByTestId("passport-modal-qr").getAttribute("data-qr-value")).toContain("/p/slug123")
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
    expect(text).not.toMatch(/\d+\s*\/\s*100|\d+\s*%|confidence:\s*\d/i)
    expect(text).not.toMatch(/\/student\/vbr\//)
  })
})
