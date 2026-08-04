"use client"

import type { ReactNode } from "react"
import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { DashboardShell } from "../../../components/dashboard/DashboardShell"
import { fetchAPI } from "@/lib/api"

// Admin portal — gated on the backend role model (GET /api/v1/me/permissions →
// dashboard_access.admin_dashboard). Backend admin routes fail closed
// regardless; this gate keeps the admin SHELL from rendering for ordinary
// signed-in students. Fail closed: any error → treated as not-admin.

const nav = [
  { label: "Overview", href: "/admin", icon: "▣" },
  { label: "Quality Review", href: "/admin/quality-review", icon: "🔍" },
  { label: "Requester Verification", href: "/admin/requesters", icon: "🧑‍💼" },
]

const accountNav = [
  { label: "Back to Dashboard", href: "/dashboard", icon: "←" },
]

export default function AdminLayout({ children }: { children: ReactNode }) {
  const router = useRouter()
  const [allowed, setAllowed] = useState<boolean | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetchAPI("/api/v1/me/permissions")
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const body = (await res.json()) as {
          dashboard_access?: { admin_dashboard?: boolean }
        }
        if (!cancelled) setAllowed(body.dashboard_access?.admin_dashboard === true)
      } catch {
        if (!cancelled) setAllowed(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (allowed === false) router.replace("/student")
  }, [allowed, router])

  if (allowed !== true) {
    return (
      <div style={{ minHeight: "60vh", display: "grid", placeContent: "center", color: "#6b7280", fontSize: 14 }}>
        {allowed === null ? "Checking access…" : "Redirecting…"}
      </div>
    )
  }

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
