"use client"

/**
 * website-ai-analyzer-panel.tsx — Phase J4D / J4E
 * Website AI Analyzer with optional connected GitHub repo.
 * Flow: form → analyze → review → save.
 */

import { useMemo, useState } from "react"
import type { CSSProperties } from "react"
import {
  analyzeWebsite,
  createSkillEvidence,
  generateEvidenceAccessLinks,
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
    makeStep("connect", "Reading website URL",      "Connecting to the public URL.",               "Reading your website URL..."),
    makeStep("fetch",   "Fetching website content",  "Downloading page content and metadata.",      "Fetching website content and metadata..."),
    makeStep("routes",  "Checking API routes",       "Inspecting /docs, /openapi.json, /health.",  "Checking /docs, /openapi.json, and /health..."),
    ...(hasRepo ? [makeStep("repo", "Scanning GitHub repo", "Fetching file tree and scanning code.", "Scanning connected GitHub repository...")] : []),
    makeStep("extract", "Extracting evidence",       "Mapping content to skill categories.",        hasRepo ? "Merging website and repo evidence..." : "Extracting skill evidence..."),
    makeStep("prepare", "Preparing review",          "Organizing evidence candidates.",             "Preparing your review screen..."),
  ]
}

function createWebsiteSaveProgressSteps() {
  return [
    makeStep("prepare",  "Preparing evidence",         "Reading selected candidates.",          "Preparing selected evidence..."),
    makeStep("save",     "Saving proof",               "Creating evidence records.",            "Saving proof 1 of 1..."),
    makeStep("links",    "Generating access links",    "Creating recruiter-accessible links.",  "Generating access links..."),
    makeStep("refresh",  "Updating Skill Proof Center","Reloading saved evidence.",             "Updating your Skill Proof Center..."),
    makeStep("complete", "Complete",                   "All done.",                             "Done."),
  ]
}

// ── Badge/style helpers ───────────────────────────────────────────────────────

const badgeBase: CSSProperties = {
  fontSize: 10, fontWeight: 700, letterSpacing: "0.1em",
  textTransform: "uppercase", padding: "3px 8px", borderRadius: 999,
}

