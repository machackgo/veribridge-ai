"use client"

/**
 * EvidenceAnalysisProgress.tsx
 *
 * Reusable progress component for all VeriBridge evidence analysis flows.
 *
 * Usage:
 *   <EvidenceAnalysisProgress
 *     featureType="website_workflow"
 *     simProgress={60}
 *     simStageIdx={3}
 *   />
 *
 * featureType controls which stages and colour theme are shown:
 *   - "website_workflow"      — 9-stage precise IAO workflow analysis (purple)
 *   - "github"                — GitHub repository analysis (dark/gray)
 *   - "project_defense"       — Project defense media analysis (orange)
 *   - "transcript_correction" — Transcript refinement (green)
 *
 * When visual_analysis_status is "not_available" (the default until frame/OCR
 * is implemented), an honest disclaimer chip is shown after the stage list.
 *
 * Backend integration:
 *   Pass analysis_stage and progress_percent from the backend response to
 *   drive the display. Until backend SSE/streaming is available, the parent
 *   can simulate progress via simProgress and simStageIdx.
 */

import type { CSSProperties } from "react"
import type { VisualAnalysisStatus } from "@/lib/api"

// ── Types ─────────────────────────────────────────────────────────────────────

export type AnalysisFeatureType =
  | "website_workflow"
  | "github"
  | "project_defense"
  | "transcript_correction"

type StageConfig = {
  key: string
  label: string
  description: string
  comingSoon?: boolean
}

// ── Stage configs ──────────────────────────────────────────────────────────────

const WEBSITE_WORKFLOW_STAGES: StageConfig[] = [
  {
    key: "preparing_recording",
    label: "Preparing recording",
    description: "Loading session metadata and workflow events.",
  },
  {
    key: "filtering_tabs",
    label: "Filtering background tabs",
    description: "Removing unrelated tabs, VeriBridge dashboard, and internal pages.",
  },
  {
    key: "identifying_target",
    label: "Identifying target website",
    description: "Classifying the proof target application type.",
  },
  {
    key: "extracting_events",
    label: "Extracting relevant workflow events",
    description: "Reading click, navigation, and form events on the target site.",
  },
  {
    key: "reading_outputs",
    label: "Reading visible text and outputs",
    description: "Analysing page titles and available DOM content.",
  },
  {
    key: "detecting_iao_flow",
    label: "Detecting input → action → output flow",
    description: "Identifying what was uploaded, triggered, and displayed.",
  },
  {
    key: "mapping_skills",
    label: "Mapping demonstration to skills",
    description: "Evaluating which claimed skills are supported by the workflow.",
  },
  {
    key: "generating_summary",
    label: "Generating recruiter-safe summary",
    description: "Writing an evidence narrative — no private URLs or paths.",
  },
  {
    key: "finalizing",
    label: "Finalizing Work Passport evidence",
    description: "Saving results to your Work Passport.",
  },
  {
    key: "video_frame_analysis",
    label: "Video frame analysis",
    description: "Extracting visual evidence from recording frames.",
    comingSoon: true,
  },
]

const GITHUB_STAGES: StageConfig[] = [
  { key: "validating_url",     label: "Validating GitHub URL",                        description: "Checking the repository URL is reachable." },
  { key: "fetching_metadata",  label: "Fetching repository metadata",                 description: "Reading repo name, description, and visibility." },
  { key: "reading_readme",     label: "Reading README and file tree",                 description: "Extracting documentation and project structure." },
  { key: "detecting_langs",    label: "Detecting languages and frameworks",           description: "Identifying technologies from code files and configs." },
  { key: "matching_skills",    label: "Matching repo evidence to claimed skills",     description: "Cross-referencing repo content with submitted skills." },
  { key: "checking_missing",   label: "Checking missing evidence and risk flags",     description: "Noting what is absent or needs human review." },
  { key: "generating_summary", label: "Generating recruiter-readable summary",        description: "Writing a safe, evidence-based repository summary." },
  { key: "saving_result",      label: "Saving result",                               description: "Persisting GitHub evidence to your Work Passport." },
]

const DEFENSE_STAGES: StageConfig[] = [
  { key: "scanning_privacy",    label: "Scanning for sensitive data",         description: "Checking transcript for private information." },
  { key: "analyzing_transcript",label: "Analyzing transcript content",        description: "Reading what was discussed in the defense." },
  { key: "detecting_skills",    label: "Detecting skills mentioned",          description: "Extracting skill evidence from the spoken content." },
  { key: "scoring_consistency", label: "Scoring evidence consistency",        description: "Comparing defense claims against other proof evidence." },
  { key: "generating_summary",  label: "Generating recruiter summary",        description: "Writing a recruiter-safe narrative from the defense." },
  { key: "saving_result",       label: "Saving result",                      description: "Saving project defense evidence to your Work Passport." },
]

