import type { ReactNode } from "react"
import { DashboardShell } from "../../../components/dashboard/DashboardShell"

// Admin portal — only navigable by users with the admin role.
// In production, RBAC middleware (GET /api/v1/me/permissions) gates this route.
// For the MVP demo, this layout is accessible directly at /admin.

const nav = [
  { label: "Overview", href: "/admin", icon: "▣" },
  { label: "Quality Review", href: "/admin/quality-review", icon: "🔍" },
  { label: "Requester Verification", href: "/admin/requesters", icon: "🧑‍💼" },
]

const accountNav = [
  { label: "Back to Dashboard", href: "/dashboard", icon: "←" },
]

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <DashboardShell
      nav={nav}
      accountNav={accountNav}
      persona={{
        name: "Admin Portal",
        detail: "veribridge-admin",
        initials: "Ad",
      }}
      accent="indigo"
    >
      {children}
    </DashboardShell>
  )
}
