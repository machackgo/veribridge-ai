// V1.0.1 arbitrary-navigation HUD regressions (manual retest bug: 0→1→0→2).
//
// The recorder HUD must follow the ACTIVE PROOF SESSION, not a navigation
// direction. These tests pin the background half of that contract:
//   1. SPA route changes (tabs.onUpdated with a url change but no reliable
//      "complete") still nudge session tabs to reconcile via START_CAPTURING.
//   2. GET_STATE exposes restorePending while the startup session restore is
//      reading storage, so content scripts never treat the default worker
//      state as an authoritative "no session" and tear down their HUD.
//   3. A service-worker restart restores the FULL tracked-tab set, not just
//      the original target tab.
//   4. Tabs that join the session are persisted immediately so they survive
//      the next worker restart.

import assert from "node:assert/strict"
import test from "node:test"

import {
  RECORDER_INIT_REQUEST,
  RECORDER_START_REQUEST,
  RECORDER_TARGET_OPEN_REQUEST,
  WEBSITE_PROOF_RECORDER_BUILD_VERSION,
  WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
  type WebsiteProofRecorderConfig,
} from "../../../packages/shared/websiteProofRecorderContract.ts"

const SW_STATE_KEY = "vb_sw_recording"
const SW_EVIDENCE_BUFFER_KEY = "vb_sw_evidence_buffer"
const RECORDER_SESSION_CONFIG_KEY = "vb_recorder_session_config"

type Listener = (
  message: { type: string; payload?: unknown },
  sender: Record<string, unknown>,
  respond: (value: unknown) => void,
) => unknown

function makeChromeMock(options: {
  stored?: Record<string, unknown>
  sessionStored?: Record<string, unknown>
  /** When set, storage.local.get(...) stalls until the returned release() runs. */
  holdLocalGet?: boolean
} = {}) {
  let messageListener: Listener | undefined
  const stored: Record<string, unknown> = options.stored ?? {}
  const sessionStored: Record<string, unknown> = options.sessionStored ?? {}
  const sentToTabs: Array<{ tabId: number; message: { type?: string } }> = []
  const tabs = new Map<number, Record<string, unknown>>([
    [7, { id: 7, url: "http://localhost:3000/student/proofs/website", active: true, windowId: 1 }],
    [99, { id: 99, url: "https://unrelated.example.com/page", active: false, windowId: 1 }],
  ])
  let nextTabId = 40
  let onUpdated: ((tabId: number, changeInfo: Record<string, unknown>, tab: Record<string, unknown>) => void) | undefined
  let onCreated: ((tab: Record<string, unknown>) => void) | undefined

  let releaseLocalGet: (() => void) | null = null
  const localGetGate: Promise<void> | null = options.holdLocalGet
    ? new Promise((resolve) => { releaseLocalGet = resolve })
    : null

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
        get: async (keys: string[]) => {
          if (localGetGate) await localGetGate
          return Object.fromEntries(keys.filter((key) => key in stored).map((key) => [key, stored[key]]))
        },
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
      create: (opts: Record<string, unknown>, callback: (tab: Record<string, unknown>) => void) => {
        const tab = { id: nextTabId++, url: opts.url, active: opts.active, openerTabId: opts.openerTabId, windowId: 1 }
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
      onActivated: { addListener: () => undefined },
    },
    windows: { update: async () => undefined },
  }

  return {
    chromeMock,
    tabs,
    stored,
    sessionStored,
    sentToTabs,
    getListener: () => messageListener,
    releaseLocalGet: () => releaseLocalGet?.(),
    fireUpdated: (tabId: number, changeInfo: Record<string, unknown>, tab: Record<string, unknown>) =>
      onUpdated?.(tabId, changeInfo, tab),
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
    claimed_skills: ["Research"],
    proof_objective: "Demonstrate the product walkthrough",
    created_at: "2026-08-20T05:04:43.000Z",
    expires_at: null,
  }
}

