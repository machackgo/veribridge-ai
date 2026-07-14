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
  initializeWebsiteProofRecorder,
  openWebsiteProofTarget,
  startWebsiteProofRecording,
} from "@/lib/api"
import {
  RECORDER_INIT_ACK,
  RECORDER_INIT_REQUEST,
  RECORDER_START_ACK,
  RECORDER_START_REQUEST,
  RECORDER_TARGET_OPEN_REQUEST,
  RECORDER_TARGET_READY,
  WEBSITE_PROOF_RECORDER_BUILD_VERSION,
  WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
  type WebsiteProofRecorderConfig,
} from "../../../../packages/shared/websiteProofRecorderContract"

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
  vi.restoreAllMocks()
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

describe("initializeWebsiteProofRecorder", () => {
  const recorderInput = {
    config_revision: 1,
    session_id: "session-new-wikitok",
    owner_user_id: "user-1",
    project_id: "project-1",
    website_url: "https://wikitok.io/",
    repository_url: "https://github.com/IsaacGemal/wikitok",
    claimed_skills: ["React", " TypeScript "],
    proof_objective: "Demonstrate five articles and change language",
    created_at: "2026-07-14T05:04:43Z",
  }

  it("waits for the exact versioned ACK and keeps secrets out of URLs", async () => {
    getSession.mockResolvedValue({
      data: { session: { access_token: "recorder-token", user: { id: "user-1" }, expires_at: 1_900_000_000 } },
    })
    const postMessage = vi.fn((message: { type?: string; payload?: { request_id?: string; config?: Record<string, unknown> } }, _targetOrigin?: string) => {
      if (message.type !== RECORDER_INIT_REQUEST || !message.payload?.request_id) return
      const config = message.payload.config as { session_id: string; config_revision: number; api_base_url: string }
      window.dispatchEvent(new MessageEvent("message", {
        data: {
          source: "veribridge-extension",
          type: RECORDER_INIT_ACK,
          payload: {
            request_id: message.payload.request_id,
            session_id: config.session_id,
            config_revision: config.config_revision,
            api_base_url: config.api_base_url,
            schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
            build_version: WEBSITE_PROOF_RECORDER_BUILD_VERSION,
            extension_id: "extension-id",
            ready: true,
          },
        },
        origin: window.location.origin,
        source: window,
      }))
    })
    vi.spyOn(window, "postMessage").mockImplementation(postMessage as never)

    const result = await initializeWebsiteProofRecorder(recorderInput)

    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.config.api_base_url).toBe("http://localhost:8128")
    expect(result.config.claimed_skills).toEqual(["React", "TypeScript"])
    expect(result.config.website_url).not.toContain("recorder-token")
    expect(result.config.repository_url).not.toContain("recorder-token")
    expect(postMessage.mock.calls[0][1]).toBe(window.location.origin)
  })

  it("fails specifically when authentication is unavailable", async () => {
    getSession.mockResolvedValue(sessionOf(null))
    const postMessage = vi.fn()
    vi.spyOn(window, "postMessage").mockImplementation(postMessage as never)

    const result = await initializeWebsiteProofRecorder(recorderInput)

    expect(result).toMatchObject({ ok: false, error_code: "authentication_unavailable" })
    expect(postMessage).not.toHaveBeenCalled()
  })

  it("retries a sleeping worker and succeeds on the second delivery", async () => {
    vi.useFakeTimers()
    getSession.mockResolvedValue({
      data: { session: { access_token: "recorder-token", user: { id: "user-1" }, expires_at: 1_900_000_000 } },
    })
    let initDeliveries = 0
    vi.spyOn(window, "postMessage").mockImplementation(((message: {
      type?: string
      payload?: { request_id?: string; config?: Record<string, unknown> }
    }) => {
      if (message.type !== RECORDER_INIT_REQUEST || !message.payload?.request_id) return
      initDeliveries += 1
      if (initDeliveries !== 2) return
      const cfg = message.payload.config as { session_id: string; config_revision: number; api_base_url: string }
      window.dispatchEvent(new MessageEvent("message", {
        data: { source: "veribridge-extension", type: RECORDER_INIT_ACK, payload: {
          request_id: message.payload.request_id,
          session_id: cfg.session_id,
          config_revision: cfg.config_revision,
          api_base_url: cfg.api_base_url,
          schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
          build_version: WEBSITE_PROOF_RECORDER_BUILD_VERSION,
          extension_id: "extension-id",
          ready: true,
        } },
        origin: window.location.origin,
        source: window,
      }))
    }) as never)

    const pending = initializeWebsiteProofRecorder(recorderInput)
    await vi.advanceTimersByTimeAsync(300)
    const result = await pending

    expect(result.ok).toBe(true)
    expect(initDeliveries).toBe(2)
  })

  it("returns extension_not_detected when no extension message arrives", async () => {
    vi.useFakeTimers()
    getSession.mockResolvedValue({
      data: { session: { access_token: "recorder-token", user: { id: "user-1" }, expires_at: 1_900_000_000 } },
    })
    vi.spyOn(window, "postMessage").mockImplementation(() => undefined)

    const pending = initializeWebsiteProofRecorder(recorderInput)
    await vi.advanceTimersByTimeAsync(7_100)

    await expect(pending).resolves.toMatchObject({ ok: false, error_code: "extension_not_detected" })
  })

  it("identifies a legacy extension build distinctly", async () => {
    vi.useFakeTimers()
    getSession.mockResolvedValue({
      data: { session: { access_token: "recorder-token", user: { id: "user-1" }, expires_at: 1_900_000_000 } },
    })
    vi.spyOn(window, "postMessage").mockImplementation(((message: { type?: string }) => {
      if (message.type !== "VERIBRIDGE_SET_RECORDER_AUTH") return
      window.dispatchEvent(new MessageEvent("message", {
        data: { source: "veribridge-extension", type: "VERIBRIDGE_RECORDER_AUTH_APPLIED", payload: {} },
        origin: window.location.origin,
        source: window,
      }))
    }) as never)

    const pending = initializeWebsiteProofRecorder(recorderInput)
    await vi.advanceTimersByTimeAsync(2_100)

    await expect(pending).resolves.toMatchObject({ ok: false, error_code: "extension_version_incompatible" })
  })

  it("rejects an ACK from the wrong session", async () => {
    getSession.mockResolvedValue({
      data: { session: { access_token: "recorder-token", user: { id: "user-1" }, expires_at: 1_900_000_000 } },
    })
    vi.spyOn(window, "postMessage").mockImplementation(((message: {
      type?: string
      payload?: { request_id?: string; config?: Record<string, unknown> }
    }) => {
      if (message.type !== RECORDER_INIT_REQUEST || !message.payload?.request_id) return
      const cfg = message.payload.config as { config_revision: number; api_base_url: string }
      window.dispatchEvent(new MessageEvent("message", {
        data: { source: "veribridge-extension", type: RECORDER_INIT_ACK, payload: {
          request_id: message.payload.request_id,
          session_id: "session-historical",
          config_revision: cfg.config_revision,
          api_base_url: cfg.api_base_url,
          schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
          build_version: WEBSITE_PROOF_RECORDER_BUILD_VERSION,
          extension_id: "extension-id",
          ready: true,
        } },
        origin: window.location.origin,
        source: window,
      }))
    }) as never)

    await expect(initializeWebsiteProofRecorder(recorderInput)).resolves
      .toMatchObject({ ok: false, error_code: "session_mismatch" })
  })
})

