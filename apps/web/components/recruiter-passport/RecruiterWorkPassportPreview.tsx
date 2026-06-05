"use client"

/**
 * RecruiterWorkPassportPreview
 *
 * Renders the evidence-enriched recruiter view of a Work Passport.
 * Consumes the /recruiter-view API endpoint and presents:
 *  - Candidate summary + overall evidence score
 *  - Grouped skill evidence with source badges and confidence
 *  - Proof source status (which evidence sources were completed)
 *  - Recruiter decision helpers (why credible, interview questions)
 *  - Project links and request-access CTA with modal
 *
 * Privacy rules:
 *  - No raw transcript text, media URLs, access tokens, or debug fields.
 *  - All displayed data comes from the recruiter-safe backend serializer.
 *  - Access to private evidence requires a separate student-approved flow.
 */

import { useState, useEffect } from "react"
import { EvidenceAccessRequestModal } from "./EvidenceAccessRequestModal"
import { listStudentAccessRequests } from "../../src/lib/mock-evidence-access-store"
import { normaliseEvidenceKey, type EvidenceAccessRequest } from "../../src/types/evidence-access"
import type {
  RecruiterPassportViewResponse,
  RecruiterSkillGroupResponse,
  RecruiterProofSourceResponse,
} from "../../src/lib/passport-api"

// ── Design tokens (mirrors passport/shared TOKEN) ─────────────────────────────

const C = {
  ink: "#0f172a",
  inkSoft: "#334155",
  muted: "#64748b",
  line: "#e2e8f0",
  bg: "#f8fafc",
  paper: "#ffffff",
  indigo: "#4f46e5",
  indigoSoft: "#eef2ff",
  emerald: "#059669",
  emeraldSoft: "#f0fdf4",
  amber: "#d97706",
  amberSoft: "#fffbeb",
  rose: "#e11d48",
  roseSoft: "#fff1f2",
  sky: "#0284c7",
  skySoft: "#f0f9ff",
  violet: "#7c3aed",
  violetSoft: "#f5f3ff",
}

// ── Small helpers ─────────────────────────────────────────────────────────────

function confidenceColor(c: "high" | "medium" | "low"): string {
  return c === "high" ? C.emerald : c === "medium" ? C.amber : C.muted
}

function confidenceBg(c: "high" | "medium" | "low"): string {
  return c === "high" ? C.emeraldSoft : c === "medium" ? C.amberSoft : C.bg
}

function confidenceBorder(c: "high" | "medium" | "low"): string {
  return c === "high" ? "#bbf7d0" : c === "medium" ? "#fde68a" : C.line
}

function confidenceLabel(c: "high" | "medium" | "low"): string {
  return c === "high" ? "High confidence" : c === "medium" ? "Partial evidence" : "Needs review"
}

function scoreColor(score: number): string {
  return score >= 80 ? C.emerald : score >= 50 ? C.amber : C.rose
}

function sourceStatusColor(status: string): string {
  return status === "pass" ? C.emerald
    : status === "partial" ? C.amber
    : C.muted
}

function sourceStatusBg(status: string): string {
  return status === "pass" ? C.emeraldSoft
    : status === "partial" ? C.amberSoft
    : C.bg
}

function sourceStatusLabel(status: string): string {
  return status === "pass" ? "Analyzed"
    : status === "partial" ? "Partial"
    : status === "not_run" ? "Not run"
    : status === "not_available" ? "Not configured"
    : status === "missing" ? "Missing"
    : status
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ConfidenceBadge({ level }: { level: "high" | "medium" | "low" }) {
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 999,
      background: confidenceBg(level),
      color: confidenceColor(level),
      border: `1px solid ${confidenceBorder(level)}`,
      letterSpacing: "0.03em",
      whiteSpace: "nowrap",
    }}>
      {confidenceLabel(level)}
    </span>
  )
}

function SourceBadge({ label }: { label: string }) {
  return (
    <span style={{
      fontSize: 10, fontWeight: 600, padding: "2px 7px", borderRadius: 5,
      background: C.indigoSoft, color: C.indigo,
      border: "1px solid #c7d2fe",
    }}>
      {label}
    </span>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 800, letterSpacing: "0.1em",
      textTransform: "uppercase", color: C.muted,
      marginBottom: 12,
    }}>
      {children}
    </div>
  )
}

function Card({ children, style, "data-testid": testId }: { children: React.ReactNode; style?: React.CSSProperties; "data-testid"?: string }) {
  return (
    <div
      data-testid={testId}
      style={{
        background: C.paper,
        border: `1px solid ${C.line}`,
        borderRadius: 12,
        padding: "20px 22px",
        ...style,
      }}
    >
      {children}
    </div>
  )
}

// ── Section: Overall Evidence Score ──────────────────────────────────────────

