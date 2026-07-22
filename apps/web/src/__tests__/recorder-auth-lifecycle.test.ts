/**
 * Recorder auth lifecycle — locks down the extension-side token contract that
 * keeps every recorder upload (visible-evidence, visual-frames, video, upload,
 * live-feedback) owner-authenticated:
 *
 *   • START_RECORDING without any token is REJECTED (no doomed recordings);
 *   • an explicit popup token wins, the app-handed token is the fallback;
 *   • a service-worker restart restores the token from chrome.storage.local
 *     (structured record preferred, legacy keys still honored);
 *   • a missing token yields NO headers → callers must skip the POST entirely
 *     (fail closed — an anonymous POST is never constructible);
 *   • the handoff ACK and debug state NEVER contain the token value.
 *
 * Imports the real module used by background.ts / recorder.ts — these are not
 * re-implemented copies.
 */

import { describe, expect, it } from "vitest"

import {
  authorizedJsonHeaders,
  authorizedUploadHeaders,
  buildRecorderAuthAck,
  buildRecorderAuthDebugState,
  isTrustedVeriBridgeAppUrl,
  MISSING_RECORDER_AUTH_MESSAGE,
  normalizeApiUrl,
  persistRecorderAuthAndVerify,
  RECORDER_AUTH_BUILD_FINGERPRINT,
  RECORDER_AUTH_STORAGE_KEY,
  recorderTokenMetadata,
  resolveStartRecordingAuth,
  restoreRecorderAuth,
  uploadEndpointUrl,
  validateRecorderAuthPayload,
} from "../../../extension/src/recorderAuth"

const TOKEN = `eyJhbGciOiJIUzI1NiJ9.${Buffer.from(JSON.stringify({ exp: 4102444800 })).toString("base64url")}.signature`

describe("resolveStartRecordingAuth (START_RECORDING gate)", () => {
  it("rejects when neither an explicit nor a stored token exists", () => {
    const result = resolveStartRecordingAuth("", "")
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error).toBe(MISSING_RECORDER_AUTH_MESSAGE)
  })

  it("rejects whitespace-only tokens (no anonymous recording)", () => {
    const result = resolveStartRecordingAuth("   ", "  ")
    expect(result.ok).toBe(false)
  })

  it("accepts and stores an explicit popup token", () => {
    const result = resolveStartRecordingAuth(TOKEN, "")
    expect(result).toEqual({ ok: true, authToken: TOKEN })
  })

  it("falls back to the app-handed stored token", () => {
    const result = resolveStartRecordingAuth("", TOKEN)
    expect(result).toEqual({ ok: true, authToken: TOKEN })
  })

  it("prefers the explicit token over the stored one", () => {
    const result = resolveStartRecordingAuth("explicit-token", TOKEN)
    expect(result).toEqual({ ok: true, authToken: "explicit-token" })
  })
})

describe("restoreRecorderAuth (service-worker restart)", () => {
  it("restores from the structured record, including apiUrl and sessionId", () => {
    const restored = restoreRecorderAuth(
      {
        [RECORDER_AUTH_STORAGE_KEY]: {
          authToken: TOKEN,
          apiUrl: "http://localhost:8000/",
          sessionId: "sess-1",
          updatedAt: "2026-07-09T00:00:00Z",
        },
      },
      "http://fallback:8000",
    )
    expect(restored).toEqual({
      authToken: TOKEN,
      apiUrl: "http://localhost:8000",
      sessionId: "sess-1",
      source: "storage",
    })
  })

  it("falls back to the legacy top-level keys from older builds", () => {
    const restored = restoreRecorderAuth(
      { authToken: TOKEN, apiUrl: "http://localhost:8000/" },
      "http://fallback:8000",
    )
    expect(restored.authToken).toBe(TOKEN)
    expect(restored.apiUrl).toBe("http://localhost:8000")
    expect(restored.source).toBe("storage")
  })

  it("prefers the structured record over legacy keys", () => {
    const restored = restoreRecorderAuth(
      {
        [RECORDER_AUTH_STORAGE_KEY]: { authToken: "new-token", updatedAt: "x" },
        authToken: "old-token",
      },
      "http://fallback:8000",
    )
    expect(restored.authToken).toBe("new-token")
  })

  it("reports source none (empty token) when storage has nothing", () => {
    const restored = restoreRecorderAuth({}, "http://fallback:8000")
    expect(restored).toEqual({
      authToken: "",
      apiUrl: "http://fallback:8000",
      sessionId: "",
      source: "none",
    })
  })

  it("ignores a malformed structured record instead of restoring garbage", () => {
    const restored = restoreRecorderAuth(
      { [RECORDER_AUTH_STORAGE_KEY]: { authToken: 42 } },
      "http://fallback:8000",
    )
    expect(restored.authToken).toBe("")
    expect(restored.source).toBe("none")
  })
})

