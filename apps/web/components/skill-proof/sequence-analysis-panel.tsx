"use client"

import { useState } from "react"
import type { CSSProperties } from "react"
import type {
  SequenceAnalysisResult,
  WorkflowStageSummary,
  InputActionOutputChain,
} from "@/lib/api"

// ── Style helpers ─────────────────────────────────────────────────────────────

const sectionTitle: CSSProperties = {
  fontSize: 10,
  fontWeight: 800,
  letterSpacing: "0.09em",
  textTransform: "uppercase",
  color: "#475569",
  marginBottom: 6,
}

function statusStyle(status: string): CSSProperties {
  switch (status) {
    case "completed":
      return { background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0" }
    case "not_available":
    case "skipped":
    case "insufficient_frames":
      return { background: "#f8fafc", color: "#64748b", border: "1px dashed #cbd5e1" }
    case "failed":
      return { background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca" }
    default:
      return { background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a" }
  }
}

function strengthStyle(strength: string): CSSProperties {
  switch (strength) {
    case "strong":
      return { background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }
    case "moderate":
      return { background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" }
    case "weak":
      return { background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a" }
    default:
      return { background: "#f1f5f9", color: "#475569", border: "1px solid #e2e8f0" }
  }
}

function scoreColor(score: number): string {
  if (score >= 70) return "#166534"
  if (score >= 40) return "#854d0e"
  return "#991b1b"
}

function pill(label: string, style: CSSProperties) {
  return (
    <span
      key={label}
      style={{
        fontSize: 11,
        fontWeight: 600,
        padding: "3px 8px",
        borderRadius: 999,
        ...style,
      }}
    >
      {label}
    </span>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const labelMap: Record<string, string> = {
    completed: "Sequence Analysis Complete ✓",
    not_available: "Sequence Analysis: Not Available",
    skipped: "Sequence Analysis: Skipped",
    insufficient_frames: "Insufficient Frames",
    failed: "Sequence Analysis Failed",
  }
  const label = labelMap[status] ?? `Status: ${status}`
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 700,
        padding: "3px 9px",
        borderRadius: 999,
        ...statusStyle(status),
      }}
    >
      {label}
    </span>
  )
}

function WorkflowStageList({ stages }: { stages: WorkflowStageSummary[] }) {
  if (!stages.length) return <span style={{ fontSize: 12, color: "#94a3b8" }}>No stage data</span>
  return (
    <div style={{ display: "grid", gap: 6 }}>
      {stages.map((s, i) => (
        <div
          key={i}
          style={{
            padding: "8px 10px",
            background: "#f8fafc",
            border: "1px solid #e2e8f0",
            borderRadius: 8,
            display: "flex",
            flexDirection: "column",
            gap: 3,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                background: "#e2e8f0",
                borderRadius: 4,
                padding: "1px 6px",
                color: "#475569",
              }}
            >
              Stage {i + 1}
            </span>
            <span style={{ fontSize: 12, fontWeight: 600, color: "#0f172a" }}>{s.stage}</span>
            {s.confidence && (
              <span
                style={{
                  fontSize: 9,
                  fontWeight: 700,
                  padding: "1px 5px",
                  borderRadius: 4,
                  ...strengthStyle(s.confidence),
                }}
              >
                {s.confidence}
              </span>
            )}
          </div>
          {s.description && (
            <span style={{ fontSize: 11, color: "#475569", lineHeight: 1.5 }}>{s.description}</span>
          )}
        </div>
      ))}
    </div>
  )
}

function InputActionOutputBlock({ chain }: { chain: InputActionOutputChain }) {
  const inputs = Array.isArray(chain.inputs) ? (chain.inputs as string[]) : []
  const actions = Array.isArray(chain.actions) ? (chain.actions as string[]) : []
  const outputs = Array.isArray(chain.outputs) ? (chain.outputs as string[]) : []

  if (!inputs.length && !actions.length && !outputs.length) {
    return <span style={{ fontSize: 12, color: "#94a3b8" }}>No chain data</span>
  }

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr auto 1fr auto 1fr",
        gap: 6,
        alignItems: "start",
      }}
    >
      {/* Inputs */}
      <div
        style={{
          background: "#f0f9ff",
          border: "1px solid #bae6fd",
          borderRadius: 8,
          padding: "7px 10px",
        }}
      >
        <div
          style={{
            fontSize: 10,
            fontWeight: 700,
            color: "#0369a1",
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            marginBottom: 4,
          }}
        >
          Inputs
        </div>
        {inputs.length ? (
          inputs.map((v, i) => (
            <div key={i} style={{ fontSize: 11, color: "#0c4a6e", lineHeight: 1.5 }}>
              {v}
            </div>
          ))
        ) : (
          <span style={{ fontSize: 11, color: "#94a3b8" }}>—</span>
        )}
      </div>

      <span style={{ fontSize: 16, color: "#94a3b8", alignSelf: "center" }}>→</span>

      {/* Actions */}
      <div
        style={{
          background: "#fdf4ff",
          border: "1px solid #e9d5ff",
          borderRadius: 8,
          padding: "7px 10px",
        }}
      >
        <div
          style={{
            fontSize: 10,
            fontWeight: 700,
            color: "#7e22ce",
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            marginBottom: 4,
          }}
        >
          Actions
        </div>
        {actions.length ? (
          actions.map((v, i) => (
            <div key={i} style={{ fontSize: 11, color: "#4c1d95", lineHeight: 1.5 }}>
              {v}
            </div>
          ))
        ) : (
          <span style={{ fontSize: 11, color: "#94a3b8" }}>—</span>
        )}
      </div>

      <span style={{ fontSize: 16, color: "#94a3b8", alignSelf: "center" }}>→</span>

      {/* Outputs */}
      <div
        style={{
          background: "#f0fdf4",
          border: "1px solid #bbf7d0",
          borderRadius: 8,
          padding: "7px 10px",
        }}
      >
        <div
          style={{
            fontSize: 10,
            fontWeight: 700,
            color: "#166534",
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            marginBottom: 4,
          }}
        >
          Outputs
        </div>
        {outputs.length ? (
          outputs.map((v, i) => (
            <div key={i} style={{ fontSize: 11, color: "#14532d", lineHeight: 1.5 }}>
              {v}
            </div>
          ))
        ) : (
          <span style={{ fontSize: 11, color: "#94a3b8" }}>—</span>
        )}
      </div>
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

/**
 * SequenceAnalysisPanel — renders Week 3 multi-frame sequence analysis results.
 *
 * viewMode:
 *   "student"   — shows full detail including limitations, stage summaries, chain
 *   "recruiter" — shows only public_safe_summary / recruiter_safe_summary
 *   "public"    — same as recruiter (safe summaries only)
 *
 * Never exposes raw frame paths, storage paths, or private metadata regardless of viewMode.
 */
export function SequenceAnalysisPanel({
  analysis,
  viewMode = "student",
}: {
  analysis: SequenceAnalysisResult | null | undefined
  viewMode?: "student" | "recruiter" | "public"
}) {
  const [showStages, setShowStages] = useState(false)
  const [showChain, setShowChain] = useState(false)

  if (!analysis) {
    return (
      <div
        style={{
          padding: "8px 12px",
          background: "#f8fafc",
          border: "1px dashed #e2e8f0",
          borderRadius: 8,
          fontSize: 11,
          color: "#94a3b8",
        }}
      >
        Sequence analysis not available for this session.
      </div>
    )
  }

  const isComplete = analysis.sequence_analysis_status === "completed"
  const isPublicView = viewMode === "recruiter" || viewMode === "public"

  return (
    <div
      style={{
        border: "1px solid #e9d5ff",
        borderRadius: 12,
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          background: "#fdf4ff",
          borderBottom: "1px solid #e9d5ff",
          padding: "12px 16px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 10,
          flexWrap: "wrap",
        }}
      >
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#5b21b6" }}>
            Sequence Analysis
          </div>
          <div style={{ fontSize: 11, color: "#7c3aed", marginTop: 2 }}>
            Multi-frame temporal workflow analysis
          </div>
        </div>
        <StatusBadge status={analysis.sequence_analysis_status} />
      </div>

      <div style={{ padding: "14px 16px", display: "grid", gap: 14, background: "#fff" }}>
        {/* Score + strength row */}
        {isComplete && (
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <span
              style={{
                fontSize: 14,
                fontWeight: 800,
                color: scoreColor(analysis.confidence_score),
                background: "#f8fafc",
                border: "1px solid #e2e8f0",
                borderRadius: 6,
                padding: "3px 9px",
              }}
            >
              {analysis.confidence_score}/100
            </span>
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                padding: "3px 9px",
                borderRadius: 999,
                ...strengthStyle(analysis.evidence_strength),
              }}
            >
              {analysis.evidence_strength} evidence
            </span>
            <span style={{ fontSize: 11, color: "#64748b" }}>
              {analysis.analyzed_frame_count} frame{analysis.analyzed_frame_count !== 1 ? "s" : ""} analyzed
            </span>
          </div>
        )}

        {/* Public/recruiter summary */}
        {(analysis.recruiter_safe_summary || analysis.public_safe_summary) && (
          <div
            style={{
              background: "#f8fafc",
              border: "1px solid #e2e8f0",
              borderRadius: 8,
              padding: "10px 12px",
            }}
          >
            <div style={sectionTitle}>
              {isPublicView ? "Summary" : "Recruiter Summary"}
            </div>
            <p
              style={{
                margin: 0,
                fontSize: 12,
                color: "#334155",
                lineHeight: 1.7,
                fontStyle: "italic",
              }}
            >
              {analysis.recruiter_safe_summary || analysis.public_safe_summary}
            </p>
          </div>
        )}

        {/* Supported skills */}
        {analysis.supported_skills.length > 0 && (
          <div>
            <div style={sectionTitle}>Evidence Supports</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
              {analysis.supported_skills.map((s) =>
                pill(s, { background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" })
              )}
            </div>
          </div>
        )}

        {/* Unsupported claims (student view only) */}
        {!isPublicView && analysis.unsupported_claims.length > 0 && (
          <div>
            <div style={sectionTitle}>Unsupported Claims</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
              {analysis.unsupported_claims.map((s) =>
                pill(s, { background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca" })
              )}
            </div>
          </div>
        )}

        {/* Observed outputs */}
        {analysis.observed_outputs.length > 0 && (
          <div>
            <div style={sectionTitle}>Observed Outputs</div>
            <div style={{ display: "grid", gap: 3 }}>
              {analysis.observed_outputs.map((o, i) => (
                <div
                  key={i}
                  style={{
                    fontSize: 11,
                    padding: "4px 8px",
                    borderRadius: 5,
                    background: "#f0fdf4",
                    border: "1px solid #bbf7d0",
                    color: "#14532d",
                    fontFamily: "monospace",
                    wordBreak: "break-word",
                  }}
                >
                  {o}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Before/After changes (student view) */}
        {!isPublicView && analysis.before_after_changes.length > 0 && (
          <div>
            <div style={sectionTitle}>Before → After Changes</div>
            <div style={{ display: "grid", gap: 3 }}>
              {analysis.before_after_changes.map((c, i) => (
                <div
                  key={i}
                  style={{
                    fontSize: 11,
                    color: "#475569",
                    lineHeight: 1.5,
                    display: "flex",
                    gap: 6,
                  }}
                >
                  <span style={{ flexShrink: 0, color: "#94a3b8" }}>→</span>
                  <span>{c}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Input → Action → Output Chain (student view, collapsible) */}
        {!isPublicView && (
          <div>
            <button
              type="button"
              onClick={() => setShowChain((v) => !v)}
              style={{
                fontSize: 10,
                fontWeight: 600,
                padding: "4px 10px",
                borderRadius: 6,
                border: "1px solid #e9d5ff",
                background: showChain ? "#fdf4ff" : "#f8fafc",
                color: "#7e22ce",
                cursor: "pointer",
              }}
            >
              {showChain ? "Hide Input→Action→Output Chain ▲" : "Show Input→Action→Output Chain ▼"}
            </button>
            {showChain && (
              <div style={{ marginTop: 8 }}>
                <InputActionOutputBlock chain={analysis.input_action_output_chain} />
              </div>
            )}
          </div>
        )}

        {/* Workflow stage summaries (student view, collapsible) */}
        {!isPublicView && analysis.workflow_stage_summaries.length > 0 && (
          <div>
            <button
              type="button"
              onClick={() => setShowStages((v) => !v)}
              style={{
                fontSize: 10,
                fontWeight: 600,
                padding: "4px 10px",
                borderRadius: 6,
                border: "1px solid #bfdbfe",
                background: showStages ? "#eff6ff" : "#f8fafc",
                color: "#1d4ed8",
                cursor: "pointer",
              }}
            >
              {showStages
                ? "Hide Workflow Stages ▲"
                : `Show Workflow Stages (${analysis.workflow_stage_summaries.length}) ▼`}
            </button>
            {showStages && (
              <div style={{ marginTop: 8 }}>
                <WorkflowStageList stages={analysis.workflow_stage_summaries} />
              </div>
            )}
          </div>
        )}

        {/* Limitations (student view) */}
        {!isPublicView && analysis.limitations.length > 0 && (
          <div
            style={{
              background: "#f8fafc",
              border: "1px dashed #e2e8f0",
              borderRadius: 8,
              padding: "8px 11px",
            }}
          >
            <div style={sectionTitle}>Analysis Limitations</div>
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 3 }}>
              {analysis.limitations.map((l, i) => (
                <li
                  key={i}
                  style={{
                    display: "flex",
                    gap: 6,
                    fontSize: 11,
                    color: "#64748b",
                    lineHeight: 1.5,
                  }}
                >
                  <span style={{ flexShrink: 0 }}>○</span>
                  <span>{l}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Not complete notice */}
        {!isComplete && (
          <div
            style={{
              fontSize: 11,
              color: "#64748b",
              fontStyle: "italic",
              padding: "6px 10px",
              background: "#f8fafc",
              borderRadius: 6,
              border: "1px dashed #e2e8f0",
            }}
          >
            {analysis.sequence_analysis_status === "insufficient_frames"
              ? "Not enough video keyframes were captured to run sequence analysis. Record a longer session with more visible workflow actions."
              : analysis.sequence_analysis_status === "not_available"
              ? "Sequence analysis was not run for this session. Re-record with video capture enabled."
              : analysis.sequence_analysis_status === "skipped"
              ? "Sequence analysis was skipped for this session."
              : "Sequence analysis could not be completed."}
          </div>
        )}
      </div>
    </div>
  )
}
