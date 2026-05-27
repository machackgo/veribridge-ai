"use client"

import { useEffect, useState } from "react"
import {
  getWorkPassportAnalytics,
  type WorkPassportAnalyticsResponse,
  type WorkPassportActivityItem,
  type RequestedSectionSummary,
  type RequesterOrganizationSummary,
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
      <div style={{ fontSize: 26, fontWeight: 800, color: color ?? TOKEN.ink, lineHeight: 1 }}>
        {value}
      </div>
      <Mono
        style={{
          fontSize: 10,
          color: TOKEN.muted,
          textTransform: "uppercase",
          letterSpacing: "0.1em",
          marginTop: 4,
        }}
      >
        {label}
      </Mono>
      {subtitle && (
        <p style={{ fontSize: 11, color: TOKEN.muted, margin: "4px 0 0" }}>{subtitle}</p>
      )}
    </Card>
  )
}

function ActivityRow({ activity }: { activity: WorkPassportActivityItem }) {
  const icons: Record<string, string> = {
    passport_viewed: "👁",
    access_requested: "🔑",
    access_approved: "✅",
    access_denied: "❌",
    access_revoked: "🚫",
    passport_saved: "📌",
    evidence_viewed: "🔍",
    protected_evidence_viewed: "🔏",
    access_granted: "🟢",
    access_revoke: "🚫",
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
          {activity.event_summary ?? activity.event_type.replace(/_/g, " ")}
        </p>
        {(activity.actor_email || activity.requester_organization) && (
          <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>
            {activity.actor_email}
            {activity.requester_organization ? ` · ${activity.requester_organization}` : ""}
          </p>
        )}
        {activity.actor_type && (
          <Mono style={{ fontSize: 9, color: TOKEN.muted }}>{activity.actor_type}</Mono>
        )}
      </div>
      <Mono style={{ fontSize: 10, color: TOKEN.muted, flexShrink: 0, whiteSpace: "nowrap" }}>
        {new Date(activity.created_at).toLocaleDateString()}
      </Mono>
    </div>
  )
}

export function WorkPassportAnalyticsPanel() {
  const [analytics, setAnalytics] = useState<WorkPassportAnalyticsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    getWorkPassportAnalytics()
      .then(setAnalytics)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  if (loading) return <LoadingState label="Loading analytics…" />
  if (error) return <ErrorState message={error} onRetry={load} />
  if (!analytics) {
    return (
      <EmptyState
        icon="📊"
        title="No analytics yet"
        description="Analytics appear once your public passport is active and receiving views."
      />
    )
  }

  // Safe defaults — backend guarantees these but guard anyway
  const topSections: RequestedSectionSummary[] = analytics.top_requested_sections ?? []
  const requesterOrgs: RequesterOrganizationSummary[] = analytics.requester_organizations ?? []
  const recentActivity: WorkPassportActivityItem[] = analytics.recent_activity ?? []

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>
            Work Passport Analytics
          </h2>
          <p style={{ fontSize: 13, color: TOKEN.muted, margin: "4px 0 0" }}>
            Visibility and engagement metrics for your public Work Passport.
          </p>
        </div>
        <Btn variant="secondary" size="sm" onClick={load}>
          Refresh
        </Btn>
      </div>

      {/* Primary metrics */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
        <MetricCard
          label="Public Views"
          value={analytics.total_public_views}
          icon="👁"
          color={TOKEN.indigo}
        />
        <MetricCard
          label="Unique Requesters"
          value={analytics.unique_requester_emails}
          icon="👥"
          color={TOKEN.purple}
        />
        <MetricCard
          label="Access Requests"
          value={analytics.total_access_requests}
          icon="🔑"
          color={TOKEN.amber}
        />
        <MetricCard
          label="Active Grants"
          value={analytics.active_access_grants}
          icon="✅"
          color={TOKEN.emerald}
        />
      </div>

      {/* Secondary metrics */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
        <MetricCard
          label="Approved"
          value={analytics.approved_access_requests}
          icon="✔"
          color={TOKEN.emerald}
        />
        <MetricCard
          label="Denied"
          value={analytics.denied_access_requests}
          icon="✗"
          color={TOKEN.rose}
        />
        <MetricCard
          label="Pending"
          value={analytics.pending_access_requests}
          icon="⏳"
          color={TOKEN.amber}
        />
        <MetricCard
          label="Protected Views"
          value={analytics.protected_evidence_views}
          icon="🔏"
          color={TOKEN.purple}
        />
      </div>

      {/* Sections & orgs row */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Card>
          <CardHeader title="Top Requested Sections" eyebrow="Evidence" icon="📋" />
          {topSections.length === 0 ? (
            <p style={{ fontSize: 12, color: TOKEN.muted, marginTop: 8 }}>
              No section requests yet.
            </p>
          ) : (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
              {topSections.map((s: RequestedSectionSummary) => (
                <Badge key={s.section} tone="sky">
                  {s.section.replace(/_/g, " ")}
                  <Mono style={{ fontSize: 9, marginLeft: 5, opacity: 0.7 }}>×{s.count}</Mono>
                </Badge>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <CardHeader title="Requester Organizations" eyebrow="Companies" icon="🏢" />
          {requesterOrgs.length === 0 ? (
            <p style={{ fontSize: 12, color: TOKEN.muted, marginTop: 8 }}>
              No requester organizations yet.
            </p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
              {requesterOrgs.slice(0, 6).map((org: RequesterOrganizationSummary, i: number) => (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 8,
                  }}
                >
                  <span style={{ fontSize: 12, color: TOKEN.ink, fontWeight: 500 }}>
                    {org.organization_name ?? org.organization_domain ?? "Unknown"}
                  </span>
                  <Mono style={{ fontSize: 10, color: TOKEN.muted, flexShrink: 0 }}>
                    {org.request_count} req
                  </Mono>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* Stats row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
        <MetricCard
          label="Total Passports"
          value={analytics.total_passports}
          icon="🪪"
          color={TOKEN.indigo}
        />
        <MetricCard
          label="Unique Orgs"
          value={analytics.unique_requester_organizations}
          icon="🏢"
          color={TOKEN.sky}
        />
        <MetricCard
          label="Unread Alerts"
          value={analytics.unread_notifications}
          icon="🔔"
          color={analytics.unread_notifications > 0 ? TOKEN.amber : TOKEN.muted}
        />
      </div>

      {/* Activity feed */}
      <Card>
        <CardHeader title="Recent Activity" icon="📈" />
        {recentActivity.length === 0 ? (
          <p
            style={{
              fontSize: 13,
              color: TOKEN.muted,
              textAlign: "center",
              padding: "16px 0",
            }}
          >
            No recent activity.
          </p>
        ) : (
          <div>
            {recentActivity.slice(0, 20).map((a: WorkPassportActivityItem, i: number) => (
              <ActivityRow key={i} activity={a} />
            ))}
          </div>
        )}
      </Card>

      <Mono style={{ fontSize: 10, color: TOKEN.muted, textAlign: "right" }}>
        Generated: {new Date(analytics.generated_at).toLocaleDateString()}
      </Mono>
    </div>
  )
}
