"use client"

/**
 * Shared recruiter section nav — the pill row every recruiter surface
 * carries (previously hand-duplicated in Workspace / Search / Briefs).
 *
 * The active section renders as a `<span aria-current="page">` pill; every
 * other section is a link. Testids follow `${testidPrefix}-nav-${key}` so
 * the pre-existing assertions (`workspace-nav-search`, `search-nav-briefs`,
 * `briefs-nav-workspace`, …) keep working unchanged.
 */

import Link from "next/link"

import { TOKEN } from "../passport/shared"

export type RecruiterNavKey =
  | "workspace"
  | "search"
  | "briefs"
  | "pools"
  | "savedsearches"

const NAV_ITEMS: { key: RecruiterNavKey; label: string; href: string }[] = [
  { key: "workspace", label: "Saved candidates", href: "/recruiters/workspace" },
  { key: "search", label: "Search", href: "/recruiters/search" },
  { key: "briefs", label: "Hiring Briefs", href: "/recruiters/briefs" },
  { key: "pools", label: "Talent Pools", href: "/recruiters/pools" },
  { key: "savedsearches", label: "Saved Searches", href: "/recruiters/saved-searches" },
]

export function RecruiterNav({
  active,
  testidPrefix,
}: {
  active: RecruiterNavKey
  testidPrefix: string
}) {
  return (
    <nav style={{ display: "flex", gap: 8, flexWrap: "wrap" }} aria-label="Recruiter sections">
      {NAV_ITEMS.map((item) =>
        item.key === active ? (
          <span
            key={item.key}
            aria-current="page"
            data-testid={`${testidPrefix}-nav-${item.key}`}
            style={{
              padding: "7px 14px",
              borderRadius: 999,
              background: TOKEN.indigo,
              color: "#fff",
              fontSize: 12.5,
              fontWeight: 700,
            }}
          >
            {item.label}
          </span>
        ) : (
          <Link
            key={item.key}
            data-testid={`${testidPrefix}-nav-${item.key}`}
            href={item.href}
            style={{
              padding: "7px 14px",
              borderRadius: 999,
              border: `1px solid ${TOKEN.line}`,
              background: "#fff",
              color: TOKEN.muted,
              fontSize: 12.5,
              fontWeight: 600,
              textDecoration: "none",
            }}
          >
            {item.label}
          </Link>
        ),
      )}
    </nav>
  )
}
