"use client"

import { useState } from "react"
import type { CSSProperties } from "react"
import type {
  SkillEvidenceProfile,
  WorkflowAnalysisResponse,
  ObservedDemonstration,
  DemonstrationStep,
  VisibleEvidenceStatus,
} from "@/lib/api"
import { getWorkflowAnalysis } from "@/lib/api"

// ── Style helpers ─────────────────────────────────────────────────────────────

const badge: CSSProperties = {
  display: "inline-block",
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  padding: "3px 8px",
  borderRadius: 999,
}

function evidenceLevelStyle(level: SkillEvidenceProfile["evidence_level"]): CSSProperties {
  switch (level) {
    case "self_claimed":
      return { background: "#f1f5f9", color: "#475569", border: "1px solid #e2e8f0" }
    case "workflow_evidence_complete":
      return { background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" }
    case "workflow_analysis_ai_reviewed":
      return { background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0" }
    case "multi_source_ai_reviewed":
      return { background: "#fdf4ff", color: "#7e22ce", border: "1px solid #e9d5ff" }
    case "final_verification_ready":
      return { background: "#dcfce7", color: "#14532d", border: "1px solid #86efac" }
    default:
      return { background: "#f1f5f9", color: "#475569", border: "1px solid #e2e8f0" }
  }
}

function confidenceStyle(confidence: string): CSSProperties {
  if (confidence === "high") return { background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }
  if (confidence === "medium") return { background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a" }
  if (confidence === "low") return { background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca" }
  return { background: "#f1f5f9", color: "#64748b", border: "1px solid #e2e8f0" }
}

function scoreColor(score: number | null): string {
  if (score === null) return "#64748b"
  if (score >= 70) return "#166534"
  if (score >= 40) return "#854d0e"
  return "#991b1b"
}

// ── Evidence sources checklist ────────────────────────────────────────────────

function SourceChecklist({ profile }: { profile: SkillEvidenceProfile }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      {profile.evidence_sources.map((src) => {
        const isComplete = src.status === "complete"
        const isPending = src.status === "pending"
        const isUnavailable = src.status === "unavailable"
        const dot = isComplete ? "#22c55e" : isPending ? "#f59e0b" : "#cbd5e1"
        const textColor = isUnavailable ? "#94a3b8" : isComplete ? "#166534" : "#92400e"
        return (
          <div key={src.key} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11 }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: dot, flexShrink: 0 }} />
            <span style={{ color: textColor, textDecoration: isUnavailable ? "line-through" : "none" }}>
              {src.label}
            </span>
            {isComplete && <span style={{ fontSize: 9, color: "#166534", fontWeight: 700 }}>✓</span>}
            {isUnavailable && <span style={{ fontSize: 9, color: "#94a3b8" }}>Coming soon</span>}
          </div>
        )
      })}
    </div>
  )
}

// ── Visible evidence status badge ────────────────────────────────────────────

function VisibleEvidenceBadge({ status }: { status: VisibleEvidenceStatus | undefined }) {
  if (!status || status === "not_captured") {
    return (
      <span
        title="Visible DOM evidence was not captured for this recording. Re-record after the extension update to enable this."
        style={{
          fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
          background: "#f1f5f9", color: "#64748b", border: "1px dashed #cbd5e1",
        }}
      >
        DOM evidence: not captured
      </span>
    )
  }
  if (status === "partial") {
    return (
      <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
        background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a" }}>
        DOM evidence: partial
      </span>
    )
  }
  return (
    <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
      background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0" }}>
      DOM evidence: captured ✓
    </span>
  )
}

// ── Visual frame analysis badge ───────────────────────────────────────────────

type VisualFrameStatus = "not_configured" | "not_captured" | "analyzed" | "skipped" | "failed" | "pending"

