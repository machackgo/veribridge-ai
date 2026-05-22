"use client"

/**
 * proof-processing-progress-panel.tsx — Phase J4 / J4C
 * Reusable inline progress panel for all proof saving and AI evidence flows.
 *
 * Modes:
 *   "agent"    (default) — VeriBridge AI avatar, progressive step reveal,
 *              live natural-language copy, premium feel.
 *   "timeline" — original checklist of all steps, useful for debugging.
 */

import { useState } from "react"
import type { CSSProperties, ReactNode } from "react"
import {
  calculateProgressPercent,
  getCurrentStepLabel,
  type ProofProcessingProgress,
  type ProofProcessingStatus,
  type ProofProcessingStep,
  type WorkLogEntry,
  type WorkLogStatus,
} from "@/lib/proof-processing"

// ── CSS keyframes (injected once per render tree) ─────────────────────────────

const KEYFRAMES = `
@keyframes proof-pulse  { 0%,100%{opacity:1}  50%{opacity:0.3} }
@keyframes vb-blink-0   { 0%,100%{opacity:1}  40%{opacity:0.15} }
@keyframes vb-blink-1   { 0%,60%{opacity:0.15} 100%{opacity:1} }
@keyframes vb-blink-2   { 0%,80%{opacity:0.15} 100%{opacity:1} }
@keyframes vb-slidein   { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }
`

// ── VeriBridge AI avatar ──────────────────────────────────────────────────────

function VBAvatar({ size = 44 }: { size?: number }) {
  const r = Math.round(size * 0.28)
  return (
    <div
      aria-hidden="true"
      style={{
        width: size,
        height: size,
        borderRadius: r,
        background: "linear-gradient(135deg, #1e293b, #2a3050)",
        boxShadow: "inset 0 1px 0 rgba(255,255,255,0.14), 0 4px 14px rgba(79,70,229,0.28)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
      }}
    >
      <div
        style={{
          width: Math.round(size * 0.24),
          height: Math.round(size * 0.24),
          borderRadius: 999,
          background: "linear-gradient(135deg, #4f46e5, #7c3aed)",
          boxShadow: "0 0 12px rgba(79,70,229,0.75)",
        }}
      />
    </div>
  )
}

// ── Pulsing status dots ───────────────────────────────────────────────────────

function ThinkingDots() {
  return (
    <div style={{ display: "flex", gap: 3, alignItems: "center" }}>
      {([0, 1, 2] as const).map((i) => (
        <span
          key={i}
          style={{
            width: 5,
            height: 5,
            borderRadius: "50%",
            background: "#4f46e5",
            display: "block",
            animation: `vb-blink-${i} 1.4s ${i * 180}ms infinite`,
          }}
        />
      ))}
    </div>
  )
}

// ── Progress bar ──────────────────────────────────────────────────────────────

function ProgressBar({ percent, failed }: { percent: number; failed: boolean }) {
  return (
    <div
      style={{
        height: 4,
        borderRadius: 2,
        background: "var(--line)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          height: "100%",
          borderRadius: 2,
          width: `${percent}%`,
          background: failed ? "#ef4444" : "linear-gradient(90deg, #4f46e5, #7c3aed)",
          transition: "width 0.5s ease",
        }}
      />
    </div>
  )
}

// ── Summary banner ────────────────────────────────────────────────────────────

function SummaryBanner({ progress }: { progress: ProofProcessingProgress }) {
  const { savedCount, skippedCount, failedCount, errorMessages, overallStatus } = progress
  const hasStats = savedCount + skippedCount + failedCount > 0
  if (!hasStats) return null
  const failed = overallStatus === "failed"
  return (
    <div
      style={{
        border: `1px solid ${failed ? "#fecaca" : "#bbf7d0"}`,
        background: failed ? "#fef2f2" : "#f0fdf4",
        borderRadius: 12,
        padding: "12px 14px",
        display: "grid",
        gap: 4,
      }}
    >
      {savedCount > 0 && (
        <div style={{ fontSize: 13, fontWeight: 700, color: "#166534" }}>
          ✓ Saved {savedCount} item{savedCount !== 1 ? "s" : ""}
        </div>
      )}
      {skippedCount > 0 && (
        <div style={{ fontSize: 12, color: "#64748b" }}>
          − Skipped {skippedCount} duplicate{skippedCount !== 1 ? "s" : ""} — already in your profile
        </div>
      )}
      {failedCount > 0 && (
        <div style={{ fontSize: 12, color: "#991b1b" }}>
          ✕ Failed {failedCount} item{failedCount !== 1 ? "s" : ""}
        </div>
      )}
      {errorMessages.slice(0, 3).map((msg, i) => (
        <div key={`err-${i}`} style={{ fontSize: 11, color: "#991b1b" }}>
          {msg}
        </div>
      ))}
      {errorMessages.length > 3 && (
        <div style={{ fontSize: 11, color: "#991b1b" }}>and {errorMessages.length - 3} more…</div>
      )}
    </div>
  )
}

