import assert from "node:assert/strict"
import test from "node:test"

import {
  RecorderFinalizeMachine,
  awaitMediaFinalization,
  classifyDisplaySurface,
  finalizeRequestMatchesSession,
  shouldResetRecorderSessionState,
  uploadRecordingOnce,
  validateRecordingBlob,
  MIN_RECORDING_BYTES,
  WPR_AUTH_UNAVAILABLE,
  WPR_EMPTY_RECORDING,
  WPR_FINAL_CHUNK_TIMEOUT,
  WPR_MEDIA_FINALIZATION_FAILED,
  WPR_SESSION_MISMATCH,
  WPR_UPLOAD_ACK_LOST,
  WPR_UPLOAD_NETWORK_FAILED,
  WPR_UPLOAD_REJECTED,
  type FinalizableRecorder,
  type PendingVideoUpload,
} from "../src/recorderFinalize.ts"

// ── Finalize state machine ────────────────────────────────────────────────────

test("finalize machine allows the durable happy path in order", () => {
  const m = new RecorderFinalizeMachine("recording")
  m.to("stop_requested")
  m.to("flushing_final_chunks")
  m.to("media_finalized")
  m.to("ready_to_upload")
  m.to("uploading")
  m.to("upload_acknowledged")
  m.to("completed")
  assert.equal(m.phase, "completed")
})

test("finalize machine never reaches COMPLETED before backend acknowledgment", () => {
  const m = new RecorderFinalizeMachine("recording")
  m.to("stop_requested")
  m.to("flushing_final_chunks")
  m.to("media_finalized")
  m.to("ready_to_upload")
  m.to("uploading")
  assert.throws(() => m.to("completed"), /Illegal recorder finalize transition/)
  // A failed upload keeps a retry path with the same pipeline
  m.to("upload_failed")
  assert.throws(() => m.to("completed"), /Illegal/)
  m.to("uploading")
  m.to("upload_acknowledged")
  m.to("completed")
})

test("finalize machine supports recovery entry at ready_to_upload", () => {
  const m = new RecorderFinalizeMachine("ready_to_upload")
  m.to("uploading")
  m.to("upload_failed")
  m.to("uploading")
  m.to("upload_acknowledged")
  m.to("completed")
  assert.throws(() => m.to("uploading"), /Illegal/)
})

// ── MediaRecorder finalization ────────────────────────────────────────────────

class FakeRecorder implements FinalizableRecorder {
  state: "inactive" | "recording" | "paused" = "recording"
  stopCalls = 0
  throwOnStop = false
  autoFireStop = true
  events: string[] = []
  private listeners = new Map<string, Array<(ev?: unknown) => void>>()

  stop(): void {
    this.stopCalls += 1
    if (this.throwOnStop) throw new Error("InvalidStateError")
    if (!this.autoFireStop) return
    // MediaRecorder spec ordering: final dataavailable, THEN stop.
    queueMicrotask(() => {
      this.state = "inactive"
      this.emit("dataavailable")
      this.emit("stop")
    })
  }

  addEventListener(type: string, listener: (ev?: unknown) => void): void {
    const list = this.listeners.get(type) ?? []
    list.push(listener)
    this.listeners.set(type, list)
  }

  removeEventListener(type: string, listener: (ev?: unknown) => void): void {
    const list = this.listeners.get(type) ?? []
    this.listeners.set(type, list.filter((l) => l !== listener))
  }

  emit(type: string): void {
    this.events.push(type)
    for (const listener of this.listeners.get(type) ?? []) listener()
  }
}

test("awaitMediaFinalization stops the recorder and resolves only after the stop event", async () => {
  const rec = new FakeRecorder()
  const chunks: string[] = []
  rec.addEventListener("dataavailable", () => chunks.push("final-chunk"))
  const result = await awaitMediaFinalization(rec)
  assert.deepEqual(result, { ok: true })
  assert.equal(rec.stopCalls, 1)
  // Final chunk was flushed BEFORE stop resolved (spec ordering honored).
  assert.deepEqual(rec.events, ["dataavailable", "stop"])
  assert.deepEqual(chunks, ["final-chunk"])
})

