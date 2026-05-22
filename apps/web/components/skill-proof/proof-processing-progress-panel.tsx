"use client"

/**
 * proof-processing-progress-panel.tsx — Phase J4
 * Reusable inline progress panel for all proof saving and AI evidence
 * processing flows. Renders inside existing modal dialogs — not a modal itself.
 */

import { useState } from "react"
import type { CSSProperties } from "react"
import {
  calculateProgressPercent,
  getCurrentStepLabel,
  type ProofProcessingProgress,
  type ProofProcessingStatus,
  type ProofProcessingStep,
} from "@/lib/proof-processing"

// ── Step status icon ──────────────────────────────────────────────────────────

function StepIcon({ status }: { status: ProofProcessingStatus }) {
  const base: CSSProperties = {
    width: 20,
    height: 20,
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 11,
    fontWeight: 700,
    flexShrink: 0,
    marginTop: 1,
  }
  if (status === "completed") {
    return (
      <div style={{ ...base, background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }}>✓</div>
    )
  }
  if (status === "running") {
    return (
      <div style={{ ...base, background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" }}>
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: "50%",
            background: "#3b82f6",
            display: "block",
            animation: "proof-pulse 1.2s infinite",
          }}
        />
      </div>
    )
  }
  if (status === "skipped") {
    return (
      <div style={{ ...base, background: "#f8fafc", color: "#94a3b8", border: "1px solid #e2e8f0" }}>
        ─
      </div>
    )
  }
  if (status === "failed") {
    return (
      <div style={{ ...base, background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca" }}>✕</div>
    )
  }
  // pending
  return (
    <div style={{ ...base, background: "#f1f5f9", color: "#94a3b8", border: "1px solid #e2e8f0" }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#cbd5e1", display: "block" }} />
    </div>
  )
}

// ── Step row ──────────────────────────────────────────────────────────────────

function StepRow({ step }: { step: ProofProcessingStep }) {
  const isDimmed = step.status === "pending"
  const countText =
    step.countCurrent != null && step.countTotal != null
      ? ` — ${step.countCurrent} of ${step.countTotal}`
      : ""

  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        alignItems: "flex-start",
        opacity: isDimmed ? 0.45 : 1,
        transition: "opacity 0.2s",
      }}
    >
      <StepIcon status={step.status} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 12,
            fontWeight: step.status === "running" ? 700 : 600,
            color: step.status === "failed" ? "#991b1b" : step.status === "completed" ? "var(--ink)" : "var(--ink-2)",
          }}
        >
          {step.label}
          {countText && (
            <span style={{ fontWeight: 400, color: "var(--muted)", marginLeft: 4 }}>{countText}</span>
          )}
        </div>
        {step.status !== "pending" && (
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 1, lineHeight: 1.4 }}>
            {step.errorMessage ?? step.description}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function ProofProcessingProgressPanel({
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
  /** Optional extra content rendered below the summary (e.g. per-item result list). */
  extraDetails?: React.ReactNode
}) {
  const [showDetails, setShowDetails] = useState(false)
  const percent = calculateProgressPercent(progress.steps)
  const currentLabel = getCurrentStepLabel(progress.steps)
  const isDone = progress.overallStatus === "completed" || progress.overallStatus === "failed"
  const hasSummary = isDone && (progress.savedCount + progress.skippedCount + progress.failedCount) > 0

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {/* Pulse animation keyframes injected once */}
      <style>{`@keyframes proof-pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }`}</style>

      {/* Header */}
      <div>
        <div
          style={{
            fontSize: 11,
            fontWeight: 800,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: "var(--muted)",
            marginBottom: 4,
          }}
        >
          {progress.overallStatus === "completed" ? "Completed" : progress.overallStatus === "failed" ? "Failed" : "In Progress"}
        </div>
        <div style={{ fontSize: 16, fontWeight: 700, color: "var(--ink)" }}>{title}</div>
      </div>

      {/* Progress bar */}
      <div>
        <div
          style={{
            height: 6,
            borderRadius: 3,
            background: "var(--line)",
            overflow: "hidden",
            marginBottom: 6,
          }}
        >
          <div
            style={{
              height: "100%",
              borderRadius: 3,
              width: `${percent}%`,
              background: progress.overallStatus === "failed" ? "#ef4444" : "#22c55e",
              transition: "width 0.4s ease",
            }}
          />
        </div>
        <div style={{ fontSize: 11, color: "var(--muted)", display: "flex", justifyContent: "space-between" }}>
          <span>{currentLabel}</span>
          <span>{percent}%</span>
        </div>
      </div>

      {/* Step timeline */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {progress.steps.map((step) => (
          <StepRow key={step.id} step={step} />
        ))}
      </div>

      {/* Summary banner */}
      {hasSummary && (
        <div
          style={{
            border: `1px solid ${progress.overallStatus === "failed" ? "#fecaca" : "#bbf7d0"}`,
            background: progress.overallStatus === "failed" ? "#fef2f2" : "#f0fdf4",
            borderRadius: 12,
            padding: "12px 14px",
            display: "grid",
            gap: 4,
          }}
        >
          {progress.savedCount > 0 && (
            <div style={{ fontSize: 13, fontWeight: 700, color: "#166534" }}>
              ✓ Saved {progress.savedCount} item{progress.savedCount !== 1 ? "s" : ""}
            </div>
          )}
          {progress.skippedCount > 0 && (
            <div style={{ fontSize: 12, color: "#64748b" }}>
              − Skipped {progress.skippedCount} duplicate{progress.skippedCount !== 1 ? "s" : ""} — already in your profile
            </div>
          )}
          {progress.failedCount > 0 && (
            <div style={{ fontSize: 12, color: "#991b1b" }}>
              ✕ Failed {progress.failedCount} item{progress.failedCount !== 1 ? "s" : ""}
            </div>
          )}
          {progress.errorMessages.length > 0 && (
            <div style={{ fontSize: 11, color: "#991b1b", marginTop: 4 }}>
              {progress.errorMessages.slice(0, 3).map((msg, i) => (
                <div key={`err-${i}`}>{msg}</div>
              ))}
              {progress.errorMessages.length > 3 && (
                <div>and {progress.errorMessages.length - 3} more…</div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Extra details accordion (e.g. per-candidate results) */}
      {extraDetails && isDone && (
        <div style={{ border: "1px solid var(--line)", borderRadius: 10 }}>
          <button
            type="button"
            onClick={() => setShowDetails((p) => !p)}
            style={{
              width: "100%",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "8px 12px",
              background: "var(--bg-2)",
              border: "none",
              borderRadius: showDetails ? "10px 10px 0 0" : 10,
              cursor: "pointer",
              fontSize: 11,
              fontWeight: 600,
              color: "var(--ink-2)",
            }}
          >
            <span>Details</span>
            <span>{showDetails ? "▲" : "▼"}</span>
          </button>
          {showDetails && (
            <div style={{ padding: "8px 12px", maxHeight: 260, overflowY: "auto" }}>
              {extraDetails}
            </div>
          )}
        </div>
      )}

      {/* Done / close button */}
      {canClose && isDone && onClose && (
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button
            type="button"
            data-testid="proof-progress-done"
            onClick={onClose}
            style={{
              border: "1px solid transparent",
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
        </div>
      )}
    </div>
  )
}
