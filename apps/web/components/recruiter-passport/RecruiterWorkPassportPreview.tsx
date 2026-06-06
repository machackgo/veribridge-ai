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
  pageTitle?: string
  observation: string
  ocr: string
  domContext?: string
  qwenObservation?: string
  whyItSupports: string
  confidence: "high" | "medium" | "low"
  isProtected: boolean
}

type SkillGithubFile = {
  path: string
  reason: string
  skills: string[]
  stackTags?: string[]
  confidence: "high" | "medium" | "low"
  isPublic: boolean
  repoUrl?: string
  branch?: string
  startLine?: number
  endLine?: number
  symbolName?: string
  codeBlockSummary?: string
}

type SkillTranscriptExcerpt = {
  excerpt: string
  fullExcerpt?: string
  lines?: string[]
  relevance: string
  ownershipSignal?: string
  technicalDepth?: string
  skillMapping?: string[]
  isProtected: boolean
}

type SkillDocumentSnippet = {
  title: string
  fileType?: string
  snippet: string
  summary?: string
  relevance: string
  supportedSkills?: string[]
  mismatchWarnings?: string[]
  extractedSections?: string[]
  isProtected: boolean
}

type SkillWorkflowRecording = {
  title: string
  duration: string
  recordedDate: string
  sessionType: string
  relatedSkills: string[]
  isProtected: boolean
  segments: { timestamp: string; label: string; reason: string }[]
}

type SkillDomEvidence = {
  pageTitle: string
  urlType: "public" | "local" | "private"
  capturedLabels: string[]
  observedSections: string[]
  capturedEvents?: string[]
  skillRelevance: string
  isProtected: boolean
}

type SkillQwenAnalysis = {
  analyzedFrameCount: number
  observations: string[]
  modelReasoning: string
  skillMatch: string
  uncertainObservations: string[]
  confidence: "high" | "medium" | "low"
}

type SkillFinalAnalysis = {
  evidenceScore: number
  sourceScores: { label: string; score: number; status: string }[]
  recommendation: string
  strongestProof: string
  weakestProof: string
  whyGranted: string
  stillNeedsReview: string[]
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
  workflowRecording?: SkillWorkflowRecording
  domEvidence?: SkillDomEvidence
  qwenAnalysis?: SkillQwenAnalysis
  finalAnalysis?: SkillFinalAnalysis
}

// ── Skill Evidence Pipeline — multi-source, multi-project aggregated model ─────
// Represents one skill across ALL evidence sources the student has collected,
// not only one project or one workflow session.

type OcrEvidenceItem = {
  timestamp: string
  extractedText: string
  source: string
  confidence: "high" | "medium" | "low"
  note?: string
}

type EvidenceItem = {
  sourceType: "workflow" | "github" | "visual" | "ocr" | "dom" | "qwen" | "transcript" | "document"
  sourceTitle: string
  projectName: string
  visibility: "public" | "protected" | "approved" | "locked" | "unavailable"
  relevanceToSkill: string
  confidence: "high" | "medium" | "low"
  proofReason: string
  artifactActionLabel: string
  artifactStatus: "supported" | "partial" | "missing" | "needs-review"
}

export type SkillEvidencePipeline = {
  skillId: string
  skillName: string
  category: string
  confidence: "high" | "medium" | "low"
  supportStatus: "strongly supported" | "partially supported" | "needs review"
  overallExplanation: string
  evidenceSources: SkillSourceEvidence[]
  codeEvidence: SkillGithubFile[]
  workflowEvidence: SkillWorkflowRecording[]
  visualEvidence: SkillVisualFrame[]
  ocrEvidence: OcrEvidenceItem[]
  domEvidence: SkillDomEvidence[]
  qwenEvidence: SkillQwenAnalysis[]
  transcriptEvidence: SkillTranscriptExcerpt[]
  documentEvidence: SkillDocumentSnippet[]
  projects: Array<{ name: string; type: string; evidenceCount: number }>
  directActions: EvidenceItem[]
  interviewQuestions: string[]
  protectedEvidenceFlags: string[]
  finalAnalysis?: SkillFinalAnalysis
  liveApp?: { label: string; isPublic: boolean; publicUrl?: string }
}

const VERIBRIDGE_REPO = "https://github.com/machackgo/veribridge-ai"
const VERIBRIDGE_BRANCH = "main"

