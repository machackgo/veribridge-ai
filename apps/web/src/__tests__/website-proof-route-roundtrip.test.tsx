import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { useSyncExternalStore } from "react"

// ── Realistic route store ─────────────────────────────────────────────────────
// Unlike the unit test, router.replace/push here actually mutate window.location
// and notify subscribers, so useSearchParams reflects the new URL — exactly like
// the real app. This exposes lifecycle bugs the no-op-router unit test cannot.
const listeners = new Set<() => void>()
function emit() { listeners.forEach((l) => l()) }
function navigate(url: string) {
  window.history.replaceState({}, "", url)
  emit()
}
const routerReplace = vi.fn((url: string) => navigate(url))
const routerPush = vi.fn((url: string) => navigate(url))

function useSearchString(): string {
  return useSyncExternalStore(
    (cb: () => void) => { listeners.add(cb); return () => listeners.delete(cb) },
    () => window.location.search,
    () => "",
  )
}
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace, push: routerPush }),
  useSearchParams: () => new URLSearchParams(useSearchString()),
}))

// useSearchParams must return something with .get(); wrap the search string.
vi.mock("../../components/passport/safe-return", () => ({
  readReturnToFromLocation: () => null,
}))

const {
  getExtensionProofSession,
  createSkillEvidence,
  createExtensionProofSession,
  syncWebsiteProofToSkillGraph,
} = vi.hoisted(() => ({
  getExtensionProofSession: vi.fn(),
  createSkillEvidence: vi.fn(),
  createExtensionProofSession: vi.fn(),
  syncWebsiteProofToSkillGraph: vi.fn().mockResolvedValue(undefined),
}))

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>()
  return {
    ...actual,
    getExtensionProofSession,
    createSkillEvidence,
    createExtensionProofSession,
    syncWebsiteProofToSkillGraph,
    getWorkflowAnalysis: vi.fn().mockResolvedValue(null),
    getLiveWebsiteCheck: vi.fn().mockResolvedValue(null),
    getExtensionProofGitHubAnalysis: vi.fn().mockResolvedValue(null),
    getWorkflowPrivacyScan: vi.fn().mockResolvedValue(null),
    getReviewStatus: vi.fn().mockResolvedValue(null),
    submitForAiReview: vi.fn().mockResolvedValue(null),
  }
})

import WebsiteProofPage from "../app/student/proofs/website/page"
import { saveActiveExtensionProofSession } from "../../components/skill-proof/extension-proof-panel"
import type { ExtensionProofSessionResponse, ExtensionProofSessionStatus } from "../lib/api"

function makeSession(id: string, status: ExtensionProofSessionStatus): ExtensionProofSessionResponse {
  return {
    id, user_id: "u1", skill_evidence_id: "ev1", status,
    started_at: status === "created" ? null : "2026-07-09T00:00:00.000Z",
    proof_upload_id: status === "completed" ? "up1" : null,
    created_at: "2026-07-09T00:00:00.000Z", updated_at: "2026-07-09T00:00:00.000Z",
  }
}

beforeEach(() => {
  // The Session ID row these tests key on is dev/debug-only in the simplified
  // workflow panel — render as the dev build so session identity stays assertable.
  vi.stubEnv("NODE_ENV", "development")
  routerReplace.mockClear(); routerPush.mockClear()
  getExtensionProofSession.mockReset(); createSkillEvidence.mockReset(); createExtensionProofSession.mockReset()
  syncWebsiteProofToSkillGraph.mockClear()
  localStorage.clear(); sessionStorage.clear()
  window.history.replaceState({}, "", "/student/proofs/website")
})
afterEach(() => { vi.unstubAllEnvs(); localStorage.clear(); sessionStorage.clear() })