test("awaitMediaFinalization is immediate for an already-inactive recorder", async () => {
  const rec = new FakeRecorder()
  rec.state = "inactive"
  const result = await awaitMediaFinalization(rec)
  assert.deepEqual(result, { ok: true })
  assert.equal(rec.stopCalls, 0)
})

test("awaitMediaFinalization times out with WPR-FINAL-CHUNK-TIMEOUT when stop never fires", async () => {
  const rec = new FakeRecorder()
  rec.autoFireStop = false
  const result = await awaitMediaFinalization(rec, { timeoutMs: 30 })
  assert.equal(result.ok, false)
  if (!result.ok) assert.equal(result.code, WPR_FINAL_CHUNK_TIMEOUT)
})

test("awaitMediaFinalization maps a throwing stop() to WPR-MEDIA-FINALIZATION-FAILED", async () => {
  const rec = new FakeRecorder()
  rec.throwOnStop = true
  const result = await awaitMediaFinalization(rec, { timeoutMs: 1000 })
  assert.equal(result.ok, false)
  if (!result.ok) assert.equal(result.code, WPR_MEDIA_FINALIZATION_FAILED)
})

// ── Blob validation ───────────────────────────────────────────────────────────

test("validateRecordingBlob rejects an empty or near-empty recording", () => {
  const empty = validateRecordingBlob({ size: 0 })
  assert.equal(empty.ok, false)
  if (!empty.ok) assert.equal(empty.code, WPR_EMPTY_RECORDING)
  const tiny = validateRecordingBlob({ size: MIN_RECORDING_BYTES - 1 })
  assert.equal(tiny.ok, false)
})

test("validateRecordingBlob accepts a real recording", () => {
  assert.deepEqual(validateRecordingBlob({ size: 5_000_000 }), { ok: true })
})

// ── Upload (idempotent, retry-safe) ───────────────────────────────────────────

function makeRecord(overrides: Partial<PendingVideoUpload> = {}): PendingVideoUpload {
  return {
    session_id: "sess-123",
    upload_id: "upload-abc",
    mime_type: "video/webm",
    duration_ms: 92_000,
    display_surface: "screen",
    created_at: new Date().toISOString(),
    attempt_count: 1,
    ...overrides,
  }
}

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

test("uploadRecordingOnce posts multipart video with bearer auth and idempotency key", async () => {
  const calls: Array<{ url: string; init: RequestInit }> = []
  const fetchFn = (async (url: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(url), init: init ?? {} })
    return jsonResponse(202, {
      keyframe_count: 8,
      video_analysis_status: "analyzed",
      replay_retained: true,
    })
  }) as typeof fetch

  const result = await uploadRecordingOnce({
    apiBaseUrl: "http://localhost:8128/",
    authToken: "token-1",
    record: makeRecord(),
    blob: new Blob(["x".repeat(500)], { type: "video/webm" }),
    fetchFn,
  })

  assert.equal(result.ok, true)
  if (result.ok) assert.equal(result.keyframe_count, 8)
  assert.equal(calls.length, 1)
  assert.equal(
    calls[0].url,
    "http://localhost:8128/api/v1/student/extension-proof/sessions/sess-123/workflow/video",
  )
  const headers = calls[0].init.headers as Record<string, string>
  assert.equal(headers["Authorization"], "Bearer token-1")
  assert.equal(headers["X-Idempotency-Key"], "upload-abc")
  assert.ok(calls[0].init.body instanceof FormData)
  const file = (calls[0].init.body as FormData).get("video")
  assert.ok(file instanceof Blob)
})

test("uploadRecordingOnce refuses to upload without an auth token (no request sent)", async () => {
  let fetched = 0
  const fetchFn = (async () => {
    fetched += 1
    return jsonResponse(202, {})
  }) as typeof fetch
  const result = await uploadRecordingOnce({
    apiBaseUrl: "http://localhost:8128",
    authToken: "",
    record: makeRecord(),
    blob: new Blob(["x".repeat(500)]),
    fetchFn,
  })
  assert.equal(result.ok, false)
  if (!result.ok) {
    assert.equal(result.code, WPR_AUTH_UNAVAILABLE)
    assert.equal(result.retryable, true)
  }
  assert.equal(fetched, 0)
})

