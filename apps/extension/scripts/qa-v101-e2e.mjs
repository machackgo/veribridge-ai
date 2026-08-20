// V1.0.1 end-to-end browser QA of the unpacked extension in a real Chromium.
//
// Exercises the full recorder protocol from the page's point of view against
// intercepted origins (no real deploy, no production traffic) and a local
// stub API that records every upload the extension makes:
//
//   A. VeriBridge target (Bug 1): a https://veribridgeai.com target completes
//      the content-script readiness handshake, starts recording, shows the
//      HUD on the target tab, and Stop & Send uploads the proof.
//   B. External target + HUD navigation (Bug 2): recording survives full
//      same-origin and CROSS-ORIGIN navigation and SPA route changes with
//      exactly one HUD; unrelated tabs never show the HUD and their events
//      are never uploaded.
//   C. Arbitrary-navigation matrix (manual retest bug 0→1→0→2): the HUD
//      follows the ACTIVE PROOF SESSION through browser Back, Back→new
//      forward branch, repeated Back/Forward, SPA route changes across the
//      internal-path boundary, and BFCache restores — with timer and event
//      count derived from authoritative session state, exactly one HUD, and
//      Stop & Send working from a page reached after history branching.
//      Session C runs against a REAL local HTTP server (no interception) with
//      Chrome's BackForwardCache ENABLED (Playwright disables it by default,
//      which is exactly why pre-fix automated runs could not see the manual
//      failure mode).
//
// The screen-recording MediaRecorder itself is not driven here (Chromium's
// desktop-capture picker cannot be automated reliably cross-platform); the
// recorder tab's upload acknowledgement is injected via the extension's own
// RECORDER_VIDEO_UPLOADED message from the real recorder page, which is the
// exact contract the background consumes.
//
// Usage: node scripts/qa-v101-e2e.mjs
// Evidence (JSON + screenshots): release/browser-qa-v101/

import { execFileSync } from "node:child_process"
import fs from "node:fs"
import http from "node:http"
import path from "node:path"
import { createRequire } from "node:module"
import { fileURLToPath } from "node:url"

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
process.chdir(root)

const requireFrom = createRequire(path.resolve(root, "../web/package.json"))
const { chromium } = requireFrom("playwright")

const evidenceDir = path.join(root, "release", "browser-qa-v101")
fs.mkdirSync(evidenceDir, { recursive: true })

// ── Stage the unpacked DEV-channel build (localhost API base allowed) ───────
execFileSync("npm", ["run", "build"], { stdio: "inherit" })
const stage = path.join(evidenceDir, "ext-dev-unpacked")
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

// ── Stub Website Proof API — records every extension upload ─────────────────
const API_PORT = 8128
const apiCalls = []
const apiServer = http.createServer((req, res) => {
  let body = ""
  req.on("data", (chunk) => { body += chunk })
  req.on("end", () => {
    let parsed = null
    try { parsed = JSON.parse(body) } catch { /* non-JSON */ }
    apiCalls.push({
      method: req.method,
      url: req.url,
      authorization: req.headers.authorization ?? null,
      body: parsed,
    })
    res.writeHead(200, { "Content-Type": "application/json" })
    res.end(JSON.stringify({ ok: true }))
  })
})
await new Promise((resolve) => apiServer.listen(API_PORT, "127.0.0.1", resolve))

