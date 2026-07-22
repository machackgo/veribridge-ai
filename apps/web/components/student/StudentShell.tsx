"use client"

/**
 * StudentShell — the shared authenticated student chrome (Stage 1 of the
 * dashboard consolidation). Mounted by `src/app/student/layout.tsx` so every
 * /student/** route gets persistent navigation, active-project context,
 * profile/settings access, and the app's first sign-out control.
 *
 * Deliberate constraints:
 * - Pages keep their own internal headers/back-links; the shell never reaches
 *   into workflow logic.
 * - No new project store: the "active project" chip only reflects the existing
 *   `projectId`/`project` URL-param convention resolved against
 *   listVBRProjects(), and shows "All projects" otherwise.
 * - Recording surfaces render bare (see BARE_ROUTE_PATTERNS) — shell chrome on
 *   a screen-capture page risks being recorded into evidence artifacts.
 */

import { Suspense, useEffect, useState, type ReactNode } from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { createSupabaseBrowserClient } from "@/lib/supabase/client"
import { listVBRProjects, type VBRProjectResponse } from "@/lib/vbr-api"
import type { StudentPersona } from "./persona"

type ShellNavItem = { label: string; href: string }
type ShellNavSection = { title: string | null; items: ShellNavItem[] }

const NAV_SECTIONS: ShellNavSection[] = [
  { title: null, items: [{ label: "Dashboard", href: "/student" }] },
  {
    title: "Proofs",
    items: [
      { label: "GitHub Proof", href: "/student/proofs/github" },
      { label: "Website Proof", href: "/student/proofs/website" },
      { label: "Document Proof", href: "/student/proofs/documents" },
      { label: "Project Defense", href: "/student/proofs/project-defense" },
    ],
  },
  { title: "Skills", items: [{ label: "Skills & Gaps", href: "/dashboard/skill-gaps" }] },
  {
    title: "Passport",
    items: [
      { label: "Work Passport", href: "/student/vbr/passport" },
      { label: "Proof Vault", href: "/student/vbr/passport/vault" },
    ],
  },
]

const ACCOUNT_LINKS: ShellNavItem[] = [
  { label: "Account", href: "/dashboard/profile" },
  { label: "Settings", href: "/dashboard/settings" },
]

/**
 * Routes that must render without shell chrome: both are full-bleed
 * screen/mic recording surfaces whose captured video could otherwise include
 * the navigation, and both already carry their own back-links.
 */
const BARE_ROUTE_PATTERNS = [
  /^\/student\/vbr\/sessions\/[^/]+$/,
  /^\/student\/proofs\/project-defense\/record\/[^/]+$/,
]

export function isBareStudentRoute(pathname: string): boolean {
  return BARE_ROUTE_PATTERNS.some((pattern) => pattern.test(pathname))
}

/** Longest-prefix-wins active resolution so nested routes light up the most specific item. */
export function activeNavHref(pathname: string): string | null {
  let winner: string | null = null
  for (const section of NAV_SECTIONS) {
    for (const item of section.items) {
      const matches = pathname === item.href || pathname.startsWith(`${item.href}/`)
      if (matches && (winner === null || item.href.length > winner.length)) {
        winner = item.href
      }
    }
  }
  return winner
}

type Crumb = { label: string; href?: string }