test("uploadRecordingOnce refuses a recording with no bound session", async () => {
  const result = await uploadRecordingOnce({
    apiBaseUrl: "http://localhost:8128",
    authToken: "token",
    record: makeRecord({ session_id: "" }),
    blob: new Blob(["x".repeat(500)]),
    fetchFn: (async () => jsonResponse(202, {})) as typeof fetch,
  })
  assert.equal(result.ok, false)
  if (!result.ok) assert.equal(result.code, WPR_SESSION_MISMATCH)
})

test("uploadRecordingOnce maps 401/403 to WPR-AUTH-UNAVAILABLE (retryable after re-auth)", async () => {
  for (const status of [401, 403]) {
    const result = await uploadRecordingOnce({
      apiBaseUrl: "http://localhost:8128",
      authToken: "expired",
      record: makeRecord(),
      blob: new Blob(["x".repeat(500)]),
      fetchFn: (async () => jsonResponse(status, { detail: "auth failed" })) as typeof fetch,
    })
    assert.equal(result.ok, false)
    if (!result.ok) {
      assert.equal(result.code, WPR_AUTH_UNAVAILABLE)
      assert.equal(result.retryable, true)
    }
  }
})

test("uploadRecordingOnce classifies backend rejections by retryability", async () => {
  const transient = await uploadRecordingOnce({
    apiBaseUrl: "http://localhost:8128",
    authToken: "token",
    record: makeRecord(),
    blob: new Blob(["x".repeat(500)]),
    fetchFn: (async () => jsonResponse(500, { detail: "boom" })) as typeof fetch,
  })
  assert.equal(transient.ok, false)
  if (!transient.ok) {
    assert.equal(transient.code, WPR_UPLOAD_REJECTED)
    assert.equal(transient.retryable, true)
    assert.equal(transient.message, "boom")
  }

  const permanent = await uploadRecordingOnce({
    apiBaseUrl: "http://localhost:8128",
    authToken: "token",
    record: makeRecord(),
    blob: new Blob(["x".repeat(500)]),
    fetchFn: (async () => jsonResponse(422, { detail: { message: "bad payload" } })) as typeof fetch,
  })
  assert.equal(permanent.ok, false)
  if (!permanent.ok) {
    assert.equal(permanent.code, WPR_UPLOAD_REJECTED)
    assert.equal(permanent.retryable, false)
  }
})

test("uploadRecordingOnce marks network failures as retryable with uncertain acknowledgment", async () => {
  const result = await uploadRecordingOnce({
    apiBaseUrl: "http://localhost:8128",
    authToken: "token",
    record: makeRecord(),
    blob: new Blob(["x".repeat(500)]),
    fetchFn: (async () => { throw new TypeError("Failed to fetch") }) as typeof fetch,
  })
  assert.equal(result.ok, false)
  if (!result.ok) {
    assert.equal(result.code, WPR_UPLOAD_NETWORK_FAILED)
    assert.equal(result.retryable, true)
    assert.equal(result.ack_uncertain, true)
  }
})

test("uploadRecordingOnce treats an unreadable 2xx acknowledgment as ack-lost (safe retry)", async () => {
  const result = await uploadRecordingOnce({
    apiBaseUrl: "http://localhost:8128",
    authToken: "token",
    record: makeRecord(),
    blob: new Blob(["x".repeat(500)]),
    fetchFn: (async () => ({
      ok: true,
      status: 202,
      text: async () => "<html>gateway mangled</html>",
    } as unknown as Response)) as typeof fetch,
  })
  assert.equal(result.ok, false)
  if (!result.ok) {
    assert.equal(result.code, WPR_UPLOAD_ACK_LOST)
    assert.equal(result.retryable, true)
    assert.equal(result.ack_uncertain, true)
  }
})

test("uploadRecordingOnce fails when the backend did not retain the replay", async () => {
  const result = await uploadRecordingOnce({
    apiBaseUrl: "http://localhost:8128",
    authToken: "token",
    record: makeRecord(),
    blob: new Blob(["x".repeat(500)]),
    fetchFn: (async () => jsonResponse(202, {
      keyframe_count: 4,
      video_analysis_status: "analyzed",
      replay_retained: false,
    })) as typeof fetch,
  })
  assert.equal(result.ok, false)
  if (!result.ok) {
    assert.equal(result.code, WPR_UPLOAD_REJECTED)
    assert.equal(result.retryable, true)
  }
})

