"use client"

import { useEffect, useState } from "react"
import {
  getWorkPassportAnalytics,
  getWorkPassportAnalyticsActivity,
  type WorkPassportAnalyticsResponse,
  type WorkPassportActivity,
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
  TOKEN,
} from "./shared"

function MetricCard({
  label,
  value,
  icon,
  color,
  subtitle,
}: {
  label: string
  value: number | string
  icon: string
  color?: string
  subtitle?: string
}) {
  return (
    <Card style={{ padding: "14px 16px" }}>
      <div style={{ fontSize: 20, marginBottom: 6 }}>{icon}</div>
      <div style={{ fontSize: 26, fontWeight: 800, color: color ?? TOKEN.ink, lineHeight: 1 }}>{value}</div>
      <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em", marginTop: 4 }}>
        {label}
      </Mono>
      {subtitle && <p style={{ fontSize: 11, color: TOKEN.muted, margin: "4px 0 0" }}>{subtitle}</p>}
    </Card>
  )
}

function ActivityRow({ activity }: { activity: WorkPassportActivity }) {
  const icons: Record<string, string> = {
    passport_viewed: "👁",
    access_requested: "🔑",
    access_approved: "✅",
    access_denied: "❌",
    access_revoked: "🚫",
    passport_saved: "📌",
    evidence_viewed: "🔍",
  }

  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        padding: "8px 0",
        borderBottom: `1px solid ${TOKEN.line}`,
        alignItems: "flex-start",
      }}
    >
      <span style={{ fontSize: 16, flexShrink: 0 }}>
        {icons[activity.event_type] ?? "📊"}
      </span>
      <div style={{ flex: 1 }}>
        <p style={{ fontSize: 13, color: TOKEN.ink, margin: "0 0 2px", fontWeight: 500 }}>
          {activity.description}
        </p>
        {(activity.requester_email || activity.requester_organization) && (
          <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>
            {activity.requester_email}
            {activity.requester_organization ? ` · ${activity.requester_organization}` : ""}
          </p>
        )}
      </div>
      <Mono style={{ fontSize: 10, color: TOKEN.muted, flexShrink: 0, whiteSpace: "nowrap" }}>
        {new Date(activity.occurred_at).toLocaleDateString()}
      </Mono>
    </div>
  )
}

export function WorkPassportAnalyticsPanel() {
  const [analytics, setAnalytics] = useState<WorkPassportAnalyticsResponse | null>(null)
  const [activity, setActivity] = useState<WorkPassportActivity[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    Promise.all([getWorkPassportAnalytics(), getWorkPassportAnalyticsActivity()])
      .then(([a, act]) => {
        setAnalytics(a)
        setActivity(act.activities ?? [])
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  if (loading) return <LoadingState label="Loading analytics…" />
  if (error) return <ErrorState message={error} onRetry={load} />
  if (!analytics) return <EmptyState icon="📊" title="No analytics yet" description="Analytics appear once your public passport is active and receiving views." />

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Work Passport Analytics</h2>
          <p style={{ fontSize: 13, color: TOKEN.muted, margin: "4px 0 0" }}>
            Visibility and engagement metrics for your public Work Passport.
          </p>
        </div>
        <Btn variant="secondary" size="sm" onClick={load}>Refresh</Btn>
      </div>

      {/* Primary metrics */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
        <MetricCard label="Total Views" value={analytics.total_views} icon="👁" color={TOKEN.indigo} />
        <MetricCard label="Unique Viewers" value={analytics.unique_viewer_count} icon="👥" color={TOKEN.purple} />
        <MetricCard label="Access Requests" value={analytics.total_access_requests} icon="🔑" color={TOKEN.amber} />
        <MetricCard label="Active Grants" value={analytics.active_grant_count} icon="✅" color={TOKEN.emerald} />
      </div>

      {/* Secondary metrics */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
        <MetricCard label="Approved Requests" value={analytics.approved_request_count} icon="✔" color={TOKEN.emerald} />
        <MetricCard label="Denied Requests" value={analytics.denied_request_count} icon="✗" color={TOKEN.rose} />
        <MetricCard label="Saved by Recruiters" value={analytics.total_saves} icon="📌" color={TOKEN.sky} />
        <MetricCard label="Protected Views" value={analytics.protected_evidence_views} icon="🔏" color={TOKEN.purple} />
      </div>

      {/* Top sections & orgs */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        {analytics.top_requested_sections.length > 0 && (
          <Card>
            <CardHeader title="Top Requested Sections" eyebrow="Evidence" icon="📋" />
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {analytics.top_requested_sections.map((s: string) => (
                <Badge key={s} tone="sky">{s.replace(/_/g, " ")}</Badge>
              ))}
            </div>
          </Card>
        )}
        {analytics.top_requester_organizations.length > 0 && (
          <Card>
            <CardHeader title="Top Requester Orgs" eyebrow="Companies" icon="🏢" />
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {analytics.top_requester_organizations.map((org: string) => (
                <Badge key={org} tone="indigo">{org}</Badge>
              ))}
            </div>
          </Card>
        )}
      </div>

      {/* Activity feed */}
      <Card>
        <CardHeader title="Recent Activity" icon="📈" />
        {activity.length === 0 ? (
          <p style={{ fontSize: 13, color: TOKEN.muted, textAlign: "center", padding: "16px 0" }}>
            No recent activity.
          </p>
        ) : (
          <div>
            {activity.slice(0, 20).map((a, i) => (
              <ActivityRow key={i} activity={a} />
            ))}
          </div>
        )}
      </Card>

      {analytics.first_view_at && (
        <Mono style={{ fontSize: 10, color: TOKEN.muted, textAlign: "right" }}>
          First view: {new Date(analytics.first_view_at).toLocaleDateString()}
          {analytics.last_view_at ? ` · Last view: ${new Date(analytics.last_view_at).toLocaleDateString()}` : ""}
        </Mono>
      )}
    </div>
  )
}
