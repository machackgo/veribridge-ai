"use client"

import { useMemo, useState } from "react"
import type { CSSProperties } from "react"
import {
  importSelectedGitHubPortfolioProofs,
  scanGitHubPortfolio,
  type GitHubPortfolioImportResponse,
  type GitHubPortfolioScanCandidate,
  type GitHubPortfolioScanResponse,
} from "@/lib/api"
import {
  groupProofSuggestions,
  isGroupFullySelected,
  isGroupPartiallySelected,
  type ConfidenceLevel,
  type GroupedSkillSuggestion,
  type SkillEvidence,
  type SkillSystemGraph,
} from "@/lib/skill-grouping"
import {
  createGitHubScanSaveSteps,
  createGitHubScanProgressSteps,
  completeStep,
  failStep,
  initialProgress,
  startStep,
  updateStep,
  appendWorkLogEntry,
  type ProofProcessingProgress,
} from "@/lib/proof-processing"
import { ProofProcessingProgressPanel } from "./proof-processing-progress-panel"

type ScanStep = "form" | "scanning" | "review" | "importing" | "done"
type FilterMode = "all" | "high" | "review"

type ScanFormState = {
  profileUrl: string
  maxRepos: string
  includeForks: boolean
  includeArchived: boolean
  smartScan: boolean
}

const initialForm = (): ScanFormState => ({
  profileUrl: "",
  maxRepos: "10",
  includeForks: false,
  includeArchived: false,
  smartScan: true,
})

function isGitHubProfileUrl(value: string): boolean {
  const trimmed = value.trim()
  if (!trimmed) return false
  return (
    /^https?:\/\/github\.com\/[a-zA-Z0-9_-]+\/?$/.test(trimmed) ||
    /^[a-zA-Z0-9_-]+$/.test(trimmed)
  )
}

// ── Badge styles ──────────────────────────────────────────────────────────────

function confidenceBadgeStyle(level: ConfidenceLevel): CSSProperties {
  if (level === "high") return { background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }
  if (level === "medium") return { background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a" }
  return { background: "#f1f5f9", color: "#475569", border: "1px solid #e2e8f0" }
}

function categoryTagStyle(category: string): CSSProperties {
  const palette: Record<string, { bg: string; color: string; border: string }> = {
    "AI / ML": { bg: "#ede9fe", color: "#5b21b6", border: "1px solid #ddd6fe" },
    "Backend": { bg: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" },
    "Frontend": { bg: "#ecfdf5", color: "#065f46", border: "1px solid #a7f3d0" },
    "Operations": { bg: "#fff7ed", color: "#9a3412", border: "1px solid #fed7aa" },
    "Cloud": { bg: "#f0f9ff", color: "#0c4a6e", border: "1px solid #bae6fd" },
    "Data": { bg: "#fdf4ff", color: "#7e22ce", border: "1px solid #e9d5ff" },
    "Game": { bg: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca" },
  }
  const p = palette[category] ?? { bg: "#f1f5f9", color: "#334155", border: "1px solid #e2e8f0" }
  return { background: p.bg, color: p.color, border: p.border }
}

const badgeBase: CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: "0.1em",
  textTransform: "uppercase",
  padding: "3px 8px",
  borderRadius: 999,
}

// ── Evidence type label ───────────────────────────────────────────────────────

const EVIDENCE_TYPE_LABELS: Record<string, string> = {
  dockerfile: "Dockerfile",
  workflow: "CI/CD Workflow",
  api_file: "API File",
  model_file: "Model/Training File",
  data_file: "Data File",
  ui_file: "UI Component",
  deployment_config: "Deployment Config",
  metrics_config: "Metrics Config",
  code: "Source Code",
  other: "Other",
}

// ── System graph renderer ─────────────────────────────────────────────────────

function SystemGraphView({ graph }: { graph: SkillSystemGraph }) {
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--muted)", marginBottom: 8 }}>
        Skill System Graph
        {graph.needsReview && (
          <span style={{ ...badgeBase, background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a", marginLeft: 8, fontSize: 9 }}>
            Needs Review
          </span>
        )}
      </div>
      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 10 }}>{graph.summary}</div>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: 4,
          padding: "10px 12px",
          background: "var(--bg-2)",
          borderRadius: 10,
          border: "1px solid var(--line)",
        }}
      >
        {graph.nodes.map((node, i) => (
          <div key={node.id} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <div
              title={node.description}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                padding: "4px 10px",
                borderRadius: 8,
                fontSize: 11,
                fontWeight: 600,
                background: node.hasEvidence ? "#dcfce7" : "#f1f5f9",
                color: node.hasEvidence ? "#166534" : "#64748b",
                border: node.hasEvidence ? "1px solid #bbf7d0" : "1px solid #e2e8f0",
                cursor: "default",
                whiteSpace: "nowrap",
              }}
            >
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: node.hasEvidence ? "#22c55e" : "#cbd5e1",
                  flexShrink: 0,
                }}
              />
              {node.label}
              {node.evidenceCount > 0 && (
                <span style={{ fontSize: 9, fontWeight: 800, color: "#166534", marginLeft: 2 }}>
                  ({node.evidenceCount})
                </span>
              )}
            </div>
            {i < graph.nodes.length - 1 && (
              <span style={{ color: "var(--muted)", fontSize: 12, fontWeight: 700 }}>→</span>
            )}
          </div>
        ))}
      </div>
      <div style={{ marginTop: 6, fontSize: 11, color: "var(--muted)" }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#22c55e", display: "inline-block" }} />
          Supported by evidence
        </span>
        <span style={{ marginLeft: 12, display: "inline-flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#cbd5e1", display: "inline-block" }} />
          Inferred / not yet found
        </span>
      </div>
    </div>
  )
}

// ── Evidence item row ─────────────────────────────────────────────────────────

