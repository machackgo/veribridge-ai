/**
 * Website / Live App Proof — focused workflow-evidence experience.
 *
 * The Website Proof results page is intentionally simplified to the recorded
 * website workflow only. This suite pins down two things:
 *
 *   1. WorkflowRecordingSection — the secure "Workflow Recording" replay player
 *      renders each state correctly (loading → available / processing /
 *      unavailable / error-with-retry), streams through the access-gated API
 *      helper, and never exposes a raw/public URL.
 *
 *   2. Composition — the panel no longer mounts the unrelated proof sections
 *      (GitHub Evidence, Project Defense, optional documents, combined Final
 *      Evidence Score, grouped skill profile, recommended next actions,
 *      Verification Review) and does not auto-run the combined final evaluator,
 *      while it DOES keep the workflow analysis + recording player.
 */

import { readFileSync } from "node:fs"
import { join } from "node:path"

import { render, screen, fireEvent } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"

vi.mock("@/lib/api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api")>()),
  fetchWebsiteProofReplayStatus: vi.fn(),
}))

import { fetchWebsiteProofReplayStatus, type WebsiteProofReplayStatus } from "@/lib/api"
import {
  WorkflowRecordingSection,
  WebsiteProofSavedBanner,
} from "../../components/skill-proof/extension-proof-panel"

const mockedFetchStatus = vi.mocked(fetchWebsiteProofReplayStatus)

const PANEL_SOURCE = readFileSync(
  join(process.cwd(), "components/skill-proof/extension-proof-panel.tsx"),
  "utf8",
)

