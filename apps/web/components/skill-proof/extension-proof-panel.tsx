"use client"

import React, { useEffect, useMemo, useRef, useState } from "react"
import type { CSSProperties } from "react"
import {
  createExtensionProofSession,
  createSkillEvidence,
  getExtensionProofSession,
  getLiveWebsiteCheck,
  runLiveWebsiteCheck,
  startExtensionProofSession,
  analyzeWorkflowEvidence,
  getWorkflowAnalysis,
  analyzeExtensionProofGitHub,
  getExtensionProofGitHubAnalysis,
  getWorkflowPrivacyScan,
  type ExtensionProofSessionResponse,
  type ExtensionProofSessionStatus,
  type LiveWebsiteCheckConfidence,
  type LiveWebsiteCheckResponse,
  type WorkflowAnalysisResponse,
  type WorkflowConfidence,
  type ExtensionProofGitHubAnalysisResponse,
  type WorkflowPrivacyScanResponse,
  type WorkflowPrivacyScanStatus,
  type ReadinessLevel,
} from "@/lib/api"

// ── Types ─────────────────────────────────────────────────────────────────────

type PanelStep = "form" | "session_active"

type FormState = {
  websiteUrl: string
  githubUrl: string
  skillName: string
  proofObjective: string
}

type UrlType =
  | "live_deployed_url"
  | "localhost_url"
  | "local_network_url"
  | "invalid_url"

// ── URL classification ────────────────────────────────────────────────────────

function classifyUrl(raw: string): UrlType {
  const t = raw.trim()
  if (!t.startsWith("http://") && !t.startsWith("https://")) return "invalid_url"
  try {
    const { hostname } = new URL(t)
    if (hostname === "localhost" || hostname === "127.0.0.1") return "localhost_url"
    if (/^10\./.test(hostname)) return "local_network_url"
    if (/^192\.168\./.test(hostname)) return "local_network_url"
    if (/^172\.(1[6-9]|2\d|3[01])\./.test(hostname)) return "local_network_url"
    return "live_deployed_url"
  } catch {
    return "invalid_url"
  }
}

function isLocal(t: UrlType): boolean {
  return t === "localhost_url" || t === "local_network_url"
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

const ANALYSIS_STAGES: Array<{ key: string; label: string; comingSoon?: boolean }> = [
  { key: "loading_metadata",   label: "Loading session metadata" },
  { key: "reading_timeline",   label: "Reading workflow timeline" },
  { key: "matching_objective", label: "Matching proof objective" },
  { key: "matching_skills",    label: "Matching claimed skills" },
  { key: "generating_summary", label: "Generating evidence summary" },
  { key: "db_insert",          label: "Saving results" },
  { key: "video_to_text",      label: "Video to text analysis", comingSoon: true },
  { key: "github_analysis",    label: "GitHub code analysis",   comingSoon: true },
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
  { label: "Final Verification",    statuses: ["completed"] },
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

// ── Evidence checklist ────────────────────────────────────────────────────────

type EvidenceItemStatus = "complete" | "uploading" | "pending" | "failed" | "unavailable"

function evidenceItemStyle(s: EvidenceItemStatus): CSSProperties {
  if (s === "complete")    return { color: "#065f46", background: "#f0fdf4", border: "1px solid #d1fae5" }
  if (s === "uploading")   return { color: "#1d4ed8", background: "#eff6ff", border: "1px solid #bfdbfe" }
  if (s === "failed")      return { color: "#991b1b", background: "#fef2f2", border: "1px solid #fecaca" }
  if (s === "unavailable") return { color: "#94a3b8", background: "#f8fafc", border: "1px solid #e2e8f0" }
  return { color: "#64748b", background: "#f8fafc", border: "1px solid #e2e8f0" }
}

function evidenceIcon(s: EvidenceItemStatus): string {
  if (s === "complete")    return "✓"
  if (s === "uploading")   return "↑"
  if (s === "failed")      return "✗"
  if (s === "unavailable") return "—"
  return "○"
}

function evidenceLabel(s: EvidenceItemStatus): string {
  if (s === "complete")    return "Complete"
  if (s === "uploading")   return "Uploading"
  if (s === "failed")      return "Failed"
  if (s === "unavailable") return "Not Available"
  return "Pending"
}

function workflowEvidenceStatus(status: ExtensionProofSessionStatus): EvidenceItemStatus {
  if (status === "expired") return "failed"
  if (["uploaded_pending_analysis", "analyzing", "completed"].includes(status)) return "complete"
  return "pending"
}

function workflowAnalysisStatus(
  sessionStatus: ExtensionProofSessionStatus,
  analysis: WorkflowAnalysisResponse | null,
): EvidenceItemStatus {
  if (analysis) return "complete"
  if (sessionStatus === "analyzing") return "uploading"
  return "pending"
}

function liveCheckStatus(
  urlType: UrlType,
  liveCheck: LiveWebsiteCheckResponse | null,
  liveChecking: boolean,
): EvidenceItemStatus {
  if (isLocal(urlType)) return "unavailable"
  if (liveChecking) return "uploading"
  if (!liveCheck) return "pending"
  if (liveCheck.is_reachable) return "complete"
  return "failed"
}

function githubEvidenceStatus(
  hasGithubUrl: boolean,
  githubAnalysis: ExtensionProofGitHubAnalysisResponse | null,
  githubAnalyzing: boolean,
): EvidenceItemStatus {
  if (!hasGithubUrl) return "pending"
  if (githubAnalyzing) return "uploading"
  if (!githubAnalysis) return "pending"
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
      // Status is always "pending" — the label override below handles "Ready for Review".
      // This feature NEVER marks Final Verification as "complete".
      getStatus: () => "pending",
    },
  ]
}

function evidenceLabelOverride(key: string, s: EvidenceItemStatus, finalVerificationReady = false): string {
  if (key === "workflow_analysis" && s === "complete") return "AI Reviewed"
  if (key === "workflow_analysis" && s === "uploading") return "In Progress"
  if (key === "github" && s === "complete") return "AI Reviewed"
  if (key === "github" && s === "uploading") return "Analyzing…"
  if (key === "live_check" && s === "uploading") return "Checking…"
  // Final Verification: show "Ready for Review" when readiness >= 80 and privacy clean.
  // NEVER show "Complete" — that requires a separate VeriBridge reviewer step.
  if (key === "final" && s === "pending" && finalVerificationReady) return "Ready for Review"
  return evidenceLabel(s)
}

