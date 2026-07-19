"use client"

import React, { useEffect, useMemo, useReducer, useRef, useState } from "react"
import type { CSSProperties } from "react"
import {
  fetchAPI,
  createExtensionProofSession,
  listExtensionProofSessions,
  createSkillEvidence,
  getExtensionProofSession,
  startExtensionProofSession,
  analyzeWorkflowEvidence,
  getWorkflowAnalysis,
  getWorkflowPrivacyScan,
  uploadProjectDefenseMedia,
  transcribeDefenseMedia,
  refineDefenseTranscript,
  submitOptionalEvidence,
  uploadOptionalEvidenceFile,
  type FinalEvaluationResult,
  type FinalRecommendationAction,
  type NextBestAction,
  type DetectedCapability,
  type DetectedSkillEntry,
  type GroupedSkillEvidence,
  type EvidenceObject,
  type OptionalEvidenceResponse,
  type OptionalEvidenceSourceType,
  type TranscriptSegment,
  type ProjectDefenseTranscribeResponse,
  type ProjectDefenseRefineTranscriptResponse,
  type TranscriptCorrectionEntry,
  type ExtensionProofSessionResponse,
  type ExtensionProofSessionStatus,
  type LiveWebsiteCheckConfidence,
  type LiveWebsiteCheckResponse,
  type WorkflowAnalysisResponse,
  type WorkflowConfidence,
  type ExtensionProofGitHubAnalysisResponse,
  type WorkflowPrivacyScanResponse,
  type WorkflowPrivacyScanStatus,
  type ProjectDefenseAnalysisResponse,
  type ProjectDefenseMediaUploadResponse,
  type TranscriptionStatus,
  type ReadinessLevel,
  type WebsiteEvidenceDiscoveryResponse,
  type DiscoveredEvidenceItem,
  type DiscoveredEvidenceType,
  initializeWebsiteProofRecorder,
  openWebsiteProofTarget,
  startWebsiteProofRecording,
  recorderFailureMessage,
  refreshWebsiteProofRecorderSessionAuth,
  type RecorderHandshakeFailure,
} from "@/lib/api"
import {
  finalizeWebsiteProof,
  listVBRProjects,
  type ProofFinalizationResult,
  type VBRProjectResponse,
} from "@/lib/vbr-api"
import { SequenceAnalysisPanel } from "./sequence-analysis-panel"
import type {
  ObservedDemonstration,
  DemonstrationStep,
} from "@/lib/api"
import {
  createWebsiteProofLifecycle,
  websiteProofLifecycleReducer,
  type WebsiteProofLifecycleEvent,
} from "@/lib/website-proof-lifecycle"

// ── Types ─────────────────────────────────────────────────────────────────────

type PanelStep = "form" | "session_active"
export type WebsiteProofEntryState =
  | "NEW"
  | "ACTIVE"
  | "COMPLETED"
  | "SAVED"
  | "FAILED_RETRYABLE"
type OptionalDocumentUiStatus = "not_added" | "processing" | "analyzed" | "failed"
type FinalSourceScore = { score: number | null; status: string; notes?: string }

export type FormState = {
  websiteUrl: string
  githubUrl: string
  skillName: string
  proofObjective: string
}

const initialWebsiteProofForm: FormState = {
  websiteUrl: "",
  githubUrl: "",
  skillName: "",
  proofObjective: "",
}

const ACTIVE_EXTENSION_PROOF_SESSION_KEY = "vb_active_extension_proof_session"

export type ActiveExtensionProofSessionDraft = {
  sessionId: string
  form: FormState
  configRevision?: number
  savedAt: string
}

function normalizeActiveExtensionProofDraft(value: unknown): ActiveExtensionProofSessionDraft | null {
  if (!value || typeof value !== "object") return null
  const candidate = value as Partial<ActiveExtensionProofSessionDraft>
  if (!candidate.sessionId || typeof candidate.sessionId !== "string") return null
  const form = candidate.form
  if (!form || typeof form !== "object") return null
  return {
    sessionId: candidate.sessionId,
    form: {
      websiteUrl: typeof form.websiteUrl === "string" ? form.websiteUrl : "",
      githubUrl: typeof form.githubUrl === "string" ? form.githubUrl : "",
      skillName: typeof form.skillName === "string" ? form.skillName : "",
      proofObjective: typeof form.proofObjective === "string" ? form.proofObjective : "",
    },
    configRevision: Number.isSafeInteger(candidate.configRevision) && Number(candidate.configRevision) >= 0
      ? Number(candidate.configRevision)
      : 0,
    savedAt: typeof candidate.savedAt === "string" ? candidate.savedAt : new Date().toISOString(),
  }
}

export function saveActiveExtensionProofSession(draft: ActiveExtensionProofSessionDraft): void {
  try {
    if (typeof window === "undefined") return
    localStorage.setItem(ACTIVE_EXTENSION_PROOF_SESSION_KEY, JSON.stringify(draft))
  } catch { /* localStorage unavailable */ }
}

export function loadActiveExtensionProofSession(): ActiveExtensionProofSessionDraft | null {
  try {
    if (typeof window === "undefined") return null
    const raw = localStorage.getItem(ACTIVE_EXTENSION_PROOF_SESSION_KEY)
    if (!raw) return null
    return normalizeActiveExtensionProofDraft(JSON.parse(raw))
  } catch {
    return null
  }
}

export function hasActiveExtensionProofSession(): boolean {
  return loadActiveExtensionProofSession() !== null
}

export function clearActiveExtensionProofSession(sessionId?: string): void {
  try {
    if (typeof window === "undefined") return
    if (sessionId) {
      const active = loadActiveExtensionProofSession()
      if (!active || active.sessionId !== sessionId) return
    }
    localStorage.removeItem(ACTIVE_EXTENSION_PROOF_SESSION_KEY)
  } catch { /* localStorage unavailable */ }
}

const RESUMABLE_EXTENSION_PROOF_STATUSES: ReadonlySet<ExtensionProofSessionStatus> = new Set([
  "created",
  "waiting_for_extension",
  "recording",
  "uploaded_pending_analysis",
  "analyzing",
])

export function isResumableExtensionProofSession(
  session: Pick<ExtensionProofSessionResponse, "status">,
): boolean {
  return RESUMABLE_EXTENSION_PROOF_STATUSES.has(session.status)
}

export function websiteProofEntryState(
  session: ExtensionProofSessionResponse | null,
): WebsiteProofEntryState {
  if (!session) return "NEW"
  if (isResumableExtensionProofSession(session)) return "ACTIVE"
  if (session.status === "completed" && session.finalized_at) return "SAVED"
  if (session.status === "completed") return "COMPLETED"
  return "FAILED_RETRYABLE"
}

export type UrlType =
  | "live_deployed_url"
  | "localhost_url"
  | "local_network_url"
  | "invalid_url"

type ExtensionUploadBridgeState = {
  sessionId: string
  status: string
  statusMessage?: string
  lastUploadError?: string | null
  isRecording?: boolean
}

// ── URL classification ────────────────────────────────────────────────────────

function classifyUrl(raw: string): UrlType {
  const t = raw.trim()
  if (!t.startsWith("http://") && !t.startsWith("https://")) return "invalid_url"
  try {
    const { hostname } = new URL(t)
    const host = hostname.toLowerCase()
    if (host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0" || host === "::1") return "localhost_url"
    if (host.endsWith(".local") || host.endsWith(".internal")) return "local_network_url"
    if (/^10\./.test(host)) return "local_network_url"
    if (/^192\.168\./.test(host)) return "local_network_url"
    if (/^172\.(1[6-9]|2\d|3[01])\./.test(host)) return "local_network_url"
    return "live_deployed_url"
  } catch {
    return "invalid_url"
  }
}

function isLocal(t: UrlType): boolean {
  return t === "localhost_url" || t === "local_network_url"
}

function isLiveCheckApplicable(t: UrlType): boolean {
  return t === "live_deployed_url"
}

// ── Constants & helpers ───────────────────────────────────────────────────────

const POLLING_STATUSES: ExtensionProofSessionStatus[] = [
  "recording",
  "uploaded_pending_analysis",
]

const LIVE_CHECK_STAGES: Array<{ key: string; label: string }> = [
  { key: "validating_url",      label: "Validating URL" },
  { key: "checking_access",     label: "Checking public accessibility" },
  { key: "following_redirects", label: "Following redirects" },
  { key: "reading_metadata",    label: "Reading page metadata" },
  { key: "saving_result",       label: "Saving result" },
]

const GITHUB_STAGES: Array<{ key: string; label: string }> = [
  { key: "validating_url",      label: "Validating GitHub URL" },
  { key: "fetching_metadata",   label: "Fetching repository metadata" },
  { key: "reading_readme",      label: "Reading README and file tree" },
  { key: "detecting_langs",     label: "Detecting languages and frameworks" },
  { key: "matching_skills",     label: "Matching repo evidence to claimed skills" },
  { key: "checking_missing",    label: "Checking missing evidence and risk flags" },
  { key: "generating_summary",  label: "Generating recruiter-readable summary" },
  { key: "saving_result",       label: "Saving result" },
]

const DEFENSE_STAGES: Array<{ key: string; label: string }> = [
  { key: "scanning_privacy",    label: "Scanning for sensitive data" },
  { key: "analyzing_transcript", label: "Analyzing transcript content" },
  { key: "detecting_skills",    label: "Detecting skills mentioned" },
  { key: "scoring_consistency", label: "Scoring evidence consistency" },
  { key: "generating_summary",  label: "Generating recruiter summary" },
  { key: "saving_result",       label: "Saving result" },
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

const SKILL_NAME_MAX = 160

function wordCount(s: string): number {
  return s.trim().match(/\S+/g)?.length ?? 0
}

function fmtTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    })
  } catch {
    return iso
  }
}

// ── Status badge ──────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<
  ExtensionProofSessionStatus,
  { bg: string; color: string; border: string; label: string }
> = {
  created:                   { bg: "#f1f5f9", color: "#475569", border: "#e2e8f0", label: "CREATED" },
  waiting_for_extension:     { bg: "#fef9c3", color: "#854d0e", border: "#fef08a", label: "WAITING" },
  recording:                 { bg: "#dcfce7", color: "#166534", border: "#bbf7d0", label: "RECORDING" },
  uploaded_pending_analysis: { bg: "#dbeafe", color: "#1d4ed8", border: "#bfdbfe", label: "WORKFLOW UPLOADED" },
  analyzing:                 { bg: "#ede9fe", color: "#5b21b6", border: "#ddd6fe", label: "ANALYZING" },
  completed:                 { bg: "#dcfce7", color: "#166534", border: "#bbf7d0", label: "ANALYSIS COMPLETE" },
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
  { label: "Session Created",       statuses: ["created", "waiting_for_extension"] },
  { label: "Recording",             statuses: ["recording"] },
  { label: "Proof Uploaded",        statuses: ["uploaded_pending_analysis"] },
  { label: "Analyzing",             statuses: ["analyzing"] },
  { label: "Website Proof Complete", statuses: ["completed"] },
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
              <div style={{ display: "flex", alignItems: "center", width: "100%" }}>
                <div style={{ flex: 1, height: 2, background: i === 0 ? "transparent" : isDone ? "#065f46" : "#e2e8f0" }} />
                <div
                  style={{
                    width: circleSize, height: circleSize, borderRadius: "50%", flexShrink: 0,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    background: circleBg, border: circleBorder, boxShadow: circleShadow,
                    color: circleColor, fontSize: circleFontSize, fontWeight: 700,
                  }}
                >
                  {circleContent}
                </div>
                <div
                  style={{
                    flex: 1, height: 2,
                    background: i === STEPPER_STEPS.length - 1 ? "transparent" : isDone ? "#065f46" : "#e2e8f0",
                  }}
                />
              </div>
              <div
                style={{
                  marginTop: 8, fontSize: 11, fontWeight: labelWeight,
                  color: labelColor, textAlign: "center", lineHeight: 1.35, paddingInline: 4,
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

// ── Website Proof progress lifecycle ─────────────────────────────────────────

export type WorkflowAnalysisProgressStatus = "pending" | "active" | "complete" | "failed"

export type WorkflowAnalysisProgressStage = {
  key: string
  label: string
  status: WorkflowAnalysisProgressStatus
}

export type WorkflowAnalysisProgressModel = {
  stages: WorkflowAnalysisProgressStage[]
  percent: number
  title: string
  currentMessage: string
  showSlowWarning: boolean
  slowWarningMessage: string
  failed: boolean
}

export type WebsiteProofProgressLifecycle =
  | "idle"
  | "recording"
  | "upload_starting"
  | "uploading"
  | "upload_complete_manual_analysis_required"
  | "analysis_starting"
  | "extracting_keyframes"
  | "running_ocr_visual"
  | "running_qwen_visual"
  | "matching_workflow_timeline"
  | "generating_workflow_report"
  | "workflow_report_ready"
  | "upload_failed"
  | "analysis_failed"

export type WebsiteProofProgressEvent =
  | { type: "session_created" }
  | { type: "recording_started" }
  | { type: "stop_send_clicked" }
  | { type: "upload_started" }
  | { type: "upload_succeeded" }
  | { type: "upload_failed" }
  | { type: "analyze_clicked" }
  | { type: "analysis_request_started" }
  | { type: "analysis_polling_result"; elapsedMs: number }
  | { type: "workflow_report_exists" }
  | { type: "analysis_failed" }
  | { type: "reset" }

const WORKFLOW_ANALYSIS_SLOW_WARNING_MS = 90_000
const WORKFLOW_UPLOAD_SLOW_WARNING_MS = 60_000
const ANALYSIS_STAGE_MS = 15_000

const WORKFLOW_UPLOAD_PROGRESS_STAGES: Array<{ key: string; label: string }> = [
  { key: "uploading", label: "Uploading proof recording" },
]

const WORKFLOW_ANALYSIS_PROGRESS_STAGES: Array<{ key: WebsiteProofProgressLifecycle; label: string }> = [
  { key: "extracting_keyframes", label: "Extracting keyframes" },
  { key: "running_ocr_visual", label: "Running OCR / visual evidence checks" },
  { key: "running_qwen_visual", label: "Running Qwen visual reasoning" },
  { key: "matching_workflow_timeline", label: "Matching browser workflow timeline to claimed skills" },
  { key: "generating_workflow_report", label: "Generating recruiter-safe workflow report" },
]

const ANALYSIS_LIFECYCLE_ORDER: WebsiteProofProgressLifecycle[] = [
  "extracting_keyframes",
  "running_ocr_visual",
  "running_qwen_visual",
  "matching_workflow_timeline",
  "generating_workflow_report",
]

function analysisLifecycleFromElapsed(elapsedMs: number): WebsiteProofProgressLifecycle {
  const index = Math.max(0, Math.min(Math.floor(elapsedMs / ANALYSIS_STAGE_MS), ANALYSIS_LIFECYCLE_ORDER.length - 1))
  return ANALYSIS_LIFECYCLE_ORDER[index]
}

export function websiteProofProgressReducer(
  state: WebsiteProofProgressLifecycle,
  event: WebsiteProofProgressEvent,
): WebsiteProofProgressLifecycle {
  // Website Proof progress is intentionally event-driven. Future edits should
  // dispatch lifecycle events from user actions / extension upload messages /
  // analysis responses instead of inferring this UI from report existence alone.
  switch (event.type) {
    case "reset":
      return "idle"
    case "session_created":
      return "idle"
    case "recording_started":
      if (doesWorkflowProgressOverrideRecordingUi(state)) return state
      return "recording"
    case "stop_send_clicked":
      return "upload_starting"
    case "upload_started": {
      // Do not regress from post-upload states if a late extension event arrives.
      const postUploadStates: WebsiteProofProgressLifecycle[] = [
        "upload_complete_manual_analysis_required",
        "analysis_starting",
        "extracting_keyframes",
        "running_ocr_visual",
        "running_qwen_visual",
        "matching_workflow_timeline",
        "generating_workflow_report",
        "workflow_report_ready",
        "analysis_failed",
        "upload_failed",
      ]
      if (postUploadStates.includes(state)) return state
      return "uploading"
    }
    case "upload_succeeded":
      return state === "workflow_report_ready" ? state : "upload_complete_manual_analysis_required"
    case "upload_failed":
      return "upload_failed"
    case "analyze_clicked":
    case "analysis_request_started":
      return "analysis_starting"
    case "analysis_polling_result":
      if (state === "workflow_report_ready") return state
      return analysisLifecycleFromElapsed(event.elapsedMs)
    case "workflow_report_exists":
      return "workflow_report_ready"
    case "analysis_failed":
      return "analysis_failed"
    default:
      return state
  }
}

function isWorkflowProgressVisible(lifecycle: WebsiteProofProgressLifecycle): boolean {
  return !["idle", "recording", "workflow_report_ready"].includes(lifecycle)
}

export function doesWorkflowProgressOverrideRecordingUi(lifecycle: WebsiteProofProgressLifecycle): boolean {
  return [
    "upload_starting",
    "uploading",
    "upload_complete_manual_analysis_required",
    "upload_failed",
    "analysis_starting",
    "extracting_keyframes",
    "running_ocr_visual",
    "running_qwen_visual",
    "matching_workflow_timeline",
    "generating_workflow_report",
    "analysis_failed",
  ].includes(lifecycle)
}

function isWorkflowAnalysisLifecycle(lifecycle: WebsiteProofProgressLifecycle): boolean {
  return lifecycle === "analysis_starting" || ANALYSIS_LIFECYCLE_ORDER.includes(lifecycle)
}

export function shouldShowWorkflowAnalysisProgress(params: {
  lifecycle?: WebsiteProofProgressLifecycle
  sessionStatus?: ExtensionProofSessionStatus
  workflowAnalysisComplete?: boolean
  uploadStatus?: string | null
  analyzeError?: string | null
}): boolean {
  if (params.lifecycle) return isWorkflowProgressVisible(params.lifecycle)
  if (params.workflowAnalysisComplete) return false
  if (params.uploadStatus === "uploading" || params.uploadStatus === "upload_failed" || params.uploadStatus === "uploaded") return true
  if (params.analyzeError) return true
  return params.sessionStatus === "analyzing"
}

export function buildWorkflowAnalysisProgress(params: {
  lifecycle?: WebsiteProofProgressLifecycle
  sessionStatus?: ExtensionProofSessionStatus
  workflowAnalysisComplete?: boolean
  workflowAnalysisRunning?: boolean
  uploadStatus?: string | null
  uploadError?: string | null
  analyzeError?: string | null
  activeElapsedMs?: number
}): WorkflowAnalysisProgressModel {
  const lifecycle = params.lifecycle ?? (
    params.workflowAnalysisComplete
      ? "workflow_report_ready"
      : params.uploadStatus === "upload_failed"
        ? "upload_failed"
        : params.uploadStatus === "uploading"
          ? "uploading"
          : params.uploadStatus === "uploaded"
            ? "upload_complete_manual_analysis_required"
            : params.analyzeError
              ? "analysis_failed"
              : params.workflowAnalysisRunning || params.sessionStatus === "analyzing"
                ? analysisLifecycleFromElapsed(params.activeElapsedMs ?? 0)
                : "idle"
  )

  if (!isWorkflowProgressVisible(lifecycle)) {
    return {
      stages: [],
      percent: 0,
      title: "Workflow proof ready",
      currentMessage: "Workflow evidence analysis has not started.",
      showSlowWarning: false,
      slowWarningMessage: "",
      failed: false,
    }
  }

  const elapsedMs = params.activeElapsedMs ?? 0
  const uploadStageStatus: WorkflowAnalysisProgressStatus =
    lifecycle === "upload_failed" ? "failed" : lifecycle === "upload_complete_manual_analysis_required" ? "complete" : "active"

  if (["upload_starting", "uploading", "upload_complete_manual_analysis_required", "upload_failed"].includes(lifecycle)) {
    const failed = lifecycle === "upload_failed"
    const complete = lifecycle === "upload_complete_manual_analysis_required"
    return {
      stages: WORKFLOW_UPLOAD_PROGRESS_STAGES.map((stage) => ({ ...stage, status: uploadStageStatus })),
      percent: failed ? 8 : complete ? 100 : 12,
      title: "Uploading workflow proof",
      currentMessage: failed
        ? "Proof upload failed. Please retry."
        : complete
        ? "Proof uploaded. Click Analyze Workflow Evidence to start workflow analysis."
        : "Uploading proof recording — keep this tab open.",
      showSlowWarning: !failed && !complete && elapsedMs >= WORKFLOW_UPLOAD_SLOW_WARNING_MS,
      slowWarningMessage: "Still uploading — large recordings can take longer. Do not close this tab.",
      failed,
    }
  }

  const failed = lifecycle === "analysis_failed"
  const activeLifecycle = failed
    ? "generating_workflow_report"
    : lifecycle === "analysis_starting"
    ? "extracting_keyframes"
    : lifecycle
  const activeIdx = Math.max(0, ANALYSIS_LIFECYCLE_ORDER.indexOf(activeLifecycle))
  const visibleStages = WORKFLOW_ANALYSIS_PROGRESS_STAGES.slice(0, activeIdx + 1)
  const stages = visibleStages.map((stage, index): WorkflowAnalysisProgressStage => ({
    key: stage.key,
    label: stage.label,
    status: failed && index === activeIdx ? "failed" : index < activeIdx ? "complete" : "active",
  }))
  const percent = failed
    ? 92
    : Math.min(95, Math.max(15, 15 + activeIdx * 18 + Math.min(17, Math.floor((elapsedMs % ANALYSIS_STAGE_MS) / 900))))
  const activeLabel = WORKFLOW_ANALYSIS_PROGRESS_STAGES[activeIdx]?.label ?? "Analyzing workflow evidence"

  return {
    stages,
    percent,
    title: "Workflow Evidence Analysis in Progress",
    currentMessage: failed
      ? "Workflow evidence analysis failed. Please retry."
      : lifecycle === "analysis_starting"
      ? "Starting workflow evidence analysis — keep this tab open."
      : `${activeLabel} is in progress.`,
    showSlowWarning: !failed && elapsedMs >= WORKFLOW_ANALYSIS_SLOW_WARNING_MS,
    slowWarningMessage: "Still analyzing — OCR and visual reasoning can take longer. Do not close this tab.",
    failed,
  }
}

function workflowProgressStatusStyle(status: WorkflowAnalysisProgressStatus): CSSProperties {
  if (status === "complete") return { color: "#065f46", background: "#f0fdf4", border: "1px solid #d1fae5" }
  if (status === "active") return { color: "#1d4ed8", background: "#eff6ff", border: "1px solid #bfdbfe" }
  if (status === "failed") return { color: "#991b1b", background: "#fef2f2", border: "1px solid #fecaca" }
  return { color: "#64748b", background: "#f8fafc", border: "1px solid #e2e8f0" }
}

function workflowProgressStatusIcon(status: WorkflowAnalysisProgressStatus): string {
  if (status === "complete") return "✓"
  if (status === "active") return "…"
  if (status === "failed") return "!"
  return "○"
}

function workflowProgressStatusLabel(status: WorkflowAnalysisProgressStatus): string {
  if (status === "active") return "Active"
  if (status === "complete") return "Complete"
  if (status === "failed") return "Retry"
  return "Pending"
}

function WorkflowAnalysisProgressCard({
  model,
  onRetry,
}: {
  model: WorkflowAnalysisProgressModel
  onRetry?: () => void
}) {
  return (
    <div
      data-testid="workflow-analysis-progress-card"
      style={{ border: "1px solid #bfdbfe", borderRadius: 12, background: "#eff6ff", padding: "14px 16px", display: "grid", gap: 12 }}
    >
      <div style={{ display: "grid", gap: 5 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 10 }}>
          <span style={{ fontSize: 13, fontWeight: 800, color: "#1e40af" }}>
            {model.title}
          </span>
          <span style={{ fontSize: 12, fontWeight: 800, color: "#1d4ed8", fontVariantNumeric: "tabular-nums" }}>
            {model.percent}%
          </span>
        </div>
        <div style={{ height: 8, borderRadius: 999, background: "#e2e8f0", overflow: "hidden" }}>
          <div
            style={{
              height: "100%",
              width: `${model.percent}%`,
              borderRadius: 999,
              background: model.failed ? "#dc2626" : "#2563eb",
              transition: "width 0.35s ease",
            }}
          />
        </div>
        {model.title === "Workflow Evidence Analysis in Progress" && (
          <p style={{ margin: 0, fontSize: 12, color: "#334155", lineHeight: 1.55 }}>
            VeriBridge is analyzing your workflow recording. This usually takes 30–90 seconds.
          </p>
        )}
        <p style={{ margin: 0, fontSize: 11, color: "#64748b", lineHeight: 1.55 }}>
          {model.currentMessage}
        </p>
        {model.showSlowWarning && (
          <div role="status" style={{ border: "1px solid #fde68a", borderRadius: 10, background: "#fffbeb", color: "#92400e", padding: "8px 10px", fontSize: 11, lineHeight: 1.55 }}>
            {model.slowWarningMessage}
          </div>
        )}
        {model.failed && onRetry && (
          <div>
            <button
              type="button"
              onClick={onRetry}
              style={{
                border: "1px solid #dc2626",
                background: "transparent",
                color: "#991b1b",
                borderRadius: 8,
                padding: "6px 14px",
                fontWeight: 700,
                fontSize: 12,
                cursor: "pointer",
              }}
            >
              Retry Workflow Analysis
            </button>
          </div>
        )}
      </div>

      <div style={{ display: "grid", gap: 7 }}>
        {model.stages.map((stage) => {
          const style = workflowProgressStatusStyle(stage.status)
          return (
            <div
              key={stage.key}
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(0, 1fr) auto",
                alignItems: "center",
                gap: 10,
                padding: "8px 10px",
                borderRadius: 9,
                ...style,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                <span style={{ width: 16, textAlign: "center", fontSize: 12, fontWeight: 800, flexShrink: 0 }}>
                  {workflowProgressStatusIcon(stage.status)}
                </span>
                <div style={{ display: "grid", gap: 2, minWidth: 0 }}>
                  <span style={{ fontSize: 12, fontWeight: stage.status === "active" || stage.status === "complete" ? 700 : 600 }}>
                    {stage.label}
                  </span>
                </div>
              </div>
              <span style={{ fontSize: 11, fontWeight: 800, whiteSpace: "nowrap" }}>
                {workflowProgressStatusLabel(stage.status)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Evidence checklist ────────────────────────────────────────────────────────

type EvidenceItemStatus = "complete" | "uploading" | "pending" | "failed" | "unavailable" | "waiting" | "not_added" | "not_applicable"

function evidenceItemStyle(s: EvidenceItemStatus): CSSProperties {
  if (s === "complete")    return { color: "#065f46", background: "#f0fdf4", border: "1px solid #d1fae5" }
  if (s === "uploading")   return { color: "#1d4ed8", background: "#eff6ff", border: "1px solid #bfdbfe" }
  if (s === "failed")      return { color: "#991b1b", background: "#fef2f2", border: "1px solid #fecaca" }
  if (s === "not_applicable") return { color: "#475569", background: "#f8fafc", border: "1px solid #e2e8f0" }
  if (s === "not_added")   return { color: "#64748b", background: "#f8fafc", border: "1px solid #e2e8f0" }
  if (s === "waiting")     return { color: "#64748b", background: "#f8fafc", border: "1px solid #e2e8f0" }
  if (s === "unavailable") return { color: "#94a3b8", background: "#f8fafc", border: "1px solid #e2e8f0" }
  return { color: "#64748b", background: "#f8fafc", border: "1px solid #e2e8f0" }
}

function evidenceIcon(s: EvidenceItemStatus): string {
  if (s === "complete")    return "✓"
  if (s === "uploading")   return "↑"
  if (s === "failed")      return "✗"
  if (s === "not_added")   return "—"
  if (s === "not_applicable") return "—"
  if (s === "waiting")     return "○"
  if (s === "unavailable") return "—"
  return "○"
}

function evidenceLabel(s: EvidenceItemStatus): string {
  if (s === "complete")    return "Complete"
  if (s === "uploading")   return "Uploading"
  if (s === "failed")      return "Failed"
  if (s === "not_added")   return "Not added"
  if (s === "not_applicable") return "Not applicable"
  if (s === "waiting")     return "Waiting"
  if (s === "unavailable") return "Not Available"
  return "Pending"
}

function workflowEvidenceStatus(status: ExtensionProofSessionStatus): EvidenceItemStatus {
  if (status === "expired") return "failed"
  if (["uploaded_pending_analysis", "analyzing", "completed"].includes(status)) return "complete"
  if (status === "recording") return "waiting"
  return "waiting"
}

function workflowAnalysisStatus(
  sessionStatus: ExtensionProofSessionStatus,
  analysis: WorkflowAnalysisResponse | null,
): EvidenceItemStatus {
  if (analysis) return "complete"
  if (sessionStatus === "analyzing") return "uploading"
  if (["uploaded_pending_analysis", "completed"].includes(sessionStatus)) return "pending"
  return "waiting"
}

function liveCheckStatus(
  urlType: UrlType,
  liveCheck: LiveWebsiteCheckResponse | null,
  liveChecking: boolean,
): EvidenceItemStatus {
  if (!isLiveCheckApplicable(urlType)) return "not_applicable"
  if (liveChecking) return "uploading"
  if (!liveCheck) return "waiting"
  if (liveCheck.status === "not_applicable") return "not_applicable"
  if (liveCheck.is_reachable) return "complete"
  return "failed"
}

function githubEvidenceStatus(
  hasGithubUrl: boolean,
  githubAnalysis: ExtensionProofGitHubAnalysisResponse | null,
  githubAnalyzing: boolean,
): EvidenceItemStatus {
  if (!hasGithubUrl) return "not_added"
  if (githubAnalyzing) return "uploading"
  if (!githubAnalysis) return "waiting"
  if (githubAnalysis.status === "success") return "complete"
  if (githubAnalysis.status === "private_or_unavailable") return "failed"
  return "failed"
}

function buildEvidenceItems(
  urlType: UrlType,
  analysis: WorkflowAnalysisResponse | null,
  liveCheck: LiveWebsiteCheckResponse | null,
  liveChecking: boolean,
  hasGithubUrl: boolean,
  githubAnalysis: ExtensionProofGitHubAnalysisResponse | null,
  githubAnalyzing: boolean,
  finalEvaluationPresent = false,
): Array<{
  key: string
  label: string
  getStatus: (s: ExtensionProofSessionStatus) => EvidenceItemStatus
}> {
  const local = isLocal(urlType)
  return [
    {
      key: "workflow",
      label: local ? "Local Workflow Evidence" : "Website Workflow Evidence",
      getStatus: workflowEvidenceStatus,
    },
    {
      key: "workflow_analysis",
      label: "Workflow Analysis",
      getStatus: (s) => workflowAnalysisStatus(s, analysis),
    },
    {
      key: "github",
      label: "GitHub Evidence",
      getStatus: () => githubEvidenceStatus(hasGithubUrl, githubAnalysis, githubAnalyzing),
    },
    {
      key: "live_check",
      label: "Live Website Check",
      getStatus: () => liveCheckStatus(urlType, liveCheck, liveChecking),
    },
    {
      key: "final",
      label: "Final Verification",
      getStatus: () => finalEvaluationPresent ? "complete" : "pending",
    },
  ]
}

function evidenceLabelOverride(key: string, s: EvidenceItemStatus, finalVerificationReady = false): string {
  if (key === "workflow_analysis" && s === "complete") return "AI Reviewed"
  if (key === "workflow_analysis" && s === "uploading") return "In Progress"
  if (key === "github" && s === "complete") return "AI Reviewed"
  if (key === "github" && s === "uploading") return "Analyzing…"
  if (key === "live_check" && s === "uploading") return "Checking…"
  if (key === "live_check" && s === "not_applicable") return "Not applicable"
  if (key === "github" && s === "not_added") return "Not added"
  if (key === "final" && s === "complete") return "Score Generated"
  // Final Verification: show "Ready for Review" when readiness >= 80 and privacy clean.
  // NEVER show "Complete" — that requires a separate VeriBridge reviewer step.
  if (key === "final" && s === "pending" && finalVerificationReady) return "Ready for Review"
  return evidenceLabel(s)
}



function EvidenceChecklist({
  status,
  urlType,
  analysis,
}: {
  status: ExtensionProofSessionStatus
  urlType: UrlType
  analysis: WorkflowAnalysisResponse | null
}) {
  // Website Proof is a focused workflow-evidence experience: GitHub Evidence,
  // the Live Website Check, and the combined Final Verification belong to the
  // other proof pipelines / Work Passport synthesis, so they never appear in
  // this page's checklist.
  const items = buildEvidenceItems(urlType, analysis, null, false, false, null, false, false)
    .filter((item) => item.key !== "github" && item.key !== "final" && item.key !== "live_check")
  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: 12, overflow: "hidden" }}>
      <div style={{ background: "var(--bg-2)", borderBottom: "1px solid var(--line)", padding: "9px 14px" }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: "var(--ink-2)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
          Workflow Evidence Checklist
        </span>
      </div>
      <div style={{ padding: "10px 14px", display: "grid", gap: 7 }}>
        {items.map((item) => {
          const s = item.getStatus(status)
          const style = evidenceItemStyle(s)
          return (
            <div
              key={item.key}
              style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                gap: 10, padding: "7px 10px", borderRadius: 8, ...style,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <span style={{ fontSize: 13, fontWeight: 700, lineHeight: 1 }}>
                  {evidenceIcon(s)}
                </span>
                <span style={{ fontSize: 12, fontWeight: s === "complete" ? 600 : 400 }}>
                  {item.label}
                </span>
              </div>
              <span style={{ fontSize: 11, fontWeight: 600 }}>
                {evidenceLabelOverride(item.key, s)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Recorded proof video ──────────────────────────────────────────────────────

type RecordingReplayState =
  | { kind: "loading" }
  | { kind: "ready"; objectUrl: string; byteSize: number; mimeType: string | null }
  | { kind: "processing" }
  | { kind: "not_retained" }
  | { kind: "error"; message: string }

const REPLAY_RECHECK_MS = 5_000
// Bounded silent rechecks (~2 min) while the extension's upload finishes landing.
const REPLAY_MAX_RECHECKS = 24

/**
 * Replays the retained recording for this Website Proof session — the primary
 * artifact of the proof. Playback streams through the owner-gated canonical
 * replay route (`/api/v1/proofs/website/{session_id}/replay`) via an
 * authenticated fetch, so no storage path or public URL ever reaches the DOM
 * and access is re-checked by the backend on every request.
 *
 * Honest states: sessions captured before recording retention (or whose upload
 * never reached a retained terminal state) have no replay — that renders as a
 * plain `not_retained` end-state, distinct from a transient `error` (Retry).
 */
export function WebsiteProofRecordingSection({
  sessionId,
  sessionStatus,
}: {
  sessionId: string
  sessionStatus: ExtensionProofSessionStatus
}) {
  const [state, setState] = useState<RecordingReplayState>({ kind: "loading" })
  const objectUrlRef = useRef<string | null>(null)
  const rechecksLeftRef = useRef(REPLAY_MAX_RECHECKS)
  const recheckTimerRef = useRef<number | null>(null)

  // A recording can only exist once the proof has been uploaded.
  const canHaveRecording = (
    ["uploaded_pending_analysis", "analyzing", "completed"] as ExtensionProofSessionStatus[]
  ).includes(sessionStatus)

  const load = React.useCallback(async (opts?: { silent?: boolean }) => {
    if (recheckTimerRef.current !== null) {
      window.clearTimeout(recheckTimerRef.current)
      recheckTimerRef.current = null
    }
    if (!opts?.silent) setState({ kind: "loading" })
    try {
      const res = await fetchAPI(`/api/v1/proofs/website/${encodeURIComponent(sessionId)}/replay`)
      if (res.ok) {
        const blob = await res.blob()
        if (blob && blob.size > 0) {
          const previousUrl = objectUrlRef.current
          const url = URL.createObjectURL(blob)
          objectUrlRef.current = url
          setState({ kind: "ready", objectUrl: url, byteSize: blob.size, mimeType: blob.type || null })
          // Revoke the previous replay URL only after React has swapped the
          // <video> source, so the player never requests a dead blob URL.
          if (previousUrl) window.setTimeout(() => URL.revokeObjectURL(previousUrl), 5_000)
          return
        }
      }
      if (res.status === 404 || res.ok) {
        // No retained replay for this session yet. The recorder's upload can
        // still be landing, so keep a bounded silent recheck running before
        // settling on the honest terminal "not retained" state.
        if (rechecksLeftRef.current > 0) {
          rechecksLeftRef.current -= 1
          setState({ kind: "processing" })
          recheckTimerRef.current = window.setTimeout(() => { void load({ silent: true }) }, REPLAY_RECHECK_MS)
        } else {
          setState({ kind: "not_retained" })
        }
        return
      }
      setState({ kind: "error", message: `The recording could not be loaded (HTTP ${res.status}). Retry shortly.` })
    } catch {
      setState({ kind: "error", message: "The recording could not be loaded. Check your connection and retry." })
    }
  }, [sessionId])

  useEffect(() => {
    if (!canHaveRecording) return
    rechecksLeftRef.current = REPLAY_MAX_RECHECKS
    void load()
    return () => {
      if (recheckTimerRef.current !== null) window.clearTimeout(recheckTimerRef.current)
    }
  }, [sessionId, canHaveRecording, load])

  // Release the local object URL when the section unmounts.
  useEffect(() => () => {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current)
  }, [])

  if (!canHaveRecording) return null

  return (
    <div data-testid="website-proof-recording-section" style={{ border: "1px solid var(--line)", borderRadius: 14, background: "var(--bg-2)", overflow: "hidden" }}>
      <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--line)", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>Recorded Proof Video</div>
          <p style={{ margin: "3px 0 0", fontSize: 11, color: "var(--ink-2)", lineHeight: 1.6 }}>
            The recorded walkthrough this Website Proof&apos;s evidence is derived from.
          </p>
        </div>
        <span data-testid="website-proof-recording-privacy" style={{ fontSize: 10, color: "#166534", background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: 999, padding: "3px 8px", fontWeight: 700 }}>
          Private retained evidence
        </span>
      </div>
      <div style={{ padding: "14px 16px" }}>
        {state.kind === "loading" && (
          <div data-testid="website-proof-recording-loading" style={{ fontSize: 12, color: "var(--muted)", padding: "20px 0", textAlign: "center" }}>
            Loading secure replay…
          </div>
        )}

        {state.kind === "ready" && (
          <div style={{ display: "grid", gap: 9 }}>
            <video
              data-testid="website-proof-recording-video"
              controls
              preload="metadata"
              playsInline
              src={state.objectUrl}
              style={{ width: "100%", borderRadius: 10, background: "#000", display: "block", maxHeight: 480 }}
            >
              Your browser cannot play this recording.
            </video>
            <span style={{ fontSize: 10, color: "var(--muted)" }}>
              Owner-only replay — access is re-checked on every request. {Math.max(1, Math.round(state.byteSize / (1024 * 1024)))} MB
            </span>
          </div>
        )}

        {state.kind === "processing" && (
          <div data-testid="website-proof-recording-processing" style={{ fontSize: 12, color: "#1e40af", background: "#eff6ff", border: "1px solid #bfdbfe", borderRadius: 10, padding: "12px 14px", lineHeight: 1.6 }}>
            The secure recording upload is still finishing. The replay will appear here as soon as the retained video is ready.
          </div>
        )}

        {state.kind === "not_retained" && (
          <div data-testid="website-proof-recording-unavailable" style={{ fontSize: 12, color: "var(--ink-2)", background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 10, padding: "12px 14px", lineHeight: 1.6 }}>
            A replayable recording was not retained for this proof. This happens for sessions captured before
            recording retention was enabled, or when the recording upload did not complete. The workflow
            evidence below remains valid — record a new Website Proof to capture a replayable walkthrough.
          </div>
        )}

        {state.kind === "error" && (
          <div data-testid="website-proof-recording-error" role="alert" style={{ display: "grid", gap: 8 }}>
            <div style={{ fontSize: 12, color: "#991b1b", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 10, padding: "10px 14px" }}>
              {state.message}
            </div>
            <div>
              <button
                type="button"
                onClick={() => void load()}
                style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 8, padding: "6px 14px", fontWeight: 600, fontSize: 12, cursor: "pointer" }}
              >
                Retry
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Status-aware message card ─────────────────────────────────────────────────

function StatusMessage({
  status,
  pollingActive,
  session,
  urlType,
}: {
  status: ExtensionProofSessionStatus
  pollingActive: boolean
  session: ExtensionProofSessionResponse
  urlType: UrlType
}) {
  const local = isLocal(urlType)

  if (status === "created" || status === "waiting_for_extension") {
    return (
      <div style={{ border: "1px solid #e2e8f0", borderRadius: 12, background: "#f8fafc", padding: "14px 16px", display: "grid", gap: 4 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#334155" }}>Proof session created</div>
        <p style={{ margin: 0, fontSize: 12, color: "#64748b", lineHeight: 1.65 }}>
          {local
            ? "Local proof session created. Make sure your local server is running, then start the demo."
            : "Proof session created. Start your demo when ready."}
        </p>
      </div>
    )
  }

  if (status === "recording") {
    return (
      <div style={{ border: "1px solid #d1fae5", borderRadius: 12, background: "#f0fdf4", padding: "14px 16px", display: "grid", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 8, height: 8, borderRadius: "50%", flexShrink: 0, background: "#16a34a" }} />
          <span style={{ fontSize: 13, fontWeight: 700, color: "#065f46" }}>
            VeriBridge Extension is recording
          </span>
        </div>
        <p style={{ margin: 0, fontSize: 12, color: "#064e3b", lineHeight: 1.7 }}>
          A floating VeriBridge recorder bar will appear on your{local ? " local" : ""} website while recording. Use
          it to stop and send proof without switching tabs. You can also use{" "}
          <strong>Stop &amp; Send Proof</strong> in the extension popup as a fallback. This
          page will update automatically when your proof is received.
        </p>
        {pollingActive && (
          <p style={{ margin: 0, fontSize: 11, color: "#16a34a" }}>Listening for proof upload…</p>
        )}
      </div>
    )
  }

  if (status === "uploaded_pending_analysis") {
    const title = local ? "✓ Local workflow evidence uploaded" : "✓ Website workflow evidence uploaded"
    const body = local
      ? "Local workflow proof uploaded. This demonstrates the project running in your local environment. Run the workflow analysis below to review the recorded evidence."
      : "Workflow proof uploaded. Run the workflow analysis below to review the recorded evidence."

    return (
      <div style={{ border: "1px solid #bfdbfe", borderRadius: 12, background: "#eff6ff", padding: "14px 16px", display: "grid", gap: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#1e40af" }}>{title}</div>
        <p style={{ margin: 0, fontSize: 12, color: "#1e3a8a", lineHeight: 1.7 }}>{body}</p>
        <div style={{ display: "grid", gap: 4, borderTop: "1px solid #bfdbfe", paddingTop: 8 }}>
          <div style={{ display: "flex", gap: 8 }}>
            <span style={{ fontSize: 11, color: "#3b82f6", minWidth: 80, flexShrink: 0 }}>Session ID</span>
            <span style={{ fontSize: 11, color: "#1e40af", fontFamily: "monospace", wordBreak: "break-all" }}>
              {session.id}
            </span>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <span style={{ fontSize: 11, color: "#3b82f6", minWidth: 80, flexShrink: 0 }}>Uploaded at</span>
            <span style={{ fontSize: 11, color: "#1e40af" }}>{fmtTimestamp(session.updated_at)}</span>
          </div>
          {session.proof_upload_id && (
            <div style={{ display: "flex", gap: 8 }}>
              <span style={{ fontSize: 11, color: "#3b82f6", minWidth: 80, flexShrink: 0 }}>Proof ID</span>
              <span style={{ fontSize: 11, color: "#1e40af", fontFamily: "monospace", wordBreak: "break-all" }}>
                {session.proof_upload_id}
              </span>
            </div>
          )}
        </div>
      </div>
    )
  }

  if (status === "completed") {
    const title = local ? "✓ Local workflow evidence complete" : "✓ Website workflow evidence complete"
    return (
      <div style={{ border: "1px solid #d1fae5", borderRadius: 12, background: "#f0fdf4", padding: "14px 16px", display: "grid", gap: 6 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#065f46" }}>{title}</div>
        <p style={{ margin: 0, fontSize: 12, color: "#064e3b", lineHeight: 1.5 }}>
          Your proof walkthrough has been reviewed. Check your Skill Proof Center for the full verification result.
        </p>
      </div>
    )
  }

  return null
}

// ── Live Website Check components ────────────────────────────────────────────

export function LiveWebsiteCheckInProgress({
  simProgress,
  simStageIdx,
}: {
  simProgress: number
  simStageIdx: number
}) {
  return (
    <div style={{ border: "1px solid #bfdbfe", borderRadius: 12, background: "#eff6ff", padding: "14px 16px", display: "grid", gap: 12 }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#1e40af" }}>Live Website Check in Progress</div>
        <p style={{ margin: "4px 0 0", fontSize: 12, color: "#1e3a8a", lineHeight: 1.65 }}>
          Checking whether your deployed website is publicly accessible. This usually takes 5–20 seconds.
        </p>
      </div>

      {/* Progress bar */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
          <span style={{ fontSize: 11, color: "#3b82f6" }}>Check in progress</span>
          <span style={{ fontSize: 11, fontWeight: 700, color: "#1e40af" }}>{simProgress}%</span>
        </div>
        <div style={{ height: 6, background: "#dbeafe", borderRadius: 999 }}>
          <div
            style={{
              height: 6, borderRadius: 999, background: "#2563eb",
              width: `${simProgress}%`, transition: "width 0.4s ease",
            }}
          />
        </div>
      </div>

      {/* Stage checklist */}
      <div style={{ display: "grid", gap: 6 }}>
        {LIVE_CHECK_STAGES.map((stage, i) => {
          const isDone = i < simStageIdx
          const isCurrent = i === simStageIdx
          return (
            <div key={stage.key} style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: isDone ? "#065f46" : isCurrent ? "#1e40af" : "#94a3b8", width: 14, flexShrink: 0, textAlign: "center" }}>
                {isDone ? "✓" : isCurrent ? "…" : "○"}
              </span>
              <span style={{ fontSize: 12, color: isDone ? "#064e3b" : isCurrent ? "#1e3a8a" : "#94a3b8" }}>
                {stage.label}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function sourceScoreFromEvaluation(
  evaluation: FinalEvaluationResult | null,
  key: string,
): FinalSourceScore | undefined {
  const src = evaluation?.evidence_source_breakdown?.find((item) => item.key === key)
  return src ? { score: src.score, status: src.status, notes: src.notes } : undefined
}

function workflowSourceScore(
  evaluation: FinalEvaluationResult | null,
  analysis: WorkflowAnalysisResponse | null,
): FinalSourceScore | undefined {
  const fromEval = sourceScoreFromEvaluation(evaluation, "website_workflow")
  if (fromEval && fromEval.status !== "not_run") return fromEval
  if (!analysis) return fromEval
  const score = Math.max(1, analysis.evidence_strength_score ?? 0)
  return {
    score,
    status: score >= 60 ? "pass" : score >= 30 ? "partial" : "missing",
    notes: `workflow confidence=${analysis.workflow_confidence}`,
  }
}

function videoKeyframeSourceScore(
  evaluation: FinalEvaluationResult | null,
  analysis: WorkflowAnalysisResponse | null,
): FinalSourceScore | undefined {
  const fromEval = sourceScoreFromEvaluation(evaluation, "video_keyframes")
  if (fromEval && fromEval.status !== "not_run") return fromEval
  const count = analysis?.video_keyframe_count ?? 0
  if (count <= 0) return fromEval
  return { score: count >= 3 ? 90 : 60, status: count >= 3 ? "pass" : "partial" }
}

function domSourceScore(
  evaluation: FinalEvaluationResult | null,
  analysis: WorkflowAnalysisResponse | null,
): FinalSourceScore | undefined {
  const fromEval = sourceScoreFromEvaluation(evaluation, "dom_visible_evidence")
  if (fromEval && fromEval.status !== "not_run" && fromEval.status !== "not_available") return fromEval
  const demo = analysis?.observed_demonstration
  const status = demo?.dom_evidence_status ?? demo?.visible_evidence_status
    ?? analysis?.dom_evidence_status ?? analysis?.visible_evidence_status
  const snippets = demo?.top_result_snippets ?? analysis?.top_result_snippets ?? []
  const actions = analysis?.demonstrated_actions ?? []
  if (status === "available" && actions.length > 3) {
    return { score: 80, status: "pass", notes: "DOM visible evidence available" }
  }
  if (status === "available" || status === "partial" || snippets.length > 0 || actions.length > 0) {
    return { score: 50, status: "partial", notes: "DOM visible evidence partial" }
  }
  return fromEval
}

function ocrSourceScore(
  evaluation: FinalEvaluationResult | null,
  analysis: WorkflowAnalysisResponse | null,
): FinalSourceScore | undefined {
  const fromEval = sourceScoreFromEvaluation(evaluation, "ocr")
  if (fromEval && fromEval.status !== "not_run") return fromEval
  const summary = analysis?.frame_ocr_evidence_summary
  const snippets = summary?.top_ocr_snippets ?? []
  if (summary?.detected_page_context === "filtered_non_target_frame") {
    return { score: 0, status: "not_run", notes: "filtered non-target" }
  }
  if (summary?.has_ocr_evidence || snippets.length > 0 || analysis?.visual_analysis_status === "analyzed") {
    return { score: snippets.length > 0 || summary?.has_ocr_evidence ? 50 : 40, status: "partial", notes: "frame text evidence present" }
  }
  return fromEval
}

function qwenSourceScore(
  evaluation: FinalEvaluationResult | null,
  analysis: WorkflowAnalysisResponse | null,
): FinalSourceScore | undefined {
  const fromEval = sourceScoreFromEvaluation(evaluation, "qwen_visual_reasoning")
  if (fromEval && fromEval.status !== "not_run" && fromEval.status !== "not_available") return fromEval
  const summary = analysis?.visual_reasoning_summary
  if (!summary) return fromEval
  if (summary.status === "analyzed") {
    const frames = summary.frames_analyzed ?? 0
    return { score: Math.min(90, 50 + frames * 15), status: "pass" }
  }
  if (summary.status === "filtered_non_target_frame") {
    return { score: 0, status: "not_run", notes: "filtered non-target" }
  }
  return fromEval
}

function projectDefenseSourceScore(
  evaluation: FinalEvaluationResult | null,
  analysis: ProjectDefenseAnalysisResponse | null,
): FinalSourceScore | undefined {
  const fromEval = sourceScoreFromEvaluation(evaluation, "project_defense")
  if (fromEval && fromEval.status !== "not_run" && (fromEval.score ?? 0) > 0) return fromEval
  if (!analysis) return fromEval
  const score = analysis.overall_defense_score
    ?? Math.round([
      analysis.consistency_with_evidence_score,
      analysis.explanation_clarity_score,
      analysis.ownership_signal_score,
      analysis.technical_depth_score,
    ].filter((v): v is number => typeof v === "number").reduce((sum, v, _, arr) => sum + v / arr.length, 0))
  if (!score) return fromEval
  return { score, status: score >= 60 ? "pass" : "partial" }
}

export function mergeVisibleSourceScores(
  evaluation: FinalEvaluationResult | null,
  analysis: WorkflowAnalysisResponse | null,
  defenseAnalysis: ProjectDefenseAnalysisResponse | null,
): FinalEvaluationResult | null {
  if (!evaluation) return evaluation
  const replacements: Record<string, FinalSourceScore | undefined> = {
    website_workflow: workflowSourceScore(evaluation, analysis),
    dom_visible_evidence: domSourceScore(evaluation, analysis),
    video_keyframes: videoKeyframeSourceScore(evaluation, analysis),
    ocr: ocrSourceScore(evaluation, analysis),
    qwen_visual_reasoning: qwenSourceScore(evaluation, analysis),
    project_defense: projectDefenseSourceScore(evaluation, defenseAnalysis),
  }
  return {
    ...evaluation,
    evidence_source_breakdown: evaluation.evidence_source_breakdown.map((src) => {
      const replacement = replacements[src.key]
      if (!replacement) return src
      return {
        ...src,
        score: replacement.score,
        status: replacement.status as typeof src.status,
        notes: replacement.notes ?? src.notes,
      }
    }),
  }
}

const NON_GITHUB_MVP_SOURCE_KEYS = [
  "website_workflow",
  "dom_visible_evidence",
  "video_keyframes",
  "ocr",
  "qwen_visual_reasoning",
  "project_defense",
  "uploaded_documents",
]

const GITHUB_UNAVAILABLE_NOTE = "GitHub evidence unavailable or failed. Other evidence sources still support this proof."

function isPositiveSourceStatus(status: string): boolean {
  return status === "pass" || status === "partial"
}

function sourceLabel(key: string): string {
  const labels: Record<string, string> = {
    website_workflow: "workflow recording",
    dom_visible_evidence: "DOM evidence",
    video_keyframes: "video keyframes",
    ocr: "OCR evidence",
    qwen_visual_reasoning: "visual reasoning",
    project_defense: "transcript",
    uploaded_documents: "documents",
    github: "GitHub evidence",
    live_website_check: "live website check",
  }
  return labels[key] ?? key.replace(/_/g, " ")
}

function compactJoin(items: string[]): string {
  if (items.length <= 1) return items[0] ?? ""
  if (items.length === 2) return `${items[0]} and ${items[1]}`
  return `${items.slice(0, -1).join(", ")}, and ${items[items.length - 1]}`
}

function stabilizeSummaryText(text: string, fallback: string): string {
  if (!text.trim()) return fallback
  if (/repository has not been analyzed|github repository has not been analyzed|repo(?:sitory)? has not been analyzed/i.test(text)) {
    return fallback
  }
  return text
}

export function stabilizeFinalEvaluationForMvp(
  evaluation: FinalEvaluationResult | null,
  urlType: UrlType,
): FinalEvaluationResult | null {
  if (!evaluation) return evaluation
  const isLocal = isLocal_(urlType)
  let githubUnavailable = false
  const sourceBreakdown = evaluation.evidence_source_breakdown.map((src) => {
    if (isLocal && src.key === "live_website_check") {
      return {
        ...src,
        status: "not_applicable" as typeof src.status,
        score: null,
        notes: "Live website check is not applicable for local proof.",
      }
    }
    if (src.key === "github" && src.status !== "pass") {
      githubUnavailable = src.status !== "not_run" || (src.score ?? 0) === 0
      return {
        ...src,
        status: "not_available" as typeof src.status,
        score: null,
        notes: GITHUB_UNAVAILABLE_NOTE,
      }
    }
    return src
  })

  const positiveNonGithub = sourceBreakdown
    .filter((src) => NON_GITHUB_MVP_SOURCE_KEYS.includes(src.key) && isPositiveSourceStatus(src.status))
  const positiveLabels = positiveNonGithub.map((src) => sourceLabel(src.key))
  const strongNonGithubCount = positiveNonGithub.filter((src) => src.status === "pass" || (src.score ?? 0) >= 60).length
  const hasStrongNonGithubPackage = positiveNonGithub.length >= 5 || strongNonGithubCount >= 4

  let finalScore = evaluation.final_score
  if (hasStrongNonGithubPackage) {
    finalScore = Math.max(finalScore, strongNonGithubCount >= 5 ? 82 : 70)
  }

  const confidence: FinalEvaluationResult["confidence"] =
    finalScore >= 80 ? "high" : finalScore >= 60 ? "medium" : evaluation.confidence

  const evidenceSourcesUsed = Array.from(new Set([
    ...evaluation.evidence_sources_used,
    ...positiveLabels,
  ]))
  const evidenceSourcesMissing = evaluation.evidence_sources_missing.filter((source) => {
    const lower = source.toLowerCase()
    if (isLocal && lower.includes("live")) return false
    if (hasStrongNonGithubPackage && lower.includes("github")) return false
    return true
  })

  const balancedSummary = hasStrongNonGithubPackage
    ? `Your proof is partially strong. ${compactJoin(positiveLabels)} support the claimed skills. GitHub evidence could strengthen code-level verification.`
    : evaluation.final_student_summary
  const recruiterSummary = hasStrongNonGithubPackage
    ? `This proof package has meaningful support from ${compactJoin(positiveLabels)}. GitHub evidence is optional code-level strengthening, not the only deciding source.`
    : evaluation.final_recruiter_summary

  const nextBestActions = hasStrongNonGithubPackage
    ? evaluation.next_best_actions.map((action) => (
      action.action_type === "run_github_analysis" || action.action_type === "add_github_url"
        ? {
          ...action,
          reason: GITHUB_UNAVAILABLE_NOTE,
          objective: "Add or retry GitHub evidence later if you want stronger code-level verification.",
          priority: "low" as const,
        }
        : action
    ))
    : evaluation.next_best_actions

  const recommendations = hasStrongNonGithubPackage && evaluation.recommendations
    ? {
      ...evaluation.recommendations,
      proof_actions: evaluation.recommendations.proof_actions.map((action) => (
        action.action_type === "run_github_analysis" || action.action_type === "add_github_url"
          ? {
            ...action,
            reason: GITHUB_UNAVAILABLE_NOTE,
            action: "Add or retry GitHub evidence later if you want stronger code-level verification.",
            priority: "low" as const,
            source_reason: "GitHub is one optional source; non-GitHub evidence is already supporting this proof.",
          }
          : action
      )),
    }
    : evaluation.recommendations

  return {
    ...evaluation,
    final_score: finalScore,
    confidence,
    strong_proof: evaluation.strong_proof || finalScore >= 80,
    evidence_source_breakdown: sourceBreakdown,
    evidence_sources_used: evidenceSourcesUsed,
    evidence_sources_missing: evidenceSourcesMissing,
    final_student_summary: stabilizeSummaryText(evaluation.final_student_summary, balancedSummary),
    final_recruiter_summary: stabilizeSummaryText(evaluation.final_recruiter_summary, recruiterSummary),
    next_best_actions: nextBestActions,
    recommendations: githubUnavailable || hasStrongNonGithubPackage ? recommendations : evaluation.recommendations,
  }
}

function SourceScoreBadge({
  label,
  source,
}: {
  label: string
  source?: FinalSourceScore
}) {
  if (!source) {
    return (
      <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4,
        background: "#f8fafc", color: "#94a3b8", border: "1px dashed #cbd5e1" }}>
        {label}: not run
      </span>
    )
  }

  const isNotRun = source.status === "not_run"
  const isNotAvailable = source.status === "not_available"
  const isNotApplicable = source.status === "not_applicable"

  // Show a neutral text status for sources that were not run or not configured.
  // Do not show "0/100" — that implies a graded failure, which is misleading.
  if (isNotRun || isNotAvailable || isNotApplicable) {
    const text = isNotApplicable ? "not applicable" : isNotAvailable ? "not configured" : "not run"
    return (
      <span title={source.notes || source.status} style={{ fontSize: 9, fontWeight: 600,
        padding: "2px 7px", borderRadius: 4,
        background: isNotApplicable ? "#eff6ff" : "#f8fafc",
        color: isNotApplicable ? "#1e40af" : "#94a3b8",
        border: `1px dashed ${isNotApplicable ? "#bfdbfe" : "#cbd5e1"}` }}>
        {label}: {text}
      </span>
    )
  }

  const color = source.status === "pass" ? "#166534"
    : source.status === "partial" ? "#854d0e"
    : source.status === "missing" ? "#991b1b"
    : "#64748b"
  const bg = source.status === "pass" ? "#f0fdf4"
    : source.status === "partial" ? "#fffbeb"
    : source.status === "missing" ? "#fef2f2"
    : "#f8fafc"
  const border = source.status === "pass" ? "#bbf7d0"
    : source.status === "partial" ? "#fde68a"
    : source.status === "missing" ? "#fecaca"
    : "#e2e8f0"

  // Qualitative evidence labels only — the Website Proof page never presents
  // numeric trust/confidence scores. Scoring synthesis lives in the Passport /
  // VBR report layer, and model confidence is not candidate ability.
  const scoreLabel = source.status === "pass" ? "strong evidence"
    : source.status === "partial" ? "partial evidence"
    : source.status === "missing" ? "insufficient evidence"
    : source.status

  return (
    <span title={source.notes || source.status} style={{ fontSize: 9, fontWeight: 700,
      padding: "2px 7px", borderRadius: 4, background: bg, color, border: `1px solid ${border}` }}>
      {label}: {scoreLabel}
    </span>
  )
}

const LIVE_CHECK_CONFIDENCE: Record<
  LiveWebsiteCheckConfidence,
  { bg: string; color: string; border: string; label: string }
> = {
  high:   { bg: "#dcfce7", color: "#166534", border: "#bbf7d0", label: "HIGH" },
  medium: { bg: "#fef9c3", color: "#854d0e", border: "#fef08a", label: "MEDIUM" },
  low:    { bg: "#fef9c3", color: "#854d0e", border: "#fef08a", label: "LOW" },
  failed: { bg: "#fef2f2", color: "#991b1b", border: "#fecaca", label: "FAILED" },
  not_applicable: { bg: "#eff6ff", color: "#1e40af", border: "#bfdbfe", label: "N/A" },
}

export function LiveWebsiteCheckCard({
  check,
  onRetry,
  sourceScore,
}: {
  check: LiveWebsiteCheckResponse
  onRetry: () => void
  sourceScore?: FinalSourceScore
}) {
  const conf = LIVE_CHECK_CONFIDENCE[check.confidence] ?? LIVE_CHECK_CONFIDENCE.failed
  const notApplicable = check.status === "not_applicable" || check.confidence === "not_applicable"
  const success = check.is_reachable
  const borderColor = notApplicable ? "#bfdbfe" : success ? "#bbf7d0" : "#fecaca"
  const panelBg = notApplicable ? "#eff6ff" : success ? "#f0fdf4" : "#fef2f2"
  const headerColor = notApplicable ? "#1e40af" : success ? "#065f46" : "#991b1b"
  const bodyColor = notApplicable ? "#1e3a8a" : success ? "#064e3b" : "#991b1b"

  return (
    <div style={{ border: `1px solid ${borderColor}`, borderRadius: 14, overflow: "hidden" }}>
      {/* Header */}
      <div style={{
        background: panelBg,
        borderBottom: `1px solid ${borderColor}`,
        padding: "12px 16px",
        display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap",
      }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: headerColor }}>
            Live Website Check — {notApplicable ? "Not applicable" : success ? "Complete" : "Failed"}
          </div>
          <div style={{ fontSize: 11, color: bodyColor, marginTop: 2 }}>
            {notApplicable ? "Public live check is not applicable for this URL" : success ? "Site is publicly reachable" : "Could not confirm public accessibility"}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <SourceScoreBadge label="Live Website Score" source={sourceScore} />
          <span style={{
            fontSize: 10, fontWeight: 700, letterSpacing: "0.08em",
            padding: "3px 9px", borderRadius: 999,
            background: conf.bg, color: conf.color, border: `1px solid ${conf.border}`,
          }}>
            {conf.label} CONFIDENCE
          </span>
        </div>
      </div>

      <div style={{ padding: "14px 16px", display: "grid", gap: 12 }}>
        {/* Recruiter summary */}
        <div style={{
          background: panelBg,
          border: `1px solid ${borderColor}`,
          borderRadius: 10, padding: "10px 12px",
        }}>
          <p style={{ margin: 0, fontSize: 12, color: bodyColor, lineHeight: 1.7, fontStyle: "italic" }}>
            {check.recruiter_summary}
          </p>
        </div>

        {/* Details grid */}
        <div style={{ display: "grid", gap: 5 }}>
          {[
            ["Submitted URL", check.website_url],
            check.final_url ? ["Final URL", check.final_url] : null,
            check.status_code !== null ? ["HTTP Status", String(check.status_code)] : null,
            check.response_time_ms !== null ? ["Response Time", `${check.response_time_ms}ms`] : null,
            check.page_title ? ["Page Title", check.page_title] : null,
            check.content_type ? ["Content Type", check.content_type.split(";")[0]] : null,
          ].filter((item): item is [string, string] => item !== null).map(([label, value]) => (
            <div key={label} style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
              <span style={{ fontSize: 11, color: "var(--muted)", minWidth: 110, flexShrink: 0 }}>{label}</span>
              <span style={{ fontSize: 12, color: "var(--ink)", wordBreak: "break-all" }}>{value}</span>
            </div>
          ))}
        </div>

        {/* Risk flags */}
        {check.risk_flags.length > 0 && (
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#9a3412", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 5 }}>
              Flags
            </div>
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 3 }}>
              {check.risk_flags.map((f, i) => (
                <li key={i} style={{ fontSize: 11, color: "#854d0e", display: "flex", gap: 6 }}>
                  <span style={{ flexShrink: 0 }}>⚠</span><span>{f}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Failure: retry recommendation */}
        {!success && !notApplicable && (
          <div style={{ background: "#fff7ed", border: "1px solid #fed7aa", borderRadius: 8, padding: "8px 12px" }}>
            <p style={{ margin: 0, fontSize: 11, color: "#9a3412", lineHeight: 1.6 }}>
              Check whether the deployed app is running, public, and not behind authentication. Then retry.
            </p>
          </div>
        )}

        {/* Stage checklist */}
        <div style={{ display: "grid", gap: 5 }}>
          {check.stages.map((stage) => {
            const isComplete = stage.status === "complete"
            const isFailed = stage.status === "failed"
            return (
              <div key={stage.key} style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: isComplete ? "#065f46" : isFailed ? "#991b1b" : "#94a3b8", width: 14, flexShrink: 0, textAlign: "center" }}>
                  {isComplete ? "✓" : isFailed ? "✗" : "○"}
                </span>
                <span style={{ fontSize: 11, color: isComplete ? "#064e3b" : isFailed ? "#991b1b" : "#94a3b8" }}>
                  {stage.label}
                </span>
              </div>
            )
          })}
        </div>

        {/* Footer actions */}
        {!notApplicable && (
          <div style={{ display: "flex", gap: 8, borderTop: "1px solid var(--line)", paddingTop: 10 }}>
            <button
              type="button"
              onClick={onRetry}
              style={{
                fontSize: 11, fontWeight: 600, padding: "6px 14px", borderRadius: 8,
                border: "1px solid var(--line-2)", background: "transparent",
                color: "var(--ink-2)", cursor: "pointer",
              }}
            >
              Re-run Check
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Workflow Analysis Card ────────────────────────────────────────────────────

const CONFIDENCE_CONFIG: Record<WorkflowConfidence, { bg: string; color: string; border: string; label: string }> = {
  high:         { bg: "#dcfce7", color: "#166534", border: "#bbf7d0", label: "HIGH" },
  medium:       { bg: "#fef9c3", color: "#854d0e", border: "#fef08a", label: "MEDIUM" },
  low:          { bg: "#fef2f2", color: "#991b1b", border: "#fecaca", label: "LOW" },
  insufficient: { bg: "#f1f5f9", color: "#475569", border: "#e2e8f0", label: "INSUFFICIENT" },
}

function AnalysisSection({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 700, color: "var(--ink-2)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
        {title}
      </div>
      {children}
    </div>
  )
}

function SkillPill({ label, variant }: { label: string; variant: "supported" | "weak" | "unsupported" }) {
  const styles = {
    supported:   { bg: "#dcfce7", color: "#166534", border: "#bbf7d0" },
    weak:        { bg: "#fef9c3", color: "#854d0e", border: "#fef08a" },
    unsupported: { bg: "#fef2f2", color: "#991b1b", border: "#fecaca" },
  }[variant]
  return (
    <span style={{
      fontSize: 11, fontWeight: 600, padding: "3px 8px", borderRadius: 999,
      background: styles.bg, color: styles.color, border: `1px solid ${styles.border}`,
    }}>
      {label}
    </span>
  )
}

function BulletList({ items, color = "var(--ink-2)" }: { items: string[]; color?: string }) {
  if (!items.length) return <span style={{ fontSize: 12, color: "var(--muted)" }}>None</span>
  return (
    <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 4 }}>
      {items.map((item, i) => (
        <li key={i} style={{ display: "flex", gap: 7, alignItems: "flex-start", fontSize: 12, color, lineHeight: 1.55 }}>
          <span style={{ flexShrink: 0, marginTop: 2, color: "var(--muted)" }}>•</span>
          <span>{item}</span>
        </li>
      ))}
    </ul>
  )
}

// ── Observed Demonstration Timeline ──────────────────────────────────────────

/**
 * DOM evidence badge — shows whether the browser extension captured visible page text.
 * This is distinct from OCR/frame analysis (which is a separate future feature).
 */
function DomEvidenceBadge({ status }: { status: string | undefined }) {
  const s = status ?? "not_captured"
  const cfg = {
    available:    { bg: "#f0fdf4", color: "#166534", border: "#bbf7d0", icon: "✓", label: "DOM evidence captured" },
    partial:      { bg: "#fef9c3", color: "#854d0e", border: "#fef08a", icon: "~", label: "DOM evidence partial" },
    not_captured: { bg: "#fef2f2", color: "#991b1b", border: "#fecaca", icon: "○", label: "DOM not captured" },
  }[s] ?? { bg: "#fef2f2", color: "#991b1b", border: "#fecaca", icon: "○", label: "DOM not captured" }

  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      fontSize: 10, fontWeight: 600, padding: "3px 8px", borderRadius: 999,
      background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.border}`,
    }}>
      {cfg.icon} {cfg.label}
    </span>
  )
}

/**
 * Frame/OCR analysis badge — reflects actual visual_analysis_status from backend.
 * "not_configured" is the safe default when no VISUAL_ANALYSIS_PROVIDER is set.
 * "analyzed" means a local OCR/vision provider ran successfully.
 */
function FrameAnalysisBadge({ status }: { status?: string | null }) {
  const s = status ?? "not_configured"
  if (s === "analyzed") {
    return (
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        fontSize: 10, fontWeight: 600, padding: "3px 8px", borderRadius: 999,
        background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0",
      }}>
        ✓ Frame analysis done
      </span>
    )
  }
  if (s === "pending") {
    return (
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        fontSize: 10, fontWeight: 500, padding: "3px 8px", borderRadius: 999,
        background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a",
      }}>
        ◌ Frame analysis pending
      </span>
    )
  }
  if (s === "failed") {
    return (
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        fontSize: 10, fontWeight: 500, padding: "3px 8px", borderRadius: 999,
        background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca",
      }}>
        ✗ Frame analysis failed
      </span>
    )
  }
  // not_configured / not_available / not_captured → neutral grey
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      fontSize: 10, fontWeight: 500, padding: "3px 8px", borderRadius: 999,
      background: "#f8fafc", color: "#94a3b8", border: "1px solid #e2e8f0",
    }}>
      ○ OCR/vision not configured
    </span>
  )
}

/** Graphical rendering badge — shown when canvas/SVG detected on page. */
function GraphicalRenderingBadge() {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      fontSize: 10, fontWeight: 500, padding: "3px 8px", borderRadius: 999,
      background: "#fff7ed", color: "#9a3412", border: "1px solid #fed7aa",
    }}>
      ◈ Graphical visualization detected
    </span>
  )
}

// ── Video / Keyframe Evidence Section ────────────────────────────────────────
// ── Advanced Visual Reasoning Section (v7) ───────────────────────────────────
// Mirrors the same component in workflow-evidence-profile-card.tsx.
// Shows structured Qwen2.5-VL / Qwen3-VL reasoning when VISUAL_REASONING_ENABLED=true.
// Hidden cleanly when reasoning is disabled or null.

const _RECORDER_UI_PHRASES_FE = [
  "live video recording", "stop or send the recording", "recording controls",
  "recorder controls", "veribridge screen recorder", "veribridge recording interface",
  "recording active", "stop recording", "send proof", "send recording",
  "screen recorder overlay", "browser recorder", "extension recorder",
  "stop & upload", "start screen recording", "recording interface",
  "recorder tab", "veribridge recorder",
]

function _containsRecorderUi(text: string): boolean {
  const lower = (text || "").toLowerCase()
  return _RECORDER_UI_PHRASES_FE.some(p => lower.includes(p))
}

function _filterRecorderUiElements(elements: string[]): string[] {
  return (elements || []).filter(el => !_containsRecorderUi(el))
}

function _preferSanitizedSummary(obs: {
  sanitized_summary?: string
  visual_summary?: string
  recorder_ui_detected?: boolean
}): string {
  if (obs.sanitized_summary && !_containsRecorderUi(obs.sanitized_summary)) {
    return obs.sanitized_summary
  }
  if (obs.visual_summary && !_containsRecorderUi(obs.visual_summary)) {
    return obs.visual_summary
  }
  if (obs.visual_summary && obs.recorder_ui_detected) {
    return ""
  }
  return obs.visual_summary || ""
}

type VisualReasoningSummary = NonNullable<WorkflowAnalysisResponse["visual_reasoning_summary"]>

function AdvancedVisualReasoningSection({
  reasoning,
  sourceScore,
}: {
  reasoning: VisualReasoningSummary | null | undefined
  sourceScore?: FinalSourceScore
}) {
  if (!reasoning) return null

  const isAnalyzed = reasoning.status === "analyzed"
  const isMissing  = reasoning.status === "missing_dependency"
  const isDisabled = reasoning.status === "disabled" || reasoning.status === "not_configured"
  const isFailed   = reasoning.status === "failed"
  const isRejected = reasoning.status === "rejected_inconsistent" || reasoning.status === "rejected_stale"

  if (isDisabled) {
    return (
      <div style={{ marginTop: 6, padding: "8px 10px", background: "#f8fafc",
        border: "1px solid #e2e8f0", borderRadius: 6, fontSize: 10, color: "#64748b" }}>
        <strong style={{ color: "#475569" }}>Qwen Visual Reasoning</strong>
        {" — "}
        Qwen visual reasoning is disabled in backend configuration.
        OCR and DOM analysis were used for evidence.
      </div>
    )
  }

  if (isMissing) {
    return (
      <div style={{ marginTop: 6, padding: "8px 10px", background: "#fefce8",
        border: "1px solid #fef08a", borderRadius: 6, fontSize: 10, color: "#78350f" }}>
        <strong>Qwen visual reasoning</strong>
        {" — "}
        Qwen model unavailable or skipped safely. OCR evidence continues to work.
        <br />
        <span style={{ fontSize: 9, color: "#92400e" }}>
          To enable: pip install &ldquo;transformers&ge;=4.45&rdquo; torch pillow accelerate qwen-vl-utils
        </span>
      </div>
    )
  }

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
          Visual reasoning was rejected because it did not match the current recording evidence.
          DOM/OCR/sequence evidence was used instead.
        </div>
      </div>
    )
  }

  const observations = reasoning.observations ?? []
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
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
        <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: "0.09em",
          textTransform: "uppercase", color: "#6d28d9" }}>
          Advanced Visual Reasoning
        </div>
        <SourceScoreBadge label="Visual reasoning" source={sourceScore} />
      </div>

      {/* Provider + status + frame count */}
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
          <strong style={{ color: "#6d28d9" }}>What Qwen saw: </strong>
          {reasoning.summary}
        </div>
      )}

      {/* Per-frame observations (show first 3) */}
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
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
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
                  {(() => {
                    const displaySummary = _preferSanitizedSummary(obs as {
                      sanitized_summary?: string
                      visual_summary?: string
                      recorder_ui_detected?: boolean
                    })
                    return displaySummary ? (
                      <div style={{ fontSize: 10, color: "#374151", lineHeight: 1.4 }}>
                        {displaySummary}
                      </div>
                    ) : (obs as { recorder_ui_detected?: boolean }).recorder_ui_detected ? (
                      <div style={{ fontSize: 10, color: "#92400e", lineHeight: 1.4, fontStyle: "italic" }}>
                        Recorder UI was detected and excluded from target-app evidence.
                      </div>
                    ) : null
                  })()}
                  {/* Visible diagrams / objects */}
                  {(obs.visible_objects_or_diagrams ?? obs.visible_objects ?? []).length > 0 && (
                    <div style={{ marginTop: 3, display: "flex", flexWrap: "wrap", gap: 3 }}>
                      <span style={{ fontSize: 9, color: "#6b7280", marginRight: 2 }}>Visible:</span>
                      {(obs.visible_objects_or_diagrams ?? obs.visible_objects ?? []).slice(0, 4).map((el, j) => (
                        <span key={j} style={{ fontSize: 9, padding: "1px 5px",
                          background: "#f0fdf4", color: "#166534",
                          borderRadius: 3, border: "1px solid #bbf7d0" }}>
                          {el}
                        </span>
                      ))}
                    </div>
                  )}
                  {(() => {
                    const cleanUi = _filterRecorderUiElements(obs.visible_ui_elements || [])
                    return cleanUi.length > 0 ? (
                      <div style={{ marginTop: 3, display: "flex", flexWrap: "wrap", gap: 3 }}>
                        <span style={{ fontSize: 9, color: "#6b7280", marginRight: 2 }}>UI:</span>
                        {cleanUi.slice(0, 4).map((el, j) => (
                          <span key={j} style={{ fontSize: 9, padding: "1px 5px",
                            background: "#ede9fe", color: "#6d28d9",
                            borderRadius: 3, border: "1px solid #c4b5fd" }}>
                            {el}
                          </span>
                        ))}
                      </div>
                    ) : null
                  })()}
                  {obs.detected_outputs && obs.detected_outputs.length > 0 && (
                    <div style={{ marginTop: 3, display: "flex", flexWrap: "wrap", gap: 3 }}>
                      <span style={{ fontSize: 9, color: "#6b7280", marginRight: 2 }}>Outputs:</span>
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

      {/* Confidence */}
      {observations.length > 0 && (() => {
        const avgConf = observations.reduce((s, o) => s + (o.confidence_score ?? 0), 0) / observations.length
        const isLow = avgConf < 0.45
        return (
          <div style={{ fontSize: 9, color: isLow ? "#92400e" : "#374151" }}>
            <strong>Confidence:</strong> {(avgConf * 100).toFixed(0)}%
            {isLow && (
              <span style={{ marginLeft: 6, fontStyle: "italic", color: "#92400e" }}>
                — Qwen output may be generic or imprecise. DOM and OCR evidence is more reliable here.
              </span>
            )}
          </div>
        )
      })()}

      {/* Model limitation / possible mismatch */}
      {limitations.length > 0 && (
        <div style={{ fontSize: 9, color: "#6b7280", fontStyle: "italic",
          borderTop: "1px solid #e9d5ff", paddingTop: 4 }}>
          <strong>Model limitation / possible mismatch:</strong> {limitations.slice(0, 2).join(" · ")}
        </div>
      )}

      {/* Failure note */}
      {isFailed && (
        <div style={{ fontSize: 10, color: "#b91c1c", background: "#fef2f2",
          border: "1px solid #fecaca", borderRadius: 5, padding: "5px 8px" }}>
          Visual reasoning failed for this session. OCR-based analysis was used as fallback.
        </div>
      )}
    </div>
  )
}

/**
 * Full Video / Keyframe Evidence section.
 * Shows upload status, keyframe count, timestamps, OCR/visual provider status,
 * and a contextual limitation message when video exists but OCR is not configured.
 *
 * Always rendered — shows "no video recorded" state when no video was uploaded.
 */
function VideoKeyframeEvidenceSection({
  analysis,
  keyframeScore,
  ocrScore,
  qwenScore,
}: {
  analysis: WorkflowAnalysisResponse
  keyframeScore?: FinalSourceScore
  ocrScore?: FinalSourceScore
  qwenScore?: FinalSourceScore
}) {
  const kfStatus    = analysis.video_keyframe_status
  const kfCount     = analysis.video_keyframe_count ?? 0
  const timestamps  = analysis.video_keyframe_timestamps_ms ?? []
  const durationMs  = analysis.video_duration_ms
  const uploadStatus = analysis.video_upload_status ?? "none"
  const visualStatus = analysis.visual_analysis_status ?? "not_configured"
  const uploadError  = analysis.video_upload_error

  // Derive whether video was uploaded based on upload_status or kf_status
  // "not_available" = video received but cv2/ffmpeg missing — still show as uploaded
  const videoUploaded = uploadStatus === "uploaded" || kfStatus === "extracted" || kfStatus === "failed" || kfStatus === "not_available"

  // Format duration
  const durationStr = durationMs != null && durationMs > 0
    ? durationMs >= 60000
      ? `${Math.floor(durationMs / 60000)}m ${Math.round((durationMs % 60000) / 1000)}s`
      : `${Math.round(durationMs / 1000)}s`
    : null

  // Format timestamps as readable list (up to 8)
  const shownTimestamps = timestamps.slice(0, 8)

  return (
    <div style={{
      border: "1px solid #e2e8f0",
      borderRadius: 10,
      overflow: "hidden",
      background: "#f8fafc",
    }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "8px 12px",
        borderBottom: "1px solid #e2e8f0",
        background: "#f1f5f9",
      }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: "#334155", textTransform: "uppercase", letterSpacing: "0.06em" }}>
          Video / Keyframe Evidence
        </span>
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <SourceScoreBadge label="Keyframes" source={keyframeScore} />
          {/* Upload status chip */}
          {videoUploaded ? (
            <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
              background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0" }}>
              ✓ Video uploaded
            </span>
          ) : (
            <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4,
              background: "#f1f5f9", color: "#94a3b8", border: "1px dashed #cbd5e1" }}>
              No video recorded
            </span>
          )}
        </div>
      </div>

      <div style={{ padding: "10px 12px", display: "grid", gap: 7 }}>
        {/* Keyframe row */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 10, color: "#64748b", minWidth: 130 }}>Keyframes extracted</span>
          {kfStatus === "extracted" ? (
            <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
              background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0" }}>
              {kfCount} keyframe{kfCount !== 1 ? "s" : ""} ✓
            </span>
          ) : kfStatus === "not_available" ? (
            // Distinguish: truly no deps installed vs installed but decode failed
            uploadError && !uploadError.includes("Install") ? (
              <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4,
                background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca" }}
                title={uploadError}>
                Extraction failed (video decode error)
              </span>
            ) : (
              <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4,
                background: "#fff7ed", color: "#9a3412", border: "1px solid #fed7aa" }}
                title={uploadError ?? "Install opencv-python-headless or ffmpeg to enable keyframe extraction"}>
                cv2/ffmpeg not installed
              </span>
            )
          ) : kfStatus === "failed" ? (
            <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
              background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca" }}
              title={uploadError ?? "Keyframe extraction failed"}>
              {uploadError ? `Failed: ${uploadError.slice(0, 70)}` : "Extraction failed"}
            </span>
          ) : videoUploaded ? (
            <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4,
              background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a" }}>
              Pending / unknown
            </span>
          ) : (
            <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4,
              background: "#f1f5f9", color: "#94a3b8", border: "1px dashed #cbd5e1" }}>
              —
            </span>
          )}
          {/* Duration */}
          {durationStr && (
            <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4,
              background: "#f1f5f9", color: "#64748b", border: "1px solid #e2e8f0" }}>
              ⏱ {durationStr}
            </span>
          )}
        </div>

        {/* Timestamps */}
        {shownTimestamps.length > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <span style={{ fontSize: 10, color: "#64748b", minWidth: 130 }}>Keyframe times</span>
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {shownTimestamps.map((ts, i) => (
                <span key={i} style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3,
                  background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" }}>
                  {ts >= 60000
                    ? `${Math.floor(ts / 60000)}:${String(Math.round((ts % 60000) / 1000)).padStart(2, "0")}`
                    : `${(ts / 1000).toFixed(1)}s`}
                </span>
              ))}
              {timestamps.length > 8 && (
                <span style={{ fontSize: 9, color: "#94a3b8" }}>+{timestamps.length - 8} more</span>
              )}
            </div>
          </div>
        )}

        {/* OCR/Visual provider status */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 10, color: "#64748b", minWidth: 130 }}>OCR/visual analysis</span>
          <SourceScoreBadge label="OCR text" source={ocrScore} />
          {visualStatus === "analyzed" ? (
            <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
              background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0" }}>
              ✓ Analyzed
            </span>
          ) : visualStatus === "failed" ? (
            <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
              background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca" }}>
              ✗ Failed
            </span>
          ) : visualStatus === "pending" ? (
            <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
              background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a" }}>
              ◌ Pending
            </span>
          ) : (
            <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4,
              background: "#f1f5f9", color: "#94a3b8", border: "1px dashed #cbd5e1" }}>
              Not configured
            </span>
          )}
        </div>

        {/* Limitation notice: video uploaded but keyframe extraction unavailable */}
        {kfStatus === "not_available" && (
          <div style={{
            fontSize: 11,
            color: uploadError && !uploadError.includes("Install") ? "#991b1b" : "#9a3412",
            background: uploadError && !uploadError.includes("Install") ? "#fef2f2" : "#fff7ed",
            border: `1px solid ${uploadError && !uploadError.includes("Install") ? "#fecaca" : "#fed7aa"}`,
            borderRadius: 6, padding: "6px 9px", lineHeight: 1.5,
          }}>
            {uploadError ?? (
              <>
                Video was recorded but keyframe extraction is not available.
                Install <code style={{ fontSize: 10 }}>opencv-python-headless</code> or{" "}
                <code style={{ fontSize: 10 }}>ffmpeg</code> on the backend to enable frame extraction.
              </>
            )}
            {" "}Verification uses recording metadata, browser events, and DOM evidence.
          </div>
        )}

        {/* Limitation notice: video uploaded + keyframes extracted but OCR not configured */}
        {kfStatus === "extracted" && (visualStatus === "not_configured" || visualStatus === "not_available") && (
          <div style={{
            fontSize: 11, color: "#854d0e", background: "#fffbeb",
            border: "1px solid #fef08a", borderRadius: 6, padding: "6px 9px", lineHeight: 1.5,
          }}>
            Video was recorded and {kfCount} keyframe{kfCount !== 1 ? "s" : ""} extracted, but OCR/visual model
            analysis is not configured. Verification uses recording metadata, browser events,
            and DOM evidence. Set <code style={{ fontSize: 10 }}>VISUAL_ANALYSIS_PROVIDER=local_ocr</code> or{" "}
            <code style={{ fontSize: 10 }}>local_vision</code> to enable frame analysis.
          </div>
        )}

        {/* Frames analyzed count (when OCR ran) */}
        {visualStatus === "analyzed" && (analysis.visual_frame_count ?? 0) > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 10, color: "#64748b", minWidth: 130 }}>Frames analyzed</span>
            <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
              background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0" }}>
              {analysis.visual_frame_count} frame{(analysis.visual_frame_count ?? 0) !== 1 ? "s" : ""} ✓
            </span>
          </div>
        )}

        {/* OCR extracted text snippets — use top_ocr_snippets from frame_ocr_evidence_summary
            when available (cleaner, deduped); fall back to splitting visual_summary */}
        {visualStatus === "analyzed" && (() => {
          const foes = analysis.frame_ocr_evidence_summary
          const snippets = foes?.top_ocr_snippets?.length
            ? foes.top_ocr_snippets
            : analysis.visual_summary
              ? analysis.visual_summary.split(" | ").map(s => s.trim()).filter(Boolean)
              : []
          if (!snippets.length) return null
          return (
            <div style={{ display: "grid", gap: 3 }}>
              <span style={{ fontSize: 10, color: "#64748b" }}>
                OCR text extracted
                <span style={{ marginLeft: 6, fontSize: 9, color: "#94a3b8", fontWeight: 400 }}>
                  from keyframes · DOM evidence separate
                </span>
              </span>
              <div style={{
                fontSize: 10, color: "#1e293b", background: "#f8fafc",
                border: "1px solid #e2e8f0", borderRadius: 5,
                padding: "5px 8px", lineHeight: 1.6, fontFamily: "monospace",
                maxHeight: 90, overflow: "auto",
              }}>
                {snippets.slice(0, 6).map((snippet, i) => (
                  <div key={i} style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {snippet.length > 100 ? snippet.slice(0, 100) + "…" : snippet}
                  </div>
                ))}
                {snippets.length > 6 && (
                  <div style={{ color: "#94a3b8", fontStyle: "italic" }}>
                    +{snippets.length - 6} more snippets
                  </div>
                )}
              </div>
            </div>
          )
        })()}

        {/* Frame Evidence Summary — observed_summary + page context */}
        {analysis.frame_ocr_evidence_summary?.has_ocr_evidence && (
          <div style={{ display: "grid", gap: 4 }}>
            {/* Page context chip */}
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              <span style={{ fontSize: 10, color: "#64748b", minWidth: 130 }}>Frame context</span>
              {(() => {
                const ctx = analysis.frame_ocr_evidence_summary!.detected_page_context
                const ctxCfg: Record<string, { bg: string; color: string; border: string; label: string }> = {
                  homepage_marketing: { bg: "#fff7ed", color: "#9a3412", border: "#fed7aa", label: "Homepage / marketing" },
                  training_ui:        { bg: "#f0fdf4", color: "#166534", border: "#bbf7d0", label: "Training UI" },
                  prediction_output:  { bg: "#eff6ff", color: "#1d4ed8", border: "#bfdbfe", label: "Prediction output" },
                  demo_content:       { bg: "#fef9c3", color: "#854d0e", border: "#fef08a", label: "Demo content" },
                  unknown:            { bg: "#f1f5f9", color: "#475569", border: "#e2e8f0", label: "Unknown context" },
                }
                const c = ctxCfg[ctx] ?? ctxCfg.unknown
                return (
                  <span style={{ fontSize: 9, fontWeight: 600, padding: "2px 7px", borderRadius: 4,
                    background: c.bg, color: c.color, border: `1px solid ${c.border}` }}>
                    {c.label}
                  </span>
                )
              })()}
            </div>

            {/* Observed summary */}
            <div style={{
              fontSize: 10, color: "#334155", background: "#f8fafc",
              border: "1px solid #e2e8f0", borderRadius: 5,
              padding: "6px 9px", lineHeight: 1.55,
            }}>
              {analysis.frame_ocr_evidence_summary.observed_summary}
            </div>

            {/* What was NOT observed */}
            {analysis.frame_ocr_evidence_summary.what_was_not_observed.length > 0 && (
              <div style={{ display: "grid", gap: 2 }}>
                <span style={{ fontSize: 9, color: "#94a3b8", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  Not observed in frames
                </span>
                {analysis.frame_ocr_evidence_summary.what_was_not_observed.map((item, i) => (
                  <div key={i} style={{ display: "flex", gap: 5, alignItems: "flex-start" }}>
                    <span style={{ fontSize: 9, color: "#ef4444", marginTop: 1 }}>✗</span>
                    <span style={{ fontSize: 10, color: "#64748b" }}>{item}</span>
                  </div>
                ))}
              </div>
            )}

          </div>
        )}

        {/* Detected result values from OCR */}
        {visualStatus === "analyzed" &&
          analysis.visual_result_values && analysis.visual_result_values.length > 0 && (
          <div style={{ display: "grid", gap: 3 }}>
            <span style={{ fontSize: 10, color: "#64748b" }}>Detected values (OCR)</span>
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {analysis.visual_result_values.slice(0, 8).map((rv, i) => (
                <span key={i} style={{
                  fontSize: 9, fontWeight: 600, padding: "2px 6px", borderRadius: 4,
                  background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0",
                }}>
                  {rv.label}: {rv.value}
                </span>
              ))}
              {analysis.visual_result_values.length > 8 && (
                <span style={{ fontSize: 9, color: "#94a3b8" }}>
                  +{analysis.visual_result_values.length - 8} more
                </span>
              )}
            </div>
          </div>
        )}

        {/* Sequence analysis status row */}
        {analysis.sequence_analysis && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontSize: 10, color: "#64748b", minWidth: 130 }}>Sequence analysis</span>
            <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4,
              background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" }}>
              {analysis.sequence_analysis.sequence_analysis_status ?? "unknown"} ·{" "}
              {analysis.sequence_analysis.analyzed_frame_count ?? 0} frames
            </span>
          </div>
        )}

        {/* Advanced Visual Reasoning section (v7) — Qwen2.5-VL / Qwen3-VL */}
        {/* Renders only when reasoning data is present (status in summary dict). */}
        {/* null = reasoning not run / disabled for this session → section hidden. */}
        {analysis.visual_reasoning_summary != null && (
          <AdvancedVisualReasoningSection reasoning={analysis.visual_reasoning_summary} sourceScore={qwenScore} />
        )}
      </div>
    </div>
  )
}

/** Evidence source chip shown inside step cards */
function EvidenceSourceChip({ source }: { source: string | undefined }) {
  if (!source) return null
  const cfg: Record<string, { bg: string; color: string; border: string; label: string }> = {
    dom_snapshot:       { bg: "#f0fdf4", color: "#166534", border: "#bbf7d0", label: "DOM snapshot" },
    event_metadata:     { bg: "#eff6ff", color: "#1d4ed8", border: "#bfdbfe", label: "Event metadata" },
    inferred_from_click:{ bg: "#fef9c3", color: "#854d0e", border: "#fef08a", label: "Inferred from click" },
  }
  const c = cfg[source] ?? { bg: "#f1f5f9", color: "#475569", border: "#e2e8f0", label: source }
  return (
    <span style={{
      fontSize: 9, fontWeight: 600, padding: "2px 6px", borderRadius: 4,
      background: c.bg, color: c.color, border: `1px solid ${c.border}`,
      textTransform: "uppercase", letterSpacing: "0.04em",
    }}>
      {c.label}
    </span>
  )
}

function SupportLevelChip({ level }: { level: string }) {
  const cfg = {
    strong:  { bg: "#dcfce7", color: "#166534", border: "#bbf7d0" },
    partial: { bg: "#fef9c3", color: "#854d0e", border: "#fef08a" },
    weak:    { bg: "#fef2f2", color: "#991b1b", border: "#fecaca" },
    missing: { bg: "#f1f5f9", color: "#475569", border: "#e2e8f0" },
  }[level] ?? { bg: "#f1f5f9", color: "#475569", border: "#e2e8f0" }
  return (
    <span style={{
      fontSize: 10, fontWeight: 600, padding: "2px 7px", borderRadius: 6,
      background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.border}`,
      textTransform: "capitalize",
    }}>
      {level}
    </span>
  )
}

function DemonstrationStepCard({
  step,
  index,
}: {
  step: DemonstrationStep
  index: number
}) {
  const [expanded, setExpanded] = React.useState(index === 0)
  const borderColor = step.confidence === "high" ? "#bbf7d0" : step.confidence === "medium" ? "#fef08a" : "#fecaca"
  const headerBg = step.confidence === "high" ? "#f0fdf4" : step.confidence === "medium" ? "#fefce8" : "#fef2f2"

  return (
    <div style={{ border: `1px solid ${borderColor}`, borderRadius: 10, overflow: "hidden" }}>
      {/* Step header */}
      <button
        type="button"
        onClick={() => setExpanded(v => !v)}
        style={{
          width: "100%", textAlign: "left", background: headerBg, border: "none",
          padding: "9px 12px", cursor: "pointer",
          display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          <span style={{
            fontSize: 10, fontWeight: 700, padding: "2px 6px", borderRadius: 4,
            background: "rgba(0,0,0,0.07)", color: "inherit", flexShrink: 0,
          }}>
            Step {step.step_number}
          </span>
          <span style={{ fontSize: 12, fontWeight: 600, color: "#334155", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {step.user_action}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
          <EvidenceSourceChip source={step.evidence_source} />
          {step.needs_review && (
            <span style={{ fontSize: 10, color: "#854d0e" }}>⚠ Needs review</span>
          )}
          <span style={{ fontSize: 11, color: "#94a3b8" }}>{expanded ? "▲" : "▼"}</span>
        </div>
      </button>

      {expanded && (
        <div style={{ padding: "10px 12px", display: "grid", gap: 8, background: "#fff" }}>
          {/* Input / Output */}
          {(step.observed_input || step.observed_output) && (
            <div style={{ display: "grid", gridTemplateColumns: step.observed_input && step.observed_output ? "1fr 1fr" : "1fr", gap: 8 }}>
              {step.observed_input && (
                <div style={{ background: "#f0f9ff", border: "1px solid #bae6fd", borderRadius: 8, padding: "7px 10px" }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "#0369a1", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 3 }}>Input</div>
                  <div style={{ fontSize: 12, color: "#0c4a6e" }}>{step.observed_input}</div>
                </div>
              )}
              {step.observed_output && (
                <div style={{ background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: 8, padding: "7px 10px" }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "#166534", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 3 }}>Output</div>
                  <div style={{ fontSize: 12, color: "#14532d" }}>{step.observed_output}</div>
                </div>
              )}
            </div>
          )}

          {/* Demonstrated feature */}
          {step.demonstrated_feature && (
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <span style={{ fontSize: 11, color: "#64748b", flexShrink: 0 }}>Feature:</span>
              <span style={{ fontSize: 11, fontWeight: 600, color: "#1e40af" }}>{step.demonstrated_feature}</span>
            </div>
          )}

          {/* Detected result values (only when OCR/frame is available) */}
          {step.detected_result_values.length > 0 && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#5b21b6", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
                Observed Outputs
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {step.detected_result_values.map((rv, i) => (
                  <span key={i} style={{
                    fontSize: 11, fontWeight: 600, padding: "3px 8px", borderRadius: 999,
                    background: "#fdf4ff", color: "#7e22ce", border: "1px solid #e9d5ff",
                  }}>
                    {rv.label}: {rv.value}
                    {rv.confidence !== null && <span style={{ fontWeight: 400 }}> ({Math.round(rv.confidence * 100)}%)</span>}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Visible text evidence */}
          {step.visible_text_evidence.filter(Boolean).length > 0 && (
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap", alignItems: "center" }}>
              <span style={{ fontSize: 10, color: "#64748b", flexShrink: 0 }}>Context:</span>
              {step.visible_text_evidence.filter(Boolean).slice(0, 3).map((t, i) => (
                <span key={i} style={{
                  fontSize: 10, padding: "2px 6px", borderRadius: 4,
                  background: "#f8fafc", color: "#475569", border: "1px solid #e2e8f0",
                  fontFamily: "monospace",
                }}>
                  {t.length > 50 ? `${t.slice(0, 47)}…` : t}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ObservedDemonstrationTimeline({
  demo,
}: {
  demo: ObservedDemonstration
}) {
  const [collapsed, setCollapsed] = React.useState(false)

  return (
    <div style={{ border: "1px solid #e9d5ff", borderRadius: 12, overflow: "hidden" }}>
      {/* Header */}
      <button
        type="button"
        onClick={() => setCollapsed(v => !v)}
        style={{
          width: "100%", textAlign: "left", background: "#fdf4ff",
          borderTop: "none", borderLeft: "none", borderRight: "none",
          borderBottom: collapsed ? "none" : "1px solid #e9d5ff",
          padding: "11px 14px", cursor: "pointer",
          display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10,
        }}
      >
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: "#5b21b6" }}>
            Observed Demonstration Timeline
          </div>
          <div style={{ fontSize: 11, color: "#6b21a8", marginTop: 2 }}>
            {demo.steps.length} step{demo.steps.length !== 1 ? "s" : ""} detected · {demo.target_app}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0, flexWrap: "wrap", justifyContent: "flex-end" }}>
          <DomEvidenceBadge status={demo.dom_evidence_status ?? demo.visible_evidence_status ?? "not_captured"} />
          {(demo.top_result_snippets?.length ?? 0) > 0 && (
            <span style={{
              display: "inline-flex", alignItems: "center", gap: 4,
              fontSize: 10, fontWeight: 600, padding: "3px 8px", borderRadius: 999,
              background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0",
            }}>
              ✦ {demo.top_result_snippets!.length} result-like block{demo.top_result_snippets!.length !== 1 ? "s" : ""} captured
            </span>
          )}
          <FrameAnalysisBadge status={demo.visual_analysis_status} />
          {demo.has_graphical_rendering && <GraphicalRenderingBadge />}
          <span style={{ fontSize: 11, color: "#94a3b8" }}>{collapsed ? "▼" : "▲"}</span>
        </div>
      </button>

      {!collapsed && (
        <div style={{ padding: "12px 14px", display: "grid", gap: 10, background: "#fff" }}>
          {/* Summary */}
          <p style={{ margin: 0, fontSize: 12, color: "#334155", lineHeight: 1.7, fontStyle: "italic" }}>
            {demo.summary}
          </p>

          {/* Result-like text snippets captured from DOM */}
          {(demo.top_result_snippets?.length ?? 0) > 0 && (
            <div style={{ background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: 8, padding: "8px 11px" }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#166534", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 5 }}>
                Result-like Text Captured from DOM
              </div>
              <div style={{ display: "grid", gap: 3 }}>
                {demo.top_result_snippets!.map((snippet, i) => (
                  <div key={i} style={{
                    fontSize: 11, color: "#14532d", padding: "4px 8px", borderRadius: 5,
                    background: "#dcfce7", border: "1px solid #bbf7d0",
                    fontFamily: "monospace", wordBreak: "break-word",
                  }}>
                    {snippet.length > 120 ? `${snippet.slice(0, 117)}…` : snippet}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Steps */}
          {demo.steps.length > 0 && (
            <div style={{ display: "grid", gap: 7 }}>
              {demo.steps.map((step, i) => (
                <DemonstrationStepCard key={i} step={step} index={i} />
              ))}
            </div>
          )}

          {/* Limitations */}
          {demo.limitations.length > 0 && (
            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8, padding: "8px 11px" }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
                Analysis Limitations
              </div>
              <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 3 }}>
                {demo.limitations.map((l, i) => (
                  <li key={i} style={{ display: "flex", gap: 6, fontSize: 11, color: "#64748b", lineHeight: 1.5 }}>
                    <span style={{ flexShrink: 0 }}>○</span><span>{l}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Historical analyses (stored before the qualitative-labels change) embed a
// numeric "Evidence strength: NN/100" sentence in their narrative text.
// Present it qualitatively at render time — the stored evidence itself is not
// rewritten, only this page's presentation of it.
function presentAnalysisNarrative(text: string): string {
  return text.replace(/Evidence strength: (\d+)\s*\/\s*100/g, (_m, n) => {
    const score = Number(n)
    const label = score >= 70 ? "strong" : score >= 40 ? "moderate" : "limited"
    return `Evidence strength: ${label}`
  })
}

function WorkflowAnalysisCard({
  analysis,
  finalEvaluation,
}: {
  analysis: WorkflowAnalysisResponse
  finalEvaluation?: FinalEvaluationResult | null
}) {
  const conf = CONFIDENCE_CONFIG[analysis.workflow_confidence] ?? CONFIDENCE_CONFIG.insufficient
  const analysisTypeLabel =
    analysis.analysis_type === "timeline_only" ? "Workflow Timeline Analysis"
    : analysis.analysis_type === "video_frame_analysis" ? "Video Frame Analysis"
    : "Full Multimodal Analysis"

  return (
    <div style={{ border: "1px solid #bfdbfe", borderRadius: 14, overflow: "hidden" }}>
      {/* Header */}
      <div style={{ background: "#eff6ff", borderBottom: "1px solid #bfdbfe", padding: "12px 16px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#1e40af" }}>Workflow Evidence Analysis</div>
          <div style={{ fontSize: 11, color: "#3b82f6", marginTop: 2 }}>AI Reviewed · {analysisTypeLabel}</div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          {/* Qualitative evidence labels only — numeric workflow/evidence-strength
              scores are never shown on the Website Proof page; combined scoring
              lives in the Passport / VBR report synthesis. */}
          <SourceScoreBadge label="Workflow evidence" source={workflowSourceScore(finalEvaluation ?? null, analysis)} />
          {/* Confidence badge */}
          <span style={{
            fontSize: 10, fontWeight: 700, letterSpacing: "0.08em", padding: "3px 9px",
            borderRadius: 999, background: conf.bg, color: conf.color, border: `1px solid ${conf.border}`,
          }}>
            {conf.label} CONFIDENCE
          </span>
        </div>
      </div>

      <div style={{ padding: "16px 16px", display: "grid", gap: 16 }}>
        {(() => {
          const filtered = analysis.filtered_unrelated_activity
          const count = filtered?.count ?? analysis.noise_filtered_count ?? 0
          const hosts = filtered?.hosts ?? []
          if (count <= 0) return null
          return (
            <div style={{ fontSize: 11, color: "#854d0e", background: "#fffbeb",
              border: "1px solid #fde68a", borderRadius: 8, padding: "8px 10px", lineHeight: 1.5 }}>
              Filtered unrelated activity: {count} frame/event{count !== 1 ? "s" : ""} outside the submitted website
              {hosts.length ? ` (${hosts.slice(0, 3).join(", ")})` : ""} were excluded from scoring.
            </div>
          )
        })()}

        {/* Summary */}
        <AnalysisSection title="Summary">
          <p style={{ margin: 0, fontSize: 12, color: "var(--ink-2)", lineHeight: 1.7 }}>
            {presentAnalysisNarrative(analysis.workflow_summary)}
          </p>
        </AnalysisSection>

        {/* Demonstrated actions */}
        {analysis.demonstrated_actions.length > 0 && (
          <AnalysisSection title="Demonstrated Workflow">
            <BulletList items={analysis.demonstrated_actions} />
          </AnalysisSection>
        )}

        {/* ── Observed Demonstration Timeline (v3) ─────────────────────────── */}
        {analysis.observed_demonstration && analysis.observed_demonstration.steps.length > 0 && (
          <ObservedDemonstrationTimeline demo={analysis.observed_demonstration} />
        )}

        {/* ── Video / Keyframe Evidence section ────────────────────────────── */}
        <VideoKeyframeEvidenceSection
          analysis={analysis}
          keyframeScore={videoKeyframeSourceScore(finalEvaluation ?? null, analysis)}
          ocrScore={ocrSourceScore(finalEvaluation ?? null, analysis)}
          qwenScore={qwenSourceScore(finalEvaluation ?? null, analysis)}
        />

        {/* ── Sequence Analysis (v6 — Week 3) ──────────────────────────────── */}
        {analysis.sequence_analysis && (
          <AnalysisSection title="Sequence Analysis">
            <SequenceAnalysisPanel analysis={analysis.sequence_analysis} viewMode="student" />
          </AnalysisSection>
        )}

        {/* Recruiter summary */}
        <AnalysisSection title="Recruiter Summary">
          <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 10, padding: "10px 12px" }}>
            <p style={{ margin: 0, fontSize: 12, color: "var(--ink-2)", lineHeight: 1.7, fontStyle: "italic" }}>
              {presentAnalysisNarrative(analysis.recruiter_summary)}
            </p>
          </div>
        </AnalysisSection>

        {/* Missing evidence and risk flags */}
        {(analysis.missing_evidence.length > 0 || analysis.risk_flags.length > 0) && (
          <div style={{ display: "grid", gap: 12, gridTemplateColumns: analysis.missing_evidence.length > 0 && analysis.risk_flags.length > 0 ? "1fr 1fr" : "1fr" }}>
            {analysis.missing_evidence.length > 0 && (
              <AnalysisSection title="Missing Evidence">
                <BulletList items={analysis.missing_evidence} color="#854d0e" />
              </AnalysisSection>
            )}
            {analysis.risk_flags.length > 0 && (
              <AnalysisSection title="Risk Flags">
                <BulletList items={analysis.risk_flags} color="#991b1b" />
              </AnalysisSection>
            )}
          </div>
        )}

        {/* Improvement suggestions — Website-Proof-scoped only. Historical
            analyses stored cross-proof advice (run GitHub analysis / live
            check / defense); those belong to other pipelines and are filtered
            from this page's presentation. */}
        {(() => {
          const websiteScoped = analysis.student_improvement_suggestions.filter(
            (s) => !/github|live website check|project defense/i.test(s),
          )
          if (websiteScoped.length === 0) return null
          return (
            <AnalysisSection title="Suggestions to Strengthen Your Proof">
              <BulletList items={websiteScoped} color="#1e40af" />
            </AnalysisSection>
          )
        })()}

        {/* Human review needed */}
        {analysis.human_review_needed && (
          <div style={{ background: "#fff7ed", border: "1px solid #fed7aa", borderRadius: 8, padding: "8px 12px", fontSize: 11, color: "#9a3412" }}>
            Human review recommended — confidence is low. A VeriBridge reviewer may follow up.
          </div>
        )}

        {/* Footer note */}
        <div style={{ borderTop: "1px solid var(--line)", paddingTop: 10 }}>
          <p style={{ margin: 0, fontSize: 11, color: "var(--muted)", lineHeight: 1.5 }}>
            Workflow analysis is based on browser events, DOM evidence, visual frames, video
            keyframes, and sequence analysis where available. This is a workflow-evidence analysis
            of the recorded website walkthrough — not a combined VeriBridge verification score.
          </p>
        </div>
      </div>
    </div>
  )
}

// ── Combined evidence summary ─────────────────────────────────────────────────

// Skills implemented in back-end code that are NOT directly visible in a browser.
const _CODE_EVIDENCE_SKILLS = new Set([
  "fastapi", "django", "flask", "starlette", "sqlalchemy", "alembic",
  "docker", "docker compose", "kubernetes",
  "pytorch", "tensorflow", "keras", "scikit-learn", "machine learning", "ml",
  "deep learning", "mlops", "celery", "redis", "mongodb", "postgresql",
  "langchain", "llamaindex", "huggingface", "openai", "anthropic",
  "python", "google cloud", "cloud run", "gcp", "aws", "azure",
])

function workflowSkillLabel(
  skill: string,
  analysis: WorkflowAnalysisResponse,
): { text: string; color: string } {
  const lower = skill.toLowerCase()
  if (analysis.supported_skills.some(s => s.toLowerCase() === lower))
    return { text: "Directly supported", color: "#166534" }
  if (analysis.weakly_supported_skills.some(s => s.toLowerCase() === lower)) {
    if (_CODE_EVIDENCE_SKILLS.has(lower))
      return { text: "Not directly visible — requires code evidence", color: "#854d0e" }
    return { text: "Partially supported", color: "#854d0e" }
  }
  if (analysis.unsupported_skills.some(s => s.toLowerCase() === lower))
    return { text: "No evidence found", color: "#991b1b" }
  return { text: "Not evaluated", color: "#94a3b8" }
}

function githubSkillLabel(
  skill: string,
  analysis: ExtensionProofGitHubAnalysisResponse,
): { text: string; color: string } {
  if (analysis.status !== "success") return { text: "Repo unavailable", color: "#991b1b" }
  const lower = skill.toLowerCase()
  if (analysis.matched_claimed_skills.some(s => s.toLowerCase() === lower))
    return { text: "Supported", color: "#166534" }
  if ((analysis.weakly_matched_claimed_skills ?? []).some(s => s.toLowerCase() === lower))
    return { text: "Partial evidence", color: "#854d0e" }
  if (analysis.missing_claimed_skills.some(s => s.toLowerCase() === lower))
    return { text: "Not detected in repo", color: "#991b1b" }
  return { text: "—", color: "#94a3b8" }
}

function overallSkillLabel(
  skill: string,
  workflowAnalysis: WorkflowAnalysisResponse,
  githubAnalysis: ExtensionProofGitHubAnalysisResponse,
): { text: string; color: string } {
  const lower = skill.toLowerCase()
  const wfSupported = workflowAnalysis.supported_skills.some(s => s.toLowerCase() === lower)
  const ghMatched = githubAnalysis.status === "success" &&
    githubAnalysis.matched_claimed_skills.some(s => s.toLowerCase() === lower)
  const ghWeakly = githubAnalysis.status === "success" &&
    (githubAnalysis.weakly_matched_claimed_skills ?? []).some(s => s.toLowerCase() === lower)

  if (wfSupported && ghMatched) return { text: "Supported (workflow + GitHub)", color: "#166534" }
  if (wfSupported) return { text: "Supported (workflow)", color: "#166534" }
  if (ghMatched) return { text: "Supported (GitHub)", color: "#166534" }
  if (ghWeakly) return { text: "Partial evidence (GitHub)", color: "#854d0e" }
  return { text: "Pending further review", color: "#64748b" }
}

// ── Final Evidence Evaluator Card ─────────────────────────────────────────────

const FOLLOWUP_INTENT_KEY_FE = "vb_followup_intent"

function clearFollowUpProofDraft() {
  try {
    sessionStorage.removeItem(FOLLOWUP_INTENT_KEY_FE)
  } catch { /* sessionStorage unavailable */ }
}

// ── Optional project proof boosters ───────────────────────────────────────────

// Website/Project Proof only uses project documents here. Profile and credential
// evidence belong to the future Work Passport / student profile credibility layer.
const FUTURE_MODULES: Array<{ sourceType: OptionalEvidenceSourceType; label: string; icon: string; description: string; placeholder: string }> = [
  { sourceType: "document", label: "Documents / PDF / Reports Evidence", icon: "📄", description: "Paste project report, research, TXT/Markdown, or PDF-extracted text.", placeholder: "Paste report text, e.g. Built a CNN model using TensorFlow and evaluated accuracy/F1-score..." },
]

const ACCEPTED_DOC_TYPES = ".pdf,.docx,.txt,.md"

export function FutureProofModulesSection({
  sessionId,
  documentScore,
  onAnalyzed,
}: {
  sessionId?: string
  documentScore?: FinalSourceScore
  onAnalyzed?: () => void
}) {
  const [openType, setOpenType] = useState<OptionalEvidenceSourceType | null>(null)
  const [texts, setTexts] = useState<Record<OptionalEvidenceSourceType, string>>({
    document: "",
    linkedin_profile: "",
    certificate_transcript: "",
  })
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState<OptionalEvidenceSourceType | null>(null)
  const [results, setResults] = useState<Partial<Record<OptionalEvidenceSourceType, OptionalEvidenceResponse & { _fileName?: string }>>>({})
  const [error, setError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  async function handleSubmit(sourceType: OptionalEvidenceSourceType) {
    if (!sessionId || submitting) return
    setSubmitting(sourceType)
    setError(null)
    try {
      let result: OptionalEvidenceResponse
      if (sourceType === "document" && selectedFile) {
        result = await uploadOptionalEvidenceFile(sessionId, selectedFile)
        setResults((prev) => ({ ...prev, [sourceType]: { ...result, _fileName: selectedFile.name } }))
      } else {
        result = await submitOptionalEvidence(sessionId, {
          source_type: sourceType,
          raw_text: texts[sourceType],
        })
        setResults((prev) => ({ ...prev, [sourceType]: result }))
      }
      onAnalyzed?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Optional evidence analysis failed.")
    } finally {
      setSubmitting(null)
    }
  }

  function uiStatus(sourceType: OptionalEvidenceSourceType): OptionalDocumentUiStatus {
    if (submitting === sourceType) return "processing"
    if (error) return "failed"
    const result = results[sourceType]
    if (!result) return "not_added"
    return result.status === "analyzed" ? "analyzed" : "failed"
  }

  return (
    <div style={{ display: "grid", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>
          Optional Evidence Boosters
        </div>
        <SourceScoreBadge label="Document Evidence Score" source={documentScore} />
        <div style={{ fontSize: 10, color: "#94a3b8", fontStyle: "italic" }}>
          Not adding these does not reduce your score
        </div>
      </div>
      {documentScore?.notes?.toLowerCase().includes("unrelated") && (
        <div role="alert" style={{ fontSize: 11, color: "#991b1b", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: "6px 10px", lineHeight: 1.5 }}>
          Document appears unrelated to the submitted proof. It was not used as a score booster.
        </div>
      )}
      {error && (
        <div role="alert" style={{ fontSize: 11, color: "#991b1b", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: "6px 10px" }}>
          {error}
        </div>
      )}
      {FUTURE_MODULES.map((m) => {
        const result = results[m.sourceType]
        const isOpen = openType === m.sourceType
        const status = uiStatus(m.sourceType)
        const analysisJson = result?.analysis_json ?? {}
        const resultFileName = (result as any)?._fileName ?? analysisJson?.file_name as string | undefined
        const resultFileType = analysisJson?.file_type as string | undefined
        const extractedPreview = analysisJson?.extracted_text_preview as string | undefined
        const isDocType = m.sourceType === "document"
        const canSubmit = isDocType
          ? (!!selectedFile || texts[m.sourceType].trim().length > 0)
          : texts[m.sourceType].trim().length > 0
        return (
        <div
          key={m.label}
          role="button"
          tabIndex={0}
          aria-expanded={isOpen}
          onClick={() => { if (!isOpen) setOpenType(m.sourceType) }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpenType(isOpen ? null : m.sourceType) }
          }}
          style={{
            border: "1px solid #e2e8f0", borderRadius: 10, padding: "10px 14px",
            background: "#f8fafc", display: "flex", gap: 10, alignItems: "flex-start",
            cursor: isOpen ? "default" : "pointer",
          }}
        >
          <span style={{ fontSize: 16, flexShrink: 0, marginTop: 1 }}>{m.icon}</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "#374151" }}>{m.label}</div>
            <div style={{ fontSize: 11, color: "#6b7280", marginTop: 2, lineHeight: 1.5 }}>{m.description}</div>
            <div style={{ marginTop: 5, fontSize: 10, fontWeight: 700, color: status === "analyzed" ? "#166534" : status === "processing" ? "#1d4ed8" : status === "failed" ? "#991b1b" : "#94a3b8" }}>
              status: {status}
            </div>
            {result && (
              <div style={{ marginTop: 6, display: "grid", gap: 4 }}>
                {resultFileName && (
                  <div style={{ fontSize: 10, color: "#374151", fontWeight: 600 }}>
                    {resultFileName}{resultFileType ? ` (${resultFileType})` : ""}
                  </div>
                )}
                <div style={{ fontSize: 10, color: result.evidence_objects.length > 0 ? "#166534" : "#854d0e", fontWeight: 700 }}>
                  {result.status} · {result.evidence_objects.length} extracted evidence item{result.evidence_objects.length !== 1 ? "s" : ""}
                </div>
                {result.evidence_objects.slice(0, 3).map((ev, i) => (
                  <div key={i} style={{ fontSize: 10, color: "#475569", lineHeight: 1.45, padding: "4px 6px", background: "#fff", border: "1px solid #e2e8f0", borderRadius: 5 }}>
                    <strong>Evidence snippet</strong>: {String(ev.snippet ?? "").slice(0, 160)}
                    {ev.page_number ? ` · page ${ev.page_number}` : ""}
                    {ev.section_label ? ` · ${String(ev.section_label)}` : ""}
                    {ev.line_start ? ` · lines ${ev.line_start}–${ev.line_end ?? "?"}` : ""}
                  </div>
                ))}
                {extractedPreview && (
                  <div style={{ fontSize: 9, color: "#94a3b8", fontStyle: "italic", marginTop: 2 }}>
                    Preview: {extractedPreview.slice(0, 120)}…
                  </div>
                )}
              </div>
            )}
            {isOpen && (
              <div style={{ marginTop: 8, display: "grid", gap: 6 }}>
                {isDocType && (
                  <div style={{ display: "grid", gap: 4 }}>
                    <div style={{ fontSize: 10, fontWeight: 600, color: "#374151" }}>Upload file (PDF, DOCX, TXT, MD)</div>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept={ACCEPTED_DOC_TYPES}
                        style={{ display: "none" }}
                        onChange={(e) => {
                          const f = e.target.files?.[0] ?? null
                          setSelectedFile(f)
                          if (f) setTexts((prev) => ({ ...prev, document: "" }))
                        }}
                      />
                      <button
                        type="button"
                        onClick={() => fileInputRef.current?.click()}
                        style={{ fontSize: 11, padding: "5px 10px", borderRadius: 6, border: "1px solid #d1d5db", background: "#fff", color: "#374151", cursor: "pointer" }}
                      >
                        {selectedFile ? "Change file" : "Choose file"}
                      </button>
                      {selectedFile && (
                        <span style={{ fontSize: 10, color: "#166534", fontWeight: 600 }}>
                          {selectedFile.name} ({(selectedFile.size / 1024).toFixed(0)} KB)
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 2 }}>
                      — or paste document text below —
                    </div>
                  </div>
                )}
                <textarea
                  value={texts[m.sourceType]}
                  onChange={(e) => {
                    setTexts((prev) => ({ ...prev, [m.sourceType]: e.target.value }))
                    if (e.target.value) setSelectedFile(null)
                  }}
                  placeholder={m.placeholder}
                  rows={4}
                  style={{ ...inp, resize: "vertical", fontFamily: "inherit" }}
                />
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    onClick={() => void handleSubmit(m.sourceType)}
                    disabled={!sessionId || submitting === m.sourceType || !canSubmit}
                    style={{ fontSize: 11, fontWeight: 700, padding: "6px 12px", borderRadius: 7, border: "none", background: "#111827", color: "#fff", cursor: (!sessionId || submitting || !canSubmit) ? "not-allowed" : "pointer", opacity: !canSubmit ? 0.5 : 1 }}
                  >
                    {submitting === m.sourceType ? "Analyzing..." : "Analyze Document Evidence"}
                  </button>
                  <span style={{ fontSize: 10, color: "#94a3b8" }}>Document is private unless you choose to share it.</span>
                </div>
              </div>
            )}
          </div>
          <button type="button" onClick={() => setOpenType(isOpen ? null : m.sourceType)}
            style={{ fontSize: 9, fontWeight: 600, letterSpacing: "0.06em", flexShrink: 0, padding: "2px 8px", borderRadius: 999, background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0", marginTop: 2, whiteSpace: "nowrap", cursor: "pointer" }}>
            {isOpen ? "Hide" : "Add document proof"}
          </button>
        </div>
      )})}
    </div>
  )
}

// ── Detected Skill Profile Section ───────────────────────────────────────────

function confidenceDot(conf: "high" | "medium" | "low"): string {
  if (conf === "high")   return "#22c55e"
  if (conf === "medium") return "#f59e0b"
  return "#94a3b8"
}

function confidenceChip(conf: "high" | "medium" | "low"): { bg: string; text: string; border: string } {
  if (conf === "high")   return { bg: "#dcfce7", text: "#166534", border: "#bbf7d0" }
  if (conf === "medium") return { bg: "#fef9c3", text: "#854d0e", border: "#fef08a" }
  return { bg: "#f1f5f9", text: "#64748b", border: "#e2e8f0" }
}

function statusChip(statusLabel: string | undefined, isInferred: boolean): { bg: string; text: string; border: string; label: string } {
  const raw = statusLabel ?? (isInferred ? "inferred from evidence" : "claimed")
  if (raw.includes("strongly supported")) return { bg: "#dcfce7", text: "#166534", border: "#bbf7d0", label: raw }
  if (raw.includes("partially")) return { bg: "#fef9c3", text: "#854d0e", border: "#fef08a", label: raw }
  if (raw.includes("inferred")) return { bg: "#ede9fe", text: "#6d28d9", border: "#ddd6fe", label: raw }
  return { bg: "#f1f5f9", text: "#64748b", border: "#e2e8f0", label: raw }
}

function SkillEvidenceCard({ s }: { s: DetectedSkillEntry }) {
  const [open, setOpen] = useState(false)
  const chip = confidenceChip(s.confidence)
  const sc = statusChip(s.status_label, s.is_inferred)
  const githubCodeEvidence = (s.evidence_objects ?? []).filter((obj) => obj.evidence_type === "github_file")
  const hasGithubCodeEvidence = githubCodeEvidence.length > 0
  const hasProofRefs = (s.keyframe_evidence?.length ?? 0) > 0
    || (s.github_evidence?.length ?? 0) > 0
    || hasGithubCodeEvidence
  const hasDetails = hasProofRefs || s.sources.length > 0

  return (
    <div style={{
      padding: "9px 11px", borderRadius: 9,
      background: s.is_inferred ? "#faf5ff" : "#f0fdf4",
      border: `1px solid ${s.is_inferred ? "#ddd6fe" : "#bbf7d0"}`,
      display: "flex", flexDirection: "column", gap: 5,
    }}>
      {/* Row: name + chips + toggle */}
      <div style={{ display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
        <span style={{ width: 7, height: 7, borderRadius: "50%",
          background: confidenceDot(s.confidence), flexShrink: 0 }} />
        <span style={{ fontSize: 12, fontWeight: 700,
          color: s.is_inferred ? "#5b21b6" : "#166534", flex: 1, minWidth: 0 }}>
          {s.skill}
        </span>
        <span style={{ fontSize: 9, fontWeight: 700, padding: "1px 6px",
          borderRadius: 999, background: chip.bg, color: chip.text,
          border: `1px solid ${chip.border}`, whiteSpace: "nowrap" }}>
          {s.confidence}
        </span>
        <span style={{ fontSize: 9, fontWeight: 600, padding: "1px 6px",
          borderRadius: 999, background: sc.bg, color: sc.text,
          border: `1px solid ${sc.border}`, whiteSpace: "nowrap" }}>
          {sc.label}
        </span>
        {hasDetails && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            style={{ fontSize: 9, fontWeight: 600, padding: "1px 7px", borderRadius: 5,
              border: "1px solid #ddd6fe", background: open ? "#ede9fe" : "transparent",
              color: "#6d28d9", cursor: "pointer", whiteSpace: "nowrap", flexShrink: 0 }}
          >
            {open ? "Hide ▲" : "Evidence ▼"}
          </button>
        )}
      </div>

      {/* Evidence support summary (always visible) */}
      <div style={{ fontSize: 10, color: "#64748b", lineHeight: 1.4, paddingLeft: 14 }}>
        {s.is_inferred ? `Evidence suggests: ${s.evidence_support}` : s.evidence_support}
      </div>

      {/* Expandable evidence details */}
      {open && (
        <div style={{ paddingLeft: 14, display: "flex", flexDirection: "column", gap: 6, marginTop: 2 }}>

          {/* Evidence sources chips */}
          {s.sources.length > 0 && (
            <div>
              <div style={{ fontSize: 8, fontWeight: 700, color: "#6b7280",
                textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 3 }}>
                Evidence sources
              </div>
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                {s.sources.map((src) => (
                  <span key={src} style={{ fontSize: 9, padding: "1px 6px",
                    borderRadius: 4, background: "#f1f5f9", color: "#475569",
                    border: "1px solid #e2e8f0" }}>
                    {src}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Keyframe / recording proof references */}
          {(s.keyframe_evidence?.length ?? 0) > 0 && (
            <div>
              <div style={{ fontSize: 8, fontWeight: 700, color: "#1d4ed8",
                textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 3 }}>
                Recording proof references
              </div>
              {s.keyframe_evidence!.map((ref, i) => (
                <div key={i} style={{ fontSize: 10, color: "#1e40af", lineHeight: 1.4,
                  padding: "3px 7px", background: "#eff6ff",
                  border: "1px solid #bfdbfe", borderRadius: 5, marginBottom: 3 }}>
                  {ref}
                </div>
              ))}
            </div>
          )}

          {/* GitHub proof references */}
          {hasGithubCodeEvidence && (
            <div>
              <div style={{ fontSize: 8, fontWeight: 700, color: "#374151",
                textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 3 }}>
                GitHub code proof references
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {githubCodeEvidence.map((obj, i) => (
                  <EvidenceObjectItem key={`github-code-${i}`} obj={obj} />
                ))}
              </div>
            </div>
          )}

          {!hasGithubCodeEvidence && (s.github_evidence?.length ?? 0) > 0 && (
            <div>
              <div style={{ fontSize: 8, fontWeight: 700, color: "#374151",
                textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 3 }}>
                GitHub proof references
              </div>
              {s.github_evidence!.map((ref, i) => (
                <div key={i} style={{ fontSize: 10, color: "#374151", lineHeight: 1.4,
                  padding: "3px 7px", background: "#f8fafc",
                  border: "1px solid #e2e8f0", borderRadius: 5, marginBottom: 3 }}>
                  {ref}
                </div>
              ))}
            </div>
          )}

          {/* What would strengthen this skill */}
          {s.confidence !== "high" && (
            <div style={{ fontSize: 9, color: "#92400e", fontStyle: "italic",
              borderTop: "1px dashed #fde68a", paddingTop: 4 }}>
              <strong style={{ fontStyle: "normal" }}>Strengthen:</strong>{" "}
              {s.is_inferred
                ? "Add a GitHub repository or record a focused demonstration to support this skill."
                : s.confidence === "medium"
                  ? "Record a more focused demonstration or run GitHub analysis to increase confidence."
                  : "Provide direct evidence — recording, GitHub analysis, or document — to confirm this skill."}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Grouped skill evidence card ───────────────────────────────────────────────

const _CATEGORY_BADGE_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  DATA:          { bg: "#eff6ff", text: "#1d4ed8", border: "#bfdbfe" },
  FRONTEND:      { bg: "#f0fdf4", text: "#166534", border: "#bbf7d0" },
  "AI/ML":       { bg: "#fdf4ff", text: "#7e22ce", border: "#e9d5ff" },
  DOCUMENTATION: { bg: "#fef9c3", text: "#854d0e", border: "#fef08a" },
  OPEN_SOURCE:   { bg: "#f1f5f9", text: "#334155", border: "#cbd5e1" },
  BACKEND:       { bg: "#fff7ed", text: "#9a3412", border: "#fed7aa" },
  DEVOPS:        { bg: "#f0fdf4", text: "#14532d", border: "#86efac" },
  PRODUCT:       { bg: "#fefce8", text: "#713f12", border: "#fde68a" },
  OTHER:         { bg: "#f8fafc", text: "#64748b", border: "#e2e8f0" },
}

const _SOURCE_LABEL_COLORS: Record<string, { bg: string; text: string }> = {
  Recording:       { bg: "#ede9fe", text: "#6d28d9" },
  DOM:             { bg: "#eff6ff", text: "#1d4ed8" },
  OCR:             { bg: "#f0fdf4", text: "#166534" },
  Qwen:            { bg: "#fdf4ff", text: "#7e22ce" },
  GitHub:          { bg: "#f1f5f9", text: "#1e293b" },
  "Live Website":  { bg: "#ecfdf5", text: "#065f46" },
  "Project Defense": { bg: "#fff7ed", text: "#9a3412" },
  Documents:       { bg: "#fefce8", text: "#713f12" },
  "LinkedIn/Profile": { bg: "#eff6ff", text: "#0369a1" },
  "Certificates/Transcript": { bg: "#fef9c3", text: "#854d0e" },
}

function SourceLabelChip({ label }: { label: string }) {
  const colors = _SOURCE_LABEL_COLORS[label] ?? { bg: "#f1f5f9", text: "#475569" }
  return (
    <span style={{
      fontSize: 9, fontWeight: 700, padding: "1px 6px", borderRadius: 4,
      background: colors.bg, color: colors.text, whiteSpace: "nowrap",
    }}>
      {label}
    </span>
  )
}

// ── Evidence object item ──────────────────────────────────────────────────────

const _EVIDENCE_TYPE_LABELS: Record<string, string> = {
  recording_keyframe: "Recording",
  ocr_text:           "OCR",
  dom_text:           "DOM",
  qwen_visual:        "Qwen",
  github_file:        "GitHub",
  document_snippet:   "Document",
  profile_snippet:    "LinkedIn/Profile",
  certificate_or_transcript_snippet: "Certificate",
  live_check:         "Live Website",
  transcript:         "Transcript",
  transcript_quote:   "Transcript Quote",
  document:           "Document",
}

const _EVIDENCE_TYPE_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  recording_keyframe: { bg: "#ede9fe", text: "#6d28d9", border: "#c4b5fd" },
  ocr_text:           { bg: "#f0fdf4", text: "#166534", border: "#bbf7d0" },
  dom_text:           { bg: "#eff6ff", text: "#1d4ed8", border: "#bfdbfe" },
  qwen_visual:        { bg: "#fdf4ff", text: "#7e22ce", border: "#e9d5ff" },
  github_file:        { bg: "#f1f5f9", text: "#1e293b", border: "#cbd5e1" },
  document_snippet:   { bg: "#fefce8", text: "#713f12", border: "#fde68a" },
  profile_snippet:    { bg: "#eff6ff", text: "#0369a1", border: "#bae6fd" },
  certificate_or_transcript_snippet: { bg: "#fef9c3", text: "#854d0e", border: "#fef08a" },
  live_check:         { bg: "#ecfdf5", text: "#065f46", border: "#a7f3d0" },
  transcript:         { bg: "#fff7ed", text: "#9a3412", border: "#fed7aa" },
  transcript_quote:   { bg: "#fff7ed", text: "#9a3412", border: "#fed7aa" },
  document:           { bg: "#fefce8", text: "#713f12", border: "#fde68a" },
}

const _EVIDENCE_KIND_LABELS: Record<string, { label: string; bg: string; text: string }> = {
  direct_workflow: { label: "Direct evidence", bg: "#dcfce7", text: "#166534" },
  contextual_page: { label: "Contextual", bg: "#fef9c3", text: "#854d0e" },
  embedded_video:  { label: "Embedded video", bg: "#fef2f2", text: "#991b1b" },
  unrelated:       { label: "Unrelated", bg: "#f1f5f9", text: "#94a3b8" },
  deployment_only: { label: "Deployment only", bg: "#eff6ff", text: "#1d4ed8" },
}

const _PROVENANCE_LABELS: Record<string, string> = {
  "Video / Keyframe Evidence": "Video / Keyframe Evidence",
  "OCR Evidence": "OCR Evidence",
  "Advanced Visual Reasoning": "Advanced Visual Reasoning",
  "GitHub Evidence": "GitHub Evidence",
  "Workflow Evidence Analysis": "Workflow Evidence Analysis",
  "Live Website Check": "Live Website Check",
  "Project Defense": "Project Defense",
  "Documents/PDF": "Documents/PDF",
  "LinkedIn/Profile": "LinkedIn/Profile",
  "Certificates/Transcript": "Certificates/Transcript",
}

export function getGitHubTraceActionLabel(obj: Pick<EvidenceObject, "github_url" | "file_path" | "line_start" | "line_end">): string {
  if (obj.github_url && obj.line_start != null && obj.line_end != null) return "Open GitHub lines"
  if (obj.github_url && obj.file_path) return "Open GitHub file"
  return "Open GitHub repo"
}

function TraceActionButton({ obj }: { obj: EvidenceObject }) {
  const action = obj.trace_action
  const available = obj.action_available !== false
  if (!action) return null
  if (action === "view_ocr" || action === "view_qwen") return null

  // Distinguish line-level / file-level / repo-level GitHub links
  const openGithubLabel = getGitHubTraceActionLabel(obj)

  const labels: Record<string, string> = {
    open_github:        openGithubLabel,
    view_keyframe:      "View keyframe",
    view_ocr:           "View OCR snippet",
    view_qwen:          "View Qwen observation",
    view_workflow_event:"View workflow event",
    view_live_check:    "View live check",
    view_document:      "View document page",
    view_transcript:    "View transcript",
  }
  const label = labels[action] ?? action

  if (!available || !obj.github_url) {
    return (
      <span style={{
        fontSize: 9, padding: "2px 7px", borderRadius: 4,
        border: "1px dashed #cbd5e1", color: "#94a3b8", background: "#f8fafc",
        cursor: "default", whiteSpace: "nowrap",
      }} title="This trace action is coming soon">
        {label} — coming soon
      </span>
    )
  }

  if (action === "open_github" && obj.github_url) {
    return (
      <a
        href={obj.github_url}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          fontSize: 9, padding: "2px 7px", borderRadius: 4,
          border: "1px solid #cbd5e1", color: "#1d4ed8", background: "#eff6ff",
          cursor: "pointer", whiteSpace: "nowrap", textDecoration: "none",
          fontWeight: 600,
        }}
      >
        {label} ↗
      </a>
    )
  }

  return (
    <span style={{
      fontSize: 9, padding: "2px 7px", borderRadius: 4,
      border: "1px dashed #cbd5e1", color: "#94a3b8", background: "#f8fafc",
      cursor: "default", whiteSpace: "nowrap",
    }}>
      {label} — coming soon
    </span>
  )
}

export function EvidenceObjectItem({ obj }: { obj: EvidenceObject }) {
  const colors = _EVIDENCE_TYPE_COLORS[obj.evidence_type] ?? { bg: "#f8fafc", text: "#64748b", border: "#e2e8f0" }
  const typeLabel = _EVIDENCE_TYPE_LABELS[obj.evidence_type] ?? obj.evidence_type
  const chip = confidenceChip(obj.confidence)
  const evKind = obj.evidence_kind ? _EVIDENCE_KIND_LABELS[obj.evidence_kind] : null
  const provenanceLabel = obj.provenance ? (_PROVENANCE_LABELS[obj.provenance] ?? obj.provenance) : null

  const lineLabel = obj.file_path
    ? (obj.line_start != null
        ? `L${obj.line_start}${obj.line_end != null && obj.line_end !== obj.line_start ? `–${obj.line_end}` : ""}`
        : obj.line_range
          ? `L${obj.line_range}`
          : "line trace not available yet")
    : null

  return (
    <div style={{ padding: "7px 10px", borderRadius: 7, background: colors.bg,
      border: `1px solid ${colors.border}`, display: "flex", flexDirection: "column", gap: 4 }}>

      {/* Row 1: type chip + confidence + provenance + evidence_kind */}
      <div style={{ display: "flex", alignItems: "center", gap: 5, flexWrap: "wrap" }}>
        <span style={{ fontSize: 9, fontWeight: 800, padding: "1px 6px", borderRadius: 4,
          background: colors.bg, color: colors.text, border: `1px solid ${colors.border}`,
          textTransform: "uppercase", letterSpacing: "0.07em", whiteSpace: "nowrap" }}>
          {typeLabel}
        </span>
        {provenanceLabel && (
          <span style={{ fontSize: 8, color: "#64748b", padding: "1px 5px", borderRadius: 3,
            background: "#f8fafc", border: "1px solid #e2e8f0", whiteSpace: "nowrap" }}>
            {provenanceLabel}
          </span>
        )}
        <span style={{ fontSize: 9, fontWeight: 700, padding: "1px 6px", borderRadius: 999,
          background: chip.bg, color: chip.text, border: `1px solid ${chip.border}`, whiteSpace: "nowrap" }}>
          {obj.confidence}
        </span>
        {evKind && (
          <span style={{ fontSize: 8, fontWeight: 700, padding: "1px 6px", borderRadius: 4,
            background: evKind.bg, color: evKind.text, whiteSpace: "nowrap" }}>
            {evKind.label}
          </span>
        )}
        {obj.timestamp_seconds != null && (
          <span style={{ fontSize: 9, color: "#94a3b8", fontFamily: "monospace" }}>
            @{obj.timestamp_seconds.toFixed(1)}s
          </span>
        )}
      </div>

      {/* Summary */}
      <div style={{ fontSize: 10, color: colors.text, lineHeight: 1.4 }}>{obj.short_summary}</div>

      {/* Repository */}
      {obj.repo_name && (
        <div style={{ fontSize: 9, color: "#475569", fontFamily: "monospace", lineHeight: 1.3 }}>
          {obj.repo_name}
        </div>
      )}

      {/* File path */}
      {obj.file_path && (
        <div style={{ fontSize: 9, color: "#475569", fontFamily: "monospace", lineHeight: 1.3 }}>
          {obj.file_path}{lineLabel ? ` ${lineLabel}` : ""}
          {!lineLabel && (
            <span style={{ color: "#94a3b8", fontFamily: "sans-serif", marginLeft: 4 }}>
              — file-level evidence available, line trace not available yet
            </span>
          )}
        </div>
      )}

      {(obj.evidence_type === "document_snippet" || obj.evidence_type === "profile_snippet" || obj.evidence_type === "certificate_or_transcript_snippet") && (
        <div style={{ fontSize: 9, color: "#475569", lineHeight: 1.35, display: "flex", flexWrap: "wrap", gap: 6 }}>
          {obj.page_number != null && <span>Page {obj.page_number}</span>}
          {obj.section_label && <span>Section: {obj.section_label}</span>}
          {obj.profile_url && (
            <a href={obj.profile_url} target="_blank" rel="noopener noreferrer" style={{ color: "#0369a1", textDecoration: "none", fontWeight: 600 }}>
              Open profile
            </a>
          )}
          {obj.issuer && <span>Issuer: {obj.issuer}</span>}
          {obj.title && <span>Title: {obj.title}</span>}
          {obj.date && <span>Date: {obj.date}</span>}
        </div>
      )}

      {/* Source-specific inline details */}
      {obj.evidence_type === "ocr_text" && (
        <div style={{ fontSize: 9, color: obj.text_snippet ? "#166534" : "#64748b",
          fontStyle: obj.text_snippet ? "italic" : "normal", lineHeight: 1.3 }}>
          {obj.text_snippet
            ? `OCR snippet: "${obj.text_snippet.slice(0, 180)}${obj.text_snippet.length > 180 ? "..." : ""}"`
            : "OCR snippet not available"}
        </div>
      )}

      {obj.evidence_type === "qwen_visual" && (
        <div style={{ fontSize: 9, color: "#6b21a8", lineHeight: 1.3 }}>
          {obj.short_summary
            ? `Qwen observation: ${obj.short_summary}`
            : "Qwen observation not available"}
        </div>
      )}

      {/* Text snippet (DOM / transcript / document) */}
      {obj.text_snippet && obj.evidence_type !== "ocr_text" && (
        <div style={{ fontSize: 9, color: "#64748b", fontStyle: "italic", lineHeight: 1.3 }}>
          &ldquo;{obj.text_snippet.slice(0, 140)}{obj.text_snippet.length > 140 ? "…" : ""}&rdquo;
        </div>
      )}

      {/* Code snippet */}
      {obj.code_snippet && (
        <pre style={{
          margin: 0, padding: "5px 7px", borderRadius: 5,
          background: "#0f172a", color: "#e2e8f0", border: "1px solid #334155",
          fontSize: 9, lineHeight: 1.35, whiteSpace: "pre-wrap", overflowWrap: "anywhere",
          maxHeight: 96, overflowY: "auto",
        }}>
          {obj.code_snippet.slice(0, 500)}
          {obj.code_snippet.length > 500 ? "..." : ""}
        </pre>
      )}

      {/* Matched keywords */}
      {obj.matched_keywords && obj.matched_keywords.length > 0 && (
        <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
          {obj.matched_keywords.slice(0, 8).map((kw, i) => (
            <span key={i} style={{ fontSize: 8, padding: "1px 5px", borderRadius: 3,
              background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0",
              fontFamily: "monospace" }}>
              {kw}
            </span>
          ))}
        </div>
      )}

      {/* Qwen context warning for embedded/contextual evidence */}
      {obj.evidence_type === "qwen_visual" && obj.evidence_kind === "embedded_video" && (
        <div style={{ fontSize: 9, color: "#991b1b", fontStyle: "italic", lineHeight: 1.3 }}>
          Contextual evidence only — embedded video detected, not direct proof of student skill.
        </div>
      )}
      {obj.evidence_type === "qwen_visual" && obj.evidence_kind === "contextual_page" && (
        <div style={{ fontSize: 9, color: "#854d0e", fontStyle: "italic", lineHeight: 1.3 }}>
          Contextual evidence — website content visible, not direct student interaction.
        </div>
      )}

      {/* Keyframe preview placeholder */}
      {obj.keyframe_url == null && obj.evidence_type === "recording_keyframe" && (
        <div style={{ fontSize: 9, color: "#94a3b8", fontStyle: "italic" }}>
          {obj.timestamp_seconds != null
            ? `Keyframe captured at ${obj.timestamp_seconds.toFixed(1)}s — preview coming soon.`
            : "Keyframe evidence captured — screenshot preview coming soon."}
        </div>
      )}

      {/* Live check deployment-only note */}
      {obj.evidence_type === "live_check" && (
        <div style={{ fontSize: 9, color: "#1d4ed8", fontStyle: "italic" }}>
          Deployment/accessibility evidence only — does not directly prove skill.
        </div>
      )}

      {/* Row: trace action button */}
      {obj.trace_action && (
        <div style={{ marginTop: 1 }}>
          <TraceActionButton obj={obj} />
        </div>
      )}
    </div>
  )
}

// ── Grouped skill evidence card (GitHub-style) ───────────────────────────────

function GroupedSkillEvidenceCard({
  group,
  selected,
  expanded,
  onToggle,
  onToggleExpand,
}: {
  group: GroupedSkillEvidence
  selected: boolean
  expanded: boolean
  onToggle: (groupName: string) => void
  onToggleExpand: (groupName: string) => void
}) {
  const confChip = confidenceChip(group.confidence)
  const catColors = _CATEGORY_BADGE_COLORS[group.category] ?? _CATEGORY_BADGE_COLORS.OTHER

  // Collect all evidence_objects from all skills, grouped by type
  const evidenceByType = new Map<string, EvidenceObject[]>()
  for (const skill of group.skills) {
    for (const obj of skill.evidence_objects ?? []) {
      if (!evidenceByType.has(obj.evidence_type)) evidenceByType.set(obj.evidence_type, [])
      evidenceByType.get(obj.evidence_type)!.push(obj)
    }
  }
  const evidenceTypes = Array.from(evidenceByType.keys())

  return (
    <div style={{
      border: `1px solid ${selected ? "#7c3aed" : catColors.border}`,
      borderRadius: 12,
      background: selected ? "#faf5ff" : "#fff",
      transition: "border-color 0.12s, background 0.12s",
    }}>
      {/* Header row */}
      <div style={{
        padding: "11px 14px",
        display: "grid",
        gridTemplateColumns: "auto 1fr auto",
        gap: 12,
        alignItems: "flex-start",
        background: selected ? "rgba(124,58,237,0.04)" : catColors.bg,
        borderRadius: "11px 11px 0 0",
      }}>
        {/* Checkbox */}
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggle(group.group_name)}
          style={{ marginTop: 3, width: 15, height: 15, cursor: "pointer", accentColor: "#7c3aed" }}
          title={selected ? "Deselect group" : "Select to save to profile"}
        />

        {/* Main content */}
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap", marginBottom: 4 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: "#1e293b" }}>{group.group_name}</span>
            <span style={{
              fontSize: 9, fontWeight: 800, padding: "1px 6px", borderRadius: 4,
              background: catColors.bg, color: catColors.text, border: `1px solid ${catColors.border}`,
              letterSpacing: "0.07em", textTransform: "uppercase", whiteSpace: "nowrap",
            }}>
              {group.category}
            </span>
            <span style={{
              fontSize: 9, fontWeight: 700, padding: "1px 7px", borderRadius: 999,
              background: confChip.bg, color: confChip.text, border: `1px solid ${confChip.border}`,
              whiteSpace: "nowrap",
            }}>
              {group.confidence} confidence
            </span>
          </div>
          <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>
            <strong style={{ color: "#475569" }}>{group.evidence_count}</strong> evidence location{group.evidence_count !== 1 ? "s" : ""} across{" "}
            <strong style={{ color: "#475569" }}>{group.sources_count}</strong> source{group.sources_count !== 1 ? "s" : ""}
          </div>
          {/* Source chips */}
          {group.source_labels.length > 0 && (
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {group.source_labels.map((lbl) => (
                <SourceLabelChip key={lbl} label={lbl} />
              ))}
            </div>
          )}
        </div>

        {/* Expand button */}
        <button
          type="button"
          onClick={() => onToggleExpand(group.group_name)}
          style={{
            fontSize: 10, fontWeight: 600, padding: "5px 10px", borderRadius: 7,
            border: `1px solid ${catColors.border}`, background: expanded ? catColors.bg : "transparent",
            color: catColors.text, cursor: "pointer", whiteSpace: "nowrap",
          }}
        >
          {expanded ? "Collapse ▲" : "Expand ▼"}
        </button>
      </div>

      {/* Expanded: evidence by type + individual skill cards */}
      {expanded && (
        <div style={{ borderTop: `1px solid ${catColors.border}`, padding: "14px", display: "flex", flexDirection: "column", gap: 14 }}>
          {/* Evidence objects by type */}
          {evidenceTypes.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: "0.09em",
                textTransform: "uppercase", color: "#475569" }}>
                Evidence Locations
              </div>
              {evidenceTypes.map((et) => {
                const objs = evidenceByType.get(et)!
                const typeLabel = _EVIDENCE_TYPE_LABELS[et] ?? et
                const colors = _EVIDENCE_TYPE_COLORS[et] ?? { bg: "#f8fafc", text: "#64748b", border: "#e2e8f0" }
                return (
                  <div key={et}>
                    <div style={{ fontSize: 9, fontWeight: 700, color: colors.text,
                      textTransform: "uppercase", letterSpacing: "0.07em",
                      marginBottom: 5, display: "flex", alignItems: "center", gap: 5 }}>
                      <span style={{ padding: "1px 6px", borderRadius: 4, background: colors.bg,
                        border: `1px solid ${colors.border}` }}>{typeLabel}</span>
                      <span style={{ color: "#94a3b8", fontSize: 9, fontWeight: 400, textTransform: "none" }}>
                        {objs.length} item{objs.length !== 1 ? "s" : ""}
                      </span>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      {objs.map((obj, i) => (
                        <EvidenceObjectItem key={`${et}-${i}`} obj={obj} />
                      ))}
                    </div>
                  </div>
                )
              })}

              {/* No evidence objects — show raw skill support text */}
              {evidenceTypes.length === 0 && (
                <div style={{ fontSize: 10, color: "#94a3b8", fontStyle: "italic" }}>
                  No detailed evidence objects captured for this group.
                </div>
              )}
            </div>
          )}

          {/* Individual skill cards */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: "0.09em",
              textTransform: "uppercase", color: "#475569" }}>
              Skills in this group
            </div>
            {group.skills.map((s) => (
              <SkillEvidenceCard key={s.skill} s={s} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

type FilterMode = "all" | "high" | "review"

export function DetectedSkillProfileSection({
  evaluation,
}: {
  evaluation: FinalEvaluationResult
}) {
  const groups = evaluation.grouped_skill_evidence ?? []
  const cap = evaluation.detected_capability
  const [filterMode, setFilterMode] = useState<FilterMode>("all")
  const [selectedGroups, setSelectedGroups] = useState<Set<string>>(new Set())
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())
  const [savedToast, setSavedToast] = useState(false)

  // Fall back to flat skill list if no grouped evidence
  const additionalSkills = evaluation.detected_additional_skills ?? []
  const flatSkills: DetectedSkillEntry[] = []
  const seen = new Set<string>()
  if (groups.length === 0) {
    for (const s of cap?.supporting_skills ?? []) {
      if (!seen.has(s.skill.toLowerCase())) { seen.add(s.skill.toLowerCase()); flatSkills.push(s) }
    }
    for (const s of additionalSkills) {
      if (!seen.has(s.skill.toLowerCase())) { seen.add(s.skill.toLowerCase()); flatSkills.push(s) }
    }
  }

  if (groups.length === 0 && !cap && flatSkills.length === 0) return null

  const totalEvidenceLocations = groups.reduce((n, g) => n + g.evidence_count, 0)
  const allSourceLabels = Array.from(new Set(groups.flatMap((g) => g.source_labels)))

  const filteredGroups =
    filterMode === "high" ? groups.filter((g) => g.confidence === "high")
    : filterMode === "review" ? groups.filter((g) => g.confidence !== "high")
    : groups

  const allSelected = filteredGroups.length > 0 && filteredGroups.every((g) => selectedGroups.has(g.group_name))

  function toggleGroup(groupName: string) {
    setSelectedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(groupName)) next.delete(groupName)
      else next.add(groupName)
      return next
    })
  }

  function toggleExpand(groupName: string) {
    setExpandedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(groupName)) next.delete(groupName)
      else next.add(groupName)
      return next
    })
  }

  function selectAll() {
    setSelectedGroups(new Set(filteredGroups.map((g) => g.group_name)))
  }

  function deselectAll() {
    setSelectedGroups(new Set())
  }

  function handleSave() {
    setSavedToast(true)
    setTimeout(() => setSavedToast(false), 2500)
  }

  return (
    <div style={{ border: "1px solid #c4b5fd", borderRadius: 14, overflow: "hidden", background: "#faf5ff" }}>
      {/* Header */}
      <div style={{
        background: "linear-gradient(135deg, #f5f3ff 0%, #ede9fe 100%)",
        borderBottom: "1px solid #ddd6fe",
        padding: "14px 16px",
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#5b21b6" }}>
              Review grouped skill evidence
            </div>
            {groups.length > 0 ? (
              <div style={{ fontSize: 11, color: "#6b7280", marginTop: 3 }}>
                Found <strong style={{ color: "#5b21b6" }}>{groups.length}</strong> grouped skill{groups.length !== 1 ? "s" : ""} from{" "}
                <strong style={{ color: "#5b21b6" }}>{totalEvidenceLocations}</strong> evidence location{totalEvidenceLocations !== 1 ? "s" : ""} across{" "}
                {allSourceLabels.join(", ")} sources
              </div>
            ) : (
              <div style={{ fontSize: 11, color: "#6b7280", marginTop: 3 }}>
                {flatSkills.length} skill{flatSkills.length !== 1 ? "s" : ""} detected from workflow evidence
              </div>
            )}
          </div>
          <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 8px", borderRadius: 999,
            background: "#ede9fe", color: "#7c3aed", border: "1px solid #c4b5fd" }}>
            AI INFERRED
          </span>
        </div>

        {/* Filter tabs + select controls */}
        {groups.length > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
            {(["all", "high", "review"] as FilterMode[]).map((mode) => {
              const count = mode === "all" ? groups.length
                : mode === "high" ? groups.filter((g) => g.confidence === "high").length
                : groups.filter((g) => g.confidence !== "high").length
              const label = mode === "all" ? `All (${count})`
                : mode === "high" ? `High confidence (${count})`
                : `Needs review (${count})`
              return (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setFilterMode(mode)}
                  style={{
                    fontSize: 10, fontWeight: 600, padding: "4px 10px", borderRadius: 6,
                    border: filterMode === mode ? "1px solid #7c3aed" : "1px solid #ddd6fe",
                    background: filterMode === mode ? "#ede9fe" : "transparent",
                    color: filterMode === mode ? "#7c3aed" : "#6b7280",
                    cursor: "pointer",
                  }}
                >
                  {label}
                </button>
              )
            })}
            <div style={{ flex: 1 }} />
            <button type="button" onClick={allSelected ? deselectAll : selectAll}
              style={{ fontSize: 9, fontWeight: 600, padding: "3px 9px", borderRadius: 5,
                border: "1px solid #ddd6fe", background: "transparent",
                color: "#7c3aed", cursor: "pointer" }}>
              {allSelected ? "Deselect all" : "Select all"}
            </button>
          </div>
        )}
      </div>

      <div style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
        {/* Grouped skill cards */}
        {filteredGroups.length > 0 && (
          filteredGroups.map((g) => (
            <GroupedSkillEvidenceCard
              key={g.group_name}
              group={g}
              selected={selectedGroups.has(g.group_name)}
              expanded={expandedGroups.has(g.group_name)}
              onToggle={toggleGroup}
              onToggleExpand={toggleExpand}
            />
          ))
        )}

        {/* Empty filter state */}
        {filteredGroups.length === 0 && groups.length > 0 && (
          <div style={{ fontSize: 11, color: "#94a3b8", fontStyle: "italic", textAlign: "center", padding: "12px 0" }}>
            No groups match this filter.
          </div>
        )}

        {/* Fallback: flat skill list when no groups */}
        {groups.length === 0 && flatSkills.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: "#6b7280",
              textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Detected Skills ({flatSkills.length})
            </div>
            {flatSkills.map((s) => (
              <SkillEvidenceCard key={s.skill} s={s} />
            ))}
          </div>
        )}

        {/* Save selected skills to profile */}
        {groups.length > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, paddingTop: 6,
            borderTop: "1px solid #ddd6fe", flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={handleSave}
              disabled={selectedGroups.size === 0}
              style={{
                fontSize: 11, fontWeight: 700, padding: "7px 16px", borderRadius: 8,
                border: selectedGroups.size > 0 ? "1px solid #7c3aed" : "1px solid #ddd6fe",
                background: selectedGroups.size > 0 ? "#7c3aed" : "#f5f3ff",
                color: selectedGroups.size > 0 ? "#fff" : "#a78bfa",
                cursor: selectedGroups.size > 0 ? "pointer" : "default",
                opacity: selectedGroups.size > 0 ? 1 : 0.6,
              }}
            >
              Save selected skills to profile
              {selectedGroups.size > 0 && ` (${selectedGroups.size})`}
            </button>
            {savedToast ? (
              <span style={{ fontSize: 10, color: "#6d28d9", fontWeight: 600 }}>
                ✓ Coming soon — skill save will be connected to your profile
              </span>
            ) : (
              <span style={{ fontSize: 9, color: "#94a3b8" }}>
                Select groups above, then save to your skill profile
              </span>
            )}
          </div>
        )}

        {/* Disclaimer */}
        <div style={{ fontSize: 9, color: "#94a3b8", fontStyle: "italic", lineHeight: 1.4,
          borderTop: "1px solid #ede9fe", paddingTop: 8 }}>
          Evidence uses recruiter-safe wording: &quot;Evidence suggests&quot; / &quot;Partially supported&quot; /
          &quot;Inferred&quot; — not &quot;verified&quot;. Expand each group to see evidence locations and proof references.
        </div>
      </div>
    </div>
  )
}

function actionPriorityColor(priority: "high" | "medium" | "low") {
  if (priority === "high")   return { bg: "#fef2f2", border: "#fecaca", text: "#991b1b", badge: "#fee2e2" }
  if (priority === "medium") return { bg: "#fffbeb", border: "#fde68a", text: "#92400e", badge: "#fef3c7" }
  return { bg: "#f8fafc", border: "#e2e8f0", text: "#475569", badge: "#f1f5f9" }
}

export function FinalEvaluatorCard({
  evaluation,
  sessionId,
  onRunGitHub,
  onRunLiveCheck,
  hideActions,
}: {
  evaluation: FinalEvaluationResult
  sessionId: string
  onRunGitHub?: () => void
  onRunLiveCheck?: () => void
  hideActions?: boolean
}) {
  const [savedSkill, setSavedSkill] = useState<string | null>(null)
  const { final_score, confidence, strong_proof, next_best_actions,
          final_student_summary, final_recruiter_summary, evidence_source_breakdown } = evaluation

  const scoreColor = final_score >= 80 ? "#166534" : final_score >= 60 ? "#854d0e" : "#991b1b"
  const scoreBg    = final_score >= 80 ? "#f0fdf4" : final_score >= 60 ? "#fffbeb" : "#fef2f2"
  const scoreBorder = final_score >= 80 ? "#bbf7d0" : final_score >= 60 ? "#fde68a" : "#fecaca"

  function handleRecordAction(skill: string, objective: string) {
    try {
      sessionStorage.setItem(FOLLOWUP_INTENT_KEY_FE, JSON.stringify({
        parentSessionId: sessionId,
        skill,
        objective,
      }))
    } catch { /* sessionStorage unavailable */ }
    setSavedSkill(skill)
  }

  function renderActionButton(action: NextBestAction) {
    if (action.action_type === "run_github_analysis" && onRunGitHub) {
      return (
        <button type="button" onClick={onRunGitHub}
          style={{ fontSize: 11, fontWeight: 700, padding: "6px 14px", borderRadius: 7,
            border: "none", background: "#111827", color: "#fff", cursor: "pointer" }}>
          {action.button_label}
        </button>
      )
    }
    if (action.action_type === "run_live_website_check" && onRunLiveCheck) {
      return (
        <button type="button" onClick={onRunLiveCheck}
          style={{ fontSize: 11, fontWeight: 700, padding: "6px 14px", borderRadius: 7,
            border: "none", background: "#1d4ed8", color: "#fff", cursor: "pointer" }}>
          {action.button_label}
        </button>
      )
    }
    if (action.is_recording) {
      if (savedSkill === action.target_skill) {
        return (
          <span style={{ fontSize: 10, color: "#6d28d9", fontWeight: 600,
            padding: "4px 10px", background: "#ede9fe",
            border: "1px solid #c4b5fd", borderRadius: 6 }}>
            ✓ Intent saved — click Start New Proof above
          </span>
        )
      }
      return (
        <button type="button"
          onClick={() => handleRecordAction(action.target_skill, action.objective)}
          style={{ fontSize: 11, fontWeight: 700, padding: "6px 14px", borderRadius: 7,
            border: "none", background: "#7c3aed", color: "#fff", cursor: "pointer" }}>
          {action.button_label}
        </button>
      )
    }
    // Non-recording, no handler wired: show neutral context, not a disabled CTA.
    return (
      <span style={{ fontSize: 10, color: "#94a3b8",
        padding: "4px 10px", background: "#f8fafc",
        border: "1px solid #e2e8f0", borderRadius: 6 }}>
        {action.button_label}
      </span>
    )
  }

  return (
    <div style={{ border: `1px solid ${scoreBorder}`, borderRadius: 14, overflow: "hidden" }}>
      {/* Header */}
      <div style={{ background: scoreBg, borderBottom: `1px solid ${scoreBorder}`,
        padding: "12px 16px", display: "flex", alignItems: "center",
        justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: scoreColor }}>
            Final Evidence Score
          </div>
          <div style={{ fontSize: 11, color: "#6b7280", marginTop: 2 }}>
            Combined across all available evidence sources
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span style={{ fontSize: 22, fontWeight: 800, color: scoreColor }}>
            {final_score}<span style={{ fontSize: 13, fontWeight: 500 }}>/100</span>
          </span>
          <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.08em",
            padding: "3px 9px", borderRadius: 999, background: scoreBorder,
            color: scoreColor, border: `1px solid ${scoreBorder}` }}>
            {confidence.toUpperCase()} CONFIDENCE
          </span>
        </div>
      </div>

      <div style={{ padding: "14px 16px", display: "grid", gap: 14 }}>
        {/* Summary for student */}
        {final_student_summary && (
          <p style={{ margin: 0, fontSize: 12, color: "#1e293b", lineHeight: 1.6 }}>
            {final_student_summary}
          </p>
        )}

        {/* Evidence source breakdown */}
        {evidence_source_breakdown && evidence_source_breakdown.length > 0 && (
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: "#64748b",
              textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
              Evidence Sources
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
              {evidence_source_breakdown.map((src) => {
                const isRun = src.status !== "not_run" && src.status !== "not_available" && src.status !== "not_applicable"
                const statusColor = src.status === "pass" ? "#166534"
                  : src.status === "partial" ? "#854d0e"
                  : src.status === "not_applicable" ? "#1e40af"
                  : src.status === "not_run" ? "#94a3b8"
                  : "#991b1b"
                const statusBg = src.status === "pass" ? "#f0fdf4"
                  : src.status === "partial" ? "#fffbeb"
                  : src.status === "not_applicable" ? "#eff6ff"
                  : "#f8fafc"
                const statusBorder = src.status === "pass" ? "#bbf7d0"
                  : src.status === "partial" ? "#fde68a"
                  : src.status === "not_applicable" ? "#bfdbfe"
                  : "#e2e8f0"
                const label = src.key.replace(/_/g, " ")
                const statusLabel = src.status === "not_run" ? "not run"
                  : src.status === "not_available" ? "not configured"
                  : src.status === "not_applicable" ? "not applicable"
                  : src.status
                return (
                  <div key={src.key} style={{ display: "flex", alignItems: "flex-start", gap: 5,
                    padding: "4px 7px", borderRadius: 5,
                    background: statusBg, border: `1px solid ${statusBorder}` }}>
                    <span style={{ fontSize: 10, fontWeight: 700, color: statusColor,
                      flexShrink: 0, lineHeight: 1.4 }}>
                      {src.status === "pass" ? "✓" : src.status === "partial" ? "~" : "○"}
                    </span>
                    <div>
                      <div style={{ fontSize: 9, fontWeight: 600, color: statusColor,
                        lineHeight: 1.3, textTransform: "capitalize" }}>{label}</div>
                      <div style={{ fontSize: 8, color: "#94a3b8", lineHeight: 1.2 }}>
                        {isRun ? `${src.score}/100` : statusLabel}
                        {src.notes ? ` · ${src.notes}` : ""}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Next best actions — hidden when hideActions=true (rendered separately after DetectedSkillProfile) */}
        {!hideActions && (
          strong_proof ? (
            <div style={{ padding: "8px 12px", background: "#f0fdf4",
              border: "1px solid #bbf7d0", borderRadius: 8,
              fontSize: 11, color: "#166534", fontWeight: 600 }}>
              Proof is strong. Optional improvements only.
            </div>
          ) : next_best_actions.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: "0.09em",
                textTransform: "uppercase", color: "#475569" }}>
                Recommended Next Actions
              </div>
              {next_best_actions.slice(0, 4).map((action, i) => {
                const pc = actionPriorityColor(action.priority)
                return (
                  <div key={action.action_type + i} style={{ padding: "10px 12px",
                    background: pc.bg, border: `1px solid ${pc.border}`,
                    borderRadius: 8, display: "flex", flexDirection: "column", gap: 6 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 9, fontWeight: 700, color: pc.text,
                        background: pc.badge, border: `1px solid ${pc.border}`,
                        borderRadius: 4, padding: "2px 7px", textTransform: "uppercase",
                        letterSpacing: "0.06em" }}>
                        {action.priority}
                      </span>
                      <span style={{ fontSize: 11, fontWeight: 700, color: "#1e293b" }}>
                        {action.target_skill}
                      </span>
                      {action.is_recording && (
                        <span style={{ fontSize: 9, color: "#6d28d9", fontWeight: 600,
                          background: "#ede9fe", border: "1px solid #ddd6fe",
                          borderRadius: 4, padding: "2px 6px" }}>recording</span>
                      )}
                    </div>
                    <div style={{ fontSize: 10, color: "#64748b", lineHeight: 1.4 }}>{action.reason}</div>
                    <div style={{ fontSize: 10, color: "#1e293b", lineHeight: 1.5,
                      padding: "5px 8px", background: "rgba(255,255,255,0.7)",
                      borderRadius: 5, border: `1px solid ${pc.border}` }}>
                      {action.objective}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      {action.recommended_duration && (
                        <span style={{ fontSize: 9, color: "#64748b" }}>
                          Duration: {action.recommended_duration}
                        </span>
                      )}
                      {renderActionButton(action)}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : null
        )}
      </div>
    </div>
  )
}

// ── Standalone Next Actions Section (rendered after Detected Skill Profile) ────

function RecommendationCard({
  action,
  index,
  sessionId,
}: {
  action: FinalRecommendationAction
  index: number
  sessionId?: string
}) {
  const [saved, setSaved] = useState(false)
  const [copied, setCopied] = useState(false)
  const pc = actionPriorityColor(action.priority)
  const prompt = `${action.title}\n\nWhy: ${action.reason}\nBuild: ${action.action}\nSkill learned: ${action.skill_learned}\nEvidence to record: ${action.evidence_to_record}`

  function saveGoal() {
    setSaved(true)
  }

  function startFollowup() {
    try {
      sessionStorage.setItem(FOLLOWUP_INTENT_KEY_FE, JSON.stringify({
        parentSessionId: sessionId ?? "",
        skill: action.skill_learned,
        objective: action.action,
      }))
    } catch { /* unavailable */ }
    setSaved(true)
  }

  async function copyPrompt() {
    try {
      await navigator.clipboard?.writeText(prompt)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <details style={{ padding: "10px 12px",
      background: pc.bg, border: `1px solid ${pc.border}`,
      borderRadius: 8 }}>
      <summary style={{ cursor: "pointer", listStyle: "none" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span style={{ fontSize: 9, fontWeight: 700, color: pc.text,
            background: pc.badge, border: `1px solid ${pc.border}`,
            borderRadius: 4, padding: "2px 7px", textTransform: "uppercase",
            letterSpacing: "0.06em" }}>
            {action.difficulty}
          </span>
          <span style={{ fontSize: 11, fontWeight: 700, color: "#1e293b" }}>
            {index + 1}. {action.title}
          </span>
          <span style={{ fontSize: 9, color: "#64748b" }}>{action.estimated_time}</span>
        </div>
      </summary>
      <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
        <div style={{ fontSize: 10, color: "#64748b", lineHeight: 1.45 }}>
          <b>Why:</b> {action.reason}
        </div>
        <div style={{ fontSize: 10, color: "#1e293b", lineHeight: 1.5,
          padding: "6px 8px", background: "rgba(255,255,255,0.72)",
          borderRadius: 5, border: `1px solid ${pc.border}` }}>
          <b>Build:</b> {action.action}
        </div>
        <div style={{ fontSize: 10, color: "#475569", lineHeight: 1.45 }}>
          <b>Skill learned:</b> {action.skill_learned}
        </div>
        <div style={{ fontSize: 10, color: "#475569", lineHeight: 1.45 }}>
          <b>Evidence to record:</b> {action.evidence_to_record}
        </div>
        <div style={{ fontSize: 9, color: "#64748b", lineHeight: 1.4 }}>
          Source: {action.source_reason}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <button type="button" onClick={saveGoal}
            style={{ fontSize: 10, fontWeight: 700, padding: "5px 10px", borderRadius: 7,
              border: "1px solid #cbd5e1", background: "#fff", color: "#334155", cursor: "pointer" }}>
            {saved ? "Saved to improvement plan" : "Save as learning goal"}
          </button>
          <button type="button" onClick={startFollowup}
            style={{ fontSize: 10, fontWeight: 700, padding: "5px 10px", borderRadius: 7,
              border: "none", background: "#7c3aed", color: "#fff", cursor: "pointer" }}>
            Start follow-up proof
          </button>
          <button type="button" onClick={() => void copyPrompt()}
            style={{ fontSize: 10, fontWeight: 700, padding: "5px 10px", borderRadius: 7,
              border: "1px solid #d1d5db", background: "#f8fafc", color: "#475569", cursor: "pointer" }}>
            {copied ? "Copied" : "Copy task prompt"}
          </button>
          {saved && (
            <span style={{ fontSize: 10, color: "#166534" }}>
              backend persistence coming soon
            </span>
          )}
        </div>
      </div>
    </details>
  )
}

export function FinalRecommendationsSection({
  evaluation,
  sessionId,
  onRunGitHub,
  onRunLiveCheck,
}: {
  evaluation: FinalEvaluationResult
  sessionId: string
  onRunGitHub?: () => void
  onRunLiveCheck?: () => void
}) {
  const [savedTitle, setSavedTitle] = useState<string | null>(null)
  const recs = evaluation.recommendations
  if (!recs) return (
    <StandaloneNextActionsSection
      evaluation={evaluation}
      sessionId={sessionId}
      onRunGitHub={onRunGitHub}
      onRunLiveCheck={onRunLiveCheck}
    />
  )

  function handleRecord(action: FinalRecommendationAction) {
    try {
      sessionStorage.setItem(FOLLOWUP_INTENT_KEY_FE, JSON.stringify({
        parentSessionId: sessionId,
        skill: action.skill_learned,
        objective: action.action,
      }))
    } catch { /* unavailable */ }
    setSavedTitle(action.title)
  }

  function renderProofButton(action: FinalRecommendationAction) {
    if (action.action_type === "run_github_analysis" && onRunGitHub) {
      return <button type="button" onClick={onRunGitHub}
        style={{ fontSize: 11, fontWeight: 700, padding: "6px 14px", borderRadius: 7,
          border: "none", background: "#111827", color: "#fff", cursor: "pointer" }}>{action.title}</button>
    }
    if (action.action_type === "run_live_website_check" && onRunLiveCheck) {
      return <button type="button" onClick={onRunLiveCheck}
        style={{ fontSize: 11, fontWeight: 700, padding: "6px 14px", borderRadius: 7,
          border: "none", background: "#1d4ed8", color: "#fff", cursor: "pointer" }}>{action.title}</button>
    }
    if (action.action_type.startsWith("record_")) {
      if (savedTitle === action.title) {
        return <span style={{ fontSize: 10, color: "#6d28d9", fontWeight: 600,
          padding: "4px 10px", background: "#ede9fe",
          border: "1px solid #c4b5fd", borderRadius: 6 }}>
          ✓ Intent saved — click Start New Proof above
        </span>
      }
      return <button type="button" onClick={() => handleRecord(action)}
        style={{ fontSize: 11, fontWeight: 700, padding: "6px 14px", borderRadius: 7,
          border: "none", background: "#7c3aed", color: "#fff", cursor: "pointer" }}>{action.title}</button>
    }
    return <span style={{ fontSize: 10, color: "#94a3b8",
      padding: "4px 10px", background: "#f8fafc",
      border: "1px solid #e2e8f0", borderRadius: 6 }}>{action.title}</span>
  }

  if (recs.mode === "project_growth" || evaluation.final_score >= 80) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: 10, color: "#166534", background: "#f0fdf4",
          border: "1px solid #bbf7d0", borderRadius: 8, padding: "8px 10px", lineHeight: 1.45 }}>
          Proof is strong. These are optional skill improvements — not required for recruiter sharing.
        </div>
        {recs.learning_actions.slice(0, 5).map((action, i) => (
          <RecommendationCard key={action.action_type + i} action={action} index={i} sessionId={sessionId} />
        ))}
      </div>
    )
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {recs.proof_actions.length > 0 && (
        <>
          <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: "0.09em",
            textTransform: "uppercase", color: "#475569" }}>
            Recommended Next Actions
          </div>
          <div style={{ fontSize: 10, color: "#64748b", marginTop: -4 }}>
            Strengthen recruiter-ready evidence by fixing the weakest source first.
          </div>
          {recs.proof_actions.slice(0, 4).map((action, i) => {
            const pc = actionPriorityColor(action.priority)
            return (
              <div key={action.action_type + i} style={{ padding: "10px 12px",
                background: pc.bg, border: `1px solid ${pc.border}`,
                borderRadius: 8, display: "flex", flexDirection: "column", gap: 6 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 9, fontWeight: 700, color: pc.text,
                    background: pc.badge, border: `1px solid ${pc.border}`,
                    borderRadius: 4, padding: "2px 7px", textTransform: "uppercase",
                    letterSpacing: "0.06em" }}>
                    {action.priority}
                  </span>
                  <span style={{ fontSize: 11, fontWeight: 700, color: "#1e293b" }}>{action.title}</span>
                </div>
                <div style={{ fontSize: 10, color: "#64748b", lineHeight: 1.4 }}>{action.reason}</div>
                <div style={{ fontSize: 10, color: "#1e293b", lineHeight: 1.5,
                  padding: "5px 8px", background: "rgba(255,255,255,0.7)",
                  borderRadius: 5, border: `1px solid ${pc.border}` }}>{action.action}</div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 9, color: "#64748b" }}>{action.source_reason}</span>
                  {renderProofButton(action)}
                </div>
              </div>
            )
          })}
        </>
      )}
      {recs.learning_actions.length > 0 && (
        <>
          <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: "0.09em",
            textTransform: "uppercase", color: "#64748b", marginTop: 4 }}>
            Optional learning opportunities
          </div>
          {recs.learning_actions.slice(0, 3).map((action, i) => (
            <RecommendationCard key={action.action_type + i} action={action} index={i} sessionId={sessionId} />
          ))}
        </>
      )}
    </div>
  )
}

function StandaloneNextActionsSection({
  evaluation,
  sessionId,
  onRunGitHub,
  onRunLiveCheck,
}: {
  evaluation: FinalEvaluationResult
  sessionId: string
  onRunGitHub?: () => void
  onRunLiveCheck?: () => void
}) {
  const [savedSkill, setSavedSkill] = useState<string | null>(null)
  const { final_score, strong_proof, next_best_actions } = evaluation

  if (strong_proof) {
    return (
      <div style={{ padding: "8px 12px", background: "#f0fdf4",
        border: "1px solid #bbf7d0", borderRadius: 8,
        fontSize: 11, color: "#166534", fontWeight: 600 }}>
        Proof is strong. Optional improvements only.
      </div>
    )
  }

  if (final_score >= 80 || next_best_actions.length === 0) return null

  function handleRecord(skill: string, objective: string) {
    try {
      sessionStorage.setItem(FOLLOWUP_INTENT_KEY_FE, JSON.stringify({
        parentSessionId: sessionId, skill, objective,
      }))
    } catch { /* unavailable */ }
    setSavedSkill(skill)
  }

  function renderBtn(action: NextBestAction) {
    if (action.action_type === "run_github_analysis" && onRunGitHub) {
      return (
        <button type="button" onClick={onRunGitHub}
          style={{ fontSize: 11, fontWeight: 700, padding: "6px 14px", borderRadius: 7,
            border: "none", background: "#111827", color: "#fff", cursor: "pointer" }}>
          {action.button_label}
        </button>
      )
    }
    if (action.action_type === "run_live_website_check" && onRunLiveCheck) {
      return (
        <button type="button" onClick={onRunLiveCheck}
          style={{ fontSize: 11, fontWeight: 700, padding: "6px 14px", borderRadius: 7,
            border: "none", background: "#1d4ed8", color: "#fff", cursor: "pointer" }}>
          {action.button_label}
        </button>
      )
    }
    if (action.is_recording) {
      if (savedSkill === action.target_skill) {
        return (
          <span style={{ fontSize: 10, color: "#6d28d9", fontWeight: 600,
            padding: "4px 10px", background: "#ede9fe",
            border: "1px solid #c4b5fd", borderRadius: 6 }}>
            ✓ Intent saved — click Start New Proof above
          </span>
        )
      }
      return (
        <button type="button"
          onClick={() => handleRecord(action.target_skill, action.objective)}
          style={{ fontSize: 11, fontWeight: 700, padding: "6px 14px", borderRadius: 7,
            border: "none", background: "#7c3aed", color: "#fff", cursor: "pointer" }}>
          {action.button_label}
        </button>
      )
    }
    return (
      <span style={{ fontSize: 10, color: "#94a3b8",
        padding: "4px 10px", background: "#f8fafc",
        border: "1px solid #e2e8f0", borderRadius: 6 }}>
        {action.button_label}
      </span>
    )
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: "0.09em",
        textTransform: "uppercase", color: "#475569" }}>
        Recommended Next Actions
      </div>
      <div style={{ fontSize: 10, color: "#64748b", marginTop: -4 }}>
        Strengthen your proof — complete the highest-priority action below.
      </div>
      {next_best_actions.slice(0, 4).map((action, i) => {
        const pc = actionPriorityColor(action.priority)
        return (
          <div key={action.action_type + i} style={{ padding: "10px 12px",
            background: pc.bg, border: `1px solid ${pc.border}`,
            borderRadius: 8, display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              <span style={{ fontSize: 9, fontWeight: 700, color: pc.text,
                background: pc.badge, border: `1px solid ${pc.border}`,
                borderRadius: 4, padding: "2px 7px", textTransform: "uppercase",
                letterSpacing: "0.06em" }}>
                {action.priority}
              </span>
              <span style={{ fontSize: 11, fontWeight: 700, color: "#1e293b" }}>
                {action.target_skill}
              </span>
              {action.is_recording && (
                <span style={{ fontSize: 9, color: "#6d28d9", fontWeight: 600,
                  background: "#ede9fe", border: "1px solid #ddd6fe",
                  borderRadius: 4, padding: "2px 6px" }}>recording</span>
              )}
            </div>
            <div style={{ fontSize: 10, color: "#64748b", lineHeight: 1.4 }}>{action.reason}</div>
            <div style={{ fontSize: 10, color: "#1e293b", lineHeight: 1.5,
              padding: "5px 8px", background: "rgba(255,255,255,0.7)",
              borderRadius: 5, border: `1px solid ${pc.border}` }}>
              {action.objective}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              {action.recommended_duration && (
                <span style={{ fontSize: 9, color: "#64748b" }}>
                  Duration: {action.recommended_duration}
                </span>
              )}
              {renderBtn(action)}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function CombinedEvidenceSummaryCard({
  claimedSkills,
  workflowAnalysis,
  githubAnalysis,
  liveCheck,
}: {
  claimedSkills: string[]
  workflowAnalysis: WorkflowAnalysisResponse
  githubAnalysis: ExtensionProofGitHubAnalysisResponse
  liveCheck: LiveWebsiteCheckResponse | null
}) {
  if (!claimedSkills.length) return null

  return (
    <div style={{ border: "1px solid #e5e7eb", borderRadius: 14, overflow: "hidden" }}>
      <div style={{
        background: "#f9fafb", borderBottom: "1px solid #e5e7eb",
        padding: "12px 16px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10,
      }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#111827" }}>Cross-Evidence Skill Summary</div>
          <div style={{ fontSize: 11, color: "#6b7280", marginTop: 2 }}>
            How each claimed skill is supported across evidence sources
          </div>
        </div>
        <span style={{
          fontSize: 9, fontWeight: 700, letterSpacing: "0.08em",
          padding: "3px 8px", borderRadius: 6,
          background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a",
        }}>
          FINAL VERIFICATION PENDING
        </span>
      </div>

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ background: "#f3f4f6", borderBottom: "1px solid #e5e7eb" }}>
              {["Skill", "Workflow Evidence", "GitHub Evidence", "Live Website", "Overall"].map(h => (
                <th key={h} style={{ padding: "8px 12px", textAlign: "left", fontWeight: 600, color: "#374151", fontSize: 11, whiteSpace: "nowrap" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {claimedSkills.map((skill, i) => {
              const wf = workflowSkillLabel(skill, workflowAnalysis)
              const gh = githubSkillLabel(skill, githubAnalysis)
              const overall = overallSkillLabel(skill, workflowAnalysis, githubAnalysis)
              const liveLabel = liveCheck
                ? liveCheck.is_reachable ? { text: "App reachable", color: "#166534" } : { text: "Not reachable", color: "#991b1b" }
                : { text: "N/A", color: "#94a3b8" }
              return (
                <tr key={skill} style={{ borderBottom: i < claimedSkills.length - 1 ? "1px solid #f3f4f6" : "none" }}>
                  <td style={{ padding: "9px 12px", fontWeight: 600, color: "#111827", whiteSpace: "nowrap" }}>{skill}</td>
                  <td style={{ padding: "9px 12px", color: wf.color }}>{wf.text}</td>
                  <td style={{ padding: "9px 12px", color: gh.color }}>{gh.text}</td>
                  <td style={{ padding: "9px 12px", color: liveLabel.color }}>{liveLabel.text}</td>
                  <td style={{ padding: "9px 12px", color: overall.color, fontWeight: 600 }}>{overall.text}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div style={{ padding: "10px 14px", borderTop: "1px solid #f3f4f6", background: "#f9fafb" }}>
        <p style={{ margin: 0, fontSize: 11, color: "#6b7280", lineHeight: 1.55 }}>
          This summary combines workflow timeline, GitHub repository, and live website evidence.
          Final Verification remains pending until all evidence is reviewed.
          Back-end skills (FastAPI, Docker, ML models, etc.) require code/repository evidence — they are not visible in browser recordings.
        </p>
      </div>
    </div>
  )
}

// ── GitHub Analysis components ────────────────────────────────────────────────

export function GitHubAnalysisInProgress({
  simProgress,
  simStageIdx,
}: {
  simProgress: number
  simStageIdx: number
}) {
  return (
    <div style={{ border: "1px solid #d1d5db", borderRadius: 12, background: "#f9fafb", padding: "14px 16px", display: "grid", gap: 12 }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#111827" }}>GitHub Evidence Analysis in Progress</div>
        <p style={{ margin: "4px 0 0", fontSize: 12, color: "#374151", lineHeight: 1.65 }}>
          VeriBridge is analysing your GitHub repository. This usually takes 10–30 seconds.
        </p>
      </div>

      <div>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
          <span style={{ fontSize: 11, color: "#6b7280" }}>Analysis in progress</span>
          <span style={{ fontSize: 11, fontWeight: 700, color: "#111827" }}>{simProgress}%</span>
        </div>
        <div style={{ height: 6, background: "#e5e7eb", borderRadius: 999 }}>
          <div
            style={{
              height: 6, borderRadius: 999, background: "#111827",
              width: `${simProgress}%`, transition: "width 0.5s ease",
            }}
          />
        </div>
      </div>

      <div style={{ display: "grid", gap: 6 }}>
        {GITHUB_STAGES.map((stage, i) => {
          const isDone = i < simStageIdx
          const isCurrent = i === simStageIdx
          return (
            <div key={stage.key} style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <span style={{
                fontSize: 12, fontWeight: 700,
                color: isDone ? "#065f46" : isCurrent ? "#111827" : "#9ca3af",
                width: 14, flexShrink: 0, textAlign: "center",
              }}>
                {isDone ? "✓" : isCurrent ? "…" : "○"}
              </span>
              <span style={{ fontSize: 12, color: isDone ? "#064e3b" : isCurrent ? "#111827" : "#9ca3af" }}>
                {stage.label}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function confidenceScoreToLabel(score: number): { label: string; bg: string; color: string; border: string } {
  if (score >= 0.7) return { label: "HIGH", bg: "#dcfce7", color: "#166534", border: "#bbf7d0" }
  if (score >= 0.4) return { label: "MEDIUM", bg: "#fef9c3", color: "#854d0e", border: "#fef08a" }
  if (score > 0) return { label: "LOW", bg: "#fef2f2", color: "#991b1b", border: "#fecaca" }
  return { label: "INSUFFICIENT", bg: "#f1f5f9", color: "#475569", border: "#e2e8f0" }
}

export function GitHubAnalysisCard({
  analysis,
  onRerun,
  sourceScore,
}: {
  analysis: ExtensionProofGitHubAnalysisResponse
  onRerun: () => void
  sourceScore?: FinalSourceScore
}) {
  const success = analysis.status === "success"
  const unavailable = analysis.status === "private_or_unavailable"
  const conf = confidenceScoreToLabel(analysis.confidence_score)
  const confidencePct = Math.round(analysis.confidence_score * 100)

  const headerBg    = success ? "#f9fafb" : "#fef2f2"
  const headerBorder = success ? "#e5e7eb" : "#fecaca"
  const headerTitle = success ? "#111827" : "#991b1b"
  const headerSub   = success ? "#6b7280" : "#dc2626"

  const FEATURE_LABELS: Record<string, string> = {
    readme:           "README",
    docker:           "Docker",
    docker_compose:   "Docker Compose",
    testing:          "Automated tests",
    machine_learning: "Machine learning",
    ai_llm:           "AI / LLM",
    api_framework:    "API framework",
    database:         "Database",
    env_config:       "Env config",
    deployment:       "Deployment config",
    makefile:         "Makefile",
  }

  return (
    <div style={{ border: `1px solid ${success ? "#e5e7eb" : "#fecaca"}`, borderRadius: 14, overflow: "hidden" }}>
      {/* Header */}
      <div style={{
        background: headerBg,
        borderBottom: `1px solid ${headerBorder}`,
        padding: "12px 16px",
        display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap",
      }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: headerTitle }}>
            GitHub Evidence Analysis — {success ? "AI Reviewed" : unavailable ? "Repository Unavailable" : "Failed"}
          </div>
          <div style={{ fontSize: 11, color: headerSub, marginTop: 2 }}>
            {success ? "Repository analysed · evidence extracted" : unavailable ? "Repository is private or could not be reached" : "Analysis encountered an error"}
          </div>
        </div>
        {success && (
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <SourceScoreBadge label="GitHub Score" source={sourceScore} />
            <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <span style={{ fontSize: 11, color: "#6b7280" }}>Confidence</span>
              <span style={{ fontSize: 14, fontWeight: 800, color: "#111827" }}>
                {confidencePct}<span style={{ fontSize: 10, fontWeight: 500 }}>%</span>
              </span>
            </div>
            <span style={{
              fontSize: 10, fontWeight: 700, letterSpacing: "0.08em", padding: "3px 9px",
              borderRadius: 999, background: conf.bg, color: conf.color, border: `1px solid ${conf.border}`,
            }}>
              {conf.label}
            </span>
          </div>
        )}
      </div>

      <div style={{ padding: "14px 16px", display: "grid", gap: 14 }}>
        {/* Repo URL */}
        <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
          <span style={{ fontSize: 11, color: "var(--muted)", minWidth: 100, flexShrink: 0 }}>Repository</span>
          <a
            href={analysis.repo_url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontSize: 12, color: "#1d4ed8", wordBreak: "break-all", textDecoration: "none" }}
          >
            {analysis.repo_url} ↗
          </a>
        </div>

        {/* Recruiter summary */}
        {analysis.recruiter_summary && (
          <div style={{
            background: success ? "#f9fafb" : "#fef2f2",
            border: `1px solid ${success ? "#e5e7eb" : "#fecaca"}`,
            borderRadius: 10, padding: "10px 12px",
          }}>
            <p style={{ margin: 0, fontSize: 12, color: success ? "#374151" : "#991b1b", lineHeight: 1.7, fontStyle: "italic" }}>
              {analysis.recruiter_summary}
            </p>
          </div>
        )}

        {/* Detected stack */}
        {analysis.detected_stack.length > 0 && (
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--ink-2)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
              Detected Stack
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
              {analysis.detected_stack.map((tech) => (
                <span key={tech} style={{
                  fontSize: 11, fontWeight: 600, padding: "3px 8px", borderRadius: 999,
                  background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe",
                }}>
                  {tech}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Detected features */}
        {analysis.detected_features.length > 0 && (
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--ink-2)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
              Detected Features
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
              {analysis.detected_features.map((feat) => (
                <span key={feat} style={{
                  fontSize: 11, fontWeight: 500, padding: "3px 8px", borderRadius: 999,
                  background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0",
                }}>
                  {FEATURE_LABELS[feat] ?? feat}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Evidence files */}
        {analysis.evidence_files.length > 0 && (
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--ink-2)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
              Evidence Files Found
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
              {analysis.evidence_files.map((f) => (
                <span key={f} style={{
                  fontSize: 11, fontFamily: "monospace", padding: "3px 8px", borderRadius: 6,
                  background: "#f8fafc", color: "#334155", border: "1px solid #e2e8f0",
                }}>
                  {f}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Warnings / risk flags */}
        {analysis.warnings.length > 0 && (
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#9a3412", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 5 }}>
              Risk Flags
            </div>
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 3 }}>
              {analysis.warnings.map((w, i) => (
                <li key={i} style={{ fontSize: 11, color: "#854d0e", display: "flex", gap: 6 }}>
                  <span style={{ flexShrink: 0 }}>⚠</span><span>{w}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Footer note */}
        <div style={{ borderTop: "1px solid var(--line)", paddingTop: 10, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <p style={{ margin: 0, fontSize: 11, color: "var(--muted)", lineHeight: 1.5 }}>
            GitHub Evidence: AI Reviewed. Final verification remains pending until all evidence steps are complete.
          </p>
          <button
            type="button"
            onClick={onRerun}
            style={{
              fontSize: 11, fontWeight: 600, padding: "6px 14px", borderRadius: 8,
              border: "1px solid var(--line-2)", background: "transparent",
              color: "var(--ink-2)", cursor: "pointer", flexShrink: 0,
            }}
          >
            Re-run Analysis
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Verification Readiness ────────────────────────────────────────────────────

// Mirror of the Python compute_readiness_report — computed in-browser from
// existing React state so the report renders instantly without an extra fetch.

type ScoreContributor = {
  label: string
  points: number
  type: "positive" | "negative" | "info"
}

type SkillImprovementTip = {
  skill: string
  status: "partial" | "missing"
  category: string
  tip: string
}

type ReadinessReport = {
  readiness_score: number
  readiness_level: ReadinessLevel
  final_verification_status: "pending" | "ready_for_review"
  // NOTE: "complete" is intentionally absent — this feature never marks
  // Final Verification complete.
  strongly_supported_skills: string[]
  partially_supported_skills: string[]
  needs_more_evidence: string[]
  risk_flags: string[]
  recommended_next_actions: string[]
  recruiter_summary: string
  is_local_only: boolean
  // ── Personalized recommendations ───────────────────────────────────────
  score_contributors: ScoreContributor[]
  score_explanation: string[]
  skill_improvement_tips: SkillImprovementTip[]
}

// ── Skill improvement tips ─────────────────────────────────────────────────────

type SkillTipEntry = {
  category: string
  patterns: string[]
  tip_missing: string
  tip_partial: string
}

const SKILL_TIPS: SkillTipEntry[] = [
  {
    category: "backend_framework",
    patterns: ["fastapi", "flask", "django", "express", "node.js", "nodejs", "spring", "rails", "laravel", "gin", "actix"],
    tip_missing: "Backend frameworks aren't visible in the browser. Add a public GitHub repo with route/controller files or API documentation.",
    tip_partial: "Strengthen backend evidence by adding API route files, controller code, or Swagger/OpenAPI docs to your GitHub repo.",
  },
  {
    category: "ml_framework",
    patterns: ["pytorch", "tensorflow", "keras", "scikit-learn", "sklearn", "xgboost", "lightgbm", "hugging face", "huggingface"],
    tip_missing: "Add model metrics, a Jupyter notebook, training script, or an inference demo to make ML skills verifiable.",
    tip_partial: "Strengthen ML evidence by adding model evaluation metrics, a training script, or a notebook with results.",
  },
  {
    category: "llm_agent",
    patterns: ["langchain", "openai", "rag", "llm", "gpt", "llama", "autogen", "crewai"],
    tip_missing: "Show a prompt→response flow. Add agent or RAG pipeline code to your GitHub repository.",
    tip_partial: "Add the agent/RAG code, chain definition, or sample prompt-response pairs to your GitHub repository.",
  },
  {
    category: "frontend_framework",
    patterns: ["react", "vue", "angular", "next.js", "nextjs", "svelte", "nuxt", "remix"],
    tip_missing: "Show multi-view navigation in your recording. Add package.json and component files to your GitHub repository.",
    tip_partial: "Add component source files and package.json to your GitHub repository to confirm the frontend framework used.",
  },
  {
    category: "ts_js",
    patterns: ["typescript", "javascript"],
    tip_missing: "Add source files to a public GitHub repository.",
    tip_partial: "Add TypeScript/JavaScript source files to GitHub to confirm usage.",
  },
  {
    category: "containers",
    patterns: ["docker", "kubernetes", "k8s", "helm", "container"],
    tip_missing: "Add a Dockerfile, docker-compose.yml, or Kubernetes manifests to your GitHub repository.",
    tip_partial: "Add container configuration files (Dockerfile, compose, or K8s manifests) to GitHub.",
  },
  {
    category: "cicd",
    patterns: ["github actions", "circleci", "gitlab ci", "jenkins", "travis", "ci/cd", "pipeline"],
    tip_missing: "Add CI/CD workflow configuration files to your GitHub repository (e.g., .github/workflows/).",
    tip_partial: "Add or expand your CI/CD workflow configuration files in GitHub.",
  },
  {
    category: "deployment_paas",
    patterns: ["vercel", "heroku", "netlify", "render", "railway", "fly.io"],
    tip_missing: "A live URL helps confirm deployment. Add a deployment README section or config file to GitHub.",
    tip_partial: "Add a deployment README section or deployment config file to strengthen evidence.",
  },
  {
    category: "cloud_platform",
    patterns: ["aws", "gcp", "azure", "google cloud", "amazon web services"],
    tip_missing: "Add IaC files, deployment scripts, or cloud architecture documentation to your GitHub repository.",
    tip_partial: "Add cloud config files (Terraform, CloudFormation, or deployment docs) to GitHub.",
  },
  {
    category: "api_design",
    patterns: ["rest", "graphql", "swagger", "openapi"],
    tip_missing: "Show a Swagger/OpenAPI UI in your recording or add API route definitions to your GitHub repository.",
    tip_partial: "Add API schema files (OpenAPI spec, route definitions) to your GitHub repository.",
  },
  {
    category: "maps_geo",
    patterns: ["google maps", "mapbox", "leaflet", "geo", "geospatial", "mapping"],
    tip_missing: "Show map interactions in your recording and add the map API integration source code to GitHub.",
    tip_partial: "Add the map integration source code showing API usage to your GitHub repository.",
  },
  {
    category: "database",
    patterns: ["postgresql", "postgres", "mysql", "mongodb", "redis", "sqlite", "prisma", "sqlalchemy", "typeorm", "orm"],
    tip_missing: "Databases aren't visible in the browser. Add schema files, migrations, or ORM model definitions to your GitHub repository.",
    tip_partial: "Add database schema, migration files, or ORM models to GitHub to confirm database usage.",
  },
  {
    category: "data_science",
    patterns: ["pandas", "numpy", "matplotlib", "seaborn", "jupyter", "data analysis", "scipy"],
    tip_missing: "Show data analysis results in your recording and add a notebook or data pipeline script to GitHub.",
    tip_partial: "Add a Jupyter notebook or data pipeline script with analysis results to your GitHub repository.",
  },
  {
    category: "programming_language",
    patterns: ["python", "java", "golang", "rust", "c++", "c#", "kotlin", "swift", "ruby", "php"],
    tip_missing: "Add a public GitHub repository with source code to confirm this language is used.",
    tip_partial: "Add more source files in this language to your GitHub repository.",
  },
]

function detectSkillTip(
  skill: string,
  status: "partial" | "missing",
  hasGithub: boolean
): SkillImprovementTip {
  const lc = skill.toLowerCase()
  for (const entry of SKILL_TIPS) {
    if (entry.patterns.some(p => lc.includes(p))) {
      const tip = status === "partial" || hasGithub ? entry.tip_partial : entry.tip_missing
      return { skill, status, category: entry.category, tip }
    }
  }
  return {
    skill,
    status,
    category: "general",
    tip: "Show this skill explicitly in your recording and add supporting code to a public GitHub repository.",
  }
}

export function computeReadinessReport({
  sessionStatus,
  urlType,
  claimedSkills,
  workflowAnalysis,
  liveCheck,
  githubAnalysis,
  privacyScan,
  defenseAnalysis,
}: {
  sessionStatus: ExtensionProofSessionStatus
  urlType: UrlType
  claimedSkills: string[]
  workflowAnalysis: WorkflowAnalysisResponse | null
  liveCheck: LiveWebsiteCheckResponse | null
  githubAnalysis: ExtensionProofGitHubAnalysisResponse | null
  privacyScan: WorkflowPrivacyScanResponse | null
  defenseAnalysis?: ProjectDefenseAnalysisResponse | null
}): ReadinessReport {
  const isLocal = isLocal_(urlType)
  const sessionUploaded = (["uploaded_pending_analysis", "analyzing", "completed"] as ExtensionProofSessionStatus[]).includes(sessionStatus)

  let score = 0
  const riskFlags: string[] = []
  const needsMoreEvidence: string[] = []
  const nextActions: string[] = []
  const contributors: ScoreContributor[] = []
  const explanation: string[] = []

  // +15 workflow evidence uploaded
  if (sessionUploaded) {
    score += 15
    contributors.push({ label: "Workflow recording uploaded", points: 15, type: "positive" })
    explanation.push("Workflow evidence was uploaded.")
  } else {
    contributors.push({ label: "Workflow recording not yet uploaded", points: 15, type: "info" })
  }

  // +15 workflow analysis complete
  const hasWf = workflowAnalysis !== null
  if (hasWf) {
    score += 15
    contributors.push({ label: "Workflow evidence AI-reviewed", points: 15, type: "positive" })
    explanation.push("Workflow analysis is complete.")
  } else if (sessionUploaded) {
    contributors.push({ label: "Workflow evidence not yet AI-reviewed", points: 15, type: "info" })
  }

  // +15 GitHub evidence AI reviewed
  const githubProvided = githubAnalysis !== null
  const githubOk = githubProvided && githubAnalysis!.status === "success"
  if (githubOk) {
    score += 15
    contributors.push({ label: "GitHub evidence AI-reviewed", points: 15, type: "positive" })
    explanation.push("GitHub repository was analysed successfully.")
  } else if (githubProvided && !githubOk) {
    riskFlags.push("GitHub repository could not be accessed or is private")
    explanation.push("GitHub repository could not be accessed.")
  } else if (sessionUploaded) {
    contributors.push({ label: "No GitHub repository linked", points: 15, type: "info" })
  }

  // +15 live website check (deployed only)
  const liveOk = !isLocal && liveCheck !== null && liveCheck.is_reachable
  if (liveOk) {
    score += 15
    contributors.push({ label: "Deployed website is publicly reachable", points: 15, type: "positive" })
    explanation.push("Deployed website is publicly accessible.")
  } else if (isLocal) {
    contributors.push({ label: "Live check not applicable (local-only project)", points: 0, type: "info" })
  } else if (!isLocal && liveCheck !== null && !liveCheck.is_reachable) {
    riskFlags.push("Deployed website is not publicly accessible")
    explanation.push("Deployed website could not be confirmed as publicly accessible.")
  } else if (!isLocal && liveCheck === null && sessionUploaded) {
    contributors.push({ label: "Live website check not yet run", points: 15, type: "info" })
  }

  // +10 privacy scan safe
  const privacyStatus = privacyScan?.status ?? null
  if (privacyStatus === "clean" || privacyStatus === "redacted") {
    score += 10
    const privLabel = privacyStatus === "redacted" ? "Privacy scan passed with redactions applied" : "Privacy scan is clean"
    contributors.push({ label: privLabel, points: 10, type: "positive" })
    explanation.push(`${privLabel}.`)
  } else if (privacyStatus === "flagged") {
    riskFlags.push("Privacy scan flagged — potential sensitive data in recording")
    explanation.push("Privacy scan flagged sensitive data — score will be capped at Weak.")
  } else if (sessionUploaded) {
    contributors.push({ label: "Privacy scan not yet run", points: 10, type: "info" })
  }

  // Skill analysis
  const wfSupported    = (workflowAnalysis?.supported_skills ?? []).map(s => s.toLowerCase())
  const wfWeakly       = (workflowAnalysis?.weakly_supported_skills ?? []).map(s => s.toLowerCase())
  const ghMatched      = githubOk ? (githubAnalysis!.matched_claimed_skills).map(s => s.toLowerCase()) : []
  const ghWeakly       = githubOk ? (githubAnalysis!.weakly_matched_claimed_skills ?? []).map(s => s.toLowerCase()) : []
  const wfSupportedSet = new Set(wfSupported)
  const wfWeaklySet    = new Set(wfWeakly)
  const ghMatchedSet   = new Set(ghMatched)
  const ghWeaklySet    = new Set(ghWeakly)

  const strongly: string[] = []
  const partially: string[] = []

  for (const skill of claimedSkills) {
    const lc = skill.toLowerCase()
    if (wfSupportedSet.has(lc) || ghMatchedSet.has(lc)) {
      strongly.push(skill)
    } else if (wfWeaklySet.has(lc) || ghWeaklySet.has(lc)) {
      partially.push(skill)
    } else {
      needsMoreEvidence.push(`${skill} — not yet supported by current evidence`)
    }
  }

  const unsupportedSkills = claimedSkills.filter(
    s => !strongly.includes(s) && !partially.includes(s)
  )

  // +15 at least one strongly supported
  if (strongly.length > 0) {
    score += 15
    const names = strongly.slice(0, 3).join(", ") + (strongly.length > 3 ? " …" : "")
    contributors.push({ label: `Strong skill support (${strongly.length} skill(s) confirmed)`, points: 15, type: "positive" })
    explanation.push(`${strongly.length} claimed skill(s) strongly supported by evidence: ${names}.`)
  } else {
    score = Math.max(0, score - 10)
    contributors.push({ label: "No claimed skills with strong support", points: -10, type: "negative" })
    explanation.push("No claimed skills have strong evidence support.")
  }
  if (partially.length > 0) {
    explanation.push(`${partially.length} claimed skill(s) have partial evidence support.`)
  }
  if (unsupportedSkills.length > 0) {
    explanation.push(`${unsupportedSkills.length} claimed skill(s) have no supporting evidence yet.`)
  }

  // +10 cross-evidence confirmation
  const crossConfirmed = strongly.filter(s => wfSupportedSet.has(s.toLowerCase()) && ghMatchedSet.has(s.toLowerCase()))
  if (crossConfirmed.length > 0) {
    score += 10
    contributors.push({ label: `Cross-evidence confirmation (${crossConfirmed.length} skill(s) in workflow + GitHub)`, points: 10, type: "positive" })
    explanation.push(`${crossConfirmed.length} skill(s) confirmed in both workflow and GitHub evidence.`)
  }

  // +5 recruiter summary exists
  const recruiterText = workflowAnalysis?.recruiter_summary ?? githubAnalysis?.recruiter_summary ?? ""
  if (recruiterText.trim().length > 30) {
    score += 5
    contributors.push({ label: "Meaningful recruiter summary present", points: 5, type: "positive" })
  }

  // ── Defense analysis contributions ────────────────────────────────────────
  if (defenseAnalysis) {
    const defTranscriptWords = defenseAnalysis.transcript_text.trim().split(/\s+/).filter(Boolean).length

    score += 10
    contributors.push({ label: "Project defense transcript analyzed", points: 10, type: "positive" })
    explanation.push("Project defense transcript was analyzed.")

    if (defenseAnalysis.consistency_with_evidence_score >= 50) {
      score += 10
      contributors.push({ label: "Defense explanation consistent with evidence", points: 10, type: "positive" })
      explanation.push("Defense explanation is consistent with existing evidence.")
    }
    if (defenseAnalysis.ownership_signal_score >= 40) {
      score += 5
      contributors.push({ label: "Ownership signals present in defense", points: 5, type: "positive" })
    }
    if (defenseAnalysis.technical_depth_score >= 40) {
      score += 5
      contributors.push({ label: "Technical depth shown in defense", points: 5, type: "positive" })
    }

    // Defense deductions
    if (defTranscriptWords < 50) {
      score = Math.max(0, score - 5)
      contributors.push({ label: "Defense transcript too short", points: -5, type: "negative" })
    }
    if (defenseAnalysis.privacy_scan_status === "flagged") {
      score = Math.max(0, score - 10)
      contributors.push({ label: "Defense transcript flagged by privacy scan", points: -10, type: "negative" })
      riskFlags.push("Defense transcript was flagged by privacy scan")
    }
    const hasDefenseContradiction = defenseAnalysis.risk_flags.some(f =>
      f.toLowerCase().includes("contradiction") ||
      f.toLowerCase().includes("borrowed") ||
      f.toLowerCase().includes("did not write")
    )
    if (hasDefenseContradiction) {
      score = Math.max(0, score - 10)
      contributors.push({ label: "Contradiction signal detected in defense", points: -10, type: "negative" })
      riskFlags.push("Contradiction detected in project defense transcript")
    }
    if (defenseAnalysis.overall_defense_score < 30 && defTranscriptWords >= 50) {
      score = Math.max(0, score - 5)
      contributors.push({ label: "Defense explanation quality below threshold", points: -5, type: "negative" })
    }
  }

  // ── Deductions ────────────────────────────────────────────────────────────
  const wfRiskFlags = workflowAnalysis?.risk_flags ?? []
  const shortRecording = wfRiskFlags.some(f => ["short", "brief", "too short"].some(kw => f.toLowerCase().includes(kw)))
  if (shortRecording) {
    score = Math.max(0, score - 10)
    contributors.push({ label: "Recording is brief", points: -10, type: "negative" })
    riskFlags.push("Recording is brief — a longer walkthrough would strengthen evidence")
    explanation.push("Recording was brief, which lowered confidence.")
  }

  if (privacyStatus === "flagged") {
    score = Math.max(0, score - 15)
    contributors.push({ label: "Privacy scan flagged sensitive data", points: -15, type: "negative" })
  }

  const wfMissing = workflowAnalysis?.missing_evidence ?? []
  if (wfMissing.length > 0) {
    const missingPenalty = Math.min(wfMissing.length * 5, 15)
    score = Math.max(0, score - missingPenalty)
    contributors.push({ label: `Missing evidence items (${wfMissing.length} item(s) flagged)`, points: -missingPenalty, type: "negative" })
    explanation.push(`${wfMissing.length} evidence item(s) flagged as missing from the workflow analysis.`)
  }
  for (const item of wfMissing) needsMoreEvidence.push(item)

  if (!isLocal && liveCheck !== null && !liveCheck.is_reachable) {
    score = Math.max(0, score - 10)
    contributors.push({ label: "Deployed website not publicly accessible", points: -10, type: "negative" })
  }
  if (githubProvided && !githubOk) {
    score = Math.max(0, score - 10)
    contributors.push({ label: "GitHub repository inaccessible", points: -10, type: "negative" })
  }

  // Privacy cap
  if (privacyStatus === "flagged") score = Math.min(score, 59)
  score = Math.max(0, Math.min(100, score))

  const level: ReadinessLevel =
    score >= 80 ? "strong" :
    score >= 60 ? "moderate" :
    score >= 40 ? "weak" :
    "insufficient"

  // INVARIANT: "complete" is never emitted here.
  const fvStatus: "pending" | "ready_for_review" =
    score >= 80 && privacyStatus !== "flagged" ? "ready_for_review" : "pending"

  // ── Skill improvement tips ─────────────────────────────────────────────────
  const skillTips: SkillImprovementTip[] = [
    ...partially.map(s => detectSkillTip(s, "partial", githubProvided)),
    ...unsupportedSkills.map(s => detectSkillTip(s, "missing", githubProvided)),
  ]

  // ── Recommended actions ───────────────────────────────────────────────────
  if (!sessionUploaded) nextActions.push("Upload your workflow recording to begin evidence analysis.")
  if (sessionUploaded && !hasWf) nextActions.push("Run Workflow Evidence Analysis to get an AI review of your recording.")
  if (privacyStatus === "flagged") nextActions.push("Re-record the workflow using demo accounts and sample data. Avoid passwords, API keys, tokens, and personal information.")
  if (shortRecording) nextActions.push("Record a longer 2–3 minute walkthrough showing the main feature from input to output end-to-end.")
  if (!isLocal && liveCheck === null && sessionUploaded) nextActions.push("Run the Live Website Check to confirm your deployed site is publicly accessible.")
  if (!isLocal && liveCheck !== null && !liveCheck.is_reachable) nextActions.push("Confirm the deployed app is running and publicly reachable, then re-run the Live Website Check.")
  if (!githubProvided && sessionUploaded) nextActions.push("Add a public GitHub repository URL and run GitHub Evidence Analysis to provide code-level proof of your work.")
  if (githubProvided && !githubOk) nextActions.push("Make the GitHub repository public or verify the repository URL, then re-run GitHub Evidence Analysis.")
  if (githubOk) {
    const features = githubAnalysis!.detected_features ?? []
    if (!features.includes("readme")) nextActions.push("Add a README with a project overview, setup instructions, and usage examples.")
    if (!features.includes("deployment") && !isLocal) nextActions.push("Add deployment configuration or documentation to your repository.")
  }
  // Skill-specific actions from improvement tips
  for (const tip of skillTips) {
    nextActions.push(`${tip.skill}: ${tip.tip}`)
  }
  if (hasWf && workflowAnalysis!.human_review_needed) nextActions.push("Request a faculty or human review — AI confidence is low for this recording.")
  // Defense-specific nudges
  if (!defenseAnalysis && sessionUploaded && hasWf) {
    nextActions.push("Submit a Project Defense transcript explaining what you built, your role, tools used, and the technical decisions you made.")
  }
  if (defenseAnalysis && defenseAnalysis.privacy_scan_status === "flagged") {
    nextActions.push("Re-submit your defense transcript — remove any passwords, API keys, or personal data before resubmitting.")
  }
  if (defenseAnalysis && defenseAnalysis.overall_defense_score < 30) {
    nextActions.push("Strengthen your defense explanation with specific technical details: the problem you solved, your role, key tools, and what you would improve next.")
  }

  // Recruiter summary
  const sources: string[] = []
  if (sessionUploaded) sources.push("workflow recording")
  if (liveOk) sources.push("live website confirmation")
  if (githubOk) sources.push("GitHub repository analysis")
  const joinSources = (lst: string[]) =>
    lst.length === 0 ? "" :
    lst.length === 1 ? lst[0] :
    lst.length === 2 ? `${lst[0]} and ${lst[1]}` :
    `${lst.slice(0, -1).join(", ")}, and ${lst[lst.length - 1]}`

  let recruiterSummary: string
  if (sources.length === 0 || !hasWf) {
    recruiterSummary = "Insufficient evidence has been submitted for recruiter review. Complete the workflow analysis and available evidence steps."
  } else if (level === "strong") {
    recruiterSummary = `This evidence package is strongly ready for recruiter review. The ${joinSources(sources)} support the claimed skills with high confidence.`
  } else if (level === "moderate") {
    const skillNote = strongly.length > 0
      ? ` ${strongly.length} skill(s) have strong support${partially.length > 0 ? ` and ${partially.length} have partial evidence` : ""}.`
      : ""
    recruiterSummary = `This evidence package is moderately ready for recruiter review. The ${joinSources(sources)} support several claimed skills, but some still need clearer evidence.${skillNote}`
  } else if (level === "weak") {
    recruiterSummary = "This evidence package is partially assembled. Some evidence steps are incomplete. Follow the recommended next actions to improve readiness."
  } else {
    recruiterSummary = "Insufficient evidence to support recruiter review. Upload a recording, run the available analyses, and confirm site accessibility."
  }

  // Deduplicate
  const seen = new Set<string>()
  const uniqueActions = nextActions.filter(a => { if (seen.has(a)) return false; seen.add(a); return true })
  const uniqueNeeds = [...new Set(needsMoreEvidence)]
  const uniqueFlags = [...new Set(riskFlags)]

  return {
    readiness_score: score,
    readiness_level: level,
    final_verification_status: fvStatus,
    strongly_supported_skills: strongly,
    partially_supported_skills: partially,
    needs_more_evidence: uniqueNeeds,
    risk_flags: uniqueFlags,
    recommended_next_actions: uniqueActions,
    recruiter_summary: recruiterSummary,
    is_local_only: isLocal,
    score_contributors: contributors,
    score_explanation: explanation,
    skill_improvement_tips: skillTips,
  }
}

// Alias to avoid shadowing isLocal already defined as a variable in the main component
function isLocal_(t: UrlType): boolean {
  return t === "localhost_url" || t === "local_network_url"
}

// ── Readiness level config ─────────────────────────────────────────────────────

const READINESS_LEVEL_CONFIG: Record<
  ReadinessLevel,
  { bg: string; border: string; color: string; badgeBg: string; badgeColor: string; badgeBorder: string; label: string; icon: string }
> = {
  strong:       { bg: "#f0fdf4", border: "#d1fae5", color: "#065f46", badgeBg: "#dcfce7", badgeColor: "#166534", badgeBorder: "#bbf7d0", label: "Strong Readiness",      icon: "✦" },
  moderate:     { bg: "#fffbeb", border: "#fef08a", color: "#78350f", badgeBg: "#fef9c3", badgeColor: "#854d0e", badgeBorder: "#fef08a", label: "Moderate Readiness",    icon: "◑" },
  weak:         { bg: "#fff7ed", border: "#fed7aa", color: "#9a3412", badgeBg: "#ffedd5", badgeColor: "#c2410c", badgeBorder: "#fed7aa", label: "Weak Readiness",        icon: "◔" },
  insufficient: { bg: "#fef2f2", border: "#fecaca", color: "#991b1b", badgeBg: "#fee2e2", badgeColor: "#991b1b", badgeBorder: "#fecaca", label: "Insufficient Evidence", icon: "○" },
}

function ReadinessScoreBar({ score, level }: { score: number; level: ReadinessLevel }) {
  const cfg = READINESS_LEVEL_CONFIG[level]
  const trackColor =
    level === "strong" ? "#d1fae5" :
    level === "moderate" ? "#fef08a" :
    level === "weak" ? "#fed7aa" :
    "#fecaca"
  const fillColor =
    level === "strong" ? "#16a34a" :
    level === "moderate" ? "#ca8a04" :
    level === "weak" ? "#ea580c" :
    "#dc2626"

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <div style={{ flex: 1, height: 8, background: trackColor, borderRadius: 999 }}>
        <div
          style={{
            height: 8, borderRadius: 999, background: fillColor,
            width: `${score}%`, transition: "width 0.6s ease",
          }}
        />
      </div>
      <span style={{ fontSize: 14, fontWeight: 800, color: cfg.color, minWidth: 36, textAlign: "right" }}>
        {score}<span style={{ fontSize: 10, fontWeight: 500 }}>/100</span>
      </span>
    </div>
  )
}

function VerificationReadinessReportCard({
  report,
}: {
  report: ReadinessReport
}) {
  const cfg = READINESS_LEVEL_CONFIG[report.readiness_level]
  const fvReady = report.final_verification_status === "ready_for_review"

  return (
    <div style={{ border: `1px solid ${cfg.border}`, borderRadius: 14, overflow: "hidden" }}>
      {/* ── Header ── */}
      <div style={{
        background: cfg.bg,
        borderBottom: `1px solid ${cfg.border}`,
        padding: "14px 16px",
        display: "flex", alignItems: "flex-start", justifyContent: "space-between",
        gap: 12, flexWrap: "wrap",
      }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: cfg.color }}>
            Verification Readiness Report
          </div>
          <div style={{ fontSize: 11, color: cfg.color, opacity: 0.8, marginTop: 2 }}>
            Evidence readiness for recruiter review. Final verification is still pending.
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          {/* Readiness level badge */}
          <span style={{
            fontSize: 10, fontWeight: 700, letterSpacing: "0.07em",
            padding: "3px 10px", borderRadius: 999,
            background: cfg.badgeBg, color: cfg.badgeColor, border: `1px solid ${cfg.badgeBorder}`,
          }}>
            {cfg.icon} {cfg.label.toUpperCase()}
          </span>
          {/* Final verification status */}
          <span style={{
            fontSize: 10, fontWeight: 700, letterSpacing: "0.06em",
            padding: "3px 10px", borderRadius: 999,
            background: fvReady ? "#dbeafe" : "#f1f5f9",
            color: fvReady ? "#1d4ed8" : "#475569",
            border: `1px solid ${fvReady ? "#bfdbfe" : "#e2e8f0"}`,
          }}>
            {fvReady ? "→ READY FOR REVIEW" : "⏳ FINAL VERIFICATION PENDING"}
          </span>
        </div>
      </div>

      <div style={{ padding: "16px 16px", display: "grid", gap: 16 }}>
        {/* ── Score bar ── */}
        <ReadinessScoreBar score={report.readiness_score} level={report.readiness_level} />

        {/* ── Why this score? ── */}
        {report.score_explanation.length > 0 && (
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
              Why this score?
            </div>
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 3 }}>
              {report.score_explanation.map((sentence, i) => (
                <li key={i} style={{ display: "flex", gap: 7, alignItems: "flex-start", fontSize: 12, color: "#334155", lineHeight: 1.6 }}>
                  <span style={{ flexShrink: 0, color: "#94a3b8", marginTop: 2 }}>•</span>
                  <span>{sentence}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* ── Score breakdown ── */}
        {report.score_contributors.filter(c => c.type !== "info").length > 0 && (
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
              Score Breakdown
            </div>
            <div style={{ display: "grid", gap: 3 }}>
              {report.score_contributors.filter(c => c.type !== "info").map((c, i) => (
                <div key={i} style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: "4px 8px", borderRadius: 6,
                  background: c.type === "positive" ? "#f0fdf4" : "#fef2f2",
                  border: `1px solid ${c.type === "positive" ? "#d1fae5" : "#fecaca"}`,
                }}>
                  <span style={{ fontSize: 11, color: "#334155" }}>{c.label}</span>
                  <span style={{
                    fontSize: 11, fontWeight: 700, minWidth: 36, textAlign: "right",
                    color: c.type === "positive" ? "#166534" : "#991b1b",
                  }}>
                    {c.points > 0 ? `+${c.points}` : c.points}
                  </span>
                </div>
              ))}
              {report.score_contributors.filter(c => c.type === "info" && c.points > 0).map((c, i) => (
                <div key={`info-${i}`} style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: "4px 8px", borderRadius: 6,
                  background: "#f8fafc", border: "1px solid #e2e8f0",
                }}>
                  <span style={{ fontSize: 11, color: "#64748b", fontStyle: "italic" }}>{c.label}</span>
                  <span style={{ fontSize: 11, fontWeight: 600, color: "#94a3b8", minWidth: 56, textAlign: "right" }}>
                    +{c.points} avail.
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Localhost note ── */}
        {report.is_local_only && (
          <div style={{ background: "#fff7ed", border: "1px solid #fed7aa", borderRadius: 8, padding: "8px 12px" }}>
            <p style={{ margin: 0, fontSize: 11, color: "#9a3412", lineHeight: 1.6 }}>
              <strong>Local-only workflow evidence</strong> — live website check not applicable. Add a GitHub repository or deploy the project for stronger verification.
            </p>
          </div>
        )}

        {/* ── Overall summary ── */}
        <div style={{ background: "#fff", border: `1px solid ${cfg.border}`, borderRadius: 10, padding: "10px 12px" }}>
          <p style={{ margin: 0, fontSize: 12, color: cfg.color, lineHeight: 1.7 }}>
            {report.recruiter_summary}
          </p>
        </div>

        {/* ── Skill support grid ── */}
        {(report.strongly_supported_skills.length > 0 || report.partially_supported_skills.length > 0) && (
          <div style={{ display: "grid", gap: 10, gridTemplateColumns: report.strongly_supported_skills.length > 0 && report.partially_supported_skills.length > 0 ? "1fr 1fr" : "1fr" }}>
            {report.strongly_supported_skills.length > 0 && (
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: "#065f46", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 5 }}>
                  ✓ Strongly Supported
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                  {report.strongly_supported_skills.map((s) => (
                    <span key={s} style={{ fontSize: 11, fontWeight: 600, padding: "3px 8px", borderRadius: 999, background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }}>
                      {s}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {report.partially_supported_skills.length > 0 && (
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: "#854d0e", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 5 }}>
                  ◑ Partially Supported
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                  {report.partially_supported_skills.map((s) => (
                    <span key={s} style={{ fontSize: 11, fontWeight: 600, padding: "3px 8px", borderRadius: 999, background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a" }}>
                      {s}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Needs more evidence ── */}
        {report.needs_more_evidence.length > 0 && (
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#9a3412", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 5 }}>
              ✗ Needs More Evidence
            </div>
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 3 }}>
              {report.needs_more_evidence.map((item, i) => (
                <li key={i} style={{ display: "flex", gap: 7, alignItems: "flex-start", fontSize: 12, color: "#9a3412", lineHeight: 1.55 }}>
                  <span style={{ flexShrink: 0, marginTop: 2, color: "#fca5a5" }}>•</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* ── Risk flags ── */}
        {report.risk_flags.length > 0 && (
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#991b1b", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 5 }}>
              ⚠ Risk Flags
            </div>
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 3 }}>
              {report.risk_flags.map((f, i) => (
                <li key={i} style={{ display: "flex", gap: 7, alignItems: "flex-start", fontSize: 12, color: "#991b1b", lineHeight: 1.55 }}>
                  <span style={{ flexShrink: 0, marginTop: 2 }}>⚠</span>
                  <span>{f}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* ── Recommended next actions ── */}
        {report.recommended_next_actions.length > 0 && (
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#1e40af", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 5 }}>
              → Recommended Next Actions
            </div>
            <ol style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 4 }}>
              {report.recommended_next_actions.map((action, i) => (
                <li key={i} style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 12, color: "#1e3a8a", lineHeight: 1.55 }}>
                  <span style={{ flexShrink: 0, fontWeight: 700, color: "#3b82f6", minWidth: 16 }}>{i + 1}.</span>
                  <span>{action}</span>
                </li>
              ))}
            </ol>
          </div>
        )}

        {/* ── Skill-specific improvement tips ── */}
        {report.skill_improvement_tips.length > 0 && (
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#1e40af", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
              💡 Skill-Specific Tips
            </div>
            <div style={{ display: "grid", gap: 7 }}>
              {report.skill_improvement_tips.map((tip, i) => (
                <div key={i} style={{
                  background: "#f8fafc", border: "1px solid #e2e8f0",
                  borderRadius: 9, padding: "8px 12px",
                }}>
                  <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 4, flexWrap: "wrap" }}>
                    <span style={{
                      fontSize: 11, fontWeight: 700,
                      padding: "2px 8px", borderRadius: 999,
                      background: tip.status === "partial" ? "#fef9c3" : "#fee2e2",
                      color: tip.status === "partial" ? "#854d0e" : "#991b1b",
                      border: `1px solid ${tip.status === "partial" ? "#fef08a" : "#fecaca"}`,
                    }}>
                      {tip.skill}
                    </span>
                    <span style={{
                      fontSize: 10, fontWeight: 600, letterSpacing: "0.06em",
                      color: tip.status === "partial" ? "#92400e" : "#7f1d1d",
                      textTransform: "uppercase",
                    }}>
                      {tip.status === "partial" ? "Partial Evidence" : "No Evidence"}
                    </span>
                  </div>
                  <p style={{ margin: 0, fontSize: 12, color: "#334155", lineHeight: 1.6 }}>
                    {tip.tip}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Footer ── */}
        <div style={{ borderTop: "1px solid var(--line)", paddingTop: 10 }}>
          <p style={{ margin: 0, fontSize: 11, color: "var(--muted)", lineHeight: 1.55 }}>
            This readiness report is computed automatically from all available evidence.
            A score of 80+ marks this evidence package as ready for recruiter review.{" "}
            <strong>Final Verification</strong> must be completed separately by a VeriBridge reviewer
            and is not triggered by this report.
          </p>
        </div>
      </div>
    </div>
  )
}

// ── Privacy Guard components ──────────────────────────────────────────────────

const PRIVACY_SCAN_CONFIG: Record<
  WorkflowPrivacyScanStatus,
  { bg: string; color: string; border: string; icon: string; label: string }
> = {
  clean:    { bg: "#dcfce7", color: "#166534", border: "#bbf7d0", icon: "🛡️", label: "Privacy scan: Clean" },
  redacted: { bg: "#dbeafe", color: "#1d4ed8", border: "#bfdbfe", icon: "🔒", label: "Privacy scan: Redacted" },
  flagged:  { bg: "#fef2f2", color: "#991b1b", border: "#fecaca", icon: "⚠️", label: "Privacy scan: Needs Review" },
}

function PrivacyScanBadge({
  scan,
  onReRecord,
}: {
  scan: WorkflowPrivacyScanResponse
  onReRecord: () => void
}) {
  const cfg = PRIVACY_SCAN_CONFIG[scan.status] ?? PRIVACY_SCAN_CONFIG.clean

  return (
    <div style={{ border: `1px solid ${cfg.border}`, borderRadius: 12, overflow: "hidden" }}>
      {/* Header */}
      <div style={{
        background: cfg.bg,
        borderBottom: `1px solid ${cfg.border}`,
        padding: "10px 14px",
        display: "flex", alignItems: "center", gap: 8,
      }}>
        <span style={{ fontSize: 14 }}>{cfg.icon}</span>
        <span style={{ fontSize: 12, fontWeight: 700, color: cfg.color }}>{cfg.label}</span>
      </div>

      <div style={{ padding: "10px 14px", display: "grid", gap: 8, background: "#fff" }}>
        {/* Summary */}
        <p style={{ margin: 0, fontSize: 12, color: "#334155", lineHeight: 1.65 }}>
          {scan.scan_summary}
        </p>

        {/* Redacted counts (for 'redacted' status) */}
        {scan.status === "redacted" && (scan.redacted_fields_count > 0 || scan.redacted_urls_count > 0) && (
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {scan.redacted_fields_count > 0 && (
              <span style={{ fontSize: 11, color: "#1d4ed8", background: "#eff6ff", padding: "2px 8px", borderRadius: 999, border: "1px solid #bfdbfe" }}>
                {scan.redacted_fields_count} field(s) masked
              </span>
            )}
            {scan.redacted_urls_count > 0 && (
              <span style={{ fontSize: 11, color: "#1d4ed8", background: "#eff6ff", padding: "2px 8px", borderRadius: 999, border: "1px solid #bfdbfe" }}>
                {scan.redacted_urls_count} URL param(s) redacted
              </span>
            )}
          </div>
        )}

        {/* Flagged: risk details + actions */}
        {scan.status === "flagged" && (
          <>
            {scan.risk_flags.length > 0 && (
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: "#9a3412", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
                  Detected Issues
                </div>
                <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 3 }}>
                  {scan.risk_flags.map((f, i) => (
                    <li key={i} style={{ fontSize: 11, color: "#991b1b", display: "flex", gap: 6 }}>
                      <span style={{ flexShrink: 0 }}>•</span><span>{f}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div style={{ background: "#fff7ed", border: "1px solid #fed7aa", borderRadius: 8, padding: "8px 12px" }}>
              <p style={{ margin: 0, fontSize: 11, color: "#9a3412", lineHeight: 1.6 }}>
                <strong>This proof is hidden from recruiter and public view</strong> until it is reviewed or re-recorded.
                Re-record using demo or sample data. Avoid passwords, API keys, tokens, and personal information.
              </p>
            </div>

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 4 }}>
              <button
                type="button"
                onClick={onReRecord}
                style={{
                  fontSize: 12, fontWeight: 600, padding: "7px 14px", borderRadius: 8,
                  border: "1px solid transparent", background: "#dc2626", color: "#fff", cursor: "pointer",
                }}
              >
                Re-record Proof
              </button>
              <button
                type="button"
                onClick={() => { /* TODO: mark-private API */ alert("Proof marked as private. It will not appear in recruiter view.") }}
                style={{
                  fontSize: 12, fontWeight: 600, padding: "7px 14px", borderRadius: 8,
                  border: "1px solid #e2e8f0", background: "transparent", color: "#475569", cursor: "pointer",
                }}
              >
                Keep Private
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

/**
 * Pre-recording privacy warning shown on the proof form.
 * Includes a required acknowledgment checkbox.
 */
function PrivacyWarningBox({
  acknowledged,
  onToggle,
}: {
  acknowledged: boolean
  onToggle: () => void
}) {
  return (
    <div style={{ border: "1px solid #fcd34d", borderRadius: 12, background: "#fffbeb", padding: "14px 16px", display: "grid", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
        <span style={{ fontSize: 16, flexShrink: 0, marginTop: 1 }}>🛡️</span>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#92400e" }}>Privacy Guard — Read before recording</div>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: "#78350f", lineHeight: 1.7 }}>
            Before recording, avoid showing <strong>passwords, API keys, tokens, private dashboards, SSNs, payment info,
            or any confidential data</strong>. Use demo accounts, sample data, or test environments whenever possible.
          </p>
          <p style={{ margin: "6px 0 0", fontSize: 11, color: "#92400e", lineHeight: 1.6 }}>
            VeriBridge automatically masks common sensitive fields and URL parameters, but you should still
            avoid navigating to pages that display real credentials or private personal information.
            Recordings that contain sensitive data are <strong>hidden from recruiter view</strong> until reviewed.
          </p>
        </div>
      </div>

      <label
        style={{ display: "flex", alignItems: "flex-start", gap: 8, cursor: "pointer", userSelect: "none" }}
        onClick={onToggle}
      >
        <div
          style={{
            width: 16, height: 16, borderRadius: 4, flexShrink: 0, marginTop: 1,
            border: `2px solid ${acknowledged ? "#d97706" : "#d97706"}`,
            background: acknowledged ? "#d97706" : "transparent",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}
        >
          {acknowledged && (
            <svg viewBox="0 0 12 12" width="10" height="10" fill="none" stroke="#fff" strokeWidth="2">
              <polyline points="1.5,6 5,9.5 10.5,2.5" />
            </svg>
          )}
        </div>
        <span style={{ fontSize: 12, color: "#78350f", lineHeight: 1.5 }}>
          I understand and will avoid showing sensitive information during this recording.
        </span>
      </label>
    </div>
  )
}

// ── Project Defense components ────────────────────────────────────────────────

export function ProjectDefenseResultCard({
  analysis,
  sourceScore,
}: {
  analysis: ProjectDefenseAnalysisResponse
  sourceScore?: FinalSourceScore
}) {
  const overallScore = sourceScore?.score ?? analysis.overall_defense_score
  const scoreColor =
    overallScore >= 70 ? "#166534" :
    overallScore >= 50 ? "#854d0e" :
    overallScore >= 30 ? "#c2410c" :
    "#991b1b"
  const scoreBg =
    overallScore >= 70 ? "#f0fdf4" :
    overallScore >= 50 ? "#fffbeb" :
    overallScore >= 30 ? "#fff7ed" :
    "#fef2f2"
  const scoreBorder =
    overallScore >= 70 ? "#d1fae5" :
    overallScore >= 50 ? "#fef08a" :
    overallScore >= 30 ? "#fed7aa" :
    "#fecaca"

  const privacyCfg = {
    clean:    { label: "Privacy: Clean",    color: "#166534", bg: "#dcfce7", border: "#bbf7d0" },
    redacted: { label: "Privacy: Redacted", color: "#1d4ed8", bg: "#dbeafe", border: "#bfdbfe" },
    flagged:  { label: "Privacy: Flagged",  color: "#991b1b", bg: "#fef2f2", border: "#fecaca" },
  }[analysis.privacy_scan_status] ?? { label: "Privacy: Unknown", color: "#64748b", bg: "#f8fafc", border: "#e2e8f0" }
  const unrelatedWarning = sourceScore?.notes?.toLowerCase().includes("unrelated")
    ? sourceScore.notes
    : analysis.risk_flags.find((flag) => flag.toLowerCase().includes("unrelated"))

  return (
    <div style={{ border: `1px solid ${scoreBorder}`, borderRadius: 14, overflow: "hidden" }}>
      {/* Header */}
      <div style={{
        background: scoreBg, borderBottom: `1px solid ${scoreBorder}`,
        padding: "12px 16px",
        display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, flexWrap: "wrap",
      }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: scoreColor }}>Project Defense — AI Reviewed</div>
          <div style={{ fontSize: 11, color: scoreColor, opacity: 0.8, marginTop: 2 }}>
            Transcript analysed · Evidence consistency checked
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <SourceScoreBadge label="Project Defense Score" source={sourceScore ?? { score: overallScore, status: overallScore >= 60 ? "pass" : "partial" }} />
          <span style={{
            fontSize: 10, fontWeight: 700, letterSpacing: "0.07em", padding: "3px 9px", borderRadius: 999,
            background: privacyCfg.bg, color: privacyCfg.color, border: `1px solid ${privacyCfg.border}`,
          }}>
            {privacyCfg.label.toUpperCase()}
          </span>
        </div>
      </div>

      <div style={{ padding: "14px 16px", display: "grid", gap: 14 }}>
        {unrelatedWarning && (
          <div role="alert" style={{
            border: "1px solid #fecaca",
            background: "#fef2f2",
            color: "#991b1b",
            borderRadius: 10,
            padding: "9px 12px",
            fontSize: 12,
            lineHeight: 1.55,
          }}>
            Transcript appears unrelated to the submitted proof. It was not used as strong support for this project.
          </div>
        )}

        {/* Score breakdown — 2-col grid */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          {([
            { label: "Evidence Consistency", score: analysis.consistency_with_evidence_score },
            { label: "Explanation Clarity",  score: analysis.explanation_clarity_score },
            { label: "Ownership Signals",    score: analysis.ownership_signal_score },
            { label: "Technical Depth",      score: analysis.technical_depth_score },
          ] as Array<{ label: string; score: number }>).map(({ label, score }) => {
            const c  = score >= 70 ? "#166534" : score >= 50 ? "#854d0e" : "#991b1b"
            const bg = score >= 70 ? "#f0fdf4" : score >= 50 ? "#fffbeb" : "#fef2f2"
            const br = score >= 70 ? "#d1fae5" : score >= 50 ? "#fef08a" : "#fecaca"
            return (
              <div key={label} style={{ padding: "8px 10px", borderRadius: 9, background: bg, border: `1px solid ${br}` }}>
                <div style={{ fontSize: 10, color: c, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 3 }}>{label}</div>
                <div style={{ fontSize: 18, fontWeight: 800, color: c }}>{score}<span style={{ fontSize: 10, fontWeight: 400 }}>/100</span></div>
              </div>
            )
          })}
        </div>

        {/* Recruiter summary */}
        <AnalysisSection title="Recruiter Summary">
          <div style={{ background: scoreBg, border: `1px solid ${scoreBorder}`, borderRadius: 10, padding: "10px 12px" }}>
            <p style={{ margin: 0, fontSize: 12, color: scoreColor, lineHeight: 1.7, fontStyle: "italic" }}>
              {analysis.recruiter_summary}
            </p>
          </div>
        </AnalysisSection>

        {/* Risk flags */}
        {analysis.risk_flags.length > 0 && (
          <AnalysisSection title="Flags">
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 4 }}>
              {analysis.risk_flags.map((f, i) => (
                <li key={i} style={{ display: "flex", gap: 7, alignItems: "flex-start", fontSize: 12, color: "#9a3412", lineHeight: 1.55 }}>
                  <span style={{ flexShrink: 0, marginTop: 2 }}>⚠</span><span>{f}</span>
                </li>
              ))}
            </ul>
          </AnalysisSection>
        )}

        {/* Recommended improvements */}
        {analysis.recommended_improvements.length > 0 && (
          <AnalysisSection title="How to Strengthen This Explanation">
            <BulletList items={analysis.recommended_improvements} color="#1e40af" />
          </AnalysisSection>
        )}

        {/* Privacy flagged warning */}
        {analysis.privacy_scan_status === "flagged" && (
          <div style={{ background: "#fff7ed", border: "1px solid #fed7aa", borderRadius: 8, padding: "8px 12px" }}>
            <p style={{ margin: 0, fontSize: 11, color: "#9a3412", lineHeight: 1.6 }}>
              <strong>Privacy flag detected</strong> — this transcript is hidden from recruiter view.
              Review and resubmit without passwords, API keys, tokens, or personal information.
            </p>
          </div>
        )}

        {/* Footer */}
        <div style={{ borderTop: "1px solid var(--line)", paddingTop: 10 }}>
          <p style={{ margin: 0, fontSize: 11, color: "var(--muted)", lineHeight: 1.55 }}>
            This analysis is based on transcript text only — video content is not analysed.
            Final verification remains pending until all evidence steps are complete.
          </p>
        </div>
      </div>
    </div>
  )
}

type DefenseInputTab = "upload" | "record" | "paste"

const ALLOWED_DEFENSE_MEDIA_EXTS = ["mp4", "mov", "webm", "mp3", "wav", "m4a"] as const
const ALLOWED_DEFENSE_MEDIA_ACCEPT = ALLOWED_DEFENSE_MEDIA_EXTS.map(e => `.${e}`).join(",")
const MAX_DEFENSE_MEDIA_MB = 200

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1_048_576) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1_048_576).toFixed(1)} MB`
}

function fmtSeconds(s: number): string {
  const m = Math.floor(s / 60)
  const sec = s % 60
  return `${m}:${String(sec).padStart(2, "0")}`
}

const TRANSCRIPTION_STATUS_CONFIG: Record<string, { label: string; color: string; bg: string; border: string }> = {
  not_started:           { label: "No media registered",                                      color: "#6b7280", bg: "#f9fafb", border: "#e5e7eb" },
  uploaded:              { label: "Media uploaded — paste or edit your transcript below",      color: "#854d0e", bg: "#fffbeb", border: "#fef08a" },
  transcription_pending: { label: "Transcription in progress — paste or edit your transcript", color: "#1d4ed8", bg: "#dbeafe", border: "#bfdbfe" },
  transcript_ready:      { label: "Transcript ready — review it and click Analyze",            color: "#065f46", bg: "#dcfce7", border: "#bbf7d0" },
  analysis_complete:     { label: "Analysis complete",                                         color: "#065f46", bg: "#f0fdf4", border: "#d1fae5" },
}

export function ProjectDefenseSection({
  session,
  defenseAnalysis,
  defenseTranscript,
  defenseAnalyzing,
  defenseAnalyzeError,
  defenseSimProgress,
  defenseSimStageIdx,
  sourceScore,
  onTranscriptChange,
  onAnalyze,
}: {
  session: ExtensionProofSessionResponse
  defenseAnalysis: ProjectDefenseAnalysisResponse | null
  defenseTranscript: string
  defenseAnalyzing: boolean
  defenseAnalyzeError: string | null
  defenseSimProgress: number
  defenseSimStageIdx: number
  sourceScore?: FinalSourceScore
  onTranscriptChange: (v: string) => void
  onAnalyze: () => void
}) {
  // ── ALL hooks must come before any conditional return (Rules of Hooks) ────

  // ── Tab ────────────────────────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<DefenseInputTab>("upload")

  // ── File upload state ──────────────────────────────────────────────────────
  const [mediaFile, setMediaFile]           = useState<File | null>(null)
  const [uploading, setUploading]           = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadError, setUploadError]       = useState<string | null>(null)
  const [uploadResult, setUploadResult]     = useState<ProjectDefenseMediaUploadResponse | null>(null)
  const fileInputRef                        = useRef<HTMLInputElement>(null)

  // ── Recording state ────────────────────────────────────────────────────────
  const [recState, setRecState]                   = useState<"idle" | "recording" | "recorded">("idle")
  const [recordingSeconds, setRecordingSeconds]   = useState(0)
  const [recordedObjectUrl, setRecordedObjectUrl] = useState<string | null>(null)
  const [recError, setRecError]                   = useState<string | null>(null)
  const [recUploading, setRecUploading]           = useState(false)
  const [recUploadProgress, setRecUploadProgress] = useState(0)
  const [recUploadResult, setRecUploadResult]     = useState<ProjectDefenseMediaUploadResponse | null>(null)
  const mediaRecorderRef                          = useRef<MediaRecorder | null>(null)
  const chunksRef                                 = useRef<Blob[]>([])
  const recordedBlobRef                           = useRef<Blob | null>(null)
  const timerRef                                  = useRef<ReturnType<typeof setInterval> | null>(null)

  // ── Transcription state ────────────────────────────────────────────────────
  const [transcribing, setTranscribing]           = useState(false)
  const [transcribeMsg, setTranscribeMsg]         = useState<string | null>(null)
  const [transcribeError, setTranscribeError]     = useState<string | null>(null)
  const [transcriptSegments, setTranscriptSegments] = useState<Array<{start_time: number, end_time: number, text: string}> | null>(null)

  // ── Refinement state ───────────────────────────────────────────────────────
  const [rawTranscript, setRawTranscript]             = useState<string | null>(null)
  const [refinedTranscript, setRefinedTranscript]     = useState<string | null>(null)
  const [showingRaw, setShowingRaw]                   = useState(false)
  const [corrections, setCorrections]                 = useState<TranscriptCorrectionEntry[]>([])
  const [glossaryMatches, setGlossaryMatches]         = useState<string[]>([])
  const [refinementDisplaySummary, setRefinementDisplaySummary] = useState<string>("")
  const [transcriptNeedsReview, setTranscriptNeedsReview]       = useState(false)
  const [reRefining, setReRefining]                   = useState(false)
  const [reRefineError, setReRefineError]             = useState<string | null>(null)
  // ── Transcript-stale flag ──────────────────────────────────────────────────
  // Set to true when a new file is selected / recording started and the
  // existing transcript may no longer match the new media.  Cleared after a
  // successful upload (which also wipes the transcript).
  const [transcriptStale, setTranscriptStale]         = useState(false)

  // ── Derived (safe to compute even when hidden — values not rendered) ───────
  const transcriptWords = defenseTranscript.trim().split(/\s+/).filter(Boolean).length
  // Block analysis when transcript is stale (new file selected but not yet uploaded)
  const canAnalyze      = transcriptWords >= 30 && !defenseAnalyzing && !transcriptStale
  const txStatus        = defenseAnalysis?.transcription_status ?? "not_started"
  const statusCfg       = TRANSCRIPTION_STATUS_CONFIG[txStatus] ?? TRANSCRIPTION_STATUS_CONFIG.not_started
  // hasMedia: any media filename is registered (controls media badge, status notice)
  const hasMedia = !!(uploadResult || recUploadResult || defenseAnalysis?.media_filename)
  // hasStoredFile: a file is actually persisted in storage and retrievable for transcription.
  // Generate Transcript is only enabled when this is true; without a storage path the
  // transcription endpoint would return 422 "Could not retrieve the media file".
  const hasStoredFile = !!(
    uploadResult?.media_storage_path ||
    recUploadResult?.media_storage_path ||
    defenseAnalysis?.media_storage_path
  )

  // ── Guard — render nothing until proof is uploaded ────────────────────────
  const uploadedOrLater: ExtensionProofSessionStatus[] = ["uploaded_pending_analysis", "analyzing", "completed"]
  if (!uploadedOrLater.includes(session.status)) return null

  // ── Transcription ──────────────────────────────────────────────────────────
  async function handleTranscribe() {
    setTranscribing(true)
    setTranscribeMsg(null)
    setTranscribeError(null)
    try {
      const result: ProjectDefenseTranscribeResponse = await transcribeDefenseMedia(session.id)
      if (!result.configured) {
        // Provider not set up — show manual fallback message, keep textarea editable
        setTranscribeMsg(result.message)
      } else {
        // Success — populate the textarea so the student can review/edit
        // If refined_transcript is available, show it by default (raw preserved)
        const workingText = result.transcript_text
        onTranscriptChange(workingText)
        setTranscribeMsg(result.message)

        // Stash refinement output
        if (result.raw_transcript) {
          setRawTranscript(result.raw_transcript)
        }
        if (result.refined_transcript) {
          setRefinedTranscript(result.refined_transcript)
        }
        if (result.transcript_correction_summary?.length) {
          setCorrections(result.transcript_correction_summary)
        }
        if (result.transcript_glossary_matches?.length) {
          setGlossaryMatches(result.transcript_glossary_matches)
        }
        if (result.refinement_display_summary) {
          setRefinementDisplaySummary(result.refinement_display_summary)
        }
        if (result.transcript_needs_review) {
          setTranscriptNeedsReview(true)
        }
        // Capture timestamped segments from faster-whisper
        if (result.transcript_segments?.length) {
          setTranscriptSegments(result.transcript_segments)
        }
        // Always show refined by default
        setShowingRaw(false)
      }
    } catch (err) {
      setTranscribeError(err instanceof Error ? err.message : "Transcription failed. Please try again.")
    } finally {
      setTranscribing(false)
    }
  }

  // ── Re-run refinement ──────────────────────────────────────────────────────
  async function handleReRefine() {
    setReRefining(true)
    setReRefineError(null)
    try {
      const result: ProjectDefenseRefineTranscriptResponse = await refineDefenseTranscript(session.id)
      setRawTranscript(result.raw_transcript)
      setRefinedTranscript(result.refined_transcript)
      setCorrections(result.transcript_correction_summary)
      setGlossaryMatches(result.transcript_glossary_matches)
      setRefinementDisplaySummary(result.refinement_display_summary)
      setTranscriptNeedsReview(result.transcript_needs_review)
      // Switch to refined view and update editable textarea
      setShowingRaw(false)
      onTranscriptChange(result.refined_transcript)
    } catch (err) {
      setReRefineError(err instanceof Error ? err.message : "Correction failed. Please try again.")
    } finally {
      setReRefining(false)
    }
  }

  // ── Toggle raw / refined ───────────────────────────────────────────────────
  function handleToggleRaw() {
    if (!rawTranscript || !refinedTranscript) return
    const nextShowRaw = !showingRaw
    setShowingRaw(nextShowRaw)
    // Keep textarea editable — switch content but don't break the form
    onTranscriptChange(nextShowRaw ? rawTranscript : refinedTranscript)
  }

  // ── File select ────────────────────────────────────────────────────────────
  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (!f) return
    setUploadError(null)
    setUploadResult(null)
    // Warn the user that the existing transcript may no longer match this new file
    if (defenseTranscript.trim() || rawTranscript || refinedTranscript) {
      setTranscriptStale(true)
    }
    const ext = f.name.split(".").pop()?.toLowerCase() ?? ""
    if (!(ALLOWED_DEFENSE_MEDIA_EXTS as readonly string[]).includes(ext)) {
      setUploadError(`File type .${ext} is not supported. Allowed: ${ALLOWED_DEFENSE_MEDIA_EXTS.join(", ")}.`)
      setMediaFile(null)
      return
    }
    if (f.size > MAX_DEFENSE_MEDIA_MB * 1024 * 1024) {
      setUploadError(`File is ${fmtBytes(f.size)} — maximum is ${MAX_DEFENSE_MEDIA_MB} MB.`)
      setMediaFile(null)
      return
    }
    setMediaFile(f)
  }

  // ── File upload ────────────────────────────────────────────────────────────
  async function handleUpload() {
    if (!mediaFile) return
    setUploading(true)
    setUploadProgress(0)
    setUploadError(null)
    try {
      const result = await uploadProjectDefenseMedia(session.id, mediaFile, pct => setUploadProgress(pct))
      setUploadResult(result)
      setUploadProgress(100)
      // New media uploaded — clear the old transcript so the user must generate
      // or paste a fresh one that matches this file before analysis.
      onTranscriptChange("")
      setRawTranscript(null)
      setRefinedTranscript(null)
      setCorrections([])
      setGlossaryMatches([])
      setRefinementDisplaySummary("")
      setTranscriptNeedsReview(false)
      setShowingRaw(false)
      setTranscriptStale(false)
      setTranscribeMsg(null)
      setTranscribeError(null)
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed. Please try again.")
    } finally {
      setUploading(false)
    }
  }

  // ── Recording ──────────────────────────────────────────────────────────────
  async function startRecording() {
    setRecError(null)
    // If there's an existing transcript, mark it stale — the new recording will
    // replace the media and the old text may no longer match.
    if (defenseTranscript.trim() || rawTranscript || refinedTranscript) {
      setTranscriptStale(true)
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mr = new MediaRecorder(stream)
      mediaRecorderRef.current = mr
      chunksRef.current = []
      mr.ondataavailable = (e: BlobEvent) => { if (e.data.size > 0) chunksRef.current.push(e.data) }
      mr.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" })
        recordedBlobRef.current = blob
        setRecordedObjectUrl(prev => {
          if (prev) URL.revokeObjectURL(prev)
          return URL.createObjectURL(blob)
        })
        setRecState("recorded")
        stream.getTracks().forEach(t => t.stop())
      }
      mr.start()
      setRecState("recording")
      setRecordingSeconds(0)
      timerRef.current = setInterval(() => setRecordingSeconds(s => s + 1), 1000)
    } catch {
      setRecError("Could not access microphone. Check browser permissions and try again.")
    }
  }

  function stopRecording() {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    mediaRecorderRef.current?.stop()
  }

  function clearRecording() {
    setRecordedObjectUrl(prev => { if (prev) URL.revokeObjectURL(prev); return null })
    setRecState("idle")
    setRecordingSeconds(0)
    setRecUploadResult(null)
    recordedBlobRef.current = null
  }

  async function handleUploadRecording() {
    const blob = recordedBlobRef.current
    if (!blob) return
    setRecUploading(true)
    setRecUploadProgress(0)
    setRecError(null)
    const file = new File([blob], `defense-recording-${Date.now()}.webm`, { type: "audio/webm" })
    try {
      const result = await uploadProjectDefenseMedia(session.id, file, pct => setRecUploadProgress(pct))
      setRecUploadResult(result)
      setRecUploadProgress(100)
      // New recording uploaded — clear old transcript so user must generate or
      // paste a fresh one for this recording before analysis.
      onTranscriptChange("")
      setRawTranscript(null)
      setRefinedTranscript(null)
      setCorrections([])
      setGlossaryMatches([])
      setRefinementDisplaySummary("")
      setTranscriptNeedsReview(false)
      setShowingRaw(false)
      setTranscriptStale(false)
      setTranscribeMsg(null)
      setTranscribeError(null)
    } catch (err) {
      setRecError(err instanceof Error ? err.message : "Recording upload failed.")
    } finally {
      setRecUploading(false)
    }
  }

  // ── Tab button style ───────────────────────────────────────────────────────
  const tabBtn = (active: boolean): CSSProperties => ({
    flex: 1,
    padding: "8px 12px",
    fontSize: 12,
    fontWeight: active ? 700 : 500,
    color: active ? "#065f46" : "#6b7280",
    background: active ? "#f0fdf4" : "transparent",
    borderTop: "none", borderLeft: "none", borderRight: "none",
    borderBottom: active ? "2px solid #16a34a" : "2px solid transparent",
    cursor: "pointer",
    transition: "all 0.15s",
  })

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {/* ── Section header ─────────────────────────────────────────────────── */}
      <div>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "var(--ink)" }}>
          Project Defense Video / Transcript
        </h3>
        <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--ink-2)", lineHeight: 1.6 }}>
          Record or upload an explanation, review the transcript, then analyze how well it
          supports your claimed skills.
        </p>
      </div>

      {/* ── Input mode card ────────────────────────────────────────────────── */}
      <div style={{ border: "1px solid #e5e7eb", borderRadius: 14, overflow: "hidden" }}>
        {/* Tab bar */}
        <div style={{ display: "flex", borderBottom: "1px solid #e5e7eb", background: "#f9fafb" }}>
          {(["upload", "record", "paste"] as DefenseInputTab[]).map(tab => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              style={tabBtn(activeTab === tab)}
            >
              {tab === "upload" ? "⬆ Upload File" : tab === "record" ? "⏺ Record" : "✏ Paste"}
            </button>
          ))}
        </div>

        <div style={{ padding: "14px 16px", display: "grid", gap: 12 }}>
          {/* ── Upload tab ──────────────────────────────────────────────────── */}
          {activeTab === "upload" && (
            <div style={{ display: "grid", gap: 10 }}>
              <p style={{ margin: 0, fontSize: 12, color: "var(--ink-2)", lineHeight: 1.6 }}>
                Upload a video or audio recording of your project explanation.
                Automatic transcription is not connected yet — paste or edit your transcript in the
                field below after uploading.
              </p>

              {/* File picker */}
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept={ALLOWED_DEFENSE_MEDIA_ACCEPT}
                  onChange={handleFileSelect}
                  style={{ display: "none" }}
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading}
                  style={{
                    padding: "8px 16px", borderRadius: 8, border: "1px solid #d1d5db",
                    background: uploading ? "#f3f4f6" : "#fff", color: "#374151",
                    fontSize: 13, fontWeight: 600, cursor: uploading ? "not-allowed" : "pointer",
                  }}
                >
                  {mediaFile ? "Change File" : "Choose File"}
                </button>
                <span style={{ fontSize: 11, color: "var(--muted)" }}>
                  MP4, MOV, WebM, MP3, WAV, M4A · max {MAX_DEFENSE_MEDIA_MB} MB
                </span>
              </div>

              {/* Selected file info */}
              {mediaFile && (
                <div style={{
                  background: "#f9fafb", border: "1px solid #e5e7eb", borderRadius: 8,
                  padding: "8px 12px", display: "flex", gap: 8, alignItems: "center",
                }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: "#111827", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {mediaFile.name}
                  </span>
                  <span style={{ fontSize: 11, color: "#6b7280", flexShrink: 0 }}>{fmtBytes(mediaFile.size)}</span>
                </div>
              )}

              {/* Validation / upload error */}
              {uploadError && (
                <div role="alert" style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: "8px 12px", fontSize: 12, color: "#991b1b" }}>
                  {uploadError}
                </div>
              )}

              {/* Upload button + progress */}
              {mediaFile && !uploadResult && (
                <div style={{ display: "grid", gap: 8 }}>
                  <button
                    type="button"
                    onClick={() => void handleUpload()}
                    disabled={uploading}
                    style={{
                      padding: "9px 18px", borderRadius: 9,
                      background: uploading ? "#f3f4f6" : "#1d4ed8",
                      color: uploading ? "#9ca3af" : "#fff",
                      border: "1px solid transparent",
                      fontSize: 13, fontWeight: 700,
                      cursor: uploading ? "not-allowed" : "pointer",
                      width: "fit-content",
                    }}
                  >
                    {uploading ? `Uploading… ${uploadProgress}%` : "Upload File"}
                  </button>
                  {uploading && (
                    <div style={{ height: 5, background: "#e0e7ff", borderRadius: 999 }}>
                      <div style={{ height: 5, borderRadius: 999, background: "#2563eb", width: `${uploadProgress}%`, transition: "width 0.3s ease" }} />
                    </div>
                  )}
                </div>
              )}

              {/* Upload success / no-storage advisory */}
              {uploadResult && (
                uploadResult.media_storage_path ? (
                  <div style={{ background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: 8, padding: "8px 12px", fontSize: 12, color: "#065f46" }}>
                    ✓ <strong>{uploadResult.media_filename}</strong> uploaded and stored.
                  </div>
                ) : (
                  <div style={{ background: "#fffbeb", border: "1px solid #fef08a", borderRadius: 8, padding: "8px 12px", fontSize: 12, color: "#854d0e" }}>
                    ⚠ <strong>{uploadResult.media_filename}</strong> registered, but no storage bucket is configured —
                    {" "}automatic transcription is unavailable. Paste your transcript manually below.
                  </div>
                )
              )}

              {/* Privacy note */}
              <div style={{ background: "#fafafa", border: "1px solid #f3f4f6", borderRadius: 8, padding: "8px 12px" }}>
                <p style={{ margin: 0, fontSize: 11, color: "#6b7280", lineHeight: 1.55 }}>
                  🔒 <strong>Media is private by default.</strong> It is never shared with recruiters
                  without your explicit consent. Sensitive data detected in your transcript will be
                  flagged before storage.
                </p>
              </div>
            </div>
          )}

          {/* ── Record tab ──────────────────────────────────────────────────── */}
          {activeTab === "record" && (
            <div style={{ display: "grid", gap: 10 }}>
              <p style={{ margin: 0, fontSize: 12, color: "var(--ink-2)", lineHeight: 1.6 }}>
                Record a brief audio explanation in your browser using your microphone — no video
                is captured. Paste or type your transcript in the field below after recording.
              </p>

              {/* Controls */}
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                {recState === "idle" && (
                  <button
                    type="button"
                    onClick={() => void startRecording()}
                    style={{
                      padding: "9px 18px", borderRadius: 9,
                      background: "#dc2626", color: "#fff",
                      border: "1px solid transparent",
                      fontSize: 13, fontWeight: 700, cursor: "pointer",
                    }}
                  >
                    ⏺ Start Recording
                  </button>
                )}
                {recState === "recording" && (
                  <>
                    <button
                      type="button"
                      onClick={stopRecording}
                      style={{
                        padding: "9px 18px", borderRadius: 9,
                        background: "#111827", color: "#fff",
                        border: "1px solid transparent",
                        fontSize: 13, fontWeight: 700, cursor: "pointer",
                      }}
                    >
                      ⏹ Stop
                    </button>
                    <span style={{
                      fontSize: 13, fontWeight: 700, color: "#dc2626",
                      padding: "4px 10px", background: "#fef2f2",
                      border: "1px solid #fecaca", borderRadius: 999,
                    }}>
                      ● {fmtSeconds(recordingSeconds)}
                    </span>
                  </>
                )}
              </div>

              {/* Playback + upload recording */}
              {recState === "recorded" && recordedObjectUrl && (
                <div style={{ display: "grid", gap: 8 }}>
                  {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
                  <audio controls src={recordedObjectUrl} style={{ width: "100%", height: 36 }} />
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                    <button
                      type="button"
                      onClick={() => void handleUploadRecording()}
                      disabled={recUploading || !!recUploadResult}
                      style={{
                        padding: "8px 16px", borderRadius: 8,
                        background: recUploading || recUploadResult ? "#f3f4f6" : "#1d4ed8",
                        color: recUploading || recUploadResult ? "#9ca3af" : "#fff",
                        border: "1px solid transparent",
                        fontSize: 12, fontWeight: 700,
                        cursor: recUploading || recUploadResult ? "not-allowed" : "pointer",
                      }}
                    >
                      {recUploading ? `Uploading… ${recUploadProgress}%` : recUploadResult ? "Uploaded ✓" : "Save Recording"}
                    </button>
                    <button
                      type="button"
                      onClick={clearRecording}
                      disabled={recUploading}
                      style={{
                        padding: "8px 12px", borderRadius: 8,
                        background: "#fff", color: "#6b7280",
                        border: "1px solid #d1d5db",
                        fontSize: 12, fontWeight: 500,
                        cursor: recUploading ? "not-allowed" : "pointer",
                      }}
                    >
                      Re-record
                    </button>
                  </div>
                  {recUploading && (
                    <div style={{ height: 5, background: "#e0e7ff", borderRadius: 999 }}>
                      <div style={{ height: 5, borderRadius: 999, background: "#2563eb", width: `${recUploadProgress}%`, transition: "width 0.3s ease" }} />
                    </div>
                  )}
                  {recUploadResult && (
                    recUploadResult.media_storage_path ? (
                      <div style={{ background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: 8, padding: "8px 12px", fontSize: 12, color: "#065f46" }}>
                        ✓ Recording saved. Media uploaded and stored.
                      </div>
                    ) : (
                      <div style={{ background: "#fffbeb", border: "1px solid #fef08a", borderRadius: 8, padding: "8px 12px", fontSize: 12, color: "#854d0e" }}>
                        ⚠ Recording saved locally, but no storage bucket is configured —
                        {" "}automatic transcription is unavailable. Paste your transcript manually below.
                      </div>
                    )
                  )}
                </div>
              )}

              {/* Recording error */}
              {recError && (
                <div role="alert" style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: "8px 12px", fontSize: 12, color: "#991b1b" }}>
                  {recError}
                </div>
              )}
            </div>
          )}

          {/* ── Paste tab ───────────────────────────────────────────────────── */}
          {activeTab === "paste" && (
            <div style={{ display: "grid", gap: 6 }}>
              <p style={{ margin: 0, fontSize: 12, color: "var(--ink-2)", lineHeight: 1.6 }}>
                If you have an existing transcript or written explanation, paste it directly in the
                field below and click <strong>Analyze Project Defense</strong>.
              </p>
              <ul style={{ margin: 0, padding: "0 0 0 18px", fontSize: 12, color: "var(--ink-2)", lineHeight: 1.7 }}>
                <li>Explain the problem you solved and why it mattered.</li>
                <li>Describe what you built — your role and technical choices.</li>
                <li>Mention the tools, libraries, and frameworks you used.</li>
                <li>Talk about limitations and what you would improve next.</li>
              </ul>
            </div>
          )}
        </div>
      </div>

      {/* ── Stale transcript warning (file selected / recording started, not yet uploaded) ── */}
      {transcriptStale && (
        <div role="alert" style={{
          background: "#fffbeb", border: "1px solid #f59e0b",
          borderRadius: 10, padding: "10px 14px",
          fontSize: 12, color: "#92400e", lineHeight: 1.6,
          display: "flex", gap: 10, alignItems: "flex-start",
        }}>
          <span style={{ fontSize: 16, flexShrink: 0 }}>⚠</span>
          <span>
            <strong>New media selected.</strong>{" "}
            The previous transcript was generated from a different file and may no longer match.
            Upload the new file to reset the transcript — then generate a fresh transcript or paste one before analysis.
          </span>
        </div>
      )}

      {/* ── Transcription status notice ───────────────────────────────────── */}
      {defenseAnalysis?.transcription_status && txStatus !== "not_started" && txStatus !== "analysis_complete" && (
        <div style={{
          background: statusCfg.bg, border: `1px solid ${statusCfg.border}`,
          borderRadius: 10, padding: "8px 12px",
          fontSize: 12, color: statusCfg.color, lineHeight: 1.55,
        }}>
          <strong>Status:</strong> {statusCfg.label}
          {txStatus === "uploaded" && (
            <span>
              {" "}— Automatic transcription is not connected yet. Paste or edit your transcript below.
            </span>
          )}
        </div>
      )}

      {/* ── Registered media badge ────────────────────────────────────────── */}
      {/* Prefer the newest upload result; fall back to persisted analysis filename */}
      {(uploadResult?.media_filename || recUploadResult?.media_filename || defenseAnalysis?.media_filename) && (
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{
            fontSize: 11, fontWeight: 700, letterSpacing: "0.05em",
            padding: "2px 10px", borderRadius: 999,
            background: (uploadResult || recUploadResult) ? "#dcfce7" : "#eff6ff",
            color: (uploadResult || recUploadResult) ? "#166534" : "#1d4ed8",
            border: `1px solid ${(uploadResult || recUploadResult) ? "#bbf7d0" : "#bfdbfe"}`,
          }}>
            {(uploadResult || recUploadResult) ? "NEW MEDIA" : "MEDIA"}
          </span>
          <span style={{ fontSize: 12, color: "#374151" }}>
            {uploadResult?.media_filename ?? recUploadResult?.media_filename ?? defenseAnalysis?.media_filename}
          </span>
        </div>
      )}

      {/* ── Generate Transcript ───────────────────────────────────────────── */}
      {hasStoredFile && txStatus !== "analysis_complete" && (
        <div style={{
          border: "1px solid #e0e7ff", borderRadius: 12, background: "#f5f3ff",
          padding: "12px 16px", display: "grid", gap: 10,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={() => void handleTranscribe()}
              disabled={transcribing || defenseAnalyzing}
              style={{
                padding: "9px 18px", borderRadius: 9,
                background: transcribing || defenseAnalyzing ? "#f3f4f6" : "#4f46e5",
                color: transcribing || defenseAnalyzing ? "#9ca3af" : "#fff",
                border: "1px solid transparent",
                fontSize: 13, fontWeight: 700,
                cursor: transcribing || defenseAnalyzing ? "not-allowed" : "pointer",
              }}
            >
              {transcribing ? "Transcribing…" : "✦ Generate Transcript"}
            </button>
            <span style={{ fontSize: 11, color: "#6d28d9", lineHeight: 1.5 }}>
              Auto-generate transcript from your uploaded or recorded media.
            </span>
          </div>

          {/* Success / not-configured message */}
          {transcribeMsg && !transcribeError && (
            <div style={{
              background: transcribeMsg.toLowerCase().includes("not configured") ? "#fffbeb" : "#f0fdf4",
              border: `1px solid ${transcribeMsg.toLowerCase().includes("not configured") ? "#fef08a" : "#bbf7d0"}`,
              borderRadius: 8, padding: "8px 12px", fontSize: 12,
              color: transcribeMsg.toLowerCase().includes("not configured") ? "#854d0e" : "#065f46",
              lineHeight: 1.55,
            }}>
              {transcribeMsg.toLowerCase().includes("not configured")
                ? <>⚠ {transcribeMsg}</>
                : <>✓ {transcribeMsg}</>
              }
            </div>
          )}

          {/* Error */}
          {transcribeError && (
            <div role="alert" style={{
              background: "#fef2f2", border: "1px solid #fecaca",
              borderRadius: 8, padding: "8px 12px", fontSize: 12, color: "#991b1b",
            }}>
              {transcribeError}
            </div>
          )}
        </div>
      )}

      {/* ── Timestamped transcript segments (local_whisper / faster-whisper) ─ */}
      {transcriptSegments && transcriptSegments.length > 0 && (
        <div style={{ border: "1px solid #dbeafe", borderRadius: 12, overflow: "hidden" }}>
          <div style={{ background: "#eff6ff", borderBottom: "1px solid #dbeafe", padding: "8px 14px",
            display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: "#1d4ed8" }}>⏱ Timestamped Segments</span>
            <span style={{ fontSize: 11, color: "#3b82f6" }}>— {transcriptSegments.length} segment{transcriptSegments.length !== 1 ? "s" : ""} from local_whisper</span>
          </div>
          <div style={{ maxHeight: 180, overflowY: "auto", padding: "8px 14px" }}>
            {transcriptSegments.map((seg, i) => {
              const fmtTs = (s: number) => {
                const m = Math.floor(s / 60).toString().padStart(2, "0")
                const sec = Math.floor(s % 60).toString().padStart(2, "0")
                return `${m}:${sec}`
              }
              return (
                <div key={i} style={{ display: "flex", gap: 8, padding: "4px 0",
                  borderBottom: i < transcriptSegments.length - 1 ? "1px solid #eff6ff" : "none" }}>
                  <span style={{ fontSize: 10, color: "#3b82f6", fontFamily: "monospace",
                    whiteSpace: "nowrap", minWidth: 90, paddingTop: 1 }}>
                    {fmtTs(seg.start_time)}–{fmtTs(seg.end_time)}
                  </span>
                  <span style={{ fontSize: 12, color: "#374151", lineHeight: 1.5 }}>
                    {seg.text}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── Transcript review card ────────────────────────────────────────── */}
      <div style={{ border: "1px solid #e5e7eb", borderRadius: 14, overflow: "hidden" }}>
        <div style={{ background: "#f9fafb", borderBottom: "1px solid #e5e7eb", padding: "12px 16px" }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#111827" }}>
            {(uploadResult || recUploadResult) && !defenseTranscript.trim()
              ? "Generate or Paste Transcript"
              : defenseAnalysis
              ? "Update Transcript & Re-analyze"
              : "Review / Paste Transcript"}
          </div>
          <p style={{ margin: "3px 0 0", fontSize: 11, color: "#6b7280", lineHeight: 1.55 }}>
            Describe the problem you solved, what you built, your role, tools used, key technical
            decisions, limitations, and future improvements. Recruiters may see this summary
            alongside your evidence.
          </p>
        </div>

        <div style={{ padding: "14px 16px", display: "grid", gap: 12 }}>

          {/* ── New-media notice — transcript was reset after upload ──────── */}
          {(uploadResult || recUploadResult) && !defenseTranscript.trim() && (
            <div role="alert" style={{
              background: "#fffbeb", border: "1px solid #fef08a",
              borderRadius: 8, padding: "10px 14px",
              fontSize: 12, color: "#854d0e", lineHeight: 1.6,
            }}>
              ⚠ <strong>New media uploaded.</strong>{" "}
              Generate a new transcript from the recording or paste your transcript here before analysis.
            </div>
          )}

          {/* ── VeriBridge AI Refinement banner ──────────────────────────── */}
          {refinedTranscript && rawTranscript && (
            <div style={{
              background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: 10,
              padding: "10px 14px", display: "grid", gap: 8,
            }}>
              {/* Header row */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                  <span style={{
                    fontSize: 10, fontWeight: 800, letterSpacing: "0.07em",
                    padding: "2px 8px", borderRadius: 999,
                    background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0",
                  }}>
                    ✦ VERIBRIDGE AI
                  </span>
                  <span style={{ fontSize: 12, fontWeight: 700, color: "#166534" }}>
                    Transcript corrected with VeriBridge AI
                  </span>
                </div>
                {/* Raw / Refined toggle */}
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <button
                    type="button"
                    onClick={handleToggleRaw}
                    style={{
                      fontSize: 11, fontWeight: 600,
                      padding: "4px 10px", borderRadius: 7,
                      background: showingRaw ? "#f3f4f6" : "#dcfce7",
                      color: showingRaw ? "#374151" : "#166534",
                      border: `1px solid ${showingRaw ? "#d1d5db" : "#86efac"}`,
                      cursor: "pointer",
                    }}
                  >
                    {showingRaw ? "Use corrected transcript" : "View raw transcript"}
                  </button>
                </div>
              </div>

              {/* Correction summary */}
              {refinementDisplaySummary && (
                <p style={{ margin: 0, fontSize: 12, color: "#065f46", lineHeight: 1.55 }}>
                  {refinementDisplaySummary}
                </p>
              )}

              {/* Correction detail (collapsed) */}
              {corrections.length > 0 && (
                <details style={{ fontSize: 11, color: "#166534" }}>
                  <summary style={{ cursor: "pointer", fontWeight: 600 }}>
                    {corrections.length} correction{corrections.length !== 1 ? "s" : ""} made — click to review
                  </summary>
                  <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 4 }}>
                    {corrections.slice(0, 12).map((c, i) => (
                      <span key={i} style={{
                        fontSize: 11, padding: "2px 8px", borderRadius: 999,
                        background: "#fff", border: "1px solid #bbf7d0", color: "#374151",
                      }}>
                        <span style={{ color: "#dc2626" }}>{c.original}</span>
                        {" → "}
                        <span style={{ color: "#166534", fontWeight: 600 }}>{c.corrected}</span>
                      </span>
                    ))}
                    {corrections.length > 12 && (
                      <span style={{ fontSize: 11, color: "#6b7280" }}>+{corrections.length - 12} more</span>
                    )}
                  </div>
                </details>
              )}

              {/* Needs review warning */}
              {transcriptNeedsReview && (
                <div style={{
                  background: "#fffbeb", border: "1px solid #fef08a",
                  borderRadius: 8, padding: "6px 10px",
                  fontSize: 11, color: "#854d0e", lineHeight: 1.55,
                }}>
                  ⚠ <strong>Please review this transcript before analysis.</strong>{" "}
                  Several corrections were applied — verify they are accurate.
                </div>
              )}

              {/* Currently viewing raw notice */}
              {showingRaw && (
                <div style={{
                  background: "#fffbeb", border: "1px solid #fef08a",
                  borderRadius: 8, padding: "6px 10px",
                  fontSize: 11, color: "#854d0e",
                }}>
                  👁 Viewing raw transcript. The editable field shows the original ASR output.
                  Click <strong>Use corrected transcript</strong> to switch back.
                </div>
              )}

              {/* Re-correct button (useful if skills/context updated) */}
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <button
                  type="button"
                  onClick={() => void handleReRefine()}
                  disabled={reRefining || defenseAnalyzing}
                  style={{
                    fontSize: 11, fontWeight: 600,
                    padding: "4px 12px", borderRadius: 7,
                    background: reRefining ? "#f3f4f6" : "#fff",
                    color: reRefining ? "#9ca3af" : "#059669",
                    border: "1px solid #a7f3d0",
                    cursor: reRefining || defenseAnalyzing ? "not-allowed" : "pointer",
                  }}
                >
                  {reRefining ? "Re-correcting…" : "↻ Re-correct"}
                </button>
                <span style={{ fontSize: 11, color: "#6b7280" }}>Re-run correction if you updated your skills or project context.</span>
              </div>

              {reRefineError && (
                <div role="alert" style={{ fontSize: 11, color: "#991b1b", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 6, padding: "4px 8px" }}>
                  {reRefineError}
                </div>
              )}
            </div>
          )}

          {/* Transcript textarea */}
          <div style={{ display: "grid", gap: 4 }}>
            <label style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>
              Transcript <span style={{ color: "#dc2626" }}>*</span>
              {refinedTranscript && rawTranscript && (
                <span style={{
                  marginLeft: 8, fontSize: 10, fontWeight: 700,
                  padding: "1px 7px", borderRadius: 999,
                  background: showingRaw ? "#f3f4f6" : "#dcfce7",
                  color: showingRaw ? "#6b7280" : "#166534",
                  border: `1px solid ${showingRaw ? "#d1d5db" : "#86efac"}`,
                  letterSpacing: "0.05em",
                }}>
                  {showingRaw ? "RAW" : "REFINED"}
                </span>
              )}
            </label>
            <textarea
              value={defenseTranscript}
              onChange={e => onTranscriptChange(e.target.value)}
              disabled={defenseAnalyzing}
              placeholder={
                (uploadResult || recUploadResult) && !defenseTranscript.trim()
                  ? "Generate a transcript from the new recording above, or paste your transcript here. Explain the problem, what you built, your role, tools used, main workflow, technical decisions, limitations, and future improvements."
                  : "Paste or type your project explanation here. Explain the problem, what you built, your role, tools used, main workflow, technical decisions, limitations, and future improvements."
              }
              style={{ ...inp, minHeight: 150, resize: "vertical", fontFamily: "inherit", lineHeight: 1.55 }}
            />
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontSize: 11, color: "var(--muted)" }}>
                Aim for at least 100 words. Be specific about your role and technical choices.
              </span>
              <span style={{
                fontSize: 11, fontWeight: 600,
                color: transcriptWords < 30 ? "#dc2626" : transcriptWords < 80 ? "#ca8a04" : "#166534",
              }}>
                {transcriptWords} words
              </span>
            </div>
          </div>

          {/* Analyze button */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={onAnalyze}
              disabled={!canAnalyze}
              title={
                transcriptStale
                  ? "Upload the new media file first to reset the transcript."
                  : transcriptWords < 30
                  ? "Write at least 30 words before analyzing."
                  : undefined
              }
              style={{
                border: "1px solid transparent",
                background: !canAnalyze ? "var(--bg-2)" : "#065f46",
                color: !canAnalyze ? "var(--muted)" : "#fff",
                borderRadius: 10, padding: "10px 20px",
                fontWeight: 700, fontSize: 14,
                cursor: !canAnalyze ? "not-allowed" : "pointer",
              }}
            >
              {defenseAnalyzing
                ? "Analyzing…"
                : transcriptStale || ((uploadResult || recUploadResult) && !defenseTranscript.trim())
                ? "Generate Transcript First"
                : defenseAnalysis
                ? "Re-analyze Defense"
                : "Analyze Project Defense"}
            </button>
            {transcriptStale && (
              <span style={{ fontSize: 11, color: "#92400e" }}>Upload the new file to reset the transcript before analysis</span>
            )}
            {!transcriptStale && transcriptWords > 0 && transcriptWords < 30 && (
              <span style={{ fontSize: 11, color: "#dc2626" }}>Need at least 30 words to analyze</span>
            )}
          </div>

          {/* Analyze error */}
          {defenseAnalyzeError && !defenseAnalyzing && (
            <div role="alert" style={{ border: "1px solid #fecaca", background: "#fef2f2", borderRadius: 8, padding: "8px 12px", fontSize: 12, color: "#991b1b" }}>
              {defenseAnalyzeError}
            </div>
          )}
        </div>
      </div>

      {/* ── In-progress stages ────────────────────────────────────────────── */}
      {defenseAnalyzing && (
        <div style={{ border: "1px solid #d1fae5", borderRadius: 12, background: "#f0fdf4", padding: "14px 16px", display: "grid", gap: 12 }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#065f46" }}>Analyzing defense transcript…</div>
            <p style={{ margin: "4px 0 0", fontSize: 12, color: "#064e3b", lineHeight: 1.65 }}>
              VeriBridge is reviewing your explanation. This usually takes 5–15 seconds.
            </p>
          </div>
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
              <span style={{ fontSize: 11, color: "#16a34a" }}>Analysis in progress</span>
              <span style={{ fontSize: 11, fontWeight: 700, color: "#065f46" }}>{defenseSimProgress}%</span>
            </div>
            <div style={{ height: 6, background: "#bbf7d0", borderRadius: 999 }}>
              <div style={{ height: 6, borderRadius: 999, background: "#16a34a", width: `${defenseSimProgress}%`, transition: "width 0.4s ease" }} />
            </div>
          </div>
          <div style={{ display: "grid", gap: 6 }}>
            {DEFENSE_STAGES.map((stage, i) => {
              const isDone    = i < defenseSimStageIdx
              const isCurrent = i === defenseSimStageIdx
              return (
                <div key={stage.key} style={{ display: "flex", alignItems: "center", gap: 7 }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: isDone ? "#065f46" : isCurrent ? "#16a34a" : "#94a3b8", width: 14, flexShrink: 0, textAlign: "center" }}>
                    {isDone ? "✓" : isCurrent ? "…" : "○"}
                  </span>
                  <span style={{ fontSize: 12, color: isDone ? "#064e3b" : isCurrent ? "#166534" : "#94a3b8" }}>
                    {stage.label}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── Result card ───────────────────────────────────────────────────── */}
      {defenseAnalysis && !defenseAnalyzing && (
        <ProjectDefenseResultCard analysis={defenseAnalysis} sourceScore={sourceScore} />
      )}
    </div>
  )
}

// ── Evidence Discovery Results component ─────────────────────────────────────

const _DISCOVERY_TYPE_ICONS: Record<DiscoveredEvidenceType, string> = {
  github_repository: "⎇",
  video_demo: "▶",
  pdf_report: "📄",
  google_doc: "📝",
  google_drive: "🗂",
  linkedin: "🔗",
  deployed_app: "🚀",
  api_docs: "📚",
  image_or_screenshot: "🖼",
  unknown: "❓",
}

const _DISCOVERY_TYPE_LABELS: Record<DiscoveredEvidenceType, string> = {
  github_repository: "GitHub Repository",
  video_demo: "Video Demo",
  pdf_report: "PDF / Report",
  google_doc: "Google Doc",
  google_drive: "Google Drive",
  linkedin: "LinkedIn",
  deployed_app: "Deployed App",
  api_docs: "API Docs",
  image_or_screenshot: "Screenshot / Image",
  unknown: "Unknown",
}

const _DISCOVERY_TYPE_COLORS: Record<DiscoveredEvidenceType, { bg: string; border: string; text: string }> = {
  github_repository: { bg: "#f0fdf4", border: "#bbf7d0", text: "#166534" },
  video_demo:        { bg: "#fef2f2", border: "#fecaca", text: "#991b1b" },
  pdf_report:        { bg: "#fffbeb", border: "#fde68a", text: "#92400e" },
  google_doc:        { bg: "#eff6ff", border: "#bfdbfe", text: "#1e40af" },
  google_drive:      { bg: "#eff6ff", border: "#bfdbfe", text: "#1e40af" },
  linkedin:          { bg: "#f0f9ff", border: "#bae6fd", text: "#075985" },
  deployed_app:      { bg: "#faf5ff", border: "#e9d5ff", text: "#6b21a8" },
  api_docs:          { bg: "#f0fdfa", border: "#99f6e4", text: "#134e4a" },
  image_or_screenshot: { bg: "#fdf4ff", border: "#f0abfc", text: "#701a75" },
  unknown:           { bg: "var(--bg-2)", border: "var(--line)", text: "var(--ink-2)" },
}

function EvidenceDiscoveryCard({ item }: { item: DiscoveredEvidenceItem }) {
  const icon = _DISCOVERY_TYPE_ICONS[item.evidence_type] ?? "❓"
  const label = _DISCOVERY_TYPE_LABELS[item.evidence_type] ?? item.evidence_type
  const colors = _DISCOVERY_TYPE_COLORS[item.evidence_type] ?? _DISCOVERY_TYPE_COLORS.unknown
  const confidencePct = Math.round(item.confidence * 100)

  return (
    <div style={{
      border: `1px solid ${colors.border}`,
      borderRadius: 10,
      background: colors.bg,
      padding: "10px 12px",
      display: "grid",
      gap: 6,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <span style={{ fontSize: 14 }}>{icon}</span>
        <span style={{ fontSize: 11, fontWeight: 700, color: colors.text }}>{label}</span>
        <span style={{ fontSize: 10, color: "var(--muted)", marginLeft: "auto", fontVariantNumeric: "tabular-nums" }}>
          {confidencePct}% confidence
        </span>
      </div>
      {item.title && (
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink)", lineHeight: 1.4 }}>
          {item.title.length > 80 ? item.title.slice(0, 78) + "…" : item.title}
        </div>
      )}
      <div style={{ fontSize: 11, color: "var(--ink-2)" }}>
        <span style={{ fontWeight: 600 }}>{item.domain}</span>
      </div>
      <div style={{ fontSize: 11, color: "var(--muted)", lineHeight: 1.5 }}>{item.reason}</div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginTop: 2 }}>
        <span style={{
          fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 999,
          background: colors.border, color: colors.text,
        }}>
          → {item.suggested_action}
        </span>
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          style={{ fontSize: 10, color: "var(--muted)", textDecoration: "underline" }}
        >
          Open ↗
        </a>
      </div>
    </div>
  )
}

export function EvidenceDiscoveryResults({ discovery }: { discovery: WebsiteEvidenceDiscoveryResponse }) {
  if (discovery.error && !["fetch_timeout", "fetch_error", "http_error", "non_html_response"].includes(discovery.error)) {
    return (
      <div style={{ fontSize: 11, color: "#991b1b", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: "6px 10px" }}>
        Could not scan this URL: {discovery.limitation ?? discovery.error}
      </div>
    )
  }

  return (
    <div style={{ display: "grid", gap: 8 }}>
      {/* Summary row */}
      <div style={{ fontSize: 11, color: "var(--ink-2)" }}>
        {discovery.page_title && (
          <span style={{ fontWeight: 600 }}>"{discovery.page_title}" — </span>
        )}
        {discovery.total_discovered > 0
          ? `${discovery.total_discovered} evidence source${discovery.total_discovered !== 1 ? "s" : ""} found`
          : "No evidence sources detected in static HTML"}
        {discovery.status_code ? (
          <span style={{ color: "var(--muted)" }}> (HTTP {discovery.status_code})</span>
        ) : null}
      </div>

      {/* JS-heavy limitation */}
      {discovery.js_heavy_warning && discovery.limitation && (
        <div style={{ fontSize: 11, color: "#92400e", background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 8, padding: "6px 10px" }}>
          ⚠ {discovery.limitation}
        </div>
      )}

      {/* General limitation (non-JS-heavy) */}
      {!discovery.js_heavy_warning && discovery.limitation && (
        <div style={{ fontSize: 11, color: "var(--muted)", background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 8, padding: "6px 10px" }}>
          {discovery.limitation}
        </div>
      )}

      {/* Evidence cards */}
      {discovery.items.map((item, idx) => (
        <EvidenceDiscoveryCard key={`${item.url}-${idx}`} item={item} />
      ))}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function ExtensionProofPanel({
  onBack,
  onSessionComplete,
  requestedSessionId = null,
  historyMode = false,
}: {
  onBack: () => void
  onSessionComplete?: () => void
  requestedSessionId?: string | null
  historyMode?: boolean
}) {
  const [step, setStep]                 = useState<PanelStep>("form")
  const [form, setForm]                 = useState<FormState>(initialWebsiteProofForm)
  const [availableProjects, setAvailableProjects] = useState<VBRProjectResponse[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState("")
  const [projectLoadError, setProjectLoadError] = useState<string | null>(null)
  const [historySessions, setHistorySessions] = useState<ExtensionProofSessionResponse[] | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [resumeCandidate, setResumeCandidate] = useState<{
    session: ExtensionProofSessionResponse
    draft: ActiveExtensionProofSessionDraft
  } | null>(null)
  const [session, setSession]           = useState<ExtensionProofSessionResponse | null>(null)
  const [error, setError]               = useState<string | null>(null)
  const [creating, setCreating]         = useState(false)
  const [starting, setStarting]         = useState(false)
  const [recorderLifecycle, dispatchRecorderLifecycle] = useReducer(
    websiteProofLifecycleReducer,
    undefined,
    createWebsiteProofLifecycle,
  )
  const [recorderConfigRevision, setRecorderConfigRevision] = useState(0)
  const [recorderReady, setRecorderReady] = useState(false)
  const [recorderDiagnosticCode, setRecorderDiagnosticCode] = useState<string | null>(null)
  const [pollingActive, setPoll]        = useState(false)
  const [extensionUploadState, setExtensionUploadState] = useState<ExtensionUploadBridgeState | null>(null)
  const [workflowAnalysis, setWorkflowAnalysis] = useState<WorkflowAnalysisResponse | null>(null)
  const [analyzing, setAnalyzing]       = useState(false)
  const [analyzeError, setAnalyzeError] = useState<string | null>(null)
  const [analyzeTimedOut, setAnalyzeTimedOut] = useState(false)
  const [saveState, setSaveState] = useState<"not_saved" | "saving" | "saved" | "already_saved" | "error">("not_saved")
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveResult, setSaveResult] = useState<ProofFinalizationResult | null>(null)
  const [websiteProofProgressLifecycle, dispatchWebsiteProofProgress] = useReducer(
    websiteProofProgressReducer,
    "idle" as WebsiteProofProgressLifecycle,
  )
  const [workflowProgressNowMs, setWorkflowProgressNowMs] = useState(() => Date.now())
  const [websiteProofProgressLastEvent, setWebsiteProofProgressLastEvent] = useState("init")
  const workflowProgressLifecycleStartedAtRef = useRef(Date.now())
  const previousWorkflowProgressLifecycleRef = useRef<WebsiteProofProgressLifecycle>("idle")
  const explicitSessionIdRef = useRef<string | null>(null)

  function transitionWebsiteProofProgress(event: WebsiteProofProgressEvent): void {
    if (
      event.type === "recording_started" &&
      doesWorkflowProgressOverrideRecordingUi(websiteProofProgressLifecycle)
    ) {
      return
    }
    setWebsiteProofProgressLastEvent(event.type)
    dispatchWebsiteProofProgress(event)
  }

  function transitionRecorderLifecycle(event: WebsiteProofLifecycleEvent, errorCode?: string | null): void {
    dispatchRecorderLifecycle({ event, error_code: errorCode })
  }

  // Load the student's owned projects once. Choosing one creates the strongest,
  // explicit proof→project edge; leaving it blank deliberately creates a
  // vault-only proof that reports cannot count until attached later.
  useEffect(() => {
    let cancelled = false
    void listVBRProjects()
      .then((projects) => {
        if (cancelled) return
        setAvailableProjects(projects)
        const requested = new URL(window.location.href).searchParams.get("project")
        if (requested && projects.some((p) => p.id === requested)) {
          setSelectedProjectId(requested)
        }
      })
      .catch(() => {
        if (!cancelled) setProjectLoadError("Projects could not be loaded. This proof will remain vault-only unless you attach it later.")
      })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!historyMode) return
    let cancelled = false
    setHistorySessions(null)
    setHistoryError(null)
    void listExtensionProofSessions()
      .then((sessions) => {
        if (!cancelled) setHistorySessions(sessions)
      })
      .catch((err) => {
        if (!cancelled) {
          setHistoryError(err instanceof Error ? err.message : "Previous Website Proofs could not be loaded.")
          setHistorySessions([])
        }
      })
    return () => { cancelled = true }
  }, [historyMode])

  // Follow-up recording intent (from sessionStorage, set by Record Follow-up button)
  const [followupIntent, setFollowupIntent] = useState<{
    parentSessionId: string
    skill: string
    objective: string
  } | null>(null)
  const followUpMode = followupIntent !== null

  function resetWebsiteProofForm({ clearDraft = true }: { clearDraft?: boolean } = {}) {
    if (clearDraft) clearActiveExtensionProofSession()
    setForm(initialWebsiteProofForm)
    setSelectedProjectId("")
    setStep("form")
    setSession(null)
    setError(null)
    setCreating(false)
    setStarting(false)
    transitionRecorderLifecycle("RESET")
    setRecorderConfigRevision(0)
    setRecorderReady(false)
    setRecorderDiagnosticCode(null)
    setPoll(false)
    setExtensionUploadState(null)
    setWorkflowAnalysis(null)
    setAnalyzing(false)
    setAnalyzeError(null)
    setAnalyzeTimedOut(false)
    transitionWebsiteProofProgress({ type: "reset" })
    setPrivacyAcknowledged(false)
    setPrivacyScan(null)
    setResumeCandidate(null)
    setSaveState("not_saved")
    setSaveError(null)
    setSaveResult(null)
  }

  function resetAndBack() {
    // Navigating away is not an abandonment action. Keep an unfinished draft
    // available for the explicit Resume choice on the next landing visit.
    resetWebsiteProofForm({ clearDraft: false })
    setFollowupIntent(null)
    clearFollowUpProofDraft()
    onBack()
  }

  // Reset the flow back to a blank form without navigating away — used by
  // "Start new Website Proof" on completed/expired/restored session screens.
  function handleStartNew() {
    resetWebsiteProofForm()
    setFollowupIntent(null)
    clearFollowUpProofDraft()
  }

  function handleResumeCandidate() {
    if (!resumeCandidate) return
    const restored = resumeCandidate.session
    setForm({ ...initialWebsiteProofForm, ...resumeCandidate.draft.form })
    setSession(restored)
    setRecorderConfigRevision(resumeCandidate.draft.configRevision ?? 0)
    setRecorderReady(false)
    if (restored.project_id) setSelectedProjectId(restored.project_id)
    setStep("session_active")
    setResumeCandidate(null)
    if (restored.status === "recording") {
      transitionRecorderLifecycle("RESTORE_RECORDING")
      transitionWebsiteProofProgress({ type: "recording_started" })
    } else if (restored.status === "uploaded_pending_analysis") {
      transitionRecorderLifecycle("RESTORE_PROCESSING")
      transitionWebsiteProofProgress({ type: "upload_succeeded" })
    } else if (restored.status === "analyzing") {
      transitionRecorderLifecycle("RESTORE_PROCESSING")
      transitionWebsiteProofProgress({ type: "analysis_request_started" })
    } else {
      transitionRecorderLifecycle("RESTORE_CREATED")
    }
    if (POLLING_STATUSES.includes(restored.status)) setPoll(true)
  }

  async function handleSaveProof() {
    if (!session || session.status !== "completed") return
    if (!selectedProjectId) {
      setSaveState("error")
      setSaveError("Select the project this Website Proof belongs to before saving.")
      return
    }
    setSaveState("saving")
    setSaveError(null)
    transitionRecorderLifecycle("SAVE_REQUESTED")
    try {
      const result = await finalizeWebsiteProof({
        proof_id: session.id,
        project_id: selectedProjectId,
      })
      setSaveResult(result)
      setSaveState(result.already_finalized ? "already_saved" : "saved")
      transitionRecorderLifecycle("SAVE_COMPLETED")
      setSession((current) => current ? {
        ...current,
        project_id: result.project_id,
        project_relationship_state: result.project_relationship.state,
        finalized_at: result.finalized_at ?? current.finalized_at ?? new Date().toISOString(),
        finalized_project_id: result.project_id,
      } : current)
      clearActiveExtensionProofSession(session.id)
    } catch (err) {
      transitionRecorderLifecycle("RETRYABLE_FAILURE", "finalization_failed")
      setSaveState("error")
      setSaveError(err instanceof Error ? err.message : "This Website Proof could not be saved safely.")
    }
  }

  // On mount, check for follow-up intent stored by the evidence card
  useEffect(() => {
    try {
      const stored = sessionStorage.getItem(FOLLOWUP_INTENT_KEY_FE)
      if (stored) {
        const intent = JSON.parse(stored) as { parentSessionId: string; skill: string; objective: string }
        setFollowupIntent(intent)
        setForm({
          ...initialWebsiteProofForm,
          skillName: intent.skill || "",
          proofObjective: intent.objective || "",
        })
        clearFollowUpProofDraft()
      }
    } catch { /* sessionStorage unavailable */ }
  }, [])

  // Privacy Guard state
  const [privacyAcknowledged, setPrivacyAcknowledged] = useState(false)
  const [privacyScan, setPrivacyScan] = useState<WorkflowPrivacyScanResponse | null>(null)
  const analyzeTimeoutRef               = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Derived from form.websiteUrl — available in both form and session_active steps.
  const urlType = classifyUrl(form.websiteUrl)
  const local = isLocal(urlType)

  useEffect(() => {
    if (followUpMode || historyMode) return
    try {
      if (sessionStorage.getItem(FOLLOWUP_INTENT_KEY_FE)) return
    } catch { /* sessionStorage unavailable */ }
    let cancelled = false

    if (!requestedSessionId) {
      // The bare landing route is always NEW.  A stored unfinished session is
      // offered as a choice below; it never replaces the blank form.
      if (explicitSessionIdRef.current) {
        resetWebsiteProofForm({ clearDraft: false })
        explicitSessionIdRef.current = null
      } else {
        setStep("form")
        setSession(null)
        setResumeCandidate(null)
        setError(null)
      }
      const draft = loadActiveExtensionProofSession()
      if (!draft) {
        return () => { cancelled = true }
      }
      void getExtensionProofSession(draft.sessionId)
        .then((restored) => {
          if (cancelled) return
          if (isResumableExtensionProofSession(restored)) {
            setResumeCandidate({ session: restored, draft })
          } else {
            // Completed/expired records remain in backend history; only the
            // stale "active" pointer is removed.
            clearActiveExtensionProofSession(restored.id)
          }
        })
        .catch((err: unknown) => {
          if (cancelled) return
          // Only a definitive not-found removes the recovery pointer. A
          // transient failure (network outage, auth still hydrating after a
          // hard reload, backend busy) must NOT delete it — that would orphan
          // an unfinished session the user can otherwise resume.
          const message = err instanceof Error ? err.message : ""
          if (message.includes("not found")) {
            clearActiveExtensionProofSession(draft.sessionId)
          }
        })
      return () => { cancelled = true }
    }

    explicitSessionIdRef.current = requestedSessionId
    setResumeCandidate(null)
    setError(null)
    setStep("session_active")
    void getExtensionProofSession(requestedSessionId)
      .then((restored) => {
        if (cancelled) return
        setSession(restored)
        const activeDraft = loadActiveExtensionProofSession()
        if (activeDraft?.sessionId === restored.id) {
          setRecorderConfigRevision(activeDraft.configRevision ?? 0)
        }
        if (restored.project_id) setSelectedProjectId(restored.project_id)
        setForm({
          websiteUrl: restored.website_url ?? "",
          githubUrl: restored.github_url ?? "",
          skillName: (restored.claimed_skills ?? []).join(", "),
          proofObjective: restored.proof_objective ?? "",
        })
        setSaveState(restored.finalized_at ? "already_saved" : "not_saved")
        if (restored.finalized_at) {
          transitionRecorderLifecycle("RESTORE_SAVED")
        } else if (restored.status === "recording") {
          transitionRecorderLifecycle("RESTORE_RECORDING")
          transitionWebsiteProofProgress({ type: "recording_started" })
        } else if (restored.status === "uploaded_pending_analysis") {
          transitionRecorderLifecycle("RESTORE_PROCESSING")
          transitionWebsiteProofProgress({ type: "upload_succeeded" })
        } else if (restored.status === "analyzing") {
          transitionRecorderLifecycle("RESTORE_PROCESSING")
          transitionWebsiteProofProgress({ type: "analysis_request_started" })
        } else if (restored.status === "completed") {
          transitionRecorderLifecycle("RESTORE_ANALYSIS_COMPLETE")
          transitionWebsiteProofProgress({ type: "workflow_report_exists" })
        } else {
          transitionRecorderLifecycle("RESTORE_CREATED")
        }
        if (POLLING_STATUSES.includes(restored.status)) {
          setPoll(true)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSession(null)
          setStep("form")
          setError("This Website Proof was not found or is not available to this account.")
        }
      })
    return () => { cancelled = true }
  }, [followUpMode, historyMode, requestedSessionId])

  useEffect(() => {
    if (!session) return
    if (!isResumableExtensionProofSession(session)) {
      clearActiveExtensionProofSession(session.id)
      return
    }
    saveActiveExtensionProofSession({
      sessionId: session.id,
      form,
      configRevision: recorderConfigRevision,
      savedAt: new Date().toISOString(),
    })
  }, [
    session?.id,
    session?.status,
    form.websiteUrl,
    form.githubUrl,
    form.skillName,
    form.proofObjective,
    recorderConfigRevision,
  ])

  useEffect(() => {
    if (!session) return
    const activeSessionId = session.id
    function handleExtensionStateMessage(event: MessageEvent) {
      if (event.source !== window) return
      const data = event.data as {
        source?: string
        type?: string
        sessionId?: string
        proofSessionId?: string
        payload?: Partial<ExtensionUploadBridgeState> & { proofSessionId?: string }
      } | null
      if (!data || data.source !== "veribridge-extension") return
      const payload = {
        ...(data.payload ?? {}),
        sessionId: data.payload?.sessionId ?? data.sessionId ?? data.proofSessionId,
      }
      if (!payload?.sessionId || payload.sessionId !== activeSessionId) return
      if (data.type === "VERIBRIDGE_PROOF_UPLOAD_STARTED") {
        if (process.env.NODE_ENV === "development") {
          console.info("[WebsiteProofProgress] upload started event received")
        }
        setExtensionUploadState({
          sessionId: payload.sessionId,
          status: "uploading",
          statusMessage: payload.statusMessage ?? "Uploading proof…",
          lastUploadError: null,
          isRecording: payload.isRecording,
        })
        transitionWebsiteProofProgress({ type: "upload_started" })
        transitionRecorderLifecycle("UPLOAD_STARTED")
        return
      }
      if (data.type !== "VERIBRIDGE_EXTENSION_STATE") return
      if (!payload.status) return
      setExtensionUploadState({
        sessionId: payload.sessionId,
        status: payload.status,
        statusMessage: payload.statusMessage,
        lastUploadError: payload.lastUploadError ?? null,
        isRecording: payload.isRecording,
      })
      if (payload.status === "uploading") {
        if (process.env.NODE_ENV === "development") {
          console.info("[WebsiteProofProgress] upload started event received")
        }
        transitionWebsiteProofProgress({ type: "upload_started" })
        transitionRecorderLifecycle("UPLOAD_STARTED")
      } else if (payload.status === "stopped") {
        transitionRecorderLifecycle("STOP_REQUESTED")
      } else if (payload.status === "uploaded") {
        if (process.env.NODE_ENV === "development") {
          console.info("[WebsiteProofProgress] upload success event received")
        }
        transitionWebsiteProofProgress({ type: "upload_succeeded" })
        transitionRecorderLifecycle("UPLOAD_ACCEPTED")
      } else if (payload.status === "upload_failed") {
        transitionWebsiteProofProgress({ type: "upload_failed" })
        transitionRecorderLifecycle("RETRYABLE_FAILURE", "evidence_upload_failed")
      }
    }
    window.addEventListener("message", handleExtensionStateMessage)
    return () => window.removeEventListener("message", handleExtensionStateMessage)
  }, [session?.id])

  // Auth renewal is always bound to the exact acknowledged session + revision.
  // It can replace the expiring credential but cannot reset metadata, API base,
  // lifecycle state, or whichever fresh session is authoritative.
  useEffect(() => {
    if (!session?.id || recorderConfigRevision < 1) return
    const refresh = () => {
      void refreshWebsiteProofRecorderSessionAuth(session.id, recorderConfigRevision)
    }
    const intervalId = window.setInterval(() => {
      refresh()
    }, 45_000)
    return () => window.clearInterval(intervalId)
  }, [session?.id, recorderConfigRevision])

  useEffect(() => {
    if (!session) return
    if ((["uploaded_pending_analysis", "analyzing", "completed"] as ExtensionProofSessionStatus[]).includes(session.status)) {
      setExtensionUploadState((current) => {
        if (!current || current.sessionId !== session.id) return current
        if (current.status !== "uploading") return current
        return { ...current, status: "uploaded", statusMessage: "Proof uploaded successfully" }
      })
    }
    if (session.status === "recording" && !doesWorkflowProgressOverrideRecordingUi(websiteProofProgressLifecycle)) {
      transitionWebsiteProofProgress({ type: "recording_started" })
    } else if (session.status === "uploaded_pending_analysis") {
      transitionWebsiteProofProgress({ type: "upload_succeeded" })
    } else if (session.status === "analyzing") {
      transitionWebsiteProofProgress({ type: "analysis_request_started" })
    }
  }, [session?.id, session?.status, websiteProofProgressLifecycle])

  // ── Session-scoped analysis ───────────────────────────────────────────────
  // workflowAnalysis state may hold a result from a previous session (if the user
  // created a new session without unmounting the panel).  Treat any analysis whose
  // proof_session_id doesn't match the current session as absent so the UI never
  // displays stale data from the wrong session.
  const currentSessionAnalysis: WorkflowAnalysisResponse | null =
    workflowAnalysis?.proof_session_id === session?.id ? workflowAnalysis : null

  useEffect(() => {
    if (currentSessionAnalysis) {
      transitionWebsiteProofProgress({ type: "workflow_report_exists" })
    }
  }, [currentSessionAnalysis?.id])

  useEffect(() => {
    const previousLifecycle = previousWorkflowProgressLifecycleRef.current
    previousWorkflowProgressLifecycleRef.current = websiteProofProgressLifecycle
    const continuingAnalysis =
      isWorkflowAnalysisLifecycle(previousLifecycle) &&
      isWorkflowAnalysisLifecycle(websiteProofProgressLifecycle)
    if (!continuingAnalysis) {
      workflowProgressLifecycleStartedAtRef.current = Date.now()
      setWorkflowProgressNowMs(Date.now())
    }
  }, [websiteProofProgressLifecycle])

  useEffect(() => {
    if (!shouldShowWorkflowAnalysisProgress({ lifecycle: websiteProofProgressLifecycle })) return
    const timer = setInterval(() => {
      const elapsedMs = Date.now() - workflowProgressLifecycleStartedAtRef.current
      setWorkflowProgressNowMs(Date.now())
      if (analyzing) {
        transitionWebsiteProofProgress({ type: "analysis_polling_result", elapsedMs })
      }
    }, 1000)
    return () => clearInterval(timer)
  }, [websiteProofProgressLifecycle, analyzing])

  const workflowAnalysisProgress = useMemo(() => {
    if (!session) return null
    if (!shouldShowWorkflowAnalysisProgress({ lifecycle: websiteProofProgressLifecycle })) return null
    return buildWorkflowAnalysisProgress({
      lifecycle: websiteProofProgressLifecycle,
      uploadError: extensionUploadState?.sessionId === session.id ? extensionUploadState.lastUploadError : null,
      analyzeError,
      activeElapsedMs: workflowProgressNowMs - workflowProgressLifecycleStartedAtRef.current,
    })
  }, [
    session?.id,
    websiteProofProgressLifecycle,
    workflowProgressNowMs,
    analyzeError,
    extensionUploadState,
  ])

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
          transitionRecorderLifecycle("ANALYSIS_COMPLETED")
          transitionRecorderLifecycle("SAVE_READY")
          setPoll(false)
          onSessionComplete?.()
        } else if (updated.status === "expired") {
          setPoll(false)
        }
      } catch { /* transient network error — next tick will retry */ }
    }, 3000)
    return () => clearTimeout(t)
  }, [pollingActive, session, onSessionComplete])

  // ── Auto-fetch workflow analysis ──────────────────────────────────────────
  // When session reaches completed, try to load any persisted result.
  // Guard: skip only if we already have an analysis for THIS specific session.
  // If workflowAnalysis belongs to a different (prior) session, proceed to fetch
  // the result for the current one.
  useEffect(() => {
    if (!session) return
    if (session.status !== "completed") return
    if (workflowAnalysis?.proof_session_id === session.id) return
    void getWorkflowAnalysis(session.id).then((r) => {
      if (r) setWorkflowAnalysis(r)
    }).catch(() => undefined)
  }, [session?.id, session?.status, workflowAnalysis?.proof_session_id])

  // ── Auto-fetch privacy scan ───────────────────────────────────────────────
  // Load the scan result once proof is uploaded (scan runs automatically on upload).
  useEffect(() => {
    if (!session) return
    if (privacyScan) return
    const uploadedOrLater: ExtensionProofSessionStatus[] = [
      "uploaded_pending_analysis", "analyzing", "completed",
    ]
    if (!uploadedOrLater.includes(session.status)) return
    void getWorkflowPrivacyScan(session.id).then((r) => {
      if (r) setPrivacyScan(r)
    }).catch(() => undefined)
  }, [session?.id, session?.status, privacyScan])

  // ── Analyze workflow ──────────────────────────────────────────────────────

  // Parse comma-separated skill names from the form field into a clean array.
  function parseSkills(): string[] {
    return form.skillName.trim()
      ? form.skillName.split(",").map(s => s.trim()).filter(Boolean)
      : []
  }

  async function handleAnalyze() {
    if (!session) return
    if (process.env.NODE_ENV === "development") {
      console.info("[WebsiteProofProgress] analysis started")
    }
    transitionWebsiteProofProgress({ type: "analyze_clicked" })
    setAnalyzing(true)
    setAnalyzeError(null)
    setAnalyzeTimedOut(false)

    let cancelled = false
    const timeoutId = setTimeout(() => {
      cancelled = true
      setAnalyzeTimedOut(true)
      setAnalyzing(false)
      setAnalyzeError("Analysis timed out after 90 seconds. Please retry.")
      transitionWebsiteProofProgress({ type: "analysis_failed" })
    }, 90_000)
    analyzeTimeoutRef.current = timeoutId

    try {
      const result = await analyzeWorkflowEvidence(session.id, {
        claimed_skills: parseSkills(),
        proof_objective: form.proofObjective.trim(),
        original_url: form.websiteUrl.trim(),
        url_type: urlType,
        github_url: form.githubUrl.trim() || null,
      })
      if (cancelled) return
      clearTimeout(timeoutId)
      analyzeTimeoutRef.current = null
      setWorkflowAnalysis(result)
      transitionWebsiteProofProgress({ type: "workflow_report_exists" })
      transitionRecorderLifecycle("ANALYSIS_COMPLETED")
      transitionRecorderLifecycle("SAVE_READY")
      setPoll(false)
      const updated = await getExtensionProofSession(session.id)
      if (!cancelled) setSession(updated)
    } catch (err) {
      if (cancelled) return
      clearTimeout(timeoutId)
      analyzeTimeoutRef.current = null
      setAnalyzeError(err instanceof Error ? err.message : "Analysis failed. Please try again.")
      transitionWebsiteProofProgress({ type: "analysis_failed" })
    } finally {
      if (!cancelled) setAnalyzing(false)
    }
  }

  // ── Create session ────────────────────────────────────────────────────────

  async function handleCreate() {
    setError(null)

    if (urlType === "invalid_url") {
      setError("Enter a valid website URL starting with http:// or https://.")
      return
    }
    if (!form.skillName.trim()) {
      setError("Enter the skill this walkthrough demonstrates.")
      return
    }
    if (form.skillName.length > SKILL_NAME_MAX) {
      setError("Skills must be 160 characters or less. Use concise comma-separated skills.")
      return
    }
    if (wordCount(form.proofObjective) < 5) {
      setError("Describe what this walkthrough proves (at least 5 words).")
      return
    }

    setCreating(true)
    transitionRecorderLifecycle("CREATE_REQUESTED")
    try {
      const evidence = await createSkillEvidence({
        skill_name:           form.skillName.trim(),
        evidence_type:        local ? "local development (extension proof)" : "private website (extension proof)",
        evidence_url:         form.websiteUrl.trim(),
        repository_url:       form.githubUrl.trim() || null,
        evidence_description: form.proofObjective.trim(),
        metadata: {
          proof_kind:         "extension_proof",
          submission_source:  "student_extension_proof_flow",
          url_type:           urlType,
        },
      })
      const intentForCreate = followupIntent
      const sess = await createExtensionProofSession(evidence.id, {
        project_id: selectedProjectId || undefined,
        ...(intentForCreate ? {
          parent_proof_session_id: intentForCreate.parentSessionId || undefined,
          followup_target_skill:   intentForCreate.skill || undefined,
          followup_objective:      intentForCreate.objective || undefined,
          proof_attempt_type:      "followup" as const,
        } : {}),
        website_url:     form.websiteUrl.trim() || undefined,
        github_url:      form.githubUrl.trim() || undefined,
        claimed_skills:  parseSkills(),
        proof_objective: form.proofObjective.trim() || undefined,
      })
      setFollowupIntent(null)
      clearFollowUpProofDraft()
      setSession(sess)
      setRecorderConfigRevision(0)
      setRecorderReady(false)
      setRecorderDiagnosticCode(null)
      transitionRecorderLifecycle("SESSION_CREATED")
      transitionWebsiteProofProgress({ type: "session_created" })
      setStep("session_active")
      saveActiveExtensionProofSession({
        sessionId: sess.id,
        form,
        configRevision: 0,
        savedAt: new Date().toISOString(),
      })
    } catch (err) {
      transitionRecorderLifecycle("RETRYABLE_FAILURE", "session_creation_failed")
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
    setRecorderReady(false)
    setRecorderDiagnosticCode(null)
    try {
      if (recorderLifecycle.state === "FAILED_RETRYABLE") {
        transitionRecorderLifecycle("RETRY_INITIALIZATION")
      } else if (recorderLifecycle.state === "NEW") {
        transitionRecorderLifecycle("RESTORE_CREATED")
      }
      transitionRecorderLifecycle("INITIALIZATION_REQUESTED")
      const nextRevision = recorderConfigRevision + 1
      setRecorderConfigRevision(nextRevision)
      saveActiveExtensionProofSession({
        sessionId: session.id,
        form,
        configRevision: nextRevision,
        savedAt: new Date().toISOString(),
      })

      const initialized = await initializeWebsiteProofRecorder({
        config_revision: nextRevision,
        session_id: session.id,
        owner_user_id: session.user_id,
        project_id: selectedProjectId || session.project_id || null,
        website_url: form.websiteUrl.trim(),
        repository_url: form.githubUrl.trim() || null,
        claimed_skills: parseSkills(),
        proof_objective: form.proofObjective.trim(),
        created_at: session.created_at,
      })
      if (!initialized.ok) {
        transitionRecorderLifecycle("RETRYABLE_FAILURE", initialized.error_code)
        setRecorderDiagnosticCode(initialized.diagnostic_code)
        setError(recorderFailureMessage(initialized))
        return
      }
      transitionRecorderLifecycle("EXTENSION_ACKNOWLEDGED")

      transitionRecorderLifecycle("TARGET_OPEN_REQUESTED")
      const targetResult = await openWebsiteProofTarget(initialized.config)
      if ("ok" in targetResult && targetResult.ok === false) {
        const targetFailure = targetResult as RecorderHandshakeFailure
        transitionRecorderLifecycle("RETRYABLE_FAILURE", targetFailure.error_code)
        setRecorderDiagnosticCode(targetFailure.diagnostic_code)
        setError(recorderFailureMessage(targetFailure))
        return
      }
      transitionRecorderLifecycle("TARGET_ACKNOWLEDGED")
      setRecorderReady(true)

      // Capture starts only after the exact target attachment ACK. The
      // extension's start ACK is also matched before the backend enters its
      // idempotent recording state.
      const recorderStarted = await startWebsiteProofRecording(initialized.config)
      if ("ok" in recorderStarted && recorderStarted.ok === false) {
        const startFailure = recorderStarted as RecorderHandshakeFailure
        transitionRecorderLifecycle("RETRYABLE_FAILURE", startFailure.error_code)
        setRecorderDiagnosticCode(startFailure.diagnostic_code)
        setError(recorderFailureMessage(startFailure))
        return
      }
      const updated = await startExtensionProofSession(session.id)
      setSession(updated)
      transitionRecorderLifecycle("RECORDING_STARTED")
      transitionWebsiteProofProgress({ type: "recording_started" })
      setPoll(true)
    } catch (err) {
      transitionRecorderLifecycle("RETRYABLE_FAILURE", "recorder_start_failed")
      setError(err instanceof Error ? err.message : "Failed to start proof session.")
    } finally {
      setStarting(false)
    }
  }

  // ── Render: owned history ────────────────────────────────────────────────

  if (historyMode) {
    const projectTitle = (projectId?: string | null) =>
      availableProjects.find((project) => project.id === projectId)?.title ??
      (projectId ? "Linked project" : "Proof Vault only")

    return (
      <div data-testid="website-proof-history" style={{ display: "grid", gap: 16 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, color: "var(--ink)" }}>Previous Website Proofs</h2>
          <p style={{ margin: "6px 0 0", fontSize: 13, color: "var(--ink-2)", lineHeight: 1.6 }}>
            Open a specific proof to review its replay, analysis, privacy result, checklist, and saved status.
          </p>
        </div>

        {historyError && (
          <div role="alert" style={{ border: "1px solid #fecaca", background: "#fef2f2", color: "#991b1b", borderRadius: 10, padding: "10px 12px", fontSize: 12 }}>
            {historyError}
          </div>
        )}

        {historySessions === null ? (
          <p style={{ fontSize: 13, color: "var(--muted)" }}>Loading previous Website Proofs…</p>
        ) : historySessions.length === 0 ? (
          <div style={{ border: "1px solid var(--line)", borderRadius: 12, padding: 16, color: "var(--ink-2)", fontSize: 13 }}>
            No Website Proof sessions yet.
          </div>
        ) : (
          <div style={{ display: "grid", gap: 10 }}>
            {historySessions.map((item) => (
              <div
                key={item.id}
                data-testid="website-proof-history-row"
                data-session-id={item.id}
                style={{ border: "1px solid var(--line)", borderRadius: 12, padding: "13px 14px", display: "grid", gap: 8 }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)", overflowWrap: "anywhere" }}>
                    {item.website_url || "Website URL unavailable"}
                  </div>
                  <StatusBadge status={item.status} />
                </div>
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 11, color: "var(--muted)" }}>
                  <span>{item.created_at ? new Date(item.created_at).toLocaleString() : "Date unavailable"}</span>
                  <span>Project: {projectTitle(item.project_id)}</span>
                  {item.finalized_at && <span style={{ color: "#166534", fontWeight: 700 }}>Saved</span>}
                </div>
                <div>
                  <a
                    href={`/student/proofs/website?session=${encodeURIComponent(item.id)}`}
                    style={{ display: "inline-flex", border: "1px solid var(--line-2)", borderRadius: 8, padding: "7px 11px", color: "var(--ink)", textDecoration: "none", fontSize: 12, fontWeight: 700 }}
                  >
                    Open proof
                  </a>
                </div>
              </div>
            ))}
          </div>
        )}

        <div>
          <a
            href="/student/proofs/website"
            style={{ display: "inline-flex", border: "1px solid var(--line-2)", borderRadius: 9, padding: "8px 13px", color: "var(--ink-2)", textDecoration: "none", fontSize: 13, fontWeight: 600 }}
          >
            ← Create a new Website Proof
          </a>
        </div>
      </div>
    )
  }

  // ── Render: form ─────────────────────────────────────────────────────────

  if (step === "form") {
    const showLocalWarning = form.websiteUrl.trim() !== "" && local

    return (
      <div data-entry-state="NEW" style={{ display: "grid", gap: 18 }}>
        {resumeCandidate && (
          <div data-testid="unfinished-website-proof" style={{ border: "1px solid #fcd34d", borderRadius: 12, background: "#fffbeb", padding: "13px 14px", display: "grid", gap: 9 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#92400e" }}>You have an unfinished Website Proof.</div>
              <p style={{ margin: "4px 0 0", fontSize: 12, color: "#78350f", lineHeight: 1.55, overflowWrap: "anywhere" }}>
                {resumeCandidate.session.website_url || resumeCandidate.draft.form.websiteUrl || "Website URL unavailable"}
              </p>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button
                type="button"
                onClick={handleResumeCandidate}
                style={{ border: "1px solid #d97706", background: "#d97706", color: "#fff", borderRadius: 8, padding: "7px 12px", fontSize: 12, fontWeight: 700, cursor: "pointer" }}
              >
                Resume
              </button>
              <button
                type="button"
                onClick={handleStartNew}
                style={{ border: "1px solid #d97706", background: "transparent", color: "#92400e", borderRadius: 8, padding: "7px 12px", fontSize: 12, fontWeight: 700, cursor: "pointer" }}
              >
                Start new proof
              </button>
            </div>
          </div>
        )}

        {/* Follow-up intent banner */}
        {followUpMode && followupIntent && (
          <div style={{ border: "1px solid #c4b5fd", borderRadius: 12, background: "#f5f3ff", padding: "12px 14px" }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: "#6d28d9", marginBottom: 4 }}>
              Follow-up Proof Recording
            </div>
            <p style={{ margin: 0, fontSize: 11, color: "#5b21b6", lineHeight: 1.55 }}>
              Recording a follow-up proof for <strong>{followupIntent.skill}</strong>.
              The form has been pre-filled with the follow-up objective.
              This proof will be linked to the original session.
            </p>
          </div>
        )}

        {/* Info banner */}
        <div style={{ border: "1px solid #bfdbfe", borderRadius: 12, background: "#eff6ff", padding: "14px 16px" }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#1e40af", marginBottom: 5 }}>Website Proof</div>
          <p style={{ margin: 0, fontSize: 12, color: "#1e40af", lineHeight: 1.65 }}>
            Record a walkthrough of your website, app, dashboard, or portfolio. VeriBridge preserves
            the recording and derives website workflow evidence from it, then attaches the completed
            proof to the project you select. Works for deployed sites, private dashboards, and local
            development servers.
          </p>
        </div>

        {/* Privacy Guard warning + acknowledgment checkbox */}
        <PrivacyWarningBox
          acknowledged={privacyAcknowledged}
          onToggle={() => setPrivacyAcknowledged((v) => !v)}
        />

        {/* Local URL warning */}
        {showLocalWarning && (
          <div
            role="note"
            style={{ border: "1px solid #fed7aa", borderRadius: 12, background: "#fff7ed", padding: "14px 16px", display: "grid", gap: 6 }}
          >
            <div style={{ fontSize: 12, fontWeight: 700, color: "#9a3412" }}>
              Local project URL detected
            </div>
            <p style={{ margin: 0, fontSize: 12, color: "#7c2d12", lineHeight: 1.65 }}>
              You are using a local project URL. Please make sure your frontend and backend are
              running before starting the proof session. VeriBridge can record your local
              workflow, but recruiters will not be able to open this localhost link later.
              Add GitHub or setup instructions, or deploy your app, for stronger evidence.
            </p>
            <div style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 2 }}>
              <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.08em", padding: "2px 8px", borderRadius: 999, background: "#fed7aa", color: "#9a3412", border: "1px solid #fdba74" }}>
                LOCAL — MEDIUM CONFIDENCE
              </span>
            </div>
          </div>
        )}

        {error && (
          <div role="alert" style={{ border: "1px solid #fecaca", background: "#fef2f2", color: "#991b1b", borderRadius: 10, padding: "8px 12px", fontSize: 12 }}>
            {error}
          </div>
        )}

        <div style={{ display: "grid", gap: 12 }}>
          {/* Explicit project relationship — canonical evidence architecture. */}
          <div style={{ display: "grid", gap: 4 }}>
            <label style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>
              Project relationship
            </label>
            <select
              data-testid="website-proof-project-select"
              value={selectedProjectId}
              onChange={(e) => setSelectedProjectId(e.target.value)}
              style={inp}
              disabled={creating}
            >
              <option value="">Proof Vault only — do not count in project reports</option>
              {availableProjects.map((project) => (
                <option key={project.id} value={project.id}>{project.title}</option>
              ))}
            </select>
            <span style={{ fontSize: 11, color: "var(--muted)" }}>
              Select the project this recording demonstrates. This explicit link is required before the proof can support that project or its skills.
            </span>
            {projectLoadError && <span role="note" style={{ fontSize: 11, color: "#92400e" }}>{projectLoadError}</span>}
          </div>

          {/* Website URL */}
          <div style={{ display: "grid", gap: 4 }}>
            <label style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>
              Website URL <span style={{ color: "#dc2626" }}>*</span>
            </label>
            <input
              value={form.websiteUrl}
              onChange={(e) => setForm((f) => ({ ...f, websiteUrl: e.target.value }))}
              placeholder="https://your-project.vercel.app or http://localhost:3000"
              style={inp}
              disabled={creating}
            />
            <span style={{ fontSize: 11, color: "var(--muted)" }}>
              Deployed site, private URL (Google login supported), or local server.
            </span>
          </div>

          {/* GitHub URL */}
          <div style={{ display: "grid", gap: 4 }}>
            <label style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>
              GitHub Repository URL{" "}
              <span style={{ fontWeight: 400, color: "var(--muted)" }}>(optional{local ? " — recommended for local projects" : ""})</span>
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
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <label style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>
                Skills this demonstrates <span style={{ color: "#dc2626" }}>*</span>
              </label>
              <span style={{
                fontSize: 11,
                fontVariantNumeric: "tabular-nums",
                color: form.skillName.length > SKILL_NAME_MAX ? "#dc2626" : "var(--muted)",
                fontWeight: form.skillName.length > SKILL_NAME_MAX ? 700 : 400,
              }}>
                {form.skillName.length}/{SKILL_NAME_MAX}
              </span>
            </div>
            <input
              value={form.skillName}
              onChange={(e) => setForm((f) => ({ ...f, skillName: e.target.value }))}
              placeholder="e.g. FastAPI, React, Machine Learning"
              style={{
                ...inp,
                borderColor: form.skillName.length > SKILL_NAME_MAX ? "#dc2626" : undefined,
              }}
              disabled={creating}
            />
            {form.skillName.length > SKILL_NAME_MAX ? (
              <span style={{ fontSize: 11, color: "#dc2626" }}>
                Skills must be 160 characters or less. Use concise comma-separated skills.
              </span>
            ) : (
              <span style={{ fontSize: 11, color: "var(--muted)" }}>Comma-separated skills you will demonstrate in this walkthrough.</span>
            )}
          </div>

          {/* Proof objective */}
          <div style={{ display: "grid", gap: 4 }}>
            <label style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>
              Proof objective — what workflow will be shown <span style={{ color: "#dc2626" }}>*</span>
            </label>
            <textarea
              value={form.proofObjective}
              onChange={(e) => setForm((f) => ({ ...f, proofObjective: e.target.value }))}
              placeholder="Describe what you'll walk through — e.g. 'Show the live ML inference dashboard processing a new prediction request and displaying the result.'"
              style={{ ...inp, minHeight: 80, resize: "vertical", fontFamily: "inherit", lineHeight: 1.5 }}
              disabled={creating}
            />
            <span style={{ fontSize: 11, color: "var(--muted)" }}>
              What feature or workflow will you demonstrate in the recording? (5 words minimum)
            </span>
          </div>
        </div>

        {/* Footer */}
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={resetAndBack}
              disabled={creating}
              style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "9px 14px", fontWeight: 600, fontSize: 13, cursor: creating ? "not-allowed" : "pointer" }}
            >
              ← Back to AI Proof Builder
            </button>
            <a
              href="/student/proofs/website?history=1"
              style={{ display: "inline-flex", alignItems: "center", border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "9px 14px", fontWeight: 600, fontSize: 13, textDecoration: "none" }}
            >
              View previous proofs
            </a>
          </div>
          <button
            type="button"
            onClick={() => void handleCreate()}
            disabled={creating || !privacyAcknowledged || form.skillName.length > SKILL_NAME_MAX}
            title={
              !privacyAcknowledged
                ? "Please acknowledge the privacy warning above first."
                : form.skillName.length > SKILL_NAME_MAX
                ? "Skills must be 160 characters or less."
                : undefined
            }
            style={{
              border: "1px solid transparent",
              background: creating || !privacyAcknowledged || form.skillName.length > SKILL_NAME_MAX ? "var(--bg-2)" : "var(--ink)",
              color: creating || !privacyAcknowledged || form.skillName.length > SKILL_NAME_MAX ? "var(--muted)" : "#fff",
              borderRadius: 10, padding: "10px 20px", fontWeight: 700, fontSize: 14,
              cursor: creating || !privacyAcknowledged || form.skillName.length > SKILL_NAME_MAX ? "not-allowed" : "pointer",
            }}
          >
            {creating ? "Creating session…" : "Start proof"}
          </button>
        </div>
      </div>
    )
  }

  // ── Render: session active ────────────────────────────────────────────────

  if (step === "session_active" && session) {
    const hasStarted = (["recording", "uploaded_pending_analysis", "analyzing", "completed"] as ExtensionProofSessionStatus[]).includes(session.status)
    const canReconnectRecorder = session.status === "recording" && !recorderReady
    const isCompleted = session.status === "completed"
    const isExpired   = session.status === "expired"
    const entryState = websiteProofEntryState(session)
    const isSaved = entryState === "SAVED" || saveState === "saved" || saveState === "already_saved"
    const savedProjectId = saveResult?.project_id || session.finalized_project_id || session.project_id || selectedProjectId
    const savedProjectTitle =
      saveResult?.project_relationship.project_title ||
      availableProjects.find((project) => project.id === savedProjectId)?.title ||
      "Selected project"
    const workflowProgressOverridesRecordingUi = doesWorkflowProgressOverrideRecordingUi(websiteProofProgressLifecycle)

    const sectionTitle = local ? "Local Workflow Evidence" : "Website Workflow Evidence"
    const sectionSubtitle = local
      ? "A recorded walkthrough of your locally running project. The recording and the evidence derived from it show the app working in your development environment."
      : "A recorded walkthrough of the submitted website or application. The recording is preserved and the website workflow evidence below is derived from it."
    const cardTitle = local ? "Local Workflow Evidence Session" : "Website Workflow Evidence Session"

    const sessionDetails: Array<[string, string, boolean]> = [
      ["Session ID", session.id.slice(0, 18) + "…", true],
      ["Website",    form.websiteUrl, false],
      ...(form.githubUrl ? [["GitHub", form.githubUrl, false] as [string, string, boolean]] : []),
      ["Skill",      form.skillName, false],
      ...(session.created_at
        ? [["Recorded", new Date(session.created_at).toLocaleString(), false] as [string, string, boolean]]
        : []),
    ]

    return (
      <div data-entry-state={entryState} style={{ display: "grid", gap: 18 }}>
        {/* Section title */}
        <div style={{ display: "grid", gap: 4 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "var(--ink)" }}>
              {sectionTitle}
            </h3>
            {local && (
              <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.08em", padding: "2px 8px", borderRadius: 999, background: "#fed7aa", color: "#9a3412", border: "1px solid #fdba74" }}>
                LOCAL
              </span>
            )}
          </div>
          <p style={{ margin: 0, fontSize: 12, color: "var(--ink-2)", lineHeight: 1.6 }}>
            {sectionSubtitle}
          </p>
        </div>

        {/* Session card */}
        <div style={{ border: "1px solid var(--line)", borderRadius: 14, background: "var(--bg-2)", padding: "16px 18px", display: "grid", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>{cardTitle}</span>
            <StatusBadge status={session.status} />
          </div>
          <div style={{ display: "grid", gap: 5 }}>
            {sessionDetails.map(([label, value, mono]) => (
              <div key={label} style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                <span style={{ fontSize: 11, color: "var(--muted)", minWidth: 70, flexShrink: 0 }}>{label}</span>
                <span style={{ fontSize: 12, color: "var(--ink)", fontFamily: mono ? "monospace" : "inherit", wordBreak: "break-all" }}>
                  {value}
                </span>
              </div>
            ))}
            <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
              <span style={{ fontSize: 11, color: "var(--muted)", minWidth: 70, flexShrink: 0 }}>Recorder</span>
              <span style={{ fontSize: 12, color: recorderReady ? "#166534" : "var(--ink)", fontWeight: recorderReady ? 700 : 500 }}>
                {recorderReady ? "Recorder ready" : recorderLifecycle.state.replaceAll("_", " ")}
              </span>
            </div>
          </div>
        </div>

        {/* Session stepper */}
        <SessionStepper status={session.status} />

        {recorderReady && (
          <div data-testid="website-proof-recorder-ready" role="status" style={{ border: "1px solid #86efac", background: "#f0fdf4", color: "#166534", borderRadius: 10, padding: "9px 12px", fontSize: 12, fontWeight: 700 }}>
            Recorder ready — the target tab is attached to this session and you can begin recording.
          </div>
        )}

        {/* Live Proof Coach removed — live feedback runs locally in extension only */}

        {/* Workflow evidence checklist — website-evidence steps only */}
        <EvidenceChecklist
          status={session.status}
          urlType={urlType}
          analysis={currentSessionAnalysis}
        />

        {workflowAnalysisProgress && (
          <WorkflowAnalysisProgressCard
            model={workflowAnalysisProgress}
            onRetry={websiteProofProgressLifecycle === "analysis_failed" ? () => void handleAnalyze() : undefined}
          />
        )}

        {process.env.NODE_ENV === "development" && (
          <div
            data-testid="website-proof-progress-debug"
            style={{
              border: "1px dashed #cbd5e1",
              borderRadius: 8,
              background: "#f8fafc",
              color: "#475569",
              padding: "6px 10px",
              fontSize: 10,
              fontFamily: "monospace",
            }}
          >
            Recorder lifecycle: {recorderLifecycle.state}; Recorder event: {recorderLifecycle.last_event}; Revision: {recorderConfigRevision}; Diagnostic: {recorderDiagnosticCode ?? "none"}; Progress lifecycle: {websiteProofProgressLifecycle}; Last event: {websiteProofProgressLastEvent}
          </div>
        )}

        {/* Privacy scan badge — shown once proof is uploaded */}
        {privacyScan && (
          <PrivacyScanBadge
            scan={privacyScan}
            onReRecord={resetAndBack}
          />
        )}

        {error && (
          <div role="alert" style={{ border: "1px solid #fecaca", background: "#fef2f2", color: "#991b1b", borderRadius: 10, padding: "8px 12px", fontSize: 12 }}>
            {error}
          </div>
        )}

        {/* Status-aware message card */}
        {!isExpired && !workflowProgressOverridesRecordingUi && (
          <StatusMessage
            status={session.status}
            pollingActive={pollingActive}
            session={session}
            urlType={urlType}
          />
        )}

        {/* Recorded proof video — the primary artifact of a Website Proof. */}
        <WebsiteProofRecordingSection
          sessionId={session.id}
          sessionStatus={session.status}
        />


        {/* Analyze button — shown when uploaded and not yet analyzing */}
        {session.status === "uploaded_pending_analysis" && !currentSessionAnalysis && !analyzing && (
          <div style={{ border: "1px solid #bfdbfe", borderRadius: 12, background: "#eff6ff", padding: "14px 16px", display: "grid", gap: 10 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#1e40af" }}>Ready to analyze your workflow</div>
              <p style={{ margin: "4px 0 0", fontSize: 12, color: "#1e3a8a", lineHeight: 1.65 }}>
                VeriBridge will analyze your recorded walkthrough to identify which claimed skills
                were demonstrated in the recording, what interactions were observed, and what
                evidence is still missing. Only this session&apos;s recording is analyzed.
              </p>
            </div>
            <div>
              <button
                type="button"
                onClick={() => void handleAnalyze()}
                style={{
                  border: "1px solid transparent",
                  background: "#1d4ed8",
                  color: "#fff",
                  borderRadius: 10, padding: "10px 20px",
                  fontWeight: 700, fontSize: 14,
                  cursor: "pointer",
                }}
              >
                Analyze Workflow Evidence
              </button>
            </div>
          </div>
        )}

        {/* Workflow analysis result card */}
        {currentSessionAnalysis && <WorkflowAnalysisCard analysis={currentSessionAnalysis} finalEvaluation={null} />}

        {/* Dev-only: session ID linkage debug info */}
        {process.env.NODE_ENV === "development" && (
          <div style={{ fontSize: 10, fontFamily: "monospace", background: "#f8f9fa", border: "1px solid #dee2e6", borderRadius: 6, padding: "6px 10px", color: "#6c757d", display: "grid", gap: 2 }}>
            <span>🔬 DEV: session.id = {session.id}</span>
            <span>🔬 DEV: analysis.proof_session_id = {workflowAnalysis?.proof_session_id ?? "—"}</span>
            {workflowAnalysis && workflowAnalysis.proof_session_id !== session.id && (
              <span style={{ color: "#dc3545", fontWeight: 700 }}>⚠ SESSION MISMATCH — analysis is from a different session and is hidden</span>
            )}
            {!workflowAnalysis && <span style={{ color: "#6c757d" }}>no analysis loaded</span>}
          </div>
        )}

        {/* Legacy multi-source sections (GitHub Evidence Analysis, Live Website
            Check, Project Defense, Document evidence, Final Evidence Score,
            grouped skill profile, recommendations, verification review) are
            intentionally NOT rendered here. Website Proof is a single focused
            proof type — cross-proof aggregation happens in the Work Passport /
            Project Report / Skill Report synthesis layer. Their independent
            proof pipelines remain available at their own routes. */}

        {/* Expired */}
        {isExpired && (
          <div style={{ border: "1px solid #fecaca", background: "#fef2f2", borderRadius: 12, padding: "14px 16px" }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#991b1b" }}>Session expired</div>
            <p style={{ margin: "4px 0 0", fontSize: 12, color: "#7f1d1d", lineHeight: 1.5 }}>
              Sessions expire after 15 minutes. Click Back to start a new session.
            </p>
          </div>
        )}

        {/* Actions */}
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          {!isCompleted && (
            <button
              type="button"
              onClick={resetAndBack}
              style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "9px 14px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}
            >
              ← Back
            </button>
          )}

          {(!hasStarted || recorderLifecycle.state === "FAILED_RETRYABLE" || canReconnectRecorder) && !isExpired && (
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {recorderLifecycle.state === "FAILED_RETRYABLE" && (
                <button
                  type="button"
                  onClick={handleStartNew}
                  disabled={starting}
                  style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "10px 16px", fontWeight: 600, fontSize: 13, cursor: starting ? "not-allowed" : "pointer" }}
                >
                  Start a new session
                </button>
              )}
              <button
                type="button"
                onClick={() => void handleStart()}
                disabled={starting}
                style={{ border: "1px solid transparent", background: starting ? "var(--bg-2)" : "#065f46", color: starting ? "var(--muted)" : "#fff", borderRadius: 10, padding: "10px 20px", fontWeight: 700, fontSize: 14, cursor: starting ? "not-allowed" : "pointer" }}
              >
                {starting
                  ? "Initializing recorder…"
                  : recorderLifecycle.state === "FAILED_RETRYABLE"
                    ? "Retry recorder initialization"
                    : canReconnectRecorder
                      ? "Reconnect recorder"
                      : "▶  Start Proof Demo"}
              </button>
            </div>
          )}

          {isExpired && (
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button
                type="button"
                onClick={handleStartNew}
                style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "10px 20px", fontWeight: 600, fontSize: 14, cursor: "pointer" }}
              >
                Start new Website Proof
              </button>
              <a
                href="/student/proofs/website?history=1"
                style={{ display: "inline-flex", alignItems: "center", border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "10px 20px", fontWeight: 600, fontSize: 14, textDecoration: "none" }}
              >
                View previous proofs
              </a>
            </div>
          )}
        </div>

        {isCompleted && (
          <div style={{ border: "1px solid var(--line)", borderRadius: 12, background: "var(--bg-2)", padding: "14px 16px", display: "grid", gap: 10 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--ink)" }}>What&apos;s next?</div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button
                type="button"
                onClick={handleStartNew}
                style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "9px 16px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}
              >
                Start a new Website Proof
              </button>
              <button
                type="button"
                onClick={resetAndBack}
                style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "9px 16px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}
              >
                Return to Proof Studio
              </button>
              <a
                href="/student/proofs/website?history=1"
                style={{ display: "inline-flex", alignItems: "center", border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "9px 16px", fontWeight: 600, fontSize: 13, textDecoration: "none" }}
              >
                View previous proofs
              </a>
            </div>
          </div>
        )}

        {/* Canonical finalization is intentionally the final result panel. */}
        {isCompleted && (
          <div data-testid="website-proof-finalization" style={{ border: `1px solid ${isSaved ? "#86efac" : "var(--line)"}`, borderRadius: 14, background: isSaved ? "#f0fdf4" : "var(--paper)", padding: "18px", display: "grid", gap: 12 }}>
            <div>
              <div style={{ fontSize: 16, fontWeight: 800, color: isSaved ? "#166534" : "var(--ink)" }}>
                {isSaved ? "Saved" : "Save this proof"}
              </div>
              <p style={{ margin: "5px 0 0", fontSize: 12, color: isSaved ? "#166534" : "var(--ink-2)", lineHeight: 1.6 }}>
                Attach this completed Website Proof to a project so it appears in your Work Passport and reports.
              </p>
            </div>

            {!isSaved && (
              <div style={{ display: "grid", gap: 5 }}>
                <label htmlFor="website-proof-save-project" style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-2)" }}>
                  Project
                </label>
                <select
                  id="website-proof-save-project"
                  data-testid="website-proof-save-project-select"
                  value={selectedProjectId}
                  onChange={(event) => {
                    setSelectedProjectId(event.target.value)
                    setSaveError(null)
                    if (saveState === "error") setSaveState("not_saved")
                  }}
                  disabled={saveState === "saving"}
                  style={inp}
                >
                  <option value="">Select a project</option>
                  {availableProjects.map((project) => (
                    <option key={project.id} value={project.id}>{project.title}</option>
                  ))}
                </select>
              </div>
            )}

            {saveError && (
              <div data-testid="website-proof-save-error" role="alert" style={{ border: "1px solid #fecaca", borderRadius: 9, background: "#fef2f2", color: "#991b1b", padding: "8px 10px", fontSize: 12 }}>
                {saveError}
              </div>
            )}

            {!isSaved && (
              <div>
                <button
                  type="button"
                  onClick={() => void handleSaveProof()}
                  disabled={saveState === "saving"}
                  style={{ border: "1px solid var(--ink)", background: saveState === "saving" ? "var(--bg-2)" : "var(--ink)", color: saveState === "saving" ? "var(--muted)" : "#fff", borderRadius: 10, padding: "10px 18px", fontWeight: 800, fontSize: 14, cursor: saveState === "saving" ? "not-allowed" : "pointer" }}
                >
                  {saveState === "saving" ? "Saving…" : "Save this proof"}
                </button>
              </div>
            )}

            {isSaved && savedProjectId && (
              <div style={{ display: "grid", gap: 10 }}>
                <div data-testid="website-proof-saved-project" style={{ fontSize: 13, fontWeight: 700, color: "#166534" }}>
                  Saved to project: {savedProjectTitle}
                </div>
                {saveState === "already_saved" && (
                  <div style={{ fontSize: 11, color: "#166534" }}>Already saved — no duplicate evidence was created.</div>
                )}
                <div>
                  <button
                    type="button"
                    data-testid="website-proof-reconcile-save"
                    onClick={() => void handleSaveProof()}
                    disabled={saveState === "saving"}
                    style={{ border: "1px solid #86efac", background: "#fff", color: "#166534", borderRadius: 9, padding: "8px 12px", fontWeight: 700, fontSize: 12, cursor: saveState === "saving" ? "not-allowed" : "pointer" }}
                  >
                    {saveState === "saving" ? "Verifying saved evidence…" : "Verify saved evidence"}
                  </button>
                </div>
                <div style={{ display: "flex", gap: 9, flexWrap: "wrap" }}>
                  <a href="/student/vbr/passport" style={{ color: "#166534", fontSize: 12, fontWeight: 700 }}>View in Passport</a>
                  <a href={`/student/vbr/projects/${encodeURIComponent(savedProjectId)}/report`} style={{ color: "#166534", fontSize: 12, fontWeight: 700 }}>View Project Report</a>
                  <a href="/student/vbr/passport/vault" style={{ color: "#166534", fontSize: 12, fontWeight: 700 }}>View Proof Vault</a>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  return null
}