// ── Real local nav server for Session C ─────────────────────────────────────
// Route interception can suppress BFCache; the arbitrary-navigation matrix
// needs REAL document loads, real history entries, and real BFCache restores,
// so its pages come from an actual HTTP server. localhost paths mirror the
// production shape: /d/* are recordable pages, /dashboard is a VeriBridge-
// internal app path (the shared contract treats localhost app prefixes as
// internal, exactly like veribridgeai.com/dashboard).
const NAV_PORT = 8129
function navPage(name, links) {
  return `<!doctype html><html><head><title>${name}</title></head><body>
  <h1 style="font-family:sans-serif">${name}</h1>
  <p>Result: demo output panel for ${name}</p>
  ${links.map(([href, id]) => `<a id="${id}" href="${href}">${id}</a>`).join(" | ")}
  <script>
    window.addEventListener("pageshow", (e) => {
      console.log("[navqa] pageshow " + location.pathname + " persisted=" + e.persisted);
    });
  </script></body></html>`
}
const navPages = {
  "/d/dashboard": navPage("Dashboard (page 0)", [["/d/student", "to-student"], ["/d/recruiter", "to-recruiter"], ["/d/extra", "to-extra"]]),
  "/d/student": navPage("Student (page 1)", [["/d/dashboard", "to-dashboard"], ["/d/recruiter", "to-recruiter"]]),
  "/d/recruiter": navPage("Recruiter (page 2)", [["/d/dashboard", "to-dashboard"], ["/d/student", "to-student"]]),
  "/d/extra": navPage("Extra (page 3)", [["/d/dashboard", "to-dashboard"]]),
  "/dashboard": navPage("Internal app dashboard", [["/d/recruiter", "to-recruiter"]]),
}
const navServer = http.createServer((req, res) => {
  const pathname = new URL(req.url, `http://localhost:${NAV_PORT}`).pathname
  const body = navPages[pathname]
  if (!body) { res.writeHead(404); res.end("not found"); return }
  // no-store mirrors production Next.js dynamic responses (BFCache-hostile),
  // while history restores of OTHER entries still exercise BFCache.
  res.writeHead(200, { "Content-Type": "text/html", "Cache-Control": "no-store" })
  res.end(body)
})
await new Promise((resolve) => navServer.listen(NAV_PORT, "127.0.0.1", resolve))

const SCHEMA = 1
const ACCESS_TOKEN = "qa-v101-access-token"

function harnessHtml(title) {
  return `<!doctype html><html><head><title>${title}</title></head><body>
  <h1 style="font-family:sans-serif">${title}</h1>
  <p>Result: analysis output panel for ${title}</p>
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

function targetHtml(title) {
  return `<!doctype html><html><head><title>${title}</title></head><body>
  <h1 style="font-family:sans-serif">${title}</h1>
  <p>Demo content block with a visible result summary for ${title}.</p>
  <button id="demo-action">Run demo action</button>
  </body></html>`
}

function makeConfig(sessionId, websiteUrl, revision) {
  return {
    schema_version: SCHEMA,
    config_revision: revision,
    session_id: sessionId,
    owner_user_id: "qa-user-1",
    api_base_url: `http://localhost:${API_PORT}`,
    auth: { mechanism: "bearer", access_token: ACCESS_TOKEN, expires_at: null },
    project_id: null,
    website_url: websiteUrl,
    repository_url: null,
    claimed_skills: ["Research"],
    proof_objective: "QA end-to-end walkthrough",
    created_at: "2026-08-20T00:00:00.000Z",
    expires_at: null,
  }
}