function evidenceFinalStyle(key: string, s: EvidenceItemStatus, finalVerificationReady: boolean): CSSProperties {
  if (key === "final" && s === "pending" && finalVerificationReady) {
    // "Ready for Review" — blue tint, distinct from "pending" (gray) and "complete" (green)
    return { color: "#1d4ed8", background: "#eff6ff", border: "1px solid #bfdbfe" }
  }
  return evidenceItemStyle(s)
}

function evidenceFinalIcon(key: string, s: EvidenceItemStatus, finalVerificationReady: boolean): string {
  if (key === "final" && s === "pending" && finalVerificationReady) return "→"
  return evidenceIcon(s)
}

function EvidenceChecklist({
  status,
  urlType,
  analysis,
  liveCheck,
  liveChecking,
  hasGithubUrl,
  githubAnalysis,
  githubAnalyzing,
  finalVerificationReady = false,
}: {
  status: ExtensionProofSessionStatus
  urlType: UrlType
  analysis: WorkflowAnalysisResponse | null
  liveCheck: LiveWebsiteCheckResponse | null
  liveChecking: boolean
  hasGithubUrl: boolean
  githubAnalysis: ExtensionProofGitHubAnalysisResponse | null
  githubAnalyzing: boolean
  /** When true, "Final Verification" shows as "Ready for Review" (blue).
   *  This is set when readiness score >= 80 and privacy scan is not flagged.
   *  It does NOT mark Final Verification as complete — that requires a
   *  separate VeriBridge reviewer step. */
  finalVerificationReady?: boolean
}) {
  const items = buildEvidenceItems(urlType, analysis, liveCheck, liveChecking, hasGithubUrl, githubAnalysis, githubAnalyzing)
  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: 12, overflow: "hidden" }}>
      <div style={{ background: "var(--bg-2)", borderBottom: "1px solid var(--line)", padding: "9px 14px" }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: "var(--ink-2)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
          Verification Checklist
        </span>
      </div>
      <div style={{ padding: "10px 14px", display: "grid", gap: 7 }}>
        {items.map((item) => {
          const s = item.getStatus(status)
          const isFinalReady = item.key === "final" && s === "pending" && finalVerificationReady
          const style = evidenceFinalStyle(item.key, s, finalVerificationReady)
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
                  {evidenceFinalIcon(item.key, s, finalVerificationReady)}
                </span>
                <span style={{ fontSize: 12, fontWeight: (s === "complete" || isFinalReady) ? 600 : 400 }}>
                  {item.label}
                </span>
              </div>
              <span style={{ fontSize: 11, fontWeight: 600 }}>
                {evidenceLabelOverride(item.key, s, finalVerificationReady)}
              </span>
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
      ? "Local workflow proof uploaded. This demonstrates the project running in the student's local environment. Recruiters cannot directly open the localhost URL, so GitHub evidence, setup instructions, or deployment are recommended for stronger verification."
      : "Workflow proof uploaded. GitHub analysis and final verification are still pending."

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

// ── Workflow Analysis In-Progress ─────────────────────────────────────────────

function WorkflowAnalysisInProgress({
  simProgress,
  simStageIdx,
}: {
  simProgress: number
  simStageIdx: number
}) {
  return (
    <div style={{ border: "1px solid #ddd6fe", borderRadius: 12, background: "#faf5ff", padding: "14px 16px", display: "grid", gap: 12 }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#5b21b6" }}>Analyzing workflow evidence…</div>
        <p style={{ margin: "4px 0 0", fontSize: 12, color: "#4c1d95", lineHeight: 1.65 }}>
          VeriBridge is reviewing your recorded workflow. This usually takes 10–30 seconds.
        </p>
      </div>

      {/* Progress bar */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
          <span style={{ fontSize: 11, color: "#7c3aed" }}>Analysis in progress</span>
          <span style={{ fontSize: 11, fontWeight: 700, color: "#5b21b6" }}>{simProgress}%</span>
        </div>
        <div style={{ height: 6, background: "#ede9fe", borderRadius: 999 }}>
          <div
            style={{
              height: 6, borderRadius: 999, background: "#7c3aed",
              width: `${simProgress}%`, transition: "width 0.5s ease",
            }}
          />
        </div>
      </div>

      {/* Stage checklist */}
      <div style={{ display: "grid", gap: 6 }}>
        {ANALYSIS_STAGES.map((stage, i) => {
          if (stage.comingSoon) {
            return (
              <div key={stage.key} style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <span style={{ fontSize: 12, color: "#cbd5e1", width: 14, flexShrink: 0, textAlign: "center" }}>—</span>
                <span style={{ fontSize: 12, color: "#94a3b8" }}>{stage.label}</span>
                <span style={{ fontSize: 10, color: "#94a3b8", marginLeft: "auto" }}>Coming soon</span>
              </div>
            )
          }
          const isDone = i <= simStageIdx
          const isCurrent = i === simStageIdx + 1
          return (
            <div key={stage.key} style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: isDone ? "#065f46" : isCurrent ? "#5b21b6" : "#94a3b8", width: 14, flexShrink: 0, textAlign: "center" }}>
                {isDone ? "✓" : isCurrent ? "…" : "○"}
              </span>
              <span style={{ fontSize: 12, color: isDone ? "#064e3b" : isCurrent ? "#4c1d95" : "#94a3b8" }}>
                {stage.label}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Live Website Check components ────────────────────────────────────────────

function LiveWebsiteCheckInProgress({
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

const LIVE_CHECK_CONFIDENCE: Record<
  LiveWebsiteCheckConfidence,
  { bg: string; color: string; border: string; label: string }
> = {
  high:   { bg: "#dcfce7", color: "#166534", border: "#bbf7d0", label: "HIGH" },
  medium: { bg: "#fef9c3", color: "#854d0e", border: "#fef08a", label: "MEDIUM" },
  low:    { bg: "#fef9c3", color: "#854d0e", border: "#fef08a", label: "LOW" },
  failed: { bg: "#fef2f2", color: "#991b1b", border: "#fecaca", label: "FAILED" },
}

function LiveWebsiteCheckCard({
  check,
  onRetry,
}: {
  check: LiveWebsiteCheckResponse
  onRetry: () => void
}) {
  const conf = LIVE_CHECK_CONFIDENCE[check.confidence] ?? LIVE_CHECK_CONFIDENCE.failed
  const success = check.is_reachable

  return (
    <div style={{ border: `1px solid ${success ? "#bbf7d0" : "#fecaca"}`, borderRadius: 14, overflow: "hidden" }}>
      {/* Header */}
      <div style={{
        background: success ? "#f0fdf4" : "#fef2f2",
        borderBottom: `1px solid ${success ? "#d1fae5" : "#fecaca"}`,
        padding: "12px 16px",
        display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap",
      }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: success ? "#065f46" : "#991b1b" }}>
            Live Website Check — {success ? "Complete" : "Failed"}
          </div>
          <div style={{ fontSize: 11, color: success ? "#16a34a" : "#dc2626", marginTop: 2 }}>
            {success ? "Site is publicly reachable" : "Could not confirm public accessibility"}
          </div>
        </div>
        <span style={{
          fontSize: 10, fontWeight: 700, letterSpacing: "0.08em",
          padding: "3px 9px", borderRadius: 999,
          background: conf.bg, color: conf.color, border: `1px solid ${conf.border}`,
        }}>
          {conf.label} CONFIDENCE
        </span>
      </div>

      <div style={{ padding: "14px 16px", display: "grid", gap: 12 }}>
        {/* Recruiter summary */}
        <div style={{
          background: success ? "#f0fdf4" : "#fef2f2",
          border: `1px solid ${success ? "#bbf7d0" : "#fecaca"}`,
          borderRadius: 10, padding: "10px 12px",
        }}>
          <p style={{ margin: 0, fontSize: 12, color: success ? "#064e3b" : "#991b1b", lineHeight: 1.7, fontStyle: "italic" }}>
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
        {!success && (
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

function WorkflowAnalysisCard({ analysis }: { analysis: WorkflowAnalysisResponse }) {
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
          {/* Evidence strength score */}
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <span style={{ fontSize: 11, color: "#3b82f6" }}>Evidence Strength</span>
            <span style={{ fontSize: 14, fontWeight: 800, color: "#1e40af" }}>
              {analysis.evidence_strength_score}<span style={{ fontSize: 10, fontWeight: 500 }}>/100</span>
            </span>
          </div>
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
        {/* Summary */}
        <AnalysisSection title="Summary">
          <p style={{ margin: 0, fontSize: 12, color: "var(--ink-2)", lineHeight: 1.7 }}>
            {analysis.workflow_summary}
          </p>
        </AnalysisSection>

        {/* Skills */}
        <AnalysisSection title="Skills Assessment">
          <div style={{ display: "grid", gap: 8 }}>
            {(analysis.supported_skills.length > 0 || analysis.weakly_supported_skills.length > 0 || analysis.unsupported_skills.length > 0) ? (
              <>
                {analysis.supported_skills.length > 0 && (
                  <div>
                    <div style={{ fontSize: 11, color: "#065f46", fontWeight: 600, marginBottom: 4 }}>Evidence supports</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                      {analysis.supported_skills.map((s) => <SkillPill key={s} label={s} variant="supported" />)}
                    </div>
                  </div>
                )}
                {analysis.weakly_supported_skills.length > 0 && (
                  <div>
                    <div style={{ fontSize: 11, color: "#854d0e", fontWeight: 600, marginBottom: 4 }}>Partially supported</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                      {analysis.weakly_supported_skills.map((s) => <SkillPill key={s} label={s} variant="weak" />)}
                    </div>
                  </div>
                )}
                {analysis.unsupported_skills.length > 0 && (
                  <div>
                    <div style={{ fontSize: 11, color: "#991b1b", fontWeight: 600, marginBottom: 4 }}>No observable evidence</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                      {analysis.unsupported_skills.map((s) => <SkillPill key={s} label={s} variant="unsupported" />)}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <span style={{ fontSize: 12, color: "var(--muted)" }}>No skills were claimed for this session</span>
            )}
          </div>
        </AnalysisSection>

        {/* Demonstrated actions */}
        {analysis.demonstrated_actions.length > 0 && (
          <AnalysisSection title="Demonstrated Workflow">
            <BulletList items={analysis.demonstrated_actions} />
          </AnalysisSection>
        )}

        {/* Recruiter summary */}
        <AnalysisSection title="Recruiter Summary">
          <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 10, padding: "10px 12px" }}>
            <p style={{ margin: 0, fontSize: 12, color: "var(--ink-2)", lineHeight: 1.7, fontStyle: "italic" }}>
              {analysis.recruiter_summary}
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

        {/* Improvement suggestions */}
        {analysis.student_improvement_suggestions.length > 0 && (
          <AnalysisSection title="Suggestions to Strengthen Your Proof">
            <BulletList items={analysis.student_improvement_suggestions} color="#1e40af" />
          </AnalysisSection>
        )}

        {/* Human review needed */}
        {analysis.human_review_needed && (
          <div style={{ background: "#fff7ed", border: "1px solid #fed7aa", borderRadius: 8, padding: "8px 12px", fontSize: 11, color: "#9a3412" }}>
            Human review recommended — confidence is low. A VeriBridge reviewer may follow up.
          </div>
        )}

        {/* Footer note */}
        <div style={{ borderTop: "1px solid var(--line)", paddingTop: 10 }}>
          <p style={{ margin: 0, fontSize: 11, color: "var(--muted)", lineHeight: 1.5 }}>
            This is a Workflow Timeline Analysis based on recorded browser events. Visual video
            analysis is not yet available. Final verification remains pending until GitHub
            evidence, live website check (if applicable), and all other evidence steps are complete.
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

function GitHubAnalysisInProgress({
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

function GitHubAnalysisCard({
  analysis,
  onRerun,
}: {
  analysis: ExtensionProofGitHubAnalysisResponse
  onRerun: () => void
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

        {/* Skill matching */}
        {(analysis.matched_claimed_skills.length > 0 || (analysis.weakly_matched_claimed_skills ?? []).length > 0 || analysis.missing_claimed_skills.length > 0) && (
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--ink-2)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
              Skills Assessment
            </div>
            <div style={{ display: "grid", gap: 8 }}>
              {analysis.matched_claimed_skills.length > 0 && (
                <div>
                  <div style={{ fontSize: 11, color: "#065f46", fontWeight: 600, marginBottom: 4 }}>Evidence supports</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                    {analysis.matched_claimed_skills.map((s) => (
                      <span key={s} style={{
                        fontSize: 11, fontWeight: 600, padding: "3px 8px", borderRadius: 999,
                        background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0",
                      }}>{s}</span>
                    ))}
                  </div>
                </div>
              )}
              {(analysis.weakly_matched_claimed_skills ?? []).length > 0 && (
                <div>
                  <div style={{ fontSize: 11, color: "#854d0e", fontWeight: 600, marginBottom: 4 }}>Partial / contextual evidence</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                    {(analysis.weakly_matched_claimed_skills ?? []).map((s) => (
                      <span key={s} style={{
                        fontSize: 11, fontWeight: 600, padding: "3px 8px", borderRadius: 999,
                        background: "#fefce8", color: "#854d0e", border: "1px solid #fef08a",
                      }}>{s}</span>
                    ))}
                  </div>
                </div>
              )}
              {analysis.missing_claimed_skills.length > 0 && (
                <div>
                  <div style={{ fontSize: 11, color: "#991b1b", fontWeight: 600, marginBottom: 4 }}>No evidence found for</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                    {analysis.missing_claimed_skills.map((s) => (
                      <span key={s} style={{
                        fontSize: 11, fontWeight: 600, padding: "3px 8px", borderRadius: 999,
                        background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca",
                      }}>{s}</span>
                    ))}
                  </div>
                </div>
              )}
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
}

function computeReadinessReport({
  sessionStatus,
  urlType,
  claimedSkills,
  workflowAnalysis,
  liveCheck,
  githubAnalysis,
  privacyScan,
}: {
  sessionStatus: ExtensionProofSessionStatus
  urlType: UrlType
  claimedSkills: string[]
  workflowAnalysis: WorkflowAnalysisResponse | null
  liveCheck: LiveWebsiteCheckResponse | null
  githubAnalysis: ExtensionProofGitHubAnalysisResponse | null
  privacyScan: WorkflowPrivacyScanResponse | null
}): ReadinessReport {
  const isLocal = isLocal_(urlType)
  const sessionUploaded = (["uploaded_pending_analysis", "analyzing", "completed"] as ExtensionProofSessionStatus[]).includes(sessionStatus)

  let score = 0
  const riskFlags: string[] = []
  const needsMoreEvidence: string[] = []
  const nextActions: string[] = []

  // +15 workflow evidence uploaded
  if (sessionUploaded) score += 15

  // +15 workflow analysis complete
  const hasWf = workflowAnalysis !== null
  if (hasWf) score += 15

  // +15 GitHub evidence AI reviewed
  const githubProvided = githubAnalysis !== null
  const githubOk = githubProvided && githubAnalysis!.status === "success"
  if (githubOk) {
    score += 15
  } else if (githubProvided && !githubOk) {
    riskFlags.push("GitHub repository could not be accessed or is private")
  }

  // +15 live website check (deployed only)
  const liveOk = !isLocal && liveCheck !== null && liveCheck.is_reachable
  if (liveOk) {
    score += 15
  } else if (!isLocal && liveCheck !== null && !liveCheck.is_reachable) {
    riskFlags.push("Deployed website is not publicly accessible")
  }

  // +10 privacy scan safe
  const privacyStatus = privacyScan?.status ?? null
  if (privacyStatus === "clean" || privacyStatus === "redacted") {
    score += 10
  } else if (privacyStatus === "flagged") {
    riskFlags.push("Privacy scan flagged — potential sensitive data in recording")
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
      needsMoreEvidence.push(`${skill} — no strong evidence detected`)
    }
  }

  // +15 at least one strongly supported
  if (strongly.length > 0) {
    score += 15
  } else {
    score = Math.max(0, score - 10)
  }

  // +10 cross-evidence confirmation
  const crossConfirmed = strongly.filter(s => wfSupportedSet.has(s.toLowerCase()) && ghMatchedSet.has(s.toLowerCase()))
  if (crossConfirmed.length > 0) score += 10

  // +5 recruiter summary exists
  const recruiterText = workflowAnalysis?.recruiter_summary ?? githubAnalysis?.recruiter_summary ?? ""
  if (recruiterText.trim().length > 30) score += 5

  // ── Deductions ────────────────────────────────────────────────────────────
  const wfRiskFlags = workflowAnalysis?.risk_flags ?? []
  const shortRecording = wfRiskFlags.some(f => ["short", "brief", "too short"].some(kw => f.toLowerCase().includes(kw)))
  if (shortRecording) {
    score = Math.max(0, score - 10)
    riskFlags.push("Recording is brief — a longer walkthrough would strengthen evidence")
  }

  if (privacyStatus === "flagged") score = Math.max(0, score - 15)

  const wfMissing = workflowAnalysis?.missing_evidence ?? []
  const missingPenalty = Math.min(wfMissing.length * 5, 15)
  score = Math.max(0, score - missingPenalty)
  for (const item of wfMissing) needsMoreEvidence.push(item)

  if (!isLocal && liveCheck !== null && !liveCheck.is_reachable) score = Math.max(0, score - 10)
  if (githubProvided && !githubOk) score = Math.max(0, score - 10)

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

  // Recommended actions
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
  const unsupported = claimedSkills.filter(s => !strongly.map(x => x.toLowerCase()).includes(s.toLowerCase()) && !partially.map(x => x.toLowerCase()).includes(s.toLowerCase()))
  if (unsupported.length > 0) nextActions.push(`Record a walkthrough that clearly demonstrates: ${unsupported.slice(0, 3).join(", ")}.`)
  if (hasWf && workflowAnalysis!.human_review_needed) nextActions.push("Request a faculty or human review — AI confidence is low for this recording.")

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

// ── Main component ────────────────────────────────────────────────────────────

export function ExtensionProofPanel({
  onBack,
  onSessionComplete,
}: {
  onBack: () => void
  onSessionComplete?: () => void
}) {
  const [step, setStep]                 = useState<PanelStep>("form")
  const [form, setForm]                 = useState<FormState>({ websiteUrl: "", githubUrl: "", skillName: "", proofObjective: "" })
  const [session, setSession]           = useState<ExtensionProofSessionResponse | null>(null)
  const [error, setError]               = useState<string | null>(null)
  const [creating, setCreating]         = useState(false)
  const [starting, setStarting]         = useState(false)
  const [pollingActive, setPoll]        = useState(false)
  const [workflowAnalysis, setWorkflowAnalysis] = useState<WorkflowAnalysisResponse | null>(null)
  const [analyzing, setAnalyzing]       = useState(false)
  const [analyzeError, setAnalyzeError] = useState<string | null>(null)
  const [analyzeTimedOut, setAnalyzeTimedOut] = useState(false)

  // Privacy Guard state
  const [privacyAcknowledged, setPrivacyAcknowledged] = useState(false)
  const [privacyScan, setPrivacyScan] = useState<WorkflowPrivacyScanResponse | null>(null)
  const [simProgress, setSimProgress]   = useState(0)
  const [simStageIdx, setSimStageIdx]   = useState(-1)
  const analyzeTimeoutRef               = useRef<ReturnType<typeof setTimeout> | null>(null)

  // GitHub evidence analysis state
  const [githubAnalysis, setGithubAnalysis]       = useState<ExtensionProofGitHubAnalysisResponse | null>(null)
  const [githubAnalyzing, setGithubAnalyzing]     = useState(false)
  const [githubAnalyzeError, setGithubAnalyzeError] = useState<string | null>(null)
  const [githubSimProgress, setGithubSimProgress] = useState(0)
  const [githubSimStageIdx, setGithubSimStageIdx] = useState(0)
  const githubAnalyzeTimeoutRef                   = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Live website check state
  const [liveCheck, setLiveCheck]           = useState<LiveWebsiteCheckResponse | null>(null)
  const [liveChecking, setLiveChecking]     = useState(false)
  const [liveCheckError, setLiveCheckError] = useState<string | null>(null)
  const [liveCheckProgress, setLiveCheckProgress] = useState(0)
  const [liveCheckStageIdx, setLiveCheckStageIdx]  = useState(0)
  const liveCheckTimeoutRef                 = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Derived from form.websiteUrl — available in both form and session_active steps.
  const urlType = classifyUrl(form.websiteUrl)
  const local = isLocal(urlType)

  // ── Verification Readiness Report (computed from existing state) ──────────
  // Re-computed whenever any piece of evidence changes. No extra API call needed.
  const readinessReport = useMemo<ReadinessReport | null>(() => {
    if (!session) return null
    const uploadedOrLater: ExtensionProofSessionStatus[] = [
      "uploaded_pending_analysis", "analyzing", "completed",
    ]
    if (!uploadedOrLater.includes(session.status)) return null
    return computeReadinessReport({
      sessionStatus: session.status,
      urlType,
      claimedSkills: form.skillName.trim()
        ? form.skillName.split(",").map(s => s.trim()).filter(Boolean)
        : [],
      workflowAnalysis,
      liveCheck,
      githubAnalysis,
      privacyScan,
    })
  }, [
    session?.id, session?.status,
    urlType,
    form.skillName,
    workflowAnalysis?.id,
    liveCheck?.id,
    githubAnalysis?.id,
    privacyScan?.status,
    privacyScan?.redacted_fields_count,
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
  useEffect(() => {
    if (!session) return
    if (session.status !== "completed") return
    if (workflowAnalysis) return
    void getWorkflowAnalysis(session.id).then((r) => {
      if (r) setWorkflowAnalysis(r)
    }).catch(() => undefined)
  }, [session?.id, session?.status, workflowAnalysis])

  // ── Auto-fetch live website check ─────────────────────────────────────────
  // When session reaches completed and url is live, load any persisted check.
  useEffect(() => {
    if (!session) return
    if (session.status !== "completed") return
    if (liveCheck) return
    if (isLocal(urlType)) return
    void getLiveWebsiteCheck(session.id).then((r) => {
      if (r) setLiveCheck(r)
    }).catch(() => undefined)
  }, [session?.id, session?.status, liveCheck, urlType])

  // ── Auto-fetch GitHub analysis ────────────────────────────────────────────
  // When session has proof uploaded and a GitHub URL, load any persisted result.
  useEffect(() => {
    if (!session) return
    if (!form.githubUrl.trim()) return
    if (githubAnalysis) return
    const uploadedOrLater: ExtensionProofSessionStatus[] = [
      "uploaded_pending_analysis", "analyzing", "completed",
    ]
    if (!uploadedOrLater.includes(session.status)) return
    void getExtensionProofGitHubAnalysis(session.id).then((r) => {
      if (r) setGithubAnalysis(r)
    }).catch(() => undefined)
  }, [session?.id, session?.status, githubAnalysis, form.githubUrl])

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

  // ── Simulated progress for live check ────────────────────────────────────
  useEffect(() => {
    if (!liveChecking) {
      setLiveCheckProgress(0)
      setLiveCheckStageIdx(0)
      return
    }
    const schedule = [
      { delay: 200,  stageIdx: 0, progress: 15 },
      { delay: 700,  stageIdx: 1, progress: 35 },
      { delay: 1400, stageIdx: 2, progress: 55 },
      { delay: 2200, stageIdx: 3, progress: 75 },
      { delay: 3500, stageIdx: 4, progress: 90 },
    ]
    const timers = schedule.map(({ delay, stageIdx, progress }) =>
      setTimeout(() => {
        setLiveCheckStageIdx(stageIdx)
        setLiveCheckProgress(progress)
      }, delay)
    )
    return () => timers.forEach(clearTimeout)
  }, [liveChecking])

  // ── Simulated progress for GitHub analysis ────────────────────────────────
  useEffect(() => {
    if (!githubAnalyzing) {
      setGithubSimProgress(0)
      setGithubSimStageIdx(0)
      return
    }
    const schedule = [
      { delay: 250,  stageIdx: 0, progress: 15 },
      { delay: 800,  stageIdx: 1, progress: 30 },
      { delay: 1600, stageIdx: 2, progress: 45 },
      { delay: 2600, stageIdx: 3, progress: 60 },
      { delay: 3700, stageIdx: 4, progress: 75 },
      { delay: 5000, stageIdx: 5, progress: 85 },
      { delay: 6500, stageIdx: 6, progress: 92 },
    ]
    const timers = schedule.map(({ delay, stageIdx, progress }) =>
      setTimeout(() => {
        setGithubSimStageIdx(stageIdx)
        setGithubSimProgress(progress)
      }, delay)
    )
    return () => timers.forEach(clearTimeout)
  }, [githubAnalyzing])

  // ── Simulated progress during analysis ────────────────────────────────────
  useEffect(() => {
    if (!analyzing) {
      setSimProgress(0)
      setSimStageIdx(-1)
      return
    }
    const schedule: Array<{ delay: number; stageIdx: number; progress: number }> = [
      { delay: 300,  stageIdx: 0, progress: 8  },
      { delay: 900,  stageIdx: 1, progress: 20 },
      { delay: 1600, stageIdx: 2, progress: 35 },
      { delay: 2500, stageIdx: 3, progress: 50 },
      { delay: 3600, stageIdx: 4, progress: 65 },
      { delay: 4800, stageIdx: 5, progress: 78 },
      { delay: 6200, stageIdx: 5, progress: 90 },
    ]
    const timers = schedule.map(({ delay, stageIdx, progress }) =>
      setTimeout(() => {
        setSimStageIdx(stageIdx)
        setSimProgress(progress)
      }, delay)
    )
    return () => timers.forEach(clearTimeout)
  }, [analyzing])

  // ── Analyze workflow ──────────────────────────────────────────────────────

  // Parse comma-separated skill names from the form field into a clean array.
  function parseSkills(): string[] {
    return form.skillName.trim()
      ? form.skillName.split(",").map(s => s.trim()).filter(Boolean)
      : []
  }

  async function handleAnalyze() {
    if (!session) return
    setAnalyzing(true)
    setAnalyzeError(null)
    setAnalyzeTimedOut(false)

    let cancelled = false
    const timeoutId = setTimeout(() => {
      cancelled = true
      setAnalyzeTimedOut(true)
      setAnalyzing(false)
      setAnalyzeError("Analysis timed out after 90 seconds. Please retry.")
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
      setPoll(false)
      const updated = await getExtensionProofSession(session.id)
      if (!cancelled) setSession(updated)
    } catch (err) {
      if (cancelled) return
      clearTimeout(timeoutId)
      analyzeTimeoutRef.current = null
      setAnalyzeError(err instanceof Error ? err.message : "Analysis failed. Please try again.")
    } finally {
      if (!cancelled) setAnalyzing(false)
    }
  }

  // ── Run live website check ────────────────────────────────────────────────

  async function handleLiveCheck() {
    if (!session) return
    setLiveChecking(true)
    setLiveCheckError(null)
    setLiveCheck(null)

    let cancelled = false
    const timeoutId = setTimeout(() => {
      cancelled = true
      setLiveChecking(false)
      setLiveCheckError("Live website check timed out after 30 seconds. Please retry.")
      if (liveCheckTimeoutRef.current === timeoutId) liveCheckTimeoutRef.current = null
    }, 30_000)
    liveCheckTimeoutRef.current = timeoutId

    try {
      const result = await runLiveWebsiteCheck(session.id, form.websiteUrl.trim())
      if (cancelled) return
      clearTimeout(timeoutId)
      liveCheckTimeoutRef.current = null
      setLiveCheck(result)
    } catch (err) {
      if (cancelled) return
      clearTimeout(timeoutId)
      liveCheckTimeoutRef.current = null
      setLiveCheckError(err instanceof Error ? err.message : "Live website check failed. Please try again.")
    } finally {
      if (!cancelled) setLiveChecking(false)
    }
  }

  // ── Run GitHub evidence analysis ──────────────────────────────────────────

  async function handleGitHubAnalysis() {
    if (!session) return
    const githubUrl = form.githubUrl.trim()
    if (!githubUrl) return

    setGithubAnalyzing(true)
    setGithubAnalyzeError(null)
    setGithubAnalysis(null)

    let cancelled = false
    const timeoutId = setTimeout(() => {
      cancelled = true
      setGithubAnalyzing(false)
      setGithubAnalyzeError("GitHub analysis timed out after 90 seconds. Please retry.")
      if (githubAnalyzeTimeoutRef.current === timeoutId) githubAnalyzeTimeoutRef.current = null
    }, 90_000)
    githubAnalyzeTimeoutRef.current = timeoutId

    try {
      const result = await analyzeExtensionProofGitHub(session.id, githubUrl, parseSkills(), {
        liveWebsiteUrl: liveCheck?.final_url ?? form.websiteUrl.trim(),
        livePageTitle: liveCheck?.page_title ?? "",
        proofObjective: form.proofObjective.trim(),
      })
      if (cancelled) return
      clearTimeout(timeoutId)
      githubAnalyzeTimeoutRef.current = null
      setGithubAnalysis(result)
    } catch (err) {
      if (cancelled) return
      clearTimeout(timeoutId)
      githubAnalyzeTimeoutRef.current = null
      setGithubAnalyzeError(err instanceof Error ? err.message : "GitHub analysis failed. Please try again.")
    } finally {
      if (!cancelled) setGithubAnalyzing(false)
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
    if (wordCount(form.proofObjective) < 5) {
      setError("Describe what this walkthrough proves (at least 5 words).")
      return
    }

    setCreating(true)
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

      const targetUrl = form.websiteUrl.trim()
      try {
        const url = new URL(targetUrl)
        url.searchParams.set("veribridge_session_id", session.id)
        window.open(url.toString(), "_blank", "noopener,noreferrer")
      } catch {
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

  // ── Render: form ─────────────────────────────────────────────────────────

  if (step === "form") {
    const showLocalWarning = form.websiteUrl.trim() !== "" && local

    return (
      <div style={{ display: "grid", gap: 18 }}>
        {/* Info banner */}
        <div style={{ border: "1px solid #bfdbfe", borderRadius: 12, background: "#eff6ff", padding: "14px 16px" }}>
          <p style={{ margin: 0, fontSize: 12, color: "#1e40af", lineHeight: 1.6 }}>
            Use the VeriBridge Chrome Extension to record a live walkthrough of your project
            website in your own browser. Works for deployed sites, private dashboards, and
            local development servers on <code style={{ fontSize: 11 }}>localhost</code>.
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
              style={{ ...inp, minHeight: 80, resize: "vertical", fontFamily: "inherit", lineHeight: 1.5 }}
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
            style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "9px 14px", fontWeight: 600, fontSize: 13, cursor: creating ? "not-allowed" : "pointer" }}
          >
            ← Back
          </button>
          <button
            type="button"
            onClick={() => void handleCreate()}
            disabled={creating || !privacyAcknowledged}
            title={!privacyAcknowledged ? "Please acknowledge the privacy warning above first." : undefined}
            style={{
              border: "1px solid transparent",
              background: creating || !privacyAcknowledged ? "var(--bg-2)" : "var(--ink)",
              color: creating || !privacyAcknowledged ? "var(--muted)" : "#fff",
              borderRadius: 10, padding: "10px 20px", fontWeight: 700, fontSize: 14,
              cursor: creating || !privacyAcknowledged ? "not-allowed" : "pointer",
            }}
          >
            {creating
              ? "Creating session…"
              : local
              ? "Create Local Workflow Proof Session"
              : "Create Extension Proof Session"}
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

    const sectionTitle = local ? "Local Workflow Evidence" : "Website Workflow Evidence"
    const sectionSubtitle = local
      ? "This evidence shows a recorded workflow of your locally running project. It demonstrates the app working in your development environment. Recruiters will see this as medium-confidence evidence — add GitHub or deploy your app for stronger verification."
      : "This evidence shows a recorded workflow of the submitted website or application. It verifies that the app was demonstrated, but it is not the final skill verification by itself."
    const cardTitle = local ? "Local Workflow Evidence Session" : "Website Workflow Evidence Session"

    const sessionDetails: Array<[string, string, boolean]> = [
      ["Session ID", session.id.slice(0, 18) + "…", true],
      ["Website",    form.websiteUrl, false],
      ...(form.githubUrl ? [["GitHub", form.githubUrl, false] as [string, string, boolean]] : []),
      ["Skill",      form.skillName, false],
    ]

    return (
      <div style={{ display: "grid", gap: 18 }}>
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
          </div>
        </div>

        {/* Session stepper */}
        <SessionStepper status={session.status} />

        {/* Evidence checklist */}
        <EvidenceChecklist
          status={session.status}
          urlType={urlType}
          analysis={workflowAnalysis}
          liveCheck={liveCheck}
          liveChecking={liveChecking}
          hasGithubUrl={!!form.githubUrl.trim()}
          githubAnalysis={githubAnalysis}
          githubAnalyzing={githubAnalyzing}
          finalVerificationReady={readinessReport?.final_verification_status === "ready_for_review"}
        />

        {/* Privacy scan badge — shown once proof is uploaded */}
        {privacyScan && (
          <PrivacyScanBadge
            scan={privacyScan}
            onReRecord={onBack}
          />
        )}

        {error && (
          <div role="alert" style={{ border: "1px solid #fecaca", background: "#fef2f2", color: "#991b1b", borderRadius: 10, padding: "8px 12px", fontSize: 12 }}>
            {error}
          </div>
        )}

        {/* Status-aware message card */}
        {!isExpired && (
          <StatusMessage
            status={session.status}
            pollingActive={pollingActive}
            session={session}
            urlType={urlType}
          />
        )}

        {/* Analyze button — shown when uploaded and not yet analyzing */}
        {session.status === "uploaded_pending_analysis" && !workflowAnalysis && !analyzing && (
          <div style={{ border: "1px solid #bfdbfe", borderRadius: 12, background: "#eff6ff", padding: "14px 16px", display: "grid", gap: 10 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#1e40af" }}>Ready to analyze your workflow</div>
              <p style={{ margin: "4px 0 0", fontSize: 12, color: "#1e3a8a", lineHeight: 1.65 }}>
                VeriBridge will analyze your recorded workflow timeline to identify which claimed skills
                are supported, what interactions were demonstrated, and what evidence is still missing.
                This is a Workflow Timeline Analysis — it does not replace GitHub evidence or final verification.
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

        {/* Error display — always visible, outside any conditional container */}
        {analyzeError && !workflowAnalysis && (
          <div role="alert" style={{ border: "1px solid #fecaca", background: "#fef2f2", borderRadius: 10, padding: "10px 14px", display: "grid", gap: 8 }}>
            <div style={{ color: "#991b1b", fontSize: 12 }}>{analyzeError}</div>
            {!analyzing && (
              <div>
                <button
                  type="button"
                  onClick={() => void handleAnalyze()}
                  style={{
                    border: "1px solid #dc2626", background: "transparent", color: "#991b1b",
                    borderRadius: 8, padding: "6px 14px", fontWeight: 600, fontSize: 12, cursor: "pointer",
                  }}
                >
                  Retry Analysis
                </button>
              </div>
            )}
          </div>
        )}

        {/* Stuck analyzing state — session is analyzing but no active request and no error */}
        {session.status === "analyzing" && !workflowAnalysis && !analyzing && !analyzeError && (
          <div style={{ border: "1px solid #ddd6fe", borderRadius: 12, background: "#faf5ff", padding: "14px 16px", display: "grid", gap: 8 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#5b21b6" }}>Analysis in progress</div>
            <p style={{ margin: 0, fontSize: 12, color: "#4c1d95", lineHeight: 1.65 }}>
              Workflow analysis was started in a previous attempt. Click Retry to re-run the analysis.
            </p>
            <div>
              <button
                type="button"
                onClick={() => void handleAnalyze()}
                style={{
                  border: "1px solid transparent", background: "#6d28d9", color: "#fff",
                  borderRadius: 10, padding: "8px 18px", fontWeight: 700, fontSize: 13, cursor: "pointer",
                }}
              >
                Retry Analysis
              </button>
            </div>
          </div>
        )}

        {/* In-progress analysis with simulated progress stages */}
        {analyzing && <WorkflowAnalysisInProgress simProgress={simProgress} simStageIdx={simStageIdx} />}

        {/* Workflow analysis result card */}
        {workflowAnalysis && <WorkflowAnalysisCard analysis={workflowAnalysis} />}

        {/* ── Live Website Check ─────────────────────────────────────────── */}

        {/* Not available note for local projects */}
        {isLocal(urlType) && isCompleted && (
          <div style={{ border: "1px solid #e2e8f0", borderRadius: 12, background: "#f8fafc", padding: "12px 14px", display: "grid", gap: 4 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: "#64748b" }}>Live Website Check: Not Available</div>
            <p style={{ margin: 0, fontSize: 11, color: "#64748b", lineHeight: 1.6 }}>
              Localhost projects cannot be accessed by recruiters or VeriBridge after the recording session.
              Add GitHub / setup instructions or deploy the app for stronger verification.
            </p>
          </div>
        )}

        {/* Run button for live deployed URLs — shown once workflow analysis is done and check not yet run */}
        {!isLocal(urlType) && isCompleted && !liveCheck && !liveChecking && (
          <div style={{ border: "1px solid #bfdbfe", borderRadius: 12, background: "#eff6ff", padding: "14px 16px", display: "grid", gap: 10 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#1e40af" }}>Run Live Website Check</div>
              <p style={{ margin: "4px 0 0", fontSize: 12, color: "#1e3a8a", lineHeight: 1.65 }}>
                VeriBridge will send a live HTTP request to your deployed website to confirm it is publicly
                accessible, capture the HTTP status, response time, and page title.
              </p>
            </div>
            <div>
              <button
                type="button"
                onClick={() => void handleLiveCheck()}
                style={{
                  border: "1px solid transparent", background: "#1d4ed8", color: "#fff",
                  borderRadius: 10, padding: "10px 20px", fontWeight: 700, fontSize: 14, cursor: "pointer",
                }}
              >
                Run Live Website Check
              </button>
            </div>
          </div>
        )}

        {/* Live check error */}
        {liveCheckError && !liveCheck && (
          <div role="alert" style={{ border: "1px solid #fecaca", background: "#fef2f2", borderRadius: 10, padding: "10px 14px", display: "grid", gap: 8 }}>
            <div style={{ color: "#991b1b", fontSize: 12 }}>{liveCheckError}</div>
            {!liveChecking && (
              <div>
                <button
                  type="button"
                  onClick={() => void handleLiveCheck()}
                  style={{
                    border: "1px solid #dc2626", background: "transparent", color: "#991b1b",
                    borderRadius: 8, padding: "6px 14px", fontWeight: 600, fontSize: 12, cursor: "pointer",
                  }}
                >
                  Retry Live Website Check
                </button>
              </div>
            )}
          </div>
        )}

        {/* Live check in-progress */}
        {liveChecking && (
          <LiveWebsiteCheckInProgress simProgress={liveCheckProgress} simStageIdx={liveCheckStageIdx} />
        )}

        {/* Live check result */}
        {liveCheck && (
          <LiveWebsiteCheckCard check={liveCheck} onRetry={() => void handleLiveCheck()} />
        )}

        {/* ── GitHub Evidence Analysis ────────────────────────────────── */}

        {/* No GitHub URL provided */}
        {!form.githubUrl.trim() && (["uploaded_pending_analysis", "analyzing", "completed"] as ExtensionProofSessionStatus[]).includes(session.status) && (
          <div style={{ border: "1px solid #e2e8f0", borderRadius: 12, background: "#f8fafc", padding: "12px 14px", display: "grid", gap: 6 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: "#64748b" }}>GitHub Evidence: Not Provided</div>
            <p style={{ margin: 0, fontSize: 11, color: "#64748b", lineHeight: 1.6 }}>
              No GitHub URL was submitted with this proof session. Add a public GitHub repository to strengthen your evidence.
            </p>
          </div>
        )}

        {/* Run GitHub analysis button — shown when GitHub URL provided, proof uploaded, and not yet analyzed */}
        {form.githubUrl.trim() && (["uploaded_pending_analysis", "analyzing", "completed"] as ExtensionProofSessionStatus[]).includes(session.status) && !githubAnalysis && !githubAnalyzing && (
          <div style={{ border: "1px solid #e5e7eb", borderRadius: 12, background: "#f9fafb", padding: "14px 16px", display: "grid", gap: 10 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#111827" }}>Run GitHub Evidence Analysis</div>
              <p style={{ margin: "4px 0 0", fontSize: 12, color: "#374151", lineHeight: 1.65 }}>
                VeriBridge will fetch your public repository, detect the tech stack, match claimed skills, and generate a recruiter-readable evidence report.
              </p>
              <p style={{ margin: "6px 0 0", fontSize: 11, color: "#6b7280" }}>
                Repo: <span style={{ fontFamily: "monospace" }}>{form.githubUrl.trim()}</span>
              </p>
            </div>
            <div>
              <button
                type="button"
                onClick={() => void handleGitHubAnalysis()}
                style={{
                  border: "1px solid transparent", background: "#111827", color: "#fff",
                  borderRadius: 10, padding: "10px 20px", fontWeight: 700, fontSize: 14, cursor: "pointer",
                }}
              >
                Run GitHub Evidence Analysis
              </button>
            </div>
          </div>
        )}

        {/* GitHub analysis error */}
        {githubAnalyzeError && !githubAnalysis && (
          <div role="alert" style={{ border: "1px solid #fecaca", background: "#fef2f2", borderRadius: 10, padding: "10px 14px", display: "grid", gap: 8 }}>
            <div style={{ color: "#991b1b", fontSize: 12 }}>{githubAnalyzeError}</div>
            {!githubAnalyzing && (
              <div>
                <button
                  type="button"
                  onClick={() => void handleGitHubAnalysis()}
                  style={{
                    border: "1px solid #dc2626", background: "transparent", color: "#991b1b",
                    borderRadius: 8, padding: "6px 14px", fontWeight: 600, fontSize: 12, cursor: "pointer",
                  }}
                >
                  Retry GitHub Analysis
                </button>
              </div>
            )}
          </div>
        )}

        {/* GitHub analysis in progress */}
        {githubAnalyzing && (
          <GitHubAnalysisInProgress simProgress={githubSimProgress} simStageIdx={githubSimStageIdx} />
        )}

        {/* GitHub analysis result */}
        {githubAnalysis && !githubAnalyzing && (
          <GitHubAnalysisCard analysis={githubAnalysis} onRerun={() => void handleGitHubAnalysis()} />
        )}

        {/* ── Combined evidence summary — shown when both analyses exist ── */}
        {workflowAnalysis && githubAnalysis && !githubAnalyzing && (
          <CombinedEvidenceSummaryCard
            claimedSkills={parseSkills()}
            workflowAnalysis={workflowAnalysis}
            githubAnalysis={githubAnalysis}
            liveCheck={liveCheck}
          />
        )}

        {/* ── Verification Readiness Report ──────────────────────────────── */}
        {/* Shown once proof is uploaded and at least some analysis has run.
            Computes score from existing state — no extra network fetch.
            Final Verification is NEVER marked complete from this component. */}
        {readinessReport && (
          <VerificationReadinessReportCard report={readinessReport} />
        )}

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
          <button
            type="button"
            onClick={onBack}
            style={{ border: "1px solid var(--line-2)", background: "transparent", color: "var(--ink-2)", borderRadius: 10, padding: "9px 14px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}
          >
            ← Back
          </button>

          {!hasStarted && !isExpired && (
            <button
              type="button"
              onClick={() => void handleStart()}
              disabled={starting}
              style={{ border: "1px solid transparent", background: starting ? "var(--bg-2)" : "#065f46", color: starting ? "var(--muted)" : "#fff", borderRadius: 10, padding: "10px 20px", fontWeight: 700, fontSize: 14, cursor: starting ? "not-allowed" : "pointer" }}
            >
              {starting ? "Opening…" : "▶  Start Proof Demo"}
            </button>
          )}

          {(isCompleted || isExpired) && (
            <button
              type="button"
              onClick={onBack}
              style={{ border: "1px solid var(--ink)", background: "var(--ink)", color: "#fff", borderRadius: 10, padding: "10px 20px", fontWeight: 700, fontSize: 14, cursor: "pointer" }}
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
