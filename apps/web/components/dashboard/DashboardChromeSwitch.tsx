"use client"

/**
 * Chrome switch for /dashboard/** (dashboard consolidation Stage 1).
 *
 * Skills & Gaps is a real, evidence-derived student surface that belongs to the
 * new Student Shell navigation, but its route (/dashboard/skill-gaps) lives in
 * the legacy dashboard segment. Wrapping it here — by pathname only — gives it
 * the shared authenticated shell without moving the route, touching the page,
 * or changing any Skill Gaps logic/APIs. Every other /dashboard route keeps the
 * legacy DashboardShell chrome until Stage 2.
 */

import { usePathname } from "next/navigation"
import type { ReactNode } from "react"
import { DashboardShell, type NavItem } from "./DashboardShell"
import { StudentShell } from "../student/StudentShell"
import type { StudentPersona } from "../student/persona"

export function DashboardChromeSwitch({
  nav,
  accountNav,
  persona,
  studentPersona,
  children,
}: {
  nav: NavItem[]
  accountNav: NavItem[]
  persona: { name: string; detail: string; initials: string }
  studentPersona: StudentPersona
  children: ReactNode
}) {
  const pathname = usePathname()
  const isSkillGaps =
    pathname === "/dashboard/skill-gaps" || pathname.startsWith("/dashboard/skill-gaps/")

  if (isSkillGaps) {
    return (
      <StudentShell persona={studentPersona}>
        {/* Match the standard student-page container (see /student/vbr pages);
            the page itself has no outer container — the legacy shell provided it. */}
        <div style={{ maxWidth: 900, margin: "0 auto", padding: "48px 24px" }}>{children}</div>
      </StudentShell>
    )
  }

  return (
    <DashboardShell nav={nav} accountNav={accountNav} persona={persona} accent="emerald">
      {children}
    </DashboardShell>
  )
}