test("retrying an upload reuses the exact same upload id (idempotency key)", async () => {
  const seenKeys: string[] = []
  const record = makeRecord()
  const failThenSucceed = (() => {
    let call = 0
    return (async (_url: RequestInfo | URL, init?: RequestInit) => {
      seenKeys.push((init?.headers as Record<string, string>)["X-Idempotency-Key"])
      call += 1
      if (call === 1) throw new TypeError("Failed to fetch")
      return jsonResponse(202, {
        keyframe_count: 3,
        video_analysis_status: "analyzed",
        replay_retained: true,
      })
    }) as typeof fetch
  })()

  const blob = new Blob(["x".repeat(500)])
  const first = await uploadRecordingOnce({
    apiBaseUrl: "http://localhost:8128", authToken: "token", record, blob, fetchFn: failThenSucceed,
  })
  assert.equal(first.ok, false)
  const second = await uploadRecordingOnce({
    apiBaseUrl: "http://localhost:8128", authToken: "token", record, blob, fetchFn: failThenSucceed,
  })
  assert.equal(second.ok, true)
  assert.deepEqual(seenKeys, ["upload-abc", "upload-abc"])
})

// ── Capture scope classification ──────────────────────────────────────────────

test("classifyDisplaySurface maps Chrome surfaces to product capture scopes", () => {
  const tab = classifyDisplaySurface("browser")
  assert.equal(tab.scope, "tab")
  assert.equal(tab.capturesOtherWindows, false)
  assert.match(tab.warning ?? "", /NOT be captured/)

  const win = classifyDisplaySurface("window")
  assert.equal(win.scope, "window")
  assert.equal(win.capturesOtherWindows, false)
  assert.match(win.warning ?? "", /Entire Screen/)

  const screen = classifyDisplaySurface("monitor")
  assert.equal(screen.scope, "screen")
  assert.equal(screen.capturesOtherWindows, true)
  assert.equal(screen.warning, null)
})

test("classifyDisplaySurface is cautious when the browser reports nothing", () => {
  for (const value of [undefined, null, "", "something-new"]) {
    const info = classifyDisplaySurface(value as string | null | undefined)
    assert.equal(info.capturesOtherWindows, false)
    assert.ok(info.warning)
  }
})

// ── Session-scoped recorder tab state (multi-tab safety) ─────────────────────
// Real-user failure (QA-D-002): a recorder tab left open after finishing one
// session answered the NEXT session's finalize broadcast with its own
// uploadDone state, so a session whose screen capture never started was
// reported as "uploaded" with the previous session's keyframe count.

test("shouldResetRecorderSessionState resets a stale idle tab when the session changes", () => {
  assert.equal(shouldResetRecorderSessionState("session-old", "session-new", false), true)
})

test("shouldResetRecorderSessionState never resets mid-capture or mid-upload", () => {
  assert.equal(shouldResetRecorderSessionState("session-old", "session-new", true), false)
})

test("shouldResetRecorderSessionState is a no-op for same, empty, or first session", () => {
  assert.equal(shouldResetRecorderSessionState("session-a", "session-a", false), false)
  assert.equal(shouldResetRecorderSessionState("", "session-a", false), false)
  assert.equal(shouldResetRecorderSessionState("session-a", "", false), false)
})

test("finalizeRequestMatchesSession silences a tab bound to a different session", () => {
  assert.equal(finalizeRequestMatchesSession("session-new", "session-old"), false)
})

test("finalizeRequestMatchesSession answers for its own session", () => {
  assert.equal(finalizeRequestMatchesSession("session-a", "session-a"), true)
})

test("finalizeRequestMatchesSession stays compatible with untargeted or unbound requests", () => {
  assert.equal(finalizeRequestMatchesSession(undefined, "session-a"), true)
  assert.equal(finalizeRequestMatchesSession(null, "session-a"), true)
  assert.equal(finalizeRequestMatchesSession("", "session-a"), true)
  assert.equal(finalizeRequestMatchesSession("session-a", ""), true)
})
