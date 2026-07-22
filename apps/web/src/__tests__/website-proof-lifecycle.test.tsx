import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

// ── Route / navigation mock ───────────────────────────────────────────────────
// The Website Proof lifecycle is driven by the route: an explicit session_id in
// the query opens "view saved proof" mode, its absence keeps the panel in fresh
// "new proof" mode. These helpers let each test control the query and observe
// the router.replace calls the panel makes to sync the active session into the URL.
const {
  routerReplace,
  routerPush,
  getExtensionProofSession,
  createSkillEvidence,
  createExtensionProofSession,
  syncWebsiteProofToSkillGraph,
} = vi.hoisted(() => ({
  routerReplace: vi.fn(),
  routerPush: vi.fn(),
  getExtensionProofSession: vi.fn(),
  createSkillEvidence: vi.fn(),
  createExtensionProofSession: vi.fn(),
  syncWebsiteProofToSkillGraph: vi.fn().mockResolvedValue(undefined),
}))

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace, push: routerPush }),
}))

// ── API mock ──────────────────────────────────────────────────────────────────
// Preserve the real module (types + untouched helpers) and override only the
// network-touching functions the lifecycle exercises so nothing hits fetch.
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

import {
  ExtensionProofPanel,
  saveActiveExtensionProofSession,
  loadActiveExtensionProofSession,
} from "../../components/skill-proof/extension-proof-panel"
import type { ExtensionProofSessionResponse, ExtensionProofSessionStatus } from "../lib/api"

const STALE_ID = "fdb305b6-59ae-4228-abc3-1c1971ace439"

function makeSession(
  id: string,
  status: ExtensionProofSessionStatus,
): ExtensionProofSessionResponse {
  return {
    id,
    user_id: "u1",
    skill_evidence_id: "ev1",
    status,
    started_at: status === "created" ? null : "2026-07-09T00:00:00.000Z",
    proof_upload_id: status === "completed" ? "up1" : null,
    created_at: "2026-07-09T00:00:00.000Z",
    updated_at: "2026-07-09T00:00:00.000Z",
  }
}

function seedStaleDraft(id = STALE_ID) {
  saveActiveExtensionProofSession({
    sessionId: id,
    form: {
      websiteUrl: "https://old-project.vercel.app",
      githubUrl: "https://github.com/old/repo",
      skillName: "Old Skill",
      proofObjective: "Old completed proof objective that should never auto restore",
    },
    savedAt: "2026-07-08T00:00:00.000Z",
  })
}

beforeEach(() => {
  // The Session ID row these tests key on is dev/debug-only in the simplified
  // workflow panel — render as the dev build so session identity stays assertable.
  vi.stubEnv("NODE_ENV", "development")
  routerReplace.mockClear()
  routerPush.mockClear()
  getExtensionProofSession.mockReset()
  createSkillEvidence.mockReset()
  createExtensionProofSession.mockReset()
  syncWebsiteProofToSkillGraph.mockClear()
  localStorage.clear()
  sessionStorage.clear()
  window.history.replaceState({}, "", "/student/proofs/website")
})

afterEach(() => {
  vi.unstubAllEnvs()
  localStorage.clear()
  sessionStorage.clear()
})

describe("Website Proof lifecycle — new vs existing mode", () => {
  it("base route (no session id) shows the blank new-proof form", () => {
    render(<ExtensionProofPanel onBack={() => undefined} initialSessionId={null} />)
    expect(screen.getByText("Create Website Proof Session")).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/https:\/\/your-project\.vercel\.app/i)).toHaveValue("")
    expect(screen.getByPlaceholderText("e.g. FastAPI, React, Machine Learning")).toHaveValue("")
  })

  it("base route does NOT auto-fetch a prior/latest session", () => {
    render(<ExtensionProofPanel onBack={() => undefined} initialSessionId={null} />)
    expect(getExtensionProofSession).not.toHaveBeenCalled()
  })

  it("stale localStorage draft never overrides new-proof route mode (the reported bug)", () => {
    seedStaleDraft()
    render(<ExtensionProofPanel onBack={() => undefined} initialSessionId={null} />)
    // The completed session must not be restored: no fetch, no session card, blank form.
    expect(getExtensionProofSession).not.toHaveBeenCalled()
    expect(screen.queryByText("Session ID")).not.toBeInTheDocument()
    expect(screen.getByText("Create Website Proof Session")).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/https:\/\/your-project\.vercel\.app/i)).toHaveValue("")
  })

  it("explicit saved-session route loads exactly that session (Proof Center reopen)", async () => {
    getExtensionProofSession.mockResolvedValue(makeSession("sess-A", "completed"))
    render(<ExtensionProofPanel onBack={() => undefined} initialSessionId="sess-A" />)
    await waitFor(() => {
      expect(getExtensionProofSession).toHaveBeenCalledWith("sess-A")
    })
    // The saved proof's session card renders (not the blank create form).
    expect(await screen.findByText("Session ID")).toBeInTheDocument()
    expect(screen.queryByText("Create Website Proof Session")).not.toBeInTheDocument()
  })

  it("stale draft for a DIFFERENT session does not hijack an explicit reopen", async () => {
    seedStaleDraft(STALE_ID)
    getExtensionProofSession.mockResolvedValue(makeSession("sess-A", "recording"))
    render(<ExtensionProofPanel onBack={() => undefined} initialSessionId="sess-A" />)
    await waitFor(() => {
      expect(getExtensionProofSession).toHaveBeenCalledWith("sess-A")
    })
    expect(getExtensionProofSession).not.toHaveBeenCalledWith(STALE_ID)
  })

  it("refresh on an explicit in-progress session URL resumes that session", async () => {
    getExtensionProofSession.mockResolvedValue(makeSession("sess-recording", "recording"))
    render(<ExtensionProofPanel onBack={() => undefined} initialSessionId="sess-recording" />)
    await waitFor(() => {
      expect(getExtensionProofSession).toHaveBeenCalledWith("sess-recording")
    })
  })

  it("back to the bare base route drops the previously-shown session (no cross-contamination)", async () => {
    getExtensionProofSession.mockResolvedValue(makeSession("sess-A", "completed"))
    const { rerender } = render(
      <ExtensionProofPanel onBack={() => undefined} initialSessionId="sess-A" />,
    )
    expect(await screen.findByText("Session ID")).toBeInTheDocument()

    // Simulate browser back/forward to the base route (query cleared, no remount).
    await act(async () => {
      rerender(<ExtensionProofPanel onBack={() => undefined} initialSessionId={null} />)
    })
    await waitFor(() => {
      expect(screen.queryByText("Session ID")).not.toBeInTheDocument()
    })
    expect(screen.getByText("Create Website Proof Session")).toBeInTheDocument()
  })
})

