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
  fetchAPI,
  publishRecorderAuthToExtension,
  RECORDER_AUTH_MESSAGE_SOURCE,
  RECORDER_AUTH_MESSAGE_TYPE,
} from "@/lib/api"

const fetchMock = vi.fn()

function sessionOf(token: string | null) {
  return { data: { session: token ? { access_token: token } : null } }
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
    getSession.mockResolvedValue(sessionOf("recorder-token"))
    const postMessage = vi.fn()
    vi.spyOn(window, "postMessage").mockImplementation(postMessage as never)

    const published = await publishRecorderAuthToExtension()
    await vi.runAllTimersAsync()

    expect(published).toBe(true)
    expect(postMessage).toHaveBeenCalledTimes(4)
    for (const [message, targetOrigin] of postMessage.mock.calls) {
      expect(message.source).toBe(RECORDER_AUTH_MESSAGE_SOURCE)
      expect(message.type).toBe(RECORDER_AUTH_MESSAGE_TYPE)
      expect(message.payload.authToken).toBe("recorder-token")
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
})