export function studentBreadcrumbs(pathname: string): Crumb[] {
  const home: Crumb = { label: "Dashboard", href: "/student" }
  let tail: Crumb[] = []
  if (pathname === "/student") return [{ label: "Dashboard" }]
  else if (pathname.startsWith("/student/proofs/github")) tail = [{ label: "GitHub Proof" }]
  else if (pathname.startsWith("/student/proofs/website")) tail = [{ label: "Website Proof" }]
  else if (pathname.startsWith("/student/proofs/documents")) tail = [{ label: "Document Proof" }]
  else if (pathname.startsWith("/student/proofs/project-defense")) tail = [{ label: "Project Defense" }]
  else if (pathname.startsWith("/student/vbr/passport/vault"))
    tail = [{ label: "Work Passport", href: "/student/vbr/passport" }, { label: "Proof Vault" }]
  else if (pathname.startsWith("/student/vbr/passport/skills/"))
    tail = [{ label: "Work Passport", href: "/student/vbr/passport" }, { label: "Skill Report" }]
  else if (pathname.startsWith("/student/vbr/passport")) tail = [{ label: "Work Passport" }]
  else if (/^\/student\/vbr\/projects\/[^/]+\/report/.test(pathname)) tail = [{ label: "VBR Report" }]
  else if (pathname.startsWith("/dashboard/skill-gaps")) tail = [{ label: "Skills & Gaps" }]
  else return [home]
  return [home, ...tail]
}

/**
 * Reflects the existing cross-navigation selection convention (`projectId`,
 * plus the website-proof `project` prefill param) against the canonical
 * project list. Read-only by design: selection still happens where it does
 * today (Project Defense selector, proof attach panels).
 */
function ActiveProjectChip({ className = "hidden sm:inline-flex", testId = "student-shell-active-project" }: { className?: string; testId?: string }) {
  const searchParams = useSearchParams()
  const projectId = searchParams.get("projectId") ?? searchParams.get("project")
  const [projects, setProjects] = useState<VBRProjectResponse[] | null>(null)

  useEffect(() => {
    if (!projectId || projects !== null) return
    let cancelled = false
    listVBRProjects()
      .then((rows) => {
        if (!cancelled) setProjects(rows)
      })
      .catch(() => {
        // Unauthenticated/transient failure: fall back to the raw id, never block the shell.
        if (!cancelled) setProjects([])
      })
    return () => {
      cancelled = true
    }
  }, [projectId, projects])

  const resolved = projectId ? projects?.find((p) => p.id === projectId) : undefined
  const label = !projectId
    ? "All projects"
    : resolved?.title ?? (projects === null ? "Loading project…" : `${projectId.slice(0, 8)}…`)

  return (
    <Link
      href="/student"
      data-testid={testId}
      title="Active project context — manage projects from the Dashboard"
      className={className}
      style={{
        alignItems: "center",
        gap: 6,
        maxWidth: 260,
        padding: "4px 10px",
        borderRadius: 999,
        border: "1px solid var(--line)",
        background: "var(--bg-2)",
        fontSize: 12,
        color: "var(--ink-2)",
        whiteSpace: "nowrap",
        overflow: "hidden",
        textOverflow: "ellipsis",
      }}
    >
      <span aria-hidden style={{ color: "var(--muted)" }}>
        ◈
      </span>
      <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
        {projectId ? `Project: ${label}` : label}
      </span>
    </Link>
  )
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname()
  const active = activeNavHref(pathname)

  return (
    <nav aria-label="Student navigation" style={{ display: "grid", gap: 4 }}>
      {NAV_SECTIONS.map((section, i) => (
        <div key={section.title ?? `section-${i}`} style={{ display: "grid", gap: 2 }}>
          {section.title && (
            <div
              className="vb-eyebrow"
              style={{ padding: "14px 10px 4px", fontSize: 10 }}
            >
              {section.title}
            </div>
          )}
          {section.items.map((item) => {
            const isActive = item.href === active
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onNavigate}
                aria-current={isActive ? "page" : undefined}
                className={isActive ? undefined : "dash-nav-hover"}
                style={{
                  display: "block",
                  padding: "8px 10px",
                  borderRadius: 8,
                  fontSize: 13,
                  fontWeight: isActive ? 600 : 500,
                  color: isActive ? "#fff" : "var(--ink-2)",
                  background: isActive ? "var(--ink)" : "transparent",
                }}
              >
                {item.label}
              </Link>
            )
          })}
        </div>
      ))}
    </nav>
  )
}

