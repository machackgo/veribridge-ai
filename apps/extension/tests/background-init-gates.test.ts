// Store-rollout compatibility + API-pinning gates on RECORDER_INIT_REQUEST.
//
// Chrome Web Store updates roll out on Chrome's schedule, so the page sends a
// MINIMUM build version: a newer installed extension must keep working against
// an older page, while an older extension must be routed to the update screen.
// The API base gate ensures evidence can only ever be uploaded to an approved
// VeriBridge origin regardless of what a page hands the extension.

import assert from "node:assert/strict"
import test from "node:test"

import {
  RECORDER_INIT_REQUEST,
  WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
  type WebsiteProofRecorderConfig,
} from "../../../packages/shared/websiteProofRecorderContract.ts"

const INSTALLED_VERSION = "1.2.3"

function chromeMock() {
  let messageListener:
    | ((
        message: { type: string; payload?: unknown },
        sender: Record<string, unknown>,
        respond: (value: unknown) => void,
      ) => unknown)
    | undefined
  const stored: Record<string, unknown> = {}
  const noopListener = { addListener: () => undefined }
  const mock = {
    runtime: {
      id: "gate-test-extension",
      lastError: undefined,
      getManifest: () => ({ version: INSTALLED_VERSION }),
      getURL: (path: string) => `chrome-extension://gate-test-extension/${path}`,
      onMessage: {
        addListener: (listener: NonNullable<typeof messageListener>) => {
          messageListener = listener
        },
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
        get: async () => ({}),
        set: async () => undefined,
        remove: async () => undefined,
      },
    },
    tabs: {
      query: async () => [],
      sendMessage: async () => undefined,
      create: (_options: Record<string, unknown>, callback: (tab: Record<string, unknown>) => void) =>
        callback({ id: 99, windowId: 1 }),
      get: (_tabId: number, callback?: (tab: undefined) => void) => {
        if (callback) callback(undefined)
        return Promise.resolve(undefined)
      },
      update: async () => undefined,
      reload: (_tabId: number, _options: Record<string, unknown>, callback?: () => void) => callback?.(),
      captureVisibleTab: async () => "data:image/jpeg;base64," + "a".repeat(1600),
      onCreated: noopListener,
      onUpdated: noopListener,
      onActivated: noopListener,
    },
    windows: { update: async () => undefined },
  }
  return {
    mock,
    send: async (type: string, payload: unknown): Promise<Record<string, unknown>> =>
      await new Promise((resolve, reject) => {
        if (!messageListener) { reject(new Error("no listener")); return }
        let responded = false
        const timeout = setTimeout(() => reject(new Error(`No response for ${type}`)), 1000)
        const keepAlive = messageListener({ type, payload }, {}, (response) => {
          responded = true
          clearTimeout(timeout)
          resolve((response ?? {}) as Record<string, unknown>)
        })
        if (keepAlive !== true && !responded) {
          clearTimeout(timeout)
          resolve({})
        }
      }),
  }
}

function config(overrides: Partial<WebsiteProofRecorderConfig> = {}): WebsiteProofRecorderConfig {
  return {
    schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    config_revision: 1,
    session_id: "session-gates",
    owner_user_id: "user-1",
    api_base_url: "http://localhost:8128",
    auth: { mechanism: "bearer", access_token: "private-token", expires_at: null },
    project_id: null,
    website_url: "https://demo.example.com/",
    repository_url: null,
    claimed_skills: ["React"],
    proof_objective: "Demonstrate the demo app",
    created_at: "2026-08-01T00:00:00.000Z",
    expires_at: null,
    ...overrides,
  }
}

test("init gates: minimum-version semantics and API pinning", async (t) => {
  const { mock, send } = chromeMock()
  Object.assign(globalThis, { chrome: mock })
  await import("../src/background.ts?init-gates")
  await Promise.resolve()

  await t.test("a newer installed build accepts an older page minimum", async () => {
    const resp = await send(RECORDER_INIT_REQUEST, {
      request_id: "older-min",
      expected_schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
      expected_build_version: "1.0.0",
      config: config(),
    })
    assert.equal(resp.ok, true)
    assert.equal(resp.build_version, INSTALLED_VERSION)
  })

  await t.test("an installed build older than the page minimum is rejected", async () => {
    const resp = await send(RECORDER_INIT_REQUEST, {
      request_id: "newer-min",
      expected_schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
      expected_build_version: "2.0.0",
      config: config({ config_revision: 2 }),
    })
    assert.equal(resp.ok, false)
    assert.equal(resp.error_code, "extension_version_incompatible")
  })

  await t.test("a schema mismatch always fails regardless of build", async () => {
    const resp = await send(RECORDER_INIT_REQUEST, {
      request_id: "schema-mismatch",
      expected_schema_version: 2,
      expected_build_version: "1.0.0",
      config: config({ config_revision: 3 }),
    })
    assert.equal(resp.ok, false)
    assert.equal(resp.error_code, "extension_version_incompatible")
  })

  await t.test("a missing page minimum fails closed", async () => {
    const resp = await send(RECORDER_INIT_REQUEST, {
      request_id: "missing-min",
      expected_schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
      config: config({ config_revision: 4 }),
    })
    assert.equal(resp.ok, false)
    assert.equal(resp.error_code, "extension_version_incompatible")
  })

  await t.test("an arbitrary https API base is rejected even in dev channel", async () => {
    const resp = await send(RECORDER_INIT_REQUEST, {
      request_id: "evil-api",
      expected_schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
      expected_build_version: "1.0.0",
      config: config({ config_revision: 5, api_base_url: "https://exfiltrate.example.com" }),
    })
    assert.equal(resp.ok, false)
    assert.equal(resp.error_code, "invalid_api_base")
  })

  await t.test("the production API base is accepted", async () => {
    const resp = await send(RECORDER_INIT_REQUEST, {
      request_id: "prod-api",
      expected_schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
      expected_build_version: "1.0.0",
      config: config({ config_revision: 6, api_base_url: "https://veribridge-api.onrender.com" }),
    })
    assert.equal(resp.ok, true)
  })
})