// ── Details accordion ─────────────────────────────────────────────────────────

function DetailsAccordion({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: 10 }}>
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        style={{
          width: "100%",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "8px 12px",
          background: "var(--bg-2)",
          border: "none",
          borderRadius: open ? "10px 10px 0 0" : 10,
          cursor: "pointer",
          fontSize: 11,
          fontWeight: 600,
          color: "var(--ink-2)",
        }}
      >
        <span>Details</span>
        <span>{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div style={{ padding: "8px 12px", maxHeight: 240, overflowY: "auto" }}>
          {children}
        </div>
      )}
    </div>
  )
}

// ── Done button ───────────────────────────────────────────────────────────────

function DoneButton({ onClick }: { onClick: () => void }) {
  return (
    <div style={{ display: "flex", justifyContent: "flex-end" }}>
      <button
        type="button"
        data-testid="proof-progress-done"
        onClick={onClick}
        style={{
          border: "1px solid transparent",
          background: "var(--ink)",
          color: "#fff",
          borderRadius: 10,
          padding: "10px 24px",
          fontWeight: 700,
          fontSize: 14,
          cursor: "pointer",
        }}
      >
        Done
      </button>
    </div>
  )
}

// ── Timeline step icon ────────────────────────────────────────────────────────

function StepIcon({ status }: { status: ProofProcessingStatus }) {
  const base: CSSProperties = {
    width: 20, height: 20, borderRadius: "50%", display: "flex", alignItems: "center",
    justifyContent: "center", fontSize: 11, fontWeight: 700, flexShrink: 0, marginTop: 1,
  }
  if (status === "completed") return <div style={{ ...base, background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }}>✓</div>
  if (status === "running") {
    return (
      <div style={{ ...base, background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" }}>
        <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#3b82f6", display: "block", animation: "proof-pulse 1.2s infinite" }} />
      </div>
    )
  }
  if (status === "skipped") return <div style={{ ...base, background: "#f8fafc", color: "#94a3b8", border: "1px solid #e2e8f0" }}>─</div>
  if (status === "failed")  return <div style={{ ...base, background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca" }}>✕</div>
  return <div style={{ ...base, background: "#f1f5f9", color: "#94a3b8", border: "1px solid #e2e8f0" }}><span style={{ width: 6, height: 6, borderRadius: "50%", background: "#cbd5e1", display: "block" }} /></div>
}

// ── Work log ─────────────────────────────────────────────────────────────────

const workLogIconMap: Record<WorkLogStatus, { char: string; color: string }> = {
  info:      { char: "›", color: "#64748b" },
  running:   { char: "◎", color: "#4f46e5" },
  completed: { char: "✓", color: "#22c55e" },
  warning:   { char: "⚠", color: "#f59e0b" },
  error:     { char: "✕", color: "#ef4444" },
}

function WorkLogView({ entries }: { entries: WorkLogEntry[] }) {
  if (entries.length === 0) return null
  return (
    <div
      style={{
        borderTop: "1px solid var(--line)",
        paddingTop: 12,
        display: "flex",
        flexDirection: "column",
        gap: 4,
        maxHeight: 220,
        overflowY: "auto",
      }}
    >
      {entries.map((entry) => {
        const icon = workLogIconMap[entry.status] ?? workLogIconMap.info
        const isRunning = entry.status === "running"
        return (
          <div
            key={entry.id}
            style={{
              display: "flex",
              gap: 8,
              alignItems: "flex-start",
              fontSize: 12,
              lineHeight: 1.4,
              animation: "vb-slidein 0.2s ease",
            }}
          >
            <span
              style={{
                color: icon.color,
                fontWeight: 700,
                fontSize: isRunning ? 10 : 11,
                flexShrink: 0,
                marginTop: 1,
                animation: isRunning ? "proof-pulse 1.2s infinite" : undefined,
              }}
            >
              {icon.char}
            </span>
            <span style={{ color: isRunning ? "var(--ink-2)" : "var(--muted)", fontWeight: isRunning ? 600 : 400 }}>
              {entry.message}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ── AGENT mode view ───────────────────────────────────────────────────────────

function AgentView({
  progress,
  onClose,
  canClose,
  extraDetails,
}: {
  progress: ProofProcessingProgress
  onClose?: () => void
  canClose?: boolean
  extraDetails?: ReactNode
}) {
  const calculatedPercent = calculateProgressPercent(progress.steps)
  const percent = progress.syntheticPercent != null
    ? Math.max(calculatedPercent, progress.syntheticPercent) // never go backwards
    : calculatedPercent
  const isDone = progress.overallStatus === "completed" || progress.overallStatus === "failed"
  const isFailed = progress.overallStatus === "failed"

  // Only show steps that have started (not pending)
  const visibleSteps = progress.steps.filter((s) => s.status !== "pending")

  // Live action text: use agentCopy of running step, or complete step's description (which is dynamically set), or done message
  const runningStep = progress.steps.find((s) => s.status === "running")
  const completeStep = progress.steps.find((s) => s.id === "complete" && s.status === "completed")
  const failedStep = progress.steps.find((s) => s.status === "failed")

  const liveText =
    failedStep?.errorMessage ??
    (isDone
      ? completeStep?.description ?? completeStep?.agentCopy ?? "Done."
      : runningStep?.agentCopy ?? runningStep?.description ?? "Working...")

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      {/* Keyframes */}
      <style>{KEYFRAMES}</style>

      {/* Avatar + brand header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <VBAvatar size={44} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)", letterSpacing: "-0.01em" }}>
            VeriBridge AI
          </div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 1 }}>
            {isFailed ? "Encountered an issue" : isDone ? "Finished" : "Processing your proof..."}
          </div>
        </div>
        {!isDone && <ThinkingDots />}
        {isDone && !isFailed && (
          <div style={{ fontSize: 16, color: "#22c55e" }}>✓</div>
        )}
        {isFailed && (
          <div style={{ fontSize: 14, color: "#ef4444" }}>✕</div>
        )}
      </div>

      {/* Live action text — the hero element */}
      <div
        style={{
          fontSize: 18,
          fontWeight: 600,
          color: isFailed ? "#991b1b" : "var(--ink)",
          lineHeight: 1.4,
          letterSpacing: "-0.01em",
          minHeight: 52,
          display: "flex",
          alignItems: "center",
        }}
      >
        {liveText}
      </div>

      {/* Progress bar */}
      <ProgressBar percent={percent} failed={isFailed} />

      {/* Completed/running steps — revealed progressively */}
      {visibleSteps.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          {visibleSteps.map((step) => {
            const isRunning = step.status === "running"
            const stepText = step.agentCopy ?? step.label
            const countText =
              isRunning && step.countCurrent != null && step.countTotal != null
                ? ` (${step.countCurrent} of ${step.countTotal})`
                : ""
            return (
              <div
                key={step.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 12,
                  animation: "vb-slidein 0.25s ease",
                }}
              >
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    width: 14,
                    flexShrink: 0,
                    color:
                      step.status === "completed" ? "#22c55e"
                      : step.status === "failed"   ? "#ef4444"
                      : step.status === "skipped"  ? "#94a3b8"
                      : "#4f46e5",
                  }}
                >
                  {step.status === "completed" ? "✓"
                    : step.status === "failed"  ? "✕"
                    : step.status === "skipped" ? "─"
                    : "◎"}
                </span>
                <span
                  style={{
                    color: isRunning ? "var(--ink-2)" : "var(--muted)",
                    fontWeight: isRunning ? 600 : 400,
                  }}
                >
                  {stepText}
                  {countText && (
                    <span style={{ color: "var(--muted)", fontWeight: 400 }}>{countText}</span>
                  )}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {/* Work log — progressive reveal of live actions */}
      {(progress.workLog?.length ?? 0) > 0 && (
        <WorkLogView entries={progress.workLog!} />
      )}

      {/* Summary banner */}
      {isDone && <SummaryBanner progress={progress} />}

      {/* Extra details accordion */}
      {extraDetails && isDone && (
        <DetailsAccordion>{extraDetails}</DetailsAccordion>
      )}

      {/* Done button */}
      {canClose && isDone && onClose && <DoneButton onClick={onClose} />}
    </div>
  )
}

// ── TIMELINE mode view (original checklist) ───────────────────────────────────

function TimelineView({
  title,
  progress,
  onClose,
  canClose,
  extraDetails,
}: {
  title: string
  progress: ProofProcessingProgress
  onClose?: () => void
  canClose?: boolean
  extraDetails?: ReactNode
}) {
  const percent = calculateProgressPercent(progress.steps)
  const currentLabel = getCurrentStepLabel(progress.steps)
  const isDone = progress.overallStatus === "completed" || progress.overallStatus === "failed"

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <style>{KEYFRAMES}</style>

      {/* Header */}
      <div>
        <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--muted)", marginBottom: 4 }}>
          {progress.overallStatus === "completed" ? "Completed" : progress.overallStatus === "failed" ? "Failed" : "In Progress"}
        </div>
        <div style={{ fontSize: 16, fontWeight: 700, color: "var(--ink)" }}>{title}</div>
      </div>

      {/* Progress bar + label */}
      <div>
        <div style={{ height: 6, borderRadius: 3, background: "var(--line)", overflow: "hidden", marginBottom: 6 }}>
          <div style={{
            height: "100%", borderRadius: 3, width: `${percent}%`,
            background: progress.overallStatus === "failed" ? "#ef4444" : "#22c55e",
            transition: "width 0.4s ease",
          }} />
        </div>
        <div style={{ fontSize: 11, color: "var(--muted)", display: "flex", justifyContent: "space-between" }}>
          <span>{currentLabel}</span>
          <span>{percent}%</span>
        </div>
      </div>

      {/* All steps */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {progress.steps.map((step) => (
          <div key={step.id} style={{ display: "flex", gap: 10, alignItems: "flex-start", opacity: step.status === "pending" ? 0.45 : 1, transition: "opacity 0.2s" }}>
            <StepIcon status={step.status} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: step.status === "running" ? 700 : 600, color: step.status === "failed" ? "#991b1b" : "var(--ink)" }}>
                {step.label}
                {step.countCurrent != null && step.countTotal != null && (
                  <span style={{ fontWeight: 400, color: "var(--muted)", marginLeft: 4 }}>
                    — {step.countCurrent} of {step.countTotal}
                  </span>
                )}
              </div>
              {step.status !== "pending" && (
                <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 1, lineHeight: 1.4 }}>
                  {step.errorMessage ?? step.description}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {isDone && <SummaryBanner progress={progress} />}
      {extraDetails && isDone && <DetailsAccordion>{extraDetails}</DetailsAccordion>}
      {canClose && isDone && onClose && <DoneButton onClick={onClose} />}
    </div>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────

export function ProofProcessingProgressPanel({
  title,
  progress,
  onClose,
  canClose,
  extraDetails,
  mode = "agent",
}: {
  title: string
  progress: ProofProcessingProgress
  onClose?: () => void
  canClose?: boolean
  /** Optional extra content in the Details accordion (e.g. per-item result list). */
  extraDetails?: ReactNode
  /**
   * "agent" (default) — VeriBridge AI branding, progressive step reveal, live copy.
   * "timeline"        — original checklist of all steps, useful for debugging.
   */
  mode?: "agent" | "timeline"
}) {
  if (mode === "timeline") {
    return (
      <TimelineView
        title={title}
        progress={progress}
        onClose={onClose}
        canClose={canClose}
        extraDetails={extraDetails}
      />
    )
  }
  return (
    <AgentView
      progress={progress}
      onClose={onClose}
      canClose={canClose}
      extraDetails={extraDetails}
    />
  )
}
