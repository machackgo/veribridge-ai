"use client"

import { useEffect, useState } from "react"
import {
  listNotifications,
  getUnreadNotificationCount,
  markNotificationRead,
  archiveNotification,
  dismissNotification,
  markAllNotificationsRead,
  type NotificationResponse,
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

function categoryIcon(category: string) {
  const icons: Record<string, string> = {
    access_request: "🔑",
    access_decision: "✅",
    verification: "🔍",
    ai_domain_review: "🤖",
    project_defense: "🎯",
    privacy: "🔒",
    passport: "🪪",
    system: "⚙️",
    general: "📢",
  }
  return icons[category] ?? "📬"
}

function priorityBadge(priority: string) {
  const map: Record<string, "rose" | "amber" | "indigo" | "slate"> = {
    urgent: "rose",
    high: "amber",
    normal: "indigo",
    low: "slate",
  }
  return map[priority] ?? "slate"
}

function NotifCard({
  notif,
  onRead,
  onArchive,
  onDismiss,
}: {
  notif: NotificationResponse
  onRead: (id: string) => void
  onArchive: (id: string) => void
  onDismiss: (id: string) => void
}) {
  const isUnread = !notif.read_at && notif.status !== "read"
  const isArchived = !!notif.archived_at
  const isDismissed = !!notif.dismissed_at

  return (
    <div
      style={{
        display: "flex",
        gap: 12,
        padding: "12px 14px",
        background: isUnread ? `${TOKEN.indigo}06` : TOKEN.paper,
        border: `1px solid ${isUnread ? TOKEN.indigo + "25" : TOKEN.line}`,
        borderRadius: 10,
        alignItems: "flex-start",
        opacity: isDismissed || isArchived ? 0.6 : 1,
      }}
    >
      <div style={{ flexShrink: 0, fontSize: 18, marginTop: 1 }}>
        {categoryIcon(notif.category)}
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 2 }}>
          {notif.title && (
            <span style={{ fontWeight: 600, fontSize: 13, color: TOKEN.ink }}>{notif.title}</span>
          )}
          <Badge tone={priorityBadge(notif.priority)}>{notif.priority}</Badge>
          <Badge tone="slate">{notif.category.replace(/_/g, " ")}</Badge>
          {isUnread && (
            <span
              style={{
                display: "inline-block",
                width: 7,
                height: 7,
                borderRadius: "50%",
                background: TOKEN.indigo,
              }}
            />
          )}
        </div>

        {notif.message && (
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: "2px 0 6px", lineHeight: 1.5 }}>
            {notif.message}
          </p>
        )}

        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <Mono style={{ fontSize: 10, color: TOKEN.muted }}>
            {new Date(notif.created_at).toLocaleString()}
          </Mono>

          {notif.action_url && notif.action_label && (
            <a
              href={notif.action_url}
              style={{ fontSize: 11, color: TOKEN.indigo, fontWeight: 600, textDecoration: "none" }}
            >
              {notif.action_label} →
            </a>
          )}
        </div>
      </div>

      <div style={{ flexShrink: 0, display: "flex", gap: 4 }}>
        {isUnread && (
          <button
            onClick={() => onRead(notif.id)}
            title="Mark read"
            type="button"
            style={{
              background: "none",
              border: "none",
              color: TOKEN.indigo,
              cursor: "pointer",
              fontSize: 14,
              padding: "2px 4px",
            }}
          >
            ✓
          </button>
        )}
        {!isArchived && (
          <button
            onClick={() => onArchive(notif.id)}
            title="Archive"
            type="button"
            style={{
              background: "none",
              border: "none",
              color: TOKEN.muted,
              cursor: "pointer",
              fontSize: 12,
              padding: "2px 4px",
            }}
          >
            📁
          </button>
        )}
        {!isDismissed && (
          <button
            onClick={() => onDismiss(notif.id)}
            title="Dismiss"
            type="button"
            style={{
              background: "none",
              border: "none",
              color: TOKEN.muted,
              cursor: "pointer",
              fontSize: 12,
              padding: "2px 4px",
            }}
          >
            ✕
          </button>
        )}
      </div>
    </div>
  )
}