describe("authorized headers (fail-closed upload guard)", () => {
  it.each(["visible-evidence", "visual-frames", "upload", "live-feedback"] as const)(
    "JSON POST to %s carries Authorization: Bearer when a token exists",
    (endpoint) => {
      const headers = authorizedJsonHeaders(TOKEN)
      expect(headers).not.toBeNull()
      expect(headers?.["Authorization"]).toBe(`Bearer ${TOKEN}`)
      expect(headers?.["Content-Type"]).toBe("application/json")
      const url = uploadEndpointUrl("http://localhost:8000", "sess-1", endpoint)
      expect(url).toContain("/api/v1/student/extension-proof/sessions/sess-1")
    },
  )

  it("video multipart POST carries Authorization: Bearer when a token exists", () => {
    const headers = authorizedUploadHeaders(TOKEN)
    expect(headers).toEqual({ Authorization: `Bearer ${TOKEN}` })
    expect(uploadEndpointUrl("http://localhost:8000", "sess-1", "video")).toBe(
      "http://localhost:8000/api/v1/student/extension-proof/sessions/sess-1/workflow/video",
    )
  })

  it("returns null (request must be skipped) when the token is missing", () => {
    expect(authorizedJsonHeaders("")).toBeNull()
    expect(authorizedJsonHeaders(null)).toBeNull()
    expect(authorizedJsonHeaders(undefined)).toBeNull()
    expect(authorizedUploadHeaders("")).toBeNull()
  })

  it("builds the exact backend endpoint URLs for every recorder POST", () => {
    const base = "http://localhost:8000/api/v1/student/extension-proof/sessions/sess-1"
    expect(uploadEndpointUrl("http://localhost:8000/", "sess-1", "visible-evidence")).toBe(
      `${base}/workflow/visible-evidence`,
    )
    expect(uploadEndpointUrl("http://localhost:8000", "sess-1", "visual-frames")).toBe(
      `${base}/workflow/visual-frames`,
    )
    expect(uploadEndpointUrl("http://localhost:8000", "sess-1", "video")).toBe(
      `${base}/workflow/video`,
    )
    expect(uploadEndpointUrl("http://localhost:8000", "sess-1", "upload")).toBe(`${base}/upload`)
  })
})

describe("token-free ACK and debug state (no token exposure)", () => {
  it("the ACK never contains the token value", () => {
    const ack = buildRecorderAuthAck({
      ok: true,
      hasAuthToken: true,
      buildId: RECORDER_AUTH_BUILD_FINGERPRINT,
      extensionId: "abcdefghijklmnopabcdefghijklmnop",
      sessionId: "sess-1",
      persistenceAttempted: true,
      persistenceSucceeded: true,
      readBackSucceeded: true,
      storedSessionMatches: true,
    })
    expect(JSON.stringify(ack)).not.toContain(TOKEN)
    expect(ack).toMatchObject({
      ok: true,
      hasAuthToken: true,
      buildId: RECORDER_AUTH_BUILD_FINGERPRINT,
      extensionId: "abcdefghijklmnopabcdefghijklmnop",
      sessionId: "sess-1",
      persistenceSucceeded: true,
      readBackSucceeded: true,
      storedSessionMatches: true,
      failureCategory: "none",
    })
    expect(Object.keys(ack).sort()).toEqual([
      "ackAt",
      "buildId",
      "extensionId",
      "failureCategory",
      "hasAuthToken",
      "ok",
      "persistenceAttempted",
      "persistenceSucceeded",
      "readBackSucceeded",
      "sessionId",
      "storedSessionMatches",
    ])
  })

  it("the debug state reports source/pending endpoints but never the token", () => {
    const debug = buildRecorderAuthDebugState({
      sessionId: "sess-1",
      hasAuthToken: true,
      authTokenSource: "storage",
      apiUrl: "http://localhost:8000",
      buildId: "build-1",
      lastAuthHandoffAt: "2026-07-09T00:00:00Z",
      isRecording: false,
      visibleEvidenceCount: 3,
      visualFrameCount: 0,
      recordingStoppedPendingSend: true,
    })
    expect(JSON.stringify(debug)).not.toContain(TOKEN)
    expect(debug.pendingUploadEndpoints).toEqual(["visible-evidence", "upload"])
    expect(debug.hasAuthToken).toBe(true)
    expect(debug.authTokenSource).toBe("storage")
    expect(Object.keys(debug).sort()).toEqual([
      "apiUrl",
      "authTokenSource",
      "buildId",
      "hasAuthToken",
      "isRecording",
      "lastAuthHandoffAt",
      "pendingUploadEndpoints",
      "sessionId",
    ])
  })
})

