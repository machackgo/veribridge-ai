/**
 * Recorder auth — PRODUCTION BUNDLE regression guard.
 *
 * The recorder auth lifecycle unit tests exercise the TypeScript SOURCE
 * (recorderAuth.ts). They passed on every prior fix attempt — yet the live
 * browser kept returning the backend's no-token 401
 * ("Authentication required. Provide a Bearer token.").
 *
 * Root cause was NOT in the source: a pre-handoff build of the extension (from
 * a different git worktree) was the one actually loaded in Chrome. That older
 * bundle attached auth with an UNCONDITIONAL guard:
 *
 *     if (state.authToken) headers["Authorization"] = `Bearer ${state.authToken}`
 *
 * i.e. it still POSTed even with an empty token — just WITHOUT the header — so
 * the backend saw no credentials and 401'd. The current source fails closed
 * (returns null headers → the caller skips the request entirely), but a green
 * SOURCE test cannot detect that the wrong BUNDLE is deployed.
 *
 * This test therefore asserts against the built `dist/*.js` that Chrome loads:
 *   1. the fail-closed guard is compiled in (no anonymous `Bearer ` is
 *      constructible);
 *   2. the app→content→background token handoff + token-free ACK are present;
 *   3. a unique build fingerprint is embedded (so "is Chrome running the code I
 *      just built?" is answerable from the ACK / debug state);
 *   4. the OLD vulnerable unconditional-header pattern is absent.
 *
 * If the dist is missing, the test fails LOUDLY telling you to run the build —
 * a stale/absent bundle is precisely the failure mode this guards against.
 */

import { existsSync, readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

import { describe, expect, it } from "vitest"

const here = dirname(fileURLToPath(import.meta.url))
const distDir = resolve(here, "../../../extension/dist")
const buildFingerprint = "recorder-auth-5.6-debug-28284748"

function readDist(name: string): string {
  const path = resolve(distDir, name)
  if (!existsSync(path)) {
    throw new Error(
      `Extension bundle ${name} is missing at ${path}. ` +
        `Run \`npm run build\` in apps/extension before this test — a stale or ` +
        `absent dist is the exact "wrong bundle loaded in Chrome" bug this guards.`,
    )
  }
  return readFileSync(path, "utf8")
}

describe("extension production bundle — fail-closed auth", () => {
  it("background.js compiles the fail-closed header guard (no anonymous Bearer)", () => {
    const background = readDist("background.js")
    // The compiled helper must return null when the token is empty.
    expect(background).toContain("if (!authToken)")
    expect(background).toContain("return null")
    expect(background).toContain("`Bearer ${authToken}`")
  })

  it("recorder.js (video upload) compiles the same fail-closed guard", () => {
    const recorder = readDist("recorder.js")
    expect(recorder).toContain("if (!authToken)")
    expect(recorder).toContain("return null")
    expect(recorder).toContain("`Bearer ${authToken}`")
  })

  it("bundles must NOT contain the old unconditional-header pattern", () => {
    // The pre-handoff worktree attached the header only when a token existed but
    // POSTed regardless, producing the exact `Provide a Bearer token` 401.
    for (const name of ["background.js", "recorder.js"]) {
      const src = readDist(name)
      expect(
        /if\s*\(\s*(state\.)?authToken\s*\)\s*headers\[\s*["']Authorization["']\s*\]/.test(src),
        `${name} still contains the vulnerable unconditional Authorization pattern`,
      ).toBe(false)
    }
  })
})

describe("extension production bundle — token handoff", () => {
  it("content.js relays the app token and posts a token-free ACK", () => {
    const content = readDist("content.js")
    expect(content).toContain("VERIBRIDGE_SET_RECORDER_AUTH")
    expect(content).toContain("SET_RECORDER_AUTH")
    expect(content).toContain("VERIBRIDGE_RECORDER_AUTH_ACK")
    // The ACK relayed to the page must never carry the token value.
    expect(content).not.toContain("payload.authToken}")
  })

  it("background.js handles SET_RECORDER_AUTH and gates START_RECORDING on a token", () => {
    const background = readDist("background.js")
    expect(background).toContain("SET_RECORDER_AUTH")
    expect(background).toContain("START_RECORDING")
    // ensureUploadAuth restores the token across MV3 service-worker restarts.
    expect(background).toContain("ensureUploadAuth")
    expect(background).toContain("persistRecorderAuthAndVerify")
    expect(background).toContain("storage_readback_mismatch")
    expect(background).toContain("readBackSucceeded")
    expect(background).toContain("storedSessionMatches")
  })
})

describe("extension production bundle — build fingerprint", () => {
  it("content/background/recorder bundles embed the same contract fingerprint", () => {
    for (const name of ["background.js", "content.js", "recorder.js"]) {
      expect(readDist(name), `${name} is stale`).toContain(buildFingerprint)
    }
  })

  it("all runtime components expose the safe debug hook", () => {
    for (const name of ["background.js", "content.js", "recorder.js"]) {
      expect(readDist(name)).toContain("__VB_RECORDER_AUTH_DEBUG__")
    }
  })
})