function VisualFrameBadge({ status, provider, frameCount }: {
  status: VisualFrameStatus | undefined
  provider?: string
  frameCount?: number
}) {
  if (!status || status === "not_captured" || status === "not_configured") {
    const isNone = !status || status === "not_captured"
    return (
      <span
        title={
          isNone
            ? "No visual frames captured. Set ENABLE_WORKFLOW_FRAME_CAPTURE=true to enable."
            : "Visual analysis provider not configured. Set VISUAL_ANALYSIS_PROVIDER to enable."
        }
        style={{
          fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
          background: "#f1f5f9", color: "#64748b", border: "1px dashed #cbd5e1",
        }}
      >
        Visual frames: not configured
      </span>
    )
  }
  if (status === "analyzed") {
    const label = frameCount ? `Visual frames: ${frameCount} analyzed ✓` : "Visual frames: analyzed ✓"
    return (
      <span
        title={`Provider: ${provider ?? "unknown"}. Visual frame analysis uses local/open-source models — no external API required.`}
        style={{
          fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
          background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0",
        }}
      >
        {label}
      </span>
    )
  }
  if (status === "pending") {
    return (
      <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
        background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a" }}>
        Visual frames: analyzing…
      </span>
    )
  }
  return (
    <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
      background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca" }}>
      Visual frames: {status}
    </span>
  )
}

// ── OCR status badge ──────────────────────────────────────────────────────────

function OCRBadge({ status, provider }: { status: string | undefined; provider?: string }) {
  if (!status || status === "not_configured" || status === "not_available") {
    return (
      <span
        title="Local OCR not configured. Set VISUAL_ANALYSIS_PROVIDER=local_ocr and install PaddleOCR or EasyOCR."
        style={{
          fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
          background: "#f1f5f9", color: "#64748b", border: "1px dashed #cbd5e1",
        }}
      >
        Local OCR: not configured
      </span>
    )
  }
  if (status === "analyzed") {
    return (
      <span
        title={`OCR provider: ${provider ?? "local"}. No external API required.`}
        style={{
          fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
          background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe",
        }}
      >
        Local OCR: active ✓
      </span>
    )
  }
  return null
}

// ── Evidence layer legend (full panel) ───────────────────────────────────────

