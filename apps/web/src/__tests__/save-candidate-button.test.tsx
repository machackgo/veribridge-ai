/**
 * SaveCandidateButton — the public passport "Save Candidate" CTA.
 *
 * Covers:
 *  * signed-out click routes to /login with a `next` that returns to the
 *    same passport carrying the save marker (+ QR source);
 *  * signed-in save → Saved ✓ with a workspace link;
 *  * already-saved passports settle straight into Saved ✓;
 *  * the post-login `?save=1` marker auto-completes the save and cleans the URL;
 *  * failures render a retryable error, and retry succeeds.
 *
 * The component is deliberately router-free (public page): it reads
 * `window.location` and navigates via the injected `navigate` seam.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const getSession = vi.fn()
vi.mock("@/lib/supabase/client", () => ({
  createSupabaseBrowserClient: () => ({ auth: { getSession } }),
}))

vi.mock("@/lib/recruiter-connections-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/recruiter-connections-api")>()),
  saveCandidate: vi.fn(),
  getConnectionStatus: vi.fn(),
}))

import {
  AuthRequiredError,
  getConnectionStatus,
  saveCandidate,
} from "@/lib/recruiter-connections-api"
import { SaveCandidateButton } from "../../components/recruiter/SaveCandidateButton"

const mockSave = vi.mocked(saveCandidate)
const mockStatus = vi.mocked(getConnectionStatus)

const SAVED_RESULT = {
  id: "conn-1",
  saved: true,
  already_saved: false,
  source: "shared_link" as const,
  created_at: "2026-08-14T00:00:00+00:00",
  candidate: {
    display_name: "Ada Lovelace",
    headline: null,
    summary: null,
    availability_label: null,
    location: null,
    role_areas: [],
    public_slug: "test-slug",
    is_published: true,
  },
}

function setUrl(pathAndQuery: string) {
  window.history.replaceState(null, "", pathAndQuery)
}

beforeEach(() => {
  vi.clearAllMocks()
  setUrl("/p/test-slug")
  getSession.mockResolvedValue({ data: { session: null } })
  mockStatus.mockResolvedValue({ saved: false, connection_id: null })
  mockSave.mockResolvedValue(SAVED_RESULT)
})

describe("SaveCandidateButton", () => {
  it("routes a signed-out visitor to login preserving the passport return URL", async () => {
    mockSave.mockRejectedValue(new AuthRequiredError())
    setUrl("/p/test-slug?src=qr")
    const navigate = vi.fn()
    render(<SaveCandidateButton slug="test-slug" navigate={navigate} />)

    fireEvent.click(await screen.findByTestId("save-candidate-button"))

    await waitFor(() => expect(navigate).toHaveBeenCalledTimes(1))
    const dest = navigate.mock.calls[0][0] as string
    expect(dest.startsWith("/login?next=")).toBe(true)
    const next = decodeURIComponent(dest.slice("/login?next=".length))
    expect(next).toBe("/p/test-slug?save=1&src=qr")
  })

  it("saves immediately for a signed-in recruiter and links to the workspace", async () => {
    getSession.mockResolvedValue({ data: { session: { user: { id: "r1" } } } })
    render(<SaveCandidateButton slug="test-slug" />)

    fireEvent.click(await screen.findByTestId("save-candidate-button"))

    expect(await screen.findByTestId("save-candidate-saved")).toHaveTextContent("Saved ✓")
    expect(screen.getByTestId("save-candidate-workspace-link")).toHaveAttribute(
      "href",
      "/recruiters/workspace",
    )
    expect(mockSave).toHaveBeenCalledWith("test-slug", "shared_link", {
      passport_slug: "test-slug",
    })
  })

  it("records a QR arrival as qr_scan", async () => {
    setUrl("/p/test-slug?src=qr")
    getSession.mockResolvedValue({ data: { session: { user: { id: "r1" } } } })
    render(<SaveCandidateButton slug="test-slug" />)

    fireEvent.click(await screen.findByTestId("save-candidate-button"))

    await waitFor(() =>
      expect(mockSave).toHaveBeenCalledWith("test-slug", "qr_scan", {
        passport_slug: "test-slug",
      }),
    )
  })

  it("shows Saved ✓ straight away when the candidate is already saved", async () => {
    getSession.mockResolvedValue({ data: { session: { user: { id: "r1" } } } })
    mockStatus.mockResolvedValue({ saved: true, connection_id: "conn-1" })
    render(<SaveCandidateButton slug="test-slug" />)

    expect(await screen.findByTestId("save-candidate-saved")).toBeInTheDocument()
    expect(mockSave).not.toHaveBeenCalled()
  })

  it("auto-completes the save after the login round-trip and cleans the URL", async () => {
    setUrl("/p/test-slug?save=1&src=qr")
    getSession.mockResolvedValue({ data: { session: { user: { id: "r1" } } } })
    render(<SaveCandidateButton slug="test-slug" />)

    expect(await screen.findByTestId("save-candidate-saved")).toBeInTheDocument()
    expect(mockSave).toHaveBeenCalledWith("test-slug", "qr_scan", {
      passport_slug: "test-slug",
    })
    // The one-shot markers are dropped so a refresh doesn't re-trigger.
    await waitFor(() => expect(window.location.search).toBe(""))
    expect(window.location.pathname).toBe("/p/test-slug")
    expect(mockStatus).not.toHaveBeenCalled()
  })

  it("renders a retryable error when the save fails, and retry succeeds", async () => {
    getSession.mockResolvedValue({ data: { session: { user: { id: "r1" } } } })
    mockSave.mockRejectedValueOnce(new Error("Network down"))
    render(<SaveCandidateButton slug="test-slug" />)

    fireEvent.click(await screen.findByTestId("save-candidate-button"))
    expect(await screen.findByRole("alert")).toHaveTextContent("Network down")

    mockSave.mockResolvedValueOnce(SAVED_RESULT)
    fireEvent.click(screen.getByTestId("save-candidate-retry"))
    expect(await screen.findByTestId("save-candidate-saved")).toBeInTheDocument()
  })
})
