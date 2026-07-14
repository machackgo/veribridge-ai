import assert from "node:assert/strict"
import test from "node:test"

import {
  WEBSITE_PROOF_RECORDER_BUILD_VERSION,
  WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
  normalizeWebsiteProofApiBase,
  normalizeWebsiteProofRecorderConfig,
  refreshWebsiteProofRecorderAuth,
  selectWebsiteProofRecorderConfig,
  type WebsiteProofRecorderConfig,
} from "../../../packages/shared/websiteProofRecorderContract.ts"

function config(overrides: Partial<WebsiteProofRecorderConfig> = {}): WebsiteProofRecorderConfig {
  return {
    schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    config_revision: 1,
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
    ...overrides,
  }
}

test("schema and extension build versions are explicit", () => {
  assert.equal(WEBSITE_PROOF_RECORDER_SCHEMA_VERSION, 1)
  assert.equal(WEBSITE_PROOF_RECORDER_BUILD_VERSION, "0.2.0")
})

test("normalizes the required localhost:8128 API origin", () => {
  assert.equal(normalizeWebsiteProofApiBase("http://localhost:8128/"), "http://localhost:8128")
})

test("normalizes the 127.0.0.1 loopback form", () => {
  assert.equal(normalizeWebsiteProofApiBase("http://127.0.0.1:8128"), "http://127.0.0.1:8128")
})

test("rejects API path, credentials, query, and public HTTP", () => {
  assert.equal(normalizeWebsiteProofApiBase("http://localhost:8128/api"), null)
  assert.equal(normalizeWebsiteProofApiBase("https://user:pass@api.example.com"), null)
  assert.equal(normalizeWebsiteProofApiBase("https://api.example.com?token=x"), null)
  assert.equal(normalizeWebsiteProofApiBase("http://api.example.com"), null)
})

test("normalizes one complete atomic config", () => {
  const normalized = normalizeWebsiteProofRecorderConfig(config({ claimed_skills: ["React", " React ", "TypeScript"] }))
  assert.ok(normalized)
  assert.deepEqual(normalized.claimed_skills, ["React", "TypeScript"])
  assert.equal(normalized.api_base_url, "http://localhost:8128")
})

test("rejects incomplete auth and objective fields", () => {
  assert.equal(normalizeWebsiteProofRecorderConfig({ ...config(), proof_objective: "" }), null)
  assert.equal(normalizeWebsiteProofRecorderConfig({ ...config(), auth: { mechanism: "bearer", access_token: "", expires_at: null } }), null)
})

test("rejects credentials and sensitive query parameters in target URLs", () => {
  assert.equal(normalizeWebsiteProofRecorderConfig(config({ website_url: "https://user:secret@wikitok.io/" })), null)
  assert.equal(normalizeWebsiteProofRecorderConfig(config({ website_url: "https://wikitok.io/?access_token=secret" })), null)
})

test("keeps the bearer credential outside target and repository URLs", () => {
  const normalized = normalizeWebsiteProofRecorderConfig(config())
  assert.ok(normalized)
  assert.equal(normalized.website_url.includes("private-token"), false)
  assert.equal(normalized.repository_url?.includes("private-token"), false)
})

test("accepts an exact duplicate initialization idempotently", () => {
  const current = config()
  assert.deepEqual(selectWebsiteProofRecorderConfig(current, current, false), {
    accepted: true, config: current, idempotent: true,
  })
})

test("rejects a stale revision", () => {
  const current = config({ config_revision: 3 })
  assert.equal(selectWebsiteProofRecorderConfig(current, config({ config_revision: 2 }), false).error_code, "stale_config")
})

test("rejects a same-revision mutation", () => {
  const current = config()
  assert.equal(selectWebsiteProofRecorderConfig(current, config({ website_url: "https://example.com/" }), false).error_code, "revision_mismatch")
})

test("accepts a higher revision for the same session", () => {
  const next = config({ config_revision: 2 })
  assert.deepEqual(selectWebsiteProofRecorderConfig(config(), next, false), {
    accepted: true, config: next, idempotent: false,
  })
})

test("prevents another session from replacing an active recording", () => {
  const current = config({ session_id: "session-active" })
  assert.equal(selectWebsiteProofRecorderConfig(current, config(), true).error_code, "different_session_active")
})

test("allows a fresh session to replace an idle historical config", () => {
  const next = config()
  assert.deepEqual(selectWebsiteProofRecorderConfig(config({ session_id: "session-old" }), next, false), {
    accepted: true, config: next, idempotent: false,
  })
})

test("bound auth refresh preserves every non-auth field", () => {
  const current = config()
  const refreshed = refreshWebsiteProofRecorderAuth(current, {
    session_id: current.session_id,
    config_revision: current.config_revision,
    access_token: "fresh-token",
    expires_at: "2026-07-14T06:00:00Z",
  })
  assert.ok(refreshed)
  assert.deepEqual({ ...refreshed, auth: current.auth }, current)
  assert.equal(refreshed.auth.access_token, "fresh-token")
})

test("foreign-session and stale-revision auth refreshes fail closed", () => {
  const current = config()
  assert.equal(refreshWebsiteProofRecorderAuth(current, {
    session_id: "session-old", config_revision: 1, access_token: "fresh",
  }), null)
  assert.equal(refreshWebsiteProofRecorderAuth(current, {
    session_id: current.session_id, config_revision: 2, access_token: "fresh",
  }), null)
})