describe("Website Proof lifecycle — creation & completion transitions", () => {
  it("creating a proof does NOT write its session id into the route (base route stays new-proof)", async () => {
    createSkillEvidence.mockResolvedValue({ id: "ev-new" })
    createExtensionProofSession.mockResolvedValue(makeSession("new-uuid", "created"))

    render(<ExtensionProofPanel onBack={() => undefined} initialSessionId={null} />)

    fireEvent.change(screen.getByPlaceholderText(/https:\/\/your-project\.vercel\.app/i), {
      target: { value: "https://new-project.vercel.app" },
    })
    fireEvent.change(screen.getByPlaceholderText("e.g. FastAPI, React, Machine Learning"), {
      target: { value: "React, Next.js" },
    })
    fireEvent.change(screen.getByPlaceholderText(/Describe what you'll walk through/i), {
      target: { value: "Demonstrate the live dashboard workflow end to end here" },
    })
    // Acknowledge Privacy Guard so the create button is enabled.
    fireEvent.click(
      screen.getByText(/I understand and will avoid showing sensitive information/i),
    )

    fireEvent.click(screen.getByText("Create Website Proof Session"))

    await waitFor(() => {
      expect(createExtensionProofSession).toHaveBeenCalled()
    })
    // A self-created session is driven from React state and must NOT be pushed
    // into the URL — otherwise its id lingers after completion and a refresh or a
    // reopened tab resurrects the finished proof instead of a blank form.
    expect(routerReplace).not.toHaveBeenCalledWith(
      expect.stringContaining("session_id=new-uuid"),
    )
  })

  it("a new proof shows the backend-issued UUID, not any previously stored id", async () => {
    seedStaleDraft() // stale draft for STALE_ID must not leak into the new proof
    createSkillEvidence.mockResolvedValue({ id: "ev-new" })
    const NEW_ID = "0f3f2b1a-9c67-4a4e-8f21-2d5f4be0c001"
    createExtensionProofSession.mockResolvedValue(makeSession(NEW_ID, "created"))

    render(<ExtensionProofPanel onBack={() => undefined} initialSessionId={null} />)

    fireEvent.change(screen.getByPlaceholderText(/https:\/\/your-project\.vercel\.app/i), {
      target: { value: "https://new-project.vercel.app" },
    })
    fireEvent.change(screen.getByPlaceholderText("e.g. FastAPI, React, Machine Learning"), {
      target: { value: "React" },
    })
    fireEvent.change(screen.getByPlaceholderText(/Describe what you'll walk through/i), {
      target: { value: "Demonstrate the live dashboard workflow end to end here" },
    })
    fireEvent.click(
      screen.getByText(/I understand and will avoid showing sensitive information/i),
    )
    await act(async () => {
      fireEvent.click(screen.getByText("Create Website Proof Session"))
    })

    // The session card shows the truncated backend UUID — not the stale one.
    expect(await screen.findByText(NEW_ID.slice(0, 18) + "…")).toBeInTheDocument()
    expect(screen.queryByText(STALE_ID.slice(0, 18) + "…")).not.toBeInTheDocument()
  })

  it("'Add another Website Proof' clears the finished session and returns to a blank form", async () => {
    // The active session is reflected in the URL, matching the real route.
    window.history.replaceState({}, "", "/student/proofs/website?session_id=sess-done")
    getExtensionProofSession.mockResolvedValue(makeSession("sess-done", "completed"))
    render(<ExtensionProofPanel onBack={() => undefined} initialSessionId="sess-done" />)

    const addAnother = await screen.findByText("Add another Website Proof")
    await act(async () => {
      fireEvent.click(addAnother)
    })

    // The completed proof is synced to the profile, the transient session state is
    // cleared (localStorage draft gone), and the URL session_id is stripped so the
    // base route can't re-hydrate the just-finished proof.
    await waitFor(() => {
      expect(syncWebsiteProofToSkillGraph).toHaveBeenCalledWith("sess-done")
    })
    await waitFor(() => {
      expect(screen.getByText("Create Website Proof Session")).toBeInTheDocument()
    })
    expect(loadActiveExtensionProofSession()).toBeNull()
    expect(routerReplace).toHaveBeenCalledWith("/student/proofs/website")
  })
})

