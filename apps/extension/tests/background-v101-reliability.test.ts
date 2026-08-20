// V1.0.1 reliability regressions:
//   Bug 1 — a https://veribridgeai.com target must complete the content-script
//           readiness handshake and start recording exactly like an external
//           site (v1.0.0 never announced readiness from VeriBridge origins).
//   Bug 2 — HUD/capture eligibility is the background's per-sender
//           isTrackedTab answer, so the HUD follows full navigation (including
//           cross-origin) on session tabs and never leaks into unrelated tabs.
//   Privacy — workflow events from untracked tabs are dropped, and
//           START_CAPTURING is only ever sent to the session's own tabs.

import assert from "node:assert/strict"
import test from "node:test"

import {
  RECORDER_INIT_REQUEST,
  RECORDER_START_REQUEST,
  RECORDER_TARGET_OPEN_REQUEST,
  WEBSITE_PROOF_RECORDER_BUILD_VERSION,
  WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
  isVeriBridgeInternalAppLocation,
  type WebsiteProofRecorderConfig,
} from "../../../packages/shared/websiteProofRecorderContract.ts"

type Listener = (
  message: { type: string; payload?: unknown },
  sender: Record<string, unknown>,
  respond: (value: unknown) => void,
) => unknown

function makeChromeMock() {
  let messageListener: Listener | undefined
  const stored: Record<string, unknown> = {}
  const sessionStored: Record<string, unknown> = {}
  const sentToTabs: Array<{ tabId: number; message: { type?: string } }> = []
  const tabs = new Map<number, Record<string, unknown>>([
    [7, { id: 7, url: "http://localhost:3000/student/proofs/website", active: true, windowId: 1 }],
    [99, { id: 99, url: "https://unrelated.example.com/page", active: false, windowId: 1 }],
  ])
  let nextTabId = 40
  let onUpdated: ((tabId: number, changeInfo: Record<string, unknown>, tab: Record<string, unknown>) => void) | undefined
  let onActivated: ((activeInfo: { tabId: number }) => void) | undefined
  let onCreated: ((tab: Record<string, unknown>) => void) | undefined

  const chromeMock = {
    runtime: {
      id: "extension-under-test",
      lastError: undefined,
      getManifest: () => ({ version: WEBSITE_PROOF_RECORDER_BUILD_VERSION }),
      getURL: (path: string) => `chrome-extension://extension-under-test/${path}`,
      onMessage: {
        addListener: (listener: Listener) => { messageListener = listener },
      },
      sendMessage: (_message: unknown, callback?: (resp: unknown) => void) => {
        callback?.({ ok: true, has_media: true, keyframe_count: 1 })
      },
    },
    storage: {
      local: {
        get: async (keys: string[]) =>
          Object.fromEntries(keys.filter((key) => key in stored).map((key) => [key, stored[key]])),
        set: async (patch: Record<string, unknown>) => { Object.assign(stored, patch) },
        remove: async (key: string) => { delete stored[key] },
      },
      session: {
        get: async (key: string) => key in sessionStored ? { [key]: sessionStored[key] } : {},
        set: async (patch: Record<string, unknown>) => { Object.assign(sessionStored, patch) },
        remove: async (key: string) => { delete sessionStored[key] },
      },
    },
    tabs: {
      query: async (query: Record<string, unknown>) =>
        query.active ? [tabs.get(7)] : [...tabs.values()],
      sendMessage: async (tabId: number, message: { type?: string }) => {
        sentToTabs.push({ tabId, message })
      },
      create: (options: Record<string, unknown>, callback: (tab: Record<string, unknown>) => void) => {
        const tab = {
          id: nextTabId++,
          url: options.url,
          active: options.active,
          openerTabId: options.openerTabId,
          windowId: 1,
        }
        tabs.set(tab.id as number, tab)
        callback(tab)
      },
      get: (tabId: number, callback?: (tab: Record<string, unknown> | undefined) => void) => {
        const tab = tabs.get(tabId)
        if (callback) callback(tab)
        return Promise.resolve(tab)
      },
      update: async (tabId: number, patch: Record<string, unknown>) => {
        const tab = { ...(tabs.get(tabId) ?? { id: tabId }), ...patch }
        tabs.set(tabId, tab)
        return tab
      },
      reload: (_tabId: number, _options: Record<string, unknown>, callback?: () => void) => {
        callback?.()
      },
      captureVisibleTab: async () => "data:image/jpeg;base64," + "a".repeat(1600),
      onCreated: { addListener: (fn: typeof onCreated) => { onCreated = fn } },
      onUpdated: { addListener: (fn: typeof onUpdated) => { onUpdated = fn } },
      onActivated: { addListener: (fn: typeof onActivated) => { onActivated = fn } },
    },
    windows: { update: async () => undefined },
  }

  return {
    chromeMock,
    tabs,
    sentToTabs,
    getListener: () => messageListener,
    fireUpdated: (tabId: number, changeInfo: Record<string, unknown>, tab: Record<string, unknown>) =>
      onUpdated?.(tabId, changeInfo, tab),
    fireActivated: (tabId: number) => onActivated?.({ tabId }),
    fireCreated: (tab: Record<string, unknown>) => onCreated?.(tab),
  }
}

