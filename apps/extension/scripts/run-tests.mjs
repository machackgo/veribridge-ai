import { spawnSync } from "node:child_process"
import { build } from "esbuild"

const outdir = "/tmp/veribridge-extension-tests"
const entries = [
  "tests/recorder-session-config.test.ts",
  "tests/recorder-bridge.test.ts",
  "tests/recorder-finalize.test.ts",
  "tests/background-recorder-lifecycle.test.ts",
  "tests/background-recovery.test.ts",
  "tests/background-finalize-orchestration.test.ts",
  "tests/background-init-gates.test.ts",
  "tests/background-v101-reliability.test.ts",
]

await build({
  entryPoints: entries,
  bundle: true,
  platform: "node",
  format: "esm",
  outdir,
  outExtension: { ".js": ".mjs" },
  target: "node20",
  logLevel: "warning",
})

const outputs = entries.map((entry) =>
  `${outdir}/${entry.split("/").at(-1).replace(/\.ts$/, ".mjs")}`,
)
const result = spawnSync(process.execPath, ["--test", ...outputs], { stdio: "inherit" })
process.exit(result.status ?? 1)
