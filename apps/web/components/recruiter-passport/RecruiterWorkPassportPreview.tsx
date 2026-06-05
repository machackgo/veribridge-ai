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

function SkillGroupCard({
  group,
  accessApproved,
  onViewEvidence,
}: {
  group: RecruiterSkillGroupResponse
  accessApproved: boolean
  onViewEvidence?: () => void
}) {
  const [collapsed, setCollapsed] = useState(false)
  const bundle = getSkillBundle(group.group_name)

  const supportColor =
    bundle.supportStatus === "strongly supported" ? C.emerald
    : bundle.supportStatus === "partially supported" ? C.amber
    : C.muted
  const supportBg =
    bundle.supportStatus === "strongly supported" ? C.emeraldSoft
    : bundle.supportStatus === "partially supported" ? C.amberSoft
    : C.bg
  const supportBorder =
    bundle.supportStatus === "strongly supported" ? "#bbf7d0"
    : bundle.supportStatus === "partially supported" ? "#fde68a"
    : C.line

  // Build inline proof snippets: visual → github → transcript/doc
  type InlineSnippet = { type: string; text: string; isProtected: boolean; lockLabel?: string }
  const snippets: InlineSnippet[] = []

  const publicVisual = bundle.visualEvidence.find((f) => !f.isProtected)
  const firstProtectedVisual = bundle.visualEvidence.find((f) => f.isProtected)
  if (bundle.visualEvidence.length > 0) {
    if (publicVisual) {
      snippets.push({ type: "Visual", text: `${publicVisual.label}. ${publicVisual.observation}`, isProtected: false })
    } else if (firstProtectedVisual) {
      if (accessApproved) {
        snippets.push({ type: "Visual", text: `${firstProtectedVisual.label}. ${firstProtectedVisual.observation}`, isProtected: false })
      } else {
        snippets.push({ type: "Visual", text: "", isProtected: true, lockLabel: "Keyframe evidence" })
      }
    }
  }

  if (bundle.githubEvidence.length > 0) {
    const f = bundle.githubEvidence[0]
    const filename = f.path.split("/").pop() ?? f.path
    snippets.push({ type: "GitHub", text: `${filename} — ${f.reason}`, isProtected: false })
  }

  if (snippets.length < 3) {
    const firstT = bundle.transcriptEvidence[0]
    const firstDoc = bundle.documentEvidence.find((d) => !d.isProtected) ?? bundle.documentEvidence[0]
    if (firstT) {
      if (firstT.isProtected && !accessApproved) {
        snippets.push({ type: "Transcript", text: "", isProtected: true, lockLabel: "Transcript excerpt" })
      } else {
        const t = firstT.excerpt.length > 130 ? `${firstT.excerpt.substring(0, 130)}...` : firstT.excerpt
        snippets.push({ type: "Transcript", text: `"${t}"`, isProtected: false })
      }
    } else if (firstDoc) {
      if (firstDoc.isProtected && !accessApproved) {
        snippets.push({ type: "Document", text: "", isProtected: true, lockLabel: "Document evidence" })
      } else {
        const t = firstDoc.snippet.length > 130 ? `${firstDoc.snippet.substring(0, 130)}...` : firstDoc.snippet
        snippets.push({ type: "Document", text: `${firstDoc.title}: "${t}"`, isProtected: false })
      }
    }
  }

  const typeColors: Record<string, string> = {
    Visual: C.violet, GitHub: C.emerald, Transcript: C.sky, Document: C.amber,
  }
  const typeBgs: Record<string, string> = {
    Visual: C.violetSoft, GitHub: C.emeraldSoft, Transcript: C.skySoft, Document: C.amberSoft,
  }

  const hasProtectedEvidence = bundle.protectedEvidenceFlags.length > 0

  return (
    <div
      data-testid={`skill-group-card-${group.group_name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}
      style={{
        border: `1px solid ${confidenceBorder(group.confidence)}`,
        borderRadius: 10,
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div style={{
        padding: "12px 14px",
        background: confidenceBg(group.confidence),
        borderBottom: collapsed ? "none" : `1px solid ${confidenceBorder(group.confidence)}`,
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        gap: 8,
      }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontWeight: 700, fontSize: 13, color: C.ink }}>{group.group_name}</span>
            <ConfidenceBadge level={group.confidence} />
            <span style={{
              fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 999,
              background: supportBg, color: supportColor,
              border: `1px solid ${supportBorder}`,
              whiteSpace: "nowrap",
            }}>
              {bundle.supportStatus}
            </span>
          </div>
          {!collapsed && (
            <p
              data-testid="skill-group-evidence-summary"
              style={{ fontSize: 11, color: C.inkSoft, margin: "6px 0 0", lineHeight: 1.5 }}
            >
              {bundle.explanation}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          aria-label={collapsed ? "Expand skill evidence" : "Collapse skill evidence"}
          style={{
            fontSize: 10, fontWeight: 600, color: C.muted,
            background: "none", border: "none", cursor: "pointer",
            padding: "2px 6px", flexShrink: 0,
          }}
        >
          {collapsed ? "▼" : "▲"}
        </button>
      </div>

      {/* Expanded body */}
      {!collapsed && (
        <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 12 }}>

          {/* Source coverage */}
          <div data-testid="skill-group-source-coverage">
            <div style={{
              fontSize: 9, fontWeight: 800, letterSpacing: "0.08em",
              textTransform: "uppercase" as const, color: C.muted, marginBottom: 6,
            }}>
              Source coverage
            </div>
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(155px, 1fr))",
              gap: 6,
            }}>
              {bundle.sources.map((source) => (
                <SkillSourceCoverageCard key={source.key} source={source} />
              ))}
            </div>
          </div>

          {/* Inline proof snippets */}
          {snippets.length > 0 && (
            <div data-testid="skill-group-inline-snippets">
              <div style={{
                fontSize: 9, fontWeight: 800, letterSpacing: "0.08em",
                textTransform: "uppercase" as const, color: C.muted, marginBottom: 6,
              }}>
                Proof snippets
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                {snippets.map((snippet, i) =>
                  snippet.isProtected ? (
                    <div
                      key={i}
                      data-testid="skill-group-protected-lock"
                      style={{
                        padding: "7px 10px", borderRadius: 7,
                        background: C.indigoSoft, border: "1px solid #c7d2fe",
                        display: "flex", alignItems: "center", gap: 7,
                      }}
                    >
                      <span style={{ fontSize: 12, flexShrink: 0 }}>🔒</span>
                      <span style={{ fontSize: 11, color: C.indigo }}>
                        {snippet.lockLabel} — Protected evidence available. Request student approval to view.
                      </span>
                    </div>
                  ) : (
                    <div key={i} style={{
                      padding: "7px 10px", borderRadius: 7,
                      background: C.bg, border: `1px solid ${C.line}`,
                      display: "flex", alignItems: "flex-start", gap: 8,
                    }}>
                      <span style={{
                        fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 4,
                        background: typeBgs[snippet.type] ?? C.bg,
                        color: typeColors[snippet.type] ?? C.muted,
                        flexShrink: 0, marginTop: 1,
                      }}>
                        {snippet.type}
                      </span>
                      <p style={{ fontSize: 11, color: C.inkSoft, margin: 0, lineHeight: 1.5 }}>
                        {snippet.text}
                      </p>
                    </div>
                  )
                )}
              </div>
            </div>
          )}

          {/* Skills list */}
          <div>
            <div style={{
              fontSize: 9, fontWeight: 800, letterSpacing: "0.08em",
              textTransform: "uppercase" as const, color: C.muted, marginBottom: 5,
            }}>
              Skills in group
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              {group.skills.map((skill) => (
                <div key={skill.skill} style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: C.ink }}>{skill.skill}</span>
                  <span style={{ fontSize: 10, color: confidenceColor(skill.confidence), fontStyle: "italic" }}>
                    {skill.status_label}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Footer — row 1: compact action chips */}
          <div data-testid="skill-card-compact-actions" style={{
            paddingTop: 10,
            borderTop: `1px solid ${confidenceBorder(group.confidence)}`,
            display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8,
          }}>
            {bundle.githubEvidence.length > 0 && (
              <button
                type="button"
                data-testid="skill-card-github-proof-action"
                onClick={onViewEvidence}
                style={{ fontSize: 9, fontWeight: 700, padding: "2px 8px", borderRadius: 4, cursor: "pointer", color: C.emerald, background: C.emeraldSoft, border: "1px solid #bbf7d0" }}
              >
                ↗ GitHub proof
              </button>
            )}
            {bundle.visualEvidence.length > 0 && (bundle.visualEvidence[0].isProtected ? accessApproved : true) && (
              <button
                type="button"
                data-testid="skill-card-keyframe-action"
                onClick={onViewEvidence}
                style={{ fontSize: 9, fontWeight: 700, padding: "2px 8px", borderRadius: 4, cursor: "pointer", color: C.violet, background: C.violetSoft, border: "1px solid #ddd6fe" }}
              >
                View keyframe
              </button>
            )}
            {bundle.transcriptEvidence.length > 0 && (bundle.transcriptEvidence[0].isProtected ? accessApproved : true) && (
              <button
                type="button"
                data-testid="skill-card-transcript-action"
                onClick={onViewEvidence}
                style={{ fontSize: 9, fontWeight: 700, padding: "2px 8px", borderRadius: 4, cursor: "pointer", color: C.sky, background: C.skySoft, border: "1px solid #bae6fd" }}
              >
                View transcript
              </button>
            )}
            {bundle.liveApp?.isPublic && (
              <a
                href={bundle.liveApp.publicUrl}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="skill-card-live-app-action"
                style={{ fontSize: 9, fontWeight: 700, padding: "2px 8px", borderRadius: 4, cursor: "pointer", color: C.emerald, background: C.emeraldSoft, border: "1px solid #bbf7d0", textDecoration: "none" }}
              >
                ↗ Live app
              </a>
            )}
          </div>

          {/* Footer — row 2: approval status + view button */}
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            gap: 8, flexWrap: "wrap",
          }}>
            <div>
              {hasProtectedEvidence && !accessApproved && (
                <span style={{ fontSize: 10, color: C.indigo, fontStyle: "italic" }}>
                  Protected evidence available — request student approval
                </span>
              )}
              {hasProtectedEvidence && accessApproved && (
                <span style={{ fontSize: 10, color: C.emerald, fontWeight: 600 }}>
                  Protected evidence approved
                </span>
              )}
            </div>
            {onViewEvidence && (
              <button
                type="button"
                data-testid="view-skill-evidence-btn"
                onClick={onViewEvidence}
                style={{
                  fontSize: 11, fontWeight: 600, color: C.indigo,
                  background: C.indigoSoft, border: "1px solid #c7d2fe",
                  borderRadius: 5, padding: "3px 9px", cursor: "pointer", flexShrink: 0,
                }}
              >
                View skill evidence
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function SkillGroupsSection({
  groups,
  verified,
  partial,
  needsReview,
  onViewSkill,
  accessApproved,
}: {
  groups: RecruiterSkillGroupResponse[]
  verified: string[]
  partial: string[]
  needsReview: string[]
  onViewSkill?: (skillName: string) => void
  accessApproved: boolean
}) {
  const hasGroups = groups.length > 0
  return (
    <Card data-testid="evidence-backed-skills-section">
      <SectionTitle>Evidence-Backed Skills</SectionTitle>
      {hasGroups ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {groups.map((g) => (
            <SkillGroupCard
              key={g.group_name}
              group={g}
              accessApproved={accessApproved}
              onViewEvidence={onViewSkill ? () => onViewSkill(g.group_name) : undefined}
            />
          ))}
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

// Source-level evidence drill-down for skill evidence viewer tab.
const SKILL_SOURCE_DRILL: Record<string, Array<{ source: string; status: "supported" | "partial" }>> = {
  "AI / Machine Learning": [
    { source: "Website Workflow",   status: "supported" },
    { source: "GitHub",             status: "supported" },
    { source: "AI Visual Analysis", status: "partial"   },
    { source: "Documents",          status: "supported" },
  ],
  "JavaScript / Frontend": [
    { source: "GitHub",           status: "supported" },
    { source: "Website Workflow", status: "supported" },
    { source: "OCR",              status: "partial"   },
  ],
  "Data & Visualization": [
    { source: "Website Workflow", status: "supported" },
    { source: "OCR",              status: "partial"   },
    { source: "Documents",        status: "supported" },
  ],
}

// ── Skill-centric evidence data model ────────────────────────────────────────

type SkillSourceEvidence = {
  key: string
  label: string
  status: "supported" | "partial" | "missing" | "protected"
  score?: number
  reason: string
}

type SkillVisualFrame = {
  timestamp: string
  label: string
  observation: string
  ocr: string
  whyItSupports: string
  confidence: "high" | "medium" | "low"
  isProtected: boolean
}

type SkillGithubFile = {
  path: string
  reason: string
  skills: string[]
  confidence: "high" | "medium" | "low"
  isPublic: boolean
}

type SkillTranscriptExcerpt = {
  excerpt: string
  relevance: string
  ownershipSignal?: string
  technicalDepth?: string
  isProtected: boolean
}

type SkillDocumentSnippet = {
  title: string
  snippet: string
  relevance: string
  isProtected: boolean
}

export type SkillEvidenceBundle = {
  skillName: string
  confidence: "high" | "medium" | "low"
  supportStatus: "strongly supported" | "partially supported" | "needs review"
  explanation: string
  sources: SkillSourceEvidence[]
  visualEvidence: SkillVisualFrame[]
  githubEvidence: SkillGithubFile[]
  transcriptEvidence: SkillTranscriptExcerpt[]
  documentEvidence: SkillDocumentSnippet[]
  interviewQuestions: string[]
  protectedEvidenceFlags: string[]
  liveApp?: { label: string; isPublic: boolean; publicUrl?: string }
}

const SKILL_EVIDENCE_BUNDLES: Record<string, SkillEvidenceBundle> = {
  "AI / Machine Learning": {
    skillName: "AI / Machine Learning",
    confidence: "high",
    supportStatus: "strongly supported",
    explanation:
      "VeriBridge found this skill across workflow recording, GitHub, visual/OCR, transcript, and documents.",
    sources: [
      { key: "workflow",  label: "Workflow recording",     status: "supported", score: 88, reason: "Live model inference workflow observed in 3 recordings"              },
      { key: "keyframes", label: "Keyframes / screenshots", status: "partial",  score: 72, reason: "AI-related UI visible in 2 of 3 keyframe sets — raw frames protected" },
      { key: "ocr",       label: "OCR / visual reasoning",  status: "partial",  score: 65, reason: "Inference output text extracted; some frames inconclusive"           },
      { key: "github",    label: "GitHub code",             status: "supported", score: 91, reason: "ML pipeline, evaluator service, and proof engine files confirmed"   },
      { key: "defense",   label: "Project defense",         status: "supported", score: 84, reason: "Candidate explained model selection, training, and evaluation"      },
      { key: "documents", label: "Documents",               status: "supported", score: 79, reason: "Project report covers ML methodology and experimental results"      },
    ],
    visualEvidence: [
      {
        timestamp: "0:22",
        label: "Model inference UI visible",
        observation: "Live prediction interface with input and inference output visible in viewport",
        ocr: "Overall Score: 87 · High confidence · Evidence reviewed",
        whyItSupports: "Confirms hands-on interaction with an AI inference system",
        confidence: "high",
        isProtected: false,
      },
      {
        timestamp: "1:18",
        label: "Prediction/demo workflow observed",
        observation: "Full model prediction workflow captured — input submission and real-time output rendered",
        ocr: "Prediction: 94.2% confidence · model loaded",
        whyItSupports: "Shows end-to-end ML workflow, not just a static UI",
        confidence: "high",
        isProtected: true,
      },
      {
        timestamp: "2:05",
        label: "AI proof builder / evidence scoring visible",
        observation: "Evidence scoring interface for AI skill signals observed",
        ocr: "AI evidence score · Workflow: supported · GitHub: supported",
        whyItSupports: "Demonstrates working knowledge of AI evidence aggregation",
        confidence: "medium",
        isProtected: true,
      },
    ],
    githubEvidence: [
      {
        path: "apps/api/app/services/final_evidence_evaluator_service.py",
        reason: "Combines workflow, GitHub, OCR, transcript, and document signals into a final skill confidence score",
        skills: ["Python", "Machine Learning", "Evidence Aggregation"],
        confidence: "high",
        isPublic: false,
      },
      {
        path: "apps/api/app/services/extension_proof_workflow_analysis_service.py",
        reason: "Analyzes browser workflow signals to extract skill evidence from recorded sessions",
        skills: ["Python", "ML Signal Processing", "Workflow Analysis"],
        confidence: "high",
        isPublic: false,
      },
      {
        path: "apps/web/components/skill-proof/extension-proof-panel.tsx",
        reason: "Frontend component that displays proof workflow state and evidence source cards for skill validation",
        skills: ["TypeScript", "React", "Evidence UI"],
        confidence: "medium",
        isPublic: false,
      },
    ],
    transcriptEvidence: [
      {
        excerpt:
          "The main goal was to demonstrate machine learning in a browser environment. I chose TensorFlow.js because it allowed real-time inference without a backend server, which simplified deployment and made it easier to capture as evidence.",
        relevance: "Explains model choice and deployment rationale — ownership signal",
        ownershipSignal: "Candidate references specific design decisions with justification",
        technicalDepth: "Discusses inference architecture and deployment trade-offs",
        isProtected: true,
      },
    ],
    documentEvidence: [
      {
        title: "AI Engineering Project Report",
        snippet:
          "The model was trained on a custom dataset and evaluated using cross-validation. Training accuracy reached 94% on held-out test data.",
        relevance: "Confirms quantitative ML evaluation — matches GitHub evidence",
        isProtected: true,
      },
    ],
    interviewQuestions: [
      "Walk me through how the evidence scoring model combines workflow, GitHub, OCR, and transcript signals.",
      "Which parts of your AI pipeline are rule-based versus model-based, and why?",
      "How would you reduce false positives in your evidence scoring system?",
      "Describe your model evaluation methodology and how you chose your validation approach.",
      "How would you improve prediction accuracy given access to a larger training dataset?",
    ],
    protectedEvidenceFlags: ["keyframes", "transcript", "documents"],
    liveApp: { label: "AI proof builder app (local dev only)", isPublic: false },
  },

  "JavaScript / Frontend": {
    skillName: "JavaScript / Frontend",
    confidence: "high",
    supportStatus: "strongly supported",
    explanation:
      "VeriBridge found this skill confirmed in GitHub code and workflow recording.",
    sources: [
      { key: "github",    label: "GitHub code",             status: "supported", score: 88, reason: "React components and TypeScript modules confirmed across multiple files"      },
      { key: "workflow",  label: "Workflow recording",     status: "supported", score: 75, reason: "Live frontend UI interaction captured in workflow recordings"                 },
      { key: "ocr",       label: "OCR / visual reasoning",  status: "partial",  score: 60, reason: "UI text extracted from keyframes; component boundaries partially identified" },
      { key: "keyframes", label: "Keyframes / screenshots", status: "partial",  score: 58, reason: "UI interaction captured; some frames protected"                              },
      { key: "defense",   label: "Project defense",         status: "partial",  score: 65, reason: "Architecture discussed at high level; limited implementation depth"          },
      { key: "documents", label: "Documents",               status: "missing",        reason: "No frontend-specific documentation uploaded"                                     },
    ],
    visualEvidence: [
      {
        timestamp: "0:14",
        label: "React UI interaction observed",
        observation: "Dashboard component with interactive evidence cards visible; state changes captured",
        ocr: "Evidence Backed Skills · High confidence · Dashboard / Proof Builder",
        whyItSupports: "Confirms hands-on interaction with a React-based interface",
        confidence: "high",
        isProtected: false,
      },
      {
        timestamp: "1:32",
        label: "Dashboard/proof builder state changed",
        observation: "Proof builder component state update captured — evidence panel opened and closed",
        ocr: "Website Proof · Session active · Evidence being captured",
        whyItSupports: "Shows working knowledge of component state management in a live app",
        confidence: "high",
        isProtected: true,
      },
    ],
    githubEvidence: [
      {
        path: "apps/web/components/recruiter-passport/RecruiterWorkPassportPreview.tsx",
        reason: "Complex React component implementing evidence gating, modal state, and recruiter-safe rendering",
        skills: ["TypeScript", "React", "UI Architecture"],
        confidence: "high",
        isPublic: false,
      },
      {
        path: "apps/web/components/skill-proof/extension-proof-panel.tsx",
        reason: "Extension-based proof panel with workflow recording state and evidence source card rendering",
        skills: ["TypeScript", "React", "UI State"],
        confidence: "high",
        isPublic: false,
      },
      {
        path: "apps/web/src/app/recruiter/passport/page.tsx",
        reason: "Recruiter passport page with tab navigation, saved candidates, and comparison panel integration",
        skills: ["TypeScript", "Next.js", "React"],
        confidence: "medium",
        isPublic: false,
      },
    ],
    transcriptEvidence: [
      {
        excerpt:
          "I structured the React component tree to separate the recruiter and student views cleanly, so neither side has access to the other's data paths.",
        relevance: "Shows deliberate component architecture decision — ownership signal",
        ownershipSignal: "Candidate describes intentional structural choices",
        technicalDepth: "Covers component separation and data access patterns",
        isProtected: true,
      },
    ],
    documentEvidence: [],
    interviewQuestions: [
      "Walk me through the component architecture of your most complex UI and why you structured it that way.",
      "How do you handle state management across deeply nested React components?",
      "How would you improve the error handling and testing coverage in this project?",
      "Describe how you approach accessibility and performance in frontend work.",
    ],
    protectedEvidenceFlags: ["keyframes", "transcript"],
    liveApp: { label: "Frontend portfolio demo", isPublic: true, publicUrl: "https://example.com/frontend-demo" },
  },

  "Data & Visualization": {
    skillName: "Data & Visualization",
    confidence: "medium",
    supportStatus: "partially supported",
    explanation:
      "VeriBridge found this skill in workflow and OCR evidence. GitHub and transcript coverage is partial.",
    sources: [
      { key: "workflow",  label: "Workflow recording",     status: "supported", score: 72, reason: "Chart and dashboard interaction observed in workflow recordings"   },
      { key: "ocr",       label: "OCR / visual reasoning",  status: "partial",  score: 55, reason: "Chart/table text partially extracted from keyframes"              },
      { key: "documents", label: "Documents",               status: "partial",  score: 60, reason: "Data visualization mentioned in project report — not primary focus" },
      { key: "github",    label: "GitHub code",             status: "partial",  score: 50, reason: "D3 imports found; no dedicated data pipeline module detected"     },
      { key: "keyframes", label: "Keyframes / screenshots", status: "partial",  score: 48, reason: "Charts partially visible in protected keyframe set"               },
      { key: "defense",   label: "Project defense",         status: "missing",        reason: "Data visualization was not a focus of the defense discussion"         },
    ],
    visualEvidence: [
      {
        timestamp: "2:11",
        label: "Chart/table/dashboard output visible",
        observation: "Data visualization panel with chart output captured in viewport",
        ocr: "Chart · Data output · Dashboard view",
        whyItSupports: "Confirms live interaction with a data visualization interface",
        confidence: "medium",
        isProtected: false,
      },
    ],
    githubEvidence: [
      {
        path: "apps/web/components/recruiter-passport/CandidateComparison.tsx",
        reason: "Candidate comparison panel rendering tabular data and comparative skill metrics",
        skills: ["TypeScript", "React", "Data Display"],
        confidence: "medium",
        isPublic: false,
      },
    ],
    transcriptEvidence: [
      {
        excerpt:
          "Data visualization was part of the project but not the primary focus — I used D3 for the chart layer.",
        relevance: "Acknowledges limited depth in visualization work — honest self-assessment",
        isProtected: true,
      },
    ],
    documentEvidence: [
      {
        title: "AI Engineering Project Report",
        snippet:
          "Three.js WebGL rendering pipeline was designed for real-time performance, targeting 60fps on standard hardware.",
        relevance: "Partial match — visual rendering is related but not core data visualization",
        isProtected: false,
      },
    ],
    interviewQuestions: [
      "Explain how data flows from your source through to the visualization layer.",
      "What data pipeline libraries or tools have you used and why did you choose them?",
      "How would you handle large datasets that exceed browser memory limits in your visualization?",
    ],
    protectedEvidenceFlags: ["keyframes", "transcript"],
    liveApp: { label: "Evidence dashboard (local dev only)", isPublic: false },
  },

  "DevOps / Deployment": {
    skillName: "DevOps / Deployment",
    confidence: "low",
    supportStatus: "needs review",
    explanation:
      "VeriBridge found limited evidence of deployment skills. Coverage is document-only — no workflow or GitHub activity observed.",
    sources: [
      { key: "workflow",  label: "Workflow recording",     status: "missing", reason: "No deployment or CI/CD workflow captured in recordings"                   },
      { key: "github",    label: "GitHub code",             status: "missing", reason: "No deployment configuration, Dockerfiles, or CI pipelines detected"       },
      { key: "ocr",       label: "OCR / visual reasoning",  status: "missing", reason: "No deployment-related UI or terminal output observed"                    },
      { key: "keyframes", label: "Keyframes / screenshots", status: "missing", reason: "No deployment evidence in captured keyframes"                             },
      { key: "defense",   label: "Project defense",         status: "missing", reason: "Deployment not discussed in defense"                                      },
      { key: "documents", label: "Documents",               status: "partial",  score: 35, reason: "Deployment mentioned briefly in project report — no technical detail" },
    ],
    visualEvidence: [],
    githubEvidence: [],
    transcriptEvidence: [],
    documentEvidence: [
      {
        title: "AI Engineering Project Report",
        snippet: "Future work includes containerizing the application for deployment.",
        relevance: "Aspirational mention only — no implemented deployment evidence",
        isProtected: false,
      },
    ],
    interviewQuestions: [
      "Describe your experience with containerization tools such as Docker or Podman.",
      "How would you set up a CI/CD pipeline for this project?",
      "What deployment approach would you use and why, given the project constraints?",
    ],
    protectedEvidenceFlags: [],
  },
}

function getSkillBundle(skillName: string): SkillEvidenceBundle {
  return SKILL_EVIDENCE_BUNDLES[skillName] ?? {
    skillName,
    confidence: "medium",
    supportStatus: "partially supported",
    explanation: `VeriBridge analyzed evidence for ${skillName} across available sources.`,
    sources: [
      { key: "workflow",  label: "Workflow recording",     status: "partial", reason: "Workflow evidence reviewed"        },
      { key: "github",    label: "GitHub code",             status: "partial", reason: "GitHub evidence reviewed"         },
      { key: "ocr",       label: "OCR / visual reasoning",  status: "partial", reason: "Visual evidence reviewed"         },
      { key: "keyframes", label: "Keyframes / screenshots", status: "partial", reason: "Keyframe evidence reviewed"       },
      { key: "defense",   label: "Project defense",         status: "missing", reason: "Defense evidence not available"   },
      { key: "documents", label: "Documents",               status: "missing", reason: "Document evidence not available"  },
    ],
    visualEvidence: [],
    githubEvidence: [],
    transcriptEvidence: [],
    documentEvidence: [],
    interviewQuestions: [
      `Describe a concrete challenge you solved using ${skillName}.`,
      `How would you improve your ${skillName} skills going forward?`,
    ],
    protectedEvidenceFlags: [],
  }
}

// Safe transcript excerpt — not a raw dump, no private content.
const DEFENSE_TRANSCRIPT_EXCERPT =
  "The main goal was to demonstrate machine learning in a browser environment. " +
  "I chose TensorFlow.js because it allowed real-time inference without a backend server, " +
  "which simplified the deployment and made it easier to capture as evidence..."

// Document summary — metadata only, no storage path or raw file access.
const DOCUMENT_MOCK = {
  title: "AI Engineering Project Report",
  pages: 24,
  updatedDate: "May 2026",
  summary:
    "Comprehensive project documentation covering the design, implementation, and evaluation " +
    "of a browser-based machine learning system. Includes methodology rationale, experimental " +
    "results, and technical architecture overview.",
  supportedSkills: ["Machine Learning", "TensorFlow.js", "Data Visualization", "Technical Documentation"],
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

// ── Evidence Viewer — richer mock evidence artifacts ─────────────────────────
// All content is recruiter-safe: no private storage URLs, access_token,
// session_id, localhost, debug metadata, raw transcript dumps, or storage paths.

const KEYFRAME_CARDS = [
  {
    timestamp: "0:14",
    label: "Dashboard / Proof Builder",
    observation: "Evidence score card and proof source list visible in viewport",
    ocr: "Overall Score: 87 · High confidence · Evidence reviewed",
    confidence: "high",
  },
  {
    timestamp: "1:32",
    label: "Website Proof — recording active",
    observation: "Workflow recording controls observed; session indicator visible",
    ocr: "Website Proof · Session active · Evidence being captured",
    confidence: "high",
  },
  {
    timestamp: "2:48",
    label: "Access request workflow",
    observation: "Evidence access request UI and approval flow captured",
    ocr: "Request Evidence Access · Protected Evidence Available",
    confidence: "medium",
  },
]

const WORKFLOW_TIMELINE = [
  { time: "0:00–0:30", action: "Dashboard load",           page: "Proof Builder",   sources: "DOM · Keyframe",        note: "Initial page load; evidence score visible" },
  { time: "0:31–1:15", action: "Proof session started",    page: "Website Proof",   sources: "DOM · Keyframe · OCR",   note: "Recording interface activated" },
  { time: "1:16–2:10", action: "Evidence interaction",     page: "Evidence Cards",  sources: "Keyframe · Visual",      note: "Skill evidence cards reviewed" },
  { time: "2:11–3:05", action: "Project navigation",       page: "Recruiter View",  sources: "DOM · Keyframe",         note: "Recruiter passport view navigated" },
  { time: "3:06–4:32", action: "Access approval flow",     page: "Access Request",  sources: "DOM · Keyframe · OCR",   note: "Evidence access approval completed" },
]

const VISUAL_OCR_ROWS = [
  { type: "OCR"    as const, snippet: "Overall Score: 87 · High confidence · Evidence reviewed",        source: "Keyframe 0:14", confidence: "high"     as const, note: "Evidence score card text extracted" },
  { type: "Visual" as const, snippet: "Dashboard/Proof Builder UI visible — evidence source cards active", source: "Keyframe 0:22", confidence: "high"  as const, note: "Proof builder confirmed in active state" },
  { type: "OCR"    as const, snippet: "Website Proof · Session active · Evidence being captured",        source: "Keyframe 1:32", confidence: "high"     as const, note: "Recording control UI text captured" },
  { type: "Visual" as const, snippet: "Evidence score card — 87/100 score present in viewport",          source: "Keyframe 1:45", confidence: "medium"   as const, note: "Score display confirmed via visual reasoning" },
  { type: "OCR"    as const, snippet: "Request Evidence Access · Protected Evidence Available",           source: "Keyframe 2:48", confidence: "medium"   as const, note: "Access request workflow UI captured" },
  { type: "Safety" as const, snippet: "No sensitive data, private URLs, or secrets detected in frames",  source: "All frames",    confidence: "verified" as const, note: "Privacy scan: no unsafe content detected" },
]

const GITHUB_EVIDENCE = {
  repo: "veribridge-ai (private — recruiter-safe summary only)",
  branch: "main",
  commitRef: "evidence-verified",
  detectedStack: ["TypeScript", "React", "Next.js", "Python", "FastAPI", "PostgreSQL"],
  files: [
    {
      path: "apps/web/components/recruiter-passport/RecruiterWorkPassportPreview.tsx",
      summary: "Recruiter preview component — gates protected evidence behind student-approved access. Evidence viewer modal wired to approved evidence types.",
      skills: ["TypeScript", "React", "Evidence Gating", "UI Architecture"],
      confidence: "high",
    },
    {
      path: "apps/web/src/lib/mock-evidence-access-store.ts",
      summary: "Mock evidence access store — manages recruiter request lifecycle (pending/approved/denied/revoked) with canonical slug-based isolation.",
      skills: ["TypeScript", "State Management", "Privacy Controls"],
      confidence: "high",
    },
    {
      path: "apps/api/app/services/final_evidence_evaluator_service.py",
      summary: "Backend evaluator combines workflow, GitHub, document, and project defense evidence to compute overall evidence score and confidence level.",
      skills: ["Python", "ML Evaluation", "Evidence Aggregation"],
      confidence: "high",
    },
    {
      path: "apps/web/components/skill-proof/extension-proof-panel.tsx",
      summary: "Extension-based Website Proof panel — handles workflow recording state and evidence source card display for student submission flow.",
      skills: ["TypeScript", "React", "UI State"],
      confidence: "medium",
    },
  ] as Array<{ path: string; summary: string; skills: string[]; confidence: string }>,
  codeSignals: [
    "Evidence gating implemented — no private URLs exposed to recruiter view",
    "TypeScript strict types ensure safe field access throughout proof pipeline",
    "React architecture separates student and recruiter facing views cleanly",
    "Python backend aggregates multiple evidence sources with weighted scoring",
  ],
  riskFlags: ["No critical risk flags detected in analyzed modules"],
}

type SkillSourceStatus = "supported" | "partial" | "missing" | "review"
type SkillMapRow = {
  skill: string
  workflow: { status: SkillSourceStatus; note: string }
  github:   { status: SkillSourceStatus; note: string }
  visual:   { status: SkillSourceStatus; note: string }
  defense:  { status: SkillSourceStatus; note: string }
  documents: { status: SkillSourceStatus; note: string }
}

const SKILL_MAP_DATA: SkillMapRow[] = [
  {
    skill: "Machine Learning",
    workflow:  { status: "supported", note: "Inference workflow observed" },
    github:    { status: "supported", note: "ML pipeline detected" },
    visual:    { status: "partial",   note: "UI elements visible" },
    defense:   { status: "supported", note: "Pipeline explained" },
    documents: { status: "supported", note: "Training docs present" },
  },
  {
    skill: "React / Frontend",
    workflow:  { status: "supported", note: "UI interactions captured" },
    github:    { status: "supported", note: "React components found" },
    visual:    { status: "partial",   note: "UI text extracted" },
    defense:   { status: "supported", note: "Architecture discussed" },
    documents: { status: "missing",   note: "Not documented" },
  },
  {
    skill: "TensorFlow.js",
    workflow:  { status: "supported", note: "Live inference confirmed" },
    github:    { status: "supported", note: "TF.js imports found" },
    visual:    { status: "partial",   note: "Prediction UI visible" },
    defense:   { status: "supported", note: "Model loading explained" },
    documents: { status: "partial",   note: "Brief mention" },
  },
  {
    skill: "Three.js / WebGL",
    workflow:  { status: "supported", note: "3D rendering observed" },
    github:    { status: "supported", note: "WebGL scene code found" },
    visual:    { status: "supported", note: "3D canvas confirmed" },
    defense:   { status: "supported", note: "Pipeline explained" },
    documents: { status: "missing",   note: "Not documented" },
  },
  {
    skill: "Data Visualization",
    workflow:  { status: "partial",   note: "Charts briefly observed" },
    github:    { status: "partial",   note: "D3 imports found" },
    visual:    { status: "partial",   note: "Chart UI extracted" },
    defense:   { status: "review",    note: "Not deeply covered" },
    documents: { status: "partial",   note: "Mentioned in report" },
  },
]

// ── Evidence Viewer Modal (6 tabs) ────────────────────────────────────────────
// Tabs gated by approved evidence type:
//   workflow_recordings    → Workflow Recording + Visual/OCR
//   detailed_skill_evidence → GitHub Code + Skill Evidence Map
//   project_defense_media  → Project Defense
//   uploaded_documents     → Documents

function ViewerWorkflowTab({ links }: { links: Array<{ label: string; url: string }> }) {
  const titles = links.length > 0
    ? links.map((l) => l.label)
    : [
        "Browser ML Demo — Teachable Machine",
        "Three.js WebGL Geometry Demo",
        "HuggingChat LLM Interface",
      ]
  return (
    <div data-testid="viewer-workflow-tab">
      <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        {titles.map((title, i) => {
          const m = RECORDING_META[i] ?? { duration: "3:00", date: "May 2026" }
          const detail: RecordingDetail = RECORDING_DETAILS[i] ?? {
            summary: "Candidate demonstrated a browser workflow and evidence-backed project interaction.",
            highlights: ["Workflow interaction captured"],
            skillsObserved: [],
          }
          return (
            <div key={i} style={{ border: `1px solid ${C.line}`, borderRadius: 8, overflow: "hidden" }}>
              {/* Recording header */}
              <div style={{ padding: "10px 14px", background: C.bg, display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ fontSize: 16, flexShrink: 0 }}>🎬</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ fontSize: 13, fontWeight: 600, color: C.ink, margin: 0 }}>{title}</p>
                  <p style={{ fontSize: 11, color: C.muted, margin: 0 }}>{m.duration} · Recorded {m.date}</p>
                </div>
                <span style={{
                  fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 999,
                  background: C.emeraldSoft, color: C.emerald, border: "1px solid #bbf7d0",
                }}>
                  Analyzed
                </span>
              </div>

              {/* Keyframe strip — realistic placeholder cards */}
              <div style={{ background: "#1e293b", padding: "10px 14px" }}>
                <p style={{ fontSize: 9, fontWeight: 600, color: "#64748b", textTransform: "uppercase" as const, letterSpacing: "0.08em", margin: "0 0 6px" }}>
                  Keyframe snapshots
                </p>
                <div style={{ display: "flex", gap: 6, overflowX: "auto" }}>
                  {KEYFRAME_CARDS.map((kf) => (
                    <div key={kf.timestamp} style={{
                      flexShrink: 0, width: 160,
                      background: "#334155", borderRadius: 6,
                      padding: "8px 10px",
                      border: "1px solid #475569",
                    }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                        <span style={{ fontSize: 9, fontWeight: 700, color: "#94a3b8" }}>{kf.timestamp}</span>
                        <span style={{
                          fontSize: 8, fontWeight: 700, padding: "1px 5px", borderRadius: 999,
                          background: kf.confidence === "high" ? "#166534" : "#92400e",
                          color: "#fff",
                        }}>
                          {kf.confidence}
                        </span>
                      </div>
                      <p style={{ fontSize: 10, fontWeight: 600, color: "#e2e8f0", margin: "0 0 3px", lineHeight: 1.3 }}>{kf.label}</p>
                      <p style={{ fontSize: 9, color: "#94a3b8", margin: 0, lineHeight: 1.4 }}>{kf.observation}</p>
                      {kf.ocr && (
                        <p style={{ fontSize: 8, color: "#64748b", margin: "4px 0 0", fontStyle: "italic", lineHeight: 1.3 }}>
                          OCR: {kf.ocr}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
                <p style={{ fontSize: 9, color: "#475569", margin: "6px 0 0", fontStyle: "italic" }}>
                  Raw recording access controlled by student — keyframe summaries shown only.
                </p>
              </div>

              {/* Summary */}
              <div style={{ padding: "10px 14px" }}>
                <p style={{ fontSize: 12, color: C.inkSoft, margin: "0 0 6px", lineHeight: 1.6 }}>{detail.summary}</p>
                {detail.highlights.length > 0 && (
                  <ul style={{ margin: 0, padding: "0 0 0 14px" }}>
                    {detail.highlights.map((h, j) => (
                      <li key={j} style={{ fontSize: 11, color: C.inkSoft, lineHeight: 1.5 }}>{h}</li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )
        })}

        {/* Workflow timeline table */}
        <div>
          <p style={{
            fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const,
            letterSpacing: "0.07em", margin: "0 0 8px",
          }}>
            Workflow timeline
          </p>
          <div style={{ border: `1px solid ${C.line}`, borderRadius: 8, overflow: "hidden" }}>
            {/* Table header */}
            <div style={{
              display: "grid", gridTemplateColumns: "80px 1fr 1fr 1fr",
              background: C.bg, padding: "6px 12px", gap: 8,
            }}>
              {["Time", "Action / Page", "Evidence Sources", "Note"].map((h) => (
                <span key={h} style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const }}>
                  {h}
                </span>
              ))}
            </div>
            {WORKFLOW_TIMELINE.map((row, idx) => (
              <div key={idx} style={{
                display: "grid", gridTemplateColumns: "80px 1fr 1fr 1fr",
                padding: "7px 12px", gap: 8,
                background: idx % 2 === 0 ? C.paper : C.bg,
                borderTop: `1px solid ${C.line}`,
              }}>
                <span style={{ fontSize: 10, fontWeight: 700, color: C.indigo }}>{row.time}</span>
                <div>
                  <p style={{ fontSize: 11, fontWeight: 600, color: C.ink, margin: "0 0 1px" }}>{row.action}</p>
                  <p style={{ fontSize: 10, color: C.muted, margin: 0 }}>{row.page}</p>
                </div>
                <span style={{ fontSize: 10, color: C.inkSoft }}>{row.sources}</span>
                <span style={{ fontSize: 10, color: C.inkSoft, lineHeight: 1.5 }}>{row.note}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function ViewerVisualOcrTab() {
  return (
    <div data-testid="viewer-visual-ocr-tab">
      <p style={{
        fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const,
        letterSpacing: "0.07em", margin: "0 0 10px",
      }}>
        Visual analysis &amp; OCR extractions
      </p>
      <div style={{ border: `1px solid ${C.line}`, borderRadius: 8, overflow: "hidden" }}>
        {/* Header row */}
        <div style={{
          display: "grid", gridTemplateColumns: "60px 1fr 80px 70px",
          background: C.bg, padding: "6px 12px", gap: 8, borderBottom: `1px solid ${C.line}`,
        }}>
          {["Type", "Snippet / Observation", "Source", "Confidence"].map((h) => (
            <span key={h} style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const }}>{h}</span>
          ))}
        </div>
        {VISUAL_OCR_ROWS.map((row, idx) => {
          const typeColor = row.type === "OCR" ? C.sky : row.type === "Visual" ? C.indigo : C.emerald
          const typeBg   = row.type === "OCR" ? C.skySoft : row.type === "Visual" ? C.indigoSoft : C.emeraldSoft
          const confColor = row.confidence === "high" ? C.emerald : row.confidence === "medium" ? C.amber : C.emerald
          return (
            <div key={idx} style={{
              display: "grid", gridTemplateColumns: "60px 1fr 80px 70px",
              padding: "8px 12px", gap: 8,
              background: idx % 2 === 0 ? C.paper : C.bg,
              borderTop: `1px solid ${C.line}`,
            }}>
              <span style={{
                fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 4,
                background: typeBg, color: typeColor,
                alignSelf: "flex-start",
              }}>
                {row.type}
              </span>
              <div>
                <p style={{ fontSize: 11, color: C.ink, margin: "0 0 2px", fontWeight: 500 }}>{row.snippet}</p>
                <p style={{ fontSize: 10, color: C.muted, margin: 0, fontStyle: "italic" }}>{row.note}</p>
              </div>
              <span style={{ fontSize: 10, color: C.muted }}>{row.source}</span>
              <span style={{ fontSize: 10, fontWeight: 700, color: confColor }}>{row.confidence}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ViewerGithubTab() {
  return (
    <div data-testid="viewer-github-tab">
      {/* Repo overview */}
      <div style={{
        padding: "10px 14px", background: C.bg, border: `1px solid ${C.line}`,
        borderRadius: 8, marginBottom: 14,
        display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
      }}>
        <span style={{ fontSize: 18 }}>💻</span>
        <div style={{ flex: 1 }}>
          <p style={{ fontSize: 13, fontWeight: 700, color: C.ink, margin: 0 }}>{GITHUB_EVIDENCE.repo}</p>
          <p style={{ fontSize: 11, color: C.muted, margin: 0 }}>
            Branch: {GITHUB_EVIDENCE.branch} · Commit: {GITHUB_EVIDENCE.commitRef}
          </p>
        </div>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {GITHUB_EVIDENCE.detectedStack.map((s) => (
            <span key={s} style={{
              fontSize: 9, fontWeight: 600, padding: "2px 6px", borderRadius: 4,
              background: C.indigoSoft, color: C.indigo, border: "1px solid #c7d2fe",
            }}>
              {s}
            </span>
          ))}
        </div>
      </div>

      {/* Evidence files */}
      <p style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const, margin: "0 0 8px" }}>
        Evidence files / modules
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 14 }}>
        {GITHUB_EVIDENCE.files.map((f) => (
          <div key={f.path} style={{ border: `1px solid ${C.line}`, borderRadius: 7, overflow: "hidden" }}>
            <div style={{ padding: "7px 12px", background: C.bg, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
              <code style={{ fontSize: 10, color: C.indigo, fontFamily: "monospace" }}>{f.path}</code>
              <span style={{
                fontSize: 9, fontWeight: 700, padding: "1px 6px", borderRadius: 999,
                background: f.confidence === "high" ? C.emeraldSoft : C.amberSoft,
                color: f.confidence === "high" ? C.emerald : C.amber,
                border: `1px solid ${f.confidence === "high" ? "#bbf7d0" : "#fde68a"}`,
                flexShrink: 0,
              }}>
                {f.confidence} confidence
              </span>
            </div>
            <div style={{ padding: "7px 12px", borderTop: `1px solid ${C.line}` }}>
              <p style={{ fontSize: 11, color: C.inkSoft, margin: "0 0 5px", lineHeight: 1.5 }}>{f.summary}</p>
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                {f.skills.map((sk) => (
                  <span key={sk} style={{
                    fontSize: 9, fontWeight: 600, padding: "1px 6px", borderRadius: 4,
                    background: C.indigoSoft, color: C.indigo, border: "1px solid #c7d2fe",
                  }}>
                    {sk}
                  </span>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Code signals + risk */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <div style={{ padding: "10px 12px", background: C.emeraldSoft, border: "1px solid #bbf7d0", borderRadius: 7 }}>
          <p style={{ fontSize: 10, fontWeight: 700, color: C.emerald, textTransform: "uppercase" as const, margin: "0 0 6px" }}>Code signals</p>
          {GITHUB_EVIDENCE.codeSignals.map((s, i) => (
            <p key={i} style={{ fontSize: 11, color: "#065f46", margin: i === 0 ? 0 : "3px 0 0", lineHeight: 1.4 }}>• {s}</p>
          ))}
        </div>
        <div style={{ padding: "10px 12px", background: C.amberSoft, border: "1px solid #fde68a", borderRadius: 7 }}>
          <p style={{ fontSize: 10, fontWeight: 700, color: C.amber, textTransform: "uppercase" as const, margin: "0 0 6px" }}>Risk flags</p>
          {GITHUB_EVIDENCE.riskFlags.map((s, i) => (
            <p key={i} style={{ fontSize: 11, color: "#92400e", margin: i === 0 ? 0 : "3px 0 0", lineHeight: 1.4 }}>• {s}</p>
          ))}
        </div>
      </div>
    </div>
  )
}

function ViewerProjectDefenseTab() {
  return (
    <div data-testid="viewer-defense-tab">
      {/* Safe excerpt */}
      <div style={{
        padding: "12px 14px", background: C.bg, border: `1px solid ${C.line}`,
        borderRadius: 8, marginBottom: 14,
      }}>
        <p style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const, margin: "0 0 6px" }}>
          Transcript excerpt
        </p>
        <blockquote style={{
          fontSize: 12, color: C.inkSoft, lineHeight: 1.7,
          margin: 0, padding: "0 0 0 12px",
          borderLeft: `3px solid ${C.indigo}`, fontStyle: "italic",
        }}>
          &ldquo;{DEFENSE_TRANSCRIPT_EXCERPT}&rdquo;
        </blockquote>
        <p style={{ fontSize: 10, color: C.muted, margin: "8px 0 0", fontStyle: "italic" }}>
          Safe excerpt — full unedited transcript is not exposed here.
        </p>
      </div>

      {/* Structured signals */}
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div>
          <p style={{ fontSize: 12, fontWeight: 700, color: C.ink, margin: "0 0 4px" }}>Project goal</p>
          <p style={{ fontSize: 12, color: C.inkSoft, margin: 0, lineHeight: 1.6 }}>{DEFENSE_DETAIL.projectGoal}</p>
        </div>
        <div>
          <p style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const, margin: "0 0 4px" }}>Ownership signals</p>
          <ul style={{ margin: 0, padding: "0 0 0 14px" }}>
            {DEFENSE_DETAIL.ownershipSignals.map((s, i) => (
              <li key={i} style={{ fontSize: 11, color: C.inkSoft, lineHeight: 1.5 }}>{s}</li>
            ))}
          </ul>
        </div>
        <div>
          <p style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const, margin: "0 0 4px" }}>Technical depth</p>
          <ul style={{ margin: 0, padding: "0 0 0 14px" }}>
            {DEFENSE_DETAIL.technicalDepthSignals.map((s, i) => (
              <li key={i} style={{ fontSize: 11, color: C.inkSoft, lineHeight: 1.5 }}>{s}</li>
            ))}
          </ul>
        </div>
        <div>
          <p style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const, margin: "0 0 4px" }}>Limitations noted</p>
          <p style={{ fontSize: 11, color: C.inkSoft, margin: 0, lineHeight: 1.5 }}>{DEFENSE_DETAIL.limitationsNoted}</p>
        </div>
        {/* Consistency checks */}
        <div style={{ padding: "10px 12px", background: C.emeraldSoft, border: "1px solid #bbf7d0", borderRadius: 7 }}>
          <p style={{ fontSize: 10, fontWeight: 700, color: C.emerald, textTransform: "uppercase" as const, margin: "0 0 4px" }}>
            Consistency checks
          </p>
          <p style={{ fontSize: 11, color: "#065f46", margin: 0, lineHeight: 1.5 }}>
            Defense content is consistent with workflow recordings and GitHub evidence. No significant contradictions detected.
          </p>
        </div>
        <div>
          <p style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const, margin: "0 0 4px" }}>Suggested recruiter questions</p>
          <ul style={{ margin: 0, padding: "0 0 0 14px" }}>
            <li style={{ fontSize: 11, color: C.inkSoft, lineHeight: 1.5 }}>Walk through the most technically challenging part of this project and how you solved it.</li>
            <li style={{ fontSize: 11, color: C.inkSoft, lineHeight: 1.5 }}>How would you improve or scale this system if given more time?</li>
            <li style={{ fontSize: 11, color: C.inkSoft, lineHeight: 1.5 }}>Which parts of the pipeline did you implement yourself versus use a library for?</li>
          </ul>
        </div>
      </div>
    </div>
  )
}

function ViewerDocumentsTab() {
  return (
    <div data-testid="viewer-documents-tab">
      <div style={{ border: `1px solid ${C.line}`, borderRadius: 8, overflow: "hidden" }}>
        <div style={{ padding: "10px 14px", background: C.bg, display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 16, flexShrink: 0 }}>📄</span>
          <div style={{ flex: 1 }}>
            <p style={{ fontSize: 13, fontWeight: 600, color: C.ink, margin: 0 }}>{DOCUMENT_MOCK.title}</p>
            <p style={{ fontSize: 11, color: C.muted, margin: 0 }}>{DOCUMENT_MOCK.pages} pages · Updated {DOCUMENT_MOCK.updatedDate}</p>
          </div>
          <span style={{
            fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 999,
            background: C.emeraldSoft, color: C.emerald, border: "1px solid #bbf7d0",
          }}>
            Approved
          </span>
        </div>
        <div style={{ padding: "12px 14px", borderTop: `1px solid ${C.line}` }}>
          <p style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const, margin: "0 0 4px" }}>Document summary</p>
          <p style={{ fontSize: 12, color: C.inkSoft, margin: "0 0 12px", lineHeight: 1.6 }}>{DOCUMENT_MOCK.summary}</p>
          <p style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const, margin: "0 0 6px" }}>Skills supported</p>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 10 }}>
            {DOCUMENT_MOCK.supportedSkills.map((s) => (
              <span key={s} style={{
                fontSize: 10, fontWeight: 600, padding: "2px 7px", borderRadius: 4,
                background: C.indigoSoft, color: C.indigo, border: "1px solid #c7d2fe",
              }}>
                {s}
              </span>
            ))}
          </div>
          {/* Evidence snippets */}
          <p style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const, margin: "0 0 5px" }}>Relevant evidence snippets</p>
          <p style={{ fontSize: 11, color: C.inkSoft, margin: "0 0 4px", lineHeight: 1.5, fontStyle: "italic" }}>
            &ldquo;The TensorFlow.js model was trained on a custom dataset and evaluated using cross-validation. Training accuracy reached 94% on held-out test data.&rdquo;
          </p>
          <p style={{ fontSize: 11, color: C.inkSoft, margin: "0 0 10px", lineHeight: 1.5, fontStyle: "italic" }}>
            &ldquo;Three.js WebGL rendering pipeline was designed for real-time performance, targeting 60fps on standard hardware.&rdquo;
          </p>
          <div style={{ padding: "8px 10px", background: C.amberSoft, border: "1px solid #fde68a", borderRadius: 6 }}>
            <p style={{ fontSize: 10, fontWeight: 700, color: C.amber, textTransform: "uppercase" as const, margin: "0 0 3px" }}>Mismatch check</p>
            <p style={{ fontSize: 11, color: "#92400e", margin: 0 }}>No significant mismatches detected. Document evidence is consistent with GitHub and workflow sources.</p>
          </div>
          <p style={{ fontSize: 10, color: C.muted, margin: "10px 0 0", fontStyle: "italic" }}>
            Raw document file is not exposed here. Summary derived from approved evidence.
          </p>
        </div>
      </div>
    </div>
  )
}

function ViewerSkillMapTab({ groups }: { groups: RecruiterSkillGroupResponse[] }) {
  type Col = { key: keyof Omit<SkillMapRow, "skill">; label: string }
  const cols: Col[] = [
    { key: "workflow",  label: "Workflow" },
    { key: "github",    label: "GitHub"   },
    { key: "visual",    label: "Visual"   },
    { key: "defense",   label: "Defense"  },
    { key: "documents", label: "Docs"     },
  ]
  const rows: SkillMapRow[] = groups.length > 0
    ? groups.map((g) => SKILL_MAP_DATA.find((r) => r.skill === g.group_name) ?? {
        skill: g.group_name,
        workflow:  { status: "partial",   note: "See workflow recordings" },
        github:    { status: "partial",   note: "See GitHub analysis" },
        visual:    { status: "partial",   note: "See visual evidence" },
        defense:   { status: "partial",   note: "See project defense" },
        documents: { status: "missing",   note: "Not in documents" },
      })
    : SKILL_MAP_DATA

  const statusColor: Record<SkillSourceStatus, string> = {
    supported: C.emerald,
    partial:   C.amber,
    missing:   C.muted,
    review:    C.rose,
  }
  const statusBg: Record<SkillSourceStatus, string> = {
    supported: C.emeraldSoft,
    partial:   C.amberSoft,
    missing:   C.bg,
    review:    C.roseSoft,
  }

  return (
    <div data-testid="viewer-skill-map-tab">
      <p style={{ fontSize: 11, color: C.muted, margin: "0 0 10px" }}>
        Skill-to-evidence-source mapping — shows which evidence types support each claimed skill.
      </p>
      <div style={{ border: `1px solid ${C.line}`, borderRadius: 8, overflow: "hidden" }}>
        {/* Header */}
        <div style={{
          display: "grid", gridTemplateColumns: `160px repeat(${cols.length}, 1fr)`,
          background: C.bg, padding: "6px 10px", gap: 6, borderBottom: `1px solid ${C.line}`,
        }}>
          <span style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const }}>Skill</span>
          {cols.map((c) => (
            <span key={c.key} style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase" as const, textAlign: "center" as const }}>
              {c.label}
            </span>
          ))}
        </div>
        {/* Rows */}
        {rows.map((row, ri) => (
          <div key={row.skill} style={{
            display: "grid", gridTemplateColumns: `160px repeat(${cols.length}, 1fr)`,
            padding: "6px 10px", gap: 6,
            background: ri % 2 === 0 ? C.paper : C.bg,
            borderTop: `1px solid ${C.line}`,
            alignItems: "start",
          }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: C.ink }}>{row.skill}</span>
            {cols.map((c) => {
              const cell = row[c.key]
              return (
                <div key={c.key} style={{
                  padding: "4px 6px", borderRadius: 5,
                  background: statusBg[cell.status],
                  border: `1px solid ${statusColor[cell.status]}22`,
                  textAlign: "center" as const,
                }}>
                  <p style={{ fontSize: 9, fontWeight: 700, color: statusColor[cell.status], margin: "0 0 2px", textTransform: "capitalize" as const }}>
                    {cell.status}
                  </p>
                  <p style={{ fontSize: 9, color: C.muted, margin: 0, lineHeight: 1.3 }}>{cell.note}</p>
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}

type ViewerTabKey = "workflow" | "visual_ocr" | "github" | "defense" | "documents" | "skill_map"

function EvidenceViewerModal({
  approvedTypes,
  view,
  onClose,
}: {
  approvedTypes: string[]
  view: RecruiterPassportViewResponse
  onClose: () => void
}) {
  const normed = approvedTypes.map((k) => normaliseEvidenceKey(k))

  // Each approved type may produce 1-2 tabs.
  // workflow_recordings    → workflow + visual_ocr
  // detailed_skill_evidence → github + skill_map
  // project_defense_media  → defense
  // uploaded_documents     → documents
  type TabDef = { key: ViewerTabKey; label: string; icon: string; testId: string }
  const allTabs: TabDef[] = [
    { key: "workflow",   label: "Workflow",        icon: "🎬", testId: "evidence-tab-workflow"   },
    { key: "visual_ocr", label: "Visual / OCR",    icon: "🔍", testId: "evidence-tab-visual-ocr" },
    { key: "github",     label: "GitHub",          icon: "💻", testId: "evidence-tab-github"     },
    { key: "defense",    label: "Project Defense", icon: "📋", testId: "evidence-tab-defense"    },
    { key: "documents",  label: "Documents",       icon: "📄", testId: "evidence-tab-documents"  },
    { key: "skill_map",  label: "Skill Map",       icon: "📊", testId: "evidence-tab-skill-map"  },
  ]
  const gateMap: Record<ViewerTabKey, string> = {
    workflow:   "workflow_recordings",
    visual_ocr: "workflow_recordings",
    github:     "detailed_skill_evidence",
    defense:    "project_defense_media",
    documents:  "uploaded_documents",
    skill_map:  "detailed_skill_evidence",
  }
  const tabs = allTabs.filter((t) => normed.includes(gateMap[t.key]))
  const [activeTab, setActiveTab] = useState<ViewerTabKey>(tabs[0]?.key ?? "workflow")

  return (
    <div
      data-testid="evidence-viewer-modal"
      style={{
        position: "fixed", inset: 0,
        background: "rgba(0,0,0,0.6)",
        display: "flex", alignItems: "flex-start", justifyContent: "center",
        zIndex: 1000, padding: "40px 20px",
        overflowY: "auto",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: C.paper, borderRadius: 14,
        width: "100%", maxWidth: 860,
        boxShadow: "0 24px 60px rgba(0,0,0,0.3)",
        display: "flex", flexDirection: "column",
      }}>
        {/* Header */}
        <div style={{
          padding: "18px 22px 14px", borderBottom: `1px solid ${C.line}`,
          display: "flex", justifyContent: "space-between", alignItems: "flex-start",
        }}>
          <div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
              <span style={{ fontSize: 18 }}>🔬</span>
              <h2 style={{ fontSize: 16, fontWeight: 800, color: C.ink, margin: 0 }}>
                Approved evidence inspection
              </h2>
            </div>
            <p style={{ fontSize: 12, color: C.muted, margin: 0 }}>
              Recruiter-safe · Approved types only
            </p>
          </div>
          <button
            type="button"
            data-testid="close-evidence-viewer-btn"
            onClick={onClose}
            aria-label="Close evidence viewer"
            style={{
              fontSize: 22, cursor: "pointer", background: "none", border: "none",
              color: C.muted, padding: "0 4px", lineHeight: 1, flexShrink: 0,
            }}
          >
            ×
          </button>
        </div>

        {/* Tab bar */}
        <div style={{
          display: "flex", gap: 0,
          borderBottom: `1px solid ${C.line}`,
          padding: "0 22px",
          overflowX: "auto",
        }}>
          {tabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              data-testid={tab.testId}
              onClick={() => setActiveTab(tab.key)}
              style={{
                padding: "10px 14px",
                background: "none", border: "none",
                borderBottom: activeTab === tab.key ? `2px solid ${C.indigo}` : "2px solid transparent",
                color: activeTab === tab.key ? C.indigo : C.muted,
                fontWeight: activeTab === tab.key ? 700 : 500,
                fontSize: 12, cursor: "pointer",
                display: "flex", alignItems: "center", gap: 5,
                whiteSpace: "nowrap",
              }}
            >
              <span>{tab.icon}</span>
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div style={{ padding: "20px 22px", overflowY: "auto" }}>
          {activeTab === "workflow"   && <ViewerWorkflowTab    links={view.public_project_links} />}
          {activeTab === "visual_ocr" && <ViewerVisualOcrTab   />}
          {activeTab === "github"     && <ViewerGithubTab      />}
          {activeTab === "defense"    && <ViewerProjectDefenseTab />}
          {activeTab === "documents"  && <ViewerDocumentsTab   />}
          {activeTab === "skill_map"  && <ViewerSkillMapTab    groups={view.skill_groups} />}
        </div>

        {/* Footer */}
        <div style={{
          padding: "12px 22px", borderTop: `1px solid ${C.line}`,
          background: C.bg, borderRadius: "0 0 14px 14px",
        }}>
          <p style={{ fontSize: 11, color: C.muted, margin: 0 }}>
            You are viewing evidence types approved by the student. Raw files and sensitive metadata are hidden.
          </p>
          <p style={{ fontSize: 11, color: C.muted, margin: "3px 0 0", fontStyle: "italic" }}>
            Use this evidence to validate VeriBridge&rsquo;s summary and prepare follow-up interview questions.
          </p>
        </div>
      </div>
    </div>
  )
}

// ── Skill Evidence Detail Modal ───────────────────────────────────────────────
// Opens when a recruiter clicks "View skill evidence" on a SkillGroupCard.
// Aggregates all proof for one skill: workflow, keyframes, GitHub, transcript, documents.
// Public-safe evidence is always visible; protected evidence shows a locked card
// until the recruiter has approved access.

function SkillSourceCoverageCard({ source }: { source: SkillSourceEvidence }) {
  const statusColor: Record<string, string> = {
    supported: C.emerald, partial: C.amber, missing: C.muted, protected: C.indigo,
  }
  const statusBg: Record<string, string> = {
    supported: C.emeraldSoft, partial: C.amberSoft, missing: C.bg, protected: C.indigoSoft,
  }
  const statusLabel: Record<string, string> = {
    supported: "Supported", partial: "Partial", missing: "Missing", protected: "Protected",
  }
  const color = statusColor[source.status] ?? C.muted
  return (
    <div style={{
      padding: "10px 12px",
      background: statusBg[source.status] ?? C.bg,
      border: `1px solid ${color}33`,
      borderRadius: 8,
      display: "flex", flexDirection: "column", gap: 4,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 4 }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: C.ink }}>{source.label}</span>
        <span style={{
          fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 999,
          background: color + "22", color, border: `1px solid ${color}44`,
          flexShrink: 0,
        }}>
          {statusLabel[source.status] ?? source.status}
        </span>
      </div>
      {source.score !== undefined && (
        <span style={{ fontSize: 10, color, fontWeight: 600 }}>{source.score}/100</span>
      )}
      <p style={{ fontSize: 10, color: C.inkSoft, margin: 0, lineHeight: 1.4 }}>{source.reason}</p>
    </div>
  )
}

function SkillKeyframeCard({ frame }: { frame: SkillVisualFrame }) {
  return (
    <div style={{
      background: "#1e293b", borderRadius: 8, padding: "12px 14px",
      border: "1px solid #334155",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8" }}>{frame.timestamp}</span>
        <span style={{
          fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 999,
          background: frame.confidence === "high" ? "#166534" : frame.confidence === "medium" ? "#92400e" : "#334155",
          color: "#fff",
        }}>
          {frame.confidence}
        </span>
      </div>
      <p style={{ fontSize: 12, fontWeight: 600, color: "#e2e8f0", margin: "0 0 4px" }}>{frame.label}</p>
      <p style={{ fontSize: 11, color: "#94a3b8", margin: "0 0 4px", lineHeight: 1.4 }}>{frame.observation}</p>
      {frame.ocr && (
        <p style={{ fontSize: 10, color: "#64748b", margin: "0 0 4px", fontStyle: "italic" }}>
          OCR: {frame.ocr}
        </p>
      )}
      <div style={{ marginTop: 6, padding: "6px 8px", background: "#0f172a", borderRadius: 4 }}>
        <p style={{ fontSize: 10, fontWeight: 600, color: "#7c3aed", margin: "0 0 2px" }}>Why this supports the skill</p>
        <p style={{ fontSize: 10, color: "#a78bfa", margin: 0, lineHeight: 1.4 }}>{frame.whyItSupports}</p>
      </div>
    </div>
  )
}

function SkillGithubFileCard({ file }: { file: SkillGithubFile }) {
  return (
    <div style={{ border: `1px solid ${C.line}`, borderRadius: 7, overflow: "hidden" }}>
      <div style={{
        padding: "7px 12px", background: C.bg,
        display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8,
      }}>
        <code style={{ fontSize: 10, color: C.indigo, fontFamily: "monospace", wordBreak: "break-all" as const }}>
          {file.path}
        </code>
        <span style={{
          fontSize: 9, fontWeight: 700, padding: "1px 6px", borderRadius: 999, flexShrink: 0,
          background: file.confidence === "high" ? C.emeraldSoft : C.amberSoft,
          color: file.confidence === "high" ? C.emerald : C.amber,
          border: `1px solid ${file.confidence === "high" ? "#bbf7d0" : "#fde68a"}`,
        }}>
          {file.confidence} confidence
        </span>
      </div>
      <div style={{ padding: "8px 12px", borderTop: `1px solid ${C.line}` }}>
        <p style={{ fontSize: 11, color: C.inkSoft, margin: "0 0 6px", lineHeight: 1.5 }}>{file.reason}</p>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {file.skills.map((sk) => (
            <span key={sk} style={{
              fontSize: 9, fontWeight: 600, padding: "1px 6px", borderRadius: 4,
              background: C.indigoSoft, color: C.indigo, border: "1px solid #c7d2fe",
            }}>
              {sk}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

function SkillProtectedLock({ label }: { label: string }) {
  return (
    <div
      data-testid="skill-evidence-protected-lock"
      style={{
        padding: "12px 14px", background: "#1e1b4b",
        border: "1px solid #4f46e5", borderRadius: 8,
        display: "flex", alignItems: "center", gap: 10,
      }}
    >
      <span style={{ fontSize: 16, flexShrink: 0 }}>🔒</span>
      <div>
        <p style={{ fontSize: 12, fontWeight: 600, color: "#a5b4fc", margin: "0 0 2px" }}>
          Protected evidence available — request access
        </p>
        <p style={{ fontSize: 11, color: "#818cf8", margin: 0 }}>
          {label} — student approval required to view
        </p>
      </div>
    </div>
  )
}

// ── Direct Proof Links Section ────────────────────────────────────────────────
// Direct inspection actions for each evidence artifact in a skill bundle.
// Public evidence is actionable inline; protected evidence requires student approval.
// Privacy: no raw storage URLs, tokens, localhost, or private media paths exposed.

function DirectProofLinksSection({
  bundle,
  accessApproved,
}: {
  bundle: SkillEvidenceBundle
  accessApproved: boolean
}) {
  const [expandedFrame, setExpandedFrame] = useState<number | null>(null)
  const [expandedTranscript, setExpandedTranscript] = useState<number | null>(null)
  const [expandedDoc, setExpandedDoc] = useState<number | null>(null)

  const hasGithub = bundle.githubEvidence.length > 0
  const hasVisual = bundle.visualEvidence.length > 0
  const hasTranscript = bundle.transcriptEvidence.length > 0
  const hasDocs = bundle.documentEvidence.length > 0
  const hasLiveApp = !!bundle.liveApp

  if (!hasGithub && !hasVisual && !hasTranscript && !hasDocs && !hasLiveApp) return null

  const sourcePill = (label: string, color: string, bg: string, border: string) => (
    <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 4, color, background: bg, border: `1px solid ${border}`, flexShrink: 0 }}>
      {label}
    </span>
  )
  const visibilityPill = (isPublic: boolean) => (
    <span style={{ fontSize: 9, fontWeight: 600, padding: "2px 6px", borderRadius: 4, color: isPublic ? C.emerald : C.indigo, background: isPublic ? C.emeraldSoft : C.indigoSoft, border: `1px solid ${isPublic ? "#bbf7d0" : "#c7d2fe"}`, flexShrink: 0 }}>
      {isPublic ? "Public" : "Protected"}
    </span>
  )
  const statusLabel = (openable: boolean) => (
    <span style={{ fontSize: 9, fontWeight: 600, color: openable ? C.emerald : C.muted }}>
      {openable ? "Openable" : "Locked"}
    </span>
  )
  const actionBtn = (label: string, onClick: () => void, variant: "primary" | "secondary", testId: string) => (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      style={{ fontSize: 10, fontWeight: 600, padding: "3px 9px", borderRadius: 5, cursor: "pointer", color: variant === "primary" ? C.indigo : C.muted, background: variant === "primary" ? C.indigoSoft : C.bg, border: `1px solid ${variant === "primary" ? "#c7d2fe" : C.line}` }}
    >
      {label}
    </button>
  )
  const lockedBanner = (reason: string, testId: string) => (
    <div data-testid={testId} style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 8px", borderRadius: 5, background: "#1e1b4b", border: "1px solid #4f46e5" }}>
      <span style={{ fontSize: 12, flexShrink: 0 }}>🔒</span>
      <span style={{ fontSize: 10, color: "#a5b4fc" }}>{reason}</span>
    </div>
  )
  const groupLabel = (text: string) => (
    <div style={{ fontSize: 9, fontWeight: 800, letterSpacing: "0.08em", textTransform: "uppercase" as const, color: C.muted, marginBottom: 6 }}>{text}</div>
  )
  const rowBox = (children: React.ReactNode, rounded: string) => (
    <div style={{ padding: "9px 11px", borderRadius: rounded, background: C.bg, border: `1px solid ${C.line}`, display: "flex", flexDirection: "column", gap: 5 }}>
      {children}
    </div>
  )

  return (
    <div data-testid="skill-direct-proof-links">
      <SectionTitle>Direct proof links</SectionTitle>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

        {/* GitHub code */}
        {hasGithub && (
          <div data-testid="skill-direct-github">
            {groupLabel("GitHub code")}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {bundle.githubEvidence.map((file, i) => (
                <div key={`gh-${i}`}>
                  {rowBox(
                    <>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                        {sourcePill("GitHub", C.emerald, C.emeraldSoft, "#bbf7d0")}
                        {visibilityPill(file.isPublic)}
                        {statusLabel(file.isPublic)}
                      </div>
                      <code style={{ fontSize: 10, color: C.indigo, fontFamily: "monospace" as const, wordBreak: "break-all" as const }}>{file.path}</code>
                      <p style={{ fontSize: 10, color: C.inkSoft, margin: 0, lineHeight: 1.4 }}>{file.reason}</p>
                      {file.isPublic ? (
                        <a
                          href={`https://github.com/candidate-repo/blob/main/${file.path}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          data-testid={`open-source-file-${i}`}
                          style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 10, fontWeight: 600, padding: "3px 9px", borderRadius: 5, color: C.emerald, background: C.emeraldSoft, border: "1px solid #bbf7d0", textDecoration: "none", width: "fit-content" as const }}
                        >
                          ↗ Open source file
                        </a>
                      ) : lockedBanner(
                        "Source file access requires student approval or public repository access.",
                        `locked-github-file-${i}`,
                      )}
                    </>,
                    "7px",
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Workflow recording / keyframes */}
        {hasVisual && (
          <div data-testid="skill-direct-keyframes">
            {groupLabel("Workflow recording / keyframes")}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {bundle.visualEvidence.map((frame, i) => {
                const canOpen = !frame.isProtected || accessApproved
                const isExpanded = expandedFrame === i
                return (
                  <div key={`kf-${i}`} style={{ display: "flex", flexDirection: "column" }}>
                    {rowBox(
                      <>
                        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                          {sourcePill("Keyframe", C.violet, C.violetSoft, "#ddd6fe")}
                          {visibilityPill(!frame.isProtected)}
                          {statusLabel(canOpen)}
                          <span style={{ fontSize: 9, color: C.muted }}>{frame.timestamp}</span>
                        </div>
                        <p style={{ fontSize: 11, fontWeight: 600, color: C.ink, margin: 0 }}>{frame.label}</p>
                        <p style={{ fontSize: 10, color: C.inkSoft, margin: 0, lineHeight: 1.4 }}>{frame.observation}</p>
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                          {canOpen ? (
                            <>
                              {actionBtn(isExpanded ? "Hide keyframe" : "View keyframe", () => setExpandedFrame(isExpanded ? null : i), "primary", "view-keyframe-btn")}
                              {frame.ocr && actionBtn("View OCR details", () => setExpandedFrame(isExpanded ? null : i), "secondary", "view-ocr-details-btn")}
                              {accessApproved && actionBtn("Open recording segment", () => setExpandedFrame(isExpanded ? null : i), "secondary", "open-recording-segment-btn")}
                            </>
                          ) : lockedBanner("Keyframe and recording access requires student approval.", "locked-keyframe-btn")}
                        </div>
                      </>,
                      isExpanded ? "7px 7px 0 0" : "7px",
                    )}
                    {isExpanded && canOpen && (
                      <div
                        data-testid={`keyframe-detail-panel-${i}`}
                        style={{ padding: "10px 12px", background: "#1e293b", border: "1px solid #334155", borderTop: "none", borderRadius: "0 0 7px 7px" }}
                      >
                        <p style={{ fontSize: 10, fontWeight: 600, color: "#e2e8f0", margin: "0 0 4px" }}>{frame.label}</p>
                        {frame.ocr && (
                          <p style={{ fontSize: 10, color: "#64748b", margin: "0 0 5px", fontStyle: "italic" }}>
                            OCR: {frame.ocr}
                          </p>
                        )}
                        <div style={{ padding: "6px 8px", background: "#0f172a", borderRadius: 4 }}>
                          <p style={{ fontSize: 10, fontWeight: 600, color: "#7c3aed", margin: "0 0 2px" }}>Why this supports the skill</p>
                          <p style={{ fontSize: 10, color: "#a78bfa", margin: 0, lineHeight: 1.4 }}>{frame.whyItSupports}</p>
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Transcript */}
        {hasTranscript && (
          <div data-testid="skill-direct-transcript">
            {groupLabel("Transcript")}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {bundle.transcriptEvidence.map((t, i) => {
                const canOpen = !t.isProtected || accessApproved
                const isExpanded = expandedTranscript === i
                return (
                  <div key={`tr-${i}`} style={{ display: "flex", flexDirection: "column" }}>
                    {rowBox(
                      <>
                        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                          {sourcePill("Transcript", C.sky, C.skySoft, "#bae6fd")}
                          {visibilityPill(!t.isProtected)}
                          {statusLabel(canOpen)}
                        </div>
                        <p style={{ fontSize: 10, color: C.inkSoft, margin: 0, lineHeight: 1.4 }}>{t.relevance}</p>
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                          {canOpen ? (
                            <>
                              {actionBtn(isExpanded ? "Hide excerpt" : "View approved excerpt", () => setExpandedTranscript(isExpanded ? null : i), "primary", "view-transcript-excerpt-btn")}
                              {accessApproved && actionBtn("View full transcript", () => setExpandedTranscript(isExpanded ? null : i), "secondary", "view-full-transcript-btn")}
                            </>
                          ) : lockedBanner("Full transcript requires student approval.", "locked-transcript-btn")}
                        </div>
                      </>,
                      isExpanded ? "7px 7px 0 0" : "7px",
                    )}
                    {isExpanded && canOpen && (
                      <div
                        data-testid={`transcript-detail-panel-${i}`}
                        style={{ padding: "10px 12px", background: C.bg, border: `1px solid ${C.line}`, borderTop: "none", borderRadius: "0 0 7px 7px" }}
                      >
                        <blockquote style={{ fontSize: 12, color: C.inkSoft, lineHeight: 1.7, margin: 0, padding: "0 0 0 12px", borderLeft: `3px solid ${C.indigo}`, fontStyle: "italic" }}>
                          &ldquo;{t.excerpt}&rdquo;
                        </blockquote>
                        {t.ownershipSignal && (
                          <p style={{ fontSize: 10, color: C.emerald, margin: "6px 0 0" }}>Ownership signal: {t.ownershipSignal}</p>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Documents */}
        {hasDocs && (
          <div data-testid="skill-direct-documents">
            {groupLabel("Documents")}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {bundle.documentEvidence.map((doc, i) => {
                const canOpen = !doc.isProtected || accessApproved
                const isExpanded = expandedDoc === i
                return (
                  <div key={`doc-${i}`} style={{ display: "flex", flexDirection: "column" }}>
                    {rowBox(
                      <>
                        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                          {sourcePill("Document", C.amber, C.amberSoft, "#fde68a")}
                          {visibilityPill(!doc.isProtected)}
                          {statusLabel(canOpen)}
                        </div>
                        <p style={{ fontSize: 11, fontWeight: 600, color: C.ink, margin: 0 }}>{doc.title}</p>
                        <p style={{ fontSize: 10, color: C.inkSoft, margin: 0, lineHeight: 1.4 }}>{doc.relevance}</p>
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                          {canOpen ? (
                            <>
                              {actionBtn(isExpanded ? "Hide summary" : "View document summary", () => setExpandedDoc(isExpanded ? null : i), "primary", "view-document-summary-btn")}
                              {accessApproved && actionBtn("Open approved document", () => setExpandedDoc(isExpanded ? null : i), "secondary", "open-approved-document-btn")}
                            </>
                          ) : lockedBanner("Document access requires student approval.", "locked-document-btn")}
                        </div>
                      </>,
                      isExpanded ? "7px 7px 0 0" : "7px",
                    )}
                    {isExpanded && canOpen && (
                      <div
                        data-testid={`document-detail-panel-${i}`}
                        style={{ padding: "10px 12px", background: C.bg, border: `1px solid ${C.line}`, borderTop: "none", borderRadius: "0 0 7px 7px" }}
                      >
                        <p style={{ fontSize: 11, color: C.inkSoft, margin: 0, fontStyle: "italic", lineHeight: 1.5 }}>
                          &ldquo;{doc.snippet}&rdquo;
                        </p>
                        <p style={{ fontSize: 10, color: C.muted, margin: "6px 0 0" }}>Relevance: {doc.relevance}</p>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Live app */}
        {hasLiveApp && bundle.liveApp && (
          <div data-testid="skill-direct-live-app">
            {groupLabel("Live app")}
            {bundle.liveApp.isPublic && bundle.liveApp.publicUrl ? (
              <div style={{ padding: "9px 11px", borderRadius: 7, background: C.emeraldSoft, border: "1px solid #bbf7d0", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <div>
                  <p style={{ fontSize: 11, fontWeight: 600, color: "#065f46", margin: "0 0 2px" }}>{bundle.liveApp.label}</p>
                  <p style={{ fontSize: 10, color: C.emerald, margin: 0 }}>Public — directly openable</p>
                </div>
                <a
                  href={bundle.liveApp.publicUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  data-testid="open-live-app-btn"
                  style={{ fontSize: 10, fontWeight: 700, padding: "4px 10px", borderRadius: 5, color: C.emerald, background: "#fff", border: "1px solid #bbf7d0", textDecoration: "none", flexShrink: 0 }}
                >
                  ↗ Open live app
                </a>
              </div>
            ) : (
              <div
                data-testid="local-private-app-notice"
                style={{ padding: "9px 11px", borderRadius: 7, background: C.bg, border: `1px solid ${C.line}`, display: "flex", alignItems: "center", gap: 8 }}
              >
                <span style={{ fontSize: 14, flexShrink: 0 }}>🔒</span>
                <div>
                  <p style={{ fontSize: 11, fontWeight: 600, color: C.ink, margin: "0 0 2px" }}>{bundle.liveApp.label}</p>
                  <p style={{ fontSize: 10, color: C.muted, margin: 0 }}>
                    Local/private app — not publicly openable. Review GitHub or setup evidence instead.
                  </p>
                </div>
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  )
}

export function SkillEvidenceDetailModal({
  skillName,
  accessApproved,
  onClose,
}: {
  skillName: string
  accessApproved: boolean
  onClose: () => void
}) {
  const bundle = getSkillBundle(skillName)

  const supportStatusColor =
    bundle.supportStatus === "strongly supported" ? C.emerald
    : bundle.supportStatus === "partially supported" ? C.amber
    : C.muted
  const supportStatusBg =
    bundle.supportStatus === "strongly supported" ? C.emeraldSoft
    : bundle.supportStatus === "partially supported" ? C.amberSoft
    : C.bg

  return (
    <div
      data-testid="skill-evidence-detail-modal"
      style={{
        position: "fixed", inset: 0,
        background: "rgba(0,0,0,0.65)",
        display: "flex", alignItems: "flex-start", justifyContent: "center",
        zIndex: 1100, padding: "40px 20px", overflowY: "auto",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: C.paper, borderRadius: 14,
        width: "100%", maxWidth: 900,
        boxShadow: "0 24px 60px rgba(0,0,0,0.35)",
        display: "flex", flexDirection: "column",
      }}>
        {/* Header */}
        <div style={{ padding: "20px 24px 16px", borderBottom: `1px solid ${C.line}` }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 6 }}>
                <span style={{ fontSize: 18 }}>📊</span>
                <h2 style={{ fontSize: 17, fontWeight: 800, color: C.ink, margin: 0 }}>
                  {bundle.skillName}
                </h2>
                <ConfidenceBadge level={bundle.confidence} />
                <span style={{
                  fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 999,
                  background: supportStatusBg, color: supportStatusColor,
                  border: `1px solid ${supportStatusColor}44`,
                }}>
                  {bundle.supportStatus}
                </span>
              </div>
              <p style={{ fontSize: 12, color: C.inkSoft, margin: 0, lineHeight: 1.5 }}>
                {bundle.explanation}
              </p>
            </div>
            <button
              type="button"
              data-testid="close-skill-evidence-modal-btn"
              onClick={onClose}
              aria-label="Close skill evidence detail"
              style={{
                fontSize: 22, cursor: "pointer", background: "none", border: "none",
                color: C.muted, padding: "0 4px", lineHeight: 1, flexShrink: 0,
              }}
            >
              ×
            </button>
          </div>
        </div>

        {/* Body */}
        <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 24, overflowY: "auto" }}>

          {/* 1. Source coverage summary */}
          <div data-testid="skill-evidence-source-coverage">
            <SectionTitle>Source coverage</SectionTitle>
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
              gap: 8,
            }}>
              {bundle.sources.map((source) => (
                <SkillSourceCoverageCard key={source.key} source={source} />
              ))}
            </div>
          </div>

          {/* 2. Visual / keyframe proof */}
          <div data-testid="skill-evidence-visual-proof">
            <SectionTitle>Precise visual proof</SectionTitle>
            {bundle.visualEvidence.length === 0 ? (
              <div style={{ padding: "12px 14px", background: C.bg, border: `1px solid ${C.line}`, borderRadius: 8 }}>
                <p style={{ fontSize: 12, color: C.muted, margin: 0, fontStyle: "italic" }}>
                  No visual/keyframe evidence captured for this skill — deployment or document-only coverage.
                </p>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {bundle.visualEvidence.map((frame, i) =>
                  frame.isProtected && !accessApproved ? (
                    <SkillProtectedLock key={i} label="Keyframe / screenshot evidence" />
                  ) : (
                    <SkillKeyframeCard key={i} frame={frame} />
                  )
                )}
              </div>
            )}
          </div>

          {/* 3. GitHub code evidence */}
          <div data-testid="skill-evidence-github">
            <SectionTitle>GitHub code evidence</SectionTitle>
            {bundle.githubEvidence.length === 0 ? (
              <div style={{ padding: "12px 14px", background: C.bg, border: `1px solid ${C.line}`, borderRadius: 8 }}>
                <p style={{ fontSize: 12, color: C.muted, margin: 0, fontStyle: "italic" }}>
                  No GitHub code evidence detected for this skill.
                </p>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {bundle.githubEvidence.map((file) => (
                  <SkillGithubFileCard key={file.path} file={file} />
                ))}
                <p style={{ fontSize: 10, color: C.muted, margin: 0, fontStyle: "italic" }}>
                  Safe file paths shown. Raw source code access requires student approval.
                </p>
              </div>
            )}
          </div>

          {/* 4. Transcript & document evidence */}
          <div data-testid="skill-evidence-transcript">
            <SectionTitle>Transcript &amp; document evidence</SectionTitle>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {bundle.transcriptEvidence.length === 0 && bundle.documentEvidence.length === 0 && (
                <div style={{ padding: "12px 14px", background: C.bg, border: `1px solid ${C.line}`, borderRadius: 8 }}>
                  <p style={{ fontSize: 12, color: C.muted, margin: 0, fontStyle: "italic" }}>
                    No transcript or document evidence for this skill.
                  </p>
                </div>
              )}
              {bundle.transcriptEvidence.map((t, i) =>
                t.isProtected && !accessApproved ? (
                  <SkillProtectedLock key={`tr-${i}`} label="Transcript excerpt" />
                ) : (
                  <div key={`tr-${i}`} style={{ padding: "12px 14px", background: C.bg, border: `1px solid ${C.line}`, borderRadius: 8 }}>
                    <blockquote style={{
                      fontSize: 12, color: C.inkSoft, lineHeight: 1.7,
                      margin: "0 0 8px", padding: "0 0 0 12px",
                      borderLeft: `3px solid ${C.indigo}`, fontStyle: "italic",
                    }}>
                      &ldquo;{t.excerpt}&rdquo;
                    </blockquote>
                    <p style={{ fontSize: 10, color: C.muted, margin: "0 0 3px" }}>
                      <strong>Relevance:</strong> {t.relevance}
                    </p>
                    {t.ownershipSignal && (
                      <p style={{ fontSize: 10, color: C.emerald, margin: "0 0 2px" }}>
                        Ownership signal: {t.ownershipSignal}
                      </p>
                    )}
                    {t.technicalDepth && (
                      <p style={{ fontSize: 10, color: C.indigo, margin: 0 }}>
                        Technical depth: {t.technicalDepth}
                      </p>
                    )}
                  </div>
                )
              )}
              {bundle.documentEvidence.map((d, i) =>
                d.isProtected && !accessApproved ? (
                  <SkillProtectedLock key={`doc-${i}`} label="Document evidence" />
                ) : (
                  <div key={`doc-${i}`} style={{ padding: "12px 14px", background: C.bg, border: `1px solid ${C.line}`, borderRadius: 8 }}>
                    <p style={{ fontSize: 11, fontWeight: 700, color: C.ink, margin: "0 0 4px" }}>{d.title}</p>
                    <p style={{ fontSize: 11, color: C.inkSoft, margin: "0 0 4px", fontStyle: "italic", lineHeight: 1.5 }}>
                      &ldquo;{d.snippet}&rdquo;
                    </p>
                    <p style={{ fontSize: 10, color: C.muted, margin: 0 }}>
                      <strong>Relevance:</strong> {d.relevance}
                    </p>
                  </div>
                )
              )}
            </div>
          </div>

          {/* 5. Direct proof links */}
          <DirectProofLinksSection bundle={bundle} accessApproved={accessApproved} />

          {/* 6. Interview questions */}
          <div data-testid="skill-evidence-interview-questions">
            <SectionTitle>Suggested interview questions</SectionTitle>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {bundle.interviewQuestions.map((q, i) => (
                <div key={i} style={{
                  padding: "8px 12px", background: C.bg,
                  border: `1px solid ${C.line}`, borderRadius: 7,
                  fontSize: 12, color: C.inkSoft, lineHeight: 1.5,
                }}>
                  <span style={{ color: C.muted, marginRight: 6, fontWeight: 700 }}>{i + 1}.</span>
                  {q}
                </div>
              ))}
            </div>
            <p style={{ fontSize: 10, color: C.muted, margin: "8px 0 0", fontStyle: "italic" }}>
              Questions focus on areas with partial or weak evidence — adapt as needed.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div style={{
          padding: "12px 24px", borderTop: `1px solid ${C.line}`,
          background: C.bg, borderRadius: "0 0 14px 14px",
        }}>
          <p style={{ fontSize: 11, color: C.muted, margin: 0 }}>
            VeriBridge aggregates evidence from workflow, GitHub, visual/OCR, transcript, and documents for each skill.
          </p>
          <p style={{ fontSize: 11, color: C.muted, margin: "2px 0 0", fontStyle: "italic" }}>
            Raw files and sensitive metadata remain under student control. Protected evidence requires explicit student approval.
          </p>
        </div>
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
  const [showViewer, setShowViewer] = useState(false)

  const normed = approvedTypes.map((k) => normaliseEvidenceKey(k))
  const hasWorkflow = normed.includes("workflow_recordings")
  const hasDefense  = normed.includes("project_defense_media")
  const hasSkills   = normed.includes("detailed_skill_evidence")
  const hasDocs     = normed.includes("uploaded_documents")

  if (!hasWorkflow && !hasDefense && !hasSkills && !hasDocs) return null

  return (
    <>
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

        {/* Open evidence viewer CTA */}
        <div style={{
          marginTop: 18, paddingTop: 16,
          borderTop: `1px solid ${C.line}`,
          display: "flex", alignItems: "center", justifyContent: "space-between",
          gap: 12, flexWrap: "wrap",
        }}>
          <div>
            <p style={{ fontSize: 12, fontWeight: 700, color: C.ink, margin: "0 0 2px" }}>
              Inspect the approved evidence directly
            </p>
            <p style={{ fontSize: 11, color: C.muted, margin: 0 }}>
              View recruiter-safe evidence in detail — no raw URLs or private data.
            </p>
          </div>
          <button
            type="button"
            data-testid="open-evidence-viewer-btn"
            onClick={() => setShowViewer(true)}
            style={{
              background: C.indigo, color: "#fff",
              border: "none", borderRadius: 7,
              padding: "8px 16px", fontSize: 12, fontWeight: 700,
              cursor: "pointer", flexShrink: 0,
            }}
          >
            Open evidence viewer
          </button>
        </div>
      </Card>

      {/* Full-screen evidence viewer modal */}
      {showViewer && (
        <EvidenceViewerModal
          approvedTypes={approvedTypes}
          view={view}
          onClose={() => setShowViewer(false)}
        />
      )}
    </>
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
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null)

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
            onViewSkill={setSelectedSkill}
            accessApproved={accessRequest?.status === "approved"}
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

      {/* Skill evidence detail modal */}
      {selectedSkill && (
        <SkillEvidenceDetailModal
          skillName={selectedSkill}
          accessApproved={accessRequest?.status === "approved"}
          onClose={() => setSelectedSkill(null)}
        />
      )}

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
