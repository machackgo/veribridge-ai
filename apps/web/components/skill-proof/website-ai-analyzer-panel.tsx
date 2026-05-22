"use client"

/**
 * website-ai-analyzer-panel.tsx — Phase J4D / J4E / J4F / J4G
 * Website AI Analyzer with optional GitHub repo, functional verification,
 * and high-level grouped skill review.
 * Flow: form → analyzing → review (grouped) → saving → done.
 */

import { useMemo, useState } from "react"
import type { CSSProperties } from "react"
import {
  analyzeWebsite,
  createSkillEvidence,
  generateEvidenceAccessLinks,
  type FunctionalVerificationCandidate,
  type GroupedWebsiteSkill,
  type WebsiteAnalysisCandidate,
  type WebsiteAnalyzeResponse,
  type WebsiteEvidenceSource,
} from "@/lib/api"
import {
  appendWorkLogEntry,
  completeStep,
  failStep,
  initialProgress,
  makeStep,
  startStep,
  updateStep,
  type ProofProcessingProgress,
} from "@/lib/proof-processing"
import { ProofProcessingProgressPanel } from "./proof-processing-progress-panel"

// ── Step presets ──────────────────────────────────────────────────────────────

function createWebsiteAnalyzeProgressSteps(hasRepo: boolean) {
  return [
    makeStep("connect",  "Reading website URL",          "Connecting to the public URL.",                             "Reading your website URL..."),
    makeStep("fetch",    "Fetching website content",      "Downloading page content, metadata, and API spec.",         "Fetching website content and metadata..."),
    makeStep("routes",   "Checking API routes",           "Inspecting /docs, /openapi.json, /health.",                 "Checking /docs, /openapi.json, and /health..."),
    ...(hasRepo ? [makeStep("repo", "Scanning GitHub repo", "Fetching file tree and scanning code files.", "Scanning connected GitHub repository...")] : []),
    makeStep("verify",   "Running functional tests",      "Safely calling inference endpoints to verify live output.", "Testing safe API endpoints with example data..."),
    makeStep("extract",  "Extracting evidence",           "Mapping all evidence to skill categories.",                  hasRepo ? "Merging website, repo, and functional evidence..." : "Extracting skill evidence..."),
    makeStep("group",    "Grouping into skill cards",     "Organizing evidence into high-level skill groups.",          "Building grouped skill review..."),
    makeStep("prepare",  "Preparing review screen",       "Rendering skill system graphs and evidence cards.",          "Preparing your grouped review screen..."),
  ]
}

function createWebsiteSaveProgressSteps() {
  return [
    makeStep("prepare",  "Preparing evidence",         "Reading selected candidates.",          "Preparing selected evidence..."),
    makeStep("save",     "Saving proof",               "Creating evidence records.",            "Saving proof..."),
    makeStep("links",    "Generating access links",    "Creating recruiter-accessible links.",  "Generating access links..."),
    makeStep("refresh",  "Updating Skill Proof Center","Reloading saved evidence.",             "Updating your Skill Proof Center..."),
    makeStep("complete", "Complete",                   "All done.",                             "Done."),
  ]
}

// ── Badge / style helpers ─────────────────────────────────────────────────────

const badgeBase: CSSProperties = {
  fontSize: 10, fontWeight: 700, letterSpacing: "0.08em",
  textTransform: "uppercase", padding: "3px 8px", borderRadius: 999,
  display: "inline-block",
}

function confidenceStyle(c: string): CSSProperties {
  if (c === "high")   return { background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }
  if (c === "medium") return { background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a" }
  return { background: "#f1f5f9", color: "#475569", border: "1px solid #e2e8f0" }
}

function sourceBadgeStyle(src: WebsiteEvidenceSource): CSSProperties {
  if (src === "combined")    return { background: "#ede9fe", color: "#5b21b6", border: "1px solid #ddd6fe" }
  if (src === "functional")  return { background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }
  if (src === "github_repo") return { background: "#f1f5f9", color: "#1e293b", border: "1px solid #e2e8f0" }
  return                            { background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" }
}

function sourceLabel(src: WebsiteEvidenceSource): string {
  if (src === "combined")    return "Combined"
  if (src === "functional")  return "Verified Workflow"
  if (src === "github_repo") return "GitHub"
  return "Website"
}

const inp: CSSProperties = {
  width: "100%", border: "1px solid var(--line)", borderRadius: 10,
  background: "#fff", color: "var(--ink)", padding: "9px 12px",
  fontSize: 13, outline: "none", boxSizing: "border-box",
}

// ── GitHub repo URL parser ────────────────────────────────────────────────────

function parseGitHubRepoUrl(url: string): { owner: string; repo: string } | null {
  const m = url.trim().match(/^(?:https?:\/\/)?github\.com\/([a-zA-Z0-9_-]+)\/([a-zA-Z0-9_.\-]+?)\/?$/)
  return m ? { owner: m[1], repo: m[2].replace(/\.git$/, "") } : null
}

// ── System graph component ────────────────────────────────────────────────────

function SystemGraph({ nodes }: { nodes: string[] }) {
  return (
    <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 6, padding: "8px 0" }}>
      {nodes.map((node, i) => (
        <span key={`sgn-${i}`} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{
            background: "#f8fafc", border: "1px solid #cbd5e1", borderRadius: 8,
            padding: "4px 10px", fontSize: 11, fontWeight: 600, color: "#334155",
            whiteSpace: "nowrap",
          }}>
            {node}
          </span>
          {i < nodes.length - 1 && (
            <span style={{ color: "#94a3b8", fontSize: 13, fontWeight: 700 }}>→</span>
          )}
        </span>
      ))}
    </div>
  )
}