function _statusData(overrides: Partial<WebsiteProofReplayStatus>): WebsiteProofReplayStatus {
  return {
    session_id: "s1",
    recording_state: "not_retained",
    replay_available: false,
    signed_url: null,
    expires_at: null,
    expires_in_seconds: null,
    duration_seconds: null,
    mime_type: null,
    artifact_id: null,
    message: "",
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe("WorkflowRecordingSection — secure replay states", () => {
  it("does not render (and makes no request) before the proof is uploaded", () => {
    render(<WorkflowRecordingSection sessionId="s1" sessionStatus="recording" />)
    expect(screen.queryByText("Workflow Recording")).not.toBeInTheDocument()
    expect(mockedFetchStatus).not.toHaveBeenCalled()
  })

  it("shows the video player with the signed URL when the recording is ready", async () => {
    mockedFetchStatus.mockResolvedValue({
      status: "ok",
      data: _statusData({
        recording_state: "ready",
        replay_available: true,
        signed_url: "https://project.supabase.co/storage/v1/object/sign/tok",
        duration_seconds: 83,
        mime_type: "video/webm",
      }),
    })
    render(<WorkflowRecordingSection sessionId="s1" sessionStatus="completed" />)

    const video = await screen.findByTestId("workflow-recording-video")
    expect(video).toHaveAttribute("src", "https://project.supabase.co/storage/v1/object/sign/tok")
    expect(video).toHaveAttribute("controls")
    // No autoplay; duration is shown; no private storage path in the DOM.
    expect(video).not.toHaveAttribute("autoplay")
    expect(screen.getByTestId("workflow-recording-duration")).toHaveTextContent("1:23")
    expect(document.body.innerHTML).not.toContain("proof-artifacts/")
    expect(mockedFetchStatus).toHaveBeenCalledWith("s1")
  })

  it("shows a processing state while the session is still analyzing and nothing is retained yet", async () => {
    mockedFetchStatus.mockResolvedValue({ status: "ok", data: _statusData({ recording_state: "not_retained" }) })
    render(<WorkflowRecordingSection sessionId="s1" sessionStatus="analyzing" />)
    expect(await screen.findByTestId("workflow-recording-processing")).toBeInTheDocument()
    // The contradiction is impossible: processing state shows no "no video" copy.
    expect(screen.queryByTestId("workflow-recording-unavailable")).not.toBeInTheDocument()
  })

  it("shows an honest 'not retained' state when completed and no recording exists", async () => {
    mockedFetchStatus.mockResolvedValue({ status: "ok", data: _statusData({ recording_state: "not_retained" }) })
    render(<WorkflowRecordingSection sessionId="s1" sessionStatus="completed" />)
    const el = await screen.findByTestId("workflow-recording-unavailable")
    expect(el).toHaveTextContent(/not retained/i)
    expect(screen.queryByTestId("workflow-recording-processing")).not.toBeInTheDocument()
  })

  it("shows an error with Retry on status failure, then refreshes the signed URL", async () => {
    mockedFetchStatus.mockResolvedValueOnce({ status: "error", message: "Recording status unavailable (HTTP 503)." })
    render(<WorkflowRecordingSection sessionId="s1" sessionStatus="completed" />)

    const err = await screen.findByTestId("workflow-recording-error")
    expect(err).toHaveTextContent("Recording status unavailable (HTTP 503).")

    // Retry succeeds with a fresh signed URL → player appears (expired-link recovery).
    mockedFetchStatus.mockResolvedValueOnce({
      status: "ok",
      data: _statusData({
        recording_state: "ready",
        replay_available: true,
        signed_url: "https://project.supabase.co/storage/v1/object/sign/fresh",
      }),
    })
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(await screen.findByTestId("workflow-recording-video")).toHaveAttribute(
      "src",
      "https://project.supabase.co/storage/v1/object/sign/fresh",
    )
    expect(mockedFetchStatus).toHaveBeenCalledTimes(2)
  })
})

describe("WebsiteProofSavedBanner — explicit auto-saved confirmation", () => {
  it("states the proof is saved automatically with a timestamp and offers Proof Center", () => {
    const onView = vi.fn()
    render(<WebsiteProofSavedBanner savedAt="2026-07-09T12:00:00Z" onViewProofCenter={onView} />)
    expect(screen.getByTestId("website-proof-saved-banner")).toHaveTextContent(/saved/i)
    expect(screen.getByTestId("website-proof-saved-banner")).toHaveTextContent(/automatically/i)
    fireEvent.click(screen.getByTestId("website-proof-view-proof-center"))
    expect(onView).toHaveBeenCalledTimes(1)
  })

  it("renders safely without a timestamp", () => {
    render(<WebsiteProofSavedBanner savedAt={null} onViewProofCenter={() => undefined} />)
    expect(screen.getByTestId("website-proof-saved-banner")).toBeInTheDocument()
  })
})

describe("Website Proof composition — unrelated sections removed", () => {
  const removedInComposition = [
    ["GitHub Evidence", /<GitHubAnalysisCard[\s>]/],
    ["GitHub in-progress", /<GitHubAnalysisInProgress[\s>]/],
    ["Project Defense", /<ProjectDefenseSection[\s>]/],
    ["Optional Evidence Boosters / documents", /<FutureProofModulesSection[\s>]/],
    ["combined Final Evidence Score", /<FinalEvaluatorCard[\s>]/],
    ["grouped skill profile", /<DetectedSkillProfileSection[\s>]/],
    ["Recommended Next Actions / Learning Opportunities", /<FinalRecommendationsSection[\s>]/],
    ["Verification Review / Submit for review", /<VerificationReviewSection[\s>]/],
  ] as const

  for (const [label, pattern] of removedInComposition) {
    it(`does not mount ${label}`, () => {
      expect(PANEL_SOURCE).not.toMatch(pattern)
    })
  }

  it("keeps the workflow analysis card, recording player, and saved confirmation", () => {
    expect(PANEL_SOURCE).toMatch(/<WorkflowAnalysisCard[\s>]/)
    expect(PANEL_SOURCE).toMatch(/<WorkflowRecordingSection[\s>]/)
    expect(PANEL_SOURCE).toMatch(/<WebsiteProofSavedBanner[\s>]/)
  })

  it("does not auto-run the combined final evaluator on this page", () => {
    // handleRunFinalEval must no longer be invoked anywhere in the composition.
    expect(PANEL_SOURCE).not.toMatch(/void handleRunFinalEval\(\)/)
  })

  it("filters GitHub and Final Verification out of the workflow checklist", () => {
    expect(PANEL_SOURCE).toMatch(/item\.key !== "github" && item\.key !== "final"/)
  })
})
