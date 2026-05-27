"use client"

import { useEffect, useState } from "react"
import {
  getSkillEvidenceTimeline,
  getPublicSkillEvidenceTimeline,
  type SkillEvidenceTimelineResponse,
  type SkillEvidenceRecord,
  type SkillEvidenceItem,
} from "@/lib/passport-api"
import {
  Badge,
  Btn,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  LoadingState,
  Mono,
  ProgressBar,
  SupportLevelBadge,
  TOKEN,
} from "./shared"

function EvidenceTypeIcon({ type }: { type: string }) {
  const icons: Record<string, string> = {
    workflow: "⚙️",
    github: "🐙",
    live_website: "🌐",
    project_defense: "🎯",
    ai_domain_review: "🤖",
    privacy_scan: "🔏",
    readiness_report: "📋",
    version_snapshot: "📸",
    future_upload: "📎",
  }
  return <span>{icons[type] ?? "📄"}</span>
}

function StrengthBar({ score }: { score: number }) {
  const color = score >= 75 ? TOKEN.emerald : score >= 40 ? TOKEN.amber : TOKEN.rose
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <ProgressBar value={score} color={color} height={5} />
      <Mono style={{ fontSize: 10, color: TOKEN.muted, width: 28, flexShrink: 0 }}>{score}%</Mono>
    </div>
  )
}

function EvidenceItemRow({ item }: { item: SkillEvidenceItem }) {
  const strengthColors: Record<string, string> = {
    strong: TOKEN.emerald,
    partial: TOKEN.amber,
    weak: TOKEN.rose,
  }
  const color = strengthColors[item.support_strength] ?? TOKEN.muted

  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        padding: "8px 10px",
        background: TOKEN.bg,
        borderRadius: 8,
        border: `1px solid ${TOKEN.line}`,
        alignItems: "flex-start",
      }}
    >
      <div style={{ flexShrink: 0, marginTop: 1 }}>
        <EvidenceTypeIcon type={item.evidence_type} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontWeight: 600, fontSize: 12, color: TOKEN.ink }}>{item.source_label}</span>
          <Badge
            tone={item.support_strength === "strong" ? "emerald" : item.support_strength === "partial" ? "amber" : "rose"}
          >
            {item.support_strength}
          </Badge>
          {item.protected && <Badge tone="purple">Protected</Badge>}
          {!item.public_safe && !item.protected && <Badge tone="slate">Private</Badge>}
        </div>
        <p style={{ fontSize: 12, color: TOKEN.muted, margin: "4px 0 0", lineHeight: 1.5 }}>{item.summary}</p>
        {item.limitations.length > 0 && (
          <div style={{ marginTop: 4, display: "flex", gap: 4, flexWrap: "wrap" }}>
            {item.limitations.map((l: string, i: number) => (
              <Badge key={i} tone="slate" style={{ fontSize: 10 }}>
                ⚠ {l}
              </Badge>
            ))}
          </div>
        )}
        {item.evidence_url && (
          <a
            href={item.evidence_url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontSize: 11, color: TOKEN.indigo, marginTop: 4, display: "inline-block" }}
          >
            View evidence →
          </a>
        )}
      </div>
      <div style={{ flexShrink: 0, textAlign: "right" }}>
        <div style={{ fontSize: 14, fontWeight: 700, color }}>{item.confidence_score}%</div>
        <Mono style={{ fontSize: 9, color: TOKEN.muted }}>conf.</Mono>
      </div>
    </div>
  )
}

function SkillCard({ skill }: { skill: SkillEvidenceRecord }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <Card style={{ padding: "14px 16px" }}>
      <div
        style={{ cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}
        onClick={() => setExpanded((e) => !e)}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontWeight: 700, fontSize: 14, color: TOKEN.ink }}>{skill.skill_name}</span>
            <SupportLevelBadge level={skill.support_level} />
            {skill.evidence_count > 0 && (
              <Badge tone="slate">{skill.evidence_count} source{skill.evidence_count !== 1 ? "s" : ""}</Badge>
            )}
          </div>
          <div style={{ marginTop: 8, maxWidth: 360 }}>
            <StrengthBar score={skill.confidence_score} />
          </div>
        </div>
        <div style={{ flexShrink: 0, color: TOKEN.muted, fontSize: 14 }}>
          {expanded ? "▲" : "▼"}
        </div>
      </div>

      {expanded && (
        <div style={{ marginTop: 14 }}>
          {/* Evidence sources tags */}
          {skill.evidence_sources.length > 0 && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
              {skill.evidence_sources.map((src: string) => (
                <Badge key={src} tone="sky">{src}</Badge>
              ))}
            </div>
          )}

          {/* Evidence items */}
          {skill.evidence_items.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 12 }}>
              {skill.evidence_items.map((item: SkillEvidenceItem, i: number) => (
                <EvidenceItemRow key={i} item={item} />
              ))}
            </div>
          )}

          {/* Gaps */}
          {skill.gaps.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <Mono style={{ fontSize: 10, color: TOKEN.rose, textTransform: "uppercase", letterSpacing: "0.12em", fontWeight: 700 }}>
                Evidence Gaps
              </Mono>
              <ul style={{ margin: "6px 0 0", padding: "0 0 0 14px", display: "flex", flexDirection: "column", gap: 3 }}>
                {skill.gaps.map((gap: string, i: number) => (
                  <li key={i} style={{ fontSize: 12, color: TOKEN.muted }}>{gap}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Next steps */}
          {skill.recommended_next_steps.length > 0 && (
            <div>
              <Mono style={{ fontSize: 10, color: TOKEN.indigo, textTransform: "uppercase", letterSpacing: "0.12em", fontWeight: 700 }}>
                Recommended Next Steps
              </Mono>
              <ol style={{ margin: "6px 0 0", padding: "0 0 0 16px", display: "flex", flexDirection: "column", gap: 3 }}>
                {skill.recommended_next_steps.map((step: string, i: number) => (
                  <li key={i} style={{ fontSize: 12, color: TOKEN.inkSoft }}>{step}</li>
                ))}
              </ol>
            </div>
          )}
        </div>
      )}
    </Card>
  )
}