const SKILL_EVIDENCE_BUNDLES: Record<string, SkillEvidenceBundle> = {
  "AI / Machine Learning": {
    skillName: "AI / Machine Learning",
    confidence: "high",
    supportStatus: "strongly supported",
    explanation:
      "This skill is backed by multiple approved proof artifacts spanning workflow recording, GitHub code, OCR/visual evidence, project defense transcript, and a formal project report.",
    sources: [
      { key: "workflow",  label: "Workflow recording",     status: "supported", score: 88, reason: "Live model inference workflow observed in 3 recordings"              },
      { key: "keyframes", label: "Keyframes / screenshots", status: "partial",  score: 72, reason: "AI-related UI visible in 2 of 3 keyframe sets — raw frames protected" },
      { key: "ocr",       label: "OCR / visual reasoning",  status: "partial",  score: 65, reason: "Inference output text extracted; some frames inconclusive"           },
      { key: "github",    label: "GitHub code",             status: "supported", score: 91, reason: "ML pipeline, evaluator service, and proof engine files confirmed"   },
      { key: "defense",   label: "Project defense",         status: "supported", score: 84, reason: "Candidate explained model selection, training, and evaluation"      },
      { key: "documents", label: "Documents",               status: "supported", score: 79, reason: "Project report covers ML methodology and experimental results"      },
      { key: "dom",       label: "DOM Evidence",            status: "supported", score: 78, reason: "Captured page structure, visible UI labels, and proof builder state changes support this skill." },
    ],
    workflowRecording: {
      title: "AI Proof Builder — Model Inference Demo",
      duration: "4:12",
      recordedDate: "May 2026",
      sessionType: "Browser workflow proof",
      relatedSkills: ["Machine Learning", "TensorFlow.js", "Evidence Aggregation"],
      isProtected: false,
      segments: [
        { timestamp: "0:22", label: "Model inference UI opened", reason: "Candidate opens proof builder and loads ML inference interface — confirms hands-on setup" },
        { timestamp: "1:18", label: "Live prediction submitted", reason: "Input fed to TensorFlow.js model; output rendered in real-time — confirms functional ML pipeline" },
        { timestamp: "2:05", label: "Evidence scoring dashboard", reason: "VeriBridge evidence score updated live as proof signals were captured — confirms ML workflow awareness" },
      ],
    },
    visualEvidence: [
      {
        timestamp: "0:22",
        label: "Model inference UI visible",
        pageTitle: "AI Proof Builder — VeriBridge",
        observation: "Live prediction interface with input field and inference output visible in viewport",
        ocr: "Overall Score: 87 · High confidence · Evidence reviewed · AI Proof Builder · VeriBridge",
        domContext: "Evidence-backed skills section, proof source cards, and AI-reviewed confidence badge present in DOM",
        qwenObservation: "Dashboard displays AI-generated evidence confidence score card with source breakdown. Proof builder UI shows 'AI Reviewed' badge and skill confidence meter.",
        whyItSupports: "Confirms hands-on interaction with an AI inference system and evidence scoring pipeline",
        confidence: "high",
        isProtected: false,
      },
      {
        timestamp: "1:18",
        label: "Prediction/demo workflow observed",
        pageTitle: "AI Proof Builder — Live Inference",
        observation: "Full model prediction workflow captured — input submission and real-time output rendered",
        ocr: "Prediction: 94.2% confidence · model loaded · TensorFlow.js runtime active",
        domContext: "Input form, submit button, and prediction output div all captured in DOM snapshot",
        qwenObservation: "TensorFlow.js inference output rendered on screen. Confidence percentage visible alongside input data and model result label.",
        whyItSupports: "Shows end-to-end ML workflow with real model output, not just a static UI",
        confidence: "high",
        isProtected: true,
      },
      {
        timestamp: "2:05",
        label: "AI proof builder / evidence scoring visible",
        pageTitle: "Evidence Score Dashboard — VeriBridge",
        observation: "Evidence scoring interface for AI skill signals observed — per-source score breakdown visible",
        ocr: "AI evidence score: 87 · Workflow: supported · GitHub: supported · OCR: partial",
        domContext: "Score breakdown table, per-source status badges, and final recommendation paragraph captured",
        qwenObservation: "Score dashboard shows per-source evidence status. Workflow and GitHub marked as 'supported', OCR as 'partial'. Final score 87/100 visible.",
        whyItSupports: "Demonstrates working knowledge of AI evidence aggregation and multi-source scoring",
        confidence: "medium",
        isProtected: true,
      },
    ],
    githubEvidence: [
      {
        path: "apps/api/app/services/final_evidence_evaluator_service.py",
        reason: "Combines workflow, GitHub, OCR, transcript, and document signals into a final skill confidence score using weighted aggregation",
        skills: ["Python", "Machine Learning", "Evidence Aggregation"],
        stackTags: ["Python", "FastAPI", "ML Pipeline", "Scoring"],
        confidence: "high",
        isPublic: true,
        repoUrl: VERIBRIDGE_REPO,
        branch: VERIBRIDGE_BRANCH,
        startLine: 40,
        endLine: 140,
        symbolName: "FinalEvidenceEvaluatorService",
        codeBlockSummary: "Combines workflow, GitHub, OCR, transcript, and document signals into final skill confidence using weighted aggregation logic.",
      },
      {
        path: "apps/api/app/services/extension_proof_workflow_analysis_service.py",
        reason: "Analyzes browser workflow signals to extract skill evidence from recorded sessions — core ML signal processing layer",
        skills: ["Python", "ML Signal Processing", "Workflow Analysis"],
        stackTags: ["Python", "Signal Processing", "Async", "Evidence Extraction"],
        confidence: "high",
        isPublic: true,
        repoUrl: VERIBRIDGE_REPO,
        branch: VERIBRIDGE_BRANCH,
        startLine: 80,
        endLine: 180,
        symbolName: "WorkflowAnalysisService",
        codeBlockSummary: "Analyzes browser workflow events and maps them to claimed skills for evidence extraction.",
      },
      {
        path: "apps/api/app/services/verification_review_service.py",
        reason: "AI review decision engine: applies approval rules based on score threshold, privacy check, and evidence completeness",
        skills: ["Python", "Machine Learning", "Decision Logic"],
        stackTags: ["Python", "AI Review", "Decision Tree", "Verification"],
        confidence: "medium",
        isPublic: true,
        repoUrl: VERIBRIDGE_REPO,
        branch: VERIBRIDGE_BRANCH,
        startLine: 30,
        endLine: 120,
        symbolName: "VerificationReviewService",
        codeBlockSummary: "Applies AI review decision logic for evidence completeness and approval threshold checks.",
      },
    ],
    transcriptEvidence: [
      {
        excerpt:
          "The main goal was to demonstrate machine learning in a browser environment. I chose TensorFlow.js because it allowed real-time inference without a backend server.",
        fullExcerpt:
          "The main goal was to demonstrate machine learning in a browser environment. I chose TensorFlow.js because it allowed real-time inference without a backend server, which simplified deployment and made it easier to capture as evidence. The model was trained offline on a labeled dataset and then exported to the TensorFlow.js format. I validated accuracy using an 80/20 train/test split and measured 92% accuracy on held-out data.",
        lines: [
          "I chose TensorFlow.js because it allowed real-time inference without a backend server.",
          "The model was trained offline on a labeled dataset, then exported to TensorFlow.js format.",
          "I validated using an 80/20 train/test split and measured 92% accuracy on held-out data.",
          "Real-time inference in the browser was the key proof — I could show the model running live.",
        ],
        relevance: "Explains model choice, training methodology, and validation — ownership signal",
        ownershipSignal: "Candidate references specific design decisions with justification and quantitative results",
        technicalDepth: "Covers inference architecture, deployment constraints, and evaluation methodology",
        skillMapping: ["Machine Learning", "TensorFlow.js", "Model Evaluation"],
        isProtected: false,
      },
      {
        excerpt:
          "The evidence scoring system aggregates signals from multiple sources — workflow, GitHub, OCR, and transcript — using a weighted confidence model.",
        fullExcerpt:
          "The evidence scoring system aggregates signals from multiple sources — workflow, GitHub, OCR, and transcript — using a weighted confidence model. Each source contributes a score between 0 and 100, and the final score is a weighted average with workflow and GitHub weighted more heavily because they are harder to fake.",
        lines: [
          "Each source contributes a score between 0 and 100.",
          "Workflow and GitHub are weighted more heavily because they are harder to fake.",
          "The final score is a weighted average across all active evidence sources.",
        ],
        relevance: "Demonstrates understanding of multi-signal ML evidence aggregation",
        ownershipSignal: "Explains design rationale for weighting scheme",
        technicalDepth: "Covers weighted scoring, source independence, and anti-gaming logic",
        skillMapping: ["Machine Learning", "Evidence Aggregation", "Scoring Systems"],
        isProtected: true,
      },
    ],
    domEvidence: {
      pageTitle: "AI Proof Builder — VeriBridge",
      urlType: "local",
      capturedLabels: [
        "Evidence-backed skills",
        "Proof source cards",
        "AI-reviewed badge",
        "Submit inference button",
        "Prediction output panel",
        "Score: 87 / 100",
      ],
      observedSections: [
        "Evidence score dashboard",
        "Source coverage grid (Workflow, GitHub, OCR, Transcript)",
        "Model inference input form",
        "Real-time prediction output",
        "Confidence meter",
      ],
      capturedEvents: [
        "click on Submit Inference button",
        "DOM update: prediction output rendered",
        "DOM update: evidence score refreshed to 87",
      ],
      skillRelevance: "DOM confirms candidate actively used the AI proof builder and ML inference interface — not just viewed it",
      isProtected: false,
    },
    qwenAnalysis: {
      analyzedFrameCount: 3,
      observations: [
        "Proof builder UI with AI-reviewed confidence badge visible at 0:22",
        "TensorFlow.js inference output rendered — 94.2% confidence label visible at 1:18",
        "Per-source evidence score breakdown table visible at 2:05 (Workflow: supported, GitHub: supported, OCR: partial)",
        "Score: 87/100 final evidence confidence displayed prominently",
      ],
      modelReasoning: "Qwen observed consistent AI tooling across all 3 analyzed frames: inference UI, live prediction output, and an evidence aggregation dashboard. The visual pattern matches a candidate who built and actively used an ML inference system — not a passive viewer of a demo.",
      skillMatch: "AI / Machine Learning — high confidence match based on inference UI, model output visualization, and evidence scoring dashboard",
      uncertainObservations: [
        "Frame at 1:18 shows prediction output but model architecture not visible",
        "Training code not captured in workflow — only inference/serving layer observed",
      ],
      confidence: "high",
    },
    documentEvidence: [
      {
        title: "AI Engineering Project Report",
        fileType: "PDF",
        snippet:
          "The model was trained on a custom dataset and evaluated using cross-validation. Training accuracy reached 94% on held-out test data.",
        summary:
          "Comprehensive project report (24 pages) covering design, implementation, and evaluation of a browser-based ML system. Includes model selection rationale, training methodology, experimental results, and architecture diagrams.",
        relevance: "Confirms quantitative ML evaluation — matches GitHub evidence and transcript",
        supportedSkills: ["Machine Learning", "TensorFlow.js", "Model Evaluation", "Technical Documentation"],
        mismatchWarnings: [],
        extractedSections: [
          "Section 2: Model Selection — Why TensorFlow.js was chosen for browser deployment",
          "Section 3: Training Methodology — Dataset, split, and cross-validation approach",
          "Section 4: Results — 94% accuracy on held-out test set",
          "Section 5: Architecture — Inference pipeline from input to output",
        ],
        isProtected: true,
      },
    ],
    finalAnalysis: {
      evidenceScore: 87,
      sourceScores: [
        { label: "GitHub code",             score: 91, status: "supported" },
        { label: "Workflow recording",       score: 88, status: "supported" },
        { label: "Project defense",          score: 84, status: "supported" },
        { label: "Documents",               score: 79, status: "supported" },
        { label: "Keyframes / screenshots", score: 72, status: "partial"   },
        { label: "OCR / visual reasoning",  score: 65, status: "partial"   },
      ],
      recommendation: "Strongly supported — verified across 4 of 6 sources with high confidence. Proceed to technical interview.",
      strongestProof: "GitHub code — 3 production service files confirm ML pipeline ownership. Final evaluator service is direct evidence of ML scoring implementation.",
      weakestProof: "OCR / visual reasoning — some frames inconclusive; protected frames not yet released.",
      whyGranted: "Candidate demonstrated working ML inference in browser (TensorFlow.js), implemented multi-source evidence scoring (Python services), and explained model evaluation methodology with quantitative results.",
      stillNeedsReview: [
        "Protected keyframes at 1:18 and 2:05 not yet reviewed",
        "Training code not observed in workflow — verify in GitHub if needed",
      ],
    },
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
      "This skill is backed by GitHub code artifacts and workflow recording. Component architecture, state management, and live UI interaction are all directly observable.",
    sources: [
      { key: "github",    label: "GitHub code",             status: "supported", score: 88, reason: "React components and TypeScript modules confirmed across multiple files"      },
      { key: "workflow",  label: "Workflow recording",     status: "supported", score: 75, reason: "Live frontend UI interaction captured in workflow recordings"                 },
      { key: "ocr",       label: "OCR / visual reasoning",  status: "partial",  score: 60, reason: "UI text extracted from keyframes; component boundaries partially identified" },
      { key: "keyframes", label: "Keyframes / screenshots", status: "partial",  score: 58, reason: "UI interaction captured; some frames protected"                              },
      { key: "defense",   label: "Project defense",         status: "partial",  score: 65, reason: "Architecture discussed at high level; limited implementation depth"          },
      { key: "documents", label: "Documents",               status: "missing",        reason: "No frontend-specific documentation uploaded"                                     },
    ],
    workflowRecording: {
      title: "Recruiter Passport Dashboard — UI Interaction Demo",
      duration: "3:01",
      recordedDate: "May 2026",
      sessionType: "Browser workflow proof",
      relatedSkills: ["React", "TypeScript", "UI State Management", "Next.js"],
      isProtected: false,
      segments: [
        { timestamp: "0:14", label: "React component interaction captured", reason: "Dashboard component with interactive evidence cards visible — state changes captured on click" },
        { timestamp: "1:32", label: "Proof builder state transition", reason: "Evidence panel opened and closed — confirms React state management in a live app" },
      ],
    },
    visualEvidence: [
      {
        timestamp: "0:14",
        label: "React UI interaction observed",
        pageTitle: "Recruiter Passport — VeriBridge Dashboard",
        observation: "Dashboard component with interactive evidence cards visible; state changes captured on interaction",
        ocr: "Evidence Backed Skills · High confidence · Dashboard / Proof Builder · VeriBridge",
        domContext: "React component tree with evidence cards, tab navigation, and modal trigger buttons captured in DOM snapshot",
        qwenObservation: "React-based dashboard UI visible with interactive evidence cards, tab navigation, and skill confidence badges. Component hierarchy visible through rendered DOM structure.",
        whyItSupports: "Confirms hands-on interaction with a React-based interface and working state management",
        confidence: "high",
        isProtected: false,
      },
      {
        timestamp: "1:32",
        label: "Dashboard/proof builder state changed",
        pageTitle: "VeriBridge — Evidence Proof Builder",
        observation: "Proof builder component state update captured — evidence panel opened and closed",
        ocr: "Website Proof · Session active · Evidence being captured · VeriBridge",
        domContext: "Modal overlay, evidence form, and close button captured — confirms React modal/portal state",
        qwenObservation: "Modal overlay rendered with evidence form and structured input fields. State transition from closed to open panel captured across frames.",
        whyItSupports: "Shows working knowledge of component state management — modal/portal pattern in a live app",
        confidence: "high",
        isProtected: true,
      },
    ],
    githubEvidence: [
      {
        path: "apps/web/components/recruiter-passport/RecruiterWorkPassportPreview.tsx",
        reason: "3050+ line React component implementing evidence gating, modal state, protected/public artifact rendering, and recruiter-safe output",
        skills: ["TypeScript", "React", "UI Architecture"],
        stackTags: ["TypeScript", "React", "Next.js", "Modal", "State Management"],
        confidence: "high",
        isPublic: true,
        repoUrl: VERIBRIDGE_REPO,
        branch: VERIBRIDGE_BRANCH,
        startLine: 300,
        endLine: 520,
        symbolName: "RecruiterWorkPassportPreview",
        codeBlockSummary: "Renders recruiter skill evidence hub and protected/public artifact UI with access gating logic.",
      },
      {
        path: "apps/web/components/skill-proof/extension-proof-panel.tsx",
        reason: "Manages proof lifecycle state and evidence UI for browser extension recording sessions",
        skills: ["TypeScript", "React", "State Management"],
        stackTags: ["TypeScript", "React", "Extension", "Proof Lifecycle"],
        confidence: "high",
        isPublic: true,
        repoUrl: VERIBRIDGE_REPO,
        branch: VERIBRIDGE_BRANCH,
        startLine: 120,
        endLine: 260,
        symbolName: "ExtensionProofPanel",
        codeBlockSummary: "Manages proof lifecycle state and evidence UI for browser extension recording sessions.",
      },
      {
        path: "apps/web/src/app/recruiter/passport/page.tsx",
        reason: "Recruiter passport page with tab navigation, saved candidates, and access request state management",
        skills: ["TypeScript", "Next.js", "React"],
        stackTags: ["TypeScript", "Next.js", "Page Router", "Data Fetching"],
        confidence: "medium",
        isPublic: true,
        repoUrl: VERIBRIDGE_REPO,
        branch: VERIBRIDGE_BRANCH,
        startLine: 20,
        endLine: 110,
        symbolName: "RecruiterPassportPage",
        codeBlockSummary: "Integrates Next.js route-level recruiter passport view with tab navigation and candidate data.",
      },
    ],
    transcriptEvidence: [
      {
        excerpt:
          "I structured the React component tree to separate the recruiter and student views cleanly, so neither side has access to the other's data paths.",
        fullExcerpt:
          "I structured the React component tree to separate the recruiter and student views cleanly, so neither side has access to the other's data paths. The recruiter sees a safe summary with controlled access gates, while the student controls what is revealed. This separation also makes the state model simpler — each view has its own data contract.",
        lines: [
          "The recruiter sees a safe summary with controlled access gates.",
          "The student controls what is revealed through explicit approval.",
          "Separating views simplifies the state model — each has its own data contract.",
          "I used a prop-based gating system rather than global state to keep it testable.",
        ],
        relevance: "Shows deliberate component architecture decision — ownership signal",
        ownershipSignal: "Candidate describes intentional structural choices with rationale",
        technicalDepth: "Covers component separation, data access patterns, and testability",
        skillMapping: ["React", "TypeScript", "UI Architecture", "State Management"],
        isProtected: true,
      },
    ],
    domEvidence: {
      pageTitle: "Recruiter Passport — VeriBridge Dashboard",
      urlType: "local",
      capturedLabels: [
        "Evidence Backed Skills",
        "View skill evidence",
        "High confidence badge",
        "Tab navigation: Overview / Evidence / Skills",
        "Access request button",
        "Skill group cards",
      ],
      observedSections: [
        "Recruiter work passport header with candidate score",
        "Evidence source coverage grid",
        "Skill group cards with inline proof",
        "Modal trigger for skill evidence detail",
      ],
      capturedEvents: [
        "click on View skill evidence button",
        "DOM update: skill evidence modal rendered",
        "click on tab navigation: Evidence tab",
      ],
      skillRelevance: "DOM confirms candidate built and interacted with a full React dashboard with modal state, tab navigation, and conditional rendering",
      isProtected: false,
    },
    qwenAnalysis: {
      analyzedFrameCount: 2,
      observations: [
        "React-based recruiter dashboard UI with interactive evidence cards and tab navigation visible at 0:14",
        "Modal overlay with evidence form captured at 1:32 — confirms React modal/portal pattern",
        "Skill confidence badges and source coverage grid rendered — TypeScript props-based rendering visible",
      ],
      modelReasoning: "Qwen identified a well-structured React dashboard with multiple interactive components. Tab navigation, modal state, and conditional rendering patterns are all observable. The UI complexity matches a senior React developer, not a beginner using a template.",
      skillMatch: "JavaScript / Frontend (React, TypeScript) — high confidence match based on dashboard complexity, state management patterns, and component architecture",
      uncertainObservations: [
        "Frame at 1:32 is protected — full modal interaction not confirmed without approval",
        "CSS/styling approach (Tailwind vs inline) not definitively identified from visual alone",
      ],
      confidence: "high",
    },
    documentEvidence: [],
    finalAnalysis: {
      evidenceScore: 83,
      sourceScores: [
        { label: "GitHub code",             score: 88, status: "supported" },
        { label: "Workflow recording",       score: 75, status: "supported" },
        { label: "Project defense",          score: 65, status: "partial"   },
        { label: "Keyframes / screenshots", score: 58, status: "partial"   },
        { label: "OCR / visual reasoning",  score: 60, status: "partial"   },
        { label: "Documents",               score: 0,  status: "missing"   },
      ],
      recommendation: "Strongly supported — GitHub and workflow evidence are high quality. No frontend documentation uploaded, but code speaks for itself.",
      strongestProof: "GitHub code — RecruiterWorkPassportPreview.tsx is a large, complex React component demonstrating advanced TypeScript and state management.",
      weakestProof: "Documents — no frontend documentation uploaded. Missing is expected for code-first candidates.",
      whyGranted: "Candidate built a production React dashboard (3000+ lines, TypeScript, modal state, data gating) and demonstrated live UI interaction in a workflow recording.",
      stillNeedsReview: [
        "Protected keyframe at 1:32 — full modal interaction not verified",
        "Transcript excerpt references architecture decisions — verify depth in interview",
      ],
    },
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
      "VeriBridge found this skill in workflow and OCR evidence. GitHub and transcript coverage is partial. Artifact inspection available for public evidence.",
    sources: [
      { key: "workflow",  label: "Workflow recording",     status: "supported", score: 72, reason: "Chart and dashboard interaction observed in workflow recordings"   },
      { key: "ocr",       label: "OCR / visual reasoning",  status: "partial",  score: 55, reason: "Chart/table text partially extracted from keyframes"              },
      { key: "documents", label: "Documents",               status: "partial",  score: 60, reason: "Data visualization mentioned in project report — not primary focus" },
      { key: "github",    label: "GitHub code",             status: "partial",  score: 50, reason: "D3 imports found; no dedicated data pipeline module detected"     },
      { key: "keyframes", label: "Keyframes / screenshots", status: "partial",  score: 48, reason: "Charts partially visible in protected keyframe set"               },
      { key: "defense",   label: "Project defense",         status: "missing",        reason: "Data visualization was not a focus of the defense discussion"         },
    ],
    workflowRecording: {
      title: "Data Dashboard — Chart Interaction Recording",
      duration: "2:30",
      recordedDate: "May 2026",
      sessionType: "Browser workflow proof",
      relatedSkills: ["D3.js", "Data Visualization", "Dashboard UI"],
      isProtected: false,
      segments: [
        { timestamp: "2:11", label: "Chart/table/dashboard output visible", reason: "Data visualization panel with chart output captured — confirms live data rendering" },
      ],
    },
    visualEvidence: [
      {
        timestamp: "2:11",
        label: "Chart/table/dashboard output visible",
        pageTitle: "Evidence Dashboard — Data Visualization",
        observation: "Data visualization panel with chart output captured in viewport",
        ocr: "Chart · Data output · Dashboard view · Evidence score",
        domContext: "Chart canvas element and data table captured in DOM — D3 SVG elements present",
        qwenObservation: "Bar chart and data table visible in dashboard. D3-style SVG chart elements rendered. Data labels and axis titles partially visible.",
        whyItSupports: "Confirms live interaction with a data visualization interface using D3 or equivalent library",
        confidence: "medium",
        isProtected: false,
      },
    ],
    githubEvidence: [
      {
        path: "apps/web/components/recruiter-passport/RecruiterWorkPassportPreview.tsx",
        reason: "Displays source coverage, scores, and confidence breakdowns in the evidence visualization grid",
        skills: ["TypeScript", "React", "Data Display"],
        stackTags: ["TypeScript", "React", "Data Grid", "Coverage Visualization"],
        confidence: "medium",
        isPublic: true,
        repoUrl: VERIBRIDGE_REPO,
        branch: VERIBRIDGE_BRANCH,
        startLine: 520,
        endLine: 700,
        symbolName: "EvidenceCoverageGrid",
        codeBlockSummary: "Displays source coverage, scores, and confidence breakdowns in the evidence visualization grid.",
      },
      {
        path: "apps/api/app/services/final_evidence_evaluator_service.py",
        reason: "Calculates per-source scores and final evidence score using weighted confidence aggregation",
        skills: ["Python", "Evidence Scoring", "Data Aggregation"],
        stackTags: ["Python", "FastAPI", "Scoring", "Aggregation"],
        confidence: "medium",
        isPublic: true,
        repoUrl: VERIBRIDGE_REPO,
        branch: VERIBRIDGE_BRANCH,
        startLine: 140,
        endLine: 220,
        symbolName: "evidence_scoring_aggregation",
        codeBlockSummary: "Calculates per-source scores and final evidence score using weighted confidence aggregation.",
      },
      {
        path: "apps/api/app/services/internal_analytics_service.py",
        reason: "Internal analytics aggregation — private repository, no public access",
        skills: ["Python", "Analytics"],
        stackTags: ["Python", "Analytics"],
        confidence: "low",
        isPublic: false,
      },
    ],
    transcriptEvidence: [
      {
        excerpt:
          "Data visualization was part of the project but not the primary focus — I used D3 for the chart layer.",
        fullExcerpt:
          "Data visualization was part of the project but not the primary focus — I used D3 for the chart layer and focused more on the data pipeline and transformations that fed into the charts.",
        lines: [
          "I used D3 for the chart layer.",
          "The primary focus was the data pipeline and transformations, not the chart styling.",
          "D3 gave me fine-grained control over SVG rendering for custom chart types.",
        ],
        relevance: "Acknowledges limited depth in visualization work — honest self-assessment",
        ownershipSignal: "Candidate names specific library (D3) with rationale",
        technicalDepth: "Limited — surface-level description without implementation details",
        skillMapping: ["D3.js", "Data Visualization"],
        isProtected: true,
      },
    ],
    domEvidence: {
      pageTitle: "Evidence Dashboard — Data Visualization",
      urlType: "local",
      capturedLabels: [
        "Evidence Dashboard",
        "D3 chart panel",
        "Data table",
        "Export button",
        "Filter controls",
      ],
      observedSections: [
        "Bar chart with D3 SVG rendering",
        "Data table with sortable columns",
        "Dashboard header with title and filter controls",
      ],
      capturedEvents: [
        "click on chart bar (hover tooltip appeared)",
        "DOM update: data table re-sorted on column click",
      ],
      skillRelevance: "DOM confirms D3 SVG chart and interactive data table are implemented — not just a screenshot of a chart library demo",
      isProtected: false,
    },
    qwenAnalysis: {
      analyzedFrameCount: 1,
      observations: [
        "D3-style SVG bar chart with axis labels visible at 2:11",
        "Data table with column headers captured below chart",
        "Dashboard title 'Evidence Dashboard' and filter controls visible",
      ],
      modelReasoning: "Single analyzed frame confirms a working data dashboard with chart output. Evidence is partial — only one frame captured, and chart type is basic. Coverage is not deep enough to confirm advanced D3 expertise.",
      skillMatch: "Data & Visualization — medium confidence. Basic chart rendering confirmed; advanced pipeline or custom visualization not observed.",
      uncertainObservations: [
        "Only one frame analyzed — limited coverage",
        "Chart type (bar chart) is basic — could be from a charting library, not raw D3",
        "Data pipeline feeding the chart not visible in recording",
      ],
      confidence: "medium",
    },
    documentEvidence: [
      {
        title: "AI Engineering Project Report",
        fileType: "PDF",
        snippet:
          "Three.js WebGL rendering pipeline was designed for real-time performance, targeting 60fps on standard hardware.",
        summary:
          "Project report covers data visualization as one of several components. Primary focus is on ML and backend systems. Visualization coverage is section 6 (4 pages of 24).",
        relevance: "Partial match — visual rendering is related but not core data visualization; mentions D3 and Three.js",
        supportedSkills: ["Data Visualization", "Three.js", "Performance"],
        mismatchWarnings: ["Primary evidence is ML-focused — data visualization is mentioned but not the main contribution"],
        extractedSections: [
          "Section 6: Visualization Layer — D3 chart integration and Three.js WebGL pipeline",
          "Section 6.1: Chart types used — bar, line, and scatter plots",
          "Section 6.2: Real-time rendering target — 60fps on standard hardware",
        ],
        isProtected: false,
      },
    ],
    finalAnalysis: {
      evidenceScore: 58,
      sourceScores: [
        { label: "Workflow recording",       score: 72, status: "supported" },
        { label: "Documents",               score: 60, status: "partial"   },
        { label: "GitHub code",             score: 50, status: "partial"   },
        { label: "OCR / visual reasoning",  score: 55, status: "partial"   },
        { label: "Keyframes / screenshots", score: 48, status: "partial"   },
        { label: "Project defense",          score: 0,  status: "missing"   },
      ],
      recommendation: "Partially supported — confirm depth in interview. Candidate self-reports D3 usage; basic chart rendering is confirmed but advanced data pipeline not verified.",
      strongestProof: "Workflow recording — chart and dashboard interaction observed. D3 SVG elements confirmed in DOM capture.",
      weakestProof: "Project defense — data visualization was not discussed in defense session.",
      whyGranted: "Basic data visualization confirmed via workflow recording, DOM capture, and project report. Depth is limited — treat as supporting skill, not primary.",
      stillNeedsReview: [
        "Protected keyframes — full chart interaction not verified",
        "Data pipeline implementation not observed in GitHub or workflow",
        "Advanced D3 usage not confirmed",
      ],
    },
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
      "VeriBridge found limited evidence of deployment skills. Coverage is document-only with aspirational mentions — no workflow, GitHub, or keyframe artifacts observed.",
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
        fileType: "PDF",
        snippet: "Future work includes containerizing the application for deployment.",
        summary:
          "Project report mentions deployment as future work only. No current deployment configuration, CI/CD pipeline, or infrastructure setup described.",
        relevance: "Aspirational mention only — no implemented deployment evidence",
        supportedSkills: [],
        mismatchWarnings: [
          "Deployment is listed as 'future work' — not current capability",
          "No Dockerfile, CI config, or deployment manifest found in GitHub",
        ],
        extractedSections: [
          "Section 7: Future Work — 'Future work includes containerizing the application for cloud deployment using Docker and Kubernetes.'",
        ],
        isProtected: false,
      },
    ],
    finalAnalysis: {
      evidenceScore: 22,
      sourceScores: [
        { label: "Documents",               score: 35, status: "partial"   },
        { label: "Workflow recording",       score: 0,  status: "missing"   },
        { label: "GitHub code",             score: 0,  status: "missing"   },
        { label: "OCR / visual reasoning",  score: 0,  status: "missing"   },
        { label: "Keyframes / screenshots", score: 0,  status: "missing"   },
        { label: "Project defense",          score: 0,  status: "missing"   },
      ],
      recommendation: "Needs review — only aspirational document mention found. Do not treat as confirmed skill. Probe in interview.",
      strongestProof: "Project report — mentions Docker/Kubernetes as future work goal. Shows awareness of deployment tooling.",
      weakestProof: "All sources except documents — no workflow, GitHub, keyframe, or defense evidence found.",
      whyGranted: "Not granted as confirmed skill. Listed for review only.",
      stillNeedsReview: [
        "Docker/Kubernetes experience not confirmed — aspirational only",
        "CI/CD pipeline setup not observed anywhere",
        "No deployment artifacts in GitHub repository",
      ],
    },
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