const results = []
function record(name, pass, detail) {
  results.push({ name, pass, detail: String(detail ?? "") })
  console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail !== undefined ? ` — ${detail}` : ""}`)
}

async function waitFor(fn, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const value = await fn()
    if (value) return value
    if (Date.now() > deadline) throw new Error(`timeout waiting for ${label}`)
    await new Promise((r) => setTimeout(r, 200))
  }
}

const context = await chromium.launchPersistentContext("", {
  headless: false,
  viewport: { width: 1280, height: 800 },
  // Playwright disables Chrome's BackForwardCache by default. Real Chrome has
  // it ON, and the manual 0→1→0→2 HUD regression involves history navigation —
  // run with real-browser cache semantics.
  ignoreDefaultArgs: ["--disable-back-forward-cache"],
  args: [
    `--disable-extensions-except=${stage}`,
    `--load-extension=${stage}`,
  ],
})

// Intercepted origins — nothing leaves the machine. Playwright matches the
// most recently registered route first, so the general veribridgeai.com route
// is registered BEFORE the specific /student/** app-harness route.
await context.route("https://veribridgeai.com/**", (route) =>
  route.fulfill({ contentType: "text/html", body: targetHtml(`VeriBridge public ${new URL(route.request().url()).pathname}`) }))
await context.route("https://veribridgeai.com/student/**", (route) =>
  route.fulfill({ contentType: "text/html", body: harnessHtml("VeriBridge proof builder") }))
await context.route("https://www.wikipedia.org/**", (route) =>
  route.fulfill({ contentType: "text/html", body: targetHtml("Wikipedia portal") }))
await context.route("https://en.wikipedia.org/**", (route) =>
  route.fulfill({ contentType: "text/html", body: targetHtml(`Wikipedia article ${new URL(route.request().url()).pathname}`) }))
await context.route("https://unrelated.example.com/**", (route) =>
  route.fulfill({ contentType: "text/html", body: targetHtml("Unrelated site") }))

const hudHost = (page) => page.locator("#veribridge-recorder-host")

async function hudVisible(page, timeoutMs = 8000) {
  try {
    await hudHost(page).waitFor({ state: "attached", timeout: timeoutMs })
    return true
  } catch {
    return false
  }
}

async function appSend(page, type, payload) {
  await page.evaluate(({ t, p }) => window.__send(t, p), { t: type, p: payload })
}

async function received(page, type, requestId) {
  return await page.evaluate(({ t, rid }) =>
    window.__received.find((m) => m.type === t && (!rid || m.payload?.request_id === rid)) ?? null,
  { t: type, rid: requestId })
}

async function runSession({ label, sessionId, websiteUrl, revision, appPage }) {
  // INIT
  await appSend(appPage, "VERIBRIDGE_RECORDER_INIT_REQUEST", {
    request_id: `${sessionId}-init`,
    expected_schema_version: SCHEMA,
    expected_build_version: "1.0.0",
    config: makeConfig(sessionId, websiteUrl, revision),
  })
  const ack = await waitFor(
    () => received(appPage, "VERIBRIDGE_RECORDER_INIT_ACK", `${sessionId}-init`),
    8000, `${label} INIT ACK`,
  )
  record(`${label}: INIT acknowledged`, ack.payload.session_id === sessionId, ack.payload.session_id)

  // TARGET OPEN — the background opens the target tab itself.
  const pagePromise = context.waitForEvent("page", { timeout: 10000 })
  await appSend(appPage, "VERIBRIDGE_RECORDER_TARGET_OPEN_REQUEST", {
    request_id: `${sessionId}-target`,
    session_id: sessionId,
    config_revision: revision,
  })
  const targetPage = await pagePromise
  await targetPage.waitForLoadState("domcontentloaded")
  const ready = await waitFor(
    () => received(appPage, "VERIBRIDGE_RECORDER_TARGET_READY", `${sessionId}-target`),
    12000, `${label} TARGET READY`,
  )
  record(
    `${label}: target content script announced readiness`,
    ready.payload.session_id === sessionId &&
      new URL(ready.payload.target_url).origin === new URL(websiteUrl).origin,
    ready.payload.target_url,
  )

  // START
  await appSend(appPage, "VERIBRIDGE_RECORDER_START_REQUEST", {
    request_id: `${sessionId}-start`,
    session_id: sessionId,
    config_revision: revision,
  })
  const started = await waitFor(
    () => received(appPage, "VERIBRIDGE_RECORDER_START_ACK", `${sessionId}-start`),
    8000, `${label} START ACK`,
  )
  record(`${label}: recording started`, started.payload.ready === true, started.payload.started_at)

  // HUD appears on the target tab.
  await targetPage.bringToFront()
  record(`${label}: HUD appears on the target tab`, await hudVisible(targetPage))
  return targetPage
}

async function findRecorderPage() {
  return await waitFor(async () => {
    for (const p of context.pages()) {
      if (p.url().startsWith("chrome-extension://") && p.url().includes("recorder.html")) return p
    }
    return null
  }, 8000, "recorder tab")
}

async function markVideoUploaded(sessionId) {
  const recorderPage = await findRecorderPage()
  await recorderPage.evaluate((sid) => new Promise((resolve) => {
    chrome.runtime.sendMessage(
      { type: "RECORDER_VIDEO_UPLOADED", payload: { ok: true, keyframe_count: 3, session_id: sid } },
      () => resolve(chrome.runtime.lastError ? "err" : "ok"),
    )
  }), sessionId)
}

async function stopAndSendFromHud(page, label, sessionId) {
  await page.bringToFront()
  const send = page.locator("#vb-send")
  await send.waitFor({ state: "attached", timeout: 8000 })
  await send.click()
  const upload = await waitFor(
    () => apiCalls.find((c) => c.url === `/api/v1/student/extension-proof/sessions/${sessionId}/upload`) ?? null,
    20000, `${label} proof upload`,
  )
  record(
    `${label}: Stop & Send uploaded the proof with recorder auth`,
    upload.authorization === `Bearer ${ACCESS_TOKEN}`,
    upload.url,
  )
  return upload
}

let exitCode = 0
try {
  const appPage = await context.newPage()
  await appPage.goto("https://veribridgeai.com/student/proofs/website", { waitUntil: "domcontentloaded" })
  await appPage.waitForTimeout(800)

  // ── Session A — VeriBridge itself as the recording target (Bug 1) ─────────
  const vbTarget = await runSession({
    label: "A (veribridgeai.com target)",
    sessionId: "qa-v101-session-vb",
    websiteUrl: "https://veribridgeai.com/",
    revision: 2,
    appPage,
  })
  await vbTarget.screenshot({ path: path.join(evidenceDir, "a-veribridge-target-hud.png") })
  await markVideoUploaded("qa-v101-session-vb")
  const uploadA = await stopAndSendFromHud(vbTarget, "A (veribridgeai.com target)", "qa-v101-session-vb")
  record(
    "A: uploaded workflow contains veribridgeai.com activity",
    Array.isArray(uploadA.body?.tracked_urls) &&
      uploadA.body.tracked_urls.some((u) => u.startsWith("https://veribridgeai.com")),
    JSON.stringify(uploadA.body?.tracked_urls ?? []),
  )
  await vbTarget.close()

  // ── Session B — external target + navigation/HUD matrix (Bug 2) ───────────
  const wikiTarget = await runSession({
    label: "B (external target)",
    sessionId: "qa-v101-session-wiki",
    websiteUrl: "https://www.wikipedia.org/",
    revision: 2,
    appPage,
  })

  // Full cross-origin navigation in the SAME tab (www → en.wikipedia.org).
  await wikiTarget.goto("https://en.wikipedia.org/wiki/Alan_Turing", { waitUntil: "domcontentloaded" })
  record("B: HUD survives full CROSS-ORIGIN navigation", await hudVisible(wikiTarget, 10000))
  record("B: exactly one HUD after navigation", (await hudHost(wikiTarget).count()) === 1)

  // Second full navigation — still exactly one HUD, still recording.
  await wikiTarget.goto("https://en.wikipedia.org/wiki/Enigma_machine", { waitUntil: "domcontentloaded" })
  record("B: HUD survives repeated navigation", await hudVisible(wikiTarget, 10000))
  record("B: no duplicate HUD after repeated navigation", (await hudHost(wikiTarget).count()) === 1)

  // SPA route change (history.pushState) — HUD stays mounted.
  await wikiTarget.evaluate(() => history.pushState({}, "", "/wiki/Bletchley_Park"))
  await wikiTarget.waitForTimeout(1500)
  record("B: HUD persists across SPA route change", (await hudHost(wikiTarget).count()) === 1)

  // Recording state (timer/count) is rehydrated, not restarted: the HUD shows
  // the Recording state fed from the background's authoritative session.
  const hudText = await wikiTarget.locator("#veribridge-recorder-host .bar").innerText()
  record("B: HUD shows live Recording state", /Recording/.test(hudText), hudText.split("\n")[0])

  // An unrelated tab never gets the HUD, and its activity is never captured.
  // NOTE: Playwright's newPage() stamps openerTabId with the previously
  // ACTIVE tab — a tab opened from a session tab is deliberately part of the
  // session (link-in-new-tab). Activate the app tab first so this new tab's
  // opener is the (untracked) proof-builder tab, matching a user's own
  // unrelated tab.
  await appPage.bringToFront()
  const unrelated = await context.newPage()
  await unrelated.goto("https://unrelated.example.com/", { waitUntil: "domcontentloaded" })
  await unrelated.waitForTimeout(2500)
  record("B: unrelated tab shows NO HUD", (await unrelated.locator("#veribridge-recorder-host").count()) === 0)
  await unrelated.click("#demo-action")
  await unrelated.waitForTimeout(1200)

  await wikiTarget.screenshot({ path: path.join(evidenceDir, "b-wiki-target-hud.png") })
  await markVideoUploaded("qa-v101-session-wiki")
  const uploadB = await stopAndSendFromHud(wikiTarget, "B (external target)", "qa-v101-session-wiki")
  const trackedB = uploadB.body?.tracked_urls ?? []
  record(
    "B: uploaded workflow NEVER contains unrelated-tab activity",
    Array.isArray(trackedB) && !trackedB.some((u) => u.includes("unrelated.example.com")) &&
      !(uploadB.body?.workflow_events ?? []).some((e) => String(e.page_url ?? "").includes("unrelated.example.com")),
    JSON.stringify(trackedB),
  )
  record(
    "B: uploaded workflow contains the cross-origin session pages",
    trackedB.some((u) => u.includes("en.wikipedia.org")),
    JSON.stringify(trackedB),
  )

  // Upload success is reflected in the HUD, then the session tab cleans up.
  const okMsg = wikiTarget.locator("#veribridge-recorder-host .msg.ok")
  let uploadedShown = false
  try {
    await okMsg.waitFor({ state: "attached", timeout: 8000 })
    uploadedShown = true
  } catch { /* recorded below */ }
  record("B: HUD reports the successful upload", uploadedShown)

  // Side-evidence uploads also reached the API with auth.
  record(
    "B: visible-evidence batch uploaded",
    apiCalls.some((c) => c.url.endsWith("/qa-v101-session-wiki/workflow/visible-evidence") &&
      c.authorization === `Bearer ${ACCESS_TOKEN}`),
  )
  await wikiTarget.close()

  // ── Session C — arbitrary-navigation matrix (manual 0→1→0→2 regression) ───
  const NAV = (p) => `http://localhost:${NAV_PORT}${p}`
  const navTarget = await runSession({
    label: "C (arbitrary navigation)",
    sessionId: "qa-v101-session-nav",
    websiteUrl: NAV("/d/dashboard"),
    revision: 2,
    appPage,
  })
  const navConsole = []
  navTarget.on("console", (m) => { if (m.text().includes("[navqa]")) navConsole.push(m.text()) })

  async function hudStats(page) {
    try {
      const text = await page.locator("#veribridge-recorder-host .bar").innerText({ timeout: 4000 })
      const timer = text.match(/(\d{2}):(\d{2})/)
      const events = text.match(/(\d+)\s+events?/)
      return {
        secs: timer ? Number(timer[1]) * 60 + Number(timer[2]) : null,
        events: events ? Number(events[1]) : null,
      }
    } catch {
      return { secs: null, events: null }
    }
  }
  // BFCache restores commit without a load event — wait for commit + reconcile.
  async function historyNav(page, direction) {
    await page[direction]({ waitUntil: "commit" }).catch(() => undefined)
    await page.waitForTimeout(1800)
  }

  await navTarget.waitForTimeout(1600)
  const statsStart = await hudStats(navTarget)
  record("C: HUD on page 0 at recording start", await hudVisible(navTarget), JSON.stringify(statsStart))
  await navTarget.screenshot({ path: path.join(evidenceDir, "01-recording-dashboard.png") })

  // TEST 1 — 0 → 1 (forward navigation via a real link click).
  await navTarget.click("#to-student")
  await navTarget.waitForURL("**/d/student")
  await navTarget.waitForTimeout(1800)
  const statsFwd = await hudStats(navTarget)
  record("C: 0→1 HUD present after forward navigation", await hudVisible(navTarget), JSON.stringify(statsFwd))
  record(
    "C: timer continues (not reset) after forward navigation",
    statsFwd.secs !== null && statsStart.secs !== null && statsFwd.secs >= statsStart.secs,
    `start=${statsStart.secs}s fwd=${statsFwd.secs}s`,
  )
  await navTarget.screenshot({ path: path.join(evidenceDir, "02-forward-navigation-hud.png") })

  // TEST 2 — browser Back → 0.
  await historyNav(navTarget, "goBack")
  record(
    "C: 0→1→BACK→0 HUD present after browser Back",
    await hudVisible(navTarget),
    navTarget.url(),
  )
  await navTarget.screenshot({ path: path.join(evidenceDir, "03-back-navigation-hud.png") })

  // TEST 3 — THE EXACT MANUAL REGRESSION: Back then a NEW forward branch.
  await navTarget.click("#to-recruiter")
  await navTarget.waitForURL("**/d/recruiter")
  await navTarget.waitForTimeout(1800)
  const statsBranch = await hudStats(navTarget)
  record(
    "C: 0→1→0→2 HUD present after Back→new-branch (manual bug)",
    await hudVisible(navTarget),
    `url=${navTarget.url()} ${JSON.stringify(statsBranch)}`,
  )
  record("C: exactly one HUD after history branching", (await hudHost(navTarget).count()) === 1)
  record(
    "C: timer continuity across Back→new-branch",
    statsBranch.secs !== null && statsFwd.secs !== null && statsBranch.secs >= statsFwd.secs,
    `fwd=${statsFwd.secs}s branch=${statsBranch.secs}s`,
  )
  record(
    "C: event count never goes backward across navigation",
    statsBranch.events !== null && statsStart.events !== null && statsBranch.events >= statsStart.events,
    `start=${statsStart.events} branch=${statsBranch.events}`,
  )
  await navTarget.screenshot({ path: path.join(evidenceDir, "04-back-then-new-branch-hud.png") })

  // TEST 4/5 — multiple Back/Forward traversals, HUD at every step.
  await navTarget.click("#to-dashboard")
  await navTarget.waitForURL("**/d/dashboard")
  await navTarget.waitForTimeout(1500)
  record("C: HUD after 2→0 link navigation", await hudVisible(navTarget), navTarget.url())
  await navTarget.click("#to-extra")
  await navTarget.waitForURL("**/d/extra")
  await navTarget.waitForTimeout(1500)
  record("C: HUD after 0→3 link navigation", await hudVisible(navTarget), navTarget.url())
  await historyNav(navTarget, "goBack")
  record("C: HUD after Back (multi-history step 1)", await hudVisible(navTarget), navTarget.url())
  await historyNav(navTarget, "goBack")
  record("C: HUD after second Back (multi-history step 2)", await hudVisible(navTarget), navTarget.url())
  await historyNav(navTarget, "goForward")
  record("C: HUD after Forward (multi-history step 3)", await hudVisible(navTarget), navTarget.url())
  record("C: exactly one HUD after repeated Back/Forward", (await hudHost(navTarget).count()) === 1)
  await navTarget.screenshot({ path: path.join(evidenceDir, "05-multi-history-hud.png") })

  // TEST 6 — SPA route changes crossing the internal-path boundary. The HUD
  // follows the SESSION TAB even onto internal app paths (capture stays
  // excluded there); returning to an eligible route keeps exactly one HUD.
  await navTarget.evaluate(() => history.pushState({}, "", "/dashboard"))
  await navTarget.waitForTimeout(2000)
  record("C: HUD stays with the session tab on internal SPA route", (await hudHost(navTarget).count()) === 1, navTarget.url())
  await navTarget.evaluate(() => history.pushState({}, "", "/d/student"))
  await navTarget.waitForTimeout(2000)
  record("C: HUD present after SPA internal→eligible route", await hudVisible(navTarget), navTarget.url())
  record("C: exactly one HUD across SPA route changes", (await hudHost(navTarget).count()) === 1)
  // SPA back (popstate, same document).
  await navTarget.evaluate(() => history.back())
  await navTarget.waitForTimeout(2000)
  record("C: HUD present after SPA popstate back", (await hudHost(navTarget).count()) === 1, navTarget.url())
  await navTarget.evaluate(() => history.pushState({}, "", "/d/recruiter"))
  await navTarget.waitForTimeout(1500)

  // TEST 7 — BFCache actually engaged during the history traversals above.
  record(
    "C: BFCache restore occurred and was reconciled (pageshow persisted=true)",
    navConsole.some((t) => t.includes("persisted=true")),
    `${navConsole.filter((t) => t.includes("persisted=true")).length} restore(s)`,
  )

  // TEST 12/13 — Stop & Send from a page reached after history branching:
  // exactly one upload, one finalization.
  const statsPreStop = await hudStats(navTarget)
  record(
    "C: timer still authoritative before Stop & Send",
    statsPreStop.secs !== null && statsBranch.secs !== null && statsPreStop.secs >= statsBranch.secs,
    `branch=${statsBranch.secs}s preStop=${statsPreStop.secs}s`,
  )
  await navTarget.screenshot({ path: path.join(evidenceDir, "06-stop-and-send.png") })
  await markVideoUploaded("qa-v101-session-nav")
  const uploadC = await stopAndSendFromHud(navTarget, "C (arbitrary navigation)", "qa-v101-session-nav")
  const uploadCallsC = apiCalls.filter((c) =>
    c.url === "/api/v1/student/extension-proof/sessions/qa-v101-session-nav/upload")
  record("C: exactly ONE proof upload after arbitrary navigation", uploadCallsC.length === 1, `${uploadCallsC.length} upload call(s)`)
  const eventsC = uploadC.body?.workflow_events ?? []
  record(
    "C: workflow contains the branched navigation trail",
    Array.isArray(uploadC.body?.tracked_urls) &&
      uploadC.body.tracked_urls.some((u) => u.includes("/d/recruiter")) &&
      uploadC.body.tracked_urls.some((u) => u.includes("/d/student")),
    JSON.stringify(uploadC.body?.tracked_urls ?? []),
  )
  record(
    "C: no page-level evidence from VeriBridge-internal paths",
    !eventsC.some((e) =>
      (e.type === "page_visit" || e.type === "click" || e.type === "input_change") &&
      String(e.page_url ?? "").includes(`localhost:${NAV_PORT}/dashboard`)),
    `${eventsC.length} workflow events`,
  )
  const okMsgC = navTarget.locator("#veribridge-recorder-host .msg.ok")
  let uploadedShownC = false
  try {
    await okMsgC.waitFor({ state: "attached", timeout: 8000 })
    uploadedShownC = true
  } catch { /* recorded below */ }
  record("C: HUD reports the successful upload", uploadedShownC)
  await navTarget.screenshot({ path: path.join(evidenceDir, "07-proof-uploaded.png") })

  // TEST 14 — completed session: HUD does not come back on later history
  // navigation. Wait out the auto-dismiss, then traverse history.
  await navTarget.waitForTimeout(6500)
  await historyNav(navTarget, "goBack")
  await navTarget.waitForTimeout(1500)
  record(
    "C: HUD does NOT reappear after the session completed",
    (await hudHost(navTarget).count()) === 0,
    navTarget.url(),
  )
} catch (err) {
  record("harness", false, err.message)
  exitCode = 1
} finally {
  await context.close().catch(() => undefined)
  apiServer.close()
  navServer.close()
}

const passCount = results.filter((r) => r.pass).length
console.log(`\n${passCount}/${results.length} V1.0.1 E2E checks passed`)
fs.writeFileSync(
  path.join(evidenceDir, "results.json"),
  JSON.stringify({ finished_at: new Date().toISOString(), results, apiCalls: apiCalls.map(c => ({ method: c.method, url: c.url, auth: Boolean(c.authorization) })) }, null, 2),
)
console.log(`evidence: ${evidenceDir}`)
if (results.some((r) => !r.pass) || exitCode) process.exit(1)
