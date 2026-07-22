// Extension bundle build. Replaces the raw esbuild CLI invocation so every
// recorder-auth component embeds the same contract fingerprint, surfaced in
// debug state and the handoff ACK to detect stale/mixed Chrome runtimes.
import * as esbuild from "esbuild"

const watch = process.argv.includes("--watch")
// Keep this in sync with RECORDER_AUTH_BUILD_FINGERPRINT in recorderAuth.ts and
// the web handoff helper. It intentionally identifies the wire-contract build,
// not just the wall-clock time at which esbuild happened to run.
const buildId = "recorder-auth-5.6-debug-28284748"

/** @type {import("esbuild").BuildOptions} */
const options = {
  entryPoints: [
    "src/background.ts",
    "src/popup.ts",
    "src/content.ts",
    "src/recorder.ts",
  ],
  bundle: true,
  outdir: "dist",
  target: "chrome112",
  platform: "browser",
  define: { __VB_BUILD_ID__: JSON.stringify(buildId) },
}

if (watch) {
  const ctx = await esbuild.context(options)
  await ctx.watch()
  console.log(`[extension] watching — build id ${buildId}`)
} else {
  await esbuild.build(options)
  console.log(`[extension] built dist/ — build id ${buildId}`)
}