// ── Skill Evidence Pipelines — derived from bundles with new aggregation fields ─

const _PIPELINE_CATEGORY: Record<string, string> = {
  "AI / Machine Learning": "AI/ML",
  "JavaScript / Frontend": "Frontend",
  "Data & Visualization": "Data",
  "DevOps / Deployment": "DevOps",
}

const _PIPELINE_PROJECTS: Record<string, Array<{ name: string; type: string; evidenceCount: number }>> = {
  "AI / Machine Learning": [{ name: "VeriBridge AI Proof System", type: "AI/ML Web App", evidenceCount: 6 }],
  "JavaScript / Frontend": [{ name: "Recruiter Passport Dashboard", type: "React/TypeScript Dashboard", evidenceCount: 4 }],
  "Data & Visualization": [{ name: "Evidence Dashboard", type: "Data Visualization App", evidenceCount: 4 }],
  "DevOps / Deployment": [{ name: "AI Engineering Project", type: "Full-Stack Application", evidenceCount: 1 }],
}

function _buildPipeline(skillName: string, bundle: SkillEvidenceBundle): SkillEvidencePipeline {
  const ocrEvidence: OcrEvidenceItem[] = bundle.visualEvidence
    .filter((f) => f.ocr)
    .map((f) => ({
      timestamp: f.timestamp,
      extractedText: f.ocr,
      source: f.pageTitle ?? skillName,
      confidence: f.confidence,
      note: f.observation,
    }))

  const directActions: EvidenceItem[] = [
    ...(bundle.workflowRecording
      ? [
          {
            sourceType: "workflow" as const,
            sourceTitle: bundle.workflowRecording.title,
            projectName: _PIPELINE_PROJECTS[skillName]?.[0]?.name ?? skillName,
            visibility: (bundle.workflowRecording.isProtected ? "protected" : "public") as EvidenceItem["visibility"],
            relevanceToSkill: bundle.workflowRecording.relatedSkills.join(", "),
            confidence: "high" as const,
            proofReason: `${bundle.workflowRecording.segments.length} workflow segments captured`,
            artifactActionLabel: "View workflow recording",
            artifactStatus: "supported" as const,
          },
        ]
      : []),
    ...bundle.githubEvidence.map(
      (f): EvidenceItem => ({
        sourceType: "github",
        sourceTitle: f.path.split("/").pop() ?? f.path,
        projectName: _PIPELINE_PROJECTS[skillName]?.[0]?.name ?? skillName,
        visibility: f.isPublic ? "public" : "protected",
        relevanceToSkill: f.reason,
        confidence: f.confidence,
        proofReason: f.reason,
        artifactActionLabel: f.isPublic ? "Open GitHub file" : "Request access",
        artifactStatus: "supported",
      }),
    ),
    ...bundle.transcriptEvidence.map(
      (t): EvidenceItem => ({
        sourceType: "transcript",
        sourceTitle: "Project defense excerpt",
        projectName: _PIPELINE_PROJECTS[skillName]?.[0]?.name ?? skillName,
        visibility: t.isProtected ? "protected" : "public",
        relevanceToSkill: t.relevance,
        confidence: "medium",
        proofReason: t.ownershipSignal ?? t.relevance,
        artifactActionLabel: t.isProtected ? "Request access" : "View approved excerpt",
        artifactStatus: "supported",
      }),
    ),
    ...bundle.documentEvidence.map(
      (d): EvidenceItem => ({
        sourceType: "document",
        sourceTitle: d.title,
        projectName: _PIPELINE_PROJECTS[skillName]?.[0]?.name ?? skillName,
        visibility: d.isProtected ? "protected" : "public",
        relevanceToSkill: d.relevance,
        confidence: "medium",
        proofReason: d.relevance,
        artifactActionLabel: d.isProtected ? "Request access" : "View document",
        artifactStatus: d.relevance.includes("aspirational") ? "needs-review" : "supported",
      }),
    ),
    ...(bundle.domEvidence
      ? [
          {
            sourceType: "dom" as const,
            sourceTitle: "DOM Evidence",
            projectName: _PIPELINE_PROJECTS[skillName]?.[0]?.name ?? skillName,
            visibility: (bundle.domEvidence.isProtected ? "protected" : "public") as EvidenceItem["visibility"],
            relevanceToSkill: bundle.domEvidence.skillRelevance,
            confidence: "medium" as const,
            proofReason: "Captured page structure, visible UI labels, and proof builder state changes support this skill.",
            artifactActionLabel: bundle.domEvidence.isProtected ? "Request access" : "View DOM capture",
            artifactStatus: "supported" as const,
          },
        ]
      : []),
  ]

  return {
    skillId: skillName.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
    skillName: bundle.skillName,
    category: _PIPELINE_CATEGORY[skillName] ?? skillName,
    confidence: bundle.confidence,
    supportStatus: bundle.supportStatus,
    overallExplanation: bundle.explanation,
    evidenceSources: bundle.sources,
    codeEvidence: bundle.githubEvidence,
    workflowEvidence: bundle.workflowRecording ? [bundle.workflowRecording] : [],
    visualEvidence: bundle.visualEvidence,
    ocrEvidence,
    domEvidence: bundle.domEvidence ? [bundle.domEvidence] : [],
    qwenEvidence: bundle.qwenAnalysis ? [bundle.qwenAnalysis] : [],
    transcriptEvidence: bundle.transcriptEvidence,
    documentEvidence: bundle.documentEvidence,
    projects: _PIPELINE_PROJECTS[skillName] ?? [{ name: skillName, type: "Project", evidenceCount: bundle.sources.filter((s) => s.status === "supported").length }],
    directActions,
    interviewQuestions: bundle.interviewQuestions,
    protectedEvidenceFlags: bundle.protectedEvidenceFlags,
    finalAnalysis: bundle.finalAnalysis,
    liveApp: bundle.liveApp,
  }
}

