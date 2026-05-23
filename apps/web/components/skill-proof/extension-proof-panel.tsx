"use client"

/**
 * extension-proof-panel.tsx
 * Private Website Proof with VeriBridge Extension — Phase 1C
 *
 * Flow:
 *   form → creating → session_active (recording → uploaded → analyzing → complete)
 *
 * The panel manages all its own state. The parent only needs to supply
 * onBack and onSessionComplete callbacks.
 */

import { useEffect, useState } from "react"
import type { CSSProperties } from "react"
import {
  analyzeExtensionProofGitHub,
  createExtensionProofSession,
  createSkillEvidence,
  getExtensionProofSession,
  startExtensionProofSession,
  type ExtensionProofGitHubAnalysisResponse,
  type ExtensionProofSessionResponse,
  type ExtensionProofSessionStatus,
} from "@/lib/api"

// ── Types ─────────────────────────────────────────────────────────────────────

type PanelStep = "form" | "session_active"

type FormState = {
  websiteUrl: string
  githubUrl: string
  skillName: string
  proofObjective: string
}

// ── Constants & helpers ───────────────────────────────────────────────────────

const POLLING_STATUSES: ExtensionProofSessionStatus[] = [
  "recording",
  "uploaded_pending_analysis",
  "analyzing",
]

const inp: CSSProperties = {
  width: "100%",
  border: "1px solid var(--line)",
  borderRadius: 10,
  background: "#fff",
  color: "var(--ink)",
  padding: "9px 12px",
  fontSize: 13,
  outline: "none",
  boxSizing: "border-box",
}

function isHttpUrl(v: string): boolean {
  const t = v.trim()
  return t.startsWith("http://") || t.startsWith("https://")
}

function wordCount(s: string): number {
  return s.trim().match(/\S+/g)?.length ?? 0
}

// ── Status badge ──────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<
  ExtensionProofSessionStatus,
  { bg: string; color: string; border: string; label: string }
> = {
  created:                   { bg: "#f1f5f9", color: "#475569", border: "#e2e8f0", label: "CREATED" },
  waiting_for_extension:     { bg: "#fef9c3", color: "#854d0e", border: "#fef08a", label: "WAITING" },
  recording:                 { bg: "#dcfce7", color: "#166534", border: "#bbf7d0", label: "RECORDING" },
  uploaded_pending_analysis: { bg: "#dbeafe", color: "#1d4ed8", border: "#bfdbfe", label: "UPLOADED" },
  analyzing:                 { bg: "#ede9fe", color: "#5b21b6", border: "#ddd6fe", label: "ANALYZING" },
  completed:                 { bg: "#dcfce7", color: "#166534", border: "#bbf7d0", label: "COMPLETE" },
  expired:                   { bg: "#fef2f2", color: "#991b1b", border: "#fecaca", label: "EXPIRED" },
}

function StatusBadge({ status }: { status: ExtensionProofSessionStatus }) {
  const c = STATUS_CONFIG[status] ?? STATUS_CONFIG.created
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.08em",
        padding: "3px 9px",
        borderRadius: 999,
        background: c.bg,
        color: c.color,
        border: `1px solid ${c.border}`,
        flexShrink: 0,
      }}
    >
      {c.label}
    </span>
  )
}

// ── Session stepper ───────────────────────────────────────────────────────────

const STEPPER_STEPS: Array<{ label: string; statuses: ExtensionProofSessionStatus[] }> = [
  { label: "Session Created", statuses: ["created", "waiting_for_extension"] },
  { label: "Recording",       statuses: ["recording"] },
  { label: "Proof Uploaded",  statuses: ["uploaded_pending_analysis"] },
  { label: "Analyzing",       statuses: ["analyzing"] },
  { label: "Complete",        statuses: ["completed"] },
]

function stepperIndex(status: ExtensionProofSessionStatus): number {
  return STEPPER_STEPS.findIndex(s => (s.statuses as string[]).includes(status))
}

