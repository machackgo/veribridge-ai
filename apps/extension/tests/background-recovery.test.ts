import assert from "node:assert/strict"
import test from "node:test"

import {
  WEBSITE_PROOF_RECORDER_BUILD_VERSION,
  WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
  type WebsiteProofRecorderConfig,
} from "../../../packages/shared/websiteProofRecorderContract.ts"

const SW_STATE_KEY = "vb_sw_recording"
const SW_EVIDENCE_BUFFER_KEY = "vb_sw_evidence_buffer"
const RECORDER_SESSION_CONFIG_KEY = "vb_recorder_session_config"

function baseConfig(overrides: Partial<WebsiteProofRecorderConfig> = {}): WebsiteProofRecorderConfig {
  return {
    schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    config_revision: 4,
    session_id: "session-recovery",
    owner_user_id: "user-1",
    api_base_url: "http://localhost:8128",
    auth: { mechanism: "bearer", access_token: "private-token", expires_at: null },
    project_id: "project-1",
    website_url: "https://wikitok.io/",
    repository_url: null,
    claimed_skills: ["React"],
    proof_objective: "Recover the recording",
    created_at: "2026-07-14T05:04:43.000Z",
    expires_at: null,
    ...overrides,
  }
}

type Harness = {
  stored: Record<string, unknown>
  sessionStored: Record<string, unknown>
  sentToTabs: Array<{ tabId: number; message: { type?: string } }>
  reloadedTabs: number[]
  send: (type: string, payload?: unknown, sender?: Record<string, unknown>) => Promise<Record<string, unknown>>
}

