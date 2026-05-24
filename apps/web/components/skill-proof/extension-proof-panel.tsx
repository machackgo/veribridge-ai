"use client"

import React, { useEffect, useState } from "react"
import type { CSSProperties } from "react"
import {
  createExtensionProofSession,
  createSkillEvidence,
  getExtensionProofSession,
  startExtensionProofSession,
  analyzeWorkflowEvidence,
  getWorkflowAnalysis,
  type ExtensionProofSessionResponse,
  type ExtensionProofSessionStatus,
  type WorkflowAnalysisResponse,
  type WorkflowConfidence,
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
  completed:                 { bg: "#dcfce7", color: "#166534", border: "#bbf7d0", label: "FULLY VERIFIED" },
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

function buildEvidenceItems(
  urlType: UrlType,
  analysis: WorkflowAnalysisResponse | null,
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
      getStatus: () => "pending",
    },
    {
      key: "live_check",
      label: "Live Website Check",
      getStatus: () => (local ? "unavailable" : "pending"),
    },
    {
      key: "final",
      label: "Final Verification",
      getStatus: () => "pending",
    },
  ]
}

function evidenceLabelOverride(key: string, s: EvidenceItemStatus): string {
  if (key === "workflow_analysis" && s === "complete") return "AI Reviewed"
  if (key === "workflow_analysis" && s === "uploading") return "In Progress"
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
  const items = buildEvidenceItems(urlType, analysis)
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
                <span style={{ fontSize: 13, fontWeight: 700, lineHeight: 1 }}>{evidenceIcon(s)}</span>
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

  if (status === "analyzing") {
    return (
      <div style={{ border: "1px solid #ddd6fe", borderRadius: 12, background: "#faf5ff", padding: "14px 16px", display: "grid", gap: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#5b21b6" }}>Verification analysis in progress</div>
        <p style={{ margin: 0, fontSize: 12, color: "#4c1d95", lineHeight: 1.7 }}>
          VeriBridge is reviewing your submitted evidence. Final verification is still pending.
        </p>
        {pollingActive && (
          <p style={{ margin: 0, fontSize: 11, color: "#7c3aed" }}>Analysis running…</p>
        )}
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

  // Derived from form.websiteUrl — available in both form and session_active steps.
  const urlType = classifyUrl(form.websiteUrl)
  const local = isLocal(urlType)

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
  // When the session is in analyzing/completed, try to load an existing result.
  useEffect(() => {
    if (!session) return
    if (!["analyzing", "completed"].includes(session.status)) return
    if (workflowAnalysis) return
    void getWorkflowAnalysis(session.id).then((r) => {
      if (r) setWorkflowAnalysis(r)
    }).catch(() => undefined)
  }, [session?.id, session?.status, workflowAnalysis])

  // ── Analyze workflow ──────────────────────────────────────────────────────

  async function handleAnalyze() {
    if (!session) return
    setAnalyzing(true)
    setAnalyzeError(null)
    try {
      const result = await analyzeWorkflowEvidence(session.id, {
        claimed_skills: form.skillName.trim() ? [form.skillName.trim()] : [],
        proof_objective: form.proofObjective.trim(),
        original_url: form.websiteUrl.trim(),
        url_type: urlType,
        github_url: form.githubUrl.trim() || null,
      })
      setWorkflowAnalysis(result)
      // Refresh session — status may have moved to 'analyzing'
      const updated = await getExtensionProofSession(session.id)
      setSession(updated)
    } catch (err) {
      setAnalyzeError(err instanceof Error ? err.message : "Analysis failed. Please try again.")
    } finally {
      setAnalyzing(false)
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
        {/* Info + privacy banner */}
        <div style={{ border: "1px solid #bfdbfe", borderRadius: 12, background: "#eff6ff", padding: "14px 16px", display: "grid", gap: 10 }}>
          <p style={{ margin: 0, fontSize: 12, color: "#1e40af", lineHeight: 1.6 }}>
            Use the VeriBridge Chrome Extension to record a live walkthrough of your project
            website in your own browser. Works for deployed sites, private dashboards, and
            local development servers on <code style={{ fontSize: 11 }}>localhost</code>.
          </p>
          <p style={{ margin: 0, fontSize: 11, color: "#3b82f6", lineHeight: 1.5, borderTop: "1px solid #bfdbfe", paddingTop: 10 }}>
            <strong>Privacy:</strong> VeriBridge records project workflow evidence only. Do not show
            personal data. Passwords and sensitive fields are masked by the extension and backend.
          </p>
        </div>

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
            disabled={creating}
            style={{ border: "1px solid transparent", background: creating ? "var(--bg-2)" : "var(--ink)", color: creating ? "var(--muted)" : "#fff", borderRadius: 10, padding: "10px 20px", fontWeight: 700, fontSize: 14, cursor: creating ? "not-allowed" : "pointer" }}
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
        <EvidenceChecklist status={session.status} urlType={urlType} analysis={workflowAnalysis} />

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

        {/* Analyze Workflow Evidence button — shown when proof is uploaded and analysis not yet done */}
        {session.status === "uploaded_pending_analysis" && !workflowAnalysis && (
          <div style={{ border: "1px solid #bfdbfe", borderRadius: 12, background: "#eff6ff", padding: "14px 16px", display: "grid", gap: 10 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#1e40af" }}>Ready to analyze your workflow</div>
              <p style={{ margin: "4px 0 0", fontSize: 12, color: "#1e3a8a", lineHeight: 1.65 }}>
                VeriBridge will analyze your recorded workflow timeline to identify which claimed skills
                are supported, what interactions were demonstrated, and what evidence is still missing.
                This is a Workflow Timeline Analysis — it does not replace GitHub evidence or final verification.
              </p>
            </div>
            {analyzeError && (
              <div role="alert" style={{ border: "1px solid #fecaca", background: "#fef2f2", color: "#991b1b", borderRadius: 8, padding: "7px 10px", fontSize: 12 }}>
                {analyzeError}
              </div>
            )}
            <div>
              <button
                type="button"
                onClick={() => void handleAnalyze()}
                disabled={analyzing}
                style={{
                  border: "1px solid transparent",
                  background: analyzing ? "var(--bg-2)" : "#1d4ed8",
                  color: analyzing ? "var(--muted)" : "#fff",
                  borderRadius: 10, padding: "10px 20px",
                  fontWeight: 700, fontSize: 14,
                  cursor: analyzing ? "not-allowed" : "pointer",
                }}
              >
                {analyzing ? "Analyzing workflow…" : "Analyze Workflow Evidence"}
              </button>
            </div>
          </div>
        )}

        {/* In-progress analysis indicator */}
        {analyzing && (
          <div style={{ border: "1px solid #ddd6fe", borderRadius: 12, background: "#faf5ff", padding: "14px 16px", display: "grid", gap: 6 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#5b21b6" }}>Analyzing workflow…</div>
            <p style={{ margin: 0, fontSize: 12, color: "#4c1d95", lineHeight: 1.65 }}>
              Evaluating your recorded workflow, matched skills, and evidence quality.
            </p>
          </div>
        )}

        {/* Workflow analysis result card */}
        {workflowAnalysis && <WorkflowAnalysisCard analysis={workflowAnalysis} />}

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