function makeConfig(websiteUrl: string, sessionId: string): WebsiteProofRecorderConfig {
  return {
    schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    config_revision: 2,
    session_id: sessionId,
    owner_user_id: "user-1",
    api_base_url: "http://localhost:8128",
    auth: { mechanism: "bearer", access_token: "private-token", expires_at: null },
    project_id: null,
    website_url: websiteUrl,
    repository_url: null,
    claimed_skills: ["Research", "Technical Writing"],
    proof_objective: "Demonstrate the product walkthrough",
    created_at: "2026-08-20T05:04:43.000Z",
    expires_at: null,
  }
}

async function bootBackground(
  importer: () => Promise<unknown>,
  mock: ReturnType<typeof makeChromeMock>,
) {
  Object.assign(globalThis, { chrome: mock.chromeMock })
  await importer()
  await Promise.resolve()
  const listener = mock.getListener()
  assert.equal(typeof listener, "function")
  const send = async (
    type: string,
    payload: unknown,
    sender: Record<string, unknown> = { tab: mock.tabs.get(7) },
  ): Promise<Record<string, unknown>> => await new Promise((resolve, reject) => {
    let responded = false
    const timeout = setTimeout(() => reject(new Error(`No response for ${type}`)), 1000)
    const keepAlive = listener!({ type, payload }, sender, (response) => {
      responded = true
      clearTimeout(timeout)
      resolve((response ?? {}) as Record<string, unknown>)
    })
    if (keepAlive !== true && !responded) {
      clearTimeout(timeout)
      resolve({})
    }
  })
  return send
}

