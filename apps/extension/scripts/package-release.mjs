// Build the Chrome Web Store release ZIP.
//
// Produces release/veribridge-recorder-v<version>.zip containing ONLY runtime
// files (manifest at the ZIP root), plus a SHA-256 checksum and a manifest of
// contents. The bundle is built with the release channel flag
// (__VB_DEV_BUILD__=false): localhost app origins untrusted, uploads pinned to
// the production API.
//
// Deterministic: zip entries are added in sorted order with a fixed mtime, so
// the same sources always produce the same checksum.

import { execFileSync } from "node:child_process"
import { createHash } from "node:crypto"
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
process.chdir(root)

const manifest = JSON.parse(fs.readFileSync("manifest.json", "utf8"))
const version = manifest.version

// 1. Clean release build.
fs.rmSync("dist", { recursive: true, force: true })
execFileSync("npm", ["run", "build:release"], { stdio: "inherit" })

// 2. Collect runtime files only.
const files = [
  "manifest.json",
  "popup.html",
  "recorder.html",
  "dist/background.js",
  "dist/content.js",
  "dist/popup.js",
  "dist/recorder.js",
  "icons/icon16.png",
  "icons/icon32.png",
  "icons/icon48.png",
  "icons/icon128.png",
].sort()

for (const f of files) {
  if (!fs.existsSync(f)) {
    console.error(`missing release file: ${f}`)
    process.exit(1)
  }
}

// 3. Guard rails: no dev channel, no sourcemaps, no secrets-looking strings.
const bundleText = files
  .filter((f) => f.endsWith(".js"))
  .map((f) => fs.readFileSync(f, "utf8"))
  .join("\n")
const guards = [
  [/sourceMappingURL/, "source map reference"],
  [/SUPABASE_SERVICE_ROLE|service_role/i, "service-role credential marker"],
  [/-----BEGIN [A-Z ]*PRIVATE KEY-----/, "private key"],
]
for (const [re, label] of guards) {
  if (re.test(bundleText)) {
    console.error(`release guard failed: found ${label} in bundle`)
    process.exit(1)
  }
}
if (fs.existsSync("dist/background.js.map")) {
  console.error("release guard failed: sourcemap emitted")
  process.exit(1)
}

// 4. Deterministic zip via a staging dir with fixed mtimes.
const releaseDir = "release"
const stage = path.join(releaseDir, `stage-v${version}`)
fs.rmSync(stage, { recursive: true, force: true })
fs.mkdirSync(stage, { recursive: true })
const FIXED_MTIME = new Date("2026-01-01T00:00:00Z")
for (const f of files) {
  const dest = path.join(stage, f)
  fs.mkdirSync(path.dirname(dest), { recursive: true })
  fs.copyFileSync(f, dest)
  fs.utimesSync(dest, FIXED_MTIME, FIXED_MTIME)
}
// fix directory mtimes too (zip stores them)
for (const dir of ["dist", "icons", "."]) {
  fs.utimesSync(path.join(stage, dir), FIXED_MTIME, FIXED_MTIME)
}

const zipName = `veribridge-recorder-v${version}.zip`
const zipPath = path.join(releaseDir, zipName)
fs.rmSync(zipPath, { force: true })
execFileSync("zip", ["-X", "-q", "-r", path.resolve(zipPath), ...files], {
  cwd: stage,
})
fs.rmSync(stage, { recursive: true, force: true })

// 5. Report checksum + contents.
const zipBytes = fs.readFileSync(zipPath)
const sha256 = createHash("sha256").update(zipBytes).digest("hex")
fs.writeFileSync(`${zipPath}.sha256`, `${sha256}  ${zipName}\n`)

const listing = execFileSync("unzip", ["-l", zipPath], { encoding: "utf8" })
console.log("\n── Release package ──────────────────────────────")
console.log(`zip:      ${path.resolve(zipPath)}`)
console.log(`size:     ${(zipBytes.length / 1024).toFixed(1)} KB`)
console.log(`sha256:   ${sha256}`)
console.log(`version:  ${version} (${manifest.version_name ?? "no version_name"})`)
console.log(`perms:    ${JSON.stringify(manifest.permissions)}`)
console.log(`hosts:    ${JSON.stringify(manifest.host_permissions)}`)
console.log("contents:")
console.log(listing)
