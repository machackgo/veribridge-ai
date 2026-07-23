/**
 * Regression: the browser's raw `TypeError: Failed to fetch` must never
 * surface in the UI (production incident 2026-07-23 — passport publish).
 * A transport-level failure (connection drop / CORS block / DNS) in
 * `fetchAPI` is rethrown as a stable, friendly, retryable message.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const getSession = vi.fn()
const refreshSession = vi.fn()

vi.mock("@/lib/supabase/client", () => ({
  createSupabaseBrowserClient: () => ({
    auth: { getSession, refreshSession },
  }),
}))

import { NETWORK_UNREACHABLE_MESSAGE, fetchAPI } from "@/lib/api"

const fetchMock = vi.fn()

beforeEach(() => {
  getSession.mockReset()
  refreshSession.mockReset()
  fetchMock.mockReset()
  vi.stubGlobal("fetch", fetchMock)
  getSession.mockResolvedValue({ data: { session: { access_token: "tok" } } })
  vi.spyOn(console, "error").mockImplementation(() => {})
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("fetchAPI transport failures", () => {
  it("maps a rejected POST (non-replayable) to the friendly network message", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"))

    await expect(
      fetchAPI("/api/v1/student/vbr/passport/publish", {
        method: "POST",
        body: JSON.stringify({}),
      })
    ).rejects.toThrow(NETWORK_UNREACHABLE_MESSAGE)
    expect(fetchMock).toHaveBeenCalledTimes(1) // body → never auto-retried
  })

  it("maps a GET that fails on every retry to the friendly network message", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"))

    await expect(fetchAPI("/api/v1/student/vbr/passport")).rejects.toThrow(
      NETWORK_UNREACHABLE_MESSAGE
    )
    expect(fetchMock).toHaveBeenCalledTimes(2) // replayable → one transient retry
  })

  it("never masks a real HTTP error response as a network failure", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: { code: "internal_error" } }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      })
    )

    const res = await fetchAPI("/api/v1/student/vbr/passport/publish", {
      method: "POST",
      body: JSON.stringify({}),
    })
    expect(res.status).toBe(500) // callers parse the JSON detail themselves
  })
})
