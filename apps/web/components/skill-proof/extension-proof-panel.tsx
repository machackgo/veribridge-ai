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
  createExtensionProofSession,
  createSkillEvidence,
  getExtensionProofSession,
  startExtensionProofSession,
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
  created:                   { bg: "#f1f5f9", color: "#475569", border: "#e2e8f0", label: "Created" },
  waiting_for_extension:     { bg: "#fef9c3", color: "#854d0e", border: "#fef08a", label: "Waiting" },
  recording:                 { bg: "#dcfce7", color: "#166534", border: "#bbf7d0", label: "Recording" },
  uploaded_pending_analysis: { bg: "#dbeafe", color: "#1d4ed8", border: "#bfdbfe", label: "Uploaded" },
  analyzing:                 { bg: "#ede9fe", color: "#5b21b6", border: "#ddd6fe", label: "Analyzing" },
  completed:                 { bg: "#dcfce7", color: "#166534", border: "#bbf7d0", label: "Complete" },
  expired:                   { bg: "#fef2f2", color: "#991b1b", border: "#fecaca", label: "Expired" },
}

function StatusBadge({ status }: { status: ExtensionProofSessionStatus }) {
  const c = STATUS_CONFIG[status] ?? STATUS_CONFIG.created
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        padding: "3px 8px",
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

// ── Status timeline ───────────────────────────────────────────────────────────

const TIMELINE_STEPS: Array<{
  label: string
  statuses: ExtensionProofSessionStatus[]
}> = [
  { label: "Session created", statuses: ["created", "waiting_for_extension"] },
  { label: "Recording",       statuses: ["recording"] },
  { label: "Proof uploaded",  statuses: ["uploaded_pending_analysis"] },
  { label: "Analyzing",       statuses: ["analyzing"] },
  { label: "Complete",        statuses: ["completed"] },
]

function timelineIndex(status: ExtensionProofSessionStatus): number {
  return TIMELINE_STEPS.findIndex(s => (s.statuses as string[]).includes(status))
}

function SessionTimeline({ status }: { status: ExtensionProofSessionStatus }) {
  const currentIdx = timelineIndex(status)

  return (
    <div>
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "var(--muted)",
          marginBottom: 12,
        }}
      >
        Session progress
      </div>
      <div style={{ display: "flex", alignItems: "flex-start" }}>
        {TIMELINE_STEPS.map((step, i) => {
          const isDone    = i < currentIdx
          const isCurrent = i === currentIdx

          return (
            <div
              key={step.label}
              style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center" }}
            >
              {/* Connector + dot row */}
              <div style={{ display: "flex", alignItems: "center", width: "100%" }}>
                {/* Left arm */}
                <div
                  style={{
                    flex: 1,
                    height: 2,
                    background: i === 0 ? "transparent" : isDone || isCurrent ? "#065f46" : "#e2e8f0",
                  }}
                />
                {/* Dot */}
                <div
                  style={{
                    width:  isCurrent ? 14 : 10,
                    height: isCurrent ? 14 : 10,
                    borderRadius: "50%",
                    flexShrink: 0,
                    background:  isDone ? "#065f46" : isCurrent ? "#16a34a" : "#e2e8f0",
                    boxShadow:   isCurrent ? "0 0 0 3px #dcfce7" : "none",
                  }}
                />
                {/* Right arm */}
                <div
                  style={{
                    flex: 1,
                    height: 2,
                    background:
                      i === TIMELINE_STEPS.length - 1
                        ? "transparent"
                        : isDone
                          ? "#065f46"
                          : "#e2e8f0",
                  }}
                />
              </div>
              {/* Label */}
              <div
                style={{
                  marginTop: 6,
                  fontSize: 10,
                  fontWeight: isCurrent ? 700 : 400,
                  color: isCurrent ? "#065f46" : isDone ? "#475569" : "#94a3b8",
                  textAlign: "center",
                  lineHeight: 1.3,
                  paddingInline: 2,
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

      // Open the website in a new tab with session ID injected as a query param
      try {
        const url = new URL(form.websiteUrl.trim())
        url.searchParams.set("veribridge_session_id", session.id)
        window.open(url.toString(), "_blank", "noopener,noreferrer")
      } catch {
        // Fallback for edge-case URLs
        window.open(form.websiteUrl.trim(), "_blank", "noopener,noreferrer")
      }

      setPoll(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start proof session.")
    } finally {
      setStarting(false)
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

        {/* Status timeline */}
        <SessionTimeline status={session.status} />

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

        {/* Recording instruction (visible while extension is expected to be recording) */}
        {hasStarted && !isCompleted && !isExpired && (
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
            <div style={{ fontSize: 13, fontWeight: 700, color: "#065f46" }}>
              VeriBridge Extension is now recording
            </div>
            <p style={{ margin: 0, fontSize: 12, color: "#064e3b", lineHeight: 1.7 }}>
              Use the VeriBridge Chrome Extension to record your workflow. When done, click{" "}
              <strong>Stop &amp; Send Proof</strong> in the extension. This page will update
              automatically when your proof is received.
            </p>
            {pollingActive && (
              <p style={{ margin: 0, fontSize: 11, color: "#16a34a" }}>
                Listening for proof upload…
              </p>
            )}
          </div>
        )}

        {/* Completed */}
        {isCompleted && (
          <div
            style={{
              border: "1px solid #d1fae5",
              borderRadius: 12,
              background: "#f0fdf4",
              padding: "14px 16px",
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 700, color: "#065f46" }}>
              Proof submitted — AI analysis complete
            </div>
            <p style={{ margin: "6px 0 0", fontSize: 12, color: "#064e3b", lineHeight: 1.5 }}>
              Your proof walkthrough has been analyzed. Check your Skill Proof Center for the
              result.
            </p>
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
