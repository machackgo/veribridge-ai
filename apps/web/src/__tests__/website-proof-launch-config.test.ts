import { describe, expect, it } from "vitest"

import {
  WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
  normalizeWebsiteProofApiBase,
  normalizeWebsiteProofRecorderConfig,
  refreshWebsiteProofRecorderAuth,
  selectWebsiteProofRecorderConfig,
  type WebsiteProofRecorderConfig,
} from "../../../../packages/shared/websiteProofRecorderContract"
import { recorderApiUrlForSession } from "../../../extension/src/recorderSessionConfig"

function config(
  overrides: Partial<WebsiteProofRecorderConfig> = {},
): WebsiteProofRecorderConfig {
  return {
    schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    config_revision: 1,
    session_id: "session-fresh-wikitok",
    owner_user_id: "user-1",
    api_base_url: "http://localhost:8128",
    auth: { mechanism: "bearer", access_token: "private-token", expires_at: null },
    project_id: "project-wikitok",
    website_url: "https://wikitok.io/",
    repository_url: "https://github.com/IsaacGemal/wikitok",
    claimed_skills: ["React", "TypeScript"],
    proof_objective: "Demonstrate the WikiTok article feed and language workflow",
    created_at: "2026-07-14T05:04:43.000Z",
    expires_at: null,
    ...overrides,
  }
}

describe("authoritative Website Proof recorder config", () => {
  it("normalizes the explicit localhost:8128 API base", () => {
    expect(normalizeWebsiteProofApiBase("http://localhost:8128/")).toBe("http://localhost:8128")
    expect(normalizeWebsiteProofRecorderConfig(config())?.api_base_url).toBe("http://localhost:8128")
  })

  it("accepts 127.0.0.1 loopback but rejects paths and non-loopback HTTP", () => {
    expect(normalizeWebsiteProofApiBase("http://127.0.0.1:8128/")).toBe("http://127.0.0.1:8128")
    expect(normalizeWebsiteProofApiBase("http://localhost:8128/api")).toBeNull()
    expect(normalizeWebsiteProofApiBase("http://api.veribridgeai.com")).toBeNull()
    expect(normalizeWebsiteProofApiBase("https://api.veribridgeai.com/")).toBe("https://api.veribridgeai.com")
  })

  it("keeps the API base bound to the matching session only", () => {
    const current = config()
    expect(recorderApiUrlForSession(current, current.session_id)).toBe("http://localhost:8128")
    expect(recorderApiUrlForSession(current, "session-historical")).toBeNull()
  })

  it("refreshes auth without changing any non-auth config field", () => {
    const current = config()
    const refreshed = refreshWebsiteProofRecorderAuth(current, {
      session_id: current.session_id,
      config_revision: current.config_revision,
      access_token: "refreshed-token",
      expires_at: "2026-07-14T06:00:00Z",
    })
    expect(refreshed).toEqual({
      ...current,
      auth: {
        mechanism: "bearer",
        access_token: "refreshed-token",
        expires_at: "2026-07-14T06:00:00.000Z",
      },
    })
  })

  it("rejects auth refresh from a historical session or revision", () => {
    const current = config()
    expect(refreshWebsiteProofRecorderAuth(current, {
      session_id: "session-historical",
      config_revision: 1,
      access_token: "token",
    })).toBeNull()
    expect(refreshWebsiteProofRecorderAuth(current, {
      session_id: current.session_id,
      config_revision: 2,
      access_token: "token",
    })).toBeNull()
  })

  it("accepts exact duplicate delivery idempotently", () => {
    const current = config()
    expect(selectWebsiteProofRecorderConfig(current, current, false)).toEqual({
      accepted: true,
      config: current,
      idempotent: true,
    })
  })

  it("rejects a stale revision", () => {
    const current = config({ config_revision: 3 })
    expect(selectWebsiteProofRecorderConfig(current, config({ config_revision: 2 }), false))
      .toMatchObject({ accepted: false, config: current, error_code: "stale_config" })
  })

  it("rejects a same-revision payload mutation", () => {
    const current = config()
    expect(selectWebsiteProofRecorderConfig(current, config({ website_url: "https://example.com/" }), false))
      .toMatchObject({ accepted: false, config: current, error_code: "revision_mismatch" })
  })

  it("allows a higher revision for the same session", () => {
    const current = config()
    const newer = config({ config_revision: 2 })
    expect(selectWebsiteProofRecorderConfig(current, newer, false))
      .toEqual({ accepted: true, config: newer, idempotent: false })
  })

  it("protects another actively recording session", () => {
    const active = config({ session_id: "session-active" })
    expect(selectWebsiteProofRecorderConfig(active, config(), true))
      .toMatchObject({ accepted: false, config: active, error_code: "different_session_active" })
  })

  it("allows a fresh session to replace an idle historical config", () => {
    const historical = config({ session_id: "session-historical" })
    const fresh = config()
    expect(selectWebsiteProofRecorderConfig(historical, fresh, false))
      .toEqual({ accepted: true, config: fresh, idempotent: false })
  })

  it("never puts bearer auth into the target or repository URL", () => {
    const normalized = normalizeWebsiteProofRecorderConfig(config())
    expect(normalized).not.toBeNull()
    expect(normalized?.website_url).not.toContain("private-token")
    expect(normalized?.repository_url).not.toContain("private-token")
    expect(normalized?.auth.access_token).toBe("private-token")
  })

  it("rejects incomplete config and credentials embedded in URLs", () => {
    expect(normalizeWebsiteProofRecorderConfig({ ...config(), proof_objective: "" })).toBeNull()
    expect(normalizeWebsiteProofRecorderConfig({
      ...config(),
      website_url: "https://user:secret@wikitok.io/",
    })).toBeNull()
  })
})