// Companion to website-proof-lifecycle.test.tsx: that suite drives the panel
// with a manual prop and a no-op router. This one wires router.replace/push to
// actually mutate the URL that useSearchParams reads, so it catches lifecycle
// bugs that only surface across a real navigation / hard refresh.
describe("Website Proof — fresh-session navigation with a real URL round-trip", () => {
  it("after completing a session (session_id in URL), navigating to the bare base route shows blank form", async () => {
    // Seed a completed session in the URL + localStorage, like the real app leaves it.
    saveActiveExtensionProofSession({
      sessionId: "sess-done",
      form: { websiteUrl: "https://old.vercel.app", githubUrl: "", skillName: "Old", proofObjective: "old proof" },
      savedAt: "2026-07-08T00:00:00.000Z",
    })
    window.history.replaceState({}, "", "/student/proofs/website?session_id=sess-done")
    getExtensionProofSession.mockResolvedValue(makeSession("sess-done", "completed"))

    const { rerender } = render(<WebsiteProofPage />)
    // The saved completed session loads (explicit route).
    expect(await screen.findByText("Session ID")).toBeInTheDocument()

    // User clicks an in-app "Add another Website Proof" link → bare base route.
    await act(async () => { navigate("/student/proofs/website") })
    rerender(<WebsiteProofPage />)

    await waitFor(() => {
      expect(screen.getByText("Create Website Proof Session")).toBeInTheDocument()
    })
    expect(screen.queryByText("Session ID")).not.toBeInTheDocument()
  })

  it("reopen a saved proof via ?session_id, then Save & add another → bare URL, blank form, no reload", async () => {
    window.history.replaceState({}, "", "/student/proofs/website?session_id=sess-done")
    getExtensionProofSession.mockResolvedValue(makeSession("sess-done", "completed"))

    render(<WebsiteProofPage />)
    expect(await screen.findByText("Session ID")).toBeInTheDocument()

    getExtensionProofSession.mockClear()
    const addAnother = await screen.findByText("Add another Website Proof")
    await act(async () => { fireEvent.click(addAnother) })

    await waitFor(() => { expect(syncWebsiteProofToSkillGraph).toHaveBeenCalledWith("sess-done") })
    await waitFor(() => { expect(screen.getByText("Create Website Proof Session")).toBeInTheDocument() })
    // URL stripped back to the base route, and the just-finished session is not
    // re-fetched by the load effect during the URL-clear render gap.
    expect(window.location.search).not.toContain("session_id")
    expect(getExtensionProofSession).not.toHaveBeenCalled()
  })

  it("a slow saved-session load cannot repopulate the base route after navigating away", async () => {
    window.history.replaceState({}, "", "/student/proofs/website?session_id=sess-slow")
    let resolveLate: (v: ExtensionProofSessionResponse) => void = () => undefined
    getExtensionProofSession.mockImplementationOnce(
      () => new Promise<ExtensionProofSessionResponse>((resolve) => { resolveLate = resolve }),
    )

    const { rerender } = render(<WebsiteProofPage />)
    expect(getExtensionProofSession).toHaveBeenCalledWith("sess-slow")

    // The load is still in flight when the user navigates to the bare base route.
    await act(async () => { navigate("/student/proofs/website") })
    rerender(<WebsiteProofPage />)
    await waitFor(() => {
      expect(screen.getByText("Create Website Proof Session")).toBeInTheDocument()
    })

    // The old session's response arrives late — the base route must stay blank.
    await act(async () => { resolveLate(makeSession("sess-slow", "completed")) })
    expect(screen.queryByText("Session ID")).not.toBeInTheDocument()
    expect(screen.getByText("Create Website Proof Session")).toBeInTheDocument()

    // And it must stay blank 'later' too — nothing queued can flip it back.
    await act(async () => { await new Promise((r) => setTimeout(r, 50)) })
    expect(screen.queryByText("Session ID")).not.toBeInTheDocument()
  })

  it("create a proof, then hard-refresh — the tab must NOT resurrect the finished session", async () => {
    createSkillEvidence.mockResolvedValue({ id: "ev-new" })
    createExtensionProofSession.mockResolvedValue(makeSession("new-uuid", "created"))
    getExtensionProofSession.mockResolvedValue(makeSession("new-uuid", "completed"))

    const { unmount } = render(<WebsiteProofPage />)

    fireEvent.change(screen.getByPlaceholderText(/https:\/\/your-project\.vercel\.app/i), { target: { value: "https://new.vercel.app" } })
    fireEvent.change(screen.getByPlaceholderText("e.g. FastAPI, React, Machine Learning"), { target: { value: "React" } })
    fireEvent.change(screen.getByPlaceholderText(/Describe what you'll walk through/i), { target: { value: "Demonstrate the live dashboard workflow end to end here" } })
    fireEvent.click(screen.getByText(/I understand and will avoid showing sensitive information/i))

    await act(async () => { fireEvent.click(screen.getByText("Create Website Proof Session")) })
    await waitFor(() => { expect(createExtensionProofSession).toHaveBeenCalled() })

    // A self-created session must NOT be written into the URL — otherwise a refresh
    // or a reopened tab lands on ?session_id=X and resurrects the finished proof.
    expect(window.location.search).not.toContain("session_id")

    // Simulate a hard refresh: unmount, then remount at whatever URL the tab holds.
    getExtensionProofSession.mockClear()
    unmount()
    render(<WebsiteProofPage />)
    // Blank create form, and no attempt to reload the previous session.
    expect(await screen.findByText("Create Website Proof Session")).toBeInTheDocument()
    expect(getExtensionProofSession).not.toHaveBeenCalled()
  })
})
