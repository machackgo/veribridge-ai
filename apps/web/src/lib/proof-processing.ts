/**
 * proof-processing.ts — Phase J4
 * Reusable types, utilities, and step presets for all proof saving and
 * AI/NLP evidence processing progress flows.
 */

// ── Core types ────────────────────────────────────────────────────────────────

export type ProofProcessingStatus = "pending" | "running" | "completed" | "skipped" | "failed"

export type ProofProcessingStep = {
  id: string
  label: string
  description: string
  /** Natural-language agent copy shown as live action text in agent mode. */
  agentCopy?: string
  status: ProofProcessingStatus
  startedAt?: number
  completedAt?: number
  /** Current item index (for live "X of Y" display). */
  countCurrent?: number
  /** Total item count for this step. */
  countTotal?: number
  errorMessage?: string
}

export type ProofProcessingProgress = {
  steps: ProofProcessingStep[]
  overallStatus: "idle" | "running" | "completed" | "failed"
  savedCount: number
  skippedCount: number
  failedCount: number
  errorMessages: string[]
}

// ── Step factory ──────────────────────────────────────────────────────────────

export function makeStep(
  id: string,
  label: string,
  description: string,
  agentCopy?: string
): ProofProcessingStep {
  return { id, label, description, agentCopy, status: "pending" }
}

export function initialProgress(steps: ProofProcessingStep[]): ProofProcessingProgress {
  return { steps, overallStatus: "running", savedCount: 0, skippedCount: 0, failedCount: 0, errorMessages: [] }
}

// ── Step updaters (return new array — never mutate) ───────────────────────────

export function updateStep(
  steps: ProofProcessingStep[],
  id: string,
  patch: Partial<ProofProcessingStep>
): ProofProcessingStep[] {
  return steps.map((s) => (s.id === id ? { ...s, ...patch } : s))
}

export function startStep(steps: ProofProcessingStep[], id: string): ProofProcessingStep[] {
  return updateStep(steps, id, { status: "running", startedAt: Date.now() })
}

export function completeStep(
  steps: ProofProcessingStep[],
  id: string,
  patch?: Partial<ProofProcessingStep>
): ProofProcessingStep[] {
  return updateStep(steps, id, { status: "completed", completedAt: Date.now(), ...(patch ?? {}) })
}

export function skipStep(
  steps: ProofProcessingStep[],
  id: string,
  patch?: Partial<ProofProcessingStep>
): ProofProcessingStep[] {
  return updateStep(steps, id, { status: "skipped", completedAt: Date.now(), ...(patch ?? {}) })
}

export function failStep(
  steps: ProofProcessingStep[],
  id: string,
  errorMessage: string
): ProofProcessingStep[] {
  return updateStep(steps, id, { status: "failed", completedAt: Date.now(), errorMessage })
}

// ── Progress calculations ─────────────────────────────────────────────────────

/** 0–100 based on how many steps are no longer "pending" or "running". */
export function calculateProgressPercent(steps: ProofProcessingStep[]): number {
  if (steps.length === 0) return 0
  const done = steps.filter(
    (s) => s.status === "completed" || s.status === "skipped" || s.status === "failed"
  ).length
  return Math.round((done / steps.length) * 100)
}

/** Label for the step currently running, or the last completed step. */
export function getCurrentStepLabel(steps: ProofProcessingStep[]): string {
  const running = steps.find((s) => s.status === "running")
  if (running) {
    if (running.countCurrent != null && running.countTotal != null) {
      return `${running.label} — ${running.countCurrent} of ${running.countTotal}`
    }
    return running.label
  }
  const lastDone = [...steps].reverse().find(
    (s) => s.status === "completed" || s.status === "skipped"
  )
  return lastDone?.label ?? "Starting…"
}

// ── Step presets per flow ─────────────────────────────────────────────────────

// ── Scan-phase step presets ───────────────────────────────────────────────────

/** Steps for the GitHub portfolio scan itself (before review). */
export function createGitHubScanProgressSteps(): ProofProcessingStep[] {
  return [
    makeStep("connect", "Connecting to GitHub",    "Connecting to the GitHub API.",                           "Connecting to GitHub..."),
    makeStep("scan",    "Scanning repositories",   "Reading READMEs, code, configs, and deployment files.",   "Scanning repositories and reading evidence..."),
    makeStep("group",   "Grouping skills",          "Connecting evidence to parent skill categories.",          "Grouping skills and building the Skill Graph..."),
    makeStep("prepare", "Preparing review screen",  "Organizing grouped skills and system graphs.",             "Almost ready — preparing your review..."),
  ]
}

