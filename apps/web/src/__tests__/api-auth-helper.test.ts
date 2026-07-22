/**
 * Tests for the central authenticated fetch helper (`fetchAPI`).
 *
 * Locks down the frontend half of the tenant-isolation contract:
 *   • a signed-in session's access token is attached as Authorization: Bearer;
 *   • with NO session, auth-required student/admin paths are never sent to the
 *     API anonymously — they resolve to a local 401 (auth_session_missing);
 *   • dual owner/public paths (optional-auth backend routes) still go out
 *     anonymously so public recruiter surfaces keep working;
 *   • a backend 401 token_expired triggers one session refresh + retry.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const getSession = vi.fn()
const refreshSession = vi.fn()

vi.mock("@/lib/supabase/client", () => ({
  createSupabaseBrowserClient: () => ({
    auth: { getSession, refreshSession },
  }),
}))

import {
  AUTH_SESSION_MISSING_CODE,
  confirmRecorderAuthWithExtension,
  fetchAPI,
  isRecorderAuthRequestMessage,
  publishRecorderAuthToExtension,
  RECORDER_AUTH_ACK_MESSAGE_TYPE,
  RECORDER_AUTH_BUILD_FINGERPRINT,
  RECORDER_AUTH_MESSAGE_SOURCE,
  RECORDER_AUTH_MESSAGE_TYPE,
  RECORDER_AUTH_REQUEST_MESSAGE_TYPE,
  RECORDER_EXTENSION_MESSAGE_SOURCE,
} from "@/lib/api"

const fetchMock = vi.fn()

function sessionOf(token: string | null) {
  return { data: { session: token ? { access_token: token } : null } }
}

function recorderToken(exp = 4102444800): string {
  return `eyJhbGciOiJIUzI1NiJ9.${btoa(JSON.stringify({ exp }))}.signature`
}

function recorderSessionOf(token: string | null, expiresAt = 4102444800) {
  return { data: { session: token ? { access_token: token, expires_at: expiresAt } : null } }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

beforeEach(() => {
  getSession.mockReset()
  refreshSession.mockReset()
  fetchMock.mockReset()
  vi.stubGlobal("fetch", fetchMock)
})

afterEach(() => {
  vi.useRealTimers()
})

describe("fetchAPI", () => {
  it("attaches the session access token as a Bearer header", async () => {
    getSession.mockResolvedValue(sessionOf("user-a-token"))
    fetchMock.mockResolvedValue(jsonResponse([]))

    const res = await fetchAPI("/api/v1/student/github-proofs")

    expect(res.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain("/api/v1/student/github-proofs")
    expect((init.headers as Record<string, string>)["Authorization"]).toBe(
      "Bearer user-a-token"
    )
  })

  it("never calls an auth-required student path anonymously", async () => {
    getSession.mockResolvedValue(sessionOf(null))

    const res = await fetchAPI("/api/v1/student/document-proofs")

    expect(fetchMock).not.toHaveBeenCalled()
    expect(res.status).toBe(401)
    const body = await res.json()
    expect(body.detail.code).toBe(AUTH_SESSION_MISSING_CODE)
  })

  it("never calls an auth-required admin path anonymously", async () => {
    getSession.mockResolvedValue(sessionOf(null))

    const res = await fetchAPI("/api/v1/admin/verification-reviews")

    expect(fetchMock).not.toHaveBeenCalled()
    expect(res.status).toBe(401)
  })

  it("still sends dual owner/public paths anonymously (no Authorization header)", async () => {
    getSession.mockResolvedValue(sessionOf(null))
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }))

    const res = await fetchAPI("/api/v1/proofs/artifacts/art-1/view")

    expect(res.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0]
    expect(
      (init.headers as Record<string, string>)["Authorization"]
    ).toBeUndefined()
  })

  it("refreshes the session once and retries when the backend says token_expired", async () => {
    getSession.mockResolvedValue(sessionOf("stale-token"))
    refreshSession.mockResolvedValue(sessionOf("fresh-token"))
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ detail: { code: "token_expired" } }, 401)
      )
      .mockResolvedValueOnce(jsonResponse([{ id: "proof-1" }]))

    const res = await fetchAPI("/api/v1/student/github-proofs")

    expect(refreshSession).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    const [, retryInit] = fetchMock.mock.calls[1]
    expect((retryInit.headers as Record<string, string>)["Authorization"]).toBe(
      "Bearer fresh-token"
    )
    expect(res.status).toBe(200)
  })

  it("surfaces the 401 unchanged when the refresh yields no new token", async () => {
    getSession.mockResolvedValue(sessionOf("stale-token"))
    refreshSession.mockResolvedValue(sessionOf(null))
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: { code: "token_expired" } }, 401)
    )

    const res = await fetchAPI("/api/v1/student/github-proofs")

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(res.status).toBe(401)
  })

  it("does not retry non-expiry 401s (invalid token fails closed)", async () => {
    getSession.mockResolvedValue(sessionOf("bad-token"))
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: { code: "invalid_token" } }, 401)
    )

    const res = await fetchAPI("/api/v1/student/vbr/projects")

    expect(refreshSession).not.toHaveBeenCalled()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(res.status).toBe(401)
  })
})

describe("publishRecorderAuthToExtension", () => {
  it("posts the signed-in access token to same-origin listeners only", async () => {
    vi.useFakeTimers()
    const token = recorderToken()
    getSession.mockResolvedValue(recorderSessionOf(token))
    const postMessage = vi.fn()
    vi.spyOn(window, "postMessage").mockImplementation(postMessage as never)

    const published = await publishRecorderAuthToExtension()
    await vi.runAllTimersAsync()

    expect(published).toBe(true)
    expect(postMessage).toHaveBeenCalledTimes(4)
    for (const [message, targetOrigin] of postMessage.mock.calls) {
      expect(message.source).toBe(RECORDER_AUTH_MESSAGE_SOURCE)
      expect(message.type).toBe(RECORDER_AUTH_MESSAGE_TYPE)
      expect(message.payload.authToken).toBe(token)
      expect(message.payload.buildFingerprint).toBe(RECORDER_AUTH_BUILD_FINGERPRINT)
      // Origin-pinned: never broadcast with "*", so the external target site the
      // recorder is visiting can never receive the token.
      expect(targetOrigin).toBe(window.location.origin)
      expect(targetOrigin).not.toBe("*")
    }
  })

  it("publishes nothing when the user is signed out", async () => {
    vi.useFakeTimers()
    getSession.mockResolvedValue(sessionOf(null))
    const postMessage = vi.fn()
    vi.spyOn(window, "postMessage").mockImplementation(postMessage as never)

    const published = await publishRecorderAuthToExtension()
    await vi.runAllTimersAsync()

    expect(published).toBe(false)
    expect(postMessage).not.toHaveBeenCalled()
  })

  it("keys the handoff to the proof session when a sessionId is provided", async () => {
    vi.useFakeTimers()
    getSession.mockResolvedValue(recorderSessionOf(recorderToken()))
    const postMessage = vi.fn()
    vi.spyOn(window, "postMessage").mockImplementation(postMessage as never)

    const published = await publishRecorderAuthToExtension("sess-42")
    await vi.runAllTimersAsync()

    expect(published).toBe(true)
    for (const [message] of postMessage.mock.calls) {
      expect(message.payload.sessionId).toBe("sess-42")
    }
  })

  it("refreshes an expired session immediately before publishing", async () => {
    vi.useFakeTimers()
    const expired = recorderToken(1)
    const fresh = recorderToken()
    getSession.mockResolvedValue(recorderSessionOf(expired, 1))
    refreshSession.mockResolvedValue(recorderSessionOf(fresh))
    const postMessage = vi.fn()
    vi.spyOn(window, "postMessage").mockImplementation(postMessage as never)

    expect(await publishRecorderAuthToExtension("sess-refresh")).toBe(true)
    await vi.runAllTimersAsync()

    expect(refreshSession).toHaveBeenCalledTimes(1)
    expect(postMessage.mock.calls[0][0].payload.authToken).toBe(fresh)
  })

  it("fails closed when refresh still yields an expired token", async () => {
    getSession.mockResolvedValue(recorderSessionOf(recorderToken(1), 1))
    refreshSession.mockResolvedValue(recorderSessionOf(recorderToken(2), 2))
    const postMessage = vi.fn()
    vi.spyOn(window, "postMessage").mockImplementation(postMessage as never)

    expect(await publishRecorderAuthToExtension("sess-expired")).toBe(false)
    expect(postMessage).not.toHaveBeenCalled()
  })
})

describe("confirmRecorderAuthWithExtension", () => {
  function confirmedAck(sessionId = "sess-1") {
    return {
      ok: true,
      hasAuthToken: true,
      buildId: RECORDER_AUTH_BUILD_FINGERPRINT,
      extensionId: "abcdefghijklmnopabcdefghijklmnop",
      sessionId,
      persistenceAttempted: true,
      persistenceSucceeded: true,
      readBackSucceeded: true,
      storedSessionMatches: true,
      failureCategory: "none",
    }
  }

  function dispatchAck(payload: Record<string, unknown>) {
    window.dispatchEvent(
      new MessageEvent("message", {
        data: {
          source: RECORDER_EXTENSION_MESSAGE_SOURCE,
          type: RECORDER_AUTH_ACK_MESSAGE_TYPE,
          payload,
        },
        origin: window.location.origin,
        source: window,
      }),
    )
  }

  it("resolves confirmed=true when the extension ACKs holding the token", async () => {
    getSession.mockResolvedValue(recorderSessionOf(recorderToken()))
    vi.spyOn(window, "postMessage").mockImplementation(() => undefined)

    const pending = confirmRecorderAuthWithExtension("sess-1", 1000)
    await Promise.resolve() // let the publish resolve and install the listener
    dispatchAck(confirmedAck())

    const result = await pending
    expect(result.published).toBe(true)
    expect(result.confirmed).toBe(true)
    expect(result.ack?.buildId).toBe(RECORDER_AUTH_BUILD_FINGERPRINT)
    expect(JSON.stringify(result.ack)).not.toContain(recorderToken())
  })

  it("resolves confirmed=false when the extension reports it has no token", async () => {
    getSession.mockResolvedValue(recorderSessionOf(recorderToken()))
    vi.spyOn(window, "postMessage").mockImplementation(() => undefined)

    const pending = confirmRecorderAuthWithExtension("sess-1", 1000)
    await Promise.resolve()
    dispatchAck({
      ...confirmedAck(),
      ok: false,
      hasAuthToken: false,
      persistenceSucceeded: false,
      readBackSucceeded: false,
      storedSessionMatches: false,
      failureCategory: "storage_write_failed",
    })

    const result = await pending
    expect(result.confirmed).toBe(false)
  })

  it("ignores a wrong-session ACK and accepts the later current-session ACK", async () => {
    getSession.mockResolvedValue(recorderSessionOf(recorderToken()))
    vi.spyOn(window, "postMessage").mockImplementation(() => undefined)

    const pending = confirmRecorderAuthWithExtension("sess-1", 1000)
    await Promise.resolve()
    dispatchAck(confirmedAck("sess-2"))
    dispatchAck(confirmedAck("sess-1"))

    const result = await pending
    expect(result.published).toBe(true)
    expect(result.confirmed).toBe(true)
    expect(result.ack?.sessionId).toBe("sess-1")
  })

  it("detects a stale content-script/build ACK and times out safely", async () => {
    getSession.mockResolvedValue(recorderSessionOf(recorderToken()))
    vi.spyOn(window, "postMessage").mockImplementation(() => undefined)

    const pending = confirmRecorderAuthWithExtension("sess-1", 20)
    await Promise.resolve()
    dispatchAck({ ...confirmedAck(), buildId: "stale-build" })

    const result = await pending
    expect(result.confirmed).toBe(false)
    expect(result.ack).toBeNull()
  })

  it("times out to confirmed=false when no extension ever ACKs", async () => {
    getSession.mockResolvedValue(recorderSessionOf(recorderToken()))
    vi.spyOn(window, "postMessage").mockImplementation(() => undefined)

    const result = await confirmRecorderAuthWithExtension("sess-1", 20)
    expect(result.published).toBe(true)
    expect(result.confirmed).toBe(false)
    expect(result.ack).toBeNull()
  })

  it("never publishes or confirms when signed out", async () => {
    getSession.mockResolvedValue(sessionOf(null))
    const postMessage = vi.fn()
    vi.spyOn(window, "postMessage").mockImplementation(postMessage as never)

    const result = await confirmRecorderAuthWithExtension("sess-1", 20)
    expect(result).toEqual({ published: false, confirmed: false, ack: null })
    expect(postMessage).not.toHaveBeenCalled()
  })
})

describe("isRecorderAuthRequestMessage", () => {
  function requestEvent(overrides: Partial<{ data: unknown; origin: string; source: unknown }> = {}) {
    return new MessageEvent("message", {
      data: overrides.data ?? {
        source: RECORDER_EXTENSION_MESSAGE_SOURCE,
        type: RECORDER_AUTH_REQUEST_MESSAGE_TYPE,
      },
      origin: (overrides.origin as string) ?? window.location.origin,
      source: (overrides.source as Window) ?? window,
    })
  }

  it("accepts the extension's same-origin re-publish request", () => {
    expect(isRecorderAuthRequestMessage(requestEvent())).toBe(true)
  })

  it("rejects cross-origin messages (target site can never trigger a publish)", () => {
    expect(
      isRecorderAuthRequestMessage(requestEvent({ origin: "https://evil.example.com" })),
    ).toBe(false)
  })

  it("rejects messages from other sources or types", () => {
    expect(
      isRecorderAuthRequestMessage(
        requestEvent({ data: { source: "someone-else", type: RECORDER_AUTH_REQUEST_MESSAGE_TYPE } }),
      ),
    ).toBe(false)
    expect(
      isRecorderAuthRequestMessage(
        requestEvent({ data: { source: RECORDER_EXTENSION_MESSAGE_SOURCE, type: "OTHER" } }),
      ),
    ).toBe(false)
  })
})
