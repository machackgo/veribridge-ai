"use client"

import type { ReactNode } from "react"

// ── Design tokens (match globals.css variables) ──────────────────────────

export const TOKEN = {
  indigo: "#4f46e5",
  indigoSoft: "#eef0ff",
  emerald: "#10b981",
  emeraldSoft: "#e6f7f1",
  amber: "#d97706",
  amberSoft: "#fef3c7",
  rose: "#f43f5e",
  roseSoft: "#fff1f2",
  purple: "#8b5cf6",
  purpleSoft: "#f1ecff",
  sky: "#0ea5e9",
  skySoft: "#e0f2fe",
  muted: "#6b7280",
  line: "#e6e8ef",
  paper: "#ffffff",
  bg: "#fafbfd",
  ink: "#0a0e1a",
  inkSoft: "#1f2a44",
} as const

// ── Shared micro-components ───────────────────────────────────────────────

export function Mono({
  children,
  style,
  "data-testid": testId,
}: {
  children: ReactNode
  style?: React.CSSProperties
  "data-testid"?: string
}) {
  return (
    <span data-testid={testId} style={{ fontFamily: "'JetBrains Mono', monospace", ...style }}>
      {children}
    </span>
  )
}

export function Card({
  children,
  style,
  className,
  id,
}: {
  children: ReactNode
  style?: React.CSSProperties
  className?: string
  id?: string
}) {
  return (
    <div
      id={id}
      className={className}
      style={{
        background: TOKEN.paper,
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 14,
        padding: 20,
        ...style,
      }}
    >
      {children}
    </div>
  )
}

export function CardHeader({
  title,
  eyebrow,
  action,
  icon,
}: {
  title: string
  eyebrow?: string
  action?: ReactNode
  icon?: string
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {icon && <span style={{ fontSize: 16 }}>{icon}</span>}
        <div>
          {eyebrow && (
            <Mono style={{ fontSize: 10, letterSpacing: "0.14em", color: TOKEN.muted, textTransform: "uppercase", display: "block", marginBottom: 2 }}>
              {eyebrow}
            </Mono>
          )}
          <span style={{ fontWeight: 600, fontSize: 14, letterSpacing: "-0.01em", color: TOKEN.ink }}>
            {title}
          </span>
        </div>
      </div>
      {action && <div style={{ flexShrink: 0 }}>{action}</div>}
    </div>
  )
}

export type BadgeTone = "slate" | "emerald" | "indigo" | "amber" | "rose" | "purple" | "sky"

const BADGE_STYLES: Record<BadgeTone, { bg: string; color: string; border: string }> = {
  slate: { bg: "#f8fafc", color: "#475569", border: "#e2e8f0" },
  emerald: { bg: TOKEN.emeraldSoft, color: "#065f46", border: "#a7f3d0" },
  indigo: { bg: TOKEN.indigoSoft, color: "#3730a3", border: "#c7d2fe" },
  amber: { bg: TOKEN.amberSoft, color: "#92400e", border: "#fde68a" },
  rose: { bg: TOKEN.roseSoft, color: "#9f1239", border: "#fecdd3" },
  purple: { bg: TOKEN.purpleSoft, color: "#6d28d9", border: "#ddd6fe" },
  sky: { bg: TOKEN.skySoft, color: "#0c4a6e", border: "#bae6fd" },
}

export function Badge({
  children,
  tone = "slate",
  style,
}: {
  children: ReactNode
  tone?: BadgeTone
  style?: React.CSSProperties
}) {
  const s = BADGE_STYLES[tone]
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "3px 9px",
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 600,
        background: s.bg,
        color: s.color,
        border: `1px solid ${s.border}`,
        whiteSpace: "nowrap",
        ...style,
      }}
    >
      {children}
    </span>
  )
}