/** Steps for a future website/portfolio scan flow. */
export function createWebsiteScanProgressSteps(): ProofProcessingStep[] {
  return [
    makeStep("connect", "Reading website URL",     "Checking accessibility of the live URL.",                 "Reading your website..."),
    makeStep("fetch",   "Fetching page content",   "Downloading visible page text and structure.",             "Fetching page content..."),
    makeStep("analyze", "Analyzing content",       "Looking for skill signals in the page.",                   "Analyzing content for skill evidence..."),
    makeStep("prepare", "Preparing results",       "Organizing evidence and matching skills.",                  "Preparing results..."),
  ]
}

/** Generic step preset for future source scanners (LinkedIn, YouTube, Drive…). */
export function createGenericSourceScanProgressSteps(sourceName: string): ProofProcessingStep[] {
  return [
    makeStep("connect", `Reading ${sourceName} link`, `Connecting to ${sourceName}.`,            `Reading your ${sourceName} link...`),
    makeStep("fetch",   "Fetching content",            "Retrieving available content.",           "Fetching content..."),
    makeStep("analyze", "Analyzing content",           "Looking for skill evidence.",             "Analyzing for skill evidence..."),
    makeStep("prepare", "Preparing results",           "Matching evidence to skills.",            "Preparing results..."),
  ]
}

/** Steps for saving selected grouped skills from GitHub portfolio scan. */
export function createGitHubScanSaveSteps(): ProofProcessingStep[] {
  return [
    makeStep("prepare",   "Preparing selected skills",      "Reading selected grouped skills and evidence items.",       "Reading your selected grouped skills..."),
    makeStep("duplicates","Checking for duplicates",        "Comparing selected evidence against your saved proof.",     "Checking what's already saved in your profile..."),
    makeStep("save",      "Saving proof evidence",          "Uploading GitHub evidence links, file paths, and line ranges.", "Saving GitHub file and line proof..."),
    makeStep("verify",    "Running verification",           "Matching evidence to skills and confidence levels on the server.", "Connecting evidence to your skill categories..."),
    makeStep("graph",     "Building skill graph",           "Updating grouped skills, subskills, source badges, and system graphs.", "Updating grouped skills and the Skill Graph..."),
    makeStep("refresh",   "Refreshing Skill Proof Center",  "Reloading your saved evidence and updating your profile.", "Updating your Skill Proof Center..."),
    makeStep("complete",  "Complete",                       "All done.", "Done."),
  ]
}

/** Steps for manual GitHub code proof submission. */
export function createManualGitHubSaveSteps(): ProofProcessingStep[] {
  return [
    makeStep("validate", "Validating proof fields",       "Checking required fields and formats.",                         "Checking your proof details..."),
    makeStep("save",     "Saving proof evidence",         "Creating your GitHub code proof record.",                       "Saving proof to your profile..."),
    makeStep("verify",   "Running verification",          "Running semantic verification and generating the recruiter report.", "Running skill verification..."),
    makeStep("links",    "Generating access links",       "Creating recruiter-accessible evidence links.",                 "Generating recruiter-accessible evidence links..."),
    makeStep("refresh",  "Refreshing Skill Proof Center", "Reloading your saved evidence.",                               "Connecting proof to your Skill Graph..."),
    makeStep("complete", "Complete",                      "GitHub proof evidence saved.",                                  "Proof saved successfully."),
  ]
}

/** Steps for manual website proof submission. */
export function createWebsiteSaveSteps(): ProofProcessingStep[] {
  return [
    makeStep("validate", "Validating website URL",        "Checking the URL and proof fields.",                     "Reading your website link..."),
    makeStep("save",     "Saving website proof",          "Creating the website proof record.",                     "Saving website proof source..."),
    makeStep("verify",   "Running website verification",  "AI checking your live website for skill demonstration.", "Running website AI verification..."),
    makeStep("links",    "Generating access links",       "Creating recruiter-accessible proof links.",             "Generating recruiter-accessible links..."),
    makeStep("refresh",  "Refreshing Skill Proof Center", "Reloading your saved evidence.",                        "Connecting website proof to your Skill Graph..."),
    makeStep("complete", "Complete",                      "Website proof saved and verified.",                      "Website proof saved."),
  ]
}

/** Steps for AI Agent link save (any source type). */
export function createAgentLinkSaveSteps(): ProofProcessingStep[] {
  return [
    makeStep("read",    "Reading resource link",          "Parsing the source URL and metadata.",                 "Reading your source link..."),
    makeStep("save",    "Saving source link",             "Creating your proof evidence record.",                 "Saving evidence safely..."),
    makeStep("queue",   "Queuing for AI extraction",      "Marking this source for future AI analysis.",          "Marking for future AI extraction..."),
    makeStep("links",   "Generating access links",        "Creating recruiter-accessible evidence links.",        "Generating access links..."),
    makeStep("refresh", "Refreshing Skill Proof Center",  "Reloading your saved evidence.",                      "Updating your Skill Proof Center..."),
    makeStep("complete","Complete",                       "Source link saved.",                                   "Source link saved."),
  ]
}
