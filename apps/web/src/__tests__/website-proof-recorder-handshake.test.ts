// Handshake classification tests for initializeWebsiteProofRecorder.
// Simulates the extension side by dispatching same-window MessageEvents,
// verifying correlation matching, stale-build fail-fast, worker-unreachable
// classification, deadline behavior, and late-response acceptance.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const OWNER_USER_ID = "42b0fe06-b9f3-4809-8647-2008ee7b678f"

vi.mock("@/lib/supabase/client", () => ({
  createSupabaseBrowserClient: () => ({
    auth: {
      getSession: async () => ({
        data: {
          session: {
            access_token: "test-access-token",
            expires_at: Math.floor(Date.now() / 1000) + 3600,
            user: { id: OWNER_USER_ID },
          },
        },
      }),
    },
  }),
}))

import {
  RECORDER_BRIDGE_PING,
  RECORDER_BRIDGE_PONG,
  RECORDER_INIT_ACK,
  RECORDER_INIT_NACK,
  RECORDER_INIT_REQUEST,
  WEBSITE_PROOF_RECORDER_BUILD_VERSION,
  WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
} from "../../../../packages/shared/websiteProofRecorderContract"
import {
  initializeWebsiteProofRecorder,
  type RecorderSessionInput,
} from "@/lib/website-proof-recorder"

const input: RecorderSessionInput = {
  config_revision: 1,
  session_id: "session-handshake-1",
  owner_user_id: OWNER_USER_ID,
  project_id: null,
  website_url: "https://reactplay.io",
  repository_url: "https://github.com/reactplay/react-play",
  claimed_skills: ["React", "JavaScript"],
  proof_objective: "Demonstrate the ReactPlay browsing workflow end to end.",
  created_at: new Date().toISOString(),
}

type SentMessage = { source?: string; type?: string; payload?: Record<string, unknown> }

let sentToExtension: SentMessage[]
let removeCapture: (() => void) | null

function captureAppMessages() {
  sentToExtension = []
  const listener = (event: MessageEvent) => {
    const data = event.data as SentMessage
    if (data?.source === "veribridge-app") sentToExtension.push(data)
  }
  window.addEventListener("message", listener)
  removeCapture = () => window.removeEventListener("message", listener)
}

function extensionReply(type: string, payload: Record<string, unknown>) {
  window.dispatchEvent(new MessageEvent("message", {
    source: window,
    origin: window.location.origin,
    data: { source: "veribridge-extension", type, payload },
  }))
}

function lastRequestId(messageType: string): string {
  const request = [...sentToExtension].reverse().find((m) => m.type === messageType)
  return String(request?.payload?.request_id ?? "")
}

async function flushPosts() {
  // window.postMessage delivery in jsdom is queued as its own task after the
  // sender's timer fires; advance in small steps so both the app's 0ms send
  // timers AND the queued deliveries land before the test replies.
  for (let i = 0; i < 6; i++) await vi.advanceTimersByTimeAsync(20)
}

beforeEach(() => {
  vi.useFakeTimers()
  captureAppMessages()
})