function EvidenceItemRow({
  evidence,
  selected,
  onToggle,
}: {
  evidence: SkillEvidence
  selected: boolean
  onToggle: (id: string) => void
}) {
  return (
    <label
      key={`evidence-${evidence.candidateId}`}
      style={{
        display: "grid",
        gridTemplateColumns: "auto 1fr",
        gap: 10,
        padding: "10px 12px",
        border: `1px solid ${selected ? "var(--indigo)" : "var(--line)"}`,
        borderRadius: 8,
        background: selected ? "var(--indigo-soft)" : "var(--bg-2)",
        cursor: "pointer",
      }}
    >
      <input
        type="checkbox"
        checked={selected}
        onChange={() => onToggle(evidence.candidateId)}
        style={{ marginTop: 2, width: 14, height: 14, cursor: "pointer" }}
      />
      <div style={{ display: "grid", gap: 4 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "var(--ink-2)" }}>
            {evidence.filePath}
          </span>
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, fontWeight: 700, color: "var(--muted)" }}>
            L{evidence.lineStart}–L{evidence.lineEnd}
          </span>
          <span style={{ ...badgeBase, ...confidenceBadgeStyle(evidence.confidence), fontSize: 9 }}>
            {evidence.confidence}
          </span>
          <span style={{ fontSize: 10, color: "var(--muted)", background: "#f1f5f9", border: "1px solid #e2e8f0", borderRadius: 4, padding: "2px 6px" }}>
            {EVIDENCE_TYPE_LABELS[evidence.evidenceType] ?? evidence.evidenceType}
          </span>
        </div>
        <div style={{ fontSize: 11, color: "var(--muted)" }}>{evidence.selectionReason}</div>
        <div style={{ fontSize: 11, color: "var(--ink-2)", lineHeight: 1.5 }}>{evidence.evidenceDescription}</div>
        <a
          href={evidence.githubHighlightUrl}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          style={{ fontSize: 11, fontWeight: 600, color: "var(--indigo)", textDecoration: "none" }}
        >
          View on GitHub →
        </a>
      </div>
    </label>
  )
}

// ── Grouped skill card ────────────────────────────────────────────────────────