test("Bug 1 — a veribridgeai.com target completes readiness and starts recording", async () => {
  const mock = makeChromeMock()
  const send = await bootBackground(() => import("../src/background.ts?v101-veribridge-target"), mock)
  const config = makeConfig("https://veribridgeai.com/", "session-vb-target")

  const initialized = await send(RECORDER_INIT_REQUEST, {
    request_id: "init-vb",
    expected_schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    expected_build_version: "1.0.0",
    config,
  })
  assert.equal(initialized.ok, true, "veribridgeai.com must be a valid recorder target")

  const opened = await send(RECORDER_TARGET_OPEN_REQUEST, {
    request_id: "target-vb",
    session_id: config.session_id,
    config_revision: config.config_revision,
  })
  assert.equal(opened.ok, true)
  const targetTabId = opened.target_tab_id as number
  assert.equal(typeof targetTabId, "number")

  // The content script on the veribridgeai.com target tab announces readiness
  // (v1.0.0 suppressed this on all VeriBridge origins — the regression).
  const ready = await send("RECORDER_TARGET_CONTENT_READY", {
    page_url: "https://veribridgeai.com/",
  }, { tab: mock.tabs.get(targetTabId) })
  assert.equal(ready.ok, true, "readiness from the veribridgeai.com target tab must be accepted")

  const started = await send(RECORDER_START_REQUEST, {
    request_id: "start-vb",
    session_id: config.session_id,
    config_revision: config.config_revision,
  })
  assert.equal(started.ok, true, "recording must start once the veribridgeai.com target is ready")
  assert.equal(started.ready, true)

  // The proof-builder tab must NOT be able to claim target readiness even
  // though it is also a VeriBridge origin — exact-tab gating stays intact.
  const builderReady = await send("RECORDER_TARGET_CONTENT_READY", {
    page_url: "https://veribridgeai.com/",
  }, { tab: mock.tabs.get(7) })
  assert.equal(builderReady.ok, false)
  assert.equal(builderReady.error_code, "target_session_mismatch")
})

test("Bug 2 — tracked-tab state drives HUD eligibility across navigation", async () => {
  const mock = makeChromeMock()
  const send = await bootBackground(() => import("../src/background.ts?v101-tracked-tabs"), mock)
  const config = makeConfig("https://www.wikipedia.org/", "session-wiki-nav")

  await send(RECORDER_INIT_REQUEST, {
    request_id: "init-wiki",
    expected_schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    expected_build_version: "1.0.0",
    config,
  })
  const opened = await send(RECORDER_TARGET_OPEN_REQUEST, {
    request_id: "target-wiki",
    session_id: config.session_id,
    config_revision: config.config_revision,
  })
  const targetTabId = opened.target_tab_id as number
  await send("RECORDER_TARGET_CONTENT_READY", {
    page_url: "https://www.wikipedia.org/",
  }, { tab: mock.tabs.get(targetTabId) })
  const started = await send(RECORDER_START_REQUEST, {
    request_id: "start-wiki",
    session_id: config.session_id,
    config_revision: config.config_revision,
  })
  assert.equal(started.ok, true)

  // The target tab is tracked; the proof-builder tab and unrelated tabs are not.
  const fromTarget = await send("GET_STATE", {}, { tab: mock.tabs.get(targetTabId) })
  assert.equal(fromTarget.isTrackedTab, true)
  const fromBuilder = await send("GET_STATE", {}, { tab: mock.tabs.get(7) })
  assert.equal(fromBuilder.isTrackedTab, false)
  const fromUnrelated = await send("GET_STATE", {}, { tab: mock.tabs.get(99) })
  assert.equal(fromUnrelated.isTrackedTab, false)
  const fromPopup = await send("GET_STATE", {}, {})
  assert.equal(fromPopup.isTrackedTab, false)

  // Cross-origin full navigation in the tracked tab: still tracked, receives
  // START_CAPTURING (HUD rehydration), and the navigation event is recorded.
  mock.tabs.set(targetTabId, {
    ...(mock.tabs.get(targetTabId) as Record<string, unknown>),
    url: "https://en.wikipedia.org/wiki/Alan_Turing",
  })
  mock.sentToTabs.length = 0
  mock.fireUpdated(targetTabId, { status: "complete" }, mock.tabs.get(targetTabId)!)
  assert.equal(
    mock.sentToTabs.some(({ tabId, message }) => tabId === targetTabId && message.type === "START_CAPTURING"),
    true,
    "the tracked tab must be told to rehydrate capture + HUD after navigation",
  )
  const afterNav = await send("GET_STATE", {}, { tab: mock.tabs.get(targetTabId) })
  assert.equal(afterNav.isTrackedTab, true, "cross-origin navigation must not untrack the session tab")

  // Unrelated tab navigation: never signalled to capture.
  mock.sentToTabs.length = 0
  mock.fireUpdated(99, { status: "complete" }, mock.tabs.get(99)!)
  mock.fireActivated(99)
  assert.equal(
    mock.sentToTabs.some(({ tabId, message }) => tabId === 99 && message.type === "START_CAPTURING"),
    false,
    "unrelated tabs must never receive START_CAPTURING",
  )

  // A tab opened FROM the tracked tab joins the session.
  mock.fireCreated({ id: 60, openerTabId: targetTabId, url: "https://en.wikipedia.org/wiki/Enigma" })
  mock.tabs.set(60, { id: 60, url: "https://en.wikipedia.org/wiki/Enigma", windowId: 1 })
  const fromChild = await send("GET_STATE", {}, { tab: mock.tabs.get(60) })
  assert.equal(fromChild.isTrackedTab, true)

  // Workflow events: tracked tab counted, untracked tab dropped.
  await send("WORKFLOW_EVENT", {
    type: "click", timestamp: "2026-08-20T05:05:00Z",
    page_url: "https://en.wikipedia.org/wiki/Alan_Turing", page_title: "Alan Turing",
  }, { tab: mock.tabs.get(targetTabId) })
  await send("WORKFLOW_EVENT", {
    type: "click", timestamp: "2026-08-20T05:05:01Z",
    page_url: "https://unrelated.example.com/page", page_title: "Unrelated",
  }, { tab: mock.tabs.get(99) })
  const counted = await send("GET_STATE", {}, { tab: mock.tabs.get(targetTabId) })
  // 2 = the tab_opened event recorded when tab 60 joined the session + the
  // tracked-tab click. The unrelated tab's click must NOT be the third.
  assert.equal(counted.eventCount, 2, "only tracked-tab events may be recorded")

  // Session end: STOP broadcast reaches tabs so HUD/listeners clean up.
  mock.sentToTabs.length = 0
  const stopped = await send("STOP_RECORDING", {})
  assert.equal(stopped.ok, true)
  assert.equal(
    mock.sentToTabs.some(({ message }) => message.type === "STOP_CAPTURING"),
    true,
  )
})

