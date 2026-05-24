"use client"

import { useState } from "react"
import type { CSSProperties } from "react"
import type { SkillEvidenceProfile, WorkflowAnalysisResponse } from "@/lib/api"
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

// ── Inline analysis view ──────────────────────────────────────────────────────

function InlineAnalysisView({ analysis }: { analysis: WorkflowAnalysisResponse }) {
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
      <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.1em", textTransform: "uppercase", color: "#64748b" }}>
        Workflow Evidence Analysis — AI Reviewed
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
