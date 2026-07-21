/**
 * Student share QR for the public Verified Build Report.
 *
 * The QR must encode exactly the canonical public report URL — the same value
 * copy-link uses — and never an auth/session token, private route, or storage
 * URL. Also covers the accessible text fallback + copy action in the modal
 * and the passport project card wiring.
 */

import { render, screen, fireEvent, waitFor, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { QrModal } from "../../components/passport/QrModal"
import { generateQrMatrix } from "@/lib/qr"
import { PrivatePassportView } from "../app/student/vbr/passport/PrivatePassportView"
import type { PrivateWorkPassport, WorkPassportStatus } from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/vbr-api")>()),
  getPrivateWorkPassport: vi.fn(),
  getWorkPassportStatus: vi.fn(),
  publishWorkPassport: vi.fn(),
  unpublishWorkPassport: vi.fn(),
  publishVBRProjectReport: vi.fn(),
}))

import { getPrivateWorkPassport, getWorkPassportStatus } from "@/lib/vbr-api"

const TOKEN = "aBcDeFgHiJkLmNoPqRsTuVwXyZ012345"
const CANONICAL_URL = `http://localhost:3000/vbr/report/${TOKEN}`

function makePassport(): PrivateWorkPassport {
  return {
    candidate_display_name: "Jordan Rivera",
    headline: "Full-stack builder",
    summary: "I ship and defend real projects.",
    is_published: false,
    public_slug: null,
    public_path: null,
    published_at: null,
    skills: [],
    projects: [
      {
        project_id: "proj-1",
        project_title: "Skill Evidence Tracker",
        project_summary: "Tracks student skill evidence.",
        repo_full_name: "octocat/Hello-World",
        claimed_skills: ["Python"],
        evidence_sources: ["GitHub Proof", "Project Defense"],
        evidence_package: {
          github_proof_attached: true,
          documents_count: 0,
          website_proofs_count: 0,
          project_defense_completed: true,
          video_defense_recorded: false,
          video_evidence_chip_count: 0,
        },
        attempt_count: 1,
        report: {
          is_public: true,
          public_token: TOKEN,
          public_path: `/vbr/report/${TOKEN}`,
          published_at: "2026-01-02T00:00:00Z",
        },
      },
    ],
    evidence_source_counts: { "GitHub Proof": 1, "Project Defense": 1 },
    project_count: 1,
    published_report_count: 1,
    limitations: [],
    generated_at: "2026-01-02T00:00:00Z",
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
  const p = makePassport()
  vi.mocked(getPrivateWorkPassport).mockReset().mockResolvedValue(p)
  vi.mocked(getWorkPassportStatus).mockReset().mockResolvedValue(statusFrom(p))
})

describe("qr generator version selection (VBR-RRO-D002 regression)", () => {
  // Root cause of the unscannable-QR defect: the RS block table was indexed
  // with the format-info bit values (M=0, L=1, H=2, Q=3) instead of the
  // table's [L, M, Q, H] row order, so an "M" code was built with L's block
  // structure (and L with M's, Q with H's, …) — structurally corrupt for
  // every real scanner. The observable symptom pinned here: a 65-byte URL at
  // level M must select version 5 (37 modules); the bug selected version 4
  // (33 modules) because it read L's larger capacity.
  const url65 = `http://localhost:3005/vbr/report/${"a".repeat(32)}`

  it("selects version 5 (37 modules) for a 65-byte URL at level M", () => {
    expect(url65.length).toBe(65)
    expect(generateQrMatrix(url65, "M")).toHaveLength(37)
  })

  it("selects version 4 (33 modules) for the same URL at level L", () => {
    expect(generateQrMatrix(url65, "L")).toHaveLength(33)
  })

  it("orders capacities L ≥ M ≥ Q ≥ H (same content never shrinks at higher EC)", () => {
    const sizes = (["L", "M", "Q", "H"] as const).map((lv) => generateQrMatrix(url65, lv).length)
    expect([...sizes].sort((a, b) => a - b)).toEqual(sizes)
  })
})

describe("QrModal (report link)", () => {
  it("encodes exactly the canonical public URL and shows the text fallback", () => {
    render(
      <QrModal
        value={CANONICAL_URL}
        open
        onClose={() => {}}
        title="Scan to open the Verified Build Report"
        subtitle="Point a phone camera at the code to open this project’s public report."
      />,
    )
    expect(screen.getByTestId("passport-modal-qr").getAttribute("data-qr-value")).toBe(
      CANONICAL_URL,
    )
    expect(screen.getByTestId("passport-qr-modal-url").textContent).toBe(CANONICAL_URL)
  })

  it("copies the link from the modal", () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } })
    render(<QrModal value={CANONICAL_URL} open onClose={() => {}} />)
    fireEvent.click(screen.getByTestId("passport-qr-modal-copy"))
    expect(writeText).toHaveBeenCalledWith(CANONICAL_URL)
    expect(screen.getByTestId("passport-qr-modal-copy").textContent).toMatch(/copied/i)
  })

  it("renders nothing without a published URL", () => {
    render(<QrModal value={null} open onClose={() => {}} />)
    expect(screen.queryByTestId("passport-qr-modal")).not.toBeInTheDocument()
  })
})

describe("PrivatePassportView project card QR", () => {
  it("opens the report QR with the same canonical URL that copy-link uses, with no auth material", async () => {
    render(<PrivatePassportView />)
    const card = await screen.findByTestId("passport-project-card")

    fireEvent.click(within(card).getByTestId("show-report-qr-button"))
    const modal = await screen.findByTestId("passport-qr-modal")

    const qrValue = within(modal).getByTestId("passport-modal-qr").getAttribute("data-qr-value")
    expect(qrValue).toBe(CANONICAL_URL)

    // No bearer/session/auth material and no private routes in the QR value.
    expect(qrValue).not.toMatch(/eyJ|bearer|sb-|supabase|access_token|session|\/student\//i)

    fireEvent.click(within(modal).getByTestId("passport-qr-modal-close"))
    await waitFor(() =>
      expect(screen.queryByTestId("passport-qr-modal")).not.toBeInTheDocument(),
    )
  })

  it("does not offer a report QR while the report is unpublished", async () => {
    const p = makePassport()
    p.projects[0].report = {
      is_public: false,
      public_token: null,
      public_path: null,
      published_at: null,
    }
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-project-card")
    expect(screen.queryByTestId("show-report-qr-button")).not.toBeInTheDocument()
  })
})