export function NotificationBell({ onClick, count }: { onClick: () => void; count: number }) {
  return (
    <button
      onClick={onClick}
      type="button"
      style={{
        position: "relative",
        background: "none",
        border: "none",
        cursor: "pointer",
        padding: "6px 8px",
        borderRadius: 8,
        fontSize: 18,
      }}
      title={`${count} unread notifications`}
    >
      🔔
      {count > 0 && (
        <span
          style={{
            position: "absolute",
            top: 2,
            right: 2,
            width: 16,
            height: 16,
            borderRadius: "50%",
            background: TOKEN.rose,
            color: "#fff",
            fontSize: 9,
            fontWeight: 700,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {count > 99 ? "99+" : count}
        </span>
      )}
    </button>
  )
}

export function NotificationCenterPanel() {
  const [notifications, setNotifications] = useState<NotificationResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<"all" | "unread">("all")
  const [markingAll, setMarkingAll] = useState(false)

  const load = () => {
    setLoading(true)
    setError(null)
    listNotifications({ unread_only: filter === "unread", limit: 50 })
      .then(setNotifications)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [filter])

  const handleRead = async (id: string) => {
    try {
      const updated = await markNotificationRead(id)
      setNotifications((prev) => prev.map((n) => (n.id === id ? updated : n)))
    } catch {}
  }

  const handleArchive = async (id: string) => {
    try {
      const updated = await archiveNotification(id)
      setNotifications((prev) => prev.map((n) => (n.id === id ? updated : n)))
    } catch {}
  }

  const handleDismiss = async (id: string) => {
    try {
      const updated = await dismissNotification(id)
      setNotifications((prev) => prev.map((n) => (n.id === id ? updated : n)))
    } catch {}
  }

  const handleMarkAllRead = async () => {
    setMarkingAll(true)
    try {
      const updated = await markAllNotificationsRead()
      const updatedIds = new Set(updated.map((n: NotificationResponse) => n.id))
      setNotifications((prev) =>
        prev.map((n: NotificationResponse) => (updatedIds.has(n.id) ? updated.find((u: NotificationResponse) => u.id === n.id)! : n))
      )
    } catch {}
    setMarkingAll(false)
  }

  const unreadCount = notifications.filter((n) => !n.read_at && n.status !== "read").length

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>
            Notifications
            {unreadCount > 0 && (
              <span
                style={{
                  marginLeft: 8,
                  fontSize: 12,
                  background: TOKEN.rose,
                  color: "#fff",
                  borderRadius: 999,
                  padding: "1px 8px",
                  fontWeight: 700,
                }}
              >
                {unreadCount} unread
              </span>
            )}
          </h2>
          <p style={{ fontSize: 13, color: TOKEN.muted, margin: "4px 0 0" }}>
            Access requests, review updates, and passport activity.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {unreadCount > 0 && (
            <Btn variant="secondary" size="sm" onClick={handleMarkAllRead} disabled={markingAll}>
              {markingAll ? "Marking…" : "Mark all read"}
            </Btn>
          )}
          <Btn variant="secondary" size="sm" onClick={load}>Refresh</Btn>
        </div>
      </div>

      {/* Filter tabs */}
      <div style={{ display: "flex", gap: 6 }}>
        {(["all", "unread"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            type="button"
            style={{
              padding: "5px 14px",
              borderRadius: 999,
              fontSize: 12,
              fontWeight: 600,
              border: `1px solid ${filter === f ? TOKEN.indigo : TOKEN.line}`,
              background: filter === f ? TOKEN.indigoSoft : TOKEN.paper,
              color: filter === f ? TOKEN.indigo : TOKEN.muted,
              cursor: "pointer",
            }}
          >
            {f === "all" ? "All" : "Unread"}
          </button>
        ))}
      </div>

      {/* Body */}
      {loading && <LoadingState label="Loading notifications…" />}
      {error && <ErrorState message={error} onRetry={load} />}
      {!loading && !error && notifications.length === 0 && (
        <EmptyState
          icon="🔔"
          title="All caught up"
          description={
            filter === "unread"
              ? "No unread notifications."
              : "No notifications yet. Activity will appear here when recruiters view or request access to your passport."
          }
        />
      )}

      {!loading && !error && notifications.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {notifications.map((n) => (
            <NotifCard
              key={n.id}
              notif={n}
              onRead={handleRead}
              onArchive={handleArchive}
              onDismiss={handleDismiss}
            />
          ))}
        </div>
      )}
    </div>
  )
}