// ── Functional verification row ───────────────────────────────────────────────

function FunctionalRow({ fc }: { fc: FunctionalVerificationCandidate }) {
  const { verified, status_code, evidence_title, verification_message, response_fields_found, method, endpoint_url } = fc
  const bg = verified ? "#f0fdf4" : status_code && status_code < 500 ? "#fef9c3" : "#fff7ed"
  const border = verified ? "#bbf7d0" : status_code && status_code < 500 ? "#fef08a" : "#fed7aa"
  const badge = verified
    ? { label: "LIVE TEST PASSED", bg: "#dcfce7", color: "#166534", border: "#bbf7d0" }
    : status_code
    ? { label: `HTTP ${status_code}`, bg: "#fef9c3", color: "#854d0e", border: "#fef08a" }
    : { label: "UNAVAILABLE",      bg: "#f1f5f9", color: "#475569", border: "#e2e8f0" }

  return (
    <div style={{ background: bg, border: `1px solid ${border}`, borderRadius: 8, padding: "10px 12px", marginBottom: 6 }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <span style={{ fontSize: 16, lineHeight: 1.4 }}>{verified ? "✓" : "⚠"}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 3 }}>
            <span style={{ fontWeight: 700, fontSize: 13, color: "var(--ink)" }}>{evidence_title}</span>
            <span style={{ ...badgeBase, fontSize: 9, background: badge.bg, color: badge.color, border: `1px solid ${badge.border}` }}>
              {badge.label}
            </span>
          </div>
          <div style={{ fontSize: 12, color: "var(--ink-2)", lineHeight: 1.5, marginBottom: 4 }}>{verification_message}</div>
          {verified && response_fields_found.length > 0 && (
            <div style={{ fontSize: 11, color: "#166534" }}>
              Response fields: <span style={{ fontFamily: "monospace" }}>{response_fields_found.slice(0, 8).join(", ")}</span>
            </div>
          )}
          <div style={{ display: "flex", gap: 12, marginTop: 6 }}>
            <span style={{ fontSize: 10, fontWeight: 700, color: "var(--muted)", fontFamily: "monospace" }}>
              {method} {endpoint_url}
            </span>
            <a href={endpoint_url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 10, color: "var(--indigo)", fontWeight: 600, textDecoration: "none" }}>
              Open endpoint →
            </a>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Atomic evidence row ───────────────────────────────────────────────────────

function AtomicRow({ c }: { c: WebsiteAnalysisCandidate }) {
  return (
    <div style={{ padding: "8px 10px", borderRadius: 8, border: "1px solid #f1f5f9", background: "#fafafa", marginBottom: 4 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink)" }}>{c.evidence_title}</div>
          <div style={{ fontSize: 11, color: "var(--ink-2)", marginTop: 2, lineHeight: 1.4 }}>
            {c.evidence_summary.slice(0, 140)}{c.evidence_summary.length > 140 ? "…" : ""}
          </div>
          <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 3, fontFamily: "monospace" }}>
            {c.route_path}
          </div>
        </div>
        <a href={c.source_url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 10, color: "var(--indigo)", fontWeight: 600, textDecoration: "none", whiteSpace: "nowrap", flexShrink: 0 }}>
          {c.action_label} →
        </a>
      </div>
    </div>
  )
}

// ── Grouped skill card ────────────────────────────────────────────────────────