async function bootBackground(
  importer: () => Promise<unknown>,
  mock: ReturnType<typeof makeChromeMock>,
  settleMs = 15,
) {
  Object.assign(globalThis, { chrome: mock.chromeMock })
  await importer()
  if (settleMs > 0) await new Promise((resolve) => setTimeout(resolve, settleMs))
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

async function startSession(
  send: Awaited<ReturnType<typeof bootBackground>>,
  mock: ReturnType<typeof makeChromeMock>,
  config: WebsiteProofRecorderConfig,
): Promise<number> {
  await send(RECORDER_INIT_REQUEST, {
    request_id: "init",
    expected_schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    expected_build_version: "1.0.0",
    config,
  })
  const opened = await send(RECORDER_TARGET_OPEN_REQUEST, {
    request_id: "target",
    session_id: config.session_id,
    config_revision: config.config_revision,
  })
  const targetTabId = opened.target_tab_id as number
  await send("RECORDER_TARGET_CONTENT_READY", {
    page_url: config.website_url,
  }, { tab: mock.tabs.get(targetTabId) })
  const started = await send(RECORDER_START_REQUEST, {
    request_id: "start",
    session_id: config.session_id,
    config_revision: config.config_revision,
  })
  assert.equal(started.ok, true)
  return targetTabId
}

test("SPA url-only tab updates nudge session tabs to reconcile (0→1→0→2 branch)", async () => {
  const mock = makeChromeMock()
  const send = await bootBackground(() => import("../src/background.ts?nav-spa-url-only"), mock)
  const config = makeConfig("https://veribridgeai.com/", "session-spa-nav")
  const targetTabId = await startSession(send, mock, config)

  // Simulate a client-side route change: Chrome reports onUpdated with only a
  // url change — no status "complete" (release-dependent behavior).
  mock.tabs.set(targetTabId, {
    ...(mock.tabs.get(targetTabId) as Record<string, unknown>),
    url: "https://veribridgeai.com/recruiters",
  })
  mock.sentToTabs.length = 0
  mock.fireUpdated(targetTabId, { url: "https://veribridgeai.com/recruiters" }, mock.tabs.get(targetTabId)!)
  assert.equal(
    mock.sentToTabs.some(({ tabId, message }) => tabId === targetTabId && message.type === "START_CAPTURING"),
    true,
    "a SPA url change on the tracked tab must trigger HUD reconciliation",
  )

  // The SPA route change is also recorded as a navigation event exactly once,
  // even when a "complete" event later fires for the same URL.
  const before = await send("GET_STATE", {}, { tab: mock.tabs.get(targetTabId) })
  mock.fireUpdated(targetTabId, { status: "complete" }, mock.tabs.get(targetTabId)!)
  const after = await send("GET_STATE", {}, { tab: mock.tabs.get(targetTabId) })
  assert.equal(after.eventCount, before.eventCount, "url+complete double-fire must not duplicate the navigation event")

  // Unrelated tabs: a url-only update must never trigger capture.
  mock.sentToTabs.length = 0
  mock.fireUpdated(99, { url: "https://unrelated.example.com/other" }, mock.tabs.get(99)!)
  assert.equal(
    mock.sentToTabs.some(({ tabId }) => tabId === 99),
    false,
    "unrelated tabs must never receive START_CAPTURING for SPA url changes",
  )
})

test("GET_STATE reports restorePending until the startup session restore settles", async () => {
  const config = makeConfig("https://veribridgeai.com/", "session-restore-pending")
  const mock = makeChromeMock({
    holdLocalGet: true,
    stored: {
      [RECORDER_SESSION_CONFIG_KEY]: config,
      [SW_STATE_KEY]: {
        sessionId: config.session_id,
        configRevision: config.config_revision,
        startedAt: "2026-08-20T05:05:00.000Z",
        phase: "recording",
        originalTabId: 40,
        trackedTabIds: [40],
      },
    },
  })
  // Boot without waiting for the (deliberately stalled) restore.
  const send = await bootBackground(() => import("../src/background.ts?nav-restore-pending"), mock, 0)

  // While the restore is in flight, the default state must be flagged as
  // indeterminate — content scripts keep their HUD instead of tearing down.
  const during = await send("GET_STATE", {}, { tab: { id: 40, url: "https://veribridgeai.com/" } })
  assert.equal(during.restorePending, true, "in-flight restore must be visible to content scripts")
  assert.equal(during.isRecording, false)

  mock.releaseLocalGet()
  await new Promise((resolve) => setTimeout(resolve, 20))

  const after = await send("GET_STATE", {}, { tab: { id: 40, url: "https://veribridgeai.com/" } })
  assert.equal(after.restorePending, false, "settled restore must clear the pending flag")
  assert.equal(after.isRecording, true, "the persisted recording session must be restored")
  assert.equal(after.isTrackedTab, true)
})

test("service-worker restart restores the FULL tracked-tab set", async () => {
  const config = makeConfig("https://veribridgeai.com/", "session-full-set")
  const mock = makeChromeMock({
    stored: {
      [RECORDER_SESSION_CONFIG_KEY]: config,
      [SW_STATE_KEY]: {
        sessionId: config.session_id,
        configRevision: config.config_revision,
        startedAt: "2026-08-20T05:05:00.000Z",
        phase: "recording",
        originalTabId: 40,
        proofBuilderTabId: 7,
        // Tab 60 was opened from the target tab during the session.
        trackedTabIds: [40, 60],
      },
    },
    sessionStored: {
      [SW_EVIDENCE_BUFFER_KEY]: {
        sessionId: config.session_id,
        configRevision: config.config_revision,
        workflowEvents: [],
        visibleEvidenceEvents: [],
      },
    },
  })
  mock.tabs.set(40, { id: 40, url: "https://veribridgeai.com/", active: true, windowId: 1 })
  mock.tabs.set(60, { id: 60, url: "https://veribridgeai.com/recruiters", active: false, windowId: 1 })

  const send = await bootBackground(() => import("../src/background.ts?nav-full-set-restore"), mock)

  const fromChild = await send("GET_STATE", {}, { tab: mock.tabs.get(60) })
  assert.equal(fromChild.isTrackedTab, true, "session tabs beyond the target must survive a worker restart")
  const fromTarget = await send("GET_STATE", {}, { tab: mock.tabs.get(40) })
  assert.equal(fromTarget.isTrackedTab, true)
  const fromUnrelated = await send("GET_STATE", {}, { tab: mock.tabs.get(99) })
  assert.equal(fromUnrelated.isTrackedTab, false)

  // The restore broadcast reaches every session tab, not just the target.
  const captureTargets = mock.sentToTabs
    .filter(({ message }) => message.type === "START_CAPTURING")
    .map(({ tabId }) => tabId)
  assert.equal(captureTargets.includes(40), true)
  assert.equal(captureTargets.includes(60), true)
})

test("tabs joining the session are persisted for the next worker restart", async () => {
  const mock = makeChromeMock()
  const send = await bootBackground(() => import("../src/background.ts?nav-persist-joined"), mock)
  const config = makeConfig("https://veribridgeai.com/", "session-persist-joined")
  const targetTabId = await startSession(send, mock, config)

  mock.fireCreated({ id: 60, openerTabId: targetTabId, url: "https://veribridgeai.com/recruiters" })
  await new Promise((resolve) => setTimeout(resolve, 10))

  const persisted = mock.stored[SW_STATE_KEY] as { trackedTabIds?: number[] } | undefined
  assert.ok(persisted, "recording state must be persisted")
  assert.ok(Array.isArray(persisted.trackedTabIds), "tracked tab ids must be persisted")
  assert.equal(persisted.trackedTabIds!.includes(targetTabId), true)
  assert.equal(persisted.trackedTabIds!.includes(60), true, "a tab joining the session must be persisted immediately")
})
