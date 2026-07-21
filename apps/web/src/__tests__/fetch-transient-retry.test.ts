/**
 * Regression: a dropped connection must not become a dead-end error.
 *
 * Production audit 2026-07-21: GET /student/vbr/passport (~80 KB, ~2.4 s)
 * intermittently rejected with `TypeError: Failed to fetch` — the transport
 * dying after the 200 headers but before the body finished streaming — and the
 * Work Passport rendered "Something went wrong / Failed to fetch" until the
 * user pressed "Try again", which always worked.
 *
 * The retry must stay narrow: never retry a request that could duplicate a
 * side effect, and never swallow or re-send on an actual HTTP response.
 */
import { describe, expect, it, vi } from "vitest"

import { fetchWithTransientRetry, isReplayableRequest } from "../lib/api"

const ok = (body = "{}") => new Response(body, { status: 200 })

describe("isReplayableRequest", () => {
  it("treats bodyless GET/HEAD as replayable", () => {
    expect(isReplayableRequest({})).toBe(true)
    expect(isReplayableRequest({ method: "GET" })).toBe(true)
    expect(isReplayableRequest({ method: "head" })).toBe(true)
  })

  it("refuses anything that could duplicate a side effect", () => {
    expect(isReplayableRequest({ method: "POST" })).toBe(false)
    expect(isReplayableRequest({ method: "PATCH" })).toBe(false)
    expect(isReplayableRequest({ method: "DELETE" })).toBe(false)
    expect(isReplayableRequest({ body: "{}" })).toBe(false)
    // A body makes it non-replayable even with a nominally safe method.
    expect(isReplayableRequest({ method: "GET", body: "{}" })).toBe(false)
  })
})

describe("fetchWithTransientRetry", () => {
  it("recovers a dropped connection on a replayable request", async () => {
    const send = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(ok('{"passport":true}'))

    const res = await fetchWithTransientRetry(send, true)

    expect(res.status).toBe(200)
    expect(await res.text()).toBe('{"passport":true}')
    expect(send).toHaveBeenCalledTimes(2)
  })

  it("never retries a non-replayable request", async () => {
    const send = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"))

    await expect(fetchWithTransientRetry(send, false)).rejects.toThrow("Failed to fetch")
    expect(send).toHaveBeenCalledTimes(1)
  })

  it("surfaces the error when every attempt fails", async () => {
    const send = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"))

    await expect(fetchWithTransientRetry(send, true)).rejects.toThrow("Failed to fetch")
    expect(send).toHaveBeenCalledTimes(2)
  })

  it("returns server errors untouched — a 500 is an answer, not a transport failure", async () => {
    const send = vi.fn().mockResolvedValue(new Response("boom", { status: 500 }))

    const res = await fetchWithTransientRetry(send, true)

    expect(res.status).toBe(500)
    expect(send).toHaveBeenCalledTimes(1)
  })

  it("does not retry a 401/404 either", async () => {
    for (const status of [401, 404]) {
      const send = vi.fn().mockResolvedValue(new Response("", { status }))
      const res = await fetchWithTransientRetry(send, true)
      expect(res.status).toBe(status)
      expect(send).toHaveBeenCalledTimes(1)
    }
  })

  it("makes exactly one call when the first attempt succeeds", async () => {
    const send = vi.fn().mockResolvedValue(ok())
    await fetchWithTransientRetry(send, true)
    expect(send).toHaveBeenCalledTimes(1)
  })
})
