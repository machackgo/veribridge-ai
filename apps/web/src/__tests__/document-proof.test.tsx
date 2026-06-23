/**
 * Document Proof / Supporting Evidence — frontend wiring tests.
 *
 * Covers: the page renders upload + paste UI, saving/uploading a document
 * does not immediately claim a Skill Graph sync, the explicit "Save to
 * Skill Graph" button calls the sync endpoint with the returned id, sync
 * failure shows an honest "Couldn't save" + Retry state that recovers on
 * retry, and no huge raw text/snippets are ever rendered.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { DocumentProofPanel } from "../../components/passport/DocumentProofPanel"
import type { DocumentProofResponse, DocumentProofSyncResult } from "@/lib/passport-api"

vi.mock("@/lib/passport-api", () => ({
  listDocumentProofs: vi.fn(),
  submitDocumentProof: vi.fn(),
  uploadDocumentProof: vi.fn(),
  syncDocumentProofToSkillGraph: vi.fn(),
}))

const mockRouterPush = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush }),
}))

import {
  listDocumentProofs,
  submitDocumentProof,
  syncDocumentProofToSkillGraph,
} from "@/lib/passport-api"

function makeProof(overrides: Partial<DocumentProofResponse> = {}): DocumentProofResponse {
  return {
    id: "doc-1",
    source_type: "document",
    status: "submitted",
    filename: null,
    title: "My Project Report",
    claimed_skills: [],
    description: null,
    analysis_json: {},
    evidence_objects: [],
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  }
}

function makeSyncResult(overrides: Partial<DocumentProofSyncResult> = {}): DocumentProofSyncResult {
  return {
    ok: true,
    already_synced: false,
    skills_synced: ["FastAPI"],
    pipelines_upserted: 1,
    artifacts_created: 1,
    errors: [],
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(listDocumentProofs).mockReset()
  vi.mocked(submitDocumentProof).mockReset()
  vi.mocked(syncDocumentProofToSkillGraph).mockReset()
  mockRouterPush.mockReset()
  // Reset the URL so a returnTo from one test never leaks into another.
  window.history.replaceState({}, "", "/student/proofs/documents")
})

describe("DocumentProofPanel", () => {
  it("renders upload and paste UI when adding a document", async () => {
    vi.mocked(listDocumentProofs).mockResolvedValue([])

    render(<DocumentProofPanel />)

    fireEvent.click(await screen.findByRole("button", { name: /add document/i }))

    expect(screen.getByRole("button", { name: /paste text/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /upload file/i })).toBeInTheDocument()

    expect(screen.getByPlaceholderText(/paste your project report/i)).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: /upload file/i }))
    expect(screen.getByText(/document file \(pdf, docx, txt, or md\)/i)).toBeInTheDocument()
  })

  it("does not call syncDocumentProofToSkillGraph immediately after submitting text", async () => {
    vi.mocked(listDocumentProofs).mockResolvedValue([])
    const analyzed = makeProof({ id: "doc-new", status: "analyzed", evidence_objects: [
      { skill_name: "FastAPI", confidence: "medium", snippet: "Implemented FastAPI to serve the app." },
    ] })
    vi.mocked(submitDocumentProof).mockResolvedValue(analyzed)

    render(<DocumentProofPanel />)

    fireEvent.click(await screen.findByRole("button", { name: /add document/i }))
    fireEvent.change(screen.getByPlaceholderText(/paste your project report/i), {
      target: { value: "For this project I implemented FastAPI to serve the application." },
    })
    fireEvent.click(screen.getByRole("button", { name: /^submit$/i }))

    await waitFor(() => expect(submitDocumentProof).toHaveBeenCalled())
    expect(syncDocumentProofToSkillGraph).not.toHaveBeenCalled()

    // The explicit save action is now available for the newly analyzed document.
    expect(await screen.findByRole("button", { name: /save to skill graph/i })).toBeInTheDocument()
  })

  it("calls syncDocumentProofToSkillGraph with the document id when 'Save to Skill Graph' is clicked", async () => {
    const analyzed = makeProof({
      id: "doc-1",
      status: "analyzed",
      evidence_objects: [{ skill_name: "FastAPI", confidence: "medium", snippet: "Implemented FastAPI." }],
    })
    vi.mocked(listDocumentProofs).mockResolvedValue([analyzed])
    vi.mocked(syncDocumentProofToSkillGraph).mockResolvedValue(makeSyncResult())

    render(<DocumentProofPanel />)

    fireEvent.click(await screen.findByRole("button", { name: /save to skill graph/i }))

    await waitFor(() => expect(syncDocumentProofToSkillGraph).toHaveBeenCalledWith("doc-1"))
    expect(await screen.findByText(/saved to skill graph/i)).toBeInTheDocument()
  })

  it("shows 'Couldn't save to Skill Graph' with Retry on failure, and recovers on retry", async () => {
    const analyzed = makeProof({
      id: "doc-2",
      status: "analyzed",
      evidence_objects: [{ skill_name: "FastAPI", confidence: "medium", snippet: "Implemented FastAPI." }],
    })
    vi.mocked(listDocumentProofs).mockResolvedValue([analyzed])
    vi.mocked(syncDocumentProofToSkillGraph).mockRejectedValueOnce(new Error("sync_failed"))

    render(<DocumentProofPanel />)

    fireEvent.click(await screen.findByRole("button", { name: /save to skill graph/i }))

    expect(await screen.findByText(/couldn.t save to skill graph/i)).toBeInTheDocument()
    expect(screen.queryByText(/saved to skill graph/i)).not.toBeInTheDocument()

    vi.mocked(syncDocumentProofToSkillGraph).mockResolvedValueOnce(makeSyncResult())
    fireEvent.click(await screen.findByRole("button", { name: /save to skill graph/i }))

    await waitFor(() => expect(syncDocumentProofToSkillGraph).toHaveBeenCalledTimes(2))
    expect(await screen.findByText(/saved to skill graph/i)).toBeInTheDocument()
  })

  it("never renders the full raw text of a long evidence snippet", async () => {
    const longSnippet = "A".repeat(500)
    const analyzed = makeProof({
      id: "doc-3",
      status: "analyzed",
      evidence_objects: [{ skill_name: "FastAPI", confidence: "medium", snippet: longSnippet }],
    })
    vi.mocked(listDocumentProofs).mockResolvedValue([analyzed])

    render(<DocumentProofPanel />)

    await screen.findByText(/FastAPI/)

    expect(screen.queryByText(longSnippet)).not.toBeInTheDocument()
    expect(screen.getByText(/A{160}…/)).toBeInTheDocument()
  })

  // ── returnTo flow (Project Defense → Add Document Proof → back) ──────────────

  it("redirects to a safe internal returnTo after a successful submission", async () => {
    window.history.replaceState(
      {},
      "",
      "/student/proofs/documents?returnTo=/student/proofs/project-defense",
    )
    vi.mocked(listDocumentProofs).mockResolvedValue([])
    vi.mocked(submitDocumentProof).mockResolvedValue(makeProof({ id: "doc-new", status: "analyzed" }))

    render(<DocumentProofPanel />)

    fireEvent.click(await screen.findByRole("button", { name: /add document/i }))
    fireEvent.change(screen.getByPlaceholderText(/paste your project report/i), {
      target: { value: "For this project I implemented FastAPI to serve the application." },
    })
    fireEvent.click(screen.getByRole("button", { name: /^submit$/i }))

    await waitFor(() => expect(submitDocumentProof).toHaveBeenCalled())
    await waitFor(() =>
      expect(mockRouterPush).toHaveBeenCalledWith("/student/proofs/project-defense"),
    )
  })

  it("ignores an unsafe external returnTo and does not redirect to it", async () => {
    window.history.replaceState({}, "", "/student/proofs/documents?returnTo=https://evil.com")
    vi.mocked(listDocumentProofs).mockResolvedValue([])
    vi.mocked(submitDocumentProof).mockResolvedValue(makeProof({ id: "doc-new", status: "analyzed" }))

    render(<DocumentProofPanel />)

    fireEvent.click(await screen.findByRole("button", { name: /add document/i }))
    fireEvent.change(screen.getByPlaceholderText(/paste your project report/i), {
      target: { value: "For this project I implemented FastAPI to serve the application." },
    })
    fireEvent.click(screen.getByRole("button", { name: /^submit$/i }))

    await waitFor(() => expect(submitDocumentProof).toHaveBeenCalled())
    expect(mockRouterPush).not.toHaveBeenCalled()
  })

  it("does not redirect when there is no returnTo", async () => {
    vi.mocked(listDocumentProofs).mockResolvedValue([])
    vi.mocked(submitDocumentProof).mockResolvedValue(makeProof({ id: "doc-new", status: "analyzed" }))

    render(<DocumentProofPanel />)

    fireEvent.click(await screen.findByRole("button", { name: /add document/i }))
    fireEvent.change(screen.getByPlaceholderText(/paste your project report/i), {
      target: { value: "For this project I implemented FastAPI to serve the application." },
    })
    fireEvent.click(screen.getByRole("button", { name: /^submit$/i }))

    await waitFor(() => expect(submitDocumentProof).toHaveBeenCalled())
    expect(mockRouterPush).not.toHaveBeenCalled()
  })
})