describe("Website Proof lifecycle — stale-source immunity and async races", () => {
  it("base route ignores stale sessionStorage keys from prior recorder/proof flows", () => {
    sessionStorage.setItem(
      "vb_recorder_session",
      JSON.stringify({ sessionId: STALE_ID, status: "completed" }),
    )
    sessionStorage.setItem("vb_last_proof_session_id", STALE_ID)
    render(<ExtensionProofPanel onBack={() => undefined} initialSessionId={null} />)
    expect(getExtensionProofSession).not.toHaveBeenCalled()
    expect(screen.getByText("Create Website Proof Session")).toBeInTheDocument()
    expect(screen.queryByText("Session ID")).not.toBeInTheDocument()
  })

  it("base route ignores a session id smuggled through window.history.state", () => {
    window.history.replaceState(
      { sessionId: STALE_ID, session_id: STALE_ID },
      "",
      "/student/proofs/website",
    )
    seedStaleDraft()
    render(<ExtensionProofPanel onBack={() => undefined} initialSessionId={null} />)
    expect(getExtensionProofSession).not.toHaveBeenCalled()
    expect(screen.getByText("Create Website Proof Session")).toBeInTheDocument()
  })

  it("a late polling response cannot revive the old session after returning to the base route", async () => {
    vi.useFakeTimers()
    try {
      getExtensionProofSession.mockResolvedValueOnce(makeSession("sess-poll", "recording"))
      const { rerender } = render(
        <ExtensionProofPanel onBack={() => undefined} initialSessionId="sess-poll" />,
      )
      // Flush the initial explicit-session load.
      await act(async () => { await vi.advanceTimersByTimeAsync(0) })
      expect(getExtensionProofSession).toHaveBeenCalledWith("sess-poll")

      // Arm the next poll tick with a response we control.
      let resolveLate: (v: ReturnType<typeof makeSession>) => void = () => undefined
      getExtensionProofSession.mockImplementationOnce(
        () => new Promise((resolve) => { resolveLate = resolve }),
      )
      // Fire the 3s poll — its fetch is now in flight.
      await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
      expect(getExtensionProofSession).toHaveBeenCalledTimes(2)

      // User navigates back to the bare base route while the poll is in flight.
      await act(async () => {
        rerender(<ExtensionProofPanel onBack={() => undefined} initialSessionId={null} />)
      })
      expect(screen.getByText("Create Website Proof Session")).toBeInTheDocument()

      // The old session's poll answer arrives late — it must lose.
      await act(async () => { resolveLate(makeSession("sess-poll", "completed")) })
      expect(screen.queryByText("Session ID")).not.toBeInTheDocument()
      expect(screen.getByText("Create Website Proof Session")).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it("bfcache pageshow does not revive a finished proof on the base route", async () => {
    createSkillEvidence.mockResolvedValue({ id: "ev-new" })
    // The session comes back already completed — the same shape bfcache restores:
    // completed proof state in memory while the URL is the bare base route.
    createExtensionProofSession.mockResolvedValue(makeSession("sess-bf", "completed"))

    render(<ExtensionProofPanel onBack={() => undefined} initialSessionId={null} />)
    fireEvent.change(screen.getByPlaceholderText(/https:\/\/your-project\.vercel\.app/i), {
      target: { value: "https://new-project.vercel.app" },
    })
    fireEvent.change(screen.getByPlaceholderText("e.g. FastAPI, React, Machine Learning"), {
      target: { value: "React" },
    })
    fireEvent.change(screen.getByPlaceholderText(/Describe what you'll walk through/i), {
      target: { value: "Demonstrate the live dashboard workflow end to end here" },
    })
    fireEvent.click(
      screen.getByText(/I understand and will avoid showing sensitive information/i),
    )
    await act(async () => {
      fireEvent.click(screen.getByText("Create Website Proof Session"))
    })
    expect(await screen.findByText("Session ID")).toBeInTheDocument()

    // Simulate the browser restoring this page from the back/forward cache.
    await act(async () => {
      const pageshow = new Event("pageshow")
      Object.defineProperty(pageshow, "persisted", { value: true })
      window.dispatchEvent(pageshow)
    })

    expect(screen.queryByText("Session ID")).not.toBeInTheDocument()
    expect(screen.getByText("Create Website Proof Session")).toBeInTheDocument()
    expect(loadActiveExtensionProofSession()).toBeNull()
  })
})