function GroupedSkillCard({
  group,
  isSelected,
  onToggle,
  atomicById,
  functionalById,
}: {
  group: GroupedWebsiteSkill
  isSelected: boolean
  onToggle: () => void
  atomicById: Map<string, WebsiteAnalysisCandidate>
  functionalById: Map<string, FunctionalVerificationCandidate>
}) {
  const [expanded, setExpanded] = useState(false)

  const allAtomicInGroup = group.candidate_ids
    .filter((id) => atomicById.has(id))
    .map((id) => atomicById.get(id)!)

  const websiteItems = allAtomicInGroup.filter((c) => c.evidence_source === "website")
  const repoItems    = allAtomicInGroup.filter((c) => c.evidence_source === "github_repo")
  const combinedItems = allAtomicInGroup.filter((c) => c.evidence_source === "combined")
  const functionalItems = group.functional_candidate_ids
    .filter((id) => functionalById.has(id))
    .map((id) => functionalById.get(id)!)

  const hasFunctionalPassed = functionalItems.some((fc) => fc.verified)
  const border = isSelected ? "#6366f1" : hasFunctionalPassed ? "#bbf7d0" : "var(--line)"
  const bgHeader = isSelected ? "#f5f3ff" : "#fff"

  return (
    <div style={{
      border: `1px solid ${border}`,
      borderRadius: 14,
      overflow: "hidden",
      transition: "border-color 0.15s",
    }}>
      {/* ── Card header ── */}
      <div style={{
        display: "grid", gridTemplateColumns: "auto 1fr auto",
        gap: 12, padding: "14px 16px", background: bgHeader,
        cursor: "pointer",
      }} onClick={onToggle}>
        <input
          type="checkbox"
          checked={isSelected}
          onChange={onToggle}
          onClick={(e) => e.stopPropagation()}
          style={{ marginTop: 3, width: 15, height: 15, cursor: "pointer", flexShrink: 0 }}
        />

        <div>
          <div style={{ fontWeight: 700, fontSize: 14, color: "var(--ink)" }}>{group.skill_name}</div>

          {/* Source badges */}
          <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 5 }}>
            {group.sources.map((src) => (
              <span key={src} style={{ ...badgeBase, ...sourceBadgeStyle(src), fontSize: 9 }}>
                {sourceLabel(src)}
              </span>
            ))}
            <span style={{ ...badgeBase, ...confidenceStyle(group.confidence), fontSize: 9 }}>
              {group.confidence}
            </span>
            {hasFunctionalPassed && (
              <span style={{ ...badgeBase, fontSize: 9, background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }}>
                Live Test Passed
              </span>
            )}
          </div>

          {/* Subskill chips */}
          {group.subskills.length > 0 && (
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 7 }}>
              {group.subskills.slice(0, 6).map((sk) => (
                <span key={sk} style={{
                  fontSize: 10, background: "#f1f5f9", color: "#475569",
                  border: "1px solid #e2e8f0", borderRadius: 999, padding: "2px 8px",
                }}>
                  {sk}
                </span>
              ))}
              {group.subskills.length > 6 && (
                <span style={{ fontSize: 10, color: "var(--muted)", padding: "2px 4px" }}>
                  +{group.subskills.length - 6} more
                </span>
              )}
            </div>
          )}

          {/* Evidence count summary */}
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 6, display: "flex", gap: 10 }}>
            {group.website_count > 0 && <span>{group.website_count} website</span>}
            {group.repo_count > 0 && <span>{group.repo_count} GitHub</span>}
            {group.combined_count > 0 && <span style={{ color: "#5b21b6" }}>{group.combined_count} combined</span>}
            {group.functional_count > 0 && <span style={{ color: "#166534" }}>{group.functional_count} functional</span>}
          </div>
        </div>

        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setExpanded((v) => !v) }}
          style={{
            border: "1px solid var(--line-2)", background: "transparent",
            color: "var(--ink-2)", borderRadius: 8, padding: "5px 10px",
            fontWeight: 600, fontSize: 11, cursor: "pointer", alignSelf: "flex-start", whiteSpace: "nowrap",
          }}
        >
          {expanded ? "Collapse ↑" : "Expand ↓"}
        </button>
      </div>

      {/* ── Expanded content ── */}
      {expanded && (
        <div style={{ borderTop: "1px solid #f1f5f9", padding: "14px 16px", background: "#fafafa" }}>

          {/* System graph */}
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: "var(--muted)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>
              Skill System Graph
            </div>
            <SystemGraph nodes={group.system_graph_nodes} />
          </div>

          {/* Functional verification */}
          {functionalItems.length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#166534", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>
                Functional Verification
              </div>
              {functionalItems.map((fc) => (
                <FunctionalRow key={fc.candidate_id} fc={fc} />
              ))}
            </div>
          )}

          {/* Combined evidence */}
          {combinedItems.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#5b21b6", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>
                Combined Evidence (Website + GitHub)
              </div>
              {combinedItems.map((c) => <AtomicRow key={c.candidate_id} c={c} />)}
            </div>
          )}

          {/* Website evidence */}
          {websiteItems.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#1d4ed8", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>
                Website Evidence
              </div>
              {websiteItems.map((c) => <AtomicRow key={c.candidate_id} c={c} />)}
            </div>
          )}

          {/* GitHub evidence */}
          {repoItems.length > 0 && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#1e293b", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>
                GitHub Evidence
              </div>
              {repoItems.map((c) => <AtomicRow key={c.candidate_id} c={c} />)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

type PanelStep = "form" | "analyzing" | "review" | "saving" | "done"

export function WebsiteAIAnalyzerPanel({
  initialUrl = "",
  initialSkillFocus = "",
  onSaveComplete,
  onBack,
}: {
  initialUrl?: string
  initialSkillFocus?: string
  onSaveComplete?: () => void
  onBack: () => void
}) {
  const [panelStep, setPanelStep] = useState<PanelStep>("form")
  const [url, setUrl] = useState(initialUrl)
  const [skillFocus, setSkillFocus] = useState(initialSkillFocus)
  const [githubRepoUrl, setGithubRepoUrl] = useState("")
  const [analyzeResult, setAnalyzeResult] = useState<WebsiteAnalyzeResponse | null>(null)
  const [selectedGroupIds, setSelectedGroupIds] = useState<Set<string>>(new Set())
  const [showAtomicAccordion, setShowAtomicAccordion] = useState(false)
  const [analyzeProgress, setAnalyzeProgress] = useState<ProofProcessingProgress | null>(null)
  const [saveProgress, setSaveProgress] = useState<ProofProcessingProgress | null>(null)
  const [error, setError] = useState<string | null>(null)

  const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0))

  // Quick-lookup maps by candidate_id
  const atomicById = useMemo(
    () => new Map((analyzeResult?.candidates ?? []).map((c) => [c.candidate_id, c])),
    [analyzeResult]
  )
  const functionalById = useMemo(
    () => new Map((analyzeResult?.functional_candidates ?? []).map((c) => [c.candidate_id, c])),
    [analyzeResult]
  )

  function toggleGroup(groupId: string) {
    setSelectedGroupIds((prev) => {
      const next = new Set(prev)
      if (next.has(groupId)) next.delete(groupId)
      else next.add(groupId)
      return next
    })
  }

  // Total unique candidate IDs across selected groups
  const totalSelectedCandidateIds = useMemo(() => {
    const ids = new Set<string>()
    for (const gid of selectedGroupIds) {
      const group = analyzeResult?.grouped_skills.find((g) => g.group_id === gid)
      if (group) group.candidate_ids.forEach((id) => ids.add(id))
    }
    return ids
  }, [selectedGroupIds, analyzeResult])

  // ── Analyze ────────────────────────────────────────────────────────────────

  async function handleAnalyze() {
    setError(null)
    const trimmedUrl = url.trim()
    if (!trimmedUrl) { setError("Enter a website URL."); return }
    if (!trimmedUrl.startsWith("http://") && !trimmedUrl.startsWith("https://")) {
      setError("URL must start with https:// or http://"); return
    }
    const trimmedRepo = githubRepoUrl.trim()
    if (trimmedRepo && !parseGitHubRepoUrl(trimmedRepo)) {
      setError("GitHub repo URL must be: https://github.com/owner/repo"); return
    }

    const hasRepo = Boolean(trimmedRepo)
    let steps = createWebsiteAnalyzeProgressSteps(hasRepo)
    steps = completeStep(steps, "connect", { agentCopy: `Connecting to ${trimmedUrl}...` })
    steps = startStep(steps, "fetch")

    let prog = initialProgress(steps)
    prog = appendWorkLogEntry(prog, `Reading ${trimmedUrl}...`)
    if (hasRepo) prog = appendWorkLogEntry(prog, `Connected GitHub repo: ${trimmedRepo}`)
    setAnalyzeProgress({ ...prog })
    setPanelStep("analyzing")

    // Staged work log messages timed to approximate server phases
    const staged = [
      { ms: 0,    msg: "Downloading homepage content and metadata..." },
      { ms: 2000, msg: "Checking /docs for FastAPI/Swagger documentation..." },
      { ms: 4000, msg: "Checking /openapi.json for API specification..." },
      { ms: 6000, msg: "Checking /health endpoint..." },
      ...(hasRepo ? [
        { ms: 8000,  msg: "Fetching connected GitHub repository file tree..." },
        { ms: 12000, msg: "Scanning code files (Dockerfile, API routes, ML models, cloud config)..." },
        { ms: 18000, msg: "Merging website and GitHub repo evidence..." },
      ] : []),
      { ms: hasRepo ? 22000 : 8000,  msg: "Parsing OpenAPI spec to find safe testable endpoints..." },
      { ms: hasRepo ? 25000 : 11000, msg: "Preparing safe test request for /predict endpoint..." },
      { ms: hasRepo ? 27000 : 13000, msg: "Calling /predict with example data (safe inference test)..." },
      { ms: hasRepo ? 29000 : 15000, msg: "Verifying response — checking status code and expected fields..." },
      { ms: hasRepo ? 31000 : 17000, msg: "Grouping evidence into high-level skill categories..." },
      { ms: hasRepo ? 33000 : 19000, msg: "Building skill system graphs for each group..." },
      { ms: hasRepo ? 35000 : 21000, msg: "Preparing grouped review screen..." },
    ]

    const maxTime = hasRepo ? 50_000 : 35_000
    const t0 = Date.now()
    let si = 0
    const interval = setInterval(() => {
      const elapsed = Date.now() - t0
      let changed = false
      while (si < staged.length && elapsed >= staged[si].ms) {
        prog = appendWorkLogEntry(prog, staged[si].msg)
        si++
        changed = true
      }
      const pct = Math.min(78, 15 + ((elapsed / maxTime) * 63))
      prog = { ...prog, syntheticPercent: Math.round(pct) }
      if (changed) setAnalyzeProgress({ ...prog })
      else setAnalyzeProgress((p) => p ? { ...p, syntheticPercent: Math.round(pct) } : p)
    }, 500)

    try {
      const result = await analyzeWebsite({
        url: trimmedUrl,
        skill_focus: skillFocus.trim() || null,
        github_repo_url: trimmedRepo || null,
        run_safe_tests: true,
      })
      clearInterval(interval)

      // Complete all analysis steps
      steps = completeStep(steps, "fetch")
      steps = completeStep(steps, "routes", {
        description: `Checked: ${result.checked_urls.map((u) => { try { return new URL(u).pathname || "/" } catch { return u } }).join(", ")}`,
      })
      if (hasRepo) {
        steps = completeStep(steps, "repo", {
          description: result.repo_candidate_count > 0
            ? `Found ${result.repo_candidate_count} GitHub evidence item${result.repo_candidate_count !== 1 ? "s" : ""}.`
            : "Repo scanned — see warnings if any.",
        })
      }
      steps = completeStep(steps, "verify", {
        description: result.functional_verification_available
          ? `${result.functional_candidate_count} functional verification result${result.functional_candidate_count !== 1 ? "s" : ""}.`
          : "Functional verification completed — see warnings.",
      })
      steps = completeStep(steps, "extract", {
        description: `Found ${result.candidate_count} evidence item${result.candidate_count !== 1 ? "s" : ""}.`,
        agentCopy: `Found ${result.candidate_count} evidence item${result.candidate_count !== 1 ? "s" : ""}.`,
      })
      steps = completeStep(steps, "group", {
        description: `Grouped into ${result.grouped_skills.length} high-level skill${result.grouped_skills.length !== 1 ? "s" : ""}.`,
        agentCopy: `${result.grouped_skills.length} grouped skill${result.grouped_skills.length !== 1 ? "s" : ""} ready for review.`,
      })
      steps = completeStep(steps, "prepare")

      let finalMsg = `Analysis complete — ${result.grouped_skills.length} grouped skill${result.grouped_skills.length !== 1 ? "s" : ""}, ${result.candidate_count} evidence item${result.candidate_count !== 1 ? "s" : ""}.`
      if (result.functional_verification_available) {
        const passed = result.functional_candidates.filter((fc) => fc.verified).length
        finalMsg += passed > 0
          ? ` ${passed} functional test${passed !== 1 ? "s" : ""} passed.`
          : ` Functional verification completed.`
      }
      if (result.combined_candidate_count > 0) {
        finalMsg += ` ${result.combined_candidate_count} skill${result.combined_candidate_count !== 1 ? "s" : ""} have combined website + GitHub evidence.`
      }
      prog = appendWorkLogEntry(prog, finalMsg, "completed")
      for (const w of result.warnings) {
        prog = appendWorkLogEntry(prog, w, "warning")
      }

      setAnalyzeProgress({
        ...prog, steps, overallStatus: "completed",
        savedCount: result.candidate_count, syntheticPercent: undefined,
      })
      setAnalyzeResult(result)

      // Auto-select all groups with suggested status
      const autoSelect = new Set(
        result.grouped_skills.filter((g) => g.suggested_status === "suggested").map((g) => g.group_id)
      )
      setSelectedGroupIds(autoSelect)
      setPanelStep("review")
    } catch (err) {
      clearInterval(interval)
      const msg = err instanceof Error ? err.message : "Analysis failed."
      steps = failStep(steps, "fetch", msg)
      prog = appendWorkLogEntry(prog, msg, "error")
      setAnalyzeProgress({ ...prog, steps, overallStatus: "failed", errorMessages: [msg], syntheticPercent: undefined })
      setError(msg)
      setPanelStep("form")
    }
  }

  // ── Save ────────────────────────────────────────────────────────────────────

  async function handleSave() {
    if (selectedGroupIds.size === 0) {
      setError("Select at least one skill group to save."); return
    }
    setError(null)

    // Collect all unique candidates from selected groups
    const seenIds = new Set<string>()
    const atomicToSave: WebsiteAnalysisCandidate[] = []
    const functionalToSave: FunctionalVerificationCandidate[] = []

    for (const gid of selectedGroupIds) {
      const group = analyzeResult?.grouped_skills.find((g) => g.group_id === gid)
      if (!group) continue
      for (const cid of group.candidate_ids) {
        if (seenIds.has(cid)) continue
        seenIds.add(cid)
        const atomic = atomicById.get(cid)
        if (atomic) { atomicToSave.push(atomic); continue }
        const functional = functionalById.get(cid)
        if (functional) functionalToSave.push(functional)
      }
    }

    const total = atomicToSave.length + functionalToSave.length
    if (total === 0) { setError("No evidence items found in selected groups."); return }

    let steps = createWebsiteSaveProgressSteps()
    steps = completeStep(steps, "prepare", {
      description: `${selectedGroupIds.size} group${selectedGroupIds.size !== 1 ? "s" : ""} selected — ${total} evidence item${total !== 1 ? "s" : ""}.`
    })
    steps = startStep(steps, "save")

    let prog = initialProgress(steps)
    prog = appendWorkLogEntry(prog, `Preparing ${total} evidence item${total !== 1 ? "s" : ""} from ${selectedGroupIds.size} skill group${selectedGroupIds.size !== 1 ? "s" : ""}...`)
    setSaveProgress({ ...prog })
    setPanelStep("saving")

    let savedCount = 0, failedCount = 0
    const errMessages: string[] = []
    let itemIndex = 0

    // Save atomic candidates
    for (const candidate of atomicToSave) {
      itemIndex++
      const label = `${candidate.skill_name} — ${sourceLabel(candidate.evidence_source)}`
      steps = updateStep(steps, "save", {
        countCurrent: itemIndex, countTotal: total,
        agentCopy: `Saving ${label} (${itemIndex} of ${total})...`,
      })
      prog = appendWorkLogEntry(
        { ...prog, steps, syntheticPercent: Math.round(10 + (itemIndex / total) * 60) },
        `Saving ${itemIndex} of ${total} — ${label}`
      )
      setSaveProgress({ ...prog })
      await tick()

      try {
        const evidenceType = candidate.evidence_source === "github_repo" ? "github repository" : "deployed_website"
        const ev = await createSkillEvidence({
          skill_name: candidate.skill_name,
          evidence_type: evidenceType,
          evidence_url: candidate.source_url,
          evidence_description: candidate.evidence_summary,
          proof_visibility: "public",
          metadata: {
            evidence_title: candidate.evidence_title,
            submission_source: "website_ai_analyzer",
            proof_kind: "website_ai_analysis",
            skill_category: candidate.skill_category,
            route_path: candidate.route_path,
            evidence_type_detail: candidate.evidence_type,
            action_label: candidate.action_label,
            evidence_snippet: candidate.evidence_snippet,
            evidence_source: candidate.evidence_source,
            is_combined: candidate.is_combined,
            related_source_url: candidate.related_source_url ?? null,
            base_url: analyzeResult?.base_url ?? candidate.source_url,
            github_repo_url: analyzeResult?.github_repo_url ?? null,
          },
        })
        try { await generateEvidenceAccessLinks(ev.id) } catch { /* best-effort */ }
        savedCount++
        prog = appendWorkLogEntry({ ...prog, steps }, `Saved — ${label}`, "completed")
      } catch (err) {
        failedCount++
        const msg = err instanceof Error ? err.message : "Unknown error"
        errMessages.push(`${label}: ${msg}`)
        prog = appendWorkLogEntry({ ...prog, steps }, `Failed — ${label}`, "error")
      }
      setSaveProgress({ ...prog })
    }

    // Save functional verification candidates
    for (const fc of functionalToSave) {
      itemIndex++
      const label = `${fc.skill_name} — Functional Verification`
      steps = updateStep(steps, "save", {
        countCurrent: itemIndex, countTotal: total,
        agentCopy: `Saving ${label} (${itemIndex} of ${total})...`,
      })
      prog = appendWorkLogEntry(
        { ...prog, steps, syntheticPercent: Math.round(10 + (itemIndex / total) * 60) },
        `Saving ${itemIndex} of ${total} — ${label}`
      )
      setSaveProgress({ ...prog })
      await tick()

      try {
        const ev = await createSkillEvidence({
          skill_name: fc.skill_name,
          evidence_type: "deployed_website",
          evidence_url: fc.endpoint_url,
          evidence_description: fc.verification_message,
          proof_visibility: "public",
          metadata: {
            evidence_title: fc.evidence_title,
            submission_source: "website_ai_analyzer_functional",
            proof_kind: "functional_verification",
            skill_category: fc.skill_category,
            endpoint_url: fc.endpoint_url,
            method: fc.method,
            request_summary: fc.request_summary,
            response_fields_found: fc.response_fields_found,
            status_code: fc.status_code,
            verified: fc.verified,
            verification_badge: fc.verified ? "Live Test Passed" : "Endpoint Detected",
            base_url: analyzeResult?.base_url ?? fc.endpoint_url,
            github_repo_url: analyzeResult?.github_repo_url ?? null,
          },
        })
        try { await generateEvidenceAccessLinks(ev.id) } catch { /* best-effort */ }
        savedCount++
        prog = appendWorkLogEntry({ ...prog, steps }, `Saved — ${label}`, "completed")
      } catch (err) {
        failedCount++
        const msg = err instanceof Error ? err.message : "Unknown error"
        errMessages.push(`${label}: ${msg}`)
        prog = appendWorkLogEntry({ ...prog, steps }, `Failed — ${label}`, "error")
      }
      setSaveProgress({ ...prog })
    }

    const finalMsg = `Done — saved ${savedCount} · failed ${failedCount}`
    steps = completeStep(steps, "save", { description: `Saved ${savedCount} · Failed ${failedCount}`, agentCopy: `Saved ${savedCount} evidence item${savedCount !== 1 ? "s" : ""}.` })
    steps = completeStep(steps, "links")
    prog = appendWorkLogEntry({ ...prog, steps }, "Updating your Skill Proof Center...")
    onSaveComplete?.()
    steps = completeStep(steps, "refresh")
    steps = completeStep(steps, "complete", { description: finalMsg, agentCopy: finalMsg })
    prog = appendWorkLogEntry({ ...prog, steps }, finalMsg, "completed")

    setSaveProgress({
      ...prog, steps,
      overallStatus: failedCount === total && savedCount === 0 ? "failed" : "completed",
      savedCount, failedCount, errorMessages: errMessages, syntheticPercent: undefined,
    })
    setPanelStep("done")
  }

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      {error && (
        <div role="alert" style={{ border: "1px solid #fecaca", background: "#fef2f2", color: "#991b1b", borderRadius: 10, padding: "8px 12px", fontSize: 12 }}>
          {error}
        </div>
      )}

      {/* ── Form ── */}
      {panelStep === "form" && (
        <div style={{ display: "grid", gap: 14 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "var(--ink)", marginBottom: 4 }}>
              🌐 Website / Portfolio AI Analysis
            </div>
            <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.6 }}>
              Enter a live URL. VeriBridge fetches the page, checks /docs and /openapi.json, runs safe functional
              tests on inference endpoints, and groups all evidence into high-level skill cards.
              Optionally connect a GitHub repo to prove backend, ML, and deployment skills behind the site.
            </div>
          </div>

          <div style={{ display: "grid", gap: 4 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>Website URL *</span>
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://your-app.run.app or https://your-portfolio.vercel.app"
              style={inp}
            />
            <span style={{ fontSize: 11, color: "var(--muted)" }}>Only public URLs. Private or localhost URLs are not supported.</span>
          </div>

          <div style={{ display: "grid", gap: 4 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>
              Skill focus <span style={{ fontWeight: 400, color: "var(--muted)" }}>(optional)</span>
            </span>
            <input
              value={skillFocus}
              onChange={(e) => setSkillFocus(e.target.value)}
              placeholder="e.g. FastAPI, Machine Learning, Cloud Deployment, Computer Vision"
              style={inp}
            />
            <span style={{ fontSize: 11, color: "var(--muted)" }}>Comma-separated skills to prioritize during analysis.</span>
          </div>

          <div style={{ display: "grid", gap: 4 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>
              Related GitHub repository <span style={{ fontWeight: 400, color: "var(--muted)" }}>(optional but recommended)</span>
            </span>
            <input
              value={githubRepoUrl}
              onChange={(e) => setGithubRepoUrl(e.target.value)}
              placeholder="https://github.com/your-username/your-repo"
              style={inp}
            />
            <span style={{ fontSize: 11, color: "var(--muted)", lineHeight: 1.5 }}>
              Connecting the repo helps VeriBridge prove backend, ML, deployment, and MLOps skills —
              Dockerfiles, GitHub Actions, model files, API routes, README architecture.
            </span>
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
            <button type="button" onClick={onBack} style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "9px 14px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>
              ← Back
            </button>
            <button type="button" onClick={() => void handleAnalyze()} style={{ border: "none", background: "var(--ink)", color: "#fff", borderRadius: 10, padding: "10px 18px", fontWeight: 700, fontSize: 14, cursor: "pointer" }}>
              Analyze Website with AI
            </button>
          </div>
        </div>
      )}

      {/* ── Analyzing progress ── */}
      {panelStep === "analyzing" && analyzeProgress && (
        <ProofProcessingProgressPanel title="Website AI Analysis" progress={analyzeProgress} canClose={false} />
      )}

      {/* ── Review ── */}
      {panelStep === "review" && analyzeResult && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

          {/* Header */}
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "var(--ink)", marginBottom: 4 }}>
              Review grouped skill evidence
            </div>
            <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.7 }}>
              Found <strong style={{ color: "var(--ink-2)" }}>{analyzeResult.grouped_skills.length}</strong> grouped skill{analyzeResult.grouped_skills.length !== 1 ? "s" : ""} from {analyzeResult.candidate_count} evidence item{analyzeResult.candidate_count !== 1 ? "s" : ""}.
              {analyzeResult.functional_verification_available && (() => {
                const passed = analyzeResult.functional_candidates.filter((fc) => fc.verified).length
                return passed > 0
                  ? <span style={{ color: "#166534", fontWeight: 600 }}> {passed} functional test{passed !== 1 ? "s" : ""} passed.</span>
                  : <span style={{ color: "var(--muted)" }}> Functional verification ran.</span>
              })()}
              {analyzeResult.combined_candidate_count > 0 && (
                <span style={{ color: "#5b21b6", fontWeight: 600 }}> {analyzeResult.combined_candidate_count} skill{analyzeResult.combined_candidate_count !== 1 ? "s" : ""} have combined website + GitHub evidence.</span>
              )}
            </div>
          </div>

          {/* Source legend */}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", fontSize: 11, color: "var(--muted)" }}>
            <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ ...badgeBase, ...sourceBadgeStyle("functional"), fontSize: 9 }}>Verified Workflow</span> live endpoint tested
            </span>
            <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ ...badgeBase, ...sourceBadgeStyle("combined"), fontSize: 9 }}>Combined</span> website + GitHub
            </span>
            <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ ...badgeBase, ...sourceBadgeStyle("website"), fontSize: 9 }}>Website</span> website only
            </span>
            {analyzeResult.github_repo_url && (
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{ ...badgeBase, ...sourceBadgeStyle("github_repo"), fontSize: 9 }}>GitHub</span> repo only
              </span>
            )}
          </div>

          {/* Warnings */}
          {analyzeResult.warnings.length > 0 && (
            <div style={{ background: "#fef9c3", border: "1px solid #fef08a", borderRadius: 8, padding: "8px 12px", fontSize: 12, color: "#854d0e", lineHeight: 1.5 }}>
              {analyzeResult.warnings.map((w, i) => <div key={`w-${i}`}>{w}</div>)}
            </div>
          )}

          {/* No groups fallback */}
          {analyzeResult.grouped_skills.length === 0 ? (
            <div style={{ border: "1px dashed var(--line-2)", borderRadius: 12, padding: 20, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>
              <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>No evidence candidates found.</div>
              <div style={{ marginBottom: 12 }}>The website responded but no strong skill signals were detected automatically.</div>
              <button
                type="button"
                onClick={() => void (async () => {
                  setError(null)
                  let steps = createWebsiteSaveProgressSteps()
                  steps = completeStep(steps, "prepare")
                  steps = startStep(steps, "save")
                  let prog = initialProgress(steps)
                  prog = appendWorkLogEntry(prog, "Saving website link as manual proof...")
                  setSaveProgress({ ...prog })
                  setPanelStep("saving")
                  try {
                    const ev = await createSkillEvidence({
                      skill_name: skillFocus.trim() || "Web Development",
                      evidence_type: "deployed_website",
                      evidence_url: analyzeResult.base_url,
                      evidence_description: `Live website at ${analyzeResult.base_url}. Skill focus: ${skillFocus || "general web development"}.`,
                      proof_visibility: "public",
                      metadata: {
                        evidence_title: `Live website — ${analyzeResult.base_url}`,
                        submission_source: "website_ai_analyzer_fallback",
                        proof_kind: "website_ai_analysis",
                      },
                    })
                    try { await generateEvidenceAccessLinks(ev.id) } catch { /* best-effort */ }
                    onSaveComplete?.()
                    steps = completeStep(steps, "save")
                    steps = completeStep(steps, "links")
                    steps = completeStep(steps, "refresh")
                    steps = completeStep(steps, "complete", { description: "Website link saved as manual proof." })
                    prog = appendWorkLogEntry({ ...prog, steps }, "Website link saved as manual proof.", "completed")
                    setSaveProgress({ ...prog, steps, overallStatus: "completed", savedCount: 1 })
                    setPanelStep("done")
                  } catch (err) {
                    setError(err instanceof Error ? err.message : "Save failed.")
                    setPanelStep("review")
                  }
                })()}
                style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "9px 16px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}
              >
                Save as manual website proof
              </button>
            </div>
          ) : (
            <>
              {/* Group selection controls */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                <span style={{ fontSize: 12, color: "var(--ink-2)", fontWeight: 600 }}>
                  {selectedGroupIds.size} of {analyzeResult.grouped_skills.length} skill group{analyzeResult.grouped_skills.length !== 1 ? "s" : ""} selected
                  {totalSelectedCandidateIds.size > 0 && (
                    <span style={{ fontWeight: 400, color: "var(--muted)" }}> ({totalSelectedCandidateIds.size} evidence item{totalSelectedCandidateIds.size !== 1 ? "s" : ""})</span>
                  )}
                </span>
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    type="button"
                    onClick={() => setSelectedGroupIds(new Set(analyzeResult.grouped_skills.map((g) => g.group_id)))}
                    style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 8, padding: "6px 12px", fontWeight: 600, fontSize: 12, cursor: "pointer" }}
                  >
                    Select all
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelectedGroupIds(new Set())}
                    style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 8, padding: "6px 12px", fontWeight: 600, fontSize: 12, cursor: "pointer" }}
                  >
                    Deselect all
                  </button>
                </div>
              </div>

              {/* Grouped skill cards */}
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {analyzeResult.grouped_skills.map((group) => (
                  <GroupedSkillCard
                    key={group.group_id}
                    group={group}
                    isSelected={selectedGroupIds.has(group.group_id)}
                    onToggle={() => toggleGroup(group.group_id)}
                    atomicById={atomicById}
                    functionalById={functionalById}
                  />
                ))}
              </div>

              {/* Atomic evidence accordion (debug) */}
              <div style={{ border: "1px solid var(--line)", borderRadius: 10, overflow: "hidden" }}>
                <button
                  type="button"
                  onClick={() => setShowAtomicAccordion((v) => !v)}
                  style={{
                    width: "100%", textAlign: "left", padding: "10px 14px",
                    border: "none", background: "#f8fafc", cursor: "pointer",
                    fontSize: 12, fontWeight: 600, color: "var(--ink-2)",
                    display: "flex", justifyContent: "space-between", alignItems: "center",
                  }}
                >
                  <span>Show all raw evidence ({analyzeResult.candidates.length} atomic item{analyzeResult.candidates.length !== 1 ? "s" : ""})</span>
                  <span>{showAtomicAccordion ? "↑" : "↓"}</span>
                </button>
                {showAtomicAccordion && (
                  <div style={{ padding: "10px 14px", display: "flex", flexDirection: "column", gap: 6, maxHeight: 360, overflowY: "auto" }}>
                    {analyzeResult.candidates.map((c) => (
                      <div key={c.candidate_id} style={{
                        padding: "8px 10px", borderRadius: 8,
                        border: `1px solid ${c.is_combined ? "#ddd6fe" : "var(--line)"}`,
                        background: c.is_combined ? "#faf5ff" : "#fff",
                        fontSize: 12,
                      }}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                          <span style={{ fontWeight: 600, color: "var(--ink)" }}>{c.skill_name}</span>
                          <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                            <span style={{ ...badgeBase, ...sourceBadgeStyle(c.evidence_source), fontSize: 9 }}>{sourceLabel(c.evidence_source)}</span>
                            <span style={{ ...badgeBase, ...confidenceStyle(c.confidence), fontSize: 9 }}>{c.confidence}</span>
                          </div>
                        </div>
                        <div style={{ color: "var(--muted)", marginTop: 2, fontFamily: "monospace", fontSize: 10 }}>{c.route_path}</div>
                      </div>
                    ))}
                    {analyzeResult.functional_candidates.length > 0 && (
                      <>
                        <div style={{ fontSize: 11, fontWeight: 700, color: "#166534", marginTop: 6 }}>Functional verification candidates</div>
                        {analyzeResult.functional_candidates.map((fc) => (
                          <div key={fc.candidate_id} style={{
                            padding: "8px 10px", borderRadius: 8,
                            border: "1px solid #bbf7d0", background: "#f0fdf4", fontSize: 12,
                          }}>
                            <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                              <span style={{ fontWeight: 600, color: "var(--ink)" }}>{fc.skill_name}</span>
                              <span style={{ ...badgeBase, fontSize: 9, background: fc.verified ? "#dcfce7" : "#fef9c3", color: fc.verified ? "#166534" : "#854d0e", border: `1px solid ${fc.verified ? "#bbf7d0" : "#fef08a"}` }}>
                                {fc.verified ? "Live Test Passed" : fc.status_code ? `HTTP ${fc.status_code}` : "Unavailable"}
                              </span>
                            </div>
                            <div style={{ color: "var(--muted)", marginTop: 2, fontFamily: "monospace", fontSize: 10 }}>{fc.method} {fc.endpoint_url}</div>
                          </div>
                        ))}
                      </>
                    )}
                  </div>
                )}
              </div>

              {/* Footer */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                <button type="button" onClick={() => setPanelStep("form")} style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "9px 14px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>
                  ← Back
                </button>
                <button
                  type="button"
                  disabled={selectedGroupIds.size === 0}
                  onClick={() => void handleSave()}
                  style={{
                    border: "none",
                    background: selectedGroupIds.size === 0 ? "var(--bg-2)" : "var(--ink)",
                    color: selectedGroupIds.size === 0 ? "var(--muted)" : "#fff",
                    borderRadius: 10, padding: "10px 18px", fontWeight: 700, fontSize: 14,
                    cursor: selectedGroupIds.size === 0 ? "not-allowed" : "pointer",
                  }}
                >
                  {selectedGroupIds.size > 0
                    ? `Save ${selectedGroupIds.size} grouped skill${selectedGroupIds.size !== 1 ? "s" : ""} to profile`
                    : "Select skills to save"}
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Saving progress ── */}
      {panelStep === "saving" && saveProgress && (
        <ProofProcessingProgressPanel title="Saving grouped skill evidence" progress={saveProgress} canClose={false} />
      )}

      {/* ── Done ── */}
      {panelStep === "done" && saveProgress && (
        <ProofProcessingProgressPanel title="Grouped skill evidence saved" progress={saveProgress} onClose={onBack} canClose />
      )}
    </div>
  )
}