function SessionStepper({ status }: { status: ExtensionProofSessionStatus }) {
  const currentIdx = stepperIndex(status)

  return (
    <div style={{ padding: "4px 0 8px" }}>
      <div style={{ display: "flex", alignItems: "flex-start" }}>
        {STEPPER_STEPS.map((step, i) => {
          const isDone    = i < currentIdx
          const isCurrent = i === currentIdx

          const circleSize = 28
          const circleBg =
            isDone    ? "#065f46" :
            isCurrent ? "#1d4ed8" :
            "#fff"
          const circleBorder =
            isDone || isCurrent ? "none" : "2px solid #cbd5e1"
          const circleShadow =
            isCurrent ? "0 0 0 4px #dbeafe" : "none"
          const circleColor =
            isDone || isCurrent ? "#fff" : "#94a3b8"
          const circleContent = isDone ? "✓" : String(i + 1)
          const circleFontSize = isDone ? 13 : 11

          const labelColor =
            isCurrent ? "#1d4ed8" :
            isDone    ? "#334155" :
            "#94a3b8"
          const labelWeight = isCurrent ? 700 : isDone ? 500 : 400

          return (
            <div
              key={step.label}
              style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center" }}
            >
              {/* Left arm + circle + right arm */}
              <div style={{ display: "flex", alignItems: "center", width: "100%" }}>
                <div
                  style={{
                    flex: 1,
                    height: 2,
                    background: i === 0 ? "transparent" : isDone ? "#065f46" : "#e2e8f0",
                  }}
                />
                <div
                  style={{
                    width: circleSize,
                    height: circleSize,
                    borderRadius: "50%",
                    flexShrink: 0,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    background: circleBg,
                    border: circleBorder,
                    boxShadow: circleShadow,
                    color: circleColor,
                    fontSize: circleFontSize,
                    fontWeight: 700,
                  }}
                >
                  {circleContent}
                </div>
                <div
                  style={{
                    flex: 1,
                    height: 2,
                    background:
                      i === STEPPER_STEPS.length - 1
                        ? "transparent"
                        : isDone ? "#065f46" : "#e2e8f0",
                  }}
                />
              </div>

              {/* Label */}
              <div
                style={{
                  marginTop: 8,
                  fontSize: 11,
                  fontWeight: labelWeight,
                  color: labelColor,
                  textAlign: "center",
                  lineHeight: 1.35,
                  paddingInline: 4,
                }}
              >
                {step.label}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Status-aware message card ─────────────────────────────────────────────────

function StatusMessage({
  status,
  pollingActive,
}: {
  status: ExtensionProofSessionStatus
  pollingActive: boolean
}) {
  if (status === "created" || status === "waiting_for_extension") {
    return (
      <div
        style={{
          border: "1px solid #e2e8f0",
          borderRadius: 12,
          background: "#f8fafc",
          padding: "14px 16px",
          display: "grid",
          gap: 4,
        }}
      >
        <div style={{ fontSize: 13, fontWeight: 700, color: "#334155" }}>
          Proof session created
        </div>
        <p style={{ margin: 0, fontSize: 12, color: "#64748b", lineHeight: 1.65 }}>
          Proof session created. Start your demo when ready.
        </p>
      </div>
    )
  }

  if (status === "recording") {
    return (
      <div
        style={{
          border: "1px solid #d1fae5",
          borderRadius: 12,
          background: "#f0fdf4",
          padding: "14px 16px",
          display: "grid",
          gap: 8,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              flexShrink: 0,
              background: "#16a34a",
            }}
          />
          <span style={{ fontSize: 13, fontWeight: 700, color: "#065f46" }}>
            VeriBridge Extension is recording
          </span>
        </div>
        <p style={{ margin: 0, fontSize: 12, color: "#064e3b", lineHeight: 1.7 }}>
          A floating VeriBridge recorder bar will appear on your website while recording. Use
          it to stop and send proof without switching tabs. You can also use{" "}
          <strong>Stop &amp; Send Proof</strong> in the extension popup as a fallback. This
          page will update automatically when your proof is received.
        </p>
        {pollingActive && (
          <p style={{ margin: 0, fontSize: 11, color: "#16a34a" }}>
            Listening for proof upload…
          </p>
        )}
      </div>
    )
  }

  if (status === "uploaded_pending_analysis") {
    return (
      <div
        style={{
          border: "1px solid #bfdbfe",
          borderRadius: 12,
          background: "#eff6ff",
          padding: "14px 16px",
          display: "grid",
          gap: 8,
        }}
      >
        <div style={{ fontSize: 13, fontWeight: 700, color: "#1e40af" }}>
          ✓ Proof uploaded successfully
        </div>
        <p style={{ margin: 0, fontSize: 12, color: "#1e3a8a", lineHeight: 1.7 }}>
          Your workflow proof has been received. Next, VeriBridge will analyze your recorded
          workflow, GitHub repository, and website evidence.
        </p>
        {pollingActive && (
          <p style={{ margin: 0, fontSize: 11, color: "#2563eb" }}>
            Waiting for analysis to begin…
          </p>
        )}
      </div>
    )
  }

  if (status === "analyzing") {
    return (
      <div
        style={{
          border: "1px solid #ddd6fe",
          borderRadius: 12,
          background: "#faf5ff",
          padding: "14px 16px",
          display: "grid",
          gap: 8,
        }}
      >
        <div style={{ fontSize: 13, fontWeight: 700, color: "#5b21b6" }}>
          Verification analysis in progress
        </div>
        <p style={{ margin: 0, fontSize: 12, color: "#4c1d95", lineHeight: 1.7 }}>
          VeriBridge is comparing your GitHub repo, website, and workflow proof.
        </p>
        {pollingActive && (
          <p style={{ margin: 0, fontSize: 11, color: "#7c3aed" }}>
            Analysis running…
          </p>
        )}
      </div>
    )
  }

  if (status === "completed") {
    return (
      <div
        style={{
          border: "1px solid #d1fae5",
          borderRadius: 12,
          background: "#f0fdf4",
          padding: "14px 16px",
          display: "grid",
          gap: 6,
        }}
      >
        <div style={{ fontSize: 13, fontWeight: 700, color: "#065f46" }}>
          ✓ Proof submitted — analysis complete
        </div>
        <p style={{ margin: 0, fontSize: 12, color: "#064e3b", lineHeight: 1.5 }}>
          Your proof walkthrough has been analyzed. Check your Skill Proof Center for the result.
        </p>
      </div>
    )
  }

  return null
}

// ── GitHub Analysis result card ───────────────────────────────────────────────

function GitHubAnalysisCard({
  analysis,
  onReanalyze,
  reanalyzing,
}: {
  analysis: ExtensionProofGitHubAnalysisResponse
  onReanalyze: () => void
  reanalyzing: boolean
}) {
  const isSuccess = analysis.status === "success"
  const isPrivate = analysis.status === "private_or_unavailable"
  const confidencePct = Math.round(analysis.confidence_score * 100)

  const headerBg    = isSuccess ? "#f0fdf4" : isPrivate ? "#fef9c3" : "#fef2f2"
  const headerBorder= isSuccess ? "#d1fae5" : isPrivate ? "#fde68a" : "#fecaca"
  const headerColor = isSuccess ? "#065f46" : isPrivate ? "#78350f" : "#991b1b"
  const headerLabel = isSuccess ? "✓ Analysis complete" : isPrivate ? "⚠ Repo unavailable" : "✗ Analysis failed"

  return (
    <div
      style={{
        border: "1px solid var(--line)",
        borderRadius: 12,
        background: "#fff",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          background: headerBg,
          borderBottom: `1px solid ${headerBorder}`,
          padding: "12px 16px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 700, color: headerColor }}>
          {headerLabel}
        </span>
        <button
          type="button"
          onClick={onReanalyze}
          disabled={reanalyzing}
          style={{
            border: "1px solid var(--line-2)",
            background: "transparent",
            color: "var(--ink-2)",
            borderRadius: 8,
            padding: "4px 10px",
            fontSize: 11,
            fontWeight: 600,
            cursor: reanalyzing ? "not-allowed" : "pointer",
            opacity: reanalyzing ? 0.5 : 1,
          }}
        >
          {reanalyzing ? "Re-analyzing…" : "Re-analyze"}
        </button>
      </div>

      <div style={{ padding: "14px 16px", display: "grid", gap: 14 }}>
        {/* Confidence */}
        {isSuccess && (
          <div style={{ display: "grid", gap: 6 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: "var(--ink-2)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                Confidence
              </span>
              <span style={{ fontSize: 13, fontWeight: 700, color: confidencePct >= 60 ? "#065f46" : confidencePct >= 35 ? "#92400e" : "#991b1b" }}>
                {confidencePct}%
              </span>
            </div>
            <div style={{ height: 6, background: "#f1f5f9", borderRadius: 999, overflow: "hidden" }}>
              <div
                style={{
                  height: "100%",
                  width: `${confidencePct}%`,
                  background: confidencePct >= 60 ? "#16a34a" : confidencePct >= 35 ? "#d97706" : "#dc2626",
                  borderRadius: 999,
                  transition: "width 0.4s ease",
                }}
              />
            </div>
          </div>
        )}

        {/* Detected stack */}
        {analysis.detected_stack.length > 0 && (
          <div style={{ display: "grid", gap: 6 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: "var(--ink-2)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Detected Stack
            </span>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
              {analysis.detected_stack.map((tech) => (
                <span
                  key={tech}
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    padding: "3px 9px",
                    borderRadius: 999,
                    background: "#f1f5f9",
                    color: "#334155",
                    border: "1px solid #e2e8f0",
                  }}
                >
                  {tech}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Skill match */}
        {(analysis.matched_claimed_skills.length > 0 || analysis.missing_claimed_skills.length > 0) && (
          <div style={{ display: "grid", gap: 6 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: "var(--ink-2)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Skill Match
            </span>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
              {analysis.matched_claimed_skills.map((s) => (
                <span key={s} style={{ fontSize: 11, fontWeight: 600, padding: "3px 9px", borderRadius: 999, background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }}>
                  ✓ {s}
                </span>
              ))}
              {analysis.missing_claimed_skills.map((s) => (
                <span key={s} style={{ fontSize: 11, fontWeight: 600, padding: "3px 9px", borderRadius: 999, background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca" }}>
                  ✗ {s}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Recruiter summary */}
        {analysis.recruiter_summary && (
          <div style={{ display: "grid", gap: 6 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: "var(--ink-2)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Recruiter Summary
            </span>
            <p style={{ margin: 0, fontSize: 12, color: "var(--ink-2)", lineHeight: 1.65 }}>
              {analysis.recruiter_summary}
            </p>
          </div>
        )}

        {/* Warnings */}
        {analysis.warnings.length > 0 && (
          <div style={{ display: "grid", gap: 4 }}>
            {analysis.warnings.map((w, i) => (
              <p key={i} style={{ margin: 0, fontSize: 11, color: "#92400e", lineHeight: 1.55 }}>
                ⚠ {w}
              </p>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function ExtensionProofPanel({
  onBack,
  onSessionComplete,
}: {
  onBack: () => void
  onSessionComplete?: () => void
}) {
  const [step, setStep]               = useState<PanelStep>("form")
  const [form, setForm]               = useState<FormState>({ websiteUrl: "", githubUrl: "", skillName: "", proofObjective: "" })
  const [session, setSession]         = useState<ExtensionProofSessionResponse | null>(null)
  const [error, setError]             = useState<string | null>(null)
  const [creating, setCreating]       = useState(false)
  const [starting, setStarting]       = useState(false)
  const [pollingActive, setPoll]      = useState(false)
  const [githubAnalysis, setGithubAnalysis] = useState<ExtensionProofGitHubAnalysisResponse | null>(null)
  const [analyzingGitHub, setAnalyzingGitHub] = useState(false)
  const [githubAnalysisError, setGithubAnalysisError] = useState<string | null>(null)

  // ── Polling ───────────────────────────────────────────────────────────────

  useEffect(() => {
    if (!pollingActive || !session) return
    if (!POLLING_STATUSES.includes(session.status)) {
      setPoll(false)
      return
    }
    const t = setTimeout(async () => {
      try {
        const updated = await getExtensionProofSession(session.id)
        setSession(updated)
        if (updated.status === "completed") {
          setPoll(false)
          onSessionComplete?.()
        } else if (updated.status === "expired") {
          setPoll(false)
        }
      } catch { /* transient network error — next tick will retry */ }
    }, 3000)
    return () => clearTimeout(t)
  }, [pollingActive, session, onSessionComplete])

  // ── Create session ────────────────────────────────────────────────────────

  async function handleCreate() {
    setError(null)

    if (!isHttpUrl(form.websiteUrl)) {
      setError("Enter a valid website URL starting with http:// or https://.")
      return
    }
    if (!form.skillName.trim()) {
      setError("Enter the skill this walkthrough demonstrates.")
      return
    }
    if (wordCount(form.proofObjective) < 5) {
      setError("Describe what this walkthrough proves (at least 5 words).")
      return
    }

    setCreating(true)
    try {
      // Create a skill evidence record as the anchor for this session
      const evidence = await createSkillEvidence({
        skill_name:           form.skillName.trim(),
        evidence_type:        "private website (extension proof)",
        evidence_url:         form.websiteUrl.trim(),
        repository_url:       form.githubUrl.trim() || null,
        evidence_description: form.proofObjective.trim(),
        metadata: {
          proof_kind:         "extension_proof",
          submission_source:  "student_extension_proof_flow",
        },
      })
      const sess = await createExtensionProofSession(evidence.id)
      setSession(sess)
      setStep("session_active")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create proof session.")
    } finally {
      setCreating(false)
    }
  }

  // ── Start session ─────────────────────────────────────────────────────────

  async function handleStart() {
    if (!session) return
    setStarting(true)
    setError(null)
    try {
      const updated = await startExtensionProofSession(session.id)
      setSession(updated)

      // Open the website in a new tab with session ID injected as a query param.
      // URL.searchParams.set preserves all existing params and adds/overwrites only ours.
      const targetUrl = form.websiteUrl.trim()
      try {
        const url = new URL(targetUrl)
        url.searchParams.set("veribridge_session_id", session.id)
        window.open(url.toString(), "_blank", "noopener,noreferrer")
      } catch {
        // Fallback: URL couldn't be parsed (shouldn't happen after isHttpUrl validation),
        // append the param manually so session detection still works.
        const sep = targetUrl.includes("?") ? "&" : "?"
        window.open(
          `${targetUrl}${sep}veribridge_session_id=${encodeURIComponent(session.id)}`,
          "_blank",
          "noopener,noreferrer"
        )
      }

      setPoll(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start proof session.")
    } finally {
      setStarting(false)
    }
  }

  // ── Analyze GitHub ────────────────────────────────────────────────────────

  async function handleAnalyzeGitHub() {
    if (!session || !form.githubUrl.trim()) return
    setAnalyzingGitHub(true)
    setGithubAnalysisError(null)
    try {
      const claimedSkills = form.skillName.trim()
        ? form.skillName.split(",").map((s) => s.trim()).filter(Boolean)
        : []
      const result = await analyzeExtensionProofGitHub(session.id, form.githubUrl.trim(), claimedSkills)
      setGithubAnalysis(result)
    } catch (err) {
      setGithubAnalysisError(err instanceof Error ? err.message : "GitHub analysis failed.")
    } finally {
      setAnalyzingGitHub(false)
    }
  }

  // ── Render: form ─────────────────────────────────────────────────────────

  if (step === "form") {
    return (
      <div style={{ display: "grid", gap: 18 }}>
        {/* Info + privacy banner */}
        <div
          style={{
            border: "1px solid #bfdbfe",
            borderRadius: 12,
            background: "#eff6ff",
            padding: "14px 16px",
            display: "grid",
            gap: 10,
          }}
        >
          <p style={{ margin: 0, fontSize: 12, color: "#1e40af", lineHeight: 1.6 }}>
            Use the VeriBridge Chrome Extension to record a live walkthrough of your private project
            website in your own browser. This works for private dashboards and websites that use
            Google login.
          </p>
          <p
            style={{
              margin: 0,
              fontSize: 11,
              color: "#3b82f6",
              lineHeight: 1.5,
              borderTop: "1px solid #bfdbfe",
              paddingTop: 10,
            }}
          >
            <strong>Privacy:</strong> VeriBridge records project workflow evidence only. Do not show
            personal data. Passwords and sensitive fields are masked by the extension and backend.
          </p>
        </div>

        {error && (
          <div
            role="alert"
            style={{
              border: "1px solid #fecaca",
              background: "#fef2f2",
              color: "#991b1b",
              borderRadius: 10,
              padding: "8px 12px",
              fontSize: 12,
            }}
          >
            {error}
          </div>
        )}

        <div style={{ display: "grid", gap: 12 }}>
          {/* Website URL */}
          <div style={{ display: "grid", gap: 4 }}>
            <label style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>
              Website URL <span style={{ color: "#dc2626" }}>*</span>
            </label>
            <input
              value={form.websiteUrl}
              onChange={(e) => setForm((f) => ({ ...f, websiteUrl: e.target.value }))}
              placeholder="https://your-private-project.vercel.app"
              style={inp}
              disabled={creating}
            />
            <span style={{ fontSize: 11, color: "var(--muted)" }}>
              Can be a private site that requires Google login.
            </span>
          </div>

          {/* GitHub URL */}
          <div style={{ display: "grid", gap: 4 }}>
            <label style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>
              GitHub Repository URL{" "}
              <span style={{ fontWeight: 400, color: "var(--muted)" }}>(optional)</span>
            </label>
            <input
              value={form.githubUrl}
              onChange={(e) => setForm((f) => ({ ...f, githubUrl: e.target.value }))}
              placeholder="https://github.com/username/repo"
              style={inp}
              disabled={creating}
            />
          </div>

          {/* Skill name */}
          <div style={{ display: "grid", gap: 4 }}>
            <label style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>
              Skill this demonstrates <span style={{ color: "#dc2626" }}>*</span>
            </label>
            <input
              value={form.skillName}
              onChange={(e) => setForm((f) => ({ ...f, skillName: e.target.value }))}
              placeholder="e.g. FastAPI, React, Machine Learning"
              style={inp}
              disabled={creating}
            />
          </div>

          {/* Proof objective */}
          <div style={{ display: "grid", gap: 4 }}>
            <label style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>
              Proof objective <span style={{ color: "#dc2626" }}>*</span>
            </label>
            <textarea
              value={form.proofObjective}
              onChange={(e) => setForm((f) => ({ ...f, proofObjective: e.target.value }))}
              placeholder="Describe what you'll walk through — e.g. 'Show the live ML inference dashboard processing a new prediction request and displaying the result.'"
              style={{
                ...inp,
                minHeight: 80,
                resize: "vertical",
                fontFamily: "inherit",
                lineHeight: 1.5,
              }}
              disabled={creating}
            />
            <span style={{ fontSize: 11, color: "var(--muted)" }}>
              What feature or workflow will you demonstrate? (5 words minimum)
            </span>
          </div>
        </div>

        {/* Footer */}
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
          <button
            type="button"
            onClick={onBack}
            disabled={creating}
            style={{
              border: "1px solid var(--line-2)",
              background: "transparent",
              color: "var(--ink-2)",
              borderRadius: 10,
              padding: "9px 14px",
              fontWeight: 600,
              fontSize: 13,
              cursor: creating ? "not-allowed" : "pointer",
            }}
          >
            ← Back
          </button>
          <button
            type="button"
            onClick={() => void handleCreate()}
            disabled={creating}
            style={{
              border: "1px solid transparent",
              background: creating ? "var(--bg-2)" : "var(--ink)",
              color: creating ? "var(--muted)" : "#fff",
              borderRadius: 10,
              padding: "10px 20px",
              fontWeight: 700,
              fontSize: 14,
              cursor: creating ? "not-allowed" : "pointer",
            }}
          >
            {creating ? "Creating session…" : "Create Extension Proof Session"}
          </button>
        </div>
      </div>
    )
  }

  // ── Render: session active ────────────────────────────────────────────────

  if (step === "session_active" && session) {
    const hasStarted = (["recording", "uploaded_pending_analysis", "analyzing", "completed"] as ExtensionProofSessionStatus[]).includes(session.status)
    const isCompleted = session.status === "completed"
    const isExpired   = session.status === "expired"

    const sessionDetails: Array<[string, string, boolean]> = [
      ["Session ID", session.id.slice(0, 18) + "…", true],
      ["Website",    form.websiteUrl, false],
      ...(form.githubUrl ? [["GitHub", form.githubUrl, false] as [string, string, boolean]] : []),
      ["Skill",      form.skillName, false],
    ]

    return (
      <div style={{ display: "grid", gap: 18 }}>
        {/* Session card */}
        <div
          style={{
            border: "1px solid var(--line)",
            borderRadius: 14,
            background: "var(--bg-2)",
            padding: "16px 18px",
            display: "grid",
            gap: 10,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
            }}
          >
            <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>
              Extension Proof Session
            </span>
            <StatusBadge status={session.status} />
          </div>

          <div style={{ display: "grid", gap: 5 }}>
            {sessionDetails.map(([label, value, mono]) => (
              <div key={label} style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                <span
                  style={{
                    fontSize: 11,
                    color: "var(--muted)",
                    minWidth: 70,
                    flexShrink: 0,
                  }}
                >
                  {label}
                </span>
                <span
                  style={{
                    fontSize: 12,
                    color: "var(--ink)",
                    fontFamily: mono ? "monospace" : "inherit",
                    wordBreak: "break-all",
                  }}
                >
                  {value}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Session stepper */}
        <SessionStepper status={session.status} />

        {error && (
          <div
            role="alert"
            style={{
              border: "1px solid #fecaca",
              background: "#fef2f2",
              color: "#991b1b",
              borderRadius: 10,
              padding: "8px 12px",
              fontSize: 12,
            }}
          >
            {error}
          </div>
        )}

        {/* Status-aware message card */}
        {!isExpired && (
          <StatusMessage status={session.status} pollingActive={pollingActive} />
        )}

        {/* GitHub Analysis */}
        {form.githubUrl && (["uploaded_pending_analysis", "analyzing", "completed"] as ExtensionProofSessionStatus[]).includes(session.status) && (
          <div style={{ display: "grid", gap: 10 }}>
            {!githubAnalysis && (
              <button
                type="button"
                onClick={() => void handleAnalyzeGitHub()}
                disabled={analyzingGitHub}
                style={{
                  border: "1px solid #1d4ed8",
                  background: analyzingGitHub ? "#eff6ff" : "#1d4ed8",
                  color: analyzingGitHub ? "#1d4ed8" : "#fff",
                  borderRadius: 10,
                  padding: "9px 16px",
                  fontWeight: 600,
                  fontSize: 13,
                  cursor: analyzingGitHub ? "not-allowed" : "pointer",
                  width: "100%",
                }}
              >
                {analyzingGitHub ? "Analyzing GitHub repo…" : "⬡ Analyze GitHub Evidence"}
              </button>
            )}
            {githubAnalysisError && (
              <div
                role="alert"
                style={{
                  border: "1px solid #fecaca",
                  background: "#fef2f2",
                  color: "#991b1b",
                  borderRadius: 10,
                  padding: "8px 12px",
                  fontSize: 12,
                }}
              >
                {githubAnalysisError}
              </div>
            )}
            {githubAnalysis && <GitHubAnalysisCard analysis={githubAnalysis} onReanalyze={() => void handleAnalyzeGitHub()} reanalyzing={analyzingGitHub} />}
          </div>
        )}

        {/* Expired */}
        {isExpired && (
          <div
            style={{
              border: "1px solid #fecaca",
              background: "#fef2f2",
              borderRadius: 12,
              padding: "14px 16px",
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 700, color: "#991b1b" }}>Session expired</div>
            <p style={{ margin: "4px 0 0", fontSize: 12, color: "#7f1d1d", lineHeight: 1.5 }}>
              Sessions expire after 15 minutes. Click Back to start a new session.
            </p>
          </div>
        )}

        {/* Actions */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          <button
            type="button"
            onClick={onBack}
            style={{
              border: "1px solid var(--line-2)",
              background: "transparent",
              color: "var(--ink-2)",
              borderRadius: 10,
              padding: "9px 14px",
              fontWeight: 600,
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            ← Back
          </button>

          {!hasStarted && !isExpired && (
            <button
              type="button"
              onClick={() => void handleStart()}
              disabled={starting}
              style={{
                border: "1px solid transparent",
                background: starting ? "var(--bg-2)" : "#065f46",
                color: starting ? "var(--muted)" : "#fff",
                borderRadius: 10,
                padding: "10px 20px",
                fontWeight: 700,
                fontSize: 14,
                cursor: starting ? "not-allowed" : "pointer",
              }}
            >
              {starting ? "Opening…" : "▶  Start Proof Demo"}
            </button>
          )}

          {(isCompleted || isExpired) && (
            <button
              type="button"
              onClick={onBack}
              style={{
                border: "1px solid var(--ink)",
                background: "var(--ink)",
                color: "#fff",
                borderRadius: 10,
                padding: "10px 20px",
                fontWeight: 700,
                fontSize: 14,
                cursor: "pointer",
              }}
            >
              Done
            </button>
          )}
        </div>
      </div>
    )
  }

  return null
}
