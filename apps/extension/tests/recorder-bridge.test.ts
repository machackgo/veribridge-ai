import assert from "node:assert/strict"
import test from "node:test"

import {
  RECORDER_AUTH_REFRESH_REQUEST,
  RECORDER_AUTH_REFRESH_ACK,
  RECORDER_BRIDGE_PING,
  RECORDER_BRIDGE_PONG,
  RECORDER_INIT_ACK,
  RECORDER_INIT_NACK,
  RECORDER_INIT_REQUEST,
  RECORDER_START_ACK,
  RECORDER_START_REQUEST,
  RECORDER_TARGET_OPEN_ACK,
  RECORDER_TARGET_OPEN_REQUEST,
  WEBSITE_PROOF_RECORDER_BUILD_VERSION,
  WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
  isTrustedVeriBridgeAppLocation,
} from "../../../packages/shared/websiteProofRecorderContract.ts"
import {
  createRecorderBridgeHandler,
  type RecorderBridgeDeps,
  type RecorderBridgeResponse,
} from "../src/recorderBridge.ts"

const APP_ORIGIN = "http://localhost:3000"

function makeHarness(overrides: Partial<{
  pathname: string
  contextInvalidated: boolean
  backgroundResponse: RecorderBridgeResponse | null
}> = {}) {
  const posted: Array<{ source: string; type: string; payload: Record<string, unknown> }> = []
  const relayed: Array<{ type: string; payload: unknown }> = []
  const location = {
    hostname: "localhost",
    pathname: overrides.pathname ?? "/student/proofs/website",
    origin: APP_ORIGIN,
  }
  const deps: RecorderBridgeDeps = {
    getLocation: () => ({ ...location }),
    isContextInvalidated: () => overrides.contextInvalidated ?? false,
    sendToBackground: async (message) => {
      relayed.push(message)
      return overrides.backgroundResponse === undefined
        ? { ok: true, request_id: "req-1" }
        : overrides.backgroundResponse
    },
    postToPage: (message) => posted.push(message as (typeof posted)[number]),
  }
  const handler = createRecorderBridgeHandler(deps)
  const send = (data: unknown, event: Partial<{ origin: string; same_window: boolean }> = {}) =>
    handler({ origin: event.origin ?? APP_ORIGIN, data, same_window: event.same_window ?? true })
  return { posted, relayed, location, send }
}

const initRequest = {
  source: "veribridge-app",
  type: RECORDER_INIT_REQUEST,
  payload: { request_id: "req-1" },
}

async function flush() {
  await new Promise((resolve) => setTimeout(resolve, 0))
}

test("trust gate is evaluated per message, not at script load (SPA navigation)", async () => {
  // Simulates a tab whose document loaded at "/" (untrusted) and later
  // client-side navigated to the proof page. The regression that produced
  // WPR-INITIALIZATION-TIMEOUT was caching the load-time answer.
  const { posted, relayed, location, send } = makeHarness({ pathname: "/" })
  send(initRequest)
  await flush()
  assert.equal(relayed.length, 0, "untrusted path must not relay")

  location.pathname = "/student/proofs/website"
  send(initRequest)
  await flush()
  assert.equal(relayed.length, 1, "post-navigation message must relay")
  assert.equal(posted.at(-1)?.type, RECORDER_INIT_ACK)
})

test("bridge ping is answered synchronously with build/context info", () => {
  const { posted, relayed, send } = makeHarness()
  send({ source: "veribridge-app", type: RECORDER_BRIDGE_PING, payload: { request_id: "ping-1" } })
  assert.equal(relayed.length, 0, "ping must not touch the background")
  assert.equal(posted.length, 1)
  assert.equal(posted[0].type, RECORDER_BRIDGE_PONG)
  assert.deepEqual(posted[0].payload, {
    request_id: "ping-1",
    schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    build_version: WEBSITE_PROOF_RECORDER_BUILD_VERSION,
    context_valid: true,
    bridge_trusted: true,
  })
})