export function SkillEvidenceTimelinePanel({
  sessionId,
  publicSlug,
}: {
  sessionId?: string
  publicSlug?: string
}) {
  const [data, setData] = useState<SkillEvidenceTimelineResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<string>("all")

  const load = () => {
    setLoading(true)
    setError(null)
    const fetch = sessionId
      ? getSkillEvidenceTimeline(sessionId)
      : publicSlug
      ? getPublicSkillEvidenceTimeline(publicSlug)
      : Promise.reject(new Error("No session or slug provided"))
    fetch
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [sessionId, publicSlug])

  if (loading) return <LoadingState label="Loading skill evidence timeline…" />
  if (error) return <ErrorState message={error} onRetry={load} />
  if (!data || data.skills.length === 0) {
    return (
      <EmptyState
        icon="🧠"
        title="No skill evidence yet"
        description="Submit proof evidence to build your skill timeline. GitHub repositories, workflows, and live demos all contribute."
      />
    )
  }

  const filters = [
    { label: "All", value: "all" },
    { label: "Strong", value: "strong" },
    { label: "Partial", value: "partial" },
    { label: "Missing", value: "missing" },
  ]

  const filtered = filter === "all" ? data.skills : data.skills.filter((s: SkillEvidenceRecord) => s.support_level === filter)

  const counts = {
    strong: data.skills.filter((s: SkillEvidenceRecord) => s.support_level === "strong").length,
    partial: data.skills.filter((s: SkillEvidenceRecord) => s.support_level === "partial").length,
    weak: data.skills.filter((s: SkillEvidenceRecord) => s.support_level === "weak").length,
    missing: data.skills.filter((s: SkillEvidenceRecord) => s.support_level === "missing").length,
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Summary row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
        {[
          { label: "Strong", count: counts.strong, color: TOKEN.emerald },
          { label: "Partial", count: counts.partial, color: TOKEN.amber },
          { label: "Weak", count: counts.weak, color: TOKEN.rose },
          { label: "Missing", count: counts.missing, color: TOKEN.muted },
        ].map(({ label, count, color }) => (
          <Card key={label} style={{ padding: "10px 14px", textAlign: "center" }}>
            <div style={{ fontSize: 22, fontWeight: 700, color }}>{count}</div>
            <div style={{ fontSize: 11, color: TOKEN.muted, marginTop: 2 }}>{label}</div>
          </Card>
        ))}
      </div>

      {/* Filter tabs */}
      <div style={{ display: "flex", gap: 6 }}>
        {filters.map((f) => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            type="button"
            style={{
              padding: "5px 12px",
              borderRadius: 999,
              fontSize: 12,
              fontWeight: 600,
              border: `1px solid ${filter === f.value ? TOKEN.indigo : TOKEN.line}`,
              background: filter === f.value ? TOKEN.indigoSoft : TOKEN.paper,
              color: filter === f.value ? TOKEN.indigo : TOKEN.muted,
              cursor: "pointer",
            }}
          >
            {f.label}
          </button>
        ))}
        <div style={{ marginLeft: "auto" }}>
          <Btn variant="secondary" size="sm" onClick={load}>Refresh</Btn>
        </div>
      </div>

      {/* Skill cards */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {filtered.length === 0 ? (
          <p style={{ fontSize: 13, color: TOKEN.muted, textAlign: "center", padding: "24px 0" }}>
            No skills in this category.
          </p>
        ) : (
          filtered.map((skill: SkillEvidenceRecord) => <SkillCard key={skill.normalized_skill_name} skill={skill} />)
        )}
      </div>

      <Mono style={{ fontSize: 10, color: TOKEN.muted, textAlign: "right" }}>
        Generated: {new Date(data.generated_at).toLocaleString()}
      </Mono>
    </div>
  )
}