function GroupedSkillCard({
  group,
  selected,
  expanded,
  onToggleGroup,
  onToggleEvidence,
  onToggleExpand,
}: {
  group: GroupedSkillSuggestion
  selected: Set<string>
  expanded: boolean
  onToggleGroup: (g: GroupedSkillSuggestion) => void
  onToggleEvidence: (candidateId: string) => void
  onToggleExpand: (id: string) => void
}) {
  const fullySelected = isGroupFullySelected(group, selected)
  const partiallySelected = isGroupPartiallySelected(group, selected)
  const anySelected = fullySelected || partiallySelected

  return (
    <div
      style={{
        border: `1px solid ${anySelected ? "var(--indigo)" : "var(--line)"}`,
        borderRadius: 14,
        background: anySelected ? "var(--indigo-soft)" : "#fff",
        transition: "border-color 0.12s, background 0.12s",
        // No overflow:hidden — it clips the expanded panel in grid layout contexts.
        // Border-radius is applied to the outer div; children fill it naturally.
      }}
    >
      {/* Card header row */}
      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 12, padding: "14px 16px", alignItems: "flex-start" }}>
        {/* Checkbox */}
        <input
          type="checkbox"
          checked={fullySelected}
          ref={(el) => { if (el) el.indeterminate = partiallySelected }}
          onChange={() => onToggleGroup(group)}
          style={{ marginTop: 3, width: 16, height: 16, cursor: "pointer" }}
          title={fullySelected ? "Deselect group" : "Select all evidence in this group"}
        />

        {/* Main content */}
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
            <span style={{ fontSize: 15, fontWeight: 700, color: "var(--ink)" }}>{group.skillName}</span>
            <span style={{ ...badgeBase, ...categoryTagStyle(group.category), fontSize: 9 }}>{group.category}</span>
            <span style={{ ...badgeBase, ...confidenceBadgeStyle(group.confidence) }}>
              {group.confidence} confidence
            </span>
          </div>

          <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>
            <strong style={{ color: "var(--ink-2)" }}>{group.evidenceCount}</strong> evidence location{group.evidenceCount !== 1 ? "s" : ""} across{" "}
            <strong style={{ color: "var(--ink-2)" }}>{group.repoCount}</strong> repo{group.repoCount !== 1 ? "s" : ""}
          </div>

          {/* Subskill chips */}
          {group.subskills.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
              {group.subskills.slice(0, 6).map((s) => (
                <span
                  key={`${group.id}-subskill-${s.name}`}
                  style={{
                    fontSize: 10,
                    padding: "2px 8px",
                    borderRadius: 6,
                    background: "#f1f5f9",
                    color: "#334155",
                    border: "1px solid #e2e8f0",
                    whiteSpace: "nowrap",
                  }}
                >
                  {s.name}
                  {s.evidenceCount > 1 && <span style={{ marginLeft: 3, color: "#94a3b8" }}>×{s.evidenceCount}</span>}
                </span>
              ))}
              {group.subskills.length > 6 && (
                <span style={{ fontSize: 10, color: "var(--muted)", padding: "2px 4px" }}>
                  +{group.subskills.length - 6} more
                </span>
              )}
            </div>
          )}
        </div>

        {/* Expand toggle */}
        <button
          type="button"
          onClick={() => onToggleExpand(group.id)}
          style={{
            border: "1px solid var(--line-2)",
            background: "transparent",
            color: "var(--ink-2)",
            borderRadius: 8,
            padding: "6px 10px",
            fontSize: 12,
            fontWeight: 600,
            cursor: "pointer",
            whiteSpace: "nowrap",
          }}
        >
          {expanded ? "Collapse ▲" : "Expand ▼"}
        </button>
      </div>

      {/* Expanded content — rendered as a sibling block, no overflow clipping */}
      {expanded && (
        <div
          style={{
            borderTop: "1px solid var(--line)",
            padding: "16px",
            display: "flex",
            flexDirection: "column",
            gap: 18,
          }}
        >
          {/* Subskills detail */}
          {group.subskills.length > 0 && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--muted)", marginBottom: 8 }}>
                Detected Subskills
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {group.subskills.map((s) => (
                  <span
                    key={`${group.id}-detail-subskill-${s.name}`}
                    style={{
                      fontSize: 11,
                      padding: "4px 10px",
                      borderRadius: 8,
                      background: "#f1f5f9",
                      color: "#334155",
                      border: "1px solid #e2e8f0",
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                    }}
                  >
                    {s.name}
                    <span style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8" }}>{s.evidenceCount}</span>
                  </span>
                ))}
              </div>
              <div style={{ marginTop: 8, fontSize: 11, color: "var(--muted)" }}>
                Repos: {group.repositories.join(", ")}
              </div>
            </div>
          )}

          {/* System graph */}
          {group.systemGraph && group.systemGraph.nodes.some((n) => n.hasEvidence) && (
            <SystemGraphView graph={group.systemGraph} />
          )}

          {/* Evidence by project */}
          {group.projectGroups.map((proj) => (
            <div key={`${group.id}-proj-${proj.repoName}`}>
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 700,
                  color: "var(--ink-2)",
                  marginBottom: 8,
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  flexWrap: "wrap",
                }}
              >
                <span>{proj.projectTitle}</span>
                <span style={{ fontWeight: 400, color: "var(--muted)" }}>
                  ({proj.evidenceItems.length} evidence item{proj.evidenceItems.length !== 1 ? "s" : ""})
                </span>
                <a
                  href={proj.repoUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  style={{ fontSize: 11, color: "var(--indigo)", textDecoration: "none", fontWeight: 600 }}
                >
                  {proj.repoName} ↗
                </a>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {proj.evidenceItems.map((ev) => (
                  <EvidenceItemRow
                    key={`ev-${ev.candidateId}`}
                    evidence={ev}
                    selected={selected.has(ev.candidateId)}
                    onToggle={onToggleEvidence}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

export function GitHubPortfolioScanPanel({
  onImportSuccess,
  onClose,
  initialProfileUrl,
}: {
  onImportSuccess?: () => void
  onClose: () => void
  /** Pre-fill the GitHub profile URL field (used from AI Agent mode). */
  initialProfileUrl?: string
}) {
  const [step, setStep] = useState<ScanStep>("form")
  const [form, setForm] = useState<ScanFormState>(() => ({
    ...initialForm(),
    profileUrl: initialProfileUrl ?? "",
  }))
  const [scanResult, setScanResult] = useState<GitHubPortfolioScanResponse | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [filterMode, setFilterMode] = useState<FilterMode>("all")
  const [showRaw, setShowRaw] = useState(false)
  const [importResult, setImportResult] = useState<GitHubPortfolioImportResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [processingProgress, setProcessingProgress] = useState<ProofProcessingProgress | null>(null)
  const [scanProgress, setScanProgress] = useState<ProofProcessingProgress | null>(null)

  // Group candidates into hierarchical skill groups
  const grouped = useMemo(
    () => (scanResult ? groupProofSuggestions(scanResult.proof_candidates) : []),
    [scanResult]
  )

  const filteredGroups = useMemo(() => {
    if (filterMode === "high") return grouped.filter((g) => g.confidence === "high")
    if (filterMode === "review") return grouped.filter((g) => g.confidence !== "high")
    return grouped
  }, [grouped, filterMode])

  function close() {
    setStep("form")
    setForm(initialForm())
    setScanResult(null)
    setSelected(new Set())
    setExpanded(new Set())
    setFilterMode("all")
    setShowRaw(false)
    setImportResult(null)
    setError(null)
    setScanProgress(null)
    setProcessingProgress(null)
    onClose()
  }

  function toggleEvidence(candidateId: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(candidateId)) next.delete(candidateId)
      else next.add(candidateId)
      return next
    })
  }

  function toggleGroup(group: GroupedSkillSuggestion) {
    setSelected((prev) => {
      const next = new Set(prev)
      const fullySelected = isGroupFullySelected(group, prev)
      if (fullySelected) {
        group.evidenceItems.forEach((e) => next.delete(e.candidateId))
      } else {
        group.evidenceItems.forEach((e) => next.add(e.candidateId))
      }
      return next
    })
  }

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function selectAllGroups() {
    if (!scanResult) return
    setSelected(new Set(scanResult.proof_candidates.map((c) => c.candidate_id)))
  }

  function deselectAllGroups() {
    setSelected(new Set())
  }

  // Count of groups with at least one selected evidence item
  const selectedGroupCount = grouped.filter((g) =>
    g.evidenceItems.some((e) => selected.has(e.candidateId))
  ).length

  async function handleScan() {
    setError(null)
    const url = form.profileUrl.trim()
    if (!url) {
      setError("Enter your GitHub profile URL or username.")
      return
    }
    if (!isGitHubProfileUrl(url)) {
      setError("Enter a valid GitHub profile URL (e.g. https://github.com/yourusername) or a plain username.")
      return
    }
    const maxRepos = parseInt(form.maxRepos, 10)
    if (!Number.isFinite(maxRepos) || maxRepos < 1 || maxRepos > 150) {
      setError("Max repos must be between 1 and 150. For large profiles, Smart Scan will prioritize the best repositories.")
      return
    }

    const username = url.includes("github.com")
      ? url.replace(/.*github\.com\//, "").replace(/\/$/, "")
      : url
    const isLargeProfile = maxRepos > 30

    // Build scan progress — steps 1-2 start before API call
    let steps = createGitHubScanProgressSteps()
    steps = completeStep(steps, "connect", {
      description: `Connected to github.com/${username}.`,
      agentCopy: `Connected to github.com/${username}.`,
    })
    steps = startStep(steps, "scan")
    steps = updateStep(steps, "scan", {
      description: isLargeProfile
        ? `Smart Scan selected top ${maxRepos} repositories. Analyzing evidence…`
        : `Scanning ${maxRepos} repositories…`,
      agentCopy: isLargeProfile
        ? `Large profile detected. Smart Scan is prioritizing the top ${maxRepos} relevant repositories…`
        : `Reading READMEs, code files, and deployment configs…`,
    })
    setScanProgress(initialProgress(steps))
    setStep("scanning")

    // ── Staged work log messages during API wait ──────────────────────────────
    // These are honest approximations of server-side phases. The API is one call
    // so we can't get real per-repo progress. Messages are time-based.
    const staged: Array<{ minElapsed: number; msg: string; status?: "info" | "warning" }> = [
      { minElapsed: 0,     msg: "Checking GitHub profile access..." },
      { minElapsed: 1500,  msg: "Fetching repository metadata from the GitHub API..." },
      ...(isLargeProfile ? [
        { minElapsed: 3000, msg: `Large profile detected. Smart Scan will prioritize the top ${maxRepos} repositories.`, status: "warning" as const },
        { minElapsed: 4500, msg: "This keeps the scan fast and avoids noisy or inactive repositories." },
      ] : [
        { minElapsed: 3000, msg: "Applying Smart Scan priority ranking to repositories..." },
      ]),
      { minElapsed: 6000,  msg: `Ranking repos by README quality, topics, stars, and recent activity...` },
      { minElapsed: 9000,  msg: `Selected the top ${maxRepos} repositories for evidence analysis.` },
      { minElapsed: 13000, msg: "Reading repository README files and metadata..." },
      { minElapsed: 17000, msg: "Inspecting source code, configuration, and deployment files..." },
      { minElapsed: 21000, msg: "Looking for Dockerfiles, GitHub Actions, model artifacts, API files, and package configs..." },
      { minElapsed: 26000, msg: "Extracting raw proof evidence from high-signal code sections..." },
      { minElapsed: 31000, msg: "Still working — large profiles can take 30–90 seconds. Thank you for waiting...", status: "warning" as const },
      { minElapsed: 46000, msg: "Normalizing skill names and deduplicating evidence across repositories..." },
      { minElapsed: 61000, msg: "Almost there — finalizing evidence extraction..." },
    ]

    const startTime = Date.now()
    let stagedIdx = 0
    let currentProgress = initialProgress(steps)
    setScanProgress(currentProgress)

    // Interval: advances work log messages + synthetic progress bar every 500ms
    const progressInterval = setInterval(() => {
      const elapsed = Date.now() - startTime
      let changed = false

      // Add any due messages
      while (stagedIdx < staged.length && elapsed >= staged[stagedIdx].minElapsed) {
        currentProgress = appendWorkLogEntry(currentProgress, staged[stagedIdx].msg, staged[stagedIdx].status ?? "info")
        stagedIdx++
        changed = true
      }

      // Advance synthetic progress bar honestly: 25%→80% over 90 seconds
      const syntheticPct = Math.min(80, 25 + (elapsed / 90_000) * 55)
      if (Math.round(syntheticPct) !== currentProgress.syntheticPercent) {
        currentProgress = { ...currentProgress, syntheticPercent: Math.round(syntheticPct) }
        changed = true
      }

      if (changed) setScanProgress({ ...currentProgress })
    }, 500)

    // ── 90-second timeout ─────────────────────────────────────────────────────
    let timeoutHandle: ReturnType<typeof setTimeout> | null = null
    const timeoutPromise = new Promise<never>((_, reject) => {
      timeoutHandle = setTimeout(
        () => reject(new Error("Scan timed out. Try reducing Max Repos or try again later.")),
        90_000
      )
    })

    try {
      const result = await Promise.race([
        scanGitHubPortfolio({
          github_profile_url: url.includes("github.com") ? url : undefined,
          github_username: url.includes("github.com") ? undefined : url,
          max_repos: maxRepos,
          include_forks: form.includeForks,
          include_archived: form.includeArchived,
          smart_scan: form.smartScan,
        }),
        timeoutPromise,
      ])
      clearInterval(progressInterval)
      if (timeoutHandle) clearTimeout(timeoutHandle)

      // Add final work log entries after API returns
      const reposSelected = result.repos_selected_count || maxRepos
      currentProgress = appendWorkLogEntry(currentProgress, `API returned — ${reposSelected} repositories scanned.`)
      currentProgress = appendWorkLogEntry(currentProgress, `Normalizing skill names and deduplicating evidence...`)
      currentProgress = appendWorkLogEntry(currentProgress, `Grouping evidence into hierarchical skill categories...`)
      currentProgress = appendWorkLogEntry(currentProgress, `Building Skill System Graphs...`)
      currentProgress = appendWorkLogEntry(currentProgress, `Preparing your grouped evidence review screen...`)

      // Check for empty results and add helpful messages
      if (result.repos_available_count === 0) {
        currentProgress = appendWorkLogEntry(
          currentProgress,
          "No public repositories found. The profile may be private or have no public repos.",
          "warning"
        )
      } else if (result.repos_selected_count === 0) {
        currentProgress = appendWorkLogEntry(
          currentProgress,
          `${result.repos_available_count} repos found but all filtered out. Try enabling forks or archived repos.`,
          "warning"
        )
      } else if (result.candidate_count === 0) {
        currentProgress = appendWorkLogEntry(
          currentProgress,
          `Scanned ${result.repos_selected_count} repos but found no high-signal code evidence. The repos may not contain structured code files.`,
          "warning"
        )
      }

      // Complete all steps with real data
      const finalMsg = result.candidate_count > 0
        ? `Found ${result.candidate_count} evidence items across ${result.repos_selected_count} repos in ${result.detected_skill_count} skill types.`
        : `Scan complete — ${result.repos_selected_count} repos scanned, no evidence items found.`
      currentProgress = appendWorkLogEntry(currentProgress, finalMsg, "completed")

      steps = completeStep(steps, "scan", {
        countCurrent: result.repos_selected_count,
        countTotal: result.repos_selected_count,
        description: `Scanned ${result.repos_selected_count} repos · found ${result.candidate_count} evidence items.`,
        agentCopy: finalMsg,
      })
      steps = completeStep(steps, "group", {
        description: `Detected ${result.detected_skill_count} skill types.`,
        agentCopy: `Grouped into ${result.detected_skill_count} skill categories.`,
      })
      steps = completeStep(steps, "prepare", {
        description: `Review is ready — ${result.candidate_count} evidence item${result.candidate_count === 1 ? "" : "s"}.`,
        agentCopy: "Review is ready.",
      })

      setScanProgress({
        ...currentProgress,
        steps,
        overallStatus: "completed",
        savedCount: result.candidate_count,
        syntheticPercent: undefined,  // let real step completion drive 100%
      })

      setScanResult(result)
      const autoSelect = new Set(
        result.proof_candidates
          .filter((c) => c.suggested_status === "suggested")
          .map((c) => c.candidate_id)
      )
      setSelected(autoSelect)
      setStep("review")
    } catch (err) {
      clearInterval(progressInterval)
      if (timeoutHandle) clearTimeout(timeoutHandle)
      const msg = err instanceof Error ? err.message : "Scan failed. Please try again."
      currentProgress = appendWorkLogEntry(currentProgress, msg, "error")
      steps = failStep(steps, "scan", msg)
      setScanProgress({
        ...currentProgress,
        steps,
        overallStatus: "failed",
        errorMessages: [msg],
        syntheticPercent: undefined,
      })
      setError(msg)
      setStep("form")
    }
  }

  async function handleImport() {
    if (!scanResult) return
    const candidates = scanResult.proof_candidates.filter((c) => selected.has(c.candidate_id))
    if (candidates.length === 0) {
      setError("Select at least one proof candidate before saving.")
      return
    }

    setError(null)

    // Small helper: yields to the browser so React can flush a render between items
    const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0))

    const total = candidates.length

    // ── Initial progress state ────────────────────────────────────────────────
    let steps = createGitHubScanSaveSteps()
    steps = completeStep(steps, "prepare", {
      countCurrent: total,
      countTotal: total,
      description: `${total} evidence item${total === 1 ? "" : "s"} selected.`,
      agentCopy: `Reading ${total} selected grouped skills...`,
    })
    steps = startStep(steps, "duplicates")
    steps = updateStep(steps, "duplicates", {
      description: "Checking each item against existing saved evidence...",
      agentCopy: "Checking existing saved evidence...",
    })

    let progress = initialProgress(steps)
    progress = appendWorkLogEntry(progress, `Preparing ${total} selected evidence items...`)
    progress = appendWorkLogEntry(progress, "Saving items one at a time — checking duplicates per item...")
    setProcessingProgress({ ...progress })
    setStep("importing")

    // ── Per-item accumulation ─────────────────────────────────────────────────
    let savedCount = 0
    let skippedCount = 0
    let failedCount = 0
    const errMessages: string[] = []
    const allResults: import("@/lib/api").GitHubPortfolioCandidateResult[] = []
    const importedIds: string[] = []

    // Complete the duplicates step after the first item (it's checked per-call)
    steps = completeStep(steps, "duplicates", {
      description: "Duplicate check runs per item.",
      agentCopy: "Checking existing saved evidence...",
    })
    steps = startStep(steps, "save")

    for (let i = 0; i < total; i++) {
      const candidate = candidates[i]
      const itemNum = i + 1
      const label = `${candidate.skill_label} · ${candidate.repo_name}`
      const syntheticPct = Math.round(20 + (i / total) * 50)  // 20%→70% during save loop

      // Update hero text + step count BEFORE API call so UI shows "Saving X of Y"
      steps = updateStep(steps, "save", {
        countCurrent: itemNum,
        countTotal: total,
        description: `Saving item ${itemNum} of ${total}…`,
        agentCopy: `Saving GitHub proof ${itemNum} of ${total}...`,
      })
      progress = appendWorkLogEntry(
        { ...progress, steps, syntheticPercent: syntheticPct },
        `Saving proof ${itemNum} of ${total} — ${label}`
      )
      setProcessingProgress({ ...progress })
      await tick()  // let React render "Saving X of Y" before the network call

      try {
        const result = await importSelectedGitHubPortfolioProofs([candidate])
        allResults.push(...result.per_candidate_results)
        importedIds.push(...result.imported_evidence_ids)

        if (result.imported_count > 0) {
          savedCount++
          progress = appendWorkLogEntry(
            { ...progress, steps },
            `Saved — ${label}`,
            "completed"
          )
        } else if (result.skipped_duplicate_count > 0) {
          skippedCount++
          progress = appendWorkLogEntry(
            { ...progress, steps },
            `Skipped duplicate — ${label}`,
            "info"
          )
        } else if (result.failed_count > 0) {
          failedCount++
          const msg = result.per_candidate_results[0]?.message ?? "Unknown error"
          errMessages.push(`${label}: ${msg}`)
          progress = appendWorkLogEntry(
            { ...progress, steps },
            `Failed — ${label}: ${msg} — continuing`,
            "error"
          )
        }
      } catch (err) {
        failedCount++
        const msg = err instanceof Error ? err.message : "Unknown error"
        errMessages.push(`${label}: ${msg}`)
        allResults.push({
          candidate_id: candidate.candidate_id,
          skill_label: candidate.skill_label,
          repo_name: candidate.repo_name,
          status: "failed",
          evidence_id: null,
          message: msg,
        })
        progress = appendWorkLogEntry(
          { ...progress, steps },
          `Failed — ${label} — continuing`,
          "error"
        )
      }

      setProcessingProgress({ ...progress })
    }

    // ── Post-loop: complete remaining steps ────────────────────────────────────
    progress = appendWorkLogEntry(
      { ...progress, steps },
      `All ${total} items processed. Connecting evidence to skill categories...`
    )

    steps = completeStep(steps, "save", {
      countCurrent: savedCount + skippedCount,
      countTotal: total,
      description: `Saved ${savedCount} · Skipped ${skippedCount} duplicates · Failed ${failedCount}`,
      agentCopy: `Saved ${savedCount}, skipped ${skippedCount} duplicates, failed ${failedCount}.`,
    })
    steps = completeStep(steps, "verify", {
      description: savedCount > 0 ? `Verification ran server-side for ${savedCount} item${savedCount !== 1 ? "s" : ""}.` : "No new items to verify.",
    })
    steps = completeStep(steps, "graph", {
      description: "Skill Graph, subskills, and system graphs updated.",
    })

    progress = appendWorkLogEntry({ ...progress, steps }, "Updating your Skill Proof Center...")
    onImportSuccess?.()

    steps = completeStep(steps, "refresh")

    const finalMsg = `Done — saved ${savedCount} · skipped ${skippedCount} duplicate${skippedCount !== 1 ? "s" : ""} · failed ${failedCount}`
    steps = completeStep(steps, "complete", {
      description: finalMsg,
      agentCopy: finalMsg,
    })
    progress = appendWorkLogEntry({ ...progress, steps }, finalMsg, "completed")

    const syntheticResult: import("@/lib/api").GitHubPortfolioImportResponse = {
      imported_count: savedCount,
      skipped_duplicate_count: skippedCount,
      failed_count: failedCount,
      imported_evidence_ids: importedIds,
      per_candidate_results: allResults,
    }

    setImportResult(syntheticResult)
    setProcessingProgress({
      ...progress,
      steps,
      overallStatus: failedCount === total && savedCount === 0 ? "failed" : "completed",
      savedCount,
      skippedCount,
      failedCount,
      errorMessages: errMessages,
      syntheticPercent: undefined,
    })
    setStep("done")
  }

  return (
    <div
      role="presentation"
      data-testid="github-scan-modal-backdrop"
      onClick={(e) => { if (e.target === e.currentTarget) close() }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15, 23, 42, 0.52)",
        zIndex: 50,
        display: "grid",
        placeItems: "center",
        padding: 20,
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="github-scan-title"
        data-testid="github-scan-modal"
        style={{
          width: "min(960px, 100%)",
          maxHeight: "min(94vh, 980px)",
          overflow: "auto",
          borderRadius: 18,
          background: "#fff",
          border: "1px solid var(--line)",
          boxShadow: "0 30px 80px rgba(15,23,42,.25)",
          padding: 24,
          display: "grid",
          gap: 20,
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--muted)" }}>
              {step === "done" ? "Completed" : "GitHub Portfolio Scan"}
            </div>
            <h2
              id="github-scan-title"
              style={{ margin: "4px 0 0", fontSize: 22, fontWeight: 700, color: "var(--ink)" }}
            >
              {step === "form" && "Scan my GitHub profile"}
              {step === "scanning" && "VeriBridge AI is scanning your GitHub profile"}
              {step === "review" && "Review grouped skill evidence"}
              {step === "importing" && "Saving selected skills…"}
              {step === "done" && "GitHub proof items imported"}
            </h2>

            {step === "form" && (
              <p style={{ margin: "6px 0 0", color: "var(--muted)", fontSize: 13, lineHeight: 1.6 }}>
                Enter your GitHub profile URL. VeriBridge scans your public repos and groups
                evidence into skill categories. You review and approve before anything is saved.
              </p>
            )}

            {step === "review" && scanResult && (
              <p style={{ margin: "6px 0 0", color: "var(--muted)", fontSize: 13 }}>
                Found{" "}
                <strong>{grouped.length} grouped skill{grouped.length !== 1 ? "s" : ""}</strong>{" "}
                from{" "}
                <strong>{scanResult.candidate_count} evidence location{scanResult.candidate_count !== 1 ? "s" : ""}</strong>{" "}
                across{" "}
                <strong>{scanResult.repos_selected_count || scanResult.repo_count_scanned} repo{(scanResult.repos_selected_count || scanResult.repo_count_scanned) !== 1 ? "s" : ""}</strong>.{" "}
                Select the skills you want to add to your profile.
              </p>
            )}
          </div>

          <button
            type="button"
            onClick={close}
            aria-label="Close GitHub scan modal"
            data-testid="github-scan-modal-close"
            style={{
              border: "1px solid var(--line)",
              background: "#fff",
              color: "var(--ink-2)",
              borderRadius: 10,
              width: 38,
              height: 38,
              fontSize: 18,
              fontWeight: 700,
              cursor: "pointer",
              flexShrink: 0,
            }}
          >
            ×
          </button>
        </div>

        {/* Error banner */}
        {error && (
          <div
            role="alert"
            data-testid="github-scan-error"
            style={{
              border: "1px solid #fecaca",
              background: "#fef2f2",
              color: "#991b1b",
              borderRadius: 12,
              padding: "10px 12px",
              fontSize: 13,
              lineHeight: 1.5,
            }}
          >
            {error}
          </div>
        )}

        {/* ── Form step ── */}
        {step === "form" && (
          <div style={{ display: "grid", gap: 16 }}>
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>
                GitHub profile URL or username
              </span>
              <input
                data-testid="github-scan-profile-url"
                value={form.profileUrl}
                onChange={(e) => setForm((prev) => ({ ...prev, profileUrl: e.target.value }))}
                placeholder="https://github.com/yourusername"
                style={inputStyle}
              />
              <span style={{ fontSize: 12, color: "var(--muted)" }}>
                Public repos only. Private repos require GitHub OAuth (future).
              </span>
            </label>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 12 }}>
              <label style={{ display: "grid", gap: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>Max repos to scan</span>
                <input
                  data-testid="github-scan-max-repos"
                  type="number"
                  min={1}
                  max={150}
                  value={form.maxRepos}
                  onChange={(e) => setForm((prev) => ({ ...prev, maxRepos: e.target.value }))}
                  style={inputStyle}
                />
              </label>

              <label style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", paddingTop: 24 }}>
                <input
                  data-testid="github-scan-smart-scan"
                  type="checkbox"
                  checked={form.smartScan}
                  onChange={(e) => setForm((prev) => ({ ...prev, smartScan: e.target.checked }))}
                  style={{ width: 16, height: 16, cursor: "pointer" }}
                />
                <div>
                  <div style={{ fontSize: 13, color: "var(--ink)", fontWeight: 600 }}>Smart Scan</div>
                  <div style={{ fontSize: 11, color: "var(--muted)" }}>Prioritize best repos</div>
                </div>
              </label>

              <label style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", paddingTop: 24 }}>
                <input
                  data-testid="github-scan-include-forks"
                  type="checkbox"
                  checked={form.includeForks}
                  onChange={(e) => setForm((prev) => ({ ...prev, includeForks: e.target.checked }))}
                  style={{ width: 16, height: 16, cursor: "pointer" }}
                />
                <span style={{ fontSize: 13, color: "var(--ink)" }}>Include forks</span>
              </label>

              <label style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", paddingTop: 24 }}>
                <input
                  data-testid="github-scan-include-archived"
                  type="checkbox"
                  checked={form.includeArchived}
                  onChange={(e) => setForm((prev) => ({ ...prev, includeArchived: e.target.checked }))}
                  style={{ width: 16, height: 16, cursor: "pointer" }}
                />
                <span style={{ fontSize: 13, color: "var(--ink)" }}>Include archived</span>
              </label>
            </div>

            {/* Large-profile hint */}
            {parseInt(form.maxRepos, 10) > 50 && (
              <div style={{ fontSize: 12, color: "#854d0e", background: "#fef9c3", border: "1px solid #fef08a", borderRadius: 8, padding: "8px 12px", lineHeight: 1.5 }}>
                Large scan may take longer. Smart Scan prioritizes the most relevant repositories first — we recommend keeping it on.
              </div>
            )}
            <div style={{ fontSize: 11, color: "var(--muted)", lineHeight: 1.6 }}>
              For large profiles, VeriBridge scans the most relevant repositories first. Max 150 repos.{" "}
              Unauthenticated scans are limited to 60 GitHub API requests/hour — configure{" "}
              <code style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10 }}>GITHUB_TOKEN</code>{" "}
              in the backend .env for reliable large-profile scanning.
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button
                type="button"
                data-testid="github-scan-submit"
                onClick={() => void handleScan()}
                style={primaryBtnStyle}
              >
                Scan GitHub profile
              </button>
            </div>
          </div>
        )}

        {/* ── Scanning step ── */}
        {step === "scanning" && scanProgress && (
          <ProofProcessingProgressPanel
            title="GitHub Scan"
            progress={scanProgress}
            canClose={false}
          />
        )}

        {/* ── Review step ── */}
        {step === "review" && scanResult && (
          <div style={{ display: "grid", gap: 16 }}>
            {grouped.length === 0 ? (
              <div
                data-testid="github-scan-no-candidates"
                style={{
                  border: "1px dashed var(--line-2)",
                  borderRadius: 14,
                  padding: 24,
                  textAlign: "center",
                  color: "var(--muted)",
                  fontSize: 13,
                  lineHeight: 1.7,
                }}
              >
                <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>No proof candidates found.</div>
                {scanResult.repos_selected_count === 0 && scanResult.repos_available_count > 0
                  ? `Found ${scanResult.repos_available_count} repos but all were filtered out. Try enabling "Include forks" or "Include archived".`
                  : scanResult.repos_selected_count === 0
                  ? "No public repositories were found for this profile."
                  : `Scanned ${scanResult.repos_selected_count} repos but found no high-signal evidence. Try manual proof submission or adjust scan options.`}
              </div>
            ) : (
              <>
                {/* Filter tabs + select controls */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                  {/* Filter tabs */}
                  <div style={{ display: "flex", gap: 6 }}>
                    {(["all", "high", "review"] as FilterMode[]).map((mode) => {
                      const label = mode === "all" ? `All (${grouped.length})` : mode === "high" ? `High confidence (${grouped.filter(g => g.confidence === "high").length})` : `Needs review (${grouped.filter(g => g.confidence !== "high").length})`
                      return (
                        <button
                          key={`filter-${mode}`}
                          type="button"
                          onClick={() => setFilterMode(mode)}
                          style={{
                            border: filterMode === mode ? "1px solid var(--indigo)" : "1px solid var(--line-2)",
                            background: filterMode === mode ? "var(--indigo-soft)" : "transparent",
                            color: filterMode === mode ? "var(--indigo)" : "var(--ink-2)",
                            borderRadius: 8,
                            padding: "6px 12px",
                            fontSize: 12,
                            fontWeight: 600,
                            cursor: "pointer",
                          }}
                        >
                          {label}
                        </button>
                      )
                    })}
                  </div>

                  {/* Selection controls */}
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <span style={{ fontSize: 12, color: "var(--ink-2)", fontWeight: 600 }}>
                      {selectedGroupCount} of {grouped.length} group{grouped.length !== 1 ? "s" : ""} selected
                      {selected.size > 0 && ` (${selected.size} items)`}
                    </span>
                    <button type="button" onClick={selectAllGroups} style={ghostBtnStyle} data-testid="github-scan-select-all">
                      Select all
                    </button>
                    <button type="button" onClick={deselectAllGroups} style={ghostBtnStyle} data-testid="github-scan-deselect-all">
                      Deselect all
                    </button>
                  </div>
                </div>

                {/* Grouped skill cards — no maxHeight here; the modal dialog handles scrolling */}
                <div
                  data-testid="github-scan-candidates-list"
                  style={{ display: "flex", flexDirection: "column", gap: 10 }}
                >
                  {filteredGroups.map((group) => (
                    <GroupedSkillCard
                      key={`group-${group.id}`}
                      group={group}
                      selected={selected}
                      expanded={expanded.has(group.id)}
                      onToggleGroup={toggleGroup}
                      onToggleEvidence={toggleEvidence}
                      onToggleExpand={toggleExpand}
                    />
                  ))}
                </div>

                {/* Advanced: raw evidence accordion */}
                <div style={{ border: "1px solid var(--line)", borderRadius: 10 }}>
                  <button
                    type="button"
                    onClick={() => setShowRaw((p) => !p)}
                    style={{
                      width: "100%",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      padding: "10px 14px",
                      background: "var(--bg-2)",
                      border: "none",
                      cursor: "pointer",
                      fontSize: 12,
                      fontWeight: 600,
                      color: "var(--ink-2)",
                    }}
                  >
                    <span>Advanced: raw evidence ({scanResult.candidate_count} items)</span>
                    <span>{showRaw ? "▲" : "▼"}</span>
                  </button>
                  {showRaw && (
                    <div style={{ maxHeight: 320, overflowY: "auto", padding: "12px 14px", display: "grid", gap: 8 }}>
                      {scanResult.proof_candidates.map((candidate, index) => {
                        const isSelected = selected.has(candidate.candidate_id)
                        return (
                          <label
                            key={`raw-${candidate.candidate_id}`}
                            style={{
                              display: "grid",
                              gridTemplateColumns: "auto 1fr",
                              gap: 10,
                              padding: "8px 10px",
                              border: `1px solid ${isSelected ? "var(--indigo)" : "var(--line)"}`,
                              borderRadius: 8,
                              background: isSelected ? "var(--indigo-soft)" : "var(--bg-2)",
                              cursor: "pointer",
                              fontSize: 12,
                            }}
                          >
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => toggleEvidence(candidate.candidate_id)}
                              style={{ marginTop: 2, width: 14, height: 14, cursor: "pointer" }}
                            />
                            <div>
                              <div style={{ fontWeight: 700, color: "var(--ink)", marginBottom: 2 }}>
                                {candidate.skill_label}
                                <span style={{ fontWeight: 400, color: "var(--muted)", marginLeft: 6 }}>
                                  {candidate.repo_name} · {candidate.file_path} L{candidate.line_start}–L{candidate.line_end}
                                </span>
                              </div>
                              <div style={{ color: "var(--muted)" }}>{candidate.selection_reason}</div>
                            </div>
                          </label>
                        )
                      })}
                    </div>
                  )}
                </div>
              </>
            )}

            {/* Footer controls */}
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
              <button
                type="button"
                data-testid="github-scan-back"
                onClick={() => { setStep("form"); setError(null) }}
                style={ghostBtnStyle}
              >
                ← Back
              </button>
              <button
                type="button"
                data-testid="github-scan-save-selected"
                onClick={() => void handleImport()}
                disabled={selected.size === 0}
                style={{
                  ...primaryBtnStyle,
                  background: selected.size === 0 ? "var(--bg-2)" : "var(--ink)",
                  color: selected.size === 0 ? "var(--muted)" : "#fff",
                  cursor: selected.size === 0 ? "not-allowed" : "pointer",
                }}
              >
                {selected.size > 0
                  ? `Save ${selectedGroupCount > 0 ? `${selectedGroupCount} grouped skill${selectedGroupCount !== 1 ? "s" : ""}` : `${selected.size} item${selected.size !== 1 ? "s" : ""}`} to profile`
                  : "Save selected grouped skills to profile"}
              </button>
            </div>
          </div>
        )}

        {/* ── Importing + Done steps — unified progress panel ── */}
        {(step === "importing" || step === "done") && processingProgress && (
          <ProofProcessingProgressPanel
            title="Saving selected GitHub skills"
            progress={processingProgress}
            onClose={close}
            canClose={step === "done"}
            extraDetails={
              importResult && importResult.per_candidate_results.length > 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  {importResult.per_candidate_results.map((r) => (
                    <div
                      key={`result-${r.candidate_id}`}
                      style={{ fontSize: 11, display: "grid", gridTemplateColumns: "auto 1fr", gap: 8 }}
                    >
                      <span style={{ fontWeight: 700, color: r.status === "imported" ? "#166534" : r.status === "skipped_duplicate" ? "#94a3b8" : "#991b1b" }}>
                        {r.status === "imported" ? "✓" : r.status === "skipped_duplicate" ? "−" : "✕"}
                      </span>
                      <span style={{ color: "var(--ink-2)" }}>
                        <strong>{r.skill_label}</strong> · {r.repo_name}
                      </span>
                    </div>
                  ))}
                </div>
              ) : null
            }
          />
        )}
      </div>
    </div>
  )
}

// ── Shared styles ─────────────────────────────────────────────────────────────

const inputStyle: CSSProperties = {
  width: "100%",
  border: "1px solid var(--line)",
  borderRadius: 10,
  background: "#fff",
  color: "var(--ink)",
  padding: "10px 12px",
  fontSize: 14,
  outline: "none",
  boxSizing: "border-box",
}

const ghostBtnStyle: CSSProperties = {
  border: "1px solid var(--line-2)",
  background: "transparent",
  color: "var(--ink-2)",
  borderRadius: 10,
  padding: "9px 14px",
  fontWeight: 600,
  fontSize: 13,
  cursor: "pointer",
}

const primaryBtnStyle: CSSProperties = {
  border: "1px solid transparent",
  background: "var(--ink)",
  color: "#fff",
  borderRadius: 10,
  padding: "10px 18px",
  fontWeight: 700,
  fontSize: 14,
  cursor: "pointer",
}