function EvidenceScoreSection({
  score,
  confidence,
  verificationStatus,
  readinessLevel,
  proofSources,
}: {
  score: number
  confidence: "high" | "medium" | "low"
  verificationStatus?: string | null
  readinessLevel?: string | null
  proofSources: RecruiterProofSourceResponse[]
}) {
  const runSources = proofSources.filter((s) => s.is_run)
  return (
    <Card>
      <SectionTitle>Overall Evidence Confidence</SectionTitle>
      <div style={{ display: "flex", alignItems: "center", gap: 20, flexWrap: "wrap", marginBottom: 16 }}>
        {/* Score dial */}
        <div style={{
          width: 72, height: 72, borderRadius: "50%",
          background: `conic-gradient(${scoreColor(score)} ${score * 3.6}deg, ${C.line} 0deg)`,
          display: "flex", alignItems: "center", justifyContent: "center",
          flexShrink: 0,
        }}>
          <div style={{
            width: 52, height: 52, borderRadius: "50%",
            background: C.paper, display: "flex", alignItems: "center",
            justifyContent: "center", flexDirection: "column",
          }}>
            <span style={{ fontSize: 18, fontWeight: 800, color: scoreColor(score), lineHeight: 1 }}>
              {score}
            </span>
            <span style={{ fontSize: 8, color: C.muted }}>/ 100</span>
          </div>
        </div>

        <div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
            <ConfidenceBadge level={confidence} />
            {verificationStatus && (
              <span style={{
                fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 999,
                background: C.indigoSoft, color: C.indigo, border: "1px solid #c7d2fe",
              }}>
                AI Reviewed
              </span>
            )}
            {readinessLevel && (
              <span style={{
                fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 999,
                background: C.skySoft, color: C.sky, border: "1px solid #bae6fd",
              }}>
                {readinessLevel}
              </span>
            )}
          </div>
          <p style={{ fontSize: 12, color: C.inkSoft, margin: 0 }}>
            {runSources.length} of {proofSources.length} evidence sources analyzed
          </p>
        </div>
      </div>

      {/* Proof source grid */}
      {proofSources.length > 0 && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
          gap: 6,
        }}>
          {proofSources.map((src) => (
            <div key={src.key} style={{
              padding: "7px 10px",
              background: src.is_run ? sourceStatusBg(src.status) : C.bg,
              border: `1px solid ${src.is_run ? (src.status === "pass" ? "#bbf7d0" : src.status === "partial" ? "#fde68a" : C.line) : C.line}`,
              borderRadius: 7,
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}>
              <span style={{
                width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
                background: src.is_run ? sourceStatusColor(src.status) : C.line,
              }} />
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: C.ink, lineHeight: 1.2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {src.label}
                </div>
                <div style={{ fontSize: 9, color: C.muted }}>
                  {src.is_run ? `${src.score}/100` : sourceStatusLabel(src.status)}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

// ── Section: Evidence-Backed Skills ──────────────────────────────────────────

function SkillGroupCard({ group }: { group: RecruiterSkillGroupResponse }) {
  return (
    <div style={{
      border: `1px solid ${confidenceBorder(group.confidence)}`,
      borderRadius: 10,
      overflow: "hidden",
    }}>
      {/* Group header */}
      <div style={{
        padding: "10px 14px",
        background: confidenceBg(group.confidence),
        borderBottom: `1px solid ${confidenceBorder(group.confidence)}`,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 8,
        flexWrap: "wrap",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontWeight: 700, fontSize: 13, color: C.ink }}>{group.group_name}</span>
          <ConfidenceBadge level={group.confidence} />
        </div>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {group.source_labels.map((lbl) => (
            <SourceBadge key={lbl} label={lbl} />
          ))}
        </div>
      </div>

      {/* Skills list */}
      <div style={{ padding: "10px 14px", display: "flex", flexDirection: "column", gap: 6 }}>
        {group.skills.map((skill) => (
          <div key={skill.skill} style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{
              fontSize: 12, fontWeight: 600, color: C.ink, minWidth: 0,
            }}>
              {skill.skill}
            </span>
            <span style={{
              fontSize: 10, color: confidenceColor(skill.confidence),
              fontStyle: "italic",
            }}>
              {skill.status_label}
            </span>
            <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
              {skill.source_labels.map((lbl) => (
                <span key={lbl} style={{
                  fontSize: 9, padding: "1px 5px", borderRadius: 4,
                  background: C.indigoSoft, color: C.indigo,
                  border: "1px solid #c7d2fe",
                }}>
                  {lbl}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function SkillGroupsSection({ groups, verified, partial, needsReview }: {
  groups: RecruiterSkillGroupResponse[]
  verified: string[]
  partial: string[]
  needsReview: string[]
}) {
  // Prefer grouped evidence if available; fall back to flat skill lists
  const hasGroups = groups.length > 0
  return (
    <Card>
      <SectionTitle>Evidence-Backed Skills</SectionTitle>
      {hasGroups ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {groups.map((g) => <SkillGroupCard key={g.group_name} group={g} />)}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {verified.length > 0 && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: C.emerald, textTransform: "uppercase", marginBottom: 6 }}>
                Strongly supported
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {verified.map((s) => (
                  <span key={s} style={{
                    fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 999,
                    background: C.emeraldSoft, color: C.emerald, border: "1px solid #bbf7d0",
                  }}>
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}
          {partial.length > 0 && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: C.amber, textTransform: "uppercase", marginBottom: 6 }}>
                Partial evidence
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {partial.map((s) => (
                  <span key={s} style={{
                    fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 999,
                    background: C.amberSoft, color: C.amber, border: "1px solid #fde68a",
                  }}>
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}
          {needsReview.length > 0 && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase", marginBottom: 6 }}>
                Needs more evidence
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {needsReview.map((s) => (
                  <span key={s} style={{
                    fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 999,
                    background: C.bg, color: C.muted, border: `1px solid ${C.line}`,
                  }}>
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}
          {verified.length === 0 && partial.length === 0 && needsReview.length === 0 && (
            <p style={{ fontSize: 12, color: C.muted, margin: 0 }}>
              Evidence analysis is pending or not available.
            </p>
          )}
        </div>
      )}
    </Card>
  )
}

// ── Section: Recruiter Decision Helpers ──────────────────────────────────────

function DecisionHelpersSection({
  whyCredible,
  areasNeedingReview,
  suggestedQuestions,
}: {
  whyCredible: string[]
  areasNeedingReview: string[]
  suggestedQuestions: string[]
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
      {/* Why credible */}
      {whyCredible.length > 0 && (
        <Card>
          <SectionTitle>Why this candidate is credible</SectionTitle>
          <ul style={{ margin: 0, padding: "0 0 0 16px", display: "flex", flexDirection: "column", gap: 6 }}>
            {whyCredible.map((reason, i) => (
              <li key={i} style={{ fontSize: 12, color: C.inkSoft, lineHeight: 1.5 }}>
                {reason}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* Areas needing review */}
      {areasNeedingReview.length > 0 && (
        <Card>
          <SectionTitle>Areas for further review</SectionTitle>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {areasNeedingReview.map((area, i) => (
              <div key={i} style={{
                padding: "6px 10px",
                background: C.amberSoft,
                border: "1px solid #fde68a",
                borderRadius: 6,
                fontSize: 12, color: C.amber,
              }}>
                {area}
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Interview questions */}
      {suggestedQuestions.length > 0 && (
        <Card style={{ gridColumn: "1 / -1" }}>
          <SectionTitle>Suggested interview questions</SectionTitle>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {suggestedQuestions.map((q, i) => (
              <div key={i} style={{
                padding: "8px 12px",
                background: C.bg,
                border: `1px solid ${C.line}`,
                borderRadius: 7,
                fontSize: 12, color: C.inkSoft,
                lineHeight: 1.5,
              }}>
                <span style={{ color: C.muted, marginRight: 6, fontWeight: 700 }}>{i + 1}.</span>
                {q}
              </div>
            ))}
          </div>
          <p style={{ fontSize: 10, color: C.muted, margin: "10px 0 0", fontStyle: "italic" }}>
            Questions are AI-generated based on evidence gaps and skill coverage — review and adapt as needed.
          </p>
        </Card>
      )}
    </div>
  )
}

// ── Section: Protected Evidence Unlocked ─────────────────────────────────────
// Shown only when the student has approved access.  All content is mock /
// recruiter-safe: no private storage URLs, access tokens, raw transcripts,
// media_storage_path, debug metadata, admin notes, or localhost paths.

// ── Mock detail data (recruiter-safe, no raw URLs or tokens) ─────────────────

const RECORDING_META = [
  { duration: "4:32", date: "May 28, 2026" },
  { duration: "6:18", date: "May 26, 2026" },
  { duration: "2:47", date: "May 22, 2026" },
]

type RecordingDetail = {
  summary: string
  highlights: string[]
  skillsObserved: string[]
}

const RECORDING_DETAILS: RecordingDetail[] = [
  {
    summary: "Candidate demonstrated a browser workflow with evidence-backed machine learning interaction. Full raw recording remains protected and can be provided only through approved evidence access.",
    highlights: [
      "Live model prediction interface observed",
      "Input gesture and real-time inference output captured",
      "TensorFlow.js model loading confirmed in workflow",
    ],
    skillsObserved: ["TensorFlow.js", "Machine Learning", "React UI"],
  },
  {
    summary: "Candidate demonstrated interactive 3D rendering using WebGL, showing controlled geometry creation and real-time rendering pipeline.",
    highlights: [
      "Interactive 3D scene manipulation observed",
      "Shader loading and geometry rendering captured",
      "WebGL canvas interaction confirmed",
    ],
    skillsObserved: ["Three.js", "WebGL", "JavaScript"],
  },
  {
    summary: "Candidate interacted with an LLM chat interface showing evidence of prompt-aware UI integration and response handling.",
    highlights: [
      "Prompt submission and response chain observed",
      "Conversational UI interaction confirmed",
      "LLM integration workflow captured",
    ],
    skillsObserved: ["LLM Interfaces", "JavaScript", "Conversational UI"],
  },
]

type SkillDetail = {
  support: string
  reviewNote: string
  interviewQ: string
}

const SKILL_DETAILS: Record<string, SkillDetail> = {
  "AI / Machine Learning": {
    support: "Candidate demonstrated AI workflow and machine learning inference pipeline with live model interaction captured in workflow recordings.",
    reviewNote: "Ask about model selection, training approach, and evaluation methodology.",
    interviewQ: "Walk me through how your model inference works from input to output prediction.",
  },
  "JavaScript / Frontend": {
    support: "GitHub repository confirms JavaScript implementation; website workflow shows live frontend interaction with interactive elements.",
    reviewNote: "Limited evidence of production deployment or testing infrastructure.",
    interviewQ: "How would you improve the error handling and testing coverage in this project?",
  },
  "Data & Visualization": {
    support: "Website workflow and OCR evidence show data display and interaction patterns in a live environment.",
    reviewNote: "No dedicated data pipeline evidence beyond the UI layer — ask about data sources.",
    interviewQ: "Explain how data flows from your source through to the visualization layer.",
  },
}

const DEFENSE_DETAIL = {
  projectGoal: "Build an AI-backed portfolio system demonstrating skill evidence across multiple sources.",
  ownershipSignals: [
    "Described design decisions and iterative implementation changes",
    "Explained debugging process and specific obstacles overcome",
    "Referenced personal choices in model selection and data pipeline",
  ],
  technicalDepthSignals: [
    "Discussed training pipeline and data preprocessing rationale",
    "Explained model evaluation methodology and performance trade-offs",
    "Addressed system architecture and integration approach",
  ],
  limitationsNoted: "Acknowledged partial coverage of backend deployment; identified concrete areas for further evidence collection.",
}

// ── Shared notice footer ──────────────────────────────────────────────────────

function EvidencePreviewNotice() {
  return (
    <p style={{ fontSize: 10, color: C.muted, margin: "8px 0 0", fontStyle: "italic" }}>
      Detailed raw evidence remains controlled by the student.
    </p>
  )
}

// ── Recording card with inline "View summary" expander ────────────────────────

function MockRecordingCard({ title, index }: { title: string; index: number }) {
  const [open, setOpen] = useState(false)
  const m = RECORDING_META[index] ?? { duration: "3:00", date: "May 2026" }
  const detail: RecordingDetail = RECORDING_DETAILS[index] ?? {
    summary: "Candidate demonstrated a browser workflow and evidence-backed project interaction. Full raw recording remains protected and can be provided only through approved evidence access.",
    highlights: ["Workflow interaction captured", "Evidence-backed skill demonstration observed"],
    skillsObserved: [],
  }

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      {/* Card row */}
      <div style={{
        padding: "9px 12px",
        background: C.bg,
        border: `1px solid ${C.line}`,
        borderRadius: open ? "7px 7px 0 0" : 7,
        display: "flex",
        alignItems: "center",
        gap: 10,
      }}>
        <span style={{ fontSize: 16, flexShrink: 0 }}>🎬</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={{
            fontSize: 12, fontWeight: 600, color: C.ink,
            margin: "0 0 2px",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {title}
          </p>
          <p style={{ fontSize: 10, color: C.muted, margin: 0 }}>
            {m.duration} · Recorded {m.date}
          </p>
        </div>
        <span style={{
          fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 999,
          background: C.emeraldSoft, color: C.emerald, border: "1px solid #bbf7d0",
          flexShrink: 0,
        }}>
          Available
        </span>
        <button
          type="button"
          data-testid="view-recording-btn"
          onClick={() => setOpen((o) => !o)}
          style={{
            fontSize: 11, fontWeight: 600, color: C.indigo,
            background: C.indigoSoft, border: "1px solid #c7d2fe",
            borderRadius: 5, padding: "3px 9px", cursor: "pointer", flexShrink: 0,
          }}
        >
          {open ? "Hide summary" : "View summary"}
        </button>
      </div>

      {/* Inline detail panel */}
      {open && (
        <div
          data-testid="recording-detail-panel"
          style={{
            padding: "12px 14px",
            background: C.indigoSoft,
            border: "1px solid #c7d2fe",
            borderTop: "none",
            borderRadius: "0 0 7px 7px",
          }}
        >
          <p style={{
            fontSize: 11, fontWeight: 700, color: C.indigo, margin: "0 0 6px",
            textTransform: "uppercase" as const, letterSpacing: "0.07em",
          }}>
            Recruiter-safe evidence preview
          </p>
          <p style={{ fontSize: 12, color: C.inkSoft, margin: "0 0 10px", lineHeight: 1.6 }}>
            {detail.summary}
          </p>
          {detail.highlights.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <p style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const, margin: "0 0 4px" }}>
                Observed highlights
              </p>
              <ul style={{ margin: 0, padding: "0 0 0 14px" }}>
                {detail.highlights.map((h, i) => (
                  <li key={i} style={{ fontSize: 11, color: C.inkSoft, lineHeight: 1.5 }}>{h}</li>
                ))}
              </ul>
            </div>
          )}
          {detail.skillsObserved.length > 0 && (
            <div style={{ marginBottom: 4 }}>
              <p style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const, margin: "0 0 4px" }}>
                Skills observed
              </p>
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                {detail.skillsObserved.map((s) => (
                  <span key={s} style={{
                    fontSize: 10, fontWeight: 600, padding: "2px 7px", borderRadius: 4,
                    background: C.paper, color: C.indigo, border: "1px solid #c7d2fe",
                  }}>
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}
          <EvidencePreviewNotice />
        </div>
      )}
    </div>
  )
}

function UnlockedWorkflowSection({ links }: { links: Array<{ label: string; url: string }> }) {
  const titles = links.length > 0
    ? links.map((l) => l.label)
    : [
        "Browser ML Demo — Teachable Machine",
        "Three.js WebGL Geometry Demo",
        "HuggingChat LLM Interface",
      ]
  return (
    <div data-testid="unlocked-workflow-recordings">
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <span style={{
          fontSize: 11, fontWeight: 800, letterSpacing: "0.1em",
          textTransform: "uppercase" as const, color: C.muted,
        }}>
          Workflow recordings
        </span>
        <span style={{
          fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 999,
          background: C.emeraldSoft, color: C.emerald, border: "1px solid #bbf7d0",
        }}>
          {titles.length} available
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {titles.map((title, i) => (
          <MockRecordingCard key={i} title={title} index={i} />
        ))}
      </div>
    </div>
  )
}

// ── Project defense section with "View transcript summary" expander ───────────

function UnlockedProjectDefenseSection() {
  const [open, setOpen] = useState(false)
  return (
    <div data-testid="unlocked-project-defense">
      <div style={{
        fontSize: 11, fontWeight: 800, letterSpacing: "0.1em",
        textTransform: "uppercase" as const, color: C.muted, marginBottom: 10,
      }}>
        Project defense media / transcript
      </div>
      <div style={{
        background: C.bg,
        border: `1px solid ${C.line}`,
        borderRadius: 8,
        overflow: "hidden",
      }}>
        {/* Summary row */}
        <div style={{
          padding: "12px 14px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 10,
          flexWrap: "wrap",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 16, flexShrink: 0 }}>📋</span>
            <span style={{ fontSize: 12, fontWeight: 700, color: C.ink }}>
              Project defense transcript available
            </span>
          </div>
          <button
            type="button"
            data-testid="view-transcript-btn"
            onClick={() => setOpen((o) => !o)}
            style={{
              fontSize: 11, fontWeight: 600, color: C.indigo,
              background: C.indigoSoft, border: "1px solid #c7d2fe",
              borderRadius: 5, padding: "3px 9px", cursor: "pointer", flexShrink: 0,
            }}
          >
            {open ? "Hide summary" : "View transcript summary"}
          </button>
        </div>
        <p style={{ fontSize: 12, color: C.inkSoft, margin: 0, padding: "0 14px 12px", lineHeight: 1.6 }}>
          Candidate explained project goal, implementation approach, evidence sources, and limitations.
        </p>

        {/* Inline detail panel */}
        {open && (
          <div
            data-testid="defense-detail-panel"
            style={{
              padding: "14px",
              background: C.indigoSoft,
              borderTop: "1px solid #c7d2fe",
            }}
          >
            <p style={{
              fontSize: 11, fontWeight: 700, color: C.indigo, margin: "0 0 10px",
              textTransform: "uppercase" as const, letterSpacing: "0.07em",
            }}>
              Recruiter-safe evidence preview
            </p>

            <p style={{ fontSize: 12, fontWeight: 600, color: C.ink, margin: "0 0 4px" }}>
              Project goal
            </p>
            <p style={{ fontSize: 12, color: C.inkSoft, margin: "0 0 12px", lineHeight: 1.6 }}>
              {DEFENSE_DETAIL.projectGoal}
            </p>

            <p style={{ fontSize: 11, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const, margin: "0 0 4px" }}>
              Ownership signals
            </p>
            <ul style={{ margin: "0 0 10px", padding: "0 0 0 14px" }}>
              {DEFENSE_DETAIL.ownershipSignals.map((s, i) => (
                <li key={i} style={{ fontSize: 11, color: C.inkSoft, lineHeight: 1.5 }}>{s}</li>
              ))}
            </ul>

            <p style={{ fontSize: 11, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const, margin: "0 0 4px" }}>
              Technical depth
            </p>
            <ul style={{ margin: "0 0 10px", padding: "0 0 0 14px" }}>
              {DEFENSE_DETAIL.technicalDepthSignals.map((s, i) => (
                <li key={i} style={{ fontSize: 11, color: C.inkSoft, lineHeight: 1.5 }}>{s}</li>
              ))}
            </ul>

            <p style={{ fontSize: 11, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const, margin: "0 0 4px" }}>
              Limitations noted
            </p>
            <p style={{ fontSize: 11, color: C.inkSoft, margin: "0 0 4px", lineHeight: 1.5 }}>
              {DEFENSE_DETAIL.limitationsNoted}
            </p>
            <EvidencePreviewNotice />
          </div>
        )}
      </div>
    </div>
  )
}

// ── Skill evidence rows with per-row "View evidence" expander ─────────────────

function SkillEvidenceRow({ name, sources }: { name: string; sources: string[] }) {
  const [open, setOpen] = useState(false)
  const detail: SkillDetail = SKILL_DETAILS[name] ?? {
    support: `Evidence from ${sources.join(", ")} supports this skill claim.`,
    reviewNote: "Ask the candidate to walk through a specific implementation example.",
    interviewQ: `Describe a concrete challenge you solved using ${name}.`,
  }

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      {/* Row */}
      <div style={{
        padding: "8px 12px",
        background: C.bg,
        border: `1px solid ${C.line}`,
        borderRadius: open ? "7px 7px 0 0" : 7,
        display: "flex",
        alignItems: "center",
        gap: 10,
        flexWrap: "wrap",
      }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: C.ink, flex: "0 0 auto", minWidth: 160 }}>
          {name}
        </span>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", flex: 1 }}>
          {sources.map((src) => (
            <span key={src} style={{
              fontSize: 10, fontWeight: 600, padding: "2px 7px", borderRadius: 4,
              background: C.indigoSoft, color: C.indigo, border: "1px solid #c7d2fe",
            }}>
              {src}
            </span>
          ))}
        </div>
        <button
          type="button"
          data-testid="view-skill-evidence-btn"
          onClick={() => setOpen((o) => !o)}
          style={{
            fontSize: 11, fontWeight: 600, color: C.indigo,
            background: C.indigoSoft, border: "1px solid #c7d2fe",
            borderRadius: 5, padding: "3px 9px", cursor: "pointer", flexShrink: 0,
          }}
        >
          {open ? "Hide evidence" : "View evidence"}
        </button>
      </div>

      {/* Inline detail panel */}
      {open && (
        <div
          data-testid="skill-detail-panel"
          style={{
            padding: "12px 14px",
            background: C.indigoSoft,
            border: "1px solid #c7d2fe",
            borderTop: "none",
            borderRadius: "0 0 7px 7px",
          }}
        >
          <p style={{
            fontSize: 11, fontWeight: 700, color: C.indigo, margin: "0 0 8px",
            textTransform: "uppercase" as const, letterSpacing: "0.07em",
          }}>
            Recruiter-safe evidence preview
          </p>

          <div style={{ marginBottom: 8 }}>
            <p style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const, margin: "0 0 3px" }}>
              What supports this claim
            </p>
            <p style={{ fontSize: 11, color: C.inkSoft, margin: 0, lineHeight: 1.5 }}>
              {detail.support}
            </p>
          </div>

          <div style={{ marginBottom: 8 }}>
            <p style={{ fontSize: 10, fontWeight: 700, color: C.amber, textTransform: "uppercase" as const, margin: "0 0 3px" }}>
              What needs review
            </p>
            <p style={{ fontSize: 11, color: C.inkSoft, margin: 0, lineHeight: 1.5 }}>
              {detail.reviewNote}
            </p>
          </div>

          <div>
            <p style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const, margin: "0 0 3px" }}>
              Suggested interview question
            </p>
            <p style={{ fontSize: 11, color: C.inkSoft, margin: 0, lineHeight: 1.5, fontStyle: "italic" }}>
              &ldquo;{detail.interviewQ}&rdquo;
            </p>
          </div>
          <EvidencePreviewNotice />
        </div>
      )}
    </div>
  )
}

function UnlockedSkillEvidenceSection({ groups }: { groups: RecruiterSkillGroupResponse[] }) {
  type Row = { name: string; sources: string[] }
  const rows: Row[] = groups.length > 0
    ? groups.map((g) => ({ name: g.group_name, sources: g.source_labels }))
    : [
        { name: "AI / Machine Learning",  sources: ["Website Workflow", "GitHub", "AI Visual Analysis", "Documents"] },
        { name: "JavaScript / Frontend",  sources: ["GitHub", "Website Workflow", "OCR"] },
        { name: "Data & Visualization",   sources: ["Website Workflow", "OCR", "Documents"] },
      ]
  return (
    <div data-testid="unlocked-detailed-skill-evidence">
      <div style={{
        fontSize: 11, fontWeight: 800, letterSpacing: "0.1em",
        textTransform: "uppercase" as const, color: C.muted, marginBottom: 10,
      }}>
        Detailed skill evidence
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {rows.map((row) => (
          <SkillEvidenceRow key={row.name} name={row.name} sources={row.sources} />
        ))}
      </div>
    </div>
  )
}

function ProtectedEvidenceUnlockedSection({
  approvedTypes,
  view,
}: {
  approvedTypes: string[]
  view: RecruiterPassportViewResponse
}) {
  const normed = approvedTypes.map((k) => normaliseEvidenceKey(k))
  const hasWorkflow = normed.includes("workflow_recordings")
  const hasDefense  = normed.includes("project_defense_media")
  const hasSkills   = normed.includes("detailed_skill_evidence")

  if (!hasWorkflow && !hasDefense && !hasSkills) return null

  return (
    <Card data-testid="unlocked-evidence-section" style={{ border: `1px solid ${C.line}` }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
        <span style={{ fontSize: 16, flexShrink: 0 }}>🔓</span>
        <p style={{ fontWeight: 800, fontSize: 14, color: C.ink, margin: 0 }}>
          Protected evidence unlocked
        </p>
      </div>
      <p style={{ fontSize: 11, color: C.muted, margin: "0 0 18px", fontStyle: "italic" }}>
        Only evidence types approved by the student are visible.
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        {hasWorkflow && <UnlockedWorkflowSection links={view.public_project_links} />}
        {hasDefense  && <UnlockedProjectDefenseSection />}
        {hasSkills   && <UnlockedSkillEvidenceSection groups={view.skill_groups} />}
      </div>
    </Card>
  )
}

// ── Store lookup helper ───────────────────────────────────────────────────────
// Reads the mock store and returns the most-relevant access request for a given
// passport slug.  When the recruiter's email is known, their own request is
// preferred; otherwise all requests for the slug are considered.
// Approved status is always preferred over pending/denied/revoked to avoid
// showing stale pending requests when approval already exists.

function loadBestRequest(
  passportSlug: string,
  recruiterEmail?: string,
): EvidenceAccessRequest | null {
  const all = listStudentAccessRequests()
  const bySlug = all.filter((r) => r.passportSlug === passportSlug)
  if (bySlug.length === 0) return null

  // Narrow to recruiter's own requests when email is known; fall back to all.
  const byEmail = recruiterEmail
    ? bySlug.filter((r) => r.requesterEmail === recruiterEmail)
    : []
  const pool = byEmail.length > 0 ? byEmail : bySlug

  return [...pool].sort((a, b) => {
    // Approved bubbles to the top regardless of timestamp
    if (a.status === "approved" && b.status !== "approved") return -1
    if (b.status === "approved" && a.status !== "approved") return 1
    return new Date(b.requestedAt).getTime() - new Date(a.requestedAt).getTime()
  })[0] ?? null
}

// ── Main Component ────────────────────────────────────────────────────────────

export function RecruiterWorkPassportPreview({
  view,
  onRequestAccess,
  onRequestCreated,
  defaultRequester,
  onReset,
}: {
  view: RecruiterPassportViewResponse
  /** Legacy callback — if provided it is called after modal submits. */
  onRequestAccess?: () => void
  /** Called with full form data after the recruiter submits the request.
   *  Use this to persist the request to a mock store or backend API. */
  onRequestCreated?: (data: import("./EvidenceAccessRequestModal").EvidenceAccessFormData) => void
  /** Pre-fill recruiter fields in the modal. */
  defaultRequester?: { name?: string; email?: string; company?: string; role?: string }
  /** Dev-only reset handler. When provided, a reset button is shown inside
   *  the pending card so stale mock state can be cleared without DevTools. */
  onReset?: () => void
}) {
  const [showModal, setShowModal] = useState(false)
  const [accessRequest, setAccessRequest] = useState<EvidenceAccessRequest | null>(null)

  // Load the best access request for this passport from the mock store on mount.
  // Scoped to the recruiter's own email when known so their status is shown.
  useEffect(() => {
    const slug = view.public_slug
    if (!slug) return
    const best = loadBestRequest(slug, defaultRequester?.email)
    if (best) setAccessRequest(best)
  }, [view.public_slug, defaultRequester?.email])

  const handleModalSubmit = async () => {
    // Modal handles its own internal success state; we update parent state here.
  }

  const handleModalClose = (sections?: string[]) => {
    setShowModal(false)
    if (sections && sections.length > 0) {
      const slug = view.public_slug
      // Re-read store to pick up the just-created/upserted request.
      const found = slug ? loadBestRequest(slug, defaultRequester?.email) : null
      // Fallback to synthetic pending when store is unavailable (e.g. tests without onRequestCreated).
      setAccessRequest(found ?? {
        id: `local-${Date.now()}`,
        passportSlug: slug ?? null,
        requesterName: defaultRequester?.name ?? "",
        requesterEmail: defaultRequester?.email ?? "",
        requestedEvidenceTypes: sections,
        status: "pending",
        requestedAt: new Date().toISOString(),
      })
      onRequestAccess?.()
    }
  }

  // Clears local access-request state so the recruiter can send a new request
  // after a denial or revocation without needing a full page reset.
  const handleRequestAgain = () => setAccessRequest(null)

  // Dev-only reset: clears component state immediately so the CTA shows at once,
  // then calls the parent's onReset so the store is cleared and the component
  // is remounted (via key change in the page).  State is cleared here too so
  // there is no flash of the pending card while the remount is pending.
  const handleResetRequested = () => {
    setAccessRequest(null)
    setShowModal(false)
    onReset?.()
  }

  const SECTION_LABELS: Record<string, string> = {
    workflow_recordings: "Workflow recordings",
    project_defense: "Project defense media/transcript",
    project_defense_media: "Project defense media/transcript",
    documents: "Uploaded documents/reports",
    uploaded_documents: "Uploaded documents/reports",
    detailed_skill_evidence: "Detailed skill evidence",
  }

  return (
    <>
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {/* 1. Evidence score */}
        <EvidenceScoreSection
          score={view.overall_score}
          confidence={view.evidence_confidence}
          verificationStatus={view.verification_status}
          readinessLevel={view.readiness_level}
          proofSources={view.proof_sources}
        />

        {/* 2. Evidence-backed skills */}
        {(view.skill_groups.length > 0 ||
          view.verified_skills.length > 0 ||
          view.partially_verified_skills.length > 0 ||
          view.skills_needing_review.length > 0) && (
          <SkillGroupsSection
            groups={view.skill_groups}
            verified={view.verified_skills}
            partial={view.partially_verified_skills}
            needsReview={view.skills_needing_review}
          />
        )}

        {/* 3. Project links */}
        {view.public_project_links.length > 0 && (
          <Card>
            <SectionTitle>Project Evidence</SectionTitle>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {view.public_project_links.map((link, i) => (
                <a
                  key={i}
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    display: "flex", alignItems: "center", gap: 8,
                    padding: "8px 12px",
                    background: C.bg,
                    border: `1px solid ${C.line}`,
                    borderRadius: 7,
                    textDecoration: "none",
                  }}
                >
                  <span style={{ fontSize: 14 }}>🔗</span>
                  <span style={{ fontSize: 12, fontWeight: 600, color: C.indigo }}>
                    {link.label || link.url}
                  </span>
                </a>
              ))}
            </div>
          </Card>
        )}

        {/* 4. Decision helpers */}
        {(view.why_credible.length > 0 ||
          view.areas_needing_review.length > 0 ||
          view.suggested_interview_questions.length > 0) && (
          <DecisionHelpersSection
            whyCredible={view.why_credible}
            areasNeedingReview={view.areas_needing_review}
            suggestedQuestions={view.suggested_interview_questions}
          />
        )}

        {/* 5. Protected evidence CTA / status */}
        {view.has_protected_evidence && (
          accessRequest?.status === "approved" ? (
            <Card
              data-testid="access-approved-card"
              style={{ border: "1px solid #bbf7d0", background: "#f0fdf4" }}
            >
              <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                <span style={{ fontSize: 22, flexShrink: 0 }}>✅</span>
                <div style={{ flex: 1 }}>
                  <p style={{ fontWeight: 700, fontSize: 14, color: "#065f46", margin: "0 0 4px" }}>
                    Access approved
                  </p>
                  <p style={{ fontSize: 12, color: "#059669", margin: onReset ? "0 0 10px" : 0 }}>
                    Protected evidence available
                  </p>
                  {onReset && (
                    <button
                      type="button"
                      data-testid="approved-reset-btn"
                      onClick={handleResetRequested}
                      style={{
                        fontSize: 11, fontWeight: 600, color: "#065f46",
                        background: "transparent", border: "1px solid #86efac",
                        borderRadius: 5, padding: "3px 9px", cursor: "pointer",
                      }}
                    >
                      Reset mock access requests
                    </button>
                  )}
                </div>
              </div>
            </Card>
          ) : accessRequest?.status === "pending" ? (
            <Card
              data-testid="access-pending-card"
              style={{ border: "1px solid #c7d2fe", background: "#eef2ff" }}
            >
              <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                <span style={{ fontSize: 22, flexShrink: 0 }}>📬</span>
                <div style={{ flex: 1 }}>
                  <p style={{ fontWeight: 700, fontSize: 14, color: "#3730a3", margin: "0 0 4px" }}>
                    Request pending
                  </p>
                  <p style={{ fontSize: 12, color: "#4338ca", margin: "0 0 8px" }}>
                    Student approval required
                  </p>
                  {accessRequest.requestedEvidenceTypes.length > 0 && (
                    <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginBottom: onReset ? 10 : 0 }}>
                      <span style={{ fontSize: 11, color: "#6366f1", marginRight: 2 }}>Requested evidence:</span>
                      {accessRequest.requestedEvidenceTypes.map((s) => (
                        <span key={s} style={{
                          fontSize: 10, fontWeight: 600, padding: "2px 7px",
                          background: "#c7d2fe", color: "#3730a3", borderRadius: 4,
                        }}>
                          {SECTION_LABELS[s] ?? s}
                        </span>
                      ))}
                    </div>
                  )}
                  {onReset && (
                    <button
                      type="button"
                      data-testid="pending-reset-btn"
                      onClick={handleResetRequested}
                      style={{
                        fontSize: 11, fontWeight: 600, color: "#6366f1",
                        background: "transparent", border: "1px solid #a5b4fc",
                        borderRadius: 5, padding: "3px 9px", cursor: "pointer",
                      }}
                    >
                      Reset mock access requests
                    </button>
                  )}
                </div>
              </div>
            </Card>
          ) : accessRequest?.status === "denied" ? (
            <Card
              data-testid="access-denied-card"
              style={{ border: "1px solid #fecaca", background: "#fff1f2" }}
            >
              <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                <span style={{ fontSize: 22, flexShrink: 0 }}>🚫</span>
                <div style={{ flex: 1 }}>
                  <p style={{ fontWeight: 700, fontSize: 14, color: "#9f1239", margin: "0 0 4px" }}>
                    Access denied
                  </p>
                  <p style={{ fontSize: 12, color: "#e11d48", margin: "0 0 10px" }}>
                    The student has declined this evidence access request.
                  </p>
                  <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
                    <button
                      type="button"
                      data-testid="request-again-btn"
                      onClick={handleRequestAgain}
                      style={{
                        fontSize: 11, fontWeight: 600, color: "#9f1239",
                        background: "#fff1f2", border: "1px solid #fca5a5",
                        borderRadius: 5, padding: "4px 10px", cursor: "pointer",
                      }}
                    >
                      Send another request
                    </button>
                    {onReset && (
                      <button
                        type="button"
                        data-testid="denied-reset-btn"
                        onClick={handleResetRequested}
                        style={{
                          fontSize: 11, fontWeight: 600, color: "#92400e",
                          background: "transparent", border: "1px solid #fbbf24",
                          borderRadius: 5, padding: "4px 10px", cursor: "pointer",
                        }}
                      >
                        Reset mock access requests
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </Card>
          ) : accessRequest?.status === "revoked" ? (
            <Card
              data-testid="access-revoked-card"
              style={{ border: "1px solid #e2e8f0", background: "#f8fafc" }}
            >
              <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                <span style={{ fontSize: 22, flexShrink: 0 }}>🔓</span>
                <div style={{ flex: 1 }}>
                  <p style={{ fontWeight: 700, fontSize: 14, color: "#334155", margin: "0 0 4px" }}>
                    Access revoked
                  </p>
                  <p style={{ fontSize: 12, color: "#64748b", margin: "0 0 10px" }}>
                    The student has revoked previously granted access.
                  </p>
                  <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
                    <button
                      type="button"
                      data-testid="request-again-btn"
                      onClick={handleRequestAgain}
                      style={{
                        fontSize: 11, fontWeight: 600, color: "#334155",
                        background: "#f8fafc", border: `1px solid #cbd5e1`,
                        borderRadius: 5, padding: "4px 10px", cursor: "pointer",
                      }}
                    >
                      Send another request
                    </button>
                    {onReset && (
                      <button
                        type="button"
                        data-testid="revoked-reset-btn"
                        onClick={handleResetRequested}
                        style={{
                          fontSize: 11, fontWeight: 600, color: "#92400e",
                          background: "transparent", border: "1px solid #fbbf24",
                          borderRadius: 5, padding: "4px 10px", cursor: "pointer",
                        }}
                      >
                        Reset mock access requests
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </Card>
          ) : (
            /* No request yet — show CTA */
            <Card style={{
              background: "linear-gradient(135deg, #1e1b4b 0%, #312e81 100%)",
              border: "none",
            }}>
              <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
                <span style={{ fontSize: 28, flexShrink: 0 }}>🔒</span>
                <div style={{ flex: 1 }}>
                  <p style={{ fontWeight: 700, fontSize: 14, color: "#fff", margin: "0 0 4px" }}>
                    Protected Evidence Available
                  </p>
                  <p style={{ fontSize: 12, color: "#a5b4fc", margin: "0 0 10px", lineHeight: 1.5 }}>
                    Full workflow recordings, project defense analysis, and detailed skill evidence require student approval.
                  </p>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                    <button
                      type="button"
                      data-testid="request-access-btn"
                      onClick={() => setShowModal(true)}
                      style={{
                        background: "#4f46e5", color: "#fff",
                        border: "none", borderRadius: 7,
                        padding: "8px 16px", fontSize: 12, fontWeight: 700,
                        cursor: "pointer",
                      }}
                    >
                      Request Evidence Access
                    </button>
                    {onReset && (
                      <button
                        type="button"
                        data-testid="cta-reset-btn"
                        onClick={handleResetRequested}
                        style={{
                          fontSize: 11, fontWeight: 600, color: "#a5b4fc",
                          background: "transparent", border: "1px solid #4f46e5",
                          borderRadius: 5, padding: "7px 11px", cursor: "pointer",
                        }}
                      >
                        Reset mock access requests
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </Card>
          )
        )}

        {/* 6. Unlocked evidence sections — only when access is approved */}
        {view.has_protected_evidence && accessRequest?.status === "approved" && (
          <ProtectedEvidenceUnlockedSection
            approvedTypes={accessRequest.approvedEvidenceTypes ?? []}
            view={view}
          />
        )}

        {/* Disclosure */}
        <div style={{
          padding: "10px 14px",
          background: C.bg,
          border: `1px solid ${C.line}`,
          borderRadius: 8,
        }}>
          <p style={{ fontSize: 10, color: C.muted, margin: 0, lineHeight: 1.6 }}>
            <strong>Disclosure:</strong> {view.disclosure_note}
          </p>
        </div>
      </div>

      {/* Access request modal */}
      {showModal && (
        <ModalWrapper
          view={view}
          defaultRequester={defaultRequester}
          onSubmit={handleModalSubmit}
          onClose={handleModalClose}
          onRequestCreated={onRequestCreated}
        />
      )}
    </>
  )
}

/**
 * ModalWrapper keeps EvidenceAccessRequestModal in this file's render tree
 * and threads section data back to the parent on close-after-submit.
 */
function ModalWrapper({
  view,
  defaultRequester,
  onSubmit,
  onClose,
  onRequestCreated,
}: {
  view: RecruiterPassportViewResponse
  defaultRequester?: { name?: string; email?: string; company?: string; role?: string }
  onSubmit: () => Promise<void>
  onClose: (sections?: string[]) => void
  onRequestCreated?: (data: import("./EvidenceAccessRequestModal").EvidenceAccessFormData) => void
}) {
  const [submittedSections, setSubmittedSections] = useState<string[] | null>(null)

  return (
    <EvidenceAccessRequestModal
      candidateName={view.student_display_name}
      defaultRequester={{
        requester_name: defaultRequester?.name ?? "",
        requester_email: defaultRequester?.email ?? "",
        company: defaultRequester?.company ?? "",
        role: defaultRequester?.role ?? "",
      }}
      onSubmit={async (data) => {
        await onSubmit()
        setSubmittedSections(data.requested_sections)
        onRequestCreated?.(data)
      }}
      onClose={() => onClose(submittedSections ?? undefined)}
    />
  )
}

export default RecruiterWorkPassportPreview
