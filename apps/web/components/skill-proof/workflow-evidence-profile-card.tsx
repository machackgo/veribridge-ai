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

function VisualFrameBadge({
  status,
  provider,
  frameCount,
  framesStored,
}: {
  status: VisualFrameStatus | undefined
  provider?: string
  frameCount?: number
  framesStored?: number
}) {
  const stored = framesStored ?? 0
  const analyzed = frameCount ?? 0

  // Frames were captured by the extension but no OCR/vision provider is configured
  if (status === "not_configured" && stored > 0) {
    return (
      <span
        title="Visual frames were captured. Configure VISUAL_ANALYSIS_PROVIDER to enable OCR/vision analysis."
        style={{
          fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
          background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe",
        }}
      >
        Visual frames: {stored} captured ✓
      </span>
    )
  }
  // No frames and not configured
  if (!status || status === "not_captured" || (status === "not_configured" && stored === 0)) {
    return (
      <span
        title="No visual frames were captured. Extension will capture frames automatically during recording."
        style={{
          fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
          background: "#f1f5f9", color: "#64748b", border: "1px dashed #cbd5e1",
        }}
      >
        Visual frames: not captured
      </span>
    )
  }
  if (status === "analyzed") {
    const label = analyzed > 0 ? `Visual frames: ${analyzed} analyzed ✓` : "Visual frames: analyzed ✓"
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

// ── OCR / vision not-configured badge ─────────────────────────────────────────

function OCRNotConfiguredBadge({ show }: { show: boolean }) {
  if (!show) return null
  return (
    <span
      title="Visual frames were captured but no OCR/vision provider is configured. Set VISUAL_ANALYSIS_PROVIDER=local_ocr (PaddleOCR/EasyOCR) or openai to enable analysis."
      style={{
        fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
        background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a",
      }}
    >
      OCR/vision not configured
    </span>
  )
}

// ── OCR active badge ──────────────────────────────────────────────────────────

function OCRActiveBadge({ status, provider }: { status: string | undefined; provider?: string }) {
  if (status !== "analyzed") return null
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

// ── Combined DOM + visual evidence badge ─────────────────────────────────────

function CombinedEvidenceBadge({ show }: { show: boolean }) {
  if (!show) return null
  return (
    <span
      title="Both DOM text evidence and visual frame analysis are available for this session."
      style={{
        fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
        background: "#fdf4ff", color: "#7e22ce", border: "1px solid #e9d5ff",
      }}
    >
      Combined DOM + visual evidence ✓
    </span>
  )
}

// ── Evidence layer legend (full panel) ───────────────────────────────────────

function EvidenceLayerLegend({
  analysis,
  sessionId,
}: {
  analysis: WorkflowAnalysisResponse
  sessionId?: string
}) {
  const isDev = process.env.NODE_ENV === "development"

  const hasEvents = (analysis.demonstrated_actions?.length ?? 0) > 0
  const domStatus = analysis.dom_evidence_status ?? analysis.visible_evidence_status ?? "not_captured"
  const visualStatus = analysis.visual_analysis_status as VisualFrameStatus | undefined
  const ocrStatus = analysis.ocr_status
  const visualProvider = analysis.visual_analysis_provider
  const visualFrameCount = analysis.visual_frame_count ?? 0
  const visualFramesStored = analysis.visual_frames_stored ?? 0

  const hasDOM = domStatus === "available" || domStatus === "partial"
  const hasVisualAnalyzed = visualStatus === "analyzed" && visualFrameCount > 0
  const hasFramesCaptured = visualFramesStored > 0
  const ocrNotConfigured = hasFramesCaptured && (visualStatus === "not_configured" || visualStatus === "skipped")
  const showCombined = hasDOM && hasVisualAnalyzed

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
        <VisualFrameBadge
          status={visualStatus}
          provider={visualProvider}
          frameCount={visualFrameCount}
          framesStored={visualFramesStored}
        />
      </div>

      {/* Row: OCR/vision not configured (only when frames captured but no provider) */}
      {ocrNotConfigured && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span style={{ fontSize: 10, color: "#64748b", minWidth: 130 }}>OCR/vision</span>
          <OCRNotConfiguredBadge show />
        </div>
      )}

      {/* Row: OCR active (when provider is running) */}
      {ocrStatus === "analyzed" && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span style={{ fontSize: 10, color: "#64748b", minWidth: 130 }}>Local OCR</span>
          <OCRActiveBadge status={ocrStatus} provider={visualProvider} />
        </div>
      )}

      {/* Row: Video keyframes */}
      {(analysis.video_keyframe_status || (analysis.video_keyframe_count ?? 0) > 0) && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <span style={{ fontSize: 10, color: "#64748b", minWidth: 130 }}>Video keyframes</span>
            {analysis.video_keyframe_status === "extracted" ? (
              <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
                background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0" }}>
                {analysis.video_keyframe_count ?? 0} extracted ✓
              </span>
            ) : analysis.video_keyframe_status === "failed" ? (
              <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
                background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca" }}
                title={analysis.video_upload_error ?? "Keyframe extraction failed"}>
                {analysis.video_upload_error
                  ? `Failed: ${analysis.video_upload_error.slice(0, 60)}`
                  : "Keyframe extraction failed"}
              </span>
            ) : (
              <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4,
                background: "#f1f5f9", color: "#94a3b8", border: "1px dashed #cbd5e1" }}>
                {analysis.video_keyframe_status ?? "not captured"}
              </span>
            )}
            {/* Duration badge */}
            {analysis.video_duration_ms != null && analysis.video_duration_ms > 0 && (
              <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4,
                background: "#f1f5f9", color: "#64748b", border: "1px solid #e2e8f0" }}>
                ~{Math.round(analysis.video_duration_ms / 1000)}s
              </span>
            )}
          </div>
          {/* Timestamp strip (collapsed to first 5) */}
          {analysis.video_keyframe_status === "extracted" &&
            (analysis.video_keyframe_timestamps_ms?.length ?? 0) > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4, paddingLeft: 136 }}>
              {(analysis.video_keyframe_timestamps_ms ?? []).slice(0, 5).map((ts, i) => (
                <span key={i} style={{ fontSize: 8, fontFamily: "monospace", padding: "1px 5px",
                  borderRadius: 3, background: "#f0fdf4", color: "#166534",
                  border: "1px solid #bbf7d0" }}>
                  {(ts / 1000).toFixed(1)}s
                </span>
              ))}
              {(analysis.video_keyframe_timestamps_ms?.length ?? 0) > 5 && (
                <span style={{ fontSize: 8, color: "#94a3b8" }}>
                  +{(analysis.video_keyframe_timestamps_ms?.length ?? 0) - 5} more
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Row: Sequence analysis */}
      {analysis.sequence_analysis && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span style={{ fontSize: 10, color: "#64748b", minWidth: 130 }}>Sequence analysis</span>
          {analysis.sequence_analysis.sequence_analysis_status === "completed" ? (
            <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
              background: "#fdf4ff", color: "#7e22ce", border: "1px solid #e9d5ff" }}>
              {analysis.sequence_analysis.analyzed_frame_count} frames · {analysis.sequence_analysis.evidence_strength} ✓
            </span>
          ) : (
            <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4,
              background: "#f1f5f9", color: "#94a3b8", border: "1px dashed #cbd5e1" }}>
              {analysis.sequence_analysis.sequence_analysis_status}
            </span>
          )}
        </div>
      )}

      {/* Row: Combined DOM + visual evidence (best case) */}
      {showCombined && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span style={{ fontSize: 10, color: "#64748b", minWidth: 130 }}>Combined</span>
          <CombinedEvidenceBadge show />
        </div>
      )}

      {/* Privacy note */}
      <div style={{ marginTop: 4, fontSize: 9, color: "#94a3b8", fontStyle: "italic", lineHeight: 1.4 }}>
        Visual frame analysis uses local/open-source providers when configured.
        No external vision API is required for the local pipeline.
      </div>

      {/* Dev-only debug panel */}
      {isDev && (
        <details style={{ marginTop: 6 }}>
          <summary style={{ fontSize: 9, color: "#64748b", cursor: "pointer", fontWeight: 600 }}>
            🛠 Dev debug
          </summary>
          <div style={{ marginTop: 4, fontSize: 9, color: "#64748b", lineHeight: 1.6, fontFamily: "monospace" }}>
            <div>analysis.proof_session_id: <b>{analysis.proof_session_id ?? "(none)"}</b></div>
            {sessionId && <div>current session_id: <b>{sessionId}</b></div>}
            <div>dom_evidence_status: <b>{domStatus}</b></div>
            <div>visual_analysis_status: <b>{visualStatus ?? "(none)"}</b></div>
            <div>visual_frames_stored: <b>{visualFramesStored}</b></div>
            <div>visual_frame_count (analyzed): <b>{visualFrameCount}</b></div>
            <div>visual_analysis_provider: <b>{visualProvider ?? "none"}</b></div>
            <div>ocr_status: <b>{ocrStatus ?? "none"}</b></div>
            <div>video_keyframe_status: <b>{analysis.video_keyframe_status ?? "none"}</b></div>
            <div>video_keyframe_count: <b>{analysis.video_keyframe_count ?? 0}</b></div>
            <div>sequence_analysis_status: <b>{analysis.sequence_analysis?.sequence_analysis_status ?? "none"}</b></div>
            <div>sequence_confidence_score: <b>{analysis.sequence_analysis?.confidence_score ?? "n/a"}</b></div>
          </div>
        </details>
      )}
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