describe("target and recording acknowledgements", () => {
  const config: WebsiteProofRecorderConfig = {
    schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    config_revision: 4,
    session_id: "session-new-wikitok",
    owner_user_id: "user-1",
    api_base_url: "http://localhost:8128",
    auth: { mechanism: "bearer", access_token: "private-token", expires_at: null },
    project_id: "project-1",
    website_url: "https://wikitok.io/",
    repository_url: "https://github.com/IsaacGemal/wikitok",
    claimed_skills: ["React", "TypeScript"],
    proof_objective: "Demonstrate the WikiTok feed and language workflow",
    created_at: "2026-07-14T05:04:43.000Z",
    expires_at: null,
  }

  it("waits for exact target readiness with API base and skills preserved", async () => {
    vi.spyOn(window, "postMessage").mockImplementation(((message: {
      type?: string
      payload?: { request_id?: string }
    }) => {
      if (message.type !== RECORDER_TARGET_OPEN_REQUEST || !message.payload?.request_id) return
      window.dispatchEvent(new MessageEvent("message", {
        data: { source: "veribridge-extension", type: RECORDER_TARGET_READY, payload: {
          request_id: message.payload.request_id,
          session_id: config.session_id,
          config_revision: config.config_revision,
          api_base_url: config.api_base_url,
          claimed_skills: config.claimed_skills,
          target_tab_id: 42,
          target_url: "https://wikitok.io/",
          ready: true,
        } },
        origin: window.location.origin,
        source: window,
      }))
    }) as never)

    await expect(openWebsiteProofTarget(config)).resolves.toMatchObject({
      session_id: config.session_id,
      config_revision: config.config_revision,
      api_base_url: "http://localhost:8128",
      claimed_skills: ["React", "TypeScript"],
      ready: true,
    })
  })

  it("rejects target readiness from another origin", async () => {
    vi.spyOn(window, "postMessage").mockImplementation(((message: {
      type?: string
      payload?: { request_id?: string }
    }) => {
      if (message.type !== RECORDER_TARGET_OPEN_REQUEST || !message.payload?.request_id) return
      window.dispatchEvent(new MessageEvent("message", {
        data: { source: "veribridge-extension", type: RECORDER_TARGET_READY, payload: {
          request_id: message.payload.request_id,
          session_id: config.session_id,
          config_revision: config.config_revision,
          api_base_url: config.api_base_url,
          claimed_skills: config.claimed_skills,
          target_tab_id: 9,
          target_url: "https://example.com/",
          ready: true,
        } },
        origin: window.location.origin,
        source: window,
      }))
    }) as never)

    await expect(openWebsiteProofTarget(config)).resolves
      .toMatchObject({ ok: false, error_code: "target_url_mismatch" })
  })

  it("requires an exact recording-start ACK", async () => {
    vi.spyOn(window, "postMessage").mockImplementation(((message: {
      type?: string
      payload?: { request_id?: string }
    }) => {
      if (message.type !== RECORDER_START_REQUEST || !message.payload?.request_id) return
      window.dispatchEvent(new MessageEvent("message", {
        data: { source: "veribridge-extension", type: RECORDER_START_ACK, payload: {
          request_id: message.payload.request_id,
          session_id: config.session_id,
          config_revision: config.config_revision,
          started_at: "2026-07-14T12:00:00Z",
          idempotent: false,
          ready: true,
        } },
        origin: window.location.origin,
        source: window,
      }))
    }) as never)

    await expect(startWebsiteProofRecording(config)).resolves.toMatchObject({
      session_id: config.session_id,
      config_revision: config.config_revision,
      ready: true,
    })
  })
})
