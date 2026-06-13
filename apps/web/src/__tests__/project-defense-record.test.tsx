/**
 * Project Defense recording route (Phase 2A) — `/student/proofs/project-defense/record/[sessionId]`.
 *
 * Covers: the route renders Project Defense-specific recording copy (not the
 * generic VBR walkthrough copy), camera is presented as optional and never
 * required, no team/diarization/public-report language leaks in, permission
 * denials are shown as friendly messages without exposing storage internals,
 * no storage paths/signed URLs/tokens are ever rendered, and the manual
 * pasted-transcript fallback remains reachable.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import ProjectDefenseRecordPage from "../app/student/proofs/project-defense/record/[sessionId]/page"
import {
  getVBRProject,
  getVBRSession,
  type VBRSessionDetailResponse,
} from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", () => ({
  getVBRSession: vi.fn(),
  getVBRProject: vi.fn(),
  createVBRSessionConsent: vi.fn(),
  startVBRSession: vi.fn(),
  requestVBRChunkUploadUrl: vi.fn(),
  uploadVBRChunkBytes: vi.fn(),
  uploadVBRSessionChunk: vi.fn(),
  updateVBRSessionTelemetry: vi.fn(),
  finalizeVBRSession: vi.fn(),
}))

vi.mock("next/navigation", () => ({
  useParams: () => ({ sessionId: "sess-1" }),
}))

function makeSession(overrides: Partial<VBRSessionDetailResponse> = {}): VBRSessionDetailResponse {
  return {
    id: "sess-1",
    project_id: "proj-1",
    attempt_no: 1,
    status: "created",
    started_at: null,
    ended_at: null,
    duration_s: null,
    webcam_present: false,
    chunk_count: 0,
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-01T00:00:00Z",
    questions: [
      {
        id: "q1",
        session_id: "sess-1",
        sort_order: 0,
        question_text: "Describe the overall architecture of your project.",
        target_ref: { kind: "architecture" },
        claim_ids: [],
        asked_at_s: null,
        answered: false,
        created_at: "2026-06-01T00:00:00Z",
      },
    ],
    ...overrides,
  }
}

const getDisplayMedia = vi.fn()
const getUserMedia = vi.fn()

beforeEach(() => {
  vi.mocked(getVBRSession).mockReset().mockResolvedValue(makeSession())
  vi.mocked(getVBRProject).mockReset().mockResolvedValue(null)

  getDisplayMedia.mockReset().mockRejectedValue(new Error("Permission denied"))
  getUserMedia.mockReset().mockRejectedValue(new Error("Permission denied"))

  Object.defineProperty(navigator, "mediaDevices", {
    value: { getDisplayMedia, getUserMedia },
    configurable: true,
    writable: true,
  })
})

describe("ProjectDefenseRecordPage", () => {
  it("renders Project Defense recording copy and does not claim a completed public report", async () => {
    render(<ProjectDefenseRecordPage />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    expect(screen.getAllByText(/project defense recording/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/record your screen and microphone while answering your defense questions/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/camera is optional/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/protected evidence for your skill graph/i).length).toBeGreaterThan(0)

    const text = document.body.textContent ?? ""
    expect(text).not.toMatch(/team proof/i)
    expect(text).not.toMatch(/diariz/i)
    expect(text).not.toMatch(/final (public )?report (is )?complete/i)
    expect(text).not.toMatch(/\bis fully verified\b/i)
    expect(text).not.toMatch(/(project|student|skill) (is|are) (now |fully )?verified/i)
  })

  it("presents the camera permission check as optional and does not block recording on it", async () => {
    render(<ProjectDefenseRecordPage />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    expect(screen.getByRole("button", { name: /test camera permission \(optional\)/i })).toBeInTheDocument()

    // Recording start is gated on consent, not on any camera permission state.
    const startButton = screen.getByRole("button", { name: /start recording session/i })
    expect(startButton).toBeDisabled()
    fireEvent.click(screen.getByRole("button", { name: /i consent to record this session/i }))
    await waitFor(() => expect(startButton).not.toBeDisabled())
  })

  it("shows a friendly permission-denied message for screen share without exposing storage internals", async () => {
    render(<ProjectDefenseRecordPage />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: /test screen share permission/i }))

    await waitFor(() => expect(screen.getByText(/permission denied/i)).toBeInTheDocument())

    const text = document.body.textContent ?? ""
    expect(text).not.toMatch(/vbr\/sessions/)
    expect(text).not.toMatch(/storage_path/i)
    expect(text).not.toMatch(/signed_url/i)
    expect(text).not.toMatch(/https?:\/\/storage/i)
  })

  it("never renders storage paths, signed URLs, or upload tokens", async () => {
    render(<ProjectDefenseRecordPage />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    const text = document.body.textContent ?? ""
    expect(text).not.toMatch(/vbr\/sessions/)
    expect(text).not.toMatch(/storage_path/i)
    expect(text).not.toMatch(/signed_url/i)
    expect(text).not.toMatch(/signedUrl/)
    expect(text).not.toMatch(/token=/i)
    expect(text).not.toMatch(/\.webm/)
  })

  it("keeps the manual pasted-transcript fallback reachable from the recorder", async () => {
    render(<ProjectDefenseRecordPage />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    expect(screen.getByText(/paste your explanation instead/i)).toBeInTheDocument()

    const links = screen.getAllByRole("link", { name: /project defense/i })
    expect(links.length).toBeGreaterThan(0)
    links.forEach((link) => expect(link).toHaveAttribute("href", "/student/proofs/project-defense"))
  })
})