export function Btn({
  children,
  onClick,
  variant = "primary",
  disabled,
  style,
  size = "md",
}: {
  children: ReactNode
  onClick?: () => void
  variant?: "primary" | "secondary" | "ghost" | "danger"
  disabled?: boolean
  style?: React.CSSProperties
  size?: "sm" | "md"
}) {
  const base: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    borderRadius: 8,
    fontWeight: 600,
    fontSize: size === "sm" ? 12 : 13,
    padding: size === "sm" ? "5px 12px" : "8px 16px",
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.5 : 1,
    transition: "background 150ms, border-color 150ms, opacity 150ms",
    border: "none",
    ...style,
  }
  const variants: Record<string, React.CSSProperties> = {
    primary: { background: TOKEN.ink, color: "#fff" },
    secondary: { background: TOKEN.paper, color: TOKEN.inkSoft, border: `1px solid ${TOKEN.line}` },
    ghost: { background: "transparent", color: TOKEN.muted },
    danger: { background: TOKEN.roseSoft, color: TOKEN.rose, border: `1px solid #fecdd3` },
  }
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{ ...base, ...variants[variant] }}
      type="button"
    >
      {children}
    </button>
  )
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div style={{ padding: "40px 0", textAlign: "center", color: TOKEN.muted }}>
      <div
        style={{
          width: 28,
          height: 28,
          borderRadius: "50%",
          border: `3px solid ${TOKEN.line}`,
          borderTopColor: TOKEN.indigo,
          animation: "spin 0.8s linear infinite",
          margin: "0 auto 12px",
        }}
      />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <p style={{ fontSize: 13 }}>{label}</p>
    </div>
  )
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon: string
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div style={{ padding: "48px 24px", textAlign: "center" }}>
      <div style={{ fontSize: 36, marginBottom: 12 }}>{icon}</div>
      <p style={{ fontWeight: 600, fontSize: 14, color: TOKEN.ink, marginBottom: 6 }}>{title}</p>
      <p style={{ fontSize: 13, color: TOKEN.muted, maxWidth: 340, margin: "0 auto 20px" }}>{description}</p>
      {action}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div style={{ padding: "32px 24px", textAlign: "center" }}>
      <div style={{ fontSize: 32, marginBottom: 10 }}>⚠️</div>
      <p style={{ fontWeight: 600, fontSize: 14, color: TOKEN.rose, marginBottom: 6 }}>Something went wrong</p>
      <p style={{ fontSize: 12, color: TOKEN.muted, maxWidth: 320, margin: "0 auto 16px" }}>{message}</p>
      {onRetry && <Btn variant="secondary" size="sm" onClick={onRetry}>Try again</Btn>}
    </div>
  )
}

export function SeverityDot({ severity }: { severity: string }) {
  const colors: Record<string, string> = {
    urgent: TOKEN.rose,
    high: TOKEN.amber,
    normal: TOKEN.indigo,
    low: "#94a3b8",
    info: "#94a3b8",
  }
  return (
    <span
      style={{
        display: "inline-block",
        width: 7,
        height: 7,
        borderRadius: "50%",
        background: colors[severity] ?? "#94a3b8",
        flexShrink: 0,
      }}
    />
  )
}

export function ProgressBar({
  value,
  max = 100,
  color = TOKEN.indigo,
  height = 6,
}: {
  value: number
  max?: number
  color?: string
  height?: number
}) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100))
  return (
    <div style={{ background: TOKEN.line, borderRadius: height, height, overflow: "hidden" }}>
      <div
        style={{
          width: `${pct}%`,
          height: "100%",
          background: color,
          borderRadius: height,
          transition: "width 500ms ease",
        }}
      />
    </div>
  )
}

export function SupportLevelBadge({ level }: { level: string }) {
  const map: Record<string, { tone: BadgeTone; label: string }> = {
    strong: { tone: "emerald", label: "Strong" },
    partial: { tone: "amber", label: "Partial" },
    weak: { tone: "rose", label: "Weak" },
    missing: { tone: "slate", label: "Missing" },
  }
  const { tone, label } = map[level] ?? { tone: "slate" as BadgeTone, label: level }
  return <Badge tone={tone}>{label}</Badge>
}

export function StatusBadge({ status }: { status: string }) {
  const label = status.replace(/_/g, " ")
  if (status.includes("active") || status === "approved" || status === "verified" || status === "trusted") {
    return <Badge tone="emerald">{label}</Badge>
  }
  if (status === "pending" || status.includes("review") || status.includes("progress")) {
    return <Badge tone="amber">{label}</Badge>
  }
  if (status === "denied" || status === "blocked" || status === "archived" || status === "revoked") {
    return <Badge tone="rose">{label}</Badge>
  }
  if (status === "draft" || status === "submitted") {
    return <Badge tone="indigo">{label}</Badge>
  }
  return <Badge tone="slate">{label}</Badge>
}

export function Divider({ style }: { style?: React.CSSProperties }) {
  return <div style={{ height: 1, background: TOKEN.line, margin: "16px 0", ...style }} />
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <Mono
      style={{
        fontSize: 10,
        letterSpacing: "0.16em",
        textTransform: "uppercase",
        color: TOKEN.muted,
        fontWeight: 600,
        display: "block",
        marginBottom: 10,
      }}
    >
      {children}
    </Mono>
  )
}

export function Grid2({ children }: { children: ReactNode }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
      {children}
    </div>
  )
}

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div style={{ marginBottom: 28, display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16 }}>
      <div>
        <Mono style={{ fontSize: 11, letterSpacing: "0.16em", color: TOKEN.muted, textTransform: "uppercase" }}>
          {eyebrow}
        </Mono>
        <h1 style={{ fontSize: 26, fontWeight: 600, letterSpacing: "-0.02em", margin: "4px 0 6px", color: TOKEN.ink }}>
          {title}
        </h1>
        <p style={{ fontSize: 13, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>{description}</p>
      </div>
      {action && <div style={{ flexShrink: 0 }}>{action}</div>}
    </div>
  )
}