const TRANSCRIPT_STAGES: StageConfig[] = [
  { key: "loading_transcript",   label: "Loading transcript",       description: "Preparing the transcript for refinement." },
  { key: "applying_corrections", label: "Applying corrections",     description: "Updating incorrect or misheard terms." },
  { key: "refining_content",     label: "Refining content",         description: "Improving clarity and accuracy of the transcript." },
  { key: "saving_result",        label: "Saving refined transcript", description: "Persisting the updated transcript." },
]

const STAGE_CONFIGS: Record<AnalysisFeatureType, StageConfig[]> = {
  website_workflow:      WEBSITE_WORKFLOW_STAGES,
  github:                GITHUB_STAGES,
  project_defense:       DEFENSE_STAGES,
  transcript_correction: TRANSCRIPT_STAGES,
}

// ── Theme ──────────────────────────────────────────────────────────────────────

type Theme = {
  bg: string
  border: string
  titleColor: string
  subColor: string
  barColor: string
  barBg: string
  doneColor: string
  currentColor: string
  pendingColor: string
}

const THEMES: Record<AnalysisFeatureType, Theme> = {
  website_workflow: {
    bg: "#faf5ff", border: "#ddd6fe",
    titleColor: "#5b21b6", subColor: "#4c1d95",
    barColor: "#7c3aed", barBg: "#ede9fe",
    doneColor: "#065f46", currentColor: "#5b21b6", pendingColor: "#94a3b8",
  },
  github: {
    bg: "#f9fafb", border: "#d1d5db",
    titleColor: "#111827", subColor: "#374151",
    barColor: "#111827", barBg: "#e5e7eb",
    doneColor: "#065f46", currentColor: "#111827", pendingColor: "#9ca3af",
  },
  project_defense: {
    bg: "#fff7ed", border: "#fed7aa",
    titleColor: "#9a3412", subColor: "#92400e",
    barColor: "#ea580c", barBg: "#ffedd5",
    doneColor: "#065f46", currentColor: "#9a3412", pendingColor: "#94a3b8",
  },
  transcript_correction: {
    bg: "#f0fdf4", border: "#bbf7d0",
    titleColor: "#065f46", subColor: "#064e3b",
    barColor: "#16a34a", barBg: "#dcfce7",
    doneColor: "#065f46", currentColor: "#065f46", pendingColor: "#94a3b8",
  },
}

// ── Copy ───────────────────────────────────────────────────────────────────────

const FEATURE_TITLE: Record<AnalysisFeatureType, string> = {
  website_workflow:      "Analysing website workflow…",
  github:                "GitHub evidence analysis in progress…",
  project_defense:       "Analysing project defense…",
  transcript_correction: "Refining transcript…",
}

const FEATURE_SUBTITLE: Record<AnalysisFeatureType, string> = {
  website_workflow: (
    "VeriBridge is reviewing your recorded workflow. This usually takes 10–30 seconds."
  ),
  github: (
    "VeriBridge is analysing your GitHub repository. This usually takes 10–30 seconds."
  ),
  project_defense: (
    "VeriBridge is analysing your project defense recording. This usually takes 10–30 seconds."
  ),
  transcript_correction: (
    "Applying corrections and refining the transcript. This usually takes a few seconds."
  ),
}

const CURRENT_STAGE_DESCRIPTIONS: Record<AnalysisFeatureType, Record<string, string>> = {
  website_workflow: {
    filtering_tabs:    "Filtering background tabs and focusing on the target website.",
    reading_outputs:   "Reading visible outputs from the recorded workflow.",
    detecting_iao_flow:"Detecting what was uploaded, triggered, and displayed.",
    mapping_skills:    "Mapping observed demonstration to skill evidence.",
    generating_summary:"Building a recruiter-safe summary from the evidence.",
    finalizing:        "Finalising evidence for your Work Passport.",
  },
  github:                {},
  project_defense:       {},
  transcript_correction: {},
}

// ── Main component ─────────────────────────────────────────────────────────────

type EvidenceAnalysisProgressProps = {
  featureType: AnalysisFeatureType
  /** Simulated progress percent (0–100) — used while waiting for backend response */
  simProgress: number
  /** Index into the stage list marking the current stage (0-based) */
  simStageIdx: number
  /**
   * Visual analysis status returned by the backend.
   * When "not_available", an honest disclaimer is shown.
   * Defaults to "not_available" until backend returns a value.
   */
  visualAnalysisStatus?: VisualAnalysisStatus
  /** Error message — if provided, shows a failed state */
  error?: string | null
  /** Callback for the retry button when error is shown */
  onRetry?: () => void
}

