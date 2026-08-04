// Real-Chromium QA of the RELEASE-channel extension build.
//
// Loads the unpacked release build (the exact file set that ships in the
// store ZIP) into a real Chromium via Playwright and verifies the
// security-critical protocol gates from a page's point of view:
//
//   1. Detection PONG on the production app origin (veribridgeai.com is
//      served via route interception — no real deploy involved).
//   2. Channel gate: a localhost app page gets NO bridge in release builds.
//   3. Foreign-origin pages get NO bridge (spoofed-origin isolation).
//   4. INIT with an arbitrary https API base → invalid_api_base NACK.
//   5. INIT with the production API base → ACK (min-version semantics).
//   6. INIT from an older page minimum ("0.9.0") → still ACKed by a newer
//      build; page minimum above the build → version_incompatible NACK.
//
// Usage: node scripts/qa-release-browser.mjs <path-to-playwright-parent>
//   (defaults to ../web/node_modules)
//
// Writes evidence (JSON + screenshots) into the directory given by
// QA_EVIDENCE_DIR (default: ./release/browser-qa).

import { execFileSync } from "node:child_process"
import fs from "node:fs"
import path from "node:path"
import { createRequire } from "node:module"
import { fileURLToPath } from "node:url"

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
process.chdir(root)

const requireFrom = createRequire(path.resolve(root, "../web/package.json"))
const { chromium } = requireFrom("playwright")

const evidenceDir = process.env.QA_EVIDENCE_DIR ?? path.join(root, "release", "browser-qa")
fs.mkdirSync(evidenceDir, { recursive: true })

// ── Stage the unpacked release build (same file set as the store ZIP) ───────
execFileSync("npm", ["run", "build:release"], { stdio: "inherit" })
const stage = path.join(evidenceDir, "ext-release-unpacked")
fs.rmSync(stage, { recursive: true, force: true })
for (const f of [
  "manifest.json", "popup.html", "recorder.html",
  "dist/background.js", "dist/content.js", "dist/popup.js", "dist/recorder.js",
  "icons/icon16.png", "icons/icon32.png", "icons/icon48.png", "icons/icon128.png",
]) {
  const dest = path.join(stage, f)
  fs.mkdirSync(path.dirname(dest), { recursive: true })
  fs.copyFileSync(f, dest)
}

const SCHEMA = 1

function harnessHtml(title) {
  return `<!doctype html><html><head><title>${title}</title></head><body>
  <h1 style="font-family:sans-serif">${title}</h1>
  <script>
    window.__received = [];
    window.addEventListener("message", (e) => {
      const d = e.data;
      if (d && d.source === "veribridge-extension") window.__received.push(d);
    });
    window.__send = (type, payload) =>
      window.postMessage({ source: "veribridge-app", type, payload }, window.location.origin);
  </script></body></html>`
}

function makeConfig(overrides = {}) {
  return {
    schema_version: SCHEMA,
    config_revision: overrides.config_revision ?? 1,
    session_id: overrides.session_id ?? "qa-session-1",
    owner_user_id: "qa-user-1",
    api_base_url: overrides.api_base_url ?? "https://veribridge-api.onrender.com",
    auth: { mechanism: "bearer", access_token: "qa-token", expires_at: null },
    project_id: null,
    website_url: "https://demo.example.org/",
    repository_url: null,
    claimed_skills: ["React"],
    proof_objective: "QA objective",
    created_at: "2026-08-01T00:00:00.000Z",
    expires_at: null,
  }
}

async function withPage(context, url, fn) {
  const page = await context.newPage()
  try {
    await page.goto(url, { waitUntil: "domcontentloaded" })
    // Give the content script (document_idle) a moment to attach.
    await page.waitForTimeout(700)
    return await fn(page)
  } finally {
    await page.close()
  }
}

async function ping(page, requestId) {
  await page.evaluate((rid) => window.__send("VERIBRIDGE_RECORDER_BRIDGE_PING", { request_id: rid }), requestId)
  await page.waitForTimeout(600)
  return await page.evaluate(() =>
    window.__received.filter((m) => m.type === "VERIBRIDGE_RECORDER_BRIDGE_PONG"))
}

async function init(page, requestId, expectedBuild, config) {
  await page.evaluate(({ rid, min, cfg }) => window.__send("VERIBRIDGE_RECORDER_INIT_REQUEST", {
    request_id: rid,
    expected_schema_version: 1,
    expected_build_version: min,
    config: cfg,
  }), { rid: requestId, min: expectedBuild, cfg: config })
  await page.waitForTimeout(900)
  return await page.evaluate((rid) =>
    window.__received.filter((m) =>
      (m.type === "VERIBRIDGE_RECORDER_INIT_ACK" || m.type === "VERIBRIDGE_RECORDER_INIT_NACK") &&
      m.payload && m.payload.request_id === rid),
    requestId)
}

