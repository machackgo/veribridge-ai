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

test("background owns the acknowledged config, target, and start lifecycle", async () => {
  let messageListener: (
    message: { type: string; payload?: unknown },
    sender: Record<string, unknown>,
    respond: (value: unknown) => void,
  ) => unknown
  const stored: Record<string, unknown> = {}
  const sessionStored: Record<string, unknown> = {}
  const sentToTabs: Array<{ tabId: number; message: unknown }> = []
  const tabs = new Map<number, Record<string, unknown>>([
    [7, { id: 7, url: "http://localhost:3000/student/proofs/website", active: true, windowId: 1 }],
  ])
  let nextTabId = 40
  const noopListener = { addListener: () => undefined }

  const chromeMock = {
    runtime: {
      id: "extension-under-test",
      lastError: undefined,
      getManifest: () => ({ version: WEBSITE_PROOF_RECORDER_BUILD_VERSION }),
      getURL: (path: string) => `chrome-extension://extension-under-test/${path}`,
      onMessage: {
        addListener: (listener: typeof messageListener) => { messageListener = listener },
      },
    },
    storage: {
      local: {
        get: async (keys: string[]) => Object.fromEntries(keys.filter((key) => key in stored).map((key) => [key, stored[key]])),
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
      query: async (query: Record<string, unknown>) => query.active ? [tabs.get(7)] : [...tabs.values()],
      sendMessage: async (tabId: number, message: unknown) => { sentToTabs.push({ tabId, message }) },
      create: (options: Record<string, unknown>, callback: (tab: Record<string, unknown>) => void) => {
        const tab = { id: nextTabId++, url: options.url, active: options.active, openerTabId: options.openerTabId, windowId: 1 }
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
      captureVisibleTab: async () => "data:image/jpeg;base64," + "a".repeat(1600),
      onCreated: noopListener,
      onUpdated: noopListener,
      onActivated: noopListener,
    },
    windows: { update: async () => undefined },
  }
  Object.assign(globalThis, { chrome: chromeMock })

  await import("../src/background.ts")
  await Promise.resolve()
  assert.equal(typeof messageListener, "function")

  const send = async (
    type: string,
    payload: unknown,
    sender: Record<string, unknown> = { tab: tabs.get(7) },
  ): Promise<Record<string, unknown>> => await new Promise((resolve, reject) => {
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

  const config: WebsiteProofRecorderConfig = {
    schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    config_revision: 2,
    session_id: "session-wikitok-fresh",
    owner_user_id: "user-1",
    api_base_url: "http://localhost:8128",
    auth: { mechanism: "bearer", access_token: "private-token", expires_at: null },
    project_id: "project-wikitok",
    website_url: "https://wikitok.io/",
    repository_url: "https://github.com/IsaacGemal/wikitok",
    claimed_skills: ["React", "TypeScript"],
    proof_objective: "Demonstrate the WikiTok feed and language workflow",
    created_at: "2026-07-14T05:04:43.000Z",
    expires_at: null,
  }
  const initPayload = {
    request_id: "init-1",
    expected_schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    expected_build_version: WEBSITE_PROOF_RECORDER_BUILD_VERSION,
    config,
  }

  const initialized = await send(RECORDER_INIT_REQUEST, initPayload)
  assert.deepEqual(initialized, {
    ok: true,
    request_id: "init-1",
    session_id: config.session_id,
    config_revision: config.config_revision,
    api_base_url: config.api_base_url,
    schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    build_version: WEBSITE_PROOF_RECORDER_BUILD_VERSION,
    extension_id: "extension-under-test",
    ready: true,
  })
  assert.deepEqual(stored.vb_recorder_session_config, config)
  assert.equal("currentSessionId" in stored, false)
  assert.equal("apiUrl" in stored, false)
  assert.equal("authToken" in stored, false)

  const publicState = await send("GET_STATE", {})
  assert.equal(publicState.authConfigured, true)
  assert.equal("authToken" in publicState, false)
  const privateStateFromPage = await send("GET_RECORDER_PRIVATE_STATE", {})
  assert.equal(privateStateFromPage.ok, false)
  assert.equal(privateStateFromPage.error_code, "authentication_unavailable")

  const duplicate = await send(RECORDER_INIT_REQUEST, { ...initPayload, request_id: "init-duplicate" })
  assert.equal(duplicate.ready, true)
  assert.equal(duplicate.config_revision, 2)

  const stale = await send(RECORDER_INIT_REQUEST, {
    ...initPayload,
    request_id: "init-stale",
    config: { ...config, config_revision: 1 },
  })
  assert.equal(stale.ok, false)
  assert.equal(stale.error_code, "stale_config")

  const opened = await send(RECORDER_TARGET_OPEN_REQUEST, {
    request_id: "target-1",
    session_id: config.session_id,
    config_revision: config.config_revision,
  })
  assert.equal(opened.ok, true)
  assert.equal(opened.target_tab_id, 40)

  const prematureStart = await send(RECORDER_START_REQUEST, {
    request_id: "start-too-soon",
    session_id: config.session_id,
    config_revision: config.config_revision,
  })
  assert.equal(prematureStart.ok, false)
  assert.equal(prematureStart.error_code, "recording_not_ready")

  const targetReady = await send("RECORDER_TARGET_CONTENT_READY", {
    page_url: "https://wikitok.io/",
  }, { tab: tabs.get(40) })
  assert.equal(targetReady.ok, true)
  assert.equal(targetReady.api_base_url, "http://localhost:8128")
  assert.deepEqual(targetReady.claimed_skills, ["React", "TypeScript"])
  assert.equal(sentToTabs.some(({ tabId, message }) =>
    tabId === 7 && (message as { type?: string }).type === "RECORDER_TARGET_READY"
  ), true)

  const started = await send(RECORDER_START_REQUEST, {
    request_id: "start-1",
    session_id: config.session_id,
    config_revision: config.config_revision,
  })
  assert.equal(started.ok, true)
  assert.equal(started.ready, true)
  assert.equal(started.idempotent, false)
  assert.equal(typeof started.started_at, "string")

  const duplicateStart = await send(RECORDER_START_REQUEST, {
    request_id: "start-duplicate",
    session_id: config.session_id,
    config_revision: config.config_revision,
  })
  assert.equal(duplicateStart.ok, true)
  assert.equal(duplicateStart.idempotent, true)
  assert.equal(duplicateStart.started_at, started.started_at)

  const foreignInit = await send(RECORDER_INIT_REQUEST, {
    ...initPayload,
    request_id: "foreign-init",
    config: { ...config, session_id: "session-foreign", config_revision: 3 },
  })
  assert.equal(foreignInit.ok, false)
  assert.equal(foreignInit.error_code, "different_session_active")

  await send("WORKFLOW_EVENT", {
    type: "page_visit",
    timestamp: "2026-07-14T12:00:01Z",
    page_url: "https://wikitok.io/",
    page_title: "WikiTok",
  }, { tab: tabs.get(40) })
  await send("VISIBLE_EVIDENCE_EVENT", {
    event_type: "page_load",
    timestamp_ms: 1000,
    event_id: "event-1",
    url: "https://wikitok.io/",
    page_title: "WikiTok",
    target_domain: "wikitok.io",
    visible_text_blocks: ["Article feed"],
    result_like_blocks: [],
    input_snapshot: {},
    action_snapshot: {},
  }, { tab: tabs.get(40) })
  await send("RECORDER_VIDEO_UPLOADED", { ok: true, keyframe_count: 3 }, {
    url: "chrome-extension://extension-under-test/recorder.html",
  })
  await send("STOP_RECORDING", {}, { tab: tabs.get(40) })
  await new Promise((resolve) => setTimeout(resolve, 10))

  assert.equal((stored.vb_sw_recording as { phase?: string }).phase, "stopped")
  assert.equal((stored.vb_sw_recording as { videoUploadStatus?: string }).videoUploadStatus, "uploaded")
  assert.equal(
    (sessionStored.vb_sw_evidence_buffer as { workflowEvents?: unknown[] }).workflowEvents?.length,
    1,
  )

  // A fresh service-worker instance must recover the stopped proof and its
  // sanitized buffer instead of silently returning an empty session.
  await import("../src/background.ts?restart")
  await new Promise((resolve) => setTimeout(resolve, 10))
  const recovered = await send("GET_STATE", {})
  assert.equal(recovered.status, "stopped")
  assert.equal(recovered.eventCount, 1)
  assert.equal(recovered.videoUploadStatus, "uploaded")
})
