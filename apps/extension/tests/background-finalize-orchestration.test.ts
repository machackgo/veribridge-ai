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

// The real-user failure: stopping from the floating bar / sending proof never
// finalized the recorder tab's screen recording, so SEND_PROOF hard-failed with
// "Finish uploading the screen recording…" and Retry could never succeed.
// This test drives the fixed orchestration end to end:
//   STOP_RECORDING → background requests recorder finalize (fire-and-forget)
//   SEND_PROOF (finalize fails)   → actionable WPR-coded failure, no proof upload
//   SEND_PROOF again (finalize ok) → same session, side evidence + ONE proof upload
test("sendProof orchestrates recorder finalization instead of hard-failing", async () => {
  let messageListener: (
    message: { type: string; payload?: unknown },
    sender: Record<string, unknown>,
    respond: (value: unknown) => void,
  ) => unknown
  const stored: Record<string, unknown> = {}
  const sessionStored: Record<string, unknown> = {}
  const tabs = new Map<number, Record<string, unknown>>([
    [7, { id: 7, url: "http://localhost:3000/student/proofs/website", active: true, windowId: 1 }],
  ])
  let nextTabId = 40
  const noopListener = { addListener: () => undefined }

  // Simulated recorder tab: answers RECORDER_FINALIZE_REQUEST like recorder.ts,
  // first with a diagnostic failure, then (after "Retry") with success.
  const finalizeRequests: unknown[] = []
  let finalizeResponse: Record<string, unknown> = {
    ok: false,
    has_media: true,
    keyframe_count: 0,
    code: "WPR-EMPTY-RECORDING",
    message: "The recording finished with no video data.",
    retryable: false,
  }

  const chromeMock = {
    runtime: {
      id: "extension-under-test",
      lastError: undefined,
      getManifest: () => ({ version: WEBSITE_PROOF_RECORDER_BUILD_VERSION }),
      getURL: (path: string) => `chrome-extension://extension-under-test/${path}`,
      onMessage: {
        addListener: (listener: typeof messageListener) => { messageListener = listener },
      },
      sendMessage: (message: { type?: string }, callback?: (resp: unknown) => void) => {
        if (message?.type === "RECORDER_FINALIZE_REQUEST") {
          finalizeRequests.push(message)
          setTimeout(() => callback?.({ ...finalizeResponse }), 0)
          return
        }
        callback?.({ ok: true })
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
      query: async (query: Record<string, unknown>) => query.active ? [tabs.get(7)] : [...tabs.values()],
      sendMessage: async () => undefined,
      create: (options: Record<string, unknown>, callback: (tab: Record<string, unknown>) => void) => {
        const tab = { id: nextTabId++, url: options.url, active: options.active, openerTabId: options.openerTabId, windowId: 1 }
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
      captureVisibleTab: async () => "data:image/jpeg;base64," + "a".repeat(1600),
      onCreated: noopListener,
      onUpdated: noopListener,
      onActivated: noopListener,
    },
    windows: { update: async () => undefined },
  }
  Object.assign(globalThis, { chrome: chromeMock })

  // Backend fetch capture — every recorder request must hit the configured
  // API base with the session's Bearer token.
  const backendCalls: Array<{ url: string; headers: Record<string, string> }> = []
  const fetchMock = (async (url: RequestInfo | URL, init?: RequestInit) => {
    backendCalls.push({
      url: String(url),
      headers: (init?.headers ?? {}) as Record<string, string>,
    })
    return { ok: true, status: 200, text: async () => "{}" } as unknown as Response
  }) as typeof fetch
  Object.assign(globalThis, { fetch: fetchMock })
  // Node exposes `navigator` as a getter-only global — override via defineProperty.
  Object.defineProperty(globalThis, "navigator", {
    value: { userAgent: "test", language: "en", platform: "test" },
    configurable: true,
  })

  await import("../src/background.ts")
  await Promise.resolve()
  assert.equal(typeof messageListener!, "function")

  const send = async (
    type: string,
    payload: unknown,
    sender: Record<string, unknown> = { tab: tabs.get(7) },
  ): Promise<Record<string, unknown>> => await new Promise((resolve, reject) => {
    let responded = false
    const timeout = setTimeout(() => reject(new Error(`No response for ${type}`)), 2000)
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
    session_id: "session-reactplay-real",
    owner_user_id: "user-1",
    api_base_url: "http://localhost:8128",
    auth: { mechanism: "bearer", access_token: "private-token", expires_at: null },
    project_id: "project-reactplay",
    website_url: "https://reactplay.io/",
    repository_url: "https://github.com/reactplay/react-play",
    claimed_skills: ["React", "JavaScript"],
    proof_objective: "Demonstrate the ReactPlay workflow and inspect the GitHub repository",
    created_at: "2026-07-17T05:00:00.000Z",
    expires_at: null,
  }

  const initialized = await send(RECORDER_INIT_REQUEST, {
    request_id: "init-1",
    expected_schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    expected_build_version: WEBSITE_PROOF_RECORDER_BUILD_VERSION,
    config,
  })
  assert.equal(initialized.ok, true)

  const opened = await send(RECORDER_TARGET_OPEN_REQUEST, {
    request_id: "target-1",
    session_id: config.session_id,
    config_revision: config.config_revision,
  })
  assert.equal(opened.ok, true)
  const targetTabId = opened.target_tab_id as number

  const targetReady = await send("RECORDER_TARGET_CONTENT_READY", {
    page_url: "https://reactplay.io/",
  }, { tab: tabs.get(targetTabId) })
  assert.equal(targetReady.ok, true)

  const started = await send(RECORDER_START_REQUEST, {
    request_id: "start-1",
    session_id: config.session_id,
    config_revision: config.config_revision,
  })
  assert.equal(started.ok, true)

  await send("WORKFLOW_EVENT", {
    type: "page_visit",
    timestamp: "2026-07-17T12:00:01Z",
    page_url: "https://reactplay.io/",
    page_title: "ReactPlay",
  }, { tab: tabs.get(targetTabId) })

  // Screen capture started in the recorder tab with a tab-scope selection —
  // the scope must surface in public state for the floating-bar warning.
  await send("RECORDER_STREAM_STARTED", { display_surface: "tab" }, {
    url: "chrome-extension://extension-under-test/recorder.html",
  })
  const duringRecording = await send("GET_STATE", {})
  assert.equal(duringRecording.captureSurface, "tab")

  // ── User stops from the floating bar (the real-user path) ────────────────
  await send("STOP_RECORDING", {}, { tab: tabs.get(targetTabId) })
  await new Promise((resolve) => setTimeout(resolve, 10))
  // The background must proactively ask the recorder tab to finalize.
  assert.equal(finalizeRequests.length, 1)
  // The finalize request targets the ACTIVE session so a recorder tab left
  // over from a previous session stays silent instead of answering with its
  // own already-completed upload state (QA-D-002).
  assert.equal(
    (finalizeRequests[0] as { payload?: { session_id?: string } }).payload?.session_id,
    config.session_id,
  )

  // ── SEND_PROOF while the recording could not be finalized ────────────────
  const failedSend = await send("SEND_PROOF", { finalNote: null })
  assert.equal(failedSend.ok, false)
  assert.match(String(failedSend.error), /WPR-EMPTY-RECORDING/)
  const afterFailure = await send("GET_STATE", {})
  assert.equal(afterFailure.status, "upload_failed")
  // The failure is actionable and preserved for the floating bar / proof page.
  assert.match(String(afterFailure.lastUploadError), /WPR-EMPTY-RECORDING/)
  // No canonical proof upload may have been sent.
  assert.equal(backendCalls.filter((c) => c.url.endsWith("/upload")).length, 0)

  // ── Retry: the recorder now finalizes successfully ───────────────────────
  finalizeResponse = { ok: true, has_media: true, keyframe_count: 5 }
  const retriedSend = await send("SEND_PROOF", { finalNote: null })
  assert.equal(retriedSend.ok, true)

  const finalState = await send("GET_STATE", {})
  assert.equal(finalState.status, "uploaded")
  assert.equal(finalState.videoUploadStatus, "uploaded")
  assert.equal(finalState.videoKeyframeCount, 5)
  assert.equal(finalState.sessionId, config.session_id)

  // Exactly ONE canonical proof upload for the session — retries never duplicate.
  const uploadCalls = backendCalls.filter((c) => c.url.endsWith("/upload"))
  assert.equal(uploadCalls.length, 1)
  assert.equal(
    uploadCalls[0].url,
    "http://localhost:8128/api/v1/student/extension-proof/sessions/session-reactplay-real/upload",
  )
  // Every backend request used the configured API base and the Bearer token.
  for (const call of backendCalls) {
    assert.ok(call.url.startsWith("http://localhost:8128/"), `unexpected API base: ${call.url}`)
    assert.equal(call.headers["Authorization"], "Bearer private-token")
  }
  // Side evidence (visible evidence + visual frames) settled before the upload.
  assert.ok(backendCalls.some((c) => c.url.includes("/workflow/visual-frames")))

  // The persisted snapshot reflects the acknowledged upload for SW-restart safety.
  assert.equal(stored.lastUploadedSessionId, config.session_id)

  // ── QA-D-002: a stale recorder tab's upload state is never credited ───────
  // Upload lifecycle messages stamped with a DIFFERENT session id (a recorder
  // tab left open from a previous session) must be ignored, not applied to
  // the active session.
  const staleStart = await send("RECORDER_VIDEO_UPLOAD_STARTED", {
    session_id: "session-stale-tab",
  })
  assert.equal(staleStart.ignored, true)
  const staleResult = await send("RECORDER_VIDEO_UPLOADED", {
    ok: true, error: null, keyframe_count: 99, session_id: "session-stale-tab",
  })
  assert.equal(staleResult.ignored, true)
  const afterStale = await send("GET_STATE", {})
  assert.equal(afterStale.videoUploadStatus, "uploaded")
  assert.equal(afterStale.videoKeyframeCount, 5)

  // A result stamped with the ACTIVE session still applies normally.
  const matchedResult = await send("RECORDER_VIDEO_UPLOADED", {
    ok: true, error: null, keyframe_count: 7, session_id: config.session_id,
  })
  assert.equal(matchedResult.ok, true)
  const afterMatched = await send("GET_STATE", {})
  assert.equal(afterMatched.videoKeyframeCount, 7)
})