function ObservedDemonstrationTimeline({
  demo,
  videoKeyframeStatus,
  videoKeyframeCount,
}: {
  demo: ObservedDemonstration
  videoKeyframeStatus?: string | null
  videoKeyframeCount?: number | null
}) {
  const visStatus = demo.visible_evidence_status ?? "not_captured"
  const hasVideoKeyframes = videoKeyframeStatus === "extracted" && (videoKeyframeCount ?? 0) > 0

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
        {/* Only show "Frame/OCR unavailable" when there's no video evidence either */}
        {visStatus === "not_captured" && !hasVideoKeyframes && (
          <span style={{ fontSize: 9, color: "#94a3b8", fontStyle: "italic" }}>
            · Frame/OCR unavailable
          </span>
        )}
        {visStatus === "not_captured" && hasVideoKeyframes && (
          <span style={{ fontSize: 9, color: "#166534", background: "#f0fdf4",
            border: "1px solid #bbf7d0", borderRadius: 3, padding: "1px 5px", fontWeight: 600 }}>
            · {videoKeyframeCount} video keyframe{(videoKeyframeCount ?? 0) !== 1 ? "s" : ""} captured
          </span>
        )}
      </div>

      {/* Summary */}
      <div style={{ fontSize: 11, color: "#334155", lineHeight: 1.6, padding: "8px 10px",
        background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8 }}>
        {demo.summary}
      </div>

      {/* Not captured notice — different message depending on video evidence */}
      {visStatus === "not_captured" && (
        <div style={{ fontSize: 11, borderRadius: 6, padding: "6px 10px",
          ...(hasVideoKeyframes
            ? { color: "#0369a1", background: "#e0f2fe", border: "1px solid #bae6fd" }
            : { color: "#92400e", background: "#fef9c3", border: "1px solid #fef08a" })
        }}>
          {hasVideoKeyframes ? (
            <>
              Video was recorded and {videoKeyframeCount} keyframe{(videoKeyframeCount ?? 0) !== 1 ? "s" : ""} extracted.{" "}
              DOM text evidence was not captured — analysis is based on recording metadata,
              browser events, and video keyframe evidence.
            </>
          ) : (
            <>
              Exact output values were not captured. VeriBridge only observed browser events
              for this recording. Use a new recording to capture visible page evidence.
            </>
          )}
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

// ── Frame OCR Evidence Sub-section ───────────────────────────────────────────

type FrameOCRSummary = NonNullable<WorkflowAnalysisResponse["frame_ocr_evidence_summary"]>

function FrameOCREvidenceSubsection({
  ocr,
  keyframeTimestamps,
}: {
  ocr: FrameOCRSummary
  keyframeTimestamps: number[]
}) {
  if (!ocr.has_ocr_evidence) return null

  const snippets = ocr.top_ocr_snippets ?? []
  const signals  = ocr.skill_signals ?? []
  const missing  = ocr.what_was_not_observed ?? []

  const partialSkills = signals.filter((s) => s.ocr_support === "partial")
  const weakSkills    = signals.filter((s) => s.ocr_support === "insufficient")

  const pageContextLabel: Record<string, string> = {
    homepage_marketing: "Homepage / platform marketing content",
    training_ui: "Training UI content",
    prediction_output: "Prediction / output content",
    demo_content: "Demo / tutorial content",
    unknown: "Unknown (minimal text detected)",
  }

  return (
    <div style={{
      marginTop: 6,
      padding: "10px 12px",
      background: "#eff6ff",
      border: "1px solid #bfdbfe",
      borderRadius: 7,
      display: "flex",
      flexDirection: "column",
      gap: 8,
    }}>
      <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: "0.09em",
        textTransform: "uppercase", color: "#1d4ed8" }}>
        Frame OCR Evidence
      </div>

      {/* Provider + counts */}
      <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: "3px 8px", fontSize: 11 }}>
        <span style={{ color: "#64748b" }}>Provider</span>
        <span style={{ color: "#1e40af", fontWeight: 600, fontFamily: "monospace" }}>{ocr.ocr_provider}</span>

        <span style={{ color: "#64748b" }}>Frames analyzed</span>
        <span style={{ color: "#1e40af", fontWeight: 600 }}>{ocr.frames_analyzed}</span>

        <span style={{ color: "#64748b" }}>Page context</span>
        <span style={{ color: "#334155" }}>
          {pageContextLabel[ocr.detected_page_context] ?? ocr.detected_page_context}
        </span>
      </div>

      {/* What the video appears to show */}
      {ocr.observed_summary && (
        <div style={{ fontSize: 11, color: "#1e293b", lineHeight: 1.5,
          padding: "6px 8px", background: "#dbeafe", borderRadius: 5,
          border: "1px solid #93c5fd" }}>
          <strong style={{ color: "#1d4ed8" }}>What the video appears to show: </strong>
          {ocr.observed_summary}
        </div>
      )}

      {/* Top OCR snippets with approximate timestamps */}
      {snippets.length > 0 && (
        <div>
          <div style={{ fontSize: 9, fontWeight: 700, color: "#1d4ed8",
            textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
            Top OCR text snippets from keyframes
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {snippets.map((text, i) => {
              const tsMs = keyframeTimestamps[Math.min(i, keyframeTimestamps.length - 1)]
              const tsLabel = tsMs != null ? `${(tsMs / 1000).toFixed(1)}s` : null
              return (
                <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 6 }}>
                  {tsLabel && (
                    <span style={{ fontSize: 8, fontFamily: "monospace", padding: "1px 5px",
                      borderRadius: 3, background: "#dbeafe", color: "#1d4ed8",
                      border: "1px solid #93c5fd", flexShrink: 0, marginTop: 2 }}>
                      {tsLabel}
                    </span>
                  )}
                  <span style={{ fontSize: 10, color: "#334155", fontFamily: "monospace",
                    background: "#f8fafc", padding: "1px 6px", borderRadius: 3,
                    border: "1px solid #e2e8f0", lineHeight: 1.4 }}>
                    {text}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* OCR-supported skill signals (partial) */}
      {partialSkills.length > 0 && (
        <div>
          <div style={{ fontSize: 9, fontWeight: 700, color: "#166534",
            textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
            OCR-supported signals (partial)
          </div>
          {partialSkills.map((sig, i) => (
            <div key={i} style={{ fontSize: 10, color: "#166534", lineHeight: 1.4,
              padding: "4px 7px", background: "#f0fdf4", borderRadius: 4,
              border: "1px solid #bbf7d0", marginBottom: 3 }}>
              <strong>{sig.skill}:</strong>{" "}{sig.reasoning}
              {sig.ocr_terms_found.length > 0 && (
                <span style={{ color: "#64748b" }}>
                  {" "}(terms: {sig.ocr_terms_found.slice(0, 5).join(", ")})
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Insufficient OCR signals */}
      {weakSkills.length > 0 && (
        <div>
          <div style={{ fontSize: 9, fontWeight: 700, color: "#92400e",
            textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
            Insufficient OCR evidence
          </div>
          {weakSkills.map((sig, i) => (
            <div key={i} style={{ fontSize: 10, color: "#92400e", lineHeight: 1.4,
              padding: "4px 7px", background: "#fef9c3", borderRadius: 4,
              border: "1px solid #fef08a", marginBottom: 3 }}>
              <strong>{sig.skill}:</strong>{" "}{sig.reasoning}
            </div>
          ))}
        </div>
      )}

      {/* What was not observed / proof still missing */}
      {missing.length > 0 && (
        <div>
          <div style={{ fontSize: 9, fontWeight: 700, color: "#991b1b",
            textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
            Proof still missing from frames
          </div>
          <ul style={{ margin: 0, padding: "0 0 0 14px", display: "flex",
            flexDirection: "column", gap: 2 }}>
            {missing.map((item, i) => (
              <li key={i} style={{ fontSize: 10, color: "#7f1d1d", lineHeight: 1.4 }}>{item}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// ── Advanced Visual Reasoning Section (v7) ───────────────────────────────────
// Shows structured Qwen2.5-VL / Qwen3-VL reasoning when enabled.
// Hidden cleanly when reasoning is disabled (VISUAL_REASONING_ENABLED=false).

type VisualReasoningSummary = NonNullable<WorkflowAnalysisResponse["visual_reasoning_summary"]>

function AdvancedVisualReasoningSection({
  reasoning,
}: {
  reasoning: VisualReasoningSummary | null | undefined
}) {
  // null = reasoning not run for this session (disabled, or analysis stored before video upload)
  // Show nothing — the OCR / keyframe section already covers it.
  if (!reasoning) return null

  const isAnalyzed  = reasoning.status === "analyzed"
  const isPending   = reasoning.status === "pending"
  const isMissing   = reasoning.status === "missing_dependency"
  const isDisabled  = reasoning.status === "disabled" || reasoning.status === "not_configured"
  const isFailed    = reasoning.status === "failed"
  const isRejected  = reasoning.status === "rejected_inconsistent" || reasoning.status === "rejected_stale"

  // Qwen enabled and configured but not yet run for this session
  if (isPending) {
    return (
      <div style={{ marginTop: 6, padding: "8px 10px", background: "#fffbeb",
        border: "1px solid #fef08a", borderRadius: 6, fontSize: 10, color: "#78350f" }}>
        <strong>Qwen Visual Reasoning — processing</strong>
        <div style={{ marginTop: 3, lineHeight: 1.5 }}>
          Qwen visual reasoning is enabled and running. Refresh after analysis completes.
        </div>
      </div>
    )
  }

  // Minimal note when explicitly disabled (VISUAL_REASONING_ENABLED=false stored in dict)
  if (isDisabled) {
    return (
      <div style={{ fontSize: 10, color: "#6b7280", fontStyle: "italic", marginTop: 4 }}>
        Advanced visual reasoning (Qwen-VL) is not enabled for this session. OCR analysis was used.
      </div>
    )
  }

  // Installation note when packages missing
  if (isMissing) {
    return (
      <div style={{ marginTop: 6, padding: "8px 10px", background: "#fefce8",
        border: "1px solid #fef08a", borderRadius: 6, fontSize: 10, color: "#78350f" }}>
        <strong>Advanced Visual Reasoning — missing dependency:</strong>{" "}
        Install Qwen-VL packages to enable structured visual skill analysis.
        <br />
        <code style={{ fontSize: 9, fontFamily: "monospace" }}>
          pip install &quot;transformers&gt;=4.45&quot; torch pillow accelerate
        </code>
      </div>
    )
  }

  // Rejection: Qwen output was inconsistent with session context
  if (isRejected) {
    return (
      <div style={{
        marginTop: 6,
        padding: "8px 10px",
        background: "#fef2f2",
        border: "1px solid #fca5a5",
        borderRadius: 6,
        fontSize: 10,
        color: "#7f1d1d",
      }}>
        <strong style={{ color: "#991b1b" }}>Advanced Visual Reasoning — rejected</strong>
        <div style={{ marginTop: 4, lineHeight: 1.5 }}>
          Qwen visual reasoning was rejected because it did not match the current
          recording evidence.
        </div>
        <div style={{ marginTop: 3, color: "#6b7280", fontStyle: "italic" }}>
          Fallback used: DOM / OCR / sequence evidence.
        </div>
      </div>
    )
  }

  const observations = reasoning.observations ?? []
  const signals      = reasoning.supported_signals ?? []
  const missing      = reasoning.missing_claims ?? []
  const limitations  = reasoning.limitations ?? []

  return (
    <div style={{
      marginTop: 6,
      padding: "10px 12px",
      background: "#f5f3ff",
      border: "1px solid #c4b5fd",
      borderRadius: 7,
      display: "flex",
      flexDirection: "column",
      gap: 8,
    }}>
      {/* Header */}
      <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: "0.09em",
        textTransform: "uppercase", color: "#6d28d9" }}>
        Advanced Visual Reasoning
      </div>

      {/* Provider + counts */}
      <div style={{ display: "grid", gridTemplateColumns: "130px 1fr", gap: "3px 8px", fontSize: 11 }}>
        <span style={{ color: "#64748b" }}>Provider</span>
        <span style={{ color: "#5b21b6", fontWeight: 600, fontFamily: "monospace" }}>
          {reasoning.provider || "qwen_vl"}
        </span>

        <span style={{ color: "#64748b" }}>Status</span>
        <span style={{ color: isFailed ? "#b91c1c" : "#166534", fontWeight: 600 }}>
          {isFailed ? "failed" : reasoning.status}
        </span>

        <span style={{ color: "#64748b" }}>Frames analyzed</span>
        <span style={{ color: "#1e40af", fontWeight: 600 }}>{reasoning.frames_analyzed}</span>
      </div>

      {/* Combined visual summary */}
      {reasoning.summary && (
        <div style={{ fontSize: 11, color: "#1e293b", lineHeight: 1.5,
          padding: "6px 8px", background: "#ede9fe", borderRadius: 5,
          border: "1px solid #c4b5fd" }}>
          <strong style={{ color: "#6d28d9" }}>What the model observed: </strong>
          {reasoning.summary}
        </div>
      )}

      {/* Per-frame observations (collapsed by default — show first 2) */}
      {observations.length > 0 && (
        <div>
          <div style={{ fontSize: 9, fontWeight: 700, color: "#6d28d9",
            textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
            Frame-level observations
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            {observations.slice(0, 3).map((obs, i) => {
              const tsLabel = obs.timestamp_ms != null
                ? `${(obs.timestamp_ms / 1000).toFixed(1)}s`
                : null
              return (
                <div key={i} style={{ padding: "6px 8px", background: "#f3f4f6",
                  borderRadius: 5, border: "1px solid #e5e7eb" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6,
                    marginBottom: 3 }}>
                    {tsLabel && (
                      <span style={{ fontSize: 8, fontFamily: "monospace",
                        padding: "1px 5px", borderRadius: 3, background: "#ede9fe",
                        color: "#6d28d9", border: "1px solid #c4b5fd" }}>
                        {tsLabel}
                      </span>
                    )}
                    <span style={{ fontSize: 9, fontWeight: 600, color: "#374151" }}>
                      {obs.detected_workflow_stage !== "unknown"
                        ? obs.detected_workflow_stage.replace(/_/g, " ")
                        : "unknown stage"}
                    </span>
                    <span style={{ fontSize: 9, color: "#9ca3af" }}>
                      confidence: {(obs.confidence_score * 100).toFixed(0)}%
                    </span>
                  </div>
                  {obs.visual_summary && (
                    <div style={{ fontSize: 10, color: "#374151", lineHeight: 1.4 }}>
                      {obs.visual_summary}
                    </div>
                  )}
                  {obs.detected_outputs && obs.detected_outputs.length > 0 && (
                    <div style={{ marginTop: 3, display: "flex", flexWrap: "wrap", gap: 3 }}>
                      {obs.detected_outputs.slice(0, 4).map((out, j) => (
                        <span key={j} style={{ fontSize: 9, padding: "1px 6px",
                          background: "#dcfce7", color: "#166534",
                          borderRadius: 3, border: "1px solid #bbf7d0",
                          fontFamily: "monospace" }}>
                          {out}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
            {observations.length > 3 && (
              <div style={{ fontSize: 9, color: "#6b7280", fontStyle: "italic" }}>
                +{observations.length - 3} more frame observations
              </div>
            )}
          </div>
        </div>
      )}

      {/* Skill signals found */}
      {signals.length > 0 && (
        <div>
          <div style={{ fontSize: 9, fontWeight: 700, color: "#166534",
            textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
            Skill signals found
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {signals.map((sig, i) => (
              <span key={i} style={{ fontSize: 10, padding: "2px 8px",
                background: "#dcfce7", color: "#166534", borderRadius: 12,
                border: "1px solid #bbf7d0", fontWeight: 500 }}>
                ✓ {sig}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Missing / unclear proof */}
      {missing.length > 0 && (
        <div>
          <div style={{ fontSize: 9, fontWeight: 700, color: "#92400e",
            textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
            Missing or unclear evidence
          </div>
          <ul style={{ margin: 0, padding: "0 0 0 14px",
            display: "flex", flexDirection: "column", gap: 2 }}>
            {missing.slice(0, 5).map((item, i) => (
              <li key={i} style={{ fontSize: 10, color: "#78350f", lineHeight: 1.4 }}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Skill Evidence Timeline */}
      {reasoning.skill_timeline && reasoning.skill_timeline.length > 0 && (
        <SkillEvidenceTimeline timeline={reasoning.skill_timeline} />
      )}

      {/* Limitations */}
      {limitations.length > 0 && (
        <div style={{ fontSize: 9, color: "#6b7280", fontStyle: "italic",
          borderTop: "1px solid #e9d5ff", paddingTop: 4 }}>
          <strong>Limitations:</strong> {limitations.slice(0, 2).join(" · ")}
        </div>
      )}
    </div>
  )
}

// ── Skill Evidence Timeline ───────────────────────────────────────────────────

type SkillTimelineEntry = NonNullable<
  NonNullable<WorkflowAnalysisResponse["visual_reasoning_summary"]>["skill_timeline"]
>[number]

const SUPPORT_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  supported: { bg: "#dcfce7", border: "#86efac", text: "#166534" },
  partial:   { bg: "#fef9c3", border: "#fde047", text: "#854d0e" },
  missing:   { bg: "#fee2e2", border: "#fca5a5", text: "#991b1b" },
  unclear:   { bg: "#f3f4f6", border: "#d1d5db", text: "#374151" },
}

const SOURCE_BADGE_COLORS: Record<string, { bg: string; text: string }> = {
  Qwen:    { bg: "#ede9fe", text: "#6d28d9" },
  OCR:     { bg: "#dbeafe", text: "#1e40af" },
  DOM:     { bg: "#dcfce7", text: "#166534" },
  fusion:  { bg: "#fef3c7", text: "#92400e" },
}

// ── Skill Evidence Timeline (compact, readable) ───────────────────────────────

const MAX_TIMELINE_SHOWN = 8

function supportIcon(level: string): string {
  if (level === "supported") return "✓"
  if (level === "partial")   return "~"
  if (level === "unclear")   return "?"
  return "✗"
}

function SkillEvidenceTimeline({ timeline }: { timeline: SkillTimelineEntry[] }) {
  if (!timeline || timeline.length === 0) return null

  // Deduplicate by (detected_skill, evidence_source, support_level)
  // keeping the highest-confidence entry per skill+source
  const bestByKey = new Map<string, SkillTimelineEntry>()
  for (const entry of timeline) {
    const key = `${entry.detected_skill}|${entry.evidence_source}`
    const existing = bestByKey.get(key)
    if (!existing || (entry.confidence ?? 0) > (existing.confidence ?? 0)) {
      bestByKey.set(key, entry)
    }
  }

  // Sort by confidence descending, take top MAX_TIMELINE_SHOWN
  const sorted = [...bestByKey.values()].sort(
    (a, b) => (b.confidence ?? 0) - (a.confidence ?? 0)
  )
  const shown = sorted.slice(0, MAX_TIMELINE_SHOWN)
  const remaining = sorted.length - shown.length

  return (
    <div style={{ marginTop: 4 }}>
      <div style={{
        fontSize: 9, fontWeight: 800, color: "#6d28d9",
        textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6,
      }}>
        Skill Evidence Timeline
      </div>

      {/* Header row */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "40px 1fr 52px 46px 36px",
        gap: "0 6px",
        fontSize: 8, fontWeight: 700, color: "#94a3b8",
        textTransform: "uppercase", letterSpacing: "0.06em",
        padding: "2px 6px", marginBottom: 3,
      }}>
        <span>Time</span>
        <span>Skill</span>
        <span>Source</span>
        <span>Level</span>
        <span style={{ textAlign: "right" }}>Conf.</span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {shown.map((entry, i) => {
          const colors   = SUPPORT_COLORS[entry.support_level] ?? SUPPORT_COLORS.unclear
          const srcColor = SOURCE_BADGE_COLORS[entry.evidence_source] ?? { bg: "#f3f4f6", text: "#374151" }
          const confPct  = Math.round((entry.confidence ?? 0) * 100)
          return (
            <div key={i} style={{
              display: "grid",
              gridTemplateColumns: "40px 1fr 52px 46px 36px",
              gap: "0 6px",
              alignItems: "center",
              padding: "4px 6px",
              borderRadius: 5,
              background: colors.bg,
              border: `1px solid ${colors.border}`,
            }}>
              {/* Timestamp */}
              <span style={{
                fontSize: 8, fontFamily: "monospace", fontWeight: 700,
                color: "#6d28d9", whiteSpace: "nowrap",
              }}>
                {entry.timestamp_label ?? "?"}
              </span>

              {/* Skill + evidence text */}
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: colors.text, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {entry.detected_skill}
                </div>
                {entry.evidence_text && (
                  <div style={{ fontSize: 8, color: colors.text, opacity: 0.8, marginTop: 1,
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
                    title={entry.evidence_text}>
                    {entry.evidence_text.slice(0, 80)}
                  </div>
                )}
                {entry.reason && entry.reason !== entry.evidence_text && (
                  <div style={{ fontSize: 8, color: "#6b7280", marginTop: 1,
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
                    title={entry.reason}>
                    {entry.reason.slice(0, 60)}
                  </div>
                )}
              </div>

              {/* Source badge */}
              <span style={{
                fontSize: 8, padding: "1px 5px", borderRadius: 10,
                background: srcColor.bg, color: srcColor.text,
                fontWeight: 700, textAlign: "center", whiteSpace: "nowrap",
              }}>
                {entry.evidence_source}
              </span>

              {/* Support level */}
              <span style={{
                fontSize: 8, fontWeight: 700, color: colors.text,
                textAlign: "center", whiteSpace: "nowrap",
              }}>
                {supportIcon(entry.support_level)} {entry.support_level}
              </span>

              {/* Confidence */}
              <span style={{
                fontSize: 9, fontWeight: 700,
                color: confPct >= 70 ? "#166534" : confPct >= 45 ? "#92400e" : "#6b7280",
                textAlign: "right",
              }}>
                {confPct}%
              </span>
            </div>
          )
        })}
      </div>

      {remaining > 0 && (
        <div style={{ fontSize: 8, color: "#6b7280", fontStyle: "italic", marginTop: 4, paddingLeft: 4 }}>
          +{remaining} more entries (showing top {MAX_TIMELINE_SHOWN} by confidence)
        </div>
      )}
    </div>
  )
}

// ── Video / Keyframe Evidence Section ────────────────────────────────────────
// Always renders — shows "no video" state or full video metadata.

function VideoKeyframeEvidenceSection({ analysis }: { analysis: WorkflowAnalysisResponse }) {
  const kfStatus   = analysis.video_keyframe_status
  const kfCount    = analysis.video_keyframe_count ?? 0
  const kfTs       = analysis.video_keyframe_timestamps_ms ?? []
  const durationMs = analysis.video_duration_ms
  const uploaded   = kfStatus === "extracted" || kfStatus === "not_available"
  const visualStatus = analysis.visual_analysis_status
  const ocrSummary   = analysis.frame_ocr_evidence_summary ?? null
  const hasOCREvidence = ocrSummary?.has_ocr_evidence === true

  // No video was uploaded for this session
  if (!kfStatus && kfCount === 0) {
    return (
      <div style={{
        background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8,
        padding: "10px 12px", display: "flex", flexDirection: "column", gap: 6,
      }}>
        <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: "0.09em",
          textTransform: "uppercase", color: "#64748b", marginBottom: 2 }}>
          Video / Keyframe Evidence
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: "4px 8px", fontSize: 11 }}>
          <span style={{ color: "#64748b" }}>Recording captured</span>
          <span style={{ color: "#94a3b8" }}>No video recorded</span>
          <span style={{ color: "#64748b" }}>Uploaded to backend</span>
          <span style={{ color: "#94a3b8" }}>No</span>
          <span style={{ color: "#64748b" }}>OCR/visual analysis</span>
          <span style={{ color: "#92400e", fontSize: 10 }}>
            Not configured — set VISUAL_ANALYSIS_PROVIDER=local_ocr or local_vision
          </span>
        </div>
        <div style={{ fontSize: 10, color: "#64748b", lineHeight: 1.5,
          padding: "6px 8px", background: "#fef9c3", border: "1px solid #fef08a", borderRadius: 6 }}>
          To add video evidence: in the recorder tab click{" "}
          <strong>Stop &amp; Upload Video</strong> before Stop &amp; Send.<br />
          Visual analysis not configured. Start backend with{" "}
          <code style={{ fontFamily: "monospace", fontSize: 9 }}>VISUAL_ANALYSIS_PROVIDER=local_ocr</code>{" "}
          or <code style={{ fontFamily: "monospace", fontSize: 9 }}>local_vision</code>.
        </div>
      </div>
    )
  }

  const isConfigured =
    visualStatus && !["not_configured", "not_available", "not_captured"].includes(visualStatus)

  return (
    <div style={{
      background: "#f0fdf4",
      border: "1px solid #bbf7d0",
      borderRadius: 8,
      padding: "10px 12px",
      display: "flex",
      flexDirection: "column",
      gap: 6,
    }}>
      <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: "0.09em",
        textTransform: "uppercase", color: "#166534", marginBottom: 2 }}>
        Video / Keyframe Evidence
      </div>

      {/* Status grid */}
      <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: "4px 8px", fontSize: 11 }}>
        <span style={{ color: "#64748b" }}>Recording captured</span>
        <span style={{ color: "#166534", fontWeight: 600 }}>Yes ✓</span>

        <span style={{ color: "#64748b" }}>Uploaded to backend</span>
        <span style={{ color: uploaded ? "#166534" : "#94a3b8", fontWeight: 600 }}>
          {uploaded ? "Yes ✓" : "No"}
        </span>

        <span style={{ color: "#64748b" }}>Keyframes extracted</span>
        {kfStatus === "extracted" ? (
          <span style={{ color: "#166534", fontWeight: 600 }}>Yes — {kfCount} frame{kfCount !== 1 ? "s" : ""} ✓</span>
        ) : kfStatus === "not_available" ? (
          <span style={{ color: "#92400e", fontSize: 10 }}>
            {analysis.video_upload_error ?? "opencv-python-headless or ffmpeg not installed"}
          </span>
        ) : kfStatus === "failed" ? (
          <span style={{ color: "#991b1b", fontWeight: 600 }}>
            Failed: {(analysis.video_upload_error ?? "extraction error").slice(0, 80)}
          </span>
        ) : (
          <span style={{ color: "#94a3b8" }}>Pending</span>
        )}

        {durationMs != null && durationMs > 0 && (
          <>
            <span style={{ color: "#64748b" }}>Video duration</span>
            <span style={{ color: "#334155" }}>~{Math.round(durationMs / 1000)}s</span>
          </>
        )}

        <span style={{ color: "#64748b" }}>OCR/vision provider</span>
        {isConfigured ? (
          <span style={{ color: "#166534", fontWeight: 600 }}>Configured — {visualStatus}</span>
        ) : (
          <span style={{ color: "#92400e" }}>
            Not configured — set VISUAL_ANALYSIS_PROVIDER to enable
          </span>
        )}

        {/* OCR analysis row — only when summary is available */}
        {ocrSummary && (
          <>
            <span style={{ color: "#64748b" }}>OCR/visual analysis</span>
            {hasOCREvidence ? (
              <span style={{ color: "#1d4ed8", fontWeight: 600 }}>
                Analyzed — {ocrSummary.frames_analyzed} frame{ocrSummary.frames_analyzed !== 1 ? "s" : ""} ✓
              </span>
            ) : (
              <span style={{ color: "#92400e", fontSize: 10 }}>
                {ocrSummary.observed_summary?.slice(0, 100) ?? "Not available"}
              </span>
            )}
          </>
        )}
      </div>

      {/* Keyframe timestamps */}
      {kfStatus === "extracted" && kfTs.length > 0 && (
        <div>
          <div style={{ fontSize: 9, fontWeight: 700, color: "#166534",
            textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 3 }}>
            Keyframe timestamps
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {kfTs.slice(0, 10).map((ts, i) => (
              <span key={i} style={{ fontSize: 9, fontFamily: "monospace",
                padding: "1px 6px", borderRadius: 3,
                background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }}>
                {(ts / 1000).toFixed(1)}s
              </span>
            ))}
            {kfTs.length > 10 && (
              <span style={{ fontSize: 9, color: "#64748b" }}>+{kfTs.length - 10} more</span>
            )}
          </div>
        </div>
      )}

      {/* Frame OCR Evidence sub-section — shown when OCR produced evidence */}
      {ocrSummary && hasOCREvidence && (
        <FrameOCREvidenceSubsection ocr={ocrSummary} keyframeTimestamps={kfTs} />
      )}

      {/* Advanced Visual Reasoning section (v7) — Qwen2.5-VL / Qwen3-VL */}
      {/* Renders only when reasoning data is present (status in summary dict). */}
      {/* null = reasoning not run / disabled for this session → section hidden. */}
      {analysis.visual_reasoning_summary != null && (
        <AdvancedVisualReasoningSection
          reasoning={analysis.visual_reasoning_summary}
        />
      )}

      {/* Developer-safe notice when OCR not configured */}
      {!isConfigured && (kfStatus === "extracted" || kfStatus === "not_available") && !hasOCREvidence && (
        <div style={{ fontSize: 10, color: "#92400e", lineHeight: 1.5,
          padding: "6px 8px", background: "#fef9c3",
          border: "1px solid #fef08a", borderRadius: 6 }}>
          <strong>Visual analysis not configured.</strong> Start backend with{" "}
          <code style={{ fontFamily: "monospace", fontSize: 9 }}>VISUAL_ANALYSIS_PROVIDER=local_ocr</code>{" "}
          or <code style={{ fontFamily: "monospace", fontSize: 9 }}>local_vision</code>.
          Qwen visual reasoning:{" "}
          <code style={{ fontFamily: "monospace", fontSize: 9 }}>VISUAL_REASONING_ENABLED=true LOCAL_VISION_PROVIDER=qwen_vl</code>.
        </div>
      )}
    </div>
  )
}

// ── Skill-by-Skill Evidence (Part C) ─────────────────────────────────────────

type SkillStatus = "strong" | "partial" | "missing"

function skillStatusStyle(s: SkillStatus): { bg: string; border: string; text: string; label: string } {
  if (s === "strong")  return { bg: "#f0fdf4", border: "#bbf7d0", text: "#166534", label: "supports" }
  if (s === "partial") return { bg: "#fef9c3", border: "#fef08a", text: "#854d0e", label: "partially supports" }
  return { bg: "#fef2f2", border: "#fecaca", text: "#991b1b", label: "not enough evidence" }
}

function deriveSkillEvidenceSources(
  skill: string,
  analysis: WorkflowAnalysisResponse
): { found: string[]; missing: string[]; recommendation: string } {
  const found: string[] = []
  const missing: string[] = []

  // DOM / workflow evidence
  const steps = analysis.observed_demonstration?.steps ?? []
  const hasStepEvidence = steps.some(s =>
    s.skill_evidence?.some(se => se.skill === skill && (se.support_level === "strong" || se.support_level === "partial"))
  )
  if (hasStepEvidence) {
    found.push("DOM / workflow events")
  } else if ((analysis.demonstrated_actions?.length ?? 0) > 0) {
    found.push("Browser events captured")
  }

  // OCR evidence
  const ocrSkill = analysis.frame_ocr_evidence_summary?.skill_signals?.find(s => s.skill === skill)
  if (ocrSkill) {
    if (ocrSkill.ocr_support === "partial") found.push(`OCR: ${ocrSkill.reasoning.slice(0, 60)}`)
    else missing.push("OCR/visual analysis insufficient")
  }

  // Qwen evidence
  const qwenTimeline = analysis.visual_reasoning_summary?.skill_timeline ?? []
  const qwenEntry = qwenTimeline.find(e => e.detected_skill === skill)
  if (qwenEntry) {
    if (qwenEntry.support_level === "supported" || qwenEntry.support_level === "partial") {
      found.push(`Qwen visual: ${qwenEntry.evidence_text.slice(0, 60)}`)
    } else {
      missing.push(`Qwen: ${qwenEntry.reason.slice(0, 60)}`)
    }
  }

  // GitHub evidence
  if ((analysis.supporting_evidence_count ?? 0) > 0) {
    found.push("GitHub repository accessed")
  } else {
    missing.push("No GitHub repository evidence")
  }

  // Video evidence
  if (analysis.video_keyframe_status === "extracted") {
    found.push(`Video: ${analysis.video_keyframe_count} keyframe${analysis.video_keyframe_count !== 1 ? "s" : ""} extracted`)
  } else if (!analysis.video_keyframe_status) {
    missing.push("No video recording")
  }

  // Derive recommendation from student_improvement_suggestions
  const allSuggestions = analysis.student_improvement_suggestions ?? []
  const skillLower = skill.toLowerCase()
  const matchedSuggestion = allSuggestions.find(s =>
    s.toLowerCase().includes(skillLower) ||
    s.toLowerCase().includes(skillLower.split(" ")[0] ?? "")
  )
  const recommendation = matchedSuggestion ?? `Record a focused follow-up showing ${skill} clearly.`

  return { found, missing, recommendation }
}

function SkillBySkillEvidence({ analysis }: { analysis: WorkflowAnalysisResponse }) {
  const allSkills: Array<{ skill: string; status: SkillStatus }> = [
    ...(analysis.supported_skills ?? []).map(s => ({ skill: s, status: "strong" as const })),
    ...(analysis.weakly_supported_skills ?? []).map(s => ({ skill: s, status: "partial" as const })),
    ...(analysis.unsupported_skills ?? []).map(s => ({ skill: s, status: "missing" as const })),
  ]
  if (allSkills.length === 0) return null

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: "0.09em",
        textTransform: "uppercase", color: "#475569" }}>
        Skill-by-Skill Evidence
      </div>
      {allSkills.map(({ skill, status }) => {
        const st = skillStatusStyle(status)
        const { found, missing, recommendation } = deriveSkillEvidenceSources(skill, analysis)
        return (
          <div key={skill} style={{ padding: "10px 12px", background: st.bg,
            border: `1px solid ${st.border}`, borderRadius: 8,
            display: "flex", flexDirection: "column", gap: 5 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: st.text }}>{skill}</span>
              <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 7px",
                borderRadius: 999, background: st.border, color: st.text }}>
                {st.label}
              </span>
            </div>
            {found.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <div style={{ fontSize: 9, fontWeight: 700, color: "#166534",
                  textTransform: "uppercase", letterSpacing: "0.06em" }}>Evidence found</div>
                {found.map((e, i) => (
                  <div key={i} style={{ fontSize: 10, color: "#166534", lineHeight: 1.4 }}>
                    ✓ {e}
                  </div>
                ))}
              </div>
            )}
            {missing.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <div style={{ fontSize: 9, fontWeight: 700, color: "#92400e",
                  textTransform: "uppercase", letterSpacing: "0.06em" }}>Missing evidence</div>
                {missing.slice(0, 2).map((m, i) => (
                  <div key={i} style={{ fontSize: 10, color: "#92400e", lineHeight: 1.4 }}>
                    · {m}
                  </div>
                ))}
              </div>
            )}
            {status !== "strong" && (
              <div style={{ fontSize: 9, color: "#64748b", fontStyle: "italic",
                borderTop: `1px solid ${st.border}`, paddingTop: 4, marginTop: 2 }}>
                <strong style={{ fontStyle: "normal" }}>Recommendation:</strong> {recommendation}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── Proof Completeness Checklist (Part D) ─────────────────────────────────────

type CheckStatus = "pass" | "partial" | "missing"

function checkIcon(s: CheckStatus) {
  if (s === "pass")    return { icon: "✓", bg: "#f0fdf4", border: "#bbf7d0", text: "#166534" }
  if (s === "partial") return { icon: "~", bg: "#fef9c3", border: "#fef08a", text: "#854d0e" }
  return { icon: "✗", bg: "#f8fafc", border: "#e2e8f0", text: "#94a3b8" }
}

function ProofCompletenessChecklist({ analysis }: { analysis: WorkflowAnalysisResponse }) {
  const steps = analysis.observed_demonstration?.steps ?? []
  const hasResultValues = steps.some(s => (s.detected_result_values?.length ?? 0) > 0)
  const hasVisibleText  = steps.some(s => (s.visible_text_evidence?.length ?? 0) > 0)
  const hasInteraction  = (analysis.demonstrated_actions?.length ?? 0) > 0

  const codingSkills = ["JavaScript", "Python", "TypeScript", "Code", "Programming", "React", "Vue"]
  const hasCodeSkill = [
    ...(analysis.supported_skills ?? []),
    ...(analysis.weakly_supported_skills ?? []),
  ].some(s => codingSkills.some(c => s.toLowerCase().includes(c.toLowerCase())))

  const qwenStatus = analysis.visual_reasoning_summary?.status
  const ocrAnalyzed = analysis.visual_analysis_status === "analyzed"
  const qwenAnalyzed = qwenStatus === "analyzed"
  const qwenPending = qwenStatus === "pending"
  const qwenNotConfigured = qwenStatus === "disabled" || qwenStatus === "not_configured"
  const qwenResourceSkipped = qwenStatus === "skipped"
  const qwenSkipped = qwenNotConfigured || qwenResourceSkipped

  const items: Array<{ label: string; status: CheckStatus; note?: string }> = [
    {
      label: "Website workflow captured",
      status: (analysis.target_site_pages_count ?? 0) > 0 ? "pass"
        : hasInteraction ? "partial" : "missing",
    },
    {
      label: "DOM evidence captured",
      status: (analysis.demonstrated_actions?.length ?? 0) > 3 ? "pass"
        : hasInteraction ? "partial" : "missing",
    },
    {
      label: "Output/result visible",
      status: hasResultValues ? "pass" : hasVisibleText ? "partial" : "missing",
    },
    {
      label: "Video uploaded",
      status: analysis.video_upload_status === "uploaded" ? "pass"
        : analysis.video_upload_status === "failed" ? "missing" : "missing",
    },
    {
      label: "Keyframes extracted",
      status: analysis.video_keyframe_status === "extracted" ? "pass"
        : analysis.video_keyframe_status === "not_available" ? "partial" : "missing",
      note: analysis.video_keyframe_status === "not_available" ? "Install opencv/ffmpeg" : undefined,
    },
    {
      label: "OCR analyzed",
      status: ocrAnalyzed ? "pass"
        : analysis.video_keyframe_status === "extracted" ? "partial" : "missing",
      note: (!ocrAnalyzed && analysis.video_keyframe_status === "extracted") ? "Set VISUAL_ANALYSIS_PROVIDER" : undefined,
    },
    {
      label: qwenAnalyzed ? "Qwen: analyzed"
        : qwenPending ? "Qwen: processing"
        : qwenResourceSkipped ? "Qwen: skipped (resource limit)"
        : qwenNotConfigured ? "Qwen: not configured"
        : "Qwen: not run",
      status: qwenAnalyzed ? "pass" : qwenPending ? "partial" : qwenSkipped ? "partial" : "missing",
      note: qwenPending ? "Refresh after Qwen analysis completes"
        : qwenNotConfigured ? "VISUAL_REASONING_ENABLED=false"
        : qwenResourceSkipped ? "Reduce VISUAL_REASONING_MAX_FRAMES"
        : undefined,
    },
    {
      label: (analysis.supporting_evidence_count ?? 0) > 0 ? "GitHub: analyzed" : "GitHub: not run",
      status: (analysis.supporting_evidence_count ?? 0) > 0 ? "pass" : "missing",
      note: (analysis.supporting_evidence_count ?? 0) === 0 ? "Run GitHub Evidence Analysis" : undefined,
    },
    {
      label: "Live website: not checked",
      status: "missing" as CheckStatus,
      note: "Run Live Website Check",
    },
    {
      label: "Final evaluator completed",
      status: "pass",
    },
  ]

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: "0.09em",
        textTransform: "uppercase", color: "#475569" }}>
        Proof Completeness Checklist
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 5 }}>
        {items.map(({ label, status, note }) => {
          const c = checkIcon(status)
          return (
            <div key={label} style={{ display: "flex", alignItems: "flex-start", gap: 6,
              padding: "5px 8px", borderRadius: 6, background: c.bg,
              border: `1px solid ${c.border}` }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: c.text,
                lineHeight: 1, flexShrink: 0, marginTop: 1 }}>{c.icon}</span>
              <div>
                <div style={{ fontSize: 10, fontWeight: 600, color: c.text,
                  lineHeight: 1.3 }}>{label}</div>
                {note && (
                  <div style={{ fontSize: 9, color: "#64748b", lineHeight: 1.3,
                    marginTop: 1 }}>{note}</div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Recommended Next Actions (Part E — source-aware) ──────────────────────────

type NextAction = {
  skill: string
  why: string
  objective: string
  buttonLabel: string
  isRecording: boolean
  duration?: string
  actionType: string
}

function buildNextActions(
  analysis: WorkflowAnalysisResponse,
  claimedSkills: string[],
): NextAction[] {
  const score = analysis.evidence_strength_score ?? 0
  if (score >= 80) return []

  const actions: NextAction[] = []
  const missing = analysis.unsupported_skills ?? []
  const partial = analysis.weakly_supported_skills ?? []
  const allWeak = [...missing, ...partial]

  const codeKeywords = ["javascript", "typescript", "python", "code", "open source", "github",
                        "programming", "react", "vue", "angular", "node"]
  const codeSkills = allWeak.filter(s => codeKeywords.some(k => s.toLowerCase().includes(k)))
  const vizSkills  = allWeak.filter(s => ["chart", "visualization", "plot", "data viz"].some(k => s.toLowerCase().includes(k)))

  // GitHub: prefer run_github_analysis over recording when code skills are weak
  if (codeSkills.length > 0) {
    actions.push({
      skill: codeSkills[0],
      why: `${codeSkills[0]} evidence is weak. If a GitHub repository exists, analyzing it gives stronger code evidence than recording alone.`,
      objective: "Run GitHub Evidence Analysis to extract code evidence from the repository.",
      buttonLabel: "Run GitHub Evidence Analysis",
      isRecording: false,
      actionType: "run_github_analysis",
    })
  }

  // Visual / chart gap → recording
  if (vizSkills.length > 0) {
    const skill = vizSkills[0]
    actions.push({
      skill,
      why: `${skill} was not captured clearly in this recording.`,
      objective: "Open one chart, explain axes/marks/trend, and interact with the chart or change a parameter.",
      buttonLabel: "Record Follow-up Proof",
      isRecording: true,
      duration: "30–60 seconds",
      actionType: "record_followup_proof",
    })
  } else if (allWeak.length > 0 && !codeSkills.length) {
    // Generic weak skill with no better action → recording
    const skill = allWeak[0]
    const skillLower = skill.toLowerCase()
    let objective = `Record a focused demonstration of ${skill} showing clear output.`
    if (skillLower.includes("interactive") || skillLower.includes("documentation")) {
      objective = "Open an interactive example, change a parameter, and explain what changed."
    }
    actions.push({
      skill,
      why: `${skill} evidence is weak or missing from the current recording.`,
      objective,
      buttonLabel: "Record Follow-up Proof",
      isRecording: true,
      duration: "30–60 seconds",
      actionType: "record_followup_proof",
    })
  }

  return actions.slice(0, 4)
}

const FOLLOWUP_INTENT_KEY = "vb_followup_intent"

function NextActionsSection({
  analysis,
  sessionId,
  claimedSkills,
}: {
  analysis: WorkflowAnalysisResponse
  sessionId?: string
  claimedSkills?: string[]
}) {
  const [savedAction, setSavedAction] = useState<string | null>(null)
  const score = analysis.evidence_strength_score ?? 0
  const actions = buildNextActions(analysis, claimedSkills ?? [])

  if (score >= 80) {
    return (
      <div style={{ padding: "8px 12px", background: "#f0fdf4",
        border: "1px solid #bbf7d0", borderRadius: 8,
        fontSize: 11, color: "#166534", fontWeight: 600 }}>
        Proof is strong. Optional improvements only.
      </div>
    )
  }

  if (actions.length === 0) return null

  function handleRecord(skill: string, objective: string) {
    try {
      sessionStorage.setItem(FOLLOWUP_INTENT_KEY, JSON.stringify({
        parentSessionId: sessionId ?? "",
        skill,
        objective,
      }))
    } catch { /* sessionStorage unavailable */ }
    setSavedAction(skill)
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: "0.09em",
        textTransform: "uppercase", color: "#475569" }}>
        Recommended Next Actions
      </div>
      <div style={{ fontSize: 10, color: "#64748b", marginTop: -4 }}>
        Strengthen your proof by completing the highest-priority action below.
      </div>
      {actions.map((a, i) => (
        <div key={a.actionType + i} style={{ padding: "10px 12px",
          background: "#fdf4ff", border: "1px solid #e9d5ff",
          borderRadius: 8, display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <span style={{ fontSize: 9, fontWeight: 700, color: "#6d28d9",
              background: "#ede9fe", border: "1px solid #ddd6fe",
              borderRadius: 4, padding: "2px 7px" }}>
              Action {i + 1}
            </span>
            <span style={{ fontSize: 11, fontWeight: 700, color: "#3b0764" }}>
              {a.skill}
            </span>
          </div>
          <div style={{ fontSize: 10, color: "#64748b", lineHeight: 1.4 }}>{a.why}</div>
          <div>
            <div style={{ fontSize: 9, fontWeight: 700, color: "#6d28d9",
              textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 2 }}>
              Objective
            </div>
            <div style={{ fontSize: 10, color: "#1e293b", lineHeight: 1.5,
              padding: "5px 8px", background: "#ede9fe",
              borderRadius: 5, border: "1px solid #ddd6fe" }}>
              {a.objective}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            {a.duration && <span style={{ fontSize: 9, color: "#64748b" }}>Duration: {a.duration}</span>}
            {savedAction === a.skill && a.isRecording ? (
              <div style={{ fontSize: 10, color: "#6d28d9", fontWeight: 600,
                padding: "4px 10px", background: "#ede9fe",
                border: "1px solid #c4b5fd", borderRadius: 6 }}>
                ✓ Intent saved — scroll to Proof Recording section and click Start New Proof
              </div>
            ) : a.isRecording ? (
              <button
                type="button"
                onClick={() => handleRecord(a.skill, a.objective)}
                style={{ fontSize: 10, fontWeight: 700, padding: "5px 12px",
                  borderRadius: 7, border: "none",
                  background: "#7c3aed", color: "#fff",
                  cursor: "pointer" }}>
                {a.buttonLabel}
              </button>
            ) : (
              <span style={{ fontSize: 10, color: "#475569", fontStyle: "italic",
                padding: "4px 10px", background: "#f1f5f9",
                border: "1px solid #e2e8f0", borderRadius: 6 }}>
                {a.buttonLabel} — available in proof session panel
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Inline analysis view ──────────────────────────────────────────────────────

function InlineAnalysisView({ analysis, sessionId, claimedSkills }: { analysis: WorkflowAnalysisResponse; sessionId?: string; claimedSkills?: string[] }) {
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

      {/* Video / Keyframe Evidence section (shown when video was recorded) */}
      <VideoKeyframeEvidenceSection analysis={analysis} />

      {/* Evidence layer badges */}
      <EvidenceLayerLegend analysis={analysis} sessionId={sessionId} />

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
              <ObservedDemonstrationTimeline
                demo={analysis.observed_demonstration}
                videoKeyframeStatus={analysis.video_keyframe_status}
                videoKeyframeCount={analysis.video_keyframe_count}
              />
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

      {/* Skill-by-Skill Evidence (Part C) */}
      <SkillBySkillEvidence analysis={analysis} />

      {/* Proof Completeness Checklist (Part D) */}
      <ProofCompletenessChecklist analysis={analysis} />

      {/* Recommended Next Actions (Part E — source-aware) */}
      <NextActionsSection
        analysis={analysis}
        sessionId={sessionId}
        claimedSkills={claimedSkills}
      />
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
        {showAnalysis && analysis && (
          <InlineAnalysisView
            analysis={analysis}
            sessionId={profile.latest_session_id ?? undefined}
            claimedSkills={profile.all_skill_names}
          />
        )}

        {/* History timeline */}
        {showHistory && <HistoryTimeline profile={profile} />}
      </div>
    </div>
  )
}