const results = []
function record(name, pass, detail) {
  results.push({ name, pass, detail })
  console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`)
}

const context = await chromium.launchPersistentContext("", {
  headless: false,
  viewport: { width: 1280, height: 800 },
  args: [
    `--disable-extensions-except=${stage}`,
    `--load-extension=${stage}`,
  ],
})

// Serve fake pages on the production origin + a foreign origin + localhost.
await context.route("https://veribridgeai.com/**", (route) =>
  route.fulfill({ contentType: "text/html", body: harnessHtml("VB app origin harness") }))
await context.route("https://attacker-portal.example/**", (route) =>
  route.fulfill({ contentType: "text/html", body: harnessHtml("Foreign origin harness") }))
await context.route("http://localhost:4599/**", (route) =>
  route.fulfill({ contentType: "text/html", body: harnessHtml("Localhost app harness") }))

try {
  // 1 + 4 + 5 + 6 on the production app origin
  await withPage(context, "https://veribridgeai.com/student/proofs/website", async (page) => {
    const pongs = await ping(page, "qa-ping-1")
    const pong = pongs.find((m) => m.payload?.request_id === "qa-ping-1")
    record(
      "detection PONG on production origin",
      Boolean(pong) &&
        pong.payload.schema_version === SCHEMA &&
        pong.payload.build_version === "1.0.0" &&
        pong.payload.bridge_trusted === true &&
        pong.payload.context_valid === true,
      JSON.stringify(pong?.payload ?? null),
    )
    await page.screenshot({ path: path.join(evidenceDir, "qa-1-detection-prod-origin.png") })

    const evil = await init(page, "qa-init-evil", "1.0.0", makeConfig({ api_base_url: "https://exfiltrate.example.com" }))
    record(
      "INIT with arbitrary https API base is NACKed (invalid_api_base)",
      evil.length > 0 && evil.every((m) => m.type === "VERIBRIDGE_RECORDER_INIT_NACK") &&
        evil[0].payload.error_code === "invalid_api_base",
      JSON.stringify(evil[0]?.payload?.error_code ?? "no-response"),
    )

    const ok = await init(page, "qa-init-ok", "1.0.0", makeConfig({ config_revision: 2 }))
    const ack = ok.find((m) => m.type === "VERIBRIDGE_RECORDER_INIT_ACK")
    record(
      "INIT with production API base is ACKed",
      Boolean(ack) && ack.payload.session_id === "qa-session-1" && ack.payload.ready === true,
      JSON.stringify(ack?.payload?.error_code ?? ack?.payload?.session_id ?? "no-response"),
    )

    const olderMin = await init(page, "qa-init-older-min", "0.9.0", makeConfig({ config_revision: 3 }))
    record(
      "older page minimum (0.9.0) still ACKed by 1.0.0 build",
      olderMin.some((m) => m.type === "VERIBRIDGE_RECORDER_INIT_ACK"),
      olderMin.map((m) => m.type).join(","),
    )

    const newerMin = await init(page, "qa-init-newer-min", "9.9.9", makeConfig({ config_revision: 4 }))
    record(
      "page minimum above installed build → extension_version_incompatible",
      newerMin.length > 0 && newerMin[0].type === "VERIBRIDGE_RECORDER_INIT_NACK" &&
        newerMin[0].payload.error_code === "extension_version_incompatible",
      JSON.stringify(newerMin[0]?.payload?.error_code ?? "no-response"),
    )
  })

  // 2. Channel gate: localhost gets no bridge in the release build.
  await withPage(context, "http://localhost:4599/student/proofs/website", async (page) => {
    const pongs = await ping(page, "qa-ping-localhost")
    record(
      "release build: NO bridge on localhost app route",
      pongs.length === 0,
      `pongs=${pongs.length}`,
    )
    const evil = await init(page, "qa-init-localhost", "1.0.0", makeConfig({ config_revision: 5 }))
    record(
      "release build: INIT ignored on localhost app route",
      evil.length === 0,
      `responses=${evil.length}`,
    )
    await page.screenshot({ path: path.join(evidenceDir, "qa-2-localhost-gated.png") })
  })

  // 3. Foreign https origin gets no bridge at all.
  await withPage(context, "https://attacker-portal.example/student/proofs/website", async (page) => {
    const pongs = await ping(page, "qa-ping-foreign")
    const inits = await init(page, "qa-init-foreign", "1.0.0", makeConfig({ config_revision: 6 }))
    record(
      "foreign origin: bridge fully silent (no PONG, no INIT response)",
      pongs.length === 0 && inits.length === 0,
      `pongs=${pongs.length} inits=${inits.length}`,
    )
    await page.screenshot({ path: path.join(evidenceDir, "qa-3-foreign-origin-silent.png") })
  })
} finally {
  await context.close()
}

fs.writeFileSync(
  path.join(evidenceDir, "release-browser-qa-results.json"),
  JSON.stringify({ ranAt: new Date().toISOString(), results }, null, 2),
)

const failed = results.filter((r) => !r.pass)
console.log(`\n${results.length - failed.length}/${results.length} release-browser QA checks passed`)
console.log(`evidence: ${evidenceDir}`)
process.exit(failed.length === 0 ? 0 : 1)