function EvidenceLayerLegend({ analysis }: { analysis: WorkflowAnalysisResponse }) {
  const hasEvents = (analysis.demonstrated_actions?.length ?? 0) > 0
  const domStatus = analysis.dom_evidence_status ?? analysis.visible_evidence_status ?? "not_captured"
  const visualStatus = (analysis as Record<string, unknown>).visual_analysis_status as VisualFrameStatus | undefined
  const ocrStatus = (analysis as Record<string, unknown>).ocr_status as string | undefined
  const visualProvider = (analysis as Record<string, unknown>).visual_analysis_provider as string | undefined
  const visualFrameCount = (analysis as Record<string, unknown>).visual_frame_count as number | undefined

  return (
    <div
      style={{
        background: "#f8fafc",
        border: "1px solid #e2e8f0",
        borderRadius: 8,
        padding: "10px 12px",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: "0.09em", textTransform: "uppercase", color: "#475569", marginBottom: 2 }}>
        Evidence Layers
      </div>

      {/* Row: Browser events */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <span style={{ fontSize: 10, color: "#64748b", minWidth: 130 }}>Browser events</span>
        {hasEvents ? (
          <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
            background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0" }}>
            captured ✓
          </span>
        ) : (
          <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4,
            background: "#f1f5f9", color: "#94a3b8", border: "1px dashed #cbd5e1" }}>
            not detected
          </span>
        )}
      </div>

      {/* Row: DOM evidence */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <span style={{ fontSize: 10, color: "#64748b", minWidth: 130 }}>DOM evidence</span>
        <VisibleEvidenceBadge status={domStatus as "not_captured" | "partial" | "available"} />
      </div>

      {/* Row: Visual frames */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <span style={{ fontSize: 10, color: "#64748b", minWidth: 130 }}>Visual frames</span>
        <VisualFrameBadge status={visualStatus} provider={visualProvider} frameCount={visualFrameCount} />
      </div>

      {/* Row: Local OCR */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <span style={{ fontSize: 10, color: "#64748b", minWidth: 130 }}>Local OCR</span>
        <OCRBadge status={ocrStatus} provider={visualProvider} />
      </div>

      {/* Privacy note */}
      <div style={{ marginTop: 4, fontSize: 9, color: "#94a3b8", fontStyle: "italic", lineHeight: 1.4 }}>
        Visual frame analysis uses local/open-source providers when configured.
        No external vision API is required for the local pipeline.
      </div>
    </div>
  )
}

// ── Evidence source label ─────────────────────────────────────────────────────

function EvidenceSourceLabel({ source }: { source: string | undefined }) {
  if (!source || source === "event_metadata") {
    return (
      <span style={{ fontSize: 9, color: "#94a3b8", fontStyle: "italic" }}>
        Browser event metadata
      </span>
    )
  }
  if (source === "dom_snapshot") {
    return (
      <span style={{ fontSize: 9, color: "#1d4ed8", background: "#eff6ff",
        border: "1px solid #bfdbfe", borderRadius: 3, padding: "1px 5px", fontWeight: 600 }}>
        DOM text captured
      </span>
    )
  }
  if (source === "inferred_from_click") {
    return (
      <span style={{ fontSize: 9, color: "#92400e", fontStyle: "italic" }}>
        Inferred from click only (low confidence)
      </span>
    )
  }
  return null
}

// ── Observed Demonstration Timeline ──────────────────────────────────────────

function ObservedDemonstrationTimeline({ demo }: { demo: ObservedDemonstration }) {
  const visStatus = demo.visible_evidence_status ?? "not_captured"

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: "0.1em", textTransform: "uppercase", color: "#475569" }}>
          Observed Demonstration Timeline
        </div>
        <VisibleEvidenceBadge status={visStatus} />
        <span style={{ fontSize: 9, color: "#94a3b8", fontStyle: "italic" }}>
          🔒 Privacy sanitized
        </span>
        {visStatus === "not_captured" && (
          <span style={{ fontSize: 9, color: "#94a3b8", fontStyle: "italic" }}>
            · Frame/OCR unavailable
          </span>
        )}
      </div>

      {/* Summary */}
      <div style={{ fontSize: 11, color: "#334155", lineHeight: 1.6, padding: "8px 10px",
        background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8 }}>
        {demo.summary}
      </div>

      {/* Not captured notice */}
      {visStatus === "not_captured" && (
        <div style={{ fontSize: 11, color: "#92400e", background: "#fef9c3",
          border: "1px solid #fef08a", borderRadius: 6, padding: "6px 10px" }}>
          Exact output values were not captured. VeriBridge only observed browser events for this recording.
          Use a new recording after the extension update to capture visible page evidence.
        </div>
      )}

      {/* Step cards */}
      {demo.steps.map((step) => (
        <StepCard key={step.step_number} step={step} />
      ))}

      {/* Limitations */}
      {demo.limitations.length > 0 && (
        <div style={{ fontSize: 10, color: "#64748b", padding: "6px 10px",
          background: "#f8fafc", border: "1px dashed #e2e8f0", borderRadius: 6 }}>
          <strong>Limitations:</strong>
          <ul style={{ margin: "4px 0 0 0", paddingLeft: 16 }}>
            {demo.limitations.map((l, i) => (
              <li key={i} style={{ lineHeight: 1.5 }}>{l}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function StepCard({ step }: { step: DemonstrationStep }) {
  const hasResultValues = step.detected_result_values.length > 0
  const hasVisibleText = step.visible_text_evidence.length > 0
  const hasDomEvidence = step.evidence_source === "dom_snapshot"

  const stepBg = hasResultValues
    ? "#f0fdf4"
    : hasDomEvidence
    ? "#eff6ff"
    : "#f8fafc"
  const stepBorder = hasResultValues
    ? "1px solid #bbf7d0"
    : hasDomEvidence
    ? "1px solid #bfdbfe"
    : "1px solid #e2e8f0"

  return (
    <div style={{ padding: "10px 12px", background: stepBg, border: stepBorder,
      borderRadius: 8, display: "flex", flexDirection: "column", gap: 6 }}>
      {/* Step header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: "#475569",
          background: "#e2e8f0", borderRadius: 4, padding: "1px 6px" }}>
          Step {step.step_number}
        </span>
        <span style={{ fontSize: 11, fontWeight: 600, color: "#0f172a", flex: 1 }}>
          {step.user_action}
        </span>
        <span style={{ ...confidenceStyle(step.confidence), ...badge, fontSize: 8 }}>
          {step.confidence}
        </span>
        <EvidenceSourceLabel source={step.evidence_source} />
      </div>

      {/* Input */}
      {step.observed_input && (
        <div style={{ fontSize: 11, color: "#334155" }}>
          <strong style={{ color: "#1d4ed8" }}>Input:</strong> {step.observed_input}
        </div>
      )}

      {/* Output */}
      {step.observed_output && (
        <div style={{ fontSize: 11, color: "#334155" }}>
          <strong style={{ color: "#166534" }}>Output:</strong> {step.observed_output}
        </div>
      )}

      {/* Detected result values */}
      {hasResultValues && (
        <div>
          <div style={{ fontSize: 9, fontWeight: 700, color: "#166534",
            textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 3 }}>
            Captured output values
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {step.detected_result_values.map((rv, i) => (
              <span key={i} style={{ fontSize: 10, padding: "2px 8px", borderRadius: 6,
                background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0",
                fontFamily: "monospace" }}>
                {rv.label}: {rv.value}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Visible text evidence (condensed) */}
      {hasVisibleText && !hasResultValues && (
        <div style={{ fontSize: 10, color: "#475569", fontStyle: "italic" }}>
          Evidence: {step.visible_text_evidence.slice(0, 2).join(" · ")}
        </div>
      )}

      {/* Feature demonstrated */}
      {step.demonstrated_feature && (
        <div style={{ fontSize: 9, color: "#64748b" }}>
          Feature: {step.demonstrated_feature}
        </div>
      )}

      {/* Review flag */}
      {step.needs_review && (
        <div style={{ fontSize: 9, color: "#92400e", fontStyle: "italic" }}>
          ⚠ Needs review — exact value not confirmed from event metadata alone
        </div>
      )}
    </div>
  )
}

// ── Inline analysis view ──────────────────────────────────────────────────────

function InlineAnalysisView({ analysis }: { analysis: WorkflowAnalysisResponse }) {
  const [showTimeline, setShowTimeline] = useState(false)
  const visStatus = analysis.visible_evidence_status ?? analysis.observed_demonstration?.visible_evidence_status

  return (
    <div
      style={{
        marginTop: 10,
        padding: "12px 14px",
        background: "#f8fafc",
        border: "1px solid #e2e8f0",
        borderRadius: 10,
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.1em", textTransform: "uppercase", color: "#64748b" }}>
          Workflow Evidence Analysis — AI Reviewed
        </div>
        <VisibleEvidenceBadge status={visStatus} />
      </div>

      {analysis.recruiter_summary && (
        <div style={{ fontSize: 12, color: "#1e293b", lineHeight: 1.6 }}>
          {analysis.recruiter_summary}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <span style={{ ...badge, ...confidenceStyle(analysis.workflow_confidence), fontSize: 9 }}>
          {analysis.workflow_confidence} confidence
        </span>
        <span style={{ fontSize: 11, color: scoreColor(analysis.evidence_strength_score), fontWeight: 700 }}>
          Score: {analysis.evidence_strength_score}/100
        </span>
      </div>

      {analysis.supported_skills.length > 0 && (
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: "#166534", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>
            Evidence supports
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {analysis.supported_skills.map((s) => (
              <span key={s} style={{ fontSize: 10, padding: "2px 8px", borderRadius: 6, background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }}>
                {s}
              </span>
            ))}
          </div>
        </div>
      )}

      {analysis.weakly_supported_skills.length > 0 && (
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: "#854d0e", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>
            Partially supported
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {analysis.weakly_supported_skills.map((s) => (
              <span key={s} style={{ fontSize: 10, padding: "2px 8px", borderRadius: 6, background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a" }}>
                {s}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Evidence layer badges */}
      <EvidenceLayerLegend analysis={analysis} />

      {/* Observed Demonstration Timeline toggle */}
      {analysis.observed_demonstration && (
        <div>
          <button
            type="button"
            onClick={() => setShowTimeline((v) => !v)}
            style={{
              fontSize: 10, fontWeight: 600, padding: "4px 10px", borderRadius: 6,
              border: "1px solid #bfdbfe", background: showTimeline ? "#eff6ff" : "#f8fafc",
              color: "#1d4ed8", cursor: "pointer",
            }}
          >
            {showTimeline ? "Hide Timeline ▲" : "Show Observed Demonstration Timeline ▼"}
          </button>
          {showTimeline && (
            <div style={{ marginTop: 8 }}>
              <ObservedDemonstrationTimeline demo={analysis.observed_demonstration} />
            </div>
          )}
        </div>
      )}

      {analysis.student_improvement_suggestions.length > 0 && (
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>
            Suggestions to strengthen evidence
          </div>
          <ul style={{ margin: 0, paddingLeft: 16, display: "flex", flexDirection: "column", gap: 3 }}>
            {analysis.student_improvement_suggestions.slice(0, 4).map((s, i) => (
              <li key={i} style={{ fontSize: 11, color: "#475569", lineHeight: 1.5 }}>{s}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// ── Submission history timeline ───────────────────────────────────────────────

function HistoryTimeline({ profile }: { profile: SkillEvidenceProfile }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>
        Submission History ({profile.submission_count})
      </div>
      {profile.history.map((attempt, i) => {
        const isLatest = i === 0
        const date = attempt.submitted_at ? new Date(attempt.submitted_at).toLocaleDateString() : "—"
        return (
          <div key={attempt.evidence_id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11 }}>
            <span style={{ color: "#94a3b8", fontFamily: "monospace", width: 80, flexShrink: 0 }}>{date}</span>
            <span style={{ color: "#475569" }}>{attempt.skill_name}</span>
            {attempt.session_status && (
              <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 4, background: "#f1f5f9", color: "#64748b", border: "1px solid #e2e8f0" }}>
                {attempt.session_status}
              </span>
            )}
            {attempt.has_analysis && (
              <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 4, background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0" }}>
                Analysed
              </span>
            )}
            {isLatest && (
              <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 4, background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe", fontWeight: 700 }}>
                Latest
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function WorkflowEvidenceProfileCard({
  profile,
  onRefresh,
}: {
  profile: SkillEvidenceProfile
  onRefresh?: () => void
}) {
  const [showAnalysis, setShowAnalysis] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [analysis, setAnalysis] = useState<WorkflowAnalysisResponse | null>(null)
  const [loadingAnalysis, setLoadingAnalysis] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)

  async function handleViewAnalysis() {
    if (showAnalysis && analysis) {
      setShowAnalysis(false)
      return
    }
    if (showAnalysis) {
      setShowAnalysis(false)
      return
    }
    if (!profile.latest_session_id) return

    if (analysis) {
      setShowAnalysis(true)
      return
    }

    setLoadingAnalysis(true)
    setAnalysisError(null)
    try {
      const result = await getWorkflowAnalysis(profile.latest_session_id)
      setAnalysis(result)
      setShowAnalysis(true)
    } catch (err) {
      setAnalysisError(err instanceof Error ? err.message : "Failed to load analysis.")
    } finally {
      setLoadingAnalysis(false)
    }
  }

  const hasAnalysis = profile.has_workflow_analysis
  const canViewAnalysis = hasAnalysis && !!profile.latest_session_id

  return (
    <div
      style={{
        border: "1px solid #bfdbfe",
        borderRadius: 14,
        background: "#fff",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "14px 16px",
          borderBottom: "1px solid #e0f2fe",
          background: "linear-gradient(135deg, #f0f9ff 0%, #f8fafc 100%)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10, flexWrap: "wrap" }}>
          {/* Left: skill name + badges */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span style={{ fontSize: 15, fontWeight: 700, color: "#0f172a" }}>
                {profile.primary_skill_name}
              </span>
              {profile.all_skill_names.length > 1 && (
                <span style={{ fontSize: 10, color: "#64748b" }}>
                  + {profile.all_skill_names.slice(1).join(", ")}
                </span>
              )}
            </div>

            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
              <span style={{ ...badge, ...evidenceLevelStyle(profile.evidence_level) }}>
                {profile.evidence_level_label}
              </span>
              {profile.confidence !== "unknown" && (
                <span style={{ ...badge, ...confidenceStyle(profile.confidence), fontSize: 9 }}>
                  {profile.confidence} confidence
                </span>
              )}
              {profile.evidence_strength_score !== null && (
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    color: scoreColor(profile.evidence_strength_score),
                    background: "#f8fafc",
                    border: "1px solid #e2e8f0",
                    borderRadius: 6,
                    padding: "2px 7px",
                  }}
                >
                  {profile.evidence_strength_score}/100
                </span>
              )}
              <span style={{ fontSize: 10, color: "#94a3b8" }}>
                {profile.submission_count} submission{profile.submission_count !== 1 ? "s" : ""}
              </span>
            </div>

            {profile.evidence_url && (
              <a
                href={profile.evidence_url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ fontSize: 11, color: "#1d4ed8", textDecoration: "none", fontWeight: 500 }}
              >
                {profile.evidence_url.length > 60
                  ? `${profile.evidence_url.slice(0, 57)}…`
                  : profile.evidence_url}{" "}
                ↗
              </a>
            )}
          </div>

          {/* Right: Extension Proof badge */}
          <span
            style={{
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              padding: "3px 8px",
              borderRadius: 6,
              background: "#eff6ff",
              color: "#1d4ed8",
              border: "1px solid #bfdbfe",
              flexShrink: 0,
            }}
          >
            Extension Proof
          </span>
        </div>

        {profile.proof_objective && (
          <div style={{ fontSize: 11, color: "#475569", marginTop: 8, lineHeight: 1.5 }}>
            <strong style={{ color: "#334155" }}>Objective:</strong> {profile.proof_objective}
          </div>
        )}
      </div>

      {/* Body */}
      <div style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 12 }}>
        {/* Evidence sources checklist */}
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
            Evidence Sources
          </div>
          <SourceChecklist profile={profile} />
        </div>

        {/* AI analysis summary (collapsed text) */}
        {profile.workflow_analysis_summary && !showAnalysis && (
          <div style={{ fontSize: 12, color: "#334155", lineHeight: 1.6, padding: "8px 10px", background: "#f0fdf4", borderRadius: 8, border: "1px solid #bbf7d0" }}>
            {profile.workflow_analysis_summary.length > 180
              ? `${profile.workflow_analysis_summary.slice(0, 177)}…`
              : profile.workflow_analysis_summary}
          </div>
        )}

        {/* Missing evidence */}
        {profile.missing_evidence.length > 0 && (
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: "#854d0e", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>
              Missing evidence
            </div>
            <ul style={{ margin: 0, paddingLeft: 16, display: "flex", flexDirection: "column", gap: 2 }}>
              {profile.missing_evidence.slice(0, 3).map((m, i) => (
                <li key={i} style={{ fontSize: 11, color: "#854d0e" }}>{m}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Action buttons */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          {canViewAnalysis && (
            <button
              type="button"
              onClick={() => { void handleViewAnalysis() }}
              disabled={loadingAnalysis}
              style={{
                fontSize: 11,
                fontWeight: 600,
                padding: "6px 12px",
                borderRadius: 8,
                border: "1px solid #bbf7d0",
                background: showAnalysis ? "#dcfce7" : "#f0fdf4",
                color: "#166534",
                cursor: loadingAnalysis ? "default" : "pointer",
                opacity: loadingAnalysis ? 0.7 : 1,
              }}
            >
              {loadingAnalysis ? "Loading…" : showAnalysis ? "Hide Analysis ▲" : "View Analysis ▼"}
            </button>
          )}

          {profile.submission_count > 1 && (
            <button
              type="button"
              onClick={() => setShowHistory((v) => !v)}
              style={{
                fontSize: 11,
                fontWeight: 600,
                padding: "6px 12px",
                borderRadius: 8,
                border: "1px solid #e2e8f0",
                background: "transparent",
                color: "#475569",
                cursor: "pointer",
              }}
            >
              {showHistory ? "Hide Timeline ▲" : "View Timeline ▼"}
            </button>
          )}

          <button
            type="button"
            disabled
            title="GitHub Evidence Analysis — coming soon"
            style={{
              fontSize: 11,
              fontWeight: 600,
              padding: "6px 12px",
              borderRadius: 8,
              border: "1px dashed #e2e8f0",
              background: "transparent",
              color: "#94a3b8",
              cursor: "not-allowed",
            }}
          >
            + Add GitHub Evidence
          </button>
        </div>

        {/* Analysis error */}
        {analysisError && (
          <div style={{ fontSize: 11, color: "#991b1b", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 6, padding: "6px 10px" }}>
            {analysisError}
          </div>
        )}

        {/* Inline analysis */}
        {showAnalysis && analysis && <InlineAnalysisView analysis={analysis} />}

        {/* History timeline */}
        {showHistory && <HistoryTimeline profile={profile} />}
      </div>
    </div>
  )
}