const SKILL_EVIDENCE_PIPELINES: Record<string, SkillEvidencePipeline> = Object.fromEntries(
  Object.entries(SKILL_EVIDENCE_BUNDLES).map(([k, v]) => [k, _buildPipeline(k, v)]),
)

export function getSkillPipeline(skillName: string): SkillEvidencePipeline {
  if (SKILL_EVIDENCE_PIPELINES[skillName]) return SKILL_EVIDENCE_PIPELINES[skillName]
  const bundle = getSkillBundle(skillName)
  return _buildPipeline(skillName, bundle)
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

// ── Proof Artifact Components ─────────────────────────────────────────────────
// Each component renders one class of proof artifact with full inspection detail.
// Privacy: no raw storage paths, tokens, localhost URLs, or Supabase URLs exposed.

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

function ArtifactBadge({ label, color, bg, border }: { label: string; color: string; bg: string; border: string }) {
  return (
    <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4, color, background: bg, border: `1px solid ${border}`, flexShrink: 0 }}>
      {label}
    </span>
  )
}

function ArtifactSectionHeader({ title, count, color }: { title: string; count?: number; color?: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
      <span style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.06em", textTransform: "uppercase" as const, color: color ?? C.ink }}>{title}</span>
      {count !== undefined && (
        <span style={{ fontSize: 9, fontWeight: 700, padding: "1px 6px", borderRadius: 4, background: C.bg, color: C.muted, border: `1px solid ${C.line}` }}>{count}</span>
      )}
    </div>
  )
}

// ── Artifact Access Summary ───────────────────────────────────────────────────

function ArtifactAccessSummary({ bundle, accessApproved }: { bundle: SkillEvidenceBundle; accessApproved: boolean }) {
  const hasProtected = bundle.protectedEvidenceFlags.length > 0
  const items = [
    { label: "Workflow recording",    public: !!(bundle.workflowRecording && !bundle.workflowRecording.isProtected), available: !!bundle.workflowRecording },
    { label: "Keyframes / OCR / DOM", public: bundle.visualEvidence.some(f => !f.isProtected),                      available: bundle.visualEvidence.length > 0 },
    { label: "GitHub code",           public: bundle.githubEvidence.some(f => f.isPublic),                           available: bundle.githubEvidence.length > 0 },
    { label: "Transcript",            public: bundle.transcriptEvidence.some(t => !t.isProtected),                  available: bundle.transcriptEvidence.length > 0 },
    { label: "Documents",             public: bundle.documentEvidence.some(d => !d.isProtected),                    available: bundle.documentEvidence.length > 0 },
    { label: "Final analysis",        public: !!bundle.finalAnalysis,                                                available: !!bundle.finalAnalysis },
  ]
  return (
    <div data-testid="skill-artifact-access-summary" style={{ padding: "12px 14px", background: C.bg, border: `1px solid ${C.line}`, borderRadius: 8 }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
        <ArtifactBadge label="Public — visible now"      color={C.emerald} bg={C.emeraldSoft} border="#bbf7d0" />
        {hasProtected && !accessApproved && <ArtifactBadge label="Protected — approval needed" color={C.indigo} bg={C.indigoSoft} border="#c7d2fe" />}
        {hasProtected && accessApproved  && <ArtifactBadge label="Approved — protected unlocked" color={C.violet} bg={C.violetSoft} border="#ddd6fe" />}
        {!bundle.workflowRecording && bundle.visualEvidence.length === 0 && <ArtifactBadge label="Limited artifacts" color={C.amber} bg={C.amberSoft} border="#fde68a" />}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 5 }}>
        {items.filter(it => it.available).map(it => (
          <div key={it.label} style={{ display: "flex", alignItems: "center", gap: 5, padding: "4px 7px", borderRadius: 5, background: C.paper, border: `1px solid ${C.line}`, fontSize: 10 }}>
            <span style={{ color: it.public || accessApproved ? C.emerald : C.indigo, fontSize: 12, flexShrink: 0 }}>
              {it.public || accessApproved ? "✓" : "🔒"}
            </span>
            <span style={{ color: C.inkSoft, fontWeight: 500 }}>{it.label}</span>
          </div>
        ))}
      </div>
      <p style={{ fontSize: 10, color: C.muted, margin: "8px 0 0", fontStyle: "italic" }}>
        Student controls visibility per proof type. Raw files and storage paths are never exposed.
      </p>
    </div>
  )
}

