/**
 * Public report view beacon — fire-and-forget analytics that may never block
 * or break the report page.
 *
 * Covers: one beacon per successful load, session dedupe key reuse, source
 * attribution consumption (recruiter_open / recruiter_scan → then back to
 * direct), silent failure, and no beacon at all for not-found reports.
 */

import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { PublicReportView } from "../app/vbr/report/[token]/PublicReportView"
import {
  markReportOpenSource,
  recordPublicReportView,
} from "@/lib/report-view-beacon"
import type { PublicVBRProjectReport } from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/vbr-api")>()),
  getPublicVBRProjectReport: vi.fn(),
}))

import { getPublicVBRProjectReport } from "@/lib/vbr-api"

const TOKEN = "aBcDeFgHiJkLmNoPqRsTuVwXyZ012345"

function minimalReport(): PublicVBRProjectReport {
  return {
    report_title: "Verified Build Report",
    project_title: "Skill Evidence Tracker",
    candidate_display_name: "Jordan Rivera",
    project_summary: "Tracks skill evidence.",
    student_role: "Built it.",
    repo_full_name: null,
    claimed_skills: [],
    evidence_package: {
      github_proof_attached: false,
      documents_count: 0,
      website_proofs_count: 0,
      project_defense_completed: false,
      video_defense_recorded: false,
      video_evidence_chip_count: 0,
    },
    github_proof: null,
    documents: [],
    website_proofs: [],
    project_defense_analysis: null,
    defense_answer_evidence: [],
    project_defense_inspection: [],
    skill_evidence: [],
    evidence_traces: [],
    video_evidence_chips: [],
    limitations: [],
    published_at: "2026-01-02T00:00:00Z",
    generated_at: "2026-01-02T00:00:00Z",
    public_passport_path: null,
    verification_note: "Shared by the candidate.",
  } as unknown as PublicVBRProjectReport
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  window.sessionStorage.clear()
  fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 })
  vi.stubGlobal("fetch", fetchMock)
  vi.mocked(getPublicVBRProjectReport).mockReset()
})

function beaconCalls() {
  return fetchMock.mock.calls.filter(([url]) => String(url).includes("/view"))
}

describe("recordPublicReportView (unit)", () => {
  it("posts source + a stable per-session dedupe key", async () => {
    markReportOpenSource("recruiter_open")
    await recordPublicReportView(TOKEN)
    await recordPublicReportView(TOKEN)

    expect(beaconCalls()).toHaveLength(2)
    const first = JSON.parse(beaconCalls()[0][1].body)
    const second = JSON.parse(beaconCalls()[1][1].body)
    expect(first.source).toBe("recruiter_open")
    // The tag is single-use: the next view of the same session is "direct".
    expect(second.source).toBe("direct")
    // Same session → same dedupe key, so the backend records only one row.
    expect(first.dedupe_key).toBe(second.dedupe_key)
    expect(first.dedupe_key).toMatch(/^[A-Za-z0-9_-]{8,128}$/)
  })

  it("uses recruiter_scan attribution when tagged by the scanner", async () => {
    markReportOpenSource("recruiter_scan")
    await recordPublicReportView(TOKEN)
    expect(JSON.parse(beaconCalls()[0][1].body).source).toBe("recruiter_scan")
  })

  it("never throws when the network fails", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"))
    await expect(recordPublicReportView(TOKEN)).resolves.toBeUndefined()
  })

  it("sends nothing identifying — only source and an opaque key", async () => {
    await recordPublicReportView(TOKEN)
    const body = JSON.parse(beaconCalls()[0][1].body)
    expect(Object.keys(body).sort()).toEqual(["dedupe_key", "source"])
  })
})

describe("PublicReportView beacon integration", () => {
  it("fires exactly one beacon after a successful load", async () => {
    vi.mocked(getPublicVBRProjectReport).mockResolvedValue(minimalReport())
    render(<PublicReportView token={TOKEN} />)
    await screen.findByText("Skill Evidence Tracker")
    await waitFor(() => expect(beaconCalls()).toHaveLength(1))
    expect(beaconCalls()[0][0]).toContain(`/api/v1/public/vbr/reports/${TOKEN}/view`)
  })

  it("does not fire a beacon for a not-found report", async () => {
    vi.mocked(getPublicVBRProjectReport).mockResolvedValue(null)
    render(<PublicReportView token={TOKEN} />)
    await screen.findByTestId("public-report-not-found")
    expect(beaconCalls()).toHaveLength(0)
  })

  it("still renders the report when the beacon endpoint fails", async () => {
    vi.mocked(getPublicVBRProjectReport).mockResolvedValue(minimalReport())
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"))
    render(<PublicReportView token={TOKEN} />)
    expect(await screen.findByText("Skill Evidence Tracker")).toBeInTheDocument()
  })
})