async function bootBackground(
  importer: () => Promise<unknown>,
  stored: Record<string, unknown>,
  sessionStored: Record<string, unknown>,
): Promise<Harness> {
  const sentToTabs: Array<{ tabId: number; message: { type?: string } }> = []
  const reloadedTabs: number[] = []
  const tabs = new Map<number, Record<string, unknown>>([
    [7, { id: 7, url: "http://localhost:3000/student/proofs/website", active: true, windowId: 1 }],
    [40, { id: 40, url: "https://wikitok.io/", active: true, windowId: 1 }],
    [55, { id: 55, url: "chrome-extension://extension-under-test/recorder.html", active: false, windowId: 1 }],
  ])
  let nextTabId = 90
  const noopListener = { addListener: () => undefined }
  let messageListener: (
    message: { type: string; payload?: unknown },
    sender: Record<string, unknown>,
    respond: (value: unknown) => void,
  ) => unknown = () => undefined

  const chromeMock = {
    runtime: {
      id: "extension-under-test",
      lastError: undefined,
      getManifest: () => ({ version: WEBSITE_PROOF_RECORDER_BUILD_VERSION }),
      getURL: (path: string) => `chrome-extension://extension-under-test/${path}`,
      onMessage: { addListener: (listener: typeof messageListener) => { messageListener = listener } },
    },
    storage: {
      local: {
        get: async (keys: string[]) =>
          Object.fromEntries(keys.filter((key) => key in stored).map((key) => [key, stored[key]])),
        set: async (patch: Record<string, unknown>) => { Object.assign(stored, patch) },
        remove: async (key: string) => { delete stored[key] },
      },
      session: {
        get: async (key: string) => (key in sessionStored ? { [key]: sessionStored[key] } : {}),
        set: async (patch: Record<string, unknown>) => { Object.assign(sessionStored, patch) },
        remove: async (key: string) => { delete sessionStored[key] },
      },
    },
    tabs: {
      query: async (query: Record<string, unknown>) => (query.active ? [tabs.get(7)] : [...tabs.values()]),
      sendMessage: async (tabId: number, message: { type?: string }) => { sentToTabs.push({ tabId, message }) },
      create: (options: Record<string, unknown>, callback: (tab: Record<string, unknown>) => void) => {
        const tab = { id: nextTabId++, url: options.url, active: options.active, windowId: 1 }
        tabs.set(tab.id, tab)
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
      reload: (tabId: number, _options: Record<string, unknown>, callback?: () => void) => {
        reloadedTabs.push(tabId)
        callback?.()
      },
      captureVisibleTab: async () => "data:image/jpeg;base64," + "a".repeat(1600),
      onCreated: noopListener,
      onUpdated: noopListener,
      onActivated: noopListener,
    },
    windows: { update: async () => undefined },
  }
  Object.assign(globalThis, { chrome: chromeMock })

  await importer()
  // Let the startup storage.get().then() restoration settle.
  await new Promise((resolve) => setTimeout(resolve, 15))

  const send = (
    type: string,
    payload: unknown = {},
    sender: Record<string, unknown> = { tab: tabs.get(40) },
  ): Promise<Record<string, unknown>> => new Promise((resolve, reject) => {
    let responded = false
    const timeout = setTimeout(() => reject(new Error(`No response for ${type}`)), 1000)
    const keepAlive = messageListener({ type, payload }, sender, (response) => {
      responded = true
      clearTimeout(timeout)
      resolve((response ?? {}) as Record<string, unknown>)
    })
    if (keepAlive !== true && !responded) {
      clearTimeout(timeout)
      resolve({})
    }
  })

  return { stored, sessionStored, sentToTabs, reloadedTabs, send }
}

test("recording-phase restart restores events and re-broadcasts capture", async () => {
  const config = baseConfig()
  const stored: Record<string, unknown> = {
    [RECORDER_SESSION_CONFIG_KEY]: config,
    [SW_STATE_KEY]: {
      sessionId: config.session_id,
      configRevision: config.config_revision,
      startedAt: "2026-07-14T05:05:00.000Z",
      phase: "recording",
      originalTabId: 40,
      proofBuilderTabId: 7,
      recorderTabId: 55,
      videoUploadStatus: "none",
    },
  }
  const sessionStored: Record<string, unknown> = {
    [SW_EVIDENCE_BUFFER_KEY]: {
      sessionId: config.session_id,
      configRevision: config.config_revision,
      workflowEvents: [{ type: "page_visit", timestamp: "t", page_url: "https://wikitok.io/", page_title: "WikiTok" }],
      visibleEvidenceEvents: [
        { event_type: "dom_snapshot", timestamp_ms: 1, event_id: "e1", url: "https://wikitok.io/", page_title: "WikiTok", target_domain: "wikitok.io", visible_text_blocks: [], result_like_blocks: [], input_snapshot: {}, action_snapshot: {} },
      ],
    },
  }
  const h = await bootBackground(() => import("../src/background.ts?recording-restart"), stored, sessionStored)
  const stateAfter = await h.send("GET_STATE")
  assert.equal(stateAfter.status, "recording")
  assert.equal(stateAfter.isRecording, true)
  assert.equal(stateAfter.eventCount, 1)
  assert.equal(
    h.sentToTabs.some((entry) => entry.message.type === "START_CAPTURING"),
    true,
    "recording restore must re-broadcast START_CAPTURING",
  )
  assert.deepEqual(
    h.reloadedTabs,
    [55],
    "recording restore must refresh the retained recorder tab from the invalidated extension context",
  )
})

test("stopped-phase restart restores buffer but does not restart capture", async () => {
  const config = baseConfig({ session_id: "session-stopped" })
  const stored: Record<string, unknown> = {
    [RECORDER_SESSION_CONFIG_KEY]: config,
    [SW_STATE_KEY]: {
      sessionId: config.session_id,
      configRevision: config.config_revision,
      startedAt: "2026-07-14T05:05:00.000Z",
      phase: "stopped",
      stoppedAt: "2026-07-14T05:07:00.000Z",
      originalTabId: 40,
      proofBuilderTabId: 7,
      videoUploadStatus: "uploaded",
    },
  }
  const sessionStored: Record<string, unknown> = {
    [SW_EVIDENCE_BUFFER_KEY]: {
      sessionId: config.session_id,
      configRevision: config.config_revision,
      workflowEvents: [
        { type: "page_visit", timestamp: "t", page_url: "https://wikitok.io/", page_title: "WikiTok" },
        { type: "click", timestamp: "t2", page_url: "https://wikitok.io/", page_title: "WikiTok" },
      ],
      visibleEvidenceEvents: [],
    },
  }
  const h = await bootBackground(() => import("../src/background.ts?stopped-restart"), stored, sessionStored)
  const stateAfter = await h.send("GET_STATE")
  assert.equal(stateAfter.status, "stopped")
  assert.equal(stateAfter.isRecording, false)
  assert.equal(stateAfter.eventCount, 2)
  assert.equal(stateAfter.videoUploadStatus, "uploaded")
  assert.equal(
    h.sentToTabs.some((entry) => entry.message.type === "START_CAPTURING"),
    false,
    "stopped restore must NOT restart capture",
  )
})

test("stale-revision persisted state clears buffer and recovers empty", async () => {
  const config = baseConfig({ session_id: "session-fresh", config_revision: 6 })
  const stored: Record<string, unknown> = {
    [RECORDER_SESSION_CONFIG_KEY]: config,
    // Persisted recording snapshot points at an older revision of the same
    // session — it must not resurrect against the fresh config.
    [SW_STATE_KEY]: {
      sessionId: config.session_id,
      configRevision: 5,
      startedAt: "2026-07-14T05:05:00.000Z",
      phase: "recording",
      originalTabId: 40,
    },
  }
  const sessionStored: Record<string, unknown> = {
    [SW_EVIDENCE_BUFFER_KEY]: {
      sessionId: config.session_id,
      configRevision: 5,
      workflowEvents: [{ type: "page_visit", timestamp: "t", page_url: "https://wikitok.io/", page_title: "WikiTok" }],
      visibleEvidenceEvents: [],
    },
  }
  const h = await bootBackground(() => import("../src/background.ts?stale-revision"), stored, sessionStored)
  const stateAfter = await h.send("GET_STATE")
  assert.equal(stateAfter.isRecording, false)
  assert.equal(stateAfter.eventCount, 0)
  assert.equal(SW_STATE_KEY in stored, false, "stale recording snapshot must be cleared")
  assert.equal(SW_EVIDENCE_BUFFER_KEY in sessionStored, false, "stale evidence buffer must be cleared")
})

test("wrong-session evidence buffer is not adopted by a recovered session", async () => {
  const config = baseConfig({ session_id: "session-a", config_revision: 2 })
  const stored: Record<string, unknown> = {
    [RECORDER_SESSION_CONFIG_KEY]: config,
    [SW_STATE_KEY]: {
      sessionId: config.session_id,
      configRevision: config.config_revision,
      startedAt: "2026-07-14T05:05:00.000Z",
      phase: "stopped",
      originalTabId: 40,
      videoUploadStatus: "uploaded",
    },
  }
  const sessionStored: Record<string, unknown> = {
    // Evidence left over from a DIFFERENT session must never attach here.
    [SW_EVIDENCE_BUFFER_KEY]: {
      sessionId: "session-b",
      configRevision: 2,
      workflowEvents: [{ type: "page_visit", timestamp: "t", page_url: "https://evil.example/", page_title: "Other" }],
      visibleEvidenceEvents: [],
    },
  }
  const h = await bootBackground(() => import("../src/background.ts?wrong-session"), stored, sessionStored)
  const stateAfter = await h.send("GET_STATE")
  assert.equal(stateAfter.status, "stopped")
  assert.equal(stateAfter.eventCount, 0, "foreign-session evidence must not be adopted")
})

test("oversized visible-evidence buffer is trimmed oldest-first and flagged", async () => {
  const config = baseConfig({ session_id: "session-quota" })
  const stored: Record<string, unknown> = { [RECORDER_SESSION_CONFIG_KEY]: config }
  const sessionStored: Record<string, unknown> = {}
  const h = await bootBackground(() => import("../src/background.ts?quota"), stored, sessionStored)

  // Configure + start a real recording so the background owns the session.
  await h.send("VERIBRIDGE_RECORDER_INIT_REQUEST", {
    request_id: "init-q",
    expected_schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    expected_build_version: WEBSITE_PROOF_RECORDER_BUILD_VERSION,
    config,
  }, { tab: { id: 7, url: "http://localhost:3000/student/proofs/website" } })
  await new Promise((resolve) => setTimeout(resolve, 5))
  await h.send("VERIBRIDGE_RECORDER_TARGET_OPEN_REQUEST", {
    request_id: "open-q",
    session_id: config.session_id,
    config_revision: config.config_revision,
  }, { tab: { id: 7, url: "http://localhost:3000/student/proofs/website" } })
  await new Promise((resolve) => setTimeout(resolve, 5))
  const readyTabId = 90
  await h.send("RECORDER_TARGET_CONTENT_READY", { page_url: "https://wikitok.io/" }, {
    tab: { id: readyTabId, url: "https://wikitok.io/" },
  })
  await h.send("VERIBRIDGE_RECORDER_START_REQUEST", {
    request_id: "start-q",
    session_id: config.session_id,
    config_revision: config.config_revision,
  }, { tab: { id: 7 } })

  // Push a handful of very large visible-evidence events past the 6MB budget.
  const blocks = [ "x".repeat(400_000) ] // ~400KB text per event
  for (let i = 0; i < 24; i += 1) {
    await h.send("VISIBLE_EVIDENCE_EVENT", {
      event_type: "dom_snapshot",
      timestamp_ms: i,
      event_id: `ve-${i}`,
      url: "https://wikitok.io/",
      page_title: "WikiTok",
      target_domain: "wikitok.io",
      visible_text_blocks: blocks,
      result_like_blocks: [],
      input_snapshot: {},
      action_snapshot: {},
    }, { tab: { id: readyTabId, url: "https://wikitok.io/" } })
  }
  await h.send("WORKFLOW_EVENT", {
    type: "page_visit", timestamp: "t", page_url: "https://wikitok.io/", page_title: "WikiTok",
  }, { tab: { id: readyTabId } })
  // Force a synchronous flush and let the write queue settle.
  await h.send("STOP_RECORDING", {}, { tab: { id: readyTabId } })
  await new Promise((resolve) => setTimeout(resolve, 20))

  const buffer = sessionStored[SW_EVIDENCE_BUFFER_KEY] as {
    workflowEvents: unknown[]
    visibleEvidenceEvents: unknown[]
    truncated?: boolean
  }
  assert.ok(buffer, "evidence buffer must be persisted")
  const serialized = JSON.stringify(buffer).length
  assert.ok(serialized <= 6_000_000, `persisted buffer must fit the quota budget (was ${serialized})`)
  assert.equal(buffer.truncated, true, "over-budget buffer must be flagged truncated")
  assert.equal(buffer.workflowEvents.length, 1, "workflow events are essential and kept in full")
  assert.ok(buffer.visibleEvidenceEvents.length < 24, "oldest visible-evidence events dropped to fit")
  assert.ok(buffer.visibleEvidenceEvents.length > 0, "recent visible-evidence events retained")
})