// ── Workflow Recording Artifact ───────────────────────────────────────────────

function WorkflowRecordingArtifact({ recording, accessApproved }: { recording: SkillWorkflowRecording; accessApproved: boolean }) {
  const canView = !recording.isProtected || accessApproved
  return (
    <div data-testid="skill-artifact-workflow-recording">
      <ArtifactSectionHeader title="Workflow Recording" color={C.violet} />
      {!canView ? (
        <SkillProtectedLock label="Workflow recording" />
      ) : (
        <div style={{ border: `1px solid #ddd6fe`, borderRadius: 8, overflow: "hidden" }}>
          {/* Recording header */}
          <div style={{ padding: "10px 14px", background: "#1e1b4b", display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
            <div>
              <p style={{ fontSize: 13, fontWeight: 700, color: "#e0e7ff", margin: "0 0 3px" }}>{recording.title}</p>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontSize: 10, color: "#a5b4fc" }}>Duration: {recording.duration}</span>
                <span style={{ fontSize: 10, color: "#a5b4fc" }}>Recorded: {recording.recordedDate}</span>
                <span style={{ fontSize: 10, color: "#a5b4fc" }}>Type: {recording.sessionType}</span>
              </div>
            </div>
            <ArtifactBadge label={recording.isProtected ? (accessApproved ? "Approved" : "Protected") : "Public"} color={recording.isProtected ? (accessApproved ? C.violet : C.indigo) : C.emerald} bg={recording.isProtected ? (accessApproved ? C.violetSoft : C.indigoSoft) : C.emeraldSoft} border={recording.isProtected ? (accessApproved ? "#ddd6fe" : "#c7d2fe") : "#bbf7d0"} />
          </div>
          {/* Related skills */}
          <div style={{ padding: "8px 14px", background: "#13102b", borderBottom: "1px solid #312e81", display: "flex", gap: 5, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ fontSize: 9, fontWeight: 700, color: "#6366f1", textTransform: "uppercase" as const }}>Skills observed:</span>
            {recording.relatedSkills.map(sk => (
              <span key={sk} style={{ fontSize: 9, padding: "1px 6px", borderRadius: 4, background: C.indigoSoft, color: C.indigo, border: "1px solid #c7d2fe", fontWeight: 600 }}>{sk}</span>
            ))}
          </div>
          {/* Placeholder viewer */}
          <div data-testid="workflow-recording-viewer" style={{ padding: "12px 14px", background: "#0f172a", borderBottom: "1px solid #1e293b" }}>
            <div style={{ borderRadius: 6, background: "#1e293b", border: "1px solid #334155", padding: "10px 12px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <span style={{ fontSize: 10, color: "#64748b", fontWeight: 600 }}>Timeline scrubber</span>
                <span style={{ fontSize: 9, color: "#475569" }}>Duration: {recording.duration}</span>
              </div>
              <div style={{ height: 6, background: "#334155", borderRadius: 3, position: "relative" as const, marginBottom: 10 }}>
                <div style={{ width: "40%", height: "100%", background: "#6366f1", borderRadius: 3 }} />
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {recording.segments.map((seg, i) => (
                  <span key={i} style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4, background: "#1e293b", color: "#94a3b8", border: "1px solid #334155" }}>{seg.timestamp}</span>
                ))}
              </div>
            </div>
            <p style={{ fontSize: 10, color: "#475569", margin: "8px 0 0", fontStyle: "italic" }}>
              Raw recording artifact will load here when backend media URL is connected.
            </p>
          </div>
          {/* Segments */}
          <div style={{ padding: "10px 14px", display: "flex", flexDirection: "column", gap: 7 }}>
            <span style={{ fontSize: 9, fontWeight: 800, letterSpacing: "0.07em", textTransform: "uppercase" as const, color: C.muted }}>Segments</span>
            {recording.segments.map((seg, i) => (
              <div key={i} style={{ padding: "8px 10px", background: C.bg, border: `1px solid ${C.line}`, borderRadius: 6, display: "flex", gap: 10, alignItems: "flex-start" }}>
                <span style={{ fontSize: 10, fontWeight: 700, color: C.indigo, flexShrink: 0, fontFamily: "monospace" }}>{seg.timestamp}</span>
                <div>
                  <p style={{ fontSize: 11, fontWeight: 600, color: C.ink, margin: "0 0 2px" }}>{seg.label}</p>
                  <p style={{ fontSize: 10, color: C.inkSoft, margin: 0, lineHeight: 1.4 }}>{seg.reason}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Keyframe / OCR / DOM / Qwen Artifact ─────────────────────────────────────

function KeyframeArtifactSection({
  frames, qwenAnalysis, domEvidence, accessApproved,
}: {
  frames: SkillVisualFrame[]
  qwenAnalysis?: SkillQwenAnalysis
  domEvidence?: SkillDomEvidence
  accessApproved: boolean
}) {
  const [expandedFrame, setExpandedFrame] = useState<number | null>(null)

  return (
    <div data-testid="skill-artifact-keyframes">
      <ArtifactSectionHeader title="Keyframes, OCR & Visual Reasoning" count={frames.length} color="#7c3aed" />

      {/* Per-frame artifact cards */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {frames.map((frame, i) => {
          const canView = !frame.isProtected || accessApproved
          const isExpanded = expandedFrame === i
          return (
            <div key={i} data-testid={`keyframe-artifact-${i}`} style={{ borderRadius: 8, overflow: "hidden", border: canView ? "1px solid #334155" : "1px solid #4f46e5" }}>
              <div style={{ padding: "10px 14px", background: canView ? "#1e293b" : "#1e1b4b" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6, flexWrap: "wrap", marginBottom: 6 }}>
                  <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", fontFamily: "monospace" }}>{frame.timestamp}</span>
                    {frame.pageTitle && <span style={{ fontSize: 10, color: "#64748b" }}>{frame.pageTitle}</span>}
                  </div>
                  <div style={{ display: "flex", gap: 5 }}>
                    <ArtifactBadge
                      label={frame.isProtected ? (accessApproved ? "Approved" : "Protected") : "Public"}
                      color={frame.isProtected ? (accessApproved ? "#7c3aed" : "#818cf8") : C.emerald}
                      bg={frame.isProtected ? (accessApproved ? "#ede9fe" : "#1e1b4b") : C.emeraldSoft}
                      border={frame.isProtected ? (accessApproved ? "#ddd6fe" : "#4f46e5") : "#bbf7d0"}
                    />
                    <ArtifactBadge
                      label={`${frame.confidence} confidence`}
                      color={frame.confidence === "high" ? C.emerald : frame.confidence === "medium" ? C.amber : C.muted}
                      bg={frame.confidence === "high" ? C.emeraldSoft : frame.confidence === "medium" ? C.amberSoft : C.bg}
                      border={frame.confidence === "high" ? "#bbf7d0" : frame.confidence === "medium" ? "#fde68a" : C.line}
                    />
                  </div>
                </div>
                {canView ? (
                  <>
                    <p style={{ fontSize: 12, fontWeight: 600, color: "#e2e8f0", margin: "0 0 4px" }}>{frame.label}</p>
                    <p style={{ fontSize: 11, color: "#94a3b8", margin: 0, lineHeight: 1.4 }}>{frame.observation}</p>
                    <button
                      type="button"
                      data-testid={`expand-keyframe-${i}`}
                      onClick={() => setExpandedFrame(isExpanded ? null : i)}
                      style={{ marginTop: 8, fontSize: 10, fontWeight: 600, padding: "3px 9px", borderRadius: 4, cursor: "pointer", color: "#a5b4fc", background: "#312e81", border: "1px solid #4f46e5" }}
                    >
                      {isExpanded ? "Hide details" : "View full keyframe details"}
                    </button>
                  </>
                ) : (
                  <p style={{ fontSize: 11, color: "#818cf8", margin: 0 }}>Protected keyframe — student approval required to view OCR, DOM, and Qwen observations.</p>
                )}
              </div>
              {isExpanded && canView && (
                <div data-testid={`keyframe-detail-${i}`} style={{ padding: "12px 14px", background: "#0f172a", display: "flex", flexDirection: "column", gap: 9 }}>
                  {/* OCR */}
                  <div data-testid={`keyframe-ocr-${i}`} style={{ padding: "8px 10px", background: "#1e293b", borderRadius: 6, border: "1px solid #334155" }}>
                    <p style={{ fontSize: 9, fontWeight: 800, color: "#7c3aed", textTransform: "uppercase" as const, margin: "0 0 4px", letterSpacing: "0.07em" }}>OCR extracted text</p>
                    <code style={{ fontSize: 11, color: "#e2e8f0", fontFamily: "monospace", lineHeight: 1.5, display: "block" }}>{frame.ocr}</code>
                  </div>
                  {/* DOM */}
                  {frame.domContext && (
                    <div data-testid={`keyframe-dom-${i}`} style={{ padding: "8px 10px", background: "#1e293b", borderRadius: 6, border: "1px solid #334155" }}>
                      <p style={{ fontSize: 9, fontWeight: 800, color: C.sky, textTransform: "uppercase" as const, margin: "0 0 4px", letterSpacing: "0.07em" }}>DOM context</p>
                      <p style={{ fontSize: 11, color: "#94a3b8", margin: 0, lineHeight: 1.5 }}>{frame.domContext}</p>
                    </div>
                  )}
                  {/* Qwen */}
                  {frame.qwenObservation && (
                    <div data-testid={`keyframe-qwen-${i}`} style={{ padding: "8px 10px", background: "#1e293b", borderRadius: 6, border: "1px solid #334155" }}>
                      <p style={{ fontSize: 9, fontWeight: 800, color: C.amber, textTransform: "uppercase" as const, margin: "0 0 4px", letterSpacing: "0.07em" }}>Qwen visual observation</p>
                      <p style={{ fontSize: 11, color: "#94a3b8", margin: 0, lineHeight: 1.5 }}>{frame.qwenObservation}</p>
                    </div>
                  )}
                  {/* Why */}
                  <div style={{ padding: "8px 10px", background: "#1a0f2e", borderRadius: 6, border: "1px solid #6d28d9" }}>
                    <p style={{ fontSize: 9, fontWeight: 800, color: "#a78bfa", textTransform: "uppercase" as const, margin: "0 0 4px", letterSpacing: "0.07em" }}>Why this supports the skill</p>
                    <p style={{ fontSize: 11, color: "#c4b5fd", margin: 0, lineHeight: 1.5 }}>{frame.whyItSupports}</p>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Qwen analysis summary */}
      {qwenAnalysis && (
        <div data-testid="skill-artifact-qwen" style={{ marginTop: 12, border: `1px solid #fde68a`, borderRadius: 8, overflow: "hidden" }}>
          <div style={{ padding: "9px 14px", background: C.amberSoft, display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 6 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: "#92400e" }}>Qwen / Visual Reasoning Summary</span>
            <div style={{ display: "flex", gap: 5 }}>
              <ArtifactBadge label={`${qwenAnalysis.analyzedFrameCount} frames analyzed`} color={C.amber} bg="#fff" border="#fde68a" />
              <ArtifactBadge label={`${qwenAnalysis.confidence} confidence`} color={qwenAnalysis.confidence === "high" ? C.emerald : C.amber} bg={qwenAnalysis.confidence === "high" ? C.emeraldSoft : C.amberSoft} border={qwenAnalysis.confidence === "high" ? "#bbf7d0" : "#fde68a"} />
            </div>
          </div>
          <div style={{ padding: "12px 14px", background: C.paper, display: "flex", flexDirection: "column", gap: 9 }}>
            <div>
              <p style={{ fontSize: 9, fontWeight: 800, textTransform: "uppercase" as const, letterSpacing: "0.07em", color: C.muted, margin: "0 0 4px" }}>Observations</p>
              <ul style={{ margin: 0, paddingLeft: 16, display: "flex", flexDirection: "column", gap: 3 }}>
                {qwenAnalysis.observations.map((obs, i) => (
                  <li key={i} style={{ fontSize: 11, color: C.inkSoft, lineHeight: 1.5 }}>{obs}</li>
                ))}
              </ul>
            </div>
            <div style={{ padding: "8px 10px", background: C.amberSoft, borderRadius: 6, border: "1px solid #fde68a" }}>
              <p style={{ fontSize: 9, fontWeight: 800, textTransform: "uppercase" as const, letterSpacing: "0.07em", color: "#92400e", margin: "0 0 4px" }}>Model reasoning</p>
              <p style={{ fontSize: 11, color: "#78350f", margin: 0, lineHeight: 1.5 }}>{qwenAnalysis.modelReasoning}</p>
            </div>
            <div>
              <p style={{ fontSize: 9, fontWeight: 800, textTransform: "uppercase" as const, letterSpacing: "0.07em", color: C.indigo, margin: "0 0 4px" }}>Skill match</p>
              <p style={{ fontSize: 11, color: C.inkSoft, margin: 0 }}>{qwenAnalysis.skillMatch}</p>
            </div>
            {qwenAnalysis.uncertainObservations.length > 0 && (
              <div>
                <p style={{ fontSize: 9, fontWeight: 800, textTransform: "uppercase" as const, letterSpacing: "0.07em", color: C.muted, margin: "0 0 4px" }}>Uncertain / not confirmed</p>
                <ul style={{ margin: 0, paddingLeft: 16, display: "flex", flexDirection: "column", gap: 2 }}>
                  {qwenAnalysis.uncertainObservations.map((obs, i) => (
                    <li key={i} style={{ fontSize: 10, color: C.muted, fontStyle: "italic", lineHeight: 1.4 }}>{obs}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}

      {/* DOM evidence */}
      {domEvidence && (
        <div data-testid="skill-artifact-dom" style={{ marginTop: 12, border: `1px solid ${C.line}`, borderRadius: 8, overflow: "hidden" }}>
          <div style={{ padding: "9px 14px", background: C.skySoft, display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 6 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: "#0c4a6e" }}>DOM Evidence</span>
            <div style={{ display: "flex", gap: 5 }}>
              <ArtifactBadge label={`URL: ${domEvidence.urlType}`} color={domEvidence.urlType === "public" ? C.emerald : C.indigo} bg={domEvidence.urlType === "public" ? C.emeraldSoft : C.indigoSoft} border={domEvidence.urlType === "public" ? "#bbf7d0" : "#c7d2fe"} />
              <ArtifactBadge label={domEvidence.isProtected ? "Protected" : "Public"} color={domEvidence.isProtected ? C.indigo : C.emerald} bg={domEvidence.isProtected ? C.indigoSoft : C.emeraldSoft} border={domEvidence.isProtected ? "#c7d2fe" : "#bbf7d0"} />
            </div>
          </div>
          <div style={{ padding: "12px 14px", background: C.paper, display: "flex", flexDirection: "column", gap: 9 }}>
            <div>
              <p style={{ fontSize: 10, fontWeight: 700, color: C.ink, margin: "0 0 2px" }}>Page: {domEvidence.pageTitle}</p>
              {domEvidence.urlType === "local" && (
                <p style={{ fontSize: 10, color: C.muted, margin: 0, fontStyle: "italic" }}>Local/private URL hidden from recruiter. DOM evidence is shown because student approved this proof.</p>
              )}
            </div>
            <div>
              <p style={{ fontSize: 9, fontWeight: 800, textTransform: "uppercase" as const, letterSpacing: "0.07em", color: C.muted, margin: "0 0 5px" }}>Captured labels & elements</p>
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                {domEvidence.capturedLabels.map((lbl, i) => (
                  <code key={i} style={{ fontSize: 10, padding: "2px 7px", borderRadius: 4, background: C.bg, color: C.indigo, border: `1px solid ${C.line}`, fontFamily: "monospace" }}>{lbl}</code>
                ))}
              </div>
            </div>
            <div>
              <p style={{ fontSize: 9, fontWeight: 800, textTransform: "uppercase" as const, letterSpacing: "0.07em", color: C.muted, margin: "0 0 5px" }}>Observed sections</p>
              <ul style={{ margin: 0, paddingLeft: 16, display: "flex", flexDirection: "column", gap: 3 }}>
                {domEvidence.observedSections.map((sec, i) => (
                  <li key={i} style={{ fontSize: 11, color: C.inkSoft, lineHeight: 1.4 }}>{sec}</li>
                ))}
              </ul>
            </div>
            {domEvidence.capturedEvents && domEvidence.capturedEvents.length > 0 && (
              <div>
                <p style={{ fontSize: 9, fontWeight: 800, textTransform: "uppercase" as const, letterSpacing: "0.07em", color: C.muted, margin: "0 0 5px" }}>Captured events</p>
                <ul style={{ margin: 0, paddingLeft: 16, display: "flex", flexDirection: "column", gap: 2 }}>
                  {domEvidence.capturedEvents.map((ev, i) => (
                    <li key={i} style={{ fontSize: 10, color: C.inkSoft, fontFamily: "monospace", lineHeight: 1.4 }}>{ev}</li>
                  ))}
                </ul>
              </div>
            )}
            <p style={{ fontSize: 10, color: C.sky, fontWeight: 600, margin: 0 }}>Skill relevance: {domEvidence.skillRelevance}</p>
          </div>
        </div>
      )}
    </div>
  )
}

// ── GitHub Code Artifact ──────────────────────────────────────────────────────

function GithubArtifactSection({ files, accessApproved }: { files: SkillGithubFile[]; accessApproved: boolean }) {
  if (files.length === 0) {
    return (
      <div data-testid="skill-artifact-github">
        <ArtifactSectionHeader title="GitHub Code" color={C.emerald} />
        <div style={{ padding: "12px 14px", background: C.bg, border: `1px solid ${C.line}`, borderRadius: 8 }}>
          <p style={{ fontSize: 12, color: C.muted, margin: 0, fontStyle: "italic" }}>No GitHub code evidence detected for this skill.</p>
        </div>
      </div>
    )
  }
  return (
    <div data-testid="skill-artifact-github">
      <ArtifactSectionHeader title="GitHub Code" count={files.length} color={C.emerald} />
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {files.map((file, i) => {
          const hasLineRange = file.startLine != null && file.endLine != null
          const exactCodeUrl = file.isPublic && file.repoUrl && file.branch && hasLineRange
            ? `${file.repoUrl}/blob/${file.branch}/${file.path}#L${file.startLine}-L${file.endLine}`
            : null
          const fullFileUrl = file.isPublic && file.repoUrl && file.branch
            ? `${file.repoUrl}/blob/${file.branch}/${file.path}`
            : null
          const repoUrl = file.isPublic && file.repoUrl ? file.repoUrl : null
          return (
            <div key={i} data-testid={`github-artifact-${i}`} style={{ border: `1px solid ${file.isPublic ? "#bbf7d0" : C.line}`, borderRadius: 8, overflow: "hidden" }}>
              {/* Header: path + symbol + line range + badges */}
              <div style={{ padding: "8px 14px", background: file.isPublic ? C.emeraldSoft : C.bg, display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <code style={{ fontSize: 11, color: file.isPublic ? "#065f46" : C.indigo, fontFamily: "monospace", wordBreak: "break-all" as const, display: "block", marginBottom: 4 }}>
                    {file.path}
                  </code>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                    {file.symbolName && (
                      <span style={{ fontSize: 10, fontWeight: 700, color: C.ink }}>
                        {file.symbolName}
                      </span>
                    )}
                    {hasLineRange && (
                      <span
                        data-testid={`github-line-range-${i}`}
                        style={{
                          fontSize: 10, fontWeight: 700, fontFamily: "monospace",
                          padding: "1px 7px", borderRadius: 4,
                          background: "#f0fdf4", color: "#065f46", border: "1px solid #bbf7d0",
                        }}
                      >
                        L{file.startLine}–L{file.endLine}
                      </span>
                    )}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 5, flexShrink: 0 }}>
                  <ArtifactBadge label={file.isPublic ? "Public repo" : "Private repo"} color={file.isPublic ? C.emerald : C.indigo} bg={file.isPublic ? "#fff" : C.indigoSoft} border={file.isPublic ? "#bbf7d0" : "#c7d2fe"} />
                  <ArtifactBadge label={`${file.confidence} confidence`} color={file.confidence === "high" ? C.emerald : file.confidence === "medium" ? C.amber : C.muted} bg={file.confidence === "high" ? C.emeraldSoft : file.confidence === "medium" ? C.amberSoft : C.bg} border={file.confidence === "high" ? "#bbf7d0" : file.confidence === "medium" ? "#fde68a" : C.line} />
                </div>
              </div>
              {/* Body: summaries, tags, buttons */}
              <div style={{ padding: "10px 14px", background: C.paper }}>
                {file.codeBlockSummary && (
                  <p style={{ fontSize: 11, color: C.ink, fontWeight: 600, margin: "0 0 4px", lineHeight: 1.5 }}>{file.codeBlockSummary}</p>
                )}
                <p style={{ fontSize: 11, color: C.inkSoft, margin: "0 0 8px", lineHeight: 1.5 }}>{file.reason}</p>
                {file.stackTags && file.stackTags.length > 0 && (
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 10 }}>
                    {file.stackTags.map(tag => (
                      <span key={tag} style={{ fontSize: 9, fontWeight: 600, padding: "1px 6px", borderRadius: 4, background: C.indigoSoft, color: C.indigo, border: "1px solid #c7d2fe" }}>{tag}</span>
                    ))}
                  </div>
                )}
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {fullFileUrl ? (
                    <>
                      {exactCodeUrl ? (
                        <a
                          href={exactCodeUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          data-testid={`github-open-exact-${i}`}
                          style={{ fontSize: 10, fontWeight: 700, padding: "4px 10px", borderRadius: 5, color: "#065f46", background: "#f0fdf4", border: "1px solid #bbf7d0", textDecoration: "none" }}
                        >
                          ↗ Open exact code block
                        </a>
                      ) : (
                        <button
                          type="button"
                          disabled
                          title="Exact code block not mapped yet."
                          data-testid={`github-open-exact-${i}`}
                          style={{ fontSize: 10, fontWeight: 700, padding: "4px 10px", borderRadius: 5, color: C.muted, background: C.bg, border: `1px solid ${C.line}`, cursor: "not-allowed", opacity: 0.6 }}
                        >
                          Open exact code block
                        </button>
                      )}
                      <a
                        href={fullFileUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        data-testid={`github-open-file-${i}`}
                        style={{ fontSize: 10, fontWeight: 700, padding: "4px 10px", borderRadius: 5, color: C.emerald, background: C.emeraldSoft, border: "1px solid #bbf7d0", textDecoration: "none" }}
                      >
                        ↗ Open full file
                      </a>
                      {repoUrl && (
                        <a
                          href={repoUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          data-testid={`github-open-repo-${i}`}
                          style={{ fontSize: 10, fontWeight: 700, padding: "4px 10px", borderRadius: 5, color: C.indigo, background: C.indigoSoft, border: "1px solid #c7d2fe", textDecoration: "none" }}
                        >
                          ↗ Open repository
                        </a>
                      )}
                    </>
                  ) : (
                    <div data-testid={`github-locked-${i}`} style={{ padding: "5px 10px", borderRadius: 5, background: "#1e1b4b", border: "1px solid #4f46e5", display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ fontSize: 11 }}>🔒</span>
                      <span style={{ fontSize: 10, color: "#a5b4fc" }}>Source file access requires student approval or public repository access.</span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Transcript Artifact ───────────────────────────────────────────────────────

function TranscriptArtifactSection({
  excerpts,
  accessApproved,
  skillName,
}: {
  excerpts: SkillTranscriptExcerpt[]
  accessApproved: boolean
  skillName?: string
}) {
  const [expanded, setExpanded] = useState<number | null>(null)

  const handleDownloadTxt = () => {
    const approved = excerpts.filter((t) => !t.isProtected || accessApproved)
    if (approved.length === 0) return
    const lines: string[] = [
      "VeriBridge Transcript Export — Recruiter Safe",
      `Generated: ${new Date().toLocaleDateString()}`,
      ...(skillName ? [`Skill: ${skillName}`] : []),
      "Note: Recruiter-safe transcript export. Raw media URLs and private metadata excluded.",
      "",
      "--- Approved Transcript Excerpts ---",
      "",
    ]
    approved.forEach((t, idx) => {
      lines.push(`Excerpt ${idx + 1}:`)
      lines.push(`"${t.fullExcerpt ?? t.excerpt}"`)
      if (t.ownershipSignal) lines.push(`Ownership signal: ${t.ownershipSignal}`)
      if (t.technicalDepth) lines.push(`Technical depth: ${t.technicalDepth}`)
      if (t.skillMapping && t.skillMapping.length > 0) lines.push(`Skills: ${t.skillMapping.join(", ")}`)
      if (t.lines && t.lines.length > 0) {
        lines.push("Key lines:")
        t.lines.forEach((line) => lines.push(`  > ${line}`))
      }
      lines.push("")
    })
    const blob = new Blob([lines.join("\n")], { type: "text/plain" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = skillName
      ? `transcript-${skillName.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.txt`
      : "transcript-export.txt"
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  if (excerpts.length === 0) {
    return (
      <div data-testid="skill-artifact-transcript">
        <ArtifactSectionHeader title="Project Defense Transcript" color={C.sky} />
        <div style={{ padding: "12px 14px", background: C.bg, border: `1px solid ${C.line}`, borderRadius: 8 }}>
          <p style={{ fontSize: 12, color: C.muted, margin: 0, fontStyle: "italic" }}>No transcript evidence for this skill.</p>
        </div>
      </div>
    )
  }
  return (
    <div data-testid="skill-artifact-transcript">
      <ArtifactSectionHeader title="Project Defense Transcript" count={excerpts.length} color={C.sky} />
      {/* Transcript download actions */}
      <div data-testid="transcript-download-actions" style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
        <button
          type="button"
          data-testid="download-transcript-txt-btn"
          onClick={handleDownloadTxt}
          style={{
            fontSize: 10, fontWeight: 600, padding: "3px 9px", borderRadius: 5,
            cursor: "pointer", color: C.sky, background: C.skySoft, border: "1px solid #bae6fd",
          }}
        >
          Download transcript TXT
        </button>
        <button
          type="button"
          data-testid="download-transcript-pdf-btn"
          disabled
          title="PDF export will be enabled when transcript export service is connected."
          style={{
            fontSize: 10, fontWeight: 600, padding: "3px 9px", borderRadius: 5,
            cursor: "not-allowed", color: C.muted, background: C.bg,
            border: `1px solid ${C.line}`, opacity: 0.55,
          }}
        >
          Download transcript PDF
        </button>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {excerpts.map((t, i) => {
          const canView = !t.isProtected || accessApproved
          const isExpanded = expanded === i
          return (
            <div key={i} data-testid={`transcript-artifact-${i}`} style={{ border: `1px solid ${canView ? "#bae6fd" : "#4f46e5"}`, borderRadius: 8, overflow: "hidden" }}>
              <div style={{ padding: "9px 14px", background: canView ? C.skySoft : "#1e1b4b", display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 6 }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: canView ? "#0c4a6e" : "#a5b4fc" }}>Project defense excerpt {i + 1}</span>
                <ArtifactBadge label={t.isProtected ? (accessApproved ? "Approved" : "Protected") : "Public"} color={t.isProtected ? (accessApproved ? C.violet : "#818cf8") : C.sky} bg={t.isProtected ? (accessApproved ? C.violetSoft : "#1e1b4b") : C.skySoft} border={t.isProtected ? (accessApproved ? "#ddd6fe" : "#4f46e5") : "#bae6fd"} />
              </div>
              {canView ? (
                <div style={{ padding: "12px 14px", background: C.paper }}>
                  <blockquote style={{ fontSize: 12, color: C.inkSoft, lineHeight: 1.8, margin: "0 0 10px", padding: "0 0 0 14px", borderLeft: `3px solid ${C.sky}`, fontStyle: "italic" }}>
                    &ldquo;{t.excerpt}&rdquo;
                  </blockquote>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
                    {t.ownershipSignal && (
                      <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 4, background: C.emeraldSoft, color: C.emerald, border: "1px solid #bbf7d0" }}>
                        Ownership: {t.ownershipSignal}
                      </span>
                    )}
                    {t.technicalDepth && (
                      <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 4, background: C.indigoSoft, color: C.indigo, border: "1px solid #c7d2fe" }}>
                        Depth: {t.technicalDepth}
                      </span>
                    )}
                  </div>
                  {t.skillMapping && t.skillMapping.length > 0 && (
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 8 }}>
                      {t.skillMapping.map(sk => (
                        <span key={sk} style={{ fontSize: 9, fontWeight: 600, padding: "1px 6px", borderRadius: 4, background: C.indigoSoft, color: C.indigo, border: "1px solid #c7d2fe" }}>{sk}</span>
                      ))}
                    </div>
                  )}
                  {(t.fullExcerpt || t.lines) && (
                    <button
                      type="button"
                      data-testid={`expand-transcript-${i}`}
                      onClick={() => setExpanded(isExpanded ? null : i)}
                      style={{ fontSize: 10, fontWeight: 600, padding: "3px 9px", borderRadius: 4, cursor: "pointer", color: C.sky, background: C.skySoft, border: "1px solid #bae6fd" }}
                    >
                      {isExpanded ? "Hide full excerpt" : "View full approved transcript"}
                    </button>
                  )}
                  {isExpanded && (
                    <div data-testid={`transcript-full-${i}`} style={{ marginTop: 10 }}>
                      {t.fullExcerpt && (
                        <blockquote style={{ fontSize: 12, color: C.inkSoft, lineHeight: 1.8, margin: "0 0 10px", padding: "0 0 0 14px", borderLeft: `3px solid ${C.indigo}`, fontStyle: "italic" }}>
                          &ldquo;{t.fullExcerpt}&rdquo;
                        </blockquote>
                      )}
                      {t.lines && t.lines.length > 0 && (
                        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                          {t.lines.map((line, j) => (
                            <div key={j} style={{ padding: "6px 10px", background: C.bg, border: `1px solid ${C.line}`, borderRadius: 5, fontSize: 11, color: C.inkSoft, lineHeight: 1.5 }}>
                              <span style={{ color: C.sky, marginRight: 6, fontWeight: 700 }}>›</span>{line}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ) : (
                <div style={{ padding: "12px 14px" }}>
                  <p style={{ fontSize: 11, color: "#818cf8", margin: 0 }}>Full transcript requires student approval. Request access to view approved excerpts and technical depth signals.</p>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Document / PDF Artifact ───────────────────────────────────────────────────

function DocumentArtifactSection({ docs, accessApproved }: { docs: SkillDocumentSnippet[]; accessApproved: boolean }) {
  const [expanded, setExpanded] = useState<number | null>(null)

  if (docs.length === 0) {
    return (
      <div data-testid="skill-artifact-documents">
        <ArtifactSectionHeader title="Documents / PDF" color={C.amber} />
        <div style={{ padding: "12px 14px", background: C.bg, border: `1px solid ${C.line}`, borderRadius: 8 }}>
          <p style={{ fontSize: 12, color: C.muted, margin: 0, fontStyle: "italic" }}>No document evidence for this skill.</p>
        </div>
      </div>
    )
  }
  return (
    <div data-testid="skill-artifact-documents">
      <ArtifactSectionHeader title="Documents / PDF" count={docs.length} color={C.amber} />
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {docs.map((doc, i) => {
          const canView = !doc.isProtected || accessApproved
          const isExpanded = expanded === i
          return (
            <div key={i} data-testid={`document-artifact-${i}`} style={{ border: `1px solid ${canView ? "#fde68a" : "#4f46e5"}`, borderRadius: 8, overflow: "hidden" }}>
              <div style={{ padding: "9px 14px", background: canView ? C.amberSoft : "#1e1b4b", display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 6 }}>
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: canView ? "#92400e" : "#a5b4fc" }}>{doc.title}</span>
                  {doc.fileType && <ArtifactBadge label={doc.fileType} color={C.amber} bg="#fff" border="#fde68a" />}
                </div>
                <ArtifactBadge label={doc.isProtected ? (accessApproved ? "Approved" : "Protected") : "Public"} color={doc.isProtected ? (accessApproved ? C.violet : "#818cf8") : C.emerald} bg={doc.isProtected ? (accessApproved ? C.violetSoft : "#1e1b4b") : C.emeraldSoft} border={doc.isProtected ? (accessApproved ? "#ddd6fe" : "#4f46e5") : "#bbf7d0"} />
              </div>
              {canView ? (
                <div style={{ padding: "12px 14px", background: C.paper, display: "flex", flexDirection: "column", gap: 8 }}>
                  {doc.summary && (
                    <p style={{ fontSize: 11, color: C.inkSoft, margin: 0, lineHeight: 1.5, fontStyle: "italic" }}>{doc.summary}</p>
                  )}
                  <blockquote style={{ fontSize: 11, color: C.inkSoft, lineHeight: 1.7, margin: 0, padding: "0 0 0 12px", borderLeft: `3px solid ${C.amber}`, fontStyle: "italic" }}>
                    &ldquo;{doc.snippet}&rdquo;
                  </blockquote>
                  <p style={{ fontSize: 10, color: C.muted, margin: 0 }}><strong>Relevance:</strong> {doc.relevance}</p>
                  {doc.supportedSkills && doc.supportedSkills.length > 0 && (
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {doc.supportedSkills.map(sk => (
                        <span key={sk} style={{ fontSize: 9, fontWeight: 600, padding: "1px 6px", borderRadius: 4, background: C.amberSoft, color: "#92400e", border: "1px solid #fde68a" }}>{sk}</span>
                      ))}
                    </div>
                  )}
                  {doc.mismatchWarnings && doc.mismatchWarnings.length > 0 && (
                    <div style={{ padding: "6px 10px", borderRadius: 5, background: "#fff7ed", border: "1px solid #fed7aa" }}>
                      {doc.mismatchWarnings.map((w, j) => (
                        <p key={j} style={{ fontSize: 10, color: "#c2410c", margin: 0, lineHeight: 1.4 }}>⚠ {w}</p>
                      ))}
                    </div>
                  )}
                  {doc.extractedSections && doc.extractedSections.length > 0 && (
                    <>
                      <button
                        type="button"
                        data-testid={`expand-document-${i}`}
                        onClick={() => setExpanded(isExpanded ? null : i)}
                        style={{ fontSize: 10, fontWeight: 600, padding: "3px 9px", borderRadius: 4, cursor: "pointer", color: C.amber, background: C.amberSoft, border: "1px solid #fde68a", width: "fit-content" as const }}
                      >
                        {isExpanded ? "Hide extracted text" : "View extracted text sections"}
                      </button>
                      {isExpanded && (
                        <div data-testid={`document-sections-${i}`} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                          {doc.extractedSections.map((sec, j) => (
                            <div key={j} style={{ padding: "6px 10px", background: C.bg, border: `1px solid ${C.line}`, borderRadius: 5, fontSize: 11, color: C.inkSoft, lineHeight: 1.5 }}>
                              <span style={{ color: C.amber, marginRight: 6 }}>›</span>{sec}
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                  {/* Document artifact actions */}
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <button
                      type="button"
                      data-testid={`open-document-btn-${i}`}
                      onClick={() => {}}
                      style={{
                        fontSize: 10, fontWeight: 600, padding: "3px 9px", borderRadius: 5,
                        cursor: "pointer", color: C.amber, background: C.amberSoft, border: "1px solid #fde68a",
                      }}
                    >
                      Open approved document
                    </button>
                    <button
                      type="button"
                      data-testid={`download-document-btn-${i}`}
                      onClick={() => {}}
                      style={{
                        fontSize: 10, fontWeight: 600, padding: "3px 9px", borderRadius: 5,
                        cursor: "pointer", color: C.amber, background: C.amberSoft, border: "1px solid #fde68a",
                      }}
                    >
                      Download document
                    </button>
                  </div>
                  {accessApproved && (
                    <div data-testid={`document-approved-viewer-${i}`} style={{ padding: "8px 10px", borderRadius: 5, background: C.amberSoft, border: "1px solid #fde68a" }}>
                      <p style={{ fontSize: 10, color: "#92400e", fontWeight: 600, margin: "0 0 2px" }}>Approved document file viewer</p>
                      <p style={{ fontSize: 10, color: "#78350f", margin: 0, fontStyle: "italic" }}>
                        Approved document file viewer will load here when document URL is connected.
                      </p>
                    </div>
                  )}
                </div>
              ) : (
                <div data-testid={`document-download-locked-${i}`} style={{ padding: "12px 14px" }}>
                  <p style={{ fontSize: 11, color: "#818cf8", margin: 0 }}>Document download requires student approval. Request access to view extracted text and document summary.</p>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Final Evidence Analysis Artifact ─────────────────────────────────────────

function FinalAnalysisArtifact({ analysis }: { analysis: SkillFinalAnalysis }) {
  const scoreColor = analysis.evidenceScore >= 80 ? C.emerald : analysis.evidenceScore >= 55 ? C.amber : C.rose
  const scoreBg    = analysis.evidenceScore >= 80 ? C.emeraldSoft : analysis.evidenceScore >= 55 ? C.amberSoft : C.bg
  const statusColor: Record<string, string> = { supported: C.emerald, partial: C.amber, missing: C.muted }
  const statusBg:    Record<string, string> = { supported: C.emeraldSoft, partial: C.amberSoft, missing: C.bg }

  return (
    <div data-testid="skill-artifact-final-analysis">
      <ArtifactSectionHeader title="Final Evidence Analysis" color={C.indigo} />
      <div style={{ border: `1px solid ${C.line}`, borderRadius: 8, overflow: "hidden" }}>
        {/* Score header */}
        <div style={{ padding: "12px 16px", background: scoreBg, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div>
            <span style={{ fontSize: 28, fontWeight: 900, color: scoreColor }}>{analysis.evidenceScore}</span>
            <span style={{ fontSize: 14, color: scoreColor }}>/100</span>
            <p style={{ fontSize: 11, color: scoreColor, margin: "2px 0 0", fontWeight: 600 }}>Evidence score</p>
          </div>
          <div style={{ flex: 1, maxWidth: 400 }}>
            <p style={{ fontSize: 11, color: C.inkSoft, margin: 0, lineHeight: 1.5 }}>{analysis.recommendation}</p>
          </div>
        </div>
        {/* Per-source scores */}
        <div style={{ padding: "12px 16px", borderTop: `1px solid ${C.line}`, display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: 7 }}>
          {analysis.sourceScores.map((src, i) => (
            <div key={i} style={{ padding: "7px 10px", background: statusBg[src.status] ?? C.bg, border: `1px solid ${(statusColor[src.status] ?? C.muted) + "44"}`, borderRadius: 6, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 10, color: C.ink, fontWeight: 600 }}>{src.label}</span>
              <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                {src.score > 0 && <span style={{ fontSize: 11, fontWeight: 700, color: statusColor[src.status] ?? C.muted }}>{src.score}</span>}
                <span style={{ fontSize: 9, fontWeight: 700, padding: "1px 5px", borderRadius: 4, color: statusColor[src.status] ?? C.muted, background: (statusColor[src.status] ?? C.muted) + "22" }}>{src.status}</span>
              </div>
            </div>
          ))}
        </div>
        {/* Analysis details */}
        <div style={{ padding: "12px 16px", borderTop: `1px solid ${C.line}`, display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div style={{ padding: "8px 10px", background: C.emeraldSoft, borderRadius: 6, border: "1px solid #bbf7d0" }}>
              <p style={{ fontSize: 9, fontWeight: 800, textTransform: "uppercase" as const, color: C.emerald, margin: "0 0 3px", letterSpacing: "0.07em" }}>Strongest proof</p>
              <p style={{ fontSize: 11, color: C.inkSoft, margin: 0, lineHeight: 1.4 }}>{analysis.strongestProof}</p>
            </div>
            <div style={{ padding: "8px 10px", background: C.amberSoft, borderRadius: 6, border: "1px solid #fde68a" }}>
              <p style={{ fontSize: 9, fontWeight: 800, textTransform: "uppercase" as const, color: C.amber, margin: "0 0 3px", letterSpacing: "0.07em" }}>Weakest proof</p>
              <p style={{ fontSize: 11, color: C.inkSoft, margin: 0, lineHeight: 1.4 }}>{analysis.weakestProof}</p>
            </div>
          </div>
          <div style={{ padding: "8px 10px", background: C.indigoSoft, borderRadius: 6, border: "1px solid #c7d2fe" }}>
            <p style={{ fontSize: 9, fontWeight: 800, textTransform: "uppercase" as const, color: C.indigo, margin: "0 0 3px", letterSpacing: "0.07em" }}>Why this skill was granted</p>
            <p style={{ fontSize: 11, color: C.inkSoft, margin: 0, lineHeight: 1.5 }}>{analysis.whyGranted}</p>
          </div>
          {analysis.stillNeedsReview.length > 0 && (
            <div style={{ padding: "8px 10px", background: C.bg, borderRadius: 6, border: `1px solid ${C.line}` }}>
              <p style={{ fontSize: 9, fontWeight: 800, textTransform: "uppercase" as const, color: C.muted, margin: "0 0 4px", letterSpacing: "0.07em" }}>Still needs review</p>
              <ul style={{ margin: 0, paddingLeft: 16, display: "flex", flexDirection: "column", gap: 3 }}>
                {analysis.stillNeedsReview.map((item, j) => (
                  <li key={j} style={{ fontSize: 10, color: C.muted, lineHeight: 1.4 }}>{item}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// DirectProofLinksSection removed — replaced by dedicated artifact sections (WorkflowRecordingArtifact,
// KeyframeArtifactSection, GithubArtifactSection, TranscriptArtifactSection, etc.) inside SkillEvidenceDetailModal.

function _DirectProofLinksSection_REMOVED({
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
                          href={`${file.repoUrl ?? VERIBRIDGE_REPO}/blob/${file.branch ?? VERIBRIDGE_BRANCH}/${file.path}`}
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
        <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 28, overflowY: "auto" }}>

          {/* 1. Source coverage + access model */}
          <div>
            <div data-testid="skill-evidence-source-coverage">
              <SectionTitle>Evidence source coverage</SectionTitle>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 8, marginBottom: 12 }}>
                {bundle.sources.map((source) => (
                  <SkillSourceCoverageCard key={source.key} source={source} />
                ))}
              </div>
            </div>
            <ArtifactAccessSummary bundle={bundle} accessApproved={accessApproved} />
          </div>

          {/* 2. Workflow recording artifact */}
          {bundle.workflowRecording && (
            <WorkflowRecordingArtifact recording={bundle.workflowRecording} accessApproved={accessApproved} />
          )}
          {!bundle.workflowRecording && bundle.sources.some(s => s.key === "workflow" && s.status === "missing") && (
            <div data-testid="skill-artifact-workflow-recording">
              <ArtifactSectionHeader title="Workflow Recording" color={C.violet} />
              <div style={{ padding: "12px 14px", background: C.bg, border: `1px solid ${C.line}`, borderRadius: 8 }}>
                <p style={{ fontSize: 12, color: C.muted, margin: 0, fontStyle: "italic" }}>No workflow recording captured for this skill. Candidate did not record a deployment or CI/CD session.</p>
              </div>
            </div>
          )}

          {/* 3. Keyframe / OCR / DOM / Qwen artifacts */}
          {(bundle.visualEvidence.length > 0 || bundle.qwenAnalysis || bundle.domEvidence) ? (
            <KeyframeArtifactSection
              frames={bundle.visualEvidence}
              qwenAnalysis={bundle.qwenAnalysis}
              domEvidence={bundle.domEvidence}
              accessApproved={accessApproved}
            />
          ) : (
            <div data-testid="skill-artifact-keyframes">
              <ArtifactSectionHeader title="Keyframes, OCR & Visual Reasoning" color="#7c3aed" />
              <div style={{ padding: "12px 14px", background: C.bg, border: `1px solid ${C.line}`, borderRadius: 8 }}>
                <p style={{ fontSize: 12, color: C.muted, margin: 0, fontStyle: "italic" }}>No keyframe or visual artifacts captured for this skill.</p>
              </div>
            </div>
          )}

          {/* 4. GitHub code artifacts */}
          <GithubArtifactSection files={bundle.githubEvidence} accessApproved={accessApproved} />

          {/* 5. Transcript artifact */}
          <TranscriptArtifactSection excerpts={bundle.transcriptEvidence} accessApproved={accessApproved} skillName={bundle.skillName} />

          {/* 6. Document artifact */}
          <DocumentArtifactSection docs={bundle.documentEvidence} accessApproved={accessApproved} />

          {/* 7. Final evidence analysis */}
          {bundle.finalAnalysis && (
            <FinalAnalysisArtifact analysis={bundle.finalAnalysis} />
          )}

          {/* 8. Interview questions */}
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
            This modal shows actual proof artifacts — workflow recordings, keyframes with OCR/DOM/Qwen, GitHub direct file links, transcript excerpts, and document extracts.
          </p>
          <p style={{ fontSize: 11, color: C.muted, margin: "2px 0 0", fontStyle: "italic" }}>
            Raw files and storage paths are never exposed. Protected evidence requires explicit student approval.
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
