"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import {
  getWorkPassportStatus,
  type WorkPassportStatusResponse,
  type WorkPassportIssue,
} from "@/lib/passport-api"
import {
  Badge,
  Btn,
  Card,
  CardHeader,
  Divider,
  EmptyState,
  ErrorState,
  LoadingState,
  Mono,
  PageHeader,
  ProgressBar,
  SectionTitle,
  SeverityDot,
  TOKEN,
} from "./shared"

function readinessColor(score: number) {
  if (score >= 80) return TOKEN.emerald
  if (score >= 50) return TOKEN.amber
  return TOKEN.rose
}

function overallStatusColor(status: string) {
  if (status === "public_passport_active" || status === "approved_for_sharing") return TOKEN.emerald
  if (status === "ai_domain_reviewed" || status === "ai_reviewed") return TOKEN.indigo
  if (status === "blocked" || status === "archived") return TOKEN.rose
  return TOKEN.amber
}

export function WorkPassportStatusPanel({ sessionId }: { sessionId: string }) {
  const [data, setData] = useState<WorkPassportStatusResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    getWorkPassportStatus(sessionId)
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [sessionId])

  if (loading) return <LoadingState label="Loading Work Passport status…" />
  if (error) return <ErrorState message={error} onRetry={load} />
  if (!data) return <EmptyState icon="🪪" title="No status available" description="Start by submitting proof evidence." />

  const score = data.readiness_score ?? 0
  const scoreColor = readinessColor(score)
  const statusColor = overallStatusColor(data.overall_status)

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* ── Hero status card ── */}
      <Card
        style={{
          background: "linear-gradient(135deg, #0a0e1a 0%, #1f2a44 100%)",
          border: "none",
          padding: "28px 24px",
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div>
            <Mono style={{ fontSize: 10, letterSpacing: "0.18em", color: "#94a3b8", textTransform: "uppercase" }}>
              Work Passport
            </Mono>
            <h2 style={{ fontSize: 22, fontWeight: 700, color: "#fff", margin: "6px 0 4px", letterSpacing: "-0.02em" }}>
              {data.status_label}
            </h2>
            <p style={{ fontSize: 13, color: "#94a3b8", margin: 0, maxWidth: 480, lineHeight: 1.5 }}>
              {data.status_description}
            </p>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 42, fontWeight: 800, color: scoreColor, lineHeight: 1 }}>
              {score}
            </div>
            <Mono style={{ fontSize: 10, color: "#94a3b8", letterSpacing: "0.14em", textTransform: "uppercase" }}>
              Readiness
            </Mono>
            <div style={{ marginTop: 8 }}>
              <Badge
                tone="slate"
                style={{ background: `${statusColor}20`, color: statusColor, border: `1px solid ${statusColor}40` }}
              >
                {data.overall_status.replace(/_/g, " ")}
              </Badge>
            </div>
          </div>
        </div>

        {/* Readiness bar */}
        <div style={{ marginTop: 20 }}>
          <ProgressBar value={score} color={scoreColor} height={8} />
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
            <Mono style={{ fontSize: 10, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.1em" }}>
              {data.readiness_level ?? "—"}
            </Mono>
            {data.public_slug && (
              <Link
                href={`/p/${data.public_slug}`}
                style={{ fontSize: 12, color: "#818cf8", textDecoration: "none", fontWeight: 600 }}
                target="_blank"
              >
                View public passport →
              </Link>
            )}
          </div>
        </div>
      </Card>

      {/* ── Key metrics row ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
        {[
          { label: "Unread Alerts", value: data.unread_notification_count, icon: "🔔", tone: data.unread_notification_count > 0 ? TOKEN.amber : TOKEN.muted },
          { label: "Pending Requests", value: data.pending_access_request_count, icon: "⏳", tone: data.pending_access_request_count > 0 ? TOKEN.indigo : TOKEN.muted },
          { label: "Active Grants", value: data.active_access_grant_count, icon: "✅", tone: TOKEN.emerald },
          { label: "Open Admin Cases", value: data.open_admin_case_count, icon: "🔍", tone: data.open_admin_case_count > 0 ? TOKEN.rose : TOKEN.muted },
        ].map(({ label, value, icon, tone }) => (
          <Card key={label} style={{ padding: "14px 16px" }}>
            <div style={{ fontSize: 20, marginBottom: 6 }}>{icon}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: tone, lineHeight: 1 }}>{value}</div>
            <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em", marginTop: 4 }}>
              {label}
            </Mono>
          </Card>
        ))}
      </div>

      {/* ── Skill evidence summary ── */}
      {data.skill_evidence_summary && (
        <Card>
          <CardHeader title="Skill Evidence Summary" eyebrow="AI-analyzed" icon="🧠" />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
            {[
              { label: "Strong Skills", count: data.skill_evidence_summary.strong_skill_count, color: TOKEN.emerald },
              { label: "Partial Skills", count: data.skill_evidence_summary.partial_skill_count, color: TOKEN.amber },
              { label: "Missing Evidence", count: data.skill_evidence_summary.missing_skill_count, color: TOKEN.rose },
            ].map(({ label, count, color }) => (
              <div
                key={label}
                style={{
                  background: `${color}10`,
                  border: `1px solid ${color}30`,
                  borderRadius: 10,
                  padding: "12px 14px",
                  textAlign: "center",
                }}
              >
                <div style={{ fontSize: 26, fontWeight: 700, color }}>{count}</div>
                <div style={{ fontSize: 11, color: TOKEN.muted, marginTop: 4 }}>{label}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* ── Next action ── */}
      {data.recommended_next_action && (
        <Card style={{ borderLeft: `3px solid ${TOKEN.indigo}`, borderRadius: "0 14px 14px 0" }}>
          <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
            <span style={{ fontSize: 18 }}>👉</span>
            <div>
              <Mono style={{ fontSize: 10, color: TOKEN.indigo, textTransform: "uppercase", letterSpacing: "0.14em", fontWeight: 700 }}>
                Recommended next step
              </Mono>
              <p style={{ margin: "4px 0 0", fontSize: 13, color: TOKEN.ink, lineHeight: 1.5 }}>
                {data.recommended_next_action}
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* ── Blocking issues ── */}
      {data.blocking_issues.length > 0 && (
        <Card>
          <CardHeader title="Blocking Issues" icon="🚫" />
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {data.blocking_issues.map((issue: WorkPassportIssue) => (
              <div
                key={issue.code}
                style={{
                  display: "flex",
                  gap: 10,
                  padding: "10px 12px",
                  background: `${TOKEN.rose}08`,
                  border: `1px solid ${TOKEN.rose}25`,
                  borderRadius: 8,
                  alignItems: "flex-start",
                }}
              >
                <SeverityDot severity={issue.severity} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 13, color: TOKEN.ink }}>{issue.label}</div>
                  <div style={{ fontSize: 12, color: TOKEN.muted, marginTop: 2 }}>{issue.description}</div>
                  {issue.recommended_fix && (
                    <div style={{ fontSize: 11, color: TOKEN.indigo, marginTop: 4, fontWeight: 500 }}>
                      Fix: {issue.recommended_fix}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* ── Warnings ── */}
      {data.warnings.length > 0 && (
        <Card>
          <CardHeader title="Warnings" icon="⚠️" />
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {data.warnings.map((w: WorkPassportIssue) => (
              <div
                key={w.code}
                style={{
                  display: "flex",
                  gap: 8,
                  padding: "8px 10px",
                  background: `${TOKEN.amber}08`,
                  border: `1px solid ${TOKEN.amber}25`,
                  borderRadius: 6,
                  alignItems: "flex-start",
                }}
              >
                <SeverityDot severity={w.severity} />
                <div>
                  <span style={{ fontWeight: 600, fontSize: 12, color: TOKEN.ink }}>{w.label}: </span>
                  <span style={{ fontSize: 12, color: TOKEN.muted }}>{w.description}</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* ── Progress steps ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Card>
          <CardHeader title="Completed Steps" icon="✅" />
          {data.completed_steps.length === 0 ? (
            <p style={{ fontSize: 12, color: TOKEN.muted }}>No steps completed yet.</p>
          ) : (
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
              {data.completed_steps.map((step: string) => (
                <li key={step} style={{ display: "flex", gap: 8, fontSize: 12, alignItems: "center" }}>
                  <span style={{ color: TOKEN.emerald, flexShrink: 0 }}>✓</span>
                  <span style={{ color: TOKEN.inkSoft }}>{step}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <CardHeader title="Missing Steps" icon="📋" />
          {data.missing_steps.length === 0 ? (
            <p style={{ fontSize: 12, color: TOKEN.emerald, fontWeight: 600 }}>All steps complete 🎉</p>
          ) : (
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
              {data.missing_steps.map((step: string) => (
                <li key={step} style={{ display: "flex", gap: 8, fontSize: 12, alignItems: "center" }}>
                  <span style={{ color: TOKEN.muted, flexShrink: 0 }}>○</span>
                  <span style={{ color: TOKEN.muted }}>{step}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {/* ── Student next steps ── */}
      {data.student_next_steps.length > 0 && (
        <Card>
          <CardHeader title="Your Next Steps" icon="🗺️" />
          <ol style={{ margin: 0, padding: "0 0 0 18px", display: "flex", flexDirection: "column", gap: 8 }}>
            {data.student_next_steps.map((step: string, i: number) => (
              <li key={i} style={{ fontSize: 13, color: TOKEN.inkSoft, lineHeight: 1.5 }}>
                {step}
              </li>
            ))}
          </ol>
        </Card>
      )}

      {/* ── Recruiter-safe summary ── */}
      <Card style={{ background: TOKEN.indigoSoft, border: `1px solid #c7d2fe` }}>
        <CardHeader title="Public-facing Summary" eyebrow="What recruiters see" icon="👀" />
        <p style={{ fontSize: 13, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.6 }}>
          {data.recruiter_safe_summary}
        </p>
      </Card>

      <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 8 }}>
        <Mono style={{ fontSize: 10, color: TOKEN.muted }}>
          Generated: {new Date(data.generated_at).toLocaleString()}
        </Mono>
        <Btn variant="secondary" size="sm" onClick={load}>Refresh</Btn>
      </div>
    </div>
  )
}