function confidenceStyle(c: string): CSSProperties {
  if (c === "high")   return { background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }
  if (c === "medium") return { background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a" }
  return { background: "#f1f5f9", color: "#475569", border: "1px solid #e2e8f0" }
}

function statusStyle(s: string): CSSProperties {
  return s === "suggested"
    ? { background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" }
    : { background: "#fff7ed", color: "#9a3412", border: "1px solid #fed7aa" }
}

function sourceBadgeStyle(src: WebsiteEvidenceSource): CSSProperties {
  if (src === "combined")    return { background: "#ede9fe", color: "#5b21b6", border: "1px solid #ddd6fe" }
  if (src === "github_repo") return { background: "#f1f5f9", color: "#1e293b", border: "1px solid #e2e8f0" }
  return                            { background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" }
}

function sourceLabel(src: WebsiteEvidenceSource): string {
  if (src === "combined")    return "Combined"
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
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [analyzeProgress, setAnalyzeProgress] = useState<ProofProcessingProgress | null>(null)
  const [saveProgress, setSaveProgress] = useState<ProofProcessingProgress | null>(null)
  const [error, setError] = useState<string | null>(null)

  const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0))

  function toggleCandidate(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const selectedCandidates = useMemo(
    () => analyzeResult?.candidates.filter((c) => selected.has(c.candidate_id)) ?? [],
    [analyzeResult, selected]
  )

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

    const staged = [
      { ms: 0,    msg: "Downloading homepage content and metadata..." },
      { ms: 2000, msg: "Checking /docs (FastAPI/Swagger documentation)..." },
      { ms: 4000, msg: "Checking /openapi.json for API specification..." },
      { ms: 6000, msg: "Checking /health endpoint for monitoring support..." },
      ...(hasRepo ? [
        { ms: 8000,  msg: "Fetching connected GitHub repository file tree..." },
        { ms: 12000, msg: "Scanning code files for skill signals (Dockerfile, API routes, ML code)..." },
        { ms: 18000, msg: "Merging website and GitHub repo evidence..." },
      ] : []),
      { ms: hasRepo ? 22000 : 8000, msg: "Mapping evidence to skill categories..." },
    ]
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
      const maxTime = hasRepo ? 30_000 : 15_000
      const pct = Math.min(75, 20 + ((elapsed / maxTime) * 55))
      prog = { ...prog, syntheticPercent: Math.round(pct) }
      if (changed) setAnalyzeProgress({ ...prog })
      else setAnalyzeProgress((p) => p ? { ...p, syntheticPercent: Math.round(pct) } : p)
    }, 500)

    try {
      const result = await analyzeWebsite({
        url: trimmedUrl,
        skill_focus: skillFocus.trim() || null,
        github_repo_url: trimmedRepo || null,
      })
      clearInterval(interval)

      steps = completeStep(steps, "fetch")
      steps = completeStep(steps, "routes", {
        description: `Checked: ${result.checked_urls.map((u) => { try { return new URL(u).pathname } catch { return u } }).join(", ")}`,
      })
      if (hasRepo) {
        steps = completeStep(steps, "repo", {
          description: result.repo_candidate_count > 0
            ? `Found ${result.repo_candidate_count} GitHub evidence items.`
            : "Repo scanned — see warnings if any.",
        })
      }
      steps = completeStep(steps, "extract", {
        description: `Found ${result.candidate_count} evidence candidate${result.candidate_count !== 1 ? "s" : ""}.`,
        agentCopy: `Found ${result.candidate_count} evidence candidate${result.candidate_count !== 1 ? "s" : ""}.`,
      })
      steps = completeStep(steps, "prepare")

      let finalMsg = `Analysis complete — ${result.candidate_count} evidence candidates.`
      if (result.combined_candidate_count > 0) {
        finalMsg += ` ${result.combined_candidate_count} have combined website + GitHub evidence.`
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

      const autoSelect = new Set(
        result.candidates.filter((c) => c.suggested_status === "suggested").map((c) => c.candidate_id)
      )
      setSelected(autoSelect)
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
    if (selectedCandidates.length === 0) {
      setError("Select at least one evidence candidate to save."); return
    }
    setError(null)

    const total = selectedCandidates.length
    let steps = createWebsiteSaveProgressSteps()
    steps = completeStep(steps, "prepare", { description: `${total} candidate${total !== 1 ? "s" : ""} selected.` })
    steps = startStep(steps, "save")

    let prog = initialProgress(steps)
    prog = appendWorkLogEntry(prog, `Preparing ${total} evidence item${total !== 1 ? "s" : ""}...`)
    setSaveProgress({ ...prog })
    setPanelStep("saving")

    let savedCount = 0, failedCount = 0
    const errMessages: string[] = []

    for (let i = 0; i < selectedCandidates.length; i++) {
      const candidate = selectedCandidates[i]
      const itemNum = i + 1
      const label = `${candidate.skill_name} — ${sourceLabel(candidate.evidence_source)}`

      steps = updateStep(steps, "save", {
        countCurrent: itemNum, countTotal: total,
        agentCopy: `Saving ${label} (${itemNum} of ${total})...`,
        description: `Saving item ${itemNum} of ${total}...`,
      })
      prog = appendWorkLogEntry(
        { ...prog, steps, syntheticPercent: Math.round(10 + (i / total) * 60) },
        `Saving ${itemNum} of ${total} — ${label}`
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
        prog = appendWorkLogEntry({ ...prog, steps }, `Failed — ${label} — continuing`, "error")
      }

      setSaveProgress({ ...prog })
    }

    const finalMsg = `Done — saved ${savedCount} · failed ${failedCount}`
    steps = completeStep(steps, "save", { description: `Saved ${savedCount} · Failed ${failedCount}`, agentCopy: `Saved ${savedCount} evidence items.` })
    steps = completeStep(steps, "links")
    prog = appendWorkLogEntry({ ...prog, steps }, "Updating your Skill Proof Center...")
    onSaveComplete?.()
    steps = completeStep(steps, "refresh")
    steps = completeStep(steps, "complete", { description: finalMsg, agentCopy: finalMsg })
    prog = appendWorkLogEntry({ ...prog, steps }, finalMsg, "completed")

    setSaveProgress({ ...prog, steps, overallStatus: failedCount === total && savedCount === 0 ? "failed" : "completed", savedCount, failedCount, errorMessages: errMessages, syntheticPercent: undefined })
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
            <div style={{ fontSize: 15, fontWeight: 700, color: "var(--ink)", marginBottom: 4 }}>🌐 Website / Portfolio AI Analysis</div>
            <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.6 }}>
              Enter a live URL. VeriBridge fetches the page, checks /docs and /openapi.json, and extracts skill evidence for review.
              Optionally connect a GitHub repo to prove backend, ML, and deployment skills behind the site.
            </div>
          </div>

          {/* Website URL */}
          <div style={{ display: "grid", gap: 4 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>Website URL *</span>
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://your-app.run.app or https://your-portfolio.vercel.app" style={inp} />
            <span style={{ fontSize: 11, color: "var(--muted)" }}>Only public URLs. Private or localhost URLs are not supported.</span>
          </div>

          {/* Skill focus */}
          <div style={{ display: "grid", gap: 4 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>Skill focus <span style={{ fontWeight: 400, color: "var(--muted)" }}>(optional)</span></span>
            <input value={skillFocus} onChange={(e) => setSkillFocus(e.target.value)} placeholder="e.g. FastAPI, Machine Learning, Cloud Deployment, Computer Vision" style={inp} />
            <span style={{ fontSize: 11, color: "var(--muted)" }}>Comma-separated skills to prioritize during analysis.</span>
          </div>

          {/* GitHub repo URL (J4E) */}
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
              Connecting the repo helps VeriBridge prove backend, ML, deployment, and MLOps skills behind the live website —
              Dockerfiles, GitHub Actions, model files, API routes, README architecture.
            </span>
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
            <button type="button" onClick={onBack} style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "9px 14px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>← Back</button>
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
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "var(--ink)", marginBottom: 4 }}>
              Review website evidence suggestions
            </div>
            {/* Source coverage summary (J4E) */}
            <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.6 }}>
              Found <strong style={{ color: "var(--ink-2)" }}>{analyzeResult.candidate_count}</strong> evidence candidate{analyzeResult.candidate_count !== 1 ? "s" : ""}.
              {analyzeResult.website_candidate_count > 0 && ` Website: ${analyzeResult.website_candidate_count}.`}
              {analyzeResult.repo_candidate_count > 0 && ` GitHub repo: ${analyzeResult.repo_candidate_count}.`}
              {analyzeResult.combined_candidate_count > 0 && (
                <span style={{ color: "#5b21b6", fontWeight: 600 }}> {analyzeResult.combined_candidate_count} skill{analyzeResult.combined_candidate_count !== 1 ? "s" : ""} have evidence from both sources.</span>
              )}
            </div>
          </div>

          {/* Source legend */}
          {analyzeResult.github_repo_url && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", fontSize: 11, color: "var(--muted)" }}>
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{ ...badgeBase, ...sourceBadgeStyle("combined"), fontSize: 9 }}>Combined</span> website + GitHub repo
              </span>
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{ ...badgeBase, ...sourceBadgeStyle("website"), fontSize: 9 }}>Website</span> website only
              </span>
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{ ...badgeBase, ...sourceBadgeStyle("github_repo"), fontSize: 9 }}>GitHub</span> repo only
              </span>
            </div>
          )}

          {/* Warnings */}
          {analyzeResult.warnings.length > 0 && (
            <div style={{ background: "#fef9c3", border: "1px solid #fef08a", borderRadius: 8, padding: "8px 12px", fontSize: 12, color: "#854d0e", lineHeight: 1.5 }}>
              {analyzeResult.warnings.map((w, i) => <div key={`w-${i}`}>{w}</div>)}
            </div>
          )}

          {/* Candidates */}
          {analyzeResult.candidates.length === 0 ? (
            <div style={{ border: "1px dashed var(--line-2)", borderRadius: 12, padding: 20, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>
              <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>No evidence candidates found.</div>
              <div style={{ marginBottom: 12 }}>The website responded but no strong skill signals were detected automatically.</div>
              <button type="button" onClick={() => void (async () => {
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
              })()} style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "9px 16px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>
                Save as manual website proof
              </button>
            </div>
          ) : (
            <>
              {/* Select controls */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                <span style={{ fontSize: 12, color: "var(--ink-2)", fontWeight: 600 }}>{selected.size} of {analyzeResult.candidates.length} selected</span>
                <div style={{ display: "flex", gap: 8 }}>
                  <button type="button" onClick={() => setSelected(new Set(analyzeResult.candidates.map((c) => c.candidate_id)))} style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 8, padding: "6px 12px", fontWeight: 600, fontSize: 12, cursor: "pointer" }}>Select all</button>
                  <button type="button" onClick={() => setSelected(new Set())} style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 8, padding: "6px 12px", fontWeight: 600, fontSize: 12, cursor: "pointer" }}>Deselect all</button>
                </div>
              </div>

              {/* Candidate cards */}
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {analyzeResult.candidates.map((candidate) => {
                  const isSelected = selected.has(candidate.candidate_id)
                  return (
                    <label
                      key={`wac-${candidate.candidate_id}`}
                      style={{
                        display: "grid", gridTemplateColumns: "auto 1fr", gap: 12, padding: "12px 14px",
                        border: `1px solid ${isSelected ? "var(--indigo)" : candidate.is_combined ? "#ddd6fe" : "var(--line)"}`,
                        borderRadius: 12, background: isSelected ? "var(--indigo-soft)" : candidate.is_combined ? "#faf5ff" : "#fff",
                        cursor: "pointer",
                      }}
                    >
                      <input type="checkbox" checked={isSelected} onChange={() => toggleCandidate(candidate.candidate_id)} style={{ marginTop: 3, width: 15, height: 15, cursor: "pointer" }} />
                      <div style={{ display: "grid", gap: 6 }}>
                        {/* Title + badges row */}
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8, flexWrap: "wrap" }}>
                          <div>
                            <div style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>{candidate.skill_name}</div>
                            <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>{candidate.evidence_title}</div>
                          </div>
                          <div style={{ display: "flex", gap: 5, flexShrink: 0, flexWrap: "wrap" }}>
                            <span style={{ ...badgeBase, ...sourceBadgeStyle(candidate.evidence_source), fontSize: 9 }}>
                              {sourceLabel(candidate.evidence_source)}
                            </span>
                            <span style={{ ...badgeBase, fontSize: 9, background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" }}>
                              {candidate.skill_category}
                            </span>
                            <span style={{ ...badgeBase, ...confidenceStyle(candidate.confidence), fontSize: 9 }}>{candidate.confidence}</span>
                            <span style={{ ...badgeBase, ...statusStyle(candidate.suggested_status), fontSize: 9 }}>
                              {candidate.suggested_status === "suggested" ? "Auto" : "Review"}
                            </span>
                          </div>
                        </div>
                        {/* Summary */}
                        <div style={{ fontSize: 12, color: "var(--ink-2)", lineHeight: 1.5 }}>{candidate.evidence_summary}</div>
                        {/* Route / file path */}
                        <div style={{ fontSize: 11, color: "var(--muted)", fontFamily: "'JetBrains Mono', monospace" }}>
                          {candidate.route_path}
                          {candidate.evidence_snippet && (
                            <span style={{ marginLeft: 8, fontFamily: "inherit", fontStyle: "italic" }}>
                              — &ldquo;{candidate.evidence_snippet.slice(0, 80)}&rdquo;
                            </span>
                          )}
                        </div>
                        {/* Action link */}
                        <a href={candidate.source_url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} style={{ fontSize: 11, fontWeight: 600, color: "var(--indigo)", textDecoration: "none" }}>
                          {candidate.action_label} →
                        </a>
                      </div>
                    </label>
                  )
                })}
              </div>

              {/* Footer */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                <button type="button" onClick={() => setPanelStep("form")} style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "9px 14px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>← Back</button>
                <button type="button" disabled={selected.size === 0} onClick={() => void handleSave()} style={{ border: "none", background: selected.size === 0 ? "var(--bg-2)" : "var(--ink)", color: selected.size === 0 ? "var(--muted)" : "#fff", borderRadius: 10, padding: "10px 18px", fontWeight: 700, fontSize: 14, cursor: selected.size === 0 ? "not-allowed" : "pointer" }}>
                  Save {selected.size > 0 ? `${selected.size} evidence item${selected.size !== 1 ? "s" : ""}` : "selected"} to profile
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Saving progress ── */}
      {panelStep === "saving" && saveProgress && (
        <ProofProcessingProgressPanel title="Saving website evidence" progress={saveProgress} canClose={false} />
      )}

      {/* ── Done ── */}
      {panelStep === "done" && saveProgress && (
        <ProofProcessingProgressPanel title="Website evidence saved" progress={saveProgress} onClose={onBack} canClose />
      )}
    </div>
  )
}