afterEach(() => {
  removeCapture?.()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

function validAck(requestId: string): Record<string, unknown> {
  return {
    request_id: requestId,
    session_id: input.session_id,
    config_revision: input.config_revision,
    api_base_url: "http://localhost:8128",
    schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    build_version: WEBSITE_PROOF_RECORDER_BUILD_VERSION,
    extension_id: "ext-under-test",
    ready: true,
  }
}

describe("initializeWebsiteProofRecorder", () => {
  it("succeeds on a correlation-matched acknowledgement", async () => {
    const promise = initializeWebsiteProofRecorder(input)
    await flushPosts()
    extensionReply(RECORDER_INIT_ACK, validAck(lastRequestId(RECORDER_INIT_REQUEST)))
    const result = await promise
    expect(result.ok).toBe(true)
  })

  it("ignores acknowledgements with a foreign correlation id, then accepts the matching one", async () => {
    const promise = initializeWebsiteProofRecorder(input)
    await flushPosts()
    extensionReply(RECORDER_INIT_ACK, validAck("some-other-request"))
    await vi.advanceTimersByTimeAsync(500)
    extensionReply(RECORDER_INIT_ACK, validAck(lastRequestId(RECORDER_INIT_REQUEST)))
    const result = await promise
    expect(result.ok).toBe(true)
  })

  it("rejects a session-mismatched acknowledgement", async () => {
    const promise = initializeWebsiteProofRecorder(input)
    await flushPosts()
    extensionReply(RECORDER_INIT_ACK, {
      ...validAck(lastRequestId(RECORDER_INIT_REQUEST)),
      session_id: "another-session",
    })
    const result = await promise
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error_code).toBe("session_mismatch")
  })

  it("classifies total silence as extension_not_detected at the deadline", async () => {
    const promise = initializeWebsiteProofRecorder(input)
    await vi.advanceTimersByTimeAsync(15_000)
    const result = await promise
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.diagnostic_code).toBe("WPR-EXTENSION-NOT-DETECTED")
  })

  it("classifies bridge-alive-but-worker-silent as extension_worker_unreachable", async () => {
    const promise = initializeWebsiteProofRecorder(input)
    await flushPosts()
    extensionReply(RECORDER_BRIDGE_PONG, {
      request_id: lastRequestId(RECORDER_BRIDGE_PING),
      schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
      build_version: WEBSITE_PROOF_RECORDER_BUILD_VERSION,
      context_valid: true,
      bridge_trusted: true,
    })
    await vi.advanceTimersByTimeAsync(20_000)
    const result = await promise
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error_code).toBe("extension_worker_unreachable")
  })

  it("keeps waiting through worker-unreachable NACKs and accepts a late ACK", async () => {
    const promise = initializeWebsiteProofRecorder(input)
    await flushPosts()
    const requestId = lastRequestId(RECORDER_INIT_REQUEST)
    extensionReply(RECORDER_INIT_NACK, {
      request_id: requestId,
      error_code: "extension_worker_unreachable",
      message: "worker waking",
      ready: false,
    })
    // ACK arrives late — after the nominal early retries, still within deadline.
    await vi.advanceTimersByTimeAsync(6_000)
    extensionReply(RECORDER_INIT_ACK, validAck(requestId))
    const result = await promise
    expect(result.ok).toBe(true)
  })

  it("extends the deadline once when a signal arrived just before it fired", async () => {
    const promise = initializeWebsiteProofRecorder(input)
    await flushPosts()
    const requestId = lastRequestId(RECORDER_INIT_REQUEST)
    // The bridge is alive from the start (a PONG lands well before the
    // 3s absent-extension fast-fail)...
    extensionReply(RECORDER_BRIDGE_PONG, {
      request_id: lastRequestId(RECORDER_BRIDGE_PING),
      schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
      build_version: WEBSITE_PROOF_RECORDER_BUILD_VERSION,
      context_valid: true,
      bridge_trusted: true,
    })
    // ...and answers again right before the 10s deadline...
    await vi.advanceTimersByTimeAsync(9_000)
    extensionReply(RECORDER_BRIDGE_PONG, {
      request_id: lastRequestId(RECORDER_BRIDGE_PING),
      schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
      build_version: WEBSITE_PROOF_RECORDER_BUILD_VERSION,
      context_valid: true,
      bridge_trusted: true,
    })
    // ...so a late ACK a moment after the nominal deadline is still accepted.
    await vi.advanceTimersByTimeAsync(2_000)
    extensionReply(RECORDER_INIT_ACK, validAck(requestId))
    const result = await promise
    expect(result.ok).toBe(true)
  })

  it("fails fast when the bridge reports an incompatible build", async () => {
    const promise = initializeWebsiteProofRecorder(input)
    await flushPosts()
    extensionReply(RECORDER_BRIDGE_PONG, {
      request_id: lastRequestId(RECORDER_BRIDGE_PING),
      schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
      build_version: "0.1.9",
      context_valid: true,
      bridge_trusted: true,
    })
    const result = await promise
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error_code).toBe("extension_version_incompatible")
  })

  it("accepts a NEWER installed build than the page's minimum (store rollout)", async () => {
    // Chrome Web Store updates extensions before the site redeploys — a newer
    // build answering an older page must complete the handshake.
    const promise = initializeWebsiteProofRecorder(input)
    await flushPosts()
    extensionReply(RECORDER_BRIDGE_PONG, {
      request_id: lastRequestId(RECORDER_BRIDGE_PING),
      schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
      build_version: "9.9.9",
      context_valid: true,
      bridge_trusted: true,
    })
    const requestId = lastRequestId(RECORDER_INIT_REQUEST)
    extensionReply(RECORDER_INIT_ACK, { ...validAck(requestId), build_version: "9.9.9" })
    const result = await promise
    expect(result.ok).toBe(true)
  })

  it("fails fast when the bridge belongs to a reloaded (orphaned) extension", async () => {
    const promise = initializeWebsiteProofRecorder(input)
    await flushPosts()
    extensionReply(RECORDER_BRIDGE_PONG, {
      request_id: lastRequestId(RECORDER_BRIDGE_PING),
      schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
      build_version: WEBSITE_PROOF_RECORDER_BUILD_VERSION,
      context_valid: false,
      bridge_trusted: true,
    })
    const result = await promise
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error_code).toBe("extension_context_invalidated")
  })

  it("classifies an unknown extension-sourced message type as a stale build", async () => {
    const promise = initializeWebsiteProofRecorder(input)
    await flushPosts()
    extensionReply("VERIBRIDGE_SOME_FUTURE_OR_ANCIENT_TYPE", {})
    const result = await promise
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error_code).toBe("extension_version_incompatible")
  })

  it("fails closed when the signed-in user does not match the session owner", async () => {
    const result = await initializeWebsiteProofRecorder({
      ...input,
      owner_user_id: "someone-else",
    })
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error_code).toBe("authentication_unavailable")
  })
})