test("ping reports an invalidated context so the page can fail fast", () => {
  const { posted, send } = makeHarness({ contextInvalidated: true })
  send({ source: "veribridge-app", type: RECORDER_BRIDGE_PING, payload: { request_id: "ping-2" } })
  assert.equal((posted[0].payload as { context_valid: boolean }).context_valid, false)
})

test("unreachable background produces an explicit retryable NACK, not silence", async () => {
  const { posted, send } = makeHarness({ backgroundResponse: null })
  send(initRequest)
  await flush()
  assert.equal(posted.length, 1)
  assert.equal(posted[0].type, RECORDER_INIT_NACK)
  assert.equal(posted[0].payload.error_code, "extension_worker_unreachable")
  assert.equal(posted[0].payload.request_id, "req-1")
})

test("invalidated context produces the context-invalidated NACK", async () => {
  const { posted, send } = makeHarness({ backgroundResponse: null, contextInvalidated: true })
  send(initRequest)
  await flush()
  assert.equal(posted[0].payload.error_code, "extension_context_invalidated")
})

test("each request type maps to its own ACK, failures map to the NACK", async () => {
  const cases: Array<[string, string]> = [
    [RECORDER_INIT_REQUEST, RECORDER_INIT_ACK],
    [RECORDER_TARGET_OPEN_REQUEST, RECORDER_TARGET_OPEN_ACK],
    [RECORDER_START_REQUEST, RECORDER_START_ACK],
    [RECORDER_AUTH_REFRESH_REQUEST, RECORDER_AUTH_REFRESH_ACK],
  ]
  for (const [requestType, ackType] of cases) {
    const { posted, send } = makeHarness()
    send({ source: "veribridge-app", type: requestType, payload: { request_id: "r" } })
    await flush()
    assert.equal(posted[0].type, ackType)
  }
  const { posted, send } = makeHarness({ backgroundResponse: { ok: false, error_code: "session_mismatch" } })
  send({ source: "veribridge-app", type: RECORDER_START_REQUEST, payload: { request_id: "r" } })
  await flush()
  assert.equal(posted[0].type, RECORDER_INIT_NACK)
})

test("cross-window, cross-origin, foreign-source, and unknown types are ignored", async () => {
  const { posted, relayed, send } = makeHarness()
  send(initRequest, { same_window: false })
  send(initRequest, { origin: "https://evil.example" })
  send({ ...initRequest, source: "not-veribridge" })
  send({ source: "veribridge-app", type: "SOMETHING_ELSE", payload: {} })
  await flush()
  assert.equal(posted.length, 0)
  assert.equal(relayed.length, 0)
})

test("external target origins never bridge recorder messages", async () => {
  const { relayed, send } = makeHarness()
  const handlerLocation = { hostname: "reactplay.io", pathname: "/", origin: "https://reactplay.io" }
  const handler = createRecorderBridgeHandler({
    getLocation: () => handlerLocation,
    isContextInvalidated: () => false,
    sendToBackground: async (m) => { relayed.push(m); return { ok: true } },
    postToPage: () => undefined,
  })
  handler({ origin: "https://reactplay.io", data: initRequest, same_window: true })
  await flush()
  assert.equal(relayed.length, 0)
})

test("shared trusted-location helper matches the app surface exactly", () => {
  const trusted = (hostname: string, pathname: string) =>
    isTrustedVeriBridgeAppLocation({ hostname, pathname })
  assert.equal(trusted("localhost", "/student/proofs/website"), true)
  assert.equal(trusted("localhost", "/dashboard/profile"), true)
  assert.equal(trusted("127.0.0.1", "/vbr"), true)
  assert.equal(trusted("app.veribridge.ai", "/anything"), true)
  assert.equal(trusted("localhost", "/"), false)
  assert.equal(trusted("localhost", "/login"), false)
  assert.equal(trusted("reactplay.io", "/student"), false)
})
