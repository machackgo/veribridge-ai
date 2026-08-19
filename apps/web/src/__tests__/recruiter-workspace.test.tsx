/**
 * RecruiterWorkspaceView — the saved-candidates list.
 *
 * Covers: candidate cards render the consented public identity with a
 * reopen link, empty/error states, remove flow, and the private-passport
 * degradation (candidate stays listed, link goes dark).
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/recruiter-connections-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/recruiter-connections-api")>()),
  listConnections: vi.fn(),
  deleteConnection: vi.fn(),
}))

import {
  deleteConnection,
  listConnections,
  type RecruiterConnection,
} from "@/lib/recruiter-connections-api"
import { RecruiterWorkspaceView } from "../app/recruiters/workspace/RecruiterWorkspaceView"

const mockList = vi.mocked(listConnections)
const mockDelete = vi.mocked(deleteConnection)

const CONNECTION: RecruiterConnection = {
  id: "conn-1",
  source: "qr_scan",
  created_at: "2026-08-10T12:00:00+00:00",
  candidate: {
    display_name: "Ada Lovelace",
    headline: "Backend engineer",
    summary: "Builds verified FastAPI services.",
    availability_label: "Seeking internship",
    location: "London",
    role_areas: ["backend"],
    public_slug: "ada-slug",
    is_published: true,
  },
}

const PRIVATE_CONNECTION: RecruiterConnection = {
  id: "conn-2",
  source: "shared_link",
  created_at: "2026-08-01T12:00:00+00:00",
  candidate: {
    display_name: "Grace Hopper",
    headline: null,
    summary: null,
    availability_label: null,
    location: null,
    role_areas: [],
    public_slug: null,
    is_published: false,
  },
}

beforeEach(() => {
  vi.clearAllMocks()
  mockList.mockResolvedValue([CONNECTION, PRIVATE_CONNECTION])
  mockDelete.mockResolvedValue(undefined)
})

describe("RecruiterWorkspaceView", () => {
  it("renders saved candidates with identity, source, and a reopen link", async () => {
    render(<RecruiterWorkspaceView />)

    const cards = await screen.findAllByTestId("workspace-candidate-card")
    expect(cards).toHaveLength(2)
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument()
    expect(screen.getByText("Backend engineer")).toBeInTheDocument()
    expect(screen.getByTestId("workspace-count")).toHaveTextContent("2 candidates")

    const openLinks = screen.getAllByTestId("workspace-candidate-open")
    expect(openLinks).toHaveLength(1)
    expect(openLinks[0]).toHaveAttribute("href", "/p/ada-slug")

    const meta = screen.getAllByTestId("workspace-candidate-meta")[0]
    expect(meta).toHaveTextContent("QR scan")
  })

  it("marks unpublished candidates and offers no dead passport link", async () => {
    render(<RecruiterWorkspaceView />)

    await screen.findAllByTestId("workspace-candidate-card")
    expect(screen.getByTestId("workspace-candidate-private")).toHaveTextContent(
      "Passport currently private",
    )
  })

  it("renders the empty state with guidance when nothing is saved", async () => {
    mockList.mockResolvedValue([])
    render(<RecruiterWorkspaceView />)

    expect(await screen.findByTestId("workspace-empty")).toBeInTheDocument()
    expect(screen.getByText("No saved candidates yet")).toBeInTheDocument()
  })

  it("renders a retryable error state when loading fails", async () => {
    mockList.mockRejectedValueOnce(new Error("Backend unavailable"))
    render(<RecruiterWorkspaceView />)

    expect(await screen.findByText("Backend unavailable")).toBeInTheDocument()

    mockList.mockResolvedValueOnce([CONNECTION])
    fireEvent.click(screen.getByText("Try again"))
    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument()
  })

  it("removes a candidate via deleteConnection", async () => {
    render(<RecruiterWorkspaceView />)

    const removeButtons = await screen.findAllByTestId("workspace-candidate-remove")
    fireEvent.click(removeButtons[0])

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith("conn-1"))
    await waitFor(() =>
      expect(screen.queryByText("Ada Lovelace")).not.toBeInTheDocument(),
    )
    expect(screen.getByText("Grace Hopper")).toBeInTheDocument()
  })
})