function SignOutButton({ onDone, testId }: { onDone?: () => void; testId: string }) {
  const router = useRouter()
  const [signingOut, setSigningOut] = useState(false)

  const handleSignOut = async () => {
    if (signingOut) return
    setSigningOut(true)
    try {
      // The browser client owns the chunked sb-* auth cookies; signOut() clears them.
      await createSupabaseBrowserClient().auth.signOut()
    } catch {
      // Even if revocation fails, proceed to /login — the proxy re-gates from there.
    }
    onDone?.()
    router.push("/login")
    router.refresh()
  }

  return (
    <button
      type="button"
      data-testid={testId}
      onClick={handleSignOut}
      disabled={signingOut}
      className="dash-nav-hover"
      style={{
        display: "block",
        width: "100%",
        textAlign: "left",
        padding: "8px 10px",
        borderRadius: 8,
        border: "none",
        background: "transparent",
        fontSize: 13,
        fontWeight: 600,
        color: "var(--rose)",
        cursor: signingOut ? "default" : "pointer",
        opacity: signingOut ? 0.6 : 1,
      }}
    >
      {signingOut ? "Signing out…" : "Sign out"}
    </button>
  )
}

export function StudentShell({
  persona,
  children,
}: {
  persona: StudentPersona
  children: ReactNode
}) {
  const pathname = usePathname()
  const [menuOpen, setMenuOpen] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)

  // Close overlays whenever navigation happens (render-time state adjustment,
  // the React-endorsed alternative to a setState-in-effect).
  const [lastPathname, setLastPathname] = useState(pathname)
  if (lastPathname !== pathname) {
    setLastPathname(pathname)
    setMenuOpen(false)
    setDrawerOpen(false)
  }

  const crumbs = studentBreadcrumbs(pathname)

  // Keep the browser-tab title in sync with the current student page.
  useEffect(() => {
    if (isBareStudentRoute(pathname)) return
    const leaf = crumbs[crumbs.length - 1]?.label
    if (leaf) document.title = `${leaf} · VeriBridge AI`
    // crumbs derives from pathname alone
  }, [pathname]) // eslint-disable-line react-hooks/exhaustive-deps

  if (isBareStudentRoute(pathname)) {
    // Recording surfaces stay exactly as they were: zero added chrome.
    return <>{children}</>
  }

  return (
    <div data-testid="student-shell" style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <header
        className="vb-glass"
        style={{
          position: "sticky",
          top: 0,
          zIndex: 40,
          borderBottom: "1px solid var(--line)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "10px 16px",
          }}
        >
          <button
            type="button"
            data-testid="student-shell-menu-toggle"
            aria-label={drawerOpen ? "Close navigation menu" : "Open navigation menu"}
            aria-expanded={drawerOpen}
            onClick={() => setDrawerOpen((open) => !open)}
            className="md:hidden"
            style={{
              border: "1px solid var(--line)",
              background: "var(--paper)",
              borderRadius: 8,
              padding: "6px 10px",
              fontSize: 14,
              cursor: "pointer",
              color: "var(--ink)",
            }}
          >
            {drawerOpen ? "✕" : "☰"}
          </button>

          <Link
            href="/student"
            data-testid="student-shell-brand"
            style={{ display: "flex", alignItems: "center", gap: 8 }}
          >
            <span className="vb-logo" aria-hidden />
            <span style={{ fontWeight: 700, fontSize: 14, color: "var(--ink)" }}>VeriBridge</span>
            <span className="vb-eyebrow" style={{ fontSize: 10 }}>
              Student
            </span>
          </Link>

          <div style={{ flex: 1 }} />

          <Suspense fallback={null}>
            <ActiveProjectChip />
          </Suspense>

          <div style={{ position: "relative" }}>
            <button
              type="button"
              data-testid="student-shell-profile-toggle"
              aria-label="Account menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((open) => !open)}
              style={{
                width: 32,
                height: 32,
                borderRadius: 999,
                border: "1px solid var(--line-strong)",
                background: "var(--ink)",
                color: "#fff",
                fontSize: 11,
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              {persona.initials}
            </button>

            {menuOpen && (
              <>
                <button
                  type="button"
                  aria-label="Close account menu"
                  onClick={() => setMenuOpen(false)}
                  style={{
                    position: "fixed",
                    inset: 0,
                    zIndex: 40,
                    background: "transparent",
                    border: "none",
                    cursor: "default",
                  }}
                />
                <div
                  data-testid="student-shell-profile-menu"
                  className="vb-card"
                  style={{
                    position: "absolute",
                    right: 0,
                    top: "calc(100% + 8px)",
                    zIndex: 50,
                    width: 220,
                    padding: 8,
                  }}
                >
                  <div style={{ padding: "6px 10px 10px", borderBottom: "1px solid var(--line)", marginBottom: 6 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {persona.name}
                    </div>
                    {persona.email && (
                      <div style={{ fontSize: 11, color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {persona.email}
                      </div>
                    )}
                  </div>
                  {ACCOUNT_LINKS.map((item) => (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={() => setMenuOpen(false)}
                      className="dash-nav-hover"
                      style={{
                        display: "block",
                        padding: "8px 10px",
                        borderRadius: 8,
                        fontSize: 13,
                        color: "var(--ink-2)",
                      }}
                    >
                      {item.label}
                    </Link>
                  ))}
                  <div style={{ borderTop: "1px solid var(--line)", marginTop: 6, paddingTop: 6 }}>
                    <SignOutButton testId="student-shell-signout" onDone={() => setMenuOpen(false)} />
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </header>

      {drawerOpen && (
        <div
          data-testid="student-shell-mobile-drawer"
          className="md:hidden"
          style={{
            position: "fixed",
            top: 53,
            left: 0,
            right: 0,
            bottom: 0,
            zIndex: 50,
            background: "var(--paper)",
            overflowY: "auto",
            padding: 16,
            borderTop: "1px solid var(--line)",
          }}
        >
          <div style={{ marginBottom: 12 }}>
            <Suspense fallback={null}>
              <ActiveProjectChip className="inline-flex" testId="student-shell-active-project-mobile" />
            </Suspense>
          </div>
          <NavLinks onNavigate={() => setDrawerOpen(false)} />
          <div style={{ borderTop: "1px solid var(--line)", marginTop: 12, paddingTop: 12, display: "grid", gap: 2 }}>
            {ACCOUNT_LINKS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setDrawerOpen(false)}
                className="dash-nav-hover"
                style={{ display: "block", padding: "8px 10px", borderRadius: 8, fontSize: 13, color: "var(--ink-2)" }}
              >
                {item.label}
              </Link>
            ))}
            <SignOutButton testId="student-shell-signout-mobile" onDone={() => setDrawerOpen(false)} />
          </div>
        </div>
      )}

      <div style={{ display: "flex", flex: 1, alignItems: "stretch" }}>
        <aside
          data-testid="student-shell-sidebar"
          className="hidden md:block"
          style={{
            width: 224,
            flexShrink: 0,
            borderRight: "1px solid var(--line)",
            padding: "16px 12px",
          }}
        >
          <div style={{ position: "sticky", top: 69 }}>
            <NavLinks />
          </div>
        </aside>

        <main style={{ flex: 1, minWidth: 0 }}>
          <div
            data-testid="student-shell-breadcrumbs"
            style={{
              maxWidth: 900,
              margin: "0 auto",
              padding: "16px 24px 0",
              display: "flex",
              alignItems: "center",
              gap: 6,
              fontSize: 12,
              color: "var(--muted)",
            }}
          >
            {crumbs.map((crumb, i) => (
              <span key={`${crumb.label}-${i}`} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                {i > 0 && <span aria-hidden>/</span>}
                {crumb.href ? (
                  <Link href={crumb.href} style={{ color: "var(--indigo)" }}>
                    {crumb.label}
                  </Link>
                ) : (
                  <span aria-current="location" style={{ color: "var(--muted)" }}>
                    {crumb.label}
                  </span>
                )}
              </span>
            ))}
          </div>
          {children}
        </main>
      </div>
    </div>
  )
}