export function EvidenceAnalysisProgress({
  featureType,
  simProgress,
  simStageIdx,
  visualAnalysisStatus = "not_available",
  error,
  onRetry,
}: EvidenceAnalysisProgressProps) {
  const theme = THEMES[featureType]
  const stages = STAGE_CONFIGS[featureType]
  const title = FEATURE_TITLE[featureType]
  const subtitle = FEATURE_SUBTITLE[featureType]
  const currentDescs = CURRENT_STAGE_DESCRIPTIONS[featureType]

  const currentStage = stages[simStageIdx]
  const currentDesc =
    currentDescs[currentStage?.key ?? ""] ??
    currentStage?.description ??
    ""

  const container: CSSProperties = {
    border: `1px solid ${error ? "#fecaca" : theme.border}`,
    borderRadius: 12,
    background: error ? "#fef2f2" : theme.bg,
    padding: "14px 16px",
    display: "grid",
    gap: 12,
  }

  if (error) {
    return (
      <div style={container}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#991b1b" }}>Analysis failed</div>
        <p style={{ margin: 0, fontSize: 12, color: "#991b1b", lineHeight: 1.65 }}>{error}</p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            style={{
              fontSize: 11, fontWeight: 600, padding: "6px 14px", borderRadius: 8,
              border: "1px solid #fecaca", background: "transparent",
              color: "#991b1b", cursor: "pointer", alignSelf: "flex-start",
            }}
          >
            Retry
          </button>
        )}
      </div>
    )
  }

  return (
    <div style={container}>
      {/* Header */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 700, color: theme.titleColor }}>{title}</div>
        <p style={{ margin: "4px 0 0", fontSize: 12, color: theme.subColor, lineHeight: 1.65 }}>
          {subtitle}
        </p>
      </div>

      {/* Progress bar */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
          <span style={{ fontSize: 11, color: theme.subColor }}>
            {currentStage ? currentStage.label : "In progress"}
          </span>
          <span style={{ fontSize: 11, fontWeight: 700, color: theme.titleColor }}>
            {simProgress}%
          </span>
        </div>
        <div style={{ height: 6, background: theme.barBg, borderRadius: 999 }}>
          <div
            style={{
              height: 6, borderRadius: 999, background: theme.barColor,
              width: `${simProgress}%`, transition: "width 0.5s ease",
            }}
          />
        </div>
        {/* Current stage description */}
        {currentDesc && (
          <p style={{
            margin: "6px 0 0", fontSize: 11, color: theme.subColor, lineHeight: 1.5,
            fontStyle: "italic",
          }}>
            {currentDesc}
          </p>
        )}
      </div>

      {/* Stage checklist */}
      <div style={{ display: "grid", gap: 6 }}>
        {stages.map((stage, i) => {
          if (stage.comingSoon) {
            return (
              <div key={stage.key} style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <span style={{ fontSize: 12, color: "#cbd5e1", width: 14, flexShrink: 0, textAlign: "center" }}>—</span>
                <span style={{ fontSize: 12, color: "#94a3b8" }}>{stage.label}</span>
                <span style={{ fontSize: 10, color: "#94a3b8", marginLeft: "auto" }}>Coming soon</span>
              </div>
            )
          }

          const isDone    = i < simStageIdx
          const isCurrent = i === simStageIdx
          const iconColor = isDone ? theme.doneColor : isCurrent ? theme.currentColor : theme.pendingColor
          const textColor = isDone ? theme.doneColor : isCurrent ? theme.titleColor  : theme.pendingColor

          return (
            <div key={stage.key} style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <span
                style={{
                  fontSize: 12, fontWeight: 700, color: iconColor,
                  width: 14, flexShrink: 0, textAlign: "center",
                }}
              >
                {isDone ? "✓" : isCurrent ? "…" : "○"}
              </span>
              <span style={{ fontSize: 12, color: textColor, fontWeight: isCurrent ? 600 : 400 }}>
                {stage.label}
              </span>
            </div>
          )
        })}
      </div>

      {/* Honest visual analysis disclaimer (website_workflow only) */}
      {featureType === "website_workflow" && visualAnalysisStatus === "not_available" && (
        <div style={{
          display: "flex", alignItems: "center", gap: 7, marginTop: 2,
          padding: "7px 10px", borderRadius: 8,
          background: "#f8fafc", border: "1px solid #e2e8f0",
        }}>
          <span style={{ fontSize: 11, color: "#64748b" }}>○</span>
          <span style={{ fontSize: 11, color: "#64748b", lineHeight: 1.5 }}>
            <strong style={{ color: "#475569" }}>Visual frame analysis:</strong>{" "}
            Not available — exact output values (labels, scores) require video frame extraction.
            The analysis uses browser event data only.
          </span>
        </div>
      )}
    </div>
  )
}

// ── Completed state chip ───────────────────────────────────────────────────────

export function AnalysisCompletedChip({
  featureType,
}: {
  featureType: AnalysisFeatureType
}) {
  const theme = THEMES[featureType]
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      fontSize: 11, fontWeight: 600, padding: "4px 10px", borderRadius: 999,
      background: "#f0fdf4", color: "#065f46", border: "1px solid #bbf7d0",
    }}>
      ✓ AI Reviewed
    </span>
  )
}
