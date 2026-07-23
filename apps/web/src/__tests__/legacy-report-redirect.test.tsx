/**
 * Legacy /r/[token] report page — canonical-redirect tests.
 *
 * Old shared links must keep working: when the legacy report's project has an
 * ACTIVE canonical public report, the page redirects to /vbr/report/{token};
 * otherwise it still renders the legacy content. The redirect target is
 * strictly validated so a tampered payload can never become an open redirect.
 */

import { render, screen, waitFor } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import PublicVBRReportPage from "../app/r/[token]/page"
import type { VBRPublicReportResponse } from "@/lib/vbr-api"

const replaceMock = vi.fn()

vi.mock("next/navigation", () => ({
  useParams: () => ({ token: "legacy-tok" }),
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
}))

vi.mock("@/lib/vbr-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/vbr-api")>()),
  getPublicVBRReport: vi.fn(),
}))

import { getPublicVBRReport } from "@/lib/vbr-api"

function makeLegacyReport(
  overrides: Partial<VBRPublicReportResponse> = {},
): VBRPublicReportResponse {
  return {
    project_title: "Skill Evidence Tracker",
    repo_full_name: "octocat/Hello-World",
    status: "published",
    published_at: "2026-01-02T00:00:00Z",
    claim_count: 1,
    evidence_count: 2,
    claims: [
      {
        claim_text: "Built the backend API",
        judgment: "demonstrated",
        rationale: "Code evidence found.",
        evidence_count: 2,
      },
    ],
    methodology: [],
    verification_note: "Evidence is described qualitatively.",
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(getPublicVBRReport).mockReset()
  replaceMock.mockReset()
})

describe("Legacy /r/[token] page", () => {
  it("redirects to the canonical /vbr/report path when the mapping is valid", async () => {
    vi.mocked(getPublicVBRReport).mockResolvedValue(
      makeLegacyReport({ canonical_report_path: "/vbr/report/tok-new" }),
    )

    render(<PublicVBRReportPage />)

    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/vbr/report/tok-new"))
  })

  it("still renders the legacy report when no canonical mapping exists", async () => {
    vi.mocked(getPublicVBRReport).mockResolvedValue(makeLegacyReport())

    render(<PublicVBRReportPage />)

    expect(await screen.findByText("Skill Evidence Tracker")).toBeInTheDocument()
    expect(replaceMock).not.toHaveBeenCalled()
  })

  it("rejects a non-canonical redirect target (open-redirect guard)", async () => {
    for (const unsafe of [
      "https://evil.example.com/vbr/report/x",
      "//evil.example.com",
      "/student/vbr/passport",
      "/vbr/report/../../admin",
      "javascript:alert(1)",
    ]) {
      vi.mocked(getPublicVBRReport).mockResolvedValue(
        makeLegacyReport({ canonical_report_path: unsafe }),
      )
      const { unmount } = render(<PublicVBRReportPage />)
      expect(await screen.findByText("Skill Evidence Tracker")).toBeInTheDocument()
      expect(replaceMock).not.toHaveBeenCalled()
      unmount()
    }
  })
})
