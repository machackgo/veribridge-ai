"use client"

/**
 * skill-proof-center.tsx — Phase J4A
 * Unified Skill Proof Center: renders saved SkillEvidenceResponse[] as
 * grouped hierarchical skill cards with source badges and redirect links.
 *
 * Data is fetched by the parent (StudentProofSubmissionPanel).
 * This component is purely presentational — no write operations.
 */

import { useMemo, useState } from "react"
import type { CSSProperties } from "react"
import type { SkillEvidenceResponse } from "@/lib/api"
import {
  groupSavedEvidence,
  getEvidenceActionLabel,
  getEvidenceRedirectUrl,
  getEvidenceSourceLabel,
  mapEvidenceSourceType,
  type ConfidenceLevel,
  type EvidenceSource,
  type GroupedSkillSuggestion,
  type SkillEvidence,
  type SkillSystemGraph,
} from "@/lib/skill-grouping"

// ── Shared badge / style helpers ──────────────────────────────────────────────

const badgeBase: CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: "0.1em",
  textTransform: "uppercase",
  padding: "3px 8px",
  borderRadius: 999,
}

function confidenceStyle(level: ConfidenceLevel): CSSProperties {
  if (level === "high") return { background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }
  if (level === "medium") return { background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a" }
  return { background: "#f1f5f9", color: "#475569", border: "1px solid #e2e8f0" }
}

function categoryStyle(category: string): CSSProperties {
  const palette: Record<string, { bg: string; color: string; border: string }> = {
    "AI / ML":   { bg: "#ede9fe", color: "#5b21b6", border: "1px solid #ddd6fe" },
    Backend:     { bg: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" },
    Frontend:    { bg: "#ecfdf5", color: "#065f46", border: "1px solid #a7f3d0" },
    Operations:  { bg: "#fff7ed", color: "#9a3412", border: "1px solid #fed7aa" },
    Cloud:       { bg: "#f0f9ff", color: "#0c4a6e", border: "1px solid #bae6fd" },
    Data:        { bg: "#fdf4ff", color: "#7e22ce", border: "1px solid #e9d5ff" },
    Game:        { bg: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca" },
  }
  const p = palette[category] ?? { bg: "#f1f5f9", color: "#334155", border: "1px solid #e2e8f0" }
  return { background: p.bg, color: p.color, border: p.border }
}

function sourceBadgeStyle(source: EvidenceSource): CSSProperties {
  const palette: Record<EvidenceSource, { bg: string; color: string; border: string }> = {
    github:      { bg: "#f1f5f9", color: "#1e293b", border: "1px solid #e2e8f0" },
    website:     { bg: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" },
    linkedin:    { bg: "#e0f2fe", color: "#0369a1", border: "1px solid #bae6fd" },
    certificate: { bg: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a" },
    youtube:     { bg: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca" },
    pdf:         { bg: "#f8fafc", color: "#475569", border: "1px solid #e2e8f0" },
    portfolio:   { bg: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0" },
    manual:      { bg: "#faf5ff", color: "#6b21a8", border: "1px solid #e9d5ff" },
    other:       { bg: "#f1f5f9", color: "#475569", border: "1px solid #e2e8f0" },
  }
  const p = palette[source]
  return { background: p.bg, color: p.color, border: p.border }
}

function statusStyle(status: string): CSSProperties {
  if (status === "verified") return { background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }
  if (status === "needs_review") return { background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a" }
  if (status === "skill_usage_not_found") return { background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca" }
  return { background: "#f1f5f9", color: "#475569", border: "1px solid #e2e8f0" }
}

function statusLabel(status: string): string {
  if (status === "verified") return "Accepted"
  if (status === "needs_review") return "Needs Review"
  if (status === "skill_usage_not_found") return "Not Verified"
  return "Pending"
}

// ── System graph view ─────────────────────────────────────────────────────────

function SystemGraphView({ graph }: { graph: SkillSystemGraph }) {
  return (
    <div style={{ marginTop: 4 }}>
      <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--muted)", marginBottom: 8 }}>
        Skill System Graph
        {graph.needsReview && (
          <span style={{ ...badgeBase, background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a", marginLeft: 8, fontSize: 9 }}>
            Needs Review
          </span>
        )}
      </div>
      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 10 }}>{graph.summary}</div>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: 4,
          padding: "10px 12px",
          background: "var(--bg-2)",
          borderRadius: 10,
          border: "1px solid var(--line)",
        }}
      >
        {graph.nodes.map((node, i) => (
          <div key={node.id} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <div
              title={node.description}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                padding: "4px 10px",
                borderRadius: 8,
                fontSize: 11,
                fontWeight: 600,
                background: node.hasEvidence ? "#dcfce7" : "#f1f5f9",
                color: node.hasEvidence ? "#166534" : "#64748b",
                border: node.hasEvidence ? "1px solid #bbf7d0" : "1px solid #e2e8f0",
                cursor: "default",
                whiteSpace: "nowrap",
              }}
            >
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: node.hasEvidence ? "#22c55e" : "#cbd5e1", flexShrink: 0 }} />
              {node.label}
              {node.evidenceCount > 0 && (
                <span style={{ fontSize: 9, fontWeight: 800, color: "#166534" }}>({node.evidenceCount})</span>
              )}
            </div>
            {i < graph.nodes.length - 1 && (
              <span style={{ color: "var(--muted)", fontSize: 12, fontWeight: 700 }}>→</span>
            )}
          </div>
        ))}
      </div>
      <div style={{ marginTop: 6, fontSize: 11, color: "var(--muted)", display: "flex", gap: 12 }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#22c55e", display: "inline-block" }} />
          Supported by evidence
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#cbd5e1", display: "inline-block" }} />
          Inferred
        </span>
      </div>
    </div>
  )
}

// ── Saved evidence item row ───────────────────────────────────────────────────

function SavedEvidenceRow({
  evidence,
  redirectUrl,
}: {
  evidence: SkillEvidence
  redirectUrl: string | null
}) {
  const source = evidence.evidenceSource
  const hasFileLocation = evidence.filePath && evidence.lineStart > 1
  const actionLabel = getEvidenceActionLabel(
    source === "github" ? "github repository"
    : source === "website" ? "deployed website"
    : source
  )

  return (
    <div
      style={{
        padding: "10px 12px",
        border: "1px solid var(--line)",
        borderRadius: 8,
        background: "var(--bg-2)",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      {/* Top row: title + badges */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8, flexWrap: "wrap" }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "var(--ink)" }}>
          {evidence.projectTitle}
        </div>
        <div style={{ display: "flex", gap: 5, flexShrink: 0 }}>
          <span style={{ ...badgeBase, ...sourceBadgeStyle(source), fontSize: 9 }}>
            {getEvidenceSourceLabel(
              source === "github" ? "github repository"
              : source === "website" ? "deployed website"
              : source
            )}
          </span>
          <span style={{ ...badgeBase, ...statusStyle(evidence.suggestedStatus), fontSize: 9 }}>
            {statusLabel(evidence.suggestedStatus)}
          </span>
        </div>
      </div>

      {/* File location for GitHub evidence */}
      {hasFileLocation && (
        <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "var(--muted)" }}>
          {evidence.filePath}
          <span style={{ marginLeft: 6, fontWeight: 700 }}>L{evidence.lineStart}–L{evidence.lineEnd}</span>
        </div>
      )}

      {/* Description */}
      {evidence.evidenceDescription && (
        <div style={{ fontSize: 11, color: "var(--ink-2)", lineHeight: 1.5 }}>
          {evidence.evidenceDescription}
        </div>
      )}

      {/* Redirect link */}
      {redirectUrl ? (
        <a
          href={redirectUrl}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          style={{ fontSize: 11, fontWeight: 600, color: "var(--indigo)", textDecoration: "none", alignSelf: "flex-start" }}
        >
          {actionLabel} →
        </a>
      ) : source !== "manual" ? null : (
        <span style={{ fontSize: 11, color: "var(--muted)" }}>No external link — stored as text proof</span>
      )}
    </div>
  )
}

// ── Skill card (read-only, no selection) ──────────────────────────────────────

function SkillProofCard({
  group,
  expanded,
  onToggleExpand,
  savedEvidence,
}: {
  group: GroupedSkillSuggestion
  expanded: boolean
  onToggleExpand: (id: string) => void
  savedEvidence: SkillEvidenceResponse[]
}) {
  // Build a lookup for redirect URLs keyed by candidateId (= evidence.id)
  const redirectUrls = useMemo(() => {
    const map = new Map<string, string | null>()
    for (const e of savedEvidence) {
      if (group.evidenceItems.some((gi) => gi.candidateId === e.id)) {
        map.set(e.id, getEvidenceRedirectUrl(e))
      }
    }
    return map
  }, [group.evidenceItems, savedEvidence])

  // Deduplicated sources in this group
  const sources = [...new Set(group.evidenceItems.map((e) => e.evidenceSource))]

  return (
    <div
      style={{
        border: "1px solid var(--line)",
        borderRadius: 14,
        background: "#fff",
      }}
    >
      {/* Header row */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr auto",
          gap: 12,
          padding: "14px 16px",
          alignItems: "flex-start",
        }}
      >
        <div style={{ minWidth: 0 }}>
          {/* Skill name + tags */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
            <span style={{ fontSize: 15, fontWeight: 700, color: "var(--ink)" }}>{group.skillName}</span>
            <span style={{ ...badgeBase, ...categoryStyle(group.category), fontSize: 9 }}>{group.category}</span>
            <span style={{ ...badgeBase, ...confidenceStyle(group.confidence) }}>
              {group.confidence}
            </span>
          </div>

          {/* Evidence summary */}
          <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>
            <strong style={{ color: "var(--ink-2)" }}>{group.evidenceCount}</strong> saved item{group.evidenceCount !== 1 ? "s" : ""} ·{" "}
            <strong style={{ color: "var(--ink-2)" }}>{group.repoCount}</strong> source{group.repoCount !== 1 ? "s" : ""}
          </div>

          {/* Source badges */}
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 4 }}>
            {sources.map((src) => (
              <span
                key={`${group.id}-src-${src}`}
                style={{ ...badgeBase, ...sourceBadgeStyle(src), fontSize: 9 }}
              >
                {getEvidenceSourceLabel(
                  src === "github" ? "github repository"
                  : src === "website" ? "deployed website"
                  : src
                )}
              </span>
            ))}
          </div>

          {/* Subskill chips */}
          {group.subskills.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
              {group.subskills.slice(0, 7).map((s) => (
                <span
                  key={`${group.id}-sub-${s.name}`}
                  style={{
                    fontSize: 10,
                    padding: "2px 8px",
                    borderRadius: 6,
                    background: "#f1f5f9",
                    color: "#334155",
                    border: "1px solid #e2e8f0",
                    whiteSpace: "nowrap",
                  }}
                >
                  {s.name}
                  {s.evidenceCount > 1 && <span style={{ marginLeft: 3, color: "#94a3b8" }}>×{s.evidenceCount}</span>}
                </span>
              ))}
              {group.subskills.length > 7 && (
                <span style={{ fontSize: 10, color: "var(--muted)", padding: "2px 4px" }}>
                  +{group.subskills.length - 7} more
                </span>
              )}
            </div>
          )}
        </div>

        {/* Expand toggle */}
        <button
          type="button"
          onClick={() => onToggleExpand(group.id)}
          style={{
            border: "1px solid var(--line-2)",
            background: "transparent",
            color: "var(--ink-2)",
            borderRadius: 8,
            padding: "6px 10px",
            fontSize: 12,
            fontWeight: 600,
            cursor: "pointer",
            whiteSpace: "nowrap",
            flexShrink: 0,
          }}
        >
          {expanded ? "Collapse ▲" : "Expand ▼"}
        </button>
      </div>

      {/* Expanded content */}
      {expanded && (
        <div
          style={{
            borderTop: "1px solid var(--line)",
            padding: "16px",
            display: "flex",
            flexDirection: "column",
            gap: 18,
          }}
        >
          {/* Subskills detail */}
          {group.subskills.length > 0 && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--muted)", marginBottom: 8 }}>
                Subskills & capabilities
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {group.subskills.map((s) => (
                  <span
                    key={`${group.id}-detail-sub-${s.name}`}
                    style={{
                      fontSize: 11,
                      padding: "4px 10px",
                      borderRadius: 8,
                      background: "#f1f5f9",
                      color: "#334155",
                      border: "1px solid #e2e8f0",
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 5,
                    }}
                  >
                    {s.name}
                    <span style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8" }}>{s.evidenceCount}</span>
                  </span>
                ))}
              </div>
              <div style={{ marginTop: 8, fontSize: 11, color: "var(--muted)" }}>
                Sources: {group.repositories.join(", ")}
              </div>
            </div>
          )}

          {/* System graph */}
          {group.systemGraph && group.systemGraph.nodes.some((n) => n.hasEvidence) && (
            <SystemGraphView graph={group.systemGraph} />
          )}

          {/* Evidence by project/source */}
          {group.projectGroups.map((proj) => (
            <div key={`${group.id}-proj-${proj.repoName}`}>
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 700,
                  color: "var(--ink-2)",
                  marginBottom: 8,
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  flexWrap: "wrap",
                }}
              >
                <span>{proj.projectTitle}</span>
                <span style={{ fontWeight: 400, color: "var(--muted)" }}>
                  ({proj.evidenceItems.length} item{proj.evidenceItems.length !== 1 ? "s" : ""})
                </span>
                {proj.repoUrl && (
                  <a
                    href={proj.repoUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    style={{ fontSize: 11, color: "var(--indigo)", textDecoration: "none", fontWeight: 600 }}
                  >
                    {proj.repoName} ↗
                  </a>
                )}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {proj.evidenceItems.map((ev) => (
                  <SavedEvidenceRow
                    key={`sev-${ev.candidateId}`}
                    evidence={ev}
                    redirectUrl={redirectUrls.get(ev.candidateId) ?? null}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Source filter ─────────────────────────────────────────────────────────────

type SourceFilter = "all" | EvidenceSource

function groupHasSource(group: GroupedSkillSuggestion, source: EvidenceSource): boolean {
  return group.evidenceItems.some((e) => e.evidenceSource === source)
}

// ── Main component ────────────────────────────────────────────────────────────

export function SkillProofCenter({
  evidence,
  loading,
}: {
  evidence: SkillEvidenceResponse[]
  loading: boolean
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all")
  const [showRaw, setShowRaw] = useState(false)

  const grouped = useMemo(() => groupSavedEvidence(evidence), [evidence])

  // Tally sources across all evidence
  const sourceCounts = useMemo(() => {
    const counts = new Map<EvidenceSource, number>()
    for (const e of evidence) {
      const src = mapEvidenceSourceType(e.evidence_type)
      counts.set(src, (counts.get(src) ?? 0) + 1)
    }
    return counts
  }, [evidence])

  const filteredGroups = useMemo(() => {
    if (sourceFilter === "all") return grouped
    return grouped.filter((g) => groupHasSource(g, sourceFilter))
  }, [grouped, sourceFilter])

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <section
      data-testid="skill-proof-center"
      style={{ display: "flex", flexDirection: "column", gap: 16 }}
    >
      {/* Header */}
      <div>
        <div
          style={{
            fontSize: 11,
            fontWeight: 800,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: "var(--muted)",
            marginBottom: 4,
          }}
        >
          Skill Proof Center
        </div>
        <div style={{ fontSize: 13, color: "var(--muted)", lineHeight: 1.5 }}>
          All your saved evidence organized by skill across GitHub, websites, manual proof, and future sources.
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div style={{ color: "var(--muted)", fontSize: 13 }}>Loading saved evidence…</div>
      )}

      {/* Empty state */}
      {!loading && evidence.length === 0 && (
        <div
          style={{
            border: "1px dashed var(--line-2)",
            borderRadius: 14,
            padding: 24,
            textAlign: "center",
            color: "var(--muted)",
            fontSize: 13,
            lineHeight: 1.7,
          }}
        >
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6, color: "var(--ink-2)" }}>
            No saved skill proof yet.
          </div>
          Add GitHub, website, or manual proof above to build your Skill Proof Center.
        </div>
      )}

      {/* Grouped skill cards */}
      {!loading && grouped.length > 0 && (
        <>
          {/* Summary + source filter tabs */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
            <div style={{ fontSize: 12, color: "var(--muted)" }}>
              <strong style={{ color: "var(--ink-2)" }}>{grouped.length}</strong> grouped skill{grouped.length !== 1 ? "s" : ""} from{" "}
              <strong style={{ color: "var(--ink-2)" }}>{evidence.length}</strong> evidence item{evidence.length !== 1 ? "s" : ""}
            </div>

            {/* Source filter tabs */}
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
              {(["all", ...sourceCounts.keys()] as SourceFilter[]).map((src) => {
                const label =
                  src === "all"
                    ? `All (${grouped.length})`
                    : `${getEvidenceSourceLabel(src === "github" ? "github repository" : src === "website" ? "deployed website" : src)} (${sourceCounts.get(src as EvidenceSource) ?? 0})`
                return (
                  <button
                    key={`filter-${src}`}
                    type="button"
                    onClick={() => setSourceFilter(src)}
                    style={{
                      border: sourceFilter === src ? "1px solid var(--indigo)" : "1px solid var(--line-2)",
                      background: sourceFilter === src ? "var(--indigo-soft)" : "transparent",
                      color: sourceFilter === src ? "var(--indigo)" : "var(--ink-2)",
                      borderRadius: 8,
                      padding: "5px 10px",
                      fontSize: 11,
                      fontWeight: 600,
                      cursor: "pointer",
                    }}
                  >
                    {label}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Cards */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {filteredGroups.map((group) => (
              <SkillProofCard
                key={`pc-group-${group.id}`}
                group={group}
                expanded={expanded.has(group.id)}
                onToggleExpand={toggleExpand}
                savedEvidence={evidence}
              />
            ))}
          </div>

          {/* Advanced: raw evidence accordion */}
          <div style={{ border: "1px solid var(--line)", borderRadius: 10 }}>
            <button
              type="button"
              onClick={() => setShowRaw((p) => !p)}
              style={{
                width: "100%",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "10px 14px",
                background: "var(--bg-2)",
                border: "none",
                borderRadius: showRaw ? "10px 10px 0 0" : 10,
                cursor: "pointer",
                fontSize: 12,
                fontWeight: 600,
                color: "var(--ink-2)",
              }}
            >
              <span>Advanced: all saved evidence ({evidence.length} items)</span>
              <span>{showRaw ? "▲" : "▼"}</span>
            </button>
            {showRaw && (
              <div style={{ padding: "10px 14px", display: "flex", flexDirection: "column", gap: 6 }}>
                {evidence.map((e) => {
                  const redirectUrl = getEvidenceRedirectUrl(e)
                  const src = mapEvidenceSourceType(e.evidence_type)
                  const meta = (e.metadata as Record<string, unknown> | undefined) ?? {}
                  const title = typeof meta.evidence_title === "string" && meta.evidence_title ? meta.evidence_title : e.skill_name
                  return (
                    <div
                      key={`raw-ev-${e.id}`}
                      style={{
                        padding: "8px 10px",
                        border: "1px solid var(--line)",
                        borderRadius: 8,
                        background: "#fff",
                        display: "flex",
                        flexDirection: "column",
                        gap: 4,
                        fontSize: 12,
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                        <span style={{ fontWeight: 700, color: "var(--ink)" }}>{title}</span>
                        <div style={{ display: "flex", gap: 4 }}>
                          <span style={{ ...badgeBase, ...sourceBadgeStyle(src), fontSize: 9 }}>
                            {getEvidenceSourceLabel(e.evidence_type)}
                          </span>
                          <span style={{ ...badgeBase, ...statusStyle(e.verification_status), fontSize: 9 }}>
                            {statusLabel(e.verification_status)}
                          </span>
                        </div>
                      </div>
                      <div style={{ color: "var(--muted)" }}>
                        {e.skill_name} · {e.evidence_type}
                      </div>
                      {redirectUrl && (
                        <a
                          href={redirectUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ fontSize: 11, fontWeight: 600, color: "var(--indigo)", textDecoration: "none" }}
                        >
                          {getEvidenceActionLabel(e.evidence_type)} →
                        </a>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </>
      )}
    </section>
  )
}