describe("recorder auth payload validation", () => {
  it("accepts a current JWT, session ID, and localhost API URL", () => {
    const result = validateRecorderAuthPayload({
      authToken: TOKEN,
      sessionId: "sess-1",
      apiUrl: "http://localhost:8000/",
    }, Date.UTC(2026, 6, 9))
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.value.apiUrl).toBe("http://localhost:8000")
      expect(result.tokenMetadata).toMatchObject({
        tokenPresent: true,
        jwtSegmentCount: 3,
        startsWithEy: true,
        expired: false,
      })
    }
  })

  it.each([
    [{ authToken: "", sessionId: "sess-1", apiUrl: "http://localhost:8000" }, "missing_token"],
    [{ authToken: "opaque-token", sessionId: "sess-1", apiUrl: "http://localhost:8000" }, "invalid_token_shape"],
    [{ authToken: TOKEN, sessionId: "", apiUrl: "http://localhost:8000" }, "missing_session_id"],
    [{ authToken: TOKEN, sessionId: "sess-1", apiUrl: "javascript:alert(1)" }, "invalid_api_url"],
  ] as const)("rejects invalid input safely: %s", (input, category) => {
    const result = validateRecorderAuthPayload(input, Date.UTC(2026, 6, 9))
    expect(result).toMatchObject({ ok: false, failureCategory: category })
    expect(JSON.stringify(result)).not.toContain(TOKEN)
  })

  it("rejects an expired JWT", () => {
    const expired = `eyJhbGciOiJIUzI1NiJ9.${Buffer.from(JSON.stringify({ exp: 1 })).toString("base64url")}.signature`
    expect(validateRecorderAuthPayload({
      authToken: expired,
      sessionId: "sess-1",
      apiUrl: "http://localhost:8000",
    }, Date.UTC(2026, 6, 9))).toMatchObject({ ok: false, failureCategory: "expired_token" })
    expect(recorderTokenMetadata(expired, Date.UTC(2026, 6, 9)).expired).toBe(true)
  })
})

describe("trusted VeriBridge app origin", () => {
  it.each([
    "http://localhost:3000/student/proofs/website",
    "http://127.0.0.1:3000/dashboard",
    "https://app.veribridge.ai/student/proofs/website",
    "https://veribridgeai.com/student/proofs/website",
  ])("accepts %s", (url) => expect(isTrustedVeriBridgeAppUrl(url)).toBe(true))

  it.each([
    "http://localhost:3000/login",
    "https://evil.example/student/proofs/website",
    "https://veribridge.ai.evil.example/student/proofs/website",
  ])("rejects %s", (url) => expect(isTrustedVeriBridgeAppUrl(url)).toBe(false))
})

describe("persistRecorderAuthAndVerify", () => {
  it("ACK eligibility follows storage completion and exact read-back", async () => {
    const events: string[] = []
    const values: Record<string, unknown> = {}
    const storage = {
      async set(items: Record<string, unknown>) {
        events.push("write")
        Object.assign(values, items)
      },
      async get() {
        events.push("read")
        return values
      },
    }
    const result = await persistRecorderAuthAndVerify(storage, {
      authToken: TOKEN,
      apiUrl: "http://localhost:8000",
      sessionId: "sess-1",
    }, "2026-07-09T00:00:00.000Z")
    expect(events).toEqual(["write", "read"])
    expect(result).toEqual({
      ok: true,
      persistenceAttempted: true,
      persistenceSucceeded: true,
      readBackSucceeded: true,
      storedSessionMatches: true,
      failureCategory: "none",
    })
  })

  it("fails closed when read-back belongs to another session", async () => {
    const storage = {
      async set() {},
      async get() {
        return {
          [RECORDER_AUTH_STORAGE_KEY]: {
            authToken: TOKEN,
            apiUrl: "http://localhost:8000",
            sessionId: "sess-other",
            updatedAt: "2026-07-09T00:00:00.000Z",
          },
        }
      },
    }
    expect(await persistRecorderAuthAndVerify(storage, {
      authToken: TOKEN,
      apiUrl: "http://localhost:8000",
      sessionId: "sess-1",
    })).toMatchObject({
      ok: false,
      readBackSucceeded: true,
      storedSessionMatches: false,
      failureCategory: "storage_readback_mismatch",
    })
  })

  it("fails closed on storage write or read errors", async () => {
    await expect(persistRecorderAuthAndVerify({
      async set() { throw new Error("quota") },
      async get() { return {} },
    }, { authToken: TOKEN, apiUrl: "http://localhost:8000", sessionId: "sess-1" }))
      .resolves.toMatchObject({ ok: false, failureCategory: "storage_write_failed" })

    await expect(persistRecorderAuthAndVerify({
      async set() {},
      async get() { throw new Error("read") },
    }, { authToken: TOKEN, apiUrl: "http://localhost:8000", sessionId: "sess-1" }))
      .resolves.toMatchObject({ ok: false, failureCategory: "storage_read_failed" })
  })
})

describe("normalizeApiUrl", () => {
  it("strips trailing slashes and applies the fallback", () => {
    expect(normalizeApiUrl("http://localhost:8000/", "x")).toBe("http://localhost:8000")
    expect(normalizeApiUrl("", "http://localhost:8000")).toBe("http://localhost:8000")
    expect(normalizeApiUrl(undefined, "http://localhost:8000/")).toBe("http://localhost:8000")
  })
})