test("internal-app path scoping — public veribridgeai.com pages are recordable, app routes are not", () => {
  assert.equal(isVeriBridgeInternalAppLocation({ hostname: "veribridgeai.com", pathname: "/" }), false)
  assert.equal(isVeriBridgeInternalAppLocation({ hostname: "veribridgeai.com", pathname: "/privacy" }), false)
  assert.equal(isVeriBridgeInternalAppLocation({ hostname: "www.veribridgeai.com", pathname: "/recruiters" }), false)
  assert.equal(isVeriBridgeInternalAppLocation({ hostname: "veribridgeai.com", pathname: "/student/proofs/website" }), true)
  assert.equal(isVeriBridgeInternalAppLocation({ hostname: "veribridgeai.com", pathname: "/dashboard/profile" }), true)
  assert.equal(isVeriBridgeInternalAppLocation({ hostname: "veribridgeai.com", pathname: "/passport" }), true)
  assert.equal(isVeriBridgeInternalAppLocation({ hostname: "veribridgeai.com", pathname: "/admin" }), true)
  assert.equal(isVeriBridgeInternalAppLocation({ hostname: "veribridgeai.com", pathname: "/vbr/report/abc" }), true)
  assert.equal(isVeriBridgeInternalAppLocation({ hostname: "localhost", pathname: "/student/proofs" }), true)
  assert.equal(isVeriBridgeInternalAppLocation({ hostname: "localhost", pathname: "/" }), false)
  // Lookalike hosts never qualify as VeriBridge at all.
  assert.equal(isVeriBridgeInternalAppLocation({ hostname: "evilveribridgeai.com", pathname: "/student" }), false)
  assert.equal(isVeriBridgeInternalAppLocation({ hostname: "en.wikipedia.org", pathname: "/wiki/Alan_Turing" }), false)
})
