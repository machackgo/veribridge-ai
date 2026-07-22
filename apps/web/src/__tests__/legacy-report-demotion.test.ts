import { readdirSync, readFileSync, statSync } from "node:fs"
import { join, relative } from "node:path"
import { describe, expect, it } from "vitest"

/**
 * Canonical-report guard (MVP Part 13 — no duplicated recruiter reports).
 *
 * The recruiter-facing Verified Build Report is the per-project report:
 *   owner preview  →  /student/vbr/projects/{id}/report
 *   public share   →  /vbr/report/{token}
 *
 * The old session-scoped generic report at /r/{token} (backend:
 * /public/vbr/legacy-reports/*) is kept only for already-shared links. No
 * student- or recruiter-facing surface may link users INTO it — this scan
 * fails if a link to the legacy route ever reappears outside its own page.
 */

const WEB_SRC_ROOTS = [
  join(__dirname, "..", "app"),
  join(__dirname, "..", "..", "components"),
]

// The legacy page itself (must keep rendering old links) is the only allowed home.
const ALLOWED = [/app\/r\/\[token\]\//]

// href="/r/..." or template-built /r/${token} navigation into the legacy report.
const LEGACY_LINK = /(href\s*=\s*["'`{]*\/r\/|[`"']\/r\/\$\{)/

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name.startsWith(".")) continue
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(tsx|ts)$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(p)
  }
  return out
}

describe("legacy generic report demotion", () => {
  it("no UI surface links into the legacy /r/{token} report", () => {
    const offenders: string[] = []
    for (const root of WEB_SRC_ROOTS) {
      for (const file of walk(root)) {
        const rel = relative(join(__dirname, "..", ".."), file)
        if (ALLOWED.some((rx) => rx.test(rel.replace(/\\/g, "/")))) continue
        const src = readFileSync(file, "utf8")
        if (LEGACY_LINK.test(src)) offenders.push(rel)
      }
    }
    expect(offenders).toEqual([])
  })
})
